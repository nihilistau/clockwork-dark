"""
READ RECEIPTS: when the phone saves (v0.22.0 T10, spec §16.5, §17.2-17.3).

The dirty timer, the saves inside an action, the purge an admin end makes
safe from every phone save path, the archive spill and its paging, and the
build epoch liveness reads.
"""

from __future__ import annotations

import pytest

from tests.social_fixtures import (  # noqa: F401
    _live_session, _matched_in, _phone, _top, _wait_until, _with, hosted_receipts, receipts_active,
)


@pytest.fixture(autouse=True)
def _no_dirty_saver_outlives_its_test():
    """Each test here stops the process's DirtySaver at teardown, so no heap outlives its test."""
    yield
    from engine.social import saves

    saves.reset_dirty_saver()


def test_a_swipe_with_no_follow_up_is_on_disk_within_autosave_seconds(receipts_active, monkeypatch, tmp_path) -> None:
    import time as _time

    from engine import social
    from engine.social import saves
    from engine.scenes.default_scene import create_app

    monkeypatch.setattr(social, "setting", _with(social.setting, autosave_seconds=0.2))
    scene, app = create_app(testing=True)
    http = app.test_client()
    sid = http.post("/api/game/new", json={"seed": 3}).get_json()["session_id"]
    session = scene.store.require(sid)
    store = session.saves
    before = store.load(session.save_id)[0].world_clock_hours
    http.post("/api/phone/action", json={"session_id": sid, "action": "wait", "args": {"until": "15m"}})
    deadline = _time.monotonic() + 5.0
    while _time.monotonic() < deadline and store.load(session.save_id)[0].world_clock_hours == before:
        _time.sleep(0.05)
    assert store.load(session.save_id)[0].world_clock_hours == pytest.approx(before + 0.25)
    assert session.dirty is False


@pytest.mark.parametrize("mid_turn", [False, True], ids=["idle", "mid-turn"])
def test_a_purge_after_an_admin_end_is_not_undone_by_any_phone_save(hosted_receipts, mid_turn) -> None:
    """R22: every phone save path after an admin end writes nothing (spec §16.5, §17.2)."""
    import shutil

    from engine.social import saves

    run = hosted_receipts.login_and_start("alice")
    store = hosted_receipts.scene.store
    session = store.require(run.sid, owner=run.account_id)
    run.client.post("/api/phone/action", json={"session_id": run.sid, "action": "wait", "args": {"until": "15m"}})
    assert session.dirty is True
    folder = session.saves.path_for(session.save_id)
    if mid_turn:
        assert session.lock.acquire(blocking=False)          # a turn holds the lock: end_owner marks it ending
    store.end_owner(run.account_id)
    if mid_turn:
        assert session.ending is True
    shutil.rmtree(folder)                                     # the admin's purge
    if mid_turn:
        saves.save_now(session)                               # the running action's own save: refused (ending)
        saves.release_turn(session)                           # unlock, then end_after_turn (Plan decision 31)
    saver = saves.DirtySaver()
    saver.schedule(session, 0.0)                              # the timer fires anyway
    _wait_until(lambda: not saver._heap)
    saver.stop()
    saves.flush_all()
    store.sweep_idle(ttl_minutes=1)
    assert not folder.exists()


def test_the_dirty_timer_skips_a_released_session(receipts_active, monkeypatch) -> None:
    from engine.social import saves

    scene, session = _live_session()
    session.dirty = True
    calls: list[str] = []
    monkeypatch.setattr(saves, "save_now", lambda s, **k: calls.append(s.session_id))
    scene.store.delete(session.session_id)
    saver = saves.DirtySaver()
    saver.schedule(session, 0.0)
    _wait_until(lambda: not saver._heap)
    saver.stop()
    assert calls == []


