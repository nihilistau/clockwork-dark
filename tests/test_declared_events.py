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

A PROBABILISTIC declared event (v0.25.0 E1, ``probability_per_day``) draws one
number per eligible day crossed, on its own stream (``event.<id>``), so its days
replay from the seed and the days crossed, never from how the day was cut.

Version: v0.1.0 [2026-09-23]
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import pytest
import yaml

from engine.config import set_overlay
from engine.game import clock as clock_module
from engine.game.clock import set_clock
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


# -- probabilistic declared events (v0.25.0 E1, spec §6.1) -------------------------------------------

from engine.game.rng import world_rng  # noqa: E402
from engine.world.world_sim import WorldSim  # noqa: E402

PROBABILISTIC = {
    "rumors": ["The road was longer than the sun said.", "Brass in the well bucket."],
    "events": {
        "caravan_arrival": {
            "probability_per_day": 0.5, "min_day": 2, "duration_days": 2,
            "location_id": "edgewood_square", "npc_ids": ["npc_odran"],
            "rumor_from": "npc_odran", "text": "A cart comes in off the road.",
        },
        "press": {"probability_per_day": 0.4, "when": {"min_awareness": 0},
                  "duration_days": 1, "text": "The levy is read."},
    },
}


def _write(tmp_path: Path, doc: dict) -> Path:
    """
    The schedules file, and NO tiered rumours (a file that is not there: an
    empty `paths.*` falls back to the active story's own), so a rumour is drawn
    from the schedules file's flat list.
    """
    path = tmp_path / "schedules.yaml"
    path.write_text(yaml.safe_dump(doc), encoding="utf-8")
    set_overlay({"paths": {"world_schedules": str(path),
                           "world_rumors": str(tmp_path / "no-tiered-rumours.yaml")}})
    schedules._SCHEDULE_CACHE = None
    return path


@contextmanager
def _quiet_world() -> Iterator[None]:
    """
    The active story's hunger and doom beats held still, so these tests measure
    the declared events alone: hunger's death check adds unconsciousness hours
    (and so days) by how the time was cut, and a doom beat is dated by the call
    that crosses it -- neither is cut-invariant (CLAUDE.md, Deliberately deferred).
    Its own MonkeyPatch, because `_cut` undoes the test's.
    """
    from engine.game import survival
    from engine.world import world_effects

    with pytest.MonkeyPatch.context() as quiet:
        quiet.setattr(survival, "tick", lambda state, hours: {})
        quiet.setattr(world_effects, "apply_pending_beats", lambda state: [])
        yield


@pytest.fixture()
def probabilistic(tmp_path: Path) -> Iterator[Path]:
    try:
        with _quiet_world():
            yield _write(tmp_path, PROBABILISTIC)
    finally:
        schedules._SCHEDULE_CACHE = None
        set_overlay(None)


@pytest.fixture()
def certain(tmp_path: Path) -> Iterator[Path]:
    """One event that always starts once eligible: its eligibility alone decides the days."""
    doc = {"events": {"caravan_arrival": {"probability_per_day": 1.0, "min_day": 1,
                                          "duration_days": 3, "text": "A cart."}}}
    try:
        with _quiet_world():
            yield _write(tmp_path, doc)
    finally:
        schedules._SCHEDULE_CACHE = None
        set_overlay(None)


def _recorder(monkeypatch: pytest.MonkeyPatch) -> list[tuple]:
    """Every event applied, as (id, start day, expiry, rumour), in order."""
    seen: list[tuple] = []
    real = WorldSim.apply_events

    def record(state, events):
        seen.extend((e.event_id, e.day, e.expires_day, e.payload.get("rumor", "")) for e in events)
        return real(state, events)

    monkeypatch.setattr(WorldSim, "apply_events", staticmethod(record))
    return seen


def _cut(monkeypatch, cuts: list[float], *, seed: int = 5, tick: bool = False) -> tuple[list, list]:
    state = GameState(rng_seed=seed)
    seen = _recorder(monkeypatch)
    for hours in cuts:
        if tick:
            WorldSim.on_tick(state, hours=hours)
        else:
            clock_module.advance_time(state, hours)
    monkeypatch.undo()
    # The instances ACTIVE as the cut ends. One that started and ran out inside
    # a single step stays on state until the next expiry (expiry runs before a
    # step's events are added), so the raw list is the cut's, not the days'.
    active = [e for e in state.world_events
              if int(e["day"]) <= state.world_day < int(e["expires_day"])]
    return seen, sorted((str(e["event_id"]), int(e["day"])) for e in active)


