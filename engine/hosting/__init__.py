"""
Hosted Mode
===========

A small group plays the operator's stories in a browser, each with an
account (spec §6). OFF BY DEFAULT (``hosting.enabled: false``), and then this
package is never imported: ``FlaskScene.__init__`` imports it inside its
hosted branch only, and ``tests/test_local_mode_golden.py`` proves a local
run never loads it.

The package's own import is light (the config schema only): the web parts are
imported by ``install``, so the bus (``bus.py``) and the supervisor
(``supervisor/``), which serve no HTTP, do not load Flask.

``install(scene)`` is the whole switch. ``FlaskScene`` calls it right after
building Socket.IO and the host guard, and BEFORE ``blueprints()`` and
``register()``, so every route added afterwards is added behind the gate. In
order it:

1. validates the ``hosting:`` block (a closed schema, ``config.py``) and
   applies spec §6.7's refusals -- the studio (``CLOCKWORK_STUDIO=1``) and
   ``llm.mcp.enabled`` -- raising ``HostingConfigError`` naming the key, so
   the server does not start with a feature the operator asked for silently
   off;
2. warms the process (spec §5.2): every content cache
   (``warm_all_caches``), the quest grammar, the governance chain, the lore
   manager, the model server's backend, registry and client, and the Oracle,
   so no two first players build one at once;
3. sets the login cookie (spec §6.2): the key, ``clockwork_session``,
   ``HttpOnly``, ``SameSite=Lax``, ``Secure`` per ``hosting.cookie_secure``,
   ``hosting.session_days``, and ``SESSION_REFRESH_EACH_REQUEST = False`` (a
   response writes the cookie only when its request changed the session);
   It then takes this server's ``server-*.lock`` for the process's life,
   refusing to start while ``scripts/users.py adopt`` holds ``adopt.lock``;
4. registers the gate (``gate.py``: the login and the request's owner), the
   generic error handler (``errors.py``: a reference, never an exception's
   words, spec §6.6) and the socket guard (``sockets.py``: every handler
   ``FlaskScene.on`` registers from now on needs a live account, and acts as
   its owner), then mounts the login blueprint (``auth.py``);
5. answers the hosted public name in the host guard's allowlist
   (``hosting.public_origin``'s host), and puts ``ForwardedHeaders`` outside
   everything, Socket.IO's middleware included (``ProxyTokenHeaders`` under
   the supervisor, below);
6. sets ``scene.template_extras = {"hosting": PageExtras()}``, which the
   page's inline block reads for the logout form.

Under the supervisor (``CLOCKWORK_BUS_ADDR`` set, spec §14.2) it also
connects the bus (``connect_bus``), right after warming and before the
cookie key and the server lock are taken: the worker answers ``health`` on
the bus's request pool, ``drain`` (answer once no session holds its turn
lock, or say so when ``seconds`` run out; the pause itself is the
supervisor's queue's) and ``shutdown``, and exits non-zero if the link drops
(the lifeline); and (v0.20.0 T15, ``worker_ops.py``) the admin panel's
``worker.sessions.list``/``end``/``end_owner``, from its session store,
metadata only. It also sets the gate's lane backend to
``lanes_remote.RemoteLanes`` (v0.20.0 T11), so every lane ticket this worker
takes is the supervisor's, in one queue with every other story's. And
(v0.20.0 T17, ``metrics_emit.py``) it sets the engine's two metric hooks
(``default_scene.turn_metric``, ``SessionStore.on_event``) and starts the
child's metric sender and ERROR handler -- in a supervised child only, whose
``boot.prepare_child`` made the queue. The tokens are read once and
deleted from ``os.environ`` -- by the boot runner's first step
(``take_bus_environment``), before activation and warming, so nothing those
start inherits them.

A worker with a bus is reached only through the front door (v0.20.0 T12,
spec §14.5), so it:

- does NOT mount the login blueprint: login, logout and the account page are
  the front door's, and a player logs in once, there;
- reads the cookie through ``auth.ReadOnlySessionInterface`` and never
  writes it (spec §6.2's one writer);
- puts ``gate.ProxyTokenHeaders`` outside everything instead of
  ``ForwardedHeaders``: the front door's forwarded headers are trusted only
  on a request carrying the boot's proxy token, and deleted on any other.

Hosted mode also refuses ``POST /api/settings`` (``engine/api/settings.py``)
and answers ``/api/metrics`` 404 (``engine/api/metrics.py``); those modules
read ``hosting.enabled`` from the config themselves, without importing this
package.

Version: v0.7.0 [2026-10-06]
"""

