"""
This or That (v0.22.0 spec §21.2, T23): five either/or pairs dealt from the
games.yaml bank, the player's five answers in one `game_move`, the person's
picks derived by the engine from their hobbies, traits and personality plus
seeded noise (rule 1), on their own clock, and the reveal: the agreements
written as canon both ways in the engine's words, their reaction queued as a
due `game_banter` message, and each agreement's familiarity and interest.

Also T23's two carried items: the person's own daily invite
(`behaviours.yaml` `games.invite_prob_per_day`, a `daily` draw on
SOCIAL_GAME) and which game an invite asks for (no draw: the one the pair
has played least).
"""

from __future__ import annotations

import copy
import dataclasses
from typing import Any

import pytest

from tests.social_fixtures import (  # noqa: F401
    _act, _force_stage, matched, receipts_active, receipts_state,
)


def _spec() -> dict[str, Any]:
    from engine import social

    return social.data("games")["this_or_that"]


def _person_with(*, hobbies: tuple[str, ...], traits: tuple[str, ...] = (), **sliders: int):
    """A generated person with these hobbies and traits, every personality slider 3 (neutral) but those given."""
    from engine import social
    from engine.social import population

    person = population.person(1, 0)
    names = [str(n) for n in social.data("population")["personality"]]
    assert set(sliders) <= set(names)
    return dataclasses.replace(person, hobbies=tuple(hobbies), traits=tuple(traits),
                              personality=tuple((n, int(sliders.get(n, 3))) for n in names))


def _pair(a: str, a_tags: list[str], b: str, b_tags: list[str]) -> dict[str, Any]:
    return {"a": {"label": a, "tags": list(a_tags)}, "b": {"label": b, "tags": list(b_tags)}}


def _start(state, pid: str, game: str) -> str:
    """Games open with them (talking), then the player's invite: the game id."""
    _force_stage(state, pid, "talking")
    receipt = _act(state, "game_invite", target=pid, args={"game": game})
    assert receipt["success"], receipt
    return receipt["result"]["game_id"]


def _answer(state, game_id: str, answers: list[str]) -> dict[str, Any]:
    """The player's five answers, through the phone's catalogue and executor."""
    receipt = _act(state, "game_move", target=game_id, args={"move": "answer", "answers": list(answers)})
    assert receipt["success"], receipt
    return receipt


def _force_their_answers(state, game_id: str, answers: list[str]) -> None:
    """Their picks, set through the `social_game` effect (a move by them), in place of the engine's draw."""
    from engine.game.effects import apply_effect

    moved = apply_effect(state, {"type": "social_game", "op": "move", "game_id": game_id, "by": "them",
                                 "args": {"move": "answer", "answers": list(answers)}})
    assert moved["ok"], moved


def _row(state, game_id: str) -> dict[str, Any]:
    return state.social["games"][game_id]


def _banter(state, pid: str) -> list[dict[str, Any]]:
    from engine.social import messaging

    tid = messaging.thread_for(state, pid)
    return [m for m in state.social["threads"][tid]["messages"]
            if (m.get("decision") or {}).get("situation") == "game_banter"]


# -- the brief's tests ------------------------------------------------------------------------------


def test_their_answers_follow_their_profile(receipts_active) -> None:
    from engine.game.rng import stable_rng
    from engine.social.games import this_or_that

    outdoorsy = _person_with(hobbies=("climbing", "hiking"), adventurous=5)
    pairs = [_pair("mountains", ["outdoors"], "beaches", ["lazy"])] * 5
    picks = [this_or_that.their_answers(outdoorsy, pairs, stable_rng(1, f"t{i}"))[0] for i in range(200)]
    assert picks.count("a") > 150


