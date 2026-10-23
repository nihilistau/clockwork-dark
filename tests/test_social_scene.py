"""
Scenes: meet-ups played in person (v0.23.0 T13; spec §10.1-§10.4, §19.3, §19.6's scene guard).

A `now` plan's arrival opens a scene, which owns the narrated turn: the moves (`scene`), the closers
(`close`) and, at the flat, the shared activities (`do`). A move is scored and banded (`lands | fine |
flat | misstep`), moves warmth and trust exactly, fills openness and spends its minutes; a question above
their rung is a scored outcome, never a refusal. The end bands the evening, closes the scene episode
(its recap queued), swaps numbers when it went fine or better, moves `numbers` to `meeting` and queues
their `post_meet` text. Every draw a test depends on is forced (pre-flight F16).

Also here, moved from v0.22's tests/test_social_meets.py when T13 deleted meets.py: the venue pick, the
venues and `meets:` data checks, the branch after two good evenings and `post_meet`'s exceptions.
"""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest

from tests.social_fixtures import (  # noqa: F401
    _force_stage, _live_session, _matched_in, _set_person, matched, numbers_pid, matched_numbers,
    receipts_active, receipts_state, there_already,
)

VENUE = "copper_kettle"


@pytest.fixture
def in_a_scene(receipts_active, monkeypatch):
    """Every draw on the way in is forced (pre-flight F16): willingness, availability now, no boundary,
    no flake, the prior's draw; the storyteller is stubbed from the session's build (F2)."""
    from engine.social import convo, growth, plans, scene as social_scene, world
    from engine.social.convo import Availability
    from tests.social_world_stub import StubNarrator

    scene, session = _live_session(llm_fn=StubNarrator())
    state = session.engine.state
    pid = _matched_in(session, "matchstick").split(":")[1]
    real = growth.willing
    monkeypatch.setattr(growth, "willing", lambda s, p, c: (True, "") if c == "meet" else real(s, p, c))
    monkeypatch.setattr(convo, "available", lambda s, p, at: Availability(True))
    monkeypatch.setattr(convo, "boundary_minutes", lambda s, p, at: None)
    monkeypatch.setattr(plans, "_flake_drawn", lambda s, p: False)
    monkeypatch.setattr(social_scene, "_prior_draw", lambda s, p: 0.0)
    monkeypatch.setattr(plans, "_arrival", there_already)        # T23C: they are there when it is made
    _force_stage(state, pid, "numbers")
    state.social["phone_up"] = False
    plans.make(state, pid, kind="drinks", when="now", venue="the_anchor")
    state.location_id = "merrow_street"
    world.go(state, "the_anchor")
    return scene, session, state, pid


def _as(monkeypatch: pytest.MonkeyPatch, pid: str, **fields: Any) -> None:
    """`pid`'s profile with `fields` replaced (a forced draw, F16)."""
    from engine.social import population

    real = population.profile
    monkeypatch.setattr(population, "profile",
                        lambda s, p: dataclasses.replace(real(s, p), **fields) if p == pid else real(s, p))


def _moments(monkeypatch, band: str) -> None:
    """Every moment, and the evening, forced to `band`'s end (a moment `fine` -> the scene `fine`, etc.)."""
    from engine.social import scene as social_scene

    monkeypatch.setattr(social_scene, "_moment_draw", lambda s, p: 0.0)
    monkeypatch.setattr(social_scene, "_band_of", lambda score: band)
    ends = {"lands": "great", "fine": "fine", "flat": "awkward", "misstep": "bad"}
    monkeypatch.setattr(social_scene, "_scene_band", lambda average: ends[band])


# -- opening, and the turn ----------------------------------------------------------------------------


def test_a_now_plan_opens_a_scene(in_a_scene) -> None:
    """The flip of T12's stub (spec §24's table)."""
    from engine import social

    scene, session, state, pid = in_a_scene
    assert social.scene_open(state) and state.social["scene"]["pid"] == pid
    assert state.social["people"][pid]["episode"]["kind"] == "scene"
    assert [p["status"] for p in state.social["plans"].values()] == ["met"]


def test_a_scene_owns_the_turn(in_a_scene) -> None:
    from engine.game.intents import legal_intents, scene_owns_turn

    scene, session, state, pid = in_a_scene
    assert scene_owns_turn(state)
    actions = {v.action for v in legal_intents(state)}
    assert actions <= {"scene", "close", "do"} and {"scene", "close"} <= actions


def test_go_is_offered_only_through_a_closer_and_each_verb_has_at_most_eight(in_a_scene) -> None:
    from engine.game.intents import legal_intents
    from engine.social import world

    scene, session, state, pid = in_a_scene
    verbs = {v.action: v for v in legal_intents(state)}
    assert "go" not in verbs and world.go_targets(state) == []
    assert all(len(v.options) <= 8 for v in verbs.values())
    assert "call_it_a_night" in verbs["close"].targets and "playful" in verbs["scene"].targets


def test_a_shared_activity_is_offered_at_the_flat_and_done_together(in_a_scene) -> None:
    from engine.game.intents import legal_intents
    from engine.social import world

    scene, session, state, pid = in_a_scene
    state.location_id = "apt_kitchen"                         # a scene at yours (T16 fills the home side)
    verbs = {v.action: v for v in legal_intents(state)}
    assert verbs["do"].targets == ("make_dinner",)
    before = state.world_clock_hours
    done = world.do(state, "make_dinner")
    assert done["ok"] and done["together"] and abs(state.world_clock_hours - before - 40 / 60) < 1e-6


# -- a moment (§10.3) ---------------------------------------------------------------------------------


