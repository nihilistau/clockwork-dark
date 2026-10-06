"""
The Front Door
==============

Under the supervisor, the one process players reach (spec §14.1, §14.5): a
small Flask app on the default scene's ``host``/``port`` (config) that activates no story,
builds no engine and holds no ``SessionStore``. It owns:

- ``GET /api/health`` (its own: 200 while its bus link to the supervisor is
  up, 503 otherwise);
- ``/login``, ``/logout``, ``/account`` (T7's blueprint, ``auth.py``, mounted
  HERE and on no worker: a player logs in once, at the front door);
- ``GET /stories``, ``POST /stories/<slug>`` and ``GET /`` (the picker and the
  choice in the cookie, ``stories.py``);
- ``/admin`` and everything under it: the admin panel (v0.20.0 T14,
  ``engine/hosting/admin/``), mounted HERE and on no worker, behind its own
  guard; an unknown ``/admin`` path is a 404 after that guard, so it never
  falls through to a worker;
- ``/static/hosting/...``, its pages' own stylesheet;

and passes every other request to the chosen story's worker: HTTP through the
proxy (``proxy.py``), Socket.IO's long polling included, and a Socket.IO
WebSocket through the relay (``ws_relay.py``, v0.20.0 T13), every player's
path, since the client does not fall back to polling.

``create_frontdoor_app()`` requires ``hosting.enabled`` and the supervisor's
bus (``CLOCKWORK_BUS_ADDR``, read and its tokens deleted by the boot runner's
first step), or raises ``HostingConfigError`` naming the key. It:

1. sets spec §6.2's cookie (the same key file every child reads, made by the
   supervisor before any child started) with ``SESSION_REFRESH_EACH_REQUEST =
   False``: the cookie is written ONLY by a request that changed the session
   -- login, ``/account``, ``POST /stories/<slug>``, the first ``GET /`` that
   picks the one ready story -- never by a proxied request, so a response in
   flight can never set back a choice or a new epoch made meanwhile;
2. takes this process's server lock (``users.py adopt`` refuses while it
   runs: the account page writes ``users.json``);
3. registers the gate (``gate.py``: Origin, ``authenticate``, the open list)
   and the generic error handler, then mounts the login blueprint, the
   picker, the admin panel and the catch-all proxy;
4. wraps the WSGI app: ``ForwardedHeaders`` (``hosting.trusted_proxies``'
   ``ProxyFix``, then every ``X-Forwarded-*`` header deleted) outside the
   host guard (``engine/scenes/host_guard.py``: the names the front door
   answers to, and a foreign Origin on the Socket.IO path) outside the
   WebSocket relay (``ws_relay.py``) outside Flask (spec §7.3's order). One
   ``limits.LongHolds`` of ``hosting.threads - RESERVED_THREADS`` places is
   shared by the relays, the proxy's polling ``GET``s and its HTTP turns.
   This is the only ``ProxyFix`` of the instance: a worker trusts the front
   door's replaced headers by its proxy token alone (spec §7.3);
5. connects the bus: ``health`` and ``drain`` (nothing to drain: it runs no
   turn) are answered, ``stories.changed`` replaces the story table, the
   child's metric sender starts (v0.20.0 T17: its ``login`` and ``error``
   metrics), and the table is read once with ``stories.list``. A lost link ends the process
   (the lifeline): a front door that cannot reach the supervisor serves
   nobody.

The front door's state lives on the app (``app.extensions[FRONTDOOR_EXTENSION]``,
a ``FrontDoor``): the bus client, the story table, the proxy (one pooled
``httpx.Client``) and the host guard. Nothing is module-level.

Version: v0.4.0 [2026-10-06]
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from engine.hosting.config import HostingConfigError

logger = logging.getLogger(__name__)

#: Where the front door's state is kept on its Flask app.
FRONTDOOR_EXTENSION = "hosting_frontdoor"

#: How long the first ``stories.list`` may take.
TABLE_READ_SECONDS = 10.0

_HERE = Path(__file__).resolve().parent


@dataclass
class FrontDoor:
    """What the front door keeps on its app."""

    bus: Any
    table: Any
    proxy: Any
    host_guard: Any
    #: The WebSocket relay (v0.20.0 T13, ``ws_relay.py``).
    relay: Any = None
    #: The long holds: relays, polls and HTTP turns (``limits.LongHolds``).
    holds: Any = None


def frontdoor(app: Any = None) -> FrontDoor:
    """The app's ``FrontDoor`` (``current_app`` by default)."""
    if app is None:
        from flask import current_app

        app = current_app
    return app.extensions[FRONTDOOR_EXTENSION]


