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


def test_executing_a_tool_does_not_leak_the_engine_binding():
    """
    ``execute_tool`` scopes the active engine to its own call.

    It used to call ``set_active_engine(engine)`` and discard the reset token,
    so the binding outlived the call. Inside ``run_turn`` -- which wraps its own
    block in ``active_engine(...)`` -- the inner set overwrote that binding and
    the outer ``finally`` then restored the value from BEFORE the with-block,
    not the one it had set. Anything reaching ``execute_tool`` from outside such
    a block, notably the MCP skills server's own thread, pinned that thread to
    one session's engine for good: the cross-session state bug the ContextVar
    was introduced to close, rebuilt one layer down.
    """
    from engine.game import engine as engine_module
    from engine.agents.tool_dispatcher import execute_tool
    from engine.game.engine import GameEngine
    from engine.game.state import GameState

    # Read the ambient binding directly rather than through `get_active_engine`,
    # which raises when there is none. There may or may not be one here: the
    # `engine` fixture in conftest binds one and never resets it, so whether
    # anything is bound depends on what ran before this. The property under test
    # holds either way -- afterwards must equal beforehand.
    before = engine_module._active_engine.get()
    other = GameEngine(GameState(location_id="forest_clearing"))

    receipt = execute_tool("query_evil_state", {}, other)
    assert receipt["skill"] == "query_evil_state"

    after = engine_module._active_engine.get()
    assert after is before, (
        "the tool call left its own engine bound; anything later on this "
        "thread now resolves skills against the wrong session's state"
    )
    assert after is not other


def test_a_tool_call_restores_whatever_binding_surrounded_it():
    """The scope nests: an outer binding survives an inner call."""
    from engine.agents.tool_dispatcher import execute_tool
    from engine.game.engine import GameEngine, active_engine, get_active_engine
    from engine.game.state import GameState

    outer = GameEngine(GameState(location_id="forest_clearing"))
    inner = GameEngine(GameState(location_id="edgewood_square"))

    with active_engine(outer):
        execute_tool("query_evil_state", {}, inner)
        assert get_active_engine() is outer, (
            "a tool call rebound the ambient engine and did not put it back"
        )


def test_deleting_a_session_releases_the_engine_registry():
    """
    ``SessionStore.delete`` is the single teardown door.

    ``mechanics.register_engine`` is called at the top of EVERY mechanics phase
    and ``release_engine`` had no production caller at all, so every
    ``GameEngine`` -- and through it a whole ``GameState``, inventory, roster
    and world-event list -- was retained for the life of the process.
    """
    import pytest

    from engine.agents import mechanics
    from engine.scenes.default_state import SessionStore

    store = SessionStore()
    kept = store.create(seed=1)
    doomed = store.create(seed=2)

    mechanics.register_engine(kept.engine)
    mechanics.register_engine(doomed.engine)

    store.delete(doomed.session_id)

    assert mechanics.resolve_engine(kept.session_id) is kept.engine
    with pytest.raises(KeyError):
        mechanics.resolve_engine(doomed.session_id)


def test_the_idle_sweep_is_off_unless_asked_for():
    """
    Evicting a live run loses a player's game; not sweeping costs memory in a
    long-lived process. Those are not symmetric, so the default is off.
    """
    import time

    from engine.scenes.default_state import SessionStore

    store = SessionStore()
    session = store.create(seed=1)
    # Aged directly rather than by passing a tiny TTL: `sweep_idle` floors the
    # TTL at one minute so a misconfigured zero cannot evict everyone.
    store._seen[session.session_id] = time.monotonic() - 86_400

    assert store.sweep_idle() == []
    assert store.get(session.session_id) is session


def test_the_idle_sweep_never_evicts_a_session_mid_turn(monkeypatch):
    """
    A turn against a local model can take minutes. The lock is the only
    reliable signal that someone is still in there; elapsed time is not.
    """
    import time

    from engine.config import get_config
    from engine.scenes.default_state import SessionStore

    cfg = get_config()
    monkeypatch.setitem(cfg._data, "session", {"idle_sweep_enabled": True})

    store = SessionStore()
    busy = store.create(seed=1)
    idle = store.create(seed=2)
    stale = time.monotonic() - 86_400
    store._seen[busy.session_id] = stale
    store._seen[idle.session_id] = stale

    assert busy.lock.acquire(blocking=False)
    try:
        swept = store.sweep_idle()
    finally:
        busy.lock.release()

    assert busy.session_id not in swept, "a running turn was swept out from under itself"
    assert store.get(busy.session_id) is busy
    assert idle.session_id in swept, "the sweep did not actually run"


def test_a_monkeypatched_manifest_does_not_poison_the_doom_memo():
    """
    A memo derived from the active manifest is per-test, not per-process.

    THE SHAPE OF THE BUG. `evil_ticker.doom_enabled()` memoizes into a module
    global and is invalidated through `engine/games/caches.py` when a story is
    ACTIVATED. That contract holds in production, where the manifest only
    changes by activation. Tests break it: patch `entry_manifest` to a
    synthetic manifest, ask `doom_enabled()` inside that window, and the answer
    -- False, because the synthetic manifest declares no doom -- outlives the
    patch that produced it.

    What that looked like: `test_world_advances_over_a_session` passed alone,
    passed in the full suite, and failed in between, watching `advance_time`
    produce exactly zero evil. The active slug, the resolved config rate and
    the loaded locations were all IDENTICAL in the passing and failing cases;
    only the memo differed, which is why it read as unreproducible rather than
    as state.

    Guarded by an autouse fixture in conftest that resets every registered
    content cache after each test. This pins the specific poisoning so the
    THESE TWO TESTS ARE A PAIR AND THE ORDER MATTERS. This one poisons the memo
    and deliberately does NOT clean up; the next one asserts the world still
    ticks. Only the conftest fixture stands between them, so removing it makes
    the SECOND test fail. Written this way because the obvious version --
    poison, call the invalidator, assert -- passes with or without the fixture
    and therefore guards nothing at all.
    """
    import engine.game.evil_ticker as evil_ticker

    assert evil_ticker.doom_enabled() is True, (
        "the flagship declares a doom clock; this pair needs that baseline"
    )

    # Exactly what a monkeypatched `entry_manifest` leaves behind: a synthetic
    # manifest declaring no doom, memoized into a module global.
    evil_ticker._DOOM_DECLARED = False
    assert evil_ticker.doom_enabled() is False

    # NO CLEANUP ON PURPOSE. The fixture is the thing under test.


def test_the_world_still_ticks_after_the_test_above_poisoned_the_memo():
    """
    The second half of the pair. Fails without the conftest fixture.

    If the memo survived the previous test, `advance_time` here produces
    exactly zero evil -- which is the failure
    `test_turn_integration.py::test_world_advances_over_a_session` was showing
    from three files away.
    """
    import engine.game.evil_ticker as evil_ticker
    from engine.game.clock import advance_time
    from engine.game.state import GameState

    assert evil_ticker.doom_enabled() is True, (
        "the previous test's poisoned memo survived into this one -- the "
        "per-test cache reset in conftest is gone or no longer registered"
    )

    state = GameState(location_id="forest_clearing")
    before = state.evil_progress
    advance_time(state, 48)

    assert state.evil_progress > before, (
        "two in-game days passed and evil did not move"
    )