def test_a_landed_moment_fills_openness(in_a_scene, monkeypatch) -> None:
    """The flip of T2's `moment` stub."""
    from engine.social import growth, scene as social_scene

    scene, session, state, pid = in_a_scene
    monkeypatch.setattr(social_scene, "_moment_draw", lambda s, p: 0.9)
    before = growth.record(state, pid)["openness"]
    result = social_scene.move(state, "playful")
    assert result["band"] == "lands" and growth.record(state, pid)["openness"] > before


def test_a_moment_moves_regard_exactly_and_spends_its_minutes(in_a_scene, monkeypatch) -> None:
    from engine import social
    from engine.social import scene as social_scene

    scene, session, state, pid = in_a_scene
    _set_person(state, pid, warmth=40, trust=40)
    monkeypatch.setattr(social_scene, "_moment_draw", lambda s, p: 0.9)
    at = state.world_clock_hours
    social_scene.move(state, "quiet")                                      # lands: trust +3 exactly
    row = social.data("scenes")["moves"]["quiet"]
    person = state.social["people"][pid]
    assert (person["warmth"], person["trust"]) == (40, 40 + row["bands"]["lands"]["trust"])
    assert abs(state.world_clock_hours - at - row["minutes"] / 60) < 1e-6
    assert state.social["scene"]["moments"][-1]["band"] == "lands"


def test_asking_above_their_rung_is_a_flat_scored_outcome_not_a_refusal(in_a_scene, monkeypatch) -> None:
    from engine.social import growth, scene as social_scene

    scene, session, state, pid = in_a_scene
    deep = next(t for t in growth.topics_of(state, pid) if t["kind"] in growth.RUNGS[3][1])
    result = social_scene.move(state, f"ask_about:{deep['id']}")
    assert result["ok"] is True and result["band"] == "flat" and "error" not in result
    assert "steer" in result["words"]


def test_two_missteps_and_they_close(in_a_scene, monkeypatch) -> None:
    from engine import social
    from engine.social import scene as social_scene

    scene, session, state, pid = in_a_scene
    monkeypatch.setattr(social_scene, "_moment_draw", lambda s, p: -1.0)
    first = social_scene.move(state, "playful")
    assert first["band"] == "misstep" and "closed_by_them" not in first and social.scene_open(state)
    second = social_scene.move(state, "playful")
    assert second["band"] == "misstep" and second["closed_by_them"] == "missteps"
    assert not social.scene_open(state) and state.location_id == "the_anchor"     # they left; you are where you were
    assert state.social["people"][pid]["episode"] is None


def test_their_schedule_closes_the_scene(in_a_scene, monkeypatch) -> None:
    from engine import social
    from engine.social import convo, scene as social_scene

    scene, session, state, pid = in_a_scene
    monkeypatch.setattr(social_scene, "_moment_draw", lambda s, p: 0.2)
    monkeypatch.setattr(convo, "boundary_minutes", lambda s, p, at: 5.0)
    assert social_scene.move(state, "quiet")["closed_by_them"] == "schedule"
    assert not social.scene_open(state)


def test_a_phone_out_in_company_costs_someone_who_minds(in_a_scene, monkeypatch) -> None:
    from engine.social import attrs, scene as social_scene, world

    scene, session, state, pid = in_a_scene
    _set_person(state, pid, warmth=40, trust=40)
    real = attrs.of
    monkeypatch.setattr(attrs, "of", lambda s, p: {**real(s, p), "habits": {**real(s, p)["habits"],
                                                                            "in_company": "rude_not_to"}})
    world.pick_up(state)
    assert state.social["people"][pid]["warmth"] == 37                        # the phone move's misstep row
    monkeypatch.setattr(social_scene, "_moment_draw", lambda s, p: 0.9)
    assert social_scene.move(state, "phone")["band"] == "misstep"            # they mind, whatever the draw


# -- the end (§10.4) ----------------------------------------------------------------------------------


def test_call_it_a_night_goes_home(in_a_scene) -> None:
    from engine import social
    from engine.social import scene as social_scene

    scene, session, state, pid = in_a_scene
    social_scene.close(state, "call_it_a_night")
    assert not social.scene_open(state) and state.location_id == "apt_lounge"
    assert state.social["people"][pid]["recap_due"][-1]["kind"] == "scene"


def test_call_it_a_night_and_stay_leaves_the_way_home_open(in_a_scene) -> None:
    from engine.game.intents import legal_intents
    from engine.social import scene as social_scene

    scene, session, state, pid = in_a_scene
    social_scene.close(state, "call_it_a_night:stay")
    assert state.location_id == "the_anchor"
    go = next(v for v in legal_intents(state) if v.action == "go")
    assert go.targets[0] == "apt_lounge"


def test_a_scene_ending_fine_swaps_numbers(in_a_scene, monkeypatch) -> None:
    from engine.social import matching, scene as social_scene

    scene, session, state, pid = in_a_scene
    _force_stage(state, pid, "talking")
    _moments(monkeypatch, "fine")
    for target in ("playful", "quiet"):
        social_scene.move(state, target)
    social_scene.close(state, "call_it_a_night")
    assert matching.thread_id("texts", pid) in state.social["threads"]
    assert state.social["people"][pid]["stage"] == "meeting"


def test_an_awkward_scene_swaps_no_numbers(in_a_scene, monkeypatch) -> None:
    from engine.social import matching, scene as social_scene

    scene, session, state, pid = in_a_scene
    _force_stage(state, pid, "talking")
    _moments(monkeypatch, "flat")
    social_scene.move(state, "quiet")
    social_scene.close(state, "call_it_a_night")
    assert matching.thread_id("texts", pid) not in state.social["threads"]
    assert state.social["people"][pid]["stage"] == "talking"


