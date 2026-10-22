"""
Conversations as episodes (v0.23.0 spec §3.3, §3.5, §4.1-§4.7, §19.2; T3):
instant replies inside an episode, bursts and sends while a pass writes,
availability and the schedule boundary, the nudge to a natural end, modes,
the per-episode-start draws, lapses, initiations by window, the costs and
`wait`'s targets.

Every draw a test depends on is forced (lesson 1): `convo._target_draw`,
`_ghost_factor`, `_reply_factor`, `available`, `boundary_minutes` or the
habits, patched. No test passes or fails by its seed.
"""

from __future__ import annotations

import dataclasses

import pytest

from tests.social_fixtures import (  # noqa: F401
    _act, _open_episode, _replies_forced, _set_clock, _set_person, matched, receipts_active, receipts_state,
)


def _no_boundary(monkeypatch) -> None:
    """No schedule boundary within reach: the draw-free term a reply's end depends on, forced (lesson 1)."""
    from engine.social import convo

    monkeypatch.setattr(convo, "boundary_minutes", lambda state, pid_, at: None)


def _theirs(state, thread):
    return [m for m in state.social["threads"][thread]["messages"] if m["from"] not in ("player", "system")]


def test_a_reply_in_an_open_episode_lands_at_the_sends_minute(receipts_state, matched, monkeypatch) -> None:
    thread = matched("matchstick")
    pid = thread.split(":")[1]
    _no_boundary(monkeypatch)                                  # no schedule edge decides the reply (M3)
    with _replies_forced():
        _open_episode(receipts_state, pid, thread)
        sent_at = receipts_state.world_clock_hours
        assert _act(receipts_state, "send", target=thread, args={"kind": "text"}, text="how was work?")["success"]
    due = [m for m in _theirs(receipts_state, thread) if m["voiced"] is False]
    assert len(due) == 1 and due[0]["at"] == pytest.approx(sent_at)
    assert receipts_state.world_clock_hours == pytest.approx(sent_at + 1 / 60)      # costs.text: 1 minute


def test_ten_exchanges_need_no_wait(receipts_state, matched, monkeypatch) -> None:
    """Acceptance 1, engine half: 10 exchanges, no `wait`, each reply at its send's minute."""
    from engine.social import convo
    from tests.social_fixtures import _voice_all
    from tests.social_stub import StubVoice

    thread = matched("matchstick")
    pid = thread.split(":")[1]
    _no_boundary(monkeypatch)                                  # no schedule edge decides the reply (M3)
    monkeypatch.setattr(convo, "_target_draw", lambda state, pid_, rng: 40)
    monkeypatch.setattr(convo, "boundary_minutes", lambda state, pid_, at: None)    # no schedule edge (lesson 1)
    with _replies_forced():
        _open_episode(receipts_state, pid, thread)
        for i in range(10):
            sent_at = receipts_state.world_clock_hours
            assert _act(receipts_state, "send", target=thread, args={"kind": "text"},
                        text=f"message {i} about the climb")["success"]
            due = [m for m in _theirs(receipts_state, thread) if m["voiced"] is False]
            assert len(due) == 1 and due[0]["at"] == pytest.approx(sent_at)
            _voice_all(receipts_state, StubVoice("zero"))
    assert receipts_state.social["people"][pid]["episode"]["exchanges"] >= 10
    assert all(m["voiced"] is not False for m in _theirs(receipts_state, thread))
    assert not [e for e in receipts_state.social["queue"] if e["pid"] == pid and e["kind"] == "read"]


def test_a_burst_before_the_mark_is_one_reply_after_the_mark_is_two(receipts_state, matched, monkeypatch) -> None:
    """§4.3, I6: unmarked -> re-decided in place; marked -> the commit queues the next decision.
    Pre-flight F15: `after_commit` returns False while an unvoiced reply-family message waits
    (`_due_reply`), so the commit is SIMULATED by setting the marked message `voiced = True` first,
    exactly as the pass's commit would. Then one NEW unvoiced decision exists, not two."""
    from engine.social import convo

    thread = matched("matchstick")
    pid = thread.split(":")[1]
    _no_boundary(monkeypatch)                                  # no schedule edge decides the reply (M3)
    with _replies_forced():
        _open_episode(receipts_state, pid, thread)
        _act(receipts_state, "send", target=thread, args={"kind": "text"}, text="hey")
        _act(receipts_state, "send", target=thread, args={"kind": "text"}, text="also")
        due = [m for m in _theirs(receipts_state, thread) if m["voiced"] is False]
        assert len(due) == 1                                   # unmarked burst: re-decided in place
        marked_id = due[0]["id"]
        with convo.marking([marked_id]):
            _act(receipts_state, "send", target=thread, args={"kind": "text"}, text="and one more")
        assert [m["id"] for m in _theirs(receipts_state, thread) if m["voiced"] is False] == [marked_id]
        through = [m for m in receipts_state.social["threads"][thread]["messages"]
                   if m["from"] == "player"][1]["id"]           # the snapshot read up to "also"
        next(m for m in _theirs(receipts_state, thread) if m["id"] == marked_id)["voiced"] = True  # the commit
        assert convo.after_commit(receipts_state, pid, thread, through, receipts_state.world_clock_hours) is True
    fresh = [m for m in _theirs(receipts_state, thread) if m["voiced"] is False]
    assert len(fresh) == 1 and fresh[0]["id"] != marked_id     # exactly one new decision, for "and one more"


