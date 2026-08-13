"""
Evil Ticker
===========

Background evil progression — advances for stories that DECLARE a doom clock.

Units: evil_progress is 0.0–1.0 (dimensionless).
evil_base_rate_per_day from config is added per in-game day elapsed.

Phase boundaries (inclusive lower, exclusive upper):
  DORMANT:   [0.0, 0.2)
  STIRRING:  [0.2, 0.5)
  SPREADING: [0.5, 0.8)
  CONSUMING: [0.8, 1.0]

THE DOOM CLOCK IS A CAPABILITY, NOT A GIVEN. ``doom_enabled()`` below answers
whether the running story has one, and everything that reads or narrates
``evil_progress``/``evil_phase`` for the model checks it first. A story used to
opt out only by setting ``world.evil_base_rate_per_day: 0.0`` -- which stopped
the number moving but not the engine TALKING about it: the GM prompt still
carried a phase line, and the turn still measured a doom delta, for a story
with no doom in it. The state fields stay (zeroed, save shape untouched); the
reads are what became conditional.

R-06 (v0.3.0): the tick answers to conduct. ``engagement_factor`` replaces the
bare inaction bonus -- earned ``doom_resistance`` (granted only through the
``doom_resistance`` effect kind, spent by decay here) slows the tick by up to
``world.evil_engagement_slowdown_max``, hard-floored at 0.25 so pushing back
buys time and never stops the clock.

Version: v0.3.0 [2026-08-14]
"""

from __future__ import annotations

import logging
from typing import Optional

from engine.config import get_config
from engine.game.locations import evil_multiplier_for
from engine.game.state import EvilPhase, GameState

logger = logging.getLogger(__name__)

# Cached per activation. Cheap to recompute, but this is asked on every prompt
# build and every clock tick; reset via engine/games/caches.py like every other
# per-story answer.
_DOOM_DECLARED: Optional[bool] = None


def doom_enabled() -> bool:
    """
    Whether the RUNNING story has a doom clock at all.

    True when the active manifest declares ``paths.doom_effects`` or a nonzero
    ``world.evil_base_rate_per_day`` in its settings. The ENGINE's config
    default rate does not count: an engine number is not a story declaring an
    apocalypse, and a story that says nothing about doom should not inherit
    one. Only a build with no readable manifest at all falls back to the
    resolved config rate, because there is nothing else to ask.

    Never activates anything -- this is asked mid-turn.
    """
    global _DOOM_DECLARED
    if _DOOM_DECLARED is not None:
        return _DOOM_DECLARED

    manifest = None
    try:
        from engine.games.registry import entry_manifest

        manifest = entry_manifest()
    except Exception as exc:  # noqa: BLE001 -- an unreadable manifest is not an outage
        logger.debug("[evil] No manifest to ask (operation=doom_enabled): %s", exc)

    if manifest is not None:
        declares_effects = bool(str(manifest.paths.get("doom_effects", "") or "").strip())
        declared_rate = manifest.allowed_settings().get("world.evil_base_rate_per_day")
        try:
            declares_rate = declared_rate is not None and float(declared_rate) > 0.0
        except (TypeError, ValueError):
            declares_rate = False
        _DOOM_DECLARED = declares_effects or declares_rate
    else:
        try:
            rate = float(get_config().get("world.evil_base_rate_per_day", 0.0) or 0.0)
        except (TypeError, ValueError):
            rate = 0.0
        _DOOM_DECLARED = rate > 0.0
    return _DOOM_DECLARED


def reset_doom_capability() -> None:
    """Forget the cached answer; the next ask re-reads the active manifest."""
    global _DOOM_DECLARED
    _DOOM_DECLARED = None

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


#: Hard floor on the combined engagement factor. Whatever a story sets
#: ``world.evil_engagement_slowdown_max`` to, engagement can slow the clock to
#: a quarter speed and no further -- the doom is bought time against, never
#: paused, and evil_progress stays strictly non-decreasing by construction.
ENGAGEMENT_FACTOR_FLOOR = 0.25


class EvilTicker:
    """Advances evil_progress based on world time, location and engagement."""

    @staticmethod
    def base_rate_per_day() -> float:
        """Configured daily evil advance rate."""
        return float(get_config().get("world.evil_base_rate_per_day", 0.01))

    @staticmethod
    def engagement_slowdown_max() -> float:
        """Fraction of the rate that doom_resistance at 100 can remove."""
        return float(get_config().get("world.evil_engagement_slowdown_max", 0.5))

    @staticmethod
    def resistance_decay_per_day() -> float:
        """Points of doom_resistance spent per in-game day."""
        return float(get_config().get("world.doom_resistance_decay_per_day", 4.0))

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
    def engagement_factor(state: GameState) -> float:
        """
        The R-06 term: what the player's conduct does to the doom rate.

        Two halves, opposite in sign and NO LONGER the same size:

          * ``inaction_bonus`` -- detachment accelerates, up to x1.35. Unchanged.
          * earned ``doom_resistance`` decelerates, up to the configured
            ``world.evil_engagement_slowdown_max`` fraction at 100 resistance.

        The old shape cancelled: the disengaged player sat behind low location
        multipliers and the engaged player walked into high ones, so the two
        extremes landed within 13% of each other per in-game day. Resistance is
        what breaks the symmetry, because it is granted only for finishing the
        story's own pushback -- exposure without engagement earns none.

        Floored at ``ENGAGEMENT_FACTOR_FLOOR``: pushing back buys time, it does
        not stop the clock.
        """
        resistance = max(0.0, min(100.0, state.doom_resistance))
        slowdown = (resistance / 100.0) * EvilTicker.engagement_slowdown_max()
        factor = EvilTicker.inaction_bonus(state) * (1.0 - slowdown)
        return max(ENGAGEMENT_FACTOR_FLOOR, factor)

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

        # A story with no doom clock ticks nothing -- and stays monotonic by
        # construction, since nothing here ever moves. The fields keep their
        # zeros and the save shape is untouched.
        if not doom_enabled():
            return state.evil_progress

        multiplier = evil_multiplier_for(state.location_id)
        delta = (
            EvilTicker.base_rate_per_day()
            * days_elapsed
            * multiplier
            * EvilTicker.engagement_factor(state)
        )
        # delta >= 0 by construction (rate, days, multiplier and the floored
        # factor are all non-negative), so progress never moves backward.
        state.evil_progress = min(1.0, state.evil_progress + max(0.0, delta))
        state.evil_phase = phase_from_progress(state.evil_progress)

        # Reprieve is SPENT, not kept: earned resistance fades at a configured
        # rate per in-game day, so holding the dark back is something the
        # player keeps doing rather than something they did once. Decayed AFTER
        # the tick above so the resistance the player had protects the days it
        # was held for, and only inside the doom-enabled branch -- a story with
        # no doom clock has nothing to resist. This is the one writer of
        # doom_resistance besides the `doom_resistance` effect kind.
        if state.doom_resistance > 0.0:
            state.doom_resistance = max(
                0.0,
                state.doom_resistance
                - EvilTicker.resistance_decay_per_day() * days_elapsed,
            )
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
            "doom_resistance": state.doom_resistance,
        }