"""
The scene director: dealing an authored hand into a running turn.

``deck.draw`` and ``resolve_card`` were called by ``scripts/simulate_decks.py``
and by tests, and by nothing in a running game. The Wicked Garden ships 11
decks, 136 cards and 386 beats, and its only ``ending_lock`` sits on a card in
``day_09_finale`` -- so the largest body of authored prose in the repo was
unreachable and the game could not be finished by playing it.

Two properties matter here and they pull against each other:

* a deck story must now actually DEAL, and
* a graph story must be untouched, byte for byte.

The second is not a matter of care. ``deck_ids()`` reads ``paths.decks``, and
The Clockwork Dark and NEON CITY declare none -- so ``due()`` returns on its
first line. That is a property of the data, and it is asserted here rather than
assumed.
"""

from __future__ import annotations

import json

import pytest

from engine.games import registry
from engine.persistence import reset_save_store
from engine.persistence.saves import SaveStore


@pytest.fixture
def garden():
    """The Wicked Garden active, restored afterwards."""
    registry.activate("wicked-garden")
    try:
        yield
    finally:
        registry.deactivate()


def _state(location_id: str = "mortal_threshold"):
    from engine.game.state import GameState

    return GameState(location_id=location_id)


# -- inertness for graph stories -----------------------------------------


@pytest.mark.parametrize("slug", ["clockwork-dark", "neon-city"])
def test_a_story_with_no_decks_never_opens_a_scene(slug: str) -> None:
    """
    THE COMPATIBILITY GATE for the three graph-shaped games.

    Not "the director is careful with them" -- it cannot see them at all.
    ``deck_ids()`` is empty, so ``due`` returns before reading any state.
    """
    from engine.content import deck, director

    registry.activate(slug)
    try:
        assert deck.deck_ids() == [], f"{slug} unexpectedly declares decks"
        state = _state()
        assert director.due(state) == ("", "", "")
        assert director.ensure_scene(state) == []
        assert director.active(state) is False
        assert state.scene == {}
    finally:
        registry.deactivate()


def test_a_graph_turn_is_unchanged_by_the_director() -> None:
    """
    A flagship turn produces the same payload with the director in the loop.

    The regression gate for the games that were working before this landed.
    """
    from engine.scenes.default_state import SessionStore, run_turn

    reset_save_store()
    narration = "The oven ticks as it cools and the room keeps the morning's bread."
    llm = lambda _m: json.dumps(  # noqa: E731
        {
            "narration": narration,
            "choices": [{"id": "a", "text": "Wait"}, {"id": "b", "text": "Listen"}],
        }
    )
    session = SessionStore().create(seed=42, llm_fn=llm)
    turn = run_turn(session, "The player chooses: Wait")

    assert turn["narration"] == narration
    assert turn["state"]["scene"] == {}
    # And no scene receipt was manufactured on a story with no decks.
    assert not [r for r in turn["tool_receipts"] if r.get("type") == "scene"]
    reset_save_store()


# -- dealing -------------------------------------------------------------


def test_the_garden_deals_its_first_day(garden) -> None:
    from engine.content import director

    state = _state()
    receipts = director.ensure_scene(state)

    assert receipts, "no scene was dealt on a story whose decks are all scheduled"
    result = receipts[0]["result"]
    assert result["ok"] is True
    assert result["deck_id"] == "day_00_prologue"
    assert result["source"] == "scheduled"
    assert director.active(state) is True
    assert state.scene["cursor"] == 0


def test_a_dealt_deck_is_not_dealt_again(garden) -> None:
    """Without the played flag, a scheduled deck re-deals every turn."""
    from engine.content import director

    state = _state()
    director.ensure_scene(state)
    while director.active(state):
        director.resolve(state, chosen=director.options(state)[0]["id"])

    assert state.scene == {}
    # Day 0's `when` is still true on day 0, so only the flag stops a re-deal.
    deck_id, _, _ = director.due(state)
    assert deck_id != "day_00_prologue"


def test_only_one_scene_opens_per_turn(garden) -> None:
    """A hand IS the turn; dealing two means the player answered neither."""
    from engine.content import director

    state = _state()
    first = director.ensure_scene(state)
    second = director.ensure_scene(state)
    assert first and not second


