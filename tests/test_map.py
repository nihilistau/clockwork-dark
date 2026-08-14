"""
The map — the graph a player can finally see, and the places they must not.

The atlas payload has carried places, rings, roads and a discovered flag since
the codex was built, and exactly one screen read it: the flagship's Codex, as a
grid of cards. Three of the four shipped stories had a travel graph and no way
to look at it.

TWO KINDS OF HIDDEN, and only one was expressible. `discovered` is fog of war:
you have not walked there, so the place is drawn and greyed, because knowing a
road exists is not knowing what is down it. `secret: true` is a spoiler: the
player must not know the place EXISTS, so it is withheld from the payload
entirely -- along with any road that points at it, since drawing the edge and
omitting the destination advertises exactly what withholding it was for.

The negative controls are the point of this file. A test that only checks a
secret place is absent would pass against a build that sent nothing at all.
"""

from __future__ import annotations

import pytest

from engine.game.state import GameState
from engine.games import registry
from engine.scenes.default_api import codex_places, map_points


@pytest.fixture
def flagship() -> GameState:
    registry.activate("clockwork-dark")
    state = GameState(session_id="map-test")
    state.location_id = "edgewood_square"
    return state


@pytest.fixture
def with_a_secret(flagship: GameState, monkeypatch: pytest.MonkeyPatch) -> GameState:
    """A secret place hung off the square, and the square's road to it."""
    from engine.game import locations as locations_module

    graph = dict(locations_module.LOCATIONS)
    graph["smugglers_cut"] = {
        "name": "The Smugglers' Cut",
        "ring": 2,
        "secret": True,
        "connections": {"edgewood_square": {"hours": 1}},
    }
    square = dict(graph["edgewood_square"])
    square["connections"] = {
        **(square.get("connections") or {}),
        "smugglers_cut": {"hours": 1},
    }
    graph["edgewood_square"] = square
    monkeypatch.setattr(locations_module, "LOCATIONS", graph)
    return flagship


def test_the_graph_reaches_the_browser(flagship: GameState) -> None:
    """The green control: without this, every assertion below is vacuous."""
    places = codex_places(flagship)
    assert len(places) > 5
    assert any(place["here"] for place in places)
    assert any(place["roads"] for place in places)


def test_an_unvisited_place_is_drawn_but_blank(flagship: GameState) -> None:
    """
    Fog of war, not a secret. The shape of the map is public; what is behind
    the next tree is not.
    """
    places = {p["id"]: p for p in codex_places(flagship)}
    unvisited = [p for p in places.values() if not p["discovered"]]
    assert unvisited, "everything was already discovered; test proves nothing"
    assert all(p["image"] == "" for p in unvisited)


def test_a_secret_place_never_reaches_the_browser(with_a_secret: GameState) -> None:
    ids = {p["id"] for p in codex_places(with_a_secret)}
    assert "smugglers_cut" not in ids


def test_a_road_to_a_secret_place_is_secret_too(with_a_secret: GameState) -> None:
    """
    Withholding the place and drawing the road would give it away in the act of
    keeping it: a road to nowhere is the loudest possible hint.
    """
    places = {p["id"]: p for p in codex_places(with_a_secret)}
    assert not any(
        road["to"] == "smugglers_cut" for road in places["edgewood_square"]["roads"]
    )


def test_walking_there_reveals_it_permanently(with_a_secret: GameState) -> None:
    """A discovery, not a lie: once found, a secret place is an ordinary one."""
    with_a_secret.quests = {"_meta": {"visited": ["smugglers_cut"]}}
    places = {p["id"]: p for p in codex_places(with_a_secret)}
    assert "smugglers_cut" in places
    assert places["smugglers_cut"]["discovered"] is True
    assert any(
        road["to"] == "smugglers_cut" for road in places["edgewood_square"]["roads"]
    )


def test_points_are_derived_from_live_quest_state(flagship: GameState) -> None:
    """
    A point of interest is a VIEW of things the story already declares, never a
    second content type. Authoring map pins separately would be a second place
    to forget to update, and the first symptom would be a map pointing at a
    quest that ended two days ago.
    """
    from engine.game.quests import QuestEngine

    QuestEngine.evaluate(flagship)
    points = map_points(flagship)
    labels = [p["label"] for rows in points.values() for p in rows]
    kinds = {p["kind"] for rows in points.values() for p in rows}

    assert labels, "no points derived at all; the derivation is not running"
    assert kinds <= {"objective", "vendor"}


def test_points_ride_on_the_place_they_belong_to(flagship: GameState) -> None:
    places = {p["id"]: p for p in codex_places(flagship)}
    assert all("points" in place for place in places.values())
    points = map_points(flagship)
    for place_id, rows in points.items():
        if place_id in places:
            assert places[place_id]["points"] == rows


def test_a_story_with_no_graph_yields_no_map() -> None:
    """
    The counter-control for the client's gate. A deck story has places but the
    map button is hidden on `world.location_id`; a story with no graph at all
    must produce an empty list rather than an error, so "no map" is a state and
    not a crash.
    """
    registry.activate("wicked-garden")
    try:
        state = GameState(session_id="deck-test")
        assert isinstance(codex_places(state), list)
        assert isinstance(map_points(state), dict)
    finally:
        registry.activate("clockwork-dark")
