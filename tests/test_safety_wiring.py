"""
The safety layer, wired into a real turn.

Two claims, and both have to hold or the layer is worse than useless:

  * with nothing configured it is INVISIBLE -- the two shipped stories take
    exactly the turn they took before, spend no prompt tokens on it and get no
    new payload keys
  * with something configured it actually BITES on the live path, not only in
    a unit test of the gate

The second is the one that matters. A safety layer that passes its own tests
and is never called is the "documented but not wired" failure with the worst
possible subject.

Version: v0.1.0 [2026-08-08]
"""

from __future__ import annotations

import json

import pytest

from content.scenes.clockwork.clockwork_state import SessionStore, run_turn
from engine.persistence import reset_save_store
from engine.persistence.saves import SaveStore

NARRATION = (
    "The oven ticks as it heats. Maris does not look up from the dough, and the "
    "low room fills with the smell of it while she decides whether to answer."
)


def _llm(_messages):
    return json.dumps(
        {
            "narration": NARRATION,
            "choices": [{"id": "a", "text": "Wait"}, {"id": "b", "text": "Ask again"}],
            "tool_calls": [],
        }
    )


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    reset_save_store()
    store = SaveStore(root=tmp_path / "saves")
    monkeypatch.setattr(
        "content.scenes.clockwork.clockwork_state.get_save_store", lambda: store
    )
    from engine.safety import reset_policies

    reset_policies()
    yield
    reset_policies()
    reset_save_store()


def _turn(action="The player chooses: Ask about the smoke"):
    session = SessionStore().create(seed=42, llm_fn=_llm)
    return session, run_turn(session, action)


# -- invisible when nothing is configured -------------------------------------


def test_a_shipped_story_gets_no_safety_key_at_all():
    """
    Not "an empty safety block" -- no key. A payload that grew a field for
    every story that does not use it is how the client contract got to
    twenty-one hardcoded keys in the first place.
    """
    _, payload = _turn()

    assert "safety" not in payload


def test_a_shipped_story_still_takes_its_turn():
    _, payload = _turn()

    assert payload["narration"]
    assert payload["choices"]


def test_the_directive_block_is_empty_for_a_shipped_story():
    """
    Zero prompt tokens. R-01 was a budget overflow caused by exactly this kind
    of addition, and a safety block that says "no limits configured" in three
    sentences would be the same bug with a better motive.
    """
    from engine.agents.governance import get_governance
    from engine.game.state import GameState

    text = get_governance().build_directives(GameState(), player_action="look around")

    assert "safety" not in text.lower()


# -- bites when a story configures it -----------------------------------------


def _with_hard_no(monkeypatch, topic="drowning"):
    """Point the session policy at a sheet with one hard limit."""
    from engine.safety.boundaries import BoundarySheet, Limit
    from engine.safety.policy import SafetyPolicy
    from engine.safety.tiers import IntensityTier

    sheet = BoundarySheet(hard_nos=(Limit(topic=topic, nouns=(topic,)),))
    policy = SafetyPolicy(sheet=sheet, intensity=IntensityTier.parse("suggestive"))
    monkeypatch.setattr("engine.safety.policy_for", lambda _sid="": policy)
    monkeypatch.setattr("engine.safety.gate.policy_for", lambda _sid="": policy)
    return policy


def test_a_hard_limit_in_player_input_is_caught_on_the_live_path(monkeypatch):
    _with_hard_no(monkeypatch)

    _, payload = _turn("I hold her under until the drowning stops")

    assert "safety" in payload, "the gate never saw the live turn"
    assert payload["safety"]["disposition"]


def test_a_caught_turn_still_runs(monkeypatch):
    """
    The whole design: the fiction declines, the interface does not.

    A turn that returned no narration would be a refusal wearing a story's
    clothes.
    """
    _with_hard_no(monkeypatch)

    _, payload = _turn("I hold her under until the drowning stops")

    assert payload["narration"], "a limit stopped the turn instead of redirecting it"
    assert payload["choices"]


def test_the_payload_never_echoes_the_players_own_limit_back_at_them(monkeypatch):
    """
    `verdict.reasons` names the limit TOPICS the player asked not to meet.
    Putting those anywhere near prose would print the thing they excluded.
    """
    _with_hard_no(monkeypatch, topic="drowning")

    _, payload = _turn("I hold her under until the drowning stops")

    shipped = json.dumps(payload.get("safety", {}))
    assert "drowning" not in shipped.lower()


def test_ordinary_input_is_untouched_even_with_a_policy_active(monkeypatch):
    _with_hard_no(monkeypatch)

    _, payload = _turn("The player chooses: Ask about the smoke")

    assert "safety" not in payload


# -- it cannot take a turn down -----------------------------------------------


def test_a_broken_gate_costs_the_check_not_the_turn(monkeypatch):
    """
    The layer's own failure must never be the reason a player loses a turn.
    """
    def _explode(*_args, **_kwargs):
        raise RuntimeError("gate is broken")

    monkeypatch.setattr("engine.safety.SafetyGate.for_state", _explode)

    _, payload = _turn()

    assert payload["narration"]
    assert "safety" not in payload
