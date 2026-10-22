from __future__ import annotations

from pathlib import Path

import pytest

from tests.social_fixtures import receipts_active  # noqa: F401

PROBE = Path(__file__).parent / "fixtures" / "social" / "decks"


@pytest.fixture
def probe_decks(monkeypatch, receipts_active):
    """The deck directory pointed at the test-only deck, for this test only. The deck module's own
    directory lookup is patched; the config and `config/local.yaml` are never touched. (`set_overlay`
    would REPLACE the active story's overlay, `paths.social` included, so it is not used.)"""
    from engine.content import deck

    monkeypatch.setattr(deck, "_decks_dir", lambda: PROBE)
    yield


def test_no_deck_is_dealt_over_a_social_scene(probe_decks) -> None:
    """§10.1 (N4): an at-home scene in the kitchen with the boiler flag set deals nothing; the deck deals on
    the first turn after the scene ends."""
    from engine.content import director
    from engine.game import procgen
    from engine.game.effects import apply_effect

    state = procgen.new_game_state(player_name="Sam", seed=4242)
    state.location_id = "apt_kitchen"
    apply_effect(state, {"type": "flag", "flag": "life_boiler"})
    state.social["scene"] = {"pid": "p0001", "location": "apt_kitchen"}
    assert director.ensure_scene(state) == []
    state.social["scene"] = {}
    receipts = director.ensure_scene(state)
    assert receipts and receipts[0]["args"]["deck_id"] == "test_boiler_probe"
