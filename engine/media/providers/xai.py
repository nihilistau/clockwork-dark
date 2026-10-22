"""
xAI Image Provider
==================

Calls xAI's REST image API directly (``POST /v1/images/generations``) instead of
driving the Grok Build CLI, which fails whenever the CLI is not signed in. The
request shape follows the owner's other project (shannon-prime-kairos,
``harness/skills/xai.py``): a Bearer key, ``grok-imagine-image-2.0``, a b64
response with a URL fallback.

NOT VERIFIED LIVE: the suite stubs ``urllib.request.urlopen`` and never reaches
api.x.ai (docs/MEDIA_SERVERS.md § xAI image API).

The key comes from ``media.xai.api_key`` (a gitignored ``xai_api_key.txt`` at the
repository root, or the ``XAI_API_KEY`` environment variable). It is sent only in
the Authorization header and never logged or put in a result.

Like grokbuild there is no seed, so determinism comes from the disk cache. An
``ImageRequest.base_image`` is not honoured: this provider has no edit route, so
the picture is generated from the prompt alone.
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional

from engine.config import get_config
from engine.media.art import render_prose
from engine.media.providers.base import (
    ImageRequest,
    ImageResult,
    cached_image,
    target_path,
    url_for,
)

logger = logging.getLogger(__name__)

ENDPOINT = "https://api.x.ai/v1/images/generations"
DEFAULT_MODEL = "grok-imagine-image-2.0"
DEFAULT_TIMEOUT = 180
DEFAULT_ASPECTS = (("location", "16:9"), ("portrait", "3:4"), ("item", "1:1"))
NO_KEY = "no xAI API key (media.xai.api_key)"
#: Anything shaped like a Bearer token or an xAI key never reaches a message.
_SECRET_SHAPES = re.compile(r"Bearer\s+\S+|xai-[A-Za-z0-9_-]{16,}", re.IGNORECASE)


def _extension(data: bytes) -> Optional[str]:
    """The file suffix for PNG or JPEG bytes, None for anything else."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    return None


class XaiImageProvider:
    """Image generation through xAI's images API."""

    name = "xai"

    def __init__(self) -> None:
        cfg = get_config()
        self.api_key = str(cfg.get("media.xai.api_key", "") or "").strip()
        self.model = str(cfg.get("media.xai.model", DEFAULT_MODEL) or DEFAULT_MODEL)
        self.resolution = str(cfg.get("media.xai.resolution", "1k") or "1k")
        aspects = cfg.get("media.xai.aspect_ratio", None)
        self.aspects = dict(DEFAULT_ASPECTS)
        if isinstance(aspects, dict):
            self.aspects.update({str(k): str(v) for k, v in aspects.items()})
        self.timeout = int(cfg.get("media.xai.timeout_seconds", DEFAULT_TIMEOUT))

    def available(self) -> bool:
        return bool(self.api_key)

    def _failed(self, detail: str) -> ImageResult:
        if self.api_key:
            detail = detail.replace(self.api_key, "[key]")
        detail = _SECRET_SHAPES.sub("[masked]", detail)
        return ImageResult(status="failed", provider=self.name, detail=detail[:300])

    def _prompt(self, request: ImageRequest) -> str:
        """The scene description alone: no CLI instructions about saving files."""
        return render_prose(
            request.subject_id,
            kind=request.kind,
            time_of_day=request.time_of_day,
            evil_phase=request.evil_phase,
        )

    def _body(self, request: ImageRequest) -> dict[str, Any]:
        return {
            "model": self.model,
            "prompt": self._prompt(request),
            "n": 1,
            "aspect_ratio": self.aspects.get(request.kind, self.aspects["location"]),
            "resolution": self.resolution,
            "response_format": "b64_json",
        }

    def _http_error(self, exc: urllib.error.HTTPError) -> ImageResult:
        message = ""
        try:
            raw = exc.read().decode("utf-8", "replace")
            try:
                payload = json.loads(raw)
                error = payload.get("error", payload) if isinstance(payload, dict) else payload
                if isinstance(error, dict):
                    error = error.get("message") or error.get("detail") or json.dumps(error)
                message = str(error)
            except ValueError:
                message = raw
        except Exception:  # noqa: BLE001 — the status code alone still explains it
            message = ""
        detail = f"HTTP {exc.code}"
        if message.strip():
            detail += f": {message.strip()}"
        return self._failed(detail)

    def _fetch(self, url: str) -> bytes:
        with urllib.request.urlopen(url, timeout=self.timeout) as response:
            return response.read()

    def generate(self, request: ImageRequest) -> ImageResult:
        """Generate one image. Blocks for the length of one HTTP call."""
        hit = cached_image(request)
        if hit:
            return hit
        if not self.api_key:
            return self._failed(NO_KEY)

        http = urllib.request.Request(
            ENDPOINT,
            data=json.dumps(self._body(request)).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer " + self.api_key,
            },
            method="POST",
        )
        logger.info(
            "[media] Generating (operation=generate, provider=xai, subject=%s, kind=%s)",
            request.subject_id,
            request.kind,
        )
        try:
            with urllib.request.urlopen(http, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8", "replace"))
            row = (payload.get("data") or [{}])[0]
            blob = b""
            if row.get("b64_json"):
                blob = base64.b64decode(row["b64_json"])
            elif row.get("url"):
                blob = self._fetch(str(row["url"]))
        except urllib.error.HTTPError as exc:
            result = self._http_error(exc)
            logger.warning(
                "[media] Generation failed (operation=generate, subject=%s): %s",
                request.subject_id,
                result.detail,
            )
            return result
        except (OSError, ValueError, binascii.Error, AttributeError, IndexError, TypeError) as exc:
            # OSError covers URLError and timeouts; ValueError a body that is not JSON.
            return self._failed(f"{type(exc).__name__}: {exc}")

        suffix = _extension(blob)
        if not blob or suffix is None:
            return self._failed("xAI returned no PNG or JPEG image")

        destination: Path = target_path(request, suffix)
        try:
            destination.write_bytes(blob)
        except OSError as exc:
            return self._failed(f"could not write {destination.name}: {exc}")

        logger.info(
            "[media] Generated (operation=generate, subject=%s, bytes=%s)",
            request.subject_id,
            len(blob),
        )
        return ImageResult(
            url=url_for(destination),
            path=str(destination),
            status="ready",
            provider=self.name,
        )
