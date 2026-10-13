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

The cache is keyed by the text AND the voice (``cache_key``) in every reader
and writer since v0.22.0: before, two voices saying one line shared the first
voice's file. A phone voice note (v0.22.0, ``engine/social/media.py``) is a
request with ``on_done``: spoken uncached (``TTSClient.speak``), never kept
in the shared cache, its answer bounded by ``tts.max_bytes`` and typed by its
magic bytes (a WAV), its wait in the queue by its deadline.

Version: v0.3.0 [2026-10-12]
"""

from __future__ import annotations

import hashlib
import json
import logging
import queue
import re
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

import httpx

from engine import net
from engine.config import get_config
from engine.locks import renew_after_fork
from engine.media.queue import MediaJob, get_media_queue
from engine.persistence import storage

logger = logging.getLogger(__name__)

# Synthesized audio lives in `storage.audio_dir()` (`<storage root>/media/tts`),
# read on every call and anchored at the repository since v0.20.0.

# Voxtral's own limit. Exceeding it is a 400, not a slow response.
SERVER_MAX_CHARS = 400

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")

#: A response body's ceiling when ``tts.max_bytes`` is not set (8 MiB: a
#: 15 s note at 48 kHz stereo 16-bit is under 3 MiB).
DEFAULT_MAX_BYTES = 8 * 1024 * 1024


class TTSError(Exception):
    """A synthesis that produced no usable audio (unreachable, refused, too big, not a WAV)."""


def is_wav(data: bytes) -> bool:
    """A RIFF/WAVE file by its magic bytes (never by a Content-Type)."""
    head = bytes(data[:12])
    return len(head) == 12 and head[:4] == b"RIFF" and head[8:12] == b"WAVE"


def write_audio(payload: bytes, text: str, *, voice: str = "", suffix: str = ".wav") -> str:
    """
    Persist audio under its content hash -- the text AND the voice that
    speaks it (`cache_key`) -- and return the fetch URL. Before v0.22.0 the
    file was named by the text alone, so the first voice to say a line
    answered for every voice after it (F7).
    """
    audio = storage.audio_dir()
    audio.mkdir(parents=True, exist_ok=True)
    path = audio / f"{cache_key(text, voice)}{suffix}"
    if not path.exists():
        path.write_bytes(payload)
    return f"/api/audio/{path.name}"


def cache_key(text: str, voice: str = "") -> str:
    """A spoken line's file name: the text and the voice (every reader and writer keys by both)."""
    return hashlib.sha256(f"{voice}|{text}".encode("utf-8")).hexdigest()[:16]


def cached_url(text: str, voice: str = "") -> Optional[str]:
    """
    Return the URL for previously synthesized audio in ``voice``, if we have
    it. Narration cached before v0.22.0 was named by the text alone
    (``cache_key(text, "")``), and the only voice it could have been spoken in
    is the configured ``tts.voice``: for that voice the old name is read too,
    so an owner's existing cache stays valid (T21 review M3).
    """
    audio = storage.audio_dir()
    path = audio / f"{cache_key(text, voice)}.wav"
    if path.exists():
        return f"/api/audio/{path.name}"
    if voice and voice == str(get_config().get("tts.voice", "neutral_male")):
        legacy = audio / f"{cache_key(text, '')}.wav"
        if legacy.exists():
            return f"/api/audio/{legacy.name}"
    return None


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
    kind: str = "narration"  # narration | assistant | npc | voice_note
    sequence: int = 0
    #: A request with ``on_done`` (a phone voice note, v0.22.0) is SPOKEN, not
    #: cached (``TTSClient.speak``), and ``on_done(request, outcome)`` hears
    #: ``{"ok": True, "audio": bytes}`` or ``{"ok": False, "error": str}``
    #: whatever happened. ``on_ready`` is never called for it.
    on_done: Optional[Callable[["SpeechRequest", dict[str, Any]], None]] = None
    #: ``time.monotonic()`` past which the request is not started (0: none);
    #: its ``on_done`` hears ``expired``.
    deadline: float = 0.0
    #: An ``on_done`` request's identity (a voice note's owner, save, mid and
    #: request digest): a second submit of a key still queued or speaking is
    #: not queued again -- it RETARGETS the pending request (its ``on_done``
    #: and deadline), so a resumed run is handed the note it resubmitted.
    key: Optional[tuple] = None


