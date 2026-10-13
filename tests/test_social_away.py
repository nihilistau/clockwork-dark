"""
READ RECEIPTS: away and resume (v0.22.0 T16, spec §15, §2.3's survival test).

The away advance (one `advance_time` for the whole absence, capped, recorded,
stamped and saved), the resume frame's lock screen, the voicing pass a
resume and a join request, the run's 19:00 start, and the 72-hour survival
test: the phone reads no hunger, hp or stamina, so an absence changes only
the time and what arrived.
"""

from __future__ import annotations

import json

import pytest

from tests.social_fixtures import (  # noqa: F401
    _live_session, _matched_in, _with, hosted_receipts, receipts_active, receipts_state,
)

NOW = 1_800_000_000.0


def _wall_hours_ago(state, hours: float, now: float = NOW) -> float:
    """Stamp last_active_wall `hours` before `now` through the effect; return `now`."""
    from engine.game.effects import apply_effect

    apply_effect(state, {"type": "social_settings", "field": "last_active_wall", "value": now - hours * 3600.0})
    return now


def _saved_away_from(session, hours: float, now: float = NOW) -> float:
    """The run's save stamped as last active `hours` before `now`, written under its turn lock."""
    from engine.session.store import release_turn
    from engine.social import saves

    assert session.lock.acquire(blocking=False)
    try:
        _wall_hours_ago(session.engine.state, hours, now)
        assert saves.save_now(session)
    finally:
        release_turn(session)
    return now


def _clock_at(monkeypatch: pytest.MonkeyPatch, now: float) -> None:
    import time as time_module

    monkeypatch.setattr(time_module, "time", lambda: now)


def test_the_advance_is_capped(receipts_state) -> None:
    from engine.social import away

    now = _wall_hours_ago(receipts_state, 200)
    assert away.away_hours(receipts_state, now) == 72.0


def test_a_clock_that_went_backwards_adds_nothing(receipts_state) -> None:
    from engine.social import away

    now = _wall_hours_ago(receipts_state, 0)
    assert away.away_hours(receipts_state, now - 3600.0) == 0.0


def test_a_run_never_stamped_has_no_absence(receipts_state) -> None:
    from engine.social import away

    assert receipts_state.social["last_active_wall"] == 0.0
    assert away.away_hours(receipts_state, NOW) == 0.0


def test_mode_none_advances_nothing(receipts_active, monkeypatch) -> None:
    from engine import social
    from engine.social import away

    monkeypatch.setattr(social, "setting", _with(social.setting, away={"mode": "none", "rate": 1.0, "max_hours": 72}))
    _scene, session = _live_session()
    state = session.engine.state
    now = _wall_hours_ago(state, 10)
    clock = state.world_clock_hours
    assert away.away_hours(state, now) == 0.0
    assert away.apply_on_resume(session, wall=lambda: now) is None
    assert state.world_clock_hours == clock
    assert state.social["last_active_wall"] == now          # still stamped
    assert not session.lock.locked()


def test_fractional_hours_are_kept(receipts_active) -> None:
    from engine.social import away

    _scene, session = _live_session()
    state = session.engine.state
    now = NOW
    from engine.game.effects import apply_effect

    apply_effect(state, {"type": "social_settings", "field": "last_active_wall", "value": now - 5400.0})
    clock = state.world_clock_hours
    record = away.apply_on_resume(session, wall=lambda: now)
    assert record == {"kind": "away", "hours": pytest.approx(1.5, abs=1e-9), "real_seconds": 5400.0}
    assert state.world_clock_hours - clock == pytest.approx(1.5, abs=1e-9)
    assert state.social["away_since"] == clock
    assert not session.lock.locked()


def test_the_advance_is_recorded_and_saved(receipts_active) -> None:
    from engine.social import away

    _scene, session = _live_session()
    now = _wall_hours_ago(session.engine.state, 2)
    record = away.apply_on_resume(session, wall=lambda: now)
    path = session.saves.path_for(session.save_id) / "transcript.jsonl"
    lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert lines[-1] == record == {"kind": "away", "hours": 2.0, "real_seconds": 7200.0}
    loaded, _memory = session.saves.load(session.save_id)
    assert loaded.world_clock_hours == session.engine.state.world_clock_hours
    assert loaded.social["last_active_wall"] == now


