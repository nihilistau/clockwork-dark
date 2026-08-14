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

from engine.game import effects as effects_module
from engine.game import foraging, inventory, survival
from engine.game.clock import advance_time
from engine.game.dice import DiceResult, resolve_check, roll_dice
from engine.game.evil_ticker import EvilTicker
from engine.game.locations import get_edge, get_location
from engine.game.plot import PlotFormula
from engine.game.rng import DICE as RNG_DICE
from engine.game.rng import world_rng
from engine.game.state import GameState
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
    # True when the leg was walked over the carry limit and priced accordingly
    # -- see engine/game/inventory.py::travel_stamina_multiplier. Carried so
    # the receipt can say WHY the leg cost half again what the road charges.
    overloaded: bool = False

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
            "overloaded": self.overloaded,
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
        # A discovered hidden path (engine/game/foraging.py) is a way through
        # the wood the map does not draw. It can OPEN a leg the graph lacks and
        # SHORTEN one it has; it can never lengthen one, and an undiscovered
        # path changes nothing -- the graph answers exactly as before.
        shortcut = foraging.shortcut_hours(self.state, current, location_id)
        if edge is None:
            if shortcut is None:
                return MoveResult(
                    success=False,
                    from_id=current,
                    to_id=location_id,
                    hours=0,
                    stamina_cost=0,
                    message=f"Cannot travel from {current} to {location_id}.",
                )
            # A quiet way, by definition: no road, no toll, nobody watching.
            edge = {"hours": shortcut, "danger_dc": 0, "awareness_delta": 0}

        hours = int(edge.get("hours", 1))
        if shortcut is not None:
            hours = min(hours, shortcut)
        # Carry weight bites here and only here. An over-limit pack scales what
        # a leg costs (engine/game/inventory.py::travel_stamina_multiplier);
        # the walk is never refused, no check is docked, and rest never reads
        # it -- gating rest is CLAUDE.md rule 6's soft-lock.
        overloaded = inventory.overloaded(self.state)
        # CLAUDE.md RULE 6, ONE LAYER DOWN. Stamina is only a resource in a
        # story that ships a way to get it back. `rest_kinds()` reads
        # `survival.yaml` inside `paths.rules`, and a story that ships none has
        # no rest verb at all (engine/game/intents.py::_rest returns None) --
        # so charging a walk against a meter nothing can refill is not a cost,
        # it is a countdown to a dead save.
        #
        # THIS WAS REACHABLE AND SHIPPED. The Wicked Garden declares a travel
        # graph and deliberately no survival rules: no hunger, no stamina, no
        # food, because time there is counted by the ten-day toll. It still
        # paid 5 stamina per hour walked, and measured, a run hit "Not enough
        # stamina." on its FOURTEENTH leg with nothing in the story able to
        # give any back. That is the exact soft-lock rule 6 exists to forbid,
        # rebuilt by absence rather than by a gate. Dev Story leaks the same
        # way, one point per interior door.
        #
        # Stories that DO ship survival rules -- the flagship, NEON CITY --
        # are untouched: `rest_kinds()` is non-empty, and the arithmetic below
        # is exactly what it was, carry multiplier and all.
        prices_stamina = bool(survival.rest_kinds())
        stamina_cost = (
            max(1, int(hours * 5 * inventory.travel_stamina_multiplier(self.state)))
            if prices_stamina
            else 0
        )
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

        # Both costs go through the one writer (CLAUDE.md rule 3): the stamina
        # spend and the awareness drift used to be inline arithmetic here, the
        # only travel mutations with no receipt and no clamp of their own.
        effects_module.apply_effect(
            self.state, {"type": "stamina", "delta": -stamina_cost}
        )
        self.state.location_id = location_id
        # Travel time goes through the clock so evil, survival and expiries all
        # advance with it. The old inline arithmetic moved the calendar without
        # ticking anything, and mis-rolled the day for hours == 0 and hours >= 24.
        advance_time(self.state, float(hours))

        awareness_delta = float(edge.get("awareness_delta", 0))
        effects_module.apply_effect(
            self.state, {"type": "awareness", "delta": awareness_delta}
        )
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
            overloaded=overloaded,
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
        """Add or stack an inventory item, through the one writer."""
        effects_module.apply_effect(
            self.state, {"type": "item", "item_id": item_id, "name": name, "qty": qty}
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