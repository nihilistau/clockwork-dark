"""
Encounters
==========

Conflict as a short contested scene -- not a combat system.

THE GAP THIS MODULE CLOSES: every travel edge in
``engine/game/locations.py`` has carried a ``danger_dc`` since the graph was
written, and nothing has ever read it. Travel was a stamina cost and a clock
advance; the road between Edgewood and Millhaven was exactly as safe at
midnight during ``consuming`` as at noon on day one. Alongside that,
``stats.hp`` was never decremented by any code path in this project's history
and ``state.ended`` was never set to True. This module is the first thing that
can actually hurt the player.

WHY NOT TURN-BASED COMBAT: DESIGN.md's pillar is "no fireballs, no MMO combat
spam" -- magic is costly, rare, and mostly a bad idea. Initiative order, armour
class and a per-round turn loop would contradict that, double the UI surface,
and turn every roadside argument into a five-minute minigame. So a conflict is
a SCENE: one to three contested checks against a threat's ``resolve``, then it
is over. The player picks an *approach* (talk, fight, sneak, pay, walk away)
and the engine resolves it through ``engine/game/checks.py`` like everything
else.

WOUNDS OVER HP: "a knife-line across your forearm, -2 to craft until day 9"
carries more weight than "-4 hp", survives into the next scene, and reads back
into narration for free. HP remains only as the death threshold -- see
``check_death`` and data/rules/death.yaml.

All numbers live in data/encounters/rules.yaml and data/rules/death.yaml. This
module contains no balance constants.

Version: v0.1.0 [2026-08-07]
"""

from __future__ import annotations

import logging
import threading
import random
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

import yaml

from engine.config import get_config
from engine.game import checks as checks_module
from engine.game import effects as effects_module
from engine.game.locations import get_edge
from engine.game.rng import ENCOUNTER, world_rng
from engine.game.state import GameState

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parents[2]

# Keys a data file may contribute. Anything else in an encounters file is
# ignored rather than rejected, so a future band file can carry notes.
_CONTENT_KEY = "encounters"
_CONFIG_KEYS = ("trigger", "scene", "degree_fallback", "default_approaches")


# ---------------------------------------------------------------------------
# loading
# ---------------------------------------------------------------------------


def _encounters_dir() -> Path:
    """Directory holding the encounter tables."""
    rel = get_config().get("paths.encounters", "data/encounters")
    return _ROOT / str(rel)


def _death_rules_path() -> Path:
    rel = get_config().get("paths.rules", "data/rules")
    return _ROOT / str(rel) / "death.yaml"


def _fingerprint(paths: list[Path]) -> tuple[Any, ...]:
    """
    Cheap change detector for a directory of YAML.

    Keyed on names and mtimes rather than just the directory path: a plain
    module-level cache would keep serving stale tables after a content edit,
    and ``engine/config.py::reset_config`` does not know about this module, so
    a repointed ``paths.encounters`` has to invalidate too.
    """
    out: list[Any] = []
    for path in paths:
        try:
            out.append((path.name, path.stat().st_mtime))
        except OSError:
            out.append((path.name, 0.0))
    return tuple(out)


@lru_cache(maxsize=8)
def _read_dir(dir_str: str, _fp: tuple[Any, ...]) -> dict[str, Any]:
    """Parse every ``*.yaml`` in the encounters directory into one table."""
    merged: dict[str, Any] = {_CONTENT_KEY: []}
    directory = Path(dir_str)
    if not directory.is_dir():
        logger.warning(
            "[encounter] Encounters directory missing (operation=_read_dir, path=%s)",
            dir_str,
        )
        return merged

    for path in sorted(directory.glob("*.yaml")):
        try:
            with path.open(encoding="utf-8") as fh:
                data = yaml.safe_load(fh) or {}
        except (OSError, yaml.YAMLError) as exc:
            # One malformed band file must not take the other three down with
            # it, and must never abort a turn mid-travel.
            logger.warning(
                "[encounter] Unreadable encounter file "
                "(operation=_read_dir, path=%s): %s",
                path.name,
                exc,
            )
            continue
        if not isinstance(data, dict):
            continue

        rows = data.get(_CONTENT_KEY) or []
        band = str(data.get("band") or path.stem)
        for row in rows:
            if isinstance(row, dict) and row.get("id"):
                row.setdefault("band", band)
                merged[_CONTENT_KEY].append(row)

        for key in _CONFIG_KEYS:
            block = data.get(key)
            if isinstance(block, dict):
                merged.setdefault(key, {}).update(block)

    return merged


