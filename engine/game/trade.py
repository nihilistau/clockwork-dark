"""
Trade
=====

Deterministic prices, a real spread, and a haggle the engine resolves.

THE BUG THIS MODULE CLOSES: ``engine/skills/builtin/mechanics.py::trade``
priced exclusively off the ``buys:``/``sells:`` rows in data/economy.yaml. That
made buying work and selling INERT -- and selling is the common case. A vendor
with no ``buys`` row for an item refused it outright, so a forageful of
mushrooms, a hide handed over by a quest and a brass shard dug out of a barrow
were all worth exactly nothing to every person in the world. Meanwhile
``data/items/*.yaml`` has carried a ``value`` in copper for every item since P9
and no runtime code had ever read it.

Now every item has a price with everyone who deals in that kind of thing, and
``data/economy.yaml`` is an OVERRIDE layer over a derived market rather than
the whole of it.

FOUR THINGS MOVE A PRICE, and each is in data/tables/trade.yaml, itemised in
every quote so a receipt can show the arithmetic:

    the spread     what a vendor asks over value and pays under it
    reputation     ``engine/game/reputation.py::price_multiplier``, at last
                   given something to price
    scarcity       by item tag, per evil phase. A `spreading` world is one
                   where food costs half again and salvage is worth less, so
                   the player feels the clock in their purse
    the haggle     what today's argument achieved, capped at the vendor's
                   reservation price

WHY THERE IS NO SESSION OBJECT. "Offer, counter, accept" reads like it wants a
mutable session, and a mutable session wants a new field on ``GameState``,
which wants a save migration and a redaction rule and a rollback story. It
does not need any of that, because a counter can be a PURE FUNCTION of the
state. The one thing that must persist -- what today's haggle achieved with
this vendor -- is stored as a ``TimedEffect`` with ``kind="haggle"``, a
structure the save format, the transaction snapshot and the clock's expiry
sweep already handle. The expiry sweep is the rule that a bargain lasts a day.

So: ``quote`` is the counter, always re-derivable and never invented by the
narrator. ``haggle`` moves it, once per vendor per day, at the risk of moving
it the wrong way. ``buy`` and ``sell`` execute at the standing quote.

Version: v0.1.0 [2026-08-08]
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

import yaml

from engine.config import get_config
from engine.game import checks as checks_module
from engine.game import effects as effects_module
from engine.game import inventory as inventory_module
from engine.game import reputation as reputation_module
from engine.game.state import GameState, TimedEffect

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parents[2]

#: TimedEffect.kind holding today's agreed movement off the spread, in
#: percentage points. Not a check_penalty, so gather_modifiers steps over it.
HAGGLE_EFFECT_KIND = "haggle"

BUY = "buy"
SELL = "sell"


def _table_path() -> Optional[Path]:
    """The trade table, or None when this story declares no table directory."""
    rel = str(get_config().get("paths.tables", "") or "").strip()
    return (_ROOT / rel / "trade.yaml") if rel else None


@lru_cache(maxsize=8)
def _read_rules(path_str: str, _mtime: float) -> dict[str, Any]:
    try:
        with Path(path_str).open(encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}
    except (OSError, yaml.YAMLError) as exc:
        logger.warning("[trade] Unreadable table (operation=_read_rules): %s", exc)
        return {}


def load_rules() -> dict[str, Any]:
    """
    Load the trade table for the active game.

    Absent is a supported configuration: without it every vendor falls back to
    the raw ``data/economy.yaml`` rows, which is exactly the behaviour that
    shipped before this module and is therefore a safe floor rather than a
    broken game.
    """
    path = _table_path()
    if path is None:
        logger.debug("[trade] Story declares no tables (operation=load_rules)")
        return {}
    try:
        mtime = path.stat().st_mtime
    except OSError:
        logger.info("[trade] No trade table for this game (path=%s)", path)
        return {}
    return _read_rules(str(path), mtime)


def _cfg() -> dict[str, Any]:
    return load_rules().get("trade", {}) or {}


@lru_cache(maxsize=8)
def _read_economy(path_str: str, _mtime: float) -> dict[str, Any]:
    try:
        with Path(path_str).open(encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}
    except (OSError, yaml.YAMLError) as exc:
        logger.warning("[trade] Unreadable economy (operation=_read_economy): %s", exc)
        return {}


def load_economy() -> dict[str, Any]:
    """
    Vendor stock overrides from ``paths.economy``.

    A story that declares no economy has no prices of its own, and must not be
    given another story's: this used to default to the flagship's
    ``data/economy.yaml``, which is how a fae court came to quote Edgewood's
    bread prices.
    """
    rel = str(get_config().get("paths.economy", "") or "").strip()
    if not rel:
        logger.debug("[trade] Story declares no economy (operation=load_economy)")
        return {}
    path = _ROOT / rel
    try:
        mtime = path.stat().st_mtime
    except OSError:
        logger.info("[trade] No economy file (operation=load_economy, path=%s)", path)
        return {}
    return _read_economy(str(path), mtime)


def vendors() -> dict[str, dict[str, Any]]:
    """Declared vendors, keyed by npc id."""
    return {
        str(k): dict(v)
        for k, v in (load_rules().get("vendors") or {}).items()
        if isinstance(v, dict)
    }


def vendor(npc_id: str) -> dict[str, Any]:
    """
    One vendor's profile, merging the trade table with the economy stock.

    An npc present in data/economy.yaml but absent from the trade table still
    trades -- on the global spread, with no faction and no tag filter. That is
    deliberate: adding a vendor must not require editing two files, and a
    second game that ships only an economy file must still have shops.
    """
    profile = dict(vendors().get(str(npc_id)) or {})
    stock = dict(load_economy().get(str(npc_id)) or {})
    profile["sells"] = dict(stock.get("sells") or {})
    profile["buys"] = dict(stock.get("buys") or {})
    profile["known"] = bool(profile.get("faction") or stock)
    return profile


def vendor_location(npc_id: str) -> str:
    """Where a vendor keeps their counter, or an empty string."""
    return str(vendor(npc_id).get("location") or "")


def vendors_at(location_id: str) -> list[str]:
    """Every vendor whose counter is at a place."""
    return sorted(k for k, v in vendors().items() if str(v.get("location") or "") == location_id)


# ---------------------------------------------------------------------------
# the standing bargain
# ---------------------------------------------------------------------------


def _haggle_effect(state: GameState, npc_id: str) -> Optional[TimedEffect]:
    marker = f"haggle:{npc_id}"
    effect = next(
        (e for e in state.active_effects if e.kind == HAGGLE_EFFECT_KIND and e.id == marker),
        None,
    )
    # A record from a previous day is stale but may not have been swept yet
    # (the sweep runs on the clock, not on read). Treat it as absent.
    if effect is not None and effect.expires_day < state.world_day:
        return None
    return effect


def haggle_points(state: GameState, npc_id: str) -> int:
    """Percentage points moved off the spread by today's argument. Signed."""
    effect = _haggle_effect(state, npc_id)
    return int(effect.delta) if effect else 0