from __future__ import annotations

import logging
import os
import threading
import time
from datetime import timedelta
from typing import Any, Optional

from engine.hosting.config import HostingConfigError, HostingSettings, load

logger = logging.getLogger(__name__)

#: Where the worker's bus client is kept on its Flask app (``app.extensions``).
BUS_EXTENSION = "clockwork_bus"

#: The bus client the boot runner made from the environment at its very first
#: step, before any story is activated or anything warms (``take_bus_environment``),
#: so the tokens leave ``os.environ`` before anything could start a grandchild
#: (T10 fix round 1). Set once on the main thread before serving; taken by
#: ``connect_bus``.
_bus_client: Optional[Any] = None


def take_bus_environment() -> Optional[Any]:
    """
    Read ``CLOCKWORK_BUS_ADDR`` and the bus and proxy tokens NOW, deleting the
    tokens from ``os.environ``, and keep the client for ``install`` to
    connect. The boot runner calls it before anything else. None without a bus.
    """
    global _bus_client
    from engine.hosting.bus import BusClient

    _bus_client = BusClient.from_environment()
    return _bus_client


def refuse_unsupported(cfg: Any) -> None:
    """
    Spec §6.7: what hosted mode does not run, refused at startup, naming the key.

    Raises:
        HostingConfigError: the studio is on, or ``llm.mcp.enabled`` is true.
    """
    if os.environ.get("CLOCKWORK_STUDIO") == "1":
        raise HostingConfigError(
            "CLOCKWORK_STUDIO",
            "the studio writes to games/ and resets every cache under other "
            "players' turns; it does not run in hosted mode (start without --studio)",
        )
    if cfg.get("llm.mcp.enabled", False):
        raise HostingConfigError(
            "llm.mcp.enabled",
            "the skills server opens its own port and edits LM Studio's mcp.json "
            "on this machine, built for one player; set it to false for hosted mode",
        )


def warm_process() -> None:
    """Build every lazily built process-wide object once, before serving (spec §5.2)."""
    from engine.agents.governance import get_governance
    from engine.game.quests import _ensure_grammar
    from engine.games.caches import warm_all_caches
    from engine.llm.backend import get_backend
    from engine.llm.registry import get_registry
    from engine.lore.manager import get_lore_manager
    from engine.telemetry.oracle import get_oracle

    warm_all_caches()
    _ensure_grammar()
    get_governance()
    get_lore_manager()
    get_backend().route_client()
    get_registry()
    get_oracle()


def configure_app(app: Any, settings: HostingSettings, key: str) -> None:
    """Spec §6.2's cookie settings on ``app``."""
    from engine.hosting.auth import COOKIE_NAME

    app.secret_key = key
    app.config.update(
        SESSION_COOKIE_NAME=COOKIE_NAME,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=settings.cookie_secure,
        PERMANENT_SESSION_LIFETIME=timedelta(days=settings.session_days),
        SESSION_REFRESH_EACH_REQUEST=False,
        # Spec §6.5: the largest request body (the voice upload's), refused
        # 413 by Werkzeug beyond it.
        MAX_CONTENT_LENGTH=settings.max_upload_mb * 1024 * 1024,
    )


def install_sessions(scene: Any) -> None:
    """
    Spec §5.4, for ``scene``'s session store (a scene without one is left
    alone): the release hook closes a released run's Socket.IO room, after
    telling it why (``session_ended``, v0.21.0 spec §6.5), so an old tab
    stops hearing the run before a new socket joins it; and a
    socket's ``disconnect`` runs the idle sweep. The sweep is the socket
    door's own after-disconnect step (``SocketDoor.after_disconnect``), run
    by the guard after whatever ``disconnect`` body is registered, so a
    story's own handler cannot remove it (T9 fix round 1); local mode's
    handler list is unchanged. Before the sweep, the socket's turn still
    waiting for a slot is called off (``cancel_waiting_turn``, T11 fix
    round 1).
    """
    store = getattr(scene, "store", None)
    if store is None:
        return

    def close_room(session_id: str, reason: str) -> None:
        # v0.21.0 (spec §6.5): the room hears WHY before it closes, with the
        # run's id, so a tab that has already left this run (it pressed Begin
        # or Load) ignores it. Closed whatever the emit did. Like every room
        # emit, the room's sockets are re-checked first, so one whose login
        # was revoked is dropped before it hears anything.
        try:
            room_check = getattr(scene, "_room_check", None)
            if room_check is not None:
                room_check(session_id)
            scene.socketio.emit("session_ended", {"reason": reason, "session_id": session_id}, to=session_id)
        finally:
            scene.socketio.close_room(session_id)

    store.on_release = close_room
    door = getattr(scene, "_socket_door", None)
    if door is not None:
        cancel_waiting = getattr(scene, "cancel_waiting_turn", None)

        def after_disconnect() -> None:
            # A turn this socket still had waiting for a slot is called off
            # first (T11 fix round 1): its place and, under the supervisor,
            # its account claim go at once. Then the idle sweep.
            if cancel_waiting is not None:
                from flask import request as current_request

                cancel_waiting(str(getattr(current_request, "sid", "") or ""))
            store.sweep_idle()

        door.after_disconnect = after_disconnect


