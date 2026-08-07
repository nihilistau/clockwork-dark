"""Faction reputation tests."""

from __future__ import annotations

import pytest

from engine.game import reputation
from engine.game.state import GameState

CANON_FACTIONS = (
    reputation.EDGEWOOD,
    reputation.MERCHANTS,
    reputation.MILITIA,
    reputation.TINKERS,
    reputation.UNNAMED_SAINTS,
)


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
    assert reputation.get(state, reputation.EDGEWOOD) == 0
    assert reputation.standing(state, reputation.EDGEWOOD) == "neutral"


def test_adjust_writes_state_reputations(state: GameState):
    assert reputation.adjust(state, reputation.EDGEWOOD, 12, reason="bakery help") == 12
    assert state.reputations[reputation.EDGEWOOD] == 12
    assert reputation.adjust(state, reputation.EDGEWOOD, -5) == 7


def test_adjust_clamps_at_both_ends(state: GameState):
    assert reputation.adjust(state, reputation.MILITIA, 5_000) == 100
    assert reputation.adjust(state, reputation.MILITIA, -5_000) == -100
    assert reputation.adjust(state, reputation.MILITIA, -1) == -100


def test_adjust_ignores_a_non_numeric_delta(state: GameState):
    reputation.adjust(state, reputation.MILITIA, 10)
    assert reputation.adjust(state, reputation.MILITIA, "lots") == 10  # type: ignore[arg-type]


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
    state.reputations[reputation.EDGEWOOD] = score
    assert reputation.standing(state, reputation.EDGEWOOD) == expected
    assert reputation.standing_id(state, reputation.EDGEWOOD) == expected


def test_faction_can_override_its_bands(state: GameState):
    """The shrine has no polite middle; its labels are its own."""
    state.reputations[reputation.UNNAMED_SAINTS] = 0
    assert reputation.standing_id(state, reputation.UNNAMED_SAINTS) == "neutral"
    assert reputation.standing(state, reputation.UNNAMED_SAINTS) == "counted"


def test_price_multiplier_formula(state: GameState):
    assert reputation.price_multiplier(state, reputation.EDGEWOOD) == pytest.approx(1.15)
    state.reputations[reputation.EDGEWOOD] = 40
    assert reputation.price_multiplier(state, reputation.EDGEWOOD) == pytest.approx(1.05)


@pytest.mark.parametrize("score", [-100, -40, 0, 25, 60, 100])
def test_price_multiplier_stays_in_bounds(state: GameState, score: int):
    state.reputations[reputation.EDGEWOOD] = score
    price = reputation.price_multiplier(state, reputation.EDGEWOOD)
    assert 0.85 <= price <= 1.25


def test_price_multiplier_is_monotonic(state: GameState):
    prices = []
    for score in range(-100, 101, 10):
        state.reputations[reputation.EDGEWOOD] = score
        prices.append(reputation.price_multiplier(state, reputation.EDGEWOOD))
    assert prices == sorted(prices, reverse=True)


def test_gate_allows_numeric_minimum(state: GameState):
    reputation.adjust(state, reputation.MILITIA, 30)
    assert reputation.gate_allows(state, reputation.MILITIA, 25) is True
    assert reputation.gate_allows(state, reputation.MILITIA, 31) is False


def test_gate_allows_band_minimum(state: GameState):
    assert reputation.gate_allows(state, reputation.MILITIA, "friendly") is False
    reputation.adjust(state, reputation.MILITIA, 65)
    assert reputation.gate_allows(state, reputation.MILITIA, "friendly") is True
    assert reputation.gate_allows(state, reputation.MILITIA, "trusted") is True
    reputation.adjust(state, reputation.MILITIA, -120)
    assert reputation.gate_allows(state, reputation.MILITIA, "neutral") is False


def test_gate_rejects_an_unknown_band(state: GameState):
    assert reputation.gate_allows(state, reputation.MILITIA, "beloved") is False


def test_reputation_survives_a_save_round_trip(state: GameState):
    reputation.adjust(state, reputation.TINKERS, -30, reason="haggled badly")
    restored = GameState.from_dict(state.to_save_dict())
    assert restored.reputations[reputation.TINKERS] == -30
    assert reputation.standing_id(restored, reputation.TINKERS) == "wary"


def test_snapshot_covers_every_faction(state: GameState):
    snap = reputation.snapshot(state)
    assert set(snap) == set(reputation.faction_ids())
    assert snap[reputation.EDGEWOOD]["standing"] == "neutral"


def test_missing_factions_file_degrades_quietly(monkeypatch, tmp_path):
    monkeypatch.setattr(reputation, "_factions_path", lambda: tmp_path / "absent.yaml")
    reputation.reset_faction_cache()
    try:
        state = GameState()
        assert reputation.adjust(state, reputation.EDGEWOOD, 500) == 100
        assert reputation.standing(state, reputation.EDGEWOOD) == "unknown"
        assert reputation.price_multiplier(state, reputation.EDGEWOOD) == pytest.approx(0.9)
    finally:
        reputation.reset_faction_cache()
