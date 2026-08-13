"""
Encounter tests.

Two halves. The first drives the machinery against a synthetic table so a
degree maps to exactly one outcome and nothing is inferred from shipped
content. The second validates the shipped content itself -- every skill,
band, art key, faction and effect type a designer wrote is one the engine
actually understands, which is the class of bug YAML content is best at
hiding.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
import yaml

import engine.skills.builtin.mechanics  # noqa: F401 — registers the skills under test
from engine.game import checks, encounter
from engine.game.clock import advance_time, set_clock
from engine.game.engine import GameEngine
from engine.game.locations import LOCATIONS, get_edge
from engine.game.state import GameState
from engine.skills.registry import SKILL_REGISTRY

# Vocabulary the engine actually implements. Kept literal here on purpose: if
# effects.py grows a type, this list should be updated deliberately rather than
# derived from the implementation and therefore never able to fail.
KNOWN_EFFECT_TYPES = {
    "stat",
    "hp",
    "stamina",
    "focus",
    "craft",
    "gold",
    "hunger",
    "awareness",
    "reputation",
    "item",
    "remove_item",
    "wound",
    "check_penalty",
    "flag",
    "ledger_fact",
}
KNOWN_FACTIONS = {"edgewood", "merchants", "militia", "tinkers", "unnamed_saints"}
KNOWN_DEGREES = {"crit_success", "success", "partial", "failure"}
KNOWN_TRIGGER_KEYS = {
    "edges",
    "to",
    "from",
    "phases",
    "hours",
    "min_day",
    "max_day",
    "requires_flag",
    "forbids_flag",
}


# ---------------------------------------------------------------------------
# synthetic table
# ---------------------------------------------------------------------------

SYNTHETIC = {
    "encounters": [
        {
            "id": "test_scene",
            "band": "test",
            "tier": 1,
            "weight": 100,
            "art": "wolf",
            "triggers": {"edges": ["forest_clearing>edgewood_square"]},
            "intro": "A test.",
            "threat": {"name": "A test threat", "resolve": 3},
            "approaches": {
                "talk": {"skill": "persuasion", "difficulty": "standard", "text": "Talk"},
                "night_only": {
                    "skill": "stealth",
                    "difficulty": "easy",
                    "requires_time": "night",
                    "text": "Only after dark",
                },
                "pay": {"cost_gold": 6, "auto": True, "text": "Pay"},
                "with_item": {
                    "skill": "craft",
                    "difficulty": "easy",
                    "requires_item": "loaf",
                    "text": "Needs a loaf",
                },
            },
            "outcomes": {
                "crit_success": {"text": "CRIT", "effects": [{"type": "gold", "delta": 5}]},
                "success": {"text": "WIN", "effects": []},
                "partial": {"text": "MIXED", "effects": [{"type": "stamina", "delta": -5}]},
                "failure": {
                    "text": "LOSS",
                    "effects": [
                        {
                            "type": "wound",
                            "id": "test_wound",
                            "text": "a test cut",
                            "severity": 2,
                            "check_penalty": -2,
                            "skills": ["craft"],
                            "heals_on_day": "+3",
                        }
                    ],
                },
            },
        },
        {
            "id": "test_lethal",
            "band": "test",
            "weight": 1,
            "triggers": {},
            "intro": "A lethal test.",
            "threat": {"name": "Something final", "resolve": 9},
            "approaches": {
                "die": {"skill": "nerve", "difficulty": "standard", "text": "Die"}
            },
            "outcomes": {
                "failure": {"text": "DOWN", "effects": [{"type": "hp", "delta": -999}]},
                "success": {"text": "UP", "effects": []},
            },
        },
        {
            "id": "test_grind",
            "band": "test",
            "weight": 1,
            "triggers": {},
            "intro": "A long test.",
            "threat": {"name": "Stubborn", "resolve": 99},
            "approaches": {
                "poke": {"skill": "nerve", "difficulty": "standard", "text": "Poke"}
            },
            "outcomes": {"partial": {"text": "GRIND", "effects": []}},
        },
    ],
    "trigger": {
        "base": 0.0,
        "per_danger_dc": 0.05,
        "time_of_day": {"day": 1.0, "night": 2.0, "dawn": 1.0, "dusk": 1.0},
        "evil_progress_bonus": 0.0,
        "stealth_reduction_per_point": 0.0,
        "min_chance": 0.0,
        "max_chance": 1.0,
    },
    "scene": {
        "max_rounds": 3,
        "default_resolve": 3,
        "degree_resolve": {"crit_success": 5, "success": 3, "partial": 1, "failure": 0},
        "ends_on": ["crit_success", "failure"],
    },
    "degree_fallback": {
        "crit_success": ["success"],
        "success": ["crit_success"],
        "partial": ["failure", "success"],
        "failure": ["partial"],
    },
    "default_approaches": {
        "flee": {
            "skill": "survival",
            "difficulty": "easy",
            "text": "Walk away",
            "ends": True,
            "outcomes": {
                "success": {"text": "GONE"},
                "failure": {"text": "GONE ANYWAY"},
            },
        }
    },
}


@pytest.fixture
def synthetic(monkeypatch) -> None:
    """Point the encounter module at a table built for testing, not for play."""
    monkeypatch.setattr(encounter, "load_encounters", lambda: SYNTHETIC)


def force_degree(monkeypatch, degree: str) -> None:
    """Pin every check the encounter runs to one degree."""

    def fake(state, skill, difficulty="standard", **kwargs):
        return SimpleNamespace(
            degree=degree,
            summary=f"{skill} ({difficulty}): forced {degree}.",
            to_dict=lambda: {"skill": skill, "difficulty": difficulty, "degree": degree},
        )

    monkeypatch.setattr(checks, "resolve", fake)


def state_at(day: int = 3, hour: int = 12, **kwargs) -> GameState:
    """A state pinned to a day and hour without side effects."""
    # Pinned explicitly: these are flagship-map tests, and the engine no longer
    # starts a bare GameState anywhere in particular.
    kwargs.setdefault("location_id", "forest_clearing")
    state = GameState(rng_seed=kwargs.pop("rng_seed", 1234), **kwargs)
    set_clock(state, day=day, hour=hour)
    return state


# ---------------------------------------------------------------------------
# triggering
# ---------------------------------------------------------------------------


def test_danger_dc_is_finally_read(synthetic):
    """The edge field nothing has ever consumed now drives the whole roll."""
    state = state_at()
    forest = encounter.trigger_chance(state, "forest_clearing", "edgewood_square")
    road = encounter.trigger_chance(state, "edgewood_square", "millhaven_gate")
    assert forest == pytest.approx(8 * 0.05)
    assert road == pytest.approx(12 * 0.05)
    assert road > forest, "the more dangerous edge must be more dangerous"


def test_zero_danger_edges_never_trigger(synthetic):
    """Crossing the square to Maris's door is not an event."""
    state = state_at()
    assert encounter.trigger_chance(state, "edgewood_square", "edgewood_bakery") == 0.0
    for _ in range(500):
        assert (
            encounter.roll_for_encounter(state, "edgewood_square", "edgewood_bakery")
            is None
        )


