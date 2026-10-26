"""The long term (v0.23.0 spec §12, T18): together, living together, engaged, married; the household; the
wedding; at home with the partner; and being seen.

Every stage here is an outcome of the relationship and the household a record of who lives in the flat
(rule 12): the tests assert stages, a pid, history lines and regard, nothing else. Every draw a test depends on
is forced (`growth.willing`, `scene._moment_draw`, `life._seen_drawn`, `convo._status`).
"""

from __future__ import annotations

import pytest

from tests.social_fixtures import (  # noqa: F401
    _force_stage, _set_person, matched, matched_numbers, receipts_active, receipts_state)


def _all_willing(monkeypatch):
    from engine.social import growth

    monkeypatch.setattr(growth, "willing", lambda s, p, c: (True, ""))


def _pid(matched, app: str = "matchstick") -> str:
    return matched(app).split(":")[1]


def _move_in(state, pid: str) -> None:
    from engine.game.effects import apply_effect

    assert apply_effect(state, {"type": "social_household", "op": "move_in", "pid": pid})["ok"]


def _at_home(state, monkeypatch, status: str = "free") -> None:
    from engine.game.effects import apply_effect
    from engine.social import convo

    assert apply_effect(state, {"type": "social_go", "op": "place", "to": "apt_lounge"})["ok"]
    monkeypatch.setattr(convo, "_status", lambda s, p, at: status)


# -- the brief's tests -----------------------------------------------------------------------------------------


def test_moving_in_from_together_is_living_together(receipts_state, matched, monkeypatch) -> None:
    from engine.social import relationships

    pid = matched("matchstick").split(":")[1]
    _all_willing(monkeypatch)
    _force_stage(receipts_state, pid, "exclusive")
    relationships.apply_move_in(receipts_state, pid)
    assert receipts_state.social["people"][pid]["stage"] == "living_together"
    assert receipts_state.social["household"] == pid


def test_an_engaged_couple_can_still_move_in(receipts_state, matched, monkeypatch) -> None:
    """m6: moving in at engaged changes the household, never the stage."""
    from engine.social import relationships

    pid = matched("matchstick").split(":")[1]
    _all_willing(monkeypatch)
    _force_stage(receipts_state, pid, "engaged")
    relationships.apply_move_in(receipts_state, pid)
    assert receipts_state.social["people"][pid]["stage"] == "engaged"
    assert receipts_state.social["household"] == pid


def test_the_wedding_cannot_go_badly_and_marries(receipts_state, matched, monkeypatch) -> None:
    from engine.social import scene

    pid = matched("matchstick").split(":")[1]
    _force_stage(receipts_state, pid, "engaged")
    monkeypatch.setattr(scene, "_moment_draw", lambda s, p: -5.0)
    receipts_state.location_id = "registry_office"
    scene.open_scene(receipts_state, pid, "registry_office", kind="wedding")
    targets = scene.scene_verbs(receipts_state)[0].targets
    assert {t.split(":")[0] for t in targets} <= {"quiet", "tell_about", "playful", "talk"}   # talk: A4 W7 (I10)
    for _ in range(3):
        assert scene.move(receipts_state, "quiet")["band"] in ("lands", "fine")
    assert receipts_state.social["people"][pid]["stage"] == "married"


def test_being_seen_with_someone_else_costs_the_partner(receipts_state, matched, monkeypatch) -> None:
    from engine.social import growth, life

    partner = matched("matchstick").split(":")[1]
    other = matched("front_porch").split(":")[1]
    _force_stage(receipts_state, partner, "exclusive")
    monkeypatch.setattr(life, "_seen_drawn", lambda s: True)
    trust = receipts_state.social["people"][partner]["trust"]
    life.seen_check(receipts_state, other)
    assert receipts_state.social["people"][partner]["trust"] < trust
    assert growth.record(receipts_state, partner)["guarded"] == 1


def test_no_stage_is_an_ending(receipts_state, matched) -> None:
    from engine.social import relationships

    pid = matched("matchstick").split(":")[1]
    for stage in ("living_together", "engaged", "married"):
        _force_stage(receipts_state, pid, stage)
        assert relationships.live(receipts_state.social["people"][pid])


