"""
The effect kinds added when the last direct writes were routed through.

``timed_effect`` exists so the daily-marker trick (shift caps, node wear,
today's haggle, once-per-day item use) has a sanctioned writer, and ``flag``
learned to carry scalars because the assistant's cooldowns store turn NUMBERS
under flag keys. Behaviour tests here; the scanner that keeps the leak class
closed is tests/test_single_writer_guard.py.
"""

from __future__ import annotations

from engine.game import effects as effects_module
from engine.game.state import GameState


# ---------------------------------------------------------------------------
# timed_effect
# ---------------------------------------------------------------------------


def test_timed_effect_appends_a_marker_with_a_receipt() -> None:
    state = GameState()
    receipt = effects_module.apply_effect(
        state,
        {
            "type": "timed_effect",
            "id": "shift:bakery",
            "kind": "shift",
            "text": "worked bakery today",
            "delta": 0,
            "expires_day": state.world_day,
        },
    )
    assert receipt["ok"] is True
    assert receipt["hidden"] is True, "a bookkeeping marker must not reach prose"
    marker = next(e for e in state.active_effects if e.id == "shift:bakery")
    assert marker.kind == "shift"
    assert marker.expires_day == state.world_day


def test_timed_effect_resolves_relative_expiry_like_every_other_kind() -> None:
    state = GameState()
    receipt = effects_module.apply_effect(
        state, {"type": "timed_effect", "id": "m1", "kind": "marker", "expires_day": "+2"}
    )
    assert receipt["expires_day"] == state.world_day + 2


def test_the_daily_markers_go_through_the_writer() -> None:
    """
    The four call sites the routing fixed, driven end to end where cheap:
    economy's shift record is representative of all four (same trick, same
    kind of module), and its marker must now exist because apply_effect made
    it, not because the module reached into the list.
    """
    from engine.game import economy

    state = GameState()
    economy._record_shift(state, "bakery")
    marker = next(
        e for e in state.active_effects if e.id == "shift:bakery"
    )
    assert marker.kind == economy.SHIFT_EFFECT_KIND
    assert int(marker.delta) == 1
    economy._record_shift(state, "bakery")
    assert economy.shifts_worked(state, "bakery") == 2


# ---------------------------------------------------------------------------
# flag scalars
# ---------------------------------------------------------------------------


def test_flag_effect_preserves_scalar_values() -> None:
    state = GameState()
    effects_module.apply_effect(state, {"type": "flag", "flag": "last_turn", "value": 40})
    effects_module.apply_effect(state, {"type": "flag", "flag": "done", "value": True})
    effects_module.apply_effect(state, {"type": "flag", "flag": "off", "value": False})
    assert state.flags["last_turn"] == 40, "a turn number must survive the write"
    assert state.flags["done"] is True
    assert state.flags["off"] is False


def test_flag_effect_collapses_structured_values_to_bool() -> None:
    state = GameState()
    effects_module.apply_effect(
        state, {"type": "flag", "flag": "weird", "value": {"nested": 1}}
    )
    assert state.flags["weird"] is True


def test_assistant_cooldowns_keep_their_turn_numbers() -> None:
    """The write that made scalar flags necessary, driven through its caller."""
    from engine.agents.assistant_director import (
        FLAG_GIFT_TURN,
        FLAG_LAST_TURN,
        INTENT_GIFT,
        AssistantDecision,
        record_appearance,
    )

    state = GameState()
    state.turn_number = 17
    record_appearance(
        state, AssistantDecision(appear=True, intent=INTENT_GIFT)
    )
    assert state.flags[FLAG_LAST_TURN] == 17
    assert state.flags[FLAG_GIFT_TURN] == 17
