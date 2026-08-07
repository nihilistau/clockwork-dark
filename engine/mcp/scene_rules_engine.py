"""
Scene Rules Engine
==================

Rejects agent-proposed changes that violate engine truth.

PR3 scope: transition validation and skill-call audit.
PR5 adds Evaluator anti-hallucination for narration prose.

Version: v0.1.0 [2026-06-20]
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from engine.game.locations import LOCATION_IDS, can_travel
from engine.game.state import GameState

_rules_instance: Optional["SceneRulesEngine"] = None


@dataclass
class RuleViolation:
    """A single rules violation."""

    rule_id: str
    message: str
    severity: str = "error"


@dataclass
class RuleCheckResult:
    """Outcome of a rules check."""

    allowed: bool
    violations: list[RuleViolation] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "violations": [
                {"rule_id": v.rule_id, "message": v.message, "severity": v.severity}
                for v in self.violations
            ],
        }


class SceneRulesEngine:
    """
    Declarative rules enforced before state commits.

    Enumerated rules (PR3):
      R001 — location_id must be canonical
      R002 — travel must follow graph edges
      R003 — stat delta requires matching tool receipt in context
      R004 — evil_progress cannot decrease without flagged event
      R005 — awareness cannot exceed 100
    """

    def validate_location(self, state: GameState, target_id: str) -> RuleCheckResult:
        """R001 + R002: location exists and edge valid."""
        violations: list[RuleViolation] = []
        if target_id not in LOCATION_IDS:
            violations.append(
                RuleViolation("R001", f"Unknown location: {target_id}")
            )
        if not can_travel(state.location_id, target_id) and target_id != state.location_id:
            violations.append(
                RuleViolation(
                    "R002",
                    f"No edge from {state.location_id} to {target_id}",
                )
            )
        return RuleCheckResult(allowed=len(violations) == 0, violations=violations)

    def validate_stat_delta(
        self,
        context: dict[str, Any],
        stat_name: str,
        delta: int,
    ) -> RuleCheckResult:
        """R003: stat change must have tool receipt in context."""
        if delta == 0:
            return RuleCheckResult(allowed=True)
        receipts = context.get("tool_receipts", [])
        allowed_stats = {r.get("stat") for r in receipts if r.get("type") == "stat"}
        if stat_name not in allowed_stats:
            return RuleCheckResult(
                allowed=False,
                violations=[
                    RuleViolation(
                        "R003",
                        f"Stat change {stat_name}{delta:+d} without tool receipt",
                    )
                ],
            )
        return RuleCheckResult(allowed=True)

    def validate_evil_progress(
        self,
        old_progress: float,
        new_progress: float,
        *,
        allow_decrease: bool = False,
    ) -> RuleCheckResult:
        """R004: evil_progress monotonic unless flagged."""
        if new_progress < old_progress and not allow_decrease:
            return RuleCheckResult(
                allowed=False,
                violations=[
                    RuleViolation(
                        "R004",
                        f"evil_progress cannot decrease ({old_progress} -> {new_progress})",
                    )
                ],
            )
        return RuleCheckResult(allowed=True)

    def validate_awareness(self, awareness: float) -> RuleCheckResult:
        """R005: awareness bounds."""
        if awareness < 0 or awareness > 100:
            return RuleCheckResult(
                allowed=False,
                violations=[
                    RuleViolation("R005", f"awareness out of range: {awareness}")
                ],
            )
        return RuleCheckResult(allowed=True)

    def validate_move_context(
        self,
        state: GameState,
        context: dict[str, Any],
        target_id: str,
    ) -> RuleCheckResult:
        """Combined move validation: rules + require move_to receipt."""
        loc_result = self.validate_location(state, target_id)
        if not loc_result.allowed:
            return loc_result
        receipts = context.get("tool_receipts", [])
        move_calls = [r for r in receipts if r.get("skill") == "move_to"]
        if not move_calls and target_id != state.location_id:
            return RuleCheckResult(
                allowed=False,
                violations=[
                    RuleViolation(
                        "R003",
                        "Location change without move_to tool receipt",
                    )
                ],
            )
        return RuleCheckResult(allowed=True)


def get_rules_engine() -> SceneRulesEngine:
    """Singleton rules engine."""
    global _rules_instance
    if _rules_instance is None:
        _rules_instance = SceneRulesEngine()
    return _rules_instance