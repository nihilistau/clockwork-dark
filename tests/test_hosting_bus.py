"""
The bus (v0.20.0 T10, spec §14.2): framing, credentials, the op table, the
lifeline. The server runs in this process (``BusServer`` on loopback, an
OS-picked port); clients are ``BusClient``s in this process, raw sockets, and
for the lifeline a real probe child (``tests/probes/fake_worker.py``).
"""

from __future__ import annotations

import io
import json
import logging
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Iterator

import pytest

from engine.hosting import bus
from engine.hosting.bus import (
    LIFELINE_EXIT_CODE,
    MAX_FRAME,
    OPS,
    BusClient,
    BusError,
    BusServer,
    FrameError,
)
from tests.hosting_instance import REPO

# In-process loopback servers: the hybrid run's serial phase (tests/tiers.py).
pytestmark = pytest.mark.loopback

JOIN = 10.0


@pytest.fixture(autouse=True)
def _no_exit_in_this_process(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[int]]:
    """
    A ``BusClient`` in THIS process exits it when its link drops (the
    lifeline). Recorded instead, so a client a test forgot to defuse -- or
    one a broken bus let through -- fails a test rather than ending the run.
    """
    exits: list[int] = []
    monkeypatch.setattr(bus, "_exit_process", exits.append)
    yield exits


@pytest.fixture
def server() -> Iterator[BusServer]:
    srv = BusServer().start()
    srv.handle("ready", lambda conn, args: {"seen": dict(args)})
    srv.handle("stories.list", lambda conn, args: {"stories": []})
    try:
        yield srv
    finally:
        srv.close()
        assert srv._thread is not None
        srv._thread.join(JOIN)
        assert not srv._thread.is_alive(), "the selector thread did not stop"


def _bare(server: BusServer, token: str) -> BusClient:
    """
    A client whose lifeline does nothing: THIS process must never exit, even
    when a broken bus lets a connect through that should have been refused.
    """
    client = BusClient(server.addr, token)
    client.on_lost = lambda: None
    return client


def _client(server: BusServer, role: str = "worker", story: str = "clockwork-dark") -> BusClient:
    record = server.mint(role, story=story if role == "worker" else "")
    client = _bare(server, record.token)
    client.connect()
    return client


def _raw(server: BusServer) -> socket.socket:
    sock = socket.create_connection(server.address, timeout=JOIN)
    return sock


def _closed(sock: socket.socket, timeout: float = JOIN) -> bool:
    """Whether the peer closes ``sock`` within ``timeout`` (data before the close is read and dropped)."""
    sock.settimeout(timeout)
    deadline = time.monotonic() + timeout
    try:
        while time.monotonic() < deadline:
            if not sock.recv(65536):
                return True
    except (ConnectionResetError, ConnectionAbortedError):
        return True
    except socket.timeout:
        return False
    return False


def _hello(sock: socket.socket, token: Any) -> dict[str, Any]:
    sock.sendall(json.dumps({"id": 1, "op": "hello", "args": {"token": token}}).encode() + b"\n")
    reader = sock.makefile("rb")
    return bus.read_frame(reader) or {}


# -- framing -----------------------------------------------------------------------------


def test_a_frame_round_trips() -> None:
    message = {"id": 7, "op": "ready", "args": {"port": 5573, "note": "ünïcode"}}
    data = bus.encode(message)
    assert data.endswith(b"\n") and data.count(b"\n") == 1
    assert bus.decode(data) == message
    assert bus.read_frame(io.BytesIO(data + data)) == message
    assert bus.read_frame(io.BytesIO(b"")) is None


def test_encode_refuses_past_the_cap_and_a_reply_becomes_too_large() -> None:
    with pytest.raises(FrameError) as caught:
        bus.encode({"x": "a" * MAX_FRAME})
    assert caught.value.code == "too_large"
    frame = bus.reply_frame(3, {"x": "a" * MAX_FRAME})
    assert bus.decode(frame) == {"id": 3, "ok": False, "error": "too_large"}


class _Endless:
    """A stream with no newline, ever: records every limit it is asked for."""

    def __init__(self) -> None:
        self.limits: list[int] = []
        self.given = 0

    def readline(self, limit: int = -1) -> bytes:
        self.limits.append(limit)
        assert limit > 0, "an unbounded readline"
        self.given += limit
        return b"x" * limit


def test_the_reader_never_reads_past_its_limit() -> None:
    stream = _Endless()
    with pytest.raises(FrameError) as caught:
        bus.read_frame(stream)
    assert caught.value.code == "too_large"
    assert stream.limits == [MAX_FRAME] and stream.given == MAX_FRAME


@pytest.mark.parametrize("line", [b"not json\n", b"[1, 2]\n", b"\xff\xfe\n"])
def test_a_malformed_frame_is_refused_by_the_reader(line: bytes) -> None:
    with pytest.raises(FrameError) as caught:
        bus.read_frame(io.BytesIO(line))
    assert caught.value.code == "malformed"


@pytest.mark.parametrize("kind", ["oversize, no newline", "oversize line", "malformed"])
def test_an_oversize_or_malformed_inbound_frame_closes_the_connection(server: BusServer, kind: str) -> None:
    junk = {
        "oversize, no newline": b"x" * (MAX_FRAME + 10),
        "oversize line": b"y" * (MAX_FRAME + 10) + b"\n",
        "malformed": b"{nope\n",
    }[kind]
    record = server.mint("worker", story="clockwork-dark")
    sock = _raw(server)
    try:
        assert _hello(sock, record.token)["ok"] is True
        sock.sendall(junk)
        assert _closed(sock)
    finally:
        sock.close()


# -- the selector's wake pair (v0.21.0: a suite that hung) ------------------------------
#
# On Windows ``socket.socketpair()`` is emulated over loopback TCP and waits in
# ``accept()`` with no bound. On the owner's workstation a loopback connect
# sometimes never reaches the listener (13 of 3000 in a plain loop, measured),
# so ``BusServer()`` -- the ``server`` fixture's first step -- hung the whole
# run. ``wake_pair`` bounds each attempt and accepts only its own peer.


@pytest.fixture
def loopback_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """The Windows path on every platform: no AF_UNIX socketpair."""
    monkeypatch.delattr(socket, "AF_UNIX", raising=False)


def _connects_go_to(monkeypatch: pytest.MonkeyPatch, hole: tuple[str, int]) -> None:
    """Every ``connect`` lands on ``hole`` instead: the caller's listener never sees it."""
    real = socket.socket.connect
    monkeypatch.setattr(socket.socket, "connect", lambda self, address: real(self, hole))


