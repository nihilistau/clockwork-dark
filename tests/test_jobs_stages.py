"""
Jobs, part two: the stages, the alarm, the score and the getaway.

THE SHAPE. An open job walks its stages -- approach, entry, inside, the score,
the getaway, with an anchored premise's own stages spliced in -- one
``resolve_stage`` per turn. Each spends the stage's in-game hours through
``advance_time`` BEFORE it rolls on the ``JOB`` stream, so the household is
read after the house has moved on. The band is the premise tier's, walked by
the stage's shift, every security feature that applies (its known shift once
cased), every carried tool that applies, and any flashback shift banked for
the stage -- and every step that moved it comes back as a human reason.

The degrees read Blades-style. A success gets past the stage cleanly; a
``partial`` gets past it at a cost (the alarm rises by ``on_fail``, noisy);
a ``failure`` does not get past it -- the alarm rises by ``on_crit_fail``,
and inside the member in the way SEES you (a real Law witness), at an entry
the story marks ``hurts`` you fall, otherwise it is noise -- and the player
may try again or abort. One stage turn files at most one Law deed. A full
alarm wakes the house (they shout for the watch) and ``jobs.tick``, run
inside ``advance_time``, brings the watch after the story's delay -- closing
the job ``caught`` and opening the Law's arrest scene, or, with no Law or no
arrest scene to open, closing it ``aborted``. A clean getaway carries hot
loot out and marks the house robbed.

WHAT THESE TESTS HOLD. The arithmetic per modifier type; each degree per
stage; the watch arriving on stage time AND on rest; the loot's provenance;
abort; replay; the verbs an open job offers; that no card can be dealt over a
job; and that the flagship and a synthetic Law-without-jobs story never
enter any of it.

Version: v0.1.0 [2026-09-24]
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Iterator

import pytest

from engine.config import set_overlay
from engine.game import checks, encounter, intents
from engine.game.clock import advance_time, set_clock
from engine.game.effects import apply_effect
from engine.game.inventory import holds, name_of
from engine.game.procgen import generate_world
from engine.game.rng import JOB
from engine.game.state import GameState
from engine.world import jobs, law, premises

from test_jobs import JOBS_SPEC, MARKET, MILL, NO_JOBS, SQUARE, _paths, no_jobs_story

ENTRIES = tuple(JOBS_SPEC["entries"])
MARGIN = {"crit_success": 7, "success": 1, "partial": -2, "failure": -6}


@pytest.fixture()
def plain(tmp_path: Path) -> Iterator[Path]:
    """Jobs and premises, no Law: nothing is ever filed."""
    set_overlay({"paths": _paths(tmp_path)})
    try:
        yield tmp_path
    finally:
        set_overlay(None)


@pytest.fixture()
def lawful(tmp_path: Path) -> Iterator[Path]:
    """Jobs, premises, the Law and its arrest scene."""
    set_overlay({"paths": _paths(tmp_path, lawful=True)})
    try:
        yield tmp_path
    finally:
        set_overlay(None)


def _world(seed: int = 42, location: str = SQUARE, hour: int = 22) -> GameState:
    state = GameState(rng_seed=seed, location_id=location)
    state.procgen = generate_world(seed)
    set_clock(state, day=1, hour=hour)
    return state


def _house(state: GameState, *, tier: int = 2, security: tuple[str, ...] = (),
           loot: Any = None) -> str:
    """The first house here, with the tier, security and loot the test needs."""
    prem = premises.at(state, state.location_id)[0]
    prem["tier"] = tier
    prem["security"] = list(security)
    if loot is not None:
        prem["loot"] = list(loot)
    return str(prem["id"])


def _open(state: GameState, **house: Any) -> str:
    pid = _house(state, **house)
    assert jobs.begin(state, pid)["ok"] is True
    return pid


class _Roll:
    """What ``jobs._check`` hands back: the three fields a stage reads."""

    def __init__(self, degree: str) -> None:
        self.degree = degree
        self.margin = MARGIN[degree]

    @property
    def success(self) -> bool:
        return self.degree in ("success", "crit_success")


def _rolls(monkeypatch: pytest.MonkeyPatch, *degrees: str) -> list[tuple[str, str]]:
    """Script the stage rolls; the last degree repeats. Returns the calls made."""
    queue = list(degrees)
    calls: list[tuple[str, str]] = []

    def fake(state: GameState, skill: str, band: str) -> _Roll:
        calls.append((skill, band))
        return _Roll(queue.pop(0) if len(queue) > 1 else queue[0])

    monkeypatch.setattr(jobs, "_check", fake)
    return calls


def _approach(state: GameState, entry: str = "door") -> str:
    stage = jobs.current_stage(state)
    return entry if stage == "entry" else str(stage)


def _walk_to(state: GameState, stage: str, entry: str = "door") -> None:
    for _ in range(20):
        if jobs.current_stage(state) == stage:
            return
        out = jobs.resolve_stage(state, _approach(state, entry))
        assert out["ok"] is True and not out["closed"], out
    raise AssertionError(f"never reached {stage}")


def _verbs(state: GameState) -> dict[str, tuple[str, ...]]:
    return {v.action: v.targets for v in intents.legal_intents(state)}


# ---------------------------------------------------------------------------
# shift_band
# ---------------------------------------------------------------------------


def test_shift_band_walks_and_clamps() -> None:
    assert checks.shift_band("standard", 1) == "hard"
    assert checks.shift_band("standard", -2) == "trivial"
    assert checks.shift_band("easy", -5) == "trivial"
    assert checks.shift_band("severe", 3) == "legendary"
    assert checks.shift_band("hard", 0) == "hard"


# ---------------------------------------------------------------------------
# band_for: one modifier type at a time
# ---------------------------------------------------------------------------


def test_the_base_band_is_the_tier_walked_by_the_stage(plain: Path) -> None:
    state = _world()
    _open(state, tier=2)
    assert jobs.band_for(state, "approach") == ("easy", [])
    assert jobs.band_for(state, "entry", "door") == ("standard", [])
    assert jobs.band_for(state, "entry", "roof") == ("hard", [])
    assert jobs.band_for(state, "score") == ("standard", [])
    assert jobs.band_for(state, "getaway") == ("easy", [])


def test_an_unknown_feature_costs_its_shift_and_a_known_one_its_known_shift(plain: Path) -> None:
    state = _world()
    pid = _open(state, tier=2, security=("good_lock",))
    band, reasons = jobs.band_for(state, "entry", "door")
    # The premise TYPE's own authored `text` (test_premises.TOWNHOUSE), the
    # same words the JOB block's obstacle line reads -- never the bare id.
    assert band == "hard"
    assert reasons == ["a good lock on the street door, not yet cased"]
    # Only on the entries it names.
    assert jobs.band_for(state, "entry", "window") == ("standard", [])
    apply_effect(state, {"type": "intel", "premise": pid, "intel": "security:good_lock"})
    band, reasons = jobs.band_for(state, "entry", "door")
    assert band == "standard"
    assert reasons == ["a good lock on the street door, cased already"]


def test_a_feature_known_or_not_that_moves_the_band_either_way(plain: Path) -> None:
    state = _world()
    # `_open`/`_house` force `mill_dog` onto whatever premise is here (a
    # townhouse), which does not itself declare that security id -- so
    # `_security_text` falls back to the id with underscores swapped, same as
    # it always has. The mismatch is deliberate here: this test is about the
    # arithmetic, not the mill house's own authored text (which the anchor
    # tests below exercise for real).
    pid = _open(state, tier=2, security=("mill_dog",))
    assert jobs.band_for(state, "score") == ("standard", [])  # not its stage
    job = jobs.active(state)
    member = next(iter(premises.get(state, pid)["household"]))
    unknown = jobs.band_for(state, "inside", member)
    apply_effect(state, {"type": "intel", "premise": pid, "intel": "security:mill_dog"})
    known = jobs.band_for(state, "inside", member)
    # +1 whether or not it was cased: the glow is there either way.
    assert unknown[0] == known[0]
    assert unknown[1] == ["mill dog, not yet cased"]
    assert known[1] == ["mill dog, cased already"]
    assert job is jobs.active(state)


def test_an_obstacle_feature_moves_only_its_own_roll(plain: Path) -> None:
    state = _world()
    pid = _open(state, tier=2, security=("yard_dog",))
    member = next(iter(premises.get(state, pid)["household"]))
    before_member = jobs.band_for(state, "inside", member)
    assert jobs.band_for(state, "inside", "yard_dog") == ("standard", [])
    apply_effect(state, {"type": "intel", "premise": pid, "intel": "security:yard_dog"})
    assert jobs.band_for(state, "inside", "yard_dog") == (
        "easy", ["a dog in the yard after dark, cased already"])
    assert jobs.band_for(state, "inside", member) == before_member


def test_a_tool_applies_only_on_its_stages_and_entries(plain: Path) -> None:
    state = _world()
    _open(state, tier=2)
    apply_effect(state, {"type": "item", "item_id": "bent_nail"})
    nail = name_of("bent_nail")
    assert jobs.band_for(state, "entry", "door") == ("easy", [nail])
    assert jobs.band_for(state, "entry", "cellar") == ("easy", [nail])
    assert jobs.band_for(state, "entry", "window") == ("standard", [])
    assert jobs.band_for(state, "score") == ("easy", [nail])
    assert jobs.band_for(state, "approach") == ("easy", [])
    assert jobs.band_for(state, "getaway") == ("easy", [])
    apply_effect(state, {"type": "item", "item_id": "hand_lantern"})
    assert jobs.band_for(state, "getaway") == ("trivial", [name_of("hand_lantern")])


def test_bands_clamp_at_trivial_and_legendary(plain: Path) -> None:
    state = _world()
    _open(state, tier=5)
    assert jobs.band_for(state, "entry", "roof")[0] == "legendary"
    apply_effect(state, {"type": "job_close", "outcome": "aborted"})
    _open(state, tier=1)
    apply_effect(state, {"type": "item", "item_id": "bent_nail"})
    assert jobs.band_for(state, "approach")[0] == "trivial"
    assert jobs.band_for(state, "entry", "door")[0] == "trivial"


def test_a_banked_flashback_shift_moves_its_stage(plain: Path) -> None:
    state = _world()
    _open(state, tier=2)
    # Task 3's `flashback` banks this through an effect; the arithmetic reads it.
    jobs.active(state)["shifts"]["score"] = -1
    band, reasons = jobs.band_for(state, "score")
    assert band == "easy" and len(reasons) == 1 and reasons[0]
    assert jobs.band_for(state, "getaway") == ("easy", [])


# ---------------------------------------------------------------------------
# Resolving a stage
# ---------------------------------------------------------------------------


def test_a_stage_spends_its_hours_before_it_rolls(plain: Path, monkeypatch) -> None:
    state = _world()
    _open(state)
    seen: list[float] = []

    def fake(st: GameState, skill: str, band: str) -> _Roll:
        seen.append(st.world_clock_hours)
        return _Roll("success")

    monkeypatch.setattr(jobs, "_check", fake)
    before = state.world_clock_hours
    out = jobs.resolve_stage(state, "approach")
    assert out["ok"] is True and out["outcome"] == "clean" and out["degree"] == "success"
    assert out["advanced"] is True
    assert seen == [before + 1]
    assert jobs.current_stage(state) == "entry"


def test_a_failure_raises_the_alarm_and_does_not_advance(plain: Path, monkeypatch) -> None:
    state = _world()
    _open(state)
    _rolls(monkeypatch, "failure")
    out = jobs.resolve_stage(state, "approach")
    assert out["ok"] is True and out["outcome"] == "noisy" and not out["closed"]
    assert out["advanced"] is False
    assert jobs.current_stage(state) == "approach"
    assert jobs.active(state)["alarm"] == JOBS_SPEC["alarm"]["on_crit_fail"]
    assert out["alarm_band"] == jobs.alarm_band(state) == "stirring"
    # Try again: new hours, new roll.
    before = state.world_clock_hours
    jobs.resolve_stage(state, "approach")
    assert state.world_clock_hours == before + 1
    assert jobs.active(state)["alarm"] == 4


def test_a_partial_advances_at_a_cost(plain: Path, monkeypatch) -> None:
    state = _world()
    _open(state)
    _rolls(monkeypatch, "partial")
    out = jobs.resolve_stage(state, "approach")
    assert out["outcome"] == "noisy" and not out["closed"]
    assert out["advanced"] is True
    assert jobs.current_stage(state) == "entry"
    assert jobs.active(state)["alarm"] == JOBS_SPEC["alarm"]["on_fail"]
    assert out["alarm_band"] == "uneasy"
    jobs.resolve_stage(state, "window")
    assert jobs.active(state)["entry"] == "window"
    assert jobs.current_stage(state) == "inside"


def test_a_partial_inside_gets_past_the_obstacle_unseen(lawful: Path, monkeypatch) -> None:
    state = _world()
    pid = _open(state)
    _rolls(monkeypatch, "success", "success", "partial")
    _walk_to(state, "inside")
    out = jobs.resolve_stage(state, "inside")
    household = list(premises.get(state, pid)["household"])
    assert out["outcome"] == "noisy"
    assert jobs.active(state)["obstacles"] == household[1:]
    assert not [r for r in state.law.get("witnessed") or [] if r.get("deed") == "burglary"]


def test_a_partial_getaway_carries_the_take_out_noisily(plain: Path, monkeypatch) -> None:
    state = _world()
    pid = _open(state, loot=("golden_ring",))
    _rolls(monkeypatch, "success")
    _walk_to(state, "getaway")
    _rolls(monkeypatch, "partial")
    out = jobs.resolve_stage(state, "getaway")
    assert out["outcome"] == "noisy" and out["closed"] is True
    assert holds(state, "golden_ring") and pid in jobs.robbed(state)


def test_the_entry_is_recorded(plain: Path, monkeypatch) -> None:
    state = _world()
    _open(state)
    _rolls(monkeypatch, "success")
    _walk_to(state, "entry")
    out = jobs.resolve_stage(state, "window")
    assert out["approach"] == "window"
    assert jobs.active(state)["entry"] == "window"
    assert jobs.current_stage(state) == "inside"


def test_an_illegal_approach_is_refused_and_spends_nothing(plain: Path, monkeypatch) -> None:
    state = _world()
    _open(state)
    calls = _rolls(monkeypatch, "success")
    before = (state.world_clock_hours, copy.deepcopy(state.jobs))
    out = jobs.resolve_stage(state, "door")  # an entry, at the approach
    assert out["ok"] is False and out["message"]
    assert (state.world_clock_hours, state.jobs) == before and calls == []


def test_a_failure_at_a_hurting_entry_is_a_fall(plain: Path, monkeypatch) -> None:
    state = _world()
    _open(state)
    _rolls(monkeypatch, "success", "failure")
    _walk_to(state, "entry")
    hp = state.stats.hp
    out = jobs.resolve_stage(state, "roof")
    assert out["outcome"] == "hurt" and not out["closed"]
    assert state.stats.hp == hp - 1
    assert jobs.current_stage(state) == "entry"
    # Through the door it is only noise.
    out = jobs.resolve_stage(state, "door")
    assert out["outcome"] == "noisy" and state.stats.hp == hp - 1


def test_only_an_entry_marked_hurts_is_a_fall(tmp_path: Path, monkeypatch) -> None:
    doc = copy.deepcopy(JOBS_SPEC)
    doc["entries"]["roof"]["hurts"] = False
    doc["entries"]["window"]["hurts"] = True
    set_overlay({"paths": _paths(tmp_path, doc)})
    try:
        state = _world()
        _open(state)
        _rolls(monkeypatch, "success", "failure")
        _walk_to(state, "entry")
        hp = state.stats.hp
        assert jobs.resolve_stage(state, "roof")["outcome"] == "noisy"
        assert state.stats.hp == hp
        assert jobs.resolve_stage(state, "window")["outcome"] == "hurt"
        assert state.stats.hp == hp - 1
    finally:
        set_overlay(None)


def test_a_hurt_that_kills_ends_the_job(plain: Path, monkeypatch) -> None:
    state = _world()
    _open(state)
    _rolls(monkeypatch, "success", "failure")
    _walk_to(state, "entry")
    state.stats.hp = 1
    out = jobs.resolve_stage(state, "cellar")
    assert out["outcome"] == "hurt" and out["closed"] is True
    assert jobs.active(state) is None
    assert state.jobs["last"]["outcome"] == "hurt"


def test_inside_the_household_at_home_are_the_obstacles(plain: Path, monkeypatch) -> None:
    state = _world()
    pid = _open(state, security=("yard_dog",))
    _rolls(monkeypatch, "success")
    _walk_to(state, "inside")
    household = list(premises.get(state, pid)["household"])
    jobs.resolve_stage(state, "inside")
    job = jobs.active(state)
    # Night: everyone is home. One roll removed the first obstacle.
    assert job["obstacles"] == household[1:] + ["yard_dog"]
    assert jobs.current_stage(state) == "inside"
    for _ in household[1:] + ["yard_dog"]:
        jobs.resolve_stage(state, "inside")
    assert jobs.current_stage(state) == "score"


def test_an_empty_house_is_crossed_without_a_roll(plain: Path, monkeypatch) -> None:
    state = _world(hour=8)  # approach 9, entry 10, inside 11: the master is at work
    pid = _open(state)
    prem = premises.get(state, pid)
    prem["household"] = prem["household"][:1]
    calls = _rolls(monkeypatch, "success")
    _walk_to(state, "inside")
    rolled = len(calls)
    out = jobs.resolve_stage(state, "inside")
    assert out["ok"] is True and out["outcome"] == "clean" and out["degree"] == ""
    assert len(calls) == rolled
    assert jobs.current_stage(state) == "score"


def test_a_failure_inside_makes_a_real_law_witness(lawful: Path, monkeypatch) -> None:
    state = _world()
    pid = _open(state)
    _rolls(monkeypatch, "success", "success", "failure")
    _walk_to(state, "inside")
    out = jobs.resolve_stage(state, "inside")
    member = premises.get(state, pid)["household"][0]
    assert out["outcome"] == "seen"
    assert member in out["witnesses"]
    rows = [r for r in state.law.get("witnessed") or []
            if r.get("npc") == member and r.get("deed") == "burglary"]
    assert rows, state.law
    assert jobs.active(state)["alarm"] == 2


def test_seen_and_shouting_on_one_roll_file_one_deed(lawful: Path, monkeypatch) -> None:
    state = _world()
    pid = _open(state)
    # A failed approach (alarm 2), then in; the failure inside both gets the
    # thief seen AND raises the alarm to max.
    _rolls(monkeypatch, "failure", "success", "success", "failure")
    _walk_to(state, "inside")
    assert jobs.active(state)["alarm"] == 2
    deeds: list[str] = []
    real = law.commit_deed

    def spy(st: GameState, kind: str, **kwargs: Any) -> dict[str, Any]:
        deeds.append(kind)
        return real(st, kind, **kwargs)

    monkeypatch.setattr(law, "commit_deed", spy)
    before = len(state.law.get("witnessed") or [])
    out = jobs.resolve_stage(state, "inside")
    assert out["outcome"] == "seen" and out["alarm_band"] == "raised"
    assert deeds == ["burglary"]
    rows = (state.law.get("witnessed") or [])[before:]
    assert len({r["deed_id"] for r in rows}) == 1
    member = premises.get(state, pid)["household"][0]
    assert member in {r["npc"] for r in rows}
    assert set(premises.get(state, pid)["household"]) <= {r["npc"] for r in rows}


def test_the_score_draws_loot_and_holds_it_until_the_getaway(plain: Path, monkeypatch) -> None:
    state = _world()
    _open(state, tier=3, loot=("golden_ring", "loaf", "loaf"))
    _rolls(monkeypatch, "success")
    _walk_to(state, "score")
    out = jobs.resolve_stage(state, "score")
    loot = jobs.active(state)["loot"]
    assert len(loot) == JOBS_SPEC["score"]["draws"][3]
    assert set(loot) <= {"golden_ring", "loaf"}
    assert out["loot"] == [name_of(i) for i in loot]
    assert not holds(state, "golden_ring") and "secret" not in out


def test_a_known_secret_is_named_at_the_score(plain: Path, monkeypatch) -> None:
    state = _world()
    pid = _open(state, loot=("golden_ring",))
    apply_effect(state, {"type": "intel", "premise": pid, "intel": "secret"})
    _rolls(monkeypatch, "success")
    _walk_to(state, "score")
    out = jobs.resolve_stage(state, "score")
    secret = premises.get(state, pid)["secret"]
    text = next(s["text"] for s in premises.spec("townhouse")["secrets"] if s["id"] == secret)
    assert out["secret"] == text


def test_a_clean_run_carries_hot_loot_out_and_robs_the_house(lawful: Path, monkeypatch) -> None:
    state = _world()
    pid = _open(state, loot=("golden_ring",))
    name = premises.get(state, pid)["name"]
    _rolls(monkeypatch, "success")
    _walk_to(state, "getaway")
    deeds: list[tuple[str, Any]] = []
    real = law.commit_deed

    def spy(st: GameState, kind: str, **kwargs: Any) -> dict[str, Any]:
        deeds.append((kind, kwargs.get("margin")))
        return real(st, kind, **kwargs)

    monkeypatch.setattr(law, "commit_deed", spy)
    out = jobs.resolve_stage(state, "getaway")
    assert out["outcome"] == "clean" and out["closed"] is True
    assert holds(state, "golden_ring")
    assert state.provenance["golden_ring"][-1]["whom"] == name
    assert jobs.active(state) is None
    assert pid in jobs.robbed(state) and state.jobs["last"]["outcome"] == "clean"
    # The burglary deed was committed at the getaway, on the getaway's margin.
    assert deeds == [("burglary", MARGIN["success"])]
    # And the house is done: `burgle` neither offers nor accepts it.
    assert pid not in _verbs(state).get("burgle", ())
    assert jobs.begin(state, pid)["ok"] is False


def test_a_getaway_after_noise_is_noisy(plain: Path, monkeypatch) -> None:
    state = _world()
    pid = _open(state, loot=("golden_ring",))
    _rolls(monkeypatch, "failure", "success")
    jobs.resolve_stage(state, "approach")
    _walk_to(state, "getaway")
    out = jobs.resolve_stage(state, "getaway")
    assert out["outcome"] == "noisy" and out["closed"] is True
    assert pid in jobs.robbed(state)
    # No Law: nothing was ever filed.
    assert state.law == {}


def test_a_consumed_tool_is_used_up_by_the_roll_it_helped(plain: Path, monkeypatch) -> None:
    state = _world()
    _open(state, loot=("golden_ring",))
    apply_effect(state, {"type": "item", "item_id": "hand_lantern"})
    calls = _rolls(monkeypatch, "success")
    _walk_to(state, "getaway")
    jobs.resolve_stage(state, "getaway")
    assert calls[-1][1] == "trivial"
    assert not holds(state, "hand_lantern")


def test_abort_carries_nothing_out_and_spends_no_time(plain: Path, monkeypatch) -> None:
    state = _world()
    pid = _open(state, loot=("golden_ring",))
    _rolls(monkeypatch, "success")
    _walk_to(state, "getaway")
    assert jobs.active(state)["loot"]
    before = state.world_clock_hours
    out = jobs.abort(state)
    assert out["ok"] is True and out["outcome"] == "aborted" and out["closed"] is True
    assert state.world_clock_hours == before
    assert not holds(state, "golden_ring")
    assert jobs.active(state) is None and pid not in jobs.robbed(state)
    again = jobs.abort(state)
    assert again["ok"] is False and again["message"]


# ---------------------------------------------------------------------------
# The alarm and the watch
# ---------------------------------------------------------------------------


def _raise(state: GameState, monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    calls = _rolls(monkeypatch, "failure")
    jobs.resolve_stage(state, "approach")
    out = jobs.resolve_stage(state, "approach")
    assert out["alarm_band"] == "raised"
    job = jobs.active(state)
    assert job["raised_at"] == state.world_day * 24 + state.world_hour
    return calls


def test_a_raised_alarm_brings_the_watch_after_two_stage_hours(lawful: Path, monkeypatch) -> None:
    state = _world()
    pid = _open(state)
    calls = _raise(state, monkeypatch)
    # The house shouted: the household at home informed.
    household = set(premises.get(state, pid)["household"])
    shouted = {r["npc"] for r in state.law.get("witnessed") or [] if r["deed"] == "burglary"}
    assert household <= shouted
    # One more stage-hour: still inside, still rolling.
    out = jobs.resolve_stage(state, "approach")
    assert not out["closed"] and jobs.active(state) is not None
    rolled = len(calls)
    # The second: the watch is at the door before the roll.
    out = jobs.resolve_stage(state, "approach")
    assert out["closed"] is True and out["outcome"] == "caught"
    assert len(calls) == rolled
    assert jobs.active(state) is None and state.jobs["last"]["outcome"] == "caught"
    assert encounter.active(state) and state.encounter["id"] == "watch_stop"
    assert pid not in jobs.robbed(state)


def test_without_a_law_a_raised_alarm_ends_the_job_with_nothing_filed(plain: Path, monkeypatch) -> None:
    state = _world()
    _open(state)
    _raise(state, monkeypatch)
    jobs.resolve_stage(state, "approach")
    out = jobs.resolve_stage(state, "approach")
    assert out["closed"] is True and out["outcome"] == "aborted"
    assert state.law == {}
    assert not encounter.active(state)


def test_an_arrest_scene_nobody_loaded_warns_once_and_rouses_the_house(
    tmp_path: Path, monkeypatch, caplog
) -> None:
    import logging

    # The Law names `watch_stop` and loads (its loader checks the name), then
    # the scene goes missing -- the content fault the patrol also warns about.
    set_overlay({"paths": _paths(tmp_path, lawful=True)})
    monkeypatch.setattr(jobs, "_WARNED_ARREST", None)
    caplog.set_level(logging.WARNING, logger="engine.world.jobs")
    try:
        assert law.load_spec()["arrest"]["encounter"] == "watch_stop" and jobs.spec()
        real = encounter.get_definition
        monkeypatch.setattr(encounter, "get_definition",
                            lambda eid: None if eid == "watch_stop" else real(eid))
        for _ in range(2):
            state = _world()
            _open(state)
            _raise(state, monkeypatch)
            jobs.resolve_stage(state, "approach")
            out = jobs.resolve_stage(state, "approach")
            assert out["closed"] is True and out["outcome"] == "aborted"
            assert not encounter.active(state)
    finally:
        set_overlay(None)
    warned = [r for r in caplog.records if "arrest.encounter" in r.getMessage()]
    assert len(warned) == 1


def test_rest_rolls_nothing_but_runs_the_watch(plain: Path, monkeypatch) -> None:
    from engine.game import survival

    state = _world()
    _open(state)
    before = (state.rng_counters.get(JOB), copy.deepcopy(jobs.active(state)))
    survival.rest(state, "rest_short")
    assert (state.rng_counters.get(JOB), jobs.active(state)) == before
    _raise(state, monkeypatch)
    counter = state.rng_counters.get(JOB)
    survival.rest(state, "rest_short")
    assert jobs.active(state) is None and state.jobs["last"]["outcome"] == "aborted"
    assert state.rng_counters.get(JOB) == counter


def test_tick_does_nothing_without_a_raised_alarm(plain: Path) -> None:
    state = _world()
    _open(state)
    snapshot = copy.deepcopy(state.jobs)
    jobs.tick(state, 48)
    assert state.jobs == snapshot


# ---------------------------------------------------------------------------
# Anchored stages
# ---------------------------------------------------------------------------


def test_an_anchor_stage_rolls_its_authored_skill_and_band(plain: Path, monkeypatch) -> None:
    state = _world(location=MARKET)
    assert jobs.begin(state, MILL)["ok"] is True
    calls = _rolls(monkeypatch, "success")
    _walk_to(state, "bell_floor")
    assert jobs.band_for(state, "bell_floor") == ("severe", [])
    assert [a for a, _ in jobs.approaches(state)] == ["bell_floor"]
    _rolls(monkeypatch, "failure", "success")
    before = state.world_clock_hours
    out = jobs.resolve_stage(state, "bell_floor")
    assert out["outcome"] == "noisy" and jobs.current_stage(state) == "bell_floor"
    assert state.world_clock_hours == before + 1
    calls = _rolls(monkeypatch, "success")
    jobs.resolve_stage(state, "bell_floor")
    assert calls == [("nerve", "severe")]
    assert jobs.current_stage(state) == "score"


# ---------------------------------------------------------------------------
# Replay
# ---------------------------------------------------------------------------


def _play(seed: int) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, int]]:
    state = _world(seed=seed)
    _open(state, loot=("golden_ring", "loaf"))
    receipts = []
    for _ in range(14):
        if jobs.active(state) is None:
            break
        receipts.append(jobs.resolve_stage(state, _approach(state, "window")))
    return receipts, copy.deepcopy(state.jobs), dict(state.rng_counters)


def test_same_seed_same_choices_same_receipts(lawful: Path) -> None:
    first = _play(7)
    second = _play(7)
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    assert first[2].get(JOB)


# ---------------------------------------------------------------------------
# The verbs
# ---------------------------------------------------------------------------


def test_an_open_job_offers_its_stage_and_abort(plain: Path, monkeypatch) -> None:
    state = _world()
    _open(state)
    assert _verbs(state) == {"job": ("approach",), "abort": ()}
    _rolls(monkeypatch, "success")
    _walk_to(state, "entry")
    assert _verbs(state) == {"job": ENTRIES, "abort": ()}
    job = intents.find_verb(intents.legal_intents(state), "job")
    for target, label in job.options:
        assert "prem_" not in label and "gen_" not in label and label != target
    _walk_to(state, "inside")
    jobs.resolve_stage(state, "inside")
    job = intents.find_verb(intents.legal_intents(state), "job")
    assert job.targets == ("inside",)
    assert "gen_" not in job.options[0][1]


def test_verb_mapping() -> None:
    assert intents.SKILL_FOR_ACTION["job"] == "job_stage"
    assert intents.SKILL_FOR_ACTION["abort"] == "abort_job"
    assert intents.REFUSAL_KEY_FOR_ACTION["job"] == "ok"
    assert intents.REFUSAL_KEY_FOR_ACTION["abort"] == "ok"
    assert intents.to_tool_call(GameState(), {"action": "job", "target": "door"}) == (
        "job_stage", {"approach": "door"})
    assert intents.to_tool_call(GameState(), {"action": "abort"}) == ("abort_job", {})


def _no_ids_or_numbers(line: str, name: str = "") -> None:
    assert line
    # A house may be "Number 12, Wick Lane"; that is its name, not a count.
    bare = line.replace(name, "") if name else line
    assert not any(ch.isdigit() for ch in bare), line
    for token in ("prem_", "gen_", "bell_floor", "j1"):
        assert token not in line, line


def test_job_intents_execute_end_to_end_and_narrate_without_ids(plain: Path) -> None:
    from engine.agents.prompts import summarise_receipt
    from engine.agents.tool_dispatcher import execute_intent
    from engine.game.engine import GameEngine

    state = _world()
    pid = _open(state)
    name = premises.get(state, pid)["name"]
    engine = GameEngine(state)
    (receipt,) = execute_intent({"action": "job", "target": "approach"}, engine)
    assert receipt["success"] is True and not receipt.get("refused"), receipt
    _no_ids_or_numbers(summarise_receipt(receipt), name)
    (refused,) = execute_intent({"action": "job", "target": "getaway"}, engine)
    assert refused.get("refused") is True
    (aborted,) = execute_intent({"action": "abort"}, engine)
    assert aborted["success"] is True
    _no_ids_or_numbers(summarise_receipt(aborted), name)
    assert jobs.active(state) is None


#: (outcome, advanced, closed) as a receipt can carry them.
RECEIPTS = [
    ("clean", True, False), ("noisy", True, False), ("noisy", False, False),
    ("seen", False, False), ("hurt", False, False), ("hurt", False, True),
    ("caught", False, True), ("aborted", False, True),
    ("clean", True, True), ("noisy", True, True),
]


def _job_line(outcome: str, advanced: bool, closed: bool) -> str:
    from engine.agents.prompts import summarise_receipt

    result = {"ok": True, "stage": "inside", "approach": "inside", "band": "hard",
              "reasons": ["an unknown yard dog"], "degree": "failure", "outcome": outcome,
              "alarm_band": "roused", "witnesses": ["gen_x_cook"], "loot": [],
              "closed": closed, "advanced": advanced, "name": "the Pike townhouse",
              "label": "get past Ada Pike"}
    return summarise_receipt({"skill": "job_stage", "result": result})


@pytest.mark.parametrize(("outcome", "advanced", "closed"), RECEIPTS)
def test_every_outcome_summarises_without_ids_or_numbers(
    outcome: str, advanced: bool, closed: bool
) -> None:
    _no_ids_or_numbers(_job_line(outcome, advanced, closed))


def test_a_partial_reads_as_progress_and_a_failure_does_not() -> None:
    partial = _job_line("noisy", True, False)
    failure = _job_line("noisy", False, False)
    seen = _job_line("seen", False, False)
    assert partial != failure
    assert "got through" in partial and "did not" not in partial
    assert "did not get through" in failure
    assert "did not get through" in seen and "saw you" in seen


def test_job_stage_is_a_rolling_skill() -> None:
    from engine.agents.evaluator import ROLLING_SKILLS

    assert "job_stage" in ROLLING_SKILLS


# ---------------------------------------------------------------------------
# Nothing pre-empts a job
# ---------------------------------------------------------------------------


def test_no_card_is_dealt_while_a_job_is_open(plain: Path, monkeypatch) -> None:
    from engine.content import director

    state = _world()
    _open(state)

    def due(*args: Any, **kwargs: Any) -> tuple[str, str, str]:
        raise AssertionError("the director asked for a card mid-job")

    monkeypatch.setattr(director, "due", due)
    assert director.ensure_scene(state) == []


def test_a_card_cannot_take_the_turn_from_a_job(plain: Path, monkeypatch) -> None:
    state = _world()
    _open(state)
    monkeypatch.setattr(intents, "_card_open", lambda s: True)
    monkeypatch.setattr(intents, "_scene_open", lambda s: True)
    assert set(_verbs(state)) == {"job", "abort"}


# ---------------------------------------------------------------------------
# The door fails loudly; the loader's grammar check
# ---------------------------------------------------------------------------


def test_begin_reads_the_file_so_a_malformed_one_fails_at_the_door(tmp_path: Path) -> None:
    doc = copy.deepcopy(JOBS_SPEC)
    doc["features"]["no_such_feature"] = {"stage": "entry", "shift": 1}
    set_overlay({"paths": _paths(tmp_path, doc)})
    try:
        state = _world()
        with pytest.raises(ValueError):
            jobs.begin(state, premises.at(state, SQUARE)[0]["id"])
    finally:
        set_overlay(None)


def test_a_requires_mixing_a_group_with_a_sibling_predicate_fails(tmp_path: Path) -> None:
    doc = copy.deepcopy(JOBS_SPEC)
    doc["flashbacks"]["planted_tool"]["requires"] = {
        "all": [{"premise_cased": {"min": 1}}], "visited": "edgewood_square"}
    paths = _paths(tmp_path, doc)
    set_overlay({"paths": paths})
    try:
        with pytest.raises(ValueError) as caught:
            jobs.spec()
        assert paths["jobs"] in str(caught.value)
    finally:
        set_overlay(None)


# ---------------------------------------------------------------------------
# Controls: stories without jobs never enter any of it
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("kind", NO_JOBS)
def test_a_story_without_jobs_never_ticks(
    kind: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with no_jobs_story(kind, tmp_path) as location:
        assert not jobs.declared()
        assert law.declared() is (kind == "law-only")

        def boom(*args: Any, **kwargs: Any) -> None:
            raise AssertionError("jobs.tick ran for a story without jobs")

        monkeypatch.setattr(jobs, "tick", boom)
        state = GameState(rng_seed=42, location_id=location)
        state.procgen = generate_world(42)
        set_clock(state, day=1, hour=8)
        advance_time(state, 5)
        assert state.jobs == {}
        assert "job" not in _verbs(state) and "abort" not in _verbs(state)


# ---------------------------------------------------------------------------
# Final fix wave (v0.11.0): the wall clock, death, and who is still at home
# ---------------------------------------------------------------------------


@pytest.fixture()
def _saves(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    from engine.persistence import reset_save_store
    from engine.persistence.saves import SaveStore

    reset_save_store()
    store = SaveStore(root=tmp_path / "saves")
    monkeypatch.setattr("engine.scenes.default_state.get_save_store", lambda: store)
    yield
    reset_save_store()


def _turn(session: Any, intent: Any = None) -> dict[str, Any]:
    """One REAL turn through ``run_turn``, the model scripted."""
    from engine.scenes.default_state import run_turn
    from test_turn_intent import canned_reply

    reply = canned_reply(session.engine.state)
    session.storyteller.llm_fn = lambda messages, **kw: reply
    session.assistant.llm_fn = session.storyteller.llm_fn
    return run_turn(session, "The player chooses: Go on", intent=intent)


def test_a_slow_read_does_not_bring_the_watch_to_an_open_job(
    lawful: Path, _saves: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Final review I1. ``run_turn`` runs the WALL-CLOCK world tick every turn,
    and ``advance_time`` inside it runs ``jobs.tick``: a player who read the
    prose for an hour of real time (six in-game hours, the cap) had the watch
    at the door before the stage they chose was even tried. The tick does not
    run while a job is open, and is re-stamped so the paused minutes do not
    arrive as a burst once the job closes.
    """
    import time

    from engine.session import SessionStore

    session = SessionStore().create(seed=42, llm_fn=None)
    state = session.engine.state
    state.location_id = SQUARE
    set_clock(state, day=1, hour=22)
    _open(state)
    calls = _raise(state, monkeypatch)  # the watch is two stage-hours out
    rolled = len(calls)
    clock = float(state.world_clock_hours)
    state.last_sim_tick_at = time.time() - 3600.0  # an hour of reading

    _turn(session, {"action": "job", "target": "approach"})

    assert jobs.active(state) is not None, state.jobs.get("last")
    assert len(calls) == rolled + 1  # the chosen stage was tried, and rolled
    assert float(state.world_clock_hours) == clock + 1.0  # its one stage-hour only
    assert state.last_sim_tick_at > time.time() - 60.0  # re-stamped

    # Walk away, then a turn with nothing chosen: no burst of paused hours.
    state.last_sim_tick_at = time.time() - 3600.0
    _turn(session, {"action": "abort"})
    assert jobs.active(state) is None
    clock = float(state.world_clock_hours)
    _turn(session)
    assert float(state.world_clock_hours) == clock