def test_a_burst_counts_one_exchange(receipts_state, matched, monkeypatch) -> None:
    """A burst re-decided in place answers once: the episode counts one exchange for it, not three."""
    thread = matched("matchstick")
    pid = thread.split(":")[1]
    _no_boundary(monkeypatch)                                  # no schedule edge decides the reply (M3)
    with _replies_forced():
        _open_episode(receipts_state, pid, thread)
        for text in ("hey", "also", "and another thing"):
            _act(receipts_state, "send", target=thread, args={"kind": "text"}, text=text)
    due = [m for m in _theirs(receipts_state, thread) if m["voiced"] is False]
    assert len(due) == 1 and receipts_state.social["people"][pid]["episode"]["exchanges"] == 1
    assert due[0]["decision"]["min_bubbles"] == 2              # three messages: at least two bubbles (§4.5)


def test_a_pass_commit_after_a_send_queues_the_next_decision(receipts_state, matched, monkeypatch) -> None:
    """I6 through the real pass: a send while the reply is MARKED (a pass is wording it) is answered by the
    NEXT decision the commit queues -- two replies, neither discarded."""
    from engine.social import convo, voicer, voicing
    from tests.social_fixtures import _VOICE_SESSIONS, _voice_all
    from tests.social_stub import StubVoice

    thread = matched("matchstick")
    pid = thread.split(":")[1]
    _no_boundary(monkeypatch)                                  # no schedule edge decides the reply (M3)
    with _replies_forced():
        _open_episode(receipts_state, pid, thread)
        _act(receipts_state, "send", target=thread, args={"kind": "text"}, text="what did you get up to today?")
        _voice_all(receipts_state, StubVoice("zero"))          # builds the session; voices the first reply
        session = _VOICE_SESSIONS[id(receipts_state)][1]
        _act(receipts_state, "send", target=thread, args={"kind": "text"}, text="and how was the climb?")
        p = voicer.VoicePass(session, session.epoch)
        snaps = voicer.snapshot(session, p)                    # MARKED for p
        assert len(snaps) == 1
        with convo.marking(tuple(session.voicing)):           # the player types while the model writes
            _act(receipts_state, "send", target=thread, args={"kind": "text"}, text="also, are you free friday?")
        reply = voicing.voice(snaps[0], StubVoice("zero"))
        assert session.lock.acquire(blocking=False)
        try:
            assert voicer._apply_reply(session, p.id, reply, p=p) in ("ok", "fallback")
        finally:
            session.lock.release()
        assert p.rerun is True
    due = [m for m in _theirs(receipts_state, thread) if m["voiced"] is False]
    voiced = [m for m in _theirs(receipts_state, thread) if m["voiced"] is True]
    assert len(due) == 1 and len(voiced) == 2                  # the marked reply committed, the next one due


def test_a_chatty_worker_at_the_end_of_their_shift_does_not_sign_off(receipts_state, matched, monkeypatch) -> None:
    """(Review I1) A status change into one where they are MORE available is no boundary: a chatty worker at
    16:50, the shift ending at 17:00, talks on -- coming off work is when talk opens up, not when it ends."""
    from engine.social import attrs, behaviour, convo

    thread = matched("matchstick")
    pid = thread.split(":")[1]
    monkeypatch.setattr(attrs, "of", lambda state, pid_: {
        "habits": {"at_work": "chatty", "late_night": "no", "in_company": "glances"},
        "pace": 1.0, "topics": [], "home": ""})
    monkeypatch.setattr(behaviour, "status_at", lambda person, at: "work" if 9 <= at % 24 < 17 else "free")
    monkeypatch.setattr(convo, "_target_draw", lambda state, pid_, rng: 40)
    _set_clock(receipts_state, hour=16)
    from engine.game import clock
    clock.advance_time(receipts_state, 50 / 60)                     # 16:50
    assert convo.boundary_minutes(receipts_state, pid, receipts_state.world_clock_hours) is None
    _open_episode(receipts_state, pid, thread, target=40)
    _act(receipts_state, "send", target=thread, args={"kind": "text"}, text="nearly done for the day?")
    due = next(m for m in _theirs(receipts_state, thread) if m["voiced"] is False)
    assert due["decision"]["end"] == "none"


def test_going_out_is_a_boundary_and_coming_home_is_not(receipts_state, matched, monkeypatch) -> None:
    """(Review I1) free -> out caps them (quick): a boundary, worded "about to head out"; out -> free is none."""
    from engine.social import attrs, behaviour, convo

    pid = matched("matchstick").split(":")[1]
    monkeypatch.setattr(attrs, "of", lambda state, pid_: {
        "habits": {"at_work": "never", "late_night": "no", "in_company": "glances"},
        "pace": 1.0, "topics": [], "home": ""})
    monkeypatch.setattr(behaviour, "status_at", lambda person, at: "out" if 19 <= at % 24 < 23 else "free")
    day = 24 * 3
    assert convo.boundary_minutes(receipts_state, pid, day + 18 + 50 / 60) == pytest.approx(10.0)
    assert convo._reason_words(receipts_state, pid, "boundary", day + 18 + 50 / 60) == "you're about to head out"
    assert convo.boundary_minutes(receipts_state, pid, day + 22 + 50 / 60) is None


