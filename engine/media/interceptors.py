"""
Media Interceptors
==================

POST-phase hooks mirroring comms interceptor pipeline (PR10).

Version: v0.1.0 [2026-06-20]
"""

from __future__ import annotations

from typing import Any

from engine.game.state import GameState
from engine.media.pipeline import MediaPipeline, MediaPipelineResult


class TTSInterceptor:
    """POST: queue narration TTS."""

    priority = 85

    def run_post(
        self,
        state: GameState,
        *,
        narration: str = "",
        voice_style: str = "",
        pipeline: MediaPipeline | None = None,
    ) -> MediaPipelineResult:
        pipe = pipeline or MediaPipeline()
        return pipe.process_tags(
            state,
            narration=narration,
            voice_style=voice_style,
            queue_tts=True,
        )


class ComfyUIMediaInterceptor:
    """POST: enqueue ComfyUI images and cutscenes from tags."""

    priority = 90

    def run_post(
        self,
        state: GameState,
        *,
        image_tags: list[str] | None = None,
        cutscene_tags: list[str] | None = None,
        pipeline: MediaPipeline | None = None,
    ) -> MediaPipelineResult:
        pipe = pipeline or MediaPipeline()
        return pipe.process_tags(
            state,
            image_tags=image_tags,
            cutscene_tags=cutscene_tags,
            queue_tts=False,
        )


class CutsceneBudgetInterceptor:
    """POST: cutscene tags with phase-shift budget enforcement."""

    priority = 88

    def run_post(
        self,
        state: GameState,
        *,
        cutscene_tags: list[str] | None = None,
        pipeline: MediaPipeline | None = None,
        force: bool = False,
    ) -> MediaPipelineResult:
        pipe = pipeline or MediaPipeline()
        return pipe.process_tags(
            state,
            cutscene_tags=cutscene_tags,
            queue_tts=False,
            force_cutscenes=force,
        )


def run_media_interceptors(
    state: GameState,
    *,
    narration: str = "",
    processed_tags: dict[str, list[str]] | None = None,
    voice_style: str = "",
) -> dict[str, Any]:
    """
    Run full media POST interceptor chain.

    Returns:
        Serialized MediaPipelineResult dict.
    """
    tags = processed_tags or {}
    pipeline = MediaPipeline()
    result = pipeline.process_tags(
        state,
        image_tags=tags.get("image"),
        cutscene_tags=tags.get("cutscene"),
        narration=narration,
        voice_style=voice_style,
    )
    return result.to_dict()