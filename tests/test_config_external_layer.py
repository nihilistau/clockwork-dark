"""
``CLOCKWORK_CONFIG``: an operator's config file outside the repo (v0.20.0 T2;
spec §2.1).

The layer merges after ``config/local.yaml`` and before the game overlay,
refused like every other operator layer when it holds a name v0.21.0 no
longer reads (``LegacyConfigError``). The variable may name several files joined by
``os.pathsep``, merged left to right, so the last one wins. A named file that
is missing or does not parse is a startup error naming the path, not a
warning: an operator who pointed at a file meant it. Unset, nothing changes.

It says what it shadows: ``external_config_keys()`` lists the dotted keys the
files set, and a Settings
save of one of them answers ``"shadowed": [...]``, a key present only when the
list is non-empty.

Every file here lives under ``tmp_path``; ``_CONFIG_DIR`` and the Settings
panel's ``_LOCAL_CONFIG`` point there too.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Iterator

import pytest
import yaml

import engine.api.settings as settings
import engine.config as config

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture
def layers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    directory = tmp_path / "config"
    directory.mkdir()
    for name in ("CLOCKWORK_ENV", "CLOCKWORK_CONFIG", "CLOCKWORK_LLM_API_KEY", "LMSTUDIO_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(config, "_CONFIG_DIR", directory)
    monkeypatch.setattr(config, "_DEFAULT_PATH", REPO / "config" / "default.yaml")
    monkeypatch.setattr(config, "_overlay", {})
    monkeypatch.setattr(config, "_instance", None)
    monkeypatch.setattr(settings, "_LOCAL_CONFIG", directory / "local.yaml")
    yield directory
    config._instance = None


def _yaml(path: Path, data: dict[str, Any]) -> Path:
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


def _point(monkeypatch: pytest.MonkeyPatch, *files: Path) -> None:
    monkeypatch.setenv("CLOCKWORK_CONFIG", os.pathsep.join(str(f) for f in files))
    config._instance = None


def test_the_layer_beats_local_yaml_and_loses_to_the_overlay(
    layers: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _yaml(layers / "local.yaml", {"world": {"tick_interval_seconds": 11, "x_local": 1}})
    external = _yaml(tmp_path / "op.yaml", {"world": {"tick_interval_seconds": 22, "x_ext": 2}})
    _point(monkeypatch, external)
    cfg = config.get_config()
    assert cfg.get("world.tick_interval_seconds") == 22
    assert cfg.get("world.x_local") == 1 and cfg.get("world.x_ext") == 2

    monkeypatch.setattr(config, "_overlay", {"world": {"tick_interval_seconds": 33}})
    config._instance = None
    assert config.get_config().get("world.tick_interval_seconds") == 33


def test_two_files_merge_left_to_right(
    layers: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = _yaml(tmp_path / "a.yaml", {"world": {"both": "a", "only_a": "a"}})
    second = _yaml(tmp_path / "b.yaml", {"world": {"both": "b", "only_b": "b"}})
    _point(monkeypatch, first, second)
    cfg = config.get_config()
    assert cfg.get("world.both") == "b"
    assert cfg.get("world.only_a") == "a" and cfg.get("world.only_b") == "b"


@pytest.mark.parametrize("which", ["alone", "second of two"])
def test_a_missing_file_raises_naming_the_path(
    layers: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, which: str
) -> None:
    missing = tmp_path / "nowhere.yaml"
    files = [missing] if which == "alone" else [_yaml(tmp_path / "ok.yaml", {"a": 1}), missing]
    _point(monkeypatch, *files)
    with pytest.raises(ValueError) as refused:
        config.get_config()
    assert str(missing) in str(refused.value)


@pytest.mark.parametrize("which", ["alone", "second of two"])
def test_an_unparsable_file_raises_naming_the_path(
    layers: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, which: str
) -> None:
    broken = tmp_path / "broken.yaml"
    broken.write_text("world: [unclosed\n  - : :\n", encoding="utf-8")
    files = [broken] if which == "alone" else [_yaml(tmp_path / "ok.yaml", {"a": 1}), broken]
    _point(monkeypatch, *files)
    with pytest.raises(ValueError) as refused:
        config.get_config()
    assert str(broken) in str(refused.value)


def test_a_parse_error_names_the_place_and_never_the_text(
    layers: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    The file may hold a secret, so the error carries a line and column and no
    text of the file, and does not chain the YAML error (which can quote it).
    """
    broken = tmp_path / "secret.yaml"
    broken.write_text("llm:\n  api_key: sk-do-not-print: oops\n", encoding="utf-8")
    _point(monkeypatch, broken)
    with pytest.raises(ValueError) as refused:
        config.get_config()
    message = str(refused.value)
    assert str(broken) in message and "line " in message
    assert "sk-do-not-print" not in message
    assert refused.value.__cause__ is None and refused.value.__suppress_context__


