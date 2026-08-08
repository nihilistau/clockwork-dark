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

The art ROOT is per-story (``paths.art_root``). It used to be a constant
pointing at the flagship's static tree, so a second story's manifest could name
files that no lookup could ever find.

Version: v0.3.0 [2026-08-08]
"""

from __future__ import annotations

import functools
import logging
import zlib
from pathlib import Path
from typing import Any, Optional

import yaml

from engine.config import get_config
from engine.game.rng import stable_rng
from engine.media.providers.base import ImageRequest, ImageResult

logger = logging.getLogger(__name__)

# The DEFAULT art root, repo-relative. This was the whole story until v0.2.1:
# a module constant naming the flagship's static tree, which meant a second
# game had nowhere to put art the lookup would find. Every Garden plate missed
# and the procedural silhouette answered.
#
# Still a module constant, and still relative, because scripts/generate_art.py
# joins it against the repo root to promote newly generated flagship plates.
# The ACTIVE story's root is `art_root()` below; this is only its default.
ART_ROOT = Path("content/scenes/clockwork/static/art")
CORRUPT_PHASES = ("spreading", "consuming")


@functools.lru_cache(maxsize=1)
def art_root() -> Optional[Path]:
    """
    Absolute directory the active story's manifest paths are relative to.

    Cached and registered in ``engine/games/caches.py`` beside
    ``load_manifest``: the two are read together on every lookup, and a game
    swap that cleared one and not the other would resolve the new story's
    manifest entries against the previous story's directory -- which mostly
    misses, so the visible symptom is art silently disappearing.

    Returns:
        The story's own art directory, or None when it declares none. This
        used to fall back to ``ART_ROOT`` -- the FLAGSHIP's tree -- which is the
        same mistake in Python that ``config/default.yaml`` was making in YAML:
        a story with no art pack would resolve Edgewood's filenames against
        Edgewood's directory and quietly serve another story's pictures.
        Without a root there is no pack, and the procedural provider answers.
    """
    return get_config().resolve_path("paths.art_root")


def _seed(*parts: str) -> int:
    """
    A stable integer for a set of strings.

    NOT ``hash()``. Python randomizes ``hash()`` of ``str`` and ``tuple`` per
    process (PYTHONHASHSEED), so the previous seed was stable within a run and
    different in the next one -- every location in the game changed picture each
    time the server restarted, while the comment beside it promised "never a
    different picture on every render". True within a process, false across
    restarts, and invisible unless you happened to look at the same place twice
    either side of a restart.

    crc32 because this picks a plate from a list; it needs to be stable and
    cheap, not cryptographic.
    """
    return zlib.crc32("\x1f".join(parts).encode("utf-8"))


@functools.lru_cache(maxsize=1)
def load_manifest() -> dict[str, Any]:
    path = get_config().resolve_path("paths.art_manifest")
    if path is None:
        logger.debug("[media] Story declares no art manifest (operation=load_manifest)")
        return {}
    if not path.exists():
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
    art_root.cache_clear()


def _exists(relative: str) -> bool:
    root = art_root()
    return bool(relative) and root is not None and (root / relative).is_file()


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
            rng = stable_rng(_seed(request.subject_id), f"art.{request.evil_phase}")
            return rng.choice(corrupted)

    by_time = entry.get("times", {}).get(request.time_of_day)
    if _exists(by_time or ""):
        return by_time

    pool = [p for p in [entry.get("base"), *entry.get("alts", [])] if _exists(p or "")]
    if not pool:
        return None
    # Deterministic per (place, daypart): stable within a save, varied across
    # the day, and never a different picture on every render.
    rng = stable_rng(_seed(request.subject_id, request.time_of_day), "art")
    return rng.choice(pool)


class ShippedArtProvider:
    """Curated art that ships with the game."""

    name = "shipped"

    def available(self) -> bool:
        return bool(load_manifest())

    def generate(self, request: ImageRequest) -> ImageResult:
        relative = lookup(request)
        root = art_root()
        if relative is None or root is None:
            return ImageResult(status="failed", provider=self.name, detail="not in manifest")
        return ImageResult(
            url=_url(relative),
            path=str(root / relative),
            status="cached",
            provider=self.name,
            detail=relative,
        )