def test_a_left_on_read_spell_holds_the_reader(receipts_state, matched, monkeypatch) -> None:
    """(Review M1, ruling) Left on read, they do not read again until their next boundary or
    `left_on_read_quiet_minutes`, whichever is first: a send in between does not redraw the episode's start."""
    from engine import social
    from engine.game import clock
    from engine.social import convo

    thread = matched("matchstick")
    pid = thread.split(":")[1]
    draws = []
    monkeypatch.setattr(convo, "_ghost_factor", lambda state, pid_: 0.0)
    monkeypatch.setattr(convo, "_reply_factor", lambda state, pid_: draws.append(1) or 0.0)
    monkeypatch.setattr(convo, "available", lambda state, pid_, at: convo.Availability(True))
    _no_boundary(monkeypatch)
    quiet = float(social.data("conversation")["left_on_read_quiet_minutes"]) / 60.0
    sent = receipts_state.world_clock_hours
    _act(receipts_state, "send", target=thread, args={"kind": "text"}, text="hey")       # read at once: left on read
    assert len(draws) == 1 and convo.episode(receipts_state, pid) is None
    clock.advance_time(receipts_state, 5 / 60)
    _act(receipts_state, "send", target=thread, args={"kind": "text"}, text="hello?")
    _act(receipts_state, "send", target=thread, args={"kind": "text"}, text="??")
    assert len(draws) == 1                                                                # no redraw
    reads = [e for e in receipts_state.social["queue"] if e["pid"] == pid and e["kind"] == "read"]
    assert len(reads) == 1 and reads[0]["at"] == pytest.approx(sent + quiet)
    # A boundary sooner than the quiet time ends the hold sooner.
    monkeypatch.setattr(convo, "boundary_minutes", lambda state, pid_, at: 30.0)
    assert convo.read_hold_until(receipts_state, pid, sent) == pytest.approx(sent + 0.5)


def test_a_send_after_their_sign_off_is_read_when_they_are_back(receipts_state, matched, monkeypatch) -> None:
    """I6 at the end of a conversation: the player wrote while the pass worded their sign-off, and they have
    nothing more to say (`after_left` 0). The commit queues no reply now; their read waits for their return."""
    from engine.game.effects import apply_effect
    from engine.social import convo

    thread = matched("matchstick")
    pid = thread.split(":")[1]
    with _replies_forced():
        back = receipts_state.world_clock_hours + 3.0                          # their shift ends (forced)
        monkeypatch.setattr(convo, "next_available", lambda state, pid_, at: max(at, back))
        _open_episode(receipts_state, pid, thread)
        _act(receipts_state, "send", target=thread, args={"kind": "text"}, text="ok go, have a good shift")
        due = next(m for m in _theirs(receipts_state, thread) if m["voiced"] is False)
        through = [m for m in receipts_state.social["threads"][thread]["messages"] if m["from"] == "player"][-1]["id"]
        apply_effect(receipts_state, {"type": "social_episode", "op": "end", "pid": pid, "end": "signed_off",
                                      "at": receipts_state.world_clock_hours, "reason": "x"})
        receipts_state.social["people"][pid]["episode"]["after_left"] = 0       # the draw, forced
        with convo.marking([due["id"]]):
            _act(receipts_state, "send", target=thread, args={"kind": "text"}, text="oh and one more thing")
        due["voiced"] = True                                                   # the commit
        now = receipts_state.world_clock_hours
        chars = list(receipts_state.social["people"][pid]["episode"]["player_chars"])
        assert convo.after_commit(receipts_state, pid, thread, through, now) is False
        # (Review M4) the message's length was noted at its send, never a second time by the commit.
        assert receipts_state.social["people"][pid]["episode"]["player_chars"] == chars
    assert not [m for m in _theirs(receipts_state, thread) if m["voiced"] is False]
    read = next(e for e in receipts_state.social["queue"] if e["pid"] == pid and e["kind"] == "read")
    assert read["at"] == pytest.approx(back) == pytest.approx(receipts_state.social["people"][pid]["episode"]["away_until"])


def test_an_unavailable_persons_read_lands_at_a_boundary(receipts_state, matched, monkeypatch) -> None:
    from engine.social import attrs, convo

    thread = matched("matchstick")
    pid = thread.split(":")[1]
    # Pre-flight F16: force the habits too, so `available`'s `late_night == "sometimes"` branch (which
    # reads the REAL `behaviour.status_at`) can never fire by seed.
    monkeypatch.setattr(attrs, "of", lambda state, pid_: {
        "habits": {"at_work": "never", "late_night": "no", "in_company": "glances"},
        "pace": 1.0, "topics": [], "home": ""})
    monkeypatch.setattr(convo, "_status", lambda state, pid_, at: "asleep" if at % 24 < 7 else "free")
    _set_clock(receipts_state, hour=2)
    _act(receipts_state, "send", target=thread, args={"kind": "text"}, text="you up?")
    read = next(e for e in receipts_state.social["queue"] if e["pid"] == pid and e["kind"] == "read")
    assert read["at"] % 24 == pytest.approx(7.0)


