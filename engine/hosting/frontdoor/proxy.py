"""
The Front Door: the HTTP Proxy
==============================

Every request the front door does not answer itself goes to the chosen
story's worker through ``Proxy.forward``, served as a Flask CATCH-ALL ROUTE
(``register``), so the gate (``frontdoor/gate.py``) runs on it as on the
front door's own pages (spec §14.5). Socket.IO's long-polling transport is
plain HTTP and goes through it too; a WebSocket upgrade never reaches it
(``ws_relay.py``, v0.20.0 T13, answers it outside Flask).

ONE POOLED ``httpx.Client`` per front door: ``trust_env=False`` (no system
proxy intercepts loopback), ``follow_redirects=False`` (a worker's redirect
reaches the browser as it was sent). The answer is streamed; the request's
body is read whole first, on every route, within ``hosting.body_read_seconds``
(408 past it; v0.20.0 T13 fix round 1, M3, so no slow body holds a pool
thread longer), and held to ``MAX_CONTENT_LENGTH`` (``hosting.max_upload_mb``)
here as well, 413 past it.

A READ TIMEOUT PER ROUTE CLASS (``read_timeout_for``), each above the
longest wait it covers:

- a Socket.IO polling ``GET``, which engineio holds open for up to
  ``ping_interval + ping_timeout`` (25 + 20 s): ``POLLING_READ_SECONDS``, 60;
- a route that may run a turn or a model call (``gate.TURN_RULES``: ``POST
  /api/game/new``, ``/api/game/choice``, ``/api/voice/transcribe``):
  ``hosting.queue_wait_seconds + hosting.turn_deadline_seconds +
  TURN_MARGIN_SECONDS`` (60): the longest a turn may wait for its place,
  then the longest an admitted turn may run (fix round 1: since T11 the
  deadline bounds a turn, where ``llm.timeout_seconds`` bounds one read);
- everything else: ``DEFAULT_READ_SECONDS``, 30.

A worker that cannot be reached is answered 503 (the story's page for
``GET /``, ``{"error": "story unavailable"}`` elsewhere); one that does not
answer within its read timeout, 504.

HEADERS. Hop-by-hop headers (and any named in ``Connection``) are dropped
both ways, ``Host`` is kept, RFC 7239's ``Forwarded`` is dropped (fix round
1), ``X-Forwarded-For``/``-Proto``/``-Host`` are REPLACED with what this front door resolved (its own ``ProxyFix``, spec §7.3:
the client's address, scheme and host), and ``X-Clockwork-Proxy`` carries the
boot's proxy token, which a worker checks before it trusts any of them. Any
``Set-Cookie`` for ``clockwork_session`` in a worker's response is STRIPPED:
the front door is the cookie's one writer (spec §6.2).

THE FRONT DOOR'S OWN PATHS are never forwarded, whatever the method:
``/login``, ``/logout``, ``/account``, ``/stories`` (and under it),
``/admin`` (and under it: the admin panel, v0.20.0 T14, whose guard answers
every path there first), ``/api/health`` and ``/static/hosting/``
(``RESERVED``).

TURN SLOTS. A proxied turn holds a front door thread for as long as the
worker takes, so the front door, which carries every story's, keeps its own
``limits.TurnSlots``: past ``hosting.threads - RESERVED_THREADS`` HTTP turns
in flight at once, or a second from one account, one more is answered 429
at once. A turn's whole body is read first (``limits.read_body``, within
``hosting.body_read_seconds``, 408 past it) and sent to the worker from
memory, so a client trickling its body never holds a slot (fix round 1).
Each turn slot is also a place among the front door's ``limits.LongHolds``,
and so is each polling ``GET`` while engineio holds it open (v0.20.0 T13):
past ``hosting.threads - RESERVED_THREADS`` of them together with the open
WebSockets, a poll is answered 503 (``SERVER_FULL``) and a turn 429; and a
poll counts toward its account's ``hosting.max_connections_per_account``
(429 past it, fix round 1, I4), every poll apiece; only the WebSocket that
upgrades from a poll joins it for free, by the ``sid`` both name (v0.20.0
T14, from T13's re-review N1; T14 fix round 1, I1).

Version: v0.5.0 [2026-10-05]
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Iterator, Optional

import httpx
from flask import Response, jsonify, request

from engine.hosting.auth import COOKIE_NAME
from engine.hosting.gate import PROXY_HEADER, TURN_RULES
from engine.hosting.limits import (
    BODY_TIMEOUT,
    ACCOUNT,
    SERVER_FULL,
    BodyTimeout,
    BodyTooLarge,
    read_body,
    refusal_text,
    too_many_connections,
)

logger = logging.getLogger(__name__)

#: A polling GET's read timeout: above engineio's ``ping_interval +
#: ping_timeout`` (25 + 20 s by default), the longest it holds a poll open.
POLLING_READ_SECONDS = 60.0

#: Every other route's read timeout, bar the turns'.
DEFAULT_READ_SECONDS = 30.0

#: A turn route's read timeout over ``queue_wait_seconds + turn_deadline_seconds``.
TURN_MARGIN_SECONDS = 60.0

#: How long a connection to a worker (loopback) may take.
CONNECT_SECONDS = 5.0

#: How long a request body's chunk may take to reach the worker.
WRITE_SECONDS = 30.0

#: How long a request waits for a pooled connection.
POOL_SECONDS = 10.0

#: Headers that belong to one hop, never forwarded either way (RFC 9110 §7.6.1).
HOP_BY_HOP = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "proxy-connection",
        "te",
        "trailer",
        "trailers",
        "transfer-encoding",
        "upgrade",
    }
)

#: Paths the front door answers itself, never forwarded (prefixes end in "/").
RESERVED = (
    "/login",
    "/logout",
    "/account",
    "/stories",
    "/stories/",
    "/admin",
    "/admin/",
    "/api/health",
    "/static/hosting/",
)

#: The Socket.IO path a polling request names.
SOCKET_PATH = "/socket.io/"

#: What a request for a story that is not running is told.
UNAVAILABLE = {"error": "story unavailable"}

#: What a request with no story chosen is told.
NO_STORY = {"error": "no story chosen: choose one at /stories"}

#: What a request whose worker did not answer in time is told.
TIMED_OUT = {"error": "the story did not answer in time"}

#: Every method the catch-all forwards.
METHODS = ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]

#: Body chunk size, both ways.
CHUNK = 64 * 1024


def reserved(path: str) -> bool:
    """Whether ``path`` is one of the front door's own (``RESERVED``)."""
    for item in RESERVED:
        if item.endswith("/"):
            if path.startswith(item):
                return True
        elif path == item:
            return True
    return False


