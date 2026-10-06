"""
Many sessions, one process: the races in module state (v0.20.0 T6; spec
§5.2, survey finding 12, §9.2).

Each race is FORCED with a ``threading.Barrier`` rather than hoped for, and
every thread is joined with a timeout, so a regression fails instead of
hanging:

* two players completing a collection at once are both paid (v0.19.0: the
  second saw the process-wide re-entrancy flag and got ``[]``);
* a thread evaluating a grammar predicate while the first ``_ensure_grammar``
  is still importing waits, and sees it registered (v0.19.0: the flag was set
  before the imports, so it read unmet);
* two overlapping validator runs each get their own document cache and leave
  none installed afterwards (v0.19.0: the later ``finally`` installed the
  earlier run's dict for good);
* two first calls to ``get_config`` publish one instance (v0.19.0: two);
* each lazy getter builds its object once under two first callers (v0.19.0:
  two queues, two workers, two stores ...);
* the Oracle's totals are exact under 16 threads x 500 records. A REGRESSION
  GUARD, not a forced race: at the default switch interval the GIL can hide
  the lost update on v0.19.0's unlocked counters. The test drops the interval
  to 1 microsecond, under which the unlocked Oracle lost updates in 3 runs of
  3 (T6's canary) -- a probability, not a barrier's certainty.

Fix round 1 adds: ``registry.active()`` activating once under two first
callers; a worker reset that stops the old worker outside the getter lock;
the ONE LOCK ORDER (engine/locks.py) -- every test here runs under the order
checker (``tests/lock_order.py``), which also runs warming, activation, a
reset, a Settings save and a turn's getters racing on six threads (failing on
3c0ca34, where warming held the config lock over a getter's); the checker's
list pinned to the documented one; every module lock renewed after fork.
A held first caller now waits for the second to RETURN (or times out), so a
regression fails every run rather than most.

Version: v0.1.0 [2026-10-01]
"""

from __future__ import annotations

import contextvars
import importlib
import sys
import threading
from typing import Any, Callable

import pytest

from engine.game.state import GameState
from tests import lock_order as lock_order_helper

#: Every join and barrier wait is bounded by this; a thread still alive after
#: it is a failure, never a hang.
JOIN_SECONDS = 20.0

#: How long a first caller is held inside a build waiting for a second. Unlocked
#: (v0.19.0), both arrive within milliseconds and the barrier releases them
#: together; locked, the second waits on the lock, so the barrier times out
#: after this and the first goes on alone.
HOLD_SECONDS = 0.75


def _run_threads(targets: list[Callable[[], None]]) -> None:
    errors: list[BaseException] = []

    def wrap(fn: Callable[[], None]) -> Callable[[], None]:
        def inner() -> None:
            try:
                fn()
            except BaseException as exc:  # noqa: BLE001 -- reported below
                errors.append(exc)

        return inner

    threads = [threading.Thread(target=wrap(fn), daemon=True) for fn in targets]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(JOIN_SECONDS)
    alive = [t.name for t in threads if t.is_alive()]
    assert not alive, f"threads did not finish within {JOIN_SECONDS}s: {alive}"
    if errors:
        raise errors[0]


def _start(fn: Callable[[], None]) -> tuple[threading.Thread, list[BaseException]]:
    errors: list[BaseException] = []

    def inner() -> None:
        try:
            fn()
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    thread = threading.Thread(target=inner, daemon=True)
    thread.start()
    return thread, errors


def _join(*pairs: tuple[threading.Thread, list[BaseException]]) -> None:
    for thread, _errors in pairs:
        thread.join(JOIN_SECONDS)
    assert not any(t.is_alive() for t, _ in pairs), f"a thread outlived {JOIN_SECONDS}s"
    for _thread, errors in pairs:
        if errors:
            raise errors[0]


@pytest.fixture(autouse=True)
def lock_order(monkeypatch: pytest.MonkeyPatch) -> Any:
    """
    Every test here runs with the engine's named locks wrapped in the order
    checker (``tests/lock_order.py``): an acquisition out of engine/locks.py's
    order fails the test, whether or not it deadlocked this time.
    """
    checker = lock_order_helper.install(monkeypatch)
    yield checker
    assert not checker.violations, (
        "locks taken out of engine/locks.py's order:\n" + lock_order_helper.report(checker)
    )


def _wait(barrier: threading.Barrier) -> None:
    """Wait at a barrier; a broken or timed-out one is a result, not an error."""
    try:
        barrier.wait()
    except threading.BrokenBarrierError:
        pass


# ---------------------------------------------------------------------------
# collections: per context
# ---------------------------------------------------------------------------


def test_two_players_completing_a_collection_at_once_are_both_paid(monkeypatch):
    from engine.game import inventory

    row = {"id": "shells", "name": "Shells", "complete": True, "claimed": False, "reward_text": ""}
    monkeypatch.setattr(inventory, "collection_status", lambda state: [dict(row)])
    monkeypatch.setattr(inventory, "load_collections", lambda: [{"id": "shells", "effects": []}])

    inside = threading.Event()
    barrier = threading.Barrier(2, timeout=5.0)

    def payout(state: Any, effects: Any, ledger: Any = None) -> list[Any]:
        # Player A is held inside its payout until player B reaches its own.
        inside.set()
        _wait(barrier)
        return []

    monkeypatch.setattr(inventory.effects_module, "apply_effects", payout)

    results: dict[str, list[dict[str, Any]]] = {}

    def player(name: str) -> Callable[[], None]:
        def run() -> None:
            results[name] = inventory.evaluate_collections(GameState())

        return run

    a = _start(player("a"))
    assert inside.wait(JOIN_SECONDS), "player A never reached its payout"
    b = _start(player("b"))
    _join(a, b)

    assert [r["id"] for r in results["a"]] == ["shells"]
    assert [r["id"] for r in results["b"]] == ["shells"], (
        "player B's completed set was skipped while player A's payout ran"
    )


