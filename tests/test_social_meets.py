"""
Meet-ups (v0.22.0 spec §14, T24): proposing, the day, the outcome and the recap.

The engine resolves every meet (rule 1, on SOCIAL_MEET); the clock moves only
through `clock.advance_time` from the phone action (rule 2); every write is
the `social_meet` effect (rule 3). The model only narrates the recap, checked
against the band.
"""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest

from tests.social_fixtures import (  # noqa: F401
    _act, _at, _force_stage, _live_session, _matched_in, _set_person, matched, matched_numbers, numbers_pid,
    receipts_active, receipts_state,
)

VENUE = "copper_kettle"


# -- helpers ------------------------------------------------------------------------------------------


def _meet_view(band: str = "awkward") -> dict[str, Any]:
    from engine.social import meets

    return meets.view_of(name="Kai", venue_id=VENUE, band_name=band, topics=["climbing", "coffee"], pid="p0001",
                         thread_id="texts:p0001", message_ids=["m9"], meet_id="t1", when="Fri afternoon",
                         about="29, a nurse")


def _free(monkeypatch: pytest.MonkeyPatch) -> None:
    """Everyone is free at every hour (their schedule out of the way)."""
    from engine.social import behaviour

    monkeypatch.setattr(behaviour, "status_at", lambda person, at: "free")


def _as(monkeypatch: pytest.MonkeyPatch, pid: str, **fields: Any) -> None:
    """`pid`'s profile with `fields` replaced (a forced draw, F16)."""
    from engine.social import population

    real = population.profile
    monkeypatch.setattr(population, "profile",
                        lambda s, p: dataclasses.replace(real(s, p), **fields) if p == pid else real(s, p))


def _to(state, at: float) -> None:
    from engine.game import clock

    clock.advance_time(state, max(0.0, at - state.world_clock_hours))


def _agreed(state, pid: str, *, ahead: int = 1, slot: str = "afternoon", venue: str = VENUE) -> str:
    """A meet agreed through the effect itself (no player message, so no read of theirs runs)."""
    from engine.game.effects import apply_effect

    made = apply_effect(state, {"type": "social_meet", "op": "agree", "pid": pid, "venue": venue,
                                "day": state.world_day + ahead, "slot": slot})
    assert made["ok"], made
    return made["meet_id"]


def _go(state, mid: str) -> dict[str, Any]:
    _to(state, state.social["meets"][mid]["start"] + 1 / 60)
    assert state.social["meets"][mid]["status"] == "due"
    went = _act(state, "meet", target=mid, args={"do": "go"})
    assert went["success"], went
    return went["result"]


def _no_flake(monkeypatch: pytest.MonkeyPatch) -> None:
    """Nobody flakes (the flake draw forced false, F16)."""
    from engine.social import behaviour

    real = behaviour.archetype
    monkeypatch.setattr(behaviour, "archetype", lambda name: dataclasses.replace(real(name), flake_prob=0.0))


def meets_data_bands() -> dict[str, float]:
    """relationships.yaml `meets.bands` (the least quality of each band), as the engine reads them."""
    from engine.social import meets

    return {k: float(v) for k, v in (meets._rules().get("bands") or {}).items()}


def _quality(monkeypatch: pytest.MonkeyPatch, q: float) -> None:
    from engine.social import meets

    monkeypatch.setattr(meets, "quality", lambda state, meet: q)


def _free_slot(state, pid: str) -> tuple[int, str]:
    from engine.social import meets

    hours = float(meets.venue(VENUE)["duration_hours"])
    for ahead in range(1, 8):
        for slot in meets.slots():
            if meets.slot_free(state, pid, state.world_day + ahead, slot, hours):
                return ahead, slot
    raise AssertionError("no free slot in a week")


def _warmth(state, pid: str) -> int:
    return int(state.social["people"][pid]["warmth"])


# -- the prompt --------------------------------------------------------------------------------------


def test_the_recap_prompt_is_exactly_its_blocks(receipts_active) -> None:
    from engine import social
    from engine.social import meets

    text = (social.social_dir().parent.parent / "prompts" / "date_recap.md").read_text(encoding="utf-8")
    msgs = meets.recap_messages(_meet_view(band="awkward"))
    assert [m["role"] for m in msgs] == ["system", "user"] and msgs[0]["content"] == text
    titles = [part.split("\n", 1)[0] for part in msgs[1]["content"].split("\n\n")]
    assert titles == ["WHO", "WHERE", "HOW IT WENT", "TOPICS", "FORMAT"]
    blocks = dict(part.split("\n", 1) for part in msgs[1]["content"].split("\n\n"))
    assert blocks["WHERE"].startswith("Coffee at The Copper Kettle")
    assert blocks["HOW IT WENT"] == "awkward: It was a little awkward."
    assert blocks["TOPICS"] == "climbing, coffee"


# -- proposing (§14.1) ------------------------------------------------------------------------------------


