"""LMSClient SSE streaming tests (mocked HTTP)."""

from __future__ import annotations

import json

import httpx
import pytest

from engine.agents.stream_processor import StreamProcessor
from engine.config import reset_config
from engine.lmstudio.client import (
    LMSClient,
    _ToolCallAccumulator,
    compat_cap,
    extract_reasoning,
    reset_lms_client,
)
from engine.lmstudio.profiles import resolve_profile, wire_cap


def _sse_lines(*chunks: str) -> bytes:
    lines = []
    for c in chunks:
        payload = json.dumps({"choices": [{"delta": {"content": c}}]})
        lines.append(f"data: {payload}")
    lines.append("data: [DONE]")
    return "\n".join(lines).encode("utf-8")


def _sse_raw(*payloads: dict) -> bytes:
    lines = [f"data: {json.dumps(p)}" for p in payloads]
    lines.append("data: [DONE]")
    return "\n".join(lines).encode("utf-8")


def _mock(client: LMSClient, handler) -> None:
    client._client = httpx.Client(
        transport=httpx.MockTransport(handler), base_url="http://test.local/v1"
    )


def test_resolve_profiles():
    reset_config()
    big = resolve_profile("big")
    draft = resolve_profile("draft")
    assert big.name == "big"
    assert draft.max_tokens == 256


def test_utility_profiles_disable_reasoning():
    """
    The whole point of the rebuild.

    max_tokens caps reasoning + content combined, so a utility profile that
    leaves reasoning on spends its cap thinking and returns "".
    """
    reset_config()
    assert resolve_profile("small").reasoning == "off"
    assert resolve_profile("draft").reasoning == "off"
    # Narration keeps reasoning: it is shown to the player as its own channel.
    assert resolve_profile("big").reasoning == "on"


def test_narration_and_utility_are_in_different_lanes():
    """A summarizer call must not be able to stall the text on screen."""
    reset_config()
    assert resolve_profile("big").lane != resolve_profile("small").lane


def test_chat_stream_mock(monkeypatch):
    reset_lms_client()
    client = LMSClient(base_url="http://test.local/v1")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/chat/completions")
        return httpx.Response(200, content=_sse_lines("Hello ", "forest."))

    _mock(client, handler)

    proc = StreamProcessor()
    chunks = list(
        client.chat_stream(
            [{"role": "user", "content": "hi"}],
            model="test-model",
            on_event=proc.on_event,
        )
    )
    assert "".join(chunks) == "Hello forest."
    result = proc.result()
    assert "Hello forest." in result.clean_text
    client.close()


def test_infer_processed_with_tags(monkeypatch):
    reset_lms_client()
    client = LMSClient(base_url="http://test.local/v1")
    body = _sse_lines("Mist rises. [IMAGE:forest_clearing] ")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body)

    _mock(client, handler)

    result = client.infer_processed(
        [{"role": "user", "content": "describe"}],
        profile="big",
    )
    assert result.image_requests == ["forest_clearing"]
    assert "Mist rises." in result.clean_text
    client.close()


# -- the confirmed production bug ----------------------------------------


def test_reasoning_is_read_not_dropped():
    """
    THE BUG. The non-streaming path did `message.get("content") or ""` and
    nothing else, so a model that hit max_tokens while still thinking produced
    an empty string with no explanation anywhere.
    """
    reset_lms_client()
    client = LMSClient(base_url="http://test.local/v1")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": "",
                            "reasoning_content": "thinking " * 100,
                            "tool_calls": [],
                        },
                        "finish_reason": "length",
                    }
                ],
                "usage": {
                    "prompt_tokens": 20,
                    "completion_tokens": 400,
                    "completion_tokens_details": {"reasoning_tokens": 400},
                },
            },
        )

    _mock(client, handler)
    result = client.chat([{"role": "user", "content": "hi"}], model="m")

    assert result.content == ""
    assert result.reasoning_content.startswith("thinking")
    assert result.reasoning_tokens == 400
    assert result.truncated
    # The specific, retryable failure class -- not "the model wrote nothing".
    assert result.starved_by_reasoning
    client.close()


def test_gpt_oss_reasoning_key_is_also_read():
    """gpt-oss models use `reasoning`, DeepSeek-style use `reasoning_content`."""
    assert extract_reasoning({"reasoning": "abc"}) == "abc"
    assert extract_reasoning({"reasoning_content": "def"}) == "def"
    assert extract_reasoning({"reasoning": {"content": "ghi"}}) == "ghi"
    assert extract_reasoning({"content": "not reasoning"}) == ""


def test_streamed_reasoning_never_reaches_the_content_channel():
    """
    Reasoning must not be yielded. A model musing "[IMAGE:forest]" while it
    thinks must not fire a real image generation.
    """
    reset_lms_client()
    client = LMSClient(base_url="http://test.local/v1")
    body = _sse_raw(
        {"choices": [{"delta": {"reasoning_content": "maybe [IMAGE:forest] fits"}}]},
        {"choices": [{"delta": {"content": "Mist rises."}}]},
        {"choices": [{"delta": {}, "finish_reason": "stop"}]},
    )
    _mock(client, lambda r: httpx.Response(200, content=body))

    reasoning: list[str] = []
    proc = StreamProcessor(on_reasoning=reasoning.append)
    generator = client.chat_stream(
        [{"role": "user", "content": "hi"}],
        model="m",
        on_event=proc.on_event,
        on_reasoning=reasoning.append,
    )
    chunks = list(generator)

    assert "".join(chunks) == "Mist rises."
    assert "maybe [IMAGE:forest] fits" in "".join(reasoning)
    result = proc.result()
    # Captured...
    assert "IMAGE:forest" in result.reasoning_content
    # ...and NOT acted on.
    assert result.image_requests == []
    assert result.clean_text == "Mist rises."
    client.close()


