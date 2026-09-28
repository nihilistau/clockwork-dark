"""
No author's note reaches the narrator.

WHY THIS EXISTS. v0.17.0 raised the cap on authored text (1500 characters,
``spec.MAX_AUTHORED_TEXT``) so that cards cut short in silence reach the prose
whole. That was right for their INTENT, CONSTRAINT and MENU lines -- and it
also carried notes written to the author or to the engine into the narrator's
prompt: The Wicked Garden's "RUNTIME: call `endings.recompute(state)`...",
"NOTE: the design lists a fifth delta...", a beat's "WHY IT IS NOT ON D8_05"
and, worst, "discharge or break the thread through the thread tool" -- an
instruction to the NARRATOR to act, which is exactly what AGENTS.md rule 1
forbids (the engine acts; the narrator narrates). Those notes now live in YAML
comments beside their card or beat, where authors still read them and the
loader never does.

The check reads every story's YAML and every string under a ``text`` key,
wherever it sits -- deck cards and beats, ending-module beats, on_fail text,
set-piece steps -- because every one of those is narrator-visible. Comments
are invisible to a YAML loader, which is the point. The markers are narrow on
purpose: INTENT / CONSTRAINT / MENU / SEQUENCE / SHE WANTS lines direct the
prose and are left alone.

Version: v0.1.0 [2026-09-28]
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
GAMES = ROOT / "games"

#: Phrases that speak to the author or the engine, never to the narrator.
#: Case-sensitive where the house style is an upper-case label.
AUTHOR_META_MARKERS: tuple[str, ...] = (
    "RUNTIME:",  # what the engine does, or what code to call
    "NOTE: the design",  # a design-doc reconciliation
    "WHY IT IS NOT",  # an author's rationale header
    "thread tool",  # an instruction to act, which rule 1 forbids
    "through threads.yaml",  # the same instruction, by file name
)


def _meta_in(text: str) -> list[str]:
    return [m for m in AUTHOR_META_MARKERS if m in text]


def _texts(node: Any, where: str) -> Iterator[tuple[str, str]]:
    if isinstance(node, dict):
        for key, value in node.items():
            here = f"{where}.{key}"
            if isinstance(value, dict) and value.get("id"):
                here = f"{where}.{key}[{value.get('id')}]"
            if key == "text" and isinstance(value, str):
                yield here, value
            else:
                yield from _texts(value, here)
    elif isinstance(node, list):
        for i, item in enumerate(node):
            label = item.get("id") if isinstance(item, dict) and item.get("id") else i
            yield from _texts(item, f"{where}[{label}]")


def _story_yaml() -> list[Path]:
    return sorted(GAMES.glob("*/data/**/*.yaml"))


def test_the_marker_list_catches_what_it_is_for() -> None:
    """Negative control: each shape this release moved out is caught."""
    assert _meta_in("ACT. Pay it. RUNTIME: discharge or break the live thread")
    assert _meta_in("Someone claps. NOTE: the design lists a fifth delta")
    assert _meta_in("WHY IT IS NOT ON D8_05: `thrall_consent` used to")
    assert _meta_in("OPEN A THREAD through the thread tool.")
    assert _meta_in("Seal whichever the player argued for through threads.yaml.")
    # ...and leaves the prose directions alone.
    assert not _meta_in(
        "INTENT: the last inventory. CONSTRAINT: exactly one free action. "
        "MENU -- resolve at most one beat. SHE WANTS: to be refused."
    )
    assert not _meta_in("a property-scent thread, not full thrall")


@pytest.mark.skipif(not GAMES.is_dir(), reason="no games/ directory")
def test_no_story_text_carries_an_authors_note() -> None:
    """Every narrator-visible ``text`` in every story is free of author meta."""
    files = _story_yaml()
    assert files, "no story YAML found under games/*/data"
    found: list[str] = []
    for path in files:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        rel = path.relative_to(ROOT).as_posix()
        for where, text in _texts(doc, rel):
            hits = _meta_in(text)
            if hits:
                found.append(f"{where}: {', '.join(hits)}")
    assert not found, (
        "author's notes in narrator-visible text -- move them to a YAML "
        "comment beside the card or beat:\n  " + "\n  ".join(found)
    )
