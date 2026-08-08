"""
Item Registry and Inventory
===========================

The engine-side reader of ``data/items/*.yaml``, and the helpers that treat a
carried thing as a thing rather than as a string.

THE GAP THIS MODULE CLOSES: ``data/items/*.yaml`` has been the declared source
of truth for every item id in the game since P9 -- name, description, tags,
weight and a base ``value`` in copper -- and the only code that had ever read
it lived in ``scripts/validate_content.py``. At runtime nothing knew what an
item was worth. ``engine/skills/builtin/mechanics.py::trade`` priced off
``data/economy.yaml`` alone, so an item a vendor had no ``buys`` row for was
worth exactly nothing no matter what the registry said, and selling -- the
common case -- silently refused. Prices could not respond to reputation,
scarcity or the evil phase because the number they would have responded to was
never loaded.

WHY A REGISTRY RATHER THAN A DICT ON GameState: items are content, not state.
A save records that you carry three of ``wild_mushroom``; what a wild mushroom
weighs and is worth is the game's business and must be repointable by a game
manifest (``paths.items``) without touching a single save file.

Unknown ids are NOT an error. Quests, procgen and the boon tables can all mint
an inventory entry, and a registry miss must degrade to "an ordinary object of
no particular worth" rather than abort a turn. ``value_of`` returns 0 and
``describe`` echoes the id; both log once at debug, never at error.

WHAT AN ITEM CAN DO (v0.2.0). An audit of the 81 declared items found 32 whose
only reachable verb was "sell it": a poultice bandage that closed no wound, a
fever draught that did nothing to a fever, four light sources that were never
lit, five pieces of apparel that were never worn, and three items -- goat_bell,
mural_pigment, tinker_map -- that nothing in the game could grant, consume or
ask for. Three optional registry blocks now close that:

    use:         a verb. Costs hours, may consume the item and other items with
                 it, and applies declared effects through effects.apply_effect.
    equip:       a slot and its bonuses. Held as a TimedEffect, so a worn cloak
                 appears in the check receipt by name (see effects.py).
    collection:  membership in a set from data/tables/collections.yaml, which
                 pays out once when the set is complete.

All three are DATA. This module reads and validates them; it never decides what
a thing is worth doing.

Version: v0.2.0 [2026-08-08]
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Optional

import yaml

from engine.config import get_config
from engine.game import effects as effects_module
from engine.game.state import GameState, InventoryItem

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parents[2]

#: Wearable slots, in the order the UI and the receipts list them. One item per
#: slot; `charm` is single as well, which is the whole reason ward pins are
#: sold nine to a card and worn as one card.
EQUIP_SLOTS = (
    "head",
    "body",
    "feet",
    "hands",
    "belt",
    "offhand",
    "light",
    "back",
    "charm",
)

#: Base carry allowance in kilograms before anything is worn. Reported, not
#: enforced: see ``carry_limit``.
BASE_CARRY_KG = 25.0


def _items_dir() -> Path:
    rel = get_config().get("paths.items", "data/items")
    return _ROOT / str(rel)


def _fingerprint(directory: Path) -> tuple[Any, ...]:
    """
    Names and mtimes of every item file.

    Keyed on this rather than on the directory path alone so the cache
    invalidates on a content edit AND on a repointed ``paths.items``. This
    module is deliberately not registered in engine/games/caches.py, which it
    does not own -- an mtime key means it does not have to be.
    """
    if not directory.is_dir():
        return ()
    out: list[Any] = []
    for path in sorted(directory.glob("*.yaml")):
        try:
            out.append((path.name, path.stat().st_mtime))
        except OSError:
            out.append((path.name, 0.0))
    return tuple(out)


@lru_cache(maxsize=8)
def _read_items(dir_str: str, _fp: tuple[Any, ...]) -> dict[str, dict[str, Any]]:
    """Merge every ``*.yaml`` under the items directory into one id->row map."""
    registry: dict[str, dict[str, Any]] = {}
    directory = Path(dir_str)
    if not directory.is_dir():
        logger.warning(
            "[inventory] Items directory missing (operation=_read_items, path=%s)",
            dir_str,
        )
        return registry

    for path in sorted(directory.glob("*.yaml")):
        try:
            with path.open(encoding="utf-8") as fh:
                data = yaml.safe_load(fh) or {}
        except (OSError, yaml.YAMLError) as exc:
            # One malformed category file costs that category, not the game.
            logger.warning(
                "[inventory] Unreadable item file (operation=_read_items, path=%s): %s",
                path.name,
                exc,
            )
            continue
        for row in data.get("items") or []:
            if not isinstance(row, dict):
                continue
            item_id = str(row.get("id") or "").strip()
            if item_id and item_id not in registry:
                registry[item_id] = dict(row)
    return registry


def load_items() -> dict[str, dict[str, Any]]:
    """Every declared item, keyed by id."""
    directory = _items_dir()
    return _read_items(str(directory), _fingerprint(directory))


def reset_item_cache() -> None:
    """Drop the parsed registry. Tests and hot reload only."""
    _read_items.cache_clear()


def get_item(item_id: str) -> Optional[dict[str, Any]]:
    """Registry row for an id, or None when the id is not declared."""
    return load_items().get(str(item_id))


def name_of(item_id: str) -> str:
    """Display name, falling back to a de-underscored id."""
    row = get_item(item_id)
    if row and str(row.get("name") or "").strip():
        return str(row["name"])
    return str(item_id).replace("_", " ")


def value_of(item_id: str) -> int:
    """
    Base worth in copper, before any multiplier.

    Zero for an unknown id and for quest items the registry deliberately values
    at 0 -- a thing nobody will buy is worth nothing, and that is a design
    statement in the data rather than a special case here.
    """
    row = get_item(item_id)
    if row is None:
        logger.debug("[inventory] Unknown item valued at zero (id=%s)", item_id)
        return 0
    try:
        return max(0, int(row.get("value", 0) or 0))
    except (TypeError, ValueError):
        return 0


def tags_of(item_id: str, carried: Optional[Iterable[str]] = None) -> list[str]:
    """
    Tags for an item, merging the registry row with any carried override.

    Quest and boon effects mint inventory entries with their own tag lists;
    those are honoured on top of the registry rather than replaced by it, so a
    ``forage``-tagged mushroom stays edible under the survival rules whether it
    was picked or granted.
    """
    row = get_item(item_id) or {}
    merged = [str(t) for t in (row.get("tags") or [])]
    for tag in carried or []:
        if str(tag) not in merged:
            merged.append(str(tag))
    return merged


def has_tag(item_id: str, tag: str, carried: Optional[Iterable[str]] = None) -> bool:
    """True when an item carries the given tag."""
    return str(tag) in tags_of(item_id, carried)


# ---------------------------------------------------------------------------
# item verbs: use, equip, collect
# ---------------------------------------------------------------------------


def use_spec(item_id: str) -> Optional[dict[str, Any]]:
    """The ``use:`` block for an item, or None when it has no verb."""
    block = (get_item(item_id) or {}).get("use")
    return dict(block) if isinstance(block, dict) else None


def equip_spec(item_id: str) -> Optional[dict[str, Any]]:
    """
    The ``equip:`` block for an item, or None when it cannot be worn.

    A block naming a slot outside ``EQUIP_SLOTS`` is dropped with a warning
    rather than honoured: an unknown slot is a content typo that would silently
    create a private slot nothing can ever displace.
    """
    block = (get_item(item_id) or {}).get("equip")
    if not isinstance(block, dict):
        return None
    slot = str(block.get("slot") or "").strip()
    if slot not in EQUIP_SLOTS:
        logger.warning(
            "[inventory] Unknown equip slot ignored (operation=equip_spec, item=%s, slot=%s)",
            item_id,
            slot,
        )
        return None
    return dict(block)


def collection_of(item_id: str) -> str:
    """The collection set this item belongs to, or ""."""
    return str((get_item(item_id) or {}).get("collection") or "")


def _quests_dir() -> Path:
    rel = get_config().get("paths.quests", "data/quests")
    return _ROOT / str(rel)


@lru_cache(maxsize=8)
def _read_quest_locks(dir_str: str, _fp: tuple[Any, ...]) -> frozenset[str]:
    """
    Item ids that some quest condition asks the player to be holding.

    Read as raw YAML and walked generically rather than parsed against the
    quest schema, because engine/game/quests.py owns that schema and this
    module has no business knowing its shape -- it only needs to know which
    ids appear behind a ``has_item`` key, at any depth.
    """
    found: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key in ("has_item", "not_has_item") and isinstance(value, dict):
                    item_id = str(value.get("id") or "").strip()
                    if item_id:
                        found.add(item_id)
                walk(value)
        elif isinstance(node, list):
            for entry in node:
                walk(entry)

    directory = Path(dir_str)
    if directory.is_dir():
        for path in sorted(directory.rglob("*.yaml")):
            try:
                with path.open(encoding="utf-8") as fh:
                    walk(yaml.safe_load(fh))
            except (OSError, yaml.YAMLError) as exc:
                # One malformed quest file costs that file's locks, not the
                # verb list for every item in the game.
                logger.warning(
                    "[inventory] Unreadable quest file (operation=_read_quest_locks, "
                    "path=%s): %s",
                    path.name,
                    exc,
                )
    return frozenset(found)


def quest_locks() -> frozenset[str]:
    """Every item id a quest condition asks for. Cached on directory mtimes."""
    directory = _quests_dir()
    fingerprint = tuple(
        (p.name, p.stat().st_mtime)
        for p in sorted(directory.rglob("*.yaml"))
        if directory.is_dir()
    )
    return _read_quest_locks(str(directory), fingerprint)


def reset_quest_lock_cache() -> None:
    """Drop the parsed lock set. Tests and hot reload only."""
    _read_quest_locks.cache_clear()


def _recipes_dir() -> Path:
    rel = get_config().get("paths.recipes", "data/recipes")
    return _ROOT / str(rel)


@lru_cache(maxsize=8)
def _read_recipe_refs(dir_str: str, _fp: tuple[Any, ...]) -> frozenset[str]:
    """Item ids any recipe consumes, requires as a tool, or produces."""
    found: set[str] = set()
    directory = Path(dir_str)
    if not directory.is_dir():
        return frozenset()
    for path in sorted(directory.glob("*.yaml")):
        try:
            with path.open(encoding="utf-8") as fh:
                data = yaml.safe_load(fh) or {}
        except (OSError, yaml.YAMLError) as exc:
            logger.warning(
                "[inventory] Unreadable recipe file (operation=_read_recipe_refs, "
                "path=%s): %s",
                path.name,
                exc,
            )
            continue
        for recipe in data.get("recipes") or []:
            if not isinstance(recipe, dict):
                continue
            for row in recipe.get("inputs") or []:
                if isinstance(row, dict) and row.get("id"):
                    found.add(str(row["id"]))
            for key in ("output", "salvage"):
                block = recipe.get(key)
                if isinstance(block, dict) and block.get("id"):
                    found.add(str(block["id"]))
            for tool in recipe.get("tools") or []:
                found.add(str(tool))
    return frozenset(found)


def recipe_refs() -> frozenset[str]:
    """Every item id some recipe consumes, needs as a tool, or makes."""
    directory = _recipes_dir()
    fingerprint = tuple(
        (p.name, p.stat().st_mtime) for p in sorted(directory.glob("*.yaml"))
    ) if directory.is_dir() else ()
    return _read_recipe_refs(str(directory), fingerprint)


def reset_recipe_ref_cache() -> None:
    """Drop the parsed recipe references. Tests and hot reload only."""
    _read_recipe_refs.cache_clear()


def is_edible(item_id: str) -> bool:
    """
    Whether ``survival.eat`` would accept this item.

    Asked of engine/game/survival.py rather than reimplemented, because the
    edible-tag fallback lives there and two copies of that rule would disagree
    the first time somebody added a tag.
    """
    from engine.game import survival

    return (
        survival.food_value(str(item_id), tags_of(item_id), survival.load_rules())
        is not None
    )


def equipped(state: GameState) -> dict[str, str]:
    """Slot -> item id for everything worn. Derived, never stored twice."""
    return effects_module.equipped_items(state)


def equip(state: GameState, item_id: str) -> dict[str, Any]:
    """
    Wear a carried item.

    Args:
        state: Mutable game state.
        item_id: Registry id to wear. Must be carried and must declare
            ``equip:``.

    Returns:
        Receipt dict. ``ok`` is False with a message for the ordinary player
        mistakes -- not carrying it, or it not being wearable -- because those
        are things the Storyteller narrates, not engine faults.
    """
    item_id = str(item_id)
    spec = equip_spec(item_id)
    if spec is None:
        return {"ok": False, "item_id": item_id, "message": f"{name_of(item_id)} is not worn."}
    if not holds(state, item_id):
        return {"ok": False, "item_id": item_id, "message": "You are not carrying that."}

    slot = str(spec["slot"])
    displaced = equipped(state).get(slot, "")
    if displaced == item_id:
        return {
            "ok": True,
            "item_id": item_id,
            "slot": slot,
            "unchanged": True,
            "text": f"Already worn: {name_of(item_id)}.",
        }

    receipt = effects_module.apply_effect(
        state,
        {
            "type": "equip",
            "item_id": item_id,
            "slot": slot,
            "text": name_of(item_id).lower(),
            "bonuses": [
                {
                    "skills": [str(s) for s in (b.get("skills") or [])],
                    "delta": int(b.get("delta", 0) or 0),
                    "text": str(b.get("text") or name_of(item_id).lower()),
                }
                for b in (spec.get("bonuses") or [])
                if isinstance(b, dict)
            ],
        },
    )
    return {
        "ok": True,
        "item_id": item_id,
        "name": name_of(item_id),
        "slot": slot,
        "displaced": displaced,
        "effect": receipt,
        "absorbs_wounds": int(spec.get("absorbs_wounds", 0) or 0),
        "text": str(spec.get("text") or f"You put on the {name_of(item_id).lower()}."),
    }


def unequip(state: GameState, slot: str = "", item_id: str = "") -> dict[str, Any]:
    """Take off whatever is worn in a slot, or a named item wherever it is."""
    receipt = effects_module.apply_effect(
        state, {"type": "unequip", "slot": str(slot), "item_id": str(item_id)}
    )
    return {"ok": True, "slot": str(slot), "effect": receipt, "text": receipt.get("text", "")}


def equipment_snapshot(state: GameState) -> dict[str, Any]:
    """Read-only view of every slot, worn or empty, for the UI and prompts."""
    worn = equipped(state)
    rows = []
    for slot in EQUIP_SLOTS:
        item_id = worn.get(slot, "")
        spec = equip_spec(item_id) or {} if item_id else {}
        rows.append(
            {
                "slot": slot,
                "item_id": item_id,
                "name": name_of(item_id) if item_id else "",
                "bonuses": [
                    {
                        "skills": [str(s) for s in (b.get("skills") or [])],
                        "delta": int(b.get("delta", 0) or 0),
                    }
                    for b in (spec.get("bonuses") or [])
                    if isinstance(b, dict)
                ],
                "absorbs_wounds": int(spec.get("absorbs_wounds", 0) or 0),
            }
        )
    return {
        "slots": rows,
        "worn_count": len(worn),
        "wound_absorption": effects_module.wound_mitigation(state),
        "carry_limit": carry_limit(state),
        "carried_weight": carried_weight(state),
    }


def wearable(state: GameState) -> list[dict[str, Any]]:
    """Carried items that could be worn right now, and where they would go."""
    worn = equipped(state)
    out = []
    for entry in state.inventory:
        spec = equip_spec(entry.id)
        if spec is None:
            continue
        slot = str(spec["slot"])
        out.append(
            {
                "item_id": entry.id,
                "name": name_of(entry.id),
                "slot": slot,
                "worn": worn.get(slot) == entry.id,
                "displaces": worn.get(slot, ""),
            }
        )
    return out


# ---------------------------------------------------------------------------
# collections
# ---------------------------------------------------------------------------


def _collections_path() -> Path:
    rel = get_config().get("paths.tables", "data/tables")
    return _ROOT / str(rel) / "collections.yaml"


@lru_cache(maxsize=8)
def _read_collections(path_str: str, _mtime: float) -> list[dict[str, Any]]:
    try:
        with Path(path_str).open(encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
    except (OSError, yaml.YAMLError) as exc:
        logger.warning("[inventory] Unreadable collections (operation=_read): %s", exc)
        return []
    return [r for r in (data.get("collections") or []) if isinstance(r, dict)]


def load_collections() -> list[dict[str, Any]]:
    """
    Declared collectable sets, or an empty list.

    A game with no collections.yaml is not broken -- The Drowned Carillon
    shipped without one for a release -- so a missing file is silence, not a
    warning.
    """
    path = _collections_path()
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return []
    return _read_collections(str(path), mtime)


def reset_collection_cache() -> None:
    """Drop the parsed sets. Tests and hot reload only."""
    _read_collections.cache_clear()


def _collection_flag(set_id: str) -> str:
    return f"collection_{set_id}_complete"


def collection_status(state: GameState) -> list[dict[str, Any]]:
    """
    Every declared set with how far along it is.

    Counts what is CARRIED, not what has ever been carried. A set you sold is a
    set you no longer have, which is the honest reading and the one that makes
    the completion payout a decision rather than a formality.
    """
    rows = []
    for row in load_collections():
        set_id = str(row.get("id") or "")
        members = [str(m) for m in (row.get("items") or [])]
        held = {m: quantity(state, m) for m in members}
        needed = {str(k): int(v) for k, v in (row.get("counts") or {}).items()}
        missing = [m for m in members if held.get(m, 0) < max(1, needed.get(m, 1))]
        rows.append(
            {
                "id": set_id,
                "name": str(row.get("name") or set_id),
                "blurb": str(row.get("blurb") or ""),
                "items": [
                    {
                        "item_id": m,
                        "name": name_of(m),
                        "have": held.get(m, 0),
                        "need": max(1, needed.get(m, 1)),
                    }
                    for m in members
                ],
                "complete": not missing,
                "missing": missing,
                "claimed": bool(state.flags.get(_collection_flag(set_id))),
                "reward_text": str(row.get("reward_text") or ""),
            }
        )
    return rows


#: Re-entrancy guard. A collection reward that grants an item would otherwise
#: re-enter this function from inside effects.apply_effect and, with two sets
#: that feed each other, recurse. One level is all any payout needs.
_evaluating_collections = False


def evaluate_collections(state: GameState) -> list[dict[str, Any]]:
    """
    Pay out any newly completed set. Idempotent.

    Called from ``grant`` and from the ``collections`` skill, so a set completes
    the moment its last piece lands rather than when the player thinks to check.
    Completion is recorded as a flag, so a set pays once even if the player
    sells a piece and re-collects it.
    """
    global _evaluating_collections
    if _evaluating_collections:
        return []
    completed = []
    _evaluating_collections = True
    try:
        for row in collection_status(state):
            if not row["complete"] or row["claimed"]:
                continue
            set_id = row["id"]
            spec = next((c for c in load_collections() if str(c.get("id")) == set_id), {})
            applied = effects_module.apply_effects(
                state, list(spec.get("effects") or [])
            )
            state.flags[_collection_flag(set_id)] = True
            logger.info(
                "[inventory] Collection completed (operation=evaluate_collections, set=%s)",
                set_id,
            )
            completed.append(
                {
                    "id": set_id,
                    "name": row["name"],
                    "text": row["reward_text"],
                    "effects": applied,
                }
            )
    finally:
        _evaluating_collections = False
    return completed


# ---------------------------------------------------------------------------
# carried inventory
# ---------------------------------------------------------------------------


def find(state: GameState, item_id: str) -> Optional[InventoryItem]:
    """The carried entry for an id, or None."""
    return next((i for i in state.inventory if i.id == str(item_id)), None)


def quantity(state: GameState, item_id: str) -> int:
    """How many of an id the player carries. Zero when none."""
    entry = find(state, item_id)
    return int(entry.qty) if entry and entry.qty > 0 else 0


def holds(state: GameState, item_id: str, qty: int = 1) -> bool:
    """True when the player carries at least ``qty`` of an id."""
    return quantity(state, item_id) >= max(1, int(qty))


def grant(state: GameState, item_id: str, qty: int = 1) -> dict[str, Any]:
    """
    Add items, filling name and tags from the registry.

    Routed through ``effects.apply_effect`` rather than appending directly:
    that module is the only sanctioned writer of game state, and a receipt is
    what the UI renders.
    """
    receipt = effects_module.apply_effect(
        state,
        {
            "type": "item",
            "item_id": str(item_id),
            "qty": max(1, int(qty)),
            "name": name_of(item_id),
            "tags": tags_of(item_id),
        },
    )
    # A set completes the moment its last piece lands, not when the player
    # thinks to go and look.
    if collection_of(item_id):
        finished = evaluate_collections(state)
        if finished:
            receipt = dict(receipt)
            receipt["collections"] = finished
    return receipt


def take(state: GameState, item_id: str, qty: int = 1) -> dict[str, Any]:
    """Remove items through the effect dispatcher. Never raises on a miss."""
    return effects_module.apply_effect(
        state,
        {"type": "remove_item", "item_id": str(item_id), "qty": max(1, int(qty))},
    )


def carried_value(state: GameState) -> int:
    """Total base worth of everything carried. Used by reports and the sim."""
    return sum(value_of(i.id) * max(0, int(i.qty)) for i in state.inventory)


def carry_limit(state: GameState) -> float:
    """
    Carry allowance in kilograms: the base plus whatever a worn pack adds.

    **NOT WIRED as a penalty.** Nothing refuses a pickup or docks a check for
    being over it; ``engine/game/checks.py`` has no encumbrance situational and
    this module does not add one. It is reported by ``snapshot`` so a pack is a
    visible, growing number rather than an invisible claim, and so the rule --
    when someone writes it -- has a limit that was chosen once rather than
    sixty times in a hurry.
    """
    bonus = 0.0
    for item_id in equipped(state).values():
        spec = equip_spec(item_id) or {}
        try:
            bonus += float(spec.get("carry_bonus", 0.0) or 0.0)
        except (TypeError, ValueError):
            continue
    return round(BASE_CARRY_KG + bonus, 2)


def carried_weight(state: GameState) -> float:
    """
    Total carried weight in kilograms.

    Compared against ``carry_limit`` for reporting only -- see that function for
    why nothing enforces it yet.
    """
    total = 0.0
    for entry in state.inventory:
        row = get_item(entry.id) or {}
        try:
            total += float(row.get("weight", 0.0) or 0.0) * max(0, int(entry.qty))
        except (TypeError, ValueError):
            continue
    return round(total, 2)


def describe(state: GameState) -> list[dict[str, Any]]:
    """
    Carried inventory joined against the registry, for the UI and prompts.

    One row per stack: id, name, qty, tags, unit value, stack value, weight and
    art key. This is the payload the inventory panel wants and the reason it
    previously had to guess at half of it.
    """
    rows: list[dict[str, Any]] = []
    worn = equipped(state)
    for entry in state.inventory:
        row = get_item(entry.id) or {}
        unit = value_of(entry.id)
        rows.append(
            {
                "id": entry.id,
                "name": entry.name or name_of(entry.id),
                "qty": int(entry.qty),
                "tags": tags_of(entry.id, entry.tags),
                "description": str(row.get("description") or "").strip(),
                "value": unit,
                "stack_value": unit * max(0, int(entry.qty)),
                "weight": float(row.get("weight", 0.0) or 0.0),
                "art": str(row.get("art") or ""),
                "known": bool(row),
                # What the player can DO with it, so the inventory panel and the
                # narration prompt stop having to guess. An empty list here is
                # the bug report: it means the thing is decoration.
                "usable": use_spec(entry.id) is not None,
                "equippable": (equip_spec(entry.id) or {}).get("slot", ""),
                "worn": worn.get(str((equip_spec(entry.id) or {}).get("slot", ""))) == entry.id,
                "collection": collection_of(entry.id),
            }
        )
    return rows


def verbs_for(item_id: str) -> list[str]:
    """
    Every verb an item answers to. Empty means the item is decoration.

    This is the audit in code: ``tests/test_items.py`` asserts no registry entry
    comes back empty, so a new item cannot be added without a reason to exist.
    """
    row = get_item(item_id)
    if row is None:
        return []
    verbs = []
    if use_spec(item_id):
        verbs.append("use")
    if is_edible(item_id):
        verbs.append("eat")
    if equip_spec(item_id):
        verbs.append("equip")
    if item_id in recipe_refs():
        verbs.append("craft")
    if collection_of(item_id):
        verbs.append("collect")
    if item_id in quest_locks():
        # Not a verb the player performs -- a door the item opens. It belongs
        # in this list because "what is this for" is the question, and "a quest
        # will ask you for it" is a complete answer. Four items in the flagship
        # registry -- cut_reed, fourth_verse, copied_list, nessas_drawing --
        # have this and nothing else, on purpose: they are evidence, and
        # evidence with a price on it is loot.
        verbs.append("quest")
    if value_of(item_id) > 0:
        verbs.append("trade")
    return verbs


def snapshot(state: GameState) -> dict[str, Any]:
    """Read-only inventory status: the stacks, the purse, the totals and the gear."""
    rows = describe(state)
    return {
        "gold": int(state.stats.gold),
        "items": rows,
        "count": sum(r["qty"] for r in rows),
        "carried_value": sum(r["stack_value"] for r in rows),
        "carried_weight": carried_weight(state),
        "carry_limit": carry_limit(state),
        "equipment": equipment_snapshot(state),
    }


# ---------------------------------------------------------------------------
# using a thing
# ---------------------------------------------------------------------------


def _use_marker(item_id: str) -> str:
    return f"used:{item_id}"


def use(state: GameState, item_id: str) -> dict[str, Any]:
    """
    Do whatever an item's ``use:`` block says it does.

    The hours are spent through ``clock.advance_time`` and every state change
    goes through ``effects.apply_effect``, so a draught of bittergreen is a
    receipt with arithmetic on it rather than a sentence the narrator invented.

    Args:
        state: Mutable game state.
        item_id: Registry id to use.

    Returns:
        Receipt dict. ``ok`` is False with a message when the item is absent,
        has no verb, is missing a companion item, or has already been used today
        under a ``once_per_day`` block. None of those raise: all four are
        ordinary player mistakes.
    """
    from engine.game.clock import advance_time
    from engine.game.state import TimedEffect

    item_id = str(item_id)
    spec = use_spec(item_id)
    if spec is None:
        return {
            "ok": False,
            "item_id": item_id,
            "message": f"There is nothing to do with {name_of(item_id).lower()}.",
        }
    if not holds(state, item_id):
        return {"ok": False, "item_id": item_id, "message": "You are not carrying that."}

    marker = _use_marker(item_id)
    if bool(spec.get("once_per_day")) and any(
        e.id == marker for e in state.active_effects
    ):
        return {
            "ok": False,
            "item_id": item_id,
            "message": f"You have already done that with the {name_of(item_id).lower()} today.",
        }

    # Companion inputs are checked before anything is spent. A fire that eats
    # the tinderbox and then discovers there is no firewood is the kind of
    # half-applied action the effect dispatcher exists to prevent.
    also = [r for r in (spec.get("also_consumes") or []) if isinstance(r, dict)]
    short = [
        r for r in also if not holds(state, str(r.get("id")), int(r.get("qty", 1) or 1))
    ]
    if short:
        return {
            "ok": False,
            "item_id": item_id,
            "message": "You are short of "
            + ", ".join(name_of(str(r.get("id"))).lower() for r in short),
        }

    hours = float(spec.get("hours", 0.0) or 0.0)
    if hours > 0:
        advance_time(state, hours)

    consumed = max(0, int(spec.get("consumes", 0) or 0))
    applied: list[dict[str, Any]] = []
    if consumed:
        applied.append(
            effects_module.apply_effect(
                state, {"type": "remove_item", "item_id": item_id, "qty": consumed}
            )
        )
    for row in also:
        applied.append(
            effects_module.apply_effect(
                state,
                {
                    "type": "remove_item",
                    "item_id": str(row.get("id")),
                    "qty": int(row.get("qty", 1) or 1),
                },
            )
        )

    applied.extend(
        effects_module.apply_effects(state, list(spec.get("effects") or []))
    )

    if bool(spec.get("once_per_day")):
        # Same trick as the labour shift cap in engine/game/economy.py: the
        # clock's expiry sweep IS the reset rule, so no new save field.
        state.active_effects.append(
            TimedEffect(
                id=marker,
                kind="item_use",
                text=f"used {name_of(item_id).lower()}",
                expires_day=state.world_day,
            )
        )

    logger.info(
        "[inventory] Item used (operation=use, item=%s, hours=%s)", item_id, hours
    )
    return {
        "ok": True,
        "item_id": item_id,
        "name": name_of(item_id),
        "verb": str(spec.get("verb") or "use"),
        "hours": hours,
        "consumed": consumed,
        "effects": applied,
        "world_day": state.world_day,
        "text": str(spec.get("text") or f"You use the {name_of(item_id).lower()}."),
    }