def haggle_attempts(state: GameState, npc_id: str) -> int:
    """How many times the player has tried it on with this vendor today."""
    effect = _haggle_effect(state, npc_id)
    if effect is None:
        return 0
    try:
        return int(str(effect.text).rsplit(":", 1)[-1])
    except (TypeError, ValueError):
        return 1


def _record_haggle(state: GameState, npc_id: str, points: int, attempts: int) -> None:
    marker = f"haggle:{npc_id}"
    effect = next(
        (e for e in state.active_effects if e.kind == HAGGLE_EFFECT_KIND and e.id == marker),
        None,
    )
    if effect is None:
        # Created through the one writer; the fields below overwrite the
        # record the writer handed back with today's argument.
        effects_module.apply_effect(
            state,
            {
                "type": "timed_effect",
                "id": marker,
                "kind": HAGGLE_EFFECT_KIND,
                "expires_day": state.world_day,
            },
        )
        effect = next(
            e
            for e in state.active_effects
            if e.kind == HAGGLE_EFFECT_KIND and e.id == marker
        )
    effect.delta = int(points)
    effect.text = f"haggle:{npc_id}:{attempts}"
    effect.expires_day = state.world_day


# ---------------------------------------------------------------------------
# pricing
# ---------------------------------------------------------------------------


