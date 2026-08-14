"""
Tool Dispatcher
===============

Executes skills and builds receipts.

``auto_resolve_skill_check`` used to live here: a fallback that fired a check
on the model's behalf whenever the JSON epilogue asked for one, inventing the
DC from ``base_dc = 12`` plus a ``dc_mod`` the model supplied, with exactly two
modifiers in the whole game (``+2`` stealth, ``+1`` persuasion). It is gone.
Difficulty is a band the model names and a number the engine derives -- see
engine/game/checks.py.

TWO CALLERS, ONE EXECUTOR. ``execute_tool_calls`` reads a ``tool_calls`` array
out of a model reply; ``execute_intent`` (added in v0.3.0) runs the structured
intent the player's chosen option declared. Only the second one is reachable in
real play -- the turn grammar forbids a ``tool_calls`` key outright, which is
the defect ``engine/game/intents.py`` documents at length. ``execute_tool_calls``
survives because the negotiation pipeline and the test suite still drive it,
and because both paths producing the same receipt shape is what lets the
narrator's MECHANICAL RESULTS block stay one format.

Version: v0.3.0 [2026-08-14]
"""

from __future__ import annotations

import json
import logging
from typing import Any

import engine.skills.builtin.assistant  # noqa: F401 — register skills
import engine.skills.builtin.items  # noqa: F401 — register skills
import engine.skills.builtin.livelihood  # noqa: F401 — register skills
import engine.skills.builtin.mechanics  # noqa: F401 — register skills
import engine.skills.builtin.quests  # noqa: F401 — register skills
from engine.game.engine import GameEngine, set_active_engine
from engine.skills.registry import AGENT_STORYTELLER, SKILL_REGISTRY

logger = logging.getLogger(__name__)


def execute_tool(name: str, args: dict[str, Any], engine: GameEngine) -> dict[str, Any]:
    """
    Invoke a registered skill and return receipt + raw result.

    Args:
        name: Skill name.
        args: Skill arguments.
        engine: Active game engine.

    Returns:
        Receipt dict with skill, args, result, success.
    """
    set_active_engine(engine)

    # The ** unpack must live inside the guard. It previously sat outside the
    # registry's try/except, so a model emitting `"args": ["stealth", 12]` --
    # routine for small local models -- raised TypeError straight out of the
    # turn handler and froze the UI.
    if not isinstance(args, dict):
        return {
            "skill": name,
            "args": args,
            "result": {"error": f"args must be an object, got {type(args).__name__}"},
            "success": False,
        }

    try:
        raw = SKILL_REGISTRY.invoke(name, **args)
    except TypeError as exc:
        return {
            "skill": name,
            "args": args,
            "result": {"error": f"bad arguments for {name}: {exc}"},
            "success": False,
        }

    try:
        result = json.loads(raw)
        success = isinstance(result, dict) and "error" not in result
    except json.JSONDecodeError:
        result = {"raw": raw}
        success = False

    receipt: dict[str, Any] = {
        "skill": name,
        "args": args,
        "result": result,
        "success": success,
    }
    if name in ("roll_dice", "resolve_skill_check"):
        receipt["type"] = "dice"
    elif name == "move_to":
        receipt["type"] = "move"
    elif name == "query_evil_state":
        receipt["type"] = "gm"
    return receipt


