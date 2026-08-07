"""
Evil Ticker
===========

Background evil progression — always advances.

Units: evil_progress is 0.0–1.0 (dimensionless).
evil_base_rate_per_day from config is added per in-game day elapsed.

Phase boundaries (inclusive lower, exclusive upper):
  DORMANT:   [0.0, 0.2)
  STIRRING:  [0.2, 0.5)
  SPREADING: [0.5, 0.8)
  CONSUMING: [0.8, 1.0]

Version: v0.1.0 [2026-06-20]
"""

from __future__ import annotations

from engine.config import get_config
from engine.game.locations import evil_multiplier_for
from engine.game.state import EvilPhase, GameState

PHASE_THRESHOLDS: list[tuple[float, EvilPhase]] = [
    (0.0, EvilPhase.DORMANT),
    (0.2, EvilPhase.STIRRING),
    (0.5, EvilPhase.SPREADING),
    (0.8, EvilPhase.CONSUMING),
]


def phase_from_progress(progress: float) -> EvilPhase:
    """Map progress to phase using inclusive lower bounds."""
    clamped = max(0.0, min(1.0, progress))
    result = EvilPhase.DORMANT
    for threshold, phase in PHASE_THRESHOLDS:
        if clamped >= threshold:
            result = phase
    return result


class EvilTicker:
    """Advances evil_progress based on world time and location."""

    @staticmethod
    def base_rate_per_day() -> float:
        """Configured daily evil advance rate."""
        return float(get_config().get("world.evil_base_rate_per_day", 0.01))

    @staticmethod
    def inaction_bonus(state: GameState) -> float:
        """
        Multiplier rewarding the world for the player's disengagement.

        Scales on how little the player is entangled in the plot: a baker who
        never asks questions lets the pattern spread faster than someone
        actively pushing against it. The previous formula compared world_day to
        turn_number, which -- once the clock was fixed -- would have made the
        bonus grow without bound simply because days pass faster than turns.
        """
        detachment = max(0.0, 1.0 - (state.plot_involvement / 100.0))
        return 1.0 + detachment * 0.35

    @staticmethod
    def advance(state: GameState, *, days_elapsed: float = 1.0) -> float:
        """
        Advance evil_progress and update evil_phase on state.

        Args:
            state: Mutable game state.
            days_elapsed: In-game days since last advance. Must be >= 0.

        Returns:
            New evil_progress value.

        Raises:
            ValueError: If days_elapsed is negative. Evil does not un-happen.
        """
        if days_elapsed < 0:
            raise ValueError(f"evil cannot recede (days_elapsed={days_elapsed})")

        multiplier = evil_multiplier_for(state.location_id)
        delta = (
            EvilTicker.base_rate_per_day()
            * days_elapsed
            * multiplier
            * EvilTicker.inaction_bonus(state)
        )
        state.evil_progress = max(0.0, min(1.0, state.evil_progress + delta))
        state.evil_phase = phase_from_progress(state.evil_progress)
        return state.evil_progress

    @staticmethod
    def snapshot(state: GameState) -> dict[str, str | float]:
        """Full evil snapshot for Storyteller tools."""
        return {
            "evil_progress": state.evil_progress,
            "evil_phase": state.evil_phase.value,
            "story_pressure": state.story_pressure,
            "plot_involvement": state.plot_involvement,
            "awareness": state.awareness,
        }