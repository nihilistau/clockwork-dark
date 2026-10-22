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
        _VOICE_SESSIONS.clear()                         # no hand-built voicing session outlives its test (M7)


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
    warmth and trust at 70 (v0.22's ``meeting`` gate, which v0.23.0 T18 removed as unread: a relationship
    well along, as the tests that use it were written against): the pid.
    """
    pid = matched_numbers("texts").split(":", 1)[1]
    _set_person(receipts_state, pid, **WELL_ALONG)
    return pid


#: Warmth and trust of a relationship well along (v0.22's `meeting` gate's values, kept as the fixtures' own).
WELL_ALONG: dict[str, int] = {"warmth": 70, "trust": 70}


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
    gate = dict(gate)
    commitment = gate.pop("willing", None)
    if commitment is not None:                       # a `{willing: <commitment>}` gate (v0.23.0 T5): its row's measures
        from engine import social

        row = social.data("growth")["willing"][commitment]
        for key in ("warmth", "trust"):
            if key in row:
                gate[key] = max(float(gate.get(key, 0)), float(row[key]))
        for key, field in (("episodes", "episodes_done"), ("scenes", "scenes_done")):
            if key in row:
                out[field] = max(0, int(row[key]) + int(offset))
        if "depth" in row:
            depth = max(0, int(row["depth"]) + int(offset))
            out["growth"] = {"depth": depth, "openness": 0.0, "pace": 1.0, "guarded": 0, "guarded_left": 0,
                             "revealed": [], "peak_depth": depth, "reveal_due": ""}
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


def _live_session(llm_fn=None):
    """``(scene, session)``: a local app with the story active (``receipts_active``) and one run, started over HTTP.
    ``llm_fn`` (v0.23.0 T11, pre-flight F2): the app's model function, passed to ``create_app`` BEFORE the run
    is started, so a session that runs a storyteller turn is built with its stub from the start
    (``tests/social_world_stub.py::StubNarrator``)."""
    from engine.scenes.default_scene import create_app

    scene, app = create_app(testing=True, llm_fn=llm_fn)
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
    For the block, every conversation start answers (v0.23.0 T3): the per-episode-start
    draws forced -- no ghost (`convo._ghost_factor` 0), every reply drawn (`convo._reply_factor`
    far past 1) -- and the person always available (`convo.available`), so their read lands at
    the send's minute and no schedule boundary of theirs moves a read. A test that needs a due
    message forces the draw rather than hunting a seed whose draws happen to give one (F16).
    """
    from engine.social import convo

    ghost, reply, available = convo._ghost_factor, convo._reply_factor, convo.available
    convo._ghost_factor = lambda state, pid: 0.0                           # type: ignore[assignment]
    convo._reply_factor = lambda state, pid: 100.0                         # type: ignore[assignment]
    convo.available = lambda state, pid, at: convo.Availability(True)      # type: ignore[assignment]
    try:
        yield
    finally:
        convo._ghost_factor, convo._reply_factor, convo.available = ghost, reply, available  # type: ignore[assignment]


def _open_episode(state, pid: str, thread: str, *, target: int = 20) -> dict[str, Any]:
    """An episode opened with ``pid`` in ``thread`` at the current hour, through ``social_episode``
    ``op: open``, its target length forced to ``target`` (20) for the call: the episode row."""
    from engine.game.effects import apply_effect
    from engine.social import convo

    real = convo._target_draw
    convo._target_draw = lambda state_, pid_, rng: target                  # type: ignore[assignment]
    try:
        done = apply_effect(state, {"type": "social_episode", "op": "open", "pid": pid, "thread_id": thread,
                                    "at": state.world_clock_hours, "kind": "chat"})
    finally:
        convo._target_draw = real                                          # type: ignore[assignment]
    assert done["ok"], done
    return state.social["people"][pid]["episode"]


class _KeepsNothing:
    """A save store that writes nothing (the simulator's, Plan decision 28): no file, no timer, no thread."""

    keeps_nothing = True

    def save(self, state: Any, **_: Any) -> str:
        return ""


#: id(state) -> (state, session): ``_voice_all``'s hand-built sessions, one per state.
_VOICE_SESSIONS: dict[int, tuple[Any, Any]] = {}


