"""
Compatibility shim -- the screens moved to ``engine/scenes/default_api.py``.

DEPRECATED IMPORT PATH, kept so no import site anywhere else breaks. Every
route in this blueprint resolves through ``paths.*`` on the active manifest,
so nothing in it was Clockwork-shaped by the time it moved in v0.3.0 -- it is
the engine's DEFAULT story blueprint now, still mounted only when a story's
``scene.blueprint`` names it (or names nothing, which defaults to it).

Import from ``engine.scenes.default_api`` in new code.
"""

from __future__ import annotations

from engine.scenes.default_api import (  # noqa: F401
    BLUEPRINT_NAME,
    codex_places,
    codex_souls,
    codex_things,
    item_catalog,
    notice_board,
    quest_journal,
    recipe_book,
    story_blueprint,
    trade_offer,
)

__all__ = [
    "BLUEPRINT_NAME",
    "codex_places",
    "codex_souls",
    "codex_things",
    "item_catalog",
    "notice_board",
    "quest_journal",
    "recipe_book",
    "story_blueprint",
    "trade_offer",
]
