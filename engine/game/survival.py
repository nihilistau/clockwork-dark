"""
Survival
========

Hunger, rest and food -- the loop that makes stamina a resource instead of a
countdown to a dead save.

THE BUG THIS MODULE FIXES: stamina was decremented on travel
(``engine/game/engine.py``: ``stamina_cost = max(1, hours * 5)``) and restored
absolutely nowhere. Nothing in the codebase ever raised ``stats.stamina``. The
round trip to millhaven_gate costs 40 stamina, so after five of them the player
sat at 0 with every travel edge refusing on "Not enough stamina" and no action
in the game capable of giving any back. That is a permanent soft-lock, and it
was reachable inside the first hour of play.

The fix is not "regenerate stamina over time". Awake regeneration is zero, on
purpose: rest has to be a *choice* with a price, because the price is hours, and
hours are what the evil clock eats. Stopping to sleep is the most expensive safe
thing you can do, and it has to stay that way for the background threat to mean
anything.

``tick`` is wired automatically -- ``engine/game/clock.py::advance_time`` imports
this module and calls it -- so hunger accrues on every hour the world advances
regardless of which action spent them.

Version: v0.1.0 [2026-08-07]
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

import yaml

from engine.config import get_config
from engine.game import effects as effects_module
from engine.game.state import GameState

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parents[2]


def _rules_path() -> Optional[Path]:
    """The survival rules, or None when this story declares no rules directory."""
    rel = str(get_config().get("paths.rules", "") or "").strip()
    return (_ROOT / rel / "survival.yaml") if rel else None


@lru_cache(maxsize=8)
def _read_rules(path_str: str, _mtime: float) -> dict[str, Any]:
    """
    Parse survival.yaml, memoized on (path, mtime).

    Keyed on mtime as well as path so the cache invalidates on a file edit or a
    repointed ``paths.rules`` without this module having to be registered in
    engine/config.py::reset_config, which it does not own.
    """
    try:
        with Path(path_str).open(encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}
    except (OSError, yaml.YAMLError) as exc:
        logger.warning("[survival] Unreadable rules (operation=_read_rules): %s", exc)
        return {}


def load_rules() -> dict[str, Any]:
    """Load data/rules/survival.yaml."""
    path = _rules_path()
    if path is None:
        logger.debug("[survival] Story declares no rules (operation=load_rules)")
        return {}
    try:
        mtime = path.stat().st_mtime
    except OSError:
        logger.warning(
            "[survival] Rules file missing (operation=load_rules, path=%s)", path
        )
        return {}
    return _read_rules(str(path), mtime)


def _thresholds(rules: dict[str, Any]) -> dict[str, float]:
    return {
        k: float(v)
        for k, v in (rules.get("hunger", {}).get("thresholds", {}) or {}).items()
    }


def hunger_stage(state: GameState, rules: Optional[dict[str, Any]] = None) -> str:
    """Coarse hunger label for prompts and the UI: fed|peckish|hungry|starving."""
    marks = _thresholds(rules or load_rules())
    hunger = state.hunger
    if hunger >= marks.get("starving", 85.0):
        return "starving"
    if hunger >= marks.get("hungry", 60.0):
        return "hungry"
    if hunger >= marks.get("peckish", 40.0):
        return "peckish"
    return "fed"


def stamina_cap(state: GameState, rules: Optional[dict[str, Any]] = None) -> int:
    """
    Highest stamina the player can currently hold.

    Below the `hungry` threshold this is simply max_stamina. Above it, the cap
    drops -- a hungry body does not hold a full tank. Implemented as a cap
    rather than by mutating ``max_stamina`` so that eating restores the ceiling
    instantly and no permanent damage can accumulate from a transient state.
    """
    rules = rules or load_rules()
    hunger_cfg = rules.get("hunger", {})
    cap = int(state.stats.max_stamina)
    if state.hunger >= float(_thresholds(rules).get("hungry", 60.0)):
        cap -= int(hunger_cfg.get("hungry_stamina_cap_penalty", 20))
    return max(0, cap)


def tick(state: GameState, hours: float) -> dict[str, Any]:
    """
    Accrue hunger and apply its penalties for elapsed time.

    Called by ``clock.advance_time`` for every hour the world moves, so it must
    stay cheap and must never raise -- a survival failure mid-turn would abort
    the clock and desynchronise the evil ticker from the calendar.

    Args:
        state: Mutable game state.
        hours: Hours elapsed. Zero or negative is a no-op.

    Returns:
        Dict describing hunger movement, stage, any starvation damage and any
        stamina clamped off by the hunger cap.
    """
    if hours <= 0:
        return {"hours": 0.0, "hunger": round(state.hunger, 1), "stage": hunger_stage(state)}

    rules = load_rules()
    hunger_cfg = rules.get("hunger", {})

    before = state.hunger
    # The rules' own ceiling is applied to the DELTA, so the one writer gets a
    # movement it can apply verbatim: the hunger kind clamps to the engine's
    # [0, 100] band, and this keeps a story's tighter `max` binding too.
    ceiling = float(hunger_cfg.get("max", 100.0))
    gain = float(hunger_cfg.get("per_hour", 2.0)) * float(hours)
    effects_module.apply_effect(
        state, {"type": "hunger", "delta": min(ceiling, before + gain) - before}
    )

    marks = _thresholds(rules)
    starving_at = float(marks.get("starving", 85.0))

    hp_lost = 0
    if state.hunger >= starving_at:
        # HP is an int, so fractional-hour damage is rounded rather than
        # accumulated in a field this dataclass does not have. Travel legs are
        # whole hours; sub-hour actions therefore cost nothing, which is the
        # forgiving direction to be wrong in.
        rate = float(hunger_cfg.get("starving_hp_per_hour", 1.0))
        hp_lost = int(round(rate * float(hours)))
        if hp_lost:
            effects_module.apply_effect(state, {"type": "hp", "delta": -hp_lost})

    # Awake stamina regeneration is zero by design; the knob exists so the
    # decision is visible in data rather than implied by an absent line of code.
    regen = float(rules.get("stamina", {}).get("awake_regen_per_hour", 0.0))
    if regen:
        effects_module.apply_effect(
            state, {"type": "stamina", "delta": int(regen * float(hours))}
        )

    cap = stamina_cap(state, rules)
    clamped = 0
    if state.stats.stamina > cap:
        # The hunger cap is enforced as a negative delta through the writer,
        # like every other stamina movement in this function.
        clamped = state.stats.stamina - cap
        effects_module.apply_effect(state, {"type": "stamina", "delta": -clamped})

    stage = hunger_stage(state, rules)
    if stage == "starving" and hunger_stage_of(before, rules) != "starving":
        logger.info(
            "[survival] Player is starving (operation=tick, day=%s, hunger=%.0f)",
            state.world_day,
            state.hunger,
        )

    return {
        "hours": float(hours),
        "hunger_before": round(before, 1),
        "hunger": round(state.hunger, 1),
        "stage": stage,
        "hp_lost": hp_lost,
        "stamina_cap": cap,
        "stamina_clamped": clamped,
        "stamina": state.stats.stamina,
    }


def hunger_stage_of(hunger: float, rules: dict[str, Any]) -> str:
    """Stage label for a bare hunger number. Used to detect threshold crossings."""
    marks = _thresholds(rules)
    if hunger >= marks.get("starving", 85.0):
        return "starving"
    if hunger >= marks.get("hungry", 60.0):
        return "hungry"
    if hunger >= marks.get("peckish", 40.0):
        return "peckish"
    return "fed"


def rest_kinds() -> list[str]:
    """Ids of every configured rest action."""
    return list((load_rules().get("rest", {}) or {}).keys())


def _resolve_rest_kind(
    state: GameState, kind: str, rest_cfg: dict[str, Any]
) -> tuple[str, dict[str, Any], str]:
    """
    Pick the rest entry actually used, honouring location requirements.

    A bed you cannot reach downgrades to sleeping rough. It never refuses:
    refusing rest is precisely how the stamina soft-lock was built, and any new
    gate on resting rebuilds it.
    """
    note = ""
    spec = rest_cfg.get(kind)
    if spec is None:
        fallback = "rest_short" if "rest_short" in rest_cfg else next(iter(rest_cfg), "")
        logger.warning(
            "[survival] Unknown rest kind (operation=rest, got=%s, using=%s)",
            kind,
            fallback,
        )
        return fallback, rest_cfg.get(fallback, {}), f"unknown rest '{kind}'"

    allowed = spec.get("locations")
    if allowed and state.location_id not in list(allowed):
        alt = str(spec.get("fallback") or "")
        if alt and alt in rest_cfg:
            return alt, rest_cfg[alt], f"no bed at {state.location_id}"
    return kind, spec, note


def rest(state: GameState, kind: str = "rest_short") -> dict[str, Any]:
    """
    Stop and recover. The only thing in the game that raises stamina.

    Time is advanced through ``clock.advance_time`` so the evil ticker, timed
    effect expiry and hunger all move with it -- resting is safe for the body
    and expensive for the world, which is the whole point.

    Restoration is applied AFTER the clock moves, because ``tick`` clamps
    stamina to the hunger cap; restoring first would let the clamp eat the rest.

    Args:
        state: Mutable game state.
        kind: rest_short | sleep_bed | sleep_rough (see data/rules/survival.yaml).

    Returns:
        Outcome dict: kind used, hours spent, stamina before/after, any check
        result, and a narration-ready text line.
    """
    from engine.game.clock import advance_time

    rules = load_rules()
    rest_cfg = rules.get("rest", {}) or {}
    if not rest_cfg:
        return {"success": False, "kind": kind, "message": "No rest rules configured."}

    used, spec, note = _resolve_rest_kind(state, kind, rest_cfg)
    hours = float(spec.get("hours", 1))
    before = state.stats.stamina

    advance = advance_time(state, hours)

    # Sleeping rough is a survival check: exposure, cold, and whatever is
    # keeping its distance. Rolled by the engine, never by the narrator.
    check_result: Optional[dict[str, Any]] = None
    failed = False
    check_cfg = spec.get("check")
    if isinstance(check_cfg, dict):
        from engine.game import checks

        outcome = checks.resolve(
            state,
            str(check_cfg.get("skill", "survival")),
            str(check_cfg.get("difficulty", "standard")),
        )
        check_result = outcome.to_dict()
        failed = not outcome.success

    on_failure = spec.get("on_failure", {}) if failed else {}
    stamina_spec = on_failure.get("stamina", spec.get("stamina", 0))
    hp_delta = int(on_failure.get("hp", spec.get("hp", 0)))

    cap = stamina_cap(state, rules)
    if str(stamina_spec).lower() == "full":
        restored = cap - state.stats.stamina
    else:
        restored = int(stamina_spec)
    if restored > 0:
        # Bounded against the hunger cap BEFORE the write -- the stat writer
        # only knows max_stamina, and the cap can sit below it.
        gain = min(cap, state.stats.stamina + restored) - state.stats.stamina
        if gain > 0:
            effects_module.apply_effect(state, {"type": "stamina", "delta": gain})
    if hp_delta:
        effects_module.apply_effect(state, {"type": "hp", "delta": hp_delta})

    text = str(on_failure.get("text") or spec.get("text") or "You rest.")
    if note:
        text = f"{text} ({note})"

    logger.info(
        "[survival] Rested (operation=rest, kind=%s, hours=%s, stamina=%s)",
        used,
        hours,
        state.stats.stamina,
    )

    return {
        "success": True,
        "kind": used,
        "requested_kind": kind,
        "hours": hours,
        "stamina_before": before,
        "stamina": state.stats.stamina,
        "stamina_cap": cap,
        "hp": state.stats.hp,
        "hunger": round(state.hunger, 1),
        "stage": hunger_stage(state, rules),
        "check": check_result,
        "failed_check": failed,
        "world_day": state.world_day,
        "world_hour": state.world_hour,
        "time_advance": advance.to_dict(),
        "text": text,
    }


def food_value(item_id: str, tags: list[str], rules: dict[str, Any]) -> Optional[dict[str, Any]]:
    """
    Nutrition for an item, or None if it is not food.

    Falls back to the `default` row for anything carrying an edible tag, so a
    procedurally generated ration is edible without a table entry.
    """
    eat_cfg = rules.get("eat", {}) or {}
    entry = (eat_cfg.get("items", {}) or {}).get(item_id)
    if entry:
        return dict(entry)
    edible_tags = set(str(t) for t in (eat_cfg.get("edible_tags") or []))
    if edible_tags.intersection(str(t) for t in tags):
        return dict(eat_cfg.get("default", {}) or {})
    return None


def eat(state: GameState, item_id: str) -> dict[str, Any]:
    """
    Consume one food item from inventory.

    Args:
        state: Mutable game state.
        item_id: Inventory item id to eat.

    Returns:
        Outcome dict. ``success`` is False (with a message, not an exception)
        when the item is absent or inedible -- both are ordinary player mistakes
        the Storyteller should narrate, not engine faults.
    """
    from engine.game.clock import advance_time

    rules = load_rules()
    entry = next((i for i in state.inventory if i.id == item_id), None)
    if entry is None or entry.qty < 1:
        return {"success": False, "item_id": item_id, "message": "You have none of that."}

    value = food_value(item_id, list(entry.tags), rules)
    if value is None:
        return {"success": False, "item_id": item_id, "message": f"{entry.name} is not food."}

    before = state.hunger
    hours = float((rules.get("eat", {}) or {}).get("hours", 0.0))
    if hours > 0:
        advance_time(state, hours)

    applied = effects_module.apply_effects(
        state,
        [
            {"type": "remove_item", "item_id": item_id, "qty": 1},
            {"type": "hunger", "delta": float(value.get("hunger", -15))},
            {"type": "stamina", "delta": int(value.get("stamina", 0))},
        ],
    )

    logger.info(
        "[survival] Ate (operation=eat, item=%s, hunger=%.0f)", item_id, state.hunger
    )

    return {
        "success": True,
        "item_id": item_id,
        "name": entry.name,
        "hunger_before": round(before, 1),
        "hunger": round(state.hunger, 1),
        "stage": hunger_stage(state, rules),
        "stamina": state.stats.stamina,
        "effects": applied,
        "text": str(value.get("text") or f"You eat the {entry.name.lower()}."),
    }


def snapshot(state: GameState) -> dict[str, Any]:
    """Read-only survival status for prompts and the UI."""
    rules = load_rules()
    return {
        "hunger": round(state.hunger, 1),
        "stage": hunger_stage(state, rules),
        "stamina": state.stats.stamina,
        "stamina_cap": stamina_cap(state, rules),
        "max_stamina": state.stats.max_stamina,
        "hp": state.stats.hp,
        "max_hp": state.stats.max_hp,
        "wounds": [w.text for w in state.wounds],
    }
