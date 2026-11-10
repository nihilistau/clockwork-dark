"""
Forge Neo Image Provider
========================

Generates a plate on a local Stable Diffusion WebUI Forge Neo server through
the AUTOMATIC1111-compatible API it serves (v0.25.0 T15, the owner's choice
for the flagship's art pack: Qwen Image 2.1 as a GGUF checkpoint, with its VAE
and text encoder named as Forge's "additional modules").

    POST {base_url}/sdapi/v1/txt2img
        {prompt, steps, cfg_scale, width, height, sampler_name, seed,
         override_settings: {sd_model_checkpoint, forge_additional_modules}}
    -> {"images": ["<base64 PNG>", ...], ...}

Everything comes from ``media.forge`` in ``config/default.yaml`` (rule 5). The
prompt is the subject's natural prose (``engine.media.art.render_prose``, the
dialect Qwen reads best) and the size the story's ``formats:`` declares for the
kind (``format_for``), as the ComfyUI provider does.

NO NEGATIVE PROMPT, by the owner's rule: the request carries no
``negative_prompt`` key at all (``tests/test_media_forge.py`` holds it).

The seed is deterministic per plate: ``ImageRequest.seed`` when the caller set
one (``scripts/generate_art.py --seed``, how a missed plate is re-rolled), else
a hash of the request's cache key, so the same subject reproduces exactly.
Never bare ``random`` (rule 4).

``available()`` is a short GET of ``/sdapi/v1/sd-models``, bounded by
``AVAILABLE_TIMEOUT_SECONDS``, and reports False on any error: the caller is a
fallback chain. ``generate()`` never raises; a failure is an ``ImageResult``.

Verified live against the owner's Forge Neo in v0.25.0 T15 (docs/MEDIA_SERVERS.md
§ Forge Neo); the suite stubs ``urllib.request.urlopen`` and never reaches it.
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from engine.config import get_config
from engine.media.art import format_for, render_prose
from engine.media.providers.base import (
    ImageRequest,
    ImageResult,
    cached_image,
    target_path,
    url_for,
)

logger = logging.getLogger(__name__)

#: ``active_provider`` asks on the caller's thread; an absent server must answer
#: "no" in seconds, not after a plate's ``timeout_seconds``.
AVAILABLE_TIMEOUT_SECONDS = 3.0
DEFAULT_BASE_URL = "http://127.0.0.1:7860"
DEFAULT_TIMEOUT = 900


def _image_bytes(payload: Any) -> bytes:
    """The first image of a txt2img reply, decoded; b"" when there is none."""
    images = payload.get("images") if isinstance(payload, dict) else None
    if not images:
        return b""
    raw = str(images[0])
    if raw.startswith("data:") and "," in raw:
        raw = raw.split(",", 1)[1]
    return base64.b64decode(raw)


def _extension(data: bytes) -> str | None:
    """The file suffix for PNG or JPEG bytes, None for anything else."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    return None


class ForgeProvider:
    """Image generation through a Forge Neo (A1111-compatible) server."""

    name = "forge"

    def __init__(self) -> None:
        cfg = get_config()
        self.base_url = str(cfg.get("media.forge.base_url", DEFAULT_BASE_URL) or DEFAULT_BASE_URL).rstrip("/")
        self.checkpoint = str(cfg.get("media.forge.checkpoint", "") or "")
        modules = cfg.get("media.forge.modules", []) or []
        self.modules = [str(m) for m in modules] if isinstance(modules, list) else [str(modules)]
        self.steps = int(cfg.get("media.forge.steps", 20))
        self.cfg_scale = float(cfg.get("media.forge.cfg_scale", 3.5))
        self.sampler = str(cfg.get("media.forge.sampler", "Euler") or "Euler")
        self.timeout = float(cfg.get("media.forge.timeout_seconds", DEFAULT_TIMEOUT))

    def available(self) -> bool:
        """Whether a Forge server answers its model list, within a few seconds."""
        try:
            with urllib.request.urlopen(
                f"{self.base_url}/sdapi/v1/sd-models", timeout=AVAILABLE_TIMEOUT_SECONDS
            ) as response:
                json.loads(response.read().decode("utf-8", "replace"))
            return True
        except Exception as exc:  # noqa: BLE001 -- any failure means "not available"
            logger.debug("[media] Forge not reachable (operation=available): %s", type(exc).__name__)
            return False

    def seed_for(self, request: ImageRequest) -> int:
        """The request's own seed, else one derived from its cache key."""
        if request.seed:
            return int(request.seed)
        return int(request.cache_key(), 16) % (2**31)

    def body(self, request: ImageRequest) -> dict[str, Any]:
        """The txt2img JSON for one request. No ``negative_prompt`` (owner rule)."""
        spec = format_for(request.kind)
        return {
            "prompt": render_prose(
                request.subject_id,
                kind=request.kind,
                time_of_day=request.time_of_day,
                evil_phase=request.evil_phase,
            ),
            "steps": self.steps,
            "cfg_scale": self.cfg_scale,
            "width": int(spec.get("width", 1024)),
            "height": int(spec.get("height", 1024)),
            "sampler_name": self.sampler,
            "seed": self.seed_for(request),
            "override_settings": {
                "sd_model_checkpoint": self.checkpoint,
                "forge_additional_modules": list(self.modules),
            },
        }

    def _failed(self, detail: str) -> ImageResult:
        return ImageResult(status="failed", provider=self.name, detail=detail[:300])

    def generate(self, request: ImageRequest) -> ImageResult:
        """Generate one image. Blocks for one txt2img call (minutes on a big model)."""
        hit = cached_image(request)
        if hit:
            return hit
        http = urllib.request.Request(
            f"{self.base_url}/sdapi/v1/txt2img",
            data=json.dumps(self.body(request)).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        logger.info(
            "[media] Generating (operation=generate, provider=forge, subject=%s, kind=%s)",
            request.subject_id,
            request.kind,
        )
        try:
            with urllib.request.urlopen(http, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8", "replace"))
            blob = _image_bytes(payload)
        except urllib.error.HTTPError as exc:
            result = self._failed(f"HTTP {exc.code}")
            logger.warning("[media] Forge generation failed (operation=generate): %s", result.detail)
            return result
        except (OSError, ValueError, binascii.Error, AttributeError, IndexError, TypeError) as exc:
            # OSError covers URLError and timeouts; ValueError a body that is not JSON.
            return self._failed(f"{type(exc).__name__}: {exc}")

        suffix = _extension(blob)
        if not blob or suffix is None:
            return self._failed("Forge returned no PNG or JPEG image")
        destination: Path = target_path(request, suffix)
        try:
            destination.write_bytes(blob)
        except OSError as exc:
            return self._failed(f"could not write {destination.name}: {exc}")
        logger.info(
            "[media] Generated (operation=generate, provider=forge, subject=%s, bytes=%s)",
            request.subject_id,
            len(blob),
        )
        return ImageResult(url=url_for(destination), path=str(destination), status="ready", provider=self.name)
