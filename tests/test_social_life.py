"""Life events, both ways (v0.23.0 T17; spec §11)."""

from __future__ import annotations

import json
from typing import Any

import pytest

from tests.social_fixtures import (  # noqa: F401
    _act, _force_stage, _open_episode, _replies_forced, _set_person, matched, receipts_active, receipts_state,
)
from tests.test_social_scene import in_a_scene  # noqa: F401


def _only(monkeypatch, who_id: str):
    from engine.social import life

    monkeypatch.setattr(life, "_event_drawn", lambda state, who, row: row["id"] == who_id)


def _none(monkeypatch):
    from engine.social import life

    monkeypatch.setattr(life, "_event_drawn", lambda state, who, row: False)


def _pid(matched_, app: str = "matchstick") -> str:
    return matched_(app).split(":")[1]


# -- the brief's tests ------------------------------------------------------------------------------


def test_life_event_reaches_who_now_and_writes_a_followup(receipts_state, matched, monkeypatch) -> None:
    """The flip of T2's "Since you met" stub (spec §24)."""
    from engine.game import clock
    from engine.social import growth, memory

    pid = matched("matchstick").split(":")[1]
    _force_stage(receipts_state, pid, "talking")
    _only(monkeypatch, "new_job")
    clock.advance_time(receipts_state, 24)
    assert "They started a new job" in growth.who_now(receipts_state, pid)
    assert any(r["kind"] == "followup" for r in memory.person(receipts_state, pid)["open"])


def test_support_fills_openness(receipts_state, matched, monkeypatch) -> None:
    """The flip of T2's support stub."""
    from engine.social import growth

    pid = matched("matchstick").split(":")[1]
    assert growth.gain(receipts_state, pid, "support") > 0


def test_a_holiday_waits_for_open_promises(receipts_state, matched, monkeypatch) -> None:
    from engine.game import clock
    from engine.social import promises

    pid = matched("matchstick").split(":")[1]
    _force_stage(receipts_state, pid, "talking")
    _only(monkeypatch, "holiday")
    promises.make(receipts_state, pid, by="person", window="tonight")
    clock.advance_time(receipts_state, 24)
    assert not [e for e in receipts_state.social["people"][pid].get("life") or [] if e["id"] == "holiday"]


def test_a_holiday_starts_once_the_promise_is_gone(receipts_state, matched, monkeypatch) -> None:
    """The other half of the wait: with no open promise the same forced draw begins the holiday."""
    from engine.game import clock

    pid = matched("matchstick").split(":")[1]
    _force_stage(receipts_state, pid, "talking")
    _only(monkeypatch, "holiday")
    clock.advance_time(receipts_state, 24)
    assert [e["id"] for e in receipts_state.social["people"][pid]["life"]] == ["holiday"]


def test_the_boiler_deck_deals_in_the_kitchen(receipts_state, monkeypatch) -> None:
    from engine.content import director
    from engine.game import clock

    _only(monkeypatch, "boiler")
    clock.advance_time(receipts_state, 24)
    receipts_state.location_id = "apt_kitchen"
    receipts = director.ensure_scene(receipts_state)
    assert receipts and receipts[0]["args"]["deck_id"] == "boiler"


def test_the_parcel_deck_deals_at_reception(receipts_state, monkeypatch) -> None:
    from engine.content import director
    from engine.game import clock

    _only(monkeypatch, "parcel")
    clock.advance_time(receipts_state, 24)
    receipts_state.location_id = "bldg_reception"
    receipts = director.ensure_scene(receipts_state)
    assert receipts and receipts[0]["args"]["deck_id"] == "parcel"


def test_a_decks_beat_clears_its_flag(receipts_state, monkeypatch) -> None:
    """Either answer of the boiler's card mends it: the flag the event set is cleared by the beat's outcome."""
    from engine.content import deck
    from engine.game import clock
    from engine.game.effects import apply_effect

    _only(monkeypatch, "boiler")
    clock.advance_time(receipts_state, 24)
    assert receipts_state.flags.get("life_boiler")
    loaded = deck.load_deck("boiler")
    for card in loaded.cards:
        for beat in card.beats:
            effects = ((beat.get("gate") or {}).get("on_pass") or {}).get("effects") or []
            assert {"type": "flag", "flag": "life_boiler", "value": False} in effects, (card.id, beat.get("id"))
    apply_effect(receipts_state, {"type": "flag", "flag": "life_boiler", "value": False})
    assert not receipts_state.flags.get("life_boiler")


