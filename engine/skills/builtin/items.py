"""
Item Skills
===========

The verbs. Using a thing, wearing a thing, and knowing what a thing is for.

WHY THESE ARE TOOLS AND NOT PROSE: CLAUDE.md's first rule is that the engine
resolves mechanics and the model narrates them. A narrator free to say "you
bind the wound and feel better" is a narrator deciding how much better, which
wound, and whether the bandage was spent. Every entry point below is a thin
wrapper over engine/game/inventory.py, which owns the arithmetic and routes
every mutation through engine/game/effects.py -- so what comes back is a
receipt with numbers on it, not a claim.

THE GAP THESE CLOSE: an audit of the 81 declared items found 32 whose only
reachable verb was "sell it", including a poultice bandage that closed no
wound, a fever draught that did nothing to a fever, five pieces of apparel
nobody could put on and three items no code path in the game could grant.
data/items/*.yaml now carries `use:`, `equip:` and `collection:` blocks; these
are the tools that reach them.

Registered by importing this module; ``engine/skills/builtin/__init__.py`` does
that, and importing any sibling imports the package.

Version: v0.1.0 [2026-08-08]
"""

from __future__ import annotations

import json

from engine.game.engine import get_active_engine
from engine.skills.registry import AGENT_STORYTELLER, skill


@skill(
    pack="clockwork",
    description=(
        "Use a carried item for what it is FOR: bind a bandage, drink a "
        "draught, light a candle, build a fire, sharpen on a whetstone, study "
        "a map. Spends the hours and consumes what it consumes whether or not "
        "the player likes the result. MUST call before narrating an item doing "
        "anything. Call inspect_item first if unsure what an item does."
    ),
    category="GAME",
    trigger="optional",
    agents=[AGENT_STORYTELLER],
)
def use_item(item_id: str) -> str:
    """
    Apply an item's declared ``use:`` block.

    Args:
        item_id: Registry id of a carried item.

    Returns:
        JSON receipt: hours spent, what was consumed, every applied effect and
        a narration line. ``ok: false`` with a message for the four ordinary
        mistakes -- not carrying it, it having no verb, a missing companion
        item, and a once-a-day thing already done today.
    """
    from engine.game import inventory

    engine = get_active_engine()
    return json.dumps(inventory.use(engine.state, str(item_id)))


@skill(
    pack="clockwork",
    description=(
        "Put on a carried item: cloak, hood, boots, shield, lantern, charm, "
        "knife, pack. One item per slot -- wearing a second displaces the "
        "first. Worn gear shows up by name in every skill check receipt."
    ),
    category="GAME",
    trigger="optional",
    agents=[AGENT_STORYTELLER],
)
def equip_item(item_id: str) -> str:
    """
    Wear a carried item.

    Args:
        item_id: Registry id of a carried item with an ``equip:`` block.

    Returns:
        JSON receipt naming the slot, the bonuses and anything displaced.
    """
    from engine.game import inventory

    engine = get_active_engine()
    return json.dumps(inventory.equip(engine.state, str(item_id)))


@skill(
    pack="clockwork",
    description=(
        "Take off what is worn in a slot (head|body|feet|hands|belt|offhand|"
        "light|back|charm), or take off a named item wherever it is worn."
    ),
    category="GAME",
    trigger="optional",
    agents=[AGENT_STORYTELLER],
)
def unequip_item(slot: str = "", item_id: str = "") -> str:
    """
    Stop wearing something.

    Args:
        slot: Slot to empty. Optional if ``item_id`` is given.
        item_id: Specific item to remove. Optional if ``slot`` is given.

    Returns:
        JSON receipt naming what came off.
    """
    from engine.game import inventory

    engine = get_active_engine()
    return json.dumps(inventory.unequip(engine.state, str(slot), str(item_id)))


@skill(
    pack="clockwork",
    description=(
        "Read-only: every equipment slot, what is worn in it, what each worn "
        "thing is doing to which skill, how much wound severity the gear "
        "absorbs, and what carried items could be worn instead. Rolls nothing "
        "and spends no time."
    ),
    category="GAME",
    trigger="optional",
    agents=[AGENT_STORYTELLER],
)
def query_equipment() -> str:
    """Worn gear, its effects, and what else in the pack could be worn."""
    from engine.game import inventory

    engine = get_active_engine()
    state = engine.state
    payload = inventory.equipment_snapshot(state)
    payload["available"] = inventory.wearable(state)
    return json.dumps(payload)


@skill(
    pack="clockwork",
    description=(
        "Read-only: what a specific item IS and what can be done with it -- "
        "its verbs, its slot, its bonuses, what it is worth, which recipes "
        "consume it and which collection it belongs to. Call before telling a "
        "player an item is useless; the engine knows and the narrator does not."
    ),
    category="NARRATIVE",
    trigger="optional",
    agents=[AGENT_STORYTELLER],
)
def inspect_item(item_id: str) -> str:
    """
    Everything the registry knows about one item.

    Args:
        item_id: Registry id. Need not be carried.

    Returns:
        JSON: the registry row, the verb list, the equip block, the collection
        it belongs to, and every recipe that consumes, requires or produces it.
    """
    from engine.game import inventory
    from engine.skills.builtin.mechanics import _load_recipes

    engine = get_active_engine()
    state = engine.state
    item_id = str(item_id)
    row = inventory.get_item(item_id)

    consumed_by, produced_by, tool_for = [], [], []
    for recipe_id, recipe in _load_recipes().items():
        if any(str(i.get("id")) == item_id for i in (recipe.get("inputs") or [])):
            consumed_by.append(recipe_id)
        for key in ("output", "salvage"):
            block = recipe.get(key)
            if isinstance(block, dict) and str(block.get("id")) == item_id:
                produced_by.append(recipe_id)
        if item_id in [str(t) for t in (recipe.get("tools") or [])]:
            tool_for.append(recipe_id)

    return json.dumps(
        {
            "item_id": item_id,
            "known": row is not None,
            "name": inventory.name_of(item_id),
            "description": str((row or {}).get("description") or "").strip(),
            "tags": inventory.tags_of(item_id),
            "value": inventory.value_of(item_id),
            "weight": float((row or {}).get("weight", 0.0) or 0.0),
            "carried": inventory.quantity(state, item_id),
            "verbs": inventory.verbs_for(item_id),
            "use": inventory.use_spec(item_id),
            "equip": inventory.equip_spec(item_id),
            "collection": inventory.collection_of(item_id),
            "consumed_by_recipes": sorted(consumed_by),
            "produced_by_recipes": sorted(set(produced_by)),
            "tool_for_recipes": sorted(tool_for),
        }
    )


@skill(
    pack="clockwork",
    description=(
        "Every collectable set, how far along each one is, what is still "
        "missing, and what completing it paid or would pay. Also settles any "
        "set that is complete but unclaimed. Sets count what is CARRIED."
    ),
    category="GAME",
    trigger="optional",
    agents=[AGENT_STORYTELLER],
)
def collections() -> str:
    """
    Collectable set progress, settling anything newly complete.

    Sets normally close by themselves the moment their last piece lands (see
    ``inventory.grant``); this also settles a set assembled by a path that did
    not go through that door -- a quest effect, a trade, a boon table.
    """
    from engine.game import inventory

    engine = get_active_engine()
    state = engine.state
    completed = inventory.evaluate_collections(state)
    return json.dumps(
        {
            "sets": inventory.collection_status(state),
            "newly_completed": completed,
        }
    )