def test_a_run_started_and_left_counts_its_first_absence(receipts_active, monkeypatch) -> None:
    """Review M1: a new run is stamped active at creation, so a resume with no action between still advances."""
    _clock_at(monkeypatch, NOW)
    scene, session = _live_session()                         # created and first saved at NOW; no phone action
    loaded, _memory = session.saves.load(session.save_id)
    assert loaded.social["last_active_wall"] == NOW
    clock = session.engine.state.world_clock_hours
    _clock_at(monkeypatch, NOW + 3600.0)
    again = scene.store.resume(session.save_id)
    assert again.engine.state.world_clock_hours - clock == pytest.approx(1.0, abs=1e-9)


def test_a_failed_away_save_keeps_its_line_for_the_retry(receipts_active, monkeypatch) -> None:
    """Review M4: the away record's transcript line is written by the retry that succeeds."""
    from engine.scenes import default_state
    from engine.session.store import release_turn
    from engine.social import away, saves

    _scene, session = _live_session()
    now = _wall_hours_ago(session.engine.state, 2)
    real = default_state._autosave
    failures = [True]

    def autosave(*args, **kwargs):
        if failures and failures.pop():
            return False                                     # the first write fails
        return real(*args, **kwargs)

    monkeypatch.setattr(default_state, "_autosave", autosave)
    record = away.apply_on_resume(session, wall=lambda: now)
    assert session.dirty is True and session.pending_entry == record
    assert session.lock.acquire(blocking=False)
    try:
        assert saves.save_now(session)                       # the timer's retry: no entry of its own
    finally:
        release_turn(session)
    path = session.saves.path_for(session.save_id) / "transcript.jsonl"
    lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert lines[-1] == record
    assert session.pending_entry is None


def test_two_resumes_never_add_the_day_twice(receipts_active, monkeypatch) -> None:
    scene, session = _live_session()
    clock = session.engine.state.world_clock_hours
    now = _saved_away_from(session, 30)
    _clock_at(monkeypatch, now)
    first = scene.store.resume(session.save_id)
    assert first.engine.state.world_clock_hours - clock == pytest.approx(30.0, abs=1e-9)
    _clock_at(monkeypatch, now + 1800.0)                    # thirty real minutes later
    second = scene.store.resume(session.save_id)
    assert second.engine.state.world_clock_hours - clock == pytest.approx(30.5, abs=1e-9)
    assert second.engine.state.social["last_active_wall"] == now + 1800.0


def test_a_held_turn_lock_skips_the_advance(receipts_active) -> None:
    from engine.social import away

    _scene, session = _live_session()
    now = _wall_hours_ago(session.engine.state, 5)
    clock = session.engine.state.world_clock_hours
    from engine.session.store import release_turn

    assert session.lock.acquire(blocking=False)
    try:
        assert away.apply_on_resume(session, wall=lambda: now) is None
    finally:
        release_turn(session)
    assert session.engine.state.world_clock_hours == clock


def test_the_next_mechanics_action_clears_away_since(receipts_active) -> None:
    from engine.social import away
    from tests.social_fixtures import _phone

    scene, session = _live_session()
    now = _wall_hours_ago(session.engine.state, 3)
    away.apply_on_resume(session, wall=lambda: now)
    assert away.away_since(session.engine.state) is not None
    _phone(scene, session, "wait", args={"until": "15m"})
    assert away.away_since(session.engine.state) is None
    assert "away_since" not in session.engine.state.social


