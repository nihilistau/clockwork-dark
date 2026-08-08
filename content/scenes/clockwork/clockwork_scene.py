"""
Clockwork Scene Server
======================

Flask + Socket.IO frontend for The Clockwork Dark.

Version: v0.1.0 [2026-06-20]
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from flask import jsonify, render_template, request, send_file
from flask_socketio import emit, join_room

from content.scenes.clockwork.clockwork_state import (
    SessionStore,
    resolve_player_action,
    run_turn,
)
from engine.config import get_config
from engine.game.engine import active_engine
from engine.media.stt import transcribe_audio
from engine.media.tts import AUDIO_DIR
from engine.persistence import MigrationError, get_save_store
from engine.scenes.flask_scene import FlaskScene

logger = logging.getLogger(__name__)

_SCENE_DIR = Path(__file__).resolve().parent

SCENE_METADATA = {
    "name": "clockwork",
    "display_name": "THE CLOCKWORK DARK",
    "port": 5573,
    "type": "rpg",
}

MEDIA_DIR = Path("data/media")

_store: Optional[SessionStore] = None
_scene: Optional["ClockworkScene"] = None


def _send_generated(root: Path, name: str) -> Any:
    """
    Serve a generated asset, refusing anything outside the root.

    Generated media lives outside static/ so the code tree stays clean, which
    means path traversal has to be rejected here rather than by Flask.
    """
    base = root.resolve()
    try:
        target = (base / name).resolve()
        target.relative_to(base)
    except (ValueError, OSError):
        return jsonify({"error": "not found"}), 404
    if not target.is_file():
        return jsonify({"error": "not found"}), 404
    return send_file(target, conditional=True)


# ---------------------------------------------------------------------------
# Reference data for the journal / codex / barter screens
#
# These read content and engine tables directly. They are deliberately pure
# functions of a (possibly absent) GameState so they can be unit-tested without
# a Flask request, and so a missing session degrades to the undiscovered view
# instead of an error page.
# ---------------------------------------------------------------------------


def shipped_art_url(
    subject_id: str,
    kind: str = "enemy",
    time_of_day: str = "day",
    evil_phase: str = "dormant",
) -> str:
    """
    Manifest key -> served URL, or "" when the pack has no picture for it.

    Only the *shipped* provider is consulted. peek() would fall through to the
    procedural generator, which writes a file to disk -- far too much work for
    a UI that is perfectly happy to fall back to the scene still.
    """
    if not subject_id:
        return ""
    try:
        from engine.media.providers.base import ImageRequest
        from engine.media.providers.shipped import ShippedArtProvider

        result = ShippedArtProvider().generate(
            ImageRequest(
                subject_id=subject_id,
                kind=kind,
                time_of_day=time_of_day,
                evil_phase=evil_phase,
            )
        )
        return result.url if result.url else ""
    except Exception as exc:  # noqa: BLE001 — a missing picture is not an error
        logger.debug("[clockwork_scene] Art lookup failed for %s: %s", subject_id, exc)
        return ""


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


def codex_places(state: Any) -> list[dict[str, Any]]:
    """
    The Atlas. Every canonical location, gated on having been there.

    Undiscovered places still appear -- the shape of the map is not a secret,
    only what is in it -- but carry no picture and no description.
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

    places: list[dict[str, Any]] = []
    for place_id, row in LOCATIONS.items():
        discovered = not state or place_id in visited
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
                ],
            }
        )
    return places


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
    import yaml

    from engine.config import project_root
    from engine.media.providers.shipped import load_manifest

    prices: dict[str, dict[str, Any]] = {}
    try:
        with (project_root() / "data" / "economy.yaml").open(encoding="utf-8") as handle:
            economy = yaml.safe_load(handle) or {}
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
    except (OSError, yaml.YAMLError) as exc:
        logger.warning("[clockwork_scene] Economy unreadable: %s", exc)

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

    root = project_root() / str(get_config().get("paths.items", "data/items"))
    registry: dict[str, dict[str, Any]] = {}
    if not root.is_dir():
        return registry
    for path in sorted(root.glob("*.yaml")):
        try:
            with path.open(encoding="utf-8") as handle:
                data = yaml.safe_load(handle) or {}
        except (OSError, yaml.YAMLError) as exc:
            # One malformed file costs one category, never the whole pack.
            logger.warning("[clockwork_scene] Item file unreadable (%s): %s", path, exc)
            continue
        for row in data.get("items") or []:
            if isinstance(row, dict) and row.get("id"):
                registry.setdefault(str(row["id"]), row)
    return registry