def _a_stranger_connects_first(monkeypatch: pytest.MonkeyPatch) -> list[socket.socket]:
    """
    Before each ``connect``, a stranger connects to the same address (so the
    listener's first connection is not the caller's). Returns the strangers.
    """
    real = socket.socket.connect
    strangers: list[socket.socket] = []

    def connect(self: socket.socket, address: Any) -> Any:
        stranger = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        stranger.settimeout(JOIN)
        strangers.append(stranger)
        real(stranger, address)
        return real(self, address)

    monkeypatch.setattr(socket.socket, "connect", connect)
    return strangers


def test_the_wake_pair_is_connected_both_ways(loopback_only: None) -> None:
    left, right = bus.wake_pair(timeout=JOIN, attempts=1)
    try:
        left.settimeout(JOIN)
        right.settimeout(JOIN)
        right.sendall(b"\0")
        assert left.recv(1) == b"\0"
        left.sendall(b"\1")
        assert right.recv(1) == b"\1"
    finally:
        left.close()
        right.close()


def test_a_wake_pair_never_takes_a_stranger(monkeypatch: pytest.MonkeyPatch, loopback_only: None) -> None:
    """The listener's first connection is another peer's: it is closed, and the pair is ours."""
    strangers = _a_stranger_connects_first(monkeypatch)
    left, right = bus.wake_pair(timeout=JOIN, attempts=1)
    monkeypatch.undo()
    try:
        assert len(strangers) == 1
        assert left.getpeername()[1] == right.getsockname()[1], "a stranger was wired into the pair"
        assert _closed(strangers[0]), "the stranger's connection was kept open"
    finally:
        left.close()
        right.close()
        for stranger in strangers:
            stranger.close()


def test_a_wake_connection_that_never_arrives_fails_the_server_instead_of_hanging(
    monkeypatch: pytest.MonkeyPatch, loopback_only: None
) -> None:
    """
    The hang, reproduced: the pair's own connect lands in a listener nobody
    accepts on, so the pair's listener never sees it. ``BusServer()`` must
    raise within its bound. Built on a thread joined with a bound, so a
    constructor that waits forever (the stdlib socketpair: the canary) FAILS
    this test rather than hanging the run.
    """
    hole = socket.create_server(("127.0.0.1", 0))  # listens, never accepts
    try:
        _connects_go_to(monkeypatch, hole.getsockname()[:2])
        monkeypatch.setattr(bus, "WAKE_PAIR_SECONDS", 0.3)
        monkeypatch.setattr(bus, "WAKE_PAIR_ATTEMPTS", 2)
        outcome: list[Any] = []

        def build() -> None:
            try:
                outcome.append(BusServer())
            except BaseException as exc:  # noqa: BLE001 -- the outcome is the assertion
                outcome.append(exc)

        thread = threading.Thread(target=build, name="wake-pair-canary", daemon=True)
        thread.start()
        thread.join(JOIN)
        assert not thread.is_alive(), "BusServer() waited for its wake connection with no bound"
        (result,) = outcome
        if isinstance(result, BusServer):
            result.close()
        assert isinstance(result, OSError), f"BusServer() did not refuse a wake pair it never got: {result!r}"
    finally:
        hole.close()


# -- a child's connect that is lost (v0.21.1) ------------------------------------------
#
# The same loopback loss, on a child's side: a worker whose ONE connect to the
# bus was never accepted waited out its 10 s hello and exited 1, and a model
# apply that was restarting it read that as "did not start under the new
# settings" and rolled back (tests/test_admin_model.py, 2 runs in 3 here).
# ``BusClient.connect`` now tries again on a fresh socket.


def _first_connects_go_to(monkeypatch: pytest.MonkeyPatch, hole: tuple[str, int], lost: int) -> list[int]:
    """The first ``lost`` bus connects land on ``hole`` (a listener that never accepts); the rest go through."""
    real = socket.create_connection
    calls: list[int] = []

    def create_connection(address: Any, *args: Any, **kwargs: Any) -> socket.socket:
        calls.append(1)
        return real(hole if len(calls) <= lost else address, *args, **kwargs)

    monkeypatch.setattr(socket, "create_connection", create_connection)
    return calls


def _connect_bounded(client: BusClient) -> Any:
    """``client.connect()`` on a thread joined with a bound: its result, or what it raised."""
    outcome: list[Any] = []

    def run() -> None:
        try:
            outcome.append(client.connect())
        except BaseException as exc:  # noqa: BLE001 -- the outcome is the assertion
            outcome.append(exc)

    thread = threading.Thread(target=run, name="bus-connect", daemon=True)
    thread.start()
    thread.join(JOIN)
    assert not thread.is_alive(), "connect() waited with no bound"
    (result,) = outcome
    return result


