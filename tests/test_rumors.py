"""Awareness-gated rumour selection tests."""

from __future__ import annotations

import random

import pytest

from engine.game.clock import set_clock
from engine.game.procgen import new_game_state
from engine.game.rng import SCHEDULE_CARAVAN, world_rng
from engine.game.state import EvilPhase, GameState
from engine.world import schedules
from engine.world.world_sim import WorldSim


def _state(awareness: float = 0.0, *, seed: int = 42) -> GameState:
    state = new_game_state(seed=seed)
    # new_game_state() seeds procgen but leaves state.rng_seed at 0, so every
    # world_rng stream currently replays identically across sessions. Set it
    # here so these tests actually vary; see the note in the phase report.
    state.rng_seed = seed
    set_clock(state, day=6, hour=8)
    state.awareness = awareness
    return state


def _tiers(entries) -> set[int]:
    return {int(e.get("tier", 1)) for e in entries}


# ---------------------------------------------------------------------------
# Content shape
# ---------------------------------------------------------------------------


def test_rumor_file_covers_all_three_tiers():
    rumors = schedules.load_rumors().get("rumors", [])
    assert len(rumors) >= 24
    assert _tiers(rumors) == {1, 2, 3}


def test_every_rumor_has_id_text_and_gate():
    seen_ids = set()
    for entry in schedules.load_rumors().get("rumors", []):
        assert entry["id"] not in seen_ids, entry["id"]
        seen_ids.add(entry["id"])
        assert str(entry["text"]).strip()
        assert int(entry["tier"]) in (1, 2, 3)
        assert int(entry["min_awareness"]) >= 0


def test_tier_gates_are_consistent():
    """Tier is the promise; min_awareness is the enforcement. They must agree."""
    expected = {1: 0, 2: 20, 3: 45}
    for entry in schedules.load_rumors().get("rumors", []):
        assert entry["min_awareness"] == expected[int(entry["tier"])], entry["id"]


# ---------------------------------------------------------------------------
# Awareness gating
# ---------------------------------------------------------------------------


def test_low_awareness_hears_only_unease():
    eligible = schedules.eligible_rumors(_state(awareness=5.0))
    assert eligible
    assert _tiers(eligible) == {1}


def test_no_tier_three_rumor_at_awareness_five():
    """A player who has noticed nothing must not be handed the pattern."""
    for _ in range(50):
        text = schedules.pick_rumor(_state(awareness=5.0), random.Random(_))
        assert text in {
            e["text"] for e in schedules.load_rumors()["rumors"] if e["tier"] == 1
        }


def test_tier_two_unlocks_at_twenty():
    assert _tiers(schedules.eligible_rumors(_state(awareness=19.0))) == {1}
    assert _tiers(schedules.eligible_rumors(_state(awareness=20.0))) == {1, 2}


def test_tier_three_available_at_awareness_sixty():
    eligible = schedules.eligible_rumors(_state(awareness=60.0))
    assert 3 in _tiers(eligible)

    drawn = {schedules.pick_rumor(_state(awareness=60.0), random.Random(i)) for i in range(60)}
    tier_three = {e["text"] for e in schedules.load_rumors()["rumors"] if e["tier"] == 3}
    assert drawn & tier_three, "high Awareness must actually surface specifics"


def test_high_awareness_prefers_the_higher_tiers():
    """Otherwise Awareness moves and the player never hears the difference."""
    tier_one = {e["text"] for e in schedules.load_rumors()["rumors"] if e["tier"] == 1}
    draws = [schedules.pick_rumor(_state(awareness=60.0), random.Random(i)) for i in range(200)]
    unease = sum(1 for d in draws if d in tier_one)
    assert unease < len(draws) / 2


