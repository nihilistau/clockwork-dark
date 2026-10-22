"""
Plans with no set time (v0.23.0 T12; spec §9, §13.4's `plan_claimed`).

A plan is a time of day in words, a place and a person: it has no slot. `now` and `tonight` plans are judged on
arrival (kept, or stood up), flake at make, and close quietly if nobody goes; a `soon` plan lapses after episodes,
never days. Every draw a test depends on is forced (pre-flight F16): willingness to meet, their time, the flake.
"""

from __future__ import annotations

import json

import pytest

from tests.social_fixtures import (  # noqa: F401
    _act, _force_stage, _live_session, _matched_in, _open_episode, _phone, _replies_forced, _set_person,
    matched, receipts_active, receipts_state, there_already,
)
from tests.social_world_stub import StubNarrator


def _willing_meet(monkeypatch, *, flake: bool = False):
    """Every draw `plans.make` reads is forced (pre-flight F16): willingness to meet, availability now, and no
    boundary in sight, so `now`/`tonight` never pass or fail by the seed's schedule; and the flake."""
    from engine.social import convo, growth, plans
    from engine.social.convo import Availability

    real = growth.willing
    monkeypatch.setattr(growth, "willing", lambda s, p, c: (True, "") if c == "meet" else real(s, p, c))
    monkeypatch.setattr(convo, "available", lambda s, p, at: Availability(True))
    monkeypatch.setattr(convo, "boundary_minutes", lambda s, p, at: None)
    monkeypatch.setattr(plans, "_flake_drawn", lambda s, p: flake)
    monkeypatch.setattr(plans, "_tonight_span", lambda s, p, at: (at, at + 3.0))


def _numbers(state, thread: str) -> str:
    """The thread's person taken to `numbers` with their messengers open: the pid."""
    from engine.social import messaging

    pid = thread.split(":", 1)[1]
    _force_stage(state, pid, "numbers")
    messaging.open_numbers(state, pid)
    return pid


def test_a_plan_has_no_slot(receipts_state, matched, monkeypatch) -> None:
    from engine.social import plans

    _willing_meet(monkeypatch)
    pid = matched("matchstick").split(":")[1]
    row = plans.make(receipts_state, pid, kind="drinks", when="soon", venue="the_anchor")
    assert row["id"].startswith("pl") and "slot" not in row and "day" not in row
    assert receipts_state.social["plans"][row["id"]] == row
    assert row["status"] == "open" and row["by"] == "player" and row["venue"] == "the_anchor"


def test_arrival_opens_the_scene_and_records_no_stub(receipts_active, monkeypatch) -> None:
    """T12's stub flipped by T13 (spec §24's table; tests/test_social_scene.py::test_a_now_plan_opens_a_scene):
    arrival opens the scene and records the plan `met`; no stub recap is written, and the stage moves only at
    the scene's end."""
    from engine import social
    from engine.social import memory, plans, world

    scene, session = _live_session(llm_fn=StubNarrator())     # F2: the stub from the session's build
    state = session.engine.state
    pid = _matched_in(session, "matchstick").split(":")[1]
    _willing_meet(monkeypatch)
    monkeypatch.setattr(plans, "_arrival", there_already)               # T23C: they are there when it is made
    _force_stage(state, pid, "numbers")
    row = plans.make(state, pid, kind="drinks", when="now", venue="the_anchor")
    state.location_id = "merrow_street"
    arrived = world.go(state, "the_anchor")
    assert arrived["met"] == row["id"] and arrived["scene"] == pid
    assert social.scene_open(state) and state.social["scene"]["plan_id"] == row["id"]
    assert state.social["people"][pid]["stage"] == "numbers"
    assert not any(str(e.get("recap") or "").startswith("You met") for e in memory.person(state, pid).get("episodes") or [])
    assert [p["status"] for p in state.social["plans"].values()] == ["met"]


def test_stood_up_after_patience(receipts_state, matched, monkeypatch) -> None:
    from engine.game import clock
    from engine.social import plans, world

    _willing_meet(monkeypatch)
    pid = matched("matchstick").split(":")[1]
    row = plans.make(receipts_state, pid, kind="coffee", when="now", venue="copper_kettle")
    before = receipts_state.social["people"][pid]["warmth"]
    clock.advance_time(receipts_state, 3)
    receipts_state.location_id = "merrow_street"
    result = world.go(receipts_state, "copper_kettle")
    assert result.get("stood_up") == row["id"]
    assert receipts_state.social["plans"][row["id"]]["status"] == "stood_up"
    assert receipts_state.social["people"][pid]["warmth"] < before                     # plans.yaml `stood_up`
    assert any((e.get("decision") or {}).get("situation") == "stood_up" and e["pid"] == pid
               for e in receipts_state.social["queue"])                                # and they say so


