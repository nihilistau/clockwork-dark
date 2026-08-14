"""
Skill Registry
==============

@skill decorator — LLM-callable mechanical tools.

WHAT A SKILL MAY DECLARE, AND WHY THE LIST IS SHORT
---------------------------------------------------
Five fields used to sit on ``SkillDef`` that nothing ever read: ``cooldown``,
``cost``, ``prerequisites``, ``tags``, and two of the four trigger constants.
No shipped skill set a non-default for any of them and no caller consulted them
— ``SkillRegistry.invoke`` went straight to ``skill_def.func(**kwargs)``. That
is the same decorative-metadata bug this file's header once called out about
``agents``, which WAS load-bearing everywhere except the dispatcher.

They are deleted rather than enforced, and the reasoning matters because
CosySim's ``execute_skill`` + ``CooldownTracker`` is the obvious thing to port:

* CosySim's skills call ComfyUI, a vector store and the filesystem — genuinely
  rate-limited things a wall-clock cooldown protects. Every skill here is a
  pure in-process mutation of one player's ``GameState``. There is nothing to
  rate-limit; a real-seconds cooldown would also break replay, because the same
  seed would resolve differently depending on how fast the model answered.
* ``cost`` and ``prerequisites`` would be a SECOND economy beside the one the
  engine already runs. Actions are priced in stamina and in-game hours by
  ``effects.apply_effect`` and ``clock.advance_time``, which critical rules 2
  and 3 name as the only writers. A skill-level cost would be a second writer
  of the same budget, disagreeing with the first.
* ``TRIGGER_AUTO`` was a value no skill ever carried and no code could produce.
  ``TRIGGER_REQUIRED`` labelled six skills "the model must call this first" and
  nothing made that true; the obligation lives in the prompt, which is the only
  place it CAN live, since no server can force a model to call a tool.

What survives is what runs: ``trigger`` now distinguishes exactly the two cases
the code acts on — ``system`` (defaults the skill to the system agent, out of
the model's reach) and ``optional`` (everything else).

Version: v0.2.0 [2026-08-14]
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

TRIGGER_OPTIONAL = "optional"
TRIGGER_SYSTEM = "system"

AGENT_STORYTELLER = "storyteller"
AGENT_ASSISTANT = "assistant"
AGENT_SYSTEM = "system"

logger = logging.getLogger(__name__)


@dataclass
class SkillDef:
    """Registered skill metadata."""

    name: str
    pack: str
    description: str
    category: str
    func: Callable[..., str]
    trigger: str = TRIGGER_OPTIONAL
    # Which agents may call this. The trigger/category metadata was previously
    # decorative: the dispatcher executed anything present in the registry, so
    # a system-only time skill was fully reachable by the model.
    agents: list[str] = field(default_factory=lambda: [AGENT_STORYTELLER])
    params_schema: Optional[dict[str, Any]] = None

    def callable_by(self, agent: str) -> bool:
        return agent in self.agents


class SkillRegistry:
    """Global skill registry."""

    def __init__(self) -> None:
        self._skills: dict[str, SkillDef] = {}

    def register(self, skill_def: SkillDef) -> None:
        existing = self._skills.get(skill_def.name)
        if existing is not None and existing.func is not skill_def.func:
            # Silently taking the last import's definition makes a name clash
            # between two skill packs invisible until something misbehaves.
            logger.warning(
                "[skills] Duplicate skill name overwritten "
                "(operation=register, skill=%s, was=%s, now=%s)",
                skill_def.name,
                existing.pack,
                skill_def.pack,
            )
        self._skills[skill_def.name] = skill_def

    def tools_for_agent(self, agent: str) -> list[SkillDef]:
        """Skills a given agent is permitted to call."""
        return [s for s in self._skills.values() if s.callable_by(agent)]

    def get(self, name: str) -> Optional[SkillDef]:
        return self._skills.get(name)

    def all_tools(self) -> list[SkillDef]:
        return list(self._skills.values())

    def get_pack_tools(self, pack: str) -> list[SkillDef]:
        return [s for s in self._skills.values() if s.pack == pack]

    def count(self) -> int:
        return len(self._skills)

    def invoke(self, name: str, **kwargs: Any) -> str:
        """Invoke skill by name; returns JSON string."""
        skill_def = self._skills.get(name)
        if skill_def is None:
            return json.dumps({"error": f"Unknown skill: {name}"})
        try:
            result = skill_def.func(**kwargs)
            return result if isinstance(result, str) else json.dumps(result)
        except Exception as exc:
            return json.dumps({"error": str(exc)})


SKILL_REGISTRY = SkillRegistry()


def skill(
    pack: str,
    description: str,
    category: str = "GAME",
    name: Optional[str] = None,
    trigger: str = TRIGGER_OPTIONAL,
    agents: Optional[list[str]] = None,
    params_schema: Optional[dict[str, Any]] = None,
) -> Callable[[Callable[..., str]], Callable[..., str]]:
    """Register a skill function."""

    def decorator(func: Callable[..., str]) -> Callable[..., str]:
        skill_name = name or func.__name__
        resolved_agents = agents
        if resolved_agents is None:
            resolved_agents = (
                [AGENT_SYSTEM] if trigger == TRIGGER_SYSTEM else [AGENT_STORYTELLER]
            )
        SKILL_REGISTRY.register(
            SkillDef(
                name=skill_name,
                pack=pack,
                description=description,
                category=category,
                func=func,
                trigger=trigger,
                agents=list(resolved_agents),
                params_schema=params_schema,
            )
        )
        return func

    return decorator