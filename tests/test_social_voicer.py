"""The voicing pass (spec §16.2-16.5, §19.4): bound to the session OBJECT and its epoch."""

from __future__ import annotations

import gc
import json
import logging
import threading
import weakref
from typing import Any

import pytest

from tests.social_fixtures import (  # noqa: F401
    _at,
    _force_stage,
    _live_session,
    _matched_in,
    _phone,
    _replies_forced,
    _set_person,
    _top,
    _wait_until,
    _with,
    receipts_active,
)
from tests.social_stub import StubVoice


def _due(scene, session, thread) -> None:
    with _replies_forced():                    # their reply drawn, never a ghost (T26's tuning: F16)
        _phone(scene, session, "send", target=thread, args={"kind": "text"}, text="hey you")
        _phone(scene, session, "wait", args={"until": "next"})
    from engine.social import messaging

    assert messaging.unvoiced(session.engine.state)


def _start_pass(session, stub):
    from engine.social import voicer

    p = voicer.VoicePass(session, session.epoch)
    out: dict = {}
    t = threading.Thread(target=lambda: out.setdefault("r", voicer.run_pass(p, llm_fn=stub, admit=False)))
    t.start()
    return p, t, out


def _theirs(session, thread) -> list[dict[str, Any]]:
    t = session.engine.state.social["threads"].get(thread, {"messages": []})
    return [m for m in t["messages"] if m["from"] not in ("player", "system")]


def _force_idle(scene, session, monkeypatch) -> None:
    """The run's idle stamp pushed past any TTL, and the CONFIG key `session.idle_sweep_enabled` answered true."""
    from engine import config

    real = config.get_config

    class _Layer:
        def __init__(self, cfg: Any) -> None:
            self._cfg = cfg

        def get(self, key: str, default: Any = None) -> Any:
            return True if key == "session.idle_sweep_enabled" else self._cfg.get(key, default)

        def __getattr__(self, name: str) -> Any:
            return getattr(self._cfg, name)

    monkeypatch.setattr(config, "get_config", lambda: _Layer(real()))
    scene.store._seen[session.session_id] = 0.0


def _reply_json(text: str, **extra: Any) -> str:
    body = {"bubbles": [{"text": text}], "regard": {"warmth": 0, "trust": 0, "mood": "neutral"},
            "learned": [], "shared": []}
    body.update(extra)
    return json.dumps(body)


# -- the brief's written-out tests ------------------------------------------------------------------


def test_a_send_during_a_pass_is_accepted(receipts_active) -> None:
    scene, session = _live_session()
    thread = _matched_in(session, "matchstick")
    _due(scene, session, thread)
    gate = threading.Event()
    stub = StubVoice("zero", block=gate)
    p, t, out = _start_pass(session, stub)
    _wait_until(lambda: stub.calls == 1)                       # the call is in flight, no lock held
    body = _phone(scene, session, "send", target=thread, args={"kind": "text"}, text="also hi")
    assert not body.get("busy") and not body["receipts"][0].get("refused")
    gate.set()
    t.join(5)
    assert out["r"] in ("ok", "fallback")


def test_a_reply_after_unmatch_is_discarded(receipts_active) -> None:
    scene, session = _live_session()
    thread = _matched_in(session, "matchstick")
    _due(scene, session, thread)
    gate = threading.Event()
    stub = StubVoice("warm", block=gate)
    p, t, out = _start_pass(session, stub)
    _wait_until(lambda: stub.calls == 1)
    _phone(scene, session, "unmatch", target=thread.split(":")[1])
    gate.set()
    t.join(5)
    assert _theirs(session, thread) and all(not m["bubbles"] for m in _theirs(session, thread))
    assert all(m["voiced"] == "withdrawn" for m in _theirs(session, thread))   # retired, never voiced later
    assert session.voicing == {}                               # its marks went with it