def test_the_dirty_timer_retries_a_busy_lock(receipts_active, monkeypatch) -> None:
    from engine.social import saves

    _scene, session = _live_session()
    session.dirty = True
    calls: list[str] = []
    monkeypatch.setattr(saves, "save_now", lambda s, **k: calls.append("saved") or setattr(s, "dirty", False))
    session.lock.acquire()
    saver = saves.DirtySaver()
    saver.schedule(session, 0.0)
    _wait_until(lambda: saver._heap and saver._heap[0][0] > 0.0)       # re-queued 1 s out
    session.lock.release()
    _wait_until(lambda: calls == ["saved"], timeout=3.0)
    saver.stop()


def test_a_match_saves_inside_the_action(receipts_active, monkeypatch) -> None:
    from engine.social import matching, saves

    scene, session = _live_session()
    monkeypatch.setattr(matching, "likes_back", lambda *a, **k: True)
    monkeypatch.setattr(matching, "see_like_hours", lambda *a, **k: 0.5)   # inside one wait's 8 h cap (F16)
    saved: list[dict] = []
    real = saves.save_now
    monkeypatch.setattr(saves, "save_now", lambda s, **k: saved.append(k) or real(s, **k))
    _phone(scene, session, "swipe", target=_top(session.engine.state, "matchstick"), args={"dir": "like"})
    _phone(scene, session, "wait", args={"until": "next"})      # the see_like fires: a match
    assert session.engine.state.social["threads"], "no match was made"
    assert any((k.get("entry") or {}).get("phone") == "wait" for k in saved)
    assert session.dirty is False


def test_the_archive_moves_old_messages_and_dedupes_a_crash_duplicate(receipts_active, monkeypatch) -> None:
    from engine import social
    from engine.social import archive, messaging, saves

    monkeypatch.setattr(social, "setting", _with(social.setting, state_messages=5))
    monkeypatch.setattr(messaging, "schedule_reply", lambda *a, **k: None)   # the player's 12 alone in the thread
    scene, session = _live_session()
    thread = _matched_in(session, "matchstick")
    for i in range(12):
        _phone(scene, session, "send", target=thread, args={"kind": "text"}, text=f"m{i}")
    with session.lock:
        saves.save_now(session)
    assert len(session.engine.state.social["threads"][thread]["messages"]) == 5
    assert session.engine.state.social["threads"][thread]["archived"] == 7
    path = session.saves.path_for(session.save_id) / "phone_archive.jsonl"
    assert len(path.read_text(encoding="utf-8").splitlines()) == 7
    # The save the run reloads with holds the five, and counts the seven archived.
    reloaded = session.saves.load(session.save_id)[0].social["threads"][thread]
    assert len(reloaded["messages"]) == 5 and reloaded["archived"] == 7
    path.write_text(path.read_text(encoding="utf-8") * 2, encoding="utf-8")   # a crash duplicate
    page = archive.page(session.saves.path_for(session.save_id), session.engine.state, thread, before="", limit=50)
    ids = [m["id"] for m in page["messages"]]
    assert len(ids) == len(set(ids)) == 12


def test_paging_reads_state_then_archive_and_checks_the_owner(hosted_receipts) -> None:
    alice = hosted_receipts.login_and_start("alice")
    bob = hosted_receipts.login_and_start("bob")
    session = hosted_receipts.scene.store.require(alice.sid, owner=alice.account_id)
    thread = _matched_in(session, "matchstick")
    for i in range(3):
        alice.client.post("/api/phone/action", json={"session_id": alice.sid, "action": "send", "target": thread,
                                                     "args": {"kind": "text"}, "text": f"p{i}"})
    resp = bob.client.get(f"/api/phone/thread/{thread}?session_id={alice.sid}")
    assert resp.status_code == 404                          # another account's run answers as missing
    mine = alice.client.get(f"/api/phone/thread/{thread}?session_id={alice.sid}")
    assert mine.status_code == 200                          # F18: the owner's case is asserted exactly
    expected = [m["id"] for m in reversed(session.engine.state.social["threads"][thread]["messages"])]
    assert [m["id"] for m in mine.get_json()["messages"]] == expected[:50]   # newest first


