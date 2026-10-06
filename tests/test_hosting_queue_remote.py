"""
One queue across processes (v0.20.0 T11, spec §14.4, §14.3's drain, §5.4).

Most of this file runs against ONE real instance (``tests/hosting_instance.py``,
spec §9.10's budget): a supervisor whose three workers are
``tests/probes/lane_client.py`` -- bus clients that queue in the supervisor's
lanes through the engine's own ``RemoteLanes``, on command -- and a probe
front door whose relay reads ``queue.snapshot``. Each test uses its own
accounts and releases what it took, so the shared queue is empty between
tests. A worker the test kills (its crash restart is counted) is the third
story, which nothing else uses.

Grants are read from the supervisor's merged output (``LANE GRANT ...`` lines
each probe prints), waited for on the instance's own condition, never slept
for. Two things run in this process instead, each saying why: the resize
refusal (no bus op resizes; the operator's model apply, T16, will) and the
``max_hold_seconds`` restart (the shipped cross-check keeps a configured hold
above 3 x ``llm.timeout_seconds`` + 60, a minute at least, so the test runs a
supervisor here with a two-second hold and a real lane_client child).
"""

from __future__ import annotations

import dataclasses
import json
import logging
import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Iterator

import pytest

from tests.hosting_instance import CONTROL_ENV, LANE_CLIENT, REPO, HostingInstance, hosting_instance
from tests.process_identity import alive

#: Three stories, one lane_client each.
A, B, C = "clockwork-dark", "wicked-garden", "neon-city"

#: The drain a stop or restart waits at most, in this instance (seconds).
DRAIN = 4

JOIN = 20.0


@pytest.fixture(scope="module")
def instance(tmp_path_factory: pytest.TempPathFactory) -> Iterator[HostingInstance]:
    yield from hosting_instance(
        tmp_path_factory,
        "queue",
        stories=[A, B, C],
        worker_module=LANE_CLIENT,
        supervisor={"drain_seconds": DRAIN, "shutdown_seconds": DRAIN + 2 + 7 + 10 + 2},  # +10: the front door's reserve (T18)
        extra={"llm": {"lanes": {"narration": 1, "utility": 2}}},
    )


_accounts = iter(range(1, 10_000))


def _account() -> str:
    """A fresh account id (``u_`` and 12 hex digits), unique in this module."""
    return f"u_{next(_accounts):012x}"


def _snap(instance: HostingInstance) -> dict[str, Any]:
    reply = instance.call("queue.snapshot")
    assert reply["ok"], reply
    return reply["result"]


def _lane(snapshot: dict[str, Any], lane: str = "narration") -> dict[str, Any]:
    return next(row for row in snapshot["lanes"] if row["lane"] == lane)


def _acquire(instance: HostingInstance, slug: str, name: str, account: str, lane: str = "narration", **extra: Any) -> None:
    reply = instance.tell(slug, {"cmd": "acquire", "name": name, "lane": lane, "account": account, "timeout": 30, **extra})
    assert reply == {"ok": True}, reply


def _release(instance: HostingInstance, slug: str, name: str) -> float:
    reply = instance.tell(slug, {"cmd": "release", "name": name})
    assert reply["ok"], reply
    return float(reply["took"])


def _granted(instance: HostingInstance, name: str, after: int, timeout: float = 10.0) -> re.Match[str]:
    return instance.wait_for(rf"LANE GRANT name={re.escape(name)} lane=\w+ t=(\d+)", timeout, after=after)


def _refused(instance: HostingInstance, name: str, after: int, timeout: float = 10.0) -> str:
    return instance.wait_for(rf"LANE REFUSED name={re.escape(name)} reason=(\w+)", timeout, after=after).group(1)


def _waiting(instance: HostingInstance, count: int, lane: str = "narration") -> dict[str, Any]:
    """Until ``lane`` has ``count`` waiters; the snapshot."""
    return instance.until(
        lambda: (lambda s: s if len(_lane(s, lane)["waiters"]) == count else None)(_snap(instance)),
        what=f"{count} waiting in {lane}",
    )


def _empty(instance: HostingInstance) -> None:
    """Every lane empty again (the tests share the queue)."""
    instance.until(
        lambda: all(not row["holders"] and not row["waiters"] for row in _snap(instance)["lanes"]),
        what="the queue empty",
    )


def _hold(instance: HostingInstance, slug: str, name: str, account: str, lane: str = "narration") -> None:
    mark = instance.mark()
    _acquire(instance, slug, name, account, lane)
    _granted(instance, name, mark)


# -- order and ownership -----------------------------------------------------------------