def test_unknown_edge_is_safe(synthetic):
    assert encounter.trigger_chance(state_at(), "forest_clearing", "atlantis") == 0.0


def test_night_is_worse_than_day(synthetic):
    day = encounter.trigger_chance(state_at(hour=12), "edgewood_square", "millhaven_gate")
    night = encounter.trigger_chance(state_at(hour=1), "edgewood_square", "millhaven_gate")
    assert night > day


def test_trigger_rate_over_10k_travels_sits_in_band():
    """
    Ten thousand seeded walks against the SHIPPED table.

    The band is deliberately wide. The assertion that matters is that the
    forest path is neither a formality nor a gauntlet, and that the four-hour
    road at midnight is meaningfully worse than the one-hour path at noon.
    """
    quiet = state_at(day=3, hour=11, rng_seed=99)
    hits = sum(
        1
        for _ in range(10_000)
        if encounter.roll_for_encounter(quiet, "forest_clearing", "edgewood_square")
    )
    forest_rate = hits / 10_000
    assert 0.08 < forest_rate < 0.30, forest_rate

    dark = state_at(day=3, hour=23, rng_seed=99)
    hits = sum(
        1
        for _ in range(10_000)
        if encounter.roll_for_encounter(dark, "edgewood_square", "millhaven_gate")
    )
    road_rate = hits / 10_000
    assert 0.25 < road_rate < 0.60, road_rate
    assert road_rate > forest_rate


