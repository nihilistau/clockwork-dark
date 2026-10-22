"""
Relationships (v0.22.0 spec §10, T9): regard and its caps, stages and their
gates, proposals, ask pacing, mood, history, arcs (a turn, a drift), the
cold wind-down and the fade, the player's answers and endings.

Every number a test needs is read from relationships.yaml (pre-flight F20),
and every draw a test depends on is forced (F16).
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from tests.social_fixtures import (  # noqa: F401
    _act, _at, _force_archetype, _force_stage, _just_below, _open_episode, _set_person, _with, matched,
    receipts_active, receipts_state,
)


def _next_episode(state, pid: str, thread: str) -> None:
    """The open conversation with `pid` closed, if any, and a new one opened (v0.23.0 T5: caps are per
    episode, `convo.cap_key`), at the same in-game minute."""
    from engine.game.effects import apply_effect
    from engine.social import convo

    if convo.episode(state, pid) is not None:
        apply_effect(state, {"type": "social_episode", "op": "close", "pid": pid,
                             "at": state.world_clock_hours, "end": "lapsed"})
    _open_episode(state, pid, thread)


def _rules() -> dict:
    """relationships.yaml `regard:` -- every number a test needs comes from the data T26 tunes (F20)."""
    from engine import social

    return social.data("relationships")["regard"]


def _data(block: str):
    from engine import social

    return social.data("relationships")[block]


def _pace(monkeypatch, **fields) -> None:
    """Every archetype with ``fields`` replaced (a forced draw: F16)."""
    from engine.social import behaviour

    real = behaviour.archetype
    monkeypatch.setattr(behaviour, "archetype", lambda name: dataclasses.replace(real(name), **fields))


def _sure_replies(monkeypatch) -> None:
    """Every read is answered, nobody ghosts, nobody double texts (F16; v0.23.0: the per-episode-start
    draws forced, the person read a few minutes after the send, as v0.22's forced latency did)."""
    from engine.social import convo

    monkeypatch.setattr(convo, "_ghost_factor", lambda state, pid: 0.0)
    monkeypatch.setattr(convo, "_reply_factor", lambda state, pid: 100.0)
    monkeypatch.setattr(convo, "next_available", lambda state, pid, at: at + 5 / 60)
    _pace(monkeypatch, reply_minutes=(5.0, 0.0), double_text={"after_hours": 1, "prob": 0.0, "max_in_row": 0},
          initiations=())


# -- the brief's tests ------------------------------------------------------------------------


def test_regard_is_capped_per_reply_per_episode_and_by_archetype(receipts_state, matched) -> None:
    from engine.game.effects import apply_effect

    rules = _rules()
    thread = matched("matchstick")
    pid = thread.split(":")[1]
    before = dict(receipts_state.social["people"][pid])
    start_w = int(before.get("warmth", rules["start"]["warmth"]))
    start_t = int(before.get("trust", rules["start"]["trust"]))
    for _ in range(10):
        apply_effect(receipts_state, {"type": "social_regard", "pid": pid, "warmth": 99, "trust": 99})
    person = receipts_state.social["people"][pid]
    assert person["warmth"] - start_w <= int(rules["per_episode_gain"]["warmth"])
    assert person["trust"] - start_t <= int(rules["per_episode_gain"]["trust"])


def test_losses_are_not_capped(receipts_state, matched) -> None:
    from engine.game.effects import apply_effect

    worst = int(_rules()["per_reply"]["warmth"][0])          # the largest per-reply loss the data allows
    pid = matched("matchstick").split(":")[1]
    _set_person(receipts_state, pid, warmth=60)
    for _ in range(5):
        apply_effect(receipts_state, {"type": "social_regard", "pid": pid, "warmth": worst})
    assert receipts_state.social["people"][pid]["warmth"] == max(0, 60 + 5 * worst)   # no cap on a loss


def test_a_dry_texter_never_passes_warming(receipts_state, matched, monkeypatch) -> None:
    from engine.game.effects import apply_effect
    from engine.social import relationships

    thread = matched("matchstick")
    pid = thread.split(":")[1]
    _force_archetype(monkeypatch, receipts_state, pid, "dry_texter")
    top = relationships._bands()[-1]
    _set_person(receipts_state, pid, familiarity={"exchanges": 0, "contact_days": int(top["contact_days"])})
    for day in range(60):                                 # contact days enough for any band: warmth alone decides
        _next_episode(receipts_state, pid, thread)        # a fresh per-episode allowance each time (T5)
        apply_effect(receipts_state, {"type": "social_regard", "pid": pid, "warmth": 4, "day": day + 2})
    person = receipts_state.social["people"][pid]
    assert person["warmth"] <= relationships._band_cap("warming")
    assert person["warmth"] == relationships._band_cap("warming")      # it grew all the way to the cap
    assert relationships.band(person) == "warming"


@pytest.mark.parametrize("stage", ["talking", "numbers", "exclusive", "engaged"])
def test_each_gate_both_sides(receipts_state, matched, stage, monkeypatch) -> None:
    """Every stage reached through a gate (v0.23.0 T18: `meeting`'s, read by nothing, is gone; `engaged`'s is
    `willing.propose`, from `exclusive`)."""
    from engine.social import population, relationships

    pid = matched("matchstick").split(":")[1]
    if stage == "engaged":
        _force_stage(receipts_state, pid, "exclusive")
    if stage == "exclusive":                 # willing.exclusive: from dating, both after something long-term (T5)
        _force_stage(receipts_state, pid, "dating")
        real = population.profile
        monkeypatch.setattr(population, "profile", lambda s, p: dataclasses.replace(real(s, p), intent="long_term"))
        receipts_state.social["player"]["looking_for"] = "long_term"
    gate = relationships.gate_spec(stage)
    _set_person(receipts_state, pid, **_just_below(gate))
    assert relationships.gate_holds(receipts_state, pid, stage) is False
    _set_person(receipts_state, pid, **_at(gate))
    assert relationships.gate_holds(receipts_state, pid, stage) is True


def test_cool_off_never_moves_a_stage(receipts_state, matched) -> None:
    from engine.social import relationships

    pid = matched("matchstick").split(":")[1]
    _force_stage(receipts_state, pid, "talking")
    before = receipts_state.social["people"][pid]["interest"]
    relationships.apply_proposal(receipts_state, pid, "cool_off")
    after = receipts_state.social["people"][pid]
    assert after["stage"] == "talking" and before - 5 <= after["interest"] < before


def test_a_proposal_outside_its_gate_is_not_offered(receipts_state, matched) -> None:
    from engine.social import relationships

    pid = matched("matchstick").split(":")[1]
    _force_stage(receipts_state, pid, "matched")
    assert "offer_number" not in relationships.legal_proposals(receipts_state, pid)
    assert "ask_exclusive" not in relationships.legal_proposals(receipts_state, pid)
    assert "cool_off" in relationships.legal_proposals(receipts_state, pid)


def test_mood_decays_to_neutral(receipts_state, matched) -> None:
    from engine.game import clock
    from engine.game.effects import apply_effect

    pid = matched("matchstick").split(":")[1]
    apply_effect(receipts_state, {"type": "social_regard", "pid": pid, "mood": "annoyed"})
    clock.advance_time(receipts_state, 48)
    assert receipts_state.social["people"][pid]["mood"] == "neutral"


def test_a_third_ask_in_an_episode_is_refused_and_the_next_episode_resets_it(receipts_state, matched) -> None:
    thread = matched("matchstick")
    pid = thread.split(":")[1]
    _force_stage(receipts_state, pid, "talking")
    _next_episode(receipts_state, pid, thread)
    _act(receipts_state, "ask", target=thread, args={"what": "number"})
    _act(receipts_state, "ask", target=thread, args={"what": "number"})
    third = _act(receipts_state, "ask", target=thread, args={"what": "number"})
    assert third["refused"] and third["result"]["error"] == "Give it a while"
    _next_episode(receipts_state, pid, thread)                     # the same in-game day, a new episode
    assert _act(receipts_state, "ask", target=thread, args={"what": "number"})["success"]


def test_history_is_bounded_with_an_earlier_line(receipts_state, matched, monkeypatch) -> None:
    from engine import social
    from engine.social import relationships

    monkeypatch.setattr(social, "setting", _with(social.setting, history_max=5))
    pid = matched("matchstick").split(":")[1]
    for i in range(12):
        relationships.add_history(receipts_state, pid, "note", f"row {i}")
    rows = receipts_state.social["people"][pid]["memory"]["history"]
    assert len(rows) == 5 and rows[0]["kind"] == "earlier"


def test_a_turner_turns_at_its_point(receipts_state, matched, monkeypatch) -> None:
    from engine.game import clock
    from engine.social import messaging

    pid = matched("matchstick").split(":")[1]
    _force_archetype(monkeypatch, receipts_state, pid, "turner", arc_point=3)
    _sure_replies(monkeypatch)                            # every send answered, no ghost (F16)
    for i in range(4):
        messaging.send(receipts_state, f"matchstick:{pid}", "text", f"message {i}")
        clock.advance_time(receipts_state, 12)
        for m in receipts_state.social["threads"][f"matchstick:{pid}"]["messages"]:
            if m["voiced"] is False:
                m["voiced"] = True       # a test shortcut: a pass voiced it (v0.23.0: an unvoiced reply is a burst's)
    person = receipts_state.social["people"][pid]
    from engine.social import behaviour

    # The reveal's canon row's PROSE, through social_memory (T12; spec §12.1: canon is prose for the voice).
    assert behaviour.canon_text("wants_something_else") in person["memory"]["canon"] and person["stage"] == "winding_down"
    reveals = [m for m in receipts_state.social["threads"][f"matchstick:{pid}"]["messages"]
               if (m.get("decision") or {}).get("situation") == "opens_up"]
    assert reveals and reveals[0]["decision"]["reveal"] == "wants_something_else" and reveals[0]["from"] == pid
    kinds = [row["kind"] for row in person["memory"]["history"]]
    assert kinds.count("turn") == 1 and "fight" not in kinds              # one event, not a falling-out too


def test_every_stage_write_goes_through_social_stage() -> None:
    """Plan decision 17. Anchored at the repo (a wrong cwd must not pass vacuously) and widened to any
    `[...]["stage"] = ...` outside `_e_social_stage` -- T7's `social_match` wrote one directly (F18)."""
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "engine" / "social"
    files = sorted(root.rglob("*.py"))
    assert len(files) >= 10, root                         # the package is there: the scan is not vacuous
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        allowed = {line for fn in ast.walk(tree)
                   if isinstance(fn, ast.FunctionDef) and fn.name == "_e_social_stage"
                   for line in range(fn.lineno, (fn.end_lineno or fn.lineno) + 1)}
        for node in ast.walk(tree):
            if isinstance(node, ast.Dict):
                keys = [k.value for k in node.keys if isinstance(k, ast.Constant)]
                if "type" in keys and "set" in keys:
                    type_value = node.values[keys.index("type")]
                    set_value = node.values[keys.index("set")]
                    if getattr(type_value, "value", "") == "social_person" and isinstance(set_value, ast.Dict):
                        set_keys = [k.value for k in set_value.keys if isinstance(k, ast.Constant)]
                        assert "stage" not in set_keys, f"{path}:{node.lineno} writes a stage through social_person"
            if isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign)) and node.lineno not in allowed:
                targets = list(node.targets if isinstance(node, ast.Assign) else [node.target])
                while any(isinstance(t, (ast.Tuple, ast.List)) for t in targets):   # `a["stage"], b = ...` too
                    targets = [e for t in targets for e in (t.elts if isinstance(t, (ast.Tuple, ast.List)) else [t])]
                for target in targets:
                    if (isinstance(target, ast.Subscript) and isinstance(target.slice, ast.Constant)
                            and target.slice.value == "stage"):
                        raise AssertionError(f"{path}:{node.lineno} writes a stage outside social_stage")