# -- the brief's further tests ----------------------------------------------------------------------------------


def test_move_in_needs_14_days_since_together(receipts_state, matched) -> None:
    """The real `willing.move_in`: 14 days since `exclusive` began (R15), with its other floors met."""
    from engine.social import growth, relationships

    pid = _pid(matched)
    _force_stage(receipts_state, pid, "exclusive")
    now = receipts_state.world_clock_hours
    _set_person(receipts_state, pid, warmth=90, trust=90, scenes_done=20, exclusive_since=now - 24.0 * 13)
    assert growth.willing(receipts_state, pid, "move_in") == (False, "not_yet")
    assert not relationships.apply_move_in(receipts_state, pid)["ok"]
    assert receipts_state.social["household"] == ""
    _set_person(receipts_state, pid, exclusive_since=now - 24.0 * 14)
    assert growth.willing(receipts_state, pid, "move_in") == (True, "")
    assert relationships.apply_move_in(receipts_state, pid)["ok"]
    assert receipts_state.social["household"] == pid
    assert receipts_state.social["people"][pid]["stage"] == "living_together"
    assert growth.willing(receipts_state, pid, "move_in") == (False, "household")      # one household at a time


def test_an_at_home_scene_with_the_partner_needs_no_plan(receipts_state, matched, monkeypatch) -> None:
    from engine.social import scene, world

    pid = _pid(matched)
    _force_stage(receipts_state, pid, "living_together")
    _move_in(receipts_state, pid)
    _at_home(receipts_state, monkeypatch)
    verbs = {v.action: v for v in world.world_verbs(receipts_state)}
    assert verbs["scene"].targets == (f"at_home:{pid}",)
    assert not receipts_state.social.get("plans")
    opened = scene.move(receipts_state, f"at_home:{pid}")
    assert opened["ok"] and opened["opened"] == "at_home"
    assert scene.current(receipts_state)["kind"] == "at_home"
    assert scene.current(receipts_state)["location"] == "apt_lounge"
    closers = {t.split(":")[0] for t in dict(scene._close_options(receipts_state, scene.current(receipts_state)))}
    assert closers <= {"call_it_a_night", "another_round", "propose"}     # no way home, nobody to see off


def test_the_partner_is_not_offered_while_out_or_away(receipts_state, matched, monkeypatch) -> None:
    from engine.social import scene, world

    pid = _pid(matched)
    _force_stage(receipts_state, pid, "living_together")
    _move_in(receipts_state, pid)
    for status in ("work", "asleep", "out"):
        _at_home(receipts_state, monkeypatch, status)
        assert "scene" not in {v.action for v in world.world_verbs(receipts_state)}
        assert scene.household_present(receipts_state) == ""
    _at_home(receipts_state, monkeypatch, "free")
    from engine.game.effects import apply_effect

    assert apply_effect(receipts_state, {"type": "social_go", "op": "place", "to": "the_anchor"})["ok"]
    assert scene.household_present(receipts_state) == ""                 # the player is out, not the partner


def test_the_persons_propose_proposal_is_held_by_willing(receipts_state, matched, monkeypatch) -> None:
    from engine.social import growth, relationships

    pid = _pid(matched)
    _force_stage(receipts_state, pid, "exclusive")
    real = growth.willing
    monkeypatch.setattr(growth, "willing", lambda s, p, c: (False, "not_yet") if c == "propose" else real(s, p, c))
    assert "propose" not in relationships.legal_proposals(receipts_state, pid)
    monkeypatch.setattr(growth, "willing", lambda s, p, c: (True, "") if c == "propose" else real(s, p, c))
    assert "propose" in relationships.legal_proposals(receipts_state, pid)
    made = relationships.apply_proposal(receipts_state, pid, "propose")
    assert made["ok"]
    request = receipts_state.social["requests"][made["request_id"]]
    assert (request["from"], request["what"]) == ("them", "propose")
    assert "propose" not in relationships.legal_proposals(receipts_state, pid)          # one ask at a time
    answered = relationships.answer(receipts_state, made["request_id"], "yes")
    assert answered["ok"], answered
    person = receipts_state.social["people"][pid]
    assert person["stage"] == "engaged" and person["engaged_since"] == pytest.approx(person["stage_since"])


