"""
Grok Imagine Provider (default)
===============================

Drives the Grok Build CLI headlessly to reach its ``image_gen`` / ``image_edit``
tools.

Measured behaviour on this machine, not assumed:

  - A 16:9 location still takes roughly two to three minutes end to end.
  - Output is a real PNG around 1.4 MB at 1280x720.
  - The generated image carries a small **Grok watermark in the bottom-right**.
    ``media.crop_watermark`` trims the bottom strip when that matters.
  - There is NO seed parameter and no ``n``. Two calls with the same prompt
    give different images, so determinism comes from the disk cache, and
    character consistency comes from ``image_edit`` against a stored base
    image rather than from re-prompting.

Version: v0.2.0 [2026-08-07]
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from engine.config import get_config, project_root
from engine.media.art import format_for, render_prose
from engine.media.providers.base import (
    ImageRequest,
    ImageResult,
    cached_image,
    target_path,
    url_for,
)

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 600


class GrokImagineProvider:
    """Image generation via the Grok Build CLI's imagine tools."""

    name = "grokbuild"

    def __init__(self, command: Optional[str] = None) -> None:
        cfg = get_config()
        self.command = command or str(
            cfg.get("stack.services.grok.command", "grok")
        )
        self.timeout = int(cfg.get("media.grok_timeout_seconds", DEFAULT_TIMEOUT))
        self.crop_watermark = bool(cfg.get("media.crop_watermark", False))

    def _resolve_command(self) -> Optional[str]:
        candidate = Path(self.command)
        if candidate.is_absolute():
            return str(candidate) if candidate.exists() else None
        return shutil.which(self.command)

    def available(self) -> bool:
        return self._resolve_command() is not None

    def _instruction(self, request: ImageRequest, destination: Path) -> str:
        """
        The headless prompt.

        Phrased as an explicit single-tool instruction because the CLI is a
        full agent: left vague it will happily reason, verify and iterate,
        which costs minutes and extra generations we did not ask for.
        """
        spec = format_for(request.kind)
        prose = render_prose(
            request.subject_id,
            kind=request.kind,
            time_of_day=request.time_of_day,
            evil_phase=request.evil_phase,
        )

        if request.base_image:
            return (
                f"Call image_edit exactly once with image='{request.base_image}' "
                f"and aspect_ratio='{spec['aspect']}'. Keep the same character, "
                f"face and clothing; change only the setting and lighting. "
                f"Prompt: {prose}\n"
                f"Then save the result to '{destination.as_posix()}' as PNG. "
                f"Do not generate any other images. Reply with the saved path only."
            )

        return (
            f"Call image_gen exactly once with aspect_ratio='{spec['aspect']}'.\n"
            f"Prompt: {prose}\n"
            f"Then save the result to '{destination.as_posix()}' as PNG. "
            f"Do not verify, iterate, or generate any variations. "
            f"Reply with the saved path only."
        )

    def generate(self, request: ImageRequest) -> ImageResult:
        """Generate one image. Blocks for minutes -- worker threads only."""
        hit = cached_image(request)
        if hit:
            return hit

        command = self._resolve_command()
        if command is None:
            return ImageResult(
                status="failed", provider=self.name, detail=f"grok not found: {self.command}"
            )

        destination = target_path(request, ".png")
        argv = [
            command,
            "-p",
            self._instruction(request, destination),
            "--permission-mode",
            "bypassPermissions",
            "--output-format",
            "json",
            "--cwd",
            str(project_root()),
        ]

        logger.info(
            "[media] Generating (operation=generate, provider=grok, subject=%s, kind=%s)",
            request.subject_id,
            request.kind,
        )
        try:
            completed = subprocess.run(
                argv,
                capture_output=True,
                timeout=self.timeout,
                cwd=str(project_root()),
            )
        except subprocess.TimeoutExpired:
            return ImageResult(
                status="failed",
                provider=self.name,
                detail=f"timed out after {self.timeout}s",
            )
        except OSError as exc:
            return ImageResult(status="failed", provider=self.name, detail=str(exc))

        if not destination.exists() or destination.stat().st_size == 0:
            detail = _explain_failure(completed)
            logger.warning(
                "[media] Generation produced no file "
                "(operation=generate, subject=%s): %s",
                request.subject_id,
                detail,
            )
            return ImageResult(status="failed", provider=self.name, detail=detail)

        if self.crop_watermark:
            _crop_bottom(destination)

        logger.info(
            "[media] Generated (operation=generate, subject=%s, bytes=%s)",
            request.subject_id,
            destination.stat().st_size,
        )
        return ImageResult(
            url=url_for(destination),
            path=str(destination),
            status="ready",
            provider=self.name,
        )


def _explain_failure(completed: subprocess.CompletedProcess[bytes]) -> str:
    """Pull a usable reason out of the CLI's JSON envelope."""
    text = (completed.stdout or b"").decode("utf-8", "replace")
    try:
        payload = json.loads(text)
        return str(payload.get("text") or payload.get("error") or "no image produced")[:300]
    except json.JSONDecodeError:
        stderr = (completed.stderr or b"").decode("utf-8", "replace")
        return (stderr or text or "no image produced").strip()[:300]


def _crop_bottom(path: Path, fraction: float = 0.045) -> None:
    """
    Trim the bottom strip carrying the provider watermark.

    Optional and off by default: it costs a sliver of composition, and for a
    local single-player game the mark is usually tolerable.
    """
    try:
        from PIL import Image  # noqa: PLC0415 — optional dependency
    except ImportError:
        logger.debug("[media] Pillow not installed; leaving watermark in place")
        return

    try:
        with Image.open(path) as image:
            width, height = image.size
            image.crop((0, 0, width, int(height * (1 - fraction)))).save(path)
    except OSError as exc:
        logger.warning("[media] Crop failed (operation=_crop_bottom): %s", exc)
