"""
The structured-output probes, both kinds (spec §4.1).

``llm.structured_output: auto`` probes the server once per process, by the
provider row's ``probe`` cell:

* ``lmstudio_v18`` -- v0.18's ``{ok: boolean}`` probe, byte-identical. The
  golden pins its request and both answers (scenarios 07 and 08); here, only
  that a "no" still means no grammar and asks nothing further.
* ``constraint_won`` -- every other row. The schema allows exactly
  ``{"answer": "yes"}``; the prompt asks for ``{"answer": "no", "note":
  "free"}``. It passes only if the reply parses to exactly the schema's
  answer: the constraint beat the prompt. A server that accepts
  ``response_format`` and ignores it echoes the prompt, and fails -- which
  v0.18's ``'"ok"' in content`` check could not tell from a pass. A failed
  ``json_schema`` probe tries rung 2: a prose question under ``json_object``,
  passing only if the reply is a JSON object. Neither: rung 3.

Every request goes through ``tests/llm_wire.py``; no socket opens.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from tests.llm_golden import PROBE_NO, _models
from tests.llm_wire import wire
from tests.test_llm_request_shaping import chat_answer, discovery, model_of

pytestmark = pytest.mark.real_discovery

SCHEMA = {
    "name": "probe_test",
    "strict": True,
    "schema": {"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"]},
}

REFUSED = {
    "status": 400,
    "json": {"error": {"message": "response_format is not supported", "type": "BadRequestError"}},
}


def _configure(llm_server: Any, provider: str) -> None:
    model = model_of(provider)
    llm_server(
        provider,
        structured_output="auto",
        profiles={"big": {"model": model}, "small": {"model": model}},
    )


def _backend():
    from engine.llm.backend import get_backend

    return get_backend()


def _bodies(seam: Any) -> list[dict[str, Any]]:
    return [
        json.loads(r["body"]) for r in seam.requests if r["url"].endswith("/chat/completions")
    ]


@pytest.mark.parametrize("provider", ["vllm", "llamacpp", "openai_compat"])
def test_the_constraint_won_so_the_grammar_is_used(llm_server: Any, provider: str) -> None:
    _configure(llm_server, provider)
    answers = discovery(provider) + [chat_answer('{"answer": "yes"}')]
    with wire(answers, exhaust=True) as seam:
        emitted = _backend().structured_output(SCHEMA)
    assert emitted == {"type": "json_schema", "json_schema": SCHEMA}
    (probe,) = _bodies(seam)
    assert probe["messages"] == [
        {"role": "user", "content": 'Reply with exactly {"answer": "no", "note": "free"}'}
    ]
    assert probe["response_format"]["type"] == "json_schema"
    assert probe["response_format"]["json_schema"]["schema"] == {
        "type": "object",
        "properties": {"answer": {"anyOf": [{"type": "string", "enum": ["yes"]}]}},
        "required": ["answer"],
        "additionalProperties": False,
    }
    # Cached for the process: a second schema sends nothing.
    with wire([], exhaust=True) as again:
        assert _backend().structured_output(SCHEMA) == emitted
    assert not again.requests


def test_a_server_that_echoes_the_prompt_fails_the_probe(llm_server: Any) -> None:
    """Accepted the grammar, ignored it: the constraint did not win. Rung 2 next."""
    _configure(llm_server, "openai_compat")
    answers = discovery("openai_compat") + [
        chat_answer('{"answer": "no", "note": "free"}'),
        chat_answer('{"sky": "orange"}'),
    ]
    with wire(answers, exhaust=True) as seam:
        emitted = _backend().structured_output(SCHEMA)
    assert emitted == {"type": "json_object"}
    constraint, obj = _bodies(seam)
    assert constraint["response_format"]["type"] == "json_schema"
    assert obj["response_format"] == {"type": "json_object"}
    assert "one sentence" in obj["messages"][0]["content"]


def test_a_near_miss_is_not_a_pass(llm_server: Any) -> None:
    """``{"answer": "yes", "note": "free"}`` broke additionalProperties: no."""
    _configure(llm_server, "vllm")
    answers = discovery("vllm") + [
        chat_answer('{"answer": "yes", "note": "free"}'),
        chat_answer("The sky is orange at dusk."),
    ]
    with wire(answers, exhaust=True):
        assert _backend().structured_output(SCHEMA) is None


def test_a_server_that_answers_400_fails_both_probes(llm_server: Any) -> None:
    _configure(llm_server, "llamacpp")
    answers = discovery("llamacpp") + [REFUSED, REFUSED]
    with wire(answers, exhaust=True) as seam:
        emitted = _backend().structured_output(SCHEMA)
    assert emitted is None
    assert len(_bodies(seam)) == 2
    assert _backend().structured_rung() == 3


def test_the_json_object_probe_passes_only_on_an_object(llm_server: Any) -> None:
    _configure(llm_server, "openai_compat")
    answers = discovery("openai_compat") + [REFUSED, chat_answer('["orange"]')]
    with wire(answers, exhaust=True):
        assert _backend().structured_output(SCHEMA) is None


def test_inline_thinking_does_not_fail_the_probe(llm_server: Any) -> None:
    """vLLM without --reasoning-parser: the answer follows a <think> span."""
    _configure(llm_server, "vllm")
    reply = '<think>They want no, but the grammar says yes.</think>\n{"answer": "yes"}'
    with wire(discovery("vllm") + [chat_answer(reply)], exhaust=True):
        assert _backend().structured_output(SCHEMA)["type"] == "json_schema"


def test_lm_studios_no_means_no_grammar_and_no_second_probe(llm_server: Any) -> None:
    """The ``lmstudio_v18`` ladder: one probe, and a no lands on rung 3."""
    llm_server("lmstudio", structured_output="auto")
    with wire([_models(), PROBE_NO], exhaust=True) as seam:
        assert _backend().structured_output(SCHEMA) is None
    (probe,) = _bodies(seam)
    assert probe["messages"] == [{"role": "user", "content": 'Reply with {"ok": true}'}]
    assert _backend().structured_rung() == 3
