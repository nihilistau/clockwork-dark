"""
The supervisor's metrics store and a child's emitter (v0.20.0 T17, spec §14.10).

- an event with an unknown kind, an unknown or missing field, or a bad value
  is dropped and COUNTED, and nothing of it is stored;
- a worker's ``metric`` claiming another story or another process is stored
  with ITS OWN (the supervisor stamps both from the connection);
- retention prunes exactly the rows older than the window (the clock
  injected);
- only the named queries are answered -- a ``metrics.query`` carrying SQL or
  an unknown name is refused -- and each answer is a page (``limit``,
  ``offset``);
- a child's full queue drops and counts without blocking its caller (timed);
- the ERROR handler records a raised exception's class and its logger's
  name, and never the message (a sentinel).

Every store lives under the test's ``tmp_path``; nothing here starts a
process.
"""

from __future__ import annotations

import logging
import math
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Iterator

import pytest

from engine.hosting import metrics_emit
from engine.hosting.supervisor.metrics import MAX_PAGE, QUERIES, MetricsQueryError, MetricsStore

A = "clockwork-dark"
B = "dev-story"
ACCOUNT = "u_0123456789ab"
OTHER = "u_ba9876543210"
SENTINEL = "Zq7SENTINEL the player typed this"
NOW = 1_790_000_000.0


def _turn(ts: float = NOW, **changes: Any) -> dict[str, Any]:
    return {"kind": "turn", "ts": ts, "story": A, "account": ACCOUNT, "admit_wait_ms": 5.0,
            "duration_ms": 100.0, "outcome": "ok", **changes}


@pytest.fixture
def store(tmp_path: Path) -> Iterator[MetricsStore]:
    found = MetricsStore(tmp_path / "metrics.sqlite3", retention_days=30, stories=(A, B), clock=lambda: NOW).open()
    try:
        yield found
    finally:
        found.close()


def _rows(path: Path, kind: str) -> list[tuple[Any, ...]]:
    with sqlite3.connect(str(path)) as db:
        return db.execute(f"SELECT * FROM {kind}").fetchall()


def _dump(path: Path) -> str:
    db = sqlite3.connect(str(path))
    try:
        return "\n".join(db.iterdump())
    finally:
        db.close()


# -- rejection -------------------------------------------------------------------------


@pytest.mark.parametrize(
    "event",
    [
        {"kind": "narration", "ts": NOW, "text": SENTINEL},
        {**_turn(), "note": SENTINEL},
        {k: v for k, v in _turn().items() if k != "duration_ms"},
        _turn(outcome=SENTINEL),
        _turn(story=SENTINEL),
        _turn(account=SENTINEL),
        {"kind": "error", "ts": NOW, "process": "frontdoor", "ref": None, "exc_class": SENTINEL, "logger": "x"},
        "not a mapping",
    ],
)
def test_an_event_that_fails_the_schema_is_dropped_counted_and_never_stored(
    store: MetricsStore, event: Any
) -> None:
    assert store.record(event) is False
    assert store.flush()
    assert store.rejected == 1 and store.dropped == 0
    assert SENTINEL not in _dump(store.path)
    assert store.query("metrics_rejected", limit=1)["rows"] == [
        {"rejected": 1, "dropped": 0, "dropped_rate": 0, "dropped_size": 0, "children": {}}
    ]


def test_a_good_event_is_stored_as_typed_columns(store: MetricsStore) -> None:
    assert store.record(_turn())
    assert store.flush()
    (row,) = _rows(store.path, "turn")
    assert row[1:] == (NOW, A, ACCOUNT, 5.0, 100.0, "ok")


def test_a_full_store_queue_drops_and_counts(tmp_path: Path) -> None:
    store = MetricsStore(tmp_path / "m.sqlite3", retention_days=30, stories=(A,), maxsize=2)  # never opened: no writer
    assert store.record(_turn()) and store.record(_turn())
    began = time.monotonic()
    assert store.record(_turn()) is False
    assert time.monotonic() - began < 0.5
    assert store.dropped == 1


# -- stamping --------------------------------------------------------------------------


