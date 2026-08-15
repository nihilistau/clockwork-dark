"""
Content Cache Registry
======================

Every module-level cache built from a config path, in one list.

WHY THIS EXISTS: config resolution is lazy and memoized all over the engine.
Roughly a dozen modules read a ``paths.*`` key once and hold the parsed YAML
for the life of the process -- which is correct for a single-story build and
catastrophic for a multi-game one. Swap the manifest without invalidating them
and the new game serves the old game's location graph, quests, factions,
rumours, art manifest and hint corpus. The failure is silent: content loads,
the turn runs, and the player is in the wrong story.

``engine/config.py::reset_config`` already walked a registry like this, but it
listed four entries and the engine has grown well past four. The audit behind
this file is:

    already registered
      engine.game.procgen           _TEMPLATE_CACHE
      engine.world.schedules        _SCHEDULE_CACHE
      engine.media.comfyui          _TEMPLATE_CACHE
      engine.mcp.scene_rules_engine _rules_instance

    found missing, wired here
      engine.world.schedules        _RUMOR_CACHE
      engine.world.npc_sim          _SCHEDULE_CACHE
      engine.game.quests            _ARC_CACHE, _QUEST_CACHE
      engine.game.reputation        _FACTION_CACHE
      engine.game.locations         LOCATIONS (populated at import time)
      engine.skills.builtin.assistant  HINTS_BY_TIER, LORE_SNIPPETS
      engine.media.art              load_subjects (lru_cache)
      engine.media.providers.shipped   load_manifest, art_root (lru_cache)
      engine.persistence.saves      _store (its root embeds the game slug)
      engine.lore.manager           _manager (its db path is a config path)

    self-invalidating, cleared anyway for determinism
      engine.game.checks            _read_yaml
      engine.game.survival          _read_rules
      engine.game.encounter         _read_dir, _read_death

    stale re-export, refreshed here
      engine.mcp.scene_rules_engine.LOCATION_IDS

The last one is the subtle case. ``engine/game/locations.py`` mutates its
``LOCATIONS`` dict in place on reload precisely so ``from ... import LOCATIONS``
keeps working, but ``LOCATION_IDS`` is a frozenset and is *rebound*, so the
copy ``scene_rules_engine`` grabbed at import time would keep validating travel
against the previous game's map. Rebinding it here is why R001/R002 do not
reject every legal move in a newly activated game.

NOTHING IS IMPORTED TO RESET IT. A module absent from ``sys.modules`` has no
cache to invalidate, and force-importing the whole content tree on every
``reset_config()`` would make the test suite pay for a dozen YAML parses it
never asked for.

Version: v0.1.1 [2026-08-09]
"""

from __future__ import annotations

import logging
import sys
from types import ModuleType
from typing import Any, Optional

logger = logging.getLogger(__name__)

# (module, attribute) pairs set back to None.
#
# These are all ``Optional[...]`` guarded by ``is not None``, so None is the
# only correct reset value -- clearing a dict in place would leave an
# empty-but-populated cache that never reloads.
NULLED_ATTRIBUTES: tuple[tuple[str, str], ...] = (
    ("engine.game.procgen", "_TEMPLATE_CACHE"),
    # Whether the active story declares a doom clock at all. Asked on every
    # prompt build; a swap that kept it warm would narrate one story's
    # apocalypse into another, which is the exact bug the flag exists to end.
    ("engine.game.evil_ticker", "_DOOM_DECLARED"),
    ("engine.world.schedules", "_SCHEDULE_CACHE"),
    ("engine.world.schedules", "_RUMOR_CACHE"),
    ("engine.world.npc_sim", "_SCHEDULE_CACHE"),
    ("engine.media.comfyui", "_TEMPLATE_CACHE"),
    ("engine.mcp.scene_rules_engine", "_rules_instance"),
    ("engine.game.quests", "_ARC_CACHE"),
    ("engine.game.quests", "_QUEST_CACHE"),
    ("engine.game.reputation", "_FACTION_CACHE"),
    ("engine.persistence.saves", "_store"),
)