def test_no_event_kind_is_queued_without_a_handler(receipts_state, matched, caplog) -> None:
    from engine.game import clock

    matched("matchstick")
    clock.advance_time(receipts_state, 24 * 30)
    assert "No handler for queued event" not in caplog.text


# -- further: regard, mood, history -------------------------------------------------------------


def test_regard_starts_where_the_data_says_at_a_match(receipts_state, matched) -> None:
    pid = matched("matchstick").split(":")[1]
    person = receipts_state.social["people"][pid]
    start = _rules()["start"]
    assert (person["warmth"], person["trust"]) == (int(start["warmth"]), int(start["trust"]))
    assert person["interest"] == int(_data("interest")["start"]) and person["mood"] == "neutral"
    assert person["stage"] == "matched"


def test_a_gain_is_multiplied_by_the_archetype_and_the_episode_cap_resets_next_episode(receipts_state, matched,
                                                                                        monkeypatch) -> None:
    from engine.game.effects import apply_effect

    rules = _rules()
    thread = matched("matchstick")
    pid = thread.split(":")[1]
    _pace(monkeypatch, warmth_mult=2.0, warmth_cap_band=None)
    _set_person(receipts_state, pid, warmth=0)
    _next_episode(receipts_state, pid, thread)
    step = int(rules["per_reply"]["warmth"][1])
    receipt = apply_effect(receipts_state, {"type": "social_regard", "pid": pid, "warmth": step, "day": 5})
    assert receipt["applied"]["warmth"] == min(2 * step, int(rules["per_episode_gain"]["warmth"]))
    for _ in range(10):
        apply_effect(receipts_state, {"type": "social_regard", "pid": pid, "warmth": step, "day": 6})
    assert receipts_state.social["people"][pid]["warmth"] == int(rules["per_episode_gain"]["warmth"])  # a day is no reset
    _next_episode(receipts_state, pid, thread)
    apply_effect(receipts_state, {"type": "social_regard", "pid": pid, "warmth": step, "day": 6})
    assert receipts_state.social["people"][pid]["warmth"] > int(rules["per_episode_gain"]["warmth"])


