"""
Agendas, part two: moves on the clock.

THE PASS. ``agendas.advance(state, hours)`` runs inside ``clock.advance_time``
after ``jobs.tick``. It walks every whole-hour boundary from
``state.agendas["last_hour"]`` to now, at most 48 per call as the Law does.
At each boundary it visits the agendas in sorted order and each agenda's
moves in declared order. A move fires when all of these hold:

* its cadence has elapsed, or it has never fired and ``start_hour`` has passed;
* its ``at_hours``, if it has any, include the hour of day;
* its ``when`` holds;
* its ``select`` finds a target.

When a move fires:

* its effects are applied, with the target placeholders substituted;
* its clock moves through ``value``;
* a robbery is recorded through ``agenda_hit``;
* its trace is written through ``agenda_trace`` (a public trace also goes to
  the moved journal);
* it is stamped through ``agenda_mark``.

A move that finds no target neither fires nor stamps.

WHAT THESE TESTS HOLD:

* cadence, ``at_hours`` and ``when`` are honoured;
* a house robbed by the player or by an agenda is never picked again under
  ``not_robbed``;
* a Magpie report against the ``magpie`` guise raises the linked ``self``
  band, which proves moves reach the Law;
* traces are recorded, and public ones are journalled;
* twelve 1h calls equal one 12h call, compared on the whole of
  ``state.agendas``, ``state.law`` and the clock values;
* a seed replays;
* the wall-clock tick moves nothing during a job;
* the flagship and a synthetic Law+jobs story with no agendas are
  byte-identical with every agenda hook forced to raise.

The Task 2 loader rulings are held here too.

Version: v0.1.0 [2026-09-25]
"""

from __future__ import annotations

import copy
import json
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import pytest

from engine.config import set_overlay
from engine.game import clocks, intents, moved
from engine.game.clock import advance_time, set_clock
from engine.game.effects import apply_effect
from engine.game.procgen import generate_world
from engine.game.rng import AGENDA
from engine.game.state import GameState
from engine.state import active as active_state
from engine.state.schema import parse_schema
from engine.world import agendas, jobs, law, premises

from test_agendas import CANDIDATES, SCHEDULES, _dump, _paths
from test_jobs import _rob
from test_premises import DISTRICTS

SQUARE = "edgewood_square"
MARKET = "millhaven_market"

CLOCKS_TABLE: dict[str, Any] = {
    "clocks": {
        "magpie_spree": {
            "label": "How close the Magpie is to the heart of the city",
            "beats": [{"id": "spree_begun", "at": 1, "set_flags": ["spree_begun"]}],
        },
        "crier_round": {"label": "How far the crier has walked"},
    }
}

STATE_YAML: dict[str, Any] = {
    "clocks": {
        "magpie_spree": {"min": 0, "max": 6, "visibility": "hidden"},
        "crier_round": {"min": 0, "max": 99, "visibility": "hidden"},
    }
}

LIFT: dict[str, Any] = {
    "id": "lift",
    "every_hours": 24,
    "at_hours": [1, 2, 3],
    "when": {"none": [{"flag": "magpie_caught"}]},
    "select": {"premise": {"tier_min": 2, "not_robbed": True, "loot_tag": "trade"}},
    "effects": [{"type": "report", "deed": "burglary", "guise": "magpie",
                 "jurisdiction": "{target_jurisdiction}", "precision": 1.0}],
    "advance": 1,
    "robs": True,
    "trace": {"text": "a black feather on the sill of {target_name}",
              "where": "target", "public": False},
}

CRY: dict[str, Any] = {
    "id": "cry",
    "every_hours": 6,
    "start_hour": 10,
    "advance": 1,
    "trace": {"text": "the crier calls the hour", "where": SQUARE, "public": True},
}

