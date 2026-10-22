"""
Promises and sign-offs (v0.23.0 spec §5, §3.6's `promise:` target, §19.2-§19.3; T4).

A promise is engine state (rule 1): a chip, the person's own sign-off, a
bounded proposal or (with no model) a phrase in the player's own message.
The person's are kept inside their window; the player's are kept by a message
in the window or broken by silence. `wait {until: promise:<id>}` jumps to one.

Every draw a test depends on is forced (lesson 1): `convo._promise_drawn`,
`_ghost_factor`, `_reply_factor`, `available`, `boundary_minutes`, or the
schedule itself (`behaviour._week`). No test passes or fails by its seed.
"""

from __future__ import annotations

import json

import pytest

from tests.social_fixtures import (  # noqa: F401
    _act, _open_episode, _replies_forced, _set_clock, _voice_all, matched, matched_numbers, receipts_active, receipts_state,
)
from tests.social_stub import StubVoice


#: Everyone's week in this file unless a test sets its own (lesson 1: a window's hours never rest on
#: which job shape the seed gave the person): up at 7, work 9-17, bed at 23, every day.
PLAIN_WEEK = [[0, 7, "asleep"], [7, 9, "free"], [9, 17, "work"], [17, 23, "free"], [23, 24, "asleep"]]


@pytest.fixture(autouse=True)
def _a_plain_week(monkeypatch):
    from engine.social import behaviour

    monkeypatch.setattr(behaviour, "_week", lambda shape: {d: PLAIN_WEEK for d in behaviour.WEEKDAYS})