def test_post_meet_is_queued_at_their_next_window(in_a_scene, monkeypatch) -> None:
    from engine.social import convo, scene as social_scene

    scene, session, state, pid = in_a_scene
    _as(monkeypatch, pid, archetype="steady")
    _moments(monkeypatch, "lands")
    social_scene.move(state, "playful")
    plan_id = state.social["scene"]["plan_id"]
    ended = state.world_clock_hours
    social_scene.close(state, "call_it_a_night:stay")
    due = [e for e in state.social["queue"] if (e.get("decision") or {}).get("situation") == "post_meet"]
    assert len(due) == 1 and due[0]["pid"] == pid and due[0]["decision"]["plan_id"] == plan_id
    assert due[0]["at"] >= ended and due[0]["at"] == convo.next_available(state, pid, due[0]["at"])
    assert state.social["plans"][plan_id]["band"] == "great"


@pytest.mark.parametrize(("band", "archetype", "sent"), [("misstep", "steady", False), ("lands", "ghoster", False),
                                                         ("lands", "steady", True)])
def test_a_bad_scene_or_a_ghoster_sends_no_post_meet(in_a_scene, monkeypatch, band, archetype, sent) -> None:
    """Moved from v0.22's meets tests: `post_meet.none_after` (bad) and `none_from` (ghoster) still hold."""
    from engine.social import scene as social_scene

    scene, session, state, pid = in_a_scene
    _as(monkeypatch, pid, archetype=archetype)
    _moments(monkeypatch, band)
    social_scene.move(state, "quiet")
    if social_scene.current(state):
        social_scene.close(state, "call_it_a_night:stay")
    queued = [e for e in state.social["queue"] if (e.get("decision") or {}).get("situation") == "post_meet"]
    assert bool(queued) is sent


@pytest.mark.parametrize(("intent", "stage"), [("long_term", "dating"), ("friendship", "friends")])
def test_two_good_scenes_move_meeting_to_its_branch(in_a_scene, monkeypatch, intent, stage) -> None:
    """Moved from v0.22's meets tests: two good-or-better evenings branch `meeting` (`meets_good`)."""
    from engine.social import plans, scene as social_scene, world

    scene, session, state, pid = in_a_scene
    _as(monkeypatch, pid, archetype="steady", intent=intent)
    state.social["player"]["looking_for"] = intent
    _moments(monkeypatch, "lands")
    social_scene.move(state, "playful")
    social_scene.close(state, "call_it_a_night")
    person = state.social["people"][pid]
    assert person["stage"] == "meeting" and person["meets_good"] == 1 and person["scenes_done"] == 1
    plans.make(state, pid, kind="coffee", when="now", venue=VENUE)
    world.go(state, VENUE)
    social_scene.move(state, "playful")
    social_scene.close(state, "call_it_a_night")
    assert person["stage"] == stage and person["meets_good"] == 2
    kinds = [h["kind"] for h in person["memory"]["history"]]
    assert kinds.count("scene") == 2


def test_back_to_yours_needs_come_over(in_a_scene, monkeypatch) -> None:
    from engine import social
    from engine.social import growth, scene as social_scene

    scene, session, state, pid = in_a_scene
    targets = dict(social_scene._close_options(state, state.social["scene"]))
    assert "back_to_yours" not in targets                                    # stage numbers, no scene done yet
    real = growth.willing
    monkeypatch.setattr(growth, "willing", lambda s, p, c: (True, "") if c in ("meet", "come_over") else real(s, p, c))
    assert "back_to_yours" in dict(social_scene._close_options(state, state.social["scene"]))
    done = social_scene.close(state, "back_to_yours")
    assert done["ok"] and done["recorded"] == ["come_over"]
    assert state.location_id == "apt_lounge" and social.scene_open(state) and state.social["scene"]["pid"] == pid
    assert state.social["scene"]["kind"] == "your_place"
    assert state.social["people"][pid]["recorded"] == ["come_over"]


def test_a_closer_not_on_offer_is_refused_and_a_promise_is_kept_by_the_engine(in_a_scene) -> None:
    from engine.social import scene as social_scene

    scene, session, state, pid = in_a_scene
    assert social_scene.close(state, "stay_the_night")["ok"] is False           # T16's
    done = social_scene.close(state, "call_it_a_night:promise:morning")
    assert done["ok"] and done["promise_id"] in state.social["promises"]
    row = state.social["promises"][done["promise_id"]]
    assert (row["by"], row["window"], row["pid"]) == ("player", "morning", pid)


def test_another_round_gives_energy_back_and_costs_its_minutes(in_a_scene) -> None:
    from engine import social
    from engine.social import scene as social_scene

    scene, session, state, pid = in_a_scene
    state.social["scene"]["energy"] = 10.0
    at = state.world_clock_hours
    social_scene.close(state, "another_round")
    rules = social.data("scenes")["close"]
    assert state.social["scene"]["energy"] == pytest.approx(10.0 + 100.0 * rules["another_round_energy"])
    assert abs(state.world_clock_hours - at - rules["another_round_minutes"] / 60) < 1e-6


def test_a_scene_episode_never_lapses(in_a_scene) -> None:
    from engine.game import clock

    scene, session, state, pid = in_a_scene
    clock.advance_time(state, 2.0)
    assert state.social["people"][pid]["episode"] is not None


def test_a_scene_replays(receipts_active, monkeypatch) -> None:
    from tests.social_fixtures import _scripted_scene

    first = _scripted_scene(seed=9)
    assert first and first == _scripted_scene(seed=9)