def test_the_collection_guard_still_stops_re_entry_on_one_thread(monkeypatch):
    from engine.game import inventory

    row = {"id": "shells", "name": "Shells", "complete": True, "claimed": False, "reward_text": ""}
    monkeypatch.setattr(inventory, "collection_status", lambda state: [dict(row)])
    monkeypatch.setattr(inventory, "load_collections", lambda: [{"id": "shells", "effects": []}])
    nested: list[list[dict[str, Any]]] = []

    def payout(state: Any, effects: Any, ledger: Any = None) -> list[Any]:
        nested.append(inventory.evaluate_collections(state))
        return []

    monkeypatch.setattr(inventory.effects_module, "apply_effects", payout)
    assert [r["id"] for r in inventory.evaluate_collections(GameState())] == ["shells"]
    assert nested == [[]]
    # Cleared in the finally: the next call on this thread pays again.
    assert [r["id"] for r in inventory.evaluate_collections(GameState())] == ["shells"]


# ---------------------------------------------------------------------------
# the grammar: locked, flag after the imports
# ---------------------------------------------------------------------------


def test_a_predicate_read_during_the_first_grammar_load_waits_for_it(monkeypatch):
    from engine.game import quests

    fake_module = "tests._fake_grammar_module_t6"
    monkeypatch.setattr(quests, "_GRAMMAR_MODULES", (fake_module,))
    monkeypatch.setattr(quests, "_grammar_loaded", False)
    monkeypatch.delitem(quests._PREDICATES, "t6_probe", raising=False)

    real_import = importlib.import_module
    barrier = threading.Barrier(2, timeout=5.0)
    second_done = threading.Event()

    def slow_import(name: str, package: Any = None) -> Any:
        if name != fake_module:
            return real_import(name, package)
        # The first load is held here until the second thread is about to
        # evaluate, then until that evaluation has RETURNED -- which, unlocked
        # (v0.19.0), it does at once, unmet; locked, it cannot until this load
        # ends, so the wait times out and the predicate is registered first.
        # Either way the outcome is decided, never left to scheduling.
        _wait(barrier)
        second_done.wait(HOLD_SECONDS)
        quests.register_predicate("t6_probe", lambda state, value, ctx: bool(value))
        return None

    monkeypatch.setattr(importlib, "import_module", slow_import)
    answers: dict[str, bool] = {}

    def first() -> None:
        quests._ensure_grammar()

    def second() -> None:
        _wait(barrier)
        try:
            answers["second"] = quests.evaluate_condition(GameState(), {"t6_probe": True})
        finally:
            second_done.set()

    try:
        _run_threads([first, second])
    finally:
        quests._PREDICATES.pop("t6_probe", None)

    assert answers["second"] is True, (
        "a predicate evaluated during the first grammar load read as unmet"
    )


def test_a_failed_grammar_import_is_recorded_not_retried(monkeypatch):
    from engine.game import quests

    fake_module = "tests._missing_grammar_module_t6"
    monkeypatch.setattr(quests, "_GRAMMAR_MODULES", (fake_module,))
    monkeypatch.setattr(quests, "_grammar_loaded", False)
    calls: list[str] = []
    real_import = importlib.import_module

    def failing(name: str, package: Any = None) -> Any:
        if name == fake_module:
            calls.append(name)
            raise ImportError(name)
        return real_import(name, package)

    monkeypatch.setattr(importlib, "import_module", failing)
    quests._ensure_grammar()
    quests._ensure_grammar()
    assert calls == [fake_module]
    assert quests._grammar_loaded is True


# ---------------------------------------------------------------------------
# the validator's run documents: per context
# ---------------------------------------------------------------------------


def _run_docs() -> Any:
    from engine.games import validation

    value = validation._RUN_DOCS
    return value.get() if isinstance(value, contextvars.ContextVar) else value


def test_two_overlapping_validator_runs_keep_their_own_documents(monkeypatch):
    from engine.games import validation

    barrier = threading.Barrier(2, timeout=5.0)
    a_done = threading.Event()
    seen: dict[str, Any] = {}

    def run_a(self: Any) -> list[Any]:
        seen["a"] = _run_docs()
        _wait(barrier)
        return []

    def run_b(self: Any) -> list[Any]:
        seen["b"] = _run_docs()
        _wait(barrier)
        # B's run ends after A's, so its finally runs last.
        a_done.wait(JOIN_SECONDS)
        return []

    class A(validation.StoryValidator):
        _run = run_a  # type: ignore[assignment]

    class B(validation.StoryValidator):
        _run = run_b  # type: ignore[assignment]

    def first() -> None:
        try:
            object.__new__(A).run()
        finally:
            a_done.set()

    def second() -> None:
        object.__new__(B).run()

    a = _start(first)
    b = _start(second)
    _join(a, b)

    assert isinstance(seen["a"], dict) and isinstance(seen["b"], dict)
    assert seen["a"] is not seen["b"], "two runs shared one document cache"
    assert _run_docs() is None, "a document cache outlived its validator run"


def test_a_nested_validator_run_shares_its_callers_documents(monkeypatch):
    from engine.games import validation

    seen: list[Any] = []

    class Inner(validation.StoryValidator):
        def _run(self) -> list[Any]:  # type: ignore[override]
            seen.append(_run_docs())
            return []

    class Outer(validation.StoryValidator):
        def _run(self) -> list[Any]:  # type: ignore[override]
            seen.append(_run_docs())
            object.__new__(Inner).run()
            return []

    object.__new__(Outer).run()
    assert seen[0] is seen[1] and isinstance(seen[0], dict)
    assert _run_docs() is None


