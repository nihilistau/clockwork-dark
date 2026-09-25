"""
A terminal death that ends in an epilogue, and the job/death seam.

THE GAP. ``death.yaml``'s only way to end a run was the flagship's
``terminal:`` block -- keyed on ``evil_phase`` and a mark flag -- and it set
``state.ended`` WITHOUT locking an ending, so a terminal death showed no
epilogue: the run stopped on a blank page. HUE & CRY's The Rope is exactly
"this death ends the story in that ending".

THE KEYS. ``terminal: {when: <condition>, ending: <ending id>}`` (additive).
``when`` is a condition in the shared grammar, read at the moment of death,
before any respawn. When it holds, the run ends and that ending is locked --
through the ``ending_lock`` effect with ``terminal: true``, which skips the
ending's own ``requires``/``completable`` because the death IS its
eligibility ("this death ends in The Rope" must always work) -- and its module
plays, so ``epilogue.for_state`` returns its cards. ``terminal: true`` is
honoured only while a death is being handled; anywhere else it is refused, so
no quest or card can use it to skip a gate. Otherwise: respawn, or the
flagship's evil_phase terminal, both unchanged.

THE SEAM. A respawn's hours run through ``advance_time``, and ``jobs.tick``
inside it can bring the watch -- closing the job ``caught`` and opening the
arrest scene. The dying scene used to be ended AFTER those hours, so the same
death's ``encounter.end`` closed the arrest scene it had just let open. The
dying scene now ends first.

Version: v0.1.0 [2026-09-25]
"""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any, Iterator

import pytest
import yaml

from engine.config import set_overlay
from engine.game import encounter, endings, epilogue
from engine.game.clock import set_clock
from engine.game.effects import apply_effect
from engine.game.state import GameState
from engine.world import jobs, law

from test_jobs import SQUARE, _dump, _paths
from test_jobs_stages import _open, _rolls, _walk_to, _world

_ROOT = Path(__file__).resolve().parents[1]

# ---------------------------------------------------------------------------
# A synthetic story: jobs, the Law and its arrest scene, two endings, a death
# ---------------------------------------------------------------------------

ENDINGS = {
    "version": 1,
    "fail_forward": "honest",
    "classes": {
        "honest": {"label": "Honest"},
        # A gate nothing ever sets. Locking this through the ordinary door is
        # refused; a terminal death must lock it anyway.
        "the_rope": {
            "label": "The Rope",
            "requires": {"flag": "rope_is_never_earned"},
            "beats": [{"id": "rope_seal", "text": "SEAL. The drop, and the laugh."}],
        },
    },
}

EPILOGUE_INDEX = {
    "version": 1,
    "prose_source": "epilogue_cards.yaml",
    "endings": [
        {"id": "honest", "class": "honest", "title": "Honest"},
        {"id": "the_rope", "class": "the_rope", "title": "The Rope"},
    ],
}

EPILOGUE_CARDS = {
    "version": 1,
    "cards": {
        "honest": {"title": "Honest", "card_m": "You left.", "card_g": "They forgot."},
        "the_rope": {"title": "The Rope", "card_m": "They hanged you.", "card_g": "It rained."},
    },
}

DEATH = {
    "version": 1,
    "threshold": 0,
    "respawn": {
        "location_id": SQUARE,
        # More than jobs' watch_delay_hours (2): the seam test needs a respawn
        # whose hours bring the watch.
        "hours": 3,
        "hp_fraction": 0.5,
        "text": "You wake on the square.",
    },
    "terminal": {
        "when": {"in_custody": True},
        "ending": "the_rope",
        "text": "They do not let you wake.",
    },
}


