"""
Planning
========

Asking one declared agent what it wants, before anything is committed.

WHY THIS IS SEPARATE FROM ``character.py``. That module is a character who
speaks after the fact -- it takes finished narration and reacts to it. A planner
runs BEFORE the world has written anything, sees the player's action rather than
the world's answer to it, and produces a proposal that can still be argued with.
The two are different moments, and collapsing them is what made the second agent
a commentator.

WHAT AN AGENT SEES IS ITS ROSTER'S BUSINESS. The prompt is assembled from
scope-tagged blocks and filtered through ``KnowledgePolicy``, so an agent barred
from ``gm_secrets`` never receives them. Filtering here rather than instructing
the model is the whole point: "do not use the following" is a request, and this
is a wall.

COST. One structured call per agent, on a small schema -- much cheaper than
narration. For The Wicked Garden this replaces the character call that already
happened at the end of the turn, so the turn's shape changes without its budget
changing much: she plans instead of reacting, and the narrator writes once
knowing what she decided.

Version: v0.1.0 [2026-08-09]
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Callable, Optional

from engine.agents.plan import AgentPlan, parse_plan, plan_schema

logger = logging.getLogger(__name__)

#: A plan is a few short fields. A model given room writes a scene instead.
MAX_TOKENS = 320


def persona_for(spec: Any) -> str:
    """
    An agent's own voice file, from the story's prompt directory.

    Empty when the story declares an agent but ships no prompt for it, and an
    empty persona means the agent does not plan at all. An agent with no voice
    should be absent, not improvised from the engine's idea of one.
    """
    from engine.config import get_config, project_root

    name = str(getattr(spec, "prompt", "") or "")
    if not name:
        return ""
    base = str(get_config().get("paths.prompts", "") or "")
    if not base:
        return ""
    root = Path(base)
    if not root.is_absolute():
        root = project_root() / root
    # `prompt: prompts/sophia.md` is relative to the story root and
    # `paths.prompts` already points there, so take the leaf.
    target = root / Path(name).name
    try:
        return target.read_text(encoding="utf-8").strip()
    except OSError as exc:
        logger.warning(
            "[planner] No voice file, agent will not plan "
            "(operation=persona_for, agent=%s, path=%s): %s",
            getattr(spec, "id", "?"),
            target,
            exc,
        )
        return ""


def _situation(spec: Any, state: Any, player_action: str, policy: Any) -> str:
    """
    What this agent may know about the moment it is planning against.

    Every block carries a scope and goes through the policy. The player's action
    is public -- both agents saw it happen. The agent's own meters are its own.
    """
    from engine.agents.knowledge import SCOPE_CHARACTER, SCOPE_PUBLIC

    blocks: list[tuple[str, str]] = [
        (SCOPE_PUBLIC, f"Where everyone is: {state.location_id}."),
        (SCOPE_PUBLIC, f"What the player just did:\n{(player_action or '').strip()}"),
    ]

    try:
        from engine.state.active import store_for
        from engine.state.schema import VISIBILITY_HIDDEN

        store = store_for(state)
        mine = [
            f"{value.display_label}: {value.band(store.get(name))}"
            for name, value in store.schema.values.items()
            if spec.id in value.owners and value.visibility != VISIBILITY_HIDDEN
        ]
        if mine:
            blocks.append((SCOPE_CHARACTER, "What is yours to move: " + "; ".join(mine)))
    except Exception as exc:  # noqa: BLE001 -- a missing meter is not a turn
        logger.debug("[planner] No declared meters for %s: %s", getattr(spec, "id", "?"), exc)

    if policy is None:
        return "\n\n".join(text for _scope, text in blocks)
    return "\n\n".join(policy.filter_blocks(spec.id, blocks))


#: Appended to every planner prompt. Says what a plan IS, because the personas
#: are written for narration and a model handed one will narrate.
_PLAN_BRIEF = """\
You are PLANNING this turn, not writing it. Nothing you say here reaches the
player as prose.

Answer with your intent, one line of what you want to happen (`beat`), and --
only if you are a character who speaks -- the words you actually say (`line`).
Do not describe the room. Do not speak for anyone else. Silence is a real
answer and a good one when you have nothing to want.
"""


def plan_for(
    spec: Any,
    state: Any,
    player_action: str,
    *,
    policy: Any = None,
    llm_fn: Optional[Callable[[list[dict[str, Any]]], str]] = None,
) -> AgentPlan:
    """
    One agent's proposal for this turn.

    Never raises. A model outage, a malformed answer or a missing persona all
    produce a silent plan, because an agent failing to plan must cost that agent
    its turn and never the player's -- the negotiator handles a silent plan as a
    normal case, and the turn goes on with whoever is left.
    """
    empty = AgentPlan(agent=spec.id)

    persona = persona_for(spec)
    if not persona:
        return empty

    writable = tuple(getattr(spec, "all_writes", ()) or ())
    schema = plan_schema(
        spec.id,
        voices=tuple(getattr(spec, "voices", ()) or ()),
        writable=writable,
    )

    messages = [
        {"role": "system", "content": f"{persona}\n\n{_PLAN_BRIEF}"},
        {"role": "user", "content": _situation(spec, state, player_action, policy)},
    ]

    try:
        raw = _infer(spec, messages, schema, llm_fn)
        data = json.loads(raw) if isinstance(raw, str) else raw
    except Exception as exc:  # noqa: BLE001 -- an agent's silence is not an outage
        logger.warning(
            "[planner] No plan, treating as silent (operation=plan_for, agent=%s): %s",
            spec.id,
            exc,
        )
        return empty

    plan = parse_plan(
        spec.id,
        data if isinstance(data, dict) else {},
        writable=writable,
        needs_reason=tuple(getattr(spec, "writes_with_reason", ()) or ()),
    )
    logger.info(
        "[planner] Planned (operation=plan_for, agent=%s, intent=%s, effects=%d, "
        "choices=%d, refused=%d)",
        plan.agent,
        plan.intent,
        len(plan.effects),
        len(plan.choices),
        len(plan.refused),
    )
    return plan


def _infer(
    spec: Any,
    messages: list[dict[str, Any]],
    schema: dict[str, Any],
    llm_fn: Optional[Callable[[list[dict[str, Any]]], str]],
) -> Any:
    if llm_fn is not None:
        return llm_fn(messages)

    from engine.lmstudio.backend import get_backend

    return get_backend().chat(
        messages,
        profile=str(getattr(spec, "profile", "small") or "small"),
        max_tokens=MAX_TOKENS,
        label=f"plan:{spec.id}",
        response_format={
            "type": "json_schema",
            "json_schema": {"name": "agent_plan", "strict": True, "schema": schema},
        },
    ).content


__all__ = ["MAX_TOKENS", "persona_for", "plan_for"]