def _load_recipe_registry() -> dict[str, dict[str, Any]]:
    """Every recipe in data/recipes/*.yaml, keyed by id. Mirrors the loader in
    engine/skills/builtin/mechanics.py, which is private to that module."""
    import yaml

    from engine.config import project_root

    root = project_root() / str(get_config().get("paths.recipes", "data/recipes"))
    recipes: dict[str, dict[str, Any]] = {}
    if not root.is_dir():
        return recipes
    for path in sorted(root.glob("*.yaml")):
        try:
            with path.open(encoding="utf-8") as handle:
                data = yaml.safe_load(handle) or {}
        except (OSError, yaml.YAMLError) as exc:
            logger.warning("[clockwork_scene] Recipe file unreadable (%s): %s", path, exc)
            continue
        for row in data.get("recipes") or []:
            if isinstance(row, dict) and row.get("id"):
                recipes.setdefault(str(row["id"]), row)
    return recipes


def _economy_prices() -> dict[str, dict[str, Any]]:
    """item id -> {price, vendor} from data/economy.yaml, first vendor wins."""
    import yaml

    from engine.config import project_root

    prices: dict[str, dict[str, Any]] = {}
    try:
        path = project_root() / str(get_config().get("paths.economy", "data/economy.yaml"))
        with path.open(encoding="utf-8") as handle:
            economy = yaml.safe_load(handle) or {}
    except (OSError, yaml.YAMLError) as exc:
        logger.warning("[clockwork_scene] Economy unreadable: %s", exc)
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


def trade_offer(state: Any) -> dict[str, Any]:
    """
    Who will barter with the player right now, and at what price.

    Presentation only: nothing here moves an item or a coin. The engine's
    `trade` skill is the single writer, and it runs inside a turn.
    """
    import yaml

    from engine.config import project_root
    from engine.game.procgen import npcs_at_location

    try:
        with (project_root() / "data" / "economy.yaml").open(encoding="utf-8") as handle:
            economy = yaml.safe_load(handle) or {}
    except (OSError, yaml.YAMLError) as exc:
        logger.warning("[clockwork_scene] Economy unreadable: %s", exc)
        economy = {}

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
# Player-facing engine settings
#
# THE GAP THIS CLOSES: config/default.yaml carries ~25 knobs a player has a
# legitimate opinion about -- whether narration is spoken, whether images are
# generated during a turn, how fast the dark spreads -- and the only way to
# touch any of them was to edit a checked-in YAML by hand. The Settings panel
# shipped four localStorage toggles, none of which reached the engine.
#
# The whitelist below is the entire contract. A key not named here cannot be
# written by any request, so a malicious or malformed body cannot repoint
# `paths.saves`, disable the evil ticker's clamp, or inject a service command
# line. Every value is type-checked and clamped to its declared domain before
# it is written, and writes go to config/local.yaml -- gitignored, the layer
# the config manager already documents as machine-local, and one that
# engine/config.py ignores wholesale if it ever fails to parse.
# ---------------------------------------------------------------------------