def test_a_flake_shows_as_their_message(receipts_state, matched, monkeypatch) -> None:
    from engine.game import clock
    from engine.social import plans

    _willing_meet(monkeypatch, flake=True)
    thread = matched("matchstick")
    pid = thread.split(":")[1]
    row = plans.make(receipts_state, pid, kind="drinks", when="tonight", venue="the_anchor")
    clock.advance_time(receipts_state, 0.1)
    assert receipts_state.social["plans"][row["id"]]["status"] == "cancelled"
    assert any((m.get("decision") or {}).get("situation") == "flake"
               and (m["decision"]["plan_id"] == row["id"])
               for t in receipts_state.social["threads"].values() for m in t["messages"])


def test_no_flake_no_message(receipts_state, matched, monkeypatch) -> None:
    from engine.game import clock
    from engine.social import plans

    _willing_meet(monkeypatch, flake=False)
    pid = matched("matchstick").split(":")[1]
    row = plans.make(receipts_state, pid, kind="drinks", when="tonight", venue="the_anchor")
    clock.advance_time(receipts_state, 0.1)
    assert receipts_state.social["plans"][row["id"]]["status"] == "open"
    assert not any((m.get("decision") or {}).get("situation") == "flake"
                   for t in receipts_state.social["threads"].values() for m in t["messages"])


def test_a_soon_plan_lapses_after_episodes_not_days(receipts_state, matched, monkeypatch) -> None:
    from engine.game import clock
    from engine.game.effects import apply_effect
    from engine.social import plans

    _willing_meet(monkeypatch)
    thread = matched("matchstick")
    pid = thread.split(":")[1]
    row = plans.make(receipts_state, pid, kind="walk", when="soon", venue="westcliff_path")
    clock.advance_time(receipts_state, 24 * 40)                     # forty days alone change nothing
    assert receipts_state.social["plans"][row["id"]]["status"] == "open"
    for i in range(6):
        assert receipts_state.social["plans"][row["id"]]["status"] == "open", i
        _open_episode(receipts_state, pid, thread)
        apply_effect(receipts_state, {"type": "social_episode", "op": "close", "pid": pid,
                                      "at": receipts_state.world_clock_hours, "end": "lapsed"})
    assert receipts_state.social["plans"][row["id"]]["status"] == "lapsed"


def test_plan_claimed_replaces_slot_claims(receipts_active) -> None:
    """§24's stub table: T7 kept meeting_claimed's slot rows; T12 swaps them for plan_claimed in one change.
    Pre-flight F27: `meet_slot_claims` never existed, so the slot rows are asserted gone where they ARE:
    `meet_claims`' `today`/`tomorrow` rows, and the `meeting_claimed` check that read them."""
    from engine import social
    from engine.social import agreement

    assert "plan_claimed" in agreement.CHECKS and "plan_claimed" in agreement.STATE_CHECKS
    assert "meeting_claimed" not in agreement.CHECKS and "meeting_claimed" not in agreement.STATE_CHECKS
    claims = social.data("relationships").get("meet_claims") or {}
    assert not {"today", "tomorrow"} & set(claims), sorted(claims)
    assert agreement._phrases("meet_denials")                 # v0.22's denials stay, read by plan_claimed


def test_plan_claimed_reads_the_open_plans_of_the_live_view(receipts_state, matched, monkeypatch) -> None:
    from engine.social import agreement, plans
    from engine.social.kinds import Decision

    _willing_meet(monkeypatch)
    pid = matched("matchstick").split(":")[1]
    reply = {"bubbles": ["see you tonight!"], "shared": [], "learned": []}
    decision = Decision(situation="reply")
    view = agreement.view_from_state(receipts_state, pid)
    assert view.plans == () and [f.check for f in agreement.check(reply, decision, view)] == ["plan_claimed"]
    row = plans.make(receipts_state, pid, kind="drinks", when="tonight", venue="the_anchor")
    view = agreement.view_from_state(receipts_state, pid)
    assert [p["id"] for p in view.plans] == [row["id"]] and agreement.check(reply, decision, view) == []
    receipts_state.social["plans"][row["id"]]["status"] = "cancelled"          # called off: no longer a plan
    view = agreement.view_from_state(receipts_state, pid)
    assert [f.check for f in agreement.check(reply, decision, view)] == ["plan_claimed"]


def test_free_now_needs_their_time_free(receipts_state, matched, monkeypatch) -> None:
    """`now` needs them available with `now_min_hours` (2 h) free: a boundary 30 minutes off declines the ask with
    `why: not_tonight`; the ask itself is answered at their read (`plans.answer_ask`)."""
    from engine.social import convo, plans, relationships

    _willing_meet(monkeypatch)
    thread = matched("matchstick")
    pid = _numbers(receipts_state, thread)
    monkeypatch.setattr(convo, "boundary_minutes", lambda s, p, at: 30.0)
    asked = relationships.ask(receipts_state, thread, "meet", {"kind": "coffee", "when": "now"})
    assert asked["ok"], asked
    request = receipts_state.social["requests"][asked["request_id"]]
    assert request["status"] == "no" and request["why"] == "not_tonight"       # decided at their read, in the ask
    assert not receipts_state.social["plans"]
    monkeypatch.setattr(convo, "boundary_minutes", lambda s, p, at: 120.0)       # two hours: exactly enough
    again = plans.ask_fields({"kind": "coffee", "when": "now"})
    assert again == {"kind": "coffee", "venue": "", "when": "now"}
    assert plans.make(receipts_state, pid, **again) is not None


