"""
World effects tests.

The doom clock used to be a number that went up. These assert it now changes
the world, that it does so exactly once, and that the changes survive both a
save round trip and the world sim's event sweep.
"""

from __future__ import annotations

import pytest

from engine.game.procgen import generate_world
from engine.game.state import GameState
from engine.world import world_effects
from engine.world.world_sim import WorldSim


@pytest.fixture(autouse=True)
def _clean_cache():
    world_effects.reset_doom_effects_cache()
    yield
    world_effects.reset_doom_effects_cache()


@pytest.fixture
def state() -> GameState:
    """A state with a real procgen population, so npc_moves has NPCs to move."""
    game = GameState(rng_seed=1234)
    game.procgen = generate_world(seed=1234)
    return game


# -- the wiring -------------------------------------------------------------


def test_beats_fire_from_the_clock_without_a_turn_handler(state):
    """
    The integration, not the unit.

    ``apply_pending_beats`` is called from ``clock.advance_time`` rather than
    from a turn handler, so the doom clock keeps its promise -- "evil ticks
    whether you become a hero or a baker" -- for a player who spends the week
    asleep, travelling or unconscious. Nothing else in the suite would notice
    if that call were removed; a whole content system would just stop existing.
    """
    from engine.game import clock

    for _ in range(60):
        clock.advance_time(state, 24)

    fired = [k for k in state.flags if k.startswith("doom_beat_")]
    assert fired, "60 days of clock must cross at least one doom threshold"
    assert state.world_events, "a fired beat must leave a mark on the world"


def test_repeated_clock_advances_do_not_refire_a_beat(state):
    from engine.game import clock

    for _ in range(40):
        clock.advance_time(state, 24)
    marks = len(state.world_events)

    for _ in range(10):
        clock.advance_time(state, 1)

    assert len(state.world_events) == marks, "a beat re-applied on every hour"


# -- the table --------------------------------------------------------------


def test_the_shipped_beat_table_loads():
    table = world_effects.load_doom_effects()
    assert table, "data/rules/doom_effects.yaml must load"
    for beat_id, spec in table.items():
        assert isinstance(spec, dict), beat_id
        assert 0.0 <= float(spec["at_progress"]) <= 1.0, beat_id


def test_npc_moves_only_target_real_locations():
    """A bad destination silently deletes an NPC from the world."""
    from engine.game.locations import LOCATION_IDS

    for beat_id, spec in world_effects.load_doom_effects().items():
        for npc_id, destination in (spec.get("npc_moves") or {}).items():
            assert destination in LOCATION_IDS, f"{beat_id}: {npc_id} -> {destination}"


# -- crossing beats ---------------------------------------------------------


def test_no_beats_pending_at_zero_progress(state):
    assert world_effects.pending_beats(state) == []


def test_beats_become_pending_as_the_dark_advances(state):
    state.evil_progress = 0.35
    pending = world_effects.pending_beats(state)
    assert "wheat_turns" in pending
    assert "scarecrow_wakes" in pending
    assert "tower_assembles" not in pending


def test_pending_beats_are_returned_in_threshold_order(state):
    state.evil_progress = 1.0
    pending = world_effects.pending_beats(state)
    table = world_effects.load_doom_effects()
    thresholds = [float(table[b]["at_progress"]) for b in pending]
    assert thresholds == sorted(thresholds)


def test_applying_a_beat_changes_the_world(state):
    state.evil_progress = 0.35
    applied = world_effects.apply_beat(state, "scarecrow_wakes")

    assert applied
    assert state.flags["scarecrow_awake"] is True
    assert state.rumors, "the village should be talking about it"
    assert any(e.get("event_id") == "scarecrow_walks" for e in state.world_events)


def test_a_beat_fires_exactly_once(state):
    state.evil_progress = 0.35
    first = world_effects.apply_beat(state, "scarecrow_wakes")
    second = world_effects.apply_beat(state, "scarecrow_wakes")

    assert first
    assert second == [], "a re-fired beat must be a no-op"
    assert len(state.rumors) == len(set(state.rumors)), "rumors must not duplicate"


