"""
Effect dispatcher tests.

Two properties matter and are asserted for every effect type: the mutation is
clamped to a legal value, and it survives ``GameState.to_save_dict()`` ->
``from_dict()``. An effect that cannot be saved is a bug that only shows up
after the player reloads, which is the worst time to find it.
"""

from __future__ import annotations

import pytest

from engine.game import effects
from engine.game.clock import set_clock
from engine.game.state import GameState, InventoryItem


def roundtrip(state: GameState) -> GameState:
    """Save and reload a state, the way persistence does."""
    return GameState.from_dict(state.to_save_dict())


# -- stats and pools -----------------------------------------------------


def test_stat_effect_moves_and_reports():
    state = GameState()
    state.stats.stamina = 50
    out = effects.apply_effect(state, {"type": "stat", "stat": "stamina", "delta": -20})
    assert state.stats.stamina == 30
    assert out["ok"] is True
    assert out["before"] == 50 and out["after"] == 30 and out["applied"] == -20


def test_stat_clamps_to_max_where_one_exists():
    state = GameState()
    state.stats.stamina = 95
    effects.apply_effect(state, {"type": "stamina", "delta": 50})
    assert state.stats.stamina == state.stats.max_stamina == 100


def test_stat_clamps_at_zero():
    state = GameState()
    state.stats.hp = 3
    effects.apply_effect(state, {"type": "hp", "delta": -99})
    assert state.stats.hp == 0


def test_attribute_without_max_is_uncapped_upward():
    state = GameState()
    effects.apply_effect(state, {"type": "stat", "stat": "grit", "delta": 5})
    assert state.stats.grit == 15
    assert roundtrip(state).stats.grit == 15


def test_gold_effect_roundtrips():
    state = GameState()
    state.stats.gold = 5
    effects.apply_effect(state, {"type": "gold", "delta": 7})
    assert state.stats.gold == 12
    assert roundtrip(state).stats.gold == 12


def test_focus_and_craft_aliases():
    state = GameState()
    effects.apply_effects(
        state, [{"type": "focus", "delta": -3}, {"type": "craft", "delta": 2}]
    )
    assert state.stats.focus == 7
    assert state.stats.craft == 12


def test_unknown_stat_name_is_ignored_not_raised():
    state = GameState()
    out = effects.apply_effect(state, {"type": "stat", "stat": "luck", "delta": 5})
    assert out["ok"] is False


# -- hunger, awareness, reputation ---------------------------------------


@pytest.mark.parametrize("delta,expected", [(30.0, 30.0), (-30.0, 0.0), (500.0, 100.0)])
def test_hunger_clamped_to_band(delta, expected):
    state = GameState()
    effects.apply_effect(state, {"type": "hunger", "delta": delta})
    assert state.hunger == expected
    assert roundtrip(state).hunger == expected


def test_awareness_clamped_0_100():
    state = GameState()
    effects.apply_effect(state, {"type": "awareness", "delta": 250})
    assert state.awareness == 100.0
    effects.apply_effect(state, {"type": "awareness", "delta": -250})
    assert state.awareness == 0.0


def test_awareness_result_is_flagged_hidden():
    state = GameState()
    out = effects.apply_effect(state, {"type": "awareness", "delta": 5})
    assert out["hidden"] is True


def test_reputation_clamped_and_roundtrips():
    state = GameState()
    effects.apply_effect(state, {"type": "reputation", "faction": "edgewood", "delta": 5})
    assert state.reputations["edgewood"] == 5
    effects.apply_effect(state, {"type": "reputation", "faction": "edgewood", "delta": 500})
    assert state.reputations["edgewood"] == 100
    effects.apply_effect(state, {"type": "reputation", "faction": "edgewood", "delta": -500})
    assert state.reputations["edgewood"] == -100
    assert roundtrip(state).reputations["edgewood"] == -100


def test_reputation_without_faction_is_ignored():
    state = GameState()
    assert effects.apply_effect(state, {"type": "reputation", "delta": 5})["ok"] is False
    assert state.reputations == {}


# -- inventory -----------------------------------------------------------


