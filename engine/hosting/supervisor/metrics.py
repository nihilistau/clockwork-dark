"""
The Supervisor's Metrics Store
==============================

SQLite (the standard library's ``sqlite3``) at
``<storage.root>/hosting/metrics.sqlite3``, in WAL mode (spec §14.10). The
SUPERVISOR IS ITS ONLY WRITER AND READER: a worker or the front door sends
``metric`` notifications (``engine/hosting/metrics_emit.py``), the
supervisor writes what it records itself (its ``lane`` and ``process``
events, its own ERROR records), and the front door asks with
``metrics.query {name, params, limit, offset}`` -- one of the closed set of
named queries below, so NO SQL CROSSES THE BUS, and every answer is a page.

WHAT IS KEPT is the closed schema of ``engine/hosting/metrics_schema.py``,
one table per kind, its columns built from ``KINDS``: timestamps, numbers,
ids, NAMEs and enum members. An event with an unknown kind, an unknown or
missing field, or a bad value is dropped and counted (``rejected``), never
stored as text (AGENTS.md rule 12: observability, never moderation).

BOUNDED, NOT ONLY BY TIME (fix round 1, I1). Rows older than
``observability.retention_days`` are pruned hourly, and:

- a REFUSAL (a ``login`` ``failed``/``limited``/``disabled``, a ``turn``
  ``refused_cap``/``refused_rate``) is not a row of its own: it is counted
  into ``refused``, one row per (minute, kind, story, outcome), so a script
  hammering ``/login`` adds at most a few rows a minute, whatever its rate;
- the file is capped at ``observability.metrics_max_mb``
  (``PRAGMA max_page_count``): a batch that would pass it makes room by
  deleting the OLDEST tenth of every table, and is written again; one that
  still does not fit is dropped and counted (``dropped_size``);
- the supervisor caps each connection's metric rate
  (``Supervisor._metric``), past which events are dropped and counted
  (``dropped_rate``).

NEVER BLOCKS A CALLER. ``record`` validates (cheap) and puts the event on a
bounded queue, dropping and counting it when full (``dropped``); ONE writer
thread inserts in batches (a failed batch is rolled back, never carried into
the next commit). So the bus's selector thread, which calls ``record`` for
every ``metric``, never waits on the disk.

NEVER BLOCKS A START (fix round 1, I2). Metrics are best effort: a CORRUPT
file (torn after a power cut, not a database, a directory in its place) is
moved aside as ``metrics.sqlite3.bad-<UTC time>`` (with its ``-wal`` and
``-shm``; the newest ``MAX_BAD_FILES`` kept) and a new one made; a file that
will not open for another reason (locked, the disk full, no permission) is
left where it is (v0.20.0 T18: it may be sound). Either way, if no store
opens, ``open`` raises ``MetricsUnavailable`` and the supervisor runs with no
store (a WARNING, a ``metrics.disabled`` audit row, the doctor's WARN row).
The full page check (``quick_check``) runs at open only on a store of at
most ``QUICK_CHECK_MAX_BYTES``.

THE NAMED QUERIES (``QUERIES``), each paged by ``limit`` (at most
``MAX_PAGE``) and ``offset``, each over the last ``params.hours`` hours (24 by
default; never more than the retention window, which is all that is kept)
where it has a window. Each AGGREGATES IN SQL (``GROUP BY``, ``COUNT``, a
percentile read as one row of an ordered subselect), so no query loads the
window's rows into Python, and the lock is held one statement at a time:

- ``turn_durations``: per story and hour, the ``ok`` turns' count and p50/p95
  duration;
- ``waits``: the admission wait (``turn.admit_wait_ms``) and each lane's wait
  and hold (``lane``, granted), count and p50/p95;
- ``outcomes``: per story and hour, turns by outcome (busy, error and the
  refusals among them);
- ``refusals``: per hour, kind, story and outcome, the refused logins and
  actions counted;
- ``usage``: per account and day, turns and sessions (created or resumed),
  and the account's active days in the window;
- ``last_login``: per account, its last successful login (no window: what is
  kept);
- ``recent_errors``: the ``error`` rows, newest first, or the one with
  ``params.ref`` (a player's reference; its traceback is in that process's
  log file on disk, which the panel never shows);
- ``recent_processes``: the ``process`` rows, newest first;
- ``metrics_rejected``: what was rejected and dropped since the supervisor
  started, the children's own drops included (their ``health`` replies).

Percentiles are nearest-rank.

LOCKS. ``_db_lock`` (a leaf in the supervisor's process) is held across one
batch's inserts, a prune, a make-room or one query statement, never while
anything else is taken; ``_counts_lock`` (a leaf) across a counter's
change. Neither is held by ``record``'s caller for any I/O.

Version: v0.2.0 [2026-10-06]
"""

