"""
TTS Client (Voxtral)
====================

Speech synthesis, off the turn path.

Measured on this machine: a 42-character line took **73.9 s** of compute to
produce 3.44 s of audio -- 21.5x slower than realtime, at the fastest setting
(euler_steps 3), on a GPU it shares with LM Studio. A full narration of 90-150
words would take three to five minutes.

Three consequences shape this module:

1. **Synthesis never blocks a turn.** A background worker drains a queue; the
   turn returns immediately and the audio arrives later over the socket. The
   previous implementation called synthesize() inline and named the method
   ``enqueue_narration``, which was not true.
2. **Everything is cached to disk by content hash.** At this cost, re-speaking
   a line is unaffordable. Cache hits are the normal case for anything repeated.
3. **Text is split on sentence boundaries.** The server hard-rejects anything
   over 400 characters with HTTP 400, and says so explicitly: long input on
   this build does not degrade, it blows up.

Because of the cost, narration TTS is OFF by default. Short Assistant lines are
the only thing worth speaking live.

Version: v0.2.0 [2026-08-07]
"""

from __future__ import annotations

import hashlib
import logging
import queue
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

import httpx

from engine.config import get_config
from engine.media.queue import MediaJob, get_media_queue

logger = logging.getLogger(__name__)

AUDIO_DIR = Path("data/media/tts")

# Voxtral's own limit. Exceeding it is a 400, not a slow response.
SERVER_MAX_CHARS = 400

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def write_audio(payload: bytes, text: str, *, suffix: str = ".wav") -> str:
    """Persist audio under its content hash and return the fetch URL."""
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    path = AUDIO_DIR / f"{cache_key(text)}{suffix}"
    if not path.exists():
        path.write_bytes(payload)
    return f"/api/audio/{path.name}"


def cache_key(text: str, voice: str = "") -> str:
    return hashlib.sha256(f"{voice}|{text}".encode("utf-8")).hexdigest()[:16]


def cached_url(text: str, voice: str = "") -> Optional[str]:
    """Return the URL for previously synthesized audio, if we have it."""
    path = AUDIO_DIR / f"{cache_key(text)}.wav"
    return f"/api/audio/{path.name}" if path.exists() else None


def split_utterances(text: str, *, max_chars: int = SERVER_MAX_CHARS) -> list[str]:
    """
    Split text into server-acceptable utterances on sentence boundaries.

    Falls back to word boundaries for a single sentence longer than the limit,
    which is rare in narration but must not raise.
    """
    text = " ".join(text.split())
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    chunks: list[str] = []
    buffer = ""
    for sentence in _SENTENCE_SPLIT.split(text):
        if len(sentence) > max_chars:
            if buffer:
                chunks.append(buffer)
                buffer = ""
            words, line = sentence.split(), ""
            for word in words:
                if len(line) + len(word) + 1 > max_chars:
                    chunks.append(line)
                    line = word
                else:
                    line = f"{line} {word}".strip()
            if line:
                buffer = line
            continue

        if len(buffer) + len(sentence) + 1 > max_chars:
            chunks.append(buffer)
            buffer = sentence
        else:
            buffer = f"{buffer} {sentence}".strip()

    if buffer:
        chunks.append(buffer)
    return chunks


@dataclass
class SpeechRequest:
    """One queued utterance."""

    text: str
    voice: str
    session_id: str = ""
    kind: str = "narration"  # narration | assistant | npc
    sequence: int = 0


