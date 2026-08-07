"""
StreamProcessor — inline tag extraction from LLM output.

Parses: [MOOD:], [IMAGE:], [CUTSCENE:], [ACTION:], [STAT:], [VOICE:]

Version: v0.1.0 [2026-06-20]
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

    @property
    def has_images(self) -> bool:
        return bool(self.image_requests)

    @property
    def has_cutscenes(self) -> bool:
        return bool(self.cutscene_requests)


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
    ) -> None:
        self._on_delta = on_delta
        self._on_mood = on_mood
        self._on_image_request = on_image_request
        self._on_cutscene_request = on_cutscene_request
        self._on_action = on_action
        self._on_stat_delta = on_stat_delta
        self._on_tool_call = on_tool_call

        self._content_parts: list[str] = []
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
        elif etype == "chat.end":
            self._t_end = time.perf_counter()
            self._response_id = getattr(event, "response_id", "") or ""
            self._stats = getattr(event, "stats", None) or {}
        elif etype == "error":
            logger.error(
                "[StreamProcessor] Stream error (operation=on_event): %s",
                getattr(event, "error", ""),
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

        return ProcessedResponse(
            raw_text=raw_text,
            clean_text=clean_text,
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