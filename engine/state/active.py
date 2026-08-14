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
from dataclasses import replace
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
    engine spine, which is what every game did before this layer existed --
    refusing to start over a missing optional file would turn an additive
    change into a breaking one. No shipped game relies on that any more: all
    four ship a ``state.yaml`` (clockwork-dark 15 declared values, neon-city
    24, wicked-garden 13, dev-story 3), so the empty return is the
    authoring-time and broken-manifest case only.
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

        _schema = _with_roster_grants(load_schema(path, slug=manifest.slug))
    except SchemaError:
        # A malformed schema is a real error and must not be swallowed: the
        # story asked for state it will not get.
        raise
    except Exception as exc:  # noqa: BLE001 -- never block a turn on introspection
        logger.debug("[state] No active schema available: %s", exc)
        _schema = StateSchema()

    return _schema


def _with_roster_grants(schema: StateSchema) -> StateSchema:
    """
    Fold the story's agent roster into the schema's per-value ``owners``.

    ONE PLACE PERMISSIONS ARE DECLARED. They had two, and the two disagreed.
    ``agents.yaml`` grants an agent its ``writes`` and ``writes_with_reason``;
    ``state.yaml`` grants a value its ``owners``; the store enforces the second
    and nothing reconciled them. The Wicked Garden's roster granted ``gm`` ten
    values and Sophia three, and its schema named owners for two -- so the world
    agent could not move ``corruption``, the meter its whole story turns on, and
    Sophia's ``autonomy`` write (the one permission that can close the door
    home) was refused with ``owners=[]`` every time she asked.

    Neither file was wrong on its own, which is what made it invisible. So the
    roster is now the source and the schema's ``owners`` is derived: a story
    declares who may write what once, beside the agent it belongs to, and the
    store still does the enforcing. A value's own ``owners:`` list still works
    and is unioned in, for a story that has no roster or wants to grant
    something to an agent it does not declare.

    Costs nothing for a story with no ``agents.yaml`` -- an empty roster grants
    nothing, and the schema comes back untouched. No shipped game is that story
    any more: all four declare a roster, and three of them actually derive
    owners here (wicked-garden 12 values, dev-story 2, neon-city 1). The
    flagship declares a roster that grants none, so it is the only one whose
    schema still comes back untouched. This derivation is load-bearing for the
    Garden specifically -- it is what gives Sophia the ``autonomy`` and
    ``corruption`` writes described above.
    """
    roster = active_roster()
    if not roster or not schema.values:
        return schema

    granted = 0
    for name, spec in schema.values.items():
        owners = roster.owners_for(name)
        if not owners:
            continue
        merged = tuple(dict.fromkeys(spec.owners + owners))
        if merged != spec.owners:
            granted += 1
            schema.values[name] = replace(spec, owners=merged)

    if granted:
        logger.info(
            "[state] Roster grants folded into the schema "
            "(operation=active_schema, slug=%s, values=%d)",
            schema.slug or "?",
            granted,
        )
    return schema


def active_roster() -> Any:
    """
    The running story's declared cast, or an empty roster.

    Cached beside the schema and cleared by the same reset, because the two are
    read together on any turn that involves an agent -- and a roster left over
    from the previous story would grant its permissions to this one's agents.

    Returns an EMPTY roster when a story declares no ``agents.yaml``. The
    flagship declares none and runs the engine's built-in narrator and
    companion, exactly as before; The Wicked Garden ships a two-agent roster,
    which is what sends its turns through the plan/negotiate/commit pipeline.
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
