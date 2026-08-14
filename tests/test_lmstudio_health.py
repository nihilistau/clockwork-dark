"""
Health reporting for LM Studio.

THE DEFECT THESE TESTS PIN DOWN. The doctor called LM Studio ``ready`` from
``GET /v1/models`` while every chat request on the same server was refused. The
ping answers "is a process listening", the game needs "can it complete
anything", and those are different questions with different answers. Measured on
this machine: the server was listening AND returning 401 to every request,
because 'Require API key' was on and ``lmstudio.api_key`` was unset -- and the
health check reported that as up.

Everything here is mocked. A test that needs a running LM Studio is a test that
gets skipped, and a skipped health test is how this got missed.
"""

from __future__ import annotations

import httpx
import pytest

from engine.config import reset_config
from engine.lmstudio.backend import chat_probe
from engine.lmstudio.profiles import ModelProfile
from engine.lmstudio.registry import ModelRegistry, reset_registry


@pytest.fixture(autouse=True)
def _clean():
    reset_config()
    reset_registry()
    yield
    reset_config()
    reset_registry()


def _profile(model: str = "gemma-4-26b", bound: bool = True) -> ModelProfile:
    return ModelProfile(name="big", model=model, bound=bound)


def _post(monkeypatch, response_or_error):
    def fake_post(_url, **_kwargs):
        if isinstance(response_or_error, Exception):
            raise response_or_error
        return response_or_error

    monkeypatch.setattr(httpx, "post", fake_post)


def _response(status: int, json_body=None, text: str = "") -> httpx.Response:
    request = httpx.Request("POST", "http://localhost:1234/v1/chat/completions")
    if json_body is not None:
        return httpx.Response(status, json=json_body, request=request)
    return httpx.Response(status, text=text, request=request)


# -- 1. a server that refuses is not healthy -------------------------------


def test_a_401_is_not_reported_as_up(monkeypatch):
    """
    ``probe`` used to answer (True, "listening, but the API key is missing").
    Reachable and usable are different questions, and the health report exists
    to answer the second one.
    """
    from engine import stack

    monkeypatch.setattr(
        httpx,
        "get",
        lambda *_a, **_k: httpx.Response(
            401,
            json={"error": {"code": "invalid_api_key"}},
            request=httpx.Request("GET", "http://localhost:1234/v1/models"),
        ),
    )
    alive, detail = stack.probe("http://localhost:1234/v1/models")
    assert alive is False
    assert "api key" in detail.lower()
    assert "config/local.yaml" in detail


def test_a_200_is_still_up(monkeypatch):
    from engine import stack

    monkeypatch.setattr(
        httpx,
        "get",
        lambda *_a, **_k: httpx.Response(
            200, json={"data": []}, request=httpx.Request("GET", "http://x/v1/models")
        ),
    )
    assert stack.probe("http://localhost:1234/v1/models") == (True, "ready")


# -- 2. the chat probe reports what actually came back ---------------------


def test_a_working_server_probes_ok(monkeypatch):
    monkeypatch.setattr("engine.lmstudio.backend.resolve_profile", lambda _p: _profile())
    _post(
        monkeypatch,
        _response(200, {"choices": [{"message": {"content": "ready"}}]}),
    )
    result = chat_probe()
    assert result["ok"] is True
    assert result["status"] == "ok"
    assert "ready" in result["content"]


def test_a_400_reports_the_status_and_the_servers_own_words(monkeypatch):
    """
    The body is the only part that says WHY. httpx.HTTPStatusError renders as
    "Client error '400 Bad Request' for url ..." and nothing else, which is how
    a planner call could 400 on every turn and leave no diagnosable trace.
    """
    monkeypatch.setattr("engine.lmstudio.backend.resolve_profile", lambda _p: _profile())
    _post(
        monkeypatch,
        _response(400, text='{"error": "Model \'local-model\' not found."}'),
    )
    result = chat_probe()
    assert result["ok"] is False
    assert result["status"] == "http"
    assert "HTTP 400" in result["detail"]
    assert "local-model" in result["detail"]


def test_a_body_is_truncated_rather_than_dumped(monkeypatch):
    monkeypatch.setattr("engine.lmstudio.backend.resolve_profile", lambda _p: _profile())
    _post(monkeypatch, _response(500, text="x" * 5000))
    detail = chat_probe()["detail"]
    assert len(detail) < 400


def test_a_timeout_is_its_own_status_and_names_the_likely_cause(monkeypatch):
    """
    A cold JIT load of a 26B model legitimately outlasts a doctor's patience.
    Reporting that as "broken" would send somebody debugging a working server.
    """
    monkeypatch.setattr("engine.lmstudio.backend.resolve_profile", lambda _p: _profile())
    _post(monkeypatch, httpx.ReadTimeout("too slow"))
    result = chat_probe(timeout=5.0)
    assert result["status"] == "timeout"
    assert "JIT load" in result["detail"]


def test_an_unreachable_server_is_distinguished_from_a_refusing_one(monkeypatch):
    monkeypatch.setattr("engine.lmstudio.backend.resolve_profile", lambda _p: _profile())
    _post(monkeypatch, httpx.ConnectError("no route"))
    assert chat_probe()["status"] == "unreachable"


