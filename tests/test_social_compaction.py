"""
The phone save's bounded state (spec §17.2's size bound, v0.22.0 T26 fix round 1).

At every save (`saves.compact`): a DEAD thread -- its person faded, ended,
unmatched or blocked, nothing due or unread, quiet `social.archive_dead_after_days`
-- goes to the archive whole and keeps a stamp of its last message; a person the
player only swiped is cut to the swipe. Neither changes a mechanic: every reader
of a thread's messages reads the stamp once they run out, and `apps.touched`
reads only the swipe. (The harness's on-disk run holds the whole game to that:
tests/test_simulate_social.py.)
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from tests.social_fixtures import (  # noqa: F401
    _force_stage, _live_session, _matched_in, _phone, _replies_forced, _with, receipts_active,
)


def _talked(scene, session, thread: str, rounds: int = 3) -> None:
    """A few exchanges, each reply voiced (the stub) and read by the player."""
    from engine.social import voicer
    from tests.social_stub import StubVoice

    with _replies_forced():
        for i in range(rounds):
            _phone(scene, session, "send", target=thread, args={"kind": "text"}, text=f"hey {i}")
            voicer.run_until_quiet(session, StubVoice("zero"))     # v0.23.0: the reply is due at the send
            _phone(scene, session, "open_thread", target=thread)


def _readers(state, thread: str) -> dict[str, Any]:
    """Every value a reader of the thread's messages derives from them."""
    from engine.social import messaging

    t = messaging.thread(state, thread)
    row = messaging._thread_row(state, t, set())
    return {"row": row, "burst": messaging.player_burst(state, thread), "in_a_row": messaging._in_a_row(t),
            "last_at": messaging.last_at(t), "since": [messaging._player_wrote_since(t, h) for h in (0.0, 30.0)],
            "spoken": messaging.last_shown(t, spoken=True) is not None, "read_state": messaging._read_state(state, t),
            "open_thread": messaging._open_thread_section(state, None)}


def test_a_dead_quiet_thread_goes_to_the_archive_whole_and_reads_as_it_did(receipts_active, monkeypatch) -> None:
    from engine import social
    from engine.game import clock
    from engine.session.store import release_turn
    from engine.social import archive, messaging, saves

    monkeypatch.setattr(social, "setting", _with(social.setting, archive_dead_after_days=2))
    scene, session = _live_session()
    state = session.engine.state
    thread = _matched_in(session, "matchstick")
    pid = thread.split(":")[1]
    _talked(scene, session, thread)
    from engine.social import convo

    with monkeypatch.context() as quiet:
        quiet.setattr(convo, "on_player_send", lambda *a, **k: None)          # they never read it
        _phone(scene, session, "send", target=thread, args={"kind": "text"}, text="still there?")   # the burst
    assert session.lock.acquire(blocking=False)
    try:
        state.social["queue"] = [e for e in state.social["queue"] if e.get("pid") != pid]   # nothing more of theirs
        state.social["open_thread"] = ""                     # the player has opened something else since
        _force_stage(state, pid, "faded")
        clock.advance_time(state, 24.0)
        before = _readers(state, thread)
        count = len(state.social["threads"][thread]["messages"])
        saves.compact(session)                                       # not yet quiet two days: kept
        assert len(state.social["threads"][thread]["messages"]) == count
        clock.advance_time(state, 24.0)
        saves.compact(session)
        t = state.social["threads"][thread]
        assert t["messages"] == [] and t["stamp"] and t["archived"] >= count
        assert _readers(state, thread) == {**before, "since": before["since"]}
        page = archive.page(archive.save_dir(session), state, thread, "", 50)
        assert len(page["messages"]) == count and page["messages"][0]["bubbles"] == ["still there?"]
        # They come back: their message lands in the emptied thread, and it reads on from there.
        messaging.new_message(state, thread, pid, "text", bubbles=["hey stranger"])
        assert messaging.player_burst(state, thread) == 0
        assert messaging.last_shown(t)["bubbles"] == ["hey stranger"]
    finally:
        release_turn(session)


