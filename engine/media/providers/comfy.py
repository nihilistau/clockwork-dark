"""
ComfyUI SDXL Provider
=====================

The second backend named in engine/media/providers/__init__.py::build_provider.

THE BUG THIS MODULE FIXES: ``build_provider("comfyui")`` has imported
``engine.media.providers.comfy`` since v0.2.0 and that module did not exist.
Selecting the documented non-default provider -- by config, or by
``scripts/generate_art.py --provider comfyui`` -- raised ImportError out of a
function whose entire contract is "returns a provider or None". The fallback
chain never got the chance to degrade, because the exception escaped before
``available()`` could say no.

WHAT THIS IS NOT. ``engine/media/comfyui.py`` is a different, older thing: an
in-turn media QUEUE that builds prompts out of
data/procgen_templates/comfyui.yaml and posts a one-node stub workflow. It
predates the provider protocol and the one-source/two-dialect prompt renderer,
and it is still wired to the turn loop. This module is the provider-protocol
implementation: it renders from data/art/subjects.yaml through
engine/media/art.py, so a ComfyUI image and a Grok Imagine image of the same
subject are two dialects of one description rather than two descriptions.

WHY A FULL WORKFLOW GRAPH RATHER THAN A PROMPT STRING. ComfyUI's ``/prompt``
endpoint takes a node graph, not a prompt: a bare CLIPTextEncode node is
accepted and then produces nothing, because nothing samples it and nothing
saves the result. The graph below is the minimum that ends in a file --
checkpoint, two text encodes, an empty latent, a KSampler, a VAE decode and a
SaveImage -- and every knob in it that a user could reasonably want to change
is a config key rather than a literal.

NOT VERIFIED AGAINST A RUNNING SERVER. ComfyUI was not running on this machine
when this was written; ``available()``, the timeout path and the failure paths
are exercised by tests/test_items.py, the graph shape is not. It is written to
the documented API and marked here rather than claimed as tested.

Version: v0.1.0 [2026-08-08]
"""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

import httpx

from engine.config import get_config
from engine.media.art import format_for, render_tags
from engine.media.providers.base import (
    ImageRequest,
    ImageResult,
    cached_image,
    target_path,
    url_for,
)

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "http://localhost:8188"
DEFAULT_CHECKPOINT = "sd_xl_base_1.0.safetensors"
POLL_SECONDS = 1.5


def build_workflow(
    request: ImageRequest,
    *,
    checkpoint: str,
    steps: int,
    cfg_scale: float,
    sampler: str,
    scheduler: str,
    seed: int,
) -> dict[str, Any]:
    """
    The ComfyUI node graph for one image.

    Args:
        request: What to draw.
        checkpoint: SDXL checkpoint filename as ComfyUI knows it.
        steps: Sampler steps.
        cfg_scale: Classifier-free guidance scale.
        sampler: KSampler sampler name.
        scheduler: KSampler scheduler name.
        seed: Sampler seed. Unlike Grok Imagine, ComfyUI HAS one, so a given
            (subject, daypart, phase) can be reproduced exactly -- which is why
            the caller derives it from the cache key rather than randomising.

    Returns:
        The ``prompt`` object for POST /prompt.
    """
    positive, negative = render_tags(
        request.subject_id,
        kind=request.kind,
        time_of_day=request.time_of_day,
        evil_phase=request.evil_phase,
    )
    spec = format_for(request.kind)

    return {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": checkpoint},
        },
        "2": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": positive, "clip": ["1", 1]},
        },
        "3": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": negative, "clip": ["1", 1]},
        },
        "4": {
            "class_type": "EmptyLatentImage",
            "inputs": {
                "width": int(spec.get("width", 1024)),
                "height": int(spec.get("height", 1024)),
                "batch_size": 1,
            },
        },
        "5": {
            "class_type": "KSampler",
            "inputs": {
                "seed": int(seed),
                "steps": int(steps),
                "cfg": float(cfg_scale),
                "sampler_name": sampler,
                "scheduler": scheduler,
                "denoise": 1.0,
                "model": ["1", 0],
                "positive": ["2", 0],
                "negative": ["3", 0],
                "latent_image": ["4", 0],
            },
        },
        "6": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["5", 0], "vae": ["1", 2]},
        },
        "7": {
            "class_type": "SaveImage",
            "inputs": {
                "filename_prefix": f"clockwork/{request.kind}_{request.subject_id}",
                "images": ["6", 0],
            },
        },
    }


