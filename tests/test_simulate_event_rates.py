"""
`simulate.py --event-rates` (v0.25.0 T1, spec §6.1 "Rates", rule 10): starts per
eligible in-game day of the caravan, tinker and press, per policy.

A day d is ELIGIBLE for an event when no instance of it that started BEFORE d
is still active on d, and the event's own gate holds on d (the caravan from its
`min_day`, the press while awareness was at its threshold at d's first sample).
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _simulate():
    spec = importlib.util.spec_from_file_location("simulate_for_rates", ROOT / "scripts" / "simulate.py")
    module = importlib.util.module_from_spec(spec)
    # Registered first: a dataclass under `from __future__ import annotations`
    # looks its module up in sys.modules while the class is built.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_event_rates_counts_starts_per_eligible_day() -> None:
    sim = _simulate()
    instances = {("caravan_arrival", 6, 8), ("caravan_arrival", 10, 12), ("militia_press", 7, 8)}
    awareness = {d: (10.0 if d < 7 else 25.0) for d in range(1, 13)}
    gates = {
        "caravan_arrival": lambda d, aw: d >= 5 and d in aw,
        "tinker_camp": lambda d, aw: d in aw,
        "militia_press": lambda d, aw: d in aw and aw[d] >= 20,
    }
    rates = sim.event_rates(instances, awareness, first_day=1, last_day=12, gates=gates)
    # Caravan: days 5..12 = 8 days, day 7 (carried from 6) and day 11 (carried from 10) not eligible.
    assert rates["caravan_arrival"] == {"starts": 2, "eligible_days": 6, "per_day": pytest.approx(2 / 6)}
    # Press: eligible from day 7 (awareness 25) to 12 = 6 days, one start.
    assert rates["militia_press"]["starts"] == 1 and rates["militia_press"]["eligible_days"] == 6
    assert rates["tinker_camp"] == {"starts": 0, "eligible_days": 12, "per_day": 0.0}


def test_the_mean_leaves_out_a_policy_that_had_no_eligible_day() -> None:
    """A policy that never reached the press's awareness measured no press rate, not 0."""
    sim = _simulate()
    rows = {
        "baker": {"caravan_arrival": {"starts": 3, "eligible_days": 4},
                  "tinker_camp": {"starts": 1, "eligible_days": 300},
                  "militia_press": {"starts": 0, "eligible_days": 0}},
        "hero": {"caravan_arrival": {"starts": 1, "eligible_days": 4},
                 "tinker_camp": {"starts": 2, "eligible_days": 300},
                 "militia_press": {"starts": 1, "eligible_days": 5}},
    }
    assert sim.mean_rates(rows) == {"caravan_arrival": 0.5, "tinker_camp": 0.005, "militia_press": 0.2}


def test_the_flag_reports_every_policy_and_the_mean(capsys) -> None:
    from engine.games import registry

    sim = _simulate()
    registry.activate("clockwork-dark")
    try:
        assert sim.main(["--event-rates", "--policy", "cautious", "--turns", "6", "--seeds", "1", "--json"]) == 0
    finally:
        registry.deactivate()
    report = json.loads(capsys.readouterr().out)
    assert set(report["policies"]) == {"cautious"}
    assert set(report["mean"]) == {"caravan_arrival", "tinker_camp", "militia_press"}
    assert "first_caravan_day" in report["policies"]["cautious"]


def test_the_flag_is_the_flagships_alone() -> None:
    sim = _simulate()
    with pytest.raises(SystemExit):
        sim.main(["--event-rates", "--game", "hue-and-cry"])


def test_an_authored_zero_gate_stays_zero(monkeypatch) -> None:
    """`rate_gates`: `min_day: 0` and `min_awareness: 0` are gates of 0, not the defaults."""
    sim = _simulate()
    monkeypatch.setattr(sim, "load_schedules", lambda: {"events": {
        "caravan_arrival": {"probability_per_day": 0.5, "min_day": 0},
        "militia_press": {"probability_per_day": 0.5, "when": {"min_awareness": 0}},
    }})
    gates = sim.rate_gates()
    assert gates["caravan_arrival"](1, {1: 0.0})
    assert gates["militia_press"](1, {1: 0.0})
    monkeypatch.setattr(sim, "load_schedules", lambda: {
        "caravan_arrival": {"min_day": 0}, "militia_press": {"min_awareness": 0}})
    gates = sim.rate_gates()
    assert gates["caravan_arrival"](1, {1: 0.0}) and gates["militia_press"](1, {1: 0.0})

