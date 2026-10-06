"""
Engine.IO v4 / Socket.IO v5 over long polling, spoken with ``httpx`` (v0.20.0
T12): a test helper, not a test. No new dependency -- the framing is small:

- the HANDSHAKE is ``GET /socket.io/?EIO=4&transport=polling``, answered with
  an Engine.IO ``open`` packet (``0{"sid": ..., "pingInterval": ...}``);
- a PAYLOAD (either way) is Engine.IO packets joined by ``\\x1e``; each packet
  is its type digit and its data (``2`` ping, ``3`` pong, ``4`` message,
  ``1`` close, ``6`` noop);
- a MESSAGE carries a Socket.IO packet: ``0`` connect (``40`` on ``/``, its
  answer ``40{"sid": ...}``), ``2`` event (``42["name", payload]``), ``4``
  connect error (``44{...}``), ``1`` disconnect;
- the client sends with ``POST ...&sid=<sid>`` (answered ``ok``) and
  receives with ``GET ...&sid=<sid>``, which the server holds open until it
  has something (or the ping interval runs out: then it sends a ping, which
  this client answers with a pong).

``PollingClient(http, base)`` wraps an ``httpx.Client`` (its cookies are the
login) and a base URL (the front door's, or a worker's directly).

THE WEBSOCKET HALF (v0.20.0 T13). ``WebSocketClient(http, base)`` speaks the
same Engine.IO session over ``transport=websocket`` the way the browser's
socket.io-client does (it connects straight to WebSocket, never polling
first): one packet per WebSocket message, the server's ``2`` ping answered
``3``. It sends the login cookie from the ``httpx`` client's jar and, like a
browser, an ``Origin`` (the base URL's own, unless ``origin`` says
otherwise; ``origin=None`` sends none). Its WebSocket is ``TestWebSocket``,
simple-websocket's client with a bounded handshake (the stock one waits for
ever on a server that says nothing), so a test fails rather than hangs.
``upgrade(port, target, headers)`` sends one raw upgrade request on a plain
socket and reads the HTTP answer, for the refusals, and leaves the socket
open for whatever a test sends next.

Version: v0.2.0 [2026-10-05]
"""

from __future__ import annotations

import json
import socket
import time
from typing import Any, Callable, Optional

import httpx
import simple_websocket
from simple_websocket.ws import Base as WebSocketBase
from wsproto import ConnectionType
from wsproto.events import AcceptConnection, RejectConnection, Request

#: Engine.IO's record separator between packets in one polling payload.
SEPARATOR = "\x1e"

#: Engine.IO packet types.
OPEN, CLOSE, PING, PONG, MESSAGE, UPGRADE, NOOP = "0", "1", "2", "3", "4", "5", "6"

#: Socket.IO packet types (inside a MESSAGE).
SIO_CONNECT, SIO_DISCONNECT, SIO_EVENT, SIO_ACK, SIO_CONNECT_ERROR = "0", "1", "2", "3", "4"


class EngineIOError(AssertionError):
    """The server answered something this client did not expect."""


def decode_payload(text: str) -> list[str]:
    """A polling payload's packets."""
    return [packet for packet in text.split(SEPARATOR) if packet]


def encode_payload(packets: list[str]) -> str:
    return SEPARATOR.join(packets)


def parse_event(packet: str) -> Optional[dict[str, Any]]:
    """
    A Socket.IO message packet (``4...``) as ``{"type", "name", "args",
    "data"}``; None for an Engine.IO control packet.
    """
    if not packet or packet[0] != MESSAGE:
        return None
    body = packet[1:]
    kind, rest = body[:1], body[1:]
    namespace = "/"
    if rest.startswith("/"):
        namespace, _, rest = rest.partition(",")
    if kind == SIO_EVENT:
        while rest and rest[0].isdigit():  # an ack id
            rest = rest[1:]
        items = json.loads(rest)
        return {"type": "event", "namespace": namespace, "name": items[0], "args": items[1:]}
    if kind == SIO_CONNECT:
        return {"type": "connect", "namespace": namespace, "data": json.loads(rest) if rest else {}}
    if kind == SIO_CONNECT_ERROR:
        return {"type": "connect_error", "namespace": namespace, "data": json.loads(rest) if rest else {}}
    if kind == SIO_DISCONNECT:
        return {"type": "disconnect", "namespace": namespace}
    if kind == SIO_ACK:
        digits = ""
        while rest and rest[0].isdigit():
            digits, rest = digits + rest[0], rest[1:]
        return {"type": "ack", "namespace": namespace, "id": int(digits or 0), "args": json.loads(rest) if rest else []}
    return {"type": kind, "namespace": namespace, "raw": rest}