def is_polling(method: str, path: str) -> bool:
    """A Socket.IO long-polling ``GET``."""
    return method.upper() == "GET" and (path == SOCKET_PATH.rstrip("/") or path.startswith(SOCKET_PATH))


def is_turn(method: str, path: str) -> bool:
    """A route that may run a turn or a model call (``gate.TURN_RULES``)."""
    return (method.upper(), path) in TURN_RULES


def session_cookie(name: str, value: str) -> bool:
    """Whether a response header is a ``Set-Cookie`` for ``clockwork_session``."""
    if name.lower() != "set-cookie":
        return False
    return value.split("=", 1)[0].strip() == COOKIE_NAME


class Proxy:
    """
    The front door's HTTP proxy: one pooled client, the timeouts per route
    class, the forwarding. ``turn_seconds`` is ``hosting.queue_wait_seconds +
    hosting.turn_deadline_seconds``; ``body_seconds`` is
    ``hosting.body_read_seconds``.
    """

    def __init__(
        self,
        *,
        proxy_token: str,
        turn_seconds: float,
        slots: Any = None,
        body_seconds: float = DEFAULT_READ_SECONDS,
        holds: Any = None,
    ) -> None:
        self._token = str(proxy_token or "")
        self.turn_read_seconds = float(turn_seconds) + TURN_MARGIN_SECONDS
        self.slots = slots
        #: The front door's ``limits.LongHolds`` (T13): a polling GET takes a place.
        self.holds = holds
        self.body_seconds = float(body_seconds)
        self.client = httpx.Client(
            trust_env=False,
            follow_redirects=False,
            timeout=httpx.Timeout(DEFAULT_READ_SECONDS, connect=CONNECT_SECONDS),
            limits=httpx.Limits(max_connections=None, max_keepalive_connections=32),
        )

    def close(self) -> None:
        self.client.close()

    # -- the route classes ------------------------------------------------------

    def read_timeout_for(self, method: str, path: str) -> float:
        """The read timeout a request of ``method`` on ``path`` is forwarded with."""
        if is_polling(method, path):
            return POLLING_READ_SECONDS
        if is_turn(method, path):
            return self.turn_read_seconds
        return DEFAULT_READ_SECONDS

    def timeout_for(self, method: str, path: str) -> httpx.Timeout:
        """The ``httpx.Timeout`` a request is forwarded with."""
        return httpx.Timeout(
            connect=CONNECT_SECONDS,
            read=self.read_timeout_for(method, path),
            write=WRITE_SECONDS,
            pool=POOL_SECONDS,
        )

    # -- forwarding -------------------------------------------------------------

    def _target(self, port: int) -> str:
        raw = request.environ.get("RAW_URI") or request.environ.get("REQUEST_URI") or ""
        if not isinstance(raw, str) or not raw.startswith("/") or raw.startswith("//"):
            raw = request.full_path if request.query_string else request.path
        return f"http://127.0.0.1:{int(port)}{raw}"

    def _headers(self) -> list[tuple[str, str]]:
        named = {
            token.strip().lower()
            for token in request.headers.get("Connection", "").split(",")
            if token.strip()
        }
        out: list[tuple[str, str]] = []
        for key, value in request.headers.items():
            lower = key.lower()
            if (
                lower in HOP_BY_HOP
                or lower in named
                or lower.startswith("x-forwarded-")
                or lower == "forwarded"
                or lower == PROXY_HEADER.lower()
                or lower == "content-length"
            ):
                continue
            out.append((key, value))
        if request.content_length is not None:
            out.append(("Content-Length", str(request.content_length)))
        # What THIS front door resolved (its own ProxyFix, spec §7.3), never
        # what the client sent: a client's header never reaches a worker as fact.
        out.append(("X-Forwarded-For", str(request.remote_addr or "")))
        out.append(("X-Forwarded-Proto", request.scheme))
        out.append(("X-Forwarded-Host", request.host))
        out.append((PROXY_HEADER, self._token))
        return out

    def forward(self, slug: str, row: dict[str, Any], *, page: bool = False, account: str = "") -> Any:
        """
        Send this request to ``slug``'s worker (its ``row``: state and port)
        and stream the answer back. ``page``: a failure is answered with the
        story's 503 page rather than JSON. ``account``: whose request it is
        (a turn's slot is counted per account).
        """
        method = request.method.upper()
        path = request.path
        limit = request.max_content_length
        if limit is not None and request.content_length is not None and request.content_length > limit:
            return jsonify({"error": "request too large"}), 413
        turn = is_turn(method, path)
        # Every body is read whole first, within body_read_seconds (T12 fix
        # round 1 for a turn; every route since T13 fix round 1, M3): a
        # trickling client is answered 408 here, never holds a turn slot, and
        # never holds a pool thread longer than the deadline. Bodies are held
        # to MAX_CONTENT_LENGTH, so reading one into memory costs nothing new.
        try:
            content: Any = read_body(request.environ, limit, self.body_seconds) or None
        except BodyTooLarge:
            return jsonify({"error": "request too large"}), 413
        except BodyTimeout:
            logger.warning(
                "[frontdoor] A body did not arrive in time (operation=proxy, story=%s, path=%.80r)",
                slug,
                path,
            )
            late = jsonify({"error": BODY_TIMEOUT})
            late.headers["Connection"] = "close"
            return late, 408
        slot = self.slots if (self.slots is not None and turn) else None
        if slot is not None:
            reason = slot.try_enter(account)
            if reason:
                logger.warning(
                    "[frontdoor] Refused an HTTP turn (operation=proxy, reason=%s, story=%s, "
                    "path=%.80r, slots=%d)",
                    reason,
                    slug,
                    path,
                    slot.limit,
                )
                return jsonify({"error": refusal_text(reason)}), 429
        held: list[Callable[[], None]] = []
        if slot is not None:
            held.append(lambda: slot.leave(account))
        if self.holds is not None and is_polling(method, path):
            # A poll holds this thread up to ping_interval + ping_timeout (T13),
            # and counts toward its account's connections (fix round 1, I4).
            # A poll always counts toward its account (T14 fix round 1, I1);
            # the sid lets the WebSocket that upgrades from it join it.
            sid = str(request.args.get("sid", "") or "")[:64]
            reason = self.holds.try_take(account, sid)
            if reason:
                logger.warning(
                    "[frontdoor] Refused a poll (operation=proxy, reason=%s, story=%s, holds=%d)",
                    reason,
                    slug,
                    self.holds.limit,
                )
                if reason == ACCOUNT:
                    return jsonify({"error": too_many_connections(self.holds.per_account or 0)}), 429
                return jsonify({"error": SERVER_FULL}), 503
            held.append(lambda: self.holds.give_back(account, sid))

        def release() -> None:
            for give_back in held:
                give_back()

        try:
            outgoing = self.client.build_request(
                method,
                self._target(int(row["port"])),
                headers=self._headers(),
                content=content,
                timeout=self.timeout_for(method, path),
            )
            response = self.client.send(outgoing, stream=True)
        except httpx.TimeoutException:
            release()
            logger.warning(
                "[frontdoor] The story did not answer in time (operation=proxy, story=%s, path=%.80r)",
                slug,
                path,
            )
            return jsonify(TIMED_OUT), 504
        except httpx.TransportError as exc:
            release()
            logger.warning(
                "[frontdoor] The story could not be reached (operation=proxy, story=%s, "
                "path=%.80r, error=%s)",
                slug,
                path,
                type(exc).__name__,
            )
            return self.unavailable(slug, row, page=page)
        except BaseException:
            release()
            raise
        return self._respond(response, release, slug)

    def _respond(self, response: httpx.Response, release: Callable[[], None], slug: str) -> Response:
        named = {
            token.strip().lower()
            for token in response.headers.get("Connection", "").split(",")
            if token.strip()
        }
        headers: list[tuple[str, str]] = []
        for key, value in response.headers.multi_items():
            lower = key.lower()
            if lower in HOP_BY_HOP or lower in named:
                continue
            if session_cookie(key, value):
                # Spec §6.2: the front door is the cookie's one writer.
                logger.warning(
                    "[frontdoor] Stripped a session cookie a worker tried to set "
                    "(operation=proxy, story=%s)",
                    slug,
                )
                continue
            headers.append((key, value))
        released = [False]

        def finish() -> None:
            if released[0]:
                return
            released[0] = True
            response.close()
            release()

        def body() -> Iterator[bytes]:
            try:
                for chunk in response.iter_raw(CHUNK):
                    yield chunk
            except httpx.HTTPError as exc:
                logger.warning(
                    "[frontdoor] A story's answer broke off (operation=proxy, story=%s, error=%s)",
                    slug,
                    type(exc).__name__,
                )
            finally:
                finish()

        answer = Response(body(), status=response.status_code, headers=headers, direct_passthrough=True)
        answer.call_on_close(finish)
        return answer

    def unavailable(self, slug: str, row: Optional[dict[str, Any]], *, page: bool) -> Any:
        """503: the story's page (``GET /``) or ``UNAVAILABLE`` as JSON."""
        if page:
            from engine.hosting.frontdoor import frontdoor
            from engine.hosting.frontdoor.stories import unavailable_page

            return unavailable_page(frontdoor().table, row, slug)
        return jsonify(UNAVAILABLE), 503


