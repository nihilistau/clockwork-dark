"""
Shared setups for The Clockwork Dark's doors and deaths (v0.25.0).

WHY THIS MODULE EXISTS. The stored ``state.evil_phase`` does NOT follow
``state.evil_progress`` by itself: it is re-synced only when the state is
built (``GameState.__post_init__``) or when the doom ticker advances
(``EvilTicker.advance``, inside ``clock.advance_time``), and the doom beats
fire only from ``advance_time`` too (``world_effects.apply_pending_beats``).
A test that writes ``state.evil_progress = 0.85`` alone therefore leaves a
``dormant`` phase and no beat flags behind it -- a state that disagrees with
itself, so a door or a death keyed on the phase reads the wrong world.

``at_reading`` sets the reading the way the engine would have reached it:
the progress, the stored phase synced by the engine's own
``phase_from_progress``, and every doom beat the reading has crossed fired
through ``world_effects.apply_pending_beats`` (the engine's own path, never
flags written by hand). Every setup that sets the reading uses it (T3, and
T6, T7 and T9 extend this module).

Version: v0.1.0 [2026-10-28]
"""

from __future__ import annotations

from typing import Any

__all__ = ["at_reading"]


def at_reading(state: Any, progress: float) -> Any:
    """
    Stand ``state`` at doom reading ``progress``, phase and beats in step.

    Args:
        state: A mutable GameState of the active story.
        progress: The reading, 0..1.

    Returns:
        The same state, for chaining.
    """
    from engine.game.evil_ticker import phase_from_progress
    from engine.world import world_effects

    state.evil_progress = float(progress)
    state.evil_phase = phase_from_progress(state.evil_progress)
    world_effects.apply_pending_beats(state)
    return state
