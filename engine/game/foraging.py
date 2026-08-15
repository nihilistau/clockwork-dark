"""
Foraging
========

Working the ground for what it will give. The repeatable food economy the game
shipped without.

THE SOFT-LOCK THIS MODULE CLOSES: ``scripts/simulate.py`` measured 62-79 deaths
per 200 turns before this landed, on every policy, and every one of them was
starvation. The only food in the game had a price; all three policies ended at
zero gold; a broke player starved, respawned, and starved again. That is not a
difficulty curve, it is a dead end, and docs/DESIGN_REVIEW.md filed it as R-05.

Meanwhile ``engine/game/procgen.py::_build_forest`` has generated a list of
forage nodes -- each with a resource, a seeded DC and a location -- since PR7,
and no code in this repository has ever read one. This module is that reader.

WHAT MAKES IT A DECISION RATHER THAN A BUTTON. Every one of these is a price
declared in data/tables/forage.yaml, not a constant here:

    hours        the evil clock eats every one of them
    stamina      which only rest returns, which costs more hours
    a check      against the node's own seeded DC, mapped to a band
    depletion    a worked node yields less and gets harder
    the season   winter is a bad joke and is meant to be
    the phase    a wood under `spreading` stops giving, which is how a
                 frontier village feels the evil before it can name it

DEPLETION WITHOUT A NEW SAVE FIELD. Node wear is held as a ``TimedEffect`` with
``kind="forage_node"`` -- a structure the save format, the transaction snapshot
and the clock's expiry sweep already handle. That last one is the trick: the
sweep in ``engine/game/clock.py`` IS the regrowth rule. Leave a node alone for
``recovery_days`` and the effect expires and the node is fresh; keep working it
and every use pushes the expiry forward, so it never recovers.

DETERMINISM. Every draw goes through ``world_rng(state, FORAGE)``. A seed
replays, and adding a forage roll cannot shift the caravan schedule or a
combat die, because the streams are independent by construction.

Version: v0.1.0 [2026-08-08]
"""

from __future__ import annotations

import logging
import random
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

import yaml

from engine.config import get_config
from engine.game import checks as checks_module
from engine.game import effects as effects_module
from engine.game import inventory as inventory_module
from engine.game.locations import get_location
from engine.game.rng import FORAGE, world_rng
from engine.game.state import GameState, TimedEffect

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parents[2]

#: TimedEffect.kind used for node wear. Not a check_penalty, so
#: engine/game/checks.py::gather_modifiers steps over it.
NODE_EFFECT_KIND = "forage_node"


def _round(value: float) -> int:
    """
    Round half away from zero.

    Python's builtin rounds half to even, so ``round(0.5) == 0``. Every number
    in this module is small -- one, two or three picks -- and banker's rounding
    on numbers that size turns a designer's 0.5 multiplier into "nothing at
    all" for exactly the cases a balance pass is looking at.
    """
    return int(value + 0.5) if value >= 0 else -int(-value + 0.5)


def _table_path() -> Optional[Path]:
    """The forage table, or None when this story declares no table directory."""
    rel = str(get_config().get("paths.tables", "") or "").strip()
    return (_ROOT / rel / "forage.yaml") if rel else None


@lru_cache(maxsize=8)
def _read_rules(path_str: str, _mtime: float) -> dict[str, Any]:
    """Parse forage.yaml, memoized on (path, mtime) so an edit invalidates."""
    try:
        with Path(path_str).open(encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}
    except (OSError, yaml.YAMLError) as exc:
        logger.warning("[forage] Unreadable table (operation=_read_rules): %s", exc)
        return {}


def load_rules() -> dict[str, Any]:
    """
    Load the forage table for the active game.

    A game with no forage table is not an error and must not log one: the
    Brass Coast is allowed to ship without foraging, in which case
    ``available`` reports False everywhere and the skill says so politely.
    """
    path = _table_path()
    if path is None:
        # A story with no tables at all forages nothing, and says so the same
        # polite way it does for a story that ships tables but no forage.yaml.
        logger.debug("[forage] Story declares no tables (operation=load_rules)")
        return {}
    try:
        mtime = path.stat().st_mtime
    except OSError:
        logger.info(
            "[forage] No forage table for this game (operation=load_rules, path=%s)",
            path,
        )
        return {}
    return _read_rules(str(path), mtime)


