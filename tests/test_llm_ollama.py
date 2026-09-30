"""
Ollama's native transport: every request on ``POST /api/chat`` (spec §6).

WHY NATIVE. Ollama's OpenAI-compatible route cannot set ``num_ctx``. Ollama's
default context is a few thousand tokens, and it truncates a longer prompt
FROM THE FRONT, silently -- the system persona is the first thing to go, the
same defect that once dropped it on LM Studio. ``/api/chat`` takes the grammar
(``format``), ``think``, ``options.num_ctx`` and tools in one request, so the
engine speaks it for every Ollama request, streamed (NDJSON) and not.

Every request here goes through ``tests/llm_wire.py`` (the ``httpx``
transport seam), after real discovery against Ollama's own fixtures
(``/api/tags``, ``/api/ps``, ``/api/show`` per model), so the body asserted is
the body the engine would send. No socket opens; the conftest guard stays up.
The multi-model discovery fixtures (``models_tags.json``, ``models_ps.json``,
``models_show_{qwen3,llama,nomic}.json``) are ``authored`` from Ollama's API
reference -- a server with a thinking model, a plain one and an embedding
model, which the live machine did not hold. Every answer a live Ollama 0.34.4
could give is ``recorded`` (``tests/fixtures/llm/PROVENANCE.yaml``): the chat
answers, streams, refusals and the live model list (``*_live.json``).

Every test that sends a chat request fails on v0.18.0's successor at T4
(2854f07), where an ``ollama`` config rode the OpenAI-compatible client to
``/chat/completions`` with no ``num_ctx`` at all.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import httpx
import pytest

from tests.llm_wire import wire

pytestmark = pytest.mark.real_discovery

REPO = Path(__file__).resolve().parents[1]
FIXTURES = REPO / "tests" / "fixtures" / "llm" / "ollama"

ROOT = "http://localhost:11434"
CHAT_URL = f"{ROOT}/api/chat"
THINKER = "qwen3:8b"  # /api/show lists `thinking`
PLAIN = "llama3.1:8b"  # it does not

MESSAGES = [
    {"role": "system", "content": "Answer in one short sentence."},
    {"role": "user", "content": "What season is it?"},
]

SCHEMA = {
    "name": "shaping_test",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["answer"],
        "properties": {"answer": {"enum": ["spring", "autumn"]}},
    },
}

#: The profile defaults (engine/llm/profiles.py): content, reasoning.
BIG = (1200, 3200)
SMALL = (900, 800)


def _real_is_available() -> Any:
    """
    ``OllamaClient.is_available`` as written, taken at import -- collection,
    before any test's conftest pin is up (``tests/llm_golden.py`` takes
    ``NativeClient``'s the same way). None at BASE, where there is no client.
    """
    try:
        from engine.llm.ollama import OllamaClient
    except ImportError:
        return None
    method = OllamaClient.__dict__["is_available"]
    assert method.__name__ == "is_available", "imported under a pin"
    return method


_REAL_IS_AVAILABLE = _real_is_available()


def _fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _ok(body: Any) -> dict[str, Any]:
    return {"status": 200, "json": body}


def discovery() -> list[dict[str, Any]]:
    """What discovery asks Ollama, in order: tags, ps, then show per model."""
    return [
        _ok(_fixture("models_tags.json")),
        _ok(_fixture("models_ps.json")),
        _ok(_fixture("models_show_qwen3.json")),
        _ok(_fixture("models_show_llama.json")),
        _ok(_fixture("models_show_nomic.json")),
    ]


def answer(
    content: str = "Autumn.",
    *,
    thinking: str = "",
    done_reason: str = "stop",
    eval_count: int = 12,
    tool_calls: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """A non-streamed ``/api/chat`` answer."""
    message: dict[str, Any] = {"role": "assistant", "content": content}
    if thinking:
        message["thinking"] = thinking
    if tool_calls:
        message["tool_calls"] = tool_calls
    return _ok(
        {
            "model": THINKER,
            "created_at": "2026-09-29T12:00:00Z",
            "message": message,
            "done": True,
            "done_reason": done_reason,
            "prompt_eval_count": 40,
            "eval_count": eval_count,
        }
    )


def ndjson(name: str) -> dict[str, Any]:
    """A streamed answer: the fixture's lines, as Ollama writes them."""
    return {
        "status": 200,
        "text": (FIXTURES / name).read_text(encoding="utf-8"),
        "headers": {"content-type": "application/x-ndjson"},
    }


def configure(llm_server: Any, model: str = THINKER, **llm: Any) -> None:
    """Name Ollama, with both profiles on ``model``."""
    llm.setdefault("structured_output", "json_schema")
    llm.setdefault("profiles", {"big": {"model": model}, "small": {"model": model}})
    llm_server("ollama", **llm)


def chats(seam: Any) -> list[dict[str, Any]]:
    """The chat requests the seam saw, bodies parsed."""
    return [json.loads(r["body"]) for r in seam.requests if r["url"] == CHAT_URL]


def backend() -> Any:
    from engine.llm.backend import get_backend

    return get_backend()


def _chat_urls(seam: Any) -> list[str]:
    """Every chat POST's URL: discovery's /api/show POSTs left out."""
    return [r["url"] for r in seam.requests if r["method"] == "POST" and "show" not in r["url"]]


# -- the route --------------------------------------------------------------------


