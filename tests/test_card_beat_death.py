"""
A card beat that drops hp to the death threshold is a death on that card
(v0.17.0, T1).

THE GAP. Encounters check death the moment an outcome lands
(``encounter.resolve_approach``); a job's stage does (``jobs.resolve_stage``);
``advance_time`` does every hour. A dealt card did not: ``director.resolve``
applied the beat's ``hp`` loss and returned, and a card turn moves no clock,
so the player stood at 0 hp answering the rest of the hand and died on
whatever later action next moved time -- after the narrator had already
described them walking on. HUE & CRY's Hanging Fair (v0.17) is a forced deck
dealt to a thief whom hunger routinely leaves on a few hp.

WHAT THESE TESTS HOLD.

- A card whose beats take hp to the threshold runs ``encounter.check_death``
  on that card: a terminal ``death.yaml`` block locks its ending there, a
  respawn carries the player out, and either way the hand ends (a scene
  cannot survive the player being carried out of it, as an encounter
  cannot) and the receipt carries the death record for the narrator.
- A card that takes no hp -- every card any story ships -- never calls it:
  byte-identical by construction.

Version: v0.1.0 [2026-09-27]
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator

import pytest

from engine.config import set_overlay
from engine.content import director
from engine.game import encounter, endings, epilogue
from engine.game.effects import apply_effect
from engine.game.state import GameState

from test_jobs import SQUARE, _dump
from test_jobs_stages import _world
from test_terminal_death_ending import _story


def _beat(beat_id: str, effects: list[dict[str, Any]]) -> dict[str, Any]:
    return {"id": beat_id, "text": beat_id, "gate": {"on_pass": {"effects": effects}}}


BRAWL = {
    "id": "brawl",
    "draw": 0,
    "cards": [
        {"id": "B1_the_punch", "required": True, "tags": ["sequence"], "title": "The Punch",
         "text": "INTENT: a fist.",
         "beats": [_beat("B1_hit", [{"type": "hp", "delta": -10}])]},
        {"id": "B2_after", "required": True, "tags": ["sequence"], "title": "After",
         "text": "INTENT: the crowd.",
         "beats": [_beat("B2_flag", [{"type": "flag", "flag": "saw_the_crowd"}])]},
    ],
}

CALM = {
    "id": "calm",
    "draw": 0,
    "cards": [
        {"id": "C1_quiet", "required": True, "tags": ["sequence"], "title": "Quiet",
         "text": "INTENT: nothing.",
         "beats": [_beat("C1_flag", [{"type": "flag", "flag": "was_quiet"}])]},
    ],
}


@pytest.fixture()
def story(tmp_path: Path) -> Iterator[Path]:
    paths = _story(tmp_path)
    scenes = tmp_path / "scenes"
    _dump(scenes / "brawl.yaml", BRAWL)
    _dump(scenes / "calm.yaml", CALM)
    paths["decks"] = str(scenes)
    set_overlay({"paths": paths})
    try:
        yield tmp_path
    finally:
        set_overlay(None)


def _deal(state: GameState, deck_id: str) -> None:
    receipt = director.begin(state, deck_id)
    assert receipt["ok"], receipt


def test_a_lethal_card_while_held_is_the_terminal_death_on_that_card(story: Path) -> None:
    state = _world()
    assert apply_effect(state, {"type": "arrest"})["ok"]
    state.stats.hp = 3
    _deal(state, "brawl")

    out = director.resolve(state)

    assert out["ok"] and out["death"]["terminal"] is True, out
    assert state.ended is True and endings.locked(state) == "the_rope"
    shown = epilogue.for_state(state)
    assert shown is not None and shown.ending_id == "the_rope"
    assert not director.active(state), "the hand outlived the death"
    assert out["scene_complete"] is True
    assert not state.flags.get("saw_the_crowd")


def test_a_lethal_card_otherwise_respawns_and_ends_the_hand(story: Path) -> None:
    state = _world(location="millhaven_market")
    state.stats.hp = 3
    _deal(state, "brawl")

    out = director.resolve(state)

    assert out["death"] and out["death"]["terminal"] is False, out
    assert state.stats.hp > 0 and state.location_id == SQUARE
    assert state.ended is False
    assert not director.active(state)
    assert not state.flags.get("saw_the_crowd")


def test_the_narrator_is_told_the_card_killed(story: Path) -> None:
    """Audit question 2: the receipt line the narrator reads says so."""
    from engine.agents.prompts import summarise_receipt

    state = _world(location="millhaven_market")
    state.stats.hp = 3
    _deal(state, "brawl")
    out = director.resolve(state)
    line = summarise_receipt({"skill": "resolve_scene_card", "result": out, "success": True})
    assert "You wake on the square." in line, line


def test_a_card_that_takes_no_hp_never_asks_about_death(
    story: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[Any] = []
    monkeypatch.setattr(encounter, "check_death", lambda *a, **k: calls.append(a))
    state = _world()
    state.stats.hp = 0  # already down, from elsewhere: not this card's business
    _deal(state, "calm")
    out = director.resolve(state)
    assert out["ok"] and "death" not in out
    assert calls == []


def test_a_card_that_wounds_but_does_not_kill_leaves_the_hand_open(story: Path) -> None:
    state = _world()
    state.stats.hp = state.stats.max_hp
    _deal(state, "brawl")
    out = director.resolve(state)
    assert out["ok"] and out.get("death") is None
    assert director.active(state)
