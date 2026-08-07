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