def test_an_agreed_meet_is_a_calendar_row_and_a_start_event(receipts_state, numbers_pid) -> None:
    from engine.social import meets, payload

    state, pid = receipts_state, numbers_pid
    ahead, slot = _free_slot(state, pid)
    day = state.world_day + ahead
    made = _act(state, "propose_meet", target=pid, args={"venue": VENUE, "day": ahead, "slot": slot})
    assert made["success"], made
    assert made["result"]["answer"] == "accept"
    mid = made["result"]["meet_id"]
    row = state.social["meets"][mid]
    assert (row["pid"], row["venue"], row["day"], row["slot"], row["status"]) == (pid, VENUE, day, slot, "agreed")
    assert row["start"] == meets.slot_start(day, slot) and isinstance(row["flake"], bool)
    (cal,) = payload.phone_block(state)["calendar"]
    assert (cal["id"], cal["status"], cal["place"]) == (mid, "agreed", "Coffee at The Copper Kettle")
    assert "flake" not in cal
    starts = [e for e in state.social["queue"] if e["kind"] == "meet_start" and e.get("meet_id") == mid]
    assert [e["at"] for e in starts] == [row["start"]]
    assert state.social["people"][pid]["stage"] == "meeting"          # the meet stage's trigger: a meet agreed
    thread = state.social["threads"][f"texts:{pid}"]["messages"]
    assert thread[-2]["from"] == "player" and thread[-2]["ask"] == "meet"
    assert thread[-1]["from"] == "system" and thread[-1]["bubbles"][0].endswith(f"{meets.when_words(row)}.")


def test_a_busy_slot_is_countered_with_the_nearest_free_one(receipts_state, numbers_pid, monkeypatch) -> None:
    from engine.social import behaviour, meets

    state, pid = receipts_state, numbers_pid
    day = state.world_day + 2
    busy = (meets.slot_start(day, "afternoon"), meets.slot_start(day, "afternoon") + 4)

    def status_at(person, at: float) -> str:
        return "work" if busy[0] <= at < busy[1] else "free"

    monkeypatch.setattr(behaviour, "status_at", status_at)
    made = _act(state, "propose_meet", target=pid, args={"venue": VENUE, "day": 2, "slot": "afternoon"})
    assert made["success"], made
    assert made["result"]["answer"] == "counter"
    assert made["result"]["counter"] == {"day": 2, "slot": "morning"}    # 4 h off, nearer than the evening's 5
    assert not state.social["meets"] and state.social["people"][pid]["stage"] == "numbers"
    line = state.social["threads"][f"texts:{pid}"]["messages"][-1]
    assert line["from"] == "system" and "works" in line["bubbles"][0]


def test_a_counter_line_carries_its_slot_and_accepting_it_agrees_the_meet(receipts_state, numbers_pid,
                                                                            monkeypatch) -> None:
    """
    A counter-offer is acceptable in one tap (T30 follow-up): its line carries the countered venue, day and
    slot, and the player's view of it says whether it is still open; sending it back through the same
    `propose_meet` agrees the meet, after which the line is no longer open.
    """
    from engine.social import behaviour, meets, messaging

    state, pid = receipts_state, numbers_pid
    day = state.world_day + 2
    busy = (meets.slot_start(day, "afternoon"), meets.slot_start(day, "afternoon") + 4)
    monkeypatch.setattr(behaviour, "status_at", lambda person, at: "work" if busy[0] <= at < busy[1] else "free")
    assert _act(state, "propose_meet", target=pid, args={"venue": VENUE, "day": 2, "slot": "afternoon"})["success"]
    t = state.social["threads"][f"texts:{pid}"]
    line = t["messages"][-1]
    assert line["counter"] == {"venue": VENUE, "day": day, "slot": "morning"}
    view = messaging.message_view(state, t, line)["counter"]
    assert view["venue"] == VENUE and view["slot"] == "morning" and view["days_ahead"] == 2 and view["open"] is True
    assert view["when"] == meets.when_words({"start": meets.slot_start(day, "morning")})
    made = _act(state, "propose_meet", target=pid,
                args={"venue": view["venue"], "day": view["days_ahead"], "slot": view["slot"]})
    assert made["success"] and made["result"]["answer"] == "accept", made
    assert messaging.message_view(state, t, line)["counter"]["open"] is False


def test_below_the_meeting_gate_the_answer_is_not_yet(receipts_state, numbers_pid, monkeypatch) -> None:
    from engine.social import relationships
    from tests.social_fixtures import _just_below

    _free(monkeypatch)
    _set_person(receipts_state, numbers_pid, **_just_below(relationships.gate_spec("meeting")))
    made = _act(receipts_state, "propose_meet", target=numbers_pid, args={"venue": VENUE, "day": 1, "slot": "evening"})
    assert made["success"] and made["result"]["answer"] == "not_yet", made
    assert not receipts_state.social["meets"]