def test_a_200_with_no_content_is_the_starvation_bug_seen_from_outside(monkeypatch):
    monkeypatch.setattr("engine.lmstudio.backend.resolve_profile", lambda _p: _profile())
    _post(monkeypatch, _response(200, {"choices": [{"message": {"content": ""}}]}))
    result = chat_probe()
    assert result["ok"] is False
    assert result["status"] == "empty"
    assert "reasoning" in result["detail"]


def test_an_unbound_model_is_named_before_a_request_is_spent(monkeypatch):
    """
    A model id discovery never confirmed is a guaranteed rejection. Saying so
    is the difference between "LM Studio is broken" and "model discovery
    failed, so we asked for a model that does not exist".
    """
    monkeypatch.setattr(
        "engine.lmstudio.backend.resolve_profile",
        lambda _p: _profile("local-model", bound=False),
    )
    _post(monkeypatch, _response(400, text="Model not found"))
    result = chat_probe()
    assert result["bound"] is False
    assert result["model"] == "local-model"


# -- 3. discovery survives a server without /api/v0 ------------------------


def test_v0_discovery_is_preferred(monkeypatch):
    seen: list[str] = []

    def fake_get(url, **_kwargs):
        seen.append(url)
        return httpx.Response(
            200,
            json={"data": [{"id": "a-model", "arch": "gemma3", "max_context_length": 32768}]},
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(httpx, "get", fake_get)
    models = ModelRegistry(base_url="http://x/v1").refresh()
    assert seen == ["http://x/api/v0/models"]
    assert [m.id for m in models] == ["a-model"]


def test_a_server_without_api_v0_still_yields_model_ids(monkeypatch):
    """
    THE FAILURE THIS PREVENTS. Discovery returning [] does not stop the game --
    it makes ``resolve_profile`` fall back to the placeholder id
    ``local-model``, which LM Studio answers with 400 on EVERY request. A
    degraded binding with no capability data beats a fictional one.
    """
    def fake_get(url, **_kwargs):
        request = httpx.Request("GET", url)
        if "/api/v0/" in url:
            return httpx.Response(404, text="not found", request=request)
        return httpx.Response(
            200,
            json={"data": [{"id": "gemma-4-26b"}, {"id": "qwen3-8b"}]},
            request=request,
        )

    monkeypatch.setattr(httpx, "get", fake_get)
    registry = ModelRegistry(base_url="http://x/v1")
    assert sorted(m.id for m in registry.chat_models()) == ["gemma-4-26b", "qwen3-8b"]
    # Degraded entries must still clear is_chat_model, or the fallback buys
    # nothing at all.
    assert all(m.is_chat_model for m in registry.chat_models())


def test_both_routes_failing_still_returns_a_list_not_an_exception(monkeypatch):
    monkeypatch.setattr(
        httpx,
        "get",
        lambda url, **_k: (_ for _ in ()).throw(httpx.ConnectError("down")),
    )
    assert ModelRegistry(base_url="http://x/v1").refresh() == []


def test_a_401_during_discovery_says_what_to_change(monkeypatch, caplog):
    """The measured state of this machine. The message has to be actionable."""
    monkeypatch.setattr(
        httpx,
        "get",
        lambda url, **_k: httpx.Response(
            401, json={"error": {}}, request=httpx.Request("GET", url)
        ),
    )
    with caplog.at_level("ERROR"):
        assert ModelRegistry(base_url="http://x/v1").refresh() == []
    assert "lmstudio.api_key" in caplog.text


# -- 4. the client stops swallowing the reason ----------------------------


def test_a_refused_chat_logs_the_response_body(monkeypatch, caplog):
    from engine.lmstudio.client import LMSClient

    client = LMSClient(base_url="http://test.local/v1")
    client._client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                400, text='{"error":"Only user and assistant roles are supported!"}'
            )
        ),
        base_url="http://test.local/v1",
    )
    with caplog.at_level("ERROR"), pytest.raises(httpx.HTTPError):
        client.chat([{"role": "user", "content": "hi"}], model="a-model")
    assert "Only user and assistant roles" in caplog.text
    assert "status=400" in caplog.text


# -- 5. the request timeout is a knob, not a constant ---------------------


def test_both_transports_read_the_configured_timeout():
    """
    180 seconds was hardcoded in both clients. A schema-constrained authoring
    draft asks for 4000 tokens on the one route that cannot disable reasoning,
    which on a large model is over 200 seconds of generation -- so the client
    gave up on work the server was still doing, and there was no knob.
    """
    from engine.config import get_config
    from engine.lmstudio.client import LMSClient
    from engine.lmstudio.native import NativeClient

    expected = float(get_config().get("lmstudio.timeout_seconds", 300))
    assert expected >= 180
    assert LMSClient().timeout == expected
    assert NativeClient().timeout == expected
    # An explicit argument still wins, for a caller that wants to fail fast.
    assert LMSClient(timeout=5.0).timeout == 5.0
