"""
Messaging (v0.22.0 spec §9, T8; v0.23.0 T3): sends, reads, bursts, ghosts,
openers, initiations, double texts, read receipts, numbers, and the threads /
notifications / open_thread payload. The conversation itself -- instant
replies, episodes, the nudge, availability -- is tests/test_social_convo.py.

Every draw a test depends on is forced (pre-flight F16): an archetype field
replaced, the per-episode-start draws or the number draw pinned, interest set
through `social_person`. No test passes or fails by its seed.
"""

from __future__ import annotations

import dataclasses

import pytest

from tests.social_fixtures import (  # noqa: F401
    _act, _at, _force_stage, _set_clock, _set_person, matched, matched_numbers, receipts_active, receipts_state,
)


def _pace(monkeypatch, **fields) -> None:
    """Every archetype with ``fields`` replaced (a forced draw: F16)."""
    from engine.social import behaviour

    real = behaviour.archetype
    monkeypatch.setattr(behaviour, "archetype", lambda name: dataclasses.replace(real(name), **fields))


def _forced(monkeypatch, *, reply: float = 100.0, ghost: float = 0.0, read_after: float = 0.0) -> None:
    """The per-episode-start draws forced (v0.23.0 T3, F16): the reply and ghost factors pinned, and the
    person's read at the send's minute plus ``read_after`` hours (`convo.next_available`)."""
    from engine.social import convo

    monkeypatch.setattr(convo, "_reply_factor", lambda state, pid: reply)
    monkeypatch.setattr(convo, "_ghost_factor", lambda state, pid: ghost)
    monkeypatch.setattr(convo, "available", lambda state, pid, at: convo.Availability(not read_after))
    monkeypatch.setattr(convo, "next_available", lambda state, pid, at: at + read_after)


def _theirs(state, thread: str) -> list[dict]:
    pid = thread.split(":", 1)[1]
    return [m for m in state.social["threads"][thread]["messages"] if m["from"] == pid]


# -- the brief's tests ------------------------------------------------------------------------


def test_a_burst_gets_one_reply_decision(receipts_state, matched, monkeypatch) -> None:
    from engine.social import messaging

    thread = matched("matchstick")
    pid = thread.split(":")[1]
    _forced(monkeypatch, read_after=0.5)                   # not reading yet: no conversation going
    for text in ("hey", "how's your week", "also: dogs or cats"):
        messaging.send(receipts_state, thread, "text", text)
    reads = [e for e in receipts_state.social["queue"] if e["pid"] == pid and e["kind"] == "read"]
    assert len(reads) == 1


def test_equal_times_replay_in_seq_order(receipts_active) -> None:
    from engine.game import procgen
    from engine.social import events

    def run() -> list[tuple]:
        state = procgen.new_game_state(seed=11)
        at = state.world_clock_hours + 1
        for pid in ("p0003", "p0001", "p0002"):
            events.push(state, at, pid, "daily")
        return [(e["at"], e["seq"], e["pid"]) for e in state.social["queue"] if e["pid"] != ""]

    first = run()
    assert first == run()
    assert [pid for _, _, pid in first] == ["p0003", "p0001", "p0002"]     # pushed order, by seq


def test_a_ghost_cancels_their_queue(receipts_state, matched, monkeypatch) -> None:
    """Every factor of the ghost draw forced to 1 (F16): it cannot pass or fail by seed."""
    from engine.game import clock
    from engine.social import messaging

    from engine import social
    from engine.social import convo, events

    thread = matched("matchstick")
    pid = thread.split(":")[1]
    _pace(monkeypatch, ghost_per_episode=1.0)
    _set_person(receipts_state, pid, interest=0)           # (1 - interest/100) == 1
    real = social.data("conversation")
    monkeypatch.setattr(convo, "_data", lambda: {**real, "reply": {**real["reply"], "stage_factor": {"default": 1.0}}})
    monkeypatch.setattr(convo, "next_available", lambda state, pid_, at: at)        # ghost_p == 1.0, read now
    messaging.send(receipts_state, thread, "text", "hi")
    clock.advance_time(receipts_state, 72)
    assert receipts_state.social["people"][pid]["ghosted"] is True
    assert not [e for e in receipts_state.social["queue"] if e["pid"] == pid and e["kind"] in events.REPLY_FAMILY]
    # A ghost is hidden: the payload never says so.
    assert "ghosted" not in repr(receipts_state.to_client_dict()["phone"])