def test_two_processes_four_threads_each_are_granted_in_global_arrival_order(instance: HostingInstance) -> None:
    """
    One narration slot, held; then eight acquires, alternating between two
    worker processes, each blocking one of that process's four pool threads.
    Every grant follows the global arrival order, whichever process asked.
    """
    _hold(instance, A, "order-h", _account())
    expected: list[tuple[str, str]] = []
    for index in range(8):
        slug = (A, B)[index % 2]
        name = f"order-{index}"
        _acquire(instance, slug, name, _account())
        expected.append((slug, name))
        # Queued before the next one is sent: arrival order is this loop's.
        _waiting(instance, index + 1)
    waiters = _lane(_snap(instance))["waiters"]
    assert [w["story"] for w in waiters] == [slug for slug, _ in expected]

    mark = instance.mark()
    _release(instance, A, "order-h")
    stamps: list[int] = []
    for slug, name in expected:
        found = _granted(instance, name, mark)
        stamps.append(int(found.group(1)))
        _release(instance, slug, name)
    # Each grant came only after the one before it was released, so the
    # supervisor's echo of the two processes' lines is in grant order.
    granted_names = re.findall(r"LANE GRANT name=(order-\d+) ", "\n".join(instance.lines[mark:]))
    assert granted_names == [name for _, name in expected]
    assert stamps == sorted(stamps)
    _empty(instance)


def test_a_release_is_served_at_once_while_every_pool_thread_of_its_process_waits(
    instance: HostingInstance,
) -> None:
    """
    I2: all four of A's pool threads are blocked in acquires; A's
    ``lane.release`` (answered on the supervisor's selector thread, never
    behind an acquire) still comes back at once, and the slot goes on.
    """
    _hold(instance, A, "pool-h", _account())
    names = [f"pool-{i}" for i in range(4)]
    for count, name in enumerate(names, 1):
        _acquire(instance, A, name, _account())
        _waiting(instance, count)
    mark = instance.mark()
    took = _release(instance, A, "pool-h")
    assert took < 1.0, f"a release waited {took:.2f}s behind blocked acquires"
    for name in names:
        _granted(instance, name, mark)
        _release(instance, A, name)
    _empty(instance)


def test_a_second_narration_acquire_for_the_same_account_is_other_window_at_once(
    instance: HostingInstance,
) -> None:
    """
    Spec §5.4 across stories: an account holding narration in story A asks
    for it again from story B and is answered ``other_window`` at once (with
    the slot taken, a plain wait would have run to its deadline); its
    utility acquire is granted as usual.
    """
    account = _account()
    _hold(instance, A, "ow-turn", account)
    mark = instance.mark()
    began = time.monotonic()
    _acquire(instance, B, "ow-second", account)
    assert _refused(instance, "ow-second", mark) == "other_window"
    assert time.monotonic() - began < 3.0
    _acquire(instance, B, "ow-utility", account, lane="utility")
    _granted(instance, "ow-utility", mark)
    _release(instance, B, "ow-utility")
    _release(instance, A, "ow-turn")
    _empty(instance)


def test_a_worker_killed_while_holding_frees_its_ticket_and_its_waits(instance: HostingInstance) -> None:
    """
    Tickets belong to the connection: C is killed while it holds the slot and
    has a wait queued; its ticket and its wait are gone, and B's waiter,
    queued behind both, is granted.
    """
    _hold(instance, C, "kill-h", _account())
    _acquire(instance, C, "kill-wait", _account())
    _waiting(instance, 1)
    _acquire(instance, B, "kill-next", _account())
    snapshot = _waiting(instance, 2)
    assert [w["story"] for w in _lane(snapshot)["waiters"]] == [C, B]
    mark = instance.mark()
    # By its pid AND creation time, never a bare pid (T15 fix round 1, I2).
    killed = instance.own_identity(f"worker-{C}")
    pid = instance.kill_child(f"worker-{C}")
    _granted(instance, "kill-next", mark)
    lane = _lane(_snap(instance))
    assert [h["story"] for h in lane["holders"]] == [B]
    assert lane["waiters"] == []
    _release(instance, B, "kill-next")
    _empty(instance)
    instance.until(lambda: not alive(killed), what="C's process gone")  # its identity, not a bare pid (N2)
    # Restarted as a crash (counted), after its backoff.
    instance.until(lambda: instance.own_pid(f"worker-{C}") != pid, timeout=30, what="C restarted")
    row = instance.wait_state(f"worker-{C}", "ready", timeout=30)
    assert row["restarts"] == 1


# -- pause and drain (design review C1) --------------------------------------------------


def _op(instance: HostingInstance, kind: str, slug: str) -> str:
    reply = instance.call(kind, {"slug": slug, "actor": "tester"})
    assert reply["ok"], reply
    return str(reply["result"]["op_id"])