def test_their_move_in_proposal_at_engaged_records_the_household(receipts_state, matched, monkeypatch) -> None:
    """m6 again, by their proposal: yes records the household and leaves the stage."""
    from engine.social import relationships

    pid = _pid(matched)
    _force_stage(receipts_state, pid, "engaged")
    _all_willing(monkeypatch)
    assert "move_in" in relationships.legal_proposals(receipts_state, pid)
    made = relationships.apply_proposal(receipts_state, pid, "move_in")
    assert relationships.answer(receipts_state, made["request_id"], "yes")["ok"]
    assert receipts_state.social["household"] == pid
    assert receipts_state.social["people"][pid]["stage"] == "engaged"


def test_the_players_asks_move_in_and_propose(receipts_state, matched, monkeypatch) -> None:
    """The phone's asks: offered by where they stand, decided at their read (`ask_decision`), settled through
    the household and the stage."""
    from engine.social import messaging, relationships

    pid = _pid(matched)
    _force_stage(receipts_state, pid, "exclusive")
    assert relationships.ask_kinds(receipts_state, pid) == ["move_in", "propose"]
    assert {"move_in", "propose"} <= set(messaging.ASKS)
    monkeypatch.setattr(relationships, "accept_draw", lambda s, p, w: True)
    _all_willing(monkeypatch)
    assert relationships.ask_decision(receipts_state, pid, "propose") == {"accept": True, "why": ""}
    request = {"id": "rX", "pid": pid, "what": "propose"}
    receipts_state.social["requests"]["rX"] = {**request, "from": "player", "status": "pending", "at": 0.0,
                                               "thread_id": "", "mult": 1.0, "asks": 1}
    relationships.settle_ask(receipts_state, request, True, receipts_state.world_clock_hours)
    assert receipts_state.social["people"][pid]["stage"] == "engaged"
    assert relationships.ask_kinds(receipts_state, pid) == ["move_in"]               # still no household
    receipts_state.social["requests"]["rY"] = {**request, "id": "rY", "what": "move_in", "from": "player",
                                               "status": "pending", "at": 0.0, "thread_id": "", "mult": 1.0,
                                               "asks": 1}
    relationships.settle_ask(receipts_state, {**request, "id": "rY", "what": "move_in"}, True,
                             receipts_state.world_clock_hours)
    assert receipts_state.social["household"] == pid
    assert receipts_state.social["people"][pid]["stage"] == "engaged"
    assert relationships.ask_kinds(receipts_state, pid) == []
    assert relationships.ask_stage_refusal(receipts_state, pid, "move_in") == "You already live together."
    assert relationships.ask_stage_refusal(receipts_state, pid, "propose") == "You're already engaged."


def test_proposing_in_person_is_a_closer_and_the_evening_goes_on(receipts_state, matched, monkeypatch) -> None:
    from engine.social import scene

    from engine.game.effects import apply_effect
    from engine.social import growth

    pid = _pid(matched)
    _force_stage(receipts_state, pid, "living_together")
    assert apply_effect(receipts_state, {"type": "social_go", "op": "place", "to": "the_anchor"})["ok"]
    scene.open_scene(receipts_state, pid, "the_anchor", kind="drinks")

    real = growth.willing
    monkeypatch.setattr(growth, "willing", lambda s, p, c: (False, "not_yet") if c == "propose" else real(s, p, c))
    assert "propose" not in dict(scene._close_options(receipts_state, scene.current(receipts_state)))
    monkeypatch.setattr(growth, "willing", lambda s, p, c: (True, "") if c == "propose" else real(s, p, c))
    assert "propose" in dict(scene._close_options(receipts_state, scene.current(receipts_state)))
    done = scene.close(receipts_state, "propose")
    assert done["ok"] and done["engaged"] and done["recorded"] == ["propose"]
    person = receipts_state.social["people"][pid]
    assert person["stage"] == "engaged" and person["recorded"] == ["propose"]
    assert scene.current(receipts_state).get("pid") == pid                          # still together this evening
    assert "You ask them to marry you" in scene.receipt_lines(
        receipts_state, [{"skill": "social_close", "intent": {"target": "propose"}, "result": done}])


