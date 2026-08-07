"""
Storyteller Evaluator
=====================

Quality gate for Storyteller output — especially anti-hallucination
for mechanical claims without tool receipts.

Version: v0.1.0 [2026-06-20]
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


_MECHANICS_CLAIM = re.compile(
    r"(?i)\b("
    r"rolled?\s+(a\s+)?\d+|"
    r"natural\s+(1|20)|"
    r"nat\s+(1|20)|"
    r"you\s+(succeed|fail|passed|failed)|"
    r"beat\s+the\s+dc|"
    r"against\s+dc\s*\d+"
    r")\b"
)


@dataclass
class EvaluationResult:
    """Evaluator scorecard."""

    overall: float
    tone: float
    lore: float
    no_hallucinated_mechanics: float
    length: float
    valid_json: float
    choices: float
    passed: bool
    notes: list[str] = field(default_factory=list)
    flag: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "overall": self.overall,
            "tone": self.tone,
            "lore": self.lore,
            "no_hallucinated_mechanics": self.no_hallucinated_mechanics,
            "length": self.length,
            "valid_json": self.valid_json,
            "choices": self.choices,
            "passed": self.passed,
            "notes": self.notes,
            "flag": self.flag,
        }


class StorytellerEvaluator:
    """Score Storyteller turns against a 6-point rubric."""

    PASS_THRESHOLD = 0.6
    MECHANICS_FAIL_THRESHOLD = 0.5

    def evaluate(
        self,
        narration: str,
        parsed: dict[str, Any],
        *,
        tool_receipts: list[dict[str, Any]],
        lore_snippets: list[str] | None = None,
    ) -> EvaluationResult:
        """
        Score a Storyteller turn.

        Args:
            narration: Prose narration text.
            parsed: Parsed JSON epilogue dict.
            tool_receipts: Skills invoked this turn.
            lore_snippets: Optional RAG chunks for lore check.

        Returns:
            EvaluationResult with pass/fail.
        """
        notes: list[str] = []
        lore_snippets = lore_snippets or []

        tone = self._score_tone(narration)
        lore = self._score_lore(narration, lore_snippets)
        mechanics = self._score_mechanics(narration, parsed, tool_receipts, notes)
        length = self._score_length(narration)
        valid_json = 1.0 if parsed.get("narration") else 0.0
        choices = self._score_choices(parsed.get("choices", []))

        if not parsed.get("narration"):
            notes.append("Missing narration in JSON epilogue.")
        if mechanics < self.MECHANICS_FAIL_THRESHOLD:
            notes.append("Mechanical outcome claimed without tool receipt.")

        overall = (
            tone * 0.2
            + lore * 0.2
            + mechanics * 0.3
            + length * 0.1
            + valid_json * 0.1
            + choices * 0.1
        )

        passed = overall >= self.PASS_THRESHOLD and mechanics >= self.MECHANICS_FAIL_THRESHOLD

        return EvaluationResult(
            overall=round(overall, 3),
            tone=round(tone, 3),
            lore=round(lore, 3),
            no_hallucinated_mechanics=round(mechanics, 3),
            length=round(length, 3),
            valid_json=round(valid_json, 3),
            choices=round(choices, 3),
            passed=passed,
            notes=notes,
            flag=not passed,
        )

    @staticmethod
    def _score_tone(narration: str) -> float:
        """Grounded fantasy tone heuristic."""
        if not narration.strip():
            return 0.0
        lower = narration.lower()
        penalty = 0.0
        if any(w in lower for w in ("fireball", "lol", "npc", "hit points", "mana bar")):
            penalty += 0.4
        if any(w in lower for w in ("mist", "oven", "forest", "road", "village", "tinker")):
            penalty -= 0.1
        return max(0.0, min(1.0, 0.75 - penalty))

    @staticmethod
    def _score_lore(narration: str, snippets: list[str]) -> float:
        """Lore consistency against retrieved RAG chunks."""
        if not snippets:
            return 0.8
        text = narration.lower()
        hits = 0
        for snippet in snippets:
            words = [w for w in snippet.lower().split() if len(w) > 4][:6]
            if any(w in text for w in words):
                hits += 1
        return min(1.0, 0.55 + hits * 0.15)

    def _score_mechanics(
        self,
        narration: str,
        parsed: dict[str, Any],
        tool_receipts: list[dict[str, Any]],
        notes: list[str],
    ) -> float:
        """Penalize dice/outcome claims without matching tool calls."""
        skill_names = {r.get("skill") for r in tool_receipts}
        has_roll = "roll_dice" in skill_names or "resolve_skill_check" in skill_names

        claims_mechanics = bool(_MECHANICS_CLAIM.search(narration))
        skill_check = parsed.get("skill_check")
        needs_roll = skill_check is not None and skill_check is not False

        if needs_roll and not has_roll:
            notes.append("skill_check requested in JSON but no resolve_skill_check called.")
            return 0.0

        if claims_mechanics and not has_roll:
            return 0.2

        if needs_roll and has_roll:
            return 1.0
        return 1.0

    @staticmethod
    def _score_length(narration: str) -> float:
        words = len(narration.split())
        if 40 <= words <= 200:
            return 1.0
        if 20 <= words < 40 or 200 < words <= 280:
            return 0.7
        return 0.4

    @staticmethod
    def _score_choices(choices: list[Any]) -> float:
        if not isinstance(choices, list):
            return 0.0
        n = len(choices)
        if 2 <= n <= 4:
            return 1.0
        if n == 1:
            return 0.5
        return 0.3