def test_the_lock_screen_counts_what_arrived(receipts_active, monkeypatch) -> None:
    from engine.session.store import release_turn
    from engine.social import events, matching, messaging, saves

    monkeypatch.setattr(messaging, "on_match", lambda *a, **k: None)    # no opener of their own
    monkeypatch.setattr(events, "daily_hooks", [])                      # no initiation crosses 04:00
    scene, session = _live_session()
    state = session.engine.state
    tid_a = _matched_in(session, "matchstick")
    tid_b = _matched_in(session, "matchstick")
    tid_c = _matched_in(session, "matchstick")
    pid_a, pid_b, pid_c = (t.split(":", 1)[1] for t in (tid_a, tid_b, tid_c))
    start = state.world_clock_hours
    reply = {"situation": "reply", "kind": "text"}
    assert session.lock.acquire(blocking=False)
    try:
        events.push(state, start + 0.5, pid_a, "reply", thread_id=tid_a, decision=reply)
        events.push(state, start + 0.6, pid_a, "reply", thread_id=tid_a, decision=reply)
        events.push(state, start + 0.7, pid_b, "reply", thread_id=tid_b, decision=reply)
        events.push(state, start + 0.8, pid_c, "expire", app="matchstick")
        _wall_hours_ago(state, 1.0)
        assert saves.save_now(session)
    finally:
        release_turn(session)
    _clock_at(monkeypatch, NOW)
    again = scene.store.resume(session.save_id)
    frame = again.last_turn
    assert frame["resumed"] is True and frame["choices"] == [] and frame["narration"] == ""
    screen = frame["lock_screen"]
    assert screen["lines"] == ["3 messages from 2 people", "1 match expired"]
    assert screen["text"] == "While you were away: 3 messages from 2 people, 1 match expired"
    assert [n["thread_id"] for n in screen["notifications"]] == [tid_a, tid_a, tid_b]
    assert matching.thread_id("matchstick", pid_c) in again.engine.state.social["threads"]


def test_a_failing_handler_still_leaves_the_away_record_and_lock_screen(receipts_active, monkeypatch) -> None:
    """Final review M2: a handler that raises mid-absence costs its event; the record, stamp and screen land."""
    from engine.session.store import release_turn
    from engine.social import events, messaging, saves

    monkeypatch.setattr(messaging, "on_match", lambda *a, **k: None)
    monkeypatch.setattr(events, "daily_hooks", [])

    def _boom(state, ev):
        raise KeyError("a broken row")

    monkeypatch.setitem(events._HANDLERS, "boom", _boom)
    scene, session = _live_session()
    state = session.engine.state
    tid = _matched_in(session, "matchstick")
    pid = tid.split(":", 1)[1]
    start = state.world_clock_hours
    assert session.lock.acquire(blocking=False)
    try:
        events.push(state, start + 0.3, pid, "boom")
        events.push(state, start + 0.5, pid, "reply", thread_id=tid, decision={"situation": "reply", "kind": "text"})
        _wall_hours_ago(state, 1.0)
        assert saves.save_now(session)
    finally:
        release_turn(session)
    _clock_at(monkeypatch, NOW)
    again = scene.store.resume(session.save_id)
    assert again.engine.state.social["away_since"] == pytest.approx(start)
    assert again.engine.state.social["last_active_wall"] == NOW
    assert again.last_turn["lock_screen"]["lines"] == ["1 message from 1 person"]
    path = again.saves.path_for(again.save_id) / "transcript.jsonl"
    lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert lines[-1]["kind"] == "away" and lines[-1]["hours"] == pytest.approx(1.0)


def _joined(scene, session) -> dict:
    """A fresh page's `join_session`: its `game_started` body."""
    sock = scene.socketio.test_client(scene.app)
    try:
        sock.emit("join_session", {"session_id": session.session_id})
        (started,) = [e["args"][0] for e in sock.get_received() if e["name"] == "game_started"]
    finally:
        sock.disconnect()
    return started


def test_a_reload_after_acting_past_the_lock_screen_does_not_show_it_again(receipts_active, monkeypatch) -> None:
    """Final review M5: once the player has acted, the saved opening no longer carries that absence's counts."""
    from engine.session.store import release_turn
    from engine.social import events, messaging, saves
    from tests.social_fixtures import _phone

    monkeypatch.setattr(messaging, "on_match", lambda *a, **k: None)
    monkeypatch.setattr(events, "daily_hooks", [])
    scene, session = _live_session()
    state = session.engine.state
    tid = _matched_in(session, "matchstick")
    pid = tid.split(":", 1)[1]
    assert session.lock.acquire(blocking=False)
    try:
        events.push(state, state.world_clock_hours + 0.5, pid, "reply", thread_id=tid,
                    decision={"situation": "reply", "kind": "text"})
        _wall_hours_ago(state, 1.0)
        assert saves.save_now(session)
    finally:
        release_turn(session)
    _clock_at(monkeypatch, NOW)
    again = scene.store.resume(session.save_id)
    assert _joined(scene, again)["opening"]["lock_screen"]["text"].startswith("While you were away")
    _phone(scene, again, "wait", args={"until": "15m"})
    assert not (_joined(scene, again)["opening"].get("lock_screen") or {}).get("text")


