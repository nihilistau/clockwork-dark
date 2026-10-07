"""
The admin layer: the admin panel's edits, ``<data root>/hosting/admin.yaml``
(v0.20.0 T14, spec §14.9, §2.1).

- its RANK: it beats ``config/local.yaml`` and loses to ``CLOCKWORK_CONFIG``
  and the game overlay;
- it is read whenever hosting is on and the file exists, whatever the
  environment (no variable selects it), and hosting turned on in
  ``CLOCKWORK_CONFIG`` still loads it (the two passes);
- with hosting off it is NEVER read: a layer file under the data root
  changes nothing, and ``get_config()`` equals the config built with the
  layer's code path taken out;
- a layer setting ``hosting.enabled`` (outside the allowlist), any key
  outside the allowlist and a file that does not parse each raise, naming
  them; ``admin_layer_keys()`` lists its keys (after the legacy alias).

``_CONFIG_DIR`` and ``CLOCKWORK_DATA_DIR`` point under ``tmp_path``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator

import pytest
import yaml

import engine.config as config

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture
def layers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    directory = tmp_path / "config"
    directory.mkdir()
    for name in ("CLOCKWORK_ENV", "CLOCKWORK_CONFIG", "CLOCKWORK_LLM_API_KEY", "LMSTUDIO_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("CLOCKWORK_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(config, "_CONFIG_DIR", directory)
    monkeypatch.setattr(config, "_DEFAULT_PATH", REPO / "config" / "default.yaml")
    monkeypatch.setattr(config, "_overlay", {})
    monkeypatch.setattr(config, "_instance", None)
    yield directory
    config._instance = None


def _yaml(path: Path, data: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


def _admin(tmp_path: Path, data: Any) -> Path:
    return _yaml(tmp_path / "data" / "hosting" / "admin.yaml", data)


def _local(layers: Path, **tree: Any) -> None:
    _yaml(layers / "local.yaml", tree)
    config._instance = None


def test_the_rank_beats_local_and_loses_to_clockwork_config_and_the_overlay(
    layers: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _local(layers, hosting={"enabled": True}, llm={"context_tokens": 1111, "lanes": {"narration": 2, "utility": 2}})
    _admin(tmp_path, {"llm": {"context_tokens": 2222, "lanes": {"narration": 3, "utility": 4}}})
    cfg = config.get_config()
    assert cfg.get("llm.context_tokens") == 2222 and cfg.get("llm.lanes.narration") == 3
    operator = _yaml(tmp_path / "op.yaml", {"llm": {"context_tokens": 3333}})
    monkeypatch.setenv("CLOCKWORK_CONFIG", str(operator))
    config._instance = None
    cfg = config.get_config()
    assert cfg.get("llm.context_tokens") == 3333 and cfg.get("llm.lanes.utility") == 4
    monkeypatch.setattr(config, "_overlay", {"llm": {"lanes": {"utility": 9}}})
    config._instance = None
    assert config.get_config().get("llm.lanes.utility") == 9
    assert config.admin_layer_keys() == ["llm.context_tokens", "llm.lanes.narration", "llm.lanes.utility"]


def test_it_is_read_with_no_variable_when_hosting_is_on(layers: Path, tmp_path: Path) -> None:
    _local(layers, hosting={"enabled": True})
    path = _admin(tmp_path, {"llm": {"base_url": "http://model.internal:8000/v1"}})
    assert config.get_config().get("llm.base_url") == "http://model.internal:8000/v1"
    assert config.admin_layer() == (str(path), ["llm.base_url"])


def test_hosting_on_in_clockwork_config_still_loads_it(
    layers: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The first pass sees hosting on in the operator's file, so the second merges the layer."""
    operator = _yaml(tmp_path / "op.yaml", {"hosting": {"enabled": True}})
    monkeypatch.setenv("CLOCKWORK_CONFIG", str(operator))
    _admin(tmp_path, {"llm": {"prefer_native": False}})
    config._instance = None
    assert config.get_config().get("llm.prefer_native") is False


