"""
Compatibility shim -- the turn moved to ``engine/scenes/default_state.py``.

DEPRECATED IMPORT PATH, kept so no import site anywhere else breaks. This
module was the turn handler for every story; in v0.3.0 it moved into the
engine, because an engine default that lives inside one story's package is a
default that story can never be absent from. Nothing here is Clockwork's --
the opening frames are read from the active manifest's ``entry.opening``.

Import from ``engine.scenes.default_state`` in new code. NOTE for tests: a
``monkeypatch.setattr`` on THIS module's attributes no longer reaches the
running code -- patch ``engine.scenes.default_state`` instead.
"""

from __future__ import annotations

from engine.scenes.default_state import (  # noqa: F401
    DefaultSessionStore,
    GameSession,
    SessionStore,
    _summarizer_fn,
    assistant_portrait_url,
    assistant_presence,
    default_archetype,
    get_save_store,
    nominal_tick_hours,
    opening,
    opening_choices,
    opening_narration,
    resolve_player_action,
    resolve_player_intent,
    resume_opening,
    run_turn,
    scene_image_url,
)

# The name this module exported before the store itself moved.
ClockworkSessionStore = DefaultSessionStore

__all__ = [
    "ClockworkSessionStore",
    "DefaultSessionStore",
    "GameSession",
    "SessionStore",
    "assistant_portrait_url",
    "assistant_presence",
    "default_archetype",
    "nominal_tick_hours",
    "opening",
    "opening_choices",
    "opening_narration",
    "resolve_player_action",
    "resolve_player_intent",
    "resume_opening",
    "run_turn",
    "scene_image_url",
]