# -- the turn's narration, the payload, the narrator -----------------------------------------------------


def test_the_scene_section_carries_words_and_no_numbers(in_a_scene) -> None:
    """Pre-flight F18 (the payload T23's Companion reads), lesson 7: sentinel VALUES planted, then absent."""
    import json

    from engine.social import payload

    scene, session, state, pid = in_a_scene
    _set_person(state, pid, warmth=61.987654, trust=48.123457)
    block = payload.phone_block(state)
    assert set(block["scene"]) == {"pid", "name", "stage_words", "closeness_words", "portrait", "kind", "id"}
    assert block["scene"]["pid"] == pid
    text = json.dumps(block["scene"], default=str)
    for sentinel in ("61.987654", "48.123457"):
        assert sentinel not in text


def test_the_scene_section_is_empty_with_no_scene(receipts_state) -> None:
    from engine.social import payload

    assert payload.phone_block(receipts_state)["scene"] == {}


def test_the_narrator_is_told_who_you_are_with(in_a_scene) -> None:
    from engine.social import population, world

    scene, session, state, pid = in_a_scene
    block = world.narration_block(state)
    assert f"You are with {population.profile(state, pid).name}, in person" in block
    assert "The Anchor" in block


def test_a_scene_turn_is_archived_and_never_kept_in_state(in_a_scene, monkeypatch) -> None:
    """A narrated scene turn's prose goes to the archive as a `scene` row (§7.1), through `run_turn`'s hook."""
    import json

    from engine.social import archive, messaging

    from engine.scenes.default_state import run_turn
    from engine.session.store import release_turn

    scene, session, state, pid = in_a_scene
    assert session.lock.acquire(blocking=False)
    try:
        turn = run_turn(session, "Be playful", intent={"action": "scene", "target": "playful"})
    finally:
        release_turn(session)
    assert turn["intent_resolved"] is True
    narration = turn["narration"]
    directory = archive.save_dir(session)
    rows = [json.loads(line) for line in (directory / archive.ARCHIVE_FILE).read_text(encoding="utf-8").splitlines()
            if line.strip()]
    scenes = [r for r in rows if r.get("row") == "scene"]
    assert scenes and scenes[-1]["bubbles"] == [narration.strip()]
    assert scenes[-1]["thread_id"] == messaging.thread_for(state, pid)
    assert narration.strip() not in json.dumps(state.social, default=str)


def test_a_fit_trait_must_be_a_population_trait(receipts_active) -> None:
    """Pre-flight F23: a move's `fit.traits` key nobody can have is refused at load."""
    import copy

    from engine import social
    from engine.social import scene as social_scene

    data = copy.deepcopy(social.data("scenes"))
    data["moves"]["quiet"]["fit"] = {"traits": {"zz_q7_trait": 0.06}}
    with pytest.raises(ValueError, match=r"scenes\.yaml: moves\.quiet\.fit\.traits"):
        social_scene.check_data(data, traits=frozenset({"warm", "laid_back", "curious"}))


def test_a_move_row_with_a_floor_or_a_refusal_is_refused_at_load(receipts_active) -> None:
    """§19.6: a move is exactly label, minutes, fit and bands."""
    import copy

    from engine import social
    from engine.social import scene as social_scene

    for extra in ({"floor": {"depth": 2}}, {"refusal": "not yet"}, {"stage": "dating"}):
        data = copy.deepcopy(social.data("scenes"))
        data["moves"]["playful"].update(extra)
        with pytest.raises(ValueError, match=r"scenes\.yaml: moves\.playful\."):
            social_scene.check_data(data)


def test_a_quiet_visit_goes_home(receipts_active) -> None:
    from engine.game.intents import legal_intents
    from engine.social import world

    scene, session = _live_session()
    state = session.engine.state
    state.social["phone_up"] = False
    state.location_id = "merrow_street"
    assert world.go(state, "copper_kettle")["quiet"] is True
    go = next(v for v in legal_intents(state) if v.action == "go")
    assert go.targets[0] == "apt_lounge"


def test_the_evaluator_fails_a_landing_over_a_misstep() -> None:
    from engine.agents.evaluator import contradicts

    receipt = {"skill": "social_scene", "result": {"band": "misstep"}}
    assert contradicts("You make the joke. It lands.", [receipt])
    assert not contradicts("You make the joke. It lands.", [{"skill": "move_to", "result": {}}])
    assert not contradicts("You make the joke. It lands.", [{"skill": "social_scene", "result": {"band": "lands"}}])
    assert not contradicts("Whether it lands is another matter.", [receipt])


def test_no_other_story_imports_social_through_scene_owns_turn() -> None:
    """Seam pin 3 (T11), re-run here: `scene_owns_turn` and `legal_intents` for every other story import no
    `engine.social` submodule (a sys.modules snapshot)."""
    import sys

    from engine.game import procgen
    from engine.game.intents import legal_intents, scene_owns_turn
    from engine.games import registry
    from tests.test_social_seam import SIX, _social_names

    for slug in SIX:
        before = set(sys.modules)
        registry.activate(slug)
        try:
            state = procgen.new_game_state(player_name="Ash", seed=5)
            scene_owns_turn(state)
            legal_intents(state)
        finally:
            registry.deactivate()
        assert sorted(_social_names(set(sys.modules) - before)) == [], slug


# -- moved from v0.22's tests/test_social_meets.py (T13 deleted meets.py) --------------------------------


