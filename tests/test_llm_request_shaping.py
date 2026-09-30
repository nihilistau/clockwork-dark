"""
Request shaping on the OpenAI-compatible route, per provider (spec §4-§5).

Every request here goes through ``tests/llm_wire.py`` (the ``httpx`` transport
seam), after real discovery against each server's own fixture list, so the
body asserted is the body the engine would send. No socket opens; the
conftest guard stays up.

What is pinned, per ``compat`` provider (vLLM, llama-server, a generic
OpenAI-compatible server):

* the structured-output ladder: rung 1 (``json_schema``), rung 2 (the row's
  ``json_object``), rung 3 (nothing), in each row's wire form;
* the reasoning-off patch for each reasoning mode, and the wire cap beside
  it: the reasoning budget is dropped ONLY when the patch is trusted (a
  declaration listing ``off``, or ``llm.reasoning_off_body``); an untrusted
  patch keeps the full "on" cap;
* keep-alive: LM Studio's ``ttl`` goes to LM Studio only;
* the starvation retry: the same request plus the patch, grammar kept, when
  the starved one lacked it; never a repeat of a request that already
  carried it -- measured room, else stand down with one request sent.

LM Studio's own requests are the golden's (``tests/test_llm_golden_lmstudio.py``);
the one LM Studio case here is that its compat route carries no patch.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import pytest

from tests.llm_golden import _models
from tests.llm_wire import wire

pytestmark = pytest.mark.real_discovery

REPO = Path(__file__).resolve().parents[1]
FIXTURES = REPO / "tests" / "fixtures" / "llm"

#: Each compat row's discovery answers (in request order) and its model id.
SERVERS: dict[str, tuple[list[str], str]] = {
    "vllm": (["vllm/models.json"], "Qwen/Qwen3-8B"),
    "llamacpp": (
        ["llamacpp/models.json", "llamacpp/models_props.json"],
        "Qwen3-4B-Thinking-2507-Q4_K_M.gguf",
    ),
    "openai_compat": (["openai_compat/models.json"], "house-narrator"),
}

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
THINKING_OFF = {"chat_template_kwargs": {"enable_thinking": False}}


def _fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def discovery(provider: str) -> list[dict[str, Any]]:
    """The canned answers discovery asks for, in order."""
    return [{"status": 200, "json": _fixture(name)} for name in SERVERS[provider][0]]


def model_of(provider: str) -> str:
    return SERVERS[provider][1]


def chat_answer(
    content: str,
    *,
    model: str = "served-model",
    finish: str = "stop",
    reasoning_tokens: int | None = None,
    completion_tokens: int = 12,
) -> dict[str, Any]:
    """A non-streamed ``/v1/chat/completions`` answer."""
    usage: dict[str, Any] = {
        "prompt_tokens": 40,
        "completion_tokens": completion_tokens,
        "total_tokens": 40 + completion_tokens,
    }
    if reasoning_tokens is not None:
        usage["completion_tokens_details"] = {"reasoning_tokens": reasoning_tokens}
    return {
        "status": 200,
        "json": {
            "id": "chatcmpl-shaping",
            "object": "chat.completion",
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": finish,
                }
            ],
            "usage": usage,
        },
    }


def configure(llm_server: Any, provider: str, **llm: Any) -> None:
    """Name ``provider``, with both profiles on its one model."""
    model = model_of(provider)
    profiles = {"big": {"model": model}, "small": {"model": model}}
    llm.setdefault("structured_output", "json_schema")
    llm_server(provider, profiles=profiles, **llm)


def chats(seam: Any) -> list[dict[str, Any]]:
    """The chat requests the seam saw, bodies parsed."""
    return [
        json.loads(r["body"]) for r in seam.requests if r["url"].endswith("/chat/completions")
    ]


def backend():
    from engine.llm.backend import get_backend

    return get_backend()


# -- the ladder, in each row's wire form ---------------------------------------------


@pytest.mark.parametrize("provider", sorted(SERVERS))
@pytest.mark.parametrize(
    "mode,expected",
    [
        ("json_schema", {"type": "json_schema", "json_schema": SCHEMA}),
        ("json_object", {"type": "json_object"}),
        ("off", None),
    ],
)
def test_each_rung_goes_on_the_wire_in_the_rows_form(
    llm_server: Any, provider: str, mode: str, expected: Any
) -> None:
    configure(llm_server, provider, structured_output=mode)
    response_format = backend().structured_output(SCHEMA)
    assert response_format == expected
    with wire(discovery(provider) + [chat_answer('{"answer": "autumn"}')], exhaust=True) as seam:
        backend().chat(MESSAGES, profile="big", response_format=response_format)
    (body,) = chats(seam)
    if expected is None:
        assert "response_format" not in body
    else:
        assert body["response_format"] == expected
    # A compat row never asks LM Studio's native route anything.
    assert not any("/api/v1/" in r["url"] for r in seam.requests)


def test_lm_studios_json_object_rung_is_still_the_permissive_schema(llm_server: Any) -> None:
    """LM Studio rejects {"type": "json_object"}; its rung 2 is v0.18's form."""
    llm_server("lmstudio", structured_output="json_object")
    emitted = backend().structured_output(SCHEMA)
    assert emitted["type"] == "json_schema"
    assert emitted["json_schema"]["schema"] == {"type": "object", "additionalProperties": True}


