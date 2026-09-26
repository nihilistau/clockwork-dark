"""
Two optional thread-template keys, v0.15 (HUE & CRY's fence credit):

  * ``repeatable: true`` -- a template that may be struck again once no copy
    of it is open. A line of credit is a thing you can run up, pay off and run
    up again; a bribe is struck once a run. Without the key a struck template
    is never offered again, whatever became of it (unchanged).
  * ``broken_text:`` -- authored words the narrator is given, once, when the
    thread breaks (``engine/game/moved.py``, kind ``promise``). A thread that
    comes due unpaid used to break in silence: its ``on_break`` applied and
    nothing told the prose why the world had turned. Without the key a break
    journals nothing (unchanged).

Driven against a synthetic threads.yaml so the seam is proved apart from any
story's content.

Version: v0.1.0 [2026-09-26]
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

import pytest

from engine.config import set_overlay
from engine.game import threads
from engine.game.state import GameState

RULES = """
version: 1
tags: [Credit, Bribe]
templates:
  slate:
    title: "A slate"
    source: lender
    tags: [Credit]
    repeatable: true
    terms: "Five now, eight back inside two days."
    due_in_days: 2
    on_seal: [{ type: gold, delta: 5 }]
    requires: { none: [{ flag: blacklisted }] }
    discharge_requires: { min_gold: 8 }
    on_discharge: [{ type: gold, delta: -8 }]
    on_break: [{ type: flag, flag: welshed }]
    broken_text: "The lender's slate came due and you never paid it."
    refusals:
      - when: { flag: blacklisted }
        text: "no lender stands credit to a known welsher"
  once:
    title: "A bribe"
    source: sergeant
    tags: [Bribe]
    terms: "Twelve in the tin."
    due_in_days: 1
    on_break: [{ type: flag, flag: bribe_lapsed }]
"""


@pytest.fixture
def state(tmp_path: Path) -> Iterator[GameState]:
    path = tmp_path / "threads.yaml"
    path.write_text(RULES, encoding="utf-8")
    set_overlay({"paths": {"threads": str(path)}})
    try:
        yield GameState(rng_seed=7)
    finally:
        set_overlay(None)


def _offered(state: GameState) -> set[str]:
    return {row["id"] for row in threads.offerable(state)}


def _seal(state: GameState, template_id: str) -> dict:
    sealed = threads.seal(state, threads.offer(state, template_id))
    assert sealed["ok"], sealed
    return sealed["thread"]


def test_a_repeatable_template_is_not_offered_while_a_copy_is_open(state) -> None:
    assert {"slate", "once"} <= _offered(state)
    _seal(state, "slate")
    assert "slate" not in _offered(state)
    assert threads.can_strike(state, "slate") is False


def test_a_repeatable_template_is_offered_again_once_settled(state) -> None:
    first = _seal(state, "slate")
    state.stats.gold = 10
    assert threads.discharge(state, first["id"])["ok"]
    assert "slate" in _offered(state)
    assert threads.can_strike(state, "slate") is True
    second = _seal(state, "slate")
    assert second["id"] != first["id"]


def test_a_repeatable_template_is_offered_again_once_broken(state) -> None:
    """Whether a lender lends again after a break is the template's `requires`, not this key."""
    first = _seal(state, "slate")
    assert threads.break_thread(state, first["id"])["ok"]
    assert "slate" in _offered(state)


def test_a_template_without_the_key_is_struck_once_a_run(state) -> None:
    thread = _seal(state, "once")
    assert "once" not in _offered(state)
    assert threads.can_strike(state, "once") is False
    threads.discharge(state, thread["id"])
    assert "once" not in _offered(state)
    assert threads.can_strike(state, "once") is False


def test_a_break_with_broken_text_tells_the_narrator_once(state) -> None:
    from engine.agents.prompts import moved_block

    thread = _seal(state, "slate")
    assert state.moved == []
    state.world_clock_hours += 24 * 3
    threads.expire_due(state)
    assert threads.get(state, thread["id"])["status"] == threads.STATUS_BROKEN
    assert state.moved == [{
        "kind": "promise",
        "text": "The lender's slate came due and you never paid it.",
        "location_id": "",
    }]
    assert "The lender's slate came due" in moved_block(state)


def test_a_settled_thread_journals_nothing(state) -> None:
    thread = _seal(state, "slate")
    state.stats.gold = 10
    threads.discharge(state, thread["id"])
    assert state.moved == []