def _voice_all(state, stub) -> int:
    """
    Voice every due message in ``state`` with ``stub`` (a ``StubVoice``), synchronously: a hand-built
    session over ``state`` in a ``SessionStore`` that keeps nothing (as the simulator's ``Phone``),
    then ``voicer.run_until_quiet``. The passes run.
    """
    from engine.scenes.default_state import SessionStore
    from engine.social import voicer

    held = _VOICE_SESSIONS.get(id(state))
    if held is None or held[0] is not state:
        keeps = _KeepsNothing()
        # Built over THIS state (the store's own builder, which `create` and `resume` use), so the
        # pass's generation check finds it live in its own store (Plan decision 28).
        session = SessionStore(save_store=lambda: keeps)._build(state, llm_fn=lambda m, **k: "{}", saves=keeps)
        _VOICE_SESSIONS.clear()
        _VOICE_SESSIONS[id(state)] = (state, session)
        held = _VOICE_SESSIONS[id(state)]
    return voicer.run_until_quiet(held[1], stub)


def _scripted_episode(state) -> list[tuple[Any, ...]]:
    """
    A match on Matchstick (the like-back forced), an open episode and eight sends, each reply voiced
    by ``StubVoice("zero")`` before the next: ``(message id, at, decision mode, decision end)`` for
    every message of the thread, in order. Every draw forced (``_replies_forced``); the replay test
    runs it twice from one seed.
    """
    from engine.game import clock
    from engine.social import matching
    from tests.social_stub import StubVoice

    real = matching.likes_back
    matching.likes_back = lambda *a, **k: True
    try:
        pid = _top(state, "matchstick")
        assert matching.like(state, "matchstick", pid)["ok"]
        due = [e for e in state.social["queue"] if e["kind"] == "see_like" and e["pid"] == pid]
        clock.advance_time(state, max(0.0, due[0]["at"] - state.world_clock_hours))
    finally:
        matching.likes_back = real
    thread = matching.thread_id("matchstick", pid)
    from engine.social import convo

    boundary = convo.boundary_minutes
    convo.boundary_minutes = lambda state_, pid_, at: None             # type: ignore[assignment]  (M3)
    try:
        with _replies_forced():
            _open_episode(state, pid, thread)
            for i in range(8):
                assert _act(state, "send", target=thread, args={"kind": "text"},
                            text=f"line {i} about the climb")["success"]
                _voice_all(state, StubVoice("zero"))
    finally:
        convo.boundary_minutes = boundary                                # type: ignore[assignment]
    return [(m["id"], m["at"], (m.get("decision") or {}).get("mode"), (m.get("decision") or {}).get("end"))
            for m in state.social["threads"][thread]["messages"]]


@contextlib.contextmanager
def _scene_forced() -> Iterator[None]:
    """
    For the block, every draw on the way into a scene is forced (v0.23.0 T13, pre-flight F16): willing to
    meet, available now with no boundary in sight, no flake, the prior's draw 0, and the person already at the
    plan's place when it is made (`plans._arrival`, v0.23.0 T23C: no travel, no lateness) -- so a scene opens on
    arrival and closes only by its moves or its closers, whatever the seed's schedule. The moments' own
    draws are left to the test.
    """
    from engine.social import convo, growth, plans, scene

    saved = (growth.willing, convo.available, convo.boundary_minutes, plans._flake_drawn, scene._prior_draw,
             plans._arrival)
    real = growth.willing
    growth.willing = lambda s, p, c: (True, "") if c == "meet" else real(s, p, c)   # type: ignore[assignment]
    convo.available = lambda s, p, at: convo.Availability(True)                       # type: ignore[assignment]
    convo.boundary_minutes = lambda s, p, at: None                                     # type: ignore[assignment]
    plans._flake_drawn = lambda s, p: False                                            # type: ignore[assignment]
    scene._prior_draw = lambda s, p: 0.0                                               # type: ignore[assignment]
    plans._arrival = there_already                                                     # type: ignore[assignment]
    try:
        yield
    finally:
        (growth.willing, convo.available, convo.boundary_minutes, plans._flake_drawn,   # type: ignore[assignment]
         scene._prior_draw, plans._arrival) = saved


def there_already(state, row, effect, at):
    """`plans._arrival` forced (v0.23.0 T23C): the person is at the plan's place the moment it is made, so a test
    that goes there opens the scene on arrival, as before arrival times existed."""
    return at, at