MOVES_SPEC: dict[str, Any] = {
    "roles": {"magpie": {"from": list(CANDIDATES)}},
    "agendas": {
        "the_magpie": {"owner": {"role": "magpie"}, "goal": "shine",
                       "clock": "magpie_spree", "moves": [LIFT]},
        "the_crier": {"owner": "npc_ardane", "goal": "keep the hours",
                      "clock": "crier_round", "moves": [CRY]},
    },
}


def _doc(**agendas_: Any) -> dict[str, Any]:
    """A contract holding exactly the given agendas (name -> list of moves)."""
    doc = copy.deepcopy(MOVES_SPEC)
    doc["agendas"] = {}
    for name, moves in agendas_.items():
        doc["agendas"][name] = {"owner": "npc_ardane", "goal": "g",
                                "clock": "magpie_spree", "moves": moves}
    return doc


@contextmanager
def story(tmp_path: Path, doc: Any = None, *, clocks_table: Any = None,
          state_yaml: Any = None, **kwargs: Any) -> Iterator[None]:
    paths = _paths(tmp_path, MOVES_SPEC if doc is None else doc, **kwargs)
    paths["clocks"] = _dump(tmp_path / "clocks.yaml", clocks_table or CLOCKS_TABLE)
    set_overlay({"paths": paths})
    active_state._schema = parse_schema(state_yaml or STATE_YAML, slug="synthetic")
    try:
        yield
    finally:
        active_state.reset_schema()
        set_overlay(None)


@pytest.fixture()
def declared(tmp_path: Path) -> Iterator[Path]:
    with story(tmp_path, with_jobs=True):
        yield tmp_path


def _world(seed: int = 42, *, day: int = 1, hour: int = 8) -> GameState:
    state = GameState(rng_seed=seed, location_id=SQUARE)
    state.procgen = generate_world(seed)
    set_clock(state, day=day, hour=hour)
    return state


def _fired(receipts: list[dict[str, Any]], key: str) -> list[int]:
    return [r["hour"] for r in receipts
            if r.get("move") and f"{r['agenda']}:{r['move']}" == key]


def _run(state: GameState, hours: float) -> list[dict[str, Any]]:
    """Advance through the real clock, capturing the pass's receipts."""
    captured: list[dict[str, Any]] = []
    real = agendas.Walk.finish

    def spy(walk: agendas.Walk) -> list[dict[str, Any]]:
        out = real(walk)
        captured.extend(out)
        return out

    agendas.Walk.finish = spy  # type: ignore[method-assign]
    try:
        advance_time(state, hours)
    finally:
        agendas.Walk.finish = real  # type: ignore[method-assign]
    return captured


# ---------------------------------------------------------------------------
# The walk
# ---------------------------------------------------------------------------


def test_the_pass_is_wired_into_advance_time(declared: Path) -> None:
    state = _world()
    advance_time(state, 3)
    assert state.agendas["last_hour"] == 11
    # The crier's first eligible hour is 10.
    assert state.agendas["moves"]["the_crier:cry"] == 10


def test_a_move_fires_on_cadence_and_not_before(declared: Path) -> None:
    state = _world()
    assert _fired(_run(state, 1), "the_crier:cry") == []  # 9: before start_hour
    assert _fired(_run(state, 1), "the_crier:cry") == [10]
    assert _fired(_run(state, 5), "the_crier:cry") == []  # 11..15
    assert _fired(_run(state, 1), "the_crier:cry") == [16]
    assert _fired(_run(state, 12), "the_crier:cry") == [22, 28]


def test_at_hours_is_honoured(declared: Path) -> None:
    state = _world()
    # From 08:00, the first hour of day inside [1, 2, 3] is 01:00 on day 2.
    assert _fired(_run(state, 16), "the_magpie:lift") == []
    assert _fired(_run(state, 1), "the_magpie:lift") == [25]
    # Cadence 24: not again at 02:00 or 03:00, and next at 01:00 on day 3.
    assert _fired(_run(state, 23), "the_magpie:lift") == []
    assert _fired(_run(state, 1), "the_magpie:lift") == [49]