def test_every_ollama_request_goes_to_api_chat_never_the_compat_route(
    llm_server: Any,
) -> None:
    """FAILS AT BASE: the request went to ``/chat/completions`` on the compat client."""
    configure(llm_server)
    with wire(discovery() + [answer()], exhaust=True) as seam:
        result = backend().chat(MESSAGES, profile="big")
    chat_requests = [r for r in seam.requests if r["method"] == "POST" and "show" not in r["url"]]
    assert [r["url"] for r in chat_requests] == [CHAT_URL]
    assert not any("/chat/completions" in r["url"] or "/api/v1/" in r["url"] for r in seam.requests)
    assert result.content == "Autumn."
    assert result.transport == "ollama"


@pytest.mark.parametrize("profile", ["big", "small"])
@pytest.mark.parametrize("streamed", [False, True], ids=["chat", "stream"])
def test_num_ctx_is_always_sent_and_is_the_profiles_bound_context(
    llm_server: Any, profile: str, streamed: bool
) -> None:
    """
    THE GUARD AGAINST OLLAMA'S SILENT FRONT-TRUNCATION. Without ``num_ctx``
    Ollama runs a few thousand tokens and drops the start of a longer prompt
    -- the system persona first. It is on every request, and it is the number
    the prompt budget was sized against.
    """
    from engine.llm.profiles import resolve_profile

    configure(llm_server)
    reply = ndjson("chat_stream_thinking.ndjson") if streamed else answer()
    with wire(discovery() + [reply], exhaust=True) as seam:
        bound = resolve_profile(profile).context_tokens
        if streamed:
            list(backend().chat_stream(MESSAGES, profile=profile))
        else:
            backend().chat(MESSAGES, profile=profile)
    (body,) = chats(seam)
    assert body["options"]["num_ctx"] == bound == 8192
    assert body["stream"] is streamed


def test_a_declared_context_is_the_num_ctx_sent(llm_server: Any) -> None:
    from engine.llm.profiles import resolve_profile
    from engine.llm.registry import get_registry

    configure(llm_server, declared_models={THINKER: {"context": 32768}})
    with wire(discovery() + [answer()], exhaust=True) as seam:
        backend().chat(MESSAGES, profile="big")
        assert resolve_profile("big").context_tokens == 32768
        # Provenance: the number came from a declaration, not from the server.
        assert "context" in get_registry().cached(THINKER).declared_fields
    (body,) = chats(seam)
    assert body["options"]["num_ctx"] == 32768


# -- the request body -----------------------------------------------------------


def test_the_request_carries_messages_options_keep_alive_and_stream(llm_server: Any) -> None:
    configure(llm_server)
    with wire(discovery() + [answer()], exhaust=True) as seam:
        backend().chat(MESSAGES, profile="big", temperature=0.4)
    (body,) = chats(seam)
    assert body["model"] == THINKER
    # OpenAI roles pass through: /api/chat keeps per-message roles.
    assert body["messages"] == MESSAGES
    assert body["options"]["temperature"] == 0.4
    assert body["keep_alive"] == 900  # llm.keep_alive_seconds
    assert body["stream"] is False
    # LM Studio's keys never reach Ollama, and nor does the OpenAI envelope.
    for key in ("ttl", "max_tokens", "response_format", "tool_choice", "reasoning"):
        assert key not in body


def test_keep_alive_follows_the_config(llm_server: Any) -> None:
    configure(llm_server, keep_alive_seconds=120)
    with wire(discovery() + [answer()], exhaust=True) as seam:
        backend().chat(MESSAGES, profile="big")
    (body,) = chats(seam)
    assert body["keep_alive"] == 120


def test_keep_alive_zero_sends_nothing_so_ollamas_default_applies(llm_server: Any) -> None:
    """
    Fix round 1 (M2): in this config 0 means "send nothing", and the server's
    default applies -- NOT Ollama's own reading of ``keep_alive: 0``, which
    is "unload after this request" (config/default.yaml says so).
    """
    configure(llm_server, keep_alive_seconds=0)
    with wire(discovery() + [answer()], exhaust=True) as seam:
        backend().chat(MESSAGES, profile="big")
    (body,) = chats(seam)
    assert "keep_alive" not in body


def test_a_multimodal_content_array_is_sent_as_its_text(llm_server: Any) -> None:
    configure(llm_server)
    parts = [{"role": "user", "content": [{"type": "text", "text": "What "}, {"type": "text", "text": "season?"}]}]
    with wire(discovery() + [answer()], exhaust=True) as seam:
        backend().chat(parts, profile="big")
    (body,) = chats(seam)
    assert body["messages"] == [{"role": "user", "content": "What season?"}]


def test_tools_pass_through_and_tool_calls_come_back(llm_server: Any) -> None:
    configure(llm_server)
    tools = [
        {
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "The weather in a city.",
                "parameters": {"type": "object", "properties": {"city": {"type": "string"}}},
            },
        }
    ]
    recorded = _fixture("chat_tool_calls.json")
    assert recorded["request"]["tools"] == tools  # the recording offered the same tool
    with wire(discovery() + [recorded], exhaust=True) as seam:
        result = backend().chat(MESSAGES, profile="big", tools=tools, tool_choice="auto")
    (body,) = chats(seam)
    assert body["tools"] == tools
    assert "tool_choice" not in body  # /api/chat has no such key
    (call,) = result.tool_calls
    assert (call.name, call.arguments) == ("get_weather", {"city": "Tallowmere"})


