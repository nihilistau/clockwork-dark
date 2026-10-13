"""
An in-process Voxtral TTS server for tests (v0.22.0 T21): an
``httpx.MockTransport`` answering ``POST /speak`` -- no bind, no socket, safe
in the parallel phase. Handed to ``TTSClient(transport=...)``.

Behaviours: ``ok`` (a WAV as long as the words take at 150 a minute, at
least ``seconds``), ``down`` (503), ``not_wav`` (``audio/wav`` that is not
one), ``oversize`` (a body past any sane ``max_bytes``) and ``long`` (a WAV
far longer than the words).
"""

from __future__ import annotations

import io
import json
import threading
import wave

import httpx


def wav_bytes(seconds: float = 1.0, rate: int = 8000) -> bytes:
    """A silent mono 16-bit WAV of ``seconds``."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(b"\x00\x00" * int(seconds * rate))
    return buffer.getvalue()


class StubTTS:
    def __init__(self, behaviour: str = "ok", *, seconds: float = 1.0) -> None:
        self.behaviour = behaviour
        self.seconds = seconds
        self.requests: list[dict] = []
        self._lock = threading.Lock()
        self.transport = httpx.MockTransport(self._answer)

    def _answer(self, request: httpx.Request) -> httpx.Response:
        if request.url.path != "/speak":
            return httpx.Response(404)
        body = json.loads(request.content or b"{}")
        with self._lock:
            self.requests.append(body)
        if self.behaviour == "down":
            return httpx.Response(503, text="busy")
        if self.behaviour == "not_wav":
            return httpx.Response(200, content=b"<html>no</html>", headers={"content-type": "audio/wav"})
        if self.behaviour == "oversize":
            return httpx.Response(200, content=b"RIFF\x00\x00\x00\x00WAVE" + b"\x00" * (9 * 1024 * 1024),
                                  headers={"content-type": "audio/wav"})
        words = len(str(body.get("text") or "").split())
        seconds = max(self.seconds, words * 60.0 / 150.0)
        if self.behaviour == "long":
            return httpx.Response(200, content=wav_bytes(600.0, rate=1000), headers={"content-type": "audio/wav"})
        return httpx.Response(200, content=wav_bytes(seconds), headers={"content-type": "audio/wav"})
