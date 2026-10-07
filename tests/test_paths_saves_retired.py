"""
``paths.saves`` retires from the manifests (v0.20.0 T3; spec §4.2, survey
finding 4, v0.19.0 carried item 3).

Activation installed a manifest's whole ``paths:`` block as the TOP config
layer, and all six shipped manifests restated ``saves: "data/saves"``, so
``config/local.yaml`` could not move saves. Saves are the engine's now: they
live under ``storage.root``. A manifest that still declares the key:

- is not a ``registry.validate`` problem (that would make the story
  unplayable);
- gets an ADVISORY from the content validator and the doctor, which also says
  when the value itself (not ``data/saves``) is ignored;
- cannot move saves: ``config_overlay`` drops it and ``paths.*`` lookups never
  answer from it.

``storage`` is refused as a story setting, with a reason.

Every file here lives under ``tmp_path``: the config directory and the
``games/`` a temp story is discovered from.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
from pathlib import Path
from typing import Any, Iterator

import pytest
import yaml

import engine.config as config
from engine.games import manifest as manifest_module
from engine.games import registry
from engine.persistence import storage

REPO = Path(__file__).resolve().parents[1]
SLUG = "keeps-a-saves-key"


def _load_script(name: str) -> Any:
    spec = importlib.util.spec_from_file_location(f"{name}_retired", REPO / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def layers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    directory = tmp_path / "config"
    directory.mkdir()
    for name in ("CLOCKWORK_ENV", "CLOCKWORK_CONFIG", "CLOCKWORK_DATA_DIR", "CLOCKWORK_GAME"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(config, "_CONFIG_DIR", directory)
    monkeypatch.setattr(config, "_DEFAULT_PATH", REPO / "config" / "default.yaml")
    monkeypatch.setattr(config, "_overlay", {})
    monkeypatch.setattr(config, "_instance", None)
    yield directory
    config._instance = None


def _story(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, saves: str, **extra: Any) -> str:
    """A minimal temp story that still declares ``paths.saves``."""
    directory = tmp_path / "games" / SLUG
    directory.mkdir(parents=True)
    data: dict[str, Any] = {
        "id": SLUG,
        "title": "A Story That Keeps Its Saves Key",
        "paths": {"saves": saves, "lore_db": str(tmp_path / "lore.db")},
        "entry": {"location_id": "nowhere", "archetypes": []},
        **extra,
    }
    directory.joinpath("game.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")
    monkeypatch.setattr(registry, "games_root", lambda: tmp_path / "games")
    return SLUG


def _manifests() -> list[Path]:
    return sorted((REPO / "games").glob("*/game.yaml")) + sorted(
        (REPO / "scripts" / "story_template").glob("*/game.yaml")
    )


def test_no_shipped_manifest_or_template_declares_it() -> None:
    found = _manifests()
    assert len(found) == 9, [p.relative_to(REPO).as_posix() for p in found]
    for path in found:
        data = yaml.safe_load(path.read_text(encoding="utf-8").replace("{{slug}}", "x-y"))
        assert "saves" not in (data.get("paths") or {}), path.relative_to(REPO).as_posix()


def test_it_is_not_a_validate_problem(layers: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    No PARENT check any more either: a value whose parent does not exist was a
    problem that made the story unplayable (it is not an output path now).
    """
    _story(tmp_path, monkeypatch, str(tmp_path / "no" / "such" / "saves"))
    found = registry.get(SLUG)
    assert found is not None
    assert registry.validate(found) == []
    assert found.config_overlay()["paths"] == {"lore_db": str(tmp_path / "lore.db")}


def test_the_content_validator_gives_the_advisory(
    layers: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from engine.games import validation

    _story(tmp_path, monkeypatch, "elsewhere/saves")
    issues = validation.validate_story(SLUG)
    retired = [i for i in issues if i.ref_id == "paths.saves"]
    assert len(retired) == 1 and retired[0].severity == "warning"
    assert "no longer a story key" in retired[0].message
    assert "'elsewhere/saves' is ignored" in retired[0].message

    script = _load_script("validate_content")
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        script.main(["--game", SLUG, "--warnings"])
    (line,) = [ln for ln in out.getvalue().splitlines() if "paths.saves" in ln]
    # An advisory, not an error.
    assert line.startswith("[warning] game.yaml: paths.saves -- paths.saves is no longer"), line


def test_the_advisory_names_the_value_only_when_it_differs(
    layers: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _story(tmp_path, monkeypatch, "data/saves")
    ((key, note),) = registry.get(SLUG).retired_paths()
    assert key == "saves"
    assert "storage.root" in note and "is ignored: saves do not go there" not in note


def test_the_doctor_gives_the_advisory(layers: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _story(tmp_path, monkeypatch, "elsewhere/saves")
    doctor = _load_script("doctor")
    report = doctor.Report()
    doctor.check_games(report)
    rows = [r for r in report.rows if r[1] == SLUG and "paths.saves" in r[3]]
    assert len(rows) == 1 and rows[0][2] == doctor.WARN, report.rows
    assert "storage.root" in rows[0][3]
    # And the story is still playable: no FAIL row for it.
    assert not [r for r in report.rows if SLUG in r[1] and r[2] == doctor.FAIL]


def test_it_cannot_move_saves(layers: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Fails on e7fdd26, where the activated manifest's ``paths.saves`` was the
    top config layer and outranked ``config/local.yaml``: ``storage.root``
    decides (an owner's ``paths.saves`` is refused since v0.21.0), the
    manifest never does.
    """
    manifest_saves = str(tmp_path / "from-the-manifest")
    _story(tmp_path, monkeypatch, manifest_saves)
    registry.activate(SLUG)
    try:
        cfg = config.get_config()
        assert cfg.get("paths.saves") in (None, "")
        assert "saves" not in cfg.section("paths")
        assert storage.local_saves_base() == config.project_root() / "data" / "saves"

        (layers / "local.yaml").write_text(
            yaml.safe_dump({"paths": {"saves": str(tmp_path / "from-local-yaml")}}), encoding="utf-8"
        )
        config._instance = None
        with pytest.raises(config.LegacyConfigError):
            config.get_config()
    finally:
        registry.deactivate()


def test_storage_is_refused_as_a_story_setting(
    layers: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _story(tmp_path, monkeypatch, "data/saves", settings={"storage": {"root": str(tmp_path / "x")}})
    found = registry.get(SLUG)
    reason = manifest_module.refusal_reason("storage.root")
    assert "belongs to the machine" in reason and "saves" in reason
    assert found.refused_settings() == {"storage.root": reason}
    assert any("storage.root" in problem for problem in registry.validate(found))
    assert "storage" not in found.config_overlay()