def test_the_state_and_join_answers_build_the_phone_holding_the_turn_lock(receipts_active, monkeypatch) -> None:
    """Final review M4: tried (never waited for) on a short schedule; still busy, the answer is built anyway."""
    from engine.game.state import GameState

    scene, session = _live_session()
    held: list[bool] = []
    real = GameState.to_client_dict
    monkeypatch.setattr(GameState, "to_client_dict", lambda self: held.append(session.lock.locked()) or real(self))
    got = scene.app.test_client().get(f"/api/game/state?session_id={session.session_id}")
    assert got.status_code == 200 and got.get_json()["state"]["phone"]
    started = _joined(scene, session)
    assert started["turn_running"] is False and started["state"]["phone"]
    assert held == [True, True] and not session.lock.locked()
    held.clear()
    assert session.lock.acquire(blocking=False)                       # a turn that outlasts the retries
    try:
        got = scene.app.test_client().get(f"/api/game/state?session_id={session.session_id}")
        assert got.status_code == 200 and got.get_json()["state"]["phone"]
        assert _joined(scene, session)["turn_running"] is True
    finally:
        session.lock.release()


def test_the_lock_screen_counts_new_matches(receipts_active, monkeypatch) -> None:
    from engine.social import away, messaging

    monkeypatch.setattr(messaging, "on_match", lambda *a, **k: None)
    _scene, session = _live_session()
    state = session.engine.state
    since = state.world_clock_hours
    _matched_in(session, "matchstick")
    _matched_in(session, "front_porch")
    screen = away.lock_screen(state, since)
    assert screen["lines"] == ["2 new matches"]
    assert away.lock_screen(state, state.world_clock_hours)["lines"] == []


def test_a_resume_with_no_absence_shows_an_empty_lock_screen(receipts_active, monkeypatch) -> None:
    _clock_at(monkeypatch, NOW)                              # created and resumed at one wall instant
    scene, session = _live_session()
    again = scene.store.resume(session.save_id)              # no real time between: nothing passes
    assert again.last_turn["lock_screen"] == {"lines": [], "text": "", "notifications": []}
    assert again.engine.state.world_clock_hours == session.engine.state.world_clock_hours


def test_a_resume_requests_a_pass_and_nothing_is_stuck_typing(receipts_active, monkeypatch) -> None:
    from engine.social import voicer

    calls: list[tuple[str, int]] = []
    monkeypatch.setattr(voicer, "request", lambda s: calls.append((s.session_id, s.epoch)))
    scene, session = _live_session()
    session.typing.add("natter:p0001")                       # a mark of the old build's pass
    now = _saved_away_from(session, 4)
    _clock_at(monkeypatch, now)
    sock = scene.socketio.test_client(scene.app)
    sock.emit("resume", {"save_id": session.save_id})
    received = sock.get_received()
    resumed = [r for r in received if r["name"] == "game_resumed"]
    assert len(resumed) == 1
    live = scene.store.require(session.session_id)
    assert calls == [(live.session_id, live.epoch)]
    assert live.typing == set()                              # typing marks are per build
    threads = resumed[0]["args"][0]["state"]["phone"]["threads"]
    assert not any(row["typing"] for row in threads)
    sock.emit("join_session", {"session_id": session.session_id})
    assert len(calls) == 2                                   # a join asks again (idempotent in the scheduler)
    sock.disconnect()


