"""
plan -> negotiate -> commit, wired into the turn.

`plan.py`, `negotiate.py`, `knowledge.py` and `roster.py` were built, tested and
called by nothing: the live turn ran the narrator to completion, committed, and
then handed the finished prose to a second agent to react to. An agent that has
already written cannot be argued with, so that shape could not express a
negotiation however good the parts were.

What this suite holds:

  * the shipped games are untouched -- fewer than two declared agents means the
    pipeline does not run, and the turn is the one they had
  * an agent proposes; nothing is written until the argument is over
  * ONE commit, atomic: no turn ends in a state neither agent proposed
  * permissions hold at both walls -- the plan filter and the store's ACL
  * a private motive never leaves the agent that thought it

Every model call is injected. These are shape tests, not model tests.

Version: v0.1.0 [2026-08-09]
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator

import pytest

from engine.agents import pipeline as pipeline_module
from engine.agents.plan import AgentPlan, ProposedEffect, parse_plan, plan_schema
from engine.agents.roster import Roster, parse_roster
from engine.game.state import GameState

_ROOT = Path(__file__).resolve().parents[1]
GARDEN = _ROOT / "games" / "wicked-garden"


@pytest.fixture
def garden() -> Iterator[GameState]:
    """
    The real story, activated the way a turn activates it.

    Deliberately `activate()` rather than assigning `active_state._schema` from
    `load_schema` directly. That shortcut is what an earlier version of this
    fixture did, and it skipped the step where the roster's grants are folded
    into the schema's `owners` -- so a permission test passed against a schema
    no running game ever sees. A fixture that bypasses the assembly is a fixture
    testing something the product does not do.
    """
    from engine.games.registry import activate, deactivate

    activate("wicked-garden")
    state = GameState(rng_seed=42)
    try:
        yield state
    finally:
        deactivate()


def _roster() -> Roster:
    import yaml

    with (GARDEN / "agents.yaml").open(encoding="utf-8") as handle:
        return parse_roster(yaml.safe_load(handle), slug="wicked-garden")


def _speaks(answers: dict[str, dict[str, Any]]) -> Any:
    """
    An injected model that answers per agent.

    Keyed off the persona in the system message, because that is the only thing
    distinguishing two calls that are otherwise the same shape -- which is
    itself worth asserting: if the two agents were sent identical prompts, the
    knowledge partition would not exist.
    """

    def llm(messages: list[dict[str, Any]]) -> str:
        system = messages[0]["content"]
        for marker, answer in answers.items():
            if marker in system:
                return json.dumps(answer)
        return json.dumps({"intent": "silent", "beat": ""})

    return llm


# ---------------------------------------------------------------------------
# The shipped games are untouched
# ---------------------------------------------------------------------------


def test_a_story_with_no_roster_does_not_run_a_pipeline() -> None:
    """
    The flagship declares no agents.yaml, and an empty roster is what any
    story that has not written one resolves to. (The Wicked Garden DOES ship
    one; that is the other side of the seam and is tested against a roster
    rather than against its absence.)

    `ran=False` is what keeps this additive: the caller falls through to the
    turn it had, the narration prompt gets no extra block, and the payload grows
    no `negotiation` key.
    """
    result = pipeline_module.run_pipeline(GameState(), "look around", roster=Roster())
    assert result.ran is False
    assert result.turn.accepted == {}
    assert result.receipts == []
    assert pipeline_module.narration_block(result) == ""


def test_a_single_declared_agent_is_a_narrator_not_a_negotiation() -> None:
    """
    One agent has nobody to argue with.

    Running the pipeline anyway would spend a model call to reach the conclusion
    it started from.
    """
    roster = parse_roster({"agents": {"solo": {"role": "world"}}}, slug="t")
    assert pipeline_module.run_pipeline(GameState(), "wait", roster=roster).ran is False


def test_choices_are_unchanged_when_no_pipeline_ran() -> None:
    """The narrator's own list, renumbered over itself and nothing added."""
    narrated = [{"id": "a", "text": "Go north"}, {"id": "b", "text": "Wait"}]
    merged = pipeline_module.merge_choices(
        pipeline_module.PipelineResult(ran=False), narrated
    )
    assert [(c["id"], c["text"]) for c in merged] == [("a", "Go north"), ("b", "Wait")]


