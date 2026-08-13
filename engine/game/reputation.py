"""
Faction Reputation
==================

How a group regards the player, and what that costs them.

``GameState.reputations`` has existed since PR1 with zero writers and zero
readers anywhere in the codebase -- it round-tripped through save files and
shipped to the browser in ``to_client_dict()`` as a permanently empty dict.
This module is the first code to put anything in it.

Reputation is deliberately NOT the same thing as disposition. How one person
feels about the player lives in ``engine.memory.ledger.NPCRelation`` and stays
there; this is the standing of a group, which moves slower, is public, and is
what a shopkeeper prices off.

Version: v0.1.0 [2026-08-07]
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional, Union

import yaml

from engine.config import get_config
from engine.game.state import GameState

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parents[2]
_FACTION_CACHE: Optional[dict[str, Any]] = None

# Faction ids are the STORY's, declared in its factions file and addressed by
# the strings that file uses. The engine used to export the flagship's five as
# module constants (EDGEWOOD, MERCHANTS, MILITIA, TINKERS, UNNAMED_SAINTS);
# nothing ever imported them, and an engine constant per story faction is the
# engine memorising one story's world.

_UNKNOWN_STANDING = "unknown"


def _factions_path() -> Optional[Path]:
    """
    Resolve the faction file, or None when the story declares none.

    Split out so tests can point it elsewhere. A story with no factions
    resolves every standing as unknown, which is what a world with no organised
    powers should do -- rather than resolving it against another story's
    militia, which is what the engine's default path used to do.
    """
    rel = str(get_config().get("paths.factions", "") or "").strip()
    return (_ROOT / rel) if rel else None


def load_factions() -> dict[str, Any]:
    """
    Load and cache the faction document.

    Returns:
        Parsed document, or an empty dict when the file is absent.
    """
    global _FACTION_CACHE
    if _FACTION_CACHE is not None:
        return _FACTION_CACHE

    path = _factions_path()
    if path is None:
        logger.debug("[reputation] Story declares no factions (operation=load_factions)")
        _FACTION_CACHE = {}
        return _FACTION_CACHE
    if not path.exists():
        logger.warning(
            "[reputation] Factions missing (operation=load_factions, path=%s)", path
        )
        _FACTION_CACHE = {}
        return _FACTION_CACHE

    with path.open(encoding="utf-8") as fh:
        _FACTION_CACHE = yaml.safe_load(fh) or {}
    return _FACTION_CACHE


def reset_faction_cache() -> None:
    """Drop the cached faction document. Tests and hot reload only."""
    global _FACTION_CACHE
    _FACTION_CACHE = None


def faction_ids() -> list[str]:
    """All configured faction ids."""
    return list((load_factions().get("factions", {}) or {}).keys())


def faction_name(faction: str) -> str:
    """Display name for a faction, falling back to its id."""
    return str(_faction_cfg(faction).get("name") or faction)


def _faction_cfg(faction: str) -> dict[str, Any]:
    """Faction entry, or an empty dict when unknown."""
    return (load_factions().get("factions", {}) or {}).get(faction) or {}


def _setting(faction: str, key: str) -> Any:
    """Faction-level override for a settings block, else the global default."""
    cfg = _faction_cfg(faction)
    if key in cfg:
        return cfg[key]
    return (load_factions().get("defaults", {}) or {}).get(key)


def _bands(faction: str) -> list[dict[str, Any]]:
    """Ordered standing bands for a faction."""
    raw = _setting(faction, "bands") or []
    return [b for b in raw if isinstance(b, dict)]


def _bounds(faction: str) -> tuple[int, int]:
    """Clamp bounds for a faction's score."""
    low = _setting(faction, "min_score")
    high = _setting(faction, "max_score")
    return int(low if low is not None else -100), int(high if high is not None else 100)


def get(state: GameState, faction: str) -> int:
    """Current score for a faction. Unset factions read as neutral zero."""
    try:
        return int(state.reputations.get(faction, 0))
    except (TypeError, ValueError):
        return 0