def test_a_compat_row_never_takes_the_native_route(llm_server: Any) -> None:
    """``use_native`` asks the row: only ``lmstudio_routed`` has /api/v1/chat."""
    configure(llm_server, "vllm")
    b = backend()
    b.native_available = lambda: True  # type: ignore[method-assign]
    assert b.use_native() is False
    assert b.use_native(integrations=[{"type": "ephemeral_mcp"}]) is False


# -- reasoning: the patch, trusted or not, and the cap beside it --------------------


@pytest.mark.parametrize("provider", ["vllm", "llamacpp"])
def test_an_undeclared_models_off_request_carries_the_patch_and_the_full_on_cap(
    llm_server: Any, provider: str
) -> None:
    """
    UNTRUSTED: nothing says this template honours ``enable_thinking``, so the
    patch is sent (it may help) but the cap still pays for thinking. Dropping
    the budget here would starve a model that ignores it on every turn, with
    no reasoning count to size a retry from. An answer from a template that
    ignored it is read knowing so (``tests/test_llm_inline_think.py``).
    """
    configure(llm_server, provider)
    with wire(discovery(provider) + [chat_answer("Autumn.")], exhaust=True) as seam:
        backend().chat(MESSAGES, profile="small")
    (body,) = chats(seam)
    assert body["chat_template_kwargs"] == {"enable_thinking": False}
    assert body["max_tokens"] == SMALL[0] + SMALL[1]


@pytest.mark.parametrize("provider", ["vllm", "llamacpp"])
def test_a_declared_off_makes_the_patch_trusted_and_the_cap_the_content_budget(
    llm_server: Any, provider: str
) -> None:
    configure(
        llm_server,
        provider,
        declared_models={model_of(provider): {"reasoning": ["off", "on"]}},
    )
    with wire(discovery(provider) + [chat_answer("Autumn.")], exhaust=True) as seam:
        backend().chat(MESSAGES, profile="small")
    (body,) = chats(seam)
    assert body["chat_template_kwargs"] == {"enable_thinking": False}
    assert body["max_tokens"] == SMALL[0]


@pytest.mark.parametrize("provider", ["vllm", "llamacpp"])
def test_a_declaration_without_off_sends_no_patch(llm_server: Any, provider: str) -> None:
    configure(
        llm_server, provider, declared_models={model_of(provider): {"reasoning": ["on"]}}
    )
    with wire(discovery(provider) + [chat_answer("Autumn.")], exhaust=True) as seam:
        backend().chat(MESSAGES, profile="small")
    (body,) = chats(seam)
    assert "chat_template_kwargs" not in body
    assert body["max_tokens"] == SMALL[0] + SMALL[1]