def test_a_local_resume_mid_pass_commits_and_saves_nothing_old(receipts_active) -> None:
    from engine.social import voicer

    scene, old = _live_session()
    thread = _matched_in(old, "matchstick")
    _due(scene, old, thread)
    gate = threading.Event()
    stub = StubVoice("warm", block=gate)
    p, t, out = _start_pass(old, stub)
    _wait_until(lambda: stub.calls == 1)
    new = scene.store.resume(old.save_id)                      # same id, new object, new epoch
    assert new is not old and new.epoch != old.epoch
    gate.set()
    t.join(5)
    assert out["r"] == "cancelled"                             # the generation check ended it
    saved, _ = new.saves.load(new.save_id)
    assert all(m["voiced"] is False for m in saved.social["threads"][thread]["messages"] if m["from"] != "player")
    assert all(m["voiced"] is False for m in _theirs(new, thread))     # nor the new run's live state
    assert voicer.run_until_quiet(new, StubVoice("zero")) >= 1
    assert all(m["voiced"] for m in new.engine.state.social["threads"][thread]["messages"])
    reloaded, _ = new.saves.load(new.save_id)                  # the pass's last commit saved
    assert all(m["voiced"] for m in reloaded.social["threads"][thread]["messages"])


def test_a_sweep_mid_pass_ends_it_and_frees_the_engine(receipts_active, monkeypatch) -> None:
    from engine.social import voicer

    scene, session = _live_session()
    thread = _matched_in(session, "matchstick")
    _due(scene, session, thread)
    gate = threading.Event()
    stub = StubVoice("warm", block=gate)
    p, t, out = _start_pass(session, stub)
    _wait_until(lambda: stub.calls == 1)
    engine_ref = weakref.ref(session.engine)
    _force_idle(scene, session, monkeypatch)                   # its _seen stamp pushed past the TTL
    assert scene.store.sweep_idle(ttl_minutes=1) == [session.session_id]
    gate.set()
    t.join(5)
    assert out["r"] == "cancelled" and voicer.in_flight() == 0
    assert all(not m["bubbles"] for m in _theirs(session, thread))
    # The DirtySaver heap and the scheduler deque may still hold the session: stop both singletons first (F2).
    from engine.social import saves

    voicer.reset()
    saves.reset_dirty_saver()
    del session, p, t, out
    gc.collect()
    assert engine_ref() is None


def test_the_stores_release_cancels_its_scheduled_passes(receipts_active) -> None:
    """Spec §16.5: `SessionStore._release` calls `voicer.forget`, cancelling a pass in flight for a run gone."""
    from engine.social import voicer

    scene, session = _live_session()
    thread = _matched_in(session, "matchstick")
    _due(scene, session, thread)
    gate = threading.Event()
    stub = StubVoice("warm", block=gate)
    voicer.set_llm_fn(stub)
    scheduler = voicer.get_scheduler()
    scheduler.resume()
    voicer.request(session)
    try:
        _wait_until(lambda: stub.calls == 1)
        (p,) = list(scheduler._in_flight.values())
        scene.store.delete(session.session_id)
        assert p.cancel.cancelled
    finally:
        gate.set()
    _wait_until(lambda: voicer.in_flight() == 0)
    assert all(not m["bubbles"] for m in _theirs(session, thread)) and scheduler.queued() == []


# -- the further tests --------------------------------------------------------------------------------


def test_a_save_written_mid_pass_reloads_with_nothing_stuck(receipts_active) -> None:
    from engine.social import saves

    scene, session = _live_session()
    thread = _matched_in(session, "matchstick")
    _due(scene, session, thread)
    gate = threading.Event()
    stub = StubVoice("warm", block=gate)
    p, t, out = _start_pass(session, stub)
    _wait_until(lambda: stub.calls == 1)
    assert session.voicing and session.typing == {thread}      # marked and typing, in memory only
    assert session.lock.acquire(blocking=False)
    try:
        assert saves.save_now(session)
    finally:
        session.lock.release()
    raw = (session.saves.path_for(session.save_id) / "save.json").read_text(encoding="utf-8")
    saved, _ = session.saves.load(session.save_id)
    gate.set()
    t.join(5)

    def keys(tree: Any) -> set[str]:
        if isinstance(tree, dict):
            return set(tree) | {k for v in tree.values() for k in keys(v)}
        if isinstance(tree, list):
            return {k for v in tree for k in keys(v)}
        return set()

    assert not ({"voicing", "typing"} & keys(json.loads(raw)))
    assert all(m["voiced"] is False for m in saved.social["threads"][thread]["messages"] if m["from"] != "player")
    assert out["r"] == "ok" and all(m["voiced"] is True for m in _theirs(session, thread))