@pytest.mark.parametrize("habit,status,expected", [
    ({"late_night": "night_owl", "at_work": "never", "in_company": "glances"}, "night_owl_3am", True),
    ({"late_night": "no", "at_work": "chatty", "in_company": "glances"}, "work", True),
    ({"late_night": "no", "at_work": "never", "in_company": "glances"}, "work", False),
])
def test_night_owls_answer_late_and_never_workers_do_not(receipts_state, matched, monkeypatch, habit, status,
                                                         expected) -> None:
    from engine.social import attrs, behaviour, convo

    pid = matched("matchstick").split(":")[1]
    monkeypatch.setattr(attrs, "of", lambda state, pid_: {"habits": habit, "pace": 1.0, "topics": [], "home": ""})
    if status == "night_owl_3am":
        monkeypatch.setattr(behaviour, "status_at", lambda p, at: "asleep" if 1 <= at % 24 < 8 else "free")
        at = 24 * 3 + 3.0
    else:
        monkeypatch.setattr(behaviour, "status_at", lambda p, at: "work")
        at = 24 * 3 + 11.0
    assert convo.available(receipts_state, pid, at).yes is expected


def test_a_sign_off_names_its_boundary(receipts_state, matched, monkeypatch) -> None:
    from engine.social import convo

    thread = matched("matchstick")
    pid = thread.split(":")[1]
    monkeypatch.setattr(convo, "boundary_minutes", lambda state, pid_, at: 5.0)
    monkeypatch.setattr(convo, "_status", lambda state, pid_, at: "work" if at % 24 >= 7 else "free")
    with _replies_forced():
        _open_episode(receipts_state, pid, thread)
        _act(receipts_state, "send", target=thread, args={"kind": "text"}, text="morning!")
    due = next(m for m in _theirs(receipts_state, thread) if m["voiced"] is False)
    assert due["decision"]["end"] == "sign_off" and due["decision"]["reason"]
    episode = receipts_state.social["people"][pid]["episode"]
    assert episode["end"] == "signed_off" and episode["end_reason"] == due["decision"]["reason"]


def test_a_sign_offs_reason_is_the_engines_words(receipts_state, matched, monkeypatch) -> None:
    """The reason comes from their schedule: a shift starting reads "your shift starts at <hour>"."""
    from engine.social import convo

    pid = matched("matchstick").split(":")[1]
    monkeypatch.setattr(convo, "boundary_minutes", lambda state, pid_, at: 10.0)
    monkeypatch.setattr(convo, "_status", lambda state, pid_, at: "work" if at % 24 >= 9 else "free")
    at = 24 * 3 + 8 + 50 / 60                                   # 08:50, the shift at 09:00
    assert convo._reason_words(receipts_state, pid, "boundary", at) == "your shift starts at 9"


def test_modes_grow_with_the_episode(receipts_state, matched, monkeypatch) -> None:
    from engine.social import convo, growth

    thread = matched("matchstick")
    pid = thread.split(":")[1]
    monkeypatch.setattr(convo, "_target_draw", lambda state, pid_, rng: 60)
    monkeypatch.setattr(convo, "boundary_minutes", lambda state, pid_, at: None)
    monkeypatch.setattr(growth, "depth", lambda state, pid_: 2)
    monkeypatch.setattr(convo, "_touched_at_depth", lambda state, pid_, ep: True)
    modes = []
    with _replies_forced():
        _open_episode(receipts_state, pid, thread)
        for _ in range(6):
            _act(receipts_state, "send", target=thread, args={"kind": "text"}, text="x" * 120)
            due = next(m for m in _theirs(receipts_state, thread) if m["voiced"] is False)
            modes.append(due["decision"]["mode"])
            due["voiced"] = True                               # a test shortcut: no pass, only the shape matters
    assert modes[0] == "quick" and "deep" in modes[3:]


def test_no_ghost_inside_an_episode_and_ghosts_between(receipts_state, matched, monkeypatch) -> None:
    from engine.social import convo

    thread = matched("matchstick")
    pid = thread.split(":")[1]
    monkeypatch.setattr(convo, "_ghost_factor", lambda state, pid_: 1.0)
    monkeypatch.setattr(convo, "_reply_factor", lambda state, pid_: 1.0)
    monkeypatch.setattr(convo, "available", lambda state, pid_, at: convo.Availability(True))
    _open_episode(receipts_state, pid, thread)                # opened: no draw inside it
    _act(receipts_state, "send", target=thread, args={"kind": "text"}, text="hi")
    assert not receipts_state.social["people"][pid].get("ghosted")
    for m in _theirs(receipts_state, thread):
        m["voiced"] = True                                     # a test shortcut: the pass voiced the reply
    from engine.game.effects import apply_effect
    apply_effect(receipts_state, {"type": "social_episode", "op": "close", "pid": pid,
                                  "at": receipts_state.world_clock_hours, "end": "lapsed"})
    _act(receipts_state, "send", target=thread, args={"kind": "text"}, text="hello again")
    from engine.game import clock
    clock.advance_time(receipts_state, 24)
    assert receipts_state.social["people"][pid]["ghosted"] is True


