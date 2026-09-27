"""
The law's memory (v0.16.0, T2): the seams HUE & CRY's spine stands on.

THE GAP. Four things the watch did not remember, and so no content could ask:

- WHEN the player was held. ``arrest`` stamped a day and ``release`` popped
  the record, so "you were in the cells when the Magpie struck" had no hours
  to be checked against.
- WHICH robbery a report was. An agenda's report row carried no hour and no
  agenda, and its ``agenda_hit`` no ``deed_id``, so a robbery could not be
  joined to the charge it put on the player's name.
- That a link can be BROKEN. ``law_link`` was append-only, and ``links()``'
  "a link the player has broken must stay broken" was true of nothing.
- Who the seed made the Magpie, as a CONDITION: ``agendas.role`` existed and
  no predicate read it.

WHAT THESE TESTS HOLD.

- ``arrest`` stamps ``since_hour`` (the first whole hour the clock has not
  crossed -- the first an agenda move can still fire at); ``release`` appends
  ``{since_hour, until_hour, jurisdiction}`` to ``custody_log``.
- An agenda move's ``report`` row carries ``agenda`` and ``hour``; its
  ``agenda_hit`` the report's ``deed_id``.
- ``alibi {agenda?, min?}`` holds when enough joined hits fall in a custody
  interval, past or live; ``agendas.alibi_deeds`` names them, and
  ``law_discharge {alibi: true}`` discharges them.
- ``law_unlink`` breaks a direct pair for good; every reader of links (wanted,
  the charge sheet, ``filed linked``, ``quash_reports linked``, the agenda's
  filing) stops counting the Magpie against ``self``; ``law_link`` refuses the
  pair again. ``linked {a, b}`` reads the belief.
- ``agenda_role {role, npc}`` holds iff the seed chose that NPC, draws
  nothing, and reaches no prompt.
- ``law_discharge`` and ``law_unlink`` are authored-only card effects; a
  model-composed challenge drops both.
- Old saves (no log, no broken links, no new row keys) load and behave as
  before; a story with no Law or no agendas is inert.

Version: v0.1.0 [2026-09-26]
"""

from __future__ import annotations

import copy
import json
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import pytest
import yaml

from engine.challenges import spec as spec_module
from engine.content import director
from engine.game.effects import apply_effect
from engine.game.quests import evaluate_condition
from engine.game.state import GameState
from engine.world import agendas, law

from test_agendas_moves import LIFT, MOVES_SPEC, TARGETS, _run, _world, story
from test_jobs import _rob

SQUARE = "edgewood_square"
MARKET = "millhaven_market"
TOWN = "town"
VILLAGE = "village"


@pytest.fixture()
def declared(tmp_path: Path) -> Iterator[Path]:
    with story(tmp_path, with_jobs=True):
        yield tmp_path


def _one_target(state: GameState) -> None:
    """Rob two of the three shining houses, so the lift has one choice and draws nothing."""
    _rob(state, TARGETS[0])
    _rob(state, TARGETS[2])


def _arrest(state: GameState) -> None:
    out = apply_effect(state, {"type": "arrest"})
    assert out["ok"], out


def _release(state: GameState) -> None:
    out = apply_effect(state, {"type": "release"})
    assert out["ok"], out


def _holds(state: GameState, condition: Any) -> bool:
    return evaluate_condition(state, condition)


# ---------------------------------------------------------------------------
# Custody history
# ---------------------------------------------------------------------------


def test_arrest_stamps_the_first_hour_still_to_come(declared: Path) -> None:
    state = _world(hour=20)
    _arrest(state)
    held = law.custody(state)
    # The clock reads 20.0: hour 20 was crossed before the arrest, so the
    # first hour the prisoner is held through is 21.
    assert held["since_hour"] == 21
    assert held["since_day"] == 1  # the day stamp is kept beside it


def test_a_fractional_clock_rounds_to_the_next_boundary(declared: Path) -> None:
    state = _world(hour=20)
    state.world_clock_hours = 20.5
    assert law.next_hour(state) == 21
    state.world_clock_hours = 20.0
    assert law.next_hour(state) == 21