def test_a_venue_is_picked_by_the_hobbies_two_people_share(receipts_state, numbers_pid) -> None:
    from engine.game.effects import apply_effect
    from engine.social import places, population

    pid = numbers_pid
    person = population.profile(receipts_state, pid)
    receipts_state.social["player"]["hobbies"] = list(person.hobbies[:1])
    made = apply_effect(receipts_state, {"type": "social_plan", "op": "pick", "pid": pid})
    assert made["ok"] and made["venue"] in places.venue_ids()
    assert set(places.venue(made["venue"])["hobbies"]) & set(person.hobbies)    # theirs at least


def test_a_venue_picked_by_kind_is_of_that_kind(receipts_state, numbers_pid) -> None:
    from engine.game.effects import apply_effect
    from engine.social import places

    for kind in ("coffee", "film", "walk"):
        made = apply_effect(receipts_state, {"type": "social_plan", "op": "pick", "pid": numbers_pid, "kind": kind})
        assert places.venue(made["venue"])["kind"] == kind == made["kind"], made


def test_the_venue_and_meets_data_is_checked(receipts_active) -> None:
    from engine import social
    from engine.social import places, scene as social_scene

    venues = social.data("venues")
    rel = social.data("relationships")
    pop = social.data("population")
    assert places.venue_faults(venues, pop) == [] and social_scene.meets_faults(rel) == []
    assert len(venues["venues"]) >= places.MIN_VENUES
    few = {**venues, "venues": venues["venues"][:3]}
    assert ("venues.yaml", "venues", "must list 12 venues or more") in places.venue_faults(few, pop)
    bad = {**venues, "venues": [{**venues["venues"][0], "neighbourhood": "atlantis"}] + venues["venues"][1:]}
    assert any(k == "venues[0].neighbourhood" for _f, k, _m in places.venue_faults(bad, pop))
    old = {**rel, "meets": {**rel["meets"], "bands": {"great": 0.6}}}               # v0.22's prior is scenes.yaml's now
    assert any(k == "meets.bands" for _f, k, _m in social_scene.meets_faults(old))
    assert social_scene.meets_faults({k: v for k, v in rel.items() if k != "meets"}, venues_declared=False) == []


def test_the_scene_data_is_the_briefs(receipts_active) -> None:
    from engine import social
    from engine.social import scene as social_scene

    data = social.data("scenes")
    assert list(data["moves"]) == list(social_scene.MOVES)
    assert set(data["closers"]) <= set(social_scene.CLOSERS)
    assert list(data["end_bands"]) == list(social_scene.SCENE_BANDS[:-1])
    assert set(data["stay"]["accept"]) == {"default", "romantic", "slow_burner"}       # by archetype only (F34)


def test_a_scenes_read_paths_draw_and_write_nothing(in_a_scene) -> None:
    """§19.1 (I14): with a scene open, the payload, the verbs, the narrator's block and the turn's owner read
    only: the save and every counter are unchanged."""
    import json

    from engine.game.intents import describe_intent, legal_intents, scene_owns_turn
    from engine.social import payload, world

    scene, session, state, pid = in_a_scene
    before = json.dumps(state.to_save_dict(), sort_keys=True, default=str)
    for _ in range(3):
        assert payload.phone_block(state)["scene"]["pid"] == pid
        assert scene_owns_turn(state)
        verbs = legal_intents(state)
        describe_intent(state, {"action": "close", "target": verbs[1].targets[0]})
        world.narration_block(state)
        state.to_client_dict()
    assert json.dumps(state.to_save_dict(), sort_keys=True, default=str) == before


def test_the_validator_names_a_scene_fault(tmp_path) -> None:
    """`validate_content.py` runs the load's own scene check (`_check_scenes`): a move with a floor, and a
    `fit.traits` key that is no population trait, are each one finding naming the key."""
    import shutil
    from pathlib import Path

    import yaml

    from engine.games import registry
    from engine.games.validation import StoryValidator

    story = Path(__file__).resolve().parents[1] / "games" / "read-receipts" / "data" / "social"
    for extra, key in (({"floor": {"depth": 2}}, "moves.quiet.floor"),
                       ({"fit": {"traits": {"zz_q7_trait": 0.1}}}, "moves.quiet.fit.traits")):
        here = tmp_path / key
        shutil.copytree(story, here)
        data = yaml.safe_load((here / "scenes.yaml").read_text(encoding="utf-8"))
        data["moves"]["quiet"].update(extra)
        (here / "scenes.yaml").write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        validator = StoryValidator(registry.get("read-receipts"))
        validator._check_scenes(here)
        named = {(i.source, i.ref_id) for i in validator.issues if i.severity == "error"}
        assert named == {("social/scenes.yaml", key)}, validator.issues


def _post_meets(state) -> list:
    return [e for e in state.social["queue"] if (e.get("decision") or {}).get("situation") == "post_meet"]


def test_post_meet_waits_for_the_last_scene_of_the_evening(in_a_scene, monkeypatch) -> None:
    """A go-on closer ends this scene but not the evening: their "after the date" text is held until the
    scene they are in actually ends (T13 review, minor 3)."""
    from engine.social import growth, scene as social_scene

    scene, session, state, pid = in_a_scene
    _as(monkeypatch, pid, archetype="steady")
    _moments(monkeypatch, "lands")
    real = growth.willing
    monkeypatch.setattr(growth, "willing", lambda s, p, c: (True, "") if c in ("meet", "come_over") else real(s, p, c))
    social_scene.move(state, "playful")
    done = social_scene.close(state, "back_to_yours")
    assert done["ok"] and social_scene.current(state).get("kind") == "your_place"
    assert _post_meets(state) == []                                   # still together
    social_scene.move(state, "playful")
    social_scene.close(state, "call_it_a_night:stay")
    assert [e["decision"]["plan_id"] for e in _post_meets(state)] == [done["plan_id"]]


