"""
Hosted Mode: Booting a Worker or the Front Door
===============================================

``build_worker_app()`` builds one story's hosted worker (spec §7.1), shared by
the development runner below and, from v0.20.0 T13, ``engine/hosting/wsgi.py``
under gunicorn:

1. reads ``CLOCKWORK_GAME``;
2. activates that story (``registry.activate``), before any content import,
   as ``launcher.py`` does;
3. requires ``hosting.enabled``, refusing to serve local mode ("local mode is
   served by launcher.py ...") before it builds anything;
4. requires the supervisor's bus (``require_bus``: ``CLOCKWORK_BUS_ADDR``,
   v0.20.0 T13), refusing without it, so a worker never serves with lanes of
   its own beside the shared queue;
5. builds ``create_app()``, whose ``install()`` validates the block, applies
   the §6.7 refusals, warms every cache and connects the bus, so the worker
   either boots ready or does not boot.

UNDER GUNICORN (v0.20.0 T13) the same build runs in ``engine/hosting/wsgi.py``
(and the front door's in ``engine/hosting/frontdoor/wsgi.py``), inside the
gunicorn WORKER, and ``deploy/gunicorn.conf.py``'s ``post_worker_init`` hook
calls ``report_ready`` with the port gunicorn bound: the bus belongs to that
worker, and a ``shutdown`` or a lost link stops the gunicorn master with it
(``stop_master``) -- by the master's IDENTITY, its pid and creation time
noted at ``ready``, never a bare pid (v0.20.0 T15 fix round 2:
``engine/hosting/process_identity.py``).

``python -m engine.hosting.boot --role worker`` is the development runner the
supervisor starts on Windows and wherever gunicorn is absent (spec §14.3):
Werkzeug on ``127.0.0.1:0``, a port the OS picks and the worker reports to the
supervisor in its ``ready`` message, after spec §7.2's WARNING. Its first
step (``prepare_child``) takes the bus tokens out of the environment and
ignores Ctrl+Break, before anything is activated or warmed. A supervised
worker's host guard answers to the names the FRONT DOOR answers to
(``scene.clockwork.host``, the public origin's host), not only to its own
loopback bind: every request it serves came through the front door with the
player's ``Host`` kept (spec §14.5).

``python -m engine.hosting.boot --role frontdoor`` (v0.20.0 T12) runs the
front door (``engine/hosting/frontdoor/``) under Werkzeug on
``scene.clockwork.host``/``port``, the one port players reach, and reports
the port it bound in ``ready``. It activates no story.

Version: v0.6.0 [2026-10-06]
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
from typing import Any, Callable, Optional

from engine.hosting.config import HostingConfigError

logger = logging.getLogger(__name__)

#: Spec §7.2's WARNING (``launcher.py`` says the same in local mode's process).
HOSTED_DEV_SERVER_WARNING = (
    "hosted mode under the development server: for a real deployment run "
    "`python -m engine.hosting.supervisor` on Linux, or the Docker image"
)

#: Where a worker listens: loopback, on a port the OS picks.
WORKER_HOST = "127.0.0.1"


def build_worker_app(*, llm_fn: Any = None) -> tuple[Any, Any]:
    """
    Spec §7.1's steps 1-3 and 5. Returns ``(scene, app)``. ``llm_fn`` is
    ``create_app``'s (the test suite's scripted model; None in production).

    Raises:
        HostingConfigError: no story named, hosting off, or ``install`` refused.
    """
    from engine.config import hosting_enabled
    from engine.games.registry import ActivationError, activate

    slug = str(os.environ.get("CLOCKWORK_GAME", "") or "").strip()
    if not slug:
        raise HostingConfigError("CLOCKWORK_GAME", "names no story; the supervisor sets it per worker")
    try:
        activate(slug)
    except ActivationError as exc:
        raise HostingConfigError("hosting.stories", f"{slug!r} will not activate: {exc}") from None
    if not hosting_enabled():
        raise HostingConfigError(
            "hosting.enabled",
            "is false: local mode is served by launcher.py; this runner serves hosted mode only",
        )
    require_bus()
    from engine.scenes.default_scene import create_app

    return create_app(llm_fn=llm_fn)


def require_bus() -> None:
    """
    Spec §7.1 step 4: a hosted worker or front door is started by the
    supervisor, which hands it the bus (``CLOCKWORK_BUS_ADDR``, taken by
    ``prepare_child``); without it, refuse, so production has one shape and
    nothing serves with lanes of its own beside the shared queue.

    Raises:
        HostingConfigError: no bus.
    """
    import engine.hosting as hosting_pkg
    from engine.hosting.bus import BUS_ADDR_ENV

    if hosting_pkg._bus_client is None and not str(os.environ.get(BUS_ADDR_ENV, "") or "").strip():
        raise HostingConfigError(
            BUS_ADDR_ENV,
            "is not set: a hosted worker is started by the supervisor: python -m engine.hosting.supervisor",
        )


def configure_logging() -> None:
    """INFO to stderr, ``httpx``'s chatter at WARNING: every child's log shape."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def report_ready(app: Any, port: int, *, master_pid: int = 0) -> None:
    """
    Tell the supervisor this child serves on ``port`` (its ``ready``): the
    front door's or a worker's ``app``, whichever this is. The front door's
    host guard also takes the host it binds (as ``serve_frontdoor`` sets it).

    ``master_pid`` (gunicorn, v0.20.0 T13): this process is a gunicorn
    WORKER, the bus is its, and the process the supervisor started is the
    MASTER. A ``shutdown`` from the supervisor, or a lost link, then also
    stops the master (``SIGTERM``, a graceful stop), so it does not start a
    new worker that would serve without a bus -- a new worker's ``hello``
    would be refused anyway (single-use tokens), which ends the master too.
    """
    from engine.hosting import BUS_EXTENSION
    from engine.hosting.bus import LIFELINE_EXIT_CODE
    from engine.hosting.frontdoor import FRONTDOOR_EXTENSION

    door = app.extensions.get(FRONTDOOR_EXTENSION)
    if door is not None:
        from engine.scenes.spec import DEFAULT_SCENE_NAME, scene_host

        door.host_guard.bind_host = scene_host(DEFAULT_SCENE_NAME)
        bus = door.bus
    else:
        bus = app.extensions.get(BUS_EXTENSION)
    if bus is None:
        raise HostingConfigError(
            "CLOCKWORK_BUS_ADDR",
            "is not set: a hosted worker is started by the supervisor: python -m engine.hosting.supervisor",
        )
    if master_pid > 0:
        # The master's IDENTITY, noted now, while it is certainly running and
        # ours (T15 fix round 2, N1): by the time the link is lost it may be
        # gone and its pid another process's.
        from engine.hosting.process_identity import identify

        master = identify(master_pid)
        parent = os.getppid()
        bus.on_shutdown = lambda: stop_master(master, 0, parent=parent)
        bus.on_lost = lambda: stop_master(master, LIFELINE_EXIT_CODE, parent=parent)
    bus.request("ready", {"port": int(port)})
    logger.info("[hosting] Serving under gunicorn (operation=serve, port=%d)", int(port))