def test_receipts_on_writes_read_at_and_off_hides_both_ways(receipts_state, matched_numbers, monkeypatch) -> None:
    from engine.game import clock
    from engine.social import messaging, payload

    _forced(monkeypatch, read_after=0.5)                                     # the read within the 48 h (F16)
    thread = matched_numbers("natter")
    pid = thread.split(":")[1]
    messaging.send(receipts_state, thread, "text", "morning!")
    clock.advance_time(receipts_state, 48)
    mine = [m for m in receipts_state.social["threads"][thread]["messages"] if m["from"] == "player"]
    assert mine[-1]["read_at"] is not None
    _act(receipts_state, "set_receipts", target="natter", args={"to": "off"})
    theirs = messaging.new_message(receipts_state, thread, pid, "text", bubbles=["morning you"])
    assert _act(receipts_state, "open_thread", target=thread)["success"]     # an OPEN thread (F18: never all([]))
    shown = payload.phone_block(receipts_state)["open_thread"]
    assert shown is not None and shown["messages"]
    assert any(m["from"] == "player" for m in shown["messages"])
    # One way: the player no longer sees when they read the player's messages.
    assert all(m.get("read_at") is None for m in shown["messages"] if m["from"] == "player")
    # The other: they never see that the player read theirs.
    row = next(m for m in receipts_state.social["threads"][thread]["messages"] if m["id"] == theirs["id"])
    assert row["read_at"] is not None and row.get("seen_by_them_at") is None


def test_a_double_text_after_silence_capped_in_a_row(receipts_state, matched, monkeypatch) -> None:
    from engine.game import clock

    _pace(monkeypatch, reply_minutes=(5.0, 0.0))                       # the opener's delay, drawn at the match (F16)
    thread = matched("matchstick")
    _pace(monkeypatch, opener_prob=1.0,                                # the opener is forced (F16)
          double_text={"after_hours": 1.0, "prob": 1.0, "max_in_row": 2})
    clock.advance_time(receipts_state, 24)
    theirs = _theirs(receipts_state, thread)
    doubles = [m for m in theirs if (m["decision"] or {}).get("situation") == "double_text"]
    assert 1 <= len(doubles) <= 2
    assert len(doubles) == 2                                            # forced: exactly the cap
    assert theirs[0]["decision"]["situation"] == "opener"


def test_numbers_open_texts_and_natter(receipts_state, matched, monkeypatch) -> None:
    from engine.game import clock
    from engine.social import messaging, relationships

    thread = matched("matchstick")
    pid = thread.split(":")[1]
    monkeypatch.setattr(messaging, "_number_accepted", lambda state, pid: True)
    _forced(monkeypatch, read_after=0.5)                                    # no ghost, read inside the 24 h (F16)
    _force_stage(receipts_state, pid, "talking")
    _set_person(receipts_state, pid, **_at(relationships.gate_spec("numbers")))   # the numbers gate holds (T9)
    assert _act(receipts_state, "ask", target=thread, args={"what": "number"})["success"]
    clock.advance_time(receipts_state, 24)
    assert {f"texts:{pid}", f"natter:{pid}"} <= set(receipts_state.social["threads"])
    assert thread in receipts_state.social["threads"]          # the app thread stays readable
    assert receipts_state.social["people"][pid]["stage"] == "numbers"
    answer = [m for m in _theirs(receipts_state, thread) if m["decision"]["situation"] == "answer_request"]
    assert answer and answer[0]["decision"]["kind"] == "text"


def test_a_voice_note_by_texts_is_refused(receipts_state, matched_numbers) -> None:
    thread = matched_numbers("texts")
    receipt = _act(receipts_state, "send", target=thread, args={"kind": "voice"}, text="(voice)")
    assert receipt["refused"] and receipt["result"]["error"] == "Texts can't send voice notes"


# -- further --------------------------------------------------------------------------------------


def test_a_declined_number_is_a_decline_and_opens_nothing(receipts_state, matched, monkeypatch) -> None:
    from engine.game import clock
    from engine.social import messaging

    thread = matched("matchstick")
    pid = thread.split(":")[1]
    monkeypatch.setattr(messaging, "_number_accepted", lambda state, pid: False)
    _forced(monkeypatch, read_after=0.5)                   # still unread when the second ask comes (F16)
    _force_stage(receipts_state, pid, "talking")
    assert _act(receipts_state, "ask", target=thread, args={"what": "number"})["success"]
    again = _act(receipts_state, "ask", target=thread, args={"what": "number"})        # asked again: one burst (T9)
    assert again["success"] and again["result"]["again"] is True
    clock.advance_time(receipts_state, 24)
    assert f"natter:{pid}" not in receipts_state.social["threads"]
    assert receipts_state.social["people"][pid]["stage"] == "talking"
    answer = [m for m in _theirs(receipts_state, thread) if m["decision"]["situation"] == "answer_request"]
    assert len(answer) == 1 and answer[0]["decision"]["kind"] == "decline"                # one decision for both


