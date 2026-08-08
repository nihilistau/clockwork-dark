"""
Extended state must survive the machinery.

These are the three hazards found when auditing the engine for a second story
whose state is nothing like the flagship's. Each one silently DISCARDED any
field declared beyond the base ``GameState``, and each failed in a way that
looks like a content bug rather than an engine bug:

  1. ``transaction.restore_in_place`` iterated ``fields(GameState)`` literally,
     so an extended field was reverted on every evaluator retry and every tool
     savepoint -- both of which run on ordinary turns.
  2. ``StateTransaction.rollback`` rehydrated through ``GameState.from_dict``,
     so even a fixed restore loop would have been handed an object with nothing
     to copy.
  3. ``GameState.from_dict`` named its six nested dataclasses one by one, so a
     seventh came back from a save as a raw dict and failed later, elsewhere,
     as an AttributeError.

Nothing in the suite exercised a subclass, so all three were invisible. This
file is the guard: it is deliberately written against a *hypothetical* story
schema rather than a real one, because the point is that the engine must not
know which fields a story added.

Version: v0.1.0 [2026-08-08]
"""

from __future__ import annotations

from dataclasses import dataclass, field

from engine.game.state import GameState
from engine.game.transaction import StateTransaction, restore_in_place


@dataclass
class Meter:
    """A nested type the base engine has never heard of."""

    value: int = 0
    ceiling: int = 100


@dataclass
class ExtendedState(GameState):
    """A story that declares its own scalar, list and nested-dataclass fields."""

    favor: int = 15
    threads: list[str] = field(default_factory=list)
    autonomy: Meter = field(default_factory=lambda: Meter(value=70))
    meters: list[Meter] = field(default_factory=list)


# -- hazard 1 + 2: rollback ---------------------------------------------------


def test_rollback_preserves_extended_scalar_fields():
    state = ExtendedState(favor=40)
    tx = StateTransaction(state)

    state.favor = 99
    tx.rollback()

    assert state.favor == 40, "an extended scalar was reverted to the base default"


def test_rollback_keeps_the_subclass_identity():
    state = ExtendedState()
    tx = StateTransaction(state)
    tx.rollback()

    assert isinstance(state, ExtendedState)
    assert state.autonomy.value == 70


def test_rollback_restores_extended_nested_and_list_fields():
    state = ExtendedState()
    state.autonomy = Meter(value=55)
    state.threads = ["obligation"]
    tx = StateTransaction(state)

    state.autonomy = Meter(value=5)
    state.threads.append("debt")
    state.threads = list(state.threads)
    tx.rollback()

    assert state.autonomy.value == 55
    assert state.threads == ["obligation"]


def test_savepoint_rollback_does_not_eat_extended_state():
    """
    The savepoint path, not just the turn path.

    A tool call that raises rolls back its own savepoint. That is the hotter of
    the two paths -- it runs per tool, several times a turn.
    """
    state = ExtendedState(favor=30)
    tx = StateTransaction(state)

    try:
        with tx.savepoint():
            state.favor = 1
            raise RuntimeError("tool blew up")
    except RuntimeError:
        pass

    assert state.favor == 30


def test_restore_in_place_walks_the_real_class():
    source = ExtendedState(favor=7)
    target = ExtendedState(favor=88)

    restore_in_place(target, source)

    assert target.favor == 7


# -- hazard 3: save round trip ------------------------------------------------


def test_extended_fields_round_trip_through_a_save():
    state = ExtendedState(favor=42, threads=["bargain"])
    state.autonomy = Meter(value=33, ceiling=80)
    state.meters = [Meter(value=1), Meter(value=2)]

    loaded = ExtendedState.from_dict(state.to_save_dict())

    assert loaded.favor == 42
    assert loaded.threads == ["bargain"]
    assert loaded.autonomy.value == 33
    assert loaded.autonomy.ceiling == 80


def test_nested_dataclasses_load_as_objects_not_dicts():
    """
    The specific silent failure: a raw dict where an object belongs.

    It does not raise on load. It raises much later, somewhere unrelated, as an
    AttributeError on a dict -- which is why this asserts the type rather than
    the value.
    """
    state = ExtendedState()
    state.autonomy = Meter(value=12)
    state.meters = [Meter(value=3)]

    loaded = ExtendedState.from_dict(state.to_save_dict())

    assert isinstance(loaded.autonomy, Meter)
    assert loaded.meters and isinstance(loaded.meters[0], Meter)


def test_base_state_still_round_trips_its_own_nested_types():
    """The derived coercion must not have lost what the hardcoded list did."""
    state = GameState()
    state.stats.gold = 77
    state.wounds.append(
        __import__("engine.game.state", fromlist=["Wound"]).Wound(id="w1", text="cut")
    )

    loaded = GameState.from_dict(state.to_save_dict())

    assert loaded.stats.gold == 77
    assert loaded.wounds and loaded.wounds[0].id == "w1"
    assert not isinstance(loaded.stats, dict)


def test_a_null_nested_field_falls_back_to_its_default():
    """
    Old saves carrying an explicit null must not load `stats=None`.

    The previous code spelled this `data.get("stats") or {}`; the derived
    version has to reproduce it or a save written before a field existed loads
    an object that fails on first attribute access.
    """
    raw = GameState().to_save_dict()
    raw["stats"] = None
    raw["procgen"] = None

    loaded = GameState.from_dict(raw)

    assert loaded.stats.hp > 0
    assert not isinstance(loaded.procgen, dict)