def load_encounters() -> dict[str, Any]:
    """
    Load the merged encounter table.

    Returns:
        Dict with ``encounters`` (list of definitions) plus the ``trigger``,
        ``scene``, ``degree_fallback`` and ``default_approaches`` config blocks
        contributed by any file in the directory.
    """
    directory = _encounters_dir()
    paths = sorted(directory.glob("*.yaml")) if directory.is_dir() else []
    return _read_dir(str(directory), _fingerprint(paths))


def all_encounters() -> list[dict[str, Any]]:
    """Every loaded encounter definition."""
    return list(load_encounters().get(_CONTENT_KEY, []))


def get_definition(encounter_id: str) -> Optional[dict[str, Any]]:
    """Look up one encounter definition by id, or None."""
    for row in all_encounters():
        if row.get("id") == encounter_id:
            return row
    return None


def _scene_rules() -> dict[str, Any]:
    return load_encounters().get("scene", {}) or {}


@lru_cache(maxsize=4)
def _read_death(path_str: str, _mtime: float) -> dict[str, Any]:
    try:
        with Path(path_str).open(encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}
    except (OSError, yaml.YAMLError) as exc:
        logger.warning("[encounter] Unreadable death rules (operation=_read_death): %s", exc)
        return {}


def load_death_rules() -> dict[str, Any]:
    """Load data/rules/death.yaml."""
    path = _death_rules_path()
    try:
        mtime = path.stat().st_mtime
    except OSError:
        logger.warning(
            "[encounter] Death rules missing (operation=load_death_rules, path=%s)", path
        )
        return {}
    return _read_death(str(path), mtime)


# ---------------------------------------------------------------------------
# eligibility and triggering
# ---------------------------------------------------------------------------


def _as_list(value: Any) -> list[str]:
    """Coerce a YAML scalar-or-list into a list of strings."""
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(v) for v in value]
    return [str(value)]


def _seen_flag(encounter_id: str) -> str:
    """Flag name recording that a ``once`` encounter has already fired."""
    return f"encounter_seen:{encounter_id}"


def matches(state: GameState, row: dict[str, Any], from_id: str, to_id: str) -> bool:
    """
    Test one encounter definition against the current travel leg.

    An omitted filter means "any". Filters are deliberately few and flat: a
    condition language here would become a second place for content logic to
    hide, and a designer has to be able to read the table.

    Args:
        state: Game state, read for phase, hour, day and flags.
        row: Encounter definition.
        from_id: Origin location id.
        to_id: Destination location id.

    Returns:
        True if the encounter may be drawn for this leg.
    """
    triggers = row.get("triggers") or {}
    if not isinstance(triggers, dict):
        return False

    edges = _as_list(triggers.get("edges"))
    if edges and f"{from_id}>{to_id}" not in edges:
        return False

    destinations = _as_list(triggers.get("to"))
    if destinations and to_id not in destinations:
        return False

    origins = _as_list(triggers.get("from"))
    if origins and from_id not in origins:
        return False

    phases = _as_list(triggers.get("phases"))
    if phases and state.evil_phase.value not in phases:
        return False

    hours = triggers.get("hours")
    if hours is not None and state.world_hour not in [int(h) for h in _as_list(hours)]:
        return False

    if "min_day" in triggers and state.world_day < int(triggers.get("min_day") or 0):
        return False
    if "max_day" in triggers and state.world_day > int(triggers.get("max_day") or 0):
        return False

    requires_flag = str(triggers.get("requires_flag") or "")
    if requires_flag and not state.flags.get(requires_flag):
        return False
    forbids_flag = str(triggers.get("forbids_flag") or "")
    if forbids_flag and state.flags.get(forbids_flag):
        return False

    if row.get("once") and state.flags.get(_seen_flag(str(row.get("id")))):
        return False

    return True


