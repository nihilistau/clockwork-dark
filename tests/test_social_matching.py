"""
Apps and matching (v0.22.0 T7, spec §6, §8): the decks, likes per day, the
like-back drawn once per pair, a match only at its `see_like` event, likes
you, expiry, unmatch and block, and apps.yaml's checks.
"""

from __future__ import annotations

import copy
import shutil
from pathlib import Path

import pytest

from tests.social_fixtures import _act, _top, matched, receipts_active, receipts_state  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]
SOCIAL_DIR = ROOT / "games" / "read-receipts" / "data" / "social"


def test_like_back_is_drawn_once_per_pair(receipts_state) -> None:
    from engine.social import matching, population

    person = population.profile(receipts_state, "p0005")
    first = matching.likes_back(receipts_state, "matchstick", person, super_=False)
    assert all(matching.likes_back(receipts_state, "matchstick", person, super_=False) == first for _ in range(20))


def test_like_back_is_clamped(receipts_state, monkeypatch) -> None:
    from engine import social
    from engine.social import matching, population

    m = social.data("apps")["matching"]
    # The person's own terms pinned (F16): a fully selective person's 0 would make the clamp vacuous by seed.
    monkeypatch.setattr(matching, "_selectivity", lambda person: 0.0)
    monkeypatch.setattr(matching, "compatibility", lambda player, person: 0.5)
    monkeypatch.setitem(m, "like_back_base", {"matchstick": 50.0, "front_porch": 50.0})
    assert matching.like_back_p(receipts_state, "matchstick", population.profile(receipts_state, "p0005"), super_=True) == 1.0
    monkeypatch.setitem(m, "like_back_base", {"matchstick": -5.0, "front_porch": -5.0})
    assert matching.like_back_p(receipts_state, "matchstick", population.profile(receipts_state, "p0005"), super_=False) == 0.0


def test_a_mutual_like_matches_only_after_its_see_like_event(receipts_state, monkeypatch) -> None:
    from engine.game import clock
    from engine.social import matching

    monkeypatch.setattr(matching, "likes_back", lambda *a, **k: True)
    pid = _top(receipts_state, "matchstick")
    matching.like(receipts_state, "matchstick", pid)
    assert "matchstick:" + pid not in receipts_state.social["threads"]
    clock.advance_time(receipts_state, 24 * 4)
    assert "matchstick:" + pid in receipts_state.social["threads"]
    assert receipts_state.social["people"][pid]["stage"] == "matched"


def test_a_new_match_notifies_new_match(receipts_state, matched) -> None:
    """
    A match is a notification of its own (T30 follow-up, spec §15.3 counts "1 new match"): the lock screen
    says so whether or not they write first, through `social_match` (rule 3), naming the thread to open.
    """
    from engine.social import messaging

    tid = matched("matchstick")
    pid = tid.split(":", 1)[1]
    rows = [r for r in messaging.notification_rows(receipts_state) if r["kind"] == "match"]
    assert len(rows) == 1, rows
    assert rows[0]["thread_id"] == tid and rows[0]["pid"] == pid and rows[0]["app"] == "matchstick"
    assert rows[0]["preview"] == messaging.NEW_MATCH and rows[0]["name"]


def test_a_like_not_returned_never_matches(receipts_state, monkeypatch) -> None:
    from engine.game import clock
    from engine.social import matching

    monkeypatch.setattr(matching, "likes_back", lambda *a, **k: False)
    pid = _top(receipts_state, "matchstick")
    assert matching.like(receipts_state, "matchstick", pid)["ok"]
    assert not [e for e in receipts_state.social["queue"] if e["kind"] == "see_like"]
    clock.advance_time(receipts_state, 24 * 4)
    assert "matchstick:" + pid not in receipts_state.social["threads"]
    assert _top(receipts_state, "matchstick") != pid           # off the deck either way