# ---------------------------------------------------------------------------
# The pipeline runs
# ---------------------------------------------------------------------------


def test_both_agents_plan_and_the_story_rule_decides(garden: GameState) -> None:
    """
    The Garden's own table: her private scene beats the world's interruption.

    Driven through the shipped agents.yaml, so the rule under test is the one
    that ships rather than one invented to pass.
    """
    result = pipeline_module.run_pipeline(
        garden,
        "ask her what the toll is",
        roster=_roster(),
        llm_fn=_speaks(
            {
                "STORYTELLER": {"intent": "interrupt", "beat": "the court arrives", "confidence": 0.9},
                "SOPHIA": {"intent": "speak", "beat": "she answers", "line": "Ten days. Yours.", "confidence": 0.4},
            }
        ),
    )

    assert result.ran is True
    assert result.lead == "sophia", result.turn.to_dict()
    assert [r.rule for r in result.turn.resolutions] == ["private_scene_finishes"]
    # `keep_loser_beat` -- the world does not lose its content, it loses the lead.
    assert result.turn.beats == ["she answers", "the court arrives"]


def test_the_narrator_is_told_what_was_agreed(garden: GameState) -> None:
    """
    The seam that makes the pipeline worth having.

    The narrator writes ONCE, knowing the answer, instead of writing first and
    being commented on afterwards. Her words go in verbatim -- a narrator asked
    to paraphrase a character's line is a narrator writing her dialogue.
    """
    result = pipeline_module.run_pipeline(
        garden,
        "step through",
        roster=_roster(),
        llm_fn=_speaks(
            {
                "STORYTELLER": {"intent": "narrate", "beat": "the gate closes", "confidence": 0.8},
                "SOPHIA": {"intent": "speak", "beat": "she welcomes them", "line": "There you are."},
            }
        ),
    )
    block = pipeline_module.narration_block(result)
    assert "already been agreed" in block.lower()
    assert "There you are." in block
    assert "the gate closes" in block


def test_a_private_motive_never_leaves_the_agent(garden: GameState) -> None:
    """
    The knowledge partition is decorative if `private` reaches the payload.

    It is logged, shipped to the browser and sent to telemetry -- a motive in
    any of those is one the other agent can eventually read.
    """
    result = pipeline_module.run_pipeline(
        garden,
        "smile back",
        roster=_roster(),
        llm_fn=_speaks(
            {
                "SOPHIA": {
                    "intent": "speak",
                    "beat": "she smiles",
                    "line": "How nice.",
                    "private": "I intend to keep them",
                },
            }
        ),
    )
    assert result.plans["sophia"].private == "I intend to keep them"
    assert "I intend to keep them" not in json.dumps(result.to_dict())
    assert "I intend to keep them" not in pipeline_module.narration_block(result)


# ---------------------------------------------------------------------------
# Commit
# ---------------------------------------------------------------------------


def test_an_accepted_effect_is_applied_through_the_one_writer(garden: GameState) -> None:
    """Her regard is hers to move, and the receipt names who moved it."""
    before = garden.meters.get("favor", 15)
    result = pipeline_module.run_pipeline(
        garden,
        "offer the ring back",
        roster=_roster(),
        llm_fn=_speaks(
            {
                "SOPHIA": {
                    "intent": "speak",
                    "beat": "she is charmed",
                    "line": "Keep it.",
                    "effects": [{"name": "favor", "delta": 6}],
                },
            }
        ),
    )
    assert garden.meters["favor"] == before + 6
    assert [r["agent"] for r in result.receipts] == ["sophia"]


