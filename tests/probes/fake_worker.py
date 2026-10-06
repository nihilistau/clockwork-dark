"""
A fake supervised child (v0.20.0 T10): speaks the bus, serves ``GET
/api/health`` on an OS-picked loopback port, and misbehaves on request.

Started by the supervisor as ``python -u -m tests.probes.fake_worker --role
worker|frontdoor`` (``tests/hosting_instance.py`` passes
``--worker-module tests.probes.fake_worker``), or by a test directly with the
bus variables in its environment. Everything it is told comes from its
environment, never argv:

- ``CLOCKWORK_FAKE_WORKER_DIR``: a control directory. ``<process>.mode``
  there (``worker-<slug>.mode`` or ``frontdoor.mode``) holds the mode, re-read
  on every health check, so a test can switch it while the child runs:

  ``healthy`` (the default), ``exit_now``, ``exit_after <seconds>``,
  ``no_ready`` (connects, never sends ``ready``), ``http_500`` (the HTTP
  check fails, the bus is fine), ``no_bus_health`` (the bus ``health`` is
  never answered while the mode holds), ``hang`` (neither is answered),
  ``hold_turn`` (at its next bus health check it takes a narration ticket in
  the supervisor's queue and keeps it until the mode changes back, so a
  drain runs out; v0.20.0 T11), ``ignore_shutdown``
  (the bus ``shutdown`` is answered and ignored), ``spew <bytes>`` (that many
  bytes of output lines, then healthy).

- On start it writes ``<process>-<pid>.json`` there: its pid, its mode,
  whether the cookie key file existed BEFORE its ``hello``, the NAMES of its
  environment variables after it connected (never a value), its process
  group (POSIX), its port and the LENGTH of the proxy token it was given
  (T12). Each HTTP health check it answers adds one
  byte to ``<process>-<pid>.http`` (``2`` or ``5``), so a test waits for
  checks rather than for time.

As ``--role frontdoor`` it also relays ``POST /bus`` (``{"op", "args",
"timeout"}``) to the supervisor and answers the reply as JSON: the tests' way
to call the front-door-only ops until the real front door (T12).
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from engine.hosting.bus import BusClient, BusError  # noqa: E402

CONTROL_ENV = "CLOCKWORK_FAKE_WORKER_DIR"


def _control() -> Path:
    return Path(os.environ[CONTROL_ENV])


def _mode(name: str) -> tuple[str, str]:
    try:
        text = (_control() / f"{name}.mode").read_text(encoding="utf-8").strip()
    except OSError:
        text = ""
    word, _, rest = (text or "healthy").partition(" ")
    return word, rest.strip()


def _write_report(name: str, report: dict[str, Any]) -> None:
    path = _control() / f"{name}-{os.getpid()}.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(report), encoding="utf-8")
    os.replace(tmp, path)


def _wait_while(name: str, modes: set[str], limit: float = 60.0) -> None:
    deadline = time.monotonic() + limit
    pause = threading.Event()
    while _mode(name)[0] in modes and time.monotonic() < deadline:
        pause.wait(0.05)


def main(argv: list[str]) -> int:
    # As the engine's boot does (engine/hosting/boot.py::prepare_child): the
    # supervisor drains and stops its children itself.
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, signal.SIG_IGN)
    parser = argparse.ArgumentParser()
    parser.add_argument("--role", choices=["worker", "frontdoor"], required=True)
    args = parser.parse_args(argv)
    slug = os.environ.get("CLOCKWORK_GAME", "")
    name = "frontdoor" if args.role == "frontdoor" else f"worker-{slug}"
    mode, param = _mode(name)
    data_dir = os.environ.get("CLOCKWORK_DATA_DIR", "")
    key_file = Path(data_dir) / "hosting" / "secret_key" if data_dir else None
    from tests.process_identity import report as identity_report

    report: dict[str, Any] = {
        **identity_report(),  # pid and creation time: never signalled by pid alone
        "mode": mode,
        "key_file_existed": bool(key_file and key_file.is_file()),
        "pgid": os.getpgid(0) if hasattr(os, "getpgid") else None,
    }
    print(f"fake {name} starting (pid={os.getpid()}, mode={mode})", flush=True)
    if mode == "exit_now":
        _write_report(name, report)
        return 5

    client = BusClient.from_environment()
    assert client is not None, "no CLOCKWORK_BUS_ADDR"

    held: list[str] = []

    def health(_args: dict[str, Any]) -> dict[str, Any]:
        _wait_while(name, {"no_bus_health", "hang"})
        # `hold_turn` (v0.20.0 T11): a turn holds this story's narration
        # ticket in the supervisor's queue until the mode changes back, so a
        # drain (which waits for the story's tickets) runs out.
        holding = _mode(name)[0] == "hold_turn"
        if holding and not held:
            reply = client.request("lane.acquire", {"lane": "narration", "timeout": 5}, timeout=10)
            held.append(str(reply["ticket"]))
        elif not holding and held:
            client.request("lane.release", {"ticket": held.pop()}, timeout=10)
        return {}

    client.handle("health", health)
    client.handle("drain", lambda _call: {"drained": True})
    if mode == "ignore_shutdown":
        client.on_shutdown = lambda: print("fake: shutdown ignored", flush=True)
    client.connect()

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
            if self.path != "/api/health":
                self._json(404, {"error": "not found"})
                return
            _wait_while(name, {"hang"})
            status = 500 if _mode(name)[0] == "http_500" else 200
            # One byte per check answered, so a test can wait for checks
            # rather than for time (<process>-<pid>.http).
            with open(_control() / f"{name}-{os.getpid()}.http", "ab") as tally:
                tally.write(b"5" if status == 500 else b"2")
            if status == 500:
                self._json(500, {"status": "broken"})
                return
            self._json(200, {"status": "ok", "fake": name})

        def do_POST(self) -> None:  # noqa: N802
            if args.role != "frontdoor" or self.path != "/bus":
                self._json(404, {"error": "not found"})
                return
            length = int(self.headers.get("Content-Length") or 0)
            call = json.loads(self.rfile.read(length) or b"{}")
            try:
                result = client.request(
                    call["op"], call.get("args") or {}, timeout=float(call.get("timeout") or 10)
                )
            except BusError as exc:
                self._json(200, {"ok": False, "error": exc.code})
                return
            self._json(200, {"ok": True, "result": result})

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    report["port"] = port
    report["env_keys"] = sorted(os.environ)
    # v0.20.0 T12: the proxy token reached it (its length only, never the value).
    report["proxy_token_chars"] = len(client.proxy_token)
    _write_report(name, report)
    if mode != "no_ready":
        client.request("ready", {"port": port})
    if mode == "exit_after":
        threading.Timer(float(param or 1), lambda: os._exit(5)).start()
    if mode == "spew":
        chunk = "x" * 1023
        for _ in range(int(param or 0) // 1024 + 1):
            print(chunk, flush=False)
        sys.stdout.flush()
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
