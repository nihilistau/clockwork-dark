"""
Agendas, part three: reactions, and the predicates they are written in.

THE RULE. At every hour boundary the pass walks, AFTER that hour's moves and
before that hour's clock beats fire, each agenda (sorted) evaluates each of
its reactions (declared order) on a scratch whose clock reads that hour:

* it fires on a false -> true EDGE. The first evaluation of a condition that
  is already true counts as one: a missing ``truth`` reads as false;
* ``once: true`` fires at most once ever (``fired``); otherwise it fires
  again after falling and rising;
* firing applies its effects (``{owner}`` substituted) and its clock
  ``advance``; a beat that advance crosses fires at the end of the hour,
  with the moves' beats;
* ``truth`` is written, through ``agenda_mark``, only when it changes -- a
  reaction that never held leaves nothing in the save.

WHAT THESE TESTS HOLD:

* the edge semantics, ``once`` and the small state;
* a reaction answers a move in the SAME hour (``wanted``, ``agenda_hit``);
* ``reported_to npc_ardane`` fires in the very hour the word reaches him
  through the Law's talk, and not for a deed that was quashed or discharged
  -- including one filed in a different watch-house from where it was done;
* ``premise_robbed {owner}`` after a job on an owned anchor;
* no predicate reads a Law row's ``day`` (stamped at the END of a call, so
  not cut-invariant across midnight);
* twelve 1h calls equal one 12h call with reactions: one that sets a flag a
  later move reads, one that winds a clock across a ``reset_to`` beat, and
  the Law-driven one;
* a seed replays with reactions.

Version: v0.1.0 [2026-09-25]
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from engine.game import clocks
from engine.game.clock import advance_time
from engine.game.effects import apply_effect
from engine.game.state import GameState
from engine.world import agendas, law

from test_agendas import CANDIDATES, _paths
from test_agendas_moves import (
    CLOCKS_TABLE, LIFT, MARKET, SQUARE, STATE_YAML, TARGETS, _fails, _run, _world, story,
)
from test_jobs import _rob
from test_premises import MILL_HOUSE

ARDANE = "npc_ardane"


def _doc(moves: list[dict[str, Any]] | None = None,
         reactions: list[dict[str, Any]] | None = None,
         *, clock: str = "magpie_spree", extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """One agenda, `the_magpie`, owned by the seed's magpie, with these rows."""
    doc: dict[str, Any] = {
        "roles": {"magpie": {"from": list(CANDIDATES)}},
        "agendas": {"the_magpie": {"owner": {"role": "magpie"}, "goal": "shine",
                                   "clock": clock, "moves": moves or [],
                                   "reactions": reactions or []}},
    }
    if extra:
        doc["agendas"].update(extra)
    return doc


def _reacted(receipts: list[dict[str, Any]], key: str) -> list[int]:
    return [r["hour"] for r in receipts
            if r.get("reaction") and f"{r['agenda']}:{r['reaction']}" == key]


def _moved(receipts: list[dict[str, Any]], key: str) -> list[int]:
    return [r["hour"] for r in receipts
            if r.get("move") and f"{r['agenda']}:{r['move']}" == key]


def _flag(state: GameState, name: str, value: bool = True) -> None:
    assert apply_effect(state, {"type": "flag", "flag": name, "value": value})["ok"]


ALARM = {"id": "alarm", "on": {"flag": "alarm"}, "advance": 1}
ALARM_ONCE = {**ALARM, "id": "alarm_once", "once": True}


# ---------------------------------------------------------------------------
# Edge semantics
# ---------------------------------------------------------------------------