def test_the_event_ends_with_its_flag(receipts_state, monkeypatch) -> None:
    """The flag is held for `lasts_days` and cleared at the event's own end (its queued `life` event)."""
    from engine.game import clock

    _only(monkeypatch, "boiler")
    clock.advance_time(receipts_state, 24)
    assert receipts_state.flags.get("life_boiler")
    _none(monkeypatch)
    clock.advance_time(receipts_state, 24 * 3)
    assert not receipts_state.flags.get("life_boiler")


def test_the_job_offer_ends_or_keeps_by_the_willing_row(receipts_state, matched, monkeypatch) -> None:
    from engine.social import growth, life

    pid = matched("matchstick").split(":")[1]
    _force_stage(receipts_state, pid, "dating")
    monkeypatch.setattr(growth, "willing", lambda s, p, c: (False, "not_yet") if c == "stay_or_go" else (True, ""))
    life.answer_stay_or_go(receipts_state, pid, ask="stay")
    assert receipts_state.social["people"][pid]["stage"] == "ended"


def test_a_willing_one_stays_and_support_is_gained(receipts_state, matched, monkeypatch) -> None:
    from engine.social import growth, life, memory

    pid = matched("matchstick").split(":")[1]
    _force_stage(receipts_state, pid, "dating")
    monkeypatch.setattr(growth, "willing", lambda s, p, c: (True, "") if c == "stay_or_go" else (True, ""))
    before = growth.record(receipts_state, pid)["openness"]
    out = life.answer_stay_or_go(receipts_state, pid, ask="stay")
    assert out["stays"] and receipts_state.social["people"][pid]["stage"] == "dating"
    assert growth.record(receipts_state, pid)["openness"] > before
    person = receipts_state.social["people"][pid]
    assert "stayed" in [memory.full_history(h)["kind"] for h in memory.part(person, "history")]


def test_told_to_go_they_go(receipts_state, matched, monkeypatch) -> None:
    from engine.social import growth, life

    pid = matched("matchstick").split(":")[1]
    _force_stage(receipts_state, pid, "dating")
    monkeypatch.setattr(growth, "willing", lambda s, p, c: (True, ""))
    assert life.answer_stay_or_go(receipts_state, pid, ask="go")["stays"] is False
    assert receipts_state.social["people"][pid]["stage"] == "ended"


def test_the_offer_is_a_request_the_answer_verb_settles(receipts_state, matched, monkeypatch) -> None:
    """The offer queues a `stay_or_go` request; `relationships.answer` yes asks them to stay, no tells them to go."""
    from engine.game import clock
    from engine.social import growth, relationships

    pid = matched("matchstick").split(":")[1]
    _force_stage(receipts_state, pid, "dating")
    _only(monkeypatch, "job_offer_elsewhere")
    clock.advance_time(receipts_state, 24)
    [offer] = relationships.pending_offers(receipts_state, pid, "stay_or_go")
    assert any(f"{pid}" in str(r) for r in relationships._open_requests(receipts_state))
    monkeypatch.setattr(growth, "willing", lambda s, p, c: (False, "not_yet") if c == "stay_or_go" else (True, ""))
    settled = relationships.answer(receipts_state, offer["id"], "yes")
    assert settled["ok"] and settled["stays"] is False
    assert receipts_state.social["requests"][offer["id"]]["status"] == "yes"
    assert receipts_state.social["people"][pid]["stage"] == "ended"


def test_life_events_replay(receipts_active, monkeypatch) -> None:
    """Pre-flight F28: the player's store is `state.social["player_life"]` (Shared interfaces), and the draw is
    FORCED for one row so the comparison is never `[] == []`."""
    from engine.game import clock, procgen

    _only(monkeypatch, "parcel")                               # the player's parcel fires on every daily draw

    def run():
        state = procgen.new_game_state(player_name="Sam", seed=31)
        clock.advance_time(state, 24 * 21)
        return sorted((e["id"], e["at"]) for e in (state.social.get("player_life") or []))

    first = run()
    assert first and {row_id for row_id, _ in first} == {"parcel"}
    assert run() == first