def _asked_for_the_number(state, matched, monkeypatch, *, gate_holds: bool, accepted: bool) -> tuple[str, str]:
    """A number asked at `talking` and answered inside 24 h: (the thread, the person)."""
    from engine.game import clock
    from engine.social import messaging, relationships

    thread = matched("matchstick")
    pid = thread.split(":")[1]
    monkeypatch.setattr(messaging, "_number_accepted", lambda state_, pid_: accepted)
    _forced(monkeypatch, read_after=0.5)                                     # no ghost (F16)
    _force_stage(state, pid, "talking")
    if gate_holds:
        _set_person(state, pid, **_at(relationships.gate_spec("numbers")))
    assert _act(state, "ask", target=thread, args={"what": "number"})["success"]
    clock.advance_time(state, 24)
    return thread, pid


@pytest.mark.parametrize("gate_holds, why, line", [
    (False, "not_yet", "Your answer: not yet, it's too early."),
    (True, "draw", "Your answer: no."),
])
def test_a_declined_numbers_why_is_carried_to_the_voice_and_the_phone(receipts_state, matched, monkeypatch,
                                                                        gate_holds: bool, why: str, line: str) -> None:
    """Owner bug (final review wave 2): `not_yet` (the gate, v0.23.0 T5's spelling) is said as such; a draw's no stays a plain no."""
    from engine.social import messaging, voicing

    thread, pid = _asked_for_the_number(receipts_state, matched, monkeypatch, gate_holds=gate_holds, accepted=False)
    (request,) = [r for r in receipts_state.social["requests"].values() if r["what"] == "number"]
    assert request["status"] == "no" and request["why"] == why
    snap = voicing.snapshot_of(receipts_state, thread)
    assert line in voicing.messages(snap)[-1]["content"]
    t = receipts_state.social["threads"][thread]
    (decline,) = [m for m in t["messages"] if (m.get("decision") or {}).get("kind") == "decline"]
    assert "declined" not in messaging.message_view(receipts_state, t, decline)      # due: nothing told yet
    view = messaging.message_view(receipts_state, t, {**decline, "voiced": True, "bubbles": ["not yet x"]})
    assert view.get("declined") == ("not_yet" if why == "not_yet" else "no")


def test_a_v022_not_yet_spelling_is_still_said_and_shown(receipts_state, matched, monkeypatch) -> None:
    """Review minor: a v0.22.0 save's request carries `why: "not yet"`; the voice and the phone still read
    it as the gate's no (`relationships.NOT_YET_WHYS`)."""
    from engine.social import messaging, voicing

    thread, pid = _asked_for_the_number(receipts_state, matched, monkeypatch, gate_holds=False, accepted=False)
    (request,) = [r for r in receipts_state.social["requests"].values() if r["what"] == "number"]
    request["why"] = "not yet"                                    # as v0.22.0 wrote it
    snap = voicing.snapshot_of(receipts_state, thread)
    assert "Your answer: not yet, it's too early." in voicing.messages(snap)[-1]["content"]
    t = receipts_state.social["threads"][thread]
    (decline,) = [m for m in t["messages"] if (m.get("decision") or {}).get("kind") == "decline"]
    view = messaging.message_view(receipts_state, t, {**decline, "voiced": True, "bubbles": ["x"]})
    assert view.get("declined") == "not_yet"


def test_a_thread_row_lists_their_number_only_once_the_gate_holds(receipts_state, matched) -> None:
    """Owner bug (final review wave 2): the Ask menu's "Their number" is the engine's call, read off the row."""
    from engine.social import messaging, relationships

    thread = matched("matchstick")
    pid = thread.split(":")[1]
    _force_stage(receipts_state, pid, "talking")
    assert "number" not in messaging.thread_row(receipts_state, thread)["asks"]
    _set_person(receipts_state, pid, **_at(relationships.gate_spec("numbers")))
    assert "number" in messaging.thread_row(receipts_state, thread)["asks"]


def test_the_number_draw_reads_trust_and_the_archetype(receipts_state, matched, monkeypatch) -> None:
    from engine.social import messaging

    pid = matched("matchstick").split(":")[1]
    _pace(monkeypatch, media={"offer_mult": 1.0, "accept_mult": 1.0})
    _set_person(receipts_state, pid, trust=100)
    assert messaging._number_accepted(receipts_state, pid) is True           # p == 1
    _set_person(receipts_state, pid, trust=0)
    assert messaging._number_accepted(receipts_state, pid) is False          # p == 0


