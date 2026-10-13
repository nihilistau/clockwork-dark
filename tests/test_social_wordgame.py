"""
Tile Talk (v0.22.0 spec §21.1, T22): the board, the bag, scoring and
validation, the person's bounded search, turns on in-game time, and what a
finished game does to the relationship. The engine judges and scores every
move (rule 1); the person's search is bounded by NODES, its wall time printed
and never asserted.
"""

from __future__ import annotations

import time
import tracemalloc
from typing import Any

import pytest

from tests.social_fixtures import (  # noqa: F401
    _act, _force_archetype, _force_stage, matched, matched_numbers, receipts_active, receipts_state,
)


def _spec() -> dict[str, Any]:
    from engine import social

    return social.data("games")["wordgame"]


def _empty_game(rack: str = "catries") -> dict[str, Any]:
    """An empty 11x11 board from games.yaml (its centre `*`), the player to move with ``rack``."""
    spec = _spec()
    assert spec["premiums"][5][5] == "*"
    return {"board": ["." * spec["size"]] * spec["size"], "racks": {"player": rack, "them": ""},
            "bag": "", "turn": "player", "scores": {"player": 0, "them": 0}, "scoreless": 0}


def _expected_score(word: str, game: dict[str, Any], tiles: list[dict[str, Any]]) -> int:
    """One word laid on an empty board, scored by hand from games.yaml (independent of the engine's scorer)."""
    spec = _spec()
    letter_mult = {".": 1, "*": 1, "l": 2, "L": 3, "w": 1, "W": 1}
    word_mult = {".": 1, "*": 1, "l": 1, "L": 1, "w": 2, "W": 3}
    assert "".join(t["letter"] for t in tiles) == word
    total, mult = 0, 1
    for t in tiles:
        square = spec["premiums"][t["y"]][t["x"]]
        value = 0 if t.get("blank") else spec["letters"][t["letter"]]["value"]
        total += value * letter_mult[square]
        mult *= word_mult[square]
    return total * mult + (spec["bingo_bonus"] if len(tiles) == spec["rack"] else 0)


def _across(word: str, x: int, y: int, blanks: tuple[int, ...] = ()) -> list[dict[str, Any]]:
    tiles = []
    for i, letter in enumerate(word):
        tile: dict[str, Any] = {"x": x + i, "y": y, "letter": letter}
        if i in blanks:
            tile["blank"] = True
        tiles.append(tile)
    return tiles


def _midgame_fixture() -> dict[str, Any]:
    """HOUSE across the centre row and OX down through its O; the player to move with AEIRSTL."""
    game = _empty_game("aeirstl")
    board = [list(row) for row in game["board"]]
    for i, letter in enumerate("house"):
        board[5][3 + i] = letter
    board[6][4] = "x"
    game["board"] = ["".join(row) for row in board]
    return game


# -- validation and scoring (rule 1) ---------------------------------------------------------------


def test_a_legal_first_move_scores_with_premiums(receipts_active) -> None:
    from engine.social.games import wordgame

    game = _empty_game()                                         # an 11x11 board from games.yaml, centre square marked
    tiles = [{"x": 5, "y": 5, "letter": "c"}, {"x": 6, "y": 5, "letter": "a"}, {"x": 7, "y": 5, "letter": "t"}]
    score, reason = wordgame.validate_move(game, tiles, frozenset({"cat"}))
    assert reason == "" and score == _expected_score("cat", game, tiles)


def test_a_premium_square_multiplies(receipts_active) -> None:
    """CRATE across x=1..5 of the centre row: its C on the triple-letter square at x=1 counts three times."""
    from engine.social.games import wordgame

    game = _empty_game("crateqq")
    tiles = _across("crate", 1, 5)
    assert _spec()["premiums"][5][1] == "L"
    score, reason = wordgame.validate_move(game, tiles, frozenset({"crate"}))
    values = _spec()["letters"]
    assert reason == "" and score == _expected_score("crate", game, tiles) == \
        3 * values["c"]["value"] + sum(values[c]["value"] for c in "rate")


