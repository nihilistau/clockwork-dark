"""
Behaviour and the event queue (v0.22.0 spec §5, §9.1; T5).

`clock.advance_time` walks `state.social["queue"]` for a story declaring
`paths.social`, in `(at, seq)` order, bounded; a person's week is derived and
draws nothing; one person's draws never shift another's. `social_profile`
queues the first `daily` (pid ""), so every test here asserts on its OWN
events (pre-flight F5).
"""

from __future__ import annotations

import copy
import logging
import shutil
from pathlib import Path

import pytest

from tests.social_fixtures import receipts_active, receipts_state  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]
SOCIAL_DIR = ROOT / "games" / "read-receipts" / "data" / "social"

TWELVE = ("romantic", "slow_burner", "banterer", "dry_texter", "needy", "ghoster",
          "breadcrumber", "drifter", "turner", "steady", "busy", "night_owl")


def test_events_apply_in_at_then_seq_order(receipts_state) -> None:
    from engine.game import clock
    from engine.social import events

    seen: list[str] = []
    events.handles("probe")(lambda state, ev: seen.append(ev["tag"]) or {"ok": True})
    try:
        now = receipts_state.world_clock_hours
        events.push(receipts_state, now + 1.0, "p0001", "probe", tag="b")
        events.push(receipts_state, now + 0.5, "p0002", "probe", tag="a")
        events.push(receipts_state, now + 1.0, "p0003", "probe", tag="c")   # same at as b: seq decides
        clock.advance_time(receipts_state, 2.0)
        assert seen == ["a", "b", "c"]
        # Only this test's events: the creation's first `daily` (pid "") is queued too (F5).
        assert [e for e in receipts_state.social["queue"] if e["kind"] == "probe"] == []
    finally:
        events._HANDLERS.pop("probe", None)


def test_an_event_due_later_stays_queued(receipts_state) -> None:
    from engine.game import clock
    from engine.social import events

    now = receipts_state.world_clock_hours
    events.push(receipts_state, now + 5.0, "p0001", "probe")     # never due here, so no handler is needed
    clock.advance_time(receipts_state, 1.0)
    mine = [e for e in receipts_state.social["queue"] if e["pid"] == "p0001"]
    assert [e["kind"] for e in mine] == ["probe"]                # the first `daily` (pid "") is not ours (F5)


def test_the_advance_is_bounded(receipts_state, monkeypatch, caplog) -> None:
    from engine.game import clock
    from engine.social import events

    events.handles("echo")(lambda state, ev: events.push(state, ev["at"], ev["pid"], "echo") and {"ok": True})
    try:
        monkeypatch.setattr(events, "_max_events", lambda: 50)
        events.push(receipts_state, receipts_state.world_clock_hours + 0.1, "p0001", "echo")
        clock.advance_time(receipts_state, 1.0)
        assert "max_events_per_advance" in caplog.text
    finally:
        events._HANDLERS.pop("echo", None)


def test_a_failing_handler_costs_its_event_never_the_rest_of_the_pass(receipts_state, caplog) -> None:
    """Final review M2: one raising handler is logged at ERROR and dropped; the pass goes on, the clock moved."""
    from engine.game import clock
    from engine.social import events

    seen: list[str] = []

    def _boom(state, ev):
        raise KeyError("a broken row")

    events.handles("boom")(_boom)
    events.handles("probe")(lambda state, ev: seen.append(ev["tag"]) or {"ok": True})
    try:
        now = receipts_state.world_clock_hours
        events.push(receipts_state, now + 0.5, "p0001", "boom")
        events.push(receipts_state, now + 1.0, "p0002", "probe", tag="after")
        with caplog.at_level(logging.ERROR):
            clock.advance_time(receipts_state, 2.0)
        assert seen == ["after"]
        assert receipts_state.world_clock_hours == pytest.approx(now + 2.0)
        assert [e for e in receipts_state.social["queue"] if e["kind"] in ("boom", "probe")] == []
        errors = [r for r in caplog.records if r.levelno == logging.ERROR and "boom" in r.getMessage()]
        assert errors and "p0001" in errors[0].getMessage()
    finally:
        events._HANDLERS.pop("boom", None)
        events._HANDLERS.pop("probe", None)


def test_status_is_derived_and_draws_nothing(receipts_state) -> None:
    from engine.social import behaviour, population

    person = population.profile(receipts_state, "p0010")
    counters = dict(receipts_state.rng_counters)
    statuses = {behaviour.status_at(person, h) for h in range(0, 24 * 7)}
    assert receipts_state.rng_counters == counters
    assert "asleep" in statuses and statuses <= {"asleep", "work", "free", "out"}


