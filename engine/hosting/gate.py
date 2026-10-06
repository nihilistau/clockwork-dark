"""
Hosted Mode: the HTTP Gate
==========================

ONE ``before_request`` for every HTTP route (spec §6.3), registered by
``install()`` BEFORE the engine's blueprints, the story's blueprint and the
scene's own routes are added, and covering every route added after it too: a
hook on the app runs for every rule, whoever registered it. A decorator per
route would be a list someone forgets to extend.

OPEN without a login (``OPEN``): ``GET /api/health``, ``GET``/``POST
/login``, ``POST /logout`` and ``/static/*`` (the built client, public in the
repo anyway). Everything else needs a live account -- the media, art and
audio routes on purpose (spec §6.8). ``GET /`` without one redirects to
``/login``; any other request answers 401 JSON ``{"error": "login
required"}``, an unknown URL included, so the gate says nothing about which
routes exist.

THE ACCOUNT IS RE-READ ON EVERY REQUEST (``auth.current_account``): a
disabled account, a removed one, or a cookie from before a password change is
logged out on its very next request. An account whose password an admin
generated (``must_change``, v0.20.0 T14) is treated as logged out too, bar
its own account page (``MUST_CHANGE_OPEN``), until its owner replaces it.

THE ORIGIN CHECK. A ``POST``, ``PUT``, ``PATCH`` or ``DELETE`` whose
``Origin`` (else ``Referer``) is present and names neither the request's own
origin (scheme and host) nor ``hosting.public_origin`` is refused with 403, open routes included
(login CSRF). The server-rendered forms carry a CSRF token as well
(``engine/hosting/auth.py``).

FORWARDED HEADERS (``ForwardedHeaders``, the outermost WSGI layer). With
``hosting.trusted_proxies: N`` the app is wrapped in Werkzeug's
``ProxyFix(x_for=N, x_proto=N, x_host=N)``, so the login buckets see the
client's address and ``cookie_secure`` the real scheme. Either way every
``X-Forwarded-*`` header is then DELETED before anything else reads it --
Socket.IO's own same-origin check reads them raw -- and, with ``0`` (the
default), the first request
that carried ``X-Forwarded-For`` logs one WARNING per process: behind a proxy
every client then shares the proxy's address, and one attacker can spend
everyone's login bucket.

THE OWNER (spec §6.4). A request with a live account has its owner set
(``engine.session.store.current_owner``) to that account's id, from the
cookie and never from the body, and ``teardown_request`` resets it. Every
session and save door reads it there, a story blueprint's included.

THE LIMITS (spec §6.5, v0.20.0 T9, ``limit_request``). A logged-in request
for an action (``ACTION_RULES``) spends a token from the account's actions
bucket, or is refused 429; one whose body carries a typed action or a name
(``CAPPED_RULES``) is held to the input caps first, refused 400 and never
cut. The voice upload's size is Flask's ``MAX_CONTENT_LENGTH``
(``hosting.max_upload_mb``), refused 413. A request that may run a turn
(``TURN_RULES``) takes one of the process's turn slots (``limits.TurnSlots``,
v0.20.0 T12) for as long as it runs, or is refused 429 at once when every
slot is taken, so turns waiting in the model server's queue never hold every
thread of the pool. Under the supervisor a cap or bucket refusal is also a
``turn`` metric, ``refused_cap`` or ``refused_rate`` (v0.20.0 T17).

UNDER THE SUPERVISOR (v0.20.0 T12, spec §7.3, §14.5) a worker is reached only
through the front door, and ``ProxyTokenHeaders`` replaces
``ForwardedHeaders`` as its outermost WSGI layer: a request carrying the
boot's proxy token (``X-Clockwork-Proxy``, compared with
``hmac.compare_digest``) has its forwarded headers resolved by
``ProxyFix(x_for=1, x_proto=1, x_host=1)`` -- one hop, the front door, which
REPLACED them with what it resolved itself -- and every other request has
them DELETED. The token header is removed either way, so neither engineio
nor Flask ever sees it, and ``hosting.trusted_proxies`` (the front door's
setting) is never applied twice.

Version: v0.4.0 [2026-10-06]
"""

from __future__ import annotations

import hmac
import logging
from typing import Any, Callable, Iterable, Optional
from urllib.parse import urlsplit

