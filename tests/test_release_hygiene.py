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
  * Every story under games/ keeps its own CHANGELOG.md with an
    ``## [Unreleased]`` section, releases newest first and none newer than
    pyproject.toml's, and AGENTS.md carries the convention that keeps it so
    ("Docs move with the change").

Version: v0.2.0 [2026-09-26]
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

import pytest

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


def test_the_lockfile_claims_the_same_version_as_the_package() -> None:
    """`npm ci` reads the lockfile, not package.json: a lock left at the old
    number is a release that installs as the previous one (v0.10.0 shipped
    its first cut with the lock still at 0.9.0)."""
    package = json.loads((ROOT / "ui" / "package.json").read_text(encoding="utf-8"))
    lock = json.loads((ROOT / "ui" / "package-lock.json").read_text(encoding="utf-8"))
    assert lock["version"] == package["version"], lock["version"]
    assert lock["packages"][""]["version"] == package["version"], lock["packages"][""]["version"]


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


def _story_dirs() -> list[Path]:
    return sorted(p for p in (ROOT / "games").iterdir() if (p / "game.yaml").is_file())


def _story_changelog_problems(
    name: str, text: str, root_versions: set[str], current: tuple[int, ...]
) -> list[str]:
    """Everything wrong with one story's CHANGELOG.md, as readable lines."""
    problems: list[str] = []
    if "\n## [Unreleased]\n" not in text:
        problems.append(f"{name}: no '## [Unreleased]' section")
    headings = re.findall(r"^## \[.*$", text, re.MULTILINE)
    for heading in headings:
        if heading != "## [Unreleased]" and not _RELEASE.fullmatch(heading):
            problems.append(
                f"{name}: {heading!r} is not written '## [x.y.z] — YYYY-MM-DD'"
            )
    if "## [Unreleased]" in headings and headings[0] != "## [Unreleased]":
        problems.append(f"{name}: '## [Unreleased]' is not above every release")
    releases = [v for v, _ in _RELEASE.findall(text)]
    for version in sorted({v for v in releases if releases.count(v) > 1}):
        problems.append(f"{name}: {version} is listed more than once")
    for version in releases:
        if version not in root_versions:
            problems.append(f"{name}: {version} is not a release in the root CHANGELOG")
    versions = [tuple(int(p) for p in v.split(".")) for v in releases]
    if versions != sorted(versions, reverse=True):
        problems.append(f"{name}: releases are not newest first")
    if versions and versions[0] > current:
        problems.append(f"{name}: names {versions[0]}, newer than {current}")
    return problems


def test_every_story_keeps_its_own_changelog() -> None:
    """Owner, 2026-09-26: each story keeps a CHANGELOG.md for its content; the
    root file covers the engine and the release. Its README links it. A
    story's file keeps an ``## [Unreleased]`` section above its releases, lists
    them newest first with no repeats, writes every heading the root's way
    (em dash and date), and names only releases the root CHANGELOG has, none
    newer than the one pyproject.toml claims."""
    current = tuple(int(p) for p in _version().split("."))
    root_text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    root_versions = {v for v, _ in _RELEASE.findall(root_text)}
    stories = _story_dirs()
    assert stories, "no games/<slug>/game.yaml found"
    problems: list[str] = []
    for story in stories:
        readme = story / "README.md"
        if not readme.is_file():
            problems.append(f"{story.name}: no README.md")
        elif "(CHANGELOG.md)" not in readme.read_text(encoding="utf-8"):
            problems.append(f"{story.name}: README.md does not link CHANGELOG.md")
        path = story / "CHANGELOG.md"
        if not path.is_file():
            problems.append(f"{story.name}: no CHANGELOG.md")
            continue
        problems += _story_changelog_problems(
            story.name, path.read_text(encoding="utf-8"), root_versions, current
        )
    assert not problems, problems


_GOOD = "# Changelog\n\n## [Unreleased]\n\n## [0.9.0] — 2026-09-23\n\n## [0.5.0] — 2026-09-20\n"


@pytest.mark.parametrize(
    "text, expected",
    [
        (_GOOD.replace("## [0.5.0] — ", "## [0.5.0] - "), "not written"),
        (_GOOD.replace("[0.5.0]", "[0.9.0]"), "more than once"),
        (
            "# Changelog\n\n## [0.9.0] — 2026-09-23\n\n## [Unreleased]\n",
            "above",
        ),
        (_GOOD.replace("[0.5.0]", "[0.4.7]"), "root CHANGELOG"),
        (_GOOD.replace("[0.9.0]", "[0.4.0]"), "newest first"),
        (_GOOD.replace("## [Unreleased]\n", ""), "Unreleased"),
    ],
    ids=["hyphen", "duplicate", "unreleased-below", "unknown-version", "order", "no-unreleased"],
)
def test_the_story_changelog_guard_catches(text: str, expected: str) -> None:
    """Each shape the guard exists for, fed to it directly: a guard that only
    ever reads correct files proves nothing about wrong ones."""
    problems = _story_changelog_problems("probe", text, {"0.9.0", "0.5.0", "0.4.0"}, (0, 15, 0))
    assert any(expected in p for p in problems), problems
    assert _story_changelog_problems("probe", _GOOD, {"0.9.0", "0.5.0"}, (0, 15, 0)) == []


def test_agents_md_says_docs_move_with_the_change() -> None:
    """The standing rule that keeps the per-story CHANGELOG/README, the root
    ones, CLAUDE.md and AGENTS.md current lives in AGENTS.md's working
    conventions -- once, where every agent reads it."""
    text = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    section = text.split("## Working conventions", 1)[1].split("\n## ", 1)[0]
    assert "**Docs move with the change.**" in section
    assert "games/<slug>/CHANGELOG.md" in section