def test_a_bus_connect_that_is_never_accepted_is_tried_again(
    server: BusServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    hole = socket.create_server(("127.0.0.1", 0))  # listens, never accepts
    try:
        monkeypatch.setattr(bus, "CONNECT_SECONDS", 0.5, raising=False)  # absent before v0.21.1
        calls = _first_connects_go_to(monkeypatch, hole.getsockname()[:2], lost=2)
        record = server.mint("worker", story="clockwork-dark")
        client = _bare(server, record.token)
        result = _connect_bounded(client)
        monkeypatch.undo()
        assert isinstance(result, dict) and result.get("process") == "worker-clockwork-dark", result
        try:
            assert len(calls) == 3
            assert record.state == "live"
            assert client.request("ready", {"port": 9})["seen"]["port"] == 9
        finally:
            client.close()
    finally:
        hole.close()


def test_a_bus_connect_that_times_out_is_tried_again(server: BusServer, monkeypatch: pytest.MonkeyPatch) -> None:
    real = socket.create_connection
    calls: list[int] = []

    def create_connection(address: Any, *args: Any, **kwargs: Any) -> socket.socket:
        calls.append(1)
        if len(calls) == 1:
            raise socket.timeout("timed out")
        return real(address, *args, **kwargs)

    monkeypatch.setattr(socket, "create_connection", create_connection)
    record = server.mint("worker", story="clockwork-dark")
    client = _bare(server, record.token)
    result = _connect_bounded(client)
    monkeypatch.undo()
    assert isinstance(result, dict), result
    client.close()
    assert len(calls) == 2


def test_a_bus_connect_lost_every_time_fails_within_its_bound(
    server: BusServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    hole = socket.create_server(("127.0.0.1", 0))
    try:
        monkeypatch.setattr(bus, "CONNECT_SECONDS", 0.3, raising=False)
        monkeypatch.setattr(bus, "CONNECT_ATTEMPTS", 3, raising=False)
        calls = _first_connects_go_to(monkeypatch, hole.getsockname()[:2], lost=99)
        record = server.mint("worker", story="clockwork-dark")
        began = time.monotonic()
        result = _connect_bounded(_bare(server, record.token))
        took = time.monotonic() - began
        monkeypatch.undo()
        assert isinstance(result, (BusError, OSError)), result
        assert len(calls) == 3 and record.state == "unused"
        assert took < 3 * 0.3 + 0.5, f"one deadline of 3 x 0.3 s, but connect() took {took:.2f}s"
    finally:
        hole.close()


def test_one_deadline_bounds_connects_that_stall(server: BusServer, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Fix round 1: each connect stalls for most of its timeout (as a lost SYN
    does) and then lands where no hello is ever answered. The attempts are
    still ``CONNECT_SECONDS`` apart from their STARTS, and the whole is bounded
    by ``CONNECT_SECONDS x CONNECT_ATTEMPTS`` -- not attempts x (connect +
    wait), as when each attempt was timed from its connect's return.
    """
    monkeypatch.setattr(bus, "CONNECT_SECONDS", 0.3)
    monkeypatch.setattr(bus, "CONNECT_ATTEMPTS", 3)
    hole = socket.create_server(("127.0.0.1", 0))  # listens, never accepts
    real = socket.create_connection
    starts: list[float] = []

    def stalls(address: Any, timeout: float = 0.0, *args: Any, **kwargs: Any) -> socket.socket:
        starts.append(time.monotonic())
        threading.Event().wait(0.9 * timeout)
        return real(hole.getsockname()[:2], timeout, *args, **kwargs)

    try:
        monkeypatch.setattr(socket, "create_connection", stalls)
        began = time.monotonic()
        result = _connect_bounded(_bare(server, server.mint("worker", story="clockwork-dark").token))
        took = time.monotonic() - began
        monkeypatch.undo()
        assert isinstance(result, BusError), result
        assert len(starts) == 3
        assert took < 3 * 0.3 + 0.25, f"connect() took {took:.2f}s, past its one deadline of 0.9 s"
    finally:
        hole.close()


def test_attempts_that_fail_at_once_still_wait_their_slot(server: BusServer, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Fix round 1: a connect reset at once must not let the next attempt start
    at once (six instant resets spent every attempt in milliseconds): attempt
    N starts (N - 1) x ``CONNECT_SECONDS`` after the first.
    """
    monkeypatch.setattr(bus, "CONNECT_SECONDS", 0.4)
    real = socket.create_connection
    starts: list[float] = []

    def reset_first(address: Any, *args: Any, **kwargs: Any) -> socket.socket:
        starts.append(time.monotonic())
        if len(starts) == 1:
            raise ConnectionResetError("reset")
        return real(address, *args, **kwargs)

    monkeypatch.setattr(socket, "create_connection", reset_first)
    client = _bare(server, server.mint("worker", story="clockwork-dark").token)
    result = _connect_bounded(client)
    monkeypatch.undo()
    assert isinstance(result, dict), result
    client.close()
    assert len(starts) == 2
    assert starts[1] - starts[0] >= 0.4 - 0.02, f"the second attempt started {starts[1] - starts[0]:.3f}s after the first"


def test_a_hello_answered_after_its_attempt_gave_up_is_still_taken(
    server: BusServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    The race a retry opens (seen in a full run): the first hello is read and
    its token accepted, but the answer comes after that attempt's wait. An
    attempt given up must not be thrown away -- its token is now live on it,
    so every later attempt is refused. The late answer is taken instead.
    """
    monkeypatch.setattr(bus, "CONNECT_SECONDS", 0.3, raising=False)
    monkeypatch.setattr(bus, "CONNECT_ATTEMPTS", 10, raising=False)  # a 3 s deadline against the 1 s stall
    seen: list[int] = []

    def slow_first(_record: Any) -> bool:
        seen.append(1)
        if len(seen) == 1:
            threading.Event().wait(1.0)  # past the attempt's 0.3 s
        return True

    server.admit = slow_first
    record = server.mint("worker", story="clockwork-dark")
    client = _bare(server, record.token)
    result = _connect_bounded(client)
    assert isinstance(result, dict) and result.get("process") == "worker-clockwork-dark", result
    try:
        assert record.state == "live"
        assert client.request("ready", {"port": 9})["seen"]["port"] == 9
    finally:
        client.close()


class _SlowAnswers:
    """
    A loopback relay to ``target`` that passes the client's bytes on at once
    and holds the server's for ``delay`` seconds: a hello the server reads
    and accepts at once, whose answer reaches the client late.
    """

    def __init__(self, target: tuple[str, int], delay: float) -> None:
        self.target, self.delay = target, delay
        self.listener = socket.create_server(("127.0.0.1", 0))
        self.address = self.listener.getsockname()[:2]
        self.socks: list[socket.socket] = []
        threading.Thread(target=self._accept, name="slow-answers", daemon=True).start()

    def _accept(self) -> None:
        try:
            client, _ = self.listener.accept()
        except OSError:
            return
        upstream = socket.create_connection(self.target, timeout=JOIN)
        self.socks += [client, upstream]
        threading.Thread(target=self._pipe, args=(client, upstream, 0.0), daemon=True).start()
        threading.Thread(target=self._pipe, args=(upstream, client, self.delay), daemon=True).start()

    @staticmethod
    def _pipe(src: socket.socket, dst: socket.socket, delay: float) -> None:
        try:
            while True:
                data = src.recv(65536)
                if not data:
                    break
                if delay:
                    threading.Event().wait(delay)
                    delay = 0.0
                dst.sendall(data)
        except OSError:
            pass
        try:
            dst.shutdown(socket.SHUT_WR)  # pass the end on, as a direct peer would see it
        except OSError:
            pass

    def close(self) -> None:
        self.listener.close()
        for sock in self.socks:
            sock.close()


def test_a_refusal_ends_nothing_while_an_earlier_attempt_is_open(
    server: BusServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Fix round 1 (review finding 8): the order a refusal-first connect must
    survive. Attempt 1's hello is accepted at once but its answer arrives
    late (the relay holds it 1.5 s); attempt 2's hello is refused (the token
    is live on attempt 1) and that refusal arrives FIRST. The connect must
    keep listening and take attempt 1's answer.
    """
    monkeypatch.setattr(bus, "CONNECT_SECONDS", 0.3)
    monkeypatch.setattr(bus, "CONNECT_ATTEMPTS", 10)
    relay = _SlowAnswers(server.address, 1.5)
    try:
        _first_connects_go_to(monkeypatch, relay.address, lost=1)
        record = server.mint("worker", story="clockwork-dark")
        client = _bare(server, record.token)
        result = _connect_bounded(client)
        monkeypatch.undo()
        assert isinstance(result, dict) and result.get("process") == "worker-clockwork-dark", result
        try:
            assert record.state == "live"
            assert client.request("ready", {"port": 9})["seen"]["port"] == 9
        finally:
            client.close()
    finally:
        relay.close()


def test_a_refused_hello_is_not_tried_again(server: BusServer, monkeypatch: pytest.MonkeyPatch) -> None:
    real = socket.create_connection
    calls: list[int] = []
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: calls.append(1) or real(*a, **k))
    result = _connect_bounded(_bare(server, "f" * 64))
    monkeypatch.undo()
    assert isinstance(result, BusError) and result.code == "unauthorized", result
    assert len(calls) == 1


def test_arguments_that_are_not_an_object_are_bad_args(server: BusServer) -> None:
    record = server.mint("worker", story="clockwork-dark")
    sock = _raw(server)
    try:
        reader = sock.makefile("rb")
        sock.sendall(json.dumps({"id": 1, "op": "hello", "args": {"token": record.token}}).encode() + b"\n")
        assert bus.read_frame(reader)["ok"] is True  # type: ignore[index]
        sock.sendall(json.dumps({"id": 2, "op": "ready", "args": ["port"]}).encode() + b"\n")
        assert bus.read_frame(reader) == {"id": 2, "ok": False, "error": "bad_args"}
    finally:
        sock.close()


def test_a_reply_over_the_cap_is_too_large_and_the_connection_stays(server: BusServer) -> None:
    server.handle("stories.list", lambda conn, args: {"big": "z" * MAX_FRAME})
    server.handle("ops.list", lambda conn, args: {"ops": []})
    front = _client(server, "frontdoor")
    try:
        with pytest.raises(BusError) as caught:
            front.request("stories.list")
        assert caught.value.code == "too_large"
        assert front.request("ops.list") == {"ops": []}  # still connected
        # And the other way: a child's reply over the cap.
        answers = iter([{"big": "z" * MAX_FRAME}, {}])
        front.handle("health", lambda args: next(answers))
        (conn,) = server.connections()
        with pytest.raises(BusError) as caught:
            server.request(conn, "health")
        assert caught.value.code == "too_large"
        assert server.request(conn, "health") == {}
    finally:
        front.close()


# -- no bytes from any connection stop the bus (T10 fix round 1, review C1) --------------

#: Hostile or broken input, as a local process could send it. Every one is
#: sent before ``hello`` and after it; then a valid child must still connect.
FUZZ: dict[str, bytes] = {
    "nested arrays": b"[" * 5000 + b"\n",
    "nested objects": b'{"a":' * 3000 + b"1" + b"}" * 3000 + b"\n",
    "nested in args": b'{"id":1,"op":"ready","args":{"port":' + b"[" * 4000 + b"\n",
    "garbage": b"\x01\x02 not json at all }{ \n",
    "oversize": b"z" * (MAX_FRAME + 100) + b"\n",
    "nul bytes": b"\x00" * 200 + b"\n",
    "invalid utf-8": b"\xff\xfe\xfd\xc3\x28\n",
    "huge integer": b'{"id":1,"op":"ready","args":{"port":' + b"9" * 6000 + b"}}\n",
    "a reply before hello": b'{"id":1,"ok":true}\n',
    "a non-object": b"[1,2,3]\n",
}


def _send_junk(server: BusServer, junk: bytes, *, after_hello: bool, close_mid_line: bool = False) -> None:
    sock = _raw(server)
    try:
        if after_hello:
            record = server.mint("worker", story="clockwork-dark")
            assert _hello(sock, record.token)["ok"] is True
        try:
            sock.sendall(junk[:-1] if close_mid_line else junk)
        except OSError:
            pass  # the server may close first
        if not close_mid_line:
            # Closed for the line itself, well before the 5 s hello deadline.
            assert _closed(sock, timeout=2.5), "the connection was not closed"
    finally:
        sock.close()


def _still_serving(server: BusServer) -> None:
    assert server._thread is not None and server._thread.is_alive(), "the selector thread died"
    worker = _client(server)
    try:
        assert worker.request("ready", {"port": 7})["seen"]["port"] == 7
    finally:
        worker.close()


@pytest.mark.parametrize("after_hello", [False, True], ids=["before hello", "after hello"])
@pytest.mark.parametrize("kind", sorted(FUZZ))
def test_no_line_from_any_connection_stops_the_bus(server: BusServer, kind: str, after_hello: bool) -> None:
    if kind == "a reply before hello" and after_hello:
        pytest.skip("after hello, a reply to nothing is dropped, by design")
    _send_junk(server, FUZZ[kind], after_hello=after_hello)
    _still_serving(server)


@pytest.mark.parametrize("after_hello", [False, True], ids=["before hello", "after hello"])
def test_a_partial_line_then_a_close_leaves_the_bus_serving(server: BusServer, after_hello: bool) -> None:
    for kind in ("nested arrays", "nul bytes", "invalid utf-8"):
        _send_junk(server, FUZZ[kind], after_hello=after_hello, close_mid_line=True)
    _still_serving(server)


def test_a_failing_handler_or_step_closes_only_its_connection(server: BusServer) -> None:
    def boom(conn: Any, args: dict[str, Any]) -> dict[str, Any]:
        raise RecursionError("deep")

    server.handle("ready", boom)
    worker = _client(server)
    try:
        with pytest.raises(BusError) as caught:
            worker.request("ready", {"port": 1})
        assert caught.value.code == "internal"
    finally:
        worker.close()
    assert server._thread is not None and server._thread.is_alive()


def test_a_deeply_nested_frame_is_refused_before_the_parser() -> None:
    assert bus.nesting_depth(b'{"a":"[[[[[[[[[[[[[[[[[[[[[[","b":[1,{"c":2}]}') == 3
    with pytest.raises(FrameError) as caught:
        bus.decode(b"[" * (bus.MAX_DEPTH + 1) + b"]" * (bus.MAX_DEPTH + 1))
    assert caught.value.code == "malformed"


#: Worst cases for the nesting scan, each a full 64 KiB line (T10 fix round
#: 2, re-review N1: the regex scan took 12.9 s on the first two).
_BS = b"\\"
SCAN_WORST: dict[str, bytes] = {
    "escaped quotes": b'"' + (_BS + b'"') * 32760 + b"\n",
    "quote-backslash runs": (b'"' + _BS) * 32760 + b"\n",
    "quotes": b'"' * 65530 + b"\n",
    "brackets inside a string": b'"' + b"[" * 65520 + b'"\n',
    "braces inside strings": b'"{",' * 16380 + b"\n",
    "deep nesting": b"[" * 65530 + b"\n",
    "deep objects": b'{"a":' * 13100 + b"\n",
    "flat numbers": b"1," * 32760 + b"\n",
}


@pytest.mark.parametrize("kind", sorted(SCAN_WORST))
def test_the_nesting_scan_is_linear_on_worst_case_lines(kind: str) -> None:
    line = SCAN_WORST[kind]
    assert len(line) <= MAX_FRAME
    began = time.perf_counter()
    try:
        bus.decode(line)
    except FrameError:
        pass
    took = time.perf_counter() - began
    assert took < 0.050, f"{kind}: {took * 1000:.1f} ms"


def test_the_nesting_scan_never_under_counts() -> None:
    """Strings full of brackets, quotes and backslashes; real nesting d around them."""
    import json as _json
    import random

    rng = random.Random(20261001)
    alphabet = '[]{}"\\,:1a'
    for _ in range(2000):
        depth = rng.randint(0, 30)
        text = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 40)))
        line = ("[" * depth + _json.dumps(text) + "]" * depth).encode()
        assert bus.nesting_depth(line) == depth, line
    for _ in range(5000):
        noise = "".join(rng.choice(alphabet) for _ in range(rng.randint(1, 60))).encode()
        try:
            bus.decode(noise)
        except FrameError:
            pass


