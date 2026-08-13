"""
Agent identity is story-declared.

``clockwork_storyteller`` and ``clockwork_assistant`` were engine literals for
the project's whole life -- the same bug paths.* had, in agent form: one
story's cast written into the runtime, inherited by every story that never
asked. The ids live in the flagship's own ``agents.yaml`` now, and the engine
resolves an agent's id through the active roster
(``engine/agents/roster.py::agent_id_for_role``), keeping the old literals
ONLY as the fallback for a story that declares no roster at all.

What this suite holds:

  * the flagship still answers to its canon ids -- via its own declaration,
    not via engine code (CLAUDE.md pins the ids; this file pins where they
    come FROM)
  * a story with its own roster gets its own names, and a role it declines to
    declare falls back to the historical pair rather than to silence
  * no active story at all resolves the legacy shim, which is what an old
    save loaded outside any story activation would see

Nothing here talks to a model; identity is resolved before any inference.

Version: v0.1.0 [2026-08-13]
"""

from __future__ import annotations

from typing import Any, Iterator

import pytest

import engine.state.active as active_module
from engine.agents.assistant import AssistantAgent
from engine.agents.roster import (
    ROLE_COMPANION,
    ROLE_WORLD,
    agent_id_for_role,
    parse_roster,
)
from engine.agents.storyteller import StorytellerAgent
from engine.game.engine import GameEngine
from engine.game.state import GameState


@pytest.fixture
def agents() -> Iterator[tuple[StorytellerAgent, AssistantAgent]]:
    engine = GameEngine(GameState(rng_seed=7))
    yield (
        StorytellerAgent(engine, llm_fn=lambda messages: "{}"),
        AssistantAgent(engine, llm_fn=lambda messages: ""),
    )


@pytest.fixture
def story() -> Iterator[Any]:
    """Activate a shipped story and guarantee deactivation (cache reset included)."""
    from engine.games.registry import activate, deactivate

    try:
        yield activate
    finally:
        deactivate()


def test_the_flagship_answers_to_its_canon_ids_by_declaration(
    story: Any, agents: tuple[StorytellerAgent, AssistantAgent]
) -> None:
    """
    The value is the one CLAUDE.md pins; the SOURCE is the story's roster.

    Asserting the roster is non-empty is what distinguishes this from the
    legacy shim returning the same strings -- if the flagship's agents.yaml
    went missing, the ids would still come back but this test would fail on
    the roster, which is exactly the regression it exists to catch.
    """
    storyteller, assistant = agents
    story("clockwork-dark")
    roster = active_module.active_roster()
    assert set(roster.agents) == {"clockwork_storyteller", "clockwork_assistant"}
    assert storyteller.AGENT_ID == "clockwork_storyteller"
    assert assistant.AGENT_ID == "clockwork_assistant"


def test_a_story_with_a_roster_names_its_own_narrator(
    story: Any, agents: tuple[StorytellerAgent, AssistantAgent]
) -> None:
    """
    The Wicked Garden's world agent is `gm`, and that is who its narrator is.

    Its cast declares no companion -- Sophia is a `character`, a different
    thing -- so the companion id falls back to the historical canon name
    rather than borrowing hers. A role a story declines to declare gets the
    engine's built-in identity, not an improvised one.
    """
    storyteller, assistant = agents
    story("wicked-garden")
    assert storyteller.AGENT_ID == "gm"
    assert assistant.AGENT_ID == "clockwork_assistant"


def test_a_synthetic_roster_reaches_both_agents(
    monkeypatch: pytest.MonkeyPatch,
    agents: tuple[StorytellerAgent, AssistantAgent],
) -> None:
    """A story that declares both roles renames both built-in agents."""
    roster = parse_roster(
        {
            "agents": {
                "chronicler": {"role": "world"},
                "raven": {"role": "companion", "pipeline": False},
            }
        },
        slug="synthetic",
    )
    monkeypatch.setattr(active_module, "_roster", roster)
    storyteller, assistant = agents
    assert storyteller.AGENT_ID == "chronicler"
    assert assistant.AGENT_ID == "raven"


def test_no_story_at_all_resolves_the_legacy_shim(
    agents: tuple[StorytellerAgent, AssistantAgent],
) -> None:
    """
    Outside any activation the historical pair answers, exactly as before the
    roster existed. This is the path an old save relies on: nothing in a save
    keys on these ids, but every name shown around one should be the name the
    player has always seen.
    """
    from engine.games.registry import deactivate

    deactivate()
    storyteller, assistant = agents
    assert storyteller.AGENT_ID == StorytellerAgent.LEGACY_AGENT_ID
    assert assistant.AGENT_ID == AssistantAgent.LEGACY_AGENT_ID
    assert agent_id_for_role(ROLE_WORLD, "fallback") == "fallback"
    assert agent_id_for_role(ROLE_COMPANION, "fallback") == "fallback"