def test_one_persons_draws_never_shift_anothers(receipts_active) -> None:
    from engine.game import procgen
    from engine.game.rng import SOCIAL_PACE
    from engine.social import behaviour

    a = procgen.new_game_state(seed=8)
    b = procgen.new_game_state(seed=8)
    for _ in range(5):
        behaviour.person_rng(b, SOCIAL_PACE, "p0003")      # a third person's history in b only
    assert behaviour.person_rng(a, SOCIAL_PACE, "p0001").random() == behaviour.person_rng(b, SOCIAL_PACE, "p0001").random()


def test_every_archetype_loads_and_a_bad_one_names_its_key(receipts_active, monkeypatch) -> None:
    from engine.social import behaviour

    for name in TWELVE:
        assert behaviour.archetype(name).reply_prob > 0
    with pytest.raises(ValueError, match="behaviours.yaml.*no_such"):
        behaviour.archetype("no_such")


def test_the_clock_never_calls_the_social_pass_in_another_story(monkeypatch) -> None:
    from engine.game import clock, procgen
    from engine.games import registry
    from engine import social

    def never() -> None:
        raise AssertionError("social.boot() was called for a story without paths.social")

    monkeypatch.setattr(social, "boot", never)
    registry.activate("hue-and-cry")
    try:
        state = procgen.new_game_state(seed=3)
        clock.advance_time(state, 2.0)
        assert state.social == {}
        assert social.declared() is False
    finally:
        registry.deactivate()


def test_a_declared_story_whose_events_module_fails_logs_once(receipts_state, monkeypatch, caplog) -> None:
    import engine.social as social_pkg
    from engine.game import clock

    monkeypatch.setattr(social_pkg, "_IMPORT_FAULTS_LOGGED", set())   # process-wide: never rely on order

    def boom() -> None:
        raise ImportError("boom")

    monkeypatch.setattr(social_pkg, "boot", boom)
    before = receipts_state.world_clock_hours
    with caplog.at_level(logging.ERROR, logger="engine.social"):
        clock.advance_time(receipts_state, 1.0)
        clock.advance_time(receipts_state, 1.0)
    faults = [r for r in caplog.records if r.levelno == logging.ERROR and "module=events" in r.getMessage()]
    assert len(faults) == 1, caplog.records
    assert receipts_state.world_clock_hours == before + 2.0


# -- further behaviour of the queue ----------------------------------------------


def test_creation_queues_the_first_daily_at_the_next_four_oclock(receipts_state) -> None:
    from engine.social import events

    dailies = [e for e in receipts_state.social["queue"] if e["kind"] == "daily"]
    assert len(dailies) == 1 and dailies[0]["pid"] == ""
    at = dailies[0]["at"]
    assert at % 24 == events.DAILY_HOUR and receipts_state.world_clock_hours < at <= receipts_state.world_clock_hours + 24


def test_the_daily_runs_its_hooks_in_order_and_requeues_itself(receipts_state, monkeypatch) -> None:
    from engine.game import clock
    from engine.social import events

    ran: list[str] = []
    monkeypatch.setattr(events, "daily_hooks", [lambda s: ran.append("first"), lambda s: ran.append("second")])
    first = next(e["at"] for e in receipts_state.social["queue"] if e["kind"] == "daily")
    clock.advance_time(receipts_state, first - receipts_state.world_clock_hours + 24.5)   # two dailies due
    assert ran == ["first", "second", "first", "second"]
    dailies = [e["at"] for e in receipts_state.social["queue"] if e["kind"] == "daily"]
    assert dailies == [first + 48.0]


def test_an_unhandled_kind_is_dropped_with_an_error(receipts_state, caplog) -> None:
    from engine.social import events

    events.push(receipts_state, receipts_state.world_clock_hours + 0.25, "p0007", "nobody_handles_this")
    with caplog.at_level(logging.ERROR, logger="engine.social.events"):
        receipts = events.advance(receipts_state, receipts_state.world_clock_hours,
                                  receipts_state.world_clock_hours + 1.0)
    assert [r["ok"] for r in receipts] == [False]
    assert "kind=nobody_handles_this" in caplog.text
    assert not [e for e in receipts_state.social["queue"] if e["pid"] == "p0007"]


def test_cancel_drops_only_that_persons_named_kinds(receipts_state) -> None:
    from engine.social import events

    now = receipts_state.world_clock_hours
    for pid, kind in (("p0001", "reply"), ("p0001", "read"), ("p0002", "reply")):
        events.push(receipts_state, now + 3.0, pid, kind)
    assert events.cancel(receipts_state, "p0001", {"reply"}) == 1
    left = sorted((e["pid"], e["kind"]) for e in receipts_state.social["queue"] if e["pid"])
    assert left == [("p0001", "read"), ("p0002", "reply")]
    assert events.cancel(receipts_state, "p0001") == 1


