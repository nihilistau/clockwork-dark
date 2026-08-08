"""
Challenge Specs — validate and bound what the model proposes
============================================================

The model composes; the engine bounds. This module is the bounding.

WHY BOUNDS ARE THE WHOLE POINT. A challenge is the one place a language model
gets to author structure the engine will then execute -- steps, branches, an
answer, a reward. That is genuinely useful (combat and a single skill check are
otherwise the entire vocabulary of the game) and it is exactly the shape of
feature that hands out 900 gold the first time a model gets excited. So nothing
here trusts a number:

  * **Difficulty is a band, never a raw DC.** The model picks from the seven
    canon bands and ``engine/game/checks.py`` maps the band to a number. There
    is no integer for it to inflate, and the mapping stays in one place where a
    balance pass can find it.
  * **Rewards are clamped per effect and capped in count.** A reward is a list
    of ordinary engine effects, so it goes through the one validated writer;
    the ceilings here sit in front of that.
  * **Size is capped.** Steps, nodes, options, outcomes and text length all
    have limits, because an oversized spec lands in ``GameState`` and is then
    paid for in every save write and every turn payload forever.

Clamping is preferred to rejection. A challenge with an over-generous reward is
still a good scene; refusing it hands narration of the outcome back to the
model unrolled, which is the failure the two-phase turn loop exists to prevent.
Rejection is reserved for specs that are structurally unusable.

Version: v0.1.0 [2026-08-08]
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)

KINDS: tuple[str, ...] = ("skill_gauntlet", "decision_tree", "puzzle", "dice_table")

#: The seven canon skills. A challenge naming anything else is retargeted
#: rather than refused -- see CLAUDE.md "Canon IDs".
SKILLS: tuple[str, ...] = (
    "persuasion",
    "stealth",
    "sympathy",
    "lore",
    "craft",
    "survival",
    "nerve",
)
DEFAULT_SKILL = "nerve"

#: The canon difficulty bands, in order. Bands are the ONLY way a spec can
#: express difficulty, which is what keeps DCs inside the engine's table.
DIFFICULTIES: tuple[str, ...] = (
    "trivial",
    "easy",
    "standard",
    "hard",
    "severe",
    "legendary",
)
DEFAULT_DIFFICULTY = "standard"

# -- structural bounds ------------------------------------------------------
MAX_STEPS = 6
MAX_NODES = 24
MAX_OPTIONS = 6
MAX_OUTCOMES = 12
MAX_ATTEMPTS = 5
MAX_TEXT = 400
MAX_ID = 64

#: Sides a dice_table may roll. Bounded so a "d1000000" table cannot be used to
#: express a probability the designer never reviewed.
ALLOWED_DICE: tuple[int, ...] = (4, 6, 8, 10, 12, 20)
DEFAULT_DIE = 6

# -- reward ceilings --------------------------------------------------------
#: Maximum number of effects one outcome may apply.
MAX_EFFECTS = 4

#: Per-effect magnitude ceilings, as absolute values. These are deliberately
#: mean: a challenge is a scene, not a treasure room, and the economy is tuned
#: against day-scale earnings (see data/economy.yaml).
EFFECT_CEILINGS: dict[str, int] = {
    "gold": 25,
    "hp": 10,
    "stamina": 40,
    "focus": 5,
    "craft": 3,
    "awareness": 10,
    "hunger": 25,
    "reputation": 10,
}

#: Item quantity ceiling for an `item` effect.
MAX_ITEM_QTY = 3

#: Effect types a model-composed challenge may use at all. Everything else is
#: dropped. Notably absent: `wound` and `check_penalty` with unbounded expiry,
#: and `ledger_fact`, which would let a challenge write itself into memory as
#: established truth.
ALLOWED_EFFECT_TYPES: frozenset[str] = frozenset(
    {"gold", "hp", "stamina", "focus", "craft", "awareness", "hunger",
     "reputation", "item", "remove_item", "flag"}
)


@dataclass
class SpecResult:
    """A validated spec, or the reason there isn't one."""

    ok: bool
    spec: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    #: Human-readable record of every clamp applied. Surfaced in the receipt so
    #: a designer can see the engine disagreeing with the model.
    adjustments: list[str] = field(default_factory=list)


