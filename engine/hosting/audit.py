"""
Hosted Mode: the Audit Log
==========================

``<storage.root>/hosting/audit.jsonl``: one JSON object per line, appended by
THIS MODULE ONLY (spec §14.11). Its callers are the admin panel (the front
door), ``scripts/users.py`` (actor ``cli``) and the supervisor (actor
``supervisor``: a hold-down; a model apply's rollback, and its outcome row
for the admin who asked, v0.20.0 T16).

A CLOSED FIELD SET (``FIELDS``), every row all of them:

- ``ts``: seconds since the epoch;
- ``actor``: an account id, ``cli`` or ``supervisor``; ``actor_name`` the
  account's name (``cli`` or ``supervisor`` for those two);
- ``address``: the front door's resolved client address ("" for the others);
- ``action``: one of ``ACTIONS``;
- ``target``: an account id, a story slug, a session reference or dotted
  config keys ("" when the action has none yet, as a create before its id is
  minted: its outcome row carries the new id);
- ``detail``: the options chosen (``purge: true``, ``apply_anyway: true``, a
  new account's name; for ``llm.apply`` each key's old and new value, the
  allowlist holding no secret, spec §14.9). Strings, numbers, booleans and
  null, one level of nesting at most;
- ``result``: one of ``RESULTS``;
- ``ref``: 8 hex digits, the same on an action's ``started`` row and its
  outcome row.

NEVER a password, a generated password, a hash, a key's value, or play text:
``check_row`` refuses a row with any field outside the set, an action or
result outside its enum, or a value that is not of its kind, so nothing can be
hung off a row that nobody reviewed. (Rule 12: the log records who
administered the service; it rates, filters and moderates nothing.)

NO ACTION WITHOUT ITS ROW (spec §14.11), one helper every caller uses,
``audited``: it appends the action's ``started`` row BEFORE the action runs,
and if that append fails (a full disk, a lock it cannot take) it raises
``AuditUnavailable`` and the action never starts -- the caller refuses with
an error page and nothing changes. The outcome (``ok``, ``refused`` or
``error``) is appended after, with the same ``ref``. A request refused
before it starts (a failed validation, a guard) is one ``refused`` row
(``refused``). So the log can hold a ``started`` with no outcome (the process
died mid-action), but never an action with no row.

ONE WRITER ACROSS PROCESSES: each append holds an operating-system lock on
``audit.jsonl.lock`` beside the file (``accounts.try_lock``: ``flock`` on
POSIX, ``msvcrt.locking`` on Windows), its own lock, not the accounts'.
It is the users.json mechanism as v0.20.0 T7 fix round 1 left it (spec
§14.11, amended in T14 fix round 1): an ``O_CREAT | O_EXCL`` lock file left
by a killed holder can be broken only by a remover racing the next holder,
while the system frees a lock its holder's death leaves behind. Each line is one ``os.write`` on an ``O_APPEND`` handle,
flushed to disk (``fsync``) before the append returns, so a line lands whole.

IT ROTATES BY SIZE (fix round 1, M4): an append that would take the file
past ``hosting.observability.audit_max_mb`` first renames it to
``audit.jsonl.1`` (the older ones shifting up), under the same lock, and at
most ``hosting.observability.audit_keep`` rotated files are kept, the oldest
deleted. A started row and its outcome may then sit in two files; the reader
reads across them. ``read_recent`` answers the newest rows, a page at a
time, filtered by action or actor, reading only a bounded tail backwards
(``AUDIT_MAX_ROWS``, ``MAX_SCAN_BYTES``). Archiving the rotated files
elsewhere is the operator's (docs/HOSTING.md § The audit log).

Version: v0.2.0 [2026-10-05]
"""

from __future__ import annotations

import json
import logging
import os
import re
import secrets
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, Optional

from engine.hosting.accounts import ID_RE, open_private, secure_dir, try_lock, unlock

logger = logging.getLogger(__name__)

#: The file's name under ``<storage.root>/hosting/``.
AUDIT_FILE = "audit.jsonl"

#: Its lock file, beside it.
AUDIT_LOCK = "audit.jsonl.lock"

#: How long an append waits for the lock before the action is refused.
LOCK_WAIT_SECONDS = 5.0

#: Every row's fields, in this order (spec §14.11). Closed.
FIELDS = ("ts", "actor", "actor_name", "address", "action", "target", "detail", "result", "ref")