# ---------------------------------------------------------------------------
# get_config: one instance
# ---------------------------------------------------------------------------


def test_two_first_calls_to_get_config_publish_one_instance(monkeypatch):
    from engine import config

    original = config._instance
    monkeypatch.setattr(config, "_instance", None)
    barrier = threading.Barrier(2, timeout=HOLD_SECONDS)
    real_load = config._load_yaml

    def held(path: Any) -> Any:
        # Both first callers are held as the build reads its first layer; with
        # the lock, the second never gets here and the first times out and
        # goes on alone.
        if path == config._DEFAULT_PATH:
            _wait(barrier)
        return real_load(path)

    monkeypatch.setattr(config, "_load_yaml", held)
    got: list[Any] = []
    _run_threads([lambda: got.append(config.get_config()), lambda: got.append(config.get_config())])
    assert len(got) == 2
    assert got[0] is got[1], "two first calls to get_config built two instances"
    assert config._instance is got[0]
    # The rebuilt config answers as the one it replaces.
    if original is not None:
        assert got[0].get("scene.clockwork.port") == original.get("scene.clockwork.port")


def test_a_reset_during_a_build_does_not_leave_the_stale_instance(monkeypatch):
    """reset_config waits for a build in flight, then drops what it built."""
    from engine import config

    monkeypatch.setattr(config, "_instance", None)
    monkeypatch.setattr("engine.games.caches.reset_all_caches", lambda: None)
    building = threading.Event()
    reset_done = threading.Event()
    real_load = config._load_yaml

    def held(path: Any) -> Any:
        # The build is held until the reset has RETURNED: at once when the
        # reset does not wait for it (v0.19.0), never when it does, so the
        # wait times out and the build finishes first. Decided either way.
        if path == config._DEFAULT_PATH:
            building.set()
            reset_done.wait(HOLD_SECONDS)
        return real_load(path)

    def reset() -> None:
        try:
            config.reset_config()
        finally:
            reset_done.set()

    monkeypatch.setattr(config, "_load_yaml", held)
    builder = _start(config.get_config)
    assert building.wait(JOIN_SECONDS)
    resetter = _start(reset)
    _join(builder, resetter)
    assert config._instance is None, "a reset raced by a build left that build installed"


# ---------------------------------------------------------------------------
# the lazy getters: built once
# ---------------------------------------------------------------------------

GETTERS = [
    ("engine.lore.manager", "get_lore_manager", "LoreManager", "_manager"),
    ("engine.llm.client", "get_lms_client", "LMSClient", "_client_instance"),
    ("engine.llm.ollama", "get_ollama_client", "OllamaClient", "_client_instance"),
    ("engine.mcp.scene_rules_engine", "get_rules_engine", "SceneRulesEngine", "_rules_instance"),
    ("engine.media.queue", "get_media_queue", "MediaQueue", "_queue"),
    ("engine.media.providers", "get_image_worker", "ImageWorker", "_worker"),
    ("engine.media.tts", "get_speech_worker", "SpeechWorker", "_worker"),
    ("engine.scenes.default_scene", "get_store", "SessionStore", "_store"),
    ("engine.telemetry.oracle", "get_oracle", "Oracle", "_oracle"),
]


@pytest.mark.parametrize("module_name,getter,cls,attr", GETTERS, ids=[g[1] for g in GETTERS])
def test_two_first_calls_to_a_lazy_getter_build_one_object(monkeypatch, module_name, getter, cls, attr):
    module = importlib.import_module(module_name)
    barrier = threading.Barrier(2, timeout=HOLD_SECONDS)
    built: list[Any] = []

    class Slow:
        db_path = None

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            built.append(self)
            _wait(barrier)

        def start(self) -> None:  # a worker getter starts what it built
            pass

        def stop(self) -> None:
            pass

        def close(self) -> None:
            pass

    monkeypatch.setattr(module, cls, Slow)
    monkeypatch.setattr(module, attr, None)
    got: list[Any] = []
    fn = getattr(module, getter)
    _run_threads([lambda: got.append(fn()), lambda: got.append(fn())])
    assert len(built) == 1, f"{getter} built {len(built)} objects under two first callers"
    assert got[0] is got[1]


def test_two_first_calls_for_one_save_store_build_one(monkeypatch, tmp_path):
    from engine.persistence import saves

    barrier = threading.Barrier(2, timeout=HOLD_SECONDS)
    built: list[Any] = []

    class Slow:
        root = tmp_path  # the conftest's teardown reads every built store's root

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            built.append(self)
            _wait(barrier)

    monkeypatch.setattr(saves, "SaveStore", Slow)
    monkeypatch.setattr(saves, "_stores", None)
    got: list[Any] = []
    call = lambda: got.append(saves.save_store_for("", "clockwork-dark"))  # noqa: E731
    _run_threads([call, call])
    assert len(built) == 1
    assert got[0] is got[1]


def test_a_reset_during_a_save_store_build_does_not_break_it(monkeypatch, tmp_path):
    """Found by the lock-order race run: a config reset nulls ``_stores``
    without the lock, and the build then wrote into None (TypeError)."""
    from engine.persistence import saves

    class ResetMidBuild:
        root = tmp_path

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            saves.reset_save_store()  # what a concurrent config reset does

    monkeypatch.setattr(saves, "SaveStore", ResetMidBuild)
    monkeypatch.setattr(saves, "_stores", None)
    store = saves.save_store_for("", "clockwork-dark")
    assert isinstance(store, ResetMidBuild)