def _overlap_pid(state) -> str:
    """Someone in the band on both apps whom the player's discovery settings let through."""
    from engine.social import apps, population

    for index in population.overlap("matchstick"):
        person = population.person(state.rng_seed, index, state.social["player"])
        if apps.shows(state, person):
            return person.pid
    raise AssertionError("no overlap person shows")


def test_a_match_on_one_app_does_not_match_the_other(receipts_state, monkeypatch) -> None:
    from engine.game import clock
    from engine.social import apps, matching, population

    pid = _overlap_pid(receipts_state)
    assert set(population.apps_of(pid)) == {"matchstick", "front_porch"}
    monkeypatch.setattr(matching, "likes_back", lambda *a, **k: True)
    monkeypatch.setattr(apps, "top_card", lambda state, name: pid)   # put them on top of both decks
    assert matching.like(receipts_state, "matchstick", pid)["ok"]
    clock.advance_time(receipts_state, 24 * 4)
    assert matching.thread_id("matchstick", pid) in receipts_state.social["threads"]
    assert matching.thread_id("front_porch", pid) not in receipts_state.social["threads"]
    on_porch = apps.on_app(receipts_state, pid, "front_porch")
    assert "matched_at" not in on_porch and "swiped" not in on_porch   # nothing happened on Front Porch


def _no_opener(monkeypatch) -> None:
    """The match's possible opener (T8) forced off, so the match stays silent (F16)."""
    import dataclasses

    from engine.social import behaviour

    real = behaviour.archetype
    monkeypatch.setattr(behaviour, "archetype", lambda name: dataclasses.replace(real(name), opener_prob=0.0))


def test_a_silent_match_expires_with_an_engine_line(receipts_state, matched, monkeypatch) -> None:
    from engine.game import clock
    from engine.social import apps

    tid = matched("matchstick")
    _no_opener(monkeypatch)
    pid = tid.split(":", 1)[1]
    clock.advance_time(receipts_state, apps.app("matchstick")["match_expiry_days"] * 24 + 1)
    last = receipts_state.social["threads"][tid]["messages"][-1]
    assert last["kind"] == "system" and last["bubbles"] == ["This match expired"]
    assert receipts_state.social["people"][pid]["stage"] == "expired"


def test_a_match_with_a_message_does_not_expire(receipts_state, matched) -> None:
    from engine.game import clock
    from engine.social import apps

    tid = matched("matchstick")
    pid = tid.split(":", 1)[1]
    # A player message, as T8's sender will write one (its row shape, the plan's).
    receipts_state.social["threads"][tid]["messages"].append(
        {"id": "m99", "thread_id": tid, "from": "player", "kind": "text", "at": receipts_state.world_clock_hours,
         "bubbles": ["hi"], "voiced": True, "decision": None, "media_id": None, "read_at": None, "transcript": None})
    clock.advance_time(receipts_state, apps.app("matchstick")["match_expiry_days"] * 24 + 1)
    assert receipts_state.social["threads"][tid]["messages"][-1]["kind"] == "text"
    assert receipts_state.social["people"][pid]["stage"] == "matched"


def test_likes_you_arrive_daily_scaled_by_completeness(receipts_state) -> None:
    from engine import social
    from engine.game import clock
    from engine.social import apps

    clock.advance_time(receipts_state, 24 * 3)
    rows = receipts_state.social["apps"]["front_porch"]["likes_you"]
    high = social.data("apps")["matching"]["completeness"][1]
    assert 0 < len(rows) <= 3 * apps.app("front_porch")["likes_you_per_day"] * high
    assert all(row["comment"].strip() and "{" not in row["comment"] for row in rows)
    assert "likes_you" not in receipts_state.social["apps"].get("matchstick", {}) or \
        not receipts_state.social["apps"]["matchstick"]["likes_you"]       # Matchstick has no likes-you


def test_a_fuller_profile_is_more_complete(receipts_active) -> None:
    from engine.game import procgen
    from engine.social import matching

    sparse = procgen.new_game_state(player_name="Sam", seed=4242)
    full = procgen.new_game_state(player_name="Sam", seed=4242, creation={
        "photos": ["hike_squint", "mirror_jacket", "harbour_sunset", "pint_laughing"]})
    full.social["player"]["bios"] = {"front_porch": "hello"}
    assert matching.completeness_mult(full.social["player"]) > matching.completeness_mult(sparse.social["player"])


