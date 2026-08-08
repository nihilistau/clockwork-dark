"""
WorldSim
========

Background world ticks — evil advance, schedules, plot pressure.

Version: v0.2.0 [2026-08-07]
"""

from __future__ import annotations

import logging
import random
import time
from typing import Any, Optional

from engine.config import get_config
from engine.game.clock import advance_time
from engine.game.rng import (
    SCHEDULE_CARAVAN,
    SCHEDULE_MILITIA,
    SCHEDULE_TINKER,
    world_rng,
)
from engine.game.state import GameState
from engine.world import npc_sim
from engine.world.schedules import ScheduleRoll, SimEvent, load_schedules

logger = logging.getLogger(__name__)


def visiting_npcs_at_location(state: GameState, location_id: str) -> list[dict[str, Any]]:
    """
    Return NPC presence entries from active world events at a location.

    Args:
        state: Current game state.
        location_id: Location to query.

    Returns:
        List of dicts with id, name, role, visiting=True.
    """
    present: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in state.world_events:
        if raw.get("location_id") != location_id:
            continue
        for npc_id in raw.get("npc_ids", []):
            if npc_id in seen:
                continue
            seen.add(npc_id)
            procgen_npc = state.procgen.npc_by_id(str(npc_id))
            if procgen_npc:
                entry = dict(procgen_npc)
            else:
                entry = {"id": npc_id, "name": npc_id, "role": "visitor"}
            entry["visiting"] = True
            entry["event_id"] = raw.get("event_id")
            present.append(entry)
    return present



def merge_npcs_at_location(state: GameState, location_id: str) -> list[dict[str, Any]]:
    """
    Everyone at a location right now, with what they are doing.

    Delegates to ``npc_sim``, which resolves routines, events, overrides and
    quest pins in one place. This used to read ``procgen.npcs_at()`` directly,
    and procgen writes an NPC's location once at world generation and never
    again -- so Maris was in her bakery at 03:00 and forest_clearing, the
    location every run starts in, was empty.

    Args:
        state: Current game state.
        location_id: Location to query.

    Returns:
        List of dicts carrying the original procgen fields (traits, canon)
        plus id/name/role/location_id/activity/available/visiting/event_id.
        ``activity`` is rendered verbatim into the Storyteller prompt.
    """
    merged: list[dict[str, Any]] = []
    for presence in npc_sim.npcs_at(state, location_id):
        entry = dict(state.procgen.npc_by_id(presence.npc_id) or {})
        entry.update(presence.to_dict())
        merged.append(entry)
    return merged