from flask import g, jsonify, redirect, request
from werkzeug.middleware.proxy_fix import ProxyFix

from engine.hosting import metrics_emit
from engine.hosting.auth import BLUEPRINT_NAME, current_account, hosting_state
from engine.hosting.limits import (
    BODY_TIMEOUT,
    SLOW_DOWN,
    BodyTimeout,
    BodyTooLarge,
    over_cap,
    read_body,
    refusal_text,
)
from engine.session.store import current_owner

logger = logging.getLogger(__name__)

#: ``endpoint -> methods`` served without a login.
OPEN: dict[str, frozenset[str]] = {
    "health": frozenset({"GET", "HEAD"}),
    "static": frozenset({"GET", "HEAD"}),
    f"{BLUEPRINT_NAME}.login": frozenset({"GET", "HEAD"}),
    f"{BLUEPRINT_NAME}.login_post": frozenset({"POST"}),
    f"{BLUEPRINT_NAME}.logout": frozenset({"POST"}),
}

#: The endpoints an account that must change its password may still reach
#: (``must_change``, v0.20.0 T14): its own account page, and logging out.
MUST_CHANGE_OPEN = frozenset(
    {
        f"{BLUEPRINT_NAME}.account_page",
        f"{BLUEPRINT_NAME}.account_post",
        f"{BLUEPRINT_NAME}.logout",
    }
)

#: Methods whose cross-site ``Origin`` is refused.
STATE_CHANGING = frozenset({"POST", "PUT", "PATCH", "DELETE"})

#: ``(method, rule)`` of every action the actions bucket counts (spec §6.5):
#: new game, choice, save write, resume (a save loaded) and transcribe. The
#: socket's ``player_choice`` and ``resume`` are counted by the socket door.
ACTION_RULES = frozenset(
    {
        ("POST", "/api/game/new"),
        ("POST", "/api/game/choice"),
        ("POST", "/api/saves"),
        ("POST", "/api/saves/<save_id>/load"),
        ("POST", "/api/voice/transcribe"),
    }
)

#: ``(method, rule)`` of every request whose JSON body carries text a player
#: wrote (an action, a name, an archetype, a seed, a save's label), held to
#: the input caps (``limits.over_cap``). The voice transcript is capped in
#: its route (``engine/api/voice.py``), being made on the server.
CAPPED_RULES = frozenset(
    {("POST", "/api/game/new"), ("POST", "/api/game/choice"), ("POST", "/api/saves")}
)

#: ``(method, rule)`` of every HTTP request that may run a turn or a model
#: call, and so may wait in the model server's queue: each takes a turn slot
#: (``limits.TurnSlots``) for its life. The front door's proxy reads the same
#: set for its longer read timeout (``engine/hosting/frontdoor/proxy.py``).
TURN_RULES = frozenset(
    {
        ("POST", "/api/game/new"),
        ("POST", "/api/game/choice"),
        ("POST", "/api/voice/transcribe"),
    }
)

#: The header the front door carries its proxy token in (spec §14.5).
PROXY_HEADER = "X-Clockwork-Proxy"

#: ``PROXY_HEADER`` as a WSGI environ key.
PROXY_ENVIRON_KEY = "HTTP_X_CLOCKWORK_PROXY"

#: What a request without a login is told.
LOGIN_REQUIRED = {"error": "login required"}

#: What a cross-site state-changing request is told.
CROSS_SITE = {"error": "cross-site request refused"}

#: Whether this process has logged the ``X-Forwarded-For`` WARNING.
_FORWARDED_WARNED = False


def is_open(endpoint: Any, method: str) -> bool:
    """Whether ``endpoint`` answers ``method`` without a login."""
    return method in OPEN.get(str(endpoint or ""), frozenset())


def _origin(value: str) -> str:
    """
    The ``scheme://host[:port]`` an ``Origin`` or ``Referer`` names, lower
    case; "" for an empty value, ``"null"`` for an opaque origin.
    """
    text = str(value or "").strip()
    if not text or text.lower() == "null":
        return "null" if text else ""
    try:
        parts = urlsplit(text)
    except ValueError:
        return "?"
    netloc = parts.netloc.rsplit("@", 1)[-1].lower()
    if not parts.scheme or not netloc:
        return "?"
    return f"{parts.scheme.lower()}://{netloc}"