def test_the_pending_cap_evicts_the_oldest_so_a_child_always_gets_in(server: BusServer) -> None:
    """50 idle sockets held open, then 10 real children: every child connects (re-review N2)."""
    idle = [_raw(server) for _ in range(50)]
    try:
        for _ in range(10):
            worker = _client(server)
            worker.close()
        with server._lock:
            waiting = sum(1 for c in server._conns.values() if c.record is None)
        assert waiting <= bus.MAX_PENDING
    finally:
        for sock in idle:
            sock.close()
    _still_serving(server)


def test_the_pending_cap_evicts_the_oldest(server: BusServer) -> None:
    socks = [_raw(server) for _ in range(bus.MAX_PENDING)]
    try:
        deadline = time.monotonic() + JOIN
        while time.monotonic() < deadline:
            with server._lock:
                waiting = sum(1 for c in server._conns.values() if c.record is None)
            if waiting >= bus.MAX_PENDING:
                break
            threading.Event().wait(0.02)
        assert waiting == bus.MAX_PENDING
        extra = _raw(server)  # one more: the OLDEST pending one goes
        try:
            assert _closed(socks[0], timeout=5.0)
            record = server.mint("worker", story="clockwork-dark")
            assert _hello(extra, record.token)["ok"] is True
        finally:
            extra.close()
    finally:
        for sock in socks:
            sock.close()
    _still_serving(server)