def test_rolls_are_reproducible_from_seed():
    a, b = state_at(rng_seed=4242), state_at(rng_seed=4242)
    draws_a = [
        (encounter.roll_for_encounter(a, "edgewood_square", "millhaven_gate") or {}).get("id")
        for _ in range(60)
    ]
    draws_b = [
        (encounter.roll_for_encounter(b, "edgewood_square", "millhaven_gate") or {}).get("id")
        for _ in range(60)
    ]
    assert draws_a == draws_b
    assert len(set(draws_a)) > 1, "a frozen generator would repeat one value"


def test_phase_filter_holds_the_clockwork_back():
    """Clockwork threats must not appear while the world is still dormant."""
    dormant = state_at()
    ids = {r["id"] for r in encounter.eligible(dormant, "edgewood_square", "millhaven_gate")}
    assert "clockwork_on_the_millhaven_road" not in ids

    consuming = state_at(evil_progress=0.99)
    ids = {r["id"] for r in encounter.eligible(consuming, "edgewood_square", "millhaven_gate")}
    assert "clockwork_on_the_millhaven_road" in ids


def test_hour_filter_is_respected():
    noon = state_at(day=4, hour=12)
    ids = {r["id"] for r in encounter.eligible(noon, "edgewood_square", "millhaven_gate")}
    assert "night_lantern_behind_you" not in ids

    midnight = state_at(day=4, hour=23)
    ids = {r["id"] for r in encounter.eligible(midnight, "edgewood_square", "millhaven_gate")}
    assert "night_lantern_behind_you" in ids


def test_once_encounters_do_not_repeat(synthetic, monkeypatch):
    row = dict(SYNTHETIC["encounters"][0], id="test_once", once=True)
    monkeypatch.setattr(
        encounter, "load_encounters", lambda: {**SYNTHETIC, "encounters": [row]}
    )
    state = state_at()
    assert encounter.eligible(state, "forest_clearing", "edgewood_square")
    encounter.begin(state, "test_once")
    assert not encounter.eligible(state, "forest_clearing", "edgewood_square")


# ---------------------------------------------------------------------------
# approaches
# ---------------------------------------------------------------------------


def test_available_approaches_never_offers_the_impossible(synthetic):
    """The engine authors the list, so every entry must be takeable."""
    state = state_at(hour=12)
    state.stats.gold = 2
    encounter.begin(state, "test_scene")
    ids = {a["id"] for a in encounter.available_approaches(state)}

    assert "pay" not in ids, "cannot afford it"
    assert "night_only" not in ids, "wrong time of day"
    assert "with_item" not in ids, "no loaf carried"
    assert "talk" in ids
    assert "flee" in ids


def test_available_approaches_open_up_when_requirements_are_met(synthetic):
    state = state_at(hour=1)
    state.stats.gold = 20
    from engine.game.effects import apply_effect

    apply_effect(state, {"type": "item", "item_id": "loaf", "name": "Loaf", "qty": 1})
    encounter.begin(state, "test_scene")
    ids = {a["id"] for a in encounter.available_approaches(state)}
    assert {"talk", "pay", "night_only", "with_item", "flee"} <= ids


def test_flee_is_always_on_the_table(synthetic):
    """A scene with no legal exit is a soft-lock."""
    state = state_at()
    state.stats.gold = 0
    for encounter_id in ("test_scene", "test_lethal", "test_grind"):
        encounter.begin(state, encounter_id)
        ids = {a["id"] for a in encounter.available_approaches(state)}
        assert "flee" in ids
        encounter.end(state)


def test_every_shipped_encounter_offers_something():
    """Same guarantee, asserted against real content in a hostile state."""
    broke = state_at(day=5, hour=3)
    broke.stats.gold = 0
    broke.inventory.clear()
    for row in encounter.all_encounters():
        encounter.begin(broke, row["id"])
        assert encounter.available_approaches(broke), row["id"]
        encounter.end(broke)


def test_available_approaches_is_empty_when_idle(synthetic):
    assert encounter.available_approaches(state_at()) == []


def test_illegal_approach_is_refused_not_raised(synthetic):
    state = state_at(hour=12)
    state.stats.gold = 0
    encounter.begin(state, "test_scene")
    result = encounter.resolve_approach(state, "pay")
    assert result["ok"] is False
    assert "not available" in result["reason"]
    assert encounter.active(state), "a refusal must not end the scene"
    assert state.encounter["round"] == 0


