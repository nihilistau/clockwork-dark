"""
Shipped Art Provider (top of the chain)
=======================================

Serves the curated art pack that ships with the game.

This is the default source of every picture, and generation is the exception.
The previous arrangement had it backwards: each still was generated on demand,
which costs two to three minutes on Imagine and makes a real-time loop
impossible -- and it only happened at all if the narrator remembered to emit
an ``[IMAGE:]`` tag, so mostly there was no picture whatsoever.

Selection is deterministic. A location with alternates picks one from
``(subject, time_of_day, seed)``, so the same place looks the same on the same
save while still varying between runs and dayparts.

Version: v0.2.0 [2026-08-07]
"""

from __future__ import annotations

import functools
import logging
from pathlib import Path
from typing import Any, Optional

import yaml

from engine.config import get_config, project_root
from engine.game.rng import stable_rng
from engine.media.providers.base import ImageRequest, ImageResult

logger = logging.getLogger(__name__)

ART_ROOT = Path("content/scenes/clockwork/static/art")
CORRUPT_PHASES = ("spreading", "consuming")


@functools.lru_cache(maxsize=1)
def load_manifest() -> dict[str, Any]:
    path = get_config().resolve_path("paths.art_manifest", "data/art/manifest.yaml")
    if path is None or not path.exists():
        logger.info("[media] No art manifest (operation=load_manifest, path=%s)", path)
        return {}
    try:
        with path.open(encoding="utf-8") as handle:
            return yaml.safe_load(handle) or {}
    except (OSError, yaml.YAMLError) as exc:
        logger.warning("[media] Unreadable art manifest (operation=load_manifest): %s", exc)
        return {}


def reset_manifest_cache() -> None:
    """Tests only."""
    load_manifest.cache_clear()


def _exists(relative: str) -> bool:
    return bool(relative) and (project_root() / ART_ROOT / relative).is_file()


def _url(relative: str) -> str:
    manifest_root = str(load_manifest().get("root", "/static/art")).rstrip("/")
    return f"{manifest_root}/{relative}"


def lookup(request: ImageRequest) -> Optional[str]:
    """
    Resolve a request to a packed art file, or None.

    Returns the path relative to the art root.
    """
    manifest = load_manifest()
    if not manifest:
        return None

    if request.kind == "portrait":
        # Assistant forms are addressed by form name, NPCs by id.
        forms = manifest.get("assistant_forms", {})
        direct = forms.get(request.subject_id) or manifest.get("portraits", {}).get(
            request.subject_id
        )
        return direct if _exists(direct or "") else None

    if request.kind == "item":
        candidate = manifest.get("items", {}).get(request.subject_id)
        return candidate if _exists(candidate or "") else None

    if request.kind == "enemy":
        candidate = manifest.get("enemies", {}).get(request.subject_id)
        return candidate if _exists(candidate or "") else None

    entry = manifest.get("locations", {}).get(request.subject_id)
    if not entry:
        return None

    # A corrupted world gets its own plates where they exist -- this is the
    # cheapest, most legible way to show the phase turning.
    if request.evil_phase in CORRUPT_PHASES:
        corrupted = [p for p in entry.get("corrupted", []) if _exists(p)]
        if corrupted:
            rng = stable_rng(hash(request.subject_id) & 0xFFFF, f"art.{request.evil_phase}")
            return rng.choice(corrupted)

    by_time = entry.get("times", {}).get(request.time_of_day)
    if _exists(by_time or ""):
        return by_time

    pool = [p for p in [entry.get("base"), *entry.get("alts", [])] if _exists(p or "")]
    if not pool:
        return None
    # Deterministic per (place, daypart): stable within a save, varied across
    # the day, and never a different picture on every render.
    rng = stable_rng(hash((request.subject_id, request.time_of_day)) & 0xFFFFFFFF, "art")
    return rng.choice(pool)


class ShippedArtProvider:
    """Curated art that ships with the game."""

    name = "shipped"

    def available(self) -> bool:
        return bool(load_manifest())

    def generate(self, request: ImageRequest) -> ImageResult:
        relative = lookup(request)
        if relative is None:
            return ImageResult(status="failed", provider=self.name, detail="not in manifest")
        return ImageResult(
            url=_url(relative),
            path=str(ART_ROOT / relative),
            status="cached",
            provider=self.name,
            detail=relative,
        )
