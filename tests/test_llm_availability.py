"""
"Is the model server up?" asks the configured provider (v0.19.0 T6, spec §8).

``LMSClient.is_available`` gates the summarizer (``engine/scenes/default_state.py``).
Through v0.18 -- and v0.19.0 until this task -- it asked LM Studio's
``GET /api/v1/models`` whatever ``llm.provider`` said, so on any other server
the running summary silently fell back to deterministic compression forever.
It now delegates to the provider row's health probe; on LM Studio that probe
is v0.18's request, byte for byte (the golden's summarizer scenario).

Nothing opens a socket: ``tests/llm_wire.py`` answers every request.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from engine.llm.ollama import OllamaClient
from engine.scenes import default_state
from tests.llm_wire import wire

pytestmark = pytest.mark.real_discovery

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "llm"

#: The real summarizer and Ollama probe, kept before the conftest guard pins
#: them for each test (it pins at test setup; this runs at import).
_REAL_SUMMARIZER_FN = default_state._summarizer_fn
_REAL_OLLAMA_IS_AVAILABLE = OllamaClient.__dict__["is_available"]
assert _REAL_SUMMARIZER_FN.__name__ == "_summarizer_fn", "imported under a pin"
assert _REAL_OLLAMA_IS_AVAILABLE.__name__ == "is_available", "imported under a pin"


def _ok(name: str) -> dict[str, Any]:
    return {"status": 200, "json": json.loads((FIXTURES / name).read_text(encoding="utf-8"))}


#: A healthy vLLM: /health answers 200 with an empty body, then its list.
VLLM_UP = [{"status": 200, "text": ""}, _ok("vllm/models.json")]


def test_is_available_on_vllm_asks_health_not_lm_studios_route(llm_server: Any) -> None:
    """FAILS on v0.18 (and on v0.19.0 before T6): it asked /api/v1/models."""
    from engine.llm.client import LMSClient

    llm_server("vllm")
    with wire(list(VLLM_UP)) as seam:
        assert LMSClient().is_available() is True
    urls = [r["url"] for r in seam.requests]
    assert urls[0] == "http://localhost:8000/health"
    assert not any(u.endswith("/api/v1/models") for u in urls)


def test_the_summarizer_is_not_disabled_on_a_healthy_vllm(llm_server: Any) -> None:
    """
    FAILS on v0.18: the gate asked LM Studio's route, read vLLM as down and
    returned None, so every summary was deterministic.
    """
    llm_server("vllm")
    with wire(list(VLLM_UP)) as seam:
        call = _REAL_SUMMARIZER_FN()
    assert callable(call)
    assert [r["url"] for r in seam.requests] == [
        "http://localhost:8000/health",
        "http://localhost:8000/v1/models",
    ]


def test_the_summarizer_stands_down_when_vllm_is_down(llm_server: Any) -> None:
    llm_server("vllm")
    with wire([{"raise": "ConnectError", "message": "refused"}], exhaust=True):
        assert _REAL_SUMMARIZER_FN() is None


def test_on_ollama_the_gate_is_ollamas_own_probe(
    llm_server: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Under the ``ollama_native`` row the gate asks the client that carries the
    turns, ``OllamaClient.is_available`` -- the same probe (spec §8), and its
    production caller since v0.19.0 T6.
    """
    monkeypatch.setattr(OllamaClient, "is_available", _REAL_OLLAMA_IS_AVAILABLE)
    llm_server("ollama")
    answers = [_ok("ollama/version.json"), _ok("ollama/models_tags.json")]
    with wire(answers, exhaust=True) as seam:
        assert callable(_REAL_SUMMARIZER_FN())
    assert [r["url"] for r in seam.requests] == [
        "http://localhost:11434/api/version",
        "http://localhost:11434/api/tags",
    ]