def _take_bus(bus: Any) -> Any:
    """The bus client: ``bus`` when given, else the boot runner's, else the environment's."""
    if bus is not None:
        return bus
    import engine.hosting as hosting_pkg
    from engine.hosting.bus import BusClient

    client, hosting_pkg._bus_client = hosting_pkg._bus_client, None
    if client is None:
        client = BusClient.from_environment()
    return client


def connect(bus: Any, table: Any) -> None:
    """
    Register the front door's bus handlers, connect, and read the story table
    once (``stories.list``). Raises ``HostingConfigError`` when the
    supervisor does not accept it.
    """
    from engine.hosting.bus import BusError, FRONTDOOR

    def changed(args: dict[str, Any]) -> dict[str, Any]:
        if table.replace(args.get("stories") or [], int(args.get("seq", 0))):
            logger.info(
                "[frontdoor] Story table updated (operation=stories.changed, seq=%s, states=%s)",
                args.get("seq"),
                ",".join(f"{r['slug']}:{r['state']}" for r in table.rows()),
            )
        return {}

    from engine.hosting import metrics_emit as emitted

    # The health answer carries the front door's dropped metrics (T17 fix round 1, M6).
    bus.handle("health", lambda _args: {"metrics_dropped": emitted.dropped})
    bus.handle("drain", lambda _args: {"drained": True})
    bus.handle("stories.changed", changed)
    try:
        hello = bus.connect()
    except (BusError, OSError) as exc:
        code = getattr(exc, "code", type(exc).__name__)
        raise HostingConfigError(
            "CLOCKWORK_BUS_ADDR",
            f"the supervisor's bus did not accept the front door ({code}); the front door is "
            "started by the supervisor: python -m engine.hosting.supervisor",
        ) from None
    if hello.get("role") not in (None, FRONTDOOR):
        raise HostingConfigError("CLOCKWORK_BUS_TOKEN", "is not the front door's")
    # Its metrics (v0.20.0 T17: logins, errors) go to the supervisor from
    # now on -- in a supervised child only, whose prepare_child made the queue.
    from engine.hosting import metrics_emit

    metrics_emit.attach(bus)
    try:
        reply = bus.request("stories.list", timeout=TABLE_READ_SECONDS)
    except BusError as exc:
        raise HostingConfigError(
            "CLOCKWORK_BUS_ADDR", f"the supervisor did not give the story table ({exc.code})"
        ) from None
    rows = [r for r in reply.get("stories") or [] if r.get("role", "worker") == "worker"]
    table.replace(rows, int(reply.get("seq", 0)))


