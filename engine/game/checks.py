"""
Skill Checks
============

The engine picks the number. The model picks the fiction.

The previous path let the Storyteller hand in a raw DC, and the dispatcher
patched it with three hardcoded lines: ``base_dc = 12``, ``+2`` if the skill was
stealth, ``+1`` if it was persuasion. That is a difficulty system with two
entries, no situational awareness, and a knob the narrator could turn on itself.
A model that wanted the player to succeed simply asked for a lower DC.

Now the model names a *band* -- trivial through legendary -- and everything
after that is engine business: the DC, the stat modifier, exhaustion, injury,
starvation, darkness, the evil phase pressing on nerve, open wounds and any
timed conditions. All of it comes from data/rules/skills.yaml, and all of it is
itemised in ``CheckResult.modifiers`` so the receipt can show the player exactly
why the roll went the way it did.

Version: v0.1.0 [2026-08-07]
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

import yaml

from engine.config import get_config
from engine.game import effects as effects_module
from engine.game.dice import DiceResult, roll_dice
from engine.game.rng import BOON, COMPLICATION, DICE, world_rng
from engine.game.state import GameState

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parents[2]

def _rules_path(filename: str) -> Path:
    rel = get_config().get("paths.rules", "data/rules")
    return _ROOT / str(rel) / filename


@lru_cache(maxsize=16)
def _read_yaml(path_str: str, _mtime: float) -> dict[str, Any]:
    """
    Parse a rules file, memoized on (path, mtime).

    A plain module-level cache would be wrong here: engine/config.py::reset_config
    clears a fixed list of module caches and this module is not on it, so a
    config change repointing paths.rules would keep serving the old tables.
    Keying on mtime as well as path means the cache invalidates on both a file
    edit and a path change, without this module needing to be registered
    anywhere.
    """
    try:
        with Path(path_str).open(encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}
    except (OSError, yaml.YAMLError) as exc:
        logger.warning(
            "[checks] Unreadable rules file (operation=_read_yaml, path=%s): %s",
            path_str,
            exc,
        )
        return {}


def _load_yaml(path: Path, label: str) -> dict[str, Any]:
    try:
        mtime = path.stat().st_mtime
    except OSError:
        logger.warning(
            "[checks] Rules file missing (operation=_load_yaml, label=%s, path=%s)",
            label,
            path,
        )
        return {}
    return _read_yaml(str(path), mtime)


def load_skill_rules() -> dict[str, Any]:
    """Load data/rules/skills.yaml."""
    return _load_yaml(_rules_path("skills.yaml"), "skills")


def load_archetypes() -> dict[str, Any]:
    """Load data/rules/archetypes.yaml."""
    return _load_yaml(_rules_path("archetypes.yaml"), "archetypes")


def _load_table(filename: str, key: str) -> list[dict[str, Any]]:
    path = _ROOT / "data" / "tables" / filename
    data = _load_yaml(path, key)
    rows = data.get(key, [])
    return [r for r in rows if isinstance(r, dict)]


def stat_mod(value: int, rules: Optional[dict[str, Any]] = None) -> int:
    """
    Convert a raw stat into a check modifier.

    Args:
        value: Raw stat value (3-18 for attributes).
        rules: Optional pre-loaded rules; loaded if omitted.

    Returns:
        ``(value - base) // divisor``, base and divisor from skills.yaml.
    """
    cfg = (rules or load_skill_rules()).get("stat_mod", {})
    base = int(cfg.get("base", 10))
    divisor = int(cfg.get("divisor", 2)) or 2
    return (int(value) - base) // divisor


# -- situational condition grammar ---------------------------------------


def _compare(value: float, cond: dict[str, Any]) -> bool:
    """Apply whichever of lte/gte/lt/gt the condition declares."""
    if "lte" in cond:
        return value <= float(cond["lte"])
    if "gte" in cond:
        return value >= float(cond["gte"])
    if "lt" in cond:
        return value < float(cond["lt"])
    if "gt" in cond:
        return value > float(cond["gt"])
    return False


def _matches(state: GameState, cond: Any) -> bool:
    """
    Evaluate one situational condition against the state.

    The grammar is intentionally tiny (see data/rules/skills.yaml header). A
    full expression language here would be a second place for balance logic to
    hide; the point of the table is that a designer can read it.
    """
    if not isinstance(cond, dict) or not cond:
        return False

    if "time_of_day" in cond:
        want = cond["time_of_day"]
        want = want if isinstance(want, list) else [want]
        return state.time_of_day in [str(w) for w in want]

    if "evil_phase" in cond:
        want = cond["evil_phase"]
        want = want if isinstance(want, list) else [want]
        return state.evil_phase.value in [str(w) for w in want]

    if "stat_ratio" in cond:
        pair = cond["stat_ratio"]
        if not isinstance(pair, list) or len(pair) != 2:
            return False
        num = float(getattr(state.stats, str(pair[0]), 0) or 0)
        den = float(getattr(state.stats, str(pair[1]), 0) or 0)
        if den == 0:
            return False
        return _compare(num / den, cond)

    if "stat" in cond:
        return _compare(float(getattr(state.stats, str(cond["stat"]), 0) or 0), cond)

    if "field" in cond:
        return _compare(float(getattr(state, str(cond["field"]), 0) or 0), cond)

    return False


def _applies_to(row: dict[str, Any], skill: str, key: str = "skills") -> bool:
    """A row with no skill filter applies to every skill."""
    allowed = row.get(key)
    if not allowed:
        return True
    return skill in [str(s) for s in allowed]


def gather_modifiers(
    state: GameState,
    skill: str,
    *,
    rules: Optional[dict[str, Any]] = None,
) -> list[tuple[str, int]]:
    """
    Build the itemised modifier list for a skill check.

    Every entry is (label, delta) and the deltas sum to the number applied to
    the die. Nothing is folded together: the receipt shows the player the whole
    arithmetic, which is what makes an engine-resolved failure feel fair rather
    than arbitrary.

    Args:
        state: Game state.
        skill: Skill id.
        rules: Optional pre-loaded skills.yaml.

    Returns:
        List of (label, delta) pairs, stat modifier first.
    """
    rules = rules or load_skill_rules()
    skills = rules.get("skills", {})
    spec = skills.get(skill)
    if spec is None:
        stat_name = str(rules.get("unknown_skill_stat", "wits"))
        logger.warning(
            "[checks] Unknown skill resolved against fallback stat "
            "(operation=gather_modifiers, skill=%s, stat=%s)",
            skill,
            stat_name,
        )
    else:
        stat_name = str(spec.get("stat", "wits"))

    mods: list[tuple[str, int]] = []

    raw = int(getattr(state.stats, stat_name, 10) or 0)
    mods.append((stat_name, stat_mod(raw, rules)))

    # Archetype affinity: the thing you were already doing before the story
    # found you. Small by design -- see data/rules/archetypes.yaml.
    arche = load_archetypes().get("archetypes", {}).get(state.archetype, {})
    affinity = int((arche.get("skill_bonus") or {}).get(skill, 0))
    if affinity:
        mods.append((str(arche.get("name") or state.archetype).lower(), affinity))

    for row in rules.get("situational", []):
        if not isinstance(row, dict):
            continue
        if not _applies_to(row, skill):
            continue
        if not _matches(state, row.get("when")):
            continue
        delta = int(row.get("delta", 0))
        if delta:
            mods.append((str(row.get("label") or row.get("id", "situation")), delta))

    # Wounds and timed conditions are state, not table rows, so they are walked
    # separately -- but they land in the same itemised list.
    for wound in state.wounds:
        if wound.check_penalty and _applies_to({"skills": wound.skills}, skill):
            mods.append((wound.text.lower(), int(wound.check_penalty)))

    for eff in state.active_effects:
        if eff.kind != "check_penalty" or not eff.delta:
            continue
        if _applies_to({"skills": eff.skills}, skill):
            mods.append((eff.text.lower() or eff.id, int(eff.delta)))

    return mods


def difficulty_dc(difficulty: str, rules: Optional[dict[str, Any]] = None) -> tuple[str, int]:
    """
    Resolve a difficulty band name to (band, dc).

    An unrecognised band falls back to the default rather than raising: the
    caller is a language model, and refusing the check would hand narration of
    the outcome back to it unrolled.
    """
    rules = rules or load_skill_rules()
    bands = rules.get("difficulty", {})
    default = str(rules.get("default_difficulty", "standard"))
    band = str(difficulty or default).strip().lower()
    if band not in bands:
        logger.warning(
            "[checks] Unknown difficulty band (operation=difficulty_dc, got=%s, using=%s)",
            difficulty,
            default,
        )
        band = default
    return band, int(bands.get(band, 13))


def degree_for(margin: int, rules: Optional[dict[str, Any]] = None) -> str:
    """Map a margin to a degree id using the ordered degrees table."""
    rules = rules or load_skill_rules()
    for row in rules.get("degrees", []):
        if not isinstance(row, dict):
            continue
        if margin >= int(row.get("min_margin", -999)):
            return str(row.get("id", "failure"))
    return "failure"


def _draw(
    state: GameState,
    rows: list[dict[str, Any]],
    skill: str,
    stream: str,
) -> Optional[dict[str, Any]]:
    """Pick one table row whose `applies_to` filter admits this skill."""
    eligible = [r for r in rows if _applies_to(r, skill, key="applies_to")]
    if not eligible:
        return None
    return world_rng(state, stream).choice(eligible)


@dataclass
class CheckResult:
    """
    One resolved skill check, with its whole arithmetic attached.

    ``modifiers`` is the receipt: the deltas sum to ``dice.modifier``, so the UI
    can render the breakdown without recomputing anything and a test can assert
    the engine did not quietly add a number it did not show.
    """

    skill: str
    stat: str
    dc: int
    difficulty: str
    dice: DiceResult
    modifiers: list[tuple[str, int]]
    total: int
    margin: int
    degree: str
    boon: Optional[dict[str, Any]] = None
    complication: Optional[dict[str, Any]] = None
    advantage: int = 0
    all_rolls: list[int] = None  # type: ignore[assignment]
    effects_applied: list[dict[str, Any]] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.all_rolls is None:
            self.all_rolls = list(self.dice.rolls)
        if self.effects_applied is None:
            self.effects_applied = []

    @property
    def success(self) -> bool:
        """True for full or critical success. Partial is not success."""
        return self.degree in ("success", "crit_success")

    @property
    def natural(self) -> int:
        """The kept die face, before modifiers."""
        return self.dice.rolls[0] if self.dice.rolls else 0

    @property
    def summary(self) -> str:
        """
        Human-readable receipt line.

        The narration prompt renders this string verbatim, so its shape is part
        of the contract: skill, band, die, every modifier, total, DC, outcome.
        """
        parts = [f"d20 {self.natural}"]
        if self.advantage and len(self.all_rolls) > 1:
            kept = "high" if self.advantage > 0 else "low"
            parts[0] += f" ({kept} of {', '.join(str(r) for r in self.all_rolls)})"
        parts.extend(f"{delta:+d} {label}" for label, delta in self.modifiers if delta)

        word = self.degree.upper().replace("_", " ")
        line = (
            f"{self.skill} ({self.difficulty}): "
            f"{', '.join(parts)} = {self.total} vs DC {self.dc}. "
            f"{word} by {abs(self.margin)}."
        )
        if self.boon:
            line += f" Boon: {self.boon.get('text', '')}"
        if self.complication:
            line += f" Complication: {self.complication.get('text', '')}"
        return line

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill": self.skill,
            "stat": self.stat,
            "dc": self.dc,
            "difficulty": self.difficulty,
            "dice": self.dice.to_dict(),
            "natural": self.natural,
            "all_rolls": list(self.all_rolls),
            "advantage": self.advantage,
            "modifiers": [{"label": l, "delta": d} for l, d in self.modifiers],
            "modifier_total": sum(d for _, d in self.modifiers),
            "total": self.total,
            "margin": self.margin,
            "degree": self.degree,
            "success": self.success,
            "boon": self.boon,
            "complication": self.complication,
            "effects": list(self.effects_applied),
            "summary": self.summary,
        }


def resolve(
    state: GameState,
    skill: str,
    difficulty: str = "standard",
    *,
    advantage: int = 0,
    extra_mod: int = 0,
    rng: Optional[random.Random] = None,
    ledger: Optional[Any] = None,
) -> CheckResult:
    """
    Resolve a skill check end to end.

    Args:
        state: Mutable game state. Mutated only by boon/complication effects.
        skill: One of the seven taxonomy skills; anything else falls back to the
            configured stat and is logged.
        difficulty: Band name (trivial|easy|standard|hard|severe|legendary).
        advantage: +1 rolls twice and keeps the high die, -1 keeps the low die,
            0 rolls once.
        extra_mod: Situational bonus the caller can justify, itemised in the
            receipt as "circumstance" so it is never invisible.
        rng: Optional RNG. Defaults to the state's deterministic dice stream.
        ledger: Optional StoryLedger for ledger_fact effects on table draws.

    Returns:
        CheckResult carrying the dice, the full modifier breakdown, the degree
        of success, and any boon or complication already applied to the state.
    """
    rules = load_skill_rules()
    spec = rules.get("skills", {}).get(skill, {})
    stat_name = str(spec.get("stat", rules.get("unknown_skill_stat", "wits")))

    band, dc = difficulty_dc(difficulty, rules)

    mods = gather_modifiers(state, skill, rules=rules)
    if extra_mod:
        mods.append(("circumstance", int(extra_mod)))
    modifier = sum(d for _, d in mods)

    gen = rng if rng is not None else world_rng(state, DICE)
    reason = f"check:{skill}:{band}"

    rolls = [roll_dice(sides=20, modifier=modifier, reason=reason, rng=gen)]
    if advantage:
        rolls.append(roll_dice(sides=20, modifier=modifier, reason=reason, rng=gen))
        pick = max if advantage > 0 else min
        dice = pick(rolls, key=lambda r: r.total)
    else:
        dice = rolls[0]

    total = dice.total
    margin = total - dc
    degree = degree_for(margin, rules)

    result = CheckResult(
        skill=skill,
        stat=stat_name,
        dc=dc,
        difficulty=band,
        dice=dice,
        modifiers=mods,
        total=total,
        margin=margin,
        degree=degree,
        advantage=int(advantage),
        all_rolls=[r.rolls[0] for r in rolls],
    )

    # Nat 20 and nat 1 read the KEPT die, so advantage genuinely buys you a
    # second chance at a boon and shields you from a complication.
    if dice.critical:
        row = _draw(state, _load_table("boons.yaml", "boons"), skill, BOON)
        if row:
            result.boon = {"id": row.get("id", ""), "text": row.get("text", "")}
            result.effects_applied = effects_module.apply_effects(
                state, row.get("effects", []), ledger=ledger
            )
    elif dice.fumble:
        row = _draw(state, _load_table("complications.yaml", "complications"), skill, COMPLICATION)
        if row:
            result.complication = {"id": row.get("id", ""), "text": row.get("text", "")}
            result.effects_applied = effects_module.apply_effects(
                state, row.get("effects", []), ledger=ledger
            )

    logger.info(
        "[checks] Check resolved (operation=resolve, skill=%s, difficulty=%s, degree=%s)",
        skill,
        band,
        degree,
    )
    return result