def test_the_reveal_writes_canon_both_ways_in_engine_words(receipts_state, matched) -> None:
    from engine.social.games import this_or_that

    pid = matched("matchstick").split(":")[1]
    game_id = _start(receipts_state, pid, "this_or_that")
    _answer(receipts_state, game_id, ["a"] * 5)
    _force_their_answers(receipts_state, game_id, ["a", "a", "b", "a", "b"])
    out = this_or_that.reveal(receipts_state, game_id)
    assert out["agreements"] == 3
    person = receipts_state.social["people"][pid]
    assert any(line.startswith("You both pick") for line in person["memory"]["canon"])
    assert any(line.startswith("You both pick") for line in person["memory"]["knows"])
    pairs = _row(receipts_state, game_id)["pairs"]
    expected = [f"You both pick {pairs[i]['a']['label']} over {pairs[i]['b']['label']}" for i in (0, 1, 3)]
    assert out["agreed"] == expected                                             # the engine's words, exactly
    assert [line for line in person["memory"]["canon"] if line.startswith("You both pick")] == expected
    assert [line for line in person["memory"]["knows"] if line.startswith("You both pick")] == expected


def test_the_reveal_queues_their_reaction(receipts_state, matched) -> None:
    from engine.game import clock
    from engine.social.games import this_or_that

    state = receipts_state
    pid = matched("matchstick").split(":")[1]
    game_id = _start(state, pid, "this_or_that")
    _answer(state, game_id, ["a"] * 5)
    _force_their_answers(state, game_id, ["b"] * 5)
    assert not _banter(state, pid)
    assert this_or_that.reveal(state, game_id)["ok"]
    queued = [e for e in state.social["queue"] if (e.get("decision") or {}).get("situation") == "game_banter"]
    assert len(queued) == 1 and queued[0]["decision"]["game_id"] == game_id
    clock.advance_time(state, queued[0]["at"] - state.world_clock_hours + 1 / 60)
    (due,) = _banter(state, pid)
    assert due["voiced"] is False and due["decision"]["situation"] == "game_banter"
    assert due["decision"]["game_id"] == game_id
    assert this_or_that.reveal(state, game_id)["ok"] is False                  # once: the game is over
    assert len(_banter(state, pid)) == 1


@pytest.mark.parametrize("theirs, agreements", [(["a", "a", "b", "a", "b"], 3), (["b"] * 5, 0)])
def test_agreements_add_familiarity_and_interest(receipts_state, matched, theirs, agreements) -> None:
    from engine.social.games import this_or_that

    state = receipts_state
    pid = matched("matchstick").split(":")[1]
    game_id = _start(state, pid, "this_or_that")
    person = state.social["people"][pid]
    exchanges, interest = int(person["familiarity"]["exchanges"]), int(person["interest"])
    _answer(state, game_id, ["a"] * 5)
    _force_their_answers(state, game_id, theirs)
    assert this_or_that.reveal(state, game_id)["agreements"] == agreements
    effects = _spec()["effects"]
    finished = effects["finished"]
    assert person["familiarity"]["exchanges"] == \
        exchanges + finished["familiarity"] + agreements * effects["agree_familiarity"]
    assert person["interest"] == min(100, interest + finished["interest"] + agreements * effects["agree_interest"])
    row = _row(state, game_id)
    assert row["status"] == "finished" and row["winner"] is None
    assert all("tags" not in pair[side] for pair in row["pairs"] for side in ("a", "b"))   # compacted


@pytest.mark.parametrize("answers", [["a"] * 4, ["a"] * 6, ["a", "b", "c", "a", "b"]])
def test_answers_must_be_five_a_or_b(receipts_state, matched, answers) -> None:
    state = receipts_state
    pid = matched("matchstick").split(":")[1]
    game_id = _start(state, pid, "this_or_that")
    at = state.world_clock_hours
    receipt = _act(state, "game_move", target=game_id, args={"move": "answer", "answers": answers})
    assert receipt["refused"] is True and "answers" in receipt["result"]["error"]
    row = _row(state, game_id)
    assert row["picks"] == {"player": None, "them": None} and row["turn"] == "player"
    assert state.world_clock_hours == at                                        # no minutes spent