def test_no_transcript_line_per_timer_save(receipts_active) -> None:
    from engine.social import saves

    _scene, session = _live_session()
    path = session.saves.path_for(session.save_id) / "transcript.jsonl"
    before = path.read_text(encoding="utf-8") if path.exists() else ""
    session.dirty = True
    with session.lock:
        saves.save_now(session)
    assert (path.read_text(encoding="utf-8") if path.exists() else "") == before


def test_epoch_is_new_per_build(receipts_active) -> None:
    scene, session = _live_session()
    again = scene.store.resume(session.save_id)
    assert again.epoch != session.epoch and again.session_id == session.session_id


def test_the_receipt_carries_no_effects_to_the_client(receipts_active) -> None:
    """The skill's `effects` (hidden values among them) are read by step 4 and taken off the receipt."""
    scene, session = _live_session()
    turn = _phone(scene, session, "swipe", target=_top(session.engine.state, "matchstick"), args={"dir": "like"})
    (receipt,) = turn["receipts"]
    assert receipt["result"]["ok"] is True and "effects" not in receipt["result"]
    assert session.engine.state.social["last_active_wall"] > 0


def test_a_skill_result_lists_every_effect_its_events_applied(receipts_active, monkeypatch) -> None:
    """`effects` holds the action's own effects and those its events applied while time passed (the match)."""
    import json

    from engine.game.engine import GameEngine
    from engine.skills.builtin import social as phone_skills
    from engine.social import matching

    monkeypatch.setattr(matching, "likes_back", lambda *a, **k: True)
    monkeypatch.setattr(matching, "see_like_hours", lambda *a, **k: 0.5)
    _scene, session = _live_session()
    state = session.engine.state
    monkeypatch.setattr(phone_skills, "get_active_engine", lambda: GameEngine(state))
    liked = json.loads(phone_skills.social_swipe(target=_top(state, "matchstick"), args={"dir": "like"}))
    assert any(r.get("type") == "social_queue" for r in liked["effects"])
    waited = json.loads(phone_skills.social_wait(args={"until": "next"}))
    kinds = [r.get("type") for r in waited["effects"]]
    assert "social_match" in kinds and "social_stage" in kinds
    assert {r.get("save_reason") for r in waited["effects"]} >= {"match", "stage"}


def test_the_spill_never_moves_a_due_message_and_remembers_an_archived_opener(receipts_active, monkeypatch) -> None:
    from engine import social
    from engine.game.effects import apply_effect
    from engine.social import archive, messaging

    monkeypatch.setattr(social, "setting", _with(social.setting, state_messages=2))
    monkeypatch.setattr(messaging, "schedule_reply", lambda *a, **k: None)
    _scene, session = _live_session()
    state = session.engine.state
    thread = _matched_in(session, "matchstick")
    pid = state.social["threads"][thread]["pid"]
    with session.lock:
        messaging.new_message(state, thread, pid, "text", bubbles=["hi"], decision={"situation": "opener"})
        messaging.new_message(state, thread, pid, "text", voiced=False, decision={"situation": "reply"})
        for i in range(3):
            messaging.new_message(state, thread, "player", "text", bubbles=[f"p{i}"])
        moved = archive.spill(session)
    rows = state.social["threads"][thread]["messages"]
    assert moved == 1 and rows[0]["voiced"] is False and len(rows) == 4   # stopped at the due one
    assert state.social["people"][pid]["opener_landed"] is True
    assert messaging._opener_taken(state, pid)
    refused = apply_effect(state, {"type": "social_message", "op": "archive", "thread_id": thread, "count": 1})
    assert refused["ok"] is False                                          # the due one never leaves


