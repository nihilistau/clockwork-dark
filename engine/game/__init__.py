"""
Deterministic game engine — sole authority on mechanics.

Re-exports are resolved LAZILY (PEP 562). Importing them eagerly created a
package-level cycle:

    engine.world.__init__ -> schedules -> engine.game.__init__
                          -> engine.game.engine -> engine.world.world_sim
                          -> engine.world.schedules   (still initializing)

so `import engine.world.npc_sim` as the first engine import failed outright.
It only ever worked because some other module happened to import the packages
in a lucky order. Nothing here is imported until it is actually asked for.
"""

from typing import Any

__all__ = ["EvilPhase", "GameState", "PlayerStats", "GameEngine"]

_LAZY = {
    "EvilPhase": "engine.game.state",
    "GameState": "engine.game.state",
    "PlayerStats": "engine.game.state",
    "GameEngine": "engine.game.engine",
}


def __getattr__(name: str) -> Any:
    module_path = _LAZY.get(name)
    if module_path is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    return getattr(importlib.import_module(module_path), name)


def __dir__() -> list[str]:
    return sorted(__all__)