def test_when_gates_and_a_gated_move_does_not_stamp(declared: Path) -> None:
    state = _world(hour=20)
    assert apply_effect(state, {"type": "flag", "flag": "magpie_caught"})["ok"]
    assert _fired(_run(state, 12), "the_magpie:lift") == []
    assert "the_magpie:lift" not in state.agendas.get("moves", {})
    assert apply_effect(state, {"type": "flag", "flag": "magpie_caught",
                                "value": False})["ok"]
    # Never fired, and its hour of day comes round again at 01:00 on day 3.
    assert _fired(_run(state, 18), "the_magpie:lift") == [49]


def test_the_first_advance_does_not_fire_the_past(declared: Path) -> None:
    """An old save loaded at day 21 walks only the hours this call crosses."""
    state = _world(day=21, hour=4)
    receipts = _run(state, 1)
    assert [r["hour"] for r in receipts] == [485]
    assert state.agendas["last_hour"] == 485


def test_a_zero_hour_advance_does_nothing(declared: Path) -> None:
    state = _world()
    advance_time(state, 0)
    assert state.agendas == {}


def test_a_long_sleep_walks_at_most_48_hours(declared: Path,
                                             monkeypatch: pytest.MonkeyPatch) -> None:
    from engine.game import encounter

    # Four days unfed would faint the player, and fainting costs hours through
    # a nested advance_time that the pass walks too. Held off, so the count is
    # of the one call (test_law_propagation's reason).
    monkeypatch.setattr(encounter, "check_death", lambda *_a, **_k: None)
    state = _world()
    receipts = _run(state, 100)
    crier = _fired(receipts, "the_crier:cry")
    assert crier and max(crier) <= 8 + law.MAX_PROPAGATION_HOURS
    # The walk is capped; the stamp is not, so nothing replays.
    assert state.agendas["last_hour"] == 108
    assert _fired(_run(state, 1), "the_crier:cry") == [109]


# ---------------------------------------------------------------------------
# Selectors and robbing
# ---------------------------------------------------------------------------

#: seed 42, tier >= 2, carrying a `trade` item, in id order.
TARGETS = ["prem_edgewood_square_2", "prem_mill_house", "prem_millhaven_market_1"]


def test_the_premise_selector_filters_and_sorts(declared: Path) -> None:
    state = _world()
    assert agendas.candidates(state, {"premise": {"tier_min": 2, "loot_tag": "trade"}}) \
        == TARGETS
    assert agendas.candidates(state, {"premise": {"district": MARKET, "tier_min": 2}}) \
        == ["prem_mill_house", "prem_millhaven_market_1"]
    assert agendas.candidates(state, {"premise": {"tier_max": 1, "district": SQUARE}}) \
        == ["prem_edgewood_square_1", "prem_edgewood_square_3"]
    assert agendas.candidates(state, {"premise": {"type": "mill_house"}}) == ["prem_mill_house"]
    owner = premises.owner(state, "prem_mill_house")
    assert agendas.candidates(state, {"premise": {"owner": owner}}) == ["prem_mill_house"]


def test_one_candidate_draws_nothing_and_several_draw_once(declared: Path) -> None:
    state = _world()
    assert agendas.select(state, {"premise": {"type": "mill_house"}}) == "prem_mill_house"
    assert state.rng_counters.get(AGENDA, 0) == 0
    assert agendas.select(state, {"premise": {"tier_min": 2}}) in TARGETS
    assert state.rng_counters[AGENDA] == 1
    assert agendas.select(state, {"premise": {"district": "forest_clearing"}}) is None
    assert state.rng_counters[AGENDA] == 1


