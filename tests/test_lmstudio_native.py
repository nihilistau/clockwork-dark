"""
Native LM Studio transport, registry and backend routing.

Everything here is mocked. The live-server evidence that motivated the module
lives in engine/lmstudio/native.py's docstring; these tests pin the contract.
"""

from __future__ import annotations

import json

import httpx
import pytest

from engine.agents.stream_processor import StreamProcessor
from engine.config import reset_config
from engine.lmstudio.backend import LMStudioBackend
from engine.lmstudio.events import LMSResponse
from engine.lmstudio.native import NativeClient, messages_to_native
from engine.lmstudio.registry import ModelInfo, ModelRegistry, ModelUnavailable

# -- request translation --------------------------------------------------


def test_system_blocks_are_hoisted_into_system_prompt():
    """
    /api/v1/chat has no per-message role: `input` is a flat array of
    {type, content} parts. Verified against the live server -- sending a role
    key returns 400 "Unrecognized key(s) in object: 'role'".
    """
    system, parts = messages_to_native(
        [
            {"role": "system", "content": "You are the Storyteller."},
            {"role": "system", "content": "WORLD STATE: dusk."},
            {"role": "user", "content": "I enter the clearing."},
        ]
    )
    assert system == "You are the Storyteller.\n\nWORLD STATE: dusk."
    assert parts == [{"type": "text", "content": "I enter the clearing."}]


def test_assistant_turns_keep_a_visible_label():
    """Without a role slot, history would otherwise flatten into one blob."""
    _, parts = messages_to_native(
        [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "The forest waits."},
        ]
    )
    assert parts[1]["content"].startswith("[ASSISTANT]")
    assert "The forest waits." in parts[1]["content"]


def test_empty_messages_do_not_produce_an_empty_input():
    """The endpoint rejects an empty `input` array."""
    client = NativeClient(base_url="http://test.local/v1")
    payload = client._payload(
        [{"role": "system", "content": "persona only"}],
        model="m",
        temperature=0.5,
        max_tokens=100,
        reasoning="off",
        context_length=4096,
        stream=False,
    )
    assert payload["input"]
    assert payload["system_prompt"] == "persona only"
    assert payload["reasoning"] == "off"
    assert payload["max_output_tokens"] == 100
    client.close()


# -- response parsing -----------------------------------------------------


def _native_client(handler) -> NativeClient:
    client = NativeClient(base_url="http://test.local/v1")
    client._client = httpx.Client(transport=httpx.MockTransport(handler))
    return client


def test_reasoning_and_message_arrive_on_separate_channels():
    body = {
        "model_instance_id": "nvidia/nemotron-3-nano-4b",
        "response_id": "resp_1",
        "output": [
            {"type": "reasoning", "content": "Let me think about dusk."},
            {"type": "message", "content": "The clearing dims."},
        ],
        "stats": {
            "input_tokens": 31,
            "total_output_tokens": 58,
            "reasoning_output_tokens": 52,
            "tokens_per_second": 13.4,
        },
    }
    client = _native_client(lambda r: httpx.Response(200, json=body))
    result = client.chat([{"role": "user", "content": "hi"}], model="m", max_tokens=400)

    assert result.content == "The clearing dims."
    assert result.reasoning_content == "Let me think about dusk."
    assert result.reasoning_tokens == 52
    assert result.output_tokens == 58
    assert result.transport == "native"
    assert not result.truncated
    assert result.stats["tokens_per_second"] == pytest.approx(13.4)
    client.close()


def test_hitting_the_ceiling_is_detected_without_a_finish_reason():
    """
    The native endpoint reports no finish_reason. Truncation is inferred from
    the token count, which is exact: a run capped at 60 returns
    total_output_tokens == 60. Without this, `starved_by_reasoning` could never
    fire on the native path.
    """
    body = {
        "output": [
            {"type": "reasoning", "content": "thinking " * 50},
            {"type": "message", "content": ""},
        ],
        "stats": {"total_output_tokens": 60, "reasoning_output_tokens": 57},
    }
    client = _native_client(lambda r: httpx.Response(200, json=body))
    result = client.chat([{"role": "user", "content": "hi"}], model="m", max_tokens=60)

    assert result.truncated
    assert result.starved_by_reasoning
    client.close()


# -- streaming ------------------------------------------------------------