def test_an_unreadable_file_is_said_to_be_unreadable(
    layers: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fix round 1 (review finding 8): not "does not parse (PermissionError)"."""
    locked = _yaml(tmp_path / "locked.yaml", {"a": 1})
    real_open = Path.open

    def refusing(self: Path, *args: object, **kwargs: object) -> object:
        if self == locked:
            raise PermissionError(13, "Permission denied")
        return real_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", refusing)
    _point(monkeypatch, locked)
    with pytest.raises(ValueError) as refused:
        config.get_config()
    message = str(refused.value)
    assert str(locked) in message
    assert "cannot be read (PermissionError)" in message
    assert "parse" not in message


def test_a_file_that_is_not_a_mapping_raises(
    layers: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    listed = tmp_path / "list.yaml"
    listed.write_text("- a\n- b\n", encoding="utf-8")
    _point(monkeypatch, listed)
    with pytest.raises(ValueError) as refused:
        config.get_config()
    assert str(listed) in str(refused.value)


def test_unset_changes_nothing(layers: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    before = config.get_config().as_dict()
    assert config.external_config_keys() == []
    monkeypatch.setenv("CLOCKWORK_CONFIG", "")
    config._instance = None
    assert config.get_config().as_dict() == before
    assert config.external_config_keys() == []


def test_external_config_keys_over_both_files(
    layers: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = _yaml(
        tmp_path / "a.yaml",
        {"llm": {"base_url": "http://10.0.0.9:1234/v1", "keep_alive_seconds": 30}},
    )
    second = _yaml(tmp_path / "b.yaml", {"tts": {"enabled": True}, "world": {"tick_interval_seconds": 9}})
    _point(monkeypatch, first, second)
    assert config.external_config_keys() == [
        "llm.base_url",
        "llm.keep_alive_seconds",
        "tts.enabled",
        "world.tick_interval_seconds",
    ]
    assert config.get_config().get("llm.base_url") == "http://10.0.0.9:1234/v1"
    assert [source for source, _ in config.external_config_layers()] == [str(first), str(second)]


def test_settings_says_what_the_external_file_shadows(
    layers: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    external = _yaml(tmp_path / "op.yaml", {"tts": {"enabled": False}})
    _point(monkeypatch, external)
    result = settings.apply_settings({"tts.enabled": True, "world.tick_interval_seconds": 5})
    assert result["ok"], result
    assert result["shadowed"] == ["tts.enabled"]
    # The file wins: the save "succeeded" and changed nothing it shadows.
    assert config.get_config().get("tts.enabled") is False


def test_settings_has_no_shadowed_key_when_nothing_is_shadowed(
    layers: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = settings.apply_settings({"world.tick_interval_seconds": 5})
    assert result["ok"], result
    assert "shadowed" not in result

    external = _yaml(tmp_path / "op.yaml", {"tts": {"enabled": False}})
    _point(monkeypatch, external)
    result = settings.apply_settings({"world.tick_interval_seconds": 6})
    assert result["ok"], result
    assert "shadowed" not in result


def test_settings_refuses_a_template_value(layers: Path) -> None:
    """
    Fix round 1 (review finding 7): since the load walk refuses a bad scope, a
    `${...}` the panel wrote would make every later `get_config` raise. The
    panel refuses one, in its own words, and never writes it.
    """
    result = settings.apply_settings({"stt.whisper.model": "${foo?env:X}"})
    assert "stt.whisper.model" in result["rejected"]
    assert result["rejected"]["stt.whisper.model"].startswith(
        "a ${...} reference cannot be set from the Settings panel"
    )
    local = layers / "local.yaml"
    assert "${" not in (local.read_text(encoding="utf-8") if local.exists() else "")
    config._instance = None
    config.get_config()


def test_settings_never_writes_a_tree_the_config_would_refuse(
    layers: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The second line: whatever passes coercion, a tree with a bad scope is not written."""
    local = _yaml(layers / "local.yaml", {"tts": {"voice": "keep-me"}})
    before = local.read_text(encoding="utf-8")
    monkeypatch.setattr(
        settings, "_coerce_setting", lambda spec, raw: (True, "${nope?env:X}", "")
    )
    result = settings.apply_settings({"stt.whisper.model": "anything"})
    assert result["ok"] is False
    assert "nope" in result["error"] and "stt.whisper.model" in result["error"]
    assert local.read_text(encoding="utf-8") == before
    config._instance = None
    config.get_config()


def test_the_post_route_carries_shadowed(
    layers: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from flask import Flask

    app = Flask(__name__)
    app.register_blueprint(settings.settings_blueprint())
    external = _yaml(tmp_path / "op.yaml", {"tts": {"enabled": False}})
    _point(monkeypatch, external)
    res = app.test_client().post("/api/settings", json={"changes": {"tts.enabled": True}})
    assert res.status_code == 200
    assert res.get_json()["shadowed"] == ["tts.enabled"]
