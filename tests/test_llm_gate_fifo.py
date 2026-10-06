"""
The model server's lanes, shared by many players (v0.20.0 T9, spec §5.3).

Hosted mode builds each lane as a ``FifoSemaphore``: waiters are served in
the order they arrived, a waiter that gives up (a timeout) or a holder that
fails (an exception) costs no slot, and a turn admitted to the narration lane
(``turn_admission``) re-enters it for every narration call it makes -- the
storyteller's own, its ``:retry`` and ``:room`` -- without queueing behind
other players. Local mode keeps ``threading.BoundedSemaphore`` and its
180-second wait, exactly as v0.19.0.

Concurrency here is ordered with events and the semaphore's own
``wait_until_waiting`` (a condition, not a poll), never with sleeps; every
thread is joined with a timeout and the test fails rather than hangs.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Iterator

import pytest

from engine.llm import gate
from tests.hosted_app import Lanes, hosting_layer

#: Generous: nothing here waits on a model.
JOIN = 30.0


@pytest.fixture
def lanes() -> Iterator[None]:
    gate.reset_lanes()
    try:
        yield
    finally:
        gate.reset_lanes()


@pytest.fixture
def hosted(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, lanes: None) -> Iterator[None]:
    """Hosted mode on (the config only; no app), with a one-slot narration lane."""
    from engine.config import reset_config

    hosting_layer(monkeypatch, tmp_path, hosting={"queue_wait_seconds": 7}, extra={"llm": {"lanes": {"narration": 1, "utility": 2}}})
    gate.reset_lanes()
    try:
        yield
    finally:
        gate.reset_lanes()
        reset_config()


@pytest.fixture(params=["own_lanes", "shared_queue"])
def either(request: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, lanes: None) -> Iterator[Lanes]:
    """
    Hosted, a one-slot narration lane, served by this process's lanes or by
    the supervisor's queue (T11): spec §5.3's rules hold under both.
    """
    from engine.config import reset_config
    from tests.hosted_app import SharedQueue

    hosting_layer(monkeypatch, tmp_path, hosting={"queue_wait_seconds": 7}, extra={"llm": {"lanes": {"narration": 1, "utility": 2}}})
    gate.reset_lanes()
    shared = None
    if request.param == "shared_queue":
        shared = SharedQueue({"narration": 1, "utility": 2})
        shared.install()
    try:
        yield Lanes(shared)
    finally:
        if shared is not None:
            shared.close()
        gate.reset_lanes()
        reset_config()


def _join(*threads: threading.Thread) -> None:
    for thread in threads:
        thread.join(JOIN)
        assert not thread.is_alive(), f"{thread.name} did not finish"


# -- FifoSemaphore ------------------------------------------------------------


def test_twenty_waiters_are_served_in_arrival_order() -> None:
    sem = gate.FifoSemaphore(1)
    assert sem.acquire(timeout=1)  # held, so every thread below queues
    order: list[int] = []
    threads = []

    def wait_then_record(index: int) -> None:
        assert sem.acquire(timeout=JOIN)
        try:
            order.append(index)
        finally:
            sem.release()

    for index in range(20):
        thread = threading.Thread(target=wait_then_record, args=(index,), name=f"fifo-{index}")
        thread.start()
        threads.append(thread)
        # Queued before the next one starts: arrival order is this loop's order.
        assert sem.wait_until_waiting(index + 1, timeout=JOIN), f"thread {index} never queued"

    sem.release()
    _join(*threads)
    assert order == list(range(20))
    assert sem.held == 0 and sem.waiting == 0


def test_a_waiter_that_times_out_costs_no_slot_and_does_not_block_the_next() -> None:
    sem = gate.FifoSemaphore(1)
    assert sem.acquire(timeout=1)
    gave_up = threading.Event()
    got: list[bool] = []

    def impatient() -> None:
        got.append(sem.acquire(timeout=0.05))
        gave_up.set()

    def patient() -> None:
        got.append(sem.acquire(timeout=JOIN))
        sem.release()

    first = threading.Thread(target=impatient, name="impatient")
    first.start()
    assert sem.wait_until_waiting(1, timeout=JOIN)
    second = threading.Thread(target=patient, name="patient")
    second.start()
    assert gave_up.wait(JOIN), "the impatient waiter never gave up"
    # The head gave up; the one behind it is now first in line.
    assert sem.waiting == 1
    sem.release()
    _join(first, second)
    assert got == [False, True]
    assert sem.held == 0 and sem.waiting == 0
    # Every slot is still there.
    assert sem.acquire(blocking=False)
    sem.release()


def test_a_holder_that_raises_costs_no_slot(either: Lanes) -> None:
    with pytest.raises(RuntimeError):
        with gate.inference_slot(lane="narration", label="boom", timeout=1):
            raise RuntimeError("the model call failed")
    sem = either.view("narration")
    assert sem.held == 0
    with gate.inference_slot(lane="narration", label="after", timeout=0.5):
        assert sem.held == 1


def test_a_release_too_many_is_refused() -> None:
    sem = gate.FifoSemaphore(1)
    with pytest.raises(ValueError):
        sem.release()


def test_position_reports_the_place_in_line() -> None:
    sem = gate.FifoSemaphore(1)
    assert sem.acquire(timeout=1)
    tickets = [object(), object()]
    threads = []
    for index, ticket in enumerate(tickets):
        thread = threading.Thread(
            target=lambda t=ticket: (sem.acquire(timeout=JOIN, ticket=t), sem.release()),
            name=f"pos-{index}",
        )
        thread.start()
        threads.append(thread)
        assert sem.wait_until_waiting(index + 1, timeout=JOIN)
    assert sem.position(tickets[0]) == 0
    assert sem.position(tickets[1]) == 1
    assert sem.position(object()) is None
    sem.release()
    _join(*threads)
    assert sem.position(tickets[0]) is None


# -- the lanes, local and hosted ----------------------------------------------


def test_local_mode_builds_a_bounded_semaphore_and_waits_180_seconds(lanes: None) -> None:
    from engine.config import hosting_enabled

    assert not hosting_enabled()
    assert type(gate._semaphore("narration")) is threading.BoundedSemaphore
    assert type(gate._semaphore("utility")) is threading.BoundedSemaphore
    assert gate.default_wait() == gate.DEFAULT_WAIT_SECONDS == 180.0


def test_hosted_mode_builds_fifo_lanes_and_waits_queue_wait_seconds(hosted: None) -> None:
    assert isinstance(gate._semaphore("narration"), gate.FifoSemaphore)
    assert isinstance(gate._semaphore("utility"), gate.FifoSemaphore)
    assert gate._semaphore("narration").limit == 1
    assert gate._semaphore("utility").limit == 2
    assert gate.default_wait() == 7.0


def test_a_lane_built_in_one_mode_is_rebuilt_in_the_other(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, lanes: None) -> None:
    """A lane left over from a local run is not reused by a hosted one (tests switch modes)."""
    from engine.config import reset_config

    assert type(gate._semaphore("narration")) is threading.BoundedSemaphore
    hosting_layer(monkeypatch, tmp_path)
    try:
        assert isinstance(gate._semaphore("narration"), gate.FifoSemaphore)
    finally:
        reset_config()


# -- admission and the held lane ----------------------------------------------


def test_an_admitted_turn_re_enters_narration_without_waiting(either: Lanes) -> None:
    """
    The storyteller's call, its ``:retry`` and its ``:room`` run inside one
    admitted turn while another player waits for the one narration slot: none
    of them queues behind that player.
    """
    sem = either.view("narration")
    admitted = threading.Event()
    other_queued = threading.Event()
    done = threading.Event()
    calls: list[str] = []
    other_got: list[float] = []

    def turn() -> None:
        with gate.turn_admission(label="turn"):
            admitted.set()
            assert other_queued.wait(JOIN)
            assert gate.held_lane() == "narration"
            # Each with a tiny timeout: a call that queued would raise at once.
            with gate.inference_slot(lane="narration", label="storyteller", timeout=0.01):
                calls.append("storyteller")
                with gate.inference_slot(lane="narration", label="storyteller:retry", timeout=0.01):
                    calls.append("retry")
            with gate.inference_slot(lane="narration", label="storyteller:room", timeout=0.01):
                calls.append("room")
            assert sem.held == 1, "a re-entry took a second slot"
        assert gate.held_lane() is None
        done.set()

    def other_player() -> None:
        assert admitted.wait(JOIN)
        with gate.inference_slot(lane="narration", label="other", timeout=JOIN):
            other_got.append(1.0)

    first = threading.Thread(target=turn, name="admitted-turn")
    second = threading.Thread(target=other_player, name="other-player")
    first.start()
    second.start()
    assert admitted.wait(JOIN)
    assert sem.wait_until_waiting(1, timeout=JOIN), "the other player never queued"
    other_queued.set()
    _join(first, second)
    assert done.is_set()
    assert calls == ["storyteller", "retry", "room"]
    assert other_got == [1.0], "the other player was not served once the turn ended"
    assert sem.held == 0


def test_admission_times_out_with_inference_busy(either: Lanes) -> None:
    sem = either.view("narration")
    release = either.hold("narration")  # another player's turn holds the slot
    try:
        with pytest.raises(gate.InferenceBusy) as caught:
            with gate.turn_admission(timeout=0.05, label="turn"):
                pytest.fail("admitted past a held slot")
        assert caught.value.reason == gate.BUSY
        assert gate.held_lane() is None
        assert sem.waiting == 0
    finally:
        release()


def test_the_held_lane_is_carried_into_a_planner_thread(either: Lanes) -> None:
    """
    The pipeline plans on pool threads, which copy no ContextVar; a planner on
    the narration lane must share the turn's ticket rather than queue behind
    it (which would wait out the whole queue wait, then plan nothing).
    """
    seen: list[Any] = []

    def planner() -> None:
        with gate.inference_slot(lane="narration", label="plan:gm", timeout=0.05):
            seen.append(gate.held_lane())

    with gate.turn_admission(label="turn"):
        thread = threading.Thread(target=gate.carrying_held_lane(planner), name="planner")
        thread.start()
        _join(thread)
    assert seen == ["narration"]


def test_hosted_utility_lanes_wait_utility_wait_seconds(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, lanes: None
) -> None:
    """Fix round 1 (I1): a utility call waits seconds, not the turn's queue wait."""
    from engine.config import reset_config

    hosting_layer(monkeypatch, tmp_path, hosting={"queue_wait_seconds": 600, "utility_wait_seconds": 3})
    try:
        assert gate.default_wait() == 600.0
        assert gate.default_wait("narration") == 600.0
        assert gate.default_wait("utility") == 3.0
    finally:
        reset_config()