def create_frontdoor_app(bus: Any = None) -> Any:
    """
    Build the front door (see the module docstring). ``bus``: a ``BusClient``
    not yet connected (the boot runner's by default).

    Raises:
        HostingConfigError: hosting is off, there is no bus, or the
            supervisor refused it.
    """
    from flask import Flask, jsonify

    from engine.config import get_config
    from engine.hosting import configure_app
    from engine.hosting.accounts import AccountError, AccountStore, hold_server_lock, secure_dir
    from engine.hosting.admin import install as install_admin
    from engine.hosting.auth import EXTENSION, HostingState, auth_blueprint, secret_key
    from engine.hosting.config import load
    from engine.hosting.errors import install_error_handler
    from engine.hosting.frontdoor import gate as door_gate
    from engine.hosting.frontdoor.proxy import SOCKET_PATH, Proxy, register as register_proxy
    from engine.hosting.frontdoor.stories import StoryTable, stories_blueprint, titles_for
    from engine.hosting.frontdoor.ws_relay import WebSocketRelay
    from engine.hosting.gate import ForwardedHeaders
    from engine.hosting.limits import LoginLimiter, LongHolds, TurnSlots, turn_slot_limit
    from engine.persistence.storage import hosting_dir
    from engine.scenes.flask_scene import HOSTED_SOCKET_BUFFER_BYTES
    from engine.scenes.host_guard import HostGuard, host_of
    from engine.scenes.spec import DEFAULT_SCENE_NAME, scene_host

    cfg = get_config()
    settings = load(cfg)
    if not settings.enabled:
        raise HostingConfigError(
            "hosting.enabled",
            "is false: the front door serves hosted mode only; local single-player is served by launcher.py",
        )
    client = _take_bus(bus)
    if client is None:
        raise HostingConfigError(
            "CLOCKWORK_BUS_ADDR",
            "is not set: the front door is started by the supervisor (python -m engine.hosting.supervisor)",
        )

    app = Flask(
        "hosting_frontdoor",
        static_folder=str(_HERE / "static"),
        static_url_path="/static/hosting",
        template_folder=str(_HERE / "templates"),
    )
    directory = secure_dir(hosting_dir())
    configure_app(app, settings, secret_key(settings, directory))
    try:
        server_lock = hold_server_lock(directory)
    except AccountError as exc:
        raise HostingConfigError("scripts/users.py adopt", str(exc)) from None
    app.extensions[EXTENSION] = HostingState(
        settings=settings,
        accounts=AccountStore(directory, hash_slots=threading.BoundedSemaphore(settings.max_concurrent_logins)),
        logins=LoginLimiter(settings.logins_per_minute, all_per_minute=settings.logins_per_minute_all),
        server_lock=server_lock,
    )

    table = StoryTable(settings.stories, titles_for(settings.stories))
    # One count for everything that holds a pool thread for long (T13):
    # relayed WebSockets, polling GETs and HTTP turns, so RESERVED_THREADS
    # are always left for login, the picker and the static files.
    holds = LongHolds(turn_slot_limit(settings.threads), per_account=settings.max_connections_per_account)
    proxy = Proxy(
        proxy_token=client.proxy_token,
        # The longest legitimate turn (fix round 1): its wait for a place,
        # then its own deadline from admission (T11).
        turn_seconds=float(settings.queue_wait_seconds + settings.turn_deadline_seconds),
        slots=TurnSlots(turn_slot_limit(settings.threads), pool=holds),
        body_seconds=float(settings.body_read_seconds),
        holds=holds,
    )

    app.before_request(door_gate.before_request)
    install_error_handler(app)

    @app.get("/api/health")
    def health() -> Any:
        if client.connected:
            return jsonify({"status": "ok", "role": "frontdoor"})
        return jsonify({"status": "down", "role": "frontdoor"}), 503

    # The admin panel (v0.20.0 T14): its guard runs after the gate above,
    # which passes every /admin path to it; an unknown admin path is a 404
    # after the guard, never a worker's.
    install_admin(app)
    app.register_blueprint(auth_blueprint())

    def forward_page(slug: str, row: dict[str, Any]) -> Any:
        from engine.hosting.frontdoor.gate import admission

        found = admission()
        return proxy.forward(slug, row, page=True, account=str(getattr(found.account, "id", "")))

    app.register_blueprint(stories_blueprint(table, forward_page))
    register_proxy(app, proxy)

    relay = WebSocketRelay(
        app.wsgi_app,
        app,
        holds=holds,
        max_message_size=HOSTED_SOCKET_BUFFER_BYTES,
        public_origin=settings.public_origin,
        proxy_token=client.proxy_token,
        socket_path=SOCKET_PATH,
    )
    guard = HostGuard(relay, scene_host(DEFAULT_SCENE_NAME), socket_path="socket.io")
    if settings.public_origin:
        from urllib.parse import urlsplit

        guard.extra_hosts = frozenset({host_of(urlsplit(settings.public_origin).netloc)})
    # Spec §7.3's order: ProxyFix (and the forwarded headers deleted), the
    # host guard, the WebSocket door, then Flask.
    app.wsgi_app = ForwardedHeaders(guard, settings.trusted_proxies)  # type: ignore[method-assign]
    app.extensions[FRONTDOOR_EXTENSION] = FrontDoor(
        bus=client, table=table, proxy=proxy, host_guard=guard, relay=relay, holds=holds
    )
    # A password change, disable, reset, role change or removal made HERE (the
    # /account page, the admin panel) closes that account's relayed
    # connections at once (T13 fix round 1, I1), without waiting on them (T14).
    app.extensions[EXTENSION].accounts.on_revoke(relay.revoke)

    connect(client, table)
    logger.info(
        "[frontdoor] Front door built (operation=create_frontdoor_app, stories=%s, "
        "trusted_proxies=%d, public_origin=%s)",
        ",".join(settings.stories),
        settings.trusted_proxies,
        settings.public_origin or "(same origin)",
    )
    return app


__all__ = ["FRONTDOOR_EXTENSION", "FrontDoor", "connect", "create_frontdoor_app", "frontdoor"]
