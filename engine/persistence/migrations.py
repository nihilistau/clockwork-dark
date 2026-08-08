"""
Save Migrations
===============

Forward-only schema evolution for save files.

DESIGN.md Key Decision #11 said "JSON save v1, no migration". That was already
untrue by the time saves existed: the overhaul changes the state schema several
times over. Retrofitting a migration chain after three breaking changes costs
far more than carrying one from the start.

TWO CHAINS, AND THE SECOND ONE IS WHY THIS FILE CHANGED. There was a single
global ``MIGRATIONS`` dict keyed only by version, so a step written for one
story would run over every story's saves -- a Wicked Garden save loaded
through a Clockwork migration that backfills ``hunger`` and ``wounds``, or worse,
a second story's step reaching into a first story's document. With N stories
that is not a hypothetical; it is the first thing anyone writing story #2 hits.

    ENGINE_MIGRATIONS   the spine. world_clock_hours, RNG streams, the save
                        envelope. Runs for EVERY story, because every story is
                        built on the same GameState spine.

    STORY_MIGRATIONS    keyed by game slug, then version. Runs only over saves
                        belonging to that story, immediately after the engine
                        step for the same version -- so a story step can rely on
                        the spine already being at v+1.

A save records the story it belongs to (``game`` in the envelope, see
``saves.py``); loads of older saves that predate that key fall back to the store's
own namespace, which is the directory the save was found in and therefore always
right.

Rules:
  - Migrations run IN MEMORY on load. Nothing is rewritten on disk until the
    next ordinary save, so a failed load never destroys the original.
  - Each step is v -> v+1 and must be total: given any valid v document it
    produces a valid v+1 document without raising.
  - Never delete a migration. Old saves are the reason this file exists.

Version: v0.3.0 [2026-08-08]
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from engine.game.state import CURRENT_SAVE_VERSION

logger = logging.getLogger(__name__)

Step = Callable[[dict[str, Any]], dict[str, Any]]


def _v1_to_v2(data: dict[str, Any]) -> dict[str, Any]:
    """
    v1 -> v2: derived world clock, named RNG streams, survival fields.

    v1 stored world_day and world_hour as independent ints. v2 derives both
    from world_clock_hours, so fold the pair into a single absolute offset.
    """
    day = int(data.get("world_day", 1) or 1)
    hour = int(data.get("world_hour", 8) or 8)
    data["world_clock_hours"] = float((max(1, day) - 1) * 24 + (hour % 24))
    data.pop("world_day", None)
    data.pop("world_hour", None)

    # v1 had no dedicated RNG seed; the procgen seed is the natural source.
    procgen = data.get("procgen") or {}
    data.setdefault("rng_seed", int(procgen.get("seed", 0) or 0))
    data.pop("rng_counter", None)
    data.setdefault("rng_counters", {})

    data.setdefault("hunger", 0.0)
    data.setdefault("wounds", [])
    data.setdefault("active_effects", [])

    stats = data.get("stats")
    if isinstance(stats, dict):
        stats.setdefault("max_stamina", int(stats.get("stamina", 100) or 100))
        for attribute in ("grit", "agility", "wits", "presence"):
            stats.setdefault(attribute, 10)

    # v1 left this junk key behind on every state that ever rolled a die.
    flags = data.get("flags")
    if isinstance(flags, dict):
        flags.pop("_last_dice", None)

    data["save_version"] = 2
    return data


#: Spine migrations. v1 -> v2 is here rather than under ``clockwork-dark``
#: because everything it touches -- the derived world clock, the named RNG
#: streams, the survival fields -- belongs to GameState, not to one story. Any
#: v1 save of any story needs it.
ENGINE_MIGRATIONS: dict[int, Step] = {
    1: _v1_to_v2,
}

#: Kept as the historical name so importers do not break. It is the engine
#: chain: a story that wants a step of its own registers it below instead.
MIGRATIONS = ENGINE_MIGRATIONS

#: slug -> {version: step}. Populated by ``register_story_migration``, which a
#: story's own package calls at import. Empty today: neither shipped story has
#: needed a step of its own, and inventing one to demonstrate the mechanism
#: would be a migration that runs over real saves for no reason.
STORY_MIGRATIONS: dict[str, dict[int, Step]] = {}


class MigrationError(RuntimeError):
    """A save could not be brought forward to the current schema."""


def register_story_migration(slug: str, version: int, step: Step) -> None:
    """
    Register a step that runs only over one story's saves.

    Args:
        slug: Game slug, matching ``games/<slug>/``.
        version: The version this step migrates FROM.
        step: Callable taking and returning a save dict. It runs after the
            engine step for the same version, so the spine is already at v+1;
            it does NOT have to touch ``save_version``.

    Raises:
        MigrationError: A step is already registered for that slug and version.
            Silently replacing one would mean the chain a save travelled through
            depends on import order.
    """
    chain = STORY_MIGRATIONS.setdefault(str(slug), {})
    existing = chain.get(int(version))
    if existing is not None and existing is not step:
        raise MigrationError(
            f"A migration from version {version} is already registered for "
            f"story {slug!r}"
        )
    chain[int(version)] = step
    logger.info(
        "[persistence] Story migration registered "
        "(operation=register_story_migration, slug=%s, from=%s)",
        slug,
        version,
    )


def story_migrations(slug: Optional[str]) -> dict[int, Step]:
    """Steps registered for one story. Unknown or None slug means none."""
    if not slug:
        return {}
    return dict(STORY_MIGRATIONS.get(str(slug), {}))


def clear_story_migrations(slug: Optional[str] = None) -> None:
    """Drop registered story steps. Tests only -- registration is per process."""
    if slug is None:
        STORY_MIGRATIONS.clear()
    else:
        STORY_MIGRATIONS.pop(str(slug), None)


def migrate(data: dict[str, Any], *, slug: Optional[str] = None) -> dict[str, Any]:
    """
    Bring a save document up to CURRENT_SAVE_VERSION.

    Args:
        data: Raw save state dict.
        slug: Story the save belongs to. None runs the engine chain only, which
            is exactly what happened before namespacing existed and is the right
            answer for a save whose story cannot be determined -- the spine
            steps are safe for every story by construction.

    Returns:
        A new dict at the current version.

    Raises:
        MigrationError: If the save is newer than this build understands, or
            a required migration step is missing.
    """
    version = int(data.get("save_version", 1) or 1)

    if version > CURRENT_SAVE_VERSION:
        raise MigrationError(
            f"Save is version {version}; this build understands up to "
            f"{CURRENT_SAVE_VERSION}. Update the game to load it."
        )

    story_chain = story_migrations(slug)

    working = dict(data)
    while version < CURRENT_SAVE_VERSION:
        engine_step = ENGINE_MIGRATIONS.get(version)
        story_step = story_chain.get(version)
        if engine_step is None and story_step is None:
            raise MigrationError(
                f"No migration from save version {version} to {version + 1}"
            )

        # Spine first: a story step is entitled to assume the engine's fields
        # are already at v+1, and the reverse is never true.
        if engine_step is not None:
            working = engine_step(working)
        if story_step is not None:
            working = story_step(working)

        new_version = int(working.get("save_version", version + 1))
        if new_version <= version:
            raise MigrationError(
                f"Migration {version} -> {version + 1} did not advance the version"
            )
        logger.info(
            "[persistence] Migrated save (operation=migrate, slug=%s, from=%s, "
            "to=%s, story_step=%s)",
            slug or "-",
            version,
            new_version,
            story_step is not None,
        )
        version = new_version

    return working


__all__ = [
    "ENGINE_MIGRATIONS",
    "MIGRATIONS",
    "STORY_MIGRATIONS",
    "MigrationError",
    "clear_story_migrations",
    "migrate",
    "register_story_migration",
    "story_migrations",
]
