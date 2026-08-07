"""WorldSim and trader schedule tests."""

from __future__ import annotations

import json

import engine.skills.builtin.mechanics  # noqa: F401 — register skills
from engine.game.clock import set_clock
from engine.game.engine import GameEngine, set_active_engine
from engine.game.procgen import new_game_state
from engine.game.rng import SCHEDULE_CARAVAN, world_rng
from engine.skills.registry import SKILL_REGISTRY
from engine.world.schedules import ScheduleRoll, load_schedules
from engine.world.world_sim import WorldSim, merge_npcs_at_location, visiting_npcs_at_location

DAY = 24.0


def _engine(day: int = 6, *, awareness: float = 0.0, seed: int = 42) -> GameEngine:
    state = new_game_state(seed=seed)
    set_clock(state, day=day, hour=8)
    state.awareness = awareness
    return GameEngine(state)


def test_schedules_load():
    schedules = load_schedules()
    assert "caravan_arrival" in schedules
    assert len(schedules.get("rumors", [])) >= 3


def test_caravan_blocked_before_day_5():
    engine = _engine(day=4)
    events = WorldSim.on_tick(
        engine.state,
        hours=0,
        force=["caravan_arrival"],
    )
    assert events == []


def test_caravan_forced_tick():
    engine = _engine(day=6)
    result = engine.advance_world_day(days=1, force_events=["caravan_arrival"])
    assert len(result["events"]) == 1
    assert result["events"][0]["event_id"] == "caravan_arrival"
    assert result["events"][0]["npc_ids"] == ["npc_odran"]
    assert len(result["rumors"]) == 1
    assert engine.state.world_events[0]["event_id"] == "caravan_arrival"


def test_tinker_forced_tick():
    engine = _engine(day=10)
    events = WorldSim.on_tick(engine.state, hours=DAY, force=["tinker_camp"])
    assert len(events) == 1
    assert events[0].event_id == "tinker_camp"
    assert events[0].location_id == "tinker_caravan"


def test_militia_requires_awareness():
    engine = _engine(day=10, awareness=10.0)
    events = WorldSim.on_tick(engine.state, force=["militia_press"])
    assert events == []

    engine.state.awareness = 25.0
    events = WorldSim.on_tick(engine.state, force=["militia_press"])
    assert len(events) == 1
    assert events[0].event_id == "militia_press"


def test_on_tick_advances_evil():
    engine = _engine(day=6)
    before = engine.state.evil_progress
    WorldSim.on_tick(engine.state, hours=2 * DAY)
    assert engine.state.world_day == 8
    assert engine.state.evil_progress > before


def test_fractional_tick_advances_evil():
    """
    The regression that proves the core premise works.

    A quarter-day tick used to be truncated to zero days by an int() cast, so
    neither the calendar nor the evil clock ever moved in normal play.
    """
    engine = _engine(day=1)
    before_progress = engine.state.evil_progress
    before_clock = engine.state.world_clock_hours

    WorldSim.on_tick(engine.state, hours=6.0)

    assert engine.state.world_clock_hours == before_clock + 6.0
    assert engine.state.evil_progress > before_progress


def test_repeated_fractional_ticks_roll_the_day():
    engine = _engine(day=1)
    for _ in range(4):
        WorldSim.on_tick(engine.state, hours=6.0)
    assert engine.state.world_day == 2
    assert engine.state.world_hour == 8


def test_visiting_npc_merge():
    engine = _engine(day=6)
    engine.advance_world_day(days=1, force_events=["caravan_arrival"])
    visitors = visiting_npcs_at_location(engine.state, "edgewood_square")
    assert any(v["id"] == "npc_odran" for v in visitors)
    merged = merge_npcs_at_location(engine.state, "edgewood_square")
    odran_entries = [n for n in merged if n.get("id") == "npc_odran"]
    assert len(odran_entries) == 1
    assert odran_entries[0].get("visiting") is True


def test_advance_world_tick_skill_force():
    engine = _engine(day=7)
    set_active_engine(engine)
    raw = SKILL_REGISTRY.invoke(
        "advance_world_tick",
        days=1.0,
        force_event="caravan_arrival",
    )
    data = json.loads(raw)
    assert data["events"][0]["event_id"] == "caravan_arrival"
    assert data["rumors"]


