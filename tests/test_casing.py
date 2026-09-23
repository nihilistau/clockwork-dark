"""
Casing: watching a house until it gives up what a thief needs to know.

THE SHAPE. ``case <premise>`` spends two in-game hours in the district and
reveals ONE more thing about the house, in an order drawn from the seed:
first when it stands empty (read off the household's own routines), then its
defences one at a time, the thing worth taking, and whether somebody inside is
hiding something. What is learned is written through ``apply_effect`` (the
``intel`` kind) onto ``state.premise_intel``, and the narrator's DISTRICT block
shows only that -- never an id, a tier or loot nobody has seen.

WHAT THESE TESTS HOLD. The order replays per seed; the occupancy line is right
for a household built by hand; the clock moves by exactly ``CASE_HOURS``
through ``advance_time``; a watch refuses in the wrong district and when there
is nothing left to learn, and costs no time when it does; the verb appears
only where there are houses with something still unknown; and the flagship,
which declares no premises, sees neither the verb nor the block.

Built on test_premises.py's synthetic directory, because HUE & CRY's own
premises land in a later task.

Version: v0.1.0 [2026-09-23]
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterator

import pytest

from engine.config import set_overlay
from engine.game import clock
from engine.game.clock import set_clock
from engine.game.effects import apply_effect
from engine.game.procgen import generate_world
from engine.game.state import GameState
from engine.world import npc_sim, premises

from test_premises import _build

SQUARE = "edgewood_square"


@pytest.fixture()
def declared(tmp_path: Path) -> Iterator[Path]:
    root = _build(tmp_path / "premises")
    set_overlay({"paths": {"premises": str(root)}})
    try:
        yield root
    finally:
        set_overlay(None)


def _world(seed: int = 42, location: str = SQUARE) -> GameState:
    state = GameState(rng_seed=seed, location_id=location)
    state.procgen = generate_world(seed)
    set_clock(state, day=1, hour=8)
    return state


def _verbs(state: GameState) -> dict[str, tuple[str, ...]]:
    from engine.game.intents import legal_intents

    return {v.action: v.targets for v in legal_intents(state)}


def _hand_built(state: GameState, routines: list[list[dict[str, Any]]]) -> dict[str, Any]:
    """One townhouse on the square with a household of the given routines."""
    pid = "prem_hand_1"
    home = npc_sim.interior_id(SQUARE, pid)
    members = []
    for idx, routine in enumerate(routines):
        members.append(
            {
                "id": f"gen_hand_1_m{idx}",
                "name": f"Person {idx}",
                "role": "master",
                "home": home,
                "premise": pid,
                "routine": routine,
            }
        )
    prem = {
        "id": pid,
        "district": SQUARE,
        "type": "townhouse",
        "anchor": False,
        "name": "the Hand house",
        "tier": 1,
        "household": [m["id"] for m in members],
        "security": ["good_lock"],
        "loot": ["golden_ring", "loaf"],
        "secret": "debt_letter",
    }
    state.procgen.premises = [prem]
    state.procgen.npcs = members
    return prem


# -- the intel list -----------------------------------------------------------


def test_intel_order_replays_per_seed_and_occupancy_leads(declared: Path) -> None:
    state = _world(42)
    for prem in state.procgen.premises:
        first = premises.intel_for(state, prem["id"])
        assert first == premises.intel_for(state, prem["id"])
        assert first[0]["id"] == "occupancy"
        ids = [row["id"] for row in first]
        assert len(ids) == len(set(ids))
        # One line per defence, one loot hint, and the secret's existence.
        assert len(ids) == 1 + len(prem["security"]) + 1 + (1 if prem["secret"] else 0)


def test_the_order_after_occupancy_is_drawn_not_fixed(declared: Path) -> None:
    orders = set()
    for seed in range(12):
        state = _world(42)
        state.rng_seed = seed
        prem = premises.get(state, "prem_edgewood_square_1")
        orders.add(tuple(r["id"] for r in premises.intel_for(state, prem["id"])))
    assert len(orders) > 1, "every seed cases the house in the same order"


def test_security_and_loot_and_secret_read_as_words(declared: Path) -> None:
    state = GameState(rng_seed=3, location_id=SQUARE)
    _hand_built(state, [[]])
    texts = {r["id"]: r["text"] for r in premises.intel_for(state, "prem_hand_1")}
    assert texts["security:good_lock"] == "a good lock on the street door"
    # The ring outvalues the loaf, so it is the one the hint names.
    assert texts["loot"] == "worth it: Gold ring"
    assert texts["secret"] == "somebody here is hiding something"


def test_occupancy_is_the_longest_empty_run(declared: Path) -> None:
    state = GameState(rng_seed=1, location_id=SQUARE)
    set_clock(state, day=2, hour=7)
    before = state.world_clock_hours
    _hand_built(
        state,
        [
            [{"hours": list(range(10, 16)), "location": "edgewood_bakery", "activity": "baking"}],
            [{"hours": list(range(9, 18)), "location": "the_forge", "activity": "at the anvil"}],
        ],
    )
    occupancy = premises.intel_for(state, "prem_hand_1")[0]
    assert occupancy == {"id": "occupancy", "text": "empty from 10:00 to 16:00"}
    # Working out who is home at every hour must not move the world's clock.
    assert state.world_clock_hours == before


def test_occupancy_wraps_midnight(declared: Path) -> None:
    state = GameState(rng_seed=1, location_id=SQUARE)
    _hand_built(
        state,
        [[{"hours": [22, 23, 0, 1], "location": "edgewood_bakery", "activity": "night baking"}]],
    )
    assert premises.intel_for(state, "prem_hand_1")[0]["text"] == "empty from 22:00 to 02:00"


def test_a_house_somebody_never_leaves_is_never_empty(declared: Path) -> None:
    state = GameState(rng_seed=1, location_id=SQUARE)
    _hand_built(
        state,
        [
            [{"hours": list(range(10, 16)), "location": "edgewood_bakery", "activity": "baking"}],
            [],
        ],
    )
    assert premises.intel_for(state, "prem_hand_1")[0]["text"] == "never empty"


# -- the intel effect -----------------------------------------------------------


def test_the_intel_effect_records_once_and_speaks_the_text(declared: Path) -> None:
    state = GameState(rng_seed=3, location_id=SQUARE)
    _hand_built(state, [[]])
    receipt = apply_effect(
        state, {"type": "intel", "premise": "prem_hand_1", "intel": "security:good_lock"}
    )
    assert receipt["ok"] is True
    assert receipt["text"] == "a good lock on the street door"
    apply_effect(state, {"type": "intel", "premise": "prem_hand_1", "intel": "security:good_lock"})
    assert state.premise_intel == {"prem_hand_1": ["security:good_lock"]}


def test_the_intel_effect_refuses_what_the_house_does_not_have(declared: Path) -> None:
    state = GameState(rng_seed=3, location_id=SQUARE)
    _hand_built(state, [[]])
    bad = apply_effect(state, {"type": "intel", "premise": "prem_hand_1", "intel": "security:moat"})
    assert bad["ok"] is False
    gone = apply_effect(state, {"type": "intel", "premise": "prem_nowhere", "intel": "occupancy"})
    assert gone["ok"] is False
    assert state.premise_intel == {}


# -- case -------------------------------------------------------------------


def test_case_spends_two_hours_through_advance_time_and_reveals_in_order(
    declared: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = _world(42)
    pid = "prem_edgewood_square_1"
    order = premises.intel_for(state, pid)
    calls: list[float] = []
    real = clock.advance_time

    def spy(st: GameState, hours: float):
        calls.append(hours)
        return real(st, hours)

    monkeypatch.setattr(clock, "advance_time", spy)

    for n, expected in enumerate(order, start=1):
        before = state.world_clock_hours
        result = premises.case(state, pid)
        assert result["ok"] is True, result
        assert result["learned"] == expected["text"]
        assert result["known"] == n and result["of"] == len(order)
        assert result["hours"] == premises.CASE_HOURS == 2
        assert state.world_clock_hours == before + 2
    assert calls == [2] * len(order)
    assert state.premise_intel[pid] == [r["id"] for r in order]

    before = state.world_clock_hours
    done = premises.case(state, pid)
    assert done["ok"] is False and done["message"]
    assert state.world_clock_hours == before, "a refused watch cost time"
    assert calls == [2] * len(order)


def test_case_refuses_a_house_in_another_district(declared: Path) -> None:
    state = _world(42, location="forest_clearing")
    before = state.world_clock_hours
    result = premises.case(state, "prem_edgewood_square_1")
    assert result["ok"] is False and result["message"]
    assert state.world_clock_hours == before
    assert state.premise_intel == {}


def test_case_refuses_a_house_that_does_not_exist(declared: Path) -> None:
    state = _world(42)
    assert premises.case(state, "prem_nowhere")["ok"] is False


# -- the verb -----------------------------------------------------------------


def test_the_verb_appears_only_where_there_are_houses(declared: Path) -> None:
    from engine.game.intents import find_verb, legal_intents

    state = _world(42)
    verbs = _verbs(state)
    here = [p["id"] for p in premises.at(state, SQUARE)]
    assert set(verbs["case"]) == set(here)
    verb = find_verb(legal_intents(state), "case")
    for prem in premises.at(state, SQUARE):
        assert verb.label_for(prem["id"]) == f"watch {prem['name']}"

    state.location_id = "forest_clearing"
    assert "case" not in _verbs(state)


def test_the_verb_drops_a_house_once_everything_is_known(declared: Path) -> None:
    state = _world(42)
    first, *rest = premises.at(state, SQUARE)
    state.premise_intel[first["id"]] = [r["id"] for r in premises.intel_for(state, first["id"])]
    targets = _verbs(state)["case"]
    assert first["id"] not in targets
    assert set(targets) == {p["id"] for p in rest}
    for prem in rest:
        state.premise_intel[prem["id"]] = [r["id"] for r in premises.intel_for(state, prem["id"])]
    assert "case" not in _verbs(state)


def test_the_case_intent_maps_onto_the_skill() -> None:
    from engine.game.intents import REFUSAL_KEY_FOR_ACTION, SKILL_FOR_ACTION, to_tool_call

    assert SKILL_FOR_ACTION["case"] == "case_premise"
    assert REFUSAL_KEY_FOR_ACTION["case"] == "ok"
    assert to_tool_call(GameState(), {"action": "case", "target": "prem_x_1"}) == (
        "case_premise",
        {"premise_id": "prem_x_1"},
    )


def test_a_case_intent_executes_end_to_end(declared: Path) -> None:
    from engine.agents.prompts import summarise_receipt
    from engine.agents.tool_dispatcher import execute_intent
    from engine.game.engine import GameEngine

    state = _world(42)
    engine = GameEngine(state)
    before = state.world_clock_hours
    receipts = execute_intent({"action": "case", "target": "prem_edgewood_square_1"}, engine)
    assert receipts and receipts[0]["success"] is True, receipts
    assert state.world_clock_hours == before + 2
    assert len(state.premise_intel["prem_edgewood_square_1"]) == 1
    line = summarise_receipt(receipts[0])
    assert "prem_" not in line
    assert premises.get(state, "prem_edgewood_square_1")["name"] in line


# -- what the narrator is told -------------------------------------------------

_CLOCK = re.compile(r"\b\d{2}:00\b")


def _no_stray_digits(text: str, state: GameState) -> str:
    """Strip clock times and the houses' own names; what is left has no digits."""
    out = _CLOCK.sub("", text)
    for prem in state.procgen.premises:
        # A drawn name may be "Number 12, Wick Lane" -- that is its name, not a
        # leaked number.
        out = out.replace(prem["name"], "")
    return out


