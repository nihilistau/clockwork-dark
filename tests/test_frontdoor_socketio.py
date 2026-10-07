"""
Socket.IO through the front door: long polling and the proxy's timeouts
(v0.20.0 T12), and the WebSocket relay (T13), spec §14.5.

Polling is plain HTTP, so it goes through the front door's catch-all proxy:
the handshake, ``connect``, ``join_session`` and a streamed turn, spoken with
``tests/engineio_wire.py`` over ``httpx``, arrive event for event as the same
turn played straight against the worker.

The WebSocket -- every browser's path, since the client does not fall back
to polling -- goes through the relay (``engine/hosting/frontdoor/ws_relay.py``):
the same turn over it equals the turn played straight at the worker; every
refusal is plain HTTP and reaches no worker; a worker's refused upgrade is a
502 and the client's next bytes are the front door's to parse; text and
binary keep their types; a message over the cap closes the connection;
either side's close closes the other and the relay thread is joined; and
open WebSockets, polls and HTTP turns share the front door's long holds, so
the threads kept for HTTP stay free. The last section runs the same against
real processes, which is how the Linux container and CI prove it under
gunicorn.

The proxy's read timeout is set per route class, each above the longest wait
it covers: a polling ``GET`` (engineio holds it up to ``ping_interval +
ping_timeout``) 60 s; a turn (``queue_wait_seconds + turn_deadline_seconds``,
plus a minute: fix round 1, I2); anything else 30 s. Asserted on the classifier and on what
the proxy actually hands ``httpx`` for each class, not by waiting a minute.

A proxied HTTP turn holds a front door thread for as long as its worker
takes, so the front door keeps its own turn slots (``limits.TurnSlots``):
past ``threads - RESERVED_THREADS`` in flight, the next is answered 429 at
once, and every other request is still served.

In this process (``tests/hosting_instance.py::InProcessFrontDoor``), bar the
last section (``HostingInstance``, one module instance).
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Iterator

import httpx
import pytest

from tests.engineio_wire import PollingClient, WebSocketClient, cookie_header, read_response, upgrade
from tests.hosting_instance import InProcessFrontDoor

# In-process loopback servers: the hybrid run's serial phase (tests/tiers.py).
pytestmark = pytest.mark.loopback

JOIN = 30.0


@pytest.fixture
def door(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[InProcessFrontDoor]:
    instance = InProcessFrontDoor(monkeypatch, tmp_path, hosting={"rate_limits": {"actions_per_minute": 1000}})
    instance.start()
    try:
        yield instance
    finally:
        instance.stop()


def _names(events: list[dict[str, Any]]) -> list[str]:
    return [e.get("name") or e["type"] for e in events]


def _update(events: list[dict[str, Any]]) -> dict[str, Any]:
    """
    The turn's ``turn_update``. Not necessarily the last event: a poll can
    bring an ``image_ready`` in the same batch (seen in the Linux container,
    T13), so the turn is found by name, never by position.
    """
    return next(e for e in events if e.get("name") == "turn_update")


def _to_update(events: list[dict[str, Any]]) -> list[str]:
    """
    The event names up to and including ``turn_update``: what follows it in
    the same turn (``portrait_ready``, ``image_ready``) arrives in the poll
    that brought the update or in the next, by timing, so a comparison past
    it compares batches, not turns (seen in the Linux container, T13).
    """
    names = _names(events)
    return names[: names.index("turn_update") + 1]


def _turn(http: httpx.Client, base: str) -> dict[str, Any]:
    """A new run over HTTP, then the socket: connect, join, one choice. What the socket heard."""
    opened = http.post(f"{base}/api/game/new", json={"seed": 11, "player_name": "Wren"})
    assert opened.status_code == 200, opened.text[:300]
    run = opened.json()
    choice = ((run.get("opening") or {}).get("choices") or [{"id": "a"}])[0]["id"]
    poll = PollingClient(http, base)
    try:
        poll.handshake()
        assert poll.connect()["type"] == "connect"
        mark = len(poll.received)
        poll.emit("join_session", {"session_id": run["session_id"]})
        poll.until(lambda e: e.get("name") in ("game_started", "error"))
        joined = poll.received[mark:]
        mark = len(poll.received)
        poll.emit("player_choice", {"session_id": run["session_id"], "choice_id": choice})
        poll.until(lambda e: e.get("name") in ("turn_update", "turn_error"))
        turn = poll.received[mark:]
    finally:
        poll.close()
    return {"joined": joined, "turn": turn}


def test_a_polling_turn_through_the_front_door_is_the_turn_played_direct(door: InProcessFrontDoor) -> None:
    """
    One account through the front door, another straight to the worker with
    its own login cookie: the same seed, the same choice, the same events in
    the same order, the final turn's narration equal.
    """
    front = door.logged_in("front")
    direct_login = door.logged_in("direct")
    direct = door.http(door.worker_base)
    direct.cookies = direct_login.cookies
    try:
        through = _turn(front, door.base)
        straight = _turn(direct, door.worker_base)
    finally:
        for client in (front, direct_login, direct):
            client.close()
    assert _names(through["joined"]) == _names(straight["joined"]) == ["game_started"]
    assert _to_update(through["turn"]) == _to_update(straight["turn"])
    assert "turn_update" in _names(through["turn"])
    narration = [e["args"][0]["narration"] for e in (_update(through["turn"]), _update(straight["turn"]))]
    assert narration[0] == narration[1] and narration[0]


def test_the_read_timeout_per_route_class(door: InProcessFrontDoor, monkeypatch: pytest.MonkeyPatch) -> None:
    from engine.hosting.frontdoor import frontdoor
    from engine.hosting.frontdoor.proxy import DEFAULT_READ_SECONDS, POLLING_READ_SECONDS

    proxy = frontdoor(door.front_app).proxy
    settings = door.hosted.state.settings
    eio = door.hosted.scene.socketio.server.eio
    # The longest legitimate turn: its wait for a place, then its deadline.
    turn_wait = settings.queue_wait_seconds + settings.turn_deadline_seconds
    assert turn_wait == 1500  # the shipped 600 + 900

    # The classifier, each class above the wait it covers.
    assert proxy.read_timeout_for("GET", "/socket.io/") == POLLING_READ_SECONDS == 60
    assert POLLING_READ_SECONDS > eio.ping_interval + eio.ping_timeout
    for path in ("/api/game/new", "/api/game/choice", "/api/voice/transcribe"):
        assert proxy.read_timeout_for("POST", path) == turn_wait + 60
        assert proxy.read_timeout_for("POST", path) > turn_wait
    assert proxy.read_timeout_for("GET", "/api/games") == DEFAULT_READ_SECONDS == 30
    assert proxy.read_timeout_for("POST", "/socket.io/") == DEFAULT_READ_SECONDS
    assert proxy.read_timeout_for("GET", "/api/game/choice") == DEFAULT_READ_SECONDS

    # What httpx is actually handed, for a real request of each class.
    handed: list[tuple[str, str, dict[str, Any]]] = []
    real_send = proxy.client.send

    def send(request: httpx.Request, **kwargs: Any) -> httpx.Response:
        handed.append((request.method, request.url.path, dict(request.extensions.get("timeout") or {})))
        return real_send(request, **kwargs)

    monkeypatch.setattr(proxy.client, "send", send)
    http = door.logged_in()
    try:
        PollingClient(http, door.base).handshake()
        assert http.get("/api/games").status_code == 200
        assert http.post("/api/game/new", json={"seed": 3}).status_code == 200
    finally:
        http.close()
    reads = {(m, p): t["read"] for m, p, t in handed}
    assert reads[("GET", "/socket.io/")] == 60
    assert reads[("GET", "/api/games")] == 30
    assert reads[("POST", "/api/game/new")] == turn_wait + 60
    assert all(t["connect"] == 5 for _m, _p, t in handed)


def test_proxied_http_turns_never_hold_every_front_door_thread(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """
    ``threads: 5`` leaves the front door one turn slot (``RESERVED_THREADS``
    = 4 kept). A proxied turn waiting in the model server's queue holds it;
    a second HTTP turn is answered 429 by the front door at once and never
    reaches a worker, while login pages, the picker and other requests are
    served. The slot comes back when the first turn ends.
    """
    from engine.hosting.bus import BusClient
    from engine.hosting.frontdoor import frontdoor
    from engine.hosting.lanes_remote import RemoteLanes
    from engine.hosting.limits import RESERVED_THREADS, SERVER_BUSY

    door = InProcessFrontDoor(
        monkeypatch,
        tmp_path,
        hosting={"threads": RESERVED_THREADS + 1, "queue_wait_seconds": 60},
    )
    door.start()
    holder = None
    reached: list[str] = []
    worker_layer = door.hosted.app.wsgi_app

    def counting(environ: dict[str, Any], start_response: Any) -> Any:
        reached.append(f"{environ.get('REQUEST_METHOD')} {environ.get('PATH_INFO')}")
        return worker_layer(environ, start_response)

    door.hosted.app.wsgi_app = counting
    try:
        alice = door.logged_in("alice")
        bob = door.logged_in("bob")
        run = alice.post("/api/game/new", json={"seed": 5}).json()
        bob_run = bob.post("/api/game/new", json={"seed": 6}).json()
        # Another worker's turn holds the one narration slot of the queue.
        record = door.server.mint("worker", story="other-story", process="worker-other-story")
        holder = BusClient(door.server.addr, record.token)
        holder.on_lost = lambda: None
        holder.connect()
        ticket = RemoteLanes(holder).acquire("narration", 1.0)
        slots = frontdoor(door.front_app).proxy.slots
        answers: list[Any] = []
        thread = threading.Thread(
            target=lambda: answers.append(
                alice.post("/api/game/choice", json={"session_id": run["session_id"], "choice_id": "a"})
            ),
            name="waiting-proxied-turn",
        )
        thread.start()
        assert door.queue.wait_for(
            lambda snap: any(row["waiters"] for row in snap["lanes"] if row["lane"] == "narration"), JOIN
        ), "the proxied turn never queued"
        assert slots.inside == 1
        refused = bob.post("/api/game/choice", json={"session_id": bob_run["session_id"], "choice_id": "a"})
        assert refused.status_code == 429 and refused.json() == {"error": SERVER_BUSY}
        assert reached.count("POST /api/game/choice") == 1, "the refused turn reached the worker"
        assert bob.get("/api/health").status_code == 200
        assert bob.get("/stories").status_code == 200
        assert bob.get("/api/games").status_code == 200
        RemoteLanes(holder).release(ticket)
        thread.join(JOIN)
        assert not thread.is_alive() and answers[0].status_code == 200, answers
        assert slots.inside == 0
        played = bob.post("/api/game/choice", json={"session_id": bob_run["session_id"], "choice_id": "a"})
        assert played.status_code == 200, played.text[:300]
        alice.close()
        bob.close()
    finally:
        if holder is not None:
            holder.close()
        door.stop()


# -- fix round 1 ----------------------------------------------------------------------


def _stall(port: int, path: str, cookie: str, content_type: str = "application/json") -> Any:
    """A raw socket sending a turn's headers and ONE byte of a 1000-byte body, then nothing."""
    import socket

    sock = socket.create_connection(("127.0.0.1", port), timeout=JOIN)
    sock.sendall(
        (
            f"POST {path} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n"
            f"Cookie: clockwork_session={cookie}\r\nContent-Type: {content_type}\r\n"
            "Content-Length: 1000\r\n\r\n{"
        ).encode("ascii")
    )
    return sock


