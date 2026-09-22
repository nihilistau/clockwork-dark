"""
A story can declare its own world events.

THE GAP. ``engine/world/schedules.py`` could fire exactly three events, each a
hardcoded flagship id with its own roll function: ``caravan_arrival``,
``tinker_camp``, ``militia_press``. Every other story's ``world_schedules`` file
could declare rumours and nothing that HAPPENS. And the flagship's own procgen
generated a festival per seed -- a name, a season, a day -- that nothing ever
read.

THE SHAPE. An ``events:`` block in the story's ``world_schedules`` file. Each
event fires on a fixed day (``on_day``), on a cadence (``every_days``, from
``first_day``), or on the first rolled day a ``when:`` predicate holds. They
fire from ``advance_time``'s day-roll branch and use NO randomness, so whether
the Hanging Fair has started replays from the seed and the choices -- never
from how long the menu was open (the background tick is wall-clock, R-03).

Probabilistic declared events are deliberately out of scope: NOT WIRED, see
docs/GOVERNANCE.md.

Version: v0.1.0 [2026-09-23]
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

import pytest
import yaml

from engine.config import set_overlay
from engine.game import clock as clock_module
from engine.game.state import GameState
from engine.world import schedules

EVENTS = {
    "events": {
        "hanging_fair": {
            "on_day": 3,
            "location_id": "gallows_green",
            "duration_days": 1,
            "npc_ids": ["npc_ardane"],
            "text": "Gallows Green fills with bunting, pie-sellers and a scaffold.",
        },
        "market_day": {
            "every_days": 2,
            "first_day": 2,
            "location_id": "wickmarket",
            "duration_days": 1,
            "text": "Wickmarket is loud with stalls.",
        },
        "curfew": {
            "when": {"flag": "curfew_called"},
            "text": "Lanterns out at ten, by order of the Watch.",
        },
    }
}


@pytest.fixture()
def declared(tmp_path: Path) -> Iterator[Path]:
    path = tmp_path / "schedules.yaml"
    path.write_text(yaml.safe_dump(EVENTS), encoding="utf-8")
    set_overlay({"paths": {"world_schedules": str(path)}})
    schedules._SCHEDULE_CACHE = None
    try:
        yield path
    finally:
        schedules._SCHEDULE_CACHE = None
        set_overlay(None)


def _ids(state: GameState) -> list[str]:
    return [str(e.get("event_id")) for e in state.world_events]


def _to_day(state: GameState, day: int) -> None:
    while state.world_day < day:
        clock_module.advance_time(state, 24)


def test_a_fixed_day_event_starts_on_its_day(declared) -> None:
    state = GameState(rng_seed=1)
    _to_day(state, 2)
    assert "hanging_fair" not in _ids(state)
    _to_day(state, 3)
    assert "hanging_fair" in _ids(state)
    event = next(e for e in state.world_events if e["event_id"] == "hanging_fair")
    assert "bunting" in event["payload"]["text"]


def test_it_reaches_the_narrator_on_the_turn_it_starts(declared) -> None:
    state = GameState(rng_seed=1)
    _to_day(state, 3)
    assert any("bunting" in e["text"] for e in state.moved if e["kind"] == "event")


def test_it_ends_when_its_window_closes(declared) -> None:
    """Expiry runs on the day roll too; the wall-clock tick alone let it linger."""
    state = GameState(rng_seed=1)
    _to_day(state, 3)
    _to_day(state, 5)
    assert "hanging_fair" not in _ids(state)


def test_a_cadence_event_recurs(declared) -> None:
    state = GameState(rng_seed=1)
    starts: list[int] = []
    for day in range(2, 9):
        _to_day(state, day)
        if any(e["event_id"] == "market_day" and e["day"] == day for e in state.world_events):
            starts.append(day)
    assert starts == [2, 4, 6, 8]


def test_a_predicate_event_fires_once_when_it_first_holds(declared) -> None:
    from engine.game.effects import apply_effect

    state = GameState(rng_seed=1)
    _to_day(state, 2)
    assert "curfew" not in _ids(state)
    apply_effect(state, {"type": "flag", "flag": "curfew_called", "value": True})
    _to_day(state, 3)
    assert _ids(state).count("curfew") == 1
    _to_day(state, 6)
    assert sum(1 for e in state.moved if "Lanterns out" in e["text"]) <= 1


def test_the_same_seed_starts_the_same_events(declared) -> None:
    def run() -> list[tuple[str, int]]:
        state = GameState(rng_seed=9)
        _to_day(state, 8)
        return sorted((str(e["event_id"]), int(e["day"])) for e in state.world_events)

    assert run() == run()


def test_a_story_that_declares_none_is_untouched(tmp_path: Path) -> None:
    path = tmp_path / "schedules.yaml"
    path.write_text(yaml.safe_dump({"rumors": []}), encoding="utf-8")
    set_overlay({"paths": {"world_schedules": str(path)}})
    schedules._SCHEDULE_CACHE = None
    try:
        state = GameState(rng_seed=1)
        _to_day(state, 6)
        assert state.world_events == []
    finally:
        schedules._SCHEDULE_CACHE = None
        set_overlay(None)


def test_the_flagship_festival_fires_on_its_day() -> None:
    """procgen generated {name, season, day_offset} per seed and nothing read it."""
    from engine.games import registry
    from engine.scenes.default_state import SessionStore

    registry.activate("clockwork-dark")
    session = SessionStore().create(seed=42, llm_fn=lambda messages, **kw: "{}")
    state = session.engine.state
    festival = state.procgen.festival
    assert festival.get("name") and festival.get("day_offset")
    _to_day(state, int(festival["day_offset"]))
    assert "festival" in _ids(state)
    event = next(e for e in state.world_events if e["event_id"] == "festival")
    assert festival["name"] in event["payload"]["text"]