# -- the deal, the judge and the whole round on in-game time -------------------------------------------


def test_a_game_deals_five_different_pairs_seeded_by_its_id(receipts_active) -> None:
    from engine.social.games import this_or_that

    one, again, other = this_or_that.deal(7, "g1"), this_or_that.deal(7, "g1"), this_or_that.deal(7, "g2")
    assert one == again and one != other
    assert len(one) == 5 and len({p["a"]["label"] for p in one}) == 5
    bank = [(p["a"]["label"], p["b"]["label"]) for p in _spec()["pairs"]]
    assert all((p["a"]["label"], p["b"]["label"]) in bank for p in one)


def test_the_bank_has_sixty_pairs_whose_tags_link_to_the_population(receipts_active) -> None:
    from engine import social
    from engine.social.games import this_or_that

    block = _spec()
    assert len(block["pairs"]) >= 60
    assert this_or_that.data_faults(block, social.data("population")) == []
    tags = block["tags"]
    assert any(t.get("hobbies") for t in tags.values()) and any(t.get("traits") for t in tags.values())
    assert any(t.get("sliders") for t in tags.values())


def test_the_data_checks_name_the_fault(receipts_active) -> None:
    from engine import social
    from engine.social.games import this_or_that

    population = social.data("population")
    bad = copy.deepcopy(_spec())
    bad["pairs"] = bad["pairs"][:59]
    assert ("this_or_that.pairs", "must list at least 60 pairs, not 59") in this_or_that.data_faults(bad, population)
    bad = copy.deepcopy(_spec())
    bad["pairs"][0]["a"]["tags"] = ["nowhere"]
    assert ("this_or_that.pairs[0].a", "unknown tag 'nowhere' (this_or_that.tags)") in \
        this_or_that.data_faults(bad, population)
    bad = copy.deepcopy(_spec())
    bad["tags"]["outdoors"]["hobbies"] = ["skydiving"]
    assert ("this_or_that.tags.outdoors", "unknown hobby 'skydiving' (population.yaml hobbies)") in \
        this_or_that.data_faults(bad, population)
    bad = copy.deepcopy(_spec())
    del bad["effects"]["agree_interest"]
    with pytest.raises(ValueError, match="games.yaml: this_or_that.effects.agree_interest"):
        this_or_that.check_data(bad, population)


def test_the_judge_refuses_out_of_turn_and_foreign_moves(receipts_state, matched) -> None:
    state = receipts_state
    pid = matched("matchstick").split(":")[1]
    game_id = _start(state, pid, "this_or_that")
    tiles = _act(state, "game_move", target=game_id, args={"move": "pass"})
    assert tiles["refused"] and tiles["result"]["error"] == "That isn't a move in This or That."
    _answer(state, game_id, ["a", "b", "a", "b", "a"])
    late = _act(state, "game_move", target=game_id, args={"move": "answer", "answers": ["a"] * 5})
    assert late["refused"] and late["result"]["error"] == "It's not your turn"
    assert _row(state, game_id)["picks"]["player"] == ["a", "b", "a", "b", "a"]


def test_they_answer_on_their_own_clock_and_the_reveal_follows(receipts_state, matched) -> None:
    """The whole round: the player answers, their `game_move` falls due at their pace, the engine draws
    their picks, the reveal ends the game, writes the canon and lands their reaction as a due message."""
    from engine.game import clock

    state = receipts_state
    pid = matched("matchstick").split(":")[1]
    game_id = _start(state, pid, "this_or_that")
    _answer(state, game_id, ["a"] * 5)
    assert _row(state, game_id)["picks"]["them"] is None                     # drawn only after the player's
    due = [e for e in state.social["queue"] if e["kind"] == "game_move" and e.get("game_id") == game_id]
    assert len(due) == 1 and due[0]["pid"] == pid
    clock.advance_time(state, due[0]["at"] - state.world_clock_hours + 1 / 60)
    row = _row(state, game_id)
    assert row["status"] == "finished" and len(row["picks"]["them"]) == 5
    assert [m["kind"] for m in row["moves"]] == ["answer", "answer", "reveal"]
    assert row["agreed"] == [i for i in range(5) if row["picks"]["them"][i] == "a"]
    assert any(n["kind"] == "game_move" and n["preview"].endswith("answered This or That")
               for n in state.social["notifications"])
    clock.advance_time(state, 1 / 60)
    (banter,) = _banter(state, pid)
    assert banter["decision"]["game_id"] == game_id
    canon = [line for line in state.social["people"][pid]["memory"]["canon"] if line.startswith("You both pick")]
    assert len(canon) == len(row["agreed"])


