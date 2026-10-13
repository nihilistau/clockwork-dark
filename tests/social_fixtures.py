"""Fixtures for the READ RECEIPTS tests: the story active, a fresh state.

Shared by every social test (Plan decision 19). The suite registers no
``pytest_plugins``, so each test module imports the fixtures it uses by name.
"""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Any, Iterator, NamedTuple

import pytest


@contextlib.contextmanager
def _quieted() -> Iterator[None]:
    """
    No social test reaches a model or races its own pass (pre-flight F2):
    the voicer's model function is a ``StubVoice("zero")``, its summary
    function a one-argument stub ("" takes the deterministic fallback), and
    the process's scheduler PAUSED, so a phone action that leaves a due
    message starts no background pass -- a test runs ``run_pass`` itself, or
    calls ``voicer.get_scheduler().resume()``. At the end both singletons
    (the scheduler and the DirtySaver) are stopped and dropped.
    """
    from engine.social import saves, voicer
    from tests.social_stub import StubVoice

    voicer.set_llm_fn(StubVoice("zero"))
    voicer.set_summary_fn(lambda messages: "")        # one argument; "" takes the deterministic fallback
    voicer.get_scheduler().pause()                      # direct-pass tests run run_pass themselves
    try:
        yield
    finally:
        voicer.reset()                                  # cancel_all, stop, drop the singleton, fns to None
        saves.reset_dirty_saver()
        _reset_media()


def _reset_media() -> None:
    """No media hand-off, client factory or worker thread -- the speech worker's included (T21) -- outlives its test (T19)."""
    import sys

    jobs = sys.modules.get("engine.media.comfy.jobs")
    if jobs is not None:
        jobs.set_on_done(None)
        jobs.set_client_factory(None)
        assert jobs.reset_media_worker(10), "the media worker's thread did not end"
    tts = sys.modules.get("engine.media.tts")
    if tts is not None:
        tts.reset_speech_worker()                       # a voice note's speech worker (T21), stopped and dropped


@pytest.fixture(autouse=True)
def _quiet_voicer() -> Iterator[None]:
    """
    ``_quieted`` for every test of a module that imports this fixture.
    ``receipts_active`` and ``hosted_receipts`` enter ``_quieted`` themselves
    (a fixture is found by name in the test's module, and each module imports
    only the fixtures it names), so every social test is quiet whether or not
    its module imports this one; entered twice, the inner one simply sets
    the same stubs again and resets first.
    """
    with _quieted():
        yield


@pytest.fixture
def receipts_active() -> Iterator[None]:
    from engine import social
    from engine.games import registry

    with _quieted():                    # F2: no pass reaches a model or races the test's own
        registry.activate("read-receipts")
        try:
            social.boot()
            from engine.social import population

            population.reset_profiles()   # no person cached by an earlier test's filter or data (F7)
            yield
        finally:
            _stop_dirty_saver()
            registry.deactivate()  # tests/conftest.py::_no_story_outlives_its_test checks this


def _stop_dirty_saver() -> None:
    """No phone save timer outlives its test (T10): the DirtySaver stopped and dropped, the exit flush unregistered."""
    import sys

    saves = sys.modules.get("engine.social.saves")
    if saves is not None:
        saves.reset_dirty_saver()
        # Nor its exit flush: no phone save is written after the session's storage checks.
        import atexit

        atexit.unregister(saves.flush_all)


@pytest.fixture
def receipts_state(receipts_active):
    from engine.game import procgen

    return procgen.new_game_state(player_name="Sam", seed=4242)


def _top(state, app: str) -> str:
    """The top card of ``app``'s deck: THE one top-card helper (Plan decision 19). A session's is
    ``_top(session.engine.state, app)``."""
    from engine.social import apps

    pid = apps.top_card(state, app)
    assert pid, f"{app}'s deck is empty"
    return pid