#: The fixed order of `_scripted_scene`'s five moves (`<their topic>` is their first small-talk topic).
SCRIPTED_MOVES: tuple[str, ...] = ("ask_about:<their topic>", "tell_about:work", "playful", "quiet",
                                   "ask_about:<their topic>")


def _scripted_scene(seed: int) -> list[tuple[Any, ...]]:
    """
    A fresh state from ``seed``: a Matchstick match (the like-back forced), stage `numbers`, a `now` plan for
    drinks at The Anchor, the walk there from Merrow Street (the scene opens), then the five moves of
    ``SCRIPTED_MOVES`` in order, each drawn for real: ``(move, band, round(score, 6))`` for every moment
    played, in order (the scene may close before the fifth). Every draw on the way in is forced
    (``_scene_forced``); the replay test runs it twice from one seed.
    """
    from engine.game import clock, procgen
    from engine.social import growth, matching, plans, scene, world
    from engine.social.kinds import collecting

    state = procgen.new_game_state(player_name="Sam", seed=seed)
    real = matching.likes_back
    matching.likes_back = lambda *a, **k: True
    try:
        pid = _top(state, "matchstick")
        assert matching.like(state, "matchstick", pid)["ok"]
        due = [e for e in state.social["queue"] if e["kind"] == "see_like" and e["pid"] == pid]
        clock.advance_time(state, max(0.0, due[0]["at"] - state.world_clock_hours))
    finally:
        matching.likes_back = real
    out: list[tuple[Any, ...]] = []
    with _scene_forced():
        _force_stage(state, pid, "numbers")
        state.social["phone_up"] = False
        assert plans.make(state, pid, kind="drinks", when="now", venue="the_anchor")
        state.location_id = "merrow_street"
        world.go(state, "the_anchor")
        assert scene.current(state).get("pid") == pid
        topic = str(growth.topics_of(state, pid, up_to=0)[0]["id"])
        for target in SCRIPTED_MOVES:
            if not scene.current(state).get("pid"):
                break
            with collecting() as applied:
                result = scene.move(state, target.replace("<their topic>", topic))
            moment = next(r for r in applied if r.get("type") == "social_scene" and "score" in r)
            out.append((result["move"], moment["band"], round(float(moment["score"]), 6)))
    return out


def _wait_until(predicate, timeout: float = 2.0) -> None:
    """Poll ``predicate`` every 20 ms; fail when it is still false after ``timeout`` seconds (a bounded wait)."""
    import threading
    import time

    deadline = time.monotonic() + timeout
    tick = threading.Event()
    while not predicate():
        assert time.monotonic() < deadline, f"not true within {timeout} s"
        tick.wait(0.02)


def hold_world(session, *, timeout: float, acquired=None, until=None) -> bool:
    """
    The WORLD side's test double (v0.23.0 T8), kept only where a test needs a world turn HELD open for
    as long as it likes (two sessions' turnstiles held while a third's pass runs); T11 retired it from
    `test_a_world_turn_waits_at_most_one_call`, which runs a real `run_guarded` world turn:
    ``turnstile.of(session).acquire_world(timeout)``; on success ``acquired`` is set (if
    given), ``until`` waited on (a bounded ``wait(5)``, if given), then ``WORLD`` released. Whether
    it got the turnstile.
    """
    from engine.social import turnstile

    gate = turnstile.of(session)
    if not gate.acquire_world(timeout):
        return False
    try:
        if acquired is not None:
            acquired.set()
        if until is not None:
            assert until.wait(5), "hold_world: never told to let go"
    finally:
        gate.release(turnstile.WORLD)
    return True


def _due_in(session, count: int) -> list[str]:
    """
    ``count`` mutual matches on Matchstick in a live session, each with an open chat episode and ONE
    due reply (a send answered at its own minute: every draw forced, no schedule edge). The episodes
    and sends are made holding the session's turn lock, released through ``release_turn``. Their
    threads, in match order.
    """
    from engine.session.store import release_turn
    from engine.social import convo, messaging

    threads = [_matched_in(session, "matchstick") for _ in range(count)]
    assert len({t.split(":")[1] for t in threads}) == count, threads
    state = session.engine.state
    boundary = convo.boundary_minutes
    convo.boundary_minutes = lambda state_, pid_, at: None             # type: ignore[assignment]  (M3)
    assert session.lock.acquire(blocking=False)
    try:
        with _replies_forced():
            for i, thread in enumerate(threads):
                _open_episode(state, thread.split(":")[1], thread)
                assert _act(state, "send", target=thread, args={"kind": "text"}, text=f"hey {i}, how was today?")[
                    "success"]
    finally:
        convo.boundary_minutes = boundary                                # type: ignore[assignment]
        release_turn(session)
    due = {m["thread_id"] for m in messaging.unvoiced(state)}
    assert due == set(threads), (due, threads)
    return threads