def test_a_band_cap_never_pulls_warmth_down(receipts_state, matched, monkeypatch) -> None:
    from engine.game.effects import apply_effect

    pid = matched("matchstick").split(":")[1]
    _pace(monkeypatch, warmth_cap_band="warming")
    _set_person(receipts_state, pid, warmth=90)
    apply_effect(receipts_state, {"type": "social_regard", "pid": pid, "warmth": 2})
    assert receipts_state.social["people"][pid]["warmth"] == 90


def test_an_unknown_mood_is_ignored_and_a_regard_bumps_rev(receipts_state, matched) -> None:
    from engine.game.effects import apply_effect

    pid = matched("matchstick").split(":")[1]
    rev = receipts_state.social["people"][pid]["rev"]
    apply_effect(receipts_state, {"type": "social_regard", "pid": pid, "mood": "furious"})
    person = receipts_state.social["people"][pid]
    assert person["mood"] == "neutral" and person["rev"] == rev + 1


def test_a_fight_and_making_up_are_history(receipts_state, matched) -> None:
    from engine.game.effects import apply_effect

    rules = _rules()
    pid = matched("matchstick").split(":")[1]
    _set_person(receipts_state, pid, warmth=60)
    worst = int(rules["per_reply"]["warmth"][0])
    while sum(row["kind"] == "fight" for row in receipts_state.social["people"][pid]["memory"]["history"]) == 0:
        apply_effect(receipts_state, {"type": "social_regard", "pid": pid, "warmth": worst, "day": 3})
    assert receipts_state.social["people"][pid]["regard_today"]["loss"] <= int(rules["fight_warmth"])
    best = int(rules["per_reply"]["warmth"][1])
    for _ in range(10):
        apply_effect(receipts_state, {"type": "social_regard", "pid": pid, "warmth": best, "day": 4})
    kinds = [row["kind"] for row in receipts_state.social["people"][pid]["memory"]["history"]]
    assert kinds.count("fight") == 1 and kinds.count("reconciled") == 1