def test_their_picks_replay_from_the_seed(receipts_active, monkeypatch) -> None:
    """Two runs of one seed and the same answers: the same deal, the same picks, at the same time."""
    from engine.game import clock, procgen
    from engine.social import matching, population

    monkeypatch.setattr(matching, "likes_back", lambda *a, **k: True)
    results = []
    for _ in range(2):
        population.reset_profiles()
        state = procgen.new_game_state(player_name="Sam", seed=4242)
        pid = matching.apps.top_card(state, "matchstick")
        assert matching.like(state, "matchstick", pid)["ok"]
        seen = [e for e in state.social["queue"] if e["kind"] == "see_like" and e["pid"] == pid][0]
        clock.advance_time(state, seen["at"] - state.world_clock_hours)
        game_id = _start(state, pid, "this_or_that")
        _answer(state, game_id, ["a", "b", "a", "b", "a"])
        due = [e for e in state.social["queue"] if e["kind"] == "game_move"][0]
        clock.advance_time(state, due["at"] - state.world_clock_hours + 1 / 60)
        row = _row(state, game_id)
        results.append((due["at"], row["pairs"], row["picks"], row["agreed"]))
    assert results[0] == results[1]


def test_the_banter_is_voiced_with_the_engines_line_about_the_reveal(receipts_state, matched) -> None:
    from engine.social import messaging, voicing
    from engine.game import clock
    from engine.social.games import this_or_that

    state = receipts_state
    pid = matched("matchstick").split(":")[1]
    game_id = _start(state, pid, "this_or_that")
    _answer(state, game_id, ["a"] * 5)
    _force_their_answers(state, game_id, ["a", "b", "b", "b", "b"])
    this_or_that.reveal(state, game_id)
    clock.advance_time(state, 1 / 60)
    snap = voicing.snapshot_of(state, messaging.thread_for(state, pid))
    pairs = _row(state, game_id)["pairs"]
    note = snap.games[game_id]
    assert note.startswith("This or That: you agree on 1 of 5.")
    assert f"You both pick {pairs[0]['a']['label']} over {pairs[0]['b']['label']}." in note
    assert f"you picked {pairs[1]['b']['label']}, they picked {pairs[1]['a']['label']}" in note
    assert f"The game: {note}" in voicing.messages(snap)[-1]["content"]


def test_the_games_section_shows_their_picks_only_after_the_reveal(receipts_state, matched) -> None:
    from engine.social import payload
    from engine.social.games import this_or_that

    state = receipts_state
    pid = matched("matchstick").split(":")[1]
    game_id = _start(state, pid, "this_or_that")
    _answer(state, game_id, ["a"] * 5)
    _force_their_answers(state, game_id, ["b", "a", "b", "a", "b"])
    (shown,) = payload.phone_block(state)["games"]
    assert shown["label"] == "This or That" and len(shown["pairs"]) == 5
    assert shown["mine"] == ["a"] * 5 and shown["theirs"] is None and shown["agreements"] is None
    assert "picks" not in shown and shown["turn"] == "them"
    this_or_that.reveal(state, game_id)
    (shown,) = payload.phone_block(state)["games"]
    assert shown["theirs"] == ["b", "a", "b", "a", "b"] and shown["agreements"] == 2
    assert shown["status"] == "finished" and shown["winner"] is None