def test_tonight_needs_their_evening(receipts_state, matched, monkeypatch) -> None:
    from engine.social import plans

    _willing_meet(monkeypatch)
    pid = matched("matchstick").split(":")[1]
    monkeypatch.setattr(plans, "_tonight_span", lambda s, p, at: None)
    assert plans.make(receipts_state, pid, kind="drinks", when="tonight") is None
    assert plans.make(receipts_state, pid, kind="drinks", when="soon") is not None   # soon needs willingness alone


def test_a_person_who_is_not_willing_makes_no_plan(receipts_state, matched) -> None:
    """The `meet` commitment (growth.yaml `willing.meet`): a fresh match is not willing, and says why."""
    from engine.social import plans

    pid = matched("matchstick").split(":")[1]
    assert plans.make(receipts_state, pid, kind="coffee", when="soon") is None


def test_the_ask_is_answered_at_their_read_and_makes_the_plan(receipts_state, matched, monkeypatch) -> None:
    """The whole way: `ask` sends the request, their read (it lands at the send's minute here) decides it through
    `messaging.answer_ask`, and a yes is a plan."""
    from engine.social import places, relationships

    _willing_meet(monkeypatch)
    thread = matched("matchstick")
    pid = _numbers(receipts_state, thread)
    asked = relationships.ask(receipts_state, thread, "meet", {"kind": "film", "when": "soon"})
    assert asked["ok"], asked
    request = receipts_state.social["requests"][asked["request_id"]]
    assert request["status"] == "yes" and "why" not in request
    (plan,) = receipts_state.social["plans"].values()
    assert (plan["kind"], plan["when"], plan["by"], plan["status"]) == ("film", "soon", "player", "open")
    assert places.venue(plan["venue"])["kind"] == "film"                    # the engine picked a film venue
    assert receipts_state.social["people"][pid]["stage"] == "numbers"      # the stage moves on arrival, not on yes
    assert any(m["from"] == "system" and "is in:" in m["bubbles"][0]
               for m in receipts_state.social["threads"][thread]["messages"])


def test_an_ask_answered_no_says_why_and_makes_no_plan(receipts_state, matched, monkeypatch) -> None:
    from engine.social import growth, relationships

    _willing_meet(monkeypatch)
    real = growth.willing
    monkeypatch.setattr(growth, "willing", lambda s, p, c: (False, "not_yet") if c == "meet" else real(s, p, c))
    thread = matched("matchstick")
    _numbers(receipts_state, thread)
    asked = relationships.ask(receipts_state, thread, "meet", {"when": "soon"})
    request = receipts_state.social["requests"][asked["request_id"]]
    assert (request["status"], request["why"]) == ("no", "not_yet") and not receipts_state.social["plans"]


def test_running_late_extends_patience_once(receipts_state, matched, monkeypatch) -> None:
    from engine.game import clock
    from engine.game.effects import apply_effect
    from engine.social import plans

    _willing_meet(monkeypatch)
    pid = matched("matchstick").split(":")[1]
    row = plans.make(receipts_state, pid, kind="coffee", when="now", venue="copper_kettle")
    assert row["patience_hours"] == 1.5
    late = apply_effect(receipts_state, {"type": "social_plan", "op": "late", "plan_id": row["id"]})
    assert late["ok"] and receipts_state.social["plans"][row["id"]]["patience_hours"] == 2.0
    again = apply_effect(receipts_state, {"type": "social_plan", "op": "late", "plan_id": row["id"]})
    assert not again["ok"] and receipts_state.social["plans"][row["id"]]["patience_hours"] == 2.0
    clock.advance_time(receipts_state, 1.8)                    # past 1.5, inside 2.0: still kept on arrival
    receipts_state.location_id = "merrow_street"
    from engine.social import world

    assert world.go(receipts_state, "copper_kettle").get("met") == row["id"]


def test_the_players_words_about_being_late_extend_it(receipts_state, matched, monkeypatch) -> None:
    from engine.social import plans

    _willing_meet(monkeypatch)
    thread = matched("matchstick")
    pid = thread.split(":")[1]
    row = plans.make(receipts_state, pid, kind="coffee", when="now", venue="copper_kettle")
    assert not plans.on_player_text(receipts_state, pid, "see you soon")
    assert plans.on_player_text(receipts_state, pid, "sorry, running late!")
    assert receipts_state.social["plans"][row["id"]]["patience_hours"] == 2.0
    assert not plans.on_player_text(receipts_state, pid, "still running late")          # once


