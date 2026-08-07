"""
State transaction tests.

The retry loop executed tool calls before the evaluator ran and never undid
them: a rejected draft still spent stamina and moved the player. These pin the
rollback that fixes it.
"""

from __future__ import annotations

import pytest

import engine.skills.builtin.mechanics  # noqa: F401 — register skills
from engine.game.clock import advance_time
from engine.game.engine import GameEngine, active_engine
from engine.game.procgen import new_game_state
from engine.game.state import InventoryItem
from engine.game.transaction import StateTransaction, transaction


def _engine(seed: int = 7) -> GameEngine:
    return GameEngine(new_game_state(seed=seed))


def test_rollback_undoes_travel():
    """The exact scenario: a rejected draft must not leave the player moved."""
    eng = _engine()
    before_stamina = eng.state.stats.stamina
    tx = StateTransaction(eng.state)

    eng.move_to("edgewood_square")
    assert eng.state.location_id == "edgewood_square"
    assert eng.state.stats.stamina < before_stamina

    tx.rollback()

    assert eng.state.location_id == "forest_clearing"
    assert eng.state.stats.stamina == before_stamina


def test_rollback_undoes_the_clock():
    eng = _engine()
    tx = StateTransaction(eng.state)
    advance_time(eng.state, 30.0)
    assert eng.state.world_day == 2
    tx.rollback()
    assert eng.state.world_day == 1
    assert eng.state.world_hour == 8


def test_rollback_undoes_evil_progress():
    eng = _engine()
    tx = StateTransaction(eng.state)
    advance_time(eng.state, 240.0)
    assert eng.state.evil_progress > 0
    tx.rollback()
    assert eng.state.evil_progress == 0.0


def test_rollback_undoes_inventory_and_gold():
    eng = _engine()
    eng.state.inventory.append(InventoryItem(id="loaf", name="Loaf", qty=1))
    # Characters now start with archetype kit, so assert on the delta rather
    # than on an exact list.
    before_ids = [i.id for i in eng.state.inventory]
    before_gold = eng.state.stats.gold
    tx = StateTransaction(eng.state)

    eng.add_item("charm", "Sympathy Charm", qty=2)
    eng.state.stats.gold -= 5

    tx.rollback()

    assert [i.id for i in eng.state.inventory] == before_ids
    assert "charm" not in [i.id for i in eng.state.inventory]
    assert eng.state.stats.gold == before_gold


def test_rollback_preserves_object_identity():
    """
    Engine and session references must stay valid after a rollback.

    Rebinding a fresh GameState would leave GameEngine.state pointing at the
    pre-rollback object and silently split the world in two.
    """
    eng = _engine()
    original = eng.state
    tx = StateTransaction(eng.state)
    eng.move_to("edgewood_square")
    tx.rollback()
    assert eng.state is original


def test_savepoint_rolls_back_only_its_own_block():
    eng = _engine()
    tx = StateTransaction(eng.state)

    eng.add_item("loaf", "Loaf", qty=1)

    with pytest.raises(RuntimeError):
        with tx.savepoint():
            eng.add_item("charm", "Charm", qty=1)
            raise RuntimeError("tool failed")

    ids = [i.id for i in eng.state.inventory]
    assert "loaf" in ids, "earlier work in the turn must survive"
    assert "charm" not in ids, "the failed tool's effect must be gone"


def test_context_manager_rolls_back_on_exception():
    eng = _engine()
    with pytest.raises(ValueError):
        with transaction(eng.state):
            eng.move_to("edgewood_square")
            raise ValueError("evaluator rejected")
    assert eng.state.location_id == "forest_clearing"


def test_committed_transaction_keeps_changes():
    eng = _engine()
    with transaction(eng.state) as tx:
        eng.move_to("edgewood_square")
        tx.commit()
    assert eng.state.location_id == "edgewood_square"


def test_rollback_restores_hidden_stats_and_minds():
    eng = _engine()
    eng.state.assistant_mind.trust_level = 20.0
    tx = StateTransaction(eng.state)

    eng.state.awareness = 80.0
    eng.state.assistant_mind.trust_level = 95.0
    eng.state.storyteller_mind.patience = 1.0

    tx.rollback()

    assert eng.state.awareness == 0.0
    assert eng.state.assistant_mind.trust_level == 20.0
    assert eng.state.storyteller_mind.patience == 80.0


def test_transaction_exercises_the_save_serializer():
    """
    A useful side effect worth keeping.

    Every turn now round-trips to_save_dict/from_dict, so a serialization
    regression surfaces in normal play rather than the first time someone
    tries to load a save.
    """
    eng = _engine()
    eng.state.rng_counters["dice"] = 3
    tx = StateTransaction(eng.state)
    with active_engine(eng):
        eng.roll(sides=20, reason="x")
    assert eng.state.rng_counters["dice"] == 4
    tx.rollback()
    assert eng.state.rng_counters["dice"] == 3