#: Every action a row may record (spec §14.11). Closed.
ACTIONS = frozenset(
    {
        "account.create",
        "account.disable",
        "account.enable",
        "account.reset_password",
        "account.delete",
        "account.set_admin",
        "account.passwd",
        "session.end",
        "story.start",
        "story.stop",
        "story.restart",
        "story.held_down",
        "llm.apply",
        "llm.rollback",
        "admin.reauth",
        "admin.reauth_failed",
        # v0.20.0 T17 fix round 1: the supervisor started without its
        # metrics store (it would not open, even fresh).
        "metrics.disabled",
    }
)

#: Every result a row may carry. ``started`` is written before an action runs.
STARTED = "started"
OK = "ok"
REFUSED = "refused"
ERROR = "error"
RESULTS = frozenset({STARTED, OK, REFUSED, ERROR})

#: The actors that are not accounts.
CLI = "cli"
SUPERVISOR = "supervisor"

#: A row's reference: 8 hex digits.
REF_RE = re.compile(r"[0-9a-f]{8}")

#: The longest text a row's string field (or a detail value) may hold.
MAX_TEXT = 200

#: What a caller says when the started row could not be written.
UNAVAILABLE = "The audit log cannot be written, so nothing was changed. Tell the operator."


class AuditUnavailable(RuntimeError):
    """The row could not be appended; an action that needed it must not run."""


class AuditRowError(ValueError):
    """A row outside the closed field set, an enum, or a value's kind."""


@dataclass(frozen=True)
class Actor:
    """Who acted: an account (its id and name, and the client's address), ``cli`` or ``supervisor``."""

    id: str
    name: str
    address: str = ""


#: The command line's actor (``scripts/users.py``).
CLI_ACTOR = Actor(CLI, CLI)

#: The supervisor's actor.
SUPERVISOR_ACTOR = Actor(SUPERVISOR, SUPERVISOR)


def new_ref() -> str:
    """A fresh row reference (``secrets``)."""
    return secrets.token_hex(4)


def _text(name: str, value: Any) -> str:
    if not isinstance(value, str):
        raise AuditRowError(f"{name} must be a string")
    if len(value) > MAX_TEXT:
        raise AuditRowError(f"{name} is longer than {MAX_TEXT} characters")
    return value