def test_a_busy_admission_is_dropped_after_max_attempts(receipts_active, monkeypatch) -> None:
    from engine.llm import gate as llm_gate
    from engine.social import messaging, voicer

    scene, session = _live_session()
    thread = _matched_in(session, "matchstick")
    _due(scene, session, thread)
    asked: list[dict[str, Any]] = []

    def busy(**kwargs: Any) -> Any:
        asked.append(kwargs)
        raise llm_gate.InferenceBusy("no slot", reason=llm_gate.BUSY)

    monkeypatch.setattr(llm_gate, "admit_turn", busy)
    reports: list[str] = []
    monkeypatch.setattr(voicer, "_report_pass", lambda _s, status, ms=0.0: reports.append(status))
    clock = [1000.0]
    slept: list[float] = []

    def sleep(seconds: float) -> None:
        slept.append(seconds)
        clock[0] += seconds

    scheduler = voicer.VoicingScheduler(workers=1, time_fn=lambda: clock[0], sleep_fn=sleep, admit=lambda: True)
    try:
        scheduler.request(session)
        _wait_until(lambda: "dropped" in reports, timeout=10)
    finally:
        scheduler.stop()
    assert len(asked) == 6 and all(a["label"] == "voice" for a in asked)
    assert reports == ["busy"] * 5 + ["dropped"]
    assert slept == [2.0, 4.0, 8.0, 16.0, 32.0]                 # the backoff
    assert messaging.unvoiced(session.engine.state) and session.voicing == {}   # still due, never marked
    assert scheduler.queued() == [] and scheduler.in_flight() == 0


def test_a_deadline_turns_the_rest_into_fallbacks(receipts_active, monkeypatch) -> None:
    from engine import social
    from engine.social import voicer

    scene, session = _live_session()
    thread = _matched_in(session, "matchstick")
    _due(scene, session, thread)
    monkeypatch.setattr(social, "setting", _with(social.setting, **{"voice.pass_deadline_seconds": 0}))
    stub = StubVoice("warm")
    assert voicer.run_pass(voicer.VoicePass(session, session.epoch), llm_fn=stub, admit=False) == "fallback"
    assert stub.calls == 0
    assert _theirs(session, thread) and all(m["voiced"] == "fallback" and m["bubbles"] for m in _theirs(session, thread))


def test_drain_cancels_and_waits_for_passes(receipts_active, monkeypatch) -> None:
    import engine.hosting as hosting
    from engine.social import voicer

    scene, session = _live_session()
    thread = _matched_in(session, "matchstick")
    _due(scene, session, thread)
    gate = threading.Event()
    stub = StubVoice("warm", block=gate)
    voicer.set_llm_fn(stub)
    scheduler = voicer.get_scheduler()
    scheduler.resume()
    voicer.request(session)
    _wait_until(lambda: stub.calls == 1)
    (p,) = list(scheduler._in_flight.values())
    result: dict[str, Any] = {}
    t = threading.Thread(target=lambda: result.setdefault("drained", hosting.drain(scene.store, 5.0)))
    t.start()
    _wait_until(lambda: p.cancel.cancelled)                   # drain cancels first
    assert t.is_alive() and voicer.in_flight() == 1            # then counts the one still finishing
    gate.set()
    t.join(6)
    assert result["drained"] is True and voicer.in_flight() == 0
    assert all(not m["bubbles"] for m in _theirs(session, thread))     # a cancelled pass commits nothing


