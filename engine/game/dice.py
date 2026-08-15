"""
Dice Engine
===========

All random mechanical rolls — agents must use skills that call here.

Version: v0.1.0 [2026-06-20]
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

#: Last-resort generator for a caller that passed no world stream. Private, so
#: such a roll cannot consume or perturb the shared `random` module's sequence
#: and desynchronise anything else that draws from it. See `roll_dice`.
_UNSEEDED = random.Random()


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
        rng: The world stream this roll belongs to. Production callers pass
            ``world_rng(state, RNG_DICE)``; omitting it is a bug, not an
            option, and is logged as one.

    Returns:
        DiceResult with critical/fumble flags for d20 nat 20/1.
    """
    sides = max(2, min(100, sides))
    num_dice = max(1, min(10, num_dice))
    # `rng or random` was the last draw in the engine that could reach the
    # process-wide `random` module: a generator no seed replays and every
    # subsystem shares, so one forgotten kwarg would silently make a run
    # unreproducible and let one system's rolls shift another's. The fallback
    # is now a private instance -- still unseeded, but it cannot consume or
    # perturb anyone else's stream -- and it says so, so the call site that
    # needs fixing is findable rather than invisible.
    gen = rng
    if gen is None:
        gen = _UNSEEDED
        logger.warning(
            "[dice] Roll with no world stream (operation=roll_dice, reason=%s). "
            "This roll will not replay from the seed.",
            reason or "unspecified",
        )
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