def test_the_earlier_line_counts_what_it_folded(receipts_state, matched, monkeypatch) -> None:
    from engine import social
    from engine.social import relationships

    monkeypatch.setattr(social, "setting", _with(social.setting, history_max=5))
    pid = matched("matchstick").split(":")[1]
    before = len(receipts_state.social["people"][pid]["memory"]["history"])
    for i in range(12):
        relationships.add_history(receipts_state, pid, "note", f"row {i}")
    rows = receipts_state.social["people"][pid]["memory"]["history"]
    assert rows[0]["count"] == before + 12 - 4 and rows[0]["text"] == f"{before + 8} earlier moments"
    assert [row["text"] for row in rows[1:]] == ["row 8", "row 9", "row 10", "row 11"]


def test_social_person_refuses_a_stage(receipts_state, matched) -> None:
    from engine.game.effects import apply_effect

    pid = matched("matchstick").split(":")[1]
    refused = apply_effect(receipts_state, {"type": "social_person", "pid": pid, "set": {"stage": "dating"}})
    assert refused["ok"] is False and receipts_state.social["people"][pid]["stage"] == "matched"


def test_a_stage_move_writes_its_words_to_history(receipts_state, matched) -> None:
    from engine.social import relationships

    pid = matched("matchstick").split(":")[1]
    _force_stage(receipts_state, pid, "numbers")
    person = receipts_state.social["people"][pid]
    assert person["memory"]["history"][-1]["text"] == relationships.stage_words("numbers") == "Swapped numbers"
    assert person["stage_since"] == receipts_state.world_clock_hours


# -- further: exchanges, the automatic stage, interest ----------------------------------------------


def test_talking_comes_at_the_gate_s_exchanges(receipts_state, matched, monkeypatch) -> None:
    from engine.social import messaging, relationships

    thread = matched("matchstick")
    pid = thread.split(":")[1]
    _sure_replies(monkeypatch)
    needed = int(relationships.gate_spec("talking")["exchanges"])
    for i in range(needed + 1):
        sender = "player" if i % 2 == 0 else pid
        if receipts_state.social["people"][pid]["stage"] == "talking":
            break
        messaging.new_message(receipts_state, thread, sender, "text", bubbles=[f"line {i}"])
    person = receipts_state.social["people"][pid]
    assert person["familiarity"]["exchanges"] == needed and person["stage"] == "talking"
    assert [row["kind"] for row in person["memory"]["history"]].count("first_message") == 1


def test_an_exchange_and_a_named_hobby_raise_interest(receipts_state, matched) -> None:
    from engine.social import messaging, population

    thread = matched("matchstick")
    pid = thread.split(":")[1]
    rules = _data("interest")
    hobby = population.profile(receipts_state, pid).hobbies[0]
    label = {row["id"]: row["label"] for row in population.table("hobbies")}[hobby]
    messaging.new_message(receipts_state, thread, pid, "text", bubbles=["hi"])
    before = receipts_state.social["people"][pid]["interest"]
    messaging.new_message(receipts_state, thread, "player", "text", bubbles=[f"I love {label.lower()} too"])
    after = receipts_state.social["people"][pid]["interest"]
    assert after - before == int(rules["per_exchange"]) + int(rules["shared_hobby_mention"])


def test_being_left_on_read_costs_interest_once(receipts_state, matched, monkeypatch) -> None:
    from engine.game.effects import apply_effect
    from engine.social import messaging, relationships

    thread = matched("matchstick")
    pid = thread.split(":")[1]
    _pace(monkeypatch, left_on_read_sensitivity=1.0)
    rules = _data("interest")["left_on_read"]
    now = receipts_state.world_clock_hours
    _set_person(receipts_state, pid, left_on_read_since=now, interest=50)
    hours = float(rules["grace_hours"]) + 3
    apply_effect(receipts_state, {"type": "social_event", "event": {
        "at": now + hours, "seq": 10 ** 6, "pid": pid, "kind": "initiate", "thread_id": thread,
        "decision": {"situation": "check_in", "kind": "text"}}})
    assert receipts_state.social["people"][pid]["interest"] == 50 - 3      # their first message: no exchange yet
    messaging.new_message(receipts_state, thread, "player", "text", bubbles=["sorry!"], at=now + hours)
    person = receipts_state.social["people"][pid]
    assert person["left_on_read_since"] is None and person["left_on_read_paid"] == 0
    assert relationships.measure(person, "exchanges") == 1
    assert person["interest"] == 50 - 3 + int(_data("interest")["per_exchange"])   # not charged twice


# -- further: the daily steps ----------------------------------------------------------------------


def test_five_cold_days_wind_it_down(receipts_state, matched, monkeypatch) -> None:
    from engine.game import clock
    from engine.social import messaging

    thread = matched("matchstick")
    pid = thread.split(":")[1]
    cold = _data("cold")
    _force_stage(receipts_state, pid, "talking")
    _set_person(receipts_state, pid, warmth=int(cold["warmth_below"]) - 1)
    for day in range(int(cold["days"]) - 1):
        messaging.new_message(receipts_state, thread, pid, "text", bubbles=["."])  # contact: no fade
        clock.advance_time(receipts_state, 24)
    assert receipts_state.social["people"][pid]["stage"] == "talking"
    clock.advance_time(receipts_state, 24)
    person = receipts_state.social["people"][pid]
    assert person["stage"] == "winding_down" and person["memory"]["history"][-1]["kind"] == "cooled"