def test_a_plan_nobody_went_to_closes_quietly(receipts_state, matched, monkeypatch) -> None:
    from engine.game import clock
    from engine.social import plans

    _willing_meet(monkeypatch)
    pid = matched("matchstick").split(":")[1]
    row = plans.make(receipts_state, pid, kind="coffee", when="tonight", venue="copper_kettle")
    clock.advance_time(receipts_state, 4.0 + 0.5 + 11.0)
    assert receipts_state.social["plans"][row["id"]]["status"] == "open"
    clock.advance_time(receipts_state, 2.0)                    # past patience + grace + `lapse_after_hours`
    assert receipts_state.social["plans"][row["id"]]["status"] == "lapsed"
    assert plans.open_for(receipts_state, pid) == []


def test_the_meet_and_propose_meet_verbs_are_gone(receipts_state, matched) -> None:
    from engine.social import intents, messaging

    thread = matched("matchstick")
    _numbers(receipts_state, thread)
    actions = {verb.action for verb in intents.legal_phone_intents(receipts_state)}
    assert "meet" not in actions and "propose_meet" not in actions
    assert intents.row("meet") is None and intents.row("propose_meet") is None
    assert "meet" in messaging.ASKS                                   # the plan is asked for with `ask`


def test_the_plans_payload_carries_words_not_times(receipts_state, matched, monkeypatch) -> None:
    from engine.social import payload, plans

    _willing_meet(monkeypatch)
    pid = matched("matchstick").split(":")[1]
    row = plans.make(receipts_state, pid, kind="walk", when="soon", venue="westcliff_path")
    receipts_state.social["plans"][row["id"]]["made_at"] = 4321.987654
    block = payload.phone_block(receipts_state)
    text = json.dumps(block)
    assert "4321" not in text and "made_at" not in text and "patience_hours" not in text
    (shown,) = block["plans"]
    assert shown["words"] == plans.words("walk", "westcliff_path", "soon") and shown["words"].endswith(", soon"), shown
    assert {"id", "pid", "name", "kind", "venue", "venue_label", "place", "when", "words", "by"} == set(shown)
    assert "calendar" not in block                                    # the slot grid is gone (spec §9.3)


def test_the_meet_options_are_the_datas_venues_kinds_and_whens(receipts_state) -> None:
    """`meet_options`: what an `ask {what: meet}` may name, in the data's order and words, the same whatever
    the clock says (not time-varying)."""
    from engine.game import clock
    from engine.social import payload, places, plans

    block = payload.phone_block(receipts_state)["meet_options"]
    assert [v["id"] for v in block["venues"]] == list(places.venue_ids())
    assert all(v["label"] and v["place"] == places.place_line(v["id"]) and v["neighbourhood"] for v in block["venues"])
    assert block["kinds"] == list(plans.PLAN_KINDS) and block["whens"] == ["now", "tonight", "soon"]
    assert "slots" not in block and "days" not in block
    clock.advance_time(receipts_state, 50.0)
    assert payload.phone_block(receipts_state)["meet_options"] == block
    assert "meet_options" not in payload.TIME_VARYING_SECTIONS


def test_a_home_plan_meets_at_a_home_and_names_no_venue(receipts_state, matched, monkeypatch) -> None:
    from engine.social import places, plans

    _willing_meet(monkeypatch)
    pid = matched("matchstick").split(":")[1]
    row = plans.make(receipts_state, pid, kind="their_place", when="soon", venue="the_anchor")
    assert row["venue"] == "" and plans.place_of(receipts_state, row) == places.home_of(receipts_state, pid)
    assert places.is_home(plans.place_of(receipts_state, row))
    receipts_state.social["plans"][row["id"]]["status"] = "cancelled"
    yours = plans.make(receipts_state, pid, kind="your_place", when="soon")
    assert yours["venue"] == "" and plans.place_of(receipts_state, yours) == "apt_lounge"


def test_a_plan_at_a_home_is_a_go_target_and_arriving_there_meets(receipts_active, monkeypatch) -> None:
    from engine.social import places, plans, world

    scene, session = _live_session(llm_fn=StubNarrator())
    state = session.engine.state
    pid = _matched_in(session, "matchstick").split(":")[1]
    _willing_meet(monkeypatch)
    _force_stage(state, pid, "meeting")
    home = places.home_of(state, pid)
    assert home not in dict(world.go_targets(state))                       # a home is a target only through a plan
    row = plans.make(state, pid, kind="their_place", when="now")
    assert home in dict(world.go_targets(state))
    assert world.go(state, home).get("met") == row["id"]


def test_one_open_plan_at_a_time(receipts_state, matched, monkeypatch) -> None:
    from engine.social import plans

    _willing_meet(monkeypatch)
    pid = matched("matchstick").split(":")[1]
    assert plans.make(receipts_state, pid, kind="coffee", when="soon")
    assert plans.make(receipts_state, pid, kind="drinks", when="soon") is None