def test_commit_rechecks_proposals_and_state_checks(receipts_active) -> None:
    from engine.social import agreement, population, relationships

    scene, session = _live_session()
    state = session.engine.state
    thread = _matched_in(session, "matchstick")
    pid = thread.split(":")[1]
    _force_stage(state, pid, "talking")
    _set_person(state, pid, **_at(relationships.gate_spec("numbers")))
    _due(scene, session, thread)
    assert "offer_number" in relationships.legal_proposals(state, pid)
    # 1. A proposal legal at the snapshot, not at the commit, is dropped.
    gate = threading.Event()
    stub = StubVoice("zero", block=gate, script=[_reply_json("haha go on then", proposals=["offer_number"])])
    p, t, out = _start_pass(session, stub)
    _wait_until(lambda: stub.calls == 1)
    assert "offer_number" in stub.requests[0][1]["json_schema"]["schema"]["properties"]["proposals"]["items"]["enum"]
    _force_stage(state, pid, "numbers")
    gate.set()
    t.join(5)
    assert out["r"] == "ok"
    assert [m["bubbles"] for m in _theirs(session, thread)][-1] == ["haha go on then"]
    assert not [r for r in state.social["requests"].values() if r["from"] == "them" and r["what"] == "number"]

    # 2. A bubble naming a person matched AFTER the snapshot fails `another_person` at the commit.
    with _replies_forced():                    # their reply drawn, never a ghost (T26's tuning: F16)
        _phone(scene, session, "send", target=thread, args={"kind": "text"}, text="what are you up to")
        _phone(scene, session, "wait", args={"until": "next"})
    # The deck's top read after the waits (T16: the run starts at 19:00, and a wait can move the deck).
    other = _top(state, "matchstick")
    first = population.profile(state, other).name.split()[0]
    assert agreement.name_forms(first), f"{first!r} has no name form for the check"
    gate2 = threading.Event()
    stub2 = StubVoice("zero", block=gate2, script=[_reply_json(f"you have to meet {first} sometime")])
    p2, t2, out2 = _start_pass(session, stub2)
    _wait_until(lambda: stub2.calls == 1)                      # it passed the voice-time check: no contact yet
    assert stub2.calls == 1
    assert _matched_in(session, "matchstick").endswith(other)
    gate2.set()
    t2.join(5)
    last = _theirs(session, thread)[-1]
    assert out2["r"] == "fallback" and last["voiced"] == "fallback"     # the commit's own fallback counts
    assert all(first not in b for b in last["bubbles"])


def test_a_commit_that_cannot_lock_parks_in_the_inbox_and_the_next_action_drains_it(receipts_active, monkeypatch,
                                                                                 caplog) -> None:
    from engine.social import voicer

    scene, session = _live_session()
    thread = _matched_in(session, "matchstick")
    _due(scene, session, thread)
    results: list[tuple[str, Any]] = []
    real = voicer.commit

    def recording(session_, p_, reply, **kw: Any) -> str:
        result = real(session_, p_, reply, **kw)
        results.append((result, reply))
        return result

    monkeypatch.setattr(voicer, "commit", recording)
    gate = threading.Event()
    stub = StubVoice("warm", block=gate)
    p, t, out = _start_pass(session, stub)
    _wait_until(lambda: stub.calls == 1)
    assert session.lock.acquire(blocking=False)                # held by the test while the pass commits
    try:
        gate.set()
        t.join(10)
    finally:
        session.lock.release()
    assert [r for r, _ in results] == ["inbox"] and len(session.inbox) == 1
    assert all(m["voiced"] is False for m in _theirs(session, thread))
    assert set(session.voicing.values()) == {p.id}             # still marked: no pass voices it twice
    stale = {"kind": "voiced", "payload": results[0][1], "epoch": session.epoch + 1, "account": "", "pass": p.id}
    session.inbox.put(stale)                                   # another build's: dropped at the drain
    caplog.set_level(logging.INFO, logger="engine.social.voicer")
    _phone(scene, session, "wait", args={"until": "15m"})      # run_mechanics' step 1 drains it
    assert len(session.inbox) == 0 and session.voicing == {}
    assert all(m["voiced"] is True and m["bubbles"] for m in _theirs(session, thread))
    assert any("another build's" in r.getMessage() for r in caplog.records)


def test_marks_are_never_saved(receipts_active) -> None:
    from engine.social import payload, voicer

    scene, session = _live_session()
    thread = _matched_in(session, "matchstick")
    _due(scene, session, thread)
    gate = threading.Event()
    stub = StubVoice("zero", block=gate)
    p, t, out = _start_pass(session, stub)
    _wait_until(lambda: stub.calls == 1)
    assert set(session.voicing.values()) == {p.id}
    assert payload.thread_row(session.engine.state, thread, session)["typing"] is True
    assert '"voicing"' not in json.dumps(session.engine.state.to_save_dict())
    gate.set()
    t.join(5)
    assert session.voicing == {} and session.typing == set()
    dumped = json.dumps(session.engine.state.to_save_dict())
    assert '"voicing"' not in dumped and '"typing"' not in dumped
    assert payload.thread_row(session.engine.state, thread, session)["typing"] is False
    assert voicer.in_flight() == 0


# -- T14's own: the push, the queue, the helpers ------------------------------------------------------------


