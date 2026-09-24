"""
The casing board's payload: ``GameState.to_client_dict()['premises']``.

THE SHAPE. For the player's district: ``[{id, name, type_label, known, of,
empty_now}]``. ``known`` holds the TEXTS a watch has already learned, in
learning order -- never an id, and never a line nobody has watched for yet.
The id on each row is for the client's React key only; it must never appear
inside a ``known`` string, because the narrator and the player are never shown
one (no engine-authored pseudo-id rides along as if it were content).

DECLARATION IS THE SWITCH, same convention as threads and endings
(``GameState._structural_block``): a story that declares no
``paths.premises`` gets no ``premises`` key at all, so the flagship's payload
is exactly what it was before this task -- asserted here rather than assumed.

Built on ``test_premises.py``'s synthetic fixture and ``test_casing.py``'s
hand-built household, because HUE & CRY's own premises land in a later task.

Version: v0.1.0 [2026-09-23]
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator

import pytest

from engine.config import set_overlay
from engine.game.clock import set_clock
from engine.game.effects import apply_effect
from engine.game.procgen import generate_world
from engine.game.state import GameState
from engine.world import npc_sim

from test_premises import _build

SQUARE = "edgewood_square"


@pytest.fixture()
def declared(tmp_path: Path) -> Iterator[Path]:
    root = _build(tmp_path / "premises")
    set_overlay({"paths": {"premises": str(root)}})
    try:
        yield root
    finally:
        set_overlay(None)


def _hand_built(state: GameState, routines: list[list[dict[str, Any]]]) -> dict[str, Any]:
    """One townhouse on the square with a household of the given routines."""
    pid = "prem_hand_1"
    home = npc_sim.interior_id(SQUARE, pid)
    members = []
    for idx, routine in enumerate(routines):
        members.append(
            {
                "id": f"gen_hand_1_m{idx}",
                "name": f"Person {idx}",
                "role": "master",
                "home": home,
                "premise": pid,
                "routine": routine,
            }
        )
    prem = {
        "id": pid,
        "district": SQUARE,
        "type": "townhouse",
        "anchor": False,
        "name": "the Hand house",
        "tier": 1,
        "household": [m["id"] for m in members],
        "security": ["good_lock"],
        "loot": ["golden_ring", "loaf"],
        "secret": "debt_letter",
    }
    state.procgen.premises = [prem]
    state.procgen.npcs = members
    return prem


# -- undeclared: the flagship must not notice this system exists -------------


def test_undeclared_premises_leave_the_payload_with_no_key_at_all() -> None:
    state = GameState(rng_seed=1, location_id=SQUARE)
    payload = state.to_client_dict()
    assert "premises" not in payload


# -- declared: the shape ------------------------------------------------------


def test_payload_holds_one_row_per_house_in_the_players_district(declared: Path) -> None:
    state = GameState(rng_seed=42, location_id=SQUARE)
    state.procgen = generate_world(42)
    set_clock(state, day=1, hour=8)

    payload = state.to_client_dict()
    assert "premises" in payload
    board = payload["premises"]
    here = [p for p in state.procgen.premises if p["district"] == SQUARE]
    assert len(board) == len(here)
    for row in board:
        assert set(row) == {"id", "name", "type_label", "known", "of", "empty_now"}
        assert isinstance(row["known"], list)
        assert isinstance(row["of"], int) and row["of"] > 0
        assert isinstance(row["empty_now"], bool)
        assert row["type_label"]  # every type in the fixture declares one


def test_a_district_with_no_premises_gets_an_empty_list_not_an_absent_key(
    declared: Path,
) -> None:
    state = GameState(rng_seed=42, location_id="forest_clearing")
    state.procgen = generate_world(42)
    payload = state.to_client_dict()
    assert payload["premises"] == []


def test_known_carries_only_learned_texts_in_learning_order(declared: Path) -> None:
    state = GameState(rng_seed=3, location_id=SQUARE)
    _hand_built(state, [[]])

    board = state.to_client_dict()["premises"]
    row = next(r for r in board if r["id"] == "prem_hand_1")
    assert row["known"] == [], "nothing has been watched yet"
    assert row["of"] == 1 + 1 + 1 + 1  # occupancy, one security row, loot, secret

    apply_effect(state, {"type": "intel", "premise": "prem_hand_1", "intel": "occupancy"})
    apply_effect(
        state, {"type": "intel", "premise": "prem_hand_1", "intel": "security:good_lock"}
    )
    board = state.to_client_dict()["premises"]
    row = next(r for r in board if r["id"] == "prem_hand_1")
    assert row["known"] == ["never empty", "a good lock on the street door"]


def test_no_premise_id_or_unlearned_text_leaks_into_known(declared: Path) -> None:
    state = GameState(rng_seed=3, location_id=SQUARE)
    _hand_built(state, [[]])
    apply_effect(
        state, {"type": "intel", "premise": "prem_hand_1", "intel": "security:good_lock"}
    )
    board = state.to_client_dict()["premises"]
    row = next(r for r in board if r["id"] == "prem_hand_1")
    for text in row["known"]:
        assert "prem_" not in text
        assert "security:" not in text
    # And nothing about the loot or the secret's existence has leaked in yet.
    assert "worth it" not in " ".join(row["known"])
    assert "hiding something" not in " ".join(row["known"])


# -- empty_now: right now, not the day's longest run --------------------------


def test_empty_now_is_true_when_nobody_currently_resolves_home(declared: Path) -> None:
    state = GameState(rng_seed=1, location_id=SQUARE)
    set_clock(state, day=1, hour=12)
    _hand_built(
        state,
        [[{"hours": list(range(9, 17)), "location": "edgewood_bakery", "activity": "baking"}]],
    )
    board = state.to_client_dict()["premises"]
    row = next(r for r in board if r["id"] == "prem_hand_1")
    assert row["empty_now"] is True


def test_empty_now_is_false_when_a_household_member_is_home(declared: Path) -> None:
    state = GameState(rng_seed=1, location_id=SQUARE)
    set_clock(state, day=1, hour=20)
    _hand_built(
        state,
        [[{"hours": list(range(9, 17)), "location": "edgewood_bakery", "activity": "baking"}]],
    )
    board = state.to_client_dict()["premises"]
    row = next(r for r in board if r["id"] == "prem_hand_1")
    assert row["empty_now"] is False
