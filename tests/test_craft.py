"""
Crafting — the `craft_item` skill against games/clockwork-dark/data/recipes/*.yaml.

WHAT THESE TESTS ARE DEFENDING. DESIGN.md makes "mundane craft as dignity" a
pillar, and the recipe files shipped for a full phase with a header reading
"DATA ONLY. Nothing reads this file yet." The skill reads them now, and these
tests hold the contract:

  1. Refusals are free. Unknown recipe, wrong station, missing tool, short of
     inputs -- none of them advance the clock or touch the pack.
  2. The attempt is not. Inputs and hours are spent pass or fail.
  3. Degrees mean something. A crit adds to the batch, a partial wastes some of
     it, a failure falls back to declared salvage.
  4. The receipt itemises everything, because a craft the player cannot audit
     is a number the narrator made up.
"""

from __future__ import annotations

import json

import pytest

from engine.game import checks, inventory
from engine.game.dice import DiceResult
from engine.game.engine import GameEngine, active_engine
from engine.game.procgen import new_game_state


def _state(location_id: str = "forest_clearing"):
    state = new_game_state(seed=42, location_id=location_id)
    return state


def _craft(state, recipe_id: str) -> dict:
    from engine.skills.builtin.mechanics import craft_item

    with active_engine(GameEngine(state)):
        return json.loads(craft_item(recipe_id))


def _force_degree(monkeypatch, degree: str) -> None:
    """Pin the check outcome so a test asserts the contract, not the dice."""

    def fake_resolve(state, skill, difficulty="standard", **kwargs):
        dice = DiceResult(
            sides=20,
            rolls=[10],
            modifier=0,
            total=10,
            critical=False,
            fumble=False,
            reason="craft",
        )
        return checks.CheckResult(
            skill=skill,
            stat="craft",
            dc=10,
            difficulty=str(difficulty),
            dice=dice,
            modifiers=[],
            total=10,
            margin=0,
            degree=degree,
        )

    monkeypatch.setattr(checks, "resolve", fake_resolve)


# ---------------------------------------------------------------------------
# refusals are free
# ---------------------------------------------------------------------------


def test_an_unknown_recipe_is_refused_and_costs_nothing():
    state = _state()
    hours_before = state.world_clock_hours

    outcome = _craft(state, "recipe_that_does_not_exist")

    assert outcome["success"] is False
    assert "recipe_that_does_not_exist" in outcome["error"]
    assert state.world_clock_hours == hours_before


def test_missing_inputs_are_named_and_nothing_is_spent():
    state = _state()
    hours_before = state.world_clock_hours

    outcome = _craft(state, "dry_mushrooms")  # needs 5x wild_mushroom

    assert outcome["success"] is False
    assert "wild_mushroom" in outcome["error"]
    assert state.world_clock_hours == hours_before
    assert inventory.quantity(state, "dried_mushrooms") == 0


def test_the_wrong_station_is_refused_before_the_clock_moves():
    state = _state(location_id="forest_clearing")
    inventory.grant(state, "barley_flour", 1)
    inventory.grant(state, "baking_peel", 1)
    hours_before = state.world_clock_hours

    outcome = _craft(state, "bake_loaf")  # station: edgewood_bakery

    assert outcome["success"] is False
    assert "edgewood_bakery" in outcome["error"]
    assert state.world_clock_hours == hours_before
    assert inventory.quantity(state, "barley_flour") == 1


def test_a_missing_tool_is_refused_by_name():
    state = _state(location_id="edgewood_bakery")
    inventory.grant(state, "barley_flour", 1)

    outcome = _craft(state, "bake_loaf")  # tools: [baking_peel]

    assert outcome["success"] is False
    assert "baking_peel" in outcome["error"]


# ---------------------------------------------------------------------------
# the attempt spends, pass or fail
# ---------------------------------------------------------------------------


def test_a_failed_craft_still_costs_the_inputs_and_the_morning(monkeypatch):
    _force_degree(monkeypatch, "failure")
    state = _state()
    inventory.grant(state, "wild_mushroom", 5)
    hours_before = state.world_clock_hours

    outcome = _craft(state, "dry_mushrooms")

    assert outcome["success"] is False
    assert state.world_clock_hours > hours_before
    assert inventory.quantity(state, "wild_mushroom") == 2, (
        "failure salvages 2 of the 5 consumed mushrooms, per the recipe"
    )
    assert outcome["salvaged"] is True
    assert outcome["produced"]["id"] == "wild_mushroom"