from __future__ import annotations

import logging
import math
import os
import queue
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Optional

from engine.hosting.metrics_schema import KINDS, REF_PATTERN, is_process, validate

logger = logging.getLogger(__name__)

#: The store's file name under ``<storage.root>/hosting/``.
FILE_NAME = "metrics.sqlite3"

#: The most rows one query answers.
MAX_PAGE = 200

#: The events waiting for the writer, at most.
MAX_QUEUE = 10000

#: The most events one batch inserts.
BATCH = 256

#: How often the writer prunes, in seconds (spec §14.10: hourly).
PRUNE_SECONDS = 3600.0

#: What the ``-wal`` file is cut back to after a checkpoint (beside the cap).
WAL_LIMIT_BYTES = 4 * 1024 * 1024

#: The share of every table's oldest rows deleted to make room at the size cap.
MAKE_ROOM_FRACTION = 0.1

#: A query's default window, in hours, and the longest it may ask for (the
#: retention window bounds it as well).
DEFAULT_HOURS = 24
MAX_HOURS = 3650 * 24

#: Error codes a query is refused with.
UNKNOWN_QUERY = "unknown_query"
BAD_PARAMS = "bad_params"

#: Every named query there is (the only ones ``metrics.query`` answers).
QUERIES = (
    "turn_durations",
    "waits",
    "outcomes",
    "refusals",
    "usage",
    "last_login",
    "recent_errors",
    "recent_processes",
    "metrics_rejected",
)

#: The parameters a query may take: the window, and (``recent_errors`` only)
#: one reference.
PARAM_KEYS = frozenset({"hours", "ref"})

#: The refusals counted per minute rather than kept one row each: kind ->
#: outcomes (members of the schema's enums).
REFUSALS: dict[str, frozenset[str]] = {
    "login": frozenset({"failed", "limited", "disabled"}),
    "turn": frozenset({"refused_cap", "refused_rate"}),
}

#: The refusal counters' table (its columns fixed here, never from an event).
REFUSED_TABLE = "refused"

#: What the moved-aside file's name gains.
BAD_SUFFIX = ".bad-"

#: Moved-aside stores kept; the oldest beyond this are deleted (v0.20.0 T18).
MAX_BAD_FILES = 3

#: The largest store whose every page is read at open (``PRAGMA quick_check``);
#: a larger one is not read whole on every start (v0.20.0 T18).
QUICK_CHECK_MAX_BYTES = 64 * 1024 * 1024

#: SQLite's result codes for a file that is damaged or is not a database.
_CORRUPT_CODES = frozenset({getattr(sqlite3, "SQLITE_CORRUPT", 11), getattr(sqlite3, "SQLITE_NOTADB", 26)})

#: The same, read from the message where the code is not carried.
_CORRUPT_WORDS = ("malformed", "not a database", "quick_check failed", "file is encrypted")


def corrupt(exc: BaseException) -> bool:
    """
    Whether ``exc`` says the store's FILE is damaged (moved aside), not that
    it is locked, the disk is full or it may not be opened (left alone).
    """
    if not isinstance(exc, sqlite3.DatabaseError):
        return False
    code = getattr(exc, "sqlite_errorcode", None)
    if code is not None and (int(code) & 0xFF) in _CORRUPT_CODES:
        return True
    text = str(exc).lower()
    return any(word in text for word in _CORRUPT_WORDS)

_DAY = 86400.0
_HOUR = 3600.0
_MINUTE = 60.0


