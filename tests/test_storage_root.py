"""
One storage root (v0.20.0 T3; spec §4.1, survey findings 2 and 4).

``engine/persistence/storage.py`` answers where the engine writes at run time:
``CLOCKWORK_DATA_DIR``, else ``storage.root``, a relative value taken against
``project_root()`` -- never the working directory. Until v0.20.0 saves
(``paths.saves``, used as-is) and generated media (``MEDIA_DIR``,
``IMAGE_DIR``, ``AUDIO_DIR``) were cwd-relative, so a launcher started from
another directory wrote saves there and served media that was not there.

Every file here lives under ``tmp_path``; ``_CONFIG_DIR`` points there, and no
test writes under the repository's ``data/``.
"""

from __future__ import annotations

import ast
import logging
import os
from pathlib import Path
from typing import Any, Iterator

import pytest
import yaml

import engine.config as config
from engine.persistence import storage

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture
def layers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """The real default.yaml, an empty temp config directory, no env layers."""
    directory = tmp_path / "config"
    directory.mkdir()
    for name in ("CLOCKWORK_ENV", "CLOCKWORK_CONFIG", "CLOCKWORK_DATA_DIR"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(config, "_CONFIG_DIR", directory)
    monkeypatch.setattr(config, "_DEFAULT_PATH", REPO / "config" / "default.yaml")
    monkeypatch.setattr(config, "_overlay", {})
    monkeypatch.setattr(config, "_instance", None)
    monkeypatch.setattr(storage, "_WARNED_ALIAS", None)
    yield directory
    config._instance = None


def _yaml(path: Path, data: dict[str, Any]) -> Path:
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    config._instance = None
    return path


def test_the_default_layout_is_v0_19s(layers: Path) -> None:
    """With the default root every path is byte-for-byte v0.19.0's, anchored at the repo."""
    root = config.project_root()
    assert storage.data_root() == root / "data"
    assert storage.saves_dir("", None) == root / "data" / "saves"
    assert storage.saves_dir("", "hue-and-cry") == root / "data" / "saves" / "hue-and-cry"
    assert storage.media_dir() == root / "data" / "media"
    assert storage.image_dir() == root / "data" / "media" / "images"
    assert storage.audio_dir() == root / "data" / "media" / "tts"
    assert storage.hosting_dir() == root / "data" / "hosting"
    # An account's saves (hosted mode) live under the root, apart from the owner's.
    assert storage.saves_dir("u1", "hue-and-cry") == (
        root / "data" / "users" / "u1" / "saves" / "hue-and-cry"
    )
    assert config.get_config().get("storage.root") == "data"
    # default.yaml no longer names a save path at all.
    default = yaml.safe_load((REPO / "config" / "default.yaml").read_text(encoding="utf-8"))
    assert "saves" not in default["paths"]


def test_clockwork_data_dir_beats_storage_root(
    layers: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _yaml(layers / "local.yaml", {"storage": {"root": str(tmp_path / "from-config")}})
    assert storage.data_root() == tmp_path / "from-config"
    monkeypatch.setenv("CLOCKWORK_DATA_DIR", str(tmp_path / "from-env"))
    assert storage.data_root() == tmp_path / "from-env"
    assert storage.image_dir() == tmp_path / "from-env" / "media" / "images"
    # Read on every call: unset again, the config answers again.
    monkeypatch.delenv("CLOCKWORK_DATA_DIR")
    assert storage.data_root() == tmp_path / "from-config"


def test_a_relative_root_is_taken_against_the_repo_not_the_cwd(
    layers: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Survey finding 2: saves AND media, from a working directory elsewhere.
    Fails on e7fdd26, where ``saves_base()`` was ``Path("data/saves")`` and the
    media constants ``Path("data/media")``, all relative to the cwd.
    """
    from engine.api.media import media_blueprint
    from engine.media import tts
    from engine.media.providers.base import ImageRequest, cached_image, target_path
    from engine.persistence.saves import SaveStore
    from engine.game.procgen import new_game_state

    store = tmp_path / "store"
    try:
        relative = os.path.relpath(store, config.project_root())
    except ValueError:
        pytest.skip("the temp directory is on another drive than the repository")
    assert not Path(relative).is_absolute()
    _yaml(layers / "local.yaml", {"storage": {"root": relative}})
    workdir = tmp_path / "cwd"
    workdir.mkdir()
    monkeypatch.chdir(workdir)

    # Saves: the owner's base, and a run written through a store built on it.
    base = storage.saves_dir("", None)
    assert Path(os.path.abspath(base)) == store / "saves"
    saves = SaveStore(root=storage.saves_dir("", "clockwork-dark"), slug="clockwork-dark")
    save_id = saves.save(new_game_state(player_name="Anchor", seed=3))
    assert (store / "saves" / "clockwork-dark" / save_id / "save.json").is_file()

    # Images: the cache the providers write and read.
    request = ImageRequest(subject_id="edgewood_square")
    path = target_path(request)
    assert Path(os.path.abspath(path)).parent == store / "media" / "images"
    path.write_bytes(b"\x89PNG not really")
    hit = cached_image(request)
    assert hit is not None and Path(hit.path) == path

    # Audio, and both routes serve what was written.
    url = tts.write_audio(b"RIFF", "a sentence")
    assert (store / "media" / "tts" / url.rsplit("/", 1)[1]).is_file()
    assert tts.cached_url("a sentence") == url

    from flask import Flask

    app = Flask(__name__)
    app.register_blueprint(media_blueprint())
    client = app.test_client()
    assert client.get(f"/api/media/images/{path.name}").status_code == 200
    assert client.get(url).status_code == 200

    assert not any(workdir.iterdir()), "something was written relative to the cwd"


_RETIRED = {"MEDIA_DIR", "IMAGE_DIR", "AUDIO_DIR"}


def _names(tree: ast.AST) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in _RETIRED:
            found.add(node.id)
        elif isinstance(node, ast.Attribute) and node.attr in _RETIRED:
            found.add(node.attr)
        elif isinstance(node, ast.alias) and (node.name in _RETIRED or node.asname in _RETIRED):
            found.add(node.name)
        elif isinstance(node, ast.Constant) and node.value in _RETIRED:
            found.add(str(node.value))  # an __all__ entry
    return found


def test_no_media_constant_survives() -> None:
    """
    The constants are DELETED, not aliased (spec §4.1): ``from ... import
    IMAGE_DIR`` bound the path at import, before ``CLOCKWORK_DATA_DIR`` could
    be read. No module in engine/ or scripts/ may name one.
    """
    offenders: dict[str, set[str]] = {}
    for top in ("engine", "scripts"):
        for path in sorted((REPO / top).rglob("*.py")):
            names = _names(ast.parse(path.read_text(encoding="utf-8"), filename=str(path)))
            if names:
                offenders[path.relative_to(REPO).as_posix()] = names
    assert not offenders, offenders


def test_the_scan_sees_a_constant() -> None:
    """The scan's canary: each shape the constants were used in is found."""
    source = (
        "MEDIA_DIR = 1\n"
        "from engine.media.providers.base import IMAGE_DIR as cache\n"
        "x = tts.AUDIO_DIR\n"
        "__all__ = ['IMAGE_DIR']\n"
    )
    assert _names(ast.parse(source)) == _RETIRED


def test_the_legacy_paths_saves_alias_warns_once_naming_its_file(
    layers: Path, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """
    A ``paths.saves`` in config/local.yaml is the EXACT local save base for one
    release (nothing appended), with ONE WARNING naming the file.
    """
    local = _yaml(layers / "local.yaml", {"paths": {"saves": str(tmp_path / "old-saves")}})
    with caplog.at_level(logging.WARNING, logger="engine.persistence.storage"):
        assert storage.saves_dir("", None) == tmp_path / "old-saves"
        assert storage.saves_dir("", "neon-city") == tmp_path / "old-saves" / "neon-city"
        assert storage.local_saves_base() == tmp_path / "old-saves"
    warnings = [r for r in caplog.records if r.name == "engine.persistence.storage"]
    assert len(warnings) == 1, [r.getMessage() for r in warnings]
    message = warnings[0].getMessage()
    assert str(local) in message and "v0.21.0" in message and "storage.root" in message
    assert storage.legacy_saves_alias() == (str(local), str(tmp_path / "old-saves"))
    # An account's saves are never moved by it.
    assert storage.saves_dir("u1", "neon-city") == (
        config.project_root() / "data" / "users" / "u1" / "saves" / "neon-city"
    )


def test_the_alias_from_clockwork_config_names_that_file(
    layers: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _yaml(layers / "local.yaml", {"paths": {"saves": "from-local"}})
    external = tmp_path / "operator.yaml"
    external.write_text(yaml.safe_dump({"paths": {"saves": "from-operator"}}), encoding="utf-8")
    monkeypatch.setenv("CLOCKWORK_CONFIG", str(external))
    config._instance = None
    assert storage.legacy_saves_alias() == (str(external), "from-operator")
    assert storage.local_saves_base() == config.project_root() / "from-operator"


def test_no_alias_no_warning(layers: Path, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="engine.persistence.storage"):
        assert storage.legacy_saves_alias() is None
        storage.saves_dir("", "clockwork-dark")
    assert not [r for r in caplog.records if r.name == "engine.persistence.storage"]


def test_the_doctor_reports_the_root_and_the_alias(
    layers: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location("doctor_storage", REPO / "scripts" / "doctor.py")
    doctor = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(doctor)

    # The row PROVES writability with a temp file (T3 fix round 1), so the
    # root is a temp directory here, never the repository's data/.
    root = tmp_path / "root"
    root.mkdir()
    monkeypatch.setenv("CLOCKWORK_DATA_DIR", str(root))
    report = doctor.Report()
    doctor._storage_rows(report)
    (row,) = [r for r in report.rows if r[1] == "storage"]
    assert row[2] == doctor.OK and row[3] == f"{root}: writable"
    assert list(root.iterdir()) == [], "the probe file was left behind"
    assert not [r for r in report.rows if r[1] == "legacy paths.saves"]

    # A root that cannot be written: the probe's own failure is the answer.
    import tempfile

    def refuse(*_a: Any, **_k: Any) -> Any:
        raise PermissionError(13, "Access is denied")

    with monkeypatch.context() as denied:
        denied.setattr(tempfile, "TemporaryFile", refuse)
        report = doctor.Report()
        doctor._storage_rows(report)
    (row,) = [r for r in report.rows if r[1] == "storage"]
    assert row[2] == doctor.FAIL and "Access is denied" in row[3]

    local = _yaml(layers / "local.yaml", {"paths": {"saves": "somewhere"}})
    report = doctor.Report()
    doctor._storage_rows(report)
    (alias,) = [r for r in report.rows if r[1] == "legacy paths.saves"]
    assert alias[2] == doctor.WARN
    assert str(local) in alias[3] and "v0.21.0" in alias[3]
