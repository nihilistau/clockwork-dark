"""
What v0.8.0 deleted stays deleted.

Each of these was live code or live config that nothing in production reached.
They are asserted absent rather than trusted to stay gone, because the pattern
this repo keeps finding is dead code read as unfinished work by the next
session -- which then finishes it (AGENTS.md rule 12, "how it survived").

Version: v0.1.0 [2026-09-23]
"""

from __future__ import annotations

from pathlib import Path

import pytest

from engine.lmstudio.schemas import storyteller_turn_schema

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize("field", ["npc_voices", "mood", "image_tag"])
def test_the_turn_samples_nothing_nobody_reads(field: str) -> None:
    """Output tokens on a local model, every turn, for a field no reader had."""
    properties = storyteller_turn_schema()["schema"]["properties"]
    assert field not in properties


@pytest.mark.parametrize(
    "path",
    [
        "engine/agents/turn_loop.py.bak",
        # The MEDIA governance phase's module: three interceptor classes and a
        # chain, reached by tests alone. The turn calls MediaPipeline directly.
        "engine/media/interceptors.py",
    ],
)
def test_dead_modules_stay_gone(path: str) -> None:
    assert not (ROOT / path).exists()


def test_there_is_no_media_governance_phase() -> None:
    from engine.agents import governance
    from engine.games.manifest import SETTING_ALLOWLIST

    assert not hasattr(governance, "MediaGovernor")
    assert not hasattr(governance, "PHASE_MEDIA")
    assert "governance.media" not in SETTING_ALLOWLIST


def test_the_hunger_line_uses_the_storys_stages() -> None:
    """It was a bare `hunger >= 60` and could never say 'starving'."""
    from engine.agents.prompts import _condition_block
    from engine.game.state import GameState

    state = GameState()
    state.hunger = 99.0
    assert "starving" in _condition_block(state)
    state.hunger = 5.0
    assert "hungry" not in _condition_block(state)