def test_the_wedding_follows_the_engagement_by_its_days(receipts_state, matched_numbers, monkeypatch) -> None:
    """The `wedding` life row: eligible only `wedding_after_days` after `engaged_since`, with no wedding plan open;
    it queues the registry office plan, and arriving there opens the wedding. The couple have each other's
    numbers (v0.24.0 T15): a bare Matchstick match nobody has written in expires over the fortnight, and an
    expired match is no live person for the daily life draw, so the test passed or failed on when they happened
    to write first."""
    from engine import social
    from engine.game import clock
    from engine.social import events, life, plans, scene, world

    pid = matched_numbers("texts").split(":", 1)[1]
    _force_stage(receipts_state, pid, "engaged")
    _set_person(receipts_state, pid, warmth=90, trust=90)                 # no cold spell while the days pass
    row = life.row_of("person", "wedding")
    after = float(social.data("relationships")["wedding_after_days"])
    engaged = float(receipts_state.social["people"][pid]["engaged_since"])
    assert not life._eligible(receipts_state, pid, row, engaged + 24.0 * (after - 1))
    assert life._eligible(receipts_state, pid, row, engaged + 24.0 * after)
    monkeypatch.setattr(life, "_event_drawn", lambda s, w, r: r.get("id") == "wedding")
    clock.advance_time(receipts_state, engaged + 24.0 * (after + 1) - receipts_state.world_clock_hours)
    wedding = [r for r in plans.open_for(receipts_state, pid) if r["kind"] == plans.WEDDING]
    assert len(wedding) == 1 and plans.place_of(receipts_state, wedding[0]) == "registry_office"
    assert not life._eligible(receipts_state, pid, row, events.daily_at(receipts_state) + 24.0 * 30)   # one at a time
    assert "registry_office" in world._plan_destinations(receipts_state)          # `go` offers it
    arrived = plans.arrive(receipts_state, "registry_office")
    assert arrived.get("scene") == pid, arrived
    assert scene.current(receipts_state)["kind"] == "wedding"
    assert plans.get(receipts_state, wedding[0]["id"])["status"] == "met"


def test_the_wedding_plan_waits_and_stands_in_no_other_plans_way(receipts_state, matched) -> None:
    from engine.social import plans

    pid = _pid(matched)
    _force_stage(receipts_state, pid, "engaged")
    made = plans.make_wedding(receipts_state, pid)
    assert made is not None and plans.make_wedding(receipts_state, pid) is None
    assert not plans._blocked(receipts_state, pid, "soon")
    for _ in range(10):
        plans.on_episode_close(receipts_state, pid)
    assert plans.get(receipts_state, made["id"])["status"] == "open"
    _force_stage(receipts_state, pid, "winding_down")
    assert plans.arrive(receipts_state, "registry_office") == {"quiet": True}      # only while engaged


def test_ending_moves_the_partner_out(receipts_state, matched) -> None:
    from engine.social import relationships

    pid = _pid(matched)
    _force_stage(receipts_state, pid, "living_together")
    _move_in(receipts_state, pid)
    assert relationships.end(receipts_state, pid)["ok"]
    assert receipts_state.social["household"] == ""


def test_cooling_off_and_its_recovery_apply_to_the_long_term(receipts_state, matched) -> None:
    """§12.4: the existing `cold:` rule is the repair. A married couple cools off and warms back to married."""
    from engine import social
    from engine.social import relationships

    pid = _pid(matched)
    _force_stage(receipts_state, pid, "married")
    cold = social.data("relationships")["cold"]
    _set_person(receipts_state, pid, warmth=int(cold["warmth_below"]) - 1, cold_days=int(cold["days"]) - 1,
                last_player_at=receipts_state.world_clock_hours)                    # in touch: not fading
    relationships._daily(receipts_state)
    assert receipts_state.social["people"][pid]["stage"] == "winding_down"
    _set_person(receipts_state, pid, warmth=int(cold["recover_above"]) + 1)
    for _ in range(int(cold["recover_days"])):
        relationships._daily(receipts_state)
    assert receipts_state.social["people"][pid]["stage"] == "married"


