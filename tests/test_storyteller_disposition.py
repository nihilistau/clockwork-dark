"""
The storyteller's disposition is the story's to declare, and absent by default.

THE BUG. ``AgentMind.cruelty_bias`` defaulted to 0.2 and nothing anywhere ever
wrote it. The ``StorytellerMind`` directive fires "be merciful with
consequences" at ``<= 0.2``, so EVERY story received that line on EVERY turn --
the noir included, whose whole register is that the city is not merciful. The
existing governance test proved it without meaning to: to make the directive
silent it had to set the knob to 0.35 by hand.

``patience`` had the opposite problem: it only ever went DOWN, one point a turn,
so after sixty turns "the world grows impatient; raise the stakes" was
permanent in every story, however the stakes had actually moved.

Version: v0.1.0 [2026-09-23]
"""

from __future__ import annotations

import pytest

from engine.agents.governance import StorytellerMind
from engine.config import set_overlay
from engine.game.state import AgentMind, GameState


@pytest.fixture()
def overlay():
    yield set_overlay
    set_overlay(None)


def test_no_declared_disposition_means_no_line() -> None:
    assert "GM disposition" not in StorytellerMind().run_pre(GameState(), "SYS")


def test_the_frozen_knobs_are_gone() -> None:
    """A field nothing writes is a default pretending to be a decision."""
    mind = AgentMind()
    assert not hasattr(mind, "cruelty_bias")
    assert not hasattr(mind, "reward_generosity")


def test_an_old_save_carrying_the_knobs_still_loads() -> None:
    data = GameState().to_save_dict()
    data["storyteller_mind"]["cruelty_bias"] = 0.2
    data["storyteller_mind"]["reward_generosity"] = 0.5
    loaded = GameState.from_dict(data)
    assert "GM disposition" not in StorytellerMind().run_pre(loaded, "SYS")


@pytest.mark.parametrize(
    "settings, expected",
    [
        ({"cruelty_bias": 0.7}, "lean harsher with consequences"),
        ({"cruelty_bias": 0.1}, "be merciful with consequences"),
        ({"reward_generosity": 0.8}, "reward clever play generously"),
    ],
)
def test_a_declared_disposition_is_honoured(overlay, settings, expected) -> None:
    overlay({"storyteller": settings})
    assert expected in StorytellerMind().run_pre(GameState(), "SYS")


def test_the_settings_are_on_the_story_allowlist() -> None:
    from engine.games.manifest import SETTING_ALLOWLIST

    assert "storyteller.cruelty_bias" in SETTING_ALLOWLIST
    assert "storyteller.reward_generosity" in SETTING_ALLOWLIST


def test_patience_recovers_when_the_stakes_come_down() -> None:
    from engine.agents.storyteller import update_patience

    state = GameState()
    state.storyteller_mind.patience = 15.0
    state.story_pressure_prev, state.story_pressure = 0.8, 0.5
    update_patience(state)
    assert state.storyteller_mind.patience > 15.0


def test_patience_still_wears_down_on_a_flat_turn() -> None:
    """The original behaviour, kept: a story that is going nowhere gets pushed."""
    from engine.agents.storyteller import update_patience

    state = GameState()
    state.storyteller_mind.patience = 50.0
    state.story_pressure_prev = state.story_pressure = 0.4
    update_patience(state)
    assert state.storyteller_mind.patience == 49.0