def test_liking_back_is_a_match_at_once(receipts_state) -> None:
    from engine.game import clock

    clock.advance_time(receipts_state, 24 * 3)
    row = receipts_state.social["apps"]["front_porch"]["likes_you"][0]
    receipt = _act(receipts_state, "like_back", target=row["pid"], args={"comment": "hello you"})
    assert receipt["success"], receipt
    assert "front_porch:" + row["pid"] in receipts_state.social["threads"]
    assert all(r["pid"] != row["pid"] for r in receipts_state.social["apps"]["front_porch"]["likes_you"])


def test_no_likes_left_is_a_refusal(receipts_state) -> None:
    from engine.game.effects import apply_effect

    pid = _top(receipts_state, "matchstick")
    assert apply_effect(receipts_state, {"type": "social_app", "app": "matchstick", "op": "set",
                                         "values": {"likes_left": 0}})["ok"]
    receipt = _act(receipts_state, "swipe", target=pid, args={"dir": "like"})
    assert receipt["refused"] is True and "No likes left today" in receipt["result"]["error"]


def test_likes_reset_at_the_daily(receipts_state) -> None:
    from engine.game import clock
    from engine.game.effects import apply_effect
    from engine.social import apps

    apply_effect(receipts_state, {"type": "social_app", "app": "matchstick", "op": "set", "values": {"likes_left": 0}})
    clock.advance_time(receipts_state, 24)
    assert apps.likes_left(receipts_state, "matchstick") == apps.app("matchstick")["likes_per_day"]


def test_a_swipe_spends_a_like_and_its_minutes(receipts_state) -> None:
    from engine.social import apps

    pid = _top(receipts_state, "matchstick")
    before, left = receipts_state.world_clock_hours, apps.likes_left(receipts_state, "matchstick")
    assert _act(receipts_state, "swipe", target=pid, args={"dir": "like"})["success"]
    assert apps.likes_left(receipts_state, "matchstick") == left - 1
    assert receipts_state.world_clock_hours - before == pytest.approx(0.2 / 60)
    assert _top(receipts_state, "matchstick") != pid


def test_a_super_like_spends_the_day_s_super(receipts_state) -> None:
    from engine.social import apps, intents

    assert _act(receipts_state, "swipe", target=_top(receipts_state, "matchstick"), args={"dir": "super"})["success"]
    assert apps.supers_left(receipts_state, "matchstick") == 0
    verb = next(v for v in intents.legal_phone_intents(receipts_state) if v.action == "swipe")
    assert verb.extra["dir"] == ("like", "pass")
    refused = _act(receipts_state, "swipe", target=_top(receipts_state, "matchstick"), args={"dir": "super"})
    assert refused["refused"] is True


def test_unmatch_hides_the_thread_and_leaves_a_card_line(receipts_state, matched) -> None:
    from engine.social import matching

    tid = matched("matchstick")
    pid = tid.split(":", 1)[1]
    listed_before = receipts_state.to_client_dict()["phone"]["threads"]
    assert any(row["thread_id"] == tid for row in listed_before)          # T8's section lists it until then
    assert _act(receipts_state, "unmatch", target=pid)["success"]
    thread = receipts_state.social["threads"][tid]
    assert not matching.listed(thread)
    listed_after = receipts_state.to_client_dict()["phone"]["threads"]
    assert isinstance(listed_after, list) and all(row["thread_id"] != tid for row in listed_after)
    history = [row["text"] for row in receipts_state.social["people"][pid]["history"]]
    assert "This match is no longer available" in history
    assert not [e for e in receipts_state.social["queue"] if e["pid"] == pid]    # their expiry cancelled
    assert _act(receipts_state, "unmatch", target=pid)["refused"] is True


