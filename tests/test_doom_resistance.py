"""
R-06: engagement buys time.

The doom clock used to cancel itself: the location multiplier and the inaction
bonus were the same size and opposite in sign, so a baker and a road-walker
ended the world within 13% of each other per in-game day. Two mechanisms broke
the symmetry -- a widened per-location ``evil_multiplier`` band (flagship data)
and earned ``doom_resistance`` (engine) -- and these tests hold the engine
half: the effect kind's bounds and receipt, the engagement factor's floor,
strict monotonicity of ``evil_progress``, and decay flowing only through the
clock.

The full five-policy divergence (baker >= 2x hero per in-game day at 200 turns,
seed 42) is measured by ``scripts/simulate.py`` and recorded in
docs/DESIGN_REVIEW.md R-06; a whole simulate run is too slow for the suite, so
what is asserted here is each gear, not the assembled machine.
"""

from __future__ import annotations

import yaml
from pathlib import Path

import pytest

from engine.config import reset_config
from engine.game import evil_ticker as evil_ticker_module
from engine.game.clock import advance_time
from engine.game.effects import apply_effect
from engine.game.evil_ticker import ENGAGEMENT_FACTOR_FLOOR, EvilTicker
from engine.game.state import GameState

_ROOT = Path(__file__).resolve().parents[1]
_FLAGSHIP_QUESTS = _ROOT / "games" / "clockwork-dark" / "data" / "quests"


# ---------------------------------------------------------------------------
# The effect kind -- the ONLY writer besides decay
# ---------------------------------------------------------------------------


def test_doom_resistance_effect_applies_and_receipts() -> None:
    state = GameState()
    receipt = apply_effect(state, {"type": "doom_resistance", "delta": 12})
    assert state.doom_resistance == 12.0
    assert receipt["ok"] is True
    assert receipt["type"] == "doom_resistance"
    assert receipt["applied"] == 12.0
    assert receipt["before"] == 0.0
    assert receipt["after"] == 12.0
    # Hidden like awareness: the player feels the clock slow, never sees the
    # number in narration.
    assert receipt["hidden"] is True


def test_doom_resistance_is_bounded_0_to_100() -> None:
    state = GameState()
    apply_effect(state, {"type": "doom_resistance", "delta": 250})
    assert state.doom_resistance == 100.0
    receipt = apply_effect(state, {"type": "doom_resistance", "delta": -999})
    assert state.doom_resistance == 0.0
    assert receipt["after"] == 0.0


# ---------------------------------------------------------------------------
# The engagement factor
# ---------------------------------------------------------------------------