def test_a_legacy_save_migration_finishes_before_a_second_caller_goes_on(monkeypatch, tmp_path):
    from engine.persistence import saves

    monkeypatch.setattr(saves, "saves_base", lambda: tmp_path)
    monkeypatch.setattr(saves, "_migrated", set())
    started = threading.Event()
    second_done = threading.Event()
    order: list[str] = []

    def slow_migrate(base: Any, slug: str) -> None:
        # Held until the second caller has RETURNED: at once if it does not
        # wait (v0.19.0), never if it does, so the wait times out. Decided
        # either way, not left to scheduling.
        started.set()
        second_done.wait(HOLD_SECONDS)
        order.append("migrated")

    monkeypatch.setattr(saves, "_migrate_legacy", slow_migrate)
    first = _start(lambda: saves.saves_root("clockwork-dark"))
    assert started.wait(JOIN_SECONDS)

    def second() -> None:
        try:
            saves.saves_root("clockwork-dark")
            order.append("second returned")
        finally:
            second_done.set()

    other = _start(second)
    _join(first, other)
    assert order == ["migrated", "second returned"]


# ---------------------------------------------------------------------------
# the Oracle: exact totals (a guard)
# ---------------------------------------------------------------------------


def test_the_oracle_keeps_exact_totals_under_sixteen_threads():
    """REGRESSION GUARD: the GIL can hide v0.19.0's lost updates (module docstring)."""
    from engine.telemetry.oracle import Oracle

    oracle = Oracle()
    threads, records = 16, 500
    barrier = threading.Barrier(threads, timeout=JOIN_SECONDS)
    payload = {
        "governance": [{"rule_id": "R003"}],
        "assistant": {"spoke": True, "reliable": False, "gift": True},
        "challenge": {"kind": "set_piece"},
    }

    def worker() -> None:
        _wait(barrier)
        for _ in range(records):
            oracle.record_turn(payload, latency_ms=1.0)
            oracle.record_unearned_claim("gold", 1)
            oracle.metrics()
            oracle.recent(5)

    # Switch threads as often as the interpreter allows, so an unlocked
    # read-modify-write has the most chances to interleave.
    interval = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    try:
        _run_threads([worker] * threads)
    finally:
        sys.setswitchinterval(interval)
    total = threads * records
    metrics = oracle.metrics()
    assert metrics["turns"] == total
    assert metrics["violations_total"] == total
    assert metrics["violations_by_rule"] == {"R003": total}
    assert metrics["assistant_misled_count"] == total
    assert metrics["gifts"] == total
    assert metrics["challenges_started"] == {"set_piece": total}
    assert metrics["unearned_claims"]["gold"]["count"] == total
    assert metrics["unearned_claims"]["gold"]["total_delta"] == total
    assert metrics["avg_latency_ms"] == 1.0
    assert sorted(r["turn"] for r in oracle.recent(total))[-1] == total


# ---------------------------------------------------------------------------
# the per-context guards: clear when a thread is reused
# ---------------------------------------------------------------------------


def test_the_thread_local_guards_are_clear_after_each_call():
    """gthread reuses threads: a guard set inside a call is cleared by its end."""
    from engine.game import clock, encounter, inventory

    for guard in (clock._guard, encounter._death_guard, encounter._terminal_lock_guard):
        assert isinstance(guard, threading.local)
    assert isinstance(inventory._evaluating_collections, threading.local)
    assert not getattr(inventory._evaluating_collections, "active", False)
    assert getattr(clock._guard, "depth", 0) == 0


CLIENTS = [
    ("engine.llm.client", "get_lms_client", "release_lms_client", "LMSClient"),
    ("engine.llm.ollama", "get_ollama_client", "release_ollama_client", "OllamaClient"),
]


@pytest.mark.parametrize("module_name,getter,release,cls", CLIENTS, ids=[c[1] for c in CLIENTS])
def test_a_release_during_a_client_build_drops_what_it_built(monkeypatch, module_name, getter, release, cls):
    """A Settings save's release waits for a build in flight (built from the
    old config) and drops it, rather than leaving it in place."""
    module = importlib.import_module(module_name)
    building = threading.Event()
    released = threading.Event()

    class Slow:
        def __init__(self) -> None:
            self._client = self  # finalize() closes this
            building.set()
            # Held until the release has RETURNED: at once if it does not
            # wait (3c0ca34), never if it does. Decided either way.
            released.wait(HOLD_SECONDS)

        def close(self) -> None:
            pass

    def do_release() -> None:
        try:
            getattr(module, release)()
        finally:
            released.set()

    monkeypatch.setattr(module, cls, Slow)
    monkeypatch.setattr(module, "_client_instance", None)
    builder = _start(getattr(module, getter))
    assert building.wait(JOIN_SECONDS)
    releaser = _start(do_release)
    _join(builder, releaser)
    assert module._client_instance is None, f"{release} left a client built from the old config"


# ---------------------------------------------------------------------------
# the skills server: single flight, and a backoff after a failed start
# ---------------------------------------------------------------------------


@pytest.fixture
def stub_skills_server(monkeypatch):
    """
    ``SkillsServer`` replaced by a stub whose ``start`` waits on an event and
    returns what the test says. The real server is never built here (it
    starts only under ``@pytest.mark.mcp_server``); MCP reads as enabled.
    """
    from engine.agents import mechanics
    from engine.mcp import skills_server

    control = {
        "release": threading.Event(),
        "result": True,
        "starts": 0,
        "stops": 0,
        "entered": threading.Event(),
    }

    class StubServer:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def start(self) -> bool:
            control["starts"] += 1
            control["entered"].set()
            control["release"].wait(JOIN_SECONDS)
            return bool(control["result"])

        def stop(self, **_kwargs: Any) -> None:
            control["stops"] += 1

    monkeypatch.setattr(skills_server, "SkillsServer", StubServer)
    monkeypatch.setattr(mechanics, "mechanics_enabled", lambda: True)
    for name, value in (("_server", None), ("_starting", False), ("_failed_at", None), ("_generation", 0)):
        monkeypatch.setattr(skills_server, name, value, raising=False)
    return skills_server, control