class PollingClient:
    """One Engine.IO session over long polling (see the module docstring)."""

    def __init__(
        self,
        http: httpx.Client,
        base: str,
        *,
        path: str = "/socket.io/",
        headers: Optional[dict[str, str]] = None,
        timeout: float = 30.0,
    ) -> None:
        self.http = http
        self.base = base.rstrip("/")
        self.path = path
        self.headers = dict(headers or {})
        self.timeout = timeout
        self.sid = ""
        self.open: dict[str, Any] = {}
        #: Every event received, in order (``parse_event`` rows).
        self.received: list[dict[str, Any]] = []
        self._acks = 0

    def _url(self, **query: str) -> str:
        params = {"EIO": "4", "transport": "polling", **query}
        if self.sid:
            params["sid"] = self.sid
        params["t"] = f"{time.monotonic_ns():x}"
        return f"{self.base}{self.path}?" + "&".join(f"{k}={v}" for k, v in params.items())

    def handshake_response(self) -> httpx.Response:
        """The raw handshake (for tests of a refusal)."""
        return self.http.get(self._url(), headers=self.headers, timeout=self.timeout)

    def handshake(self) -> dict[str, Any]:
        """Open the Engine.IO session; its ``open`` packet's data."""
        response = self.handshake_response()
        if response.status_code != 200:
            raise EngineIOError(f"handshake refused: HTTP {response.status_code} {response.text[:200]!r}")
        packets = decode_payload(response.text)
        if not packets or packets[0][0] != OPEN:
            raise EngineIOError(f"no open packet: {response.text[:200]!r}")
        self.open = json.loads(packets[0][1:])
        self.sid = str(self.open["sid"])
        return self.open

    def send(self, *packets: str) -> None:
        response = self.http.post(
            self._url(),
            content=encode_payload(list(packets)).encode("utf-8"),
            headers={"Content-Type": "text/plain;charset=UTF-8", **self.headers},
            timeout=self.timeout,
        )
        if response.status_code != 200 or response.text.lower() != "ok":
            raise EngineIOError(f"send refused: HTTP {response.status_code} {response.text[:200]!r}")

    def poll(self) -> list[dict[str, Any]]:
        """One long-poll ``GET``: the events it brought (a ping is answered)."""
        response = self.http.get(self._url(), headers=self.headers, timeout=self.timeout + 60)
        if response.status_code != 200:
            raise EngineIOError(f"poll refused: HTTP {response.status_code} {response.text[:200]!r}")
        events: list[dict[str, Any]] = []
        for packet in decode_payload(response.text):
            if packet[0] == PING:
                self.send(PONG)
                continue
            if packet[0] == CLOSE:
                events.append({"type": "close"})
                continue
            event = parse_event(packet)
            if event is not None:
                events.append(event)
        self.received.extend(events)
        return events

    def connect(self, namespace: str = "/") -> dict[str, Any]:
        """Socket.IO ``connect`` on ``namespace``: its answer (``connect`` or ``connect_error``)."""
        prefix = "" if namespace == "/" else f"{namespace},"
        self.send(MESSAGE + SIO_CONNECT + prefix)
        return self.until(lambda e: e["type"] in ("connect", "connect_error"))

    def emit(self, event: str, *args: Any, ack: bool = False) -> Optional[int]:
        """
        Send ``event``. ``ack``: ask for an acknowledgement, which the server
        sends once the handler has returned (after anything it emitted);
        the ack's id is returned, for ``until`` to wait on.
        """
        number = ""
        if ack:
            self._acks += 1
            number = str(self._acks)
        self.send(MESSAGE + SIO_EVENT + number + json.dumps([event, *args], separators=(",", ":")))
        return self._acks if ack else None

    def acked(self, ids: set[int]) -> set[int]:
        """Which of ``ids`` have been acknowledged so far."""
        return {e["id"] for e in self.received if e["type"] == "ack"} & set(ids)

    def until(self, done: Callable[[dict[str, Any]], bool], timeout: Optional[float] = None) -> dict[str, Any]:
        """Poll until an event satisfies ``done``; that event."""
        deadline = time.monotonic() + (timeout if timeout is not None else self.timeout)
        start = len(self.received)
        while True:
            for event in self.received[start:]:
                if done(event):
                    return event
            start = len(self.received)
            if time.monotonic() > deadline:
                raise EngineIOError(f"no matching event within the timeout; got {self.received[-10:]!r}")
            self.poll()

    def close(self) -> None:
        if not self.sid:
            return
        try:
            self.send(CLOSE)
        except (EngineIOError, httpx.HTTPError):
            pass
        self.sid = ""