def test_approach_outside_an_encounter_is_refused(synthetic):
    result = encounter.resolve_approach(state_at(), "talk")
    assert result["ok"] is False


# ---------------------------------------------------------------------------
# outcomes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "degree,expected",
    [
        ("crit_success", "CRIT"),
        ("success", "WIN"),
        ("partial", "MIXED"),
        ("failure", "LOSS"),
    ],
)
def test_each_degree_maps_to_its_own_outcome(synthetic, monkeypatch, degree, expected):
    force_degree(monkeypatch, degree)
    state = state_at()
    encounter.begin(state, "test_scene")
    result = encounter.resolve_approach(state, "talk")
    assert result["ok"] is True
    assert result["degree"] == degree
    assert result["text"] == expected


def test_outcome_effects_are_applied(synthetic, monkeypatch):
    force_degree(monkeypatch, "crit_success")
    state = state_at()
    before = state.stats.gold
    encounter.begin(state, "test_scene")
    encounter.resolve_approach(state, "talk")
    assert state.stats.gold == before + 5


def test_failure_leaves_a_named_wound_not_a_hit_point_total(synthetic, monkeypatch):
    force_degree(monkeypatch, "failure")
    state = state_at()
    hp_before = state.stats.hp
    encounter.begin(state, "test_scene")
    encounter.resolve_approach(state, "talk")

    assert state.stats.hp == hp_before
    assert len(state.wounds) == 1
    wound = state.wounds[0]
    assert wound.text == "a test cut"
    assert wound.check_penalty == -2
    assert wound.heals_on_day == state.world_day + 3


def test_wounds_expire_on_schedule(synthetic, monkeypatch):
    # hp is pinned high so an incidental starvation death cannot add its
    # own wound or respawn the player part-way through the assertion.
    force_degree(monkeypatch, "failure")
    state = state_at(day=3)
    # Hunger is zeroed so the five days this test advances cannot starve the
    # player into a death that adds its OWN wound -- which would look exactly
    # like the wound under test failing to heal.
    state.hunger = 0.0
    encounter.begin(state, "test_scene")
    encounter.resolve_approach(state, "talk")
    assert state.wounds
    # Track THIS wound specifically. A failure outcome can also kill, and death
    # adds its own longer-lived wound -- asserting the wound list is simply
    # empty would fail for the wrong reason.
    wound_id = state.wounds[0].id

    def still_open() -> bool:
        return any(w.id == wound_id for w in state.wounds)

    advance_time(state, 24 * 2)
    assert still_open(), "still inside the heal window on day 5"
    advance_time(state, 24 * 3)
    assert not still_open(), "heals_on_day +3 must have passed by day 8"


def test_a_wound_actually_bites_on_the_skills_it_names(synthetic, monkeypatch):
    force_degree(monkeypatch, "failure")
    state = state_at()
    encounter.begin(state, "test_scene")
    encounter.resolve_approach(state, "talk")

    labels = [label for label, _ in checks.gather_modifiers(state, "craft")]
    assert "a test cut" in labels
    labels = [label for label, _ in checks.gather_modifiers(state, "persuasion")]
    assert "a test cut" not in labels


def test_auto_approach_pays_its_cost_and_needs_no_roll(synthetic, monkeypatch):
    def explode(*args, **kwargs):
        raise AssertionError("an auto approach must not roll")

    monkeypatch.setattr(checks, "resolve", explode)
    state = state_at()
    state.stats.gold = 10
    encounter.begin(state, "test_scene")
    result = encounter.resolve_approach(state, "pay")
    assert result["ok"] is True
    assert result["check"] is None
    assert state.stats.gold == 4


# ---------------------------------------------------------------------------
# scene shape
# ---------------------------------------------------------------------------


def test_a_clean_success_breaks_the_threat_in_one_round(synthetic, monkeypatch):
    force_degree(monkeypatch, "success")
    state = state_at()
    encounter.begin(state, "test_scene")
    result = encounter.resolve_approach(state, "talk")
    assert result["threat_resolve"] == 0
    assert result["resolved"] is True
    assert result["outcome"] == "cleared"
    assert not encounter.active(state)
    assert state.encounter == {}, "a finished scene must not linger in the UI payload"


