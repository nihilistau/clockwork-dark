"""
``StubComfy``: an in-process ComfyUI for the phone's media tests (v0.22.0
spec §13.5) -- an ``httpx.MockTransport`` over ``scripts/comfy_stub.py``'s ONE
behaviour table (:data:`scripts.comfy_stub.SCRIPTS`, :func:`answer`), so the
loopback stub and this one cannot drift apart. No bind: safe in the parallel
phase.

``StubComfy(script="ready", *, polls=2)``: ``.transport`` for a
``ComfyClient``, ``.requests`` every ``httpx.Request`` it was sent, in order.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Iterator

import httpx

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.comfy_stub import SCRIPTS, StubState, answer, png_bytes, webm_bytes  # noqa: E402


class _Stream(httpx.SyncByteStream):
    def __init__(self, chunks: Iterator[bytes]) -> None:
        self._chunks = chunks

    def __iter__(self) -> Iterator[bytes]:
        yield from self._chunks


class StubComfy:
    """A scripted ComfyUI behind an ``httpx.MockTransport``."""

    def __init__(self, script: str = "ready", *, polls: int = 2) -> None:
        if script not in SCRIPTS:
            raise ValueError(f"unknown stub script {script!r} (one of {', '.join(SCRIPTS)})")
        self.script = script
        self.polls = polls
        self.requests: list[httpx.Request] = []
        self._state = StubState()
        self.transport = httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        query = {k: v for k, v in request.url.params.items()}
        status, ctype, body = answer(
            self.script, request.method, request.url.path, query, request.read(), self._state, polls=self.polls
        )
        headers = {"Content-Type": ctype}
        if isinstance(body, bytes):
            return httpx.Response(status, headers=headers, content=body, request=request)
        return httpx.Response(status, headers=headers, stream=_Stream(body), request=request)


__all__ = ["SCRIPTS", "StubComfy", "png_bytes", "webm_bytes"]