def test_a_release_whose_reset_raises_still_frees_the_slot(either: Lanes) -> None:
    """
    Fix round 1 (M2): the slot is released before the ContextVar is reset, so
    a reset that raises (here, released from another context) cannot wedge
    the narration lane. Fails on 1e0557f, which reset first.
    """
    import contextvars

    sem = either.view("narration")
    admission = gate.admit_turn(label="turn")
    assert sem.held == 1
    try:
        with pytest.raises(ValueError):
            contextvars.copy_context().run(admission.release)
        assert sem.held == 0, "a raising reset kept the slot"
    finally:
        gate._held_lane.set(None)  # this context's leftover, from the refused reset


def test_carrying_nothing_returns_the_function_itself(lanes: None) -> None:
    def planner() -> None:
        return None

    assert gate.carrying_held_lane(planner) is planner


# -- the lane backend (v0.20.0 T11, spec §14.4) ---------------------------------


class SpyBackend:
    """A lane backend that records every call and grants at once."""

    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []

    def acquire(self, lane: str, timeout: float, account: str, story: str) -> str:
        self.calls.append(("acquire", lane, account))
        return f"ticket-{len(self.calls)}"

    def release(self, ticket: Any) -> None:
        self.calls.append(("release", ticket))


def test_with_a_backend_admission_acquires_once_and_narration_re_enters_without_it(hosted: None) -> None:
    """
    One bus round trip per turn: admission asks the backend once, and the
    storyteller's call, its ``:retry``, ``:room`` and stream re-enter the held
    ticket in this worker. The turn's utility call is asked in its account's
    name (the supervisor grants it while the story is paused, spec §14.4).
    """
    spy = SpyBackend()
    gate.set_lane_backend(spy)
    try:
        with gate.turn_admission(label="turn", account="u_0123456789ab"):
            for label in ("storyteller", "storyteller:retry", "storyteller:room", "stream"):
                with gate.inference_slot(lane="narration", label=label, timeout=0.01):
                    pass
            assert spy.calls == [("acquire", "narration", "u_0123456789ab")]
            with gate.inference_slot(lane="utility", label="summarizer", timeout=0.01):
                pass
        assert spy.calls == [
            ("acquire", "narration", "u_0123456789ab"),
            ("acquire", "utility", "u_0123456789ab"),
            ("release", "ticket-2"),
            ("release", "ticket-1"),
        ]
        # The process's own lanes were never touched.
        assert gate._lanes == {}
    finally:
        gate.reset_lane_backend()