#: How often a drain looks again for a running turn, in seconds.
DRAIN_POLL_SECONDS = 0.05


def drain(store: Any, seconds: float) -> bool:
    """
    The worker's part of a drain (spec §14.3). The supervisor has already
    paused this story's admissions in its queue, waited until the story
    holds no lane ticket and answered its queued turns busy (v0.20.0 T11:
    T10's worker-local pause is gone). What is left here is to let the
    requests still under a session's turn lock -- a refused turn writing its
    answer, a run being built -- finish: wait up to ``seconds`` for no
    session to hold its turn lock. True: drained. False: one still does.
    """
    deadline = time.monotonic() + max(0.0, float(seconds))
    waiter = threading.Event()
    while True:
        running = store.turns_running() if store is not None else 0
        if running == 0:
            logger.info("[hosting] Drained: no turn running (operation=drain)")
            return True
        if time.monotonic() >= deadline:
            logger.warning(
                "[hosting] Drain ran out with %d turn lock(s) held (operation=drain)",
                running,
            )
            return False
        waiter.wait(DRAIN_POLL_SECONDS)


def connect_bus(scene: Any) -> Optional[Any]:
    """
    Under the supervisor (``CLOCKWORK_BUS_ADDR`` set), connect this worker's
    bus client and register its handlers; None otherwise. The bus and proxy
    tokens are read once and deleted from ``os.environ`` here.

    Raises:
        HostingConfigError: the supervisor refused the token, or is not there.
    """
    global _bus_client
    from engine.hosting.bus import BusClient, BusError

    client, _bus_client = _bus_client, None
    if client is None:
        client = BusClient.from_environment()
    if client is None:
        return None
    from engine.hosting.lanes_remote import RemoteLanes

    store = getattr(scene, "store", None)
    lanes = RemoteLanes(client)
    from engine.hosting import metrics_emit

    # The health answer carries this child's dropped metrics (T17 fix round 1, M6).
    client.handle("health", lambda _args: {"metrics_dropped": metrics_emit.dropped})
    client.handle("drain", lambda args: {"drained": drain(store, float(args["seconds"]))})
    # T11 fix round 1: the supervisor took back a ticket held past
    # max_hold_seconds; acknowledging proves this worker is not hung.
    client.handle("lane.reclaimed", lambda args: lanes.reclaimed_ticket(str(args["ticket"])))
    try:
        client.connect()
    except (BusError, OSError) as exc:
        code = getattr(exc, "code", type(exc).__name__)
        raise HostingConfigError(
            "CLOCKWORK_BUS_ADDR",
            f"the supervisor's bus did not accept this worker ({code}); a hosted worker is "
            "started by the supervisor: python -m engine.hosting.supervisor",
        ) from None
    scene.app.extensions[BUS_EXTENSION] = client
    # One queue for every story (spec §14.4): this worker's lanes are the
    # supervisor's from now on. Set once, before anything is served.
    from engine.llm.gate import set_lane_backend

    set_lane_backend(lanes)
    logger.info("[hosting] Connected to the supervisor's bus (operation=connect_bus)")
    return client


