"""
The per-session narration turnstile, voice side (v0.23.0 T8; spec §20.1 N1, N3, m10; Plan decision 3).

A voice pass holds the turnstile for ONE model call at a time and only ever TRIES it; a world turn
waits for it (bounded) before the turn lock, so it waits at most one call. Every interleaving a test
depends on is forced with events; nothing sleeps for timing. The world side is a real `run_guarded`
world turn (T11), except where a test needs world turns HELD open (the `hold_world` double).
"""

from __future__ import annotations

import threading

import pytest

from tests.social_fixtures import (  # noqa: F401
    _act, _matched_in, _open_episode, _replies_forced, _wait_until, hold_world, receipts_active,
)


def test_a_voice_pass_defers_while_a_world_turn_waits_or_holds() -> None:
    from engine.social.turnstile import VOICE, WORLD, Turnstile

    gate = Turnstile()
    assert gate.acquire_world(0.1)
    assert gate.try_acquire_voice() is False
    gate.release(WORLD)
    assert gate.try_acquire_voice() is True
    waiting = threading.Event()

    def world() -> None:
        waiting.set()
        assert gate.acquire_world(2.0)
        gate.release(WORLD)

    t = threading.Thread(target=world)
    t.start()
    waiting.wait(1.0)
    _wait_until(lambda: gate.world_waiting == 1)
    gate.release(VOICE)
    t.join(2.0)
    assert not t.is_alive() and gate.holder is None
    assert gate.try_acquire_voice() is True                    # free again, nobody waiting
    gate.release(VOICE)


def test_a_world_wait_times_out_and_a_wrong_release_is_refused() -> None:
    from engine.social.turnstile import VOICE, WORLD, Turnstile

    gate = Turnstile()
    assert gate.try_acquire_voice()
    assert gate.acquire_world(0.0) is False                   # bounded: never held silently
    assert gate.world_waiting == 0
    with pytest.raises(RuntimeError):
        gate.release(WORLD)
    gate.release(VOICE)
    assert gate.held_seconds[VOICE] >= 0.0 and gate.holder is None


def test_a_world_turn_waits_at_most_one_call(receipts_active) -> None:
    """§20.1: a world turn arriving during a 3-person pass waits for ONE reply; the other two defer, then
    complete. The world side is a real `run_guarded` world turn (T11; `hold_world` retired here), its
    session built with its storyteller stub from the start (F2) and the engine-offered intent (F3)."""
    from engine.scenes.default_scene import run_guarded
    from engine.social import voicer
    from engine.social.voicer import VoicePass
    from tests.social_fixtures import _live_session, _phone, _three_due
    from tests.social_stub import StubVoice
    from tests.social_world_stub import StubNarrator

    scene, session = _live_session(llm_fn=StubNarrator())
    _three_due(session)                                        # three people, one due reply each
    _phone(scene, session, "put_down")
    release = threading.Event()
    stub = StubVoice("zero", block=release)
    outcome: list[str] = []
    t = threading.Thread(target=lambda: outcome.append(voicer.run_pass(VoicePass(session, session.epoch),
                                                                        llm_fn=stub, admit=False)))
    t.start()
    _wait_until(lambda: stub.calls == 1)
    turn: list = []
    w = threading.Thread(target=lambda: turn.append(run_guarded(session, "Tidy up",
                                                                {"action": "do", "target": "tidy_up"})))
    w.start()
    _wait_until(lambda: session.narration_turnstile.world_waiting == 1)
    release.set()                                              # the one in-flight call finishes
    t.join(5.0)
    w.join(10.0)
    assert not t.is_alive() and not w.is_alive()
    assert outcome == ["deferred"] and stub.calls == 1         # the pass deferred the other two
    payload, error, busy = turn[0]
    assert payload is not None and not error and not busy, error
    assert session.narration_turnstile.holder is None
    voicer.run_until_quiet(session, StubVoice("zero"))         # (the turn's own request: the scheduler is paused)
    assert not voicer.pending(session)


