"""
Games HTTP API
==============

The data behind a title-screen game picker.

    GET  /api/games          every discovered game, playable or not
    GET  /api/games/active   the one currently in force
    GET  /api/games/<slug>   one game, with its validation problems

This module ships the routes only. The picker UI is somebody else's file; all
it needs is a list it can render and a slug it can pass back. Nothing here
activates a game -- switching stories mid-session would invalidate every save
and cache under a live turn, so selection stays a launch-time decision made by
``launcher.py``.

Wire it into a scene with one line in its ``register()``::

    from engine.games.api import games_blueprint
    app.register_blueprint(games_blueprint())

Version: v0.1.0 [2026-08-08]
"""

from __future__ import annotations

import logging
from typing import Any

from flask import Blueprint, jsonify

from engine.games import registry

logger = logging.getLogger(__name__)

BLUEPRINT_NAME = "games"


def games_blueprint(name: str = BLUEPRINT_NAME) -> Blueprint:
    """
    Build the games blueprint.

    A factory rather than a module-level singleton: Flask refuses to register
    the same blueprint object on two apps, and the test suite builds a fresh
    app per case.

    Args:
        name: Blueprint name, in case a host app already has one called
            "games".

    Returns:
        An unregistered Blueprint carrying the three read-only routes.
    """
    blueprint = Blueprint(name, __name__)

    @blueprint.get("/api/games")
    def list_games() -> Any:
        games = registry.catalog()
        return jsonify(
            {
                "games": games,
                "active": registry.active_slug(),
                "default": registry.DEFAULT_SLUG,
            }
        )

    @blueprint.get("/api/games/active")
    def active_game() -> Any:
        manifest = registry.peek()
        if manifest is None:
            # Nothing has been activated, which is the normal state for a
            # process that never called activate() -- the config's own paths
            # are in force. Report the slug that WOULD be used rather than
            # activating one as a side effect of a GET.
            return jsonify({"active": registry.active_slug(), "manifest": None})
        return jsonify({"active": manifest.slug, "manifest": manifest.to_dict()})

    @blueprint.get("/api/games/<slug>")
    def one_game(slug: str) -> Any:
        manifest = registry.get(slug)
        if manifest is None:
            return jsonify({"error": f"no such game: {slug}"}), 404
        problems = registry.validate(manifest)
        payload = manifest.to_dict()
        payload["playable"] = not problems
        payload["problems"] = problems
        payload["active"] = slug == registry.active_slug()
        return jsonify(payload)

    return blueprint


__all__ = ["BLUEPRINT_NAME", "games_blueprint"]
