"""
Set-pieces are validated with the rest of a story's content (v0.17.0, T1).

THE GAP. ``paths.challenges`` was the one content directory neither
``scripts/doctor.py`` nor ``scripts/validate_content.py`` read. The runtime
loader (``set_pieces.load_set_pieces``) refuses a bad ``requires:`` -- logged
and skipped -- and nothing else: a piece at a place the graph lacks, a
``requires_flags: gate_open`` (a string, iterated letter by letter), a
challenge whose shape the spec validator rejects, or a ``release`` in a
FAILED break-out's outcome all loaded, and each either did nothing or did the
wrong thing, with nothing said until a player met it. HUE & CRY's jailbreak
(v0.17) is the first shipped set-piece to carry ``release``.

WHAT THESE TESTS HOLD. ``validation.validate_story`` -- the one pass doctor
and validate_content both run -- reports, naming the challenge file:

- a ``location_id`` that is not in the story's graph;
- a ``requires:`` the shared grammar cannot read;
- ``requires_flags`` / ``forbids_flags`` that are not a list of flag names,
  and a ``grants_flag`` that is not one flag name;
- a ``challenge`` the spec validator rejects;
- an outcome effect of a type no set-piece may apply;
- ``release`` anywhere but a challenge's success outcome (a ``reward``, or a
  dice-table row, which always succeeds).

And the flagship's shipped set-pieces stay clean.

Version: v0.1.0 [2026-09-27]
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest
import yaml

from engine.games import registry, validation

GOOD = {
    "id": "square_break",
    "location_id": "edgewood_square",
    "requires": {"flag": "scarecrow_awake"},
    "requires_flags": ["scarecrow_awake"],
    "forbids_flags": ["set_piece_square_break_done"],
    "grants_flag": "set_piece_square_break_done",
    "challenge": {
        "id": "square_break",
        "kind": "puzzle",
        "title": "The Loose Bar",
        "prompt": "What opens it?",
        "answer": "patience",
        "attempts": 2,
        "reward": {"text": "Free.", "effects": [{"type": "release"}, {"type": "awareness", "delta": 2}]},
        "fail": {"text": "The bar holds.", "effects": [{"type": "stamina", "delta": -5}]},
    },
}


def _issues(tmp_path: Path, pieces: list[dict[str, Any]]) -> list[str]:
    directory = tmp_path / "challenges"
    directory.mkdir(exist_ok=True)
    (directory / "pieces.yaml").write_text(
        yaml.safe_dump({"set_pieces": pieces}), encoding="utf-8"
    )
    manifest = registry.get("clockwork-dark")
    paths = dict(manifest.paths)
    paths["challenges"] = str(directory)
    patched = type(manifest)(**{**manifest.__dict__, "paths": paths})
    return [
        f"{i.source}|{i.ref_id}|{i.message}"
        for i in validation.errors_only(validation.validate_story(patched))
        if "pieces.yaml" in i.source
    ]


def _with(**changes: Any) -> dict[str, Any]:
    piece = copy.deepcopy(GOOD)
    for key, value in changes.items():
        if value is None:
            piece.pop(key, None)
        else:
            piece[key] = value
    return piece


def test_a_well_formed_set_piece_is_clean(tmp_path: Path) -> None:
    assert _issues(tmp_path, [copy.deepcopy(GOOD)]) == []


def test_the_flagships_shipped_set_pieces_are_clean() -> None:
    issues = validation.errors_only(validation.validate_story("clockwork-dark"))
    assert not [i for i in issues if "challenges" in i.source], issues


def test_a_location_the_graph_lacks_is_an_error(tmp_path: Path) -> None:
    issues = _issues(tmp_path, [_with(location_id="edgewood_sqaure")])
    assert any("edgewood_sqaure" in i and "square_break" in i for i in issues), issues


def test_an_unreadable_requires_is_an_error(tmp_path: Path) -> None:
    issues = _issues(tmp_path, [_with(requires={"in_custardy": True})])
    assert any("in_custardy" in i for i in issues), issues


@pytest.mark.parametrize("key,value", [
    ("requires_flags", "scarecrow_awake"),   # a string: iterated letter by letter
    ("requires_flags", ["two words"]),
    ("forbids_flags", [True]),               # YAML `yes`
    ("forbids_flags", {"a": 1}),
    ("grants_flag", ["set_piece_done"]),
    ("grants_flag", "set piece done"),
    ("grants_flag", ""),
])
def test_a_malformed_flag_is_an_error(tmp_path: Path, key: str, value: Any) -> None:
    issues = _issues(tmp_path, [_with(**{key: value})])
    assert any(key in i for i in issues), issues


@pytest.mark.parametrize("challenge", [
    None,                                     # no challenge at all
    {"kind": "riddle", "answer": "x"},        # no such kind
    {"kind": "puzzle", "prompt": "no answer"},
    {"kind": "skill_gauntlet", "steps": []},
])
def test_a_challenge_the_spec_rejects_is_an_error(tmp_path: Path, challenge: Any) -> None:
    issues = _issues(tmp_path, [_with(challenge=challenge)])
    assert any("challenge" in i for i in issues), issues


def test_an_effect_no_set_piece_may_apply_is_an_error(tmp_path: Path) -> None:
    piece = copy.deepcopy(GOOD)
    piece["challenge"]["reward"]["effects"].append({"type": "arrest"})
    piece["challenge"]["fail"]["effects"].append({"type": "stamnia", "delta": -1})
    issues = _issues(tmp_path, [piece])
    assert any("'arrest'" in i for i in issues), issues
    assert any("'stamnia'" in i for i in issues), issues


def test_release_in_a_failed_outcome_is_an_error(tmp_path: Path) -> None:
    piece = copy.deepcopy(GOOD)
    piece["challenge"]["fail"]["effects"].append({"type": "release"})
    issues = _issues(tmp_path, [piece])
    assert any("release" in i for i in issues), issues


def test_release_outside_the_challenge_is_an_error(tmp_path: Path) -> None:
    piece = copy.deepcopy(GOOD)
    piece["on_complete"] = [{"type": "release"}]
    issues = _issues(tmp_path, [piece])
    assert any("release" in i for i in issues), issues


def test_release_in_a_failure_node_of_a_tree_is_an_error(tmp_path: Path) -> None:
    piece = _with(challenge={
        "id": "square_break", "kind": "decision_tree", "start": "door",
        "nodes": {
            "door": {"text": "A door.", "options": [
                {"id": "push", "text": "Push", "goto": "open"},
                {"id": "wait", "text": "Wait", "goto": "caught"},
            ]},
            "open": {"terminal": True, "outcome": "success", "text": "Out.",
                     "reward": {"effects": [{"type": "release"}]}},
            "caught": {"terminal": True, "outcome": "failure", "text": "Caught.",
                       "fail": {"effects": [{"type": "release"}]}},
        },
    })
    issues = _issues(tmp_path, [piece])
    assert any("release" in i and "caught" in i for i in issues), issues
    assert not any("'open'" in i for i in issues), issues


def test_release_in_a_dice_table_row_is_allowed(tmp_path: Path) -> None:
    piece = _with(challenge={
        "id": "square_break", "kind": "dice_table", "die": 6,
        "outcomes": [{"min": 1, "max": 6, "text": "Out.", "effects": [{"type": "release"}]}],
    })
    assert _issues(tmp_path, [piece]) == []


def test_a_duplicate_or_missing_id_is_an_error(tmp_path: Path) -> None:
    issues = _issues(tmp_path, [copy.deepcopy(GOOD), copy.deepcopy(GOOD), _with(id=None)])
    assert any("duplicate" in i for i in issues), issues
    assert any("no id" in i for i in issues), issues