def _spread(npc_id: str, side: str) -> float:
    """Vendor spread for a side, falling back to the global one."""
    default = float((_cfg().get("spread") or {}).get(side, 1.0 if side == BUY else 0.5) or 1.0)
    override = (vendor(npc_id).get("spread") or {}).get(side)
    try:
        return float(override) if override is not None else default
    except (TypeError, ValueError):
        return default


def scarcity_multiplier(state: GameState, item_id: str) -> float:
    """
    Tag-driven price pressure for the current evil phase.

    The highest matching tag wins rather than the product of them: an item that
    is both ``food`` and ``material`` is priced as the scarcer of the two, not
    as the two multiplied together, which compounds to nonsense on anything
    carrying three tags.
    """
    table = (_cfg().get("scarcity") or {}).get(state.evil_phase.value) or {}
    if not table:
        return 1.0
    hits = [
        float(table[tag])
        for tag in inventory_module.tags_of(item_id)
        if tag in table
    ]
    if not hits:
        return 1.0
    return max(hits, key=lambda m: abs(m - 1.0))


def deals_in(npc_id: str, item_id: str) -> bool:
    """
    Whether a vendor will touch this kind of thing at all.

    An explicit ``buys``/``sells`` row always wins: a stock list is a statement
    of intent that outranks a tag filter.
    """
    profile = vendor(npc_id)
    if item_id in profile.get("buys", {}) or item_id in profile.get("sells", {}):
        return True
    never = {str(t) for t in (_cfg().get("never_traded_tags") or [])}
    tags = set(inventory_module.tags_of(item_id))
    if never.intersection(tags):
        return False
    allowed = profile.get("deals_in")
    if allowed is None:
        return True
    return bool(tags.intersection(str(t) for t in allowed))


def quote(
    state: GameState,
    npc_id: str,
    item_id: str,
    side: str = BUY,
    qty: int = 1,
) -> dict[str, Any]:
    """
    The price this vendor is standing behind right now, with its whole receipt.

    This IS the counter-offer in the offer/counter/accept loop: it is a pure
    function of the state, so it can be recomputed on demand, cannot be
    invented by the narrator, and is what ``buy`` and ``sell`` execute at.

    Args:
        state: Game state. Not mutated.
        npc_id: Vendor npc id.
        item_id: Item being traded.
        side: ``buy`` (player pays) or ``sell`` (player receives).
        qty: How many.

    Returns:
        Dict with ``ok``, ``unit_price``, ``total``, and an itemised
        ``breakdown``. ``ok`` is False with a ``reason`` when the vendor will
        not deal in the item at all.
    """
    side = SELL if str(side).lower() == SELL else BUY
    qty = max(1, int(qty))
    profile = vendor(npc_id)

    if not profile.get("known"):
        return {"ok": False, "npc_id": npc_id, "reason": f"Nobody trades here as {npc_id}."}
    if not deals_in(npc_id, item_id):
        return {
            "ok": False,
            "npc_id": npc_id,
            "item_id": item_id,
            "reason": f"{profile.get('name', npc_id)} does not deal in that.",
        }

    listed = (profile.get("sells") if side == BUY else profile.get("buys")) or {}
    listed_price = listed.get(item_id, {}).get("price") if isinstance(listed.get(item_id), dict) else None

    base_value = inventory_module.value_of(item_id)
    spread = _spread(npc_id, side)

    if listed_price is not None:
        # An explicit stock row is the vendor's own number and wins over the
        # derived one. This is what keeps data/economy.yaml meaningful and what
        # stops a rebalance of `value` silently repricing every shop.
        base = float(listed_price)
        source = "stock list"
    else:
        base = base_value * spread
        source = "registry value"

    faction = str(profile.get("faction") or "")
    faction_mult = (
        reputation_module.price_multiplier(state, faction) if faction else 1.0
    )
    # Reputation charges the player on a buy and pays them on a sell, so the
    # same number is inverted between the sides. Reading it one way on both
    # would mean being trusted made your sales worse.
    standing_mult = faction_mult if side == BUY else round(2.0 - faction_mult, 3)

    scarcity = scarcity_multiplier(state, item_id)
    # Scarcity moves both sides together: a dear loaf is dear to buy AND worth
    # more to sell, which is what makes a shortage tradeable rather than a tax.
    points = haggle_points(state, npc_id)
    haggle_mult = 1.0 - (points / 100.0) if side == BUY else 1.0 + (points / 100.0)

    unit = base * standing_mult * scarcity * haggle_mult

    if side == BUY:
        unit_price = max(1, int(unit + 0.5)) if base_value or listed_price else 1
    else:
        floor = int(_cfg().get("min_sale_price", 1) or 0)
        unit_price = int(unit)
        if base_value > 0 or listed_price:
            unit_price = max(floor, unit_price)
        else:
            # A worthless thing is worthless. Quest items land here and this is
            # where they should: nobody buys somebody else's business.
            unit_price = 0

    return {
        "ok": True,
        "npc_id": npc_id,
        "vendor": str(profile.get("name") or npc_id),
        "item_id": item_id,
        "item_name": inventory_module.name_of(item_id),
        "side": side,
        "qty": qty,
        "unit_price": unit_price,
        "total": unit_price * qty,
        "breakdown": {
            "base": round(base, 2),
            "base_source": source,
            "registry_value": base_value,
            "spread": spread if listed_price is None else None,
            "faction": faction,
            "standing": reputation_module.standing(state, faction) if faction else "",
            "standing_multiplier": round(standing_mult, 3),
            "scarcity_multiplier": round(scarcity, 3),
            "evil_phase": state.evil_phase.value,
            "haggle_points": points,
            "haggle_multiplier": round(haggle_mult, 3),
        },
        "summary": (
            f"{profile.get('name', npc_id)}: {qty}x {inventory_module.name_of(item_id)} "
            f"{'costs' if side == BUY else 'fetches'} {unit_price * qty}c "
            f"({unit_price}c each)"
        ),
    }


