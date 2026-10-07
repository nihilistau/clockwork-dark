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
      engine.mcp.scene_rules_engine _rules_instance (reset_rules_engine since v0.20.0)

    found missing, wired here
      engine.world.schedules        _RUMOR_CACHE
      engine.world.npc_sim          _SCHEDULE_CACHE
      engine.game.quests            _ARC_CACHE, _QUEST_CACHE
      engine.game.reputation        _FACTION_CACHE
      engine.game.locations         LOCATIONS (populated at import time)
      engine.skills.builtin.assistant  HINTS_BY_TIER, LORE_SNIPPETS
      engine.media.art              load_subjects (lru_cache)
      engine.media.providers.shipped   load_manifest, art_root (lru_cache)
      engine.persistence.saves      _stores (each root embeds the game slug)
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

WARMING IS THE OTHER DIRECTION (v0.20.0). ``WARMERS`` names the loader that
builds each cache, and ``warm_all_caches()`` calls them all, importing as it
goes, so a process serving many sessions on threads has nothing left to build
lazily (spec §5.2). ``tests/test_cache_warming.py`` checks it calls every one
and leaves every ``warmed`` row of ``tests/fixtures/module_state.yaml`` built.

Version: v0.2.0 [2026-10-01]
"""

from __future__ import annotations

import importlib
import logging
import sys
import threading
from types import ModuleType
from typing import Any, Optional

from engine.locks import renew_after_fork

logger = logging.getLogger(__name__)

#: Held by ``warm_all_caches`` while its loaders run: first in the engine's
#: lock order (engine/locks.py), so a loader may take any lock after it.
_warm_lock = threading.Lock()
renew_after_fork(globals(), _warm_lock=threading.Lock)

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
    # Parsed premises directory: types, anchors, pools. Kept warm across a swap
    # it would lay one city's houses into another's districts.
    ("engine.world.premises", "_SPEC_CACHE"),
    # Parsed thievery file: alertness bands, purses, hot_days. A swap that kept
    # it warm would rob one city's stewards with another's purses.
    ("engine.world.thievery", "_SPEC_CACHE"),
    # Parsed law file: jurisdictions, deeds, bands, guises. A swap that kept it
    # warm would police one city with another's watch.
    ("engine.world.law", "_SPEC_CACHE"),
    # Warn-once memory for an arrest scene the story's encounters lack; per story.
    ("engine.world.law", "_WARNED_ENCOUNTERS"),
    # Parsed jobs file: stages, bands, features, tools, flashbacks, anchors. A
    # swap that kept it warm would burgle one city's houses by another's rules.
    ("engine.world.jobs", "_SPEC_CACHE"),
    # Warn-once memory for an arrest scene a raised alarm cannot open; per story.
    ("engine.world.jobs", "_WARNED_ARREST"),
    # Parsed agendas file: roles, owners, clocks, moves, reactions. A swap that
    # kept it warm would set one city's thief loose in another's streets.
    ("engine.world.agendas", "_SPEC_CACHE"),
    # Parsed clues file: the role, the evidence meter, every clue's row. A swap
    # that kept it warm would lay one city's trail through another's houses.
    ("engine.world.clues", "_SPEC_CACHE"),
    # Warn-once memory for a story's missing death rules; per story.
    ("engine.game.encounter", "_WARNED_DEATH"),
    ("engine.media.comfyui", "_TEMPLATE_CACHE"),
    ("engine.game.quests", "_ARC_CACHE"),
    ("engine.game.quests", "_QUEST_CACHE"),
    ("engine.game.reputation", "_FACTION_CACHE"),
    # Parsed recipes, keyed on the recipe directory and its files' mtimes, so
    # already self-invalidating; nulled so a swap and each test start cold.
    ("engine.skills.builtin.mechanics", "_RECIPE_CACHE"),
    # Warn-once memory for forced scenes nothing can answer; per story.
    ("engine.content.director", "_WARNED_FORCED"),
    # One save store per (owner, slug); each root embeds the storage root and
    # the game slug (v0.20.0: was the single `_store`).
    ("engine.persistence.saves", "_stores"),
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
    # v0.20.0 (the module-state inventory, spec §5.2): the rest of the
    # per-story lru_cache loaders, mtime-keyed like the entries above --
    # collections, the quest-lock and recipe-reference scans, the epilogue
    # cards and index, and the story's spoiler table.
    ("engine.game.inventory", "_read_collections"),
    ("engine.game.inventory", "_read_quest_locks"),
    ("engine.game.inventory", "_read_recipe_refs"),
    ("engine.game.epilogue", "_read"),
    ("engine.lore.interceptors", "_compile_terms"),
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
    # The rules engine singleton, dropped under its own lock (v0.20.0 T6 fix
    # round 2; it was a NULLED_ATTRIBUTES row, nulled with no lock).
    ("engine.mcp.scene_rules_engine", "reset_rules_engine"),
    ("engine.skills.builtin.assistant", "reload_hints"),
    # LM Studio: resolved model ids, transport capability probes and lane
    # semaphores are all derived from config. A game swap can rebind profiles,
    # so a stale backend would keep talking to the previous game's model policy.
    ("engine.llm.profiles", "reset_profiles"),
    ("engine.llm.registry", "reset_registry"),
    # The compat client reads its base URL, key and timeout once, when built.
    # Kept across a reload it went on dialling the previous server with the
    # previous key; before the backend, which is rebuilt around a fresh one.
    # Released, not closed: a turn may still be streaming through the old one.
    ("engine.llm.client", "release_lms_client"),
    # Ollama's /api/chat client, for the same reason and in the same way.
    ("engine.llm.ollama", "release_ollama_client"),
    ("engine.llm.backend", "reset_backend"),
    ("engine.llm.gate", "reset_lanes"),
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


# (module, attribute) pairs called with no arguments to BUILD a cache: the
# loader for every entry above that holds per-story content (v0.20.0, spec
# §5.2's "warmed, then read-only"). ``warm_all_caches`` calls each once, in
# this order, under ``_warm_lock``, before hosted mode serves a request -- so
# no two first readers race to build one, and no reader sees a container
# another thread is still filling. Nothing resets them while serving: every
# path that would is refused in hosted mode. The grammar is first: loaded
# here, the first turn's condition never takes the grammar lock.
#
# Not here, on purpose: the warn-once flags (``_WARNED_*``), which are not
# caches; the save stores (one per owner, built on first use under their own
# lock); and the model server's objects (profiles, registry, client, backend,
# lanes) and the Oracle, which hosted mode's startup builds itself (spec §5.2)
# because building them can reach the model server.
#
# A WARMER MUST NOT take the backend's, the LLM registry's, the profiles' or
# the lanes' locks: they belong to the model server's objects above, not to a
# story's content. Any other lock is allowed -- ``_warm_lock`` is first in the
# engine's lock order (engine/locks.py) -- and the order checker in
# tests/test_thread_safety.py runs warming to hold every warmer to it.
#
# A cache with no zero-argument public loader is warmed by a small function
# in this module (``_warm_*``), named here like any other.
WARMERS: tuple[tuple[str, str], ...] = (
    ("engine.game.quests", "_ensure_grammar"),
    ("engine.state.active", "active_schema"),
    ("engine.state.active", "active_roster"),
    ("engine.games.caches", "_warm_story_tables"),
    ("engine.game.procgen", "load_templates"),
    ("engine.game.evil_ticker", "doom_enabled"),
    ("engine.world.schedules", "load_schedules"),
    ("engine.world.schedules", "load_rumors"),
    ("engine.world.npc_sim", "load_npc_schedules"),
    ("engine.world.premises", "_load"),
    ("engine.world.thievery", "load_spec"),
    ("engine.world.law", "load_spec"),
    ("engine.world.jobs", "spec"),
    ("engine.world.agendas", "spec"),
    ("engine.world.clues", "spec"),
    ("engine.media.comfyui", "load_comfyui_templates"),
    ("engine.mcp.scene_rules_engine", "get_rules_engine"),
    ("engine.game.quests", "load_arcs"),
    ("engine.game.quests", "load_quests"),
    ("engine.game.reputation", "load_factions"),
    ("engine.skills.builtin.mechanics", "_load_recipes"),
    ("engine.media.art", "load_subjects"),
    ("engine.media.providers.shipped", "load_manifest"),
    ("engine.media.providers.shipped", "art_root"),
    ("engine.game.checks", "load_skill_rules"),
    ("engine.game.checks", "load_archetypes"),
    ("engine.game.survival", "load_rules"),
    ("engine.game.encounter", "load_encounters"),
    ("engine.game.encounter", "load_death_rules"),
    ("engine.game.inventory", "load_items"),
    ("engine.game.inventory", "load_collections"),
    ("engine.game.inventory", "quest_locks"),
    ("engine.game.inventory", "recipe_refs"),
    ("engine.game.foraging", "load_rules"),
    ("engine.game.economy", "load_rules"),
    ("engine.game.trade", "load_rules"),
    ("engine.game.trade", "load_economy"),
    ("engine.game.clocks", "load_clocks"),
    ("engine.game.threads", "load_rules"),
    ("engine.game.endings", "load_rules"),
    ("engine.games.caches", "_warm_decks"),
    ("engine.challenges.spec", "load_bounds"),
    ("engine.agents.prompts", "storyteller_persona"),
    ("engine.agents.prompts", "storyteller_examples"),
    ("engine.agents.prompts", "assistant_persona"),
    ("engine.game.epilogue", "load_index"),
    ("engine.game.epilogue", "load_cards"),
    ("engine.lore.interceptors", "spoiler_terms"),
    ("engine.world.world_effects", "load_doom_effects"),
    ("engine.challenges.set_pieces", "load_set_pieces"),
    ("engine.agents.governance", "get_governance"),
)


def _warm_story_tables() -> None:
    """
    The tables a module fills as it imports and a reset reloads IN PLACE
    (``locations.LOCATIONS`` and its id sets, the assistant's hints): warm
    once imported, so warming them is importing them.
    """
    importlib.import_module("engine.game.locations")
    importlib.import_module("engine.skills.builtin.assistant")


def _warm_decks() -> None:
    """Every deck the running story ships (``deck._read_deck``, one per file)."""
    from engine.content import deck

    for deck_id in deck.deck_ids():
        deck.load_deck(deck_id)


def warm_all_caches() -> list[str]:
    """
    Build every per-story cache once, before hosted mode serves (spec §5.2).

    Each ``WARMERS`` entry is imported and called, in order, under
    ``_warm_lock`` (the OUTERMOST lock in engine/locks.py, so a loader may
    take any other), after the config is built and the running story's
    manifest paths are read (``story_paths``, whose first read for a slug
    takes the config lock). Not under the config lock: that one is innermost,
    and loaders take locks after it. UNLIKE ``reset_all_caches`` this
    imports: its point is to leave nothing to be built lazily by the first two
    players at once. A loader that raises is not stepped over -- a story whose
    content does not load should not start serving.

    Returns:
        ``"module.attr"`` for each loader called, in order.
    """
    from engine.config import get_config, story_paths

    called: list[str] = []
    with _warm_lock:
        get_config()
        story_paths()
        for module_name, attr in WARMERS:
            module = importlib.import_module(module_name)
            getattr(module, attr)()
            called.append(f"{module_name}.{attr}")
    logger.info("[games] Content caches warmed (operation=warm_all_caches, loaders=%d)", len(called))
    return called


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
    "WARMERS",
    "registered_caches",
    "reset_all_caches",
    "warm_all_caches",
]
