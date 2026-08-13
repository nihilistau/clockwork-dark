"""
Hidden forest paths — procgen output that nothing could reach, wired.

``engine/game/procgen.py::_build_forest`` has minted two hidden paths per world
(label, destination, seeded DC) since PR7, and no code ever read one. They work
now the way the forage nodes they were minted beside do: dealt across the
forageable places, noticed by a good survival roll while working the ground,
and once noticed they are a real shortcut -- travel between the path's two ends
costs ``SHORTCUT_HOURS`` whether or not the map draws a road there.
"""

from __future__ import annotations

import json

import pytest

from engine.game import checks, foraging
from engine.game.dice import DiceResult
from engine.game.engine import GameEngine
from engine.game.procgen import new_game_state
from engine.game.state import GameState


def _check(total: int, degree: str) -> checks.CheckResult:
    dice = DiceResult(
        sides=20, rolls=[10], modifier=0, total=total,
        critical=False, fumble=False, reason="forage",
    )
    return checks.CheckResult(
        skill="survival", stat="wits", dc=10, difficulty="standard",
        dice=dice, modifiers=[], total=total, margin=total - 10, degree=degree,
    )


def _force_check(monkeypatch, total: int, degree: str) -> None:
    monkeypatch.setattr(
        checks, "resolve", lambda *a, **k: _check(total, degree)
    )


def _plant_path(state: GameState, home_hint: str = "", **overrides) -> dict:
    """Replace the seeded pool with one controlled path homed where we want it."""
    path = {
        "id": "hidden_path_1",
        "label": "deer track",
        "leads_to": "old_barrows",
        "dc": 12,
        **overrides,
    }
    state.procgen.forest["hidden_paths"] = [path]
    return path


# ---------------------------------------------------------------------------
# the deal
# ---------------------------------------------------------------------------


def test_every_seeded_path_is_dealt_to_exactly_one_forageable_place():
    state = new_game_state(seed=42)
    paths = foraging.hidden_paths(state)
    assert paths, "procgen stopped minting hidden paths"

    places = sorted(foraging._all_forageable_places())
    for path in paths:
        home = foraging.path_home(state, str(path["id"]))
        assert home in places, f"{path['id']} was dealt nowhere"


def test_an_undiscovered_path_changes_nothing():
    state = new_game_state(seed=42)
    _plant_path(state)

    assert foraging.discovered_paths(state) == []
    assert foraging.shortcut_hours(state, "forest_clearing", "old_barrows") is None
    # The graph has no forest_clearing -> old_barrows edge, so travel refuses
    # exactly as it did before the feature existed.
    move = GameEngine(state).move_to("old_barrows")
    assert move.success is False


# ---------------------------------------------------------------------------
# discovery
# ---------------------------------------------------------------------------


def test_a_good_forage_roll_discovers_a_path_through_apply_effect(monkeypatch):
    state = new_game_state(seed=42)
    path = _plant_path(state, dc=12)
    home = foraging.path_home(state, "hidden_path_1")
    state.location_id = home
    _force_check(monkeypatch, total=15, degree="success")

    outcome = foraging.forage(state)

    assert outcome["discovery"] is not None
    assert outcome["discovery"]["id"] == "hidden_path_1"
    assert outcome["discovery"]["leads_to"] == "old_barrows"
    assert outcome["discovery"]["effect"]["type"] == "flag", (
        "discovery must land through the effect dispatcher, not a bare write"
    )
    assert state.flags.get("hidden_path_found:hidden_path_1") is True
    assert "deer track" in outcome["text"]


def test_a_roll_under_the_path_dc_finds_nothing(monkeypatch):
    state = new_game_state(seed=42)
    _plant_path(state, dc=16)
    home = foraging.path_home(state, "hidden_path_1")
    state.location_id = home
    _force_check(monkeypatch, total=13, degree="success")

    outcome = foraging.forage(state)

    assert outcome["discovery"] is None
    assert not state.flags.get("hidden_path_found:hidden_path_1")


def test_a_failed_forage_never_discovers(monkeypatch):
    state = new_game_state(seed=42)
    _plant_path(state, dc=2)
    home = foraging.path_home(state, "hidden_path_1")
    state.location_id = home
    _force_check(monkeypatch, total=19, degree="failure")

    assert foraging.forage(state)["discovery"] is None


def test_discovery_happens_once(monkeypatch):
    state = new_game_state(seed=42)
    _plant_path(state, dc=2)
    home = foraging.path_home(state, "hidden_path_1")
    state.location_id = home
    _force_check(monkeypatch, total=20, degree="success")

    first = foraging.forage(state)
    state.stats.stamina = 100
    second = foraging.forage(state)

    assert first["discovery"] is not None
    assert second["discovery"] is None, "the same path was discovered twice"


# ---------------------------------------------------------------------------
# what a discovered path DOES
# ---------------------------------------------------------------------------


def _discovered(state: GameState) -> str:
    """Mark the planted path found the way the game does, returning its home."""
    from engine.game import effects as effects_module

    effects_module.apply_effect(
        state,
        {"type": "flag", "flag": "hidden_path_found:hidden_path_1", "value": True},
    )
    return foraging.path_home(state, "hidden_path_1")


def test_a_discovered_path_opens_a_leg_the_graph_does_not_have():
    state = new_game_state(seed=42)
    _plant_path(state, leads_to="old_barrows")
    home = _discovered(state)
    # Choose the interesting case: a home with no direct road to the barrows.
    from engine.game.locations import get_edge

    if get_edge(home, "old_barrows") is not None:
        pytest.skip(f"seed dealt the path to {home}, which already has a road")

    state.location_id = home
    state.stats.stamina = 100
    move = GameEngine(state).move_to("old_barrows")

    assert move.success is True
    assert move.hours == foraging.SHORTCUT_HOURS


def test_a_discovered_path_shortens_an_existing_road_both_ways():
    state = new_game_state(seed=42)
    _plant_path(state, leads_to="old_barrows")
    home = _discovered(state)

    assert foraging.shortcut_hours(state, home, "old_barrows") == foraging.SHORTCUT_HOURS
    assert foraging.shortcut_hours(state, "old_barrows", home) == foraging.SHORTCUT_HOURS
    assert foraging.shortcut_hours(state, home, "edgewood_square") is None


def test_the_shortcut_survives_a_save_round_trip():
    state = new_game_state(seed=42)
    _plant_path(state)
    home = _discovered(state)

    loaded = GameState.from_dict(state.to_save_dict())

    assert foraging.path_discovered(loaded, "hidden_path_1")
    assert foraging.shortcut_hours(loaded, home, "old_barrows") == foraging.SHORTCUT_HOURS


def test_the_snapshot_names_found_paths_and_only_found_paths():
    state = new_game_state(seed=42)
    _plant_path(state)

    assert foraging.snapshot(state)["hidden_paths"] == []
    _discovered(state)
    rows = foraging.snapshot(state)["hidden_paths"]
    assert [r["id"] for r in rows] == ["hidden_path_1"]
    assert rows[0]["leads_to"] == "old_barrows"