def test_a_reaction_fires_on_the_rising_edge_and_again_after_a_fall(tmp_path: Path) -> None:
    with story(tmp_path, _doc(reactions=[ALARM])):
        state = _world()
        assert _reacted(_run(state, 3), "the_magpie:alarm") == []
        # Never held: nothing written. The state stays small.
        assert "truth" not in state.agendas
        _flag(state, "alarm")
        assert _reacted(_run(state, 1), "the_magpie:alarm") == [12]
        assert state.agendas["truth"] == {"the_magpie:alarm": True}
        assert clocks.value_of(state, "magpie_spree") == 1
        # Still true: no edge, no second firing.
        assert _reacted(_run(state, 5), "the_magpie:alarm") == []
        _flag(state, "alarm", False)
        assert _reacted(_run(state, 1), "the_magpie:alarm") == []
        assert state.agendas["truth"] == {"the_magpie:alarm": False}
        _flag(state, "alarm")
        assert _reacted(_run(state, 2), "the_magpie:alarm") == [19]
        assert clocks.value_of(state, "magpie_spree") == 2
        # Not a once-reaction: nothing is spent.
        assert "fired" not in state.agendas


def test_a_once_reaction_fires_at_most_once_ever(tmp_path: Path) -> None:
    with story(tmp_path, _doc(reactions=[ALARM_ONCE])):
        state = _world()
        _flag(state, "alarm")
        assert _reacted(_run(state, 1), "the_magpie:alarm_once") == [9]
        assert state.agendas["fired"] == ["the_magpie:alarm_once"]
        _flag(state, "alarm", False)
        _run(state, 1)
        _flag(state, "alarm")
        assert _reacted(_run(state, 24), "the_magpie:alarm_once") == []
        assert clocks.value_of(state, "magpie_spree") == 1


def test_a_condition_already_true_at_its_first_evaluation_is_an_edge(
    tmp_path: Path,
) -> None:
    with story(tmp_path, _doc(reactions=[ALARM])):
        state = _world()
        _flag(state, "alarm")
        assert _reacted(_run(state, 2), "the_magpie:alarm") == [9]


def test_truth_is_written_only_when_it_changes(tmp_path: Path,
                                               monkeypatch: pytest.MonkeyPatch) -> None:
    import engine.game.effects as effects_module

    writes: list[dict[str, Any]] = []
    real = effects_module.apply_effect

    def spy(st: GameState, effect: dict[str, Any], *a: Any, **k: Any) -> Any:
        if effect.get("type") == "agenda_mark" and "truth" in effect:
            writes.append(copy.deepcopy(effect["truth"]))
        return real(st, effect, *a, **k)

    with story(tmp_path, _doc(reactions=[ALARM])):
        state = _world()
        monkeypatch.setattr(effects_module, "apply_effect", spy)
        _run(state, 4)
        _flag(state, "alarm")
        _run(state, 4)
        _flag(state, "alarm", False)
        _run(state, 4)
    assert writes == [{"the_magpie:alarm": True}, {"the_magpie:alarm": False}]


def test_reactions_go_in_sorted_agenda_then_declared_order(tmp_path: Path) -> None:
    first = {"id": "b_first", "on": {"flag": "alarm"},
             "effects": [{"type": "flag", "flag": "order_b_first"}]}
    second = {"id": "a_second", "on": {"flag": "order_b_first"},
              "effects": [{"type": "flag", "flag": "order_a_second"}]}
    other = {"the_aardvark": {"owner": ARDANE, "goal": "g", "clock": "magpie_spree",
                              "reactions": [{"id": "early", "on": {"flag": "order_a_second"},
                                             "effects": [{"type": "flag", "flag": "late"}]}]}}
    with story(tmp_path, _doc(reactions=[first, second], extra=other)):
        state = _world()
        _flag(state, "alarm")
        receipts = _run(state, 1)
        # Declared order inside an agenda: `a_second` sees `b_first`'s flag at once.
        assert _reacted(receipts, "the_magpie:b_first") == [9]
        assert _reacted(receipts, "the_magpie:a_second") == [9]
        # `the_aardvark` sorts first, so it read before the flag was set: next hour.
        assert _reacted(receipts, "the_aardvark:early") == []
        assert _reacted(_run(state, 1), "the_aardvark:early") == [10]


def test_a_reaction_effect_names_its_owner(tmp_path: Path) -> None:
    react = {"id": "sign", "on": {"flag": "alarm"},
             "effects": [{"type": "flag", "flag": "by_{owner}"}]}
    with story(tmp_path, _doc(reactions=[react])):
        state = _world()
        _flag(state, "alarm")
        _run(state, 1)
        assert state.flags.get(f"by_{agendas.owner_of(state, 'the_magpie')}") is True


