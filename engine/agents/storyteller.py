"""
Storyteller Agent
=================

GM agent — narrates world, dispatches required skills, passes Evaluator gate.

Version: v0.1.0 [2026-06-20]
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from engine.agents.evaluator import EvaluationResult, StorytellerEvaluator
from engine.agents.json_stream import NarrationStreamer, extract_json
from engine.agents.prompts import evaluator_retry_prompt, storyteller_system_prompt
from engine.agents.tag_buffer import TagBuffer
from engine.game.transaction import StateTransaction
from engine.lmstudio.gate import inference_slot
from engine.memory.context import build_storyteller_messages
from engine.memory.ledger import StoryLedger
from engine.agents.stream_processor import StreamProcessor
from engine.agents.tool_dispatcher import execute_tool_calls
from engine.game.engine import GameEngine
from engine.game.plot import PlotFormula
from engine.lmstudio.speculative import speculative_stream
from engine.lore.interceptors import AwarenessGateInterceptor
from engine.lore.manager import get_lore_manager
from engine.media.pipeline import MediaPipeline

logger = logging.getLogger(__name__)



@dataclass
class StorytellerTurnResult:
    """Result of one Storyteller turn."""

    narration: str
    choices: list[dict[str, str]]
    parsed: dict[str, Any]
    tool_receipts: list[dict[str, Any]]
    evaluation: EvaluationResult
    tags_inline: str = ""
    processed_tags: dict[str, list[str]] = field(default_factory=dict)
    media: dict[str, Any] = field(default_factory=dict)
    retries: int = 0
    raw_llm: str = ""
    # Whether the fallback narration was used because the model was
    # unreachable. Previously the canned line was emitted with no signal
    # anywhere in the payload, so a dead LLM looked like a very boring game.
    llm_unavailable: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "narration": self.narration,
            "choices": self.choices,
            "parsed": self.parsed,
            "tool_receipts": self.tool_receipts,
            "evaluation": self.evaluation.to_dict(),
            "tags_inline": self.tags_inline,
            "processed_tags": self.processed_tags,
            "media": self.media,
            "retries": self.retries,
            "llm_unavailable": self.llm_unavailable,
        }


def parse_storyteller_response(raw: str) -> dict[str, Any]:
    """
    Extract the JSON turn object from Storyteller output.

    Uses a brace-counting scanner rather than a regex. The old fallback was

        _JSON_LOOSE = r"(\\{[^{}]*\"narration\"[^{}]*\\})"

    whose ``[^{}]*`` forbids nested braces -- but the mandated payload always
    contains ``"choices": [{...}]``. So the fallback could never match, and
    whenever the model omitted the code fence (the single most common local
    model deviation) the player was shown the raw JSON as narration.

    Args:
        raw: Full LLM response text.

    Returns:
        Parsed dict with narration, choices, tool_calls, etc.
    """
    data = extract_json(raw)

    if isinstance(data, dict) and "narration" in data:
        prose = raw.split("```")[0].strip()
        # Only fall back to the prose body if it is not itself the JSON.
        if not prose.lstrip().startswith("{"):
            data.setdefault("narration", prose)
        data.setdefault("narration", "")
        data.setdefault("choices", [])
        data.setdefault("tool_calls", [])
        data.setdefault("npc_voices", [])
        data.setdefault("ledger_delta", {})
        data.setdefault("stat_changes", {})
        data.setdefault("items_gained", [])
        data.setdefault("items_lost", [])
        data.setdefault("skill_check", None)
        data.setdefault("tags_inline", "")
        return data

    # Genuinely unparseable: show the prose, never the machinery.
    narration = raw.strip()
    if narration.lstrip().startswith("{"):
        logger.warning(
            "[storyteller] Unparseable JSON response "
            "(operation=parse_storyteller_response, chars=%s)",
            len(raw),
        )
        narration = ""

    return {
        "narration": narration,
        "choices": [
            {"id": "a", "text": "Look around"},
            {"id": "b", "text": "Continue"},
        ],
        "tool_calls": [],
        "npc_voices": [],
        "ledger_delta": {},
        "stat_changes": {},
        "items_gained": [],
        "items_lost": [],
        "skill_check": None,
        "tags_inline": "",
        "parse_failed": True,
    }


class StorytellerAgent:
    """
    Orchestrates Storyteller inference, tool execution, and evaluation.

    Args:
        engine: Game engine bound to session state.
        llm_fn: Optional mock/injectable LLM callable(messages) -> str.
        use_speculative: Use draft→refine if True and client available.
    """

    AGENT_ID = "clockwork_storyteller"
    MAX_RETRIES = 1

    def __init__(
        self,
        engine: GameEngine,
        *,
        llm_fn: Optional[Callable[[list[dict[str, Any]]], str]] = None,
        use_speculative: bool = False,
        lms_client: Any = None,
        ledger: Optional[StoryLedger] = None,
    ) -> None:
        self.engine = engine
        self.llm_fn = llm_fn
        self.use_speculative = use_speculative
        self._client = lms_client
        self._evaluator = StorytellerEvaluator()
        self._media = MediaPipeline()
        # Narrative memory. Owned by the session; the agent holds a reference so
        # every prompt it builds carries what the world already knows.
        self.ledger: StoryLedger = ledger if ledger is not None else StoryLedger()
        self._lore_chunks: list[Any] = []
        self._llm_failed = False

    def _infer(
        self,
        messages: list[dict[str, Any]],
        *,
        on_delta: Optional[Callable[[str], None]] = None,
    ) -> str:
        """
        Call the LLM, streaming narration to on_delta when one is supplied.

        Narration is decoded out of the JSON object as it arrives (it is the
        first property in the schema) and passed through a tag buffer, so
        ``[IMAGE:...]`` split across chunks never reaches the player's log.
        """
        if self.llm_fn is not None:
            raw = self.llm_fn(messages)
            if on_delta is not None and raw:
                # Injected callables return the whole response at once; replay
                # it through the same path so tests exercise the real decoder.
                streamer = NarrationStreamer()
                buffer = TagBuffer()
                text = buffer.push(streamer.push(raw)) + buffer.flush()
                if text:
                    on_delta(text)
            return raw

        from engine.lmstudio.client import get_lms_client
        from engine.lmstudio.profiles import resolve_profile

        client = self._client or get_lms_client()
        profile = resolve_profile("big")

        if on_delta is None:
            with inference_slot(label="storyteller"):
                return client.chat(
                    messages,
                    model=profile.model,
                    temperature=profile.temperature,
                    max_tokens=profile.max_tokens,
                ).content

        streamer = NarrationStreamer()
        buffer = TagBuffer()
        parts: list[str] = []

        def _forward(delta: str) -> None:
            parts.append(delta)
            text = streamer.push(delta)
            if text:
                safe = buffer.push(text)
                if safe:
                    on_delta(safe)

        with inference_slot(label="storyteller"):
            generator = client.chat_stream(
                messages,
                model=profile.model,
                temperature=profile.temperature,
                max_tokens=profile.max_tokens,
                on_delta=_forward,
            )
            try:
                while True:
                    next(generator)
            except StopIteration:
                pass

        tail = buffer.flush()
        if tail:
            on_delta(tail)
        return "".join(parts)

    def _lore_block(self, player_action: str) -> str:
        """
        Retrieve lore once per turn.

        The old code ran one query inside the interceptor and a second,
        differently-worded one for the evaluator, so the evaluator scored the
        narration against chunks the model had never seen -- and both ran again
        on every retry.
        """
        state = self.engine.state
        manager = get_lore_manager()
        if manager.count() == 0:
            return ""
        query = f"{state.location_id} {player_action} {state.archetype}"
        self._lore_chunks = manager.search(query, limit=3)
        if not self._lore_chunks:
            return ""
        lines = [f"- [{c.title}] {c.text}" for c in self._lore_chunks]
        return (
            "LORE CONTEXT (canonical — prefer this over your own invention):\n"
            + "\n".join(lines)
        )

    def _build_messages(
        self,
        player_action: str,
        *,
        retry_notes: Optional[list[str]] = None,
        receipts: Optional[list[dict[str, Any]]] = None,
        rejected_draft: str = "",
    ) -> list[dict[str, Any]]:
        state = self.engine.state
        PlotFormula.update_story_pressure(state)

        messages = build_storyteller_messages(
            state,
            self.ledger,
            player_action,
            evil_snapshot=self.engine.get_evil_snapshot(),
            lore_block=self._lore_block(player_action),
            receipts=receipts,
            retry_note=(
                evaluator_retry_prompt(retry_notes, rejected_draft)
                if retry_notes
                else ""
            ),
        )

        # ONLY the awareness gate runs here, and only over system blocks.
        #
        # Not the whole PRE chain: LoreInjectInterceptor appends its own lore
        # block, this loop visits every system message, and all of it happens
        # AFTER build_storyteller_messages has already fitted the prompt to the
        # token budget -- so lore was injected once per system block, on top of
        # the copy context.py had already budgeted, and none of those copies
        # were counted. Measured at 7,550 tokens sent against a 6,198 budget,
        # growing with play, and invisible until someone seeds the lore DB.
        # Lore belongs to context.py, which puts it inside the budget.
        gate = AwarenessGateInterceptor()
        for message in messages:
            if message["role"] == "system":
                message["content"] = gate.run_pre(
                    state, message["content"], player_action=player_action
                )
        return messages

    def run_turn(
        self,
        player_action: str,
        *,
        on_delta: Optional[Callable[[str], None]] = None,
    ) -> StorytellerTurnResult:
        """
        Execute one Storyteller turn with tools and evaluator retry.

        Args:
            player_action: Player choice or free-text action.
            on_delta: Called with narration text as it streams. This is what
                puts words on screen during generation instead of after it.

        Returns:
            StorytellerTurnResult with narration and evaluation.
        """
        retries = 0
        retry_notes: list[str] = []
        raw = ""
        rejected_draft = ""
        parsed: dict[str, Any] = {}
        tool_receipts: list[dict[str, Any]] = []
        processed_tags: dict[str, list[str]] = {}
        self._lore_chunks = []
        evaluation = EvaluationResult(
            overall=0.0,
            tone=0.0,
            lore=0.0,
            no_hallucinated_mechanics=0.0,
            length=0.0,
            valid_json=0.0,
            choices=0.0,
            passed=False,
        )

        # Snapshot before any tool runs. A draft rejected by the evaluator used
        # to keep its side effects: the player was moved and drained by a
        # narration they never saw.
        tx = StateTransaction(self.engine.state)

        while retries <= self.MAX_RETRIES:
            if retries:
                tx.rollback()

            messages = self._build_messages(
                player_action,
                retry_notes=retry_notes if retries else None,
                receipts=tool_receipts if retries else None,
                rejected_draft=rejected_draft,
            )
            try:
                # Only stream the first attempt: a retry would replay text the
                # player has already watched appear.
                raw = self._infer(messages, on_delta=on_delta if not retries else None)
            except Exception as exc:
                logger.warning(
                    "[storyteller] LLM unavailable (operation=run_turn): %s", exc
                )
                raw = (
                    "The forest holds its breath. Smoke drifts from a distant chimney."
                )
                self._llm_failed = True

            parsed = parse_storyteller_response(raw)
            tool_receipts = execute_tool_calls(
                parsed.get("tool_calls", []),
                self.engine,
            )

            narration = parsed.get("narration", raw)
            tags_inline = parsed.get("tags_inline", "")
            tag_result = StreamProcessor.extract_tags(tags_inline or narration)
            processed_tags = tag_result.all_tags

            evaluation = self._evaluator.evaluate(
                narration,
                parsed,
                tool_receipts=tool_receipts,
                lore_snippets=[c.text for c in self._lore_chunks],
            )

            if evaluation.passed:
                break

            retry_notes = evaluation.notes
            rejected_draft = raw
            retries += 1

        tx.commit()

        self.engine.state.turn_number += 1
        self.engine.state.storyteller_mind.patience = max(
            0.0,
            self.engine.state.storyteller_mind.patience - 1.0,
        )

        media_result = self._media.process_storyteller_turn(
            self.engine.state,
            narration=parsed.get("narration", raw),
            processed_tags=processed_tags,
        )

        return StorytellerTurnResult(
            narration=parsed.get("narration", raw),
            choices=parsed.get("choices", []),
            parsed=parsed,
            tool_receipts=tool_receipts,
            evaluation=evaluation,
            tags_inline=parsed.get("tags_inline", ""),
            processed_tags=processed_tags,
            media=media_result.to_dict(),
            retries=retries,
            raw_llm=raw,
            llm_unavailable=self._llm_failed,
        )