def test_meet_is_legal_only_when_due(receipts_state, numbers_pid, monkeypatch) -> None:
    from engine.social import meets

    _free(monkeypatch)
    _no_flake(monkeypatch)
    state = receipts_state
    mid = _act(state, "propose_meet", target=numbers_pid,
               args={"venue": VENUE, "day": 1, "slot": "afternoon"})["result"]["meet_id"]
    early = _act(state, "meet", target=mid, args={"do": "go"})
    assert early["refused"] and early["result"]["error"].startswith("It isn't time yet"), early
    row = state.social["meets"][mid]
    _to(state, row["start"] + 1 / 60)
    assert row["status"] == "due"
    assert any(n["kind"] == "meet_start" for n in state.social["notifications"])
    before = state.world_clock_hours
    went = _act(state, "meet", target=mid, args={"do": "go"})
    assert went["success"], went
    assert went["result"]["band"] in meets.BANDS and row["status"] == "done" and row["band"] == went["result"]["band"]
    assert state.world_clock_hours == pytest.approx(before + row["hours"])   # the venue's duration, advance_time's
    again = _act(state, "meet", target=mid, args={"do": "go"})
    assert again["refused"] and again["result"]["error"] == "That meet-up is over."


def test_a_late_cancel_costs_more(receipts_state, numbers_pid, monkeypatch) -> None:
    from engine.social import meets

    _free(monkeypatch)
    state, pid = receipts_state, numbers_pid
    _as(monkeypatch, pid, archetype="steady")
    _set_person(state, pid, warmth=90, trust=90)                       # past the meeting gate, two cancels on
    early_id = _act(state, "propose_meet", target=pid, args={"venue": VENUE, "day": 4, "slot": "evening"})
    early_id = early_id["result"]["meet_id"]
    hours_early = state.social["meets"][early_id]["start"] - state.world_clock_hours
    assert hours_early >= 72
    before = _warmth(state, pid)
    assert _act(state, "meet", target=early_id, args={"do": "cancel"})["success"]
    early = _warmth(state, pid) - before
    late_id = _act(state, "propose_meet", target=pid, args={"venue": VENUE, "day": 1, "slot": "evening"})
    late_id = late_id["result"]["meet_id"]
    _to(state, state.social["meets"][late_id]["start"] - 1.0)
    before = _warmth(state, pid)
    assert _act(state, "meet", target=late_id, args={"do": "cancel"})["success"]
    late = _warmth(state, pid) - before
    assert early == meets.cancel_cost(hours_early)["warmth"]
    assert late == meets.cancel_cost(1.0)["warmth"]
    assert late < early < 0
    assert state.social["meets"][late_id]["status"] == "cancelled"
    _to(state, state.social["meets"][late_id]["start"] + 1 / 60)          # its start event finds it called off
    assert state.social["meets"][late_id]["status"] == "cancelled"


def test_no_answer_by_the_slots_end_is_a_no_show(receipts_state, numbers_pid, monkeypatch) -> None:
    from engine import social

    _free(monkeypatch)
    _no_flake(monkeypatch)
    state, pid = receipts_state, numbers_pid
    _as(monkeypatch, pid, archetype="steady")
    _set_person(state, pid, warmth=70, trust=60)
    mid = _agreed(state, pid)
    row = state.social["meets"][mid]
    before = _warmth(state, pid)
    _to(state, row["end"] + 1 / 60)
    assert row["status"] == "no_show"
    cost = social.data("relationships")["meets"]["no_show"]
    assert _warmth(state, pid) == before + cost["warmth"]
    history = state.social["people"][pid]["history"]
    assert history[-1]["kind"] == "no_show"
    refused = _act(state, "meet", target=mid, args={"do": "go"})
    assert refused["refused"] and refused["result"]["error"] == "That meet-up is over."


def test_a_flake_is_drawn_at_agreement_and_shown_at_the_start(receipts_state, numbers_pid, monkeypatch) -> None:
    from engine.social import behaviour, population

    _free(monkeypatch)
    state, pid = receipts_state, numbers_pid
    real = behaviour.archetype
    monkeypatch.setattr(behaviour, "archetype", lambda name: dataclasses.replace(real(name), flake_prob=1.0))
    name = population.profile(state, pid).name
    mid = _act(state, "propose_meet", target=pid, args={"venue": VENUE, "day": 2, "slot": "evening"})["result"]["meet_id"]
    row = state.social["meets"][mid]
    assert row["flake"] is True and row["status"] == "agreed"          # decided at agreement, before the day
    assert state.social["people"][pid]["rng_n"]["social.meet"] == 1     # one SOCIAL_MEET draw
    _to(state, row["start"] + 1 / 60)
    assert row["status"] == "flaked"
    last = state.social["threads"][f"texts:{pid}"]["messages"][-1]
    assert (last["from"], last["bubbles"]) == ("system", [f"{name} cancelled."])
    assert state.social["notifications"][-1]["kind"] == "meet_flaked"
    refused = _act(state, "meet", target=mid, args={"do": "go"})
    assert refused["refused"] and refused["result"]["error"] == f"{name} cancelled."