@pytest.fixture
def matched(receipts_state, monkeypatch: pytest.MonkeyPatch):
    """
    ``matched(app) -> thread_id``: a mutual match on ``app`` in ``receipts_state``, made the real
    way -- the deck's top card liked with the like-back forced true, then the clock advanced
    exactly to its ``see_like`` event.
    """
    from engine.game import clock
    from engine.social import matching

    monkeypatch.setattr(matching, "likes_back", lambda *a, **k: True)

    def make(app: str) -> str:
        pid = _top(receipts_state, app)
        assert matching.like(receipts_state, app, pid)["ok"]
        due = [e for e in receipts_state.social["queue"] if e["kind"] == "see_like" and e["pid"] == pid]
        clock.advance_time(receipts_state, max(0.0, due[0]["at"] - receipts_state.world_clock_hours))
        tid = matching.thread_id(app, pid)
        assert tid in receipts_state.social["threads"]
        return tid

    return make


@pytest.fixture
def matched_numbers(receipts_state, matched):
    """
    ``matched_numbers(app) -> thread_id``: a Matchstick match taken to stage ``numbers`` through
    the effects (the stage through ``social_stage``, the messengers opened through
    ``social_message``), returning its thread on ``app`` (``texts``, ``natter`` or ``matchstick``).
    """
    from engine.social import matching, messaging

    def make(app: str) -> str:
        pid = matched("matchstick").split(":", 1)[1]
        _force_stage(receipts_state, pid, "numbers")
        messaging.open_numbers(receipts_state, pid)
        tid = matching.thread_id(app, pid)
        assert tid in receipts_state.social["threads"]
        return tid

    return make


@pytest.fixture
def numbers_pid(receipts_state, matched_numbers) -> str:
    """
    A Matchstick match taken to stage ``numbers`` (``matched_numbers``: its messengers open) with its
    warmth and trust exactly at relationships.yaml's ``meeting`` gate (T24, Plan decision 19): the pid.
    """
    from engine.social import relationships

    pid = matched_numbers("texts").split(":", 1)[1]
    _set_person(receipts_state, pid, **_at(relationships.gate_spec("meeting")))
    return pid


def _set_clock(state, hour: float) -> None:
    """Advance (through ``clock.advance_time``) to the next in-game ``hour`` o'clock."""
    from engine.game import clock

    hours = (float(hour) - state.world_clock_hours % 24.0) % 24.0
    clock.advance_time(state, hours or 24.0)


def _force_stage(state, pid: str, stage: str) -> None:
    """A person's stage, through ``social_stage`` (its one writer, Plan decision 17), whatever its gate."""
    from engine.game.effects import apply_effect

    if (state.social.get("people") or {}).get(pid, {}).get("stage") != stage:
        assert apply_effect(state, {"type": "social_stage", "pid": pid, "stage": stage})["ok"]


def _set_person(state, pid: str, **values: Any) -> None:
    """Any of a person's dynamic fields, through ``social_person``'s ``set``."""
    from engine.game.effects import apply_effect

    assert apply_effect(state, {"type": "social_person", "pid": pid, "set": dict(values)})["ok"]


def _with(fn, **over: Any):
    """A ``social.setting`` that answers ``over[key]`` first and ``fn(key, default)`` otherwise."""
    def setting(key: str, default: Any) -> Any:
        return over[key] if key in over else fn(key, default)

    return setting


def _force_archetype(monkeypatch: pytest.MonkeyPatch, state, pid: str, name: str, arc_point: Any = None) -> None:
    """
    ``pid`` plays archetype ``name``: ``population.profile`` patched for that pid to a
    ``dataclasses.replace`` of the real person, and (when given) their arc point set through
    ``social_person`` -- a forced draw (F16).
    """
    import dataclasses

    from engine.social import population

    real = population.profile

    def profile(state_, pid_):
        person = real(state_, pid_)
        return dataclasses.replace(person, archetype=name) if pid_ == pid else person

    monkeypatch.setattr(population, "profile", profile)
    if arc_point is not None:
        _set_person(state, pid, arc_point=arc_point)


def _gate_fields(gate: dict[str, Any], offset: float) -> dict[str, Any]:
    """A gate's measures, each plus ``offset``, as the person fields ``_set_person`` writes."""
    from engine.social import relationships

    out: dict[str, Any] = {}
    for name, minimum in gate.items():
        path = dict(relationships.GATE_PATHS)[name]
        value = minimum + offset
        if len(path) == 1:
            out[path[0]] = value
        else:
            out.setdefault(path[0], {})[path[1]] = value
    return out