def _story(tmp_path: Path, death: Any = None) -> dict[str, str]:
    paths = _paths(tmp_path, lawful=True)
    rules = tmp_path / "rules"
    # The flagship's skill list, which is what these paths otherwise fall back
    # to: declaring `paths.rules` for death.yaml must not lose the skills.
    rules.mkdir(parents=True, exist_ok=True)
    shutil.copy(_ROOT / "games/clockwork-dark/data/rules/skills.yaml", rules / "skills.yaml")
    _dump(rules / "death.yaml", DEATH if death is None else death)
    paths["rules"] = str(rules)
    paths["endings"] = _dump(tmp_path / "endings.yaml", ENDINGS)
    epi = tmp_path / "epilogues"
    _dump(epi / "epilogue_index.yaml", EPILOGUE_INDEX)
    _dump(epi / "epilogue_cards.yaml", EPILOGUE_CARDS)
    paths["epilogues"] = str(epi)
    return paths


@pytest.fixture()
def story(tmp_path: Path) -> Iterator[Path]:
    set_overlay({"paths": _story(tmp_path)})
    try:
        yield tmp_path
    finally:
        set_overlay(None)


def _held(state: GameState) -> None:
    receipt = apply_effect(state, {"type": "arrest"})
    assert receipt["ok"] is True, receipt
    assert law.in_custody(state)


# ---------------------------------------------------------------------------
# The terminal ending
# ---------------------------------------------------------------------------


def test_a_death_while_held_locks_the_rope_and_shows_its_epilogue(story: Path) -> None:
    state = _world()
    _held(state)
    # The ordinary door is shut: the_rope's own gate has not been earned.
    assert "the_rope" not in endings.eligible(state).eligible
    state.stats.hp = 0

    death = encounter.check_death(state)

    assert death is not None and death["terminal"] is True and death["ended"] is True
    assert death["ending"] == "the_rope"
    assert state.ended is True
    assert endings.locked(state) == "the_rope"
    assert endings.module_ran(state) == "the_rope"
    shown = epilogue.for_state(state)
    assert shown is not None and shown.ending_id == "the_rope"
    assert shown.card_m == "They hanged you."
    # No respawn: the terminal death is not a setback with hours lost.
    assert state.stats.hp == 0 and "hours_lost" not in death


def test_a_death_outside_the_condition_respawns(story: Path) -> None:
    state = _world()
    state.stats.hp = 0

    death = encounter.check_death(state)

    assert death is not None and death["terminal"] is False and death["ended"] is False
    assert state.ended is False
    assert state.location_id == SQUARE and state.stats.hp > 0
    assert endings.locked(state) == endings.NONE_ID
    assert epilogue.for_state(state) is None


def test_the_terminal_lock_is_refused_outside_a_death(story: Path) -> None:
    """``terminal: true`` is the death's key, not a way round an ending's gate."""
    state = _world()
    refused = apply_effect(state, {"type": "ending_lock", "ending": "the_rope", "terminal": True})
    assert refused["ok"] is False
    assert endings.locked(state) == endings.NONE_ID
    # And the ordinary lock still honours the gate.
    assert apply_effect(state, {"type": "ending_lock", "ending": "the_rope"})["ok"] is False
    assert endings.locked(state) == endings.NONE_ID


def test_a_terminal_death_on_an_already_locked_run_does_not_relock(story: Path) -> None:
    state = _world()
    assert apply_effect(state, {"type": "ending_lock", "ending": "honest"})["ok"] is True
    _held(state)
    state.stats.hp = 0
    death = encounter.check_death(state)
    assert state.ended is True and death["terminal"] is True
    assert endings.locked(state) == "honest"


def test_a_terminal_lock_written_during_respawn_hours_is_refused(
    story: Path, monkeypatch
) -> None:
    """The bypass is the death's own lock, not the whole death: content that
    runs during a respawn's hours (an event, a card, a job tick) writing
    ``terminal: true`` is refused like anywhere else."""
    from engine.game import clock

    real = clock.advance_time
    written: list[dict[str, Any]] = []

    def hours(st: GameState, amount: float, *args: Any, **kwargs: Any) -> Any:
        written.append(apply_effect(
            st, {"type": "ending_lock", "ending": "the_rope", "terminal": True}))
        return real(st, amount, *args, **kwargs)

    monkeypatch.setattr(clock, "advance_time", hours)
    state = _world()
    state.stats.hp = 0

    death = encounter.check_death(state)

    assert death is not None and death["terminal"] is False
    assert written and written[0]["ok"] is False, written
    assert endings.locked(state) == endings.NONE_ID


