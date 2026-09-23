"""
Thievery: lifting a purse, and the memory the goods carry afterwards.

THE SHAPE. ``lift <mark>`` rolls stealth against the mark's role's alertness.
A success draws one row of that role's purse on the THIEVERY stream -- coin
through the ``gold`` effect, an item through the ``item`` effect carrying
``stolen_from``, which appends ``{whom, where, day}`` to ``state.provenance``.
A partial takes coin only, halved. A failure takes nothing and says the mark
noticed. ``heat`` reads provenance: hot for ``hot_days``, then cool, and hot
for ever while the item is ``named``.

WHAT THESE TESTS HOLD. The receipt reports the attempt under ``ok`` and how it
went under ``success`` (the v0.8 ``work`` lesson); refusals roll nothing; the
verb offers only present, awake people outside houses; a seed replays; the
narrator's sentence has no ids or numbers; and the flagship, which declares no
thievery, sees no verb and an unchanged prompt.

Version: v0.1.0 [2026-09-23]
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator

import pytest
import yaml

from engine.config import set_overlay
from engine.game import checks
from engine.game.clock import advance_time, set_clock
from engine.game.effects import apply_effect
from engine.game.procgen import generate_world
from engine.game.state import GameState
from engine.world import npc_sim, thievery

SQUARE = "edgewood_square"
ALL_DAY = [{"hours": list(range(24)), "location": SQUARE, "activity": "idling"}]
ASLEEP = [{"hours": list(range(24)), "location": SQUARE, "activity": "dozing", "available": False}]
AWAY = [{"hours": list(range(24)), "location": "forest_clearing", "activity": "walking"}]

SPEC = {
    "alertness": {"default": "standard", "steward": "hard", "cook": "easy"},
    "purses": {
        "default": [{"gold": [2, 4], "weight": 1}],
        "steward": [{"item_id": "golden_ring", "weight": 1}],
        "cook": [{"gold": [9, 9], "weight": 1}],
    },
    "hot_days": 7,
}


def _write(tmp_path: Path, doc: dict[str, Any]) -> Path:
    path = tmp_path / "thievery.yaml"
    path.write_text(yaml.safe_dump(doc), encoding="utf-8")
    return path


@pytest.fixture()
def declared(tmp_path: Path) -> Iterator[Path]:
    path = _write(tmp_path, SPEC)
    set_overlay({"paths": {"thievery": str(path)}})
    try:
        yield path
    finally:
        set_overlay(None)


def _person(npc_id: str, role: str, routine: list[dict[str, Any]]) -> dict[str, Any]:
    return {"id": npc_id, "name": npc_id.replace("_", " ").title(), "role": role, "routine": routine}


def _world(seed: int = 42) -> GameState:
    state = GameState(rng_seed=seed, location_id=SQUARE)
    state.procgen = generate_world(seed)
    state.procgen.npcs = [
        _person("gen_t_steward", "steward", ALL_DAY),
        _person("gen_t_cook", "cook", ALL_DAY),
        _person("gen_t_plain", "labourer", ALL_DAY),
        _person("gen_t_sleeper", "labourer", ASLEEP),
        _person("gen_t_away", "labourer", AWAY),
    ]
    set_clock(state, day=1, hour=12)
    return state


class _Rigged:
    """A check result with a chosen degree -- the purse, not the dice, is under test."""

    def __init__(self, degree: str) -> None:
        self.degree = degree

    def to_dict(self) -> dict[str, Any]:
        return {"degree": self.degree}


def _rig(monkeypatch: pytest.MonkeyPatch, degree: str) -> list[tuple[str, str]]:
    calls: list[tuple[str, str]] = []

    def fake(state: GameState, skill: str, difficulty: str = "standard", **_: Any) -> _Rigged:
        calls.append((skill, difficulty))
        return _Rigged(degree)

    monkeypatch.setattr(checks, "resolve", fake)
    return calls


def _verbs(state: GameState) -> dict[str, tuple[tuple[str, str], ...]]:
    from engine.game.intents import legal_intents

    return {v.action: v.options for v in legal_intents(state)}


# -- the lift itself ----------------------------------------------------------


def test_a_success_takes_the_item_and_records_provenance(
    declared: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _rig(monkeypatch, "success")
    state = _world()
    set_clock(state, day=3, hour=12)
    before = state.world_clock_hours
    out = thievery.lift(state, "gen_t_steward")
    assert out["ok"] is True and out["success"] is True and out["noticed"] is False
    assert calls == [("stealth", "hard")]
    assert out["item_id"] == "golden_ring"
    assert any(i.id == "golden_ring" for i in state.inventory)
    assert state.provenance["golden_ring"] == [
        {"whom": "gen_t_steward", "where": SQUARE, "day": 3}
    ]
    # A lift is a moment.
    assert state.world_clock_hours == before


def test_a_success_takes_the_rolled_gold(declared: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _rig(monkeypatch, "crit_success")
    state = _world()
    gold = state.stats.gold
    out = thievery.lift(state, "gen_t_cook")
    assert out["gold"] == 9
    assert state.stats.gold == gold + 9
    # Coin carries no provenance: nobody recognises a penny.
    assert state.provenance == {}


def test_a_partial_takes_half_the_coin_and_never_the_item(
    declared: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _rig(monkeypatch, "partial")
    state = _world()
    gold = state.stats.gold
    out = thievery.lift(state, "gen_t_cook")
    assert out["ok"] is True and out["success"] is True
    assert out["gold"] == 4
    assert state.stats.gold == gold + 4
    # The steward's purse is only a ring: a partial there takes nothing.
    out = thievery.lift(state, "gen_t_steward")
    assert out["ok"] is True and out["success"] is False and out["gold"] == 0
    assert not any(i.id == "golden_ring" for i in state.inventory)


def test_a_failure_takes_nothing_and_the_mark_noticed(
    declared: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _rig(monkeypatch, "failure")
    state = _world()
    gold = state.stats.gold
    out = thievery.lift(state, "gen_t_steward")
    # It HAPPENED: `ok` stays true, so it is narrated as a caught hand rather
    # than as nothing at all.
    assert out["ok"] is True
    assert out["success"] is False and out["noticed"] is True
    assert state.stats.gold == gold and state.inventory == [] and state.provenance == {}
    # Nothing was drawn from the purse: a caught hand never reaches the pocket.
    assert "thievery" not in state.rng_counters


@pytest.mark.parametrize("npc_id", ["gen_t_away", "gen_t_sleeper", "nobody_at_all"])
def test_a_lift_refuses_the_absent_and_the_asleep(
    declared: Path, monkeypatch: pytest.MonkeyPatch, npc_id: str
) -> None:
    calls = _rig(monkeypatch, "success")
    state = _world()
    out = thievery.lift(state, npc_id)
    assert out["ok"] is False and out["message"]
    assert calls == []


def test_a_lift_refuses_inside_a_house(declared: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _rig(monkeypatch, "success")
    state = _world()
    inside = npc_sim.interior_id(SQUARE, "prem_x_1")
    state.procgen.npcs.append(
        _person("gen_t_inside", "labourer", [{"hours": list(range(24)), "location": inside}])
    )
    state.location_id = inside
    out = thievery.lift(state, "gen_t_inside")
    assert out["ok"] is False and calls == []


def test_a_lift_refuses_without_the_file(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _rig(monkeypatch, "success")
    out = thievery.lift(_world(), "gen_t_cook")
    assert out["ok"] is False and calls == []


def test_a_seed_replays(declared: Path) -> None:
    def run() -> list[dict[str, Any]]:
        state = _world(seed=7)
        rows = []
        for npc in ("gen_t_cook", "gen_t_plain", "gen_t_steward"):
            out = thievery.lift(state, npc)
            rows.append({k: out[k] for k in ("degree", "gold", "item_id", "noticed")})
        # Same mark again the next day: the daily limit has cleared, so this
        # is a fresh attempt rather than a refusal -- and still replays.
        advance_time(state, 24)
        out = thievery.lift(state, "gen_t_plain")
        rows.append({k: out[k] for k in ("degree", "gold", "item_id", "noticed")})
        rows.append({"gold": state.stats.gold, "prov": dict(state.provenance)})
        return rows

    assert run() == run()


# -- crowd ordering -----------------------------------------------------------


def test_the_named_cast_survives_a_crowd_over_the_option_cap(
    tmp_path: Path, declared: Path
) -> None:
    """
    Thirteen marks (3 scheduled, 10 generated) over `intents._MAX_OPTIONS`
    (8): before the fix, `marks()` returned `known_npc_ids` order, which lists
    every procgen NPC ahead of the schedule, so the cast was truncated out of
    both `thievery.marks` and the `lift` verb's options while PEOPLE HERE
    still named them -- a player could see Cast 0 standing right there and
    not be offered a lift on them.
    """
    from engine.game.intents import legal_intents

    schedule_doc = {
        "npcs": {
            f"npc_cast_{i}": {
                "home": SQUARE,
                "role": "default",
                "name": f"Cast {i}",
                "routine": [
                    {"hours": list(range(24)), "location": SQUARE, "activity": "keeping watch"}
                ],
            }
            for i in range(3)
        }
    }
    schedule_path = tmp_path / "npc_schedules.yaml"
    schedule_path.write_text(yaml.safe_dump(schedule_doc), encoding="utf-8")
    set_overlay(
        {"paths": {"thievery": str(declared), "npc_schedules": str(schedule_path)}}
    )
    npc_sim.reset_schedule_cache()
    try:
        state = GameState(rng_seed=1, location_id=SQUARE)
        state.procgen = generate_world(1)
        state.procgen.npcs = [_person(f"gen_t_{i}", "labourer", ALL_DAY) for i in range(10)]
        set_clock(state, day=1, hour=12)

        marks = thievery.marks(state)
        assert len(marks) == 13
        scheduled_ids = {f"npc_cast_{i}" for i in range(3)}
        assert {m.npc_id for m in marks[:3]} == scheduled_ids, (
            "scheduled cast must sort ahead of the generated crowd"
        )

        lift_options = next(v.options for v in legal_intents(state) if v.action == "lift")
        offered = {t for t, _ in lift_options}
        assert scheduled_ids <= offered, "the cast fell out of the capped lift options"
        assert len(lift_options) == 8  # _MAX_OPTIONS
    finally:
        set_overlay(None)
        npc_sim.reset_schedule_cache()


# -- the daily limit ----------------------------------------------------------


def test_a_lifted_mark_is_not_offered_again_the_same_day(
    declared: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from engine.game.intents import legal_intents

    _rig(monkeypatch, "success")
    state = _world()
    assert "gen_t_steward" in {m.npc_id for m in thievery.marks(state)}

    out = thievery.lift(state, "gen_t_steward")
    assert out["ok"] is True

    assert "gen_t_steward" not in {m.npc_id for m in thievery.marks(state)}
    lift_targets = {
        t for v in legal_intents(state) if v.action == "lift" for t, _ in v.options
    }
    assert "gen_t_steward" not in lift_targets

    refusal = thievery.lift(state, "gen_t_steward")
    assert refusal["ok"] is False
    assert refusal["mark"] == "Gen T Steward"
    assert refusal["message"]


def test_a_lifted_mark_is_offered_again_the_next_day(
    declared: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _rig(monkeypatch, "success")
    state = _world()
    out = thievery.lift(state, "gen_t_steward")
    assert out["ok"] is True
    assert "gen_t_steward" not in {m.npc_id for m in thievery.marks(state)}

    advance_time(state, 24)

    assert "gen_t_steward" in {m.npc_id for m in thievery.marks(state)}
    out = thievery.lift(state, "gen_t_steward")
    assert out["ok"] is True


def test_the_daily_limit_survives_a_save_round_trip(
    declared: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _rig(monkeypatch, "success")
    state = _world()
    out = thievery.lift(state, "gen_t_steward")
    assert out["ok"] is True

    restored = GameState.from_dict(state.to_save_dict())
    assert "gen_t_steward" not in {m.npc_id for m in thievery.marks(restored)}
    refusal = thievery.lift(restored, "gen_t_steward")
    assert refusal["ok"] is False


# -- content faults -----------------------------------------------------------


@pytest.mark.parametrize(
    "patch,needle",
    [
        ({"purses": {"steward": [{"gold": [1, 2]}]}}, "default"),
        ({"purses": {"default": [{"item_id": "no_such_thing"}]}}, "no_such_thing"),
        ({"alertness": {"default": "impossible"}}, "impossible"),
        ({"purses": {"default": [{"gold": [1, 2], "item_id": "loaf"}]}}, "exactly one"),
    ],
)
def test_a_broken_file_names_itself(tmp_path: Path, patch: dict[str, Any], needle: str) -> None:
    path = _write(tmp_path, {**SPEC, **patch})
    set_overlay({"paths": {"thievery": str(path)}})
    try:
        with pytest.raises(ValueError) as err:
            thievery.load_spec()
        assert needle in str(err.value) and "thievery.yaml" in str(err.value)
    finally:
        set_overlay(None)


# -- provenance and heat --------------------------------------------------------


def test_the_item_effect_records_provenance_only_when_stolen(declared: Path) -> None:
    state = _world()
    apply_effect(state, {"type": "item", "item_id": "loaf"})
    assert state.provenance == {}
    apply_effect(
        state,
        {"type": "item", "item_id": "loaf", "qty": 2, "stolen_from": {"whom": "a", "where": SQUARE}},
    )
    assert state.provenance["loaf"] == [{"whom": "a", "where": SQUARE, "day": 1}] * 2


def test_the_provenance_effect_consumes_the_oldest_entries(declared: Path) -> None:
    state = _world()
    state.provenance = {"loaf": [{"whom": "a", "where": SQUARE, "day": 1}, {"whom": "b", "where": SQUARE, "day": 2}]}
    out = apply_effect(state, {"type": "provenance", "item_id": "loaf", "qty": 1})
    assert out["ok"] is True and out["removed"] == 1
    assert state.provenance["loaf"] == [{"whom": "b", "where": SQUARE, "day": 2}]
    apply_effect(state, {"type": "provenance", "item_id": "loaf", "qty": 5})
    assert "loaf" not in state.provenance


def test_heat_goes_hot_then_cool_across_hot_days(
    declared: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _rig(monkeypatch, "success")
    state = _world()
    assert thievery.heat(state, "golden_ring") == ""
    thievery.lift(state, "gen_t_steward")
    assert thievery.heat(state, "golden_ring") == "hot"
    advance_time(state, 24 * 6)
    assert thievery.heat(state, "golden_ring") == "hot"
    advance_time(state, 24)
    assert thievery.heat(state, "golden_ring") == "cool"


def test_a_named_thing_stays_hot(declared: Path) -> None:
    state = _world()
    apply_effect(
        state,
        {
            "type": "item",
            "item_id": "golden_ring",
            "tags": ["named"],
            "stolen_from": {"whom": "gen_t_steward", "where": SQUARE},
        },
    )
    advance_time(state, 24 * 30)
    assert thievery.heat(state, "golden_ring") == "hot"


# -- the verb -------------------------------------------------------------------


def test_the_verb_offers_only_present_awake_people(declared: Path) -> None:
    state = _world()
    targets = dict(_verbs(state)["lift"])
    assert targets["gen_t_steward"] == "lift Gen T Steward's purse"
    assert "gen_t_cook" in targets and "gen_t_plain" in targets
    assert "gen_t_sleeper" not in targets and "gen_t_away" not in targets


def test_the_verb_is_absent_inside_a_house(declared: Path) -> None:
    state = _world()
    state.location_id = npc_sim.interior_id(SQUARE, "prem_x_1")
    assert "lift" not in _verbs(state)


def test_the_verb_is_absent_without_the_file() -> None:
    assert "lift" not in _verbs(_world())


def test_the_lift_intent_maps_onto_the_skill() -> None:
    from engine.agents.evaluator import ROLLING_SKILLS
    from engine.game.intents import REFUSAL_KEY_FOR_ACTION, SKILL_FOR_ACTION, to_tool_call

    assert SKILL_FOR_ACTION["lift"] == "lift_purse"
    assert REFUSAL_KEY_FOR_ACTION["lift"] == "ok"
    assert "lift_purse" in ROLLING_SKILLS
    assert to_tool_call(GameState(), {"action": "lift", "target": "gen_t_cook"}) == (
        "lift_purse",
        {"npc_id": "gen_t_cook"},
    )


def test_a_failed_lift_executes_as_an_attempt_not_a_refusal(
    declared: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from engine.agents.prompts import summarise_receipt
    from engine.agents.tool_dispatcher import execute_intent
    from engine.game.engine import GameEngine

    _rig(monkeypatch, "failure")
    state = _world()
    engine = GameEngine(state)
    receipts = execute_intent({"action": "lift", "target": "gen_t_cook"}, engine)
    assert receipts and receipts[0]["success"] is True, receipts
    line = summarise_receipt(receipts[0])
    assert "Gen T Cook" in line and "noticed" in line
    assert "gen_t" not in line


def test_the_receipt_line_has_no_ids_and_no_numbers(
    declared: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from engine.agents.prompts import summarise_receipt

    _rig(monkeypatch, "success")
    state = _world()
    for npc in ("gen_t_steward", "gen_t_cook"):
        out = thievery.lift(state, npc)
        line = summarise_receipt({"skill": "lift_purse", "result": out})
        assert line and "gen_t" not in line and "golden_ring" not in line
        assert "DC" not in line and "d20" not in line
    # Coin reads as the story's currency label, never a bare roll total.
    from engine.game.trade import currency_label

    assert currency_label(9) in line


# -- a story without thievery pays nothing ----------------------------------------


def test_the_flagship_sees_no_verb_and_an_unchanged_prompt() -> None:
    from engine.agents import prompts
    from engine.games import registry

    registry.activate("clockwork-dark")
    try:
        assert not thievery.declared()
        state = GameState(rng_seed=42, location_id=SQUARE)
        state.procgen = generate_world(42)
        assert "lift" not in _verbs(state)
        block = prompts.world_state_block(state, {})
        assert "lift" not in block.lower()
        assert "provenance" not in state.to_client_dict()
    finally:
        registry.deactivate()
