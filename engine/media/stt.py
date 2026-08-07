"""
Speech-to-Text Client
=====================

Stub for push-to-talk transcription routed to the Assistant agent.

Version: v0.1.0 [2026-06-20]
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

from engine.config import get_config

logger = logging.getLogger(__name__)


class STTClient:
    """
    Transcribe audio via configured STT service.

    Falls back to stub transcript when the service is unreachable.
    """

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
        POST audio to STT endpoint.

        Args:
            audio_bytes: Raw audio payload.
            content_type: MIME type for upload.
            language: BCP-47 language hint.

        Returns:
            Dict with transcript, success, and source (live|stub).
        """
        if not audio_bytes:
            return {
                "success": False,
                "transcript": "",
                "source": "stub",
                "message": "Empty audio payload.",
            }

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
                    "raw": data,
                }
        except Exception as exc:
            logger.warning(
                "[stt] Service unavailable (operation=transcribe): %s", exc
            )
            return {
                "success": False,
                "transcript": "",
                "source": "stub",
                "message": str(exc),
            }


def transcribe_audio(
    audio_bytes: bytes,
    *,
    client: Optional[STTClient] = None,
) -> dict[str, Any]:
    """Module-level helper for STT transcription."""
    return (client or STTClient()).transcribe(audio_bytes)