def foreign_origin(public_origin: str) -> str:
    """
    The foreign ``Origin`` (else ``Referer``) of this state-changing request,
    or "" when it is absent, this request's own (scheme AND host), or
    ``public_origin``. The scheme counts: an ``http://`` page on the public
    name is not the ``https://`` origin players use.
    """
    if request.method not in STATE_CHANGING:
        return ""
    source = request.headers.get("Origin")
    if source is None:
        source = request.headers.get("Referer")
    if source is None:
        return ""
    sent = _origin(source)
    return "" if origin_allowed(sent, request.scheme, request.host, public_origin) else (sent or "?")


def origin_allowed(sent: str, scheme: str, host: str, public_origin: str) -> bool:
    """
    Whether ``sent`` (an ``Origin`` already read by ``_origin``) is this
    request's own ``scheme://host`` -- the RESOLVED scheme and host, after the
    door's ``ProxyFix``, never a raw ``X-Forwarded-Host`` -- or
    ``public_origin``. The front door's WebSocket door asks the same (v0.20.0
    T13).
    """
    allowed = {f"{str(scheme or '').lower()}://{str(host or '').lower()}"}
    if public_origin:
        allowed.add(_origin(public_origin))
    return sent in allowed


def origin_of(value: str) -> str:
    """An ``Origin`` header's ``scheme://host[:port]``, lower case (``_origin``)."""
    return _origin(value)


def limit_request(state: Any, account: Any) -> Any:
    """
    The input caps, then the actions bucket, for a logged-in request (spec
    §6.5): the refusal to answer, or None to serve it.

    Keyed by the matched rule and method (``ACTION_RULES``, ``CAPPED_RULES``),
    not by endpoint name, so a blueprint mounted under another name is
    limited all the same. A body over a cap is refused 400, never cut, and
    spends no token; an action past the bucket is refused 429.
    """
    rule = request.url_rule.rule if request.url_rule is not None else ""
    key = (request.method, rule)
    if key in TURN_RULES:
        # Fix round 1: the whole body first, within body_read_seconds, before
        # anything waits on it -- the caps below, and the turn slot.
        refused = _read_turn_body(state, account)
        if refused is not None:
            return refused
    if key in CAPPED_RULES:
        text = over_cap(request.get_json(silent=True), state.settings.max_input_chars)
        if text is not None:
            logger.info(
                "[hosting] Refused a request over the input cap (operation=gate, "
                "path=%.80r, account=%s)",
                request.path,
                account.id,
            )
            metrics_emit.refused(account.id, "refused_cap")
            return jsonify({"error": text}), 400
    if key in ACTION_RULES and state.actions is not None and not state.actions.allow(account.id):
        logger.info(
            "[hosting] Refused an action over the rate limit (operation=gate, "
            "path=%.80r, account=%s)",
            request.path,
            account.id,
        )
        metrics_emit.refused(account.id, "refused_rate")
        return jsonify({"error": SLOW_DOWN}), 429
    slots = getattr(state, "turn_slots", None)
    if key in TURN_RULES and slots is not None:
        reason = slots.try_enter(account.id)
        if reason:
            logger.warning(
                "[hosting] Refused an HTTP turn (operation=gate, reason=%s, path=%.80r, "
                "account=%s, slots=%d)",
                reason,
                request.path,
                account.id,
                slots.limit,
            )
            return jsonify({"error": refusal_text(reason)}), 429
        g.hosting_turn_slot = (slots, account.id)
    return None


def _read_turn_body(state: Any, account: Any) -> Any:
    """A turn's whole body read now (``limits.read_body``): None, or the 408/413 to answer."""
    try:
        read_body(request.environ, request.max_content_length, state.settings.body_read_seconds)
    except BodyTooLarge:
        return jsonify({"error": "request too large"}), 413
    except BodyTimeout:
        logger.warning(
            "[hosting] A turn's body did not arrive in time (operation=gate, path=%.80r, account=%s)",
            request.path,
            account.id,
        )
        response = jsonify({"error": BODY_TIMEOUT})
        response.headers["Connection"] = "close"
        return response, 408
    return None