def test_an_episode_lapses_after_the_gap(receipts_state, matched) -> None:
    from engine.game import clock

    thread = matched("matchstick")
    pid = thread.split(":")[1]
    _open_episode(receipts_state, pid, thread)
    clock.advance_time(receipts_state, 1.0)                    # past episode_gap_minutes (45)
    person = receipts_state.social["people"][pid]
    assert person["episode"] is None and person["recap_due"][-1]["end"] == "lapsed"
    assert person["episodes_done"] == 1


def test_an_exchange_pushes_the_lapse_back(receipts_state, matched, monkeypatch) -> None:
    """The gap runs from the last exchange, not the start: a chat 30 minutes in is still going 30 later."""
    from engine.game import clock
    from engine.social import convo

    thread = matched("matchstick")
    pid = thread.split(":")[1]
    monkeypatch.setattr(convo, "boundary_minutes", lambda state, pid_, at: None)
    with _replies_forced():
        _open_episode(receipts_state, pid, thread)
        clock.advance_time(receipts_state, 0.5)
        _act(receipts_state, "send", target=thread, args={"kind": "text"}, text="still there?")
        clock.advance_time(receipts_state, 0.5)
    assert convo.episode(receipts_state, pid) is not None
    lapses = [e for e in receipts_state.social["queue"] if e["pid"] == pid and e["kind"] == "episode_lapse"]
    assert len(lapses) == 1


def test_a_closed_episode_ticks_growth_and_a_good_sign_off_gains(receipts_state, matched) -> None:
    from engine.game.effects import apply_effect
    from engine.social import growth

    thread = matched("matchstick")
    pid = thread.split(":")[1]
    _set_person(receipts_state, pid, growth={**growth.record(receipts_state, pid), "guarded": 1, "guarded_left": 3})
    _open_episode(receipts_state, pid, thread)
    at = receipts_state.world_clock_hours
    apply_effect(receipts_state, {"type": "social_episode", "op": "end", "pid": pid, "at": at, "end": "signed_off",
                                  "reason": "it's a natural place to leave it"})
    _set_person(receipts_state, pid, warmth=float(receipts_state.social["people"][pid].get("warmth", 0)) + 5)
    before = growth.record(receipts_state, pid)["openness"]
    apply_effect(receipts_state, {"type": "social_episode", "op": "close", "pid": pid, "at": at})
    rec = growth.record(receipts_state, pid)
    assert rec["guarded_left"] == 2                             # the tick
    assert rec["openness"] > before                             # good_end: warmth rose across a sign-off
    assert receipts_state.social["people"][pid]["recap_due"][-1]["end"] == "signed_off"


def test_each_exchange_fills_openness(receipts_state, matched, monkeypatch) -> None:
    from engine.social import convo, growth

    thread = matched("matchstick")
    pid = thread.split(":")[1]
    monkeypatch.setattr(convo, "boundary_minutes", lambda state, pid_, at: None)
    with _replies_forced():
        _open_episode(receipts_state, pid, thread)
        before = growth.record(receipts_state, pid)["openness"]
        _act(receipts_state, "send", target=thread, args={"kind": "text"}, text="tell me about your week")
    assert growth.record(receipts_state, pid)["openness"] > before


def test_a_topic_label_with_punctuation_matches_whole_words(receipts_state, matched, monkeypatch) -> None:
    """(Review Focus 4) a label carrying regex characters is matched literally, on whole words."""
    from engine.social import convo

    assert convo.names_label("Have you seen their sister's band lately?", "their sister's band")
    assert convo.names_label("I write C++ for a living", "C++")
    assert convo.names_label("climbing (bouldering) tonight?", "climbing (bouldering)")
    assert not convo.names_label("sisters bands", "their sister's band")
    assert not convo.names_label("I love climbingwalls", "climbing")
    assert not convo.names_label("anything", "")


def test_naming_their_topic_gives_energy_back(receipts_state, matched, monkeypatch) -> None:
    from engine.social import convo, growth, population

    thread = matched("matchstick")
    pid = thread.split(":")[1]
    monkeypatch.setattr(convo, "boundary_minutes", lambda state, pid_, at: None)
    rows = growth.topics_of(receipts_state, pid)
    label = str(rows[0]["label"])
    real = population.profile
    monkeypatch.setattr(population, "profile",
                        lambda state, pid_: dataclasses.replace(real(state, pid_), hobbies=()))
    with _replies_forced():
        _open_episode(receipts_state, pid, thread)
        _act(receipts_state, "send", target=thread, args={"kind": "text"}, text=f"so, {label} -- tell me everything")
    ep = receipts_state.social["people"][pid]["episode"]
    assert rows[0]["id"] in ep["topics"]
    assert ep["energy"] == pytest.approx(100 - 6 + 3)           # one exchange, a topic named