def test_a_reply_is_left_on_read_when_the_draw_says_so(receipts_state, matched, monkeypatch) -> None:
    from engine.game import clock
    from engine.social import messaging

    thread = matched("matchstick")
    pid = thread.split(":")[1]
    _pace(monkeypatch, double_text={"after_hours": 1, "prob": 0, "max_in_row": 0})
    _forced(monkeypatch, reply=0.0, read_after=0.5)
    messaging.send(receipts_state, thread, "text", "hello?")
    assert [e for e in receipts_state.social["queue"] if e["pid"] == pid and e["kind"] == "read"]
    clock.advance_time(receipts_state, 48)
    assert not [e for e in receipts_state.social["queue"] if e["pid"] == pid and e["kind"] == "read"]   # it was read
    assert not [m for m in _theirs(receipts_state, thread) if m["decision"]["situation"] == "reply"]


def test_a_sure_reply_lands_due_shaped_by_the_conversation(receipts_state, matched, monkeypatch) -> None:
    """v0.23.0 §4.5: a reply's bubbles come from its MODE (a first exchange is `quick`, 1-2), never the burst;
    a burst only raises the minimum. Replaces v0.22's bubble cap by burst (`1 + burst`)."""
    from engine.game import clock
    from engine.social import messaging

    thread = matched("matchstick")
    _forced(monkeypatch, read_after=0.5)
    messaging.send(receipts_state, thread, "text", "one")
    messaging.send(receipts_state, thread, "text", "two")
    clock.advance_time(receipts_state, 48)
    reply = next(m for m in _theirs(receipts_state, thread) if m["decision"]["situation"] == "reply")
    assert reply["voiced"] is False and reply["decision"]["mode"] == "quick"
    assert reply["decision"]["max_bubbles"] == 2 and reply["decision"]["min_bubbles"] == 1
    assert messaging.unvoiced(receipts_state)[0]["id"] in {m["id"] for m in _theirs(receipts_state, thread)}


def test_a_burst_across_threads_reads_each_thread(receipts_state, matched_numbers, monkeypatch) -> None:
    """Review minor 2: a send in Natter while Texts' read is pending gets a read of its own."""
    from engine.game import clock
    from engine.social import messaging

    _forced(monkeypatch, read_after=0.5)
    natter = matched_numbers("natter")
    pid = natter.split(":")[1]
    messaging.send(receipts_state, f"texts:{pid}", "text", "on texts")
    messaging.send(receipts_state, natter, "text", "and on natter")
    reads = {e["thread_id"] for e in receipts_state.social["queue"] if e["pid"] == pid and e["kind"] == "read"}
    assert reads == {f"texts:{pid}", natter}
    clock.advance_time(receipts_state, 24)
    mine = [m for m in receipts_state.social["threads"][natter]["messages"] if m["from"] == "player"]
    assert mine[-1]["read_at"] is not None                     # Natter keeps receipts: read, not "delivered" forever


def test_the_double_text_cap_holds_when_another_message_lands_first(receipts_state, matched, monkeypatch) -> None:
    """Review important 1: an initiation landing while a double text is pending starts no second chain."""
    from engine.game import clock
    from engine.social import messaging
    from engine.social.kinds import Decision

    row = {"id": "hello", "kind": "text", "window": "evening", "prob": [1, 1, 1, 1, 1],
           "instruction": "window_message"}
    _pace(monkeypatch, reply_minutes=(5.0, 0.0), opener_prob=1.0, initiations=(row,),
          double_text={"after_hours": 3.0, "prob": 1.0, "max_in_row": 1})
    monkeypatch.setattr(messaging.behaviour, "status_at", lambda person, hour: "free")
    thread = matched("matchstick")
    pid = thread.split(":")[1]
    opener = next(e for e in receipts_state.social["queue"] if e["pid"] == pid and e["kind"] == "initiate")
    clock.advance_time(receipts_state, opener["at"] - receipts_state.world_clock_hours)     # the opener lands
    pending = [e for e in receipts_state.social["queue"] if e["pid"] == pid and e["kind"] == "double_text"]
    assert len(pending) == 1
    # Their initiation lands before the double text is due.
    from engine.game.effects import apply_effect

    apply_effect(receipts_state, {"type": "social_event", "event": {
        "at": receipts_state.world_clock_hours + 1, "seq": 0, "pid": pid, "kind": "initiate", "thread_id": thread,
        "initiation": "hello", "decision": {**Decision(situation="window_message").__dict__}}})
    clock.advance_time(receipts_state, 24)
    doubles = [m for m in _theirs(receipts_state, thread) if m["decision"]["situation"] == "double_text"]
    assert len(doubles) == 1                                   # max_in_row: 1, however many messages landed


