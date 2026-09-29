"""
``scripts/simulate.py --game hue-and-cry``: the thief policy (v0.18.0).

Three promises, each pinned here:

    THE ROUTE    ``--game hue-and-cry`` runs HUE & CRY's own harnesses
                 (scripts/simulate_endings.py's policies, and
                 scripts/simulate_labour.py's careful pickpocket for the days a
                 thief keeps on its own coin) instead of the refusal it got
                 before v0.18. ``--policy thief`` names one of those policies;
                 no policy is written twice.
    REPLAY       The same arguments print the same JSON, byte for byte (rule 4).
    NO DRIFT     Every path that ran before v0.18 -- no ``--game``, the
                 flagship by name, a deck story -- prints exactly what it
                 printed at the commit before the route landed. The golden
                 files under ``tests/fixtures/simulate/`` were captured there,
                 from the CLI's own stdout, by running this file as a script
                 (``python tests/test_simulate_thief.py --write-golden``). Re-run
                 that ONLY for a change that is meant to move those numbers, and
                 say so in the CHANGELOG.

    COLLISIONS   (T2) Where the city's agendas met the player
                 (``simulate_endings.COLLISIONS``): the definitions on a
                 hand-built record, and the 40-seed headline rates pinned
                 loosely over the first ``COLLISION_SEEDS`` seeds, played once
                 for the module.

Every run here goes through the CLI in a subprocess where the claim is about
the CLI's bytes, and in-process where it is about what the run touched (the
save store). Budgets are tiny for the route; the collisions fixture is the
one measurement (about a minute and a half).

Version: v0.2.0 [2026-09-28] -- T2: collisions; unread flags refused
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_SIMULATE = _ROOT / "scripts" / "simulate.py"
GOLDEN = Path(__file__).resolve().parent / "fixtures" / "simulate"

#: golden file -> the argv that printed it. Small on purpose: a handful of
#: turns per flagship policy, two Garden walks.
GOLDEN_RUNS: dict[str, list[str]] = {
    "flagship_all.json": ["--turns", "12", "--seed", "7", "--policy", "all", "--json"],
    "flagship_cautious.txt": ["--turns", "12", "--seed", "7"],
    "garden.json": ["--game", "wicked-garden", "--runs", "2", "--seed", "5", "--json"],
    "garden.txt": ["--game", "wicked-garden", "--runs", "2", "--seed", "5"],
}

#: The flagship by name must print what no ``--game`` prints.
FLAGSHIP_BY_NAME: dict[str, list[str]] = {
    "flagship_all.json": ["--game", "clockwork-dark", *GOLDEN_RUNS["flagship_all.json"]],
    "flagship_cautious.txt": ["--game", "clockwork-dark", *GOLDEN_RUNS["flagship_cautious.txt"]],
}

#: The HUE & CRY run the replay and shape tests make: two seeds, three days.
HUE_ARGV = ["--game", "hue-and-cry", "--policy", "thief", "--runs", "2", "--days", "3",
            "--json"]


def _stdout(argv: list[str]) -> bytes:
    """What ``scripts/simulate.py`` prints to stdout for ``argv`` (stderr is logging)."""
    done = subprocess.run([sys.executable, str(_SIMULATE), *argv], cwd=str(_ROOT),
                          capture_output=True, timeout=600)
    assert done.returncode == 0, done.stderr.decode("utf-8", "replace")[-2000:]
    return done.stdout


def _lf(data: bytes) -> bytes:
    """Every byte, with the platform's line ending read as ``\\n``: Windows'
    stdout writes CRLF, and git's autocrlf may check a golden file out either
    way. Nothing else is forgiven."""
    return data.replace(b"\r\n", b"\n")


# ---------------------------------------------------------------------------
# no drift: the paths that ran before v0.18
# ---------------------------------------------------------------------------


#: What a golden mismatch says: how to re-capture, and what that obliges.
RECAPTURE = ("{name}: simulate.py no longer prints what it printed before v0.18. If "
             "that change is MEANT to move these numbers, re-capture with `python "
             "tests/test_simulate_thief.py --write-golden` and say so in CHANGELOG.md's "
             "[Unreleased]; otherwise the change drifted a path it should not touch.")


@pytest.mark.parametrize("name", sorted(GOLDEN_RUNS))
def test_a_path_that_ran_before_prints_what_it_printed(name: str) -> None:
    assert _lf(_stdout(GOLDEN_RUNS[name])) == _lf((GOLDEN / name).read_bytes()), \
        RECAPTURE.format(name=name)


@pytest.mark.parametrize("name", sorted(FLAGSHIP_BY_NAME))
def test_the_flagship_by_name_prints_what_no_game_prints(name: str) -> None:
    assert _lf(_stdout(FLAGSHIP_BY_NAME[name])) == _lf((GOLDEN / name).read_bytes()), \
        RECAPTURE.format(name=name)


# ---------------------------------------------------------------------------
# the route
# ---------------------------------------------------------------------------


def test_hue_and_cry_runs_the_thief_and_replays_from_its_seed() -> None:
    first = _stdout(HUE_ARGV)
    assert first == _stdout(HUE_ARGV)
    report = json.loads(first)
    assert report["config"]["game"] == "hue-and-cry"
    assert report["config"]["seeds"] == [0, 1]
    assert report["config"]["days"] == 3
    # `thief` is an alias, reported under the policy it names.
    from scripts import simulate_endings

    assert report["config"]["thief"] == simulate_endings.THIEF_POLICY
    assert list(report["policies"]) == [simulate_endings.THIEF_POLICY]


def test_the_report_carries_every_field_the_thief_is_measured_by(capsys) -> None:
    from engine.games import registry
    from scripts import simulate, simulate_endings

    try:
        assert simulate.main(HUE_ARGV) == 0
    finally:
        registry.deactivate()
    report = json.loads(capsys.readouterr().out)
    row = report["policies"][report["config"]["thief"]]
    assert row["seeds"] == 2
    # simulate_endings' own table, untouched ...
    for key in ("endings", "arrests_per_run", "days_served_per_run", "runs_with_a_death"):
        assert key in row, key
    # ... and what the thief is measured by on top of it.
    thief = row["thief"]
    for key in ("worst_band", "jobs_tried_per_run", "jobs_carried_out_per_run",
                "loot_value_per_run", "clues_per_run", "deaths_per_run", "respawns_per_run",
                "end_gold", "end_gold_min"):
        assert key in thief, key
    assert sum(thief["worst_band"].values()) == 2
    # v0.18 T2: where the agendas met the player, over the policies played.
    collisions = report["collisions"]
    assert collisions["runs"] == 2
    assert set(collisions["kinds"]) == set(simulate_endings.COLLISIONS)
    assert list(collisions["policies"]) == [report["config"]["thief"]]
    for kind, row in collisions["kinds"].items():
        for key in ("meaning", "runs", "per_run", "first_day", "earliest_day", "policies"):
            assert key in row, (kind, key)
    living = report["living"]
    assert living["policy"] == "careful" and living["days"] == 3 and living["seeds"] == 2
    assert 0.0 <= living["kept_days"] <= 1.0


def test_every_endings_policy_and_all_are_accepted(capsys) -> None:
    from engine.games import registry
    from scripts import simulate, simulate_endings

    try:
        assert simulate.main(["--game", "hue-and-cry", "--policy", "all", "--runs", "1",
                              "--days", "1", "--json"]) == 0
        declared = set(simulate_endings.declared_endings())   # while the story is active
    finally:
        registry.deactivate()
    report = json.loads(capsys.readouterr().out)
    assert list(report["policies"]) == list(simulate_endings.POLICIES)
    assert set(report["reach"]) == declared and len(declared) == 8


def test_the_thief_is_one_of_the_endings_policies() -> None:
    """``thief`` is an alias, not a second copy: it names a burgling policy
    that simulate_endings.py already plays."""
    from scripts import simulate_endings

    assert simulate_endings.THIEF_POLICY in simulate_endings.POLICIES
    assert simulate_endings.THIEF_POLICY in simulate_endings.BURGLE


def test_a_flagship_policy_is_refused_for_hue_and_cry(capsys) -> None:
    from engine.games import registry
    from scripts import simulate

    try:
        with pytest.raises(SystemExit) as excinfo:
            simulate.main(["--game", "hue-and-cry", "--policy", "baker"])
    finally:
        registry.deactivate()
    assert excinfo.value.code == 2
    assert "simulate_endings" in capsys.readouterr().err


def test_a_hue_policy_is_refused_for_the_flagship(capsys) -> None:
    from scripts import simulate

    with pytest.raises(SystemExit) as excinfo:
        simulate.main(["--policy", "heister", "--turns", "1"])
    assert excinfo.value.code == 2
    assert "baker" in capsys.readouterr().err


@pytest.mark.parametrize("extra,flag", [(["--policy", "cautious"], "--policy"),
                                        (["--policy", "thief"], "--policy"),
                                        (["--days", "3"], "--days")])
def test_the_deck_walker_refuses_what_it_would_ignore(capsys, extra: list[str],
                                                      flag: str) -> None:
    """T1 left the deck route accepting any ``--policy`` and ignoring
    ``--days``: a flag that changes nothing is refused, not swallowed."""
    from engine.games import registry
    from scripts import simulate

    try:
        with pytest.raises(SystemExit) as excinfo:
            simulate.main(["--game", "wicked-garden", "--runs", "1", *extra])
    finally:
        registry.deactivate()
    assert excinfo.value.code == 2
    err = capsys.readouterr().err
    assert f"argument {flag}" in err and "deck" in err


def test_the_flagship_refuses_days(capsys) -> None:
    from scripts import simulate

    with pytest.raises(SystemExit) as excinfo:
        simulate.main(["--turns", "1", "--days", "3"])
    assert excinfo.value.code == 2
    assert "hue-and-cry only" in capsys.readouterr().err


def test_the_prose_report_says_the_agendas_are_on(capsys) -> None:
    from engine.games import registry
    from scripts import simulate

    try:
        assert simulate.main(["--game", "hue-and-cry", "--runs", "1", "--days", "1"]) == 0
    finally:
        registry.deactivate()
    out = capsys.readouterr().out
    assert out.splitlines()[0] == "hue-and-cry: seeds 0-0, 1 days (agendas on)"
    assert "collisions -- where the agendas met the player" in out


def test_thieves_names_every_policy_the_collisions_are_measured_over(capsys) -> None:
    from engine.games import registry
    from scripts import simulate, simulate_endings

    try:
        assert simulate.main(["--game", "hue-and-cry", "--policy", "thieves", "--runs", "1",
                              "--days", "1", "--json"]) == 0
    finally:
        registry.deactivate()
    report = json.loads(capsys.readouterr().out)
    assert list(report["policies"]) == list(simulate_endings.THIEF_POLICIES)
    assert list(report["collisions"]["policies"]) == list(simulate_endings.THIEF_POLICIES)
    assert set(simulate_endings.THIEF_POLICIES) <= set(simulate_endings.BURGLE)


def test_the_hue_run_keeps_no_save(monkeypatch, capsys) -> None:
    """The CLI route keeps nothing in the owner's data/saves: every harness
    player it builds is simulate_law.Thief, handed ``_KEEPS_NOTHING``."""
    from engine.games import registry
    from engine.persistence import saves
    from scripts import simulate

    written: list[str] = []
    real_save = saves.SaveStore.save

    def spy(self, state, **kwargs):
        written.append(str(self.root))
        return real_save(self, state, **kwargs)

    monkeypatch.setattr(saves.SaveStore, "save", spy)
    root = saves.saves_root("hue-and-cry")
    before = sorted(p.name for p in root.iterdir()) if root.is_dir() else []
    try:
        assert simulate.main(["--game", "hue-and-cry", "--runs", "1", "--days", "1",
                              "--json"]) == 0
    finally:
        registry.deactivate()
    capsys.readouterr()
    after = sorted(p.name for p in root.iterdir()) if root.is_dir() else []
    assert written == [], written
    assert after == before


# ---------------------------------------------------------------------------
# agenda collisions (v0.18 T2)
# ---------------------------------------------------------------------------


def test_a_collision_is_read_from_the_hits_against_the_houses_touched(monkeypatch) -> None:
    """The definitions, on a record built by hand: a Magpie hit on a house
    the player touched is one collision (before or after, split by which came
    first; its day is when both had happened), a touch in the same
    noon-to-noon span is `cased_the_same_day`, one in that span's night
    hours (20:00-05:00) is also `same_night`, and a hit that filed a deed
    while the player was held is the alibi's. Another agenda's hit, and a house nobody touched, are neither."""
    from engine.games import registry
    from engine.world import law
    from scripts import simulate_endings as se

    registry.activate("hue-and-cry")
    try:
        p = se.Heister(0, "heister", "b")
        # house_a cased at 06:00 on day 2 (not a night hour), robbed at 02:00
        # that morning: the same noon-to-noon span, not co-presence. house_e
        # cased at 22:00 on day 1 and robbed at 01:00: the same night.
        p.touches = [("house_e", 22, "case"), ("house_a", 30, "case"), ("house_a", 31, "job"),
                     ("house_b", 40, "case")]
        p.state.agendas["hits"] = [
            {"agenda": se.MAGPIE, "premise": "house_e", "hour": 25},
            {"agenda": se.MAGPIE, "premise": "house_a", "hour": 26, "deed_id": "d1"},
            {"agenda": se.MAGPIE, "premise": "house_b", "hour": 75, "deed_id": "d2"},
            {"agenda": se.MAGPIE, "premise": "house_c", "hour": 76},
            {"agenda": se.MAGPIE, "premise": "house_d", "hour": 77, "deed_id": "d3"},
            {"agenda": "silas_ambition", "premise": "house_b", "hour": 27},
        ]
        monkeypatch.setattr(law, "held_at", lambda state, hour: 70 <= hour < 80)
        p.collide()
    finally:
        registry.deactivate()
    end = p.end
    assert end.collisions == {"magpie_on_your_house": 3, "same_night": 1,
                              "cased_the_same_day": 2, "robbed_while_held": 2}
    # house_e: day 2 (robbed at 25); house_a: first cased at 30 -> day 2;
    # house_b: robbed at 75 -> day 4.
    assert end.collision_days == {"magpie_on_your_house": 2, "same_night": 2,
                                  "cased_the_same_day": 2, "robbed_while_held": 4}
    assert end.collision_detail == {"magpie_first": 1, "player_first": 2}


def test_the_net_on_hot_goods_is_its_own_kind(monkeypatch) -> None:
    """Fix round 1: the warrant or doubled watch over a thief holding hot
    goods is counted whatever the band, and apart from the marked-thief kind
    (which a band alone satisfies)."""
    from engine.games import registry
    from scripts import simulate_endings as se

    registry.activate("hue-and-cry")
    try:
        p = se.Heister(0, "heister", "b")
        p.state.flags["ardane_doubles_the_watch"] = True
        monkeypatch.setattr(se.Heister, "marked", lambda self: True)
        monkeypatch.setattr(se.Heister, "carries_hot_goods", lambda self: False)
        p.meet(5)
        assert "net_on_hot_goods" not in p.end.collisions
        assert p.end.collision_days == {"net_on_a_marked_thief": 5}
        monkeypatch.setattr(se.Heister, "carries_hot_goods", lambda self: True)
        p.meet(7)
    finally:
        registry.deactivate()
    assert p.end.collision_days == {"net_on_a_marked_thief": 5, "net_on_hot_goods": 7}


#: MEASURED, v0.18 T2: ``simulate.py --game hue-and-cry --policy thieves
#: --seeds 40 --days 14`` (CHANGELOG [Unreleased], the collisions table).
#: Asserted over the FIRST ``COLLISION_SEEDS`` seeds, loosely, as
#: tests/test_hue_and_cry.py pins its other 40-seed harness tables.
COLLISION_SEEDS = 8
COLLISION_DAYS = 14


@pytest.fixture(scope="module")
def measured_collisions():
    """Every thief policy over the first seeds, played once for the module."""
    from engine.games import registry
    from scripts import simulate_endings as se

    before = registry.peek()
    registry.activate("hue-and-cry")
    try:
        runs = {p: [se.play(seed, p, days=COLLISION_DAYS) for seed in range(COLLISION_SEEDS)]
                for p in se.THIEF_POLICIES}
        return {"runs": runs, "table": se.summarise_collisions(runs)}
    finally:
        if registry.peek() is not before:
            registry.deactivate()


def _share(measured, kind: str, policy: str = "") -> float:
    table = measured["table"]
    return (table["policies"][policy][kind]["runs"] if policy
            else table["kinds"][kind]["runs"])


def test_ardanes_net_stands_over_almost_every_marked_thief(measured_collisions) -> None:
    """40 seeds: 92% of runs (heister 100%, loyalist 85%), first day 8.2 --
    every first one under the doubled watch, none waiting for the warrant.
    8 seeds: 88%."""
    table = measured_collisions["table"]
    assert _share(measured_collisions, "net_on_a_marked_thief") >= 0.75, table["kinds"]
    for policy in table["policies"]:
        assert _share(measured_collisions, "net_on_a_marked_thief", policy) >= 0.6, policy
    row = table["kinds"]["net_on_a_marked_thief"]
    assert row["earliest_day"] >= 4 and 6 <= row["first_day"] <= 10, row


def test_silas_splits_the_company_under_a_sworn_thief_on_day_seven(measured_collisions) -> None:
    """40 seeds: 25% of runs, always day 7 (his clock's own pace), the
    loyalist most (45%). 8 seeds: 20%, loyalist 50%."""
    table = measured_collisions["table"]
    row = table["kinds"]["split_on_a_sworn_thief"]
    assert 0.05 <= row["runs"] <= 0.45, row
    assert row["earliest_day"] >= 6, row
    loyalist = _share(measured_collisions, "split_on_a_sworn_thief", "loyalist")
    assert all(loyalist >= _share(measured_collisions, "split_on_a_sworn_thief", p)
               for p in table["policies"]), table["policies"]


def test_the_magpie_meets_the_investigator_at_the_houses_not_the_loyalist(
        measured_collisions) -> None:
    """40 seeds: the Magpie robs a house the player touched in 36% of runs --
    52-60% of the investigators', 10% of the heister's, none of the
    loyalist's -- the Magpie first four times in five; the same night (night
    hours, fix round 1) 4.5%, the same noon-to-noon span 9%, and a robbery
    while the player is held (the alibi's source) 10.5%, all three the
    investigators' alone. 8 seeds: 23%, 2.5%, 2.5%, 5%."""
    table = measured_collisions["table"]
    kinds = table["kinds"]
    assert 0.10 <= kinds["magpie_on_your_house"]["runs"] <= 0.55, kinds
    investigators = [p for p in table["policies"] if p.startswith("investigator_")]
    assert any(_share(measured_collisions, "magpie_on_your_house", p) >= 0.25
               for p in investigators), table["policies"]
    assert _share(measured_collisions, "magpie_on_your_house", "loyalist") == 0.0
    detail = [row["detail"] for row in table["policies"].values()]
    assert sum(d["magpie_first"] for d in detail) > sum(d["player_first"] for d in detail)
    for kind in ("same_night", "cased_the_same_day", "robbed_while_held"):
        # Fix round 1: a floor as well as a ceiling, so a regression to
        # zero is caught (8 seeds: 2.5%, 2.5%, 5% -- one run, one, two).
        assert 0.02 <= kinds[kind]["runs"] <= 0.25, kinds[kind]
        assert set(kinds[kind]["policies"]) <= set(investigators), kinds[kind]
    # Co-presence is a subset of the half-day span, never more.
    assert kinds["same_night"]["runs"] <= kinds["cased_the_same_day"]["runs"]


def test_ardanes_net_meets_hot_goods_under_every_policy(measured_collisions) -> None:
    """Fix round 1: the net over stolen goods still hot, whatever the band --
    40 seeds: 84% of runs (day 8.1), the loyalist least (62%). 8 seeds: 85%."""
    table = measured_collisions["table"]
    row = table["kinds"]["net_on_hot_goods"]
    assert 0.6 <= row["runs"] <= _share(measured_collisions, "net_on_a_marked_thief"), row
    assert row["earliest_day"] >= 4 and 6 <= row["first_day"] <= 10, row
    assert set(row["policies"]) == set(table["policies"]), row


def test_the_collisions_replay_from_the_seed(measured_collisions) -> None:
    from engine.games import registry
    from scripts import simulate_endings as se

    # An investigator's run that met the Magpie at a house (fix round 1: the
    # loyalist never does, so replaying it proved nothing about the table).
    runs = measured_collisions["runs"]["investigator_a"]
    seed = next(i for i, r in enumerate(runs) if r.collisions.get("magpie_on_your_house"))
    registry.activate("hue-and-cry")
    try:
        again = se.play(seed, "investigator_a", days=COLLISION_DAYS)
    finally:
        registry.deactivate()
    assert again == runs[seed]
    assert again.collisions and again.collision_days


# ---------------------------------------------------------------------------
# the living (T3): the burglar's credit, and the careful pickpocket
# ---------------------------------------------------------------------------

#: The living fixture: every thief who pays its own way, over the first seeds
#: at the ruling's 14 days (the fair's last day + 2).
LIVING_SEEDS = 8
LIVING_DAYS = 14
LIVING = ("careful", "careful_porter", "burglar", "burglar_pell", "burglar_marrow")


def test_a_death_is_named_by_the_module_that_asked_and_custody_first(monkeypatch) -> None:
    """``simulate_law.cause_of_death``: the clock's hour is hunger, an
    encounter round the street, a job stage the job; held, it is custody
    whoever asked; anything else is `other`."""
    from engine.games import registry
    from engine.world import law
    from scripts import simulate_law

    registry.activate("hue-and-cry")
    try:
        thief = simulate_law.Thief(0, "careful")
        cause = simulate_law.cause_of_death
        assert cause(thief.state, "x/engine/game/clock.py") == "hunger"
        assert cause(thief.state, "x/engine/game/encounter.py") == "street"
        assert cause(thief.state, "x/engine/world/jobs.py") == "job"
        assert cause(thief.state, "x/tests/whatever.py") == "other"
        monkeypatch.setattr(law, "in_custody", lambda state: True)
        assert cause(thief.state, "x/engine/game/clock.py") == "custody"
        assert cause(thief.state, "x/engine/game/encounter.py") == "custody"
    finally:
        registry.deactivate()


def test_a_starved_hour_is_logged_as_hunger_on_its_day() -> None:
    """Through the real clock: hp at the floor, an hour passes, the respawn
    runs, and the log holds one death -- hunger, on the day it fell."""
    from engine.game.clock import advance_time
    from engine.game.effects import apply_effect
    from engine.games import registry
    from scripts import simulate_law

    registry.activate("hue-and-cry")
    try:
        with simulate_law.counting_deaths():
            thief = simulate_law.Thief(0, "careful")
            day = int(thief.state.world_day)
            gold, where = int(thief.state.stats.gold), str(thief.state.location_id)
            apply_effect(thief.state, {"type": "hp", "delta": -int(thief.state.stats.hp)})
            advance_time(thief.state, 1.0)
            log = simulate_law.death_log(thief.state)
    finally:
        registry.deactivate()
    assert simulate_law.deaths(thief.state) == 1
    assert [d["cause"] for d in log] == ["hunger"] and log[0]["day"] == day, log
    # Fix round 2: what it held and where it lay, read before the respawn
    # (which takes half the purse and carries the body to the Snuffs).
    assert log[0]["gold"] == gold and log[0]["location"] == where, log


@pytest.fixture(scope="module")
def measured_living():
    """Every living thief over the first seeds, played once for the module:
    the runs (for the replay) and the table."""
    from engine.games import registry
    from scripts import simulate_labour, simulate_law

    before = registry.peek()
    registry.activate("hue-and-cry")
    try:
        with simulate_law.agendas_off():
            lives = {p: [simulate_labour.play(seed, p, LIVING_DAYS) for seed in range(LIVING_SEEDS)]
                     for p in LIVING}
        return {"lives": lives,
                "table": {p: simulate_labour.summarise(runs, LIVING_DAYS)
                          for p, runs in lives.items()}}
    finally:
        if registry.peek() is not before:
            registry.deactivate()


def test_the_living_replays_from_the_seed(measured_living) -> None:
    """A welsher's run -- the credit, the collectors, the loot it could not
    sell -- played again from its seed is the same run, field for field."""
    from engine.games import registry
    from scripts import simulate_labour, simulate_law

    runs = measured_living["lives"]["burglar_pell"]
    seed = next(i for i, r in enumerate(runs) if r.credit_broken and r.loot_unsold)
    registry.activate("hue-and-cry")
    try:
        with simulate_law.agendas_off():
            again = simulate_labour.play(seed, "burglar_pell", LIVING_DAYS)
    finally:
        registry.deactivate()
    assert again == runs[seed]


def test_the_careful_pickpocket_dies_of_hunger_and_nothing_else(measured_living) -> None:
    """The owner's v0.14 pressure, broken down (not tuned). 40 seeds x 14
    days: 2.90 deaths a run, every one hunger -- none in the street, the
    cells or at the fair -- at 05:00 in its bed or at 21:00 waiting for the
    night's purse; the first on day 6.2 (never before day 5); 4.33 of 14
    days kept. (Before fix round 1's fence pay: 2.92 and 4.2 -- its purses'
    goods are cheap, so the fences' new pay barely reaches it.)"""
    careful = measured_living["table"]["careful"]
    assert careful["deaths_per_run"] >= 1.5, careful
    assert set(careful["death_causes"]) == {"hunger"}, careful
    assert careful["first_death_day"] >= 4, careful
    assert careful["kept_days_per_run"] <= 6, careful
    hours = {d["hour"] for life in measured_living["lives"]["careful"] for d in life.death_log}
    assert hours <= {5, 21}, hours


def test_a_careful_thief_who_takes_a_shift_when_hungry_keeps_fed(measured_living) -> None:
    """A living exists for a thief who adapts. 40 seeds x 14 days: the
    careful pickpocket who takes Dock Mag's shift on a hungry or lean
    morning keeps 11.9 of 14 days (the honest porter 13.1, the purses-only
    thief 4.3), works 0.74 shifts a day, still lifts purses every run, and
    dies 0.03 times a run (one death in 40 runs). 8 seeds: 10.6 kept, no
    deaths."""
    table = measured_living["table"]
    careful, adaptive = table["careful"], table["careful_porter"]
    assert adaptive["kept_days_per_run"] >= careful["kept_days_per_run"] + 4, (careful, adaptive)
    assert adaptive["kept_days_per_run"] >= 0.6 * LIVING_DAYS, adaptive
    assert adaptive["deaths_per_run"] <= 0.5, adaptive
    assert 0.3 <= adaptive["shifts_per_day"] <= 1.2, adaptive
    assert all(life.money.get("lift", 0) > 0
               for life in measured_living["lives"]["careful_porter"])


def test_the_fencing_burglar_lives_better_than_the_careful_pickpocket(measured_living) -> None:
    """The burglar who never borrows (fix round 1: the fences made to pay,
    trade.yaml). 40 seeds x 14 days: 6.5 hauls a run worth 99 crowns of
    registry value, sold hot for 51.7 (0.54 of what it sold -- Pell's
    0.75 x 0.7, Marrow's 0.7 x 0.9), 3.0 left unsold at the end; it keeps
    7.25 of 14 days against the careful pickpocket's 4.33 (and the honest
    porter's 13.05), ends with 13.3 crowns and dies 0.7 times a run, all
    hunger. Before the fix it fenced 19.3 of 85 (23%) and kept 4.75."""
    table = measured_living["table"]
    burglar, careful = table["burglar"], table["careful"]
    assert burglar["hauls_per_run"] >= 3, burglar
    sold = burglar["loot_taken_per_run"] - burglar["loot_unsold"]
    assert 0.45 <= burglar["fenced_per_run"] / sold <= 0.67, burglar
    assert burglar["runs_with_loot_unsold"] <= 0.5, burglar
    assert burglar["kept_days_per_run"] >= careful["kept_days_per_run"] + 2, (careful, burglar)
    assert burglar["deaths_per_run"] < careful["deaths_per_run"], (careful, burglar)
    assert "credit_struck" not in burglar and "collectors_met" not in burglar, burglar


@pytest.mark.parametrize("welsher,advance", [("burglar_pell", 10), ("burglar_marrow", 5)])
def test_a_welshing_burglar_is_shut_out_of_both_fences(measured_living, welsher: str,
                                                       advance: int) -> None:
    """The cost the owner's v0.15 decision said falls on a burglar. 40 seeds
    x 14 days: every line struck breaks; the counters pay 19.7 (Pell) and
    22.4 (Marrow) crowns a run instead of 51.7; 57-62 crowns of registry
    value are still in its pockets at the end (95% / 92.5% of runs); the
    collectors meet it 2.05 and 1.7 times."""
    table = measured_living["table"]
    burglar, credit = table["burglar"], table[welsher]
    # A burglar whose purse never runs lean never strikes one (fix round 1:
    # one of the fixture's 8 Marrow runs, 0.88 a run).
    assert credit["credit_struck"] >= 0.75 and credit["credit_repaid"] == 0, credit
    assert credit["credit_broken"] >= 0.8, credit
    assert credit["fenced_per_run"] <= 0.6 * burglar["fenced_per_run"], (burglar, credit)
    # The advance never makes up what the counters stopped paying.
    assert advance - (burglar["fenced_per_run"] - credit["fenced_per_run"]) < 0, (burglar, credit)
    assert credit["loot_unsold"] >= burglar["loot_unsold"] + 30, (burglar, credit)
    assert credit["runs_with_loot_unsold"] >= 0.6, credit
    assert credit["collectors_met"] >= 0.5, credit


@pytest.mark.parametrize("welsher", ["burglar_pell", "burglar_marrow"])
def test_welshing_costs_a_burglar_more_than_it_gains(measured_living, welsher: str) -> None:
    """The v0.15 question answered. 40 seeds x 14 days, paired by seed
    against the burglar who never borrows: kept days -0.62 (Pell) and -0.60
    (Marrow), each under 1.3 standard errors -- nothing gained, where a
    purses-only pickpocket still gains +3.1 and +1.2 over 10 days; deaths
    +0.72 and +0.70 a run (5.5 and 4.4 standard errors); 11.0 and 9.5
    crowns less at the end, and more on 1 seed of 40 (Pell) and none
    (Marrow). On the fixture's 8 seeds the welsher ends with no more coin
    than the burglar on every seed, and keeps fewer days (6.9 and 5.75
    against 8.25)."""
    lives = measured_living["lives"]
    table = measured_living["table"]
    burglar, credit = table["burglar"], table[welsher]
    assert credit["kept_days_per_run"] <= burglar["kept_days_per_run"] + 0.5, (burglar, credit)
    assert credit["deaths_per_run"] > burglar["deaths_per_run"], (burglar, credit)
    assert all(w.end_gold <= b.end_gold for b, w in zip(lives["burglar"], lives[welsher])),         [(b.end_gold, w.end_gold) for b, w in zip(lives["burglar"], lives[welsher])]
    assert credit["end_gold"] < burglar["end_gold"], (burglar, credit)


def test_the_new_living_policies_read_only_what_a_player_sees() -> None:
    """The constraint every harness policy keeps: nowhere in the classes T3
    added is the Magpie's role, a clue's `points_to` or `clues_favour` read
    (docstrings aside)."""
    import ast

    path = _ROOT / "scripts" / "simulate_labour.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    ours = {"CarefulPorter", "FencingBurglar", "BurglarOnCredit", "CreditLine"}
    classes = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name in ours]
    assert {c.name for c in classes} == ours
    forbidden = {"agenda_role", "points_to", "clues_favour", "role", "magpie"}
    for cls in classes:
        for node in ast.walk(cls):
            name = (node.attr if isinstance(node, ast.Attribute)
                    else node.id if isinstance(node, ast.Name) else None)
            assert name not in forbidden, (cls.name, name)