def test_seen_needs_a_partner_and_another_person(receipts_state, matched, monkeypatch) -> None:
    from engine.social import life, relationships

    drawn: list[bool] = []
    monkeypatch.setattr(life, "_seen_drawn", lambda s: drawn.append(True) or True)
    partner = _pid(matched)
    _force_stage(receipts_state, partner, "dating")
    assert life.seen_check(receipts_state, "nobody") == [] and drawn == []           # not together: no draw
    _force_stage(receipts_state, partner, "engaged")
    assert life.seen_check(receipts_state, partner) == [] and drawn == []            # with the partner: no draw
    found = life.seen_check(receipts_state, "someone_else")
    assert found == [partner] and drawn == [True]
    person = receipts_state.social["people"][partner]
    assert relationships.mood_now(person, receipts_state.world_clock_hours) == "hurt"
    from engine.social import memory

    assert any(h.get("text") == "They found out" for h in memory.part(person, "history") or ())
    monkeypatch.setattr(life, "_seen_drawn", lambda s: False)
    assert life.seen_check(receipts_state, "someone_else") == []                     # not seen: nothing moves


def test_a_scenes_end_asks_whether_they_were_seen(receipts_state, matched, monkeypatch) -> None:
    from engine.social import life, scene

    partner = _pid(matched)
    other = _pid(matched, "front_porch")
    _force_stage(receipts_state, partner, "exclusive")
    asked: list[str] = []
    monkeypatch.setattr(life, "seen_check", lambda s, p: asked.append(p) or [])
    scene.open_scene(receipts_state, other, "the_anchor", kind="drinks")
    scene.end_scene(receipts_state, "player", then="stay")
    assert asked == [other]


# -- the narrator, the voice, the data -----------------------------------------------------------------------


def test_the_narrator_is_told_of_the_household_and_handed_the_partner_at_home(receipts_state, matched,
                                                                              monkeypatch) -> None:
    from engine.social import scene, world

    pid = _pid(matched)
    name = scene._name(receipts_state, pid)
    assert "lives with you" not in world.narration_block(receipts_state)
    _force_stage(receipts_state, pid, "living_together")
    _move_in(receipts_state, pid)
    _at_home(receipts_state, monkeypatch, "work")
    block = world.narration_block(receipts_state)
    assert f"{name} lives with you, and is at work." in block and "WITH YOU IN PERSON" not in block
    assert scene.present_pid(receipts_state) == ""
    _at_home(receipts_state, monkeypatch, "free")
    block = world.narration_block(receipts_state)
    assert f"{name} lives with you, and is home." in block
    assert f"WITH YOU IN PERSON: {name}" in block and "This moment: the two of you are at home." in block
    assert scene.present_pid(receipts_state) == pid


def test_you_and_them_lists_moving_in_and_proposing_when_willing(receipts_state, matched, monkeypatch) -> None:
    import dataclasses

    from engine.social import growth, voicing

    pid = _pid(matched)
    _force_stage(receipts_state, pid, "exclusive")
    real = growth.willing
    monkeypatch.setattr(growth, "willing",
                        lambda s, p, c: (True, "") if c in ("move_in", "propose") else real(s, p, c))
    from engine.social import agreement

    willing = agreement.willing_now(receipts_state, pid)
    assert {"move_in", "propose"} <= willing
    snap = voicing.PersonSnapshot(pid=pid, thread_id="", profile={}, dynamic=dict(
        receipts_state.social["people"][pid]), tail=[], summary="", due=[], proposals=(), player={}, now={"at": 0.0},
        contacts=(), seed=1, willing=tuple(sorted(willing)))
    text = voicing._you_and_them(snap)
    assert "moving in together" in text and "getting engaged" in text
    assert "You live together" not in text
    assert "You live together, in their flat." in voicing._you_and_them(dataclasses.replace(snap, lives_together=True))
    assert voicing.PROPOSAL_WORDS["move_in"] and voicing.PROPOSAL_WORDS["propose"]