# -- homes and visits (v0.23.0 T16; spec §10.5) ----------------------------------------------------------


def test_a_home_needs_a_plan_or_invitation(receipts_active) -> None:
    from engine.game.intents import legal_intents
    from tests.social_fixtures import _live_session, _matched_in

    scene, session = _live_session()
    state = session.engine.state
    state.social["phone_up"] = False
    _matched_in(session, "matchstick")
    state.location_id = "merrow_street"
    go = next(v for v in legal_intents(state) if v.action == "go")
    assert not [t for t in go.targets if t.startswith("home_")]


def test_staying_over_is_logistics_and_a_no_is_a_plain_answer(in_a_scene, monkeypatch) -> None:
    from engine.social import growth, scene as social_scene

    _, session, state, pid = in_a_scene
    real = growth.willing
    monkeypatch.setattr(growth, "willing", lambda s, p, c: (True, "") if c in ("stay_over", "meet") else real(s, p, c))
    monkeypatch.setattr(social_scene, "stay_offered", lambda s: True)
    monkeypatch.setattr(social_scene, "_stay_drawn", lambda s, p: False)
    result = social_scene.stay_the_night(state)
    assert result["ok"] is True and result["stayed"] is False and "error" not in result
    assert state.social["scene"]["pid"] == pid                       # the evening goes on
    monkeypatch.setattr(social_scene, "_stay_drawn", lambda s, p: True)
    result = social_scene.stay_the_night(state)
    assert result["stayed"] is True and state.world_clock_hours % 24 < 12
    assert not state.social["scene"] and "morning" not in result        # a venue opens no morning (F6)
    from engine.social import memory

    rows = memory.part(state.social["people"][pid], "history")
    assert any(h.get("kind") == "stay" and h.get("text") == "Stayed over" for h in rows)


def _to_the_flat(in_a_scene, monkeypatch):
    from engine.social import growth, scene as social_scene

    _, session, state, pid = in_a_scene
    real = growth.willing
    monkeypatch.setattr(growth, "willing",
                        lambda s, p, c: (True, "") if c in ("stay_over", "meet", "come_over") else real(s, p, c))
    done = social_scene.close(state, "back_to_yours")
    return state, pid, done


def test_your_place_brings_them_to_the_flat(in_a_scene, monkeypatch) -> None:
    state, pid, done = _to_the_flat(in_a_scene, monkeypatch)
    assert done["ok"] and done["recorded"] == ["come_over"]
    assert state.location_id == "apt_lounge"
    assert state.social["scene"]["pid"] == pid and state.social["scene"]["kind"] == "your_place"


def test_stay_the_night_is_offered_at_a_home_only_and_closes_the_clock_on_the_morning(in_a_scene, monkeypatch) -> None:
    from engine.social import scene as social_scene

    state, pid, _ = _to_the_flat(in_a_scene, monkeypatch)
    state.social["scene"]["energy"] = 90.0
    state.social["scene"]["sum"], state.social["scene"]["count"] = 0.8, 1
    assert social_scene.stay_offered(state)
    state.social["scene"]["location"] = "the_anchor"
    assert not social_scene.stay_offered(state)                        # a venue offers no night
    state.social["scene"]["location"] = "apt_lounge"
    assert "stay_the_night" in dict(social_scene._close_options(state, state.social["scene"]))
    monkeypatch.setattr(social_scene, "_stay_drawn", lambda s, p: True)
    done = social_scene.close(state, "stay_the_night")
    assert done["ok"] and done["stayed"] is True
    assert state.location_id == "apt_kitchen" and state.social["scene"]["kind"] == "morning"   # the morning (T1)
    assert 5 <= state.world_clock_hours % 24 < 12
    morning = state.world_clock_hours
    queued = [r for r in (state.social.get("queue") or ()) if r.get("pid") == pid]
    assert queued and all(float(r["at"]) >= morning - 1e-6 for r in queued)       # the text waits for the morning


def test_the_not_tonight_reason_is_a_fact_that_holds(in_a_scene) -> None:
    from engine.social import scene as social_scene

    _, session, state, pid = in_a_scene
    scn = {"energy": 10.0, "location": "apt_lounge"}
    assert social_scene._not_tonight_reason(state, pid, scn) == "they're shattered"
    scn = {"energy": 90.0, "location": "home_terrace_share"}
    assert social_scene._not_tonight_reason(state, pid, scn) == "their housemates have people over"
    scn = {"energy": 90.0, "location": "home_quays_loft"}
    assert social_scene._not_tonight_reason(state, pid, scn) == ""


def test_stay_the_night_is_not_offered_before_an_early_shift(in_a_scene, monkeypatch) -> None:
    from engine.social import convo, growth, scene as social_scene

    state, pid, _ = _to_the_flat(in_a_scene, monkeypatch)
    state.social["scene"]["energy"] = 90.0
    state.social["scene"]["sum"], state.social["scene"]["count"] = 0.8, 1
    assert social_scene.stay_offered(state)
    monkeypatch.setattr(convo, "boundary_minutes", lambda s, p, at: 360.0)
    monkeypatch.setattr(convo, "_status", lambda s, p, at: "work")
    assert not social_scene.stay_offered(state)