def test_local_mode_sets_no_backend_and_builds_a_bounded_semaphore(lanes: None) -> None:
    from engine.config import hosting_enabled

    assert not hosting_enabled()
    assert gate.lane_backend() is None
    with gate.inference_slot(lane="narration", label="local", timeout=1):
        pass
    assert type(gate._lanes["narration"]) is threading.BoundedSemaphore
    assert gate.lane_backend() is None


def test_the_gate_never_imports_hosting() -> None:
    """The backend is handed in; ``engine/llm/gate.py`` names no hosting module."""
    source = Path(gate.__file__).read_text(encoding="utf-8")
    assert "import engine.hosting" not in source and "from engine.hosting" not in source


# -- the turn deadline (v0.20.0 T11 fix round 1) ------------------------------------


class FakeClock:
    """The gate's deadline clock, moved by the test instead of by sleeping."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> FakeClock:
    fake = FakeClock()
    monkeypatch.setattr(gate, "_clock", fake)
    return fake


def _slow_stream(clock: FakeClock, step: float, chunks: int) -> Any:
    import httpx

    class SlowStream(httpx.SyncByteStream):
        """An SSE body whose every chunk takes ``step`` seconds of the fake clock: never idle, long in total."""

        def __init__(self) -> None:
            self.sent = 0

        def __iter__(self) -> Iterator[bytes]:
            for index in range(chunks):
                clock.now += step
                self.sent += 1
                frame = {"choices": [{"delta": {"content": f"word{index} "}}]}
                yield f"data: {json.dumps(frame)}\n\n".encode("utf-8")
            yield b"data: [DONE]\n\n"

    return SlowStream()


def test_a_stream_slower_in_total_than_its_timeout_is_cut_at_the_turn_deadline(
    hosted: None, clock: FakeClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Review #1: a stream that is never idle for ``llm.timeout_seconds`` (httpx's
    per-phase timeout never fires) but runs far past it in total. Inside an
    admitted turn with a 25-second deadline, the call is cut at the deadline
    -- as a read timeout, the client's own failure path -- and its timeout
    was capped to what was left. Fails on 31cb510, where it streamed on.
    """
    import httpx

    from engine.llm.client import LMSClient

    stream = _slow_stream(clock, step=10.0, chunks=20)
    seen: list[Any] = []

    def handle(_self: Any, request: httpx.Request) -> httpx.Response:
        seen.append(request.extensions.get("timeout"))
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=stream, request=request)

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", handle)
    client = LMSClient("http://127.0.0.1:9", timeout=300.0)
    try:
        with gate.turn_admission(label="turn", deadline_seconds=25):
            clock.now += 5  # the turn's mechanics took five seconds
            with pytest.raises(httpx.ReadTimeout):
                for _delta in client.chat_stream([{"role": "user", "content": "go"}], model="m"):
                    pass
            # No further call starts once the deadline has passed.
            with pytest.raises(gate.InferenceBusy) as caught:
                with gate.inference_slot(lane="utility", label="summarizer", timeout=5):
                    pytest.fail("a utility call started past the deadline")
            assert caught.value.reason == gate.DEADLINE
    finally:
        client.close()
    assert stream.sent == 2, f"the stream ran {stream.sent} chunks past a 25 s deadline"
    assert seen and seen[0]["read"] == pytest.approx(20.0)  # min(300, 25 - 5)
    assert gate._semaphore("narration").held == 0


