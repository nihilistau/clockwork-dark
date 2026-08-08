"""
StreamProcessor — inline tag extraction from LLM output.

Parses: [MOOD:], [IMAGE:], [CUTSCENE:], [ACTION:], [STAT:], [VOICE:]

REASONING IS NOT CONTENT
------------------------
``reasoning.*`` events are captured into ``ProcessedResponse.reasoning_content``
(declared since the first version and, until now, never once assigned) and
forwarded to ``on_reasoning`` so the UI can show a live "the world is
deciding..." channel during a slow local turn.

They are deliberately NOT passed to ``_scan_for_tags``. A model musing "maybe
[IMAGE:forest_clearing] would fit here" while thinking must not fire a real
image generation, and reasoning text must never reach the narration JSON
decoder, whose ``find``-based scan is O(n^2) over a buffer it never truncates.

SENTENCE GATE
-------------
``SentenceGate`` is the other half of "streamed narration must never cut off
mid sentence". The tag buffer decides what is safe to show because it might be
markup; the sentence gate decides what is safe to show because it might not be
finished. It releases text only at boundaries that leave a well-formed prefix
on screen, and on a stream that ended badly it DROPS the unfinished tail
instead of presenting a severed clause as prose.

Version: v0.3.0 [2026-08-08]
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

_RE_MOOD = re.compile(r"\[MOOD:([^\]]+)\]", re.IGNORECASE)
_RE_IMAGE = re.compile(r"\[(?:IMAGE|SELFIE|PHOTO):([^\]]+)\]", re.IGNORECASE)
_RE_CUTSCENE = re.compile(r"\[CUTSCENE:([^\]]+)\]", re.IGNORECASE)
_RE_ACTION = re.compile(r"\[ACTION:([^\]]+)\]", re.IGNORECASE)
_RE_STAT = re.compile(r"\[STAT:(\w+)([+-]\d+)\]", re.IGNORECASE)
_RE_VOICE = re.compile(r"\[VOICE:([^\]]+)\]", re.IGNORECASE)

_STRIP_TAGS = re.compile(
    r"\[(?:MOOD|IMAGE|SELFIE|PHOTO|CUTSCENE|ACTION|STAT|VOICE):[^\]]+\]\s*",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Sentence gating
# ---------------------------------------------------------------------------

# Characters that are never prose: markdown fence and emphasis marks, JSON
# braces and brackets, stray backslashes, whitespace. Deliberately EXCLUDES
# `.`, `,`, `"` and `'` -- those end real sentences, and a class wide enough
# to catch the debris would eat the full stop off the end of every paragraph.
_DEBRIS = r'\s`*_~#>{}\[\]\\'

# A finished sentence: terminal punctuation, optionally a closing quote or
# bracket, then whitespace, debris, or the end of the text. `"He is not
# alarmed."` and `...she says, and waits.` both end here; `Mr.Smith` does not,
# which is why something must follow the stop rather than nothing.
#
# Debris belongs in that lookahead because the model abuts it directly:
# `...holding its breath.``` has no space between the full stop and the fence,
# and without this the sentence went unrecognised and the debris stayed.
_SENTENCE_END = re.compile(rf'[.!?…]["\'’”)\]]*(?=[{_DEBRIS}]|$)')

# A clause boundary is enough to reveal text without it reading as broken --
# a comma or a dash leaves a grammatical prefix on screen. Used for PACING
# only; it is never accepted as a place to end a turn.
_CLAUSE_END = re.compile(r'[,;:–—](?=\s)|\n')

# Past this many held characters with no boundary in sight, release up to the
# last whole word anyway. A model writing one very long unpunctuated line must
# not freeze the screen; a half-written WORD is never released either way.
SOFT_HOLD_LIMIT = 180

_DEBRIS_CHAR = re.compile(rf'[{_DEBRIS}]')


def _last_sentence_end(text: str) -> int:
    """Index just past the last complete sentence in ``text``, or 0."""
    end = 0
    for match in _SENTENCE_END.finditer(text):
        end = match.end()
    return end


def _wordless(text: str) -> bool:
    """True when ``text`` contains no letter or digit -- so, no prose."""
    return not any(char.isalnum() for char in text)


def trailing_fragment(text: str) -> int:
    """
    Index at which ``text`` stops being finished sentences.

    Returns the length of the longest prefix that ends on a sentence boundary,
    so ``text[:n]`` is safe to show and ``text[n:]`` is the unfinished tail.
    Returns ``0`` when there is no complete sentence at all.
    """
    return _last_sentence_end(text) if text else 0


def strip_trailing_debris(text: str) -> str:
    """
    Drop a trailing remainder that contains no words.

    The rule is "wordless", not a fixed character class, because the debris a
    local model leaves is not one shape. All four of these were measured on
    nemotron-3-nano-4b, inside a grammar-constrained JSON string, after a
    perfectly finished sentence::

        ...holding its breath.\\n\\n`
        ...Just home.}`
        ...hearts full of quiet things. ``}`
        ...The clockwork bird ticks: once. `"``,

    A character class wide enough for the last two would have to include ``"``
    and ``,``, and would then strip the closing quote off every line of
    dialogue. Asking "is there a word in the tail?" costs nothing and is right
    in every case: ``He said, "Wait."`` has no tail at all, because the closing
    quote is part of the sentence-end pattern.

    Applied unconditionally -- unlike sentence trimming, which only runs when
    the generation was cut short. Debris survives every truncation check by
    construction: the sentence before it is finished, so nothing else looks.
    """
    if not text:
        return text
    end = _last_sentence_end(text)
    if end <= 0:
        # No complete sentence to fall back on. Leave it alone; something
        # imperfect beats an empty log entry.
        return text
    return text[:end] if _wordless(text[end:]) else text


def trim_to_sentence(text: str, *, min_keep_ratio: float = 0.0) -> str:
    """
    Drop an unfinished trailing fragment.

    This is the rule the player actually asked for: a dropped clause reads
    better than a visibly severed one. Wordless debris goes with it.

    Args:
        text: Narration, possibly cut mid-sentence.
        min_keep_ratio: Refuse to trim when doing so would leave less than this
            fraction of the original. At 0.0 (the default) any complete prefix
            is preferred to a broken one; raise it where losing most of the
            paragraph is worse than showing a ragged edge.

    Returns:
        The trimmed text, or the original when there is no complete sentence to
        fall back to -- showing something imperfect beats showing nothing.
    """
    if not text or not text.strip():
        return text
    end = _last_sentence_end(text)
    if end <= 0:
        return text
    kept = text[:end]
    if min_keep_ratio and len(kept) < len(text.strip()) * min_keep_ratio:
        return text
    return kept or text


def ends_mid_sentence(text: str) -> bool:
    """True when ``text`` ends with prose that is not a finished sentence."""
    if not text or not text.strip():
        return bool(text)
    end = _last_sentence_end(text)
    if end <= 0:
        return True
    return not _wordless(text[end:])


class SentenceGate:
    """
    Releases streamed narration only where it leaves a well-formed prefix.

    Raw local-model output arrives in bursts and stalls, and a naive forward of
    every delta puts half-written words and severed clauses on screen. This
    holds text back to the nearest sentence, clause or -- as a last resort --
    word boundary, so whatever is on screen at any instant reads as writing
    rather than as a socket.

    Feed it with :meth:`push` and close it with :meth:`flush`. ``flush`` is the
    important one: ``complete=False`` says the generation ended badly, and the
    unfinished tail is discarded rather than shown.
    """

    def __init__(self, *, soft_limit: int = SOFT_HOLD_LIMIT) -> None:
        self._pending = ""
        self._soft_limit = soft_limit
        # Text withheld because the stream ended mid-sentence. Diagnostics.
        self.dropped = ""

    @property
    def pending(self) -> str:
        """Text held back, not yet safe to show."""
        return self._pending

    def push(self, delta: str) -> str:
        """Feed a chunk; return the part that is safe to display now."""
        if not delta:
            return ""
        self._pending += delta
        cut = self._release_point(self._pending)
        if cut <= 0:
            return ""

        # Never release a TRAILING run of debris characters, even at a legal
        # boundary. ``...like a current.\n\n``` decodes as a finished sentence
        # followed by fence junk, and `\n` is a clause boundary -- so the
        # backtick was released and sat on screen until `turn_update` replaced
        # the text. Held back, it is simply never shown; if real prose follows,
        # the run stops being trailing and goes out with it.
        while cut > 0 and _DEBRIS_CHAR.match(self._pending[cut - 1]):
            cut -= 1
        if cut <= 0:
            return ""

        emitted = self._pending[:cut]
        self._pending = self._pending[cut:]
        return emitted

    def flush(self, *, complete: bool = True) -> str:
        """
        Release what is held.

        Args:
            complete: True when the model stopped of its own accord, so the
                tail is the author's ending and is shown verbatim. False when
                the generation was cut short (``finish_reason: "length"``, a
                transport error, a truncated JSON envelope), in which case only
                whole sentences are released and the severed remainder is
                dropped into ``self.dropped``.
        """
        text = self._pending
        self._pending = ""
        if not text:
            return ""
        if complete:
            # Even a model that stopped of its own accord leaves fence debris
            # behind; that is punctuation-shaped, not prose, and never belongs
            # on screen. A tail that is ONLY debris is dropped outright.
            return "" if _wordless(text) else strip_trailing_debris(text)

        end = trailing_fragment(text)
        if end <= 0:
            # Nothing complete to keep. Holding the whole fragment back is the
            # point: the caller's authoritative narration will replace it.
            self.dropped = text
            return ""
        self.dropped = text[end:]
        return text[:end]

    def _release_point(self, text: str) -> int:
        """Index up to which ``text`` is safe to emit, or 0 to hold it all."""
        end = 0
        for match in _SENTENCE_END.finditer(text):
            end = match.end()
        if end:
            return end

        for match in _CLAUSE_END.finditer(text):
            end = match.end()
        if end:
            return end

        if len(text) > self._soft_limit:
            # Long unpunctuated run. Emit up to the last whole word so the
            # screen keeps moving without ever showing half a word.
            space = text.rfind(" ")
            if space > 0:
                return space + 1
        return 0


@dataclass
class StatDelta:
    """Stat adjustment from [STAT:name±value]."""

    stat: str = ""
    delta: int = 0


@dataclass
class ToolCallRecord:
    """Tool call observed during streaming."""

    name: str = ""
    arguments: dict[str, Any] = field(default_factory=dict)
    output: str = ""
    success: bool = True


@dataclass
class ProcessedResponse:
    """Rich result from processing a stream."""

    raw_text: str = ""
    clean_text: str = ""
    reasoning_content: str = ""
    mood_tags: list[str] = field(default_factory=list)
    image_requests: list[str] = field(default_factory=list)
    cutscene_requests: list[str] = field(default_factory=list)
    action_tags: list[str] = field(default_factory=list)
    stat_deltas: list[StatDelta] = field(default_factory=list)
    voice_style: str = ""
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    response_id: str = ""
    model: str = ""
    latency_ms: float = 0.0
    all_tags: dict[str, list[str]] = field(default_factory=dict)
    stats: dict[str, Any] = field(default_factory=dict)
    finish_reason: str = ""
    error: str = ""

    @property
    def has_images(self) -> bool:
        return bool(self.image_requests)

    @property
    def has_cutscenes(self) -> bool:
        return bool(self.cutscene_requests)

    @property
    def has_reasoning(self) -> bool:
        return bool(self.reasoning_content)

    @property
    def starved_by_reasoning(self) -> bool:
        """
        The model thought itself out of a reply.

        Empty content behind non-empty reasoning is the confirmed production
        bug. Callers check this instead of treating an empty string as "the
        model declined to answer".
        """
        return bool(self.reasoning_content) and not self.raw_text.strip()

    @property
    def truncated(self) -> bool:
        return self.finish_reason == "length"

    @property
    def truncated_mid_content(self) -> bool:
        """Cut at the ceiling with prose already written -- a severed sentence."""
        return self.truncated and bool(self.raw_text.strip())

    @property
    def ends_mid_sentence(self) -> bool:
        """The displayable text does not end on a sentence boundary."""
        return ends_mid_sentence(self.clean_text)

    @property
    def reasoning_tokens(self) -> int:
        return int(self.stats.get("reasoning_output_tokens", 0) or 0)

    @property
    def output_tokens(self) -> int:
        return int(self.stats.get("total_output_tokens", 0) or 0)


class StreamProcessor:
    """Consumes LMSStreamEvent callbacks and content; produces ProcessedResponse."""

    def __init__(
        self,
        *,
        on_delta: Optional[Callable[[str], None]] = None,
        on_mood: Optional[Callable[[str], None]] = None,
        on_image_request: Optional[Callable[[str], None]] = None,
        on_cutscene_request: Optional[Callable[[str], None]] = None,
        on_action: Optional[Callable[[str], None]] = None,
        on_stat_delta: Optional[Callable[[StatDelta], None]] = None,
        on_tool_call: Optional[Callable[[ToolCallRecord], None]] = None,
        on_reasoning: Optional[Callable[[str], None]] = None,
    ) -> None:
        self._on_reasoning = on_reasoning
        self._on_delta = on_delta
        self._on_mood = on_mood
        self._on_image_request = on_image_request
        self._on_cutscene_request = on_cutscene_request
        self._on_action = on_action
        self._on_stat_delta = on_stat_delta
        self._on_tool_call = on_tool_call

        self._content_parts: list[str] = []
        self._reasoning_parts: list[str] = []
        self._finish_reason = ""
        self._error = ""
        self._mood_tags: list[str] = []
        self._image_requests: list[str] = []
        self._cutscene_requests: list[str] = []
        self._action_tags: list[str] = []
        self._stat_deltas: list[StatDelta] = []
        self._voice_styles: list[str] = []
        self._tool_calls: list[ToolCallRecord] = []
        self._current_tool: Optional[ToolCallRecord] = None
        self._response_id = ""
        self._model = ""
        self._stats: dict[str, Any] = {}
        self._t_start = 0.0
        self._t_end = 0.0

    def on_event(self, event: Any) -> None:
        """Process LMSStreamEvent from LMSClient.chat_stream."""
        etype = getattr(event, "event_type", "")
        if not self._t_start:
            self._t_start = time.perf_counter()

        if etype == "chat.start":
            self._model = getattr(event, "model_instance_id", "") or self._model
        elif etype == "message.delta":
            content = getattr(event, "content", "")
            if content:
                self._content_parts.append(content)
                self._scan_for_tags(content)
                if self._on_delta:
                    self._on_delta(content)
        elif etype == "reasoning.delta":
            # Captured, forwarded, and NEVER scanned for tags. See the module
            # docstring: a model musing "[IMAGE:...]" must not generate one.
            content = getattr(event, "content", "")
            if content:
                self._reasoning_parts.append(content)
                if self._on_reasoning:
                    self._on_reasoning(content)
        elif etype == "tool_call.start":
            self._current_tool = ToolCallRecord(name=getattr(event, "tool_name", ""))
        elif etype == "tool_call.arguments":
            if self._current_tool:
                self._current_tool.arguments = getattr(event, "tool_arguments", None) or {}
        elif etype == "tool_call.success":
            if self._current_tool:
                self._current_tool.output = getattr(event, "tool_output", "")
                self._current_tool.success = True
                self._tool_calls.append(self._current_tool)
                if self._on_tool_call:
                    self._on_tool_call(self._current_tool)
                self._current_tool = None
        elif etype == "tool_call.failure":
            # Previously dropped on the floor, so a tool the model tried and
            # failed to call looked identical to one it never attempted.
            if self._current_tool:
                self._current_tool.success = False
                self._current_tool.output = getattr(event, "error", "")
                self._tool_calls.append(self._current_tool)
                if self._on_tool_call:
                    self._on_tool_call(self._current_tool)
                self._current_tool = None
            logger.warning(
                "[StreamProcessor] Tool call failed (operation=on_event): %s",
                getattr(event, "error", ""),
            )
        elif etype == "chat.end":
            self._t_end = time.perf_counter()
            self._response_id = getattr(event, "response_id", "") or ""
            self._stats = getattr(event, "stats", None) or {}
            # Declared on ProcessedResponse since the first version and never
            # once assigned, so `finish_reason` was permanently "" and a
            # guillotined generation looked exactly like a finished one.
            self._finish_reason = str(self._stats.get("finish_reason", "") or "")
        elif etype == "error":
            self._error = getattr(event, "error", "") or ""
            logger.error(
                "[StreamProcessor] Stream error (operation=on_event): %s",
                self._error,
            )

    def _scan_for_tags(self, text: str) -> None:
        """Extract inline tags from a content delta."""
        for match in _RE_MOOD.finditer(text):
            for mood in [m.strip() for m in match.group(1).split(",")]:
                self._mood_tags.append(mood)
                if self._on_mood:
                    self._on_mood(mood)

        for match in _RE_IMAGE.finditer(text):
            prompt = match.group(1).strip()
            self._image_requests.append(prompt)
            if self._on_image_request:
                self._on_image_request(prompt)

        for match in _RE_CUTSCENE.finditer(text):
            cid = match.group(1).strip()
            self._cutscene_requests.append(cid)
            if self._on_cutscene_request:
                self._on_cutscene_request(cid)

        for match in _RE_ACTION.finditer(text):
            action = match.group(1).strip()
            self._action_tags.append(action)
            if self._on_action:
                self._on_action(action)

        for match in _RE_STAT.finditer(text):
            sd = StatDelta(stat=match.group(1), delta=int(match.group(2)))
            self._stat_deltas.append(sd)
            if self._on_stat_delta:
                self._on_stat_delta(sd)

        for match in _RE_VOICE.finditer(text):
            self._voice_styles.append(match.group(1).strip())

    def result(self) -> ProcessedResponse:
        """Assemble ProcessedResponse after stream completes."""
        raw_text = "".join(self._content_parts)
        clean_text = _STRIP_TAGS.sub("", raw_text).strip()
        if not self._t_end:
            self._t_end = time.perf_counter()
        latency = self._stats.get("latency_ms") or (
            (self._t_end - self._t_start) * 1000 if self._t_start else 0.0
        )

        all_tags: dict[str, list[str]] = {}
        if self._mood_tags:
            all_tags["mood"] = list(self._mood_tags)
        if self._image_requests:
            all_tags["image"] = list(self._image_requests)
        if self._cutscene_requests:
            all_tags["cutscene"] = list(self._cutscene_requests)
        if self._action_tags:
            all_tags["action"] = list(self._action_tags)
        if self._stat_deltas:
            all_tags["stat"] = [f"{s.stat}{s.delta:+d}" for s in self._stat_deltas]
        if self._voice_styles:
            all_tags["voice"] = list(self._voice_styles)

        reasoning_content = "".join(self._reasoning_parts)
        if reasoning_content and not raw_text.strip():
            logger.error(
                "[StreamProcessor] REASONING STARVED THE OUTPUT — the content "
                "channel is empty behind %s chars of reasoning "
                "(operation=result, model=%s, reasoning_tokens=%s)",
                len(reasoning_content),
                self._model,
                self._stats.get("reasoning_output_tokens", "?"),
            )

        return ProcessedResponse(
            raw_text=raw_text,
            clean_text=clean_text,
            reasoning_content=reasoning_content,
            stats=dict(self._stats),
            finish_reason=self._finish_reason,
            error=self._error,
            mood_tags=list(self._mood_tags),
            image_requests=list(self._image_requests),
            cutscene_requests=list(self._cutscene_requests),
            action_tags=list(self._action_tags),
            stat_deltas=list(self._stat_deltas),
            voice_style=self._voice_styles[-1] if self._voice_styles else "",
            tool_calls=list(self._tool_calls),
            response_id=self._response_id,
            model=self._model,
            latency_ms=float(latency),
            all_tags=all_tags,
        )

    @staticmethod
    def extract_tags(text: str) -> ProcessedResponse:
        """Parse tags from a complete string (no streaming)."""
        proc = StreamProcessor()
        proc._scan_for_tags(text)
        proc._content_parts.append(text)
        return proc.result()