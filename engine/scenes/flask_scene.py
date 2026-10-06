"""
FlaskScene Base
===============

Minimal Flask + Socket.IO scene host (CosySim pattern).

Subclasses supply two things:

    blueprints()   route sets to mount -- the engine's shared API, plus
                   whatever Blueprint the active story declares
    register()     the scene's own routes and socket handlers

Blueprints are mounted BEFORE ``register()`` runs, so a subclass can still
claim a rule a blueprint left free, and a story blueprint that fails to import
costs its own screens rather than the whole scene.

HOSTED MODE (v0.20.0, ``hosting.enabled``) is decided here, at construction:
Socket.IO's CORS value and buffer size come from config
(``socketio_options``), and ``engine.hosting.install(self)`` runs before
``blueprints()`` and ``register()``, imported inside that branch so a local
run never loads the package.

SOCKET HANDLERS are registered through ``self.on(event)``, never
``@socketio.on``: in local mode it IS ``socketio.on``; in hosted mode it wraps
each handler in the socket guard ``install`` set (spec §6.3).

Version: v0.2.0 [2026-08-08]
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable, Optional

from flask import Blueprint, Flask, jsonify
from flask_socketio import SocketIO

from engine.config import hosting_enabled
from engine.scenes.host_guard import HostGuard
from engine.scenes.spec import exposure_warning, scene_host, scene_port

logger = logging.getLogger(__name__)


def socketio_path(socketio: SocketIO) -> str:
    """
    The path a constructed ``SocketIO`` actually serves, as ``engineio`` holds
    it (``/socket.io/``).

    Read off the middleware Flask-SocketIO installs, never off
    ``server_options``: ``init_app`` POPS ``path`` from ``server_options``
    before it builds that middleware, so a custom path read there came back
    as the default and was never guarded (v0.20.0 T3 re-review, N1). Falls
    back to ``server_options`` and then the default only for an instance with
    no middleware (one not yet bound to an app).
    """
    middleware = getattr(socketio, "sockio_mw", None)
    path = getattr(middleware, "engineio_path", None)
    if not path:
        path = socketio.server_options.get("path") or socketio.server_options.get("resource")
    return str(path or "socket.io")


#: Socket.IO's largest accepted message in hosted mode, in bytes (spec §6.5).
HOSTED_SOCKET_BUFFER_BYTES = 65536


def socketio_options(hosted: bool) -> dict[str, Any]:
    """
    ``SocketIO``'s options, chosen from config at construction (spec §6.3).

    Local mode: ``cors_allowed_origins="*"`` and nothing else, exactly as
    every release has built it (the local-mode golden pins it); the host
    guard refuses a foreign Origin on the Socket.IO path instead. Hosted
    mode: ``[hosting.public_origin]`` when it is set, else ``None``, which is
    python-engineio's SAME-ORIGIN ONLY. Never ``[]``: that DISABLES the check.
    Hosted also caps a message at ``HOSTED_SOCKET_BUFFER_BYTES``.
    """
    if not hosted:
        return {"cors_allowed_origins": "*", "async_mode": "threading"}
    from engine.config import get_config

    origin = str(get_config().get("hosting.public_origin", "") or "").strip()
    return {
        "cors_allowed_origins": [origin] if origin else None,
        "async_mode": "threading",
        "max_http_buffer_size": HOSTED_SOCKET_BUFFER_BYTES,
    }


class FlaskScene:
    """
    Base scene server wiring Flask app and Socket.IO.

    Subclasses register routes and socket handlers in ``register``.
    """

    def __init__(
        self,
        *,
        name: str,
        static_folder: Path,
        template_folder: Path,
        testing: bool = False,
    ) -> None:
        self.name = name
        self.testing = testing
        self.app = Flask(
            name,
            static_folder=str(static_folder),
            static_url_path="/static",
            template_folder=str(template_folder),
        )
        self.app.config["TESTING"] = testing
        #: What the page template gets besides ``scene``: ``{}`` in local mode
        #: (so ``GET /`` is byte-identical), ``{"hosting": ...}`` once
        #: ``engine.hosting.install`` has run.
        self.template_extras: dict[str, Any] = {}
        #: Hosted mode's socket guard, ``(event, namespace, handler) ->
        #: guarded handler``, set by ``engine.hosting.install``; None in local
        #: mode, where ``on`` registers handlers as they are.
        self._socket_guard: Optional[Callable[[str, str, Callable[..., Any]], Callable[..., Any]]] = None
        #: ``(namespace, event)`` of every handler ``on`` registered through
        #: the guard. ``tests/test_hosting_sockets.py`` asserts it covers every
        #: handler Socket.IO holds.
        self.guarded_events: set[tuple[str, str]] = set()
        #: Hosted mode's room check, ``(room) -> None``, called before every
        #: emit to a run's room: it disconnects any socket in the room whose
        #: login is no longer live (``engine/hosting/sockets.py``). None in
        #: local mode, where an emit is exactly the emit.
        self._room_check: Optional[Callable[[str], None]] = None
        hosted = hosting_enabled()
        self.socketio = SocketIO(self.app, **socketio_options(hosted))
        # Outside Flask-SocketIO's middleware, so /socket.io/ is guarded too:
        # loopback keeps the network out, this keeps a DNS-rebinding page in
        # the owner's own browser out (engine/scenes/host_guard.py).
        # The Socket.IO path is passed in, not assumed: every request on it
        # (and every WebSocket upgrade) is guarded as state-changing.
        self.host_guard = HostGuard(
            self.app.wsgi_app,
            scene_host(name),
            socket_path=socketio_path(self.socketio),
        )
        self.app.wsgi_app = self.host_guard  # type: ignore[method-assign]
        if hosted:
            # HOSTED MODE, AND ONLY HERE: the package is imported inside this
            # branch, so a local run never loads it. Installed before any
            # route exists, so every route -- the engine's, the story's, the
            # scene's -- is added behind its gate (spec §6.3).
            from engine.hosting import install

            install(self)
        self._register_health()
        for blueprint in self.blueprints():
            if blueprint is not None:
                self.app.register_blueprint(blueprint)
        self.register()

    def on(self, event: str, namespace: Optional[str] = None) -> Callable[..., Any]:
        """
        THE one way a socket handler is registered (spec §6.3).

        Local mode: ``self.socketio.on(event, namespace)`` itself, so the
        registered handlers (and the local-mode golden's handler list) are
        exactly what ``@socketio.on`` made. Hosted mode: the handler is
        wrapped in the socket guard ``engine.hosting.install`` set (a live
        account on connect and on every event, the owner set for the body,
        the limits), and the event recorded in ``guarded_events``.
        """
        guard = self._socket_guard
        if guard is None:
            return self.socketio.on(event, namespace)
        space = namespace or "/"

        def decorator(handler: Callable[..., Any]) -> Callable[..., Any]:
            self.socketio.on(event, namespace)(guard(event, space, handler))
            self.guarded_events.add((space, event))
            return handler

        return decorator

    def _register_health(self) -> None:
        @self.app.get("/api/health")
        def health() -> Any:
            return jsonify({"status": "ok", "scene": self.name})

    def blueprints(self) -> list[Blueprint]:
        """Override to declare route sets mounted before ``register()``."""
        return []

    def register(self) -> None:
        """Override to add scene routes and socket handlers."""

    def run(
        self,
        *,
        host: str = "127.0.0.1",
        port: Optional[int] = None,
        debug: bool = False,
    ) -> None:
        """
        Start the scene server.

        ``port`` defaults from ``scene.<name>.port`` rather than a literal.
        The number had four homes and config was only one of them.

        The host guard answers to the host actually bound (a ``--host`` beats
        the config it was built from), and a bind other than loopback is
        logged as the WARNING the doctor and the launcher give.
        """
        self.host_guard.bind_host = host
        resolved_port = port if port is not None else scene_port(self.name)
        warning = exposure_warning(host, resolved_port)
        if warning:
            logger.warning("[scene] Bound to %s: %s", host, warning)
        self.socketio.run(
            self.app,
            host=host,
            port=resolved_port,
            debug=debug,
            allow_unsafe_werkzeug=True,
        )