def test_callers_during_a_skills_server_start_do_not_wait_for_it(stub_skills_server):
    """Fails on b2b1b86, which held the lock across the whole start."""
    skills_server, control = stub_skills_server
    resolver = lambda _sid: None  # noqa: E731
    got: dict[str, Any] = {}
    starter = _start(lambda: got.__setitem__("starter", skills_server.get_skills_server(resolver)))
    try:
        assert control["entered"].wait(JOIN_SECONDS)
        other = _start(lambda: got.__setitem__("other", skills_server.get_skills_server(resolver)))
        other[0].join(HOLD_SECONDS * 4)
        assert not other[0].is_alive(), "a second caller waited out the skills server's start"
        _join(other)
        assert got["other"] is None  # not ready: this turn runs without tools
    finally:
        control["release"].set()
        _join(starter)
    assert got["starter"] is not None
    assert skills_server.get_skills_server(resolver) is got["starter"]
    assert control["starts"] == 1


def test_a_failed_skills_server_start_is_not_retried_until_the_backoff_passes(stub_skills_server):
    """Fails on b2b1b86, which retried the start on every call (every turn)."""
    import yaml

    from engine.config import project_root

    skills_server, control = stub_skills_server
    control["result"] = False
    control["release"].set()
    resolver = lambda _sid: None  # noqa: E731
    assert skills_server.get_skills_server(resolver) is None
    assert skills_server.get_skills_server(resolver) is None
    assert control["starts"] == 1, "a failed start was retried at once"
    # T9 fix round 1: a start that timed out may come up later; it is stopped.
    assert control["stops"] == 1
    # The backoff is config (rule 5), with its default in default.yaml.
    default = yaml.safe_load((project_root() / "config" / "default.yaml").read_text(encoding="utf-8"))
    retry = float(default["llm"]["mcp"]["start_retry_seconds"])
    assert skills_server._start_retry_seconds() == retry
    # Once it has passed, the next call tries again.
    skills_server._failed_at = skills_server.time.monotonic() - retry - 1
    control["result"] = True
    assert skills_server.get_skills_server(resolver) is not None
    assert control["starts"] == 2


def test_a_reset_during_a_skills_server_start_is_not_published(stub_skills_server):
    skills_server, control = stub_skills_server
    got: list[Any] = []
    starter = _start(lambda: got.append(skills_server.get_skills_server(lambda _sid: None)))
    assert control["entered"].wait(JOIN_SECONDS)
    skills_server.reset_skills_server()
    control["release"].set()
    _join(starter)
    assert got == [None]
    assert skills_server._server is None
    # v0.20.0 T9: nobody owns the discarded server, so it is stopped, not
    # left listening on its port for the life of the process.
    assert control["stops"] == 1


def test_a_turn_that_finds_a_start_in_flight_says_it_plays_without_tools(stub_skills_server, caplog):
    """
    v0.20.0 T9: a turn whose skills server is still starting gets no tools,
    and its log says why (the start in flight), so nothing reads the turn as
    one whose tools ran.
    """
    from engine.agents import mechanics
    from engine.game.engine import GameEngine
    from engine.game.state import GameState

    skills_server, control = stub_skills_server
    starter = _start(lambda: skills_server.get_skills_server(lambda _sid: None))
    engine = GameEngine(GameState())
    try:
        assert control["entered"].wait(JOIN_SECONDS)
        assert skills_server.start_in_flight()
        with caplog.at_level("WARNING", logger="engine.agents.mechanics"):
            receipts = mechanics.run_mechanics_phase(engine, "look around")
        said = [r.getMessage() for r in caplog.records if r.name == "engine.agents.mechanics"]
        assert any("start is in flight" in m and "without tools" in m for m in said), said
        # Fix round 1: and in the turn's receipts, engine-authored, so the
        # narration is told no tool ran (receipts_block renders it).
        from engine.agents.prompts import receipts_block

        assert receipts == [mechanics.tools_unavailable_receipt()]
        block = receipts_block(receipts)
        assert "no tool ran this turn" in block
    finally:
        control["release"].set()
        _join(starter)
        mechanics.release_engine(engine.state.session_id)
    assert not skills_server.start_in_flight()


# ---------------------------------------------------------------------------
# ModelRegistry.models(): one discovery, however many callers (v0.20.0 T9)
# ---------------------------------------------------------------------------


def test_two_cold_model_list_reads_make_one_discovery_request(monkeypatch):
    """
    Two planners on two threads asking a cold registry for its models made a
    discovery request each (T1 re-review); behind a shared model server that
    doubled every cold start. Now the second waits for the first's answer.
    Fails on 844bf5f, where both refresh.
    """
    from engine.llm import registry as registry_module

    reg = registry_module.ModelRegistry()
    fetches: list[str] = []
    first_in = threading.Event()
    second_waiting = threading.Event()
    real_wait = registry_module._Flight.wait

    def fetch(path: str, body: Any = None) -> Any:
        fetches.append(path)
        first_in.set()
        if len(fetches) > 1:
            second_waiting.set()  # the bug: a second discovery, not a wait
        # Held until the other caller is either waiting on this one's flight
        # or (the bug) inside a second fetch of its own.
        assert second_waiting.wait(JOIN_SECONDS)
        return {"models": [], "data": [], "object": "list"}

    def waiting(self: Any, timeout: Any = None) -> bool:
        second_waiting.set()
        return real_wait(self, timeout)

    monkeypatch.setattr(reg, "_fetch", fetch)
    monkeypatch.setattr(registry_module._Flight, "wait", waiting)
    got: dict[str, Any] = {}
    first = _start(lambda: got.__setitem__("first", reg.models()))
    assert first_in.wait(JOIN_SECONDS)
    second = _start(lambda: got.__setitem__("second", reg.models()))
    _join(first, second)
    assert len(fetches) == 1, f"two discovery requests: {fetches}"
    assert got["first"] == got["second"]
    # Warm now: a third read makes none.
    assert reg.models() == got["first"]
    assert len(fetches) == 1


