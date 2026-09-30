"""
The stack's model-server probe (v0.19.0 T6, spec §8, finding 3).

FINDING 3. ``engine/stack.py::probe`` sent the bearer key only when the URL
contained ``1234`` or ``lmstudio``: a vLLM on 8000 started with ``--api-key``
was reported "refuses every request" while it worked, and any other service
that happened to sit on a port 1234 was handed the key. The key now goes to
the configured server's ORIGIN -- the scheme, host and port of
``llm.base_url`` -- and nowhere else.

THE SERVICE. ``stack.services.llm.health_url`` ships empty: the model server
is checked by the configured provider's own health probe against
``llm.base_url``. With the default LM Studio config that is still
``GET http://localhost:1234/api/v1/models`` (golden scenario 23).

Nothing opens a socket: ``tests/llm_wire.py`` answers every request.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.llm_wire import wire

pytestmark = pytest.mark.real_discovery

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "llm"
KEY = "shaping-test-key"  # the key `llm_server` writes
LMS_LIST = {"models": [{"key": "a-model", "type": "llm"}]}


def _ok(body: Any) -> dict[str, Any]:
    return {"status": 200, "json": body}


def _fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _model_server() -> Any:
    from engine.stack import load_specs

    (spec,) = [s for s in load_specs() if s.model_server]
    return spec


# -- finding 3 ---------------------------------------------------------------------


def test_the_key_is_sent_to_the_configured_origin(llm_server: Any) -> None:
    """FAILS on v0.18: no `1234` in the URL, so no key, so "refuses every request"."""
    from engine import stack

    llm_server("vllm")
    with wire([_ok({})], exhaust=True) as seam:
        ok, _ = stack.probe("http://localhost:8000/health")
    assert ok is True
    (request,) = seam.requests
    assert request["headers"].get("authorization") == f"Bearer {KEY}"


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8188/system_stats",  # another service
        "http://localhost:8001/health",  # another port
        "https://localhost:8000/health",  # another scheme
        "http://evil.example:1234/lmstudio",  # what v0.18's sniff would have keyed
    ],
)
def test_the_key_is_never_sent_to_another_origin(llm_server: Any, url: str) -> None:
    from engine import stack

    llm_server("vllm")
    with wire([_ok({})], exhaust=True) as seam:
        stack.probe(url)
    (request,) = seam.requests
    assert "authorization" not in request["headers"]


def test_a_401_from_another_origin_does_not_name_the_model_servers_key(llm_server: Any) -> None:
    from engine import stack

    llm_server("vllm")
    with wire([{"status": 401, "json": {"error": "no"}}], exhaust=True):
        ok, detail = stack.probe("http://127.0.0.1:8188/system_stats")
    assert ok is False
    assert "llm.api_key" not in detail


# -- the llm service ----------------------------------------------------------------


def test_the_shipped_health_url_is_empty() -> None:
    from engine.config import get_config

    assert get_config().get("stack.services.llm.health_url") == ""


def test_the_lm_studio_default_still_probes_its_model_list(llm_server: Any) -> None:
    """Golden scenario 23, through the service: v0.18's URL, key and detail."""
    from engine.stack import StackManager

    llm_server("lmstudio")
    spec = _model_server()
    assert spec.name == "lmstudio" and spec.health_url == ""
    with wire([_ok(LMS_LIST)], exhaust=True) as seam:
        (status,) = StackManager([spec]).status()
    assert status.status == "up"
    assert status.detail == "/api/v1/models answers: 1 models, loaded: none"
    (request,) = seam.requests
    assert request["url"] == "http://localhost:1234/api/v1/models"
    assert request["headers"].get("authorization") == f"Bearer {KEY}"


def test_a_moved_lm_studio_is_checked_where_it_is(llm_server: Any) -> None:
    """The v0.18 bug the golden's legacy scenario 23 now names: it asked 1234."""
    from engine.stack import StackManager

    llm_server("lmstudio", base_url="http://127.0.0.1:1235/v1")
    with wire([_ok(LMS_LIST)], exhaust=True) as seam:
        StackManager([_model_server()]).status()
    assert [r["url"] for r in seam.requests] == ["http://127.0.0.1:1235/api/v1/models"]


@pytest.mark.parametrize(
    ("provider", "answers", "first_url"),
    [
        ("vllm", [{"status": 200, "text": ""}, _ok(_fixture("vllm/models.json"))],
         "http://localhost:8000/health"),
        ("llamacpp", [_ok(_fixture("llamacpp/health.json"))], "http://localhost:8080/health"),
        ("ollama", [_ok(_fixture("ollama/version.json")), _ok(_fixture("ollama/models_tags.json"))],
         "http://localhost:11434/api/version"),
        ("openai_compat", [_ok(_fixture("openai_compat/models.json"))],
         "https://models.example/v1/models"),
    ],
)
def test_every_other_provider_is_asked_its_own_question(
    llm_server: Any, provider: str, answers: list[dict[str, Any]], first_url: str
) -> None:
    from engine.stack import StackManager

    llm_server(provider)
    spec = _model_server()
    assert spec.name == "llm"
    with wire(answers, exhaust=True) as seam:
        (status,) = StackManager([spec]).status()
    assert status.status == "up", status.detail
    assert seam.requests[0]["url"] == first_url
    assert all(r["headers"].get("authorization") == f"Bearer {KEY}" for r in seam.requests)


def test_the_providers_shape_check_holds_in_the_stack(llm_server: Any) -> None:
    """A 200 error body is down, not up, through the service too."""
    from engine.stack import StackManager

    llm_server("vllm")
    with wire([_ok(_fixture("vllm/models_error.json"))], exhaust=True):
        (status,) = StackManager([_model_server()]).status()
    assert status.status == "down"


def test_an_explicit_health_url_is_probed_as_it_is(
    llm_server: Any, tmp_path: Path
) -> None:
    """A URL set on the service keeps v0.18's generic probe."""
    import engine.config as config
    from engine.stack import StackManager

    llm_server("vllm")
    local = config._CONFIG_DIR / "local.yaml"
    data = yaml.safe_load(local.read_text(encoding="utf-8"))
    data["stack"] = {"services": {"llm": {"health_url": "http://localhost:8000/ping"}}}
    local.write_text(yaml.safe_dump(data), encoding="utf-8")
    config.reset_config()
    with wire([_ok({})], exhaust=True) as seam:
        (status,) = StackManager([_model_server()]).status()
    assert status.status == "up"
    assert [r["url"] for r in seam.requests] == ["http://localhost:8000/ping"]


def test_model_server_cannot_be_set_from_config(llm_server: Any) -> None:
    """Only `load_specs` says which service is the model server."""
    from engine.stack import ServiceSpec

    spec = ServiceSpec.from_config("comfyui", {"model_server": True, "health_url": ""})
    assert spec.model_server is False