def configured() -> bool:
    """True when the active game ships a forage table with at least one row."""
    rules = load_rules()
    return bool(rules.get("tables")) and bool(rules.get("forage"))


def _cfg() -> dict[str, Any]:
    return load_rules().get("forage", {}) or {}


# ---------------------------------------------------------------------------
# season, place, node
# ---------------------------------------------------------------------------


def season_of(state: GameState) -> str:
    """
    Which season the world day falls in.

    Derived, never stored. The clock already owns time; a ``season`` field on
    GameState would be a second copy of the same number and would drift from it
    the first time anything set one without the other.
    """
    cfg = (_cfg().get("season") or {})
    order = [str(s) for s in (cfg.get("order") or ["spring"])]
    if not order:
        return "spring"
    span = max(1, int(cfg.get("days_each", 30) or 30))
    return order[((state.world_day - 1) // span) % len(order)]


def _season_mods(state: GameState) -> dict[str, Any]:
    cfg = (_cfg().get("season") or {}).get("modifiers") or {}
    return dict(cfg.get(season_of(state)) or {})


def location_tags(location_id: str) -> list[str]:
    """Tags declared for a place in data/world/locations.yaml."""
    return [str(t) for t in ((get_location(location_id) or {}).get("tags") or [])]


def forageable(location_id: str) -> bool:
    """True when a place's tags admit foraging at all."""
    if not configured():
        return False
    allowed = {str(t) for t in (_cfg().get("location_tags") or [])}
    return bool(allowed.intersection(location_tags(location_id)))


def _applicable_tables(location_id: str) -> list[dict[str, Any]]:
    """Every yield table whose tags intersect this location's tags."""
    here = set(location_tags(location_id))
    out = []
    for row in load_rules().get("tables") or []:
        if not isinstance(row, dict):
            continue
        if here.intersection(str(t) for t in (row.get("tags") or [])):
            out.append(row)
    return out


def nodes_at(state: GameState, location_id: str) -> list[dict[str, Any]]:
    """
    Forage nodes belonging to a place.

    The seeded pool comes from ``engine/game/procgen.py::_build_forest``, which
    stamps EVERY node with the same hardcoded ``location_id`` because it was
    written to furnish one clearing. Honouring that field would put all six
    nodes in forest_clearing -- which both strands every other forageable place
    in the graph and defeats depletion, since six nodes in one wood is a farm.
    It would also name a location that does not exist in the second game.

    So the field is ignored and the pool is DEALT: nodes go round-robin to the
    forageable places in id order. Deterministic (no RNG, no state), stable for
    a seed, and correct for any map.

    Args:
        state: Game state, read for its procgen snapshot.
        location_id: Place to look up.

    Returns:
        The node dicts assigned to that place. Empty when the place is not
        forageable or the world generated no nodes.
    """
    raw = [
        n
        for n in ((state.procgen.forest or {}).get("forage_nodes") or [])
        if isinstance(n, dict) and n.get("id")
    ]
    places = sorted(_all_forageable_places())
    if not raw or location_id not in places:
        return []
    index = places.index(location_id)
    return [n for i, n in enumerate(raw) if i % len(places) == index]


def _all_forageable_places() -> list[str]:
    from engine.game.locations import LOCATIONS

    return [loc_id for loc_id in LOCATIONS if forageable(loc_id)]


def _node_effect(state: GameState, node_id: str) -> Optional[TimedEffect]:
    return next(
        (
            e
            for e in state.active_effects
            if e.kind == NODE_EFFECT_KIND and e.id == f"forage:{node_id}"
        ),
        None,
    )


def node_uses(state: GameState, node_id: str) -> int:
    """How many times this node has been worked since it last recovered."""
    effect = _node_effect(state, node_id)
    return int(effect.delta) if effect else 0


def _wear_node(state: GameState, node_id: str) -> int:
    """
    Record one use, refreshing the recovery clock.

    Returns the new use count. Pushing ``expires_day`` forward on every use is
    what makes "you cannot farm one clearing forever" true: the node only
    forgets you while you are somewhere else.
    """
    days = max(1, int((_cfg().get("depletion") or {}).get("recovery_days", 6) or 6))
    effect = _node_effect(state, node_id)
    if effect is None:
        # Created through the one writer; the wear count below mutates the
        # record the writer handed back.
        effects_module.apply_effect(
            state,
            {
                "type": "timed_effect",
                "id": f"forage:{node_id}",
                "kind": NODE_EFFECT_KIND,
                "text": f"worked ground ({node_id})",
                "delta": 0,
                "expires_day": effects_module.duration_day(state, days),
            },
        )
        effect = _node_effect(state, node_id)
    effect.delta = int(effect.delta) + 1
    # `duration_day`, so `recovery_days: 1` means the node is worn TODAY and
    # fresh tomorrow. `world_day + days` kept it worn for two.
    effect.expires_day = effects_module.duration_day(state, days)
    return int(effect.delta)


def _band_for(dc: int) -> str:
    """Map a seeded node DC onto a difficulty band name."""
    for row in _cfg().get("bands") or []:
        if not isinstance(row, dict):
            continue
        upto = row.get("upto")
        if upto is None or dc <= int(upto):
            return str(row.get("band", "standard"))
    return "standard"


def _pick_node(state: GameState, location_id: str, node_id: str = "") -> Optional[dict[str, Any]]:
    """
    Choose which node the attempt works.

    Named ids win. Otherwise the least-worked node is taken, because that is
    what a person who lives here would do and it makes depletion a reason to
    walk further rather than a punishment for playing.
    """
    nodes = nodes_at(state, location_id)
    if not nodes:
        return None
    if node_id:
        named = next((n for n in nodes if str(n.get("id")) == node_id), None)
        if named is not None:
            return named
    return min(nodes, key=lambda n: (node_uses(state, str(n.get("id"))), str(n.get("id"))))


# ---------------------------------------------------------------------------
# hidden paths
# ---------------------------------------------------------------------------
#
# ``engine/game/procgen.py::_build_forest`` has generated two hidden paths per
# world -- each with a label, a destination and a seeded DC -- since PR7, and
# until now no code had ever read one (docs/DESIGN_REVIEW listed them beside
# the forage nodes this module already rescued). They are wired the same way:
# the seeded pool is dealt round-robin across the forageable places, a good
# survival roll while working the ground can notice one, and a noticed path is
# a real shortcut -- travel between its two ends costs SHORTCUT_HOURS whether
# or not the map draws a road there.

#: GameState.flags key prefix recording a discovered path. A flag rather than a
#: new save field: flags already serialize, and discovery is exactly the kind
#: of one-way fact the flag store exists for.
PATH_FLAG_PREFIX = "hidden_path_found:"

#: What a discovered path costs to walk. One hour: shorter than every forest
#: edge in the shipped map, which is what makes finding one worth the roll.
SHORTCUT_HOURS = 1


def hidden_paths(state: GameState) -> list[dict[str, Any]]:
    """The seeded path pool, as procgen minted it."""
    return [
        p
        for p in ((state.procgen.forest or {}).get("hidden_paths") or [])
        if isinstance(p, dict) and p.get("id")
    ]


def path_home(state: GameState, path_id: str) -> str:
    """
    Which place a path starts from.

    Dealt round-robin across the forageable places in id order -- the identical
    rule ``nodes_at`` uses, for the identical reason: procgen stamped no usable
    location on them, and the deal is deterministic for a seed with no RNG.
    """
    places = sorted(_all_forageable_places())
    if not places:
        return ""
    for index, path in enumerate(hidden_paths(state)):
        if str(path.get("id")) == str(path_id):
            return places[index % len(places)]
    return ""


def paths_at(state: GameState, location_id: str) -> list[dict[str, Any]]:
    """The hidden paths that start from one place, discovered or not."""
    return [
        p
        for p in hidden_paths(state)
        if path_home(state, str(p.get("id"))) == location_id
    ]


def path_discovered(state: GameState, path_id: str) -> bool:
    """True once a path has been found. Flags survive the save round-trip."""
    return bool(state.flags.get(f"{PATH_FLAG_PREFIX}{path_id}"))


def discovered_paths(state: GameState) -> list[dict[str, Any]]:
    """Every found path, with both ends attached. For the UI and the prompts."""
    out = []
    for path in hidden_paths(state):
        path_id = str(path.get("id"))
        if not path_discovered(state, path_id):
            continue
        out.append(
            {
                "id": path_id,
                "label": str(path.get("label") or "hidden path"),
                "from_id": path_home(state, path_id),
                "leads_to": str(path.get("leads_to") or ""),
                "hours": SHORTCUT_HOURS,
            }
        )
    return out


def shortcut_hours(state: GameState, from_id: str, to_id: str) -> Optional[int]:
    """
    Hours for this leg by a discovered hidden path, or None.

    Bidirectional on purpose -- a deer track you know runs both ways -- and
    only ever an improvement: the caller takes the smaller of this and the
    road, so a path can never make a trip longer.
    """
    for row in discovered_paths(state):
        if not row["from_id"] or not row["leads_to"]:
            continue
        if {from_id, to_id} == {row["from_id"], row["leads_to"]}:
            return SHORTCUT_HOURS
    return None


def _discover_path(
    state: GameState, location_id: str, result: Any
) -> Optional[dict[str, Any]]:
    """
    A good roll while working the ground can also notice a path.

    Reuses the forage attempt's own survival check rather than drawing again:
    the path's seeded DC (procgen mints 10-16) is the bar, and the roll already
    on the table either clears it or does not. Deterministic for a seed, and
    adding the feature cannot shift any RNG stream -- which is the whole of the
    stream discipline this module runs on.

    At most one path per attempt, easiest first: finding both ways out of the
    wood in one afternoon of mushroom-picking would cheapen both.
    """
    if not getattr(result, "success", False):
        return None
    candidates = sorted(
        (p for p in paths_at(state, location_id)
         if not path_discovered(state, str(p.get("id")))),
        key=lambda p: int(p.get("dc", 12) or 12),
    )
    for path in candidates:
        path_id = str(path.get("id"))
        if int(result.total) < int(path.get("dc", 12) or 12):
            continue
        from engine.game import effects as effects_module

        receipt = effects_module.apply_effect(
            state,
            {"type": "flag", "flag": f"{PATH_FLAG_PREFIX}{path_id}", "value": True},
        )
        label = str(path.get("label") or "hidden path")
        leads_to = str(path.get("leads_to") or "")
        logger.info(
            "[forage] Hidden path discovered (operation=_discover_path, "
            "path=%s, at=%s, leads_to=%s)",
            path_id,
            location_id,
            leads_to,
        )
        return {
            "id": path_id,
            "label": label,
            "from_id": location_id,
            "leads_to": leads_to,
            "hours": SHORTCUT_HOURS,
            "dc": int(path.get("dc", 12) or 12),
            "effect": receipt,
            "text": (
                f"Working the ground, you find a {label} -- "
                f"a quicker way through to {leads_to.replace('_', ' ')}."
            ),
        }
    return None


# ---------------------------------------------------------------------------
# yield draws
# ---------------------------------------------------------------------------


def _eligible(entries: list[Any], season: str) -> list[dict[str, Any]]:
    """Entries whose optional season filter admits the current season."""
    out = []
    for row in entries or []:
        if not isinstance(row, dict) or not row.get("item_id"):
            continue
        seasons = row.get("seasons")
        if seasons and season not in [str(s) for s in seasons]:
            continue
        out.append(row)
    return out


def _weighted(rng: random.Random, rows: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """One row, drawn by weight. None for an empty pool."""
    if not rows:
        return None
    weights = [max(0.0, float(r.get("weight", 1) or 0)) for r in rows]
    if sum(weights) <= 0:
        return rng.choice(rows)
    return rng.choices(rows, weights=weights, k=1)[0]


def _qty(rng: random.Random, row: dict[str, Any]) -> int:
    span = row.get("qty") or [1, 1]
    try:
        low, high = int(span[0]), int(span[-1])
    except (TypeError, ValueError, IndexError):
        return 1
    return rng.randint(min(low, high), max(low, high))


def preview(state: GameState, location_id: str = "") -> dict[str, Any]:
    """
    What foraging here would cost and roughly what it would give.

    Read-only: draws nothing, advances nothing, spends no RNG. This is what the
    UI and the Assistant should show before the player commits two hours.
    """
    location_id = location_id or state.location_id
    if not configured():
        return {"available": False, "reason": "This game has no foraging.", "location_id": location_id}
    if not forageable(location_id):
        return {
            "available": False,
            "reason": "There is nothing to forage here.",
            "location_id": location_id,
            "tags": location_tags(location_id),
        }

    node = _pick_node(state, location_id)
    if node is None:
        return {
            "available": False,
            "reason": "No forage ground has been found here.",
            "location_id": location_id,
        }

    cfg = _cfg()
    depletion = cfg.get("depletion") or {}
    uses = node_uses(state, str(node.get("id")))
    dc = int(node.get("dc", 10) or 10) + min(
        int(depletion.get("dc_cap", 5) or 5), int(depletion.get("dc_step", 1) or 1) * uses
    )
    season = season_of(state)
    return {
        "available": True,
        "location_id": location_id,
        "node_id": str(node.get("id")),
        "resource": str(node.get("resource") or ""),
        "difficulty": _band_for(dc),
        "effective_dc": dc,
        "skill": str(cfg.get("skill", "survival")),
        "hours": float(cfg.get("hours", 2.0) or 0.0),
        "stamina_cost": int(cfg.get("stamina_cost", 0) or 0),
        "season": season,
        "season_yield": float(_season_mods(state).get("yield", 1.0) or 1.0),
        "node_uses": uses,
        "depleted": uses > 0,
        "depletion_multiplier": round(depletion_multiplier(state, uses), 3),
        "expected_picks": {
            degree: max(0, _round(int(count) * depletion_multiplier(state, uses)))
            for degree, count in (cfg.get("picks") or {}).items()
        },
        "tables": [str(t.get("id")) for t in _applicable_tables(location_id)],
        "modifiers": _situational(state),
    }


def depletion_multiplier(state: GameState, uses: int) -> float:
    """
    How much of a fresh node's yield worked ground still gives.

    Applied to the PICK COUNT rather than to each stack size. Scaling stack
    sizes was tried first and is wrong at this scale: almost every table row
    yields one or two, and ``round(1 * 0.27)`` is zero, so a twice-worked node
    silently produced nothing on every degree including a critical success.
    Cutting picks instead means depletion costs you a draw, which is legible in
    the receipt and still leaves a good roll worth making.
    """
    depletion = _cfg().get("depletion") or {}
    step = float(depletion.get("yield_step", 0.65) or 0.65)
    floor = float(depletion.get("yield_floor", 0.25) or 0.0)
    return max(floor, step ** max(0, int(uses)))


def season_yield(state: GameState) -> float:
    """Seasonal multiplier on stack size. Winter is a bad joke by design."""
    return float(_season_mods(state).get("yield", 1.0) or 1.0)


def _situational(state: GameState) -> list[dict[str, Any]]:
    """
    The itemised season/daypart/phase modifiers applied to the check.

    Returned as a receipt rather than folded into one number, for the same
    reason engine/game/checks.py itemises its own: an engine-resolved failure
    reads as fair only when the player can see the whole arithmetic.
    """
    from engine.game import survival

    cfg = _cfg()
    rows: list[dict[str, Any]] = []
    season_delta = int(_season_mods(state).get("check", 0) or 0)
    if season_delta:
        rows.append({"label": season_of(state), "delta": season_delta})

    # Desperation. Deliberately positive, and deliberately shaped to offset the
    # global `starving` and `exhausted` penalties in data/rules/skills.yaml for
    # this one activity -- see the comment on `hunger:` in the forage table. A
    # penalty on the only unpaid food source in the game is a spiral, not a
    # difficulty curve.
    stage = survival.hunger_stage(state)
    hunger_delta = int((cfg.get("hunger") or {}).get(stage, 0) or 0)
    if hunger_delta:
        rows.append({"label": f"{stage}, and looking harder", "delta": hunger_delta})
    tod = int((cfg.get("time_of_day") or {}).get(state.time_of_day, 0) or 0)
    if tod:
        rows.append({"label": state.time_of_day, "delta": tod})
    phase = int((cfg.get("evil_phase") or {}).get(state.evil_phase.value, 0) or 0)
    if phase:
        rows.append({"label": f"the wood is {state.evil_phase.value}", "delta": phase})
    return rows


# ---------------------------------------------------------------------------
# the attempt
# ---------------------------------------------------------------------------


def forage(
    state: GameState,
    *,
    node_id: str = "",
    ledger: Optional[Any] = None,
) -> dict[str, Any]:
    """
    Spend hours and stamina working the ground here.

    Args:
        state: Mutable game state.
        node_id: Optional specific node. Omit to work the least-depleted one.
        ledger: Optional StoryLedger, forwarded to the check's boon/complication
            effects.

    Returns:
        Receipt dict: the check, the itemised modifiers, every item gained,
        the hours and stamina spent, the season, and the node's new wear. A
        refusal comes back as ``success: false`` with a message -- never an
        exception, because the caller may be a language model.
    """
    from engine.game.clock import advance_time

    if not configured():
        return {"success": False, "message": "There is no foraging in this story."}

    location_id = state.location_id
    if not forageable(location_id):
        return {
            "success": False,
            "location_id": location_id,
            "message": "There is nothing worth foraging here.",
        }

    node = _pick_node(state, location_id, node_id)
    if node is None:
        return {
            "success": False,
            "location_id": location_id,
            "message": "You find no ground here worth working.",
        }

    cfg = _cfg()
    depletion = cfg.get("depletion") or {}
    node_key = str(node.get("id"))
    uses_before = node_uses(state, node_key)

    hours = float(cfg.get("hours", 2.0) or 0.0)
    stamina_cost = int(cfg.get("stamina_cost", 0) or 0)

    # Time first, and unconditionally. A failed forage still costs you the
    # morning, or the attempt carries no risk and the decision is not a
    # decision. advance_time runs hunger, the evil ticker and expiry.
    if hours > 0:
        advance_time(state, hours)
    if stamina_cost:
        from engine.game import effects as effects_module

        effects_module.apply_effect(state, {"type": "stamina", "delta": -stamina_cost})

    raw_dc = int(node.get("dc", 10) or 10)
    worn_dc = raw_dc + min(
        int(depletion.get("dc_cap", 5) or 5), int(depletion.get("dc_step", 1) or 1) * uses_before
    )
    band = _band_for(worn_dc)
    situational = _situational(state)
    extra = sum(int(r["delta"]) for r in situational)

    result = checks_module.resolve(
        state,
        str(cfg.get("skill", "survival")),
        band,
        extra_mod=extra,
        ledger=ledger,
    )

    base_picks = int((cfg.get("picks") or {}).get(result.degree, 0) or 0)
    wear = depletion_multiplier(state, uses_before)
    picks = max(0, _round(base_picks * wear))
    bounty = season_yield(state)
    season = season_of(state)
    rng = world_rng(state, FORAGE)

    pools = _applicable_tables(location_id)
    common: list[dict[str, Any]] = []
    uncommon: list[dict[str, Any]] = []
    for table in pools:
        common.extend(_eligible(table.get("common") or [], season))
        uncommon.extend(_eligible(table.get("uncommon") or [], season))

    gained: dict[str, int] = {}
    for _ in range(picks):
        row = _weighted(rng, common)
        if row is None:
            break
        # A pick that landed always yields at least one. The season scales the
        # size of what a good pick gives; it must not be able to erase one.
        qty = max(1, _round(_qty(rng, row) * bounty))
        gained[str(row["item_id"])] = gained.get(str(row["item_id"]), 0) + qty

    # The chance at something better than food. Rolled once, on the degrees the
    # table allows, and it is the reason to walk out to the barrows rather than
    # picking the hedge behind the bakery.
    uncommon_cfg = cfg.get("uncommon") or {}
    rare_hit: Optional[str] = None
    if result.degree in [str(d) for d in (uncommon_cfg.get("degrees") or [])]:
        chance = float((uncommon_cfg.get("chance") or {}).get(result.degree, 0.0) or 0.0)
        if uncommon and picks and rng.random() < chance:
            row = _weighted(rng, uncommon)
            if row is not None:
                rare_hit = str(row["item_id"])
                gained[rare_hit] = gained.get(rare_hit, 0) + max(1, _qty(rng, row))

    applied = [inventory_module.grant(state, item_id, qty) for item_id, qty in gained.items()]

    # Only a productive attempt wears the ground. Failing to find anything has
    # already cost the hours; charging depletion on top would make a bad roll
    # punish the next attempt as well, which is two prices for one failure.
    uses_after = _wear_node(state, node_key) if gained else uses_before

    found = [
        {
            "item_id": item_id,
            "name": inventory_module.name_of(item_id),
            "qty": qty,
            "value": inventory_module.value_of(item_id),
            "uncommon": item_id == rare_hit,
        }
        for item_id, qty in gained.items()
    ]

    # A good roll can also notice one of procgen's hidden paths -- the seam
    # that makes the forest margin worth walking rather than a yield table.
    discovery = _discover_path(state, location_id, result)

    if found:
        text = "You come back with " + ", ".join(f"{f['qty']}x {f['name'].lower()}" for f in found) + "."
    elif result.degree == "failure":
        text = "Two hours of looking, and the ground gives you nothing."
    else:
        text = "Nothing here worth carrying."
    if discovery is not None:
        text = f"{text} {discovery['text']}"

    logger.info(
        "[forage] Worked ground (operation=forage, location=%s, node=%s, "
        "degree=%s, items=%s, uses=%s)",
        location_id,
        node_key,
        result.degree,
        len(found),
        uses_after,
    )

    return {
        "success": bool(found),
        "location_id": location_id,
        "node_id": node_key,
        "resource": str(node.get("resource") or ""),
        "check": result.to_dict(),
        "difficulty": band,
        "node_dc": raw_dc,
        "effective_dc": worn_dc,
        "situational": situational,
        "season": season,
        "picks": picks,
        "picks_before_depletion": base_picks,
        "depletion_multiplier": round(wear, 3),
        "season_yield": bounty,
        "found": found,
        "effects": applied,
        "hours": hours,
        "stamina_cost": stamina_cost,
        "stamina": state.stats.stamina,
        "hunger": round(state.hunger, 1),
        "node_uses": uses_after,
        "node_recovers_day": (
            _node_effect(state, node_key).expires_day if _node_effect(state, node_key) else 0
        ),
        "discovery": discovery,
        "world_day": state.world_day,
        "text": text,
    }


def snapshot(state: GameState) -> dict[str, Any]:
    """Every forageable place the player knows of, with its current state."""
    return {
        "configured": configured(),
        "season": season_of(state) if configured() else "",
        "here": preview(state),
        # Only what has been FOUND. The undiscovered pool must not reach a
        # prompt: a narrator told where the deer tracks are will hand the
        # player the forest without a single survival roll.
        "hidden_paths": discovered_paths(state),
        "places": [
            {
                "location_id": loc_id,
                "nodes": [
                    {
                        "id": str(n.get("id")),
                        "resource": str(n.get("resource") or ""),
                        "dc": int(n.get("dc", 10) or 10),
                        "uses": node_uses(state, str(n.get("id"))),
                    }
                    for n in nodes_at(state, loc_id)
                ],
            }
            for loc_id in sorted(_all_forageable_places())
        ]
        if configured()
        else [],
    }
