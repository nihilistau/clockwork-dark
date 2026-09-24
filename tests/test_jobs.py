"""
Jobs, part one: the data, the state, and opening a job.

THE SHAPE. ``paths.jobs`` names ONE YAML file (the contract is in
docs/superpowers/plans/2026-09-24-v0.11.0-jobs.md): five derived stages, the
band each premise tier starts from, the entry approaches, what each security
feature and carried tool does to a stage, the alarm and prep meters, the
flashbacks and the anchored premises' extra stages. ``burgle <premise>``
opens a job held on ``state.jobs["active"]`` through the ``job_open`` effect;
``job_close`` ends it, and a score carried out (``clean``/``noisy``) marks the
premise robbed so ``burgle`` never offers it again.

WHAT THESE TESTS HOLD. The loader accepts the contract and rejects each
malformed file loudly, naming the file -- a jobs file that loads, validates
and changes nothing is the inert shape this repo has shipped before. A story
that declares no jobs keeps an empty ``jobs`` and never sees the verb. The
verb offers exactly the unrobbed premises of the district. An open job owns
the turn -- ``legal_intents`` offers only job verbs and ``scene_owns_turn``
says so, which is what keeps the Law's patrol from stopping a player mid-
burglary. Every refusal is ``ok: False`` and spends no time.

Built on test_premises.py's synthetic directory, so the engine is proven
apart from any one story's content. HUE & CRY declares jobs (its own tests
live in test_hue_and_cry.py), so it is NOT a "story without jobs" control:
the byte-identical controls here are the flagship and the synthetic
premises-and-Law story, `law_only_paths`.

Version: v0.1.1 [2026-09-24]
"""

from __future__ import annotations

import copy
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import pytest
import yaml

from engine.config import set_overlay
from engine.game import encounter, intents
from engine.game.clock import advance_time, set_clock
from engine.game.effects import apply_effect
from engine.game.procgen import generate_world
from engine.game.state import GameState
from engine.world import jobs, law, premises

from test_law import SPEC as _LAW_BASE
from test_law_arrest import ENCOUNTERS, WATCH, _always, _hunted
from test_premises import _build

SQUARE = "edgewood_square"
MARKET = "millhaven_market"
MILL = "prem_mill_house"
FIVE = ["approach", "entry", "inside", "score", "getaway"]
#: The verbs an open job may offer; the assertion is that nothing OUTSIDE
#: this set is offered.
JOB_VERBS = {"job", "abort", "flashback"}

JOBS_SPEC: dict[str, Any] = {
    "stages": {name: {"hours": 1} for name in FIVE},
    "tier_band": {1: "easy", 2: "standard", 3: "hard", 4: "severe", 5: "legendary"},
    "entries": {
        "door": {"skill": "stealth", "shift": 0, "label": "the door"},
        "window": {"skill": "stealth", "shift": 0, "label": "a window"},
        "roof": {"skill": "survival", "shift": 1, "label": "over the roof", "hurts": True},
        "cellar": {"skill": "nerve", "shift": 0, "label": "through the cellar", "hurts": True},
    },
    "approach": {"skill": "stealth", "shift": -1},
    "inside": {
        "awake": {"skill": "stealth", "shift": 0},
        "asleep": {"skill": "stealth", "shift": -2},
    },
    "score": {"skill": "craft", "shift": 0, "draws": {1: 1, 2: 1, 3: 2, 4: 2, 5: 3}},
    "getaway": {"skill": "stealth", "shift": -1},
    # Security ids the synthetic premises declare: townhouse (good_lock,
    # yard_dog) and the mill_house anchor (mill_dog).
    "features": {
        "good_lock": {"stage": "entry", "entries": ["door"], "shift": 1, "known_shift": 0},
        "yard_dog": {"stage": "inside", "obstacle": True, "known_shift": -1},
        "mill_dog": {"stage": "inside", "shift": 1, "known_shift": 1},
    },
    "tools": {
        "bent_nail": {"stage": ["entry", "score"], "entries": ["door", "cellar"], "shift": -1},
        "hand_lantern": {"stage": ["getaway"], "shift": -1, "consumed": True},
    },
    "alarm": {
        "max": 4,
        "bands": ["quiet", "uneasy", "stirring", "roused"],
        "on_fail": 1,
        "on_crit_fail": 2,
        "watch_delay_hours": 2,
        "deed": "burglary",
    },
    "prep": {"max": 3, "per_case": 1, "bands": ["none", "a little", "some", "plenty"]},
    "flashbacks": {
        "bribed_servant": {
            "label": "you bribed a servant last week",
            "stage": ["inside"],
            "requires": {"visited": "{district}"},
            "cost": {"prep": 1, "gold": 5},
            "effect": {"remove_obstacle": 1},
            "exposure": "household",
        },
        "planted_tool": {
            "label": "you left a bar hidden by the back wall",
            "stage": ["entry", "score"],
            "requires": {"premise_cased": {"min": 2}},
            "cost": {"prep": 1},
            "effect": {"shift": -2},
        },
        "knew_the_rota": {
            "label": "you knew the rota",
            "stage": ["approach", "inside"],
            "requires": {"all": [{"premise_cased": {"min": 1}}, {"job": {"open": True}}]},
            "cost": {"prep": 1},
            "effect": {"shift": -1},
        },
    },
    "anchors": {
        "mill_house": {
            "after": "inside",
            "stages": [
                {
                    "id": "bell_floor",
                    "label": "the grinding floor on its springs",
                    "skill": "nerve",
                    "band": "severe",
                    "hours": 1,
                }
            ],
        }
    },
}