def adjust(state: GameState, faction: str, delta: int, *, reason: str = "") -> int:
    """
    Move a faction's standing and record it on state.

    Args:
        state: Mutable game state.
        faction: Canonical faction id.
        delta: Signed change. Clamped into the faction's bounds after applying.
        reason: Free text for the log. Reputation moves are the kind of thing
            players contest later, so every write leaves a trail.

    Returns:
        The new clamped score.
    """
    if faction not in (load_factions().get("factions", {}) or {}):
        # Applied anyway rather than dropped: silently discarding a quest reward
        # is worse than carrying an unrecognised key that shows up in a log.
        logger.warning(
            "[reputation] Unknown faction (operation=adjust, faction=%s, delta=%s)",
            faction,
            delta,
        )

    low, high = _bounds(faction)
    try:
        step = int(delta)
    except (TypeError, ValueError):
        logger.warning(
            "[reputation] Non-numeric delta ignored "
            "(operation=adjust, faction=%s, delta=%r)",
            faction,
            delta,
        )
        return get(state, faction)

    before = get(state, faction)
    after = max(low, min(high, before + step))
    state.reputations[faction] = after

    logger.info(
        "[reputation] Standing changed (operation=adjust, faction=%s, "
        "from=%s, to=%s, standing=%s, reason=%s)",
        faction,
        before,
        after,
        standing(state, faction),
        reason or "unspecified",
    )
    return after


def standing(state: GameState, faction: str) -> str:
    """
    Threshold label for a faction's current score.

    Bands are walked in order and the first whose ``upto`` covers the score
    wins; the final band carries no ``upto`` and catches everything above.
    """
    score = get(state, faction)
    bands = _bands(faction)
    if not bands:
        return _UNKNOWN_STANDING
    for band in bands:
        upto = band.get("upto")
        if upto is None or score <= int(upto):
            return str(band.get("label") or band.get("id") or _UNKNOWN_STANDING)
    return str(bands[-1].get("label") or bands[-1].get("id") or _UNKNOWN_STANDING)


def standing_id(state: GameState, faction: str) -> str:
    """Band id (``hostile``..``trusted``) rather than its display label."""
    score = get(state, faction)
    bands = _bands(faction)
    if not bands:
        return _UNKNOWN_STANDING
    for band in bands:
        upto = band.get("upto")
        if upto is None or score <= int(upto):
            return str(band.get("id") or _UNKNOWN_STANDING)
    return str(bands[-1].get("id") or _UNKNOWN_STANDING)


def price_multiplier(state: GameState, faction: str) -> float:
    """
    What this faction charges the player, as a multiplier on list price.

    ``clamp(base - score / divisor, floor, ceiling)``. Neutral sits above 1.0
    on purpose: a stranger pays the stranger's price, and working down to a
    fair one is meant to be felt.
    """
    cfg = _setting(faction, "price") or {}
    base = float(cfg.get("base", 1.15))
    divisor = float(cfg.get("divisor", 400)) or 400.0
    floor = float(cfg.get("floor", 0.85))
    ceiling = float(cfg.get("ceiling", 1.25))
    return max(floor, min(ceiling, base - get(state, faction) / divisor))


def gate_allows(state: GameState, faction: str, minimum: Union[int, str]) -> bool:
    """
    Test a standing gate.

    Args:
        state: Current game state.
        faction: Canonical faction id.
        minimum: A numeric score, or a band id such as ``"friendly"``. The band
            form is what content should use -- it survives rebalancing the
            numbers, which a hardcoded 25 does not.

    Returns:
        True if the player meets or exceeds the requirement.
    """
    if isinstance(minimum, str):
        order = [str(b.get("id")) for b in _bands(faction)]
        current = standing_id(state, faction)
        if minimum not in order or current not in order:
            logger.warning(
                "[reputation] Unknown standing band "
                "(operation=gate_allows, faction=%s, minimum=%r, current=%s)",
                faction,
                minimum,
                current,
            )
            return False
        return order.index(current) >= order.index(minimum)

    try:
        return get(state, faction) >= int(minimum)
    except (TypeError, ValueError):
        logger.warning(
            "[reputation] Non-numeric gate ignored "
            "(operation=gate_allows, faction=%s, minimum=%r)",
            faction,
            minimum,
        )
        return False


def snapshot(state: GameState) -> dict[str, dict[str, Any]]:
    """Every known faction with score, label and price. For UI and prompts."""
    return {
        faction: {
            "name": faction_name(faction),
            "score": get(state, faction),
            "standing": standing(state, faction),
            "price_multiplier": round(price_multiplier(state, faction), 3),
        }
        for faction in faction_ids()
    }