def test_district_block_shows_only_what_is_known(declared: Path) -> None:
    from engine.agents.prompts import district_block

    state = _world(42)
    here = premises.at(state, SQUARE)
    before = district_block(state)
    assert before.startswith("PREMISES HERE (what you know):")
    for prem in here:
        assert prem["name"] in before
    for prem in here:
        for row in premises.intel_for(state, prem["id"]):
            if row["id"] == "occupancy":
                continue
            assert row["text"] not in before, "unlearned intel reached the narrator"

    target = here[0]
    learned = premises.case(state, target["id"])["learned"]
    after = district_block(state)
    assert learned in after
    unknown = premises.intel_for(state, target["id"])[1:]
    for row in unknown:
        assert row["text"] not in after

    for text in (before, after):
        assert "prem_" not in text
        assert "tier" not in text.lower()
        assert not re.search(r"\d", _no_stray_digits(text, state)), text


def test_district_block_is_empty_where_there_are_no_houses(declared: Path) -> None:
    from engine.agents.prompts import district_block

    assert district_block(_world(42, location="forest_clearing")) == ""


def test_the_world_block_carries_the_district(declared: Path) -> None:
    from engine.agents.prompts import world_state_block

    state = _world(42)
    assert "PREMISES HERE (what you know):" in world_state_block(state, {})


