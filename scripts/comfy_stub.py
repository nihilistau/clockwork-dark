"""
A stub ComfyUI (v0.22.0 spec §13.5): every route the phone's media use,
answered by a SCRIPTED behaviour, with tiny PNG and WEBM bodies.

ONE TABLE, TWO DOORS. :data:`SCRIPTS` and :func:`answer` are the behaviour;
``tests/comfy_stub.py::StubComfy`` serves them in process through an
``httpx.MockTransport`` (no bind, the parallel phase), and this script serves
them over loopback for a hand test and the one end-to-end test
(``tests/test_comfy_stub_e2e.py``)::

    python scripts/comfy_stub.py --port N [--script ready] [--polls 2]
                                 [--control control.json] [--log requests.jsonl]
                                 [--exit-with-parent]

``--control`` names a JSON file ``{"script": "<name>"}`` re-read on every
request, so a test can change the behaviour of a running stub; ``--log``
appends one JSON line per request (``path``, and for ``/prompt`` the body's
``client_id``). It binds ``127.0.0.1`` only. ``--exit-with-parent`` ends it
once the process that started it is gone (its parent's pid AND creation
time, ``engine/hosting/process_identity.py``), so it never outlives its
launcher. Start it with the shell's background task, never a bare ``&``.

THE SCRIPTS. A prompt id is ``p-<client_id>``. ``ready``: ``/history``
answers empty ``polls`` times after each submit, then an entry whose output
nodes (every submitted node with a ``filename_prefix`` input) list one PNG.
``node_errors``: ``/prompt`` answers 400. ``execution_error``: the history
entry is an execution error, always; ``execution_error_once``: only for the
first submit of a prompt id. ``never`` and ``hold``: ``/history`` empty for
ever. ``unauthorized``: 401 on every route. ``oversized``: ``/view`` streams
past any cap (25 MiB and 64 KiB more). ``wrong_magic``: ``/view`` answers
text. ``video``: a WEBM under ``gifs`` and a PNG first frame under
``images``; ``video_no_poster``: the WEBM alone. ``native_video``: what
ComfyUI's native nodes answer -- a ``SaveWEBM`` node lists its WEBM under
``images`` (no first frame), every other save node (a ``SaveImage``) a PNG.

Version: v0.1.0 [2026-10-12]
"""

from __future__ import annotations

import argparse
import json
import os
import struct
import sys
import threading
import zlib
from pathlib import Path
from typing import Any, Callable, Iterator, Optional, Union
from urllib.parse import parse_qs, urlsplit

REPO = Path(__file__).resolve().parents[1]

#: Every script's name (``SCRIPTS``'s keys), in the order documented above.
SCRIPTS: dict[str, str] = {
    "ready": "the PNG after `polls` empty polls",
    "node_errors": "/prompt refused with node_errors (400)",
    "execution_error": "every history entry an execution error",
    "execution_error_once": "the first submit of a prompt errors, the next is ready",
    "never": "/history empty for ever",
    "hold": "/history empty for ever (the end-to-end test's restart)",
    "unauthorized": "401 on every route",
    "oversized": "/view streams past any cap",
    "wrong_magic": "/view answers text",
    "video": "a WEBM under gifs and a PNG first frame under images",
    "video_no_poster": "a WEBM under gifs alone",
    "native_video": "SaveWEBM nodes list a WEBM under images, other save nodes a PNG",
}

#: What ``oversized`` streams: past ``comfyui.max_bytes``' default.
OVERSIZED_BYTES = 26_214_400 + 65_536
_CHUNK = b"\x00" * 65_536

Body = Union[bytes, Iterator[bytes]]


def png_bytes() -> bytes:
    """A real 1x1 PNG."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    pixels = zlib.compress(b"\x00\xff\x80\x40")
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", pixels) + chunk(b"IEND", b"")


def webm_bytes() -> bytes:
    """An EBML header whose DocType is ``webm``, and a little padding: enough to sniff."""
    doctype = b"\x42\x82\x84webm"
    header = b"\x1a\x45\xdf\xa3" + bytes([0x80 | len(doctype)]) + doctype
    return header + b"\x00" * 32


class StubState:
    """Per-prompt counts (polls since its last submit, submits), shared by every request."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.polls: dict[str, int] = {}
        self.submits: dict[str, int] = {}
        self.outputs: dict[str, list[str]] = {}
        #: prompt id -> {node id: class_type} of its save nodes (``native_video``).
        self.classes: dict[str, dict[str, str]] = {}

    def submitted(self, prompt_id: str, nodes: list[str], classes: Optional[dict[str, str]] = None) -> None:
        with self._lock:
            self.submits[prompt_id] = self.submits.get(prompt_id, 0) + 1
            self.polls[prompt_id] = 0
            self.outputs[prompt_id] = nodes
            self.classes[prompt_id] = dict(classes or {})

    def class_of(self, prompt_id: str, node: str) -> str:
        with self._lock:
            return (self.classes.get(prompt_id) or {}).get(node, "")

    def polled(self, prompt_id: str) -> tuple[int, int, list[str]]:
        """``(polls before this one, submits, output nodes)``."""
        with self._lock:
            seen = self.polls.get(prompt_id, 0)
            self.polls[prompt_id] = seen + 1
            return seen, self.submits.get(prompt_id, 0), list(self.outputs.get(prompt_id) or ["7"])


