"""
READ RECEIPTS served hosted (v0.22.0 spec §17.1): the phone's own bucket, its
text cap, its metric kind, and every phone route behind the login.

Built in-process through tests/hosted_app.py (``hosted_receipts`` in
tests/social_fixtures.py): the test clients bind no server.
"""

from __future__ import annotations

import json
import threading
from typing import Any

import pytest

from engine.hosting.limits import SLOW_DOWN, ActionLimiter
from tests.social_fixtures import _wait_until, hosted_receipts  # noqa: F401


def test_the_phone_bucket_not_the_actions_bucket_limits_phone_action(hosted_receipts) -> None:
    # hosted_receipts: a tests/hosted_app.py app with read-receipts active,
    # actions_per_minute 12 and phone_actions_per_minute 90 in its local.yaml layer.
    run = hosted_receipts.login_and_start()
    for _ in range(30):
        run.sock.emit("phone_action", {"session_id": run.sid, "action": "wait", "args": {"until": "1h"}})
    errors = [e for e in run.sock.get_received() if e["name"] == "turn_error"
              and "faster than this server allows" in e["args"][0]["message"]]
    assert errors == []                                   # 30 < 90, and the actions bucket was not spent
    actions = hosted_receipts.state.actions
    assert actions.buckets.level(run.account_id, actions.clock()) > 11


def test_a_phone_text_over_max_input_chars_is_refused(hosted_receipts) -> None:
    run = hosted_receipts.login_and_start()
    run.sock.emit("phone_action", {"session_id": run.sid, "action": "edit_profile", "target": "matchstick",
                                   "args": {"field": "bio"}, "text": "y" * 1001})
    refused = [e for e in run.sock.get_received() if e["name"] == "turn_error"]
    assert refused and "1000 characters" in refused[0]["args"][0]["message"]


def test_a_hosted_mechanics_action_reports_a_phone_metric_never_a_turn(hosted_receipts, monkeypatch) -> None:
    from engine.scenes import default_scene

    seen: list[tuple] = []
    monkeypatch.setattr(default_scene, "phone_metric", lambda *a: seen.append(("phone",) + a))
    monkeypatch.setattr(default_scene, "turn_metric", lambda *a: seen.append(("turn",) + a))
    run = hosted_receipts.login_and_start()
    run.sock.emit("phone_action", {"session_id": run.sid, "action": "wait", "args": {"until": "1h"}})
    assert [row[0] for row in seen] == ["phone"] and seen[0][2] == "action" and seen[0][3] == "ok"


# -- further: the bucket refuses, both doors; no admission; the login --------


def _one_phone_token(hosted_receipts: Any) -> ActionLimiter:
    """From now on: one phone action, and the clock never refills it."""
    limiter = ActionLimiter(1, clock=lambda: 0.0)
    hosted_receipts.state.phone_actions = limiter
    hosted_receipts.scene._socket_door.phone_actions = limiter
    return limiter


def test_the_phone_bucket_refuses_on_the_socket_once_spent(hosted_receipts) -> None:
    run = hosted_receipts.login_and_start()
    _one_phone_token(hosted_receipts)
    body = {"session_id": run.sid, "action": "wait", "args": {"until": "1h"}}
    run.sock.emit("phone_action", body)
    first = run.sock.get_received()
    assert [e["name"] for e in first] == ["turn_update"]
    run.sock.emit("phone_action", body)
    second = run.sock.get_received()
    assert second == [{"name": "turn_error", "args": [{"message": SLOW_DOWN, "busy": False}], "namespace": "/"}]


def test_the_http_twin_has_the_phone_bucket_and_cap_not_the_actions_bucket(hosted_receipts) -> None:
    run = hosted_receipts.login_and_start()
    actions = hosted_receipts.state.actions
    before = actions.buckets.level(run.account_id, actions.clock())
    body = {"session_id": run.sid, "action": "wait", "args": {"until": "1h"}}
    ok = run.client.post("/api/phone/action", json=body)
    assert ok.status_code == 200 and ok.get_json()["narration"] == ""
    assert actions.buckets.level(run.account_id, actions.clock()) >= before     # nothing spent there
    over = run.client.post("/api/phone/action", json={**body, "action": "edit_profile", "target": "matchstick",
                                                      "args": {"field": "bio"}, "text": "z" * 1001})
    assert over.status_code == 400 and "1000 characters" in over.get_json()["error"]
    _one_phone_token(hosted_receipts)
    assert run.client.post("/api/phone/action", json=body).status_code == 200
    limited = run.client.post("/api/phone/action", json=body)
    assert limited.status_code == 429 and limited.get_json() == {"error": SLOW_DOWN}