def test_nothing_is_written_before_the_argument_is_over(garden: GameState) -> None:
    """
    Planning is inert.

    The property the whole ordering rests on: a proposal that has already taken
    effect cannot be argued with.
    """
    from engine.agents.planner import plan_for

    spec = _roster().get("sophia")
    before = dict(garden.meters)
    plan = plan_for(
        spec,
        garden,
        "take my hand",
        llm_fn=_speaks(
            {"SOPHIA": {"intent": "speak", "beat": "she takes it",
                        "effects": [{"name": "favor", "delta": 9}]}}
        ),
    )
    assert plan.effects and plan.effects[0].payload["name"] == "favor"
    assert garden.meters == before, "planning wrote to state"


def test_a_failed_commit_leaves_no_half_applied_turn(garden: GameState) -> None:
    """
    One transaction, not one per effect.

    A negotiation that half-applied -- her regard moved, the world's consequence
    did not -- would leave a state neither agent proposed and no rule produced.
    """
    from engine.agents.negotiate import NegotiatedTurn

    turn = NegotiatedTurn(lead="sophia")
    turn.accepted = {
        "sophia": AgentPlan(
            agent="sophia",
            effects=[
                ProposedEffect(kind="value", payload={"name": "favor", "delta": 5}),
                ProposedEffect(kind="value", payload={"name": "desire", "delta": 5}),
            ],
        )
    }
    before = dict(garden.meters)

    import engine.game.effects as effects_module

    real = effects_module.apply_effect
    calls = {"n": 0}

    def explode(state, effect, **kwargs):
        calls["n"] += 1
        if calls["n"] > 1:
            raise RuntimeError("model server died mid-commit")
        return real(state, effect, **kwargs)

    effects_module.apply_effect = explode
    try:
        with pytest.raises(RuntimeError):
            pipeline_module._commit(garden, turn)
    finally:
        effects_module.apply_effect = real

    assert garden.meters == before, "first effect survived a failed commit"


# ---------------------------------------------------------------------------
# Permissions, at both walls
# ---------------------------------------------------------------------------


def test_a_plan_cannot_name_a_value_the_agent_does_not_own() -> None:
    """
    The schema wall: `corruption` is the world's, and is not in her enum.

    Deliberately NOT in her `writes` -- the dictionary allows it "in
    intimate/claim contexts", the store's ACL has no notion of context, and a
    permission that cannot express its own condition is refused rather than
    approximated.
    """
    spec = _roster().get("sophia")
    schema = plan_schema(spec.id, voices=spec.voices, writable=spec.all_writes)
    enum = schema["properties"]["effects"]["items"]["properties"]["name"]["enum"]
    assert set(enum) == {"favor", "desire", "autonomy"}
    assert "corruption" not in enum

    # And if one arrives anyway, it is recorded rather than dropped.
    plan = parse_plan(
        "sophia",
        {"intent": "speak", "effects": [{"name": "corruption", "delta": 5}]},
        writable=spec.all_writes,
        needs_reason=spec.writes_with_reason,
    )
    assert plan.effects == []
    assert plan.refused[0]["name"] == "corruption"


def test_autonomy_needs_a_reason_and_is_refused_without_one() -> None:
    """
    The single most consequential permission in the roster.

    Autonomy gates the door home and the equal ending. A character who could
    quietly drain it would close both without the player ever seeing why, so
    the reason is what attaches "she took something from you" to the number.
    """
    spec = _roster().get("sophia")

    bare = parse_plan(
        "sophia",
        {"intent": "speak", "effects": [{"name": "autonomy", "delta": -4}]},
        writable=spec.all_writes,
        needs_reason=spec.writes_with_reason,
    )
    assert bare.effects == []
    assert bare.refused[0]["why"] == "requires a stated reason"

    given = parse_plan(
        "sophia",
        {
            "intent": "speak",
            "effects": [
                {"name": "autonomy", "delta": -4, "reason": "you let her answer for you"}
            ],
        },
        writable=spec.all_writes,
        needs_reason=spec.writes_with_reason,
    )
    assert given.effects[0].reason == "you let her answer for you"


