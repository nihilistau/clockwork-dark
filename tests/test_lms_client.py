"""LMSClient SSE streaming tests (mocked HTTP)."""

from __future__ import annotations

import json

import httpx
import pytest

from engine.agents.stream_processor import StreamProcessor
from engine.config import reset_config
from engine.lmstudio.client import LMSClient, reset_lms_client
from engine.lmstudio.profiles import resolve_profile
from engine.lmstudio.speculative import speculative_enabled, speculative_stream


def _sse_lines(*chunks: str) -> bytes:
    lines = []
    for c in chunks:
        payload = json.dumps({"choices": [{"delta": {"content": c}}]})
        lines.append(f"data: {payload}")
    lines.append("data: [DONE]")
    return "\n".join(lines).encode("utf-8")


def test_resolve_profiles():
    reset_config()
    big = resolve_profile("big")
    draft = resolve_profile("draft")
    assert big.name == "big"
    assert draft.max_tokens == 256


def test_chat_stream_mock(monkeypatch):
    reset_lms_client()
    client = LMSClient(base_url="http://test.local/v1")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/chat/completions")
        return httpx.Response(200, content=_sse_lines("Hello ", "forest."))

    transport = httpx.MockTransport(handler)
    client._client = httpx.Client(transport=transport, base_url="http://test.local/v1")

    proc = StreamProcessor()
    chunks = list(
        client.chat_stream(
            [{"role": "user", "content": "hi"}],
            model="test-model",
            on_event=proc.on_event,
        )
    )
    assert "".join(chunks) == "Hello forest."
    result = proc.result()
    assert "Hello forest." in result.clean_text
    client.close()


def test_infer_processed_with_tags(monkeypatch):
    reset_lms_client()
    client = LMSClient(base_url="http://test.local/v1")
    body = _sse_lines("Mist rises. [IMAGE:forest_clearing] ")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body)

    transport = httpx.MockTransport(handler)
    client._client = httpx.Client(transport=transport, base_url="http://test.local/v1")

    result = client.infer_processed(
        [{"role": "user", "content": "describe"}],
        profile="big",
    )
    assert result.image_requests == ["forest_clearing"]
    assert "Mist rises." in result.clean_text
    client.close()


def test_speculative_fallback_single_model(monkeypatch):
    reset_lms_client()
    client = LMSClient(base_url="http://test.local/v1")
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        body = json.loads(request.content.decode()) if request.content else {}
        if body.get("stream"):
            return httpx.Response(200, content=_sse_lines("Refined tale."))
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "Skeleton."}}]},
        )

    transport = httpx.MockTransport(handler)
    client._client = httpx.Client(transport=transport, base_url="http://test.local/v1")

    deltas: list[str] = []
    resp = speculative_stream(
        client,
        [{"role": "system", "content": "GM"}, {"role": "user", "content": "start"}],
        on_delta=deltas.append,
    )
    assert "Refined" in resp.content
    assert speculative_enabled()
    client.close()