def test_a_house_the_player_or_an_agenda_robbed_is_never_picked_again(
    declared: Path,
) -> None:
    state = _world(hour=20)
    _rob(state, TARGETS[0])
    _rob(state, TARGETS[2])
    receipts = _run(state, 6)  # to 02:00
    [hit] = [r for r in receipts if r["move"] == "lift"]
    assert hit["target"] == TARGETS[1]
    assert state.rng_counters.get(AGENDA, 0) == 0  # one candidate left
    assert state.agendas["hits"] == [{"agenda": "the_magpie", "premise": TARGETS[1],
                                      "hour": 25}]
    # The agenda's robbery is its own record: the player's list is untouched.
    assert jobs.robbed(state) == [TARGETS[0], TARGETS[2]]
    assert agendas.candidates(state, LIFT["select"]) == []
    # Nothing left: the next day's lift finds no target, so neither fires nor stamps.
    assert _fired(_run(state, 24), "the_magpie:lift") == []
    assert state.agendas["moves"]["the_magpie:lift"] == 25


def test_the_magpie_report_raises_the_linked_self_band(declared: Path) -> None:
    state = _world(hour=20)
    _rob(state, TARGETS[0])
    _rob(state, TARGETS[2])
    town = law.jurisdiction_at(MARKET)
    assert law.wanted_band(state, "self", town) == "unknown"
    [hit] = [r for r in _run(state, 6) if r["move"] == "lift"]
    assert hit["target"] == "prem_mill_house"
    [report] = state.law["reports"]
    assert report["guise"] == "magpie" and report["jurisdiction"] == town
    # burglary 3 x precision 1.0 reaches `noticed` (2), on YOUR face by the link.
    assert law.wanted_band(state, "self", town) == "noticed"
    assert law.wanted_band(state, "self", law.jurisdiction_at(SQUARE)) == "unknown"


def test_a_report_where_no_watch_reaches_is_refused_cleanly(tmp_path: Path) -> None:
    districts = copy.deepcopy(DISTRICTS)
    districts["forest_clearing"] = {"count": 1, "types": {"townhouse": 1}}
    lift = {**LIFT, "at_hours": [], "every_hours": 1,
            "select": {"premise": {"district": "forest_clearing"}}}
    with story(tmp_path, _doc(the_magpie=[lift]), **{"districts.yaml": districts}):
        state = _world()
        [fired] = _run(state, 1)
        [refused] = [e for e in fired["effects"] if e["type"] == "report"]
        assert refused["ok"] is False and refused["message"]
        assert not state.law.get("reports")
        assert state.agendas["hits"][0]["premise"] == "prem_forest_clearing_1"


def test_the_witness_selector_finds_a_live_holder(declared: Path) -> None:
    state = _world()
    watch = {"select": {"witness": {"knows": "magpie"}}}
    assert agendas.candidates(state, watch["select"]) == []
    row = apply_effect(state, {"type": "witness", "deed": "fencing", "guise": "self",
                               "npc": "npc_wren", "where": SQUARE})
    assert row["ok"], row
    # The watch takes you for the Magpie, so a sighting of your face counts.
    assert agendas.candidates(state, watch["select"]) == ["npc_wren"]
    assert agendas.candidates(state, {"witness": {"knows": "porter"}}) == []
    assert agendas.candidates(state, {"witness": {"knows": "magpie",
                                                  "jurisdiction": "town"}}) == []
    apply_effect(state, {"type": "law_discharge", "deed_ids": [row["deed_id"]]})
    assert agendas.candidates(state, watch["select"]) == []


def test_the_fence_selector_finds_a_fence(tmp_path: Path,
                                          monkeypatch: pytest.MonkeyPatch) -> None:
    from engine.game import trade

    real = trade.vendors()
    fake = {**real, "npc_brindle": {**real["npc_brindle"], "fence": True}}
    monkeypatch.setattr(trade, "vendors", lambda: copy.deepcopy(fake))
    move = {"id": "sell", "every_hours": 1, "select": {"fence": {"district": SQUARE}},
            "trace": {"text": "{target_name} has new stock", "where": "target"}}
    with story(tmp_path, _doc(the_magpie=[move])):
        state = _world()
        assert agendas.candidates(state, {"fence": {}}) == ["npc_brindle"]
        assert agendas.candidates(state, {"fence": {"district": MARKET}}) == []
        [fired] = _run(state, 1)
        assert fired["target"] == "npc_brindle"
        [trace] = state.agendas["traces"]
        assert trace["text"] == "Brindle has new stock" and trace["where"] == SQUARE


