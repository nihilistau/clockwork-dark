"""
Thievery
========

Lifting a purse in a crowd, and the memory the goods carry afterwards.

``paths.thievery`` names ONE YAML file::

    alertness: {default: standard, watch: hard, captain: severe}
    purses:                       # by role; `default` required
      default: [{gold: [1, 4], weight: 4}, {item_id: brass_button, weight: 1}]
      steward: [{gold: [8, 20], weight: 3}, {item_id: signet_ring, weight: 1}]
    hot_days: 7                   # goods stay hot this many days

A lift is a stealth check against the mark's alertness (their ROLE's band, or
``default``). It is a moment, not an errand: it spends no time beyond whatever
``checks.resolve`` itself does, because a hand in a pocket is not an hour.

Everything taken is written through ``effects.apply_effect``: gold through the
``gold`` kind, an item through the ``item`` kind carrying ``stolen_from``,
which is what appends to ``state.provenance``. That record -- who, where, and
the day -- is what makes a ring HOT. Where the story also declares a Law, every
attempted lift is a ``pickpocket`` deed through ``law.commit_deed``: the receipt
gains ``seen_by`` (witness ids, for the engine) and ``reported``. Without one,
``noticed: True`` is only narrated.

Every content fault is a ValueError naming the file, for the reason
``premises.py`` gives: a purse row naming an item the registry lacks would
load, validate and lift nothing -- the inert shape this repo has shipped
before.

Version: v0.2.0 [2026-09-24]
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

import yaml

from engine.config import get_config
from engine.game.rng import THIEVERY, world_rng
from engine.game.state import GameState

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parents[2]
# The parsed, validated file. Registered in engine/games/caches.py: a story swap
# that kept it warm would pick one city's pockets with another's purses.
_SPEC_CACHE: Optional[dict[str, Any]] = None

#: The skill a lift rolls. Stealth, not a new skill: the taxonomy is canon.
LIFT_SKILL = "stealth"
#: Degrees at which the hand came away with something. A partial still took
#: coin, which is why it is here: reporting it as failed is the v0.8 `work`
#: mistake of calling a shift that happened one that did not.
_TOOK_SOMETHING = frozenset({"crit_success", "success", "partial"})
#: The Law's deed kind a lift commits. Named in the story's law file with its
#: severity; a story whose file omits it has decided a lifted purse is no crime.
PICKPOCKET_DEED = "pickpocket"


# ---------------------------------------------------------------------------
# Loading and validation
# ---------------------------------------------------------------------------


def _thievery_path() -> Optional[Path]:
    rel = str(get_config().get("paths.thievery", "") or "").strip()
    return (_ROOT / rel) if rel else None


def declared() -> bool:
    """Whether the running story declares thievery at all."""
    return _thievery_path() is not None


def _fail(path: Path, message: str) -> ValueError:
    return ValueError(f"thievery: {path}: {message}")


def _purse_row(path: Path, role: str, row: Any, items: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(row, dict):
        raise _fail(path, f"purse `{role}`: each row must be a mapping")
    try:
        weight = int(row.get("weight", 1))
    except (TypeError, ValueError):
        raise _fail(path, f"purse `{role}`: weight must be an integer") from None
    if weight <= 0:
        raise _fail(path, f"purse `{role}`: weight must be positive")
    has_gold, has_item = "gold" in row, "item_id" in row
    if has_gold == has_item:
        raise _fail(path, f"purse `{role}`: a row holds exactly one of `gold` or `item_id`")
    if has_gold:
        raw = row["gold"]
        if not (isinstance(raw, (list, tuple)) and len(raw) == 2):
            raise _fail(path, f"purse `{role}`: `gold` must be [low, high]")
        try:
            low, high = int(raw[0]), int(raw[1])
        except (TypeError, ValueError):
            raise _fail(path, f"purse `{role}`: `gold` bounds must be integers") from None
        if low < 0 or high < low:
            raise _fail(path, f"purse `{role}`: `gold` must be 0 <= low <= high")
        return {"gold": (low, high), "weight": weight}
    item_id = str(row["item_id"])
    if item_id not in items:
        raise _fail(path, f"purse `{role}`: unknown item `{item_id}`")
    return {"item_id": item_id, "weight": weight}


def load_spec() -> dict[str, Any]:
    """
    The parsed thievery file. Empty mappings for a story that declares none.

    Raises:
        ValueError: naming the file, for a declared-but-missing file, a band
            the check rules do not have, a missing ``default`` purse, an
            unknown item, or a malformed row.
    """
    global _SPEC_CACHE
    if _SPEC_CACHE is not None:
        return _SPEC_CACHE
    path = _thievery_path()
    if path is None:
        _SPEC_CACHE = {"alertness": {}, "purses": {}, "hot_days": 0}
        return _SPEC_CACHE
    if not path.is_file():
        # Declared and absent is a broken install: the story promised pockets.
        raise ValueError(f"thievery: declared file {path} does not exist")

    from engine.game.checks import load_skill_rules
    from engine.game.inventory import load_items

    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(doc, dict):
        raise _fail(path, "must be a mapping")

    bands = set((load_skill_rules().get("difficulty") or {}).keys())
    raw_alert = doc.get("alertness") or {}
    if not isinstance(raw_alert, dict):
        raise _fail(path, "`alertness` must map role -> band")
    alertness: dict[str, str] = {}
    for role, band in raw_alert.items():
        band = str(band).strip().lower()
        # An unknown band would fall back to the default inside checks with a
        # warning -- a captain quietly as easy to rob as anybody.
        if bands and band not in bands:
            raise _fail(path, f"alertness `{role}`: unknown band `{band}`")
        alertness[str(role)] = band

    raw_purses = doc.get("purses") or {}
    if not isinstance(raw_purses, dict) or "default" not in raw_purses:
        raise _fail(path, "`purses` must be a mapping with a `default` row list")
    items = load_items()
    purses: dict[str, list[dict[str, Any]]] = {}
    for role, rows in raw_purses.items():
        if not isinstance(rows, list) or not rows:
            raise _fail(path, f"purse `{role}` must be a non-empty list")
        purses[str(role)] = [_purse_row(path, str(role), row, items) for row in rows]

    try:
        hot_days = int(doc.get("hot_days", 7))
    except (TypeError, ValueError):
        raise _fail(path, "`hot_days` must be an integer") from None
    if hot_days < 0:
        raise _fail(path, "`hot_days` must not be negative")

    _SPEC_CACHE = {"alertness": alertness, "purses": purses, "hot_days": hot_days}
    return _SPEC_CACHE


def alertness_for(role: str) -> str:
    """The difficulty band a mark of this role lifts at."""
    alertness = load_spec()["alertness"]
    return str(alertness.get(role) or alertness.get("default") or "standard")


def purse_for(role: str) -> list[dict[str, Any]]:
    """The purse rows a mark of this role carries."""
    purses = load_spec()["purses"]
    return list(purses.get(role) or purses.get("default") or [])


# ---------------------------------------------------------------------------
# Marks
# ---------------------------------------------------------------------------


def _lifted_flag(npc_id: str, day: int) -> str:
    """The flag name recording a lift attempt on ``npc_id`` for ``day``.

    Controller ruling: a mark the player has already tried (success, partial
    or noticed) is not offered again the same in-game day -- lifting was
    otherwise free and unlimited, a real money exploit against a static
    purse. The flag is per-day so the same mark is fair game again once the
    clock turns over, same as a purse refilling overnight.
    """
    return f"lifted_{npc_id}_d{day}"


def marks(state: GameState) -> list[Any]:
    """
    Everyone the player could lift from right now: present here, awake, not
    already tried today.

    Nobody inside a house. A premise interior is somebody's home, where a hand
    in a pocket is a burglary, and burglary is a later feature with its own
    rules -- so an interior offers no marks rather than a cheap shortcut.

    ORDER. Scheduled cast (the named people in the story's schedule table)
    come first, generated household people after, mirroring the split
    `_npcs_present_block` in engine/agents/prompts.py already draws between
    the story's cast and procgen crowd -- reused here via
    `npc_sim.is_scheduled` rather than re-deriving it, so the two splits can
    never disagree. `_MAX_OPTIONS` in engine/game/intents.py then truncates;
    without this order a crowd over that cap silently dropped the named cast
    first, since procgen fills `known_npc_ids` ahead of the schedule.
    """
    from engine.world import npc_sim

    if not declared() or npc_sim.is_interior(state.location_id):
        return []
    present = [
        p
        for p in npc_sim.npcs_at(state, state.location_id)
        if p.available and not state.flags.get(_lifted_flag(p.npc_id, state.world_day))
    ]
    present.sort(key=lambda p: 0 if npc_sim.is_scheduled(p.npc_id) else 1)
    return present


# ---------------------------------------------------------------------------
# Lifting
# ---------------------------------------------------------------------------


def _draw(rng: Any, rows: list[dict[str, Any]]) -> dict[str, Any]:
    return rng.choices(rows, weights=[r["weight"] for r in rows], k=1)[0]


def lift(state: GameState, npc_id: str) -> dict[str, Any]:
    """
    Try to lift one mark's purse.

    ``ok`` means THE ATTEMPT HAPPENED -- success, partial, or a hand caught in
    the act. It is ``False`` only when the engine declines: thievery
    undeclared, the mark not here, asleep, or the player inside a house. A
    refusal rolls nothing and draws nothing. How it went is ``success`` and
    ``degree``; ``noticed`` is True on a failure and is the key the Law
    release will read.

    Returns:
        ``{"ok", "npc_id", "mark", "degree", "success", "noticed", "gold",
        "item_id", "item", "check"}`` on an attempt -- plus ``seen_by`` and
        ``reported`` where the story declares a Law, or ``{"ok": False,
        "message"}``.
    """
    from engine.game import checks, inventory
    from engine.game.effects import apply_effect
    from engine.world import law, npc_sim

    if not declared():
        return {"ok": False, "message": "there is nobody here to rob"}
    npc_id = str(npc_id)
    mark = npc_sim.display_name(npc_id, state)
    if npc_sim.is_interior(state.location_id):
        return {"ok": False, "mark": mark, "message": "not inside somebody's house"}
    presence = npc_sim.resolve_npc(state, npc_id)
    if presence is None or presence.location_id != state.location_id:
        return {"ok": False, "mark": mark, "message": f"{mark} is not here"}
    if not presence.available:
        return {"ok": False, "mark": mark, "message": f"{mark} is asleep, not in a crowd"}
    flag = _lifted_flag(npc_id, state.world_day)
    if state.flags.get(flag):
        return {"ok": False, "mark": mark, "message": f"{mark} is watching their purse now"}

    band = alertness_for(presence.role)
    check = checks.resolve(state, LIFT_SKILL, band)
    degree = str(check.degree)
    apply_effect(state, {"type": "flag", "flag": flag})
    receipt: dict[str, Any] = {
        "ok": True,
        "npc_id": npc_id,
        "mark": mark,
        "degree": degree,
        "success": degree in _TOOK_SOMETHING,
        "noticed": degree not in _TOOK_SOMETHING,
        "gold": 0,
        "item_id": "",
        "item": "",
        "check": check.to_dict(),
    }
    if law.declared():
        # A lift is the deed whether or not the hand came away full. A caught
        # hand is seen by its mark for certain; a clean one is not seen by its
        # mark at all -- the check already answered for them, and a receipt
        # saying "unnoticed" must not list the mark among the witnesses.
        # Everyone else rolls, the stealth margin shading their chance. Gated
        # so a story with thievery and no Law keeps a byte-identical receipt.
        seen = law.commit_deed(
            state,
            PICKPOCKET_DEED,
            margin=check.margin,
            certain=(npc_id,) if receipt["noticed"] else (),
            exclude=() if receipt["noticed"] else (npc_id,),
        )
        receipt["seen_by"] = seen["witnesses"]
        receipt["reported"] = seen["reported"]
    if receipt["noticed"]:
        logger.info("[thievery] Lift noticed (operation=lift, npc=%s, band=%s)", npc_id, band)
        return receipt

    rows = purse_for(presence.role)
    if degree == "partial":
        # A partial is a fumble for loose coin: gold only, halved. Drawn from
        # the gold rows alone, so a partial never becomes "nothing" merely
        # because the weights happened to land on the ring.
        rows = [r for r in rows if "gold" in r]
    if rows:
        rng = world_rng(state, THIEVERY)
        row = _draw(rng, rows)
        if "gold" in row:
            amount = rng.randint(*row["gold"])
            if degree == "partial":
                amount = max(1, amount // 2)
            if amount > 0:
                apply_effect(state, {"type": "gold", "delta": amount})
            receipt["gold"] = amount
        else:
            item_id = row["item_id"]
            apply_effect(
                state,
                {
                    "type": "item",
                    "item_id": item_id,
                    "qty": 1,
                    "name": inventory.name_of(item_id),
                    "tags": inventory.tags_of(item_id),
                    "stolen_from": {"whom": npc_id, "where": state.location_id},
                },
            )
            receipt["item_id"] = item_id
            receipt["item"] = inventory.name_of(item_id)
    # A partial against a purse with no coin in it took nothing; say so rather
    # than claim a success the inventory does not show.
    if not receipt["gold"] and not receipt["item_id"]:
        receipt["success"] = False
    logger.info(
        "[thievery] Lifted (operation=lift, npc=%s, degree=%s, gold=%s, item=%s)",
        npc_id,
        degree,
        receipt["gold"],
        receipt["item_id"] or "-",
    )
    return receipt


# ---------------------------------------------------------------------------
# Heat
# ---------------------------------------------------------------------------


def heat(state: GameState, item_id: str) -> str:
    """
    How dangerous an item is to be seen with: ``"hot"``, ``"cool"`` or ``""``.

    Hot while any theft of it is younger than ``hot_days``, or for as long as
    it carries the ``named`` tag -- a signet with a crest on it is recognised
    whenever it surfaces, which no amount of waiting fixes. Cool once every
    record has aged past ``hot_days``. Empty for an item never stolen.
    """
    from engine.game import inventory

    item_id = str(item_id)
    entries = state.provenance.get(item_id) or []
    carried = inventory.find(state, item_id)
    tags = inventory.tags_of(item_id, carried.tags if carried else None)
    if entries and "named" in tags:
        return "hot"
    if not entries:
        return ""
    hot_days = int(load_spec()["hot_days"])
    today = state.world_day
    if any(today - int(e.get("day", today)) < hot_days for e in entries):
        return "hot"
    return "cool"


def heat_split(state: GameState, item_id: str) -> dict[str, int]:
    """
    Per-unit breakdown of a carried stack: how many units are ``clean``
    (never stolen -- the stack simply holds more than it has records for),
    ``cool`` (stolen, every relevant record aged past ``hot_days``) and
    ``hot`` (stolen and still fresh, or the item is ``named`` and was ever
    stolen at all -- a crest does not fade).

    ``heat`` collapses a whole stack to its single worst answer, which is
    what let ``trade.quote``/``trade.sell`` apply one item's refusal or fence
    cut to an entire mixed stack: one clean unit and one stolen unit sold
    together had an honest vendor refuse BOTH, and a fence discount both.
    This is the per-unit answer those two now read instead.

    Capped at what is actually held: a non-sale removal (a complication, a
    theft back) does not touch ``state.provenance`` (see
    ``effects._e_remove_item``), so the record can outlive the unit it
    describes. The oldest records are the ones a sale would consume first
    (``effects._e_provenance``), so they are also the ones read here first.
    """
    from engine.game import inventory

    item_id = str(item_id)
    entries = state.provenance.get(item_id) or []
    carried = inventory.find(state, item_id)
    held = int(carried.qty) if carried else 0
    stolen = min(len(entries), max(0, held))
    clean = max(0, held - stolen)
    if stolen == 0:
        return {"clean": clean, "cool": 0, "hot": 0}

    tags = inventory.tags_of(item_id, carried.tags if carried else None)
    if "named" in tags:
        return {"clean": clean, "cool": 0, "hot": stolen}

    hot_days = int(load_spec()["hot_days"])
    today = state.world_day
    hot = sum(1 for e in entries[:stolen] if today - int(e.get("day", today)) < hot_days)
    return {"clean": clean, "cool": stolen - hot, "hot": hot}
