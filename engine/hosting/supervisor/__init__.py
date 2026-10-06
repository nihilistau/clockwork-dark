"""
The Supervisor
==============

``python -m engine.hosting.supervisor`` runs a hosted instance (spec §14.1,
§14.3): a plain Python process that serves no HTTP and runs no turn. It
starts one worker process per story in ``hosting.stories`` (and, from v0.20.0
T12, the front door), talks to each over the bus (``engine/hosting/bus.py``),
health-checks them, restarts a crashed one with backoff (holding a crash loop
down), stops and restarts stories one operation at a time, captures every
child's log, and on SIGTERM, SIGINT or Ctrl+C drains and stops everything
within ``hosting.supervisor.shutdown_seconds``.

Local mode never starts it: ``launcher.py`` with hosting off is v0.19.0's code
path, and this package is never imported there.

- ``__main__.py``: the start order and the signals;
- ``server.py``: ``Supervisor`` (the bus server, the token table, the story
  table, health, restarts, shutdown);
- ``process.py``: one child (its command, environment, state, stop);
- ``ops.py``: the operations table and its one thread;
- ``logs.py``: per-process log files, rotation, the ``[<process>]`` echo.

Restarting the supervisor itself is NOT WIRED (docs/GOVERNANCE.md): the
container's or systemd's restart policy does it.

Version: v0.1.0 [2026-10-01]
"""

from __future__ import annotations

from engine.hosting.supervisor.server import DEFAULT_WORKER_MODULE, Supervisor

__all__ = ["DEFAULT_WORKER_MODULE", "Supervisor"]