def test_the_roster_grant_reaches_the_store(garden: GameState) -> None:
    """
    Permissions were declared in two files that disagreed.

    `agents.yaml` grants an agent its writes; `state.yaml` grants a value its
    owners; the store enforces the second and nothing reconciled them. The
    Garden's roster granted `gm` ten values and Sophia three, and its schema
    named owners for two -- so the world agent could not move `corruption`, the
    meter the whole story turns on, and Sophia's `autonomy` write was refused
    with `owners=[]` every time she asked for it.

    The roster is the source now and the schema's `owners` is derived. Read
    through `active_schema()`, which is the path a turn takes.
    """
    from engine.games.registry import activate, deactivate
    from engine.state.active import active_schema

    activate("wicked-garden")
    try:
        schema = active_schema()
        assert "sophia" in schema.get("autonomy").owners
        assert "gm" in schema.get("corruption").owners
        # An explicitly declared owner list is unioned, never replaced.
        assert set(schema.get("favor").owners) == {"gm", "sophia"}
    finally:
        deactivate()


def test_a_shipped_game_gains_no_agent_writable_values() -> None:
    """An empty roster grants nothing, so the flagship's schema is untouched."""
    from engine.games.registry import activate, deactivate
    from engine.state.active import active_schema

    activate("clockwork-dark")
    try:
        schema = active_schema()
        assert schema.values, "the flagship declares values"
        assert [n for n, v in schema.values.items() if v.owners] == []
    finally:
        deactivate()


def test_a_write_says_who_and_why_after_the_turn(garden: GameState) -> None:
    """
    "She took something from you", attached to the number that moved.

    The store's write journal held this and threw it away: it was per-store,
    `store_for()` builds a fresh store per call, and `clear_journal()` -- "called
    per turn, after it has been read" -- was called by nothing and read by
    nothing. The journal is deleted; the receipt is what actually survives a
    turn, so `by` and `why` ride out on it.
    """
    result = pipeline_module.run_pipeline(
        garden,
        "let her answer",
        roster=_roster(),
        llm_fn=_speaks(
            {
                "SOPHIA": {
                    "intent": "speak",
                    "beat": "she answers for them",
                    "effects": [
                        {"name": "autonomy", "delta": -3,
                         "reason": "you let her answer for you"}
                    ],
                },
            }
        ),
    )
    receipt = next(r for r in result.receipts if r["name"] == "autonomy")
    assert receipt["by"] == "sophia"
    assert receipt["why"] == "you let her answer for you"
    assert receipt["after"] < receipt["before"]


def test_the_store_refuses_a_write_that_slipped_past_the_filter(garden: GameState) -> None:
    """
    The second wall, and the one that journals.

    Belt and braces on the one permission that can quietly close an ending: the
    plan filter is cheap and first, the store's `owners` is authoritative and
    records the attempt.
    """
    from engine.agents.negotiate import NegotiatedTurn

    turn = NegotiatedTurn(lead="sophia")
    turn.accepted = {
        "sophia": AgentPlan(
            agent="sophia",
            effects=[ProposedEffect(kind="value", payload={"name": "corruption", "delta": 5})],
        )
    }
    receipts, refused, veto = pipeline_module._commit(garden, turn)
    assert veto == ""
    assert receipts[0]["ok"] is False
    assert refused and refused[0]["agent"] == "sophia"
    assert garden.meters.get("corruption", 5) == 5


def test_an_agent_cannot_speak_as_a_voice_it_does_not_own(garden: GameState) -> None:
    """
    Recorded, not merely dropped.

    Negotiation is where an agent's INTENT to do it is visible, and the attempt
    is worth more than a silent refusal.
    """
    from engine.agents.negotiate import Negotiator

    roster = _roster()
    plans = {
        "sophia": AgentPlan(
            agent="sophia", intent="speak", beat="she answers", speaks_as="thornwake"
        )
    }
    turn = Negotiator(roster.rules, owned_voices=roster.owned_voices()).negotiate(plans)
    assert plans["sophia"].speaks_as == ""
    assert any(r.rule == "ownership" for r in turn.resolutions)


# ---------------------------------------------------------------------------
# Safety
# ---------------------------------------------------------------------------