def test_a_ghost_cancels_only_the_reply_family(receipts_state, matched, monkeypatch) -> None:
    """Pre-flight F7: a ghost drops `read`/`reply`/`initiate`/`double_text`/`episode_lapse` for the pid,
    and leaves every other kind (here a stand-in `promise_close`, pushed directly) queued."""
    from engine.game import clock
    from engine.social import convo, events

    thread = matched("matchstick")
    pid = thread.split(":")[1]
    monkeypatch.setattr(convo, "_ghost_factor", lambda state, pid_: 1.0)
    monkeypatch.setattr(convo, "next_available", lambda state, pid_, at: at)    # the read lands now (F16)
    at = receipts_state.world_clock_hours
    events.push(receipts_state, at + 5, pid, "promise_close", promise_id="pr1")   # a social_queue write
    _act(receipts_state, "send", target=thread, args={"kind": "text"}, text="hi")   # queues the read
    clock.advance_time(receipts_state, 1)                     # the read fires; the ghost draw is forced
    kinds_left = [e["kind"] for e in receipts_state.social["queue"] if e["pid"] == pid]
    assert receipts_state.social["people"][pid]["ghosted"] is True
    assert not set(kinds_left) & events.REPLY_FAMILY
    assert "promise_close" in kinds_left                      # (a match's own `expire` row may sit beside it)


def test_left_on_read_opens_no_episode(receipts_state, matched, monkeypatch) -> None:
    from engine.game import clock
    from engine.social import convo

    thread = matched("matchstick")
    pid = thread.split(":")[1]
    monkeypatch.setattr(convo, "_ghost_factor", lambda state, pid_: 0.0)
    monkeypatch.setattr(convo, "_reply_factor", lambda state, pid_: 0.0)
    monkeypatch.setattr(convo, "next_available", lambda state, pid_, at: at)
    _act(receipts_state, "send", target=thread, args={"kind": "text"}, text="hi")
    clock.advance_time(receipts_state, 0.5)
    assert convo.episode(receipts_state, pid) is None and not _theirs(receipts_state, thread)


def test_the_players_schedule_reads_their_creation_job(receipts_state) -> None:
    """Pre-flight F24: a nights player (creation's `attributes.job`, e.g. bartender) resolves to `nights`,
    not to the office default."""
    from engine.social import windows

    receipts_state.social.setdefault("player", {}).setdefault("attributes", {})["job"] = "bartender"
    try:
        assert windows.schedule_of(receipts_state, "player").job_shape == "nights"
    finally:
        receipts_state.social["player"]["attributes"].pop("job", None)


def test_an_episode_replays(receipts_active) -> None:
    from engine.game import procgen

    def run():
        state = procgen.new_game_state(player_name="Sam", seed=4242)
        from tests.social_fixtures import _scripted_episode
        return _scripted_episode(state)

    first = run()
    assert first == run()
    assert len([row for row in first if row[2] is not None]) >= 8     # eight replies decided


def test_away_mode_none_moves_nothing_on_resume(receipts_state) -> None:
    from engine.social import away

    receipts_state.social["last_active_wall"] = 1_000.0
    assert away.away_hours(receipts_state, 1_000.0 + 3 * 3600) == 0.0


def test_a_glance_worker_signs_off_after_one_exchange_with_a_promise_window(receipts_state, matched,
                                                                            monkeypatch) -> None:
    """A `glances` worker answers once, then signs off -- with a promise, its draw forced (T4): `lunch`."""
    from engine.social import convo

    thread = matched("matchstick")
    pid = thread.split(":")[1]
    # Forced by monkeypatch alone (not inside `_replies_forced`, whose exit would restore `available`
    # under the monkeypatch and leak the patch to later tests).
    monkeypatch.setattr(convo, "_ghost_factor", lambda state, pid_: 0.0)
    monkeypatch.setattr(convo, "_reply_factor", lambda state, pid_: 100.0)
    monkeypatch.setattr(convo, "available", lambda state, pid_, at: convo.Availability(True, "glance"))
    monkeypatch.setattr(convo, "boundary_minutes", lambda state, pid_, at: None)
    monkeypatch.setattr(convo, "_promise_drawn", lambda state, pid_: True)
    _open_episode(receipts_state, pid, thread)
    _act(receipts_state, "send", target=thread, args={"kind": "text"}, text="are you at work?")
    first = next(m for m in _theirs(receipts_state, thread) if m["voiced"] is False)
    assert first["decision"]["end"] == "none" and first["decision"]["mode"] == "quick"
    first["voiced"] = True
    _act(receipts_state, "send", target=thread, args={"kind": "text"}, text="what are you working on?")
    second = next(m for m in _theirs(receipts_state, thread) if m["voiced"] is False)
    assert second["decision"]["end"] == "sign_off"
    row = receipts_state.social["promises"][second["decision"]["promise_id"]]
    assert row["window"] == "lunch" and row["by"] == "person" and row["status"] == "open"