def test_with_no_deadline_a_call_keeps_its_own_timeout(lanes: None) -> None:
    """Local mode (and any context outside an admitted hosted turn): unchanged."""
    assert gate.time_left() is None
    assert gate.turn_expired() == ""
    assert gate.call_timeout(300.0) == 300.0


def test_a_reclaimed_ticket_stops_the_turn_s_further_calls(hosted: None) -> None:
    """Ruling (c): a turn whose ticket the supervisor took back makes no further model call."""
    from tests.hosted_app import SharedQueue

    shared = SharedQueue({"narration": 1, "utility": 2})
    lanes = shared.install()
    try:
        with gate.turn_admission(label="turn"):
            ticket = gate._held_lane.get().ticket
            lanes.reclaimed_ticket(ticket)
            assert gate.turn_expired() == gate.RECLAIMED
            with pytest.raises(gate.InferenceBusy) as caught:
                with gate.inference_slot(lane="narration", label="storyteller", timeout=1):
                    pytest.fail("a call ran on a reclaimed ticket")
            assert caught.value.reason == gate.RECLAIMED
    finally:
        shared.close()


# -- a stalled stream is cut at the deadline (v0.20.0 T12, T11's N2) ---------------------


class _StalledStream:
    """
    A loopback HTTP server that answers one streamed response: headers and one
    SSE line, then NOTHING -- a model server stalled mid-stream -- until
    ``release`` is set (the test's teardown) or ``hold`` seconds pass.
    """

    def __init__(self, hold: float = 30.0) -> None:
        import socket

        self.release = threading.Event()
        self.hold = hold
        self.listener = socket.create_server(("127.0.0.1", 0))
        self.port = self.listener.getsockname()[1]
        self.thread = threading.Thread(target=self._serve, name="stalled-stream", daemon=True)
        self.thread.start()

    def _serve(self) -> None:
        conn, _addr = self.listener.accept()
        with conn:
            data = b""
            while b"\r\n\r\n" not in data:
                chunk = conn.recv(4096)
                if not chunk:
                    return
                data += chunk
            line = b"data: {\"choices\": [{\"delta\": {\"content\": \"x\"}}]}\n\n"
            conn.sendall(
                b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\n"
                b"Transfer-Encoding: chunked\r\n\r\n" + f"{len(line):x}\r\n".encode() + line + b"\r\n"
            )
            self.release.wait(self.hold)

    def close(self) -> None:
        self.release.set()
        self.listener.close()
        self.thread.join(JOIN)
        assert not self.thread.is_alive()