@pytest.mark.parametrize(("intent", "stage"), [("long_term", "dating"), ("friendship", "friends")])
def test_two_good_meets_move_meeting_to_its_branch(receipts_state, numbers_pid, monkeypatch, intent, stage) -> None:
    _free(monkeypatch)
    state, pid = receipts_state, numbers_pid
    _as(monkeypatch, pid, archetype="steady", intent=intent)
    state.social["player"]["looking_for"] = intent
    _quality(monkeypatch, 0.65)                                        # good
    _no_flake(monkeypatch)
    first = _agreed(state, pid)
    assert state.social["people"][pid]["stage"] == "meeting"
    assert _go(state, first)["band"] == "good"
    assert state.social["people"][pid]["stage"] == "meeting" and state.social["people"][pid]["meets_good"] == 1
    second = _agreed(state, pid)
    assert _go(state, second)["band"] == "good"
    assert state.social["people"][pid]["stage"] == stage
    kinds = [h["kind"] for h in state.social["people"][pid]["history"]]
    assert kinds.count("meet") == 2 and kinds[-1] == stage


@pytest.mark.parametrize(("q", "archetype", "sent"), [(0.0, "steady", False), (0.65, "ghoster", False),
                                                      (0.65, "steady", True)])
def test_a_bad_meet_or_a_ghoster_sends_no_post_meet(receipts_state, numbers_pid, monkeypatch, q, archetype,
                                                    sent) -> None:
    _free(monkeypatch)
    state, pid = receipts_state, numbers_pid
    _as(monkeypatch, pid, archetype=archetype)
    _quality(monkeypatch, q)
    _no_flake(monkeypatch)
    mid = _agreed(state, pid)
    result = _go(state, mid)
    assert result["band"] == ("bad" if q == 0.0 else "good")
    queued = [e for e in state.social["queue"] if (e.get("decision") or {}).get("situation") == "post_meet"]
    assert bool(queued) is sent
    if sent:
        assert queued[0]["decision"]["meet_id"] == mid and queued[0]["pid"] == pid
    from engine.social import messaging

    recap = state.social["threads"][messaging.thread_for(state, pid)]["messages"][-1]   # the thread they reply in
    assert (recap["from"], recap["kind"], recap["voiced"]) == ("system", "recap", False)
    assert recap["decision"]["meet_id"] == mid


def test_the_quality_draw_is_social_meets_and_bands_from_data(receipts_state, numbers_pid, monkeypatch) -> None:
    from engine import social
    from engine.game.rng import SOCIAL_MEET
    from engine.social import meets

    bands = social.data("relationships")["meets"]["bands"]
    assert [meets.band(bands[b]) for b in ("great", "good", "fine", "awkward")] == ["great", "good", "fine", "awkward"]
    assert meets.band(bands["awkward"] - 0.01) == "bad"
    _free(monkeypatch)
    _no_flake(monkeypatch)
    mid = _agreed(receipts_state, numbers_pid)
    counters = receipts_state.social["people"][numbers_pid]["rng_n"]
    drawn = counters.get(SOCIAL_MEET, 0)
    _go(receipts_state, mid)
    assert counters[SOCIAL_MEET] == drawn + 1


# -- the recap (§14.4) --------------------------------------------------------------------------------------


def test_a_recap_contradicting_its_band_falls_back_to_the_engine_line(receipts_active) -> None:
    from engine.social import meets

    calls: list[Any] = []

    def stub(messages, fmt):
        calls.append(messages)
        return "best night ever, honestly"

    reply = meets.voice_recap(_meet_view(band="awkward"), stub)
    assert len(calls) == 2 and "best night ever" in calls[1][-1]["content"]   # one retry, with the correction
    assert reply.bubbles == ["Coffee at The Copper Kettle with Kai. It was a little awkward."]
    assert reply.fallback is True and reply.failures == ["band", "band"] and reply.regard == {}


def test_a_recap_that_agrees_is_kept(receipts_active) -> None:
    from engine.social import meets

    text = "You met Kai at The Copper Kettle. It wasn't a disaster, but the talk kept stalling over the climbing."
    reply = meets.voice_recap(_meet_view(band="awkward"), lambda m, f: text)
    assert reply.bubbles == [text] and reply.fallback is False and reply.failures == []
    glowing = meets.voice_recap(_meet_view(band="great"), lambda m, f: "You two hit it off from the first coffee.")
    assert glowing.fallback is False
    assert meets.voice_recap(_meet_view(band="great"), None).bubbles == [
        "Coffee at The Copper Kettle with Kai. It went really well."]