@pytest.mark.parametrize("provider", sorted(SERVERS))
def test_reasoning_on_sends_nothing_and_pays_for_thinking(llm_server: Any, provider: str) -> None:
    configure(llm_server, provider)
    with wire(discovery(provider) + [chat_answer("Autumn.")], exhaust=True) as seam:
        backend().chat(MESSAGES, profile="big")
    (body,) = chats(seam)
    assert set(body) == {"model", "messages", "temperature", "max_tokens", "stream"}
    assert body["max_tokens"] == BIG[0] + BIG[1]


def test_a_generic_server_turns_nothing_off_unless_the_owner_declares_a_body(
    llm_server: Any,
) -> None:
    configure(llm_server, "openai_compat")
    with wire(discovery("openai_compat") + [chat_answer("Autumn.")], exhaust=True) as seam:
        backend().chat(MESSAGES, profile="small")
    (body,) = chats(seam)
    assert set(body) == {"model", "messages", "temperature", "max_tokens", "stream"}
    assert body["max_tokens"] == SMALL[0] + SMALL[1]


def test_a_declared_reasoning_off_body_is_sent_and_trusted(llm_server: Any) -> None:
    patch = {"reasoning": {"effort": "none"}}
    configure(llm_server, "openai_compat", reasoning_off_body=patch)
    with wire(discovery("openai_compat") + [chat_answer("Autumn.")], exhaust=True) as seam:
        backend().chat(MESSAGES, profile="small")
    (body,) = chats(seam)
    assert body["reasoning"] == {"effort": "none"}
    assert body["max_tokens"] == SMALL[0]


def test_lm_studios_compat_route_carries_no_patch_and_keeps_its_ttl(llm_server: Any) -> None:
    """The route ignores every knob (v0.18), so nothing is sent and the cap pays."""
    llm_server("lmstudio", structured_output="json_schema")
    with wire([_models(), chat_answer("Autumn.")], exhaust=True) as seam:
        backend().chat(MESSAGES, profile="small")
    (body,) = chats(seam)
    assert "chat_template_kwargs" not in body and "reasoning" not in body
    assert body["max_tokens"] == SMALL[0] + SMALL[1]
    assert body["ttl"] == 900


@pytest.mark.parametrize("provider", sorted(SERVERS))
def test_ttl_is_lm_studios_key_and_goes_nowhere_else(llm_server: Any, provider: str) -> None:
    configure(llm_server, provider)
    with wire(discovery(provider) + [chat_answer("Autumn.")], exhaust=True) as seam:
        backend().chat(MESSAGES, profile="big")
    (body,) = chats(seam)
    assert "ttl" not in body


def test_the_streamed_route_shapes_the_same_way(llm_server: Any) -> None:
    configure(llm_server, "vllm")
    frames = [
        {"data": {"choices": [{"index": 0, "delta": {"content": "Autumn."}}]}},
        {"data": {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}},
        {"data": "[DONE]"},
    ]
    with wire(discovery("vllm") + [{"status": 200, "sse": frames}], exhaust=True) as seam:
        generator = backend().chat_stream(MESSAGES, profile="small")
        assert "".join(generator) == "Autumn."
    (body,) = chats(seam)
    assert body["stream"] is True
    assert body["chat_template_kwargs"] == {"enable_thinking": False}
    assert body["max_tokens"] == SMALL[0] + SMALL[1]
    assert "ttl" not in body


# -- the planner (finding 4) -----------------------------------------------------------


@pytest.fixture
def neon_city() -> Any:
    from engine.games import registry

    registry.activate("neon-city")
    try:
        yield
    finally:
        registry.deactivate()


def _plan(llm_server: Any, mode: str, reply: str) -> tuple[Any, dict[str, Any]]:
    """neon-city's ``the_line`` plans once on vLLM under ``mode``."""
    from engine.agents.planner import plan_for
    from engine.agents.roster import load_roster
    from engine.game.procgen import new_game_state

    configure(llm_server, "vllm", structured_output=mode)
    roster = load_roster(REPO / "games" / "neon-city" / "agents.yaml", slug="neon-city")
    spec, state = roster.get("the_line"), new_game_state(seed=5)
    with wire(discovery("vllm") + [chat_answer(reply)], exhaust=True) as seam:
        plan = plan_for(spec, state, "I ask the line what it wants.")
    (body,) = chats(seam)
    return plan, body


