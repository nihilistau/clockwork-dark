"""
Hosted Mode: a Story Worker under gunicorn
==========================================

``app`` is one story's hosted worker (spec §7.1), for gunicorn:

    gunicorn -c deploy/gunicorn.conf.py engine.hosting.wsgi:app

which the supervisor runs on POSIX when gunicorn is installed
(``engine/hosting/supervisor/process.py``, v0.20.0 T13); nothing else should.
gunicorn imports this module in its WORKER process (``preload_app`` is off),
so everything below -- the bus, the warmed caches -- belongs to that worker.
On import, in order:

- the supervised child's first step (``boot.prepare_child``): the bus and
  proxy tokens taken out of ``os.environ`` before anything is activated or
  warmed;
- local mode refused before anything is activated or built ("local mode is
  served by launcher.py; gunicorn serves hosted mode only");
- spec §7.1's five steps (``boot.build_worker_app``): ``CLOCKWORK_GAME``
  read, the story activated, hosting required, the supervisor's bus required
  (``boot.require_bus``), then ``create_app()``, whose ``install()``
  validates the ``hosting:`` block, applies the §6.7 refusals, warms every
  cache and connects the bus.

So the worker boots ready or does not boot: a refusal raises here, gunicorn
reports the worker failed to boot and its master exits, and the supervisor
applies its restart policy. The port gunicorn bound (``127.0.0.1:0``) is
reported to the supervisor by ``deploy/gunicorn.conf.py``'s
``post_worker_init`` hook, through ``boot.report_ready``.

Version: v0.1.0 [2026-10-05]
"""

from __future__ import annotations

from typing import Any

from engine.hosting.boot import build_worker_app, configure_logging, prepare_child
from engine.hosting.config import HostingConfigError

#: What gunicorn is told when hosting is off.
LOCAL_MODE_REFUSAL = "is false: local mode is served by launcher.py; gunicorn serves hosted mode only"


def build() -> Any:
    """The worker's Flask app (see the module docstring)."""
    from engine.config import hosting_enabled

    prepare_child()
    configure_logging()
    if not hosting_enabled():
        raise HostingConfigError("hosting.enabled", LOCAL_MODE_REFUSAL)
    _scene, worker = build_worker_app()
    return worker


app = build()

__all__ = ["LOCAL_MODE_REFUSAL", "app", "build"]