def test_a_failed_single_flight_discovery_fails_every_waiter(monkeypatch):
    """
    T9 fix round 1 (M7): when the leader's refresh raises, a follower waiting
    on its flight raises the same error rather than answering "no models".
    Fails on 1e0557f, where the follower returned [].
    """
    from engine.llm import registry as registry_module

    reg = registry_module.ModelRegistry()
    leader_in = threading.Event()
    follower_waiting = threading.Event()
    real_wait = registry_module._Flight.wait

    def refresh() -> Any:
        leader_in.set()
        assert follower_waiting.wait(JOIN_SECONDS)
        raise RuntimeError("the model server is down")

    def waiting(self: Any, timeout: Any = None) -> bool:
        follower_waiting.set()
        return real_wait(self, timeout)

    monkeypatch.setattr(reg, "refresh", refresh)
    monkeypatch.setattr(registry_module._Flight, "wait", waiting)
    leader = _start(lambda: reg.models())
    assert leader_in.wait(JOIN_SECONDS)
    follower = _start(lambda: reg.models())
    for thread, _errors in (leader, follower):
        thread.join(JOIN_SECONDS)
        assert not thread.is_alive()
    assert [str(e) for e in leader[1]] == ["the model server is down"]
    assert [str(e) for e in follower[1]] == ["the model server is down"], "the follower hid the failure"


# ---------------------------------------------------------------------------
# registry.active(): double-checked
# ---------------------------------------------------------------------------


def test_two_first_calls_to_registry_active_activate_once(monkeypatch):
    from engine.games import registry

    monkeypatch.setattr(registry, "_active", None)
    barrier = threading.Barrier(2, timeout=HOLD_SECONDS)
    calls: list[int] = []
    manifest = object()

    def slow_activate(slug: Any = None) -> Any:
        calls.append(1)
        _wait(barrier)
        registry._active = manifest
        return manifest

    monkeypatch.setattr(registry, "activate", slow_activate)
    got: list[Any] = []
    _run_threads([lambda: got.append(registry.active()), lambda: got.append(registry.active())])
    assert len(calls) == 1, "two first callers of active() activated twice"
    assert got == [manifest, manifest]


# ---------------------------------------------------------------------------
# a worker reset stops the old worker outside the getter lock
# ---------------------------------------------------------------------------

WORKERS = [
    ("engine.media.providers", "get_image_worker", "reset_image_worker", "ImageWorker"),
    ("engine.media.tts", "get_speech_worker", "reset_speech_worker", "SpeechWorker"),
]


@pytest.mark.parametrize("module_name,getter,reset,cls", WORKERS, ids=[w[1] for w in WORKERS])
def test_a_worker_reset_does_not_hold_the_getter_lock_across_its_join(
    monkeypatch, module_name, getter, reset, cls
):
    module = importlib.import_module(module_name)
    stopping = threading.Event()
    let_stop = threading.Event()

    class Stuck:
        def stop(self) -> None:  # joins a thread that takes its time
            stopping.set()
            let_stop.wait(JOIN_SECONDS)

    class Fresh:
        def start(self) -> None:
            pass

        def stop(self) -> None:
            pass

    monkeypatch.setattr(module, "_worker", Stuck())
    monkeypatch.setattr(module, cls, Fresh)
    resetter = _start(getattr(module, reset))
    try:
        assert stopping.wait(JOIN_SECONDS)
        # The old worker is still stopping; a getter must not wait for it.
        getting = _start(getattr(module, getter))
        getting[0].join(HOLD_SECONDS * 4)
        assert not getting[0].is_alive(), f"{getter} waited behind {reset}'s join"
        _join(getting)
        # And it got a new worker, not the one being stopped (3c0ca34 dropped
        # the reference only after stop() returned, so a getter in between
        # was handed the dying worker).
        assert isinstance(module._worker, Fresh), f"{getter} handed out the worker being stopped"
    finally:
        let_stop.set()
        _join(resetter)


# ---------------------------------------------------------------------------
# the lock order
# ---------------------------------------------------------------------------


def _documented_order() -> list[str]:
    """engine/locks.py's LOCK ORDER, as its docstring numbers it."""
    import re

    from engine import locks

    return re.findall(r"^\d+\. (engine\.\S+)$", locks.__doc__ or "", flags=re.MULTILINE)


def test_the_checker_holds_the_documented_order():
    assert _documented_order() == list(lock_order_helper.ORDER)


def test_the_checker_holds_the_documented_leaves():
    import re

    from engine import locks

    section = (locks.__doc__ or "").split("LEAF LOCKS", 1)[1].split("TWO MORE", 1)[0]
    assert re.findall(r"^- (engine\.\S+)$", section, flags=re.MULTILINE) == list(lock_order_helper.LEAVES)


