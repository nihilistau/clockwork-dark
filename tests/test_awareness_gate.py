"""Awareness gate interceptor tests."""

from __future__ import annotations

from engine.game.state import GameState
from engine.lore.interceptors import (
    AwarenessGateInterceptor,
    mark_spoiler,
    run_pre_interceptors,
)


def test_strips_clockwork_dark_below_threshold():
    gate = AwarenessGateInterceptor()
    text = "The Clockwork Dark spreads through the wheat."
    result = gate.gate(text, awareness=10.0)
    assert "Clockwork Dark" not in result
    assert "something wrong in the wheat" in result


def test_preserves_term_above_threshold():
    gate = AwarenessGateInterceptor()
    text = "The Clockwork Dark spreads."
    result = gate.gate(text, awareness=25.0)
    assert "Clockwork Dark" in result


def test_run_pre_gates_only_marked_regions():
    state = GameState(awareness=5.0)
    prompt = (
        'You are the STORYTELLER of "The Clockwork Dark".\n'
        + mark_spoiler("A rumor names the Clockwork Dark outright.")
    )
    result = run_pre_interceptors(
        state,
        prompt,
        interceptors=[AwarenessGateInterceptor()],
    )
    # The marked rumor is redacted, and reads as English -- matching the bare
    # term used to leave a dangling article: "names the something wrong in...".
    assert "A rumor names something wrong in the wheat outright." in result
    # ...but the game's own title survives in its own instructions. This used
    # to read: You are the STORYTELLER of "something wrong in the wheat".
    assert 'STORYTELLER of "The Clockwork Dark"' in result


def test_run_pre_leaves_instructions_untouched_at_zero_awareness():
    state = GameState(awareness=0.0)
    prompt = "You are the STORYTELLER (Game Master) of \"The Clockwork Dark\"."
    result = run_pre_interceptors(
        state,
        prompt,
        interceptors=[AwarenessGateInterceptor()],
    )
    assert result == prompt


def test_markers_are_stripped_above_threshold():
    state = GameState(awareness=90.0)
    prompt = "Intro. " + mark_spoiler("The Clockwork Dark is named.")
    result = run_pre_interceptors(
        state,
        prompt,
        interceptors=[AwarenessGateInterceptor()],
    )
    assert "<<<SPOILER" not in result
    assert "SPOILER>>>" not in result
    assert "The Clockwork Dark is named." in result


def test_run_post_gates_model_output():
    """The model can leak the term on its own; output must be gated too."""
    gate = AwarenessGateInterceptor()
    state = GameState(awareness=2.0)
    leaked = "You feel the Clockwork Dark turning under the field."
    assert "Clockwork Dark" not in gate.run_post(state, leaked)
