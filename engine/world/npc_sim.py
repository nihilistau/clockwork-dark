"""
NPC Simulation
==============

Where each NPC actually is, and what they are doing there.

NPCs used to carry one ``location_id`` written at world generation and never
touched again. Maris stood in her bakery at three in the morning, Sera never
came off the gate, and ``forest_clearing`` -- the location every single run
STARTS in -- contained nobody at all, so the opening scene was narrated to an
empty glade.

Presence is DERIVED on read rather than stored on state. Two reasons:

  1. It cannot drift out of sync with the clock, and it survives a save round
     trip for free because there is nothing extra to serialize.
  2. It is idempotent. ``prompts.py`` calls this once per turn and tests call
     it in loops; neither may consume RNG or mutate the world.

Precedence, highest first:

    quest pin      state.flags["npc_pin_<id>"]   -- a quest outranks weather
    world event    an active SimEvent listing the NPC
    state override state.flags["npc_at_<id>"]    -- soft, non-quest relocation
    routine        data/world/npc_schedules.yaml
    procgen home   the NPC's generated location_id

Version: v0.1.0 [2026-08-07]
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import yaml

from engine.config import get_config
from engine.game.rng import stable_rng
from engine.game.state import GameState

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parents[2]
_SCHEDULE_CACHE: Optional[dict[str, Any]] = None

# Flag conventions. GameState.flags is annotated dict[str, bool], but a pin has
# to say WHERE, so these carry a location id string. A bare ``True`` is honoured
# as "hold them at home" rather than ignored, because a caller who wrote True
# clearly meant something.
PIN_FLAG_PREFIX = "npc_pin_"
PIN_UNTIL_SUFFIX = "_until_day"
OVERRIDE_FLAG_PREFIX = "npc_at_"

_ACTIVITY_STREAM = "npc_activity"


@dataclass
class NPCPresence:
    """One NPC, resolved for the current world hour."""

    npc_id: str
    name: str
    role: str
    location_id: str
    activity: str = ""
    available: bool = True
    visiting: bool = False
    event_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Prompt-facing shape. ``id`` not ``npc_id`` -- procgen's key wins."""
        return {
            "id": self.npc_id,
            "name": self.name,
            "role": self.role,
            "location_id": self.location_id,
            "activity": self.activity,
            "available": self.available,
            "visiting": self.visiting,
            "event_id": self.event_id,
        }


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------


def _schedules_path() -> Path:
    """Resolve the routine file. Split out so tests can point it elsewhere."""
    rel = get_config().get("paths.npc_schedules", "data/world/npc_schedules.yaml")
    return _ROOT / rel


def load_npc_schedules() -> dict[str, Any]:
    """
    Load and cache NPC routines from YAML.

    Returns:
        Parsed routine document, or an empty dict when the file is absent. A
        missing file degrades to procgen homes -- the pre-existing behaviour --
        rather than raising in the middle of a turn.
    """
    global _SCHEDULE_CACHE
    if _SCHEDULE_CACHE is not None:
        return _SCHEDULE_CACHE

    path = _schedules_path()
    if not path.exists():
        logger.warning(
            "[npc_sim] Routines missing, falling back to procgen homes "
            "(operation=load_npc_schedules, path=%s)",
            path,
        )
        _SCHEDULE_CACHE = {}
        return _SCHEDULE_CACHE

    with path.open(encoding="utf-8") as fh:
        _SCHEDULE_CACHE = yaml.safe_load(fh) or {}
    return _SCHEDULE_CACHE


def reset_schedule_cache() -> None:
    """Drop the cached routine document. Tests and hot reload only."""
    global _SCHEDULE_CACHE
    _SCHEDULE_CACHE = None


# ---------------------------------------------------------------------------
# Resolution helpers
# ---------------------------------------------------------------------------


def _routine_slot(cfg: dict[str, Any], hour: int) -> Optional[dict[str, Any]]:
    """Return the routine entry covering ``hour``, or None."""
    for slot in cfg.get("routine", []) or []:
        if not isinstance(slot, dict):
            continue
        try:
            hours = {int(h) % 24 for h in slot.get("hours", [])}
        except (TypeError, ValueError):
            continue
        if hour in hours:
            return slot
    return None


def _role_activity(
    data: dict[str, Any],
    state: GameState,
    npc_id: str,
    role: str,
) -> tuple[str, bool]:
    """
    Pick a by-role activity for an NPC with no routine of their own.

    Drawn from ``stable_rng`` keyed on (seed, npc, day) rather than
    ``world_rng``: this runs on every prompt build, so consuming a state RNG
    counter here would make the same save replay differently depending on how
    many times the UI happened to render.
    """
    defaults = data.get("defaults", {}) or {}
    fallback = str(defaults.get("activity", ""))

    night_hours = set()
    for raw in data.get("night_hours", []) or []:
        try:
            night_hours.add(int(raw) % 24)
        except (TypeError, ValueError):
            continue
    is_night = state.world_hour in night_hours

    role_defaults = data.get("role_defaults", {}) or {}
    cfg = role_defaults.get(role) or role_defaults.get("default") or {}
    pool = list(cfg.get("night" if is_night else "day", []) or [])
    if not pool:
        return fallback, not is_night

    rng = stable_rng(state.rng_seed + state.world_day, f"{_ACTIVITY_STREAM}.{npc_id}")
    return str(rng.choice(pool)), not is_night