def test_the_stay_draw_reads_the_archetype_alone(in_a_scene, monkeypatch) -> None:
    from engine.social import scene as social_scene

    _, session, state, pid = in_a_scene
    class _Rng:
        def random(self) -> float:
            return 0.7
    from engine.social import behaviour
    monkeypatch.setattr(behaviour, "person_rng", lambda s, stream, p: _Rng())
    _as(monkeypatch, pid, archetype="romantic")
    assert social_scene._stay_drawn(state, pid) is True            # 0.7 < 0.75
    _as(monkeypatch, pid, archetype="slow_burner")
    assert social_scene._stay_drawn(state, pid) is False           # 0.7 >= 0.35


def test_a_not_tonight_holds_for_the_rest_of_the_scene(in_a_scene, monkeypatch) -> None:
    from engine.social import scene as social_scene

    state, pid, _ = _to_the_flat(in_a_scene, monkeypatch)
    state.social["scene"]["energy"] = 90.0
    state.social["scene"]["sum"], state.social["scene"]["count"] = 0.8, 1
    assert social_scene.stay_offered(state)
    monkeypatch.setattr(social_scene, "_stay_drawn", lambda s, p: False)
    assert social_scene.close(state, "stay_the_night")["stayed"] is False
    assert not social_scene.stay_offered(state)
    assert "stay_the_night" not in dict(social_scene._close_options(state, state.social["scene"]))
    assert social_scene.close(state, "stay_the_night")["ok"] is False
    assert state.social["scene"]["stay_asked"] is True


# -- the morning after (v0.24.0 T1; spec §12.1) ---------------------------------------------------------


def _stayed(in_a_scene, monkeypatch, *, where: str):
    """A stay-over that is accepted: from a `back_to_yours` scene in the lounge (`where="yours"`) or a
    `back_to_theirs` scene at their home (`where="theirs"`). Every draw forced (F16)."""
    from engine.social import growth, scene as social_scene

    _, session, state, pid = in_a_scene
    real = growth.willing
    monkeypatch.setattr(growth, "willing", lambda s, p, c: (True, "") if c in (
        "stay_over", "meet", "come_over", "go_to_theirs") else real(s, p, c))
    social_scene.close(state, "back_to_yours" if where == "yours" else "back_to_theirs")
    monkeypatch.setattr(social_scene, "stay_offered", lambda s: True)
    monkeypatch.setattr(social_scene, "_stay_drawn", lambda s, p: True)
    done = social_scene.stay_the_night(state)
    assert done["ok"] and done["stayed"] is True
    return state, pid


def test_morning_scene_after_stay_over(in_a_scene, monkeypatch) -> None:
    """Pre-flight F32: a night at the flat wakes in the kitchen, a morning scene open there."""
    state, pid = _stayed(in_a_scene, monkeypatch, where="yours")
    scn = state.social["scene"]
    assert scn["pid"] == pid and scn["kind"] == "morning"
    assert state.location_id == "apt_kitchen" and scn["location"] == "apt_kitchen"
    assert 5 <= state.world_clock_hours % 24 < 12


def test_a_morning_at_theirs_is_in_their_home(in_a_scene, monkeypatch) -> None:
    """Pre-flight F32: a `home_*` host's home is a single location, so the morning scene is there."""
    from engine.social import places

    state, pid = _stayed(in_a_scene, monkeypatch, where="theirs")
    home = places.home_of(state, pid)
    assert state.location_id == home
    assert state.social["scene"]["kind"] == "morning" and state.social["scene"]["location"] == home


def test_the_morning_offers_only_its_moves_and_closers(in_a_scene, monkeypatch) -> None:
    from engine.social import scene as social_scene

    state, pid = _stayed(in_a_scene, monkeypatch, where="yours")
    allowed = set(social_scene._data()["morning"]["moves"])
    moves = [t.split(":")[0] for t, _ in social_scene._move_options(state, pid)]
    assert moves and set(moves) <= allowed and "talk" in moves
    closers = [t for t, _ in social_scene._close_options(state, state.social["scene"])]
    assert closers == ["see_them_out", "see_them_out:plan:soon"]


def test_the_morning_ends_after_its_moments(in_a_scene, monkeypatch) -> None:
    """It ends after its moments (spec §12.1); energy is forced high so no ordinary close ends it first (F18)."""
    from engine.social import scene as social_scene

    state, pid = _stayed(in_a_scene, monkeypatch, where="yours")
    _moments(monkeypatch, "fine")
    state.social["scene"]["energy"] = 100.0
    for _ in range(int(social_scene._data()["morning"]["moments"])):
        assert state.social["scene"]
        social_scene.move(state, "quiet")
    assert not state.social["scene"]


def test_the_morning_is_not_a_second_scene(in_a_scene, monkeypatch) -> None:
    """The night's tail: no `scenes_done`, no `meets_good`, no second `post_meet`, no history row."""
    from engine.social import memory, scene as social_scene

    state, pid = _stayed(in_a_scene, monkeypatch, where="yours")
    person = state.social["people"][pid]
    done, good = int(person.get("scenes_done", 0)), int(person.get("meets_good", 0))
    history = len(memory.part(person, "history") or [])
    queued = len(_post_meets(state))
    _moments(monkeypatch, "lands")
    social_scene.close(state, "see_them_out")
    assert not state.social["scene"]
    assert int(person.get("scenes_done", 0)) == done and int(person.get("meets_good", 0)) == good
    assert len(memory.part(person, "history") or []) == history
    assert len(_post_meets(state)) == queued