def test_a_cold_spell_that_warms_again_recovers(receipts_state, matched, monkeypatch) -> None:
    from engine.game import clock
    from engine.social import messaging

    _pace(monkeypatch, initiations=(), double_text={"after_hours": 1, "prob": 0.0, "max_in_row": 0})
    thread = matched("matchstick")
    pid = thread.split(":")[1]
    cold = _data("cold")
    _force_stage(receipts_state, pid, "talking")
    _set_person(receipts_state, pid, warmth=int(cold["warmth_below"]) - 1)
    for _ in range(int(cold["days"])):
        messaging.new_message(receipts_state, thread, pid, "text", bubbles=["."])
        clock.advance_time(receipts_state, 24)
    assert receipts_state.social["people"][pid]["stage"] == "winding_down"
    _set_person(receipts_state, pid, warmth=int(cold["recover_above"]))
    for _ in range(int(cold["recover_days"]) - 1):
        messaging.new_message(receipts_state, thread, pid, "text", bubbles=["."])
        clock.advance_time(receipts_state, 24)
    assert receipts_state.social["people"][pid]["stage"] == "winding_down"   # not yet: one morning short
    messaging.new_message(receipts_state, thread, pid, "text", bubbles=["."])
    clock.advance_time(receipts_state, 24)
    person = receipts_state.social["people"][pid]
    assert person["stage"] == "talking" and person["memory"]["history"][-1]["kind"] == "recovered"


def test_a_turn_does_not_recover_by_warming(receipts_state, matched, monkeypatch) -> None:
    from engine.game import clock
    from engine.game.effects import apply_effect
    from engine.social import messaging

    _pace(monkeypatch, initiations=(), double_text={"after_hours": 1, "prob": 0.0, "max_in_row": 0})
    thread = matched("matchstick")
    pid = thread.split(":")[1]
    cold = _data("cold")
    _force_stage(receipts_state, pid, "talking")
    _force_archetype(monkeypatch, receipts_state, pid, "turner")
    apply_effect(receipts_state, {"type": "social_event", "event": {
        "at": receipts_state.world_clock_hours, "seq": 10 ** 6, "pid": pid, "kind": "arc_beat",
        "arc": "turner_wants_different"}})
    assert receipts_state.social["people"][pid]["stage"] == "winding_down"
    _set_person(receipts_state, pid, warmth=int(cold["recover_above"]) + 20)
    for _ in range(int(cold["recover_days"]) + 2):
        messaging.new_message(receipts_state, thread, pid, "text", bubbles=["."])
        clock.advance_time(receipts_state, 24)
    assert receipts_state.social["people"][pid]["stage"] == "winding_down"


def test_a_turn_on_someone_already_cooling_does_not_recover(receipts_state, matched, monkeypatch) -> None:
    from engine.game import clock
    from engine.game.effects import apply_effect
    from engine.social import messaging

    _pace(monkeypatch, initiations=(), double_text={"after_hours": 1, "prob": 0.0, "max_in_row": 0})
    thread = matched("matchstick")
    pid = thread.split(":")[1]
    cold = _data("cold")
    _force_stage(receipts_state, pid, "talking")
    _set_person(receipts_state, pid, warmth=int(cold["warmth_below"]) - 1)
    for _ in range(int(cold["days"])):
        messaging.new_message(receipts_state, thread, pid, "text", bubbles=["."])
        clock.advance_time(receipts_state, 24)
    assert receipts_state.social["people"][pid]["wound_by"] == "cold"
    _force_archetype(monkeypatch, receipts_state, pid, "turner")
    apply_effect(receipts_state, {"type": "social_event", "event": {
        "at": receipts_state.world_clock_hours, "seq": 10 ** 6, "pid": pid, "kind": "arc_beat",
        "arc": "turner_wants_different"}})
    _set_person(receipts_state, pid, warmth=int(cold["recover_above"]) + 20)
    for _ in range(int(cold["recover_days"]) + 2):
        messaging.new_message(receipts_state, thread, pid, "text", bubbles=["."])
        clock.advance_time(receipts_state, 24)
    assert receipts_state.social["people"][pid]["stage"] == "winding_down"


def test_mood_now_reads_the_clock_before_the_morning_step(receipts_state, matched) -> None:
    from engine.game.effects import apply_effect
    from engine.social import relationships

    pid = matched("matchstick").split(":")[1]
    hours = float(_data("mood")["decay_hours"])
    assert hours < 24
    now = receipts_state.world_clock_hours
    apply_effect(receipts_state, {"type": "social_regard", "pid": pid, "mood": "annoyed"})
    person = receipts_state.social["people"][pid]
    assert relationships.mood_now(person, now + hours - 0.5) == "annoyed"
    assert relationships.mood_now(person, now + hours + 0.5) == "neutral"


def test_give_it_a_day_gives_way_to_a_truer_reason(receipts_state, matched) -> None:
    thread = matched("matchstick")
    pid = thread.split(":")[1]
    _force_stage(receipts_state, pid, "talking")
    for _ in range(2):
        assert _act(receipts_state, "ask", target=thread, args={"what": "number"})["success"]
    _force_stage(receipts_state, pid, "numbers")
    third = _act(receipts_state, "ask", target=thread, args={"what": "number"})
    assert third["refused"] and third["result"]["error"].startswith("You already have")


