"""
Story state: the schema that declares it and the store that reads and writes it.

Lazy re-exports via PEP 562. Two import cycles have already been introduced in
this repo by an ``__init__`` that eagerly imported its own submodules, and this
package is imported from ``engine.game.state``, which is close to the bottom of
the dependency graph.

Version: v0.1.0 [2026-08-08]
"""

from __future__ import annotations

from typing import Any

_EXPORTS = {
    "SchemaError": "engine.state.schema",
    "StateSchema": "engine.state.schema",
    "ValueSpec": "engine.state.schema",
    "load_schema": "engine.state.schema",
    "parse_schema": "engine.state.schema",
    "StateStore": "engine.state.store",
    "WRITER_ENGINE": "engine.state.store",
}


def __getattr__(name: str) -> Any:
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    return getattr(importlib.import_module(module_name), name)


def __dir__() -> list[str]:
    return sorted(_EXPORTS)


__all__ = list(_EXPORTS)