def test_no_text_lands_during_the_morning(in_a_scene, monkeypatch) -> None:
    """The night's post_meet, due during the morning, is HELD while they are together (addendum 4 W5) and is
    landed when they part (`end_scene` -> `messaging.release_held`). Pre-flight F30: every draw forced, the due
    time set through the scene's own seam (no queue row mutated), and the landing asserted."""
    from engine.social import messaging, scene as social_scene

    monkeypatch.setattr(social_scene, "_post_meet_at", lambda s, p, at: at)   # due at the morning hour itself
    state, pid = _stayed(in_a_scene, monkeypatch, where="yours")
    _moments(monkeypatch, "fine")
    state.social["scene"]["energy"] = 100.0
    tid = messaging.thread_for(state, pid)
    shown = len((messaging.thread(state, tid) or {}).get("messages") or [])
    assert _post_meets(state)
    social_scene.move(state, "quiet")                          # time passes; the text is due and held
    assert messaging.held(state, pid)
    assert len((messaging.thread(state, tid) or {}).get("messages") or []) == shown
    social_scene.close(state, "see_them_out")
    assert not state.social["scene"] and not messaging.held(state, pid)
    assert not [e for e in _post_meets(state) if e.get("held")]          # released: none still held
    assert len((messaging.thread(state, tid) or {}).get("messages") or []) > shown


def test_see_them_out_leaves_the_player_in_the_kitchen(in_a_scene, monkeypatch) -> None:
    from engine.social import scene as social_scene

    state, pid = _stayed(in_a_scene, monkeypatch, where="yours")
    done = social_scene.close(state, "see_them_out:plan:soon")
    assert done["ok"] and done.get("plan_id")
    assert state.location_id == "apt_kitchen" and not state.social["scene"]


def test_the_scene_section_names_the_morning(in_a_scene, monkeypatch) -> None:
    from engine.social import scene as social_scene

    state, pid = _stayed(in_a_scene, monkeypatch, where="yours")
    section = social_scene._scene_section(state, None)
    started = state.social["scene"]["started_at"]
    assert section["kind"] == "morning" and section["id"] == f"{pid}@{started}"


@pytest.mark.parametrize("morning, key", [
    ({"moments": 0, "moves": ["talk"]}, "morning.moments"),
    ({"moments": 2, "moves": ["quiet"]}, "morning.moves"),
    ({"moments": 2, "moves": ["talk", "phone"]}, "morning.moves"),
    ({"moments": 2, "moves": ["talk"], "prior_bias": 0.5}, "morning.prior_bias"),
    ({"moments": 2, "moves": ["talk"], "floor": 1}, "morning.floor"),
])
def test_the_morning_block_is_checked(receipts_active, morning, key) -> None:
    import copy

    from engine.social import scene as social_scene

    data = copy.deepcopy(social_scene._data())
    data["morning"] = morning
    with pytest.raises(ValueError, match=key.replace(".", r"\.")):
        social_scene.check_data(data)


def test_a_morning_that_ends_by_itself_is_reported_as_the_morning(in_a_scene, monkeypatch) -> None:
    """Review finding 1: the receipt said "They call it a night" over a morning that ran out of moments."""
    from engine.social import scene as social_scene

    state, pid = _stayed(in_a_scene, monkeypatch, where="yours")
    _moments(monkeypatch, "fine")
    state.social["scene"]["energy"] = 100.0
    result = {}
    for _ in range(int(social_scene._data()["morning"]["moments"])):
        result = social_scene.move(state, "quiet")
    assert result["closed_by_them"] == "morning" and not state.social["scene"]
    text = social_scene.receipt_lines(state, [{"skill": "social_scene", "result": result}])
    assert "They have to get on with the day." in text and "call it a night" not in text


@pytest.mark.parametrize("target, words", [
    ("call_it_a_night", "You head home."),
    ("call_it_a_night:plan:soon", "You head home, and say you'll do it again soon."),
])
def test_the_morning_at_theirs_closes_in_the_morning_words(in_a_scene, monkeypatch, target, words) -> None:
    from engine.social import scene as social_scene

    state, pid = _stayed(in_a_scene, monkeypatch, where="theirs")
    closers = dict(social_scene._close_options(state, state.social["scene"]))
    assert closers[target].startswith("Head home")
    result = social_scene.close(state, target)
    assert result["ok"]
    text = social_scene.receipt_lines(state, [{"skill": "social_close", "result": result,
                                               "intent": {"action": "close", "target": target}}])
    assert words in text and "call it a night" not in text.lower()


def test_the_morning_is_worded_in_a_line_in_lower_case(in_a_scene, monkeypatch) -> None:
    from engine.social import scene as social_scene

    state, pid = _stayed(in_a_scene, monkeypatch, where="yours")
    assert social_scene._where_words(state, state.social["scene"]) == "The morning after, at yours"
    assert social_scene._where_in_a_line(state, state.social["scene"]) == "the morning after, at yours"
    assert "in person: the morning after, at yours." in social_scene.narration_line(state)


def test_the_morning_opens_with_its_prior_bias(in_a_scene, monkeypatch) -> None:
    """`morning.prior_bias` is added to the prior at the opening; another kind gets none of it."""
    from engine.social import scene as social_scene

    state, pid = _stayed(in_a_scene, monkeypatch, where="yours")
    social_scene.end_scene(state, "test")
    monkeypatch.setattr(social_scene, "_prior_terms", lambda s, p: 0.0)
    monkeypatch.setattr(social_scene, "_prior_draw", lambda s, p: 0.0)
    bias = float(social_scene._data()["morning"]["prior_bias"])
    assert bias != 0.0
    for kind, want in (("morning", bias), ("date", 0.0)):
        opened = social_scene.apply_effect(state, {"type": "social_scene", "op": "open", "pid": pid, "kind": kind,
                                                    "location": "apt_kitchen"})
        assert opened.get("ok")
        assert abs(float(social_scene.current(state)["prior"]) - want) < 1e-6
        state.social["scene"] = {}
