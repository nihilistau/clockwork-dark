"""
Service commands without ``.exe`` (v0.20.0 T4; spec §3.3, survey finding 10).

``config/default.yaml`` shipped ``target/release/tts-server.exe`` and
``voxtral.exe``: a Linux build of the same Rust servers is named without the
suffix, so the shipped config could never find it there. The commands now
carry no extension, and ``ServiceSpec.resolved_command`` resolves a path the
config names the way ``shutil.which`` resolves a PATH name: on Windows, the
name as written, then with each ``PATHEXT`` suffix. So Windows finds the same
``tts-server.exe`` it found before, and an owner's ``local.yaml`` that still
says ``.exe`` resolves unchanged.
"""

from __future__ import annotations

import difflib
import os
from pathlib import Path

import pytest
import yaml

from engine.stack import ServiceSpec
from tests.llm_golden import FIXTURES as GOLDEN, capture_baseline

REPO = Path(__file__).resolve().parents[1]

windows_only = pytest.mark.skipif(os.name != "nt", reason="PATHEXT is a Windows lookup")
posix_only = pytest.mark.skipif(os.name == "nt", reason="POSIX takes a name exactly")


def _shipped_services() -> dict:
    raw = yaml.safe_load((REPO / "config" / "default.yaml").read_text(encoding="utf-8"))
    return raw["stack"]["services"]


def test_the_shipped_commands_carry_no_exe() -> None:
    commands = {
        name: str(service.get("command") or "")
        for name, service in _shipped_services().items()
    }
    assert commands["voxtral_tts"] == "target/release/tts-server"
    assert commands["voxtral_asr"] == "target/release/voxtral"
    assert not [c for c in commands.values() if c.lower().endswith(".exe")], commands


def _build(root: Path, name: str) -> Path:
    exe = root / "target" / "release" / name
    exe.parent.mkdir(parents=True, exist_ok=True)
    exe.write_bytes(b"")
    exe.chmod(0o755)
    return exe


# -- fix round 1: only a runnable regular file counts (review finding 6) -----------


def test_a_directory_named_like_the_command_is_not_it(tmp_path: Path) -> None:
    """A directory is not an executable. Before round 1 ``exists()`` accepted
    it, and the stack would have tried to Popen a directory."""
    (tmp_path / "target" / "release" / "tts-server").mkdir(parents=True)
    (tmp_path / "target" / "release" / "tts-server.exe").mkdir()
    spec = ServiceSpec.from_config(
        "voxtral_tts", {"root": str(tmp_path), "command": "target/release/tts-server"}
    )
    assert spec.resolved_command() is None


def test_an_absolute_directory_is_not_a_command(tmp_path: Path) -> None:
    spec = ServiceSpec.from_config("voxtral_tts", {"command": str(tmp_path)})
    assert spec.resolved_command() is None


@posix_only
def test_posix_needs_the_exec_bit(tmp_path: Path) -> None:
    exe = _build(tmp_path, "tts-server")
    exe.chmod(0o644)
    spec = ServiceSpec.from_config(
        "voxtral_tts", {"root": str(tmp_path), "command": "target/release/tts-server"}
    )
    assert spec.resolved_command() is None


@windows_only
def test_pathext_order_is_windows_own(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Documented, not changed: suffixes are tried in PATHEXT's order, as
    Windows and ``shutil.which`` try them, so a ``.com`` twin in the owner's
    own ``root`` wins over the ``.exe``; naming the ``.exe`` pins it."""
    monkeypatch.setenv("PATHEXT", ".COM;.EXE;.BAT;.CMD")
    exe = _build(tmp_path, "tts-server.exe")
    com = _build(tmp_path, "tts-server.com")
    bare = ServiceSpec.from_config(
        "voxtral_tts", {"root": str(tmp_path), "command": "target/release/tts-server"}
    )
    pinned = ServiceSpec.from_config(
        "voxtral_tts", {"root": str(tmp_path), "command": "target/release/tts-server.exe"}
    )
    assert bare.resolved_command() == com
    assert pinned.resolved_command() == exe


@windows_only
def test_a_local_name_finds_the_windows_exe_through_pathext(tmp_path: Path) -> None:
    exe = _build(tmp_path, "tts-server.exe")
    spec = ServiceSpec.from_config(
        "voxtral_tts", {"root": str(tmp_path), "command": "target/release/tts-server"}
    )
    assert spec.resolved_command() == exe


@windows_only
def test_an_absolute_name_finds_the_windows_exe_through_pathext(tmp_path: Path) -> None:
    exe = _build(tmp_path, "tts-server.exe")
    spec = ServiceSpec.from_config(
        "voxtral_tts", {"command": str(tmp_path / "target" / "release" / "tts-server")}
    )
    assert spec.resolved_command() == exe


def test_an_owners_exe_command_still_resolves(tmp_path: Path) -> None:
    exe = _build(tmp_path, "tts-server.exe")
    spec = ServiceSpec.from_config(
        "voxtral_tts", {"root": str(tmp_path), "command": "target/release/tts-server.exe"}
    )
    assert spec.resolved_command() == exe


def test_the_linux_build_is_found_by_its_bare_name(tmp_path: Path) -> None:
    exe = _build(tmp_path, "tts-server")
    spec = ServiceSpec.from_config(
        "voxtral_tts", {"root": str(tmp_path), "command": "target/release/tts-server"}
    )
    assert spec.resolved_command() == exe


@posix_only
def test_posix_adds_no_suffix(tmp_path: Path) -> None:
    _build(tmp_path, "tts-server.exe")
    spec = ServiceSpec.from_config(
        "voxtral_tts", {"root": str(tmp_path), "command": "target/release/tts-server"}
    )
    assert spec.resolved_command() is None


def test_nothing_there_is_none(tmp_path: Path) -> None:
    spec = ServiceSpec.from_config(
        "voxtral_tts", {"root": str(tmp_path), "command": "target/release/tts-server"}
    )
    assert spec.resolved_command() is None


def test_doctor_services_baseline_is_unchanged(tmp_path: Path) -> None:
    recorded = (GOLDEN / "doctor_services.txt").read_text(encoding="utf-8")
    now = capture_baseline("doctor_services", tmp_path / "config")
    assert now == recorded, "\n".join(
        difflib.unified_diff(recorded.splitlines(), now.splitlines(), "recorded", "now", lineterm="")
    )