def _just_below(gate: dict[str, Any]) -> dict[str, Any]:
    """Each of a gate's measures one below its minimum."""
    return _gate_fields(gate, -1)


def _at(gate: dict[str, Any]) -> dict[str, Any]:
    """Each of a gate's measures exactly at its minimum."""
    return _gate_fields(gate, 0)


def _engine(state):
    from engine.game.engine import GameEngine

    return GameEngine(state)


def _act(state, action: str, target: str = "", args: dict | None = None, text: str = "") -> dict[str, Any]:
    """One phone action through the real executor, as the mechanics action runs it."""
    from engine.agents.tool_dispatcher import execute_phone_intent

    return execute_phone_intent({"action": action, "target": target, "args": args or {}, "text": text},
                                _engine(state))


def _live_session():
    """``(scene, session)``: a local app with the story active (``receipts_active``) and one run, started over HTTP."""
    from engine.scenes.default_scene import create_app

    scene, app = create_app(testing=True)
    opened = app.test_client().post("/api/game/new", json={"seed": 3})
    assert opened.status_code == 200, opened.get_data(as_text=True)
    return scene, scene.store.require(opened.get_json()["session_id"])


def _phone(scene, session, action: str, target: str = "", args: dict | None = None, text: str = "") -> dict[str, Any]:
    """One phone action over ``POST /api/phone/action``: the turn payload (asserted 200)."""
    resp = scene.app.test_client().post("/api/phone/action", json={
        "session_id": session.session_id, "action": action, "target": target, "args": args or {}, "text": text})
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return resp.get_json()


def _matched_in(session, app: str) -> str:
    """
    A mutual match on ``app`` in a live session's state, made the real way (``matched``'s):
    the top card liked with the like-back forced true for that one like, then the clock
    advanced exactly to its ``see_like``. Made holding the session's turn lock.
    """
    from engine.game import clock
    from engine.session.store import release_turn
    from engine.social import matching

    state = session.engine.state
    assert session.lock.acquire(blocking=False)
    real = matching.likes_back
    try:
        matching.likes_back = lambda *a, **k: True
        pid = _top(state, app)
        assert matching.like(state, app, pid)["ok"]
        due = [e for e in state.social["queue"] if e["kind"] == "see_like" and e["pid"] == pid]
        clock.advance_time(state, max(0.0, due[0]["at"] - state.world_clock_hours))
    finally:
        matching.likes_back = real
        release_turn(session)
    tid = matching.thread_id(app, pid)
    assert tid in state.social["threads"]
    return tid


@contextlib.contextmanager
def _replies_forced() -> Iterator[None]:
    """
    For the block, every read answers (v0.22.0 T26): no ghost (the stage term
    of `messaging`'s ghost chance 0) and every reply drawn (the interest term
    of its reply chance far past 1). A test that needs a due message forces
    the draw rather than hunting a seed whose draws happen to give one
    (F16): T26's tuning made a new match ghost and go quiet often.
    """
    from engine.social import messaging

    stage, interest = messaging._stage_factor, messaging._interest_factor
    messaging._stage_factor = lambda stage_: 0.0              # type: ignore[assignment]
    messaging._interest_factor = lambda interest_: 100.0      # type: ignore[assignment]
    try:
        yield
    finally:
        messaging._stage_factor, messaging._interest_factor = stage, interest   # type: ignore[assignment]


def _wait_until(predicate, timeout: float = 2.0) -> None:
    """Poll ``predicate`` every 20 ms; fail when it is still false after ``timeout`` seconds (a bounded wait)."""
    import threading
    import time

    deadline = time.monotonic() + timeout
    tick = threading.Event()
    while not predicate():
        assert time.monotonic() < deadline, f"not true within {timeout} s"
        tick.wait(0.02)


class Started(NamedTuple):
    """One logged-in player with a run open and its socket joined to it."""

    client: Any
    sock: Any
    sid: str
    account_id: str