def test_release_logs_the_interval(declared: Path) -> None:
    state = _world(hour=20)
    _arrest(state)
    jurisdiction = law.custody(state)["jurisdiction"]
    from engine.game.clock import advance_time

    advance_time(state, 6)
    _release(state)
    assert not law.in_custody(state)
    assert state.law["custody_log"] == [
        {"since_hour": 21, "until_hour": 27, "jurisdiction": jurisdiction}
    ]
    # A second stay appends.
    _arrest(state)
    advance_time(state, 2)
    _release(state)
    assert [row["since_hour"] for row in state.law["custody_log"]] == [21, 27]
    assert state.law["custody_log"][1]["until_hour"] == 29


def test_pay_and_serve_log_through_release(declared: Path) -> None:
    from test_law_arrest import _file

    state = _world(hour=20)
    _file(state, "fencing", 1)
    _arrest(state)
    out = law.serve_sentence(state)
    assert out["ok"] and out["served_out"]
    [row] = state.law["custody_log"]
    assert row["since_hour"] == 21
    assert row["until_hour"] == law.next_hour(state)


# ---------------------------------------------------------------------------
# Hits joined to reports
# ---------------------------------------------------------------------------


def test_an_agenda_report_carries_its_agenda_and_hour(declared: Path) -> None:
    state = _world(hour=20)
    _one_target(state)
    _run(state, 6)  # the lift fires at 25
    [report] = state.law["reports"]
    assert report["agenda"] == "the_magpie"
    assert report["hour"] == 25
    [hit] = state.agendas["hits"]
    assert hit == {"agenda": "the_magpie", "premise": TARGETS[1], "hour": 25,
                   "deed_id": report["deed_id"]}


def test_a_plain_report_carries_neither(declared: Path) -> None:
    from test_law_arrest import _file

    state = _world()
    _file(state, "fencing", 1)
    [report] = state.law["reports"]
    assert "agenda" not in report and "hour" not in report


def test_report_refuses_a_forged_stamp(declared: Path) -> None:
    state = _world()
    base = {"type": "report", "deed": "fencing", "guise": "self",
            "jurisdiction": VILLAGE, "precision": 1.0}
    bad_agenda = apply_effect(state, {**base, "agenda": "the_nobody", "hour": 3})
    assert bad_agenda["ok"] is False and "the_nobody" in bad_agenda["message"]
    bad_hour = apply_effect(state, {**base, "agenda": "the_magpie", "hour": "soon"})
    assert bad_hour["ok"] is False
    assert not state.law.get("reports")


def test_agenda_hit_refuses_a_malformed_deed_id(declared: Path) -> None:
    state = _world()
    out = apply_effect(state, {"type": "agenda_hit", "agenda": "the_magpie",
                               "premise": TARGETS[1], "hour": 3, "deed_id": 7})
    assert out["ok"] is False
    assert not state.agendas.get("hits")


def test_two_moves_in_one_hour_each_claim_their_own_deed(tmp_path: Path) -> None:
    doc = copy.deepcopy(MOVES_SPEC)
    doc["agendas"]["the_magpie"]["moves"] = [LIFT, {**LIFT, "id": "lift_again"}]
    with story(tmp_path, doc, with_jobs=True):
        state = _world(hour=20)
        _run(state, 6)
        hits = state.agendas["hits"]
        assert [h["hour"] for h in hits] == [25, 25]
        reports = state.law["reports"]
        assert len(reports) == 2
        assert [h["deed_id"] for h in hits] == [r["deed_id"] for r in reports]


def test_a_reactions_report_is_stamped_too(tmp_path: Path) -> None:
    """OWNER DECISION (fix round 1): a report an agenda REACTION files carries
    ``{agenda, hour}`` exactly as a move's does. (A reaction has no ``select``
    and so cannot rob: there is no hit for it to join.)"""
    doc = copy.deepcopy(MOVES_SPEC)
    doc["agendas"]["the_magpie"]["moves"] = []
    doc["agendas"]["the_magpie"]["reactions"] = [{
        "id": "cries_thief",
        "on": {"flag": "alarm_raised"},
        "once": True,
        "effects": [{"type": "report", "deed": "burglary", "guise": "magpie",
                     "jurisdiction": TOWN, "precision": 0.6}],
    }]
    with story(tmp_path, doc, with_jobs=True):
        state = _world(hour=20)
        assert apply_effect(state, {"type": "flag", "flag": "alarm_raised"})["ok"]
        _run(state, 1)
        [report] = state.law["reports"]
        assert report["agenda"] == "the_magpie" and report["hour"] == 21
        assert not state.agendas.get("hits")


