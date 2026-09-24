"""
Jobs, part three: prep and flashbacks.

THE SHAPE. ``state.jobs["prep"]`` is a veiled meter, refilled only by casing
(``premises.case`` pays ``prep.per_case`` through the ``job_prep`` effect,
capped at ``prep.max``, and only on a watch that actually learned something --
a refused case spends nothing, prep included). Mid-job, ``jobs.flashback``
spends prep (and coin, where named) to call on something the thief is said to
have arranged beforehand: a shift banked into the current stage's band, or the
first few ``inside`` obstacles gone. ``jobs.legal_flashbacks`` is what the
``flashback`` verb offers -- a kind whose stage matches, that has not been
used yet this job, that the player can afford, and whose ``requires`` (with
``{district}``/``{premise}`` filled from the open job) the shared condition
grammar accepts. ``exposure: household`` draws one member of the premise on
the JOB stream and, only with a Law declared, makes them a real witness --
the retroactively bribed servant. A flashback NEVER calls ``advance_time``:
the present stage's odds and its costs change now, but no hour passes.

WHAT THESE TESTS HOLD. A flashback gated on unmet history is never offered
and refuses if forced; one the player cannot afford is never offered; a used
kind cannot be called on twice in the same job; the band moves by exactly the
banked shift; an obstacle-clearing flashback initialises ``inside`` the same
deterministic way a roll there would, drawing nothing extra from JOB; the one
exposure draw makes a real, named Law witness and, with no Law, does nothing
at all; no flashback ever advances the clock; casing raises prep and caps it;
the verb and its skill wire in end to end, narrating without a leaked id or
number; and a story that declares no jobs is untouched, prep included.

Version: v0.1.0 [2026-09-24]
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest

from engine.config import set_overlay
from engine.game import checks, intents, quests
from engine.game.clock import set_clock
from engine.game.effects import apply_effect
from engine.game.procgen import generate_world
from engine.game.rng import JOB
from engine.game.state import GameState
from engine.world import jobs, premises

from test_jobs import JOB_VERBS, JOBS_SPEC, MALFORMED, NO_JOBS, SQUARE, _paths, _verbs, no_jobs_story
from test_jobs_stages import _house, _no_ids_or_numbers, _open, _rolls, _walk_to, _world

FLASHBACKS = JOBS_SPEC["flashbacks"]


@pytest.fixture()
def plain(tmp_path: Path):
    set_overlay({"paths": _paths(tmp_path)})
    try:
        yield tmp_path
    finally:
        set_overlay(None)


@pytest.fixture()
def lawful(tmp_path: Path):
    set_overlay({"paths": _paths(tmp_path, lawful=True)})
    try:
        yield tmp_path
    finally:
        set_overlay(None)


def _cased_once(state: GameState, pid: str) -> None:
    out = premises.case(state, pid)
    assert out["ok"] is True, out


# ---------------------------------------------------------------------------
# Prep: earned only by casing
# ---------------------------------------------------------------------------


def test_prep_rises_by_casing_and_caps(plain: Path) -> None:
    state = _world()
    pid = _house(state, security=("good_lock", "barred_shutters", "yard_dog", "night_man"))
    remaining = len(premises.unknown_ids(state, pid))
    assert remaining >= 5
    assert state.jobs.get("prep") in (None, 0)
    for i in range(1, remaining + 3):
        out = premises.case(state, pid)
        if i <= remaining:
            assert out["ok"] is True, out
        else:
            # Nothing left to learn: the case refuses and prep does not move.
            assert out["ok"] is False, out
    assert state.jobs["prep"] == JOBS_SPEC["prep"]["max"]


def test_a_refused_case_pays_no_prep(plain: Path) -> None:
    state = _world()
    pid = _house(state)
    for _ in range(20):
        if not premises.unknown_ids(state, pid):
            break
        assert premises.case(state, pid)["ok"] is True
    before = state.jobs["prep"]
    refused = premises.case(state, pid)
    assert refused["ok"] is False
    assert state.jobs["prep"] == before


# ---------------------------------------------------------------------------
# What is offered
# ---------------------------------------------------------------------------


def test_a_flashback_is_never_offered_when_requires_fails_and_refuses_if_forced(
    plain: Path,
) -> None:
    state = _world()
    pid = _house(state)
    assert jobs.begin(state, pid)["ok"] is True
    assert jobs.current_stage(state) == "approach"
    # `knew_the_rota` needs `premise_cased: {min: 1}`; nothing has been cased.
    assert "knew_the_rota" not in jobs.legal_flashbacks(state)
    out = jobs.flashback(state, "knew_the_rota")
    assert out["ok"] is False and out["message"]
    assert jobs.active(state)["shifts"] == {}
    assert jobs.active(state)["used_flashbacks"] == []


def test_a_flashback_is_never_offered_when_unaffordable(plain: Path) -> None:
    state = _world()
    pid = _house(state)
    _cased_once(state, pid)  # meets `premise_cased: {min: 1}`, earns 1 prep
    assert jobs.begin(state, pid)["ok"] is True
    assert "knew_the_rota" in jobs.legal_flashbacks(state)
    apply_effect(state, {"type": "job_prep", "delta": -state.jobs["prep"]})
    assert state.jobs["prep"] == 0
    assert "knew_the_rota" not in jobs.legal_flashbacks(state)
    out = jobs.flashback(state, "knew_the_rota")
    assert out["ok"] is False


def test_a_flashback_is_offered_once_requires_and_cost_both_hold(plain: Path) -> None:
    state = _world()
    pid = _house(state)
    _cased_once(state, pid)
    assert jobs.begin(state, pid)["ok"] is True
    assert jobs.current_stage(state) == "approach"
    assert "knew_the_rota" in jobs.legal_flashbacks(state)
    # `planted_tool` needs `premise_cased: {min: 2}` and only applies at
    # entry/score -- neither holds yet.
    assert "planted_tool" not in jobs.legal_flashbacks(state)
    # `bribed_servant` only applies inside.
    assert "bribed_servant" not in jobs.legal_flashbacks(state)


def test_a_flashback_is_used_at_most_once_per_job(plain: Path) -> None:
    state = _world()
    pid = _house(state)
    _cased_once(state, pid)
    assert jobs.begin(state, pid)["ok"] is True
    assert "knew_the_rota" in jobs.legal_flashbacks(state)
    out = jobs.flashback(state, "knew_the_rota")
    assert out["ok"] is True
    assert "knew_the_rota" not in jobs.legal_flashbacks(state)
    assert jobs.active(state)["used_flashbacks"] == ["knew_the_rota"]
    again = jobs.flashback(state, "knew_the_rota")
    assert again["ok"] is False


# ---------------------------------------------------------------------------
# What it does
# ---------------------------------------------------------------------------


def test_a_shift_flashback_moves_the_band_by_exactly_its_effect(
    plain: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = _world()
    pid = _house(state, security=())
    _cased_once(state, pid)
    _cased_once(state, pid)  # `premise_cased: {min: 2}` for `planted_tool`
    assert jobs.begin(state, pid)["ok"] is True
    _rolls(monkeypatch, "success")
    _walk_to(state, "entry")
    before, _ = jobs.band_for(state, "entry")
    out = jobs.flashback(state, "planted_tool")
    assert out["ok"] is True
    after, reasons = jobs.band_for(state, "entry")
    assert out["band_before"] == before
    assert out["band_after"] == after
    assert after == checks.shift_band(before, FLASHBACKS["planted_tool"]["effect"]["shift"])
    assert jobs._BANKED_REASON in reasons
    assert jobs.active(state)["shifts"] == {"entry": -2}


def test_a_remove_obstacle_flashback_initialises_inside_the_same_way_a_roll_would(
    plain: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = _world()
    pid = _open(state, security=("yard_dog",))
    apply_effect(state, {"type": "job_prep", "delta": 3})
    quests.QuestEngine.observe(state)  # `bribed_servant` needs `visited: {district}`
    _rolls(monkeypatch, "success")
    _walk_to(state, "inside")
    household = list(premises.get(state, pid)["household"])
    assert "obstacles" not in jobs.active(state)
    out = jobs.flashback(state, "bribed_servant")
    assert out["ok"] is True
    # The obstacle list is read once, lazily, the same as a roll would read
    # it -- then the flashback's own effect removes the first one.
    assert jobs.active(state)["obstacles"] == (household + ["yard_dog"])[1:]


def test_a_remove_obstacle_flashback_offered_off_inside_is_a_load_fault(
    tmp_path: Path,
) -> None:
    doc = MALFORMED["a remove_obstacle flashback offered outside inside"]
    set_overlay({"paths": _paths(tmp_path, doc)})
    try:
        with pytest.raises(ValueError, match="remove_obstacle.*only applies at `inside`"):
            jobs.spec()
    finally:
        set_overlay(None)


def test_job_stage_refuses_an_obstacles_write_off_inside(plain: Path) -> None:
    # A second, cheap belt under the loader fault above: even a stray write
    # for any OTHER stage never reaches `state.jobs` -- so a bug that got
    # past the loader (or a future caller) still cannot skip a whole `inside`
    # stage by pre-seeding its obstacle list from elsewhere.
    state = _world()
    pid = _house(state)
    assert jobs.begin(state, pid)["ok"] is True
    assert jobs.current_stage(state) == "approach"
    refused = apply_effect(
        state, {"type": "job_stage", "stage": "approach", "obstacles": ["ghost"]}
    )
    assert refused["ok"] is False
    assert "obstacles" not in jobs.active(state)


# ---------------------------------------------------------------------------
# No time, ever
# ---------------------------------------------------------------------------


def test_a_flashback_never_advances_time(
    plain: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from engine.game import clock

    state = _world()
    pid = _house(state)
    _cased_once(state, pid)
    assert jobs.begin(state, pid)["ok"] is True
    calls: list[Any] = []
    monkeypatch.setattr(clock, "advance_time", lambda *a, **k: calls.append((a, k)))
    when = (state.world_day, state.world_hour)
    out = jobs.flashback(state, "knew_the_rota")
    assert out["ok"] is True
    assert calls == []
    assert (state.world_day, state.world_hour) == when


# ---------------------------------------------------------------------------
# Exposure: a real witness, and only with a Law
# ---------------------------------------------------------------------------


def test_exposure_makes_a_real_named_witness_with_one_job_draw(
    lawful: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from engine.game import rng as rng_module
    from engine.world.npc_sim import display_name

    state = _world()
    pid = _open(state, security=())
    apply_effect(state, {"type": "job_prep", "delta": 3})
    quests.QuestEngine.observe(state)  # the district the job is in is now "visited"
    real_world_rng = rng_module.world_rng
    draws: list[str] = []

    def spy(st: GameState, stream: str):
        draws.append(stream)
        return real_world_rng(st, stream)

    monkeypatch.setattr(rng_module, "world_rng", spy)
    _rolls(monkeypatch, "success", "success")
    _walk_to(state, "inside")
    household = list(premises.get(state, pid)["household"])
    out = jobs.flashback(state, "bribed_servant")
    assert out["ok"] is True
    assert out["exposure_witness"]
    assert draws.count(JOB) == 1
    rows = state.law.get("witnessed") or []
    matched = [r for r in rows if r.get("deed") == "burglary" and r.get("npc") in household]
    assert matched, state.law
    assert out["exposure_witness"] == display_name(matched[-1]["npc"], state)


def test_exposure_writes_nothing_without_a_law(
    plain: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = _world()
    pid = _open(state, security=())
    apply_effect(state, {"type": "job_prep", "delta": 3})
    quests.QuestEngine.observe(state)
    _rolls(monkeypatch, "success", "success")
    _walk_to(state, "inside")
    assert state.law == {}
    out = jobs.flashback(state, "bribed_servant")
    assert out["ok"] is True
    assert "exposure_witness" not in out
    assert state.law == {}


# ---------------------------------------------------------------------------
# The verb, the skill, the narration
# ---------------------------------------------------------------------------


def test_verb_mapping() -> None:
    assert intents.SKILL_FOR_ACTION["flashback"] == "call_flashback"
    assert intents.REFUSAL_KEY_FOR_ACTION["flashback"] == "ok"
    assert intents.to_tool_call(GameState(), {"action": "flashback", "target": "knew_the_rota"}) == (
        "call_flashback", {"kind": "knew_the_rota"})


def test_the_flashback_verb_offers_exactly_legal_flashbacks(plain: Path) -> None:
    state = _world()
    pid = _house(state)
    _cased_once(state, pid)
    assert jobs.begin(state, pid)["ok"] is True
    verbs = _verbs(state)
    assert set(verbs) <= JOB_VERBS
    assert verbs["flashback"] == ("knew_the_rota",)
    verb = intents.find_verb(intents.legal_intents(state), "flashback")
    assert verb.options == (("knew_the_rota", FLASHBACKS["knew_the_rota"]["label"]),)


def test_flashback_intent_executes_end_to_end_and_narrates_without_ids(plain: Path) -> None:
    from engine.agents.prompts import summarise_receipt
    from engine.agents.tool_dispatcher import execute_intent
    from engine.game.engine import GameEngine

    state = _world()
    pid = _house(state)
    _cased_once(state, pid)
    assert jobs.begin(state, pid)["ok"] is True
    engine = GameEngine(state)
    (receipt,) = execute_intent({"action": "flashback", "target": "knew_the_rota"}, engine)
    assert receipt["success"] is True and not receipt.get("refused"), receipt
    _no_ids_or_numbers(summarise_receipt(receipt))
    (refused,) = execute_intent({"action": "flashback", "target": "knew_the_rota"}, engine)
    assert refused.get("refused") is True


def test_flashback_is_not_a_rolling_skill() -> None:
    from engine.agents.evaluator import ROLLING_SKILLS

    assert "call_flashback" not in ROLLING_SKILLS


# ---------------------------------------------------------------------------
# A story without jobs is untouched
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("kind", NO_JOBS)
def test_flashbacks_are_inert_where_jobs_are_undeclared(kind: str, tmp_path: Path) -> None:
    with no_jobs_story(kind, tmp_path) as location:
        state = GameState(rng_seed=42, location_id=location)
        state.procgen = generate_world(42)
        set_clock(state, day=1, hour=9)
        assert not jobs.declared()
        assert jobs.legal_flashbacks(state) == []
        refused = jobs.flashback(state, "anything")
        assert refused["ok"] is False
        assert state.jobs == {}


def test_casing_pays_no_prep_where_jobs_are_undeclared_but_premises_are(
    tmp_path: Path,
) -> None:
    # The flagship has no `paths.premises` at all, so only "law-only" -- the
    # synthetic control with premises and a Law but no jobs -- can case here.
    with no_jobs_story("law-only", tmp_path) as location:
        state = GameState(rng_seed=42, location_id=location)
        state.procgen = generate_world(42)
        set_clock(state, day=1, hour=9)
        assert not jobs.declared()
        pid = str(premises.at(state, location)[0]["id"])
        before = copy.deepcopy(state.jobs)
        out = premises.case(state, pid)
        assert out["ok"] is True
        assert state.jobs == before == {}