def test_resign_ends_a_this_or_that_game_with_no_effects(receipts_state, matched) -> None:
    state = receipts_state
    pid = matched("matchstick").split(":")[1]
    game_id = _start(state, pid, "this_or_that")
    _answer(state, game_id, ["a"] * 5)
    person = state.social["people"][pid]
    interest = int(person["interest"])
    assert _act(state, "game_move", target=game_id, args={"move": "resign"})["success"]
    assert _row(state, game_id)["status"] == "resigned" and int(person["interest"]) == interest
    assert not [e for e in state.social["queue"] if e["kind"] == "game_move"]


# -- carried from T22: which game they ask for, and their own daily invite ------------------------------


def test_their_invite_asks_for_the_game_the_pair_has_played_least(receipts_state, matched) -> None:
    """No draw (spec §10.5's table): ties go to apps.yaml's `offers` order, then the game played least."""
    from engine.social import games, relationships

    state = receipts_state
    pid = matched("matchstick").split(":")[1]
    _force_stage(state, pid, "talking")
    assert games.offered() == ("wordgame", "this_or_that")
    assert games.proposed_game(state, pid) == "wordgame"                       # none played: the first offered
    gid = _start(state, pid, "wordgame")
    assert _act(state, "game_move", target=gid, args={"move": "resign"})["success"]
    assert games.proposed_game(state, pid) == "this_or_that"                  # wordgame once, this_or_that never
    rid = relationships.apply_proposal(state, pid, "invite_game")["request_id"]
    assert state.social["requests"][rid]["game"] == "this_or_that"


def _first_daily(state) -> float:
    return min(e["at"] for e in state.social["queue"] if e["kind"] == "daily")


def _force_waking(monkeypatch, pid: str, at: float, *, asleep: bool, wakes: float = 3.0) -> None:
    """At the hour `at` (the morning's `daily`) `pid` is asleep (waking `wakes` hours later) or awake;
    every other person and hour reads their real schedule."""
    from engine.social import behaviour

    real_status, real_awake = behaviour.status_at, behaviour.next_awake

    def status_at(person, hour):
        if person.pid == pid and abs(float(hour) - at) < 1e-9:
            return "asleep" if asleep else "free"
        return real_status(person, hour)

    def next_awake(person, hour):
        if person.pid == pid and abs(float(hour) - at) < 1e-9:
            return at + wakes if asleep else at
        return real_awake(person, hour)

    monkeypatch.setattr(behaviour, "status_at", status_at)
    monkeypatch.setattr(behaviour, "next_awake", next_awake)


@pytest.mark.parametrize("asleep", [True, False])
def test_their_daily_invite_is_drawn_each_morning_and_lands_as_a_request(receipts_state, matched,
                                                                         monkeypatch, asleep) -> None:
    """`games.invite_prob_per_day`: a `daily` draw on SOCIAL_GAME queues their invite (a `game_move`
    event, `invite: true`) for the morning's hour, or for their waking when they are asleep then; when it
    lands it is the `invite_game` proposal, re-checked, with a notification."""
    from engine.game import clock
    from engine.social import games

    state = receipts_state
    pid = matched("matchstick").split(":")[1]
    _force_stage(state, pid, "talking")
    monkeypatch.setattr(games, "_invite_prob", lambda *a: 1.0)
    daily = _first_daily(state)
    _force_waking(monkeypatch, pid, daily, asleep=asleep)
    clock.advance_time(state, daily - state.world_clock_hours + 1 / 60)
    queued = [e for e in state.social["queue"] if e["kind"] == "game_move" and e.get("invite")]
    games_asked = [r for r in state.social["requests"].values() if r["what"] == "game"]
    if asleep:                                                 # forced: both paths run, one per parameter
        assert len(queued) == 1 and queued[0]["pid"] == pid and queued[0]["at"] == pytest.approx(daily + 3.0)
        assert not games_asked                                 # nothing until they wake
        clock.advance_time(state, queued[0]["at"] - state.world_clock_hours + 1 / 60)
    else:
        assert not queued                                      # landed in the same advance, at the morning's hour
    (request,) = [r for r in state.social["requests"].values() if r["what"] == "game"]
    assert request["from"] == "them" and request["pid"] == pid and request["game"] == "wordgame"
    assert request["at"] == pytest.approx(daily + 3.0 if asleep else daily)
    assert any(n["kind"] == "game_invite" and n["pid"] == pid for n in state.social["notifications"])
    clock.advance_time(state, 24.0)                            # asked: no second invite
    assert len([r for r in state.social["requests"].values() if r["what"] == "game"]) == 1


