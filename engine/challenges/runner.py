"""
Challenge Runner — engine-authoritative resolution
==================================================

The model composed the scene (bounded by ``engine/challenges/spec.py``); this
module plays it. Every roll goes through ``engine/game/checks.py`` and every
reward through ``engine/game/effects.py``, so a challenge is resolved by the
same code as any other check and cannot invent a mechanic of its own.

WHY IT ROUTES THROUGH ``checks.resolve`` RATHER THAN ROLLING ITSELF: the
obvious implementation is ``d20 + stat // 5 >= dc``. That silently opts the
whole system out of everything the check layer already does -- wound penalties,
hunger, timed effects, archetype modifiers, advantage, the boon and
complication tables, and the itemised modifier receipt the UI renders. A
challenge resolved by a private formula would be the one place in the game
where being injured did not matter.

State lives in ``GameState.challenge`` and is therefore saved, so a challenge
survives a reload mid-gauntlet.

Version: v0.1.0 [2026-08-08]
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field
from typing import Any, Optional

from engine.challenges import spec as spec_module
from engine.game import checks, effects as effects_module
from engine.game.dice import roll_dice
from engine.game.rng import CHALLENGE as RNG_CHALLENGE
from engine.game.rng import world_rng
from engine.game.state import GameState

logger = logging.getLogger(__name__)

STATUS_ACTIVE = "active"
STATUS_SUCCESS = "success"
STATUS_FAILURE = "failure"
STATUS_ERROR = "error"


@dataclass
class ChallengeResult:
    """One step of a challenge, as the engine resolved it."""

    challenge_id: str = ""
    kind: str = ""
    status: str = STATUS_ACTIVE
    title: str = ""
    text: str = ""
    message: str = ""
    options: list[dict[str, str]] = field(default_factory=list)
    answer_required: bool = False
    step: int = 0
    total_steps: int = 0
    check: Optional[dict[str, Any]] = None
    dice: Optional[dict[str, Any]] = None
    effects_applied: list[dict[str, Any]] = field(default_factory=list)
    adjustments: list[str] = field(default_factory=list)
    ended: bool = False
    success: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "challenge_id": self.challenge_id,
            "kind": self.kind,
            "status": self.status,
            "title": self.title,
            "text": self.text,
            "message": self.message,
            "options": list(self.options),
            "answer_required": self.answer_required,
            "step": self.step,
            "total_steps": self.total_steps,
            "check": self.check,
            "dice": self.dice,
            "effects_applied": list(self.effects_applied),
            "adjustments": list(self.adjustments),
            "ended": self.ended,
            "success": self.success,
        }


def _error(message: str, kind: str = "") -> ChallengeResult:
    return ChallengeResult(kind=kind, status=STATUS_ERROR, message=message, ended=True)


def _rng(state: GameState, rng: Optional[random.Random]) -> random.Random:
    """Injected RNG, else the state's deterministic challenge stream."""
    return rng if rng is not None else world_rng(state, RNG_CHALLENGE)


def _apply_outcome(
    state: GameState,
    outcome: dict[str, Any],
    *,
    ledger: Optional[Any] = None,
) -> list[dict[str, Any]]:
    """
    Apply a bounded outcome's effects through the one validated writer.

    The spec layer has already clamped magnitudes and dropped disallowed types,
    so everything reaching here is inside the ceilings.
    """
    if not isinstance(outcome, dict):
        return []
    return effects_module.apply_effects(
        state, outcome.get("effects") or [], ledger=ledger
    )


def _clear(state: GameState) -> None:
    """End the active challenge. Empty dict, never None -- the field is typed."""
    state.challenge = {}


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


