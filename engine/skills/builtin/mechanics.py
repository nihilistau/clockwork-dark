"""
Mechanics Skills
================

Required tools for Storyteller mechanical resolution.

Version: v0.2.0 [2026-08-07]
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from engine.config import get_config
from engine.game.engine import get_active_engine
from engine.skills.registry import (
    AGENT_STORYTELLER,
    AGENT_SYSTEM,
    TRIGGER_REQUIRED,
    TRIGGER_SYSTEM,
    skill,
)

_ROOT = Path(__file__).resolve().parents[3]


def _load_economy() -> dict[str, Any]:
    path = get_config().get("paths.economy", "data/economy.yaml")
    economy_path = _ROOT / path
    if not economy_path.exists():
        return {}
    with economy_path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


@skill(
    pack="clockwork",
    description="Roll dice. MUST call before narrating any roll outcome.",
    category="GAME",
    trigger=TRIGGER_REQUIRED,
)
def roll_dice(sides: int = 20, modifier: int = 0, reason: str = "") -> str:
    """Roll dice via engine."""
    engine = get_active_engine()
    result = engine.roll(sides=sides, modifier=modifier, reason=reason)
    return json.dumps(result.to_dict())


@skill(
    pack="clockwork",
    description=(
        "Resolve a skill check. MUST call for risky actions. Pick a skill "
        "(persuasion|stealth|sympathy|lore|craft|survival|nerve) and a difficulty "
        "BAND (trivial|easy|standard|hard|severe|legendary). You do NOT set a DC "
        "or a modifier -- the engine derives both."
    ),
    category="GAME",
    trigger=TRIGGER_REQUIRED,
)
def resolve_skill_check(
    skill: str,
    difficulty: str = "standard",
    reason: str = "",
) -> str:
    """
    Resolve a skill check through the rules engine.

    The DC is gone from this signature on purpose. When the narrator supplied
    it, difficulty was whatever the model felt like that turn -- and the only
    modifiers that existed were three hardcoded lines in the tool dispatcher
    (``base_dc = 12``, ``+2`` stealth, ``+1`` persuasion). Exhaustion, injury,
    hunger, darkness, wounds and the evil phase did not touch a roll at all.
    The model now names a band; engine/game/checks.py computes the number and
    itemises every modifier in the receipt.

    Args:
        skill: One of the seven taxonomy skills.
        difficulty: Difficulty band name.
        reason: Short audit string describing what is being attempted.

    Returns:
        JSON CheckResult, including a "summary" line for narration receipts.
    """
    from engine.game import checks

    engine = get_active_engine()
    result = checks.resolve(engine.state, skill, difficulty)
    payload = result.to_dict()
    payload["reason"] = reason
    return json.dumps(payload)


@skill(
    pack="clockwork",
    description=(
        "Rest to recover stamina. kind = rest_short (2h) | sleep_bed (8h, needs "
        "a bed) | sleep_rough (8h outdoors, survival check). Advances the clock."
    ),
    category="GAME",
    trigger="optional",
    agents=[AGENT_STORYTELLER],
)
def rest(kind: str = "rest_short") -> str:
    """
    Recover stamina by stopping.

    This is the only action in the game that raises stamina, and it exists
    because nothing did: travel spent stamina and nothing gave it back, so a
    player soft-locked at 0 after a handful of long trips.
    """
    from engine.game import survival

    engine = get_active_engine()
    return json.dumps(survival.rest(engine.state, kind))


@skill(
    pack="clockwork",
    description="Eat one food item from inventory to reduce hunger.",
    category="GAME",
    trigger="optional",
    agents=[AGENT_STORYTELLER],
)
def eat(item_id: str) -> str:
    """Consume one food item, reducing hunger."""
    from engine.game import survival

    engine = get_active_engine()
    return json.dumps(survival.eat(engine.state, item_id))


@skill(
    pack="clockwork",
    description=(
        "Wait or sleep until a given hour of day (0-23). Advances the clock; "
        "8+ hours of it counts as a night's sleep."
    ),
    category="GAME",
    trigger="optional",
    agents=[AGENT_STORYTELLER],
)
def sleep_until(hour: int = 6) -> str:
    """
    Pass time until an hour of day.

    Long waits route through the rest rules rather than a bare clock advance,
    so a night spent waiting restores stamina the same way a night spent
    sleeping does -- otherwise "wait until dawn" is a free way to burn the
    world clock while getting nothing back.
    """
    from engine.game import survival
    from engine.game.clock import advance_time, hours_until

    engine = get_active_engine()
    state = engine.state
    hours = hours_until(state, int(hour))

    rules = survival.load_rules()
    sleep_hours = float((rules.get("rest", {}).get("sleep_bed", {}) or {}).get("hours", 8))

    if hours >= sleep_hours:
        has_bed = state.location_id in list(
            (rules.get("rest", {}).get("sleep_bed", {}) or {}).get("locations", [])
        )
        outcome = survival.rest(state, "sleep_bed" if has_bed else "sleep_rough")
        remaining = hours - float(outcome.get("hours", 0.0))
        if remaining > 0:
            advance_time(state, remaining)
        outcome["hours"] = hours
        outcome["until_hour"] = int(hour) % 24
        return json.dumps(outcome)

    advance = advance_time(state, hours)
    return json.dumps(
        {
            "success": True,
            "kind": "wait",
            "hours": hours,
            "until_hour": int(hour) % 24,
            "world_day": state.world_day,
            "world_hour": state.world_hour,
            "stamina": state.stats.stamina,
            "hunger": round(state.hunger, 1),
            "time_advance": advance.to_dict(),
            "text": "You wait.",
        }
    )


@skill(
    pack="clockwork",
    description="Move player to location_id along the location graph.",
    category="GAME",
    trigger=TRIGGER_REQUIRED,
)
def move_to(location_id: str) -> str:
    """Travel via engine."""
    engine = get_active_engine()
    return json.dumps(engine.move_to(location_id).to_dict())


@skill(
    pack="clockwork",
    description="Browse, buy, or sell with an NPC vendor.",
    category="GAME",
    trigger="optional",
)
def trade(action: str, item_id: str = "", npc_id: str = "") -> str:
    """Trade using economy.yaml prices."""
    engine = get_active_engine()
    state = engine.state
    economy = _load_economy()
    vendor = economy.get(npc_id, {})

    if action == "browse":
        return json.dumps({"npc_id": npc_id, "sells": vendor.get("sells", {}), "buys": vendor.get("buys", {})})

    if action == "buy":
        sells = vendor.get("sells", {})
        item = sells.get(item_id)
        if not item:
            return json.dumps({"success": False, "message": f"{npc_id} does not sell {item_id}."})
        price = int(item.get("price", 0))
        if state.stats.gold < price:
            return json.dumps({"success": False, "message": "Not enough gold."})
        state.stats.gold -= price
        engine.add_item(item_id, item.get("name", item_id))
        return json.dumps({"success": True, "item_id": item_id, "gold_spent": price, "gold": state.stats.gold})

    if action == "sell":
        buys = vendor.get("buys", {})
        item = buys.get(item_id)
        if not item:
            return json.dumps({"success": False, "message": f"{npc_id} does not buy {item_id}."})
        owned = next((i for i in state.inventory if i.id == item_id), None)
        if not owned or owned.qty < 1:
            return json.dumps({"success": False, "message": "You do not have that item."})
        price = int(item.get("price", 0))
        owned.qty -= 1
        if owned.qty <= 0:
            state.inventory.remove(owned)
        state.stats.gold += price
        return json.dumps({"success": True, "item_id": item_id, "gold_gained": price, "gold": state.stats.gold})

    return json.dumps({"success": False, "message": f"Unknown trade action: {action}"})


@skill(
    pack="clockwork",
    description="Advance world day and evil ticker. System and tests only.",
    category="SYSTEM",
    trigger=TRIGGER_SYSTEM,
    agents=[AGENT_SYSTEM],
)
def advance_world_tick(days: float = 1.0, force_event: str = "") -> str:
    """
    World tick with optional forced schedule event.

    Deliberately NOT callable by any agent. Exposed to the model, an unbounded
    ``days`` is a time machine: negative values rewound the calendar and large
    ones jumped the world straight to the CONSUMING endgame in a single call.
    Time advances through play -- travel, rest, work -- or not at all.
    """
    engine = get_active_engine()
    force_events = [force_event] if force_event else None
    return json.dumps(engine.advance_world_day(days=days, force_events=force_events))


@skill(
    pack="clockwork",
    description="Storyteller-only: full evil and pressure snapshot.",
    category="NARRATIVE",
    trigger=TRIGGER_REQUIRED,
)
def query_evil_state() -> str:
    """Evil snapshot for GM narration."""
    engine = get_active_engine()
    return json.dumps(engine.get_evil_snapshot())


@skill(
    pack="clockwork",
    description=(
        "Read the encounter the player is currently in: the intro, the threat, "
        "how much fight it has left, what has happened so far, and the exact "
        "list of approaches that are legal right now. Returns {} when nothing "
        "is happening. Call this before describing a scene you did not open."
    ),
    category="NARRATIVE",
    trigger=TRIGGER_REQUIRED,
)
def query_encounter() -> str:
    """
    Current encounter scene, or ``{}`` when idle.

    The ``approaches`` list is engine-authored and is the contract: every id in
    it can be handed straight to ``encounter_approach`` and will resolve.
    Anything the player cannot pay for, cannot reach at this hour or lacks the
    item for is simply absent, so the narrator is never in a position to offer
    a choice the engine will then refuse.
    """
    from engine.game import encounter

    engine = get_active_engine()
    scene = encounter.snapshot(engine.state)
    return json.dumps(
        {
            "active": encounter.active(engine.state),
            "encounter": scene,
            "approaches": scene.get("approaches", []),
        }
    )


@skill(
    pack="clockwork",
    description=(
        "Resolve one round of the current encounter with a named approach "
        "(talk|fight|sneak|pay|flee|...). MUST call before narrating how a "
        "confrontation goes. Use only ids returned by query_encounter's "
        "approaches list. One to three rounds and the scene is over."
    ),
    category="GAME",
    trigger=TRIGGER_REQUIRED,
)
def encounter_approach(approach: str) -> str:
    """
    Take one approach to the active encounter.

    There is no combat loop behind this. An encounter is a short contested
    scene: the approach becomes one skill check through engine/game/checks.py,
    the degree strips resolve from the threat, and the scene closes when the
    threat breaks, the round cap is hit, or a failure lands. Consequences are
    wounds with names and heal dates rather than a hit-point countdown.

    Args:
        approach: Approach id from ``query_encounter``.

    Returns:
        JSON receipt: the check summary, the outcome text, every applied
        effect, whether the scene is over, and a death record if the player
        was put below the threshold. Never raises; an illegal approach comes
        back as ``ok: false`` with the legal list.
    """
    from engine.game import encounter

    engine = get_active_engine()
    return json.dumps(encounter.resolve_approach(engine.state, approach))


@skill(
    pack="clockwork",
    description=(
        "Break off the current encounter and walk away. Shorthand for "
        "encounter_approach('flee'); always available while a scene is open."
    ),
    category="GAME",
    trigger="optional",
    agents=[AGENT_STORYTELLER],
)
def flee() -> str:
    """
    Leave the scene.

    Exists as its own tool because walking away is a decision the narrator
    reaches for constantly and should never have to discover in an approach
    list. data/encounters/rules.yaml merges a ``flee`` approach into every
    encounter, so this cannot fail for want of an option -- a scene with no
    legal exit is a soft-lock.
    """
    from engine.game import encounter

    engine = get_active_engine()
    return json.dumps(encounter.resolve_approach(engine.state, "flee"))

def _load_recipes() -> dict[str, Any]:
    """
    All recipes, keyed by id.

    Merged across data/recipes/*.yaml so a malformed file costs one category
    rather than every recipe in the game.
    """
    root = _ROOT / str(get_config().get("paths.recipes", "data/recipes"))
    recipes: dict[str, Any] = {}
    if not root.exists():
        return recipes
    for path in sorted(root.glob("*.yaml")):
        try:
            with path.open(encoding="utf-8") as handle:
                data = yaml.safe_load(handle) or {}
        except (OSError, yaml.YAMLError):
            continue
        for entry in data.get("recipes", []) or []:
            if isinstance(entry, dict) and entry.get("id"):
                recipes[str(entry["id"])] = entry
    return recipes


def _held(state: Any, item_id: str, qty: int = 1) -> bool:
    return any(i.id == item_id and i.qty >= qty for i in state.inventory)


@skill(
    pack="clockwork",
    description=(
        "Make something from a recipe. Consumes the inputs and the hours "
        "whether or not it works. Call list_recipes first if unsure."
    ),
    category="GAME",
    trigger="optional",
    agents=[AGENT_STORYTELLER],
)
def craft_item(recipe_id: str) -> str:
    """
    Attempt a recipe.

    DESIGN.md makes "mundane craft as dignity" a pillar and the Quiet Life arc
    a complete way to play, and until now there was no way to MAKE anything --
    a baker could buy bread and be given bread, and that was the whole fantasy.

    Inputs and time are spent on the attempt, not on success: a failed bake
    still costs you the morning, or the risk is not a risk.
    """
    from engine.game import effects as effects_module
    from engine.game import checks
    from engine.game.clock import advance_time

    engine = get_active_engine()
    state = engine.state

    recipe = _load_recipes().get(recipe_id)
    if recipe is None:
        return json.dumps({"success": False, "error": f"No such recipe: {recipe_id}"})

    station = recipe.get("station")
    if station and state.location_id != station:
        return json.dumps(
            {"success": False, "error": f"That work happens at {station}, not here."}
        )

    for tool in recipe.get("tools", []) or []:
        if not _held(state, str(tool)):
            return json.dumps({"success": False, "error": f"You need a {tool} for that."})

    inputs = [i for i in (recipe.get("inputs") or []) if isinstance(i, dict)]
    missing = [i for i in inputs if not _held(state, str(i.get("id")), int(i.get("qty", 1)))]
    if missing:
        return json.dumps(
            {"success": False, "error": "You are short of " +
             ", ".join(str(m.get("id")) for m in missing)}
        )

    advance_time(state, float(recipe.get("hours", 1)))
    for item in inputs:
        effects_module.apply_effect(
            state,
            {"type": "remove_item", "id": str(item.get("id")), "qty": int(item.get("qty", 1))},
        )

    result = checks.resolve(
        state, str(recipe.get("skill", "craft")), str(recipe.get("band", "standard"))
    )
    passed = result.degree in ("crit_success", "success", "partial")
    granted = recipe.get("output") if passed else recipe.get("salvage")

    if isinstance(granted, dict) and granted.get("id"):
        effects_module.apply_effect(
            state,
            {"type": "item", "id": str(granted["id"]), "qty": int(granted.get("qty", 1))},
        )

    return json.dumps(
        {
            "success": passed,
            "recipe_id": recipe_id,
            "check": result.to_dict(),
            "produced": granted if granted else None,
            "hours": float(recipe.get("hours", 1)),
            "text": str(recipe.get("success_text" if passed else "failure_text", "")).strip(),
        }
    )


@skill(
    pack="clockwork",
    description="List recipes the player could attempt here, with what they need.",
    category="GAME",
    trigger="optional",
    agents=[AGENT_STORYTELLER],
)
def list_recipes() -> str:
    """Recipes available at the current location, and whether they are makeable."""
    engine = get_active_engine()
    state = engine.state

    available = []
    for recipe_id, recipe in _load_recipes().items():
        station = recipe.get("station")
        if station and state.location_id != station:
            continue
        inputs = [i for i in (recipe.get("inputs") or []) if isinstance(i, dict)]
        available.append(
            {
                "id": recipe_id,
                "name": recipe.get("name", recipe_id),
                "hours": recipe.get("hours", 1),
                "makeable": all(
                    _held(state, str(i.get("id")), int(i.get("qty", 1))) for i in inputs
                ),
                "needs": [f"{i.get('qty', 1)}x {i.get('id')}" for i in inputs],
            }
        )
    return json.dumps({"location_id": state.location_id, "recipes": available})