# ---------------------------------------------------------------------------
# Traces, clocks and effects
# ---------------------------------------------------------------------------


def test_a_trace_is_recorded_and_a_public_one_is_journalled(declared: Path) -> None:
    state = _world(hour=20)
    _rob(state, TARGETS[0])
    _rob(state, TARGETS[2])
    _run(state, 6)
    traces = state.agendas["traces"]
    lift = [t for t in traces if t["agenda"] == "the_magpie"]
    assert lift == [{"id": lift[0]["id"], "agenda": "the_magpie",
                     "text": "a black feather on the sill of the old mill house",
                     "where": MARKET, "hour": 25, "public": False, "seen": False}]
    assert [t["id"] for t in traces] == [f"t{i}" for i in range(1, len(traces) + 1)]
    assert state.agendas["trace_seq"] == len(traces)
    # A private sign stays in state; the crier's public one is common talk, at once.
    texts = [(e["kind"], e["text"], e["location_id"]) for e in state.moved]
    assert ("agenda", "the crier calls the hour", "") in texts
    assert not any("feather" in e["text"] for e in state.moved)
    assert "agenda" in moved.KINDS


def test_the_clock_advances_and_its_beat_fires_the_same_call(declared: Path) -> None:
    state = _world(hour=20)
    _run(state, 6)
    assert clocks.value_of(state, "magpie_spree") == 1
    assert clocks.value_of(state, "crier_round") == 1  # 22:00; 04:00 not yet reached
    # The beat at 1 fires inside the call whose move crossed it, not one call late.
    assert state.flags.get("spree_begun") is True


def test_placeholders_reach_the_effects(tmp_path: Path) -> None:
    move = {"id": "mark", "every_hours": 1, "select": {"premise": {"type": "mill_house"}},
            "effects": [{"type": "flag", "flag": "hit_{target}"},
                        {"type": "flag", "flag": "in_{target_district}_{target_jurisdiction}"},
                        {"type": "flag", "flag": "by_{owner}"}]}
    with story(tmp_path, _doc(the_magpie=[move])):
        state = _world()
        _run(state, 1)
        assert state.flags.get("hit_prem_mill_house") is True
        assert state.flags.get(f"in_{MARKET}_town") is True
        assert state.flags.get("by_npc_ardane") is True


@pytest.mark.parametrize("effect", [
    {"type": "agenda_hit", "agenda": "nobody", "premise": "prem_mill_house", "hour": 1},
    {"type": "agenda_hit", "agenda": "the_magpie", "premise": "prem_nowhere", "hour": 1},
    {"type": "agenda_hit", "agenda": "the_magpie", "premise": "prem_mill_house"},
    {"type": "agenda_trace", "agenda": "nobody", "text": "x", "where": SQUARE, "hour": 1},
    {"type": "agenda_trace", "agenda": "the_magpie", "text": " ", "where": SQUARE, "hour": 1},
    {"type": "agenda_trace", "agenda": "the_magpie", "text": "x", "where": SQUARE,
     "hour": "late"},
    {"type": "agenda_trace", "agenda": "the_magpie", "text": "x", "where": SQUARE,
     "hour": 1, "public": "yes"},
])
def test_the_new_effects_refuse_what_they_cannot_record(declared: Path,
                                                         effect: dict) -> None:
    state = _world()
    out = apply_effect(state, effect)
    assert out["ok"] is False and out["message"], out
    assert state.agendas == {}