def test_the_join_is_cut_invariant(declared: Path) -> None:
    """Twelve 1h calls and one 12h call write the same rows, stamps included."""
    one = _world(hour=20)
    many = _world(hour=20)
    _one_target(one)
    _one_target(many)
    _run(one, 12)
    for _ in range(12):
        _run(many, 1)
    assert one.law["reports"] == many.law["reports"]
    assert one.agendas["hits"] == many.agendas["hits"]


# ---------------------------------------------------------------------------
# The alibi
# ---------------------------------------------------------------------------


def test_a_robbery_while_held_is_an_alibi(declared: Path) -> None:
    state = _world(hour=20)
    _one_target(state)
    _arrest(state)
    town_before = law.wanted_band(state, "self", TOWN)
    _run(state, 6)  # lift at 25, inside the cell
    [report] = state.law["reports"]
    # Live custody: already an alibi, before release.
    assert _holds(state, {"alibi": {"agenda": "the_magpie"}})
    _release(state)
    assert _holds(state, {"alibi": {}})
    assert _holds(state, {"alibi": {"agenda": "the_magpie", "min": 1}})
    assert not _holds(state, {"alibi": {"min": 2}})
    assert agendas.alibi_deeds(state) == [report["deed_id"]]
    assert agendas.alibi_deeds(state, "the_magpie") == [report["deed_id"]]
    # The charge it put on your name is real until the alibi is presented.
    assert law.wanted_band(state, "self", TOWN) != town_before
    out = apply_effect(state, {"type": "law_discharge", "alibi": True})
    assert out["ok"], out
    assert not state.law.get("reports")
    assert report["deed_id"] in law.discharged(state)
    assert law.wanted_band(state, "self", TOWN) == town_before


def test_a_robbery_while_free_is_no_alibi(declared: Path) -> None:
    state = _world(hour=20)
    _one_target(state)
    _run(state, 6)
    assert state.agendas["hits"]
    assert not _holds(state, {"alibi": {}})
    assert agendas.alibi_deeds(state) == []
    out = apply_effect(state, {"type": "law_discharge", "alibi": True})
    assert out["ok"] is False
    assert state.law["reports"]


def test_a_robbery_in_the_hour_of_the_arrest_is_no_alibi(declared: Path) -> None:
    """The lift at 25 was walked before an arrest at 25:00 -- it is not covered."""
    state = _world(hour=20)
    _one_target(state)
    _run(state, 5)  # to 25.0; the lift fired at 25
    assert state.agendas["hits"][0]["hour"] == 25
    _arrest(state)
    assert law.custody(state)["since_hour"] == 26
    assert not _holds(state, {"alibi": {}})


def test_a_robbery_after_release_is_no_alibi(declared: Path) -> None:
    state = _world(hour=20)
    _one_target(state)
    _arrest(state)
    _run(state, 2)
    _release(state)  # until_hour 23
    _run(state, 4)  # lift at 25
    assert state.agendas["hits"][0]["hour"] == 25
    assert not _holds(state, {"alibi": {}})


def test_alibi_names_only_that_agendas_hits(declared: Path) -> None:
    state = _world(hour=20)
    _one_target(state)
    _arrest(state)
    _run(state, 6)
    assert not _holds(state, {"alibi": {"agenda": "the_crier"}})
    assert agendas.alibi_deeds(state, "the_crier") == []
    assert not _holds(state, {"alibi": {"agenda": "the_nobody"}})


def test_a_hit_with_no_deed_is_ignored(declared: Path) -> None:
    """An old hit (no ``deed_id``) cannot be joined to any charge."""
    state = _world(hour=20)
    _arrest(state)
    assert apply_effect(state, {"type": "agenda_hit", "agenda": "the_magpie",
                                "premise": TARGETS[1], "hour": 22})["ok"]
    assert not _holds(state, {"alibi": {}})
    assert agendas.alibi_deeds(state) == []


