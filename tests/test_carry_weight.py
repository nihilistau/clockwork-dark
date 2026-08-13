"""
Carry weight — computed since v0.2.0 of the item registry, read by nothing.

``inventory.carry_limit``'s own docstring said it: "NOT WIRED as a penalty...
so the rule -- when someone writes it -- has a limit that was chosen once".
This is the rule, and its whole surface area is deliberate:

  * an over-limit pack scales TRAVEL stamina by 1.5, and travel only
  * a pack AT the limit pays nothing -- full is not penalised
  * rest never reads it (CLAUDE.md rule 6: never gate rest)
  * the state payload and the move receipt both say when it is biting

Balance: `scripts/simulate.py --policy all --turns 200 --seed 42` before and
after shows identical death counts -- no simulated policy ever packs past
25 kg, so the multiplier prices a choice, not the baseline game.
"""

from __future__ import annotations

import pytest

from engine.game import inventory, survival
from engine.game.engine import GameEngine
from engine.game.procgen import new_game_state


def _overload(state) -> None:
    """Stuff the pack past the allowance with a real, weighed registry item."""
    row = inventory.get_item("hide_roll") or {}
    weight = float(row.get("weight", 0.0) or 0.0)
    assert weight > 0, "hide_roll lost its weight; pick another heavy item"
    needed = int(inventory.carry_limit(state) / weight) + 1
    inventory.grant(state, "hide_roll", needed)
    assert inventory.overloaded(state)


def test_an_over_limit_pack_prices_the_leg_at_one_and_a_half():
    state = new_game_state(seed=42, location_id="forest_clearing")
    state.stats.stamina = 100
    baseline = GameEngine(state).move_to("edgewood_square")
    assert baseline.success and baseline.overloaded is False

    heavy = new_game_state(seed=42, location_id="forest_clearing")
    heavy.stats.stamina = 100
    _overload(heavy)
    priced = GameEngine(heavy).move_to("edgewood_square")

    assert priced.success is True, "an over-limit pack must never refuse the walk"
    assert priced.overloaded is True
    assert priced.stamina_cost == int(baseline.stamina_cost * 1.5)


def test_a_pack_at_the_limit_pays_nothing_extra():
    state = new_game_state(seed=42)
    state.inventory.clear()
    # Exactly at the allowance: hide_roll ships at a clean weight, so top up
    # to the limit with arithmetic rather than luck.
    row = inventory.get_item("hide_roll") or {}
    weight = float(row.get("weight"))
    at_limit = int(inventory.carry_limit(state) / weight)
    inventory.grant(state, "hide_roll", at_limit)

    assert inventory.carried_weight(state) <= inventory.carry_limit(state)
    assert inventory.overloaded(state) is False
    assert inventory.travel_stamina_multiplier(state) == 1.0


def test_rest_is_never_gated_or_taxed_by_the_pack():
    """
    CLAUDE.md rule 6. Rest is the only thing that restores stamina; a carry
    penalty that reached it would rebuild the shipped soft-lock.
    """
    light = new_game_state(seed=42)
    light.stats.stamina = 10
    light_rest = survival.rest(light, "rest_short")

    heavy = new_game_state(seed=42)
    heavy.stats.stamina = 10
    _overload(heavy)
    heavy_rest = survival.rest(heavy, "rest_short")

    assert heavy_rest["success"] is True
    light_gain = light_rest["stamina"] - light_rest["stamina_before"]
    heavy_gain = heavy_rest["stamina"] - heavy_rest["stamina_before"]
    assert heavy_gain == light_gain, "the pack taxed rest -- rule 6"


def test_the_client_payload_names_the_state_before_it_bites():
    state = new_game_state(seed=42)
    carry = state.to_client_dict()["carry"]
    assert carry["limit"] >= inventory.BASE_CARRY_KG
    assert carry["overloaded"] is False

    _overload(state)
    carry = state.to_client_dict()["carry"]
    assert carry["overloaded"] is True
    assert carry["weight"] > carry["limit"]


def test_the_move_receipt_says_why_the_leg_cost_more():
    state = new_game_state(seed=42, location_id="forest_clearing")
    state.stats.stamina = 100
    _overload(state)

    receipt = GameEngine(state).move_to("edgewood_square").to_dict()

    assert receipt["overloaded"] is True
    assert receipt["stamina_cost"] > 5