class _Bare:
    """A ``Supervisor`` in this process with its bus and its store (never started): ``connect(role, story)``."""

    def __init__(self, tmp_path: Path, **block: Any) -> None:
        from engine.hosting.config import validate
        from engine.hosting.supervisor.logs import LogHub
        from engine.hosting.supervisor.server import Supervisor
        from tests.test_hosting_config import _block

        self.hub = LogHub(tmp_path / "logs", max_mb=1, keep=2, echo=None)
        self.sup = Supervisor(
            validate(_block(stories=[A, B], **block)), hub=self.hub, metrics_path=tmp_path / "hosting" / "metrics.sqlite3"
        )
        self.sup.server.admit = None  # no child is starting: the token alone admits this test's client
        self.clients: list[Any] = []

    def start(self) -> "_Bare":
        self.sup._open_metrics()
        self.sup.server.start()
        return self

    def connect(self, role: str, story: str = "") -> Any:
        from engine.hosting.bus import BusClient

        process = "frontdoor" if role == "frontdoor" else f"worker-{story}"
        record = self.sup.server.mint(role, story=story, process=process)
        client = BusClient(self.sup.server.addr, record.token)
        client.on_lost = lambda: None
        client.connect()
        self.clients.append(client)
        return client

    def close(self) -> None:
        for client in self.clients:
            client.close()
        sup = self.sup
        sup.ops.close()
        sup._health.shutdown(wait=False)
        sup._reaper.shutdown(wait=False)
        sup._fanout.shutdown(wait=False)
        sup._audit_writer.close(timeout=10)
        sup.server.close()
        if sup.metrics is not None:
            sup.metrics.close()
        self.hub.close()


@pytest.fixture
def bare(tmp_path: Path) -> Iterator[_Bare]:
    found = _Bare(tmp_path).start()
    try:
        yield found
    finally:
        found.close()


