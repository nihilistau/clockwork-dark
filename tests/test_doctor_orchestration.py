"""
The doctor's orchestration rows (v0.20.0 T10, spec §7.4).

``hosting.stories``: with hosting on, each slug is shown (OK), a slug the
registry does not know or that does not validate is a FAIL, and so is an
empty list. With hosting off there is no row (local mode's doctor output is
v0.19.0's). The doctor reads the config only: it holds no bus token and asks
the live supervisor nothing. The ``metrics store`` row (v0.20.0 T17) names
the store's path, whether it can be written and the retention, and never
opens the store.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any, Iterator

import pytest
import yaml

import engine.config as config

REPO = Path(__file__).resolve().parents[1]


def _doctor() -> Any:
    spec = importlib.util.spec_from_file_location(
        "doctor_orchestration_under_test", REPO / "scripts" / "doctor.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


DOCTOR = _doctor()


@pytest.fixture
def cfg_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    directory = tmp_path / "config"
    directory.mkdir()
    for name in ("CLOCKWORK_ENV", "CLOCKWORK_CONFIG", "CLOCKWORK_SECRET_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("CLOCKWORK_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(config, "_CONFIG_DIR", directory)
    monkeypatch.setattr(config, "_DEFAULT_PATH", REPO / "config" / "default.yaml")
    monkeypatch.setattr(config, "_overlay", {})
    monkeypatch.setattr(config, "_instance", None)
    yield directory
    config._instance = None


def _hosting(directory: Path, **block: Any) -> None:
    (directory / "local.yaml").write_text(
        yaml.safe_dump({"hosting": {"enabled": True, **block}}), encoding="utf-8"
    )
    config._instance = None


def _rows() -> list[tuple[str, str, str, str]]:
    report = DOCTOR.Report()
    DOCTOR.check_config(report)
    return [row for row in report.rows if row[1] == "hosting.stories"]


def test_no_row_in_local_mode(cfg_dir: Path) -> None:
    assert _rows() == []


def test_each_known_story_is_shown_ok(cfg_dir: Path) -> None:
    _hosting(cfg_dir, stories=["clockwork-dark", "hue-and-cry"])
    assert _rows() == [
        ("Config", "hosting.stories", DOCTOR.OK, "clockwork-dark, hue-and-cry - one worker process each")
    ]


def test_an_unknown_slug_fails(cfg_dir: Path) -> None:
    _hosting(cfg_dir, stories=["clockwork-dark", "no-such-story"])
    (row,) = _rows()
    assert row[2] == DOCTOR.FAIL
    assert row[3].startswith("'no-such-story' is not an installed story")


def test_a_story_that_does_not_validate_fails(cfg_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from engine.games import registry

    real = registry.validate
    monkeypatch.setattr(
        registry,
        "validate",
        lambda manifest: ["title is empty"] if manifest.slug == "hue-and-cry" else real(manifest),
    )
    _hosting(cfg_dir, stories=["clockwork-dark", "hue-and-cry"])
    assert _rows() == [
        ("Config", "hosting.stories", DOCTOR.FAIL, "'hue-and-cry' does not validate: title is empty")
    ]


def test_an_empty_list_fails(cfg_dir: Path) -> None:
    _hosting(cfg_dir, stories=[])
    (row,) = _rows()
    assert row[2] == DOCTOR.FAIL and row[3].startswith("is empty")


# -- hosting.threads, restated for the front door (v0.20.0 T12, spec §6.9, §7.4) -------


def _threads_rows() -> list[tuple[str, str, str, str]]:
    report = DOCTOR.Report()
    DOCTOR.check_config(report)
    return [row for row in report.rows if row[1] == "hosting.threads"]


def test_no_threads_row_in_local_mode(cfg_dir: Path) -> None:
    assert _threads_rows() == []


def test_the_threads_row_counts_the_front_door_s_sockets(cfg_dir: Path) -> None:
    """
    Each open WebSocket pins a thread in the front door AND in its worker, and
    the front door carries every story's: about (threads - 4) / 2 players with
    two tabs each across ALL the stories, 4 threads kept for HTTP. Fails on
    3a7da4f, which had no such row. Since T13 the row says the long holds are
    capped, which is what makes the reserve true
    (``test_open_websockets_never_take_the_threads_kept_for_http``).
    """
    _hosting(cfg_dir, stories=["clockwork-dark", "hue-and-cry"])
    assert _threads_rows() == [
        (
            "Config",
            "hosting.threads",
            DOCTOR.OK,
            "32 per process; the front door carries every story's WebSockets (each pins a "
            "thread there and one in its worker), so about 14 players with two tabs each "
            "across all 2 stories; open WebSockets, polls and HTTP turns together hold at "
            "most 28 (one more is refused at once), at most 4 of them one account's, leaving 4 "
            "threads for HTTP",
        )
    ]


def test_too_few_threads_warn(cfg_dir: Path) -> None:
    _hosting(cfg_dir, stories=["clockwork-dark"], threads=6)
    (row,) = _threads_rows()
    assert row[2] == DOCTOR.WARN
    assert "about 1 players" in row[3] and "below 8" in row[3]


# -- the admins and the admin layer (v0.20.0 T14, spec §7.4, §14.9) ---------------------


def _admin_rows() -> list[tuple[str, str, str, str]]:
    report = DOCTOR.Report()
    DOCTOR.check_config(report)
    return [row for row in report.rows if row[1] in ("admins", "admin layer")]


def test_no_admin_rows_in_local_mode(cfg_dir: Path) -> None:
    assert _admin_rows() == []


def test_the_admins_row_counts_enabled_admins_and_warns_at_zero(cfg_dir: Path, tmp_path: Path) -> None:
    from engine.hosting.accounts import AccountStore

    _hosting(cfg_dir)
    store = AccountStore(tmp_path / "data" / "hosting")
    store.add("player", "pw-0123456789")
    (row,) = [r for r in _admin_rows() if r[1] == "admins"]
    assert row[2] == DOCTOR.WARN and "python scripts/users.py admin <name> on" in row[3]
    store.add("root", "pw-0123456789", admin=True)
    store.add("gone", "pw-0123456789", admin=True)
    store.disable("gone")
    (row,) = [r for r in _admin_rows() if r[1] == "admins"]
    assert row[2] == DOCTOR.OK and row[3].startswith("1 enabled admin")


def test_the_admin_layer_rows_name_its_keys_never_its_values(
    cfg_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    layer = tmp_path / "data" / "hosting" / "admin.yaml"
    _hosting(cfg_dir)
    (row,) = [r for r in _admin_rows() if r[1] == "admin layer"]
    assert row[2] == DOCTOR.OK and "none yet" in row[3]
    layer.parent.mkdir(parents=True, exist_ok=True)
    layer.write_text(
        yaml.safe_dump({"llm": {"base_url": "http://value-never-shown.internal:8000/v1", "context_tokens": 4096}}),
        encoding="utf-8",
    )
    operator = tmp_path / "op.yaml"
    operator.write_text(yaml.safe_dump({"llm": {"context_tokens": 2048}}), encoding="utf-8")
    monkeypatch.setenv("CLOCKWORK_CONFIG", str(operator))
    config._instance = None
    rows = [r for r in _admin_rows() if r[1] == "admin layer"]
    assert rows[0] == ("Config", "admin layer", DOCTOR.OK, f"{layer}: sets llm.base_url, llm.context_tokens")
    assert rows[1:] == [
        ("Config", "admin layer", DOCTOR.WARN, f"the panel's edit of llm.context_tokens is overridden by {operator}")
    ]
    assert not [r for r in rows if "value-never-shown" in r[3] or "4096" in r[3]]


def _metrics_rows() -> list[tuple[str, str, str, str]]:
    report = DOCTOR.Report()
    DOCTOR.check_config(report)
    return [row for row in report.rows if row[1] == "metrics store"]


def test_no_metrics_store_row_in_local_mode(cfg_dir: Path) -> None:
    assert _metrics_rows() == []


def test_the_metrics_store_row_names_its_path_and_whether_it_can_be_written(
    cfg_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """v0.20.0 T17 (spec §7.4): the path, writable or not, the retention. Fails on 7e38c54: no such row."""
    path = tmp_path / "data" / "hosting" / "metrics.sqlite3"
    _hosting(cfg_dir)
    (row,) = _metrics_rows()
    assert row[2] == DOCTOR.OK and row[3].startswith(f"{path}: not made yet")
    assert "rows kept 30 days, at most 512 MB" in row[3]
    assert not path.exists(), "the doctor made the store"
    from engine.hosting.supervisor.metrics import MetricsStore

    MetricsStore(path, retention_days=30).open().close()
    (row,) = _metrics_rows()
    assert row[2] == DOCTOR.OK and " bytes, " in row[3]
    monkeypatch.setattr(DOCTOR, "_writable", lambda _directory: (False, "cannot write in it"))
    (row,) = _metrics_rows()
    # Best effort (fix round 1, I2): the supervisor runs without metrics, so a WARN.
    assert row[2] == DOCTOR.WARN and str(path) in row[3] and "cannot write in it" in row[3]


def test_a_store_that_will_not_open_is_a_warn_and_the_doctor_leaves_it(cfg_dir: Path, tmp_path: Path) -> None:
    """T17 fix round 1 (I2): a torn file is a WARN, never a FAIL; the doctor changes nothing."""
    path = tmp_path / "data" / "hosting" / "metrics.sqlite3"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"not a database, torn by a power cut" * 100)
    _hosting(cfg_dir)
    (row,) = _metrics_rows()
    assert row[2] == DOCTOR.WARN and "moves it aside" in row[3]
    assert path.read_bytes().startswith(b"not a database")
    assert sorted(p.name for p in path.parent.iterdir()) == ["metrics.sqlite3"]


def test_a_key_outside_the_allowlist_fails_the_admin_layer_row(cfg_dir: Path, tmp_path: Path) -> None:
    layer = tmp_path / "data" / "hosting" / "admin.yaml"
    layer.parent.mkdir(parents=True, exist_ok=True)
    layer.write_text(yaml.safe_dump({"hosting": {"enabled": True}}), encoding="utf-8")
    _hosting(cfg_dir)
    rows = _admin_rows()
    assert len(rows) == 1 and rows[0][2] == DOCTOR.FAIL
    assert "hosting.enabled" in rows[0][3] and str(layer) in rows[0][3]