# (module, attribute) pairs whose attribute is an ``lru_cache``-wrapped
# function; ``.cache_clear()`` is called on it.
#
# The checks/survival/encounter entries are keyed on (path, mtime) and so
# already invalidate themselves on a repointed path. They are listed anyway:
# an activation that leaves *some* caches warm is an activation whose
# behaviour depends on what ran before it, and that is not a property worth
# defending in a test.
LRU_CACHES: tuple[tuple[str, str], ...] = (
    ("engine.media.art", "load_subjects"),
    ("engine.media.providers.shipped", "load_manifest"),
    # The directory that manifest's paths resolve against. Read on every
    # lookup alongside load_manifest, so the two must be cleared together --
    # otherwise a game swap checks the new story's filenames inside the old
    # story's directory, misses every one, and the art silently vanishes.
    ("engine.media.providers.shipped", "art_root"),
    ("engine.game.checks", "_read_yaml"),
    ("engine.game.survival", "_read_rules"),
    ("engine.game.encounter", "_read_dir"),
    ("engine.game.encounter", "_read_death"),
    # Livelihood: items, forage nodes, wages and vendor stock all come from
    # per-game YAML. Mtime-keyed like the entries above and so self-healing,
    # listed for the same reason -- an activation that leaves some caches warm
    # behaves differently depending on what ran before it.
    ("engine.game.inventory", "_read_items"),
    ("engine.game.foraging", "_read_rules"),
    ("engine.game.economy", "_read_rules"),
    ("engine.game.trade", "_read_rules"),
    ("engine.game.trade", "_read_economy"),
    # Structural systems: progress clocks, contract threads, ending gates,
    # scene decks and the challenge bounds derived from a story's meters.
    # Mtime-keyed and self-healing like the entries above, listed for the same
    # reason this file states in its own docstring -- an activation that leaves
    # some caches warm behaves differently depending on what ran before it.
    ("engine.game.clocks", "_read_table"),
    ("engine.game.threads", "_read_table"),
    ("engine.game.endings", "_read_table"),
    ("engine.content.deck", "_read_deck"),
    ("engine.challenges.spec", "_read_bounds"),
    # The words the model actually reads: storyteller.md, examples.json and
    # assistant.md from the active story's prompt directory. Mtime-keyed and
    # so self-healing, listed for the same reason as the entries above.
    ("engine.agents.prompts", "_read_prompt"),
)

# (module, attribute) pairs called with no arguments to rebuild in place.
#
# Order matters: locations must reload before anything that re-exports from it
# (see RE_EXPORTS below).
RELOADERS: tuple[tuple[str, str], ...] = (
    ("engine.game.locations", "reload_locations"),
    ("engine.skills.builtin.assistant", "reload_hints"),
    # LM Studio: resolved model ids, transport capability probes and lane
    # semaphores are all derived from config. A game swap can rebind profiles,
    # so a stale backend would keep talking to the previous game's model policy.
    ("engine.lmstudio.profiles", "reset_profiles"),
    ("engine.lmstudio.registry", "reset_registry"),
    ("engine.lmstudio.backend", "reset_backend"),
    ("engine.lmstudio.gate", "reset_lanes"),
    # Governance: the PRE chain is built from `comms.interceptors` and the
    # doom/set-piece tables from `paths.*`, so all four are config-derived and
    # a swap that kept them would run the previous game's rules and doom beats.
    # Telemetry is reset too -- metrics from one story must not be attributed
    # to another.
    ("engine.world.world_effects", "reset_doom_effects_cache"),
    ("engine.challenges.set_pieces", "reset_set_piece_cache"),
    ("engine.agents.governance", "reset_governance"),
    # Which stories have already been warned about shipping no storyteller.md.
    # Suppressed per slug for the life of the process, so a swap back to a
    # story must be able to say it again -- an author who fixes a manifest and
    # reactivates deserves to see whether it took.
    ("engine.agents.prompts", "reset_prompt_warnings"),
    ("engine.telemetry.oracle", "reset_oracle"),
    # The story's state declaration -- which meters exist, what they are bounded
    # by, who may write them and what the player may see. Swapping stories
    # without clearing this would serve the previous story's schema, and the
    # failure mode is the worst kind: reads succeed and return the wrong story's
    # defaults.
    ("engine.state.active", "reset_schema"),
)

