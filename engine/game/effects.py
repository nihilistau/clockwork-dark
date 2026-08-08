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
through here by design (CLAUDE.md rule 3). The one-writer rule was quietly also
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

Version: v0.3.0 [2026-08-08]
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
REPUTATION_MIN, REPUTATION_MAX = -100, 100
HUNGER_MIN, HUNGER_MAX = 0.0, 100.0

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


@effect_kind("reputation")
def _e_reputation(
    state: GameState, effect: dict[str, Any], ctx: EffectContext
) -> dict[str, Any]:
    faction = str(effect.get("faction") or effect.get("id") or "").strip()
    if not faction:
        return _unknown("reputation", effect)
    delta = _int(effect.get("delta"))
    before = _int(state.reputations.get(faction, 0))
    after = int(_clamp(before + delta, REPUTATION_MIN, REPUTATION_MAX))
    state.reputations[faction] = after
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
    return {
        "type": "item",
        "item_id": item_id,
        "qty": qty,
        "ok": True,
        "text": f"gained {qty}x {name}",
    }


@effect_kind("remove_item")
def _e_remove_item(
    state: GameState, effect: dict[str, Any], ctx: EffectContext
) -> dict[str, Any]:
    item_id = str(effect.get("item_id") or effect.get("id") or "").strip()
    if not item_id:
        return _unknown("remove_item", effect)
    want = max(1, _int(effect.get("qty"), 1))
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
    expires = resolve_day(
        state,
        effect.get("expires_day"),
        default_days=max(1, _int(effect.get("days"), 1)),
    )
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
    value = bool(effect.get("value", True))
    state.flags[name] = value
    return {
        "type": "flag",
        "flag": name,
        "value": value,
        "ok": True,
        "text": f"flag {name}={value}",
    }


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
    return {
        "type": "value",
        "name": name,
        "label": label,
        "kind": spec.kind if spec is not None else "meter",
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
        receipt = endings_module.lock(state, ending_id, ledger=ctx.ledger)
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
