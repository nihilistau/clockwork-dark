"""
Default Story API
=================

The engine's default story screens, as one Blueprint.

    GET /api/quests            the journal
    GET /api/codex/places      the Atlas
    GET /api/codex/souls       the Souls
    GET /api/codex/things      the Things
    GET /api/items             the pack
    GET /api/recipes           the recipe book
    GET /api/trade             who will barter, and at what price
    GET /api/notices           the notice board: contracts posted here

MOVED FROM ``content/scenes/clockwork/clockwork_api.py`` in v0.3.0. Every
route here resolves through ``paths.*`` on the active manifest (the loaders
below), so by the time it moved nothing in it was Clockwork-shaped -- a story
that declares items gets its items served, and one that declares none gets an
empty pack rather than Edgewood's. The old module remains as a compatibility
shim.

WHY THESE ARE STILL NOT IN THE ALWAYS-MOUNTED SHARED SET. Each one answers a
question that only makes sense if the story asked it. A story with no quests
should not serve an empty journal to satisfy a client that assumes one; a
story that trades in favours rather than coin should not be handed a vendor
table. So they stay behind ``scene.blueprint``, which defaults to this
factory: a story replaces them by naming its own in its ``game.yaml``, or
ships no screens at all by naming ``blueprint: ""``.

    scene:
      blueprint: games.tide_and_bell.api:story_blueprint

Every route here is a GET that mutates nothing. ``session_id`` is optional
except where a payload is meaningless without one: without a session the codex
degrades to "show everything" rather than 404ing, so the screens are still
browsable from a menu.

The view-model builders are deliberately pure functions of a (possibly absent)
GameState so they can be unit-tested without a Flask request.

Version: v0.1.0 [2026-08-13]
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from flask import Blueprint, jsonify, request

from engine.api.art import shipped_art_url
from engine.config import get_config
from engine.session import GameSession, SessionStore

logger = logging.getLogger(__name__)

# The Blueprint's registration name. Was "clockwork_story" when this module
# lived in the flagship's package; it names the engine default now. Only Flask
# endpoint names carry it -- no route, payload or template does.
BLUEPRINT_NAME = "default_story"


# ---------------------------------------------------------------------------
# Reference data for the journal / codex / barter screens
#
# These read content and engine tables directly.
# ---------------------------------------------------------------------------


def quest_journal(state: Any) -> dict[str, Any]:
    """
    Everything the journal screen renders.

    Objective lines come from QuestEngine so the player reads exactly what the
    Storyteller reads -- a journal that paraphrases the prompt is a journal
    that will eventually disagree with it.
    """
    from engine.game.quests import (
        QuestEngine,
        load_arcs,
        load_quests,
        progress_records,
    )

    definitions = load_quests()
    arcs = load_arcs()
    quests: list[dict[str, Any]] = []

    for quest_id, record in progress_records(state).items():
        definition = definitions.get(quest_id, {})
        stages = definition.get("stages") or []
        stage = QuestEngine.current_stage(definition, record) if definition else None
        quests.append(
            {
                "id": quest_id,
                "title": str(definition.get("name") or quest_id.replace("_", " ").title()),
                "arc": str(definition.get("arc") or ""),
                "arc_title": str(
                    (arcs.get(str(definition.get("arc"))) or {}).get("name")
                    or definition.get("arc")
                    or ""
                ),
                "summary": str(definition.get("summary") or "").strip(),
                "status": record.status,
                "stage_index": record.stage_index,
                "stage_count": len(stages),
                "stage_id": str((stage or {}).get("id") or ""),
                "objective": str((stage or {}).get("objective") or "").strip(),
                "started_day": record.started_day,
            }
        )

    active_arc = str(getattr(state, "active_arc", ""))
    return {
        "active_arc": active_arc,
        "active_arc_title": str((arcs.get(active_arc) or {}).get("name") or active_arc),
        "active_arc_blurb": str((arcs.get(active_arc) or {}).get("blurb") or "").strip(),
        "arcs_unlocked": [
            {
                "id": str(arc_id),
                "title": str((arcs.get(str(arc_id)) or {}).get("name") or arc_id),
                "blurb": str((arcs.get(str(arc_id)) or {}).get("blurb") or "").strip(),
            }
            for arc_id in (getattr(state, "arcs_unlocked", None) or [])
        ],
        "objectives": QuestEngine.active_objectives(state),
        "quests": quests,
    }


def codex_places(state: Any, ledger: Any = None) -> list[dict[str, Any]]:
    """
    The Atlas. Every canonical location, gated on having been there.

    Undiscovered places still appear -- the shape of the map is not a secret,
    only what is in it -- but carry no picture and no description.

    THERE ARE TWO KINDS OF HIDDEN, and only one of them was expressible. An
    undiscovered place is one the player has not walked to yet: it belongs on
    the map, greyed, because knowing a road exists is not knowing what is down
    it. A place marked ``secret: true`` is one the player must not know EXISTS,
    and that is a spoiler rather than a fog-of-war question -- so it is withheld
    from the payload entirely rather than drawn as a grey rectangle with a
    tantalising road count. Walking there reveals it permanently, which is what
    makes it a discovery instead of a lie.
    """
    from engine.game.locations import LOCATIONS

    visited: set[str] = set()
    time_of_day = "day"
    evil_phase = "dormant"
    if state is not None:
        # The quest engine's own visited ledger; see quests.py::_meta, whose
        # reserved block is the `_meta` key inside state.quests.
        meta = (getattr(state, "quests", None) or {}).get("_meta") or {}
        visited = {str(v) for v in (meta.get("visited") or [])}
        visited.add(str(state.location_id))
        time_of_day = state.time_of_day
        evil_phase = state.evil_phase.value

    points = map_points(state, ledger)

    places: list[dict[str, Any]] = []
    for place_id, row in LOCATIONS.items():
        discovered = not state or place_id in visited
        if row.get("secret") and not discovered:
            continue
        places.append(
            {
                "id": place_id,
                "name": str(row.get("name") or place_id.replace("_", " ").title()),
                "ring": int(row.get("ring", 0)),
                "discovered": discovered,
                "here": bool(state is not None and state.location_id == place_id),
                # Withheld until walked, deliberately. Art ships for all 20
                # places and it is tempting to send all 20 -- the Atlas used to
                # be a grid of black rectangles over paintings sitting on disk.
                # But the fix for that was the per-ring wash, road count and
                # per-place unknown line the client now draws, NOT the painting
                # itself: `.codexcard.is-unknown` filters only `.paint__wash`,
                # so an image sent here renders at full strength and the player
                # sees every place in the game on turn one. The shape of the
                # map is not a secret; what is behind the next tree is.
                "image": shipped_art_url(place_id, "location", time_of_day, evil_phase)
                if discovered
                else "",
                "roads": [
                    {
                        "to": str(other),
                        "name": str(
                            (LOCATIONS.get(str(other)) or {}).get("name") or other
                        ),
                        "hours": int(edge.get("hours", 0)),
                        "danger_dc": int(edge.get("danger_dc", 0)),
                    }
                    for other, edge in (row.get("connections") or {}).items()
                    # A road TO a secret place is itself a secret. Drawing the
                    # edge and omitting its destination would advertise exactly
                    # what withholding the place was for.
                    if not (
                        (LOCATIONS.get(str(other)) or {}).get("secret")
                        and str(other) not in visited
                    )
                ],
                "points": points.get(place_id, []),
            }
        )
    return places


def clue_board(state: Any, ledger: Any = None) -> list[dict[str, Any]]:
    """
    The player's own working-out, newest first.

    THREE KINDS OF KNOWING, and this is the third. What is TRUE lives in the
    world; what a CHARACTER knows lives in their subject memory; what the
    PLAYER has pieced together is neither, and conflating it with either is how
    a mystery stops being one -- a board built from world truth would hand over
    the answer, and one built from a character's memory would show the player
    things nobody told them.

    Each clue carries what it is ABOUT, resolved to a display name where the
    subject is a place or a named person, so the board reads as a board rather
    than as a list of ids.
    """
    if ledger is None:
        return []

    names = getattr(ledger, "names", {}) or {}
    try:
        from engine.game.locations import LOCATIONS
    except Exception:  # noqa: BLE001 -- a story with no graph still has clues
        LOCATIONS = {}  # type: ignore[assignment]

    out: list[dict[str, Any]] = []
    for clue in ledger.clues():
        subject = str(clue.subject_id or "")
        label = (
            str((LOCATIONS.get(subject) or {}).get("name") or "")
            or str(names.get(subject) or "")
            or subject.replace("_", " ")
        )
        out.append(
            {
                "id": clue.id,
                "text": clue.text,
                "subject_id": subject,
                "about": label,
                "day": clue.day,
                "turn": clue.turn,
            }
        )
    return out


def map_points(state: Any, ledger: Any = None) -> dict[str, list[dict[str, Any]]]:
    """
    What is worth going to, per location, derived from live state.

    DERIVED, NEVER AUTHORED TWICE. A point of interest is not a new content
    type -- it is a view of things a story already declares. An objective is a
    point because a quest stage names a location; a vendor is a point because
    the economy says they trade there. Authoring a parallel "map pins" file
    would be a second place to forget to update, and the first symptom would be
    a map confidently pointing at a quest that ended two days ago.

    Returns:
        ``{location_id: [{kind, label}]}``. Empty for a story with no quests
        and no economy, which is most of the deck-shaped ones.
    """
    points: dict[str, list[dict[str, Any]]] = {}
    if state is None:
        return points

    def add(place_id: str, kind: str, label: str) -> None:
        if not place_id or not label:
            return
        points.setdefault(place_id, []).append({"kind": kind, "label": label})

    # Objectives. The location comes out of the stage definition itself via the
    # validator's own reference walker, so a stage that names a place in ANY of
    # the predicate shapes it supports is found without this function learning
    # the predicate vocabulary twice.
    try:
        from engine.games.validation import location_refs
        from engine.game.quests import QuestEngine

        for definition, record in QuestEngine.active_quests(state):
            stage = QuestEngine.current_stage(definition, record)
            if not stage:
                continue
            objective = str(stage.get("objective") or "").strip()
            if not objective:
                continue
            name = str(definition.get("name") or record.quest_id)
            for place_id in location_refs(stage):
                add(place_id, "objective", f"{name} — {objective}")
    except Exception as exc:  # noqa: BLE001 -- a story with no quests
        logger.debug("[api] No quest points for the map: %s", exc)

    # Clues the player has learned ABOUT a place. Free, because a clue is a
    # fact with a subject and a location id is a subject -- no map data was
    # authored and no clue was written twice.
    # Passed in rather than reached for: the ledger lives on the SESSION and
    # this function is handed state, and quietly digging one out of a back
    # reference would be the same conflation the engine/story seam removes.
    try:
        if ledger is not None:
            for clue in ledger.clues(limit=40):
                if clue.subject_id:
                    add(clue.subject_id, "clue", clue.text)
    except Exception as exc:  # noqa: BLE001 -- a story with no ledger
        logger.debug("[api] No clue points for the map: %s", exc)

    # Vendors, for places the player has reason to walk back to.
    try:
        from engine.game import trade
        from engine.game.locations import LOCATIONS

        for place_id in LOCATIONS:
            for npc_id in trade.vendors_at(place_id):
                listing = trade.browse(state, npc_id)
                if listing.get("ok"):
                    add(place_id, "vendor", str(listing.get("vendor") or npc_id))
    except Exception as exc:  # noqa: BLE001 -- a story with no economy
        logger.debug("[api] No vendor points for the map: %s", exc)

    return points


def codex_souls(state: Any, ledger: Any = None) -> dict[str, Any]:
    """
    The Souls. Villagers met, plus the Assistant's five canonical forms.

    An unmet NPC is listed by role and place only. Naming everyone up front
    would hand the player a cast list the fiction has not introduced.
    """
    from engine.game.locations import LOCATIONS

    relations = getattr(ledger, "relations", {}) or {}
    npcs = list(getattr(getattr(state, "procgen", None), "npcs", []) or [])
    if not npcs:
        # No session: fall back to the canon cast from the procgen templates so
        # the codex is still worth opening from a menu.
        from engine.game.procgen import load_templates

        npcs = list(load_templates().get("canon_npcs", []) or [])

    souls: list[dict[str, Any]] = []
    for npc in npcs:
        npc_id = str(npc.get("id") or "")
        relation = relations.get(npc_id)
        met = bool(state is None or getattr(relation, "met", False))
        place_id = str(npc.get("location_id") or "")
        souls.append(
            {
                "id": npc_id,
                "name": str(npc.get("name") or npc_id) if met else "Someone",
                "role": str(npc.get("role") or "villager").replace("_", " "),
                "place": str((LOCATIONS.get(place_id) or {}).get("name") or place_id),
                "traits": [str(t) for t in (npc.get("traits") or [])] if met else [],
                "canon": bool(npc.get("canon")),
                "met": met,
                "disposition": int(getattr(relation, "disposition", 0) or 0),
                "first_met_day": int(getattr(relation, "first_met_day", 0) or 0),
                "portrait": shipped_art_url(npc_id, "portrait") if met else "",
            }
        )

    from engine.media.providers.shipped import load_manifest

    forms = [
        {
            "form": str(form),
            "portrait": shipped_art_url(str(form), "portrait"),
            "current": bool(
                state is not None
                and getattr(state.assistant_mind, "current_form", "") == form
            ),
        }
        for form in (load_manifest().get("assistant_forms") or {})
    ]
    return {"souls": souls, "forms": forms}


def codex_things(state: Any) -> list[dict[str, Any]]:
    """
    The Things. Everything the art pack knows about, priced where a vendor
    trades in it, and marked when the player is carrying one.
    """
    from engine.media.providers.shipped import load_manifest

    prices: dict[str, dict[str, Any]] = {}
    economy = _load_economy()
    for vendor_id, vendor in economy.items():
        for side in ("sells", "buys"):
            for item_id, row in (vendor.get(side) or {}).items():
                prices.setdefault(
                    str(item_id),
                    {
                        "name": str(row.get("name") or item_id),
                        "price": int(row.get("price", 0)),
                        "from": str(vendor_id).replace("npc_", "").title(),
                    },
                )

    carried = {i.id: i.qty for i in (getattr(state, "inventory", None) or [])}
    things: list[dict[str, Any]] = []
    for item_id in (load_manifest().get("items") or {}):
        row = prices.get(str(item_id), {})
        things.append(
            {
                "id": str(item_id),
                "name": str(row.get("name") or str(item_id).replace("_", " ").title()),
                "price": int(row.get("price", 0)),
                "from": str(row.get("from") or ""),
                "carried": int(carried.get(str(item_id), 0)),
                "image": shipped_art_url(str(item_id), "item"),
            }
        )
    return things


def _story_dir(key: str) -> Optional[Path]:
    """
    Resolve one ``paths.*`` key, or None when the story declares none.

    THE BUG THIS EXISTS FOR. These three loaders each passed a flagship
    repo-root literal as ``get_config().get``'s fallback and joined it onto
    ``project_root()``, with no guard on an empty value. Two failures came
    out of that once the engine's defaults were emptied:

      * a story declaring no items resolved the path to ``""`` and globbed
        ``*.yaml`` at the REPOSITORY ROOT, which is harmless only for as long
        as nobody puts a yaml file there;
      * ``_economy_prices`` logged "Economy unreadable" at WARNING on every
        call for a story that simply has no economy, which is not an error --
        it is an answer.

    The literal defaults were also dead by then: `engine/config.py` resolves a
    declared-but-empty key through the active story's manifest and deliberately
    ignores the caller's default, so the string here could never win. Removing
    them stops the next reader believing the flagship is the fallback.
    """
    from engine.config import project_root

    rel = str(get_config().get(key, "") or "").strip()
    if not rel:
        logger.debug("[default_api] Story declares no %s", key)
        return None
    candidate = Path(rel)
    return candidate if candidate.is_absolute() else (project_root() / candidate)


def _load_economy() -> dict[str, Any]:
    """
    The story's vendor economy, or {} when it declares none.

    Resolved through ``paths.economy`` like every other loader in this module.
    Two callers used to open ``project_root() / data/economy.yaml`` directly --
    the last two repo-root content literals in this file, left over from when
    the flagship's economy WAS at the repo root. A story with no economy is an
    answer (debug), not an error; an unreadable file it did declare is one
    (warning).
    """
    import yaml

    path = _story_dir("paths.economy")
    if path is None:
        return {}
    try:
        with path.open(encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
    except (OSError, yaml.YAMLError) as exc:
        logger.warning("[default_api] Economy unreadable: %s", exc)
        return {}
    return data if isinstance(data, dict) else {}


def _load_item_registry() -> dict[str, dict[str, Any]]:
    """
    The whole of data/items/*.yaml, keyed by item id.

    THE GAP THIS CLOSES: 74 items ship with a description, tags, a weight, a
    value and an art key, and the client rendered `name ×qty` because the
    browser cannot read YAML and no route handed it over. `/api/codex/things`
    was the closest thing, and it iterates the ART MANIFEST -- roughly 25 ids --
    so two thirds of the registry was unreachable from the UI entirely.

    Deliberately uncached. It is seven small files, read when an overlay opens,
    and a module-level cache here would survive a game activation (which
    repoints ``paths.items``) without anything to invalidate it.
    """
    import yaml

    from engine.config import project_root

    registry: dict[str, dict[str, Any]] = {}
    root = _story_dir("paths.items")
    if root is None or not root.is_dir():
        return registry
    for path in sorted(root.glob("*.yaml")):
        try:
            with path.open(encoding="utf-8") as handle:
                data = yaml.safe_load(handle) or {}
        except (OSError, yaml.YAMLError) as exc:
            # One malformed file costs one category, never the whole pack.
            logger.warning("[default_api] Item file unreadable (%s): %s", path, exc)
            continue
        for row in data.get("items") or []:
            if isinstance(row, dict) and row.get("id"):
                registry.setdefault(str(row["id"]), row)
    return registry


def _load_recipe_registry() -> dict[str, dict[str, Any]]:
    """Every recipe in data/recipes/*.yaml, keyed by id. Mirrors the loader in
    engine/skills/builtin/mechanics.py, which is private to that module."""
    import yaml

    recipes: dict[str, dict[str, Any]] = {}
    root = _story_dir("paths.recipes")
    if root is None or not root.is_dir():
        return recipes
    for path in sorted(root.glob("*.yaml")):
        try:
            with path.open(encoding="utf-8") as handle:
                data = yaml.safe_load(handle) or {}
        except (OSError, yaml.YAMLError) as exc:
            logger.warning("[default_api] Recipe file unreadable (%s): %s", path, exc)
            continue
        for row in data.get("recipes") or []:
            if isinstance(row, dict) and row.get("id"):
                recipes.setdefault(str(row["id"]), row)
    return recipes


def _economy_prices() -> dict[str, dict[str, Any]]:
    """item id -> {price, vendor} from data/economy.yaml, first vendor wins."""
    import yaml

    prices: dict[str, dict[str, Any]] = {}
    path = _story_dir("paths.economy")
    if path is None:
        return prices
    try:
        with path.open(encoding="utf-8") as handle:
            economy = yaml.safe_load(handle) or {}
    except (OSError, yaml.YAMLError) as exc:
        logger.warning("[default_api] Economy unreadable: %s", exc)
        return prices
    for vendor_id, vendor in economy.items():
        for side in ("sells", "buys"):
            for item_id, row in ((vendor or {}).get(side) or {}).items():
                prices.setdefault(
                    str(item_id),
                    {
                        "price": int((row or {}).get("price", 0)),
                        "vendor": str(vendor_id).replace("npc_", "").replace("_", " ").title(),
                    },
                )
    return prices


def item_catalog(state: Any) -> dict[str, Any]:
    """
    The pack: every registry item, with the player's carried count folded in.

    Everything the inventory panel needs to be a real inventory rather than a
    list of names -- picture, prose, tags, weight, value, and where it can be
    sold. Read-only: nothing here moves an item. Item movement is a turn, and
    the engine's own skills are the only writers.
    """
    registry = _load_item_registry()
    prices = _economy_prices()
    carried: dict[str, int] = {}
    if state is not None:
        for entry in getattr(state, "inventory", None) or []:
            carried[str(entry.id)] = carried.get(str(entry.id), 0) + int(entry.qty)

    def _row(item_id: str, row: dict[str, Any]) -> dict[str, Any]:
        tags = [str(t) for t in (row.get("tags") or [])]
        price = prices.get(item_id, {})
        return {
            "id": item_id,
            "name": str(row.get("name") or item_id.replace("_", " ").title()),
            "description": str(row.get("description") or "").strip(),
            "tags": tags,
            "weight": float(row.get("weight", 0) or 0),
            "value": int(row.get("value", 0) or 0),
            "stack": bool(row.get("stack", True)),
            # `art:` is the manifest key and is usually but not always the id.
            "image": shipped_art_url(str(row.get("art") or item_id), "item"),
            "carried": int(carried.get(item_id, 0)),
            "price": int(price.get("price", 0)),
            "vendor": str(price.get("vendor") or ""),
        }

    items = [_row(item_id, row) for item_id, row in registry.items()]

    # An id the player is holding that no YAML declares would otherwise vanish
    # from the pack entirely -- the player would be carrying something the UI
    # refuses to admit exists.
    for entry in getattr(state, "inventory", None) or []:
        if str(entry.id) not in registry:
            items.append(
                {
                    "id": str(entry.id),
                    "name": str(entry.name or entry.id),
                    "description": "",
                    "tags": ["unregistered"],
                    "weight": 0.0,
                    "value": 0,
                    "stack": True,
                    "image": shipped_art_url(str(entry.id), "item"),
                    "carried": int(entry.qty),
                    "price": 0,
                    "vendor": "",
                }
            )

    items.sort(key=lambda r: (-r["carried"], r["name"].lower()))
    tags = sorted({t for row in items for t in row["tags"]})
    held = [r for r in items if r["carried"] > 0]
    return {
        "items": items,
        "tags": tags,
        "gold": int(getattr(getattr(state, "stats", None), "gold", 0) or 0),
        "carried_count": sum(r["carried"] for r in held),
        # Encumbrance has no rules yet (see data/items/food.yaml), so this is
        # shown as a fact about the pack, never as a limit.
        "carried_weight": round(sum(r["weight"] * r["carried"] for r in held), 1),
        "location_id": str(getattr(state, "location_id", "") or ""),
    }


def recipe_book(state: Any) -> dict[str, Any]:
    """
    Every recipe, annotated with what the player is holding and where they are.

    `craft_item` and `list_recipes` have existed as engine skills with no way
    for a player to discover a single recipe id -- the Storyteller had to guess
    one unprompted. This is the discovery half; crafting itself still runs as a
    normal turn through the engine.
    """
    registry = _load_item_registry()
    held: dict[str, int] = {}
    for entry in getattr(state, "inventory", None) or []:
        held[str(entry.id)] = held.get(str(entry.id), 0) + int(entry.qty)
    here = str(getattr(state, "location_id", "") or "")

    def _name(item_id: str) -> str:
        row = registry.get(item_id) or {}
        return str(row.get("name") or item_id.replace("_", " ").title())

    def _ingredient(raw: Any) -> dict[str, Any]:
        entry = raw if isinstance(raw, dict) else {"id": raw}
        item_id = str(entry.get("id") or "")
        qty = int(entry.get("qty", 1) or 1)
        return {
            "id": item_id,
            "name": _name(item_id),
            "qty": qty,
            "have": int(held.get(item_id, 0)),
            "image": shipped_art_url(item_id, "item"),
        }

    recipes: list[dict[str, Any]] = []
    for recipe_id, row in _load_recipe_registry().items():
        station = str(row.get("station") or "")
        inputs = [_ingredient(i) for i in (row.get("inputs") or [])]
        tools = [_ingredient(t) for t in (row.get("tools") or [])]
        output = row.get("output") if isinstance(row.get("output"), dict) else {}
        recipes.append(
            {
                "id": recipe_id,
                "name": str(row.get("name") or recipe_id.replace("_", " ").title()),
                "category": str(row.get("category") or "craft"),
                "skill": str(row.get("skill") or "craft"),
                "band": str(row.get("band") or "standard"),
                "hours": float(row.get("hours", 1) or 1),
                "station": station,
                "here": not station or station == here,
                "inputs": inputs,
                "tools": tools,
                "output": {
                    "id": str(output.get("id") or ""),
                    "name": _name(str(output.get("id") or "")),
                    "qty": int(output.get("qty", 1) or 1),
                    "image": shipped_art_url(str(output.get("id") or ""), "item"),
                },
                "has_inputs": all(i["have"] >= i["qty"] for i in inputs),
                "has_tools": all(t["have"] >= 1 for t in tools),
            }
        )

    for row in recipes:
        # Exactly the three gates craft_item enforces, so the button never
        # promises something the engine is about to refuse.
        row["makeable"] = bool(row["here"] and row["has_inputs"] and row["has_tools"])

    recipes.sort(key=lambda r: (not r["makeable"], r["category"], r["name"].lower()))
    return {
        "location_id": here,
        "recipes": recipes,
        "categories": sorted({r["category"] for r in recipes}),
    }


def notice_board(state: Any) -> dict[str, Any]:
    """
    The notice board: what is posted in the square right now.

    docs/GOVERNANCE.md carried this in NOT WIRED as "the contract catalogue it
    would serve from exists; the render does not". The catalogue is
    ``data/tables/labour.yaml`` read through ``engine/game/economy.py``, and
    this is the server half of the render: every contract the engine would
    actually honour here, with its wage arithmetic attached, plus the jobs
    posted for other places so the board is a reason to travel.

    Presentation only. Taking a shift is a turn through the ``work`` skill,
    and ``economy.available`` has already filtered out anything the engine
    would refuse -- a board must never post work the player cannot take.
    """
    from engine.game import economy
    from engine.game.locations import get_location

    posted = economy.snapshot(state)
    here = str(getattr(state, "location_id", "") or "")
    return {
        "location_id": here,
        "location_name": str((get_location(here) or {}).get("name") or here),
        "configured": bool(posted.get("configured")),
        "phase": str(posted.get("phase") or ""),
        "shifts_worked_today": int(posted.get("shifts_worked_today", 0) or 0),
        "shifts_per_day": int(posted.get("shifts_per_day", 0) or 0),
        # The contracts the player could take right now, wage breakdown and
        # all -- economy.available's rows, unrewrapped, so the board and the
        # `query_work` skill can never disagree about what is on offer.
        "notices": list(posted.get("here") or []),
        "elsewhere": list(posted.get("elsewhere") or []),
    }


def trade_offer(state: Any) -> dict[str, Any]:
    """
    Who will barter with the player right now, and at what price.

    Presentation only: nothing here moves an item or a coin. The engine's
    `trade` skill is the single writer, and it runs inside a turn.
    """
    from engine.game.procgen import npcs_at_location

    economy = _load_economy()

    here = npcs_at_location(state.procgen, state.location_id)
    carried = {i.id: {"name": i.name, "qty": i.qty} for i in state.inventory}

    vendors: list[dict[str, Any]] = []
    for npc in here:
        npc_id = str(npc.get("id") or "")
        row = economy.get(npc_id)
        if not row:
            continue
        vendors.append(
            {
                "npc_id": npc_id,
                "name": str(npc.get("name") or npc_id),
                "role": str(npc.get("role") or "").replace("_", " "),
                "sells": [
                    {
                        "id": str(item_id),
                        "name": str(item.get("name") or item_id),
                        "price": int(item.get("price", 0)),
                        "image": shipped_art_url(str(item_id), "item"),
                    }
                    for item_id, item in (row.get("sells") or {}).items()
                ],
                # Only what the player is actually holding: an offer to sell
                # something you do not have is an offer the engine will refuse.
                "buys": [
                    {
                        "id": str(item_id),
                        "name": str(carried[str(item_id)]["name"]),
                        "price": int(item.get("price", 0)),
                        "qty": int(carried[str(item_id)]["qty"]),
                        "image": shipped_art_url(str(item_id), "item"),
                    }
                    for item_id, item in (row.get("buys") or {}).items()
                    if str(item_id) in carried
                ],
            }
        )

    return {
        "location": state.location_id,
        "gold": int(state.stats.gold),
        "vendors": vendors,
    }


# ---------------------------------------------------------------------------
# the blueprint
# ---------------------------------------------------------------------------


def story_blueprint(store: SessionStore, name: str = BLUEPRINT_NAME) -> Blueprint:
    """
    Build the engine's default story blueprint.

    Args:
        store: The scene's session registry. Every route here is read-only, but
            most of them read a live run.
        name: Blueprint name, in case a host app already has one.

    Returns:
        An unregistered Blueprint carrying the seven story screens.
    """
    blueprint = Blueprint(name, __name__)

    def _optional_session(session_id: str) -> Optional[GameSession]:
        try:
            return store.require(session_id) if session_id else None
        except KeyError:
            return None

    @blueprint.get("/api/quests")
    def api_quests() -> Any:
        """Quest journal: active objectives plus per-quest stage detail."""
        try:
            session = store.require(request.args.get("session_id", ""))
        except KeyError:
            return jsonify({"error": "session not found"}), 404
        return jsonify(quest_journal(session.engine.state))

    @blueprint.get("/api/codex/places")
    def api_codex_places() -> Any:
        session = _optional_session(request.args.get("session_id", ""))
        return jsonify(
            {
                "places": codex_places(
                    session.engine.state if session else None,
                    session.ledger if session else None,
                )
            }
        )

    @blueprint.get("/api/codex/souls")
    def api_codex_souls() -> Any:
        session = _optional_session(request.args.get("session_id", ""))
        return jsonify(
            codex_souls(
                session.engine.state if session else None,
                session.ledger if session else None,
            )
        )

    @blueprint.get("/api/codex/things")
    def api_codex_things() -> Any:
        session = _optional_session(request.args.get("session_id", ""))
        return jsonify({"things": codex_things(session.engine.state if session else None)})

    @blueprint.get("/api/items")
    def api_items() -> Any:
        """
        The full item registry, with carried counts when a session is given.

        data/items/*.yaml holds 74 items with prose, tags, weight and value
        and the browser cannot read YAML, so the inventory rendered
        `name ×qty`. Session-optional so the pack is still browsable from
        the title screen.
        """
        session = _optional_session(request.args.get("session_id", ""))
        return jsonify(item_catalog(session.engine.state if session else None))

    @blueprint.get("/api/recipes")
    def api_recipes() -> Any:
        """
        Every recipe, with what the player holds and whether it can be made.

        `craft_item` and `list_recipes` have been callable engine skills
        with no way for a player to learn a single recipe id.
        """
        session = _optional_session(request.args.get("session_id", ""))
        return jsonify(recipe_book(session.engine.state if session else None))

    @blueprint.get("/api/trade")
    def api_trade() -> Any:
        """Vendors standing where the player is, with prices and stock."""
        try:
            session = store.require(request.args.get("session_id", ""))
        except KeyError:
            return jsonify({"error": "session not found"}), 404
        return jsonify(trade_offer(session.engine.state))

    @blueprint.get("/api/notices")
    def api_notices() -> Any:
        """
        The notice board: posted contracts where the player stands.

        Session-required, because a board is meaningless without a location
        and a day -- every row's wage moves with standing, phase and the
        shifts already worked.
        """
        try:
            session = store.require(request.args.get("session_id", ""))
        except KeyError:
            return jsonify({"error": "session not found"}), 404
        return jsonify(notice_board(session.engine.state))

    @blueprint.get("/api/clues")
    def api_clues() -> Any:
        """
        What the PLAYER has worked out, as distinct from what is true.

        Session-required: a clue board is a record of one run. Without a
        session there is nothing to show, and showing every clue the story
        could ever yield would be the spoiler this screen exists to avoid.
        """
        try:
            session = store.require(request.args.get("session_id", ""))
        except KeyError:
            return jsonify({"error": "session not found"}), 404
        return jsonify({"clues": clue_board(session.engine.state, session.ledger)})

    return blueprint


__all__ = [
    "BLUEPRINT_NAME",
    "clue_board",
    "codex_places",
    "codex_souls",
    "codex_things",
    "item_catalog",
    "notice_board",
    "quest_journal",
    "recipe_book",
    "story_blueprint",
    "trade_offer",
]
