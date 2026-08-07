"""Pytest fixtures."""

from __future__ import annotations

import pytest

from engine.game.engine import GameEngine, set_active_engine
from engine.game.state import GameState


@pytest.fixture
def game_state() -> GameState:
    """Fresh game state."""
    return GameState()


@pytest.fixture
def engine(game_state: GameState) -> GameEngine:
    """Game engine with active context bound."""
    eng = GameEngine(game_state)
    set_active_engine(eng)
    return eng