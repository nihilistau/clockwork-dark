"""
ComfyUI Client
==============

The in-turn image queue: template prompts and placeholder URLs.

v0.15.1: no negative prompt. The templates carry none and the job payload
no longer has a ``negative_prompt`` slot.

v0.22.0 (spec §13.4): its ``/prompt`` submit is RETIRED. It posted a one-node
graph (a lone CLIPTextEncode) that ComfyUI accepts and that produces nothing,
on every turn of every story once ``comfyui.enabled`` was on -- the art
pipeline's switch. ``enqueue_image`` now answers a placeholder (or a cached
URL) whatever that switch says, and no story's turn contacts ComfyUI. Real
generation is ``engine/media/providers/comfy.py`` (the art pipeline, behind the
image worker) and ``engine/media/comfy/`` (the phone's media). The queue and
its prompt building stay: the turn payload's ``media.images`` rows are built
here. NOT WIRED to any server (docs/GOVERNANCE.md).

Version: v0.2.0 [2026-10-12]
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from engine import yamlio
from engine.config import get_config
from engine.game.state import GameState
from engine.media.queue import (
    MediaJob,
    get_media_queue,
    make_cache_key,
    parse_image_tag,
)

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parents[2]
_TEMPLATE_CACHE: Optional[dict[str, Any]] = None


def load_comfyui_templates() -> dict[str, Any]:
    """Load ComfyUI prompt templates."""
    global _TEMPLATE_CACHE
    cached = _TEMPLATE_CACHE  # read once: a reset nulls it without a lock
    if cached is not None:
        return cached

    rel = str(get_config().get("paths.comfyui_templates", "") or "").strip()
    path = _ROOT / rel if rel else None
    if path is None or not path.exists():
        # A story with no image-prompt templates generates from the caller's
        # tag alone. It must not borrow another story's visual language.
        templates: dict[str, Any] = {}
    else:
        with path.open(encoding="utf-8") as fh:
            templates = yamlio.safe_load(fh) or {}
    _TEMPLATE_CACHE = templates
    return templates


def build_image_prompt(
    image_tag: str,
    *,
    evil_phase: str = "dormant",
    templates: Optional[dict[str, Any]] = None,
) -> str:
    """Compose full ComfyUI prompt from tag and templates."""
    tpl = templates or load_comfyui_templates()
    location_id, time_of_day = parse_image_tag(image_tag)
    loc_prompts = tpl.get("locations", {}).get(location_id, {})
    subject = loc_prompts.get(time_of_day) or loc_prompts.get("dawn") or image_tag
    style = tpl.get("style_suffix", "")
    prompt = f"{subject}, {style}".strip(", ")
    if evil_phase in ("spreading", "consuming"):
        corruption = tpl.get("corruption_suffix", "")
        if corruption:
            prompt = f"{prompt}, {corruption}"
    return prompt


class ComfyUIClient:
    """
    Queue in-turn image jobs: a cached URL, else a placeholder.

    It contacts no server (v0.22.0): see the module docstring.
    """

    def enqueue_image(
        self,
        image_tag: str,
        state: GameState,
        *,
        templates: Optional[dict[str, Any]] = None,
    ) -> MediaJob:
        """
        Enqueue an image job from a stream tag.

        Args:
            image_tag: e.g. forest_clearing_dawn
            state: Game state for phase bucket and cache.

        Returns:
            MediaJob added to the media queue: ``cached`` with the cached URL,
            else ``placeholder``.
        """
        location_id, time_of_day = parse_image_tag(image_tag)
        phase_bucket = state.evil_phase.value
        cache_key = make_cache_key(location_id, time_of_day, phase_bucket)
        prompt = build_image_prompt(
            image_tag,
            evil_phase=phase_bucket,
            templates=templates,
        )

        queue = get_media_queue()
        job = MediaJob(
            job_id=queue.new_job_id(),
            kind="image",
            cache_key=cache_key,
            prompt=prompt,
            payload={
                "image_tag": image_tag,
                "location_id": location_id,
                "time_of_day": time_of_day,
                "evil_phase": phase_bucket,
            },
        )

        if cache_key in state.media_cache:
            cached_url = state.media_cache[cache_key]
            job.status = "cached"
            job.url = cached_url
            return queue.enqueue(job)

        job.status = "placeholder"
        job.url = f"/static/placeholders/{image_tag}.png"
        state.media_cache[cache_key] = job.url
        logger.debug(
            "[comfyui] Placeholder image (operation=enqueue_image, tag=%s)",
            image_tag,
        )
        return queue.enqueue(job)
