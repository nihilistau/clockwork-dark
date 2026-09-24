"""
Jobs, part four: the narrator and the player see the job.

THE SHAPE. ``prompts.job_block`` renders the open job (or its close, on the
turn it happened) in words -- the house by name, the stage in words, the
obstacle in the way, what is moving this stage's odds, which flashback paid
off THIS TURN, and the alarm's band. ``state.to_client_dict()`` ships the
same facts under ``job`` -- ``{"active": None|{...}, "prep": "<band>"}``, so
``prep`` sits at a stable place whether or not a job is open. Neither ever
carries a number, a stage id, or a difficulty band name. The evaluator gains
a fourth anchored contradiction: a clean, silent entry claimed over an ENTRY
stage receipt marked ``noisy``/``seen``, and a claim of getting inside over an
entry that did not advance -- same anchoring discipline as the Law's own
``_CLAIMS_UNSEEN`` (v0.10.0), so ordinary scene-setting prose is not caught
in the net.

WHAT THESE TESTS HOLD. The block is "" undeclared, and equally "" declared
but idle; otherwise it never leaks a digit or an id. The payload's ``job``
key exists exactly when jobs are declared, is ``None``-active between jobs,
and carries a stable ``prep`` band either way; the flagship gets no ``job``
key at all. A flashback's label shows only on the turn it was called. The
evaluator flags the two new claims and passes the honest counter-control.

Version: v0.1.0 [2026-09-24]
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

import pytest

from engine.config import set_overlay
from engine.game.effects import apply_effect
from engine.game.inventory import name_of
from engine.game.state import GameState
from engine.world import jobs, premises

from test_jobs import FIVE, JOBS_SPEC, SQUARE, _paths, no_jobs_story
from test_jobs_stages import (
    _house,
    _no_ids_or_numbers,
    _open,
    _raise,
    _rolls,
    _walk_to,
    _world,
)

from engine.agents import prompts
from engine.agents.evaluator import contradicts


@pytest.fixture()
def plain(tmp_path: Path) -> Iterator[Path]:
    """Jobs and premises, no Law."""
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


def _cased_once(state: GameState, pid: str) -> None:
    out = premises.case(state, pid)
    assert out["ok"] is True, out


# ---------------------------------------------------------------------------
# job_block
# ---------------------------------------------------------------------------


def test_job_block_is_empty_for_the_flagship() -> None:
    state = GameState(location_id=SQUARE)
    assert not jobs.declared()
    assert prompts.job_block(state) == ""


def test_job_block_is_empty_declared_but_idle(plain: Path) -> None:
    state = _world()
    assert jobs.declared()
    assert jobs.active(state) is None
    assert prompts.job_block(state) == ""


def test_job_block_names_the_house_and_the_stage_in_words(plain: Path) -> None:
    state = _world()
    pid = _open(state)
    name = premises.get(state, pid)["name"]
    block = prompts.job_block(state)
    assert name in block
    assert "approach" not in block  # the stage id, never spoken
    _no_ids_or_numbers(block, name)


def test_job_block_shows_the_reasons_moving_the_odds(
    plain: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = _world()
    pid = _open(state)
    name = premises.get(state, pid)["name"]
    _rolls(monkeypatch, "success")
    _walk_to(state, "score")
    apply_effect(state, {"type": "item", "item_id": "bent_nail"})
    block = prompts.job_block(state)
    assert name_of("bent_nail") in block
    _no_ids_or_numbers(block, name)


def test_job_block_shows_the_obstacle_in_the_way(
    plain: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Before the first roll at ``inside``, the obstacles have not been read yet
    (``jobs._ensure_obstacles`` is lazy) -- same as ``approaches``' own
    fallback -- so this forces one roll that does not clear the only
    obstacle, to see the label appear.
    """
    state = _world()
    pid = _open(state, security=("yard_dog",))
    name = premises.get(state, pid)["name"]
    household = list(premises.get(state, pid)["household"])
    _rolls(monkeypatch, "success")
    _walk_to(state, "inside")
    out = jobs.resolve_stage(state, "inside")
    assert out["ok"] is True and not out["closed"]
    assert jobs.current_stage(state) == "inside"  # more than one obstacle left
    block = prompts.job_block(state)
    assert "In the way" in block
    _no_ids_or_numbers(block, name)


