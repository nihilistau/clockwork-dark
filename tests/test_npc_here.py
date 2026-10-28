"""`{npc_here: <npc_id>}` (v0.25.0 E6, spec §6.6): the person is where the player is, and can be spoken to."""

from __future__ import annotations

from typing import Any

import pytest

from engine.games import registry


@pytest.fixture
def state():
    from engine.game.procgen import new_game_state

    registry.activate("clockwork-dark")
    try:
        yield new_game_state(seed=7)
    finally:
        registry.deactivate()


def _here(state: Any, npc_id: str, place: str, hour: int) -> bool:
    from engine.game.clock import set_clock
    from engine.game.quests import evaluate_condition

    set_clock(state, day=state.world_day, hour=hour)
    state.location_id = place
    return bool(evaluate_condition(state, {"npc_here": npc_id}))


def test_it_is_in_the_grammar() -> None:
    from engine.game.quests import predicate_names

    assert "npc_here" in predicate_names()


def test_by_routine(state) -> None:
    assert _here(state, "npc_maris", "edgewood_bakery", 5)
    assert not _here(state, "npc_maris", "edgewood_square", 5)


def test_asleep_is_not_here(state) -> None:
    assert not _here(state, "npc_maris", "edgewood_bakery", 22)


def test_by_override(state) -> None:
    from engine.game.effects import apply_effect

    apply_effect(state, {"type": "flag", "flag": "npc_at_npc_maris", "value": "edgewood_square"})
    assert _here(state, "npc_maris", "edgewood_square", 8)


def test_by_event(state) -> None:
    from engine.game.clock import set_clock
    from engine.world.world_sim import WorldSim

    # The caravan's own `min_day: 5` gate holds for a forced start too (T1's force hook).
    set_clock(state, day=5, hour=8)
    WorldSim.on_tick(state, hours=0.0, force=["caravan_arrival"])
    assert any(e.get("event_id") == "caravan_arrival" for e in state.world_events), state.world_events
    assert _here(state, "npc_odran", "edgewood_square", 2)   # asleep by routine, here by the event


def test_by_pin(state) -> None:
    from engine.game.effects import apply_effect

    apply_effect(state, {"type": "flag", "flag": "npc_pin_npc_ilya", "value": True})
    assert _here(state, "npc_ilya", "tinker_caravan", 16)     # the square by routine


def test_nobody_is_not_here(state) -> None:
    assert not _here(state, "npc_nobody", "edgewood_square", 12)
