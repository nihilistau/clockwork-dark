"""
Effect Dispatcher
=================

The single validated gate for every mechanical mutation.

Before this module, state changed from wherever it was convenient: boons and
complications were prose hints the model was trusted to honour, skill outcomes
poked ``state.stats`` inline, and a table entry that wanted to grant an item had
no way to say so. Three consequences followed, all of them bugs:

  1. A mutation could not be described. Receipts had nothing to show the UI, so
     the player was told the world changed but never what changed.
  2. A mutation could not be validated. Nothing clamped a stat to its maximum
     or a reputation to its band, so a stacked table entry could push stamina to
     140 or reputation past any threshold the world checks.
  3. A malformed data row crashed the turn. A YAML typo in a complication is a
     content mistake; it must never take the game down mid-narration.

So: data declares effects, this module applies them, and every application
returns a description. Unknown effect types are logged and ignored, never
raised -- an unrecognised row is content the engine is too old to understand,
not a reason to stop playing.

ITEMS WRITE THROUGH HERE TOO. ``equip``/``unequip``, ``heal_wound`` and
``clear_condition`` were added when items were given verbs (data/items/*.yaml
``use:`` and ``equip:`` blocks). They are here rather than in
engine/game/inventory.py for the reason at the top of this file: a bandage that
closed a wound by reaching into ``state.wounds`` would be a second writer, and
the receipt the UI renders would have nothing to show.

WHY THE KINDS ARE A REGISTRY NOW. They used to be a 330-line ``if/elif`` chain,
and the chain was not the problem -- what it *implied* was. Every branch named a
field of one story's ``GameState``, so the set of things an effect could change
was closed at the moment the flagship was written. A second story's ``favor``,
``corruption`` or ``briar_hunger`` could not be reached by any effect at all,
which meant they could not be reached by a quest reward, a challenge outcome, a
deck card, a thread's terms, or an ending gate -- every one of those funnels
through here by design (AGENTS.md rule 3). The one-writer rule was quietly also
a one-STORY rule.

Two changes fix that without loosening the rule:

  * ``@effect_kind("name")`` registers a handler. The fourteen original kinds
    are registered unchanged and resolve first, so nothing about the flagship
    moves.
  * ``value`` writes anything the ACTIVE STORY DECLARED in its ``state.yaml``,
    through ``StateStore`` -- which clamps to the declared bounds, enforces the
    per-agent ``owners`` ACL, and journals the write. A bare ``{type: favor,
    delta: 8}`` also works: an unregistered kind that names a declared value
    falls through to ``value``, exactly as ``hp``/``gold`` have always been
    sugar for ``stat``.

So the writer is still singular and every effect still returns a receipt; what
changed is that "the state" is now the state the running story declared rather
than the state this file was written against.

Version: v0.3.1 [2026-08-14]
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from engine.game.state import GameState, InventoryItem, TimedEffect, Wound

# Safe to import at module scope: engine.state.store reaches only
# engine.state.schema, which reaches only yaml. The story-AWARE half
# (engine.state.active) pulls in the game registry and is imported late, inside
# `_store`, because this module is loaded by tests and by the world sim with no
# story activated at all.
from engine.state.store import WRITER_ENGINE

logger = logging.getLogger(__name__)

#: An effect handler: (state, effect, context) -> receipt dict.
EffectHandler = Callable[[GameState, dict[str, Any], "EffectContext"], dict[str, Any]]

# Clamp bands. These are engine invariants, not balance knobs -- awareness and
# reputation are read as percentages and signed bands respectively by code that
# would otherwise need to defend itself at every call site.
AWARENESS_MIN, AWARENESS_MAX = 0.0, 100.0
HUNGER_MIN, HUNGER_MAX = 0.0, 100.0
DOOM_RESISTANCE_MIN, DOOM_RESISTANCE_MAX = 0.0, 100.0

# Effect type aliases that are just `stat` with the name baked in. Kept so a
# content author can write `{type: hp, delta: -2}` instead of the longer form.
_STAT_ALIASES = ("hp", "stamina", "focus", "craft", "gold")

# Worn gear is held as a TimedEffect rather than as a new GameState field, the
# same trick engine/game/foraging.py uses for node wear, engine/game/economy.py
# for the daily shift cap and engine/game/trade.py for today's haggle. Two
# things fall out of it for free:
#
#   1. engine/game/checks.py already walks ``active_effects`` for
#      ``kind == "check_penalty"`` and itemises each one in the receipt, so a
#      worn cloak shows up in the roll breakdown by name with no change there.
#   2. No save migration. A save written before equipment existed loads with an
#      empty list, which is exactly "wearing nothing".
#
# The id carries the whole record -- ``equip:<slot>:<item_id>`` -- so what is
# worn is derivable from the state rather than duplicated beside it.
EQUIP_ID_PREFIX = "equip:"

#: TimedEffect.expires_day for worn gear. The clock sweeps anything whose
#: expires_day is BELOW the current day (engine/game/clock.py); a sentinel this
#: far out means gear comes off when the player takes it off and at no other
#: time. Not `sys.maxsize`: this number round-trips through YAML and JSON saves
#: on every platform, and a boots entry reading "expires day 1000000000" is
#: legible in a save file as "never".
EQUIP_NEVER_EXPIRES = 1_000_000_000


def equip_effect_ids(state: GameState, slot: str = "") -> list[str]:
    """
    Ids of the worn-gear effects, optionally narrowed to one slot.

    Args:
        state: Game state.
        slot: Slot id, or "" for every slot.

    Returns:
        Matching ``TimedEffect.id`` strings, in wear order.
    """
    prefix = f"{EQUIP_ID_PREFIX}{slot}:" if slot else EQUIP_ID_PREFIX
    return [e.id for e in state.active_effects if e.id.startswith(prefix)]


def equipped_items(state: GameState) -> dict[str, str]:
    """
    Slot -> item id for everything currently worn.

    Derived from ``active_effects`` on every call rather than cached: the list
    is a handful of entries, and a cache would be a second source of truth for
    the one fact this whole encoding exists to avoid duplicating.
    """
    worn: dict[str, str] = {}
    for effect_id in equip_effect_ids(state):
        parts = effect_id.split(":")
        if len(parts) >= 3:
            # Extra bonuses past the first are suffixed `#2`, `#3`; they name
            # the same slot and item, so last write wins and agrees.
            worn[parts[1]] = parts[2].split("#")[0]
    return worn


def wound_mitigation(state: GameState) -> int:
    """
    Points of wound severity absorbed by worn gear.

    A board shield is not armour class -- DESIGN.md rules out hit-point combat
    -- but a thing between you and the problem has to do something or it is a
    35-copper decoration. It reduces severity and the check penalty that comes
    with it, and it can never reduce a wound to nothing: taking the hit is
    still taking the hit.
    """
    from engine.game import inventory  # late: inventory imports this module

    total = 0
    for item_id in equipped_items(state).values():
        spec = inventory.equip_spec(item_id) or {}
        total += max(0, _int(spec.get("absorbs_wounds"), 0))
    return total


class EffectContext:
    """
    Everything an effect handler may need that is not the state or the effect.

    A class rather than more keyword arguments because the handler signature is
    a public extension point now: a story or a later phase adding a dependency
    must not break every registered handler's signature.

    Attributes:
        ledger: Optional StoryLedger. Only ``ledger_fact`` needs it.
        by: Who is writing, for the StateStore journal and its ``owners`` ACL.
            Defaults to the engine, which is always permitted. An agent-composed
            effect should carry the agent's id so a write it does not own is
            refused AND recorded rather than silently taken.
        turn: Turn number, recorded in the journal.
    """

    __slots__ = ("ledger", "by", "turn")

    def __init__(
        self,
        *,
        ledger: Optional[Any] = None,
        by: str = WRITER_ENGINE,
        turn: int = 0,
    ) -> None:
        self.ledger = ledger
        self.by = by
        self.turn = turn


#: Registered effect kinds. Populated by ``@effect_kind`` at import time.
_KINDS: dict[str, EffectHandler] = {}


def effect_kind(*names: str) -> Callable[[EffectHandler], EffectHandler]:
    """
    Register a handler under one or more effect type names.

    Args:
        names: Type strings content may write. Lowercased on registration and
            on lookup, because YAML authors are not consistent about case.

    Returns:
        The undecorated function, so a handler stays directly callable and
        directly testable.
    """

    def decorator(func: EffectHandler) -> EffectHandler:
        for name in names:
            key = str(name).strip().lower()
            existing = _KINDS.get(key)
            if existing is not None and existing is not func:
                # Silently taking the last import's handler makes a clash
                # between two packs invisible until something misbehaves --
                # the same failure mode the skill registry warns about.
                logger.warning(
                    "[effects] Duplicate effect kind overwritten "
                    "(operation=effect_kind, kind=%s)",
                    key,
                )
            _KINDS[key] = func
        return func

    return decorator


def register_effect_kind(name: str, handler: EffectHandler) -> None:
    """Register a handler imperatively. For story packs and tests."""
    effect_kind(name)(handler)


def registered_kinds() -> list[str]:
    """Every effect type name the engine understands, sorted. For doctor/docs."""
    return sorted(_KINDS)


def _int(value: Any, default: int = 0) -> int:
    """Coerce a YAML scalar to int without raising on junk."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _float(value: Any, default: float = 0.0) -> float:
    """Coerce a YAML scalar to float without raising on junk."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def resolve_day(state: GameState, raw: Any, *, default_days: int = 1) -> int:
    """
    Resolve a day reference to an absolute world day.

    Content writes relative offsets (``"+3"``) because a table entry cannot know
    what day it will fire on. Absolute ints are passed through so a scripted
    event can still pin a date.

    Args:
        state: Game state, read for ``world_day``.
        raw: ``"+3"``, ``3``, or None.
        default_days: Offset used when raw is missing or unparseable.

    Returns:
        Absolute world day.
    """
    if raw is None or raw == "":
        return state.world_day + default_days
    if isinstance(raw, str):
        text = raw.strip()
        if text.startswith(("+", "-")):
            return state.world_day + _int(text, default_days)
        return _int(text, state.world_day + default_days)
    return _int(raw, state.world_day + default_days)


def duration_day(state: GameState, days: int) -> int:
    """
    The last day a thing lasting ``days`` days is still in force.

    NOT ``resolve_day``. The sweep in ``engine/game/clock.py`` drops an effect
    when ``expires_day < world_day`` -- i.e. ``expires_day`` is the last day it
    is STILL ACTIVE, not the first day it is gone. ``resolve_day`` returns
    ``world_day + days``, so ``{days: 1}`` applied on day 5 stamped 6 and the
    effect was in force on both day 5 and day 6: every duration in the game ran
    a day longer than it read.

    The comparator is deliberately not the thing that changed.
    ``economy._record_shift`` stamps ``expires_day = world_day`` meaning "today
    only", and flipping the sweep to ``<=`` would evict that on the first
    intra-day ``advance_time`` -- taking the daily shift cap with it.

    Args:
        state: Game state, read for ``world_day``.
        days: How many days it should last. Zero or less means today only.

    Returns:
        Absolute world day, inclusive.
    """
    return state.world_day + max(0, int(days) - 1)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _apply_stat(state: GameState, name: str, delta: int) -> dict[str, Any]:
    """
    Move a numeric stat, clamped to [0, max_<name>] when a maximum exists.

    Attributes (grit/agility/wits/presence) have no paired maximum, so only the
    floor applies to them.
    """
    stats = state.stats
    if not hasattr(stats, name):
        return _unknown(f"stat:{name}", {"stat": name, "delta": delta})

    before = _int(getattr(stats, name))
    cap_attr = f"max_{name}"
    ceiling = _int(getattr(stats, cap_attr)) if hasattr(stats, cap_attr) else None

    after = before + delta
    after = int(_clamp(after, 0, ceiling if ceiling is not None else after))
    setattr(stats, name, after)

    return {
        "type": "stat",
        "stat": name,
        "delta": delta,
        "applied": after - before,
        "before": before,
        "after": after,
        "ok": True,
        "text": f"{name} {after - before:+d} ({after}"
        + (f"/{ceiling})" if ceiling is not None else ")"),
    }


def _unknown(kind: str, effect: dict[str, Any]) -> dict[str, Any]:
    """
    Record an effect the engine does not understand.

    Logged at warning and returned as a non-ok description. Deliberately not an
    exception: content is loaded at runtime and a single bad row must not be
    able to abort a turn.
    """
    logger.warning(
        "[effects] Unknown effect ignored (operation=apply_effect, type=%s, effect=%s)",
        kind,
        effect,
    )
    return {"type": kind, "ok": False, "text": f"ignored unknown effect: {kind}"}


def _next_id(prefix: str, existing: list[Any], day: int) -> str:
    """Stable-ish unique id for a wound or timed effect."""
    return f"{prefix}_d{day}_{len(existing) + 1}"


# ---------------------------------------------------------------------------
# The kinds
#
# Each handler is exactly the branch that used to sit in `apply_effect`'s
# if/elif chain, moved out unchanged. Behaviour is identical by construction;
# what is new is that the set is open.
# ---------------------------------------------------------------------------


# -- stats and pools --------------------------------------------------------


@effect_kind("stat")
def _e_stat(state: GameState, effect: dict[str, Any], ctx: EffectContext) -> dict[str, Any]:
    name = str(effect.get("stat", "")).strip()
    if not name:
        return _unknown("stat", effect)
    return _apply_stat(state, name, _int(effect.get("delta")))


@effect_kind(*_STAT_ALIASES)
def _e_stat_alias(
    state: GameState, effect: dict[str, Any], ctx: EffectContext
) -> dict[str, Any]:
    """`{type: hp, delta: -2}` -- `stat` with the name in the type."""
    name = str(effect.get("type") or effect.get("stat") or "").strip().lower()
    if name not in _STAT_ALIASES:
        return _unknown("stat", effect)
    return _apply_stat(state, name, _int(effect.get("delta")))


@effect_kind("hunger")
def _e_hunger(state: GameState, effect: dict[str, Any], ctx: EffectContext) -> dict[str, Any]:
    before = state.hunger
    state.hunger = _clamp(before + _float(effect.get("delta")), HUNGER_MIN, HUNGER_MAX)
    return {
        "type": "hunger",
        "delta": _float(effect.get("delta")),
        "applied": state.hunger - before,
        "before": round(before, 1),
        "after": round(state.hunger, 1),
        "ok": True,
        "text": f"hunger {state.hunger - before:+.0f} ({state.hunger:.0f}/100)",
    }


@effect_kind("awareness")
def _e_awareness(
    state: GameState, effect: dict[str, Any], ctx: EffectContext
) -> dict[str, Any]:
    before = state.awareness
    state.awareness = _clamp(
        before + _float(effect.get("delta")), AWARENESS_MIN, AWARENESS_MAX
    )
    # Awareness is a hidden stat -- the description exists for receipts and
    # logs, never for the player-facing narration.
    return {
        "type": "awareness",
        "delta": _float(effect.get("delta")),
        "applied": state.awareness - before,
        "before": round(before, 1),
        "after": round(state.awareness, 1),
        "ok": True,
        "hidden": True,
        "text": f"awareness {state.awareness - before:+.0f}",
    }


@effect_kind("doom_resistance")
def _e_doom_resistance(
    state: GameState, effect: dict[str, Any], ctx: EffectContext
) -> dict[str, Any]:
    """
    Earned reprieve against the doom clock (R-06).

    THE ONLY WRITER OF ``state.doom_resistance`` BESIDES ITS DECAY. Quest
    rewards, set-piece victories and anything else that represents pushing back
    grant it through here; ``EvilTicker.advance`` spends it down at a
    configured rate per in-game day. Bounded 0-100 like awareness, and hidden
    like awareness: the player experiences it as the dark slowing, never as a
    number in the narration.
    """
    before = state.doom_resistance
    state.doom_resistance = _clamp(
        before + _float(effect.get("delta")), DOOM_RESISTANCE_MIN, DOOM_RESISTANCE_MAX
    )
    return {
        "type": "doom_resistance",
        "delta": _float(effect.get("delta")),
        "applied": state.doom_resistance - before,
        "before": round(before, 1),
        "after": round(state.doom_resistance, 1),
        "ok": True,
        "hidden": True,
        "text": f"doom resistance {state.doom_resistance - before:+.0f}",
    }


@effect_kind("reputation")
def _e_reputation(
    state: GameState, effect: dict[str, Any], ctx: EffectContext
) -> dict[str, Any]:
    faction = str(effect.get("faction") or effect.get("id") or "").strip()
    if not faction:
        return _unknown("reputation", effect)
    delta = _int(effect.get("delta"))
    # ONE implementation. This kind used to clamp to a global -100..100 while
    # `reputation.adjust` clamped to the FACTION's own bounds, and
    # `economy.work` called `adjust` directly around this dispatcher -- two
    # writers, two clamps. Now `adjust` is the implementation and this is the
    # only door to it (AGENTS.md rule 3).
    from engine.game import reputation as reputation_module

    before = _int(state.reputations.get(faction, 0))
    after = reputation_module.adjust(
        state, faction, delta, reason=str(effect.get("why") or effect.get("reason") or "")
    )
    return {
        "type": "reputation",
        "faction": faction,
        "delta": delta,
        "applied": after - before,
        "before": before,
        "after": after,
        "ok": True,
        "text": f"{faction} reputation {after - before:+d} ({after})",
    }


# -- inventory --------------------------------------------------------------


@effect_kind("item")
def _e_item(state: GameState, effect: dict[str, Any], ctx: EffectContext) -> dict[str, Any]:
    item_id = str(effect.get("item_id") or effect.get("id") or "").strip()
    if not item_id:
        return _unknown("item", effect)
    qty = max(1, _int(effect.get("qty"), 1))
    name = str(effect.get("name") or item_id.replace("_", " "))
    tags = list(effect.get("tags") or [])
    for entry in state.inventory:
        if entry.id == item_id:
            entry.qty += qty
            break
    else:
        state.inventory.append(InventoryItem(id=item_id, name=name, qty=qty, tags=tags))
    stolen = effect.get("stolen_from")
    if isinstance(stolen, dict):
        # One record per unit, so selling one ring of two consumes one record
        # and the other stays exactly as hot as it was. Stamped with the day
        # HERE rather than by the caller: the effect is the only writer, and a
        # caller-supplied day is a day a bug can backdate.
        record = {
            "whom": str(stolen.get("whom") or ""),
            "where": str(stolen.get("where") or ""),
            "day": state.world_day,
        }
        state.provenance.setdefault(item_id, []).extend(dict(record) for _ in range(qty))
    receipt: dict[str, Any] = {
        "type": "item",
        "item_id": item_id,
        "qty": qty,
        "ok": True,
        "text": f"gained {qty}x {name}",
    }
    # A set closes the moment its last piece lands, by WHATEVER door it came
    # in: a job's getaway, a quest's reward and a boon all grant through here,
    # not through ``inventory.grant``, and until v0.15 only that one door
    # settled a set (the rest waited for the ``collections`` skill).
    from engine.game import inventory as inventory_module

    if inventory_module.collection_of(item_id):
        finished = inventory_module.evaluate_collections(state, ledger=ctx.ledger)
        if finished:
            receipt["collections"] = finished
    return receipt


@effect_kind("provenance")
def _e_provenance(
    state: GameState, effect: dict[str, Any], ctx: EffectContext
) -> dict[str, Any]:
    """
    Consume ``qty`` theft records for an item, oldest first -- the goods left.

    A sale is what calls this (the fence's rules land with it). Oldest first
    because the record that goes is the one whose heat has most nearly worn
    off; which physical ring was handed over is not something the ledger can
    tell apart, and taking the newest would let a player cool a fresh theft by
    selling an old one. A miss is not an error, for the ``remove_item`` reason:
    selling honest goods simply has nothing to forget.

    ``newest: true`` consumes from the other end, for a CONFISCATION: the watch
    takes the hot units, and the hot records are the freshest ones. Taken
    oldest-first, a seized fresh ring would leave its record on the old ring
    still in the pack, and the ring the watch let you keep would turn hot.
    """
    item_id = str(effect.get("item_id") or effect.get("id") or "").strip()
    if not item_id:
        return _unknown("provenance", effect)
    want = max(1, _int(effect.get("qty"), 1))
    records = state.provenance.get(item_id) or []
    removed = min(want, len(records))
    if effect.get("newest"):
        del records[len(records) - removed:]
    else:
        del records[:removed]
    if not records:
        state.provenance.pop(item_id, None)
    # `inventory.name_of`, not a raw id massaged with `.replace` -- a raw id
    # must never reach the narrator, and an item's registry name is not
    # reliably its id with underscores swapped for spaces.
    from engine.game import inventory as inventory_module

    return {
        "type": "provenance",
        "item_id": item_id,
        "removed": removed,
        "ok": True,
        "text": f"forgot {removed} theft record(s) of {inventory_module.name_of(item_id)}"
        if removed
        else "",
    }


@effect_kind("remove_item")
def _e_remove_item(
    state: GameState, effect: dict[str, Any], ctx: EffectContext
) -> dict[str, Any]:
    item_id = str(effect.get("item_id") or effect.get("id") or "").strip()
    if not item_id:
        return _unknown("remove_item", effect)
    want = max(1, _int(effect.get("qty"), 1))
    # Deliberately does NOT touch `state.provenance`. A sale is a laundering --
    # the fence's cut is what buys the goods' history away, through the
    # `provenance` kind below -- but a complication that spoils rations or a
    # theft that takes them back is just loss. Those items' records stay
    # exactly as hot as they were, on the goods that are left, so a later gift
    # of the same id does not inherit a clean history it never earned.
    entry = next((i for i in state.inventory if i.id == item_id), None)
    if entry is None:
        # Not an error. A complication that spoils rations you do not carry
        # simply costs you nothing; refusing it would abort the draw.
        return {
            "type": "remove_item",
            "item_id": item_id,
            "removed": 0,
            "ok": True,
            "text": f"nothing to lose ({item_id})",
        }
    removed = min(want, entry.qty)
    entry.qty -= removed
    if entry.qty <= 0:
        state.inventory.remove(entry)
    return {
        "type": "remove_item",
        "item_id": item_id,
        "removed": removed,
        "ok": True,
        "text": f"lost {removed}x {entry.name}",
    }


# -- status -----------------------------------------------------------------


@effect_kind("wound")
def _e_wound(state: GameState, effect: dict[str, Any], ctx: EffectContext) -> dict[str, Any]:
    day = state.world_day
    severity = max(1, _int(effect.get("severity"), 1))
    penalty = _int(effect.get("check_penalty"), -1)

    # Worn gear absorbs, it does not cancel. The floor of 1 is the design
    # statement: a shield turns a bad wound into a lesser one and never
    # into no wound at all.
    absorbed = min(wound_mitigation(state), severity - 1)
    if absorbed > 0:
        severity -= absorbed
        penalty = min(0, penalty + absorbed)

    wound = Wound(
        id=str(effect.get("id") or _next_id("wound", state.wounds, day)),
        text=str(effect.get("text") or "Injury"),
        severity=severity,
        check_penalty=penalty,
        skills=[str(s) for s in (effect.get("skills") or [])],
        heals_on_day=resolve_day(state, effect.get("heals_on_day"), default_days=3),
    )
    state.wounds.append(wound)
    line = f"wounded: {wound.text} (heals day {wound.heals_on_day})"
    if absorbed:
        line += f"; gear absorbed {absorbed}"
    return {
        "type": "wound",
        "id": wound.id,
        "severity": wound.severity,
        "absorbed": absorbed,
        "heals_on_day": wound.heals_on_day,
        "ok": True,
        "text": line,
    }


@effect_kind("heal_wound")
def _e_heal_wound(
    state: GameState, effect: dict[str, Any], ctx: EffectContext
) -> dict[str, Any]:
    # Worst first. A poultice spent on a scratch while a deep cut is open
    # is a bandage the player will never forgive the engine for.
    want = max(1, _int(effect.get("count"), 1))
    wound_id = str(effect.get("id") or "").strip()
    pool = (
        [w for w in state.wounds if w.id == wound_id]
        if wound_id
        else sorted(state.wounds, key=lambda w: -int(w.severity))
    )
    healed = []
    for wound in pool[:want]:
        state.wounds.remove(wound)
        healed.append(wound.text)
    return {
        "type": "heal_wound",
        "healed": healed,
        "count": len(healed),
        "ok": True,
        "text": ("closed: " + ", ".join(healed) if healed else "nothing needed binding"),
    }


@effect_kind("clear_condition")
def _e_clear_condition(
    state: GameState, effect: dict[str, Any], ctx: EffectContext
) -> dict[str, Any]:
    # Matched by id first, then by exact text, then by kind. A draught that
    # takes a fever down has to be able to name the fever.
    target_id = str(effect.get("id") or "").strip()
    target_text = str(effect.get("text") or "").strip().lower()
    target_kind = str(effect.get("kind") or "check_penalty").strip()
    cleared = []
    for timed in list(state.active_effects):
        if timed.expires_day >= EQUIP_NEVER_EXPIRES:
            # PERMANENT EFFECTS ARE NOT CONDITIONS. Worn gear and completed
            # collections both live in this list as check_penalty entries
            # with the "never" sentinel, and a blanket clear would take a
            # cloak off your back and a finished set's standing away for
            # the price of one draught of bittergreen. A condition is a
            # thing that was going to end on its own.
            continue
        hit = (
            (target_id and timed.id == target_id)
            or (target_text and timed.text.lower() == target_text)
            or (not target_id and not target_text and timed.kind == target_kind)
        )
        if hit:
            state.active_effects.remove(timed)
            cleared.append(timed.text or timed.id)
    return {
        "type": "clear_condition",
        "cleared": cleared,
        "count": len(cleared),
        "ok": True,
        "text": "eased: " + ", ".join(cleared) if cleared else "nothing to ease",
    }


@effect_kind("equip")
def _e_equip(state: GameState, effect: dict[str, Any], ctx: EffectContext) -> dict[str, Any]:
    item_id = str(effect.get("item_id") or effect.get("id") or "").strip()
    slot = str(effect.get("slot") or "").strip()
    if not item_id or not slot:
        return _unknown("equip", effect)

    # One thing per slot. Displacing is the caller's job, so that the
    # receipt can name what came off.
    for existing in list(state.active_effects):
        if existing.id.startswith(f"{EQUIP_ID_PREFIX}{slot}:"):
            state.active_effects.remove(existing)

    bonuses = [b for b in (effect.get("bonuses") or []) if isinstance(b, dict)]
    if not bonuses:
        bonuses = [{}]
    applied: list[dict[str, Any]] = []
    for index, bonus in enumerate(bonuses):
        suffix = "" if index == 0 else f"#{index + 1}"
        timed = TimedEffect(
            id=f"{EQUIP_ID_PREFIX}{slot}:{item_id}{suffix}",
            kind="check_penalty",
            text=str(bonus.get("text") or effect.get("text") or item_id.replace("_", " ")),
            delta=_int(bonus.get("delta"), 0),
            skills=[str(s) for s in (bonus.get("skills") or [])],
            expires_day=EQUIP_NEVER_EXPIRES,
        )
        state.active_effects.append(timed)
        applied.append({"delta": timed.delta, "skills": list(timed.skills)})

    return {
        "type": "equip",
        "item_id": item_id,
        "slot": slot,
        "bonuses": applied,
        "ok": True,
        "text": f"worn: {item_id.replace('_', ' ')} ({slot})",
    }


@effect_kind("unequip")
def _e_unequip(
    state: GameState, effect: dict[str, Any], ctx: EffectContext
) -> dict[str, Any]:
    slot = str(effect.get("slot") or "").strip()
    item_id = str(effect.get("item_id") or "").strip()
    removed = ""
    for existing in list(state.active_effects):
        if not existing.id.startswith(EQUIP_ID_PREFIX):
            continue
        parts = existing.id.split(":")
        if len(parts) < 3:
            continue
        worn_slot, worn_item = parts[1], parts[2].split("#")[0]
        if (slot and worn_slot != slot) or (item_id and worn_item != item_id):
            continue
        state.active_effects.remove(existing)
        removed = worn_item
    return {
        "type": "unequip",
        "slot": slot,
        "item_id": removed,
        "ok": True,
        "text": (
            f"stowed: {removed.replace('_', ' ')}" if removed else "nothing worn there"
        ),
    }


@effect_kind("check_penalty")
def _e_check_penalty(
    state: GameState, effect: dict[str, Any], ctx: EffectContext
) -> dict[str, Any]:
    day = state.world_day
    # `days` is the natural way to write "for two days" in a table; it is
    # converted here so the clock's expiry sweep sees an absolute day.
    #
    # Through `duration_day`, not `resolve_day`: the sweep keeps an effect while
    # `expires_day >= world_day`, so a one-day penalty stamped `world_day + 1`
    # was in force on two days. An ABSOLUTE `expires_day` written by content
    # still passes through `resolve_day` untouched -- that is a date, not a
    # duration.
    raw_expiry = effect.get("expires_day")
    if raw_expiry in (None, ""):
        expires = duration_day(state, max(1, _int(effect.get("days"), 1)))
    else:
        expires = resolve_day(state, raw_expiry, default_days=1)
    timed = TimedEffect(
        id=str(effect.get("id") or _next_id("effect", state.active_effects, day)),
        kind="check_penalty",
        text=str(effect.get("text") or "condition"),
        delta=_int(effect.get("delta"), -1),
        skills=[str(s) for s in (effect.get("skills") or [])],
        expires_day=expires,
    )
    state.active_effects.append(timed)
    return {
        "type": "check_penalty",
        "id": timed.id,
        "delta": timed.delta,
        "skills": list(timed.skills),
        "expires_day": timed.expires_day,
        "ok": True,
        "text": f"{timed.text} ({timed.delta:+d} until day {timed.expires_day})",
    }


@effect_kind("flag")
def _e_flag(state: GameState, effect: dict[str, Any], ctx: EffectContext) -> dict[str, Any]:
    name = str(effect.get("flag") or effect.get("name") or "").strip()
    if not name:
        return _unknown("flag", effect)
    # Flags are booleans in content, but the assistant's cooldowns keep a turn
    # NUMBER under a flag key, and a writer that coerced it would turn "last
    # appeared on turn 40" into "has appeared". Scalars pass through untouched;
    # anything structured is collapsed to a bool, exactly as it always was.
    raw = effect.get("value", True)
    value = raw if isinstance(raw, (bool, int, float, str)) else bool(raw)
    state.flags[name] = value
    return {
        "type": "flag",
        "flag": name,
        "value": value,
        "ok": True,
        "text": f"flag {name}={value}",
    }


@effect_kind("timed_effect")
def _e_timed_effect(
    state: GameState, effect: dict[str, Any], ctx: EffectContext
) -> dict[str, Any]:
    """
    Append an arbitrary ``TimedEffect`` record -- the daily-marker trick.

    Four systems keep "what happened today" as a timed effect so the clock's
    expiry sweep IS the reset rule: the labour shift cap (``kind: shift``),
    forage node wear (``kind: forage_node``), today's haggle (``kind: haggle``)
    and once-per-day item use (``kind: item_use``). Each used to append to the
    live effects list directly from its own module, which was four quiet
    exceptions to the one-writer rule; they route through here now, and the
    receipt is what makes the marker visible in a turn log.

    ``expires_day`` accepts the same forms as ``check_penalty``: an absolute
    day, a relative ``"+2"``, or nothing for tomorrow.
    """
    timed = TimedEffect(
        id=str(
            effect.get("id")
            or _next_id("effect", state.active_effects, state.world_day)
        ),
        kind=str(effect.get("kind") or "marker").strip(),
        text=str(effect.get("text") or ""),
        delta=_int(effect.get("delta"), 0),
        skills=[str(s) for s in (effect.get("skills") or [])],
        expires_day=resolve_day(state, effect.get("expires_day"), default_days=1),
    )
    state.active_effects.append(timed)
    return {
        "type": "timed_effect",
        "id": timed.id,
        "kind": timed.kind,
        "delta": timed.delta,
        "expires_day": timed.expires_day,
        "ok": True,
        # Bookkeeping, not narration: a marker that says "worked the forge
        # today" is for the engine's arithmetic, never for the player's prose.
        "hidden": True,
        "text": f"{timed.text or timed.id} (until day {timed.expires_day})",
    }


@effect_kind("intel")
def _e_intel(state: GameState, effect: dict[str, Any], ctx: EffectContext) -> dict[str, Any]:
    """
    Record one thing learned about a premise by watching it.

    The id must be one the house actually holds -- ``premises.intel_for`` is
    asked, not trusted to the caller -- because an id nothing can render would
    count toward "everything is known" while telling the player nothing: the
    verb would vanish over a house the player never learned about.
    """
    from engine.world import premises

    premise_id = str(effect.get("premise") or "").strip()
    intel_id = str(effect.get("intel") or "").strip()
    rows = {row["id"]: row["text"] for row in premises.intel_for(state, premise_id)}
    if intel_id not in rows:
        return {
            "type": "intel",
            "ok": False,
            "text": "nothing of that kind to learn about that house",
        }
    learned = state.premise_intel.setdefault(premise_id, [])
    if intel_id not in learned:
        learned.append(intel_id)
    return {
        "type": "intel",
        "premise": premise_id,
        "intel": intel_id,
        "ok": True,
        "text": rows[intel_id],
    }


def _deed_id(state: GameState, effect: dict[str, Any]) -> str:
    """
    The deed a witness row or report belongs to: the caller's, or a new one.

    New ids come from the saved counter ``state.law["deed_seq"]`` and are
    allocated HERE, by whichever Law effect first needs one, so the counter
    has the same single writer as every other Law field. Called only after an
    effect has validated, so a refusal never burns an id.
    """
    given = str(effect.get("deed_id") or "").strip()
    if given:
        return given
    seq = _int(state.law.get("deed_seq"), 0) + 1
    state.law["deed_seq"] = seq
    return f"d{seq}"


@effect_kind("witness")
def _e_witness(state: GameState, effect: dict[str, Any], ctx: EffectContext) -> dict[str, Any]:
    """
    Record that one person saw one deed: who, what, the guise worn, where, when.

    First-hand by default -- ``hop`` 1, ``precision`` 1.0 -- because a deed's
    own witnesses saw it themselves. ``law.propagate`` passes both for a TOLD
    copy, which must retell a row someone holds one hop nearer. Severity is
    read from the law file (a told copy keeps its teller's) and the day stamped
    here, the ``report`` kind's reason.

    The id comes from a counter in ``state.law`` rather than the row count, so
    ids stay unique within a save even once rows are copied or pruned -- a
    retold sighting must be traceable to the one it retells. ``deed_id`` ties
    every witness and report of one deed together (see ``_deed_id``).
    """
    from engine.world import law

    if not law.declared():
        return _law_refusal("witness", "this story keeps no watch to witness for")
    spec = law.load_spec()
    deed = str(effect.get("deed") or "").strip()
    guise = str(effect.get("guise") or "").strip()
    npc = str(effect.get("npc") or "").strip()
    where = str(effect.get("where") or "").strip()
    hop = _int(effect.get("hop"), 1)
    precision = _float(effect.get("precision"), 1.0)
    if deed not in spec["deeds"]:
        return _law_refusal("witness", f"unknown deed `{deed}`")
    if guise not in spec["guises"]:
        return _law_refusal("witness", f"unknown guise `{guise}`")
    if not npc or not where:
        return _law_refusal("witness", "a witness needs a person and a place")
    if hop < 1 or not 0.0 <= precision <= 1.0:
        return _law_refusal("witness", "hop must be 1 or more and precision between 0 and 1")
    if str(effect.get("deed_id") or "").strip() in law.discharged(state):
        return _law_refusal("witness", "that deed has been discharged")
    severity = spec["deeds"][deed]
    if hop > 1:
        # A TOLD copy. It must name the deed it retells, and someone must hold
        # that deed one remove nearer with the same kind, guise and place --
        # otherwise a copy could say something the sighting did not, and the
        # counted-once score keyed on the deed id could be fooled by it.
        # Severity is the teller's row's, so a copy is never re-priced.
        from engine.world.gossip import MAX_HOPS

        given = str(effect.get("deed_id") or "").strip()
        teller = next((
            row for row in state.law.get("witnessed") or []
            if row.get("deed_id") == given and _int(row.get("hop"), 1) == hop - 1
            and row.get("deed") == deed and row.get("guise") == guise
            and row.get("where") == where
        ), None) if given else None
        if hop > MAX_HOPS or teller is None:
            return _law_refusal("witness", "a told sighting needs a teller one remove nearer")
        # And exactly as clear as that remove allows: a hop-2 copy filed at 1.0
        # would be a second-hand sighting counted as first-hand.
        if precision != (spec.get("precision") or {}).get(hop):
            return _law_refusal("witness", f"a hop-{hop} sighting is filed at that hop's precision")
        severity = teller.get("severity", severity)
    deed_id = _deed_id(state, effect)
    seq = _int(state.law.get("witness_seq"), 0) + 1
    state.law["witness_seq"] = seq
    state.law.setdefault("witnessed", []).append({
        "id": f"w{seq}",
        "deed_id": deed_id,
        "deed": deed,
        "severity": severity,
        "guise": guise,
        "npc": npc,
        "where": where,
        "day": state.world_day,
        "hop": hop,
        "precision": precision,
    })
    return {
        "type": "witness",
        "ok": True,
        # So the caller can stamp the rest of this deed's rows with it.
        "deed_id": deed_id,
        # The calling skill's receipt carries who saw (``seen_by``), rendered
        # by name; this row is bookkeeping and its fields are all ids.
        "hidden": True,
        "text": "",
    }


@effect_kind("report")
def _e_report(state: GameState, effect: dict[str, Any], ctx: EffectContext) -> dict[str, Any]:
    """
    File one report with the watch: a deed, the guise it was pinned on, where.

    Severity is read from the story's law file, never taken from the caller,
    and the day is stamped here -- the ``item`` kind's reason: the effect is the
    only writer, so it is the only place a bug could inflate or backdate a
    crime. Every reference is checked before anything is written, because a
    report against a guise or jurisdiction the Law does not know would count
    toward nobody's wanted level while looking like heat.

    ``deed_id`` names the deed this report is OF; a report without one is a
    deed of its own. The wanted score counts each deed once (``law.filed_score``).
    """
    from engine.world import law

    if not law.declared():
        return _law_refusal("report", "this story keeps no watch to report to")
    spec = law.load_spec()
    deed = str(effect.get("deed") or "").strip()
    guise = str(effect.get("guise") or "").strip()
    jurisdiction = str(effect.get("jurisdiction") or "").strip()
    precision = _float(effect.get("precision"), 1.0)
    if deed not in spec["deeds"]:
        return _law_refusal("report", f"unknown deed `{deed}`")
    if guise not in spec["guises"]:
        return _law_refusal("report", f"unknown guise `{guise}`")
    if jurisdiction not in spec["jurisdictions"]:
        return _law_refusal("report", f"unknown jurisdiction `{jurisdiction}`")
    if not 0.0 <= precision <= 1.0:
        return _law_refusal("report", "precision must be between 0 and 1")
    deed_id = _deed_id(state, effect)
    given = str(effect.get("deed_id") or "").strip()
    if given in law.discharged(state):
        # Paid for or served (`law_discharge`): the watch-house has closed it.
        return _law_refusal("report", "that deed has been discharged")
    if given and given in law.quashed(state, jurisdiction):
        # Bought off (`quash_reports`): this watch-house has lost that file and
        # will not re-open it when a witness's gossip reaches a watchman here.
        return _law_refusal("report", "that deed's file was lost here")
    rows = state.law.setdefault("reports", [])
    rows.append({
        "deed_id": deed_id,
        "deed": deed,
        "severity": spec["deeds"][deed],
        "guise": guise,
        "jurisdiction": jurisdiction,
        "precision": precision,
        "day": state.world_day,
    })
    # Prose only: the guise's authored label and a clarity word. The deed kind
    # and jurisdiction are ids, and the precision is a number -- all three are
    # exactly what the narrator must not echo.
    return {
        "type": "report",
        "ok": True,
        "text": f"word of {law.guise_label(guise)} reached the watch, {law.clarity(precision)}",
    }


def _law_refusal(kind: str, why: str) -> dict[str, Any]:
    """A Law effect that wrote nothing, and why -- for the log and the receipt.

    ``text`` stays empty: the reason names ids, and ids never reach the prose.
    ``message`` is the diagnosable half, so a thread whose bribe discharges into
    a misspelt guise says so instead of reporting success over nothing.
    """
    return {"type": kind, "ok": False, "text": "", "message": why}


@effect_kind("quash_reports")
def _e_quash_reports(
    state: GameState, effect: dict[str, Any], ctx: EffectContext
) -> dict[str, Any]:
    """
    Make reports go missing: every one matching ``jurisdiction``, ``guise`` and
    ``max_severity``, each filter optional. A bribed sergeant's thread
    discharges through this -- corruption is a contract, and this is its term.

    Exact guise match by default: a sergeant paid to lose the porter's file
    has not been paid to lose yours. ``linked: true`` widens it to every guise
    the watch takes for the same person -- without it, a bribe to lose you
    would leave the Magpie's file standing while the watch believes you are
    her, and appear to do nothing. A named guise or jurisdiction the Law does
    not know is refused, not matched against nothing.

    Cooling is re-capped afterwards, or the offset that was wearing down the
    quashed reports would be left over to pre-forgive the next one.

    A quash LASTS. Each removed report's deed id is remembered under its
    jurisdiction (``state.law["quashed"]``, written only here), and ``report``
    refuses that deed there from then on -- otherwise the witnesses who saw it
    would carry it to the next watchman within the day and ``law.propagate``
    would re-file what the bribe had lost. The witness rows stay: the deed was
    still seen, and another district's watch can still hear of it.
    """
    from engine.world import law

    if not law.declared():
        return _law_refusal("quash_reports", "this story keeps no watch to bribe")
    try:
        # The one row reading, shared with the `filed` predicate that gates a
        # bribe on there being something for it to lose.
        _matches = law.report_matcher(
            state,
            jurisdiction=str(effect.get("jurisdiction") or ""),
            guise=str(effect.get("guise") or ""),
            linked=bool(effect.get("linked")),
            max_severity=effect.get("max_severity"),
        )
    except ValueError as exc:
        return _law_refusal("quash_reports", str(exc))
    rows = state.law.get("reports") or []
    kept = [row for row in rows if not _matches(row)]
    removed = len(rows) - len(kept)
    # Nothing matched writes nothing: a clean state must not grow `reports: []`.
    if removed:
        state.law["reports"] = kept
        lost = state.law.setdefault("quashed", {})
        for row in rows:
            deed_id = str(row.get("deed_id") or "")
            if deed_id and _matches(row):
                place = lost.setdefault(str(row.get("jurisdiction")), [])
                if deed_id not in place:
                    place.append(deed_id)
        if state.law.get("cool"):
            state.law["cool"] = law.cap_cooling(state, state.law["cool"])
    return {
        "type": "quash_reports",
        "ok": True,
        "text": "some reports against you went missing from the watch-house" if removed else "",
    }


@effect_kind("deed")
def _e_deed(state: GameState, effect: dict[str, Any], ctx: EffectContext) -> dict[str, Any]:
    """
    The player committed a crime here and now: ``law.commit_deed`` from an
    authored outcome. How a scene's fight with the watch becomes
    ``assault_watch`` -- the skills that commit deeds call ``commit_deed``
    themselves; content has no other way to.

    ``seen_by_watch: true`` makes every awake law-role person present a
    CERTAIN witness: a Lantern you knocked down saw who did it, whatever the
    notice roll would have said. Everyone else rolls as for any deed.

    ``report_precision: <0..1>`` is the victim telling the watch-house
    himself -- a scene's own Lantern, who is no scheduled person and so is not
    among the witnesses ``seen_by_watch`` can find. When nobody present filed
    the deed, one report of it is filed for the guise worn, where it happened,
    at that clarity. When someone did, it adds nothing: one deed, one report.

    Every write inside is itself an effect (``witness``, ``report``). A kind
    the law file does not list is refused rather than committed as nothing,
    so a misspelt deed in an outcome says so.
    """
    from engine.world import law, npc_sim

    if not law.declared():
        return _law_refusal("deed", "this story keeps no watch to offend")
    kind = str(effect.get("deed") or "").strip()
    if kind not in law.load_spec()["deeds"]:
        return _law_refusal("deed", f"unknown deed `{kind}`")
    told: float | None = None
    if "report_precision" in effect:
        raw = effect.get("report_precision")
        if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not 0.0 <= raw <= 1.0:
            return _law_refusal("deed", "report_precision must be a number between 0 and 1")
        told = float(raw)
    certain: tuple[str, ...] = ()
    if effect.get("seen_by_watch"):
        roles = set(law.load_spec().get("roles") or [])
        certain = tuple(
            p.npc_id for p in npc_sim.npcs_at(state, state.location_id)
            if p.available and p.role in roles
        )
    seen = law.commit_deed(state, kind, certain=certain)
    reported = bool(seen.get("reported"))
    jurisdiction = law.jurisdiction_at(state.location_id)
    if told is not None and not reported and jurisdiction:
        filed = apply_effect(state, {
            "type": "report", "deed": kind, "guise": law.current_guise(state),
            "jurisdiction": jurisdiction, "precision": told,
            # Seen by a bystander who did not tell: join that deed (the
            # stamp `commit_deed` just wrote), so it is still one deed.
            "deed_id": str((state.law.get("last_deed") or {}).get("id") or "")
            if seen.get("witnesses") else "",
        })
        reported = bool(filed.get("ok"))
    return {
        "type": "deed",
        "ok": True,
        "reported": reported,
        # The outcome's own prose tells it; witness ids never reach the narrator.
        "hidden": True,
        "text": "",
    }


@effect_kind("law_cool")
def _e_law_cool(state: GameState, effect: dict[str, Any], ctx: EffectContext) -> dict[str, Any]:
    """
    Let ``days`` of quiet wear every file down by ``cool_per_day`` a day. The
    only writer of the cooling offsets.

    One offset per FILE -- per jurisdiction, per guise the report was filed
    under -- rather than a rewrite of each report, so the rows stay what was
    filed and a later quash still sees them. Per file because one offset per
    jurisdiction let the Magpie's quiet week forgive a porter's fresh assault.
    Each is capped by ``law.cap_cooling`` at its own file's score, so quiet
    days cannot be banked against a crime not yet committed.
    """
    from engine.world import law

    if not law.declared():
        return _law_refusal("law_cool", "this story keeps no watch to forget")
    days = max(0.0, _float(effect.get("days"), 0.0))
    step = law.load_spec()["wanted"]["cool_per_day"] * days
    proposed: dict[str, dict[str, float]] = {}
    for row in state.law.get("reports") or []:
        where, guise = str(row.get("jurisdiction")), str(row.get("guise"))
        proposed.setdefault(where, {})[guise] = law.cooling_of(state, guise, where) + step
    after = law.cap_cooling(state, proposed)
    changed = any(
        value > law.cooling_of(state, guise, where)
        for where, files in after.items()
        for guise, value in files.items()
    )
    # Nothing to cool writes nothing: a story with a Law and a clean record
    # keeps `state.law` empty rather than growing a column of zeros.
    if changed:
        state.law["cool"] = after
    return {
        "type": "law_cool",
        "ok": True,
        # Bookkeeping; the narrator hears about heat as a band, not a decay.
        "hidden": True,
        "text": "the watch's memory of you wears thinner" if changed else "",
    }


@effect_kind("law_guise")
def _e_law_guise(state: GameState, effect: dict[str, Any], ctx: EffectContext) -> dict[str, Any]:
    """
    Set which face the player is wearing. The only writer of ``state.law["guise"]``.

    Refuses a guise the Law does not know, and refuses any guise but ``self``
    whose item is not currently carried -- a mask left behind cannot still be
    on the player's face. ``self`` needs no item and is always available: it
    is what a player who owns nothing else to wear still has.
    """
    from engine.world import law

    if not law.declared():
        return _law_refusal("law_guise", "this story keeps no watch to notice a change of face")
    spec = law.load_spec()
    guise = str(effect.get("guise") or "").strip()
    if guise not in spec["guises"]:
        return _law_refusal("law_guise", f"unknown guise `{guise}`")
    if guise != law.SELF_GUISE:
        item = str(spec["guises"][guise].get("item") or "")
        if item:
            from engine.game import inventory  # late: inventory imports this module

            if not inventory.holds(state, item):
                return _law_refusal(
                    "law_guise", f"guise `{guise}` needs `{item}`, which is not carried"
                )
    state.law["guise"] = guise
    return {"type": "law_guise", "ok": True, "guise": guise, "text": ""}


@effect_kind("law_link")
def _e_law_link(state: GameState, effect: dict[str, Any], ctx: EffectContext) -> dict[str, Any]:
    """
    Tell the watch two guises are one person. The only writer of ``state.law["links"]``.

    ``law.links`` reads the file's OWN starting belief until state holds any
    of its own, so this is the first write's seed too: adding one pair reads
    through the spec's list, appends to that (rather than to an empty one),
    and stores the result -- the spec's initial belief survives instead of
    being silently replaced by a set of one.

    Symmetric and deduplicated: ``[a, b]`` and ``[b, a]`` are the same belief,
    and asking twice writes once.
    """
    from engine.world import law

    if not law.declared():
        return _law_refusal("law_link", "this story keeps no watch to link anything for")
    spec = law.load_spec()
    a = str(effect.get("a") or "").strip()
    b = str(effect.get("b") or "").strip()
    if a not in spec["guises"] or b not in spec["guises"]:
        return _law_refusal("law_link", "a link needs two known guises")
    if a == b:
        return _law_refusal("law_link", "a guise cannot be linked to itself")
    pairs = law.links(state)
    if not any({pair[0], pair[1]} == {a, b} for pair in pairs):
        pairs.append([a, b])
        state.law["links"] = pairs
    return {"type": "law_link", "ok": True, "text": ""}


@effect_kind("arrest")
def _e_arrest(state: GameState, effect: dict[str, Any], ctx: EffectContext) -> dict[str, Any]:
    """
    The watch takes the player: to the gaol, relieved of hot goods, held.

    THE ONLY EFFECT THAT MOVES THE PLAYER. Location otherwise changes only by
    graph travel (``GameEngine.move_to``, which validates the edge and charges
    the leg) and by a death's respawn (``encounter._check_death_inner``, which
    is the engine carrying a body, not a choice). Everything else that wants
    the player elsewhere -- a card, a thread, a scene's outcome -- has to walk
    them or arrest them. Written directly to ``state.location_id`` for the
    respawn's reason: an arrest is not a walk, so it spends no stamina and no
    hours (the hours are the SENTENCE, served through ``advance_time``).

    In order, reading everything BEFORE anything is written:

      1. The charge -- ``law.sentence_for`` over the jurisdiction the player
         was standing in and the face they were wearing (read before the
         confiscation, which may take the mask itself).
      2. The confiscation -- every carried unit ``thievery.heat_split`` calls
         HOT, through ``remove_item`` and ``provenance`` (newest records
         first, so a mixed stack keeps its cool units cool). Cool and clean
         goods stay: the watch takes what a victim could name this week.
      3. The move to ``arrest.gaol``, and ``custody`` set to ``{fine, days,
         since_day, jurisdiction, guise, charged}`` -- ``charged`` the deed ids
         on the sheet, so ``pay_fine`` and ``serve_sentence`` discharge exactly
         what was charged and nothing committed from the cell.

    An open scene (the arrest encounter this outcome came from) is marked
    resolved: an unresolved scene cannot survive the player being carried out
    of it, and ``resolve_approach`` clears a resolved one at the end of its
    round. Refused while already held, and in a story with no Law or no
    ``arrest`` block.
    """
    from engine.game import inventory as inventory_module
    from engine.game.locations import LOCATIONS
    from engine.world import law, thievery

    if not law.declared():
        return _law_refusal("arrest", "this story keeps no watch to arrest anyone")
    gaol = str((law.load_spec().get("arrest") or {}).get("gaol") or "")
    if not gaol:
        return _law_refusal("arrest", "the law file declares no gaol")
    if law.in_custody(state):
        return _law_refusal("arrest", "already held")

    jurisdiction = law.jurisdiction_at(state.location_id)
    guise = law.current_guise(state)
    sentence = law.sentence_for(state, guise, jurisdiction) if jurisdiction else {"fine": 0, "days": 0}
    charged = sorted(law.charged_deeds(state, guise, jurisdiction)) if jurisdiction else []

    seized: list[str] = []
    for entry in list(state.inventory):
        hot = thievery.heat_split(state, entry.id)["hot"]
        if hot <= 0:
            continue
        apply_effect(state, {"type": "remove_item", "item_id": entry.id, "qty": hot})
        apply_effect(state, {"type": "provenance", "item_id": entry.id, "qty": hot, "newest": True})
        # The name only: a count in the receipt is a number in the prose.
        seized.append(inventory_module.name_of(entry.id))

    state.location_id = gaol
    if state.encounter and not state.encounter.get("resolved"):
        state.encounter["resolved"] = True
        state.encounter["outcome"] = "arrested"
    state.law["custody"] = {
        "fine": sentence["fine"],
        "days": sentence["days"],
        "since_day": state.world_day,
        "jurisdiction": jurisdiction,
        "guise": guise,
        # Exactly what this arrest charged, so paying or serving discharges
        # these deeds and nothing filed afterwards (`law._discharge`).
        "charged": [d for d in charged if not d.startswith("#row")],
    }
    where = str((LOCATIONS.get(gaol) or {}).get("name") or "the cells")
    taken = f"; the watch kept {', '.join(seized)}" if seized else ""
    return {"type": "arrest", "ok": True, "seized": seized, "text": f"taken to {where}{taken}"}


@effect_kind("release")
def _e_release(state: GameState, effect: dict[str, Any], ctx: EffectContext) -> dict[str, Any]:
    """
    Let the player go. The only writer that clears ``state.law["custody"]``.

    Clears custody and NOTHING else: the file stays filed. ``law.pay_fine``
    and ``law.serve_sentence`` discharge the charge before they call this; a
    story's break-out scene calls it bare, and walks out still wanted.
    """
    from engine.world import law

    if not law.declared():
        return _law_refusal("release", "this story keeps no watch to hold anyone")
    if not law.in_custody(state):
        return _law_refusal("release", "not held")
    state.law.pop("custody", None)
    return {"type": "release", "ok": True, "text": "released"}


@effect_kind("law_discharge")
def _e_law_discharge(
    state: GameState, effect: dict[str, Any], ctx: EffectContext
) -> dict[str, Any]:
    """
    Close deeds for good: a paid fine or a served sentence. The only writer of
    ``state.law["discharged_deeds"]``.

    For each deed id: every report of it goes (in every jurisdiction -- a
    deed paid for is paid for), every witness row of it goes (so propagation
    has nobody left to carry it to a new watchman), and the id is remembered,
    so ``report`` and ``witness`` refuse it from then on. Rows are dropped
    rather than flagged because a flagged row would still be a teller in
    ``law.propagate`` and a sighting in every later reader. Cooling is
    re-capped, as ``quash_reports`` does, so an offset never outlives the
    file it wore down.
    """
    from engine.world import law

    if not law.declared():
        return _law_refusal("law_discharge", "this story keeps no watch to settle with")
    ids = [str(d).strip() for d in effect.get("deed_ids") or [] if str(d).strip()]
    if not ids:
        return _law_refusal("law_discharge", "no deeds named to discharge")
    closing = set(ids)
    for key in ("reports", "witnessed"):
        rows = state.law.get(key) or []
        kept = [row for row in rows if str(row.get("deed_id") or "") not in closing]
        if len(kept) != len(rows):
            state.law[key] = kept
    done = [str(d) for d in state.law.get("discharged_deeds") or []]
    state.law["discharged_deeds"] = done + [d for d in ids if d not in done]
    if state.law.get("cool"):
        state.law["cool"] = law.cap_cooling(state, state.law["cool"])
    return {"type": "law_discharge", "ok": True, "hidden": True, "text": ""}


@effect_kind("law_last_deed")
def _e_law_last_deed(
    state: GameState, effect: dict[str, Any], ctx: EffectContext
) -> dict[str, Any]:
    """
    Record the deed the player just committed, SEEN OR NOT. The only writer
    of ``state.law["last_deed"]``.

    A SEEN deed is stamped ``{id, turn, where}`` -- the id its first witness
    row allocated, ``state.turn_number``, the place. An UNSEEN deed (no id:
    nobody saw it, so none was allocated) removes any earlier stamp instead,
    which reads identically -- no seen deed this turn -- and keeps a clean
    save clean: a deed nobody saw in a Law that holds nothing still writes
    nothing at all.

    ``commit_deed`` applies it for every deed, so the narrator's "you were
    seen" line (``prompts.law_block``) asks about THIS turn's deed and not
    the newest deed anybody happened to see: an unseen lift after a seen one
    must not name the earlier witnesses, who are not even in the room.
    """
    from engine.world import law

    if not law.declared():
        return _law_refusal("law_last_deed", "this story keeps no watch")
    deed_id = str(effect.get("deed_id") or "").strip()
    if deed_id:
        state.law["last_deed"] = {
            "id": deed_id,
            "turn": state.turn_number,
            "where": str(effect.get("where") or "").strip(),
        }
    else:
        state.law.pop("last_deed", None)
    return {"type": "law_last_deed", "ok": True, "hidden": True, "text": ""}


def _job_refusal(kind: str, why: str) -> dict[str, Any]:
    """A job effect that wrote nothing, and why. Same shape as ``_law_refusal``."""
    return {"type": kind, "ok": False, "text": "", "message": why}


@effect_kind("job_open")
def _e_job_open(state: GameState, effect: dict[str, Any], ctx: EffectContext) -> dict[str, Any]:
    """
    Start a job on a premise. The only writer of ``state.jobs["active"]`` and
    ``state.jobs["seq"]``.

    ``stages`` is the caller's (``jobs.stages_for``), so an anchored premise's
    spliced stages are decided once, where the anchor is read. Refuses an
    unknown premise, an empty stage list, and a second job while one is open
    -- two open jobs would each believe they own the turn. The id comes from
    the saved counter, allocated only after every check passed, so a refusal
    never burns one.

    The job starts at its first stage with no alarm. ``entry`` and
    ``obstacles`` are absent until the stages that decide them are reached.
    """
    from engine.world import jobs, premises

    if not jobs.declared():
        return _job_refusal("job_open", "this story has no jobs")
    if jobs.active(state) is not None:
        return _job_refusal("job_open", "a job is already open")
    premise_id = str(effect.get("premise") or "").strip()
    prem = premises.get(state, premise_id)
    if prem is None:
        return _job_refusal("job_open", f"unknown premise `{premise_id}`")
    stages = effect.get("stages")
    if not isinstance(stages, list) or not stages or not all(
        isinstance(s, str) and s for s in stages
    ):
        return _job_refusal("job_open", "a job needs a non-empty list of stage ids")
    seq = _int(state.jobs.get("seq"), 0) + 1
    state.jobs["seq"] = seq
    job_id = f"j{seq}"
    state.jobs["active"] = {
        "id": job_id,
        "premise": premise_id,
        "district": str(prem.get("district") or ""),
        "stages": list(stages),
        "at": 0,
        "alarm": 0,
        "raised_at": None,
        "shifts": {},
        "used_flashbacks": [],
        "loot": [],
        "log": [],
    }
    return {"type": "job_open", "ok": True, "hidden": True, "job_id": job_id, "text": ""}


@effect_kind("job_close")
def _e_job_close(state: GameState, effect: dict[str, Any], ctx: EffectContext) -> dict[str, Any]:
    """
    End the open job. The only writer of ``state.jobs["robbed"]`` and
    ``state.jobs["last"]``, and the only thing that clears ``active``.

    A score carried out (``jobs.CARRIED_OUT``: ``clean`` or ``noisy``) marks
    the premise robbed, so ``burgle`` never offers it again; an aborted or
    caught job took nothing and leaves the house to try again. ``last`` keeps
    the close for the narrator, stamped with ``state.turn_number``, and with
    ``by: "player"`` when the effect says the thief chose it (``jobs.abort``)
    -- an ``aborted`` close written by ``jobs.tick`` (the house roused, nobody
    to come) is not the player walking away, and must not be narrated as one.
    """
    from engine.world import jobs

    if not jobs.declared():
        return _job_refusal("job_close", "this story has no jobs")
    job = jobs.active(state)
    if job is None:
        return _job_refusal("job_close", "no job is open")
    outcome = str(effect.get("outcome") or "").strip()
    if outcome not in jobs.OUTCOMES:
        return _job_refusal("job_close", f"unknown job outcome `{outcome}`")
    premise_id = str(job.get("premise") or "")
    if outcome in jobs.CARRIED_OUT:
        robbed = state.jobs.setdefault("robbed", [])
        if premise_id not in robbed:
            robbed.append(premise_id)
    state.jobs["last"] = {
        "id": str(job.get("id") or ""),
        "premise": premise_id,
        "outcome": outcome,
        "turn": state.turn_number,
    }
    if effect.get("by") == "player":
        state.jobs["last"]["by"] = "player"
    if job.get("emptied"):
        state.jobs["last"]["emptied"] = True
        if job.get("loot"):
            # What an agenda's robbery left behind (a set's pieces,
            # ``jobs._left_by_agendas``), so the close line can name it.
            state.jobs["last"]["left"] = [str(i) for i in job["loot"]]
    state.jobs.pop("active", None)
    return {"type": "job_close", "ok": True, "hidden": True, "outcome": outcome, "text": ""}


@effect_kind("job_stage")
def _e_job_stage(state: GameState, effect: dict[str, Any], ctx: EffectContext) -> dict[str, Any]:
    """
    Record what one stage turn did to the open job. The only writer of its
    ``at``, ``entry``, ``obstacles``, ``loot`` and ``log``.

    ``stage`` must be the job's CURRENT stage: a write for any other would
    record a turn at a stage the player is not at. ``emptied: true`` marks
    a score that found the house already robbed by an agenda. ``entry``,
    ``obstacles``, ``loot``, ``shifts``, ``used_flashbacks`` and ``last_flashback`` replace
    their fields when given; a ``degree`` key (even "") appends one ``log``
    row; ``advance`` moves to the next stage. Advancing past the last stage
    is refused -- the getaway closes the job through ``job_close``, never by
    walking off the end of the list.

    ``shifts``, ``used_flashbacks`` and ``last_flashback`` are how a
    flashback banks its effect, marks itself spent, and stamps which one
    paid off THIS turn (``jobs.flashback``); nothing else writes them.
    """
    from engine.world import jobs

    if not jobs.declared():
        return _job_refusal("job_stage", "this story has no jobs")
    job = jobs.active(state)
    if job is None:
        return _job_refusal("job_stage", "no job is open")
    stages = list(job.get("stages") or [])
    at = _int(job.get("at"), 0)
    stage = str(effect.get("stage") or "")
    if not 0 <= at < len(stages) or stages[at] != stage:
        return _job_refusal("job_stage", f"`{stage}` is not the stage the job is at")
    advance = bool(effect.get("advance"))
    if advance and at + 1 >= len(stages):
        return _job_refusal("job_stage", "the last stage closes the job; it does not advance")
    if "obstacles" in effect and stage != "inside":
        # An obstacle only exists at `inside`; a write for any other stage
        # would leave a later `inside` seeing the key already present and
        # crossing it with no roll at all -- the whole stage silently skipped.
        return _job_refusal("job_stage", "obstacles only apply at the `inside` stage")
    if "entry" in effect:
        job["entry"] = str(effect["entry"])
    if "obstacles" in effect:
        job["obstacles"] = [str(o) for o in effect.get("obstacles") or []]
    if "loot" in effect:
        job["loot"] = [str(i) for i in effect.get("loot") or []]
    if effect.get("emptied"):
        # The score found the house already bare (an agenda robbed it first).
        job["emptied"] = True
    if "shifts" in effect:
        job["shifts"] = {str(k): int(v) for k, v in (effect.get("shifts") or {}).items()}
    if "used_flashbacks" in effect:
        job["used_flashbacks"] = [str(k) for k in effect.get("used_flashbacks") or []]
    if "last_flashback" in effect:
        # Which flashback paid off, and on what turn -- `jobs.flashback`'s own
        # stamp, read back by `jobs.flashback_label_this_turn` the same way
        # `law_last_deed` is read back through `last_deed.turn`.
        payload = effect.get("last_flashback")
        job["last_flashback"] = dict(payload) if payload else None
    if "degree" in effect:
        job.setdefault("log", []).append({
            "stage": stage,
            "approach": str(effect.get("approach") or ""),
            "degree": str(effect.get("degree") or ""),
        })
    if advance:
        job["at"] = at + 1
    return {"type": "job_stage", "ok": True, "hidden": True, "at": job["at"], "text": ""}


@effect_kind("job_alarm")
def _e_job_alarm(state: GameState, effect: dict[str, Any], ctx: EffectContext) -> dict[str, Any]:
    """
    Move the open job's alarm by ``delta``, clamped to 0..``alarm.max``. The
    only writer of its ``alarm`` and ``raised_at``.

    The first time the alarm reaches max, ``raised_at`` is stamped HERE with
    the absolute in-game hour (``jobs.now_hour``) -- the effect is the only
    writer, and a caller-supplied hour is an hour a bug can backdate. It is
    never re-stamped: the watch was sent for once, and more noise does not
    make it set out again later.

    Returns ``raised: True`` only on the write that raised it.
    """
    from engine.world import jobs

    if not jobs.declared():
        return _job_refusal("job_alarm", "this story has no jobs")
    job = jobs.active(state)
    if job is None:
        return _job_refusal("job_alarm", "no job is open")
    maximum = int(jobs.spec()["alarm"]["max"])
    before = _int(job.get("alarm"), 0)
    after = int(_clamp(before + _int(effect.get("delta")), 0, maximum))
    job["alarm"] = after
    raised = after >= maximum and job.get("raised_at") is None
    if raised:
        job["raised_at"] = jobs.now_hour(state)
    return {"type": "job_alarm", "ok": True, "hidden": True, "alarm": after,
            "raised": raised, "text": ""}


@effect_kind("job_prep")
def _e_job_prep(state: GameState, effect: dict[str, Any], ctx: EffectContext) -> dict[str, Any]:
    """
    Move the veiled ``prep`` meter by ``delta``, clamped to 0..``prep.max``.
    The only writer of ``state.jobs["prep"]``.

    Lives on ``state.jobs`` itself, not the open job: prep is restored by
    casing between jobs, not by opening one, so it survives ``job_open`` and
    ``job_close`` untouched. No job needs to be open to spend or earn it --
    ``premises.case`` pays into it whether or not a burglary is under way.
    """
    from engine.world import jobs

    if not jobs.declared():
        return _job_refusal("job_prep", "this story has no jobs")
    maximum = int(jobs.spec()["prep"]["max"])
    before = _int(state.jobs.get("prep"), 0)
    after = int(_clamp(before + _int(effect.get("delta")), 0, maximum))
    state.jobs["prep"] = after
    return {"type": "job_prep", "ok": True, "hidden": True, "prep": after, "text": ""}


def _agenda_refusal(kind: str, why: str) -> dict[str, Any]:
    """An agenda effect that wrote nothing, and why. Same shape as ``_law_refusal``."""
    return {"type": kind, "ok": False, "text": "", "message": why}


def _strict_int(value: Any) -> Optional[int]:
    """An int, or None for anything else -- a bool and "soon" included."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


@effect_kind("agenda_mark")
def _e_agenda_mark(
    state: GameState, effect: dict[str, Any], ctx: EffectContext
) -> dict[str, Any]:
    """
    The agendas pass's bookkeeping. The only writer of ``state.agendas``'s
    ``last_hour``, ``moves``, ``fired`` and ``truth``.

    Shape (any combination, at least one)::

        {type: agenda_mark, last_hour: 57}                  # the pass walked to 57
        {type: agenda_mark, move: "the_magpie:lift", hour: 49}   # a move fired at 49
        {type: agenda_mark, fired: "the_magpie:hears"}      # a once-reaction spent
        {type: agenda_mark, truth: {"the_magpie:hears": true}}   # edge-trigger memory

    Every key is checked against the loaded agendas file before anything is
    written, so a refusal writes nothing: a move or reaction the file does not
    declare, ``fired`` on a reaction that is not ``once``, a truth that is not
    a bool, an hour that is not an integer. ``last_hour`` never moves
    backwards -- the pass walking to an hour it already walked would replay
    every move in between.
    """
    from engine.world import agendas

    if not agendas.declared():
        return _agenda_refusal("agenda_mark", "this story has no agendas")
    moves = agendas.move_keys()
    reactions = agendas.reaction_keys()
    once = agendas.reaction_keys(once_only=True)
    writes: dict[str, Any] = {}
    if "last_hour" in effect:
        last = _strict_int(effect.get("last_hour"))
        if last is None:
            return _agenda_refusal("agenda_mark", "`last_hour` must be an integer hour")
        if last < _int(state.agendas.get("last_hour"), last):
            return _agenda_refusal("agenda_mark", "the agendas pass never walks backwards")
        writes["last_hour"] = last
    if "move" in effect:
        move = str(effect.get("move") or "")
        hour = _strict_int(effect.get("hour"))
        if move not in moves:
            return _agenda_refusal("agenda_mark", f"unknown move `{move}`")
        if hour is None:
            return _agenda_refusal("agenda_mark", "a fired move needs an integer `hour`")
        writes["move"] = (move, hour)
    if "fired" in effect:
        fired = str(effect.get("fired") or "")
        if fired not in once:
            return _agenda_refusal("agenda_mark", f"`{fired}` is not a once-reaction")
        writes["fired"] = fired
    if "truth" in effect:
        truth = effect.get("truth")
        if not isinstance(truth, dict) or not truth:
            return _agenda_refusal("agenda_mark", "`truth` must map reactions to true/false")
        for key, value in truth.items():
            if str(key) not in reactions:
                return _agenda_refusal("agenda_mark", f"unknown reaction `{key}`")
            if not isinstance(value, bool):
                return _agenda_refusal("agenda_mark", f"truth of `{key}` must be true or false")
        writes["truth"] = {str(k): v for k, v in truth.items()}
    if not writes:
        return _agenda_refusal("agenda_mark", "nothing to record")

    if "last_hour" in writes:
        state.agendas["last_hour"] = writes["last_hour"]
    if "move" in writes:
        move, hour = writes["move"]
        state.agendas.setdefault("moves", {})[move] = hour
    if "fired" in writes:
        fired_list = state.agendas.setdefault("fired", [])
        if writes["fired"] not in fired_list:
            fired_list.append(writes["fired"])
    if "truth" in writes:
        state.agendas.setdefault("truth", {}).update(writes["truth"])
    return {"type": "agenda_mark", "ok": True, "hidden": True, "text": ""}


@effect_kind("agenda_hit")
def _e_agenda_hit(
    state: GameState, effect: dict[str, Any], ctx: EffectContext
) -> dict[str, Any]:
    """
    Record that an agenda robbed a premise. The only writer of ``state.agendas["hits"]``.

    Shape: ``{type: agenda_hit, agenda: the_magpie, premise: prem_x, hour: 49}``.

    Deliberately NOT ``jobs.robbed``: that list is the player's -- the scores
    a job of theirs carried out -- and ``premise_robbed`` reads it as such. An
    agenda's robbery is its own record; ``not_robbed`` selectors and the
    ``agenda_hit`` predicate read it here.
    """
    from engine.world import agendas, premises

    if not agendas.declared():
        return _agenda_refusal("agenda_hit", "this story has no agendas")
    agenda = str(effect.get("agenda") or "")
    premise = str(effect.get("premise") or "")
    hour = _strict_int(effect.get("hour"))
    if agenda not in (agendas.spec().get("agendas") or {}):
        return _agenda_refusal("agenda_hit", f"unknown agenda `{agenda}`")
    if premises.get(state, premise) is None:
        return _agenda_refusal("agenda_hit", f"unknown premise `{premise}`")
    if hour is None:
        return _agenda_refusal("agenda_hit", "a hit needs an integer `hour`")
    state.agendas.setdefault("hits", []).append(
        {"agenda": agenda, "premise": premise, "hour": hour}
    )
    return {"type": "agenda_hit", "ok": True, "hidden": True, "text": ""}


@effect_kind("agenda_trace")
def _e_agenda_trace(
    state: GameState, effect: dict[str, Any], ctx: EffectContext
) -> dict[str, Any]:
    """
    Leave a sign of an agenda's move. The only writer of ``state.agendas``'s
    ``traces`` and ``trace_seq``.

    Shape: ``{type: agenda_trace, agenda, text, where, hour, public?}``.

    Ids are ``t<n>`` from the saved counter ``trace_seq`` -- allocated here,
    after validation, so a refusal never burns one (``_deed_id``'s rule). A
    PUBLIC trace is common talk: it also goes to the moved journal, unlocated,
    at once. A private one waits in state for the player to come upon it.
    The receipt is hidden: the text reaches the prose only through those two
    routes, never as a line of this turn's mechanics.
    """
    from engine.game import moved
    from engine.world import agendas

    if not agendas.declared():
        return _agenda_refusal("agenda_trace", "this story has no agendas")
    agenda = str(effect.get("agenda") or "")
    text = " ".join(str(effect.get("text") or "").split())
    where = effect.get("where", "")
    hour = _strict_int(effect.get("hour"))
    public = effect.get("public", False)
    if agenda not in (agendas.spec().get("agendas") or {}):
        return _agenda_refusal("agenda_trace", f"unknown agenda `{agenda}`")
    if not text:
        return _agenda_refusal("agenda_trace", "a trace needs text")
    if not isinstance(where, str):
        return _agenda_refusal("agenda_trace", "`where` must be a location id")
    if hour is None:
        return _agenda_refusal("agenda_trace", "a trace needs an integer `hour`")
    if not isinstance(public, bool):
        return _agenda_refusal("agenda_trace", "`public` must be true or false")
    seq = _int(state.agendas.get("trace_seq"), 0) + 1
    state.agendas["trace_seq"] = seq
    trace_id = f"t{seq}"
    state.agendas.setdefault("traces", []).append({
        "id": trace_id, "agenda": agenda, "text": text, "where": where,
        "hour": hour, "public": public, "seen": False,
    })
    if public:
        moved.note(state, "agenda", text)
    return {"type": "agenda_trace", "ok": True, "hidden": True, "id": trace_id, "text": ""}


@effect_kind("agenda_trace_seen")
def _e_agenda_trace_seen(
    state: GameState, effect: dict[str, Any], ctx: EffectContext
) -> dict[str, Any]:
    """
    Record that the narrator has been shown these signs. The only writer of a
    trace's ``seen``.

    Shape: ``{type: agenda_trace_seen, ids: [t3, t4]}``. Applied by
    ``agendas.clear_shown`` after the turn that rendered them (the moved
    journal's lifecycle), never authored. Every id is checked before any is
    written, so a bad list records nothing.
    """
    from engine.world import agendas

    if not agendas.declared():
        return _agenda_refusal("agenda_trace_seen", "this story has no agendas")
    ids = effect.get("ids")
    if not isinstance(ids, list) or not ids or not all(isinstance(i, str) for i in ids):
        return _agenda_refusal("agenda_trace_seen", "`ids` must be a list of trace ids")
    rows = {str(t.get("id")): t for t in state.agendas.get("traces") or []}
    unknown = [i for i in ids if i not in rows]
    if unknown:
        return _agenda_refusal("agenda_trace_seen", f"unknown trace `{unknown[0]}`")
    for trace_id in ids:
        rows[trace_id]["seen"] = True
    return {"type": "agenda_trace_seen", "ok": True, "hidden": True, "text": ""}


@effect_kind("ledger_fact")
def _e_ledger_fact(
    state: GameState, effect: dict[str, Any], ctx: EffectContext
) -> dict[str, Any]:
    text = str(effect.get("text") or "").strip()
    if ctx.ledger is None or not text:
        # No ledger in scope is normal outside a turn (tests, world sim).
        return {
            "type": "ledger_fact",
            "ok": False,
            "text": "no ledger in scope; fact dropped",
        }
    ctx.ledger.add_fact(
        text,
        kind=str(effect.get("kind") or "engine"),
        subject_id=str(effect.get("subject_id") or ""),
        turn=state.turn_number,
        day=state.world_day,
        source="engine",
    )
    return {"type": "ledger_fact", "ok": True, "text": f"remembered: {text}"}


# -- story-declared state ---------------------------------------------------


@effect_kind("value")
def _e_value(state: GameState, effect: dict[str, Any], ctx: EffectContext) -> dict[str, Any]:
    """
    Move or set any value the ACTIVE STORY declared in its ``state.yaml``.

    This is the kind that makes the dispatcher story-agnostic. It does not know
    what ``favor`` or ``briar_hunger`` are; it knows the schema declared them,
    what they are bounded by and who may write them, and it hands the write to
    ``StateStore`` which enforces all three and journals the result.

    Shapes::

        {type: value, name: favor, delta: 8}
        {type: value, name: favor, set: 40}

    ``delta`` and ``set`` are both accepted because both read naturally in
    content and neither can be expressed as the other without the author
    knowing the current value, which content never does.
    """
    name = str(effect.get("name") or effect.get("value") or effect.get("id") or "").strip()
    if not name:
        return _unknown("value", effect)

    store = _store(state)
    if store is None or not store.has(name):
        # A story that does not declare this value is not a story where this
        # effect means anything. Ignored rather than raised, like every other
        # unusable row: content the engine is too old (or too other) to
        # understand must not abort a turn.
        return _unknown(f"value:{name}", effect)

    before = store.get(name)
    why = str(effect.get("why") or effect.get("reason") or "")

    if "set" in effect:
        after = store.set(name, _float(effect.get("set")), by=ctx.by, why=why, turn=ctx.turn)
        wanted = _float(effect.get("set"))
    else:
        delta = _float(effect.get("delta"))
        after = store.adjust(name, delta, by=ctx.by, why=why, turn=ctx.turn)
        wanted = before + delta

    spec = store.schema.get(name)
    label = spec.display_label if spec is not None else name
    refused = after == before and wanted != before

    # A veiled value crossing a band is a story beat the engine already had
    # and threw away. Journalled in band WORDS -- the number is exactly what
    # veiling exists to keep from the prose.
    if (
        spec is not None
        and spec.visibility == "veiled"
        and not refused
        and spec.band(before) != spec.band(after)
    ):
        from engine.game import moved

        moved.note(
            state,
            "band",
            f"{label.lower()}: {spec.band(before)} -> {spec.band(after)}",
        )
    return {
        "type": "value",
        "name": name,
        "label": label,
        "kind": spec.kind if spec is not None else "meter",
        # WHO and WHY, on the receipt -- the artifact that survives the turn.
        #
        # The store used to keep a write journal holding these. It was per-store
        # and `store_for()` builds a fresh store on every call, so every record
        # died the moment this function returned; nothing ever read one, and the
        # journal is deleted. This receipt is what the roster's
        # `writes_with_reason` grant actually lands on: "she took something from
        # you" attached to the number that moved.
        "by": ctx.by,
        "why": why,
        "delta": _float(effect.get("delta")) if "set" not in effect else None,
        "applied": after - before,
        "before": before,
        "after": after,
        # A veiled or hidden value must not leak its number into a receipt the
        # player can read; the caller decides, but it has to be told.
        "visibility": spec.visibility if spec is not None else "public",
        "ok": not refused,
        "text": (
            f"{label} {after - before:+g} ({after:g})"
            if not refused
            else f"{label} unchanged: write refused or already at bound"
        ),
    }


@effect_kind("track")
def _e_track(state: GameState, effect: dict[str, Any], ctx: EffectContext) -> dict[str, Any]:
    """
    Write a NON-NUMERIC story value -- an enum, a list, a small record.

    ``StateStore`` is numeric by construction: meters and clocks are numbers
    with bounds. But a story's spine also carries things like
    ``ending_intent = "E1a"``, ``act2_compass = "love_and_door"`` and
    ``eligible_endings = [...]`` -- enum-valued and list-valued state that is
    not a flag (flags are booleans) and not a meter (no bounds, no arithmetic).
    Without this kind those would be written by reaching into ``state.tracks``
    from wherever was convenient, which is precisely the second writer this
    module exists to prevent.

    Bounding is by declared enum: pass ``allowed`` and a value outside it is
    refused rather than stored. That is what stops a model inventing an
    ending id.
    """
    name = str(effect.get("name") or effect.get("track") or "").strip()
    if not name:
        return _unknown("track", effect)

    value = effect.get("value")
    allowed = effect.get("allowed")
    if isinstance(allowed, (list, tuple)) and allowed:
        if value not in list(allowed):
            logger.warning(
                "[effects] Track value outside its declared set, refused "
                "(operation=apply_effect, track=%s, value=%r)",
                name,
                value,
            )
            return {
                "type": "track",
                "name": name,
                "ok": False,
                "text": f"{name}: {value!r} is not one of the declared values",
            }

    before = state.tracks.get(name)
    state.tracks[name] = value
    return {
        "type": "track",
        "name": name,
        "before": before,
        "after": value,
        "ok": True,
        "text": f"{name} = {value}",
    }


@effect_kind("ending_module")
def _e_ending_module(
    state: GameState, effect: dict[str, Any], ctx: EffectContext
) -> dict[str, Any]:
    """
    ``{type: ending_module}`` -- play the locked ending's Speak · Act · Seal.

    Takes no id: which three beats these are was decided by the lock, and
    letting a beat name them would let the finale play an ending the player
    never committed to. Runs once; a replay is refused with a receipt.

    Authored-content-only, same as the two phases above.
    """
    from engine.game import endings as endings_module

    receipt = endings_module.run_module(state, ledger=ctx.ledger, by=ctx.by)
    receipt["type"] = "ending_module"
    return receipt


@effect_kind("ending_intent", "ending_lock")
def _e_ending(state: GameState, effect: dict[str, Any], ctx: EffectContext) -> dict[str, Any]:
    """
    Swear an ending, or commit to one.

    ``{type: ending_intent, ending: E1a}`` is soft -- it can be sworn, changed
    and dropped, and Day 8 exists for it. ``{type: ending_lock, ending: E1a}``
    is the point of no return: refused on an id that cannot complete, refused a
    second time on an already-locked save, and the signal the run is over.

    THIS IS THE LINK THAT WAS MISSING. ``engine/game/endings.py`` has had both
    calls since the structural systems landed, ``day_09_finale.yaml`` names them
    beat by beat ("RUNTIME: ``endings.lock(state, <id>)``"), and no Python
    anywhere invoked either -- so the finale was a document describing a
    mechanism, the epilogue could not be reached by playing, and every layer
    beneath it worked.

    Routed through this dispatcher rather than called from a scene runner
    because ``apply_effect`` is the one writer, and because that is what puts
    both behind the ``by=`` ACL: an agent that may not end the story cannot,
    and the refusal is journalled rather than dropped.

    ``ending_lock`` WITH NO ID locks whatever the run has earned, via
    ``endings.resolve()`` -- the intent sworn on Day 8 if it is still eligible,
    else the highest-scoring eligible ending, else the declared fail-forward.
    That is the shape the finale actually needs: the id belongs to the player,
    not to the beat, and ``day_09_finale.yaml`` says so ("Whatever
    ``endings.locked(state)`` returns... it cannot return nothing"). An
    ``ending_intent`` with no id is still an error, because swearing to
    whatever you happen to be nearest is not swearing.

    Neither is bounded here. ``endings`` does its own bounding against the
    declared table, which is stricter than an enum -- it checks the ending can
    actually COMPLETE, not merely that its id was spelled right.
    """
    from engine.game import endings as endings_module

    kind = str(effect.get("type", "")).strip().lower()
    ending_id = str(effect.get("ending") or effect.get("id") or "").strip()
    if not ending_id:
        if kind != "ending_lock":
            return _unknown(kind, effect)
        ending_id = endings_module.resolve(state, ledger=ctx.ledger)
        if not ending_id:
            # A story with no declared endings. Nothing to lock, and this is
            # not an error -- it is a story that does not end this way.
            return _unknown(kind, effect)

    if kind == "ending_lock":
        terminal = effect.get("terminal") is True
        if terminal:
            from engine.game import encounter as encounter_module

            if not encounter_module.terminal_lock_in_progress():
                # The death's key, not a way round an ending's gate: a quest,
                # a card, or anything a respawn's hours run writing it would
                # lock an ending nobody earned.
                logger.warning(
                    "[effects] Terminal ending lock outside a death, refused "
                    "(operation=apply_effect, ending=%s)",
                    ending_id,
                )
                return {
                    "type": kind,
                    "ok": False,
                    "text": "a terminal lock belongs to a death; nothing is dying",
                }
        receipt = endings_module.lock(state, ending_id, ledger=ctx.ledger, terminal=terminal)
    else:
        receipt = endings_module.set_intent(state, ending_id, ledger=ctx.ledger)
    # The receipt is already a track receipt from `_write_track`; relabelling it
    # would hide which of the two phases produced it.
    receipt["type"] = kind
    return receipt


def _store(state: GameState) -> Optional[Any]:
    """
    A StateStore over the active story's schema, or None.

    Imported late and defensively: ``engine.state.active`` reaches the game
    registry and the manifest, and this module is imported by the world sim and
    by tests that construct a bare ``GameState`` with no story activated at all.
    A story-declared write that cannot find a schema is a no-op, never a crash.
    """
    try:
        from engine.state.active import store_for

        return store_for(state)
    except Exception as exc:  # noqa: BLE001 -- see docstring
        logger.debug("[effects] No state store available: %s", exc)
        return None


def _declared(state: GameState, name: str) -> bool:
    """True when the active story declares ``name`` as one of its values."""
    store = _store(state)
    return store is not None and store.has(name)


# ---------------------------------------------------------------------------
# The dispatcher
# ---------------------------------------------------------------------------


def apply_effect(
    state: GameState,
    effect: dict[str, Any],
    *,
    ledger: Optional[Any] = None,
    by: str = WRITER_ENGINE,
    turn: int = 0,
) -> dict[str, Any]:
    """
    Apply one declared effect to the game state.

    Args:
        state: Mutable game state.
        effect: Effect dict with a ``type`` key. Shape depends on the type; see
            data/tables/*.yaml for worked examples.
        ledger: Optional StoryLedger. Required only for ``ledger_fact``; when
            absent that effect type is skipped rather than failing.
        by: Writer id, for the StateStore journal and the per-value ``owners``
            ACL. Defaults to the engine, which may always write.
        turn: Turn number, recorded in the journal.

    Returns:
        Description dict. Always has ``type``, ``ok`` and ``text``. ``ok`` is
        False for unknown or unusable effects; this function does not raise.
    """
    if not isinstance(effect, dict):
        return _unknown("malformed", {"raw": effect})

    kind = str(effect.get("type", "")).strip().lower()
    if not kind:
        return _unknown("missing_type", effect)

    ctx = EffectContext(ledger=ledger, by=by, turn=turn)

    handler = _KINDS.get(kind)
    if handler is not None:
        return handler(state, effect, ctx)

    # LAST RESORT, AND ONLY FOR A NAME THE STORY ACTUALLY DECLARED. `{type:
    # favor, delta: 8}` is the shape a content author reaches for, and it is
    # the same sugar `hp`/`gold` have always had -- but it must never turn a
    # typo into a silent write, so an undeclared name still falls through to
    # `_unknown` and is logged.
    if _declared(state, kind):
        return _e_value(state, {**effect, "type": "value", "name": kind}, ctx)

    return _unknown(kind, effect)


def apply_effects(
    state: GameState,
    effects: list[dict[str, Any]],
    *,
    ledger: Optional[Any] = None,
    by: str = WRITER_ENGINE,
    turn: int = 0,
) -> list[dict[str, Any]]:
    """
    Apply a list of effects in order, returning one description per entry.

    Args:
        state: Mutable game state.
        effects: Effect dicts. A non-list is tolerated and treated as empty,
            because this is fed directly from YAML.
        ledger: Optional StoryLedger for ``ledger_fact`` effects.
        by: Writer id, applied to every effect in the list.
        turn: Turn number, recorded in the journal.

    Returns:
        Descriptions, same length and order as the input.
    """
    if not isinstance(effects, list):
        return []
    return [apply_effect(state, e, ledger=ledger, by=by, turn=turn) for e in effects]


__all__ = [
    "EQUIP_ID_PREFIX",
    "EQUIP_NEVER_EXPIRES",
    "EffectContext",
    "EffectHandler",
    "apply_effect",
    "apply_effects",
    "effect_kind",
    "equip_effect_ids",
    "equipped_items",
    "register_effect_kind",
    "registered_kinds",
    "resolve_day",
    "wound_mitigation",
]