def test_moving_in_is_taken_only_with_the_household(receipts_state, matched) -> None:
    """m6 in the fact checks: an engaged couple has not moved in unless the household says so."""
    from engine.social import agreement

    pid = _pid(matched)
    _force_stage(receipts_state, pid, "engaged")
    assert "move_in" not in agreement.scene_view(receipts_state, pid).willing
    assert "propose" in agreement.scene_view(receipts_state, pid).willing
    _move_in(receipts_state, pid)
    assert "move_in" in agreement.scene_view(receipts_state, pid).willing


def test_no_stage_row_carries_an_unread_gate(receipts_active) -> None:
    """A gate is read only for a stage reached `automatic`, by `ask` or by `branch` (`can_reach`, `ask_decision`):
    v0.22's `meeting` gate (warmth 70, trust 70) was read by nothing once a scene moved `numbers` to `meeting`,
    so it is gone, and such a gate refuses to load."""
    import copy

    from engine import social
    from engine.social import relationships

    data = social.data("relationships")
    for name, row in data["stages"].items():
        if row.get("gate"):
            assert row.get("trigger") in relationships.GATED_TRIGGERS, name
    assert "gate" not in data["stages"]["meeting"]
    assert data["stages"]["married"]["trigger"] == "event" and "gate" not in data["stages"]["married"]
    bad = copy.deepcopy(data)
    bad["stages"]["meeting"]["gate"] = {"warmth": 70, "trust": 70}
    with pytest.raises(ValueError, match=r"stages\.meeting\.gate: .*read by nothing"):
        relationships.check_data(bad)


def test_the_long_term_stages_are_reached_as_the_spec_says(receipts_active) -> None:
    from engine import social

    stages = social.data("relationships")["stages"]
    assert (stages["living_together"]["from"], stages["living_together"]["gate"]) == (["exclusive"], {"willing": "move_in"})
    assert (stages["engaged"]["from"], stages["engaged"]["gate"]) == (["exclusive", "living_together"],
                                                                    {"willing": "propose"})
    assert stages["married"]["from"] == ["engaged"]


def test_the_household_effect_holds_one_partner(receipts_state, matched) -> None:
    from engine.game.effects import apply_effect

    a, b = _pid(matched), _pid(matched, "front_porch")
    _move_in(receipts_state, a)
    refused = apply_effect(receipts_state, {"type": "social_household", "op": "move_in", "pid": b})
    assert not refused["ok"] and receipts_state.social["household"] == a
    assert not apply_effect(receipts_state, {"type": "social_household", "op": "move_out", "pid": b})["ok"]
    assert apply_effect(receipts_state, {"type": "social_household", "op": "move_out", "pid": a})["ok"]
    assert receipts_state.social["household"] == ""
    assert not apply_effect(receipts_state, {"type": "social_household", "op": "move_in", "pid": "nobody"})["ok"]


# -- fix round 1 (review I1-I3, M1-M3) ---------------------------------------------------------------------------


def _living_together(state, matched, app: str = "matchstick") -> str:
    pid = _pid(matched, app)
    _force_stage(state, pid, "living_together")
    _move_in(state, pid)
    return pid


def _nobody_lives_here(state, pid: str, other: str, monkeypatch) -> None:
    """The household is empty, the narrator's household line is gone, and someone else can move in later."""
    from engine.social import relationships, scene, world

    assert state.social["household"] == ""
    _at_home(state, monkeypatch, "free")
    assert "lives with you" not in world.narration_block(state)
    assert scene.household_present(state) == "" and scene.present_pid(state) == ""
    _force_stage(state, other, "exclusive")
    assert "move_in" in relationships.ask_kinds(state, other)


def test_unmatching_the_live_in_partner_moves_them_out(receipts_state, matched, monkeypatch) -> None:
    """I1: an unmatch is an end: the household records their moving out (`social_household`)."""
    from engine.social import matching

    pid = _living_together(receipts_state, matched)
    other = _pid(matched, "front_porch")
    assert matching.unmatch(receipts_state, pid, by="player")["ok"]
    _nobody_lives_here(receipts_state, pid, other, monkeypatch)


