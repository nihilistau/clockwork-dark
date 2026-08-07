"""GameState serialization tests."""

from __future__ import annotations

from dataclasses import asdict

import pytest

from engine.game.clock import set_clock
from engine.game.state import (
    AgentMind,
    EvilPhase,
    GameState,
    InventoryItem,
    ProcgenResult,
    TimedEffect,
    Wound,
)


def _rich_state() -> GameState:
    """A state with every field pushed off its default."""
    state = GameState(
        player_name="Alden",
        archetype="hedge_wise",
        location_id="edgewood_square",
        awareness=55.0,
        evil_progress=0.7,
        plot_involvement=42.0,
        story_pressure=61.0,
        inventory=[InventoryItem(id="loaf", name="Loaf", qty=2, tags=["food"])],
        reputations={"edgewood": 12, "militia": -30},
        storyteller_mind=AgentMind(patience=3.0, cruelty_bias=0.9),
        assistant_mind=AgentMind(trust_level=95.0, current_form="reflection"),
        procgen=ProcgenResult(seed=1234, shrine_mural="a wheel with no rim"),
        flags={"met_maris": True},
        world_events=[{"event_id": "caravan_arrival", "expires_day": 9}],
        rumors=["The rain came down wrong over Millhaven."],
        media_cache={"forest_dawn": "/api/media/x.png"},
        media_cutscenes_shown=["phase_stirring"],
        last_cutscene_phase="stirring",
        turn_number=37,
        rng_seed=1234,
        rng_counters={"encounter": 4},
        hunger=41.5,
        wounds=[Wound(id="w1", text="knife-line", severity=2, heals_on_day=9)],
        active_effects=[TimedEffect(id="e1", kind="check_penalty", expires_day=9)],
    )
    set_clock(state, day=11, hour=19)
    return state


def test_save_round_trip_is_lossless():
    """
    Every field survives a save/load cycle.

    The old to_dict() omitted both AgentMinds while from_dict() read them, so
    any round trip silently reset evil progress, awareness, trust and patience.
    The tests that existed hand-patched the dropped keys back in, which hid it.
    This test is not permitted to patch anything.
    """
    original = _rich_state()
    restored = GameState.from_dict(original.to_save_dict())
    assert asdict(restored) == asdict(original)


def test_round_trip_preserves_agent_minds():
    original = _rich_state()
    restored = GameState.from_dict(original.to_save_dict())
    assert restored.assistant_mind.trust_level == 95.0
    assert restored.assistant_mind.current_form == "reflection"
    assert restored.storyteller_mind.patience == 3.0


def test_round_trip_preserves_hidden_stats():
    original = _rich_state()
    restored = GameState.from_dict(original.to_save_dict())
    assert restored.awareness == 55.0
    assert restored.evil_progress == 0.7
    assert restored.evil_phase == EvilPhase.SPREADING


def test_phase_is_derived_from_progress_on_load():
    state = GameState(evil_progress=0.25)
    restored = GameState.from_dict(state.to_save_dict())
    assert restored.evil_phase == EvilPhase.STIRRING


def test_from_dict_ignores_unknown_keys():
    """Schema evolution must not hard-crash a load."""
    data = _rich_state().to_save_dict()
    data["a_field_from_the_future"] = 1
    data["stats"]["luck"] = 7
    data["inventory"][0]["weight"] = 3
    restored = GameState.from_dict(data)
    assert restored.player_name == "Alden"
    assert restored.inventory[0].qty == 2


def test_from_dict_tolerates_missing_keys():
    restored = GameState.from_dict({})
    assert restored.player_name == "Traveler"
    assert restored.world_day == 1


def test_client_dict_redacts_hidden_stats():
    state = _rich_state()
    payload = state.to_client_dict()
    assert "awareness" not in payload
    assert "evil_progress" not in payload
    assert "storyteller_mind" not in payload
    # The phase ships because the UI re-tints on it; the raw number does not.
    assert payload["evil_phase"] == "spreading"


def test_client_dict_carries_derived_time():
    state = _rich_state()
    payload = state.to_client_dict()
    assert payload["world_day"] == 11
    assert payload["world_hour"] == 19
    assert payload["time_of_day"] == "dusk"


@pytest.mark.parametrize(
    "hour,expected",
    [(6, "dawn"), (12, "day"), (18, "dusk"), (23, "night"), (3, "night")],
)
def test_time_of_day_bands(hour, expected):
    state = GameState()
    set_clock(state, day=1, hour=hour)
    assert state.time_of_day == expected