def stop_master(master: Any, code: int, *, parent: Optional[int] = None) -> None:
    """
    SIGTERM the gunicorn master (a graceful stop), then leave this worker at
    once. ``master`` is its ``process_identity.Identity``, noted when this
    worker reported ``ready`` (T15 fix round 2, N1): it is signalled ONLY if
    the process holding its pid still has that creation time, checked and
    signalled through one handle (``process_identity.terminate``). It is
    never signalled -- only logged -- when its identity is unknown, its pid
    is 1, or, on POSIX, this worker's parent is no longer the parent it had
    then (``parent``: the master died and the worker was re-parented, so the
    pid may by now be anyone's). A master already gone needs no signal.
    """
    from engine.hosting import bus as bus_module
    from engine.hosting.process_identity import terminate

    pid = int(getattr(master, "pid", 0) or 0)
    reparented = os.name == "posix" and parent is not None and os.getppid() != parent
    if pid <= 1 or getattr(master, "created", None) is None or reparented:
        logger.warning(
            "[hosting] The gunicorn master was not signalled: it cannot be verified "
            "(operation=stop_master, pid=%d, reparented=%s)",
            pid,
            reparented,
        )
    elif not terminate(master, signal.SIGTERM):
        logger.warning(
            "[hosting] The gunicorn master was not signalled: gone, or its pid is another "
            "process's now (operation=stop_master, pid=%d)",
            pid,
        )
    bus_module._exit_process(code)