def test_a_terminal_death_mid_job_closes_the_job_hurt_and_keeps_custody_rules(
    tmp_path: Path, monkeypatch
) -> None:
    """What a terminal death leaves: nothing respawned or moved, the run
    locked -- and a fall that killed closes the job ``hurt`` (the fall's own
    ``check_death`` returned a record)."""
    doc = copy.deepcopy(DEATH)
    doc["terminal"] = {"when": {"flag": "doomed"}, "ending": "the_rope",
                       "text": "They do not let you wake."}
    set_overlay({"paths": _story(tmp_path, doc)})
    try:
        state = _world()
        _open(state)
        _rolls(monkeypatch, "success", "failure")
        _walk_to(state, "entry")
        where = state.location_id
        state.flags["doomed"] = True
        state.stats.hp = 1

        out = jobs.resolve_stage(state, "cellar")

        assert state.ended is True and endings.locked(state) == "the_rope"
        assert out["outcome"] == "hurt" and out["closed"] is True, out
        assert jobs.active(state) is None
        assert state.jobs["last"]["outcome"] == "hurt"
        assert state.location_id == where and state.stats.hp == 0
    finally:
        set_overlay(None)


def test_a_terminal_death_in_a_round_closes_the_dying_scene_and_keeps_the_cell(
    story: Path, monkeypatch
) -> None:
    from engine.game import checks
    from types import SimpleNamespace

    state = _world()
    _held(state)
    lethal = {
        "id": "test_lethal", "band": "test", "intro": "", "triggers": {},
        "threat": {"name": "Something final", "resolve": 9},
        "approaches": {"die": {"skill": "nerve", "difficulty": "standard", "text": "Die"}},
        "outcomes": {"failure": {"text": "DOWN", "effects": [{"type": "hp", "delta": -999}]}},
    }
    real = encounter.get_definition
    monkeypatch.setattr(encounter, "get_definition",
                        lambda eid: lethal if eid == "test_lethal" else real(eid))
    monkeypatch.setattr(
        checks, "resolve",
        lambda state, skill, difficulty="standard", **kw: SimpleNamespace(
            degree="failure", summary="forced", margin=-6,
            to_dict=lambda: {"degree": "failure"}),
    )
    state.encounter = {}
    assert encounter.begin(state, "test_lethal")
    receipt = encounter.resolve_approach(state, "die")
    assert receipt["death"] and receipt["death"]["terminal"] is True
    assert state.ended is True and endings.locked(state) == "the_rope"
    assert not encounter.active(state)
    assert law.in_custody(state)


def test_a_finished_run_stops_dying(story: Path, caplog) -> None:
    """M2: once a terminal death has ended the run, hp stays at 0 and every
    later hour re-ran the terminal death -- another "You do not get up." and
    another refused lock, per hour."""
    import logging

    from engine.game.clock import advance_time

    state = _world()
    _held(state)
    state.stats.hp = 0
    assert encounter.check_death(state)["terminal"] is True
    caplog.set_level(logging.INFO)
    caplog.clear()

    assert encounter.check_death(state) is None
    advance_time(state, 3)
    assert "Terminal death" not in caplog.text, caplog.text
    assert "refused" not in caplog.text, caplog.text


# ---------------------------------------------------------------------------
# Validation: a load error naming the file
# ---------------------------------------------------------------------------


def _terminal(**block: Any) -> dict[str, Any]:
    doc = copy.deepcopy(DEATH)
    doc["terminal"] = block
    return doc


MALFORMED = {
    "unknown ending": _terminal(when={"in_custody": True}, ending="the_noose"),
    "unknown predicate": _terminal(when={"in_cutsody": True}, ending="the_rope"),
    "when is not a condition": _terminal(when="held", ending="the_rope"),
    "group beside a predicate": _terminal(
        when={"all": [{"in_custody": True}], "flag": "x"}, ending="the_rope"
    ),
    "when without ending": _terminal(when={"in_custody": True}),
    "ending without when": _terminal(ending="the_rope"),
    "mixed with the phase terminal": _terminal(
        when={"in_custody": True}, ending="the_rope", phases=["consuming"], flag="m"
    ),
}


