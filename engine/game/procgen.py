"""
Procgen — seeded village and margin for whichever story is running.

Two flagship answers used to be welded in here and both are gone:

    the entry location   ``location_id="forest_clearing"`` was a Python default,
                         so ``entry.location_id`` in every game.yaml was
                         validated, published over /api/games and consumed by
                         nothing. A new run in the second story began on a
                         location id its map does not contain.

    the template path    ``"data/procgen_templates/edgewood.yaml"`` was the
                         string-literal fallback for ``paths.procgen_templates``,
                         so a story whose config lost that key silently
                         generated Edgewood.

Both now come from the active manifest, with the flagship's answer as the last
resort so nothing changes for The Clockwork Dark.

Version: v0.2.0 [2026-08-08]
"""

from __future__ import annotations

import logging
import random
import secrets
from pathlib import Path
from typing import Any, Optional

import yaml

from engine.config import get_config
from engine.game.state import GameState, InventoryItem, ProcgenResult

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parents[2]
_TEMPLATE_CACHE: Optional[dict[str, Any]] = None

# Last-resort answers, used only when neither the config nor the active
# manifest has one. They are the flagship's, so a build with a damaged config
# degrades to the behaviour it had before this module learned about manifests
# -- but a story that DECLARES its own now wins, which it did not before.
_FALLBACK_TEMPLATES = "data/procgen_templates/edgewood.yaml"
_FALLBACK_LOCATION = "forest_clearing"


def _manifest_path(key: str) -> str:
    """
    A ``paths.*`` value straight off the active manifest, or "".

    Read without activating anything: asking where the templates live must not
    repoint config and clear a dozen caches as a side effect.
    """
    try:
        from engine.games.registry import entry_manifest

        manifest = entry_manifest()
    except Exception as exc:  # noqa: BLE001 -- procgen must not fail on lookup
        logger.debug("[procgen] No manifest available (operation=_manifest_path): %s", exc)
        return ""
    return str((manifest.paths.get(key) if manifest else "") or "")


def _templates_path() -> Path:
    rel = get_config().get("paths.procgen_templates", "") or _manifest_path(
        "procgen_templates"
    ) or _FALLBACK_TEMPLATES
    return _ROOT / rel


def load_templates() -> dict[str, Any]:
    """Load and cache Edgewood procgen templates."""
    global _TEMPLATE_CACHE
    if _TEMPLATE_CACHE is not None:
        return _TEMPLATE_CACHE

    path = _templates_path()
    if not path.exists():
        logger.warning(
            "[procgen] Templates missing (operation=load_templates, path=%s)", path
        )
        _TEMPLATE_CACHE = {}
        return _TEMPLATE_CACHE

    with path.open(encoding="utf-8") as fh:
        _TEMPLATE_CACHE = yaml.safe_load(fh) or {}
    return _TEMPLATE_CACHE


def _pick_unique(rng: random.Random, pool: list[Any], count: int) -> list[Any]:
    """Sample up to count unique items from pool."""
    if count <= 0 or not pool:
        return []
    count = min(count, len(pool))
    return rng.sample(pool, count)


def _build_procedural_npcs(
    rng: random.Random,
    templates: dict[str, Any],
    count: int,
) -> list[dict[str, Any]]:
    """Generate procedural villagers with deterministic ids."""
    given = templates.get("name_given", [])
    family = templates.get("name_family", [])
    roles = templates.get("villager_roles", ["villager"])
    traits = templates.get("trait_pool", [])

    if not given or not family:
        # The graceful-degradation path for a missing template used to walk
        # straight into rng.choice([]) -> IndexError.
        logger.warning(
            "[procgen] Name pools empty (operation=_build_procedural_npcs); "
            "skipping procedural villagers"
        )
        return []

    npcs: list[dict[str, Any]] = []
    used_names: set[str] = set()
    for idx in range(count):
        for attempt in range(20):
            name = f"{rng.choice(given)} {rng.choice(family)}"
            if name not in used_names:
                used_names.add(name)
                break
        else:
            # 20 consecutive collisions: fall back to a guaranteed-unique name
            # rather than silently emitting a duplicate, which the old loop did
            # because it had no else clause.
            name = f"{rng.choice(given)} {rng.choice(family)} the {idx + 1}"
            used_names.add(name)
        role = rng.choice(roles)
        npc_traits = _pick_unique(rng, traits, 2)
        npcs.append(
            {
                "id": f"npc_villager_{idx + 1}",
                "name": name,
                "role": role,
                "location_id": "edgewood_square",
                "traits": npc_traits,
                "canon": False,
            }
        )
    return npcs


