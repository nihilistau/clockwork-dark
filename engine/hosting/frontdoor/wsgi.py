"""
The Front Door under gunicorn
=============================

``app`` is the front door (spec §7.1, §14.5), for gunicorn:

    gunicorn -c deploy/gunicorn.conf.py engine.hosting.frontdoor.wsgi:app

which the supervisor runs on POSIX when gunicorn is installed
(``engine/hosting/supervisor/process.py``, v0.20.0 T13). gunicorn imports
this module in its WORKER process, so the bus link and the WebSocket relay's
threads belong to that worker. On import:

- the supervised child's first step (``boot.prepare_child``): the bus and
  proxy tokens taken out of ``os.environ``;
- local mode refused ("local mode is served by launcher.py; gunicorn serves
  hosted mode only"), then the supervisor's bus required
  (``boot.require_bus``), before anything is built;
- ``create_frontdoor_app()``, which activates NO story (the front door serves
  no turn), takes the cookie key and the server lock, and connects the bus
  and reads the story table.

The port gunicorn bound (``scene.clockwork.host``/``port``) is reported by
``deploy/gunicorn.conf.py``'s ``post_worker_init`` hook (``boot.report_ready``).

Version: v0.1.0 [2026-10-05]
"""

from __future__ import annotations

from typing import Any

from engine.hosting.boot import configure_logging, prepare_child, require_bus
from engine.hosting.config import HostingConfigError

#: What gunicorn is told when hosting is off.
LOCAL_MODE_REFUSAL = "is false: local mode is served by launcher.py; gunicorn serves hosted mode only"


def build() -> Any:
    """The front door's Flask app (see the module docstring)."""
    from engine.config import hosting_enabled
    from engine.hosting.frontdoor import create_frontdoor_app

    prepare_child()
    configure_logging()
    if not hosting_enabled():
        raise HostingConfigError("hosting.enabled", LOCAL_MODE_REFUSAL)
    require_bus()
    return create_frontdoor_app()


app = build()

__all__ = ["LOCAL_MODE_REFUSAL", "app", "build"]
