"""
Prompt guidance and grammar caps must agree.

The persona asks the model for a word target; the JSON schema enforces a hard
character cap. Those are two homes for one decision, and they have drifted
before: the schema was loosened to 1800 chars while every persona still said
"90-150 words", so the guidance described a quarter of the room the grammar
allowed. This file pins the relationship:

  - the guidance's upper word target, at a generous chars-per-word, must fit
    INSIDE the schema cap with headroom (the cap is a cliff -- storyteller.py
    treats landing exactly on maxLength as a grammar cut, so the target must
    never sit near it);
  - the guidance's lower word target must clear the schema minimum;
  - choice-text guidance must fit inside the choice maxLength.

Checked for the engine's neutral persona AND every shipped story's
storyteller.md that states a target, so a story cannot drift on its own.

Version: v0.1.0 [2026-08-13]
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from engine.agents.prompts import _NEUTRAL_PERSONA
from engine.lmstudio.schemas import (
    NARRATION_MAX_CHARS,
    NARRATION_MIN_CHARS,
    storyteller_turn_schema,
)

# Generous English averages, chars per word including the trailing space.
CHARS_PER_WORD_HIGH = 7.0  # long-worded prose still fits the cap at this rate
CHARS_PER_WORD_LOW = 4.0  # terse prose still clears the minimum at this rate

# Read from the schema itself so this file is not a second home for the number.
CHOICE_MAX_CHARS = storyteller_turn_schema()["schema"]["properties"]["choices"][
    "items"
]["properties"]["text"]["maxLength"]

_WORD_RANGE = re.compile(r"(\d+)\s*[-–]\s*(\d+)\s+words")
_CHOICE_LIMIT = re.compile(r"under\s+(\d+)\s+words", re.IGNORECASE)


def _story_prompts() -> list[Path]:
    root = Path("games")
    return sorted(root.glob("*/prompts/storyteller.md"))


def _targets(text: str) -> tuple[int, int] | None:
    found = _WORD_RANGE.search(text)
    return (int(found.group(1)), int(found.group(2))) if found else None


class TestNarrationGuidanceFitsTheGrammar:
    def _assert_coherent(self, low: int, high: int, source: str) -> None:
        assert high * CHARS_PER_WORD_HIGH <= NARRATION_MAX_CHARS * 0.85, (
            f"{source}: the {high}-word target leaves no headroom under the "
            f"{NARRATION_MAX_CHARS}-char grammar cap; the cap cuts mid-sentence"
        )
        assert low * CHARS_PER_WORD_LOW >= NARRATION_MIN_CHARS, (
            f"{source}: the {low}-word target can undershoot the "
            f"{NARRATION_MIN_CHARS}-char grammar minimum"
        )

    def test_the_neutral_persona(self) -> None:
        targets = _targets(_NEUTRAL_PERSONA)
        assert targets, "the neutral persona no longer states a word target"
        self._assert_coherent(*targets, source="engine neutral persona")

    @pytest.mark.parametrize(
        "path", _story_prompts(), ids=lambda p: p.parent.parent.name
    )
    def test_each_shipped_story(self, path: Path) -> None:
        text = path.read_text(encoding="utf-8")
        targets = _targets(text)
        if targets is None:
            pytest.skip(f"{path} states no word target of its own")
        self._assert_coherent(*targets, source=str(path))


class TestChoiceGuidanceFitsTheGrammar:
    @pytest.mark.parametrize(
        "source,text",
        [("engine neutral persona", _NEUTRAL_PERSONA)]
        + [
            (str(p), p.read_text(encoding="utf-8"))
            for p in _story_prompts()
        ],
    )
    def test_choice_word_limit_fits(self, source: str, text: str) -> None:
        found = _CHOICE_LIMIT.search(text)
        if found is None:
            pytest.skip(f"{source} states no choice word limit")
        words = int(found.group(1))
        assert words * CHARS_PER_WORD_HIGH <= CHOICE_MAX_CHARS, (
            f"{source}: 'under {words} words' does not fit the "
            f"{CHOICE_MAX_CHARS}-char choice cap"
        )
