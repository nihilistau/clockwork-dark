"""
The Front Door: the WebSocket Relay
===================================

The client is WebSocket-first and does not fall back to polling (spec §12),
so this is every player's path to a story (spec §14.5). WSGI middleware
INSIDE the front door's ``ForwardedHeaders`` (its ``ProxyFix``) and the host
guard, OUTSIDE Flask (spec §7.3's order): no ``before_request`` reaches it,
so it calls the HTTP gate's own check, ``gate.authenticate``.

On a ``/socket.io/`` request asking ``Upgrade: websocket``, in order:

1. the client's handshake headers (``handshake_ok``: else 400, before
   anything else costs a worker a session); ``authenticate(environ)``: a
   live account (else 401), a story chosen
   (else 409, as the HTTP door answers it) and routable (else 503); then the
   ``Origin``, when the browser sent one, against the RESOLVED scheme and
   Host -- after ``ProxyFix``, never a raw ``X-Forwarded-Host`` -- or
   ``hosting.public_origin`` (else 403); then a place among the front door's
   long holds (``limits.LongHolds``, else 503 ``SERVER_FULL``), at most
   ``hosting.max_connections_per_account`` of them one account's (else 429;
   fix round 1, I4). Each refusal
   is a plain HTTP answer and nothing reaches the worker;
2. a WebSocket CLIENT to the worker (``WorkerSocket``, simple-websocket's
   client with a bounded handshake), ``ws://127.0.0.1:<port>`` with the same
   path and query, carrying the cookie, the client's ``Origin`` and
   ``User-Agent``, ``X-Forwarded-For``/``-Proto``/``-Host`` REPLACED with
   what this front door resolved, and the proxy token. The worker's engineio
   does its own handshake and Origin check, and its socket guard
   authenticates ``connect`` as ever. A worker that refuses the upgrade (a
   bad ``sid``, a refused Origin) or cannot be reached gives the client a
   plain 502, never an upgrade;
3. only then the client's socket is taken over as a WebSocket SERVER
   (``simple_websocket.Server(environ, max_message_size=...)``, the workers'
   ``max_http_buffer_size``: a message over it closes the connection), and
   messages are relayed both ways, text as text and binary as binary, the
   handler thread one way and one relay thread (``frontdoor-ws-relay``) the
   other, until either side closes; then the other is closed with the same
   code and the relay thread joined (``RELAY_JOIN_SECONDS``);
4. the WSGI call ends as engineio's does after its own takeover: ``raise
   StopIteration()`` under gunicorn, ``raise ConnectionError()`` under
   Werkzeug (by the server's ``ws.mode``), so the server writes nothing more
   on that socket.

The client never speaks HTTP to the worker: what it sends after a refused
upgrade on a keep-alive connection is parsed by the front door's own server,
as a new request through every check (spec §14.5's "why a relay").

A REVOKED LOGIN IS CLOSED (fix round 1, I1). The relay authenticates once,
at the upgrade, and the worker's socket guard re-reads the login on every
event; but a connection that only listens sends no event, and the
``/account`` page and the admin panel are served HERE, not by the worker, so
the worker's own revocation listener never hears them. So the relay keeps
its links by account: the front door's ``AccountStore.on_revoke`` calls
``revoke``, which ASKS every link of that account whose login is no longer
live to close (1008), and returns at once; each link's handler thread closes
it within ``WAKE_SECONDS``, the close frame's send bounded by
``CLOSE_SECONDS`` and a client stuck in a send cut instead (v0.20.0 T14: the
close used to run on the caller's thread, where a client that had stopped
reading held a disable for 20 s). Each link also re-reads its login every
``ACCOUNT_RECHECK_SECONDS`` through the store's cached read, which catches a
change another process made (``scripts/users.py``).

AN UPGRADE JOINS ITS POLL (v0.20.0 T14, from T13's re-review N1): a
WebSocket upgrading from polling names its session (``sid``), and it and
that tab's last poll count once toward the account's
``hosting.max_connections_per_account``. Only that one WebSocket joins for
free; any other hold naming the session counts (T14 fix round 1, I1).

A PASSWORD AN ADMIN GENERATED (``must_change``) is refused 403 ``{"error":
"password change required"}`` here, as at the HTTP door.

A CLIENT THAT STOPS READING (fix round 1, M1): a send to it that blocks past
``SEND_STALL_SECONDS`` ends the link -- the client's socket is shut both
ways, which wakes the send -- so its threads and the worker's buffered
output are not left behind outside the long-hold count.

COST. simple-websocket's two reader threads (one per end) and the relay
thread, outside the server's pool; the handler thread is a pool thread for
the connection's life, which is why every relay holds one of the front
door's ``LongHolds`` places (v0.20.0 T13, from T12's review M3).

Version: v0.3.0 [2026-10-05]
"""