def test_the_recap_is_voiced_by_the_pass_and_moves_no_regard(receipts_active, monkeypatch) -> None:
    from engine.session.store import release_turn
    from engine.social import messaging, relationships, voicer

    _free(monkeypatch)
    _no_flake(monkeypatch)
    bands = meets_data_bands()
    _quality(monkeypatch, (bands["fine"] + bands["good"]) / 2)        # fine, wherever the data puts it
    _scene, session = _live_session()
    state = session.engine.state
    tid = _matched_in(session, "matchstick")
    pid = tid.split(":", 1)[1]
    _as(monkeypatch, pid, archetype="steady")
    assert session.lock.acquire(blocking=False)
    try:
        _force_stage(state, pid, "numbers")
        messaging.open_numbers(state, pid)
        _set_person(state, pid, **_at(relationships.gate_spec("meeting")))
        mid = _agreed(state, pid)
        _to(state, state.social["meets"][mid]["start"] + 1 / 60)
        from engine.social import meets

        assert meets.go(state, mid)["band"] == "fine"
    finally:
        release_turn(session)
    recap = [m for t in state.social["threads"].values() for m in t["messages"] if m["kind"] == "recap"][0]
    warmth = state.social["people"][pid]["warmth"]
    text = "You met them at The Copper Kettle; it was fine, pleasant enough."
    voicer.run_until_quiet(session, lambda messages, fmt: text if messages[0]["content"].startswith("Write a short")
                           else '{"bubbles": [{"text": "hey"}], "regard": {"warmth": 0, "trust": 0, "mood": "neutral"}}')
    assert recap["bubbles"] == [text] and recap["voiced"] is True
    assert state.social["people"][pid]["warmth"] == warmth


# -- asks and proposals: the engine picks (§10.5) ------------------------------------------------------


def test_their_ask_meet_is_a_request_the_player_answers(receipts_state, numbers_pid, monkeypatch) -> None:
    from engine.social import meets, payload, relationships

    _free(monkeypatch)
    state, pid = receipts_state, numbers_pid
    assert "ask_meet" in relationships.legal_proposals(state, pid)
    made = relationships.apply_proposal(state, pid, "ask_meet")
    assert made["ok"], made
    request = state.social["requests"][made["request_id"]]
    assert request["what"] == "meet" and request["venue"] in meets.venue_ids() and request["slot"] in meets.slots()
    assert "ask_meet" not in relationships.legal_proposals(state, pid)              # one at a time
    (row,) = payload.phone_block(state)["requests"]
    assert (row["what"], row["venue"]) == ("meet", request["venue"])
    # T28: the thread's request card words it as the calendar does.
    assert row["venue_label"] == meets.venue(request["venue"])["label"]
    assert row["when"] == meets.when_words({"start": meets.slot_start(request["day"], request["slot"])})
    answered = _act(state, "answer", target=made["request_id"], args={"reply": "yes"})
    assert answered["success"], answered
    meet = state.social["meets"][answered["result"]["meet_id"]]
    assert (meet["by"], meet["venue"], meet["day"], meet["slot"]) == ("them", request["venue"], request["day"],
                                                                       request["slot"])
    assert state.social["people"][pid]["stage"] == "meeting"


def test_an_unreadable_venue_costs_only_its_words(receipts_state, numbers_pid, monkeypatch) -> None:
    """T28 review M3: a meet request whose venue cannot be read still lists, named by its id."""
    from engine.social import meets, payload, relationships

    _free(monkeypatch)
    made = relationships.apply_proposal(receipts_state, numbers_pid, "ask_meet")
    assert made["ok"], made
    request = receipts_state.social["requests"][made["request_id"]]

    def boom(*_a, **_k):
        raise RuntimeError("venues unreadable")

    monkeypatch.setattr(meets, "venue", boom)
    (row,) = payload.phone_block(receipts_state)["requests"]
    assert row["venue_label"] == request["venue"] and row["when"]


def test_the_players_ask_to_meet_is_answered_at_their_read(receipts_state, numbers_pid, monkeypatch) -> None:
    _free(monkeypatch)
    state, pid = receipts_state, numbers_pid
    _as(monkeypatch, pid, archetype="steady")
    tid = f"texts:{pid}"
    asked = _act(state, "ask", target=tid, args={"what": "meet"})
    assert asked["success"], asked
    rid = asked["result"]["request_id"]
    read = [e for e in state.social["queue"] if e["kind"] == "read" and e["pid"] == pid][0]
    _to(state, read["at"] + 1 / 60)
    assert state.social["requests"][rid]["status"] == "yes"
    (meet,) = state.social["meets"].values()
    assert meet["status"] == "agreed" and meet["by"] == "player"
    refused = _act(state, "ask", target=tid, args={"what": "meet"})
    assert refused["refused"] and "already have plans" in refused["result"]["error"]


# -- data, views -------------------------------------------------------------------------------------------


