"""NPC routine, presence and precedence tests."""

from __future__ import annotations

import pytest

from engine.game.clock import set_clock
from engine.game.locations import CANONICAL_LOCATION_IDS
from engine.game.procgen import new_game_state
from engine.game.state import GameState
from engine.world import npc_sim
from engine.world.world_sim import WorldSim, merge_npcs_at_location

CANON_NPCS = ("npc_maris", "npc_odran", "npc_ilya", "npc_sera", "npc_brindle")


def _state(*, day: int = 2, hour: int = 8, seed: int = 42) -> GameState:
    state = new_game_state(seed=seed)
    set_clock(state, day=day, hour=hour)
    return state


# ---------------------------------------------------------------------------
# Routines
# ---------------------------------------------------------------------------


def test_maris_sells_in_the_square_at_noon():
    presence = npc_sim.resolve_npc(_state(hour=12), "npc_maris")
    assert presence is not None
    assert presence.location_id == "edgewood_square"
    assert presence.available is True
    assert presence.activity


def test_maris_is_asleep_in_the_bakery_at_two():
    """The bug this module exists for: she used to be baking at 02:00."""
    presence = npc_sim.resolve_npc(_state(hour=2), "npc_maris")
    assert presence is not None
    assert presence.location_id == "edgewood_bakery"
    assert presence.available is False
    assert "asleep" in presence.activity


def test_sleepers_are_still_listed_as_present():
    """A dark bakery with a sleeping baker in it is a scene; an empty one is not."""
    ids = [n["id"] for n in merge_npcs_at_location(_state(hour=2), "edgewood_bakery")]
    assert "npc_maris" in ids


def test_brindle_is_findable_at_the_start():
    """
    forest_clearing is where every run begins and had nobody in it at all.

    The default clock (day 1, 08:00) must find the cat there.
    """
    state = new_game_state(seed=7)
    assert state.location_id == "forest_clearing"
    assert (state.world_day, state.world_hour) == (1, 8)

    present = merge_npcs_at_location(state, "forest_clearing")
    assert [n["id"] for n in present] == ["npc_brindle"]
    assert present[0]["activity"]


def test_brindle_roams_across_the_day():
    state = _state()
    seen = set()
    for hour in range(24):
        set_clock(state, day=2, hour=hour)
        presence = npc_sim.resolve_npc(state, "npc_brindle")
        assert presence is not None
        seen.add(presence.location_id)
    assert len(seen) > 1, "a roaming cat that never leaves is not roaming"


@pytest.mark.parametrize("npc_id", CANON_NPCS)
def test_canon_npcs_cover_every_hour(npc_id: str):
    """No hour may fall through to the procgen home with no activity."""
    state = _state()
    for hour in range(24):
        set_clock(state, day=2, hour=hour)
        presence = npc_sim.resolve_npc(state, npc_id)
        assert presence is not None, f"{npc_id} unresolved at {hour:02d}:00"
        assert presence.location_id, f"{npc_id} has no location at {hour:02d}:00"
        assert presence.activity, f"{npc_id} has no activity at {hour:02d}:00"


def test_routines_stay_on_the_canonical_map():
    data = npc_sim.load_npc_schedules()
    for npc_id, cfg in (data.get("npcs") or {}).items():
        assert cfg.get("home") in CANONICAL_LOCATION_IDS, npc_id
        for slot in cfg.get("routine", []):
            assert slot["location"] in CANONICAL_LOCATION_IDS, (npc_id, slot)


def test_procedural_villagers_get_role_activities():
    """Otherwise the square renders as a wall of identical villager lines."""
    present = merge_npcs_at_location(_state(hour=10), "edgewood_square")
    villagers = [n for n in present if n["id"].startswith("npc_villager_")]
    assert villagers
    assert all(v["activity"] for v in villagers)


def test_resolution_is_idempotent():
    """prompts.py resolves every turn; it must never consume RNG or drift."""
    state = _state(hour=15)
    before = dict(state.rng_counters)
    first = [n["activity"] for n in merge_npcs_at_location(state, "edgewood_square")]
    second = [n["activity"] for n in merge_npcs_at_location(state, "edgewood_square")]
    assert first == second
    assert state.rng_counters == before


