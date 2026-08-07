"""Location graph tests."""

from __future__ import annotations

from engine.game.engine import GameEngine
from engine.game.locations import CANONICAL_LOCATION_IDS, can_travel
from engine.game.state import GameState


def test_canonical_ids():
    expected = {
        "forest_clearing",
        "edgewood_square",
        "edgewood_bakery",
        "tinker_caravan",
        "millhaven_gate",
    }
    assert expected == CANONICAL_LOCATION_IDS


def test_valid_travel():
    assert can_travel("forest_clearing", "edgewood_square")
    assert not can_travel("forest_clearing", "millhaven_gate")


def test_move_to_rejects_invalid():
    state = GameState(location_id="forest_clearing")
    engine = GameEngine(state)
    result = engine.move_to("millhaven_gate")
    assert result.success is False