@pytest.mark.parametrize("fault", sorted(MALFORMED))
def test_a_malformed_terminal_fails_naming_the_file(tmp_path: Path, fault: str) -> None:
    paths = _story(tmp_path, MALFORMED[fault])
    set_overlay({"paths": paths})
    try:
        with pytest.raises(ValueError) as caught:
            encounter.load_death_rules()
        assert str(Path(paths["rules"]) / "death.yaml") in str(caught.value), caught.value
    finally:
        set_overlay(None)


def test_the_validator_reports_an_unknown_terminal_ending(tmp_path: Path) -> None:
    from engine.games import registry, validation

    manifest = registry.get("hue-and-cry")
    rules = tmp_path / "rules"
    shutil.copytree(manifest.resolve(manifest.paths["rules"]), rules)
    _dump(rules / "death.yaml", _terminal(when={"in_custody": True}, ending="the_noose"))
    patched = type(manifest)(**{**manifest.__dict__, "paths": {**manifest.paths, "rules": str(rules)}})
    errors = [
        f"{i.source}|{i.ref_id}|{i.message}"
        for i in validation.errors_only(validation.validate_story(patched))
    ]
    hits = [e for e in errors if "death.yaml" in e]
    assert len(hits) == 1 and "the_noose" in hits[0], errors


def test_every_shipped_story_validates_its_death_rules() -> None:
    from engine.games import registry, validation

    for slug in ("clockwork-dark", "neon-city"):
        errors = validation.errors_only(validation.validate_story(registry.get(slug)))
        assert not [i for i in errors if "death.yaml" in i.source], errors


# ---------------------------------------------------------------------------
# The job/death seam
# ---------------------------------------------------------------------------


def test_the_arrest_scene_a_respawn_brings_survives_the_death(story: Path, monkeypatch) -> None:
    state = _world()
    pid = _open(state)
    # Approach cleanly, fail the door twice (the alarm rises by on_crit_fail
    # each time and is raised at max), then fall through the cellar.
    _rolls(monkeypatch, "success", "failure")
    _walk_to(state, "entry")
    jobs.resolve_stage(state, "door")
    jobs.resolve_stage(state, "door")
    job = jobs.active(state)
    assert job is not None and job.get("raised_at") is not None
    state.stats.hp = 1

    out = jobs.resolve_stage(state, "cellar")

    # The fall killed; the respawn's three hours passed the watch's two, so
    # the receipt reports the job as the watch closed it.
    assert out["closed"] is True and out["outcome"] == "caught"
    assert state.stats.hp > 0 and state.location_id == SQUARE
    assert jobs.active(state) is None
    assert state.jobs["last"]["outcome"] == "caught"
    assert encounter.active(state) and state.encounter["id"] == "watch_stop"
    assert pid not in jobs.robbed(state)


def test_a_respawn_before_the_watch_is_due_still_closes_the_job_hurt(
    tmp_path: Path, monkeypatch
) -> None:
    doc = copy.deepcopy(DEATH)
    doc["respawn"]["hours"] = 0.5
    set_overlay({"paths": _story(tmp_path, doc)})
    try:
        state = _world()
        _open(state)
        _rolls(monkeypatch, "success", "failure")
        _walk_to(state, "entry")
        state.stats.hp = 1
        out = jobs.resolve_stage(state, "cellar")
        assert out["outcome"] == "hurt" and out["closed"] is True
        assert state.jobs["last"]["outcome"] == "hurt"
        assert not encounter.active(state)
    finally:
        set_overlay(None)