def test_one_opener_per_person_across_apps(receipts_state, matched, monkeypatch) -> None:
    """Review minor 6: a second dating-app match of the same person queues no second opener."""
    from engine.game.effects import apply_effect

    thread = matched("matchstick")
    pid = thread.split(":")[1]
    assert len([e for e in receipts_state.social["queue"] if e["pid"] == pid and e["kind"] == "initiate"]) == 1
    assert apply_effect(receipts_state, {"type": "social_match", "app": "front_porch", "pid": pid})["ok"]
    assert len([e for e in receipts_state.social["queue"] if e["pid"] == pid and e["kind"] == "initiate"]) == 1


def test_writing_first_cancels_their_opener(receipts_state, matched, monkeypatch) -> None:
    from engine.game import clock
    from engine.social import messaging

    thread = matched("matchstick")
    pid = thread.split(":")[1]
    _pace(monkeypatch, opener_prob=1.0)
    _forced(monkeypatch, reply=0.0)
    assert [e for e in receipts_state.social["queue"] if e["pid"] == pid and e["kind"] == "initiate"]
    messaging.send(receipts_state, thread, "text", "me first")
    assert not [e for e in receipts_state.social["queue"] if e["pid"] == pid and e["kind"] == "initiate"]
    clock.advance_time(receipts_state, 24)
    assert not [m for m in _theirs(receipts_state, thread) if m["decision"]["situation"] == "opener"]


def test_an_opener_not_drawn_writes_nothing(receipts_state, matched, monkeypatch) -> None:
    from engine.game import clock

    thread = matched("matchstick")
    _pace(monkeypatch, opener_prob=0.0)
    clock.advance_time(receipts_state, 24)
    assert _theirs(receipts_state, thread) == []


def test_a_player_reply_stops_their_double_texts(receipts_state, matched, monkeypatch) -> None:
    from engine.game import clock
    from engine.social import messaging

    thread = matched("matchstick")
    pid = thread.split(":")[1]
    _pace(monkeypatch, opener_prob=1.0, double_text={"after_hours": 5.0, "prob": 1.0, "max_in_row": 3})
    _forced(monkeypatch, reply=0.0)
    due = next(e for e in receipts_state.social["queue"] if e["pid"] == pid and e["kind"] == "initiate")
    clock.advance_time(receipts_state, due["at"] - receipts_state.world_clock_hours)
    waiting = {e["seq"] for e in receipts_state.social["queue"] if e["pid"] == pid and e["kind"] == "double_text"}
    assert waiting
    messaging.send(receipts_state, thread, "text", "sorry, was out")
    # The chain waiting on the player's silence is gone (their answer, landed since, may start its own).
    assert not [e for e in receipts_state.social["queue"] if e["pid"] == pid and e["seq"] in waiting]


def test_an_initiation_is_queued_while_its_when_holds(receipts_state, matched_numbers, monkeypatch) -> None:
    """An initiation row by window (v0.23.0 §4.7), its chance forced to 1 at every depth: it lands while its
    `when` holds, and never below its stage_min."""
    from engine.game import clock
    from engine.social import convo, messaging

    row = {"id": "good_morning", "kind": "text", "window": "waking", "prob": [1, 1, 1, 1, 1],
           "when": {"stage_min": "numbers"}, "instruction": "window_message"}
    _pace(monkeypatch, initiations=(row,), opener_prob=0.0, double_text={"after_hours": 1, "prob": 0, "max_in_row": 0})
    monkeypatch.setattr(messaging.behaviour, "status_at", lambda person, hour: "free" if hour % 24 >= 7 else "asleep")
    monkeypatch.setattr(convo, "_reply_factor", lambda state, pid: 0.0)
    thread = matched_numbers("natter")
    pid = thread.split(":")[1]
    clock.advance_time(receipts_state, 72)
    situations = [m["decision"]["situation"] for t in receipts_state.social["threads"].values()
                  if t["pid"] == pid for m in t["messages"] if m["from"] == pid]
    assert "window_message" in situations
    # Below its stage_min, it never comes.
    _force_stage(receipts_state, pid, "talking")
    before = situations.count("window_message")
    clock.advance_time(receipts_state, 48)
    after = [m for t in receipts_state.social["threads"].values() if t["pid"] == pid
             for m in t["messages"] if m["from"] == pid and m["decision"]["situation"] == "window_message"]
    assert len(after) == before


