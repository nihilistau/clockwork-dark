"""
The continuity guard — narration that disagrees with the save file.

WHAT IT CHECKS, AND WHY ONLY THAT. General contradiction detection needs a
model. This catches the one contradiction the ledger can PROVE: treating
somebody as a stranger when `SubjectMemory.met` says the player has met them.
`met` was set by the engine when the meeting happened, so a narration that has
a met character introduce themselves is not a judgement call about tone -- it
is the narrator disagreeing with state.

It earns a gate because before the memory work it was the DEFAULT failure. The
narrator got one sentence per character ("maris has met you and is neutral
toward you") and everything else sat unread, so a character could greet you as
a stranger on your fourth visit. The dossier is in the prompt now; this asks
whether the prompt was believed.

THE FALSE-POSITIVE CONTROLS ARE THE POINT OF THIS FILE. A guard that fires on
correct prose is worse than no guard -- the lesson from the 205 Garden beats
and from two abandoned attempts at flag reachability. "A stranger" three
paragraphs from a known name, about somebody else, must not trip it.
"""

from __future__ import annotations

import pytest

from engine.agents.continuity import (
    continuity_note,
    find_reintroduction,
    known_cast,
)
from engine.agents.evaluator import StorytellerEvaluator
from engine.memory.ledger import StoryLedger


CAST = {"maris": ("Maris",)}


# ---------------------------------------------------------------------------
# it fires on the thing it is for
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "narration",
    [
        "Maris introduces herself, wiping flour from her hands.",
        "A woman you have never seen looks up. Maris, she says.",
        "Maris gives her name as Maris, and waits.",
        "Maris looks up from the counter. Who are you?",
    ],
)
def test_meeting_someone_you_know_is_caught(narration: str) -> None:
    assert find_reintroduction(narration, CAST) == "Maris"


def test_the_note_names_who_was_forgotten() -> None:
    """
    "Do not introduce strangers" is unactionable in exactly the way "do not
    invent people" was for the cast check: the model cannot tell which of the
    names it wrote was the wrong one.
    """
    note = continuity_note("Maris")
    assert "Maris" in note
    assert "already met" in note


# ---------------------------------------------------------------------------
# it does not fire on correct prose
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "narration",
    [
        "Maris nods at you and goes on kneading.",
        "Maris says nothing about the money, which is how you know she remembers.",
        "You have never seen the sky this colour. Maris is at her counter.",
        "Maris looks at you the way you look at a stranger.",
        "You see the whole square for the first time. Maris waves.",
    ],
)
def test_ordinary_prose_about_a_known_character_passes(narration: str) -> None:
    assert find_reintroduction(narration, CAST) is None


def test_a_stranger_far_from_a_known_name_is_not_a_contradiction() -> None:
    """
    The proximity window is what makes this usable. A narration may perfectly
    well contain both a character you know and a stranger you do not -- that is
    an ordinary scene, not a continuity error.
    """
    narration = (
        "Maris hands you the loaf without being asked, and says the frost is "
        "coming early this year. " + ("The room is warm. " * 24) +
        "By the door, a stranger is shaking rain off a heavy coat."
    )
    assert find_reintroduction(narration, CAST) is None


def test_an_unmet_character_is_not_the_guard_s_business() -> None:
    """
    Introducing somebody you have NOT met is correct writing. `known_cast`
    only ever contains met characters, so an empty cast makes the whole
    criterion inert -- turn zero must not be penalised for having no history.
    """
    assert find_reintroduction("A stranger introduces herself as Maris.", {}) is None


def test_known_cast_is_empty_without_state_or_ledger() -> None:
    assert known_cast(None, None) == {}
    assert known_cast(None, StoryLedger()) == {}


# ---------------------------------------------------------------------------
# the gate
# ---------------------------------------------------------------------------


def _evaluate(narration: str, **kwargs):
    return StorytellerEvaluator().evaluate(
        narration,
        {"narration": narration, "choices": [{"id": "a", "text": "Go on"}]},
        tool_receipts=[],
        **kwargs,
    )


def test_the_evaluator_fails_a_forgotten_character() -> None:
    result = _evaluate(
        "Maris introduces herself, wiping flour from her hands. " * 6,
        known_cast=CAST,
    )
    assert result.continuity == 0.0
    assert result.passed is False
    assert any("Maris" in note for note in result.notes)


def test_the_gate_is_inert_with_no_history() -> None:
    """
    The counter-control. Without this, a passing suite would prove only that
    the criterion defaults to 1.0 and never that it can fail.
    """
    result = _evaluate("Maris introduces herself, wiping flour from her hands. " * 6)
    assert result.continuity == 1.0


def test_continuity_is_a_gate_and_not_a_weighted_nudge() -> None:
    """
    A scene that forgets who the player knows has written the WRONG scene, not
    a slightly worse one, so scoring well on tone must not rescue it.
    """
    good = _evaluate("Maris nods at you and goes on kneading. " * 8, known_cast=CAST)
    bad = _evaluate("Maris introduces herself and asks who you are. " * 8, known_cast=CAST)
    assert good.passed is True
    assert bad.passed is False