def test_the_meet_data_is_checked(receipts_active) -> None:
    from engine import social
    from engine.social import meets

    venues = social.data("venues")
    rel = social.data("relationships")
    pop = social.data("population")
    assert meets.meet_faults(venues, rel, pop) == []
    assert len(venues["venues"]) >= meets.MIN_VENUES
    few = {**venues, "venues": venues["venues"][:3]}
    assert ("venues.yaml", "venues", "must list 12 venues or more") in meets.meet_faults(few, rel, pop)
    bad = {**venues, "venues": [{**venues["venues"][0], "neighbourhood": "atlantis"}] + venues["venues"][1:]}
    assert any(k == "venues[0].neighbourhood" for _f, k, _m in meets.meet_faults(bad, rel, pop))
    broken = {**rel, "meets": {**rel["meets"], "bands": {"good": 0.6, "great": 0.75}}}
    assert any(k == "meets.bands" for _f, k, _m in meets.meet_faults(venues, broken, pop))
    assert meets.meet_faults({}, {k: v for k, v in rel.items() if k != "meets"}, pop) == []   # no meet-ups at all


def test_the_agreement_view_carries_the_meets_and_now(receipts_state, numbers_pid, monkeypatch) -> None:
    from engine.social import agreement

    _free(monkeypatch)
    mid = _agreed(receipts_state, numbers_pid)
    view = agreement.view_from_state(receipts_state, numbers_pid)
    assert [m["id"] for m in view.agreed_meets] == [mid] and view.now == receipts_state.world_clock_hours
    tomorrow = {"bubbles": ["see you tomorrow!"], "shared": [], "learned": []}
    tonight = {"bubbles": ["see you tonight!"], "shared": [], "learned": []}
    decision = agreement.Decision(situation="reply")
    assert [f.check for f in agreement.check(tomorrow, decision, view)] == []
    assert [f.check for f in agreement.check(tonight, decision, view)] == ["meeting_claimed"]


def test_meeting_claimed_fixtures_both_ways(receipts_active) -> None:
    from tests.test_social_agreement import CHECKS, _cases

    from engine.social import agreement

    assert "meeting_claimed" in CHECKS and "meeting_claimed" in agreement.STATE_CHECKS
    for case in _cases("meeting_claimed", "bad"):
        found = agreement.check(case["reply"], agreement.decision_of(case), agreement.view_of(case))
        assert any(f.check == "meeting_claimed" for f in found), case
    for case in _cases("meeting_claimed", "good"):
        assert agreement.check(case["reply"], agreement.decision_of(case), agreement.view_of(case)) == [], case


# -- review fixes (T24 fix round 1) ---------------------------------------------------------------------


def test_a_ghost_gives_no_answer_to_a_proposal(receipts_state, numbers_pid, monkeypatch) -> None:
    """I1: the bubble lands and the ask counts; no engine line, no row, no stage move."""
    from engine.social import messaging, relationships

    _free(monkeypatch)
    state, pid = receipts_state, numbers_pid
    _set_person(state, pid, ghosted=True)
    made = _act(state, "propose_meet", target=pid, args={"venue": VENUE, "day": 1, "slot": "evening"})
    assert made["success"] and made["result"]["answer"] == "unanswered", made
    assert state.social["meets"] == {} and state.social["people"][pid]["stage"] == "numbers"
    assert relationships.asks_today(state, pid, "meet") == 1
    last = state.social["threads"][messaging.thread_for(state, pid)]["messages"][-1]
    assert (last["from"], last.get("ask")) == ("player", "meet")


def _their_request(state, pid: str) -> dict[str, Any]:
    from engine.social import relationships

    made = relationships.apply_proposal(state, pid, "ask_meet")
    assert made["ok"], made
    return state.social["requests"][made["request_id"]]


def test_their_meet_request_lapses_at_its_slot_at_no_cost(receipts_state, numbers_pid, monkeypatch) -> None:
    """I2: unanswered by the slot's start it is answered no by the engine, free, with an engine line; it stops
    blocking the player's proposals and is no answer option."""
    from engine.social import meets, messaging

    _free(monkeypatch)
    _no_flake(monkeypatch)
    state, pid = receipts_state, numbers_pid
    _as(monkeypatch, pid, archetype="steady")
    request = _their_request(state, pid)
    refused = _act(state, "propose_meet", target=pid, args={"venue": VENUE, "day": 3, "slot": "evening"})
    assert refused["refused"] and "already asked to meet" in refused["result"]["error"]
    start = meets.slot_start(request["day"], request["slot"])
    _to(state, start - 0.5)
    warmth = _warmth(state, pid)
    _to(state, start + 1 / 60)
    assert request["status"] == "no" and request["lapsed"] is True
    assert _warmth(state, pid) == warmth                                   # no turned_down cost
    line = state.social["threads"][messaging.thread_for(state, pid)]["messages"][-1]
    assert line["from"] == "system" and line["bubbles"][0].endswith("lapsed.")
    assert _act(state, "answer", target=request["id"], args={"reply": "yes"})["refused"] is True
    again = _act(state, "propose_meet", target=pid, args={"venue": VENUE, "day": 3, "slot": "evening"})
    assert again["success"], again