def test_a_failure_with_no_salvage_produces_nothing(monkeypatch):
    _force_degree(monkeypatch, "failure")
    state = _state()
    inventory.grant(state, "birch_resin", 2)

    outcome = _craft(state, "press_pitch_torches")  # no salvage row declared

    assert outcome["success"] is False
    assert outcome["produced"] is None
    assert inventory.quantity(state, "birch_resin") == 0
    assert inventory.quantity(state, "pitch_torch") == 0


# ---------------------------------------------------------------------------
# degrees
# ---------------------------------------------------------------------------


def test_a_success_grants_the_declared_output(monkeypatch):
    _force_degree(monkeypatch, "success")
    state = _state()
    inventory.grant(state, "seed_grain", 1)

    outcome = _craft(state, "mill_flour")  # output: 2x barley_flour

    assert outcome["success"] is True
    assert outcome["degree"] == "success"
    assert inventory.quantity(state, "seed_grain") == 0
    assert inventory.quantity(state, "barley_flour") == 2
    assert outcome["produced"]["qty"] == 2


def test_a_critical_success_adds_one_to_the_batch(monkeypatch):
    _force_degree(monkeypatch, "crit_success")
    state = _state()
    inventory.grant(state, "seed_grain", 1)

    outcome = _craft(state, "mill_flour")

    assert inventory.quantity(state, "barley_flour") == 3
    assert outcome["produced"]["qty"] == 3


def test_a_partial_success_wastes_some_of_the_batch(monkeypatch):
    _force_degree(monkeypatch, "partial")
    state = _state(location_id="edgewood_bakery")
    inventory.grant(state, "barley_flour", 1)
    inventory.grant(state, "baking_peel", 1)

    outcome = _craft(state, "bake_loaf")  # output: 4x loaf

    assert outcome["success"] is True
    assert outcome["degree"] == "partial"
    assert inventory.quantity(state, "loaf") == 2, "half the batch, wasted material"
    assert outcome["produced"]["qty"] == 2


def test_a_tool_is_required_but_never_consumed(monkeypatch):
    _force_degree(monkeypatch, "success")
    state = _state(location_id="edgewood_bakery")
    inventory.grant(state, "barley_flour", 1)
    inventory.grant(state, "baking_peel", 1)

    _craft(state, "bake_loaf")

    assert inventory.quantity(state, "baking_peel") == 1


# ---------------------------------------------------------------------------
# receipt shape
# ---------------------------------------------------------------------------


def test_the_receipt_carries_the_whole_arithmetic(monkeypatch):
    _force_degree(monkeypatch, "success")
    state = _state()
    inventory.grant(state, "seed_grain", 1)

    outcome = _craft(state, "mill_flour")

    for key in (
        "success",
        "recipe_id",
        "degree",
        "check",
        "consumed",
        "produced",
        "salvaged",
        "hours",
        "world_day",
        "text",
    ):
        assert key in outcome, f"receipt lost its {key}"
    assert outcome["recipe_id"] == "mill_flour"
    assert outcome["hours"] == 2.0
    assert outcome["check"]["skill"] == "craft"
    assert outcome["consumed"][0]["item_id"] == "seed_grain"
    assert outcome["text"], "the recipe's own line must reach the narrator"


def test_a_real_unforced_craft_resolves_through_the_rules_engine():
    """No mock: the whole path, dice included, on a fixed seed."""
    state = _state()
    inventory.grant(state, "seed_grain", 1)

    outcome = _craft(state, "mill_flour")

    assert outcome["degree"] in ("crit_success", "success", "partial", "failure")
    assert outcome["check"]["dc"] > 0
    # Whatever the roll, the grain is gone and the hours are spent.
    assert inventory.quantity(state, "seed_grain") == 0
    assert state.world_clock_hours >= 2.0


def test_list_recipes_names_only_what_can_be_attempted_here():
    from engine.skills.builtin.mechanics import list_recipes

    state = _state(location_id="forest_clearing")
    with active_engine(GameEngine(state)):
        listing = json.loads(list_recipes())

    ids = {r["id"] for r in listing["recipes"]}
    assert "dry_mushrooms" in ids, "a stationless recipe is attemptable anywhere"
    assert "bake_loaf" not in ids, "a stationed recipe must not be offered elsewhere"