def test_the_receipt_line_has_no_ids_and_no_numbers() -> None:
    from engine.agents.prompts import summarise_receipt

    line = summarise_receipt(
        {
            "skill": "case_premise",
            "success": True,
            "result": {
                "ok": True,
                "premise": "the Fenwick townhouse",
                "learned": "empty from 10:00 to 16:00",
                "known": 1,
                "of": 5,
                "hours": 2,
            },
        }
    )
    assert "the Fenwick townhouse" in line and "empty from 10:00 to 16:00" in line
    assert not re.search(r"\d", _CLOCK.sub("", line)), line
    assert "{" not in line


# -- a story without premises pays nothing --------------------------------------


def test_the_flagship_sees_no_verb_and_no_block(monkeypatch: pytest.MonkeyPatch) -> None:
    from engine.agents import prompts
    from engine.games import registry

    registry.activate("clockwork-dark")
    try:
        assert not premises.declared()
        state = GameState(rng_seed=42, location_id=SQUARE)
        state.procgen = generate_world(42)
        assert "case" not in _verbs(state)
        assert prompts.district_block(state) == ""
        with_block = prompts.world_state_block(state, {})
        monkeypatch.setattr(prompts, "district_block", lambda s: "")
        assert prompts.world_state_block(state, {}) == with_block
        assert "PREMISES" not in with_block
    finally:
        registry.deactivate()
