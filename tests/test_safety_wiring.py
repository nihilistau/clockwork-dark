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
        "engine.scenes.default_state.get_save_store", lambda: store
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
    twenty-one hardcoded keys in the first place. The same holds for the
    narration review's keys: inert means invisible at every surface.
    """
    _, payload = _turn()

    assert "safety" not in payload
    assert "safety_narration" not in payload
    assert "fade_card" not in payload


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


# -- the narration surface: the last line ------------------------------------


def _policy(monkeypatch, *, hard=(), soft=(), substitutes=None):
    """Install a session policy with the given limits on every lookup path."""
    from engine.safety.boundaries import BoundarySheet, Limit
    from engine.safety.policy import SafetyPolicy
    from engine.safety.tiers import IntensityTier

    substitutes = substitutes or {}
    policy = SafetyPolicy(
        sheet=BoundarySheet(
            hard_nos=tuple(Limit(topic=t, nouns=(t,)) for t in hard),
            soft_nos=tuple(
                Limit(topic=t, nouns=(t,), substitute=substitutes.get(t, ""))
                for t in soft
            ),
        ),
        intensity=IntensityTier.parse("suggestive"),
    )
    monkeypatch.setattr("engine.safety.policy_for", lambda _sid="": policy)
    monkeypatch.setattr("engine.safety.gate.policy_for", lambda _sid="": policy)
    return policy


def _narrating(text):
    def llm(_messages):
        return json.dumps(
            {
                "narration": text,
                "choices": [{"id": "a", "text": "Wait"}, {"id": "b", "text": "Go"}],
                "tool_calls": [],
            }
        )

    return llm


def _turn_with(llm, action="The player chooses: Wait"):
    session = SessionStore().create(seed=42, llm_fn=llm)
    return session, run_turn(session, action)


def test_a_hard_no_in_the_prose_is_redirected_not_shown(monkeypatch):
    """
    The model, not the player, crossed the line. The prose never ships; the
    player gets the in-fiction interruption and the payload names the verdict.
    """
    _policy(monkeypatch, hard=("drowning",))

    _, payload = _turn_with(
        _narrating("She holds him under until the drowning is done, and the mill wheel turns.")
    )

    assert "drowning" not in payload["narration"].lower()
    assert payload["narration"], "a redirect must still say something"
    assert payload["safety_narration"]["disposition"] == "redirect"
    assert payload["choices"], "a redirected turn must not soft-lock"


def test_a_soft_no_with_no_rename_fades_and_ships_the_card(monkeypatch):
    from engine.agents.storyteller import FADE_FALLBACK_LINE

    _policy(monkeypatch, soft=("gallows",))

    _, payload = _turn_with(
        _narrating("The gallows creak all night over the square.")
    )

    assert "gallows" not in payload["narration"].lower()
    assert payload["narration"] == FADE_FALLBACK_LINE
    assert payload["safety_narration"]["disposition"] == "fade"
    assert payload["safety_narration"]["outcomes_apply"] is True
    assert payload["fade_card"]["heading"], "a fade with no card is a blank scene"


def test_a_soft_no_with_a_rename_substitutes_in_place(monkeypatch):
    _policy(monkeypatch, soft=("collar",), substitutes={"collar": "throat-garland"})

    _, payload = _turn_with(
        _narrating("She fastens the collar and says nothing at all.")
    )

    assert "collar" not in payload["narration"].lower()
    assert "throat-garland" in payload["narration"]
    assert payload["safety_narration"]["disposition"] == "substitute"


def test_clean_prose_under_an_active_policy_is_untouched(monkeypatch):
    _policy(monkeypatch, hard=("drowning",))

    _, payload = _turn_with(_narrating(NARRATION))

    assert payload["narration"].startswith("The oven ticks")
    assert "safety_narration" not in payload
    assert "fade_card" not in payload


def test_a_redirected_turn_does_not_land_its_effects(monkeypatch):
    """
    REDIRECT is the one disposition whose outcomes do not apply: the fiction
    interrupted, so the thing did not happen. The draft's tool effects roll
    back with the draft.
    """
    _policy(monkeypatch, hard=("drowning",))
    from engine.agents.storyteller import StorytellerAgent
    from engine.game.engine import GameEngine
    from engine.game.procgen import new_game_state

    state = new_game_state(seed=42)
    state.stats.stamina = 10

    def llm(_messages):
        return json.dumps(
            {
                "narration": "The drowning is quick, and the water closes over it.",
                "choices": [{"id": "a", "text": "Wait"}],
                "tool_calls": [{"name": "rest", "args": {"kind": "rest_short"}}],
            }
        )

    result = StorytellerAgent(GameEngine(state), llm_fn=llm).run_turn("rest")

    assert result.safety["disposition"] == "redirect"
    assert state.stats.stamina == 10, "a redirected draft kept its effects"
    assert result.tool_receipts == []


def test_a_faded_turn_keeps_its_effects(monkeypatch):
    """FADE is a change of camera, not of world (docs/SAFETY.md)."""
    _policy(monkeypatch, soft=("gallows",))
    from engine.agents.storyteller import StorytellerAgent
    from engine.game.engine import GameEngine
    from engine.game.procgen import new_game_state

    state = new_game_state(seed=42)
    state.stats.stamina = 10

    def llm(_messages):
        return json.dumps(
            {
                "narration": "The gallows creak over the square all night.",
                "choices": [{"id": "a", "text": "Wait"}],
                "tool_calls": [{"name": "rest", "args": {"kind": "rest_short"}}],
            }
        )

    result = StorytellerAgent(GameEngine(state), llm_fn=llm).run_turn("rest")

    assert result.safety["disposition"] == "fade"
    assert state.stats.stamina > 10, "a fade must keep its mechanical outcomes"
    assert result.tool_receipts, "a fade must not erase the receipts"


def test_the_redirect_stream_constant_lives_with_the_others():
    """
    docs/SAFETY.md carried the promotion as owed tidiness. One definition, in
    the module that owns stream names, imported back by the safety package.
    """
    from engine.game import rng
    from engine.safety import redirect

    assert rng.SAFETY_REDIRECT == "safety.redirect"
    assert redirect.SAFETY_REDIRECT is rng.SAFETY_REDIRECT


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
