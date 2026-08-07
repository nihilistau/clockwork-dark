"""
Two-Phase Turn Loop
===================

The single highest-leverage change in the overhaul.

Before, the model was asked to emit ``tool_calls`` AND the narration in one
message. It could not possibly know the outcome of a roll it had just
requested, so the prompt's central rule -- "NEVER invent dice results" -- was
architecturally unsatisfiable. The evaluator then tried to police the result
after the fact, and its main anti-hallucination branch was itself unreachable
because ``auto_resolve_skill_check`` always fired first and satisfied the
condition it was checking.

Now:

    Phase A  MECHANICS   low temperature, tools enabled, no prose.
                         Each requested tool runs transactionally; the result
                         is appended as a role:"tool" message and the model may
                         take one more round.

    Phase B  NARRATION   high temperature, streaming, JSON schema enforced,
                         with an authoritative MECHANICAL RESULTS block.

The model narrates outcomes it has already been shown. Anti-hallucination stops
being a rule it is asked to follow and becomes a property of the pipeline.

Version: v0.2.0 [2026-08-07]
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from engine.agents.json_stream import NarrationStreamer, extract_json
from engine.agents.tag_buffer import TagBuffer
from engine.agents.tool_dispatcher import execute_tool
from engine.game.engine import GameEngine
from engine.game.transaction import StateTransaction
from engine.lmstudio.gate import inference_slot
from engine.lmstudio.schemas import response_format, storyteller_turn_schema
from engine.lmstudio.tools import build_manifest
from engine.memory.context import build_storyteller_messages, present_npc_ids
from engine.memory.ledger import StoryLedger, apply_ledger_delta
from engine.skills.registry import AGENT_STORYTELLER, SKILL_REGISTRY

logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 2
MAX_TOOLS_PER_ROUND = 4

FALLBACK_CHOICES = [
    {"id": "a", "text": "Look around", "hint": "safe"},
    {"id": "b", "text": "Wait and listen", "hint": "safe"},
]


@dataclass
class PhaseResult:
    """Outcome of one full turn through the loop."""

    narration: str = ""
    choices: list[dict[str, Any]] = field(default_factory=list)
    npc_voices: list[dict[str, Any]] = field(default_factory=list)
    tool_receipts: list[dict[str, Any]] = field(default_factory=list)
    ledger_accepted: dict[str, Any] = field(default_factory=dict)
    mood: str = ""
    image_tag: str = ""
    tags: list[tuple[str, str]] = field(default_factory=list)
    raw: str = ""
    truncated: bool = False


def _dispatch(
    call_name: str,
    args: dict[str, Any],
    engine: GameEngine,
    tx: StateTransaction,
) -> dict[str, Any]:
    """Run one tool inside a savepoint so a failure cannot half-apply."""
    try:
        with tx.savepoint():
            return execute_tool(call_name, args, engine)
    except Exception as exc:  # noqa: BLE001 — surfaced to the model as a receipt
        logger.warning(
            "[turn_loop] Tool raised (operation=_dispatch, tool=%s): %s", call_name, exc
        )
        return {
            "skill": call_name,
            "args": args,
            "result": {"error": str(exc)},
            "success": False,
        }


def run_mechanics_phase(
    engine: GameEngine,
    ledger: StoryLedger,
    player_action: str,
    *,
    client: Any,
    tx: StateTransaction,
    evil_snapshot: Optional[dict[str, Any]] = None,
    lore_block: str = "",
    max_rounds: int = MAX_TOOL_ROUNDS,
) -> list[dict[str, Any]]:
    """
    Phase A: let the model request mechanical resolution, and resolve it.

    Returns the receipts. Deliberately cheap: low temperature, few tokens, no
    few-shot examples, no prose. Its only job is deciding which dice to roll.
    """
    from engine.lmstudio.profiles import resolve_profile

    manifest = build_manifest(AGENT_STORYTELLER)
    if not manifest:
        return []

    profile = resolve_profile("small")
    messages = build_storyteller_messages(
        engine.state,
        ledger,
        player_action,
        evil_snapshot=evil_snapshot,
        lore_block=lore_block,
        include_examples=False,
    )
    messages.append(
        {
            "role": "system",
            "content": (
                "MECHANICS PASS. Do not narrate. Decide only whether this action "
                "needs mechanical resolution, and if so call the tools for it. "
                "Call nothing if the action is ordinary conversation or movement "
                "within a room. Never call more than two tools."
            ),
        }
    )

    receipts: list[dict[str, Any]] = []
    for round_index in range(max_rounds):
        try:
            with inference_slot(label="mechanics"):
                response = client.chat(
                    messages,
                    model=profile.model,
                    temperature=0.3,
                    max_tokens=400,
                    tools=manifest,
                    tool_choice="auto",
                )
        except Exception as exc:  # noqa: BLE001 — mechanics are optional
            logger.warning(
                "[turn_loop] Mechanics pass failed (operation=run_mechanics_phase): %s",
                exc,
            )
            break

        if not response.tool_calls:
            break

        assistant_msg: dict[str, Any] = {"role": "assistant", "content": None, "tool_calls": []}
        tool_msgs: list[dict[str, Any]] = []

        for call in response.tool_calls[:MAX_TOOLS_PER_ROUND]:
            skill_def = SKILL_REGISTRY.get(call.name)
            if skill_def is None or not skill_def.callable_by(AGENT_STORYTELLER):
                continue

            receipt = _dispatch(call.name, call.arguments, engine, tx)
            receipts.append(receipt)

            assistant_msg["tool_calls"].append(
                {
                    "id": call.id,
                    "type": "function",
                    "function": {"name": call.name, "arguments": str(call.arguments)},
                }
            )
            tool_msgs.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": str(receipt.get("result", {})),
                }
            )

        if not tool_msgs:
            break

        messages.append(assistant_msg)
        messages.extend(tool_msgs)

    return receipts


def run_narration_phase(
    engine: GameEngine,
    ledger: StoryLedger,
    player_action: str,
    receipts: list[dict[str, Any]],
    *,
    client: Any,
    evil_snapshot: Optional[dict[str, Any]] = None,
    lore_block: str = "",
    retry_note: str = "",
    on_delta: Optional[Callable[[str], None]] = None,
) -> PhaseResult:
    """
    Phase B: narrate the outcomes the engine already decided.

    Streams narration to ``on_delta`` as it decodes, so the player sees text
    appear rather than watching a frozen screen for the whole generation.
    """
    from engine.lmstudio.profiles import resolve_profile

    profile = resolve_profile("big")
    npc_ids = present_npc_ids(engine.state)
    schema = storyteller_turn_schema(npc_ids=npc_ids)

    messages = build_storyteller_messages(
        engine.state,
        ledger,
        player_action,
        evil_snapshot=evil_snapshot,
        lore_block=lore_block,
        receipts=receipts,
        include_examples=True,
        retry_note=retry_note,
    )

    streamer = NarrationStreamer()
    tags = TagBuffer()
    raw_parts: list[str] = []

    def _forward(delta: str) -> None:
        raw_parts.append(delta)
        if on_delta is None:
            return
        text = streamer.push(delta)
        if text:
            safe = tags.push(text)
            if safe:
                on_delta(safe)

    truncated = False
    try:
        with inference_slot(label="narration"):
            generator = client.chat_stream(
                messages,
                model=profile.model,
                temperature=profile.temperature,
                max_tokens=profile.max_tokens,
                on_delta=_forward,
                response_format=response_format(schema),
            )
            # chat_stream yields deltas and returns the response via StopIteration.
            try:
                while True:
                    next(generator)
            except StopIteration as stop:
                final = stop.value
                truncated = bool(getattr(final, "truncated", False))
    except Exception as exc:  # noqa: BLE001 — turn must still produce something
        logger.error("[turn_loop] Narration failed (operation=run_narration_phase): %s", exc)

    if on_delta is not None:
        tail = tags.push(streamer.push("")) + tags.flush()
        if tail:
            on_delta(tail)

    raw = "".join(raw_parts)
    return _finalize(raw, streamer, tags, truncated)


def _finalize(
    raw: str,
    streamer: NarrationStreamer,
    tags: TagBuffer,
    truncated: bool,
) -> PhaseResult:
    """Parse the completed object, falling back to whatever text we streamed."""
    parsed = extract_json(raw) or {}

    narration = str(parsed.get("narration") or streamer.text or "").strip()
    if not narration:
        # Everything failed: show the prose rather than the JSON. The old
        # fallback handed the player a raw JSON blob as narration.
        narration = raw.strip()

    choices = parsed.get("choices") or []
    if not isinstance(choices, list) or len(choices) < 2:
        # A zero-choice turn soft-locks the game; the old evaluator scored it
        # 0.86 and passed it.
        choices = list(FALLBACK_CHOICES)

    return PhaseResult(
        narration=narration,
        choices=choices,
        npc_voices=parsed.get("npc_voices") or [],
        ledger_accepted={},
        mood=str(parsed.get("mood") or ""),
        image_tag=str(parsed.get("image_tag") or ""),
        tags=list(tags.tags),
        raw=raw,
        truncated=truncated,
    )


def commit_ledger(
    result: PhaseResult,
    parsed_delta: dict[str, Any],
    ledger: StoryLedger,
    engine: GameEngine,
) -> None:
    """Apply the model's proposed memory delta, validated against known NPCs."""
    state = engine.state
    known = {str(n.get("id")) for n in state.procgen.npcs if n.get("id")}
    result.ledger_accepted = apply_ledger_delta(
        ledger,
        parsed_delta,
        turn=state.turn_number,
        day=state.world_day,
        known_npc_ids=known,
    )