def eligible(state: GameState, from_id: str, to_id: str) -> list[dict[str, Any]]:
    """Every encounter definition legal for this travel leg."""
    return [row for row in all_encounters() if matches(state, row, from_id, to_id)]


def trigger_chance(state: GameState, from_id: str, to_id: str) -> float:
    """
    Probability that this travel leg produces an encounter.

    Built from the edge's ``danger_dc`` -- the number the location graph has
    carried unread since it was written -- then modulated by the time of day,
    how far the evil has progressed, and how quietly the player moves. The
    stealth term is the player's full stealth check modifier, so darkness
    partly pays for the night multiplier it also causes, and a wound that
    penalises stealth makes the road worse.

    Args:
        state: Game state.
        from_id: Origin location id.
        to_id: Destination location id.

    Returns:
        Probability in [min_chance, max_chance]. Exactly 0.0 for an edge with
        no danger at all (a door between two village buildings).
    """
    edge = get_edge(from_id, to_id)
    if edge is None:
        return 0.0
    danger_dc = int(edge.get("danger_dc", 0) or 0)
    if danger_dc <= 0:
        return 0.0

    cfg = load_encounters().get("trigger", {}) or {}
    chance = float(cfg.get("base", 0.0)) + float(cfg.get("per_danger_dc", 0.0)) * danger_dc
    chance *= float((cfg.get("time_of_day") or {}).get(state.time_of_day, 1.0))
    # evil_progress is 0.0-1.0 (see engine/game/evil_ticker.py), so this knob
    # is the full bonus at total corruption, not a per-point rate.
    chance += float(cfg.get("evil_progress_bonus", 0.0)) * float(state.evil_progress)

    stealth_mod = sum(d for _, d in checks_module.gather_modifiers(state, "stealth"))
    chance -= float(cfg.get("stealth_reduction_per_point", 0.0)) * stealth_mod

    low = float(cfg.get("min_chance", 0.0))
    high = float(cfg.get("max_chance", 1.0))
    return max(low, min(high, chance))


def _weighted_choice(
    rows: list[dict[str, Any]], gen: random.Random
) -> Optional[dict[str, Any]]:
    """Pick one row by its ``weight`` (default 10)."""
    weights = [max(0, int(r.get("weight", 10) or 0)) for r in rows]
    total = sum(weights)
    if total <= 0:
        return gen.choice(rows) if rows else None
    target = gen.random() * total
    running = 0.0
    for row, weight in zip(rows, weights):
        running += weight
        if target < running:
            return row
    return rows[-1]


def roll_for_encounter(
    state: GameState,
    from_id: str,
    to_id: str,
    *,
    rng: Optional[random.Random] = None,
) -> Optional[dict[str, Any]]:
    """
    Decide whether this travel leg produces an encounter, and which one.

    Does NOT mutate ``state.encounter`` -- call ``begin`` with the returned id
    for that. Keeping the draw separate from the scene setup is what lets a
    balance run count triggers over ten thousand legs without building ten
    thousand scenes.

    Args:
        state: Game state. The ENCOUNTER rng counter advances on every call.
        from_id: Origin location id.
        to_id: Destination location id.
        rng: Optional generator. Defaults to the state's ENCOUNTER stream, so
            replaying a seed replays the same roads.

    Returns:
        The chosen encounter definition, or None if nothing happened.
    """
    gen = rng if rng is not None else world_rng(state, ENCOUNTER)
    chance = trigger_chance(state, from_id, to_id)
    if chance <= 0.0 or gen.random() >= chance:
        return None

    candidates = eligible(state, from_id, to_id)
    if not candidates:
        # The dice said "something happens" and the table had nothing to say.
        # Silence is the correct answer; inventing a generic ambush here is how
        # a content gap becomes a balance problem nobody can find.
        logger.info(
            "[encounter] Triggered with no eligible content "
            "(operation=roll_for_encounter, edge=%s>%s, phase=%s)",
            from_id,
            to_id,
            state.evil_phase.value,
        )
        return None

    chosen = _weighted_choice(candidates, gen)
    logger.info(
        "[encounter] Encounter drawn (operation=roll_for_encounter, id=%s, edge=%s>%s)",
        (chosen or {}).get("id"),
        from_id,
        to_id,
    )
    return chosen


# ---------------------------------------------------------------------------
# scene lifecycle
# ---------------------------------------------------------------------------


