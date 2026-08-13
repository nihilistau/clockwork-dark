"""Mechanics skill integration tests."""

from __future__ import annotations

import json

import engine.skills.builtin.mechanics  # noqa: F401 — register skills
from engine.game.engine import GameEngine, set_active_engine
from engine.game.state import GameState
from engine.skills.registry import SKILL_REGISTRY


def test_skills_registered():
    # "core", not "clockwork": the built-in pack is the engine's, and its old
    # name was one story's. The pack name is registry-internal -- it reaches no
    # save, no client payload and no model manifest -- so the rename is free.
    names = {s.name for s in SKILL_REGISTRY.get_pack_tools("core")}
    assert "roll_dice" in names
    assert "move_to" in names
    assert "query_evil_state" in names


def test_roll_dice_skill():
    state = GameState()
    set_active_engine(GameEngine(state))
    raw = SKILL_REGISTRY.invoke("roll_dice", sides=20, modifier=0, reason="test")
    data = json.loads(raw)
    assert "total" in data
    assert data["sides"] == 20


def test_move_to_skill_success():
    state = GameState(location_id="forest_clearing")
    state.stats.stamina = 100
    set_active_engine(GameEngine(state))
    raw = SKILL_REGISTRY.invoke("move_to", location_id="edgewood_square")
    data = json.loads(raw)
    assert data["success"] is True
    assert state.location_id == "edgewood_square"


def test_trade_buy_bread():
    state = GameState(location_id="edgewood_bakery")
    state.stats.gold = 10
    set_active_engine(GameEngine(state))
    raw = SKILL_REGISTRY.invoke("trade", action="buy", item_id="loaf", npc_id="npc_maris")
    data = json.loads(raw)
    assert data["success"] is True
    assert state.stats.gold == 8