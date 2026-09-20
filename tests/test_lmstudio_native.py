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


# The shape GET /api/v1/models actually returns, copied field-for-field from
# the live server: `key` rather than `id`, `architecture` rather than `arch`,
# residency expressed as `loaded_instances` rather than a `state` string, and
# capabilities as an object rather than a list of names.
_MODELS = {
    "models": [
        {
            "key": "nvidia/nemotron-3-nano-4b",
            "type": "llm",
            "architecture": "nemotron_h",
            "publisher": "nvidia",
            "quantization": {"name": "Q4_K_M", "bits_per_weight": 4},
            "max_context_length": 1048576,
            "loaded_instances": [
                {"id": "nvidia/nemotron-3-nano-4b", "config": {"context_length": 20224}}
            ],
            "capabilities": {"vision": False, "trained_for_tool_use": True},
        },
        {
            "key": "gemma-4-e4b-it",
            "type": "llm",
            "architecture": "gemma4",
            "max_context_length": 131072,
            "loaded_instances": [],
            "capabilities": {"vision": True, "trained_for_tool_use": True},
        },
        {
            "key": "lfm2.5-1.2b-instruct@q8_0",
            "type": "llm",
            "architecture": "lfm2",
            "max_context_length": 128000,
            "loaded_instances": [],
            "capabilities": {"vision": False, "trained_for_tool_use": True},
        },
        {"key": "vae", "type": "llm", "architecture": None, "max_context_length": 4096},
        {
            "key": "text_encoder",
            "type": "llm",
            "architecture": "clip_text_model",
            "max_context_length": 77,
        },
    ]
}


def _registry() -> ModelRegistry:
    from engine.lmstudio.registry import parse_models_payload

    registry = ModelRegistry(base_url="http://test.local/v1")
    registry._models = parse_models_payload(_MODELS)
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


# -- reasoning the model does not expose ----------------------------------
#
# MEASURED, NOT GUESSED. `GET /api/v1/models` on the author's machine reports
# 42 LLMs, and 30 of them carry NO `reasoning` key under `capabilities`:
#
#   lfm2.5-vl-3b-uncensored  {"vision": true, "trained_for_tool_use": true}
#   gemma-4-e4b-it           {..., "reasoning": {"allowed_options": ["off","on"],
#                                                "default": "on"}}
#
# Sending `reasoning` to one of the 30 is a 400:
#
#   Model 'lfm2.5-vl-3b-uncensored.gguf@q8_0' does not expose reasoning
#   configuration.   (type=invalid_request, param=reasoning)
#
# which made the starvation net -- whose ENTIRE mechanism is to switch to this
# transport and send `reasoning="off"` -- guaranteed to fail on 30 of 42 local
# models. A live Wicked Garden turn starved, retried, took the 400, and the
# planner logged "No plan, treating as silent": a two-agent story quietly
# running on one agent, with nothing failing anywhere.
#
# `_capabilities` flattened the whole block to its `default` string, so both
# "exposes no reasoning at all" and "exposes it, defaulting to off" arrived
# downstream as "". The information needed to avoid the 400 was in the payload
# the engine already fetched, and was parsed away.


def _installed(capabilities: dict) -> None:
    """Make the process-wide registry hold one model with these capabilities."""
    from engine.lmstudio import registry as registry_module
    from engine.lmstudio.registry import ModelRegistry, parse_models_payload

    registry = ModelRegistry(base_url="http://test.local/v1")
    registry._models = parse_models_payload(
        {
            "models": [
                {
                    "key": "probe-model",
                    "type": "llm",
                    "architecture": "test_arch",
                    "max_context_length": 4096,
                    "loaded_instances": [],
                    "capabilities": capabilities,
                }
            ]
        }
    )
    registry_module._registry = registry


def _reasoning_sent(value: str, capabilities: dict, *, model: str = "probe-model"):
    """The `reasoning` key this payload would carry, or None when omitted."""
    from engine.lmstudio.registry import reset_registry

    _installed(capabilities)
    try:
        client = NativeClient(base_url="http://test.local/v1")
        payload = client._payload(
            [{"role": "user", "content": "hello"}],
            model=model,
            temperature=0.5,
            max_tokens=100,
            reasoning=value,
            context_length=4096,
            stream=False,
        )
        client.close()
        return payload.get("reasoning")
    finally:
        reset_registry()


def test_a_model_that_exposes_no_reasoning_config_is_sent_no_reasoning_key():
    """OMITTED, not set to "off". "off" is precisely what produced the 400."""
    sent = _reasoning_sent("off", {"vision": True, "trained_for_tool_use": True})
    assert sent is None, (
        "sent a reasoning key to a model that publishes no reasoning "
        "configuration; this is the 400 that silenced an agent"
    )


def test_a_model_that_exposes_reasoning_still_gets_the_key():
    """
    The positive control.

    A fix that simply stopped sending `reasoning` would pass the test above and
    destroy the only thing this transport exists for -- this module's own
    docstring calls the native endpoint "the ONLY way to stop a reasoning model
    from spending the whole budget thinking".
    """
    sent = _reasoning_sent(
        "off", {"reasoning": {"allowed_options": ["off", "on"], "default": "on"}}
    )
    assert sent == "off"