def active(state: GameState) -> bool:
    """True while an unresolved encounter is the current scene."""
    scene = state.encounter
    return bool(scene) and not scene.get("resolved")


def end(state: GameState) -> None:
    """Clear the current scene. Idempotent."""
    if state.encounter:
        logger.info(
            "[encounter] Scene ended (operation=end, id=%s)", state.encounter.get("id")
        )
    state.encounter = {}


def begin(state: GameState, encounter_id: str) -> dict[str, Any]:
    """
    Open an encounter as the current scene.

    Args:
        state: Mutable game state. ``state.encounter`` is overwritten.
        encounter_id: Id from data/encounters/*.yaml.

    Returns:
        The scene dict now held on the state, including the engine-authored
        approach list. An unknown id returns ``{}`` and leaves the state idle
        rather than raising -- the caller may be a language model.
    """
    row = get_definition(encounter_id)
    if row is None:
        logger.warning(
            "[encounter] Unknown encounter id (operation=begin, id=%s)", encounter_id
        )
        return {}

    threat = dict(row.get("threat") or {})
    resolve_points = int(threat.get("resolve", _scene_rules().get("default_resolve", 3)))

    scene: dict[str, Any] = {
        "id": str(row.get("id")),
        "band": str(row.get("band") or ""),
        "tier": int(row.get("tier", 1) or 1),
        "intro": str(row.get("intro") or ""),
        # Art is addressed by manifest key so the UI gets a picture for free;
        # see data/art/manifest.yaml `enemies:` and
        # engine/media/providers/shipped.py::lookup.
        "art": str(row.get("art") or ""),
        "art_kind": str(row.get("art_kind") or "enemy"),
        "threat": {
            "name": str(threat.get("name") or "Trouble"),
            "resolve": resolve_points,
            "resolve_max": resolve_points,
        },
        "round": 0,
        "max_rounds": int(row.get("max_rounds", _scene_rules().get("max_rounds", 3))),
        "started_day": state.world_day,
        "started_hour": state.world_hour,
        "log": [],
        "resolved": False,
        "outcome": "",
    }
    state.encounter = scene

    if row.get("once"):
        effects_module.apply_effect(
            state, {"type": "flag", "flag": _seen_flag(scene["id"]), "value": True}
        )

    scene["approaches"] = available_approaches(state)
    logger.info(
        "[encounter] Scene begun (operation=begin, id=%s, threat=%s, resolve=%s)",
        scene["id"],
        scene["threat"]["name"],
        resolve_points,
    )
    return dict(scene)