def test_a_stalled_stream_is_cut_at_the_turn_deadline(hosted: None) -> None:
    """
    v0.20.0 T12 (T11's N2): ``stop_if_turn_expired`` runs between a stream's
    lines, so a stream that stalls without a byte used to run on until its
    READ timeout -- up to ``llm.timeout_seconds`` past the turn's deadline.
    ``cut_at_deadline`` shuts the response's socket at the deadline: here a
    turn with 1 s left whose call has a 20 s read timeout ends within a
    couple of seconds, through ``httpx.HTTPError`` (the model-failure path).
    Fails on 3a7da4f, where the read ran the whole 20 s.
    """
    import time

    import httpx

    from engine.llm.client import cut_at_deadline

    server = _StalledStream()
    client = httpx.Client(trust_env=False)
    try:
        with gate.turn_admission(label="turn", deadline_seconds=1.0):
            began = time.monotonic()
            with pytest.raises(httpx.HTTPError):
                with client.stream(
                    "POST", f"http://127.0.0.1:{server.port}/v1/chat/completions", json={}, timeout=20.0
                ) as response, cut_at_deadline(response) as cut:
                    for _line in response.iter_lines():
                        pass
            took = time.monotonic() - began
        assert cut.cut, "the deadline's timer never fired"
        assert took < 8.0, f"the stalled stream ran {took:.1f}s past a 1 s deadline"
    finally:
        client.close()
        server.close()