def start(
    state: GameState,
    proposed: dict[str, Any],
    *,
    replace: bool = False,
) -> ChallengeResult:
    """
    Validate a proposed challenge and present its first step.

    Args:
        state: Mutable game state.
        proposed: Raw spec from a model tool call or a set-piece file.
        replace: Abandon an already-running challenge. Default False, because
            a model that composes a second challenge mid-gauntlet is far more
            likely to be confused than deliberate, and silently discarding the
            player's progress is not a recoverable mistake.

    Returns:
        ChallengeResult describing the first step, or an error result.
    """
    if state.challenge and not replace:
        return _error(
            f"a challenge is already running ({state.challenge.get('id', '?')})",
        )

    validated = spec_module.validate(proposed)
    if not validated.ok:
        return _error(validated.error, str(proposed.get("kind", "")) if isinstance(proposed, dict) else "")

    stored = validated.spec
    state.challenge = stored
    logger.info(
        "[challenges] Started (operation=start, id=%s, kind=%s, clamps=%d)",
        stored["id"],
        stored["kind"],
        len(validated.adjustments),
    )

    result = _present(stored)
    result.adjustments = validated.adjustments
    return result


def resolve(
    state: GameState,
    *,
    choice: str = "",
    answer: str = "",
    rng: Optional[random.Random] = None,
    ledger: Optional[Any] = None,
) -> ChallengeResult:
    """
    Advance the active challenge by one step, choice or answer.

    Args:
        choice: Option id, for a decision tree.
        answer: Typed answer, for a puzzle.
        rng: Optional RNG override. Defaults to the deterministic challenge
            stream, so a seed replays a gauntlet identically.
        ledger: Optional StoryLedger, passed through to effects.
    """
    active = state.challenge
    if not active:
        return _error("no active challenge")

    kind = str(active.get("kind", ""))
    if kind == "skill_gauntlet":
        return _resolve_gauntlet(state, active, rng=rng, ledger=ledger)
    if kind == "decision_tree":
        return _resolve_tree(state, active, choice, ledger=ledger)
    if kind == "puzzle":
        return _resolve_puzzle(state, active, answer, ledger=ledger)
    if kind == "dice_table":
        return _resolve_dice_table(state, active, rng=rng, ledger=ledger)

    # Unreachable via start(), reachable via a save written by a newer build.
    logger.error(
        "[challenges] Active challenge has an unknown kind, clearing "
        "(operation=resolve, kind=%s)",
        kind,
    )
    _clear(state)
    return _error(f"unknown challenge kind {kind!r}", kind)


def abandon(state: GameState) -> ChallengeResult:
    """Drop the active challenge with no reward and no penalty."""
    active = state.challenge
    if not active:
        return _error("no active challenge")
    result = ChallengeResult(
        challenge_id=str(active.get("id", "")),
        kind=str(active.get("kind", "")),
        status=STATUS_FAILURE,
        title=str(active.get("title", "")),
        text="You let it go.",
        ended=True,
        success=False,
    )
    _clear(state)
    return result


# ---------------------------------------------------------------------------
# Presenters
# ---------------------------------------------------------------------------


def _present_gauntlet(stored: dict[str, Any]) -> ChallengeResult:
    steps = stored["steps"]
    index = int(stored.get("step", 0))
    step = steps[index]
    return ChallengeResult(
        challenge_id=stored["id"],
        kind=stored["kind"],
        status=STATUS_ACTIVE,
        title=stored["title"],
        text=step.get("text", ""),
        message=f"{step['skill']} check ({step['difficulty']})",
        options=[{"id": "attempt", "text": "Attempt it"}],
        step=index,
        total_steps=len(steps),
    )


def _present_tree(stored: dict[str, Any]) -> ChallengeResult:
    node = stored["nodes"][stored["current"]]
    return ChallengeResult(
        challenge_id=stored["id"],
        kind=stored["kind"],
        status=STATUS_ACTIVE,
        title=stored["title"],
        text=node.get("text", ""),
        options=[
            {"id": o["id"], "text": o["text"]} for o in node.get("options", [])
        ],
    )


def _present_puzzle(stored: dict[str, Any]) -> ChallengeResult:
    attempts = int(stored.get("attempts_left", 1))
    return ChallengeResult(
        challenge_id=stored["id"],
        kind=stored["kind"],
        status=STATUS_ACTIVE,
        title=stored["title"],
        text=stored.get("prompt", ""),
        message=f"{attempts} attempts",
        answer_required=True,
    )


