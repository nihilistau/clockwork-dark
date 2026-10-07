"""
The pace slider holds the value the game ships with (v0.21.0 T13 fix round 1).

``world.evil_base_rate_per_day`` went from 0.006 to 0.028 in 080831c, measured
with ``scripts/simulate.py``, and the Settings row kept its old range (max
0.02), its marks and a hint written for 0.006. The slider's thumb sat pinned
at its end while the number beside it said 0.028, and touching it wrote at
most 0.02. The balance constant is not this test's to change (AGENTS.md rule
10); the slider is.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from engine.api.settings import SETTINGS_BY_KEY, _fit_range

REPO = Path(__file__).resolve().parents[1]
KEY = "world.evil_base_rate_per_day"


def _shipped_default() -> float:
    with (REPO / "config" / "default.yaml").open(encoding="utf-8") as fh:
        return float(yaml.safe_load(fh)["world"]["evil_base_rate_per_day"])


def test_the_pace_slider_holds_the_shipped_default() -> None:
    spec = SETTINGS_BY_KEY[KEY]
    default = _shipped_default()
    assert spec["min"] <= default <= spec["max"], (default, spec["min"], spec["max"])


def test_every_numeric_row_holds_its_shipped_default() -> None:
    # The same fault on any other slider: config/default.yaml is the engine's
    # own default for every row the panel offers.
    with (REPO / "config" / "default.yaml").open(encoding="utf-8") as fh:
        config = yaml.safe_load(fh)
    for key, spec in SETTINGS_BY_KEY.items():
        if spec["type"] not in ("int", "float"):
            continue
        node = config
        for part in key.split("."):
            node = node.get(part) if isinstance(node, dict) else None
        if node is None:
            continue
        assert spec["min"] <= node <= spec["max"], (key, node, spec["min"], spec["max"])


def test_the_pace_marks_sit_on_the_scale_and_name_the_measured_rates() -> None:
    spec = SETTINGS_BY_KEY[KEY]
    for at in spec["marks"]:
        assert spec["min"] <= float(at) <= spec["max"], at
    # The shipped default is one of the measured rates, so it is marked.
    assert _shipped_default() in {float(at) for at in spec["marks"]}
    # The hint claims only the sweep config/default.yaml records.
    assert "day 130" not in spec["hint"] and "day 40" not in spec["hint"]


def test_a_configured_value_outside_the_range_widens_the_view() -> None:
    spec = SETTINGS_BY_KEY[KEY]
    high = _fit_range(dict(spec), 0.08)
    assert (high["min"], high["max"], high["value"]) == (spec["min"], 0.08, 0.08)
    low = _fit_range(dict(spec), 0.0)
    assert (low["min"], low["max"]) == (0.0, spec["max"])
    inside = _fit_range(dict(spec), 0.028)
    assert (inside["min"], inside["max"]) == (spec["min"], spec["max"])
    # The declared range itself is never changed by a view.
    assert SETTINGS_BY_KEY[KEY]["max"] == spec["max"]
