"""Willingness, numbers and per-episode caps (v0.23.0 spec §1.4, §6.4's caps, §6.5, §15; T5).

What each person is willing to do NOW comes from growth.yaml `willing:` (stage, regard floors, play
counts, needs, and depth for `number`/`meet` only). Regard, fallback, ask and media caps are counted
per conversation episode (`convo.cap_key`), never per in-game day. Every draw a test reads is forced.
"""

from __future__ import annotations

import copy

import pytest

from tests.social_fixtures import (  # noqa: F401
    _act, _force_archetype, _force_stage, _open_episode, _replies_forced, _set_person, matched, receipts_active,
    receipts_state,
)


def _pace_one(monkeypatch, state, pid: str) -> None:
    """The person's fixed pace pinned to 1.0 (lesson 1: no loop rides the drawn pace)."""
    from engine.game.effects import apply_effect
    from engine.social import attrs, growth

    monkeypatch.setattr(growth, "_jitter", lambda rng: 1.0)
    apply_effect(state, {"type": "social_person", "pid": pid, "set": {"attrs": {**attrs.of(state, pid), "pace": 1.0}}})


def test_number_needs_everyday_and_warmth_and_says_not_yet(receipts_state, matched) -> None:
    from engine.game.effects import apply_effect
    from engine.social import growth

    pid = matched("matchstick").split(":")[1]
    _set_person(receipts_state, pid, warmth=40, trust=40, episodes_done=1)
    assert growth.willing(receipts_state, pid, "number") == (False, "not_yet")      # depth 0
    apply_effect(receipts_state, {"type": "social_growth", "op": "gain", "pid": pid, "amount": 100})
    assert growth.willing(receipts_state, pid, "number") == (True, "")


def test_the_number_gate_reads_warmth_too(receipts_state, matched) -> None:
    from engine.game.effects import apply_effect
    from engine.social import growth

    pid = matched("matchstick").split(":")[1]
    _set_person(receipts_state, pid, warmth=40, trust=40, episodes_done=1)
    apply_effect(receipts_state, {"type": "social_growth", "op": "gain", "pid": pid, "amount": 100})
    assert growth.depth(receipts_state, pid) == 1
    _set_person(receipts_state, pid, warmth=24)                                    # below willing.number's 25
    assert growth.willing(receipts_state, pid, "number") == (False, "not_yet")


def test_a_declined_number_ask_carries_why_not_yet(receipts_state, matched, monkeypatch) -> None:
    from engine.game import clock

    thread = matched("matchstick")
    pid = thread.split(":")[1]
    _force_stage(receipts_state, pid, "talking")
    with _replies_forced():
        _open_episode(receipts_state, pid, thread)
        _act(receipts_state, "ask", target=thread, args={"what": "number"})
    clock.advance_time(receipts_state, 0.1)
    answer = next(m for m in receipts_state.social["threads"][thread]["messages"]
                  if (m.get("decision") or {}).get("situation") == "answer_request")
    request = receipts_state.social["requests"][answer["decision"]["request_id"]]
    assert request["status"] == "no" and request["why"] == "not_yet"


def test_willing_says_stage_needs_and_household(receipts_state, matched, monkeypatch) -> None:
    from engine.social import growth

    pid = matched("matchstick").split(":")[1]
    _set_person(receipts_state, pid, warmth=90, trust=90, scenes_done=20, episodes_done=20)
    assert growth.willing(receipts_state, pid, "exclusive") == (False, "stage")       # not dating
    _force_stage(receipts_state, pid, "dating")
    receipts_state.social.setdefault("player", {})["looking_for"] = "short_term"
    assert growth.willing(receipts_state, pid, "exclusive") == (False, "needs")
    _force_stage(receipts_state, pid, "exclusive")
    _set_person(receipts_state, pid, exclusive_since=receipts_state.world_clock_hours - 24.0 * 15)
    assert growth.willing(receipts_state, pid, "move_in") == (True, "")
    receipts_state.social["household"] = "someone"
    assert growth.willing(receipts_state, pid, "move_in") == (False, "household")