def test_outside_a_hosted_turn_no_timer_is_set(lanes: None) -> None:
    """Local mode (``time_left()`` is None): the stream is exactly what it was, no timer."""
    from engine.llm.client import cut_at_deadline

    with cut_at_deadline(object()) as cut:  # type: ignore[arg-type]
        assert cut.timer is None


def test_every_streamed_model_call_is_cut_at_the_deadline() -> None:
    """
    Each client's streamed request is wrapped (compat, LM Studio native,
    Ollama), and gives the cut up when its read loop ends (fix round 2, N3).
    """
    import re

    root = Path(__file__).resolve().parents[1] / "engine" / "llm"
    for name in ("client.py", "lmstudio_native.py", "ollama.py"):
        source = (root / name).read_text(encoding="utf-8")
        calls = re.findall(r"self\._client\.stream\((?:.|\n)*?\) as response([^:\n]*):", source)
        assert calls, name
        assert all(c == ", cut_at_deadline(response) as deadline_cut" for c in calls), (
            f"{name}: a streamed call is not cut at the deadline: {calls}"
        )
        assert source.count("deadline_cut.finish()") == len(calls), f"{name}: a read loop keeps its cut"


class _Sock:
    """A socket that records what was done to it."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.calls: list[str] = []

    def shutdown(self, _how: int) -> None:
        self.calls.append("shutdown")

    def close(self) -> None:
        self.calls.append("close")


class _Stream:
    def __init__(self, sock: _Sock) -> None:
        self.sock = sock

    def get_extra_info(self, name: str) -> Any:
        return self.sock if name == "socket" else None


class _Response:
    """A response whose connection's socket can change under it (a pooled connection reused)."""

    def __init__(self, sock: _Sock) -> None:
        self.extensions = {"network_stream": _Stream(sock)}


def test_the_deadline_cut_reaches_only_the_connection_its_stream_started_on(hosted: None) -> None:
    """
    Fix round 1 (M1): the socket is taken when the stream STARTS. A cut that
    fires while the stream runs shuts that socket, even if the response's
    connection now names another; a cut that fires after the stream ended
    (``__exit__`` ran, the connection back in httpx's pool for another call)
    does nothing. On eb1d4d4 the cut read the socket when it fired and had
    no ``done`` guard, so a late cut shut whichever call held it then.
    """
    from engine.llm.client import cut_at_deadline

    with gate.turn_admission(label="turn", deadline_seconds=600.0):
        ours, theirs = _Sock("ours"), _Sock("theirs")
        response = _Response(ours)
        with cut_at_deadline(response) as running:  # type: ignore[arg-type]
            response.extensions["network_stream"] = _Stream(theirs)
            running._cut()
        assert running.cut and "shutdown" in ours.calls and theirs.calls == []

        late_ours, pooled = _Sock("late"), _Sock("pooled")
        late = _Response(late_ours)
        with cut_at_deadline(late) as ended:  # type: ignore[arg-type]
            pass
        late.extensions["network_stream"] = _Stream(pooled)
        ended._cut()  # the timer firing just as the stream finished
        assert not ended.cut and late_ours.calls == [] and pooled.calls == []


