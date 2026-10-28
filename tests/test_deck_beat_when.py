"""
A menu beat's own `when:` (v0.25.0 E5, spec §6.5).

Kept on the bound beat ONLY when authored, so every other story's beats bind to
the dicts they always did; `options` and `player_options` drop a beat whose
`when:` is false, and `resolve` (whose legality reads `options`) refuses it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

import pytest
import yaml

from engine.config import set_overlay
from tests import flagship_overhaul_recorder as rec

DECK = {
    "id": "the_door",
    "draw": 1,
    "when": {"min_day": 1},
    "cards": [{
        "id": "C1", "title": "A door", "tags": ["menu"],
        "beats": [
            {"id": "open_it", "text": "Open it.", "when": {"flag": "has_key"},
             "gate": {"on_pass": {"effects": [{"type": "flag", "flag": "opened", "value": True}]}}},
            {"id": "leave_it", "text": "Leave it."},
        ],
    }],
}


@pytest.fixture
def door(tmp_path: Path) -> Iterator[None]:
    """A one-deck story directory (the deck reader is memoized on path and mtime, so no reset)."""
    scenes = tmp_path / "scenes"
    scenes.mkdir()
    (scenes / "the_door.yaml").write_text(yaml.safe_dump(DECK), encoding="utf-8")
    set_overlay({"paths": {"decks": str(scenes)}})
    try:
        yield
    finally:
        set_overlay(None)


def test_a_beat_keeps_its_when_only_when_authored() -> None:
    from engine.content.deck import bound_beats

    bound = bound_beats(DECK["cards"][0]["beats"], "the_door", "C1")
    assert bound[0]["when"] == {"flag": "has_key"}
    assert "when" not in bound[1]


@pytest.mark.parametrize("slug", rec.OTHER_SIX)
def test_no_shipped_beat_outside_the_flagship_carries_one(slug: str) -> None:
    from engine.content import deck as deck_module

    with rec.active(slug):
        for deck_id in deck_module.deck_ids():
            for card in deck_module.load_deck(deck_id).cards:
                assert not any("when" in beat for beat in card.beats), f"{deck_id}/{card.id}"


def test_options_and_labels_drop_a_beat_whose_when_is_false(door) -> None:
    from engine.content import director
    from engine.game.effects import apply_effect
    from engine.game.state import GameState

    state = GameState(rng_seed=1)
    assert director.begin(state, "the_door")["ok"]
    assert [o["id"] for o in director.options(state)] == ["leave_it"]
    assert list(director.player_options(state)) == ["leave_it"]
    apply_effect(state, {"type": "flag", "flag": "has_key", "value": True})
    assert [o["id"] for o in director.options(state)] == ["open_it", "leave_it"]


def test_a_stale_pick_is_refused_at_resolve(door) -> None:
    from engine.content import director
    from engine.game.state import GameState

    state = GameState(rng_seed=1)
    director.begin(state, "the_door")
    out = director.resolve(state, chosen="open_it")
    assert out["ok"] is False and "is not on this card" in out["error"]
    assert not state.flags.get("opened")


def test_an_empty_choice_takes_the_first_offered_beat(door) -> None:
    """Plan decision 5: never the filtered-out first beat."""
    from engine.content import director
    from engine.game.state import GameState

    state = GameState(rng_seed=1)
    director.begin(state, "the_door")
    assert director.resolve(state, chosen="")["ok"] and not state.flags.get("opened")


@pytest.mark.parametrize("card, words", [
    ({"id": "S", "tags": [], "beats": [{"id": "a", "when": {"flag": "x"}}, {"id": "b"}]}, "not a menu"),
    ({"id": "M", "tags": ["menu"], "beats": [{"id": "a", "when": {"flag": "x"}}]}, "keep one without"),
    ({"id": "M", "tags": ["menu"], "beats": [{"id": "a", "when": {"no_such": 1}}, {"id": "b"}]}, "unknown predicate"),
])
def test_the_validator_names_a_misused_beat_when(card, words) -> None:
    from engine.content.deck import beat_when_problems

    assert any(words in p for p in beat_when_problems(card))


def test_a_card_with_no_beat_when_has_no_problem() -> None:
    from engine.content.deck import beat_when_problems

    assert beat_when_problems({"id": "M", "tags": ["menu"], "beats": [{"id": "a"}, {"id": "b"}]}) == []