def test_a_commit_pushes_phone_message_with_its_thread_row_and_notification(receipts_active) -> None:
    from engine.social import messaging, voicer

    scene, session = _live_session()
    thread = _matched_in(session, "matchstick")
    _due(scene, session, thread)
    pushed: list[tuple[str, str, dict]] = []
    voicer.set_emitter(lambda sid, event, body: pushed.append((sid, event, body)))
    assert voicer.run_pass(voicer.VoicePass(session, session.epoch), llm_fn=StubVoice("warm"), admit=False) == "ok"
    ((sid, event, body),) = pushed
    assert sid == session.session_id and event == "phone_message"
    assert set(body) == {"message", "messages", "thread", "badges", "notification"}
    assert body["message"]["bubbles"] == ["that sounds lovely, tell me more"] and not body["message"]["pending"]
    assert body["thread"]["thread_id"] == thread and body["thread"]["typing"] is False
    assert body["badges"] == messaging.badges(session.engine.state)
    assert body["notification"]["thread_id"] == thread
    assert body["notification"]["preview"] == "that sounds lovely, tell me more"


def test_a_full_queue_drops_the_oldest_and_a_running_pass_takes_a_rerun(monkeypatch) -> None:
    from engine.social import voicer

    class Fake:
        def __init__(self, sid: str) -> None:
            self.session_id, self.epoch, self.owner = sid, 1, ""

    scheduler = voicer.VoicingScheduler(queue_max=2, workers=1)
    monkeypatch.setattr(scheduler, "_start_workers", lambda: None)     # nothing runs: the queue only
    a, b, c = Fake("a"), Fake("b"), Fake("c")
    for s in (a, b, a, c):
        scheduler.request(s)
    assert [p.session for p in scheduler.queued()] == [b, c]           # a, the oldest, dropped; one entry each
    running = voicer.VoicePass(a, 1)
    scheduler._in_flight[running.key] = running
    scheduler.request(a)
    assert running.rerun and [p.session for p in scheduler.queued()] == [b, c]
    assert scheduler.cancel_unwatched(lambda room: room == "b") == 2   # c queued, a in flight
    assert [p.session for p in scheduler.queued()] == [b] and running.cancel.cancelled
    scheduler.pause()
    scheduler.request(c)
    assert [p.session for p in scheduler.queued()] == [b]              # paused: nothing queued
    scheduler.stop()


def test_fallback_reply_for_is_the_snapshots_fallback(receipts_active) -> None:
    from engine.social import voicing

    scene, session = _live_session()
    thread = _matched_in(session, "matchstick")
    _due(scene, session, thread)
    state = session.engine.state
    snap = voicing.snapshot_of(state, thread)
    made = voicing.fallback_reply_for(state, snap.pid, thread, snap.due, "state changed")
    assert made.fallback and made.bubbles == voicing.fallback_reply(snap, "x").bubbles
    assert made.message_ids == tuple(m["id"] for m in snap.due) and made.regard == voicing.fallback_reply(snap, "x").regard
    with pytest.raises(ValueError):
        voicing.fallback_reply_for(state, "p_nobody", thread, snap.due, "x")


def test_the_checks_read_story_tables_safely_off_the_lock_across_a_reset(receipts_active) -> None:
    """T11 M3: a pass runs the checks off the lock, reading `social.data`; a cache reset meanwhile reloads the
    same story's tables (the cache is read once into a local), so every answer is the same and none raises."""
    import engine.social as social_module
    from engine.social import agreement, voicing

    scene, session = _live_session()
    thread = _matched_in(session, "matchstick")
    _due(scene, session, thread)
    snap = voicing.snapshot_of(session.engine.state, thread)
    view = agreement.view_from_snapshot(snap)
    decision = voicing._decision(snap)
    reply = {"bubbles": ["sent you a pic", "i'm 99", "we're dating now"], "shared": [], "learned": []}
    baseline = agreement.check(reply, decision, view)
    assert baseline, "the probe reply must trip some checks, or the race proves nothing"
    stop = threading.Event()
    seen: list[Any] = []

    def checking() -> None:
        try:
            while not stop.is_set():
                seen.append(agreement.check(reply, decision, view))
        except Exception as exc:  # noqa: BLE001 -- recorded and asserted below
            seen.append(exc)

    worker = threading.Thread(target=checking)
    worker.start()
    try:
        for _ in range(200):
            social_module._DATA_CACHE = None                   # what a reset does, with no lock
            threading.Event().wait(0.001)
    finally:
        stop.set()
        worker.join(5)
    assert seen and all(result == baseline for result in seen), [r for r in seen if r != baseline][:1]