def test_a_plan_with_a_word_the_data_does_not_know_is_a_value_error(receipts_state, matched, monkeypatch) -> None:
    from engine.social import plans

    _willing_meet(monkeypatch)
    pid = matched("matchstick").split(":")[1]
    for kwargs in ({"kind": "tango", "when": "soon"}, {"kind": "coffee", "when": "someday"},
                   {"kind": "coffee", "when": "soon", "venue": "the_moon"}):
        with pytest.raises(ValueError):
            plans.make(receipts_state, pid, **kwargs)


# -- arriving ends a cut-short activity ---------------------------------------------------------------


@pytest.mark.parametrize("past_patience", [False, True])
def test_arriving_on_a_plan_ends_a_cut_short_activity(receipts_state, matched, monkeypatch, past_patience) -> None:
    """T11 saves `resume` (the "Carry on" target); picking a plan up, kept or stood up, clears it as `go` does."""
    from engine.game import clock
    from engine.social import plans

    _willing_meet(monkeypatch)
    monkeypatch.setattr(plans, "_arrival", there_already)               # T23C: they are there when it is made
    pid = matched("matchstick").split(":")[1]
    plans.make(receipts_state, pid, kind="coffee", when="now", venue="copper_kettle")
    clock.advance_time(receipts_state, 3.0 if past_patience else 1.0 / 60.0)   # T23C: their arrival recorded
    receipts_state.social["resume"] = {"activity": "sleep", "until": receipts_state.world_clock_hours + 5.0}
    result = plans.arrive(receipts_state, "copper_kettle")
    assert ("stood_up" in result) is past_patience and ("met" in result) is not past_patience, result
    assert not receipts_state.social.get("resume")


def test_a_quiet_visit_leaves_resume_alone(receipts_state, matched, monkeypatch) -> None:
    from engine.social import plans

    receipts_state.social["resume"] = {"activity": "sleep", "until": 99.0}
    assert plans.arrive(receipts_state, "copper_kettle") == {"quiet": True}
    assert receipts_state.social["resume"]                               # `go` itself clears it; arrive does not


# -- leaving, closing, bounding --------------------------------------------------------------------


@pytest.mark.parametrize("leave", ["unmatch", "end"])
def test_a_person_who_leaves_calls_off_their_plans_free(receipts_state, matched, monkeypatch, leave) -> None:
    from engine.social import plans, relationships

    _willing_meet(monkeypatch)
    thread = matched("matchstick")
    pid = thread.split(":")[1]
    row = plans.make(receipts_state, pid, kind="coffee", when="soon", venue="copper_kettle")
    before = receipts_state.social["people"][pid]["warmth"]
    if leave == "unmatch":
        assert _act(receipts_state, "unmatch", target=pid)["success"]
    else:
        assert relationships.end(receipts_state, pid)["ok"]
    assert receipts_state.social["plans"][row["id"]]["status"] == "cancelled"
    assert receipts_state.social["people"][pid]["warmth"] >= before - 0      # no cost
    assert plans.open_for(receipts_state) == []


def test_closed_plans_are_kept_a_few_a_person_and_open_ones_never_leave(receipts_state, matched, monkeypatch) -> None:
    from engine.game.effects import apply_effect
    from engine.social import plans

    _willing_meet(monkeypatch)
    pid = matched("matchstick").split(":")[1]
    ids = []
    for i in range(6):
        row = plans.make(receipts_state, pid, kind="coffee", when="soon", venue="copper_kettle")
        ids.append(row["id"])
        apply_effect(receipts_state, {"type": "social_plan", "op": "cancel", "plan_id": row["id"]})
    open_row = plans.make(receipts_state, pid, kind="walk", when="soon", venue="westcliff_path")
    assert plans.forget_closed(receipts_state) == 3                      # plans.yaml closed_kept: 3
    assert set(receipts_state.social["plans"]) == set(ids[3:]) | {open_row["id"]}
    assert plans.forget_closed(receipts_state) == 0                      # idempotent
    refused = apply_effect(receipts_state, {"type": "social_plan", "op": "forget", "plan_id": open_row["id"]})
    assert not refused["ok"]                                             # an open plan is never forgotten


def test_the_save_compaction_forgets_closed_plans(receipts_active, monkeypatch) -> None:
    from engine.game.effects import apply_effect
    from engine.session.store import release_turn
    from engine.social import plans, saves

    _scene, session = _live_session()
    state = session.engine.state
    pid = _matched_in(session, "matchstick").split(":")[1]
    _willing_meet(monkeypatch)
    assert session.lock.acquire(blocking=False)
    try:
        for _ in range(5):
            row = plans.make(state, pid, kind="coffee", when="soon", venue="copper_kettle")
            apply_effect(state, {"type": "social_plan", "op": "cancel", "plan_id": row["id"]})
        saves.compact(session)
        assert len(state.social["plans"]) == 3
    finally:
        release_turn(session)


# -- their asks -------------------------------------------------------------------------------------


