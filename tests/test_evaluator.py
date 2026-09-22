"""Evaluator tests."""

from __future__ import annotations

from engine.agents.evaluator import StorytellerEvaluator


def test_rejects_mechanics_without_tool():
    ev = StorytellerEvaluator()
    result = ev.evaluate(
        "You rolled a 18 and succeed against DC 12.",
        {"narration": "...", "choices": [{"id": "a", "text": "ok"}]},
        tool_receipts=[],
    )
    assert result.no_hallucinated_mechanics < 0.5
    assert result.passed is False


def test_passes_with_tool_receipt():
    ev = StorytellerEvaluator()
    result = ev.evaluate(
        "You slip through the brush unnoticed.",
        {
            "narration": "...",
            "choices": [{"id": "a", "text": "go"}, {"id": "b", "text": "wait"}],
            "skill_check": {"skill": "stealth", "dc_mod": 0},
        },
        tool_receipts=[{"skill": "resolve_skill_check", "type": "dice"}],
    )
    assert result.passed is True


def test_fails_skill_check_without_receipt():
    ev = StorytellerEvaluator()
    result = ev.evaluate(
        "You try to persuade the baker.",
        {
            "narration": "...",
            "choices": [{"id": "a", "text": "x"}],
            "skill_check": {"skill": "persuasion", "dc_mod": 0},
        },
        tool_receipts=[],
    )
    assert result.no_hallucinated_mechanics == 0.0
    assert result.passed is False

# ---------------------------------------------------------------------------
# Outcomes, not just the presence of a roll
# ---------------------------------------------------------------------------
#
# TWO BUGS, OPPOSITE DIRECTIONS. `has_roll` recognised only `roll_dice` and
# `resolve_skill_check`, so a real `work` shift narrated honestly as a success
# scored mechanics 0.2 and forced a retry -- pushing the narrator AWAY from
# reporting a real outcome. And nothing compared the prose to the receipt, so a
# failed check narrated "You succeed" passed.

import pytest

from engine.agents.evaluator import ROLLING_SKILLS, contradicts

TWO_CHOICES = {
    "narration": "...",
    "choices": [{"id": "a", "text": "go"}, {"id": "b", "text": "wait"}],
}

FAILED_CHECK = [
    {
        "skill": "resolve_skill_check",
        "success": True,
        "result": {"success": False, "degree": "failure"},
    }
]


@pytest.mark.parametrize(
    "skill",
    ["work", "forage", "encounter_approach", "resolve_scene_card", "resolve_challenge"],
)
def test_every_rolling_receipt_counts_as_a_roll(skill: str) -> None:
    result = StorytellerEvaluator().evaluate(
        "You succeed, and the foreman nods you through.",
        TWO_CHOICES,
        tool_receipts=[{"skill": skill, "success": True, "result": {"success": True}}],
    )
    assert result.no_hallucinated_mechanics == 1.0
    assert skill in ROLLING_SKILLS


def test_success_narrated_over_a_failed_check_is_caught() -> None:
    assert contradicts("You succeed. The lock clicks open.", FAILED_CHECK)
    result = StorytellerEvaluator().evaluate(
        "You succeed. The lock clicks open.", TWO_CHOICES, tool_receipts=FAILED_CHECK
    )
    assert result.passed is False
    assert any("failed check" in n for n in result.notes)


@pytest.mark.parametrize("skill", ["move_to", "travel"])
def test_arrival_narrated_over_a_refused_move_is_caught(skill: str) -> None:
    refused = [
        {
            "skill": skill,
            "success": False,
            "refused": True,
            "args": {"location_id": "millhaven_gate"},
            "result": {"error": "too tired to walk that far"},
        }
    ]
    assert contradicts("You arrive at Millhaven Gate as the bells ring.", refused)


@pytest.mark.parametrize(
    "prose",
    [
        "The pick slips. You do not succeed, not tonight.",
        "You fail, and the guard turns.",
        "You don't succeed. The tumblers laugh at you.",
        "Whether you succeed tomorrow is another matter; tonight the lock holds.",
    ],
)
def test_honest_failure_prose_is_not_flagged(prose: str) -> None:
    """The counter-control. A gate that fires on honest prose gets deleted."""
    assert contradicts(prose, FAILED_CHECK) == ""


def test_success_over_a_successful_check_is_fine() -> None:
    ok = [{"skill": "resolve_skill_check", "success": True, "result": {"success": True}}]
    assert contradicts("You succeed. The lock clicks open.", ok) == ""


def test_continuity_reaches_the_payload() -> None:
    """`to_dict` dropped it, so a continuity hard-fail never reached telemetry."""
    result = StorytellerEvaluator().evaluate("Quiet.", TWO_CHOICES, tool_receipts=[])
    assert "continuity" in result.to_dict()