# -- review fix round 1 ---------------------------------------------------------------------------------


def test_a_request_absorbed_by_a_cancelled_pass_in_flight_is_not_lost(receipts_active) -> None:
    """Review I1: a room emptied (its pass cancelled mid-call), the player back and acting: a fresh pass voices."""
    from engine.social import voicer

    scene, session = _live_session()
    thread = _matched_in(session, "matchstick")
    _due(scene, session, thread)
    gate = threading.Event()
    stub = StubVoice("warm", block=gate)
    voicer.set_llm_fn(stub)
    scheduler = voicer.get_scheduler()
    scheduler.resume()
    voicer.request(session)
    try:
        _wait_until(lambda: stub.calls == 1)
        (first,) = list(scheduler._in_flight.values())
        assert voicer.cancel_unwatched(lambda _room: False) == 1 and first.cancel.cancelled
        voicer.request(session)                                # the player is back: absorbed before the fix
    finally:
        gate.set()
    _wait_until(lambda: all(m["voiced"] is True for m in _theirs(session, thread)), timeout=5)
    assert stub.calls == 2 and _theirs(session, thread)[-1]["bubbles"] == ["that sounds lovely, tell me more"]
    _wait_until(lambda: voicer.in_flight() == 0)


def test_an_ended_persons_due_messages_are_withdrawn_and_a_reconnect_never_voices_them(receipts_active) -> None:
    """Review I2: retired, not left as "…": withdrawn through an effect, out of the payload, never voiced."""
    from engine.social import messaging, payload, voicer

    scene, session = _live_session()
    state = session.engine.state
    thread = _matched_in(session, "matchstick")
    pid = thread.split(":")[1]
    _due(scene, session, thread)
    due_ids = [m["id"] for m in _theirs(session, thread) if m["voiced"] is False]
    _force_stage(state, pid, "ended")
    stub = StubVoice("warm")
    assert voicer.run_until_quiet(session, stub) == 0 and stub.calls == 0
    rows = {m["id"]: m for m in _theirs(session, thread)}
    assert all(rows[i]["voiced"] == messaging.WITHDRAWN and rows[i]["bubbles"] == [] for i in due_ids)
    assert not messaging.unvoiced(state)
    _phone(scene, session, "open_thread", target=thread)
    shown = payload.phone_block(state, session)["open_thread"]["messages"]
    assert not [m for m in shown if m["id"] in due_ids] and not [m for m in shown if m["pending"]]
    row = payload.thread_row(state, thread, session)
    assert row["last"] is None or not row["last"]["pending"]
    assert not [n for n in state.social["notifications"] if n["thread_id"] == thread
                and n["preview"] == messaging.NEW_MESSAGE]
    _force_stage(state, pid, "talking")                        # they come back: the old messages stay retired
    assert voicer.run_until_quiet(session, stub) == 0 and stub.calls == 0
    assert all(rows[i]["voiced"] == messaging.WITHDRAWN for i in due_ids)


def test_an_unmatched_persons_due_messages_are_withdrawn_at_the_next_tap(receipts_active) -> None:
    from engine.social import messaging

    scene, session = _live_session()
    thread = _matched_in(session, "matchstick")
    _due(scene, session, thread)
    _phone(scene, session, "unmatch", target=thread.split(":")[1])     # the route's check retires them
    assert _theirs(session, thread) and all(m["voiced"] == messaging.WITHDRAWN for m in _theirs(session, thread)
                                            if not m["bubbles"])
    assert not messaging.unvoiced(session.engine.state)


def test_a_commit_discarded_for_an_unmatch_withdraws_the_rest(receipts_active) -> None:
    from engine.social import messaging

    scene, session = _live_session()
    thread = _matched_in(session, "matchstick")
    _due(scene, session, thread)
    gate = threading.Event()
    stub = StubVoice("warm", block=gate)
    p, t, out = _start_pass(session, stub)
    _wait_until(lambda: stub.calls == 1)
    from engine.social import matching

    assert session.lock.acquire(blocking=False)
    try:
        matching.unmatch(session.engine.state, thread.split(":")[1], by="them")
    finally:
        session.lock.release()
    gate.set()
    t.join(5)
    assert out["r"] == "discarded"
    assert all(m["voiced"] == messaging.WITHDRAWN for m in _theirs(session, thread))


