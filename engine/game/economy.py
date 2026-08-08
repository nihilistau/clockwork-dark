"""
Labour and Wages
================

Hours for money. The economy the Quiet Life arc was promised and never got.

THE GAP THIS MODULE CLOSES: DESIGN.md makes "become a baker, not a hero" a
pillar, data/quests/arcs.yaml ships a ``quiet_life`` arc, and there has never
been a way to earn a copper by working. Gold entered the game as a quest reward
and left it at a vendor's counter. ``scripts/simulate.py`` measured every
policy -- including ``baker``, which never leaves Edgewood -- finishing 200
turns at zero gold, net -5 for the whole run. A baker who cannot be paid for
baking is not a playstyle, it is a skin over the same loop.

WHAT A WAGE RESPONDS TO, and why each one is here rather than a flat number:

    the degree      a bad day's work is paid like a bad day's work, so the
                    skill check has stakes on a job you cannot die at
    reputation      the people paying decide what you are worth; this is the
                    first thing in the game that makes standing pay rent
    the evil phase  nobody hires when the village is emptying. This is the
                    honest answer to DESIGN_REVIEW.md's R-06: the doomsday
                    clock should change what your *life* is, not only what
                    the monsters are, and a baker feels `spreading` as the
                    morning the oven shift is not on offer
    a daily cap     a shift is a shift. Without it labour is an infinite gold
                    button and the whole economy is decoration

The cap is held as a ``TimedEffect`` (kind ``shift``) that expires with the
day, the same trick foraging uses for node wear: no new save field, and the
clock's existing expiry sweep is the reset.

All numbers live in data/tables/labour.yaml. This module contains none.

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

#: TimedEffect.kind recording a shift worked today. Not a check_penalty, so
#: engine/game/checks.py::gather_modifiers steps over it.
SHIFT_EFFECT_KIND = "shift"


def _table_path() -> Path:
    rel = get_config().get("paths.tables", "data/tables")
    return _ROOT / str(rel) / "labour.yaml"


@lru_cache(maxsize=8)
def _read_rules(path_str: str, _mtime: float) -> dict[str, Any]:
    """Parse labour.yaml, memoized on (path, mtime) so an edit invalidates."""
    try:
        with Path(path_str).open(encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}
    except (OSError, yaml.YAMLError) as exc:
        logger.warning("[economy] Unreadable table (operation=_read_rules): %s", exc)
        return {}


def load_rules() -> dict[str, Any]:
    """
    Load the labour table for the active game.

    A game with no labour table is a supported configuration, not a fault: it
    logs at info and every entry point degrades to "there is no work here".
    """
    path = _table_path()
    try:
        mtime = path.stat().st_mtime
    except OSError:
        logger.info(
            "[economy] No labour table for this game (operation=load_rules, path=%s)",
            path,
        )
        return {}
    return _read_rules(str(path), mtime)


def configured() -> bool:
    """True when the active game declares at least one job."""
    return bool(load_rules().get("jobs"))


def _cfg() -> dict[str, Any]:
    return load_rules().get("labour", {}) or {}


def jobs() -> dict[str, dict[str, Any]]:
    """Every declared job, keyed by id."""
    out: dict[str, dict[str, Any]] = {}
    for row in load_rules().get("jobs") or []:
        if isinstance(row, dict) and row.get("id"):
            out[str(row["id"])] = row
    return out


def get_job(job_id: str) -> Optional[dict[str, Any]]:
    """One job row, or None."""
    return jobs().get(str(job_id))


# ---------------------------------------------------------------------------
# the daily cap
# ---------------------------------------------------------------------------


def _shift_effects(state: GameState) -> list[TimedEffect]:
    """Shift records that have not yet expired. The clock sweeps the rest."""
    return [e for e in state.active_effects if e.kind == SHIFT_EFFECT_KIND]


def shifts_worked(state: GameState, job_id: str = "") -> int:
    """
    Shifts worked today, in total or for one job.

    Reads ``expires_day`` rather than a stored date so it agrees with whatever
    the clock has already swept: a record for a day that has passed is gone,
    and one for today is still standing.
    """
    today = state.world_day
    rows = [e for e in _shift_effects(state) if e.expires_day >= today]
    if job_id:
        rows = [e for e in rows if e.id == f"shift:{job_id}"]
    return sum(max(0, int(e.delta)) for e in rows)


def _record_shift(state: GameState, job_id: str) -> None:
    """Mark one shift worked. Expires with the day."""
    marker_id = f"shift:{job_id}"
    effect = next((e for e in _shift_effects(state) if e.id == marker_id), None)
    if effect is None or effect.expires_day < state.world_day:
        if effect is not None:
            state.active_effects.remove(effect)
        effect = TimedEffect(
            id=marker_id,
            kind=SHIFT_EFFECT_KIND,
            text=f"worked {job_id} today",
            delta=0,
            expires_day=state.world_day,
        )
        state.active_effects.append(effect)
    effect.delta = int(effect.delta) + 1
    effect.expires_day = state.world_day


# ---------------------------------------------------------------------------
# what a day is worth
# ---------------------------------------------------------------------------


def demand_multiplier(state: GameState, job: dict[str, Any]) -> float:
    """
    How much this employer wants the work done, given the state of the world.

    A zero means NOT HIRING, and the job leaves the board entirely rather than
    offering a shift that pays nothing -- being told there is no work is a
    different piece of information from being told the work is worthless, and
    it is the one the fiction wants.
    """
    table = job.get("demand") or {}
    if not table:
        return 1.0
    return max(0.0, float(table.get(state.evil_phase.value, 1.0) or 0.0))


def wage_multiplier(state: GameState, job: dict[str, Any]) -> dict[str, Any]:
    """
    The itemised multipliers on a job's base wage.

    Returned as a breakdown rather than a product, for the same reason
    engine/game/checks.py itemises a roll: the player must be able to see that
    the pay dropped because the militia is buying every hand in the district,
    not because the engine felt like it.
    """
    faction = str(job.get("faction") or "")
    # Reputation prices the work. price_multiplier is what a vendor CHARGES,
    # so it is inverted here -- being trusted means you buy cheap and you are
    # paid well, and both are the same number read from opposite sides.
    standing_mult = 1.0
    if faction:
        standing_mult = round(2.0 - reputation_module.price_multiplier(state, faction), 3)
    demand = demand_multiplier(state, job)
    return {
        "base_wage": int(job.get("base_wage", 0) or 0),
        "standing": standing_mult,
        "standing_label": reputation_module.standing(state, faction) if faction else "",
        "demand": demand,
        "phase": state.evil_phase.value,
    }


def _requirements_met(state: GameState, job: dict[str, Any]) -> tuple[bool, str]:
    """Check a job's optional gates. Returns (ok, reason-if-not)."""
    requires = job.get("requires") or {}
    item = requires.get("item")
    if item and not inventory_module.holds(state, str(item)):
        return False, f"You need a {inventory_module.name_of(str(item))} for that work."
    standing = requires.get("standing") or {}
    if standing:
        faction = str(standing.get("faction") or "")
        minimum = standing.get("minimum")
        if faction and minimum is not None:
            if not reputation_module.gate_allows(state, faction, minimum):
                return False, (
                    f"{reputation_module.faction_name(faction)} will not put "
                    "work your way yet."
                )
    return True, ""