def test_a_free_pass_voices_one_person_per_call_and_holds_nothing_after(receipts_active) -> None:
    """With the turnstile free, a 3-person pass makes three calls, one person each, taking and releasing
    the turnstile around every call (it is free between and after them)."""
    from engine.social import messaging, voicer
    from engine.social.voicer import VoicePass
    from tests.social_fixtures import _live_session, _three_due
    from tests.social_stub import StubVoice

    scene, session = _live_session()
    threads = _three_due(session)
    gate = session.narration_turnstile
    holders: list[object] = []
    stub = StubVoice("zero")

    def voice(messages, fmt):
        holders.append(gate.holder)
        return stub(messages, fmt)

    p = VoicePass(session, session.epoch)
    assert voicer.run_pass(p, llm_fn=voice, admit=False) == "ok"
    assert holders == ["voice"] * 3 and gate.holder is None
    assert p.voiced_people == {t.split(":")[1] for t in threads}
    assert not messaging.unvoiced(session.engine.state) and not session.voicing


def test_run_until_quiet_stops_on_a_deferral(receipts_active) -> None:
    """Pre-flight F17: a held turnstile defers the first pass, and `run_until_quiet` returns at once."""
    from engine.social import voicer
    from tests.social_fixtures import _due_in, _live_session
    from tests.social_stub import StubVoice

    scene, session = _live_session()
    _due_in(session, 1)
    gate = session.narration_turnstile
    assert gate.acquire_world(0.1)
    try:
        stub = StubVoice("zero")
        assert voicer.run_until_quiet(session, stub) == 1
        assert stub.calls == 0 and voicer.pending(session)
    finally:
        gate.release("world")


def test_a_deferral_is_not_an_attempt(receipts_active, monkeypatch) -> None:
    from engine.social import voicer
    from engine.social.voicer import VoicePass, VoicingScheduler
    from tests.social_fixtures import _live_session

    scene, session = _live_session()
    sched = VoicingScheduler(workers=0)
    p = VoicePass(session, session.epoch)
    sched._in_flight[p.key] = p
    sched._after(p, "deferred")
    assert p.attempts == 0 and p.deferrals == 1 and p.key in sched._queued
    assert "deferred" in voicer.OUTCOMES


def test_voice_pass_never_blocks_a_scheduler_thread(receipts_active, monkeypatch) -> None:
    """§20.1 N3: two sessions in a world turn (the double holding each turnstile) while a third session's
    pass runs to completion on a 2-worker scheduler: no worker waited on a turnstile. The hosted variant
    lands in T28."""
    from engine.social import messaging, voicer
    from tests.social_fixtures import _due_in, _live_session

    sessions = []
    for _ in range(3):
        _scene, s = _live_session()
        _due_in(s, 1)
        sessions.append(s)
    held = [threading.Event(), threading.Event()]
    done = threading.Event()
    worlds = [threading.Thread(target=hold_world, args=(s,), kwargs={"timeout": 5.0, "acquired": e, "until": done})
              for s, e in zip(sessions[:2], held)]
    sched = voicer.VoicingScheduler(workers=2)
    try:
        for w in worlds:
            w.start()
        assert all(e.wait(5.0) for e in held)                 # both world turns hold their turnstiles
        for s in sessions:
            sched.request(s)
        _wait_until(lambda: not messaging.unvoiced(sessions[2].engine.state), timeout=10.0)
        assert all(messaging.unvoiced(s.engine.state) for s in sessions[:2])   # deferred, never voiced
        assert all(not s.voicing for s in sessions[:2])                         # nothing marked for them
        done.set()
        for w in worlds:
            w.join(5.0)
        _wait_until(lambda: not any(messaging.unvoiced(s.engine.state) for s in sessions[:2]), timeout=10.0)
    finally:
        done.set()
        sched.stop()


