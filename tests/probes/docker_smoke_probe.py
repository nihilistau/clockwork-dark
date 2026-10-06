"""
The Docker smoke test's helper INSIDE the container (v0.20.0 T18), copied in
by ``tests/test_docker_smoke.py`` (``docker compose cp``, onto the smoke's
own throwaway ``/data`` volume: the root filesystem is read-only and ``/tmp``
a tmpfs ``docker cp`` cannot reach) and run there with ``docker compose
exec``: the image ships no ``tests/``. Standard library, and the engine's own
account store and lore manager for ``accounts`` and ``lore``.

    python /data/docker_smoke_probe.py stub --port 18080
    python /data/docker_smoke_probe.py accounts alpha:admin beta
    python /data/docker_smoke_probe.py procs
    python /data/docker_smoke_probe.py kill-master <slug> [--freeze-worker]
    python /data/docker_smoke_probe.py resume <slug> <pid> <started>
    python /data/docker_smoke_probe.py fetch <url>
    python /data/docker_smoke_probe.py lore <slug> <query>

- ``stub``: a model server on the container's loopback that speaks the
  OpenAI-compatible routes the engine asks (``GET /v1/models``, ``POST
  /v1/chat/completions``, streamed or not). Every chat is answered with the
  smoke's one fixed turn (``REPLY``), streamed in ``CHUNKS`` pieces
  ``CHUNK_SECONDS`` apart so a turn runs long enough to be seen in the
  queue; the grammar probe's question is answered as a grammar would. No
  model, no network beyond loopback. ``StubModelServer`` is also served on
  the Windows host by the test, to measure ``host.docker.internal``;
- ``accounts``: makes each named account (``name`` or ``name:admin``) with a
  password from ``secrets`` and prints ``{name: password}`` as JSON on
  stdout, for the test process to hold in memory. Nothing else keeps them;
- ``procs``: every process in the container as JSON (pid, ppid, state,
  start time, argv), read from ``/proc`` (the slim image has no ``ps``);
- ``kill-master <slug> [--freeze-worker]``: SIGKILL the gunicorn MASTER
  serving that story's worker -- the process whose argv runs ``gunicorn``
  with the worker's WSGI module and whose environment holds
  ``CLOCKWORK_GAME=<slug>`` -- in the container the test started, and print
  its pid and its gunicorn worker's. ``--freeze-worker`` SIGSTOPs that
  worker first, so it wakes (``resume``) to a dead parent and a closed bus
  link at once: the path where ``engine.hosting.boot.stop_master`` must not
  signal the pid its master had;
- ``resume <slug> <pid> <started>``: SIGCONT that process, only if it is a
  stopped gunicorn worker of that story with that start time;
- ``fetch <url>``: GET it, print the HTTP status or the error's class;
- ``lore <slug> <query>``: open the story's built-in lore index as this
  user and print its chunk count and a search's hits.

``kill-master`` and ``resume`` refuse to run outside a container (no
``/.dockerenv``): on a host serving a hosted instance they would signal it.

Every signal goes through a pidfd, after the process behind it is checked to
have the start time it was listed with (``_signal``): a process is its pid
AND its start time, never a bare pid (AGENTS.md). And only inside the
container the smoke test started, whose pid namespace holds nothing else.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import signal
import sys
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Optional

#: The smoke's one model reply: a turn the engine accepts.
REPLY = json.dumps(
    {
        "narration": "Lamplight pools on the wet cobbles while the smoke test waits.",
        "choices": [{"id": "a", "text": "Walk on"}, {"id": "b", "text": "Wait"}],
    }
)

#: How many pieces a streamed answer comes in, and the pause between them.
CHUNKS = 8
CHUNK_SECONDS = 0.4

#: The grammar probe's question (``engine/llm/backend.py``), answered as an
#: enforced grammar would answer it.
CONSTRAINT_PROBE = "Reply with exactly"

MODEL_ID = "smoke-stub"


def _answer_for(body: dict[str, Any]) -> str:
    text = json.dumps(body.get("messages") or [])
    if CONSTRAINT_PROBE in text:
        return json.dumps({"answer": "yes"})
    return REPLY


class StubModelServer:
    """The stub on ``host``:``port`` (0: one the OS picks), in this process."""

    def __init__(self, host: str = "127.0.0.1", port: int = 0) -> None:
        stub = self
        self.seen: list[str] = []

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *_args: Any) -> None:
                return

            def _json(self, status: int, payload: Any) -> None:
                data = json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self) -> None:  # noqa: N802
                path = self.path.split("?", 1)[0]
                stub.seen.append(f"GET {path}")
                if path in ("/v1/models", "/models"):
                    self._json(200, {"object": "list", "data": [{"id": MODEL_ID, "object": "model"}]})
                elif path in ("/health", "/v1/health"):
                    self._json(200, {"status": "ok"})
                else:
                    self._json(404, {"error": "not found"})

            def do_POST(self) -> None:  # noqa: N802
                path = self.path.split("?", 1)[0]
                stub.seen.append(f"POST {path}")
                length = int(self.headers.get("Content-Length") or 0)
                try:
                    body = json.loads(self.rfile.read(length) or b"{}")
                except ValueError:
                    body = {}
                if not path.endswith("/chat/completions"):
                    self._json(404, {"error": "not found"})
                    return
                content = _answer_for(body if isinstance(body, dict) else {})
                usage = {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}
                if not (isinstance(body, dict) and body.get("stream")):
                    self._json(200, {
                        "id": "smoke", "object": "chat.completion", "model": MODEL_ID,
                        "choices": [{"index": 0, "message": {"role": "assistant", "content": content},
                                     "finish_reason": "stop"}],
                        "usage": usage,
                    })
                    return
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "close")
                self.end_headers()
                size = max(1, -(-len(content) // CHUNKS))
                pieces = [content[i:i + size] for i in range(0, len(content), size)]
                try:
                    for index, piece in enumerate(pieces):
                        chunk = {
                            "id": "smoke", "object": "chat.completion.chunk", "model": MODEL_ID,
                            "choices": [{"index": 0, "delta": ({"role": "assistant"} if index == 0 else {})
                                         | {"content": piece}, "finish_reason": None}],
                        }
                        self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode("utf-8"))
                        self.wfile.flush()
                        time.sleep(CHUNK_SECONDS)
                    last = {
                        "id": "smoke", "object": "chat.completion.chunk", "model": MODEL_ID,
                        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}], "usage": usage,
                    }
                    self.wfile.write(f"data: {json.dumps(last)}\n\ndata: [DONE]\n\n".encode("utf-8"))
                    self.wfile.flush()
                except OSError:
                    return
                self.close_connection = True

        self.server = ThreadingHTTPServer((host, port), Handler)
        self.server.daemon_threads = True

    @property
    def port(self) -> int:
        return int(self.server.server_address[1])


def _procs() -> list[dict[str, Any]]:
    found = []
    for name in os.listdir("/proc"):
        if not name.isdigit():
            continue
        try:
            with open(f"/proc/{name}/cmdline", "rb") as handle:
                argv = [p.decode("utf-8", "replace") for p in handle.read().split(b"\0") if p]
            with open(f"/proc/{name}/stat", encoding="utf-8") as handle:
                stat = handle.read()
        except OSError:
            continue
        after = stat.rsplit(")", 1)[1].split()
        # after[19] is the process's start time (field 22 of /proc/<pid>/stat):
        # with the pid, its identity -- a pid alone the kernel may reuse.
        found.append({"pid": int(name), "state": after[0], "ppid": int(after[1]),
                      "started": int(after[19]), "argv": argv})
    return sorted(found, key=lambda row: row["pid"])


def _started(pid: int) -> Optional[int]:
    try:
        with open(f"/proc/{pid}/stat", encoding="utf-8") as handle:
            return int(handle.read().rsplit(")", 1)[1].split()[19])
    except (OSError, ValueError, IndexError):
        return None


def _signal(row: dict[str, Any], sig: int) -> bool:
    """
    Signal the process ``row`` names through ONE handle (a pidfd), only if
    the process behind it still has the start time it was listed with: never
    a bare pid (AGENTS.md, the suite's process identity rule).
    """
    fd = os.pidfd_open(int(row["pid"]))
    try:
        if _started(int(row["pid"])) != int(row["started"]):
            return False
        signal.pidfd_send_signal(fd, sig)
        return True
    finally:
        os.close(fd)


def _environ_game(pid: int) -> Optional[str]:
    try:
        with open(f"/proc/{pid}/environ", "rb") as handle:
            for item in handle.read().split(b"\0"):
                if item.startswith(b"CLOCKWORK_GAME="):
                    return item.split(b"=", 1)[1].decode("utf-8", "replace")
    except OSError:
        return None
    return None


def _in_container() -> bool:
    """Docker writes ``/.dockerenv`` into every container: nowhere else is a signal sent."""
    return os.path.exists("/.dockerenv")


def _lore(slug: str, query: str) -> int:
    """The built-in lore index of ``slug``, opened and searched as THIS user (uid 10001 in the image)."""
    sys.path.insert(0, "/app")
    from pathlib import Path

    from engine.lore.manager import LoreManager

    path = Path("/app/games") / slug / "data" / "lore" / "lore.db"
    manager = LoreManager(db_path=path)
    try:
        found = {"uid": os.getuid(), "count": manager.count(), "hits": len(manager.search(query, limit=3))}
    finally:
        manager.close()
    print(json.dumps(found))
    return 0


def _story_gunicorns(slug: str) -> list[dict[str, Any]]:
    """Every gunicorn process serving ``slug``'s worker app (its master and its worker)."""
    return [
        r for r in _procs()
        if "gunicorn" in " ".join(r["argv"]) and "engine.hosting.wsgi:app" in r["argv"]
        and _environ_game(r["pid"]) == slug
    ]


def _kill_master(slug: str, freeze: bool) -> int:
    found = _story_gunicorns(slug)
    # The master is the one whose parent is not itself a gunicorn of the same app.
    pids = {r["pid"] for r in found}
    roots = [r for r in found if r["ppid"] not in pids]
    if len(roots) != 1:
        print(json.dumps({"error": "no single master", "found": sorted(pids)}))
        return 2
    master = roots[0]
    workers = [r for r in found if r["ppid"] == master["pid"]]
    if freeze:
        # Stopped first, so the worker cannot notice its parent die before the
        # supervisor has: on SIGCONT it meets both at once.
        for row in workers:
            if not _signal(row, signal.SIGSTOP):
                print(json.dumps({"error": "the worker changed before it was stopped"}))
                return 2
    if not _signal(master, signal.SIGKILL):
        print(json.dumps({"error": "the master changed before it was killed"}))
        return 2
    print(json.dumps({
        "master": master["pid"], "master_started": master["started"],
        "workers": [r["pid"] for r in workers], "workers_started": [r["started"] for r in workers],
    }))
    return 0


def _resume(slug: str, pid: int, started: int) -> int:
    """SIGCONT the process (``pid``, ``started``) -- only a STOPPED gunicorn worker of ``slug``'s app."""
    match = [r for r in _story_gunicorns(slug)
             if r["pid"] == pid and r["started"] == started and r["state"] == "T"]
    if not match or not _signal(match[0], signal.SIGCONT):
        print(json.dumps({"error": "not a stopped worker of that story", "pid": pid}))
        return 2
    print(json.dumps({"resumed": pid, "ppid": match[0]["ppid"]}))
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    sub = parser.add_subparsers(dest="command", required=True)
    stub = sub.add_parser("stub")
    stub.add_argument("--port", type=int, default=18080)
    accounts = sub.add_parser("accounts")
    accounts.add_argument("names", nargs="+")
    sub.add_parser("procs")
    kill = sub.add_parser("kill-master")
    kill.add_argument("slug")
    kill.add_argument("--freeze-worker", action="store_true")
    resume = sub.add_parser("resume")
    resume.add_argument("slug")
    resume.add_argument("pid", type=int)
    resume.add_argument("started", type=int)
    fetch = sub.add_parser("fetch")
    fetch.add_argument("url")
    lore = sub.add_parser("lore")
    lore.add_argument("slug")
    lore.add_argument("query")
    args = parser.parse_args(argv)

    if args.command in ("kill-master", "resume") and not _in_container():
        # Run by hand on a host serving a hosted instance, it would signal
        # that instance's processes: refused outside a container.
        print(json.dumps({"error": "refused: not inside a container (no /.dockerenv)"}))
        return 3
    if args.command == "lore":
        return _lore(args.slug, args.query)

    if args.command == "stub":
        server = StubModelServer("127.0.0.1", args.port)
        print(f"stub serving on 127.0.0.1:{server.port}", flush=True)
        server.server.serve_forever()
        return 0
    if args.command == "accounts":
        sys.path.insert(0, "/app")
        from engine.hosting.accounts import AccountStore
        from engine.persistence.storage import hosting_dir

        store = AccountStore(hosting_dir())
        made = {}
        for spec in args.names:
            name, _, role = spec.partition(":")
            password = secrets.token_urlsafe(18)
            store.add(name, password, admin=(role == "admin"))
            made[name] = password
        print(json.dumps(made))
        return 0
    if args.command == "procs":
        print(json.dumps(_procs()))
        return 0
    if args.command == "kill-master":
        return _kill_master(args.slug, args.freeze_worker)
    if args.command == "resume":
        return _resume(args.slug, args.pid, args.started)
    if args.command == "fetch":
        try:
            with urllib.request.urlopen(args.url, timeout=10) as answer:  # noqa: S310 - the test's own URL
                print(json.dumps({"status": int(answer.status)}))
        except urllib.error.HTTPError as exc:
            print(json.dumps({"status": int(exc.code)}))
        except (OSError, ValueError) as exc:
            print(json.dumps({"error": type(exc).__name__, "detail": str(exc)[:200]}))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