def test_the_new_effects_refuse_in_a_story_without_agendas() -> None:
    state = GameState()
    for effect in ({"type": "agenda_hit", "agenda": "a", "premise": "p", "hour": 1},
                   {"type": "agenda_trace", "agenda": "a", "text": "x", "hour": 1}):
        out = apply_effect(state, effect)
        assert out["ok"] is False and out["message"]
    assert state.agendas == {}


# ---------------------------------------------------------------------------
# Cut-invariance, replay, and the wall-clock tick
# ---------------------------------------------------------------------------


def _clock_values(state: GameState) -> dict[str, float]:
    return {name: clocks.value_of(state, name) for name in ("magpie_spree", "crier_round")}


def test_twelve_one_hour_calls_equal_one_twelve_hour_call(declared: Path) -> None:
    stepped, whole = _world(hour=20), _world(hour=20)
    for _ in range(12):
        advance_time(stepped, 1)
    advance_time(whole, 12)
    assert state_hits(stepped), "the window must actually fire the lift"
    assert stepped.agendas == whole.agendas
    assert stepped.law == whole.law
    assert _clock_values(stepped) == _clock_values(whole)
    assert stepped.rng_counters == whole.rng_counters


def test_a_sighting_a_move_files_travels_the_same_either_way(tmp_path: Path) -> None:
    """
    A move that adds a witness row makes a teller mid-call. The Law's pass
    must pick it up in the hours after, as twelve short calls would.

    Within one day on purpose: a Law row's ``day`` is stamped with the day the
    CALL ends on, for the Law's own rows as for a move's (``agendas.Walk``),
    so a row filed before midnight in a call that ends after it reads the
    later day. Nothing reads that field; it is recorded, not engineered round.
    """
    whisper = {"id": "whisper", "every_hours": 100, "start_hour": 10,
               "effects": [{"type": "witness", "deed": "fencing", "guise": "magpie",
                            "npc": "npc_wren", "where": SQUARE}]}
    with story(tmp_path, _doc(the_magpie=[whisper])):
        stepped, whole = _world(hour=8), _world(hour=8)
        for _ in range(12):
            advance_time(stepped, 1)
        advance_time(whole, 12)
        assert len(stepped.law["witnessed"]) > 1, "the sighting must actually travel"
        assert stepped.law == whole.law
        assert stepped.rng_counters == whole.rng_counters


def test_a_beat_fires_at_the_end_of_its_hour_either_way(tmp_path: Path) -> None:
    """
    A beat an agenda crosses fires at the end of THAT hour, not of the call:
    its ``reset_to`` lands before the next hour winds the clock again, and the
    flag it sets opens the next hour's gate -- as across twelve 1h calls.
    """
    table = copy.deepcopy(CLOCKS_TABLE)
    table["clocks"]["tick_tock"] = {
        "label": "A clock that strikes and starts again",
        "beats": [{"id": "tock", "at": 2, "reset_to": 0, "set_flags": ["tocked"]}],
    }
    schema = copy.deepcopy(STATE_YAML)
    schema["clocks"]["tick_tock"] = {"min": 0, "max": 99, "visibility": "hidden"}
    doc = copy.deepcopy(MOVES_SPEC)
    doc["agendas"] = {"the_clock": {
        "owner": "npc_ardane", "goal": "keep time", "clock": "tick_tock",
        "moves": [{"id": "wind", "every_hours": 1, "advance": 1},
                  {"id": "answer", "every_hours": 1, "when": {"flag": "tocked"},
                   "trace": {"text": "a bell answers", "where": SQUARE}}],
    }}
    with story(tmp_path, doc, clocks_table=table, state_yaml=schema):
        stepped, whole = _world(), _world()
        for _ in range(12):
            advance_time(stepped, 1)
        advance_time(whole, 12)
        # Wound at 9 and 10, struck and reset at the end of 10, wound 11..20.
        assert clocks.value_of(stepped, "tick_tock") == 10
        assert stepped.agendas["moves"]["the_clock:answer"] == 20
        assert clocks.value_of(whole, "tick_tock") == clocks.value_of(stepped, "tick_tock")
        assert whole.agendas == stepped.agendas
        assert whole.flags.get("tocked") is stepped.flags.get("tocked") is True
        assert {k: v for k, v in whole.flags.items()} ==             {k: v for k, v in stepped.flags.items()}