def test_an_open_alibi_is_one_not_yet_presented(declared: Path) -> None:
    """v0.16 T7: ``alibi {open: true}`` counts only the robberies whose deed
    is still on the books, so a card gated on it is offered once per alibi
    EARNED -- presented, it closes; a robbery in a later stay opens it again.
    ``alibi`` without ``open`` stays true once earned, as it always was."""
    state = _world(hour=20)
    _rob(state, TARGETS[0])  # two shining houses left: one a night, two nights
    assert not _holds(state, {"alibi": {"open": True}})
    _arrest(state)
    _run(state, 6)  # the first lift, at 25, inside the cell
    _release(state)
    assert _holds(state, {"alibi": {"agenda": "the_magpie", "open": True}})
    assert _holds(state, {"alibi": {"open": False}})  # false reads as the plain alibi
    assert apply_effect(state, {"type": "law_discharge", "alibi": True})["ok"]
    assert not _holds(state, {"alibi": {"open": True}})
    assert _holds(state, {"alibi": {}})  # earned is earned
    # A second robbery in a second stay opens a second alibi -- one of two.
    _arrest(state)
    _run(state, 24)  # the second lift, at 49
    _release(state)
    assert len(agendas.alibi_deeds(state)) == 2
    assert _holds(state, {"alibi": {"open": True}})
    assert not _holds(state, {"alibi": {"open": True, "min": 2}})
    assert apply_effect(state, {"type": "law_discharge", "alibi": True})["ok"]
    assert not _holds(state, {"alibi": {"open": True}})


def test_discharge_merges_named_ids_with_the_alibi(declared: Path) -> None:
    from test_law_arrest import _file

    state = _world(hour=20)
    _one_target(state)
    _file(state, "fencing", 1)
    [mine] = [r["deed_id"] for r in state.law["reports"]]
    _arrest(state)
    _run(state, 6)
    out = apply_effect(state, {"type": "law_discharge", "alibi": True, "deed_ids": [mine]})
    assert out["ok"], out
    assert not state.law.get("reports")
    assert mine in law.discharged(state)


# ---------------------------------------------------------------------------
# law_unlink and linked
# ---------------------------------------------------------------------------


def test_linked_reads_the_belief(declared: Path) -> None:
    state = _world()
    assert _holds(state, {"linked": {"a": "self", "b": "magpie"}})
    assert _holds(state, {"linked": {"a": "magpie", "b": "self"}})
    assert not _holds(state, {"linked": {"a": "self", "b": "porter"}})
    assert not _holds(state, {"linked": {"a": "self", "b": "nobody"}})
    assert not _holds(state, {"linked": {"a": "self"}})
    assert not _holds(state, {"linked": True})


def test_unlink_breaks_the_pair_for_good(declared: Path) -> None:
    state = _world()
    out = apply_effect(state, {"type": "law_unlink", "a": "self", "b": "magpie"})
    assert out["ok"], out
    assert state.law["links"] == []
    assert state.law["broken_links"] == [["self", "magpie"]]
    assert not _holds(state, {"linked": {"a": "self", "b": "magpie"}})
    assert law.same_person(state, "self") == {"self"}
    # A later link of the same pair, either way round, is refused.
    again = apply_effect(state, {"type": "law_link", "a": "magpie", "b": "self"})
    assert again["ok"] is False
    assert state.law["links"] == []
    # Other pairs still link.
    assert apply_effect(state, {"type": "law_link", "a": "self", "b": "porter"})["ok"]
    assert state.law["links"] == [["self", "porter"]]


def test_unlink_refuses_what_is_not_linked(declared: Path) -> None:
    state = _world()
    for effect in ({"a": "self", "b": "porter"}, {"a": "self", "b": "nobody"},
                   {"a": "self", "b": "self"}):
        out = apply_effect(state, {"type": "law_unlink", **effect})
        assert out["ok"] is False, effect
    assert "links" not in state.law and "broken_links" not in state.law


def _crowded(state: GameState) -> None:
    """One labourer idling on the square all day: someone to see a change of face."""
    state.procgen.npcs = [{"id": "gen_g_a", "name": "A", "role": "labourer",
                           "routine": [{"hours": list(range(24)), "location": SQUARE,
                                        "activity": "idling"}]}]


class _AlwaysNotices:
    def random(self) -> float:
        return 0.0


def _magpie_filed_then_unlinked() -> GameState:
    """A burglary on the Magpie's town file, then the self/magpie link broken."""
    state = _world(hour=20)
    assert apply_effect(state, {"type": "report", "deed": "burglary", "guise": "magpie",
                                "jurisdiction": TOWN, "precision": 1.0})["ok"]
    assert law.wanted_band(state, "self", TOWN) == "noticed"
    assert apply_effect(state, {"type": "law_unlink", "a": "self", "b": "magpie"})["ok"]
    assert law.wanted_band(state, "self", TOWN) == "unknown"
    return state