def test_block_closes_every_thread_and_keeps_them_off_the_decks(receipts_state, matched) -> None:
    from engine.social import apps, matching

    tid = matched("matchstick")
    pid = tid.split(":", 1)[1]
    assert _act(receipts_state, "block", target=pid)["success"]
    assert receipts_state.social["threads"][tid]["closed"] == "blocked"
    assert not matching.listed(receipts_state.social["threads"][tid])
    assert all(apps.touched(receipts_state, pid, name) for name in apps.dating_apps())
    assert _act(receipts_state, "block", target=pid)["refused"] is True


def test_the_deck_only_shows_the_filtered_sex_and_age_range(receipts_state) -> None:
    from engine.social import matching, population

    player = receipts_state.social["player"]
    low, high = player["discovery"]["age_min"], player["discovery"]["age_max"]
    for app in ("matchstick", "front_porch"):
        for _ in range(40):
            pid = _top(receipts_state, app)
            person = population.profile(receipts_state, pid)
            assert person.sex != player["sex"] and low <= person.age <= high
            assert matching.pass_(receipts_state, app, pid)["ok"]


def test_a_near_discovery_shows_only_near_neighbourhoods(receipts_active) -> None:
    from engine import social
    from engine.game import procgen
    from engine.social import population

    state = procgen.new_game_state(player_name="Sam", seed=4242,
                                   creation={"neighbourhood": "eastfield", "discovery": {"distance": "near"}})
    table = social.data("population")["distance"]["eastfield"]
    from engine.social import matching

    for _ in range(25):
        pid = _top(state, "matchstick")
        assert table[population.profile(state, pid).neighbourhood] <= 1
        matching.pass_(state, "matchstick", pid)


def test_compatibility_is_deterministic_and_in_range(receipts_state) -> None:
    from engine.social import matching, population

    player = receipts_state.social["player"]
    scores = []
    for index in range(0, 1300, 13):
        person = population.profile(receipts_state, population.pid_for(index))
        score = matching.compatibility(player, person)
        assert 0.0 <= score <= 1.0
        assert matching.compatibility(copy.deepcopy(player), person) == score
        scores.append(score)
    assert len(set(scores)) > 10      # it discriminates


def test_complementary_outgoing_scores_three_quarters(receipts_state) -> None:
    from dataclasses import replace

    from engine.social import matching, population

    person = population.profile(receipts_state, "p0005")
    person = replace(person, personality=(("outgoing", 1),))
    assert matching.personality_score({"personality": {"outgoing": 3}}, person) == 0.75
    assert matching.personality_score({"personality": {"outgoing": 5}}, person) == 0.0
    person = replace(person, personality=(("homebody", 1),))
    assert matching.personality_score({"personality": {"homebody": 3}}, person) == 0.5


def test_a_dealbreaker_hit_costs_the_preferences_term(receipts_state) -> None:
    from dataclasses import replace

    from engine.social import matching, population

    person = population.profile(receipts_state, "p0005")
    person = replace(person, preferences=(("age_max", 40), ("age_min", 20), ("dealbreakers", ("smokes_yes",)),
                                          ("liked_hobbies", ()), ("selectivity", 0.3)))
    assert matching.preferences_score({"age": 30, "attributes": {"smokes": "no"}}, person) == 1.0
    assert matching.preferences_score({"age": 30, "attributes": {"smokes": "yes"}}, person) == pytest.approx(0.1)
    assert matching.preferences_score({"age": 50, "attributes": {"smokes": "no"}}, person) == 0.0


def test_looking_for_is_symmetric_with_a_middle_for_missing_pairs(receipts_active, monkeypatch) -> None:
    from engine import social
    from engine.social import matching

    assert matching.looking_for_score("short_term", "long_term") == matching.looking_for_score("long_term", "short_term") == 0.2
    monkeypatch.delitem(social.data("apps")["matching"]["looking_for_table"], "unsure_unsure")
    assert matching.looking_for_score("unsure", "unsure") == 0.5