@pytest.mark.parametrize("gate", [
    {"disposition": {"npc": ARDANE, "min": 1}},
    {"any": [{"flag": "x"}, {"disposition": {"npc": ARDANE, "min": 1}}]},
])
def test_disposition_in_on_is_a_load_error(tmp_path: Path, gate: dict) -> None:
    message = _fails(tmp_path, _doc(reactions=[{"id": "r", "on": gate}]))
    assert "ledger" in message.replace(str(tmp_path), "")


# ---------------------------------------------------------------------------
# A reaction answers a move in the same hour
# ---------------------------------------------------------------------------


def test_wanted_answers_the_move_that_raised_it_in_the_same_hour(tmp_path: Path) -> None:
    hunted = {"id": "hue", "on": {"wanted": {"min": "noticed", "jurisdiction": "town"}},
              "once": True, "effects": [{"type": "flag", "flag": "hue_raised"}]}
    with story(tmp_path, _doc([LIFT], [hunted]), with_jobs=True):
        state = _world(hour=20)
        _rob(state, TARGETS[0])
        _rob(state, TARGETS[2])
        receipts = _run(state, 6)
        # The lift reports the Magpie in town at 01:00; its linked `self` band
        # reaches `noticed` there, and the reaction hears it that same hour.
        assert _moved(receipts, "the_magpie:lift") == [25]
        assert _reacted(receipts, "the_magpie:hue") == [25]
        assert state.flags.get("hue_raised") is True


def test_wanted_is_read_where_the_player_stands_by_default(tmp_path: Path) -> None:
    hunted = {"id": "hue", "on": {"wanted": {"min": "noticed"}}}
    with story(tmp_path, _doc(reactions=[hunted])):
        state = _world()  # in the village square
        # Severity 5: an hour's cooling does not drop it below `noticed`.
        assert apply_effect(state, {"type": "report", "deed": "assault_watch", "guise": "self",
                                    "jurisdiction": "town", "precision": 1.0})["ok"]
        assert _reacted(_run(state, 2), "the_magpie:hue") == []
        state.location_id = MARKET  # the town's streets
        assert _reacted(_run(state, 1), "the_magpie:hue") == [11]


def test_agenda_hit_answers_the_robbery_in_the_same_hour(tmp_path: Path) -> None:
    gloat = {"id": "gloat", "on": {"agenda_hit": {"agenda": "the_magpie",
                                                  "district": MARKET}},
             "once": True, "advance": 1}
    with story(tmp_path, _doc([LIFT], [gloat]), with_jobs=True):
        state = _world(hour=20)
        _rob(state, TARGETS[0])
        _rob(state, TARGETS[2])
        receipts = _run(state, 6)
        assert _moved(receipts, "the_magpie:lift") == [25]
        assert _reacted(receipts, "the_magpie:gloat") == [25]
        # The lift's advance and the reaction's both wound the clock.
        assert clocks.value_of(state, "magpie_spree") == 2


def test_premise_robbed_by_owner_after_a_job_on_an_owned_anchor(tmp_path: Path) -> None:
    mill = {**MILL_HOUSE, "owner": "npc_imelda"}
    hers = {"id": "hers", "on": {"premise_robbed": {"owner": "npc_imelda"}}, "once": True,
            "effects": [{"type": "flag", "flag": "imelda_robbed"}]}
    his = {"id": "his", "on": {"premise_robbed": {"owner": "npc_silas"}}, "once": True}
    with story(tmp_path, _doc(reactions=[hers, his]), with_jobs=True,
               **{"anchors/mill_house.yaml": mill}):
        state = _world()
        assert _reacted(_run(state, 2), "the_magpie:hers") == []
        _rob(state, "prem_mill_house")
        receipts = _run(state, 1)
        assert _reacted(receipts, "the_magpie:hers") == [11]
        assert _reacted(receipts, "the_magpie:his") == []
        assert state.flags.get("imelda_robbed") is True


# ---------------------------------------------------------------------------
# reported_to: the captain hears
# ---------------------------------------------------------------------------