def available(state: GameState, location_id: str = "") -> list[dict[str, Any]]:
    """
    Jobs the player could take right now, with what each would pay.

    Args:
        state: Game state. Not mutated.
        location_id: Place to ask about; defaults to where the player is.

    Returns:
        One row per offered job: id, name, hours, the check it needs, the
        expected wage at a clean success, and the in-kind pay. A job whose
        demand is zero, whose gate is unmet or whose daily cap is spent is
        absent, so the narrator is never in a position to offer work the
        engine will then refuse.
    """
    location_id = location_id or state.location_id
    if not configured():
        return []

    cfg = _cfg()
    day_cap = int(cfg.get("shifts_per_day", 2) or 0)
    repeat_cap = int(cfg.get("repeats_per_day", 1) or 0)
    worked_today = shifts_worked(state)

    rows: list[dict[str, Any]] = []
    for job_id, job in sorted(jobs().items()):
        where = str(job.get("location_id") or "")
        if where and where != location_id:
            continue
        if demand_multiplier(state, job) <= 0:
            continue
        ok, _reason = _requirements_met(state, job)
        if not ok:
            continue
        if day_cap and worked_today >= day_cap:
            continue
        if repeat_cap and shifts_worked(state, job_id) >= repeat_cap:
            continue

        mult = wage_multiplier(state, job)
        rows.append(
            {
                "id": job_id,
                "name": str(job.get("name") or job_id),
                "blurb": str(job.get("blurb") or "").strip(),
                "location_id": where or location_id,
                "skill": str(job.get("skill", "craft")),
                "difficulty": str(job.get("difficulty", "standard")),
                "hours": float(job.get("hours", 1) or 0),
                "stamina_cost": int(job.get("stamina_cost", 0) or 0),
                "faction": str(job.get("faction") or ""),
                "expected_wage": _wage_for(state, job, "success"),
                "wage_breakdown": mult,
                "in_kind": [
                    {
                        "item_id": str(row.get("item_id")),
                        "name": inventory_module.name_of(str(row.get("item_id"))),
                        "qty": int(row.get("qty", 1) or 1),
                    }
                    for row in (job.get("in_kind") or [])
                    if isinstance(row, dict) and row.get("item_id")
                ],
            }
        )
    return rows