def _status_of(sock: Any) -> bytes:
    """The status line the server sends back (within JOIN seconds)."""
    data = b""
    while b"\r\n" not in data:
        chunk = sock.recv(4096)
        if not chunk:
            break
        data += chunk
    return data.split(b"\r\n", 1)[0]


@pytest.mark.parametrize("where", ["front door", "worker"])
@pytest.mark.slow
def test_one_account_s_trickled_bodies_hold_no_turn_slot(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, where: str
) -> None:
    """
    The review's probe (I1): one account opens raw sockets that send a
    turn's headers and one byte of its body, then nothing. Another account's
    turn is still admitted and plays, at the front door and straight at a
    worker; each trickled request is answered 408 once
    ``hosting.body_read_seconds`` runs out. On eb1d4d4 both slots (``threads:
    RESERVED_THREADS + 2``) were held by the stalled bodies and the other
    account's turn was refused 429 for as long as the sockets stayed open.
    (At the worker the probe stalls a voice upload: a choice's body was
    already read there before its slot, by the input cap.)
    """
    import time

    import engine.hosting.frontdoor.proxy as proxy_module
    import engine.hosting.gate as gate_module
    from engine.hosting.frontdoor import frontdoor
    from engine.hosting.limits import RESERVED_THREADS

    door = InProcessFrontDoor(
        monkeypatch,
        tmp_path,
        hosting={
            "threads": RESERVED_THREADS + 2,
            "body_read_seconds": 3,
            "rate_limits": {"actions_per_minute": 1000},
        },
    )
    door.start()
    stalled: list[Any] = []
    entered: list[str] = []
    module = proxy_module if where == "front door" else gate_module
    real = getattr(module, "read_body", None)
    if real is not None:

        def counting(*args: Any, **kwargs: Any) -> Any:
            entered.append("read")
            return real(*args, **kwargs)

        monkeypatch.setattr(module, "read_body", counting)
    try:
        alice = door.logged_in("alice")
        bob = door.logged_in("bob")
        bob_run = bob.post("/api/game/new", json={"seed": 6}).json()
        cookie = str(alice.cookies.get("clockwork_session"))
        if where == "front door":
            port, path, kind = door.front_port, "/api/game/choice", "application/json"
            slots = frontdoor(door.front_app).proxy.slots
        else:
            port, path, kind = door.worker_port, "/api/voice/transcribe", "multipart/form-data; boundary=x"
            slots = door.hosted.state.turn_slots
        stalled = [_stall(port, path, cookie, kind) for _ in range(2)]
        # Both stalled requests are in: holding slots (eb1d4d4) or reading
        # their bodies before any slot (now).
        deadline = time.monotonic() + JOIN
        pause = threading.Event()
        while not (slots.inside == 2 or len(entered) >= 2):
            assert time.monotonic() < deadline, "the stalled requests never arrived"
            pause.wait(0.02)
        played = bob.post("/api/game/choice", json={"session_id": bob_run["session_id"], "choice_id": "a"})
        assert played.status_code == 200, (played.status_code, played.text[:200])
        for sock in stalled:
            assert _status_of(sock).startswith(b"HTTP/1.1 408"), "a trickled body was not refused in time"
        assert slots.inside == 0
        alice.close()
        bob.close()
    finally:
        for sock in stalled:
            sock.close()
        door.stop()