def before_request() -> Any:
    """The gate: Origin, then the account, then the open list."""
    state = hosting_state()
    foreign = foreign_origin(state.settings.public_origin)
    if foreign:
        logger.warning(
            "[hosting] Refused a cross-site request (operation=gate, from=%.80r, "
            "method=%s, path=%.80r)",
            foreign,
            request.method,
            request.path,
        )
        return jsonify(CROSS_SITE), 403
    account = current_account()
    if account is not None and account.must_change:
        # A password an admin generated (spec §14.6, v0.20.0 T14): logged
        # out here until its owner replaces it. Only the account page (and
        # logging out) is served -- in a standalone hosted app, which mounts
        # the login blueprint; under the supervisor the front door does.
        if request.endpoint in MUST_CHANGE_OPEN:
            return None
        account = None
    if account is not None:
        # The request's owner (spec §6.4), from the cookie's account, never
        # from the body: what every session and save door reads.
        g.hosting_owner_token = current_owner.set(account.id)
        return limit_request(state, account)
    if is_open(request.endpoint, request.method):
        return None
    if request.path == "/" and request.method in {"GET", "HEAD"}:
        return redirect("/login", code=302)
    return jsonify(LOGIN_REQUIRED), 401


def teardown_request(_exc: Optional[BaseException] = None) -> None:
    """
    Give back the request's turn slot, if it took one, and reset the owner
    ``before_request`` set, so a reused thread never inherits it.
    """
    held = g.pop("hosting_turn_slot", None)
    if held is not None:
        slots, account_id = held
        slots.leave(account_id)
    token = g.pop("hosting_owner_token", None)
    if token is None:
        return
    try:
        current_owner.reset(token)
    except ValueError:  # set in another context: clear it rather than leave it
        current_owner.set(None)


def register(app: Any) -> None:
    """Install the gate on ``app`` (before any route is added, by ``install``)."""
    app.before_request(before_request)
    app.teardown_request(teardown_request)


def _warn_forwarded_once() -> None:
    global _FORWARDED_WARNED
    if _FORWARDED_WARNED:
        return
    _FORWARDED_WARNED = True
    logger.warning(
        "[hosting] A request carried X-Forwarded-For while hosting.trusted_proxies "
        "is 0 (operation=ForwardedHeaders): the header is ignored, so behind a "
        "reverse proxy every player shares the proxy's address and its login "
        "limit. Set hosting.trusted_proxies to the number of proxies in front "
        "(docs/HOSTING.md). Logged once per process."
    )


class ForwardedHeaders:
    """
    The outermost WSGI layer: ``ProxyFix`` for ``trusted`` proxies, or, with
    none trusted, every ``X-Forwarded-*`` header deleted (and the first
    ``X-Forwarded-For`` warned about).
    """

    def __init__(self, app: Callable[..., Iterable[bytes]], trusted: int) -> None:
        self.trusted = int(trusted)
        self.inner = app
        # With proxies trusted, ProxyFix resolves the address, scheme and host
        # and THEN the raw headers are deleted (``_stripped``), so nothing
        # inside -- Socket.IO's origin check reads them raw -- sees a value
        # ProxyFix did not vouch for (spec §7.3).
        self.app: Callable[..., Iterable[bytes]] = (
            ProxyFix(self._stripped, x_for=self.trusted, x_proto=self.trusted, x_host=self.trusted)
            if self.trusted > 0
            else self._stripped
        )

    def _stripped(self, environ: dict[str, Any], start_response: Callable[..., Any]) -> Any:
        strip_forwarded(environ)
        return self.inner(environ, start_response)

    def __call__(self, environ: dict[str, Any], start_response: Callable[..., Any]) -> Any:
        if chunked(environ):
            return refuse_chunked(environ, start_response)
        if self.trusted <= 0 and "HTTP_X_FORWARDED_FOR" in environ:
            _warn_forwarded_once()
        return self.app(environ, start_response)


#: What a request with a ``Transfer-Encoding`` body is told (fix round 2).
LENGTH_REQUIRED = (
    b'{"error":"This server needs a request body\'s length (Content-Length); '
    b'a body sent in chunks is refused."}'
)