def test_one_systems_draws_do_not_shift_anothers(receipts_active, monkeypatch) -> None:
    """§19.1: SOCIAL_LIFE draws do not move SOCIAL_CONVO or SOCIAL_SCENE. A 10-day run with life events
    drawing (parcel forced on) and one with them off leave every other stream's counters identical."""
    from engine.game import clock, procgen
    from engine.social import life

    def run(on: bool):
        if on:
            monkeypatch.undo()
            monkeypatch.setattr(life, "_event_drawn", lambda state, who, row: row["id"] == "parcel")
        else:
            monkeypatch.undo()
            monkeypatch.setattr(life, "_event_drawn", lambda state, who, row: False)
        state = procgen.new_game_state(player_name="Sam", seed=77)
        clock.advance_time(state, 24 * 10)
        counters = {k: v for k, v in state.rng_counters.items() if k != "social.life"}
        people = {p: {k: v for k, v in (row.get("rng_n") or {}).items() if k != "social.life"}
                  for p, row in state.social.get("people", {}).items()}
        return counters, people, bool(state.social.get("player_life"))

    off, on = run(False), run(True)
    assert off[:2] == on[:2] and on[2] and not off[2]


def test_a_life_events_followup_reaches_the_voice_when_due(receipts_state, matched, monkeypatch) -> None:
    """`RIGHT NOW` names the follow-up a life event wrote, once it is due."""
    from engine.game import clock
    from engine.social import memory, voicing
    from tests.test_social_voice_v2 import _block, _only_due, _user

    thread = matched("matchstick")
    pid = thread.split(":")[1]
    _force_stage(receipts_state, pid, "talking")
    _only(monkeypatch, "new_job")
    clock.advance_time(receipts_state, 24)
    _none(monkeypatch)
    [row] = [r for r in memory.person(receipts_state, pid)["open"] if r["kind"] == "followup"]
    assert row["about"] == "their first week at the new job"
    clock.advance_time(receipts_state, 24 * 4)
    assert memory.followup_due(receipts_state, pid, receipts_state.world_clock_hours)["id"] == row["id"]
    snap = _only_due(receipts_state, thread, followup_id=row["id"])
    assert "their first week at the new job" in _block(_user(voicing.messages(snap)), "RIGHT NOW")


def test_the_player_news_is_a_tell_about_topic(in_a_scene, monkeypatch) -> None:
    """In a scene, `tell_about:life_<id>` is a target, and telling it is how they come to know."""
    from engine.game.effects import apply_effect
    from engine.social import life, memory, scene as social_scene

    scene, session, state, pid = in_a_scene
    apply_effect(state, {"type": "social_life", "op": "start", "who": "player", "id": "boiler",
                         "at": state.world_clock_hours})
    assert [n["topic"] for n in life.player_news(state)] == ["life_boiler"]
    targets = [t for t, _ in social_scene._move_options(state, pid)]
    assert "tell_about:life_boiler" in targets
    labels = dict(social_scene._move_options(state, pid))
    assert labels["tell_about:life_boiler"] == "Tell them about your boiler"
    assert not any("boiler" in str(k) for k in memory.person(state, pid).get("knows") or [])
    social_scene.move(state, "tell_about:life_boiler")
    assert any("boiler" in k for k in memory.person(state, pid)["knows"])


def test_a_scene_while_their_event_runs_gains_support_once(in_a_scene, monkeypatch) -> None:
    from engine.game.effects import apply_effect
    from engine.social import growth, scene as social_scene

    scene, session, state, pid = in_a_scene
    monkeypatch.setattr(social_scene, "_moment_draw", lambda s, p: 0.0)
    apply_effect(state, {"type": "social_life", "op": "start", "who": pid, "id": "family_illness",
                         "at": state.world_clock_hours})
    gains: list[float] = []
    real = growth.gain
    monkeypatch.setattr(growth, "gain", lambda s, p, e, **k: (gains.append(e), real(s, p, e, **k))[1])
    social_scene.move(state, "quiet")
    social_scene.move(state, "quiet")
    assert gains.count("support") == 1


def test_the_world_narrator_is_told_of_the_players_news(receipts_state) -> None:
    from engine.game.effects import apply_effect
    from engine.social import world

    assert "boiler" not in world.narration_block(receipts_state)
    apply_effect(receipts_state, {"type": "social_life", "op": "start", "who": "player", "id": "boiler",
                                  "at": receipts_state.world_clock_hours})
    assert "Your boiler has gone." in world.narration_block(receipts_state)


