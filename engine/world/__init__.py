"""
World simulation — ticks, schedules, trader events.

Re-exports are resolved LAZILY (PEP 562); see engine/game/__init__.py for the
package cycle this avoids.
"""

from typing import Any

__all__ = ["WorldSim", "ScheduleRoll", "SimEvent"]

_LAZY = {
    "ScheduleRoll": "engine.world.schedules",
    "SimEvent": "engine.world.schedules",
    "WorldSim": "engine.world.world_sim",
}


def __getattr__(name: str) -> Any:
    module_path = _LAZY.get(name)
    if module_path is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    return getattr(importlib.import_module(module_path), name)


def __dir__() -> list[str]:
    return sorted(__all__)