def test_when_reads_each_condition(receipts_state, matched) -> None:
    from engine.social import messaging

    pid = matched("matchstick").split(":")[1]
    now = receipts_state.world_clock_hours
    _force_stage(receipts_state, pid, "talking")
    _set_person(receipts_state, pid, last_player_at=now, last_them_at=now)
    assert messaging.when_holds(receipts_state, pid, {"stage_min": "talking"}, now)
    assert not messaging.when_holds(receipts_state, pid, {"stage_min": "numbers"}, now)
    assert not messaging.when_holds(receipts_state, pid, {"hours_since_player": 6}, now + 5)
    assert messaging.when_holds(receipts_state, pid, {"hours_since_player": 6}, now + 6.01)
    assert messaging.when_holds(receipts_state, pid, {"days_since_last": 2}, now + 48.01)
    assert not messaging.when_holds(receipts_state, pid, {"ghosted": True}, now)       # not ghosted
    assert not messaging.when_holds(receipts_state, pid, {"nonsense": 1}, now)
    saturday = (5 * 24) + 12.0                                                          # day 6 is a Saturday
    assert messaging.when_holds(receipts_state, pid, {"weekend": True}, saturday)
    assert not messaging.when_holds(receipts_state, pid, {"weekend": True}, saturday - 48)
    _set_person(receipts_state, pid, ghosted=True)
    assert not messaging.when_holds(receipts_state, pid, {"stage_min": "talking"}, now)  # a ghost does not start things
    assert messaging.when_holds(receipts_state, pid, {"ghosted": True}, now)


def test_a_send_after_an_unmatch_is_refused_in_words(receipts_state, matched) -> None:
    thread = matched("matchstick")
    pid = thread.split(":")[1]
    assert _act(receipts_state, "unmatch", target=pid)["success"]
    receipt = _act(receipts_state, "send", target=thread, args={"kind": "text"}, text="wait")
    assert receipt["refused"] and receipt["result"]["error"].startswith("You unmatched")


def test_a_send_spends_its_minutes_and_needs_words(receipts_state, matched) -> None:
    from engine import social

    thread = matched("matchstick")
    before = receipts_state.world_clock_hours
    assert _act(receipts_state, "send", target=thread, args={"kind": "text"}, text="hey you")["success"]
    assert receipts_state.world_clock_hours - before == pytest.approx(social.data("conversation")["costs"]["text"] / 60)
    assert _act(receipts_state, "send", target=thread, args={"kind": "text"}, text="")["refused"]
    photo = _act(receipts_state, "send", target=thread, args={"kind": "photo"}, text="look")
    assert photo["refused"] and photo["result"]["error"] == "Matchstick can't send photos"


def test_opening_a_thread_marks_it_read_and_focuses_it(receipts_state, matched_numbers) -> None:
    from engine.social import messaging

    thread = matched_numbers("natter")
    pid = thread.split(":")[1]
    messaging.new_message(receipts_state, thread, pid, "text", bubbles=["hi!"])
    assert messaging.badges(receipts_state)["natter"] == 1
    assert receipts_state.to_client_dict()["phone"]["apps"][[a["id"] for a in
           receipts_state.to_client_dict()["phone"]["apps"]].index("natter")]["badge"] == 1
    assert _act(receipts_state, "open_thread", target=thread)["success"]
    t = receipts_state.social["threads"][thread]
    assert t["unread"] == 0 and t["focus"] >= 1 and receipts_state.social["open_thread"] == thread
    assert messaging.badges(receipts_state).get("natter", 0) == 0
    # Receipts on, on Natter: they saw it, and the player has left them on read.
    assert t["messages"][-1]["seen_by_them_at"] is not None
    assert receipts_state.social["people"][pid]["left_on_read_since"] is not None
    messaging.send(receipts_state, thread, "text", "hey")
    assert receipts_state.social["people"][pid]["left_on_read_since"] is None


def test_a_due_message_is_not_read_by_opening(receipts_state, matched) -> None:
    from engine.social import messaging

    thread = matched("matchstick")
    pid = thread.split(":")[1]
    messaging.new_message(receipts_state, thread, pid, "text", voiced=False, decision={"situation": "reply"})
    _act(receipts_state, "open_thread", target=thread)
    assert receipts_state.social["threads"][thread]["unread"] == 1
    shown = receipts_state.to_client_dict()["phone"]["open_thread"]
    assert shown["messages"][-1]["pending"] is True and shown["messages"][-1]["bubbles"] == []
    assert "decision" not in shown["messages"][-1]