class MetricsQueryError(ValueError):
    """A query refused (``code``: ``unknown_query``, ``bad_params``)."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class MetricsUnavailable(RuntimeError):
    """The store could not be opened, even fresh: run without one."""


class _Flush:
    """A marker the writer sets once everything queued before it is written."""

    def __init__(self) -> None:
        self.done = threading.Event()


def percentile(values: list[float], fraction: float) -> float:
    """The nearest-rank percentile of ``values`` (sorted here); 0.0 for none."""
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(1, math.ceil(fraction * len(ordered)))
    return round(float(ordered[min(rank, len(ordered)) - 1]), 1)


def _rank(count: int, fraction: float) -> int:
    """The 0-based offset of the nearest-rank ``fraction`` of ``count`` sorted values."""
    return max(1, math.ceil(fraction * count)) - 1


def _is_full(exc: BaseException) -> bool:
    code = getattr(exc, "sqlite_errorcode", None)
    return code == getattr(sqlite3, "SQLITE_FULL", 13) or "full" in str(exc).lower()


def _private(path: Path) -> None:
    """0600 on POSIX (fix round 1, M2), as ``users.json`` and the audit log are."""
    if os.name != "posix":
        return
    for each in (path, Path(f"{path}-wal"), Path(f"{path}-shm")):
        try:
            os.chmod(each, 0o600)
        except OSError:
            pass


class MetricsStore:
    """The supervisor's metrics (see the module docstring)."""

    def __init__(
        self,
        path: Path,
        *,
        retention_days: int,
        stories: Iterable[str] = (),
        clock: Callable[[], float] = time.time,
        maxsize: int = MAX_QUEUE,
        max_mb: int = 512,
    ) -> None:
        self.path = Path(path)
        self.retention_days = int(retention_days)
        self.max_mb = int(max_mb)
        self.stories = frozenset(stories)
        self.clock = clock
        self._queue: "queue.Queue[Any]" = queue.Queue(maxsize=max(1, int(maxsize)))
        #: A leaf: the connection, across one batch, a prune, a make-room or a statement.
        self._db_lock = threading.Lock()
        #: A leaf: the counters.
        self._counts_lock = threading.Lock()
        self._db: Optional[sqlite3.Connection] = None
        self._thread: Optional[threading.Thread] = None
        self.rejected = 0
        self.dropped = 0
        self.dropped_rate = 0
        self.dropped_size = 0
        #: Each child's own dropped count, as its last ``health`` reply said.
        self.children: dict[str, int] = {}
        #: Where a file that would not open was moved, if one was.
        self.moved_aside: Optional[Path] = None

    # -- lifecycle ----------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        """Open the file and make its tables; closes the connection on any failure."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(str(self.path), check_same_thread=False)
        try:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA synchronous=NORMAL")
            # The -wal file is checkpointed every 1000 pages (SQLite's
            # default) and cut back to this after each checkpoint.
            db.execute(f"PRAGMA journal_size_limit = {WAL_LIMIT_BYTES}")
            # A file that is not a database fails the line above. The page
            # check reads the WHOLE file, so it runs only on a store small
            # enough to read at once (v0.20.0 T18): a large store is checked
            # by its use, and a write that finds it malformed is rolled back.
            size = self.path.stat().st_size if self.path.is_file() else 0
            if size <= QUICK_CHECK_MAX_BYTES:
                check = db.execute("PRAGMA quick_check(1)").fetchone()
                if not check or str(check[0]).lower() != "ok":
                    raise sqlite3.DatabaseError("quick_check failed")
            for kind, fields in KINDS.items():
                # Names from the schema's own constants, never from an event.
                columns = ", ".join(f"{name} {spec.sql}" for name, spec in fields.items())
                db.execute(f"CREATE TABLE IF NOT EXISTS {kind} (id INTEGER PRIMARY KEY, {columns})")
                db.execute(f"CREATE INDEX IF NOT EXISTS {kind}_ts ON {kind} (ts)")
            # The admin's "find an error by its reference" (v0.20.0 T18).
            db.execute("CREATE INDEX IF NOT EXISTS error_ref ON error (ref)")
            db.execute(
                f"CREATE TABLE IF NOT EXISTS {REFUSED_TABLE} (minute REAL NOT NULL, kind TEXT NOT NULL, "
                "story TEXT NOT NULL, outcome TEXT NOT NULL, count INTEGER NOT NULL, "
                "PRIMARY KEY (minute, kind, story, outcome))"
            )
            page = int(db.execute("PRAGMA page_size").fetchone()[0]) or 4096
            db.execute(f"PRAGMA max_page_count = {max(64, (self.max_mb * 1024 * 1024) // page)}")
            db.commit()
        except BaseException:
            try:
                db.close()
            except sqlite3.Error:
                pass
            raise
        _private(self.path)
        return db

    def _move_aside(self) -> Path:
        """The file (and its ``-wal``, ``-shm``) renamed ``<name>.bad-<UTC>``; the new name."""
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        target = self.path.with_name(f"{self.path.name}{BAD_SUFFIX}{stamp}")
        for suffix in ("", "-wal", "-shm"):
            source = Path(f"{self.path}{suffix}")
            if source.exists():
                os.replace(source, Path(f"{target}{suffix}"))
        return target

    def _prune_bad(self) -> None:
        """Keep the newest ``MAX_BAD_FILES`` moved-aside stores (each with its ``-wal``/``-shm``)."""
        prefix = f"{self.path.name}{BAD_SUFFIX}"
        moved = sorted(
            p for p in self.path.parent.glob(f"{prefix}*")
            if not p.name.endswith(("-wal", "-shm"))
        )
        for old in moved[: max(0, len(moved) - MAX_BAD_FILES)]:
            for suffix in ("", "-wal", "-shm"):
                try:
                    Path(f"{old}{suffix}").unlink(missing_ok=True)
                except OSError:
                    pass

    def open(self) -> "MetricsStore":
        """
        Open (or make) the file, prune once, and start the writer. A file that
        is CORRUPT (``corrupt``: not a database, malformed, a failed
        ``quick_check``, a directory in its place) is moved aside and a fresh
        one made, once (fix round 1, I2), keeping at most ``MAX_BAD_FILES``
        such files (v0.20.0 T18). Any other failure -- the file locked, the
        disk full, no permission -- moves nothing: the file may be sound.

        Raises:
            MetricsUnavailable: the file will not open and is not corrupt, or
                not even a fresh file opens.
        """
        try:
            db = self._connect()
        except (sqlite3.Error, OSError) as exc:
            if not (self.path.is_dir() or corrupt(exc)):
                raise MetricsUnavailable(type(exc).__name__) from None
            try:
                self.moved_aside = self._move_aside()
                logger.warning(
                    "[metrics] The store is corrupt (%s); moved aside to %s, a new one made (operation=open)",
                    type(exc).__name__,
                    self.moved_aside.name,
                )
                self._prune_bad()
                db = self._connect()
            except (sqlite3.Error, OSError) as again:
                raise MetricsUnavailable(type(again).__name__) from None
        self._db = db
        self.prune()
        thread = threading.Thread(target=self._write_loop, name="metrics-writer", daemon=True)
        self._thread = thread
        thread.start()
        logger.info(
            "[metrics] Store open (operation=open, path=%s, retention_days=%d, max_mb=%d)",
            self.path,
            self.retention_days,
            self.max_mb,
        )
        return self

    def close(self, timeout: float = 5.0) -> None:
        """Write what is queued, stop the writer and close the file, within ``timeout``."""
        thread = self._thread
        if thread is not None:
            try:
                self._queue.put(None, timeout=max(0.0, timeout))
            except queue.Full:
                pass
            thread.join(max(0.0, timeout))
            self._thread = None
        with self._db_lock:
            db, self._db = self._db, None
            if db is not None:
                db.close()

    # -- counting -----------------------------------------------------------------------

    def count(self, what: str, number: int = 1) -> None:
        """Add ``number`` to the counter ``what`` (``rejected``, ``dropped``, ``dropped_rate``, ``dropped_size``)."""
        with self._counts_lock:
            setattr(self, what, getattr(self, what) + int(number))

    def child_dropped(self, process: str, number: Any) -> None:
        """What a child said it dropped (its ``health`` reply); ignored unless a count of a known process."""
        if not is_process(process, self.stories or None):
            return
        if not isinstance(number, int) or isinstance(number, bool) or number < 0:
            return
        with self._counts_lock:
            self.children[process] = number

    # -- recording (any thread: never blocks) ---------------------------------------

    def record(self, event: Mapping[str, Any]) -> bool:
        """
        Validate ``event`` and queue it for the writer. False when it was
        rejected (counted) or dropped because the queue is full (counted).
        Never blocks and never raises.
        """
        clean = validate(event, stories=self.stories or None)
        if clean is None:
            self.count("rejected")
            return False
        try:
            self._queue.put_nowait(clean)
        except queue.Full:
            self.count("dropped")
            return False
        return True

    def flush(self, timeout: float = 5.0) -> bool:
        """Wait until everything queued so far is written (tests, and the shutdown)."""
        marker = _Flush()
        try:
            self._queue.put(marker, timeout=timeout)
        except queue.Full:
            return False
        return marker.done.wait(timeout)

    # -- the writer thread --------------------------------------------------------------

    def _write_loop(self) -> None:
        next_prune = time.monotonic() + PRUNE_SECONDS
        while True:
            try:
                item = self._queue.get(timeout=max(0.1, next_prune - time.monotonic()))
            except queue.Empty:
                item = _TICK
            batch = [item]
            while len(batch) < BATCH:
                try:
                    batch.append(self._queue.get_nowait())
                except queue.Empty:
                    break
            rows = [i for i in batch if isinstance(i, dict)]
            if rows:
                self._insert(rows)
            if time.monotonic() >= next_prune:
                self.prune()
                next_prune = time.monotonic() + PRUNE_SECONDS
            for marker in batch:
                if isinstance(marker, _Flush):
                    marker.done.set()
            if any(i is None for i in batch):
                return

    @staticmethod
    def _rollback(db: sqlite3.Connection) -> None:
        try:
            db.rollback()
        except sqlite3.Error:
            pass

    def _write(self, db: sqlite3.Connection, rows: list[dict[str, Any]]) -> None:
        for row in rows:
            kind = row["kind"]
            if row.get("outcome") in REFUSALS.get(kind, ()):
                # Counted per minute, one row per (minute, kind, story, outcome).
                db.execute(
                    f"INSERT INTO {REFUSED_TABLE} (minute, kind, story, outcome, count) VALUES (?, ?, ?, ?, 1) "
                    "ON CONFLICT (minute, kind, story, outcome) DO UPDATE SET count = count + 1",
                    (math.floor(row["ts"] / _MINUTE) * _MINUTE, kind, row.get("story") or "", row["outcome"]),
                )
                continue
            names = list(KINDS[kind])
            db.execute(
                f"INSERT INTO {kind} ({', '.join(names)}) VALUES ({', '.join('?' for _ in names)})",
                [row[name] for name in names],
            )
        db.commit()

    def _insert(self, rows: list[dict[str, Any]]) -> None:
        with self._db_lock:
            db = self._db
            if db is None:
                return
            try:
                self._write(db, rows)
                return
            except sqlite3.Error as exc:
                # Rolled back (fix round 1, M1): never carried into the next commit.
                self._rollback(db)
                if not _is_full(exc):
                    # A WARNING, never an ERROR: an ERROR would be recorded as
                    # a metric, which would fail again.
                    logger.warning(
                        "[metrics] A batch was not written (operation=insert, rows=%d, error=%s)",
                        len(rows),
                        type(exc).__name__,
                    )
                    self.count("dropped_size", len(rows))
                    return
            # At the size cap: make room, oldest first, and try once more.
            self._make_room(db)
            try:
                self._write(db, rows)
            except sqlite3.Error as exc:
                self._rollback(db)
                logger.warning(
                    "[metrics] A batch was dropped at the size cap (operation=insert, rows=%d, error=%s)",
                    len(rows),
                    type(exc).__name__,
                )
                self.count("dropped_size", len(rows))

    def _make_room(self, db: sqlite3.Connection) -> int:
        """Delete the oldest ``MAKE_ROOM_FRACTION`` of every table (the caller holds ``_db_lock``); how many."""
        removed = 0
        try:
            for kind in KINDS:
                total = int(db.execute(f"SELECT COUNT(*) FROM {kind}").fetchone()[0])
                if total:
                    take = max(1, int(total * MAKE_ROOM_FRACTION))
                    removed += db.execute(
                        f"DELETE FROM {kind} WHERE id IN (SELECT id FROM {kind} ORDER BY ts, id LIMIT ?)", (take,)
                    ).rowcount
            total = int(db.execute(f"SELECT COUNT(*) FROM {REFUSED_TABLE}").fetchone()[0])
            if total:
                take = max(1, int(total * MAKE_ROOM_FRACTION))
                removed += db.execute(
                    f"DELETE FROM {REFUSED_TABLE} WHERE rowid IN "
                    f"(SELECT rowid FROM {REFUSED_TABLE} ORDER BY minute LIMIT ?)",
                    (take,),
                ).rowcount
            db.commit()
        except sqlite3.Error as exc:
            self._rollback(db)
            logger.warning("[metrics] Making room failed (operation=make_room, error=%s)", type(exc).__name__)
            return 0
        logger.info("[metrics] At the size cap: the oldest rows deleted (operation=make_room, rows=%d)", removed)
        return removed

    def prune(self, now: Optional[float] = None) -> int:
        """Delete every row older than ``retention_days`` (``now``: the clock's by default); how many."""
        cutoff = (self.clock() if now is None else float(now)) - self.retention_days * _DAY
        removed = 0
        with self._db_lock:
            db = self._db
            if db is None:
                return 0
            try:
                for kind in KINDS:
                    removed += db.execute(f"DELETE FROM {kind} WHERE ts < ?", (cutoff,)).rowcount
                removed += db.execute(f"DELETE FROM {REFUSED_TABLE} WHERE minute < ?", (cutoff,)).rowcount
                db.commit()
            except sqlite3.Error as exc:
                self._rollback(db)
                logger.warning("[metrics] Prune failed (operation=prune, error=%s)", type(exc).__name__)
                return 0
        if removed:
            logger.info("[metrics] Pruned rows past the retention window (operation=prune, rows=%d)", removed)
        return removed

    def size(self) -> int:
        """The file's size in bytes, its ``-wal`` included (0 when absent)."""
        total = 0
        for suffix in ("", "-wal"):
            try:
                total += Path(f"{self.path}{suffix}").stat().st_size
            except OSError:
                pass
        return total

    # -- the named queries ----------------------------------------------------------------

    def query(self, name: Any, params: Any = None, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        """
        One named query, a page of it: ``{"rows": [...], "total": n}``.

        Raises:
            MetricsQueryError: ``unknown_query`` (a name not in ``QUERIES``:
                SQL included), ``bad_params``.
        """
        if not isinstance(name, str) or name not in QUERIES:
            raise MetricsQueryError(UNKNOWN_QUERY)
        given = dict(params or {}) if isinstance(params, Mapping) or params is None else None
        if given is None or set(given) - PARAM_KEYS:
            raise MetricsQueryError(BAD_PARAMS)
        hours = given.get("hours", DEFAULT_HOURS)
        if not isinstance(hours, int) or isinstance(hours, bool) or not 1 <= hours <= MAX_HOURS:
            raise MetricsQueryError(BAD_PARAMS)
        ref = given.get("ref")
        if ref is not None and (name != "recent_errors" or not isinstance(ref, str) or not REF_PATTERN.fullmatch(ref)):
            raise MetricsQueryError(BAD_PARAMS)
        # Nothing older than the retention window is kept anyway.
        hours = min(hours, max(1, self.retention_days * 24))
        if not isinstance(limit, int) or isinstance(limit, bool) or not 0 <= limit <= MAX_PAGE:
            raise MetricsQueryError(BAD_PARAMS)
        if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
            raise MetricsQueryError(BAD_PARAMS)
        since = self.clock() - hours * _HOUR
        if name == "recent_errors":
            rows, total = self._recent("error", limit, offset, ref=ref)
        else:
            rows, total = getattr(self, f"_q_{name}")(since, limit, offset)
        return {"rows": rows, "total": total}

    def _select(self, sql: str, args: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
        """One statement's rows (``_db_lock`` held for it alone)."""
        with self._db_lock:
            db = self._db
            if db is None:
                return []
            return list(db.execute(sql, args).fetchall())

    def _one(self, sql: str, args: tuple[Any, ...] = ()) -> Any:
        found = self._select(sql, args)
        return found[0][0] if found and found[0] else None

    def _pct(self, column: str, table: str, where: str, args: tuple[Any, ...], count: int, fraction: float) -> float:
        """The nearest-rank percentile of ``column``, one row read from SQL's own ordering."""
        if count <= 0:
            return 0.0
        value = self._one(
            f"SELECT {column} FROM {table} WHERE {where} ORDER BY {column} LIMIT 1 OFFSET ?",
            args + (_rank(count, fraction),),
        )
        return round(float(value or 0.0), 1)

    @staticmethod
    def _page(rows: list[dict[str, Any]], limit: int, offset: int) -> tuple[list[dict[str, Any]], int]:
        return rows[offset : offset + limit], len(rows)

    def _q_turn_durations(self, since: float, limit: int, offset: int) -> tuple[list[dict[str, Any]], int]:
        where = "outcome = 'ok' AND ts >= ?"
        total = int(
            self._one(f"SELECT COUNT(*) FROM (SELECT 1 FROM turn WHERE {where} GROUP BY story, CAST(ts / 3600 AS INTEGER))", (since,))
            or 0
        )
        groups = self._select(
            f"SELECT story, CAST(ts / 3600 AS INTEGER) AS h, COUNT(*) FROM turn WHERE {where} "
            "GROUP BY story, h ORDER BY h DESC, story LIMIT ? OFFSET ?",
            (since, limit, offset),
        )
        rows = []
        for story, hour, count in groups:
            low = max(since, float(hour) * _HOUR)
            within = "outcome = 'ok' AND story = ? AND ts >= ? AND ts < ?"
            args = (story, low, (float(hour) + 1) * _HOUR)
            rows.append(
                {
                    "story": str(story),
                    "hour": float(hour) * _HOUR,
                    "turns": int(count),
                    "p50_ms": self._pct("duration_ms", "turn", within, args, int(count), 0.5),
                    "p95_ms": self._pct("duration_ms", "turn", within, args, int(count), 0.95),
                }
            )
        return rows, total

    def _q_waits(self, since: float, limit: int, offset: int) -> tuple[list[dict[str, Any]], int]:
        rows = []
        where = "outcome IN ('ok', 'busy', 'error') AND ts >= ?"
        count = int(self._one(f"SELECT COUNT(*) FROM turn WHERE {where}", (since,)) or 0)
        rows.append(
            {
                "source": "admission",
                "count": count,
                "p50_ms": self._pct("admit_wait_ms", "turn", where, (since,), count, 0.5),
                "p95_ms": self._pct("admit_wait_ms", "turn", where, (since,), count, 0.95),
                "hold_p50_ms": 0.0,
                "hold_p95_ms": 0.0,
            }
        )
        for lane, lane_count in self._select(
            "SELECT lane, COUNT(*) FROM lane WHERE outcome = 'granted' AND ts >= ? GROUP BY lane ORDER BY lane", (since,)
        ):
            within = "outcome = 'granted' AND lane = ? AND ts >= ?"
            args = (lane, since)
            n = int(lane_count)
            rows.append(
                {
                    "source": str(lane),
                    "count": n,
                    "p50_ms": self._pct("wait_ms", "lane", within, args, n, 0.5),
                    "p95_ms": self._pct("wait_ms", "lane", within, args, n, 0.95),
                    "hold_p50_ms": self._pct("hold_ms", "lane", within, args, n, 0.5),
                    "hold_p95_ms": self._pct("hold_ms", "lane", within, args, n, 0.95),
                }
            )
        return self._page(rows, limit, offset)

    def _q_outcomes(self, since: float, limit: int, offset: int) -> tuple[list[dict[str, Any]], int]:
        outcomes = KINDS["turn"]["outcome"].values
        groups: dict[tuple[str, int], dict[str, int]] = {}
        found = self._select(
            "SELECT story, CAST(ts / 3600 AS INTEGER) AS h, outcome, COUNT(*) FROM turn WHERE ts >= ? "
            "GROUP BY story, h, outcome",
            (since,),
        ) + self._select(
            f"SELECT story, CAST(minute / 3600 AS INTEGER) AS h, outcome, SUM(count) FROM {REFUSED_TABLE} "
            "WHERE kind = 'turn' AND minute >= ? GROUP BY story, h, outcome",
            (math.floor(since / _MINUTE) * _MINUTE,),
        )
        for story, hour, outcome, count in found:
            counts = groups.setdefault((str(story), int(hour)), {o: 0 for o in outcomes})
            if outcome in counts:
                counts[outcome] += int(count or 0)
        rows = [{"story": story, "hour": hour * _HOUR, **counts} for (story, hour), counts in groups.items()]
        rows.sort(key=lambda r: (-r["hour"], r["story"]))
        return self._page(rows, limit, offset)

    def _q_refusals(self, since: float, limit: int, offset: int) -> tuple[list[dict[str, Any]], int]:
        start = math.floor(since / _MINUTE) * _MINUTE
        grouping = f"FROM {REFUSED_TABLE} WHERE minute >= ? GROUP BY CAST(minute / 3600 AS INTEGER), kind, story, outcome"
        total = int(self._one(f"SELECT COUNT(*) FROM (SELECT 1 {grouping})", (start,)) or 0)
        found = self._select(
            f"SELECT CAST(minute / 3600 AS INTEGER) AS h, kind, story, outcome, SUM(count) {grouping} "
            "ORDER BY h DESC, kind, story, outcome LIMIT ? OFFSET ?",
            (start, limit, offset),
        )
        rows = [
            {"hour": float(h) * _HOUR, "kind": str(kind), "story": str(story), "outcome": str(outcome), "count": int(n or 0)}
            for h, kind, story, outcome, n in found
        ]
        return rows, total

    def _q_usage(self, since: float, limit: int, offset: int) -> tuple[list[dict[str, Any]], int]:
        days: dict[tuple[str, int], dict[str, int]] = {}
        for account, day, count in self._select(
            "SELECT account, CAST(ts / 86400 AS INTEGER) AS d, COUNT(*) FROM turn "
            "WHERE outcome = 'ok' AND account IS NOT NULL AND ts >= ? GROUP BY account, d",
            (since,),
        ):
            days.setdefault((str(account), int(day)), {"turns": 0, "sessions": 0})["turns"] += int(count)
        for account, day, count in self._select(
            "SELECT account, CAST(ts / 86400 AS INTEGER) AS d, COUNT(*) FROM session "
            "WHERE event IN ('created', 'resumed') AND account IS NOT NULL AND ts >= ? GROUP BY account, d",
            (since,),
        ):
            days.setdefault((str(account), int(day)), {"turns": 0, "sessions": 0})["sessions"] += int(count)
        active: dict[str, int] = {}
        for account, _day in days:
            active[account] = active.get(account, 0) + 1
        rows = [
            {"account": account, "day": day * _DAY, **counts, "active_days": active[account]}
            for (account, day), counts in days.items()
        ]
        rows.sort(key=lambda r: (-r["day"], r["account"]))
        return self._page(rows, limit, offset)

    def _q_last_login(self, _since: float, limit: int, offset: int) -> tuple[list[dict[str, Any]], int]:
        where = "FROM login WHERE account IS NOT NULL AND outcome IN ('ok', 'must_change')"
        total = int(self._one(f"SELECT COUNT(DISTINCT account) {where}") or 0)
        found = self._select(
            f"SELECT account, MAX(ts) {where} GROUP BY account ORDER BY MAX(ts) DESC, account LIMIT ? OFFSET ?",
            (limit, offset),
        )
        return [{"account": str(account), "ts": float(ts)} for account, ts in found], total

    def _recent(self, kind: str, limit: int, offset: int, *, ref: Optional[str] = None) -> tuple[list[dict[str, Any]], int]:
        names = list(KINDS[kind])
        where, args = ("WHERE ref = ?", (ref,)) if ref is not None else ("", ())
        total = int(self._one(f"SELECT COUNT(*) FROM {kind} {where}", args) or 0)
        found = self._select(
            f"SELECT {', '.join(names)} FROM {kind} {where} ORDER BY ts DESC, id DESC LIMIT ? OFFSET ?",
            args + (limit, offset),
        )
        return [dict(zip(names, row)) for row in found], total

    def _q_recent_processes(self, _since: float, limit: int, offset: int) -> tuple[list[dict[str, Any]], int]:
        return self._recent("process", limit, offset)

    def _q_metrics_rejected(self, _since: float, limit: int, offset: int) -> tuple[list[dict[str, Any]], int]:
        with self._counts_lock:
            row = {
                "rejected": self.rejected,
                "dropped": self.dropped,
                "dropped_rate": self.dropped_rate,
                "dropped_size": self.dropped_size,
                "children": dict(sorted(self.children.items())),
            }
        return self._page([row], limit, offset)


#: The writer's wake-up with nothing queued (time to prune).
_TICK = object()


__all__ = [
    "BAD_PARAMS",
    "BAD_SUFFIX",
    "FILE_NAME",
    "MAX_PAGE",
    "MetricsQueryError",
    "MetricsStore",
    "MetricsUnavailable",
    "PRUNE_SECONDS",
    "QUERIES",
    "REFUSALS",
    "REFUSED_TABLE",
    "UNKNOWN_QUERY",
    "percentile",
]