def _wait_written(store: MetricsStore, check: Any, timeout: float = 20.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        store.flush(1)
        if check():
            return
    raise AssertionError("the metrics never arrived")


@pytest.mark.loopback
def test_a_worker_s_metric_is_stored_with_its_own_story_and_process(bare: _Bare) -> None:
    """A worker of B claims story A and the front door's process name: both are B's."""
    sup = bare.sup
    assert sup.metrics is not None
    client = bare.connect("worker", B)
    client.notify("metric", {"event": {**_turn(), "story": A}})
    client.notify("metric", {"event": {"kind": "error", "ts": NOW, "process": "frontdoor", "ref": "3fa9c2e1",
                                       "exc_class": "RuntimeError", "logger": "engine.hosting.errors"}})
    client.notify("metric", {"event": {"kind": "login", "ts": NOW, "account": ACCOUNT, "outcome": "ok"}})
    _wait_written(sup.metrics, lambda: len(_rows(sup.metrics.path, "login")) >= 1)
    (turn,) = _rows(sup.metrics.path, "turn")
    (error,) = _rows(sup.metrics.path, "error")
    assert turn[2] == B, "the story a worker claimed was stored"
    assert error[2] == f"worker-{B}", "the process a worker claimed was stored"
    assert len(_rows(sup.metrics.path, "login")) == 1  # a kind with neither field: kept as sent


# -- bounded (fix round 1, I1) -----------------------------------------------------------


@pytest.mark.loopback
def test_a_flood_of_refused_logins_keeps_the_store_bounded(bare: _Bare) -> None:
    """
    A script hammering /login: 50,000 `limited` logins sent by the front
    door, as fast as the bus takes them. The store keeps a few counter rows
    (one per minute), never a row per refusal; past the connection's rate the
    rest are dropped and counted; the file stays small. Fails on 5c9c3b5,
    where each refusal was a row and nothing capped a connection.
    """
    sup = bare.sup
    store = sup.metrics
    assert store is not None
    door = bare.connect("frontdoor")
    event = {"kind": "login", "ts": NOW, "account": None, "outcome": "limited"}
    for _ in range(50_000):
        door.notify("metric", {"event": event})
    _wait_written(store, lambda: store.dropped_rate + _refused(store.path) >= 50_000 - 10, timeout=60)
    assert _rows(store.path, "login") == [], "a refusal was kept as a row of its own"
    counters = _rows_of(store.path, "SELECT minute, kind, story, outcome, count FROM refused")
    assert counters == [(math.floor(NOW / 60) * 60, "login", "", "limited", _refused(store.path))]
    assert store.dropped_rate > 40_000, "the connection's rate was not capped"
    # The file itself stays a few pages; its -wal is bounded by SQLite's
    # checkpoint (1000 pages) and cut back to WAL_LIMIT_BYTES after it.
    assert Path(store.path).stat().st_size < 256 * 1024, Path(store.path).stat().st_size
    assert store.size() < 8 * 1024 * 1024, store.size()
    shown = store.query("refusals", {"hours": 24 * 365}, 10, 0)
    assert shown["rows"][0]["count"] == _refused(store.path) and shown["rows"][0]["outcome"] == "limited"


def _rows_of(path: Path, sql: str) -> list[tuple[Any, ...]]:
    with sqlite3.connect(str(path)) as db:
        return db.execute(sql).fetchall()


def _refused(path: Path) -> int:
    found = _rows_of(path, "SELECT COALESCE(SUM(count), 0) FROM refused")
    return int(found[0][0])


def test_the_file_is_capped_and_the_oldest_rows_go_first(tmp_path: Path) -> None:
    """At ``metrics_max_mb`` the oldest tenth of every table goes, the newest are kept, the file stays at the cap."""
    store = MetricsStore(tmp_path / "m.sqlite3", retention_days=3650, stories=(A,), clock=lambda: NOW, max_mb=1).open()
    try:
        for i in range(30_000):
            store.record(_turn(ts=NOW - 30_000 + i, duration_ms=float(i)))
            if i % 2000 == 1999:
                assert store.flush(30)
        assert store.flush(30)
        rows = _rows_of(store.path, "SELECT MIN(ts), MAX(ts), COUNT(*) FROM turn")
        oldest, newest, count = rows[0]
        assert newest == NOW - 1, "the newest row was not kept"
        assert oldest > NOW - 30_000, "the oldest rows were not the ones deleted"
        assert 0 < count < 30_000
        assert Path(store.path).stat().st_size <= 1024 * 1024 + 64 * 1024
        assert store.dropped_size == 0, "a batch was dropped instead of making room"
    finally:
        store.close()


@pytest.mark.loopback
def test_a_connection_s_rate_is_capped(bare: _Bare) -> None:
    sup = bare.sup
    assert sup.metrics is not None
    sup.metric_rate, sup.metric_burst = 1.0, 5.0
    worker = bare.connect("worker", A)
    for _ in range(50):
        worker.notify("metric", {"event": _turn()})
    _wait_written(sup.metrics, lambda: sup.metrics.dropped_rate + len(_rows(sup.metrics.path, "turn")) >= 50)
    assert 5 <= len(_rows(sup.metrics.path, "turn")) <= 10
    assert sup.metrics.dropped_rate >= 40


# -- never blocks a start (fix round 1, I2) -----------------------------------------------


def test_a_corrupt_store_is_moved_aside_and_a_new_one_made(tmp_path: Path) -> None:
    path = tmp_path / "metrics.sqlite3"
    path.write_bytes(b"torn by a power cut" * 512)
    store = MetricsStore(path, retention_days=30, stories=(A,), clock=lambda: NOW).open()
    try:
        assert store.moved_aside is not None and store.moved_aside.name.startswith("metrics.sqlite3.bad-")
        assert store.moved_aside.read_bytes().startswith(b"torn by a power cut")
        assert store.record(_turn()) and store.flush()
        assert len(_rows(path, "turn")) == 1
    finally:
        store.close()


@pytest.mark.parametrize("message", ["database is locked", "database or disk is full", "unable to open database file"])
def test_a_store_that_is_locked_or_full_is_not_moved_aside(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, message: str
) -> None:
    """
    v0.20.0 T18 (T17 re-review N1): only CORRUPTION moves the store aside. A
    locked file, a full disk or a refused open says nothing about the file,
    which may be sound: it stays where it is, and the start goes on without
    metrics.
    """
    from engine.hosting.supervisor.metrics import BAD_SUFFIX, MetricsUnavailable

    path = tmp_path / "metrics.sqlite3"
    sound = MetricsStore(path, retention_days=30, stories=(A,), clock=lambda: NOW).open()
    assert sound.record(_turn()) and sound.flush()
    sound.close()
    before = path.read_bytes()

    def refuse(_self: Any) -> Any:
        raise sqlite3.OperationalError(message)

    monkeypatch.setattr(MetricsStore, "_connect", refuse)
    with pytest.raises(MetricsUnavailable):
        MetricsStore(path, retention_days=30, stories=(A,), clock=lambda: NOW).open()
    assert path.read_bytes() == before
    assert not list(tmp_path.glob(f"metrics.sqlite3{BAD_SUFFIX}*"))


def test_corruption_is_told_from_the_rest() -> None:
    from engine.hosting.supervisor.metrics import corrupt

    assert corrupt(sqlite3.DatabaseError("file is not a database"))
    assert corrupt(sqlite3.DatabaseError("database disk image is malformed"))
    assert corrupt(sqlite3.DatabaseError("quick_check failed"))
    for sound in ("database is locked", "database or disk is full", "unable to open database file", "disk I/O error"):
        assert not corrupt(sqlite3.OperationalError(sound)), sound
    assert not corrupt(OSError("Permission denied"))


def test_at_most_a_few_moved_aside_stores_are_kept(tmp_path: Path) -> None:
    from engine.hosting.supervisor.metrics import BAD_SUFFIX, MAX_BAD_FILES

    path = tmp_path / "metrics.sqlite3"
    for day in range(1, 6):
        old = tmp_path / f"metrics.sqlite3{BAD_SUFFIX}2026010{day}T000000Z"
        old.write_bytes(b"old")
        Path(f"{old}-wal").write_bytes(b"old wal")
    path.write_bytes(b"torn by a power cut" * 512)
    store = MetricsStore(path, retention_days=30, stories=(A,), clock=lambda: NOW).open()
    try:
        kept = sorted(p.name for p in tmp_path.glob(f"metrics.sqlite3{BAD_SUFFIX}*") if not p.name.endswith("-wal"))
        assert len(kept) == MAX_BAD_FILES == 3
        assert store.moved_aside is not None and store.moved_aside.name in kept  # the newest is kept
        assert kept[:2] == [f"metrics.sqlite3{BAD_SUFFIX}20260104T000000Z", f"metrics.sqlite3{BAD_SUFFIX}20260105T000000Z"]
        wals = sorted(p.name for p in tmp_path.glob("*-wal") if BAD_SUFFIX in p.name)
        assert wals == [f"{name}-wal" for name in kept[:2]]  # an old store's -wal goes with it
    finally:
        store.close()


def test_the_error_reference_is_indexed(store: MetricsStore) -> None:
    indexes = _rows_of(store.path, "SELECT name, tbl_name FROM sqlite_master WHERE type = 'index'")
    assert ("error_ref", "error") in indexes
    plan = " ".join(str(row) for row in _rows_of(store.path, "EXPLAIN QUERY PLAN SELECT * FROM error WHERE ref = 'x'"))
    assert "error_ref" in plan, plan


def test_a_large_store_is_not_read_whole_at_every_start(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """v0.20.0 T18 (T17 re-review N4): the page check runs only on a store of at most QUICK_CHECK_MAX_BYTES."""
    from engine.hosting.supervisor import metrics as metrics_module

    path = tmp_path / "metrics.sqlite3"
    MetricsStore(path, retention_days=30, stories=(A,), clock=lambda: NOW).open().close()
    seen: list[str] = []
    real = sqlite3.connect

    def tracing(*args: Any, **kwargs: Any) -> sqlite3.Connection:
        db = real(*args, **kwargs)
        db.set_trace_callback(seen.append)
        return db

    monkeypatch.setattr(metrics_module.sqlite3, "connect", tracing)
    small = MetricsStore(path, retention_days=30, stories=(A,), clock=lambda: NOW).open()
    small.close()
    assert any("quick_check" in statement for statement in seen)
    seen.clear()
    monkeypatch.setattr(metrics_module, "QUICK_CHECK_MAX_BYTES", 0)
    large = MetricsStore(path, retention_days=30, stories=(A,), clock=lambda: NOW).open()
    large.close()
    assert seen and not any("quick_check" in statement for statement in seen)


@pytest.mark.loopback
def test_a_store_that_will_not_open_even_fresh_leaves_the_supervisor_running_without_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both opens fail: the start goes on with no store, a WARNING and a metrics.disabled audit row."""
    import json as json_module

    path = tmp_path / "hosting" / "metrics.sqlite3"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"garbage" * 100)

    def refuse(_self: Any) -> Any:
        raise sqlite3.OperationalError("unable to open database file")

    monkeypatch.setattr(MetricsStore, "_connect", refuse)
    found = _Bare(tmp_path)
    try:
        found.start()
        sup = found.sup
        assert sup.metrics is None
        sup.record(_turn())  # a no-op, never a raise
        found.connect("worker", A).notify("metric", {"event": _turn()})
        sup._audit_writer.close(timeout=10)
        rows = [json_module.loads(line) for line in (path.parent / "audit.jsonl").read_text(encoding="utf-8").splitlines()]
        assert [(r["action"], r["actor"], r["result"]) for r in rows] == [("metrics.disabled", "supervisor", "error")]
    finally:
        found.close()


def test_a_failed_batch_is_rolled_back_and_never_carried_into_the_next(store: MetricsStore) -> None:
    """Fix round 1 (M1): a statement that fails mid-batch rolls the batch back."""
    assert store._db is not None
    with store._db_lock:
        store._db.execute("DROP TABLE lane")
        store._db.commit()
    store.record(_turn(ts=NOW - 5))
    store.record({"kind": "lane", "ts": NOW, "story": A, "account": None, "lane": "utility",
                  "wait_ms": 0, "hold_ms": 1.0, "outcome": "granted"})
    assert store.flush()
    assert _rows(store.path, "turn") == [], "the failed batch's first row was kept"
    assert store.dropped_size == 2
    store.record(_turn(ts=NOW))
    assert store.flush()
    assert [r[1] for r in _rows(store.path, "turn")] == [NOW], "an earlier batch's row rode into this commit"


@pytest.mark.skipif(os.name != "posix", reason="file modes are POSIX's")
def test_the_store_is_private_on_posix(store: MetricsStore) -> None:
    for suffix in ("", "-wal", "-shm"):
        found = Path(f"{store.path}{suffix}")
        if found.exists():
            assert found.stat().st_mode & 0o077 == 0, found


def test_a_reference_finds_its_error(store: MetricsStore) -> None:
    for i in range(3):
        store.record({"kind": "error", "ts": NOW - i, "process": f"worker-{A}", "ref": f"{i:08x}",
                      "exc_class": None, "logger": "engine.hosting.errors"})
    assert store.flush()
    found = store.query("recent_errors", {"ref": "00000001"}, 10, 0)
    assert found["total"] == 1 and found["rows"][0]["ref"] == "00000001"
    for bad in ("0000001", "zzzzzzzz", "00000001 OR 1=1"):
        with pytest.raises(MetricsQueryError):
            store.query("recent_errors", {"ref": bad}, 10, 0)
    with pytest.raises(MetricsQueryError):
        store.query("usage", {"ref": "00000001"}, 10, 0)


def test_a_child_s_own_drops_are_kept_for_the_panel(store: MetricsStore) -> None:
    store.child_dropped(f"worker-{A}", 7)
    store.child_dropped("worker-no-such-story", 9)
    store.child_dropped("frontdoor", "many")
    assert store.query("metrics_rejected", limit=1)["rows"][0]["children"] == {f"worker-{A}": 7}


# -- retention -------------------------------------------------------------------------


def test_retention_prunes_exactly_the_rows_older_than_the_window(tmp_path: Path) -> None:
    clock = [NOW]
    store = MetricsStore(tmp_path / "m.sqlite3", retention_days=30, stories=(A,), clock=lambda: clock[0]).open()
    try:
        window = 30 * 86400.0
        for ts in (NOW - window - 1, NOW - window + 1, NOW):
            assert store.record(_turn(ts=ts))
            assert store.record({"kind": "login", "ts": ts, "account": ACCOUNT, "outcome": "ok"})
        # A refusal counter's minute is pruned by the same window.
        assert store.record({"kind": "login", "ts": NOW - window - 120, "account": None, "outcome": "failed"})
        assert store.record({"kind": "login", "ts": NOW, "account": None, "outcome": "failed"})
        assert store.flush()
        assert store.prune() == 3
        for kind in ("turn", "login"):
            assert sorted(r[1] for r in _rows(store.path, kind)) == [NOW - window + 1, NOW]
        assert [r[0] for r in _rows_of(store.path, "SELECT minute FROM refused")] == [math.floor(NOW / 60) * 60]
        clock[0] = NOW + 2  # one more row now falls outside
        assert store.prune() == 2
        assert sorted(r[1] for r in _rows(store.path, "turn")) == [NOW]
    finally:
        store.close()


# -- the named queries -----------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    ["SELECT * FROM turn", "turn_durations; DROP TABLE turn", "turn", "", None, 7, "recent_errors "],
)
def test_only_a_named_query_is_answered(store: MetricsStore, name: Any) -> None:
    with pytest.raises(MetricsQueryError) as caught:
        store.query(name)
    assert caught.value.code == "unknown_query"
    assert store.query("recent_errors")["rows"] == []  # the table is still there


@pytest.mark.parametrize(
    ("params", "limit", "offset"),
    [({"hours": 0}, 10, 0), ({"hours": "24"}, 10, 0), ({"sql": "1=1"}, 10, 0), ({}, MAX_PAGE + 1, 0), ({}, 10, -1)],
)
def test_a_bad_parameter_is_refused(store: MetricsStore, params: Any, limit: int, offset: int) -> None:
    with pytest.raises(MetricsQueryError) as caught:
        store.query("usage", params, limit, offset)
    assert caught.value.code == "bad_params"


def test_every_query_answers_a_page(store: MetricsStore) -> None:
    for i in range(7):
        assert store.record(_turn(ts=NOW - i * 3600 - 1, duration_ms=100.0 * (i + 1), account=ACCOUNT if i % 2 else OTHER))
        assert store.record({"kind": "error", "ts": NOW - i, "process": f"worker-{A}", "ref": f"{i:08x}",
                             "exc_class": "RuntimeError", "logger": "engine.hosting.errors"})
    assert store.record({"kind": "login", "ts": NOW - 5, "account": ACCOUNT, "outcome": "ok"})
    assert store.record({"kind": "login", "ts": NOW - 1, "account": ACCOUNT, "outcome": "must_change"})
    assert store.record({"kind": "lane", "ts": NOW - 1, "story": A, "account": ACCOUNT, "lane": "narration",
                         "wait_ms": 40.0, "hold_ms": 900.0, "outcome": "granted"})
    assert store.flush()
    for name in QUERIES:
        whole = store.query(name, {"hours": 24}, MAX_PAGE, 0)
        assert set(whole) == {"rows", "total"}
        assert whole["total"] >= len(whole["rows"])
    errors = store.query("recent_errors", limit=3, offset=0)
    assert errors["total"] == 7 and [r["ref"] for r in errors["rows"]] == ["00000000", "00000001", "00000002"]
    later = store.query("recent_errors", limit=3, offset=6)
    assert [r["ref"] for r in later["rows"]] == ["00000006"]
    assert set(errors["rows"][0]) == {"ts", "process", "ref", "exc_class", "logger"}
    durations = store.query("turn_durations", {"hours": 24}, limit=2, offset=0)
    assert durations["total"] == 7 and len(durations["rows"]) == 2
    assert durations["rows"][0]["turns"] == 1 and durations["rows"][0]["p50_ms"] == 100.0
    assert store.query("last_login", limit=10)["rows"] == [{"account": ACCOUNT, "ts": NOW - 1}]
    waits = {r["source"]: r for r in store.query("waits", {"hours": 24}, 10, 0)["rows"]}
    assert waits["admission"]["count"] == 7 and waits["narration"]["p50_ms"] == 40.0
    assert waits["narration"]["hold_p95_ms"] == 900.0
    usage = store.query("usage", {"hours": 24}, 10, 0)["rows"]
    assert {r["account"] for r in usage} == {ACCOUNT, OTHER}
    assert sum(r["turns"] for r in usage) == 7


# -- a child's emitter -----------------------------------------------------------------


class _StuckBus:
    """A bus whose notify never returns until released: the sender is stuck."""

    def __init__(self) -> None:
        self.release = threading.Event()
        self.sent: list[Any] = []

    def notify(self, op: str, args: Any) -> None:
        self.release.wait(30)
        self.sent.append((op, args))


@pytest.fixture
def emitter() -> Iterator[_StuckBus]:
    bus = _StuckBus()
    metrics_emit.stop()
    metrics_emit.enable(maxsize=4)
    metrics_emit.attach(bus)
    try:
        yield bus
    finally:
        bus.release.set()
        metrics_emit.stop(timeout=10)


def test_a_full_child_queue_drops_and_counts_without_blocking_the_caller(emitter: _StuckBus) -> None:
    began = time.monotonic()
    for _ in range(200):
        metrics_emit.emit("turn", account=None, admit_wait_ms=0.0, duration_ms=0.0, outcome="busy")
    took = time.monotonic() - began
    assert took < 1.0, f"emit waited {took:.2f}s on a stuck sender"
    # At most the queue (4) and the one the sender holds were kept.
    assert metrics_emit.dropped >= 200 - 5


def test_emit_is_a_no_op_in_a_process_that_never_enabled_it() -> None:
    metrics_emit.stop()
    assert not metrics_emit.enabled()
    metrics_emit.emit("turn", outcome="ok")  # nothing to put it on: returns
    assert metrics_emit.dropped == 0


def test_the_error_handler_keeps_the_class_and_the_logger_never_the_message() -> None:
    caught: list[dict[str, Any]] = []
    handler = metrics_emit.ErrorMetricHandler(caught.append)
    log = logging.getLogger("engine.test_metrics_store.probe")
    log.addHandler(handler)
    log.propagate = False
    try:
        try:
            raise ValueError(SENTINEL)
        except ValueError:
            log.exception("failed on %s", SENTINEL)
        log.error("a line with no exception: %s", SENTINEL)
        log.warning("below ERROR: %s", SENTINEL)
        log.error("already reported", extra={metrics_emit.METRIC_REPORTED: True})
    finally:
        log.removeHandler(handler)
        log.propagate = True
    assert caught == [
        {"ref": None, "exc_class": "ValueError", "logger": "engine.test_metrics_store.probe"},
        {"ref": None, "exc_class": None, "logger": "engine.test_metrics_store.probe"},
    ]
    assert SENTINEL not in repr(caught)


def test_the_error_handler_s_events_fit_the_schema(store: MetricsStore) -> None:
    """What the handler makes, stamped as the supervisor stamps it, is kept, and holds no message."""
    caught: list[dict[str, Any]] = []
    handler = metrics_emit.ErrorMetricHandler(caught.append)
    log = logging.getLogger("weird logger name: with words")
    log.addHandler(handler)
    log.propagate = False
    try:
        try:
            raise KeyError(SENTINEL)
        except KeyError:
            log.exception("boom")
    finally:
        log.removeHandler(handler)
        log.propagate = True
    (fields,) = caught
    assert fields["logger"] == metrics_emit.UNNAMED_LOGGER
    assert store.record({"kind": "error", "ts": NOW, "process": f"worker-{A}", **fields})
    assert store.flush()
    assert SENTINEL not in _dump(store.path) and "with words" not in _dump(store.path)


def test_public_message_sends_its_reference_too() -> None:
    """Fix round 1 (M4): a failure that is a value (an STT result) is found by its ref as well."""
    from engine.hosting.errors import public_message

    metrics_emit.stop()
    metrics_emit.enable(maxsize=10)
    try:
        text, ref = public_message("Transcription failed", detail=SENTINEL)
        queued = metrics_emit._queue
        assert queued is not None
        event = queued.get_nowait()
    finally:
        metrics_emit.stop()
    assert ref in text and SENTINEL not in text
    assert {k: v for k, v in event.items() if k != "ts"} == {
        "kind": "error", "ref": ref, "exc_class": None, "logger": "engine.hosting.errors"
    }


def test_public_error_sends_its_reference_and_class_and_the_handler_skips_its_record(
    caplog: pytest.LogCaptureFixture,
) -> None:
    from engine.hosting.errors import public_error

    seen: list[dict[str, Any]] = []
    handler = metrics_emit.ErrorMetricHandler(seen.append)
    logging.getLogger().addHandler(handler)
    metrics_emit.stop()
    metrics_emit.enable(maxsize=10)
    try:
        text, ref = public_error(RuntimeError(SENTINEL), "The turn could not be completed", where="test")
        queued = metrics_emit._queue
        assert queued is not None
        event = queued.get_nowait()
    finally:
        logging.getLogger().removeHandler(handler)
        metrics_emit.stop()
    assert ref in text and SENTINEL not in text
    assert {k: v for k, v in event.items() if k != "ts"} == {
        "kind": "error", "ref": ref, "exc_class": "RuntimeError", "logger": "engine.hosting.errors"
    }
    assert seen == [], "the ERROR handler recorded public_error's line a second time"