def _step_at(op: dict[str, Any], status: str) -> float:
    return next(float(step["at"]) for step in op["steps"] if step["status"] == status)


def test_a_paused_turn_s_utility_call_is_granted_and_the_drain_ends_when_it_releases(
    instance: HostingInstance,
) -> None:
    """
    C1: A's turn holds narration when A is restarted. The drain pauses A's
    admissions, and the turn's utility call (same account) is granted at
    once; the drain then completes as soon as the turn releases -- not at
    ``drain_seconds`` -- and the restart goes on.
    """
    account = _account()
    _hold(instance, A, "c1-turn", account)
    op_id = _op(instance, "stories.restart", A)
    instance.until(lambda: A in _snap(instance)["paused_stories"], what="A paused")
    mark = instance.mark()
    began = time.monotonic()
    _acquire(instance, A, "c1-summary", account, lane="utility")
    _granted(instance, "c1-summary", mark, timeout=DRAIN)
    assert time.monotonic() - began < 1.5, "the admitted turn's utility call waited on the pause"
    _release(instance, A, "c1-summary")
    released_at = time.time()
    _release(instance, A, "c1-turn")
    op = instance.wait_op(op_id, timeout=30)
    assert [s["status"] for s in op["steps"]] == ["queued", "draining", "restarting", "done"]
    assert _step_at(op, "restarting") >= released_at - 0.05, "the drain ended while the turn held its ticket"
    assert _step_at(op, "restarting") - released_at < 1.5, "the drain waited past the release"
    assert _step_at(op, "restarting") - _step_at(op, "draining") < DRAIN
    instance.wait_state(f"worker-{A}", "ready", timeout=30)
    snapshot = _snap(instance)
    assert A not in snapshot["paused_stories"] and A not in snapshot["closing_stories"]
    _empty(instance)


def test_a_paused_head_never_delays_another_story_and_resume_grants_in_order(
    instance: HostingInstance,
) -> None:
    """
    C1: A is paused by a stop whose drain cannot finish (A holds a utility
    ticket). A's two narration waiters keep their places at the head of the
    line, and B's waiter behind them is granted the moment B's slot frees.
    When the drain runs out, A resumes, and its waiters are granted in order.
    """
    _hold(instance, B, "res-b-hold", _account())
    _hold(instance, A, "res-a-util", _account(), lane="utility")
    _acquire(instance, A, "res-a-1", _account())
    _waiting(instance, 1)
    _acquire(instance, A, "res-a-2", _account())
    _waiting(instance, 2)
    _acquire(instance, B, "res-b-next", _account())
    _waiting(instance, 3)
    op_id = _op(instance, "stories.stop", A)
    instance.until(lambda: A in _snap(instance)["paused_stories"], what="A paused")

    mark = instance.mark()
    _release(instance, B, "res-b-hold")
    _granted(instance, "res-b-next", mark)
    lane = _lane(_snap(instance))
    assert [w["story"] for w in lane["waiters"]] == [A, A], "the paused waiters lost their places"
    assert [h["story"] for h in lane["holders"]] == [B]
    _release(instance, B, "res-b-next")

    op = instance.wait_op(op_id, timeout=DRAIN + 10)
    assert op["status"] == "refused" and op["reason"] == "turns are still running; the story was not stopped"
    _granted(instance, "res-a-1", mark, timeout=10)
    assert not any("LANE GRANT name=res-a-2" in line for line in instance.lines[mark:])
    mark2 = instance.mark()
    _release(instance, A, "res-a-1")
    _granted(instance, "res-a-2", mark2)
    _release(instance, A, "res-a-2")
    _release(instance, A, "res-a-util")
    _empty(instance)
    assert instance.row(f"worker-{A}")["state"] == "ready"


# -- a wait called off (#2), a grant nobody waits for (I2) -------------------------------


def test_a_cancelled_wait_leaves_the_queue_at_once_and_frees_the_account(instance: HostingInstance) -> None:
    """
    T11 fix round 1 (#2): B's turn waits behind A's for narration; its player
    leaves (the worker's ``CancelToken``, as a socket's disconnect fires
    it). The wait ends at once, its entry leaves the supervisor's line with
    its account claim, so the same player's turn in C is admitted, not told
    ``other_window``. On 31cb510 the entry stayed until its deadline.
    """
    account = _account()
    _hold(instance, A, "cx-h", _account())
    _acquire(instance, B, "cx-gone", account)
    _waiting(instance, 1)
    mark = instance.mark()
    assert instance.tell(B, {"cmd": "cancel", "name": "cx-gone"}) == {"ok": True}
    assert _refused(instance, "cx-gone", mark) == "cancelled"
    _waiting(instance, 0)
    _acquire(instance, C, "cx-elsewhere", account)
    snapshot = _waiting(instance, 1)
    assert [w["story"] for w in _lane(snapshot)["waiters"]] == [C]
    _release(instance, A, "cx-h")
    _granted(instance, "cx-elsewhere", mark)
    assert not any("LANE GRANT name=cx-gone" in line for line in instance.lines[mark:])
    _release(instance, C, "cx-elsewhere")
    _empty(instance)


