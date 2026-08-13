"""Faction reputation tests."""

from __future__ import annotations

import pytest

from engine.game import reputation
from engine.game.state import GameState

# The flagship's five, as the strings its factions.yaml declares. These were
# module constants on engine.game.reputation until v0.2.2; faction ids belong
# to a story's content, so the engine no longer exports any story's list and a
# test about the flagship names the flagship's ids itself.
CANON_FACTIONS = (
    "edgewood",
    "merchants",
    "militia",
    "tinkers",
    "unnamed_saints",
)
EDGEWOOD, MILITIA = "edgewood", "militia"


@pytest.fixture
def state() -> GameState:
    return GameState()


def test_all_canon_factions_are_configured():
    configured = set(reputation.faction_ids())
    assert set(CANON_FACTIONS) <= configured


@pytest.mark.parametrize("faction", CANON_FACTIONS)
def test_every_faction_has_a_name_and_description(faction: str):
    cfg = reputation._faction_cfg(faction)
    assert cfg.get("name")
    assert str(cfg.get("description", "")).strip()


def test_reputations_starts_empty_and_reads_neutral(state: GameState):
    """The field shipped in PR1 with no writer; unset must not mean hostile."""
    assert state.reputations == {}
    assert reputation.get(state, EDGEWOOD) == 0
    assert reputation.standing(state, EDGEWOOD) == "neutral"


def test_adjust_writes_state_reputations(state: GameState):
    assert reputation.adjust(state, EDGEWOOD, 12, reason="bakery help") == 12
    assert state.reputations[EDGEWOOD] == 12
    assert reputation.adjust(state, EDGEWOOD, -5) == 7


def test_adjust_clamps_at_both_ends(state: GameState):
    assert reputation.adjust(state, MILITIA, 5_000) == 100
    assert reputation.adjust(state, MILITIA, -5_000) == -100
    assert reputation.adjust(state, MILITIA, -1) == -100


def test_adjust_ignores_a_non_numeric_delta(state: GameState):
    reputation.adjust(state, MILITIA, 10)
    assert reputation.adjust(state, MILITIA, "lots") == 10  # type: ignore[arg-type]


def test_unknown_faction_is_still_recorded(state: GameState):
    """A silently dropped quest reward is worse than a loud unknown key."""
    assert reputation.adjust(state, "brigands", 20) == 20
    assert state.reputations["brigands"] == 20


@pytest.mark.parametrize(
    "score,expected",
    [
        (-100, "hostile"),
        (-40, "hostile"),
        (-39, "wary"),
        (-15, "wary"),
        (-14, "neutral"),
        (0, "neutral"),
        (24, "neutral"),
        (25, "friendly"),
        (59, "friendly"),
        (60, "trusted"),
        (100, "trusted"),
    ],
)
def test_standing_thresholds(state: GameState, score: int, expected: str):
    state.reputations[EDGEWOOD] = score
    assert reputation.standing(state, EDGEWOOD) == expected
    assert reputation.standing_id(state, EDGEWOOD) == expected


def test_faction_can_override_its_bands(state: GameState):
    """The shrine has no polite middle; its labels are its own."""
    state.reputations["unnamed_saints"] = 0
    assert reputation.standing_id(state, "unnamed_saints") == "neutral"
    assert reputation.standing(state, "unnamed_saints") == "counted"


def test_price_multiplier_formula(state: GameState):
    assert reputation.price_multiplier(state, EDGEWOOD) == pytest.approx(1.15)
    state.reputations[EDGEWOOD] = 40
    assert reputation.price_multiplier(state, EDGEWOOD) == pytest.approx(1.05)


@pytest.mark.parametrize("score", [-100, -40, 0, 25, 60, 100])
def test_price_multiplier_stays_in_bounds(state: GameState, score: int):
    state.reputations[EDGEWOOD] = score
    price = reputation.price_multiplier(state, EDGEWOOD)
    assert 0.85 <= price <= 1.25


def test_price_multiplier_is_monotonic(state: GameState):
    prices = []
    for score in range(-100, 101, 10):
        state.reputations[EDGEWOOD] = score
        prices.append(reputation.price_multiplier(state, EDGEWOOD))
    assert prices == sorted(prices, reverse=True)


def test_gate_allows_numeric_minimum(state: GameState):
    reputation.adjust(state, MILITIA, 30)
    assert reputation.gate_allows(state, MILITIA, 25) is True
    assert reputation.gate_allows(state, MILITIA, 31) is False


def test_gate_allows_band_minimum(state: GameState):
    assert reputation.gate_allows(state, MILITIA, "friendly") is False
    reputation.adjust(state, MILITIA, 65)
    assert reputation.gate_allows(state, MILITIA, "friendly") is True
    assert reputation.gate_allows(state, MILITIA, "trusted") is True
    reputation.adjust(state, MILITIA, -120)
    assert reputation.gate_allows(state, MILITIA, "neutral") is False


def test_gate_rejects_an_unknown_band(state: GameState):
    assert reputation.gate_allows(state, MILITIA, "beloved") is False


def test_reputation_survives_a_save_round_trip(state: GameState):
    reputation.adjust(state, "tinkers", -30, reason="haggled badly")
    restored = GameState.from_dict(state.to_save_dict())
    assert restored.reputations["tinkers"] == -30
    assert reputation.standing_id(restored, "tinkers") == "wary"


def test_snapshot_covers_every_faction(state: GameState):
    snap = reputation.snapshot(state)
    assert set(snap) == set(reputation.faction_ids())
    assert snap[EDGEWOOD]["standing"] == "neutral"


def test_missing_factions_file_degrades_quietly(monkeypatch, tmp_path):
    monkeypatch.setattr(reputation, "_factions_path", lambda: tmp_path / "absent.yaml")
    reputation.reset_faction_cache()
    try:
        state = GameState()
        assert reputation.adjust(state, EDGEWOOD, 500) == 100
        assert reputation.standing(state, EDGEWOOD) == "unknown"
        assert reputation.price_multiplier(state, EDGEWOOD) == pytest.approx(0.9)
    finally:
        reputation.reset_faction_cache()