def _active_event(state: GameState, npc_id: str) -> Optional[tuple[str, str]]:
    """Return (location_id, event_id) of the first active event listing the NPC."""
    for raw in state.world_events:
        if npc_id in [str(n) for n in raw.get("npc_ids", [])]:
            return str(raw.get("location_id", "")), str(raw.get("event_id", ""))
    return None


def _flag_location(state: GameState, key: str, home: str) -> str:
    """
    Read a location-carrying flag.

    A string value is the destination. ``True`` means "hold them at home",
    which is the only sensible reading of a boolean pin.
    """
    value = state.flags.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    if value is True:
        return home
    return ""


def _expire_pins(state: GameState) -> None:
    """Drop quest pins whose day has passed, so no pin is accidentally forever."""
    day = state.world_day
    stale: list[str] = []
    for key, raw in list(state.flags.items()):
        if not (key.startswith(PIN_FLAG_PREFIX) and key.endswith(PIN_UNTIL_SUFFIX)):
            continue
        try:
            until = int(raw)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        if until > day:
            continue
        stale.append(key)

    for key in stale:
        pin_key = key[: -len(PIN_UNTIL_SUFFIX)]
        state.flags.pop(key, None)
        state.flags.pop(pin_key, None)
        logger.info(
            "[npc_sim] Quest pin expired (operation=refresh, flag=%s, day=%s)",
            pin_key,
            day,
        )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def resolve_npc(state: GameState, npc_id: str) -> Optional[NPCPresence]:
    """
    Resolve one NPC's presence for the current world hour.

    Args:
        state: Current game state. Never mutated.
        npc_id: Canonical NPC id.

    Returns:
        NPCPresence, or None when the id is unknown to both procgen and the
        routine file.
    """
    npc_id = str(npc_id)
    data = load_npc_schedules()
    cfg = (data.get("npcs", {}) or {}).get(npc_id) or {}
    procgen_npc = state.procgen.npc_by_id(npc_id) or {}
    if not cfg and not procgen_npc and not _active_event(state, npc_id):
        return None

    defaults = data.get("defaults", {}) or {}
    relocated = str(defaults.get("relocated_activity", defaults.get("activity", "")))

    name = str(procgen_npc.get("name") or cfg.get("name") or npc_id)
    role = str(procgen_npc.get("role") or cfg.get("role") or "visitor")
    home = str(cfg.get("home") or procgen_npc.get("location_id") or "")

    slot = _routine_slot(cfg, state.world_hour)
    if slot:
        location = str(slot.get("location") or home)
        activity = str(slot.get("activity") or defaults.get("activity", ""))
        available = bool(slot.get("available", True))
    else:
        location = home
        activity, available = _role_activity(data, state, npc_id, role)

    # -- state override (soft relocation, below events) ---------------------
    override = _flag_location(state, f"{OVERRIDE_FLAG_PREFIX}{npc_id}", home)
    if override and override != location:
        location, activity = override, relocated

    # -- world event --------------------------------------------------------
    visiting = False
    event_id = ""
    event = _active_event(state, npc_id)
    if event:
        event_location, event_id = event
        visiting = True
        event_activities = data.get("event_activities", {}) or {}
        if event_location and event_location != location:
            location = event_location
            activity = str(event_activities.get(event_id) or relocated)
        else:
            activity = str(event_activities.get(event_id) or activity)
        # An event NPC is here BECAUSE of the event; they are not asleep through
        # their own caravan arrival.
        available = True

    # -- quest pin ----------------------------------------------------------
    # Deliberately outranks the event: a quest that put someone somewhere must
    # not be undercut by a caravan rolling into town on the same day.
    pin = _flag_location(state, f"{PIN_FLAG_PREFIX}{npc_id}", home)
    if pin:
        if pin != location:
            location = pin
            activity = str(defaults.get("pinned_activity") or relocated)
        available = True

    return NPCPresence(
        npc_id=npc_id,
        name=name,
        role=role,
        location_id=location,
        activity=activity,
        available=available,
        visiting=visiting,
        event_id=event_id,
    )


def known_npc_ids(state: GameState) -> list[str]:
    """Every NPC id the sim can resolve, in stable order and deduplicated."""
    ordered: list[str] = []
    seen: set[str] = set()

    def _add(raw: Any) -> None:
        npc_id = str(raw)
        if npc_id and npc_id not in seen:
            seen.add(npc_id)
            ordered.append(npc_id)

    for npc in state.procgen.npcs:
        _add(npc.get("id"))
    for npc_id in (load_npc_schedules().get("npcs", {}) or {}):
        _add(npc_id)
    for event in state.world_events:
        for npc_id in event.get("npc_ids", []):
            _add(npc_id)
    return ordered


def npcs_at(state: GameState, location_id: str) -> list[NPCPresence]:
    """
    Everyone currently at a location, asleep or awake.

    Sleepers are included on purpose: "Maris is asleep on the cot above the
    ovens" is a scene the Storyteller should be able to narrate, and hiding her
    would make the bakery read as abandoned at night.
    """
    present: list[NPCPresence] = []
    for npc_id in known_npc_ids(state):
        presence = resolve_npc(state, npc_id)
        if presence and presence.location_id == location_id:
            present.append(presence)
    return present


def refresh(state: GameState) -> None:
    """
    Per-tick hook, called from ``engine.game.clock.advance_time``.

    Presence itself is derived on read, so there is nothing to recompute here.
    What the clock DOES owe the sim is pin housekeeping: a quest pin with an
    expiry has to be swept by something that sees the calendar move, or it
    outlives the quest that set it.

    Cheap and idempotent by contract -- it may be called several times for the
    same hour.
    """
    load_npc_schedules()
    _expire_pins(state)