def test_safety_outranks_every_agent_goal(garden: GameState) -> None:
    """
    Ahead of the story table and not reorderable from it.

    And NOT an early return: the turn still happens, with a lead and choices, so
    the caller can decline in fiction rather than show an out-of-character
    refusal.
    """
    result = pipeline_module.run_pipeline(
        garden,
        "something refused",
        roster=_roster(),
        safety_block="that is outside what this run allows",
        llm_fn=_speaks({"SOPHIA": {"intent": "speak", "beat": "she leans in", "line": "Come here."}}),
    )
    assert result.turn.blocked is True
    assert result.turn.resolutions[0].rule == "safety_first"
    assert result.lead, "blocked turns still need a lead to redirect through"
    assert "IN FICTION" in pipeline_module.narration_block(result)


# ---------------------------------------------------------------------------
# Choices
# ---------------------------------------------------------------------------


def test_an_agents_choice_reaches_the_player(garden: GameState) -> None:
    """
    What the old shape could not do.

    Choices were written solely by the narrator and the second agent never saw
    them, so a companion who had just warned you about a door could not put
    "not that door" on the table.
    """
    result = pipeline_module.run_pipeline(
        garden,
        "reach for the fruit",
        roster=_roster(),
        llm_fn=_speaks(
            {
                "SOPHIA": {
                    "intent": "speak",
                    "beat": "she warns them",
                    "choices": [{"text": "Put it down", "hint": "safe"}],
                },
            }
        ),
    )
    merged = pipeline_module.merge_choices(result, [{"text": "Eat it", "hint": "risky"}])
    assert [c["text"] for c in merged] == ["Eat it", "Put it down"]
    # Positional over the FINAL list -- two sources numbering independently
    # would collide, and a gap leaves a keyboard shortcut pointing at nothing.
    assert [c["id"] for c in merged] == ["a", "b"]


def test_duplicate_choices_are_offered_once(garden: GameState) -> None:
    """Two agents proposing "Refuse" is one option, not a rendering bug."""
    result = pipeline_module.run_pipeline(
        garden,
        "wait",
        roster=_roster(),
        llm_fn=_speaks(
            {"SOPHIA": {"intent": "speak", "beat": "she waits", "choices": [{"text": "refuse"}]}}
        ),
    )
    merged = pipeline_module.merge_choices(result, [{"text": "Refuse"}])
    assert [c["text"] for c in merged] == ["Refuse"]


# ---------------------------------------------------------------------------
# Robustness
# ---------------------------------------------------------------------------


def test_an_agent_that_cannot_plan_costs_only_its_own_turn(garden: GameState) -> None:
    """
    A model outage is not a lost turn for the player.

    The negotiator treats a silent plan as an ordinary case, and the turn goes
    on with whoever is left.
    """

    def dead(messages: list[dict[str, Any]]) -> str:
        raise ConnectionError("LM Studio is not running")

    result = pipeline_module.run_pipeline(
        garden, "look up", roster=_roster(), llm_fn=dead
    )
    assert result.ran is True
    assert result.turn.accepted == {}
    assert result.receipts == []


def test_a_malformed_plan_is_silence_not_a_crash() -> None:
    """Garbage costs the agent its turn, never the player's."""
    assert parse_plan("x", {"intent": "conquer"}).intent == "silent"
    assert parse_plan("x", []).intent == "silent"  # type: ignore[arg-type]


def test_the_two_agents_are_not_sent_the_same_prompt(garden: GameState) -> None:
    """
    If they were, the knowledge partition would not exist.

    The world reads `gm_secrets`; she reads `character_private` and never the
    world's. Asserted by capturing what each was actually sent.
    """
    seen: dict[str, str] = {}

    def capture(messages: list[dict[str, Any]]) -> str:
        system = messages[0]["content"]
        key = "sophia" if "SOPHIA" in system else "gm"
        seen[key] = system + "\n" + messages[1]["content"]
        return json.dumps({"intent": "silent", "beat": ""})

    pipeline_module.run_pipeline(garden, "look", roster=_roster(), llm_fn=capture)
    assert set(seen) == {"gm", "sophia"}
    assert seen["gm"] != seen["sophia"]
