"""
``constraints.txt``: one set of versions everywhere (v0.20.0 T4; spec §3.10,
survey finding 15).

``requirements.txt`` keeps its ``>=`` ranges (what the code supports);
``constraints.txt`` pins what the suite was proven green on, and every
installer passes both. These tests hold the two together: every distribution
a requirements file names has exactly one pin, and the version installed here
equals it (a requirement that is not installed -- ``faster-whisper`` on the
owner's Windows ``.venv`` -- is skipped, not failed).
"""

from __future__ import annotations

import importlib.metadata as metadata
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
CONSTRAINTS = REPO / "constraints.txt"
REQUIREMENT_FILES = ("requirements.txt", "requirements-server.txt")

_NAME = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)")
_PIN = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([^\s;#]+)\s*$")


def canonical(name: str) -> str:
    """PEP 503's normalised name: ``Flask_SocketIO`` and ``flask-socketio`` agree."""
    return re.sub(r"[-_.]+", "-", name).lower()


def _lines(path: Path) -> list[str]:
    out = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if line:
            out.append(line)
    return out


def required() -> list[str]:
    names = []
    for filename in REQUIREMENT_FILES:
        path = REPO / filename
        if not path.exists():
            continue
        for line in _lines(path):
            if line.startswith("-"):  # -c constraints.txt, -r other.txt
                continue
            match = _NAME.match(line)
            assert match, f"{filename}: cannot read {line!r}"
            names.append(canonical(match.group(1)))
    return names


def pins() -> dict[str, str]:
    found: dict[str, str] = {}
    for line in _lines(CONSTRAINTS):
        match = _PIN.match(line)
        assert match, f"constraints.txt: {line!r} is not name==version"
        name = canonical(match.group(1))
        assert name not in found, f"constraints.txt pins {name} twice"
        found[name] = match.group(2)
    return found


def test_the_constraints_file_parses_and_pins_each_name_once() -> None:
    assert pins(), "constraints.txt pins nothing"


def test_every_requirement_has_a_pin() -> None:
    pinned = pins()
    missing = sorted(set(required()) - set(pinned))
    assert not missing, f"requirements with no pin in constraints.txt: {missing}"


@pytest.mark.parametrize("name", sorted(set(required())))
def test_the_installed_version_is_the_pin(name: str) -> None:
    try:
        installed = metadata.version(name)
    except metadata.PackageNotFoundError:
        pytest.skip(f"{name} is not installed here")
    assert installed == pins()[name], (
        f"{name} {installed} is installed but constraints.txt pins "
        f"{pins()[name]}: re-pin deliberately (a CHANGELOG'd edit) or reinstall "
        "with -c constraints.txt"
    )


def test_fastmcp_is_pinned_to_the_version_that_imports() -> None:
    """The owner's .venv carries a stale fastmcp 3.4.7 record beside the 3.2.4
    that is installed; the pin follows what ``import fastmcp`` loads, and the
    stale ``fastmcp-slim`` is not pinned (constraints.txt's header)."""
    assert pins()["fastmcp"] == "3.2.4"
    assert "fastmcp-slim" not in pins()


def test_installer_tooling_is_not_pinned() -> None:
    """pip and setuptools are left to each environment (fix round 1, review
    finding 8): a pin only ever reached an isolated build, and the .venv's
    setuptools 65.5.0 has published advisories."""
    assert not {"pip", "setuptools", "wheel"} & set(pins())


def test_pillow_is_declared() -> None:
    """The art tests import PIL directly; a clean install must bring it."""
    assert "pillow" in required()
