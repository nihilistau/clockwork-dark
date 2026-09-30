"""
The MCP tool loop stays LM Studio-only (v0.19.0 T6, spec §7).

``llm.mcp.enabled`` turns on Phase A, which reaches the engine's skills
through LM Studio's native ``integrations`` -- the only route that carries an
MCP server, and the provider row's ``mcp_integrations`` cell. On any other
provider the switch is refused, not half-honoured: ``mechanics_enabled()``
is False, one ERROR per process says why, the skills server never starts,
and the turn is exactly the MCP-off turn. There is no engine-side tool loop
to fall back to (a docs/GOVERNANCE.md NOT WIRED row).
"""

from __future__ import annotations

import logging
from typing import Any

import pytest

from engine.agents import mechanics
from tests.test_two_phase_turn import (
    test_a_disabled_phase_a_leaves_the_prompt_byte_identical as _mcp_off_is_byte_identical,
)


@pytest.fixture(autouse=True)
def _fresh_refusal(monkeypatch: pytest.MonkeyPatch) -> None:
    """The once-per-process ERROR, made once-per-test."""
    monkeypatch.setattr(mechanics, "_mcp_refusal_logged", False)


@pytest.mark.parametrize("provider", ["vllm", "llamacpp", "ollama", "openai_compat"])
def test_mcp_enabled_off_lm_studio_is_refused_with_one_error(
    llm_server: Any, provider: str, caplog: Any
) -> None:
    llm_server(provider, mcp={"enabled": True})
    with caplog.at_level(logging.ERROR, logger="engine.agents.mechanics"):
        assert [mechanics.mechanics_enabled() for _ in range(3)] == [False] * 3
    errors = [r for r in caplog.records if r.name == "engine.agents.mechanics"]
    assert len(errors) == 1
    assert "llm.mcp.enabled is set" in errors[0].getMessage()
    assert f"provider={provider}" in errors[0].getMessage()


def test_lm_studio_keeps_phase_a(llm_server: Any, caplog: Any) -> None:
    llm_server("lmstudio", mcp={"enabled": True})
    with caplog.at_level(logging.ERROR):
        assert mechanics.mechanics_enabled() is True
    assert not caplog.records


def test_off_is_off_everywhere_and_says_nothing(llm_server: Any, caplog: Any) -> None:
    llm_server("vllm")
    with caplog.at_level(logging.ERROR):
        assert mechanics.mechanics_enabled() is False
    assert not caplog.records


@pytest.fixture
def no_skills_server(monkeypatch: pytest.MonkeyPatch) -> Any:
    """
    ``SkillsServer`` replaced by a stand-in that records being built and
    refuses to be. A REAL one, reached through a broken gate, listens on a
    socket and registers itself in the owner's own LM Studio ``mcp.json`` --
    so these tests must never get that far even when the gate they guard is
    broken (measured: this file's canary once did, before this stub). The
    record is asserted empty at teardown, because Phase A swallows the
    stand-in's refusal on purpose.
    """
    from engine.mcp import skills_server

    asked: list[Any] = []

    class _NeverBuilt:
        def __init__(self, *a: Any, **k: Any) -> None:
            asked.append((a, k))
            raise AssertionError("a skills server was built off LM Studio")

    monkeypatch.setattr(skills_server, "SkillsServer", _NeverBuilt)
    monkeypatch.setattr(skills_server, "_server", None)
    yield asked
    assert asked == [], "a skills server was built off LM Studio"


def test_the_skills_server_never_starts_off_lm_studio(
    llm_server: Any, no_skills_server: list[Any]
) -> None:
    from engine.mcp import skills_server

    llm_server("vllm", mcp={"enabled": True})
    assert skills_server.get_skills_server(lambda _sid: None) is None


def test_phase_a_returns_nothing_off_lm_studio(
    llm_server: Any, monkeypatch: pytest.MonkeyPatch, no_skills_server: list[Any]
) -> None:
    from engine.game.engine import GameEngine
    from engine.game.procgen import new_game_state
    from engine.mcp import skills_server

    llm_server("vllm", mcp={"enabled": True})
    monkeypatch.setattr(
        skills_server, "get_skills_server", lambda *a, **k: no_skills_server.append(a)
    )
    engine = GameEngine(new_game_state(player_name="Tester", seed=42))
    assert mechanics.run_mechanics_phase(engine, "look around") == []
    assert no_skills_server == [], "Phase A asked for a skills server off LM Studio"


def test_the_turn_is_byte_identical_to_mcp_off(
    llm_server: Any, monkeypatch: pytest.MonkeyPatch, no_skills_server: list[Any]
) -> None:
    """``tests/test_two_phase_turn.py``'s own assertion, under an MCP-enabled vLLM."""
    llm_server("vllm", mcp={"enabled": True})
    assert mechanics.mechanics_enabled() is False
    _mcp_off_is_byte_identical(monkeypatch)