def test_streamed_tool_call_fragments_are_reassembled():
    """
    Streamed arguments arrive as fragments keyed by index. Parsing them one at
    a time yields nothing but JSONDecodeErrors, which is why streaming tool
    calls could not work here at all.
    """
    accumulator = _ToolCallAccumulator()
    accumulator.push([{"index": 0, "id": "call_a", "function": {"name": "roll", "arguments": '{"dice"'}}])
    accumulator.push([{"index": 0, "function": {"arguments": ': "1d20"'}}])
    accumulator.push([{"index": 0, "function": {"arguments": "}"}}])

    calls = accumulator.flush()
    assert len(calls) == 1
    assert calls[0].name == "roll"
    assert calls[0].arguments == {"dice": "1d20"}
    assert calls[0].id == "call_a"


def test_chat_stream_accepts_tools_and_returns_them():
    """chat_stream had no `tools` param, so tool calling while streaming was
    structurally impossible."""
    reset_lms_client()
    client = LMSClient(base_url="http://test.local/v1")
    sent: dict = {}

    body = _sse_raw(
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "c1",
                                "function": {"name": "roll", "arguments": '{"d":'},
                            }
                        ]
                    }
                }
            ]
        },
        {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": "20}"}}]}}]},
        {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]},
    )

    def handler(request: httpx.Request) -> httpx.Response:
        sent.update(json.loads(request.content.decode()))
        return httpx.Response(200, content=body)

    _mock(client, handler)

    generator = client.chat_stream(
        [{"role": "user", "content": "roll"}],
        model="m",
        tools=[{"type": "function", "function": {"name": "roll"}}],
    )
    try:
        while True:
            next(generator)
    except StopIteration as stop:
        result = stop.value

    assert sent["tools"]
    assert sent["stream_options"] == {"include_usage": True}
    assert result.finish_reason == "tool_calls"
    assert [c.name for c in result.tool_calls] == ["roll"]
    assert result.tool_calls[0].arguments == {"d": 20}
    client.close()


def test_stream_reports_real_token_counts():
    """Token counts used to be hardcoded zeros on the streaming path."""
    reset_lms_client()
    client = LMSClient(base_url="http://test.local/v1")
    body = _sse_raw(
        {"choices": [{"delta": {"content": "hi"}}]},
        {
            "choices": [],
            "usage": {
                "prompt_tokens": 11,
                "completion_tokens": 22,
                "completion_tokens_details": {"reasoning_tokens": 7},
            },
        },
    )
    _mock(client, lambda r: httpx.Response(200, content=body))

    generator = client.chat_stream([{"role": "user", "content": "hi"}], model="m")
    try:
        while True:
            next(generator)
    except StopIteration as stop:
        result = stop.value

    assert result.input_tokens == 11
    assert result.output_tokens == 22
    assert result.reasoning_tokens == 7
    client.close()


# -- the two budgets -------------------------------------------------------


def test_content_and_reasoning_are_budgeted_separately():
    """
    The defect this whole seam exists for.

    One combined cap is not a budget, it is a race. Measured on this machine,
    narration spent 1098-2630 tokens thinking inside a 3000-token ceiling, so
    the answer got the remainder -- often a severed sentence, sometimes nothing.
    `max_tokens` is the answer's floor now and `reasoning_budget` is bought
    separately; the wire cap is their sum.
    """
    reset_config()
    big = resolve_profile("big")
    assert big.max_tokens > 0
    assert big.reasoning_budget >= 2997, "must clear the worst measured think"
    assert big.wire_cap("on") == big.max_tokens + big.reasoning_budget
    # Reasoning off spends nothing on thinking, so it buys nothing extra.
    assert big.wire_cap("off") == big.max_tokens


def test_a_negative_reasoning_budget_cannot_shrink_the_answer():
    """A bad config value must not eat into the content floor."""
    assert wire_cap(1000, -500, "on") == 1000


def test_uncapped_stays_uncapped():
    """A non-positive cap means 'no ceiling'; adding to it would invent one."""
    assert wire_cap(0, 3200, "on") == 0


def test_compat_transport_pays_for_reasoning_it_cannot_switch_off():
    """
    Honouring `reasoning: off` on this route would starve the request.

    /v1/chat/completions ignores every reasoning control. Measured: the big
    profile set to "off" still burned 2331 and 2630 reasoning tokens on two
    consecutive narration turns, because a schema-constrained call has to ride
    this route. So the budget is granted unconditionally here.
    """
    assert compat_cap(1200, 3200) == 4400


def test_compat_chat_sends_the_summed_ceiling():
    reset_lms_client()
    client = LMSClient(base_url="http://test.local/v1")
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
                "usage": {"completion_tokens": 5},
            },
        )

    _mock(client, handler)
    client.chat(
        [{"role": "user", "content": "hi"}],
        model="m",
        max_tokens=1200,
        reasoning_budget=3200,
    )
    assert seen["max_tokens"] == 4400
    client.close()


def test_compat_stream_sends_the_summed_ceiling():
    reset_lms_client()
    client = LMSClient(base_url="http://test.local/v1")
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(200, content=_sse_lines("hi"))

    _mock(client, handler)
    generator = client.chat_stream(
        [{"role": "user", "content": "hi"}],
        model="m",
        max_tokens=900,
        reasoning_budget=800,
    )
    for _ in generator:
        pass
    assert seen["max_tokens"] == 1700
    client.close()