def test_an_unknown_cap_band_fails_at_load(tmp_path, monkeypatch) -> None:
    import shutil

    import yaml

    from engine import social

    src = Path(__file__).resolve().parents[1] / "games" / "read-receipts" / "data" / "social"
    shutil.copytree(src, tmp_path / "social")
    path = tmp_path / "social" / "behaviours.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["archetypes"]["dry_texter"]["warmth_cap_band"] = "lukewarm"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    monkeypatch.setattr(social, "social_dir", lambda: tmp_path / "social")
    monkeypatch.setattr(social, "_DATA_CACHE", None)
    with pytest.raises(ValueError, match=r"behaviours.yaml: archetypes.dry_texter.warmth_cap_band"):
        social.load_all()
    assert social._DATA_CACHE is None


def test_no_contact_for_fade_days_fades_and_their_message_reconnects(receipts_state, matched, monkeypatch) -> None:
    from engine.game import clock
    from engine.social import messaging

    _pace(monkeypatch, initiations=(), double_text={"after_hours": 1, "prob": 0.0, "max_in_row": 0})
    thread = matched("matchstick")
    pid = thread.split(":")[1]
    messaging.new_message(receipts_state, thread, "player", "text", bubbles=["hi"])
    _force_stage(receipts_state, pid, "talking")
    receipts_state.social["queue"] = [e for e in receipts_state.social["queue"] if e["pid"] != pid]
    clock.advance_time(receipts_state, 24 * (int(_data("fade_days")) + 1))
    person = receipts_state.social["people"][pid]
    assert person["stage"] == "faded" and person["stage_before"] == "talking"
    messaging.new_message(receipts_state, thread, pid, "text", bubbles=["hey stranger"])
    person = receipts_state.social["people"][pid]
    assert person["stage"] == "talking" and person["memory"]["history"][-1]["kind"] == "reconnected"


def test_a_drifter_loses_interest_each_day_past_its_point(receipts_state, matched, monkeypatch) -> None:
    from engine.game import clock
    from engine.social import messaging, relationships

    thread = matched("matchstick")
    pid = thread.split(":")[1]
    _force_archetype(monkeypatch, receipts_state, pid, "drifter", arc_point=0)
    monkeypatch.setattr(relationships, "_block", _decay_off(relationships._block))
    _set_person(receipts_state, pid, interest=60)
    messaging.new_message(receipts_state, thread, pid, "text", bubbles=["."])
    receipts_state.social["queue"] = [e for e in receipts_state.social["queue"] if e["pid"] != pid]
    clock.advance_time(receipts_state, 24 * 3)
    from engine.social import behaviour

    step = int(behaviour.arc_spec("drifter_fade")["each_day"]["interest"])
    assert receipts_state.social["people"][pid]["interest"] == 60 + 3 * step


def _decay_off(real):
    """relationships.yaml with `interest.daily_decay` 0, so only the drift moves interest."""
    def block(name):
        value = real(name)
        return {**value, "daily_decay": 0} if name == "interest" else value

    return block


# -- further: asks, proposals, answers, ending ----------------------------------------------------


def test_a_repeat_ask_lowers_its_odds_and_costs_warmth(receipts_state, matched) -> None:
    thread = matched("matchstick")
    pid = thread.split(":")[1]
    asks = _data("asks")
    _force_stage(receipts_state, pid, "talking")
    warmth = receipts_state.social["people"][pid]["warmth"]
    assert _act(receipts_state, "ask", target=thread, args={"what": "number"})["success"]
    again = _act(receipts_state, "ask", target=thread, args={"what": "number"})
    assert again["success"] and again["result"]["again"] is True
    requests = [r for r in receipts_state.social["requests"].values() if r["pid"] == pid]
    assert len(requests) == 1 and requests[0]["mult"] == pytest.approx(float(asks["repeat_mult"]))
    assert receipts_state.social["people"][pid]["warmth"] == warmth + int(asks["repeat_warmth"])


def test_an_ask_answered_below_its_gate_is_not_yet(receipts_state, matched, monkeypatch) -> None:
    from engine.social import relationships

    pid = matched("matchstick").split(":")[1]
    _force_stage(receipts_state, pid, "talking")
    _set_person(receipts_state, pid, **_just_below(relationships.gate_spec("numbers")))
    assert relationships.ask_decision(receipts_state, pid, "number") == {"accept": False, "why": "not_yet"}
    _set_person(receipts_state, pid, **{**_at(relationships.gate_spec("numbers")), "trust": 100})
    _pace(monkeypatch, media={"offer_mult": 1.0, "accept_mult": 1.0})
    assert relationships.ask_decision(receipts_state, pid, "number")["accept"] is True


def test_exclusive_needs_both_long_term(receipts_state, matched, monkeypatch) -> None:
    from engine.social import population, relationships

    pid = matched("matchstick").split(":")[1]
    _force_stage(receipts_state, pid, "dating")
    _set_person(receipts_state, pid, **_at(relationships.gate_spec("exclusive")))
    real = population.profile
    for theirs, mine, holds in (("long_term", "long_term", True), ("short_term", "long_term", False)):
        monkeypatch.setattr(population, "profile", lambda s, p, t=theirs: dataclasses.replace(real(s, p), intent=t))
        receipts_state.social["player"]["looking_for"] = mine
        assert relationships.can_reach(receipts_state, pid, "exclusive") is holds
        assert ("ask_exclusive" in relationships.legal_proposals(receipts_state, pid)) is holds