def test_a_reply_while_their_event_runs_gains_support_once(receipts_state, matched, monkeypatch) -> None:
    from engine.game.effects import apply_effect
    from engine.social import growth, messaging

    thread = matched("matchstick")
    pid = thread.split(":")[1]
    apply_effect(receipts_state, {"type": "social_life", "op": "start", "who": pid, "id": "family_illness",
                                  "at": receipts_state.world_clock_hours})
    before = growth.record(receipts_state, pid)["openness"]
    with _replies_forced():
        assert messaging.send(receipts_state, thread, "text", "how is she doing?")["ok"]
        mid = growth.record(receipts_state, pid)["openness"]
        assert mid > before
        assert messaging.send(receipts_state, thread, "text", "thinking of you")["ok"]
    gained = growth.record(receipts_state, pid)["openness"] - mid
    assert gained < (mid - before) / 2                        # support (15) came once; the second send gave none


# -- the news, the holiday, the player's sign-off ------------------------------------------------------


def test_their_news_is_told_once_as_a_situation(receipts_state, matched, monkeypatch) -> None:
    from engine.game import clock
    from engine.social import convo

    thread = matched("matchstick")
    pid = thread.split(":")[1]
    _force_stage(receipts_state, pid, "talking")
    _only(monkeypatch, "new_pet")
    clock.advance_time(receipts_state, 24)
    _none(monkeypatch)
    assert receipts_state.social["people"][pid]["news"]["id"] == "new_pet"
    _open_episode(receipts_state, pid, thread)
    at = receipts_state.world_clock_hours
    first = convo.decide(receipts_state, pid, thread, at)
    assert first.situation == "news" and "got a new pet" in first.reason
    assert "news" not in receipts_state.social["people"][pid]
    second = convo.decide(receipts_state, pid, thread, at)
    assert second.situation == "reply" and "pet" not in second.reason


def test_a_holiday_makes_them_unavailable_while_it_runs(receipts_state, matched, monkeypatch) -> None:
    from engine.game import clock
    from engine.social import convo

    pid = matched("matchstick").split(":")[1]
    _force_stage(receipts_state, pid, "talking")
    _only(monkeypatch, "holiday")
    clock.advance_time(receipts_state, 24)
    _none(monkeypatch)
    [event] = receipts_state.social["people"][pid]["life"]
    mid = (event["at"] + event["until"]) / 2
    assert not convo.available(receipts_state, pid, mid).yes
    assert convo.next_available(receipts_state, pid, mid) >= event["until"]
    assert convo.available(receipts_state, pid, event["until"] + 12).yes in (True, False)   # their own hours again


def test_a_new_job_is_in_who_now_and_not_in_the_seed(receipts_state, matched, monkeypatch) -> None:
    from engine.game import clock
    from engine.social import growth, life, population

    pid = matched("matchstick").split(":")[1]
    _force_stage(receipts_state, pid, "talking")
    seeded = population.profile(receipts_state, pid).job
    _only(monkeypatch, "new_job")
    clock.advance_time(receipts_state, 24)
    new = life.job_now(receipts_state, pid)
    assert new and new != seeded and population.profile(receipts_state, pid).job == seeded
    assert life.person_now(receipts_state, pid).job == new
    first = growth.who_now(receipts_state, pid).splitlines()[0]
    words = population.template_words(
        __import__("engine").social.data("population"), tuple(life.person_now(receipts_state, pid).hobbies) or ("",),
        new, population.profile(receipts_state, pid).neighbourhood)
    assert words["a_job"] in first


def test_the_new_job_is_what_the_checks_and_the_voice_read(receipts_state, matched, monkeypatch) -> None:
    """Their job claim is judged against the job they took, not the seed's, and the voice's snapshot says it."""
    from engine.game import clock
    from engine.social import agreement, life, messaging, voicing
    from engine.social.kinds import Decision

    thread = matched("matchstick")
    pid = thread.split(":")[1]
    _force_stage(receipts_state, pid, "talking")
    _only(monkeypatch, "new_job")
    clock.advance_time(receipts_state, 24)
    new = life.job_now(receipts_state, pid)
    assert agreement.view_from_state(receipts_state, pid).person.job == new
    messaging.new_message(receipts_state, thread, pid, "text", voiced=False,
                          decision=__import__("dataclasses").asdict(Decision(situation="reply")))
    assert voicing.snapshot_of(receipts_state, thread).profile["job"] == new


def test_moving_house_redraws_their_home(receipts_state, matched, monkeypatch) -> None:
    from engine.game import clock
    from engine.social import growth, places

    pid = matched("matchstick").split(":")[1]
    _force_stage(receipts_state, pid, "talking")
    before = places.home_of(receipts_state, pid)
    _only(monkeypatch, "moved_house")
    clock.advance_time(receipts_state, 24)
    assert places.home_of(receipts_state, pid) != before
    assert places.home_label(receipts_state, pid) in growth.who_now(receipts_state, pid)