def test_a_live_or_unread_thread_is_never_emptied(receipts_active, monkeypatch) -> None:
    from engine import social
    from engine.game import clock
    from engine.session.store import release_turn
    from engine.social import saves

    monkeypatch.setattr(social, "setting", _with(social.setting, archive_dead_after_days=0))
    scene, session = _live_session()
    state = session.engine.state
    thread = _matched_in(session, "matchstick")
    pid = thread.split(":")[1]
    _talked(scene, session, thread)
    assert session.lock.acquire(blocking=False)
    try:
        state.social["queue"] = [e for e in state.social["queue"] if e.get("pid") != pid]
        clock.advance_time(state, 24.0 * 3)
        saves.compact(session)                                        # live: kept
        assert state.social["threads"][thread]["messages"]
        _force_stage(state, pid, "faded")
        state.social["threads"][thread]["unread"] = 1
        saves.compact(session)                                        # unread: kept
        assert state.social["threads"][thread]["messages"]
    finally:
        release_turn(session)


def test_a_swiped_only_person_keeps_only_the_swipe(receipts_active) -> None:
    from engine.session.store import release_turn
    from engine.social import apps, matching, saves
    from tests.social_fixtures import _top

    scene, session = _live_session()
    state = session.engine.state
    passed = _top(state, "matchstick")
    _phone(scene, session, "swipe", target=passed, args={"dir": "pass"})
    talked = _matched_in(session, "matchstick").split(":")[1]
    assert session.lock.acquire(blocking=False)
    try:
        matched = copy.deepcopy(state.social["people"][talked])
        assert set(state.social["people"][passed]) > {"apps"}
        assert saves.compact(session) >= 1
        assert state.social["people"][passed] == {"apps": {"matchstick": {"swiped": "pass"}}}
        assert apps.touched(state, passed, "matchstick")             # still off the deck
        assert not apps.touched(state, passed, "front_porch")
        assert state.social["people"][talked] == matched              # a match is a relationship: untouched
        # Met again (a later write): their arc point is drawn the same, on its stable key.
        matching.apply_effect(state, {"type": "social_person", "pid": passed, "set": {"x": 1}})
        assert "arc_point" in state.social["people"][passed]
    finally:
        release_turn(session)


def test_a_pending_like_is_not_compacted(receipts_active, monkeypatch) -> None:
    from engine.session.store import release_turn
    from engine.social import matching, saves
    from tests.social_fixtures import _top

    monkeypatch.setattr(matching, "likes_back", lambda *a, **k: True)
    scene, session = _live_session()
    state = session.engine.state
    pid = _top(state, "matchstick")
    _phone(scene, session, "swipe", target=pid, args={"dir": "like"})
    assert any(e["kind"] == "see_like" and e["pid"] == pid for e in state.social["queue"])
    assert session.lock.acquire(blocking=False)
    try:
        row = copy.deepcopy(state.social["people"][pid])
        saves.compact(session)
        assert state.social["people"][pid] == row                     # its see_like is still to come
    finally:
        release_turn(session)


def test_answered_requests_past_the_kept_count_are_forgotten(receipts_active, monkeypatch) -> None:
    from engine import social
    from engine.game.effects import apply_effect
    from engine.session.store import release_turn
    from engine.social import saves

    monkeypatch.setattr(social, "setting", _with(social.setting, requests_kept=2))
    scene, session = _live_session()
    state = session.engine.state
    pid = _matched_in(session, "matchstick").split(":")[1]
    assert session.lock.acquire(blocking=False)
    try:
        ids = []
        for i in range(5):
            made = apply_effect(state, {"type": "social_request", "op": "create", "pid": pid, "from": "them",
                                        "what": "number", "thread_id": ""})
            ids.append(made["request"]["id"])
        for rid in ids[:4]:
            apply_effect(state, {"type": "social_request", "op": "answer", "request_id": rid, "status": "no"})
        state.social["queue"].append({"at": 1e9, "seq": 999, "pid": pid, "kind": "plan_lapse", "request_id": ids[0]})
        saves.compact(session)
        kept = set(state.social["requests"])
        # The oldest answered one is named by a queued event; the newest two answered stay; the open one stays.
        assert kept == {ids[0], ids[2], ids[3], ids[4]}, kept
        refused = apply_effect(state, {"type": "social_request", "op": "forget", "request_id": ids[4]})
        assert not refused["ok"]                                       # an open request is never forgotten
    finally:
        release_turn(session)