def test_a_seen_change_of_face_re_forms_a_broken_pair(
    declared: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """OWNER DECISION (v0.16 T2 fix round 1): a witness seeing the mask go back
    on is new evidence, so the broken pair re-forms and the Magpie's file
    counts against you again."""
    from engine.game.state import InventoryItem

    state = _magpie_filed_then_unlinked()
    _crowded(state)
    monkeypatch.setattr("engine.game.rng.world_rng", lambda s, stream: _AlwaysNotices())
    state.inventory.append(InventoryItem(id="golden_ring", name="ring", qty=1))
    out = law.change_guise(state, "magpie")
    assert out["ok"] and out["seen"]
    assert law.same_person(state, "self") == {"self", "magpie"}
    assert not law.is_broken(state, "self", "magpie")
    assert _holds(state, {"linked": {"a": "self", "b": "magpie"}})
    assert law.wanted_band(state, "self", TOWN) == "noticed"
    assert _holds(state, {"filed": {"jurisdiction": TOWN, "guise": "self", "linked": True}})


def test_an_unseen_change_of_face_leaves_the_pair_broken(declared: Path) -> None:
    from engine.game.state import InventoryItem

    state = _magpie_filed_then_unlinked()
    state.procgen.npcs = []  # nobody on the square to see it
    state.inventory.append(InventoryItem(id="golden_ring", name="ring", qty=1))
    out = law.change_guise(state, "magpie")
    assert out["ok"] and not out["seen"]
    assert law.is_broken(state, "self", "magpie")
    assert law.same_person(state, "self") == {"self"}
    assert law.wanted_band(state, "self", TOWN) == "unknown"


def test_an_authored_link_cannot_re_form_a_broken_pair(declared: Path) -> None:
    """Only the witness's writer id re-forms it; no YAML key can."""
    state = _magpie_filed_then_unlinked()
    for effect in ({"a": "self", "b": "magpie"}, {"a": "magpie", "b": "self"},
                   {"a": "self", "b": "magpie", "witnessed": True},
                   {"a": "self", "b": "magpie", "by": law.WRITER_WITNESS}):
        out = apply_effect(state, {"type": "law_link", **effect})
        assert out["ok"] is False, effect
    assert law.is_broken(state, "self", "magpie")
    assert law.wanted_band(state, "self", TOWN) == "unknown"
    # The witness's writer, and only it, re-forms the pair.
    assert apply_effect(state, {"type": "law_link", "a": "self", "b": "magpie"},
                        by=law.WRITER_WITNESS)["ok"]
    assert law.wanted_band(state, "self", TOWN) == "noticed"


def test_an_unlinked_magpie_no_longer_lands_on_you(declared: Path) -> None:
    """Every reader of links: wanted, the charge sheet, `filed linked`, the
    agenda's own filing -- and wanted is read live, so it moves at once."""
    state = _world(hour=20)
    _one_target(state)
    _run(state, 6)  # a burglary on the Magpie's file in town
    assert law.wanted_band(state, "self", TOWN) == "noticed"
    assert law.charged_deeds(state, "self", TOWN)
    assert _holds(state, {"filed": {"jurisdiction": TOWN, "guise": "self", "linked": True}})

    assert apply_effect(state, {"type": "law_unlink", "a": "self", "b": "magpie"})["ok"]
    assert law.wanted_band(state, "self", TOWN) == "unknown"
    assert law.wanted_band(state, "magpie", TOWN) == "noticed"
    assert law.charged_deeds(state, "self", TOWN) == {}
    assert law.sentence_for(state, "self", TOWN) == {"fine": 0, "days": 0}
    assert not _holds(state, {"filed": {"jurisdiction": TOWN, "guise": "self",
                                        "linked": True}})
    assert law.best_precision(state, "self", TOWN) == 0.0

    # `quash_reports linked` on your face no longer reaches the Magpie's file.
    apply_effect(state, {"type": "quash_reports", "jurisdiction": TOWN,
                         "guise": "self", "linked": True})
    assert len(state.law["reports"]) == 1


def test_the_next_lift_after_unlink_files_on_the_magpie_only(tmp_path: Path) -> None:
    lift = {**LIFT, "select": {"premise": {"tier_min": 2, "not_robbed": True}}}
    doc = copy.deepcopy(MOVES_SPEC)
    doc["agendas"]["the_magpie"]["moves"] = [lift]
    with story(tmp_path, doc, with_jobs=True):
        state = _world(hour=20)
        assert apply_effect(state, {"type": "law_unlink", "a": "self", "b": "magpie"})["ok"]
        _run(state, 6)
        [report] = state.law["reports"]
        assert report["guise"] == "magpie"
        where = report["jurisdiction"]
        assert law.wanted_score(state, "self", where) == 0.0
        assert law.wanted_score(state, "magpie", where) > 0.0


# ---------------------------------------------------------------------------
# agenda_role
# ---------------------------------------------------------------------------


def test_agenda_role_names_the_seeds_choice_and_draws_nothing(declared: Path) -> None:
    state = _world(seed=42)
    chosen = agendas.role(state, "magpie")
    before = json.dumps(state.to_save_dict(), sort_keys=True, default=str)
    counters = dict(state.rng_counters)
    for npc in ("npc_wren", "npc_silas", "npc_imelda"):
        held = _holds(state, {"agenda_role": {"role": "magpie", "npc": npc}})
        assert held is (npc == chosen), npc
    assert not _holds(state, {"agenda_role": {"role": "highwayman", "npc": chosen}})
    assert not _holds(state, {"agenda_role": {"role": "magpie"}})
    assert not _holds(state, {"agenda_role": True})
    assert state.rng_counters == counters
    assert json.dumps(state.to_save_dict(), sort_keys=True, default=str) == before


def test_every_candidate_is_someones_role(declared: Path) -> None:
    seen = set()
    for seed in range(30):
        state = _world(seed=seed)
        for npc in ("npc_wren", "npc_silas", "npc_imelda"):
            if _holds(state, {"agenda_role": {"role": "magpie", "npc": npc}}):
                seen.add(npc)
    assert seen == {"npc_wren", "npc_silas", "npc_imelda"}


def test_agenda_role_never_reaches_a_prompt() -> None:
    """HUE & CRY: asking the question changes no prompt block, and nothing in
    the prompt layer reads the predicate or the helper."""
    from engine.agents import prompts
    from engine.games import registry
    from engine.game.procgen import new_game_state

    registry.activate("hue-and-cry")
    state = new_game_state(seed=11)
    chosen = agendas.role(state, "magpie")
    before = prompts.world_state_block(state, {})
    for npc in ("npc_wren", "npc_silas", "npc_imelda"):
        _holds(state, {"agenda_role": {"role": "magpie", "npc": npc}})
    after = prompts.world_state_block(state, {})
    assert after == before
    assert "agenda_role" not in after and chosen not in after
    root = Path(__file__).resolve().parents[1] / "engine" / "agents"
    for source in root.rglob("*.py"):
        text = source.read_text(encoding="utf-8")
        assert "agenda_role" not in text, source
        assert "alibi_deeds" not in text, source


# ---------------------------------------------------------------------------
# Loader checks on the new predicates
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("gate", "message"), [
    ({"agenda_role": {"role": "highwayman", "npc": "npc_wren"}}, "not a declared role"),
    ({"agenda_role": {"role": "magpie", "npc": "npc_ardane"}}, "candidates"),
    ({"alibi": {"agenda": "the_nobody"}}, "not a declared agenda"),
    ({"alibi": {"min": 0}}, "at least 1"),
    ({"alibi": {"open": "yes"}}, "`alibi.open` must be true or false"),
    ({"linked": {"a": "self", "b": "nobody"}}, "`linked.b`"),
    ({"linked": {"a": "self"}}, "`linked.b`"),
])
def test_an_agenda_gate_on_a_new_predicate_is_checked(
    tmp_path: Path, gate: Any, message: str
) -> None:
    doc = copy.deepcopy(MOVES_SPEC)
    doc["agendas"]["the_magpie"]["moves"][0]["when"] = gate
    with story(tmp_path, doc, with_jobs=True):
        with pytest.raises(ValueError, match=message):
            agendas.spec()