def test_the_queue_replays_from_the_seed(receipts_active, monkeypatch) -> None:
    """
    The queue holds DRAWN times: since T7 a like's see_like delay and each
    day's likes-you; since T8 the opener's delay, each read's and reply's
    latency, the double texts' and the day's initiations' times -- all of it
    the same from the same seed and the same actions.
    """
    import dataclasses

    from engine.game import clock, procgen
    from engine.game.effects import apply_effect
    from engine.social import apps, behaviour, events, matching, messaging

    monkeypatch.setattr(matching, "likes_back", lambda *a, **k: True)
    real = behaviour.archetype
    monkeypatch.setattr(behaviour, "archetype", lambda name: dataclasses.replace(
        real(name), opener_prob=1.0, reply_prob=1.0, ghost_per_episode=0.0,
        double_text={"after_hours": 2.0, "prob": 1.0, "max_in_row": 1},
        initiations=({"id": "hello", "kind": "text", "window": "evening", "prob": [1, 1, 1, 1, 1],
                      "when": {"stage_min": "talking"}, "instruction": "window_message"},)))

    def run() -> tuple:
        state = procgen.new_game_state(player_name="Sam", seed=77)
        events.push(state, state.world_clock_hours + 30, "p0004", "probe")
        matching.like(state, "matchstick", apps.top_card(state, "matchstick"))
        drawn = [e["at"] for e in state.social["queue"] if e["kind"] == "see_like"]
        clock.advance_time(state, 3.0)
        clock.advance_time(state, 22.0)
        clock.advance_time(state, 30.0)
        likes = [e["at"] for e in state.social["queue"] if e["kind"] == "likes_you"]
        thread = next(iter(state.social["threads"]))
        apply_effect(state, {"type": "social_stage", "pid": thread.split(":", 1)[1], "stage": "talking"})
        messaging.send(state, thread, "text", "hello again")
        clock.advance_time(state, 20.0)
        return (copy.deepcopy(state.social["queue"]), copy.deepcopy(state.social["threads"]),
                copy.deepcopy(state.social["apps"]), drawn, likes, copy.deepcopy(state.social["people"]))

    first = run()
    assert first == run()
    assert first[3]                                                    # a see_like delay was drawn
    assert first[2]["front_porch"]["likes_you"] or first[4]            # and a day's likes-you
    theirs = [m["decision"]["situation"] for t in first[1].values() for m in t["messages"]
              if m["from"] not in ("player", "system")]
    assert {"opener", "reply", "double_text"} <= set(theirs)           # the T8 draws were exercised
    assert "window_message" in theirs or any(e.get("initiation") == "hello" for e in first[0])   # a day's initiation


def test_next_awake_is_the_next_waking_band(receipts_state) -> None:
    from engine.social import behaviour, population

    person = population.profile(receipts_state, "p0010")
    for hour in range(0, 24 * 7):
        awake = behaviour.next_awake(person, float(hour))
        assert awake >= hour and behaviour.status_at(person, awake) != "asleep"
        if behaviour.status_at(person, float(hour)) != "asleep":
            assert awake == hour


def test_lognormal_minutes_has_its_median_and_a_floor() -> None:
    import random

    from engine.social import behaviour

    rng = random.Random(5)
    draws = sorted(behaviour.lognormal_minutes(rng, 10.0, 0.8) for _ in range(2001))
    assert 8.5 < draws[1000] < 11.5
    assert behaviour.lognormal_minutes(random.Random(1), 0.01, 0.0) == 0.5


def test_the_shipped_behaviours_validate_clean() -> None:
    from engine.games.validation import errors_only, validate_story

    errors = [i for i in errors_only(validate_story("read-receipts"))
              if i.source in ("social/behaviours.yaml", "social/population.yaml", "social/apps.yaml")]
    assert errors == []


def _broken(data: dict, how: str) -> tuple[str, str]:
    rows = data["archetypes"]
    if how == "missing":
        del rows["needy"]["flake_prob"]
        return "social/behaviours.yaml", "archetypes.needy"
    if how == "prob":
        rows["banterer"]["reply_prob"] = 1.5
        return "social/behaviours.yaml", "archetypes.banterer.reply_prob"
    if how == "median":
        rows["steady"]["reply_minutes"]["median"] = 0
        return "social/behaviours.yaml", "archetypes.steady.reply_minutes.median"
    if how == "arc":
        rows["turner"]["arc"] = "no_such_arc"
        return "social/behaviours.yaml", "archetypes.turner.arc"
    if how == "initiation":
        rows["needy"]["initiations"][1].pop("prob")
        return "social/behaviours.yaml", "archetypes.needy.initiations[1](did_i_do_something).prob"
    if how == "cool_off":
        rows["needy"]["cool_off_step"] = 9
        return "social/behaviours.yaml", "archetypes.needy.cool_off_step"
    if how == "arc_shape":
        data["arcs"]["drifter_fade"]["from"] = {"days_since_matched": [40, 14]}
        return "social/behaviours.yaml", "arcs.drifter_fade.from.days_since_matched"
    if how == "undeclared":
        del rows["night_owl"]
        return "social/apps.yaml", "apps.matchstick.culture.archetype_weights"
    raise AssertionError(how)