def _wage_for(state: GameState, job: dict[str, Any], degree: str) -> int:
    """Copper paid for one degree of success, all multipliers applied."""
    mult = wage_multiplier(state, job)
    share = float((job.get("pay") or {}).get(degree, 0.0) or 0.0)
    raw = mult["base_wage"] * share * float(mult["standing"]) * float(mult["demand"])
    # Rounded down: an employer counting copper into your hand does not round
    # up, and a floor keeps every wage in this table an integer the UI can show.
    return max(0, int(raw))


# ---------------------------------------------------------------------------
# working
# ---------------------------------------------------------------------------


def work(
    state: GameState,
    job_id: str,
    *,
    ledger: Optional[Any] = None,
) -> dict[str, Any]:
    """
    Take a shift. Spends the hours and the stamina, pass or fail.

    Args:
        state: Mutable game state.
        job_id: Job id from data/tables/labour.yaml.
        ledger: Optional StoryLedger for the check's boon/complication effects.

    Returns:
        Receipt dict: the check, the itemised wage breakdown, the coin, the
        in-kind pay, any reputation moved, and the hours spent. A refusal is
        ``success: false`` with a message and costs nothing -- the caller may
        be a language model asking for work that is not on offer.
    """
    from engine.game.clock import advance_time

    if not configured():
        return {"success": False, "message": "There is no paid work in this story."}

    job = get_job(job_id)
    if job is None:
        return {"success": False, "job_id": job_id, "message": f"No such work: {job_id}."}

    where = str(job.get("location_id") or "")
    if where and where != state.location_id:
        return {
            "success": False,
            "job_id": job_id,
            "message": f"That work happens at {where}, not here.",
        }

    demand = demand_multiplier(state, job)
    if demand <= 0:
        return {
            "success": False,
            "job_id": job_id,
            "message": "Nobody is hiring for that. Not now.",
            "phase": state.evil_phase.value,
        }

    ok, reason = _requirements_met(state, job)
    if not ok:
        return {"success": False, "job_id": job_id, "message": reason}

    cfg = _cfg()
    day_cap = int(cfg.get("shifts_per_day", 2) or 0)
    repeat_cap = int(cfg.get("repeats_per_day", 1) or 0)
    if day_cap and shifts_worked(state) >= day_cap:
        return {
            "success": False,
            "job_id": job_id,
            "message": "You have already given this day everything it is going to get.",
            "shifts_worked": shifts_worked(state),
        }
    if repeat_cap and shifts_worked(state, job_id) >= repeat_cap:
        return {
            "success": False,
            "job_id": job_id,
            "message": "That shift is done for today.",
        }

    hours = float(job.get("hours", 1) or 0)
    stamina_cost = int(job.get("stamina_cost", 0) or 0)

    # Time and stamina first, and unconditionally. A shift you were bad at
    # still took the whole day, or failing costs nothing and the check is
    # decoration.
    if hours > 0:
        advance_time(state, hours)
    if stamina_cost:
        effects_module.apply_effect(state, {"type": "stamina", "delta": -stamina_cost})

    result = checks_module.resolve(
        state,
        str(job.get("skill", "craft")),
        str(job.get("difficulty", "standard")),
        ledger=ledger,
    )
    degree = result.degree

    wage = _wage_for(state, job, degree)
    applied: list[dict[str, Any]] = []
    if wage:
        applied.append(effects_module.apply_effect(state, {"type": "gold", "delta": wage}))

    paid_in_kind: list[dict[str, Any]] = []
    for row in job.get("in_kind") or []:
        if not isinstance(row, dict) or not row.get("item_id"):
            continue
        if degree not in [str(d) for d in (row.get("degrees") or [])]:
            continue
        item_id, qty = str(row["item_id"]), max(1, int(row.get("qty", 1) or 1))
        applied.append(inventory_module.grant(state, item_id, qty))
        paid_in_kind.append(
            {"item_id": item_id, "name": inventory_module.name_of(item_id), "qty": qty}
        )

    standing_moved: list[dict[str, Any]] = []
    for row in job.get("reputation") or []:
        if not isinstance(row, dict):
            continue
        if degree not in [str(d) for d in (row.get("degrees") or [])]:
            continue
        faction = str(row.get("faction") or "")
        delta = int(row.get("delta", 0) or 0)
        if not faction or not delta:
            continue
        delta = _plateau(state, faction, delta)
        after = reputation_module.adjust(state, faction, delta, reason=f"work:{job_id}")
        standing_moved.append(
            {
                "faction": faction,
                "delta": delta,
                "score": after,
                "standing": reputation_module.standing(state, faction),
            }
        )

    _record_shift(state, job_id)

    text = str(
        job.get("success_text" if degree != "failure" else "failure_text") or ""
    ).strip()

    logger.info(
        "[economy] Shift worked (operation=work, job=%s, degree=%s, wage=%s, "
        "phase=%s, day=%s)",
        job_id,
        degree,
        wage,
        state.evil_phase.value,
        state.world_day,
    )

    return {
        "success": degree != "failure",
        "job_id": job_id,
        "name": str(job.get("name") or job_id),
        "check": result.to_dict(),
        "degree": degree,
        "wage": wage,
        "wage_breakdown": wage_multiplier(state, job),
        "gold": state.stats.gold,
        "in_kind": paid_in_kind,
        "reputation": standing_moved,
        "effects": applied,
        "hours": hours,
        "stamina_cost": stamina_cost,
        "stamina": state.stats.stamina,
        "hunger": round(state.hunger, 1),
        "shifts_worked": shifts_worked(state),
        "shifts_per_day": day_cap,
        "world_day": state.world_day,
        "text": text,
    }


