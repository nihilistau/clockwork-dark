"""The xAI image provider (engine/media/providers/xai.py), against a stubbed urlopen."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import logging
import urllib.error
import urllib.request
from typing import Any

import pytest

import engine.config
from engine.media.providers import build_provider
from engine.media.providers.base import ImageRequest
from engine.media.providers import xai

SENTINEL = "SENTINEL_planted_value_0123456789"
REAL_ROOT = engine.config._ROOT  # captured before any test patches it
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 32


class _Response:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *exc: Any) -> None:
        return None


@pytest.fixture(autouse=True)
def _never_the_real_key_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    """`${file:xai_api_key.txt}` resolves against an empty temp root here."""
    monkeypatch.setattr(engine.config, "_ROOT", tmp_path)


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> list[dict[str, Any]]:
    """Every urlopen is recorded; none leaves the process. A host other than
    api.x.ai, or any call not routed through a script below, fails the test."""
    monkeypatch.setenv("CLOCKWORK_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("XAI_API_KEY", SENTINEL)
    record: list[dict[str, Any]] = []
    monkeypatch.setattr(urllib.request, "urlopen", _refuse(record))
    return record


def _refuse(record: list[dict[str, Any]]) -> Any:
    def urlopen(target: Any, timeout: Any = None) -> Any:
        record.append({"target": target, "timeout": timeout})
        raise AssertionError("an unscripted urlopen reached for " + str(target))

    return urlopen


def _script(monkeypatch: pytest.MonkeyPatch, record: list[dict[str, Any]], *replies: Any) -> None:
    queue = list(replies)

    def urlopen(target: Any, timeout: Any = None) -> Any:
        record.append({"target": target, "timeout": timeout})
        reply = queue.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return _Response(reply)

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)


def _provider() -> xai.XaiImageProvider:
    """Built with the sentinel key, whatever xai_api_key.txt the checkout holds."""
    provider = xai.XaiImageProvider()
    provider.api_key = SENTINEL
    return provider


def _request(subject: str = "xai_test_place") -> ImageRequest:
    return ImageRequest(subject_id=subject, kind="location", story="xai-test")


def _http_error(code: int, message: str) -> urllib.error.HTTPError:
    body = json.dumps({"error": {"message": message}}).encode()
    return urllib.error.HTTPError(xai.ENDPOINT, code, "err", {}, io.BytesIO(body))  # type: ignore[arg-type]


def test_factory_builds_it(calls: list) -> None:
    provider = build_provider("xai")
    assert provider is not None and provider.name == "xai"


def test_the_request_is_shaped_for_the_images_api(
    calls: list, monkeypatch: pytest.MonkeyPatch
) -> None:
    ok = json.dumps({"data": [{"b64_json": base64.b64encode(PNG).decode()}]}).encode()
    _script(monkeypatch, calls, ok)
    _provider().generate(_request())
    (sent,) = calls
    http = sent["target"]
    assert http.full_url == "https://api.x.ai/v1/images/generations"
    assert http.get_method() == "POST"
    assert http.get_header("Authorization") == "Bearer " + SENTINEL
    body = json.loads(http.data)
    assert body["model"] == "grok-imagine-image-2.0"
    assert body["aspect_ratio"] == "16:9"
    assert body["response_format"] == "b64_json"
    assert body["resolution"] == "1k" and body["n"] == 1
    assert body["prompt"] and "image_gen" not in body["prompt"] and "save" not in body["prompt"].lower()
    assert sent["timeout"] == 180


@pytest.mark.parametrize("blob,suffix", [(PNG, ".png"), (JPEG, ".jpg")])
def test_a_b64_response_is_written(
    calls: list, monkeypatch: pytest.MonkeyPatch, blob: bytes, suffix: str
) -> None:
    ok = json.dumps({"data": [{"b64_json": base64.b64encode(blob).decode()}]}).encode()
    _script(monkeypatch, calls, ok)
    result = _provider().generate(_request(f"b64{suffix[1:]}"))
    assert result.status == "ready" and result.provider == "xai"
    assert result.path.endswith(suffix)
    with open(result.path, "rb") as f:
        assert f.read() == blob
    assert result.url.startswith("/api/media/images/")


def test_a_url_response_is_fetched(calls: list, monkeypatch: pytest.MonkeyPatch) -> None:
    first = json.dumps({"data": [{"url": "https://imgen.x.ai/abc.png"}]}).encode()
    _script(monkeypatch, calls, first, PNG)
    result = _provider().generate(_request("by_url"))
    assert result.status == "ready"
    assert calls[1]["target"] == "https://imgen.x.ai/abc.png"
    with open(result.path, "rb") as f:
        assert f.read() == PNG


@pytest.mark.parametrize("code,message", [(401, "Incorrect API key provided"), (429, "Rate limit reached")])
def test_http_errors_fail_with_the_message_and_never_the_key(
    calls: list,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    code: int,
    message: str,
) -> None:
    # An API that echoes the key back must still not leak it.
    _script(monkeypatch, calls, _http_error(code, f"{message}: {SENTINEL}"))
    with caplog.at_level(logging.DEBUG):
        result = _provider().generate(_request(f"err{code}"))
    assert result.status == "failed" and not result.ok
    assert str(code) in result.detail and message in result.detail
    assert SENTINEL not in result.detail
    assert SENTINEL not in caplog.text
    assert "Bearer" not in result.detail and "Bearer" not in caplog.text


def test_a_network_error_fails_without_raising(calls: list, monkeypatch: pytest.MonkeyPatch) -> None:
    _script(monkeypatch, calls, urllib.error.URLError("unreachable"))
    result = _provider().generate(_request("netdown"))
    assert result.status == "failed" and "unreachable" in result.detail


def test_a_reply_with_no_image_fails(calls: list, monkeypatch: pytest.MonkeyPatch) -> None:
    _script(monkeypatch, calls, json.dumps({"data": []}).encode())
    assert _provider().generate(_request("empty")).status == "failed"


def test_no_key_fails_fast_without_a_request(
    calls: list, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    provider = _provider()
    provider.api_key = ""
    assert not provider.available()
    result = provider.generate(_request("nokey"))
    assert result.status == "failed"
    assert result.detail == "no xAI API key (media.xai.api_key)"
    assert calls == []


def test_the_live_call_guard_stops_an_unscripted_request(calls: list) -> None:
    """The fixture's urlopen refuses anything unscripted, so a test that forgot
    to stub fails here rather than reaching api.x.ai: the provider turns the
    refusal into a failed result and the call is on the record."""
    with pytest.raises(AssertionError):
        urllib.request.urlopen("https://api.x.ai/v1/images/generations")
    assert calls and "api.x.ai" in calls[0]["target"]


def test_the_suite_never_resolves_the_repositorys_key_file() -> None:
    real = REAL_ROOT / "xai_api_key.txt"
    if not real.is_file():
        pytest.skip("no xai_api_key.txt in the repository")
    lines = real.read_text(encoding="utf-8-sig").strip().splitlines()
    if not lines or not lines[0].strip():
        pytest.skip("xai_api_key.txt is empty")
    wanted = hashlib.sha256(lines[0].strip().encode()).hexdigest()
    resolved = xai.XaiImageProvider().api_key
    assert hashlib.sha256(resolved.encode()).hexdigest() != wanted, (
        "the provider resolved the repository's real xAI key under test"
    )


def test_bearer_shaped_text_is_masked_from_details(
    calls: list, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    stray = "xai-" + "A1b2C3d4" * 4
    _script(monkeypatch, calls, _http_error(401, f"bad Authorization: Bearer {stray} and {stray}"))
    with caplog.at_level(logging.DEBUG):
        result = _provider().generate(_request("masked"))
    assert "[masked]" in result.detail
    assert stray not in result.detail and stray not in caplog.text
    assert "Bearer " + stray not in caplog.text
