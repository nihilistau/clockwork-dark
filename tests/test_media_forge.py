"""The Forge Neo image provider (engine/media/providers/forge.py), against a stubbed urlopen.

v0.25.0 T15: the flagship's art pack is generated on the owner's local Forge Neo
(Qwen Image 2.1). Nothing here reaches a real server: every ``urlopen`` is
scripted, and an unscripted one fails the test.
"""

from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import pytest

from engine.config import get_config
from engine.media.providers import build_provider
from engine.media.providers.base import ImageRequest

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


class _Response:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *exc: Any) -> None:
        return None


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> list[dict[str, Any]]:
    monkeypatch.setenv("CLOCKWORK_DATA_DIR", str(tmp_path))
    record: list[dict[str, Any]] = []

    def urlopen(target: Any, timeout: Any = None) -> Any:
        record.append({"target": target, "timeout": timeout})
        raise AssertionError("an unscripted urlopen reached for " + str(target))

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    return record


def _script(monkeypatch: pytest.MonkeyPatch, record: list[dict[str, Any]], *replies: Any) -> None:
    queue = list(replies)

    def urlopen(target: Any, timeout: Any = None) -> Any:
        record.append({"target": target, "timeout": timeout})
        reply = queue.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return _Response(reply)

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)


def _url(target: Any) -> str:
    return target.full_url if isinstance(target, urllib.request.Request) else str(target)


def _reply(blob: bytes = PNG) -> bytes:
    return json.dumps({"images": [base64.b64encode(blob).decode("ascii")], "info": "{}"}).encode()


def test_build_provider_knows_forge() -> None:
    provider = build_provider("forge")
    assert provider is not None and provider.name == "forge"


def test_the_config_block_names_the_owners_model() -> None:
    cfg = get_config()
    assert cfg.get("media.forge.base_url") == "http://127.0.0.1:7860"
    assert cfg.get("media.forge.checkpoint") == "qwen-image-2.1-Q4_K_M.gguf"
    assert cfg.get("media.forge.modules") == [
        "qwen_image_2.1_vae_bf16.safetensors",
        "qwen3vl_8b_int8_convrot.safetensors",
    ]
    assert cfg.get("media.forge.steps") == 20
    assert cfg.get("media.forge.cfg_scale") == 3.5
    assert cfg.get("media.forge.sampler") == "Euler"
    assert cfg.get("media.forge.timeout_seconds") == 900


def test_a_plate_is_one_txt2img_post_with_no_negative_prompt(
    monkeypatch: pytest.MonkeyPatch, calls: list[dict[str, Any]], tmp_path: Path
) -> None:
    _script(monkeypatch, calls, _reply())
    request = ImageRequest(subject_id="forest_clearing", kind="location", time_of_day="night")
    result = build_provider("forge").generate(request)

    assert result.status == "ready", result.detail
    assert Path(result.path).read_bytes() == PNG
    assert Path(result.path).suffix == ".png"
    assert Path(result.path).parent == tmp_path / "media" / "images"
    [call] = calls
    http = call["target"]
    assert http.full_url == "http://127.0.0.1:7860/sdapi/v1/txt2img"
    assert http.get_method() == "POST"
    assert call["timeout"] == 900
    body = json.loads(http.data.decode("utf-8"))
    assert "negative_prompt" not in body
    assert set(body) == {
        "prompt", "steps", "cfg_scale", "width", "height", "sampler_name", "seed", "override_settings"
    }
    assert body["override_settings"] == {
        "sd_model_checkpoint": "qwen-image-2.1-Q4_K_M.gguf",
        "forge_additional_modules": [
            "qwen_image_2.1_vae_bf16.safetensors",
            "qwen3vl_8b_int8_convrot.safetensors",
        ],
    }
    assert body["steps"] == 20 and body["cfg_scale"] == 3.5 and body["sampler_name"] == "Euler"
    assert isinstance(body["prompt"], str) and body["prompt"]


def test_the_seed_is_deterministic_and_a_request_seed_wins(
    monkeypatch: pytest.MonkeyPatch, calls: list[dict[str, Any]]
) -> None:
    provider = build_provider("forge")
    a = ImageRequest(subject_id="well_row", kind="location")
    b = ImageRequest(subject_id="well_row", kind="location")
    assert provider.seed_for(a) == provider.seed_for(b)
    assert provider.seed_for(a) != provider.seed_for(ImageRequest(subject_id="the_join", kind="location"))
    assert provider.seed_for(ImageRequest(subject_id="well_row", kind="location", seed=1234)) == 1234
    # The re-roll seed does not move the cache key: the plate is the same plate.
    assert ImageRequest(subject_id="well_row", seed=7).cache_key() == a.cache_key()


def test_a_cached_plate_is_not_generated_again(
    monkeypatch: pytest.MonkeyPatch, calls: list[dict[str, Any]]
) -> None:
    _script(monkeypatch, calls, _reply())
    request = ImageRequest(subject_id="well_row", kind="location")
    provider = build_provider("forge")
    assert provider.generate(request).status == "ready"
    assert provider.generate(request).status == "cached"
    assert len(calls) == 1


@pytest.mark.parametrize(
    "reply",
    [
        urllib.error.URLError("refused"),
        b"not json",
        json.dumps({"images": []}).encode(),
        _reply(b"GIF89a not an image we write"),
    ],
)
def test_a_failure_is_a_status_never_a_raise(
    monkeypatch: pytest.MonkeyPatch, calls: list[dict[str, Any]], reply: Any
) -> None:
    _script(monkeypatch, calls, reply)
    result = build_provider("forge").generate(ImageRequest(subject_id="well_row"))
    assert result.status == "failed" and result.provider == "forge"


def test_available_is_a_short_get_of_the_model_list(
    monkeypatch: pytest.MonkeyPatch, calls: list[dict[str, Any]]
) -> None:
    _script(monkeypatch, calls, json.dumps([{"title": "qwen"}]).encode())
    assert build_provider("forge").available() is True
    assert _url(calls[0]["target"]) == "http://127.0.0.1:7860/sdapi/v1/sd-models"
    assert calls[0]["timeout"] <= 5


def test_available_is_false_on_any_error(
    monkeypatch: pytest.MonkeyPatch, calls: list[dict[str, Any]]
) -> None:
    _script(monkeypatch, calls, urllib.error.URLError("nothing listening"))
    assert build_provider("forge").available() is False


@pytest.mark.parametrize(
    ("kind", "subject", "words"),
    [("enemy", "brass_hound", "mechanical hound of polished brass"),
     ("gallery", "banked_oven", "brick oven banked for the night")],
)
def test_an_enemy_or_ending_prompt_reads_its_own_block(kind: str, subject: str, words: str) -> None:
    """An `enemy` request used to fall through to the `locations:` block and render its bare id."""
    from engine.games import registry

    registry.activate("clockwork-dark")
    try:
        prompt = build_provider("forge").body(ImageRequest(subject_id=subject, kind=kind))["prompt"]
    finally:
        registry.deactivate()
    assert words in prompt


def test_generate_arts_provider_help_lists_forge() -> None:
    from scripts import generate_art

    parser_help = Path(generate_art.__file__).read_text(encoding="utf-8")
    assert "grokbuild | xai | comfyui | forge | procedural" in parser_help
