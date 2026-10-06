"""
A light supervised WSGI app for the fake gunicorn (v0.20.0 T13,
``tests/probes/fake_gunicorn``): served as ``tests.probes.fake_gunicorn_app:app``
(the supervisor's ``--worker-wsgi``). On first access to ``app``, in the fake
gunicorn's worker, it does what a real worker's boot does with the bus and
nothing else: the child's first step (``boot.prepare_child``), the bus
required (``boot.require_bus``), ``hello`` -- raising when the supervisor
refuses it, as a real worker's ``install`` does -- and ``health`` and
``drain`` answered; then a Flask app answering ``GET /api/health``, with the
bus on its extensions, so ``boot.report_ready`` (the conf's
``post_worker_init``) sends ``ready`` with the port. It writes
``<process>-<pid>.json`` (its pid) to ``CLOCKWORK_FAKE_WORKER_DIR`` once
connected, for the instance's orphan check.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_APP: list[Any] = []


def _build() -> Any:
    from flask import Flask, jsonify

    import engine.hosting as hosting_pkg
    from engine.hosting import BUS_EXTENSION
    from engine.hosting.boot import configure_logging, prepare_child, require_bus

    prepare_child()
    configure_logging()
    require_bus()
    client, hosting_pkg._bus_client = hosting_pkg._bus_client, None
    client.handle("health", lambda _args: {})
    client.handle("drain", lambda _args: {"drained": True})
    client.connect()  # a refused hello raises: the worker fails to boot
    name = f"worker-{os.environ.get('CLOCKWORK_GAME', '')}"
    control = Path(os.environ["CLOCKWORK_FAKE_WORKER_DIR"])
    from tests.process_identity import report as identity_report

    (control / f"{name}-{os.getpid()}.json").write_text(json.dumps(identity_report()), encoding="utf-8")
    app = Flask("fake_gunicorn_app")
    app.extensions[BUS_EXTENSION] = client

    @app.get("/api/health")
    def health() -> Any:
        return jsonify({"status": "ok"})

    return app


def __getattr__(name: str) -> Any:
    if name != "app":
        raise AttributeError(name)
    if not _APP:
        _APP.append(_build())
    return _APP[0]
