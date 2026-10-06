"""
The doctor's ``platform`` row (v0.20.0 T4; spec §3.6).

``check_python`` names the system and its release as a person would (Windows
11 answers "10" to ``platform.release()``, so the build decides), and whether
filenames differ by case UNDER THE CHECKOUT: a temporary directory is made in
the repository root, probed and removed. The checkout is the filesystem that
matters -- a Docker Desktop bind mount of NTFS is case-insensitive inside a
Linux container whose ``/tmp`` is not (fix round 1, review finding 9).

Both answers are supported platforms (AGENTS.md rule 11), so the row is OK
either way: it is there so a report from someone else's machine says which
kind it came from.
"""

from __future__ import annotations

import importlib.util
import platform
import re
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]


def _doctor() -> Any:
    spec = importlib.util.spec_from_file_location(
        "doctor_platform_under_test", REPO / "scripts" / "doctor.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


DOCTOR = _doctor()

ROW = re.compile(
    r"^(?P<release>.+), "
    r"(?P<case>case-(?:in)?sensitive filesystem under the checkout"
    r"|case-(?:in)?sensitive filesystem under the storage root .+ \(the checkout could not be probed\)"
    r"|filesystem case unknown \(probe under the checkout(?: and the storage root)? failed\))$"
)


def _leftovers() -> list[Path]:
    return sorted(REPO.glob(".clockwork-case-probe-*"))


def test_the_platform_row_follows_python_and_is_ok(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(DOCTOR, "REPO_ROOT", tmp_path)
    report = DOCTOR.Report()
    DOCTOR.check_python(report)
    names = [name for _, name, _, _ in report.rows]
    assert names[:2] == ["python", "platform"]
    section, _, status, detail = report.rows[1]
    assert (section, status) == ("Runtime", DOCTOR.OK)
    match = ROW.match(detail)
    assert match, detail
    assert match["release"] == DOCTOR.os_release()


def test_the_release_names_windows_11_by_its_build(monkeypatch: pytest.MonkeyPatch) -> None:
    """Windows 11 says "10" to platform.release(); build 22000 and later is 11."""

    class Version:
        def __init__(self, build: int) -> None:
            self.build = build

    monkeypatch.setattr(platform, "system", lambda: "Windows")
    monkeypatch.setattr(platform, "release", lambda: "10")
    monkeypatch.setattr(sys, "getwindowsversion", lambda: Version(26200), raising=False)
    assert DOCTOR.os_release() == "Windows 11 (build 26200)"
    monkeypatch.setattr(sys, "getwindowsversion", lambda: Version(19045), raising=False)
    assert DOCTOR.os_release() == "Windows 10 (build 19045)"


def test_elsewhere_the_release_is_platform_release(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    monkeypatch.setattr(platform, "release", lambda: "6.18.33.2-microsoft-standard-WSL2")
    assert DOCTOR.os_release() == "Linux 6.18.33.2-microsoft-standard-WSL2"


def test_the_probe_matches_the_filesystem(tmp_path: Path) -> None:
    """The answer agrees with a direct look at a file in the same directory,
    and the probe leaves nothing behind."""
    probe = tmp_path / "MixedCase"
    probe.write_text("", encoding="utf-8")
    expected = not (tmp_path / "mixedcase").exists()
    assert DOCTOR.case_sensitive_filesystem(tmp_path) is expected
    assert list(tmp_path.iterdir()) == [probe]


def test_by_default_it_probes_under_the_checkout_and_cleans_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import tempfile

    seen: list[Any] = []
    real = tempfile.TemporaryDirectory

    def spy(*args: Any, **kwargs: Any) -> Any:
        seen.append(kwargs.get("dir"))
        return real(*args, **kwargs)

    before = _leftovers()
    monkeypatch.setattr(tempfile, "TemporaryDirectory", spy)
    assert DOCTOR.case_sensitive_filesystem() in (True, False)
    assert seen == [DOCTOR.REPO_ROOT]
    assert DOCTOR.REPO_ROOT == REPO
    assert _leftovers() == before


def test_a_read_only_checkout_is_probed_under_the_storage_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    v0.20.0 T5 (T4 re-review): a read-only checkout (an image's ``/app``)
    cannot hold the probe, and the row said "unknown". It falls back to the
    storage root, which the engine writes anyway, and says so.
    """
    monkeypatch.setattr(DOCTOR, "REPO_ROOT", tmp_path / "read-only-checkout")
    root = tmp_path / "storage"
    root.mkdir()
    monkeypatch.setenv("CLOCKWORK_DATA_DIR", str(root))
    detail = DOCTOR.platform_detail()
    assert ROW.match(detail), detail
    assert f"filesystem under the storage root {root} (the checkout could not be probed)" in detail
    assert list(root.iterdir()) == [], "the probe cleans up after itself"

    monkeypatch.setenv("CLOCKWORK_DATA_DIR", str(tmp_path / "no-storage-either"))
    assert DOCTOR.platform_detail().endswith(
        "filesystem case unknown (probe under the checkout and the storage root failed)"
    )


def test_an_unwritable_directory_is_unknown_not_a_crash(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist"
    assert DOCTOR.case_sensitive_filesystem(missing) is None
    assert DOCTOR.platform_detail(missing).endswith(
        "filesystem case unknown (probe under the checkout failed)"
    )