def test_a_running_cut_holds_the_stream_s_end_until_it_is_done(hosted: None) -> None:
    """``__exit__`` waits for a cut already under way (the shared lock), so none outlives its stream."""
    from engine.llm.client import cut_at_deadline

    entered, finish = threading.Event(), threading.Event()

    class SlowSock(_Sock):
        def shutdown(self, how: int) -> None:
            entered.set()
            finish.wait(JOIN)
            super().shutdown(how)

    sock = SlowSock("slow")
    with gate.turn_admission(label="turn", deadline_seconds=600.0):
        guard = cut_at_deadline(_Response(sock))  # type: ignore[arg-type]
        guard.__enter__()
        cutter = threading.Thread(target=guard._cut, name="cutter")
        cutter.start()
        assert entered.wait(JOIN)
        exited = threading.Event()
        closer = threading.Thread(target=lambda: (guard.__exit__(None, None, None), exited.set()), name="closer")
        closer.start()
        assert not exited.wait(0.2), "the stream ended while its cut was still running"
        finish.set()
        for thread in (cutter, closer):
            thread.join(JOIN)
            assert not thread.is_alive()
        assert exited.is_set() and guard.done and "shutdown" in sock.calls


def test_a_stream_gives_up_its_cut_once_its_body_is_read(
    hosted: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Fix round 2 (N3): a stream that ends without ``[DONE]`` has its body read
    when its read loop ends, and httpx may hand its connection to another
    call then, while this generator is still suspended at a later yield. The
    compat client gives the cut up right there (``deadline_cut.finish()``),
    not when the generator exits. On 2b55e89 the cut stayed armed until the
    generator's ``with`` closed.
    """
    import socket

    import engine.llm.client as client_module
    from engine.llm.client import LMSClient

    seen: list[tuple[str, bool]] = []
    real = client_module.cut_at_deadline

    class Watching(real):  # type: ignore[misc, valid-type]
        def finish(self) -> None:
            seen.append(("finish", bool(self.response.is_stream_consumed)))
            getattr(super(), "finish", lambda: None)()

        def __exit__(self, *exc: Any) -> None:
            seen.append(("exit", bool(self.response.is_stream_consumed)))
            super().__exit__(*exc)

    monkeypatch.setattr(client_module, "cut_at_deadline", Watching)
    release = threading.Event()
    listener = socket.create_server(("127.0.0.1", 0))
    port = listener.getsockname()[1]

    def serve() -> None:
        conn, _addr = listener.accept()
        with conn:
            data = b""
            while b"\r\n\r\n" not in data:
                chunk = conn.recv(4096)
                if not chunk:
                    return
                data += chunk
            line = b'data: {"choices": [{"delta": {"content": "x"}}]}\n\n'
            conn.sendall(
                b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\n"
                b"Transfer-Encoding: chunked\r\n\r\n"
                + f"{len(line):x}\r\n".encode() + line + b"\r\n0\r\n\r\n"
            )
            release.wait(JOIN)  # the body is whole; the connection stays open (pooled)

    server = threading.Thread(target=serve, name="ended-stream", daemon=True)
    server.start()
    client = LMSClient(base_url=f"http://127.0.0.1:{port}/v1")
    try:
        with gate.turn_admission(label="turn", deadline_seconds=600.0):
            deltas = list(client.chat_stream([{"role": "user", "content": "go"}], model="m"))
        assert deltas == ["x"]
        assert seen and seen[0] == ("finish", True), seen
    finally:
        release.set()
        listener.close()
        server.join(JOIN)
        assert not server.is_alive()
        close = getattr(client, "close", None)
        if close is not None:
            close()