def execute_intent(
    intent: Any,
    engine: GameEngine,
    *,
    agent: str = AGENT_STORYTELLER,
) -> list[dict[str, Any]]:
    """
    Resolve the structured intent the player's chosen option declared.

    This is the production channel that makes a narration turn able to change
    the world. It runs BEFORE the next turn's narration, so the receipt it
    produces is an input to the prose rather than a claim the prose has to be
    trusted about.

    Legality is re-checked here, against the live state, rather than trusted
    from when the option was written: the intent was declared on the previous
    turn and the world has ticked since. An intent that has gone illegal comes
    back as an engine-authored refusal receipt, never as an empty list -- a
    silent no-op is what produced the original bug report.

    Args:
        intent: The chosen choice's ``intent`` object. Anything unusable --
            missing, malformed, or from a save written before intents existed
            -- yields ``[]`` and the turn behaves exactly as it did before.
        engine: Active game engine.
        agent: Caller identity, checked against the skill's allowlist.

    Returns:
        Zero or one receipt, in the same shape ``execute_tool`` produces.
    """
    from engine.game import intents as intents_module

    parsed = intents_module.normalise(intent)
    if not parsed:
        return []

    verbs = intents_module.legal_intents(engine.state)
    verb = intents_module.find_verb(verbs, parsed["action"])
    if verb is None:
        return [
            intents_module.refusal(
                parsed,
                f"{parsed['action']} is not something you can do here right now.",
            )
        ]

    target = parsed.get("target", "")
    if verb.targets and target not in verb.targets:
        return [
            intents_module.refusal(
                parsed,
                f"{target or 'that'} is not a legal {parsed['action']} target "
                f"from here. Legal now: {', '.join(verb.targets)}.",
            )
        ]

    try:
        name, args = intents_module.to_tool_call(engine.state, parsed)
    except KeyError:
        logger.warning(
            "[tool_dispatcher] Intent has no skill "
            "(operation=execute_intent, action=%s)",
            parsed["action"],
        )
        return [intents_module.refusal(parsed, "the engine has no way to do that.")]

    skill_def = SKILL_REGISTRY.get(name)
    if skill_def is None or not skill_def.callable_by(agent):
        return [
            intents_module.refusal(
                parsed, f"{name} is not available to {agent}."
            )
        ]

    receipt = execute_tool(name, args, engine)
    receipt["intent"] = dict(parsed)

    # The skill ran and said no. Marked as a refusal so the narrator is told
    # plainly that it did not happen, instead of being handed a travel line for
    # a leg that was never walked. Which key counts as a refusal is declared
    # per verb -- a failed skill check reports `success: false` and is an
    # outcome, not a refusal. See REFUSAL_KEY_FOR_ACTION.
    declined = intents_module.declined_reason(
        parsed["action"], receipt.get("result")
    )
    if receipt.get("success") and declined:
        receipt["success"] = False
        receipt["refused"] = True
        receipt["result"] = {**receipt["result"], "error": declined}
        logger.info(
            "[tool_dispatcher] Intent refused by the engine "
            "(operation=execute_intent, action=%s, target=%s, reason=%s)",
            parsed["action"],
            target,
            declined,
        )
    elif not receipt.get("success"):
        receipt["refused"] = True

    return [receipt]


def execute_tool_calls(
    tool_calls: list[dict[str, Any]],
    engine: GameEngine,
    *,
    agent: str = AGENT_STORYTELLER,
) -> list[dict[str, Any]]:
    """
    Execute a list of tool call dicts with name/args keys.

    Args:
        tool_calls: Raw tool calls from the model. Tolerates malformed shapes.
        engine: Active game engine.
        agent: Caller identity, checked against each skill's allowlist. This is
            what keeps system-only skills -- notably the unbounded world tick --
            out of the model's reach.
    """
    receipts: list[dict[str, Any]] = []

    # Models routinely emit a bare object instead of a list of them.
    if isinstance(tool_calls, dict):
        tool_calls = [tool_calls]
    if not isinstance(tool_calls, list):
        return receipts

    for call in tool_calls:
        if not isinstance(call, dict):
            logger.warning(
                "[tool_dispatcher] Skipping non-object tool call "
                "(operation=execute_tool_calls, got=%r)",
                call,
            )
            continue
        name = call.get("name") or call.get("skill", "")
        args = call.get("args") or call.get("arguments") or {}
        if not name:
            continue
        skill_def = SKILL_REGISTRY.get(name)
        if skill_def is None:
            logger.warning(
                "[tool_dispatcher] Unknown skill (operation=execute_tool, skill=%s)",
                name,
            )
            receipts.append(
                {
                    "skill": name,
                    "args": args,
                    "result": {"error": f"Unknown skill: {name}"},
                    "success": False,
                }
            )
            continue

        if not skill_def.callable_by(agent):
            logger.warning(
                "[tool_dispatcher] Skill not permitted for agent "
                "(operation=execute_tool, skill=%s, agent=%s)",
                name,
                agent,
            )
            receipts.append(
                {
                    "skill": name,
                    "args": args,
                    "result": {"error": f"{name} is not callable by {agent}"},
                    "success": False,
                }
            )
            continue

        receipts.append(execute_tool(name, args, engine))
    return receipts


__all__ = ["execute_intent", "execute_tool", "execute_tool_calls"]