def serve_worker(
    build: Callable[[], tuple[Any, Any]] = build_worker_app,
    *,
    make_server: Optional[Callable[..., Any]] = None,
) -> int:
    """
    Build the worker, bind ``127.0.0.1:0``, report the port in ``ready`` and
    serve until the process ends (a bus ``shutdown``, or the lifeline).
    """
    from engine.hosting import BUS_EXTENSION

    if make_server is None:
        from werkzeug.serving import make_server as werkzeug_server

        make_server = werkzeug_server
    print(f"WARNING: {HOSTED_DEV_SERVER_WARNING}", flush=True)
    scene, app = build()
    host_guard = getattr(scene, "host_guard", None)
    if host_guard is not None and app.extensions.get(BUS_EXTENSION) is None:
        # Standalone: it answers to the loopback it binds. A supervised
        # worker keeps the front door's names (the scene's configured host,
        # built in), because the front door keeps the player's Host.
        host_guard.bind_host = WORKER_HOST
    server = make_server(WORKER_HOST, 0, app, threaded=True)
    port = int(server.server_port)
    bus = app.extensions.get(BUS_EXTENSION)
    if bus is not None:
        bus.request("ready", {"port": port})
    logger.info("[hosting] Worker serving (operation=serve, host=%s, port=%d)", WORKER_HOST, port)
    try:
        server.serve_forever()
    finally:
        server.server_close()
    return 0


def serve_frontdoor(
    build: Optional[Callable[[], Any]] = None,
    *,
    make_server: Optional[Callable[..., Any]] = None,
) -> int:
    """
    Build the front door, bind ``scene.clockwork.host``/``port``, report the
    port it got in ``ready``, and serve until the process ends (a bus
    ``shutdown``, or the lifeline). ``build`` returns the Flask app
    (``frontdoor.create_frontdoor_app`` by default).
    """
    from engine.hosting.frontdoor import FRONTDOOR_EXTENSION, create_frontdoor_app
    from engine.scenes.spec import DEFAULT_SCENE_NAME, scene_host, scene_port

    if make_server is None:
        from werkzeug.serving import make_server as werkzeug_server

        make_server = werkzeug_server
    print(f"WARNING: {HOSTED_DEV_SERVER_WARNING}", flush=True)
    app = (build or create_frontdoor_app)()
    door = app.extensions[FRONTDOOR_EXTENSION]
    host = scene_host(DEFAULT_SCENE_NAME)
    server = make_server(host, frontdoor_port(scene_port(DEFAULT_SCENE_NAME)), app, threaded=True)
    port = int(server.server_port)
    door.host_guard.bind_host = host
    door.bus.request("ready", {"port": port})
    logger.info("[hosting] Front door serving (operation=serve, host=%s, port=%d)", host, port)
    try:
        server.serve_forever()
    finally:
        server.server_close()
    return 0


def frontdoor_port(configured: int) -> int:
    """
    The port the front door binds: ``scene.clockwork.port`` (``configured``,
    as ``scene_port`` reads it), except that an explicit ``0`` there means a
    port the OS picks (``scene_port`` reads 0 as unset): how the test suite's
    instances bind, and reported in ``ready`` like any other.
    """
    from engine.config import get_config

    raw = get_config().get("scene.clockwork.port", None)
    if isinstance(raw, int) and not isinstance(raw, bool) and raw == 0:
        return 0
    return int(configured)


def prepare_child() -> None:
    """
    A supervised child's first step, before anything is imported or warmed
    (T10 fix round 1):

    - take the bus tokens out of ``os.environ`` (``take_bus_environment``), so
      nothing activation or warming starts inherits them;
    - make this child's bounded metrics queue (``metrics_emit.enable``,
      v0.20.0 T17), whose sender and ERROR handler start once the bus is
      connected;
    - ignore Ctrl+Break: on Windows it reaches every process on the console,
      and a child must be drained and stopped by its supervisor, which takes
      Ctrl+Break as its own shutdown (Ctrl+C is already disabled in a new
      process group). Not done on POSIX, which has no SIGBREAK.
    """
    from engine.hosting import metrics_emit, take_bus_environment

    take_bus_environment()
    # The bounded metrics queue (v0.20.0 T17): only a supervised child makes
    # one, so a front door or worker built inside the test suite's own process
    # sends nothing. Its sender starts once the bus is connected.
    metrics_emit.enable()
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, signal.SIG_IGN)


def main(argv: Optional[list[str]] = None) -> int:
    prepare_child()
    parser = argparse.ArgumentParser(prog="python -m engine.hosting.boot")
    parser.add_argument("--role", choices=["worker", "frontdoor"], required=True)
    args = parser.parse_args(argv)
    configure_logging()
    try:
        if args.role == "worker":
            return serve_worker()
        if args.role == "frontdoor":
            return serve_frontdoor()
    except HostingConfigError as exc:
        print(f"Hosted mode refused to start: {exc}", file=sys.stderr, flush=True)
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