def test_a_turn_lock_is_only_ever_taken_non_blocking():
    """engine/locks.py: a session's turn lock is taken ``blocking=False`` and
    never waited for, so it can be in no deadlock. Pinned by AST over engine/."""
    import ast

    from tests.module_state_scan import ENGINE

    offenders = []
    for path in ENGINE.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            is_turn_lock = (
                isinstance(node, ast.Attribute)
                and node.attr == "lock"
                and isinstance(node.value, (ast.Name, ast.Attribute))
                and (getattr(node.value, "id", None) or getattr(node.value, "attr", None)) == "session"
            )
            if not is_turn_lock:
                continue
            parent = next(
                (p for p in ast.walk(tree) for c in ast.iter_child_nodes(p) if c is node), None
            )
            if isinstance(parent, ast.withitem):
                offenders.append(f"{path.name}:{node.lineno} with session.lock")
            elif isinstance(parent, ast.Attribute) and parent.attr == "acquire":
                call = next(
                    (p for p in ast.walk(tree) if isinstance(p, ast.Call) and p.func is parent), None
                )
                kwargs = {k.arg: k.value for k in (call.keywords if call else [])}
                blocking = kwargs.get("blocking")
                if not (isinstance(blocking, ast.Constant) and blocking.value is False):
                    offenders.append(f"{path.name}:{node.lineno} blocking acquire")
    assert not offenders, offenders


def test_the_checker_catches_a_blocking_acquire_under_a_leaf_and_a_lane_under_a_lock():
    checker = lock_order_helper.Checker()
    leaf = lock_order_helper.TrackedLock(threading.RLock(), lock_order_helper.LEAVES[0], checker)
    config_lock = lock_order_helper.TrackedLock(threading.RLock(), "engine.config._config_lock", checker)
    other = lock_order_helper.TrackedLock(threading.Lock(), "engine.persistence.saves._stores_lock", checker)
    rules = lock_order_helper.TrackedLock(threading.Lock(), "engine.mcp.scene_rules_engine._rules_lock", checker)
    with rules:
        with leaf:  # a leaf under an ordered lock: fine
            assert other.acquire(blocking=False)  # a try under a leaf: fine
            other.release()
    assert checker.violations == []
    with leaf:
        with config_lock:  # blocking, under a leaf
            pass
    assert len(checker.violations) == 1
    lane = lock_order_helper.TrackedSemaphore(threading.BoundedSemaphore(1), checker)
    with lane:
        with config_lock:  # under a lane: fine
            pass
    assert len(checker.violations) == 1
    with config_lock:
        with lane:  # a lane taken holding an ordered lock
            pass
    assert len(checker.violations) == 2
    checker.violations.clear()


def test_a_save_store_writes_its_index_holding_only_its_leaf(tmp_path):
    """SaveStore._lock is a leaf: the index bound and the summary are read
    before it is taken, so a save under the checker takes nothing under it."""
    from engine import config
    from engine.persistence.saves import SaveStore

    store = SaveStore(root=tmp_path / "saves", slug="clockwork-dark")
    assert isinstance(store._lock, lock_order_helper.TrackedLock), "the checker is not tracking the leaf"
    saved_config = config._instance
    try:
        config._instance = None  # so any get_config under the leaf would take the config lock
        store.save(GameState(), save_id="leafcheck")
        store.delete("leafcheck")
    finally:
        config._instance = saved_config
    # The autouse checker fails the test on a blocking acquisition under the leaf.


def test_the_hosting_leaves_are_tracked_by_class_and_take_nothing_under_them(lock_order):
    """
    v0.20.0 T15 (from T13's and T14's reports): ``LongHolds._lock``,
    ``OneTimeShown._lock`` and ``AuditWriter._lock`` are leaves in the formal
    list, each tracked by its own class (no longer under another class's name
    in its module), and used under the checker -- the autouse fixture fails
    the test on any blocking acquisition under one. Fails on bebdcb2, whose
    checker named every ``engine.hosting.limits`` lock ``LoginLimiter._lock``
    and tracked neither of the other two.
    """
    from engine.hosting.admin.users import OneTimeShown
    from engine.hosting.limits import ActionLimiter, LongHolds, LoginLimiter, TurnSlots
    from engine.hosting.supervisor.process import AuditWriter

    holds = LongHolds(4, per_account=2)
    shown = OneTimeShown()
    writer = AuditWriter()
    names = {
        "engine.hosting.limits.LongHolds._lock": holds,
        "engine.hosting.admin.users.OneTimeShown._lock": shown,
        "engine.hosting.supervisor.process.AuditWriter._lock": writer,
        "engine.hosting.limits.ActionLimiter._lock": ActionLimiter(10),
        "engine.hosting.limits.LoginLimiter._lock": LoginLimiter(10),
        # The final review's addition: tracked by its own class's name too.
        "engine.hosting.limits.TurnSlots._lock": TurnSlots(2),
    }
    for name, owner in names.items():
        assert isinstance(owner._lock, lock_order_helper.TrackedLock) and owner._lock.name == name, name
    # A module named more than once names each lock by its own class (none of
    # the limits module's locks is left untracked since the final review).

    assert holds.try_take("u_000000000001", "sid1") == ""
    assert holds.of_account("u_000000000001") == 1 and holds.inside == 1
    holds.give_back("u_000000000001", "sid1")
    token = shown.put("u_000000000001", {"password": "x"})
    assert shown.take("u_000000000001", token) == {"password": "x"} and len(shown) == 0
    done = threading.Event()
    writer.submit(done.set)
    writer.close(timeout=JOIN_SECONDS)
    assert done.is_set()
    for name in names:
        if name.endswith(("LongHolds._lock", "OneTimeShown._lock", "AuditWriter._lock")):
            assert name in lock_order.acquired, name


