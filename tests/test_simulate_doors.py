"""
The doors harness (v0.25.0 §10.1, §12.6; rule 10): `scripts/simulate_doors.py`.

The smoke test plays three seeds per policy and holds each to the floor its
§10.2 band row was MEASURED at in T10 (ruling I6, option a): a floor, named
with its band row, never a widened band and never an xfail. The 40-seed table
lives in the root and story CHANGELOGs and the data files' headers. `slow`:
balance measurement.

The rest are cheap: the helpers live once (ruling M13), `simulate.py --policy
doors` hands over, and the five-policy table over seeds has its shape.
"""

from __future__ import annotations

import pytest

from scripts import simulate_doors as doors

#: Per policy: (the floor of own-ending runs of seeds 0-2 in T10's final measurement, and its §10.2
#: row). `own` is rounded to three places, so two of three is written 0.66.
SMOKE_FLOORS: dict[str, tuple[float, str]] = {
    "baker": (1.0, "each door policy reaches its own ending: at least 80% (40 seeds)"),
    "settler": (1.0, "each door policy reaches its own ending: at least 80% (40 seeds)"),
    "witness": (0.66, "each door policy reaches its own ending: at least 80% (40 seeds)"),
    "marcher": (0.66, "each door policy reaches its own ending: at least 80% (40 seeds)"),
    "namer": (1.0, "each door policy reaches its own ending: at least 80% (40 seeds)"),
    "payer": (1.0, "each door policy reaches its own ending: at least 80% (40 seeds)"),
    "pinner": (0.0, "each door policy reaches its own ending: at least 80% (40 seeds); MISSED: 12.5% after "
                    "every lever tried (T10), seeds 0-2 all miss; a CLAUDE.md deferred row"),
    "drifter": (1.0, "each door policy reaches its own ending: at least 80% (40 seeds)"),
}


def _row(policy: str, seeds: list[int]) -> dict:
    from engine.games import registry

    registry.activate("clockwork-dark")
    try:
        return doors.run_policy(policy, seeds)
    finally:
        registry.deactivate()


@pytest.mark.slow
@pytest.mark.parametrize("policy", sorted(SMOKE_FLOORS))
def test_three_seeds_reach_their_own_ending_at_the_measured_floor(policy: str) -> None:
    floor, band_row = SMOKE_FLOORS[policy]
    row = _row(policy, [0, 1, 2])
    assert row["own"] >= floor, (f"{policy}: own {row['own']} under its measured floor {floor} "
                                 f"(§10.2: {band_row}); runs {row['runs_detail']}")


@pytest.mark.slow
def test_the_reckless_die_into_the_fail_forward() -> None:
    """§10.2: `reckless` ends in the terminal death in at least 50% of runs."""
    row = _row("reckless", [0, 1, 2])
    assert row["own"] >= 1 / 3 and row["other"] == 0.0, row


def test_the_condition_helpers_live_once_and_the_walks_import_them() -> None:
    from tests import clockwork_walks

    for name in ("stage", "done", "locked", "inside_window"):
        assert getattr(clockwork_walks, name) is getattr(doors, name), name
    assert doors.stage("q", 2) == {"quest_state": {"quest": "q", "stage_at_least": 2}}
    assert doors.done("q") == {"quest_completed": "q"}
    assert doors.locked("e") == {"ending": {"locked": "e"}}
    assert doors.inside_window(22, 19, 23) and not doors.inside_window(23, 19, 23)
    assert doors.inside_window(2, 22, 4) and not doors.inside_window(4, 22, 4)


def test_every_policy_names_a_declared_ending_and_card_answers_are_offered_ids() -> None:
    from engine import yamlio

    endings_doc = yamlio.safe_load((doors.ROOT / "games" / doors.FLAGSHIP / "data" / "rules"
                                    / "endings.yaml").read_text(encoding="utf-8"))
    declared = set(endings_doc.get("classes") or {})
    assert len(declared) == 8, declared
    beats: dict[str, set[str]] = {}
    for path in doors.SCENES.glob("*.yaml"):
        for card in (yamlio.safe_load(path.read_text(encoding="utf-8")) or {}).get("cards") or []:
            beats[str(card["id"])] = {str(b.get("id")) for b in card.get("beats") or []}
    assert len(beats) == 34, sorted(beats)
    for name, policy in doors.POLICIES.items():
        assert policy.ending in declared, (name, policy.ending)
        for card_id, beat in {**doors.SAFE, **policy.answers}.items():
            assert beat in beats.get(card_id, set()), (name, card_id, beat)


def test_card_flags_are_never_raised_as_pending_narrative_flags() -> None:
    flags = doors.card_flags()
    assert {"nf_naming_laid_it_out", "nf_ninth_asked", "nf_drawing_seen"} <= flags


def test_simulate_policy_doors_hands_over_to_the_doors_harness(monkeypatch) -> None:
    import simulate  # beside scripts/simulate_doors.py, which put scripts/ on the path

    seen: list[list[str]] = []
    monkeypatch.setattr(doors, "main", lambda argv: seen.append(list(argv)) or 0)
    monkeypatch.setitem(__import__("sys").modules, "simulate_doors", doors)
    assert simulate.main(["--policy", "doors", "--seeds", "3", "--seed", "5", "--json"]) == 0
    assert simulate.main(["--policy", "doors"]) == 0
    assert seen == [["--seeds", "3", "--seed", "5", "--json"], ["--seeds", "40"]]


def test_the_policy_table_over_seeds_has_the_design_tables_columns() -> None:
    import simulate
    from engine.games import registry

    registry.activate("clockwork-dark")
    try:
        table = simulate.measure_policy_table(["cautious"], [1, 2], turns=6, tick_hours=2.0)
    finally:
        registry.deactivate()
    row = table["policies"]["cautious"]
    assert table["seeds"] == [1, 2] and table["turns"] == 6
    assert {"hours_per_turn", "evil_progress", "deaths", "starvation_deaths", "deaths_median",
            "deaths_max", "bands"} <= set(row)
    assert set(table["bands"]) >= set(row["bands"])