def test_move_in_counts_days_since_exclusive(receipts_state, matched) -> None:
    from engine.social import growth

    pid = matched("matchstick").split(":")[1]
    _set_person(receipts_state, pid, warmth=90, trust=90, scenes_done=20)
    _force_stage(receipts_state, pid, "exclusive")
    since = receipts_state.social["people"][pid]["exclusive_since"]               # written by social_stage
    assert since == pytest.approx(receipts_state.world_clock_hours)
    assert growth.willing(receipts_state, pid, "move_in") == (False, "not_yet")


def test_an_undeclared_commitment_is_an_error(receipts_state, matched, monkeypatch) -> None:
    from engine import social
    from engine.social import growth

    pid = matched("matchstick").split(":")[1]
    data = copy.deepcopy(social.data("growth"))
    del data["willing"]["meet_family"]
    monkeypatch.setattr(growth, "_data", lambda: data)
    with pytest.raises(ValueError, match="willing.meet_family"):
        growth.willing(receipts_state, pid, "meet_family")


def test_no_life_logistics_commitment_reads_depth(receipts_active) -> None:
    from engine import social
    from engine.social import growth

    for name, gate in social.data("growth")["willing"].items():
        if name not in growth.DEPTH_COMMITMENTS:
            assert "depth" not in gate, name


@pytest.mark.parametrize("change, match", [
    (lambda w: w["stay_over"].update(depth=1), r"willing\.stay_over\.depth"),
    (lambda w: w["number"].update(stage_min="eloped"), r"willing\.number\.stage_min"),
    (lambda w: w["propose"].update(stages=["eloped"]), r"willing\.propose\.stages"),
    (lambda w: w["meet"].update(days_since_exclusive=3), r"willing\.meet\.days_since_exclusive"),
    (lambda w: w["number"].update(hours=3), r"willing\.number"),
])
def test_a_bad_willing_row_is_a_load_error(receipts_active, change, match) -> None:
    from engine import social
    from engine.social import growth

    data = copy.deepcopy(social.data("growth"))
    change(data["willing"])
    with pytest.raises(ValueError, match=match):
        growth.check_data(data, social.data("topics"), social.data("layers"))


@pytest.mark.parametrize("gate, match", [
    ({"days": 3}, r"stages\.numbers\.gate\.days"),
    ({"stage_days": 28}, r"stages\.numbers\.gate\.stage_days"),
    ({"willing": "elope"}, r"stages\.numbers\.gate\.willing"),
])
def test_a_stage_gate_reads_willing_never_days(receipts_active, gate, match) -> None:
    from engine import social
    from engine.social import relationships

    data = copy.deepcopy(social.data("relationships"))
    data["stages"]["numbers"]["gate"] = gate
    with pytest.raises(ValueError, match=match):
        relationships.check_data(data)


def test_regard_is_capped_per_episode_not_per_day(receipts_state, matched, monkeypatch) -> None:
    """Pre-flight F16: the archetype is pinned to `steady` (warmth_mult 1.0, no warmth cap band), so the
    "+4" below is the proposal itself, never the seed's archetype."""
    from engine.game.effects import apply_effect
    from engine.social import relationships

    thread = matched("matchstick")
    pid = thread.split(":")[1]
    _force_archetype(monkeypatch, receipts_state, pid, "steady")
    _open_episode(receipts_state, pid, thread)
    start = receipts_state.social["people"][pid]["warmth"]
    for _ in range(10):
        relationships.apply_regard(receipts_state, pid, {"warmth": 4, "trust": 2}, day=receipts_state.world_day)
    cap = relationships._block("regard")["per_episode_gain"]["warmth"]
    assert receipts_state.social["people"][pid]["warmth"] - start == cap
    apply_effect(receipts_state, {"type": "social_episode", "op": "close", "pid": pid,
                                  "at": receipts_state.world_clock_hours, "end": "lapsed"})
    _open_episode(receipts_state, pid, thread)                    # the same in-game day, a new episode
    relationships.apply_regard(receipts_state, pid, {"warmth": 4, "trust": 2}, day=receipts_state.world_day)
    assert receipts_state.social["people"][pid]["warmth"] - start == cap + 4


