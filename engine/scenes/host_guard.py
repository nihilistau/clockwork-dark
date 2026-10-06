"""
Host Guard
==========

A Host-header allowlist for local mode (v0.20.0 T2 fix round 1, review
finding 10). Binding ``127.0.0.1`` keeps the NETWORK out, but not a hostile
page in the owner's own browser: with DNS rebinding, ``evil.example`` first
resolves to the attacker and then to ``127.0.0.1``, and the page's requests
reach the game with ``Host: evil.example``. Local mode has no login, so
every one of them could play, load and delete runs. A request whose Host is
not a name this server answers to is refused here, before Flask or Socket.IO
see it.

It wraps the WHOLE WSGI app (``FlaskScene`` installs it outside
Flask-SocketIO's middleware), so ``/socket.io/`` is covered as well as every
route. Allowed:

- ``localhost``, ``127.0.0.1`` and ``::1``, always;
- the host the scene binds (``scene.<name>.host``, or ``--host``);
- when that bind is a wildcard (``0.0.0.0``, ``::``: LAN play), any IP-literal
  Host and this machine's own name -- a LAN player types the machine's
  address, and a rebinding attack needs a DOMAIN, never an IP literal;
- in hosted mode, the host of ``hosting.public_origin`` (``extra_hosts``,
  set by ``engine.hosting.install``): the public name a reverse proxy
  passes on.

A request with no Host header at all (HTTP/1.0) is not a browser's, and
passes.

Cross-site writes (v0.20.0 T2 re-review, N1): a request that is not GET,
HEAD or OPTIONS is refused (403) when its ``Origin`` -- or, absent that, its
``Referer`` -- names a host outside the same allowlist, because a page on
another site can POST ``text/plain`` here with no preflight. A request with
neither header (curl, a script) passes. Every request on the Socket.IO path,
and every WebSocket upgrade, counts as state-changing whatever its method
(the polling handshake and the upgrade are GETs), and is refused when its
``Origin`` -- or, absent that, its ``Referer``, as JSONP polling sends --
is foreign (T3 fix round 1; the Referer, T5). The Socket.IO path is read off
the constructed server (``flask_scene.socketio_path``), so a custom one is
guarded too. That closes what Socket.IO's
``cors_allowed_origins="*"`` left open; only the recorded ``"*"`` value is
left, which the local-mode golden pins.

THE PORT IS NOT COMPARED. An ``Origin`` of ``http://localhost:8080`` is
answered to like ``http://localhost:5573``: the check is by HOST, which is
the web's own notion of a "site" (a page on another port of the same host is
the same site, and shares its cookies). A page served from this machine's
loopback on another port -- a local dev server, a notebook -- is therefore
trusted as the game's own. Refusing it would also refuse the owner's own
tooling, and anything that can serve a page on loopback can already reach the
game directly.
"""

from __future__ import annotations

import ipaddress
import logging
import re
import socket
from typing import Any, Callable, Iterable
from urllib.parse import urlsplit

from engine.scenes.spec import is_wildcard

logger = logging.getLogger(__name__)

#: Always answered to, whatever the bind.
LOOPBACK_NAMES = frozenset({"localhost", "127.0.0.1", "::1"})

#: What a refused request is told.
REFUSAL = (
    b"This game answers only to the names it is served under (Host header "
    b"not allowed). Open it at http://localhost or http://127.0.0.1, or set "
    b"scene.clockwork.host in config/local.yaml.\n"
)

#: What a state-changing request from another site is told.
CROSS_SITE_REFUSAL = (
    b"This game does not take changes from pages on other sites (Origin not "
    b"allowed). Play it at http://localhost or http://127.0.0.1.\n"
)

#: Methods that change nothing, so a cross-site one is not refused.
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


#: A bracketed IPv6 Host: ``[addr]`` and an optional ``:port``, and NOTHING
#: after it. ``[::1].evil.example`` is not this form, and must not be read as
#: ``::1`` (v0.20.0 T2 re-review nit).
_BRACKETED_RE = re.compile(r"\[([0-9a-f:.%a-z]*)\](?::[0-9]*)?")


def host_of(header: str) -> str:
    """
    The host part of a Host header, lowercased, without port or brackets.

    A header that starts with ``[`` but is not exactly ``[addr]`` or
    ``[addr]:port`` is answered whole (lowercased), which matches no name on
    the allowlist.
    """
    text = str(header or "").strip().lower()
    if text.startswith("["):
        match = _BRACKETED_RE.fullmatch(text)
        return match.group(1) if match else text
    if text.count(":") == 1:
        text = text.rsplit(":", 1)[0]
    return text.rstrip(".")


def origin_host(value: str) -> str:
    """
    The host an ``Origin`` or ``Referer`` names, as ``host_of`` spells it; ""
    when it names none (``null``, an opaque origin, is answered ``"null"``,
    which no allowlist holds).
    """
    text = str(value or "").strip()
    if not text:
        return ""
    if text.lower() == "null":
        return "null"
    try:
        netloc = urlsplit(text).netloc
    except ValueError:
        return text.lower()
    # Credentials never name the host: `http://localhost@evil.example/`.
    netloc = netloc.rsplit("@", 1)[-1]
    return host_of(netloc) if netloc else text.lower()