# -- answering -----------------------------------------------------------


def test_resolving_a_menu_card_applies_exactly_one_beat(garden) -> None:
    """
    A menu card's beats are BRANCHES of one question. Applying them all means
    the player both looks at their mortal home and refuses to.
    """
    from engine.content import director

    state = _state()
    director.ensure_scene(state)
    card = director.current_card(state)
    assert "menu" in card.tags, "this test needs a menu card"

    result = director.resolve(state, chosen=director.options(state)[0]["id"])
    assert result["ok"] is True
    assert len(result["beats"]) == 1


def test_an_illegal_beat_is_refused_rather_than_silently_dropped(garden) -> None:
    """
    A refusal reaches the prose through the intent machinery. A silent no-op
    would let the narration describe an outcome the engine never produced.
    """
    from engine.content import director

    state = _state()
    director.ensure_scene(state)
    before = dict(state.meters)

    result = director.resolve(state, chosen="no_such_beat")

    assert result["ok"] is False
    assert "not on this card" in result["error"]
    assert result["options"], "a refusal must say what WAS legal"
    assert state.meters == before, "a refused beat still moved the world"


def test_the_hand_closes_when_its_last_card_is_answered(garden) -> None:
    from engine.content import director

    state = _state()
    director.ensure_scene(state)
    guard = 0
    while director.active(state):
        director.resolve(state, chosen=director.options(state)[0]["id"])
        guard += 1
        assert guard <= director.MAX_SCENE_CARDS + 1, "the hand never ended"

    assert state.scene == {}
    assert director.current_card(state) is None


# -- the intent seam -----------------------------------------------------


def test_an_open_scene_suppresses_every_other_verb(garden) -> None:
    """
    Same rule as an encounter: while a scene is open the engine owns the option
    list, so the narrator cannot offer a road out of it.
    """
    from engine.content import director
    from engine.game.intents import legal_intents

    state = _state()
    director.ensure_scene(state)

    verbs = legal_intents(state)
    assert [v.action for v in verbs] == ["card"]
    offered = {opt for v in verbs for opt, _label in v.options}
    assert offered == {row["id"] for row in director.options(state)}


def test_the_card_verb_resolves_through_the_engine(garden) -> None:
    """End to end: intent -> tool call -> director -> world moved."""
    from engine.agents.tool_dispatcher import execute_intent
    from engine.content import director
    from engine.game.engine import GameEngine

    state = _state()
    engine = GameEngine(state)
    director.ensure_scene(state)
    chosen = director.options(state)[0]["id"]
    before = dict(state.meters)

    receipts = execute_intent({"action": "card", "target": chosen}, engine)

    assert receipts and receipts[0]["success"] is True
    assert state.meters != before, "the card resolved and nothing moved"
    assert state.scene["cursor"] == 1


# -- persistence ---------------------------------------------------------


def test_a_scene_survives_a_save_and_reload(garden) -> None:
    """
    Mid-hand is a real place to close the browser. Card IDS are stored rather
    than card objects, so this also proves the ids re-resolve.
    """
    from engine.content import director
    from engine.game.state import GameState

    state = _state()
    director.ensure_scene(state)
    director.resolve(state, chosen=director.options(state)[0]["id"])
    assert state.scene["cursor"] == 1

    reloaded = GameState.from_dict(state.to_save_dict())

    assert reloaded.scene == state.scene
    assert director.active(reloaded) is True
    assert director.current_card(reloaded).id == director.current_card(state).id


def test_a_card_deleted_from_the_deck_is_skipped_not_raised_on(garden) -> None:
    """
    The reason ids are stored and not copies: a deck edited mid-run degrades to
    "that card is gone" instead of replaying a card the author has rewritten.
    """
    from engine.content import director

    state = _state()
    director.ensure_scene(state)
    state.scene["card_ids"] = ["definitely_not_a_card"] + list(
        state.scene["card_ids"]
    )
    state.scene["cursor"] = 0

    card = director.current_card(state)
    assert card is not None
    assert card.id != "definitely_not_a_card"
