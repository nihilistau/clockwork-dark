"""
The Settings panel writes ``llm.*``, and migrates a legacy block when it saves.

``engine/api/settings.py`` rewrites ``config/local.yaml`` whole. Since v0.19.0
its model rows are ``llm.*`` keys, and a save moves the file's ``lmstudio:``
block to ``llm:`` by the alias's own merge rule (spec §2.2), so the first
setting a player saves migrates the file, keeping every value in it.

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


def _write(path: Path, data: dict[str, Any]) -> None:
    path.write_text(yaml.safe_dump(data, sort_keys=True), encoding="utf-8")


def _read(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


LEGACY = {
    "lmstudio": {
        "base_url": "http://10.1.2.3:1234/v1",
        "api_key": "${file:somewhere/key.txt}",
        "ttl_seconds": 700,
        "profiles": {"big": {"temperature": 0.4, "model": "my/model"}},
        "mcp": {"enabled": True, "port": 8999},
    },
    "stack": {"services": {"lmstudio": {"enabled": False}, "comfyui": {"root": "C:/comfy"}}},
    "tts": {"enabled": True},
}


def test_every_model_row_is_an_llm_key() -> None:
    model_rows = [s["key"] for s in settings.SETTING_SPECS if s["group"] == "The model"]
    assert model_rows
    assert all(key.startswith("llm.") for key in model_rows), model_rows
    assert not [s["key"] for s in settings.SETTING_SPECS if s["key"].startswith("lmstudio")]


def test_a_save_migrates_the_legacy_block_keeping_every_value(local_yaml: Path) -> None:
    _write(local_yaml, LEGACY)
    result = settings.apply_settings({"llm.profiles.big.max_tokens": 1500})
    assert result["ok"], result

    written = _read(local_yaml)
    assert "lmstudio" not in written
    assert written["llm"] == {
        "base_url": "http://10.1.2.3:1234/v1",
        "api_key": "${file:somewhere/key.txt}",
        "keep_alive_seconds": 700,
        "profiles": {"big": {"temperature": 0.4, "model": "my/model", "max_tokens": 1500}},
        "mcp": {"enabled": True, "port": 8999},
    }
    assert written["stack"]["services"] == {"llm": {"enabled": False}, "comfyui": {"root": "C:/comfy"}}
    assert written["tts"] == {"enabled": True}

    # And the reloaded config reads it with no alias left to apply.
    cfg = config.get_config()
    assert cfg.get("llm.profiles.big.max_tokens") == 1500
    assert cfg.get("llm.keep_alive_seconds") == 700


def test_a_save_merges_both_blocks_with_llm_winning(local_yaml: Path) -> None:
    _write(
        local_yaml,
        {
            "llm": {"base_url": "http://new:1/v1"},
            "lmstudio": {"base_url": "http://old:2/v1", "timeout_seconds": 41},
        },
    )
    assert settings.apply_settings({"llm.context_tokens": 16384})["ok"]
    written = _read(local_yaml)
    assert "lmstudio" not in written
    assert written["llm"] == {
        "base_url": "http://new:1/v1",
        "timeout_seconds": 41,
        "context_tokens": 16384,
    }


def test_a_reset_migrates_and_removes_only_the_panels_keys(local_yaml: Path) -> None:
    _write(local_yaml, LEGACY)
    assert settings.apply_settings({}, reset=True)["ok"]
    written = _read(local_yaml)
    assert "lmstudio" not in written
    # `profiles.big.model` and `temperature` are the panel's own rows; the rest is the machine's.
    assert written["llm"]["profiles"] == {"big": {}}
    assert written["llm"]["base_url"] == "http://10.1.2.3:1234/v1"
    assert written["llm"]["mcp"] == {"enabled": True, "port": 8999}


def test_a_legacy_override_shows_as_overridden(local_yaml: Path) -> None:
    _write(local_yaml, LEGACY)
    rows = {row["key"]: row for row in settings.settings_view()["settings"]}
    assert rows["llm.profiles.big.temperature"]["overridden"] is True
    assert rows["llm.profiles.big.temperature"]["value"] == 0.4
    assert rows["llm.profiles.big.reasoning"]["overridden"] is False
    # Viewing never writes.
    assert _read(local_yaml) == LEGACY


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