def test_a_dead_selector_tells_its_owner() -> None:
    srv = BusServer().start()
    died = threading.Event()
    srv.on_dead = died.set
    try:
        srv._turn = lambda: (_ for _ in ()).throw(MemoryError("simulated"))  # type: ignore[method-assign]
        srv._wake()
        assert died.wait(JOIN), "on_dead was not called"
    finally:
        srv.close()


def test_health_has_a_thread_of_its_own(server: BusServer) -> None:
    """Four drains holding the request pool cannot fail a bus health check."""
    release = threading.Event()
    worker = _client(server)
    try:
        worker.handle("drain", lambda args: (release.wait(JOIN), {"drained": True})[1])
        worker.handle("health", lambda args: {"alive": True})
        (conn,) = server.connections()
        busy = [
            threading.Thread(target=server.request, args=(conn, "drain", {"seconds": 1}), kwargs={"timeout": JOIN})
            for _ in range(5)
        ]
        for thread in busy:
            thread.start()
        try:
            assert server.request(conn, "health", timeout=2.0) == {"alive": True}
        finally:
            release.set()
            for thread in busy:
                thread.join(JOIN)
                assert not thread.is_alive()
    finally:
        worker.close()


def test_an_oversize_request_is_too_large_and_leaves_nothing_pending(server: BusServer) -> None:
    worker = _client(server)
    try:
        with pytest.raises(BusError) as caught:
            worker.request("ready", {"port": 1, "x": "y" * MAX_FRAME})
        assert caught.value.code == "too_large"
        assert worker._pending == {}
        (conn,) = server.connections()
        with pytest.raises(BusError) as caught:
            server.notify(conn, "health", {"x": "y" * MAX_FRAME})
        assert caught.value.code == "too_large"
        assert conn.pending == {}
    finally:
        worker.close()


# -- credentials -------------------------------------------------------------------------


@pytest.mark.parametrize("token", ["0" * 64, "", None, 12345])
def test_a_wrong_or_missing_token_is_refused(server: BusServer, token: Any) -> None:
    server.mint("worker", story="clockwork-dark")
    sock = _raw(server)
    try:
        reply = _hello(sock, token)
        assert reply.get("ok") is False and reply.get("error") == "unauthorized"
        assert _closed(sock)
    finally:
        sock.close()


def test_a_hello_with_no_token_argument_or_another_op_first_is_refused(server: BusServer) -> None:
    for first in ({"id": 1, "op": "hello", "args": {}}, {"id": 1, "op": "stories.list", "args": {}}):
        sock = _raw(server)
        try:
            sock.sendall(json.dumps(first).encode() + b"\n")
            assert _closed(sock)
        finally:
            sock.close()


def test_a_token_reused_after_its_connection_closed_is_refused(server: BusServer) -> None:
    record = server.mint("worker", story="clockwork-dark")
    first = _bare(server, record.token)
    first.connect()
    first.close()
    server_side_gone = time.monotonic() + JOIN
    while server.connections() and time.monotonic() < server_side_gone:
        threading.Event().wait(0.02)
    assert record.state == "dead"
    again = _bare(server, record.token)
    with pytest.raises(BusError) as caught:
        again.connect()
    assert caught.value.code == "refused"


def test_a_second_hello_while_the_first_connection_is_up_is_refused(server: BusServer) -> None:
    record = server.mint("worker", story="clockwork-dark")
    first = _bare(server, record.token)
    first.connect()
    try:
        second = _bare(server, record.token)
        with pytest.raises(BusError) as caught:
            second.connect()
        assert caught.value.code == "refused"
        assert first.request("ready", {"port": 9})["seen"]["port"] == 9  # the first is untouched
    finally:
        first.close()


def test_no_hello_in_time_closes_the_connection() -> None:
    """The hello deadline, shortened for the wait (the configured one is pinned below)."""
    srv = BusServer(hello_seconds=0.3).start()
    try:
        sock = _raw(srv)
        try:
            began = time.monotonic()
            assert _closed(sock, timeout=5.0)
            assert time.monotonic() - began >= 0.25
        finally:
            sock.close()
    finally:
        srv.close()


def test_the_hello_deadline_is_two_seconds_from_config(tmp_path: Path) -> None:
    """hosting.supervisor.hello_seconds (2, T10 fix round 2) is the supervisor's bus deadline."""
    from engine.hosting.supervisor.logs import LogHub
    from engine.hosting.supervisor.server import Supervisor
    from tests.test_hosting_config import _block

    from engine.hosting.config import validate

    assert bus.HELLO_SECONDS == 2.0
    settings = validate(_block(enabled=True, supervisor__hello_seconds=3))
    hub = LogHub(tmp_path / "logs", max_mb=1, keep=1, echo=None)
    sup = Supervisor(settings, hub=hub)
    try:
        assert sup.server.hello_seconds == 3.0
        assert validate(_block()).hello_seconds == 2
    finally:
        sup.ops.close()
        sup._health.shutdown(wait=False)
        sup._reaper.shutdown(wait=False)
        sup.server.close()
        hub.close()


# -- the op table ------------------------------------------------------------------------


