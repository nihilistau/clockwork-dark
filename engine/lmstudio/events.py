"""
LM Studio stream event types.

The event vocabulary here is LM Studio's NATIVE ``/api/v1/chat`` SSE vocabulary
(chat.start, prompt_processing.*, reasoning.*, message.*, tool_call.*,
chat.end), verified against a live server. The OpenAI-compatible client
translates its flatter chunk format into the same vocabulary so downstream
consumers -- StreamProcessor above all -- only ever learn one shape.

Version: v0.3.0 [2026-08-08]
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Every event type the native endpoint can emit. Kept as data so the client can
# assert it never silently swallows an event LM Studio added in a new build.
NATIVE_EVENT_TYPES: frozenset[str] = frozenset(
    {
        "chat.start",
        "model_load.start",
        "model_load.progress",
        "model_load.end",
        "prompt_processing.start",
        "prompt_processing.progress",
        "prompt_processing.end",
        "reasoning.start",
        "reasoning.delta",
        "reasoning.end",
        "tool_call.start",
        "tool_call.arguments",
        "tool_call.success",
        "tool_call.failure",
        "message.start",
        "message.delta",
        "message.end",
        "error",
        "chat.end",
    }
)


@dataclass
class LMSStreamEvent:
    """Single SSE event from LM Studio."""

    event_type: str
    content: str = ""
    tool_name: str = ""
    tool_arguments: dict[str, Any] = field(default_factory=dict)
    tool_output: str = ""
    tool_call_id: str = ""
    response_id: str = ""
    model_instance_id: str = ""
    stats: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    load_time_seconds: float = 0.0
    # prompt_processing.progress / model_load.progress carry 0.0-1.0.
    progress: float = 0.0

    @property
    def is_reasoning(self) -> bool:
        """True for the three reasoning events.

        The one question every consumer must ask before touching ``content``:
        reasoning text must never reach the tag scanner or the narration
        decoder.
        """
        return self.event_type.startswith("reasoning.")


@dataclass
class ToolCall:
    """One tool the model asked the engine to run."""

    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "args": dict(self.arguments)}


@dataclass
class LMSResponse:
    """Completed chat response."""

    content: str = ""
    response_id: str = ""
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float = 0.0
    stats: dict[str, Any] = field(default_factory=dict)
    tool_calls: list[ToolCall] = field(default_factory=list)
    # Read rather than ignored: a max_tokens cut mid-JSON is otherwise
    # indistinguishable from a model that simply wrote badly formed output.
    finish_reason: str = ""
    # Reasoning is a separate output channel, not a prefix of `content`. On a
    # reasoning model these are the tokens that were actually spent.
    reasoning_content: str = ""
    reasoning_tokens: int = 0
    # Which transport produced this: "native" (/api/v1/chat) or "openai"
    # (/v1/chat/completions). Diagnostics only.
    transport: str = ""

    @property
    def truncated(self) -> bool:
        return self.finish_reason == "length"

    @property
    def starved_by_reasoning(self) -> bool:
        """
        The confirmed production bug, as a first-class condition.

        A reasoning model hit the token ceiling while still thinking, so the
        content channel is empty and the player gets a blank screen. This is
        NOT "the model wrote nothing" -- it wrote plenty, into the wrong
        channel -- and it is retryable with a larger ceiling or reasoning off.
        """
        return self.truncated and not self.content.strip()

    @property
    def truncated_mid_content(self) -> bool:
        """
        The cut nobody was looking for.

        ``starved_by_reasoning`` is the EMPTY-content case: dramatic, easy to
        spot, and rare on a 3000-token cap. The common one is this: the model
        wrote most of a paragraph, hit the ceiling, and stopped in the middle of
        a word. Content is non-empty, so every starvation check passes and the
        severed sentence goes straight to the player as if it were finished.

        Retryable exactly like starvation is -- and, unlike starvation, the
        partial text is worth keeping if the retry also fails.
        """
        return self.truncated and bool(self.content.strip())

    @property
    def total_output_tokens(self) -> int:
        """Reasoning plus content. `max_tokens` caps this sum, not `content`."""
        return self.output_tokens