def _build_procedural_buildings(
    rng: random.Random,
    templates: dict[str, Any],
    count: int,
) -> list[dict[str, Any]]:
    """Generate procedural village buildings."""
    types = templates.get("building_types", [])
    picked = _pick_unique(rng, types, count)
    buildings: list[dict[str, Any]] = []
    for idx, entry in enumerate(picked):
        prefix = str(entry.get("prefix", "")).strip()
        suffix = str(entry.get("suffix", "Building"))
        name = f"{prefix} {suffix}".strip() if prefix else suffix
        btype = str(entry.get("type", "civic"))
        buildings.append(
            {
                "id": f"building_proc_{idx + 1}",
                "name": name,
                "type": btype,
                "location_id": "edgewood_square",
                "canon": False,
            }
        )
    return buildings


def _build_forest(rng: random.Random, templates: dict[str, Any]) -> dict[str, Any]:
    """Generate forest margin features."""
    counts = templates.get("counts", {})
    resources = templates.get("forage_resources", ["mushroom"])
    barrow_names = templates.get("barrow_names", ["Hollow Hill"])

    forage_nodes = []
    for idx in range(int(counts.get("forage_nodes", 6))):
        forage_nodes.append(
            {
                "id": f"forage_{idx + 1}",
                "resource": rng.choice(resources),
                "dc": rng.randint(6, 14),
                "location_id": "forest_clearing",
            }
        )

    hidden_paths = []
    for idx in range(int(counts.get("hidden_paths", 2))):
        hidden_paths.append(
            {
                "id": f"hidden_path_{idx + 1}",
                "label": rng.choice(
                    ["deer track", "mossy shortcut", "root-choked gap", "dry creek bed"]
                ),
                "leads_to": rng.choice(["deeper_forest", "old_barrows", "herb_glen"]),
                "dc": rng.randint(10, 16),
            }
        )

    barrow = {
        "id": "barrow_dungeon",
        "name": rng.choice(barrow_names),
        "optional": True,
        "dc": rng.randint(12, 16),
        "location_id": "forest_clearing",
    }

    return {
        "forage_nodes": forage_nodes,
        "hidden_paths": hidden_paths,
        "barrow_dungeon": barrow,
    }


def _build_festival(rng: random.Random, templates: dict[str, Any]) -> dict[str, Any]:
    """Pick one seasonal festival."""
    names = templates.get("festival_names", ["Harvest Lantern"])
    seasons = templates.get("festival_seasons", ["autumn"])
    return {
        "name": rng.choice(names),
        "season": rng.choice(seasons),
        "day_offset": rng.randint(14, 56),
    }


def generate_world(seed: int) -> ProcgenResult:
    """
    Generate a full procgen snapshot for the given seed.

    Args:
        seed: Deterministic RNG seed.

    Returns:
        ProcgenResult with NPCs, buildings, forest, and festival data.
    """
    templates = load_templates()
    rng = random.Random(seed)
    counts = templates.get("counts", {})

    canon_npcs = [
        {**npc, "canon": True}
        for npc in templates.get("canon_npcs", [])
    ]
    proc_npc_count = int(counts.get("procedural_npcs", 3))
    procedural_npcs = _build_procedural_npcs(rng, templates, proc_npc_count)
    npcs = canon_npcs + procedural_npcs

    canon_buildings = [
        {**b, "canon": True}
        for b in templates.get("canon_buildings", [])
    ]
    # Vary the count so village size differs by seed too, not just contents.
    target_buildings = int(counts.get("buildings", 12)) + rng.randint(-2, 4)
    proc_building_count = max(0, target_buildings - len(canon_buildings))
    procedural_buildings = _build_procedural_buildings(
        rng,
        templates,
        proc_building_count,
    )
    buildings = canon_buildings + procedural_buildings

    murals = templates.get("mural_fragments", [])
    shrine_mural = rng.choice(murals) if murals else ""
    bakery_job_day = int(templates.get("bakery_job_day", 3))

    result = ProcgenResult(
        seed=seed,
        npcs=npcs,
        buildings=buildings,
        forest=_build_forest(rng, templates),
        festival=_build_festival(rng, templates),
        shrine_mural=shrine_mural,
        bakery_job_day=bakery_job_day,
    )

    logger.info(
        "[procgen] World generated (operation=generate_world, seed=%s, npcs=%s, buildings=%s)",
        seed,
        len(npcs),
        len(buildings),
    )
    return result


def npcs_at_location(procgen: ProcgenResult, location_id: str) -> list[dict[str, Any]]:
    """Return NPCs assigned to a location."""
    return [n for n in procgen.npcs if n.get("location_id") == location_id]


