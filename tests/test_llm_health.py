"""
Every provider's health probe, from fixtures (v0.19.0 T6, spec §8).

``Provider.health_probe`` asks the row's ``health`` cell in order, and the
first "no" is the answer: LM Studio's model list by its shape (v0.18's
request, which the golden pins), vLLM's ``/health`` then its list,
llama-server's ``/health`` (503 while a model loads), Ollama's
``/api/version`` then ``/api/tags``, a generic server's list. A 200 is never
enough on its own -- a server can answer a route it does not own with 200 and
an error body -- so a 200 error body fails on every row.

Nothing opens a socket: ``tests/llm_wire.py`` answers every request, and the
conftest guard stays up. ``real_discovery`` lifts only the discovery pin, since
the list routes ARE discovery's.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from engine.llm.providers import PROVIDERS, get_provider
from tests.llm_wire import wire

pytestmark = pytest.mark.real_discovery

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "llm"
KEY = "shaping-test-key"  # the key `llm_server` writes


def _fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _ok(body: Any) -> dict[str, Any]:
    return {"status": 200, "json": body}


#: LM Studio's v1 list, the smallest shape `parse_lmstudio_v1` accepts.
LMS_LIST = {"models": [{"key": "a-model", "type": "llm"}]}

#: Per provider: the answers of a healthy server, in order, and the URLs asked.
HEALTHY: dict[str, tuple[list[dict[str, Any]], list[str]]] = {
    "lmstudio": ([_ok(LMS_LIST)], ["http://localhost:1234/api/v1/models"]),
    # vLLM's /health answers 200 with an EMPTY body (its docs); inline, since
    # an empty body is not a JSON fixture.
    "vllm": (
        [{"status": 200, "text": ""}, _ok(_fixture("vllm/models.json"))],
        ["http://localhost:8000/health", "http://localhost:8000/v1/models"],
    ),
    "llamacpp": (
        [_ok(_fixture("llamacpp/health.json"))],
        ["http://localhost:8080/health"],
    ),
    "ollama": (
        [_ok(_fixture("ollama/version.json")), _ok(_fixture("ollama/models_tags.json"))],
        ["http://localhost:11434/api/version", "http://localhost:11434/api/tags"],
    ),
    "openai_compat": (
        [_ok(_fixture("openai_compat/models.json"))],
        ["https://models.example/v1/models"],
    ),
}

#: Per provider: a 200 whose body is an error, on the FIRST route it asks.
ERROR_200: dict[str, dict[str, Any]] = {
    "lmstudio": _ok({"error": "Unexpected endpoint or method. (GET /api/v1/models)"}),
    "vllm": _ok(_fixture("vllm/models_error.json")),
    "llamacpp": _ok(_fixture("llamacpp/models_error.json")),
    "ollama": _ok(_fixture("ollama/models_error.json")),
    "openai_compat": _ok(_fixture("openai_compat/models_error.json")),
}


def test_every_row_has_a_healthy_case_and_an_error_case() -> None:
    assert set(HEALTHY) == set(PROVIDERS) == set(ERROR_200)


@pytest.mark.parametrize("provider", sorted(PROVIDERS))
def test_a_healthy_server_is_up_on_its_own_routes(llm_server: Any, provider: str) -> None:
    llm_server(provider)
    answers, urls = HEALTHY[provider]
    with wire(answers, exhaust=True) as seam:
        ok, detail = get_provider().health_probe()
    assert ok is True, detail
    assert [r["url"] for r in seam.requests] == urls
    # The configured server's own origin: the key goes with every request.
    assert all(r["headers"].get("authorization") == f"Bearer {KEY}" for r in seam.requests)


@pytest.mark.parametrize("provider", sorted(PROVIDERS))
def test_a_200_error_body_is_a_failure_on_every_row(llm_server: Any, provider: str) -> None:
    """The route answered, with 200 and an error: down, and nothing more asked."""
    llm_server(provider)
    with wire([ERROR_200[provider]], exhaust=True) as seam:
        ok, detail = get_provider().health_probe()
    assert ok is False, detail
    assert len(seam.requests) == 1


def test_llama_server_loading_its_model_is_down_with_loading(llm_server: Any) -> None:
    """llama-server answers /health with 503 while ``-m`` loads."""
    llm_server("llamacpp")
    answer = {"status": 503, "json": _fixture("llamacpp/health_loading.json")}
    with wire([answer], exhaust=True):
        ok, detail = get_provider().health_probe()
    assert ok is False
    assert detail.startswith("loading"), detail


def test_a_health_status_that_is_not_ok_is_down(llm_server: Any) -> None:
    """An older llama-server answered ``{"status": "loading model"}``."""
    llm_server("llamacpp")
    with wire([_ok({"status": "loading model"})], exhaust=True):
        ok, detail = get_provider().health_probe()
    assert ok is False
    assert detail.startswith("loading"), detail


def test_vllm_up_but_listing_nothing_is_down(llm_server: Any) -> None:
    """/health passes; the list is then asked, and an empty one is not a server."""
    llm_server("vllm")
    answers = [{"status": 200, "text": ""}, _ok({"object": "list", "data": []})]
    with wire(answers, exhaust=True):
        ok, detail = get_provider().health_probe()
    assert ok is False
    assert "no models" in detail


def test_ollama_answering_something_else_on_version_is_down(llm_server: Any) -> None:
    llm_server("ollama")
    with wire([_ok({"name": "not ollama"})], exhaust=True):
        ok, detail = get_provider().health_probe()
    assert ok is False
    assert "version" in detail


@pytest.mark.parametrize("provider", ["vllm", "llamacpp", "ollama"])
def test_a_401_on_a_liveness_route_names_the_key(llm_server: Any, provider: str) -> None:
    llm_server(provider)
    with wire([{"status": 401, "json": {"error": "unauthorized"}}], exhaust=True):
        ok, detail = get_provider().health_probe()
    assert ok is False
    assert PROVIDERS[provider].key_hint in detail


def test_a_closed_port_is_down_and_says_so(llm_server: Any) -> None:
    llm_server("llamacpp")
    with wire([{"raise": "ConnectError", "message": "refused"}], exhaust=True):
        ok, detail = get_provider().health_probe()
    assert ok is False
    assert "unreachable (ConnectError)" in detail


def test_the_key_is_not_sent_to_another_origin(llm_server: Any) -> None:
    """
    Finding 3's rule, on the probe itself: asked of a base that is not the
    configured server's, the configured key stays home (rule 5).
    """
    llm_server("llamacpp")
    with wire([_ok(_fixture("llamacpp/health.json"))], exhaust=True) as seam:
        ok, _ = get_provider().health_probe("http://127.0.0.1:8081/v1")
    assert ok is True
    (request,) = seam.requests
    assert request["url"] == "http://127.0.0.1:8081/health"
    assert "authorization" not in request["headers"]
