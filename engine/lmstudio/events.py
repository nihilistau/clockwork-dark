"""
LM Studio stream event types.

Version: v0.1.0 [2026-06-20]
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class LMSStreamEvent:
    """Single SSE event from LM Studio."""

    event_type: str
    content: str = ""
    tool_name: str = ""
    tool_arguments: dict[str, Any] = field(default_factory=dict)
    tool_output: str = ""
    response_id: str = ""
    model_instance_id: str = ""
    stats: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    load_time_seconds: float = 0.0


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

    @property
    def truncated(self) -> bool:
        return self.finish_reason == "length"