def _json(status: int, payload: Any) -> tuple[int, str, Body]:
    return status, "application/json", json.dumps(payload).encode("utf-8")


def _output_nodes(graph: Any) -> list[str]:
    """The submitted graph's save nodes (a ``filename_prefix`` input), else every node."""
    if not isinstance(graph, dict) or not graph:
        return ["7"]
    saves = [str(k) for k, node in graph.items() if isinstance(node, dict) and "filename_prefix" in (node.get("inputs") or {})]
    return saves or [str(k) for k in graph]


def _files(script: str, prompt_id: str, class_type: str = "") -> dict[str, list[dict[str, str]]]:
    def ref(ext: str) -> dict[str, str]:
        return {"filename": f"{prompt_id}.{ext}", "subfolder": "", "type": "output"}

    if script == "native_video":
        return {"images": [ref("webm" if class_type == "SaveWEBM" else "png")]}
    if script == "video":
        return {"gifs": [ref("webm")], "images": [ref("png")]}
    if script == "video_no_poster":
        return {"gifs": [ref("webm")]}
    return {"images": [ref("png")]}


def _oversized() -> Iterator[bytes]:
    sent = 0
    while sent < OVERSIZED_BYTES:
        yield _CHUNK
        sent += len(_CHUNK)


def answer(
    script: str,
    method: str,
    path: str,
    query: dict[str, str],
    body: bytes,
    state: StubState,
    *,
    polls: int = 2,
) -> tuple[int, str, Body]:
    """``(status, content type, body)`` for one request under ``script``."""
    if script not in SCRIPTS:
        return _json(500, {"error": f"unknown stub script {script!r}"})
    if script == "unauthorized":
        return _json(401, {"error": "unauthorized"})
    if method == "GET" and path == "/system_stats":
        return _json(200, {"system": {"os": "stub", "comfyui_version": "stub"}, "devices": []})
    if method == "POST" and path == "/upload/image":
        return _json(200, {"name": "reference.png", "subfolder": "", "type": "input"})
    if method == "POST" and path == "/interrupt":
        return _json(200, {})
    if method == "POST" and path == "/prompt":
        try:
            request = json.loads(body.decode("utf-8") or "{}")
        except ValueError:
            return _json(400, {"error": "not json"})
        if script == "node_errors":
            return _json(
                400,
                {
                    "error": {"type": "prompt_outputs_failed_validation", "message": "Prompt outputs failed validation"},
                    "node_errors": {"1": {"errors": [{"type": "value_not_in_list", "message": "ckpt_name not found"}]}},
                },
            )
        prompt_id = f"p-{request.get('client_id') or 'anon'}"
        graph = request.get("prompt")
        nodes = _output_nodes(graph)
        classes = {n: str((graph.get(n) or {}).get("class_type", "")) for n in nodes} if isinstance(graph, dict) else {}
        state.submitted(prompt_id, nodes, classes)
        return _json(200, {"prompt_id": prompt_id, "number": 1, "node_errors": {}})
    if method == "GET" and path.startswith("/history/"):
        prompt_id = path[len("/history/"):]
        seen, submits, nodes = state.polled(prompt_id)
        if script in ("never", "hold"):
            return _json(200, {})
        failing = script == "execution_error" or (script == "execution_error_once" and submits <= 1)
        if failing:
            entry = {
                "status": {
                    "status_str": "error",
                    "completed": False,
                    "messages": [["execution_error", {"node_id": "5", "exception_message": "stub execution error"}]],
                },
                "outputs": {},
            }
            return _json(200, {prompt_id: entry})
        if seen < polls:
            return _json(200, {})
        outputs = {node: _files(script, prompt_id, state.class_of(prompt_id, node)) for node in nodes}
        entry = {"status": {"status_str": "success", "completed": True, "messages": []}, "outputs": outputs}
        return _json(200, {prompt_id: entry})
    if method == "GET" and path == "/view":
        filename = query.get("filename", "")
        if script == "oversized":
            return 200, "application/octet-stream", _oversized()
        if script == "wrong_magic":
            return 200, "text/plain", b"this is not an image, it is a sentence"
        if filename.endswith(".webm"):
            return 200, "video/webm", webm_bytes()
        return 200, "image/png", png_bytes()
    return _json(404, {"error": f"no route {method} {path}"})