FRONT_ONLY = sorted(name for name, op in OPS.items() if op.callers == frozenset({"frontdoor"}))
TO_CHILD = sorted(name for name, op in OPS.items() if op.direction == bus.TO_CHILD)
WORKER_ONLY = sorted(name for name, op in OPS.items() if op.callers == frozenset({"worker"}))

#: A valid argument set for each op a test sends.
_ARGS: dict[str, dict[str, Any]] = {
    "drain": {"seconds": 1},
    "lane.acquire": {"lane": "narration", "timeout": 1},
    "lane.release": {"ticket": "t1"},
    "lane.cancel": {"id": 1},
    "lane.reclaimed": {"ticket": "t1"},
    "stories.changed": {"stories": [{"slug": "clockwork-dark", "state": "ready", "port": 1}], "seq": 1},
    "sessions.list": {"limit": 10, "offset": 0},  # T15
    "sessions.end": {"slug": "clockwork-dark", "session_id": "abc"},
    "sessions.end_owner": {"account": "u_000000000000"},
    "worker.sessions.list": {"limit": 10, "offset": 0},
    "worker.sessions.end": {"session_id": "abc"},
    "worker.sessions.end_owner": {"account": "u_000000000000"},
    "llm.apply": {"changes": {"llm.lanes.narration": 2}, "apply_anyway": False},  # T16
    "metrics.query": {"name": "recent_errors", "limit": 10, "offset": 0},  # T17
    "oracle.snapshot": {"slug": "clockwork-dark"},
}


def test_request_all_checks_every_call_before_it_registers_any() -> None:
    """
    T15 fix round 2 (N7): a bad argument in the LAST call of a fan-out is
    refused before the first is registered or sent, so nothing is left
    pending on the connection. On 9098e90 the first call's entry stayed.
    """
    server = BusServer()
    left, right = bus.wake_pair()  # bounded: the stdlib's Windows socketpair is not
    try:
        conn = bus.Connection(1, left, time.monotonic() + 60)
        with pytest.raises(BusError) as caught:
            server.request_all(
                [
                    (conn, "worker.sessions.list", {"limit": 1, "offset": 0}),
                    (conn, "worker.sessions.list", {"limit": -1, "offset": 0}),
                ],
                timeout=0.1,
            )
        assert caught.value.code == "bad_args"
        assert conn.pending == {} and not conn.outbuf
    finally:
        server.close()
        left.close()
        right.close()


def test_the_op_table_is_this_task_s_and_its_roles_are_the_spec_s() -> None:
    assert set(OPS) == {
        "hello",
        "ready",
        "health",
        "drain",
        "shutdown",
        "stories.list",
        "stories.start",
        "stories.stop",
        "stories.restart",
        "ops.list",
        "lane.acquire",  # T11
        "lane.release",  # T11
        "queue.snapshot",  # T11
        "lane.cancel",  # T11 fix round 1
        "lane.reclaimed",  # T11 fix round 1
        "stories.changed",  # T12
        "sessions.list",  # T15
        "sessions.end",  # T15
        "sessions.end_owner",  # T15
        "worker.sessions.list",  # T15: the supervisor's fan-out
        "worker.sessions.end",  # T15
        "worker.sessions.end_owner",  # T15
        "llm.health",  # T16
        "llm.models",  # T16
        "llm.apply",  # T16
        "metric",  # T17: either child, stamped by the supervisor
        "metrics.query",  # T17: a named query, never SQL
        "oracle.snapshot",  # T17
        "worker.oracle.snapshot",  # T17: the supervisor's ask of a worker
    }
    assert FRONT_ONLY == [
        "llm.apply",
        "llm.health",
        "llm.models",
        "metrics.query",
        "ops.list",
        "oracle.snapshot",
        "queue.snapshot",
        "sessions.end",
        "sessions.end_owner",
        "sessions.list",
        "stories.list",
        "stories.restart",
        "stories.start",
        "stories.stop",
    ]
    assert TO_CHILD == [
        "drain",
        "health",
        "lane.reclaimed",
        "shutdown",
        "stories.changed",
        "worker.oracle.snapshot",
        "worker.sessions.end",
        "worker.sessions.end_owner",
        "worker.sessions.list",
    ]
    assert WORKER_ONLY == ["lane.acquire", "lane.cancel", "lane.release"]
    for name in ("hello", "ready", "metric"):
        assert OPS[name].callers == frozenset({"frontdoor", "worker"})


@pytest.mark.parametrize("op", FRONT_ONLY + TO_CHILD)
def test_an_op_a_worker_may_not_call_is_forbidden(server: BusServer, op: str, caplog: Any) -> None:
    worker = _client(server)
    try:
        args = {"slug": "clockwork-dark"} if op.startswith("stories.") and op != "stories.list" else {}
        args = _ARGS.get(op, args)
        with caplog.at_level(logging.WARNING, logger="engine.hosting.bus"):
            with pytest.raises(BusError) as caught:
                worker.request(op, args)
        assert caught.value.code == "forbidden"
        assert [r for r in caplog.records if "forbidden" in r.getMessage()]
    finally:
        worker.close()


@pytest.mark.parametrize("op", TO_CHILD)
def test_a_request_meant_for_a_child_is_forbidden_from_the_front_door(server: BusServer, op: str) -> None:
    front = _client(server, "frontdoor")
    try:
        with pytest.raises(BusError) as caught:
            front.request(op, {"seconds": 1} if op == "drain" else {})
        assert caught.value.code == "forbidden"
    finally:
        front.close()


@pytest.mark.parametrize("role", ["frontdoor", "worker"])
def test_stories_changed_is_refused_from_any_child(server: BusServer, role: str, caplog: Any) -> None:
    """
    v0.20.0 T12 (spec §14.2): ``stories.changed`` is the supervisor's
    notification to the front door. Sent by a child -- as the notification it
    is (no id), or as a request -- it is refused ``forbidden`` with a WARNING
    and reaches no handler. Fails on 3a7da4f, whose op table has no such op
    (``unknown_op``).
    """
    reached: list[Any] = []
    server.handle("stories.changed", lambda _conn, args: reached.append(args) or {})
    child = _client(server, role)
    try:
        with caplog.at_level(logging.WARNING, logger="engine.hosting.bus"):
            child.notify("stories.changed", _ARGS["stories.changed"])
            with pytest.raises(BusError) as caught:
                child.request("stories.changed", _ARGS["stories.changed"])
        assert caught.value.code == "forbidden"
        forbidden = [r for r in caplog.records if "stories.changed" in r.getMessage() and "forbidden" in r.getMessage()]
        assert len(forbidden) == 2, [r.getMessage() for r in caplog.records]
        assert reached == []
    finally:
        child.close()


