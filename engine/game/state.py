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
from typing import Any, Optional, get_args, get_origin, get_type_hints

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


def _coerce_annotated(annotation: Any, raw: Any) -> Any:
    """
    Rebuild a value according to its declared field type.

    WHY THIS IS DERIVED RATHER THAN LISTED: ``from_dict`` used to name its six
    nested dataclasses one by one. Anything a story added beyond those six came
    back from a save as a raw ``dict`` instead of an object, with no warning --
    it would fail later, somewhere else, as an AttributeError on a dict. Reading
    the annotations means a new nested type round-trips the moment it is
    declared, which is the property a per-story state schema needs.

    Handles the bare dataclass and the ``list[Dataclass]`` case, which is every
    shape the state actually uses. Anything else passes through untouched.
    """
    if is_dataclass(annotation) and isinstance(raw, dict):
        return _coerce(annotation, raw)

    if get_origin(annotation) is list and isinstance(raw, list):
        args = get_args(annotation)
        if args and is_dataclass(args[0]):
            return [_coerce(args[0], item) for item in raw]

    return raw


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
    # Active multi-step challenge (skill gauntlet, decision tree, puzzle, dice
    # table). Empty dict when nothing is running. A plain dict for the same
    # reason as encounter: the spec is model-composed and engine-bounded, so its
    # shape varies by kind and must not force a save migration per field.
    # See engine/challenges/.
    challenge: dict[str, Any] = field(default_factory=dict)
    # Quests and arcs (P7). quests maps quest_id -> progress record.
    quests: dict[str, Any] = field(default_factory=dict)
    active_arc: str = "quiet_life"
    arcs_unlocked: list[str] = field(default_factory=lambda: ["quiet_life"])

    # -- story-declared state (see engine/state/schema.py) ----------------
    #
    # The generic containers a story's own values live in when they have no
    # typed field to sit on. Everything above this line is one story's answer
    # welded into the engine; a story with eight 0-100 meters, four progress
    # clocks and nine per-NPC relationship records had nowhere to put any of it,
    # because `flags` is booleans only.
    #
    # Empty for a story whose schema declares `backing: field` throughout -- The
    # Clockwork Dark describes its existing attributes rather than moving them,
    # so these stay empty for the flagship and its saves are unchanged in every
    # key that already existed.
    #
    # Reached through StateStore, never directly: the store is what clamps to
    # declared bounds and records who wrote what.
    meters: dict[str, float] = field(default_factory=dict)
    clocks: dict[str, float] = field(default_factory=dict)
    tracks: dict[str, Any] = field(default_factory=dict)
    # Persistent contracts -- offered, sealed, and live until discharged, broken
    # or transformed. Plain dicts for the same reason as `encounter`: the shape
    # is story-declared and must not force a save migration per field.
    threads: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        """
        Keep evil_phase consistent with evil_progress.

        These are two views of one number. Constructing a state with a progress
        value but a stale phase produced states that disagreed with themselves
        and did not survive a save round trip.

        Guarded on the fields existing, not unconditional. This runs on EVERY
        ``GameState()`` in the process -- every test, every transaction
        savepoint, every load -- and pulled in the doom ticker to do it. A story
        with no doom clock should not import one, and once these two fields are
        a story's declared meters rather than engine fields, the base spine must
        still construct.
        """
        if getattr(self, "evil_progress", None) is None:
            return

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

        The hand-written keys below are The Clockwork Dark's contract and stay
        exactly as they are -- the sheet, the reducer and a dozen components
        read them by name. Everything a STORY declares arrives under ``meters``
        instead, projected from its schema.

        Why both: this allowlist was one of three independent hardcoded payload
        contracts (here, the ``turn_update`` literal, and the reducer's own
        shape), which together meant a story could not show the player a value
        the engine had not already been taught about. A story now declares
        visibility once. Rewriting the flagship's twenty-one keys to prove the
        point would have been a large silent change to every screen for no
        gain, so the projection is added beside them rather than through them.
        """
        return {
            **self._declared_client_values(),
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
            # Pack weight against allowance, with the over-limit state the
            # travel cost multiplier reads -- so the sheet can say WHY the next
            # leg will cost half again, instead of the number moving silently.
            "carry": self._carry_block(),
            "reputations": dict(self.reputations),
            "wounds": [asdict(w) for w in self.wounds],
            "hunger": round(self.hunger, 1),
            # A player at 100/100 whose real cap is 80 because they are hungry
            # has no way to know that from the raw numbers alone.
            "hunger_stage": self.hunger_stage,
            "stamina_cap": self.effective_stamina_cap,
            "encounter": dict(self.encounter),
            # The player has to be able to see the step they are on and the
            # options they may pick, or a challenge is unplayable.
            "challenge": dict(self.challenge),
            "quests": dict(self.quests),
            "active_arc": self.active_arc,
            "turn_number": self.turn_number,
            "ended": self.ended,
        }

    def _carry_block(self) -> dict[str, Any]:
        """
        Pack weight, allowance, and whether travel is being priced for it.

        Never raises: a story with no item registry weighs everything at zero,
        and a failure here must cost the sheet a row, not the player a turn.
        """
        try:
            from engine.game import inventory as inventory_module

            weight = inventory_module.carried_weight(self)
            limit = inventory_module.carry_limit(self)
            return {
                "weight": weight,
                "limit": limit,
                "overloaded": weight > limit,
            }
        except Exception:  # noqa: BLE001 -- see docstring
            return {}

    def _declared_client_values(self) -> dict[str, Any]:
        """
        The story's own declared state, projected by visibility.

        Empty for a story that declares no schema, which is why this is safe to
        splat into the payload unconditionally: both shipped games see no change
        until they describe themselves.

        Never raises. A broken schema must cost the player a meter on the sheet,
        not the turn they just played -- and the schema is validated loudly at
        activation, so a failure here is already being reported somewhere with
        far better context than a serialization call can give.
        """
        try:
            from engine.state.active import store_for

            declared = store_for(self).to_client()
        except Exception:  # noqa: BLE001 -- see docstring
            return {}

        return {"meters": declared} if declared else {}

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

        # Rebuild nested dataclasses from the ANNOTATIONS of the class being
        # loaded, so a subclass's own nested types come back as objects too.
        # `get_type_hints` rather than `field.type` because this module uses
        # `from __future__ import annotations`, which makes every annotation a
        # string that would otherwise never match `is_dataclass`.
        hints = get_type_hints(cls)
        for name, value in list(kwargs.items()):
            annotation = hints.get(name)
            if annotation is None:
                continue
            # An explicit null for a nested dataclass drops out entirely so the
            # field's default_factory runs. The previous code spelled this
            # `data.get("stats") or {}`; without it, a save carrying a null
            # would load `stats=None` and fail on first attribute access.
            if value is None and is_dataclass(annotation):
                kwargs.pop(name)
                continue
            kwargs[name] = _coerce_annotated(annotation, value)

        # evil_progress is the source of truth for phase on load.
        kwargs["evil_progress"] = evil_progress
        kwargs["evil_phase"] = phase_from_progress(evil_progress)
        return cls(**kwargs)