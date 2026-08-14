"""
World Clock
===========

The single writer of world time.

Time used to live in two ints (``world_day``, ``world_hour``) advanced by
``state.world_day += int(days_elapsed)``. The only production caller passed
0.25, and ``int(0.25) == 0``, so the calendar never moved and the evil clock
never ticked. Both are now derived from one float, and this module owns it.

Everything that consumes elapsed time -- evil progression, survival, timed
effect expiry, NPC schedules -- hangs off ``advance_time`` so it cannot be
bypassed by a caller who forgets a step.

Version: v0.2.0 [2026-08-07]
"""

from __future__ import annotations

import logging
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator

from engine.game.evil_ticker import EvilTicker
from engine.game.plot import PlotFormula
from engine.game.state import GameState

logger = logging.getLogger(__name__)

HOURS_PER_DAY = 24.0

# Re-entrancy guard for death handling. Thread-local because sessions run on
# separate Socket.IO worker threads and must not see each other's depth.
_guard = threading.local()


def _in_death_check() -> bool:
    return getattr(_guard, "depth", 0) > 0


@contextmanager
def _death_check_guard() -> Iterator[None]:
    _guard.depth = getattr(_guard, "depth", 0) + 1
    try:
        yield
    finally:
        _guard.depth -= 1


@dataclass
class TimeAdvance:
    """What one movement of the clock actually did."""

    hours: float
    days: float
    day_rolled: bool
    from_day: int
    to_day: int
    from_hour: int
    to_hour: int
    expired_effects: list[str]
    healed_wounds: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "hours": self.hours,
            "days": self.days,
            "day_rolled": self.day_rolled,
            "from_day": self.from_day,
            "to_day": self.to_day,
            "from_hour": self.from_hour,
            "to_hour": self.to_hour,
            "expired_effects": list(self.expired_effects),
            "healed_wounds": list(self.healed_wounds),
        }


def _sweep_expiries(state: GameState) -> tuple[list[str], list[str]]:
    """Drop timed effects and wounds whose day has passed."""
    day = state.world_day

    expired = [e.id for e in state.active_effects if e.expires_day < day]
    if expired:
        state.active_effects = [
            e for e in state.active_effects if e.expires_day >= day
        ]

    healed = [w.id for w in state.wounds if w.heals_on_day and w.heals_on_day < day]
    if healed:
        state.wounds = [
            w for w in state.wounds if not (w.heals_on_day and w.heals_on_day < day)
        ]

    return expired, healed


def advance_time(state: GameState, hours: float) -> TimeAdvance:
    """
    Move the world clock forward. The only function permitted to do so.

    Args:
        state: Mutable game state.
        hours: In-game hours to advance. Must be >= 0.

    Returns:
        TimeAdvance describing the transition.

    Raises:
        ValueError: If hours is negative. Time does not run backward; an
            unbounded LLM-callable tick previously allowed exactly that.
    """
    if hours < 0:
        raise ValueError(f"time does not run backward (hours={hours})")

    from_day, from_hour = state.world_day, state.world_hour

    state.world_clock_hours += float(hours)
    days = float(hours) / HOURS_PER_DAY

    # Fractional days now reach the ticker intact -- this is the line that
    # makes "evil ticks whether you become a hero or a baker" true.
    EvilTicker.advance(state, days_elapsed=days)
    PlotFormula.update_story_pressure(state)

    # Doom beats key on the evil_progress the ticker just moved, so they fire
    # here rather than in a turn handler. That matters: the clock also advances
    # for travel, rest, unconsciousness and the background world tick, and a
    # doom clock that only advanced on narrated turns would stop for a player
    # who spent three days asleep. Idempotent (each beat sets its own flag), so
    # the death check's re-entry cannot double-apply one.
    try:
        from engine.world import world_effects

        world_effects.apply_pending_beats(state)
    except ImportError:
        pass

    # Progress clocks, the story-declared generalisation of the doom beats
    # above. Same reasoning for the same placement: a clock that only wound on
    # narrated turns would stop for a player who slept through the week. Inert
    # for a story that declares none, which is now only the flagship -- the
    # other three shipped games wind real clocks from here (wicked-garden 4,
    # neon-city 2, dev-story 1), so this call does work on most turns played.
    try:
        from engine.game import clocks as clocks_module

        clocks_module.resolve(state)
    except ImportError:
        pass

    expired, healed = _sweep_expiries(state)

    # Imported lazily so the clock has no hard dependency on layers that may
    # not be present in a trimmed build or a partially-migrated checkout.
    try:
        from engine.game import survival

        survival.tick(state, hours)
    except ImportError:
        pass

    try:
        from engine.world import npc_sim

        # Presence itself is derived on read; this sweeps dated quest pins so
        # a pin cannot outlive the quest that set it.
        npc_sim.refresh(state)
    except ImportError:
        pass

    # Death handling advances the clock itself (unconsciousness costs hours),
    # which re-enters this function. Unguarded, each nested call ran the death
    # check again and the calendar ran away -- measured jumping day 2 to day 123
    # in a single 8-hour step.
    if not _in_death_check():
        try:
            from engine.game import encounter

            # Starvation decrements hp every hour and nothing else checks the
            # threshold, so without this a starving player parks at hp 0
            # forever -- a soft-lock reachable just by not eating.
            with _death_check_guard():
                encounter.check_death(state)
        except ImportError:
            pass

    to_day, to_hour = state.world_day, state.world_hour
    if to_day != from_day:
        # Contracts whose day has passed break on the rollover. Silence is an
        # answer too: a bargain the player quietly let lapse should cost them
        # the same as one they refused out loud.
        #
        # On the day tick specifically, beside the wound and effect sweep --
        # a due date is a calendar fact, and running it per hour would break a
        # thread up to twenty-three hours before its day was actually over.
        try:
            from engine.game import threads as threads_module

            threads_module.expire_due(state)
        except ImportError:
            pass

        logger.info(
            "[clock] Day rolled (operation=advance_time, from=%s, to=%s)",
            from_day,
            to_day,
        )

    return TimeAdvance(
        hours=float(hours),
        days=days,
        day_rolled=to_day > from_day,
        from_day=from_day,
        to_day=to_day,
        from_hour=from_hour,
        to_hour=to_hour,
        expired_effects=expired,
        healed_wounds=healed,
    )


def set_clock(state: GameState, *, day: int, hour: int) -> None:
    """
    Hard-set the clock without side effects. Tests and migrations only.

    Never call this from gameplay -- it skips evil progression, expiry sweeps
    and survival, which is precisely the class of bug this module exists to
    prevent.
    """
    state.world_clock_hours = float((max(1, day) - 1) * HOURS_PER_DAY + (hour % 24))


def hours_until(state: GameState, hour: int) -> float:
    """Hours from now until the next occurrence of the given hour of day."""
    target = hour % 24
    current = state.world_clock_hours % 24
    delta = target - current
    if delta <= 0:
        delta += 24
    return delta