def test_the_between_episode_cap_resets_when_an_episode_closes(receipts_state, matched, monkeypatch) -> None:
    """Pre-flight F36: outside any episode the cap is keyed `after:<last closed episode id>`, so closing
    another episode gives a fresh between-episode allowance."""
    from engine.game.effects import apply_effect
    from engine.social import convo

    thread = matched("matchstick")
    pid = thread.split(":")[1]
    _force_archetype(monkeypatch, receipts_state, pid, "steady")
    assert convo.cap_key(receipts_state, pid) == "after:"
    _open_episode(receipts_state, pid, thread)
    first = receipts_state.social["people"][pid]["episode"]["id"]
    assert convo.cap_key(receipts_state, pid) == first
    apply_effect(receipts_state, {"type": "social_episode", "op": "close", "pid": pid,
                                  "at": receipts_state.world_clock_hours, "end": "lapsed"})
    assert convo.cap_key(receipts_state, pid) == f"after:{first}"
    assert receipts_state.social["people"][pid]["last_episode"] == first


def test_reaching_everyday_queues_their_number_offer(receipts_state, matched, monkeypatch) -> None:
    from engine.game import clock
    from engine.game.effects import apply_effect
    from engine.social import convo

    thread = matched("matchstick")
    pid = thread.split(":")[1]
    monkeypatch.setattr(convo, "_offer_drawn", lambda state, pid_: True)
    _set_person(receipts_state, pid, warmth=40, trust=30, episodes_done=1)
    _open_episode(receipts_state, pid, thread)
    apply_effect(receipts_state, {"type": "social_growth", "op": "gain", "pid": pid, "amount": 100})
    clock.advance_time(receipts_state, 0.05)
    assert any((m.get("decision") or {}).get("situation") == "offer_number"
               for m in receipts_state.social["threads"][thread]["messages"])
    offered = [r for r in receipts_state.social["requests"].values() if r["from"] == "them" and r["what"] == "number"]
    assert len(offered) == 1 and offered[0]["status"] == "pending"


def test_their_number_offer_answered_yes_swaps_numbers(receipts_state, matched, monkeypatch) -> None:
    """§15.2: the player's yes goes through v0.22's number path (the stage, the messenger threads)."""
    from engine.game import clock
    from engine.game.effects import apply_effect
    from engine.social import convo, relationships

    thread = matched("matchstick")
    pid = thread.split(":")[1]
    monkeypatch.setattr(convo, "_offer_drawn", lambda state, pid_: True)
    _set_person(receipts_state, pid, warmth=40, trust=30, episodes_done=1)
    _open_episode(receipts_state, pid, thread)
    apply_effect(receipts_state, {"type": "social_growth", "op": "gain", "pid": pid, "amount": 100})
    clock.advance_time(receipts_state, 0.05)
    rid = next(r["id"] for r in receipts_state.social["requests"].values() if r["from"] == "them")
    _force_stage(receipts_state, pid, "talking")
    assert relationships.answer(receipts_state, rid, "yes")["ok"]
    assert receipts_state.social["people"][pid]["stage"] == "numbers"
    assert any(t.startswith("texts:") or t.startswith("natter:") for t in receipts_state.social["threads"])


def test_a_declined_offer_draw_offers_nothing(receipts_state, matched, monkeypatch) -> None:
    from engine.game import clock
    from engine.game.effects import apply_effect
    from engine.social import convo

    thread = matched("matchstick")
    pid = thread.split(":")[1]
    monkeypatch.setattr(convo, "_offer_drawn", lambda state, pid_: False)
    _set_person(receipts_state, pid, warmth=40, trust=30, episodes_done=1)
    _open_episode(receipts_state, pid, thread)
    apply_effect(receipts_state, {"type": "social_growth", "op": "gain", "pid": pid, "amount": 100})
    clock.advance_time(receipts_state, 0.05)
    assert not any((m.get("decision") or {}).get("situation") == "offer_number"
                   for m in receipts_state.social["threads"][thread]["messages"])
    assert not [r for r in receipts_state.social["requests"].values() if r["from"] == "them"]