CUTS = {
    "one step": [240.0],
    "2h steps": [2.0] * 120,
    "1h steps": [1.0] * 240,
    "mixed": [5.0, 19.0, 48.0, 3.0, 21.0, 72.0, 24.0, 48.0],
}


@pytest.mark.parametrize("name", [n for n in CUTS if n != "one step"])
def test_a_probabilistic_events_days_do_not_depend_on_the_cut(probabilistic, monkeypatch, name) -> None:
    reference = _cut(monkeypatch, CUTS["one step"])
    assert _cut(monkeypatch, CUTS[name]) == reference
    assert any(eid == "caravan_arrival" for eid, *_ in reference[0]), "the seed must draw a caravan"


def test_nor_on_how_the_background_tick_cut_them(probabilistic, monkeypatch) -> None:
    """Through `WorldSim.on_tick` with differing tick counts, which advance the legacy
    `schedule.*` counters by different amounts (spec §12.3): the declared days do not move."""
    reference = _cut(monkeypatch, CUTS["one step"])
    for name in ("2h steps", "mixed"):
        assert _cut(monkeypatch, CUTS[name], tick=True) == reference, name
    few, many = GameState(rng_seed=5), GameState(rng_seed=5)
    WorldSim.on_tick(few, hours=240.0)
    for _ in range(120):
        WorldSim.on_tick(many, hours=2.0)
    assert few.rng_counters.get("schedule.caravan") != many.rng_counters.get("schedule.caravan")


def test_an_event_drawn_in_a_step_is_not_drawn_again_while_active(certain, monkeypatch) -> None:
    seen, _ = _cut(monkeypatch, [24.0 * 9])
    starts = [day for eid, day, *_ in seen if eid == "caravan_arrival"]
    assert starts == [2, 5, 8], starts       # 3-day instances, back to back


def test_one_expiring_inside_a_step_still_blocks_its_last_days(certain, monkeypatch) -> None:
    state = GameState(rng_seed=1)
    WorldSim.apply_events(state, [schedules.SimEvent(event_id="caravan_arrival", day=1, expires_day=4)])
    seen = _recorder(monkeypatch)
    clock_module.advance_time(state, 24.0 * 5)
    assert [day for eid, day, *_ in seen if eid == "caravan_arrival"] == [4]


def test_its_default_stream_is_its_own(certain) -> None:
    state = GameState(rng_seed=1)
    clock_module.advance_time(state, 48.0)
    assert state.rng_counters.get("event.caravan_arrival", 0) >= 1
    assert schedules.event_stream("caravan_arrival", {}) == "event.caravan_arrival"


@pytest.mark.parametrize("stream", sorted(schedules.LEGACY_STREAMS))
def test_a_legacy_stream_is_refused(tmp_path: Path, stream: str) -> None:
    spec = {"probability_per_day": 0.5, "stream": stream}
    assert "legacy" in (schedules.declared_event_problem("caravan_arrival", spec) or "")
    _write(tmp_path, {"events": {"caravan_arrival": spec}})
    try:
        with pytest.raises(ValueError, match="legacy"):
            schedules.load_schedules()
    finally:
        schedules._SCHEDULE_CACHE = None
        set_overlay(None)


@pytest.mark.parametrize("spec, words", [
    ({"probability_per_day": 1.5}, "from 0 to 1"),
    ({"probability_per_day": "often"}, "must be a number"),
    ({"probability_per_day": 0.2, "on_day": 3}, "cannot be combined"),
    ({"stream": "event.x"}, "only with probability_per_day"),
    ({"rumor_from": "npc_odran"}, "only with probability_per_day"),
])
def test_a_malformed_probabilistic_event_is_named(spec: dict, words: str) -> None:
    assert words in (schedules.declared_event_problem("x", spec) or "")


def test_when_gates_it_without_firing_it_once(tmp_path: Path, monkeypatch) -> None:
    from engine.game.effects import apply_effect

    _write(tmp_path, {"events": {"press": {"probability_per_day": 1.0, "when": {"flag": "levy_open"},
                                           "duration_days": 1, "text": "The levy."}}})
    try:
        state = GameState(rng_seed=2)
        _to_day(state, 3)
        assert "press" not in _ids(state)
        apply_effect(state, {"type": "flag", "flag": "levy_open", "value": True})
        seen = _recorder(monkeypatch)
        _to_day(state, 7)
        assert [day for eid, day, *_ in seen if eid == "press"] == [4, 5, 6, 7]
        assert not state.flags.get(f"{schedules.EVENT_FIRED_PREFIX}press")
    finally:
        schedules._SCHEDULE_CACHE = None
        set_overlay(None)


