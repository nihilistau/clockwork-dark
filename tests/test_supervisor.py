"""
The supervisor (v0.20.0 T10, spec §14.3): real processes, shared.

One instance (``tests/hosting_instance.py``) serves most of this file: a
supervisor, six probe workers (``tests/probes/fake_worker.py``) and a probe
front door, whose relay calls the front-door-only ops. Each test uses its
own story, so their crashes and stops do not meet. Two tests need a fresh
instance and say why: the shutdown (it ends its instance) and the startup
refusal (it never starts one).

The rest run in this process: the startup refusals of ``preflight``, the
process-group flag (spied), the restart backoff and the launcher's no-spawn.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Iterator

import pytest

# At module level: the runner keeps the real seams it pins, which a first
# import inside a test body (under the conftest's pins) cannot.
from tests import local_golden
from tests.hosting_instance import HostingInstance, hosting_instance
from tests.process_identity import alive, identify

#: The six stories, one worker each; each test below owns one.
A, B, C, D, E, F = (
    "clockwork-dark",
    "wicked-garden",
    "neon-city",
    "the-long-con",
    "dev-story",
    "hue-and-cry",
)


@pytest.fixture(scope="module", autouse=True)
def _no_supervisor_test_writes_the_real_storage_root() -> Iterator[None]:
    """
    T14 fix round 2, N1: on ab77837 the in-process supervisors' held-down
    audit rows were written by their writer thread AFTER a test's storage
    redirect was undone, into the owner's real ``data/hosting/audit.jsonl``
    -- caught only by the session-end guard. This module checks its own
    share: the real root's ``hosting/`` and ``users/`` are net unchanged once
    every test here has run (any writer thread left running is given a
    moment to land what it would).
    """
    from conftest import _REAL_DATA_ROOT, snapshot_changes, storage_snapshot

    roots = [(_REAL_DATA_ROOT / "hosting", None), (_REAL_DATA_ROOT / "users", None)]
    before = storage_snapshot(roots)
    yield
    for thread in [t for t in threading.enumerate() if t.name == "supervisor-audit"]:
        thread.join(2.0)
    time.sleep(0.5)
    changes = snapshot_changes(before, storage_snapshot(roots))
    assert not changes, f"a supervisor test wrote the owner's real storage root: {changes[:5]}"


@pytest.fixture(scope="module")
def instance(tmp_path_factory: pytest.TempPathFactory) -> Iterator[HostingInstance]:
    yield from hosting_instance(tmp_path_factory, "supervisor", stories=[A, B, C, D, E, F])


def _w(slug: str) -> str:
    return f"worker-{slug}"


def _live_pid(instance: HostingInstance, slug: str) -> int:
    row = instance.row(_w(slug))
    assert row["pid"], row
    return int(row["pid"])


def _kill(instance: HostingInstance, slug: str) -> None:
    """
    Make a child exit as a crash would (TerminateProcess on Windows): its
    probe, by its pid AND creation time, never a bare pid that the OS may
    have handed to another process (v0.20.0 T15 fix round 1, I2).
    """
    instance.kill_child(_w(slug))


# -- started, ready, grouped ----------------------------------------------------------


def test_every_story_is_started_and_ready_with_its_reported_port(instance: HostingInstance) -> None:
    import httpx

    table = instance.table()
    assert [table[_w(s)]["state"] for s in (A, B, C, D, E, F)] == ["ready"] * 6
    ports = {table[_w(s)]["port"] for s in (A, B, C, D, E, F)}
    assert len(ports) == 6 and all(ports)
    for slug in (A, B):
        port = table[_w(slug)]["port"]
        body = httpx.get(f"http://127.0.0.1:{port}/api/health", trust_env=False).json()
        assert body == {"status": "ok", "fake": _w(slug)}


def test_the_cookie_key_was_made_before_any_child_said_hello(instance: HostingInstance) -> None:
    reports = instance.reports()
    assert len(reports) >= 7
    assert all(r["key_file_existed"] for r in reports), reports
    assert (instance.data_dir / "hosting" / "secret_key").is_file()


def test_a_child_holds_no_token_in_its_environment(instance: HostingInstance) -> None:
    for report in instance.reports():
        keys = set(report["env_keys"])
        assert "CLOCKWORK_BUS_TOKEN" not in keys and "CLOCKWORK_PROXY_TOKEN" not in keys
        assert {"CLOCKWORK_BUS_ADDR", "CLOCKWORK_BUS_ROLE"} <= keys
        if report["process"].startswith("worker-"):
            assert "CLOCKWORK_GAME" in keys


def test_no_token_reaches_a_log_line(instance: HostingInstance) -> None:
    """A token is 64 hex digits; none appears in the echo or in any log file."""
    token = re.compile(r"\b[0-9a-f]{64}\b")
    assert not [line for line in instance.lines if token.search(line)]
    for path in (instance.data_dir / "hosting" / "logs").glob("*.log*"):
        assert not token.search(path.read_text(encoding="utf-8", errors="replace")), path


@pytest.mark.skipif(os.name == "nt", reason="POSIX process groups; Windows is spied below")
def test_each_child_is_in_its_own_process_group(instance: HostingInstance) -> None:
    supervisor_group = os.getpgid(instance.proc.pid)  # type: ignore[union-attr]
    groups = {r["pgid"] for r in instance.reports()}
    assert supervisor_group not in groups
    assert len(groups) == len(instance.reports())


def test_a_child_is_started_in_a_new_process_group(monkeypatch: pytest.MonkeyPatch) -> None:
    """The flag itself, spied: CREATE_NEW_PROCESS_GROUP on Windows, a new session on POSIX."""
    from engine.hosting.bus import TokenRecord
    from engine.hosting.supervisor import process

    seen: list[tuple[list[str], dict[str, Any]]] = []

    class Spy:
        pid = 4242
        stdout = None

        def __init__(self, args: list[str], **kwargs: Any) -> None:
            seen.append((args, kwargs))

    monkeypatch.setattr(process.subprocess, "Popen", Spy)
    child = process.Child(role="worker", slug=A, module="engine.hosting.boot")
    record = TokenRecord(token="t" * 64, role="worker", story=A, process=_w(A))
    child.spawn(addr="127.0.0.1:1", record=record, environ={"PATH": "x", "CLOCKWORK_BUS_TOKEN": "old"})
    (args, kwargs), = seen
    assert args == [sys.executable, "-u", "-m", "engine.hosting.boot", "--role", "worker"]
    assert "shell" not in kwargs
    if os.name == "nt":
        assert kwargs["creationflags"] & subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        assert kwargs["start_new_session"] is True
    env = kwargs["env"]
    assert env["CLOCKWORK_BUS_TOKEN"] == "t" * 64  # this start's, never the inherited one
    assert env["CLOCKWORK_GAME"] == A and env["CLOCKWORK_BUS_ROLE"] == "worker"
    assert "t" * 64 not in " ".join(args)
    assert child.state == process.STARTING


# -- health and restarts -------------------------------------------------------------------


def test_a_child_that_exits_is_restarted_after_its_backoff(instance: HostingInstance) -> None:
    old = _live_pid(instance, D)
    mark = instance.mark()
    killed_at = time.monotonic()
    _kill(instance, D)
    instance.wait_for(rf"worker-{D} crashed \(exited with code -?\d+\): restarting in 1s", after=mark)
    row = instance.until(
        lambda: (lambda r: r if r["state"] == "ready" and r["pid"] not in (0, old) else None)(instance.row(_w(D))),
        what="D restarted",
    )
    assert time.monotonic() - killed_at >= 1.0
    assert row["restarts"] == 1


def test_failed_bus_health_checks_restart_a_child(instance: HostingInstance) -> None:
    old = _live_pid(instance, E)
    gone = identify(old)  # its pid AND creation time (T15 fix round 2, N2)
    mark = instance.mark()
    instance.set_mode(_w(E), "no_bus_health")
    instance.wait_for(rf"worker-{E} crashed \(2 failed bus health checks\)", after=mark)
    instance.set_mode(_w(E), "healthy")
    instance.until(
        lambda: (lambda r: r if r["state"] == "ready" and r["pid"] not in (0, old) else None)(instance.row(_w(E))),
        what="E restarted",
    )
    assert not alive(gone)


def test_a_failing_http_check_marks_degraded_and_restarts_nothing(instance: HostingInstance) -> None:
    old = _live_pid(instance, B)
    mark = instance.mark()
    instance.set_mode(_w(B), "http_500")
    instance.wait_state(_w(B), "degraded")
    instance.wait_for(rf"worker-{B} is degraded.*event=unhealthy", after=mark)
    # Three more failing checks later it is the same process, still degraded.
    assert instance.wait_checks(_w(B), 3).endswith("555")
    row = instance.row(_w(B))
    assert row["state"] == "degraded" and row["pid"] == old and row["restarts"] == 0
    instance.set_mode(_w(B), "healthy")
    row = instance.wait_state(_w(B), "ready")
    assert row["pid"] == old


def test_a_child_with_no_ready_within_boot_seconds_is_restarted(instance: HostingInstance) -> None:
    instance.set_mode(_w(F), "no_ready")
    mark = instance.mark()
    reply = instance.call("stories.restart", {"slug": F, "actor": "tester"})
    assert reply["ok"], reply
    assert instance.wait_op(reply["result"]["op_id"])["status"] == "done"
    instance.wait_for(rf"worker-{F} crashed \(no ready within boot_seconds \(3\)\)", after=mark, timeout=10)
    instance.set_mode(_w(F), "healthy")
    row = instance.wait_state(_w(F), "ready", timeout=10)
    assert row["restarts"] == 1  # the boot deadline is a crash; the admin's restart is not


def test_a_crash_loop_is_held_down_and_admin_restarts_do_not_count(instance: HostingInstance) -> None:
    # Two admin restarts first: they must not count toward max_restarts (2).
    for _ in range(2):
        reply = instance.call("stories.restart", {"slug": C})
        assert instance.wait_op(reply["result"]["op_id"])["status"] == "done"
        instance.wait_state(_w(C), "ready")
    assert instance.row(_w(C))["restarts"] == 0
    instance.set_mode(_w(C), "exit_now")
    mark = instance.mark()
    _kill(instance, C)
    instance.wait_for(rf"worker-{C} crashed .*restarting in 1s", after=mark)
    instance.wait_for(rf"worker-{C} crashed .*restarting in 2s", after=mark, timeout=10)
    instance.wait_for(rf"worker-{C} held down: .* after 2 crash restarts", after=mark, timeout=10)
    row = instance.wait_state(_w(C), "held_down")
    assert row["pid"] == 0
    # Nothing restarts it on its own: three health rounds later (the front
    # door's checks are the clock), it is still held down with no process.
    instance.wait_checks("frontdoor", 3)
    row = instance.row(_w(C))
    assert row["state"] == "held_down" and row["pid"] == 0
    # ... but an admin does.
    instance.set_mode(_w(C), "healthy")
    reply = instance.call("stories.restart", {"slug": C})
    op = instance.wait_op(reply["result"]["op_id"])
    assert [s["status"] for s in op["steps"]] == ["queued", "restarting", "done"]
    row = instance.wait_state(_w(C), "ready")
    assert row["restarts"] == 0


# -- operations ----------------------------------------------------------------------------


def test_stop_answers_at_once_drains_and_stops_and_the_table_shows_each_step(
    instance: HostingInstance,
) -> None:
    old = identify(_live_pid(instance, D))
    began = time.monotonic()
    reply = instance.call("stories.stop", {"slug": D, "actor": "tester"})
    assert time.monotonic() - began < 2.0
    assert reply["ok"] and set(reply["result"]) == {"op_id"}
    op = instance.wait_op(reply["result"]["op_id"])
    assert [s["status"] for s in op["steps"]] == ["queued", "draining", "done"]
    assert op["slug"] == D and op["actor"] == "tester" and op["kind"] == "stories.stop"
    assert instance.row(_w(D))["state"] == "stopped"
    instance.until(lambda: not alive(old), what="D's process gone")
    reply = instance.call("stories.start", {"slug": D})
    op = instance.wait_op(reply["result"]["op_id"])
    assert [s["status"] for s in op["steps"]] == ["queued", "restarting", "done"]
    instance.wait_state(_w(D), "ready")


def test_a_drain_that_runs_out_refuses_the_stop_and_a_second_op_is_refused(
    instance: HostingInstance,
) -> None:
    old = _live_pid(instance, A)
    instance.set_mode(_w(A), "hold_turn")
    try:
        # A's turn holds a narration ticket in the supervisor's queue (T11).
        instance.until(lambda: _holds_narration(instance, A), what="A holding a narration ticket")
        reply = instance.call("stories.stop", {"slug": A})
        assert reply["ok"], reply
        second = instance.call("stories.restart", {"slug": B})
        assert second == {"ok": False, "error": "busy"}
        op = instance.wait_op(reply["result"]["op_id"])
    finally:
        instance.set_mode(_w(A), "healthy")
    assert op["status"] == "refused"
    assert op["reason"] == "turns are still running; the story was not stopped"
    assert [s["status"] for s in op["steps"]] == ["queued", "draining", "refused"]
    row = instance.wait_state(_w(A), "ready")
    assert row["pid"] == old
    # The refused drain resumed the story, and the turn's ticket came back.
    instance.until(lambda: not _holds_narration(instance, A), what="A's ticket released")
    snapshot = instance.call("queue.snapshot")["result"]
    assert A not in snapshot["paused_stories"] and A not in snapshot["closing_stories"]


def _holds_narration(instance: HostingInstance, slug: str) -> bool:
    reply = instance.call("queue.snapshot")
    assert reply["ok"], reply
    lane = next(row for row in reply["result"]["lanes"] if row["lane"] == "narration")
    return any(holder["story"] == slug for holder in lane["holders"])


def test_an_unknown_story_and_a_worker_s_call_are_refused(instance: HostingInstance) -> None:
    assert instance.call("stories.stop", {"slug": "no-such-story"}) == {
        "ok": False,
        "error": "unknown_story",
    }
    assert instance.call("stories.stop", {}) == {"ok": False, "error": "bad_args"}


# -- the shutdown and the logs (a fresh instance: the shutdown ends it) -------------------


@pytest.fixture(scope="module")
def spent(tmp_path_factory: pytest.TempPathFactory) -> Iterator[dict[str, Any]]:
    """
    A FRESH instance, run to its end: its shutdown is the thing tested. One
    worker ignores the bus ``shutdown`` (so it is terminated); one wrote 2.5 MB
    at start (its log rotated at ``log_max_mb: 1``).
    """
    inst = HostingInstance(
        tmp_path_factory.mktemp("spent"),
        stories=[A, B],
        modes={_w(B): "ignore_shutdown", _w(A): "spew 2500000"},
        # A (fake) front door too, since T18 fix round 1: it is stopped LAST.
        frontdoor=True,
    )
    inst.start()
    try:
        children = inst.children()  # pid AND creation time (T15 fix round 2, N2)
        mark = inst.mark()
        began = time.monotonic()
        code = inst.stop(timeout=30)
        took = time.monotonic() - began
        yield {"instance": inst, "children": children, "mark": mark, "code": code, "took": took}
    finally:
        inst.stop()


def test_shutdown_stops_every_child_within_shutdown_seconds(spent: dict[str, Any]) -> None:
    inst: HostingInstance = spent["instance"]
    assert spent["code"] == 0
    # Within shutdown_seconds, plus the interpreter's own exit (T10 fix round
    # 1: nothing after the deadline may wait past it).
    assert spent["took"] < inst.supervisor_keys["shutdown_seconds"] + 2
    assert spent["children"] and not [child for child in spent["children"] if alive(child)]
    after = inst.lines[spent["mark"] :]
    text = "\n".join(after)
    assert "Shutting down (operation=shutdown" in text
    assert re.search(rf"Stopped worker-{A} \(operation=stop, how=exited\)", text)
    assert re.search(rf"Terminating worker-{B}", text)
    assert re.search(rf"Stopped worker-{B} \(operation=stop, how=terminated\)", text)
    # Nothing was restarted once the shutdown began.
    begun = next(i for i, line in enumerate(after) if "Shutting down" in line)
    assert not [line for line in after[begun:] if "Started worker-" in line or "restarting in" in line]


def test_the_front_door_is_stopped_only_after_every_worker(spent: dict[str, Any]) -> None:
    """
    T18 fix round 1: the workers drain and stop first (B only after its
    terminate grace), and the front door is stopped after both, so a turn
    drained to its end still reaches its player through the relay.
    """
    after = spent["instance"].lines[spent["mark"] :]

    def first(pattern: str) -> int:
        return next(i for i, line in enumerate(after) if re.search(pattern, line))

    door = first(r"Stopped frontdoor \(operation=stop")
    assert first(rf"Stopped worker-{A} \(operation=stop") < door
    assert first(rf"Stopped worker-{B} \(operation=stop, how=terminated\)") < door


def test_each_child_s_log_is_written_and_rotated(spent: dict[str, Any]) -> None:
    inst: HostingInstance = spent["instance"]
    logs = inst.data_dir / "hosting" / "logs"
    names = sorted(p.name for p in logs.iterdir())
    assert "supervisor.log" in names and f"worker-{B}.log" in names
    assert {f"worker-{A}.log", f"worker-{A}.log.1", f"worker-{A}.log.2"} <= set(names)
    assert f"worker-{A}.log.3" not in names  # log_keep: 2
    for name in (f"worker-{A}.log", f"worker-{A}.log.1"):
        assert (logs / name).stat().st_size <= 1024 * 1024
    assert "fake worker-" in (logs / f"worker-{B}.log").read_text(encoding="utf-8")
    # Echoed to the supervisor's stdout with the process's prefix.
    assert any(line.startswith(f"[worker-{B}] fake worker-{B} starting") for line in inst.lines)


# -- startup refusals ---------------------------------------------------------------------


class _Cfg:
    """A stand-in config: the hosting block and a few dotted keys."""

    def __init__(self, block: dict[str, Any], **keys: Any) -> None:
        self.block = block
        self.keys = keys

    def _raw(self, name: str, default: Any) -> Any:
        return self.block if name == "hosting" else default

    def get(self, key: str, default: Any = None) -> Any:
        return self.keys.get(key, default)


def _block(**changes: Any) -> dict[str, Any]:
    import copy

    import yaml

    from tests.test_hosting_config import DEFAULT

    block = copy.deepcopy(yaml.safe_load(DEFAULT.read_text(encoding="utf-8"))["hosting"])
    block["enabled"] = True
    block.update(changes)
    return block


@pytest.mark.parametrize(
    ("block", "keys", "env", "named"),
    [
        (_block(enabled=False), {}, {}, "hosting.enabled"),
        (_block(stories=[]), {}, {}, "hosting.stories"),
        (_block(stories=[A, "no-such-story"]), {}, {}, "hosting.stories"),
        (_block(), {}, {"CLOCKWORK_STUDIO": "1"}, "CLOCKWORK_STUDIO"),
        (_block(), {"llm.mcp.enabled": True}, {}, "llm.mcp.enabled"),
    ],
)
def test_preflight_refuses_naming_the_key(
    monkeypatch: pytest.MonkeyPatch, block: dict[str, Any], keys: dict[str, Any], env: dict[str, str], named: str
) -> None:
    from engine.hosting.config import HostingConfigError
    from engine.hosting.supervisor.__main__ import preflight

    monkeypatch.delenv("CLOCKWORK_STUDIO", raising=False)
    assert preflight(_Cfg(_block())).stories == ("clockwork-dark",)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    with pytest.raises(HostingConfigError) as caught:
        preflight(_Cfg(block, **keys))
    assert caught.value.key == named
    if named == "hosting.stories" and block["stories"]:
        assert "no-such-story" in str(caught.value)


@pytest.mark.parametrize("env", [{}, {"CLOCKWORK_STUDIO": "1"}])
def test_a_refused_supervisor_exits_1_before_any_child_starts(
    tmp_path: Path, env: dict[str, str]
) -> None:
    """A fresh process each (nothing is started to share): an unknown slug, then the studio."""
    stories = [A, "no-such-story"] if not env else [A]
    inst = HostingInstance(tmp_path, stories=stories, frontdoor=False, wait_ready=False, env=env)
    inst.start()
    try:
        assert inst.proc is not None
        code = inst.proc.wait(30)
    finally:
        inst.stop()
    assert code == 1
    text = "\n".join(inst.lines)
    named = "CLOCKWORK_STUDIO" if env else "hosting.stories: 'no-such-story'"
    assert f"Hosted mode refused to start: {named}" in text
    assert inst.reports() == [] and "Started worker-" not in text


# -- the restart policy, in this process ------------------------------------------------


def test_the_backoff_doubles_to_a_minute() -> None:
    from engine.hosting.supervisor.process import backoff

    assert [backoff(n) for n in range(9)] == [1, 2, 4, 8, 16, 32, 60, 60, 60]


def test_an_admin_restart_keeps_the_crash_history(instance: HostingInstance) -> None:
    """It does not count, and it does not forgive (T10 fix round 1, review #14)."""
    old = _live_pid(instance, A)
    mark = instance.mark()
    _kill(instance, A)
    instance.wait_for(rf"worker-{A} crashed .*restarting in \d+s", after=mark)
    row = instance.until(
        lambda: (lambda r: r if r["state"] == "ready" and r["pid"] not in (0, old) else None)(instance.row(_w(A))),
        what="A restarted",
    )
    before = row["restarts"]
    assert before >= 1
    reply = instance.call("stories.restart", {"slug": A})
    assert instance.wait_op(reply["result"]["op_id"])["status"] == "done"
    assert instance.wait_state(_w(A), "ready")["restarts"] == before


# -- in this process: the supervisor's own robustness (T10 fix round 1) ------------------


def _settings(**changes: Any) -> Any:
    from engine.hosting.config import validate

    return validate(_block(**changes))


@pytest.fixture
def bare(tmp_path: Path) -> Iterator[Any]:
    """A ``Supervisor`` in this process, never started: its bus server runs, no child does."""
    from engine.hosting.supervisor.logs import LogHub
    from engine.hosting.supervisor.server import Supervisor

    hub = LogHub(tmp_path / "logs", max_mb=1, keep=2, echo=None)
    sup = Supervisor(_settings(stories=[A]), hub=hub)
    sup.server.start()
    try:
        yield sup
    finally:
        sup.ops.close()
        sup._health.shutdown(wait=False)
        sup._reaper.shutdown(wait=False)
        # Its audit rows written (under THIS test's storage root) before the
        # test's redirect is undone (T14 fix round 2, N1).
        sup._audit_writer.close(timeout=10)
        sup.server.close()
        hub.close()


def _connect(sup: Any, record: Any) -> Any:
    from engine.hosting.bus import BusClient

    client = BusClient(sup.server.addr, record.token)
    client.on_lost = lambda: None
    client.connect()
    return client


def test_a_token_is_accepted_only_for_a_child_starting_now(bare: Any) -> None:
    from engine.hosting.bus import BusError
    from engine.hosting.supervisor.process import HELD_DOWN, STARTING

    child = bare.children[0]
    child.record = bare.server.mint("worker", story=A, process=child.name)
    child.state = HELD_DOWN
    with pytest.raises(BusError) as caught:
        _connect(bare, child.record)
    assert caught.value.code == "refused"
    child.record = bare.server.mint("worker", story=A, process=child.name)
    child.state = STARTING
    client = _connect(bare, child.record)
    client.close()


def test_ready_is_taken_once_from_a_starting_child(bare: Any) -> None:
    from engine.hosting.bus import BusError
    from engine.hosting.supervisor.process import STARTING

    child = bare.children[0]
    child.record = bare.server.mint("worker", story=A, process=child.name)
    child.state = STARTING
    client = _connect(bare, child.record)
    try:
        assert client.request("ready", {"port": 4000}) == {}
        with pytest.raises(BusError) as caught:
            client.request("ready", {"port": 5000})
        assert caught.value.code == "refused"
        assert child.port == 4000
    finally:
        client.close()


def test_a_crashed_child_s_unused_token_is_retired(bare: Any) -> None:
    child = bare.children[0]
    record = bare.server.mint("worker", story=A, process=child.name)
    child.record = record
    child.stopping = True
    bare._crash(child, "exited with code 1")
    assert record.state == "dead"
    assert child.state == "restarting" and not child.stopping


def test_a_spawn_that_fails_does_not_end_the_tick(bare: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from engine.hosting.supervisor.process import RESTARTING, Child

    child = bare.children[0]
    child.state = RESTARTING
    child.restart_at = 0.0

    def broken(self: Any, **kwargs: Any) -> Any:
        raise OSError("no such executable")

    monkeypatch.setattr(Child, "spawn", broken)
    bare.tick()  # must not raise
    assert child.state == RESTARTING and child.restart_at > time.monotonic()
    assert not child.stopping


def test_a_respawn_that_keeps_failing_is_held_down(bare: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Each failed start is a crash: after max_restarts of them the story is held down (re-review N3)."""
    from engine.hosting.supervisor.process import HELD_DOWN, RESTARTING, Child

    def broken(self: Any, **kwargs: Any) -> Any:
        raise OSError("no such executable")

    monkeypatch.setattr(Child, "spawn", broken)
    child = bare.children[0]
    child.state = RESTARTING
    for _ in range(bare.settings.max_restarts + 1):
        assert child.state == RESTARTING
        child.restart_at = 0.0  # its backoff is over
        bare.tick()
    assert child.state == HELD_DOWN
    assert len(child.crashes) == bare.settings.max_restarts


def test_a_capture_that_fails_after_popen_kills_and_reaps_the_process(
    bare: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from engine.hosting.supervisor.process import RESTARTING, STARTING, Child

    calls: list[str] = []

    class Popen:
        pid = 777
        stdout = None

        def kill(self) -> None:
            calls.append("kill")

        def wait(self, timeout: Any = None) -> int:
            calls.append("wait")
            return -9

        def poll(self) -> Any:
            return None

    def spawn(self: Any, **kwargs: Any) -> Any:
        self.popen = Popen()
        self.record = kwargs["record"]
        self.state = STARTING
        return self.popen

    def no_capture(name: str, stream: Any) -> Any:
        raise OSError("no thread for you")

    monkeypatch.setattr(Child, "spawn", spawn)
    monkeypatch.setattr(bare.hub, "capture", no_capture)
    child = bare.children[0]
    child.state = RESTARTING
    child.restart_at = 0.0
    bare.tick()
    assert calls == ["kill", "wait"]
    assert child.popen is None and child.state == RESTARTING
    assert child.record is not None and child.record.state == "dead"


def test_a_health_check_that_fails_unexpectedly_is_rescheduled(bare: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    child = bare.children[0]
    child.conn = object()
    child.checking = True
    monkeypatch.setattr(bare.server, "request", lambda *a, **k: {})
    monkeypatch.setattr(bare, "_http_ok", lambda port: True)

    def boom(*args: Any) -> None:
        raise RuntimeError("unexpected")

    monkeypatch.setattr(bare, "_apply_health", boom)
    with pytest.raises(RuntimeError):
        bare._check(child)
    assert child.checking is False and child.check_due > time.monotonic()


def test_the_signal_handler_only_records(monkeypatch: pytest.MonkeyPatch, caplog: Any) -> None:
    import signal as signals
    import threading

    from engine.hosting.supervisor import __main__ as entry

    installed: dict[int, Any] = {}
    monkeypatch.setattr(entry.signal, "signal", lambda num, handler: installed.__setitem__(num, handler))
    stop, caught = threading.Event(), []
    entry._install_signals(stop, caught)
    assert signals.SIGINT in installed
    with caplog.at_level(logging.DEBUG):
        installed[signals.SIGINT](signals.SIGINT, None)
    assert caught == [signals.SIGINT] and stop.is_set()
    assert not caplog.records, "the handler logged"


def test_a_child_takes_its_tokens_before_anything_is_activated(monkeypatch: pytest.MonkeyPatch) -> None:
    import signal as signals

    import engine.hosting as hosting
    from engine.hosting import boot

    monkeypatch.setenv("CLOCKWORK_BUS_ADDR", "127.0.0.1:1")
    monkeypatch.setenv("CLOCKWORK_BUS_TOKEN", "a" * 64)
    monkeypatch.setenv("CLOCKWORK_PROXY_TOKEN", "b" * 64)
    seen: dict[str, Any] = {}
    ignored: list[Any] = []

    def serve() -> int:
        seen["env"] = dict(os.environ)
        seen["client"] = hosting._bus_client
        return 0

    monkeypatch.setattr(boot, "serve_worker", serve)
    monkeypatch.setattr(boot.signal, "signal", lambda num, handler: ignored.append((num, handler)))
    try:
        assert boot.main(["--role", "worker"]) == 0
    finally:
        hosting._bus_client = None
    assert "CLOCKWORK_BUS_TOKEN" not in seen["env"] and "CLOCKWORK_PROXY_TOKEN" not in seen["env"]
    assert seen["client"] is not None and seen["client"].proxy_token == "b" * 64
    if hasattr(signals, "SIGBREAK"):
        assert ignored == [(signals.SIGBREAK, signals.SIG_IGN)]
    else:
        assert ignored == []


# -- logs: never blocking, never stopping (T10 fix round 1) ---------------------------------


class _StalledEcho:
    """An echo stream nobody reads: ``write`` blocks until released."""

    def __init__(self) -> None:
        self.release = threading.Event()
        self.lines: list[str] = []

    def write(self, text: str) -> None:
        self.release.wait(30)
        self.lines.append(text)

    def flush(self) -> None:
        return


def test_a_stalled_echo_never_blocks_a_logger(tmp_path: Path) -> None:
    from engine.hosting.supervisor import logs

    echo = _StalledEcho()
    hub = logs.LogHub(tmp_path / "logs", max_mb=50, keep=2, echo=echo)  # type: ignore[arg-type]
    handler = logs.HubHandler(hub)
    record = logging.LogRecord("t", logging.INFO, __file__, 1, "supervisor line %d", (1,), None)
    total = logs.ECHO_QUEUE_LINES + 500
    began = time.monotonic()
    writers = [
        threading.Thread(target=lambda n=n: [hub.line(f"worker-{n}", f"line {i}") for i in range(total // 3)])
        for n in range(3)
    ]
    for thread in writers:
        thread.start()
    for thread in writers:
        thread.join(30)
        assert not thread.is_alive(), "a logger blocked on the stalled echo"
    handler.emit(record)
    assert time.monotonic() - began < 20
    assert hub.dropped > 0  # the echo dropped lines and counted them ...
    for n in range(3):  # ... and every file has every line
        text = (tmp_path / "logs" / f"worker-{n}.log").read_text(encoding="utf-8")
        assert text.count("\n") == total // 3
    echo.release.set()
    hub.close(timeout=10)
    assert any("were not echoed here" in line for line in echo.lines)


def _hold_rotation(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    from engine.hosting.supervisor import logs

    refused: list[str] = []

    def replace(src: Any, dst: Any) -> None:
        refused.append(str(src))
        raise PermissionError(13, "The process cannot access the file", str(src))

    monkeypatch.setattr(logs.os, "replace", replace)
    return refused


def test_a_failed_rotation_keeps_writing_and_retries(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from engine.hosting.supervisor import logs

    log = logs.RotatingLog(tmp_path / "w.log", max_bytes=1024, keep=2)
    with monkeypatch.context() as held:
        refused = _hold_rotation(held)
        for i in range(100):
            log.write(f"line {i:04d} ".encode() + b"x" * 40 + b"\n")  # never raises
        assert refused and log.failed_rotations >= 1
    text = (tmp_path / "w.log").read_text(encoding="utf-8")
    assert "line 0099" in text and "rotation failed" in text
    log.retry_seconds = 0
    log._retry_at = 0.0
    log.write(b"after\n")
    assert (tmp_path / "w.log.1").is_file()
    assert (tmp_path / "w.log").read_text(encoding="utf-8") == "after\n"
    log.close()


@pytest.mark.skipif(os.name != "nt", reason="Windows refuses to rename a file another handle holds open")
def test_a_log_held_open_by_another_reader_keeps_writing(tmp_path: Path) -> None:
    from engine.hosting.supervisor import logs

    log = logs.RotatingLog(tmp_path / "held.log", max_bytes=512, keep=2)
    log.write(b"first\n")
    reader = open(tmp_path / "held.log", "rb")  # an operator's tail, say
    try:
        for i in range(50):
            log.write(f"line {i}\n".encode() + b"y" * 30 + b"\n")
        assert log.failed_rotations >= 1
    finally:
        reader.close()
    assert "line 49" in (tmp_path / "held.log").read_text(encoding="utf-8")
    log._retry_at = 0.0
    log.write(b"rotated\n")
    assert (tmp_path / "held.log.1").is_file()
    log.close()


def test_a_capture_keeps_draining_when_its_file_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """More than a pipe buffer of output, with every rotation failing: the writer is never blocked."""
    from engine.hosting.supervisor import logs

    _hold_rotation(monkeypatch)
    hub = logs.LogHub(tmp_path / "logs", max_mb=1, keep=2, echo=None)
    hub.log("child").max_bytes = 2048
    read_end, write_end = os.pipe()
    capture = hub.capture("child", os.fdopen(read_end, "rb"))
    chunk = (b"z" * 99 + b"\n") * 10

    def writer() -> None:
        with os.fdopen(write_end, "wb") as out:
            for _ in range(400):  # 400 KB, many times a pipe's buffer
                out.write(chunk)

    thread = threading.Thread(target=writer)
    thread.start()
    thread.join(30)
    assert not thread.is_alive(), "the child's pipe stopped being read"
    capture.join(30)
    assert not capture.is_alive()
    assert hub.log("child").failed_rotations >= 1
    hub.close()


# -- the boot runner ---------------------------------------------------------------------


def test_the_boot_runner_reports_the_os_picked_port_in_ready(capsys: pytest.CaptureFixture[str]) -> None:
    import launcher
    from engine.hosting import BUS_EXTENSION
    from engine.hosting.boot import HOSTED_DEV_SERVER_WARNING, serve_worker

    assert HOSTED_DEV_SERVER_WARNING == launcher.HOSTED_DEV_SERVER_WARNING
    sent: list[tuple[str, dict[str, Any]]] = []
    served: list[tuple[str, int]] = []

    class Bus:
        def request(self, op: str, args: dict[str, Any]) -> dict[str, Any]:
            sent.append((op, args))
            return {}

    class App:
        extensions = {BUS_EXTENSION: Bus()}

    class Guard:
        bind_host = "0.0.0.0"

    class Scene:
        host_guard = Guard()

    class Server:
        server_port = 50123

        def serve_forever(self) -> None:
            served.append(("served", self.server_port))

        def server_close(self) -> None:
            served.append(("closed", 0))

    def make_server(host: str, port: int, app: Any, threaded: bool) -> Server:
        assert (host, port, threaded) == ("127.0.0.1", 0, True)
        return Server()

    scene = Scene()
    assert serve_worker(lambda: (scene, App()), make_server=make_server) == 0
    assert sent == [("ready", {"port": 50123})]
    assert served == [("served", 50123), ("closed", 0)]
    # Supervised (T12): the worker keeps answering to the front door's names
    # (the scene's configured host), since the front door keeps the Host.
    assert scene.host_guard.bind_host == "0.0.0.0"
    assert f"WARNING: {HOSTED_DEV_SERVER_WARNING}" in capsys.readouterr().out

    class Standalone:
        extensions: dict[str, Any] = {}

    alone = Scene()
    alone.host_guard = Guard()
    assert serve_worker(lambda: (alone, Standalone()), make_server=make_server) == 0
    assert alone.host_guard.bind_host == "127.0.0.1"


def test_a_real_worker_boots_under_the_supervisor_and_drains_at_shutdown(tmp_path: Path) -> None:
    """
    A fresh instance with the engine's own worker (``python -m
    engine.hosting.boot``), not a probe: it warms, says hello and ``ready``
    with its OS-picked port, answers ``/api/health``, and at the shutdown
    drains and takes the bus ``shutdown``.
    """
    import httpx

    inst = HostingInstance(
        tmp_path,
        stories=[A],
        frontdoor=False,
        wait_ready=False,
        supervisor={"boot_seconds": 120, "drain_seconds": 5, "stop_seconds": 5, "shutdown_seconds": 30},
    )
    inst.command = lambda: [sys.executable, "-u", "-m", "engine.hosting.supervisor"]  # type: ignore[method-assign]
    inst.start()
    try:
        port = int(inst.wait_for(rf"worker-{A} sent ready \(operation=ready, pid=\d+, port=(\d+)\)", 180).group(1))
        inst.wait_for(rf"worker-{A} is ready", 30)
        body = httpx.get(f"http://127.0.0.1:{port}/api/health", trust_env=False).json()
        assert body == {"scene": "clockwork", "status": "ok"}
        from engine.hosting.supervisor.process import gunicorn_runs_here

        if gunicorn_runs_here():
            # T13: on POSIX with gunicorn, the engine's own wsgi module under it.
            assert any(
                f"Started worker-{A} (operation=spawn" in line and "-m gunicorn -c " in line
                and line.endswith("engine.hosting.wsgi:app)")
                for line in inst.lines
            ), [line for line in inst.lines if "operation=spawn" in line]
        else:
            assert any("WARNING: hosted mode under the development server" in line for line in inst.lines)
        mark = inst.mark()
    finally:
        code = inst.stop()
    assert code == 0
    tail = "\n".join(inst.lines[mark:])
    assert "Drained: no turn running (operation=drain)" in tail
    assert f"Stopped worker-{A} (operation=stop, how=exited)" in tail


def test_the_boot_runner_refuses_local_mode_and_a_missing_story(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import engine.config as config
    from engine.hosting.boot import build_worker_app
    from engine.hosting.config import HostingConfigError

    monkeypatch.delenv("CLOCKWORK_GAME", raising=False)
    with pytest.raises(HostingConfigError) as caught:
        build_worker_app()
    assert caught.value.key == "CLOCKWORK_GAME"
    (tmp_path / "config").mkdir()
    monkeypatch.setattr(config, "_CONFIG_DIR", tmp_path / "config")
    monkeypatch.setattr(config, "_instance", None)
    monkeypatch.setenv("CLOCKWORK_GAME", "clockwork-dark")
    with pytest.raises(HostingConfigError) as caught:
        build_worker_app()  # hosting is off in the shipped config
    assert caught.value.key == "hosting.enabled"
    assert "launcher.py" in str(caught.value)


# -- gunicorn's branch (v0.20.0 T13) -----------------------------------------------------

FAKE_GUNICORN = Path(__file__).resolve().parent / "probes" / "fake_gunicorn"


@pytest.fixture
def fake_gunicorn_on_path(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """``tests/probes/fake_gunicorn`` first on ``sys.path``; the fake's modules dropped after."""
    monkeypatch.syspath_prepend(str(FAKE_GUNICORN))
    for name in [m for m in sys.modules if m == "gunicorn" or m.startswith("gunicorn.")]:
        monkeypatch.delitem(sys.modules, name)
    try:
        yield
    finally:
        for name in [m for m in sys.modules if m == "gunicorn" or m.startswith("gunicorn.")]:
            del sys.modules[name]


def test_without_gunicorn_each_child_runs_the_boot_runner() -> None:
    """As on this workstation (no gunicorn, or Windows): the Werkzeug runner, for both roles."""
    from engine.hosting.supervisor.process import DEFAULT_WSGI, child_command, gunicorn_runs_here

    if gunicorn_runs_here():
        pytest.skip("gunicorn runs here (the Linux container, CI): the branch below is the one taken")
    for role in ("worker", "frontdoor"):
        assert child_command("engine.hosting.boot", role, DEFAULT_WSGI[role]) == [
            sys.executable, "-u", "-m", "engine.hosting.boot", "--role", role
        ]


def test_with_gunicorn_each_child_is_gunicorn_with_the_conf_and_its_role_s_module(
    fake_gunicorn_on_path: None,
) -> None:
    from engine.hosting.supervisor.__main__ import wsgi_for
    from engine.hosting.supervisor.process import GUNICORN_CONF, child_command, gunicorn_runs_here

    assert gunicorn_runs_here()
    assert GUNICORN_CONF.is_file() and GUNICORN_CONF.name == "gunicorn.conf.py"
    worker = wsgi_for("engine.hosting.boot", None, "engine.hosting.boot", "worker")
    front = wsgi_for("engine.hosting.boot", None, "engine.hosting.boot", "frontdoor")
    assert (worker, front) == ("engine.hosting.wsgi", "engine.hosting.frontdoor.wsgi")
    assert child_command("engine.hosting.boot", "worker", worker) == [
        sys.executable, "-m", "gunicorn", "-c", str(GUNICORN_CONF), "engine.hosting.wsgi:app"
    ]
    assert child_command("engine.hosting.boot", "frontdoor", front) == [
        sys.executable, "-m", "gunicorn", "-c", str(GUNICORN_CONF), "engine.hosting.frontdoor.wsgi:app"
    ]
    # A test probe's runner with no wsgi module of its own runs as itself.
    assert wsgi_for("tests.probes.fake_worker", None, "engine.hosting.boot", "worker") == ""
    assert child_command("tests.probes.fake_worker", "worker", "") == [
        sys.executable, "-u", "-m", "tests.probes.fake_worker", "--role", "worker"
    ]


def test_no_child_inherits_gunicorn_s_override_variables() -> None:
    """Fix round 1, I3: GUNICORN_CMD_ARGS and WEB_CONCURRENCY never reach a child."""
    from engine.hosting.supervisor.process import GUNICORN_OVERRIDE_ENV, child_env

    base = {"PATH": "x", "GUNICORN_CMD_ARGS": "--bind 0.0.0.0:8000", "WEB_CONCURRENCY": "4"}
    for role in ("worker", "frontdoor"):
        env = child_env(base, addr="127.0.0.1:1", token="t" * 64, role=role, slug=A)
        assert not GUNICORN_OVERRIDE_ENV & set(env), env
        assert env["PATH"] == "x"


def test_gunicorn_s_command_args_cannot_rebind_a_worker(tmp_path: Path) -> None:
    """
    Fix round 1, I3 and M4, under the fake gunicorn (which resolves settings
    as gunicorn does: GUNICORN_CMD_ARGS over the file, WEB_CONCURRENCY only a
    default): started by hand with ``--bind 0.0.0.0:...`` in
    GUNICORN_CMD_ARGS, the conf's ``on_starting`` refuses and gunicorn exits
    1 before binding; WEB_CONCURRENCY alone changes nothing.
    """
    from engine.hosting.supervisor.process import GUNICORN_CONF

    env = {k: v for k, v in os.environ.items() if k not in ("GUNICORN_CMD_ARGS", "WEB_CONCURRENCY")}
    env["PYTHONPATH"] = os.pathsep.join([str(FAKE_GUNICORN), *filter(None, [os.environ.get("PYTHONPATH")])])
    env["CLOCKWORK_BUS_ROLE"] = "worker"
    env["GUNICORN_CMD_ARGS"] = "--bind 0.0.0.0:0"
    done = subprocess.run(
        [sys.executable, "-m", "gunicorn", "-c", str(GUNICORN_CONF), "tests.probes.fake_gunicorn_app:app"],
        cwd=str(Path(__file__).resolve().parents[1]),
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        timeout=120,
    )
    err = done.stderr.decode("utf-8", "replace")
    assert done.returncode == 1, (done.returncode, err[-500:])
    assert "Error:" in err and "loopback only" in err and "GUNICORN_CMD_ARGS" in err


def test_under_gunicorn_a_closed_bus_link_restarts_the_master(tmp_path: Path) -> None:
    """
    Under the fake gunicorn (spec §14.3): the supervisor starts gunicorn with
    the conf; the fake master plays gunicorn replacing its worker while the
    master runs on -- a second worker presents the token already used, and is
    refused; then the first worker goes and the bus link closes. The
    supervisor takes the closed link as the child down: it terminates the
    master and starts a new one with a fresh token, which comes up ready.
    A fresh instance: it needs gunicorn on the children's path.
    """
    env = {
        "PYTHONPATH": os.pathsep.join([str(FAKE_GUNICORN), *filter(None, [os.environ.get("PYTHONPATH")])]),
        # Fix round 1, I3: an operator's GUNICORN_CMD_ARGS would rebind every
        # worker off loopback, which the conf refuses; the supervisor never
        # passes it on, so the children start.
        "GUNICORN_CMD_ARGS": "--bind 0.0.0.0:8123 --max-requests 5",
        "WEB_CONCURRENCY": "3",
    }
    inst = HostingInstance(tmp_path, stories=[A], frontdoor=False, env=env, wait_ready=False)
    inst.command = lambda: [  # type: ignore[method-assign]
        sys.executable, "-u", "-m", "engine.hosting.supervisor",
        "--worker-module", "tests.probes.fake_worker",
        "--worker-wsgi", "tests.probes.fake_gunicorn_app",
        "--no-frontdoor",
    ]
    inst.start()
    try:
        first = inst.wait_for(rf"Started worker-{A} \(operation=spawn, pid=(\d+), state=starting, command=(.*)\)", 30)
        assert first.group(2).startswith("-m gunicorn -c ") and first.group(2).endswith(
            "gunicorn.conf.py tests.probes.fake_gunicorn_app:app"
        ), first.group(2)
        master = int(first.group(1))
        master_identity = identify(master)  # noted while it is certainly the master (N2)
        inst.wait_for(rf"worker-{A} is ready", 60)
        mark = inst.mark()
        (inst.control / f"worker-{A}.gunicorn_restart").write_text("1", encoding="ascii")
        inst.wait_for(rf"hello refused \(error=refused, for=worker-{A}, credential=live\)", 60, after=mark)
        assert inst.until(lambda: (inst.control / f"worker-{A}.second_hello").is_file(), 30)
        assert (inst.control / f"worker-{A}.second_hello").read_text(encoding="ascii") == "3"
        inst.wait_for(rf"worker-{A} crashed \(the bus link closed\)", 30, after=mark)
        again = inst.wait_for(rf"Started worker-{A} \(operation=spawn, pid=(\d+)", 30, after=mark)
        assert int(again.group(1)) != master
        inst.wait_for(rf"worker-{A} is ready", 60, after=mark)
        inst.until(lambda: not alive(master_identity), 15, "the old master was stopped")
    finally:
        inst.stop()


# -- local mode never spawns it ------------------------------------------------------------


def test_local_mode_spawns_no_hosting_process(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``launcher.main([])`` with hosting off, the stack stubbed as T1's golden stubs it."""
    import contextlib
    import io

    import launcher
    from engine.scenes import default_scene

    spawned: list[Any] = []
    real_init = subprocess.Popen.__init__

    def spy(self: Any, args: Any, *rest: Any, **kwargs: Any) -> None:
        spawned.append(args)
        real_init(self, args, *rest, **kwargs)

    with local_golden.pinned(monkeypatch, tmp_path / "config", tmp_path / "data"):
        monkeypatch.setattr(subprocess.Popen, "__init__", spy)
        monkeypatch.setattr(default_scene, "run_scene", lambda **kw: None)
        with contextlib.redirect_stdout(io.StringIO()):
            assert launcher.main([]) == 0
    argvs = [" ".join(map(str, a)) if isinstance(a, (list, tuple)) else str(a) for a in spawned]
    assert not [argv for argv in argvs if "engine.hosting" in argv], argvs


# -- the front door child (v0.20.0 T12) ------------------------------------------------------


def test_the_front_door_child_is_started_after_the_workers(instance: HostingInstance) -> None:
    """Spec §14.3, step 4: every worker, in list order, and then the front door."""
    started = [
        m.group(1)
        for m in (re.search(r"Started (\S+) \(operation=spawn", line) for line in instance.lines)
        if m
    ]
    first = started[: len(instance.stories) + 1]
    assert first == [_w(s) for s in instance.stories] + ["frontdoor"], started


def test_every_child_gets_one_proxy_token_per_supervisor_start(instance: HostingInstance) -> None:
    """
    ``CLOCKWORK_PROXY_TOKEN`` reaches every child in its environment -- 64
    hex characters, the fake worker reports its length -- and is deleted once
    read (the probe reports the NAMES of its variables after it connected);
    never on argv.
    """
    reports = [r for r in instance.reports() if "env_keys" in r]
    assert reports, "no probe reported its environment"
    for report in reports:
        assert "CLOCKWORK_PROXY_TOKEN" not in report["env_keys"], report["process"]
        assert report["proxy_token_chars"] == 64, report["process"]
    assert not [arg for arg in instance.command() if "PROXY" in arg.upper()]


def test_a_held_down_front_door_ends_the_supervisor_non_zero(tmp_path: Path) -> None:
    """
    A FRESH instance (it ends): the front door exits at once on every start,
    so after ``max_restarts`` (2 here) it is held down -- and an instance with
    no front door serves nobody, so the supervisor stops everything and exits
    1 (spec §14.3), for the container's or systemd's restart policy.
    """
    inst = HostingInstance(tmp_path, stories=[A], modes={"frontdoor": "exit_now"}, wait_ready=False)
    inst.start()
    try:
        assert inst.proc is not None
        code = inst.proc.wait(60)
    finally:
        inst.stop()
    assert code == 1
    text = "\n".join(inst.lines)
    assert "frontdoor held down" in text
    assert "The front door is held down: exiting (operation=restart)" in text
    assert f"Stopped {_w(A)}" in text


def _hosting_on(config_dir: Path) -> None:
    import engine.config as config
    import yaml

    (config_dir / "local.yaml").write_text(
        yaml.safe_dump({"hosting": {"enabled": True, "stories": [A]}}), encoding="utf-8"
    )
    config._instance = None


def test_the_launcher_with_hosting_on_runs_the_supervisor(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Spec §7.2 (T12): ``launcher.main([])`` with hosting on runs the
    supervisor's own ``main`` in the foreground (stubbed here), after the
    WARNING, and never builds the scene in this process.
    """
    import contextlib
    import io

    import launcher
    import engine.hosting.supervisor.__main__ as supervisor_main
    from engine.scenes import default_scene

    ran: list[Any] = []
    with local_golden.pinned(monkeypatch, tmp_path / "config", tmp_path / "data"):
        _hosting_on(tmp_path / "config")
        monkeypatch.setattr(supervisor_main, "main", lambda argv=None: ran.append(("supervisor", argv)) or 0)
        monkeypatch.setattr(default_scene, "run_scene", lambda **kw: ran.append(("scene", kw)))
        text = io.StringIO()
        with contextlib.redirect_stdout(text):
            assert launcher.main([]) == 0
    assert ran == [("supervisor", [])]
    assert "WARNING: " + launcher.HOSTED_DEV_SERVER_WARNING in text.getvalue()


def test_the_launcher_check_adds_the_hosted_row_only_with_hosting_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Spec §7.4 (T12): ``--check`` with hosting on prints the stack's table as
    ever, then the front door's ``GET /api/health`` and the logs' path. With
    hosting off it is the local golden's ``launcher_check.txt``, unchanged.
    """
    import contextlib
    import io
    import json

    import launcher

    recorded = (local_golden.FIXTURES / "launcher_check.txt").read_text(encoding="utf-8")
    probed: list[str] = []
    with local_golden.pinned(monkeypatch, tmp_path / "config", tmp_path / "data") as stack_calls:
        off = local_golden.launcher_runs(monkeypatch, stack_calls)["launcher_check.txt"]
        _hosting_on(tmp_path / "config")
        monkeypatch.setattr(launcher, "_frontdoor_health", lambda url: probed.append(url) or (False, "ConnectError"))
        stack_calls.clear()
        text = io.StringIO()
        with contextlib.redirect_stdout(text):
            code = launcher.main(["--check"])
        on = text.getvalue() + f"--- exit {code}\n--- stack calls {json.dumps(stack_calls)}\n"
    assert off == recorded
    table = recorded.split("--- exit")[0]
    assert on.startswith(table)
    hosted = on[len(table) :]
    logs = str((tmp_path / "data" / "hosting" / "logs").resolve())
    assert "Hosted mode (python -m engine.hosting.supervisor):" in hosted
    assert "front door  down" in hosted and "/api/health (ConnectError)" in hosted
    assert logs in hosted or str(tmp_path / "data" / "hosting" / "logs") in hosted
    assert probed and probed[0].endswith(":5573/api/health"), probed


def test_the_launcher_refuses_the_studio_with_hosting_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """
    Fix round 1 (M5, spec §6.7): ``launcher.py --studio`` with hosting on is
    refused at once, exit 1, naming ``--studio``, before any supervisor
    runs and without setting ``CLOCKWORK_STUDIO`` for children to inherit.
    On eb1d4d4 it set the flag and ran the supervisor, whose workers each
    refused it and crash-looped until held down.
    """
    import launcher
    import engine.hosting.supervisor.__main__ as supervisor_main

    ran: list[Any] = []
    monkeypatch.setenv("CLOCKWORK_STUDIO", "0")  # recorded, so the variable is restored whatever happens
    monkeypatch.delenv("CLOCKWORK_STUDIO")
    with local_golden.pinned(monkeypatch, tmp_path / "config", tmp_path / "data"):
        _hosting_on(tmp_path / "config")
        monkeypatch.setattr(supervisor_main, "main", lambda argv=None: ran.append(argv) or 0)
        assert launcher.main(["--studio"]) == 1
        assert "CLOCKWORK_STUDIO" not in os.environ
    assert ran == []
    err = capsys.readouterr().err
    assert "Hosted mode refused to start: --studio" in err


# -- the orphan guard: a pid is not a process (v0.20.0 T15 fix round 1, I2) ----------------


def _idle_child() -> subprocess.Popen:
    """A process this test starts and owns: the stand-in for a stranger holding a reused pid."""
    from tests.hosting_instance import REPO

    return subprocess.Popen(  # noqa: S603 -- sys.executable and -m, no shell
        [sys.executable, "-m", "tests.probes.idle_child"],
        cwd=str(REPO),
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _stop_idle(child: subprocess.Popen) -> None:
    try:
        if child.stdin is not None:
            child.stdin.close()
        child.wait(15)
    except subprocess.TimeoutExpired:
        child.kill()
        child.wait(15)


def _guard_on(tmp_path: Path, reports: list[dict[str, Any]]) -> HostingInstance:
    inst = HostingInstance(tmp_path, stories=[A])
    inst.control.mkdir(parents=True, exist_ok=True)
    for number, report in enumerate(reports):
        (inst.control / f"worker-{A}-{number}.json").write_text(json.dumps(report), encoding="utf-8")
    return inst


def test_the_orphan_guard_never_signals_a_reused_pid(tmp_path: Path) -> None:
    """
    A probe reported a pid that now belongs to ANOTHER process (simulated with
    a process this test started, under a different creation time), and a
    report with no creation time at all: the guard counts neither, signals
    neither and passes. On 1261d42 it took the bare pid as the orphan,
    terminated it and failed.
    """
    from tests.process_identity import created

    stranger = _idle_child()
    try:
        born = created(stranger.pid)
        assert born is not None, "the stand-in's creation time could not be read"
        inst = _guard_on(
            tmp_path,
            [{"pid": stranger.pid, "created": born - 1000.0}, {"pid": stranger.pid}],
        )
        inst._no_orphans(timeout=0.5)
        assert stranger.poll() is None, "the guard signalled a process that is not its child"
        assert created(stranger.pid) == born
    finally:
        _stop_idle(stranger)


def test_creation_times_match_exactly_and_an_unknown_one_never_matches(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    T15 fix round 2 (N6): the comparison's tolerance is documented and zero
    -- neither platform's clock jitters (Linux reads the start time in ticks
    since boot, never ``btime``, which wobbles) -- and fail safe: an unknown
    creation time never matches, so it is never signalled.
    """
    from pathlib import Path as _Path

    from engine.hosting import process_identity

    assert process_identity.TOLERANCE_SECONDS == 0.0
    assert process_identity.same(12.5, 12.5)
    assert not process_identity.same(12.5, 12.51) and not process_identity.same(12.5, 12.49)
    assert not process_identity.same(None, 12.5) and not process_identity.same(12.5, None)
    assert not process_identity.alive(process_identity.Identity(os.getpid(), None))
    assert process_identity.alive(process_identity.me()), "this process is not alive by its own identity"
    # The Linux reader never reads /proc/stat (btime): only /proc/<pid>/stat.
    read: list[str] = []
    real = _Path.read_text

    def spy(self: Any, *args: Any, **kwargs: Any) -> str:
        read.append(str(self).replace("\\", "/"))
        return real(self, *args, **kwargs)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(_Path, "read_text", spy)
        process_identity._linux_created(os.getpid())
    assert not [p for p in read if p.endswith("/proc/stat")], read


class _FakeBus:
    """What ``boot.report_ready`` needs of a bus: hooks it sets, and ``ready``."""

    def __init__(self) -> None:
        self.on_shutdown: Any = None
        self.on_lost: Any = None
        self.sent: list[Any] = []

    def request(self, op: str, args: Any = None, **_kwargs: Any) -> dict[str, Any]:
        self.sent.append((op, args))
        return {}


def test_a_gunicorn_worker_never_signals_its_master_s_pid_once_another_process_has_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    T15 fix round 2 (N1): a gunicorn worker notes its master's identity
    (pid and creation time) when it reports ``ready``, and its lost link
    signals the master only if the pid's process still has that creation
    time. Simulated on a process THIS test starts and owns: the noted master
    was "born" earlier than the process now holding the pid (a reused pid).
    The stand-in survives and the worker still leaves. On 9098e90,
    ``stop_master`` SIGTERMed the bare pid and killed the stand-in.
    """
    import importlib
    from types import SimpleNamespace

    from engine.hosting import BUS_EXTENSION, boot
    from engine.hosting import bus as bus_module

    exits: list[int] = []
    monkeypatch.setattr(bus_module, "_exit_process", exits.append)
    stranger = _idle_child()
    try:
        try:
            identity = importlib.import_module("engine.hosting.process_identity")
        except ImportError:  # 9098e90: no identities at all
            identity = None
        bus = _FakeBus()
        app = SimpleNamespace(extensions={BUS_EXTENSION: bus})
        with pytest.MonkeyPatch.context() as clock:  # its own: only this patch is undone
            if identity is not None:
                assert identity.created(stranger.pid) is not None
                # The master the worker noted started 1000 s before whatever holds the pid now.
                clock.setattr(identity, "created", lambda pid, _real=identity.created: _real(pid) - 1000.0)
            boot.report_ready(app, 4321, master_pid=stranger.pid)
        # The clock is the real one again: the pid's process is not the noted master.
        assert bus.sent == [("ready", {"port": 4321})]
        bus.on_lost()
        threading.Event().wait(0.5)
        assert stranger.poll() is None, "the worker signalled a pid its master no longer holds"
        assert exits == [bus_module.LIFELINE_EXIT_CODE]
    finally:
        _stop_idle(stranger)


def test_a_gunicorn_worker_does_signal_the_master_it_noted(monkeypatch: pytest.MonkeyPatch) -> None:
    """The control: the master noted at ``ready`` and still running IS stopped by a shutdown."""
    from types import SimpleNamespace

    from engine.hosting import BUS_EXTENSION, boot
    from engine.hosting import bus as bus_module

    exits: list[int] = []
    monkeypatch.setattr(bus_module, "_exit_process", exits.append)
    master = _idle_child()
    try:
        bus = _FakeBus()
        boot.report_ready(SimpleNamespace(extensions={BUS_EXTENSION: bus}), 4321, master_pid=master.pid)
        bus.on_shutdown()
        master.wait(15)
        assert exits == [0]
    finally:
        _stop_idle(master)


def test_the_orphan_guard_still_ends_and_reports_a_verified_child(tmp_path: Path) -> None:
    """The control: a reported pid whose creation time matches IS the child, and is terminated and reported."""
    from tests.process_identity import created

    child = _idle_child()
    try:
        inst = _guard_on(tmp_path, [{"pid": child.pid, "created": created(child.pid)}])
        with pytest.raises(AssertionError, match="outlived their supervisor"):
            inst._no_orphans(timeout=0.5)
        child.wait(15)
    finally:
        _stop_idle(child)