def test_stories_changed_rows_are_checked() -> None:
    """Exactly ``slug``, ``state`` and ``port`` per row, typed, at most ``MAX_STORY_ROWS``."""
    op = OPS["stories.changed"]
    good = {"stories": [{"slug": "a", "state": "ready", "port": 5000}], "seq": 3}
    assert bus.check_args(op, good) == good
    for bad in (
        {"stories": [{"slug": "a", "state": "ready"}], "seq": 1},
        {"stories": [{"slug": "a", "state": "ready", "port": "5000"}], "seq": 1},
        {"stories": [{"slug": "a", "state": "ready", "port": 1, "pid": 9}], "seq": 1},
        {"stories": [{"slug": "a", "state": "ready", "port": True}], "seq": 1},
        {"stories": "a", "seq": 1},
        {"stories": [], "seq": -1},
        {"stories": [{"slug": "a", "state": "ready", "port": 1}] * (bus.MAX_STORY_ROWS + 1), "seq": 1},
    ):
        with pytest.raises(bus.BusRefusal):
            bus.check_args(op, bad)


@pytest.mark.parametrize("op", WORKER_ONLY)
def test_a_lane_op_is_forbidden_from_the_front_door(server: BusServer, op: str, caplog: Any) -> None:
    """T11: only a worker queues for the model server (spec §14.2)."""
    front = _client(server, "frontdoor")
    try:
        with caplog.at_level(logging.WARNING, logger="engine.hosting.bus"):
            with pytest.raises(BusError) as caught:
                front.request(op, _ARGS[op])
        assert caught.value.code == "forbidden"
        assert [r for r in caplog.records if "forbidden" in r.getMessage()]
    finally:
        front.close()


def test_queue_snapshot_is_forbidden_from_a_worker(server: BusServer) -> None:
    """T11: the panel's view of the queue is the front door's alone."""
    worker = _client(server)
    try:
        with pytest.raises(BusError) as caught:
            worker.request("queue.snapshot", {})
        assert caught.value.code == "forbidden"
    finally:
        worker.close()


def test_a_lane_acquire_is_stamped_with_the_connection_s_story(server: BusServer) -> None:
    """
    T11: a ``lane.acquire`` naming another story is queued under the
    connection's own (spec §14.2): a worker cannot queue, or pause-skip, as
    another story. Answered later, from another thread (a deferred reply).
    """
    seen: list[dict[str, Any]] = []

    def acquire(conn: Any, args: dict[str, Any], answer: Any) -> None:
        seen.append(dict(args))
        threading.Thread(target=answer, args=({"ticket": "t9"}, ""), name="grant").start()

    server.handle_deferred("lane.acquire", acquire)
    worker = _client(server, story="hue-and-cry")
    try:
        reply = worker.request(
            "lane.acquire", {"lane": "narration", "timeout": 1, "story": "clockwork-dark", "process": "x"}
        )
        assert reply == {"ticket": "t9"}
        assert seen == [
            {"lane": "narration", "timeout": 1, "story": "hue-and-cry", "process": "worker-hue-and-cry"}
        ]
    finally:
        worker.close()


def test_a_reply_that_comes_after_its_caller_gave_up_reaches_on_late(server: BusServer) -> None:
    """T11: the client hands a late reply to ``on_late`` instead of dropping it."""
    answers: list[Any] = []
    late: list[dict[str, Any]] = []
    arrived = threading.Event()

    def acquire(conn: Any, args: dict[str, Any], answer: Any) -> None:
        answers.append(answer)

    server.handle_deferred("lane.acquire", acquire)
    worker = _client(server)
    try:
        with pytest.raises(bus.BusTimeout):
            worker.request(
                "lane.acquire",
                {"lane": "narration", "timeout": 1},
                timeout=0.2,
                on_late=lambda reply: (late.append(reply), arrived.set()),
            )
        assert len(answers) == 1
        answers[0]({"ticket": "t1"}, "")
        assert arrived.wait(JOIN), "the late reply was dropped"
        assert late[0]["ok"] is True and late[0]["result"] == {"ticket": "t1"}
    finally:
        worker.close()


def test_process_and_story_are_stamped_from_the_connection(server: BusServer) -> None:
    worker = _client(server, story="hue-and-cry")
    try:
        seen = worker.request("ready", {"port": 4321, "story": "clockwork-dark", "process": "frontdoor"})["seen"]
        assert seen == {"port": 4321, "story": "hue-and-cry", "process": "worker-hue-and-cry"}
    finally:
        worker.close()


@pytest.mark.parametrize(
    ("op", "args", "code"),
    [
        ("no.such.op", {}, "unknown_op"),
        ("ready", {"port": "5573"}, "bad_args"),
        ("ready", {"port": 0}, "bad_args"),
        ("ready", {"port": True}, "bad_args"),
        ("ready", {}, "bad_args"),
        ("ready", {"port": 1, "extra": 1}, "bad_args"),
    ],
)
def test_an_unknown_op_and_a_bad_argument_are_refused(server: BusServer, op: str, args: Any, code: str) -> None:
    worker = _client(server)
    try:
        with pytest.raises(BusError) as caught:
            worker.request(op, args)  # type: ignore[arg-type]
        assert caught.value.code == code
        assert worker.request("ready", {"port": 2})["seen"]["port"] == 2  # still up
    finally:
        worker.close()


def test_a_front_door_s_bad_slug_type_is_bad_args(server: BusServer) -> None:
    server.handle("stories.stop", lambda conn, args: {"op_id": "op-1"})
    front = _client(server, "frontdoor")
    try:
        with pytest.raises(BusError) as caught:
            front.request("stories.stop", {"slug": 3})
        assert caught.value.code == "bad_args"
        assert front.request("stories.stop", {"slug": "clockwork-dark", "actor": "admin"}) == {"op_id": "op-1"}
    finally:
        front.close()


def test_requests_go_both_ways_on_one_connection(server: BusServer) -> None:
    gate = threading.Event()
    server.handle("ready", lambda conn, args: {"port": args["port"]})
    worker = _client(server)
    try:

        def health(_args: dict[str, Any]) -> dict[str, Any]:
            # While the supervisor's request is being answered, the child asks its own.
            gate.set()
            return {"asked": worker.request("ready", {"port": 77})["port"]}

        worker.handle("health", health)
        (conn,) = server.connections()
        assert server.request(conn, "health", timeout=JOIN) == {"asked": 77}
        assert gate.is_set()
    finally:
        worker.close()


# -- the lifeline and the environment ---------------------------------------------------