def test_unknown_npc_resolves_to_none():
    assert npc_sim.resolve_npc(_state(), "npc_nobody") is None


# ---------------------------------------------------------------------------
# Precedence
# ---------------------------------------------------------------------------


def test_event_overrides_routine():
    """A caravan puts Odran in the square at an hour his routine has him elsewhere."""
    state = _state(day=6, hour=6)
    assert npc_sim.resolve_npc(state, "npc_odran").location_id == "millhaven_gate"

    WorldSim.on_tick(state, hours=0, force=["caravan_arrival"])
    set_clock(state, day=6, hour=6)

    presence = npc_sim.resolve_npc(state, "npc_odran")
    assert presence.location_id == "edgewood_square"
    assert presence.visiting is True
    assert presence.event_id == "caravan_arrival"
    assert presence.available is True


def test_event_npc_is_not_duplicated():
    state = _state(day=6, hour=10)
    WorldSim.on_tick(state, hours=0, force=["caravan_arrival"])
    set_clock(state, day=6, hour=10)

    merged = merge_npcs_at_location(state, "edgewood_square")
    odran = [n for n in merged if n["id"] == "npc_odran"]
    assert len(odran) == 1
    assert odran[0]["visiting"] is True


def test_merge_keeps_procgen_fields():
    merged = merge_npcs_at_location(_state(hour=12), "edgewood_square")
    maris = next(n for n in merged if n["id"] == "npc_maris")
    assert maris["name"] == "Maris Hearth"
    assert maris["role"] == "baker"
    assert maris["canon"] is True
    assert maris["traits"]
    assert maris["activity"]
    assert maris["available"] is True


def test_state_override_moves_an_npc():
    state = _state(hour=2)
    state.flags["npc_at_npc_maris"] = "forest_clearing"
    presence = npc_sim.resolve_npc(state, "npc_maris")
    assert presence.location_id == "forest_clearing"
    assert "asleep" not in presence.activity, "relocated NPCs keep no stale activity"


def test_quest_pin_beats_a_world_event():
    state = _state(day=6, hour=10)
    WorldSim.on_tick(state, hours=0, force=["caravan_arrival"])
    set_clock(state, day=6, hour=10)
    state.flags["npc_pin_npc_odran"] = "forest_clearing"

    presence = npc_sim.resolve_npc(state, "npc_odran")
    assert presence.location_id == "forest_clearing"
    assert presence.available is True


def test_boolean_pin_holds_an_npc_at_home():
    state = _state(hour=12)
    state.flags["npc_pin_npc_maris"] = True
    assert npc_sim.resolve_npc(state, "npc_maris").location_id == "edgewood_bakery"


# ---------------------------------------------------------------------------
# refresh()
# ---------------------------------------------------------------------------


def test_refresh_expires_a_dated_pin():
    state = _state(day=5, hour=10)
    state.flags["npc_pin_npc_sera"] = "edgewood_square"
    state.flags["npc_pin_npc_sera_until_day"] = 4

    npc_sim.refresh(state)

    assert "npc_pin_npc_sera" not in state.flags
    assert "npc_pin_npc_sera_until_day" not in state.flags
    assert npc_sim.resolve_npc(state, "npc_sera").location_id == "millhaven_gate"


def test_refresh_keeps_a_live_pin_and_is_idempotent():
    state = _state(day=5, hour=10)
    state.flags["npc_pin_npc_sera"] = "edgewood_square"
    state.flags["npc_pin_npc_sera_until_day"] = 9

    for _ in range(3):
        npc_sim.refresh(state)

    assert state.flags["npc_pin_npc_sera"] == "edgewood_square"
    assert npc_sim.resolve_npc(state, "npc_sera").location_id == "edgewood_square"


def test_refresh_survives_an_empty_state():
    npc_sim.refresh(GameState())


def test_missing_schedule_file_falls_back_to_procgen_homes(monkeypatch, tmp_path):
    monkeypatch.setattr(npc_sim, "_schedules_path", lambda: tmp_path / "absent.yaml")
    npc_sim.reset_schedule_cache()
    try:
        presence = npc_sim.resolve_npc(_state(hour=2), "npc_maris")
        assert presence.location_id == "edgewood_bakery"
    finally:
        npc_sim.reset_schedule_cache()