@pytest.mark.parametrize("tiles, reason", [
    ([{"x": 0, "y": 0, "letter": "a"}], "The first word must cross the centre."),
    ([{"x": 5, "y": 5, "letter": "q"}, {"x": 6, "y": 5, "letter": "x"}], "qx is not a word."),
    ([{"x": 5, "y": 5, "letter": "a"}, {"x": 7, "y": 5, "letter": "t"}], "Tiles must be in one unbroken line."),
    ([{"x": 5, "y": 5, "letter": "z"}], "You don't have a z."),
])
def test_illegal_moves_are_refused_with_a_reason(receipts_active, tiles, reason) -> None:
    from engine.social.games import wordgame

    game = _empty_game(rack="catqxa")
    assert wordgame.validate_move(game, tiles, frozenset({"cat", "at"})) == (None, reason)


@pytest.mark.parametrize("tiles, reason", [
    ([{"x": 5, "y": 5, "letter": "a"}], "A word needs at least two letters."),
    ([{"x": 5, "y": 5, "letter": "c"}, {"x": 6, "y": 6, "letter": "a"}], "Tiles must be in one unbroken line."),
    ([{"x": 11, "y": 5, "letter": "a"}], "That's off the board."),
    ([{"x": 5, "y": 5}], "That isn't a move."),
    ([], "That isn't a move."),
    ([{"x": 5, "y": 5, "letter": "a", "blank": True}, {"x": 6, "y": 5, "letter": "t"}], "You don't have a blank."),
])
def test_more_illegal_moves_each_have_their_reason(receipts_active, tiles, reason) -> None:
    from engine.social.games import wordgame

    assert wordgame.validate_move(_empty_game(rack="catqxa"), tiles, frozenset({"cat", "at"})) == (None, reason)


def test_a_later_word_must_join_the_board_and_every_cross_word_counts(receipts_active) -> None:
    from engine.social.games import wordgame

    game = _midgame_fixture()
    words = frozenset({"house", "ox", "at", "as", "ta", "hat"})
    assert wordgame.validate_move(game, _across("at", 0, 0), words) == (None, wordgame.JOIN_THE_BOARD)
    assert wordgame.validate_move(game, [{"x": 3, "y": 5, "letter": "a"}], words) == (None, "That square is taken.")
    # A below H (x=3, y=6) makes HA down and AX across: AX is not in this word list.
    assert wordgame.validate_move(game, [{"x": 3, "y": 6, "letter": "a"}], words) == (None, "ax is not a word.")
    score, reason = wordgame.validate_move(game, [{"x": 3, "y": 6, "letter": "a"}], words | {"ax", "ha"})
    values = _spec()["letters"]
    assert _spec()["premiums"][6][3] == "."                       # a plain square: no premium either way
    ha = values["h"]["value"] + values["a"]["value"]
    ax = values["a"]["value"] + values["x"]["value"]
    assert reason == "" and score == ha + ax                      # each word scored whole, H and X included


def test_a_new_tiles_premium_counts_in_both_its_words_an_old_tiles_in_neither(receipts_active) -> None:
    """A on (2, 6), a double-word square, with H above it and X beside it: HA and AX are each doubled.
    Then H on that square already and A beside it: HA is not doubled (a premium is spent once played)."""
    from engine.social.games import wordgame

    spec = _spec()
    values = spec["letters"]
    assert spec["premiums"][6][2] == "w" and spec["premiums"][6][3] == "."
    words = frozenset({"ha", "ax"})
    game = _empty_game("aaaaaaa")
    board = [list(row) for row in game["board"]]
    board[5][2], board[6][3] = "h", "x"
    game["board"] = ["".join(row) for row in board]
    score, reason = wordgame.validate_move(game, [{"x": 2, "y": 6, "letter": "a"}], words)
    ha = values["h"]["value"] + values["a"]["value"]
    ax = values["a"]["value"] + values["x"]["value"]
    assert reason == "" and score == 2 * ha + 2 * ax
    old = _empty_game("aaaaaaa")
    board = [list(row) for row in old["board"]]
    board[6][2] = "h"
    old["board"] = ["".join(row) for row in board]
    score, reason = wordgame.validate_move(old, [{"x": 3, "y": 6, "letter": "a"}], words)
    assert reason == "" and score == ha


def test_the_seven_tile_bonus(receipts_active) -> None:
    from engine.social.games import wordgame

    game = _empty_game("aeirstl")
    tiles = _across("retails", 2, 5)                              # x=2..8, over the centre
    score, reason = wordgame.validate_move(game, tiles, frozenset({"retails"}))
    values = _spec()["letters"]
    plain = sum(values[c]["value"] for c in "retails")
    assert reason == "" and score == _expected_score("retails", game, tiles) == plain + _spec()["bingo_bonus"]
    six_score, _ = wordgame.validate_move(game, _across("retail", 2, 5), frozenset({"retail"}))
    assert six_score == plain - values["s"]["value"]               # six tiles: no bonus