def test_after_a_sign_off_they_answer_one_more_then_read_later(receipts_state, matched, monkeypatch) -> None:
    from engine.game.effects import apply_effect
    from engine.social import convo

    thread = matched("matchstick")
    pid = thread.split(":")[1]
    monkeypatch.setattr(convo, "boundary_minutes", lambda state, pid_, at: None)
    with _replies_forced():
        monkeypatch.setattr(convo, "next_available", lambda state, pid_, at: at + 2.0)   # away two hours
        _open_episode(receipts_state, pid, thread)
        apply_effect(receipts_state, {"type": "social_episode", "op": "end", "pid": pid,
                                      "at": receipts_state.world_clock_hours, "end": "signed_off", "reason": "x"})
        receipts_state.social["people"][pid]["episode"]["after_left"] = 1        # the draw, forced
        _act(receipts_state, "send", target=thread, args={"kind": "text"}, text="night!")
        due = [m for m in _theirs(receipts_state, thread) if m["voiced"] is False]
        assert len(due) == 1 and due[0]["decision"]["end"] == "sign_off"         # the one more thing
        assert receipts_state.social["people"][pid]["episode"]["after_left"] == 0
        due[0]["voiced"] = True
        _act(receipts_state, "send", target=thread, args={"kind": "text"}, text="also!")
    assert not [m for m in _theirs(receipts_state, thread) if m["voiced"] is False]
    read = next(e for e in receipts_state.social["queue"] if e["pid"] == pid and e["kind"] == "read")
    assert read["at"] > receipts_state.world_clock_hours + 1.0                    # they read it when back


def test_initiations_resolve_their_window(receipts_state, matched, monkeypatch) -> None:
    from engine.social import behaviour, convo, events, windows

    pid = matched("matchstick").split(":")[1]
    real = behaviour.archetype
    row = {"id": "lunch_hello", "kind": "text", "window": "lunch", "prob": [1, 1, 1, 1, 1],
           "instruction": "window_message"}
    monkeypatch.setattr(behaviour, "archetype",
                        lambda name: dataclasses.replace(real(name), initiations=(row,)))
    events.cancel(receipts_state, pid, {"initiate"})
    day = events.daily_at(receipts_state)
    convo._daily_initiations(receipts_state)
    queued = [e for e in receipts_state.social["queue"] if e["pid"] == pid and e["kind"] == "initiate"
              and e.get("initiation") == "lunch_hello"]
    span = windows.resolve(receipts_state, pid, "lunch", day)
    assert len(queued) == 1 and span is not None and span[0] <= queued[0]["at"] <= span[1]
    assert queued[0]["decision"]["situation"] == "window_message"
    # While a conversation is going, nobody is nudged.
    events.cancel(receipts_state, pid, {"initiate"})
    _open_episode(receipts_state, pid, matched_thread(receipts_state, pid))
    convo._daily_initiations(receipts_state)
    assert not [e for e in receipts_state.social["queue"] if e["pid"] == pid and e["kind"] == "initiate"]


def matched_thread(state, pid: str) -> str:
    from engine.social import messaging

    return str(messaging.thread_for(state, pid))


def test_an_initiation_that_lands_opens_a_conversation(receipts_state, matched, monkeypatch) -> None:
    from engine.game import clock
    from engine.social import behaviour, convo, events, messaging
    from engine.social.kinds import Decision

    thread = matched("matchstick")
    pid = thread.split(":")[1]
    real = behaviour.archetype
    row = {"id": "hello", "kind": "text", "window": "evening", "prob": [1, 1, 1, 1, 1],
           "instruction": "window_message"}
    monkeypatch.setattr(behaviour, "archetype", lambda name: dataclasses.replace(real(name), initiations=(row,)))
    events.cancel(receipts_state, pid, {"initiate"})
    at = receipts_state.world_clock_hours + 0.5
    messaging.queue_due(receipts_state, pid, thread, Decision(situation="window_message"), at, initiation="hello")
    clock.advance_time(receipts_state, 1.0)
    assert [m for m in _theirs(receipts_state, thread) if m["decision"]["situation"] == "window_message"]
    assert convo.episode(receipts_state, pid) is not None


def test_an_initiation_is_skipped_when_the_player_just_wrote(receipts_state, matched, monkeypatch) -> None:
    from engine.game import clock
    from engine.social import behaviour, convo, events, messaging
    from engine.social.kinds import Decision

    thread = matched("matchstick")
    pid = thread.split(":")[1]
    monkeypatch.setattr(convo, "_reply_factor", lambda state, pid_: 0.0)     # the send is left on read
    monkeypatch.setattr(convo, "_ghost_factor", lambda state, pid_: 0.0)
    monkeypatch.setattr(convo, "next_available", lambda state, pid_, at: at)
    real = behaviour.archetype
    row = {"id": "hello", "kind": "text", "window": "evening", "prob": [1, 1, 1, 1, 1],
           "instruction": "window_message"}
    monkeypatch.setattr(behaviour, "archetype", lambda name: dataclasses.replace(real(name), initiations=(row,)))
    _act(receipts_state, "send", target=thread, args={"kind": "text"}, text="hi")
    events.cancel(receipts_state, pid, {"initiate"})
    messaging.queue_due(receipts_state, pid, thread, Decision(situation="window_message"),
                        receipts_state.world_clock_hours + 0.5, initiation="hello")
    clock.advance_time(receipts_state, 1.0)                    # within skip_if_talked_minutes (120)
    assert not [m for m in _theirs(receipts_state, thread) if m["decision"]["situation"] == "window_message"]