class TTSClient:
    """
    Synthesize narration audio via Voxtral.

    Falls back to text-only when the service is unavailable.
    """

    def __init__(self, base_url: Optional[str] = None, *,
                 transport: Optional[httpx.BaseTransport] = None) -> None:
        cfg = get_config()
        #: Tests only: an in-process transport (``httpx.MockTransport``), no socket.
        self._transport = transport
        self.base_url = (
            base_url or cfg.get("tts.base_url", "http://127.0.0.1:8123")
        ).rstrip("/")
        self.fallback = str(cfg.get("tts.fallback", "text"))
        self.timeout = float(cfg.get("tts.timeout_seconds", 120))
        self.voice = str(cfg.get("tts.voice", "neutral_male"))
        self.max_chars = int(cfg.get("tts.max_chars", SERVER_MAX_CHARS))
        self.euler_steps = int(cfg.get("tts.euler_steps", 3))
        self.max_bytes = int(cfg.get("tts.max_bytes", DEFAULT_MAX_BYTES))

    def _post(self, text: str, voice: str) -> tuple[str, bytes]:
        """
        ``POST /speak``: ``(content_type, body)``, the body read to at most
        ``max_bytes`` (a byte more is a ``TTSError``, the rest never read).
        Bounded by ``timeout_seconds``. Raises ``httpx.HTTPError`` as before.
        """
        kwargs: dict[str, Any] = {"timeout": self.timeout}
        if self._transport is not None:
            kwargs["transport"] = self._transport
        else:
            kwargs["verify"] = net.ssl_context()
        with httpx.Client(**kwargs) as client:
            with client.stream("POST", f"{self.base_url}/speak",
                               json={"text": text, "voice": voice, "euler_steps": self.euler_steps}) as response:
                response.raise_for_status()
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > self.max_bytes:
                        raise TTSError(f"the audio is over {self.max_bytes} bytes")
                return response.headers.get("content-type", ""), bytes(body)

    def speak(self, text: str, *, voice: str = "") -> bytes:
        """
        One utterance's WAV bytes, UNCACHED: a voice note's file belongs to
        its owner's save, never to the shared narration cache (v0.22.0).
        Blocking and slow. Raises ``TTSError`` for anything but a WAV within
        ``max_bytes``.
        """
        text = " ".join(str(text or "").split())
        if not text:
            raise TTSError("nothing to say")
        if len(text) > self.max_chars:
            raise TTSError(f"{len(text)} chars exceeds the {self.max_chars} limit")
        try:
            _, body = self._post(text, voice or self.voice)
        except httpx.HTTPError as exc:
            raise TTSError(str(exc)) from exc
        if not is_wav(body):
            raise TTSError("the answer is not a WAV")
        return body

    def is_available(self) -> bool:
        try:
            response = net.get(f"{self.base_url}/health", timeout=3.0)
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
            content_type, body = self._post(text, voice)
            if "audio" in content_type:
                if not is_wav(body):
                    raise TTSError("the answer is not a WAV")
                return {
                    "success": True,
                    "source": "live",
                    "audio_url": write_audio(body, text, voice=voice),
                    "text": text,
                }
            data = json.loads(body.decode("utf-8") or "{}")
            return {
                "success": True,
                "source": "live",
                "audio_url": str(data.get("url", "")) if isinstance(data, dict) else "",
                "text": text,
            }
        except (httpx.HTTPError, TTSError, ValueError) as exc:
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
        #: A LEAF (engine/locks.py): guards only ``_pending``; no synthesis,
        #: config read, log line or ``on_done`` runs under it.
        self._lock = threading.Lock()
        #: Keyed ``on_done`` requests queued or speaking, by ``key``.
        self._pending: dict[tuple, SpeechRequest] = {}

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
        on_done: Optional[Callable[[SpeechRequest, dict[str, Any]], None]] = None,
        deadline: float = 0.0,
        key: Optional[tuple] = None,
    ) -> int:
        """
        Queue text for synthesis. Returns the number of utterances queued.

        Splitting happens here so the queue holds only server-legal work. A
        request with ``on_done`` must be ONE utterance (a voice note's
        transcript is cut far below the server's limit): anything else is
        refused, 0 queued.
        """
        utterances = split_utterances(text, max_chars=self._client.max_chars)
        if on_done is not None and len(utterances) != 1:
            return 0
        if on_done is not None and key is not None:
            with self._lock:
                pending = self._pending.get(key)
                if pending is not None:            # a resubmission: retarget, never queue twice
                    pending.on_done, pending.deadline = on_done, deadline
                    return 1
                request = SpeechRequest(text=utterances[0], voice=voice or self._client.voice,
                                        session_id=session_id, kind=kind, on_done=on_done,
                                        deadline=deadline, key=key)
                self._pending[key] = request
            self._queue.put(request)
            return 1
        for index, utterance in enumerate(utterances):
            self._queue.put(
                SpeechRequest(
                    text=utterance,
                    voice=voice or self._client.voice,
                    session_id=session_id,
                    kind=kind,
                    sequence=index,
                    on_done=on_done,
                    deadline=deadline,
                )
            )
        return len(utterances)

    def pending(self) -> int:
        return self._queue.qsize()

    def holds(self, key: tuple) -> bool:
        """Whether a keyed request is queued or speaking now."""
        with self._lock:
            return key in self._pending

    def _run(self) -> None:
        while not self._stop.is_set():
            request = self._queue.get()
            if request is None:
                break
            if request.on_done is not None:
                try:
                    self._speak(request)
                finally:
                    self._queue.task_done()
                continue
            try:
                result = self._client.synthesize(request.text, voice=request.voice)
                url = str(result.get("audio_url", ""))
                if url and self._on_ready is not None:
                    self._on_ready(request, url)
            except Exception as exc:  # noqa: BLE001 — a bad line must not kill the worker
                logger.warning("[tts] Worker item failed (operation=_run): %s", exc)
            finally:
                self._queue.task_done()


    def _speak(self, request: SpeechRequest) -> None:
        """A request with ``on_done``: spoken (uncached) unless past its deadline; ``on_done`` always told."""
        if request.deadline and time.monotonic() > request.deadline:
            outcome: dict[str, Any] = {"ok": False, "error": "expired"}
        else:
            try:
                outcome = {"ok": True, "audio": self._client.speak(request.text, voice=request.voice)}
            except TTSError as exc:
                outcome = {"ok": False, "error": str(exc)[:300]}
            except Exception as exc:  # noqa: BLE001 -- a bad line must not kill the worker
                logger.warning("[tts] Voice note failed (operation=_speak): %s", exc)
                outcome = {"ok": False, "error": type(exc).__name__}
        with self._lock:
            # Read and released together: a resubmission from here on queues afresh.
            if request.key is not None:
                self._pending.pop(request.key, None)
            on_done = request.on_done
        try:
            if on_done is not None:
                on_done(request, outcome)
        except Exception:  # noqa: BLE001 -- the hand-off's own fault, never the worker's end
            logger.exception("[tts] Hand-off failed (operation=_speak, kind=%s)", request.kind)


_worker: Optional[SpeechWorker] = None
#: Guards building and starting ``_worker`` (v0.20.0): two first callers used
#: to start two speech threads.
_worker_lock = threading.Lock()
renew_after_fork(globals(), _worker_lock=threading.Lock)


def get_speech_worker() -> SpeechWorker:
    """Process-wide speech worker (double-checked: no lock once built)."""
    global _worker
    worker = _worker
    if worker is not None:
        return worker
    with _worker_lock:
        if _worker is None:
            built = SpeechWorker()
            built.start()
            _worker = built
        return _worker


def reset_speech_worker() -> None:
    """Stop and drop the worker. Tests only. The reference is swapped under
    the lock; the old worker is stopped (its thread joined) after it."""
    global _worker
    with _worker_lock:
        old, _worker = _worker, None
    if old is not None:
        old.stop()


def tts_enabled() -> bool:
    """
    Whether narration should be spoken at all.

    Off by default: at 21x realtime, speaking a full narration costs minutes.
    """
    return bool(get_config().get("tts.enabled", False))