def test_the_bearer_key_is_passed_through_when_one_is_set(llm_server: Any) -> None:
    """None locally; a reverse proxy in front of Ollama may want one."""
    configure(llm_server)
    with wire(discovery() + [answer()], exhaust=True) as seam:
        backend().chat(MESSAGES, profile="big")
    chat = next(r for r in seam.requests if r["url"] == CHAT_URL)
    assert chat["headers"]["authorization"] == "Bearer shaping-test-key"


def test_a_401_from_a_proxy_is_raised_with_its_words_logged(
    llm_server: Any, caplog: Any
) -> None:
    configure(llm_server)
    refused = {"status": 401, "json": _fixture("error_401.json")}
    with caplog.at_level(logging.ERROR), wire(discovery() + [refused], exhaust=True) as seam:
        with pytest.raises(httpx.HTTPStatusError):
            backend().chat(MESSAGES, profile="big")
    # The refusal came from /api/chat, and the Ollama client logged it (fix
    # round 1: without these two lines this passed at BASE, on compat).
    assert _chat_urls(seam) == [CHAT_URL]
    assert any(
        r.getMessage().startswith("[ollama]") and "unauthorized" in r.getMessage()
        for r in caplog.records
    )


# -- format: the ladder, and a caller's own response_format ------------------------


@pytest.mark.parametrize(
    "mode,expected",
    [("json_schema", SCHEMA["schema"]), ("json_object", "json"), ("off", None)],
)
def test_each_rung_goes_on_the_wire_as_format(
    llm_server: Any, mode: str, expected: Any
) -> None:
    configure(llm_server, structured_output=mode)
    response_format = backend().structured_output(SCHEMA)
    with wire(discovery() + [answer('{"answer": "autumn"}')], exhaust=True) as seam:
        backend().chat(MESSAGES, profile="big", response_format=response_format)
    (body,) = chats(seam)
    if expected is None:
        assert "format" not in body
    else:
        assert body["format"] == expected
    assert "response_format" not in body


def test_the_planners_grammar_is_translated_to_format(llm_server: Any) -> None:
    configure(llm_server)
    envelope = {"name": "agent_plan", "strict": True, "schema": SCHEMA["schema"]}
    response_format = backend().caller_format(envelope)
    with wire(discovery() + [answer('{"answer": "autumn"}')], exhaust=True) as seam:
        backend().chat(MESSAGES, profile="small", response_format=response_format, label="plan:x")
    (body,) = chats(seam)
    assert body["format"] == SCHEMA["schema"]


def test_author_py_s_envelope_is_translated_to_format(llm_server: Any) -> None:
    """``scripts/author.py`` builds ``{"type": "json_schema", "json_schema": envelope}`` itself."""
    from tests.llm_golden import AUTHOR_ENVELOPE, AUTHOR_REPLY, _load_script

    configure(llm_server)
    author = _load_script("author", REPO / "scripts" / "author.py").Author("clockwork-dark")
    with wire(discovery() + [answer(AUTHOR_REPLY)], exhaust=True) as seam:
        data = author._complete_json(
            "draft:item",
            [{"role": "user", "content": "Draft 1 item."}],
            AUTHOR_ENVELOPE,
            profile="small",
            max_tokens=1400,
        )
    (body,) = chats(seam)
    assert body["format"] == AUTHOR_ENVELOPE["schema"]
    assert data == json.loads(AUTHOR_REPLY)


def test_a_json_object_response_format_is_format_json(llm_server: Any) -> None:
    configure(llm_server)
    with wire(discovery() + [answer("{}")], exhaust=True) as seam:
        backend().chat(MESSAGES, profile="big", response_format={"type": "json_object"})
    (body,) = chats(seam)
    assert body["format"] == "json"


@pytest.mark.parametrize(
    "response_format",
    [
        {"type": "text"},
        {"type": "regex", "pattern": "a+"},
        {"type": "json_schema", "json_schema": {"name": "no_schema_here"}},
        {"json_schema": SCHEMA},
    ],
    ids=["text", "regex", "json_schema_without_a_schema", "no_type"],
)
def test_any_other_response_format_is_refused_naming_the_caller(
    llm_server: Any, caplog: Any, response_format: dict[str, Any]
) -> None:
    """Never silently dropped: a request whose grammar cannot be sent is not sent."""
    from engine.llm.ollama import UnsupportedResponseFormat

    configure(llm_server)
    with caplog.at_level(logging.ERROR), wire(discovery()) as seam:
        with pytest.raises(UnsupportedResponseFormat):
            backend().chat(
                MESSAGES, profile="big", response_format=response_format, label="author:draft:item"
            )
    assert chats(seam) == []
    assert "author:draft:item" in caplog.text
    assert issubclass(UnsupportedResponseFormat, ValueError)


# -- think, and the cap beside it ------------------------------------------------


def test_a_thinking_model_off_sends_think_false_untrusted_with_the_full_cap(
    llm_server: Any,
) -> None:
    """
    UNTRUSTED (v0.19.0 T8, measured): /api/show's ``thinking`` says a knob
    exists, not that the template honours ``think: false`` -- the library's
    own ``qwen3:4b`` reports it and thinks anyway
    (``chat_think_ignored.json``). So ``think: false`` goes, and the cap keeps
    the reasoning budget. At 10ded3c it was trusted, and the cap the content
    budget alone.
    """
    configure(llm_server)
    with wire(discovery() + [answer()], exhaust=True) as seam:
        backend().chat(MESSAGES, profile="small")
    (body,) = chats(seam)
    assert body["think"] is False
    assert body["options"]["num_predict"] == SMALL[0] + SMALL[1]