def test_the_send_costs_come_from_conversation_yaml(receipts_state) -> None:
    from engine import social
    from engine.social import turn

    costs = social.data("conversation")["costs"]
    assert turn.cost_hours(receipts_state, "natter", "text") == pytest.approx(costs["text"] / 60) == pytest.approx(1 / 60)
    assert turn.cost_hours(receipts_state, "natter", "voice") == pytest.approx(2 / 60)
    assert turn.cost_hours(receipts_state, "matchstick", "text") == pytest.approx(1 / 60)   # every app the same
    assert costs["reply"] == 0
    assert turn.cost_hours(receipts_state, "matchstick", "swipe") == pytest.approx(0.2 / 60)  # apps.yaml's own


def test_wait_targets_are_next_1h_evening_morning(receipts_state) -> None:
    from engine.social import turn

    assert turn.WAIT_UNTIL == ("next", "1h", "evening", "morning")
    refused = _act(receipts_state, "wait", args={"until": "15m"})
    assert not refused["success"]
    _set_clock(receipts_state, hour=16)
    assert turn.wait(receipts_state, {"until": "evening"})["waited_hours"] == pytest.approx(2.0)
    _set_clock(receipts_state, hour=23)
    assert turn.wait(receipts_state, {"until": "morning"})["waited_hours"] == pytest.approx(8.0)
    assert turn.wait(receipts_state, {"until": "1h"})["waited_hours"] == pytest.approx(1.0)


def test_the_wait_verb_is_labelled_wait(receipts_state) -> None:
    from engine.social import intents

    assert intents.label_of(receipts_state, {"action": "wait", "target": "", "args": {"until": "1h"}}) == "Wait"


def test_an_unknown_mode_or_end_is_clamped_with_a_log_line(caplog) -> None:
    """The stored-decision rebuilds (voicer, voicing, agreement) read an unknown mode or end as the
    default, logged, instead of raising: a save from another version stays voiceable."""
    import logging

    from engine.social import agreement, voicer, voicing
    from engine.social.kinds import Decision

    row = {"situation": "reply", "mode": "rambling", "end": "storm_off", "surprise": 1}
    with caplog.at_level(logging.WARNING):
        assert voicer._decision_of({"id": "m1", "decision": row}) == Decision("reply")
        snap = dataclasses.make_dataclass("S", [("due", list)])([{"id": "m1", "decision": row}])
        assert voicing._decision(snap) == Decision("reply")
        assert agreement.decision_of({"decision": row}) == Decision("reply")
    assert sum("rambling" in r.getMessage() for r in caplog.records) == 3
    with pytest.raises(ValueError):
        Decision("reply", mode="rambling")                     # a NEW decision with a bad mode is still a bug


def test_the_shipped_conversation_validates_clean() -> None:
    from engine.games.validation import errors_only, validate_story

    assert [i for i in errors_only(validate_story("read-receipts"))
            if i.source in ("social/conversation.yaml", "social/behaviours.yaml", "social/apps.yaml")] == []


@pytest.mark.parametrize("key,value,where", [
    ("episode_gap_minutes", 0, "episode_gap_minutes"),
    ("talk.per_depth", [1, 1], "talk.per_depth"),
    ("talk.exchanges.wizard", [2, 4], "talk.exchanges.wizard"),
    ("reasons.work", "", "reasons.work"),
    ("habits.weights.default.at_work.sometimes", 2, "habits.weights.default.at_work"),
])
def test_a_broken_conversation_file_names_its_key(receipts_active, key, value, where) -> None:
    import copy

    from engine import social
    from engine.social import convo

    data = copy.deepcopy(social.data("conversation"))
    node = data
    parts = key.split(".")
    for part in parts[:-1]:
        node = node[part]
    node[parts[-1]] = value
    archetypes = social.data("behaviours")["archetypes"]
    with pytest.raises(ValueError, match=rf"conversation\.yaml: {where.replace('.', chr(92) + '.')}"):
        convo.check_data(data, archetypes=archetypes)


def test_an_initiation_row_needs_a_window_and_a_prob_per_depth(receipts_active) -> None:
    from engine import social
    from engine.social import behaviour

    rows = social.data("behaviours")["archetypes"]
    row = dict(rows["romantic"])
    row["initiations"] = [{"id": "x", "kind": "text", "at_hours": [8], "prob_per_day": 0.5}]
    with pytest.raises(ValueError, match="went in v0.23.0"):
        behaviour.build_archetype("romantic", row, social.data("behaviours").get("arcs") or {})
    row["initiations"] = [{"id": "x", "kind": "text", "window": "brunch", "prob": [0.1] * 5}]
    with pytest.raises(ValueError, match=r"window"):
        behaviour.build_archetype("romantic", row, social.data("behaviours").get("arcs") or {})
    row["initiations"] = [{"id": "x", "kind": "text", "window": "lunch", "prob": [0.1, 0.2]}]
    with pytest.raises(ValueError, match=r"prob"):
        behaviour.build_archetype("romantic", row, social.data("behaviours").get("arcs") or {})


def test_a_hand_built_voicing_session_is_dropped_at_teardown(receipts_state) -> None:
    """(Review M7) `_voice_all`'s session over a test's state does not outlive the test: `_quieted` clears it."""
    from tests import social_fixtures
    from tests.social_stub import StubVoice

    social_fixtures._voice_all(receipts_state, StubVoice("zero"))
    assert social_fixtures._VOICE_SESSIONS
    with social_fixtures._quieted():
        pass
    assert social_fixtures._VOICE_SESSIONS == {}