def browse(state: GameState, npc_id: str) -> dict[str, Any]:
    """
    Everything this vendor sells, priced, plus what they would pay for what the
    player is carrying.

    The second half is the point: the old ``trade("browse")`` returned the raw
    ``buys``/``sells`` blocks, so a player could not find out what their own
    inventory was worth without offering each item one at a time and being
    refused.
    """
    profile = vendor(npc_id)
    if not profile.get("known"):
        return {"ok": False, "npc_id": npc_id, "reason": f"Nobody trades here as {npc_id}."}

    sells = []
    for item_id in sorted(profile.get("sells", {})):
        row = quote(state, npc_id, item_id, BUY, 1)
        if row.get("ok"):
            sells.append(
                {
                    "item_id": item_id,
                    "name": row["item_name"],
                    "price": row["unit_price"],
                    "affordable": state.stats.gold >= row["unit_price"],
                }
            )

    offers = []
    for entry in state.inventory:
        row = quote(state, npc_id, entry.id, SELL, entry.qty)
        if not row.get("ok") or row["unit_price"] <= 0:
            continue
        offers.append(
            {
                "item_id": entry.id,
                "name": row["item_name"],
                "qty": entry.qty,
                "unit_price": row["unit_price"],
                "total": row["total"],
            }
        )

    return {
        "ok": True,
        "npc_id": npc_id,
        "vendor": str(profile.get("name") or npc_id),
        "location_id": str(profile.get("location") or ""),
        "faction": str(profile.get("faction") or ""),
        "standing": (
            reputation_module.standing(state, str(profile["faction"]))
            if profile.get("faction")
            else ""
        ),
        "gold": int(state.stats.gold),
        "sells": sells,
        "will_buy": sorted(offers, key=lambda r: -r["total"]),
        "haggle_points": haggle_points(state, npc_id),
        "haggle_attempts_left": max(
            0,
            int((_cfg().get("haggle") or {}).get("attempts_per_day", 1) or 0)
            - haggle_attempts(state, npc_id),
        ),
    }


# ---------------------------------------------------------------------------
# haggling
# ---------------------------------------------------------------------------


def _band_for_greed(percent: float) -> str:
    """Difficulty band from how far past the standing quote the offer reaches."""
    for row in (_cfg().get("haggle") or {}).get("bands") or []:
        if not isinstance(row, dict):
            continue
        upto = row.get("upto")
        if upto is None or percent <= float(upto):
            return str(row.get("band", "standard"))
    return "standard"