from __future__ import annotations

import json
import logging
import socket
import threading
from typing import Any, Callable, Iterable, Optional

import simple_websocket
from simple_websocket.ws import Base as _WebSocketBase
from wsproto import ConnectionType
from wsproto.events import AcceptConnection, RejectConnection, Request

logger = logging.getLogger(__name__)

#: How long the worker has to answer the upgrade (it is on loopback).
HANDSHAKE_SECONDS = 10.0

#: How often each relay loop wakes to see whether the other side has ended.
WAKE_SECONDS = 1.0

#: How long the handler waits for the relay thread once a side has closed.
RELAY_JOIN_SECONDS = 10.0

#: How often an open relay re-reads its login (fix round 1, I1): a change
#: another process made (``scripts/users.py``) closes it within this.
ACCOUNT_RECHECK_SECONDS = 2.0

#: How long one send to the client may block before the client is taken to
#: have stopped reading and its connection is shut (fix round 1, M1).
SEND_STALL_SECONDS = 30.0

#: How long a revoked link's close frame may take to send before the
#: client's socket is shut instead (``_Link.end_bounded``).
CLOSE_SECONDS = 5.0

#: The close code a revoked login's connections get.
POLICY_VIOLATION = 1008

#: The worker answered the upgrade with anything but ``101``.
WORKER_REFUSED = {"error": "the story refused the connection"}

#: The client's upgrade request was not a WebSocket handshake.
BAD_UPGRADE = {"error": "not a WebSocket handshake"}


def is_upgrade(environ: dict[str, Any], socket_path: str = "/socket.io/") -> bool:
    """A ``GET`` on the Socket.IO path asking ``Upgrade: websocket``."""
    path = str(environ.get("PATH_INFO", "") or "")
    on_path = path == socket_path.rstrip("/") or path.startswith(socket_path)
    upgrade = str(environ.get("HTTP_UPGRADE", "") or "").strip().lower() == "websocket"
    return on_path and upgrade and str(environ.get("REQUEST_METHOD", "")).upper() == "GET"


def handshake_ok(environ: dict[str, Any]) -> bool:
    """
    Whether the client's upgrade is a WebSocket handshake RFC 6455 accepts:
    ``Connection`` naming ``upgrade``, ``Sec-WebSocket-Version: 13`` and a
    ``Sec-WebSocket-Key`` of 16 base64-coded bytes. Checked before anything
    reaches a worker, so a malformed one costs no worker session (M5).
    """
    import base64
    import binascii

    tokens = {t.strip().lower() for t in str(environ.get("HTTP_CONNECTION", "") or "").split(",")}
    if "upgrade" not in tokens:
        return False
    if str(environ.get("HTTP_SEC_WEBSOCKET_VERSION", "") or "").strip() != "13":
        return False
    key = str(environ.get("HTTP_SEC_WEBSOCKET_KEY", "") or "").strip()
    try:
        return len(base64.b64decode(key, validate=True)) == 16
    except (binascii.Error, ValueError):
        return False