def _play_through_the_turn_tick(seed: int, read_seconds: float) -> Any:
    """``_play``, with ``run_turn``'s own background tick before every stage."""
    import time

    from engine.scenes.default_state import _background_tick

    state = _world(seed=seed)
    _open(state, loot=("golden_ring", "loaf"))
    receipts = []
    for _ in range(14):
        if jobs.active(state) is None:
            break
        state.last_sim_tick_at = time.time() - read_seconds
        _background_tick(state)
        receipts.append(jobs.resolve_stage(state, _approach(state, "window")))
    return receipts, copy.deepcopy(state.jobs), dict(state.rng_counters)


def test_a_job_replays_however_long_the_player_read_between_stages(lawful: Path) -> None:
    """
    The replay guarantee through the wall-clock path (final review I1): the
    same seed and choices give the same receipts whether the player answered
    each stage at once or read for an hour first.
    """
    quick = _play_through_the_turn_tick(7, 0.0)
    slow = _play_through_the_turn_tick(7, 3600.0)
    assert json.dumps(quick, sort_keys=True) == json.dumps(slow, sort_keys=True)
    assert quick[2].get(JOB)


def test_dying_mid_job_closes_the_job(plain: Path, monkeypatch) -> None:
    """
    Final review I2. ``check_death`` carried the thief off (respawn location,
    hours, hp) but left the job open, so ``job``/``abort`` were offered from
    wherever they woke. The stage's hours took the last hp here, so nothing
    rolls either.
    """
    monkeypatch.setattr(encounter, "load_death_rules", lambda: {
        "threshold": 0, "respawn": {"location_id": MARKET, "hours": 4, "hp": 3}})
    state = _world()
    _open(state)
    calls = _rolls(monkeypatch, "success")
    state.stats.hp = 0
    out = jobs.resolve_stage(state, "approach")
    assert out["closed"] is True and out["outcome"] == "hurt", out
    assert out["alarm_band"] != "raised"
    assert calls == []
    assert jobs.active(state) is None and state.jobs["last"]["outcome"] == "hurt"
    assert state.location_id == MARKET
    assert "job" not in _verbs(state) and "abort" not in _verbs(state)