PLAN = json.dumps(
    {"intent": "speak", "beat": "the line hums, interested", "line": "Everyone wants passage."}
)


def test_the_planners_grammar_rides_the_ladder_off_lm_studio_rung_1(
    llm_server: Any, neon_city: Any
) -> None:
    plan, body = _plan(llm_server, "json_schema", PLAN)
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["name"] == "agent_plan"
    assert "OUTPUT FORMAT" not in json.dumps(body["messages"])
    assert plan.intent == "speak"


def test_on_rung_3_the_planner_sends_no_grammar_and_its_parse_failure_answers(
    llm_server: Any, neon_city: Any
) -> None:
    """
    Nothing on the wire, the shape in the prompt instead -- and a model that
    answers in prose gets the planner's own parse-failure path: a silent plan.
    """
    plan, body = _plan(llm_server, "off", "The line hums and wants passage.")
    assert "response_format" not in body
    system = body["messages"][0]["content"]
    assert "OUTPUT FORMAT" in system and '"intent"' in system
    from engine.agents.plan import INTENT_SILENT

    assert plan.intent == INTENT_SILENT and not plan.beat


# -- the starvation retry (spec §5.3) -------------------------------------------------


STARVED = dict(finish="length", completion_tokens=4400)


@pytest.mark.parametrize("provider", ["vllm", "llamacpp"])
def test_a_starved_request_without_the_patch_retries_with_it_and_keeps_the_grammar(
    llm_server: Any, provider: str
) -> None:
    configure(llm_server, provider)
    response_format = backend().structured_output(SCHEMA)
    answers = discovery(provider) + [
        chat_answer("", **STARVED),
        chat_answer('{"answer": "autumn"}'),
    ]
    with wire(answers, exhaust=True) as seam:
        result = backend().chat(MESSAGES, profile="big", response_format=response_format)
    first, retry = chats(seam)
    assert result.content == '{"answer": "autumn"}'
    assert "chat_template_kwargs" not in first
    assert retry["chat_template_kwargs"] == {"enable_thinking": False}
    # The grammar survives the retry -- the thing LM Studio's retry cannot do.
    assert retry["response_format"] == first["response_format"] == {
        "type": "json_schema",
        "json_schema": SCHEMA,
    }
    # Untrusted patch: the cap still pays for thinking (§5.2).
    assert retry["max_tokens"] == BIG[0] + BIG[1]
    assert retry["messages"] == first["messages"]


def test_a_trusted_retry_spends_the_whole_cap_on_the_answer(llm_server: Any) -> None:
    configure(
        llm_server, "vllm", declared_models={"Qwen/Qwen3-8B": {"reasoning": ["off", "on"]}}
    )
    answers = discovery("vllm") + [chat_answer("", **STARVED), chat_answer("Autumn.")]
    with wire(answers, exhaust=True) as seam:
        backend().chat(MESSAGES, profile="big")
    _first, retry = chats(seam)
    assert retry["chat_template_kwargs"] == {"enable_thinking": False}
    assert retry["max_tokens"] == BIG[0]