def test_a_grant_that_lands_after_its_wait_was_called_off_is_released_at_once_and_counted() -> None:
    """
    I2 through the real cancel path: the grant crosses the cancel on the wire
    (the supervisor here answers when the test says, after the cancel), so
    it reaches a caller that has gone. ``RemoteLanes`` releases it at once
    from the reader thread and counts it. In this process: the crossing has
    to be ordered, and a real queue would withdraw the waiter first.
    """
    from engine.hosting.bus import BusClient, BusServer
    from engine.hosting.lanes_remote import RemoteLanes
    from engine.llm.gate import CancelToken, InferenceBusy

    server = BusServer().start()
    answers: list[Any] = []
    asked = threading.Event()
    released: list[str] = []
    cancelled: list[int] = []
    release_seen = threading.Event()

    def acquire(conn: Any, args: dict[str, Any], answer: Any) -> None:
        answers.append(answer)
        asked.set()

    def release(conn: Any, args: dict[str, Any]) -> dict[str, Any]:
        released.append(args["ticket"])
        release_seen.set()
        return {}

    server.handle_deferred("lane.acquire", acquire)
    server.handle("lane.release", release)
    server.handle("lane.cancel", lambda conn, args: (cancelled.append(args["id"]), {})[1])
    record = server.mint("worker", story=A)
    client = BusClient(server.addr, record.token)
    client.on_lost = lambda: None
    client.connect()
    try:
        lanes = RemoteLanes(client)
        token = CancelToken()
        outcome: list[Any] = []
        waiter = threading.Thread(
            target=lambda: outcome.append(_raises(lambda: lanes.acquire("narration", 30, cancel=token))),
            name="cancelled-turn",
        )
        waiter.start()
        assert asked.wait(JOIN)
        token.cancel()
        waiter.join(JOIN)
        assert not waiter.is_alive()
        assert isinstance(outcome[0], InferenceBusy) and outcome[0].reason == "cancelled"
        answers[0]({"ticket": "t77"}, "")  # the grant that crossed the cancel
        assert release_seen.wait(JOIN), "the late grant was not given back"
        assert released == ["t77"] and lanes.abandoned_grants == 1
        assert cancelled == [answers[0].request_id]
    finally:
        client.close()
        server.close()


def _raises(call: Any) -> Any:
    try:
        return call()
    except Exception as exc:  # noqa: BLE001 -- the outcome is what is asserted
        return exc


# -- the snapshot -------------------------------------------------------------------------

_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_ACCOUNT = re.compile(r"^u_[0-9a-f]{12}$")
_SNAPSHOT_KEYS = {"lanes", "paused_stories", "closing_stories", "lane", "limit", "paused", "holders", "waiters", "story", "account", "since"}


def _leaves(value: Any, key: str = "") -> Iterator[tuple[str, Any]]:
    if isinstance(value, dict):
        for inner, item in value.items():
            assert inner in _SNAPSHOT_KEYS, f"an unexpected key {inner!r}"
            yield from _leaves(item, inner)
    elif isinstance(value, list):
        for item in value:
            yield from _leaves(item, key)
    else:
        yield key, value


def test_the_snapshot_holds_only_ids_slugs_enums_and_numbers(instance: HostingInstance) -> None:
    _hold(instance, A, "snap-h", _account())
    _hold(instance, B, "snap-u", _account(), lane="utility")
    _acquire(instance, B, "snap-w", _account())
    snapshot = _waiting(instance, 1)
    try:
        assert {row["lane"] for row in snapshot["lanes"]} == {"narration", "utility"}
        seen = 0
        for key, value in _leaves(snapshot):
            seen += 1
            if key in ("story", "paused_stories", "closing_stories"):
                assert isinstance(value, str) and _SLUG.fullmatch(value), (key, value)
            elif key == "account":
                assert isinstance(value, str) and (value == "" or _ACCOUNT.fullmatch(value)), value
            elif key == "lane":
                assert value in ("narration", "utility")
            elif key == "paused":
                assert isinstance(value, bool)
            else:
                assert key in ("limit", "since") and isinstance(value, (int, float)) and not isinstance(value, bool)
        assert seen >= 9
        assert len(json.dumps(snapshot)) < 4096
    finally:
        mark = instance.mark()
        _release(instance, A, "snap-h")
        _granted(instance, "snap-w", mark)
        _release(instance, B, "snap-w")
        _release(instance, B, "snap-u")
    _empty(instance)