def _drive_until_dropped(session, monkeypatch) -> tuple[object, list[str]]:
    """Run one session's pass through a worker-less scheduler with `admit_turn` always busy, until the
    scheduler drops it after `social.voice.max_attempts` (its fake clock jumped past each backoff)."""
    from engine import social
    from engine.llm import gate
    from engine.social import voicer
    from tests.social_stub import StubVoice

    def busy(**_: object) -> None:
        raise gate.InferenceBusy("test: no slot", reason="busy")

    monkeypatch.setattr(gate, "admit_turn", busy)
    clock = [0.0]
    sched = voicer.VoicingScheduler(workers=0, time_fn=lambda: clock[0])
    stub = StubVoice("zero")
    outcomes: list[str] = []
    limit = int(social.setting("voice.max_attempts", 6))
    sched.request(session)                                     # queued; no worker runs it (the test's monkeypatch)
    for _ in range(limit):
        clock[0] += 1000.0
        p, _wait = sched._next()
        assert p is not None
        outcome = voicer.run_pass(p, llm_fn=stub, admit=True)
        outcomes.append(outcome)
        sched._after(p, outcome)
    assert stub.calls == 0
    return sched, outcomes


def test_an_open_episodes_reply_is_never_silent_after_max_attempts(receipts_active, monkeypatch) -> None:
    """§20.1's last bullet: a pass for an OPEN episode dropped after `max_attempts` busy admissions commits
    the templated fallback (§13.1) -- the reply is never silent."""
    from engine.social import messaging, voicer
    from tests.social_fixtures import _due_in, _live_session

    monkeypatch.setattr(voicer.VoicingScheduler, "_start_workers", lambda self: None)   # driven by hand
    scene, session = _live_session()
    (thread,) = _due_in(session, 1)
    sched, outcomes = _drive_until_dropped(session, monkeypatch)
    assert outcomes == ["busy"] * len(outcomes)
    assert not sched._queued                                   # dropped, not re-queued
    theirs = [m for m in session.engine.state.social["threads"][thread]["messages"] if m["from"] not in ("player", "system")]
    assert theirs and theirs[-1]["voiced"] == "fallback"
    assert not messaging.unvoiced(session.engine.state)
    assert not session.voicing


def test_open_fallbacks_park_in_the_inbox_while_the_lock_is_busy(receipts_active, monkeypatch) -> None:
    """A busy turn lock parks the open-episode fallbacks in the inbox; the lock's next holder applies them."""
    from engine.llm.gate import CancelToken
    from engine.session.store import release_turn
    from engine.social import messaging, voicer
    from tests.social_fixtures import _due_in, _live_session

    monkeypatch.setattr(voicer, "_retry_ms", lambda: [1])
    scene, session = _live_session()
    (thread,) = _due_in(session, 1)
    assert session.lock.acquire(blocking=False)
    try:
        assert voicer.commit_open_fallbacks(session, cancel=CancelToken()) == 0
        assert [i["kind"] for i in session.inbox.drain()] == ["open_fallback"]
        voicer.commit_open_fallbacks(session, cancel=CancelToken())            # parked again
        assert voicer.drain_inbox(session) == 1                                 # applied by the lock's holder
    finally:
        release_turn(session)
    assert not messaging.unvoiced(session.engine.state)
    theirs = [m for m in session.engine.state.social["threads"][thread]["messages"] if m["from"] not in ("player", "system")]
    assert theirs[-1]["voiced"] == "fallback"


def test_no_open_fallback_for_a_person_with_no_open_episode(receipts_active, monkeypatch) -> None:
    """Only an OPEN episode's reply is forced out: a due message of someone with no episode stays due."""
    from engine.session.store import release_turn
    from engine.social import messaging, voicer
    from tests.social_fixtures import _due_in, _live_session, _set_person

    scene, session = _live_session()
    (thread,) = _due_in(session, 1)
    state = session.engine.state
    pid = thread.split(":")[1]
    assert session.lock.acquire(blocking=False)
    try:
        _set_person(state, pid, episode=None)                     # no open episode
        assert voicer._open_fallbacks(session, "attempts") == 0
    finally:
        release_turn(session)
    assert messaging.unvoiced(state)


def test_no_turnstile_for_a_story_without_paths_social(monkeypatch) -> None:
    """Seam pin 9 (m10), the session half: parametrized over every other story in tests/test_social_seam.py."""
    from engine.games import registry
    from engine.session.store import SessionStore

    registry.activate("dev-story")
    try:
        store = SessionStore()
        session = store.create(seed=1)
        assert session.narration_turnstile is None
    finally:
        registry.deactivate()