def test_a_blank_scores_zero_and_takes_any_letter(receipts_active) -> None:
    """EATER across x=1..5 of the centre row; its first E a blank on the triple-letter square (0, tripled,
    is 0), then the same word with the blank a plain E and the real E on that square (tripled)."""
    from engine.social.games import wordgame

    values = _spec()["letters"]
    game = _empty_game("ater?ee")
    blank_on_premium = _across("eater", 1, 5, blanks=(0,))
    score, reason = wordgame.validate_move(game, blank_on_premium, frozenset({"eater"}))
    assert reason == "" and score == _expected_score("eater", game, blank_on_premium) == \
        sum(values[c]["value"] for c in "ater")
    blank_plain = _across("eater", 1, 5, blanks=(3,))
    score, reason = wordgame.validate_move(game, blank_plain, frozenset({"eater"}))
    assert reason == "" and score == _expected_score("eater", game, blank_plain) == \
        3 * values["e"]["value"] + sum(values[c]["value"] for c in "atr")
    # Played for real: the board shows the blank as an upper-case letter, and the rack spends its `?`.
    row = {**_empty_game("ater?ee"), "bag": "", "moves": []}
    out = wordgame.apply_move(None, row, "player", {"move": "play", "tiles": blank_plain})
    assert out["ok"] and row["board"][5][1:6] == "eatEr" and "?" not in row["racks"]["player"]


def test_the_bag_is_seeded_per_game(receipts_active) -> None:
    from engine.social.games import wordgame

    one, again, other = (wordgame.shuffled_bag(4242, g) for g in ("g1", "g1", "g2"))
    assert one == again and one != other
    for bag in (one, other):
        assert len(bag) == 72 and bag.count("?") == 2
        assert sorted(bag) == sorted(one)                         # the same tiles, another order
    assert wordgame.shuffled_bag(7, "g1") != one                  # and per run seed


def test_a_new_game_deals_two_racks_of_seven_from_its_bag(receipts_state) -> None:
    from engine.social.games import wordgame

    part = wordgame.new_game(receipts_state, "g1", "p0001")
    bag = wordgame.shuffled_bag(receipts_state.rng_seed, "g1")
    assert part["racks"]["player"] == bag[:7] and part["racks"]["them"] == bag[7:14]
    assert part["bag"] == bag[14:] and len(part["bag"]) == 58 and part["turn"] == "player"
    assert part["board"] == ["." * 11] * 11


# -- the person's search (bounded by nodes) ------------------------------------------------------------


def test_the_persons_search_respects_its_node_budget_and_plays_legally(receipts_active) -> None:
    from engine.social.games import wordgame

    game = _midgame_fixture()
    counter = wordgame.NodeCounter()
    started = time.perf_counter()
    moves = wordgame.best_moves(game, "aeirstl", wordgame.words(), wordgame.prefixes(), node_budget=20000, counter=counter)
    print(f"\n[tile talk] best_moves: {len(moves)} moves, {counter.nodes} nodes, "
          f"{(time.perf_counter() - started) * 1000:.0f} ms (recorded, never asserted)")
    assert counter.nodes <= 20000 and moves
    for _score, placement in moves[:20]:
        assert wordgame.validate_move(game, list(placement), wordgame.words())[0] is not None
    keys = [(-s, tuple((t["x"], t["y"], t["letter"], bool(t.get("blank"))) for t in p)) for s, p in moves]
    assert keys == sorted(keys)                                    # canonical order
    for score, placement in moves[:20]:
        assert wordgame.validate_move(game, list(placement), wordgame.words())[0] == score


def test_a_small_budget_stops_the_search_and_the_same_budget_finds_the_same_moves(receipts_active) -> None:
    from engine.social.games import wordgame

    game = _midgame_fixture()
    small = wordgame.NodeCounter()
    few = wordgame.best_moves(game, "aeirstl", wordgame.words(), wordgame.prefixes(), node_budget=50, counter=small)
    assert small.nodes == 50                                       # stopped AT the budget, never past it
    again = wordgame.best_moves(game, "aeirstl", wordgame.words(), wordgame.prefixes(), node_budget=50)
    assert few == again
    for _score, placement in few:
        assert wordgame.validate_move(game, list(placement), wordgame.words())[0] is not None


