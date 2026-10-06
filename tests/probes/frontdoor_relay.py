"""
The engine's own front door, with a side door for the test suite (v0.20.0
T12).

Runs exactly what ``python -m engine.hosting.boot --role frontdoor`` runs --
``prepare_child``, ``create_frontdoor_app()``, ``serve_frontdoor`` on
``scene.clockwork.host``/``port`` -- and, beside it on ANOTHER loopback port
the OS picks, a tiny HTTP server whose ``POST /bus`` (``{"op", "args",
"timeout"}``) relays a front-door-only op to the supervisor over the front
door's own bus connection and answers the reply as JSON. That is how a test
stops a story or reads the operations table before the admin panel (T14)
exists; the front door app itself carries no such route. With ``CLOCKWORK_PROBE_FORBID_RESET``
set, the front door's ``reset_config`` and ``reset_all_caches`` are replaced
once it is built by functions that write ``frontdoor-<pid>.reset`` and raise
(v0.20.0 T16, ``scripted_worker.forbid_resets``). The side port is
written to ``frontdoor-relay.port`` in ``CLOCKWORK_FAKE_WORKER_DIR``, and a
``frontdoor-<pid>.json`` report there lets the instance check this process is
gone at the end.

Run by the supervisor as ``python -u -m tests.probes.frontdoor_relay --role
frontdoor`` (``tests/hosting_instance.py``, ``frontdoor="real"``), or, where
gunicorn runs (v0.20.0 T13), served by gunicorn as
``tests.probes.frontdoor_relay:app`` (the supervisor's ``--frontdoor-wsgi``).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

CONTROL_ENV = "CLOCKWORK_FAKE_WORKER_DIR"


def _relay(bus: Any, control: Path) -> None:
    from engine.hosting.bus import BusError

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args: Any) -> None:
            return

        def do_POST(self) -> None:  # noqa: N802
            if self.path != "/bus":
                self.send_response(404)
                self.end_headers()
                return
            length = int(self.headers.get("Content-Length") or 0)
            call = json.loads(self.rfile.read(length) or b"{}")
            try:
                result = {"ok": True, "result": bus.request(call["op"], call.get("args") or {}, timeout=float(call.get("timeout", 10)))}
            except BusError as exc:
                result = {"ok": False, "error": exc.code}
            data = json.dumps(result).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, name="relay", daemon=True).start()
    path = control / "frontdoor-relay.port"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(str(server.server_address[1]), encoding="utf-8")
    os.replace(tmp, path)


def _builder() -> Any:
    """Write this process's report and return the build (the front door, with the side port)."""
    from engine.hosting.boot import configure_logging

    configure_logging()
    control = Path(os.environ[CONTROL_ENV])
    from tests.process_identity import report as identity_report

    (control / f"frontdoor-{os.getpid()}.json").write_text(json.dumps(identity_report()), encoding="utf-8")

    def build() -> Any:
        from engine.hosting.frontdoor import FRONTDOOR_EXTENSION, create_frontdoor_app

        app = create_frontdoor_app()
        _relay(app.extensions[FRONTDOOR_EXTENSION].bus, control)
        # v0.20.0 T16: with CLOCKWORK_PROBE_FORBID_RESET set, a reset here
        # writes frontdoor-<pid>.reset and raises (the model apply's rule).
        from tests.probes.scripted_worker import forbid_resets, trace_bus

        forbid_resets(control, "frontdoor")
        # v0.20.0 T17: with CLOCKWORK_PROBE_BUS_TRACE set, every frame sent
        # to the supervisor is also written to frontdoor-<pid>.bustrace.
        trace_bus(control, "frontdoor")
        return app

    return build


def main(argv: list[str]) -> int:
    from engine.hosting.boot import prepare_child, serve_frontdoor

    prepare_child()
    parser = argparse.ArgumentParser()
    parser.add_argument("--role", choices=["frontdoor"], required=True)
    parser.parse_args(argv)
    return serve_frontdoor(_builder())


#: The app gunicorn serves (``tests.probes.frontdoor_relay:app``, the
#: supervisor's ``--frontdoor-wsgi``; v0.20.0 T13), built on first access in
#: gunicorn's worker, side port included.
_APP: list[Any] = []


def __getattr__(name: str) -> Any:
    if name != "app":
        raise AttributeError(name)
    if not _APP:
        from engine.hosting.boot import prepare_child

        prepare_child()
        _APP.append(_builder()())
    return _APP[0]


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
