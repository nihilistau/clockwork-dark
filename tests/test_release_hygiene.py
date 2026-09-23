"""
The release record agrees with itself.

WHY THIS EXISTS. Three files describe the repo's state and every one of them has
gone stale while the suite stayed green: CLAUDE.md's test count read "2020
passing, 18 skipped" for a month after v0.3.0 deleted three test files -- in the
sentence warning about exactly that; README.md claimed a Python floor (3.13)
that the venv the whole suite runs on (3.11) contradicted; and pyproject.toml
and ui/package.json had drifted to 0.1.0 and 0.2.0 against no changelog at all.

A convention nobody checks is a convention that decays, so the parts that CAN
be checked mechanically are checked here:

  * CHANGELOG.md keeps an ``## [Unreleased]`` section, and its newest release
    heading names the same version as pyproject.toml and ui/package.json.
  * CLAUDE.md states that same version, so it is touched every release.
  * CLAUDE.md imports AGENTS.md, and AGENTS.md carries all twelve critical rules
    -- including rule 12 in full, the one whose absence was how it got rebuilt.

Version: v0.1.0 [2026-09-23]
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_RELEASE = re.compile(r"^## \[(\d+\.\d+\.\d+)\] — (\d{4}-\d{2}-\d{2})$", re.MULTILINE)


def _version() -> str:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"][
        "version"
    ]


def test_the_changelog_keeps_an_unreleased_section() -> None:
    """Work in progress is recorded as it lands, not reconstructed at release."""
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "\n## [Unreleased]\n" in text


def test_the_newest_release_is_the_version_everything_else_claims() -> None:
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    releases = _RELEASE.findall(text)
    assert releases, "no '## [x.y.z] — YYYY-MM-DD' headings in CHANGELOG.md"
    newest, _ = releases[0]
    package = json.loads((ROOT / "ui" / "package.json").read_text(encoding="utf-8"))
    assert newest == _version() == package["version"], (
        f"CHANGELOG {newest} / pyproject {_version()} / ui {package['version']}"
    )


def test_releases_are_newest_first() -> None:
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    versions = [tuple(int(p) for p in v.split(".")) for v, _ in _RELEASE.findall(text)]
    assert versions == sorted(versions, reverse=True)


def test_claude_md_states_the_current_release() -> None:
    text = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    assert f"**v{_version()}**" in text, "CLAUDE.md's Status was not updated this release"


def test_claude_md_imports_the_shared_rules() -> None:
    first_lines = (ROOT / "CLAUDE.md").read_text(encoding="utf-8").splitlines()[:5]
    assert "@AGENTS.md" in first_lines


def test_agents_md_carries_all_twelve_rules() -> None:
    text = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    section = text.split("## Critical rules", 1)[1].split("\n## ", 1)[0]
    numbered = re.findall(r"^(\d+)\. \*\*", section, re.MULTILINE)
    assert numbered == [str(n) for n in range(1, 13)], numbered
    assert "Never add a content-rating or \"safety\" layer." in section
    assert "If you find yourself specifying the fix for a missing" in section


def test_the_declared_python_floor_is_one_the_suite_runs_on() -> None:
    import sys

    spec = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"][
        "requires-python"
    ]
    floor = tuple(int(p) for p in spec.removeprefix(">=").split("."))
    assert sys.version_info[: len(floor)] >= floor, (
        f"pyproject says {spec}; this suite is running on "
        f"{sys.version_info.major}.{sys.version_info.minor}"
    )