def _text(value: Any, *, limit: int = MAX_TEXT) -> str:
    """Coerce to a bounded single string."""
    return str(value or "").strip()[:limit]


def _ident(value: Any, fallback: str = "") -> str:
    """Coerce to a bounded identifier."""
    return str(value or fallback).strip()[:MAX_ID]


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _clamp_effect(
    effect: Any,
    adjustments: list[str],
) -> Optional[dict[str, Any]]:
    """
    Bound one effect, or drop it.

    Returns None when the effect is unusable or of a type a model-composed
    challenge is not allowed to apply.
    """
    if not isinstance(effect, dict):
        return None
    kind = str(effect.get("type", "")).strip().lower()
    if kind not in ALLOWED_EFFECT_TYPES:
        adjustments.append(f"dropped disallowed effect type {kind!r}")
        return None

    bounded = dict(effect)
    bounded["type"] = kind

    ceiling = EFFECT_CEILINGS.get(kind)
    if ceiling is not None:
        delta = _int(effect.get("delta"))
        if abs(delta) > ceiling:
            capped = ceiling if delta > 0 else -ceiling
            adjustments.append(f"{kind} delta {delta:+d} clamped to {capped:+d}")
            delta = capped
        bounded["delta"] = delta

    if kind in ("item", "remove_item"):
        item_id = _ident(effect.get("item_id") or effect.get("id"))
        if not item_id:
            adjustments.append("dropped item effect with no id")
            return None
        bounded["item_id"] = item_id
        quantity = max(1, _int(effect.get("qty"), 1))
        if quantity > MAX_ITEM_QTY:
            adjustments.append(f"item qty {quantity} clamped to {MAX_ITEM_QTY}")
            quantity = MAX_ITEM_QTY
        bounded["qty"] = quantity
        bounded["name"] = _text(effect.get("name") or item_id.replace("_", " "), limit=80)

    if kind == "flag":
        name = _ident(effect.get("flag") or effect.get("name"))
        if not name:
            adjustments.append("dropped flag effect with no name")
            return None
        bounded["flag"] = name

    if kind == "reputation":
        faction = _ident(effect.get("faction") or effect.get("id"))
        if not faction:
            adjustments.append("dropped reputation effect with no faction")
            return None
        bounded["faction"] = faction

    return bounded


def clamp_outcome(raw: Any, adjustments: list[str]) -> dict[str, Any]:
    """
    Bound one outcome block (``reward`` or ``fail``).

    Shape: ``{"text": str, "effects": [effect, ...]}``.
    """
    if not isinstance(raw, dict):
        return {"text": "", "effects": []}

    effects_in = raw.get("effects")
    effects_in = effects_in if isinstance(effects_in, list) else []
    if len(effects_in) > MAX_EFFECTS:
        adjustments.append(
            f"outcome had {len(effects_in)} effects, kept first {MAX_EFFECTS}"
        )
        effects_in = effects_in[:MAX_EFFECTS]

    bounded: list[dict[str, Any]] = []
    for entry in effects_in:
        clamped = _clamp_effect(entry, adjustments)
        if clamped is not None:
            bounded.append(clamped)

    return {"text": _text(raw.get("text")), "effects": bounded}


def _clamp_options(raw: Any, adjustments: list[str], *, node: str) -> list[dict[str, str]]:
    """Bound a decision-tree node's options."""
    options_in = raw if isinstance(raw, list) else []
    if len(options_in) > MAX_OPTIONS:
        adjustments.append(f"node {node!r} had {len(options_in)} options, kept {MAX_OPTIONS}")
        options_in = options_in[:MAX_OPTIONS]
    options: list[dict[str, str]] = []
    for entry in options_in:
        if not isinstance(entry, dict):
            continue
        option_id = _ident(entry.get("id"))
        if not option_id:
            continue
        options.append(
            {
                "id": option_id,
                "text": _text(entry.get("text"), limit=160),
                "goto": _ident(entry.get("goto")),
            }
        )
    return options


