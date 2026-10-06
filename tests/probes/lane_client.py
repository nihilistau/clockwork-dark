"""
A supervised worker that only queues (v0.20.0 T11): a bus client acting as a
worker, acquiring and releasing lane tickets on command, through the engine's
own ``RemoteLanes`` (``engine/hosting/lanes_remote.py``).

Started by the supervisor as ``python -u -m tests.probes.lane_client --role
worker`` (``tests/hosting_instance.py``'s ``worker_module``). The supervisor
starts its children with stdin closed, so the commands come over a loopback
HTTP port instead, the one this probe reports in ``ready`` (the story
table's ``port``), one JSON command per ``POST /command``:

- ``{"cmd": "acquire", "name": N, "lane": L, "account": A, "timeout": T}``:
  run on one of FOUR pool threads, as a worker's turn threads would, with a
  ``CancelToken`` of its own; answered at once (``{"ok": true}``), the
  outcome printed;
- ``{"cmd": "cancel", "name": N}``: N's wait is called off, as a socket's
  disconnect calls off a waiting turn (T11 fix round 1);
- ``{"cmd": "release", "name": N}``: on the HTTP thread, answered once the
  supervisor acknowledged it, with the seconds it took (``took``);
- ``{"cmd": "hang"}``: from now on a ``lane.reclaimed`` is never
  acknowledged (it blocks a bus pool thread), as a hung worker's would not be;
- ``{"cmd": "status"}``: the names held, ``abandoned_grants`` and the
  ``reclaimed`` names.

Every outcome is one stdout line, which the supervisor echoes as
``[worker-<slug>] LANE ...`` (the test reads the supervisor's output):
``LANE GRANT name=N lane=L t=<time_ns>``, ``LANE REFUSED name=N reason=R``,
``LANE RELEASED name=N``, ``LANE RECLAIMED``. ``GET /api/health`` answers
200; the bus ``health`` and ``drain`` are answered at once.

It writes ``<process>-<pid>.json`` (its pid and port) to
``CLOCKWORK_FAKE_WORKER_DIR``, as ``fake_worker`` does, so the instance can
check that no child outlives it.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from engine.hosting.bus import BusClient  # noqa: E402
from engine.hosting.lanes_remote import RemoteLanes  # noqa: E402
from engine.llm.gate import CancelToken, InferenceBusy  # noqa: E402

CONTROL_ENV = "CLOCKWORK_FAKE_WORKER_DIR"

#: The pool a worker's turns would run on, as many as a gthread worker might.
POOL_THREADS = 4


def _say(line: str) -> None:
    print(line, flush=True)


def main(argv: list[str]) -> int:
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, signal.SIG_IGN)
    parser = argparse.ArgumentParser()
    parser.add_argument("--role", choices=["worker"], required=True)
    parser.parse_args(argv)
    slug = os.environ.get("CLOCKWORK_GAME", "")
    name = f"worker-{slug}"
    control = Path(os.environ[CONTROL_ENV])

    client = BusClient.from_environment()
    assert client is not None, "no CLOCKWORK_BUS_ADDR"
    lanes = RemoteLanes(client)
    hung = threading.Event()
    never = threading.Event()

    def reclaimed(args: dict[str, Any]) -> dict[str, Any]:
        if hung.is_set():
            never.wait()  # a hung worker: the acknowledgement never comes
        _say("LANE RECLAIMED")
        return lanes.reclaimed_ticket(str(args["ticket"]))

    client.handle("health", lambda _args: {})
    client.handle("drain", lambda _args: {"drained": True})
    client.handle("lane.reclaimed", reclaimed)
    client.connect()
    pool = ThreadPoolExecutor(max_workers=POOL_THREADS, thread_name_prefix="turn")
    held: dict[str, str] = {}
    tokens: dict[str, CancelToken] = {}
    held_lock = threading.Lock()

    def acquire(command: dict[str, Any]) -> None:
        label = str(command["name"])
        token = CancelToken()
        with held_lock:
            tokens[label] = token
        try:
            ticket = lanes.acquire(
                str(command["lane"]),
                float(command.get("timeout", 30)),
                str(command.get("account") or ""),
                cancel=token,
            )
        except InferenceBusy as exc:
            _say(f"LANE REFUSED name={label} reason={exc.reason}")
            return
        with held_lock:
            held[label] = ticket
        _say(f"LANE GRANT name={label} lane={command['lane']} t={time.time_ns()}")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args: Any) -> None:
            return

        def _json(self, status: int, body: dict[str, Any]) -> None:
            data = json.dumps(body).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/api/health":
                self._json(200, {"status": "ok", "probe": name})
            else:
                self._json(404, {"error": "not found"})

        def do_POST(self) -> None:  # noqa: N802
            if self.path != "/command":
                self._json(404, {"error": "not found"})
                return
            length = int(self.headers.get("Content-Length") or 0)
            command = json.loads(self.rfile.read(length) or b"{}")
            cmd = command.get("cmd")
            if cmd == "acquire":
                pool.submit(acquire, command)
                self._json(200, {"ok": True})
            elif cmd == "release":
                label = str(command["name"])
                with held_lock:
                    ticket = held.pop(label, None)
                if ticket is None:
                    self._json(200, {"ok": False, "error": "not held"})
                    return
                began = time.monotonic()
                lanes.release(ticket)
                took = time.monotonic() - began
                _say(f"LANE RELEASED name={label}")
                self._json(200, {"ok": True, "took": took})
            elif cmd == "cancel":
                with held_lock:
                    token = tokens.get(str(command["name"]))
                if token is not None:
                    token.cancel()
                self._json(200, {"ok": token is not None})
            elif cmd == "hang":
                hung.set()
                self._json(200, {"ok": True})
            elif cmd == "status":
                with held_lock:
                    names = sorted(held)
                    gone = sorted(n for n, t in held.items() if lanes.reclaimed(t))
                self._json(
                    200,
                    {"ok": True, "held": names, "reclaimed": gone, "abandoned_grants": lanes.abandoned_grants},
                )
            else:
                self._json(400, {"error": "unknown command"})

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    from tests.process_identity import report as identity_report

    report = {**identity_report(), "port": port, "mode": "lane_client"}
    path = control / f"{name}-{os.getpid()}.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(report), encoding="utf-8")
    os.replace(tmp, path)
    client.request("ready", {"port": port})
    _say(f"lane client {name} ready (pid={os.getpid()}, port={port})")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