#: A sighting of the Magpie at 10:00 held by Wren, who shares the square with
#: the captain: the Law's talk carries it to him some hours later.
WHISPER = {"id": "whisper", "every_hours": 1000, "start_hour": 10,
           "effects": [{"type": "witness", "deed": "fencing", "guise": "magpie",
                        "npc": "npc_wren", "where": SQUARE}]}
HEARS = {"id": "the_captain_hears", "on": {"reported_to": {"npc": ARDANE, "guise": "magpie"}},
         "once": True, "effects": [{"type": "flag", "flag": "captain_heard"}], "advance": 1}


def _holds_word(state: GameState) -> bool:
    return any(r.get("npc") == ARDANE for r in state.law.get("witnessed") or [])


@pytest.mark.parametrize("seed", [42, 7, 11])
def test_the_captain_hears_in_the_hour_the_word_reaches_him(tmp_path: Path,
                                                           seed: int) -> None:
    with story(tmp_path, _doc([WHISPER], [HEARS])):
        stepped, whole = _world(seed), _world(seed)
        heard_at = None
        stepped_receipts: list[dict[str, Any]] = []
        for _ in range(16):
            receipts = _run(stepped, 1)
            stepped_receipts += receipts
            hour = int(stepped.world_clock_hours)
            # At the end of every hour: the reaction has fired iff he holds the word.
            assert _holds_word(stepped) == ("the_magpie:the_captain_hears"
                                            in stepped.agendas.get("fired", []))
            if heard_at is None and _holds_word(stepped):
                heard_at = hour
        assert heard_at is not None and heard_at > 10, "the word must reach him by talk"
        assert _reacted(stepped_receipts, "the_magpie:the_captain_hears") == [heard_at]
        assert stepped.flags.get("captain_heard") is True
        # And the same hour when the day passes as one call.
        whole_receipts = _run(whole, 16)
        assert _reacted(whole_receipts, "the_magpie:the_captain_hears") == [heard_at]
        assert whole.agendas == stepped.agendas
        # Midnight is crossed at the last boundary: a Law row's `day` is the
        # day its CALL ends on (Task 2's recorded caveat, read by nothing --
        # see test_no_agenda_predicate_reads_a_law_rows_day). All else agrees.
        assert _dayless(whole.law) == _dayless(stepped.law)