def test_with_no_conversation_the_offer_waits_for_their_next_available_minute(receipts_state, matched,
                                                                              monkeypatch) -> None:
    from engine.game.effects import apply_effect
    from engine.social import convo

    thread = matched("matchstick")
    pid = thread.split(":")[1]
    later = receipts_state.world_clock_hours + 5.0
    monkeypatch.setattr(convo, "next_available", lambda state, pid_, at: later)
    _set_person(receipts_state, pid, warmth=40, trust=30, episodes_done=1)
    apply_effect(receipts_state, {"type": "social_growth", "op": "gain", "pid": pid, "amount": 100})
    queued = [e for e in receipts_state.social["queue"] if e["kind"] == "offer_number"]
    assert [e["at"] for e in queued] == [later]


def test_the_attentive_depth_floor_is_reachable_in_episodes_not_days(receipts_state, matched, monkeypatch) -> None:
    """Three conversations of eight exchanges each, an hour apart, played through the conversation
    (`convo.decide`: each decision is an exchange and its openness gain, by the mode it decides): depth 1
    inside a day, and the number gate holds at the end (spec §1.4, §15.1). Pace 1.0, `steady` (warmth_mult
    1.0), availability, the promise and the offer draws are forced. Deep mode needs depth 2 (spec §4.5), so
    these exchanges run quick, then chatting."""
    from engine.game import clock
    from engine.game.effects import apply_effect
    from engine.social import convo, growth, relationships

    thread = matched("matchstick")
    pid = thread.split(":")[1]
    _force_archetype(monkeypatch, receipts_state, pid, "steady")
    _pace_one(monkeypatch, receipts_state, pid)
    monkeypatch.setattr(convo, "_offer_drawn", lambda state, pid_: False)
    monkeypatch.setattr(convo, "_promise_drawn", lambda state, pid_: False)
    day = receipts_state.world_day
    modes: list[str] = []
    with _replies_forced():
        for _ in range(3):
            _open_episode(receipts_state, pid, thread)
            for _ in range(8):
                relationships.apply_regard(receipts_state, pid, {"warmth": 4, "trust": 2},
                                           day=receipts_state.world_day)
                modes.append(convo.decide(receipts_state, pid, thread, receipts_state.world_clock_hours).mode)
            apply_effect(receipts_state, {"type": "social_episode", "op": "close", "pid": pid,
                                          "at": receipts_state.world_clock_hours, "end": "lapsed"})
            clock.advance_time(receipts_state, 1.0)
    assert "chatting" in modes
    assert growth.depth(receipts_state, pid) == 1
    assert receipts_state.world_day - day <= 1
    assert growth.willing(receipts_state, pid, "number") == (True, "")


def test_the_ask_that_opens_a_conversation_counts_in_that_conversation(receipts_state, matched) -> None:
    """Review I2: an ask made with no conversation going is counted against `after:<last>`; the read it
    brings opens the episode, and the ask is carried into it (`convo._open`), so the cap holds there."""
    from engine.game import clock
    from engine.social import convo, relationships

    thread = matched("matchstick")
    pid = thread.split(":")[1]
    _force_stage(receipts_state, pid, "talking")
    assert convo.episode(receipts_state, pid) is None
    with _replies_forced():
        _act(receipts_state, "ask", target=thread, args={"what": "number"})
        clock.advance_time(receipts_state, 0.1)
    assert convo.episode(receipts_state, pid) is not None
    assert relationships.asks_this_episode(receipts_state, pid, "number") == 1


