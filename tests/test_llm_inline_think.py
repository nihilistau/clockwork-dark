"""
Inline ``<think>`` never reaches the content channel (spec §4.5).

vLLM without ``--reasoning-parser``, and llama-server with
``--reasoning-format none``, send a reasoning model's thinking INSIDE
``content``, wrapped in ``<think>…</think>``. Left there it reaches the
narration decoder and the tag buffer, and an ``[IMAGE:]`` the model wrote
while thinking would fire a real image generation.

On every row whose ``inline_think`` is ``strip`` the client moves a LEADING
span to the reasoning channel -- streamed (split across deltas anywhere,
inside either tag included) and not -- before anything downstream sees it. An
unclosed span is reasoning, so the response reads as starved rather than as
narration. The ``lmstudio`` row is ``pass``: LM Studio splits reasoning out
itself, and its parse is the golden's.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from engine.llm.client import InlineThinkSplitter, strip_inline_think
from tests.llm_golden import _models
from tests.llm_wire import wire
from tests.test_llm_request_shaping import chat_answer, discovery

pytestmark = pytest.mark.real_discovery

REPO = Path(__file__).resolve().parents[1]
STREAM = REPO / "tests" / "fixtures" / "llm" / "vllm" / "chat_stream_inline_think.json"

MESSAGES = [
    {"role": "system", "content": "Narrate."},
    {"role": "user", "content": "I light the lamp."},
]


def _split(pieces: list[str]) -> tuple[str, str]:
    """Feed ``pieces`` as deltas; return (content, reasoning)."""
    splitter = InlineThinkSplitter()
    out = [p for piece in pieces for p in splitter.push(piece)] + splitter.flush()
    content = "".join(t for c, t in out if c == "content")
    reasoning = "".join(t for c, t in out if c == "reasoning")
    return content, reasoning


TEXT = "<think>maybe [IMAGE: a lamp]</think>\n\n{\"narration\": \"A lamp.\"}"


def test_a_leading_span_moves_to_reasoning_whole() -> None:
    assert _split([TEXT]) == ('{"narration": "A lamp."}', "maybe [IMAGE: a lamp]")


def test_every_split_point_gives_the_same_answer() -> None:
    """Split in two anywhere -- inside ``<think>``, inside ``</think>`` -- and in three."""
    expected = _split([TEXT])
    for i in range(len(TEXT) + 1):
        assert _split([TEXT[:i], TEXT[i:]]) == expected, i
        for j in range(i, len(TEXT) + 1, 7):
            assert _split([TEXT[:i], TEXT[i:j], TEXT[j:]]) == expected, (i, j)


def test_one_character_at_a_time() -> None:
    assert _split(list(TEXT)) == _split([TEXT])


def test_an_unclosed_span_is_reasoning_not_content() -> None:
    assert _split(["<think>still thinking about [IMAGE: a lamp]"]) == (
        "",
        "still thinking about [IMAGE: a lamp]",
    )


def test_text_with_no_leading_span_is_untouched() -> None:
    for text in (
        '{"narration": "A lamp."}',
        "  leading space, then prose",
        'Prose first, then <think>not a span</think>',
        "<thin>not the tag</thin>",
        "<",
    ):
        assert _split([text]) == (text, ""), text


def test_leading_whitespace_before_the_tag_is_still_a_span() -> None:
    assert _split(["\n  <think>x</think>answer"]) == ("answer", "x")


def test_the_non_streamed_helper_keeps_any_reasoning_the_server_split() -> None:
    assert strip_inline_think("<think>b</think>c", "a") == ("c", "ab")


# -- through the client --------------------------------------------------------------


def _vllm(llm_server: Any) -> None:
    model = "Qwen/Qwen3-1.7B"
    llm_server(
        "vllm",
        structured_output="off",
        profiles={"big": {"model": model}, "small": {"model": model}},
    )


def _backend():
    from engine.llm.backend import get_backend

    return get_backend()


def test_a_streamed_think_holding_an_image_tag_never_reaches_the_content_deltas(
    llm_server: Any,
) -> None:
    """The fixture splits both tags across deltas; its thinking names [IMAGE: a lamp]."""
    _vllm(llm_server)
    answer = json.loads(STREAM.read_text(encoding="utf-8"))
    deltas: list[str] = []
    reasoning: list[str] = []
    events: list[Any] = []
    with wire(discovery("vllm") + [answer], exhaust=True):
        generator = _backend().chat_stream(
            MESSAGES,
            profile="big",
            on_delta=deltas.append,
            on_reasoning=reasoning.append,
            on_event=events.append,
        )
        yielded = list(generator)
    assert yielded == deltas
    content = "".join(deltas)
    assert "[IMAGE" not in content and "<think>" not in content and "think>" not in content
    assert content.startswith('{"narration": "The path east narrows')
    assert "[IMAGE: a lamp]" in "".join(reasoning)
    types = [e.event_type for e in events]
    assert types.index("reasoning.end") < types.index("message.start")
    assert all("[IMAGE" not in e.content for e in events if e.event_type == "message.delta")


def test_the_storyteller_streams_no_thinking_to_the_player(llm_server: Any) -> None:
    """Through ``_infer``: the narration decoder and the tag buffer see no span."""
    from engine.agents.storyteller import StorytellerAgent
    from engine.game.engine import GameEngine
    from engine.game.procgen import new_game_state
    from engine.games import registry

    _vllm(llm_server)
    registry.activate("clockwork-dark")
    try:
        agent = StorytellerAgent(GameEngine(new_game_state(seed=7)))
        answer = json.loads(STREAM.read_text(encoding="utf-8"))
        shown: list[str] = []
        with wire(discovery("vllm") + [answer], exhaust=True):
            generation = agent._infer([dict(m) for m in MESSAGES], on_delta=shown.append)
    finally:
        registry.deactivate()
    assert "[IMAGE" not in "".join(shown)
    assert "The path east narrows" in "".join(shown)
    assert not generation.raw.lstrip().startswith("<think>")
    assert "[IMAGE: a lamp]" in agent.last_reasoning


def test_a_non_streamed_answer_is_split_the_same_way(llm_server: Any) -> None:
    _vllm(llm_server)
    reply = "<think>maybe [IMAGE: a lamp]</think>\n\nIt is autumn."
    with wire(discovery("vllm") + [chat_answer(reply)], exhaust=True):
        result = _backend().chat(MESSAGES, profile="big", retry_on_starvation=False)
    assert result.content == "It is autumn."
    assert result.reasoning_content == "maybe [IMAGE: a lamp]"


def test_an_unclosed_span_at_the_cap_reads_as_starved(llm_server: Any) -> None:
    _vllm(llm_server)
    reply = "<think>thinking and thinking and"
    with wire(
        discovery("vllm") + [chat_answer(reply, finish="length", completion_tokens=4400)],
        exhaust=True,
    ):
        result = _backend().chat(MESSAGES, profile="big", retry_on_starvation=False)
    assert result.content == ""
    assert result.starved_by_reasoning


# -- a template that ignores the patch (recorded, llama-server b7966, v0.19.0 T8) ----
#
# Qwen3-4B-Thinking-2507's chat template opens <think> in the PROMPT whatever
# enable_thinking says. Sent the untrusted reasoning-off patch, it thinks
# anyway -- and llama-server, told thinking is off, stops splitting it out:
# the thinking arrives in `content` with NO opening tag, then </think>, then
# the answer. Recorded in llamacpp/chat_patch_ignored.json and
# chat_stream_patch_ignored.json. At 10ded3c the whole train of thought was
# the answer: a summary, a plan or a narration made of the model's musings.

LLAMACPP = REPO / "tests" / "fixtures" / "llm" / "llamacpp"
THINKER = "Qwen3-4B-Thinking-2507-Q4_K_M.gguf"


def _recorded(name: str) -> dict[str, Any]:
    return json.loads((LLAMACPP / name).read_text(encoding="utf-8"))


def _llamacpp(llm_server: Any, **llm: Any) -> None:
    """The recorded model, undeclared: an `off` request sends an UNTRUSTED patch."""
    llm.setdefault("structured_output", "off")
    llm_server(
        "llamacpp",
        profiles={"big": {"model": THINKER}, "small": {"model": THINKER}},
        **llm,
    )


def _forced(
    pieces: list[str], *, truncated: bool = False, grammar: bool = False
) -> tuple[str, str]:
    splitter = InlineThinkSplitter(forced_open=True, **({"grammar": True} if grammar else {}))
    out = [p for piece in pieces for p in splitter.push(piece)] + splitter.flush(
        truncated=truncated
    )
    content = "".join(t for c, t in out if c == "content")
    reasoning = "".join(t for c, t in out if c == "reasoning")
    return content, reasoning


def _recorded_content(name: str) -> str:
    return _recorded(name)["json"]["choices"][0]["message"]["content"]


def test_an_orphan_close_splits_the_thinking_from_the_answer_at_every_split_point() -> None:
    text = _recorded_content("chat_patch_ignored.json")
    assert text.count("</think>") == 1 and "<think>" not in text  # as recorded
    content, reasoning = _forced([text])
    assert content == "4"
    assert reasoning.startswith("Okay, the user is asking") and "</think>" not in reasoning
    for i in range(0, len(text) + 1, 13):
        assert _forced([text[:i], text[i:]]) == (content, reasoning), i
    assert _forced(list(text[-40:]), truncated=False)[0] == "4"


def test_an_answer_whose_template_honoured_the_patch_is_left_alone() -> None:
    """Qwen3-0.6B honours enable_thinking: no </think>, so it is all answer."""
    text = _recorded_content("chat_reasoning_off.json")
    assert _forced([text]) == (text, "")
    assert _forced(list(text)) == (text, "")


def test_unclosed_thinking_cut_at_the_cap_is_thinking_not_an_answer() -> None:
    text = _recorded_content("chat_patch_ignored.json").split("</think>")[0]
    assert _forced([text], truncated=True) == ("", text.strip())
    # The same text ending on its own (finish "stop") is an answer.
    assert _forced([text], truncated=False) == (text, "")


def test_forced_open_still_reads_a_leading_span_the_ordinary_way() -> None:
    assert _forced(["<think>x</think>answer"]) == ("answer", "x")


def test_a_recorded_answer_to_an_ignored_patch_reaches_the_caller_without_its_thinking(
    llm_server: Any, caplog: Any
) -> None:
    import logging

    _llamacpp(llm_server)
    with caplog.at_level(logging.WARNING), wire(
        discovery("llamacpp") + [_recorded("chat_patch_ignored.json")], exhaust=True
    ) as seam:
        result = _backend().chat(MESSAGES, profile="small", retry_on_starvation=False)
    (body,) = [json.loads(r["body"]) for r in seam.requests if r["url"].endswith("/chat/completions")]
    assert body["chat_template_kwargs"] == {"enable_thinking": False}
    assert result.content == "4"
    assert result.reasoning_content.startswith("Okay, the user is asking")
    assert "ignored its reasoning-off patch" in caplog.text and THINKER in caplog.text


def test_a_recorded_stream_to_an_ignored_patch_yields_only_the_answer(llm_server: Any) -> None:
    _llamacpp(llm_server)
    deltas: list[str] = []
    reasoning: list[str] = []
    with wire(
        discovery("llamacpp") + [_recorded("chat_stream_patch_ignored.json")], exhaust=True
    ):
        generator = _backend().chat_stream(
            MESSAGES, profile="small", on_delta=deltas.append, on_reasoning=reasoning.append
        )
        yielded = list(generator)
    assert "".join(yielded) == "".join(deltas) == "4"
    assert "final answer is just the number 4" in "".join(reasoning)


def test_reasoning_format_none_sends_the_thinking_with_no_opening_tag_and_it_is_split(
    llm_server: Any,
) -> None:
    """
    Recorded with ``--reasoning-format none``: NO patch was sent, and the
    template's own <think> sits in the prompt, so the content is
    ``thinking</think>answer`` -- not the leading span §4.5 was written for.
    A whole answer is read held, so the orphan close splits it; it counts as
    inline thinking, which is the flag's to fix (the doctor's WARN).
    """
    from engine.llm.client import inline_think_seen

    _llamacpp(llm_server)
    recorded = _recorded("chat_inline_think.json")
    assert "chat_template_kwargs" not in recorded["request"]
    with wire(discovery("llamacpp") + [recorded], exhaust=True):
        result = _backend().chat(MESSAGES, profile="big", retry_on_starvation=False)
    assert result.content == "4"
    assert "</think>" not in result.content and result.reasoning_content
    assert inline_think_seen() == 1


# -- vLLM, recorded live (vLLM 0.31.0, v0.20.0 T19) -----------------------------------
#
# Without --reasoning-parser, Qwen3-1.7B's thinking arrives as a LEADING
# <think>...</think> span (the case §4.5 was written for), whole and streamed.
# With the parser it arrives in a channel vLLM 0.31.0 names `reasoning`, not
# `reasoning_content`.

VLLM = REPO / "tests" / "fixtures" / "llm" / "vllm"


def _vllm_recorded(name: str) -> dict[str, Any]:
    return json.loads((VLLM / name).read_text(encoding="utf-8"))


def _vllm_live(llm_server: Any) -> None:
    model = "Qwen/Qwen3-1.7B"
    llm_server(
        "vllm",
        structured_output="off",
        profiles={"big": {"model": model}, "small": {"model": model}},
    )


def test_vllm_s_recorded_inline_span_is_split_whole_and_streamed(llm_server: Any) -> None:
    from engine.llm.client import inline_think_seen

    _vllm_live(llm_server)
    whole = _vllm_recorded("chat_inline_think_live.json")
    assert whole["json"]["choices"][0]["message"]["content"].startswith("<think>")  # as recorded
    with wire(discovery("vllm") + [whole], exhaust=True):
        result = _backend().chat(MESSAGES, profile="big", retry_on_starvation=False)
    assert result.content == "4"
    assert result.reasoning_content.startswith("\nOkay") and "</think>" not in result.reasoning_content
    assert inline_think_seen() == 1

    deltas: list[str] = []
    reasoning: list[str] = []
    # Discovery was asked once, above; the bound model is cached.
    with wire([_vllm_recorded("chat_stream_inline_think_live.json")], exhaust=True):
        yielded = list(_backend().chat_stream(
            MESSAGES, profile="big", on_delta=deltas.append, on_reasoning=reasoning.append
        ))
    assert "".join(yielded) == "".join(deltas) == "4"
    assert "think>" not in "".join(reasoning) and "".join(reasoning).strip()


def test_vllm_s_recorded_reasoning_channel_is_read_as_reasoning(llm_server: Any) -> None:
    """vLLM 0.31.0 sends `reasoning`, not `reasoning_content`, whole and in deltas."""
    _vllm_live(llm_server)
    whole = _vllm_recorded("chat.json")
    assert "reasoning_content" not in whole["json"]["choices"][0]["message"]  # as recorded
    with wire(discovery("vllm") + [whole], exhaust=True):
        result = _backend().chat(MESSAGES, profile="big", retry_on_starvation=False)
    assert result.content.strip() == "4"
    assert result.reasoning_content.strip() and result.reasoning_tokens > 0
    reasoning: list[str] = []
    streamed = _vllm_recorded("chat_stream_thinking.json")
    sent = "".join(
        frame["data"]["choices"][0]["delta"].get("reasoning", "")
        for frame in streamed["sse"]
        if isinstance(frame["data"], dict) and frame["data"].get("choices")
    )
    assert sent.strip() and "reasoning_content" not in json.dumps(streamed["sse"])  # as recorded
    with wire([streamed], exhaust=True):
        yielded = list(_backend().chat_stream(MESSAGES, profile="big", on_reasoning=reasoning.append))
    assert "".join(yielded).strip() == "4"
    # Every reasoning delta reaches the reasoning channel, in order, and none
    # of it the answer (T20, from T19's review: the stream half had asserted
    # only "non-empty").
    assert "".join(reasoning) == sent


# -- fix round 1 ---------------------------------------------------------------------


def _sse(pieces: list[str], finish: str = "stop") -> dict[str, Any]:
    """An OpenAI-compatible stream whose content arrives in ``pieces``."""
    frames = [
        {"data": {"choices": [{"index": 0, "delta": {"content": p}, "finish_reason": None}]}}
        for p in pieces
    ]
    frames.append({"data": {"choices": [{"index": 0, "delta": {}, "finish_reason": finish}]}})
    frames.append({"data": "[DONE]"})
    return {"status": 200, "sse": frames}


GRAMMARED = ['{"narration": "The lamp', ' catches, and the room', ' comes back."}']


def test_a_grammared_stream_to_an_untrusted_patch_streams_as_it_arrives(
    llm_server: Any,
) -> None:
    """
    Fix round 1 (review finding 1): under a grammar the thinking cannot land
    in the content -- llama-server binds the grammar from the first token --
    so the stream is not held. At 40f2de5 every delta was held to the end and
    the player saw nothing until the turn was over.
    """
    from engine.llm.backend import get_backend

    _llamacpp(llm_server, structured_output="json_schema")
    schema = {
        "name": "t", "strict": True,
        "schema": {"type": "object", "properties": {"narration": {"type": "string"}}},
    }
    response_format = get_backend().structured_output(schema)
    assert response_format is not None
    with wire(discovery("llamacpp") + [_sse(GRAMMARED)], exhaust=True) as seam:
        yielded = list(
            _backend().chat_stream(MESSAGES, profile="small", response_format=response_format)
        )
    (body,) = [json.loads(r["body"]) for r in seam.requests if r["url"].endswith("/chat/completions")]
    assert body["chat_template_kwargs"] == {"enable_thinking": False}  # untrusted patch sent
    assert yielded == GRAMMARED  # one delta per delta, not one lump at the end


def test_an_ungrammared_stream_to_an_untrusted_patch_is_still_held(llm_server: Any) -> None:
    """The cost that remains, and is documented: no grammar, no streaming."""
    _llamacpp(llm_server)
    with wire(discovery("llamacpp") + [_sse(["It is ", "autumn."])], exhaust=True):
        yielded = list(_backend().chat_stream(MESSAGES, profile="small"))
    assert yielded == ["It is autumn."]


MENTION = 'I must not write <think> here, [IMAGE: x]</think>{"narration":"ok"}'


def test_a_think_the_ignored_patch_mentions_does_not_make_its_thinking_content() -> None:
    """Fix round 1 (review finding 3): under forced_open the orphan close is the signal."""
    content, reasoning = _forced([MENTION])
    assert content == '{"narration":"ok"}'
    assert "[IMAGE: x]" in reasoning and "[IMAGE" not in content
    for i in range(len(MENTION) + 1):
        assert _forced([MENTION[:i], MENTION[i:]]) == (content, reasoning), i


def test_a_streamed_mention_never_reaches_the_content_deltas(llm_server: Any) -> None:
    _llamacpp(llm_server)
    deltas: list[str] = []
    with wire(discovery("llamacpp") + [_sse([MENTION[:20], MENTION[20:45], MENTION[45:]])],
              exhaust=True):
        list(_backend().chat_stream(MESSAGES, profile="small", on_delta=deltas.append))
    assert "".join(deltas) == '{"narration":"ok"}'
    assert all("[IMAGE" not in d and "<think>" not in d for d in deltas)


def test_a_cut_answer_that_starts_as_json_under_a_grammar_is_an_answer_not_thinking() -> None:
    """Fix round 1 (review finding 4): the one cheap tell of an answer -- under a grammar."""
    assert _forced(
        ['{"narration": "The lamp catches and'], truncated=True, grammar=True
    ) == ('{"narration": "The lamp catches and', "")
    # A cut PROSE answer cannot be told from unclosed thinking: read as starved
    # (the documented trade-off).
    assert _forced(["The lamp catches and"], truncated=True) == ("", "The lamp catches and")


@pytest.mark.parametrize(
    "text",
    [
        "{Let me think about the JSON. [IMAGE: bad] The narration should",
        '{"narration": "draft [IMAGE: bad] and then',
        "[a list I am drafting, [IMAGE: bad]",
    ],
)
def test_brace_led_cut_text_without_a_grammar_is_starved_thinking(text: str) -> None:
    """
    T8 re-review N2: with no grammar on the request, content need not begin
    as JSON, and thinking that drafts its JSON opens with a brace too. At
    5dce685 all of it -- ``[IMAGE:]`` included -- came back as content.
    """
    assert _forced([text], truncated=True) == ("", text)
    assert strip_inline_think(text, "", forced_open=True, truncated=True) == ("", text)
    # The same under a grammar is a cut answer.
    assert _forced([text], truncated=True, grammar=True) == (text, "")


@pytest.mark.parametrize(
    "text",
    [
        '< space-first thinking [IMAGE: v]</think>{"narration":"ok"}',
        '<not a think tag> thinking [IMAGE: w]</think>{"narration":"ok"}',
        '<th and more thinking [IMAGE: z]</think>{"narration":"ok"}',
    ],
)
def test_thinking_that_begins_with_a_tag_prefix_splits_at_every_boundary(text: str) -> None:
    """
    T8 re-review N1: a held stream whose first delta is only part of
    ``<think>`` (``<``, ``<th``) must still find the later orphan close. At
    5dce685 a first delta of ``<`` sent everything, ``[IMAGE:]`` included,
    to the content.
    """
    whole = _forced([text])
    assert whole[0] == '{"narration":"ok"}' and "[IMAGE" in whole[1]
    assert _forced(list(text)) == whole
    for i in range(len(text) + 1):
        assert _forced([text[:i], text[i:]]) == whole, i
        for j in range(i, len(text) + 1, 5):
            got = _forced([text[:i], text[i:j], text[j:]])
            assert got == whole, (i, j)
            assert "[IMAGE" not in got[0]


def test_a_leading_span_after_a_split_open_tag_is_still_a_span_when_held() -> None:
    text = "<think>x [IMAGE: y]</think>answer"
    for i in range(len(text) + 1):
        assert _forced([text[:i], text[i:]]) == ("answer", "x [IMAGE: y]"), i


def test_a_trusted_patch_is_not_second_guessed(llm_server: Any) -> None:
    """A declaration listing `off` is the owner's word: the answer is read as sent."""
    _llamacpp(llm_server, declared_models={THINKER: {"reasoning": ["off", "on"]}})
    text = _recorded_content("chat_reasoning_off.json")
    with wire(discovery("llamacpp") + [chat_answer(text)], exhaust=True):
        result = _backend().chat(MESSAGES, profile="small", retry_on_starvation=False)
    assert result.content == text


def test_lm_studio_passes_content_through_untouched(llm_server: Any) -> None:
    """``inline_think: pass`` -- the server splits reasoning itself."""
    llm_server("lmstudio", structured_output="off")
    reply = "<think>as written</think>It is autumn."
    with wire([_models(), chat_answer(reply)], exhaust=True):
        result = _backend().chat(MESSAGES, profile="small", retry_on_starvation=False)
    assert result.content == reply
    assert result.reasoning_content == ""
