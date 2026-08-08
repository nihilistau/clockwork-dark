"""
Shared Scene API
================

The routes every story serves, as Blueprint factories.

    /api/games/*        the catalogue behind a title-screen picker
    /api/archetypes     what a new run may start as
    /api/saves/*        list, write, load, delete
    /api/settings       the player's own knobs
    /api/art            manifest art key -> URL
    /api/metrics        what the agents are actually doing
    /api/audio/<name>   synthesized narration
    /api/media/<name>   generated stills and portraits
    /api/voice/transcribe

WHAT MAKES A ROUTE SHARED. It answers the same QUESTION for every story even
though the answer differs. ``/api/archetypes`` is shared because every story
has a character sheet; ``/api/quests`` is not, because a story without quests
should not have to serve an empty list to satisfy a client that assumes them.
The test is whether a second story would want the route DELETED, not merely
repointed.

A scene mounts the whole set in one line::

    for blueprint in shared_blueprints(self.store, llm_fn=self.llm_fn):
        app.register_blueprint(blueprint)

Story-owned screens go in a separate blueprint the scene mounts alongside --
see ``engine/scenes/spec.load_story_blueprint`` and
``content/scenes/clockwork/clockwork_api.py``.

Version: v0.1.0 [2026-08-08]
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from flask import Blueprint

from engine.api.archetypes import archetypes_blueprint
from engine.api.art import art_blueprint, shipped_art_url
from engine.api.media import media_blueprint
from engine.api.metrics import metrics_blueprint
from engine.api.saves import saves_blueprint
from engine.api.settings import settings_blueprint
from engine.api.voice import voice_blueprint
from engine.games.api import games_blueprint
from engine.session import SessionStore


def shared_blueprints(
    store: SessionStore,
    *,
    llm_fn: Optional[Callable[[list[dict[str, Any]]], str]] = None,
) -> list[Blueprint]:
    """
    Every engine-shared blueprint, ready to register.

    Args:
        store: The scene's session registry. Two of these routes reach into a
            live run (writing a save, speaking into one), so the set cannot be
            built without it.
        llm_fn: Agent transport handed to sessions this set creates -- today
            only the one a loaded save produces.

    Returns:
        Unregistered Blueprints, in mount order. Order carries no meaning:
        no two of these claim the same rule.
    """
    return [
        games_blueprint(),
        archetypes_blueprint(),
        saves_blueprint(store, llm_fn=llm_fn),
        settings_blueprint(),
        art_blueprint(),
        metrics_blueprint(),
        media_blueprint(),
        voice_blueprint(store),
    ]


__all__ = [
    "archetypes_blueprint",
    "art_blueprint",
    "games_blueprint",
    "media_blueprint",
    "metrics_blueprint",
    "saves_blueprint",
    "settings_blueprint",
    "shared_blueprints",
    "shipped_art_url",
    "voice_blueprint",
]
