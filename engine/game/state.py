"""
Game State
==========

Canonical truth for all mechanical state.

Serialization has two distinct audiences and therefore two methods:

  - ``to_save_dict()``   complete and lossless; the only thing persistence writes.
  - ``to_client_dict()`` redacted allowlist; the only thing the browser sees.

Never merge them. The previous single ``to_dict(include_hidden=)`` silently
dropped both AgentMinds, so any round trip reset evil progress, awareness and
trust to defaults.

Version: v0.2.0 [2026-08-07]
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field, fields, is_dataclass
from enum import Enum
from typing import Any, Optional

CURRENT_SAVE_VERSION = 2


def _coerce(cls: type, raw: Any) -> Any:
    """
    Build a dataclass from a dict, ignoring unknown keys.

    Schema evolution must never hard-crash a load. The old code splatted raw
    dicts straight into constructors, so a single added field made every
    existing save unloadable with a bare TypeError.
    """
    if not isinstance(raw, dict):
        return raw
    known = {f.name for f in fields(cls)}
    return cls(**{k: v for k, v in raw.items() if k in known})


class EvilPhase(str, Enum):
    """Background evil escalation phases."""

    DORMANT = "dormant"
    STIRRING = "stirring"
    SPREADING = "spreading"
    CONSUMING = "consuming"


@dataclass
class PlayerStats:
    """Player numeric stats."""

    hp: int = 20
    max_hp: int = 20
    stamina: int = 100
    max_stamina: int = 100
    focus: int = 10
    max_focus: int = 10
    craft: int = 10
    gold: int = 5
    # Core attributes (3-18). Skill checks derive modifiers from these via
    # data/rules/skills.yaml; see engine/game/checks.py.
    grit: int = 10
    agility: int = 10
    wits: int = 10
    presence: int = 10


@dataclass
class Wound:
    """
    A lasting injury.

    Wounds carry the weight that HP used to pretend to: a named consequence
    with a skill penalty and a heal date. HP remains only as a death threshold.
    """

    id: str
    text: str
    severity: int = 1
    check_penalty: int = 0
    skills: list[str] = field(default_factory=list)
    heals_on_day: int = 0


@dataclass
class TimedEffect:
    """A temporary modifier swept by the clock when it expires."""

    id: str
    kind: str
    text: str = ""
    delta: int = 0
    skills: list[str] = field(default_factory=list)
    expires_day: int = 0


@dataclass
class InventoryItem:
    """Single inventory entry."""

    id: str
    name: str
    qty: int = 1
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "qty": self.qty, "tags": list(self.tags)}


@dataclass
class AgentMind:
    """Agency knobs for Storyteller or Assistant."""

    intervention_willingness: float = 0.3
    cruelty_bias: float = 0.2
    reward_generosity: float = 0.5
    patience: float = 80.0
    trust_level: float = 20.0
    help_probability: float = 0.4
    current_form: str = "cat"
    appearance_schedule: str = "hidden"


@dataclass
class ProcgenResult:
    """Seeded world generation output (populated in PR7)."""

    seed: int = 0
    npcs: list[dict[str, Any]] = field(default_factory=list)
    buildings: list[dict[str, Any]] = field(default_factory=list)
    forest: dict[str, Any] = field(default_factory=dict)
    festival: dict[str, Any] = field(default_factory=dict)
    shrine_mural: str = ""
    bakery_job_day: int = 3

    def to_dict(self) -> dict[str, Any]:
        return {
            "seed": self.seed,
            "npcs": self.npcs,
            "buildings": self.buildings,
            "forest": self.forest,
            "festival": self.festival,
            "shrine_mural": self.shrine_mural,
            "bakery_job_day": self.bakery_job_day,
        }

    def npc_by_id(self, npc_id: str) -> Optional[dict[str, Any]]:
        """Return NPC dict by id."""
        for npc in self.npcs:
            if npc.get("id") == npc_id:
                return npc
        return None

    def npcs_at(self, location_id: str) -> list[dict[str, Any]]:
        """Return NPCs at a location."""
        return [n for n in self.npcs if n.get("location_id") == location_id]


@dataclass
class GameState:
    """Full session state."""

    session_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    player_name: str = "Traveler"
    archetype: str = "wayfarer"
    stats: PlayerStats = field(default_factory=PlayerStats)
    location_id: str = "forest_clearing"
    awareness: float = 0.0
    evil_phase: EvilPhase = EvilPhase.DORMANT
    evil_progress: float = 0.0
    plot_involvement: float = 0.0
    story_pressure: float = 0.0
    # Absolute hours since the start of day 1. world_day and world_hour are
    # DERIVED from this and must never be assigned directly -- see
    # engine/game/clock.py::advance_time, the only writer.
    world_clock_hours: float = 8.0
    inventory: list[InventoryItem] = field(default_factory=list)
    reputations: dict[str, int] = field(default_factory=dict)
    storyteller_mind: AgentMind = field(default_factory=AgentMind)
    assistant_mind: AgentMind = field(default_factory=AgentMind)
    procgen: ProcgenResult = field(default_factory=ProcgenResult)
    flags: dict[str, bool] = field(default_factory=dict)
    world_events: list[dict[str, Any]] = field(default_factory=list)
    rumors: list[str] = field(default_factory=list)
    last_sim_tick_at: float = 0.0
    media_cache: dict[str, str] = field(default_factory=dict)
    media_cutscenes_shown: list[str] = field(default_factory=list)
    last_cutscene_phase: str = ""
    turn_number: int = 0
    ended: bool = False
    save_version: int = CURRENT_SAVE_VERSION
    # Deterministic RNG. One counter per named stream, so the same seed replays
    # identically, consecutive draws differ, and streams stay independent of
    # each other. See engine/game/rng.py.
    rng_seed: int = 0
    rng_counters: dict[str, int] = field(default_factory=dict)
    # Survival + status (P4)
    hunger: float = 0.0
    wounds: list[Wound] = field(default_factory=list)
    active_effects: list[TimedEffect] = field(default_factory=list)
    # Active encounter (P6). Empty dict when nothing is happening. Held as a
    # plain dict so the save schema does not need a migration every time an
    # encounter gains a field.
    encounter: dict[str, Any] = field(default_factory=dict)
    # Quests and arcs (P7). quests maps quest_id -> progress record.
    quests: dict[str, Any] = field(default_factory=dict)
    active_arc: str = "quiet_life"
    arcs_unlocked: list[str] = field(default_factory=lambda: ["quiet_life"])

    def __post_init__(self) -> None:
        """
        Keep evil_phase consistent with evil_progress.

        These are two views of one number. Constructing a state with a progress
        value but a stale phase produced states that disagreed with themselves
        and did not survive a save round trip.
        """
        from engine.game.evil_ticker import phase_from_progress

        self.evil_phase = phase_from_progress(self.evil_progress)

    # -- derived time ----------------------------------------------------

    @property
    def world_day(self) -> int:
        """Day number, 1-based. Derived from world_clock_hours."""
        return 1 + int(self.world_clock_hours // 24)

    @property
    def world_hour(self) -> int:
        """Hour of day, 0-23. Derived from world_clock_hours."""
        return int(self.world_clock_hours % 24)

    @property
    def time_of_day(self) -> str:
        """Coarse daypart label used by prompts, art tags and NPC schedules."""
        hour = self.world_hour
        if 5 <= hour < 8:
            return "dawn"
        if 8 <= hour < 17:
            return "day"
        if 17 <= hour < 20:
            return "dusk"
        return "night"

    @property
    def hunger_stage(self) -> str:
        """
        Coarse hunger label for the UI and prompts.

        Delegates to the survival rules rather than restating the thresholds.
        A second copy of the numbers here disagreed with data/rules/survival.yaml
        immediately: the sheet advertised a cap the engine was not enforcing.
        """
        try:
            from engine.game import survival

            return survival.hunger_stage(self)
        except ImportError:
            return "fed"

    @property
    def effective_stamina_cap(self) -> int:
        """Stamina ceiling after hunger penalties, per the survival rules."""
        try:
            from engine.game import survival

            return int(survival.stamina_cap(self))
        except ImportError:
            return self.stats.max_stamina

    # -- serialization ---------------------------------------------------

    def to_save_dict(self) -> dict[str, Any]:
        """
        Complete, lossless serialization. The only form persistence writes.

        Every field round-trips; tests/test_state.py asserts this on a fully
        non-default state and is not permitted to hand-patch omissions.
        """
        data = asdict(self)
        data["evil_phase"] = self.evil_phase.value
        return data

    def to_client_dict(self) -> dict[str, Any]:
        """
        Redacted view for the browser.

        Awareness and evil_progress are hidden stats: the player experiences
        them through fiction, never as numbers. evil_phase ships because the UI
        re-tints on it, but the raw progress does not.
        """
        return {
            "session_id": self.session_id,
            "player_name": self.player_name,
            "archetype": self.archetype,
            "stats": asdict(self.stats),
            "location_id": self.location_id,
            "evil_phase": self.evil_phase.value,
            "world_day": self.world_day,
            "world_hour": self.world_hour,
            "time_of_day": self.time_of_day,
            "inventory": [i.to_dict() for i in self.inventory],
            "reputations": dict(self.reputations),
            "wounds": [asdict(w) for w in self.wounds],
            "hunger": round(self.hunger, 1),
            # A player at 100/100 whose real cap is 80 because they are hungry
            # has no way to know that from the raw numbers alone.
            "hunger_stage": self.hunger_stage,
            "stamina_cap": self.effective_stamina_cap,
            "encounter": dict(self.encounter),
            "quests": dict(self.quests),
            "active_arc": self.active_arc,
            "turn_number": self.turn_number,
            "ended": self.ended,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GameState:
        """
        Deserialize from a save dict.

        Unknown keys are ignored rather than raising, so a save written by an
        older build still loads after new fields land.
        """
        from engine.game.evil_ticker import phase_from_progress

        evil_progress = float(data.get("evil_progress", 0.0))
        known = {f.name for f in fields(cls)}
        kwargs: dict[str, Any] = {
            k: v for k, v in data.items() if k in known
        }

        kwargs["stats"] = _coerce(PlayerStats, data.get("stats") or {})
        kwargs["inventory"] = [
            _coerce(InventoryItem, i) for i in data.get("inventory", [])
        ]
        kwargs["procgen"] = _coerce(ProcgenResult, data.get("procgen") or {})
        kwargs["storyteller_mind"] = _coerce(AgentMind, data.get("storyteller_mind") or {})
        kwargs["assistant_mind"] = _coerce(AgentMind, data.get("assistant_mind") or {})
        kwargs["wounds"] = [_coerce(Wound, w) for w in data.get("wounds", [])]
        kwargs["active_effects"] = [
            _coerce(TimedEffect, e) for e in data.get("active_effects", [])
        ]
        # evil_progress is the source of truth for phase on load.
        kwargs["evil_progress"] = evil_progress
        kwargs["evil_phase"] = phase_from_progress(evil_progress)
        return cls(**kwargs)