def state_hits(state: GameState) -> list[dict[str, Any]]:
    return list(state.agendas.get("hits") or [])


def test_a_seed_replays(declared: Path) -> None:
    def play(seed: int) -> Any:
        state = _world(seed, hour=20)
        receipts = _run(state, 12) + _run(state, 30)
        return receipts, dict(state.rng_counters), copy.deepcopy(state.agendas)

    first, second = play(42), play(42)
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    # Three candidates on the first night: the draw really happened.
    assert first[1].get(AGENDA, 0) >= 1
    picks = {play(seed)[2]["hits"][0]["premise"] for seed in (42, 5, 9, 11, 13)}
    assert len(picks) > 1


def test_the_background_tick_moves_no_agenda_during_a_job(declared: Path) -> None:
    from engine.scenes.default_state import _background_tick

    state = _world(hour=20)
    advance_time(state, 1)
    before = copy.deepcopy(state.agendas)
    opened = apply_effect(state, {"type": "job_open", "premise": TARGETS[0],
                                  "stages": jobs.stages_for(state, TARGETS[0])})
    assert opened["ok"], opened
    state.last_sim_tick_at = time.time() - 3 * 3600.0  # three hours of reading
    assert _background_tick(state) == 0.0
    assert state.agendas == before


# ---------------------------------------------------------------------------
# Stories without agendas: byte-identical
# ---------------------------------------------------------------------------

NO_AGENDAS = ("clockwork-dark", "law-jobs")


@contextmanager
def no_agendas_story(kind: str, tmp_path: Path) -> Iterator[None]:
    from engine.games import registry

    if kind == "clockwork-dark":
        registry.activate(kind)
        try:
            yield
        finally:
            registry.deactivate()
        return
    set_overlay({"paths": _paths(tmp_path, with_agendas=False, with_jobs=True)})
    try:
        assert law.declared() and jobs.declared()
        yield
    finally:
        set_overlay(None)


def _surface(state: GameState) -> tuple[Any, str, dict[str, Any]]:
    from engine.agents import prompts

    return (intents.legal_intents(state), prompts.world_state_block(state, {}),
            state.to_client_dict())