# -- the loopback server -----------------------------------------------------


def _exit_with_parent(parent: Any = None, poll: float = 2.0, leave: Callable[[int], Any] = os._exit) -> Any:
    """
    A daemon thread that ends this process once its parent is gone (copied
    from ``scripts/screenshot_runs.py::_exit_with_parent``). The parent is its
    pid AND creation time, so a pid reused by a stranger is not followed: a
    parent that started AFTER this process cannot be its launcher, so it is
    treated as already gone. A parent that cannot be verified is a WARNING,
    never a silent no-op. Returns the thread, or None when nothing is watched.
    """
    import time

    from engine.hosting import process_identity

    parent = parent or process_identity.identify(os.getppid())
    if parent.created is None:
        print(
            f"comfy_stub: WARNING --exit-with-parent cannot verify its parent (pid {parent.pid}); "
            "this server will NOT exit when its launcher does",
            file=sys.stderr,
            flush=True,
        )
        return None
    mine = process_identity.me().created

    def watch() -> None:
        gone = mine is not None and parent.created > mine
        while not gone and process_identity.alive(parent):
            time.sleep(poll)
        print("comfy_stub: the parent process is gone; exiting", flush=True)
        leave(0)

    thread = threading.Thread(target=watch, name="exit-with-parent", daemon=True)
    thread.start()
    return thread


def make_server(
    port: int,
    *,
    script: str = "ready",
    polls: int = 2,
    control: Optional[Path] = None,
    log: Optional[Path] = None,
) -> Any:
    """A ``ThreadingHTTPServer`` on ``127.0.0.1:port`` answering through :func:`answer`."""
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    state = StubState()
    log_lock = threading.Lock()

    def current_script() -> str:
        if control is None:
            return script
        try:
            return str(json.loads(control.read_text(encoding="utf-8")).get("script") or script)
        except (OSError, ValueError):
            return script

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *_args: Any) -> None:  # quiet: --log is the record
            pass

        def _serve(self, method: str) -> None:
            parts = urlsplit(self.path)
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else b""
            query = {k: v[0] for k, v in parse_qs(parts.query).items()}
            if log is not None:
                record: dict[str, Any] = {"method": method, "path": parts.path}
                if parts.path == "/prompt":
                    try:
                        record["client_id"] = json.loads(body.decode("utf-8") or "{}").get("client_id")
                    except ValueError:
                        record["client_id"] = None
                with log_lock, log.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(record) + "\n")
            status, ctype, payload = answer(current_script(), method, parts.path, query, body, state, polls=polls)
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            if isinstance(payload, bytes):
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            try:
                for chunk in payload:
                    self.wfile.write(f"{len(chunk):x}\r\n".encode("ascii") + chunk + b"\r\n")
                self.wfile.write(b"0\r\n\r\n")
            except OSError:  # the client stopped reading at its cap
                self.close_connection = True

        def do_GET(self) -> None:  # noqa: N802
            self._serve("GET")

        def do_POST(self) -> None:  # noqa: N802
            self._serve("POST")

    server = ThreadingHTTPServer(("127.0.0.1", int(port)), Handler)
    server.daemon_threads = True
    return server


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="comfy_stub.py", description="A scripted stub ComfyUI on loopback.")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--script", choices=sorted(SCRIPTS), default="ready")
    parser.add_argument("--polls", type=int, default=2)
    parser.add_argument("--control", type=Path, default=None, help='a JSON file {"script": name}, re-read per request')
    parser.add_argument("--log", type=Path, default=None, help="append one JSON line per request")
    parser.add_argument("--exit-with-parent", action="store_true", help="exit when the launching process is gone")
    args = parser.parse_args(argv)
    if args.exit_with_parent:
        if str(REPO) not in sys.path:
            sys.path.insert(0, str(REPO))
        _exit_with_parent()
    server = make_server(args.port, script=args.script, polls=args.polls, control=args.control, log=args.log)
    print(f"comfy stub ({args.script}) on http://127.0.0.1:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