def test_pick_move_takes_one_of_the_top_k_for_the_skill(receipts_active) -> None:
    import random

    from engine.social.games import wordgame

    moves = [(50 - i, ({"x": i, "y": 0, "letter": "a"},)) for i in range(20)]
    table = _spec()["top_k_by_skill"]
    assert wordgame.top_k(0.0) == table[0][1] and wordgame.top_k(1.0) == table[-1][1]
    for skill in (0.0, 0.5, 0.95):
        k = wordgame.top_k(skill)
        placements = [p for _s, p in moves]
        picks = {placements.index(wordgame.pick_move(moves, skill, random.Random(n))) for n in range(200)}
        assert picks == set(range(min(k, len(moves))))
    assert wordgame.pick_move([], 0.5, random.Random(1)) is None


def test_the_word_list_is_cached_and_measured(receipts_active, monkeypatch) -> None:
    from engine.social.games import wordgame

    monkeypatch.setattr(wordgame, "_WORDS", None)
    monkeypatch.setattr(wordgame, "_PREFIXES", None)
    tracemalloc.start()
    try:
        started = time.perf_counter()
        words, prefixes = wordgame.words(), wordgame.prefixes()
        seconds = time.perf_counter() - started
        current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    print(f"\n[tile talk] word list: {len(words)} words, {len(prefixes)} prefixes; "
          f"held {current / 2**20:.1f} MiB, peak {peak / 2**20:.1f} MiB, loaded in {seconds:.2f} s (recorded)")
    assert len(words) > 150000
    assert wordgame.words() is words and wordgame.prefixes() is prefixes     # cached
    assert words <= prefixes and "retail" in words and "retai" in prefixes


def test_a_reset_drops_the_word_list_and_the_next_read_reloads_it(receipts_active) -> None:
    from engine.games import caches
    from engine.social.games import wordgame

    first = wordgame.words()
    caches.reset_all_caches()
    assert wordgame._WORDS is None and wordgame._PREFIXES is None
    assert wordgame.words() == first and wordgame.words() is not first


# -- turns on in-game time, through the phone ------------------------------------------------------------


def _talking(state, matched) -> str:
    pid = matched("matchstick").split(":", 1)[1]
    _force_stage(state, pid, "talking")
    return pid


def _row(state, game_id: str) -> dict[str, Any]:
    return state.social["games"][game_id]


def _player_moves(state, game_id: str) -> dict[str, Any]:
    """The player's best play from their rack (the engine's own search), or a pass when there is none."""
    from engine.social.games import wordgame

    row = _row(state, game_id)
    moves = wordgame.best_moves(row, row["racks"]["player"], wordgame.words(), wordgame.prefixes(),
                                node_budget=20000)
    args = {"move": "play", "tiles": [dict(t) for t in moves[0][1]]} if moves else {"move": "pass"}
    return _act(state, "game_move", target=game_id, args=args)


def test_an_invite_starts_a_game_the_player_moves_first(receipts_state, matched) -> None:
    state = receipts_state
    pid = _talking(state, matched)
    before = state.world_clock_hours
    receipt = _act(state, "game_invite", target=pid, args={"game": "wordgame"})
    assert receipt["success"], receipt
    gid = receipt["result"]["game_id"]
    row = _row(state, gid)
    assert gid == "g1" and row["status"] == "active" and row["turn"] == "player" and row["pid"] == pid
    assert state.world_clock_hours == pytest.approx(before + 3 / 60)       # apps.yaml games cost_minutes.move
    again = _act(state, "game_invite", target=pid, args={"game": "wordgame"})
    assert again["refused"] and "already have a game going" in again["result"]["error"]


def test_a_move_out_of_turn_is_refused(receipts_state, matched) -> None:
    state = receipts_state
    pid = _talking(state, matched)
    gid = _act(state, "game_invite", target=pid, args={"game": "wordgame"})["result"]["game_id"]
    played = _player_moves(state, gid)
    assert played["success"], played
    assert _row(state, gid)["turn"] == "them"
    refused = _act(state, "game_move", target=gid, args={"move": "pass"})
    assert refused["refused"] is True and refused["result"]["error"] == "It's not your turn"