def test_the_payload_shows_the_decks_and_likes_you_without_hidden_values(receipts_state) -> None:
    from engine.game import clock
    from engine.social import payload

    clock.advance_time(receipts_state, 24 * 3)
    block = receipts_state.to_client_dict()["phone"]
    assert block["deck"]["matchstick"]["card"]["pid"] == _top(receipts_state, "matchstick")
    assert block["deck"]["front_porch"]["card"]["prompts"]
    assert block["likes_you"] and all(row["comment"] for row in block["likes_you"])
    text = repr(block["deck"]) + repr(block["likes_you"])
    for hidden in ("chemistry", "selectivity", "archetype", "compat", "likes_back"):
        assert hidden not in text
    assert {"deck", "likes_you"} <= payload.TIME_VARYING_SECTIONS


def test_a_like_comment_is_capped_at_140(receipts_state) -> None:
    pid = _top(receipts_state, "front_porch")
    assert _act(receipts_state, "like", target=pid, args={"on": "photo_0", "comment": "x" * 141})["refused"] is True
    assert _act(receipts_state, "like", target=pid, args={"on": "photo_0", "comment": "x" * 140})["success"]


# -- apps.yaml's checks --------------------------------------------------------------------


def test_the_shipped_apps_validate_clean() -> None:
    from engine.games.validation import errors_only, validate_story

    errors = [i for i in errors_only(validate_story("read-receipts")) if i.source.startswith("social/")]
    assert errors == []


def _break(data: dict, how: str) -> tuple[str, str]:
    """Break apps.yaml one way; return (source, key) the validator must name."""
    apps_ = data["apps"]
    if how == "capability":
        apps_["texts"]["capabilities"] = ["text", "smoke_signal"]
        return "social/apps.yaml", "apps.texts.capabilities"
    if how == "cost_verb":
        apps_["natter"]["cost_minutes"]["hug"] = 1
        return "social/apps.yaml", "apps.natter.cost_minutes"
    if how == "weights_sum":
        data["matching"]["weights"]["distance"] = 0.2
        return "social/apps.yaml", "matching.weights"
    if how == "intent_missing":
        del apps_["matchstick"]["culture"]["intent_weights"]
        return "social/apps.yaml", "apps.matchstick.culture.intent_weights"
    if how == "archetype_missing":
        del apps_["front_porch"]["culture"]["archetype_weights"]
        return "social/apps.yaml", "apps.front_porch.culture.archetype_weights"
    if how == "intent_zero":
        apps_["matchstick"]["culture"]["intent_weights"]["unsure"] = 0
        return "social/apps.yaml", "apps.matchstick.culture.intent_weights"
    if how == "archetype_negative":
        apps_["front_porch"]["culture"]["archetype_weights"]["steady"] = -1
        return "social/apps.yaml", "apps.front_porch.culture.archetype_weights"
    if how == "intent_unknown":
        apps_["matchstick"]["culture"]["intent_weights"]["situationship"] = 2
        return "social/apps.yaml", "apps.matchstick.culture.intent_weights"
    if how == "archetype_unknown":
        apps_["matchstick"]["culture"]["archetype_weights"]["wizard"] = 2
        return "social/apps.yaml", "apps.matchstick.culture.archetype_weights"
    if how == "looking_for_pair":
        data["matching"]["looking_for_table"]["short_long"] = 0.2      # not the canonical order
        return "social/apps.yaml", "matching.looking_for_table"
    if how == "like_back_base":
        del data["matching"]["like_back_base"]["front_porch"]
        return "social/apps.yaml", "matching.like_back_base"
    if how == "likes_you_hours":
        data["matching"]["likes_you_hours"] = [22, 6]
        return "social/apps.yaml", "matching.likes_you_hours"
    if how == "deck":
        apps_["matchstick"]["deck"] = "carousel"
        return "social/apps.yaml", "apps.matchstick.deck"
    raise AssertionError(how)