def register(app: Any, proxy: Proxy) -> None:
    """The catch-all route: every path the front door does not own, every method."""
    from engine.hosting.frontdoor.gate import NO_STORY as REFUSED_NO_STORY, UNAVAILABLE as REFUSED_UNAVAILABLE
    from engine.hosting.frontdoor.gate import admission

    def proxied(path: str = "") -> Any:
        if reserved(request.path):
            # One of the front door's own paths, in a method it does not
            # serve: answered here, never by a worker.
            return jsonify({"error": "method not allowed"}), 405
        found = admission()
        if found.refusal == REFUSED_NO_STORY:
            return jsonify(NO_STORY), 409
        if found.refusal == REFUSED_UNAVAILABLE or found.row is None:
            return proxy.unavailable(found.story, found.row, page=False)
        return proxy.forward(found.story, found.row, account=str(found.account.id))

    app.add_url_rule("/<path:path>", "proxy", proxied, methods=METHODS, provide_automatic_options=False)
    app.add_url_rule(
        "/",
        "proxy_root",
        proxied,
        methods=[m for m in METHODS if m not in ("GET", "HEAD")],
        provide_automatic_options=False,
    )


__all__ = [
    "CONNECT_SECONDS",
    "DEFAULT_READ_SECONDS",
    "HOP_BY_HOP",
    "METHODS",
    "NO_STORY",
    "POLLING_READ_SECONDS",
    "Proxy",
    "RESERVED",
    "TIMED_OUT",
    "TURN_MARGIN_SECONDS",
    "UNAVAILABLE",
    "is_polling",
    "is_turn",
    "register",
    "reserved",
    "session_cookie",
]
