"""
ComfyUI SDXL Provider
=====================

The second backend named in engine/media/providers/__init__.py::build_provider.

THE BUG THIS MODULE FIXED (v0.2.0): ``build_provider("comfyui")`` imported
this module before it existed, so selecting the documented non-default
provider raised ImportError out of a function whose contract is "returns a
provider or None".

WHAT THIS IS. The art provider: it renders a subject from data/art/subjects.yaml
through engine/media/art.py, so a ComfyUI image and a Grok Imagine image of
the same subject are two dialects of one description. Since v0.22.0 (spec
§13.4) it is built on ``engine.media.comfy``: the graph is
``comfyui.workflows.photo``'s template (``config/comfyui/photo_sdxl.json``)
with this request bound into it, and every HTTP call goes through
``ComfyClient`` -- bounded, a ``ComfyError`` with a kind on failure. The
template reproduces v0.21.1's in-code graph exactly
(``tests/test_comfy_client.py`` holds them equal, node for node): checkpoint,
two text encodes (KSampler needs a negative conditioning; it encodes an empty
string, because no story carries a negative prompt, v0.15.1), an empty
latent, a KSampler, a VAE decode and a SaveImage.

The art provider keeps its own subjects and sizes (``format_for``), not the
workflow's ``size``, which is the phone's. It is switched by
``comfyui.enabled`` (``available()``), unchanged; the phone's media are
switched by ``phone_media.provider`` alone.

WHAT THIS IS NOT. ``engine/media/comfyui.py`` is the older in-turn queue: it
builds prompts from a story's ``paths.comfyui_templates`` and, since v0.22.0,
contacts no server at all.

NOT VERIFIED AGAINST A RUNNING SERVER unless docs/MEDIA_SERVERS.md says so;
the routes are exercised against an in-process ``httpx.MockTransport``.

Version: v0.2.0 [2026-10-12]
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

from engine.config import get_config
from engine.media.art import format_for, render_tags
from engine.media.comfy.client import ComfyClient, ComfyError
from engine.media.comfy.workflows import BindingError, Workflow, bind, load_workflow
from engine.media.providers.base import (
    ImageRequest,
    ImageResult,
    cached_image,
    target_path,
    url_for,
)

logger = logging.getLogger(__name__)

#: The availability probe's bound: ``active_provider`` asks on the caller's
#: thread, so an unreachable server must answer "no" in seconds, not after
#: ``comfyui.timeout_seconds``.
AVAILABLE_TIMEOUT_SECONDS = 3.0

#: The workflow the art provider binds (``comfyui.workflows.<name>``).
WORKFLOW = "photo"


class ComfyProvider:
    """SDXL image generation through a ComfyUI server."""

    name = "comfyui"

    def __init__(self, *, transport: Optional[httpx.BaseTransport] = None) -> None:
        cfg = get_config()
        self.enabled = bool(cfg.get("comfyui.enabled", False))
        self.checkpoint = str(cfg.get("comfyui.checkpoint", "sd_xl_base_1.0.safetensors"))
        self.steps = int(cfg.get("comfyui.steps", 28))
        self.cfg_scale = float(cfg.get("comfyui.cfg_scale", 6.5))
        self.sampler = str(cfg.get("comfyui.sampler", "dpmpp_2m"))
        self.scheduler = str(cfg.get("comfyui.scheduler", "karras"))
        self.poll_seconds = float(cfg.get("comfyui.poll_seconds", 1.5))
        self.job_timeout = float(cfg.get("comfyui.job_timeout_seconds", 600))
        self._transport = transport

    def available(self) -> bool:
        """
        Whether a ComfyUI server is up and enabled.

        Returns False rather than raising for every reason it could fail --
        disabled in config, nothing listening, a refused key, a non-200 --
        because the caller is a fallback chain and an exception here skips the
        fallback.
        """
        if not self.enabled:
            return False
        try:
            with ComfyClient.from_config(self._transport, timeout=AVAILABLE_TIMEOUT_SECONDS) as client:
                client.system_stats()
                return True
        except ComfyError as exc:
            logger.debug("[media] ComfyUI not reachable (operation=available, kind=%s)", exc.kind)
            return False

    def _seed_for(self, request: ImageRequest) -> int:
        """Deterministic per request, so the same subject reproduces exactly."""
        return int(request.cache_key(), 16) % (2**31)

    def graph_for(self, request: ImageRequest, workflow: Optional[Workflow] = None) -> dict[str, Any]:
        """The ``photo`` workflow (loaded, unless given) with this request bound into it."""
        spec = format_for(request.kind)
        return bind(
            workflow or load_workflow(WORKFLOW),
            {
                "checkpoint": self.checkpoint,
                "positive": render_tags(
                    request.subject_id,
                    kind=request.kind,
                    time_of_day=request.time_of_day,
                    evil_phase=request.evil_phase,
                ),
                "width": int(spec.get("width", 1024)),
                "height": int(spec.get("height", 1024)),
                "seed": self._seed_for(request),
                "steps": self.steps,
                "cfg_scale": self.cfg_scale,
                "sampler": self.sampler,
                "scheduler": self.scheduler,
                "filename_prefix": f"clockwork/{request.kind}_{request.subject_id}",
            },
        )

    def generate(self, request: ImageRequest) -> ImageResult:
        """
        Generate one image: submit, poll ``/history`` every
        ``comfyui.poll_seconds`` up to ``comfyui.job_timeout_seconds``, fetch the
        output node's first file, write it. Seconds to a minute on a warm GPU.

        Returns:
            ImageResult. Never raises: a failure is a status, because this runs
            on the background worker in engine/media/providers/__init__.py and
            one bad image must not take the queue down.
        """
        hit = cached_image(request)
        if hit:
            return hit

        logger.info(
            "[media] Generating (operation=generate, provider=comfyui, subject=%s, kind=%s)",
            request.subject_id,
            request.kind,
        )
        try:
            workflow = load_workflow(WORKFLOW)
            graph = self.graph_for(request, workflow)
            with ComfyClient.from_config(self._transport) as client:
                prompt_id = client.submit(graph, request.cache_key())
                entry = client.wait(prompt_id, poll_seconds=self.poll_seconds, timeout=self.job_timeout)
                files = client.outputs(entry, workflow.output_node)
                if not files:
                    return ImageResult(
                        status="failed",
                        provider=self.name,
                        detail=f"no output from node {workflow.output_node}",
                    )
                blob = client.fetch(files[0])
            destination = target_path(request, ".png")
            destination.write_bytes(blob)
        except ComfyError as exc:
            logger.warning(
                "[media] ComfyUI generation failed (operation=generate, kind=%s): %s",
                exc.kind,
                exc.detail[:300],
            )
            return ImageResult(status="failed", provider=self.name, detail=str(exc)[:300])
        except (BindingError, OSError) as exc:
            logger.warning("[media] ComfyUI generation failed (operation=generate): %s", exc)
            return ImageResult(status="failed", provider=self.name, detail=str(exc)[:300])

        return ImageResult(
            url=url_for(destination),
            path=str(destination),
            status="ready",
            provider=self.name,
        )