def test_failure_ends_the_scene_immediately(synthetic, monkeypatch):
    force_degree(monkeypatch, "failure")
    state = state_at()
    encounter.begin(state, "test_scene")
    result = encounter.resolve_approach(state, "talk")
    assert result["resolved"] is True
    assert result["outcome"] == "overcome"


def test_a_scene_cannot_run_past_the_round_cap(synthetic, monkeypatch):
    """One to three checks, then it resolves. No grinding."""
    force_degree(monkeypatch, "partial")
    state = state_at()
    encounter.begin(state, "test_grind")

    rounds = 0
    while encounter.active(state) and rounds < 20:
        encounter.resolve_approach(state, "poke")
        rounds += 1
    assert rounds == 3
    assert not encounter.active(state)


def test_the_scene_log_records_every_round(synthetic, monkeypatch):
    force_degree(monkeypatch, "partial")
    state = state_at()
    encounter.begin(state, "test_scene")
    first = encounter.resolve_approach(state, "talk")
    assert first["resolved"] is False
    assert len(first["encounter"]["log"]) == 1
    second = encounter.resolve_approach(state, "talk")
    assert len(second["encounter"]["log"]) == 2


def test_begin_on_an_unknown_id_leaves_the_state_idle():
    state = state_at()
    assert encounter.begin(state, "no_such_encounter") == {}
    assert not encounter.active(state)


def test_end_is_idempotent(synthetic):
    state = state_at()
    encounter.begin(state, "test_scene")
    encounter.end(state)
    encounter.end(state)
    assert state.encounter == {}


# ---------------------------------------------------------------------------
# death
# ---------------------------------------------------------------------------


def test_death_respawns_rather_than_hanging(synthetic, monkeypatch):
    force_degree(monkeypatch, "failure")
    state = state_at(day=4)
    state.stats.gold = 20
    state.location_id = "millhaven_gate"
    encounter.begin(state, "test_lethal")
    result = encounter.resolve_approach(state, "die")

    death = result["death"]
    assert death is not None and death["died"] is True
    assert death["terminal"] is False
    assert state.ended is False, "death is a setback, not a game over"
    assert state.location_id == "edgewood_square"
    assert state.stats.hp > 0, "a respawn at zero hp is a hang"
    assert state.stats.gold < 20
    assert state.wounds, "you do not walk away from that clean"
    assert state.encounter == {}, "the scene cannot survive being carried out of it"


def test_death_costs_hours_the_evil_keeps(synthetic, monkeypatch):
    force_degree(monkeypatch, "failure")
    state = state_at(day=4, hour=6)
    before_hours = state.world_clock_hours
    before_evil = state.evil_progress
    encounter.begin(state, "test_lethal")
    encounter.resolve_approach(state, "die")
    assert state.world_clock_hours > before_hours
    assert state.evil_progress > before_evil


def test_awareness_is_untouched_by_death(synthetic, monkeypatch):
    force_degree(monkeypatch, "failure")
    state = state_at(day=4)
    state.awareness = 33.0
    encounter.begin(state, "test_lethal")
    encounter.resolve_approach(state, "die")
    assert state.awareness == 33.0


def test_terminal_death_only_after_a_marked_death_while_consuming(synthetic, monkeypatch):
    # hp is pinned high so an incidental starvation death cannot add its
    # own wound or respawn the player part-way through the assertion.
    force_degree(monkeypatch, "failure")
    state = state_at(day=4, evil_progress=0.99)
    # Same reason: an incidental starvation death here would consume the one
    # non-terminal death this test is counting.
    state.hunger = 0.0
    assert state.evil_phase.value == "consuming"

    encounter.begin(state, "test_lethal")
    first = encounter.resolve_approach(state, "die")
    assert first["death"]["terminal"] is False
    assert state.ended is False
    assert state.flags.get("saints_marked_you") is True

    encounter.begin(state, "test_lethal")
    second = encounter.resolve_approach(state, "die")
    assert second["death"]["terminal"] is True
    assert state.ended is True


def test_a_survivable_round_reports_no_death(synthetic, monkeypatch):
    force_degree(monkeypatch, "success")
    state = state_at()
    encounter.begin(state, "test_scene")
    assert encounter.resolve_approach(state, "talk")["death"] is None


# ---------------------------------------------------------------------------
# travel hook and persistence
# ---------------------------------------------------------------------------


