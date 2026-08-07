"""Evil ticker tests."""

from __future__ import annotations

from engine.config import reset_config
from engine.game.evil_ticker import EvilTicker, phase_from_progress
from engine.game.state import EvilPhase, GameState


def test_phase_boundaries():
    assert phase_from_progress(0.0) == EvilPhase.DORMANT
    assert phase_from_progress(0.19) == EvilPhase.DORMANT
    assert phase_from_progress(0.2) == EvilPhase.STIRRING
    assert phase_from_progress(0.49) == EvilPhase.STIRRING
    assert phase_from_progress(0.5) == EvilPhase.SPREADING
    assert phase_from_progress(0.79) == EvilPhase.SPREADING
    assert phase_from_progress(0.8) == EvilPhase.CONSUMING


def test_evil_progress_monotonic():
    reset_config()
    state = GameState(location_id="millhaven_gate")
    p0 = state.evil_progress
    EvilTicker.advance(state, days_elapsed=5.0)
    assert state.evil_progress > p0
    assert state.evil_progress <= 1.0


def test_forest_advances_slower_than_millhaven():
    reset_config()
    forest = GameState(location_id="forest_clearing")
    gate = GameState(location_id="millhaven_gate")
    EvilTicker.advance(forest, days_elapsed=10.0)
    EvilTicker.advance(gate, days_elapsed=10.0)
    assert gate.evil_progress > forest.evil_progress