# type: bool | int | float | enum | text
SETTING_SPECS: tuple[dict[str, Any], ...] = (
    # -- pace ------------------------------------------------------------
    {
        "key": "world.evil_base_rate_per_day",
        "label": "How fast the dark spreads",
        "group": "Pace",
        "type": "float",
        "min": 0.001,
        "max": 0.02,
        "step": 0.001,
        "restart": False,
        "hint": (
            "The difficulty slider. 0.006 reaches CONSUMING near day 130; "
            "0.012 does it in half that; below 0.003 the world is still quiet "
            "at day 40 and the premise evaporates."
        ),
        "marks": {"0.003": "Slow", "0.006": "Measured", "0.012": "Hunted"},
    },
    {
        "key": "world.tick_interval_seconds",
        "label": "Background tick",
        "group": "Pace",
        "type": "int",
        "min": 15,
        "max": 600,
        "restart": True,
        "hint": "Real seconds between world simulation ticks.",
    },
    # -- voice -----------------------------------------------------------
    {
        "key": "tts.enabled",
        "label": "Speak the narration",
        "group": "Voice",
        "type": "bool",
        "restart": False,
        "hint": (
            "Off by default on measurement, not taste: this machine "
            "synthesizes about 21x slower than realtime, so a full paragraph "
            "costs minutes."
        ),
    },
    {
        "key": "tts.assistant_enabled",
        "label": "Speak the Assistant",
        "group": "Voice",
        "type": "bool",
        "restart": False,
        "hint": "Its lines are one to three sentences — the only speech worth waiting for.",
    },
    {
        "key": "tts.voice",
        "label": "Voice",
        "group": "Voice",
        "type": "enum",
        "options": ["neutral_male", "neutral_female", "warm_female", "old_male"],
        "restart": False,
        "hint": "Whatever your Voxtral build ships. An unknown name falls back to text.",
    },
    {
        "key": "tts.euler_steps",
        "label": "Synthesis quality",
        "group": "Voice",
        "type": "int",
        "min": 1,
        "max": 12,
        "restart": False,
        "hint": "Higher is better and much slower. 3 is the measured floor that still sounds human.",
    },
    # -- pictures --------------------------------------------------------
    {
        "key": "media.live_generation",
        "label": "Generate pictures during play",
        "group": "Pictures",
        "type": "bool",
        "restart": False,
        "hint": (
            "Off, the shipped art pack answers instantly. On, a turn waits for "
            "the provider — minutes on Grok, seconds on ComfyUI."
        ),
    },
    {
        "key": "media.image_provider",
        "label": "Picture provider",
        "group": "Pictures",
        "type": "enum",
        "options": ["grokbuild", "comfyui", "procedural"],
        "restart": False,
        "hint": "Only consulted when live generation is on.",
    },
    {
        "key": "media.cutscene_budget",
        "label": "Cutscene budget",
        "group": "Pictures",
        "type": "enum",
        "options": ["phase_shift_only", "unlimited"],
        "restart": True,
        "hint": "One cutscene per evil phase, or as many as the story asks for.",
    },
    {
        "key": "media.cutscene_skip_after_seconds",
        "label": "Skippable after",
        "group": "Pictures",
        "type": "int",
        "min": 0,
        "max": 60,
        "restart": False,
        "hint": "Seconds before a cutscene will let you out of it. 0 means immediately.",
    },
    # -- the companion ---------------------------------------------------
    {
        "key": "awareness.reveal_threshold",
        "label": "Awareness before it will speak plainly",
        "group": "The companion",
        "type": "int",
        "min": 0,
        "max": 100,
        "restart": False,
        "hint": "Below this the Assistant answers in weather and omens.",
    },
    {
        "key": "awareness.reflection_form_min",
        "label": "Awareness before the reflection",
        "group": "The companion",
        "type": "int",
        "min": 0,
        "max": 100,
        "restart": False,
        "hint": "The fifth form is gated: it cannot appear until you have seen enough.",
    },
    {
        "key": "awareness.spoiler_gate_threshold",
        "label": "Lore spoiler gate",
        "group": "The companion",
        "type": "int",
        "min": 0,
        "max": 100,
        "restart": False,
        "hint": "Lore above this awareness is withheld from the prompt entirely.",
    },
    {
        "key": "assistant.max_tokens",
        "label": "How much it may say",
        "group": "The companion",
        "type": "int",
        "min": 60,
        "max": 600,
        "restart": False,
        "hint": "Tokens per line. It is a presence, not a chat window.",
    },
    # -- the model -------------------------------------------------------
    {
        "key": "lmstudio.profiles.big.model",
        "label": "Narration model",
        "group": "The model",
        "type": "text",
        "maxlength": 120,
        "restart": True,
        "hint": "Empty means discover one by capability from LM Studio. Otherwise an exact model id.",
    },
    {
        "key": "lmstudio.profiles.big.temperature",
        "label": "Narration temperature",
        "group": "The model",
        "type": "float",
        "min": 0.0,
        "max": 2.0,
        "step": 0.05,
        "restart": False,
    },
    {
        "key": "lmstudio.profiles.big.max_tokens",
        "label": "Narration token cap",
        "group": "The model",
        "type": "int",
        "min": 512,
        "max": 8000,
        "restart": False,
        "hint": "Covers reasoning AND prose combined. Too low and thinking eats the whole answer.",
    },
    {
        "key": "lmstudio.profiles.big.reasoning",
        "label": "Let it think out loud",
        "group": "The model",
        "type": "enum",
        "options": ["on", "off"],
        "restart": False,
        "hint": "On feeds the live reasoning panel. Off is faster and blanker.",
    },
    {
        "key": "lmstudio.context_tokens",
        "label": "Context window",
        "group": "The model",
        "type": "int",
        "min": 2048,
        "max": 131072,
        "restart": True,
        "hint": "Fallback only — the real number comes from the loaded model.",
    },
    {
        "key": "lmstudio.prefer_native",
        "label": "Use LM Studio's native endpoint",
        "group": "The model",
        "type": "bool",
        "restart": True,
        "hint": "The only transport that can actually turn reasoning off. Leave on unless it misbehaves.",
    },
)

