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

Version: v0.1.0 [2026-08-07]
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
        wound = Wound(
            id=str(effect.get("id") or _next_id("wound", state.wounds, day)),
            text=str(effect.get("text") or "Injury"),
            severity=max(1, _int(effect.get("severity"), 1)),
            check_penalty=_int(effect.get("check_penalty"), -1),
            skills=[str(s) for s in (effect.get("skills") or [])],
            heals_on_day=resolve_day(state, effect.get("heals_on_day"), default_days=3),
        )
        state.wounds.append(wound)
        return {
            "type": "wound",
            "id": wound.id,
            "severity": wound.severity,
            "heals_on_day": wound.heals_on_day,
            "ok": True,
            "text": f"wounded: {wound.text} (heals day {wound.heals_on_day})",
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