def test_an_illegal_play_reaches_the_player_in_words_and_changes_nothing(receipts_state, matched) -> None:
    state = receipts_state
    pid = _talking(state, matched)
    gid = _act(state, "game_invite", target=pid, args={"game": "wordgame"})["result"]["game_id"]
    rack = _row(state, gid)["racks"]["player"]
    tile = {"x": 0, "y": 0, "letter": "e", "blank": True} if rack[0] == "?" else {"x": 0, "y": 0, "letter": rack[0]}
    board, at = list(_row(state, gid)["board"]), state.world_clock_hours
    out = _act(state, "game_move", target=gid, args={"move": "play", "tiles": [tile]})
    assert out["refused"] is True and out["result"]["error"] == "The first word must cross the centre."
    assert _row(state, gid)["board"] == board and _row(state, gid)["turn"] == "player"
    assert _row(state, gid)["racks"]["player"] == rack and state.world_clock_hours == at   # no minutes spent


def test_they_play_on_their_own_clock_and_may_banter(receipts_state, matched, monkeypatch) -> None:
    from engine.game import clock
    from engine.social import games, messaging

    state = receipts_state
    pid = _talking(state, matched)
    gid = _act(state, "game_invite", target=pid, args={"game": "wordgame"})["result"]["game_id"]
    monkeypatch.setattr(games, "_banters", lambda *a, **k: True)           # the draw says so (F16)
    assert _player_moves(state, gid)["success"]
    due = [e for e in state.social["queue"] if e["kind"] == "game_move" and e.get("game_id") == gid]
    assert len(due) == 1 and due[0]["pid"] == pid and due[0]["at"] > state.world_clock_hours - 3 / 60
    assert _row(state, gid)["moves"][-1]["by"] == "player"
    clock.advance_time(state, due[0]["at"] - state.world_clock_hours + 1 / 60)
    row = _row(state, gid)
    assert row["moves"][-1]["by"] == "them" and row["turn"] == "player"
    assert not [e for e in state.social["queue"] if e["kind"] == "game_move"]
    tid = messaging.thread_for(state, pid)
    banter = [m for m in state.social["threads"][tid]["messages"]
              if (m.get("decision") or {}).get("situation") == "game_banter"]
    assert len(banter) == 1 and banter[0]["voiced"] is False and banter[0]["decision"]["game_id"] == gid
    assert any(n["kind"] == "game_move" and n["pid"] == pid for n in state.social["notifications"])


def test_no_banter_when_the_draw_says_no(receipts_state, matched, monkeypatch) -> None:
    from engine.game import clock
    from engine.social import games

    state = receipts_state
    pid = _talking(state, matched)
    gid = _act(state, "game_invite", target=pid, args={"game": "wordgame"})["result"]["game_id"]
    monkeypatch.setattr(games, "_banters", lambda *a, **k: False)
    assert _player_moves(state, gid)["success"]
    due = [e for e in state.social["queue"] if e["kind"] == "game_move"][0]
    clock.advance_time(state, due["at"] - state.world_clock_hours + 1 / 60)
    assert _row(state, gid)["moves"][-1]["by"] == "them"
    assert not [m for t in state.social["threads"].values() for m in t["messages"]
                if (m.get("decision") or {}).get("situation") == "game_banter"]


def test_their_move_replays_from_the_seed(receipts_active, monkeypatch) -> None:
    """Two runs of one seed and the same moves: the same move of theirs, at the same in-game time."""
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
        _force_stage(state, pid, "talking")
        gid = _act(state, "game_invite", target=pid, args={"game": "wordgame"})["result"]["game_id"]
        assert _player_moves(state, gid)["success"]
        due = [e for e in state.social["queue"] if e["kind"] == "game_move"][0]
        clock.advance_time(state, due["at"] - state.world_clock_hours + 1 / 60)
        row = _row(state, gid)
        assert row["moves"][-1]["by"] == "them"
        results.append((due["at"], row["board"], row["scores"], row["moves"][-1], row["racks"]))
    assert results[0] == results[1]


