"""
SceneRulesEngine enforcement tests (PR3 scope).

Evaluator anti-hallucination for narration prose is PR5.
"""

from __future__ import annotations

from engine.game.state import GameState
from engine.mcp.scene_rules_engine import get_rules_engine


def test_rejects_unknown_location():
    engine = get_rules_engine()
    state = GameState(location_id="forest_clearing")
    result = engine.validate_location(state, "crossroads")
    assert result.allowed is False
    assert any(v.rule_id == "R001" for v in result.violations)


def test_rejects_invalid_edge():
    engine = get_rules_engine()
    state = GameState(location_id="forest_clearing")
    result = engine.validate_location(state, "millhaven_gate")
    assert result.allowed is False
    assert any(v.rule_id == "R002" for v in result.violations)


def test_rejects_stat_delta_without_tool_receipt():
    engine = get_rules_engine()
    context = {"tool_receipts": []}
    result = engine.validate_stat_delta(context, "hp", -5)
    assert result.allowed is False
    assert result.violations[0].rule_id == "R003"


def test_allows_stat_delta_with_receipt():
    engine = get_rules_engine()
    context = {"tool_receipts": [{"type": "stat", "stat": "hp"}]}
    result = engine.validate_stat_delta(context, "hp", -5)
    assert result.allowed is True


def test_rejects_location_change_without_move_to():
    engine = get_rules_engine()
    state = GameState(location_id="forest_clearing")
    context = {"tool_receipts": []}
    result = engine.validate_move_context(state, context, "edgewood_square")
    assert result.allowed is False


def test_evil_progress_cannot_decrease():
    engine = get_rules_engine()
    result = engine.validate_evil_progress(0.5, 0.3)
    assert result.allowed is False
    assert result.violations[0].rule_id == "R004"