"""
ComfyUI Client
==============

One ComfyUI server, local or hosted (v0.22.0 spec §13.4): its HTTP API --
``/system_stats``, ``/upload/image``, ``/prompt``, ``/history/<id>``,
``/view`` and ``/interrupt`` -- behind one class whose every call is bounded
by a timeout from config and whose every failure is a :class:`ComfyError`
with a ``kind``, never a raw ``httpx`` exception, so the caller (the art
provider, the phone's job worker) maps a failure to a status instead of
catching a library's exception tree.

WHAT IT DOES NOT DO. It builds no graph (``workflows.py`` binds a template)
and decides nothing about a request's words: the prompt reaches ComfyUI as the
caller wrote it. No filter, classifier or rewriting of any kind sits here
(AGENTS.md rule 12).

THE KEY. ``comfyui.api_key`` resolves through the config's ``${file:...|env:...}``
chain on every ``from_config`` and is sent in ``comfyui.auth_header``:
``Authorization: Bearer <key>`` by default, the key as written under any other
header name. It is never logged.

NOT VERIFIED against a live server unless docs/MEDIA_SERVERS.md says so; the
routes are ComfyUI's documented API, exercised here against an in-process
``httpx.MockTransport`` (``tests/test_comfy_client.py``).

Version: v0.1.0 [2026-10-12]
"""

from __future__ import annotations

import json
import time
from urllib.parse import quote
from typing import Any, Callable, Optional

import httpx

from engine import net
from engine.config import get_config

#: Every ``ComfyError.kind``. ``bad_type`` is the job worker's (an output whose
#: magic bytes name no type it stores) and ``cancelled`` the worker's own stop
#: mid-wait; the client raises the rest.
ERROR_KINDS = (
    "http",
    "node_errors",
    "execution",
    "timeout",
    "auth",
    "oversized",
    "bad_type",
    "unreachable",
    "cancelled",
)

#: The keys a history entry's output node lists its files under (§13.4 step 5).
OUTPUT_KEYS = ("images", "gifs", "videos", "audio")

#: How much of a server's error body a ComfyError keeps.
DETAIL_CHARS = 2000


class ComfyError(Exception):
    """A ComfyUI call that failed, by ``kind`` (one of :data:`ERROR_KINDS`)."""

    def __init__(self, kind: str, detail: str = "") -> None:
        if kind not in ERROR_KINDS:
            raise ValueError(f"unknown ComfyError kind {kind!r} (one of {', '.join(ERROR_KINDS)})")
        super().__init__(f"{kind}: {detail}" if detail else kind)
        self.kind = kind
        self.detail = detail


def _json_or_empty(response: httpx.Response) -> dict[str, Any]:
    """The response's JSON object, or ``{}`` for a body that is not one."""
    try:
        body = response.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