@pytest.mark.parametrize("kind", NO_AGENDAS)
def test_a_story_without_agendas_is_unchanged(
    kind: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with no_agendas_story(kind, tmp_path):
        assert not agendas.declared()
        state = GameState(rng_seed=42, location_id=SQUARE)
        state.procgen = generate_world(42)
        set_clock(state, day=1, hour=20)
        twin = copy.deepcopy(state)
        before = _surface(state)
        advance_time(state, 12)
        after = _surface(state)
        saved = state.to_save_dict()

        def boom(*args: Any, **kwargs: Any) -> None:
            raise AssertionError("an agenda hook ran in a story without agendas")

        for name in ("begin", "advance", "select", "candidates", "spec", "_try_reaction"):
            monkeypatch.setattr(agendas, name, boom)
        assert _surface(twin) == before
        advance_time(twin, 12)
        assert _surface(twin) == after
        assert saved["agendas"] == {}
        assert twin.to_save_dict() == saved


# ---------------------------------------------------------------------------
# Loader rulings
# ---------------------------------------------------------------------------


def _fails(tmp_path: Path, doc: Any, needle: str = "", **kwargs: Any) -> str:
    paths_file = str(tmp_path / "agendas.yaml")
    with story(tmp_path, doc, **kwargs):
        with pytest.raises(ValueError) as caught:
            agendas.spec()
    message = str(caught.value)
    assert paths_file in message, message
    assert needle in message.replace(paths_file, ""), message
    return message


@pytest.mark.parametrize("predicate", ["days_in_stage", "days_since_started"])
def test_a_quest_progress_predicate_is_refused(tmp_path: Path, predicate: str) -> None:
    move = {**CRY, "when": {predicate: 2}}
    _fails(tmp_path, _doc(the_crier=[move]), "quest")


MALFORMED: dict[str, dict[str, Any]] = {
    "agenda_hit naming an undeclared agenda": {"agenda_hit": {"agenda": "the_phantom"}},
    "agenda_hit naming an anchor that does not exist": {
        "agenda_hit": {"premise": "prem_castle"}},
    "agenda_hit naming a generated premise past the count": {
        "agenda_hit": {"premise": "prem_edgewood_square_9"}},
    "agenda_hit whose premise is not a string": {"agenda_hit": {"premise": 3}},
    "agenda_hit naming an unknown district": {"agenda_hit": {"district": "atlantis"}},
    "wanted on an unknown guise": {"wanted": {"min": "noticed", "guise": "phantom"}},
    "wanted in an unknown jurisdiction": {"wanted": {"min": "noticed",
                                                     "jurisdiction": "atlantis"}},
    "reported_to on an unknown guise": {"reported_to": {"npc": "npc_ardane",
                                                        "guise": "phantom"}},
    "filed with no jurisdiction": {"filed": {"guise": "self"}},
    "filed in an unknown jurisdiction": {"filed": {"jurisdiction": "atlantis"}},
    "filed on an unknown guise": {"filed": {"jurisdiction": "village", "guise": "phantom"}},
}


@pytest.mark.parametrize("fault", sorted(MALFORMED))
def test_a_malformed_gate_fails_naming_the_file(tmp_path: Path, fault: str) -> None:
    move = {**CRY, "when": MALFORMED[fault]}
    _fails(tmp_path, _doc(the_crier=[move]))


def test_agenda_hit_on_a_real_premise_loads(tmp_path: Path) -> None:
    move = {**CRY, "when": {"any": [{"agenda_hit": {"premise": "prem_mill_house"}},
                                    {"agenda_hit": {"premise": "prem_edgewood_square_3",
                                                    "agenda": "the_crier"}}]}}
    with story(tmp_path, _doc(the_crier=[move])):
        assert agendas.spec()


@pytest.mark.parametrize("kind", ["agenda_mark", "agenda_hit", "agenda_trace"])
def test_bookkeeping_effects_are_not_authorable(tmp_path: Path, kind: str) -> None:
    move = {**CRY, "effects": [{"type": kind}]}
    _fails(tmp_path, _doc(the_crier=[move]), "bookkeeping")


@pytest.mark.parametrize("kind", ["report", "witness", "quash_reports"])
def test_a_law_effect_needs_a_law(tmp_path: Path, kind: str) -> None:
    move = {**CRY, "effects": [{"type": kind}]}
    _fails(tmp_path, _doc(the_crier=[move]), "`paths.law`", lawful=False)


def test_a_move_in_a_lawless_story_never_files_a_report(tmp_path: Path) -> None:
    lift = {**LIFT, "effects": []}
    with story(tmp_path, _doc(the_magpie=[lift]), lawful=False, with_jobs=True):
        state = _world(hour=20)
        receipts = _run(state, 12)
        assert _fired(receipts, "the_magpie:lift") == [25]
        assert not state.law.get("reports")


@pytest.mark.parametrize("move", [
    {**CRY, "effects": [{"type": "flag", "flag": "x_{target}"}]},       # no select
    {**CRY, "effects": [{"type": "flag", "flag": "x_{nonsense}"}]},     # unknown
    {**CRY, "trace": {"text": "near {owner}", "where": SQUARE}},        # ids in prose
    {**CRY, "trace": {"text": "at {target_name}", "where": SQUARE}},    # no select
])
def test_a_placeholder_that_cannot_be_filled_fails(tmp_path: Path, move: dict) -> None:
    _fails(tmp_path, _doc(the_crier=[move]), "placeholder")