@pytest.mark.parametrize("how", ["missing", "prob", "median", "arc", "initiation", "cool_off", "arc_shape", "undeclared"])
def test_a_broken_behaviours_file_is_an_error_naming_its_key(tmp_path, how) -> None:
    import yaml

    from engine import yamlio
    from engine.games import registry
    from engine.games.validation import StoryValidator

    for name in ("population", "apps"):
        shutil.copy(SOCIAL_DIR / f"{name}.yaml", tmp_path / f"{name}.yaml")
    data = copy.deepcopy(yamlio.safe_load((SOCIAL_DIR / "behaviours.yaml").read_text(encoding="utf-8")))
    source, key = _broken(data, how)
    (tmp_path / "behaviours.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")
    validator = StoryValidator(registry.get("read-receipts"))
    validator._check_behaviours(tmp_path)
    named = {(i.source, i.ref_id) for i in validator.issues if i.severity == "error"}
    assert (source, key) in named, validator.issues


def test_a_bad_schedule_band_is_an_error(tmp_path) -> None:
    import yaml

    from engine import yamlio
    from engine.games import registry
    from engine.games.validation import StoryValidator

    shutil.copy(SOCIAL_DIR / "behaviours.yaml", tmp_path / "behaviours.yaml")
    shutil.copy(SOCIAL_DIR / "apps.yaml", tmp_path / "apps.yaml")
    population = yamlio.safe_load((SOCIAL_DIR / "population.yaml").read_text(encoding="utf-8"))
    population["schedules"]["office"]["mon"].append([20, 18, "dancing"])
    (tmp_path / "population.yaml").write_text(yaml.safe_dump(population), encoding="utf-8")
    validator = StoryValidator(registry.get("read-receipts"))
    validator._check_behaviours(tmp_path)
    named = {(i.source, i.ref_id) for i in validator.issues if i.severity == "error"}
    assert ("social/population.yaml", "schedules.office.mon") in named, validator.issues


def test_a_failing_daily_hook_still_leaves_the_next_daily_queued(receipts_state, monkeypatch, caplog) -> None:
    from engine.game import clock
    from engine.social import events

    def broken(state) -> None:
        raise RuntimeError("hook fault")

    monkeypatch.setattr(events, "daily_hooks", [broken])
    first = next(e["at"] for e in receipts_state.social["queue"] if e["kind"] == "daily")
    with caplog.at_level(logging.ERROR):                              # isolated since the final review's M2
        clock.advance_time(receipts_state, first - receipts_state.world_clock_hours + 0.5)
    assert "hook fault" in caplog.text
    dailies = [e["at"] for e in receipts_state.social["queue"] if e["kind"] == "daily"]
    assert dailies == [first + 24.0]


def test_a_handler_that_moves_the_clock_is_refused(receipts_state) -> None:
    from engine.game import clock
    from engine.social import events

    events.handles("clockwork")(lambda state, ev: clock.advance_time(state, 1.0) and {"ok": True})
    try:
        before = receipts_state.world_clock_hours
        events.push(receipts_state, before + 0.5, "p0001", "clockwork")
        with pytest.raises(clock.SocialPassClockError, match="never moves the clock"):
            clock.advance_time(receipts_state, 1.0)
        assert receipts_state.world_clock_hours == before + 1.0       # the nested hour never landed
        clock.advance_time(receipts_state, 1.0)                        # the guard was cleared on the way out
        assert receipts_state.world_clock_hours == before + 2.0
    finally:
        events._HANDLERS.pop("clockwork", None)


def test_the_death_checks_reentry_runs_after_the_social_pass(receipts_state, monkeypatch) -> None:
    """The death check advances the clock itself (unconsciousness); it is outside the guard."""
    from engine.game import clock, encounter

    calls: list[float] = []

    def knocked_out(state) -> None:
        calls.append(state.world_clock_hours)
        clock.advance_time(state, 2.0)

    monkeypatch.setattr(encounter, "check_death", knocked_out)
    before = receipts_state.world_clock_hours
    clock.advance_time(receipts_state, 1.0)
    assert calls == [before + 1.0] and receipts_state.world_clock_hours == before + 3.0