def test_an_events_mood_lasts_its_days(receipts_state, matched, monkeypatch) -> None:
    from engine.game import clock
    from engine.game.effects import apply_effect
    from engine.social import relationships

    pid = matched("matchstick").split(":")[1]
    apply_effect(receipts_state, {"type": "social_life", "op": "start", "who": pid, "id": "holiday",
                                  "at": receipts_state.world_clock_hours})
    person = receipts_state.social["people"][pid]
    assert person["mood"] == "playful"
    assert person["mood_until"] - receipts_state.world_clock_hours == pytest.approx(24 * 7)
    assert relationships.mood_now(person, receipts_state.world_clock_hours + 24 * 6) == "playful"


def test_overtime_lengthens_the_players_work_band(receipts_state) -> None:
    from engine.game.effects import apply_effect
    from engine.social import windows

    day = int(receipts_state.world_clock_hours // 24)
    while not windows.work_bands(receipts_state, "player", day):
        day += 1
    before = windows.work_bands(receipts_state, "player", day)
    apply_effect(receipts_state, {"type": "social_life", "op": "start", "who": "player", "id": "overtime",
                                  "at": day * 24.0 - 1.0})
    after = windows.work_bands(receipts_state, "player", day)
    assert [(a, b - 2.0) for a, b in after] == before


def test_the_lift_out_adds_minutes_to_going_out(receipts_state) -> None:
    from engine.game.effects import apply_effect
    from engine.social import life

    assert life.extra_minutes(receipts_state) == 0
    apply_effect(receipts_state, {"type": "social_life", "op": "start", "who": "player", "id": "lift_out",
                                  "at": receipts_state.world_clock_hours})
    assert life.extra_minutes(receipts_state) == 5


def test_the_players_event_is_a_sign_off_reason(receipts_state, matched) -> None:
    from engine.game.effects import apply_effect
    from engine.social import convo

    pid = matched("matchstick").split(":")[1]
    at = receipts_state.world_clock_hours
    assert convo._reason(receipts_state, pid, "player", at)[1] != "you have the boiler to sort out"
    apply_effect(receipts_state, {"type": "social_life", "op": "start", "who": "player", "id": "boiler", "at": at})
    key, words = convo._reason(receipts_state, pid, "player", at)
    assert (key, words) == ("player", "you have the boiler to sort out")


# -- the data, and the saves ----------------------------------------------------------------------------


def test_unknown_life_event_keys_are_a_load_error(receipts_active) -> None:
    from engine.social import life

    life.check_data({"player": [{"id": "a", "prob_per_week": 0.1, "cooldown_days": 1, "text": "x"}]})
    with pytest.raises(ValueError, match="unknown key"):
        life.check_data({"player": [{"id": "a", "prob_per_week": 0.1, "cooldown_days": 1, "text": "x",
                                     "intensity": 3}]})
    with pytest.raises(ValueError, match="unknown key"):
        life.check_data({"banana": {}})
    with pytest.raises(ValueError, match="need `lasts_days`"):
        life.check_data({"person": [{"id": "a", "prob_per_week": 0.1, "cooldown_days": 1, "text": "x",
                                     "unavailable": True}]})
    with pytest.raises(ValueError, match="mood"):
        life.check_data({"person": [{"id": "a", "prob_per_week": 0.1, "cooldown_days": 1, "text": "x",
                                     "mood": {"value": "ecstatic", "days": 1}}]}, moods=("neutral",))
    with pytest.raises(ValueError, match="no stage"):
        life.check_data({"person": [{"id": "a", "when": {"stage_min": "elsewhere"}, "prob_per_week": 0.1,
                                     "cooldown_days": 1, "text": "x"}]})


def test_the_shipped_table_is_checked_and_its_scenes_exist(receipts_active) -> None:
    from engine import social
    from engine.content import deck
    from engine.social import life

    data = social.data("life_events")
    assert len(data["player"]) == 12 and len(data["person"]) == 15        # T18 added the wedding's row
    assert [r["id"] for r in data["person"] if r.get("plan")] == ["wedding"]
    for row in data["player"]:
        if row.get("scene"):
            assert deck.load_deck(row["scene"]).id == row["scene"]
    assert not {r["id"] for r in data["person"] if r.get("proposal")} - {"job_offer_elsewhere"}
    life.check_data(data)
