"""
Tool Dispatcher
===============

Executes @skill tools from Storyteller tool_calls and builds receipts.

``auto_resolve_skill_check`` used to live here: a fallback that fired a check
on the model's behalf whenever the JSON epilogue asked for one, inventing the
DC from ``base_dc = 12`` plus a ``dc_mod`` the model supplied, with exactly two
modifiers in the whole game (``+2`` stealth, ``+1`` persuasion). It is gone.
Difficulty is a band the model names and a number the engine derives -- see
engine/game/checks.py.

Version: v0.2.0 [2026-08-07]
"""

from __future__ import annotations

import json
import logging
from typing import Any

import engine.skills.builtin.assistant  # noqa: F401 — register skills
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