"""
Game Engine
===========

Action resolution — sole authority on state mutations.

Version: v0.1.0 [2026-06-20]
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from typing import Any, Iterator, Optional

from engine.game.clock import advance_time
from engine.game.dice import DiceResult, resolve_check, roll_dice
from engine.game.evil_ticker import EvilTicker
from engine.game.locations import get_edge, get_location
from engine.game.plot import PlotFormula
from engine.game.rng import DICE as RNG_DICE
from engine.game.rng import world_rng
from engine.game.state import GameState, InventoryItem
from engine.world.world_sim import WorldSim


# A single tick may never advance more than this. Guards against a runaway or
# hostile caller reaching the endgame phase in one step.
MAX_TICK_DAYS = 30.0


@dataclass
class MoveResult:
    """Travel outcome."""

    success: bool
    from_id: str
    to_id: str
    hours: int
    stamina_cost: int
    message: str
    awareness_delta: float = 0.0
    # The scene the road produced, if any. Empty dict for a quiet trip. Travel
    # still succeeds either way -- an encounter is what you walked into, not a
    # reason the walk failed.
    encounter: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "from_id": self.from_id,
            "to_id": self.to_id,
            "hours": self.hours,
            "stamina_cost": self.stamina_cost,
            "message": self.message,
            "awareness_delta": self.awareness_delta,
            "encounter": dict(self.encounter),
        }


class GameEngine:
    """Deterministic game logic bound to a GameState."""

    def __init__(self, state: GameState) -> None:
        self.state = state

    def move_to(self, location_id: str) -> MoveResult:
        """Validate and execute travel along location graph."""
        current = self.state.location_id
        if location_id == current:
            return MoveResult(
                success=True,
                from_id=current,
                to_id=location_id,
                hours=0,
                stamina_cost=0,
                message="Already here.",
            )

        edge = get_edge(current, location_id)
        if edge is None:
            return MoveResult(
                success=False,
                from_id=current,
                to_id=location_id,
                hours=0,
                stamina_cost=0,
                message=f"Cannot travel from {current} to {location_id}.",
            )

        hours = int(edge.get("hours", 1))
        stamina_cost = max(1, hours * 5)
        if self.state.stats.stamina < stamina_cost:
            return MoveResult(
                success=False,
                from_id=current,
                to_id=location_id,
                hours=hours,
                stamina_cost=stamina_cost,
                message="Not enough stamina.",
            )

        if get_location(location_id) is None:
            return MoveResult(
                success=False,
                from_id=current,
                to_id=location_id,
                hours=hours,
                stamina_cost=stamina_cost,
                message=f"Unknown location: {location_id}.",
            )

        self.state.stats.stamina -= stamina_cost
        self.state.location_id = location_id
        # Travel time goes through the clock so evil, survival and expiries all
        # advance with it. The old inline arithmetic moved the calendar without
        # ticking anything, and mis-rolled the day for hours == 0 and hours >= 24.
        advance_time(self.state, float(hours))

        awareness_delta = float(edge.get("awareness_delta", 0))
        self.state.awareness = min(100.0, self.state.awareness + awareness_delta)
        PlotFormula.update_story_pressure(self.state)

        return MoveResult(
            success=True,
            from_id=current,
            to_id=location_id,
            hours=hours,
            stamina_cost=stamina_cost,
            message=f"Arrived at {location_id}.",
            awareness_delta=awareness_delta,
            encounter=self._roll_travel_encounter(current, location_id),
        )

    def _roll_travel_encounter(self, from_id: str, to_id: str) -> dict[str, Any]:
        """
        Roll the arrival encounter for a completed travel leg.

        This is the first thing in the project's history to read an edge's
        ``danger_dc``; it has been sitting on every connection in
        engine/game/locations.py since the graph was written, unused, so the
        Millhaven road was exactly as safe at midnight during ``consuming`` as
        the walk to the bakery at noon on day one.

        Args:
            from_id: Origin location id.
            to_id: Destination location id.

        Returns:
            The scene now held on ``state.encounter``, or ``{}``.
        """
        from engine.game import encounter as encounter_module

        # An unresolved scene is not overwritten by walking away from it. The
        # player can leave -- travel always completes -- but the road does not
        # get to hand them a second problem while the first is open.
        if encounter_module.active(self.state):
            return dict(self.state.encounter)

        drawn = encounter_module.roll_for_encounter(self.state, from_id, to_id)
        if drawn is None:
            return {}
        return encounter_module.begin(self.state, str(drawn.get("id", "")))

    def roll(self, sides: int = 20, modifier: int = 0, reason: str = "") -> DiceResult:
        """
        Roll dice on the state's deterministic dice stream.

        Previously this used the process-global ``random``, so outcomes were
        neither reproducible nor isolated between concurrent sessions.
        """
        return roll_dice(
            sides=sides,
            modifier=modifier,
            reason=reason,
            rng=world_rng(self.state, RNG_DICE),
        )

    def skill_check(
        self,
        skill: str,
        difficulty: str = "standard",
        *,
        advantage: int = 0,
    ) -> dict[str, Any]:
        """
        Resolve a skill check through the rules engine.

        Kept as a thin wrapper rather than deleted: the old signature took a
        raw ``dc`` and an already-computed ``modifier``, which is the exact
        model the overhaul replaced. Leaving that version in place -- callerless
        but importable -- is how it gets found and used again six months from
        now. This one routes to engine/game/checks.py like everything else.
        """
        from engine.game import checks

        return checks.resolve(
            self.state, skill, difficulty, advantage=advantage
        ).to_dict()

    def advance_world_day(
        self,
        days: float = 1.0,
        *,
        force_events: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        """
        Advance world time via WorldSim tick (evil, schedules, rumors).

        Bounded deliberately. This is reachable from a system skill, and an
        unbounded value let one call jump the world to CONSUMING or rewind the
        calendar entirely.
        """
        if days < 0:
            raise ValueError(f"cannot advance world time backward (days={days})")
        days = min(float(days), MAX_TICK_DAYS)
        events = WorldSim.on_tick(
            self.state,
            hours=days * 24.0,
            force=force_events,
        )
        return {
            "world_day": self.state.world_day,
            "evil_progress": self.state.evil_progress,
            "evil_phase": self.state.evil_phase.value,
            "plot_involvement": self.state.plot_involvement,
            "events": [e.to_dict() for e in events],
            "rumors": list(self.state.rumors),
        }

    def add_item(self, item_id: str, name: str, qty: int = 1) -> None:
        """Add or stack inventory item."""
        for entry in self.state.inventory:
            if entry.id == item_id:
                entry.qty += qty
                return
        self.state.inventory.append(
            InventoryItem(id=item_id, name=name, qty=qty, tags=[])
        )

    def get_evil_snapshot(self) -> dict[str, str | float]:
        """Storyteller-only evil state."""
        return EvilTicker.snapshot(self.state)


# Active engine for skill handlers.
#
# This was a module-level global. With Socket.IO in threading mode, one session
# could rebind it while another was blocked on a multi-second LLM call, so
# skills resolved against the wrong player's state. A ContextVar is per-thread
# and per-task, which closes that window without touching any call site.
_active_engine: ContextVar[Optional[GameEngine]] = ContextVar(
    "clockwork_active_engine", default=None
)


def set_active_engine(engine: GameEngine) -> Token:
    """Bind active engine for skill execution context. Returns a reset token."""
    return _active_engine.set(engine)


def get_active_engine() -> GameEngine:
    """Return active engine or raise."""
    engine = _active_engine.get()
    if engine is None:
        raise RuntimeError("No active GameEngine — call set_active_engine first")
    return engine


@contextmanager
def active_engine(engine: GameEngine) -> Iterator[GameEngine]:
    """Scope an engine to a block, restoring the previous binding on exit."""
    token = _active_engine.set(engine)
    try:
        yield engine
    finally:
        _active_engine.reset(token)