# (consumer module, consumer attribute, source module, source attribute).
#
# Immutable values pulled in by ``from x import y`` at import time, which a
# reload of the source module rebinds rather than mutates.
RE_EXPORTS: tuple[tuple[str, str, str, str], ...] = (
    (
        "engine.mcp.scene_rules_engine",
        "LOCATION_IDS",
        "engine.game.locations",
        "LOCATION_IDS",
    ),
)


def _loaded(module_name: str) -> Optional[ModuleType]:
    """Return an already-imported module, or None. Never imports."""
    return sys.modules.get(module_name)


def _reset_lore_manager() -> None:
    """
    Close and drop the lore singleton so the next call reopens the new DB.

    ``engine.lore.manager.reset_lore_manager`` is not used: it eagerly
    constructs a replacement, which would open (and create) a SQLite file on
    every single ``reset_config()``. Dropping to None keeps the rebuild lazy.
    """
    module = _loaded("engine.lore.manager")
    if module is None:
        return
    manager = getattr(module, "_manager", None)
    if manager is None:
        return
    try:
        manager.close()
    except Exception as exc:  # noqa: BLE001 -- a stuck DB must not block a swap
        logger.warning(
            "[games] Lore manager would not close (operation=_reset_lore_manager): %s",
            exc,
        )
    module._manager = None


def reset_all_caches() -> None:
    """
    Invalidate every content cache derived from config.

    Safe to call at any time and on any number of consecutive calls; a module
    that has not been imported is skipped rather than imported. Individual
    failures are logged and stepped over, because a half-reset cache is still
    better than an exception thrown out of a config reload mid-turn.
    """
    cleared = 0

    for module_name, attr in NULLED_ATTRIBUTES:
        module = _loaded(module_name)
        if module is not None and hasattr(module, attr):
            setattr(module, attr, None)
            cleared += 1

    for module_name, attr in LRU_CACHES:
        module = _loaded(module_name)
        func = getattr(module, attr, None) if module is not None else None
        clear = getattr(func, "cache_clear", None)
        if callable(clear):
            clear()
            cleared += 1

    for module_name, attr in RELOADERS:
        module = _loaded(module_name)
        func = getattr(module, attr, None) if module is not None else None
        if not callable(func):
            continue
        try:
            func()
            cleared += 1
        except Exception as exc:  # noqa: BLE001 -- one bad file, not a crash
            logger.warning(
                "[games] Reloader failed (operation=reset_all_caches, "
                "module=%s, attr=%s): %s",
                module_name,
                attr,
                exc,
            )

    for dst_module_name, dst_attr, src_module_name, src_attr in RE_EXPORTS:
        dst = _loaded(dst_module_name)
        src = _loaded(src_module_name)
        if dst is None or src is None or not hasattr(src, src_attr):
            continue
        setattr(dst, dst_attr, getattr(src, src_attr))
        cleared += 1

    _reset_lore_manager()

    logger.info("[games] Content caches invalidated (operation=reset_all_caches, entries=%d)", cleared)


def registered_caches() -> list[str]:
    """
    Human-readable list of everything the registry knows how to invalidate.

    Used by ``scripts/doctor.py`` so "what does activating a game clear?" is a
    question with an answer that does not require reading this file.
    """
    rows = [f"{m}.{a}" for m, a in NULLED_ATTRIBUTES]
    rows += [f"{m}.{a}()" for m, a in LRU_CACHES]
    rows += [f"{m}.{a}()" for m, a in RELOADERS]
    rows += [f"{d}.{da} <- {s}.{sa}" for d, da, s, sa in RE_EXPORTS]
    rows.append("engine.lore.manager._manager")
    return sorted(rows)


__all__ = [
    "LRU_CACHES",
    "NULLED_ATTRIBUTES",
    "RELOADERS",
    "RE_EXPORTS",
    "registered_caches",
    "reset_all_caches",
]