@pytest.mark.parametrize("provider", ["vllm", "llamacpp"])
def test_a_starved_request_that_carried_the_patch_is_never_repeated(
    llm_server: Any, provider: str, caplog: Any
) -> None:
    """
    It already said ``off``. These servers report no reasoning-token count, so
    measured room has nothing to size from: the backend stands down at once,
    and exactly one chat request went out.
    """
    configure(llm_server, provider)
    with caplog.at_level(logging.ERROR), wire(
        discovery(provider) + [chat_answer("", **STARVED)], exhaust=True
    ) as seam:
        result = backend().chat(MESSAGES, profile="small")
    assert len(chats(seam)) == 1
    assert chats(seam)[0]["chat_template_kwargs"] == {"enable_thinking": False}
    assert result.starved_by_reasoning
    # The advice fits what happened (v0.19.0 T6, T5 re-review N2, T8 fix round
    # 1): the patch WAS sent, untrusted -- the model is undeclared, so the cap
    # already kept its reasoning budget -- and did not take. Room or another
    # template can help; marking it untrusted (it already is) and a generic
    # server's body patch cannot. At 40f2de5 it advised reasoning_off_trusted.
    for fix in ("max_tokens", "reasoning_budget", "already carried", "untrusted"):
        assert fix in caplog.text
    assert "reasoning_off_trusted" not in caplog.text
    assert "llm.reasoning_off_body" not in caplog.text


def test_a_starved_request_that_carried_a_trusted_patch_advises_the_untrusted_mark(
    llm_server: Any, caplog: Any
) -> None:
    """A declared (trusted) patch that did not take: the cap dropped the budget, so the mark helps."""
    configure(
        llm_server, "vllm", declared_models={"Qwen/Qwen3-8B": {"reasoning": ["off", "on"]}}
    )
    with caplog.at_level(logging.ERROR), wire(
        discovery("vllm") + [chat_answer("", **STARVED)], exhaust=True
    ) as seam:
        result = backend().chat(MESSAGES, profile="small")
    assert len(chats(seam)) == 1
    assert result.starved_by_reasoning
    assert "reasoning_off_trusted" in caplog.text and "max_tokens" in caplog.text


@pytest.mark.parametrize(
    ("provider", "profile"),
    # vLLM's `small` profile is `off`: the patch was carried. A generic
    # server's `big` has no patch to carry at all.
    [("vllm", "small"), ("openai_compat", "big")],
)
def test_an_empty_answer_is_not_advised_as_starvation(
    llm_server: Any, provider: str, profile: str, caplog: Any
) -> None:
    """
    T5 re-review N2. A response with no content, no reasoning and no tokens
    spent -- a stream cut before its done line, an empty answer -- is not a
    model thinking too long, and no declaration fixes it: the stand-down says
    what happened and advises no ``llm.declared_models`` entry. (Before
    v0.19.0 T6 it logged "Cannot recover from reasoning starvation ...
    Declare the model's `reasoning`".)
    """
    configure(llm_server, provider)
    empty = chat_answer("", finish="length", completion_tokens=0)
    with caplog.at_level(logging.ERROR), wire(discovery(provider) + [empty], exhaust=True):
        result = backend().chat(MESSAGES, profile=profile)
    assert result.starved_by_reasoning  # truncated and empty, as the backend sees it
    stand_down = [r.getMessage() for r in caplog.records if r.name == "engine.llm.backend"]
    assert len(stand_down) == 1
    assert "done line" in stand_down[0]
    assert "starvation" not in stand_down[0]
    assert "llm.declared_models" not in stand_down[0]


def test_a_generic_server_with_no_patch_stands_down_after_one_request(
    llm_server: Any, caplog: Any
) -> None:
    configure(llm_server, "openai_compat")
    with caplog.at_level(logging.ERROR), wire(
        discovery("openai_compat") + [chat_answer("", **STARVED)], exhaust=True
    ) as seam:
        result = backend().chat(MESSAGES, profile="big")
    assert len(chats(seam)) == 1
    assert result.starved_by_reasoning
    assert "llm.reasoning_off_body" in caplog.text


def test_a_generic_server_that_reports_its_thinking_gets_measured_room(
    llm_server: Any,
) -> None:
    configure(llm_server, "openai_compat")
    response_format = backend().structured_output(SCHEMA)
    answers = discovery("openai_compat") + [
        chat_answer("", reasoning_tokens=4390, **STARVED),
        chat_answer('{"answer": "autumn"}'),
    ]
    with wire(answers, exhaust=True) as seam:
        result = backend().chat(MESSAGES, profile="big", response_format=response_format)
    first, retry = chats(seam)
    assert result.content == '{"answer": "autumn"}'
    assert retry["max_tokens"] == 4390 + BIG[0]
    assert retry["response_format"] == first["response_format"]


