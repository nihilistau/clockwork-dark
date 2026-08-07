"""
Concurrent session isolation tests.

The active engine used to be a module-level global. With Socket.IO in threading
mode, one session rebound it while another was blocked on a multi-second LLM
call, so skills mutated the wrong player's state. These tests pin the fix.
"""

from __future__ import annotations

import json
import threading

import engine.skills.builtin.mechanics  # noqa: F401 — register skills
from engine.game.engine import GameEngine, active_engine, get_active_engine
from engine.game.procgen import new_game_state
from engine.skills.registry import SKILL_REGISTRY


def _engine(name: str, seed: int) -> GameEngine:
    return GameEngine(new_game_state(player_name=name, seed=seed))


def test_context_manager_restores_previous_binding():
    outer, inner = _engine("Outer", 1), _engine("Inner", 2)
    with active_engine(outer):
        assert get_active_engine() is outer
        with active_engine(inner):
            assert get_active_engine() is inner
        assert get_active_engine() is outer


def test_threads_do_not_share_the_active_engine():
    alpha, beta = _engine("Alpha", 1), _engine("Beta", 2)
    seen: dict[str, str] = {}
    both_bound = threading.Barrier(2, timeout=5)

    def run(label: str, eng: GameEngine) -> None:
        with active_engine(eng):
            # Both threads hold a binding at the same moment; a global would
            # have been overwritten by whichever arrived second.
            both_bound.wait()
            seen[label] = get_active_engine().state.player_name

    threads = [
        threading.Thread(target=run, args=("a", alpha)),
        threading.Thread(target=run, args=("b", beta)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)

    assert seen == {"a": "Alpha", "b": "Beta"}


def test_concurrent_skill_calls_hit_their_own_state():
    """A skill resolving through the context must mutate only its own session."""
    alpha, beta = _engine("Alpha", 1), _engine("Beta", 2)
    both_bound = threading.Barrier(2, timeout=5)
    errors: list[BaseException] = []

    def travel(eng: GameEngine) -> None:
        try:
            with active_engine(eng):
                both_bound.wait()
                SKILL_REGISTRY.invoke("move_to", location_id="edgewood_square")
        except BaseException as exc:  # noqa: BLE001 — surfaced below
            errors.append(exc)

    threads = [threading.Thread(target=travel, args=(e,)) for e in (alpha, beta)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)

    assert not errors
    assert alpha.state.location_id == "edgewood_square"
    assert beta.state.location_id == "edgewood_square"
    # Each paid its own travel cost exactly once.
    assert alpha.state.stats.stamina == beta.state.stats.stamina < 100


def test_sessions_keep_independent_rng_streams():
    alpha, beta = _engine("Alpha", 1), _engine("Beta", 2)
    with active_engine(alpha):
        for _ in range(5):
            alpha.roll(sides=20, reason="test")
    assert beta.state.rng_counters == {}
    assert alpha.state.rng_counters.get("dice") == 5


def test_dice_are_reproducible_from_seed():
    a, b = _engine("A", 4242), _engine("B", 4242)
    rolls_a = [a.roll(sides=20, reason="r").total for _ in range(6)]
    rolls_b = [b.roll(sides=20, reason="r").total for _ in range(6)]
    assert rolls_a == rolls_b
    assert len(set(rolls_a)) > 1, "a frozen generator would repeat one value"


def test_unknown_tool_args_do_not_escape_as_exceptions():
    """
    Malformed LLM arguments must return a receipt, not raise.

    The ** unpack sat outside the registry's guard, so a model emitting a list
    instead of an object raised TypeError straight out of the turn handler.
    """
    from engine.agents.tool_dispatcher import execute_tool_calls

    eng = _engine("A", 1)
    with active_engine(eng):
        receipts = execute_tool_calls(
            [
                {"name": "move_to", "args": ["edgewood_square"]},
                {"name": "roll_dice", "args": "twenty"},
                {"name": "roll_dice", "args": {"sides": 20}},
            ],
            eng,
        )

    assert receipts[0]["success"] is False
    assert receipts[1]["success"] is False
    assert receipts[2]["success"] is True


def test_non_list_tool_calls_are_tolerated():
    from engine.agents.tool_dispatcher import execute_tool_calls

    eng = _engine("A", 1)
    with active_engine(eng):
        receipts = execute_tool_calls({"name": "roll_dice", "args": {"sides": 6}}, eng)
    assert len(receipts) == 1
    assert json.loads(json.dumps(receipts))  # stays JSON-serializable
