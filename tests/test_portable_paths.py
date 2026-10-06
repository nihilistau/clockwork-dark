"""
Case and separators, checked on every platform (v0.20.0 T4; spec §3.4).

Windows forgives two slips that Linux does not: a backslash as a separator,
and a name whose case differs from the file's (NTFS is case-insensitive, so
``Path.exists()`` says yes). A story authored on Windows could carry either
and play there, then fail to find its file on a Linux host. These tests run on
Windows too, so the slip is caught on the machine where it is made.

Three things, over every manifest ``paths:`` value, every file-naming string
value in a story's YAML (a path with a directory part, or -- since fix round
1 -- a bare ``name.ext``, resolved first against its own YAML file's
directory), every relative path in ``config/default.yaml``, and every
``games/...`` file a string literal in ``engine/``, ``scripts/`` or
``launcher.py`` names:

* the path holds no ``\\`` and no drive letter;
* each component matches a directory entry EXACTLY, by comparing against
  ``os.listdir`` of its parent, never by ``exists()``;
* every file the repo tracks is unique case-insensitively (two names that
  differ only by case cannot both be checked out on Windows).

A path that does not exist at all (a runtime file such as ``lore.db``, or a
service binary an owner builds) is held to the first rule only: there is
nothing on disk to compare its case against.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterator

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
GAMES = REPO / "games"

_DRIVE = re.compile(r"^[A-Za-z]:")
#: A string that names a file: no spaces, at least one "/", a file suffix.
_FILELIKE = re.compile(
    r"^[^\s:*?\"<>|]+/[^\s:*?\"<>|]*\.(ya?ml|md|txt|json|jpe?g|png|webp|gif|svg|db|gguf|py|toml|css|js)$",
    re.IGNORECASE,
)
#: A bare filename value: no directory part, a file suffix.
_BARE = re.compile(
    r"^[A-Za-z0-9_][A-Za-z0-9_.\-]*\.(ya?ml|md|txt|json|jpe?g|png|webp|gif|svg|db|gguf)$",
    re.IGNORECASE,
)
_IMAGE = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".svg")


def _manifests() -> list[Path]:
    return sorted(GAMES.glob("*/game.yaml"))


def _load(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _strings(node: Any, where: str = "") -> Iterator[tuple[str, str]]:
    if isinstance(node, str):
        yield where, node
    elif isinstance(node, dict):
        for key, value in node.items():
            yield from _strings(value, f"{where}.{key}" if where else str(key))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _strings(value, f"{where}[{index}]")


@lru_cache(maxsize=None)
def _entries(directory: str) -> frozenset[str]:
    try:
        return frozenset(os.listdir(directory))
    except OSError:
        return frozenset()


def _case_mismatch(relative: str, base: Path = REPO) -> str | None:
    """None if every component of ``relative`` (under ``base``) is a directory
    entry with exactly that name, or if the path does not exist at all; else
    the first component whose case differs."""
    current = base
    for part in Path(relative).parts:
        if part in (".", ""):
            continue
        if part == "..":
            current = current.parent
            continue
        entries = _entries(str(current))
        if part in entries:
            current = current / part
            continue
        folded = [e for e in entries if e.lower() == part.lower()]
        if folded:
            try:
                under = current.relative_to(REPO).as_posix() or "."
            except ValueError:
                under = current.as_posix()
            return f"{part!r} is {folded[0]!r} on disk (under {under})"
        return None  # does not exist: nothing to compare
    return None


def _portable(value: str) -> list[str]:
    problems = []
    if "\\" in value:
        problems.append("holds a backslash")
    if _DRIVE.match(value):
        problems.append("names a drive letter")
    return problems


# -- the sources -------------------------------------------------------------------


def manifest_paths() -> list[tuple[str, str]]:
    out = []
    for manifest in _manifests():
        paths = (_load(manifest) or {}).get("paths") or {}
        for key, value in paths.items():
            if isinstance(value, str) and value:
                out.append((f"{manifest.relative_to(REPO).as_posix()} paths.{key}", value))
    return out


def content_paths() -> list[tuple[str, str, Path]]:
    """(where, path, base) for each file a story's content names.

    * every image in a story's art manifest, under its ``paths.art_root``;
    * every file-like string VALUE (not a comment) in any YAML under
      ``games/<slug>/``, resolved against the repo root, the story's own
      directory, or its art root -- whichever holds it.
    Decks, scenes and the lore corpus are directories the engine lists, so each
    of their files is named by its own directory entry; the directory itself
    is a ``paths:`` value, checked above.
    """
    out: list[tuple[str, str, Path]] = []
    for manifest in _manifests():
        story = manifest.parent
        paths = (_load(manifest) or {}).get("paths") or {}
        art_root = REPO / paths["art_root"] if paths.get("art_root") else None
        for yaml_file in sorted(story.rglob("*.yaml")):
            out += yaml_file_paths(yaml_file, story, art_root)
    return out


def yaml_file_paths(
    yaml_file: Path, story: Path, art_root: Path | None
) -> list[tuple[str, str, Path]]:
    """The file-naming values in one YAML file, each with the base it
    resolves against. A value with a directory part (``prompts/x.md``) is
    tried against the art root (images), the repo and the story; a BARE
    filename (``prose_source: epilogue_cards.yaml``, ``menu: menu-screen.jpg``;
    fix round 1, review finding 5) against the YAML file's own directory
    first, then the same three."""
    try:
        where_file = yaml_file.relative_to(REPO).as_posix()
    except ValueError:
        where_file = yaml_file.as_posix()
    try:
        data = _load(yaml_file)
    except yaml.YAMLError:
        return []
    out = []
    for where, value in _strings(data):
        slashed = value.replace("\\", "/")
        if "://" in value or value.startswith("/"):
            continue
        bare = bool(_BARE.match(slashed))
        if not bare and not _FILELIKE.match(slashed):
            continue
        candidates = [REPO, story]
        if art_root is not None and value.lower().endswith(_IMAGE):
            candidates.insert(0, art_root)
        if bare:
            candidates.insert(0, yaml_file.parent)
        base = next((c for c in candidates if _exists_folded(slashed, c)), REPO)
        out.append((f"{where_file} {where}", value, base))
    return out


#: A string literal in code that names a file under ``games/``.
_CODE_REF = re.compile(
    r"games/[A-Za-z0-9_.\-/]+\.(?:ya?ml|md|txt|json|jpe?g|png|webp|gif|svg|db)\b"
)
_CODE_ROOTS = ("engine", "scripts", "launcher.py")


def code_paths() -> list[tuple[str, str]]:
    """(where, path) for each ``games/...`` file a string in the engine, the
    scripts or the launcher names (fix round 1, review finding 5). Read as
    text, so f-string pieces count; a reference with a placeholder
    (``games/{slug}/game.yaml``) stops at the brace and is held to the rules
    only as far as it is literal."""
    import ast

    out = []
    files: list[Path] = []
    for root in _CODE_ROOTS:
        path = REPO / root
        files += [path] if path.is_file() else sorted(path.rglob("*.py"))
    for path in files:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                for match in _CODE_REF.finditer(node.value.replace("\\", "/")):
                    out.append(
                        (f"{path.relative_to(REPO).as_posix()}:{node.lineno}", match.group(0))
                    )
    return out


def _exists_folded(relative: str, base: Path) -> bool:
    current = base
    for part in Path(relative).parts:
        match = [e for e in _entries(str(current)) if e.lower() == part.lower()]
        if not match:
            return False
        current = current / match[0]
    return True


#: Config keys whose value is a path even with no "/" in it (``storage.root:
#: "data"``).
_PATH_KEY = re.compile(r"(^|\.)([a-z_]*(root|_db|_dir|_path|command|model))$")


def config_paths() -> list[tuple[str, str]]:
    data = _load(REPO / "config" / "default.yaml")
    out = []
    for where, value in _strings(data):
        slashed = value.replace("\\", "/")
        if not value or "://" in value or value.startswith("/"):
            continue
        named_by_key = bool(_PATH_KEY.search(re.sub(r"\[\d+\]$", "", where))) and " " not in value
        looks_like_a_file = bool(_FILELIKE.match(slashed))
        if named_by_key and "/" not in slashed and "." not in slashed and where.endswith("model"):
            continue  # a model id ("qwen3-..."), not a file
        if named_by_key or looks_like_a_file:
            out.append((where, value))
    return out


# -- the three assertions ------------------------------------------------------------


def test_the_sources_are_not_empty() -> None:
    """Guard the guards: a walker that finds nothing proves nothing."""
    assert len(manifest_paths()) > 50
    assert len(content_paths()) > 20
    assert len(config_paths()) > 3
    assert len(code_paths()) > 5
    bare = [v for _, v, _ in content_paths() if "/" not in v.replace("\\", "/")]
    assert "epilogue_cards.yaml" in bare and "menu-screen.jpg" in bare, bare


def test_manifest_paths_are_portable_and_exact() -> None:
    problems = []
    for where, value in manifest_paths():
        problems += [f"{where}: {value!r} {p}" for p in _portable(value)]
        mismatch = _case_mismatch(value)
        if mismatch:
            problems.append(f"{where}: {value!r} -- {mismatch}")
    assert not problems, "\n".join(problems)


def test_content_paths_are_portable_and_exact() -> None:
    problems = []
    for where, value, base in content_paths():
        problems += [f"{where}: {value!r} {p}" for p in _portable(value)]
        mismatch = _case_mismatch(value.replace("\\", "/"), base)
        if mismatch:
            problems.append(f"{where}: {value!r} -- {mismatch}")
    assert not problems, "\n".join(problems)


def test_config_paths_are_portable_and_exact() -> None:
    problems = []
    for where, value in config_paths():
        problems += [f"config/default.yaml {where}: {value!r} {p}" for p in _portable(value)]
        mismatch = _case_mismatch(value)
        if mismatch:
            problems.append(f"config/default.yaml {where}: {value!r} -- {mismatch}")
    assert not problems, "\n".join(problems)


def _tracked() -> list[str]:
    if shutil.which("git") is None:
        pytest.skip("git is not on PATH -- the tracked files cannot be listed")
    try:
        done = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=REPO,
            capture_output=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        pytest.skip(f"git could not be run: {exc}")
    if done.returncode != 0:
        pytest.skip("git ls-files failed: no history to read")
    return [p for p in done.stdout.decode("utf-8").split("\0") if p]


def case_collisions(paths: list[str]) -> list[list[str]]:
    """Groups of paths (files, and the directories above them) that differ
    only by case."""
    seen: dict[str, set[str]] = {}
    for path in paths:
        parts = path.split("/")
        for depth in range(1, len(parts) + 1):
            prefix = "/".join(parts[:depth])
            seen.setdefault(prefix.lower(), set()).add(prefix)
    return sorted(sorted(group) for group in seen.values() if len(group) > 1)


def test_code_references_to_story_files_are_portable_and_exact() -> None:
    problems = []
    for where, value in code_paths():
        mismatch = _case_mismatch(value)
        if mismatch:
            problems.append(f"{where}: {value!r} -- {mismatch}")
    assert not problems, "\n".join(problems)


def test_tracked_names_are_unique_ignoring_case() -> None:
    collisions = case_collisions(_tracked())
    assert not collisions, collisions


# -- the walkers catch what they exist for (canaries, kept as tests) ---------------


def test_a_case_slip_is_caught_where_exists_would_forgive_it() -> None:
    real = manifest_paths()[0][1]
    slipped = real.replace("games/", "Games/", 1)
    assert _case_mismatch(slipped) is not None
    assert _case_mismatch(real) is None


def test_a_bare_filename_slip_is_caught(tmp_path: Path) -> None:
    """``prose_source: Epilogue_cards.yaml`` beside ``epilogue_cards.yaml``:
    a bare name is resolved against its YAML file's own directory, and its
    case compared there (fix round 1, review finding 5)."""
    story = tmp_path / "story"
    index = story / "data" / "epilogues" / "epilogue_index.yaml"
    index.parent.mkdir(parents=True)
    (index.parent / "epilogue_cards.yaml").write_text("{}", encoding="utf-8")
    index.write_text("prose_source: Epilogue_cards.yaml\n", encoding="utf-8")
    [(where, value, base)] = yaml_file_paths(index, story, None)
    assert base == index.parent
    assert _case_mismatch(value, base) is not None
    index.write_text("prose_source: epilogue_cards.yaml\n", encoding="utf-8")
    [(_, value, base)] = yaml_file_paths(index, story, None)
    assert _case_mismatch(value, base) is None


def test_a_code_reference_is_found_in_a_string() -> None:
    assert [m.group(0) for m in _CODE_REF.finditer('x = "games/hue-and-cry/Game.yaml"')] == [
        "games/hue-and-cry/Game.yaml"
    ]
    assert _case_mismatch("games/hue-and-cry/Game.yaml") is not None


def test_a_backslash_and_a_drive_letter_are_caught() -> None:
    assert _portable("games\\hue-and-cry\\game.yaml") == ["holds a backslash"]
    assert _portable("C:/games/x.yaml") == ["names a drive letter"]
    assert _portable("games/hue-and-cry/game.yaml") == []


def test_a_case_twin_is_a_collision() -> None:
    assert case_collisions(["a/Readme.md", "a/README.md", "b/x"]) == [["a/README.md", "a/Readme.md"]]
    assert case_collisions(["Docs/a", "docs/b"]) == [["Docs", "docs"]]
