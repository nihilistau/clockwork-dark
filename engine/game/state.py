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

Version: v0.2.1 [2026-08-14]
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
    # `cruelty_bias` and `reward_generosity` lived here, defaulted, and were
    # written by nothing -- so the default 0.2 sent "be merciful with
    # consequences" to every story on every turn. They are story settings now
    # (`settings.storyteller.*`), read by governance.StorytellerMind, and a
    # story that declares neither gets no disposition line. An old save's keys
    # are ignored on load by `_coerce`.
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
    # engine/world/premises.py: the houses inside each district. Empty for a
    # story that declares no ``paths.premises``.
    premises: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "seed": self.seed,
            "npcs": self.npcs,
            "buildings": self.buildings,
            "forest": self.forest,
            "festival": self.festival,
            "shrine_mural": self.shrine_mural,
            "bakery_job_day": self.bakery_job_day,
            "premises": self.premises,
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
    # Empty means "the active story's manifest answers" -- see
    # engine/game/procgen.py::new_game_state, which is where real runs are
    # built. These two carried the flagship's answers ("wayfarer",
    # "forest_clearing") as dataclass defaults, so every bare GameState() in
    # the engine was implicitly a Clockwork Dark character standing in
    # Edgewood's forest.
    archetype: str = ""
    stats: PlayerStats = field(default_factory=PlayerStats)
    location_id: str = ""
    awareness: float = 0.0
    evil_phase: EvilPhase = EvilPhase.DORMANT
    evil_progress: float = 0.0
    plot_involvement: float = 0.0
    story_pressure: float = 0.0
    #: `story_pressure` as it stood at the previous advance of world time, so a
    #: narrator can be told which WAY the story is leaning and not only how far.
    #: Written in exactly one place -- `clock.advance_time`, immediately before
    #: the recompute -- because `update_story_pressure` is called several times
    #: per turn and a naive "remember the last value" would compare a turn
    #: against itself and report every story as steady. Neutral zero: a fresh
    #: state and a state loaded from a save that predates the field agree.
    story_pressure_prev: float = 0.0
    # Earned reprieve against the doom clock, 0-100. Granted only through the
    # `doom_resistance` effect kind (quest rewards, set-piece victories), spent
    # by decay inside EvilTicker.advance. Neutral zero: a story with no doom
    # clock never writes it and never reads it. Hidden like awareness -- the
    # player feels it as the dark slowing down, never as a number.
    doom_resistance: float = 0.0
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
    #: What changed since the narrator last looked -- engine/game/moved.py.
    #: Presentation, not rules; saved so a reload does not lose what the
    #: player has not yet been told.
    moved: list[dict[str, Any]] = field(default_factory=list)
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
    # The authored scene currently being played: a hand dealt from a deck, and
    # how far through it the player is. Empty dict when no scene is running,
    # which for a story declaring no `paths.decks` is always -- the flagship and
    # NEON CITY never fill this. A plain dict for the same reason as the two
    # above, and card IDS rather than card objects so the save stays small and a
    # mid-run content edit degrades to "that card is gone" instead of silently
    # replaying a stale copy. See engine/content/director.py.
    scene: dict[str, Any] = field(default_factory=dict)
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
    # What casing has learned about each house: premise id -> intel ids, in the
    # order they were learned. Written only by the ``intel`` effect kind
    # (engine/world/premises.py::case). Ids rather than texts, so a premise's
    # occupancy line is re-read from the routines each time rather than frozen
    # at the hour it was first seen. Empty for a story with no premises.
    premise_intel: dict[str, list[str]] = field(default_factory=dict)
    # Where stolen goods came from: item id -> one ``{"whom", "where", "day"}``
    # per unit taken, oldest first. Appended only by the ``item`` effect when it
    # carries ``stolen_from``, consumed only by the ``provenance`` kind (a sale).
    # ``thievery.heat`` reads it: the record, not the object, is what makes a
    # ring hot. Empty for a story with no thievery, and absent from an old save,
    # which loads as "nothing was ever stolen".
    provenance: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    # What the watch knows: reports filed, cooling per jurisdiction, and (once
    # the player changes them) the current guise and the links the watch
    # believes. A plain dict for the ``encounter`` reason -- its shape grows
    # through v0.10.0 and must not force a save migration per key. Written only
    # by the Law's effect kinds (engine/world/law.py). Empty for a story with
    # no Law, and absent from an old save, which loads as "the watch knows
    # nothing".
    law: dict[str, Any] = field(default_factory=dict)
    # Burglaries: the veiled prep meter, the premises already robbed, the job
    # id counter, the open job (``active``, present only while one runs) and
    # the last job's close. A plain dict for the ``law`` reason. Written only
    # by the job effect kinds (engine/world/jobs.py). Empty for a story with
    # no jobs, and absent from an old save, which loads as "no job ever run".
    jobs: dict[str, Any] = field(default_factory=dict)

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

    # -- derived place ---------------------------------------------------

    @property
    def location_name(self) -> str:
        """
        What the ACTIVE STORY calls where the player is standing.

        Resolved through the active story's graph, so it is whatever that
        story's ``locations.yaml`` authored, and falls back to the id with its
        underscores opened out -- which is exactly what the client used to do
        for every story, having been given nothing else.

        Never raises: a story with no graph, or an id the graph has lost, still
        has to render a masthead.
        """
        fallback = str(self.location_id or "").replace("_", " ")
        try:
            from engine.game.locations import LOCATIONS

            row = LOCATIONS.get(self.location_id) or {}
            return str(row.get("name") or fallback)
        except Exception:  # noqa: BLE001 -- a header must not be able to fail
            return fallback

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
        instead, projected from its schema, and the two systems that cannot be
        said as a number arrive beside it under ``threads`` and ``endings`` --
        see ``_structural_block``.

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
            **self._structural_block(),
            **self._premises_block(),
            **self._law_block(),
            **self._job_block(),
            "session_id": self.session_id,
            "player_name": self.player_name,
            "archetype": self.archetype,
            "stats": asdict(self.stats),
            "location_id": self.location_id,
            # The AUTHORED name, so the masthead can stop inventing one.
            #
            # The client drew `prettyPlace(location_id)` -- the id with its
            # underscores swapped for spaces -- because the payload carried
            # nothing better. Every story writes `name:` for every location and
            # no player has ever seen one: "edgewood square" instead of
            # "Edgewood Square", "afterdeck" instead of "The Afterdeck". The
            # ids happened to read acceptably in the shipped stories, which is
            # why it went unnoticed rather than why it was fine.
            "location_name": self.location_name,
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
            # Same rule for an authored scene: the card in front of them and how
            # far through the hand they are. Empty for every story that declares
            # no decks.
            "scene": dict(self.scene),
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

        Empty for a story that declares no schema, which is why this was safe
        to splat into the payload unconditionally when it landed. Every shipped
        game has since described itself -- all four ship a ``state.yaml`` -- so
        this projection contributes real keys on all of them and is no longer a
        no-op anywhere in production.

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

    def _structural_block(self) -> dict[str, Any]:
        """
        The structural systems the story DECLARES, projected for the browser.

        ``meters`` covers everything a story can express as a number with
        bounds. Two of its systems cannot be said that way at all: a thread is a
        contract with terms and a due day, and ending eligibility is a list of
        ids with a reason attached to each. ``StateStore.get`` returns a float,
        so neither was projectable through the schema and neither reached the
        client -- which is why two finished screens sat unreachable for months
        with the data for both sitting in ``GameState``.

        DECLARATION IS THE SWITCH, not a slug. A key appears here only when the
        story declares the system that fills it (``paths.threads``,
        ``paths.endings``), so a story that ships neither gets a payload
        identical to the one it got before this method existed, and a client
        keyed off the key's PRESENCE draws no screen for a system the story does
        not have. A story that declares threads and owes nobody anything yet
        gets ``[]``, which is a real empty state and a different thing.

        THE VEILED RULE TRAVELS WITH THE DATA. An ending's continuous 0-1 score
        is projected as a band word by the same code that bands a veiled meter,
        and a silhouette's title never leaves the server -- see
        ``engine/game/endings.py::to_client``.

        Never raises, for the same reason ``_carry_block`` does not: an ending
        table with a malformed gate must cost the player a panel, not the turn
        they just played.
        """
        out: dict[str, Any] = {}

        try:
            from engine.game import threads as threads_module

            if threads_module.is_declared():
                out["threads"] = threads_module.summary(self)
        except Exception:  # noqa: BLE001 -- see docstring
            pass

        try:
            from engine.game import endings as endings_module

            finale = endings_module.to_client(self)
            if finale:
                out["endings"] = finale
        except Exception:  # noqa: BLE001 -- see docstring
            pass

        return out

    def _premises_block(self) -> dict[str, Any]:
        """
        The casing board: houses in the player's district and what watching
        has learned about each.

        DECLARATION IS THE SWITCH, same convention as ``_structural_block``:
        a story that declares no ``paths.premises`` gets no ``premises`` key
        at all, so the flagship's payload stays byte-identical. A story that
        declares premises but whose current district holds none still gets
        ``"premises": []`` -- a real empty state, not an absent system.

        ``known`` carries the LEARNED TEXTS, in the order they were learned --
        never an id, and never a line nobody has watched for yet. The id
        travels on each row only as a React key; the narrator and the player
        never see one (no engine-authored pseudo-id ever reaches prose or
        screen as if it were content).

        Never raises: a broken premises tree must cost the casing board a
        panel, not the turn the player is mid-way through, same as every other
        optional block here.
        """
        try:
            from engine.world import premises as premises_module

            if not premises_module.declared():
                return {}
            board = []
            for prem in premises_module.at(self, self.location_id):
                prem_id = str(prem.get("id"))
                rows = premises_module.intel_for(self, prem_id)
                learned = set(premises_module.known(self, prem_id))
                type_spec = premises_module.spec(str(prem.get("type") or ""))
                board.append(
                    {
                        "id": prem_id,
                        "name": str(prem.get("name") or ""),
                        # `label` is REQUIRED at load time for both a type and
                        # an anchor (premises.py's `_load_type`/`_load_anchor`)
                        # precisely so this never falls back to the raw type
                        # id -- an id is not prose, and this reaches the
                        # player's screen.
                        "type_label": str(type_spec.get("label") or ""),
                        "known": [row["text"] for row in rows if row["id"] in learned],
                        "of": len(rows),
                        "empty_now": premises_module.empty_now(self, prem_id),
                    }
                )
            return {"premises": board}
        except Exception:  # noqa: BLE001 -- see docstring
            return {}

    def _law_block(self) -> dict[str, Any]:
        """
        The Law, for the player's own sheet: the face currently worn, how
        wanted it is in each jurisdiction, and whether the watch is holding
        the player.

        DECLARATION IS THE SWITCH, same convention as ``_premises_block``: a
        story that declares no ``paths.law`` gets no ``law`` key at all, so
        the flagship's payload -- and every other Law-less story's -- stays
        byte-identical. Keyed by JURISDICTION LABEL, never the raw id (an id
        is not prose, and this reaches the player's screen): a wanted-poster
        reads the docks, not `dockside`. Nothing here renders yet -- the wanted-poster UI chrome is
        the v1.0 hue-and-cry plugin's job; this is only the data it will read.

        Never raises: a broken Law file must cost the sheet a panel, not the
        turn the player is mid-way through, same as every other optional
        block here.
        """
        try:
            from engine.game.trade import currency_label
            from engine.world import law as law_module

            if not law_module.declared():
                return {}
            guise = law_module.current_guise(self)
            wanted = {
                law_module.jurisdiction_label(name): law_module.wanted_band(self, guise, name)
                for name in (law_module.load_spec().get("jurisdictions") or {})
            }
            held = law_module.custody(self)
            custody: Optional[dict[str, Any]] = None
            if held:
                fine = int(held.get("fine") or 0)
                custody = {
                    # Both: `fine` meets the plan's own documented contract
                    # (`{fine, days}`), and `fine_text` -- the story's own
                    # money, via `currency_label` -- saves a client from
                    # having to know what a story calls its currency just to
                    # show the number back.
                    "fine": fine,
                    "fine_text": currency_label(fine),
                    "days": int(held.get("days") or 0),
                }
            return {
                "law": {
                    "guise_label": law_module.guise_label(guise),
                    "wanted": wanted,
                    "custody": custody,
                }
            }
        except Exception:  # noqa: BLE001 -- see docstring
            return {}

    def _job_block(self) -> dict[str, Any]:
        """
        The open job for the player's own sheet: house, stage, alarm and prep.

        DECLARATION IS THE SWITCH, same convention as ``_premises_block`` and
        ``_law_block``: a story that declares no ``paths.jobs`` gets no
        ``job`` key at all, so the flagship's payload stays byte-identical.
        ``prep`` sits at a STABLE place -- top-level, and ONLY there -- because
        casing between jobs still earns it, and a client watching for "did
        prep just go up" should not have to also watch whether a job happens
        to be open, nor read two copies of the one meter that could drift
        apart. ``active`` is ``None`` between jobs; its ``stages`` and
        ``stage_label`` are words (``jobs.stage_words``), never a stage id,
        and ``alarm`` is a band word, never a number. The job panel UI is NOT
        WIRED (docs/GOVERNANCE.md) -- this is only the data it will read,
        exactly as the Law's own wanted-poster payload was before it.

        Never raises: a broken jobs file must cost the sheet a panel, not the
        turn the player is mid-way through, same as every other optional
        block here.
        """
        try:
            from engine.world import jobs as jobs_module
            from engine.world import premises as premises_module

            if not jobs_module.declared():
                return {}
            active_job = jobs_module.active(self)
            active: Optional[dict[str, Any]] = None
            if active_job is not None:
                stage = jobs_module.current_stage(self) or ""
                prem = premises_module.get(
                    self, str(active_job.get("premise") or "")
                ) or {}
                active = {
                    "premise_name": str(prem.get("name") or ""),
                    "stage_label": jobs_module.stage_words(self, stage),
                    "stages": jobs_module.stage_labels(self),
                    "at": int(active_job.get("at") or 0),
                    "alarm": jobs_module.alarm_band(self),
                }
            return {"job": {"active": active, "prep": jobs_module.prep_band(self)}}
        except Exception:  # noqa: BLE001 -- see docstring
            return {}

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