def test_the_root_comes_from_storage_root_when_the_variable_is_unset(
    layers: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CLOCKWORK_DATA_DIR")
    root = tmp_path / "elsewhere"
    _local(layers, hosting={"enabled": True}, storage={"root": str(root)})
    _yaml(root / "hosting" / "admin.yaml", {"llm": {"context_tokens": 4444}})
    assert config.get_config().get("llm.context_tokens") == 4444


def test_with_hosting_off_it_is_never_read(
    layers: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _local(layers, llm={"context_tokens": 1111})
    without = config.get_config().as_dict()
    assert config.admin_layer() is None and config.admin_layer_keys() == []
    # A layer file under the data root -- even one that would refuse to load.
    _admin(tmp_path, {"llm": {"context_tokens": 2222}, "hosting": {"enabled": True}})
    config._instance = None
    reads: list[Any] = []
    real = config._load_admin_layer
    monkeypatch.setattr(config, "_load_admin_layer", lambda path: reads.append(path) or real(path))
    assert config.get_config().as_dict() == without
    assert config.get_config().get("llm.context_tokens") == 1111
    assert reads == []
    # And the same tree with the layer's code path taken out entirely.
    monkeypatch.setattr(config, "_truthy_path", lambda _data, _dotted: False)
    config._instance = None
    assert config.get_config().as_dict() == without


@pytest.mark.parametrize(
    ("layer", "named"),
    [
        ({"hosting": {"enabled": True}}, "hosting.enabled"),
        ({"llm": {"api_key": "sk-not-in-the-allowlist"}}, "llm.api_key"),
        ({"llm": {"profiles": {"small": {"model": "x"}}}}, "llm.profiles.small.model"),
        ({"stack": {"services": {}}, "speech": {"voice": "x"}}, "speech.voice"),
    ],
)
def test_a_key_outside_the_allowlist_raises_naming_it(
    layers: Path, tmp_path: Path, layer: dict[str, Any], named: str
) -> None:
    _local(layers, hosting={"enabled": True})
    path = _admin(tmp_path, layer)
    with pytest.raises(ValueError) as caught:
        config.get_config()
    message = str(caught.value)
    assert named in message and str(path) in message and "admin layer" in message
    assert "sk-not-in-the-allowlist" not in message, "a value reached the message"


def test_an_unparsable_layer_raises_naming_the_file(layers: Path, tmp_path: Path) -> None:
    _local(layers, hosting={"enabled": True})
    path = tmp_path / "data" / "hosting" / "admin.yaml"
    path.parent.mkdir(parents=True)
    path.write_text("llm: [unclosed\n  base_url: secret-ish\n", encoding="utf-8")
    with pytest.raises(ValueError) as caught:
        config.get_config()
    assert str(path) in str(caught.value) and "does not parse" in str(caught.value)
    assert "secret-ish" not in str(caught.value)
    path.write_text("- a list\n", encoding="utf-8")
    config._instance = None
    with pytest.raises(ValueError, match="not a mapping"):
        config.get_config()


def test_a_legacy_block_is_refused_before_the_allowlist(layers: Path, tmp_path: Path) -> None:
    _local(layers, hosting={"enabled": True})
    path = _admin(tmp_path, {"lmstudio": {"base_url": "http://legacy.internal:1234/v1"}})
    with pytest.raises(config.LegacyConfigError) as caught:
        config.get_config()
    assert [(s, k) for s, k, _ in caught.value.findings] == [(str(path), "lmstudio")]


def test_every_allowlisted_key_loads(layers: Path, tmp_path: Path) -> None:
    from engine.hosting.admin.model import EDITABLE

    _local(layers, hosting={"enabled": True})
    tree: dict[str, Any] = {}
    shipped = config.get_config()
    for dotted in sorted(EDITABLE):
        node = tree
        parts = dotted.split(".")
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = shipped.get(dotted)
    _admin(tmp_path, tree)
    config._instance = None
    assert config.admin_layer_keys() == sorted(EDITABLE)
    assert not any(key.startswith("hosting.") for key in EDITABLE)