class ComfyProvider:
    """SDXL image generation through a local ComfyUI server."""

    name = "comfyui"

    def __init__(self, base_url: Optional[str] = None) -> None:
        cfg = get_config()
        self.base_url = str(
            base_url or cfg.get("comfyui.base_url", DEFAULT_BASE_URL)
        ).rstrip("/")
        self.enabled = bool(cfg.get("comfyui.enabled", False))
        self.timeout = float(cfg.get("comfyui.timeout_seconds", 120))
        self.checkpoint = str(cfg.get("comfyui.checkpoint", DEFAULT_CHECKPOINT))
        self.steps = int(cfg.get("comfyui.steps", 28))
        self.cfg_scale = float(cfg.get("comfyui.cfg_scale", 6.5))
        self.sampler = str(cfg.get("comfyui.sampler", "dpmpp_2m"))
        self.scheduler = str(cfg.get("comfyui.scheduler", "karras"))

    def available(self) -> bool:
        """
        Whether a ComfyUI server is up and enabled.

        Returns False rather than raising for every reason it could fail --
        disabled in config, nothing listening, a non-200 -- because the caller
        is a fallback chain and an exception here skips the fallback.
        """
        if not self.enabled:
            return False
        try:
            with httpx.Client(timeout=3.0) as client:
                return client.get(f"{self.base_url}/system_stats").status_code == 200
        except httpx.HTTPError as exc:
            logger.debug("[media] ComfyUI not reachable (operation=available): %s", exc)
            return False

    def _seed_for(self, request: ImageRequest) -> int:
        """Deterministic per request, so the same subject reproduces exactly."""
        return int(request.cache_key(), 16) % (2**31)

    def generate(self, request: ImageRequest) -> ImageResult:
        """
        Generate one image. Seconds to a minute on a warm GPU.

        Returns:
            ImageResult. Never raises: a failure is a status, because this runs
            on the background worker in engine/media/providers/__init__.py and
            one bad image must not take the queue down.
        """
        hit = cached_image(request)
        if hit:
            return hit

        workflow = build_workflow(
            request,
            checkpoint=self.checkpoint,
            steps=self.steps,
            cfg_scale=self.cfg_scale,
            sampler=self.sampler,
            scheduler=self.scheduler,
            seed=self._seed_for(request),
        )

        logger.info(
            "[media] Generating (operation=generate, provider=comfyui, subject=%s, kind=%s)",
            request.subject_id,
            request.kind,
        )
        try:
            with httpx.Client(timeout=self.timeout) as client:
                submitted = client.post(
                    f"{self.base_url}/prompt",
                    json={"prompt": workflow, "client_id": request.cache_key()},
                )
                submitted.raise_for_status()
                prompt_id = str(submitted.json().get("prompt_id") or "")
                if not prompt_id:
                    return ImageResult(
                        status="failed", provider=self.name, detail="no prompt_id returned"
                    )

                image = self._await_image(client, prompt_id)
                if image is None:
                    return ImageResult(
                        status="failed",
                        provider=self.name,
                        detail=f"no image after {self.timeout:.0f}s",
                    )

                blob = client.get(f"{self.base_url}/view", params=image)
                blob.raise_for_status()
                destination = target_path(request, ".png")
                destination.write_bytes(blob.content)
        except (httpx.HTTPError, OSError, ValueError) as exc:
            logger.warning("[media] ComfyUI generation failed (operation=generate): %s", exc)
            return ImageResult(status="failed", provider=self.name, detail=str(exc)[:300])

        return ImageResult(
            url=url_for(destination),
            path=str(destination),
            status="ready",
            provider=self.name,
        )

    def _await_image(
        self, client: httpx.Client, prompt_id: str
    ) -> Optional[dict[str, str]]:
        """
        Poll /history until the SaveImage node reports a file, or time out.

        Returns the /view query parameters for the first image produced.
        """
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            response = client.get(f"{self.base_url}/history/{prompt_id}")
            if response.status_code == 200:
                entry = (response.json() or {}).get(prompt_id) or {}
                for node in (entry.get("outputs") or {}).values():
                    for image in node.get("images") or []:
                        return {
                            "filename": str(image.get("filename", "")),
                            "subfolder": str(image.get("subfolder", "")),
                            "type": str(image.get("type", "output")),
                        }
            time.sleep(POLL_SECONDS)
        return None
