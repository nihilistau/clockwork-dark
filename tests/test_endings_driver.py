"""
The per-ending driver's own doors, on a synthetic story (v0.17.0, T1).

``tests/test_finales.py`` drives shipped endings through quest and card doors
(HUE & CRY's barge, the Garden's finale card). The other two kinds -- a
set-piece and a death -- have no shipped ending behind them yet, so they are
proved here on the synthetic two-ending story ``test_terminal_death_ending``
builds (``honest``, the fail-forward, and ``the_rope``, gated on a flag
nothing sets), with one set-piece added. And the driver is shown to FAIL when
a door locks the wrong ending: a helper that could not fail would prove
nothing for the eight endings that will lean on it.

Version: v0.1.0 [2026-09-27]
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

import pytest

from engine.challenges import set_pieces
from engine.config import set_overlay
from engine.game.effects import apply_effect
from engine.game.state import GameState

from endings_driver import Door, drive_ending
from test_jobs import SQUARE, _dump
from test_jobs_stages import _world
from test_terminal_death_ending import _story

WALK_OUT = {
    "set_pieces": [{
        "id": "walk_out",
        "location_id": SQUARE,
        "grants_flag": "walked_out",
        "challenge": {
            "id": "walk_out",
            "kind": "puzzle",
            "title": "The Open Gate",
            "prompt": "What do you do with an open gate?",
            "answer": "leave",
            "attempts": 2,
            "reward": {
                "text": "You go.",
                "effects": [{"type": "ending_lock", "ending": "honest"},
                            {"type": "ending_module"}],
            },
            "fail": {"text": "You stay.", "effects": []},
        },
    }]
}


#: A deck whose ending card is a POOL card behind its own `when:` -- the
#: shortcut a forced deal would skip.
CONFESSION = {
    "id": "confession",
    "draw": 1,
    "cards": [
        {"id": "C1_the_truth", "tags": ["menu"], "title": "The Truth",
         "text": "INTENT: an honest end.",
         "when": {"flag": "ready_to_confess"},
         "beats": [
             {"id": "C1_say_it", "text": "Say it.",
              "gate": {"on_pass": {"effects": [{"type": "ending_lock", "ending": "honest"},
                                                {"type": "ending_module"}]}}},
             {"id": "C1_dont", "text": "Don't.",
              "gate": {"on_pass": {"effects": [{"type": "flag", "flag": "kept_quiet"}]}}},
         ]},
    ],
}


@pytest.fixture()
def story(tmp_path: Path) -> Iterator[Path]:
    paths = _story(tmp_path)
    paths["challenges"] = str(Path(_dump(tmp_path / "challenges" / "gate.yaml", WALK_OUT)).parent)
    paths["decks"] = str(Path(_dump(tmp_path / "scenes" / "confession.yaml", CONFESSION)).parent)
    set_pieces.reset_set_piece_cache()
    set_overlay({"paths": paths})
    try:
        yield tmp_path
    finally:
        set_overlay(None)
        set_pieces.reset_set_piece_cache()


def _held(state: GameState) -> None:
    assert apply_effect(state, {"type": "arrest"})["ok"]


def test_a_set_piece_door(story: Path) -> None:
    state, card = drive_ending(None, "honest", Door.set_piece("walk_out", {"answer": "leave"}),
                               state=_world())
    assert card.card_m == "You left."
    assert state.flags.get("walked_out") is True


def test_a_death_door(story: Path) -> None:
    state, card = drive_ending(None, "the_rope", Door.death(), _held, state=_world())
    assert state.ended is True and card.card_m == "They hanged you."


def _ready(state: GameState) -> None:
    assert apply_effect(state, {"type": "flag", "flag": "ready_to_confess"})["ok"]


def test_a_card_door_on_a_gated_pool_card(story: Path) -> None:
    state, card = drive_ending(None, "honest", Door.card("confession", "C1_the_truth", "C1_say_it"),
                               _ready, state=_world())
    assert card.card_m == "You left."


def test_the_driver_fails_a_card_door_whose_gate_the_setup_never_met(story: Path) -> None:
    """No shortcut deal: a forced placement would put the card in the hand
    whatever its `when:` says. The driver refuses it instead."""
    with pytest.raises(AssertionError, match="not eligible"):
        drive_ending(None, "honest", Door.card("confession", "C1_the_truth", "C1_say_it"),
                     state=_world())


def test_the_driver_fails_a_door_that_locks_another_ending(story: Path) -> None:
    with pytest.raises(AssertionError, match="locked 'honest', not 'the_rope'"):
        drive_ending(None, "the_rope", Door.set_piece("walk_out", {"answer": "leave"}),
                     state=_world())


def test_the_driver_fails_a_door_that_never_opens(story: Path) -> None:
    """A death with no custody respawns: not the terminal door."""
    with pytest.raises(AssertionError, match="not terminal"):
        drive_ending(None, "the_rope", Door.death(), state=_world())


def test_the_driver_fails_a_failed_set_piece(story: Path) -> None:
    with pytest.raises(AssertionError, match="did not end in success"):
        drive_ending(None, "honest",
                     Door.set_piece("walk_out", {"answer": "stay"}, {"answer": "sit"}),
                     state=_world())


def test_the_driver_fails_an_undeclared_ending(story: Path) -> None:
    with pytest.raises(AssertionError, match="not an ending this story declares"):
        drive_ending(None, "the_noose", Door.death(), _held, state=_world())