def test_a_finished_game_adds_familiarity_and_interest(receipts_state, matched) -> None:
    state = receipts_state
    pid = _talking(state, matched)
    gid = _act(state, "game_invite", target=pid, args={"game": "wordgame"})["result"]["game_id"]
    person = state.social["people"][pid]
    exchanges, interest = int(person["familiarity"]["exchanges"]), int(person["interest"])
    _end_with_a_pass(state, gid, player=40, them=30)
    finished = _spec()["effects"]["finished"]
    row = _row(state, gid)
    assert row["status"] == "finished" and row["winner"] == "player"
    assert "bag" not in row and "racks" not in row                         # bounded: compacted
    assert person["familiarity"]["exchanges"] == exchanges + finished["familiarity"]
    assert person["interest"] == min(100, interest + finished["interest"])


def _end_with_a_pass(state, gid: str, *, player: int, them: int) -> dict[str, Any]:
    """Arrange a row one scoreless turn from its end with empty racks and these scores; the player passes."""
    row = _row(state, gid)
    row["scores"] = {"player": player, "them": them}
    row["racks"] = {"player": "", "them": ""}
    row["bag"] = ""
    row["scoreless"] = int(_spec()["scoreless_turns"]) - 1
    return _act(state, "game_move", target=gid, args={"move": "pass"})


@pytest.mark.parametrize("archetype, margin, costs", [
    ("needy", 200, True), ("needy", 50, False), ("romantic", 200, False),
])
def test_a_crushing_win_over_needy_costs_a_little_warmth(receipts_state, matched, monkeypatch,
                                                         archetype, margin, costs) -> None:
    state = receipts_state
    pid = _talking(state, matched)
    _force_archetype(monkeypatch, state, pid, archetype)
    gid = _act(state, "game_invite", target=pid, args={"game": "wordgame"})["result"]["game_id"]
    warmth = int(state.social["people"][pid]["warmth"])
    effects = _spec()["effects"]
    assert (margin > effects["crushing_margin"]) == (margin == 200)        # 200 crushes, 50 does not
    receipt = _end_with_a_pass(state, gid, player=10 + margin, them=10)
    assert receipt["success"], receipt
    regards = [e for e in receipt["result"]["effects"]
               if e.get("type") == "social_regard" and (e.get("applied") or {}).get("warmth")]
    expected = int(effects["needy_crushing_warmth"]) if costs else 0
    assert state.social["people"][pid]["warmth"] == warmth + expected
    assert [e["applied"]["warmth"] for e in regards] == ([expected] if costs else [])


# -- their invite (spec §10.5 `invite_game`) ------------------------------------------------------------------


def test_their_invite_is_a_request_the_player_answers(receipts_state, matched) -> None:
    from engine.social import relationships

    state = receipts_state
    pid = matched("matchstick").split(":", 1)[1]
    assert "invite_game" not in relationships.legal_proposals(state, pid)       # matched: games not open yet
    _force_stage(state, pid, "talking")
    assert "invite_game" in relationships.legal_proposals(state, pid)
    rid = relationships.apply_proposal(state, pid, "invite_game")["request_id"]
    request = state.social["requests"][rid]
    assert request["what"] == "game" and request["game"] == "wordgame" and request["from"] == "them"
    assert "invite_game" not in relationships.legal_proposals(state, pid)       # asked: not twice
    refused = _act(state, "game_invite", target=pid, args={"game": "wordgame"})
    assert refused["refused"] and "already asked you" in refused["result"]["error"]
    answered = _act(state, "answer", target=rid, args={"reply": "yes"})
    assert answered["success"], answered
    gid = answered["result"]["game_id"]
    assert state.social["games"][gid]["status"] == "active" and state.social["games"][gid]["turn"] == "player"
    assert state.social["people"][pid]["stage"] == "talking"                   # a game moves no stage
    assert "invite_game" not in relationships.legal_proposals(state, pid)       # one running


def test_a_game_whose_person_left_is_abandoned_in_the_morning(receipts_state, matched) -> None:
    from engine.game import clock

    state = receipts_state
    pid = _talking(state, matched)
    gid = _act(state, "game_invite", target=pid, args={"game": "wordgame"})["result"]["game_id"]
    assert _act(state, "unmatch", target=pid)["success"]
    assert _act(state, "game_move", target=gid, args={"move": "pass"})["refused"] is True
    clock.advance_time(state, 24.0)
    row = _row(state, gid)
    assert row["status"] == "abandoned" and "bag" not in row