def test_their_ask_is_a_request_the_player_answers(receipts_state, matched, monkeypatch) -> None:
    from engine.social import plans, relationships
    from tests.social_fixtures import WELL_ALONG

    _willing_meet(monkeypatch)
    thread = matched("matchstick")
    pid = _numbers(receipts_state, thread)
    _set_person(receipts_state, pid, **WELL_ALONG)
    assert plans.PROPOSAL in relationships.legal_proposals(receipts_state, pid)
    made = relationships.apply_proposal(receipts_state, pid, plans.PROPOSAL)
    assert made["ok"], made
    request = receipts_state.social["requests"][made["request_id"]]
    assert (request["from"], request["what"], request["when"]) == ("them", "meet", "tonight")
    assert request["venue"] and request["kind"] and "day" not in request and "slot" not in request
    assert plans.PROPOSAL not in relationships.legal_proposals(receipts_state, pid)       # one ask at a time
    answered = relationships.answer(receipts_state, request["id"], "yes")
    assert answered["ok"] and answered["plan_id"], answered
    plan = receipts_state.social["plans"][answered["plan_id"]]
    assert (plan["by"], plan["when"], plan["venue"]) == ("person", "tonight", request["venue"])


def test_their_ask_that_can_no_longer_be_met_is_refused_and_unlisted(receipts_state, matched, monkeypatch) -> None:
    from engine.social import plans, relationships

    _willing_meet(monkeypatch)
    thread = matched("matchstick")
    pid = _numbers(receipts_state, thread)
    made = plans._their_request(receipts_state, pid, thread, "coffee", "copper_kettle", "soon", None)
    request = made["request"]
    assert any(r["id"] == request["id"] for r in relationships._open_requests(receipts_state))
    plans.make(receipts_state, pid, kind="walk", when="soon", venue="westcliff_path")        # a plan now stands
    assert not any(r["id"] == request["id"] for r in relationships._open_requests(receipts_state))
    refused = relationships.answer(receipts_state, request["id"], "yes")
    assert not refused["ok"] and refused["error"] == "That isn't on the table any more."


def test_their_tonight_ask_lapses_at_its_patience_at_no_cost(receipts_state, matched, monkeypatch) -> None:
    from engine.game import clock
    from engine.social import plans

    _willing_meet(monkeypatch)
    thread = matched("matchstick")
    pid = _numbers(receipts_state, thread)
    warmth = receipts_state.social["people"][pid]["warmth"]
    made = plans._their_request(receipts_state, pid, thread, "coffee", "copper_kettle", "tonight", None)
    rid = made["request"]["id"]
    clock.advance_time(receipts_state, 3.9)
    assert receipts_state.social["requests"][rid]["status"] == "pending"
    clock.advance_time(receipts_state, 0.2)
    assert receipts_state.social["requests"][rid]["status"] == "no"
    assert receipts_state.social["requests"][rid].get("lapsed") is True
    assert receipts_state.social["people"][pid]["warmth"] == warmth


def test_their_invite_is_a_request_and_a_message_once_a_day(receipts_state, matched, monkeypatch) -> None:
    from engine.social import growth, plans

    _willing_meet(monkeypatch)
    thread = matched("matchstick")
    pid = _numbers(receipts_state, thread)
    monkeypatch.setattr(growth, "depth", lambda s, p: 4)
    real = plans._data

    def sure():
        data = dict(real())
        data["invite"] = {**data["invite"], "prob": [1.0] * 5}
        return data

    monkeypatch.setattr(plans, "_data", sure)
    plans._daily_invites(receipts_state)
    (request,) = [r for r in receipts_state.social["requests"].values() if r["what"] == "meet"]
    assert request["from"] == "them" and request["when"] == "tonight" and request["pid"] == pid
    (due,) = [e for e in receipts_state.social["queue"] if (e.get("decision") or {}).get("situation") == "invite"]
    assert due["decision"]["request_id"] == request["id"]
    plans._daily_invites(receipts_state)                                  # one ask waiting: no second
    assert len([r for r in receipts_state.social["requests"].values() if r["what"] == "meet"]) == 1


def test_nobody_invites_who_is_not_willing_or_has_a_plan(receipts_state, matched, monkeypatch) -> None:
    from engine.social import growth, plans

    thread = matched("matchstick")
    _numbers(receipts_state, thread)
    monkeypatch.setattr(growth, "depth", lambda s, p: 4)
    real = plans._data
    monkeypatch.setattr(plans, "_data", lambda: {**real(), "invite": {**real()["invite"], "prob": [1.0] * 5}})
    plans._daily_invites(receipts_state)                                  # a fresh numbers match is not willing yet
    assert not [r for r in receipts_state.social["requests"].values() if r["what"] == "meet"]


# -- the data -----------------------------------------------------------------------------------------