def test_engagement_factor_has_a_hard_floor(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Whatever a story sets ``evil_engagement_slowdown_max`` to, engagement buys
    time -- it never stops the clock. A slowdown of 1.0 at full resistance
    would multiply the rate by zero without the floor.
    """
    monkeypatch.setattr(
        EvilTicker, "engagement_slowdown_max", staticmethod(lambda: 1.0)
    )
    state = GameState()
    state.doom_resistance = 100.0
    state.plot_involvement = 100.0  # inaction bonus 1.0, so raw factor is 0.0
    assert EvilTicker.engagement_factor(state) == ENGAGEMENT_FACTOR_FLOOR


def test_engagement_factor_disengaged_equals_the_old_inaction_bonus() -> None:
    """A player with no resistance keeps the pre-R-06 behaviour exactly."""
    state = GameState()
    state.doom_resistance = 0.0
    state.plot_involvement = 0.0
    assert EvilTicker.engagement_factor(state) == pytest.approx(1.35)


def test_resistance_slows_the_tick_but_never_reverses_it() -> None:
    reset_config()
    engaged = GameState(location_id="edgewood_square")
    detached = GameState(location_id="edgewood_square")
    engaged.doom_resistance = 100.0
    engaged.plot_involvement = 100.0

    EvilTicker.advance(engaged, days_elapsed=5.0)
    EvilTicker.advance(detached, days_elapsed=5.0)

    assert 0.0 < engaged.evil_progress < detached.evil_progress


def test_evil_progress_never_decreases_at_any_resistance() -> None:
    reset_config()
    state = GameState(location_id="edgewood_shrine")
    state.doom_resistance = 100.0
    state.plot_involvement = 100.0
    previous = state.evil_progress
    for _ in range(50):
        EvilTicker.advance(state, days_elapsed=0.5)
        assert state.evil_progress >= previous
        previous = state.evil_progress
        # Keep it topped up so the whole walk happens at maximum slowdown.
        state.doom_resistance = 100.0


# ---------------------------------------------------------------------------
# Decay -- spent through the clock and nowhere else
# ---------------------------------------------------------------------------


def test_resistance_decays_with_the_world_clock() -> None:
    reset_config()
    state = GameState(location_id="forest_clearing")
    state.doom_resistance = 50.0
    advance_time(state, 24.0)
    expected = 50.0 - EvilTicker.resistance_decay_per_day()
    assert state.doom_resistance == pytest.approx(expected)


def test_resistance_decay_is_proportional_and_floored_at_zero() -> None:
    reset_config()
    state = GameState(location_id="forest_clearing")
    state.doom_resistance = 1.0
    EvilTicker.advance(state, days_elapsed=10.0)
    assert state.doom_resistance == 0.0

    state.doom_resistance = 50.0
    EvilTicker.advance(state, days_elapsed=0.0)
    assert state.doom_resistance == 50.0  # no time, no decay


def test_no_doom_clock_means_no_decay(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    A story with no doom clock ticks nothing -- including the decay. The
    resistance a save carries must not silently drain in a story that can
    never grant it back.
    """
    monkeypatch.setattr(evil_ticker_module, "_DOOM_DECLARED", False)
    state = GameState(location_id="forest_clearing")
    state.doom_resistance = 50.0
    before_progress = state.evil_progress
    EvilTicker.advance(state, days_elapsed=3.0)
    assert state.doom_resistance == 50.0
    assert state.evil_progress == before_progress


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


def test_doom_resistance_round_trips_through_a_save() -> None:
    state = GameState()
    state.doom_resistance = 37.5
    data = state.to_save_dict()
    assert data["doom_resistance"] == 37.5
    assert GameState.from_dict(data).doom_resistance == 37.5


def test_old_saves_load_with_neutral_zero() -> None:
    data = GameState().to_save_dict()
    data.pop("doom_resistance")
    assert GameState.from_dict(data).doom_resistance == 0.0


# ---------------------------------------------------------------------------
# The bounder knows the kind
# ---------------------------------------------------------------------------


def test_challenge_specs_may_grant_it_but_clamped() -> None:
    from engine.challenges.spec import clamp_outcome

    adjustments: list[str] = []
    outcome = clamp_outcome(
        {"text": "", "effects": [{"type": "doom_resistance", "delta": 40}]},
        adjustments,
    )
    assert outcome["effects"][0]["delta"] == 15
    assert any("doom_resistance" in line for line in adjustments)


def test_the_new_settings_are_story_tunable() -> None:
    from engine.games.manifest import SETTING_ALLOWLIST

    assert "world.evil_engagement_slowdown_max" in SETTING_ALLOWLIST
    assert "world.doom_resistance_decay_per_day" in SETTING_ALLOWLIST


# ---------------------------------------------------------------------------
# The flagship actually grants it (mechanism 2's data half)
# ---------------------------------------------------------------------------


def _completion_grant(path: Path) -> float:
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    for effect in ((doc.get("on_complete") or {}).get("effects") or []):
        if isinstance(effect, dict) and effect.get("type") == "doom_resistance":
            return float(effect.get("delta", 0))
    return 0.0


@pytest.mark.skipif(not _FLAGSHIP_QUESTS.is_dir(), reason="flagship content absent")
def test_flagship_pushback_arcs_grant_scaled_reprieve() -> None:
    """
    Every whisper/march/convergence quest pays doom_resistance on completion,
    and deeper arcs pay more -- while the bakery apprenticeship pays none,
    because the baker's clock staying fast is the whole point of R-06.
    """
    grants = {
        arc: [_completion_grant(p) for p in sorted((_FLAGSHIP_QUESTS / arc).glob("*.yaml"))]
        for arc in ("whisper", "march", "convergence")
    }
    for arc, values in grants.items():
        assert values and all(v > 0 for v in values), f"{arc} quest without a grant"
    assert max(grants["whisper"]) < min(grants["march"])
    assert max(grants["march"]) < min(grants["convergence"])
    assert (
        _completion_grant(_FLAGSHIP_QUESTS / "quiet_life" / "bakery_apprentice.yaml")
        == 0.0
    )