def test_72_hours_away_changes_only_time_and_arrivals(receipts_active, monkeypatch) -> None:
    """§2.3 (F15): survival moves hunger and hp underneath; the phone never reads them."""
    import time as time_module

    from engine.social import away as away_module
    from engine.social import payload

    scene, session = _live_session()
    state = session.engine.state
    before = payload.phone_block(state)
    now = _wall_hours_ago(state, 72)
    monkeypatch.setattr(time_module, "time", lambda: now)
    record = away_module.apply_on_resume(session)
    after = payload.phone_block(state)
    assert record["hours"] == 72.0
    assert session.engine.state.flags.get("dead") is not True
    changed = {k for k in after if after[k] != before[k]}
    # The payload module's own declaration (F14): a section added later (T29's contacts) joins it there.
    assert changed <= payload.TIME_VARYING_SECTIONS, changed - payload.TIME_VARYING_SECTIONS
    assert "now" in changed                                  # not vacuous: the time did move
    assert after["refusal"] is None


def test_no_phone_module_reads_hunger_hp_or_stamina() -> None:
    from pathlib import Path

    repo = Path(__file__).resolve().parents[1]          # anchored: a wrong cwd must not pass vacuously (F18)
    banned = {"hunger", "hp", "stamina"}
    engine_files = sorted((repo / "engine" / "social").rglob("*.py"))
    assert engine_files, "engine/social has no files: the scan would be vacuous"
    client_root = repo / "ui" / "src" / "stories" / "read-receipts"   # exists since T27
    client_files = sorted(list(client_root.rglob("*.js")) + list(client_root.rglob("*.jsx")))
    assert client_files, "ui/src/stories/read-receipts has no files: the client scan would be vacuous"
    for path in engine_files + client_files:
        text = path.read_text(encoding="utf-8")
        for word in banned:
            assert f'"{word}"' not in text and f".{word}" not in text and f"'{word}'" not in text, (path, word)
    for name in ("texter.md", "thread_summary.md", "date_recap.md"):
        text = (repo / "games" / "read-receipts" / "prompts" / name).read_text(encoding="utf-8").lower()
        assert not any(f" {w} " in text for w in banned)


def test_a_new_run_starts_at_19_on_day_1(receipts_state) -> None:
    from engine.social import events

    assert (receipts_state.world_day, receipts_state.world_hour) == (1, 19)
    assert receipts_state.world_clock_hours == 19.0
    dailies = [e["at"] for e in receipts_state.social["queue"] if e["kind"] == "daily"]
    assert dailies == [events.next_daily(19.0)] == [28.0]    # the first daily: day 2, 04:00


def test_every_other_story_still_starts_at_8() -> None:
    from engine.game import procgen

    state = procgen.new_game_state(player_name="Sam", seed=4242)
    assert state.world_clock_hours == 8.0


def test_a_start_hour_outside_the_day_is_refused(receipts_active, monkeypatch) -> None:
    from engine import social
    from engine.social import creation

    real = social.data
    monkeypatch.setattr(social, "data", lambda name: {"start_hour": 24} if name == "creation" else real(name))
    with pytest.raises(ValueError, match="creation.yaml: start_hour"):
        creation.start_hours()


def test_a_hosted_resume_advances_only_its_own_accounts_run(hosted_receipts, monkeypatch) -> None:
    """Per account (spec §5.4, §15.2): a resume advances the account's own run; another's save is missing."""
    store = hosted_receipts.scene.store
    alice = hosted_receipts.login_and_start("alice")
    bob = hosted_receipts.login_and_start("bob")
    mine = store.get(alice.sid, owner=alice.account_id)
    theirs = store.get(bob.sid, owner=bob.account_id)
    clock, their_clock = mine.engine.state.world_clock_hours, theirs.engine.state.world_clock_hours
    now = _saved_away_from(mine, 5)
    _clock_at(monkeypatch, now)
    bob.sock.emit("resume", {"save_id": mine.save_id})
    assert [r["name"] for r in bob.sock.get_received()] == ["resume_failed"]
    alice.sock.emit("resume", {"save_id": mine.save_id})
    (resumed,) = [r for r in alice.sock.get_received() if r["name"] == "game_resumed"]
    assert "lock_screen" in resumed["args"][0]["opening"]
    again = store.get(alice.sid, owner=alice.account_id)
    assert again.engine.state.world_clock_hours - clock == pytest.approx(5.0, abs=1e-9)
    assert store.get(bob.sid, owner=bob.account_id).engine.state.world_clock_hours == their_clock