def test_a_member_who_left_is_neither_rolled_against_nor_a_witness(
    lawful: Path, monkeypatch
) -> None:
    """
    Final review I3. The inside queue is read once; a member who went out
    after that stayed in it, was rolled against as a sleeper, and on a
    failure SAW the thief from wherever they had gone -- a certain Law
    witness. At each inside roll the absent are dropped first.
    """
    state = _world()
    pid = _open(state)
    household = list(premises.get(state, pid)["household"])
    assert len(household) >= 2
    _rolls(monkeypatch, "success")
    _walk_to(state, "inside")
    jobs.resolve_stage(state, "inside")  # past the first; the queue is read
    assert jobs.active(state)["obstacles"][0] == household[1]

    gone = household[1]
    real = jobs._at_home
    monkeypatch.setattr(jobs, "_at_home",
                        lambda s, p: [(n, a) for n, a in real(s, p) if n != gone])
    _rolls(monkeypatch, "failure")
    out = jobs.resolve_stage(state, "inside")

    assert gone not in out["witnesses"], out
    job = jobs.active(state)
    assert job is not None and gone not in job["obstacles"]
    assert gone not in {r["npc"] for r in state.law.get("witnessed") or []}


def test_a_tick_abort_and_a_players_abort_close_differently(plain: Path, monkeypatch) -> None:
    """Final review M2: only ``jobs.abort`` stamps ``by: player`` on the close."""
    state = _world()
    _open(state)
    _raise(state, monkeypatch)
    jobs.resolve_stage(state, "approach")
    jobs.resolve_stage(state, "approach")  # the watch's hours: nobody to come
    assert state.jobs["last"]["outcome"] == "aborted"
    assert state.jobs["last"].get("by") is None
    state = _world()
    _open(state)
    jobs.abort(state)
    assert state.jobs["last"]["outcome"] == "aborted"
    assert state.jobs["last"]["by"] == "player"