def test_a_declared_off_makes_think_false_trusted_and_the_cap_the_content_budget(
    llm_server: Any,
) -> None:
    """The owner's word that this model's template honours ``think: false``."""
    configure(llm_server, declared_models={THINKER: {"reasoning": ["off", "on"]}})
    with wire(discovery() + [answer()], exhaust=True) as seam:
        backend().chat(MESSAGES, profile="small")
    (body,) = chats(seam)
    assert body["think"] is False
    assert body["options"]["num_predict"] == SMALL[0]


def test_a_recorded_answer_that_ignored_think_false_reaches_the_caller_without_its_thinking(
    llm_server: Any,
) -> None:
    """
    Recorded (Ollama 0.34.4, qwen3:4b): under ``think: false`` the thinking
    arrives in ``message.content`` with no opening tag, then ``</think>``,
    then the answer. At 10ded3c the whole of it was the answer.
    """
    recorded = _fixture("chat_think_ignored.json")
    assert recorded["request"]["think"] is False
    assert "</think>" in recorded["json"]["message"]["content"]
    configure(llm_server)
    with wire(discovery() + [recorded], exhaust=True):
        result = backend().chat(MESSAGES, profile="small", retry_on_starvation=False)
    assert result.content == "4"
    assert "</think>" not in result.content and result.reasoning_content


def test_a_formatted_stream_to_an_untrusted_think_false_streams_as_it_arrives(
    llm_server: Any,
) -> None:
    """
    Fix round 1 (review finding 1): under ``format`` Ollama puts thinking in
    ``message.thinking`` (measured), never in the content, so the stream is
    not held. At 40f2de5 every line was held to the end.
    """
    configure(llm_server)
    pieces = ['{"answer": ', '"autu', 'mn"}']
    lines = [
        {"model": THINKER, "message": {"role": "assistant", "content": p}, "done": False}
        for p in pieces
    ] + [{"model": THINKER, "message": {"role": "assistant", "content": ""}, "done": True,
          "done_reason": "stop"}]
    stream = {
        "status": 200,
        "text": "".join(json.dumps(line) + "\n" for line in lines),
        "headers": {"content-type": "application/x-ndjson"},
    }
    response_format = backend().structured_output(SCHEMA)
    with wire(discovery() + [stream], exhaust=True) as seam:
        yielded = list(
            backend().chat_stream(MESSAGES, profile="small", response_format=response_format)
        )
    (body,) = chats(seam)
    assert body["think"] is False and "format" in body
    assert yielded == pieces


def test_a_recorded_stream_that_ignored_think_false_yields_only_the_answer(
    llm_server: Any,
) -> None:
    configure(llm_server)
    thought: list[str] = []
    with wire(discovery() + [ndjson("chat_stream_think_ignored.ndjson")], exhaust=True):
        yielded = list(
            backend().chat_stream(MESSAGES, profile="small", on_reasoning=thought.append)
        )
    assert "".join(yielded).strip() == "4"
    assert "".join(thought) and "</think>" not in "".join(thought)


def test_a_thinking_model_on_sends_think_true_and_pays_for_thinking(llm_server: Any) -> None:
    configure(llm_server)
    with wire(discovery() + [answer()], exhaust=True) as seam:
        backend().chat(MESSAGES, profile="big")
    (body,) = chats(seam)
    assert body["think"] is True
    assert body["options"]["num_predict"] == BIG[0] + BIG[1]


@pytest.mark.parametrize("profile", ["big", "small"])
def test_a_model_without_thinking_is_never_sent_think(llm_server: Any, profile: str) -> None:
    """
    ``think`` on a model whose /api/show lists no ``thinking`` is a 400 (the
    next test's fixture), the same class as LM Studio's "does not expose
    reasoning configuration". So it is omitted, in either mode.
    """
    configure(llm_server, model=PLAIN)
    with wire(discovery() + [answer()], exhaust=True) as seam:
        backend().chat(MESSAGES, profile=profile)
    (body,) = chats(seam)
    assert "think" not in body


# -- a declaration narrows what /api/show reports (fix round 1, I1) ---------------


def test_a_thinking_model_declared_untrusted_keeps_its_reasoning_budget_under_off(
    llm_server: Any, caplog: Any
) -> None:
    """
    ``reasoning_off_trusted: false``: the owner's word that this model may
    ignore ``think: false``. The patch still goes, but the cap keeps the
    reasoning budget (§5.2), and when it starves anyway it is never re-sent
    (§5.3). At 87a7055 /api/show's ``thinking`` made it trusted and the cap
    the content budget alone.
    """
    configure(llm_server, declared_models={THINKER: {"reasoning_off_trusted": False}})
    starved = _fixture("chat_starved.json")
    with caplog.at_level(logging.ERROR), wire(discovery() + [starved], exhaust=True) as seam:
        result = backend().chat(MESSAGES, profile="small")
    (body,) = chats(seam)
    assert body["think"] is False
    assert body["options"]["num_predict"] == SMALL[0] + SMALL[1]
    assert result.starved_by_reasoning