def haggle(
    state: GameState,
    npc_id: str,
    item_id: str,
    side: str = BUY,
    offer: int = 0,
    *,
    ledger: Optional[Any] = None,
) -> dict[str, Any]:
    """
    Argue about the price. One attempt per vendor per day.

    The player names a price; the engine works out how greedy that is against
    the standing quote, sets the difficulty band from it, rolls, and moves the
    day's price by the degree. A fumbled haggle moves it the WRONG way and the
    vendor remembers until morning, which is what makes trying it on a
    decision rather than a free reroll.

    Args:
        state: Mutable game state.
        npc_id: Vendor npc id.
        item_id: What is being argued over.
        side: ``buy`` or ``sell``.
        offer: The price per unit the player is asking for. Zero means "just
            try it on", which is scored as a standard-band attempt.
        ledger: Optional StoryLedger for boon/complication effects.

    Returns:
        Receipt with the check, the points moved, and the NEW quote -- which is
        the counter-offer, and is what ``buy``/``sell`` will execute at.
    """
    from engine.game.clock import advance_time

    side = SELL if str(side).lower() == SELL else BUY
    cfg = (_cfg().get("haggle") or {})
    before = quote(state, npc_id, item_id, side, 1)
    if not before.get("ok"):
        return {"success": False, **before}

    cap_attempts = int(cfg.get("attempts_per_day", 1) or 0)
    if cap_attempts and haggle_attempts(state, npc_id) >= cap_attempts:
        return {
            "success": False,
            "npc_id": npc_id,
            "message": "You have already had that argument today.",
            "quote": before,
        }

    standing_price = int(before["unit_price"])
    if offer and standing_price > 0:
        # Greed is how much better than the standing price the player is
        # asking for, in percent, and it reads the same on both sides: paying
        # less, or being paid more.
        if side == BUY:
            greed = (standing_price - int(offer)) / standing_price * 100.0
        else:
            greed = (int(offer) - standing_price) / standing_price * 100.0
    else:
        greed = 8.0
    greed = max(0.0, greed)
    band = _band_for_greed(greed)

    hours = float(cfg.get("hours", 0.0) or 0.0)
    if hours > 0:
        advance_time(state, hours)

    result = checks_module.resolve(
        state, str(cfg.get("skill", "persuasion")), band, ledger=ledger
    )
    moved = int((cfg.get("degrees") or {}).get(result.degree, 0) or 0)
    cap = int(cfg.get("cap", 20) or 0)
    points = max(-cap, min(cap, haggle_points(state, npc_id) + moved))
    _record_haggle(state, npc_id, points, haggle_attempts(state, npc_id) + 1)

    after = quote(state, npc_id, item_id, side, 1)
    accepted = bool(offer) and (
        after["unit_price"] <= int(offer) if side == BUY else after["unit_price"] >= int(offer)
    )

    logger.info(
        "[trade] Haggled (operation=haggle, npc=%s, item=%s, side=%s, band=%s, "
        "degree=%s, points=%s)",
        npc_id,
        item_id,
        side,
        band,
        result.degree,
        points,
    )

    if accepted:
        text = "They take it, with the face of someone who has decided not to argue."
    elif moved > 0:
        text = f"They come down to {after['unit_price']}c and will not be moved further."
    elif moved < 0:
        text = "You push too hard. The price goes the other way and stays there."
    else:
        text = "They hear you out and repeat the number."

    return {
        "success": moved > 0,
        "npc_id": npc_id,
        "vendor": before["vendor"],
        "item_id": item_id,
        "side": side,
        "offer": int(offer),
        "greed_percent": round(greed, 1),
        "difficulty": band,
        "check": result.to_dict(),
        "points_moved": moved,
        "haggle_points": points,
        "cap": cap,
        "price_before": standing_price,
        "counter": after["unit_price"],
        "offer_accepted": accepted,
        "quote": after,
        "attempts_used": haggle_attempts(state, npc_id),
        "attempts_per_day": cap_attempts,
        "hours": hours,
        "text": text,
    }


# ---------------------------------------------------------------------------
# execution
# ---------------------------------------------------------------------------


