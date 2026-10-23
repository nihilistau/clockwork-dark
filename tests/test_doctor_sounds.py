"""scripts/doctor.py's engine-sounds row (v0.24.0 T3): OK on the shipped file, FAIL naming the fault on a broken one."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]


def _doctor() -> Any:
    spec = importlib.util.spec_from_file_location("doctor_sounds_under_test", REPO / "scripts" / "doctor.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


DOCTOR = _doctor()


def _row(report) -> tuple[str, str, str, str]:
    rows = [r for r in report.rows if r[0] == "UI" and r[1] == "engine sounds"]
    assert len(rows) == 1, report.rows
    return rows[0]


def test_the_shipped_sounds_are_ok() -> None:
    report = DOCTOR.Report()
    DOCTOR.check_ui(report)
    assert _row(report)[2] == DOCTOR.OK


def test_a_broken_sounds_file_fails_naming_its_key(tmp_path, monkeypatch) -> None:
    from engine.games import sounds

    (tmp_path / "sounds.yaml").write_text("version: 1\nlimits: {}\nsounds: {}\nbind: {}\n", encoding="utf-8")
    monkeypatch.setattr(sounds, "engine_root", lambda: tmp_path)
    report = DOCTOR.Report()
    DOCTOR.check_ui(report)
    row = _row(report)
    assert row[2] == DOCTOR.FAIL and "bind.ui.press" in row[3]