def test_item_effect_adds_and_roundtrips():
    state = GameState()
    effects.apply_effect(
        state,
        {"type": "item", "item_id": "loaf", "name": "Loaf of bread", "qty": 2, "tags": ["food"]},
    )
    reloaded = roundtrip(state)
    entry = reloaded.inventory[0]
    assert (entry.id, entry.name, entry.qty, entry.tags) == ("loaf", "Loaf of bread", 2, ["food"])


def test_item_effect_stacks_existing():
    state = GameState()
    state.inventory.append(InventoryItem(id="loaf", name="Loaf of bread", qty=1))
    effects.apply_effect(state, {"type": "item", "item_id": "loaf", "qty": 3})
    assert len(state.inventory) == 1
    assert state.inventory[0].qty == 4


def test_remove_item_drops_empty_stacks():
    state = GameState()
    state.inventory.append(InventoryItem(id="loaf", name="Loaf", qty=2))
    effects.apply_effect(state, {"type": "remove_item", "item_id": "loaf", "qty": 2})
    assert state.inventory == []
    assert roundtrip(state).inventory == []


def test_remove_item_you_do_not_have_is_a_no_op_not_a_failure():
    # A complication that spoils rations you never carried costs nothing; it
    # must not abort the rest of the draw.
    state = GameState()
    out = effects.apply_effect(state, {"type": "remove_item", "item_id": "ghost"})
    assert out["ok"] is True and out["removed"] == 0


# -- status --------------------------------------------------------------


def test_wound_effect_roundtrips_with_relative_heal_day():
    state = GameState()
    set_clock(state, day=4, hour=9)
    effects.apply_effect(
        state,
        {
            "type": "wound",
            "text": "Turned ankle",
            "severity": 2,
            "check_penalty": -1,
            "skills": ["stealth", "survival"],
            "heals_on_day": "+3",
        },
    )
    wound = roundtrip(state).wounds[0]
    assert wound.text == "Turned ankle"
    assert wound.severity == 2
    assert wound.check_penalty == -1
    assert wound.skills == ["stealth", "survival"]
    assert wound.heals_on_day == 7


def test_check_penalty_effect_roundtrips():
    state = GameState()
    set_clock(state, day=2, hour=9)
    effects.apply_effect(
        state,
        {"type": "check_penalty", "delta": -2, "days": 2, "skills": ["nerve"], "text": "shaken"},
    )
    eff = roundtrip(state).active_effects[0]
    assert eff.kind == "check_penalty"
    assert eff.delta == -2
    assert eff.skills == ["nerve"]
    # Day 2 and day 3 -- two days, because `days: 2` says two days.
    #
    # This asserted 4, which is what `world_day + days` produced and is three
    # days of penalty (2, 3 and 4): the sweep in engine/game/clock.py keeps an
    # effect while `expires_day >= world_day`, so `expires_day` is the last day
    # STILL IN FORCE. Every duration in the game ran one day long. Durations
    # now convert through `effects.duration_day`; see tests/test_durations.py.
    assert eff.expires_day == 3


def test_timed_effects_expire_through_the_clock():
    from engine.game.clock import advance_time

    state = GameState()
    effects.apply_effect(state, {"type": "check_penalty", "delta": -2, "days": 1})
    assert len(state.active_effects) == 1
    advance_time(state, 48)
    assert state.active_effects == []


def test_flag_effect_roundtrips():
    state = GameState()
    effects.apply_effect(state, {"type": "flag", "flag": "was_watched", "value": True})
    assert roundtrip(state).flags["was_watched"] is True


def test_flag_without_name_is_ignored():
    state = GameState()
    assert effects.apply_effect(state, {"type": "flag", "value": True})["ok"] is False
    assert state.flags == {}


# -- ledger --------------------------------------------------------------


def test_ledger_fact_requires_a_ledger():
    state = GameState()
    out = effects.apply_effect(state, {"type": "ledger_fact", "text": "Saw brass in the wheat."})
    assert out["ok"] is False


def test_ledger_fact_records_when_ledger_present():
    # `engine.agents` first: engine/memory/__init__.py -> context -> agents.prompts
    # -> agents/__init__ -> storyteller -> memory.context is a pre-existing import
    # cycle that only resolves if engine.agents is imported first. Unrelated to
    # effects; noted here so the next reader does not "fix" it by reordering.
    import engine.agents  # noqa: F401
    from engine.memory.ledger import StoryLedger

    state = GameState()
    ledger = StoryLedger()
    out = effects.apply_effect(
        state,
        {"type": "ledger_fact", "text": "Saw brass in the wheat."},
        ledger=ledger,
    )
    assert out["ok"] is True
    assert any("brass" in f.text for f in ledger.facts)


