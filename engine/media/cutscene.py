"""
Cutscene Runner
===============

Video cutscene jobs with placeholder MP4 and phase-shift budget.

Version: v0.1.0 [2026-06-20]
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from engine.config import get_config
from engine.game.state import GameState
from engine.media.comfyui import load_comfyui_templates
from engine.media.queue import MediaJob, get_media_queue

logger = logging.getLogger(__name__)


class CutsceneBudget:
    """
    Enforces phase-shift-only cutscene budget (DESIGN default).

    One cutscene allowed per evil_phase per session.
    """

    @staticmethod
    def can_play(state: GameState, cutscene_id: str) -> tuple[bool, str]:
        """
        Check whether cutscene budget allows playback.

        Returns:
            (allowed, reason)
        """
        phase = state.evil_phase.value
        if phase != state.last_cutscene_phase:
            return True, "phase_shift"
        if state.media_cutscenes_shown:
            return False, "phase_budget_exhausted"
        return True, "first_in_phase"

    @staticmethod
    def record_play(state: GameState, cutscene_id: str) -> None:
        """Record cutscene consumption against budget."""
        phase = state.evil_phase.value
        if phase != state.last_cutscene_phase:
            state.last_cutscene_phase = phase
            state.media_cutscenes_shown = []
        if cutscene_id not in state.media_cutscenes_shown:
            state.media_cutscenes_shown.append(cutscene_id)


class CutsceneRunner:
    """Build cutscene media jobs from [CUTSCENE:id] tags."""

    def __init__(self) -> None:
        self.skip_after_seconds = float(
            get_config().get("media.cutscene_skip_after_seconds", 5)
        )
        self._queue = get_media_queue()

    def enqueue_cutscene(
        self,
        cutscene_id: str,
        state: GameState,
        *,
        templates: Optional[dict[str, Any]] = None,
        force: bool = False,
    ) -> Optional[MediaJob]:
        """
        Enqueue cutscene if budget allows.

        Args:
            cutscene_id: Milestone cutscene id.
            state: Session state for budget tracking.
            force: Skip budget check (tests).

        Returns:
            MediaJob or None if budget blocked.
        """
        if not force:
            allowed, reason = CutsceneBudget.can_play(state, cutscene_id)
            if not allowed:
                logger.info(
                    "[cutscene] Budget blocked (operation=enqueue, id=%s, reason=%s)",
                    cutscene_id,
                    reason,
                )
                return None

        tpl = templates or load_comfyui_templates()
        scene = tpl.get("cutscenes", {}).get(cutscene_id, {})
        placeholder = scene.get("placeholder", f"{cutscene_id}.mp4")
        captions = list(scene.get("captions", []))

        job = MediaJob(
            job_id=self._queue.new_job_id(),
            kind="cutscene",
            cache_key=cutscene_id,
            prompt=cutscene_id,
            payload={
                "cutscene_id": cutscene_id,
                "captions": captions,
                "skip_after_seconds": self.skip_after_seconds,
                "evil_phase": state.evil_phase.value,
            },
            status="placeholder",
            url=f"/static/cutscenes/{placeholder}",
        )
        CutsceneBudget.record_play(state, cutscene_id)
        return self._queue.enqueue(job)