def _approach_specs(row: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """
    Merge an encounter's approaches over the table-wide defaults.

    The defaults exist so ``available_approaches`` can never come back empty:
    a scene the player has no legal way to address is a soft-lock, and walking
    away has to be on the table in every single one.
    """
    merged: dict[str, dict[str, Any]] = {}
    for key, spec in (load_encounters().get("default_approaches") or {}).items():
        if isinstance(spec, dict):
            merged[str(key)] = dict(spec)
    for key, spec in (row.get("approaches") or {}).items():
        if isinstance(spec, dict):
            merged[str(key)] = dict(spec)
    return merged


def _approach_available(state: GameState, spec: dict[str, Any]) -> bool:
    """Whether the player can actually take this approach right now."""
    times = _as_list(spec.get("requires_time"))
    if times and state.time_of_day not in times:
        return False

    cost = int(spec.get("cost_gold", 0) or 0)
    if cost and state.stats.gold < cost:
        return False

    item_id = str(spec.get("requires_item") or "")
    if item_id and not any(i.id == item_id and i.qty > 0 for i in state.inventory):
        return False

    flag = str(spec.get("requires_flag") or "")
    if flag and not state.flags.get(flag):
        return False

    phases = _as_list(spec.get("requires_phase"))
    if phases and state.evil_phase.value not in phases:
        return False

    return True


def available_approaches(state: GameState) -> list[dict[str, Any]]:
    """
    Legal approaches for the current scene, engine-authored.

    The list is the contract with the narrator: anything in it can be passed
    straight to ``resolve_approach`` and will resolve. Anything the player
    cannot pay for, cannot reach at this hour, or lacks the item for is simply
    absent, so the model is never in a position to offer a choice the engine
    will refuse.

    Args:
        state: Game state with an active encounter.

    Returns:
        List of approach dicts (id, text, skill, difficulty, cost_gold, auto).
        Empty only when no encounter is active.
    """
    if not active(state):
        return []
    row = get_definition(str(state.encounter.get("id", "")))
    if row is None:
        return []

    out: list[dict[str, Any]] = []
    for key, spec in _approach_specs(row).items():
        if not _approach_available(state, spec):
            continue
        out.append(
            {
                "id": key,
                "text": str(spec.get("text") or key.replace("_", " ").capitalize()),
                "skill": str(spec.get("skill") or ""),
                "difficulty": str(spec.get("difficulty") or ""),
                "cost_gold": int(spec.get("cost_gold", 0) or 0),
                "auto": bool(spec.get("auto", False)),
            }
        )
    return out


def _outcome_block(
    spec: dict[str, Any], row: dict[str, Any], degree: str
) -> dict[str, Any]:
    """
    Find the outcome text and effects for a degree.

    Approach-level outcomes win over encounter-level ones, and a missing
    degree walks the configured fallback chain rather than yielding an empty
    beat -- content should be able to write only `success` and `failure` for a
    minor scene without partial silently doing nothing.
    """
    chains = load_encounters().get("degree_fallback", {}) or {}
    order = [degree, *[k for k in _as_list(chains.get(degree)) if k != degree]]
    for source in (spec.get("outcomes") or {}, row.get("outcomes") or {}):
        if not isinstance(source, dict):
            continue
        for key in order:
            block = source.get(key)
            if isinstance(block, dict):
                return block
    return {}


def _refused(reason: str, approach: str, state: GameState) -> dict[str, Any]:
    """Non-raising refusal receipt. The caller may be a language model."""
    logger.warning(
        "[encounter] Approach refused (operation=resolve_approach, approach=%s, reason=%s)",
        approach,
        reason,
    )
    return {
        "ok": False,
        "approach": approach,
        "reason": reason,
        "text": reason,
        "encounter": snapshot(state),
        "approaches": available_approaches(state),
    }


def resolve_approach(
    state: GameState,
    approach: str,
    *,
    ledger: Optional[Any] = None,
) -> dict[str, Any]:
    """
    Resolve one round of the current encounter with the named approach.

    One round is one contested check (or one automatic action, for paying a
    toll or handing over a loaf). Its degree strips ``resolve`` from the threat
    per data/encounters/rules.yaml; the scene ends when the threat is out of
    resolve, when the round cap is reached, or when the degree is one the rules
    declare terminal. That is the whole combat system: one to three checks.

    Args:
        state: Mutable game state.
        approach: Approach id, as returned by ``available_approaches``.
        ledger: Optional StoryLedger, forwarded to effects and checks.

    Returns:
        Receipt dict: the check summary, the outcome text, every applied
        effect, the scene state after the round, and -- if the player was put
        below the death threshold -- the death record. Never raises.
    """
    if not active(state):
        return _refused("no encounter is active", approach, state)

    scene = state.encounter
    row = get_definition(str(scene.get("id", "")))
    if row is None:
        end(state)
        return _refused("encounter content is missing", approach, state)

    legal = {a["id"] for a in available_approaches(state)}
    if approach not in legal:
        return _refused(
            f"'{approach}' is not available; choose one of: {', '.join(sorted(legal))}",
            approach,
            state,
        )

    spec = _approach_specs(row)[approach]
    rules = _scene_rules()

    scene["round"] = int(scene.get("round", 0)) + 1
    applied: list[dict[str, Any]] = []

    # A declared cost is paid for taking the approach at all, win or lose. The
    # toll-takers keep the coin whether or not they also keep their manners.
    cost = int(spec.get("cost_gold", 0) or 0)
    if cost:
        applied.append(effects_module.apply_effect(state, {"type": "gold", "delta": -cost}))

    check_payload: Optional[dict[str, Any]] = None
    if spec.get("auto"):
        degree = str(spec.get("degree") or "success")
        summary = ""
    else:
        result = checks_module.resolve(
            state,
            str(spec.get("skill") or "nerve"),
            str(spec.get("difficulty") or "standard"),
            advantage=int(spec.get("advantage", 0) or 0),
            ledger=ledger,
        )
        check_payload = result.to_dict()
        degree = result.degree
        summary = result.summary

    block = _outcome_block(spec, row, degree)
    text = str(block.get("text") or "")
    applied.extend(effects_module.apply_effects(state, block.get("effects") or [], ledger=ledger))

    damage = int(
        block.get(
            "resolve_damage",
            (rules.get("degree_resolve") or {}).get(degree, 0),
        )
    )
    threat = scene.setdefault("threat", {})
    threat["resolve"] = max(0, int(threat.get("resolve", 0)) - damage)

    scene.setdefault("log", []).append(
        {
            "round": scene["round"],
            "approach": approach,
            "degree": degree,
            "text": text,
            "summary": summary,
        }
    )

    # End conditions, in priority order: the content's explicit say-so, then a
    # degree the rules call terminal, then the threat breaking, then the cap.
    if "ends" in block:
        ends = bool(block.get("ends"))
    elif "ends" in spec:
        ends = bool(spec.get("ends"))
    elif degree in _as_list(rules.get("ends_on")):
        ends = True
    elif threat["resolve"] <= 0:
        ends = True
    else:
        ends = scene["round"] >= int(scene.get("max_rounds", 3))

    if ends:
        scene["resolved"] = True
        scene["outcome"] = str(block.get("outcome") or _outcome_label(degree, threat, spec))

    death = check_death(state, ledger=ledger)

    receipt = {
        "ok": True,
        "encounter_id": scene.get("id"),
        "approach": approach,
        "round": scene["round"],
        "degree": degree,
        "check": check_payload,
        "summary": summary,
        "text": text,
        "effects": applied,
        "threat_resolve": threat["resolve"],
        "resolved": bool(scene.get("resolved")),
        "outcome": scene.get("outcome", ""),
        "encounter": snapshot(state),
        "death": death,
    }

    logger.info(
        "[encounter] Round resolved (operation=resolve_approach, id=%s, approach=%s, "
        "degree=%s, resolved=%s)",
        scene.get("id"),
        approach,
        degree,
        bool(scene.get("resolved")),
    )

    if scene.get("resolved"):
        # Clear the scene so the UI is not left showing a finished encounter.
        # The receipt above already carries the closing snapshot.
        end(state)
    else:
        scene["approaches"] = available_approaches(state)
        receipt["approaches"] = scene["approaches"]

    return receipt


def _outcome_label(degree: str, threat: dict[str, Any], spec: dict[str, Any]) -> str:
    """Coarse label for how the scene closed, for logs and the narrator."""
    if spec.get("auto"):
        return "settled"
    if degree == "failure":
        return "overcome"
    if int(threat.get("resolve", 0)) <= 0:
        return "cleared"
    return "broken_off"


def snapshot(state: GameState) -> dict[str, Any]:
    """Read-only view of the current scene, or ``{}`` when idle."""
    if not state.encounter:
        return {}
    scene = dict(state.encounter)
    scene["threat"] = dict(scene.get("threat") or {})
    scene["log"] = list(scene.get("log") or [])
    scene["approaches"] = available_approaches(state)
    return scene


# ---------------------------------------------------------------------------
# death
# ---------------------------------------------------------------------------


def _to_target(current: int, ceiling: int, spec: dict[str, Any], key: str) -> int:
    """
    Delta needed to reach a target expressed as a fraction or an absolute.

    Effects only move values by deltas, so a rule that wants "wake at half
    stamina" has to be converted here rather than by mutating stats directly.
    """
    if f"{key}_fraction" in spec:
        target = int(round(ceiling * float(spec.get(f"{key}_fraction") or 0.0)))
    elif key in spec:
        target = int(spec.get(key) or 0)
    else:
        return 0
    return target - current


_death_guard = threading.local()


def _death_in_progress() -> bool:
    return getattr(_death_guard, "active", False)


def check_death(
    state: GameState, *, ledger: Optional[Any] = None
) -> Optional[dict[str, Any]]:
    """
    Apply the death rules if the player has dropped to the threshold.

    Death is a setback, not a game over: you wake in Edgewood Square hours
    later, lighter of purse, stiff with a wound that will take days to close,
    and the evil has kept its own hours the whole time. ``state.ended`` is set
    only for the terminal case defined in data/rules/death.yaml -- dying a
    second time while the world is already ``consuming``, when there is no
    longer anyone left to carry you back.

    Args:
        state: Mutable game state.
        ledger: Optional StoryLedger for the death fact.

    Returns:
        Death record dict, or None if the player is still standing.
    """
    # See _death_guard above: one death must not be counted twice.
    if _death_in_progress():
        return None
    _death_guard.active = True
    try:
        return _check_death_inner(state, ledger=ledger)
    finally:
        _death_guard.active = False


def _check_death_inner(
    state: GameState, *, ledger: Optional[Any] = None
) -> Optional[dict[str, Any]]:
    """Actual death handling. Always call check_death, never this."""

    rules = load_death_rules()
    if not rules:
        return None

    threshold = int(rules.get("threshold", 0))
    if state.stats.hp > threshold:
        return None

    terminal_cfg = rules.get("terminal") or {}
    phases = _as_list(terminal_cfg.get("phases"))
    mark = str(terminal_cfg.get("flag") or "")
    terminal = False
    if phases and state.evil_phase.value in phases and mark:
        if state.flags.get(mark):
            terminal = True
        else:
            effects_module.apply_effect(state, {"type": "flag", "flag": mark, "value": True})

    if terminal:
        state.ended = True
        text = str(terminal_cfg.get("text") or "You do not get up.")
        logger.info(
            "[encounter] Terminal death (operation=check_death, day=%s, phase=%s)",
            state.world_day,
            state.evil_phase.value,
        )
        if ledger is not None:
            effects_module.apply_effect(
                state, {"type": "ledger_fact", "text": text, "kind": "death"}, ledger=ledger
            )
        return {"died": True, "terminal": True, "ended": True, "text": text}

    respawn = rules.get("respawn") or {}
    hours = float(respawn.get("hours", 0) or 0)
    if hours > 0:
        # Time passes while you are down, and the evil ticker keeps its
        # appointment. Advanced before restoration so the hunger tick cannot
        # immediately claw back the stamina the rules just gave you.
        from engine.game.clock import advance_time

        advance_time(state, hours)

    stats = state.stats
    queued: list[dict[str, Any]] = []

    hp_delta = _to_target(stats.hp, stats.max_hp, respawn, "hp")
    if hp_delta:
        queued.append({"type": "hp", "delta": hp_delta})
    stamina_delta = _to_target(stats.stamina, stats.max_stamina, respawn, "stamina")
    if stamina_delta:
        queued.append({"type": "stamina", "delta": stamina_delta})

    gold_lost = 0
    if "gold_loss_fraction" in respawn:
        gold_lost = int(stats.gold * float(respawn.get("gold_loss_fraction") or 0.0))
    gold_lost = max(gold_lost, int(respawn.get("gold_loss_min", 0) or 0))
    gold_lost = min(gold_lost, stats.gold)
    if gold_lost:
        queued.append({"type": "gold", "delta": -gold_lost})

    wound = respawn.get("wound")
    if isinstance(wound, dict):
        queued.append({"type": "wound", **wound})

    queued.extend(e for e in (respawn.get("effects") or []) if isinstance(e, dict))

    applied = effects_module.apply_effects(state, queued, ledger=ledger)

    location = str(respawn.get("location_id") or state.location_id)
    state.location_id = location
    # An unresolved scene cannot survive the player being carried out of it.
    end(state)

    text = str(respawn.get("text") or "You wake somewhere else, and later.")
    if ledger is not None:
        effects_module.apply_effect(
            state, {"type": "ledger_fact", "text": text, "kind": "death"}, ledger=ledger
        )

    logger.info(
        "[encounter] Player down, respawned (operation=check_death, location=%s, "
        "hp=%s, gold_lost=%s, day=%s)",
        location,
        stats.hp,
        gold_lost,
        state.world_day,
    )

    return {
        "died": True,
        "terminal": False,
        "ended": False,
        "location_id": location,
        "hours_lost": hours,
        "gold_lost": gold_lost,
        "hp": stats.hp,
        "stamina": stats.stamina,
        "effects": applied,
        "text": text,
    }
