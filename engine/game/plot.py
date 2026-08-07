"""
Plot Formula
============

Computes plot_involvement and story_pressure from engine state.

The arc term used to be ``flags.get("main_quest_started")``, worth a flat 15
points. Nothing in the codebase ever set that flag -- not the engine, not the
world sim, not a single skill -- so the only pacing formula the game has
carried a term that was always zero. How deep into the story the player had
gone simply did not register.

It is now the involvement weight of the arc they are actually in, declared in
``data/quests/arcs.yaml`` and read through ``engine.game.quests``. Quiet Life
weighs 0 on purpose: a player who bakes bread is not behind schedule, so the
Storyteller should feel no pressure to escalate on them.

Version: v0.2.0 [2026-08-07]
"""

from __future__ import annotations

from engine.game.locations import LOCATIONS
from engine.game.quests import arc_involvement
from engine.game.state import GameState


class PlotFormula:
    """Derive narrative pressure signals from hard state."""

    @staticmethod
    def inward_distance(location_id: str) -> int:
        """Return location ring as proxy for distance to Heartlands."""
        loc = LOCATIONS.get(location_id, {})
        return int(loc.get("ring", 0))

    @staticmethod
    def arc_weight(state: GameState) -> float:
        """
        Involvement contributed by the story arc the player is currently in.

        Args:
            state: Current game state.

        Returns:
            The arc's declared ``involvement``, or 0.0 for an arc the content
            pack does not describe.
        """
        return arc_involvement(state.active_arc)

    @staticmethod
    def compute(state: GameState) -> float:
        """
        Compute plot_involvement (0–100) from awareness, travel, and story arc.

        Args:
            state: Current game state.

        Returns:
            Updated plot_involvement (also written to state).
        """
        ring = PlotFormula.inward_distance(state.location_id)
        involvement = (
            state.awareness * 0.4
            + ring * 12.0
            + PlotFormula.arc_weight(state)
            + state.evil_progress * 20.0
        )
        state.plot_involvement = min(100.0, max(0.0, involvement))
        return state.plot_involvement

    @staticmethod
    def update_story_pressure(state: GameState) -> float:
        """
        Story pressure rises with plot involvement and low storyteller patience.

        Args:
            state: Current game state.

        Returns:
            story_pressure 0–100.
        """
        PlotFormula.compute(state)
        patience_factor = (100.0 - state.storyteller_mind.patience) * 0.3
        pressure = state.plot_involvement * 0.7 + patience_factor
        state.story_pressure = min(100.0, max(0.0, pressure))
        return state.story_pressure