# -- in this process: resize and max_hold_seconds ------------------------------------------


def test_a_resize_is_refused_while_a_ticket_is_held_or_unpaused() -> None:
    """Lanes change size only paused for all with no ticket held (spec §14.4)."""
    from engine.hosting.supervisor.queue import LaneQueue, QueueRefusal

    queue = LaneQueue({"narration": 1, "utility": 2}).start()
    try:
        answers: list[Any] = []
        queue.acquire(owner=1, story=A, lane="narration", account="", timeout=5, reply=lambda r, e: answers.append((r, e)))
        assert answers and answers[0][1] == ""
        with pytest.raises(QueueRefusal):
            queue.resize("narration", 4)  # not paused
        queue.pause()
        with pytest.raises(QueueRefusal):
            queue.resize("narration", 4)  # paused, a ticket held
        queue.release(owner=1, ticket=answers[0][0]["ticket"])
        queue.resize("narration", 4)
        assert _lane(queue.snapshot())["limit"] == 4
        queue.resume()
    finally:
        queue.close()


def test_releasing_another_connection_s_ticket_is_bad_args() -> None:
    from engine.hosting.supervisor.queue import LaneQueue, QueueRefusal

    queue = LaneQueue().start()
    try:
        answers: list[Any] = []
        queue.acquire(owner=1, story=A, lane="narration", account="", timeout=5, reply=lambda r, e: answers.append(r))
        with pytest.raises(QueueRefusal) as caught:
            queue.release(owner=2, ticket=answers[0]["ticket"])
        assert caught.value.code == "bad_args"
        assert queue.held() == 1
    finally:
        queue.close()


def test_a_double_release_and_a_release_of_a_waiting_ticket_are_bad_args_and_free_nothing() -> None:
    """#8: the holder stays held, the waiter keeps its place."""
    from engine.hosting.supervisor.queue import LaneQueue, QueueRefusal

    queue = LaneQueue().start()
    try:
        held: list[Any] = []
        queue.acquire(owner=1, story=A, lane="narration", account="", timeout=5, reply=lambda r, e: held.append(r))
        waiting: list[Any] = []
        queue.acquire(owner=1, story=A, lane="narration", account="", timeout=5, reply=lambda r, e: waiting.append(r))
        assert held and not waiting
        snapshot = queue.snapshot()
        waiter_ticket = f"t{int(held[0]['ticket'][1:]) + 1}"
        with pytest.raises(QueueRefusal) as caught:
            queue.release(owner=1, ticket=waiter_ticket)  # still waiting, never granted
        assert caught.value.code == "bad_args"
        assert queue.snapshot() == snapshot
        queue.release(owner=1, ticket=held[0]["ticket"])
        assert waiting and waiting[0]["ticket"] == waiter_ticket
        with pytest.raises(QueueRefusal) as caught:
            queue.release(owner=1, ticket=held[0]["ticket"])  # twice
        assert caught.value.code == "bad_args"
        assert queue.held() == 1
    finally:
        queue.close()


def test_a_malformed_account_and_lane_are_refused_bad_args_over_the_bus() -> None:
    """#8: the shape of what a worker says is checked (the account is its word, §14.4)."""
    from engine.hosting.bus import BusError
    from tests.hosted_app import SharedQueue

    shared = SharedQueue()
    try:
        client = shared.client()
        for args in (
            {"lane": "narration", "account": "bob", "timeout": 1},
            {"lane": "narration", "account": "u_XYZ", "timeout": 1},
            {"lane": "Not A Lane", "timeout": 1},
        ):
            with pytest.raises(BusError) as caught:
                client.request("lane.acquire", args)
            assert caught.value.code == "bad_args", args
        assert all(not row["waiters"] and not row["holders"] for row in shared.queue.snapshot()["lanes"])
    finally:
        shared.close()


def test_an_unlisted_lane_opens_at_the_default_size_as_the_gate_opens_it() -> None:
    """#4: one behaviour everywhere: a profile's custom lane works under the supervisor too."""
    from engine.llm.gate import DEFAULT_LANE_LIMIT
    from tests.hosted_app import SharedQueue

    shared = SharedQueue()
    try:
        lanes = shared.lanes()
        ticket = lanes.acquire("voice", 1.0)
        row = next(r for r in shared.queue.snapshot()["lanes"] if r["lane"] == "voice")
        assert row["limit"] == DEFAULT_LANE_LIMIT and len(row["holders"]) == 1
        lanes.release(ticket)
    finally:
        shared.close()