def test_move_to_carries_an_encounter_on_the_result(synthetic, monkeypatch):
    monkeypatch.setattr(
        encounter, "trigger_chance", lambda *a, **k: 1.0
    )  # force the road to bite
    eng = GameEngine(state_at())
    result = eng.move_to("edgewood_square")

    assert result.success is True, "travel completes regardless"
    assert result.encounter.get("id") == "test_scene"
    assert eng.state.location_id == "edgewood_square"
    assert eng.state.encounter["id"] == "test_scene"
    assert result.to_dict()["encounter"]["id"] == "test_scene"


def test_move_to_is_quiet_when_nothing_triggers(synthetic, monkeypatch):
    monkeypatch.setattr(encounter, "trigger_chance", lambda *a, **k: 0.0)
    eng = GameEngine(state_at())
    result = eng.move_to("edgewood_square")
    assert result.encounter == {}
    assert result.to_dict()["encounter"] == {}


def test_travel_does_not_overwrite_an_open_scene(synthetic, monkeypatch):
    monkeypatch.setattr(encounter, "trigger_chance", lambda *a, **k: 1.0)
    eng = GameEngine(state_at())
    eng.state.location_id = "edgewood_square"
    encounter.begin(eng.state, "test_grind")
    eng.move_to("forest_clearing")
    assert eng.state.encounter["id"] == "test_grind"


def test_an_encounter_round_trips_through_the_save(synthetic, monkeypatch):
    force_degree(monkeypatch, "partial")
    state = state_at()
    encounter.begin(state, "test_scene")
    encounter.resolve_approach(state, "talk")

    restored = GameState.from_dict(state.to_save_dict())
    assert restored.encounter == state.encounter
    assert restored.encounter["log"][0]["text"] == "MIXED"
    assert encounter.active(restored)
    assert {a["id"] for a in encounter.available_approaches(restored)} == {
        a["id"] for a in encounter.available_approaches(state)
    }


def test_the_client_payload_ships_the_scene(synthetic):
    state = state_at()
    encounter.begin(state, "test_scene")
    assert state.to_client_dict()["encounter"]["id"] == "test_scene"


# ---------------------------------------------------------------------------
# skills
# ---------------------------------------------------------------------------


def test_encounter_skills_are_registered():
    names = {s.name for s in SKILL_REGISTRY.all_tools()}
    assert {"query_encounter", "encounter_approach", "flee"} <= names


def test_query_encounter_skill_reports_the_scene(synthetic, engine):
    import json

    encounter.begin(engine.state, "test_scene")
    payload = json.loads(SKILL_REGISTRY.invoke("query_encounter"))
    assert payload["active"] is True
    assert payload["encounter"]["id"] == "test_scene"
    assert "flee" in {a["id"] for a in payload["approaches"]}


def test_encounter_approach_skill_resolves(synthetic, monkeypatch, engine):
    import json

    force_degree(monkeypatch, "success")
    encounter.begin(engine.state, "test_scene")
    payload = json.loads(SKILL_REGISTRY.invoke("encounter_approach", approach="talk"))
    assert payload["ok"] is True
    assert payload["text"] == "WIN"


def test_flee_skill_always_works(synthetic, monkeypatch, engine):
    import json

    force_degree(monkeypatch, "failure")
    encounter.begin(engine.state, "test_scene")
    payload = json.loads(SKILL_REGISTRY.invoke("flee"))
    assert payload["ok"] is True
    assert payload["resolved"] is True
    assert not encounter.active(engine.state)


def test_skills_return_receipts_not_exceptions(engine):
    import json

    engine.state.encounter = {}
    payload = json.loads(SKILL_REGISTRY.invoke("encounter_approach", approach="nonsense"))
    assert payload["ok"] is False


# ---------------------------------------------------------------------------
# shipped content
# ---------------------------------------------------------------------------


def test_the_table_is_stocked():
    rows = encounter.all_encounters()
    assert len(rows) >= 30, f"only {len(rows)} encounters"
    ids = [r["id"] for r in rows]
    assert len(ids) == len(set(ids)), "duplicate encounter ids"
    assert {"forest", "road", "village", "marches"} <= {r["band"] for r in rows}