@pytest.mark.parametrize("why", ["ghosted", "gone", "running", "asked"])
def test_no_daily_invite_from_someone_ghosted_gone_playing_or_already_asking(receipts_state, matched,
                                                                              monkeypatch, why) -> None:
    from engine.game import clock
    from engine.social import games, relationships
    from tests.social_fixtures import _set_person

    state = receipts_state
    pid = matched("matchstick").split(":")[1]
    _force_stage(state, pid, "talking")
    monkeypatch.setattr(games, "_invite_prob", lambda *a: 1.0)
    if why == "ghosted":
        _set_person(state, pid, ghosted=True)
    elif why == "gone":
        assert _act(state, "unmatch", target=pid)["success"]
    elif why == "running":
        _start(state, pid, "this_or_that")
    else:
        assert relationships.apply_proposal(state, pid, "invite_game")["ok"]
    asked = len([r for r in state.social["requests"].values() if r["what"] == "game"])
    daily = _first_daily(state)
    clock.advance_time(state, daily - state.world_clock_hours + 1 / 60)
    assert not [e for e in state.social["queue"] if e["kind"] == "game_move" and e.get("invite")]
    assert len([r for r in state.social["requests"].values() if r["what"] == "game"]) == asked


# -- the review's fixes (T23 fix round 1) ----------------------------------------------------------------


def test_a_ghosted_persons_this_or_that_is_rearmed_and_then_answered(receipts_state, matched) -> None:
    from engine.game import clock
    from engine.social import games
    from tests.social_fixtures import _set_person

    state = receipts_state
    pid = matched("matchstick").split(":")[1]
    game_id = _start(state, pid, "this_or_that")
    _answer(state, game_id, ["a"] * 5)
    _set_person(state, pid, ghosted=True)
    due = [e for e in state.social["queue"] if e["kind"] == "game_move"][0]
    clock.advance_time(state, due["at"] - state.world_clock_hours + 1 / 60)
    assert _row(state, game_id)["turn"] == "them" and _row(state, game_id)["picks"]["them"] is None
    assert not [e for e in state.social["queue"] if e["kind"] == "game_move"]       # spent while ghosted
    _set_person(state, pid, ghosted=False)
    assert games.rearm(state, pid, state.world_clock_hours) == 1
    (queued,) = [e for e in state.social["queue"] if e["kind"] == "game_move" and e.get("game_id") == game_id]
    clock.advance_time(state, queued["at"] - state.world_clock_hours + 1 / 60)
    assert _row(state, game_id)["status"] == "finished"


def test_a_this_or_that_whose_person_left_is_abandoned_in_the_morning(receipts_state, matched) -> None:
    from engine.game import clock

    state = receipts_state
    pid = matched("matchstick").split(":")[1]
    game_id = _start(state, pid, "this_or_that")
    assert _act(state, "unmatch", target=pid)["success"]
    clock.advance_time(state, 24.0)
    row = _row(state, game_id)
    assert row["status"] == "abandoned" and row["picks"]["them"] is None