#: The shared synthetic Law, plus the deed a raised alarm files.
LAW_SPEC = copy.deepcopy(_LAW_BASE)
LAW_SPEC["deeds"]["burglary"] = {"severity": 3}
LAW_SPEC["arrest"]["encounter"] = "watch_stop"


def _dump(path: Path, doc: Any) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = doc if isinstance(doc, str) else yaml.safe_dump(doc, sort_keys=False)
    path.write_text(text, encoding="utf-8")
    return str(path)


def _paths(tmp_path: Path, jobs_doc: Any = None, *, lawful: bool = False,
           with_premises: bool = True) -> dict[str, str]:
    paths = {"jobs": _dump(tmp_path / "jobs.yaml", JOBS_SPEC if jobs_doc is None else jobs_doc)}
    if with_premises:
        paths["premises"] = str(_build(tmp_path / "premises"))
    if lawful:
        enc_dir = tmp_path / "encounters"
        _dump(enc_dir / "watch.yaml", ENCOUNTERS)
        paths["law"] = _dump(tmp_path / "law.yaml", LAW_SPEC)
        paths["encounters"] = str(enc_dir)
    return paths


def law_only_paths(tmp_path: Path) -> dict[str, str]:
    """
    A synthetic story with premises, a Law and its arrest scene, and NO jobs:
    the shape HUE & CRY had at v0.10.0, kept here because HUE & CRY itself
    declares jobs from Task 6 on and would stop being a control.
    """
    paths = _paths(tmp_path, lawful=True)
    paths.pop("jobs")
    return paths


#: The stories that declare no jobs and must be untouched by them.
NO_JOBS = ("clockwork-dark", "law-only")


@contextmanager
def no_jobs_story(kind: str, tmp_path: Path) -> Iterator[str]:
    """Activate one of ``NO_JOBS``; yields the location to stand in."""
    from engine.games import registry

    if kind == "clockwork-dark":
        registry.activate(kind)
        try:
            yield SQUARE
        finally:
            registry.deactivate()
        return
    set_overlay({"paths": law_only_paths(tmp_path)})
    try:
        assert law.declared()
        yield SQUARE
    finally:
        set_overlay(None)


@pytest.fixture()
def declared(tmp_path: Path) -> Iterator[Path]:
    set_overlay({"paths": _paths(tmp_path)})
    try:
        yield tmp_path
    finally:
        set_overlay(None)


@pytest.fixture()
def lawful(tmp_path: Path) -> Iterator[Path]:
    set_overlay({"paths": _paths(tmp_path, lawful=True)})
    try:
        yield tmp_path
    finally:
        set_overlay(None)


def _world(seed: int = 42, location: str = SQUARE) -> GameState:
    state = GameState(rng_seed=seed, location_id=location)
    state.procgen = generate_world(seed)
    set_clock(state, day=1, hour=22)
    return state