@pytest.mark.parametrize("how", ["capability", "cost_verb", "weights_sum", "intent_missing", "archetype_missing",
                                 "intent_zero", "archetype_negative", "intent_unknown", "archetype_unknown",
                                 "looking_for_pair", "like_back_base", "likes_you_hours", "deck"])
def test_a_broken_apps_yaml_is_an_error_naming_its_key(tmp_path, how) -> None:
    import yaml

    from engine import yamlio
    from engine.games import registry
    from engine.games.validation import StoryValidator

    for path in SOCIAL_DIR.glob("*.yaml"):
        shutil.copy(path, tmp_path / path.name)
    data = copy.deepcopy(yamlio.safe_load((SOCIAL_DIR / "apps.yaml").read_text(encoding="utf-8")))
    source, key = _break(data, how)
    (tmp_path / "apps.yaml").write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    validator = StoryValidator(registry.get("read-receipts"))
    validator._check_apps(tmp_path)
    validator._check_behaviours(tmp_path)
    named = {(i.source, i.ref_id) for i in validator.issues if i.severity == "error"}
    assert (source, key) in named, validator.issues


def test_a_like_comment_template_naming_an_unknown_field_is_an_error(tmp_path) -> None:
    import yaml

    from engine import yamlio
    from engine.games import registry
    from engine.games.validation import StoryValidator

    data = yamlio.safe_load((SOCIAL_DIR / "population.yaml").read_text(encoding="utf-8"))
    data["like_comments"]["terse_busy"] = ["hi {player_name}"]
    (tmp_path / "population.yaml").write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    validator = StoryValidator(registry.get("read-receipts"))
    validator._check_population(tmp_path)
    assert ("social/population.yaml", "like_comments.terse_busy") in {
        (i.source, i.ref_id) for i in validator.issues if i.severity == "error"}


def test_an_unmatched_person_is_gone_from_every_app(receipts_state, monkeypatch) -> None:
    """Review T7 I1: one rule for an unmatched person on both paths -- the deck and Likes you."""
    from engine.game import clock
    from engine.game.effects import apply_effect
    from engine.social import apps, matching, population

    pid = _overlap_pid(receipts_state)
    real_top, real_order = apps.top_card, apps.order
    monkeypatch.setattr(matching, "likes_back", lambda *a, **k: True)
    monkeypatch.setattr(apps, "top_card", lambda state, name: pid)
    assert matching.like(receipts_state, "matchstick", pid)["ok"]
    clock.advance_time(receipts_state, 24 * 4)
    monkeypatch.setattr(apps, "top_card", real_top)
    assert matching.thread_id("matchstick", pid) in receipts_state.social["threads"]
    # They were waiting in Front Porch's Likes you when the player unmatched them on Matchstick.
    apply_effect(receipts_state, {"type": "social_app", "app": "front_porch", "op": "liked_by",
                                  "row": {"pid": pid, "comment": "hi", "at": receipts_state.world_clock_hours}})
    assert _act(receipts_state, "unmatch", target=pid)["success"]
    assert all(r["pid"] != pid for r in apps.likes_you(receipts_state, "front_porch"))
    assert apps.gone(receipts_state, pid)
    # Never dealt on Front Porch ...
    assert apps.touched(receipts_state, pid, "front_porch")
    monkeypatch.setattr(apps, "order", lambda state, name, day: [population.index_of(pid)] + real_order(state, name, day))
    assert apps.top_card(receipts_state, "front_porch") != pid
    # ... never queued into its Likes you ...
    clock.advance_time(receipts_state, 24 * 2)
    assert all(r["pid"] != pid for r in apps.likes_you(receipts_state, "front_porch"))
    # ... and never likable back there, even from a row that slipped in.
    apply_effect(receipts_state, {"type": "social_app", "app": "front_porch", "op": "liked_by",
                                  "row": {"pid": pid, "comment": "hi", "at": receipts_state.world_clock_hours}})
    refused = matching.like_back(receipts_state, "front_porch", pid)
    assert refused["ok"] is False and refused["error"]
    assert matching.thread_id("front_porch", pid) not in receipts_state.social["threads"]