def _is_ip(text: str) -> bool:
    try:
        ipaddress.ip_address(text)
    except ValueError:
        return False
    return True


class HostGuard:
    """
    WSGI middleware: refuse a request whose Host is not on the allowlist.

    Args:
        app: The WSGI app it guards.
        bind_host: The host the scene binds; ``run`` updates it.
    """

    def __init__(
        self,
        app: Callable[..., Iterable[bytes]],
        bind_host: str,
        *,
        socket_path: str = "socket.io",
    ) -> None:
        self.app = app
        self.bind_host = bind_host
        #: Socket.IO's path as ``/<path>``, from the scene's SocketIO instance.
        self.socket_path = "/" + str(socket_path or "socket.io").strip("/")
        #: Further names answered to: hosted mode's public name
        #: (``hosting.public_origin``'s host, set by ``engine.hosting.install``),
        #: which a reverse proxy passes on as the Host. Empty in local mode.
        self.extra_hosts: frozenset[str] = frozenset()

    def is_socket(self, environ: dict[str, Any]) -> bool:
        """A request on the Socket.IO path, or any WebSocket upgrade."""
        path = str(environ.get("PATH_INFO", ""))
        if path == self.socket_path or path.startswith(self.socket_path + "/"):
            return True
        return str(environ.get("HTTP_UPGRADE", "")).strip().lower() == "websocket"

    def allowed(self, host: str) -> bool:
        """Whether a request's host (already ``host_of``'d) is answered to."""
        if host in LOOPBACK_NAMES or host in self.extra_hosts:
            return True
        bound = host_of(self.bind_host)
        if host == bound:
            return True
        if is_wildcard(self.bind_host):
            if _is_ip(host):
                return True
            name = socket.gethostname().lower()
            return host in {name, name.split(".", 1)[0]}
        return False

    def cross_site(self, environ: dict[str, Any]) -> str:
        """
        The foreign host a state-changing request came from, or "".

        A page on another site can POST to this server with no preflight
        (``Content-Type: text/plain`` is a "simple" request), and the owner's
        browser sends it: that started a game on the owner's model (v0.20.0
        T2 re-review, N1). Such a request carries an ``Origin`` (or, from an
        older client, a ``Referer``) naming the other site. A request that is
        not GET, HEAD or OPTIONS is refused when its ``Origin`` -- or, with no
        ``Origin``, its ``Referer`` -- is present and names a host this server
        does not answer to. A request with neither (curl, a script, the
        golden's test client) passes, as before.

        SOCKET.IO IS STATE-CHANGING WHATEVER THE METHOD (T3 fix round 1,
        review finding 1). Its polling handshake is a GET that hands back a
        readable ``sid``, and the WebSocket upgrade is a GET too; after either,
        a page can emit any event -- start a game, resume, play. So a request
        on the Socket.IO path, or any ``Upgrade: websocket`` request, is
        refused when it carries an ``Origin`` naming another host. A browser
        always sends ``Origin`` on a WebSocket handshake and on a cross-origin
        XHR; a same-origin polling GET and the golden's test client send none,
        and pass.

        WITH NO ``Origin``, THE ``Referer`` (T3 re-review, N2), on the socket
        path as everywhere else. Engine.IO's JSONP polling (``j=`` in the
        query) is loaded by a ``<script>`` tag, which sends no ``Origin`` --
        only a ``Referer`` naming the page -- so a foreign page could open a
        session that way. A socket request whose ``Referer`` names a foreign
        host is refused; one with neither header still passes.
        """
        method = str(environ.get("REQUEST_METHOD", "GET")).upper()
        if method in SAFE_METHODS and not self.is_socket(environ):
            return ""
        source = environ.get("HTTP_ORIGIN")
        if source is None:
            source = environ.get("HTTP_REFERER")
        if source is None:
            return ""
        host = origin_host(source)
        return "" if host and self.allowed(host) else (host or str(source))

    def _refuse(self, start_response: Callable[..., Any], body: bytes) -> list[bytes]:
        start_response(
            "400 Bad Request" if body is REFUSAL else "403 Forbidden",
            [("Content-Type", "text/plain; charset=utf-8"), ("Content-Length", str(len(body)))],
        )
        return [body]

    def __call__(self, environ: dict[str, Any], start_response: Callable[..., Any]) -> Any:
        header = environ.get("HTTP_HOST")
        if header is not None and not self.allowed(host_of(header)):
            logger.warning(
                "[host_guard] Refused a request for a host this game does not "
                "answer to (operation=__call__, host=%.80r, path=%.80r)",
                header,
                environ.get("PATH_INFO", ""),
            )
            return self._refuse(start_response, REFUSAL)
        foreign = self.cross_site(environ)
        if foreign:
            logger.warning(
                "[host_guard] Refused a state-changing request from another "
                "site (operation=__call__, from=%.80r, method=%s, path=%.80r)",
                foreign,
                environ.get("REQUEST_METHOD", ""),
                environ.get("PATH_INFO", ""),
            )
            return self._refuse(start_response, CROSS_SITE_REFUSAL)
        return self.app(environ, start_response)


__all__ = [
    "CROSS_SITE_REFUSAL",
    "HostGuard",
    "LOOPBACK_NAMES",
    "REFUSAL",
    "SAFE_METHODS",
    "host_of",
    "origin_host",
]