def buy(state: GameState, npc_id: str, item_id: str, qty: int = 1) -> dict[str, Any]:
    """
    Buy at the standing quote.

    Args:
        state: Mutable game state.
        npc_id: Vendor npc id.
        item_id: What to buy. Must be on the vendor's ``sells`` list -- a
            vendor prices anything, but only stocks what they stock.
        qty: How many.

    Returns:
        Receipt with the price paid, the purse after, and the quote it went
        through. A refusal is ``success: false`` and changes nothing.
    """
    qty = max(1, int(qty))
    profile = vendor(npc_id)
    if item_id not in (profile.get("sells") or {}):
        return {
            "success": False,
            "npc_id": npc_id,
            "item_id": item_id,
            "message": f"{profile.get('name', npc_id)} has none of that to sell.",
        }

    priced = quote(state, npc_id, item_id, BUY, qty)
    if not priced.get("ok"):
        return {"success": False, **priced, "message": priced.get("reason", "No deal.")}

    total = int(priced["total"])
    if state.stats.gold < total:
        return {
            "success": False,
            "npc_id": npc_id,
            "item_id": item_id,
            "quote": priced,
            "gold": int(state.stats.gold),
            "message": f"That is {total}c and you have {state.stats.gold}c.",
        }

    applied = [
        effects_module.apply_effect(state, {"type": "gold", "delta": -total}),
        inventory_module.grant(state, item_id, qty),
    ]

    logger.info(
        "[trade] Bought (operation=buy, npc=%s, item=%s, qty=%s, price=%s)",
        npc_id,
        item_id,
        qty,
        total,
    )
    return {
        "success": True,
        "npc_id": npc_id,
        "vendor": priced["vendor"],
        "item_id": item_id,
        "name": priced["item_name"],
        "qty": qty,
        "unit_price": priced["unit_price"],
        "gold_spent": total,
        "gold": int(state.stats.gold),
        "quote": priced,
        "effects": applied,
        "text": f"You pay {total}c for {qty}x {priced['item_name'].lower()}.",
    }


def sell(state: GameState, npc_id: str, item_id: str, qty: int = 1) -> dict[str, Any]:
    """
    Sell at the standing quote.

    This is the half of the shop that did not previously exist. Any item the
    vendor deals in is sellable at its registry value times the spread; a
    ``buys`` row is an override, not a gate.

    Args:
        state: Mutable game state.
        npc_id: Vendor npc id.
        item_id: What to sell.
        qty: How many. Clamped to what is actually carried.

    Returns:
        Receipt with the coin received and the quote it went through.
    """
    qty = max(1, int(qty))
    held = inventory_module.quantity(state, item_id)
    if held <= 0:
        return {
            "success": False,
            "npc_id": npc_id,
            "item_id": item_id,
            "message": "You are not carrying that.",
        }
    qty = min(qty, held)

    priced = quote(state, npc_id, item_id, SELL, qty)
    if not priced.get("ok"):
        return {"success": False, **priced, "message": priced.get("reason", "No deal.")}
    if priced["unit_price"] <= 0:
        return {
            "success": False,
            "npc_id": npc_id,
            "item_id": item_id,
            "quote": priced,
            "message": f"{priced['vendor']} will not put a price on that.",
        }

    total = int(priced["total"])
    applied = [
        inventory_module.take(state, item_id, qty),
        effects_module.apply_effect(state, {"type": "gold", "delta": total}),
    ]

    logger.info(
        "[trade] Sold (operation=sell, npc=%s, item=%s, qty=%s, price=%s)",
        npc_id,
        item_id,
        qty,
        total,
    )
    return {
        "success": True,
        "npc_id": npc_id,
        "vendor": priced["vendor"],
        "item_id": item_id,
        "name": priced["item_name"],
        "qty": qty,
        "unit_price": priced["unit_price"],
        "gold_gained": total,
        "gold": int(state.stats.gold),
        "quote": priced,
        "effects": applied,
        "text": f"They count out {total}c for {qty}x {priced['item_name'].lower()}.",
    }


def snapshot(state: GameState) -> dict[str, Any]:
    """Who the player could trade with from where they stand."""
    here = vendors_at(state.location_id)
    return {
        "location_id": state.location_id,
        "vendors_here": [
            {
                "npc_id": npc_id,
                "name": str(vendors()[npc_id].get("name") or npc_id),
                "faction": str(vendors()[npc_id].get("faction") or ""),
                "haggle_points": haggle_points(state, npc_id),
            }
            for npc_id in here
        ],
        "carried_value": inventory_module.carried_value(state),
        "gold": int(state.stats.gold),
    }