def test_a_yes_to_their_offer_at_matched_goes_through_talking(receipts_state, matched, monkeypatch) -> None:
    """Review minor: their offer may come before `talking` (depth 1 needs no stage), but a yes moves the
    stage only by the normal transitions -- talking's own gate first, then numbers' `from` -- and is refused
    when talking's gate does not hold."""
    from engine.game import clock
    from engine.game.effects import apply_effect
    from engine.social import convo, relationships

    thread = matched("matchstick")
    pid = thread.split(":")[1]
    monkeypatch.setattr(convo, "_offer_drawn", lambda state, pid_: True)
    _set_person(receipts_state, pid, warmth=40, trust=30, episodes_done=1)
    _open_episode(receipts_state, pid, thread)
    apply_effect(receipts_state, {"type": "social_growth", "op": "gain", "pid": pid, "amount": 100})
    clock.advance_time(receipts_state, 0.05)
    rid = next(r["id"] for r in receipts_state.social["requests"].values() if r["from"] == "them")
    _set_person(receipts_state, pid, familiarity={"exchanges": 0, "contact_days": 1})
    assert not relationships.answer(receipts_state, rid, "yes")["ok"]                # talking's gate: no
    assert receipts_state.social["people"][pid]["stage"] == "matched"
    _set_person(receipts_state, pid, familiarity={"exchanges": 4, "contact_days": 1})
    assert relationships.answer(receipts_state, rid, "yes")["ok"]
    kinds = [h["kind"] for h in receipts_state.social["people"][pid]["memory"]["history"]]
    assert kinds.index("talking") < kinds.index("numbers")                         # both, in order


def test_the_number_hint_is_the_asks_own_call(receipts_state, matched) -> None:
    """Review minor: `hints.number.ok` is `can_reach` -- the Ask menu's rule -- so it is False at `matched`
    (the menu offers no number) and once the number is swapped, whatever `willing.number` says."""
    from engine.game.effects import apply_effect
    from engine.social import payload

    pid = matched("matchstick").split(":")[1]
    _set_person(receipts_state, pid, warmth=40, trust=30, episodes_done=1)
    apply_effect(receipts_state, {"type": "social_growth", "op": "gain", "pid": pid, "amount": 100})
    assert payload.phone_block(receipts_state)["hints"][pid]["number"] == {"ok": False, "why": "Not the moment"}
    _force_stage(receipts_state, pid, "talking")
    assert payload.phone_block(receipts_state)["hints"][pid]["number"] == {"ok": True, "why": ""}
    _force_stage(receipts_state, pid, "numbers")
    assert payload.phone_block(receipts_state)["hints"][pid]["number"] == {"ok": False, "why": ""}


def test_hints_carry_booleans_and_words_never_numbers(receipts_state, matched) -> None:
    """Lesson 7: sentinels planted, then absent from the JSON payload."""
    import json

    from engine.game.effects import apply_effect
    from engine.social import payload

    pid = matched("matchstick").split(":")[1]
    _set_person(receipts_state, pid, warmth=61.987654, trust=48.123457)
    apply_effect(receipts_state, {"type": "social_growth", "op": "gain", "pid": pid, "amount": 73.123457})
    block = json.dumps(payload.phone_block(receipts_state), default=str)
    for sentinel in ("61.987654", "48.123457", "73.123457"):
        assert sentinel not in block
    hint = payload.phone_block(receipts_state)["hints"][pid]
    assert hint["closer_soon"] is True and isinstance(hint["number"]["ok"], bool)
    assert set(hint) == {"closer_soon", "available_words", "number"}
    assert hint["number"] == {"ok": False, "why": "Not the moment"}                 # at matched: not offered yet
    assert hint["available_words"] == ""                                           # depth 0: nothing known
    _force_stage(receipts_state, pid, "talking")
    assert payload.phone_block(receipts_state)["hints"][pid]["number"] == {"ok": False, "why": "Not there yet"}


def test_at_everyday_the_hint_names_their_days(receipts_state, matched) -> None:
    from engine.game.effects import apply_effect
    from engine.social import payload

    pid = matched("matchstick").split(":")[1]
    _set_person(receipts_state, pid, warmth=40, trust=30, episodes_done=1)
    apply_effect(receipts_state, {"type": "social_growth", "op": "gain", "pid": pid, "amount": 100})
    _force_stage(receipts_state, pid, "talking")
    hint = payload.phone_block(receipts_state)["hints"][pid]
    assert hint["available_words"].startswith(("Usually", "At work"))
    assert hint["number"] == {"ok": True, "why": ""} and hint["closer_soon"] is False
