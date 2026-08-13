"""
Compatibility shim -- the scene moved to ``engine/scenes/default_scene.py``.

DEPRECATED IMPORT PATH, kept so no import site anywhere else breaks. The scene
server here served every story (the page title, opening frames and content all
follow the active manifest); in v0.3.0 it moved into the engine and this
package kept only what is genuinely the flagship's: the shared client asset
tree (``static/``, ``templates/`` -- pinned here by ``ui/vite.config.js``'s
build output and the shipped art pack).

Import from ``engine.scenes.default_scene`` in new code. The module globals
(session store, scene singleton) live there now: ``get_store``/``reset_store``
imported from here still operate on the engine module's store.
"""

from __future__ import annotations

from engine.scenes.default_scene import (  # noqa: F401
    SCENE_METADATA,
    SCENE_NAME,
    DefaultScene,
    create_app,
    get_store,
    reset_store,
    run_scene,
    scene_metadata,
)

# The name this module exported before the move.
ClockworkScene = DefaultScene

__all__ = [
    "ClockworkScene",
    "DefaultScene",
    "SCENE_METADATA",
    "SCENE_NAME",
    "create_app",
    "get_store",
    "reset_store",
    "run_scene",
    "scene_metadata",
]