def test_a_death_in_an_encounter_round_leaves_the_arrest_scene_open(
    story: Path, monkeypatch
) -> None:
    """The same seam through ``resolve_approach``: its own end-of-round clear
    must not close a scene the death's hours opened."""
    from engine.game import checks
    from types import SimpleNamespace

    state = _world()
    _open(state)
    _rolls(monkeypatch, "success", "failure")
    _walk_to(state, "entry")
    jobs.resolve_stage(state, "door")
    jobs.resolve_stage(state, "door")
    assert jobs.active(state)["raised_at"] is not None
    # A lethal round in some other scene, resolved on this turn.
    lethal = {
        "id": "test_lethal", "band": "test", "intro": "", "triggers": {},
        "threat": {"name": "Something final", "resolve": 9},
        "approaches": {"die": {"skill": "nerve", "difficulty": "standard", "text": "Die"}},
        "outcomes": {"failure": {"text": "DOWN", "effects": [{"type": "hp", "delta": -999}]}},
    }
    real = encounter.get_definition
    monkeypatch.setattr(encounter, "get_definition",
                        lambda eid: lethal if eid == "test_lethal" else real(eid))
    monkeypatch.setattr(
        checks, "resolve",
        lambda state, skill, difficulty="standard", **kw: SimpleNamespace(
            degree="failure", summary="forced", margin=-6,
            to_dict=lambda: {"degree": "failure"}),
    )
    assert encounter.begin(state, "test_lethal")
    receipt = encounter.resolve_approach(state, "die")
    assert receipt["death"] and receipt["death"]["terminal"] is False
    assert encounter.active(state) and state.encounter["id"] == "watch_stop"


# ---------------------------------------------------------------------------
# Byte-identical: the flagship's terminal and respawn, neon-city's respawn
# ---------------------------------------------------------------------------

#: sha256 of the death record plus the full save dict, measured against the
#: code BEFORE this change (HEAD 1109034). Any drift in how either story dies
#: -- order of effects, hours, what the scene looks like afterwards -- moves it.
GOLDEN = {
    "flagship_respawn": "0dde0d46d56395866e447aa82174e6f09a00a1e88a226aeadf260f555ca5f01a",
    "flagship_terminal": "cf152e2a0893edcbc7d59b3e341d82e98fd6dc7ffa5d36e0a47a14ba828e33ae",
    "neon_respawn": "5c3e34b9bd8d880286cbee68e3c542cbae5c4910379a16656f2099634bb3ccb9",
}


def _death_digest(case: str) -> str:
    from engine.games import registry

    slug, scene, where = {
        "flagship_respawn": ("clockwork-dark", "wolf_at_the_margin", "forest_clearing"),
        "flagship_terminal": ("clockwork-dark", "wolf_at_the_margin", "forest_clearing"),
        "neon_respawn": ("neon-city", "storm_front", "the_grid"),
    }[case]
    registry.activate(slug)
    try:
        terminal = case == "flagship_terminal"
        state = GameState(rng_seed=77, location_id=where, evil_progress=0.99 if terminal else 0.0)
        set_clock(state, day=3, hour=14)
        state.stats.gold = 40
        state.hunger = 10.0
        if terminal:
            assert state.evil_phase.value == "consuming"
            state.flags["saints_marked_you"] = True
        assert encounter.begin(state, scene), scene
        state.stats.hp = 0
        death = encounter.check_death(state)
        saved = state.to_save_dict()
        saved.pop("session_id", None)  # random per GameState, not per death
        blob = json.dumps({"death": death, "state": saved},
                          sort_keys=True, default=str)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()
    finally:
        registry.deactivate()


@pytest.mark.parametrize("case", sorted(GOLDEN))
def test_shipped_death_handling_is_byte_identical(case: str) -> None:
    assert _death_digest(case) == GOLDEN[case]


def test_the_flagship_terminal_still_ends_without_an_ending() -> None:
    from engine.games import registry

    registry.activate("clockwork-dark")
    try:
        state = GameState(rng_seed=77, location_id="forest_clearing", evil_progress=0.99)
        set_clock(state, day=3, hour=14)
        state.flags["saints_marked_you"] = True
        state.stats.hp = 0
        death = encounter.check_death(state)
        assert death == {"died": True, "terminal": True, "ended": True,
                         "text": death["text"]}
        assert state.ended is True
        assert epilogue.for_state(state) is None
    finally:
        registry.deactivate()
