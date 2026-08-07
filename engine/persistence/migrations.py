"""
Save Migrations
===============

Forward-only schema evolution for save files.

DESIGN.md Key Decision #11 said "JSON save v1, no migration". That was already
untrue by the time saves existed: the overhaul changes the state schema several
times over. Retrofitting a migration chain after three breaking changes costs
far more than carrying one from the start.

Rules:
  - Migrations run IN MEMORY on load. Nothing is rewritten on disk until the
    next ordinary save, so a failed load never destroys the original.
  - Each step is v -> v+1 and must be total: given any valid v document it
    produces a valid v+1 document without raising.
  - Never delete a migration. Old saves are the reason this file exists.

Version: v0.2.0 [2026-08-07]
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from engine.game.state import CURRENT_SAVE_VERSION

logger = logging.getLogger(__name__)


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


MIGRATIONS: dict[int, Callable[[dict[str, Any]], dict[str, Any]]] = {
    1: _v1_to_v2,
}


class MigrationError(RuntimeError):
    """A save could not be brought forward to the current schema."""


def migrate(data: dict[str, Any]) -> dict[str, Any]:
    """
    Bring a save document up to CURRENT_SAVE_VERSION.

    Args:
        data: Raw save state dict.

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

    working = dict(data)
    while version < CURRENT_SAVE_VERSION:
        step = MIGRATIONS.get(version)
        if step is None:
            raise MigrationError(
                f"No migration from save version {version} to {version + 1}"
            )
        working = step(working)
        new_version = int(working.get("save_version", version + 1))
        if new_version <= version:
            raise MigrationError(
                f"Migration {version} -> {version + 1} did not advance the version"
            )
        logger.info(
            "[persistence] Migrated save (operation=migrate, from=%s, to=%s)",
            version,
            new_version,
        )
        version = new_version

    return working