def _sse(*events: tuple[str, dict]) -> bytes:
    lines = []
    for name, data in events:
        lines.append(f"event: {name}")
        lines.append(f"data: {json.dumps(data)}")
        lines.append("")
    return "\n".join(lines).encode("utf-8")


def test_native_stream_splits_reasoning_from_content():
    body = _sse(
        ("chat.start", {"type": "chat.start", "model_instance_id": "m"}),
        ("prompt_processing.start", {"type": "prompt_processing.start"}),
        ("reasoning.start", {"type": "reasoning.start"}),
        ("reasoning.delta", {"type": "reasoning.delta", "content": "perhaps [IMAGE:x]"}),
        ("reasoning.end", {"type": "reasoning.end"}),
        ("message.start", {"type": "message.start"}),
        ("message.delta", {"type": "message.delta", "content": "Mist rises."}),
        ("message.end", {"type": "message.end"}),
        (
            "chat.end",
            {
                "type": "chat.end",
                "result": {
                    "output": [
                        {"type": "reasoning", "content": "perhaps [IMAGE:x]"},
                        {"type": "message", "content": "Mist rises."},
                    ],
                    "stats": {"total_output_tokens": 9, "reasoning_output_tokens": 5},
                    "response_id": "resp_9",
                },
            },
        ),
    )
    client = _native_client(lambda r: httpx.Response(200, content=body))

    reasoning: list[str] = []
    content: list[str] = []
    proc = StreamProcessor(on_reasoning=reasoning.append)
    generator = client.chat_stream(
        [{"role": "user", "content": "hi"}],
        model="m",
        max_tokens=500,
        on_event=proc.on_event,
        on_delta=content.append,
        on_reasoning=reasoning.append,
    )
    yielded = list(generator)

    # Only content is yielded; reasoning never reaches the narration decoder.
    assert yielded == ["Mist rises."]
    assert content == ["Mist rises."]
    assert "perhaps [IMAGE:x]" in "".join(reasoning)

    result = proc.result()
    assert result.reasoning_content == "perhaps [IMAGE:x]"
    assert result.image_requests == []          # tag scanner never saw it
    assert result.clean_text == "Mist rises."
    assert result.reasoning_tokens == 5
    client.close()


# -- registry -------------------------------------------------------------


_MODELS = {
    "data": [
        {
            "id": "nvidia/nemotron-3-nano-4b",
            "type": "llm",
            "arch": "nemotron_h",
            "state": "loaded",
            "max_context_length": 1048576,
            "loaded_context_length": 20224,
            "capabilities": ["tool_use"],
        },
        {
            "id": "gemma-4-e4b-it",
            "type": "vlm",
            "arch": "gemma4",
            "state": "not-loaded",
            "max_context_length": 131072,
            "capabilities": ["tool_use"],
        },
        {
            "id": "lfm2.5-1.2b-instruct@q8_0",
            "type": "llm",
            "arch": "lfm2",
            "state": "not-loaded",
            "max_context_length": 128000,
            "capabilities": ["tool_use"],
        },
        {"id": "vae", "type": "llm", "arch": None, "max_context_length": 4096},
        {"id": "text_encoder", "type": "llm", "arch": "clip_text_model", "max_context_length": 77},
    ]
}


def _registry() -> ModelRegistry:
    registry = ModelRegistry(base_url="http://test.local/v1")
    registry._models = [
        __import__("engine.lmstudio.registry", fromlist=["_parse"])._parse(m)
        for m in _MODELS["data"]
    ]
    return registry


def test_loaded_context_length_wins_over_the_advertised_window():
    """
    Nemotron advertises 1,048,576 tokens but the user loaded it at 20,224.
    Budgeting against the advertised number overflows the real one, and LM
    Studio truncates the prompt from the front -- taking the system persona.
    """
    registry = _registry()
    nemotron = registry.get("nvidia/nemotron-3-nano-4b")
    assert nemotron is not None
    assert nemotron.usable_context == 20224


def test_encoders_and_vaes_are_not_chat_models():
    registry = _registry()
    ids = {m.id for m in registry.chat_models()}
    assert "vae" not in ids
    assert "text_encoder" not in ids


def test_denylisted_model_is_never_bound():
    """gemma-4-e4b-it is reported broken on this host."""
    registry = _registry()
    assert all(m.id != "gemma-4-e4b-it" for m in registry.chat_models())
    binding = registry.bind("big", prefer=("gemma-4-e4b-it",))
    assert binding.model.id != "gemma-4-e4b-it"