def npc_by_id(procgen: ProcgenResult, npc_id: str) -> Optional[dict[str, Any]]:
    """Lookup NPC by canonical id."""
    for npc in procgen.npcs:
        if npc.get("id") == npc_id:
            return npc
    return None


def populate_state(state: GameState, seed: Optional[int] = None) -> ProcgenResult:
    """
    Attach procgen data to an existing GameState.

    Args:
        state: Mutable game state.
        seed: Optional seed; random if omitted.

    Returns:
        Generated ProcgenResult attached to state.
    """
    effective_seed = seed if seed is not None else secrets.randbelow(2**31 - 1)
    procgen = generate_world(effective_seed)
    state.procgen = procgen
    # Seed every runtime RNG stream from the same number that built the world.
    # Without this, rng_seed stayed at its 0 default, so schedules, dice and
    # encounters drew an identical sequence in every session ever played --
    # regardless of the seed the player chose.
    state.rng_seed = effective_seed
    return procgen


def entry_location_id() -> str:
    """
    Where a new run starts, taken from the active story's manifest.

    Falls back to the flagship's ``forest_clearing`` when no manifest is
    readable, which is the value this module hardcoded before.
    """
    try:
        from engine.games.registry import entry_location

        return entry_location(_FALLBACK_LOCATION)
    except Exception as exc:  # noqa: BLE001 -- never block a new game on this
        logger.debug(
            "[procgen] Manifest entry unavailable (operation=entry_location_id): %s", exc
        )
        return _FALLBACK_LOCATION


def new_game_state(
    *,
    player_name: str = "Traveler",
    archetype: Optional[str] = None,
    seed: Optional[int] = None,
    location_id: Optional[str] = None,
) -> GameState:
    """
    Create a new session with procgen-populated world.

    Args:
        player_name: Player display name.
        archetype: Starting archetype id. None means "ask the active manifest",
            which may legitimately answer "this story has none" -- the old
            ``"wayfarer"`` default was the third and last place the flagship's
            answer was hardcoded into the new-game path.
        seed: Optional deterministic seed.
        location_id: Starting location. None means "ask the active manifest",
            which is now the only correct answer -- the old ``forest_clearing``
            default started every story in Edgewood.

    Returns:
        Fresh GameState ready for play.
    """
    from engine.session import default_archetype

    chosen = default_archetype() if archetype is None else archetype
    state = GameState(
        player_name=player_name,
        archetype=chosen,
        location_id=location_id or entry_location_id(),
    )
    apply_archetype(state, chosen)
    populate_state(state, seed=seed)
    return state


def apply_archetype(state: GameState, archetype: str) -> dict[str, Any]:
    """
    Stamp an archetype's stats and starting kit onto a fresh character.

    Until this ran, ``archetype`` was generated, serialized and read by nothing
    but a display line in the prompt -- every character in the game was
    mechanically identical, and the start screen was a cosmetic choice.

    Args:
        state: Fresh game state.
        archetype: Archetype id; unknown ids fall back to the configured default.

    Returns:
        The archetype entry that was applied.
    """
    from engine.game.checks import load_archetypes

    # No archetype is a legitimate answer, not a missing one.
    #
    # A story where the player is simply a person who walked in declares
    # `archetypes: []`, and creation offers a name rather than a build. Falling
    # back here would stamp that run with another story's noun -- and it did:
    # the manifest and the session store both honoured the empty list, and this
    # function quietly reinstated "wayfarer" at the end of the chain. A default
    # with three homes only has to be missed in one of them.
    if not archetype:
        return {}

    spec = load_archetypes()
    entries = spec.get("archetypes", {}) or {}
    entry = entries.get(archetype)
    if entry is None:
        fallback = str(spec.get("default", "wayfarer"))
        entry = entries.get(fallback, {})
        if entry:
            logger.info(
                "[procgen] Unknown archetype, using default "
                "(operation=apply_archetype, wanted=%s, used=%s)",
                archetype,
                fallback,
            )
            state.archetype = fallback

    for stat, value in (entry.get("stats") or {}).items():
        if hasattr(state.stats, stat):
            setattr(state.stats, stat, int(value))

    if "start_gold" in entry:
        state.stats.gold = int(entry["start_gold"])

    for raw in entry.get("starting_items") or []:
        if not isinstance(raw, dict) or not raw.get("id"):
            continue
        state.inventory.append(
            InventoryItem(
                id=str(raw["id"]),
                name=str(raw.get("name", raw["id"])),
                qty=int(raw.get("qty", 1)),
                tags=list(raw.get("tags", [])),
            )
        )

    return entry