def test_blocking_the_live_in_partner_moves_them_out(receipts_state, matched, monkeypatch) -> None:
    from engine.social import matching

    pid = _living_together(receipts_state, matched)
    other = _pid(matched, "front_porch")
    assert matching.block(receipts_state, pid)["ok"]
    _nobody_lives_here(receipts_state, pid, other, monkeypatch)


def test_their_unmatch_moves_them_out(receipts_state, matched, monkeypatch) -> None:
    from engine.game.effects import apply_effect

    pid = _living_together(receipts_state, matched)
    other = _pid(matched, "front_porch")
    assert apply_effect(receipts_state, {"type": "social_unmatch", "pid": pid, "by": "them"})["ok"]
    _nobody_lives_here(receipts_state, pid, other, monkeypatch)


@pytest.mark.parametrize("stage", ["ended", "faded", "expired"])
def test_ending_or_fading_moves_the_partner_out_and_the_line_goes(receipts_state, matched, monkeypatch,
                                                                  stage) -> None:
    pid = _living_together(receipts_state, matched)
    other = _pid(matched, "front_porch")
    _force_stage(receipts_state, pid, stage)
    _nobody_lives_here(receipts_state, pid, other, monkeypatch)


def test_the_household_partner_never_moves_house(receipts_state, matched) -> None:
    """I2: `moved_house` (a `home: redraw` row) is not drawn for the partner who lives with the player
    (life._eligible's rule): they live in the player's flat now."""
    from engine.social import life

    pid = _pid(matched)
    _force_stage(receipts_state, pid, "living_together")
    row = life.row_of("person", "moved_house")
    now = receipts_state.world_clock_hours
    assert life._eligible(receipts_state, pid, row, now)
    _move_in(receipts_state, pid)
    assert not life._eligible(receipts_state, pid, row, now)
    assert life._eligible(receipts_state, pid, life.row_of("person", "new_pet"), now)   # other rows still run


def test_their_place_is_no_plan_with_the_household_partner(receipts_state, matched, monkeypatch) -> None:
    """I2: no `their_place` plan with the partner who lives with the player: the engine makes none, and the
    player's ask is refused in the engine's words."""
    from engine.social import messaging, plans, relationships

    pid = _living_together(receipts_state, matched)
    monkeypatch.setattr(plans, "_why_not", lambda s, p, w, at: "")
    assert plans.make(receipts_state, pid, kind="their_place", when="soon") is None
    assert plans.ask_refusal(receipts_state, pid, "soon", kind="their_place").endswith("lives with you.")
    assert plans.ask_refusal(receipts_state, pid, "soon", kind="your_place") == ""
    tid = messaging.thread_for(receipts_state, pid)
    asked = relationships.ask(receipts_state, tid, "meet", {"kind": "their_place", "when": "soon"})
    assert not asked["ok"] and "lives with you" in str(asked)
    assert plans.make(receipts_state, pid, kind="your_place", when="soon") is not None


def test_a_plan_at_their_old_home_lapses_when_they_move_in(receipts_state, matched, monkeypatch) -> None:
    from engine.social import plans

    pid = _pid(matched)
    _force_stage(receipts_state, pid, "exclusive")
    monkeypatch.setattr(plans, "_why_not", lambda s, p, w, at: "")
    made = plans.make(receipts_state, pid, kind="their_place", when="soon")
    assert made is not None
    _move_in(receipts_state, pid)
    assert plans.get(receipts_state, made["id"])["status"] == "lapsed"


def test_moving_in_from_together_writes_one_history_row(receipts_state, matched, monkeypatch) -> None:
    """M1: the household's "Moved in together", not the stage's own row as well."""
    from engine.social import memory, relationships

    pid = _pid(matched)
    _all_willing(monkeypatch)
    _force_stage(receipts_state, pid, "exclusive")
    before = len(memory.part(receipts_state.social["people"][pid], "history") or ())
    relationships.apply_move_in(receipts_state, pid)
    rows = list(memory.part(receipts_state.social["people"][pid], "history") or ())
    assert len(rows) == before + 1 and rows[-1]["text"] == "Moved in together"
    assert receipts_state.social["people"][pid]["stage"] == "living_together"