def test_the_plans_data_is_checked(receipts_active) -> None:
    from engine import social
    from engine.social import plans

    data = social.data("plans")
    plans.check_data(data)
    assert data["patience_hours"] == {"now": 1.5, "tonight": 4} and data["soon_patience_episodes"] == 6
    assert data["stood_up"] == {"warmth": -8, "trust": -6, "interest": -6} and data["now_min_hours"] == 2
    for key, bad in (("kinds", ["coffee"]), ("patience_hours", {"now": 1}), ("now_min_hours", 0),
                     ("soon_patience_episodes", 0), ("stood_up", {"warmth": 1.5}),
                     ("flake", {"stage_prob": {"numbers": 0.1}}), ("invite", {"prob": [2], "window": "evening"}),
                     ("invite", {"prob": [0.1], "window": "midnight"}), ("running_late", [""])):
        with pytest.raises(ValueError, match=key):
            plans.check_data({**data, key: bad})
    assert list(data["kinds"]) == list(plans.PLAN_KINDS)


# -- the voice and the checks know -----------------------------------------------------------------------


def test_every_check_has_its_correction(receipts_active) -> None:
    """A failing check is retried with its one-line correction (`voicing.CORRECTIONS`): renaming a check without
    renaming its correction left `plan_claimed` on the generic line (found in T12)."""
    from engine.social import agreement, voicing

    assert set(agreement.CHECKS) <= set(voicing.CORRECTIONS), set(agreement.CHECKS) - set(voicing.CORRECTIONS)


def test_right_now_names_the_plan_for_a_flake_a_stood_up_and_an_invite(receipts_state, matched, monkeypatch) -> None:
    from engine.game.effects import apply_effect
    from engine.social import plans, voicing
    from tests.test_social_voice_v2 import _block, _only_due, _user

    _willing_meet(monkeypatch)
    thread = matched("matchstick")
    pid = _numbers(receipts_state, thread)
    row = plans.make(receipts_state, pid, kind="drinks", when="tonight", venue="the_anchor")
    apply_effect(receipts_state, {"type": "social_plan", "op": "cancel", "plan_id": row["id"]})
    snap = _only_due(receipts_state, thread, situation="flake", plan_id=row["id"])
    now = _block(_user(voicing.messages(snap)), "RIGHT NOW")
    assert f"The plan: {plans.words('drinks', 'the_anchor', 'tonight')}." in now and "Your plans with them" not in now
    open_row = plans.make(receipts_state, pid, kind="walk", when="soon", venue="westcliff_path")
    snap = _only_due(receipts_state, thread, situation="reply")
    assert f"Your plans with them: {plans.words('walk', 'westcliff_path', 'soon')}." in _block(_user(voicing.messages(snap)), "RIGHT NOW")
    receipts_state.social["plans"][open_row["id"]]["status"] = "cancelled"
    made = plans._their_request(receipts_state, pid, thread, "coffee", "copper_kettle", "tonight", None)
    snap = _only_due(receipts_state, thread, situation="invite", request_id=made["request"]["id"])
    now = _block(_user(voicing.messages(snap)), "RIGHT NOW")
    assert f"You are asking them to meet up: {plans.words('coffee', 'copper_kettle', 'tonight')}." in now
    assert "Your answer" not in now


# -- fix round 1 (review of T12) ------------------------------------------------------------------------


def test_their_ask_follows_willingness_not_the_old_stage_gate(receipts_state, matched, monkeypatch) -> None:
    """§9.2, §6.5: a person below the v0.22 `meeting` gate (warmth 70, trust 70) but willing to meet can propose; one
    who is not willing cannot, whatever their warmth."""
    from engine.social import growth, plans, relationships

    thread = matched("matchstick")
    pid = _numbers(receipts_state, thread)
    person = receipts_state.social["people"][pid]
    assert person["warmth"] < 70 or person["trust"] < 70
    real = growth.willing
    monkeypatch.setattr(growth, "willing", lambda s, p, c: (True, "") if c == "meet" else real(s, p, c))
    assert plans.PROPOSAL in relationships.legal_proposals(receipts_state, pid)
    monkeypatch.setattr(growth, "willing", lambda s, p, c: (False, "not_yet") if c == "meet" else real(s, p, c))
    assert plans.PROPOSAL not in relationships.legal_proposals(receipts_state, pid)
    _set_person(receipts_state, pid, warmth=95, trust=95)
    assert plans.PROPOSAL not in relationships.legal_proposals(receipts_state, pid)


@pytest.mark.parametrize("how", ["ended", "gone", "unlisted"])
def test_a_lapse_writes_no_line_into_a_gone_or_ended_persons_thread(receipts_state, matched, monkeypatch, how) -> None:
    from engine.social import matching, plans

    _willing_meet(monkeypatch)
    thread = matched("matchstick")
    pid = _numbers(receipts_state, thread)
    made = plans._their_request(receipts_state, pid, thread, "coffee", "copper_kettle", "tonight", None)
    if how == "ended":
        _force_stage(receipts_state, pid, "ended")
    elif how == "gone":
        monkeypatch.setattr(plans, "_gone", lambda s, p: True)
    else:
        monkeypatch.setattr(matching, "listed", lambda t: False)
    assert plans._lapse_request(receipts_state, made["request"]["id"], 30.0)["lapsed"]
    assert not any("lapsed" in b for m in receipts_state.social["threads"][thread]["messages"]
                   for b in m.get("bubbles") or ())


