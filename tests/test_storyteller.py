"""Storyteller agent tests with mock LLM."""

from __future__ import annotations

import json

from engine.agents.storyteller import StorytellerAgent, parse_storyteller_response
from engine.game.engine import GameEngine
from engine.game.state import GameState


GOOD_RESPONSE = """
Mist clings to the birch trunks. Edgewood's smoke is a thin grey thread.

```json
{
  "tool_calls": [],
  "narration": "Mist clings to the birch trunks. Edgewood's smoke is a thin grey thread ahead.",
  "choices": [
    {"id": "a", "text": "Walk toward the smoke"},
    {"id": "b", "text": "Forage the clearing"}
  ],
  "npc_voices": [],
  "stat_changes": {},
  "items_gained": [],
  "items_lost": [],
  "skill_check": null,
  "tags_inline": "[IMAGE:forest_clearing_dawn]"
}
```
"""

BAD_MECHANICS_RESPONSE = """
You rolled a natural 20 and easily pass the check!

```json
{
  "tool_calls": [],
  "narration": "You rolled a natural 20 and easily pass the check!",
  "choices": [{"id": "a", "text": "Continue"}],
  "skill_check": null
}
```
"""

FIXED_RESPONSE = """
You move carefully; the forest does not give up its secrets easily.

```json
{
  "tool_calls": [
    {"name": "resolve_skill_check", "args": {"skill": "stealth", "dc": 12, "modifier": 0}}
  ],
  "narration": "You move carefully; the forest does not give up its secrets easily.",
  "choices": [
    {"id": "a", "text": "Press on"},
    {"id": "b", "text": "Hide"}
  ],
  "skill_check": {"skill": "stealth", "dc_mod": 0},
  "tags_inline": ""
}
```
"""


def test_parse_json_block():
    parsed = parse_storyteller_response(GOOD_RESPONSE)
    assert "birch" in parsed["narration"]
    assert len(parsed["choices"]) == 2
    assert "forest_clearing_dawn" in parsed["tags_inline"]


def test_storyteller_good_turn():
    state = GameState(location_id="forest_clearing")
    engine = GameEngine(state)

    def llm(_messages):
        return GOOD_RESPONSE

    agent = StorytellerAgent(engine, llm_fn=llm)
    result = agent.run_turn("The player looks toward the village smoke.")
    assert result.evaluation.passed is True
    assert len(result.choices) >= 2
    assert state.turn_number == 1


def test_storyteller_retries_on_hallucination():
    state = GameState(location_id="forest_clearing")
    engine = GameEngine(state)
    calls = {"n": 0}

    def llm(_messages):
        calls["n"] += 1
        if calls["n"] == 1:
            return BAD_MECHANICS_RESPONSE
        return FIXED_RESPONSE

    agent = StorytellerAgent(engine, llm_fn=llm)
    result = agent.run_turn("The player sneaks forward.")
    assert calls["n"] == 2
    assert result.retries == 1
    assert result.evaluation.passed is True
    assert any(r["skill"] == "resolve_skill_check" for r in result.tool_receipts)


def test_tool_calls_execute_move():
    state = GameState(location_id="forest_clearing")
    state.stats.stamina = 50
    engine = GameEngine(state)

    payload = {
        "tool_calls": [{"name": "move_to", "args": {"location_id": "edgewood_square"}}],
        "narration": "You follow the path to the village square.",
        "choices": [{"id": "a", "text": "Look around"}],
        "skill_check": None,
    }

    def llm(_messages):
        return f"```json\n{json.dumps(payload)}\n```"

    agent = StorytellerAgent(engine, llm_fn=llm)
    result = agent.run_turn("Walk to the village.")
    assert state.location_id == "edgewood_square"
    assert result.tool_receipts[0]["success"] is True