def test_a_paused_utility_exemption_needs_narration_on_the_same_connection() -> None:
    """
    #6: an account holding narration on worker A does not open story B's
    pause for a utility acquire from B in that account's name.
    """
    from engine.hosting.supervisor.queue import LaneQueue

    queue = LaneQueue().start()
    try:
        account = "u_00000000beef"
        got: list[Any] = []
        queue.acquire(owner=1, story=A, lane="narration", account=account, timeout=5, reply=lambda r, e: got.append(("A", e)))
        queue.pause(B)
        queue.acquire(owner=2, story=B, lane="utility", account=account, timeout=5, reply=lambda r, e: got.append(("B", e)))
        queue.pause(A)
        queue.acquire(owner=1, story=A, lane="utility", account=account, timeout=5, reply=lambda r, e: got.append(("A-utility", e)))
        assert got == [("A", ""), ("A-utility", "")], got
        assert len(_lane(queue.snapshot(), "utility")["waiters"]) == 1
    finally:
        queue.close()


def test_the_queue_takes_no_lock_under_its_own(monkeypatch: pytest.MonkeyPatch) -> None:
    """#7: ``LaneQueue._cond`` is a leaf, checked by ``tests/lock_order.py``."""
    from engine.hosting.supervisor.queue import LaneQueue
    from tests import lock_order

    checker = lock_order.install(monkeypatch)
    queue = LaneQueue().start()
    try:
        answers: list[Any] = []
        queue.acquire(owner=1, story=A, lane="narration", account="", timeout=5, reply=lambda r, e: answers.append(r))
        queue.acquire(owner=2, story=B, lane="narration", account="", timeout=5, reply=lambda r, e: answers.append(r))
        queue.pause(B)
        queue.release(owner=1, ticket=answers[0]["ticket"])
        queue.resume(B)
        assert queue.wait_until_idle(A, 1.0)
        queue.close_connection(2)
        queue.close_story(A)
        queue.snapshot()
    finally:
        queue.close()
    assert "engine.hosting.supervisor.queue.LaneQueue._cond" in checker.acquired, "the queue's lock was not tracked"
    assert not checker.violations, lock_order.report(checker)


