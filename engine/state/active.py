"""
The Active Story's Schema
=========================

One lazily-built ``StateSchema`` for whichever story is running, plus a helper
that hands you a store over a given state.

WHY THIS IS NOT INSIDE THE REGISTRY. ``engine/games/registry.py`` knows about
manifests and config; making it also know about state schemas would put a second
responsibility in the module that owns activation atomicity, and it would pull
``engine.state`` into the import graph underneath ``engine.config``. Two latent
import cycles have already been paid for in this repo. The registry stays the
authority on WHICH story is active; this module asks it, and caches the answer.

The cache is registered in ``engine/games/caches.py`` like every other
config-derived cache, so a game swap invalidates it through the one path that
already exists rather than a second ad-hoc reset.

Version: v0.1.0 [2026-08-08]
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from engine.state.schema import SchemaError, StateSchema, load_schema
from engine.state.store import StateStore

logger = logging.getLogger(__name__)

_schema: Optional[StateSchema] = None
_roster: Optional[Any] = None


def active_schema() -> StateSchema:
    """
    The running story's state declaration.

    Returns an EMPTY schema rather than raising when a story declares none, or
    when the manifest cannot be read. A story without a schema runs on the
    engine spine, which is exactly what both shipped games did before this layer
    existed -- refusing to start over a missing optional file would turn an
    additive change into a breaking one.
    """
    global _schema
    if _schema is not None:
        return _schema

    try:
        from engine.games.registry import active_slug, peek

        manifest = peek()
        if manifest is None:
            _schema = StateSchema(slug=active_slug())
            return _schema

        path = manifest.state_schema_path
        if path is None:
            _schema = StateSchema(slug=manifest.slug)
            return _schema

        _schema = load_schema(path, slug=manifest.slug)
    except SchemaError:
        # A malformed schema is a real error and must not be swallowed: the
        # story asked for state it will not get.
        raise
    except Exception as exc:  # noqa: BLE001 -- never block a turn on introspection
        logger.debug("[state] No active schema available: %s", exc)
        _schema = StateSchema()

    return _schema


def active_roster() -> Any:
    """
    The running story's declared cast, or an empty roster.

    Cached beside the schema and cleared by the same reset, because the two are
    read together on any turn that involves an agent -- and a roster left over
    from the previous story would grant its permissions to this one's agents.

    Returns an EMPTY roster when a story declares no ``agents.yaml``, which is
    both shipped games: they run the engine's built-in narrator and companion,
    exactly as before.
    """
    global _roster
    if _roster is not None:
        return _roster

    from engine.agents.roster import Roster, load_roster

    try:
        from engine.games.registry import peek

        manifest = peek()
        if manifest is None or manifest.root is None:
            _roster = Roster()
            return _roster
        _roster = load_roster(manifest.root / "agents.yaml", slug=manifest.slug)
    except Exception as exc:  # noqa: BLE001 -- never block a turn on the roster
        logger.debug("[state] No active roster: %s", exc)
        _roster = Roster()
    return _roster


def reset_schema() -> None:
    """Drop the cached schema and roster. Registered in engine/games/caches.py."""
    global _schema, _roster
    _schema = None
    _roster = None


def store_for(state: Any) -> StateStore:
    """
    A store over this state, using the active story's schema.

    Built per call rather than cached on the state: ``StateStore`` holds the
    GameState by reference, and a rollback replaces that object's contents in
    place. A store cached across a rollback would be reading a journal from a
    turn that no longer happened.
    """
    return StateStore(state, active_schema())


__all__ = ["active_roster", "active_schema", "reset_schema", "store_for"]