def test_one_inbox_items_fault_costs_that_item_only(receipts_active, monkeypatch, caplog) -> None:
    """Review M2: an item that raises is logged and dropped, its marks popped; the others apply; the tap stands."""
    from engine.social import voicer, voicing

    scene, session = _live_session()
    thread = _matched_in(session, "matchstick")
    _due(scene, session, thread)
    state = session.engine.state
    snap = voicing.snapshot_of(state, thread)
    good = voicing.fallback_reply(snap, "test")
    bad = voicing.VoicedReply(pid="p_nobody", thread_id="nowhere", message_ids=("m_missing",), bubbles=["x"],
                              caption="", regard={"warmth": 0, "trust": 0, "mood": "neutral"}, learned=[],
                              shared=[], proposals=[], fallback=False, failures=[])
    for m in snap.due:
        session.voicing[m["id"]] = "vX"
    session.voicing["m_missing"] = "vBad"
    real = voicer._apply_reply

    def flaky(session_, pass_id, reply, **kw):
        if pass_id == "vBad":
            raise RuntimeError("a broken item")
        return real(session_, pass_id, reply, **kw)

    monkeypatch.setattr(voicer, "_apply_reply", flaky)
    session.inbox.put({"kind": "voiced", "payload": bad, "epoch": session.epoch, "account": "", "pass": "vBad"})
    session.inbox.put({"kind": "voiced", "payload": good, "epoch": session.epoch, "account": "", "pass": "vX"})
    caplog.set_level(logging.WARNING, logger="engine.social.voicer")
    body = _phone(scene, session, "wait", args={"until": "15m"})      # the player's tap still stands
    assert not body["receipts"][0].get("refused")
    assert session.voicing == {} and len(session.inbox) == 0
    assert all(m["voiced"] == "fallback" for m in _theirs(session, thread))
    assert any("Inbox item failed" in r.getMessage() for r in caplog.records)


def test_fewer_bubbles_than_due_messages_never_voices_a_wordless_one(receipts_active) -> None:
    """Review M6: a burst of two answered with one bubble: the first voiced, the second withdrawn, never empty."""
    from engine.social import messaging, voicer

    scene, session = _live_session()
    thread = _matched_in(session, "matchstick")
    _due(scene, session, thread)
    state = session.engine.state
    pid = thread.split(":")[1]
    messaging.new_message(state, thread, pid, "text", voiced=False, decision={"situation": "double_text"})
    due = [m for m in _theirs(session, thread) if m["voiced"] is False]
    assert len(due) >= 2
    assert voicer.run_pass(voicer.VoicePass(session, session.epoch), llm_fn=StubVoice("zero"), admit=False) == "ok"
    rows = [m for m in _theirs(session, thread) if m["id"] in {d["id"] for d in due}]
    assert rows[0]["voiced"] is True and rows[0]["bubbles"] == ["sure"]
    assert all(m["voiced"] == messaging.WITHDRAWN for m in rows[1:])
    assert not [m for m in _theirs(session, thread) if m["voiced"] is True and not m["bubbles"]]


def test_a_pass_reports_one_voice_pass_metric(receipts_active, monkeypatch) -> None:
    """Review M7: one `voice_pass` row per pass run, read off its commits; a pass with nothing due records none."""
    from engine.social import voicer

    scene, session = _live_session()
    thread = _matched_in(session, "matchstick")
    other = _matched_in(session, "matchstick")
    _due(scene, session, thread)
    from engine.social import messaging

    messaging.new_message(session.engine.state, other, other.split(":")[1], "text", voiced=False,
                          decision={"situation": "reply"})
    reported: list[str] = []
    monkeypatch.setattr(voicer, "_report_pass", lambda _s, status, ms=0.0: reported.append(status))
    assert voicer.run_pass(voicer.VoicePass(session, session.epoch), llm_fn=StubVoice("zero"), admit=False) == "ok"
    assert reported == ["ok"]                                   # two people committed, one row
    assert voicer.run_pass(voicer.VoicePass(session, session.epoch), llm_fn=StubVoice("zero"), admit=False) == "ok"
    assert reported == ["ok"]                                   # nothing due: nothing recorded