def _abs(state, day_offset: int, hour: float) -> float:
    return (int(state.world_clock_hours // 24) + day_offset) * 24 + hour


def _theirs(state, thread):
    return [m for m in state.social["threads"][thread]["messages"] if m["from"] not in ("player", "system")]


def _due(state, thread):
    return [m for m in _theirs(state, thread) if m["voiced"] is False]


def _always_available(monkeypatch) -> None:
    """The person always fully available and no boundary in reach: a decision's end rests on the terms a
    test sets (energy, length), never on their schedule (lesson 1)."""
    from engine.social import convo

    monkeypatch.setattr(convo, "available", lambda state, pid_, at: convo.Availability(True))
    monkeypatch.setattr(convo, "boundary_minutes", lambda state, pid_, at: None)
    monkeypatch.setattr(convo, "_ghost_factor", lambda state, pid_: 0.0)
    monkeypatch.setattr(convo, "_reply_factor", lambda state, pid_: 100.0)


# -- windows (§5.1) -------------------------------------------------------------------------------------


def test_windows_resolve_across_midnight(receipts_state, matched, monkeypatch) -> None:
    """(Review Focus 1) "morning" said at 00:30 is THIS morning; "tonight" at 23:40 is the rest of tonight."""
    from engine.social import behaviour, windows

    monkeypatch.setattr(behaviour, "_week", lambda shape: {d: [[0, 7, "asleep"], [7, 9, "free"], [9, 17, "work"],
                                                               [17, 23, "free"], [23, 24, "asleep"]]
                                                           for d in behaviour.WEEKDAYS})
    pid = matched("matchstick").split(":")[1]
    day = int(receipts_state.world_clock_hours // 24) + 1
    for said, window, start in ((day * 24 + 0.5, "morning", day * 24 + 7),
                                (day * 24 + 6.99, "morning", day * 24 + 7),
                                (day * 24 + 7.01, "morning", day * 24 + 7.01),
                                (day * 24 + 23 + 40 / 60, "tonight", day * 24 + 23 + 40 / 60)):
        span = windows.resolve(receipts_state, pid, window, said)
        assert span is not None and span[0] == pytest.approx(start), (said, window, span)
    late = windows.resolve(receipts_state, pid, "morning", day * 24 + 13.0)
    assert late[0] == pytest.approx((day + 1) * 24 + 7)


def test_a_night_tail_is_not_a_morning(receipts_state, matched, monkeypatch) -> None:
    """A night worker's 00:00-02:00 shift is the night before's tail, not their waking band: "morning"
    never lands at 07:00 while they sleep -- they have no morning, so it is their next free band."""
    from engine.social import behaviour, promises, windows

    monkeypatch.setattr(behaviour, "_week", lambda shape: {d: [[0, 2, "work"], [12, 16, "free"], [16, 24, "work"]]
                                                           for d in behaviour.WEEKDAYS})
    pid = matched("matchstick").split(":")[1]
    _set_clock(receipts_state, hour=3)
    assert windows.resolve(receipts_state, pid, "morning", receipts_state.world_clock_hours) is None
    row = promises.make(receipts_state, pid, by="person", window="morning")
    assert row["fallback"] and row["opens_at"] == pytest.approx(_abs(receipts_state, 0, 12.0))
    assert promises.window_words(row) == "in the morning, so this afternoon"


def test_a_nurse_on_nights_after_work_resolves_truthfully(receipts_state, matched, monkeypatch) -> None:
    from engine.social import behaviour, promises

    monkeypatch.setattr(behaviour, "_week", lambda shape: {d: [[0, 8, "work"], [8, 16, "asleep"], [16, 24, "free"]]
                                                           for d in behaviour.WEEKDAYS})
    pid = matched("matchstick").split(":")[1]
    _set_clock(receipts_state, hour=20)
    row = promises.make(receipts_state, pid, by="person", window="after_work")
    assert row is not None and row["opens_at"] % 24 == pytest.approx(8.0)


def test_a_window_they_do_not_have_is_their_next_free_band_worded_truthfully(receipts_state, matched,
                                                                              monkeypatch) -> None:
    """§5.1: no work band means no `at_work` for them -- their next free band, and the words say when."""
    from engine.social import behaviour, promises

    monkeypatch.setattr(behaviour, "_week", lambda shape: {d: [[0, 8, "asleep"], [8, 24, "free"]]
                                                           for d in behaviour.WEEKDAYS})
    pid = matched("matchstick").split(":")[1]
    _set_clock(receipts_state, hour=2)
    row = promises.make(receipts_state, pid, by="player", window="at_work")   # the PERSON's work band (m4)
    assert row is not None and row["fallback"] is True
    assert row["opens_at"] == pytest.approx(_abs(receipts_state, 0, 8.0))
    assert promises.window_words(row) == "at work, so this morning"


def test_later_is_their_next_free_band_at_least_two_hours_ahead(receipts_state, matched, monkeypatch) -> None:
    from engine.social import behaviour, windows

    monkeypatch.setattr(behaviour, "_week", lambda shape: {d: [[0, 7, "asleep"], [7, 9, "free"], [9, 17, "work"],
                                                               [17, 23, "free"], [23, 24, "asleep"]]
                                                           for d in behaviour.WEEKDAYS})
    pid = matched("matchstick").split(":")[1]
    _set_clock(receipts_state, hour=8)
    span = windows.resolve(receipts_state, pid, "later", receipts_state.world_clock_hours)
    assert span[0] == pytest.approx(_abs(receipts_state, 0, 17.0))           # 10:00 is at work: their evening


# -- making them (§5.2) ---------------------------------------------------------------------------------


def test_a_chip_records_a_promise_and_their_message_lands_in_it(receipts_state, matched) -> None:
    from engine.game import clock

    thread = matched("matchstick")
    pid = thread.split(":")[1]
    with _replies_forced():
        _open_episode(receipts_state, pid, thread)
        receipt = _act(receipts_state, "sign_off", target=thread, args={"who": "you", "window": "morning"},
                       text="message me in the morning?")
    assert receipt["success"]
    row = next(iter(receipts_state.social["promises"].values()))
    assert row["by"] == "person" and row["status"] == "open" and row["id"].startswith("pr")
    clock.advance_time(receipts_state, row["closes_at"] - receipts_state.world_clock_hours + 0.1)
    theirs = [m for m in receipts_state.social["threads"][thread]["messages"]
              if (m.get("decision") or {}).get("situation") == "promised_message"]
    assert theirs and row["opens_at"] <= theirs[0]["at"] <= row["closes_at"]
    assert theirs[0]["decision"]["promise_id"] == row["id"]
    assert receipts_state.social["promises"][row["id"]]["status"] == "open"        # landed, not yet written
    assert receipts_state.social["promises"][row["id"]]["message_id"] == theirs[0]["id"]
    _voice_all(receipts_state, StubVoice("zero"))
    assert receipts_state.social["promises"][row["id"]]["status"] == "kept"         # kept when it is voiced (M2)


def test_the_players_talk_later_ends_the_conversation(receipts_state, matched, monkeypatch) -> None:
    """The chip sends the default line, records the player's promise, and the person's reply signs off
    with the engine's `player` reason: a natural end, the episode signed off."""
    from engine import social
    from engine.social import convo, promises

    thread = matched("matchstick")
    pid = thread.split(":")[1]
    _always_available(monkeypatch)
    monkeypatch.setattr(convo, "_promise_drawn", lambda state, pid_: True)   # never consulted: the player promised
    _open_episode(receipts_state, pid, thread)
    receipt = _act(receipts_state, "sign_off", target=thread, args={"who": "me", "window": "tonight"})
    assert receipt["success"], receipt
    (row,) = receipts_state.social["promises"].values()
    assert row["by"] == "player" and row["window"] == "tonight"
    sent = [m for m in receipts_state.social["threads"][thread]["messages"] if m["from"] == "player"]
    assert sent[-1]["bubbles"] == [f"Talk later — I'll message you {promises.window_words(row)}"]
    (reply,) = _due(receipts_state, thread)
    reasons = social.data("conversation")["reasons"]
    assert reply["decision"]["end"] == "sign_off" and reply["decision"]["reason"] == reasons["player"]
    assert reply["decision"]["promise_id"] == row["id"]
    assert receipts_state.social["people"][pid]["episode"]["end"] == "signed_off"


def test_message_me_at_work_lands_in_the_players_work_band(receipts_state, matched, monkeypatch) -> None:
    from engine.social import promises, windows

    pid = matched("matchstick").split(":")[1]
    span = windows.resolve(receipts_state, "player", "at_work", receipts_state.world_clock_hours)
    row = promises.make(receipts_state, pid, by="person", window="at_work")
    assert row["opens_at"] == pytest.approx(span[0])


def test_the_persons_sign_off_promise_is_recorded_before_voicing(receipts_state, matched, monkeypatch) -> None:
    """§5.2 route 2: their sign-off (a boundary 5 minutes off) draws a promise, recorded at the decision,
    and the due message names an open row before any voice runs."""
    from engine.social import convo

    thread = matched("matchstick")
    pid = thread.split(":")[1]
    _always_available(monkeypatch)
    monkeypatch.setattr(convo, "boundary_minutes", lambda state, pid_, at: 5.0)
    monkeypatch.setattr(convo, "_promise_drawn", lambda state, pid_: True)
    _open_episode(receipts_state, pid, thread)
    _act(receipts_state, "send", target=thread, args={"kind": "text"}, text="what are you up to later?")
    (due,) = _due(receipts_state, thread)
    assert due["decision"]["end"] == "sign_off"
    row = receipts_state.social["promises"][due["decision"]["promise_id"]]
    assert row["status"] == "open" and row["by"] == "person"
    assert row["window"] == convo.sign_off_window(receipts_state, pid, due["at"])


def test_a_breadcrumber_makes_no_promise(receipts_state, matched) -> None:
    """A breadcrumber's `promise_prob` is 0: "maybe later" is not a promise (§5.2)."""
    from engine.social import behaviour

    assert behaviour.archetype("breadcrumber").promise_prob == 0.0


def test_a_promise_beyond_48_hours_is_refused(receipts_state, matched, monkeypatch) -> None:
    from engine import social
    from engine.game import clock
    from engine.social import promises

    thread = matched("matchstick")
    pid = thread.split(":")[1]
    near = dict(social.data("promises"), max_ahead_hours=0.5)
    # With the shipped reach (48 hours): the weekend, from Monday morning, is too far off.
    monday = next(d for d in range(int(receipts_state.world_clock_hours // 24) + 1,
                                   int(receipts_state.world_clock_hours // 24) + 8) if d % 7 == 0)
    clock.advance_time(receipts_state, monday * 24 + 10 - receipts_state.world_clock_hours)
    assert promises.make(receipts_state, pid, by="person", window="weekend") is None
    assert promises.make(receipts_state, pid, by="person", window="tonight") is not None
    receipts_state.social["promises"].clear()
    receipts_state.social["queue"] = [e for e in receipts_state.social["queue"] if e["kind"] != "promise_due"]
    monkeypatch.setattr(promises, "_data", lambda: near)                   # and a reach of half an hour
    _set_clock(receipts_state, hour=15)
    assert promises.make(receipts_state, pid, by="person", window="morning") is None
    with _replies_forced():
        _open_episode(receipts_state, pid, thread)
        receipt = _act(receipts_state, "sign_off", target=thread, args={"who": "you", "window": "morning"})
    assert not receipt["success"] and receipt["result"]["error"] == "That's too far off to promise."
    assert not receipts_state.social["promises"]
    assert not [m for m in receipts_state.social["threads"][thread]["messages"] if m["from"] == "player"]


def test_a_typed_phrase_with_no_model_makes_a_promise(receipts_state, matched) -> None:
    from engine.social import promises

    assert promises.phrase_match("ok, message me in the morning") == ("you", "morning")
    assert promises.phrase_match("will you message me in the morning?") is None       # a question is not one
    assert promises.phrase_match("I'll text you in the morning!") == ("me", "morning")
    thread = matched("matchstick")
    pid = thread.split(":")[1]
    with _replies_forced():
        _open_episode(receipts_state, pid, thread)
        _act(receipts_state, "send", target=thread, args={"kind": "text"}, text="night! message me in the morning")
    assert [r for r in receipts_state.social["promises"].values() if r["by"] == "person" and r["window"] == "morning"]
    assert not receipts_state.social["people"][pid].get("promise_asked")          # accepted once, cleared


def test_the_promise_proposal_is_legal_only_while_winding(receipts_state, matched, monkeypatch) -> None:
    """§5.2 route 3: legal while the conversation winds down or is signed off; a window outside the row's
    list is refused; one in it is a promise of theirs."""
    from engine.game.effects import apply_effect
    from engine.social import relationships

    thread = matched("matchstick")
    pid = thread.split(":")[1]
    _set_clock(receipts_state, hour=10)
    _open_episode(receipts_state, pid, thread)
    assert "promise" not in relationships.legal_proposals(receipts_state, pid)
    apply_effect(receipts_state, {"type": "social_episode", "op": "end", "pid": pid, "end": "winding", "reason": "x",
                                  "at": receipts_state.world_clock_hours})
    assert "promise" in relationships.legal_proposals(receipts_state, pid)
    assert not relationships.apply_proposal(receipts_state, pid, "promise", args={"window": "weekend"})["ok"]
    made = relationships.apply_proposal(receipts_state, pid, "promise", args={"window": "tonight"})
    assert made["ok"]
    row = receipts_state.social["promises"][made["promise_id"]]
    assert row["by"] == "person" and row["window"] == "tonight"
    # No window (the production path until T7): the engine's own sign-off window, exactly.
    from engine.social import convo

    expected = convo.sign_off_window(receipts_state, pid, receipts_state.world_clock_hours)
    assert expected == "after_work"                                    # 10:00 on the plain week: work ends at 17
    named = relationships.apply_proposal(receipts_state, pid, "promise")
    assert named["ok"], named
    assert receipts_state.social["promises"][named["promise_id"]]["window"] == expected


# -- keeping them (§5.3) --------------------------------------------------------------------------------


def test_a_kept_player_promise_gains_and_a_broken_one_costs_once(receipts_state, matched) -> None:
    """Pre-flight F7/F16: every draw on this path is forced (`_replies_forced`: no ghost, every reply,
    always available), so the result never depends on the seed; and since T3 a ghost could not drop
    the player's `promise_close` anyway (it cancels only `events.REPLY_FAMILY`)."""
    from engine.game import clock
    from engine.social import growth, promises

    thread = matched("matchstick")
    pid = thread.split(":")[1]
    kept = promises.make(receipts_state, pid, by="player", window="tonight")
    clock.advance_time(receipts_state, kept["opens_at"] - receipts_state.world_clock_hours + 0.05)
    before = growth.record(receipts_state, pid)["openness"]
    with _replies_forced():
        _act(receipts_state, "send", target=thread, args={"kind": "text"}, text="as promised!")
    assert receipts_state.social["promises"][kept["id"]]["status"] == "kept"
    assert growth.record(receipts_state, pid)["openness"] > before
    broken = promises.make(receipts_state, pid, by="player", window="morning")
    judged = broken["closes_at"] + promises._data()["grace_minutes"] / 60.0
    with _replies_forced():
        clock.advance_time(receipts_state, judged - 0.01 - receipts_state.world_clock_hours)
        person = receipts_state.social["people"][pid]
        trust, warmth = person["trust"], person["warmth"]                    # just before it is judged
        clock.advance_time(receipts_state, 0.02)
    cost = promises._data()["broken"]
    assert receipts_state.social["promises"][broken["id"]]["status"] == "broken"
    assert person["trust"] == trust + cost["trust"] and person["warmth"] == warmth + cost["warmth"]   # once (M8)
    assert receipts_state.social["people"][pid]["broken_promise"] == broken["id"]


def test_a_broken_promise_is_carried_to_the_voice_once(receipts_state, matched, monkeypatch) -> None:
    from engine.game import clock
    from engine.social import promises

    thread = matched("matchstick")
    pid = thread.split(":")[1]
    _always_available(monkeypatch)
    row = promises.make(receipts_state, pid, by="player", window="morning")
    clock.advance_time(receipts_state, row["closes_at"] + 2 - receipts_state.world_clock_hours)
    words = promises.broken_reason(receipts_state, pid)
    assert words and promises.window_words(row) in words
    _open_episode(receipts_state, pid, thread)
    _act(receipts_state, "send", target=thread, args={"kind": "text"}, text="sorry, long day yesterday")
    (first,) = _due(receipts_state, thread)
    assert first["decision"]["reason"] == words
    first["voiced"] = True
    _act(receipts_state, "send", target=thread, args={"kind": "text"}, text="how was yours?")
    (second,) = _due(receipts_state, thread)
    assert second["decision"]["reason"] != words
    assert receipts_state.social["people"][pid].get("broken_promise") is None


def test_a_ghost_leaves_the_players_promise_to_close(receipts_state, matched, monkeypatch) -> None:
    """Pre-flight F7: a ghost cancels only the reply family, so the player's own promise to them still
    closes -- broken, never left open forever."""
    from engine.game import clock
    from engine.social import convo, promises

    thread = matched("matchstick")
    pid = thread.split(":")[1]
    monkeypatch.setattr(convo, "available", lambda state, pid_, at: convo.Availability(True))
    monkeypatch.setattr(convo, "_ghost_factor", lambda state, pid_: 1.0)
    _set_clock(receipts_state, hour=1)
    row = promises.make(receipts_state, pid, by="player", window="tonight")
    _act(receipts_state, "send", target=thread, args={"kind": "text"}, text="hey you")    # before the window
    assert receipts_state.social["people"][pid].get("ghosted")
    assert [e for e in receipts_state.social["queue"] if e["kind"] == "promise_close"]
    clock.advance_time(receipts_state, row["closes_at"] + 2 - receipts_state.world_clock_hours)
    assert receipts_state.social["promises"][row["id"]]["status"] == "broken"


def test_no_ghost_while_a_promise_is_open(receipts_state, matched, monkeypatch) -> None:
    from engine.game import clock
    from engine.social import convo, promises

    thread = matched("matchstick")
    pid = thread.split(":")[1]
    monkeypatch.setattr(convo, "_ghost_factor", lambda state, pid_: 1.0)
    promises.make(receipts_state, pid, by="person", window="morning")
    _act(receipts_state, "send", target=thread, args={"kind": "text"}, text="hi")
    clock.advance_time(receipts_state, 2)
    assert not receipts_state.social["people"][pid].get("ghosted")


def test_a_promise_to_someone_who_left_is_void(receipts_state, matched) -> None:
    from engine.game import clock
    from engine.game.effects import apply_effect
    from engine.social import promises

    pid = matched("matchstick").split(":")[1]
    theirs = promises.make(receipts_state, pid, by="person", window="morning")
    mine = promises.make(receipts_state, pid, by="player", window="tonight")
    apply_effect(receipts_state, {"type": "social_person", "pid": pid, "set": {"unmatched_by": "them"}})
    clock.advance_time(receipts_state, max(theirs["closes_at"], mine["closes_at"]) + 2
                       - receipts_state.world_clock_hours)
    assert receipts_state.social["promises"][theirs["id"]]["status"] == "void"
    assert receipts_state.social["promises"][mine["id"]]["status"] == "void"


def test_kept_promise_fills_openness(receipts_state, matched) -> None:
    """The flip of T2's stub (spec §24): promise_kept is no longer 0."""
    from engine.social import growth

    pid = matched("matchstick").split(":")[1]
    assert growth.gain(receipts_state, pid, "promise_kept") > 0


# -- waiting for one (§3.6) -----------------------------------------------------------------------------


def test_wait_until_a_promise_jumps_to_its_window(receipts_state, matched) -> None:
    from engine.social import intents, promises, turn

    thread = matched("matchstick")
    pid = thread.split(":")[1]
    _set_clock(receipts_state, hour=20)
    row = promises.make(receipts_state, pid, by="person", window="morning")
    due_at = next(e["at"] for e in receipts_state.social["queue"] if e["kind"] == "promise_due")
    target = f"promise:{row['id']}"
    verb = next(v for v in intents.legal_phone_intents(receipts_state) if v.action == "wait")
    assert target in verb.extra["until"]
    assert intents.label_of(receipts_state, {"action": "wait", "target": "", "args": {"until": target}}) \
        .startswith("Wait for ")
    with _replies_forced():
        receipt = _act(receipts_state, "wait", args={"until": target})
    assert receipt["success"], receipt
    assert receipts_state.world_clock_hours == pytest.approx(due_at)
    assert row["opens_at"] <= due_at <= row["closes_at"]
    assert [m for m in _due(receipts_state, thread) if m["decision"]["promise_id"] == row["id"]]
    assert target not in next(v for v in intents.legal_phone_intents(receipts_state)
                              if v.action == "wait").extra["until"]
    assert "promise_due" in turn.NOTIFYING


def test_wait_next_stops_at_a_promised_message(receipts_state, matched, monkeypatch) -> None:
    """Pre-flight's T4 note: `wait next` stops at a person's promised message (`promise_due` notifies)."""
    from engine.social import behaviour, promises, turn

    monkeypatch.setattr(behaviour, "_week", lambda shape: {d: [[0, 7, "asleep"], [7, 23, "free"], [23, 24, "asleep"]]
                                                           for d in behaviour.WEEKDAYS})
    pid = matched("matchstick").split(":")[1]
    _set_clock(receipts_state, hour=1)
    promises.make(receipts_state, pid, by="person", window="morning")
    # Every other notifying event out of the way, so the promise is the next thing that writes (lesson 1).
    receipts_state.social["queue"] = [e for e in receipts_state.social["queue"]
                                      if e["kind"] not in turn.NOTIFYING or e["kind"] == "promise_due"]
    due_at = next(e["at"] for e in receipts_state.social["queue"] if e["kind"] == "promise_due")
    assert due_at - receipts_state.world_clock_hours < 8.0                          # inside the wait's cap
    with _replies_forced():
        _act(receipts_state, "wait", args={"until": "next"})
    assert receipts_state.world_clock_hours == pytest.approx(due_at)


# -- sign-off away times (T3 review M6) -----------------------------------------------------------------


@pytest.mark.parametrize("term", ["energy", "length", "glance"])
def test_their_sign_off_is_away_as_long_as_its_reason_says(receipts_state, matched, monkeypatch, term) -> None:
    """The away time after a non-schedule sign-off is conversation.yaml's, by reason (T3 review M6): an
    energy, length or glance sign-off is gone that long, not a hard 15 minutes."""
    from engine import social
    from engine.social import convo

    thread = matched("matchstick")
    pid = thread.split(":")[1]
    _always_available(monkeypatch)
    monkeypatch.setattr(convo, "_promise_drawn", lambda state, pid_: False)
    if term == "glance":
        monkeypatch.setattr(convo, "available", lambda state, pid_, at: convo.Availability(True, "glance"))
    ep = _open_episode(receipts_state, pid, thread, target=1 if term == "length" else 50)
    if term == "energy":
        ep["energy"] = 0.0
    if term == "glance":
        ep["exchanges"] = 1                               # the glance's one exchange already made
    at = receipts_state.world_clock_hours
    _act(receipts_state, "send", target=thread, args={"kind": "text"}, text="ok tell me everything about it")
    (due,) = _due(receipts_state, thread)
    talk = social.data("conversation")["talk"]
    assert due["decision"]["end"] == "sign_off"
    assert due["decision"]["reason"] == social.data("conversation")["reasons"][term]
    minutes = talk["away_after_sign_off"][term]
    assert minutes > 15
    assert receipts_state.social["people"][pid]["episode"]["away_until"] == pytest.approx(at + minutes / 60.0)


def test_a_boundary_sign_off_is_away_at_least_until_the_boundary(receipts_state, matched, monkeypatch) -> None:
    from engine.social import convo

    thread = matched("matchstick")
    pid = thread.split(":")[1]
    _always_available(monkeypatch)
    monkeypatch.setattr(convo, "_promise_drawn", lambda state, pid_: False)
    monkeypatch.setattr(convo, "boundary_minutes", lambda state, pid_, at: 18.0)
    _open_episode(receipts_state, pid, thread, target=50)
    at = receipts_state.world_clock_hours
    _act(receipts_state, "send", target=thread, args={"kind": "text"}, text="what are you doing tonight then?")
    assert receipts_state.social["people"][pid]["episode"]["away_until"] == pytest.approx(at + 18.0 / 60.0)


# -- the payload and the data ---------------------------------------------------------------------------


def test_the_promises_payload_has_no_numbers(receipts_state, matched) -> None:
    from engine.social import payload, promises

    pid = matched("matchstick").split(":")[1]
    _set_clock(receipts_state, hour=20)
    row = promises.make(receipts_state, pid, by="person", window="morning")
    receipts_state.social["promises"][row["id"]]["opens_at"] = 1234.567891 + 24 * 400   # a sentinel value
    block = payload.phone_block(receipts_state)
    (shown,) = block["promises"]
    assert set(shown) == {"id", "pid", "name", "by", "window_words", "opens_at_words", "status"}
    text = json.dumps(block)
    assert "567891" not in text
    assert shown["window_words"] == "in the morning" and shown["status"] == "open"
    assert "promises" in payload.TIME_VARYING_SECTIONS


def test_the_shipped_promises_file_validates_clean() -> None:
    from pathlib import Path

    import yaml

    from engine.social import promises

    path = Path(__file__).resolve().parents[1] / "games" / "read-receipts" / "data" / "social" / "promises.yaml"
    promises.check_data(yaml.safe_load(path.read_text(encoding="utf-8")))


@pytest.mark.parametrize("key, value, where", [
    ("max_ahead_hours", -1, "max_ahead_hours"),
    ("broken", {"trust": 2, "warmth": -1}, "broken"),
    ("phrases", {"you": {"weekend": ["see you at the weekend"]}, "me": {}}, "phrases.you.weekend"),
    ("words", {"morning": "in the morning"}, "words."),
])
def test_a_broken_promises_file_names_its_key(key, value, where) -> None:
    from pathlib import Path

    import yaml

    from engine.social import promises

    path = Path(__file__).resolve().parents[1] / "games" / "read-receipts" / "data" / "social" / "promises.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data[key] = value
    with pytest.raises(ValueError, match=rf"promises\.yaml: {where.replace('.', chr(92) + '.')}"):
        promises.check_data(data)


# -- review fixes (T4 fix round 1) ------------------------------------------------------------------------


def test_one_talk_later_is_one_promise_when_the_decision_is_late(receipts_state, matched, monkeypatch) -> None:
    """Review I1: the chip's own default line ("I'll message you tonight") matches a phrase. With the
    window already open and the person's decision made LATER (a voicing commit's minute), it must not
    make a second promise: one row, one `promise_close`."""
    from engine.game import clock
    from engine.social import convo

    thread = matched("matchstick")
    pid = thread.split(":")[1]
    _always_available(monkeypatch)
    _set_clock(receipts_state, hour=20)
    _open_episode(receipts_state, pid, thread)
    _act(receipts_state, "send", target=thread, args={"kind": "text"}, text="good day?")
    (due,) = _due(receipts_state, thread)
    with convo.marking({due["id"]}):                                   # a voicing pass holds their reply
        assert _act(receipts_state, "sign_off", target=thread, args={"who": "me", "window": "tonight"})["success"]
    clock.advance_time(receipts_state, 20 / 60.0)
    due["voiced"], due["bubbles"] = True, ["it was fine"]               # that pass commits, 20 minutes on
    assert convo.after_commit(receipts_state, pid, thread, due["id"], receipts_state.world_clock_hours)
    rows = list(receipts_state.social["promises"].values())
    assert len(rows) == 1 and rows[0]["by"] == "player", rows
    assert len([e for e in receipts_state.social["queue"] if e["kind"] == "promise_close"]) == 1


def test_a_phrase_accepted_late_does_not_stack(receipts_state, matched) -> None:
    """Review I1: an open promise of the same side and window, overlapping, is the same promise."""
    from engine.social import promises

    pid = matched("matchstick").split(":")[1]
    _set_clock(receipts_state, hour=20)
    first = promises.make(receipts_state, pid, by="player", window="tonight")
    promises.note_player_text(receipts_state, pid, "talk later, i'll message you tonight",
                              receipts_state.world_clock_hours)
    again = promises.accept_asked(receipts_state, pid, receipts_state.world_clock_hours + 20 / 60.0)
    assert again["id"] == first["id"] and len(receipts_state.social["promises"]) == 1


def test_a_model_reproposal_does_not_stack(receipts_state, matched) -> None:
    from engine.game import clock
    from engine.game.effects import apply_effect
    from engine.social import relationships

    thread = matched("matchstick")
    pid = thread.split(":")[1]
    _set_clock(receipts_state, hour=19)
    _open_episode(receipts_state, pid, thread)
    apply_effect(receipts_state, {"type": "social_episode", "op": "end", "pid": pid, "end": "winding", "reason": "x",
                                  "at": receipts_state.world_clock_hours})
    one = relationships.apply_proposal(receipts_state, pid, "promise", args={"window": "tonight"})
    clock.advance_time(receipts_state, 0.25)
    two = relationships.apply_proposal(receipts_state, pid, "promise", args={"window": "tonight"})
    assert one["promise_id"] == two["promise_id"] and len(receipts_state.social["promises"]) == 1


def test_wait_next_skips_a_promise_no_longer_open(receipts_state, matched) -> None:
    """Review M1: a `promise_due` whose promise is void writes nothing, so `wait next` runs past it."""
    from engine.game.effects import apply_effect
    from engine.social import promises, turn

    pid = matched("matchstick").split(":")[1]
    _set_clock(receipts_state, hour=1)
    row = promises.make(receipts_state, pid, by="person", window="morning")
    apply_effect(receipts_state, {"type": "social_promise", "op": "void", "promise_id": row["id"]})
    receipts_state.social["queue"] = [e for e in receipts_state.social["queue"]
                                      if e["kind"] not in turn.NOTIFYING or e["kind"] == "promise_due"]
    assert turn._next_notifying_at(receipts_state) is None


def test_a_withdrawn_promised_message_voids_its_promise(receipts_state, matched) -> None:
    """Review M2: their promise is kept when the message is voiced; withdrawn unvoiced (they left), void."""
    from engine.game import clock
    from engine.game.effects import apply_effect
    from engine.social import promises

    thread = matched("matchstick")
    pid = thread.split(":")[1]
    _set_clock(receipts_state, hour=1)
    row = promises.make(receipts_state, pid, by="person", window="morning")
    with _replies_forced():
        clock.advance_time(receipts_state, row["closes_at"] + 0.1 - receipts_state.world_clock_hours)
    landed = receipts_state.social["promises"][row["id"]]
    assert landed["status"] == "open" and landed["message_id"]
    apply_effect(receipts_state, {"type": "social_voiced", "op": "withdraw", "thread_id": thread,
                                  "message_ids": [landed["message_id"]]})
    assert receipts_state.social["promises"][row["id"]]["status"] == "void"


def test_a_promised_message_that_cannot_land_voids_its_promise(receipts_state, matched) -> None:
    from engine.game import clock
    from engine.social import promises

    thread = matched("matchstick")
    pid = thread.split(":")[1]
    _set_clock(receipts_state, hour=1)
    row = promises.make(receipts_state, pid, by="person", window="morning")
    receipts_state.social["people"][pid]["ghosted"] = True             # their due message will not land
    with _replies_forced():
        clock.advance_time(receipts_state, row["closes_at"] + 0.1 - receipts_state.world_clock_hours)
    assert receipts_state.social["promises"][row["id"]]["status"] == "void"


def test_a_promised_message_keeps_its_own_new_promise(receipts_state, matched, monkeypatch) -> None:
    """Review M3: the promised message's own decision signs off with a NEW promise: the Decision names
    the new one, and the old one is still kept, by its landed message."""
    from engine.game import clock
    from engine.social import convo, promises

    thread = matched("matchstick")
    pid = thread.split(":")[1]
    _always_available(monkeypatch)
    monkeypatch.setattr(convo, "boundary_minutes", lambda state, pid_, at: 5.0)
    monkeypatch.setattr(convo, "_promise_drawn", lambda state, pid_: True)
    _set_clock(receipts_state, hour=1)
    old = promises.make(receipts_state, pid, by="person", window="morning")
    clock.advance_time(receipts_state, old["closes_at"] + 0.1 - receipts_state.world_clock_hours)
    message = next(m for m in _due(receipts_state, thread)
                   if m["decision"]["situation"] == "promised_message")
    assert message["decision"]["end"] == "sign_off"
    assert message["decision"]["promise_id"] not in ("", old["id"])
    assert receipts_state.social["promises"][message["decision"]["promise_id"]]["status"] == "open"
    _voice_all(receipts_state, StubVoice("zero"))
    assert receipts_state.social["promises"][old["id"]]["status"] == "kept"


def test_later_with_no_free_band_is_no_promise(receipts_state, matched, monkeypatch) -> None:
    """Review M4: a schedule with no free band in a week makes no promise; it never raises."""
    from engine.social import behaviour, promises

    monkeypatch.setattr(behaviour, "_week", lambda shape: {d: [[0, 24, "work"]] for d in behaviour.WEEKDAYS})
    pid = matched("matchstick").split(":")[1]
    assert promises.make(receipts_state, pid, by="person", window="later") is None


def test_morning_is_clipped_to_the_waking_band(receipts_state, matched, monkeypatch) -> None:
    """Review M5: a worker on 00:00-08:00 then asleep: "morning" ends at 08:00, never runs into sleep."""
    from engine.social import behaviour, windows

    monkeypatch.setattr(behaviour, "_week", lambda shape: {d: [[0, 8, "work"], [16, 24, "free"]]
                                                           for d in behaviour.WEEKDAYS})
    pid = matched("matchstick").split(":")[1]
    _set_clock(receipts_state, hour=3)
    span = windows.resolve(receipts_state, pid, "morning", receipts_state.world_clock_hours)
    assert span[0] == pytest.approx(_abs(receipts_state, 0, 7.0))
    assert span[1] == pytest.approx(_abs(receipts_state, 0, 8.0))


def test_waiting_for_your_own_promise_reads_as_yours(receipts_state, matched) -> None:
    """Review M7: the player's own promise's wait target says whose it is."""
    from engine.social import intents, messaging, promises

    pid = matched("matchstick").split(":")[1]
    _set_clock(receipts_state, hour=10)
    row = promises.make(receipts_state, pid, by="player", window="tonight")
    label = intents.label_of(receipts_state, {"action": "wait", "target": "",
                                              "args": {"until": f"promise:{row['id']}"}})
    assert label == f"Wait until tonight (you said you'd message {messaging._name(receipts_state, pid)})"


# -- T9 fix round 1 ---------------------------------------------------------------------------------------


def test_wait_next_stops_at_the_read_a_reply_follows(receipts_state, matched_numbers, monkeypatch) -> None:
    """`wait {until: next}` stops at the event that makes a reply due (T9 fix round 1): their READ of a cold
    message, which decides the reply at its own minute (spec §4.3), not only at notifying events -- so play
    never runs past a reply to the next notification or the 8-hour cap."""
    from engine.social import convo

    thread = matched_numbers("natter")   # a receipts app: the read shows the player a receipt
    pid = thread.split(":")[1]
    monkeypatch.setattr(convo, "_ghost_factor", lambda state, pid_: 0.0)
    monkeypatch.setattr(convo, "_reply_factor", lambda state, pid_: 100.0)
    _set_clock(receipts_state, hour=5)                           # they are asleep until 07:00 (PLAIN_WEEK)
    _act(receipts_state, "send", target=thread, args={"kind": "text"}, text="morning, how did you sleep?")
    read_at = _abs(receipts_state, 0, 7.0)
    # Nothing else that notifies is queued, so the read is the only thing the wait could stop at.
    receipts_state.social["queue"] = [e for e in receipts_state.social["queue"] if e["kind"] == "read"]
    assert any(e["kind"] == "read" and e["pid"] == pid and e["at"] == pytest.approx(read_at)
               for e in receipts_state.social["queue"])
    _act(receipts_state, "wait", args={"until": "next"})
    assert receipts_state.world_clock_hours == pytest.approx(read_at)
    assert any(m["at"] == pytest.approx(read_at) for m in _due(receipts_state, thread)), "no reply due at the read"


def test_wait_next_does_not_stop_at_a_read_the_player_cannot_see(receipts_state, matched_numbers, monkeypatch) -> None:
    """T9 fix round 3 (review M3): `wait {until: next}` stops at a read only when it shows the player
    something -- a receipt on a thread they can see. With their receipts off the read shows nothing, so the
    wait runs past it instead of stopping for no visible reason."""
    from engine.social import convo

    thread = matched_numbers("natter")
    pid = thread.split(":")[1]
    monkeypatch.setattr(convo, "_ghost_factor", lambda state, pid_: 0.0)
    monkeypatch.setattr(convo, "_reply_factor", lambda state, pid_: 100.0)
    receipts_state.social.setdefault("settings", {})["receipts"] = False        # their receipts off
    _set_clock(receipts_state, hour=5)
    _act(receipts_state, "send", target=thread, args={"kind": "text"}, text="morning, how did you sleep?")
    read_at = _abs(receipts_state, 0, 7.0)
    # Nothing else that notifies is queued, so the read is the only thing the wait could stop at.
    receipts_state.social["queue"] = [e for e in receipts_state.social["queue"] if e["kind"] == "read"]
    assert any(e["kind"] == "read" and e["pid"] == pid and e["at"] == pytest.approx(read_at)
               for e in receipts_state.social["queue"])
    _act(receipts_state, "wait", args={"until": "next"})
    assert receipts_state.world_clock_hours != pytest.approx(read_at)


def test_wait_next_does_not_stop_at_a_read_on_an_app_with_no_receipts(receipts_state, matched, monkeypatch) -> None:
    """The same on Matchstick, which keeps no read receipts: the read shows the player nothing."""
    from engine.social import convo

    thread = matched("matchstick")
    pid = thread.split(":")[1]
    monkeypatch.setattr(convo, "_ghost_factor", lambda state, pid_: 0.0)
    monkeypatch.setattr(convo, "_reply_factor", lambda state, pid_: 100.0)
    _set_clock(receipts_state, hour=5)
    _act(receipts_state, "send", target=thread, args={"kind": "text"}, text="morning, how did you sleep?")
    read_at = _abs(receipts_state, 0, 7.0)
    # Nothing else that notifies is queued, so the read is the only thing the wait could stop at.
    receipts_state.social["queue"] = [e for e in receipts_state.social["queue"] if e["kind"] == "read"]
    assert any(e["kind"] == "read" and e["pid"] == pid for e in receipts_state.social["queue"])
    _act(receipts_state, "wait", args={"until": "next"})
    assert receipts_state.world_clock_hours != pytest.approx(read_at)


def test_a_promise_into_the_window_open_now_is_its_next_occurrence(receipts_state, matched) -> None:
    """T9 fix round 1 (§5.1, §3.5 item 2): a promise names a LATER time, so a window already open when it is
    made resolves to that window's next occurrence -- "lunch" said at 12:30 is tomorrow's lunch."""
    from engine.social import promises

    pid = matched("matchstick").split(":")[1]
    _set_clock(receipts_state, hour=12.5)
    row = promises.make(receipts_state, pid, by="person", window="lunch")
    assert row is not None and row["opens_at"] == pytest.approx(_abs(receipts_state, 1, 12.0))
    _set_clock(receipts_state, hour=10)
    row = promises.make(receipts_state, pid, by="person", window="lunch")       # not open yet: today's
    assert row["opens_at"] == pytest.approx(_abs(receipts_state, 0, 12.0))


def test_a_glance_at_lunch_does_not_loop_through_the_hour(receipts_state, matched, monkeypatch) -> None:
    """T9's finding: someone at work who glances off at lunch promised `lunch` while it was lunch, so the
    promise fell due at once, opened a conversation that glanced off again with another lunch promise, and
    repeated through the window (two-exchange conversations, six promises in an hour). Now their promise
    is tomorrow's lunch, and nothing of theirs lands again in this one."""
    from engine.social import convo

    thread = matched("matchstick")
    pid = thread.split(":")[1]
    monkeypatch.setattr(convo, "available", lambda state, pid_, at: convo.Availability(True, "glance"))
    monkeypatch.setattr(convo, "boundary_minutes", lambda state, pid_, at: None)
    monkeypatch.setattr(convo, "_ghost_factor", lambda state, pid_: 0.0)
    monkeypatch.setattr(convo, "_reply_factor", lambda state, pid_: 100.0)
    monkeypatch.setattr(convo, "_promise_drawn", lambda state, pid_: True)
    _set_clock(receipts_state, hour=12.5)
    ep = _open_episode(receipts_state, pid, thread, target=50)
    ep["exchanges"] = 1                                          # the glance's one exchange already made
    _act(receipts_state, "send", target=thread, args={"kind": "text"}, text="quick one, how's the day going?")
    (due,) = _due(receipts_state, thread)
    assert due["decision"]["end"] == "sign_off" and due["decision"]["promise_id"]
    row = receipts_state.social["promises"][due["decision"]["promise_id"]]
    assert row["window"] == "lunch" and row["opens_at"] >= _abs(receipts_state, 1, 12.0) - 1e-9
    for _ in range(2):
        _act(receipts_state, "wait", args={"until": "1h"})       # to 14:30, past today's lunch
    landed = [m for m in _theirs(receipts_state, thread)
              if (m.get("decision") or {}).get("situation") == "promised_message"]
    assert not landed, "their lunch promise landed inside the lunch it was made in"
    assert len(receipts_state.social["promises"]) == 1


def test_closed_promises_are_forgotten_past_the_bound_keeping_what_is_read(receipts_state, matched) -> None:
    """T9 fix round 1 (bounded state, spec §17.2): closed promise rows past `promises.yaml` `closed_kept` per
    person leave state at compaction (`promises.forget_closed`, `social_promise` `op: forget`), oldest
    first, tallied on the person (`promises_closed`, by side and status). Open ones stay, and so does a
    closed one a reader still needs: the broken promise their next reply carries, one an episode due a
    recap names or made inside it, a due message's or queued event's, and the newest the payload lists."""
    from engine import social
    from engine.game import clock
    from engine.game.effects import apply_effect
    from engine.social import promises

    pid = matched("matchstick").split(":")[1]
    other = matched("front_porch").split(":")[1]
    made = []
    for i in range(12):
        clock.advance_time(receipts_state, 30.0)
        row = promises.make(receipts_state, pid, by="player" if i % 2 else "person", window="morning")
        made.append(row["id"])
        apply_effect(receipts_state, {"type": "social_promise", "op": "break" if i % 3 == 0 else "keep",
                                      "promise_id": row["id"]})
    pointer = made[3]
    apply_effect(receipts_state, {"type": "social_person", "pid": pid, "set": {"broken_promise": pointer}})
    for _ in range(6):                                            # another's, newer: the payload's newest five
        clock.advance_time(receipts_state, 30.0)
        row = promises.make(receipts_state, other, by="person", window="morning")
        apply_effect(receipts_state, {"type": "social_promise", "op": "keep", "promise_id": row["id"]})
    still = promises.make(receipts_state, pid, by="person", window="tonight")            # open
    keep = int(social.data("promises")["closed_kept"])
    before = {r["id"]: dict(r) for r in receipts_state.social["promises"].values()}
    shown = [r["id"] for r in promises._promises_section(receipts_state, None)]
    gone = promises.forget_closed(receipts_state)
    rows = receipts_state.social["promises"]
    assert gone > 0
    assert still["id"] in rows and pointer in rows
    mine = [r for r in rows.values() if r["pid"] == pid and r["status"] != "open"]
    newest = sorted((before[i] for i in made), key=lambda r: r["made_at"])[-keep:]
    assert {r["id"] for r in newest} <= {r["id"] for r in mine}
    assert len(mine) == keep + 1                                  # the newest `closed_kept`, and the pointer
    tally = receipts_state.social["people"][pid]["promises_closed"]
    forgotten = [before[i] for i in before if i not in rows]
    for side in ("person", "player"):
        for status in ("kept", "broken"):
            assert tally.get(side, {}).get(status, 0) == sum(
                1 for r in forgotten if r["pid"] == pid and r["by"] == side and r["status"] == status)
    assert promises.forget_closed(receipts_state) == 0            # idempotent
    assert [r["id"] for r in promises._promises_section(receipts_state, None)] == shown


def test_closed_kept_is_checked_at_load(receipts_active) -> None:
    import copy

    from engine import social
    from engine.social import promises

    data = copy.deepcopy(social.data("promises"))
    data["closed_kept"] = -1
    with pytest.raises(ValueError, match="closed_kept"):
        promises.check_data(data)