def test_the_new_predicates_load_in_an_agenda_gate(tmp_path: Path) -> None:
    doc = copy.deepcopy(MOVES_SPEC)
    doc["agendas"]["the_magpie"]["moves"][0]["when"] = {"all": [
        {"agenda_role": {"role": "magpie", "npc": "npc_wren"}},
        {"none": [{"alibi": {"agenda": "the_magpie", "min": 2}}]},
        {"none": [{"alibi": {"open": True}}]},
        {"linked": {"a": "self", "b": "magpie"}},
    ]}
    with story(tmp_path, doc, with_jobs=True):
        assert agendas.spec()["agendas"]["the_magpie"]


@pytest.mark.parametrize("gate", [{"alibi": {}}, {"linked": {"a": "self", "b": "magpie"}}])
def test_the_law_predicates_need_a_law(tmp_path: Path, gate: Any) -> None:
    doc = copy.deepcopy(MOVES_SPEC)
    doc["agendas"]["the_magpie"]["moves"] = [
        {"id": "wait", "every_hours": 1, "when": gate}]
    with story(tmp_path, doc, lawful=False):
        with pytest.raises(ValueError, match="Law"):
            agendas.spec()


# ---------------------------------------------------------------------------
# Card access
# ---------------------------------------------------------------------------


