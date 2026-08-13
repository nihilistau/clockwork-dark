"""
Multi-Game Support
==================

The engine is one thing; a game is another. This package is the seam.

A *game* is a directory under ``games/<slug>/`` holding a ``game.yaml``
manifest and whatever content that manifest points at. Activating a game
deep-merges its ``paths:`` block over the config and invalidates every module
cache that was built from the old paths, so the same engine binary can serve
"The Clockwork Dark" and "The Wicked Garden" without an edit -- two stories
that share no meters, no travel model and no character classes.

Public surface:

    engine.games.registry    discover / validate / activate / active
    engine.games.manifest    GameManifest, the parsed manifest
    engine.games.caches      the cache-invalidation registry
    engine.games.api         Flask blueprint serving GET /api/games

Version: v0.1.0 [2026-08-08]
"""

from __future__ import annotations

# The engine's own version, matched against each manifest's
# ``engine_requires`` gate at activation. This is the ONE home for the string:
# ``engine.persistence.saves`` imports it for the save envelope, so a manifest
# gate and a save's recorded engine version cannot disagree by construction.
# tests/test_games.py still asserts the two agree -- the assertion now proves
# the import rather than a copy.
ENGINE_VERSION = "0.2.0"

__all__ = ["ENGINE_VERSION"]
