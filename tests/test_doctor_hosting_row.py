"""
The doctor's ``hosting`` and ``CLOCKWORK_CONFIG`` rows (v0.20.0 T2; spec
§3.6, §2.1).

Local mode binds ``127.0.0.1`` by default since v0.20.0 (the owner's
decision): the ``hosting`` row says so, OK. LAN play is one line in
``config/local.yaml`` (``scene.clockwork.host: "0.0.0.0"``), and then the row
is a WARN, because local mode has no login. The ``CLOCKWORK_CONFIG`` row names
each external file and the dotted keys it sets, never a value.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from typing import Any, Iterator

import pytest
import yaml

import engine.config as config

REPO = Path(__file__).resolve().parents[1]


def _doctor() -> Any:
    spec = importlib.util.spec_from_file_location(
        "doctor_hosting_under_test", REPO / "scripts" / "doctor.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


DOCTOR = _doctor()

WARN_TEXT = (
    "anyone who can reach port 5573 can play, load and delete runs, with no "
    "login; bind 127.0.0.1, or turn on hosting (docs/HOSTING.md)"
)


@pytest.fixture
def cfg_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    directory = tmp_path / "config"
    directory.mkdir()
    for name in ("CLOCKWORK_ENV", "CLOCKWORK_CONFIG", "CLOCKWORK_LLM_API_KEY", "LMSTUDIO_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(config, "_CONFIG_DIR", directory)
    monkeypatch.setattr(config, "_DEFAULT_PATH", REPO / "config" / "default.yaml")
    monkeypatch.setattr(config, "_overlay", {})
    monkeypatch.setattr(config, "_instance", None)
    yield directory
    config._instance = None


def _rows(name: str) -> list[tuple[str, str, str, str]]:
    report = DOCTOR.Report()
    DOCTOR.check_config(report)
    return [row for row in report.rows if row[1] == name]


def _host(directory: Path, host: str) -> None:
    (directory / "local.yaml").write_text(
        yaml.safe_dump({"scene": {"clockwork": {"host": host}}}), encoding="utf-8"
    )
    config._instance = None


def test_the_shipped_bind_is_loopback_and_ok(cfg_dir: Path) -> None:
    assert config.get_config().get("scene.clockwork.host") == "127.0.0.1"
    assert _rows("hosting") == [
        ("Config", "hosting", DOCTOR.OK, "local single-player on 127.0.0.1")
    ]


@pytest.mark.parametrize("host", ["localhost", "::1", "127.0.0.2"])
def test_any_loopback_address_is_ok(cfg_dir: Path, host: str) -> None:
    _host(cfg_dir, host)
    assert _rows("hosting") == [("Config", "hosting", DOCTOR.OK, f"local single-player on {host}")]


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.20", "::", "my-desktop"])
def test_a_non_loopback_bind_warns(cfg_dir: Path, host: str) -> None:
    _host(cfg_dir, host)
    assert _rows("hosting") == [("Config", "hosting", DOCTOR.WARN, WARN_TEXT)]


def test_the_warning_names_the_configured_port(cfg_dir: Path) -> None:
    (cfg_dir / "local.yaml").write_text(
        yaml.safe_dump({"scene": {"clockwork": {"host": "0.0.0.0", "port": 6001}}}),
        encoding="utf-8",
    )
    config._instance = None
    (row,) = _rows("hosting")
    assert row[2] == DOCTOR.WARN and "reach port 6001" in row[3]


def _launch(monkeypatch: pytest.MonkeyPatch, argv: list[str]) -> tuple[str, list[dict[str, Any]]]:
    """``launcher.main(argv)`` with no stack and ``run_scene`` stubbed."""
    import contextlib
    import io

    import launcher
    from engine.scenes import default_scene

    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(default_scene, "run_scene", lambda **kw: calls.append(dict(kw)))
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        assert launcher.main(["--no-stack", *argv]) == 0
    return out.getvalue(), calls


def test_the_launcher_warns_on_a_non_loopback_host(
    cfg_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fix round 1 (review finding 9): `--host 0.0.0.0` is said, as the doctor says it."""
    text, calls = _launch(monkeypatch, ["--host", "0.0.0.0"])
    assert calls == [{"host": "0.0.0.0", "port": None}]
    assert f"WARNING: bound to 0.0.0.0 - {WARN_TEXT}" in text


def test_the_launcher_warns_on_a_configured_lan_bind(
    cfg_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _host(cfg_dir, "0.0.0.0")
    text, _ = _launch(monkeypatch, [])
    assert WARN_TEXT in text


def test_the_launcher_is_quiet_on_loopback(cfg_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    text, calls = _launch(monkeypatch, [])
    assert calls == [{"host": None, "port": None}]
    assert "WARNING" not in text
    text, _ = _launch(monkeypatch, ["--host", "127.0.0.1"])
    assert "WARNING" not in text


def test_the_brief_no_longer_shows_the_old_bind() -> None:
    brief = (REPO / "docs" / "CLAUDE_CODE_BRIEF.md").read_text(encoding="utf-8")
    assert 'host: "0.0.0.0"' not in brief.split("## §9", 1)[1].split("```", 2)[1]


def test_no_external_file_no_row(cfg_dir: Path) -> None:
    assert _rows("CLOCKWORK_CONFIG") == []


def test_the_external_row_lists_keys_and_never_values(
    cfg_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret = "sk-very-secret-value"
    first = tmp_path / "op.yaml"
    first.write_text(
        yaml.safe_dump({"llm": {"api_key": secret, "base_url": "http://10.9.8.7:1234/v1"}}),
        encoding="utf-8",
    )
    second = tmp_path / "more.yaml"
    second.write_text(yaml.safe_dump({"tts": {"enabled": True}}), encoding="utf-8")
    monkeypatch.setenv("CLOCKWORK_CONFIG", os.pathsep.join([str(first), str(second)]))
    config._instance = None
    report = DOCTOR.Report()
    DOCTOR.check_config(report)
    rows = [row for row in report.rows if row[1] == "CLOCKWORK_CONFIG"]
    assert [row[2] for row in rows] == [DOCTOR.OK, DOCTOR.OK]
    assert rows[0][3].startswith(f"{first}: sets llm.api_key, llm.base_url")
    assert rows[1][3].startswith(f"{second}: sets tts.enabled")
    rendered = report.render()
    assert secret not in rendered
    assert "10.9.8.7" not in rendered