@pytest.mark.parametrize("how", ["faded", "ended", "expired", "blocked"])
def test_the_wedding_plan_is_called_off_when_the_partner_goes(receipts_state, matched, how) -> None:
    """M2: a wedding plan does not outlive the relationship."""
    from engine.social import matching, plans

    pid = _pid(matched)
    _force_stage(receipts_state, pid, "engaged")
    made = plans.make_wedding(receipts_state, pid)
    assert made is not None
    if how == "blocked":
        assert matching.block(receipts_state, pid)["ok"]
    else:
        _force_stage(receipts_state, pid, how)
    assert plans.get(receipts_state, made["id"])["status"] == "cancelled"


# -- I3: the at-home checks on run_turn's shared path ------------------------------------------------------------


@pytest.fixture
def at_home(receipts_active, monkeypatch):
    """A live session with the household partner at home and free (convo._status forced), no scene open, the
    storyteller a stub (F2)."""
    from engine.game.effects import apply_effect
    from engine.social import convo
    from tests.social_fixtures import _live_session, _matched_in
    from tests.social_world_stub import StubNarrator

    _, session = _live_session(llm_fn=StubNarrator())
    state = session.engine.state
    pid = _matched_in(session, "matchstick").split(":")[1]
    _force_stage(state, pid, "living_together")
    _move_in(state, pid)
    state.social["phone_up"] = False
    assert apply_effect(state, {"type": "social_go", "op": "place", "to": "apt_lounge"})["ok"]
    monkeypatch.setattr(convo, "_status", lambda s, p, at: "free")
    return session, state, pid


def _home_turn(session):
    from engine.scenes.default_scene import run_guarded

    payload, error, busy = run_guarded(session, "Watch something", {"action": "do", "target": "watch_something"})
    assert payload is not None, error
    return payload


def test_see_you_tonight_at_home_passes_the_home_checks(at_home) -> None:
    """I3: at home with no scene open only the facts that cannot misfire on home talk are held to the prose;
    "see you tonight" between people who live together is no plan claimed."""
    from engine import social
    from engine.social import scene
    from tests.social_world_stub import StubNarrator

    session, state, pid = at_home
    assert scene.present_pid(state) == pid and not social.scene_open(state)
    name = scene._name(state, pid)
    narrator = StubNarrator(narration=f'"See you tonight," {name} says, and heads out to the shop.')
    session.storyteller.llm_fn = narrator
    payload = _home_turn(session)
    assert narrator.calls == 1 and payload["narration"].startswith('"See you tonight,"')


def test_a_profile_contradiction_at_home_is_still_retried(at_home) -> None:
    from engine.social import life, scene
    from tests.social_world_stub import StubNarrator

    session, state, pid = at_home
    name = scene._name(state, pid)
    age = int(life.person_now(state, pid).age)
    narrator = StubNarrator(narration=f'"I\'m {age + 7}," {name} says.')
    session.storyteller.llm_fn = narrator
    _home_turn(session)
    assert narrator.calls == 2


def test_the_home_checks_are_the_three_facts(receipts_active) -> None:
    from engine.social import agreement

    assert agreement.HOME_PROSE_CHECKS == ("profile_contradicted", "another_person", "stage_claimed")
    assert set(agreement.HOME_PROSE_CHECKS) < set(agreement.SCENE_PROSE_CHECKS)


def test_a_partner_who_goes_out_mid_turn_leaves_no_at_home_line(at_home, monkeypatch) -> None:
    """M3: the partner is free as the turn begins and out once the intent has run: the turn's prompt is not told
    "You are with them, in person: at home." beside the household line that says they are out."""
    from engine.social import convo, scene
    from tests.social_world_stub import StubNarrator

    session, state, pid = at_home
    began = state.world_clock_hours
    monkeypatch.setattr(convo, "_status", lambda s, p, at: "free" if at <= began + 1e-6 else "out")
    name = scene._name(state, pid)
    narrator = StubNarrator(narration="You put something on and watch it.")
    session.storyteller.llm_fn = narrator
    _home_turn(session)
    assert state.world_clock_hours > began
    assert f"{name} lives with you, and is out." in narrator.prompts[0]
    assert f"You are with {name}, in person: at home." not in narrator.prompts[0]
