"""
ComfyUI Client
==============

Image generation queue with template prompts and placeholder fallback.

Version: v0.1.0 [2026-06-20]
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

import httpx
import yaml

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
    if _TEMPLATE_CACHE is not None:
        return _TEMPLATE_CACHE

    rel = str(get_config().get("paths.comfyui_templates", "") or "").strip()
    if not rel:
        # A story with no image-prompt templates generates from the caller's
        # tag alone. It must not borrow another story's visual language.
        _TEMPLATE_CACHE = {}
        return _TEMPLATE_CACHE

    path = _ROOT / rel
    if not path.exists():
        _TEMPLATE_CACHE = {}
        return _TEMPLATE_CACHE

    with path.open(encoding="utf-8") as fh:
        _TEMPLATE_CACHE = yaml.safe_load(fh) or {}
    return _TEMPLATE_CACHE


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
    Queue ComfyUI image jobs; POST to API when enabled.

    When disabled, returns placeholder URLs for dev/test.
    """

    def __init__(self, base_url: Optional[str] = None) -> None:
        cfg = get_config()
        self.base_url = (base_url or cfg.get("comfyui.base_url", "http://localhost:8188")).rstrip(
            "/"
        )
        self.enabled = bool(cfg.get("comfyui.enabled", False))
        self.timeout = float(cfg.get("comfyui.timeout_seconds", 120))

    def is_available(self) -> bool:
        """Return True if ComfyUI responds."""
        if not self.enabled:
            return False
        try:
            with httpx.Client(timeout=3.0) as client:
                r = client.get(f"{self.base_url}/system_stats")
                return r.status_code == 200
        except Exception:
            return False

    def enqueue_image(
        self,
        image_tag: str,
        state: GameState,
        *,
        templates: Optional[dict[str, Any]] = None,
    ) -> MediaJob:
        """
        Enqueue an image generation job from a stream tag.

        Args:
            image_tag: e.g. forest_clearing_dawn
            state: Game state for phase bucket and cache.

        Returns:
            MediaJob added to the media queue.
        """
        location_id, time_of_day = parse_image_tag(image_tag)
        phase_bucket = state.evil_phase.value
        cache_key = make_cache_key(location_id, time_of_day, phase_bucket)
        prompt = build_image_prompt(
            image_tag,
            evil_phase=phase_bucket,
            templates=templates,
        )
        tpl = templates or load_comfyui_templates()

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
                "negative_prompt": tpl.get("negative_prompt", ""),
            },
        )

        if cache_key in state.media_cache:
            cached_url = state.media_cache[cache_key]
            job.status = "cached"
            job.url = cached_url
            return queue.enqueue(job)

        if not self.enabled:
            job.status = "placeholder"
            job.url = f"/static/placeholders/{image_tag}.png"
            state.media_cache[cache_key] = job.url
            logger.debug(
                "[comfyui] Placeholder image (operation=enqueue_image, tag=%s)",
                image_tag,
            )
            return queue.enqueue(job)

        try:
            submitted = self._submit_prompt(prompt, job.payload.get("negative_prompt", ""))
            job.status = "submitted"
            job.payload["comfyui"] = submitted
            job.url = submitted.get("preview_url", "")
            if job.url:
                state.media_cache[cache_key] = job.url
        except Exception as exc:
            job.status = "error"
            job.error = str(exc)
            job.url = f"/static/placeholders/{image_tag}.png"
            logger.warning(
                "[comfyui] Submit failed (operation=enqueue_image): %s", exc
            )

        return queue.enqueue(job)

    def _submit_prompt(self, prompt: str, negative_prompt: str) -> dict[str, Any]:
        """POST minimal workflow payload to ComfyUI."""
        payload = {
            "prompt": {
                "1": {
                    "class_type": "CLIPTextEncode",
                    "inputs": {"text": prompt},
                },
            },
            "client_id": get_media_queue().new_job_id(),
        }
        with httpx.Client(timeout=self.timeout) as client:
            response = client.post(f"{self.base_url}/prompt", json=payload)
            response.raise_for_status()
            data = response.json()
            return {
                "prompt_id": data.get("prompt_id"),
                "preview_url": "",
                "raw": data,
            }