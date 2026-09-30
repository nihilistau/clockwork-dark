"""
Skill to Tool Schema
====================

Turns registered ``@skill`` functions into OpenAI tool definitions by
inspection, so the manifest cannot drift from the implementations.

The old prompt listed four tool signatures as a bare bullet list -- no types,
no ranges, no guidance on when not to call one, and it omitted two registered
skills entirely, so the model never knew ``trade`` existed.

Version: v0.2.0 [2026-08-07]
"""

from __future__ import annotations

import inspect
import logging
from typing import Any, Optional, get_type_hints

from engine.skills.registry import (
    AGENT_STORYTELLER,
    SKILL_REGISTRY,
    SkillDef,
)

logger = logging.getLogger(__name__)

_JSON_TYPES: dict[Any, str] = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    list: "array",
    dict: "object",
}


def _json_type(annotation: Any) -> str:
    return _JSON_TYPES.get(annotation, "string")


def skill_to_openai_tool(skill_def: SkillDef) -> dict[str, Any]:
    """Build an OpenAI tool definition from a skill's signature."""
    if skill_def.params_schema is not None:
        parameters = skill_def.params_schema
    else:
        signature = inspect.signature(skill_def.func)
        try:
            hints = get_type_hints(skill_def.func)
        except Exception:  # noqa: BLE001 — annotations may reference missing names
            hints = {}

        properties: dict[str, Any] = {}
        required: list[str] = []
        for name, param in signature.parameters.items():
            if name in ("self", "cls") or param.kind in (
                inspect.Parameter.VAR_POSITIONAL,
                inspect.Parameter.VAR_KEYWORD,
            ):
                continue
            properties[name] = {"type": _json_type(hints.get(name, str))}
            if param.default is inspect.Parameter.empty:
                required.append(name)

        parameters = {
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        }

    return {
        "type": "function",
        "function": {
            "name": skill_def.name,
            "description": skill_def.description,
            "parameters": parameters,
        },
    }


def build_manifest(
    agent: str = AGENT_STORYTELLER,
    *,
    exclude: Optional[set[str]] = None,
) -> list[dict[str, Any]]:
    """
    Tool definitions the given agent may call.

    Filtered by the registry's own allowlist, so a system-only skill can never
    reach the model by being forgotten in a hand-maintained list.
    """
    exclude = exclude or set()
    manifest = [
        skill_to_openai_tool(s)
        for s in SKILL_REGISTRY.tools_for_agent(agent)
        if s.name not in exclude
    ]
    logger.debug(
        "[tools] Manifest built (operation=build_manifest, agent=%s, count=%s)",
        agent,
        len(manifest),
    )
    return manifest


def tool_names(agent: str = AGENT_STORYTELLER) -> list[str]:
    return [s.name for s in SKILL_REGISTRY.tools_for_agent(agent)]