def test_notifications_are_bounded_and_say_new_message(receipts_state, matched, monkeypatch) -> None:
    from engine import social
    from engine.social import messaging

    thread = matched("matchstick")
    pid = thread.split(":")[1]
    monkeypatch.setattr(social, "setting", lambda key, default: 3 if key == "notifications_max" else default)
    for _ in range(5):
        messaging.new_message(receipts_state, thread, pid, "text", voiced=False, decision={"situation": "reply"})
    rows = receipts_state.social["notifications"]
    assert len(rows) == 3 and all(row["preview"] == "New message" for row in rows)
    shown = receipts_state.to_client_dict()["phone"]["notifications"]
    assert [row["id"] for row in shown] == [row["id"] for row in rows] and shown[0]["name"]


def test_thread_for_is_the_last_written_to(receipts_state, matched_numbers) -> None:
    from engine.social import messaging

    natter = matched_numbers("natter")
    pid = natter.split(":")[1]
    messaging.send(receipts_state, f"texts:{pid}", "text", "on texts now")
    assert messaging.thread_for(receipts_state, pid) == f"texts:{pid}"
    messaging.send(receipts_state, natter, "text", "or here")
    assert messaging.thread_for(receipts_state, pid) == natter


def test_the_threads_section_hides_closed_threads_and_hidden_values(receipts_state, matched, monkeypatch) -> None:
    from engine.social import messaging

    thread = matched("matchstick")
    pid = thread.split(":")[1]
    _forced(monkeypatch, read_after=0.5)                   # not read yet: "delivered"
    messaging.send(receipts_state, thread, "text", "hello")
    rows = receipts_state.to_client_dict()["phone"]["threads"]
    row = next(r for r in rows if r["thread_id"] == thread)
    assert row["last"]["preview"] == "hello" and row["read_state"] == "delivered"
    text = repr(rows)
    for hidden in ("warmth", "interest", "trust", "mood", "ghosted", "arc", "rev", "decision"):
        assert f"'{hidden}'" not in text
    assert _act(receipts_state, "block", target=pid)["success"]
    assert all(r["thread_id"] != thread for r in receipts_state.to_client_dict()["phone"]["threads"])


def test_the_new_sections_are_time_varying() -> None:
    from engine.social import payload

    assert {"threads", "notifications", "open_thread"} <= payload.TIME_VARYING_SECTIONS


def test_decision_is_one_class_in_kinds() -> None:
    from engine.social import kinds, messaging

    assert messaging.Decision is kinds.Decision
    assert dataclasses.asdict(kinds.Decision(situation="reply"))["max_bubbles"] == 3


def test_the_shipped_behaviours_validate_clean() -> None:
    from engine.games.validation import errors_only, validate_story

    errors = [i for i in errors_only(validate_story("read-receipts")) if "behaviours" in i.source or "apps" in i.source]
    assert errors == []


_BROKEN = {
    "pacing_back": ("social/behaviours.yaml", "pacing"),
    "window_unknown": ("social/behaviours.yaml", "archetypes.romantic.initiations[0](good_morning).window"),
    "when_unknown_key": ("social/behaviours.yaml", "archetypes.romantic.initiations[0](good_morning).when"),
    "when_bad_stage": ("social/behaviours.yaml", "archetypes.romantic.initiations[0](good_morning).when"),
    "first_message": ("social/apps.yaml", "apps.matchstick.first_message"),
    "unlock": ("social/apps.yaml", "apps.natter.unlock"),
}


@pytest.mark.parametrize("how", sorted(_BROKEN))
def test_a_broken_initiation_or_app_is_an_error_naming_its_key(tmp_path, how) -> None:
    import shutil

    import yaml

    from engine import social, yamlio
    from engine.games import registry
    from engine.games.validation import StoryValidator

    social_dir = social._ROOT / "games" / "read-receipts" / "data" / "social"
    for path in social_dir.glob("*.yaml"):
        shutil.copy(path, tmp_path / path.name)
    behaviours = yamlio.safe_load((social_dir / "behaviours.yaml").read_text(encoding="utf-8"))
    apps_ = yamlio.safe_load((social_dir / "apps.yaml").read_text(encoding="utf-8"))
    romantic = behaviours["archetypes"]["romantic"]["initiations"][0]
    if how == "pacing_back":                  # v0.22's block: its terms are conversation.yaml's `reply:` now
        behaviours["pacing"] = {"interest_factor": [0.3, 1.5]}
    elif how == "window_unknown":
        romantic["window"] = "brunch"
    elif how == "when_unknown_key":
        romantic["when"]["moon"] = "full"
    elif how == "when_bad_stage":
        romantic["when"]["stage_min"] = "eloped"  # no stage (v0.23 made "engaged" one)
    elif how == "first_message":
        apps_["apps"]["matchstick"]["first_message"] = "whoever"
    else:
        apps_["apps"]["natter"]["unlock"] = "soon"
    (tmp_path / "behaviours.yaml").write_text(yaml.safe_dump(behaviours, allow_unicode=True), encoding="utf-8")
    (tmp_path / "apps.yaml").write_text(yaml.safe_dump(apps_, allow_unicode=True), encoding="utf-8")
    validator = StoryValidator(registry.get("read-receipts"))
    validator._check_apps(tmp_path)
    validator._check_behaviours(tmp_path)
    named = {(i.source, i.ref_id) for i in validator.issues if i.severity == "error"}
    assert _BROKEN[how] in named, validator.issues