def test_the_new_effects_are_authored_only() -> None:
    effects = [{"type": "law_discharge", "alibi": True},
               {"type": "law_discharge", "deed_ids": ["d1"]},
               {"type": "law_unlink", "a": "self", "b": "magpie"}]
    assert {"law_discharge", "law_unlink"} <= spec_module.STRUCTURAL_EFFECT_TYPES
    authored = spec_module.clamp_outcome({"effects": effects}, [], authored=True)
    assert authored["effects"] == effects
    notes: list[str] = []
    composed = spec_module.clamp_outcome({"effects": effects}, notes)
    assert composed["effects"] == []
    assert any("law_discharge" in n for n in notes) and any("law_unlink" in n for n in notes)
    # And a model-composed challenge, whole, drops them too.
    result = spec_module.validate({
        "kind": "dice_table", "id": "x", "title": "x", "die": 6,
        "outcomes": [{"min": 1, "max": 6, "text": "t", "effects": effects}],
    })
    assert result.ok, result.error
    assert [e for row in result.spec["outcomes"] for e in row["effects"]] == []
    # The same table from the story's own file keeps them.
    authored_table = spec_module.validate({
        "kind": "dice_table", "id": "x", "title": "x", "die": 6,
        "outcomes": [{"min": 1, "max": 6, "text": "t", "effects": effects}],
    }, authored=True)
    assert [e["type"] for row in authored_table.spec["outcomes"] for e in row["effects"]] \
        == ["law_discharge", "law_discharge", "law_unlink"]


def test_an_authored_card_may_remember_a_fact_and_a_model_may_not() -> None:
    """v0.16 T7: ``ledger_fact`` is structural -- a card from the story's own
    file may write what the story now knows (the Magpie unmasked), a
    model-composed challenge may not write itself into memory as truth."""
    fact = [{"type": "ledger_fact", "kind": "reveal", "subject_id": "npc_wren",
             "text": "Captain Ardane believed you."}]
    assert "ledger_fact" in spec_module.STRUCTURAL_EFFECT_TYPES
    assert "ledger_fact" not in spec_module.ALLOWED_EFFECT_TYPES
    authored = spec_module.clamp_outcome({"effects": fact}, [], authored=True)
    assert authored["effects"] == fact
    assert spec_module.clamp_outcome({"effects": fact}, [])["effects"] == []


def test_the_card_skill_hands_the_session_ledger_to_the_card(monkeypatch) -> None:
    """The ``card`` intent's skill passed ``ledger=None``, so a card's
    ``ledger_fact`` was dropped and a gate on ``disposition`` never held. It
    passes the session's ledger now, as the job skill does."""
    from types import SimpleNamespace

    from engine.skills.builtin import scenes

    seen: dict[str, Any] = {}
    ledger = object()
    monkeypatch.setattr(scenes, "get_active_engine",
                        lambda: SimpleNamespace(state=GameState(), ledger=ledger))
    monkeypatch.setattr(director, "resolve",
                        lambda state, chosen="", ledger=None: seen.update(ledger=ledger) or {})
    scenes.resolve_scene_card("resolve")
    assert seen["ledger"] is ledger


def _deck_dir(tmp_path: Path) -> str:
    deck = {
        "id": "the_alibi",
        "draw": 1,
        "when": {"alibi": {"agenda": "the_magpie"}},
        "cards": [{
            "id": "the_alibi_card",
            "required": True,
            "tags": ["sequence"],
            "title": "The Alibi",
            "text": "INTENT: the cells were your alibi.",
            "beats": [{
                "id": "present_it",
                "text": "You were in the cells that night.",
                "gate": {"when": {"alibi": {}}, "on_pass": {"effects": [
                    {"type": "law_discharge", "alibi": True, "agenda": "the_magpie"},
                    {"type": "law_unlink", "a": "self", "b": "magpie"},
                ]}},
            }],
        }],
    }
    folder = tmp_path / "scenes"
    folder.mkdir(exist_ok=True)
    (folder / "the_alibi.yaml").write_text(yaml.safe_dump(deck), encoding="utf-8")
    return str(folder)