def test_a_save_is_written_compact(receipts_active) -> None:
    """A save's envelope carries no indentation (spec §17.2's size bound): it reads back the same."""
    from engine.session.store import release_turn
    from engine.social import saves

    _scene, session = _live_session()
    assert session.lock.acquire(blocking=False)
    try:
        session.dirty = True
        assert saves.save_now(session)
    finally:
        release_turn(session)
    text = (session.saves.path_for(session.save_id) / "save.json").read_text(encoding="utf-8")
    assert "\n" not in text.strip() and ", " not in text[:200]
    loaded, _ = session.saves.load(session.save_id)
    assert loaded.social == session.engine.state.social


def test_a_thread_left_behind_for_a_messenger_is_emptied_too(receipts_active, monkeypatch) -> None:
    """Numbers swapped, they talk in Natter: the dating app's thread, quiet, goes to the archive whole."""
    from engine import social
    from engine.game import clock
    from engine.session.store import release_turn
    from engine.social import messaging, saves

    monkeypatch.setattr(social, "setting", _with(social.setting, archive_dead_after_days=2))
    scene, session = _live_session()
    state = session.engine.state
    thread = _matched_in(session, "matchstick")
    pid = thread.split(":")[1]
    _talked(scene, session, thread)
    assert session.lock.acquire(blocking=False)
    try:
        state.social["queue"] = [e for e in state.social["queue"] if e.get("pid") != pid]
        _force_stage(state, pid, "numbers")
        messaging.open_numbers(state, pid)
        natter = f"natter:{pid}"
        state.social["open_thread"] = natter                 # they talk in Natter now
        clock.advance_time(state, 24.0 * 3)
        saves.compact(session)
        assert state.social["threads"][thread]["messages"]            # quiet, but nothing newer elsewhere
        messaging.new_message(state, natter, "player", "text", bubbles=["over here now"])
        state.social["queue"] = [e for e in state.social["queue"] if e.get("pid") != pid]
        before, replies_in = _readers(state, thread), messaging.thread_for(state, pid)
        saves.compact(session)
        assert state.social["threads"][thread]["messages"] == [] and state.social["threads"][thread]["stamp"]
        assert state.social["threads"][natter]["messages"]              # the live one stays
        assert _readers(state, thread) == before
        assert messaging.thread_for(state, pid) == replies_in          # they answer where they did
    finally:
        release_turn(session)


@pytest.mark.parametrize("slug", ["clockwork-dark", "hue-and-cry"])
def test_another_storys_save_keeps_its_v0211_format(slug, tmp_path) -> None:
    """Only a phone story's save is compact (T26 fix round 2): every other story's is indented as in v0.21.1."""
    import json

    from engine.game import procgen
    from engine.games import registry
    from engine.persistence import SaveStore

    registry.activate(slug)
    try:
        state = procgen.new_game_state(player_name="Ash", seed=11)
        store = SaveStore(root=tmp_path / slug, slug=slug)
        save_id = store.save(state)
        text = (store.path_for(save_id) / "save.json").read_text(encoding="utf-8")
    finally:
        registry.deactivate()
    assert not state.social
    # v0.21.1's writer: json.dump(payload, indent=2, ensure_ascii=False), key order as built.
    assert text == json.dumps(json.loads(text), indent=2, ensure_ascii=False)
    assert "\n  " in text


def test_the_open_thread_is_never_emptied(receipts_active, monkeypatch) -> None:
    """Review I1: the thread the player last opened keeps its messages (the payload's `open_thread` shows them)."""
    from engine import social
    from engine.game import clock
    from engine.session.store import release_turn
    from engine.social import messaging, saves

    monkeypatch.setattr(social, "setting", _with(social.setting, archive_dead_after_days=1))
    scene, session = _live_session()
    state = session.engine.state
    thread = _matched_in(session, "matchstick")
    pid = thread.split(":")[1]
    _talked(scene, session, thread)
    assert state.social["open_thread"] == thread
    assert session.lock.acquire(blocking=False)
    try:
        state.social["queue"] = [e for e in state.social["queue"] if e.get("pid") != pid]
        _force_stage(state, pid, "faded")
        clock.advance_time(state, 24.0 * 3)
        shown = messaging._open_thread_section(state, None)
        saves.compact(session)
        assert state.social["threads"][thread]["messages"]
        assert messaging._open_thread_section(state, None) == shown and shown["messages"]
        state.social["open_thread"] = ""                                # opened elsewhere: now it goes
        saves.compact(session)
        assert state.social["threads"][thread]["messages"] == []
    finally:
        release_turn(session)