def test_a_read_receipts_session_is_built_with_its_turnstile(receipts_active) -> None:
    from engine.social.turnstile import NULL, Turnstile, of
    from tests.social_fixtures import _live_session

    scene, session = _live_session()
    assert isinstance(session.narration_turnstile, Turnstile)
    assert of(session) is session.narration_turnstile
    assert of(object()) is NULL and NULL.acquire_world(0) and NULL.try_acquire_voice()


def test_the_lock_order_holds_turnstile_before_turn_lock(receipts_active, monkeypatch) -> None:
    from tests import lock_order
    from tests.social_fixtures import _live_session

    checker = lock_order.install(monkeypatch)
    lock_order.install_turnstile(monkeypatch, checker)
    scene, session = _live_session()
    lock_order.track_turn_lock(session, checker)
    gate = session.narration_turnstile
    assert gate.acquire_world(0.1)
    assert session.lock.acquire(blocking=False)
    session.lock.release()
    gate.release("world")
    assert not checker.violations
    assert session.lock.acquire(blocking=False)
    gate.try_acquire_voice()                                   # under a turn lock: a violation, even a try
    session.lock.release()
    assert any("turnstile while holding a turn lock" in v for v in checker.violations)


def test_the_checker_names_a_turn_lock_under_a_listed_lock_and_never_raises(monkeypatch) -> None:
    """Pre-flight F38: `TURN` and `TURNSTILE` are not in RANK; the checker records a violation, no KeyError."""
    from tests import lock_order

    checker = lock_order.Checker()
    listed = lock_order.ORDER[0]                               # any lock of the numbered list
    checker.push(listed)
    checker.before(lock_order.TURN, blocking=False)           # must not raise KeyError
    assert any("took a turn lock while holding" in v for v in checker.violations)
    checker.pop(listed)


# -- fix round 1 (review M1-M3, M6, M7) ----------------------------------------------------------------


def test_people_voiced_earlier_in_the_pass_are_not_counted_as_more(receipts_active) -> None:
    """M1: a per-call snapshot passes over a person this pass already voiced (they wait for the next
    pass: `rerun`) WITHOUT counting them in `p.more`, so the commit of the last one due is the pass's
    last and saves."""
    from engine.session.store import release_turn
    from engine.social import voicer
    from tests.social_fixtures import _due_in, _live_session

    scene, session = _live_session()
    first, second = _due_in(session, 2)
    p = voicer.VoicePass(session, session.epoch)
    p.voiced_people = {first.split(":")[1]}
    assert session.lock.acquire(blocking=False)
    try:
        (snap,) = voicer.snapshot(session, p, limit=1)
    finally:
        release_turn(session)
    assert snap.thread_id == second
    assert p.more == 0 and p.rerun is True
    assert voicer._more_due_unlocked(session, p) is False


def test_a_busy_after_a_commit_is_not_an_attempt_and_its_commits_are_reported(receipts_active,
                                                                             monkeypatch) -> None:
    """M2: admission is per call, so a pass that committed one reply and then found the queue busy made
    progress: its commits are reported, and the scheduler does not count the busy as an attempt."""
    from engine.llm import gate
    from engine.social import voicer
    from tests.social_fixtures import _live_session, _three_due
    from tests.social_stub import StubVoice

    scene, session = _live_session()
    _three_due(session)

    class _Admitted:
        def release(self) -> None:
            return None

    asked: list[int] = []

    def admit(**_: object) -> object:
        asked.append(1)
        if len(asked) > 1:
            raise gate.InferenceBusy("test: no slot", reason=gate.BUSY)
        return _Admitted()

    monkeypatch.setattr(gate, "admit_turn", admit)
    reports: list[str] = []
    monkeypatch.setattr(voicer, "_report_pass", lambda _s, status, ms=0.0: reports.append(status))
    monkeypatch.setattr(voicer.VoicingScheduler, "_start_workers", lambda self: None)   # driven by hand
    sched = voicer.VoicingScheduler(workers=0)
    p = voicer.VoicePass(session, session.epoch)
    p.attempts = 3
    sched._in_flight[p.key] = p
    outcome = voicer.run_pass(p, llm_fn=StubVoice("zero"), admit=True)
    assert outcome == "busy" and p.statuses == ["ok"]
    assert reports == ["ok"]                                   # the pass's one commit, reported
    sched._after(p, outcome)
    assert p.attempts == 0 and p.key in sched._queued          # progress: not a failed attempt
    assert reports == ["ok"]                                   # no `busy` metric for a pass that committed