def test_a_ghost_drops_the_reads_waiting_in_other_threads(receipts_state, matched_numbers, monkeypatch) -> None:
    """Re-review 1, v0.23.0: a ghost cancels their reply family, so the read waiting in their other thread
    goes with it; after a reconnect a send in that thread is read again (the queue is the burst rule's record)."""
    from engine.game import clock
    from engine.social import convo, messaging

    _forced(monkeypatch, ghost=1.0, read_after=0.5)
    natter = matched_numbers("natter")
    pid = natter.split(":")[1]
    messaging.send(receipts_state, f"texts:{pid}", "text", "on texts")
    messaging.send(receipts_state, natter, "text", "and natter")
    reads = [e for e in receipts_state.social["queue"] if e["pid"] == pid and e["kind"] == "read"]
    assert len(reads) == 2
    clock.advance_time(receipts_state, reads[0]["at"] - receipts_state.world_clock_hours)   # the first read ghosts
    assert receipts_state.social["people"][pid]["ghosted"] is True
    assert not [e for e in receipts_state.social["queue"] if e["pid"] == pid and e["kind"] == "read"]
    # They come back (a reconnect), and the player writes in Natter again: it is read.
    _set_person(receipts_state, pid, ghosted=False)
    monkeypatch.setattr(convo, "_ghost_factor", lambda state, pid_: 0.0)
    messaging.send(receipts_state, natter, "text", "hey, welcome back")
    assert [e for e in receipts_state.social["queue"] if e["pid"] == pid and e["kind"] == "read"
            and e["thread_id"] == natter]


def test_load_all_refuses_a_malformed_conversation_file(tmp_path, monkeypatch) -> None:
    """Re-review 2, v0.23.0: conversation.yaml is checked once, when the story's data loads (the load rule)."""
    import shutil

    import yaml

    from engine import social, yamlio

    source = social._ROOT / "games" / "read-receipts" / "data" / "social"
    for path in source.glob("*.*"):                                    # words.txt too: games.yaml needs it
        shutil.copy(path, tmp_path / path.name)
    data = yamlio.safe_load((source / "conversation.yaml").read_text(encoding="utf-8"))
    data["talk"]["per_depth"] = "lots"
    (tmp_path / "conversation.yaml").write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    monkeypatch.setattr(social, "_DATA_CACHE", None)
    monkeypatch.setattr(social, "social_dir", lambda: tmp_path)
    with pytest.raises(ValueError, match=r"conversation\.yaml: talk\.per_depth"):
        social.load_all()
    assert social._DATA_CACHE is None                                   # nothing half-loaded is cached


def test_an_app_without_typing_never_shows_typing_dots(receipts_state, matched_numbers) -> None:
    """apps.yaml `typing: false` (Texts, as SMS) hides the dots even while a voicing call is in
    flight on the thread; `typing: true` (Natter) and an app that says nothing show them (T31)."""
    import types

    from engine.social import messaging

    texts = matched_numbers("texts")
    pid = texts.split(":", 1)[1]
    natter = f"natter:{pid}"
    session = types.SimpleNamespace(typing={texts, natter, f"matchstick:{pid}"})
    assert messaging.thread_row(receipts_state, texts, session)["typing"] is False
    assert messaging.thread_row(receipts_state, natter, session)["typing"] is True
    assert messaging.thread_row(receipts_state, f"matchstick:{pid}", session)["typing"] is True
    rows = {row["thread_id"]: row for row in messaging._threads_section(receipts_state, session)}
    assert rows[texts]["typing"] is False and rows[natter]["typing"] is True
    receipts_state.social["open_thread"] = texts
    assert messaging._open_thread_section(receipts_state, session)["typing"] is False
