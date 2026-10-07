"""
``python -m engine.hosting.supervisor``: a hosted instance (spec §14.3).

ON START, IN ORDER:

1. requires ``hosting.enabled``, and a non-empty ``hosting.stories`` whose
   every slug the registry knows and validates (naming any that fails), and
   applies spec §6.7's startup refusals itself (the studio,
   ``llm.mcp.enabled``), so the operator sees ONE error and not a crash loop
   per story;
2. checks the storage root is writable, and makes the cookie key (spec §6.2)
   before any child starts, so every child reads the same one;
3. binds the bus, then opens the metrics store
   (``<storage.root>/hosting/metrics.sqlite3``, v0.20.0 T17), whose ``error``
   rows also get the supervisor's own ERROR records (the logger's name and
   the exception's class, never the message);
4. starts one worker per slug, in list order, and the front door after them
   (v0.20.0 T12), on ``scene.clockwork.host``/``port``: under gunicorn on
   POSIX when it is installed (``gunicorn -c deploy/gunicorn.conf.py``, the
   role's WSGI module, v0.20.0 T13), else ``python -m engine.hosting.boot
   --role worker|frontdoor`` (Werkzeug). Each start logs its command.

A refusal prints ``Hosted mode refused to start: <key>: <why>`` and exits 1.

SIGTERM and SIGINT on POSIX (``docker stop``), Ctrl+C or Ctrl+Break on
Windows, start the shutdown; nothing is forwarded to a child (each runs in a
process group of its own), which the supervisor drains and stops itself.

``--worker-module`` / ``--frontdoor-module`` name what a child runs with
``python -m``; the defaults are the engine's own boot runner. The test suite
points them at its probes (``tests/probes/``), and ``--no-frontdoor``, the
suite's alone, runs the supervisor and its workers with no front door (an
instance that serves nobody: the supervisor's own tests).
``--worker-wsgi`` / ``--frontdoor-wsgi`` (hidden, the suite's) name the
module whose ``app`` gunicorn serves for a probe; a probe runner given none
runs as itself even where gunicorn is installed (``wsgi_for``).

Version: v0.5.0 [2026-10-06]
"""

from __future__ import annotations

import argparse
import logging
import re
import signal
import sys
import tempfile
import threading
from pathlib import Path
from typing import Any, Optional

from engine.hosting.config import HostingConfigError, HostingSettings, load, story_problems

logger = logging.getLogger("engine.hosting.supervisor")

#: A module name a child may be started with (``python -m <name>``).
MODULE_NAME = re.compile(r"^[A-Za-z_]\w*(\.[A-Za-z_]\w*)*$")

#: What a refused start prints before exiting 1.
REFUSED_PREFIX = "Hosted mode refused to start"


def lane_limits(cfg: Any) -> dict[str, int]:
    """
    ``llm.lanes`` as the queue's sizes (spec §14.4: sizing is unchanged),
    through the gate's own reading (``engine.llm.gate.lane_limits``), the
    one source of the defaults.
    """
    from engine.llm.gate import lane_limits as read_lanes

    return read_lanes(cfg.get("llm.lanes", {}) or {})


def preflight(cfg: Any) -> HostingSettings:
    """
    Steps 1 of the start order: the block, the stories, the §6.7 refusals.

    Raises:
        HostingConfigError: naming the key.
    """
    from engine.hosting import refuse_unsupported

    settings = load(cfg)
    if not settings.enabled:
        raise HostingConfigError(
            "hosting.enabled",
            "is false: the supervisor runs hosted mode only; local single-player is "
            "served by launcher.py",
        )
    problems = story_problems(settings.stories)
    if problems:
        slug, why = problems[0]
        raise HostingConfigError("hosting.stories", f"{slug!r} {why}" if slug else why)
    refuse_unsupported(cfg)
    return settings


def prepare_storage(settings: HostingSettings) -> Path:
    """
    Step 2: ``<root>/hosting/`` made and proved writable, and the cookie key
    made there (unless ``hosting.secret_key`` is set). Returns the directory.

    Raises:
        HostingConfigError: naming ``storage.root`` when it cannot be written.
    """
    from engine.hosting.accounts import secure_dir
    from engine.hosting.auth import secret_key
    from engine.persistence.storage import hosting_dir

    try:
        directory = secure_dir(hosting_dir())
        with tempfile.TemporaryFile(dir=directory, prefix=".supervisor-probe-"):
            pass
    except OSError as exc:
        raise HostingConfigError(
            "storage.root", f"{hosting_dir()} is not writable ({exc.strerror or exc})"
        ) from None
    secret_key(settings, directory)
    return directory