def _verbs(state: GameState) -> dict[str, tuple[str, ...]]:
    return {v.action: v.targets for v in intents.legal_intents(state)}


def _here(state: GameState) -> list[str]:
    return [str(p["id"]) for p in premises.at(state, state.location_id)]


def _rob(state: GameState, premise_id: str, outcome: str = "clean") -> None:
    opened = apply_effect(state, {"type": "job_open", "premise": premise_id,
                                  "stages": jobs.stages_for(state, premise_id)})
    assert opened["ok"], opened
    closed = apply_effect(state, {"type": "job_close", "outcome": outcome})
    assert closed["ok"], closed


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def test_the_contract_loads(declared: Path) -> None:
    assert jobs.declared()
    spec = jobs.spec()
    assert list(spec["stages"]) == FIVE
    assert spec["stages"]["entry"]["hours"] == 1
    assert spec["tier_band"][3] == "hard"
    assert spec["entries"]["roof"] == {"skill": "survival", "shift": 1,
                                       "label": "over the roof", "hurts": True}
    # `hurts` is optional and defaults to false.
    assert spec["entries"]["door"]["hurts"] is False
    # A single stage name is normalised to a list, so a reader has one shape.
    assert spec["features"]["good_lock"]["stage"] == "entry"
    assert spec["tools"]["hand_lantern"]["stage"] == ["getaway"]
    assert spec["tools"]["hand_lantern"]["consumed"] is True
    assert spec["alarm"]["max"] == 4 and spec["alarm"]["deed"] == "burglary"
    assert spec["prep"]["bands"][0] == "none"
    assert spec["flashbacks"]["planted_tool"]["cost"] == {"prep": 1, "gold": 0}
    assert spec["anchors"]["mill_house"]["stages"][0]["id"] == "bell_floor"


def _mutated(**changes: Any) -> dict[str, Any]:
    doc = copy.deepcopy(JOBS_SPEC)
    for dotted, value in changes.items():
        node = doc
        *parents, leaf = dotted.split("__")
        for key in parents:
            node = node[key]
        node[leaf] = value
    return doc


MALFORMED = {
    "an unknown band": _mutated(tier_band={1: "impossible", 2: "standard", 3: "hard"}),
    "an unknown skill": _mutated(
        entries__door={"skill": "juggling", "shift": 0, "label": "the door"}
    ),
    "a features key no premise declares": _mutated(
        features={"greasy_step": {"stage": "entry", "entries": ["door"], "shift": 1}}
    ),
    "a tool not in the registry": _mutated(
        tools={"lockpicks": {"stage": ["entry"], "shift": -1}}
    ),
    "an anchors key that is not an anchored premise": _mutated(
        anchors={"townhouse": {"after": "inside", "stages": []}}
    ),
    "a flashback requires with an unknown predicate": _mutated(
        flashbacks__planted_tool__requires={"moon_phase": "full"}
    ),
    "an unknown predicate nested in a group": _mutated(
        flashbacks__planted_tool__requires={"any": [{"visited": "x"}, {"moon_phase": 1}]}
    ),
    "alarm bands of the wrong length": _mutated(alarm__bands=["quiet", "uneasy", "roused"]),
    "prep bands of the wrong length": _mutated(prep__bands=["none", "plenty"]),
    "a stage that is not one of the five": _mutated(
        stages={**{n: {"hours": 1} for n in FIVE}, "tea_break": {"hours": 1}}
    ),
    "a missing stage": _mutated(stages={n: {"hours": 1} for n in FIVE[:-1]}),
    "a tier some premise has with no band": _mutated(tier_band={1: "easy", 2: "standard"}),
    "a feature on an unknown stage": _mutated(
        features__good_lock={"stage": "lobby", "shift": 1}
    ),
    "a feature naming an unknown entry": _mutated(
        features__good_lock={"stage": "entry", "entries": ["chimney"], "shift": 1}
    ),
    "an anchor stage with an unknown band": _mutated(
        anchors__mill_house__stages=[{"id": "x", "label": "x", "skill": "nerve",
                                      "band": "brutal", "hours": 1}]
    ),
    "an anchor spliced after an unknown stage": _mutated(anchors__mill_house__after="lobby"),
    "a flashback with no effect": _mutated(flashbacks__planted_tool__effect={}),
    "a flashback with an unknown exposure": _mutated(
        flashbacks__bribed_servant__exposure="everyone"
    ),
    "a remove_obstacle flashback offered outside inside": _mutated(
        flashbacks__bribed_servant__stage=["entry"]
    ),
    "a remove_obstacle flashback effect of less than one": _mutated(
        flashbacks__bribed_servant__effect={"remove_obstacle": 0}
    ),
    "an entry whose hurts is not a bool": _mutated(
        entries__roof={"skill": "survival", "shift": 1, "label": "over the roof", "hurts": "yes"}
    ),
    "not valid YAML": "stages: [unclosed",
}