# -- the WebSocket half (v0.20.0 T13) ---------------------------------------------------


class TestWebSocket(simple_websocket.Client):
    """simple-websocket's client with a bounded connect and handshake (see the module docstring)."""

    __test__ = False  # not a pytest class

    def __init__(self, url: str, *, headers: list[tuple[str, str]], timeout: float = 10.0) -> None:
        from urllib.parse import urlsplit

        parts = urlsplit(url)
        self.host = parts.hostname or "127.0.0.1"
        self.port = int(parts.port or 80)
        self.path = parts.path + (f"?{parts.query}" if parts.query else "")
        self.subprotocols: list[str] = []
        self.extra_headeers = headers  # (sic) simple-websocket's attribute
        self._timeout = timeout
        sock = socket.create_connection((self.host, self.port), timeout=timeout)
        try:
            WebSocketBase.__init__(self, sock, connection_type=ConnectionType.CLIENT)
        except BaseException:
            sock.close()
            raise

    def handshake(self) -> None:
        self.sock.settimeout(self._timeout)
        self.sock.sendall(
            self.ws.send(
                Request(host=f"{self.host}:{self.port}", target=self.path, extra_headers=self.extra_headeers)
            )
        )
        event: Any = None
        while event is None:
            data = self.sock.recv(self.receive_bytes)
            if not data:
                raise simple_websocket.ConnectionError(None)
            self.ws.receive_data(data)
            event = next(self.ws.events(), None)
        if isinstance(event, RejectConnection):
            raise simple_websocket.ConnectionError(event.status_code)
        if not isinstance(event, AcceptConnection):
            raise simple_websocket.ConnectionError(400)
        self.sock.settimeout(None)
        self.connected = True
        self.connected = self._handle_events()


def cookie_header(http: httpx.Client) -> str:
    """The ``Cookie`` header an ``httpx`` client's jar would send."""
    return "; ".join(f"{name}={value}" for name, value in http.cookies.items())