class TTSClient:
    """
    Synthesize narration audio via Voxtral.

    Falls back to text-only when the service is unavailable.
    """

    def __init__(self, base_url: Optional[str] = None) -> None:
        cfg = get_config()
        self.base_url = (
            base_url or cfg.get("tts.base_url", "http://127.0.0.1:8123")
        ).rstrip("/")
        self.fallback = str(cfg.get("tts.fallback", "text"))
        self.timeout = float(cfg.get("tts.timeout_seconds", 120))
        self.voice = str(cfg.get("tts.voice", "neutral_male"))
        self.max_chars = int(cfg.get("tts.max_chars", SERVER_MAX_CHARS))
        self.euler_steps = int(cfg.get("tts.euler_steps", 3))

    def is_available(self) -> bool:
        try:
            response = httpx.get(f"{self.base_url}/health", timeout=3.0)
            return response.status_code == 200
        except httpx.HTTPError:
            return False

    def synthesize(
        self,
        text: str,
        *,
        voice: str = "",
        style: str = "",
    ) -> dict[str, Any]:
        """
        Synthesize one utterance. Blocking and slow -- do not call from a turn.

        Returns a JSON-safe dict. Never returns raw bytes: this result is
        embedded in the turn payload, which is jsonify'd and emitted over
        Socket.IO, and bytes there raise TypeError and take down the turn.
        """
        text = text.strip()
        if not text:
            return {"success": False, "source": "empty", "text": ""}

        voice = voice or self.voice

        hit = cached_url(text, voice)
        if hit:
            return {"success": True, "source": "cache", "audio_url": hit, "text": text}

        if len(text) > self.max_chars:
            return {
                "success": False,
                "source": "too_long",
                "text": text,
                "message": (
                    f"{len(text)} chars exceeds the {self.max_chars} limit; "
                    "split with split_utterances() first"
                ),
            }

        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(
                    f"{self.base_url}/speak",
                    json={
                        "text": text,
                        "voice": voice,
                        "euler_steps": self.euler_steps,
                    },
                )
                response.raise_for_status()
                if "audio" in response.headers.get("content-type", ""):
                    return {
                        "success": True,
                        "source": "live",
                        "audio_url": write_audio(response.content, text),
                        "text": text,
                    }
                data = response.json()
                return {
                    "success": True,
                    "source": "live",
                    "audio_url": data.get("url", ""),
                    "text": text,
                }
        except httpx.HTTPError as exc:
            logger.warning("[tts] Synthesis failed (operation=synthesize): %s", exc)
            return {
                "success": False,
                "source": self.fallback,
                "text": text,
                "message": str(exc),
            }

    def enqueue_narration(
        self,
        text: str,
        *,
        voice: str = "storyteller",
        style: str = "",
    ) -> MediaJob:
        """
        Queue narration for background synthesis.

        Returns immediately with a job whose url is filled in only on a cache
        hit; otherwise the audio arrives later via the speech worker.
        """
        media_queue = get_media_queue()
        hit = cached_url(text, voice)
        job = MediaJob(
            job_id=media_queue.new_job_id(),
            kind="tts",
            cache_key=cache_key(text, voice),
            prompt=text,
            payload={"voice": voice, "style": style, "utterances": len(
                split_utterances(text, max_chars=self.max_chars)
            )},
            status="ready" if hit else "queued",
            url=hit or "",
        )
        return media_queue.enqueue(job)


class SpeechWorker:
    """
    Background synthesis queue.

    One worker thread, matching the server's own serial design: two concurrent
    syntheses contend for the same GPU and the second is not faster for having
    started.
    """

    def __init__(
        self,
        client: Optional[TTSClient] = None,
        *,
        on_ready: Optional[Callable[[SpeechRequest, str], None]] = None,
    ) -> None:
        self._client = client or TTSClient()
        self._queue: "queue.Queue[Optional[SpeechRequest]]" = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self._on_ready = on_ready
        self._stop = threading.Event()

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="tts-worker", daemon=True
        )
        self._thread.start()
        logger.info("[tts] Speech worker started (operation=start)")

    def stop(self) -> None:
        self._stop.set()
        self._queue.put(None)
        if self._thread is not None:
            self._thread.join(timeout=5)

    def submit(
        self,
        text: str,
        *,
        voice: str = "",
        session_id: str = "",
        kind: str = "narration",
    ) -> int:
        """
        Queue text for synthesis. Returns the number of utterances queued.

        Splitting happens here so the queue holds only server-legal work.
        """
        utterances = split_utterances(text, max_chars=self._client.max_chars)
        for index, utterance in enumerate(utterances):
            self._queue.put(
                SpeechRequest(
                    text=utterance,
                    voice=voice or self._client.voice,
                    session_id=session_id,
                    kind=kind,
                    sequence=index,
                )
            )
        return len(utterances)

    def pending(self) -> int:
        return self._queue.qsize()

    def _run(self) -> None:
        while not self._stop.is_set():
            request = self._queue.get()
            if request is None:
                break
            try:
                result = self._client.synthesize(request.text, voice=request.voice)
                url = str(result.get("audio_url", ""))
                if url and self._on_ready is not None:
                    self._on_ready(request, url)
            except Exception as exc:  # noqa: BLE001 — a bad line must not kill the worker
                logger.warning("[tts] Worker item failed (operation=_run): %s", exc)
            finally:
                self._queue.task_done()


_worker: Optional[SpeechWorker] = None


def get_speech_worker() -> SpeechWorker:
    """Process-wide speech worker."""
    global _worker
    if _worker is None:
        _worker = SpeechWorker()
        _worker.start()
    return _worker


def reset_speech_worker() -> None:
    """Stop and drop the worker. Tests only."""
    global _worker
    if _worker is not None:
        _worker.stop()
    _worker = None


def tts_enabled() -> bool:
    """
    Whether narration should be spoken at all.

    Off by default: at 21x realtime, speaking a full narration costs minutes.
    """
    return bool(get_config().get("tts.enabled", False))