def test_loaded_models_are_preferred():
    """A JIT load inside a player's turn is a multi-second freeze."""
    registry = _registry()
    assert registry.bind("big").model.id == "nvidia/nemotron-3-nano-4b"


def test_residency_outranks_the_non_reasoning_preference():
    """
    A loaded reasoning model beats JIT-loading a second model for utility work.

    Pulling another model into VRAM to avoid reasoning would be a bad trade:
    the load costs seconds and contends with the narration model, while
    `reasoning: "off"` on the native transport already measures 0 reasoning
    tokens on the model that is already resident.
    """
    registry = _registry()
    binding = registry.bind("small", prefer_non_reasoning=True, allow_unloaded=True)
    assert binding.model.id == "nvidia/nemotron-3-nano-4b"
    assert binding.reason == "loaded"


def test_non_reasoning_wins_among_equally_resident_models():
    registry = _registry()
    # Nothing is loaded, so the preference is the deciding factor.
    registry._models = [
        m.__class__(**{**m.__dict__, "state": "not-loaded"}) for m in registry._models
    ]
    binding = registry.bind("small", prefer_non_reasoning=True)
    assert binding.model.id == "lfm2.5-1.2b-instruct@q8_0"


def test_failed_bind_names_the_real_available_ids():
    """"Model not found" without the list of what IS there is unactionable."""
    registry = ModelRegistry(base_url="http://test.local/v1")
    registry._models = []
    with pytest.raises(ModelUnavailable) as excinfo:
        registry.bind("big")
    assert "Available chat models" in str(excinfo.value)


# -- backend routing ------------------------------------------------------


class _Recorder:
    """Stands in for either transport, recording what it was asked to do."""

    def __init__(self, response: LMSResponse | None = None) -> None:
        self.calls: list[dict] = []
        self.response = response or LMSResponse(content="ok")

    def chat(self, messages, **kwargs):
        self.calls.append(kwargs)
        return self.response

    def chat_stream(self, messages, **kwargs):
        self.calls.append(kwargs)
        yield self.response.content
        return self.response


def _backend(native_ok: bool = True) -> tuple[LMStudioBackend, _Recorder, _Recorder]:
    reset_config()
    compat = _Recorder()
    native = _Recorder()
    backend = LMStudioBackend(compat=compat, native=native, prefer_native=True)
    backend._native_available = native_ok
    return backend, compat, native


def test_tool_requests_must_use_the_openai_transport():
    """/api/v1/chat rejects `tools` outright (400 unrecognized_keys)."""
    backend, compat, native = _backend()
    assert backend.use_native(tools=[{"type": "function"}]) is False
    backend.chat([{"role": "user", "content": "x"}], tools=[{"type": "function"}])
    assert compat.calls and not native.calls


def test_structured_output_requests_must_use_the_openai_transport():
    backend, compat, native = _backend()
    assert backend.use_native(response_format={"type": "json_object"}) is False


def test_plain_requests_prefer_native():
    """Native is preferred because it is the only transport that can turn
    reasoning off."""
    backend, compat, native = _backend()
    assert backend.use_native() is True
    backend.chat([{"role": "user", "content": "x"}], profile="small")
    assert native.calls and not compat.calls
    assert native.calls[0]["reasoning"] == "off"


def test_starved_response_is_retried_with_reasoning_off():
    """The recovery for the confirmed production bug."""
    reset_config()
    starved = LMSResponse(content="", reasoning_content="thinking", finish_reason="length")
    good = LMSResponse(content="The clearing dims.")

    compat = _Recorder(starved)
    native = _Recorder(good)
    backend = LMStudioBackend(compat=compat, native=native, prefer_native=True)
    backend._native_available = True

    result = backend.chat(
        [{"role": "user", "content": "x"}],
        profile="big",
        response_format={"type": "json_object"},  # forces the compat transport
    )
    assert compat.calls          # first attempt went to compat
    assert native.calls          # retry went native...
    assert native.calls[0]["reasoning"] == "off"   # ...with reasoning off
    assert result.content == "The clearing dims."


def test_no_retry_when_native_is_unavailable():
    """The compat endpoint cannot disable reasoning, so a retry there would
    starve identically and cost the player another full generation."""
    reset_config()
    starved = LMSResponse(content="", reasoning_content="thinking", finish_reason="length")
    compat = _Recorder(starved)
    native = _Recorder()
    backend = LMStudioBackend(compat=compat, native=native, prefer_native=True)
    backend._native_available = False

    result = backend.chat([{"role": "user", "content": "x"}], profile="big")
    assert len(compat.calls) == 1
    assert not native.calls
    assert result.starved_by_reasoning