def test_job_block_uses_the_features_authored_text_for_a_feature_obstacle(
    plain: Path,
) -> None:
    state = _world()
    pid = _open(state, security=("yard_dog",))
    active = jobs.active(state)
    active["at"] = FIVE.index("inside")
    active["obstacles"] = ["yard_dog"]
    block = prompts.job_block(state)
    # `text` authored on the security feature (test_premises.TOWNHOUSE), never
    # the id or a bare underscored word.
    assert "a dog in the yard after dark" in block
    assert "yard_dog" not in block


def test_job_block_names_a_feature_obstacle_the_same_way_in_both_lines(
    plain: Path,
) -> None:
    """
    Finding 4 of the T4 review: "In the way" (``current_obstacle_label``)
    and "Working the odds" (``band_for``'s reasons, via ``_plan``) must read
    a feature by the SAME words -- the premise type's authored ``text`` --
    not one by that text and the other by the id with underscores swapped.
    """
    state = _world()
    pid = _open(state, security=("yard_dog",))
    apply_effect(state, {"type": "intel", "premise": pid, "intel": "security:yard_dog"})
    active = jobs.active(state)
    active["at"] = FIVE.index("inside")
    active["obstacles"] = ["yard_dog"]
    block = prompts.job_block(state)
    assert "In the way: a dog in the yard after dark." in block
    assert "a dog in the yard after dark, cased already" in block


def test_job_block_shows_which_flashback_paid_off_only_this_turn(plain: Path) -> None:
    state = _world()
    pid = _open(state)
    _cased_once(state, pid)
    label = JOBS_SPEC["flashbacks"]["knew_the_rota"]["label"]
    assert "knew_the_rota" in jobs.legal_flashbacks(state)
    out = jobs.flashback(state, "knew_the_rota")
    assert out["ok"] is True, out
    block = prompts.job_block(state)
    assert label in block
    state.turn_number += 1  # the storyteller's counter, after the turn commits
    block = prompts.job_block(state)
    assert label not in block