class WorkerSocket(simple_websocket.Client):
    """
    simple-websocket's client, connected to a worker on loopback with a
    BOUNDED handshake: the connect and the upgrade's answer each within
    ``timeout`` (the stock client waits for ever on a peer that says
    nothing), the request's ``Host`` the player's, and any frame the worker
    sent in the same read as its ``101`` (engineio's ``open`` packet) handed
    on at once rather than left until the next one arrives.

    Raises ``simple_websocket.ConnectionError`` (``status_code`` the
    worker's, or None when it said nothing) or ``OSError``.
    """

    def __init__(
        self,
        port: int,
        target: str,
        *,
        host_header: str,
        headers: list[tuple[str, str]],
        max_message_size: Optional[int],
        timeout: float = HANDSHAKE_SECONDS,
    ) -> None:
        self.host = "127.0.0.1"
        self.port = int(port)
        self.path = target
        self.subprotocols: list[str] = []
        self.extra_headeers = headers  # (sic) simple-websocket's own attribute name
        self.host_header = host_header or f"{self.host}:{self.port}"
        self._timeout = float(timeout)
        sock = socket.create_connection((self.host, self.port), timeout=self._timeout)
        try:
            _WebSocketBase.__init__(
                self,
                sock,
                connection_type=ConnectionType.CLIENT,
                max_message_size=max_message_size,
            )
        except BaseException:
            sock.close()
            raise

    def handshake(self) -> None:
        self.sock.settimeout(self._timeout)
        self.sock.sendall(
            self.ws.send(Request(host=self.host_header, target=self.path, extra_headers=self.extra_headeers))
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
        self.subprotocol = event.subprotocol
        self.sock.settimeout(None)
        self.connected = True
        # Frames that came with the 101 (engineio sends its open packet at
        # once): taken now, before the reader thread blocks on the socket.
        self.connected = self._handle_events()


def _engineio_sid(environ: dict[str, Any]) -> str:
    """The request's Engine.IO session id (``sid`` in its query), or ""."""
    from urllib.parse import parse_qs

    values = parse_qs(str(environ.get("QUERY_STRING", "") or "")).get("sid") or [""]
    return str(values[0])[:64]


def _close(ws: Any, code: Any) -> None:
    """Close ``ws`` with ``code`` if it is still open (a local-only code goes as 1000)."""
    if not getattr(ws, "connected", False):
        return
    try:
        ws.close(reason=code)
    except (simple_websocket.ConnectionClosed, OSError):
        pass


class WebSocketRelay:
    """
    The WSGI layer (see the module docstring). ``inner`` (read on every
    call) is what it wraps; ``app`` is the front door's Flask app, for
    ``authenticate`` and the story table; ``holds`` its ``LongHolds``;
    ``max_message_size`` the workers' ``max_http_buffer_size``.
    """

    def __init__(
        self,
        inner: Callable[..., Iterable[bytes]],
        app: Any,
        *,
        holds: Any,
        max_message_size: int,
        public_origin: str,
        proxy_token: str,
        socket_path: str = "/socket.io/",
    ) -> None:
        self.inner = inner
        self.app = app
        self.holds = holds
        self.max_message_size = int(max_message_size)
        self.public_origin = str(public_origin or "")
        self._token = str(proxy_token or "")
        self.socket_path = socket_path
        self._lock = threading.Lock()
        self._active = 0
        #: Open links by account id (``revoke``), under ``_lock``, a leaf.
        self._links: dict[str, set[_Link]] = {}

    @property
    def active(self) -> int:
        """Relays open now (each holds a ``holds`` place)."""
        with self._lock:
            return self._active

    # -- answers ------------------------------------------------------------------

    @staticmethod
    def _answer(start_response: Callable[..., Any], status: str, body: dict[str, Any]) -> list[bytes]:
        data = json.dumps(body).encode("utf-8")
        start_response(status, [("Content-Type", "application/json"), ("Content-Length", str(len(data)))])
        return [data]

    # -- the door -------------------------------------------------------------------

    def __call__(self, environ: dict[str, Any], start_response: Callable[..., Any]) -> Any:
        if not is_upgrade(environ, self.socket_path):
            return self.inner(environ, start_response)
        return self._door(environ, start_response)

    def _admit(self, environ: dict[str, Any]) -> tuple[Optional[tuple[str, dict[str, Any]]], Any]:
        """Step 1 bar the long hold: ``((status, body) or None, admission)``."""
        from werkzeug.wsgi import get_host

        from engine.hosting.frontdoor.gate import MUST_CHANGE, NO_STORY, PASSWORD_CHANGE_REQUIRED, authenticate
        from engine.hosting.frontdoor.proxy import NO_STORY as NO_STORY_BODY
        from engine.hosting.frontdoor.proxy import UNAVAILABLE as UNAVAILABLE_BODY
        from engine.hosting.gate import CROSS_SITE, LOGIN_REQUIRED, origin_allowed, origin_of

        if not handshake_ok(environ):
            # Before the login check costs a worker anything (M5).
            return ("400 Bad Request", BAD_UPGRADE), None
        admission = authenticate(environ, app=self.app)
        if admission.account is None:
            return ("401 Unauthorized", LOGIN_REQUIRED), admission
        if admission.refusal == MUST_CHANGE:
            # A password an admin generated must be replaced first (T14).
            return ("403 Forbidden", PASSWORD_CHANGE_REQUIRED), admission
        if admission.refusal == NO_STORY:
            return ("409 Conflict", NO_STORY_BODY), admission
        if not admission.ok or admission.row is None:
            return ("503 Service Unavailable", UNAVAILABLE_BODY), admission
        sent = environ.get("HTTP_ORIGIN")
        if sent is not None:
            scheme = str(environ.get("wsgi.url_scheme", "http"))
            if not origin_allowed(origin_of(sent), scheme, get_host(environ), self.public_origin):
                logger.warning(
                    "[frontdoor] Refused a cross-site WebSocket (operation=ws_relay, from=%.80r)",
                    origin_of(sent),
                )
                return ("403 Forbidden", CROSS_SITE), admission
        return None, admission

    def _door(self, environ: dict[str, Any], start_response: Callable[..., Any]) -> Any:
        from engine.hosting.limits import ACCOUNT, SERVER_FULL, too_many_connections

        refused, admission = self._admit(environ)
        if refused is not None:
            status, body = refused
            logger.info("[frontdoor] Refused a WebSocket (operation=ws_relay, status=%s)", status.split(" ", 1)[0])
            return self._answer(start_response, status, body)
        account_id = str(admission.account.id)
        # A WebSocket upgrading from polling names its Engine.IO session: it
        # and that tab's last poll are one connection (T13 re-review N1).
        sid = _engineio_sid(environ)
        reason = self.holds.try_take(account_id, sid, upgrade=True)
        if reason:
            logger.warning(
                "[frontdoor] Refused a WebSocket (operation=ws_relay, reason=%s, holds=%d)",
                reason,
                self.holds.limit,
            )
            if reason == ACCOUNT:
                return self._answer(
                    start_response,
                    "429 Too Many Requests",
                    {"error": too_many_connections(self.holds.per_account or 0)},
                )
            return self._answer(start_response, "503 Service Unavailable", {"error": SERVER_FULL})
        try:
            return self._relay(environ, start_response, admission)
        finally:
            self.holds.give_back(account_id, sid, upgrade=True)

    # -- revocation (fix round 1, I1) -------------------------------------------------

    def _live(self, link: "_Link") -> bool:
        """Whether ``link``'s login is still live (re-read through the accounts store's cache)."""
        from engine.hosting.auth import hosting_state

        try:
            account = hosting_state(self.app).accounts.get(link.account_id)
        except Exception:  # noqa: BLE001 -- an unreadable users.json is not a live login
            logger.exception("[frontdoor] Accounts unreadable (operation=ws_relay)")
            return False
        return account is not None and not account.disabled and account.epoch == link.epoch

    def revoke(self, account_id: str) -> None:
        """
        ``AccountStore.on_revoke``'s listener: an account's logins ended in
        this process (the ``/account`` page or the admin panel, both served
        here). Every relayed connection of that account whose login is no
        longer live is ASKED to close, both ends, with 1008 (policy
        violation): the close itself runs on that link's own handler thread
        (``_inbound``, within ``WAKE_SECONDS``), never on the caller's, so a
        client that has stopped reading can hold up neither the password
        change nor an admin's action (v0.20.0 T14; T13 fix round 1 closed it
        here, where the close frame could block on such a client).
        """
        with self._lock:
            links = list(self._links.get(str(account_id), ()))
        for link in links:
            if not self._live(link):
                link.ask_end(POLICY_VIOLATION)

    def _track(self, link: "_Link", add: bool) -> None:
        with self._lock:
            if add:
                self._active += 1
                self._links.setdefault(link.account_id, set()).add(link)
                return
            self._active -= 1
            found = self._links.get(link.account_id)
            if found is not None:
                found.discard(link)
                if not found:
                    del self._links[link.account_id]

    def _worker_headers(self, environ: dict[str, Any]) -> list[tuple[str, str]]:
        from werkzeug.wsgi import get_host

        from engine.hosting.gate import PROXY_HEADER

        headers: list[tuple[str, str]] = []
        for key, name in (("HTTP_COOKIE", "Cookie"), ("HTTP_ORIGIN", "Origin"), ("HTTP_USER_AGENT", "User-Agent")):
            value = environ.get(key)
            if value is not None:
                headers.append((name, str(value)))
        # What THIS front door resolved (its own ProxyFix), never the client's.
        headers.append(("X-Forwarded-For", str(environ.get("REMOTE_ADDR", "") or "")))
        headers.append(("X-Forwarded-Proto", str(environ.get("wsgi.url_scheme", "http"))))
        headers.append(("X-Forwarded-Host", get_host(environ)))
        headers.append((PROXY_HEADER, self._token))
        return headers

    @staticmethod
    def _target(environ: dict[str, Any]) -> str:
        from urllib.parse import quote

        path = quote(str(environ.get("PATH_INFO", "") or "/"), safe="/:@!$&'()*+,;=-._~%")
        query = str(environ.get("QUERY_STRING", "") or "")
        return f"{path}?{query}" if query else path

    def _relay(self, environ: dict[str, Any], start_response: Callable[..., Any], admission: Any) -> Any:
        from werkzeug.wsgi import get_host

        slug = admission.story
        try:
            worker = WorkerSocket(
                int(admission.row["port"]),
                self._target(environ),
                host_header=get_host(environ),
                headers=self._worker_headers(environ),
                # The worker is trusted and its cap bounds what it ACCEPTS;
                # what it sends has none (fix round 1, M2).
                max_message_size=None,
            )
        except (simple_websocket.ConnectionError, OSError) as exc:
            logger.warning(
                "[frontdoor] The story refused a WebSocket (operation=ws_relay, story=%s, status=%s)",
                slug,
                getattr(exc, "status_code", None) or type(exc).__name__,
            )
            return self._answer(start_response, "502 Bad Gateway", WORKER_REFUSED)
        try:
            client = simple_websocket.Server(environ, max_message_size=self.max_message_size)
        except Exception as exc:  # noqa: BLE001 -- a malformed handshake: nothing was sent yet
            _close(worker, None)
            logger.info(
                "[frontdoor] A WebSocket upgrade was not a handshake (operation=ws_relay, error=%s)",
                type(exc).__name__,
            )
            return self._answer(start_response, "400 Bad Request", BAD_UPGRADE)
        link = _Link(str(admission.account.id), int(admission.account.epoch), client, worker)
        self._track(link, True)
        logger.info("[frontdoor] WebSocket relayed (operation=ws_relay, story=%s)", slug)
        relay = threading.Thread(target=self._outbound, args=(link,), name="frontdoor-ws-relay", daemon=True)
        try:
            relay.start()
            self._inbound(link)
            relay.join(RELAY_JOIN_SECONDS)
            if relay.is_alive():
                # Stuck in a send to a client that stopped reading: shut its
                # socket, which wakes the send, and wait once more (M1).
                logger.error("[frontdoor] A relay thread did not end in time (operation=ws_relay, story=%s)", slug)
                link.abort()
                relay.join(RELAY_JOIN_SECONDS)
        finally:
            link.end(None)
            self._track(link, False)
            logger.info("[frontdoor] WebSocket closed (operation=ws_relay, story=%s)", slug)
        # engineio's own ending after a takeover: the server writes nothing more.
        if client.mode == "gunicorn":
            raise StopIteration()
        if client.mode == "werkzeug":
            raise ConnectionError()
        return []

    def _inbound(self, link: "_Link") -> None:
        """
        The handler thread: the client's messages to the worker. Each time it
        wakes it also re-checks the login (``ACCOUNT_RECHECK_SECONDS``: a
        change another process made, which no listener heard, I1) and whether
        the other direction is stuck in a send to a client that stopped
        reading (``SEND_STALL_SECONDS``, M1), and ends the link for either.
        """
        import time

        next_check = time.monotonic() + ACCOUNT_RECHECK_SECONDS
        try:
            while not link.done.is_set():
                try:
                    data = link.client.receive(timeout=WAKE_SECONDS)
                except simple_websocket.ConnectionClosed:
                    break
                now = time.monotonic()
                if link.end_asked is not None:
                    logger.info("[frontdoor] WebSocket closed, login no longer live (operation=ws_relay)")
                    link.end_bounded(link.end_asked)
                    return
                if now >= next_check:
                    next_check = now + ACCOUNT_RECHECK_SECONDS
                    if not self._live(link):
                        logger.info("[frontdoor] WebSocket closed, login no longer live (operation=ws_relay)")
                        link.end(POLICY_VIOLATION)
                        return
                stalled = link.sending_since
                if stalled and now - stalled > SEND_STALL_SECONDS:
                    logger.warning(
                        "[frontdoor] WebSocket closed: the client stopped reading (operation=ws_relay, seconds=%d)",
                        int(now - stalled),
                    )
                    link.abort()
                    return
                if data is None:
                    continue
                try:
                    link.worker.send(data)
                except (simple_websocket.ConnectionClosed, OSError):
                    break
        finally:
            link.end_from(link.client)

    @staticmethod
    def _outbound(link: "_Link") -> None:
        """The relay thread: the worker's messages to the client."""
        import time

        try:
            while not link.done.is_set():
                try:
                    data = link.worker.receive(timeout=WAKE_SECONDS)
                except simple_websocket.ConnectionClosed:
                    break
                if data is None:
                    continue
                link.sending_since = time.monotonic()
                try:
                    link.client.send(data)
                except (simple_websocket.ConnectionClosed, OSError):
                    break
                finally:
                    link.sending_since = 0.0
        finally:
            link.end_from(link.worker)


class _Link:
    """
    One relayed connection: its two ends, whose it is and the epoch it was
    admitted under. Whichever side ends first closes the other with its own
    close code (``end_from``); a revocation closes both with 1008 (``end``);
    a client that stopped reading has its socket shut (``abort``).
    """

    def __init__(self, account_id: str, epoch: int, client: Any, worker: Any) -> None:
        self.account_id = account_id
        self.epoch = epoch
        self.client = client
        self.worker = worker
        self.done = threading.Event()
        #: When the relay thread began its current send to the client (0: none).
        self.sending_since = 0.0
        #: A close another thread asked for (``ask_end``): the code, or None.
        self.end_asked: Optional[int] = None
        self._lock = threading.Lock()

    def ask_end(self, code: int) -> None:
        """Ask the handler thread to close both ends with ``code``; returns at once."""
        self.end_asked = int(code)

    def end_bounded(self, code: Any) -> None:
        """
        ``end(code)`` on the handler thread, bounded: a client stuck in a
        send (it stopped reading) is cut (``abort``), and otherwise the close
        frame's send may take ``CLOSE_SECONDS`` at most before the client's
        socket is shut.
        """
        if self.sending_since:
            self.abort()
            return
        sock = getattr(self.client, "sock", None)
        if sock is not None:
            try:
                sock.settimeout(CLOSE_SECONDS)
            except OSError:
                pass
        try:
            self.end(code)
        except Exception:  # noqa: BLE001 -- a close that failed: cut the socket instead
            self.abort()
            return
        if sock is not None and getattr(self.client, "connected", False):
            self.abort()

    def _claim(self) -> bool:
        with self._lock:
            if self.done.is_set():
                return False
            self.done.set()
            return True

    def end_from(self, source: Any) -> None:
        """``source`` ended: close the other end with its code."""
        if self._claim():
            _close(self.worker if source is self.client else self.client, source.close_reason)

    def end(self, code: Any) -> None:
        """Close both ends with ``code`` (once; later calls do nothing)."""
        if self._claim():
            _close(self.client, code)
            _close(self.worker, code)

    def abort(self) -> None:
        """Shut the client's socket both ways (wakes a send blocked on it), and close the worker."""
        self.done.set()
        sock = getattr(self.client, "sock", None)
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                sock.close()
            except OSError:
                pass
        _close(self.worker, None)


__all__ = [
    "ACCOUNT_RECHECK_SECONDS",
    "BAD_UPGRADE",
    "HANDSHAKE_SECONDS",
    "POLICY_VIOLATION",
    "RELAY_JOIN_SECONDS",
    "SEND_STALL_SECONDS",
    "WAKE_SECONDS",
    "WORKER_REFUSED",
    "WebSocketRelay",
    "WorkerSocket",
    "handshake_ok",
    "is_upgrade",
]