def _present_dice_table(stored: dict[str, Any]) -> ChallengeResult:
    return ChallengeResult(
        challenge_id=stored["id"],
        kind=stored["kind"],
        status=STATUS_ACTIVE,
        title=stored["title"],
        text=stored.get("prompt", ""),
        message=f"d{stored['die']}",
        options=[{"id": "roll", "text": "Roll"}],
    )


# ---------------------------------------------------------------------------
# Resolvers
# ---------------------------------------------------------------------------


#: Which presenter renders each challenge kind. Named rather than inlined in
#: `start` so `present` below can reach it: a challenge that has already
#: STARTED still has to be renderable, or the player who saved mid-gauntlet
#: reloads into a challenge the client cannot draw and no intent verb can
#: offer options for.
#:
#: Declared HERE, below the four functions, because a module-level dict is
#: evaluated at import.
_PRESENTERS = {
    "skill_gauntlet": _present_gauntlet,
    "decision_tree": _present_tree,
    "puzzle": _present_puzzle,
    "dice_table": _present_dice_table,
}


def _present(stored: dict[str, Any]) -> ChallengeResult:
    return _PRESENTERS[stored["kind"]](stored)


def present(state: GameState) -> Optional[ChallengeResult]:
    """
    The current step of the running challenge, or None if none is running.

    Read-only: this is what the intent layer asks in order to build the
    ``challenge`` verb's options, and building a prompt must never move the
    world.
    """
    stored = getattr(state, "challenge", None)
    if not stored or stored.get("kind") not in _PRESENTERS:
        return None
    try:
        return _present(stored)
    except (KeyError, IndexError) as exc:
        logger.warning(
            "[challenges] Cannot present stored challenge "
            "(operation=present, id=%s): %s",
            stored.get("id"),
            exc,
        )
        return None


def _resolve_gauntlet(
    state: GameState,
    active: dict[str, Any],
    *,
    rng: Optional[random.Random],
    ledger: Optional[Any],
) -> ChallengeResult:
    """One d20 skill check. Any failure ends the gauntlet."""
    steps = active["steps"]
    index = int(active.get("step", 0))
    step = steps[index]

    check = checks.resolve(
        state,
        step["skill"],
        step["difficulty"],
        rng=_rng(state, rng),
        ledger=ledger,
    )

    common = {
        "challenge_id": active["id"],
        "kind": active["kind"],
        "title": active["title"],
        "check": check.to_dict(),
        "dice": check.dice.to_dict(),
        "total_steps": len(steps),
    }

    if not check.success:
        outcome = active.get("fail", {})
        applied = _apply_outcome(state, outcome, ledger=ledger)
        _clear(state)
        logger.info(
            "[challenges] Gauntlet failed (operation=_resolve_gauntlet, id=%s, step=%d)",
            active["id"],
            index,
        )
        return ChallengeResult(
            status=STATUS_FAILURE,
            text=step.get("on_fail_text") or outcome.get("text") or "It slips away.",
            step=index,
            effects_applied=applied,
            ended=True,
            success=False,
            **common,
        )

    index += 1
    if index >= len(steps):
        outcome = active.get("reward", {})
        applied = _apply_outcome(state, outcome, ledger=ledger)
        _clear(state)
        logger.info(
            "[challenges] Gauntlet cleared (operation=_resolve_gauntlet, id=%s, steps=%d)",
            active["id"],
            len(steps),
        )
        return ChallengeResult(
            status=STATUS_SUCCESS,
            text=outcome.get("text") or f"{active['title']} — done.",
            step=index,
            effects_applied=applied,
            ended=True,
            success=True,
            **common,
        )

    active["step"] = index
    nxt = steps[index]
    return ChallengeResult(
        status=STATUS_ACTIVE,
        text=nxt.get("text", ""),
        message=f"{nxt['skill']} check ({nxt['difficulty']})",
        options=[{"id": "attempt", "text": "Attempt it"}],
        step=index,
        **common,
    )