def test_world_tick_rejects_negative_days():
    """One tool call must not be able to rewind the calendar."""
    engine = _engine(day=7)
    try:
        engine.advance_world_day(days=-5.0)
    except ValueError:
        pass
    else:
        raise AssertionError("negative days should raise")
    assert engine.state.world_day == 7


def test_world_tick_is_bounded():
    """Nor jump straight to the endgame phase."""
    engine = _engine(day=1)
    engine.advance_world_day(days=100000.0)
    assert engine.state.world_day <= 1 + 30


def test_events_expire():
    engine = _engine(day=6)
    WorldSim.on_tick(engine.state, hours=DAY, force=["caravan_arrival"])
    assert engine.state.world_events
    set_clock(engine.state, day=20, hour=8)
    WorldSim.expire_events(engine.state)
    assert engine.state.world_events == []


def test_event_lifetime_is_exact():
    """
    A two-day event created on day 6 is gone once the clock reads day 8.

    The old comparison kept it alive on day 8 as well -- three days of life
    for a two-day duration.
    """
    engine = _engine(day=6)
    WorldSim.on_tick(engine.state, hours=0, force=["caravan_arrival"])
    assert engine.state.world_events

    set_clock(engine.state, day=7, hour=8)
    WorldSim.expire_events(engine.state)
    assert engine.state.world_events, "should still be active on day 7"

    set_clock(engine.state, day=8, hour=8)
    WorldSim.expire_events(engine.state)
    assert engine.state.world_events == []


def test_malformed_event_does_not_live_forever():
    engine = _engine(day=6)
    engine.state.world_events = [{"event_id": "bogus"}]
    WorldSim.expire_events(engine.state)
    assert engine.state.world_events == []


def test_realtime_tick_interval():
    assert WorldSim.should_run_realtime_tick(0.0, now=100.0) is True
    assert WorldSim.should_run_realtime_tick(100.0, now=120.0) is False
    assert WorldSim.should_run_realtime_tick(100.0, now=200.0) is True


def test_schedule_roll_no_duplicate_caravan():
    engine = _engine(day=6)
    WorldSim.on_tick(engine.state, force=["caravan_arrival"])
    second = ScheduleRoll.check_caravan(
        engine.state,
        world_rng(engine.state, SCHEDULE_CARAVAN),
        force=True,
    )
    assert second == []


def test_schedule_rng_is_not_frozen():
    """
    Consecutive draws must differ.

    The old generator was keyed on world_day alone and rebuilt each tick, so
    every tick produced the identical first float -- the caravan either never
    came or came every tick, decided at world generation.
    """
    engine = _engine(day=6)
    draws = [world_rng(engine.state, SCHEDULE_CARAVAN).random() for _ in range(5)]
    assert len(set(draws)) == 5


def test_new_game_seeds_the_rng_streams():
    """
    The seed the world was built from must reach the runtime RNG.

    It did not: rng_seed stayed at its 0 default, so every session drew the
    same schedule, dice and encounter sequence no matter what seed the player
    picked. This assertion has to come first, because without it the two tests
    below pass vacuously by comparing two identically-unseeded states.
    """
    assert _engine(seed=1).state.rng_seed == 1
    assert _engine(seed=999999).state.rng_seed == 999999


def test_schedule_rng_replays_from_seed():
    a = _engine(day=6, seed=99).state
    b = _engine(day=6, seed=99).state
    assert a.rng_seed == 99, "guard: a zero seed would make this test meaningless"
    assert [world_rng(a, SCHEDULE_CARAVAN).random() for _ in range(3)] == [
        world_rng(b, SCHEDULE_CARAVAN).random() for _ in range(3)
    ]


def test_different_seeds_draw_differently():
    """The other half of the property, and the half that was actually broken."""
    a = _engine(day=6, seed=1).state
    b = _engine(day=6, seed=999999).state
    assert [world_rng(a, SCHEDULE_CARAVAN).random() for _ in range(3)] != [
        world_rng(b, SCHEDULE_CARAVAN).random() for _ in range(3)
    ]


def test_streams_are_independent():
    """Adding a roll on one stream must not shift another's sequence."""
    a = _engine(seed=7).state
    b = _engine(seed=7).state

    baseline = [world_rng(a, SCHEDULE_CARAVAN).random() for _ in range(3)]

    world_rng(b, "encounter").random()
    world_rng(b, "encounter").random()
    shifted = [world_rng(b, SCHEDULE_CARAVAN).random() for _ in range(3)]

    assert baseline == shifted