def test_a_value_the_model_does_not_allow_is_not_sent():
    """
    `allowed_options` is the server's own list, and it was parsed away.

    gemma publishes ["off", "on"]. "low" is a legal native level and an illegal
    value FOR THIS MODEL -- a 400 of exactly the same family, from the opposite
    direction.
    """
    sent = _reasoning_sent(
        "low", {"reasoning": {"allowed_options": ["off", "on"], "default": "on"}}
    )
    assert sent is None


def test_a_block_with_no_allowed_options_is_trusted_with_any_level():
    """
    Absent `allowed_options` means "unspecified", not "none permitted".

    The distinction that matters is whether the BLOCK exists; a server that
    stops publishing the option list must not silently disable reasoning
    control for every model at once.
    """
    sent = _reasoning_sent("off", {"reasoning": {"default": "on"}})
    assert sent == "off"


def test_an_unknown_model_is_unchanged():
    """
    Offline, or a model the registry has never seen, keeps today's behaviour.

    An empty registry means the server was unreachable, in which case the
    request is not going to succeed on any grounds -- and quietly changing what
    we send would make a network outage look like a capability decision.
    """
    from engine.lmstudio.registry import reset_registry

    reset_registry()
    client = NativeClient(base_url="http://test.local/v1")
    payload = client._payload(
        [{"role": "user", "content": "hello"}],
        model="never-heard-of-it",
        temperature=0.5,
        max_tokens=100,
        reasoning="off",
        context_length=4096,
        stream=False,
    )
    assert payload["reasoning"] == "off"
    client.close()


class _RecordingNative:
    """Captures the retry's arguments instead of issuing it."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def chat(self, messages, **kwargs):
        self.calls.append(kwargs)
        return "recovered"


def _retry(capabilities: dict, *, starved, cap: int = 320):
    from engine.lmstudio.backend import LMStudioBackend
    from engine.lmstudio.profiles import ModelProfile
    from engine.lmstudio.registry import reset_registry

    _installed(capabilities)
    try:
        native = _RecordingNative()
        backend = LMStudioBackend()
        backend.native_available = lambda: True  # type: ignore[method-assign]
        backend.native_client = lambda: native  # type: ignore[method-assign]
        result = backend._retry_without_reasoning(
            [{"role": "user", "content": "hello"}],
            ModelProfile(
                name="big",
                model="probe-model",
                max_tokens=cap,
                reasoning_budget=3200,
                reasoning="on",
            ),
            cap=cap,
            temperature=0.7,
            label="test",
            starved=starved,
        )
        return result, native.calls
    finally:
        reset_registry()


class _Starved:
    def __init__(self, reasoning_tokens: int) -> None:
        self.reasoning_tokens = reasoning_tokens


def test_a_model_that_cannot_stop_thinking_is_retried_with_measured_room():
    """
    The retry has to buy the answer space BESIDE the thinking, not instead.

    Measured live: content_budget=320, reasoning_budget=3200, wire_cap=3520 --
    the model spent 3320 tokens thinking and returned empty content. The old
    retry asked for `reasoning="off"`, which is a 400 for this model AND, had
    it been accepted, would have dropped the ceiling to 320, since `wire_cap`
    returns the content budget unchanged when reasoning is off. The second
    attempt would have had LESS room than the one that just starved.

    The new ceiling is what the model actually spent plus the full content
    budget. No magic multiplier: the number comes from what this model just did
    with this prompt.
    """
    result, calls = _retry(
        {"vision": True, "trained_for_tool_use": True}, starved=_Starved(3320)
    )
    assert result == "recovered"
    assert len(calls) == 1
    assert calls[0]["max_tokens"] == 3320 + 320
    # Not "off": that is the 400. The key is dropped on the wire by
    # native.reasoning_for, which has its own tests above.
    assert calls[0]["reasoning"] != "off"
    assert calls[0]["reasoning_budget"] == 0


def test_a_model_that_can_stop_thinking_still_gets_reasoning_off():
    """
    The positive control: the original net is intact for models that have a
    knob, and it still spends the whole ceiling on the answer.
    """
    result, calls = _retry(
        {"reasoning": {"allowed_options": ["off", "on"], "default": "on"}},
        starved=_Starved(3320),
    )
    assert result == "recovered"
    assert calls[0]["reasoning"] == "off"
    assert calls[0]["max_tokens"] == 320


def test_with_no_measurement_the_retry_stands_down():
    """
    Nothing to size the retry from, so it does not spend a player's turn.

    Same argument the method already makes about the OpenAI-compatible
    endpoint: a retry certain to starve again costs a full generation and
    cannot do better.
    """
    result, calls = _retry(
        {"vision": True, "trained_for_tool_use": True}, starved=_Starved(0)
    )
    assert result is None
    assert calls == []