def test_an_ask_to_a_ghost_stays_unanswered_and_makes_no_plan(receipts_state, matched, monkeypatch) -> None:
    """A ghosted person's read gives no answer (convo's `ghosted` start): the ask waits, no plan, no flake."""
    from engine.game import clock
    from engine.social import relationships

    _willing_meet(monkeypatch, flake=True)
    thread = matched("matchstick")
    pid = _numbers(receipts_state, thread)
    _set_person(receipts_state, pid, ghosted=True)
    asked = relationships.ask(receipts_state, thread, "meet", {"when": "tonight"})
    clock.advance_time(receipts_state, 0.5)
    assert receipts_state.social["requests"][asked["request_id"]]["status"] in ("pending", "later")
    assert not receipts_state.social["plans"]
    assert not any((m.get("decision") or {}).get("situation") == "flake"
                   for t in receipts_state.social["threads"].values() for m in t["messages"])


@pytest.mark.parametrize("text", ["not running late", "I'm not running late", "won't be late", "never late",
                                  "I'm late for work", "im not late", "I was never running late"])
def test_negated_or_other_lateness_does_not_extend_a_plan(receipts_state, matched, monkeypatch, text) -> None:
    from engine.social import plans

    _willing_meet(monkeypatch)
    pid = matched("matchstick").split(":")[1]
    row = plans.make(receipts_state, pid, kind="coffee", when="now", venue="copper_kettle")
    assert not plans.on_player_text(receipts_state, pid, text)
    assert receipts_state.social["plans"][row["id"]]["patience_hours"] == 1.5


def test_a_plan_they_proposed_draws_no_flake_when_accepted(receipts_state, matched, monkeypatch) -> None:
    from engine.game import clock
    from engine.social import plans, relationships

    _willing_meet(monkeypatch, flake=True)
    thread = matched("matchstick")
    pid = _numbers(receipts_state, thread)
    made = plans._their_request(receipts_state, pid, thread, "coffee", "copper_kettle", "tonight", None)
    answered = relationships.answer(receipts_state, made["request"]["id"], "yes")
    assert answered["ok"], answered
    clock.advance_time(receipts_state, 0.1)
    assert receipts_state.social["plans"][answered["plan_id"]]["status"] == "open"
    assert not any((m.get("decision") or {}).get("situation") == "flake"
                   for t in receipts_state.social["threads"].values() for m in t["messages"])


def test_the_players_ask_turns_a_soon_plan_into_a_tonight_plan(receipts_state, matched, monkeypatch) -> None:
    """9.3: either side's ask turns a `soon` plan into `now` / `tonight`: the same plan, not a second."""
    from engine.social import plans, relationships

    _willing_meet(monkeypatch)
    thread = matched("matchstick")
    pid = _numbers(receipts_state, thread)
    plan = plans.make(receipts_state, pid, kind="film", when="soon")
    again = relationships.ask(receipts_state, thread, "meet", {"when": "soon"})
    assert not again["ok"] and "already have plans" in again["error"]       # a second soon is still "you have plans"
    up = relationships.ask(receipts_state, thread, "meet", {"when": "tonight"})
    assert up["ok"], up
    (after,) = receipts_state.social["plans"].values()
    assert after["id"] == plan["id"] and after["when"] == "tonight" and after["status"] == "open"
    assert (after["kind"], after["venue"]) == (plan["kind"], plan["venue"]) and after["patience_hours"] == 4
    assert not relationships.ask(receipts_state, thread, "meet", {"when": "now"})["ok"]   # a tonight plan stands


def test_their_ask_turns_a_soon_plan_into_a_tonight_plan(receipts_state, matched, monkeypatch) -> None:
    from engine.social import plans, relationships

    _willing_meet(monkeypatch)
    thread = matched("matchstick")
    pid = _numbers(receipts_state, thread)
    soon = plans.make(receipts_state, pid, kind="walk", when="soon", venue="westcliff_path")
    assert plans.PROPOSAL in relationships.legal_proposals(receipts_state, pid)      # a soon plan does not block it
    made = relationships.apply_proposal(receipts_state, pid, plans.PROPOSAL)
    assert made["ok"], made
    assert any(r["id"] == made["request_id"] for r in relationships._open_requests(receipts_state))
    answered = relationships.answer(receipts_state, made["request_id"], "yes")
    assert answered["ok"] and answered["plan_id"] == soon["id"], answered
    (row,) = receipts_state.social["plans"].values()
    assert row["when"] == "tonight" and row["by"] == "person" and row["status"] == "open"