def _resolve_tree(
    state: GameState,
    active: dict[str, Any],
    choice: str,
    *,
    ledger: Optional[Any],
) -> ChallengeResult:
    nodes = active["nodes"]
    node = nodes.get(active["current"], {})
    option = next(
        (o for o in node.get("options", []) if o.get("id") == choice), None
    )

    if option is None:
        # Re-present rather than penalise: an unrecognised choice is a UI or
        # model slip, not a decision the player made.
        return ChallengeResult(
            challenge_id=active["id"],
            kind=active["kind"],
            title=active["title"],
            status=STATUS_ACTIVE,
            text=node.get("text", ""),
            message="Pick one of the options.",
            options=[{"id": o["id"], "text": o["text"]} for o in node.get("options", [])],
        )

    target_id = option.get("goto", "")
    target = nodes.get(target_id, {})

    if target.get("terminal"):
        success = target.get("outcome", "success") == "success"
        outcome = target.get("reward" if success else "fail", {})
        applied = _apply_outcome(state, outcome, ledger=ledger)
        _clear(state)
        logger.info(
            "[challenges] Tree resolved (operation=_resolve_tree, id=%s, node=%s, success=%s)",
            active["id"],
            target_id,
            success,
        )
        return ChallengeResult(
            challenge_id=active["id"],
            kind=active["kind"],
            title=active["title"],
            status=STATUS_SUCCESS if success else STATUS_FAILURE,
            text=target.get("text") or outcome.get("text", ""),
            effects_applied=applied,
            ended=True,
            success=success,
        )

    active["current"] = target_id
    return ChallengeResult(
        challenge_id=active["id"],
        kind=active["kind"],
        title=active["title"],
        status=STATUS_ACTIVE,
        text=target.get("text", ""),
        options=[{"id": o["id"], "text": o["text"]} for o in target.get("options", [])],
    )


def _resolve_puzzle(
    state: GameState,
    active: dict[str, Any],
    answer: str,
    *,
    ledger: Optional[Any],
) -> ChallengeResult:
    common = {
        "challenge_id": active["id"],
        "kind": active["kind"],
        "title": active["title"],
    }

    if spec_module.normalise_answer(answer) == active.get("answer"):
        outcome = active.get("reward", {})
        applied = _apply_outcome(state, outcome, ledger=ledger)
        _clear(state)
        return ChallengeResult(
            status=STATUS_SUCCESS,
            text=outcome.get("text") or "The mechanism yields.",
            effects_applied=applied,
            ended=True,
            success=True,
            **common,
        )

    remaining = int(active.get("attempts_left", 1)) - 1
    active["attempts_left"] = remaining
    if remaining <= 0:
        outcome = active.get("fail", {})
        applied = _apply_outcome(state, outcome, ledger=ledger)
        _clear(state)
        return ChallengeResult(
            status=STATUS_FAILURE,
            text=outcome.get("text") or "The mechanism locks fast.",
            effects_applied=applied,
            ended=True,
            success=False,
            **common,
        )

    return ChallengeResult(
        status=STATUS_ACTIVE,
        text="Not quite — the dials reset.",
        message=f"{remaining} attempts left",
        answer_required=True,
        **common,
    )


def _resolve_dice_table(
    state: GameState,
    active: dict[str, Any],
    *,
    rng: Optional[random.Random],
    ledger: Optional[Any],
) -> ChallengeResult:
    die = int(active.get("die", spec_module.DEFAULT_DIE))
    dice = roll_dice(
        sides=die,
        reason=f"challenge:{active['id']}",
        rng=_rng(state, rng),
    )
    roll = dice.total
    match = next(
        (o for o in active["outcomes"] if int(o["min"]) <= roll <= int(o["max"])),
        active["outcomes"][-1],
    )
    applied = _apply_outcome(state, {"effects": match.get("effects", [])}, ledger=ledger)
    _clear(state)
    return ChallengeResult(
        challenge_id=active["id"],
        kind=active["kind"],
        title=active["title"],
        status=STATUS_SUCCESS,
        text=match.get("text", ""),
        dice=dice.to_dict(),
        effects_applied=applied,
        ended=True,
        success=True,
    )


__all__ = [
    "STATUS_ACTIVE",
    "STATUS_ERROR",
    "STATUS_FAILURE",
    "STATUS_SUCCESS",
    "ChallengeResult",
    "abandon",
    "resolve",
    "start",
]
