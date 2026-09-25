"""
Custody you can read, and a jailbreak that can free you (v0.13.0, Task 2).

THE GAP. The ``arrest`` effect writes ``state.law["custody"]`` and sets no
flag, and ``law.in_custody`` was a function nothing in the condition grammar
could name. Set-pieces gated only on flags, and their rewards ran through the
strict (model-composed) allowlist, which drops ``release``. So a story could
hold the player and offer two ways out -- pay or serve -- but could not author
a third: a break-out scene offered only in the cell, whose success frees the
player.

WHAT THESE TESTS HOLD.

- ``{in_custody: bool}`` is a grammar predicate: true exactly while held,
  across arrest, pay_fine, serve, a bare release and a death in the cells;
  false (and ``{in_custody: false}`` true) in a story with no Law.
- A set-piece may carry ``requires:`` -- a condition in the shared grammar --
  and one gated on ``{in_custody: true}`` is offered by ``legal_intents`` in
  the cell and nowhere else. An unknown predicate there is refused at load.
- An AUTHORED challenge (a set-piece) may pay ``{type: release}``: its success
  clears custody and charges nothing else. A model-composed spec still cannot
  (the strict path drops it), and neither can a thread or a deck gate, whose
  authored path widens by the structural kinds only.
- The flagship's set-pieces bound identically on the authored path.

Version: v0.1.0 [2026-09-25]
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Iterator

import pytest
import yaml

from engine.challenges import runner, set_pieces
from engine.challenges import spec as spec_module
from engine.config import set_overlay
from engine.game import intents, quests
from engine.game.effects import apply_effect
from engine.game.state import GameState
from engine.world import law

from test_law_arrest import GAOL, SQUARE, _file, _held, _paths, _verbs, _world

JAILBREAK = {
    "id": "lantern_house_break",
    "location_id": GAOL,
    "requires": {"in_custody": True},
    "grants_flag": "broke_out_of_the_lantern_house",
    "challenge": {
        "id": "lantern_house_break",
        "kind": "puzzle",
        "title": "The Loose Bar",
        "prompt": "One bar in the window turns in its socket. What opens it?",
        "answer": "patience",
        "attempts": 2,
        "reward": {
            "text": "The bar comes free and the night takes you.",
            "effects": [{"type": "release"}],
        },
        "fail": {"text": "The bar holds.", "effects": []},
    },
}


def _write_pieces(tmp_path: Path, pieces: list[dict[str, Any]]) -> str:
    directory = tmp_path / "challenges"
    directory.mkdir(exist_ok=True)
    (directory / "cells.yaml").write_text(
        yaml.safe_dump({"set_pieces": pieces}), encoding="utf-8"
    )
    return str(directory)


@pytest.fixture()
def cells(tmp_path: Path) -> Iterator[Path]:
    paths = _paths(tmp_path)
    paths["challenges"] = _write_pieces(tmp_path, [copy.deepcopy(JAILBREAK)])
    set_pieces.reset_set_piece_cache()
    set_overlay({"paths": paths})
    try:
        yield tmp_path
    finally:
        set_overlay(None)
        set_pieces.reset_set_piece_cache()


def _held_clause(state: GameState, want: bool = True) -> bool:
    return quests.evaluate_condition(state, {"in_custody": want})


# -- the predicate --------------------------------------------------------------


def test_in_custody_is_a_grammar_predicate() -> None:
    assert "in_custody" in quests.predicate_names()


def test_in_custody_tracks_arrest_and_pay_fine(cells: Path) -> None:
    state = _world([])
    assert _held_clause(state) is False and _held_clause(state, False) is True
    _held(state)
    assert _held_clause(state) is True and _held_clause(state, False) is False
    state.stats.gold = 100
    assert law.pay_fine(state)["ok"]
    assert _held_clause(state) is False and _held_clause(state, False) is True


def test_in_custody_tracks_serve(cells: Path) -> None:
    state = _world([])
    _held(state)
    assert _held_clause(state) is True
    assert law.serve_sentence(state)["ok"]
    assert _held_clause(state) is False


def test_in_custody_tracks_a_bare_release(cells: Path) -> None:
    state = _world([])
    _held(state)
    assert apply_effect(state, {"type": "release"})["ok"]
    assert _held_clause(state) is False


def test_in_custody_falls_when_the_prisoner_dies(cells: Path) -> None:
    from engine.game.clock import advance_time

    state = _world([])
    _held(state)
    assert _held_clause(state) is True
    state.stats.hp = 0
    advance_time(state, 1.0)  # the death check carries the body out
    assert _held_clause(state) is False


def test_in_custody_is_false_in_a_story_with_no_law() -> None:
    state = GameState(rng_seed=1)
    assert not law.declared()
    # A stray custody record cannot make a story with no watch "hold" anyone.
    state.law["custody"] = {"fine": 1, "days": 1}
    assert _held_clause(state) is False
    assert _held_clause(state, False) is True


def test_in_custody_needs_a_law_to_gate_an_agenda() -> None:
    from engine.world import agendas

    assert "in_custody" in agendas.LAW_PREDICATES


# -- the gate: `requires:` on a set-piece -------------------------------------------


def test_a_custody_gated_set_piece_is_offered_in_the_cell_and_not_outside(cells: Path) -> None:
    state = _world([])
    state.location_id = GAOL
    assert "set_piece" not in _verbs(state)  # standing in the barracks, free
    _held(state)
    assert state.location_id == GAOL
    verbs = _verbs(state)
    assert "set_piece" in verbs
    assert verbs["set_piece"].targets == ("lantern_house_break",)
    assert "travel" not in verbs  # held: the break-out is the way out, not a road


def test_start_refuses_a_custody_gated_piece_when_free(cells: Path) -> None:
    state = _world([])
    state.location_id = GAOL
    result = set_pieces.start(state, "lantern_house_break")
    assert result.status == runner.STATUS_ERROR
    assert not state.challenge


def test_an_unknown_predicate_in_requires_is_refused_at_load(tmp_path: Path) -> None:
    bad = copy.deepcopy(JAILBREAK)
    bad["requires"] = {"in_custardy": True}
    paths = _paths(tmp_path)
    paths["challenges"] = _write_pieces(tmp_path, [bad])
    set_pieces.reset_set_piece_cache()
    set_overlay({"paths": paths})
    try:
        assert "lantern_house_break" not in set_pieces.load_set_pieces()
    finally:
        set_overlay(None)
        set_pieces.reset_set_piece_cache()


def test_a_requires_mixing_a_group_and_a_sibling_is_refused_at_load(tmp_path: Path) -> None:
    bad = copy.deepcopy(JAILBREAK)
    bad["requires"] = {"all": [{"in_custody": True}], "flag": "x"}
    paths = _paths(tmp_path)
    paths["challenges"] = _write_pieces(tmp_path, [bad])
    set_pieces.reset_set_piece_cache()
    set_overlay({"paths": paths})
    try:
        assert "lantern_house_break" not in set_pieces.load_set_pieces()
    finally:
        set_overlay(None)
        set_pieces.reset_set_piece_cache()


@pytest.mark.parametrize("clause", [
    {"disposition": {"npc": "npc_wren", "min": 1}},
    {"days_in_stage": 2},
    {"any": [{"flag": "x"}, {"days_since_started": 3}]},
])
def test_a_requires_needing_a_ledger_or_a_quest_is_refused_at_load(
    tmp_path: Path, clause: dict
) -> None:
    """`is_available` evaluates with no ledger and no quest record: these
    would be unmet forever, a piece that loads and is never offered."""
    bad = copy.deepcopy(JAILBREAK)
    bad["requires"] = clause
    paths = _paths(tmp_path)
    paths["challenges"] = _write_pieces(tmp_path, [bad])
    set_pieces.reset_set_piece_cache()
    set_overlay({"paths": paths})
    try:
        assert "lantern_house_break" not in set_pieces.load_set_pieces()
    finally:
        set_overlay(None)
        set_pieces.reset_set_piece_cache()


# -- the payoff: `release` from an authored challenge -------------------------------


def test_the_jailbreak_frees_the_player_and_charges_nothing_else(cells: Path) -> None:
    from engine.agents.tool_dispatcher import execute_intent
    from engine.game.engine import GameEngine

    state = _world([])
    state.location_id = SQUARE
    _file(state, "pickpocket", 1)
    _held(state)
    engine = GameEngine(state)
    (started,) = execute_intent({"action": "set_piece", "target": "lantern_house_break"}, engine)
    assert started["success"] and not started.get("refused")
    assert _verbs(state).keys() == {"challenge"}  # the break-out owns the turn

    stats = state.stats.model_dump() if hasattr(state.stats, "model_dump") else dict(vars(state.stats))
    hours = state.world_clock_hours
    reports = copy.deepcopy(state.law.get("reports"))
    inventory = [(e.id, e.qty) for e in state.inventory]

    (solved,) = execute_intent({"action": "challenge", "target": "patience"}, engine)
    assert solved["success"] and not solved.get("refused")

    assert not law.in_custody(state)
    assert state.flags.get("broke_out_of_the_lantern_house") is True
    after = state.stats.model_dump() if hasattr(state.stats, "model_dump") else dict(vars(state.stats))
    assert after == stats
    assert state.world_clock_hours == hours
    assert state.law.get("reports") == reports  # walked out still wanted
    assert [(e.id, e.qty) for e in state.inventory] == inventory
    assert state.location_id == GAOL  # released, not carried anywhere
    verbs = _verbs(state)
    assert "travel" in verbs and "serve" not in verbs and "set_piece" not in verbs


def test_a_failed_jailbreak_leaves_the_player_held(cells: Path) -> None:
    state = _world([])
    _held(state)
    assert set_pieces.start(state, "lantern_house_break").status != runner.STATUS_ERROR
    set_pieces.resolve(state, answer="wrong")
    set_pieces.resolve(state, answer="still wrong")
    assert not state.challenge
    assert law.in_custody(state)


def test_a_model_composed_challenge_cannot_release() -> None:
    raw = copy.deepcopy(JAILBREAK["challenge"])
    strict = spec_module.validate(raw)
    assert strict.ok
    assert strict.spec["reward"]["effects"] == []
    assert any("release" in a for a in strict.adjustments)
    authored = spec_module.validate(raw, authored=True)
    assert authored.spec["reward"]["effects"] == [{"type": "release"}]


def test_a_thread_still_cannot_release() -> None:
    from engine.game import threads

    adjustments: list[str] = []
    assert threads._bound_effects([{"type": "release"}], adjustments) == []
    assert any("release" in a for a in adjustments)
    # And the authored outcome path that threads and deck gates share stays
    # structural-only: `release` is a set-piece's alone.
    out = spec_module.clamp_outcome({"effects": [{"type": "release"}]}, [], authored=True)
    assert out["effects"] == []
    assert "release" not in spec_module.STRUCTURAL_EFFECT_TYPES


# -- byte-identical --------------------------------------------------------------


def test_the_flagship_set_pieces_bound_identically_on_the_authored_path() -> None:
    set_pieces.reset_set_piece_cache()
    try:
        catalogue = set_pieces.load_set_pieces()
        assert catalogue, "the flagship ships set-pieces"
        for piece in catalogue.values():
            assert "requires" not in piece
            strict = spec_module.validate(piece["challenge"])
            authored = spec_module.validate(piece["challenge"], authored=True)
            assert strict.ok and authored.ok
            assert authored.spec == strict.spec
            assert authored.adjustments == strict.adjustments
    finally:
        set_pieces.reset_set_piece_cache()