def test_paging_walks_back_through_the_archive_by_before(receipts_active, monkeypatch) -> None:
    from engine import social
    from engine.social import archive, messaging, saves

    monkeypatch.setattr(social, "setting", _with(social.setting, state_messages=3))
    monkeypatch.setattr(messaging, "schedule_reply", lambda *a, **k: None)
    scene, session = _live_session()
    thread = _matched_in(session, "matchstick")
    for i in range(8):
        _phone(scene, session, "send", target=thread, args={"kind": "text"}, text=f"w{i}")
    with session.lock:
        saves.save_now(session)
    http = scene.app.test_client()
    first = http.get(f"/api/phone/thread/{thread}?session_id={session.session_id}&limit=4").get_json()
    ids = [m["id"] for m in first["messages"]]
    assert len(ids) == 4 and first["more"] is True
    assert all("decision" not in m for m in first["messages"])            # the client's view of a row
    rest = http.get(f"/api/phone/thread/{thread}?session_id={session.session_id}&before={ids[-1]}").get_json()
    every = ids + [m["id"] for m in rest["messages"]]
    assert len(every) == len(set(every)) == 8 and rest["more"] is False
    assert [int(i[1:]) for i in every] == sorted((int(i[1:]) for i in every), reverse=True)
    assert archive.page(None, session.engine.state, "nope:p1", "", 10)["messages"] == []
    missing = http.get(f"/api/phone/thread/nope:p1?session_id={session.session_id}")
    assert missing.status_code == 404
    opened = _phone(scene, session, "open_thread", target=thread)["state"]["phone"]["open_thread"]
    assert opened["more"] is True                                           # older rows sit in the archive


def test_a_keeps_nothing_store_schedules_and_writes_nothing(receipts_active) -> None:
    from engine.social import saves

    _scene, session = _live_session()
    session.saves.keeps_nothing = True
    try:
        saves.mark_dirty(session, "action")
        assert session.dirty is True and saves._saver is None              # no timer, no thread
        with session.lock:
            assert saves.save_now(session) is False
        assert session.dirty is False
    finally:
        del session.saves.keeps_nothing


def test_the_idle_sweep_and_a_second_run_flush_a_dirty_phone(hosted_receipts) -> None:
    """flush_taken (spec §16.5): the sweep and hosted one-run-per-account save a dirty run before letting go."""
    alice = hosted_receipts.login_and_start("alice")
    store = hosted_receipts.scene.store
    session = store.require(alice.sid, owner=alice.account_id)
    before = session.saves.load(session.save_id)[0].world_clock_hours
    alice.client.post("/api/phone/action", json={"session_id": alice.sid, "action": "wait", "args": {"until": "1h"}})
    assert session.dirty is True
    store._seen[alice.sid] = 0.0                                            # idle since long ago
    assert alice.sid in store.sweep_idle(ttl_minutes=1)
    assert session.dirty is False
    assert session.saves.load(session.save_id)[0].world_clock_hours == before + 1.0

    bob = hosted_receipts.login_and_start("bob")
    first = store.require(bob.sid, owner=bob.account_id)
    bob.client.post("/api/phone/action", json={"session_id": bob.sid, "action": "wait", "args": {"until": "1h"}})
    assert first.dirty is True
    again = bob.client.post("/api/game/new", json={"seed": 4})             # the account's other run is released
    assert again.status_code == 200
    assert first.dirty is False
    assert first.saves.load(first.save_id)[0].world_clock_hours == before + 1.0


def test_a_drain_and_shutdown_flush_every_free_dirty_run(hosted_receipts) -> None:
    from engine import hosting
    from engine.social import saves

    run = hosted_receipts.login_and_start("alice")
    store = hosted_receipts.scene.store
    session = store.require(run.sid, owner=run.account_id)
    run.client.post("/api/phone/action", json={"session_id": run.sid, "action": "wait", "args": {"until": "15m"}})
    assert session.dirty is True
    assert hosting.drain(store, 1.0) is True
    assert session.dirty is False
    session.dirty = True
    assert session.lock.acquire(blocking=False)                            # a turn holds it: left to its holder
    try:
        assert saves.flush_all(store) == 0 and session.dirty is True
    finally:
        saves.release_turn(session)
    assert saves.flush_all(store) == 1 and session.dirty is False