# -- the storyteller's STREAMED recovery goes through the same rules -------------------


@pytest.fixture
def flagship() -> Any:
    from engine.games import registry

    registry.activate("clockwork-dark")
    try:
        yield
    finally:
        registry.deactivate()


def starved_stream(*, reasoning_tokens: int | None = None) -> dict[str, Any]:
    """A streamed answer that spent the whole cap thinking: no content, ``length``."""

    def chunk(delta: dict[str, Any], finish: str | None = None) -> dict[str, Any]:
        return {"data": {"choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}}

    usage: dict[str, Any] = {"prompt_tokens": 800, "completion_tokens": 4400, "total_tokens": 5200}
    if reasoning_tokens is not None:
        usage["completion_tokens_details"] = {"reasoning_tokens": reasoning_tokens}
    return {
        "status": 200,
        "sse": [
            chunk({"role": "assistant", "content": ""}),
            chunk({"reasoning_content": "Thinking about the path, and the clock, and"}),
            chunk({}, "length"),
            {"data": {"choices": [], "usage": usage}},
            {"data": "[DONE]"},
        ],
    }


ENVELOPE = json.dumps(
    {
        "narration": "The path east narrows between birches, and a clock ticks ahead.",
        "choices": [{"id": "a", "text": "Follow it"}, {"id": "b", "text": "Wait"}],
    }
)


def _stream_turn(provider: str) -> tuple[Any, Any]:
    """One streamed ``Storyteller._infer`` on the flagship, and what it showed."""
    from engine.agents.storyteller import StorytellerAgent
    from engine.game.engine import GameEngine
    from engine.game.procgen import new_game_state

    agent = StorytellerAgent(GameEngine(new_game_state(seed=7)))
    shown: list[str] = []
    generation = agent._infer([dict(m) for m in MESSAGES], on_delta=shown.append)
    return generation, shown


def test_a_streamed_turn_that_starved_with_the_patch_is_never_resent(
    llm_server: Any, flagship: Any, caplog: Any
) -> None:
    """Narration with ``reasoning: off``: the stream carried the patch, so nothing follows it."""
    model = model_of("vllm")
    llm_server(
        "vllm",
        structured_output="json_schema",
        profiles={"big": {"model": model, "reasoning": "off"}, "small": {"model": model}},
    )
    with caplog.at_level(logging.ERROR), wire(
        discovery("vllm") + [starved_stream()], exhaust=True
    ) as seam:
        generation, _shown = _stream_turn("vllm")
    (only,) = chats(seam)
    assert only["stream"] is True
    assert only["chat_template_kwargs"] == {"enable_thinking": False}
    assert generation.raw == ""
    assert "reasoning_budget" in caplog.text and "untrusted" in caplog.text


def test_a_streamed_turn_that_starved_without_the_patch_recovers_with_it(
    llm_server: Any, flagship: Any
) -> None:
    configure(llm_server, "vllm")
    answers = discovery("vllm") + [starved_stream(), chat_answer(ENVELOPE)]
    with wire(answers, exhaust=True) as seam:
        generation, _shown = _stream_turn("vllm")
    stream, recovery = chats(seam)
    assert "chat_template_kwargs" not in stream
    assert recovery["chat_template_kwargs"] == {"enable_thinking": False}
    assert recovery["response_format"] == stream["response_format"]
    assert recovery["response_format"]["type"] == "json_schema"
    assert recovery["messages"] == stream["messages"]
    assert generation.raw == ENVELOPE


def test_a_generic_servers_starved_stream_stands_down_after_one_request(
    llm_server: Any, flagship: Any, caplog: Any
) -> None:
    """The shipped config on a generic server: no patch exists, so no identical resend."""
    configure(llm_server, "openai_compat")
    with caplog.at_level(logging.ERROR), wire(
        discovery("openai_compat") + [starved_stream()], exhaust=True
    ) as seam:
        generation, _shown = _stream_turn("openai_compat")
    assert len(chats(seam)) == 1
    assert generation.raw == ""
    assert "llm.reasoning_off_body" in caplog.text


def test_a_generic_servers_starved_stream_that_reported_its_thinking_gets_room(
    llm_server: Any, flagship: Any
) -> None:
    configure(llm_server, "openai_compat")
    answers = discovery("openai_compat") + [
        starved_stream(reasoning_tokens=4390),
        chat_answer(ENVELOPE),
    ]
    with wire(answers, exhaust=True) as seam:
        generation, _shown = _stream_turn("openai_compat")
    stream, room = chats(seam)
    assert room["max_tokens"] == 4390 + BIG[0]
    assert room["response_format"] == stream["response_format"]
    assert room["stream"] is False
    assert generation.raw == ENVELOPE


def test_a_generic_servers_declared_patch_is_the_retry(llm_server: Any) -> None:
    configure(llm_server, "openai_compat", reasoning_off_body={"think": False})
    answers = discovery("openai_compat") + [chat_answer("", **STARVED), chat_answer("Autumn.")]
    with wire(answers, exhaust=True) as seam:
        backend().chat(MESSAGES, profile="big")
    first, retry = chats(seam)
    assert "think" not in first
    assert retry["think"] is False
    assert retry["max_tokens"] == BIG[0]


# -- llama-server's recorded answers (b7966, v0.19.0 T8) ------------------------------
#
# Replayed through the real client after real discovery against the recorded
# list and /props. Each fixture holds the request that produced it under
# `request`; tests/fixtures/llm/PROVENANCE.yaml names the model and the date.


def _recorded(name: str) -> dict[str, Any]:
    return _fixture(f"llamacpp/{name}")


def test_a_verified_reasoning_off_cell_does_not_make_the_patch_trusted(
    llm_server: Any,
) -> None:
    """
    The llamacpp row's ``reasoning_off`` cell is verified live: llama-server
    passes the patch to the template. Whether the template HONOURS it is the
    model's -- recorded: Qwen3-0.6B's does, Qwen3-4B-Thinking-2507's does not
    -- so the cell cannot vouch for an undeclared model. Before v0.19.0 T8 a
    verified cell made every undeclared model's patch trusted, and the cap
    dropped its reasoning budget for a model that thinks anyway.
    """
    from engine.llm.providers import PROVIDERS

    assert PROVIDERS["llamacpp"].reasoning_off.verified
    configure(llm_server, "llamacpp")
    with wire(discovery("llamacpp") + [chat_answer("Autumn.")], exhaust=True) as seam:
        backend().chat(MESSAGES, profile="small")
    (body,) = chats(seam)
    assert body["chat_template_kwargs"] == {"enable_thinking": False}
    assert body["max_tokens"] == SMALL[0] + SMALL[1]


def test_llama_servers_recorded_answer_splits_its_reasoning_itself(llm_server: Any) -> None:
    """With ``--jinja`` and no ``--reasoning-format`` flag, b7966 splits it out."""
    configure(llm_server, "llamacpp")
    recorded = _recorded("chat.json")
    with wire(discovery("llamacpp") + [recorded], exhaust=True):
        result = backend().chat(MESSAGES, profile="big")
    message = recorded["json"]["choices"][0]["message"]
    assert result.content == message["content"] == "4"
    assert result.reasoning_content == message["reasoning_content"]
    assert result.finish_reason == "stop"
    assert result.output_tokens == recorded["json"]["usage"]["completion_tokens"]
    # llama-server reports no reasoning-token count: the §5.3 stand-down case.
    assert result.reasoning_tokens == 0


def test_llama_servers_recorded_stream_sends_reasoning_to_its_own_channel(
    llm_server: Any,
) -> None:
    configure(llm_server, "llamacpp")
    deltas: list[str] = []
    reasoning: list[str] = []
    with wire(discovery("llamacpp") + [_recorded("chat_stream_thinking.json")], exhaust=True):
        generator = backend().chat_stream(
            MESSAGES, profile="big", on_delta=deltas.append, on_reasoning=reasoning.append
        )
        yielded = list(generator)
    assert "".join(yielded) == "".join(deltas)
    assert "".join(deltas).strip() == "4"
    assert len("".join(reasoning)) > 100 and "</think>" not in "".join(reasoning)


def test_llama_servers_recorded_probe_answer_is_the_grammar_winning(llm_server: Any) -> None:
    """
    The ``constraint_won`` probe, recorded: asked for ``{"answer": "no", ...}``
    under a schema allowing only ``yes``, it answered ``yes``. The grammar also
    bound from the first token: a reasoning model under a schema did not think.
    """
    from engine.llm.backend import CONSTRAINT_PROBE_PROMPT

    recorded = _recorded("chat_json_schema.json")
    assert recorded["request"]["messages"][0]["content"] == CONSTRAINT_PROBE_PROMPT
    assert "reasoning_content" not in recorded["json"]["choices"][0]["message"]
    configure(llm_server, "llamacpp", structured_output="auto")
    with wire(discovery("llamacpp") + [recorded], exhaust=True) as seam:
        assert backend().structured_rung() == 1
    (probe,) = chats(seam)
    assert probe["response_format"] == recorded["request"]["response_format"]


def test_llama_servers_recorded_json_object_answer_passes_rung_2(llm_server: Any) -> None:
    """Rung 2's probe, recorded: a prose question under json_object came back an object."""
    from engine.llm.backend import OBJECT_PROBE_PROMPT

    recorded = _recorded("chat_json_object.json")
    assert recorded["request"]["messages"][0]["content"] == OBJECT_PROBE_PROMPT
    configure(llm_server, "llamacpp", structured_output="auto")
    refused = {"status": 200, "json": {"choices": [{"index": 0, "finish_reason": "stop",
               "message": {"role": "assistant", "content": '{"answer": "no", "note": "free"}'}}]}}
    with wire(discovery("llamacpp") + [refused, recorded], exhaust=True) as seam:
        assert backend().structured_rung() == 2
    _, probe = chats(seam)
    assert probe["response_format"] == {"type": "json_object"}


def test_llama_servers_recorded_tool_call_is_parsed(llm_server: Any) -> None:
    """``tools=`` with ``--jinja``: the call arrives in ``message.tool_calls``."""
    configure(llm_server, "llamacpp")
    recorded = _recorded("chat_tool_calls.json")
    with wire(discovery("llamacpp") + [recorded], exhaust=True) as seam:
        result = backend().chat(
            MESSAGES, profile="big", tools=recorded["request"]["tools"], tool_choice="auto"
        )
    (body,) = chats(seam)
    assert body["tools"] == recorded["request"]["tools"]
    assert result.finish_reason == "tool_calls"
    (call,) = result.tool_calls
    assert call.name == "add"
    assert call.arguments == {"a": 2, "b": 2}


def test_llama_servers_recorded_400_is_named_as_llama_servers(
    llm_server: Any, caplog: Any
) -> None:
    """The refusal's own words reach the log, under the server's name, not LM Studio's."""
    import httpx

    configure(llm_server, "llamacpp")
    recorded = _recorded("error_400.json")
    with caplog.at_level(logging.ERROR), wire(discovery("llamacpp") + [recorded], exhaust=True):
        with pytest.raises(httpx.HTTPStatusError):
            backend().chat(MESSAGES, profile="big")
    assert "llama.cpp server refused the request" in caplog.text
    assert "LM Studio" not in caplog.text
    assert recorded["json"]["error"]["message"].split('"')[0] in caplog.text


def test_llama_servers_recorded_401_is_a_refused_key(llm_server: Any) -> None:
    import httpx

    configure(llm_server, "llamacpp")
    with wire(discovery("llamacpp") + [_recorded("error_401.json")], exhaust=True):
        with pytest.raises(httpx.HTTPStatusError) as refused:
            backend().chat(MESSAGES, profile="big")
    assert refused.value.response.status_code == 401
