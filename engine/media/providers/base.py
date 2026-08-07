"""
Image Provider Protocol
=======================

One interface, three backends: Grok Imagine (default), ComfyUI SDXL, and a
deterministic procedural fallback that always works offline.

Generation is SLOW everywhere -- Imagine takes minutes per image and ComfyUI is
GPU-bound -- so the contract is deliberately two-part:

    peek()      instant. A cached file, or the procedural stand-in.
    generate()  slow. Runs on a worker thread; the UI swaps when it lands.

Nothing in a turn ever waits on generate().

Version: v0.2.0 [2026-08-07]
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Protocol

logger = logging.getLogger(__name__)

MEDIA_DIR = Path("data/media")
IMAGE_DIR = MEDIA_DIR / "images"


@dataclass
class ImageRequest:
    """One image to produce."""

    subject_id: str
    kind: str = "location"  # location | portrait | item | cutscene
    time_of_day: str = "dawn"
    evil_phase: str = "dormant"
    # Base image for a consistent variant. Imagine has no seed, so the way to
    # keep a character recognisable across images is to edit one base rather
    # than re-rolling from the prompt.
    base_image: str = ""

    def cache_key(self) -> str:
        raw = f"{self.kind}|{self.subject_id}|{self.time_of_day}|{self.evil_phase}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


@dataclass
class ImageResult:
    """Where an image ended up, and how it got there."""

    url: str = ""
    path: str = ""
    status: str = "pending"  # ready | cached | procedural | pending | failed
    provider: str = ""
    detail: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status in ("ready", "cached", "procedural")

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "status": self.status,
            "provider": self.provider,
            "detail": self.detail,
        }


class ImageProvider(Protocol):
    """What every backend must offer."""

    name: str

    def available(self) -> bool:
        """Whether this backend can run right now."""

    def generate(self, request: ImageRequest) -> ImageResult:
        """Produce an image. May block for minutes."""


def cached_image(request: ImageRequest) -> Optional[ImageResult]:
    """
    Return a previously generated image for this request, if one exists.

    Caching is not an optimization here, it is the difference between a usable
    game and one that pauses for minutes. Both backends are far too slow to
    regenerate anything.
    """
    for suffix in (".png", ".jpg", ".jpeg", ".webp"):
        path = IMAGE_DIR / f"{request.cache_key()}{suffix}"
        if path.exists() and path.stat().st_size > 0:
            return ImageResult(
                url=f"/api/media/images/{path.name}",
                path=str(path),
                status="cached",
                provider="cache",
            )
    return None


def target_path(request: ImageRequest, suffix: str = ".png") -> Path:
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    return IMAGE_DIR / f"{request.cache_key()}{suffix}"


def url_for(path: Path) -> str:
    return f"/api/media/images/{path.name}"