def test_save_now_refuses_an_ending_session_before_the_spill(receipts_active, monkeypatch) -> None:
    """R22: the ending check comes FIRST -- the spill, which writes, never runs for an ending session."""
    from engine.social import archive, saves

    _scene, session = _live_session()
    spilled: list[str] = []
    monkeypatch.setattr(archive, "spill", lambda s: spilled.append(s.session_id) or 0)
    session.dirty = True
    session.ending = True
    with session.lock:
        assert saves.save_now(session) is False
    assert spilled == [] and session.dirty is True


def test_a_torn_last_line_is_closed_before_the_next_append(receipts_active, monkeypatch) -> None:
    """Review minor 2: a crash mid-append leaves a line with no newline; the next batch's first row survives."""
    import json

    from engine import social
    from engine.social import archive, messaging, saves

    monkeypatch.setattr(social, "setting", _with(social.setting, state_messages=2))
    monkeypatch.setattr(messaging, "schedule_reply", lambda *a, **k: None)
    scene, session = _live_session()
    thread = _matched_in(session, "matchstick")
    path = session.saves.path_for(session.save_id) / archive.ARCHIVE_FILE
    path.write_text('{"id": "m999", "thread_id": "' + thread + '", "fr', encoding="utf-8")   # torn
    for i in range(3):
        _phone(scene, session, "send", target=thread, args={"kind": "text"}, text=f"t{i}")
    with session.lock:
        saves.save_now(session)
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2                                                  # the torn one, then the batch
    first = json.loads(lines[1])
    page = archive.page(path.parent, session.engine.state, thread, before="", limit=50)
    assert first["id"] in [m["id"] for m in page["messages"]]


