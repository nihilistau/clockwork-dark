"""
No CORE client file names one story, in script or in stylesheet.

THE REGRESSION THIS BLOCKS. ``ui/src/styles/index.css`` -- the core stylesheet
every story loads -- carried::

    .overlay__title::before { content: "The Clockwork Dark"; }

so every overlay in every game drew the flagship's name above its heading. Four
of the five shipped stories wore a title that was not theirs, and the one that
made it obvious was a funeral-barge story borrowing the Garden's skin: "THE
CLOCKWORK DARK" over an overlay called "The court".

It survived the whole engine/story seam pass because that pass's grep-gates
read ``engine/`` Python (``tests/test_no_flagship_content_literals.py``). CSS
`content` is player-visible copy exactly like a Python string is, and nothing
was looking at it.

THE RULE. A story's title may appear inside its own plugin directory
(``ui/src/stories/<plugin>/``) and nowhere else under ``ui/src``. Core draws
what the running story tells it to -- see ``--story-eyebrow``, set on :root in
``main.jsx`` from the resolved story, which is also correct for a BORROWED
plugin because ``loadStory`` swaps the lender's naming slots for the
borrower's.

Titles are read from the shipped manifests rather than listed here, so a story
added tomorrow is covered with no test edit.

COMMENTS ARE EXEMPT, as in the Python gate: history is allowed to say the
client used to BE The Clockwork Dark. Code and CSS declarations are not.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

_ROOT = Path(__file__).resolve().parents[1]
_UI_SRC = _ROOT / "ui" / "src"

#: Extensions whose contents reach a player.
_SCANNED = (".js", ".jsx", ".css")

#: ``/* ... */`` in JS and CSS alike.
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
#: ``//`` to end of line, but NOT the ``//`` inside a URL scheme.
_LINE_COMMENT = re.compile(r"(?<!:)//[^\n]*")


def _story_titles() -> dict[str, str]:
    """Every shipped story's title, keyed by the plugin directory it may use."""
    titles: dict[str, str] = {}
    for manifest in sorted((_ROOT / "games").glob("*/game.yaml")):
        try:
            doc = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
        except Exception:  # noqa: BLE001 — a broken manifest is another test's job
            continue
        title = str(doc.get("title") or "").strip()
        if not title:
            continue
        slug = str(doc.get("id") or manifest.parent.name)
        # Where this title is allowed to be written down: the plugin the story
        # declares, which for a borrower is somebody else's directory -- and a
        # borrower's title must NOT be written into the lender's plugin, so the
        # own-slug directory is the only allowance.
        titles[title] = slug
    return titles


TITLES = _story_titles()


def _code_only(text: str) -> str:
    """The file with its comments blanked out, newlines preserved for line numbers."""
    def _blank(match: re.Match[str]) -> str:
        return re.sub(r"[^\n]", " ", match.group(0))

    return _LINE_COMMENT.sub(_blank, _BLOCK_COMMENT.sub(_blank, text))


@pytest.mark.skipif(not _UI_SRC.is_dir(), reason="no ui/src in this checkout")
@pytest.mark.skipif(not TITLES, reason="no story manifests discovered")
def test_no_core_ui_file_names_a_single_story() -> None:
    offenders: list[str] = []

    for path in sorted(_UI_SRC.rglob("*")):
        if not path.is_file() or path.suffix not in _SCANNED:
            continue
        rel = path.relative_to(_ROOT).as_posix()
        parts = path.relative_to(_UI_SRC).parts
        owner = parts[1] if len(parts) > 1 and parts[0] == "stories" else ""

        code = _code_only(path.read_text(encoding="utf-8"))
        for lineno, line in enumerate(code.splitlines(), start=1):
            for title, slug in TITLES.items():
                if title not in line:
                    continue
                # Inside its own plugin directory is exactly where a story's
                # own name belongs.
                if owner and owner == slug:
                    continue
                offenders.append(f"{rel}:{lineno}: {title!r}")

    assert not offenders, (
        "Client code outside a story's own plugin directory names that story. "
        "Core must draw the RUNNING story's name (main.jsx sets --story-eyebrow "
        "on :root); a literal here is worn by every other game:\n  "
        + "\n  ".join(offenders)
    )


@pytest.mark.skipif(not _UI_SRC.is_dir(), reason="no ui/src in this checkout")
def test_the_overlay_eyebrow_is_a_variable_not_a_name() -> None:
    """
    The specific line this file was written for, asserted directly.

    The gate above would catch the flagship's title returning verbatim, but not
    a different hardcoded string landing in the same slot -- and the slot is the
    bug, not the string that was in it.
    """
    css = (_UI_SRC / "styles" / "index.css").read_text(encoding="utf-8")
    match = re.search(r"\.overlay__title::before\s*\{[^}]*\}", css, re.DOTALL)
    assert match is not None, "the overlay eyebrow rule is gone; update this test"
    body = match.group(0)
    content = re.search(r"content:\s*([^;]+);", body)
    assert content is not None, f"no content declaration in:\n{body}"
    assert "var(--story-eyebrow" in content.group(1), (
        "the overlay eyebrow must read the running story's name from "
        f"--story-eyebrow, not carry one: {content.group(1).strip()!r}"
    )
