"""
faster-whisper STT provider
===========================

CTranslate2 Whisper, running in this process. The best-optimised local ASR on
Windows: no server to start, no CLI to shell out to, and int8 on CPU is fast
enough that a two-second push-to-talk utterance comes back before the player has
finished letting go of the button.

CONFIG
------
::

    stt:
      provider: faster_whisper
      whisper:
        model: distil-small.en   # any faster-whisper size or HF repo id
        device: auto             # auto | cuda | cpu
        compute_type: ""         # blank -> float16 on CUDA, int8 on CPU
        language: ""             # blank -> autodetect
        beam_size: 1
        vad_filter: true

THE MODEL IS LOADED LAZILY AND CACHED
-------------------------------------
Never at import: importing ``faster_whisper`` alone pulls CTranslate2 and its
native library, and constructing ``WhisperModel`` downloads weights on first
use. Doing either at import time would make ``import engine.media.stt`` -- which
happens on any route that touches the Assistant -- either slow or fatal. So the
first transcription pays for the load and every later one is free, and the cache
is keyed on (model, device, compute_type) so a Settings change rebinds rather
than silently keeping the old model.

THE DEPENDENCY IS OPTIONAL
--------------------------
``faster-whisper`` is in requirements.txt, but this module must not need it to
be importable. A machine without it gets a result dict whose ``message`` says
exactly what to install -- the same shape a dead service returns -- so
push-to-talk degrades to "nothing was heard" instead of taking down the turn.
The whole test suite runs green without it installed.

Version: v0.1.0 [2026-08-13]
"""

from __future__ import annotations

import logging
import os
import tempfile
import threading
from typing import Any, Optional

from engine.config import get_config
from engine.media.stt import PROVIDER_FASTER_WHISPER, empty_result

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "distil-small.en"

INSTALL_HINT = (
    "faster-whisper is not installed. Push-to-talk needs it: "
    "pip install faster-whisper  (or switch stt.provider to voxtral_http)"
)

# Loaded models, keyed by (model, device, compute_type). Module-level so two
# sessions in one process share one set of weights.
_models: dict[tuple[str, str, str], Any] = {}
_models_lock = threading.Lock()


def reset_whisper_models() -> None:
    """Drop every loaded model. Tests, and a provider rebind."""
    with _models_lock:
        _models.clear()


def _cuda_available() -> bool:
    """
    Whether CTranslate2 can see a GPU.

    Asked of CTranslate2 rather than torch: faster-whisper does not depend on
    torch, so a torch-based check would be answering about a library that need
    not be installed, and would say "no GPU" on a perfectly good CUDA box.
    """
    try:
        import ctranslate2  # noqa: PLC0415 -- optional dependency, lazy on purpose

        return int(ctranslate2.get_cuda_device_count()) > 0
    except Exception as exc:  # noqa: BLE001 -- any failure means "assume CPU"
        logger.debug("[stt] CUDA probe failed (operation=_cuda_available): %s", exc)
        return False


def resolve_device(requested: str = "auto") -> tuple[str, str]:
    """
    Settle on (device, compute_type).

    Returns:
        ``("cuda", "float16")`` when a GPU is visible and wanted, otherwise
        ``("cpu", "int8")``. int8 is not a compromise on CPU -- it is the only
        quantisation that makes a Whisper encoder run at conversational speed
        there, and on a short utterance the accuracy cost is not audible.
    """
    wanted = (requested or "auto").strip().lower()
    if wanted == "cuda" or (wanted == "auto" and _cuda_available()):
        return "cuda", "float16"
    return "cpu", "int8"