def test_a_model_declared_with_effort_levels_is_sent_its_level(llm_server: Any) -> None:
    """
    gpt-oss style (UNVERIFIED, checked live in T8): ``think`` takes
    ``"low" | "medium" | "high"`` and ``true``/``false`` are ignored. At
    87a7055 a ``high`` profile sent ``think: true``.
    """
    configure(
        llm_server,
        declared_models={THINKER: {"reasoning": ["low", "medium", "high"]}},
        profiles={"big": {"model": THINKER, "reasoning": "high"}, "small": {"model": THINKER}},
    )
    with wire(discovery() + [answer()], exhaust=True) as seam:
        backend().chat(MESSAGES, profile="big")
    (body,) = chats(seam)
    assert body["think"] == "high"
    assert body["options"]["num_predict"] == BIG[0] + BIG[1]


def test_an_effort_level_model_asked_for_off_is_sent_no_think_and_pays_for_thinking(
    llm_server: Any,
) -> None:
    """Its options have no ``off``: nothing can turn it off, so nothing claims to."""
    configure(llm_server, declared_models={THINKER: {"reasoning": ["low", "medium", "high"]}})
    starved = _fixture("chat_starved.json")
    with wire(discovery() + [starved], exhaust=True) as seam:
        result = backend().chat(MESSAGES, profile="small")
    (body,) = chats(seam)
    assert "think" not in body
    assert body["options"]["num_predict"] == SMALL[0] + SMALL[1]
    assert result.starved_by_reasoning  # stood down after one request


def test_a_declaration_never_grants_a_knob_ollama_did_not_report(llm_server: Any) -> None:
    configure(
        llm_server,
        model=PLAIN,
        declared_models={PLAIN: {"reasoning": ["off", "on"]}},
    )
    with wire(discovery() + [answer()], exhaust=True) as seam:
        backend().chat(MESSAGES, profile="small")
    (body,) = chats(seam)
    assert "think" not in body


def test_the_400_that_omitting_think_avoids_is_raised_with_the_servers_words(
    llm_server: Any, caplog: Any
) -> None:
    """
    What Ollama answers to ``think`` on a model without it. Should a model's
    capabilities change under a running engine, the refusal is logged with
    the server's own words and raised -- never a silent empty answer.
    """
    configure(llm_server, model=PLAIN)
    refused = _fixture("chat_error_think.json")
    with caplog.at_level(logging.ERROR), wire(discovery() + [refused], exhaust=True) as seam:
        with pytest.raises(httpx.HTTPStatusError):
            backend().chat(MESSAGES, profile="big")
    assert _chat_urls(seam) == [CHAT_URL]
    assert any(
        r.getMessage().startswith("[ollama]") and "does not support thinking" in r.getMessage()
        for r in caplog.records
    )


# -- the response ----------------------------------------------------------------


def test_the_answer_maps_onto_lmsresponse(llm_server: Any) -> None:
    """Recorded (Ollama 0.34.4, qwen3:4b, ``think: true``)."""
    configure(llm_server)
    recorded = _fixture("chat.json")
    body = recorded["json"]
    with wire(discovery() + [recorded], exhaust=True):
        result = backend().chat(MESSAGES, profile="big")
    assert result.content == body["message"]["content"] == "4"
    assert result.reasoning_content == body["message"]["thinking"]
    assert (result.input_tokens, result.output_tokens) == (
        body["prompt_eval_count"], body["eval_count"]
    )
    assert result.finish_reason == "stop"
    assert result.model == body["model"] == "qwen3:4b"


def test_inline_think_in_content_is_moved_to_the_reasoning_channel(llm_server: Any) -> None:
    configure(llm_server)
    reply = answer("<think>Maybe [IMAGE:forest].</think>\n\nAutumn.")
    with wire(discovery() + [reply], exhaust=True):
        result = backend().chat(MESSAGES, profile="big")
    assert result.content == "Autumn."
    assert "[IMAGE:forest]" in result.reasoning_content