@contextmanager
def deck_story(tmp_path: Path) -> Iterator[None]:
    """``story``'s synthetic city, plus one deck: the alibi."""
    from engine.config import set_overlay
    from engine.state import active as active_state
    from engine.state.schema import parse_schema
    from test_agendas import _dump, _paths
    from test_agendas_moves import CLOCKS_TABLE, STATE_YAML

    paths = _paths(tmp_path, MOVES_SPEC, with_jobs=True)
    paths["clocks"] = _dump(tmp_path / "clocks.yaml", CLOCKS_TABLE)
    paths["decks"] = _deck_dir(tmp_path)
    set_overlay({"paths": paths})
    active_state._schema = parse_schema(STATE_YAML, slug="synthetic")
    director._WARNED_FORCED = None
    try:
        yield
    finally:
        director._WARNED_FORCED = None
        active_state.reset_schema()
        set_overlay(None)


def test_a_card_presents_the_alibi(tmp_path: Path) -> None:
    with deck_story(tmp_path):
        state = _world(hour=20)
        _one_target(state)
        assert director.due(state) == ("", "", "")
        _arrest(state)
        _run(state, 6)
        _release(state)
        [report] = state.law["reports"]
        assert director.due(state)[0] == "the_alibi"
        dealt = [r for r in director.ensure_scene(state) if r["result"].get("ok")]
        assert dealt
        guard = 0
        while director.active(state) and guard < 16:
            director.resolve(state, chosen=director.options(state)[0]["id"])
            guard += 1
        assert report["deed_id"] in law.discharged(state)
        assert not state.law.get("reports")
        assert not _holds(state, {"linked": {"a": "self", "b": "magpie"}})


# ---------------------------------------------------------------------------
# Old saves and stories without the systems
# ---------------------------------------------------------------------------


def test_an_old_save_loads_and_behaves_as_before(declared: Path) -> None:
    """No log, no broken links, rows and hits without the new keys, and a live
    custody with no ``since_hour``: it loads, quashes, releases and links as
    it always did, and no alibi appears out of nothing."""
    state = _world(hour=20)
    old = state.to_save_dict()
    old["law"] = {
        "reports": [{"deed_id": "d1", "deed": "burglary", "severity": 3, "guise": "magpie",
                     "jurisdiction": TOWN, "precision": 1.0, "day": 1}],
        "deed_seq": 1,
        "custody": {"fine": 0, "days": 0, "since_day": 1, "jurisdiction": VILLAGE,
                    "guise": "self", "charged": []},
    }
    old["agendas"] = {"hits": [{"agenda": "the_magpie", "premise": TARGETS[1], "hour": 22}]}
    loaded = GameState.from_dict(json.loads(json.dumps(old)))
    assert law.in_custody(loaded)
    assert law.wanted_band(loaded, "self", TOWN) == "noticed"
    assert not _holds(loaded, {"alibi": {}})
    assert agendas.alibi_deeds(loaded) == []
    _release(loaded)
    # An interval with no start cannot be placed: nothing is logged.
    assert "custody_log" not in loaded.law
    # The old rows still quash, linked, exactly as before.
    apply_effect(loaded, {"type": "quash_reports", "jurisdiction": TOWN, "guise": "self",
                          "linked": True})
    assert not loaded.law.get("reports")
    assert apply_effect(loaded, {"type": "law_link", "a": "self", "b": "porter"})["ok"]
    assert "broken_links" not in loaded.law


def test_a_story_with_no_law_or_agendas_is_inert() -> None:
    state = GameState()
    before = json.dumps(state.to_save_dict(), sort_keys=True, default=str)
    assert apply_effect(state, {"type": "law_unlink", "a": "self", "b": "magpie"})["ok"] is False
    assert apply_effect(state, {"type": "law_discharge", "alibi": True})["ok"] is False
    for gate in ({"alibi": {}}, {"linked": {"a": "self", "b": "magpie"}},
                 {"agenda_role": {"role": "magpie", "npc": "npc_wren"}}):
        assert not _holds(state, gate), gate
    assert agendas.alibi_deeds(state) == []
    assert json.dumps(state.to_save_dict(), sort_keys=True, default=str) == before