class ComfyClient:
    """
    One ComfyUI server (v0.22.0 spec §13.4): local or hosted, an optional key.
    Every call has a timeout; every failure is a ComfyError with a kind, never
    a raw httpx exception, so the job worker can map it to a status.
    NOT VERIFIED against a live server unless docs/MEDIA_SERVERS.md says so.
    """

    def __init__(
        self,
        base_url: str,
        *,
        api_key: str = "",
        auth_header: str = "Authorization",
        timeout: float = 120.0,
        max_bytes: int = 26_214_400,
        max_json_bytes: int = 1_048_576,
        transport: Optional[httpx.BaseTransport] = None,
    ) -> None:
        headers: dict[str, str] = {}
        if api_key:
            headers[auth_header] = (
                f"Bearer {api_key}" if auth_header.lower() == "authorization" else api_key
            )
        self.base_url = base_url.rstrip("/")
        self.max_bytes = int(max_bytes)
        self.max_json_bytes = int(max_json_bytes)
        self._http = httpx.Client(
            base_url=self.base_url,
            headers=headers,
            timeout=float(timeout),
            verify=net.ssl_context(),
            transport=transport,
        )

    @classmethod
    def from_config(
        cls,
        transport: Optional[httpx.BaseTransport] = None,
        *,
        timeout: Optional[float] = None,
    ) -> "ComfyClient":
        """
        A client on the ``comfyui.*`` connection keys. ``timeout`` overrides
        ``comfyui.timeout_seconds`` for a caller that wants a shorter bound (the
        art provider's availability probe).
        """
        cfg = get_config()
        return cls(
            str(cfg.get("comfyui.base_url", "http://localhost:8188")),
            api_key=str(cfg.get("comfyui.api_key", "") or ""),
            auth_header=str(cfg.get("comfyui.auth_header", "Authorization") or "Authorization"),
            timeout=float(timeout if timeout is not None else cfg.get("comfyui.timeout_seconds", 120)),
            max_bytes=int(cfg.get("comfyui.max_bytes", 26_214_400)),
            max_json_bytes=int(cfg.get("comfyui.max_json_bytes", 1_048_576)),
            transport=transport,
        )

    def __enter__(self) -> "ComfyClient":
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.close()

    def _call(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        """
        One API call (every route but ``/view``), its body streamed and refused
        past ``max_json_bytes`` (``oversized``): a misbehaving server cannot make
        a status or history read hold an unbounded body in memory.
        """
        try:
            request = self._http.build_request(method, path, **kwargs)
            streamed = self._http.send(request, stream=True)
            try:
                if streamed.status_code in (401, 403):
                    raise ComfyError("auth", f"{method} {path}: {streamed.status_code}")
                chunks: list[bytes] = []
                size = 0
                for chunk in streamed.iter_bytes():
                    size += len(chunk)
                    if size > self.max_json_bytes:
                        raise ComfyError("oversized", f"{method} {path}: over {self.max_json_bytes} bytes")
                    chunks.append(chunk)
            finally:
                streamed.close()
        except httpx.TimeoutException as exc:
            raise ComfyError("timeout", f"{method} {path}: {exc}") from None
        except httpx.HTTPError as exc:
            raise ComfyError("unreachable", f"{method} {path}: {exc}") from None
        # The body is already decoded; the copy carries no content headers.
        return httpx.Response(streamed.status_code, content=b"".join(chunks), request=request)

    def system_stats(self) -> dict[str, Any]:
        """The server's ``/system_stats``: up, and answering with this key."""
        response = self._call("GET", "/system_stats")
        if response.status_code != 200:
            raise ComfyError("http", f"system_stats: {response.status_code}")
        return _json_or_empty(response)

    def upload_image(self, data: bytes, name: str) -> str:
        """Upload an input image (a reference portrait); the name ComfyUI stored it under."""
        response = self._call(
            "POST",
            "/upload/image",
            files={"image": (name, data, "image/png")},
            data={"overwrite": "true"},
        )
        if response.status_code != 200:
            raise ComfyError("http", f"upload: {response.status_code}")
        return str(_json_or_empty(response).get("name") or name)

    def submit(self, graph: dict[str, Any], client_id: str) -> str:
        """
        Queue one graph; its ``prompt_id``. A 400 is ComfyUI refusing the graph
        (``node_errors``: a missing model, a bad input), kept in the detail.
        """
        response = self._call("POST", "/prompt", json={"prompt": graph, "client_id": client_id})
        if response.status_code == 400:
            body = _json_or_empty(response)
            refusal = body.get("node_errors") or body.get("error") or body or response.text
            raise ComfyError("node_errors", json.dumps(refusal)[:DETAIL_CHARS])
        if response.status_code != 200:
            raise ComfyError("http", f"prompt: {response.status_code}")
        prompt_id = str(_json_or_empty(response).get("prompt_id") or "")
        if not prompt_id:
            raise ComfyError("http", "prompt: no prompt_id returned")
        return prompt_id

    def history(self, prompt_id: str) -> Optional[dict[str, Any]]:
        """The history entry, or None while it is still queued or running."""
        response = self._call("GET", f"/history/{quote(prompt_id, safe='')}")
        if response.status_code != 200:
            raise ComfyError("http", f"history: {response.status_code}")
        entry = _json_or_empty(response).get(prompt_id)
        if not isinstance(entry, dict) or not entry:
            return None
        status = entry.get("status") or {}
        if status.get("status_str") == "error":
            raise ComfyError("execution", json.dumps(status.get("messages") or [])[:DETAIL_CHARS])
        if not status.get("completed", bool(entry.get("outputs"))):
            return None
        return entry

    def wait(
        self,
        prompt_id: str,
        *,
        poll_seconds: float,
        timeout: float,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], float] = time.monotonic,
    ) -> dict[str, Any]:
        """
        Poll ``history`` every ``poll_seconds`` until the entry is done. Past
        ``timeout`` seconds the server is asked to ``interrupt`` (best-effort)
        and ``ComfyError("timeout")`` is raised: a wait never spins forever.
        """
        deadline = now() + float(timeout)
        while True:
            entry = self.history(prompt_id)
            if entry is not None:
                return entry
            if now() >= deadline:
                self.interrupt()
                raise ComfyError("timeout", f"{prompt_id}: no result after {timeout:.0f}s")
            sleep(float(poll_seconds))

    @staticmethod
    def outputs(entry: dict[str, Any], node: str) -> list[dict[str, str]]:
        """The declared output node's files, under any of images, gifs, videos, audio (§13.4 step 5)."""
        out = (entry.get("outputs") or {}).get(node) or {}
        files: list[dict[str, str]] = []
        for key in OUTPUT_KEYS:
            for item in out.get(key) or []:
                if not isinstance(item, dict):
                    continue
                files.append(
                    {
                        "filename": str(item.get("filename", "")),
                        "subfolder": str(item.get("subfolder", "")),
                        "type": str(item.get("type", "output")),
                        "key": key,
                    }
                )
        return files

    def fetch(self, ref: dict[str, str]) -> bytes:
        """One output file's bytes, streamed and refused past ``max_bytes``."""
        params = {
            "filename": str(ref.get("filename", "")),
            "subfolder": str(ref.get("subfolder", "")),
            "type": str(ref.get("type", "output")),
        }
        chunks: list[bytes] = []
        size = 0
        try:
            with self._http.stream("GET", "/view", params=params) as response:
                if response.status_code in (401, 403):
                    raise ComfyError("auth", f"view: {response.status_code}")
                if response.status_code != 200:
                    raise ComfyError("http", f"view: {response.status_code}")
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > self.max_bytes:
                        raise ComfyError("oversized", f"view: over {self.max_bytes} bytes")
                    chunks.append(chunk)
        except httpx.TimeoutException as exc:
            raise ComfyError("timeout", f"view: {exc}") from None
        except httpx.HTTPError as exc:
            raise ComfyError("unreachable", f"view: {exc}") from None
        return b"".join(chunks)

    def interrupt(self) -> None:
        """Ask the server to stop the running job; best-effort (§13.4 step 4)."""
        try:
            self._call("POST", "/interrupt")
        except ComfyError:
            pass

    def close(self) -> None:
        self._http.close()
