"""
Schedule Rolls
==============

Trader, tinker, and militia world events, plus Awareness-gated rumour selection.

Version: v0.2.0 [2026-08-07]
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml

from engine.config import get_config
from engine.game.state import GameState

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parents[2]
_SCHEDULE_CACHE: Optional[dict[str, Any]] = None
_RUMOR_CACHE: Optional[dict[str, Any]] = None

_DEFAULT_FALLBACK_RUMOR = "The village mutters, but nothing clear reaches you."


@dataclass
class SimEvent:
    """World simulation event emitted on tick."""

    event_id: str
    day: int
    npc_ids: list[str] = field(default_factory=list)
    location_id: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    expires_day: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "day": self.day,
            "npc_ids": list(self.npc_ids),
            "location_id": self.location_id,
            "payload": dict(self.payload),
            "expires_day": self.expires_day,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SimEvent:
        return cls(
            event_id=str(data.get("event_id", "")),
            day=int(data.get("day", 0)),
            npc_ids=list(data.get("npc_ids", [])),
            location_id=str(data.get("location_id", "")),
            payload=dict(data.get("payload", {})),
            expires_day=int(data.get("expires_day", 0)),
        )


def load_schedules() -> dict[str, Any]:
    """Load schedule config from YAML."""
    global _SCHEDULE_CACHE
    if _SCHEDULE_CACHE is not None:
        return _SCHEDULE_CACHE

    rel = str(get_config().get("paths.world_schedules", "") or "").strip()
    if not rel:
        logger.debug("[schedules] Story declares no schedules (operation=load_schedules)")
        _SCHEDULE_CACHE = {}
        return _SCHEDULE_CACHE

    path = _ROOT / rel
    if not path.exists():
        logger.warning(
            "[schedules] Config missing (operation=load_schedules, path=%s)", path
        )
        _SCHEDULE_CACHE = {}
        return _SCHEDULE_CACHE

    with path.open(encoding="utf-8") as fh:
        _SCHEDULE_CACHE = yaml.safe_load(fh) or {}
    return _SCHEDULE_CACHE


def _rumors_path() -> Optional[Path]:
    """
    Resolve the rumour file, or None when the story declares none.

    Split out so tests can point it elsewhere.
    """
    rel = str(get_config().get("paths.world_rumors", "") or "").strip()
    return (_ROOT / rel) if rel else None


def load_rumors() -> dict[str, Any]:
    """
    Load and cache the tiered rumour document.

    Returns:
        Parsed document, or an empty dict when the file is absent -- in which
        case callers fall back to the flat ``rumors:`` list still carried in
        schedules.yaml, so an old checkout keeps working.
    """
    global _RUMOR_CACHE
    if _RUMOR_CACHE is not None:
        return _RUMOR_CACHE

    path = _rumors_path()
    if path is None:
        logger.debug("[schedules] Story declares no rumours (operation=load_rumors)")
        _RUMOR_CACHE = {}
        return _RUMOR_CACHE
    if not path.exists():
        logger.info(
            "[schedules] Tiered rumours absent, using flat list "
            "(operation=load_rumors, path=%s)",
            path,
        )
        _RUMOR_CACHE = {}
        return _RUMOR_CACHE

    with path.open(encoding="utf-8") as fh:
        _RUMOR_CACHE = yaml.safe_load(fh) or {}
    return _RUMOR_CACHE


def reset_rumor_cache() -> None:
    """Drop the cached rumour document. Tests and hot reload only."""
    global _RUMOR_CACHE
    _RUMOR_CACHE = None


def _phase_value(state: GameState) -> str:
    """Current evil phase as a plain string."""
    return str(getattr(state.evil_phase, "value", state.evil_phase))


def eligible_rumors(state: GameState) -> list[dict[str, Any]]:
    """
    Rumours the player's Awareness (and the world's phase) permit right now.

    DESIGN.md gates rumour QUALITY, not rumour frequency: low Awareness gets
    unease with no subject, high Awareness gets names, places and dates. The
    old flat list had no gate at all, so a player who had noticed nothing could
    be handed the pattern on turn one.
    """
    document = load_rumors()
    phase = _phase_value(state)
    eligible: list[dict[str, Any]] = []
    for entry in document.get("rumors", []) or []:
        if not isinstance(entry, dict) or not entry.get("text"):
            continue
        try:
            if float(state.awareness) < float(entry.get("min_awareness", 0)):
                continue
        except (TypeError, ValueError):
            continue
        phases = entry.get("requires_phase")
        if phases and phase not in [str(p) for p in phases]:
            continue
        eligible.append(entry)
    return eligible


def pick_rumor(
    state: GameState,
    rng: random.Random,
    *,
    source_npc: str = "",
    schedules: Optional[dict[str, Any]] = None,
) -> str:
    """
    Choose one rumour appropriate to what the player has noticed so far.

    Args:
        state: Current game state; ``awareness`` and ``evil_phase`` gate the pool.
        rng: Draw source. Never ``random`` directly -- see engine/game/rng.py.
        source_npc: Preferred speaker. A PREFERENCE, not a filter: if no rumour
            is attributed to them the whole eligible pool is used, so tightening
            attribution data can never strike a speaker mute.
        schedules: Optional preloaded schedules, used for the legacy fallback.

    Returns:
        Rumour text. Never empty.
    """
    document = load_rumors()
    pool = eligible_rumors(state)

    if not pool:
        # Legacy path: no rumors.yaml, or nothing unlocked yet.
        flat = (schedules if schedules is not None else load_schedules()).get(
            "rumors", []
        )
        if flat:
            return str(rng.choice(flat))
        return str(document.get("fallback") or _DEFAULT_FALLBACK_RUMOR)

    if source_npc:
        attributed = [r for r in pool if str(r.get("source_npc", "")) == source_npc]
        if attributed:
            pool = attributed

    # Weight toward the highest unlocked tier, or a high-Awareness player would
    # keep drawing first-day unease out of the (deliberately larger) tier-1 pool
    # and Awareness would stay invisible.
    weights_cfg = document.get("tier_weights", {}) or {}
    weights = []
    for entry in pool:
        tier = entry.get("tier", 1)
        try:
            weights.append(float(weights_cfg.get(int(tier), 1.0)))
        except (TypeError, ValueError):
            weights.append(1.0)

    chosen = rng.choices(pool, weights=weights, k=1)[0]
    return str(chosen.get("text", ""))


def _pick_rumor(
    rng: random.Random,
    schedules: dict[str, Any],
    state: Optional[GameState] = None,
    *,
    source_npc: str = "",
) -> str:
    """Backward-compatible shim. Prefer ``pick_rumor``."""
    if state is None:
        flat = schedules.get("rumors", [])
        if not flat:
            return _DEFAULT_FALLBACK_RUMOR
        return str(rng.choice(flat))
    return pick_rumor(state, rng, source_npc=source_npc, schedules=schedules)


def _event_active(state: GameState, event_id: str) -> bool:
    return any(e.get("event_id") == event_id for e in state.world_events)


class ScheduleRoll:
    """Roll trader/tinker/militia schedules against game state."""

    @staticmethod
    def check_caravan(
        state: GameState,
        rng: random.Random,
        *,
        schedules: Optional[dict[str, Any]] = None,
        force: bool = False,
    ) -> list[SimEvent]:
        """Roll caravan_arrival — 8% per day after day 5."""
        cfg = (schedules or load_schedules()).get("caravan_arrival", {})
        # An event the story's schedules file does not declare does not fire.
        # The code defaults below used to fill in the flagship's caravan master
        # and square, so a story with no such event still staged one, cast with
        # another story's NPC at a place its map does not contain.
        if not cfg:
            return []
        min_day = int(cfg.get("min_day", 5))
        if state.world_day < min_day:
            return []
        if _event_active(state, "caravan_arrival"):
            return []

        prob = float(cfg.get("probability_per_day", 0.08))
        if not force and rng.random() >= prob:
            return []

        duration = int(cfg.get("duration_days", 2))
        npc_id = str(cfg.get("npc_id", ""))
        # The caravan master is the one carrying the news, so his attributed
        # rumours are preferred over the general pool.
        rumor = pick_rumor(
            state,
            rng,
            source_npc=npc_id,
            schedules=schedules or load_schedules(),
        )
        location_id = str(cfg.get("location_id", ""))
        goods = list(cfg.get("goods", []))

        return [
            SimEvent(
                event_id="caravan_arrival",
                day=state.world_day,
                npc_ids=[npc_id],
                location_id=location_id,
                expires_day=state.world_day + duration,
                payload={"rumor": rumor, "goods": goods, "npc_id": npc_id},
            )
        ]

    @staticmethod
    def check_tinker(
        state: GameState,
        rng: random.Random,
        *,
        days_elapsed: float = 1.0,
        schedules: Optional[dict[str, Any]] = None,
        force: bool = False,
    ) -> list[SimEvent]:
        """Roll tinker_camp — 5% per week."""
        cfg = (schedules or load_schedules()).get("tinker_camp", {})
        if not cfg:  # undeclared event; see check_caravan
            return []
        if _event_active(state, "tinker_camp"):
            return []

        prob = float(cfg.get("probability_per_week", 0.05)) * (days_elapsed / 7.0)
        if not force and rng.random() >= prob:
            return []

        duration = int(cfg.get("duration_days", 3))
        npc_id = str(cfg.get("npc_id", ""))
        location_id = str(cfg.get("location_id", ""))
        goods = list(cfg.get("goods", []))

        return [
            SimEvent(
                event_id="tinker_camp",
                day=state.world_day,
                npc_ids=[npc_id],
                location_id=location_id,
                expires_day=state.world_day + duration,
                payload={"goods": goods, "npc_id": npc_id},
            )
        ]

    @staticmethod
    def check_militia(
        state: GameState,
        rng: random.Random,
        *,
        schedules: Optional[dict[str, Any]] = None,
        force: bool = False,
    ) -> list[SimEvent]:
        """Roll militia_press — only if Awareness >= threshold."""
        cfg = (schedules or load_schedules()).get("militia_press", {})
        if not cfg:  # undeclared event; see check_caravan
            return []
        min_awareness = float(cfg.get("min_awareness", 20))
        if state.awareness < min_awareness:
            return []
        if _event_active(state, "militia_press"):
            return []

        prob = float(cfg.get("probability_per_day", 0.03))
        if not force and rng.random() >= prob:
            return []

        duration = int(cfg.get("duration_days", 1))
        npc_id = str(cfg.get("npc_id", ""))
        location_id = str(cfg.get("location_id", ""))

        return [
            SimEvent(
                event_id="militia_press",
                day=state.world_day,
                npc_ids=[npc_id],
                location_id=location_id,
                expires_day=state.world_day + duration,
                payload={"npc_id": npc_id, "recruitment": True},
            )
        ]