SETTINGS_BY_KEY: dict[str, dict[str, Any]] = {s["key"]: s for s in SETTING_SPECS}

_LOCAL_CONFIG = Path("config") / "local.yaml"


def _dig(node: Any, dotted: str) -> Any:
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def _plant(root: dict[str, Any], dotted: str, value: Any) -> None:
    """Set a dotted key, creating intermediate dicts. Never replaces a dict."""
    parts = dotted.split(".")
    node = root
    for part in parts[:-1]:
        child = node.get(part)
        if not isinstance(child, dict):
            child = {}
            node[part] = child
        node = child
    node[parts[-1]] = value


def _local_overrides() -> dict[str, Any]:
    """Whatever config/local.yaml currently holds, or {} if it is absent or bad."""
    import yaml

    from engine.config import project_root

    path = project_root() / _LOCAL_CONFIG
    if not path.is_file():
        return {}
    try:
        with path.open(encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
    except (OSError, yaml.YAMLError) as exc:
        logger.warning("[clockwork_scene] local.yaml unreadable: %s", exc)
        return {}
    return data if isinstance(data, dict) else {}


def settings_view() -> dict[str, Any]:
    """Every player-settable knob, its live value, and whether it is overridden."""
    cfg = get_config()
    overrides = _local_overrides()
    rows: list[dict[str, Any]] = []
    for spec in SETTING_SPECS:
        row = dict(spec)
        row["value"] = cfg.get(spec["key"])
        row["overridden"] = _dig(overrides, spec["key"]) is not None
        rows.append(row)
    return {
        "settings": rows,
        # Order is presentation, but it is stable order: a settings panel whose
        # groups reshuffle between loads is unusable.
        "groups": list(dict.fromkeys(s["group"] for s in SETTING_SPECS)),
        "config_path": str(_LOCAL_CONFIG).replace("\\", "/"),
    }


def _coerce_setting(spec: dict[str, Any], raw: Any) -> tuple[bool, Any, str]:
    """
    Validate one value against its spec.

    Returns (accepted, value, note). A number outside its range is CLAMPED and
    accepted with a note rather than rejected: the point of the whitelist is
    that no reachable value can brick a run, so the safe move is to land on the
    nearest legal one, not to hand back an error the player cannot act on.
    """
    kind = spec["type"]
    try:
        if kind == "bool":
            if isinstance(raw, str):
                return True, raw.strip().lower() in ("1", "true", "yes", "on"), ""
            return True, bool(raw), ""
        if kind in ("int", "float"):
            value = int(raw) if kind == "int" else float(raw)
            if value != value or value in (float("inf"), float("-inf")):
                return False, None, "not a finite number"
            low, high = spec.get("min"), spec.get("max")
            clamped = value
            if low is not None:
                clamped = max(low, clamped)
            if high is not None:
                clamped = min(high, clamped)
            note = "" if clamped == value else f"clamped to {clamped}"
            return True, (int(clamped) if kind == "int" else round(float(clamped), 6)), note
        if kind == "enum":
            value = str(raw)
            if value not in spec.get("options", []):
                return False, None, f"not one of {', '.join(spec.get('options', []))}"
            return True, value, ""
        if kind == "text":
            value = str(raw).strip()[: int(spec.get("maxlength", 120))]
            # A model id is an identifier, never a path or a shell fragment.
            if any(c in value for c in "\n\r\t\\'\"$`;|&<>"):
                return False, None, "contains characters an identifier cannot have"
            return True, value, ""
    except (TypeError, ValueError):
        return False, None, f"not a valid {kind}"
    return False, None, "unknown setting type"


def apply_settings(changes: dict[str, Any], *, reset: bool = False) -> dict[str, Any]:
    """
    Merge validated changes into config/local.yaml and reload the config.

    Only whitelisted keys are ever touched, so machine-specific values already
    in local.yaml (service roots, API hosts) survive untouched. The file is
    written to a sibling temp path and moved into place, so a crash mid-write
    cannot leave a half-parsed config behind -- and even if one somehow did,
    engine/config.py logs and ignores an unparseable layer rather than dying.
    """
    import yaml

    from engine.config import project_root, reset_config

    overrides = _local_overrides()
    applied: dict[str, Any] = {}
    rejected: dict[str, str] = {}
    notes: dict[str, str] = {}

    if reset:
        # Remove only OUR keys. Anything else in the file is somebody's machine.
        for key in SETTINGS_BY_KEY:
            parts = key.split(".")
            node = overrides
            for part in parts[:-1]:
                node = node.get(part) if isinstance(node.get(part), dict) else {}
            if isinstance(node, dict):
                node.pop(parts[-1], None)
    else:
        for key, raw in (changes or {}).items():
            spec = SETTINGS_BY_KEY.get(str(key))
            if spec is None:
                rejected[str(key)] = "not a settable key"
                continue
            ok, value, note = _coerce_setting(spec, raw)
            if not ok:
                rejected[str(key)] = note
                continue
            _plant(overrides, str(key), value)
            applied[str(key)] = value
            if note:
                notes[str(key)] = note

    path = project_root() / _LOCAL_CONFIG
    temp = path.with_suffix(".yaml.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with temp.open("w", encoding="utf-8") as handle:
            handle.write(
                "# Machine-local config overrides. Gitignored.\n"
                "# The game's Settings panel writes the keys it owns here;\n"
                "# anything else in this file is yours and is left alone.\n\n"
            )
            yaml.safe_dump(overrides, handle, sort_keys=True, allow_unicode=True)
        temp.replace(path)
    except OSError as exc:
        logger.error("[clockwork_scene] Could not write %s: %s", path, exc)
        return {
            "ok": False,
            "error": f"could not write {_LOCAL_CONFIG}: {exc}",
            "applied": {},
            "rejected": rejected,
        }

    # Drops the config singleton AND every cache keyed off it, so a changed
    # path or rate is live on the next turn rather than the next launch.
    reset_config()

    restart_needed = sorted(
        k for k in applied if SETTINGS_BY_KEY[k].get("restart")
    )
    logger.info(
        "[clockwork_scene] Settings written (operation=apply_settings, keys=%s)",
        sorted(applied) or "reset",
    )
    return {
        "ok": True,
        "applied": applied,
        "rejected": rejected,
        "notes": notes,
        "restart_needed": restart_needed,
        **settings_view(),
    }


def get_store() -> SessionStore:
    global _store
    if _store is None:
        _store = SessionStore()
    return _store


def reset_store() -> SessionStore:
    """Clear sessions — for tests."""
    global _store
    _store = SessionStore()
    return _store


class ClockworkScene(FlaskScene):
    """Clockwork Dark play scene."""

    def __init__(self, *, testing: bool = False, llm_fn: Any = None) -> None:
        self.llm_fn = llm_fn
        self.store = get_store()
        super().__init__(
            name="clockwork",
            static_folder=_SCENE_DIR / "static",
            template_folder=_SCENE_DIR / "templates",
            testing=testing,
        )

    def register(self) -> None:
        app = self.app
        socketio = self.socketio

        # Game catalogue: GET /api/games, /api/games/active, /api/games/<slug>.
        # Lives in engine/games so the registry owns its own serialization
        # rather than the scene reaching into it.
        from engine.games.api import games_blueprint

        app.register_blueprint(games_blueprint())

        # Activate the default game at startup. The launcher does this for a
        # CLI run, but the scene is also constructed directly by tests and by
        # any other host -- and without it the registry sits inactive, so
        # /api/games/active reported a slug with a null manifest and every
        # content path still resolved through the un-overlaid config.
        try:
            from engine.games.registry import ActivationError, active, peek

            if peek() is None:
                active()
        except ActivationError as exc:
            logger.error(
                "[clockwork_scene] No game could be activated "
                "(operation=register): %s",
                exc,
            )
        except ImportError:
            pass

        @app.get("/")
        def index() -> str:
            return render_template("clockwork.html", scene=SCENE_METADATA)

        @app.post("/api/game/new")
        def api_new_game() -> Any:
            body = request.get_json(silent=True) or {}
            session = self.store.create(
                player_name=str(body.get("player_name", "Traveler")),
                archetype=str(body.get("archetype", "wayfarer")),
                seed=body.get("seed"),
                llm_fn=self.llm_fn,
            )
            payload = {
                "session_id": session.session_id,
                "save_id": session.save_id,
                "state": session.engine.state.to_client_dict(),
                "opening": session.last_turn,
            }
            return jsonify(payload)

        @app.get("/api/game/state")
        def api_get_state() -> Any:
            session_id = request.args.get("session_id", "")
            try:
                session = self.store.require(session_id)
            except KeyError:
                return jsonify({"error": "session not found"}), 404
            return jsonify({"state": session.engine.state.to_client_dict()})

        # -- read-only reference APIs (P10 screens) ----------------------
        #
        # The journal, the codex and the barter overlay all need content the
        # browser cannot see: quest definitions, the location graph, procgen
        # NPCs, economy prices and data/art/manifest.yaml. None of it belongs
        # in to_client_dict() -- it is static reference material, not turn
        # state, and shipping it on every turn would bloat every payload.
        #
        # Every route here is a GET that mutates nothing. `session_id` is
        # optional: without a session the codex degrades to "show everything"
        # rather than 404ing, so the screens are still browsable from a menu.

        def _optional_session(session_id: str) -> Any:
            try:
                return self.store.require(session_id) if session_id else None
            except KeyError:
                return None

        @app.get("/api/quests")
        def api_quests() -> Any:
            """Quest journal: active objectives plus per-quest stage detail."""
            try:
                session = self.store.require(request.args.get("session_id", ""))
            except KeyError:
                return jsonify({"error": "session not found"}), 404
            return jsonify(quest_journal(session.engine.state))

        @app.get("/api/codex/places")
        def api_codex_places() -> Any:
            session = _optional_session(request.args.get("session_id", ""))
            return jsonify({"places": codex_places(session.engine.state if session else None)})

        @app.get("/api/codex/souls")
        def api_codex_souls() -> Any:
            session = _optional_session(request.args.get("session_id", ""))
            return jsonify(
                codex_souls(
                    session.engine.state if session else None,
                    session.ledger if session else None,
                )
            )

        @app.get("/api/codex/things")
        def api_codex_things() -> Any:
            session = _optional_session(request.args.get("session_id", ""))
            return jsonify({"things": codex_things(session.engine.state if session else None)})

        @app.get("/api/metrics")
        def api_metrics() -> Any:
            """
            What the agents are actually doing, as numbers.

            Exists so the Assistant and the prompts can be tuned against data
            instead of vibes. The most useful series is `unearned_claims`: the
            governance chain records every stat delta the model asserted with no
            tool receipt behind it, and a stat that keeps appearing there is a
            prompt defect that is otherwise completely invisible -- the engine
            drops the claim silently and correctly, and nobody ever finds out
            the model kept trying.

            Process-wide and unpersisted; these are numbers about this run of
            the server, not about a save.
            """
            from engine.telemetry import get_oracle

            oracle = get_oracle()
            return jsonify({"metrics": oracle.metrics(), "recent": oracle.recent(20)})

        @app.get("/api/items")
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

        @app.get("/api/recipes")
        def api_recipes() -> Any:
            """
            Every recipe, with what the player holds and whether it can be made.

            `craft_item` and `list_recipes` have been callable engine skills
            with no way for a player to learn a single recipe id.
            """
            session = _optional_session(request.args.get("session_id", ""))
            return jsonify(recipe_book(session.engine.state if session else None))

        @app.get("/api/settings")
        def api_get_settings() -> Any:
            """Player-settable engine config: spec, live value, override state."""
            return jsonify(settings_view())

        @app.post("/api/settings")
        def api_put_settings() -> Any:
            """
            Persist whitelisted settings into config/local.yaml.

            Not a game mutation: nothing here touches a GameState. Unknown keys
            are refused and numbers are clamped to their declared domain, so no
            body a client can send makes a run unplayable.
            """
            body = request.get_json(silent=True) or {}
            result = apply_settings(
                body.get("changes") or {},
                reset=bool(body.get("reset")),
            )
            return jsonify(result), (200 if result.get("ok") else 500)

        @app.get("/api/art")
        def api_art() -> Any:
            """
            Resolve a manifest art key to a URL.

            The client cannot read data/art/manifest.yaml, so an encounter's
            `art: "wolf"` was unrenderable without this. Returns an empty url
            rather than 404 so the caller falls back to its own visual instead
            of logging a failed request every turn.
            """
            return jsonify({"url": shipped_art_url(
                request.args.get("id", ""),
                request.args.get("kind", "enemy"),
                request.args.get("time_of_day", "day"),
                request.args.get("evil_phase", "dormant"),
            )})

        @app.get("/api/trade")
        def api_trade() -> Any:
            """Vendors standing where the player is, with prices and stock."""
            try:
                session = self.store.require(request.args.get("session_id", ""))
            except KeyError:
                return jsonify({"error": "session not found"}), 404
            return jsonify(trade_offer(session.engine.state))

        @app.get("/api/saves")
        def api_list_saves() -> Any:
            return jsonify({"saves": [s.to_dict() for s in get_save_store().list_saves()]})

        @app.post("/api/saves")
        def api_write_save() -> Any:
            body = request.get_json(silent=True) or {}
            try:
                session = self.store.require(str(body.get("session_id", "")))
            except KeyError:
                return jsonify({"error": "session not found"}), 404
            save_id = get_save_store().save(
                session.engine.state,
                save_id=body.get("save_id") or None,
                slot=str(body.get("slot", "1")),
            )
            return jsonify({"save_id": save_id})

        @app.post("/api/saves/<save_id>/load")
        def api_load_save(save_id: str) -> Any:
            try:
                session = self.store.resume(save_id, llm_fn=self.llm_fn)
            except FileNotFoundError:
                return jsonify({"error": "save not found"}), 404
            except MigrationError as exc:
                return jsonify({"error": str(exc)}), 409
            return jsonify(
                {
                    "session_id": session.session_id,
                    "save_id": save_id,
                    "state": session.engine.state.to_client_dict(),
                }
            )

        @app.delete("/api/saves/<save_id>")
        def api_delete_save(save_id: str) -> Any:
            return jsonify({"deleted": get_save_store().delete(save_id)})

        @app.get("/api/audio/<path:name>")
        def api_audio(name: str) -> Any:
            """Serve synthesized narration. Generated audio never lives in static/."""
            return _send_generated(AUDIO_DIR, name)

        @app.get("/api/media/<path:name>")
        def api_media(name: str) -> Any:
            """Serve generated stills and portraits."""
            return _send_generated(MEDIA_DIR, name)

        @app.post("/api/game/choice")
        def api_choice() -> Any:
            body = request.get_json(silent=True) or {}
            session_id = str(body.get("session_id", ""))
            try:
                session = self.store.require(session_id)
            except KeyError:
                return jsonify({"error": "session not found"}), 404

            action = resolve_player_action(
                session,
                str(body.get("choice_id", "")),
                body.get("custom_text"),
            )
            turn = run_turn(session, action)
            return jsonify(turn)

        @app.post("/api/voice/transcribe")
        def api_transcribe() -> Any:
            session_id = request.form.get("session_id", "")
            audio = request.files.get("audio")
            if audio is None:
                return jsonify({"error": "audio file required"}), 400
            try:
                session = self.store.require(session_id)
            except KeyError:
                return jsonify({"error": "session not found"}), 404

            audio_bytes = audio.read()
            with active_engine(session.engine):
                # Transcribe once. This used to call transcribe_audio here AND
                # again inside process_voice_input -- two full ASR round trips
                # per push-to-talk, which could disagree with each other.
                stt = transcribe_audio(audio_bytes)
                assistant = session.assistant.process_voice_input(
                    audio_bytes,
                    scene_context=session.last_turn.get("narration", ""),
                    transcript=stt.get("transcript", ""),
                )
            return jsonify({"stt": stt, "assistant": assistant.to_dict()})

        @socketio.on("connect")
        def on_connect() -> None:
            logger.debug("[clockwork_scene] Client connected (operation=connect)")

        @socketio.on("join_session")
        def on_join(data: dict[str, Any]) -> None:
            session_id = str(data.get("session_id", ""))
            if session_id:
                join_room(session_id)
                try:
                    session = self.store.require(session_id)
                    emit(
                        "game_started",
                        {
                            "session_id": session_id,
                            "save_id": session.save_id,
                            "state": session.engine.state.to_client_dict(),
                            "opening": session.last_turn,
                        },
                    )
                except KeyError:
                    emit("error", {"message": "session not found"})

        @socketio.on("player_choice")
        def on_player_choice(data: dict[str, Any]) -> None:
            session_id = str(data.get("session_id", ""))
            try:
                session = self.store.require(session_id)
            except KeyError:
                emit("turn_error", {"message": "session not found", "fatal": True})
                return

            def _emit(event: str, payload: dict[str, Any]) -> None:
                emit(event, payload, room=session_id)

            # One turn at a time per session. The client also guards, but a
            # double-click or a reconnect race must not reach the engine.
            if not session.lock.acquire(blocking=False):
                emit("turn_error", {"message": "A turn is already in progress."})
                return

            try:
                action = resolve_player_action(
                    session,
                    str(data.get("choice_id", "")),
                    data.get("custom_text"),
                )
                run_turn(session, action, emit_callback=_emit)
            except Exception as exc:  # noqa: BLE001 — last line of defence
                # Without this the handler raised into Socket.IO, no event was
                # emitted, and the client's busy flag never cleared: every
                # button disabled forever with no message on screen.
                logger.exception(
                    "[clockwork_scene] Turn failed (operation=player_choice, id=%s)",
                    session_id,
                )
                emit(
                    "turn_error",
                    {"message": f"The turn could not be completed: {exc}"},
                )
            finally:
                session.lock.release()

        @socketio.on("resume")
        def on_resume(data: dict[str, Any]) -> None:
            """Rehydrate a run from its save after a reconnect."""
            save_id = str(data.get("save_id", ""))
            if not save_id:
                emit("resume_failed", {"message": "save_id required"})
                return
            try:
                session = self.store.resume(save_id, llm_fn=self.llm_fn)
            except (FileNotFoundError, MigrationError) as exc:
                emit("resume_failed", {"message": str(exc)})
                return
            join_room(session.session_id)
            emit(
                "game_resumed",
                {
                    "session_id": session.session_id,
                    "save_id": save_id,
                    "state": session.engine.state.to_client_dict(),
                    # BUG THIS FIXES: game_resumed shipped no `opening` at all,
                    # and the client's reducer reads narration, choices and the
                    # scene still out of exactly that key. Every reload restored
                    # the run into a screen with no choices -- see
                    # clockwork_state.resume_opening for the other half.
                    "opening": session.last_turn,
                },
            )


def create_app(
    *,
    testing: bool = False,
    llm_fn: Any = None,
) -> tuple[ClockworkScene, Any]:
    """
    Application factory for tests and launcher.

    Returns:
        (ClockworkScene instance, Flask app)
    """
    global _scene
    _scene = ClockworkScene(testing=testing, llm_fn=llm_fn)
    return _scene, _scene.app


def run_scene(*, host: Optional[str] = None, port: Optional[int] = None) -> None:
    """Start clockwork scene from launcher."""
    cfg = get_config()
    scene_cfg = cfg.get("scene.clockwork", {}) or {}
    resolved_host = host or str(scene_cfg.get("host", "0.0.0.0"))
    resolved_port = int(port or scene_cfg.get("port", SCENE_METADATA["port"]))
    scene, _ = create_app()
    logger.info(
        "[clockwork_scene] Starting (operation=run_scene, host=%s, port=%s)",
        resolved_host,
        resolved_port,
    )
    scene.run(host=resolved_host, port=resolved_port)