def install(scene: Any) -> Any:
    """
    Turn ``scene`` (a ``FlaskScene``, before its routes) into a hosted server.

    Raises:
        HostingConfigError: the block is invalid, or a §6.7 feature is on.
    """
    from engine.config import get_config
    from engine.hosting.accounts import AccountError, AccountStore, hold_server_lock, secure_dir
    from engine.hosting.auth import EXTENSION, HostingState, PageExtras, auth_blueprint, secret_key
    from engine.hosting.errors import install_error_handler
    from engine.hosting.gate import ForwardedHeaders, ProxyTokenHeaders, register
    from engine.hosting.limits import ActionLimiter, LoginLimiter, TurnSlots, turn_slot_limit
    from engine.hosting.sockets import install as install_socket_guard
    from engine.persistence.storage import hosting_dir
    from engine.scenes.host_guard import host_of

    cfg = get_config()
    settings = load(cfg)
    refuse_unsupported(cfg)
    warm_process()
    # Before anything is held for the process's life: a worker the
    # supervisor does not accept stops here, holding nothing.
    bus = connect_bus(scene)
    if bus is not None:
        # The admin panel's live sessions (v0.20.0 T15): the supervisor's
        # worker.sessions.* requests, answered from this worker's store; and
        # (T17) its Oracle's numbers, through the projection.
        from engine.hosting import metrics_emit
        from engine.hosting.worker_ops import register as register_worker_ops

        register_worker_ops(bus, scene)
        # Metrics (v0.20.0 T17, spec §14.10): the engine's two emitters are
        # hooks set here (run_guarded's turn, the store's session events),
        # never imports of this package from engine code; the sender starts
        # only in a supervised child (boot.prepare_child made its queue).
        metrics_emit.install_hooks(scene)
        metrics_emit.attach(bus)

    directory = secure_dir(hosting_dir())
    app = scene.app
    configure_app(app, settings, secret_key(settings, directory))
    if bus is not None:
        # Spec §6.2: under the supervisor the front door is the cookie's one
        # writer; this worker reads it and never sends Set-Cookie.
        from engine.hosting.auth import ReadOnlySessionInterface

        app.session_interface = ReadOnlySessionInterface()
    try:
        server_lock = hold_server_lock(directory)
    except AccountError as exc:  # an adopt is running (accounts.ADOPT_RUNNING)
        raise HostingConfigError("scripts/users.py adopt", str(exc)) from None
    state = HostingState(
        settings=settings,
        accounts=AccountStore(
            directory,
            hash_slots=threading.BoundedSemaphore(settings.max_concurrent_logins),
        ),
        logins=LoginLimiter(
            settings.logins_per_minute, all_per_minute=settings.logins_per_minute_all
        ),
        actions=ActionLimiter(settings.actions_per_minute),
        server_lock=server_lock,
        turn_slots=TurnSlots(turn_slot_limit(settings.threads)),
    )
    app.extensions[EXTENSION] = state
    register(app)
    install_error_handler(app)
    install_socket_guard(scene, state.accounts, actions=state.actions, settings=settings)
    install_sessions(scene)
    store = getattr(scene, "store", None)
    if store is not None:
        # T15 fix round 2 (N3): a save outside a turn (a new run's first, a
        # manual one) is refused for an account that is disabled or gone,
        # read from the account store at the moment of the write.
        accounts = state.accounts

        def owner_open(owner: str) -> bool:
            found = accounts.get(owner)
            return found is not None and not found.disabled

        store.owner_open = owner_open
    if bus is None:
        # Standalone (T7-T9's shape): this process is the whole instance.
        # Under the supervisor the front door owns these pages (spec §14.5).
        app.register_blueprint(auth_blueprint())

    if settings.public_origin:
        from urllib.parse import urlsplit

        scene.host_guard.extra_hosts = frozenset(
            {host_of(urlsplit(settings.public_origin).netloc)}
        )
    if bus is not None:
        # One hop, the front door, trusted by its token (spec §7.3): never
        # hosting.trusted_proxies, which is the front door's own setting.
        app.wsgi_app = ProxyTokenHeaders(app.wsgi_app, bus.proxy_token)
    else:
        app.wsgi_app = ForwardedHeaders(app.wsgi_app, settings.trusted_proxies)
    scene.template_extras = {"hosting": PageExtras()}
    logger.info(
        "[hosting] Hosted mode installed (operation=install, public_origin=%s, "
        "trusted_proxies=%s, cookie_secure=%s)",
        settings.public_origin or "(same origin)",
        "the front door's proxy token" if bus is not None else settings.trusted_proxies,
        settings.cookie_secure,
    )
    return state


__all__ = [
    "BUS_EXTENSION",
    "HostingConfigError",
    "configure_app",
    "connect_bus",
    "drain",
    "install",
    "refuse_unsupported",
    "take_bus_environment",
    "warm_process",
]