# -- robustness ----------------------------------------------------------


@pytest.mark.parametrize(
    "effect",
    [
        {"type": "teleport", "to": "the moon"},
        {"type": ""},
        {},
        {"no_type_at_all": 1},
    ],
)
def test_unknown_effects_are_logged_and_ignored_never_raised(effect):
    state = GameState()
    before = state.to_save_dict()
    out = effects.apply_effect(state, effect)
    assert out["ok"] is False
    assert state.to_save_dict() == before


def test_non_dict_effect_is_tolerated():
    state = GameState()
    assert effects.apply_effect(state, "have some gold")["ok"] is False  # type: ignore[arg-type]
    assert effects.apply_effects(state, "not a list") == []  # type: ignore[arg-type]


def test_junk_scalars_do_not_raise():
    state = GameState()
    out = effects.apply_effect(state, {"type": "gold", "delta": "lots"})
    assert out["ok"] is True and state.stats.gold == 5  # delta coerced to 0


def test_apply_effects_preserves_order_and_length():
    state = GameState()
    out = effects.apply_effects(
        state,
        [
            {"type": "gold", "delta": 1},
            {"type": "nonsense"},
            {"type": "hunger", "delta": 5},
        ],
    )
    assert len(out) == 3
    assert [o["ok"] for o in out] == [True, False, True]


def test_resolve_day_handles_relative_absolute_and_missing():
    state = GameState()
    set_clock(state, day=5, hour=0)
    assert effects.resolve_day(state, "+3") == 8
    assert effects.resolve_day(state, "-1") == 4
    assert effects.resolve_day(state, 12) == 12
    assert effects.resolve_day(state, None, default_days=2) == 7


def test_every_effect_type_survives_a_full_save_roundtrip():
    """One state carrying every effect type at once, saved and reloaded."""
    state = GameState()
    set_clock(state, day=3, hour=10)
    effects.apply_effects(
        state,
        [
            {"type": "stat", "stat": "grit", "delta": 2},
            {"type": "gold", "delta": 10},
            {"type": "hp", "delta": -5},
            {"type": "stamina", "delta": -25},
            {"type": "focus", "delta": -2},
            {"type": "hunger", "delta": 40},
            {"type": "awareness", "delta": 15},
            {"type": "reputation", "faction": "edgewood", "delta": -4},
            {"type": "item", "item_id": "loaf", "name": "Loaf", "qty": 2, "tags": ["food"]},
            {"type": "item", "item_id": "pin", "name": "Ward pin", "qty": 1},
            {"type": "remove_item", "item_id": "pin", "qty": 1},
            {"type": "wound", "text": "Torn hands", "check_penalty": -2,
             "skills": ["craft"], "heals_on_day": "+2"},
            {"type": "check_penalty", "delta": -1, "days": 1, "text": "brass taste"},
            {"type": "flag", "flag": "was_watched", "value": True},
        ],
    )

    reloaded = roundtrip(state)
    assert reloaded.stats.grit == 12
    assert reloaded.stats.gold == 15
    assert reloaded.stats.hp == 15
    assert reloaded.stats.stamina == 75
    assert reloaded.stats.focus == 8
    assert reloaded.hunger == 40.0
    assert reloaded.awareness == 15.0
    assert reloaded.reputations == {"edgewood": -4}
    assert [(i.id, i.qty) for i in reloaded.inventory] == [("loaf", 2)]
    assert reloaded.wounds[0].heals_on_day == 5
    # `days: 1` is in force TODAY and gone tomorrow. It asserted 4 (day 3 plus
    # one), which kept a one-day penalty for two -- see the note on
    # test_check_penalty_effect_roundtrips and tests/test_durations.py.
    assert reloaded.active_effects[0].expires_day == 3
    assert reloaded.flags == {"was_watched": True}
    assert reloaded.to_save_dict() == state.to_save_dict()