def test_a_break_without_broken_text_journals_nothing(state) -> None:
    """Every thread a story wrote before the key breaks exactly as it always did."""
    thread = _seal(state, "once")
    assert "broken_text" not in thread
    state.world_clock_hours += 24 * 3
    threads.expire_due(state)
    assert threads.get(state, thread["id"])["status"] == threads.STATUS_BROKEN
    assert state.moved == []


def test_a_sealed_thread_without_the_keys_keeps_its_shape(state) -> None:
    """Carried only when declared, like `discharge_requires`: old saves and stories unchanged."""
    thread = _seal(state, "once")
    assert "broken_text" not in thread and "repeatable" not in thread


def test_the_validator_refuses_a_repeatable_that_is_not_a_bool_and_an_empty_broken_text(
    tmp_path: Path,
) -> None:
    import shutil

    import yaml

    from engine.games import registry, validation

    manifest = registry.get("hue-and-cry")
    rules = tmp_path / "threads.yaml"
    shutil.copy(manifest.resolve(manifest.paths["threads"]), rules)
    doc = yaml.safe_load(rules.read_text(encoding="utf-8"))
    doc["templates"]["pell_advance"]["repeatable"] = "yes"
    doc["templates"]["marrow_slate"]["broken_text"] = "  "
    rules.write_text(yaml.safe_dump(doc), encoding="utf-8")
    patched = type(manifest)(**{**manifest.__dict__, "paths": {**manifest.paths, "threads": str(rules)}})

    errors = [f"{i.ref_id}|{i.message}" for i in validation.errors_only(validation.validate_story(patched))]
    assert any(e.startswith("pell_advance|repeatable must be true or false") for e in errors), errors
    assert any(e.startswith("marrow_slate|broken_text") for e in errors), errors
    clean = validation.errors_only(validation.validate_story(manifest))
    assert not [i for i in clean if i.ref_id in ("pell_advance", "marrow_slate")], clean


def test_the_validator_refuses_a_refusal_that_can_never_be_voiced_or_hold(tmp_path: Path) -> None:
    import shutil

    import yaml

    from engine.games import registry, validation

    manifest = registry.get("hue-and-cry")
    tables = tmp_path / "tables"
    shutil.copytree(manifest.resolve(manifest.paths["tables"]), tables)
    doc = yaml.safe_load((tables / "trade.yaml").read_text(encoding="utf-8"))
    doc["vendors"]["npc_pell_hollis"]["refuses_to_buy"] = {"when": {"moon_phase": "full"}, "text": "No."}
    doc["vendors"]["npc_marrow"]["refuses_to_buy"] = {"when": {"flag": "welshed_on_marrow"}}
    doc["vendors"]["npc_dock_mag"]["refuses_to_buy"] = {"when": {"disposition": {"npc": "x", "min": 1}},
                                                        "text": "No."}
    (tables / "trade.yaml").write_text(yaml.safe_dump(doc), encoding="utf-8")
    patched = type(manifest)(**{**manifest.__dict__, "paths": {**manifest.paths, "tables": str(tables)}})

    errors = [f"{i.ref_id}|{i.message}" for i in validation.errors_only(validation.validate_story(patched))]
    assert any(e.startswith("npc_pell_hollis|") and "moon_phase" in e for e in errors), errors
    assert any(e.startswith("npc_marrow|") and "needs a `text`" in e for e in errors), errors
    assert any(e.startswith("npc_dock_mag|") and "ledger" in e for e in errors), errors
    clean = validation.errors_only(validation.validate_story(manifest))
    assert not [i for i in clean if "refuses_to_buy" in i.message], clean


def test_a_refusal_row_says_why_when_its_condition_holds(state) -> None:
    assert threads.strike_refusal(state, "slate") == ""
    state.flags["blacklisted"] = True
    assert threads.strike_refusal(state, "slate") == "no lender stands credit to a known welsher"
    assert threads.strike_refusal(state, "once") == ""   # a template with none


def test_the_validator_refuses_a_refusal_row_with_no_words_or_a_bad_condition() -> None:
    assert threads.template_key_problems({"refusals": "no"}) == [
        "refusals must be a list of {when, text}"]
    assert threads.template_key_problems({"refusals": [{"when": {"flag": "x"}}]}) == [
        "refusals[0] needs a `when` and a `text`"]
    problems = threads.template_key_problems(
        {"refusals": [{"when": {"moon_phase": "full"}, "text": "No."}]})
    assert problems and "moon_phase" in problems[0], problems
    assert threads.template_key_problems(
        {"refusals": [{"when": {"flag": "x"}, "text": "No."}]}) == []
