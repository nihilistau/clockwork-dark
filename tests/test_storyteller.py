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


def test_the_tool_dispatcher_executes_a_move_when_it_is_handed_one():
    """
    THE DISPATCHER, NOT THE TURN. Read the name carefully before trusting this.

    This exercises ``execute_tool_calls`` (``storyteller.py``): given a reply
    that already contains a ``tool_calls`` array, the move is applied. It says
    NOTHING about whether a real turn can produce such a reply, and it was
    called ``test_tool_calls_execute_move`` for most of the project's life,
    which is how it got read as proof that a choice moves the player.

    It was not. Under the shipped ``structured_output: auto``
    (``config/default.yaml``), the turn grammar sets
    ``additionalProperties: False`` and declares no ``tool_calls`` property, so
    the key is UNSAMPLABLE and this path never runs. A player picked "Follow
    the smoke toward Edgewood", the narrator wrote the walk, and the save still
    read ``forest_clearing`` -- with this test green the whole time.

    The path is not dead, which is why the test stays: under
    ``structured_output: off`` (the native transport, the only one that can
    turn reasoning off) no grammar is sent and a fenced block like the one
    below IS parseable. It is config-dependent, and
    ``test_the_turn_grammar_forbids_tool_calls`` below pins that rule so the
    two halves cannot drift apart.

    What actually proves a choice moves the player is
    ``tests/test_turn_intent.py::test_a_travel_choice_actually_moves_the_player``
    and its per-story sibling, both of which drive a real ``run_turn`` and read
    the answer off ``GameState``.
    """
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


def test_the_turn_grammar_forbids_tool_calls():
    """
    The reachability rule the test above depends on, stated once.

    With a grammar on the wire, ``tool_calls`` cannot be sampled: the schema
    closes the object and never declares the property. That is the whole reason
    the intent channel had to exist, and it is asserted here rather than left as
    a claim in a docstring, so that adding the property back cannot silently
    resurrect a second way to change the world.
    """
    from engine.lmstudio.schemas import storyteller_turn_schema

    schema = storyteller_turn_schema()["schema"]
    assert schema.get("additionalProperties") is False, (
        "the turn object is open again; anything the model invents would be "
        "carried into the parsed turn"
    )
    assert "tool_calls" not in (schema.get("properties") or {}), (
        "the turn grammar declares tool_calls -- a narration turn can change "
        "the world by a second route, and engine/game/intents.py is no longer "
        "the only one"
    )

def test_an_outage_does_not_latch_on_for_the_rest_of_the_session():
    """
    ``llm_unavailable`` reports THIS turn, not the worst turn so far.

    ``_llm_failed`` was set once in ``__init__`` and raised on the first
    backend failure, and the agent is session-scoped -- so a single transient
    LM Studio hiccup pinned "The Storyteller is unreachable" on screen for the
    remainder of the run, while narration streamed in perfectly well behind the
    banner. Nothing ever lowered it.
    """
    state = GameState(location_id="forest_clearing")
    engine = GameEngine(state)
    calls = {"n": 0}

    def llm(_messages):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("LM Studio is not answering")
        return GOOD_RESPONSE

    agent = StorytellerAgent(engine, llm_fn=llm)

    first = agent.run_turn("The player looks toward the village smoke.")
    assert first.llm_unavailable is True, "the outage was not reported at all"

    second = agent.run_turn("The player starts down the path.")
    assert second.llm_unavailable is False, (
        "the banner stayed up on a turn the model answered -- the failure flag "
        "is per-agent instead of per-turn"
    )