def test_an_answered_meet_requests_lapse_never_stops_wait_next(receipts_state, numbers_pid, monkeypatch) -> None:
    """Final review M1: once answered, its slot's lapse event is no notification -- `wait {until: next}` runs past."""
    from engine.social import meets, turn

    _free(monkeypatch)
    state, pid = receipts_state, numbers_pid
    request = _their_request(state, pid)
    start = meets.slot_start(request["day"], request["slot"])
    state.social["queue"][:] = [e for e in state.social["queue"]
                                if e["kind"] not in turn.NOTIFYING or e.get("request_id") == request["id"]]
    assert turn._next_notifying_at(state) == start                        # unanswered: it stops there
    assert _act(state, "answer", target=request["id"], args={"reply": "no"})["success"]
    assert request["status"] == "no"
    assert turn._next_notifying_at(state) is None                         # answered: nothing to stop at


@pytest.mark.parametrize("how", ["ended", "unmatched"])
def test_a_lapse_writes_no_line_into_a_gone_or_ended_persons_thread(receipts_state, numbers_pid, monkeypatch,
                                                                     how: str) -> None:
    """Final review M1: the request still lapses, but nothing is said in a thread they left."""
    from engine.game.effects import apply_effect
    from engine.social import messaging

    _free(monkeypatch)
    state, pid = receipts_state, numbers_pid
    request = _their_request(state, pid)
    t = state.social["threads"][messaging.thread_for(state, pid)]
    if how == "ended":
        _force_stage(state, pid, "ended")
    else:
        _set_person(state, pid, unmatched_by="player")
        t["closed"] = "unmatched"
    before = len(t["messages"])
    assert apply_effect(state, {"type": "social_meet", "op": "lapse", "request_id": request["id"],
                                "at": state.world_clock_hours})["ok"]
    assert request["status"] == "no" and request["lapsed"] is True
    assert not any(str(b).endswith("lapsed.") for m in t["messages"][before:] for b in m.get("bubbles") or [])


def test_a_meet_request_whose_slot_is_taken_lapses_next_morning(receipts_state, numbers_pid, matched,
                                                                monkeypatch) -> None:
    from engine.game.effects import apply_effect
    from engine.social import intents, meets

    _free(monkeypatch)
    state, pid = receipts_state, numbers_pid
    request = _their_request(state, pid)
    other = matched("front_porch").split(":", 1)[1]
    _force_stage(state, other, "numbers")
    assert apply_effect(state, {"type": "social_meet", "op": "agree", "pid": other, "venue": VENUE,
                                "day": request["day"], "slot": request["slot"]})["ok"]
    assert not meets.still_open(state, request)                       # the player's slot is taken now
    answers = next((v for v in intents.legal_phone_intents(state) if v.action == "answer"), None)
    assert answers is None or request["id"] not in answers.targets
    daily = min(e["at"] for e in state.social["queue"] if e["kind"] == "daily")
    _to(state, daily + 1 / 60)
    assert request["status"] == "no" and request["lapsed"] is True


def test_a_fine_recap_may_not_say_it_went_badly(receipts_active) -> None:
    """M1: `fine` is contradicted both ways."""
    from engine.social import meets

    reply = meets.voice_recap(_meet_view(band="fine"), lambda m, f: "Honestly it was a disaster from the start.")
    assert reply.fallback is True and reply.bubbles == ["Coffee at The Copper Kettle with Kai. It was fine."]


def test_a_meet_missed_while_away_is_a_no_show_told_in_the_past(receipts_state, numbers_pid, monkeypatch) -> None:
    """M2 (ruling): one away advance across a planned meet makes it a no-show; the start's notification
    names its time, never "now", and the no-show has its own."""
    from engine.game import clock

    _free(monkeypatch)
    _no_flake(monkeypatch)
    state, pid = receipts_state, numbers_pid
    mid = _agreed(state, pid)
    clock.advance_time(state, 72.0)                                   # the away advance is one advance_time
    assert state.social["meets"][mid]["status"] == "no_show"
    notes = {n["kind"]: n["preview"] for n in state.social["notifications"]}
    assert "now" not in notes["meet_start"].split() and notes["meet_start"].startswith("Coffee at")
    assert notes["meet_missed"].startswith("You missed coffee at The Copper Kettle with ")