def _validate_gauntlet(spec: dict[str, Any], out: dict[str, Any], adj: list[str]) -> Optional[str]:
    raw_steps = spec.get("steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        return "skill_gauntlet needs a non-empty 'steps' list"
    if len(raw_steps) > MAX_STEPS:
        adj.append(f"steps trimmed from {len(raw_steps)} to {MAX_STEPS}")
        raw_steps = raw_steps[:MAX_STEPS]

    steps: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_steps):
        raw = raw if isinstance(raw, dict) else {}
        skill = str(raw.get("skill", "")).strip().lower()
        if skill not in SKILLS:
            adj.append(f"step {index}: skill {skill!r} is not canon, using {DEFAULT_SKILL}")
            skill = DEFAULT_SKILL
        difficulty = str(raw.get("difficulty", "")).strip().lower()
        if difficulty not in DIFFICULTIES:
            # No raw DC is accepted at all, so there is nothing to clamp -- an
            # unrecognised band simply falls back to the middle of the table.
            if difficulty:
                adj.append(
                    f"step {index}: difficulty {difficulty!r} unknown, "
                    f"using {DEFAULT_DIFFICULTY}"
                )
            difficulty = DEFAULT_DIFFICULTY
        steps.append(
            {
                "skill": skill,
                "difficulty": difficulty,
                "text": _text(raw.get("text")),
                "on_fail_text": _text(raw.get("on_fail_text"), limit=200),
            }
        )

    out["steps"] = steps
    out["step"] = 0
    out["reward"] = clamp_outcome(spec.get("reward"), adj)
    out["fail"] = clamp_outcome(spec.get("fail"), adj)
    return None


def _validate_tree(spec: dict[str, Any], out: dict[str, Any], adj: list[str]) -> Optional[str]:
    raw_nodes = spec.get("nodes")
    start = _ident(spec.get("start"), "start")
    if not isinstance(raw_nodes, dict) or start not in raw_nodes:
        return "decision_tree needs a 'nodes' mapping and a 'start' that exists in it"
    if len(raw_nodes) > MAX_NODES:
        return f"decision_tree has {len(raw_nodes)} nodes, over the limit of {MAX_NODES}"

    nodes: dict[str, Any] = {}
    for node_id, raw in raw_nodes.items():
        raw = raw if isinstance(raw, dict) else {}
        key = _ident(node_id)
        if not key:
            continue
        terminal = bool(raw.get("terminal"))
        node: dict[str, Any] = {
            "text": _text(raw.get("text")),
            "terminal": terminal,
        }
        if terminal:
            outcome = str(raw.get("outcome", "success")).strip().lower()
            node["outcome"] = outcome if outcome in ("success", "failure") else "success"
            node["reward"] = clamp_outcome(raw.get("reward"), adj)
            node["fail"] = clamp_outcome(raw.get("fail"), adj)
        else:
            node["options"] = _clamp_options(raw.get("options"), adj, node=key)
        nodes[key] = node

    # A non-terminal node whose options all point nowhere is a dead end the
    # player can walk into and never leave -- the same failure the location
    # graph validates for. Repair by marking it terminal rather than refusing.
    for key, node in nodes.items():
        if node.get("terminal"):
            continue
        reachable = [o for o in node.get("options", []) if o.get("goto") in nodes]
        if not reachable:
            adj.append(f"node {key!r} had no reachable options, made terminal")
            node["terminal"] = True
            node["outcome"] = "failure"
            node["reward"] = {"text": "", "effects": []}
            node["fail"] = {"text": "", "effects": []}
            node.pop("options", None)
        else:
            node["options"] = reachable

    out["nodes"] = nodes
    out["current"] = start
    return None


def _validate_puzzle(spec: dict[str, Any], out: dict[str, Any], adj: list[str]) -> Optional[str]:
    if "answer" not in spec or not str(spec.get("answer", "")).strip():
        return "puzzle needs a non-empty 'answer'"
    attempts = _int(spec.get("attempts"), 3)
    if attempts < 1 or attempts > MAX_ATTEMPTS:
        clamped = max(1, min(MAX_ATTEMPTS, attempts))
        adj.append(f"attempts {attempts} clamped to {clamped}")
        attempts = clamped
    out["answer"] = normalise_answer(spec["answer"])
    out["attempts_left"] = attempts
    out["prompt"] = _text(spec.get("prompt"))
    out["reward"] = clamp_outcome(spec.get("reward"), adj)
    out["fail"] = clamp_outcome(spec.get("fail"), adj)
    return None