def test_a_dead_thread_is_remembered_by_its_recap_not_its_summary(receipts_active, monkeypatch) -> None:
    """
    v0.23.0 T6 (it replaces v0.22's "a dead thread costs no summary call"): a dead thread, emptied
    whole by the save, writes no thread summary; its last conversation is remembered by the person's
    recap, one call per closed episode, after which nothing more is due.
    """
    from engine import social
    from engine.game import clock
    from engine.session.store import release_turn
    from engine.social import memory, saves, voicer

    monkeypatch.setattr(social, "setting", _with(social.setting, archive_dead_after_days=1, state_messages=2, closed_thread_tail=2,
                                                 **{"memory.verbatim": 2}))
    scene, session = _live_session()
    state = session.engine.state
    thread = _matched_in(session, "matchstick")
    pid = thread.split(":")[1]
    _talked(scene, session, thread, rounds=4)
    calls: list[int] = []
    monkeypatch.setattr(voicer, "_summary_fn", lambda messages: calls.append(1) or "")
    assert session.lock.acquire(blocking=False)
    try:
        state.social["queue"] = [e for e in state.social["queue"] if e.get("pid") != pid]
        state.social["open_thread"] = ""
        _force_stage(state, pid, "faded")
        clock.advance_time(state, 24.0 * 3)
        if memory.recap_due_pids(state) == [] and state.social["people"][pid].get("episode"):
            from engine.game.effects import apply_effect

            apply_effect(state, {"type": "social_episode", "op": "close", "pid": pid})
        saves.compact(session)
        assert state.social["threads"][thread]["messages"] == [] and state.social["threads"][thread]["stamp"]
        due = len(state.social["people"][pid].get("recap_due") or [])
    finally:
        release_turn(session)
    assert due >= 1
    p = voicer.VoicePass(session, session.epoch)
    while voicer._recap_one(session, p):
        pass
    assert len(calls) == due and not state.social["people"][pid].get("recap_due")
    assert memory.person(state, pid)["episodes"]
    assert "summary" not in state.social["threads"][thread]
    assert voicer._recap_one(session, p) is False and len(calls) == due


def test_a_media_rows_spilled_message_is_read_from_the_archive(receipts_active, monkeypatch) -> None:
    """Review I3: a save may spill a media row's message before its job runs; the row finds it in the archive."""
    from engine import social
    from engine.session.store import release_turn
    from engine.social import archive, media, saves

    monkeypatch.setattr(social, "setting", _with(social.setting, state_messages=2, closed_thread_tail=2))
    scene, session = _live_session()
    state = session.engine.state
    thread = _matched_in(session, "matchstick")
    _talked(scene, session, thread)
    assert session.lock.acquire(blocking=False)
    try:
        for m in state.social["threads"][thread]["messages"]:   # read: unread messages stay in state (keep_for)
            if m["from"] != "player" and m.get("read_at") is None:
                m["read_at"] = state.world_clock_hours
        from engine.game.effects import apply_effect

        pid = state.social["threads"][thread]["pid"]
        if state.social["people"][pid].get("episode"):        # the conversation over: its messages may leave
            apply_effect(state, {"type": "social_episode", "op": "close", "pid": pid})
        saves.compact(session)
        first = archive.archived(archive.save_dir(session), thread)[0]                # spilled by a save
        assert first["id"] not in {m["id"] for m in state.social["threads"][thread]["messages"]}
        row = {"thread_id": thread, "message_id": first["id"], "caption": "", "kind": "voice"}
        assert media._message_of(state, row) is None                      # state alone: gone
        found = media._message_of(state, row, archive.save_dir(session))
        assert found is not None and found["id"] == first["id"] and found["bubbles"] == first["bubbles"]
        assert media._voice_words(state, row, archive.save_dir(session)) == " ".join(first["bubbles"])
    finally:
        release_turn(session)