def _scalar(name: str, value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return _text(name, value)


def _detail(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise AuditRowError("detail must be a mapping")
    out: dict[str, Any] = {}
    for key, inner in value.items():
        name = _text("a detail key", key)
        if isinstance(inner, dict):
            out[name] = {_text("a detail key", k): _scalar(f"detail.{name}.{k}", v) for k, v in inner.items()}
        else:
            out[name] = _scalar(f"detail.{name}", inner)
    return out


def check_row(row: Any) -> dict[str, Any]:
    """
    ``row`` with its fields in ``FIELDS`` order, or ``AuditRowError``: a
    field missing or outside the set, an action or result outside its enum,
    an actor that is neither an account id nor ``cli``/``supervisor``, a
    reference that is not 8 hex digits, or a value not of its kind.
    """
    if not isinstance(row, dict) or set(row) != set(FIELDS):
        raise AuditRowError(f"a row has exactly the fields {', '.join(FIELDS)}")
    if row["action"] not in ACTIONS:
        raise AuditRowError("not an audited action")
    if row["result"] not in RESULTS:
        raise AuditRowError("not an audit result")
    actor = _text("actor", row["actor"])
    if actor not in (CLI, SUPERVISOR) and not ID_RE.fullmatch(actor):
        raise AuditRowError("the actor is an account id, cli or supervisor")
    if not isinstance(row["ref"], str) or not REF_RE.fullmatch(row["ref"]):
        raise AuditRowError("the reference is 8 hex digits")
    if isinstance(row["ts"], bool) or not isinstance(row["ts"], (int, float)):
        raise AuditRowError("ts is a number")
    return {
        "ts": float(row["ts"]),
        "actor": actor,
        "actor_name": _text("actor_name", row["actor_name"]),
        "address": _text("address", row["address"]),
        "action": row["action"],
        "target": _text("target", row["target"]),
        "detail": _detail(row["detail"]),
        "result": row["result"],
        "ref": row["ref"],
    }


def audit_path(directory: Optional[Path] = None) -> Path:
    """``<storage.root>/hosting/audit.jsonl`` (or ``directory``'s)."""
    if directory is None:
        from engine.persistence.storage import hosting_dir

        directory = hosting_dir()
    return Path(directory) / AUDIT_FILE


#: The rotation's defaults, when the config gives none (``config/default.yaml``
#: ships ``hosting.observability.audit_max_mb`` and ``audit_keep``).
DEFAULT_MAX_MB = 20
DEFAULT_KEEP = 10

#: How many times a rename blocked by a reader (Windows) is retried.
_RENAME_ATTEMPTS = 20


def rotation() -> tuple[int, int]:
    """``(bytes before a rotation, rotated files kept)``, from the config."""
    from engine.config import get_config

    cfg = get_config()
    values = []
    for key, default in (("audit_max_mb", DEFAULT_MAX_MB), ("audit_keep", DEFAULT_KEEP)):
        raw = cfg.get(f"hosting.observability.{key}", default)
        values.append(raw if isinstance(raw, int) and not isinstance(raw, bool) and raw > 0 else default)
    return values[0] * 1024 * 1024, values[1]


def rotated_path(directory: Path, index: int) -> Path:
    """``audit.jsonl`` (index 0) or its ``index``-th rotated file, ``audit.jsonl.<index>``."""
    return Path(directory) / (AUDIT_FILE if index == 0 else f"{AUDIT_FILE}.{index}")


def _replace(source: Path, target: Path) -> bool:
    """``os.replace``, retried while a reader holds a file (Windows); whether it went."""
    for _ in range(_RENAME_ATTEMPTS):
        try:
            os.replace(source, target)
            return True
        except FileNotFoundError:
            return True
        except PermissionError:
            time.sleep(0.01)
    return False


def _rotate(directory: Path, keep: int) -> None:
    """
    Under the audit lock: each ``.n`` becomes ``.n+1`` (oldest first: ``.keep``
    moves to ``.keep+1``), then ``audit.jsonl`` becomes ``.1``, and only once
    every move has gone is the overflow, ``.keep+1``, deleted (fix round 2,
    N2: deleting the oldest first lost it whenever a later move was blocked).
    A move a reader blocks (Windows) undoes the moves already made, newest
    first, so the chain is left as it was, and the append goes on into the
    current file; the next append tries again.
    """
    done: list[tuple[Path, Path]] = []
    for index in range(keep, -1, -1):
        source = rotated_path(directory, index)
        if not source.exists():
            continue
        target = rotated_path(directory, index + 1)
        if not _replace(source, target):
            logger.warning(
                "[hosting] An audit file could not be rotated; undone (operation=audit.rotate, index=%d)", index
            )
            for moved_from, moved_to in reversed(done):
                if not _replace(moved_to, moved_from):
                    logger.error(
                        "[hosting] An audit rotation could not be undone (operation=audit.rotate, file=%s)",
                        moved_to.name,
                    )
            return
        done.append((source, target))
    overflow = rotated_path(directory, keep + 1)
    try:
        overflow.unlink(missing_ok=True)
    except OSError:
        logger.warning("[hosting] The oldest audit file could not be deleted yet (operation=audit.rotate)")
    logger.info("[hosting] The audit log was rotated (operation=audit.rotate, keep=%d)", keep)


def _write_line(directory: Path, line: bytes) -> None:
    """
    Append ``line`` under the audit lock, flushed to disk, rotating the file
    first when the line would take it past ``audit_max_mb``. Raises
    ``OSError`` or ``TimeoutError``.
    """
    secure_dir(directory)
    max_bytes, keep = rotation()
    lock_fd = open_private(directory / AUDIT_LOCK)
    try:
        deadline = time.monotonic() + LOCK_WAIT_SECONDS
        while not try_lock(lock_fd):
            if time.monotonic() > deadline:
                raise TimeoutError(f"{AUDIT_LOCK} stayed held for {LOCK_WAIT_SECONDS:.0f} s")
            time.sleep(0.01)
        try:
            try:
                size = (directory / AUDIT_FILE).stat().st_size
            except FileNotFoundError:
                size = 0
            if size and size + len(line) > max_bytes:
                _rotate(directory, keep)
            fd = os.open(str(directory / AUDIT_FILE), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
            try:
                if os.name == "posix":
                    os.fchmod(fd, 0o600)
                written = os.write(fd, line)
                if written != len(line):
                    raise OSError(f"a short write ({written} of {len(line)} bytes)")
                os.fsync(fd)
            finally:
                os.close(fd)
        finally:
            unlock(lock_fd)
    finally:
        os.close(lock_fd)


def append(
    action: str,
    *,
    actor: Actor,
    result: str,
    target: str = "",
    detail: Optional[dict[str, Any]] = None,
    ref: Optional[str] = None,
    directory: Optional[Path] = None,
) -> dict[str, Any]:
    """
    Append one row; returns it. A row outside the closed set raises
    ``AuditRowError`` (a programming error); a row that cannot be written
    raises ``AuditUnavailable``.
    """
    row = check_row(
        {
            "ts": time.time(),
            "actor": actor.id,
            "actor_name": actor.name,
            "address": actor.address,
            "action": action,
            "target": target,
            "detail": detail or {},
            "result": result,
            "ref": ref or new_ref(),
        }
    )
    line = (json.dumps(row, ensure_ascii=True, separators=(",", ":")) + "\n").encode("ascii")
    try:
        _write_line(Path(audit_path(directory).parent), line)
    except (OSError, TimeoutError) as exc:
        logger.error(
            "[hosting] The audit log could not be written (operation=audit.append, action=%s, "
            "result=%s, ref=%s, error=%s)",
            action,
            result,
            row["ref"],
            type(exc).__name__,
        )
        raise AuditUnavailable(UNAVAILABLE) from None
    return row


def refused(
    action: str,
    *,
    actor: Actor,
    target: str = "",
    detail: Optional[dict[str, Any]] = None,
    directory: Optional[Path] = None,
) -> Optional[dict[str, Any]]:
    """
    One ``refused`` row, for a request refused before it started (a failed
    validation, a guard). Nothing changed, so a failed append is logged and
    the refusal stands: None is returned.
    """
    try:
        return append(action, actor=actor, result=REFUSED, target=target, detail=detail, directory=directory)
    except AuditUnavailable:
        return None


@dataclass
class Ticket:
    """An action in flight under ``audited``: what its outcome row will say."""

    ref: str
    target: str
    detail: dict[str, Any] = field(default_factory=dict)
    #: The outcome ``audited`` appends when the block ends without raising.
    result: str = OK


@contextmanager
def audited(
    action: str,
    target: str = "",
    *,
    actor: Actor,
    detail: Optional[dict[str, Any]] = None,
    refusals: tuple[type[BaseException], ...] = (),
    directory: Optional[Path] = None,
) -> Iterator[Ticket]:
    """
    THE WRITE-FIRST RULE (spec §14.11). Appends the ``started`` row, then
    runs the block, then appends the outcome with the same ``ref``:

    - the started row cannot be written: ``AuditUnavailable`` is raised and
      the block never runs (nothing changes);
    - the block raises one of ``refusals`` (a guard checked inside a lock):
      ``refused``, and the exception goes on;
    - it raises anything else: ``error``, and the exception goes on;
    - it returns: ``ticket.result`` (``ok`` unless the block set another),
      with ``ticket.target`` and ``ticket.detail`` as the block left them.

    An outcome row that cannot be written is logged (the action has
    happened, and its started row records it).
    """
    ticket = Ticket(ref=new_ref(), target=target, detail=dict(detail or {}))
    append(action, actor=actor, result=STARTED, target=target, detail=ticket.detail, ref=ticket.ref, directory=directory)
    outcome = ERROR
    try:
        yield ticket
        outcome = ticket.result
    except refusals:
        outcome = REFUSED
        raise
    finally:
        try:
            append(
                action,
                actor=actor,
                result=outcome,
                target=ticket.target,
                detail=ticket.detail,
                ref=ticket.ref,
                directory=directory,
            )
        except AuditUnavailable:
            pass  # logged by append; the action's started row stands


def read_recent(
    n: int = 200,
    offset: int = 0,
    action: Optional[str] = None,
    actor: Optional[str] = None,
    *,
    directory: Optional[Path] = None,
) -> list[dict[str, Any]]:
    """
    The newest rows first: ``n`` of them after skipping ``offset``, only
    ``action``'s and ``actor``'s when named. A line that is not a row (a hand
    edit, a torn write from a killed process) is skipped.

    A BOUNDED TAIL (fix round 1, M4): the files are read backwards in
    blocks, the current one and then each rotated one, and reading stops as
    soon as ``offset + n`` matching rows are in hand; ``offset + n`` is held
    to ``AUDIT_MAX_ROWS``, and at most ``MAX_SCAN_BYTES`` are read
    (``FILTER_SCAN_BYTES`` with a filter). ``read_tail`` also says whether
    the budget ran out before the oldest file did.
    """
    return read_tail(n, offset, action, actor, directory=directory)[0]


def read_tail(
    n: int = 200,
    offset: int = 0,
    action: Optional[str] = None,
    actor: Optional[str] = None,
    *,
    directory: Optional[Path] = None,
) -> tuple[list[dict[str, Any]], bool]:
    """
    ``read_recent``'s rows, and whether older rows were left unsearched (the
    byte budget ran out while files remained).

    FIX ROUND 2: a missing ``.n`` is skipped, not taken as the end of the
    chain (N2); a row seen twice -- a reader racing a rotation, which renames
    the file it has just read to ``.1`` -- is kept once: two rows are one when
    their lines are byte for byte the same, which two real rows never are
    (each carries its own ``ts`` and its ``ref``) (N3); and a filtered read is held to the smaller
    ``FILTER_SCAN_BYTES`` (N4).
    """
    start = max(0, min(int(offset), AUDIT_MAX_ROWS))
    want = max(0, min(start + int(n), AUDIT_MAX_ROWS))
    if want <= start:
        return [], False
    folder = audit_path(directory).parent
    _max, keep = rotation()
    rows: list[dict[str, Any]] = []
    seen: set[bytes] = set()
    #: [bytes left to read, whether the last file was read to its start]
    budget = [FILTER_SCAN_BYTES if (action or actor) else MAX_SCAN_BYTES, True]
    paths = [rotated_path(folder, index) for index in range(keep + 1)]
    for position, path in enumerate(paths):
        if not path.is_file():
            continue
        if budget[0] <= 0:
            return rows[start:want], True
        for line in _lines_backwards(path, budget):
            if line in seen:
                continue
            seen.add(line)
            try:
                row = check_row(json.loads(line.decode("utf-8")))
            except (ValueError, UnicodeDecodeError):
                continue
            if action and row["action"] != action:
                continue
            if actor and row["actor"] != actor:
                continue
            rows.append(row)
            if len(rows) >= want:
                return rows[start:want], False
        if budget[0] <= 0 and (not budget[1] or any(p.is_file() for p in paths[position + 1 :])):
            return rows[start:want], True
    return rows[start:want], False


#: The deepest the Audit page reads back, in rows (offset plus page).
AUDIT_MAX_ROWS = 5000

#: The most bytes one unfiltered ``read_recent`` reads, across every file.
#: An unfiltered page stops at ``offset + n`` rows long before this.
MAX_SCAN_BYTES = 64 * 1024 * 1024

#: The most bytes one FILTERED read searches (fix round 2, N4). A filter
#: that matches rarely would otherwise read every kept file on every page
#: view; 8 MiB is some 25,000 rows at a typical ~330 bytes each -- weeks of
#: an operator's actions on a small server -- read in a few tens of
#: milliseconds. Rows older than that are "not searched", and the page says so.
FILTER_SCAN_BYTES = 8 * 1024 * 1024

#: The block a backwards read takes at a time.
_BLOCK = 64 * 1024


def _lines_backwards(path: Path, budget: list[Any]) -> Iterator[bytes]:
    """
    ``path``'s lines, last first, read in ``_BLOCK``s from the end; spends
    ``budget[0]`` bytes and stops when it runs out, and sets ``budget[1]``
    (when there is one) to whether it reached the file's start. A file that
    vanishes (a rotation) ends the read.
    """
    if len(budget) > 1:
        budget[1] = True
    try:
        handle = path.open("rb")
    except OSError:
        return
    with handle:
        handle.seek(0, os.SEEK_END)
        position = handle.tell()
        tail = b""
        while position > 0 and budget[0] > 0:
            size = min(_BLOCK, position)
            position -= size
            handle.seek(position)
            block = handle.read(size)
            budget[0] -= len(block)
            parts = (block + tail).split(b"\n")
            tail = parts[0]
            for line in reversed(parts[1:]):
                if line:
                    yield line
        if len(budget) > 1:
            budget[1] = position == 0
        if tail and position == 0:
            yield tail


__all__ = [
    "ACTIONS",
    "AUDIT_FILE",
    "AUDIT_LOCK",
    "AUDIT_MAX_ROWS",
    "FILTER_SCAN_BYTES",
    "read_tail",
    "DEFAULT_KEEP",
    "DEFAULT_MAX_MB",
    "MAX_SCAN_BYTES",
    "rotated_path",
    "rotation",
    "Actor",
    "AuditRowError",
    "AuditUnavailable",
    "CLI",
    "CLI_ACTOR",
    "ERROR",
    "FIELDS",
    "LOCK_WAIT_SECONDS",
    "MAX_TEXT",
    "OK",
    "REFUSED",
    "RESULTS",
    "STARTED",
    "SUPERVISOR",
    "SUPERVISOR_ACTOR",
    "Ticket",
    "UNAVAILABLE",
    "append",
    "audit_path",
    "audited",
    "check_row",
    "new_ref",
    "read_recent",
    "refused",
]