def test_a_move_refused_with_no_pass_to_fall_back_on_abandons_the_game(receipts_state, matched, monkeypatch,
                                                                        caplog) -> None:
    """M1: their move refused by its own judge, and This or That has no pass: the game is abandoned through
    the effect, at ERROR, never left on their turn."""
    import logging

    from engine.game import clock
    from engine.social.games import this_or_that

    state = receipts_state
    pid = matched("matchstick").split(":")[1]
    game_id = _start(state, pid, "this_or_that")
    _answer(state, game_id, ["a"] * 5)
    monkeypatch.setattr(this_or_that, "their_move", lambda *a, **k: {"move": "answer", "answers": ["c"] * 5})
    due = [e for e in state.social["queue"] if e["kind"] == "game_move"][0]
    with caplog.at_level(logging.ERROR, logger="engine.social.games"):
        clock.advance_time(state, due["at"] - state.world_clock_hours + 1 / 60)
    row = _row(state, game_id)
    assert row["status"] == "abandoned" and row["picks"]["them"] is None
    assert any("abandoned" in r.getMessage() and game_id in r.getMessage() for r in caplog.records
               if r.levelno == logging.ERROR)
    assert not [e for e in state.social["queue"] if e["kind"] == "game_move"]
    assert _act(state, "game_invite", target=pid, args={"game": "this_or_that"})["success"]   # the pair is free


def test_a_failed_reveal_abandons_the_game(receipts_state, matched, monkeypatch, caplog) -> None:
    """M1: their answer lands but the reveal fails: abandoned at ERROR, never left at `reveal`."""
    import logging

    from engine.game import clock
    from engine.social.games import this_or_that

    state = receipts_state
    pid = matched("matchstick").split(":")[1]
    game_id = _start(state, pid, "this_or_that")
    _answer(state, game_id, ["a"] * 5)
    monkeypatch.setattr(this_or_that, "reveal", lambda *a, **k: {"ok": False, "error": "forced"})
    due = [e for e in state.social["queue"] if e["kind"] == "game_move"][0]
    with caplog.at_level(logging.ERROR, logger="engine.social.games"):
        clock.advance_time(state, due["at"] - state.world_clock_hours + 1 / 60)
    row = _row(state, game_id)
    assert row["status"] == "abandoned" and row["turn"] == "reveal"
    assert any("the reveal failed" in r.getMessage() for r in caplog.records if r.levelno == logging.ERROR)
    assert not _banter(state, pid)


def test_no_daily_invite_when_the_draw_says_no_or_games_are_closed(receipts_state, matched, monkeypatch) -> None:
    from engine.game import clock
    from engine.social import games

    state = receipts_state
    pid = matched("matchstick").split(":")[1]                                 # matched: games not open yet
    monkeypatch.setattr(games, "_invite_prob", lambda *a: 1.0)
    clock.advance_time(state, 30.0)
    assert not [r for r in state.social["requests"].values() if r["what"] == "game"]
    _force_stage(state, pid, "talking")
    monkeypatch.setattr(games, "_invite_prob", lambda *a: 0.0)
    clock.advance_time(state, 30.0)
    assert not [r for r in state.social["requests"].values() if r["what"] == "game"]
    assert not [e for e in state.social["queue"] if e["kind"] == "game_move"]


@pytest.mark.parametrize("archetype", ["needy", "banterer", "slow_burner"])
def test_the_draw_reads_their_archetypes_invite_prob(receipts_state, matched, monkeypatch, archetype) -> None:
    """The key is read (rule 9): the draw's chance is the person's archetype's `games.invite_prob_per_day`."""
    from engine import social
    from engine.social import games
    from tests.social_fixtures import _force_archetype

    state = receipts_state
    pid = matched("matchstick").split(":")[1]
    rows = social.data("behaviours")["archetypes"]
    _force_archetype(monkeypatch, state, pid, archetype)
    assert games._invite_prob(state, pid) == rows[archetype]["games"]["invite_prob_per_day"]