def test_finished_games_are_bounded(receipts_state, matched, monkeypatch) -> None:
    from engine import social

    state = receipts_state
    pid = _talking(state, matched)
    real = social.setting
    monkeypatch.setattr(social, "setting", lambda key, default: 2 if key == "games_kept" else real(key, default))
    ids = []
    for _ in range(4):
        gid = _act(state, "game_invite", target=pid, args={"game": "wordgame"})["result"]["game_id"]
        _end_with_a_pass(state, gid, player=5, them=5)
        ids.append(gid)
    assert sorted(state.social["games"]) == sorted(ids[-2:])


# -- the payload and the data -------------------------------------------------------------------------------


def test_the_games_section_shows_the_players_rack_never_theirs(receipts_state, matched) -> None:
    from engine.social import payload

    state = receipts_state
    pid = _talking(state, matched)
    gid = _act(state, "game_invite", target=pid, args={"game": "wordgame"})["result"]["game_id"]
    row = _row(state, gid)
    block = payload.phone_block(state)
    assert "games" in payload.TIME_VARYING_SECTIONS
    (shown,) = block["games"]
    assert shown["rack"] == row["racks"]["player"] and shown["bag_left"] == len(row["bag"])
    assert shown["label"] == "Tile Talk" and len(shown["premiums"]) == 11
    assert not ({"racks", "bag"} & set(shown))


def test_the_data_checks_name_the_fault(receipts_active, tmp_path) -> None:
    import copy

    from engine.social.games import wordgame

    good = copy.deepcopy(_spec())
    assert wordgame.data_faults(good, None) == []
    bad = copy.deepcopy(good)
    bad["premiums"] = bad["premiums"][:10]
    assert ("wordgame.premiums", "must be 11 rows of 11 squares (spec §21.1)") in wordgame.data_faults(bad, None)
    bad = copy.deepcopy(good)
    bad["letters"]["e"]["count"] += 1
    assert ("wordgame.letters", "the bag (letters plus blanks) must hold 72 tiles, not 73") in \
        wordgame.data_faults(bad, None)
    assert (wordgame.WORDS_FILE, f"missing: games.yaml offers {wordgame.GAME}, which needs its word list") in \
        wordgame.data_faults(good, tmp_path)
    with pytest.raises(ValueError, match="games.yaml: wordgame.premiums"):
        wordgame.check_data({**good, "premiums": []}, None)


def test_the_banter_is_voiced_with_the_engines_line_about_the_game(receipts_state, matched, monkeypatch) -> None:
    """The `game_banter` due message's RIGHT NOW block carries what happened in the game (engine words):
    texter.md's row says "what happened in it is given below"."""
    from engine.game import clock
    from engine.social import games, messaging, voicing

    state = receipts_state
    pid = _talking(state, matched)
    gid = _act(state, "game_invite", target=pid, args={"game": "wordgame"})["result"]["game_id"]
    monkeypatch.setattr(games, "_banters", lambda *a, **k: True)
    assert _player_moves(state, gid)["success"]
    due = [e for e in state.social["queue"] if e["kind"] == "game_move"][0]
    clock.advance_time(state, due["at"] - state.world_clock_hours + 1 / 60)
    snap = voicing.snapshot_of(state, messaging.thread_for(state, pid))
    assert snap is not None and snap.games.get(gid, "").startswith("Tile Talk: You just ")
    user = voicing.messages(snap)[-1]["content"]
    assert f"The game: {snap.games[gid]}" in user
    scores = state.social["games"][gid]["scores"]
    assert f"you {scores['them']}, them {scores['player']}" in snap.games[gid]


# -- the review's fixes (T22 fix round 1) ------------------------------------------------------------------