def test_a_forced_declared_event_starts_today_with_no_draw(certain) -> None:
    state = GameState(rng_seed=3)
    _to_day(state, 1)
    state.world_events = []
    before = dict(state.rng_counters)
    events = WorldSim.on_tick(state, hours=0.0, force=["caravan_arrival"])
    assert [(e.event_id, e.day) for e in events] == [("caravan_arrival", state.world_day)]
    assert state.rng_counters.get("event.caravan_arrival", 0) == before.get("event.caravan_arrival", 0)


def test_a_forced_event_with_a_rumour_draws_only_the_rumour(probabilistic) -> None:
    state = GameState(rng_seed=3)
    set_clock(state, day=2, hour=8)          # its min_day, with no day rolled (no draw)
    events = WorldSim.on_tick(state, hours=0.0, force=["caravan_arrival"])
    assert events and events[-1].payload.get("rumor") in PROBABILISTIC["rumors"]
    assert state.rng_counters.get("event.caravan_arrival") == 1


def test_an_event_with_no_probability_takes_the_old_path(declared) -> None:
    """The fire-once `when:` form and fixed days are byte-for-byte as before: no stream drawn."""
    state = GameState(rng_seed=1)
    _to_day(state, 8)
    assert not any(k.startswith("event.") for k in state.rng_counters)


def test_a_death_checks_own_hours_roll_their_days_once_and_in_order(certain, monkeypatch) -> None:
    """The death check's re-entry (unconsciousness hours) crosses days of its own:
    the OUTER call rolls them with its own, once and in order (v0.25.0 E1)."""
    from engine.game import encounter

    state = GameState(rng_seed=1)
    fell: list[int] = []

    def falls_once(st) -> None:
        if not fell:
            fell.append(st.world_day)
            clock_module.advance_time(st, 48.0)

    monkeypatch.setattr(encounter, "check_death", falls_once)
    seen = _recorder(monkeypatch)
    clock_module.advance_time(state, 24.0)
    assert fell and state.world_day == 4
    assert [day for eid, day, *_ in seen if eid == "caravan_arrival"] == [2]


def test_the_flagship_declares_its_three_events_on_their_own_streams() -> None:
    from engine.games import registry

    registry.activate("clockwork-dark")
    try:
        doc = schedules.load_schedules()
        for event_id in ("caravan_arrival", "tinker_camp", "militia_press"):
            assert event_id not in doc, f"{event_id} is still a legacy slot"
            spec = doc["events"][event_id]
            assert 0.0 < float(spec["probability_per_day"]) < 1.0
            assert schedules.event_stream(event_id, spec) == f"event.{event_id}"
            assert "goods" not in spec
    finally:
        registry.deactivate()


def test_a_forced_event_still_keeps_its_gates(probabilistic) -> None:
    """Force skips the draw, never `min_day` or `when:` (the legacy slots' meaning)."""
    early = GameState(rng_seed=3)                      # day 1, the caravan's min_day is 2
    assert WorldSim.on_tick(early, hours=0.0, force=["caravan_arrival"]) == []
    assert "caravan_arrival" not in _ids(early)



def _validator_issues(tmp_path: Path, events: dict) -> list[str]:
    """Every validator ERROR for dev-story with its schedules file swapped for `events`."""
    from engine.games import registry, validation

    sched = tmp_path / "schedules.yaml"
    sched.write_text(yaml.safe_dump({"events": events}), encoding="utf-8")
    manifest = registry.get("dev-story")
    paths = {**manifest.paths, "world_schedules": str(sched)}
    patched = type(manifest)(**{**manifest.__dict__, "paths": paths})
    return [f"{i.source}|{i.ref_id}|{i.message}"
            for i in validation.errors_only(validation.validate_story(patched))]


def test_the_validator_names_a_bad_probabilistic_event_and_passes_a_good_one(tmp_path: Path) -> None:
    """`validation.check_declared_events`: the shared problem, as an Issue on the
    schedules file and the event's id; a well-formed event reports nothing."""
    issues = _validator_issues(tmp_path, {
        "levy": {"probability_per_day": 0.2, "stream": "schedule.militia", "text": "x"},
        "market": {"probability_per_day": 0.3, "min_day": 2, "duration_days": 1, "text": "y"},
    })
    mine = [i for i in issues if "|levy|" in i or "|market|" in i]
    assert len(mine) == 1, issues
    assert mine[0].split("|")[0].endswith("schedules.yaml") and "|levy|" in mine[0]
    assert "legacy" in mine[0]
    clean = _validator_issues(tmp_path, {
        "market": {"probability_per_day": 0.3, "min_day": 2, "duration_days": 1, "text": "y"}})
    assert not [i for i in clean if "|market|" in i], clean
