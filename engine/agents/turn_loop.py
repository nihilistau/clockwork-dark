"""
Two-Phase Turn Loop
===================

**NOT WIRED.** Nothing imports this module. The live path is
``content/scenes/clockwork/clockwork_state.run_turn`` ->
``engine/agents/storyteller.StorytellerAgent.run_turn``, which implements a
weaker SINGLE-phase version of the same idea: it asks for tool calls and prose
in one message, then executes the tools afterwards.

So two turn architectures coexist in this repo and the better one is dark. Read
that as a warning, not as an endorsement -- this file has never run in
production and its docstring below describes an intent, not observed behaviour.

It is kept rather than deleted because it is the designated basis for the
multi-agent pipeline (plan -> negotiate -> commit -> narrate): the phase split,
the per-tool savepoints and the pre-dispatch ACL check at ``_dispatch`` are all
the shapes that work needs, and rewriting them from scratch would be waste.

One thing it had that the live path did not, ``commit_ledger``, has been lifted
out and wired into ``clockwork_state._record_memory`` -- the model's proposed
facts, names, promises and dispositions were being parsed and discarded on every
turn because this module's only caller was nobody. That is fixed independently
of this file's fate; see ``tests/test_ledger_delta_wiring.py``.

---

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
from engine.lmstudio.schemas import storyteller_turn_schema
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
    client: Any = None,
    tx: StateTransaction,
    evil_snapshot: Optional[dict[str, Any]] = None,
    lore_block: str = "",
    max_rounds: int = MAX_TOOL_ROUNDS,
) -> list[dict[str, Any]]:
    """
    Phase A: let the model request mechanical resolution, and resolve it.

    Returns the receipts. Low temperature, no few-shot examples, no prose. Its
    only job is deciding which dice to roll.

    NOT as cheap as it looks. Tool calling is only available on the
    OpenAI-compatible transport, and that transport cannot disable reasoning --
    so the old hardcoded ``max_tokens=400`` was the same trap that produced
    empty narration: a reasoning model spends the cap thinking and emits no
    tool calls at all, which this loop reads as "no mechanics needed". The cap
    now comes from the profile, and a starved pass says so.
    """
    from engine.lmstudio.backend import get_backend

    manifest = build_manifest(AGENT_STORYTELLER)
    if not manifest:
        return []

    backend = client or get_backend()
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
            response = backend.chat(
                messages,
                profile="small",
                temperature=0.3,
                tools=manifest,
                tool_choice="auto",
                label="mechanics",
                # A reasoning-off retry would go native, and native cannot call
                # tools at all -- the retry could only return prose.
                retry_on_starvation=False,
            )
        except Exception as exc:  # noqa: BLE001 — mechanics are optional
            logger.warning(
                "[turn_loop] Mechanics pass failed (operation=run_mechanics_phase): %s",
                exc,
            )
            break

        if not response.tool_calls:
            if response.starved_by_reasoning:
                logger.error(
                    "[turn_loop] Mechanics pass emitted NO tool calls because the "
                    "model spent its whole token budget reasoning "
                    "(operation=run_mechanics_phase, model=%s, reasoning_tokens=%s). "
                    "This turn will resolve with no dice.",
                    response.model,
                    response.reasoning_tokens,
                )
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
    client: Any = None,
    evil_snapshot: Optional[dict[str, Any]] = None,
    lore_block: str = "",
    retry_note: str = "",
    on_delta: Optional[Callable[[str], None]] = None,
    on_reasoning: Optional[Callable[[str], None]] = None,
) -> PhaseResult:
    """
    Phase B: narrate the outcomes the engine already decided.

    Streams narration to ``on_delta`` as it decodes, so the player sees text
    appear rather than watching a frozen screen for the whole generation.

    Reasoning goes to ``on_reasoning`` and never to the narration decoder --
    the decoder's buffer grows without bound and rescans from the start, so
    feeding it a reasoning transcript is quadratic as well as wrong.

    Args:
        client: Backend override. Defaults to the routed LM Studio backend,
            which picks native or OpenAI-compat per request.
        on_reasoning: Live sink for the model's thinking channel.
    """
    from engine.lmstudio.backend import get_backend

    backend = client or get_backend()
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
        generator = backend.chat_stream(
            messages,
            profile="big",
            on_delta=_forward,
            on_reasoning=on_reasoning,
            response_format=backend.structured_output(schema),
        )
        # chat_stream yields deltas and returns the response via StopIteration.
        try:
            while True:
                next(generator)
        except StopIteration as stop:
            final = stop.value
            truncated = bool(getattr(final, "truncated", False))
            if getattr(final, "starved_by_reasoning", False):
                logger.error(
                    "[turn_loop] Narration came back EMPTY because the model "
                    "spent its whole token budget reasoning "
                    "(operation=run_narration_phase, model=%s, reasoning_tokens=%s)",
                    getattr(final, "model", "?"),
                    getattr(final, "reasoning_tokens", 0),
                )
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