def test_a_failed_write_leaves_the_run_dirty_and_retries(receipts_active, monkeypatch) -> None:
    """Review minor 3: `_autosave` answers False on a failed write; `save_now` keeps the run dirty and requeues it."""
    from engine.social import saves

    _scene, session = _live_session()
    session.dirty = True

    def broken(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(session.saves, "save", broken)
    with session.lock:
        assert saves.save_now(session) is False
    assert session.dirty is True
    assert [entry[2] for entry in saves.get_dirty_saver()._heap] == [session]   # the retry is queued
    monkeypatch.undo()
    with session.lock:
        assert saves.save_now(session) is True
    assert session.dirty is False


def test_a_dirty_run_queues_one_timer_entry(receipts_active) -> None:
    """Review minor 6: however many actions dirty a run, the heap holds one entry for it."""
    from engine.social import saves

    _scene, session = _live_session()
    saver = saves.DirtySaver()
    try:
        for _ in range(5):
            saver.schedule(session, 1e12)
        assert len(saver._heap) == 1
    finally:
        saver.stop()


def test_a_local_resume_of_the_same_save_loads_the_old_runs_phone(receipts_active, monkeypatch) -> None:
    """Review minor 4 (ruling): the live run is flushed BEFORE the resume loads, so the new run has its state."""
    import time as time_module

    # One wall instant for the action and the resume: the resume's away advance (T16) adds nothing.
    monkeypatch.setattr(time_module, "time", lambda: 1_800_000_000.0)
    scene, session = _live_session()
    _phone(scene, session, "wait", args={"until": "1h"})
    assert session.dirty is True
    clock = session.engine.state.world_clock_hours
    again = scene.store.resume(session.save_id)
    assert session.dirty is False
    assert again.engine.state.world_clock_hours == clock


def test_a_resume_skips_the_flush_of_a_run_mid_turn(receipts_active, caplog) -> None:
    """The ruling's other half: an old run holding its turn lock is not waited for -- skipped, logged at INFO."""
    import logging

    scene, session = _live_session()
    _phone(scene, session, "wait", args={"until": "1h"})
    assert session.lock.acquire(blocking=False)
    try:
        with caplog.at_level(logging.INFO, logger="engine.session.store"):
            again = scene.store.resume(session.save_id)
    finally:
        session.lock.release()
    assert session.dirty is True
    assert again.engine.state.world_clock_hours < session.engine.state.world_clock_hours
    assert any("Not flushed before its resume" in r.getMessage() for r in caplog.records)


def _whole_file_page(save_dir, state, thread_id, before, limit):
    """The page as T10 read it, the whole file every time: the reference `archive.page` must equal (T26)."""
    from engine.social import archive, messaging

    t = messaging.thread(state, thread_id)
    rows = {}
    for row in t.get("messages") or []:
        rows.setdefault(str(row["id"]), row)
    for row in archive.archived(save_dir, thread_id):
        rows.setdefault(str(row["id"]), row)
    ordered = sorted((m for m in rows.values() if messaging.shown(m)), key=lambda m: archive._number(m.get("id")),
                     reverse=True)
    cut = archive._number(before)
    if cut >= 0:
        ordered = [m for m in ordered if archive._number(m.get("id")) < cut]
    size = max(1, min(archive.PAGE_MAX, int(limit or archive.PAGE_MAX)))
    return {"thread_id": thread_id, "messages": [messaging.message_view(state, t, m) for m in ordered[:size]],
            "more": len(ordered) > size}


def _archived_session(monkeypatch, sends: int = 14):
    """A live session whose thread spilled most of its messages, behind 400 rows of another thread's."""
    import json

    from engine import social
    from engine.social import archive, messaging, saves

    monkeypatch.setattr(social, "setting", _with(social.setting, state_messages=4))
    monkeypatch.setattr(messaging, "schedule_reply", lambda *a, **k: None)
    scene, session = _live_session()
    thread = _matched_in(session, "matchstick")
    path = session.saves.path_for(session.save_id) / archive.ARCHIVE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    other = [json.dumps({"id": f"m{9000 + i}", "thread_id": "natter:p9999", "from": "player", "kind": "text",
                         "at": 0.0, "bubbles": ["x"], "voiced": True}) for i in range(400)]
    path.write_text("\n".join(other) + "\n", encoding="utf-8")
    for i in range(sends):
        _phone(scene, session, "send", target=thread, args={"kind": "text"}, text=f"t{i}")
        if i == sends // 2:
            with session.lock:
                saves.save_now(session)
    with session.lock:
        saves.save_now(session)
    with path.open("a", encoding="utf-8") as handle:           # a crash duplicate of the newest batch, and junk
        handle.write(path.read_text(encoding="utf-8").splitlines()[-1] + "\nnot json\n")
    return session, thread, path


def test_a_thread_page_reads_the_archive_from_its_end_and_equals_the_whole_files_page(
        receipts_active, monkeypatch) -> None:
    """T26: the page route reads under the turn lock, so it reads only what the page needs."""
    from engine.social import archive

    session, thread, path = _archived_session(monkeypatch)
    state = session.engine.state
    assert len(archive.archived(path.parent, thread)) >= 8, "nothing spilled: the check is vacuous"
    for limit in (1, 3, 5, 50):
        before, pages = "", 0
        while True:
            page = archive.page(path.parent, state, thread, before, limit)
            assert page == _whole_file_page(path.parent, state, thread, before, limit), (before, limit)
            pages += 1
            if not page["more"]:
                break
            before = page["messages"][-1]["id"]
        assert pages >= 2 or limit == 50


def test_a_thread_page_never_decodes_another_threads_lines(receipts_active, monkeypatch) -> None:
    """The tail read stops once it holds the page, and never decodes a line that is not the thread's."""
    import json as real_json
    import types

    from engine.social import archive

    session, thread, path = _archived_session(monkeypatch)
    decoded: list[str] = []

    def loads(raw, *a, **k):
        row = real_json.loads(raw, *a, **k)
        decoded.append(str(row.get("thread_id")) if isinstance(row, dict) else "")
        return row

    monkeypatch.setattr(archive, "json", types.SimpleNamespace(loads=loads, dumps=real_json.dumps))
    state = session.engine.state
    first = state.social["threads"][thread]["messages"][0]["id"]
    page = archive.page(path.parent, state, thread, first, 2)
    assert len(page["messages"]) == 2 and page["more"]
    assert decoded and set(decoded) == {thread}, set(decoded)
    assert len(decoded) <= 4, decoded                       # the page, one more, the crash duplicate