def _install_signals(stop: threading.Event, caught: list[int]) -> None:
    """
    The handler only records the signal and sets ``stop``: it runs on the
    main thread between bytecodes, possibly while that thread holds a log
    lock, so it must not log (T10 fix round 1). ``Supervisor.run`` says it.
    """

    def handler(signum: int, _frame: Any) -> None:
        caught.append(signum)
        stop.set()

    names = ["SIGINT", "SIGTERM", "SIGBREAK"]  # SIGBREAK: Ctrl+Break on Windows
    for name in names:
        number = getattr(signal, name, None)
        if number is not None:
            signal.signal(number, handler)


def _module(value: str) -> str:
    if not MODULE_NAME.match(value):
        raise argparse.ArgumentTypeError(f"{value!r} is not a module name")
    return value


def wsgi_for(module: str, wsgi: Optional[str], default_module: str, role: str) -> str:
    """
    The WSGI module a child serves under gunicorn: ``wsgi`` when given; the
    role's own (``engine.hosting.wsgi``, ``engine.hosting.frontdoor.wsgi``)
    when it runs the engine's default boot runner; else "" -- a test probe's
    runner with no WSGI module runs as itself, under gunicorn or not.
    """
    from engine.hosting.supervisor.process import DEFAULT_WSGI

    if wsgi:
        return wsgi
    return DEFAULT_WSGI[role] if module == default_module else ""


def main(argv: Optional[list[str]] = None) -> int:
    from engine.hosting.metrics_emit import ErrorMetricHandler
    from engine.hosting.supervisor.logs import HubHandler, LogHub
    from engine.hosting.supervisor.metrics import FILE_NAME as METRICS_FILE
    from engine.hosting.supervisor.server import (
        DEFAULT_FRONTDOOR_MODULE,
        DEFAULT_WORKER_MODULE,
        Supervisor,
    )

    parser = argparse.ArgumentParser(prog="python -m engine.hosting.supervisor")
    parser.add_argument("--worker-module", type=_module, default=DEFAULT_WORKER_MODULE)
    parser.add_argument("--frontdoor-module", type=_module, default=DEFAULT_FRONTDOOR_MODULE)
    parser.add_argument("--worker-wsgi", type=_module, default=None, help=argparse.SUPPRESS)
    parser.add_argument("--frontdoor-wsgi", type=_module, default=None, help=argparse.SUPPRESS)
    parser.add_argument("--no-frontdoor", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    args = parser.parse_args(argv)
    worker_wsgi = wsgi_for(args.worker_module, args.worker_wsgi, DEFAULT_WORKER_MODULE, "worker")
    frontdoor_wsgi = wsgi_for(args.frontdoor_module, args.frontdoor_wsgi, DEFAULT_FRONTDOOR_MODULE, "frontdoor")

    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=level, format="[supervisor] %(levelname)s %(message)s", stream=sys.stderr)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    try:
        from engine.config import LegacyConfigError, get_config

        cfg = get_config()
        settings = preflight(cfg)
        directory = prepare_storage(settings)
    except LegacyConfigError as exc:
        # Plan decision 4: like every other startup refusal (exit 1).
        print(f"{REFUSED_PREFIX}: {exc}", file=sys.stderr, flush=True)
        return 1
    except HostingConfigError as exc:
        print(f"{REFUSED_PREFIX}: {exc}", file=sys.stderr, flush=True)
        return 1

    hub = LogHub(directory / "logs", max_mb=settings.log_max_mb, keep=settings.log_keep, echo=sys.stdout)
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
    root.addHandler(HubHandler(hub))
    root.setLevel(level)

    from engine.config import project_root

    stop = threading.Event()
    caught: list[int] = []
    _install_signals(stop, caught)
    supervisor = Supervisor(
        settings,
        hub=hub,
        worker_module=args.worker_module,
        frontdoor_module=None if args.no_frontdoor else args.frontdoor_module,
        worker_wsgi=worker_wsgi,
        frontdoor_wsgi=frontdoor_wsgi,
        # Children run from the repository root: `python -m` puts the working
        # directory first on sys.path, and the operator's must not shadow it.
        cwd=str(project_root()),
        # One queue for every worker, sized as each process's lanes would be.
        lanes=lane_limits(cfg),
        # The metrics store (v0.20.0 T17), opened by start() after the bus.
        metrics_path=directory / METRICS_FILE,
    )
    # The supervisor's own ERROR records, as `error` metrics: the logger's
    # name and the exception's class, never the message (spec §14.10).
    root.addHandler(ErrorMetricHandler(supervisor.record_error))
    try:
        supervisor.start()
        code = supervisor.run(stop, caught)
    except BaseException:
        logger.exception("[supervisor] Failed; stopping every child (operation=main)")
        supervisor.shutdown()
        code = 1
    hub.close()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