def test_structured_output_off_returns_nothing():
    """`off` frees the request to use the native transport."""
    from engine.config import set_overlay

    set_overlay({"lmstudio": {"structured_output": "off"}})
    try:
        backend, _, _ = _backend()
        assert backend.structured_output({"type": "object"}) is None
    finally:
        set_overlay(None)


def test_json_object_mode_is_emitted_as_a_permissive_schema():
    """
    LM Studio rejects OpenAI's {"type": "json_object"} with
    400 "'response_format.type' must be 'json_schema' or 'text'".
    """
    from engine.config import set_overlay

    set_overlay({"lmstudio": {"structured_output": "json_object"}})
    try:
        backend, _, _ = _backend()
        emitted = backend.structured_output({"type": "object"})
        assert emitted["type"] == "json_schema"
        assert emitted["json_schema"]["schema"]["additionalProperties"] is True
    finally:
        set_overlay(None)


def test_structured_output_json_schema_mode_wraps_the_schema():
    """The envelope the ONLY production narration path never once sent."""
    from engine.config import set_overlay

    set_overlay({"lmstudio": {"structured_output": "json_schema"}})
    try:
        backend, _, _ = _backend()
        wrapped = backend.structured_output({"type": "object"})
        assert wrapped["type"] == "json_schema"
        assert wrapped["json_schema"]["schema"] == {"type": "object"}
    finally:
        set_overlay(None)


# -- the two budgets ------------------------------------------------------


def test_reasoning_budget_is_added_on_top_of_the_answer():
    """
    ``max_output_tokens`` is one ceiling covering both channels, so the split
    has to be reconstructed in the payload: ask for the sum, and the content
    budget survives as the part deliberation cannot reach.
    """
    client = NativeClient(base_url="http://test.local/v1")
    payload = client._payload(
        [{"role": "user", "content": "hi"}],
        model="m",
        temperature=0.5,
        max_tokens=1200,
        reasoning="on",
        context_length=8192,
        stream=False,
        reasoning_budget=3200,
    )
    assert payload["max_output_tokens"] == 4400
    client.close()


def test_reasoning_off_buys_no_thinking_headroom():
    """Nothing will be spent thinking, so nothing is reserved for it."""
    client = NativeClient(base_url="http://test.local/v1")
    payload = client._payload(
        [{"role": "user", "content": "hi"}],
        model="m",
        temperature=0.5,
        max_tokens=1200,
        reasoning="off",
        context_length=8192,
        stream=False,
        reasoning_budget=3200,
    )
    assert payload["max_output_tokens"] == 1200
    client.close()


def test_truncation_is_judged_against_the_wire_cap_not_the_content_budget():
    """
    The ceiling the server was given is the sum, so that is what a run has to
    reach to count as truncated. Comparing against the content budget alone
    would report every ordinary reasoning turn as cut off.
    """
    body = {
        "output": [
            {"type": "reasoning", "content": "thinking"},
            {"type": "message", "content": "The clearing dims."},
        ],
        "stats": {"total_output_tokens": 2129, "reasoning_output_tokens": 1854},
    }
    client = _native_client(lambda r: httpx.Response(200, json=body))
    result = client.chat(
        [{"role": "user", "content": "hi"}],
        model="m",
        max_tokens=1200,
        reasoning="on",
        reasoning_budget=3200,
    )
    # 2129 is well past the 1200 content budget and well short of the 4400 cap.
    assert not result.truncated
    assert result.reasoning_tokens == 1854
    client.close()


def test_the_backend_hands_both_budgets_to_the_transport():
    """A profile's reasoning budget must survive the routing hop."""
    reset_config()
    seen: dict = {}

    class _Spy:
        def chat(self, messages, **kwargs):
            seen.update(kwargs)
            return LMSResponse(content="ok", finish_reason="stop")

    backend = LMStudioBackend(native=_Spy(), prefer_native=True)
    backend._native_available = True
    backend.chat([{"role": "user", "content": "hi"}], profile="big")

    from engine.lmstudio.profiles import resolve_profile

    assert seen["reasoning_budget"] == resolve_profile("big").reasoning_budget
    assert seen["max_tokens"] == resolve_profile("big").max_tokens