class WhisperSTTProvider:
    """Transcribe audio with a lazily-loaded, cached faster-whisper model."""

    name = PROVIDER_FASTER_WHISPER

    def __init__(self) -> None:
        cfg = get_config()
        self.model_name = str(cfg.get("stt.whisper.model", "") or DEFAULT_MODEL)
        self.requested_device = str(cfg.get("stt.whisper.device", "auto") or "auto")
        self.compute_type = str(cfg.get("stt.whisper.compute_type", "") or "")
        self.language = str(cfg.get("stt.whisper.language", "") or "")
        self.beam_size = int(cfg.get("stt.whisper.beam_size", 1) or 1)
        self.vad_filter = bool(cfg.get("stt.whisper.vad_filter", True))

    # -- model ---------------------------------------------------------------

    def binding(self) -> tuple[str, str, str]:
        """The (model, device, compute_type) this provider would load."""
        device, default_compute = resolve_device(self.requested_device)
        return self.model_name, device, (self.compute_type or default_compute)

    def load(self) -> Any:
        """
        Return the cached model, loading it on first use.

        Raises:
            ImportError: faster-whisper is not installed.
            Exception: the model could not be built (bad name, no disk, no net).
        """
        key = self.binding()
        with _models_lock:
            cached = _models.get(key)
        if cached is not None:
            return cached

        from faster_whisper import WhisperModel  # noqa: PLC0415 -- optional, lazy

        model_name, device, compute_type = key
        logger.info(
            "[stt] Loading Whisper (operation=load, model=%s, device=%s, compute=%s) "
            "-- first transcription pays for this once",
            model_name,
            device,
            compute_type,
        )
        model = WhisperModel(model_name, device=device, compute_type=compute_type)
        with _models_lock:
            _models[key] = model
        return model

    # -- transcription -------------------------------------------------------

    def transcribe(
        self,
        audio_bytes: bytes,
        *,
        content_type: str = "audio/wav",
        language: str = "en",
    ) -> dict[str, Any]:
        """
        Transcribe one utterance.

        Args:
            audio_bytes: Whatever MediaRecorder produced -- webm/opus, ogg or
                wav. Decoding is ffmpeg's job, via faster-whisper's reader, so
                the container does not have to be negotiated with the browser.
            content_type: Advisory only; kept for interface parity.
            language: BCP-47 hint. ``stt.whisper.language`` wins if set; an
                empty hint means autodetect.

        Returns:
            The shared STT result dict. Never raises.
        """
        if not audio_bytes:
            return empty_result(self.name)

        try:
            model = self.load()
        except ImportError:
            logger.warning("[stt] %s (operation=transcribe)", INSTALL_HINT)
            return self._failure(INSTALL_HINT, source="unavailable")
        except Exception as exc:  # noqa: BLE001 -- a bad model name must not kill the turn
            model_name, device, compute = self.binding()
            logger.error(
                "[stt] Whisper model would not load (operation=transcribe, "
                "model=%s, device=%s, compute=%s): %s",
                model_name,
                device,
                compute,
                exc,
            )
            return self._failure(f"could not load Whisper model {model_name!r}: {exc}")

        # faster-whisper reads a path or a file-like; a named temp file is the
        # portable option on Windows, where a still-open NamedTemporaryFile
        # cannot be reopened by another handle.
        path = ""
        try:
            handle, path = tempfile.mkstemp(suffix=".audio")
            with os.fdopen(handle, "wb") as sink:
                sink.write(audio_bytes)

            hint = self.language or (language or "").strip()
            segments, info = model.transcribe(
                path,
                language=hint or None,
                beam_size=self.beam_size,
                vad_filter=self.vad_filter,
            )
            # `segments` is a generator: the work happens here, not above.
            transcript = " ".join(segment.text.strip() for segment in segments).strip()
        except Exception as exc:  # noqa: BLE001 -- decode failures are a dead mic, not a crash
            logger.warning(
                "[stt] Transcription failed (operation=transcribe, provider=%s): %s",
                self.name,
                exc,
            )
            return self._failure(str(exc))
        finally:
            if path:
                try:
                    os.unlink(path)
                except OSError:
                    pass

        model_name, device, compute = self.binding()
        return {
            "success": bool(transcript),
            "transcript": transcript,
            "source": "live",
            "provider": self.name,
            "raw": {
                "model": model_name,
                "device": device,
                "compute_type": compute,
                "language": getattr(info, "language", "") or "",
                "language_probability": float(
                    getattr(info, "language_probability", 0.0) or 0.0
                ),
                "duration": float(getattr(info, "duration", 0.0) or 0.0),
            },
        }

    def _failure(self, message: str, *, source: str = "stub") -> dict[str, Any]:
        return {
            "success": False,
            "transcript": "",
            "source": source,
            "provider": self.name,
            "message": message,
        }


def whisper_installed() -> bool:
    """Whether ``faster_whisper`` can be imported. For the doctor, not the turn."""
    import importlib.util  # noqa: PLC0415

    return importlib.util.find_spec("faster_whisper") is not None


__all__ = [
    "DEFAULT_MODEL",
    "INSTALL_HINT",
    "WhisperSTTProvider",
    "reset_whisper_models",
    "resolve_device",
    "whisper_installed",
]