def test_phase_gates_a_rumor_that_has_not_happened_yet():
    dormant = _state(awareness=100.0)
    assert dormant.evil_phase is EvilPhase.DORMANT
    assert "orders_predated" not in {e["id"] for e in schedules.eligible_rumors(dormant)}

    spreading = _state(awareness=100.0)
    spreading.evil_progress = 0.6
    spreading.evil_phase = EvilPhase.SPREADING
    assert "orders_predated" in {e["id"] for e in schedules.eligible_rumors(spreading)}


def test_source_npc_is_a_preference_not_a_filter():
    """A speaker with no attributed rumour must not be struck mute."""
    state = _state(awareness=0.0)
    text = schedules.pick_rumor(state, random.Random(1), source_npc="npc_sera")
    assert text
    assert text != schedules.load_rumors()["fallback"]


def test_source_npc_is_honoured_when_it_can_be():
    state = _state(awareness=60.0)
    drawn = {
        schedules.pick_rumor(state, random.Random(i), source_npc="npc_odran")
        for i in range(30)
    }
    odran = {
        e["text"]
        for e in schedules.load_rumors()["rumors"]
        if e.get("source_npc") == "npc_odran"
    }
    assert drawn <= odran


def test_pick_rumor_replays_from_the_same_seed():
    state = _state(awareness=60.0)
    a = [schedules.pick_rumor(state, random.Random(11)) for _ in range(3)]
    b = [schedules.pick_rumor(state, random.Random(11)) for _ in range(3)]
    assert a == b


# ---------------------------------------------------------------------------
# Fallback
# ---------------------------------------------------------------------------


def test_falls_back_to_the_flat_list_when_rumors_yaml_is_absent(monkeypatch, tmp_path):
    monkeypatch.setattr(schedules, "_rumors_path", lambda: tmp_path / "absent.yaml")
    schedules.reset_rumor_cache()
    try:
        assert schedules.eligible_rumors(_state(awareness=90.0)) == []
        text = schedules.pick_rumor(_state(awareness=90.0), random.Random(3))
        assert text in schedules.load_schedules()["rumors"]
    finally:
        schedules.reset_rumor_cache()


def test_falls_back_to_a_line_when_nothing_at_all_is_configured(monkeypatch, tmp_path):
    monkeypatch.setattr(schedules, "_rumors_path", lambda: tmp_path / "absent.yaml")
    schedules.reset_rumor_cache()
    try:
        text = schedules.pick_rumor(
            _state(awareness=90.0), random.Random(3), schedules={}
        )
        assert text == "The village mutters, but nothing clear reaches you."
    finally:
        schedules.reset_rumor_cache()


def test_legacy_shim_without_state_uses_the_flat_list():
    text = schedules._pick_rumor(random.Random(5), schedules.load_schedules())
    assert text in schedules.load_schedules()["rumors"]


# ---------------------------------------------------------------------------
# Integration
# ---------------------------------------------------------------------------


def test_caravan_still_carries_a_rumor():
    state = _state(awareness=0.0)
    events = WorldSim.on_tick(state, hours=0, force=["caravan_arrival"])
    assert len(events) == 1
    assert events[0].payload["rumor"]
    assert state.rumors == [events[0].payload["rumor"]]


def test_caravan_rumor_quality_tracks_awareness():
    tier_three = {e["text"] for e in schedules.load_rumors()["rumors"] if e["tier"] == 3}

    low = _state(awareness=0.0)
    WorldSim.on_tick(low, hours=0, force=["caravan_arrival"])
    assert low.rumors[0] not in tier_three

    high = _state(awareness=80.0)
    seen = set()
    for seed in range(40):
        state = _state(awareness=80.0, seed=seed)
        seen.add(
            schedules.pick_rumor(
                state, world_rng(state, SCHEDULE_CARAVAN), source_npc="npc_odran"
            )
        )
    assert seen & tier_three
    assert high.awareness > low.awareness


@pytest.mark.parametrize("awareness", [0.0, 10.0, 25.0, 50.0, 100.0])
def test_a_rumor_is_always_available(awareness: float):
    text = schedules.pick_rumor(_state(awareness=awareness), random.Random(0))
    assert text and text.strip()