# -- review fix round 2 ---------------------------------------------------------------------------------


def test_a_withdrawn_extra_is_never_pushed(receipts_active) -> None:
    """Review N1: a burst answered with one bubble pushes the voiced message only, never the withdrawn one."""
    from engine.social import messaging, voicer

    scene, session = _live_session()
    thread = _matched_in(session, "matchstick")
    _due(scene, session, thread)
    messaging.new_message(session.engine.state, thread, thread.split(":")[1], "text", voiced=False,
                          decision={"situation": "double_text"})
    due = [m["id"] for m in _theirs(session, thread) if m["voiced"] is False]
    pushed: list[dict] = []
    voicer.set_emitter(lambda _sid, event, body: pushed.append(body) if event == "phone_message" else None)
    assert voicer.run_pass(voicer.VoicePass(session, session.epoch), llm_fn=StubVoice("zero"), admit=False) == "ok"
    (body,) = pushed
    assert [m["id"] for m in body["messages"]] == due[:1]
    assert body["message"]["id"] == due[0] and body["message"]["bubbles"] == ["sure"]
    assert all(m["bubbles"] for m in body["messages"])


def test_a_withdrawal_is_pushed_at_once(receipts_active) -> None:
    """Review N3: an ended person's "..." leaves the thread row in a push, not at the next payload."""
    from engine.social import voicer

    scene, session = _live_session()
    state = session.engine.state
    thread = _matched_in(session, "matchstick")
    _due(scene, session, thread)
    pushed: list[dict] = []
    voicer.set_emitter(lambda _sid, event, body: pushed.append(body) if event == "phone_message" else None)
    _force_stage(state, thread.split(":")[1], "ended")
    assert voicer.request_if_due(session) is False             # nothing left to voice: withdrawn instead
    (body,) = pushed
    assert body["messages"] == [] and body["message"] is None
    assert body["thread"]["thread_id"] == thread
    assert body["thread"]["last"] is None or not body["thread"]["last"]["pending"]


def test_a_cancel_racing_a_rerun_still_queues_a_fresh_pass(receipts_active, monkeypatch) -> None:
    """Review N2: a request that set `rerun` just before its pass was cancelled is not lost when the pass ends."""
    from engine.social import voicer

    scene, session = _live_session()
    scheduler = voicer.VoicingScheduler(workers=1)
    monkeypatch.setattr(scheduler, "_start_workers", lambda: None)
    p = voicer.VoicePass(session, session.epoch)
    scheduler._in_flight[p.key] = p
    scheduler.request(session)                                 # the pass is not cancelled yet: rerun
    assert p.rerun
    p.cancel.cancel()                                          # the cancel fires after the request
    scheduler._after(p, "cancelled")
    (successor,) = scheduler.queued()
    assert successor is not p and not successor.cancel.cancelled and scheduler.in_flight() == 0
    scheduler.stop()


def test_withdrawn_messages_count_as_never_sent_after_a_reconnect(receipts_active) -> None:
    """Review N4: a withdrawn opener and double text spend nothing: not the opener, not the cap, not the burst."""
    from engine.social import messaging

    scene, session = _live_session()
    state = session.engine.state
    thread = _matched_in(session, "matchstick")
    pid = thread.split(":")[1]
    assert session.lock.acquire(blocking=False)
    try:
        for situation in ("opener", "double_text", "double_text"):
            messaging.new_message(state, thread, pid, "text", voiced=False, decision={"situation": situation})
        _force_stage(state, pid, "ended")
        from engine.social import voicer

        assert not voicer.pending(session)                     # all three withdrawn
        _force_stage(state, pid, "talking")                    # they come back
        t = messaging.thread(state, thread)
        assert all(m["voiced"] == messaging.WITHDRAWN for m in t["messages"] if m["from"] == pid)
        assert messaging._in_a_row(t) == 0                     # the cap counts none of them
        assert messaging._opener_taken(state, pid) is (
            any(e["pid"] == pid and e["kind"] == "initiate" and messaging._is_opener(e)
                for e in state.social.get("queue") or []))    # only a QUEUED opener still counts
        messaging.new_message(state, thread, "player", "text", bubbles=["you there?"])
        assert messaging._player_burst(state, thread) == 1     # "they last wrote" is not a withdrawn row
    finally:
        session.lock.release()