def test_a_stop_that_raises_after_its_drain_leaves_the_story_open(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    #3, #8: the drain paused and closed the story, then the stop raised: the
    story is resumed anyway, never left refusing every turn. Fails on
    31cb510, which resumed only after a stop that returned.
    """
    from engine.hosting.config import validate
    from engine.hosting.supervisor.logs import LogHub
    from engine.hosting.supervisor.ops import Operation
    from engine.hosting.supervisor.process import READY
    from engine.hosting.supervisor.server import Supervisor
    from tests.test_hosting_config import _block

    hub = LogHub(tmp_path / "logs", max_mb=1, keep=2, echo=None)
    sup = Supervisor(validate(_block(stories=[A])), hub=hub)
    try:
        child = sup.children[0]
        child.state = READY
        child.conn = type("Conn", (), {"id": 99})()
        monkeypatch.setattr(sup.server, "request", lambda *_a, **_k: {"drained": True})

        def broken_stop(*_args: Any, **_kwargs: Any) -> str:
            raise RuntimeError("the stop failed")

        monkeypatch.setattr(sup, "_stop", broken_stop)
        steps: list[str] = []
        with pytest.raises(RuntimeError):
            sup._perform(Operation(op_id="op-1", kind="stories.restart", slug=A, actor=""), steps.append)
        assert steps == ["draining", "restarting"]
        snapshot = sup.queue.snapshot()
        assert A not in snapshot["paused_stories"] and A not in snapshot["closing_stories"]
    finally:
        sup.ops.close()
        sup._health.shutdown(wait=False)
        sup._reaper.shutdown(wait=False)
        sup.server.close()
        sup.queue.close()
        hub.close()


class _GrantingBus:
    """A bus that grants every acquire one fresh ticket and acknowledges releases."""

    connected = True

    def __init__(self) -> None:
        self.count = 0

    def request(self, op: str, args: Any = None, timeout: float = 0.0, **_kw: Any) -> dict[str, Any]:
        if op == "lane.acquire":
            self.count += 1
            return {"ticket": f"t{self.count}"}
        return {}


def test_a_reclaim_that_comes_after_its_release_is_not_kept() -> None:
    """
    v0.20.0 T12 (T11's N3): ``lane.reclaimed`` for a ticket this worker has
    already released is acknowledged and forgotten -- nothing would ever
    remove it again. A reclaim of a ticket still held is kept until its
    release. On 3a7da4f the late reclaim stayed in ``_reclaimed`` for the
    process's life.
    """
    from engine.hosting.lanes_remote import RemoteLanes

    lanes = RemoteLanes(_GrantingBus())  # type: ignore[arg-type]
    late = lanes.acquire("narration", 1.0)
    lanes.release(late)
    assert lanes.reclaimed_ticket(late) == {}
    assert not lanes.reclaimed(late) and lanes._reclaimed == set()

    held = lanes.acquire("narration", 1.0)
    assert lanes.reclaimed_ticket(held) == {}
    assert lanes.reclaimed(held)
    lanes.release(held)
    assert lanes._reclaimed == set() and lanes._held == set()


# -- in this process: max_hold_seconds, a reclaim and a hung worker -------------------------


class InProcess:
    """A supervisor in this process, running two real lane_client workers."""

    def __init__(self, sup: Any, stop: threading.Event, control: Path) -> None:
        self.sup = sup
        self.stop = stop
        self.control = control

    def child(self, slug: str) -> Any:
        return self.sup.child(slug)

    def children(self) -> set[Any]:
        """Every reported child, by pid AND creation time (T15 fix round 1, I2)."""
        from tests.process_identity import of_report

        return {of_report(json.loads(p.read_text())) for p in self.control.glob("*.json")}

    def own_pid(self, slug: str) -> int:
        reports = sorted(self.control.glob(f"worker-{slug}-*.json"), key=lambda p: p.stat().st_mtime_ns)
        return int(json.loads(reports[-1].read_text())["pid"])

    def own_identity(self, slug: str) -> Any:
        """The newest probe's identity, pid AND creation time (T15 fix round 2, N2)."""
        from tests.process_identity import of_report

        reports = sorted(self.control.glob(f"worker-{slug}-*.json"), key=lambda p: p.stat().st_mtime_ns)
        return of_report(json.loads(reports[-1].read_text()))

    def until(self, check: Any, what: str, timeout: float = JOIN) -> None:
        deadline = time.monotonic() + timeout
        while not check():
            assert time.monotonic() < deadline, f"not within {timeout}s: {what}"
            self.stop.wait(0.05)

    def tell(self, slug: str, payload: dict[str, Any]) -> dict[str, Any]:
        import httpx

        with httpx.Client(trust_env=False, timeout=10) as http:
            return http.post(f"http://127.0.0.1:{self.child(slug).port}/command", json=payload).json()

    def ready(self, slug: str) -> None:
        self.until(lambda: self.child(slug).state == "ready" and self.child(slug).port, f"{slug} ready")


@pytest.fixture(scope="module")
def in_process(tmp_path_factory: pytest.TempPathFactory) -> Iterator[InProcess]:
    """
    A supervisor in THIS process, because the shipped cross-check keeps
    ``max_hold_seconds`` above two minutes: its settings are the validated
    ones with the hold cut to 1.5 s, ``max_restarts`` to 1 and the
    acknowledgement grace to 3 s. Its workers are real ``lane_client``s
    (sandboxed by the suite's ``Popen`` wrapper). Shared by the three tests
    below; the hung worker's comes last, since it restarts a worker.
    """
    from engine.hosting.config import validate
    from engine.hosting.supervisor.logs import LogHub
    from engine.hosting.supervisor.server import Supervisor
    from tests.test_hosting_config import _block

    tmp_path = tmp_path_factory.mktemp("reclaim")
    settings = dataclasses.replace(
        validate(
            _block(
                stories=[A, B],
                supervisor__boot_seconds=10,
                supervisor__health_interval_seconds=1,
                supervisor__drain_seconds=2,
                supervisor__stop_seconds=2,
                supervisor__shutdown_seconds=21,  # 2 + 2 + 7 + the front door's 10 (T18)
                supervisor__max_restarts=1,
            )
        ),
        max_hold_seconds=1.5,
    )
    control = tmp_path / "control"
    control.mkdir()
    environ = {k: v for k, v in os.environ.items() if k not in ("CLOCKWORK_GAME", "CLOCKWORK_CONFIG")}
    environ[CONTROL_ENV] = str(control)
    environ["CLOCKWORK_DATA_DIR"] = str(tmp_path / "data")
    hub = LogHub(tmp_path / "logs", max_mb=1, keep=2, echo=None)
    sup = Supervisor(settings, hub=hub, worker_module=LANE_CLIENT, environ=environ, cwd=str(REPO), lanes={"narration": 1, "utility": 2})
    sup.reclaim_ack_seconds = 3.0
    stop = threading.Event()
    runner = threading.Thread(target=sup.run, args=(stop,), name="in-process-supervisor", daemon=True)
    handle = InProcess(sup, stop, control)
    sup.start()
    runner.start()
    try:
        handle.ready(A)
        handle.ready(B)
        yield handle
    finally:
        from tests.process_identity import alive as running, terminate

        children = handle.children()
        stop.set()
        runner.join(JOIN)
        alive_runner = runner.is_alive()
        hub.close()
        left = [child for child in children if running(child)]
        for child in left:
            terminate(child)  # only a verified child: a reused pid is another process
        assert not alive_runner, "the in-process supervisor did not stop"
        assert not left, "a lane_client outlived its supervisor"


def _held_by(sup: Any, slug: str) -> bool:
    return any(h["story"] == slug for h in _lane(sup.queue.snapshot())["holders"])


def test_a_slow_but_healthy_turn_past_max_hold_is_reclaimed_without_a_restart(
    in_process: InProcess, caplog: Any
) -> None:
    """
    Ruling (c): A's turn holds narration past the hold (a slow turn in a
    healthy worker). The ticket is reclaimed -- B's waiter gets the place at
    once -- A acknowledges, and A is NOT restarted; A's own late release is
    accepted quietly. Fails on 31cb510, which restarted A as a crash.
    """
    caplog.set_level(logging.INFO)
    pid = in_process.own_pid(A)
    assert in_process.tell(A, {"cmd": "acquire", "name": "slow", "lane": "narration", "account": "", "timeout": 5}) == {"ok": True}
    in_process.until(lambda: _held_by(in_process.sup, A), "A holding narration")
    assert in_process.tell(B, {"cmd": "acquire", "name": "next", "lane": "narration", "account": "", "timeout": 30}) == {"ok": True}
    in_process.until(lambda: _held_by(in_process.sup, B), "B granted the reclaimed place")
    in_process.until(lambda: in_process.tell(A, {"cmd": "status"})["reclaimed"] == ["slow"], "A acknowledged")
    assert in_process.tell(A, {"cmd": "release", "name": "slow"})["ok"]  # accepted quietly
    assert in_process.tell(B, {"cmd": "release", "name": "next"})["ok"]
    in_process.until(lambda: not _lane(in_process.sup.queue.snapshot())["holders"], "the lane empty")
    child = in_process.child(A)
    assert child.state == "ready" and not child.crashes and in_process.own_pid(A) == pid
    messages = [r.getMessage() for r in caplog.records]
    assert any("reclaimed" in m and "event=unhealthy" in m for m in messages)
    assert any("acknowledged a reclaimed lane ticket; not restarted" in m for m in messages)


def test_reclaims_never_count_toward_the_hold_down(in_process: InProcess) -> None:
    """
    Ruling (c): with ``max_restarts`` at 1, two reclaims in a row leave A
    running, uncounted -- a slow model server never holds a story down.
    Fails on 31cb510 (each was a counted crash restart: held down).
    """
    pid = in_process.own_pid(A)
    for round_ in range(2):
        name = f"slow-{round_}"
        assert in_process.tell(A, {"cmd": "acquire", "name": name, "lane": "narration", "account": "", "timeout": 5}) == {"ok": True}
        in_process.until(lambda: name in in_process.tell(A, {"cmd": "status"})["reclaimed"], f"{name} reclaimed and acknowledged")
        assert in_process.tell(A, {"cmd": "release", "name": name})["ok"]
    child = in_process.child(A)
    assert child.state == "ready" and not child.crashes
    assert in_process.own_pid(A) == pid


def test_a_hung_worker_that_does_not_acknowledge_is_restarted(in_process: InProcess, caplog: Any) -> None:
    """
    Ruling (c): B is hung (its ``lane.reclaimed`` is never answered). Its
    ticket is reclaimed -- the place passes to A's waiter while B's process
    still runs -- and after the grace B is restarted, as a crash. On
    31cb510 the place passed only when the killed process's connection
    closed, and nothing asked B anything.
    """
    caplog.set_level(logging.INFO)
    old = in_process.own_pid(B)
    old_identity = in_process.own_identity(B)
    assert in_process.tell(B, {"cmd": "hang"}) == {"ok": True}
    assert in_process.tell(B, {"cmd": "acquire", "name": "hung", "lane": "narration", "account": "", "timeout": 5}) == {"ok": True}
    in_process.until(lambda: _held_by(in_process.sup, B), "B holding narration")
    assert in_process.tell(A, {"cmd": "acquire", "name": "after-hung", "lane": "narration", "account": "", "timeout": 30}) == {"ok": True}
    in_process.until(lambda: _held_by(in_process.sup, A), "A granted the reclaimed place")
    assert alive(old_identity), "the place passed only when B died: no reclaim"
    in_process.until(lambda: in_process.own_pid(B) != old, "B restarted")
    in_process.ready(B)
    assert len(in_process.child(B).crashes) == 1
    assert any("did not acknowledge a reclaimed lane ticket" in r.getMessage() for r in caplog.records)
    assert in_process.tell(A, {"cmd": "release", "name": "after-hung"})["ok"]
