"""
Narration executes no ``tool_calls``, on any config (spec finding 5, §4.4).

THE BUG. ``parse_storyteller_response`` keeps any ``tool_calls`` array a reply
carries, and ``StorytellerAgent.run_turn`` handed it to
``tool_dispatcher.execute_tool_calls``. With the turn grammar on the wire the
array cannot be sampled (the schema closes the object and declares no such
key). Under ``structured_output: off`` -- which ``config/default.yaml``
recommends for reasoning models, and which ``auto`` becomes whenever the probe
fails -- nothing forbids it, so a narration turn could move the player through
the very channel AGENTS.md rule 1 forbids: the world changed by what the
narrator wrote, not by what the engine resolved.

THE FIX deletes the call. Intents are the channel: a choice's ``intent`` is
executed by ``execute_intent`` before the next narration, and refused in the
prose when it has gone illegal. The dispatcher keeps its production caller
(``engine/agents/assistant.py``).

Both tests fail on v0.18.0, where the reply below walks the player to
``edgewood_square``.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from tests.llm_golden import _compat_json, _models
from tests.llm_wire import wire

NARRATION = (
    "You follow the path east until the birches thin and the smoke of the "
    "village rises ahead. A cart rattles somewhere out of sight, and a dog "
    "barks twice and falls quiet. The square opens in front of you, cobbled "
    "and wet, with a clock face above the bakery door that has stopped at "
    "a quarter past nine."
)

REPLY = {
    "narration": NARRATION,
    "choices": [
        {"id": "a", "text": "Look for the baker"},
        {"id": "b", "text": "Study the stopped clock"},
    ],
    "tool_calls": [{"name": "move_to", "args": {"location_id": "edgewood_square"}}],
}


def _agent(llm_fn: Any = None) -> Any:
    from engine.agents.storyteller import StorytellerAgent
    from engine.game.engine import GameEngine
    from engine.game.procgen import new_game_state

    return StorytellerAgent(GameEngine(new_game_state(seed=7)), llm_fn=llm_fn)


@pytest.fixture
def flagship() -> Any:
    from engine.games import registry

    registry.activate("clockwork-dark")
    try:
        yield
    finally:
        registry.deactivate()


@pytest.mark.real_discovery
def test_a_turn_under_structured_output_off_moves_nobody(
    llm_server: Any, flagship: Any
) -> None:
    """The real path: no grammar on the wire, a reply carrying ``tool_calls``."""
    llm_server("lmstudio", structured_output="off")
    agent = _agent()
    assert agent.engine.state.location_id == "forest_clearing"
    answer = _compat_json(json.dumps(REPLY))
    with wire([_models(), answer, answer]) as seam:
        result = agent.run_turn("I follow the path east.")
    chats = [r for r in seam.requests if r["method"] == "POST"]
    assert chats, "the turn never asked the model"
    assert "response_format" not in json.loads(chats[0]["body"])
    assert agent.engine.state.location_id == "forest_clearing"
    assert not any(r.get("skill") == "move_to" for r in result.tool_receipts)


def test_an_injected_reply_carrying_tool_calls_moves_nobody(flagship: Any) -> None:
    """The same reply from an injected ``llm_fn``: nothing executes it either."""
    agent = _agent(llm_fn=lambda _messages: json.dumps(REPLY))
    result = agent.run_turn("I follow the path east.")
    assert agent.engine.state.location_id == "forest_clearing"
    assert not any(r.get("skill") == "move_to" for r in result.tool_receipts)