def _start_probe(server: BusServer, tmp_path: Path, slug: str = "clockwork-dark") -> tuple[subprocess.Popen, Path]:
    record = server.mint("worker", story=slug)
    control = tmp_path / "control"
    control.mkdir()
    env = dict(os.environ)
    env.update(
        {
            "CLOCKWORK_BUS_ADDR": server.addr,
            "CLOCKWORK_BUS_TOKEN": record.token,
            "CLOCKWORK_PROXY_TOKEN": "p" * 64,
            "CLOCKWORK_BUS_ROLE": "worker",
            "CLOCKWORK_GAME": slug,
            "CLOCKWORK_FAKE_WORKER_DIR": str(control),
        }
    )
    proc = subprocess.Popen(
        [sys.executable, "-u", "-m", "tests.probes.fake_worker", "--role", "worker"],
        cwd=str(REPO),
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    return proc, control


@pytest.mark.process
def test_a_child_whose_link_closes_exits_non_zero_and_holds_no_token(tmp_path: Path) -> None:
    srv = BusServer().start()
    readied = threading.Event()

    def ready(conn: Any, args: dict[str, Any]) -> dict[str, Any]:
        readied.set()
        return {}

    srv.handle("ready", ready)
    proc, control = _start_probe(srv, tmp_path)
    try:
        assert readied.wait(30), "the probe never said ready"
        (report_file,) = control.glob("worker-clockwork-dark-*.json")
        keys = set(json.loads(report_file.read_text(encoding="utf-8"))["env_keys"])
        assert "CLOCKWORK_BUS_TOKEN" not in keys and "CLOCKWORK_PROXY_TOKEN" not in keys
        assert "CLOCKWORK_BUS_ADDR" in keys
        srv.close()
        code = proc.wait(15)
        output = proc.stdout.read().decode("utf-8", "replace") if proc.stdout else ""
        assert code == LIFELINE_EXIT_CODE, output
        assert "The link to the supervisor is lost" in output
    finally:
        srv.close()
        if proc.poll() is None:
            proc.kill()
            proc.wait(10)
        if proc.stdout:
            proc.stdout.close()


def test_the_tokens_are_read_once_and_deleted_from_the_environment() -> None:
    environ = {"CLOCKWORK_BUS_ADDR": "127.0.0.1:1", "CLOCKWORK_BUS_TOKEN": "a" * 64, "CLOCKWORK_PROXY_TOKEN": "b" * 64}
    client = BusClient.from_environment(environ)
    assert client is not None and client.proxy_token == "b" * 64
    assert environ == {"CLOCKWORK_BUS_ADDR": "127.0.0.1:1"}
    assert BusClient.from_environment({"CLOCKWORK_BUS_TOKEN": "c"}) is None


# -- the worker's side: install, drain -------------------------------------------------


class _Store:
    def __init__(self, running: list[int]) -> None:
        self.running = running

    def turns_running(self) -> int:
        return self.running.pop(0) if len(self.running) > 1 else self.running[0]


def test_a_worker_s_drain_waits_for_no_turn_lock() -> None:
    """The worker's part of a drain (the queue's pause is the supervisor's, T11)."""
    from engine.hosting import drain

    assert drain(_Store([1, 1, 0]), 5.0) is True


def test_a_worker_s_drain_that_runs_out_says_so() -> None:
    from engine.hosting import drain

    began = time.monotonic()
    assert drain(_Store([1]), 0.2) is False
    assert time.monotonic() - began >= 0.2


def test_the_worker_local_pause_is_gone() -> None:
    """T11 replaced T10's stopgap (a worker-local Event the gate read) with the queue's pause."""
    from engine.llm import gate

    for name in ("pause_admissions", "resume_admissions", "admissions_paused", "_admissions_paused"):
        assert not hasattr(gate, name), name


def test_turns_running_counts_held_turn_locks() -> None:
    from types import SimpleNamespace

    from engine.session.store import SessionStore

    store = SessionStore()
    held, idle = threading.Lock(), threading.Lock()
    store._sessions = {"a": SimpleNamespace(lock=held), "b": SimpleNamespace(lock=idle)}  # type: ignore[assignment]
    assert store.turns_running() == 0
    assert held.acquire(blocking=False)
    try:
        assert store.turns_running() == 1
    finally:
        held.release()


def test_install_connects_the_bus_and_answers_health_and_drain(
    server: BusServer, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from engine.hosting import BUS_EXTENSION
    from engine.llm import gate
    from tests import hosted_app

    record = server.mint("worker", story="clockwork-dark")
    env = {"CLOCKWORK_BUS_ADDR": server.addr, "CLOCKWORK_BUS_TOKEN": record.token, "CLOCKWORK_PROXY_TOKEN": "p" * 64}
    client = None
    try:
        hosted = hosted_app.build(monkeypatch, tmp_path, env=env)
        client = hosted.app.extensions[BUS_EXTENSION]
        client.on_lost = lambda: None  # this process must not exit
        assert "CLOCKWORK_BUS_TOKEN" not in os.environ and "CLOCKWORK_PROXY_TOKEN" not in os.environ
        assert client.proxy_token == "p" * 64
        (conn,) = server.connections()
        assert conn.process == "worker-clockwork-dark" and record.state == "live"
        # T17 fix round 1 (M6): the answer carries the worker's dropped metrics.
        assert server.request(conn, "health") == {"metrics_dropped": 0}
        assert server.request(conn, "drain", {"seconds": 1}) == {"drained": True}
        # T11: this worker's lanes are the supervisor's queue now.
        from engine.hosting.lanes_remote import RemoteLanes

        backend = gate.lane_backend()
        assert isinstance(backend, RemoteLanes) and backend.bus is client
    finally:
        gate.reset_lane_backend()
        if client is not None:
            client.close()
        hosted_app.teardown()


def test_install_refuses_when_the_bus_refuses_the_token(
    server: BusServer, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from engine.hosting.config import HostingConfigError
    from tests import hosted_app

    env = {"CLOCKWORK_BUS_ADDR": server.addr, "CLOCKWORK_BUS_TOKEN": "9" * 64}
    try:
        with pytest.raises(HostingConfigError) as caught:
            hosted_app.build(monkeypatch, tmp_path, env=env)
        assert caught.value.key == "CLOCKWORK_BUS_ADDR" and "unauthorized" in str(caught.value)
        assert "9" * 64 not in str(caught.value)
    finally:
        hosted_app.teardown()


def test_no_token_appears_in_any_log_record(server: BusServer, caplog: Any) -> None:
    caplog.set_level(logging.DEBUG)
    good = server.mint("worker", story="clockwork-dark")
    spare = server.mint("frontdoor")
    tokens = [good.token, spare.token]
    client = _bare(server, good.token)
    client.connect()
    try:
        # A refused second hello, a wrong token, a forbidden op, a bad argument.
        with pytest.raises(BusError):
            _bare(server, good.token).connect()
        with pytest.raises(BusError):
            _bare(server, "f" * 64).connect()
        with pytest.raises(BusError):
            client.request("stories.stop", {"slug": "x"})
        with pytest.raises(BusError):
            client.request("ready", {"port": "x"})
    finally:
        client.close()
    for record in caplog.records:
        text = record.getMessage() + repr(record.args) + (record.exc_text or "")
        for token in tokens:
            assert token not in text, record.getMessage()
    assert caplog.records, "nothing was logged: the check saw nothing"