def test_their_number_offered_and_answered_yes_opens_texts(receipts_state, matched) -> None:
    from engine.social import relationships
    from engine.social.payload import phone_block

    thread = matched("matchstick")
    pid = thread.split(":")[1]
    _force_stage(receipts_state, pid, "talking")
    _set_person(receipts_state, pid, **_at(relationships.gate_spec("numbers")))
    made = relationships.apply_proposal(receipts_state, pid, "offer_number")
    assert made["ok"]
    assert "offer_number" not in relationships.legal_proposals(receipts_state, pid)    # one at a time
    rows = phone_block(receipts_state)["requests"]
    assert [(r["id"], r["from"], r["what"]) for r in rows] == [(made["request_id"], "them", "number")]
    assert "mult" not in rows[0]
    answered = _act(receipts_state, "answer", target=made["request_id"], args={"reply": "yes"})
    assert answered["success"], answered
    assert receipts_state.social["people"][pid]["stage"] == "numbers"
    assert f"texts:{pid}" in receipts_state.social["threads"]
    assert receipts_state.social["threads"][thread]["messages"][-1]["answer"] == "yes"
    assert phone_block(receipts_state)["requests"] == []


def test_saying_no_costs_warmth_and_sets_their_mood(receipts_state, matched) -> None:
    from engine.social import relationships

    thread = matched("matchstick")
    pid = thread.split(":")[1]
    down = _data("asks")["turned_down"]
    _force_stage(receipts_state, pid, "talking")
    _set_person(receipts_state, pid, **{**_at(relationships.gate_spec("numbers")), "warmth": 50})
    rid = relationships.apply_proposal(receipts_state, pid, "offer_number")["request_id"]
    assert _act(receipts_state, "answer", target=rid, args={"reply": "no"})["success"]
    person = receipts_state.social["people"][pid]
    assert person["warmth"] == 50 + int(down["warmth"]) and person["mood"] == down["mood"]
    assert person["stage"] == "talking"
    assert _act(receipts_state, "answer", target=rid, args={"reply": "yes"})["refused"]   # answered


def test_a_yes_after_the_gate_closed_is_refused(receipts_state, matched) -> None:
    from engine.social import relationships

    pid = matched("matchstick").split(":")[1]
    _force_stage(receipts_state, pid, "talking")
    _set_person(receipts_state, pid, **_at(relationships.gate_spec("numbers")))
    rid = relationships.apply_proposal(receipts_state, pid, "offer_number")["request_id"]
    _set_person(receipts_state, pid, warmth=0)
    refused = _act(receipts_state, "answer", target=rid, args={"reply": "yes"})
    assert refused["refused"] and receipts_state.social["requests"][rid]["status"] == "pending"


def test_ending_it_drops_their_queue(receipts_state, matched) -> None:
    from engine.social import messaging

    thread = matched("matchstick")
    pid = thread.split(":")[1]
    messaging.send(receipts_state, thread, "text", "hello")
    assert any(e["pid"] == pid and e["kind"] == "read" for e in receipts_state.social["queue"])
    ended = _act(receipts_state, "end", target=pid)
    assert ended["success"], ended
    person = receipts_state.social["people"][pid]
    assert person["stage"] == "ended" and person["ended_by"] == "player"
    assert not any(e["pid"] == pid and e["kind"] in ("read", "reply") for e in receipts_state.social["queue"])
    assert _act(receipts_state, "end", target=pid)["refused"]


def test_apply_regard_counts_against_the_day_it_names(receipts_state, matched) -> None:
    from engine.social import relationships

    rules = _rules()
    pid = matched("matchstick").split(":")[1]
    relationships.apply_regard(receipts_state, pid, {"warmth": 4, "trust": 2, "mood": "fond"}, day=9)
    person = receipts_state.social["people"][pid]
    assert person["regard_day"] == 9 and person["mood"] == "fond"
    assert person["trust"] == int(rules["start"]["trust"]) + 2


def test_stage_words_and_band_ride_on_the_thread_row(receipts_state, matched) -> None:
    from engine.social.payload import phone_block

    thread = matched("matchstick")
    row = next(r for r in phone_block(receipts_state)["threads"] if r["thread_id"] == thread)
    assert row["stage_words"] == "Just matched" and row["band"] == "new"


# -- further: the data's own checks ------------------------------------------------------------------


def test_the_shipped_relationships_data_validates_clean() -> None:
    from engine.games.validation import errors_only, validate_story

    errors = [i for i in errors_only(validate_story("read-receipts"))
              if "relationships" in i.source or "behaviours" in i.source]
    assert errors == []


@pytest.mark.parametrize("path, value, key", [
    (("stages", "numbers", "gate", "warmth_ish"), 3, "stages.numbers.gate"),
    (("proposals", "offer_kiss"), {"stage": "talking", "gate": None}, "proposals.offer_kiss"),
    (("regard", "per_reply", "warmth"), [4, -4], "regard.per_reply.warmth"),
    (("mood", "values"), ["fond"], "mood.values"),
    (("regard", "fallback"), {"warmth": 2}, "regard.fallback.trust"),
    (("cold", "recover_above"), "warm", "cold"),
    (("cold", "recover_above"), 10, "cold.recover_above"),
])
def test_a_broken_relationships_file_is_an_error_naming_its_key(path, value, key) -> None:
    import copy

    from engine.social import relationships
    from engine import yamlio
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    data = yamlio.safe_load((root / "games/read-receipts/data/social/relationships.yaml").read_text(encoding="utf-8"))
    broken = copy.deepcopy(data)
    target = broken
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = value
    with pytest.raises(ValueError, match=f"relationships.yaml: {key.replace('.', '[.]')}"):
        relationships.check_data(broken)