class WebSocketClient:
    """One Engine.IO session over WebSocket (see the module docstring)."""

    def __init__(
        self,
        http: httpx.Client,
        base: str,
        *,
        path: str = "/socket.io/",
        origin: Optional[str] = "",
        headers: Optional[dict[str, str]] = None,
        query: str = "",
        timeout: float = 30.0,
    ) -> None:
        from urllib.parse import urlsplit

        self.http = http
        self.base = base.rstrip("/")
        parts = urlsplit(self.base)
        self.port = int(parts.port or 80)
        self.path = path
        self.origin = f"{parts.scheme}://{parts.netloc}" if origin == "" else origin
        self.headers = dict(headers or {})
        self.query = query
        self.timeout = timeout
        self.ws: Optional[TestWebSocket] = None
        self.open: dict[str, Any] = {}
        self.sid = ""
        #: Every event received, in order (``parse_event`` rows).
        self.received: list[dict[str, Any]] = []
        self._acks = 0

    def header_list(self) -> list[tuple[str, str]]:
        found: list[tuple[str, str]] = []
        cookies = cookie_header(self.http)
        if cookies:
            found.append(("Cookie", cookies))
        if self.origin is not None:
            found.append(("Origin", self.origin))
        found += list(self.headers.items())
        return found

    def target(self) -> str:
        return f"{self.path}?EIO=4&transport=websocket" + (f"&{self.query}" if self.query else "")

    def handshake(self) -> dict[str, Any]:
        """Upgrade, then read the server's ``open`` packet."""
        self.ws = TestWebSocket(
            f"ws://127.0.0.1:{self.port}{self.target()}", headers=self.header_list(), timeout=self.timeout
        )
        first = self.ws.receive(timeout=self.timeout)
        if not isinstance(first, str) or not first.startswith(OPEN):
            raise EngineIOError(f"no open packet over the WebSocket: {first!r}")
        self.open = json.loads(first[1:])
        self.sid = str(self.open["sid"])
        return self.open

    def send(self, packet: Any) -> None:
        assert self.ws is not None
        self.ws.send(packet)

    def poll(self, timeout: float = 1.0) -> list[dict[str, Any]]:
        """Whatever arrives within ``timeout`` (a ping is answered); [] on a quiet line."""
        assert self.ws is not None
        events: list[dict[str, Any]] = []
        try:
            packet = self.ws.receive(timeout=timeout)
        except simple_websocket.ConnectionClosed:
            events.append({"type": "close"})
            self.received.extend(events)
            return events
        if packet is None:
            return events
        if isinstance(packet, bytes):
            events.append({"type": "binary", "data": packet})
        elif packet[:1] == PING:
            self.send(PONG + packet[1:])
        elif packet[:1] == CLOSE:
            events.append({"type": "close"})
        else:
            event = parse_event(packet)
            if event is not None:
                events.append(event)
        self.received.extend(events)
        return events

    def connect(self, namespace: str = "/") -> dict[str, Any]:
        prefix = "" if namespace == "/" else f"{namespace},"
        self.send(MESSAGE + SIO_CONNECT + prefix)
        return self.until(lambda e: e["type"] in ("connect", "connect_error", "close"))

    def emit(self, event: str, *args: Any, ack: bool = False) -> Optional[int]:
        number = ""
        if ack:
            self._acks += 1
            number = str(self._acks)
        self.send(MESSAGE + SIO_EVENT + number + json.dumps([event, *args], separators=(",", ":")))
        return self._acks if ack else None

    def until(self, done: Callable[[dict[str, Any]], bool], timeout: Optional[float] = None) -> dict[str, Any]:
        deadline = time.monotonic() + (timeout if timeout is not None else self.timeout)
        start = len(self.received)
        while True:
            for event in self.received[start:]:
                if done(event):
                    return event
            start = len(self.received)
            if time.monotonic() > deadline:
                raise EngineIOError(f"no matching event within the timeout; got {self.received[-10:]!r}")
            self.poll()

    def close(self) -> None:
        if self.ws is not None and self.ws.connected:
            try:
                self.ws.close()
            except (simple_websocket.ConnectionClosed, OSError):
                pass


def upgrade(
    port: int,
    target: str,
    headers: list[tuple[str, str]],
    *,
    host: str = "",
    timeout: float = 10.0,
    key: str = "dGhlIHNhbXBsZSBub25jZQ==",
) -> tuple[int, dict[str, str], bytes, socket.socket]:
    """
    One raw WebSocket upgrade request on a fresh socket: the answer's status,
    headers (lower-cased names) and body (by ``Content-Length``), and the
    socket, still open, for the caller to send more on (and close).
    """
    sock = socket.create_connection(("127.0.0.1", port), timeout=timeout)
    lines = [
        f"GET {target} HTTP/1.1",
        f"Host: {host or f'127.0.0.1:{port}'}",
        "Upgrade: websocket",
        "Connection: Upgrade",
        f"Sec-WebSocket-Key: {key}",
        "Sec-WebSocket-Version: 13",
        *[f"{k}: {v}" for k, v in headers],
    ]
    sock.sendall(("\r\n".join(lines) + "\r\n\r\n").encode("latin-1"))
    status, found, body = read_response(sock)
    return status, found, body, sock


def read_response(sock: socket.socket) -> tuple[int, dict[str, str], bytes]:
    """One HTTP response off ``sock``: status, headers, body (by ``Content-Length``; none on a 101)."""
    data = b""
    while b"\r\n\r\n" not in data:
        chunk = sock.recv(4096)
        if not chunk:
            raise EngineIOError(f"the connection closed before a whole answer: {data[:200]!r}")
        data += chunk
    head, _, rest = data.partition(b"\r\n\r\n")
    first, *header_lines = head.decode("latin-1").split("\r\n")
    status = int(first.split(" ", 2)[1])
    found = {}
    for line in header_lines:
        name, _, value = line.partition(":")
        found[name.strip().lower()] = value.strip()
    length = int(found.get("content-length", "0") or 0) if status != 101 else 0
    while len(rest) < length:
        chunk = sock.recv(4096)
        if not chunk:
            break
        rest += chunk
    return status, found, rest[:length]


__all__ = [
    "EngineIOError",
    "PollingClient",
    "TestWebSocket",
    "WebSocketClient",
    "cookie_header",
    "decode_payload",
    "encode_payload",
    "parse_event",
    "read_response",
    "upgrade",
]
