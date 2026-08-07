"""
Dice Engine
===========

All random mechanical rolls — agents must use skills that call here.

Version: v0.1.0 [2026-06-20]
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any


@dataclass
class DiceResult:
    """Result of a dice roll."""

    sides: int
    rolls: list[int]
    modifier: int
    total: int
    reason: str
    critical: bool
    fumble: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "sides": self.sides,
            "rolls": self.rolls,
            "modifier": self.modifier,
            "total": self.total,
            "reason": self.reason,
            "critical": self.critical,
            "fumble": self.fumble,
        }


def roll_dice(
    sides: int = 20,
    modifier: int = 0,
    reason: str = "",
    *,
    num_dice: int = 1,
    rng: random.Random | None = None,
) -> DiceResult:
    """
    Roll dice with optional modifier.

    Args:
        sides: Die sides (2–100).
        modifier: Added to sum of rolls.
        reason: Audit string for logs.
        num_dice: Number of dice (default 1).
        rng: Optional seeded RNG for tests.

    Returns:
        DiceResult with critical/fumble flags for d20 nat 20/1.
    """
    sides = max(2, min(100, sides))
    num_dice = max(1, min(10, num_dice))
    gen = rng or random
    rolls = [gen.randint(1, sides) for _ in range(num_dice)]
    total = sum(rolls) + modifier
    critical = sides == 20 and len(rolls) == 1 and rolls[0] == 20
    fumble = sides == 20 and len(rolls) == 1 and rolls[0] == 1
    return DiceResult(
        sides=sides,
        rolls=rolls,
        modifier=modifier,
        total=total,
        reason=reason,
        critical=critical,
        fumble=fumble,
    )


def resolve_check(
    roll_total: int,
    dc: int,
) -> dict[str, Any]:
    """
    Compare roll total to difficulty class.

    Returns:
        Dict with success, margin, dc.
    """
    margin = roll_total - dc
    return {
        "success": roll_total >= dc,
        "margin": margin,
        "dc": dc,
        "roll_total": roll_total,
    }