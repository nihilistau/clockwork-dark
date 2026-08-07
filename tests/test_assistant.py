"""Assistant agent tests — agency, forms, skills, STT stub."""

from __future__ import annotations

import json
import random

import pytest

from engine.agents.assistant import (
    AssistantAgent,
    parse_assistant_response,
    should_assistant_speak,
)
from engine.agents.prompts import assistant_system_prompt
from engine.game.engine import GameEngine
from engine.game.state import GameState
from engine.media.stt import STTClient
from engine.skills.builtin.assistant import (
    ASSISTANT_FORMS,
    compute_hint_tier,
    grant_hint,
    reveal_lore,
    change_form,
)
from engine.skills.registry import SKILL_REGISTRY
from engine.game.engine import set_active_engine


SPEAK_RESPONSE = """
[VOICE:whisper] The smoke lies about its source.

```json
{
  "text": "The smoke lies about its source.",
  "tool_calls": [],
  "voice_style": "whisper"
}
```
"""

HINT_RESPONSE = """
A cat might know, if you listen.

```json
{
  "text": "A cat might know, if you listen.",
  "tool_calls": [{"name": "grant_hint", "args": {"tier": 1}}],
  "voice_style": "chime"
}
```
"""


def test_compute_hint_tier():
    assert compute_hint_tier(10.0, 0.0) == 1
    assert compute_hint_tier(35.0, 0.0) == 2
    assert compute_hint_tier(65.0, 0.0) == 3
    assert compute_hint_tier(10.0, 25.0) == 3


def test_assistant_skills_registered():
    assert SKILL_REGISTRY.get("grant_hint") is not None
    assert SKILL_REGISTRY.get("reveal_lore") is not None
    assert SKILL_REGISTRY.get("change_form") is not None


def test_prompt_excludes_evil_progress():
    state = GameState(evil_progress=0.75, awareness=5.0)
    prompt = assistant_system_prompt(state, hint_tier=2)
    assert "evil_progress" not in prompt
    assert "HINT TIER: 2" in prompt
    assert "cat" in prompt


def test_agency_silent_branch():
    state = GameState()
    state.assistant_mind.help_probability = 0.0
    engine = GameEngine(state)
    rng = random.Random(0)

    agent = AssistantAgent(engine, rng=rng)
    result = agent.run_turn("The player studies the path.")
    assert result.spoke is False
    assert result.text == ""


def test_agency_speak_branch():
    state = GameState()
    state.assistant_mind.help_probability = 1.0
    engine = GameEngine(state)

    def llm(_messages):
        return SPEAK_RESPONSE

    agent = AssistantAgent(engine, llm_fn=llm, rng=random.Random(0))
    result = agent.run_turn("The player studies the path.")
    assert result.spoke is True
    assert "smoke" in result.text.lower()
    assert result.voice_style == "whisper"
    assert result.form == "cat"


def test_should_assistant_speak_probability():
    rng = random.Random(42)
    assert should_assistant_speak(1.0, rng) is True
    rng2 = random.Random(42)
    assert should_assistant_speak(0.0, rng2) is False


def test_parse_assistant_plain_text():
    parsed = parse_assistant_response("Only the wind answers.")
    assert parsed["text"] == "Only the wind answers."
    assert parsed["tool_calls"] == []


def test_grant_hint_skill():
    state = GameState()
    state.assistant_mind.trust_level = 35.0
    engine = GameEngine(state)
    set_active_engine(engine)
    raw = grant_hint(tier=2)
    data = json.loads(raw)
    assert data["tier"] == 2
    assert data["hint"]


def test_reveal_lore_gated():
    state = GameState()
    state.assistant_mind.trust_level = 10.0
    engine = GameEngine(state)
    set_active_engine(engine)
    blocked = json.loads(reveal_lore(topic="clockwork_dark"))
    assert blocked["success"] is False

    state.assistant_mind.trust_level = 70.0
    allowed = json.loads(reveal_lore(topic="clockwork_dark"))
    assert allowed["success"] is True
    assert "Clockwork Dark" in allowed["lore"]


def test_change_form_reflection_locked():
    state = GameState(awareness=10.0)
    engine = GameEngine(state)
    set_active_engine(engine)
    result = json.loads(change_form(form="reflection"))
    assert result["success"] is False
    assert state.assistant_mind.current_form == "cat"

    state.awareness = 45.0
    result = json.loads(change_form(form="reflection"))
    assert result["success"] is True
    assert state.assistant_mind.current_form == "reflection"


def test_change_form_validates():
    state = GameState()
    engine = GameEngine(state)
    set_active_engine(engine)
    result = json.loads(change_form(form="dragon"))
    assert result["success"] is False
    assert set(result["valid_forms"]) == set(ASSISTANT_FORMS)


def test_tool_calls_via_agent():
    state = GameState()
    state.assistant_mind.help_probability = 1.0
    engine = GameEngine(state)

    def llm(_messages):
        return HINT_RESPONSE

    agent = AssistantAgent(engine, llm_fn=llm, rng=random.Random(1))
    result = agent.run_turn("Player asks for guidance.")
    assert result.spoke is True
    assert any(r["skill"] == "grant_hint" for r in result.tool_receipts)


def test_stt_stub_empty_audio():
    state = GameState()
    engine = GameEngine(state)
    agent = AssistantAgent(engine, stt_client=STTClient())
    result = agent.process_voice_input(b"")
    assert result.spoke is False
    assert result.transcript == ""


def test_stt_routes_to_assistant(monkeypatch):
    state = GameState()
    state.assistant_mind.help_probability = 1.0
    engine = GameEngine(state)

    class FakeSTT:
        def transcribe(self, audio_bytes, **kwargs):
            return {"success": True, "transcript": "What is wrong with the wheat?", "source": "stub"}

    calls: list[str] = []

    def llm(messages):
        calls.append(messages[-1]["content"])
        return "The wheat remembers being cut."

    agent = AssistantAgent(engine, llm_fn=llm, stt_client=FakeSTT(), rng=random.Random(1))
    result = agent.process_voice_input(b"\x00\x01", scene_context="Forest clearing at dawn.")
    assert result.transcript == "What is wrong with the wheat?"
    assert result.spoke is True
    assert "wheat" in result.text.lower()
    assert "Player (voice):" in calls[0]