def _validate_dice_table(spec: dict[str, Any], out: dict[str, Any], adj: list[str]) -> Optional[str]:
    raw_outcomes = spec.get("outcomes")
    if not isinstance(raw_outcomes, list) or not raw_outcomes:
        return "dice_table needs a non-empty 'outcomes' list"
    if len(raw_outcomes) > MAX_OUTCOMES:
        adj.append(f"outcomes trimmed from {len(raw_outcomes)} to {MAX_OUTCOMES}")
        raw_outcomes = raw_outcomes[:MAX_OUTCOMES]

    die = _int(spec.get("die"), DEFAULT_DIE)
    if die not in ALLOWED_DICE:
        adj.append(f"die d{die} is not a standard die, using d{DEFAULT_DIE}")
        die = DEFAULT_DIE

    outcomes: list[dict[str, Any]] = []
    for raw in raw_outcomes:
        raw = raw if isinstance(raw, dict) else {}
        low = max(1, _int(raw.get("min"), 1))
        high = min(die, _int(raw.get("max"), die))
        if high < low:
            low, high = high, low
        outcomes.append(
            {
                "min": low,
                "max": high,
                "text": _text(raw.get("text")),
                "effects": clamp_outcome(raw, adj)["effects"],
            }
        )

    out["die"] = die
    out["outcomes"] = outcomes
    out["prompt"] = _text(spec.get("prompt"))
    return None


def normalise_answer(value: Any) -> str:
    """Case- and punctuation-insensitive form used to compare puzzle answers."""
    return "".join(ch.lower() for ch in str(value) if ch.isalnum())


def validate(spec: Any) -> SpecResult:
    """
    Validate and bound a proposed challenge spec.

    Args:
        spec: Raw spec, typically straight from a model tool call or a YAML
            set-piece file.

    Returns:
        SpecResult. On success ``spec`` is the normalised, bounded form ready to
        store on ``GameState.challenge``; ``adjustments`` lists every clamp.
    """
    if not isinstance(spec, dict):
        return SpecResult(ok=False, error="challenge spec must be a mapping")

    kind = str(spec.get("kind", "")).strip().lower()
    if kind not in KINDS:
        return SpecResult(
            ok=False,
            error=f"unknown challenge kind {kind!r}; expected one of {', '.join(KINDS)}",
        )

    adjustments: list[str] = []
    challenge_id = _ident(spec.get("id"), kind)
    out: dict[str, Any] = {
        "id": challenge_id,
        "kind": kind,
        "title": _text(spec.get("title") or challenge_id, limit=120),
    }

    validators = {
        "skill_gauntlet": _validate_gauntlet,
        "decision_tree": _validate_tree,
        "puzzle": _validate_puzzle,
        "dice_table": _validate_dice_table,
    }
    error = validators[kind](spec, out, adjustments)
    if error:
        logger.warning(
            "[challenges] Rejected spec (operation=validate, kind=%s, reason=%s)",
            kind,
            error,
        )
        return SpecResult(ok=False, error=error, adjustments=adjustments)

    if adjustments:
        logger.info(
            "[challenges] Spec bounded (operation=validate, id=%s, kind=%s, clamps=%d)",
            challenge_id,
            kind,
            len(adjustments),
        )
    return SpecResult(ok=True, spec=out, adjustments=adjustments)


__all__ = [
    "ALLOWED_DICE",
    "ALLOWED_EFFECT_TYPES",
    "DIFFICULTIES",
    "EFFECT_CEILINGS",
    "KINDS",
    "MAX_EFFECTS",
    "MAX_ITEM_QTY",
    "MAX_STEPS",
    "SKILLS",
    "SpecResult",
    "clamp_outcome",
    "normalise_answer",
    "validate",
]
