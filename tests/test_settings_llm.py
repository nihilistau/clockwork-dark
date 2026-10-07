"""
The Settings panel writes ``llm.*``.

``engine/api/settings.py`` rewrites ``config/local.yaml`` whole. Since v0.19.0
its model rows are ``llm.*`` keys. A file still holding the old ``lmstudio:``
block is refused at config load since v0.21.0 (``LegacyConfigError``), so no
running process can hold one for the panel to save over.

``_LOCAL_CONFIG`` and the config directory are both pointed at ``tmp_path``:
nothing here writes the real ``config/local.yaml``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator

import pytest
import yaml

import engine.api.settings as settings
import engine.config as config
from engine.config import ConfigManager

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture
def local_yaml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    monkeypatch.delenv("CLOCKWORK_ENV", raising=False)
    monkeypatch.setattr(settings, "_LOCAL_CONFIG", tmp_path / "local.yaml")
    monkeypatch.setattr(config, "_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config, "_DEFAULT_PATH", REPO / "config" / "default.yaml")
    monkeypatch.setattr(config, "_overlay", {})
    monkeypatch.setattr(config, "_instance", None)
    yield tmp_path / "local.yaml"
    # The save reset the config against tmp_path; start the next test cold.
    config._instance = None


def _read(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def test_every_model_row_is_an_llm_key() -> None:
    model_rows = [s["key"] for s in settings.SETTING_SPECS if s["group"] == "The model"]
    assert model_rows
    assert all(key.startswith("llm.") for key in model_rows), model_rows
    assert not [s["key"] for s in settings.SETTING_SPECS if s["key"].startswith("lmstudio")]


def test_prefer_native_is_listed_only_for_lm_studio(
    local_yaml: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def keys_for(provider: str) -> list[str]:
        cfg = ConfigManager({"llm": {"provider": provider, "prefer_native": True}})
        monkeypatch.setattr(settings, "get_config", lambda: cfg)
        return [row["key"] for row in settings.settings_view()["settings"]]

    assert "llm.prefer_native" in keys_for("lmstudio")
    shown = keys_for("vllm")
    assert "llm.prefer_native" not in shown
    assert "llm.profiles.big.temperature" in shown


def test_a_hidden_row_is_refused_on_save(
    local_yaml: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """What the panel does not list, a client cannot write around it."""
    cfg = ConfigManager({"llm": {"provider": "vllm"}})
    monkeypatch.setattr(settings, "get_config", lambda: cfg)
    result = settings.apply_settings(
        {"llm.prefer_native": False, "llm.profiles.big.temperature": 0.5}
    )
    assert result["ok"], result
    assert "llm.prefer_native" not in result["applied"]
    assert "vllm" in result["rejected"]["llm.prefer_native"]
    assert result["applied"] == {"llm.profiles.big.temperature": 0.5}
    assert "prefer_native" not in _read(local_yaml)["llm"]


def test_an_unparseable_local_yaml_is_refused_not_overwritten(local_yaml: Path) -> None:
    """The save rewrites the whole file; read as empty, it would erase the machine's config."""
    broken = "stack:\n  services:\n    comfyui: {root: 'C:/comfy'\n  tts: [\n"
    local_yaml.write_text(broken, encoding="utf-8")
    result = settings.apply_settings({"llm.context_tokens": 16384})
    assert result["ok"] is False
    assert "does not parse" in result["error"]
    assert "Nothing was saved" in result["error"]
    assert result["applied"] == {}
    assert local_yaml.read_text(encoding="utf-8") == broken
    assert not local_yaml.with_suffix(".yaml.tmp").exists()

    # So is a reset, and a file that parses to something other than a mapping.
    assert settings.apply_settings({}, reset=True)["ok"] is False
    local_yaml.write_text("- just\n- a list\n", encoding="utf-8")
    listed = settings.apply_settings({"llm.context_tokens": 16384})
    assert listed["ok"] is False and "not a mapping" in listed["error"]
    assert local_yaml.read_text(encoding="utf-8") == "- just\n- a list\n"


def test_a_local_yaml_that_is_not_utf8_is_refused_not_a_500(local_yaml: Path) -> None:
    """
    Bytes that do not decode are a file the panel cannot read, like one that
    does not parse. Until v0.19.0 T3 ``_read_local`` caught only OSError and
    YAMLError, so the UnicodeDecodeError escaped ``apply_settings`` and the
    request answered 500 instead of the engine's own refusal.
    """
    raw = "llm:\n  base_url: 'http://café:1234/v1'\n".encode("latin-1")
    local_yaml.write_bytes(raw)
    result = settings.apply_settings({"llm.context_tokens": 16384})
    assert result["ok"] is False
    assert "does not parse" in result["error"]
    assert "UnicodeDecodeError" in result["error"]
    assert local_yaml.read_bytes() == raw
    # The view reads the same file; it shows no overrides rather than raising.
    assert settings._local_overrides() == {}