def test_a_hosted_phone_action_never_asks_for_admission(hosted_receipts, monkeypatch) -> None:
    """Spec §16.1: a mechanics action never enters the narration queue (admit=False)."""
    from engine.llm import gate

    def _no(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("a phone action asked admit_turn for a ticket")

    monkeypatch.setattr(gate, "admit_turn", _no)
    run = hosted_receipts.login_and_start()
    run.sock.emit("phone_action", {"session_id": run.sid, "action": "wait", "args": {"until": "1h"}})
    assert [e["name"] for e in run.sock.get_received()] == ["turn_update"]
    assert run.client.post("/api/phone/action", json={"session_id": run.sid, "action": "wait",
                                                      "args": {"until": "1h"}}).status_code == 200


@pytest.mark.parametrize("method, path", [("GET", "/api/social/creation"), ("POST", "/api/phone/action")])
def test_every_phone_route_needs_a_login(hosted_receipts, method: str, path: str) -> None:
    """T4's creation form and T6's action: refused logged out, served logged in."""
    from tests.hosted_app import login

    anonymous = hosted_receipts.hosted.client()
    response = anonymous.open(path, method=method, json={} if method == "POST" else None)
    assert response.status_code == 401 and response.get_json() == {"error": "login required"}

    _account, password = hosted_receipts.hosted.add("bob")
    client = hosted_receipts.hosted.client()
    assert login(client, "bob", password).status_code == 303
    served = client.open(path, method=method, json={} if method == "POST" else None)
    assert served.status_code != 401
    if method == "GET":
        assert served.status_code == 200 and served.get_json()


# -- review fix round 1: faults, and the phone metric's `refused` ------------------


def test_a_hosted_skill_fault_is_answered_generically_never_with_the_exception(hosted_receipts, monkeypatch) -> None:
    from engine.agents.tool_dispatcher import PHONE_FAULT
    from engine.social import turn

    def _broken(*_a: Any, **_k: Any) -> Any:
        raise KeyError("C:/secret/path/users.json")

    monkeypatch.setattr(turn, "set_receipts", _broken)
    run = hosted_receipts.login_and_start()
    run.sock.emit("phone_action", {"session_id": run.sid, "action": "set_receipts", "target": "natter",
                                   "args": {"to": "off"}})
    (update,) = [e["args"][0] for e in run.sock.get_received() if e["name"] == "turn_update"]
    assert update["state"]["phone"]["refusal"]["reason"] == PHONE_FAULT
    assert "secret" not in str(update)


def test_a_refused_phone_action_reports_phone_refused_never_a_turn(hosted_receipts, monkeypatch) -> None:
    """Spec §17.1: a mechanics action is never a `turn` -- the engine's refusal, the cap and the bucket alike."""
    from engine.hosting import metrics_emit
    from engine.scenes import default_scene

    seen: list[tuple] = []
    monkeypatch.setattr(default_scene, "phone_metric", lambda *a: seen.append(("hook",) + a))
    monkeypatch.setattr(metrics_emit, "emit", lambda kind, **f: seen.append((kind, f)))
    run = hosted_receipts.login_and_start()
    seen.clear()
    run.sock.emit("phone_action", {"session_id": run.sid, "action": "wait", "args": {"until": "forever"}})
    assert seen[0][0] == "hook" and seen[0][3] == "refused"
    seen.clear()
    run.sock.emit("phone_action", {"session_id": run.sid, "action": "wait", "args": {"until": "1h"},
                                   "text": "x" * 1001})
    _one_phone_token(hosted_receipts)
    body = {"session_id": run.sid, "action": "wait", "args": {"until": "1h"}}
    run.client.post("/api/phone/action", json=body)
    run.client.post("/api/phone/action", json=body)              # past the bucket
    refusals = [row for row in seen if row[0] != "hook"]
    assert refusals == [("phone", {"account": run.account_id, "event": "action", "status": "refused", "ms": 0.0})] * 2
    assert not any(row[0] == "turn" for row in seen)


# -- the voicing pass, hosted (v0.22.0 T14, spec §16.2, §17.1) ----------------------------------------


def _session(hosted_receipts: Any, run: Any) -> Any:
    return hosted_receipts.scene.store.get(run.sid, owner=run.account_id)


def _post(run: Any, action: str, target: str = "", args: Any = None, text: str = "") -> dict[str, Any]:
    resp = run.client.post("/api/phone/action", json={"session_id": run.sid, "action": action, "target": target,
                                                       "args": args or {}, "text": text})
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return resp.get_json()


def _due_hosted(hosted_receipts: Any, run: Any) -> tuple[Any, str]:
    """A match in the player's run and a reply of theirs due (unvoiced): (the session, the thread)."""
    from engine.social import messaging
    from tests.social_fixtures import _matched_in, _replies_forced

    session = _session(hosted_receipts, run)
    thread = _matched_in(session, "matchstick")
    with _replies_forced():                    # their reply drawn, never a ghost (T26's tuning: F16)
        _post(run, "send", target=thread, args={"kind": "text"}, text="hey you")
        _post(run, "wait", args={"until": "next"})
    assert messaging.unvoiced(session.engine.state)
    return session, thread


@pytest.fixture
def own_lanes() -> Any:
    from engine.llm import gate

    gate.reset_lanes()
    try:
        yield
    finally:
        gate.reset_lanes()


def test_a_hosted_mechanics_action_never_calls_admit_turn(hosted_receipts, monkeypatch) -> None:
    """Spec §16.1: a swipe and a send, hosted, never ask for a narration ticket (a pass does, later)."""
    from engine.llm import gate
    from tests.social_fixtures import _matched_in, _top

    def _no(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("a mechanics action asked admit_turn for a ticket")

    monkeypatch.setattr(gate, "admit_turn", _no)
    run = hosted_receipts.login_and_start()
    session = _session(hosted_receipts, run)
    swiped = _post(run, "swipe", target=_top(session.engine.state, "matchstick"), args={"dir": "like"})
    assert not swiped["receipts"][0].get("refused"), swiped["receipts"][0]
    thread = _matched_in(session, "matchstick")
    sent = _post(run, "send", target=thread, args={"kind": "text"}, text="hello there")
    assert not sent["receipts"][0].get("refused"), sent["receipts"][0]


def test_a_phone_action_on_another_accounts_session_is_refused(hosted_receipts) -> None:
    alice = hosted_receipts.login_and_start("alice")
    bob = hosted_receipts.login_and_start("bob")
    session = _session(hosted_receipts, alice)
    before = json.dumps(session.engine.state.to_save_dict(), sort_keys=True)
    bob.sock.emit("phone_action", {"session_id": alice.sid, "action": "wait", "args": {"until": "1h"}})
    errors = [e["args"][0] for e in bob.sock.get_received() if e["name"] == "turn_error"]
    assert errors and errors[0]["message"] == "session not found"
    assert json.dumps(session.engine.state.to_save_dict(), sort_keys=True) == before
    assert bob.client.post("/api/phone/action", json={"session_id": alice.sid, "action": "wait",
                                                      "args": {"until": "1h"}}).status_code == 404


def test_a_revoked_socket_receives_no_phone_message(hosted_receipts) -> None:
    """Spec §17.1: a background push runs the room check first, so a login no longer live hears nothing."""
    from engine.social import voicer
    from tests.social_stub import StubVoice

    run = hosted_receipts.login_and_start("alice")
    second = hosted_receipts.scene.socketio.test_client(hosted_receipts.app, flask_test_client=run.client)
    second.emit("join_session", {"session_id": run.sid})
    second.get_received()
    session, thread = _due_hosted(hosted_receipts, run)
    run.sock.get_received()
    door = hosted_receipts.scene._socket_door
    sid = hosted_receipts.scene.socketio.server.manager.sid_from_eio_sid(second.eio_sid, "/")
    door.registry.add(sid, run.account_id, -1, "/")          # its login's epoch no longer the account's
    assert voicer.run_pass(voicer.VoicePass(session, session.epoch), llm_fn=StubVoice("warm"), admit=False) == "ok"
    heard = [e for e in run.sock.get_received() if e["name"] == "phone_message"]
    assert heard and heard[0]["args"][0]["thread"]["thread_id"] == thread
    assert not second.is_connected()                          # dropped by the room check before the push
    assert not [e for e in second.queue if e["name"] == "phone_message"]   # (get_received refuses a closed one)


def test_a_pass_admits_with_a_short_wait(hosted_receipts, monkeypatch) -> None:
    """Spec §16.2 step 1: admitted before anything is marked, for the owner, short-waited, cancellable."""
    from engine.config import get_config
    from engine.llm import gate
    from engine.social import voicer
    from tests.social_stub import StubVoice

    run = hosted_receipts.login_and_start()
    session, thread = _due_hosted(hosted_receipts, run)
    asked: list[dict[str, Any]] = []
    released: list[int] = []

    class _Admission:
        def release(self) -> None:
            released.append(1)

    def admit(**kwargs: Any) -> Any:
        asked.append(dict(kwargs, marks=dict(session.voicing)))
        return _Admission()

    monkeypatch.setattr(gate, "admit_turn", admit)
    p = voicer.VoicePass(session, session.epoch)
    assert voicer.run_pass(p, llm_fn=StubVoice("zero"), admit=True) == "ok"
    (call,) = asked
    assert call["timeout"] == 5.0 and call["label"] == "voice" and call["account"] == run.account_id
    assert call["cancel"] is p.cancel and call["marks"] == {}             # nothing marked before admission
    assert call["deadline_seconds"] == float(get_config().get("hosting.turn_deadline_seconds"))
    assert released == [1]


def test_a_hosted_voice_call_runs_inside_its_admission(hosted_receipts, own_lanes) -> None:
    """
    T13's carry: the off-lock voice call, hosted, is neither refused nor
    given a second ticket -- it runs inside the pass's own narration ticket
    (a narration-lane slot, as `backend.chat` takes for the `texter`
    profile, shares it), and the ticket is back once the pass ends.
    """
    from engine.llm import gate
    from engine.social import voicer
    from tests.social_stub import StubVoice

    run = hosted_receipts.login_and_start()
    session, thread = _due_hosted(hosted_receipts, run)
    stub = StubVoice("zero")
    seen: list[Any] = []

    def llm(messages: Any, fmt: Any) -> str:
        seen.append(gate.held_lane())
        with gate.inference_slot(label="texter", lane="narration", timeout=0):
            seen.append("shared")
        return stub(messages, fmt)

    assert voicer.run_pass(voicer.VoicePass(session, session.epoch), llm_fn=llm, admit=True) == "ok"
    assert seen == ["narration", "shared"]
    assert gate.held_lane() is None
    with gate.turn_admission(label="next", timeout=0):         # the one narration slot is free again
        pass


def test_one_ticket_per_account(hosted_receipts, own_lanes, monkeypatch) -> None:
    """
    An account's mechanics action while its pass holds the narration ticket
    is not busy (mechanics take no ticket); a second pass for the same run
    never asks for a second ticket at all (v0.23.0 T8, spec §20.1): it finds
    the run's narration turnstile held by the first pass's call, answers
    `deferred` -- not an attempt -- and is re-queued on the retry schedule.
    """
    from engine import social
    from engine.llm import gate
    from engine.social import voicer
    from tests.social_fixtures import _with
    from tests.social_stub import StubVoice

    run = hosted_receipts.login_and_start()
    session, thread = _due_hosted(hosted_receipts, run)
    real_admit = gate.admit_turn
    asked: list[tuple[str, str]] = []

    def admit(**kwargs: Any) -> Any:
        try:
            got = real_admit(**kwargs)
        except gate.InferenceBusy as exc:
            asked.append((kwargs["account"], exc.reason))
            raise
        asked.append((kwargs["account"], "admitted"))
        return got

    monkeypatch.setattr(gate, "admit_turn", admit)
    monkeypatch.setattr(social, "setting", _with(social.setting, **{"voice.admit_wait_seconds": 0.2}))
    held = threading.Event()
    stub = StubVoice("zero", block=held)
    first = voicer.VoicePass(session, session.epoch)
    out: dict[str, Any] = {}
    worker = threading.Thread(target=lambda: out.setdefault("r", voicer.run_pass(first, llm_fn=stub, admit=True)))
    worker.start()
    scheduler = None
    try:
        _wait_until(lambda: stub.calls == 1)
        acted = _post(run, "wait", args={"until": "1h"})            # mechanics: no ticket, not busy
        assert not acted.get("busy") and not acted["receipts"][0].get("refused")
        # Something due that the first pass has not taken, so the second asks for a ticket at all.
        from tests.social_fixtures import _matched_in

        from engine.social import messaging

        other = _matched_in(session, "matchstick")
        assert session.lock.acquire(blocking=False)
        try:
            messaging.new_message(session.engine.state, other, other.split(":")[1], "text", voiced=False,
                                  decision={"situation": "reply"})
        finally:
            session.lock.release()
        scheduler = voicer.VoicingScheduler(workers=1, admit=lambda: True)
        scheduler.request(session)
        _wait_until(lambda: any(p.deferrals for p in scheduler.queued()), timeout=5)
        (second,) = scheduler.queued()
        assert second is not first and second.attempts == 0        # deferred: not an attempt
        assert asked == [(session.owner, "admitted")]              # one ticket for the account, ever
    finally:
        if scheduler is not None:
            scheduler.stop()
        held.set()
        worker.join(5)
    assert asked[0] == (run.account_id, "admitted")
    assert gate.BUSY not in {reason for _account, reason in asked}   # the turnstile kept the two passes apart
    assert out["r"] == "ok"


def test_a_pass_with_nothing_due_asks_no_ticket(hosted_receipts, monkeypatch) -> None:
    """Review M3: a pass that finds nothing due (or parked) never enters the narration queue."""
    from engine.llm import gate
    from engine.social import voicer
    from tests.social_stub import StubVoice

    run = hosted_receipts.login_and_start()
    session = _session(hosted_receipts, run)
    _post(run, "wait", args={"until": "1h"})

    def _no(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("a pass with nothing due asked admit_turn for a ticket")

    monkeypatch.setattr(gate, "admit_turn", _no)
    stub = StubVoice("zero")
    assert voicer.run_pass(voicer.VoicePass(session, session.epoch), llm_fn=stub, admit=True) == "ok"
    assert stub.calls == 0


def test_a_pass_with_only_a_parked_media_result_drains_it_with_no_ticket(hosted_receipts, monkeypatch) -> None:
    """Final review I1: applying a parked result calls no model, so the pass asks no ticket for it."""
    from engine.llm import gate
    from engine.social import voicer
    from tests.social_stub import StubVoice

    run = hosted_receipts.login_and_start()
    session = _session(hosted_receipts, run)
    _post(run, "wait", args={"until": "1h"})
    assert not voicer.pending(session)
    applied: list[Any] = []
    monkeypatch.setattr("engine.social.media.apply_and_push",
                        lambda _s, result, *_a, **_k: applied.append(result) or True)
    session.inbox.put({"kind": "media", "payload": "a result", "epoch": session.epoch,
                       "account": str(session.owner or ""), "ms": 0.0, "digest": ""})

    def _no(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("draining a parked media result asked admit_turn for a ticket")

    monkeypatch.setattr(gate, "admit_turn", _no)
    stub = StubVoice("zero")
    assert voicer.run_pass(voicer.VoicePass(session, session.epoch), llm_fn=stub, admit=True) == "ok"
    assert applied == ["a result"] and len(session.inbox) == 0 and stub.calls == 0


def test_a_disconnect_calls_off_only_the_passes_of_its_own_rooms(hosted_receipts, monkeypatch) -> None:
    """Review M4: bob's socket closing leaves alice's queued pass alone; alice's last socket closing calls it off."""
    from engine.social import voicer

    alice = hosted_receipts.login_and_start("alice")
    bob = hosted_receipts.login_and_start("bob")
    session, thread = _due_hosted(hosted_receipts, alice)
    alice.sock.disconnect()                                   # alice now plays over HTTP: no socket in her room
    scheduler = voicer.get_scheduler()
    monkeypatch.setattr(scheduler, "_start_workers", lambda: None)       # queued, never run: the cancel only
    scheduler.resume()
    voicer.request(session)
    (queued,) = scheduler.queued()
    bob.sock.disconnect()                                     # not in alice's room: her pass is not his to end
    assert not queued.cancel.cancelled and scheduler.queued() == [queued]
    again = hosted_receipts.scene.socketio.test_client(hosted_receipts.app, flask_test_client=alice.client)
    again.emit("join_session", {"session_id": alice.sid})
    again.disconnect()                                        # her room's last socket goes: called off
    assert queued.cancel.cancelled and scheduler.queued() == []


# -- the narration turnstile, hosted (v0.23.0 T28, spec §20.1) -----------------------------------------


def _put_down(started: Any) -> None:
    resp = started.client.post("/api/phone/action", json={"session_id": started.sid, "action": "put_down",
                                                           "target": "", "args": {}, "text": ""})
    assert resp.status_code == 200, resp.get_data(as_text=True)


@pytest.mark.loopback
def test_no_other_window_for_one_session_world_then_voice(hosted_receipts) -> None:
    """§20.1: a world turn and a voice pass from ONE account never refuse each other `other_window`."""
    from engine.social import voicer
    from tests.social_fixtures import _offered, _three_due_hosted

    started = hosted_receipts.login_and_start("alice")
    _three_due_hosted(hosted_receipts, started)
    voicer.get_scheduler().resume()
    _put_down(started)
    turn = started.client.post("/api/game/choice", json={
        "session_id": started.sid, "choice_id": _offered(hosted_receipts, started, "Tidy up a bit")})
    assert turn.status_code == 200, turn.get_data(as_text=True)
    assert "other window" not in turn.get_data(as_text=True)
    _wait_until(lambda: not voicer.pending(hosted_receipts.session(started)), timeout=10.0)


@pytest.mark.loopback
def test_no_other_window_for_one_session_voice_then_world(hosted_receipts) -> None:
    """The other direction: a pass holding the turnstile; the world turn waits one call, then runs."""
    from engine.social import voicer
    from tests.social_fixtures import _offered, _three_due_hosted
    from tests.social_stub import StubVoice

    started = hosted_receipts.login_and_start("alice")
    _three_due_hosted(hosted_receipts, started)
    release = threading.Event()
    stub = StubVoice("zero", block=release)
    voicer.set_llm_fn(stub)
    _put_down(started)
    choice_id = _offered(hosted_receipts, started, "Tidy up a bit")
    voicer.get_scheduler().resume()
    voicer.request(hosted_receipts.session(started))              # the scheduler was paused: ask for the pass
    _wait_until(lambda: stub.calls == 1, timeout=10.0)            # a voice call holds the turnstile
    answers: list[Any] = []
    t = threading.Thread(target=lambda: answers.append(started.client.post("/api/game/choice", json={
        "session_id": started.sid, "choice_id": choice_id})))
    t.start()
    session = hosted_receipts.session(started)
    try:
        _wait_until(lambda: session.narration_turnstile.world_waiting == 1, timeout=10.0)
    finally:
        release.set()
        t.join(30.0)
    assert answers and answers[0].status_code == 200, answers and answers[0].get_data(as_text=True)
    assert "other window" not in answers[0].get_data(as_text=True)
    _wait_until(lambda: not voicer.pending(session), timeout=10.0)


@pytest.mark.loopback
def test_a_world_turn_whose_arrival_opens_a_scene_beside_a_voice_pass_is_never_refused(
        hosted_receipts, monkeypatch) -> None:
    """
    T23C's arrival after the drain and its second `turn_update`: a plan's person arrives inside a room move's minute, so
    the scene opens inside the world turn, while a voice pass from the same account has replies due. Neither is refused
    `other_window` (the arrival calls no model, under the turn's own turnstile and lock), the turn answers with the
    scene's frame, and the pass still commits.
    """
    from engine import social
    from engine.session.store import release_turn
    from engine.social import matching, plans, voicer
    from tests.social_fixtures import _force_stage, _three_due_hosted
    from tests.test_social_plans import _willing_meet

    started = hosted_receipts.login_and_start("alice")
    threads = _three_due_hosted(hosted_receipts, started)
    session = hosted_receipts.session(started)
    state = session.engine.state
    pid = threads[0].split(":")[1]
    _force_stage(state, pid, "numbers")
    wait = started.client.post("/api/phone/action", json={"session_id": started.sid, "action": "wait",
                                                           "target": "", "args": {"until": "1h"}, "text": ""})
    assert wait.status_code == 200, wait.get_data(as_text=True)
    _put_down(started)
    _willing_meet(monkeypatch)
    monkeypatch.setattr(plans, "_arrival", lambda s, r, e, at: (at, at + 0.5 / 60.0))   # inside the move's minute
    assert session.lock.acquire(blocking=False)
    try:
        assert plans.make(state, pid, kind="your_place", when="now", venue="")
    finally:
        release_turn(session)
    move = next(c for c in session.last_turn["choices"] if (c.get("intent") or {}).get("action") == "travel")
    voicer.get_scheduler().resume()
    turn = started.client.post("/api/game/choice", json={"session_id": started.sid, "choice_id": move["id"]})
    assert turn.status_code == 200, turn.get_data(as_text=True)
    assert "other window" not in turn.get_data(as_text=True)
    assert social.scene_open(state)
    assert f"{matching._name(state, pid)} arrives." in turn.get_json()["narration"]
    _wait_until(lambda: not voicer.pending(session), timeout=15.0)


@pytest.mark.loopback
def test_voice_pass_never_blocks_a_scheduler_thread_hosted(hosted_receipts) -> None:
    """Two accounts each in a world turn (their turnstiles held), while a third account's pass completes on the 2-worker scheduler."""
    from engine.social import voicer
    from tests.social_fixtures import _three_due_hosted, hold_world

    a, b, c = (hosted_receipts.login_and_start(n) for n in ("alice", "bob", "carol"))
    _three_due_hosted(hosted_receipts, c)
    held = [threading.Event(), threading.Event()]
    let_go = threading.Event()
    threads = [threading.Thread(target=hold_world, args=(hosted_receipts.session(s),),
                                kwargs={"timeout": 5.0, "acquired": ev, "until": let_go}) for s, ev in zip((a, b), held)]
    for t in threads:
        t.start()
    try:
        for ev in held:
            assert ev.wait(10.0)
        voicer.get_scheduler().resume()
        voicer.request(hosted_receipts.session(c))
        _wait_until(lambda: not voicer.pending(hosted_receipts.session(c)), timeout=15.0)
    finally:
        let_go.set()
        for t in threads:
            t.join(10.0)


@pytest.mark.loopback
def test_the_narration_share_metric_is_emitted(hosted_receipts, monkeypatch) -> None:
    """A world turn and a pass each add seconds; the share goes out as `phone` rows (`narration_world`, `narration_voice`) whose fields are exactly the schema's."""
    from engine.hosting import metrics_schema
    from engine.scenes import default_scene
    from engine.social import turnstile, voicer
    from tests.social_fixtures import _offered, _three_due_hosted

    rows: list[tuple[Any, ...]] = []
    monkeypatch.setattr(default_scene, "phone_metric", lambda *row: rows.append(row))
    monkeypatch.setattr(turnstile, "SHARE_INTERVAL_SECONDS", 0.0)
    started = hosted_receipts.login_and_start("alice")
    session = hosted_receipts.session(started)
    _three_due_hosted(hosted_receipts, started)
    voicer.get_scheduler().resume()
    _put_down(started)
    turn = started.client.post("/api/game/choice", json={
        "session_id": started.sid, "choice_id": _offered(hosted_receipts, started, "Tidy up a bit")})
    assert turn.status_code == 200, turn.get_data(as_text=True)
    _wait_until(lambda: not voicer.pending(session), timeout=15.0)
    gate = session.narration_turnstile
    assert gate.held_seconds[turnstile.WORLD] > 0.0 and gate.held_seconds[turnstile.VOICE] > 0.0
    shares = [r for r in rows if r[1] in ("narration_world", "narration_voice")]
    assert {r[1] for r in shares} == {"narration_world", "narration_voice"}, rows
    for account, event, status, ms in shares:
        assert account == started.account_id and status == "ok" and ms > 0.0
        clean = metrics_schema.validate({"kind": "phone", "ts": 1_790_000_000, "story": "read-receipts",
                                         "account": account, "event": event, "status": status, "ms": ms},
                                        stories=["read-receipts"])
        assert clean is not None, (event, status, ms)
    assert set(metrics_schema.KINDS["phone"]) == {"ts", "story", "account", "event", "status", "ms"}


def test_a_share_is_told_once_a_minute_and_only_what_was_held_since() -> None:
    """`take_share`: deltas since the last report, None inside the interval or when nothing was held."""
    from engine.social.turnstile import VOICE, WORLD, Turnstile

    gate = Turnstile()
    gate.held_seconds[WORLD] = 2.0
    gate.held_seconds[VOICE] = 1.0
    start = gate._told_at
    assert gate.take_share(60.0, now=start + 10.0) is None            # inside the minute
    assert gate.take_share(60.0, now=start + 61.0) == (2.0, 1.0)
    gate.held_seconds[VOICE] = 4.0
    assert gate.take_share(60.0, now=start + 100.0) is None            # a minute has not passed again
    assert gate.take_share(60.0, now=start + 125.0) == (0.0, 3.0)      # only what was held since
    assert gate.take_share(60.0, now=start + 200.0) is None            # nothing held since


# -- the hosted drain and a world turn / scene (v0.23.0 T28, spec §16.5, §20.1) --------------------------


@pytest.mark.loopback
def test_a_drain_waits_for_a_world_turn_still_waiting_at_the_turnstile(hosted_receipts) -> None:
    """
    A world turn waits for the turnstile BEFORE the turn lock, so it holds no lock the drain counts. The drain counts
    it all the same: it does not report drained while a turn (a scene's, a chance scene's, an arrival's) waits for
    its turn, and returns once the turn has finished.
    """
    from engine import hosting
    from engine.social import turnstile
    from tests.social_fixtures import _offered

    started = hosted_receipts.login_and_start("alice")
    session = hosted_receipts.session(started)
    store = hosted_receipts.scene.store
    _put_down(started)
    choice_id = _offered(hosted_receipts, started, "Tidy up a bit")
    gate = session.narration_turnstile
    assert gate.try_acquire_voice()                              # a voice call holds the turnstile
    answers: list[Any] = []
    t = threading.Thread(target=lambda: answers.append(started.client.post("/api/game/choice", json={
        "session_id": started.sid, "choice_id": choice_id})))
    t.start()
    try:
        _wait_until(lambda: gate.world_waiting == 1, timeout=10.0)
        assert not session.lock.locked()                         # waiting holds no turn lock: `turns_running` is 0
        assert store.turns_running() == 0
        assert hosting.drain(store, 0.3) is False                # but the drain does not call it drained
    finally:
        gate.release(turnstile.VOICE)
        t.join(30.0)
    assert answers and answers[0].status_code == 200, answers and answers[0].get_data(as_text=True)
    assert hosting.drain(store, 5.0) is True


@pytest.mark.loopback
def test_a_drain_parks_an_open_scene_and_what_was_due_for_the_resume(hosted_receipts, monkeypatch) -> None:
    """
    A scene opened by an arrival, replies due and recaps waiting: the drain finishes the turn (it waits for the lock),
    cancels the pass (nothing half-written), and flushes the run, so the saved state holds the open scene, the
    queued and held texts and every `recap_due` row the live state holds, and a resume reads the same.
    """
    from engine import hosting, social
    from engine.session.store import release_turn
    from engine.social import plans, voicer
    from tests.social_fixtures import _force_stage, _three_due_hosted
    from tests.test_social_plans import _willing_meet

    started = hosted_receipts.login_and_start("alice")
    threads = _three_due_hosted(hosted_receipts, started)
    session = hosted_receipts.session(started)
    state = session.engine.state
    pid = threads[0].split(":")[1]
    _force_stage(state, pid, "numbers")
    started.client.post("/api/phone/action", json={"session_id": started.sid, "action": "wait",
                                                    "target": "", "args": {"until": "1h"}, "text": ""})
    _put_down(started)
    _willing_meet(monkeypatch)
    monkeypatch.setattr(plans, "_arrival", lambda s, r, e, at: (at, at + 0.5 / 60.0))
    assert session.lock.acquire(blocking=False)
    try:
        assert plans.make(state, pid, kind="your_place", when="now", venue="")
    finally:
        release_turn(session)
    move = next(c for c in session.last_turn["choices"] if (c.get("intent") or {}).get("action") == "travel")
    turn = started.client.post("/api/game/choice", json={"session_id": started.sid, "choice_id": move["id"]})
    assert turn.status_code == 200, turn.get_data(as_text=True)
    assert social.scene_open(state) and session.dirty is True
    voicer.get_scheduler().resume()
    assert hosting.drain(hosted_receipts.scene.store, 5.0) is True
    assert session.dirty is False
    saved = session.saves.load(session.save_id)[0]
    assert (saved.social.get("scene") or {}).get("pid") == pid and social.scene_open(saved)
    assert saved.social["queue"] == state.social["queue"]
    assert {p: r.get("recap_due") for p, r in saved.social["people"].items() if r.get("recap_due")} == {
        p: r.get("recap_due") for p, r in state.social["people"].items() if r.get("recap_due")}