class HostedReceipts:
    """A hosted READ RECEIPTS app (tests/hosted_app.py) and the one way a test starts playing on it."""

    def __init__(self, hosted: Any) -> None:
        self.hosted = hosted
        self.scene = hosted.scene
        self.app = hosted.app

    @property
    def state(self) -> Any:
        """The app's ``HostingState``."""
        return self.hosted.state

    def login_and_start(self, name: str = "alice") -> Started:
        from tests.hosted_app import login

        account, password = self.hosted.add(name)
        client = self.hosted.client()
        assert login(client, name, password).status_code == 303
        opened = client.post("/api/game/new", json={"seed": 3})
        assert opened.status_code == 200, opened.get_data(as_text=True)
        sid = opened.get_json()["session_id"]
        sock = self.scene.socketio.test_client(self.app, flask_test_client=client)
        assert sock.is_connected()
        sock.emit("join_session", {"session_id": sid})
        sock.get_received()
        return Started(client, sock, sid, account.id)


@pytest.fixture
def hosted_receipts(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[HostedReceipts]:
    """
    READ RECEIPTS served hosted, in this process (Plan decision 19): a temp
    ``_CONFIG_DIR`` whose ``local.yaml`` turns hosting on with
    ``actions_per_minute`` 12 and ``phone_actions_per_minute`` 90,
    ``CLOCKWORK_DATA_DIR`` at ``tmp_path``, the story chosen by
    ``CLOCKWORK_GAME``. No server is bound (the test clients are in-process).
    """
    from engine.games import registry
    from tests.hosted_app import build, teardown

    with _quieted():                    # F2: no pass reaches a model or races the test's own
        try:
            hosted = build(
                monkeypatch,
                tmp_path,
                hosting={"rate_limits": {"actions_per_minute": 12, "phone_actions_per_minute": 90}},
                env={"CLOCKWORK_GAME": "read-receipts"},
            )
            yield HostedReceipts(hosted)
        finally:
            _stop_dirty_saver()
            teardown()
            registry.deactivate()


# -- T18: the phone's media jobs --------------------------------------------


@pytest.fixture
def media_root(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    """
    The storage root's ``media_dir()``, which the conftest has already made a
    per-test temporary directory (``CLOCKWORK_DATA_DIR``): asserted to sit
    under the session's basetemp, never re-patched. The process's media
    worker, if a test built one, is stopped and dropped at the end.
    """
    from engine.media.comfy import storage

    root = storage.media_dir().resolve()
    base = Path(tmp_path_factory.getbasetemp()).resolve()
    assert root.is_relative_to(base), f"media_dir() {root} is not a temporary directory under {base}"
    try:
        yield root
    finally:
        import sys

        jobs = sys.modules.get("engine.media.comfy.jobs")
        if jobs is not None:
            assert jobs.reset_media_worker(10), "the media worker's thread did not end"


def _spec(mid: str, workflow: str, *, priority: int = 0, account: str = "", owner: str = "",
          save_id: str = "s1", values: dict | None = None, created: float = 0.0, reference: bytes | None = None,
          saved: bool = True):
    """
    A ``JobSpec`` for ``mid`` on ``workflow`` (its ``kind`` too), owner-scoped
    as given. With ``saved`` (and plain ids) the save's own folder is made
    under the temporary storage root first: the worker writes media only for
    a save that still exists (review I3).
    """
    from engine.media.comfy.jobs import JobSpec, _save_folder

    spec = JobSpec(mid=mid, kind=workflow, owner=owner, save_id=save_id, session_id="sess-1", epoch=1,
                   workflow=workflow, values=dict(values or {}), priority=priority, account=account,
                   reference=reference, created=created)
    if saved:
        try:
            folder = _save_folder(spec)
        except ValueError:
            return spec
        folder.mkdir(parents=True, exist_ok=True)
    return spec


def _lines(log: Path, prefix: str) -> list[dict[str, Any]]:
    """The loopback stub's request log (``--log``): every record whose path starts with ``prefix``."""
    import json

    if not log.exists():
        return []
    rows = []
    for line in log.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except ValueError:  # a line the stub is still writing
            continue
    return [row for row in rows if str(row.get("path", "")).startswith(prefix)]