@pytest.mark.parametrize("fault", sorted(MALFORMED))
def test_a_malformed_file_fails_naming_itself(tmp_path: Path, fault: str) -> None:
    paths = _paths(tmp_path, MALFORMED[fault])
    set_overlay({"paths": paths})
    try:
        with pytest.raises(ValueError) as caught:
            jobs.spec()
        assert paths["jobs"] in str(caught.value), caught.value
    finally:
        set_overlay(None)


def test_a_jobs_file_in_a_story_without_premises_fails_naming_itself(tmp_path: Path) -> None:
    """Jobs open on premises; a story with none has nothing a job could rob."""
    paths = _paths(tmp_path, with_premises=False)
    set_overlay({"paths": paths})
    try:
        with pytest.raises(ValueError) as caught:
            jobs.spec()
        assert paths["jobs"] in str(caught.value)
    finally:
        set_overlay(None)


def test_a_declared_file_that_is_missing_is_a_broken_install(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    missing = str(tmp_path / "nowhere.yaml")
    set_overlay({"paths": {**paths, "jobs": missing}})
    try:
        with pytest.raises(ValueError) as caught:
            jobs.spec()
        assert missing in str(caught.value)
    finally:
        set_overlay(None)


def test_alarm_deed_must_be_a_law_deed_when_the_law_is_declared(tmp_path: Path) -> None:
    doc = _mutated(alarm__deed="treason")
    paths = _paths(tmp_path, doc, lawful=True)
    set_overlay({"paths": paths})
    try:
        with pytest.raises(ValueError) as caught:
            jobs.spec()
        assert paths["jobs"] in str(caught.value)
    finally:
        set_overlay(None)


def test_alarm_deed_is_not_checked_without_a_law(declared: Path) -> None:
    """With no watch there is nobody to file with; the name is not an error."""
    assert not law.declared()
    assert jobs.spec()["alarm"]["deed"] == "burglary"


def test_the_lawful_contract_loads(lawful: Path) -> None:
    assert law.declared() and jobs.spec()["alarm"]["deed"] == "burglary"


# ---------------------------------------------------------------------------
# Undeclared: the flagship
# ---------------------------------------------------------------------------


def test_an_undeclared_story_has_no_jobs() -> None:
    assert not jobs.declared()
    assert jobs.spec() == {}
    state = GameState(location_id=SQUARE)
    assert state.jobs == {}
    assert jobs.active(state) is None
    before = state.world_clock_hours
    out = jobs.begin(state, "prem_edgewood_square_1")
    assert out["ok"] is False and out["message"]
    assert state.world_clock_hours == before
    for effect in ({"type": "job_open", "premise": "p", "stages": FIVE},
                   {"type": "job_close", "outcome": "clean"},
                   {"type": "job_prep", "delta": 1}):
        refused = apply_effect(state, effect)
        assert refused["ok"] is False and refused["message"]
    assert state.jobs == {}
    assert jobs.legal_flashbacks(state) == []
    refused = jobs.flashback(state, "anything")
    assert refused["ok"] is False and refused["message"]


def test_the_flagship_save_round_trips_with_empty_jobs() -> None:
    state = GameState()
    data = state.to_save_dict()
    assert data["jobs"] == {}
    assert GameState.from_dict(data).jobs == {}
    # A save written before jobs existed loads as "no job ever run".
    data.pop("jobs")
    assert GameState.from_dict(data).jobs == {}
    assert "jobs" not in state.to_client_dict() and "job" not in state.to_client_dict()


def _surface(state: GameState) -> tuple[Any, str, dict[str, Any]]:
    from engine.agents import prompts

    return (
        intents.legal_intents(state),
        prompts.world_state_block(state, {}),
        state.to_client_dict(),
    )


@pytest.mark.parametrize("kind", NO_JOBS)
def test_a_story_without_jobs_is_unchanged(
    kind: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    The flagship, and a synthetic story with premises and a Law but no jobs,
    see no ``burgle``. Their state (apart from the empty ``jobs`` field),
    intents, prompt and payload are byte-identical with every job hook
    forced off -- across a stretch of in-game time too, where ``jobs.tick``
    would run if anything reached it.
    """
    with no_jobs_story(kind, tmp_path) as location:
        assert not jobs.declared()
        assert law.declared() is (kind == "law-only")
        state = GameState(rng_seed=42, location_id=location)
        state.procgen = generate_world(42)
        set_clock(state, day=1, hour=8)
        twin = copy.deepcopy(state)
        assert "burgle" not in _verbs(state)
        assert not intents.scene_owns_turn(state)
        before = _surface(state)
        advance_time(state, 6)
        after = _surface(state)
        saved = state.to_save_dict()

        def boom(*args: Any, **kwargs: Any) -> None:
            raise AssertionError("a job hook ran in a story without jobs")

        monkeypatch.setattr(intents, "_burgle", lambda s: None)
        monkeypatch.setattr(intents, "_job_open", lambda s: False)
        monkeypatch.setattr(jobs, "tick", boom)
        monkeypatch.setattr(jobs, "active", boom)
        assert _surface(twin) == before
        advance_time(twin, 6)
        assert _surface(twin) == after
        assert saved["jobs"] == {}
        assert twin.to_save_dict() == saved


# ---------------------------------------------------------------------------
# The verb
# ---------------------------------------------------------------------------


def test_burgle_offers_exactly_the_unrobbed_premises_here(declared: Path) -> None:
    state = _world()
    here = _here(state)
    assert len(here) == 3
    assert list(_verbs(state)["burgle"]) == here[: intents._MAX_OPTIONS]
    _rob(state, here[0])
    assert list(_verbs(state)["burgle"]) == here[1:]
    # An aborted job carried nothing out: the house is still there to rob.
    _rob(state, here[1], outcome="aborted")
    assert list(_verbs(state)["burgle"]) == here[1:]


def test_burgle_labels_are_house_names_never_ids(declared: Path) -> None:
    state = _world()
    verb = intents.find_verb(intents.legal_intents(state), "burgle")
    assert verb is not None
    for target, label in verb.options:
        assert "prem_" not in label
        assert premises.get(state, target)["name"] in label


def test_burgle_is_capped(declared: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state = _world()
    many = [dict(premises.at(state, SQUARE)[0], id=f"prem_many_{i}") for i in range(12)]
    state.procgen.premises = many
    assert len(_verbs(state)["burgle"]) == intents._MAX_OPTIONS


def test_burgle_is_not_offered_where_there_are_no_houses(declared: Path) -> None:
    state = _world(location="forest_clearing")
    assert "burgle" not in _verbs(state)


def test_burgle_is_not_offered_in_custody(lawful: Path) -> None:
    state = _world()
    apply_effect(state, {"type": "arrest"})
    state.location_id = SQUARE
    assert "burgle" not in _verbs(state)


def test_verb_mapping() -> None:
    assert intents.SKILL_FOR_ACTION["burgle"] == "begin_job"
    assert intents.REFUSAL_KEY_FOR_ACTION["burgle"] == "ok"
    assert intents.to_tool_call(GameState(), {"action": "burgle", "target": "prem_x_1"}) == (
        "begin_job",
        {"premise_id": "prem_x_1"},
    )


# ---------------------------------------------------------------------------
# Opening a job
# ---------------------------------------------------------------------------


def test_begin_opens_a_job_with_the_five_stages(declared: Path) -> None:
    state = _world()
    pid = _here(state)[0]
    before = state.world_clock_hours
    out = jobs.begin(state, pid)
    assert out["ok"] is True, out
    assert out["job_id"] == "j1" and out["premise"] == pid
    assert out["stages"] == FIVE
    # Opening a job is deciding to go; the approach stage spends the hours.
    assert state.world_clock_hours == before
    active = jobs.active(state)
    assert active is not None
    assert active["id"] == "j1" and active["premise"] == pid and active["district"] == SQUARE
    assert active["stages"] == FIVE and active["at"] == 0 and active["alarm"] == 0
    assert active["raised_at"] is None
    assert state.jobs["seq"] == 1


def test_an_anchored_premise_splices_its_stages(declared: Path) -> None:
    state = _world(location=MARKET)
    assert premises.get(state, MILL)["anchor"] is True
    spliced = ["approach", "entry", "inside", "bell_floor", "score", "getaway"]
    assert jobs.stages_for(state, MILL) == spliced
    out = jobs.begin(state, MILL)
    assert out["ok"] is True and out["stages"] == spliced
    assert jobs.active(state)["stages"] == spliced
    # A generated premise in the same district keeps the plain five.
    generated = next(p for p in _here(state) if p != MILL)
    assert jobs.stages_for(state, generated) == FIVE


def test_job_close_records_the_score_and_the_last_job(declared: Path) -> None:
    state = _world()
    pid = _here(state)[0]
    state.turn_number = 7
    jobs.begin(state, pid)
    out = apply_effect(state, {"type": "job_close", "outcome": "noisy"})
    assert out["ok"] is True
    assert jobs.active(state) is None
    assert state.jobs["robbed"] == [pid]
    assert state.jobs["last"] == {"id": "j1", "premise": pid, "outcome": "noisy", "turn": 7}
    # The next job gets the next id.
    assert jobs.begin(state, _here(state)[1])["job_id"] == "j2"


def test_an_aborted_close_robs_nothing(declared: Path) -> None:
    state = _world()
    jobs.begin(state, _here(state)[0])
    apply_effect(state, {"type": "job_close", "outcome": "aborted"})
    assert state.jobs.get("robbed", []) == []
    assert state.jobs["last"]["outcome"] == "aborted"


def test_job_effects_refuse_what_they_cannot_do(declared: Path) -> None:
    state = _world()
    assert apply_effect(state, {"type": "job_close", "outcome": "clean"})["ok"] is False
    assert apply_effect(state, {"type": "job_open", "premise": "prem_nowhere",
                                "stages": FIVE})["ok"] is False
    assert apply_effect(state, {"type": "job_open", "premise": _here(state)[0],
                                "stages": []})["ok"] is False
    jobs.begin(state, _here(state)[0])
    snapshot = copy.deepcopy(state.jobs)
    assert apply_effect(state, {"type": "job_open", "premise": _here(state)[1],
                                "stages": FIVE})["ok"] is False
    assert apply_effect(state, {"type": "job_close", "outcome": "triumphant"})["ok"] is False
    assert state.jobs == snapshot


# ---------------------------------------------------------------------------
# Refusals: ok False, no hours
# ---------------------------------------------------------------------------


def _refused(state: GameState, premise_id: str) -> dict[str, Any]:
    before_hours = state.world_clock_hours
    before_jobs = copy.deepcopy(state.jobs)
    out = jobs.begin(state, premise_id)
    assert out["ok"] is False, out
    assert out["message"]
    assert "prem_" not in out["message"]
    assert state.world_clock_hours == before_hours
    assert state.jobs == before_jobs
    return out


def test_begin_refuses_an_unknown_premise(declared: Path) -> None:
    _refused(_world(), "prem_nowhere_9")


def test_begin_refuses_a_premise_in_another_district(declared: Path) -> None:
    _refused(_world(), MILL)


def test_begin_refuses_a_robbed_premise(declared: Path) -> None:
    state = _world()
    pid = _here(state)[0]
    _rob(state, pid)
    _refused(state, pid)


def test_begin_refuses_while_a_job_is_open(declared: Path) -> None:
    state = _world()
    jobs.begin(state, _here(state)[0])
    _refused(state, _here(state)[1])


def test_begin_refuses_in_custody(lawful: Path) -> None:
    state = _world()
    apply_effect(state, {"type": "arrest"})
    state.location_id = SQUARE  # custody, not the district, must be what refuses
    out = _refused(state, _here(state)[0])
    assert "district" not in out["message"]


def test_begin_refuses_while_a_scene_owns_the_turn(lawful: Path) -> None:
    state = _world()
    encounter.begin(state, "watch_stop")
    _refused(state, _here(state)[0])


def test_an_illegal_burgle_intent_is_refused_before_the_skill(declared: Path) -> None:
    from engine.agents.tool_dispatcher import execute_intent
    from engine.game.engine import GameEngine

    state = _world()
    receipts = execute_intent({"action": "burgle", "target": MILL}, GameEngine(state))
    assert receipts[0]["refused"] is True
    assert jobs.active(state) is None


def test_a_burgle_intent_executes_end_to_end(declared: Path) -> None:
    from engine.agents.prompts import summarise_receipt
    from engine.agents.tool_dispatcher import execute_intent
    from engine.game.engine import GameEngine

    state = _world()
    pid = _here(state)[0]
    receipts = execute_intent({"action": "burgle", "target": pid}, GameEngine(state))
    assert receipts and receipts[0]["success"] is True, receipts
    assert jobs.active(state)["premise"] == pid
    line = summarise_receipt(receipts[0])
    assert "prem_" not in line and "j1" not in line
    assert premises.get(state, pid)["name"] in line


# ---------------------------------------------------------------------------
# An open job owns the turn
# ---------------------------------------------------------------------------


def test_an_open_job_owns_the_turn(declared: Path) -> None:
    state = _world()
    ordinary = set(_verbs(state))
    assert {"burgle", "case", "travel", "rest"} <= ordinary
    assert not intents.scene_owns_turn(state)
    jobs.begin(state, _here(state)[0])
    assert intents.scene_owns_turn(state)
    assert set(_verbs(state)) <= JOB_VERBS


def test_the_patrol_does_not_stop_a_player_mid_burglary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    set_overlay({"paths": _paths(tmp_path, lawful=True)})
    try:
        state = _world()
        pid = _here(state)[0]
        state.procgen.npcs = copy.deepcopy(WATCH)
        _hunted(state)
        _always(monkeypatch)
        # Positive control: with no job open the same watchman knows the face.
        assert law.recognition(state)["recognised"] is True
        jobs.begin(state, pid)
        assert law.recognition(state) == {"recognised": False}
        assert law.patrol(state) is None
    finally:
        set_overlay(None)


# ---------------------------------------------------------------------------
# The predicates flashbacks and contracts will test
# ---------------------------------------------------------------------------


def test_the_job_predicates_are_in_the_shared_grammar(declared: Path) -> None:
    from engine.game.quests import evaluate_condition, predicate_names

    assert {"premise_cased", "premise_robbed", "job"} <= set(predicate_names())
    state = _world()
    pid, other = _here(state)[0], _here(state)[1]
    assert evaluate_condition(state, {"job": {"open": False}})
    assert not evaluate_condition(state, {"job": {"open": True}})
    # No job open and no premise named: there is nothing to have cased.
    assert not evaluate_condition(state, {"premise_cased": {"min": 1}})
    apply_effect(state, {"type": "intel", "premise": pid,
                         "intel": premises.unknown_ids(state, pid)[0]})
    assert evaluate_condition(state, {"premise_cased": {"min": 1, "premise": pid}})
    assert not evaluate_condition(state, {"premise_cased": {"min": 2, "premise": pid}})
    jobs.begin(state, pid)
    assert evaluate_condition(state, {"job": {"open": True}})
    assert evaluate_condition(state, {"premise_cased": {"min": 1}})
    apply_effect(state, {"type": "job_close", "outcome": "clean"})
    assert evaluate_condition(state, {"premise_robbed": {"premise": pid}})
    assert not evaluate_condition(state, {"premise_robbed": {"premise": other}})
    assert evaluate_condition(state, {"premise_robbed": {"district": SQUARE, "type": "townhouse"}})
    assert not evaluate_condition(state, {"premise_robbed": {"district": MARKET}})