class WorldSim:
    """Orchestrates world tick side effects."""

    @staticmethod
    def tick_interval_seconds() -> int:
        """Real-time seconds between optional background ticks."""
        return int(get_config().get("world.tick_interval_seconds", 60))

    @staticmethod
    def realtime_tick_hours(
        last_tick_at: float,
        *,
        now: Optional[float] = None,
    ) -> float:
        """
        In-game hours the background world has earned since the last tick.

        Replaces a step function with a rate. The old form answered a yes/no
        question and the caller then granted a flat 6 hours, so a 61-second
        turn and a ten-minute turn cost exactly the same, and a turn at 59
        seconds cost nothing -- the clock moved in cliffs that had no relation
        to how long the player actually took. That constant was also 60% of
        every hour the game ever advanced (issue R-03).

        Args:
            last_tick_at: Wall-clock stamp of the previous tick. Zero or less
                means "tick now" -- a new game, and the documented way for
                tests to force one (``state.last_sim_tick_at = 0.0``).
            now: Wall-clock override for tests.

        Returns:
            Hours to advance, or 0.0 when not enough real time has passed.
            Never more than ``world.tick_max_hours``.
        """
        cfg = get_config()
        base = float(cfg.get("world.tick_hours", 2.0))
        interval = WorldSim.tick_interval_seconds()

        # A forced tick has no elapsed time to scale by, so it gets exactly one
        # interval's worth rather than a guess.
        if last_tick_at <= 0:
            return base
        if interval <= 0:
            return base

        elapsed = max(0.0, (now if now is not None else time.time()) - last_tick_at)
        if elapsed < interval:
            return 0.0

        cap = float(cfg.get("world.tick_max_hours", 6.0))
        return min(base * (elapsed / interval), cap)

    @staticmethod
    def should_run_realtime_tick(
        last_tick_at: float,
        *,
        now: Optional[float] = None,
    ) -> bool:
        """
        Whether the background world owes the player any time.

        Kept as the predicate half of ``realtime_tick_hours`` so the two can
        never disagree about when a tick is due.
        """
        return WorldSim.realtime_tick_hours(last_tick_at, now=now) > 0.0

    @staticmethod
    def expire_events(state: GameState) -> None:
        """
        Remove world events whose life has run out.

        ``expires_day`` is the first day on which the event is NOT active. An
        event created on day 6 with duration 2 gets expires_day 8, so it runs
        on days 6 and 7 and is gone on day 8. The old comparison was ``>=``,
        which gave a two-day event three days of life.

        A malformed event with no expiry is dropped rather than defaulted to
        "alive today", which previously made it immortal.
        """
        day = state.world_day
        kept: list[dict[str, Any]] = []
        for event in state.world_events:
            raw = event.get("expires_day")
            if raw is None:
                logger.warning(
                    "[world_sim] Dropping event with no expiry "
                    "(operation=expire_events, event=%s)",
                    event.get("event_id"),
                )
                continue
            try:
                if int(raw) > day:
                    kept.append(event)
            except (TypeError, ValueError):
                logger.warning(
                    "[world_sim] Dropping event with bad expiry "
                    "(operation=expire_events, event=%s, expires_day=%r)",
                    event.get("event_id"),
                    raw,
                )
        state.world_events = kept

    @staticmethod
    def apply_events(state: GameState, events: list[SimEvent]) -> None:
        """Persist events and rumors on state."""
        for event in events:
            state.world_events = [
                e for e in state.world_events if e.get("event_id") != event.event_id
            ]
            state.world_events.append(event.to_dict())
            rumor = event.payload.get("rumor")
            if rumor and rumor not in state.rumors:
                state.rumors.append(str(rumor))
            logger.info(
                "[world_sim] Event applied (operation=apply_events, event=%s, day=%s)",
                event.event_id,
                event.day,
            )

    @staticmethod
    def on_tick(
        state: GameState,
        *,
        hours: float = 24.0,
        rng: Optional[random.Random] = None,
        force: Optional[list[str]] = None,
    ) -> list[SimEvent]:
        """
        Advance world simulation for elapsed in-game hours.

        Takes hours rather than days because the old float-days signature made
        the truncation bug easy to write: callers passed 0.25 and the calendar
        silently discarded it.

        Args:
            state: Mutable game state.
            hours: In-game hours to advance.
            rng: Optional RNG override for tests. When omitted, each schedule
                draws from its own named stream so they stay uncorrelated.
            force: Force specific event ids (caravan_arrival, tinker_camp,
                militia_press).

        Returns:
            List of SimEvent emitted this tick.
        """
        force_set = set(force or [])
        schedules = load_schedules()
        days_elapsed = float(hours) / 24.0

        advance_time(state, float(hours))
        state.last_sim_tick_at = time.time()
        WorldSim.expire_events(state)

        events: list[SimEvent] = []
        events.extend(
            ScheduleRoll.check_caravan(
                state,
                rng or world_rng(state, SCHEDULE_CARAVAN),
                schedules=schedules,
                force="caravan_arrival" in force_set,
            )
        )
        events.extend(
            ScheduleRoll.check_tinker(
                state,
                rng or world_rng(state, SCHEDULE_TINKER),
                days_elapsed=days_elapsed,
                schedules=schedules,
                force="tinker_camp" in force_set,
            )
        )
        events.extend(
            ScheduleRoll.check_militia(
                state,
                rng or world_rng(state, SCHEDULE_MILITIA),
                schedules=schedules,
                force="militia_press" in force_set,
            )
        )

        WorldSim.apply_events(state, events)
        return events