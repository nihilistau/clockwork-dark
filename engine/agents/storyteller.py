"""
Storyteller Agent
=================

GM agent — narrates world, dispatches required skills, passes Evaluator gate.

This is the ONLY production narration path, and until now it never sent a
``response_format``: ``engine/lmstudio/schemas.py`` built a full turn schema
that nothing on this path ever used, and the ``lmstudio.structured_output``
config key was read nowhere at all. ``_infer`` now goes through
``engine.lmstudio.backend``, which applies the configured structured-output
mode, picks the transport that can serve the request, and reports a reasoning-
starved generation as its own failure instead of as an empty string.

NARRATION THAT STOPS DEAD
-------------------------
Three separate paths used to put a severed sentence in front of the player, and
only one of them was detected:

1. A generation cut at ``max_tokens`` with SOME content produced
   ``finish_reason: "length"`` and was merely logged. ``starved_by_reasoning``
   only ever caught the case where content was EMPTY, so a partial cut sailed
   through as if the model had finished.
2. A cut mid-JSON left ``parse_storyteller_response`` with an object that never
   closed. ``extract_json`` returned None and the function handed back
   ``narration: ""`` -- while the player had already watched the first half of
   that narration stream onto the screen. The turn then "failed evaluation" for
   having no narration, which is not what happened.
3. The evaluator retry does not stream (replaying text the player already
   watched would be worse), so the accepted narration only ever reached the
   client inside ``turn_update``. The client trusted its own delta buffer and
   ignored it, leaving the rejected half-streamed draft on screen permanently.

``_infer`` now reports whether the generation actually finished,
``parse_storyteller_response`` salvages the narration prefix out of an
unterminated envelope, and everything the player is shown is trimmed to a
sentence boundary on the way out.

Version: v0.3.0 [2026-08-08]
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from engine.agents.cast import absent_cast
from engine.agents.continuity import known_cast
from engine.agents.evaluator import EvaluationResult, StorytellerEvaluator
from engine.agents.json_stream import NarrationStreamer, extract_json
from engine.agents.prompts import evaluator_retry_prompt, storyteller_system_prompt
from engine.agents.tag_buffer import TagBuffer
from engine.game.transaction import StateTransaction
from engine.memory.context import build_storyteller_messages
from engine.memory.ledger import StoryLedger
from engine.agents.stream_processor import (
    SentenceGate,
    StreamProcessor,
    ends_mid_sentence,
    strip_trailing_debris,
    trim_to_sentence,
)
from engine.agents.tool_dispatcher import execute_tool_calls
from engine.game.engine import GameEngine
from engine.game.plot import PlotFormula
from engine.lmstudio.schemas import NARRATION_MAX_CHARS
from engine.lore.interceptors import AwarenessGateInterceptor
from engine.lore.manager import get_lore_manager
from engine.media.pipeline import MediaPipeline

logger = logging.getLogger(__name__)

#: What a faded scene reads as when there is no model pass left to write the
#: summary at a distance. Deliberately complete-sounding and deliberately
#: silent about the fade itself: the contract (docs/SAFETY.md) is that the
#: player loses the detail, keeps the consequences, and is never told that
#: anything was skipped.
FADE_FALLBACK_LINE = (
    "The hour passes at a remove, and what it cost and what it settled stand."
)

#: The engine's own line for a turn the model never answered. Deliberately
#: placeless: it names no forest, no village, no court, because it is handed to
#: whichever story is running. A story that wants weather in this sentence
#: declares ``entry.fallback_narration`` in its manifest.
NEUTRAL_FALLBACK_NARRATION = (
    "The moment holds where it is, quiet and unhurried, waiting on you."
)


def fallback_narration() -> str:
    """
    The canned line shown when the LLM is unavailable, in the story's voice.

    Read through the registry WITHOUT activating anything -- this runs inside a
    failing turn, and repointing config plus a dozen cache resets is the last
    thing a failing turn should trigger. The canned line used to be a literal
    here ("The forest holds its breath..."), which put the flagship's forest
    into every story's outage.
    """
    try:
        from engine.games.registry import entry_manifest

        manifest = entry_manifest()
        if manifest is not None and manifest.fallback_narration:
            return manifest.fallback_narration
    except Exception as exc:  # noqa: BLE001 -- a failing turn must still speak
        logger.debug(
            "[storyteller] No declared fallback narration "
            "(operation=fallback_narration): %s",
            exc,
        )
    return NEUTRAL_FALLBACK_NARRATION


@dataclass
class Generation:
    """
    One call to the model, plus whether it actually got to the end.

    ``_infer`` used to return a bare string, which made "the model finished"
    and "the model was cut off at max_tokens" the same value. Every decision
    downstream -- retry, trim, what to tell the client -- needs to tell those
    apart.
    """

    raw: str = ""
    # False when finish_reason was "length", the stream errored, or the model
    # produced nothing at all.
    complete: bool = True
    finish_reason: str = ""
    output_tokens: int = 0
    reasoning_tokens: int = 0
    # Text withheld from the player because the stream stopped mid-sentence.
    dropped_tail: str = ""

    @property
    def truncated(self) -> bool:
        return self.finish_reason == "length"

    def __str__(self) -> str:  # pragma: no cover - convenience only
        return self.raw


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
    # Rule breaches found by the governance POST chain (R001-R005). Empty on a
    # clean turn, which is the overwhelmingly common case.
    governance: list[dict[str, Any]] = field(default_factory=list)
    # False when the accepted narration came from a generation that was cut
    # short (max_tokens, a broken stream, an unterminated JSON envelope) and
    # had its unfinished tail trimmed away. Carried so the client and the
    # telemetry oracle can tell a deliberate ending from a survived one.
    narration_complete: bool = True
    # finish_reason of the generation that produced the accepted narration.
    finish_reason: str = ""
    # The narration review's verdict (engine/safety), serialised, when it had
    # anything to say. Empty for an ALLOW and always empty for an inert policy
    # -- of the shipped games, only the flagship. Wicked-garden, neon-city and
    # dev-story resolve non-inert, so this key can and does appear for them.
    safety: dict[str, Any] = field(default_factory=dict)
    # The player-facing summary card when the review FADED the scene. The
    # client renders it (a later phase); mechanically everything already
    # applied, because a fade is a change of camera, not of world.
    fade_card: Optional[dict[str, Any]] = None

    def to_dict(self) -> dict[str, Any]:
        out = {
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
            "governance": self.governance,
            "narration_complete": self.narration_complete,
            "finish_reason": self.finish_reason,
        }
        # Same rule as the turn payload: an inert policy adds no key at all.
        if self.safety:
            out["safety"] = self.safety
        if self.fade_card:
            out["fade_card"] = self.fade_card
        return out


# The model writing the whole turn object a second time, escaped, INSIDE the
# narration string. Grammar-legal -- a JSON string may contain anything -- so
# structured output does not prevent it, and the player is shown
# `..., "choices": [{"id": "a", "text": ...` as if it were prose. Measured once
# in 21 live turns on nemotron-3-nano-4b.
_EMBEDDED_ENVELOPE = re.compile(
    r'["\'”’]?\s*,\s*"'
    r"(?:choices|npc_voices|ledger_delta|mood|image_tag|tags_inline|narration"
    r"|tool_calls|stat_changes|items_gained|items_lost|skill_check)"
    r'"\s*:'
)


def _positional_ids(choices: Any) -> list[dict[str, str]]:
    """
    Renumber choices a, b, c... in the order they were offered.

    The turn schema declares choice ids as an enum of a|b|c|d, and a model is
    free to pick from the middle of it -- observed live on
    gemma-4-26b-a4b-it-qat, which returned two choices with ids "c" and "d".
    Nothing broke, because the client keys its 1-4 shortcuts off position, but
    the ids are what ``resolve_player_action`` matches and what the API returns,
    so a turn advertised options the player could not name.

    Assigned by the ENGINE rather than requested from the model, for the same
    reason the negotiator does it: position is what the keyboard uses, so the
    id has to follow the order rather than the sampler's mood.
    """
    if not isinstance(choices, list):
        return []
    out: list[dict[str, str]] = []
    for choice in choices:
        if not isinstance(choice, dict):
            continue
        text = str(choice.get("text") or "").strip()
        if not text:
            continue
        row = {k: v for k, v in choice.items() if k != "id"}
        # Numbered over what SURVIVES, not over the input. Counting the input
        # would leave a gap wherever a malformed choice was dropped -- a "b"
        # with no "a", which is worse than the ids it replaced.
        row["id"] = chr(ord("a") + len(out)) if len(out) < 26 else str(len(out))
        row["text"] = text
        out.append(row)
    return out


def strip_embedded_envelope(narration: str) -> str:
    """
    Cut the narration where it stops being prose and starts being JSON.

    Returns the text unchanged when no envelope is embedded, which is the
    overwhelmingly common case.
    """
    match = _EMBEDDED_ENVELOPE.search(narration)
    if not match:
        return narration
    return narration[: match.start()]


def salvage_narration(raw: str) -> str:
    """
    Recover the narration string from a JSON object that never closed.

    A generation cut at ``max_tokens`` mid-envelope is unparseable, and the old
    behaviour was to return an empty narration -- despite the player having
    already watched most of that narration arrive as deltas. The incremental
    decoder can read exactly as much of the string as was actually written, so
    the prose is recoverable even though the object is not.

    Args:
        raw: Partial model output, expected to contain ``"narration": "..."``.

    Returns:
        The decoded narration text (possibly unfinished), or "" if the key
        never arrived.
    """
    if '"narration"' not in raw:
        return ""
    streamer = NarrationStreamer()
    streamer.push(raw)
    return streamer.text


def parse_storyteller_response(raw: str) -> dict[str, Any]:
    """
    Extract the JSON turn object from Storyteller output.

    Uses a brace-counting scanner rather than a regex. The old fallback was

        _JSON_LOOSE = r"(\\{[^{}]*\"narration\"[^{}]*\\})"

    whose ``[^{}]*`` forbids nested braces -- but the mandated payload always
    contains ``"choices": [{...}]``. So the fallback could never match, and
    whenever the model omitted the code fence (the single most common local
    model deviation) the player was shown the raw JSON as narration.

    When the object is unparseable because it was CUT SHORT rather than
    malformed, the narration string is salvaged out of the fragment instead of
    being thrown away. That is the difference between "the model wrote nothing"
    and "the model was interrupted", and only the second one is true.

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

    # Unparseable. Before falling back, try to read the narration out of a
    # fragment that was simply cut short -- the common case by far, and the one
    # that used to blank the screen after the player had already read half of
    # it.
    salvaged = salvage_narration(raw)
    if salvaged.strip():
        logger.warning(
            "[storyteller] JSON envelope never closed; salvaged the narration "
            "(operation=parse_storyteller_response, raw_chars=%s, "
            "narration_chars=%s, mid_sentence=%s)",
            len(raw),
            len(salvaged),
            ends_mid_sentence(salvaged),
        )
        return {
            "narration": salvaged,
            # Generic, but never empty: a zero-choice turn is a soft-lock, and
            # a cut-short generation is exactly when one would happen. The
            # retry in run_turn is driven by `salvaged`, not by the evaluator
            # noticing the choices are dull.
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
            "salvaged": True,
        }

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
        lms_client: Optional backend override (anything with chat_stream/chat).
        on_reasoning: Optional sink for the model's reasoning channel, so the
            UI can show "the world is deciding..." during a slow local turn.
    """

    #: The historical canon id (CLAUDE.md: do not rename), kept as the LEGACY
    #: SHIM: it is the answer only for a story that ships no agents.yaml at
    #: all. A story with a roster names its own narrator -- the flagship's
    #: declares this same id, which is how the canon name survives without
    #: living in engine code.
    LEGACY_AGENT_ID = "clockwork_storyteller"
    MAX_RETRIES = 1

    @property
    def AGENT_ID(self) -> str:
        """The active story's world-role agent id, or the historical canon id."""
        from engine.agents.roster import ROLE_WORLD, agent_id_for_role

        return agent_id_for_role(ROLE_WORLD, self.LEGACY_AGENT_ID)

    def __init__(
        self,
        engine: GameEngine,
        *,
        llm_fn: Optional[Callable[[list[dict[str, Any]]], str]] = None,
        lms_client: Any = None,
        ledger: Optional[StoryLedger] = None,
        on_reasoning: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.engine = engine
        self.llm_fn = llm_fn
        self._client = lms_client
        self.on_reasoning = on_reasoning
        self._evaluator = StorytellerEvaluator()
        self._media = MediaPipeline()
        # Narrative memory. Owned by the session; the agent holds a reference so
        # every prompt it builds carries what the world already knows.
        self.ledger: StoryLedger = ledger if ledger is not None else StoryLedger()
        self._lore_chunks: list[Any] = []
        self._llm_failed = False
        # Populated per turn from the last generation, for diagnostics and for
        # the UI's reasoning channel.
        self.last_reasoning: str = ""

    def _infer(
        self,
        messages: list[dict[str, Any]],
        *,
        on_delta: Optional[Callable[[str], None]] = None,
    ) -> Generation:
        """
        Call the LLM, streaming narration to on_delta when one is supplied.

        Narration is decoded out of the JSON object as it arrives (it is the
        first property in the schema) and passed through two gates before it
        reaches the player:

        * :class:`TagBuffer` holds back text that might still turn out to be a
          ``[IMAGE:...]`` split across chunks.
        * :class:`SentenceGate` holds back text that is not yet a well-formed
          prefix, and -- when the generation is cut short -- drops the severed
          tail rather than presenting it as prose.

        Returns:
            A :class:`Generation` carrying the raw text and whether the model
            reached its own ending.
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
            return Generation(raw=raw, complete=True, finish_reason="stop")

        from engine.game.intents import legal_intents
        from engine.lmstudio.backend import get_backend
        from engine.lmstudio.schemas import storyteller_turn_schema
        from engine.memory.context import present_npc_ids

        backend = self._client or get_backend()
        # The schema this path built and then never sent. `structured_output`
        # decides whether it actually goes on the wire.
        #
        # `intents` is what lets a choice carry a mechanic. Built from the LIVE
        # state on every attempt, so a retry after the world moved cannot offer
        # a road that has since closed.
        schema = storyteller_turn_schema(
            npc_ids=present_npc_ids(self.engine.state),
            intents=legal_intents(self.engine.state),
        )
        response_format = backend.structured_output(schema)

        self.last_reasoning = ""

        def _reasoning(delta: str) -> None:
            # Reasoning is captured and forwarded, and deliberately never fed
            # to the narration decoder or the tag buffer: a model musing
            # "maybe [IMAGE:forest]" must not fire a real image generation.
            self.last_reasoning += delta
            if self.on_reasoning:
                self.on_reasoning(delta)

        if on_delta is None:
            result = backend.chat(
                messages,
                profile="big",
                response_format=response_format,
                label="storyteller",
            )
            self.last_reasoning = result.reasoning_content
            self._warn_if_starved(result)
            self._warn_if_truncated(result)
            return self._generation(result, result.content)

        streamer = NarrationStreamer()
        buffer = TagBuffer()
        gate = SentenceGate()
        parts: list[str] = []
        # Set when the narration string turns into a second copy of the turn
        # envelope. Everything after that point is machinery, not prose, and
        # must stop reaching the screen immediately -- not at the end of the
        # turn when the authoritative text replaces it.
        derailed = False

        def _forward(delta: str) -> None:
            nonlocal derailed
            parts.append(delta)
            text = streamer.push(delta)
            if derailed or not text:
                return
            # Scan a bounded tail, not the whole buffer: this runs on every
            # delta, and the O(n^2) rescan is the exact shape of the bug the
            # tag scanner already carries.
            window = streamer.text[-max(160, len(text) + 80) :]
            if _EMBEDDED_ENVELOPE.search(window):
                derailed = True
                logger.warning(
                    "[storyteller] Narration ran into an embedded JSON envelope; "
                    "stopped forwarding (operation=_infer, chars=%s)",
                    len(streamer.text),
                )
                return
            safe = buffer.push(text)
            if safe:
                paced = gate.push(safe)
                if paced:
                    on_delta(paced)

        generator = backend.chat_stream(
            messages,
            profile="big",
            response_format=response_format,
            on_delta=_forward,
            on_reasoning=_reasoning,
        )
        result = None
        error = ""
        try:
            while True:
                next(generator)
        except StopIteration as stop:
            result = stop.value
        except Exception as exc:  # noqa: BLE001 -- surfaced as an incomplete turn
            error = f"{type(exc).__name__}: {exc}"
            logger.warning(
                "[storyteller] Narration stream broke off "
                "(operation=_infer, chars=%s): %s",
                sum(len(p) for p in parts),
                exc,
            )

        # A generation that reached its own ending may show its tail verbatim.
        # One that was cut short must not: the severed clause is dropped, and
        # the authoritative narration in `turn_update` replaces what is on
        # screen with a version that ends properly.
        complete = bool(
            result is not None and not result.truncated and not error and not derailed
        )
        held = buffer.flush()
        if held:
            tail = gate.push(held)
            if tail:
                on_delta(tail)
        closing = gate.flush(complete=complete)
        if closing:
            on_delta(closing)
        if gate.dropped:
            logger.info(
                "[storyteller] Held back %s chars of unfinished narration "
                "(operation=_infer, complete=%s, tail=%r)",
                len(gate.dropped),
                complete,
                gate.dropped[-60:],
            )

        raw = "".join(parts)
        if result is not None:
            self._warn_if_starved(result)
            self._warn_if_truncated(result)
            # A starved stream produced no content at all. Recover with one
            # non-streaming, reasoning-off attempt rather than handing the
            # evaluator an empty string and calling it a bad narration.
            if result.starved_by_reasoning:
                recovered = backend.chat(
                    messages,
                    profile="big",
                    reasoning="off",
                    response_format=response_format,
                    label="storyteller:recover",
                    retry_on_starvation=False,
                )
                if recovered.content.strip():
                    logger.info(
                        "[storyteller] Recovered narration with reasoning off "
                        "(operation=_infer, chars=%s)",
                        len(recovered.content),
                    )
                    return self._generation(recovered, recovered.content)
            generation = self._generation(result, raw, dropped=gate.dropped)
            if derailed:
                generation.complete = False
            return generation

        return Generation(
            raw=raw,
            complete=False,
            finish_reason="error" if error else "",
            dropped_tail=gate.dropped,
        )

    @staticmethod
    def _generation(result: Any, raw: str, *, dropped: str = "") -> Generation:
        """Wrap an LMSResponse and the text actually collected."""
        return Generation(
            raw=raw,
            complete=not getattr(result, "truncated", False),
            finish_reason=str(getattr(result, "finish_reason", "") or ""),
            output_tokens=int(getattr(result, "output_tokens", 0) or 0),
            reasoning_tokens=int(getattr(result, "reasoning_tokens", 0) or 0),
            dropped_tail=dropped,
        )

    @staticmethod
    def _warn_if_truncated(result: Any) -> None:
        """
        Name the PARTIAL cut, which nothing used to detect.

        ``starved_by_reasoning`` is the empty-content case and was the only one
        with a failure class. A generation that wrote 900 characters and was
        then guillotined at ``max_tokens`` is the case the player actually
        complains about, and it looked identical to a clean stop.
        """
        if getattr(result, "truncated_mid_content", False):
            logger.warning(
                "[storyteller] Narration was CUT OFF at max_tokens with content "
                "already written -- the last sentence is severed "
                "(operation=_infer, model=%s, chars=%s, output_tokens=%s, "
                "reasoning_tokens=%s)",
                getattr(result, "model", "?"),
                len(getattr(result, "content", "") or ""),
                getattr(result, "output_tokens", 0),
                getattr(result, "reasoning_tokens", 0),
            )

    @staticmethod
    def _warn_if_starved(result: Any) -> None:
        """Name the empty-content failure instead of letting it look like prose."""
        if getattr(result, "starved_by_reasoning", False):
            logger.error(
                "[storyteller] Narration came back EMPTY because the model spent "
                "its whole token budget reasoning (operation=_infer, model=%s, "
                "reasoning_tokens=%s, output_tokens=%s)",
                getattr(result, "model", "?"),
                getattr(result, "reasoning_tokens", 0),
                getattr(result, "output_tokens", 0),
            )

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
        agreed_block: str = "",
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
            agreed_block=agreed_block,
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
        agreed_block: str = "",
        intent_receipts: Optional[list[dict[str, Any]]] = None,
    ) -> StorytellerTurnResult:
        """
        Execute one Storyteller turn with tools and evaluator retry.

        Args:
            player_action: Player choice or free-text action.
            on_delta: Called with narration text as it streams. This is what
                puts words on screen during generation instead of after it.
            intent_receipts: What the engine already resolved for this turn --
                the structured intent the player's chosen option declared, run
                before a word was written. These go into the MECHANICAL
                RESULTS block of the FIRST prompt, not just a retry's, which is
                the whole point: the narrator is told the outcome and asked to
                render it, so "never invent a dice result" is achievable rather
                than merely demanded. Empty when the choice carried no
                mechanic, which is the ordinary case for pure conversation.
            agreed_block: What the multi-agent negotiation already settled, if
                this story runs one. The narrator REPORTS this rather than
                re-deciding it -- the point of planning before narrating is
                that the argument is over by the time the prose starts. Empty
                for a single-agent story such as the flagship; The Wicked
                Garden declares two agents and passes the agreed turn here.

        Returns:
            StorytellerTurnResult with narration and evaluation.
        """
        retries = 0
        retry_notes: list[str] = []
        # Per-TURN, not per-agent. This used to be set once in __init__ and
        # raised on the first backend failure, and the agent is session-scoped:
        # one transient LM Studio hiccup pinned "The Storyteller is unreachable"
        # on screen for the rest of the run, while prose streamed in fine behind
        # the banner. It reports what happened on THIS turn or it reports
        # nothing useful.
        self._llm_failed = False
        raw = ""
        rejected_draft = ""
        parsed: dict[str, Any] = {}
        # Already applied to the world before this method was entered. They are
        # carried through every retry unchanged and are NOT inside the
        # transaction below: a rejected draft must not un-walk a walk the
        # player actually took.
        resolved: list[dict[str, Any]] = list(intent_receipts or [])

        # PHASE A -- mechanics, and it must happen HERE: before the transaction
        # below exists. A skill called inside that boundary is undone by an
        # evaluator retry, and LM Studio -- which ran the tool loop and already
        # holds the receipt -- would never learn the roll was rolled back. Out
        # here a Phase A receipt is exactly as durable as a resolved intent,
        # which is the rule the `resolved` list above already follows.
        #
        # Returns [] when `lmstudio.mcp.enabled` is false (the default), when
        # the server or LM Studio is unavailable, or when the model called
        # nothing -- so the turn below is untouched in every one of those cases.
        # See engine/agents/mechanics.py.
        from engine.agents.mechanics import run_mechanics_phase

        # The registry's agent id, not this story's narrator id: skill
        # allowlists are declared against the ROLE ("storyteller"), which is why
        # execute_tool_calls below takes the same default.
        resolved += run_mechanics_phase(self.engine, player_action)

        tool_receipts: list[dict[str, Any]] = list(resolved)
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

        # R004 needs the pre-turn value to prove evil_progress never fell. Read
        # here, before the transaction can be rolled back and replayed, so a
        # retry compares against the turn's true starting point rather than
        # against a partially applied draft. A story with no doom clock skips
        # the measurement entirely -- None makes the R004 governor stand down
        # rather than audit a number the story does not keep.
        from engine.game.evil_ticker import doom_enabled

        evil_before: Optional[float] = (
            float(self.engine.state.evil_progress) if doom_enabled() else None
        )

        while retries <= self.MAX_RETRIES:
            if retries:
                tx.rollback()

            messages = self._build_messages(
                player_action,
                retry_notes=retry_notes if retries else None,
                # The engine's own resolutions go in on the FIRST attempt.
                # `receipts=... if retries else None` was correct while the
                # only receipts were the model's own tool calls, which by
                # definition did not exist yet -- but the intent the player
                # chose was resolved before this loop started, and withholding
                # it would leave the narrator guessing at an outcome it is
                # forbidden to invent.
                receipts=tool_receipts if (retries or resolved) else None,
                rejected_draft=rejected_draft,
                agreed_block=agreed_block,
            )
            try:
                # Only stream the first attempt: a retry would replay text the
                # player has already watched appear. The retry's narration
                # still reaches them -- `turn_update` carries the authoritative
                # text and the client replaces the streamed entry with it.
                generation = self._infer(
                    messages, on_delta=on_delta if not retries else None
                )
            except Exception as exc:
                logger.warning(
                    "[storyteller] LLM unavailable (operation=run_turn): %s", exc
                )
                generation = Generation(raw=fallback_narration(), complete=True)
                self._llm_failed = True

            raw = generation.raw
            parsed = parse_storyteller_response(raw)
            tool_receipts = resolved + execute_tool_calls(
                parsed.get("tool_calls", []),
                self.engine,
            )

            # Never hand the player a severed sentence, and never hand them the
            # machinery. A generation that was cut short gets its unfinished
            # tail dropped; one that ended on its own is untouched apart from
            # markdown debris and any envelope it wrote inside its own prose.
            narration = parsed.get("narration", raw)
            cleaned = strip_embedded_envelope(narration)
            if cleaned != narration:
                logger.warning(
                    "[storyteller] Narration contained an embedded JSON envelope; "
                    "cut it (operation=run_turn, before=%s, after=%s)",
                    len(narration),
                    len(cleaned),
                )
                narration = cleaned
                parsed["narration"] = cleaned

            # Fence debris is stripped unconditionally. It survives every
            # truncation check by construction: the sentence before it is
            # complete, so `ends_mid_sentence` is False and nothing else looks.
            debris_free = strip_trailing_debris(narration)
            if debris_free != narration:
                narration = debris_free
                parsed["narration"] = debris_free

            # A narration that lands exactly on the schema's maxLength was cut
            # by the GRAMMAR, not by the model: the sampler was forced to emit
            # the closing quote mid-word. finish_reason is a clean "stop", so
            # this is the one truncation no token-level check can ever see.
            # Measured once in 21 live turns (a degeneration into backticks
            # that ran the string to its ceiling).
            if len(narration) >= NARRATION_MAX_CHARS:
                logger.warning(
                    "[storyteller] Narration hit the schema ceiling and was cut "
                    "by the grammar (operation=run_turn, max_chars=%s)",
                    NARRATION_MAX_CHARS,
                )
                generation.complete = False

            if narration and (
                not generation.complete
                or parsed.get("salvaged")
                or ends_mid_sentence(narration)
            ):
                trimmed = trim_to_sentence(narration)
                if trimmed != narration:
                    logger.info(
                        "[storyteller] Trimmed an unfinished trailing fragment "
                        "(operation=run_turn, before=%s, after=%s, complete=%s)",
                        len(narration),
                        len(trimmed),
                        generation.complete,
                    )
                    narration = trimmed
                    parsed["narration"] = trimmed

            tags_inline = parsed.get("tags_inline", "")
            tag_result = StreamProcessor.extract_tags(tags_inline or narration)
            processed_tags = tag_result.all_tags

            evaluation = self._evaluator.evaluate(
                narration,
                parsed,
                tool_receipts=tool_receipts,
                lore_snippets=[c.text for c in self._lore_chunks],
                # Read AFTER the tools ran: a turn that travelled has a
                # different room, and the cast has to be the one the prose
                # describes rather than the one it started in.
                absent_cast=absent_cast(self.engine.state, self.ledger),
                # Read from the SAME post-tool state, and for the same reason:
                # who the player knows is a fact about where they are standing
                # now. The dossier for each of these is already in the prompt,
                # so this gate asks whether the prompt was believed.
                known_cast=known_cast(self.engine.state, self.ledger),
                player_action=player_action,
            )

            # A cut-short generation is retried even when the evaluator is
            # happy with what survived. The evaluator scores prose; it cannot
            # tell a deliberate ending from a guillotine, and the trimmed text
            # is by definition missing its last beat.
            incomplete = not generation.complete or bool(parsed.get("salvaged"))
            if evaluation.passed and not incomplete:
                break
            if incomplete and retries < self.MAX_RETRIES:
                logger.info(
                    "[storyteller] Retrying a cut-short generation "
                    "(operation=run_turn, finish_reason=%s, salvaged=%s)",
                    generation.finish_reason,
                    bool(parsed.get("salvaged")),
                )
            elif evaluation.passed:
                # Out of retries but the surviving prose is good. Keep it
                # rather than spending another generation the player waits for.
                break

            retry_notes = evaluation.notes or [
                "Your previous reply was cut off before it finished. "
                "Write a shorter, complete narration that ends on a full stop."
            ]
            rejected_draft = raw
            retries += 1

        # The last safety surface (docs/SAFETY.md attach point 4): review what
        # was actually WRITTEN, before it reaches the player. The earlier
        # surfaces read intent; this one reads what the model did with it.
        # An inert policy takes the short-circuit: no review, no RNG drawn, no
        # new payload keys, and the turn is byte-for-byte the turn it had. Of
        # the four shipped games only the flagship still gets that; the review
        # below runs for real on wicked-garden, neon-city and dev-story, which
        # is where its RNG draws and payload keys actually land. Runs BEFORE the
        # commit so a hard-no verdict can still make "this did not happen" true.
        safety_dict: dict[str, Any] = {}
        fade_card_dict: Optional[dict[str, Any]] = None
        try:
            # Imported here for the same reason governance is below: keeping
            # the seam lazy keeps a story that never configures it from paying
            # for the import, and a broken gate must cost the review, never
            # the turn.
            from engine.safety import SafetyGate
            from engine.safety.verdict import Disposition

            gate = SafetyGate.for_state(self.engine.state)
        except Exception as exc:  # noqa: BLE001 -- see the comment above
            logger.warning(
                "[storyteller] Safety gate unavailable (operation=run_turn): %s",
                exc,
            )
            gate = None

        if gate is not None and not gate.inert:
            reviewed = str(parsed.get("narration", raw) or "")
            verdict = gate.review_narration(reviewed)
            if verdict.blocked:
                # A hard no reached the prose. The thing did not happen: the
                # draft's effects roll back with the draft, and the player is
                # handed the in-fiction interruption -- never the content, and
                # never a refusal string.
                tx.rollback()
                # The DRAFT's effects go with the draft. What the player's own
                # chosen intent already resolved does not: it was applied
                # before this method was entered and before any prose existed,
                # so it is outside the transaction by construction, and
                # dropping its receipt would leave the payload claiming a move
                # the state has already taken.
                tool_receipts = list(resolved)
                parsed["narration"] = verdict.fallback
                safety_dict = verdict.to_dict()
                logger.info(
                    "[storyteller] Narration redirected by the safety gate "
                    "(operation=run_turn, reasons=%s)",
                    list(verdict.reasons),
                )
            elif verdict.disposition is Disposition.FADE:
                # Above the session's tier. The scene HAPPENED -- every
                # mechanical outcome keeps, which is why nothing here touches
                # the transaction -- but the player is not shown the detail.
                outcomes = tuple(
                    line
                    for line in (
                        str((r.get("result") or {}).get("text") or "").strip()
                        for r in tool_receipts
                        if isinstance(r, dict)
                    )
                    if line
                )
                card = gate.fade_card(
                    verdict, summary=FADE_FALLBACK_LINE, outcomes=outcomes
                )
                parsed["narration"] = FADE_FALLBACK_LINE
                safety_dict = verdict.to_dict()
                fade_card_dict = card.to_dict() if card is not None else None
            elif verdict.disposition is Disposition.SUBSTITUTE:
                # Same scene, renamed nouns. Mechanics untouched by design --
                # rename is a pure string function and cannot be handed an id.
                parsed["narration"] = gate.rename(reviewed)
                safety_dict = verdict.to_dict()

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

        # Audit the committed turn. This is the call that makes SceneRulesEngine
        # (R001-R005) real -- it has enforced nothing since it was written
        # because nothing invoked it. Runs after the commit so it judges the
        # state the player actually ends the turn in, and never raises: a
        # governor that could kill a turn would trade an audit for an outage.
        #
        # Imported here, not at module scope: engine.agents.governance registers
        # the legacy lore interceptors at import time, and engine.agents.__init__
        # eagerly imports this class. A top-level import would close that loop.
        from engine.agents.governance import TurnContext, get_governance

        governance_ctx = get_governance().run_post(
            TurnContext(
                state=self.engine.state,
                player_action=player_action,
                parsed=parsed,
                narration=parsed.get("narration", raw),
                tool_receipts=tool_receipts,
                metadata={"evil_before": evil_before},
            )
        )

        return StorytellerTurnResult(
            narration=parsed.get("narration", raw),
            choices=_positional_ids(parsed.get("choices", [])),
            parsed=parsed,
            tool_receipts=tool_receipts,
            evaluation=evaluation,
            tags_inline=parsed.get("tags_inline", ""),
            processed_tags=processed_tags,
            media=media_result.to_dict(),
            retries=retries,
            raw_llm=raw,
            llm_unavailable=self._llm_failed,
            governance=governance_ctx.violations,
            narration_complete=bool(
                generation.complete and not parsed.get("salvaged")
            ),
            finish_reason=generation.finish_reason,
            safety=safety_dict,
            fade_card=fade_card_dict,
        )