def test_a_stream_with_thinking_yields_only_content(llm_server: Any) -> None:
    """
    The reasoning channel (``message.thinking``) goes to ``on_reasoning`` and
    the ``reasoning.*`` events, never to the generator: a model musing
    "[IMAGE:forest]" while thinking must not fire an image generation.
    Recorded (Ollama 0.34.4, qwen3:4b): one line per token.
    """
    lines = [
        json.loads(line)
        for line in (FIXTURES / "chat_stream_thinking.ndjson").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    said = [str(line["message"].get("content") or "") for line in lines]
    thought_recorded = "".join(str(line["message"].get("thinking") or "") for line in lines)
    done = lines[-1]
    configure(llm_server)
    events: list[Any] = []
    thought: list[str] = []
    shown: list[str] = []
    with wire(discovery() + [ndjson("chat_stream_thinking.ndjson")], exhaust=True):
        generator = backend().chat_stream(
            MESSAGES,
            profile="big",
            on_event=events.append,
            on_reasoning=thought.append,
            on_delta=shown.append,
        )
        yielded: list[str] = []
        try:
            while True:
                yielded.append(next(generator))
        except StopIteration as stop:
            result = stop.value
    assert yielded == [s for s in said if s] == shown
    assert "".join(yielded).strip() == "4"
    assert "".join(thought) == thought_recorded and len(thought_recorded) > 100
    kinds = [e.event_type for e in events]
    assert kinds[0] == "chat.start" and kinds[-1] == "chat.end"
    assert kinds.index("reasoning.end") < kinds.index("message.start")
    assert "".join(e.content for e in events if e.event_type == "message.delta") == "".join(said)
    assert result.content == "".join(said)
    assert result.reasoning_content == "".join(thought)
    assert (result.input_tokens, result.output_tokens, result.finish_reason) == (
        done["prompt_eval_count"], done["eval_count"], "stop"
    )
    assert events[-1].stats["finish_reason"] == "stop"


def test_a_streamed_inline_think_split_anywhere_is_reasoning(llm_server: Any) -> None:
    configure(llm_server)
    with wire(discovery() + [ndjson("chat_stream_inline_think.ndjson")], exhaust=True):
        generator = backend().chat_stream(MESSAGES, profile="big")
        yielded: list[str] = []
        try:
            while True:
                yielded.append(next(generator))
        except StopIteration as stop:
            result = stop.value
    assert "".join(yielded) == "Autumn."
    assert result.reasoning_content == "Perhaps [IMAGE:forest]."


def test_done_reason_length_with_no_content_reads_as_starved(llm_server: Any) -> None:
    configure(llm_server)
    with wire(discovery() + [_fixture("chat_starved.json")], exhaust=True):
        result = backend().chat(MESSAGES, profile="small", retry_on_starvation=False)
    assert result.finish_reason == "length"
    assert result.starved_by_reasoning


def test_an_error_line_mid_stream_is_raised_not_swallowed(llm_server: Any) -> None:
    configure(llm_server)
    broken = {
        "status": 200,
        "text": json.dumps({"model": THINKER, "message": {"role": "assistant", "content": "Au"}, "done": False})
        + "\n"
        + json.dumps({"error": "model runner has unexpectedly stopped"})
        + "\n",
        "headers": {"content-type": "application/x-ndjson"},
    }
    events: list[Any] = []
    with wire(discovery() + [broken], exhaust=True):
        with pytest.raises(RuntimeError, match="unexpectedly stopped"):
            list(backend().chat_stream(MESSAGES, profile="big", on_event=events.append))
    assert events[-1].event_type == "error"


def test_a_4xx_on_a_stream_is_logged_with_the_caller_and_raised(
    llm_server: Any, caplog: Any
) -> None:
    configure(llm_server)
    refused = _fixture("chat_error_think.json")
    events: list[Any] = []
    with caplog.at_level(logging.ERROR), wire(discovery() + [refused], exhaust=True) as seam:
        with pytest.raises(httpx.HTTPStatusError):
            list(backend().chat_stream(MESSAGES, profile="big", on_event=events.append))
    assert _chat_urls(seam) == [CHAT_URL]
    assert events[-1].event_type == "error"
    refusal = next(r.getMessage() for r in caplog.records if "refused" in r.getMessage())
    assert refusal.startswith("[ollama]")
    assert "caller=big" in refusal and "does not support thinking" in refusal


def test_tool_calls_on_a_streamed_line_are_collected(llm_server: Any) -> None:
    configure(llm_server)
    call = {"function": {"name": "get_weather", "arguments": {"city": "Tallowmere"}}}
    lines = [
        {"model": THINKER, "message": {"role": "assistant", "content": "", "tool_calls": [call]}, "done": False},
        {"model": THINKER, "message": {"role": "assistant", "content": ""}, "done": True, "done_reason": "stop"},
    ]
    stream = {
        "status": 200,
        "text": "".join(json.dumps(line) + "\n" for line in lines),
        "headers": {"content-type": "application/x-ndjson"},
    }
    with wire(discovery() + [stream], exhaust=True):
        generator = backend().chat_stream(MESSAGES, profile="big")
        try:
            while True:
                next(generator)
        except StopIteration as stop:
            result = stop.value
    (tool,) = result.tool_calls
    assert (tool.name, tool.arguments) == ("get_weather", {"city": "Tallowmere"})


def test_a_stream_that_closes_without_done_reads_as_truncated(
    llm_server: Any, caplog: Any
) -> None:
    """Fix round 1: at 87a7055 its finish reason was "", so a cut stream read as finished."""
    configure(llm_server)
    cut = {
        "status": 200,
        "text": json.dumps({"model": THINKER, "message": {"role": "assistant", "content": "Autumn, by"}, "done": False})
        + "\n",
        "headers": {"content-type": "application/x-ndjson"},
    }
    with caplog.at_level(logging.WARNING), wire(discovery() + [cut], exhaust=True):
        generator = backend().chat_stream(MESSAGES, profile="big")
        try:
            while True:
                next(generator)
        except StopIteration as stop:
            result = stop.value
    assert result.content == "Autumn, by"
    assert result.truncated and result.finish_reason == "length"
    assert "no `done` line" in caplog.text


# -- the starvation retry (spec §5.3) --------------------------------------------


def test_a_starved_request_without_think_false_retries_once_with_it(llm_server: Any) -> None:
    """Same request, same ``format``, plus ``think: false`` -- the grammar survives."""
    configure(llm_server)
    response_format = backend().structured_output(SCHEMA)
    starved = _fixture("chat_starved.json")
    with wire(discovery() + [starved, answer('{"answer": "autumn"}')], exhaust=True) as seam:
        result = backend().chat(MESSAGES, profile="big", response_format=response_format)
    first, retry = chats(seam)
    assert result.content == '{"answer": "autumn"}'
    assert first["think"] is True and retry["think"] is False
    assert retry["format"] == first["format"] == SCHEMA["schema"]
    assert retry["messages"] == first["messages"]
    assert retry["options"]["num_ctx"] == first["options"]["num_ctx"]
    # Untrusted (the model is undeclared): the cap still pays for thinking.
    assert retry["options"]["num_predict"] == BIG[0] + BIG[1]


def test_a_starved_request_that_carried_think_false_is_never_repeated(
    llm_server: Any, caplog: Any
) -> None:
    """Ollama reports no reasoning-token count, so there is no room to measure: stand down."""
    configure(llm_server)
    starved = _fixture("chat_starved.json")
    with caplog.at_level(logging.ERROR), wire(discovery() + [starved], exhaust=True) as seam:
        result = backend().chat(MESSAGES, profile="small")
    (only,) = chats(seam)
    assert only["think"] is False
    assert result.starved_by_reasoning
    assert "llm.declared_models" in caplog.text or "max_tokens" in caplog.text


def test_a_starved_model_without_thinking_stands_down_after_one_request(
    llm_server: Any,
) -> None:
    """Nothing can say ``think: false`` to it, and nothing re-sends the same request."""
    configure(llm_server, model=PLAIN)
    starved = _fixture("chat_starved.json")
    with wire(discovery() + [starved], exhaust=True) as seam:
        result = backend().chat(MESSAGES, profile="big")
    assert len(chats(seam)) == 1
    assert result.starved_by_reasoning


# -- the storyteller: stream, recovery and rule 1 --------------------------------


@pytest.fixture
def flagship() -> Any:
    from engine.games import registry

    registry.activate("clockwork-dark")
    try:
        yield
    finally:
        registry.deactivate()


ENVELOPE = json.dumps(
    {
        "narration": "The path east narrows between birches, and a clock ticks ahead.",
        "choices": [{"id": "a", "text": "Follow it"}, {"id": "b", "text": "Wait"}],
    }
)


def _agent() -> Any:
    from engine.agents.storyteller import StorytellerAgent
    from engine.game.engine import GameEngine
    from engine.game.procgen import new_game_state

    return StorytellerAgent(GameEngine(new_game_state(seed=7)))


def test_a_streamed_turn_that_starved_recovers_with_think_false_and_its_grammar(
    llm_server: Any, flagship: Any
) -> None:
    configure(llm_server)
    answers = discovery() + [ndjson("chat_stream_starved.ndjson"), answer(ENVELOPE)]
    with wire(answers, exhaust=True) as seam:
        generation = _agent()._infer([dict(m) for m in MESSAGES], on_delta=lambda _t: None)
    stream, recovery = chats(seam)
    assert stream["stream"] is True and recovery["stream"] is False
    assert stream["think"] is True and recovery["think"] is False
    assert recovery["format"] == stream["format"]
    assert recovery["format"]["type"] == "object"  # the turn schema itself
    assert recovery["messages"] == stream["messages"]
    assert generation.raw == ENVELOPE


def test_a_streamed_turn_that_starved_with_think_false_is_never_resent(
    llm_server: Any, flagship: Any
) -> None:
    configure(
        llm_server,
        profiles={"big": {"model": THINKER, "reasoning": "off"}, "small": {"model": THINKER}},
    )
    with wire(discovery() + [ndjson("chat_stream_starved.ndjson")], exhaust=True) as seam:
        generation = _agent()._infer([dict(m) for m in MESSAGES], on_delta=lambda _t: None)
    (only,) = chats(seam)
    assert only["think"] is False
    assert generation.raw == ""


LEGAL = {
    "id": "a",
    "text": "Head for the village square",
    "intent": {"action": "travel", "target": "edgewood_square"},
}
UNREACHABLE = {
    "id": "b",
    "text": "March straight to Millhaven's gate",
    "intent": {"action": "travel", "target": "millhaven_gate"},
}
NARRATION = (
    "The path east narrows between the birches, and somewhere ahead a clock "
    "ticks in the dark. The air smells of oil and cold iron. The bark is scored "
    "with marks that look deliberate, as if someone counted the hours here, and "
    "you keep walking while the ticking keeps pace with you, step for step."
)


@pytest.mark.parametrize("mode", ["json_schema", "json_object", "off"])
def test_rule_1_holds_on_the_ollama_transport_on_every_rung(
    llm_server: Any, flagship: Any, mode: str
) -> None:
    """
    An unoffered road is never offered, and neither a ``tool_calls`` key in
    the envelope nor ``message.tool_calls`` on the answer moves anyone: the
    reply is conformed on every rung, and narration executes no tool calls.
    """
    configure(llm_server, structured_output=mode)
    agent = _agent()
    before = agent.engine.state.location_id
    envelope = json.dumps(
        {
            "narration": NARRATION,
            "choices": [LEGAL, UNREACHABLE],
            "tool_calls": [{"name": "move_to", "args": {"location_id": "millhaven_gate"}}],
        }
    )
    walk = [{"function": {"name": "move_to", "arguments": {"location_id": "millhaven_gate"}}}]
    reply = answer(envelope, tool_calls=walk)
    with wire(discovery() + [reply, reply]) as seam:
        result = agent.run_turn("I look east.")
    first = chats(seam)[0]
    if mode == "json_schema":
        assert first["format"]["type"] == "object"
    elif mode == "json_object":
        assert first["format"] == "json"
    else:
        assert "format" not in first
    assert "tools" not in first  # a narration turn sends none, on any provider
    offered = [c["intent"] for c in result.choices if c.get("intent")]
    assert offered == [LEGAL["intent"]]
    assert UNREACHABLE["text"] not in json.dumps(result.to_dict())
    assert agent.engine.state.location_id == before
    assert result.tool_receipts == []


def test_rule_1_a_streamed_turns_tool_calls_move_nobody(
    llm_server: Any, flagship: Any
) -> None:
    """
    The streamed turn: a ``message.tool_calls`` walk arrives on an NDJSON
    line beside the narration. It is collected on the response and executed
    by nothing -- narration's only channel is the intent.
    """
    configure(llm_server)
    agent = _agent()
    before = agent.engine.state.location_id
    envelope = json.dumps({"narration": NARRATION, "choices": [LEGAL, {"id": "b", "text": "Wait"}]})
    walk = [{"function": {"name": "move_to", "arguments": {"location_id": "millhaven_gate"}}}]
    lines = [
        {"model": THINKER, "message": {"role": "assistant", "content": envelope}, "done": False},
        {"model": THINKER, "message": {"role": "assistant", "content": "", "tool_calls": walk}, "done": False},
        {"model": THINKER, "message": {"role": "assistant", "content": ""}, "done": True, "done_reason": "stop"},
    ]
    stream = {
        "status": 200,
        "text": "".join(json.dumps(line) + "\n" for line in lines),
        "headers": {"content-type": "application/x-ndjson"},
    }
    shown: list[str] = []
    with wire(discovery() + [stream, answer(envelope), answer(envelope)]) as seam:
        result = agent.run_turn("I look east.", on_delta=shown.append)
    assert chats(seam)[0]["stream"] is True
    assert "tools" not in chats(seam)[0]
    assert shown  # it streamed
    assert agent.engine.state.location_id == before
    assert result.tool_receipts == []


def test_the_constraint_won_probe_goes_to_api_chat_as_format(llm_server: Any) -> None:
    """``auto``: the probe schema is sent as ``format``, and a reply that obeyed it passes."""
    from engine.llm.backend import CONSTRAINT_PROBE_SCHEMA, RUNG_SCHEMA

    configure(llm_server, structured_output="auto")
    with wire(discovery() + [_fixture("chat_json_schema.json")], exhaust=True) as seam:
        assert backend().structured_rung() == RUNG_SCHEMA
    (probe,) = chats(seam)
    assert probe["format"] == CONSTRAINT_PROBE_SCHEMA


def test_the_probes_ask_for_no_thinking(llm_server: Any) -> None:
    """
    Measured live (v0.19.0 T8): ``qwen3:4b`` probed with ``think: true``
    thought 13k characters past the probe's cap, and both probes failed -- a
    server that enforces ``format`` was put on rung 3. ``think: false`` beside
    the grammar binds it from the first token (measured, 10 tokens). At
    10ded3c the probe sent ``think: true``.
    """
    from engine.llm.backend import RUNG_OBJECT

    configure(llm_server, structured_output="auto")
    answers = discovery() + [
        _ok(_fixture("chat_probe_ignored.json")),
        answer('{"sky": "orange"}'),
    ]
    with wire(answers, exhaust=True) as seam:
        assert backend().structured_rung() == RUNG_OBJECT
    schema_probe, object_probe = chats(seam)
    assert schema_probe["think"] is False and object_probe["think"] is False


def test_a_probe_answer_that_ignored_the_grammar_falls_to_json_object(llm_server: Any) -> None:
    from engine.llm.backend import RUNG_OBJECT

    configure(llm_server, structured_output="auto")
    answers = discovery() + [
        _ok(_fixture("chat_probe_ignored.json")),
        answer('{"sky": "orange"}'),
    ]
    with wire(answers, exhaust=True) as seam:
        assert backend().structured_rung() == RUNG_OBJECT
    schema_probe, object_probe = chats(seam)
    assert schema_probe["format"]["additionalProperties"] is False
    assert object_probe["format"] == "json"


# -- is_available, and the client's lifetime ---------------------------------------


def test_is_available_asks_the_version_route(llm_server: Any, monkeypatch: Any) -> None:
    """
    The real method (the conftest pins it False for every other test): the
    ``ollama`` row's health probe since v0.19.0 T6 (spec §8, "the same
    probe"): a ``{"version": ...}`` body and then a model list is served; an
    error body, a 404 or a closed port on the version route is not, and the
    list is then never asked.
    """
    from engine.llm import ollama

    monkeypatch.setattr(ollama.OllamaClient, "is_available", _REAL_IS_AVAILABLE)
    configure(llm_server)
    client = ollama.OllamaClient()
    answers = [
        _ok(_fixture("version.json")),
        _ok(_fixture("models_tags.json")),
        _ok(_fixture("models_error.json")),
        {"status": 404, "text": "404 page not found"},
        {"raise": "ConnectError", "message": "refused"},
    ]
    with wire(answers, exhaust=True) as seam:
        assert [client.is_available() for _ in range(4)] == [True, False, False, False]
    assert [r["url"] for r in seam.requests] == [
        f"{ROOT}/api/version", f"{ROOT}/api/tags", *[f"{ROOT}/api/version"] * 3
    ]


def test_a_config_reload_rebuilds_the_ollama_client(llm_server: Any) -> None:
    from engine.llm.ollama import get_ollama_client

    configure(llm_server)
    first = get_ollama_client()
    assert first.root == ROOT
    configure(llm_server, base_url="http://gpu-box.lan:11434")
    second = get_ollama_client()
    assert second is not first
    assert second.root == "http://gpu-box.lan:11434"