def _plateau(state: GameState, faction: str, delta: int) -> int:
    """
    Halve standing gains once past the configured band.

    Chores should build a reputation from nothing and then stop being how you
    build one. Without this, a baker reaches ``trusted`` with every faction in
    the game by repeating the cheapest job on the board, and standing stops
    meaning anything the moment it becomes a grind counter.
    """
    if delta <= 0:
        return delta
    band = str(_cfg().get("reputation_plateau") or "")
    if not band:
        return delta
    if reputation_module.gate_allows(state, faction, band):
        return max(1, delta // 2)
    return delta


def snapshot(state: GameState) -> dict[str, Any]:
    """Read-only labour status for prompts, the UI and the Assistant."""
    cfg = _cfg()
    return {
        "configured": configured(),
        "location_id": state.location_id,
        "shifts_worked_today": shifts_worked(state),
        "shifts_per_day": int(cfg.get("shifts_per_day", 0) or 0),
        "phase": state.evil_phase.value,
        "here": available(state),
        "elsewhere": [
            {
                "id": job_id,
                "name": str(job.get("name") or job_id),
                "location_id": str(job.get("location_id") or ""),
                "hiring": demand_multiplier(state, job) > 0,
            }
            for job_id, job in sorted(jobs().items())
            if str(job.get("location_id") or "") != state.location_id
        ],
    }