def _three_due(session) -> list[str]:
    """Three people, each with an open episode and one due reply (``_due_in(session, 3)``)."""
    return _due_in(session, 3)


def _three_due_hosted(hosted: Any, started: Any) -> list[str]:
    """``_three_due`` on the hosted session of ``started`` (it holds the turn lock and releases it through ``release_turn``)."""
    return _three_due(hosted.session(started))


def _offered(hosted: Any, started: Any, text: str) -> str:
    """The ``id`` of the option whose ``text`` is ``text`` in the hosted session's last turn's choices (pre-flight F3:
    the route never reads a client's intent, so a world action goes by an OFFERED option's choice id), asserted to carry an ``intent``."""
    choices = (hosted.session(started).last_turn or {}).get("choices") or []
    found = [c for c in choices if c.get("text") == text]
    assert found, (text, [c.get("text") for c in choices])
    assert found[0].get("intent"), found[0]
    return str(found[0]["id"])


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

    def session(self, started: "Started") -> Any:
        """The live session of ``started``'s run, from the app's store by its ``sid`` (pre-flight F21: ``Started`` has
        no ``session_id`` field), beside ``state``."""
        return self.scene.store.get(started.sid, owner=started.account_id)

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


# -- v0.23.0 T20: a recorded v0.22.0 save resumed by each route ---------------


def _resume_by(route: str, store: Any, save_id: str, tmp_path: Path) -> dict[str, Any]:
    """
    The save ``save_id`` of ``store`` (a ``SaveStore``) resumed through ``route`` (spec §16.3 step 1);
    what that route hands back first:

    - ``local_resume``: a local ``SessionStore`` over ``store``, ``resume`` (its first payload);
    - ``hosted_resume``: a hosted app (tests/hosted_app.py, as ``hosted_receipts`` builds it, under
      ``tmp_path / "hosted"``), one account logged in, the save copied into that account's save folder
      and ``POST /api/saves/<id>/load`` (its JSON);
    - ``save_store_direct``: ``store.load``, then ``GameState.to_client_dict()``.

    Every session built is ended, and the hosted app torn down, before it returns.
    """
    import shutil

    if route == "save_store_direct":
        state, _ = store.load(save_id)
        return state.to_client_dict()
    if route == "local_resume":
        from engine.scenes.default_state import SessionStore

        sessions = SessionStore(save_store=lambda: store)
        session = sessions.resume(save_id, llm_fn=lambda messages, **kw: "{}")
        try:
            return dict(session.last_turn or {})
        finally:
            sessions.end(session.session_id)
    if route == "hosted_resume":
        from engine.persistence.saves import save_store_for
        from tests.hosted_app import build, login, teardown

        with pytest.MonkeyPatch.context() as mp:
            try:
                hosted = build(mp, tmp_path / "hosted",
                               hosting={"rate_limits": {"actions_per_minute": 12, "phone_actions_per_minute": 90}},
                               env={"CLOCKWORK_GAME": "read-receipts"})
                account, password = hosted.add("alice")
                client = hosted.client()
                assert login(client, "alice", password).status_code == 303
                target = Path(save_store_for(account.id, "read-receipts").path_for(save_id))
                target.mkdir(parents=True, exist_ok=True)
                for child in Path(store.path_for(save_id)).iterdir():
                    shutil.copy(child, target / child.name)
                resp = client.post(f"/api/saves/{save_id}/load")
                assert resp.status_code == 200, resp.get_data(as_text=True)
                body = resp.get_json()
                hosted.scene.store.end(str(body.get("session_id") or ""))
                return body
            finally:
                _stop_dirty_saver()
                teardown()
    raise ValueError(f"_resume_by: no route {route!r}")