def test_a_lane_is_taken_holding_nothing(monkeypatch):
    from engine.llm import gate

    gate.reset_lanes()
    try:
        with gate.inference_slot(label="t6", lane="utility", timeout=JOIN_SECONDS):
            pass
    finally:
        gate.reset_lanes()


def test_every_module_lock_is_ordered_and_renewed_after_fork():
    """Each lock object the inventory lists is in the order and renews after fork."""
    from engine import locks
    from tests.module_state_scan import load_inventory

    lock_types = (type(threading.Lock()), type(threading.RLock()), lock_order_helper.TrackedLock)
    module_locks = []
    for site in load_inventory():
        if "#" in site or site.endswith("()"):
            continue
        module_name, _, name = site.rpartition(".")
        try:
            value = getattr(importlib.import_module(module_name), name, None)
        except ImportError:  # a class attribute's "module" is a class path
            continue
        if isinstance(value, lock_types):
            module_locks.append(site)
    assert module_locks, "found no module locks: the probe is broken"
    renewed = {f"{m}.{n}" for m, n in locks.RENEWED_AFTER_FORK}
    assert sorted(set(module_locks) - set(lock_order_helper.ORDER)) == [], "a lock missing from the order"
    assert sorted(set(module_locks) - renewed) == [], "a lock not renewed after fork"


def test_renew_after_fork_replaces_each_named_lock(monkeypatch):
    """No fork on Windows, so the registered handler is called by hand."""
    from engine import locks

    namespace: dict[str, Any] = {"__name__": "engine.fake", "_a": threading.Lock(), "_b": threading.RLock()}
    registered: list[Any] = []
    monkeypatch.setattr(
        locks.os, "register_at_fork", lambda **kw: registered.append(kw["after_in_child"]), raising=False
    )
    monkeypatch.setattr(locks, "RENEWED_AFTER_FORK", [])
    locks.renew_after_fork(namespace, _a=threading.Lock, _b=threading.RLock)
    assert locks.RENEWED_AFTER_FORK == [("engine.fake", "_a"), ("engine.fake", "_b")]
    old_a, old_b = namespace["_a"], namespace["_b"]
    old_a.acquire()  # as a parent's other thread would have held it at fork
    (renew,) = registered
    renew()
    assert namespace["_a"] is not old_a and namespace["_b"] is not old_b
    assert namespace["_a"].acquire(blocking=False), "the child's lock is not free"
    namespace["_a"].release()
    old_a.release()


def test_the_checker_catches_an_inversion():
    """The checker's own canary: config lock (innermost) held, then a getter's."""
    checker = lock_order_helper.Checker()
    outer = lock_order_helper.TrackedLock(threading.RLock(), "engine.config._config_lock", checker)
    inner = lock_order_helper.TrackedLock(threading.Lock(), "engine.mcp.scene_rules_engine._rules_lock", checker)
    with inner:
        with outer:  # in order: fine
            pass
    assert checker.violations == []
    with outer:
        with inner:  # out of order
            pass
    assert len(checker.violations) == 1


def test_warming_activation_and_resets_racing_keep_the_lock_order(lock_order, monkeypatch, tmp_path):
    """
    Warming, activation, a reset, a Settings save and the getters a turn uses,
    all at once on six threads, three rounds each: every lock is taken in
    engine/locks.py's order. On 3c0ca34 this fails (warming held the config
    lock -- then the innermost -- while ``get_rules_engine`` took the rules
    engine's).
    """
    from engine import config
    from engine.api import settings
    from engine.game import quests
    from engine.games import caches, registry
    from engine.llm import client, ollama
    from engine.mcp import scene_rules_engine
    from engine.persistence import saves
    from engine.scenes import default_scene
    from engine.telemetry import oracle

    repo = config._ROOT
    rounds = 3
    barrier = threading.Barrier(6, timeout=JOIN_SECONDS)

    def looped(fn: Callable[[], Any]) -> Callable[[], None]:
        def run() -> None:
            _wait(barrier)
            for _ in range(rounds):
                fn()

        return run

    def turn_getters(save: bool) -> None:
        client.get_lms_client()
        ollama.get_ollama_client()
        scene_rules_engine.get_rules_engine()
        oracle.get_oracle().record_turn({})
        store = saves.save_store_for("", "clockwork-dark")
        if save:
            # One saving thread: across a reset two SaveStore objects for one
            # directory hold different index locks (a CLAUDE.md deferred row).
            store.save(GameState(), save_id="t6race")  # the store's leaf lock
        default_scene.get_store().get("t6-no-such-session")  # SessionStore's leaf
        quests.evaluate_condition(GameState(), {"flag": "t6_never_set"})
        config.get_config().get("paths.locations")

    try:
        with monkeypatch.context() as local:
            # The Settings save writes here, never config/local.yaml.
            local.setattr(settings, "_LOCAL_CONFIG", tmp_path / "local.yaml")
            local.setattr(config, "_CONFIG_DIR", tmp_path)
            local.setattr(config, "_DEFAULT_PATH", repo / "config" / "default.yaml")
            _run_threads(
                [
                    looped(caches.warm_all_caches),
                    looped(lambda: registry.activate("clockwork-dark")),
                    looped(config.reset_config),
                    looped(lambda: settings.apply_settings({"tts.enabled": False})),
                    looped(lambda: turn_getters(save=True)),
                    looped(lambda: turn_getters(save=False)),
                ]
            )
    finally:
        config.reset_config()
    assert lock_order.acquired, "the checker saw no lock at all: it is not installed"
    violations = lock_order_helper.report(lock_order)
    lock_order.violations.clear()  # reported here, as this test's failure
    assert not violations, "locks taken out of engine/locks.py's order:\n" + violations