def chunked(environ: dict[str, Any]) -> bool:
    """Whether the request's body is sent with a ``Transfer-Encoding`` (chunked)."""
    return bool(str(environ.get("HTTP_TRANSFER_ENCODING", "") or "").strip())


def refuse_chunked(environ: dict[str, Any], start_response: Callable[..., Any]) -> list[bytes]:
    """
    411 Length Required, and the connection closed (fix round 2, N1). Hosted
    mode takes a request body only with its ``Content-Length``: a chunked
    body's reads cannot be held to ``hosting.body_read_seconds`` (Werkzeug's
    ``DechunkedInput`` reads a whole buffer in one call, each recv restarting
    the socket's timeout), so a client trickling one could hold a thread for
    ever. Nothing the game serves sends one: the page's ``fetch`` calls and
    voice upload, and Socket.IO's polling POSTs, all send a length. Refused
    in the outermost layer of both doors, before Socket.IO or any route.
    """
    logger.warning(
        "[hosting] Refused a chunked request body (operation=gate, method=%s, path=%.80r)",
        environ.get("REQUEST_METHOD", ""),
        environ.get("PATH_INFO", ""),
    )
    start_response(
        "411 Length Required",
        [
            ("Content-Type", "application/json"),
            ("Content-Length", str(len(LENGTH_REQUIRED))),
            ("Connection", "close"),
        ],
    )
    return [LENGTH_REQUIRED]


def strip_forwarded(environ: dict[str, Any]) -> None:
    """
    Delete every ``X-Forwarded-*`` header from ``environ``, and RFC 7239's
    ``Forwarded`` (fix round 1): nothing reads it today, but a client's claim
    in it must not reach anything that someday would.
    """
    for key in [k for k in environ if k.startswith("HTTP_X_FORWARDED_") or k == "HTTP_FORWARDED"]:
        del environ[key]


class ProxyTokenHeaders:
    """
    A supervised worker's outermost WSGI layer (spec §7.3, §14.5), outside
    the host guard and Socket.IO's middleware: ``X-Clockwork-Proxy`` is
    removed from the environ, then checked against ``token`` (the boot's
    proxy token, ``hmac.compare_digest``). Right: ``ProxyFix(x_for=1,
    x_proto=1, x_host=1)`` resolves the front door's forwarded headers, which
    are then deleted. Absent or wrong: every ``X-Forwarded-*`` header is
    deleted as it stands, so engineio's same-origin check (which reads them
    raw) never trusts a header the front door did not send.

    ``inner`` is read on every call, so what it wraps can be replaced.
    """

    def __init__(self, app: Callable[..., Iterable[bytes]], token: str) -> None:
        self.inner = app
        self._token = str(token or "").encode("utf-8")
        self._trusting = ProxyFix(self._stripped, x_for=1, x_proto=1, x_host=1)

    def _stripped(self, environ: dict[str, Any], start_response: Callable[..., Any]) -> Any:
        strip_forwarded(environ)
        return self.inner(environ, start_response)

    def trusted(self, sent: Any) -> bool:
        """Whether ``sent`` is the boot's proxy token (never true without one)."""
        if not self._token or not isinstance(sent, str) or not sent:
            return False
        return hmac.compare_digest(sent.encode("utf-8", "replace"), self._token)

    def __call__(self, environ: dict[str, Any], start_response: Callable[..., Any]) -> Any:
        if chunked(environ):
            return refuse_chunked(environ, start_response)
        sent = environ.pop(PROXY_ENVIRON_KEY, None)
        if self.trusted(sent):
            return self._trusting(environ, start_response)
        return self._stripped(environ, start_response)


__all__ = [
    "ACTION_RULES",
    "CAPPED_RULES",
    "CROSS_SITE",
    "ForwardedHeaders",
    "LOGIN_REQUIRED",
    "MUST_CHANGE_OPEN",
    "OPEN",
    "PROXY_ENVIRON_KEY",
    "PROXY_HEADER",
    "ProxyTokenHeaders",
    "STATE_CHANGING",
    "LENGTH_REQUIRED",
    "TURN_RULES",
    "chunked",
    "refuse_chunked",
    "before_request",
    "foreign_origin",
    "is_open",
    "origin_allowed",
    "origin_of",
    "limit_request",
    "register",
    "strip_forwarded",
    "teardown_request",
]