def test_fallback_regard_has_its_own_smaller_episode_cap(receipts_state, matched) -> None:
    """Spec §10.2's ruling, T26 fix round 2: a fallback reply's regard grows a relationship, capped an episode
    by `regard.fallback.per_episode`, below what a working model's replies may add (`per_episode_gain`)."""
    from engine.social import relationships

    rules = relationships._block("regard")
    cap = rules["fallback"]["per_episode"]
    pid = matched("matchstick").split(":")[1]
    person = receipts_state.social["people"][pid]
    start = (person["warmth"], person["trust"])
    for _ in range(10):
        relationships.apply_regard(receipts_state, pid, {"warmth": 1, "trust": 1}, day=receipts_state.world_day,
                                   fallback=True)
    assert person["trust"] - start[1] == int(cap["trust"]) > 0
    assert 0 < person["warmth"] - start[0] <= int(cap["warmth"])
    # A model's reply in the same episode still has the room per_episode_gain leaves.
    before = person["trust"]
    relationships.apply_regard(receipts_state, pid, {"warmth": 1, "trust": 1}, day=receipts_state.world_day)
    assert person["trust"] == before + 1 and int(rules["per_episode_gain"]["trust"]) > int(cap["trust"])


# -- the contact card's section (T29, spec §18.2) ------------------------------------------------------


def test_the_contacts_section_is_the_players_view_of_each_person(receipts_state, matched) -> None:
    """One row per person with a listed thread: their dating profile, the stage's words and the band (never
    a number), "Your story" (history lines), what they chose to tell (`canon`, never `knows`), and whole days
    since their last message. Registered time-varying (F14), so T16's 72-hour test allows it to move."""
    from engine.social import apps, memory, payload, relationships

    state = receipts_state
    thread = matched("matchstick")
    pid = thread.split(":", 1)[1]
    memory.add_canon(state, pid, ["I grew up by the sea"])
    memory.add_knows(state, pid, ["zz-knows-sentinel: the player hates mornings"])
    _set_person(state, pid, last_them_at=state.world_clock_hours - 74.0)
    (row,) = [r for r in payload.phone_block(state)["contacts"] if r["pid"] == pid]
    card = apps.card(state, "matchstick", pid)
    person = state.social["people"][pid]
    assert row["name"] == card["name"] and row["photos"] == card["photos"] and row["app"] == "matchstick"
    assert row["profile"] == {k: card[k] for k in relationships.CONTACT_PROFILE if k in card}
    assert row["stage_words"] == relationships.stage_words(person["stage"]) and row["band"] == relationships.band(person)
    assert [h["text"] for h in row["history"]] == [h["text"] for h in person["memory"]["history"]] and row["history"]
    assert all(set(h) == {"day", "at", "text"} for h in row["history"])
    assert row["about"] == ["I grew up by the sea"]
    assert "zz-knows-sentinel" not in repr(row)
    assert row["last_heard_days"] == 3
    assert row["thread_ids"] == [thread] and row["open"] is True and row["matched"] is True
    assert "contacts" in payload.TIME_VARYING_SECTIONS


def test_the_contacts_section_lists_each_person_once_and_never_an_unmatched_one(receipts_state, matched) -> None:
    """A person with a dating thread and two messenger threads is one contact (their dating app's profile);
    one the player unmatched is gone from the list, as their thread is; nobody heard from yet reads None."""
    from engine.social import matching, messaging, payload

    state = receipts_state
    first = matched("matchstick").split(":", 1)[1]
    _force_stage(state, first, "numbers")
    messaging.open_numbers(state, first)
    second = matched("matchstick").split(":", 1)[1]
    rows = {r["pid"]: r for r in payload.phone_block(state)["contacts"]}
    assert set(rows) == {first, second}
    assert sorted(rows[first]["thread_ids"]) == sorted(t for t, row in state.social["threads"].items()
                                                       if row["pid"] == first) and len(rows[first]["thread_ids"]) == 3
    assert rows[first]["app"] == "matchstick"
    heard = state.social["people"][second].get("last_them_at")
    assert rows[second]["last_heard_days"] == (None if heard is None else int((state.world_clock_hours - heard) // 24))
    assert matching.unmatch(state, second, by="player")["ok"]
    assert [r["pid"] for r in payload.phone_block(state)["contacts"]] == [first]


def test_a_contact_names_the_app_the_match_was_made_on(receipts_state, matched) -> None:
    """T29 review M9: "Matched on" comes from the person's own record (`apps.<app>.matched_at`), never the
    population's first app; an unmatched dating thread still names it while a messenger thread keeps them
    listed, and a person with no match on record names none."""
    from engine.social import apps, matching, messaging, payload

    state = receipts_state
    pid = matched("matchstick").split(":", 1)[1]
    _force_stage(state, pid, "numbers")
    messaging.open_numbers(state, pid)
    assert matching.unmatch(state, pid, by="player")["ok"]
    (row,) = [r for r in payload.phone_block(state)["contacts"] if r["pid"] == pid]
    assert all(not t.startswith("matchstick:") for t in row["thread_ids"])     # its dating thread is gone
    assert row["app"] == "matchstick" and row["matched_on"] == apps.label("matchstick")
    # The record names Front Porch: so does the card, whatever the population lists first.
    _set_person(state, pid, apps={"front_porch": {"matched_at": 1.0}})
    (row,) = [r for r in payload.phone_block(state)["contacts"] if r["pid"] == pid]
    assert row["app"] == "front_porch" and row["matched_on"] == apps.label("front_porch")