def _dayless(law_state: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(law_state)
    for table in ("witnessed", "reports"):
        for row in out.get(table) or []:
            row.pop("day", None)
    return out


def _file_on_the_captain(state: GameState, *, done_at: str = SQUARE,
                         filed_in: tuple[str, ...] = ("village",)) -> str:
    """The captain holds a live sighting of the Magpie, filed where given."""
    row = apply_effect(state, {"type": "witness", "deed": "fencing", "guise": "magpie",
                               "npc": ARDANE, "where": done_at})
    assert row["ok"], row
    for jurisdiction in filed_in:
        assert apply_effect(state, {"type": "report", "deed": "fencing", "guise": "magpie",
                                    "jurisdiction": jurisdiction,
                                    "deed_id": row["deed_id"]})["ok"]
    return str(row["deed_id"])


def test_a_quashed_deed_does_not_reach_the_captain(tmp_path: Path) -> None:
    with story(tmp_path, _doc(reactions=[HEARS])):
        state = _world()
        _file_on_the_captain(state)
        assert apply_effect(state, {"type": "quash_reports", "jurisdiction": "village"})["ok"]
        assert _reacted(_run(state, 6), "the_magpie:the_captain_hears") == []
        assert "captain_heard" not in state.flags


def test_a_discharged_deed_does_not_reach_the_captain(tmp_path: Path) -> None:
    with story(tmp_path, _doc(reactions=[HEARS])):
        state = _world()
        deed = _file_on_the_captain(state)
        assert apply_effect(state, {"type": "law_discharge", "deed_ids": [deed]})["ok"]
        assert _reacted(_run(state, 6), "the_magpie:the_captain_hears") == []


def test_a_file_lost_in_the_captains_house_silences_him_wherever_the_deed_was_done(
    tmp_path: Path,
) -> None:
    """
    The Law files a report where the WATCHMAN heard it, not where the deed was
    done (``law._propagate_hour``). A Magpie lift up in town, told to the
    captain in the village, is filed in the village; the sergeant paid to lose
    the village's file has lost the only file there is. Reading "quashed" only
    where the deed was done would leave the captain acting on it anyway.
    """
    with story(tmp_path, _doc(reactions=[HEARS])):
        state = _world()
        _file_on_the_captain(state, done_at=MARKET, filed_in=("village",))
        assert apply_effect(state, {"type": "quash_reports", "jurisdiction": "village"})["ok"]
        assert _reacted(_run(state, 6), "the_magpie:the_captain_hears") == []


def test_a_file_still_standing_elsewhere_keeps_the_word_live(tmp_path: Path) -> None:
    """Filed in both houses and lost in one: the other still holds it."""
    with story(tmp_path, _doc(reactions=[HEARS])):
        state = _world()
        _file_on_the_captain(state, done_at=MARKET, filed_in=("village", "town"))
        assert apply_effect(state, {"type": "quash_reports", "jurisdiction": "town"})["ok"]
        assert _reacted(_run(state, 1), "the_magpie:the_captain_hears") == [9]


def test_word_never_filed_is_still_word(tmp_path: Path) -> None:
    """A sighting no watch-house holds a file on has nothing to quash: it is live."""
    with story(tmp_path, _doc(reactions=[HEARS])):
        state = _world()
        _file_on_the_captain(state, filed_in=())
        assert _reacted(_run(state, 1), "the_magpie:the_captain_hears") == [9]


# ---------------------------------------------------------------------------
# The `day` stamp is read by no predicate
# ---------------------------------------------------------------------------


def test_no_agenda_predicate_reads_a_law_rows_day(tmp_path: Path) -> None:
    """
    A Law row's ``day`` is stamped with the day the CALL ends on, so it is not
    cut-invariant across midnight (Task 2's recorded concern). Every predicate
    an agenda may gate on reads the same with every ``day`` rewritten.
    """
    gates = [
        {"wanted": {"min": "noticed", "jurisdiction": "village"}},
        {"wanted": {"guise": "magpie", "min": "noticed", "jurisdiction": "village"}},
        {"reported_to": {"npc": ARDANE, "guise": "magpie"}},
        {"reported_to": {"npc": "npc_wren"}},
    ]
    from engine.game.quests import evaluate_condition

    with story(tmp_path, _doc(reactions=[HEARS])):
        state = _world()
        _file_on_the_captain(state)
        _witness_wren = apply_effect(state, {"type": "witness", "deed": "fencing",
                                             "guise": "self", "npc": "npc_wren",
                                             "where": SQUARE})
        assert _witness_wren["ok"]
        before = [evaluate_condition(state, g) for g in gates]
        assert all(before)
        for table in ("witnessed", "reports"):
            for row in state.law.get(table) or []:
                row["day"] = 999
        assert [evaluate_condition(state, g) for g in gates] == before


# ---------------------------------------------------------------------------
# Cut-invariance and replay
# ---------------------------------------------------------------------------


def test_a_reaction_that_sets_a_flag_a_later_move_reads_is_cut_invariant(
    tmp_path: Path,
) -> None:
    answer = {"id": "answer", "every_hours": 1, "when": {"flag": "answered"},
              "advance": 1, "trace": {"text": "a bell answers", "where": SQUARE}}
    react = {"id": "ring", "on": {"flag": "alarm"}, "once": True,
             "effects": [{"type": "flag", "flag": "answered"}]}
    with story(tmp_path, _doc([answer], [react])):
        stepped, whole = _world(), _world()
        for state in (stepped, whole):
            _flag(state, "alarm")
        for _ in range(12):
            advance_time(stepped, 1)
        advance_time(whole, 12)
        # The reaction fires at 9 after the moves; the move first reads it at 10.
        assert stepped.agendas["moves"]["the_magpie:answer"] == 20
        assert [t["hour"] for t in stepped.agendas["traces"]][0] == 10
        assert whole.agendas == stepped.agendas
        assert whole.flags == stepped.flags
        assert clocks.value_of(whole, "magpie_spree") == clocks.value_of(stepped, "magpie_spree")


def test_a_reaction_winding_a_clock_across_a_reset_beat_is_cut_invariant(
    tmp_path: Path,
) -> None:
    """
    A reaction that re-fires every other hour winds `tick_tock` by 2; the beat
    at 3 resets it at the END of the hour it is crossed, so the count is the
    same however the hours are cut.
    """
    table = copy.deepcopy(CLOCKS_TABLE)
    table["clocks"]["tick_tock"] = {
        "label": "A clock that strikes and starts again",
        "beats": [{"id": "tock", "at": 3, "reset_to": 0, "set_flags": ["tocked"]}],
    }
    schema = copy.deepcopy(STATE_YAML)
    schema["clocks"]["tick_tock"] = {"min": 0, "max": 99, "visibility": "hidden"}
    # `blink` toggles the flag every hour; `wind` rises on every other one.
    blink_on = {"id": "blink_on", "every_hours": 2, "effects": [{"type": "flag",
                                                                 "flag": "lit"}]}
    blink_off = {"id": "blink_off", "every_hours": 2, "start_hour": 10,
                 "effects": [{"type": "flag", "flag": "lit", "value": False}]}
    wind = {"id": "wind", "on": {"flag": "lit"}, "advance": 2}
    doc = _doc([blink_on, blink_off], [wind], clock="tick_tock")
    with story(tmp_path, doc, clocks_table=table, state_yaml=schema):
        stepped, whole = _world(), _world()
        for _ in range(12):
            advance_time(stepped, 1)
        advance_time(whole, 12)
        # Wound to 2 at 9, to 4 at 11 and struck back to 0 that hour, then
        # 2, 4, 6, 8 at 13..19.
        assert stepped.flags.get("tocked") is True
        assert clocks.value_of(stepped, "tick_tock") == 8
        assert clocks.value_of(whole, "tick_tock") == clocks.value_of(stepped, "tick_tock")
        assert whole.agendas == stepped.agendas
        assert whole.flags == stepped.flags


def test_twelve_hours_with_reactions_across_midnight_equal_one_call(tmp_path: Path) -> None:
    hunted = {"id": "hue", "on": {"wanted": {"min": "noticed", "jurisdiction": "town"}},
              "effects": [{"type": "flag", "flag": "hue_raised"}], "advance": 1}
    gloat = {"id": "gloat", "on": {"agenda_hit": {}}, "once": True, "advance": 1}
    with story(tmp_path, _doc([LIFT], [hunted, gloat, HEARS]), with_jobs=True):
        stepped, whole = _world(hour=20), _world(hour=20)
        for state in (stepped, whole):
            _rob(state, TARGETS[0])
            _rob(state, TARGETS[2])
        for _ in range(12):
            advance_time(stepped, 1)
        advance_time(whole, 12)
        assert stepped.agendas["truth"]["the_magpie:hue"] is True
        assert stepped.agendas == whole.agendas
        assert stepped.law == whole.law
        assert stepped.flags == whole.flags
        assert stepped.rng_counters == whole.rng_counters


def test_a_seed_replays_with_reactions(tmp_path: Path) -> None:
    def play(seed: int) -> str:
        state = _world(seed)
        receipts = _run(state, 12) + _run(state, 30)
        return json.dumps([receipts, dict(state.rng_counters), state.agendas,
                           state.law, dict(state.flags)], sort_keys=True, default=str)

    with story(tmp_path, _doc([WHISPER], [HEARS, ALARM])):
        first, second = play(11), play(11)
        assert "the_captain_hears" in first
        assert first == second


def test_a_spent_once_reaction_is_not_evaluated_again(tmp_path: Path,
                                                      monkeypatch: pytest.MonkeyPatch) -> None:
    with story(tmp_path, _doc(reactions=[ALARM_ONCE])):
        state = _world()
        _flag(state, "alarm")
        _run(state, 1)
        seen: list[Any] = []
        from engine.game import quests

        real = quests.evaluate_condition

        def spy(st: GameState, condition: Any, **k: Any) -> bool:
            seen.append(condition)
            return real(st, condition, **k)

        monkeypatch.setattr(quests, "evaluate_condition", spy)
        _run(state, 3)
        assert {"flag": "alarm"} not in seen
