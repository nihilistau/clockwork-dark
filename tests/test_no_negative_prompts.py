"""
No committed art prompt carries a negative-prompt list.

The owner's decision (2026-09-26, release v0.15.1): the negative keyword lists
come out of every story's art direction -- all of them, the art-style ones
("anime, text, watermark") as much as any other. Someone generating their own
plates knows how to drive their own image model; the repository does not
publish lists of what to keep out of a picture.

This guard reads every committed art prompt file -- each story's
``data/art/*.yaml`` and ``*.md`` and its ``data/procgen_templates/*.yaml`` --
and fails if one declares a negative prompt: a YAML key named ``negative``,
``negatives`` or ``negative_prompt`` at any depth, or a ``NEGATIVE:`` line in a
plate brief.

Version: v0.15.1 [2026-09-26]
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterator

import yaml

from engine.config import project_root

_GAMES = project_root() / "games"
_NEGATIVE_KEYS = {"negative", "negatives", "negative_prompt"}
_NEGATIVE_LINE = re.compile(r"^\s*(?:[-*>#]\s*)*\**negative(?:s|[ _]prompt)?\**\s*:", re.IGNORECASE)


def _prompt_files() -> list[Path]:
    files: list[Path] = []
    for game in sorted(p for p in _GAMES.iterdir() if p.is_dir()):
        art = game / "data" / "art"
        if art.is_dir():
            files += sorted(art.glob("*.yaml")) + sorted(art.glob("*.md"))
        templates = game / "data" / "procgen_templates"
        if templates.is_dir():
            files += sorted(templates.glob("*.yaml"))
    return files


def _negative_keys(node: Any, trail: str = "") -> Iterator[str]:
    if isinstance(node, dict):
        for key, value in node.items():
            here = f"{trail}.{key}" if trail else str(key)
            if str(key).lower() in _NEGATIVE_KEYS:
                yield here
            yield from _negative_keys(value, here)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _negative_keys(value, f"{trail}[{index}]")


def test_the_scan_sees_every_story_that_ships_art() -> None:
    files = _prompt_files()
    assert any(f.name == "subjects.yaml" for f in files)
    assert any(f.name == "MISSING-PLATES.md" for f in files)
    assert any(f.parent.name == "procgen_templates" for f in files)


def test_no_committed_art_prompt_carries_a_negative_list() -> None:
    found: list[str] = []
    for path in _prompt_files():
        rel = path.relative_to(project_root()).as_posix()
        text = path.read_text(encoding="utf-8")
        if path.suffix == ".yaml":
            data = yaml.safe_load(text)
            found += [f"{rel}: {key}" for key in _negative_keys(data)]
        for number, line in enumerate(text.splitlines(), start=1):
            if _NEGATIVE_LINE.match(line) and not line.lstrip().startswith("#"):
                found.append(f"{rel}:{number}: {line.strip()[:60]}")
    assert not found, "negative prompt lists in committed art files:\n" + "\n".join(sorted(set(found)))