def test_the_admitted_path_asks_no_ticket_for_a_person_already_voiced(receipts_active, monkeypatch) -> None:
    """M3: when the only due messages are of people this pass already voiced, a call asks no ticket."""
    from engine.llm import gate
    from engine.social import voicer
    from tests.social_fixtures import _due_in, _live_session
    from tests.social_stub import StubVoice

    scene, session = _live_session()
    (thread,) = _due_in(session, 1)

    def admit(**_: object) -> object:
        raise AssertionError("asked a ticket it could not use")

    monkeypatch.setattr(gate, "admit_turn", admit)
    p = voicer.VoicePass(session, session.epoch)
    p.voiced_people = {thread.split(":")[1]}
    p.deadline = float("inf")
    assert voicer._one_call(p, llm_fn=StubVoice("zero"), admit=True, store=None) == "empty"


def test_a_call_that_proceeds_resets_the_deferrals(receipts_active) -> None:
    """M6: once a call takes the turnstile, the pass's deferral count starts again from the first step."""
    from engine.social import voicer
    from tests.social_fixtures import _live_session
    from tests.social_stub import StubVoice

    scene, session = _live_session()
    p = voicer.VoicePass(session, session.epoch)
    p.deferrals = 4
    voicer.run_pass(p, llm_fn=StubVoice("zero"), admit=False)
    assert p.deferrals == 0


def test_the_deadline_fallbacks_run_even_when_the_recap_step_defers(receipts_active, monkeypatch) -> None:
    """M7: past its deadline a pass answers every open episode with its fallback, also when a world turn
    took the turnstile before the recap step (the pass then still answers `deferred`)."""
    from engine import social
    from engine.social import messaging, voicer
    from tests.social_fixtures import _due_in, _live_session, _with
    from tests.social_stub import StubVoice

    scene, session = _live_session()
    threads = _due_in(session, 2)
    monkeypatch.setattr(social, "setting", _with(social.setting, **{"voice.pass_deadline_seconds": 0,
                                                                    "voice.max_per_pass": 1}))

    class _OneCallThenWorld:
        """Free for the pass's one call; a world turn has it by the recap step."""

        holder = None
        world_waiting = 0
        tries = 0

        def try_acquire_voice(self) -> bool:
            self.tries += 1
            return self.tries == 1

        def release(self, who: str) -> None:
            return None

    session.narration_turnstile = _OneCallThenWorld()
    stub = StubVoice("zero")
    assert voicer.run_pass(voicer.VoicePass(session, session.epoch), llm_fn=stub, admit=False) == "deferred"
    assert stub.calls == 0                                     # past the deadline: no model call at all
    assert not messaging.unvoiced(session.engine.state)
    for thread in threads:
        pid = thread.split(":")[1]
        theirs = [m for m in session.engine.state.social["threads"][thread]["messages"] if m["from"] == pid]
        assert theirs[-1]["voiced"] == "fallback", thread


def test_a_failed_share_report_is_logged_not_swallowed(monkeypatch, caplog) -> None:
    """(v0.24.0 T14 c11) `report_share` never raises (a metric must not fail a turn), but a failure is logged at
    warning with its exception; before, `except Exception: pass` hid it."""
    import logging
    from types import SimpleNamespace

    from engine.social import turnstile

    class Broken:
        def take_share(self, interval):
            raise RuntimeError("share-sentinel-7f3a")

    session = SimpleNamespace(narration_turnstile=Broken())
    with caplog.at_level(logging.WARNING, logger="engine.social.turnstile"):
        turnstile.report_share(session)                      # does not raise
    logged = [r for r in caplog.records if r.name == "engine.social.turnstile" and r.levelno == logging.WARNING]
    assert logged and logged[0].exc_info and "share-sentinel-7f3a" in str(logged[0].exc_info[1])