def test_living_is_a_hue_and_cry_policy(capsys) -> None:
    """``--policy living`` runs simulate_labour's thieves who pay their own
    way, and prints each one's table."""
    from scripts import simulate

    assert simulate.main(["--game", "hue-and-cry", "--policy", "living", "--runs", "1",
                          "--days", "2", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["config"]["policy"] == "living" and payload["config"]["agendas"] == "off"
    assert tuple(payload["living"]) == simulate.LIVING_POLICIES
    for policy in ("burglar", "burglar_pell", "burglar_marrow", "careful_porter"):
        assert policy in simulate.LIVING_POLICIES
    assert "kept_days_per_run" in payload["living"]["burglar"]


# ---------------------------------------------------------------------------
# the stories with no harness
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("slug,release", [("neon-city", "v0.24.0"),
                                          ("the-long-con", "v0.25.0"),
                                          ("dev-story", "v0.26.0")])
def test_a_graph_story_with_no_harness_is_refused_truthfully(capsys, slug: str,
                                                             release: str) -> None:
    from engine.games import registry
    from scripts import simulate

    assert simulate.story_shape(registry.get(slug)) == "graph"
    try:
        with pytest.raises(SystemExit) as excinfo:
            simulate.main(["--game", slug, "--turns", "1"])
    finally:
        registry.deactivate()
    assert excinfo.value.code == 2
    err = capsys.readouterr().err
    assert "flagship-owned" in err and release in err and "hue-and-cry" in err


# ---------------------------------------------------------------------------
# capture (run at the commit before the route, never to make a test pass)
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    if sys.argv[1:] != ["--write-golden"]:
        raise SystemExit("usage: python tests/test_simulate_thief.py --write-golden")
    GOLDEN.mkdir(parents=True, exist_ok=True)
    for _name, _argv in GOLDEN_RUNS.items():
        (GOLDEN / _name).write_bytes(_stdout(_argv))
        print(f"wrote {GOLDEN / _name}")
