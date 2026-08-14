"""
Speech-to-Text
==============

One provider interface, two implementations, one caller-visible contract.

    transcribe_audio(audio_bytes) -> {"success", "transcript", "source",
                                      "provider", "message"?, "raw"?}

``POST /api/voice/transcribe`` (engine/api/voice.py) does not know or care which
provider answered; neither does ``AssistantAgent.process_voice_input``. The
provider is chosen by ``stt.provider``:

    faster_whisper   CTranslate2 Whisper, in this process (engine/media/stt_whisper.py)
    voxtral_http     POST {stt.base_url}/v1/audio/transcriptions

``stt.provider`` REPLACES ``stt.mode``, and the rename is a correction rather
than a preference. ``stt.mode: voxtral_cli`` was documented in
config/default.yaml as "the adapter shells out to the binary" -- and no adapter
in this file ever shelled out to anything. The only code that existed POSTed
multipart audio to an OpenAI-compatible transcription endpoint that nothing on
this machine serves, and the key was read NOWHERE, so the mode had no effect
either way. ``stt.mode`` is still honoured (with a warning) so an existing
config/local.yaml keeps working, and ``voxtral_cli`` maps onto the HTTP
provider, because that is what it has always actually been.

WHY THE DEPENDENCY IS OPTIONAL. ``faster-whisper`` pulls CTranslate2 and a model
download. The game must boot, and the whole test suite must pass, on a machine
that has neither -- so the import lives inside the call, and its absence is a
legible message on the transcript result rather than an ImportError at startup.

Version: v0.2.0 [2026-08-13]
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Optional, Protocol

import httpx

from engine.config import get_config

logger = logging.getLogger(__name__)

PROVIDER_FASTER_WHISPER = "faster_whisper"
PROVIDER_VOXTRAL_HTTP = "voxtral_http"

STT_PROVIDERS: tuple[str, ...] = (PROVIDER_FASTER_WHISPER, PROVIDER_VOXTRAL_HTTP)

# Names that used to appear under `stt.mode`. `voxtral_cli` never had a CLI
# adapter behind it (see the module docstring), so it resolves to the HTTP
# client it has always been.
_PROVIDER_ALIASES: dict[str, str] = {
    "voxtral_cli": PROVIDER_VOXTRAL_HTTP,
    "voxtral": PROVIDER_VOXTRAL_HTTP,
    "http": PROVIDER_VOXTRAL_HTTP,
    "whisper": PROVIDER_FASTER_WHISPER,
}

DEFAULT_PROVIDER = PROVIDER_FASTER_WHISPER


class STTProvider(Protocol):
    """What a transcription backend has to be able to do."""

    name: str

    def transcribe(
        self,
        audio_bytes: bytes,
        *,
        content_type: str = "audio/wav",
        language: str = "en",
    ) -> dict[str, Any]:
        """Return the shared result dict. Never raises for a service failure."""


def empty_result(provider: str) -> dict[str, Any]:
    """The answer to zero bytes of audio. Shared so every provider agrees."""
    return {
        "success": False,
        "transcript": "",
        "source": "stub",
        "provider": provider,
        "message": "Empty audio payload.",
    }


class STTClient:
    """
    Transcribe audio by POSTing it to an OpenAI-compatible endpoint.

    Kept under its original name because ``AssistantAgent(stt_client=...)`` is
    typed on it. Nothing on the default stack serves this route -- Voxtral ASR
    ships as a CLI, not a server -- so this provider is here for a Whisper.cpp
    or whisper-server install, and ``faster_whisper`` is the default.
    """

    name = PROVIDER_VOXTRAL_HTTP

    def __init__(self, base_url: Optional[str] = None) -> None:
        cfg = get_config()
        self.base_url = (base_url or cfg.get("stt.base_url", "http://localhost:5051")).rstrip(
            "/"
        )
        self.timeout = float(cfg.get("stt.timeout_seconds", 30))

    def transcribe(
        self,
        audio_bytes: bytes,
        *,
        content_type: str = "audio/wav",
        language: str = "en",
    ) -> dict[str, Any]:
        """
        POST audio to the STT endpoint.

        Args:
            audio_bytes: Raw audio payload.
            content_type: MIME type for upload.
            language: BCP-47 language hint.

        Returns:
            Dict with transcript, success, source (live|stub) and provider.
        """
        if not audio_bytes:
            return empty_result(self.name)

        url = f"{self.base_url}/v1/audio/transcriptions"
        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(
                    url,
                    files={"file": ("audio.wav", audio_bytes, content_type)},
                    data={"language": language},
                )
                response.raise_for_status()
                data = response.json()
                transcript = str(data.get("text") or data.get("transcript") or "").strip()
                return {
                    "success": bool(transcript),
                    "transcript": transcript,
                    "source": "live",
                    "provider": self.name,
                    "raw": data,
                }
        except Exception as exc:
            logger.warning(
                "[stt] Service unavailable (operation=transcribe, provider=%s): %s",
                self.name,
                exc,
            )
            return {
                "success": False,
                "transcript": "",
                "source": "stub",
                "provider": self.name,
                "message": str(exc),
            }


def resolve_provider_name() -> str:
    """
    Which provider ``stt.provider`` (or the legacy ``stt.mode``) names.

    An unknown name falls back to the default and says so, rather than leaving
    push-to-talk quietly dead.
    """
    cfg = get_config()
    raw = str(cfg.get("stt.provider", "") or "").strip().lower()
    if not raw:
        legacy = str(cfg.get("stt.mode", "") or "").strip().lower()
        if legacy:
            logger.warning(
                "[stt] `stt.mode` is the old name for `stt.provider` and will "
                "stop being read (operation=resolve_provider_name, mode=%s)",
                legacy,
            )
            raw = legacy
    if not raw:
        return DEFAULT_PROVIDER

    resolved = _PROVIDER_ALIASES.get(raw, raw)
    if resolved not in STT_PROVIDERS:
        logger.warning(
            "[stt] Unknown provider; using %s (operation=resolve_provider_name, "
            "requested=%s, known=%s)",
            DEFAULT_PROVIDER,
            raw,
            ", ".join(STT_PROVIDERS),
        )
        return DEFAULT_PROVIDER
    return resolved


def build_provider(name: Optional[str] = None) -> STTProvider:
    """Construct one provider by name. No caching -- see ``get_stt_provider``."""
    resolved = (name or resolve_provider_name()).strip().lower()
    resolved = _PROVIDER_ALIASES.get(resolved, resolved)
    if resolved == PROVIDER_FASTER_WHISPER:
        from engine.media.stt_whisper import WhisperSTTProvider

        return WhisperSTTProvider()
    return STTClient()


_provider: Optional[STTProvider] = None
_provider_config: Any = None
_provider_lock = threading.Lock()


def get_stt_provider() -> STTProvider:
    """
    The process-wide provider.

    Cached against the live config object, not merely on first use: the Settings
    panel can repoint ``stt.provider`` mid-run, and a cached Whisper model held
    across that change would keep answering as the provider the player just
    switched away from.
    """
    global _provider, _provider_config
    current = get_config()
    with _provider_lock:
        if _provider is None or _provider_config is not current:
            _provider = build_provider()
            _provider_config = current
        return _provider


def reset_stt_provider() -> None:
    """Drop the cached provider. Tests, and config reloads."""
    global _provider, _provider_config
    with _provider_lock:
        _provider = None
        _provider_config = None


def transcribe_audio(
    audio_bytes: bytes,
    *,
    client: Optional[STTProvider] = None,
    language: Optional[str] = None,
) -> dict[str, Any]:
    """
    Transcribe one utterance with the configured provider.

    Args:
        audio_bytes: Whatever the browser's MediaRecorder produced.
        client: An explicit provider, which wins over the configured one.
            Tests and ``AssistantAgent(stt_client=...)`` use this.
        language: BCP-47 hint. Defaults to ``stt.language``.

    Returns:
        The shared result dict. This never raises: a dead service, a missing
        dependency and an unintelligible recording are all a transcript of "".
    """
    provider = client or get_stt_provider()
    hint = language if language is not None else str(get_config().get("stt.language", "en") or "en")
    return provider.transcribe(audio_bytes, language=hint)


__all__ = [
    "DEFAULT_PROVIDER",
    "PROVIDER_FASTER_WHISPER",
    "PROVIDER_VOXTRAL_HTTP",
    "STT_PROVIDERS",
    "STTClient",
    "STTProvider",
    "build_provider",
    "empty_result",
    "get_stt_provider",
    "reset_stt_provider",
    "resolve_provider_name",
    "transcribe_audio",
]
