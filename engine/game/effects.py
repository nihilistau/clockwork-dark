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

Version: v0.2.0 [2026-08-08]
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from engine.game.state import GameState, InventoryItem, TimedEffect, Wound

logger = logging.getLogger(__name__)

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


def apply_effect(
    state: GameState,
    effect: dict[str, Any],
    *,
    ledger: Optional[Any] = None,
) -> dict[str, Any]:
    """
    Apply one declared effect to the game state.

    Args:
        state: Mutable game state.
        effect: Effect dict with a ``type`` key. Shape depends on the type; see
            data/tables/*.yaml for worked examples.
        ledger: Optional StoryLedger. Required only for ``ledger_fact``; when
            absent that effect type is skipped rather than failing.

    Returns:
        Description dict. Always has ``type``, ``ok`` and ``text``. ``ok`` is
        False for unknown or unusable effects; this function does not raise.
    """
    if not isinstance(effect, dict):
        return _unknown("malformed", {"raw": effect})

    kind = str(effect.get("type", "")).strip().lower()
    if not kind:
        return _unknown("missing_type", effect)

    # -- stats and pools -------------------------------------------------
    if kind == "stat":
        name = str(effect.get("stat", "")).strip()
        if not name:
            return _unknown("stat", effect)
        return _apply_stat(state, name, _int(effect.get("delta")))

    if kind in _STAT_ALIASES:
        return _apply_stat(state, kind, _int(effect.get("delta")))

    if kind == "hunger":
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

    if kind == "awareness":
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

    if kind == "reputation":
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

    # -- inventory -------------------------------------------------------
    if kind == "item":
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
            state.inventory.append(
                InventoryItem(id=item_id, name=name, qty=qty, tags=tags)
            )
        return {
            "type": "item",
            "item_id": item_id,
            "qty": qty,
            "ok": True,
            "text": f"gained {qty}x {name}",
        }

    if kind == "remove_item":
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

    # -- status ----------------------------------------------------------
    if kind == "wound":
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

    if kind == "heal_wound":
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
            "text": (
                "closed: " + ", ".join(healed) if healed else "nothing needed binding"
            ),
        }

    if kind == "clear_condition":
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

    if kind == "equip":
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

    if kind == "unequip":
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

    if kind == "check_penalty":
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

    if kind == "flag":
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

    if kind == "ledger_fact":
        text = str(effect.get("text") or "").strip()
        if ledger is None or not text:
            # No ledger in scope is normal outside a turn (tests, world sim).
            return {
                "type": "ledger_fact",
                "ok": False,
                "text": "no ledger in scope; fact dropped",
            }
        ledger.add_fact(
            text,
            kind=str(effect.get("kind") or "engine"),
            subject_id=str(effect.get("subject_id") or ""),
            turn=state.turn_number,
            day=state.world_day,
            source="engine",
        )
        return {"type": "ledger_fact", "ok": True, "text": f"remembered: {text}"}

    return _unknown(kind, effect)


def apply_effects(
    state: GameState,
    effects: list[dict[str, Any]],
    *,
    ledger: Optional[Any] = None,
) -> list[dict[str, Any]]:
    """
    Apply a list of effects in order, returning one description per entry.

    Args:
        state: Mutable game state.
        effects: Effect dicts. A non-list is tolerated and treated as empty,
            because this is fed directly from YAML.
        ledger: Optional StoryLedger for ``ledger_fact`` effects.

    Returns:
        Descriptions, same length and order as the input.
    """
    if not isinstance(effects, list):
        return []
    return [apply_effect(state, e, ledger=ledger) for e in effects]