def test_a_recap_whose_meet_is_gone_is_withdrawn(receipts_active, monkeypatch) -> None:
    """M5: a recap whose meet row was trimmed is retired, so the person's other messages are voiced."""
    from engine import social
    from engine.session.store import release_turn
    from engine.social import meets, messaging, relationships, voicer
    from tests.social_fixtures import _with

    _free(monkeypatch)
    _no_flake(monkeypatch)
    monkeypatch.setattr(social, "setting", _with(social.setting, meets_kept=0))
    _scene, session = _live_session()
    state = session.engine.state
    pid = _matched_in(session, "matchstick").split(":", 1)[1]
    assert session.lock.acquire(blocking=False)
    try:
        _force_stage(state, pid, "numbers")
        messaging.open_numbers(state, pid)
        _set_person(state, pid, **_at(relationships.gate_spec("meeting")))
        mid = _agreed(state, pid)
        _to(state, state.social["meets"][mid]["start"] + 1 / 60)
        meets.go(state, mid)
        assert mid not in state.social["meets"]                       # trimmed at once (meets_kept 0)
    finally:
        release_turn(session)
    voicer.run_until_quiet(session, lambda m, f: "unused")
    recap = [m for t in state.social["threads"].values() for m in t["messages"] if m["kind"] == "recap"][0]
    assert recap["voiced"] == "withdrawn"


def test_a_ghost_at_the_start_flakes(receipts_state, numbers_pid, monkeypatch) -> None:
    _free(monkeypatch)
    _no_flake(monkeypatch)
    state, pid = receipts_state, numbers_pid
    mid = _agreed(state, pid)
    _set_person(state, pid, ghosted=True)
    _to(state, state.social["meets"][mid]["start"] + 1 / 60)
    assert state.social["meets"][mid]["status"] == "flaked"


def test_a_person_faded_by_the_start_calls_it_off(receipts_state, numbers_pid, monkeypatch) -> None:
    _free(monkeypatch)
    _no_flake(monkeypatch)
    state, pid = receipts_state, numbers_pid
    mid = _agreed(state, pid)
    _force_stage(state, pid, "faded")
    _to(state, state.social["meets"][mid]["start"] + 1 / 60)
    assert state.social["meets"][mid]["status"] == "cancelled"


def test_a_counter_can_land_on_the_next_day(receipts_state, numbers_pid, monkeypatch) -> None:
    from engine.social import behaviour

    state, pid = receipts_state, numbers_pid
    day = state.world_day + 2
    busy_from = (day - 1) * 24.0

    def status_at(person, at: float) -> str:
        return "work" if busy_from <= at < busy_from + 24 else "free"

    monkeypatch.setattr(behaviour, "status_at", status_at)
    made = _act(state, "propose_meet", target=pid, args={"venue": VENUE, "day": 2, "slot": "evening"})
    assert made["result"]["answer"] == "counter" and made["result"]["counter"] == {"day": 3, "slot": "morning"}


@pytest.mark.parametrize("leave", ["end", "unmatch"])
def test_a_person_who_leaves_calls_off_their_plans_free(receipts_state, numbers_pid, monkeypatch, leave) -> None:
    """M7: ended or unmatched, every plan with them is called off at no cost, with an engine line; a due
    meet included, so `go` is refused and no regard moves on someone gone."""
    from engine.game.effects import apply_effect

    _free(monkeypatch)
    _no_flake(monkeypatch)
    state, pid = receipts_state, numbers_pid
    _as(monkeypatch, pid, archetype="steady")
    mid = _agreed(state, pid)
    _to(state, state.social["meets"][mid]["start"] + 1 / 60)
    assert state.social["meets"][mid]["status"] == "due"
    warmth = _warmth(state, pid)
    if leave == "end":
        assert _act(state, "end", target=pid)["success"]
    else:
        assert apply_effect(state, {"type": "social_unmatch", "pid": pid, "by": "them"})["ok"]
    assert state.social["meets"][mid]["status"] == "cancelled"
    assert _warmth(state, pid) == warmth
    lines = [b for t in state.social["threads"].values() for m in t["messages"] if m["from"] == "system"
             for b in m["bubbles"]]
    assert any(b.startswith("Plans with ") and " are off: " in b for b in lines)
    refused = _act(state, "meet", target=mid, args={"do": "go"})
    assert refused["refused"] and refused["result"]["error"] == "That meet-up is over."


# -- the contact card's planner (T29) ------------------------------------------------------------------


def test_the_meet_options_are_the_datas_venues_slots_and_days(receipts_state) -> None:
    """`meet_options`: what a `propose_meet` may name, in the data's order and words -- every venue, every
    slot with its start hour, the days ahead -- and the same whatever the clock says (not time-varying)."""
    from engine.game import clock
    from engine.social import meets, payload

    block = payload.phone_block(receipts_state)["meet_options"]
    assert [v["id"] for v in block["venues"]] == list(meets.venue_ids())
    assert all(v["label"] and v["place"] == meets.place_line(v["id"]) and v["neighbourhood"] for v in block["venues"])
    assert block["slots"] == [{"id": k, "start": v[0]} for k, v in meets.slots().items()]
    assert block["days"] == list(meets.days_ahead()) == [1, 7]
    clock.advance_time(receipts_state, 50.0)
    assert payload.phone_block(receipts_state)["meet_options"] == block
    assert "meet_options" not in payload.TIME_VARYING_SECTIONS