def test_apply_pending_fires_everything_crossed_and_then_stops(state):
    state.evil_progress = 0.55
    first_pass = world_effects.apply_pending_beats(state)
    second_pass = world_effects.apply_pending_beats(state)

    assert first_pass
    assert second_pass == []
    assert world_effects.pending_beats(state) == []


def test_unknown_beat_is_ignored_not_raised(state):
    assert world_effects.apply_beat(state, "no_such_beat") == []


# -- the effects themselves -------------------------------------------------


def test_discoveries_open_gated_content(state):
    state.evil_progress = 0.75
    world_effects.apply_beat(state, "tunnels_open")
    assert state.flags["discovery_hidden_path"] is True


def test_npc_moves_empty_the_margins(state):
    """The village visibly contracts. This is the effect the player notices."""
    ilya = state.procgen.npc_by_id("npc_ilya")
    assert ilya is not None and ilya["location_id"] == "tinker_caravan"

    state.evil_progress = 0.55
    world_effects.apply_beat(state, "vines_breach_forest")

    assert ilya["location_id"] == "edgewood_square"
    assert ilya["displaced"] is True
    assert "npc_ilya" not in [
        n["id"] for n in state.procgen.npcs_at("tinker_caravan")
    ]


def test_npc_move_to_a_bogus_location_is_refused(state, monkeypatch):
    monkeypatch.setattr(
        world_effects,
        "load_doom_effects",
        lambda: {
            "bad": {
                "at_progress": 0.1,
                "npc_moves": {"npc_ilya": "atlantis"},
            }
        },
    )
    world_effects.apply_beat(state, "bad")
    assert state.procgen.npc_by_id("npc_ilya")["location_id"] == "tinker_caravan"


def test_npc_move_for_an_absent_npc_is_survivable(state, monkeypatch):
    monkeypatch.setattr(
        world_effects,
        "load_doom_effects",
        lambda: {
            "bad": {
                "at_progress": 0.1,
                "npc_moves": {"npc_who": "edgewood_square"},
            }
        },
    )
    assert world_effects.apply_beat(state, "bad") == []
    assert state.flags["doom_beat_bad"] is True


# -- persistence and interop ------------------------------------------------


def test_doom_marks_survive_the_world_sim_event_sweep(state):
    """
    The port hazard.

    ``WorldSim.expire_events`` DELETES any world event with no ``expires_day``.
    A straight port of the upstream schema wrote doom marks without one, so
    every permanent mark would vanish on the next day tick.
    """
    state.evil_progress = 0.35
    world_effects.apply_beat(state, "scarecrow_wakes")
    assert state.world_events

    state.world_clock_hours += 24 * 30
    WorldSim.expire_events(state)

    assert any(
        e.get("event_id") == "scarecrow_walks" for e in state.world_events
    ), "doom marks must be permanent"


def test_everything_round_trips_through_a_save(state):
    state.evil_progress = 0.75
    world_effects.apply_pending_beats(state)

    restored = GameState.from_dict(state.to_save_dict())

    assert restored.flags["scarecrow_awake"] is True
    assert restored.flags["discovery_hidden_path"] is True
    assert restored.flags["doom_beat_tunnels_open"] is True
    assert restored.rumors == state.rumors
    assert len(restored.world_events) == len(state.world_events)
    assert (
        restored.procgen.npc_by_id("npc_ilya")["location_id"] == "edgewood_square"
    )
    # And a reload must not re-fire what already happened.
    assert world_effects.pending_beats(restored) == []


def test_doom_signs_reads_back_what_the_dark_did(state):
    state.evil_progress = 0.35
    world_effects.apply_pending_beats(state)
    signs = world_effects.doom_signs(state)
    assert signs
    assert all(isinstance(s, str) and s for s in signs)