def test_an_account_has_one_http_turn_in_flight(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """
    I1: while one of alice's turns waits in the queue, her second is answered
    429 at once ("Your last turn is still on its way"), while bob's is
    admitted to wait beside it.
    """
    from engine.hosting.bus import BusClient
    from engine.hosting.frontdoor import frontdoor
    from engine.hosting.lanes_remote import RemoteLanes
    from engine.hosting.limits import RESERVED_THREADS, TURN_IN_FLIGHT

    door = InProcessFrontDoor(
        monkeypatch,
        tmp_path,
        hosting={
            "threads": RESERVED_THREADS + 2,
            "queue_wait_seconds": 60,
            "rate_limits": {"actions_per_minute": 1000},
        },
    )
    door.start()
    holder = None
    try:
        alice = door.logged_in("alice")
        bob = door.logged_in("bob")
        run = alice.post("/api/game/new", json={"seed": 5}).json()
        bob_run = bob.post("/api/game/new", json={"seed": 6}).json()
        record = door.server.mint("worker", story="other-story", process="worker-other-story")
        holder = BusClient(door.server.addr, record.token)
        holder.on_lost = lambda: None
        holder.connect()
        ticket = RemoteLanes(holder).acquire("narration", 1.0)
        slots = frontdoor(door.front_app).proxy.slots
        answers: list[Any] = []

        def turn(http: httpx.Client, opened: dict[str, Any]) -> threading.Thread:
            thread = threading.Thread(
                target=lambda: answers.append(
                    http.post("/api/game/choice", json={"session_id": opened["session_id"], "choice_id": "a"})
                ),
                name="waiting-turn",
            )
            thread.start()
            return thread

        def waiting(count: int) -> bool:
            return door.queue.wait_for(
                lambda snap: any(len(row["waiters"]) == count for row in snap["lanes"] if row["lane"] == "narration"),
                JOIN,
            )

        first = turn(alice, run)
        assert waiting(1)
        again = alice.post("/api/game/choice", json={"session_id": run["session_id"], "choice_id": "a"})
        assert again.status_code == 429 and again.json() == {"error": TURN_IN_FLIGHT}
        second = turn(bob, bob_run)
        assert waiting(2), "bob's turn was not admitted beside alice's"
        assert slots.inside == 2
        RemoteLanes(holder).release(ticket)
        for thread in (first, second):
            thread.join(JOIN)
            assert not thread.is_alive()
        assert [a.status_code for a in answers] == [200, 200], answers
        alice.close()
        bob.close()
    finally:
        if holder is not None:
            holder.close()
        door.stop()


def test_a_turn_past_the_old_bound_but_inside_the_new_one_is_not_cut(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """
    I2, scaled down: ``queue_wait_seconds`` 1, ``llm.timeout_seconds`` 1,
    ``turn_deadline_seconds`` 8 and a 0.1 s margin. A turn whose model takes
    2.6 s is past eb1d4d4's bound (wait + model timeout + margin = 2.1 s: the
    front door answered 504 while the worker committed the turn) and inside
    the new one (wait + deadline + margin = 9.1 s): it reaches the player.
    (v0.21.1 T1 fix round 1: was a 0.5 s margin and a 4 s model.)
    """
    import engine.hosting.frontdoor.proxy as proxy_module
    from engine.hosting.frontdoor import frontdoor

    monkeypatch.setattr(proxy_module, "TURN_MARGIN_SECONDS", 0.1)
    slow = threading.Event()
    reply = (
        '```json\n{"narration": "The lamps gutter.", "choices": [{"id": "a", "text": "Wait"}, '
        '{"id": "b", "text": "Go"}]}\n```'
    )

    def model(_messages: Any, *_args: Any, **_kwargs: Any) -> str:
        if slow.is_set():
            threading.Event().wait(2.6)  # the model's own pace: the duration under test
        return reply

    door = InProcessFrontDoor(
        monkeypatch,
        tmp_path,
        hosting={"queue_wait_seconds": 1, "turn_deadline_seconds": 8},
        extra={"llm": {"timeout_seconds": 1}},
        llm_fn=model,
    )
    door.start()
    try:
        proxy = frontdoor(door.front_app).proxy
        http = door.logged_in()
        run = http.post("/api/game/new", json={"seed": 2}).json()
        slow.set()
        played = http.post("/api/game/choice", json={"session_id": run["session_id"], "choice_id": "a"})
        assert played.status_code == 200, (played.status_code, played.text[:200])
        assert "The lamps gutter." in played.json()["narration"]
        http.close()
        assert proxy.read_timeout_for("POST", "/api/game/choice") == 1 + 8 + 0.1
    finally:
        door.stop()


def _chunked_stall(port: int, path: str, cookie: str) -> Any:
    """
    A raw socket sending a request with ``Transfer-Encoding: chunked``, a
    chunk header announcing 0x1000 bytes and ONE byte of it, then nothing:
    the re-review's probe (N1).
    """
    import socket

    sock = socket.create_connection(("127.0.0.1", port), timeout=10)
    sock.sendall(
        (
            f"POST {path} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n"
            f"Cookie: clockwork_session={cookie}\r\nContent-Type: application/json\r\n"
            "Transfer-Encoding: chunked\r\n\r\n1000\r\n{"
        ).encode("ascii")
    )
    return sock


@pytest.mark.parametrize("where", ["front door", "worker"])
def test_a_chunked_body_is_refused_411_at_once(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, where: str) -> None:
    """
    Fix round 2 (N1): a chunked body's reads cannot be held to
    ``body_read_seconds`` (Werkzeug's ``DechunkedInput`` fills a whole buffer
    in one call, each recv restarting the timeout), so hosted mode takes a
    body only with its length. A turn, and a Socket.IO polling POST, sent
    chunked and trickled are answered 411 at once, at both doors, and
    another account's turn plays. On 2b55e89 the trickled turn got no answer
    at all (the re-review saw the connection still open at 12 s).
    """
    from engine.hosting.limits import RESERVED_THREADS

    door = InProcessFrontDoor(
        monkeypatch,
        tmp_path,
        hosting={
            "threads": RESERVED_THREADS + 2,
            "body_read_seconds": 3,
            "rate_limits": {"actions_per_minute": 1000},
        },
    )
    door.start()
    stalled: list[Any] = []
    try:
        alice = door.logged_in("alice")
        bob = door.logged_in("bob")
        bob_run = bob.post("/api/game/new", json={"seed": 6}).json()
        cookie = str(alice.cookies.get("clockwork_session"))
        port = door.front_port if where == "front door" else door.worker_port
        for path in ("/api/game/choice", "/socket.io/?EIO=4&transport=polling&sid=x"):
            sock = _chunked_stall(port, path, cookie)
            stalled.append(sock)
            assert _status_of(sock).startswith(b"HTTP/1.1 411"), f"{path}: a chunked body was not refused"
        played = bob.post("/api/game/choice", json={"session_id": bob_run["session_id"], "choice_id": "a"})
        assert played.status_code == 200, (played.status_code, played.text[:200])
        alice.close()
        bob.close()
    finally:
        for sock in stalled:
            sock.close()
        door.stop()


# -- v0.20.0 T13: the WebSocket relay ------------------------------------------------------


def _ws_turn(http: httpx.Client, base: str) -> dict[str, Any]:
    """``_turn`` over the WebSocket, as the browser plays it."""
    opened = http.post(f"{base}/api/game/new", json={"seed": 11, "player_name": "Wren"})
    assert opened.status_code == 200, opened.text[:300]
    run = opened.json()
    choice = ((run.get("opening") or {}).get("choices") or [{"id": "a"}])[0]["id"]
    ws = WebSocketClient(http, base)
    try:
        ws.handshake()
        assert ws.connect()["type"] == "connect"
        mark = len(ws.received)
        ws.emit("join_session", {"session_id": run["session_id"]})
        ws.until(lambda e: e.get("name") in ("game_started", "error"))
        joined = ws.received[mark:]
        mark = len(ws.received)
        ws.emit("player_choice", {"session_id": run["session_id"], "choice_id": choice})
        ws.until(lambda e: e.get("name") in ("turn_update", "turn_error"))
        turn = ws.received[mark:]
    finally:
        ws.close()
    return {"joined": joined, "turn": turn}


def _counting(door: InProcessFrontDoor) -> list[str]:
    """Every ``METHOD path?query`` the worker is sent from now on."""
    reached: list[str] = []
    inner = door.hosted.app.wsgi_app

    def counting(environ: dict[str, Any], start_response: Any) -> Any:
        reached.append(f"{environ.get('REQUEST_METHOD')} {environ.get('PATH_INFO')}?{environ.get('QUERY_STRING', '')}")
        return inner(environ, start_response)

    door.hosted.app.wsgi_app = counting
    return reached


def _wait(check: Any, timeout: float = 10.0, what: str = "") -> Any:
    import time

    deadline = time.monotonic() + timeout
    pause = threading.Event()
    while time.monotonic() < deadline:
        found = check()
        if found:
            return found
        pause.wait(0.02)
    raise AssertionError(f"not within {timeout}s: {what}")


def _relay_threads() -> list[threading.Thread]:
    return [t for t in threading.enumerate() if t.name == "frontdoor-ws-relay"]


def test_a_websocket_turn_through_the_relay_is_the_turn_played_direct(door: InProcessFrontDoor) -> None:
    """
    The browser's path (v0.20.0 T13): over WebSocket through the front
    door's relay, ``connect``, ``join_session`` and one streamed turn arrive
    event for event as the same turn played over WebSocket straight at the
    worker. On 270b502 the upgrade went to the HTTP proxy, which dropped
    ``Upgrade``, and the handshake failed.
    """
    from engine.hosting.frontdoor import frontdoor

    front = door.logged_in("front")
    direct_login = door.logged_in("direct")
    direct = door.http(door.worker_base)
    direct.cookies = direct_login.cookies
    door_state = frontdoor(door.front_app)
    try:
        through = _ws_turn(front, door.base)
        straight = _ws_turn(direct, door.worker_base)
    finally:
        for client in (front, direct_login, direct):
            client.close()
    assert _names(through["joined"]) == _names(straight["joined"]) == ["game_started"]
    assert _to_update(through["turn"]) == _to_update(straight["turn"])
    assert "turn_update" in _names(through["turn"])
    narration = [e["args"][0]["narration"] for e in (_update(through["turn"]), _update(straight["turn"]))]
    assert narration[0] == narration[1] and narration[0]
    _wait(lambda: door_state.relay.active == 0 and not _relay_threads(), what="the relay ended, its thread joined")
    assert door_state.holds.inside == 0


@pytest.mark.parametrize(
    "case",
    [
        "no cookie",
        "cross-site origin",
        "cross-scheme origin",
        "forwarded host and scheme, untrusted",
        "no story",
        "bad handshake",  # fix round 1, M5: refused before the worker makes a session
    ],
)
def test_a_refused_upgrade_is_plain_http_and_never_reaches_the_worker(door: InProcessFrontDoor, case: str) -> None:
    """
    Each refusal is answered by the front door as plain HTTP (never a 101)
    and nothing reaches the worker (its request counter). The Origin is
    judged against the RESOLVED scheme and Host: under ``trusted_proxies: 0``
    a client's ``X-Forwarded-Host``/``-Proto`` are deleted before the check,
    so claiming the https origin through them does not pass.
    """
    from engine.hosting.gate import CROSS_SITE, LOGIN_REQUIRED

    http = door.logged_in("rowan", chosen=case != "no story")
    reached = _counting(door)
    own = f"127.0.0.1:{door.front_port}"
    headers: list[tuple[str, str]] = [("Cookie", cookie_header(http)), ("Origin", f"http://{own}")]
    expected = {"no cookie": 401, "no story": 409, "bad handshake": 400}.get(case, 403)
    if case == "no cookie":
        headers = [("Origin", f"http://{own}")]
    elif case == "cross-site origin":
        headers[1] = ("Origin", "http://evil.example")
    elif case == "cross-scheme origin":
        headers[1] = ("Origin", f"https://{own}")
    elif case == "forwarded host and scheme, untrusted":
        headers[1] = ("Origin", "https://game.example")
        headers += [("X-Forwarded-Host", "game.example"), ("X-Forwarded-Proto", "https")]
    sock = None
    try:
        status, found, body, sock = upgrade(
            door.front_port,
            "/socket.io/?EIO=4&transport=websocket",
            headers,
            key="not-a-key" if case == "bad handshake" else "dGhlIHNhbXBsZSBub25jZQ==",
        )
    finally:
        if sock is not None:
            sock.close()
        http.close()
    assert status == expected, (status, body[:200])
    assert "sec-websocket-accept" not in found
    if case == "no cookie":
        assert json.loads(body) == LOGIN_REQUIRED
    if case == "cross-scheme origin":
        assert json.loads(body) == CROSS_SITE  # the relay's own check: the host guard compares hosts only
    assert not [r for r in reached if "/socket.io" in r], reached


def test_a_worker_refusing_the_upgrade_gives_502_and_the_next_request_is_the_front_door_s(
    door: InProcessFrontDoor,
) -> None:
    """
    A bad ``sid``: the worker answers the relay's upgrade 400, the client
    gets 502 and no upgrade. What the client sends next on that keep-alive
    connection is a new request to the FRONT DOOR (``/api/health`` answers
    ``role: frontdoor``), never bytes the worker parses: the relay never
    lets the client speak HTTP to a worker.
    """
    from engine.hosting.frontdoor.ws_relay import WORKER_REFUSED

    http = door.logged_in("rowan")
    reached = _counting(door)
    own = f"127.0.0.1:{door.front_port}"
    sock = None
    try:
        status, found, body, sock = upgrade(
            door.front_port,
            "/socket.io/?EIO=4&transport=websocket&sid=not-a-session",
            [("Cookie", cookie_header(http)), ("Origin", f"http://{own}")],
        )
        assert status == 502 and json.loads(body) == WORKER_REFUSED
        assert "sec-websocket-accept" not in found
        _next_request_is_the_front_door_s(sock, found, own)
    finally:
        if sock is not None:
            sock.close()
        http.close()
    assert [r for r in reached if "/socket.io" in r] == [
        "GET /socket.io/?EIO=4&transport=websocket&sid=not-a-session"
    ]
    assert not [r for r in reached if "/api/health" in r], "the client's next request reached the worker"


def _next_request_is_the_front_door_s(sock: Any, found: dict[str, str], own: str) -> str:
    """
    After a refused upgrade: the connection is closed (Werkzeug closes every
    connection after its answer), or -- kept alive, as gunicorn does -- the
    next request on it is answered by the front door itself. Which it was.
    """
    if found.get("connection", "").lower() == "close":
        sock.settimeout(10)
        try:
            rest = sock.recv(4096)
        except ConnectionResetError:
            rest = b""
        assert rest == b"", f"bytes after a closing answer: {rest[:100]!r}"
        return "closed"
    sock.sendall(f"GET /api/health HTTP/1.1\r\nHost: {own}\r\n\r\n".encode("ascii"))
    status, _found, body = read_response(sock)
    assert status == 200 and json.loads(body)["role"] == "frontdoor", (status, body[:200])
    return "kept alive"


def test_a_login_revoked_after_the_upgrade_is_refused_at_connect(door: InProcessFrontDoor) -> None:
    """
    The relay authenticates the upgrade; the worker's socket guard still
    authenticates ``connect``: an account disabled between the two is
    refused there, over the relayed socket.
    """
    http = door.logged_in("rowan")
    ws = WebSocketClient(http, door.base)
    try:
        ws.handshake()
        door.hosted.state.accounts.disable("rowan")
        answer = ws.connect()
    finally:
        ws.close()
        http.close()
    assert answer["type"] in ("connect_error", "close"), answer


class _EchoWorker:
    """A WebSocket server standing in for a worker: echoes, records types, closes on command."""

    def __init__(self) -> None:
        from werkzeug.serving import make_server

        self.got: list[Any] = []
        self.closed = threading.Event()
        self.close_code: Any = None
        self.server = make_server("127.0.0.1", 0, self.app, threaded=True)
        self.port = int(self.server.server_port)
        self.thread = threading.Thread(target=self.server.serve_forever, name="echo-worker", daemon=True)
        self.thread.start()

    def app(self, environ: dict[str, Any], start_response: Any) -> Any:
        import simple_websocket

        ws = simple_websocket.Server(environ)
        try:
            while True:
                message = ws.receive(timeout=30)
                if message is None:
                    break
                self.got.append(message)
                if message == "close-me":
                    ws.close(reason=4001)
                    break
                if message == "big":  # fix round 1, M2: a worker's message past the inbound cap
                    ws.send("y" * 100_000)
                    continue
                if message == "flood":  # fix round 1, M1: more than a client that never reads can take
                    self.flood(ws)
                    break
                ws.send(message)
        except simple_websocket.ConnectionClosed:
            self.close_code = ws.close_reason
        finally:
            self.closed.set()
        raise ConnectionError()

    def flood(self, ws: Any) -> None:
        """Send 64 KiB messages until the relay stops taking them (at most 64 MiB)."""
        import simple_websocket

        chunk = "f" * 65536
        try:
            for _ in range(1024):
                ws.send(chunk)
                if not ws.connected:
                    break
        except (simple_websocket.ConnectionClosed, OSError):
            pass
        # Wait for the relay to close this end (or give up after 30 s).
        try:
            while ws.connected and ws.receive(timeout=30) is not None:
                pass
        except simple_websocket.ConnectionClosed:
            pass

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(10)
        assert not self.thread.is_alive()


@pytest.fixture
def echo(door: InProcessFrontDoor) -> Iterator[_EchoWorker]:
    worker = _EchoWorker()
    real = door.worker_port
    door.worker_port = worker.port
    door.set_state("ready")
    try:
        yield worker
    finally:
        door.worker_port = real
        door.set_state("ready")
        worker.stop()


def _socket(door: InProcessFrontDoor, http: httpx.Client) -> Any:
    from tests.engineio_wire import TestWebSocket

    return TestWebSocket(
        f"ws://127.0.0.1:{door.front_port}/socket.io/?EIO=4&transport=websocket",
        headers=[("Cookie", cookie_header(http)), ("Origin", door.base)],
    )


def test_text_and_binary_are_relayed_as_themselves(door: InProcessFrontDoor, echo: _EchoWorker) -> None:
    http = door.logged_in("rowan")
    ws = _socket(door, http)
    try:
        ws.send("hello")
        ws.send(b"\x00\x01\xff")
        back = [ws.receive(timeout=10), ws.receive(timeout=10)]
    finally:
        ws.close()
        http.close()
    assert echo.got[:2] == ["hello", b"\x00\x01\xff"]
    assert back == ["hello", b"\x00\x01\xff"]
    assert isinstance(back[0], str) and isinstance(back[1], bytes)


def test_a_message_over_the_cap_closes_the_connection(door: InProcessFrontDoor, echo: _EchoWorker) -> None:
    import simple_websocket

    from engine.scenes.flask_scene import HOSTED_SOCKET_BUFFER_BYTES

    http = door.logged_in("rowan")
    ws = _socket(door, http)
    try:
        ws.send("x" * (HOSTED_SOCKET_BUFFER_BYTES + 1))
        with pytest.raises(simple_websocket.ConnectionClosed):
            while True:
                assert ws.receive(timeout=10) is not None, "the connection stayed open"
        assert ws.close_reason == 1009
    finally:
        http.close()
    assert echo.closed.wait(10), "the worker's side was not closed"
    assert not echo.got, "the oversized message reached the worker"


def test_closing_either_side_closes_the_other_and_joins_the_relay(door: InProcessFrontDoor, echo: _EchoWorker) -> None:
    import simple_websocket

    from engine.hosting.frontdoor import frontdoor

    door_state = frontdoor(door.front_app)
    http = door.logged_in("rowan")
    # The client closes: the worker's side closes with its code, the relay ends.
    ws = _socket(door, http)
    ws.send("ping")
    assert ws.receive(timeout=10) == "ping"
    ws.close(reason=4002)
    assert echo.closed.wait(10), "the worker's side stayed open"
    assert echo.close_code == 4002
    _wait(lambda: door_state.relay.active == 0 and not _relay_threads(), what="the relay thread joined")
    # The worker closes: the client's side closes with the worker's code.
    echo.closed.clear()
    ws = _socket(door, http)
    ws.send("close-me")
    with pytest.raises(simple_websocket.ConnectionClosed):
        while True:
            assert ws.receive(timeout=10) is not None, "the client's side stayed open"
    assert ws.close_reason == 4001
    _wait(lambda: door_state.relay.active == 0 and not _relay_threads(), what="the relay thread joined")
    assert door_state.holds.inside == 0
    http.close()


def test_open_websockets_never_take_the_threads_kept_for_http(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """
    T12's review M3: ``threads: RESERVED_THREADS + 2`` gives the front door
    two long holds. Two open WebSockets take both: a third upgrade is
    answered 503 at once, as are a poll and (429) an HTTP turn, while the
    login page, the picker and the stylesheet are served. A closed socket
    gives its place back.
    """
    from engine.hosting.frontdoor import frontdoor
    from engine.hosting.limits import RESERVED_THREADS, SERVER_BUSY, SERVER_FULL

    door = InProcessFrontDoor(
        monkeypatch,
        tmp_path,
        hosting={"threads": RESERVED_THREADS + 2, "rate_limits": {"actions_per_minute": 1000}},
    )
    door.start()
    sockets: list[Any] = []
    try:
        http = door.logged_in("rowan")
        run = http.post("/api/game/new", json={"seed": 4}).json()
        holds = frontdoor(door.front_app).holds
        for _ in range(2):
            ws = WebSocketClient(http, door.base)
            sockets.append(ws)
            ws.handshake()
        assert holds.inside == 2
        status, _found, body, sock = upgrade(
            door.front_port,
            "/socket.io/?EIO=4&transport=websocket",
            [("Cookie", cookie_header(http)), ("Origin", door.base)],
        )
        sock.close()
        assert status == 503 and json.loads(body) == {"error": SERVER_FULL}
        polled = http.get("/socket.io/?EIO=4&transport=polling")
        assert polled.status_code == 503 and polled.json() == {"error": SERVER_FULL}
        turn = http.post("/api/game/choice", json={"session_id": run["session_id"], "choice_id": "a"})
        assert turn.status_code == 429 and turn.json() == {"error": SERVER_BUSY}
        assert door.http().get("/login").status_code == 200
        assert http.get("/stories").status_code == 200
        assert http.get("/static/hosting/hosting.css").status_code == 200
        sockets.pop().close()
        _wait(lambda: holds.inside == 1, what="a closed socket gave its place back")
        again = WebSocketClient(http, door.base)
        sockets.append(again)
        again.handshake()
        http.close()
    finally:
        for ws in sockets:
            ws.close()
        door.stop()


# -- v0.20.0 T13: the same, every process real (the gunicorn proof) -----------------------
#
# One instance for these tests (``tests/hosting_instance.py``): the supervisor,
# the scripted worker and the engine's own front door, each a real process on
# loopback. Where gunicorn runs (the Linux container, CI) the supervisor
# serves both under it, so these are the WebSocket relay, the long holds, the
# refused upgrade and the body-read deadline proved under gunicorn; on
# Windows, under Werkzeug.

REAL_STORY = "clockwork-dark"


@pytest.fixture(scope="module")
def real(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Any]:
    from engine.hosting.limits import RESERVED_THREADS
    from tests.hosting_instance import SCRIPTED_WORKER, hosting_instance

    yield from hosting_instance(
        tmp_path_factory,
        "frontdoor-ws",
        stories=[REAL_STORY],
        frontdoor="real",
        worker_module=SCRIPTED_WORKER,
        supervisor={"boot_seconds": 180, "health_failures": 5},
        hosting={
            "cookie_secure": False,
            "threads": RESERVED_THREADS + 2,
            "body_read_seconds": 3,
            "rate_limits": {"actions_per_minute": 1000, "logins_per_minute": 1000, "logins_per_minute_all": 1000},
        },
    )


@pytest.fixture(scope="module")
def real_player(real: Any) -> dict[str, str]:
    return {"name": "wren", "password": real.add_account("wren")}


def _real_client(real: Any, player: dict[str, str]) -> httpx.Client:
    from tests.hosting_instance import choose, login

    http = real.http()
    assert login(http, player["name"], player["password"]).status_code == 303
    assert choose(http, REAL_STORY).status_code == 303
    return http


def _server_of(real: Any) -> str:
    """Which server the instance's children run under, from the supervisor's log."""
    started = [line for line in real.lines if f"Started worker-{REAL_STORY} (operation=spawn" in line]
    assert started, "no spawn line"
    return "gunicorn" if "-m gunicorn -c " in started[-1] else "werkzeug"


@pytest.mark.process
def test_real_a_browser_shaped_websocket_turn_through_the_front_door(real: Any, real_player: dict[str, str]) -> None:
    from engine.hosting.supervisor.process import gunicorn_runs_here

    assert _server_of(real) == ("gunicorn" if gunicorn_runs_here() else "werkzeug")
    assert any("Started frontdoor (operation=spawn" in line for line in real.lines)
    http = _real_client(real, real_player)
    try:
        played = _ws_turn(http, real.base)
    finally:
        http.close()
    assert _names(played["joined"]) == ["game_started"]
    assert "turn_update" in _names(played["turn"])
    assert "Mist clings to the birch trunks." in _update(played["turn"])["args"][0]["narration"]


@pytest.mark.process
def test_real_a_refused_upgrade_never_lets_the_client_speak_http_to_the_worker(
    real: Any, real_player: dict[str, str]
) -> None:
    from engine.hosting.frontdoor.ws_relay import WORKER_REFUSED

    http = _real_client(real, real_player)
    own = f"127.0.0.1:{real.frontdoor_port}"
    before = len(real.proxied(f"worker-{REAL_STORY}"))
    sock = None
    try:
        status, found, body, sock = upgrade(
            real.frontdoor_port,
            "/socket.io/?EIO=4&transport=websocket&sid=not-a-session",
            [("Cookie", cookie_header(http)), ("Origin", f"http://{own}")],
        )
        assert status == 502 and json.loads(body) == WORKER_REFUSED
        assert "sec-websocket-accept" not in found
        how = _next_request_is_the_front_door_s(sock, found, own)
    finally:
        if sock is not None:
            sock.close()
        http.close()
    if _server_of(real) == "gunicorn":
        assert how == "kept alive", "gunicorn closed a connection it keeps alive"
    reached = real.proxied(f"worker-{REAL_STORY}")[before:]
    assert reached == ["GET /socket.io/"], reached


@pytest.mark.process
def test_real_websockets_past_the_long_holds_are_refused_and_login_is_served(
    real: Any, real_player: dict[str, str]
) -> None:
    """
    ``threads: RESERVED_THREADS + 2``: under gunicorn the front door's pool
    has six threads, two of which open WebSockets pin. The third upgrade is
    refused at once (503) and the login page, the picker and the stylesheet
    are served from the four kept for HTTP.
    """
    from engine.hosting.limits import SERVER_FULL

    http = _real_client(real, real_player)
    sockets: list[Any] = []
    try:
        for _ in range(2):
            ws = WebSocketClient(http, real.base)
            sockets.append(ws)
            ws.handshake()
        status, _found, body, sock = upgrade(
            real.frontdoor_port,
            "/socket.io/?EIO=4&transport=websocket",
            [("Cookie", cookie_header(http)), ("Origin", real.base)],
        )
        sock.close()
        assert status == 503 and json.loads(body) == {"error": SERVER_FULL}
        fresh = real.http()
        try:
            assert fresh.get("/login", timeout=10).status_code == 200
        finally:
            fresh.close()
        assert http.get("/stories", timeout=10).status_code == 200
        assert http.get("/static/hosting/hosting.css", timeout=10).status_code == 200
    finally:
        for ws in sockets:
            ws.close()
        http.close()
    # Both places come back: a new socket is let in.
    http = _real_client(real, real_player)
    try:

        def one_more() -> bool:
            ws = WebSocketClient(http, real.base)
            try:
                ws.handshake()
                return True
            except Exception:  # noqa: BLE001 -- refused while a place is still held
                return False
            finally:
                ws.close()

        _wait(one_more, 15, "a closed socket gave its long hold back")
    finally:
        http.close()


@pytest.mark.process
def test_real_a_worker_takes_no_scheme_from_a_header_without_the_proxy_token(real: Any) -> None:
    """
    Fix round 1, I2: a request reaching a worker WITHOUT the proxy token
    gets no forwarded header trusted -- not by the engine (spec §7.3), and
    not by gunicorn, whose default trusts ``X-Forwarded-Proto`` from any
    loopback peer and would set the scheme before the engine's layers run.
    So claiming https through the header does not make an https Origin
    same-origin at the worker's Socket.IO; the plain http one is.
    """
    port = int(real.row(f"worker-{REAL_STORY}")["port"])
    own = f"127.0.0.1:{port}"
    with httpx.Client(trust_env=False, timeout=10) as http:
        claimed = http.get(
            f"http://{own}/socket.io/?EIO=4&transport=polling",
            headers={"Origin": f"https://{own}", "X-Forwarded-Proto": "https"},
        )
        plain = http.get(f"http://{own}/socket.io/?EIO=4&transport=polling", headers={"Origin": f"http://{own}"})
    assert claimed.status_code in (400, 403), (claimed.status_code, claimed.text[:200])
    assert plain.status_code == 200, (plain.status_code, plain.text[:200])


def _trickle(port: int, path: str, cookie: str, content_type: str, stop: threading.Event) -> tuple[Any, threading.Thread]:
    """A raw socket sending a turn's headers, then its 1000-byte body ONE byte every 0.4 s."""
    import socket

    sock = socket.create_connection(("127.0.0.1", port), timeout=JOIN)
    sock.sendall(
        (
            f"POST {path} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n"
            f"Cookie: clockwork_session={cookie}\r\nContent-Type: {content_type}\r\n"
            "Content-Length: 1000\r\n\r\n"
        ).encode("ascii")
    )

    def drip() -> None:
        for _ in range(1000):
            if stop.wait(0.4):
                return
            try:
                sock.sendall(b"x")
            except OSError:
                return

    thread = threading.Thread(target=drip, name="trickle")
    thread.start()
    return sock, thread


@pytest.mark.parametrize("where", ["front door", "worker"])
@pytest.mark.process
def test_real_a_trickled_body_is_cut_at_the_deadline(real: Any, real_player: dict[str, str], where: str) -> None:
    """
    The body-read deadline under each server (``hosting.body_read_seconds``,
    3 s here): a body arriving one byte every 0.4 s -- each byte well inside
    any per-read timeout -- is answered 408 within the deadline and a margin,
    at the front door (a choice) and at the worker (a voice upload). Under
    gunicorn, whose input has no ``read1``, one read used to run until the
    whole body came (400 s).
    """
    import time

    http = _real_client(real, real_player)
    cookie = str(http.cookies.get("clockwork_session"))
    if where == "front door":
        port, path, kind = real.frontdoor_port, "/api/game/choice", "application/json"
    else:
        port, path, kind = (
            int(real.row(f"worker-{REAL_STORY}")["port"]),
            "/api/voice/transcribe",
            "multipart/form-data; boundary=x",
        )
    stop = threading.Event()
    sock, thread = None, None
    began = time.monotonic()
    try:
        sock, thread = _trickle(port, path, cookie, kind, stop)
        status = _status_of(sock)
        took = time.monotonic() - began
    finally:
        stop.set()
        if thread is not None:
            thread.join(10)
        if sock is not None:
            sock.close()
        http.close()
    assert thread is not None and not thread.is_alive()
    assert status.startswith(b"HTTP/1.1 408"), status
    assert took < 3 + 4, f"answered after {took:.1f}s against a 3s deadline"


# -- v0.20.0 T13 fix round 1 -----------------------------------------------------------------


def _joined_socket(door: InProcessFrontDoor, http: httpx.Client) -> WebSocketClient:
    """A relayed WebSocket that has connected and joined a new run, then sits idle."""
    run = http.post("/api/game/new", json={"seed": 7}).json()
    ws = WebSocketClient(http, door.base)
    ws.handshake()
    assert ws.connect()["type"] == "connect"
    ws.emit("join_session", {"session_id": run["session_id"]})
    ws.until(lambda e: e.get("name") in ("game_started", "error"))
    return ws


def _closed_within(ws: WebSocketClient, seconds: float) -> bool:
    import time

    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if any(e["type"] == "close" for e in ws.poll(timeout=0.2)):
            return True
    return False


@pytest.mark.parametrize("how", ["disable", "password", "remove"])
def test_a_login_ended_at_the_front_door_closes_its_relayed_socket_at_once(
    door: InProcessFrontDoor, how: str
) -> None:
    """
    I1: the /account page is the FRONT DOOR's, so a change made there must
    reach a relayed socket that only listens -- the worker's own listener
    never hears it. On 930cd50 such a socket stayed open (and kept its long
    hold) for as long as the tab did.
    """
    from engine.hosting.auth import hosting_state
    from engine.hosting.frontdoor import frontdoor
    from tests.hosted_app import new_password

    state = frontdoor(door.front_app)
    http = door.logged_in("rowan")
    ws = _joined_socket(door, http)
    try:
        accounts = hosting_state(door.front_app).accounts
        if how == "disable":
            accounts.disable("rowan")
        elif how == "password":
            accounts.set_password("rowan", new_password())
        else:
            accounts.remove("rowan")
        assert _closed_within(ws, 2.0), "the relayed socket stayed open after its login ended"
        assert ws.ws is not None and ws.ws.close_reason == 1008
    finally:
        ws.close()
        http.close()
    _wait(lambda: state.relay.active == 0 and state.holds.inside == 0, what="the relay and its hold freed")


def test_a_login_ended_by_another_process_closes_its_relayed_socket(
    door: InProcessFrontDoor, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    I1, the other half: a change made by ANOTHER process (``scripts/users.py``,
    played here by a second store on the same users.json, whose listeners
    the front door never hears) closes the socket at the relay's next
    re-check (``ACCOUNT_RECHECK_SECONDS``, shortened here).
    """
    import engine.hosting.frontdoor.ws_relay as relay_module
    from engine.hosting.accounts import AccountStore
    from engine.hosting.auth import hosting_state
    from tests.hosted_app import new_password

    monkeypatch.setattr(relay_module, "ACCOUNT_RECHECK_SECONDS", 0.5)
    http = door.logged_in("rowan")
    ws = _joined_socket(door, http)
    try:
        other = AccountStore(hosting_state(door.front_app).accounts.directory)
        other.set_password("rowan", new_password())
        assert _closed_within(ws, 4.0), "the relayed socket stayed open after another process ended its login"
        assert ws.ws is not None and ws.ws.close_reason == 1008
    finally:
        ws.close()
        http.close()


def test_one_account_cannot_take_every_open_connection(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """
    I4, the review's scenario: with plenty of long holds, one account opens
    connections until its cap (``max_connections_per_account: 2``): its next
    WebSocket and its next poll are refused 429, while another account's
    WebSocket is let in. A closed socket gives the account its place back.
    """
    from engine.hosting.frontdoor import frontdoor
    from engine.hosting.limits import too_many_connections

    door = InProcessFrontDoor(
        monkeypatch,
        tmp_path,
        hosting={"max_connections_per_account": 2, "rate_limits": {"actions_per_minute": 1000}},
    )
    door.start()
    sockets: list[Any] = []
    try:
        alice = door.logged_in("alice")
        bob = door.logged_in("bob")
        for _ in range(2):
            ws = WebSocketClient(alice, door.base)
            sockets.append(ws)
            ws.handshake()
        status, _found, body, sock = upgrade(
            door.front_port,
            "/socket.io/?EIO=4&transport=websocket",
            [("Cookie", cookie_header(alice)), ("Origin", door.base)],
        )
        sock.close()
        assert status == 429 and json.loads(body) == {"error": too_many_connections(2)}
        polled = alice.get("/socket.io/?EIO=4&transport=polling")
        assert polled.status_code == 429
        other = WebSocketClient(bob, door.base)
        sockets.append(other)
        other.handshake()
        assert frontdoor(door.front_app).holds.of_account(str(door.hosted.state.accounts.by_name("alice").id)) == 2
        sockets.pop(0).close()
        _wait(lambda: _upgrade_status(door, alice) == 101, what="alice's place came back")
        alice.close()
        bob.close()
    finally:
        for ws in sockets:
            ws.close()
        door.stop()


def test_the_page_s_probe_says_the_account_is_at_its_connection_cap(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """
    v0.21.0 T11 fix round 1: a WebSocket refused at the cap is an HTTP 429 the
    browser cannot read, so the game page's auth probe (``GET
    /api/games/active``, ``ui/src/core/link.js``) is answered 429 with the
    cap's words while the account holds its cap, and is forwarded as before
    for another account, and for this one once a connection closes.
    """
    from engine.hosting.limits import too_many_connections

    door = InProcessFrontDoor(
        monkeypatch,
        tmp_path,
        hosting={"max_connections_per_account": 2, "rate_limits": {"actions_per_minute": 1000}},
    )
    door.start()
    sockets: list[Any] = []
    try:
        alice = door.logged_in("alice")
        bob = door.logged_in("bob")
        assert alice.get("/api/games/active").status_code == 200
        for _ in range(2):
            ws = WebSocketClient(alice, door.base)
            sockets.append(ws)
            ws.handshake()
        probed = alice.get("/api/games/active")
        assert probed.status_code == 429
        assert probed.json() == {"error": too_many_connections(2)}
        assert bob.get("/api/games/active").status_code == 200
        # Only the probe: another route of the same account is forwarded.
        assert alice.get("/api/games").status_code == 200
        sockets.pop(0).close()
        _wait(lambda: alice.get("/api/games/active").status_code == 200, what="the probe answers again")
        alice.close()
        bob.close()
    finally:
        for ws in sockets:
            ws.close()
        door.stop()


def _upgrade_status(door: InProcessFrontDoor, http: httpx.Client) -> int:
    status, _found, _body, sock = upgrade(
        door.front_port,
        "/socket.io/?EIO=4&transport=websocket",
        [("Cookie", cookie_header(http)), ("Origin", door.base)],
    )
    sock.close()
    return status


def test_a_worker_refuses_one_account_s_connect_past_the_cap(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """I4 at the worker: a third Socket.IO connect of one account is refused there too."""
    door = InProcessFrontDoor(
        monkeypatch,
        tmp_path,
        hosting={"max_connections_per_account": 2, "rate_limits": {"actions_per_minute": 1000}},
    )
    door.start()
    polls: list[PollingClient] = []
    try:
        login_client = door.logged_in("alice")
        direct = door.http(door.worker_base)
        direct.cookies = login_client.cookies
        from engine.hosting.limits import too_many_connections

        answers = []
        for _ in range(3):
            poll = PollingClient(direct, door.worker_base)
            polls.append(poll)
            poll.handshake()
            answers.append(poll.connect())
        assert [a["type"] for a in answers] == ["connect", "connect", "connect_error"], answers
        # T13 re-review N4: an engine-authored refusal the client shows
        # (its connect_error's message), not a generic connect failure.
        assert answers[2]["data"] == {"message": too_many_connections(2)}
        polls.pop().close()
        login_client.close()
    finally:
        for poll in polls:
            poll.close()
        door.stop()


def test_a_worker_s_message_past_the_inbound_cap_still_reaches_the_client(
    door: InProcessFrontDoor, echo: _EchoWorker
) -> None:
    """M2: the 64 KiB cap bounds what a worker ACCEPTS; a 100 KB message from it is relayed."""
    http = door.logged_in("rowan")
    ws = _socket(door, http)
    try:
        ws.send("big")
        got = ws.receive(timeout=10)
    finally:
        ws.close()
        http.close()
    assert got == "y" * 100_000


def test_a_client_that_stops_reading_is_cut_and_the_relay_ends(
    door: InProcessFrontDoor, echo: _EchoWorker, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    M1: a client completes the upgrade, asks for a flood and then never
    reads. The relay's send blocks once the socket's buffers fill; past
    ``SEND_STALL_SECONDS`` (shortened here) the link is cut: the relay thread
    ends, the hold comes back and the worker's side is closed. On 930cd50
    nothing ended it while the client stayed connected.
    """
    import base64

    import engine.hosting.frontdoor.ws_relay as relay_module
    from engine.hosting.frontdoor import frontdoor

    monkeypatch.setattr(relay_module, "SEND_STALL_SECONDS", 1.0)
    # The relay's join after the cut (10 s, then an abort and 10 s more) is
    # shortened too: the claim is that the link ends, not how long the
    # handler waits on its relay thread (v0.21.1 T1 fix round 1: 22 s -> ~5 s).
    monkeypatch.setattr(relay_module, "RELAY_JOIN_SECONDS", 1.0)
    state = frontdoor(door.front_app)
    http = door.logged_in("rowan")
    status, _found, _body, sock = upgrade(
        door.front_port,
        "/socket.io/?EIO=4&transport=websocket",
        [("Cookie", cookie_header(http)), ("Origin", door.base)],
        key=base64.b64encode(b"0123456789abcdef").decode("ascii"),
    )
    try:
        assert status == 101
        # One masked text frame, "flood" (RFC 6455 §5.2), written by hand.
        mask = b"\x01\x02\x03\x04"
        payload = bytes(b ^ mask[i % 4] for i, b in enumerate(b"flood"))
        sock.sendall(bytes([0x81, 0x80 | len(payload)]) + mask + payload)
        # ... and never read again.
        assert echo.closed.wait(60), "the worker's side was never closed"
        _wait(
            lambda: state.relay.active == 0 and not _relay_threads() and state.holds.inside == 0,
            30,
            "the stalled relay ended and gave its hold back",
        )
    finally:
        sock.close()
        http.close()


def test_ending_a_login_returns_at_once_with_a_stuck_client_connected(
    door: InProcessFrontDoor, echo: _EchoWorker, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    v0.20.0 T14 (from T13 fix round 1): a disable, a reset or a removal --
    the admin panel's, or the /account page's -- tells the front door's relay
    to close that account's sockets. The close used to run on the CALLER's
    thread, and its close frame blocked on a client that had stopped reading
    (until the 30 s stall check), holding the admin's request. Now the relay's
    own thread closes it: the change returns at once, and the stuck link is
    cut all the same.
    """
    import base64
    import time

    import engine.hosting.frontdoor.ws_relay as relay_module
    from engine.hosting.auth import hosting_state
    from engine.hosting.frontdoor import frontdoor

    # The relay's join after the cut, shortened as in the test above: the
    # claim is that the disable returns at once and the link is cut.
    monkeypatch.setattr(relay_module, "RELAY_JOIN_SECONDS", 1.0)
    state = frontdoor(door.front_app)
    http = door.logged_in("rowan")
    status, _found, _body, sock = upgrade(
        door.front_port,
        "/socket.io/?EIO=4&transport=websocket",
        [("Cookie", cookie_header(http)), ("Origin", door.base)],
        key=base64.b64encode(b"0123456789abcdef").decode("ascii"),
    )
    try:
        assert status == 101
        mask = b"\x01\x02\x03\x04"
        payload = bytes(b ^ mask[i % 4] for i, b in enumerate(b"flood"))
        sock.sendall(bytes([0x81, 0x80 | len(payload)]) + mask + payload)

        def stuck() -> bool:
            links = [link for found in state.relay._links.values() for link in found]
            return bool(links) and all(
                link.sending_since and time.monotonic() - link.sending_since > 0.5 for link in links
            )

        _wait(stuck, 30, "the relay stuck in a send to the client that stopped reading")
        accounts = hosting_state(door.front_app).accounts
        began = time.monotonic()
        accounts.disable("rowan")
        took = time.monotonic() - began
        assert took < 2.0, f"disabling the account waited {took:.1f}s on a stuck client"
        _wait(
            lambda: state.relay.active == 0 and not _relay_threads() and state.holds.inside == 0,
            30,
            "the revoked, stuck link was cut",
        )
    finally:
        sock.close()
        http.close()


def test_a_trickled_body_on_any_route_is_cut_at_the_front_door(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """
    M3: every proxied body is read whole within ``body_read_seconds`` (1
    here), not only a turn's: a save trickled a byte at a time is answered
    408 at the front door. On 930cd50 it was streamed to the worker and held
    a thread for as long as the bytes kept coming.
    """
    import time

    door = InProcessFrontDoor(
        monkeypatch,
        tmp_path,
        hosting={"body_read_seconds": 1, "rate_limits": {"actions_per_minute": 1000}},
    )
    door.start()
    stop = threading.Event()
    sock, thread = None, None
    try:
        http = door.logged_in("rowan")
        cookie = str(http.cookies.get("clockwork_session"))
        began = time.monotonic()
        sock, thread = _trickle(door.front_port, "/api/saves", cookie, "application/json", stop)
        status = _status_of(sock)
        took = time.monotonic() - began
        assert status.startswith(b"HTTP/1.1 408"), status
        assert took < 1 + 4, f"answered after {took:.1f}s"
        http.close()
    finally:
        stop.set()
        if thread is not None:
            thread.join(10)
        if sock is not None:
            sock.close()
        door.stop()