def test_job_block_reports_how_the_job_closed_this_turn_only(
    plain: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = _world()
    pid = _open(state, loot=("golden_ring",))
    name = premises.get(state, pid)["name"]
    _rolls(monkeypatch, "success")
    out = {}
    for _ in range(20):
        stage = jobs.current_stage(state)
        if stage is None:
            break
        approach = "door" if stage == "entry" else str(stage)
        out = jobs.resolve_stage(state, approach)
        assert out["ok"] is True
        if out.get("closed"):
            break
    assert out["closed"] is True and out["outcome"] == "clean"
    block = prompts.job_block(state)
    assert name in block
    _no_ids_or_numbers(block, name)
    state.turn_number += 1
    block = prompts.job_block(state)
    assert block == ""  # no job open, and the close is a turn stale


def test_job_block_reports_a_caught_close(
    lawful: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Finding 5 of the T4 review: the watch actually arriving (`jobs.tick`,
    via `_raise` + two more stage-hours) closes the job `caught`, and the
    block says so on the turn it happened."""
    state = _world()
    pid = _open(state)
    name = premises.get(state, pid)["name"]
    _raise(state, monkeypatch)
    jobs.resolve_stage(state, "approach")
    out = jobs.resolve_stage(state, "approach")
    assert out["closed"] is True and out["outcome"] == "caught"
    block = prompts.job_block(state)
    assert name in block and "watch" in block.lower()
    _no_ids_or_numbers(block, name)
    state.turn_number += 1
    assert prompts.job_block(state) == ""


def test_job_block_does_not_say_you_walked_away_when_the_house_threw_you_out(
    plain: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Final review M2. With no Law, ``jobs.tick`` closes a roused job
    ``aborted`` -- nobody chose to leave, and "You walked away" put a decision
    in the player's mouth. Only ``jobs.abort`` reads as walking away.
    """
    state = _world()
    pid = _open(state)
    name = premises.get(state, pid)["name"]
    _raise(state, monkeypatch)
    jobs.resolve_stage(state, "approach")
    out = jobs.resolve_stage(state, "approach")
    assert out["closed"] is True and out["outcome"] == "aborted"
    block = prompts.job_block(state)
    assert name in block and "walked away" not in block.lower(), block
    assert "alarm" in block.lower()
    _no_ids_or_numbers(block, name)

    state = _world()
    pid = _open(state)
    jobs.abort(state)
    block = prompts.job_block(state)
    assert "walked away" in block.lower(), block


# ---------------------------------------------------------------------------
# the client payload
# ---------------------------------------------------------------------------


def test_flagship_payload_has_no_job_key() -> None:
    assert "job" not in GameState().to_client_dict()


def test_payload_job_key_present_and_prep_stable_when_idle(plain: Path) -> None:
    state = _world()
    payload = state.to_client_dict()
    assert payload["job"] == {"active": None, "prep": "none"}


def test_payload_job_active_shape_when_open(plain: Path) -> None:
    state = _world()
    pid = _open(state)
    name = premises.get(state, pid)["name"]
    payload = state.to_client_dict()
    job = payload["job"]
    assert job["prep"] == "none"
    active = job["active"]
    assert active["premise_name"] == name
    assert active["at"] == 0
    assert active["alarm"] == "quiet"
    assert isinstance(active["stages"], list) and len(active["stages"]) == len(FIVE)
    for stage_id, label in zip(FIVE, active["stages"]):
        assert label != stage_id and label
    assert active["stage_label"] not in FIVE and active["stage_label"]
    # Finding 3 of the T4 review: `prep` lives ONLY at the top level, never
    # duplicated inside `active` -- one meter, one place to read it.
    assert "prep" not in active


def test_a_story_without_jobs_has_no_job_payload_or_block(tmp_path: Path) -> None:
    with no_jobs_story("law-only", tmp_path) as location:
        state = GameState(location_id=location)
        assert "job" not in state.to_client_dict()
        assert prompts.job_block(state) == ""


# ---------------------------------------------------------------------------
# evaluator: the anchored job claims
# ---------------------------------------------------------------------------

# `stage` matters (T4 review finding 1, final review M1): BOTH claims are
# entry-only, since at any LATER stage the thief is already in.
NOISY_STAGE = [
    {"skill": "job_stage", "success": True,
     "result": {"outcome": "noisy", "advanced": True, "stage": "entry"}}
]
NOISY_INSIDE_STAGE = [
    {"skill": "job_stage", "success": True,
     "result": {"outcome": "noisy", "advanced": True, "stage": "inside"}}
]
SEEN_STAGE = [
    {"skill": "job_stage", "success": True,
     "result": {"outcome": "seen", "advanced": False, "stage": "inside"}}
]
BLOCKED_ENTRY_STAGE = [
    {"skill": "job_stage", "success": True,
     "result": {"outcome": "noisy", "advanced": False, "stage": "entry"}}
]
BLOCKED_INSIDE_STAGE = [
    {"skill": "job_stage", "success": True,
     "result": {"outcome": "noisy", "advanced": False, "stage": "inside"}}
]


def test_a_clean_silent_entry_claim_over_a_noisy_stage_is_caught() -> None:
    assert contradicts("You slip in without a sound.", NOISY_STAGE)


def test_a_clean_silent_entry_claim_past_the_entry_stage_is_not_a_contradiction() -> None:
    """
    Final review M1, the counter-control. ``seen``/``noisy`` at ``inside`` is
    the maid waking or the strongroom's hinge, not the way in: "you slipped
    in unseen" recalls the entry, which that receipt says nothing about.
    """
    for prose in (
        "And you slip inside unnoticed, quick as thought.",
        "You slip in without a sound; it is the maid on the stair who ruins it.",
    ):
        assert contradicts(prose, SEEN_STAGE) == ""
        assert contradicts(prose, NOISY_INSIDE_STAGE) == ""
        assert contradicts(prose, NOISY_STAGE)


def test_a_getting_in_claim_over_an_entry_stage_that_did_not_advance_is_caught() -> None:
    assert contradicts("You get inside before anyone stirs.", BLOCKED_ENTRY_STAGE)


def test_a_getting_in_claim_past_the_entry_stage_is_not_a_contradiction() -> None:
    """
    T4 review finding 1. `advanced: False` at `inside` (or `score`,
    `getaway`) means a roll failed with the thief ALREADY past the door --
    "You're inside, but the dog has your scent" is the honest narration of
    exactly that, not a claim the receipt contradicts.
    """
    for prose in (
        "You get inside before anyone stirs.",
        "You are inside, but the study door will not give.",
        "You're inside the house, and the dog has your scent.",
    ):
        assert contradicts(prose, BLOCKED_INSIDE_STAGE) == ""


@pytest.mark.parametrize(
    "prose",
    [
        "You try the latch, but it catches loud, and you do not get in.",
        "The board creaks under you; whoever is inside stirs but does not wake.",
        "You slip on the wet step and swear under your breath.",
        "You are not inside yet, and the dog is already barking.",
    ],
)
def test_honest_job_stage_prose_is_not_flagged(prose: str) -> None:
    """The counter-control. A gate that fires on honest prose gets deleted."""
    assert contradicts(prose, NOISY_STAGE) == ""
    assert contradicts(prose, SEEN_STAGE) == ""
    assert contradicts(prose, BLOCKED_ENTRY_STAGE) == ""
    assert contradicts(prose, BLOCKED_INSIDE_STAGE) == ""


@pytest.mark.parametrize(
    "prose",
    [
        # "quietly" dropped from the trigger words entirely (T4 review
        # finding 2): this is the honest narration of a NOISY entry, using
        # that very word.
        "You slip inside, quietly as you can, but the hinge shrieks.",
        # A trigger word IS present ("unseen"), but a contrastive clause in
        # the same sentence undoes the claim a moment later.
        "You slip in unseen, but a floorboard betrays you.",
        "You slip inside unnoticed, until a board creaks underfoot.",
    ],
)
def test_a_clean_entry_claim_undone_in_the_same_sentence_is_not_flagged(prose: str) -> None:
    assert contradicts(prose, NOISY_STAGE) == ""
    assert contradicts(prose, SEEN_STAGE) == ""


def test_the_new_claims_fire_on_a_real_production_receipt(
    plain: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    The hand-built receipts above assume a shape; this drives one stage
    through the real intent -> skill -> receipt path
    (``tool_dispatcher.execute_tool``, which ``json.loads``s the skill's
    string return into ``result``) and proves ``contradicts`` reads it the
    same way, exactly as v0.10's ``_CLAIMS_UNSEEN``/``lift_purse`` did.
    """
    from engine.agents.tool_dispatcher import execute_intent
    from engine.game.engine import GameEngine

    state = _world()
    _open(state)
    _rolls(monkeypatch, "success")
    _walk_to(state, "entry")
    _rolls(monkeypatch, "failure")
    engine = GameEngine(state)
    receipts = execute_intent({"action": "job", "target": "door"}, engine)
    assert len(receipts) == 1
    receipt = receipts[0]
    assert receipt["skill"] == "job_stage"
    result = receipt["result"]
    assert result["stage"] == "entry" and result["advanced"] is False
    assert result["outcome"] in ("noisy", "seen")

    assert contradicts("You get inside before anyone stirs.", [receipt])
    assert contradicts("You slip in without a sound.", [receipt])
    assert contradicts(
        "You try the door, but it holds, and you do not get in.", [receipt]
    ) == ""
