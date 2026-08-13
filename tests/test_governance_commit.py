"""
The PHASE_COMMIT chain is wired into the turn.

``GovernancePipeline.run_commit``, the ``governance.commit`` config key and the
``SafetyCeiling`` governor all shipped together -- and nothing called
``run_commit``, so the one governance phase with veto authority was a document.
These tests hold the wiring: the configured chain contains the ceiling, the
chain runs inside ``pipeline._commit`` BEFORE anything is written, an inert
policy changes nothing, and a veto stops the commit with nothing applied.

Every model call is injected. These are shape tests, not model tests.

Version: v0.1.0 [2026-08-13]
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator

import pytest
import yaml

from engine.agents import pipeline as pipeline_module
from engine.agents.governance import (
    PHASE_COMMIT,
    GovernancePipeline,
    get_governance,
    reset_governance,
)
from engine.agents.roster import Roster, parse_roster
from engine.game.state import GameState

_ROOT = Path(__file__).resolve().parents[1]
GARDEN = _ROOT / "games" / "wicked-garden"

#: One agent moving one value she owns. The write is what proves ordering: the
#: chain must see the state BEFORE it and the player must see it applied AFTER.
SOPHIA_MOVES_FAVOR = {
    "SOPHIA": {
        "intent": "speak",
        "beat": "she is charmed",
        "line": "Keep it.",
        "effects": [{"name": "favor", "delta": 6}],
    },
}


@pytest.fixture
def garden() -> Iterator[GameState]:
    """The real second story, activated the way a turn activates it."""
    from engine.games.registry import activate, deactivate

    activate("wicked-garden")
    state = GameState(rng_seed=42)
    try:
        yield state
    finally:
        deactivate()


def _roster() -> Roster:
    with (GARDEN / "agents.yaml").open(encoding="utf-8") as handle:
        return parse_roster(yaml.safe_load(handle), slug="wicked-garden")


def _speaks(answers: dict[str, dict[str, Any]]) -> Any:
    def llm(messages: list[dict[str, Any]]) -> str:
        system = messages[0]["content"]
        for marker, answer in answers.items():
            if marker in system:
                return json.dumps(answer)
        return json.dumps({"intent": "silent", "beat": ""})

    return llm


class _CommitSpy:
    """Records what the chain was shown, and when."""

    priority = 10
    name = "CommitSpy"

    def __init__(self) -> None:
        self.seen: list[dict[str, Any]] = []

    def run_post(self, ctx: Any) -> Any:
        self.seen.append(
            {
                "meters": dict(ctx.state.meters),
                "agents": sorted(ctx.plans),
                "negotiated": ctx.negotiated,
            }
        )
        return ctx


class _AlwaysVeto:
    priority = 5
    name = "AlwaysVeto"

    def run_post(self, ctx: Any) -> Any:
        ctx.veto = "a governor said no"
        return ctx


# ---------------------------------------------------------------------------
# The chain exists and the pipeline calls it
# ---------------------------------------------------------------------------


def test_the_configured_commit_chain_contains_the_safety_ceiling() -> None:
    """
    ``config/default.yaml`` names ``governance.commit: [SafetyCeiling]`` and
    ``from_config`` reads it. This is the half that was always true; the tests
    below are the half that was not.
    """
    reset_governance()
    try:
        chain = get_governance().chains.get(PHASE_COMMIT, [])
        assert "SafetyCeiling" in [type(hook).__name__ for hook in chain]
    finally:
        reset_governance()


def test_run_commit_runs_during_the_pipeline_commit_before_any_write(
    garden: GameState,
) -> None:
    """
    THE regression this file exists for: ``run_commit`` is actually invoked.

    And invoked at the right moment -- the spy sees the pre-commit state while
    the player sees the committed one, which is the difference between a
    governor with authority and a post-mortem audit.
    """
    spy = _CommitSpy()
    before = garden.meters.get("favor", 15)

    result = pipeline_module.run_pipeline(
        garden,
        "offer the ring back",
        roster=_roster(),
        llm_fn=_speaks(SOPHIA_MOVES_FAVOR),
        governance=GovernancePipeline({PHASE_COMMIT: [spy]}),
    )

    assert garden.meters["favor"] == before + 6, "the governed turn still committed"
    assert len(spy.seen) == 1, "run_commit was not invoked exactly once"
    assert spy.seen[0]["meters"].get("favor", before) == before, (
        "the commit chain ran after the write instead of before it"
    )
    # EVERY plan is reviewed, not only the accepted ones: a losing plan's beat
    # was still proposed, and the ceiling reads intent, not just outcome.
    assert spy.seen[0]["agents"] == ["gm", "sophia"]
    assert spy.seen[0]["negotiated"] is result.turn
    assert result.veto == ""


# ---------------------------------------------------------------------------
# An inert policy costs nothing
# ---------------------------------------------------------------------------


def test_an_inert_policy_story_turn_is_unchanged(garden: GameState) -> None:
    """
    A story that configures no safety policy gets the turn it always had.

    Two identical states play the identical turn, one with no commit chain and
    one through the real SafetyCeiling under an inert policy; they must land on
    the same numbers with nothing blocked.
    """
    from engine.safety.governor import SafetyCeiling
    from engine.safety.policy import INERT_POLICY, reset_policies, set_policy

    other = GameState(rng_seed=42)
    set_policy(INERT_POLICY, session_id=garden.session_id)
    set_policy(INERT_POLICY, session_id=other.session_id)
    try:
        bare = pipeline_module.run_pipeline(
            garden,
            "offer the ring back",
            roster=_roster(),
            llm_fn=_speaks(SOPHIA_MOVES_FAVOR),
            governance=GovernancePipeline({}),
        )
        governed = pipeline_module.run_pipeline(
            other,
            "offer the ring back",
            roster=_roster(),
            llm_fn=_speaks(SOPHIA_MOVES_FAVOR),
            governance=GovernancePipeline({PHASE_COMMIT: [SafetyCeiling()]}),
        )
    finally:
        reset_policies()

    assert governed.veto == "" and governed.turn.blocked is False
    assert bare.turn.blocked is False
    assert dict(other.meters) == dict(garden.meters)
    assert [r.get("applied") for r in governed.receipts] == [
        r.get("applied") for r in bare.receipts
    ]


# ---------------------------------------------------------------------------
# A veto stops the turn's writes
# ---------------------------------------------------------------------------


def test_a_veto_blocks_the_commit_cleanly(garden: GameState) -> None:
    """
    Nothing applied, everything refused, the turn marked blocked.

    The veto runs before the transaction opens, so "rolls back cleanly" is the
    strongest form available: there is nothing to roll back.
    """
    before_meters = dict(garden.meters)

    result = pipeline_module.run_pipeline(
        garden,
        "offer the ring back",
        roster=_roster(),
        llm_fn=_speaks(SOPHIA_MOVES_FAVOR),
        governance=GovernancePipeline({PHASE_COMMIT: [_AlwaysVeto()]}),
    )

    assert result.veto == "a governor said no"
    assert result.receipts == []
    assert result.turn.blocked is True
    assert result.turn.block_reason == "a governor said no"
    assert any(
        str(row.get("why", "")).startswith("vetoed") for row in result.refused
    ), "a vetoed write must be recorded as refused, not silently dropped"
    assert dict(garden.meters) == before_meters, "a vetoed turn moved a meter"
    # The veto surfaces through the existing blocked flow: the narrator is told
    # to decline in fiction, never to render a refusal.
    assert "IN FICTION" in pipeline_module.narration_block(result)
    assert result.to_dict()["veto"] == "a governor said no"