def test_a_ghosted_opponents_game_moves_again_when_they_come_back(receipts_state, matched_numbers,
                                                                  monkeypatch) -> None:
    """I1: their `game_move` falls due while they are ghosted (the game sits, the event spent); when they
    come back -- a `ghosted: true` initiation landing -- the game is re-armed and their move lands."""
    from engine.game import clock
    from engine.social import events, messaging
    from tests.social_fixtures import _set_person

    state = receipts_state
    pid = matched_numbers("natter").split(":", 1)[1]        # a Natter thread: no match expiry in 15 days
    _force_archetype(monkeypatch, state, pid, "ghoster")
    gid = _act(state, "game_invite", target=pid, args={"game": "wordgame"})["result"]["game_id"]
    assert _act(state, "game_move", target=gid, args={"move": "pass"})["success"]
    _set_person(state, pid, ghosted=True)
    due = [e for e in state.social["queue"] if e["kind"] == "game_move"][0]
    clock.advance_time(state, due["at"] - state.world_clock_hours + 1 / 60)
    assert _row(state, gid)["turn"] == "them" and _row(state, gid)["moves"][-1]["by"] == "player"
    assert not [e for e in state.social["queue"] if e["kind"] == "game_move"]           # the event is spent
    # They come back: their archetype's `hey_stranger` (when: ghosted, 14 days quiet) lands.
    tid = messaging.thread_for(state, pid)
    events.push(state, state.world_clock_hours + 15 * 24.0, pid, "initiate", thread_id=tid,
                decision={"situation": "reconnect", "kind": "text"}, initiation="hey_stranger")
    back = [e for e in state.social["queue"] if e.get("initiation") == "hey_stranger"][0]["at"]
    clock.advance_time(state, back - state.world_clock_hours + 1 / 60)
    assert state.social["people"][pid].get("ghosted") is False                           # they came back
    queued = [e for e in state.social["queue"] if e["kind"] == "game_move" and e.get("game_id") == gid]
    assert len(queued) == 1                                                              # re-armed
    clock.advance_time(state, queued[0]["at"] - state.world_clock_hours + 1 / 60)
    row = _row(state, gid)
    assert row["moves"][-1]["by"] == "them" and row["turn"] == "player"


def test_resign_on_their_turn_frees_the_pair(receipts_state, matched) -> None:
    state = receipts_state
    pid = _talking(state, matched)
    gid = _act(state, "game_invite", target=pid, args={"game": "wordgame"})["result"]["game_id"]
    assert _act(state, "game_move", target=gid, args={"move": "pass"})["success"]
    assert _row(state, gid)["turn"] == "them"
    person = state.social["people"][pid]
    interest = int(person["interest"])
    receipt = _act(state, "game_move", target=gid, args={"move": "resign"})
    assert receipt["success"], receipt
    row = _row(state, gid)
    assert row["status"] == "resigned" and row["winner"] == "them" and row["moves"][-1]["kind"] == "resign"
    assert "bag" not in row and "racks" not in row
    assert not [e for e in state.social["queue"] if e["kind"] == "game_move"]           # their move withdrawn
    assert int(person["interest"]) == interest                                          # no finished-game effects
    again = _act(state, "game_invite", target=pid, args={"game": "wordgame"})
    assert again["success"] and again["result"]["game_id"] != gid                       # the pair is free


def test_declining_their_game_invite_costs_no_warmth(receipts_state, matched) -> None:
    """M3: a "no" to their game costs nothing (a "no" to their number costs asks.turned_down)."""
    from engine.social import relationships

    state = receipts_state
    pid = _talking(state, matched)
    rid = relationships.apply_proposal(state, pid, "invite_game")["request_id"]
    person = state.social["people"][pid]
    warmth, mood = int(person["warmth"]), person.get("mood")
    receipt = _act(state, "answer", target=rid, args={"reply": "no"})
    assert receipt["success"], receipt
    assert state.social["requests"][rid]["status"] == "no"
    assert int(person["warmth"]) == warmth and person.get("mood") == mood
    assert not state.social["games"]


def test_the_swap_minimum_is_data(receipts_active, monkeypatch) -> None:
    """M2: a swap needs the bag to hold as many tiles as are swapped and games.yaml `swap_bag_min`."""
    from engine.social.games import wordgame

    assert _spec()["swap_bag_min"] == 0                                    # the shipped rule: only the count
    row = {**_empty_game("abcdefg"), "bag": "xyz", "moves": []}
    assert wordgame.can_swap(row, 3) and not wordgame.can_swap(row, 4)
    assert wordgame.apply_move(None, dict(row, racks={"player": "abcdefg", "them": ""}), "player",
                               {"move": "swap", "letters": "abc"})["ok"]
    strict = dict(_spec(), swap_bag_min=7)
    monkeypatch.setattr(wordgame, "spec", lambda: strict)
    assert not wordgame.can_swap(row, 1)
    refused = wordgame.apply_move(None, dict(row, racks={"player": "abcdefg", "them": ""}), "player",
                                  {"move": "swap", "letters": "a"})
    assert refused == {"ok": False, "error": "There aren't enough tiles left to swap."}