def test_most_encounters_are_not_monsters():
    """
    The pillar. Ordinary work continuing is the horror; a monster every trip is
    just a bestiary.
    """
    rows = encounter.all_encounters()
    with_art = [r for r in rows if r.get("art")]
    assert len(with_art) / len(rows) < 0.4, "too many encounters are creatures"


def test_clockwork_is_reserved_for_the_late_phases():
    clockwork = {"clockwork_scarecrow", "clockwork_thing", "clockwork_soldier"}
    for row in encounter.all_encounters():
        if row.get("art") in clockwork:
            phases = set(row.get("triggers", {}).get("phases") or [])
            assert phases and phases <= {"spreading", "consuming"}, row["id"]


def test_every_art_key_exists_in_the_manifest():
    from engine.config import get_config

    path = encounter._ROOT / str(get_config().get("paths.art_manifest", "games/clockwork-dark/data/art/manifest.yaml"))
    with path.open(encoding="utf-8") as fh:
        enemies = set((yaml.safe_load(fh) or {}).get("enemies", {}))

    for row in encounter.all_encounters():
        art = row.get("art")
        if art:
            assert art in enemies, f"{row['id']} points at missing art '{art}'"


def test_every_skill_and_band_is_one_the_engine_knows():
    rules = checks.load_skill_rules()
    taxonomy = set(rules.get("skills", {}))
    bands = set(rules.get("difficulty", {}))

    specs = [encounter.load_encounters().get("default_approaches") or {}]
    specs.extend(row.get("approaches") or {} for row in encounter.all_encounters())

    for group in specs:
        for name, spec in group.items():
            if spec.get("auto"):
                continue
            assert spec.get("skill") in taxonomy, f"{name}: {spec.get('skill')}"
            assert spec.get("difficulty") in bands, f"{name}: {spec.get('difficulty')}"


def test_every_effect_is_one_the_dispatcher_implements():
    def walk(block, where):
        for effect in block.get("effects") or []:
            kind = effect.get("type")
            assert kind in KNOWN_EFFECT_TYPES, f"{where}: unknown effect '{kind}'"
            if kind == "reputation":
                assert effect.get("faction") in KNOWN_FACTIONS, where

    for row in encounter.all_encounters():
        for degree, block in (row.get("outcomes") or {}).items():
            assert degree in KNOWN_DEGREES, f"{row['id']}: bad degree '{degree}'"
            walk(block, f"{row['id']}/{degree}")
        for name, spec in (row.get("approaches") or {}).items():
            for degree, block in (spec.get("outcomes") or {}).items():
                assert degree in KNOWN_DEGREES, f"{row['id']}/{name}: bad degree"
                walk(block, f"{row['id']}/{name}/{degree}")


def test_every_trigger_key_is_understood():
    for row in encounter.all_encounters():
        unknown = set(row.get("triggers", {})) - KNOWN_TRIGGER_KEYS
        assert not unknown, f"{row['id']}: unknown trigger keys {unknown}"


def test_every_declared_edge_exists_in_the_graph():
    for row in encounter.all_encounters():
        triggers = row.get("triggers", {})
        for edge in triggers.get("edges") or []:
            src, _, dst = str(edge).partition(">")
            assert get_edge(src, dst) is not None, f"{row['id']}: dead edge {edge}"
        for location in (triggers.get("to") or []) + (triggers.get("from") or []):
            assert location in LOCATIONS, f"{row['id']}: unknown location {location}"


def test_every_encounter_has_intro_threat_and_outcomes():
    for row in encounter.all_encounters():
        assert row.get("intro"), row["id"]
        assert (row.get("threat") or {}).get("name"), row["id"]
        assert row.get("approaches"), row["id"]
        outcomes = set(row.get("outcomes") or {})
        assert {"success", "failure"} <= outcomes, row["id"]


def test_every_edge_in_the_graph_with_danger_has_content():
    """A dangerous edge with an empty table is a roll that can never pay off."""
    state = state_at(day=6, hour=21, evil_progress=0.5)
    for src, spec in LOCATIONS.items():
        for dst, edge in (spec.get("connections") or {}).items():
            if int(edge.get("danger_dc", 0)) <= 0:
                continue
            assert encounter.eligible(state, src, dst), f"{src}>{dst} has no content"


def test_death_rules_load():
    rules = encounter.load_death_rules()
    assert rules.get("respawn", {}).get("location_id") in LOCATIONS
    assert rules.get("terminal", {}).get("flag")
