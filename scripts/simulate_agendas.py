"""
The Agendas Balance Harness
===========================

Play HUE & CRY headlessly for ten in-game days with a scripted player and
report the numbers that decide whether the city's agendas are tuned (AGENTS.md
rule 10: balance constants are set by measurement, not guessed): the Magpie,
Captain Ardane's net and Silas Crook's rise (data/rules/agendas.yaml).

THREE POLICIES, one city, the same seeds:

  idle      Never steals. Walks up to Wickmarket each morning and passes the
            day there an hour a turn (so the patrol gets its look) and sleeps
            in the square. Everything the watch holds against it is the
            Magpie's work landing on its name -- this policy MEASURES THE HOOK.
  careful   ``scripts/simulate_law.py``'s careful thief (the porter's smock,
            one purse a night in the Snuffs) that also buys lockpicks on day
            one and, on days 3, 5, 7 and 9, burgles a tier-1/2 house the way
            ``scripts/simulate_jobs.py``'s careful burglar does: cased, the
            empty hour, the best way in, walking away from a roused house.
  reckless  ``simulate_law.py``'s reckless thief (three purses every
            afternoon in Wickmarket, in its own face) that also, on every
            even day, burgles a tier-1/2 house blind at eleven at night --
            no tools, no casing, by the door.

Both thieves pick houses the way ``simulate_jobs.py`` does (a seed-spread
choice among the tier-1/2 houses nobody has robbed ON THE PLAYER'S RECORD):
a thief does not know which house the Magpie emptied last night. That is
what the COLLISION rate counts -- a player job opened on a house an agenda
had already robbed -- so it is the honest rate, not one a careful reader of
the town talk would see.

WHAT IS REAL AND WHAT IS NOT. The thieves are ``simulate_jobs.Burglar``,
which is ``simulate_law.Thief``: every lift, walk, purchase, guise change,
case, burglary, encounter approach, fine and sentence goes through
``tool_dispatcher.execute_intent``, and time through ``clock.advance_time`` --
so the agendas walk every hour exactly as they do in play, through the Law's
per-hour hook. What is NOT the game, and says so: the player is fed and rested
as simulate_law.py and simulate_jobs.py feed it, and careful is handed its
lockpicks' price (``simulate_jobs.KIT_PURSE``). No narration runs.

Usage:
    python scripts/simulate_agendas.py                    # 40 seeds x 10 days, all
    python scripts/simulate_agendas.py --seeds 10 --policy idle
    python scripts/simulate_agendas.py --set the_magpie.lift_a_shiny.every_hours=36
    python scripts/simulate_agendas.py --json

Version: v0.1.0 [2026-09-25]
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts import simulate_jobs, simulate_law  # noqa: E402

POLICIES = ("idle", "careful", "reckless")
MAGPIE = "the_magpie"
ARDANE = "ardane_hunt"
SILAS = "silas_ambition"
CLOCKS = {"magpie_spree": MAGPIE, "ardane_net": ARDANE, "silas_rise": SILAS}
#: The veiled bands a clock is read in (``engine/state/schema.py``), past "none".
CLOCK_BANDS = ("faint", "some", "strong", "utmost")
#: Where the idle player passes its days, and the hours it stands about.
IDLE_DISTRICT = "wickmarket"
IDLE_HOURS = range(9, 21)
#: The careful thief's burglary days, and the reckless one's.
CAREFUL_JOB_DAYS = (3, 5, 7, 9)
RECKLESS_JOB_DAYS = (2, 4, 6, 8, 10)
CAREFUL_JOB_HOUR = 9
RECKLESS_JOB_HOUR = 23
#: Seeds the role evenness is counted over (at least the brief's 90).
ROLE_SEEDS = 90


@dataclass
class Job:
    premise: str
    day: int
    collided: bool          # an agenda had robbed it already
    by_magpie: bool         # ...and it was the Magpie
    outcome: str = ""


@dataclass
class Day:
    day: int
    band: str               # the worst band on the player's face, anywhere, at 08:00
    clocks: dict[str, float] = field(default_factory=dict)
    lifts: int = 0
    witnessed: int = 0
    reported: int = 0
    arrests: int = 0
    seconds: float = 0.0


@dataclass
class Run:
    """What simulate_law.Thief and simulate_jobs.Burglar read and write, plus the agendas."""
    seed: int
    policy: str
    magpie: str = ""
    days: list[Day] = field(default_factory=list)
    jobs: list[simulate_jobs.JobRow] = field(default_factory=list)
    player_jobs: list[Job] = field(default_factory=list)
    magpie_hits: int = 0
    silas_moves: int = 0
    traces: int = 0
    unseen_traces: int = 0
    company: int = 0
    arrests: int = 0
    stops: int = 0
    fines_paid: int = 0
    income: int = 0
    bribes: int = 0
    bribe_gold: int = 0
    days_served: list[int] = field(default_factory=list)
    hp_after_sentence: list[int] = field(default_factory=list)
    min_hp: int = 99


class Citizen(simulate_jobs.Burglar):
    """The jobs harness's burglar -- simulate_law's thief underneath -- with an agenda ledger."""

    def __init__(self, seed: int, policy: str) -> None:
        from engine.world import agendas

        super().__init__(seed, policy)
        self.run = Run(seed=seed, policy=policy)  # type: ignore[assignment]
        self.run.magpie = agendas.role(self.state, "magpie")

    def hit_by(self, premise_id: str) -> set[str]:
        return {str(h.get("agenda")) for h in self.state.agendas.get("hits") or []
                if str(h.get("premise")) == premise_id}

    def job(self, prem: dict[str, Any], day: int, *, smart: bool) -> None:
        """Burgle ``prem`` (the thief stands in its district) and note any collision."""
        premise_id = str(prem["id"])
        robbed_by = self.hit_by(premise_id)
        row = self.burgle(prem, smart=smart, walk_away=smart)
        if row.outcome == "refused":
            return
        self.run.player_jobs.append(Job(premise=premise_id, day=day, collided=bool(robbed_by),
                                        by_magpie=MAGPIE in robbed_by, outcome=row.outcome))

    def pick_house(self, n: int) -> Optional[dict[str, Any]]:
        tried = {j.premise for j in self.run.player_jobs}
        options = [p for p in self.candidates(simulate_jobs._small) if str(p["id"]) not in tried]
        return simulate_jobs._pick(options, self.run.seed, n)


# ---------------------------------------------------------------------------
# Policies: one in-game day each
# ---------------------------------------------------------------------------


def _idle_day(c: Citizen, day: int) -> None:
    c.walk(IDLE_DISTRICT)
    for hour in IDLE_HOURS:
        if c.state.location_id != IDLE_DISTRICT:
            return  # held, or somewhere the watch put it
        c.wait_until(hour)
        c.linger(1.0)


def _careful_day(c: Citizen, day: int) -> None:
    from engine.world import law

    if day == 1:
        # The smock on the quay first, then Marrow's lockpicks in the Snuffs at
        # dusk, then simulate_law's change of face in an empty Wickmarket.
        c.act("buy", "npc_dock_mag/porters_smock")
        c.buy_kit(("lockpicks",))
        c.walk(simulate_law.BUSY_DISTRICT)
        c.wait_until(simulate_law.CAREFUL_CHANGE_HOUR)
        if "porter" in c.legal_targets("guise"):
            c.act("guise", "porter")
        c.walk(simulate_law.QUIET_DISTRICT)
        return
    if day in CAREFUL_JOB_DAYS:
        prem = c.pick_house(len(c.run.player_jobs))
        if prem is not None:
            c.wait_until(CAREFUL_JOB_HOUR)
            c.walk(str(prem["district"]))
            if c.state.location_id == prem["district"]:
                c.case_until(str(prem["id"]), simulate_jobs.CAREFUL_INTEL)
                if c.wait_for_empty(str(prem["id"])):
                    c.job(prem, day, smart=True)
        # The night's lift, if the house left the evening free.
        if law.in_custody(c.state) or c.state.world_clock_hours % 24 >= simulate_law.CAREFUL_LIFT_HOUR:
            return
    simulate_law._careful_day(c, day)


def _reckless_day(c: Citizen, day: int) -> None:
    simulate_law._reckless_day(c, day)
    if day not in RECKLESS_JOB_DAYS:
        return
    prem = c.pick_house(len(c.run.player_jobs))
    if prem is None:
        return
    c.walk(str(prem["district"]))
    c.wait_until(RECKLESS_JOB_HOUR)
    if c.state.location_id == prem["district"]:
        c.job(prem, day, smart=False)


DAYS: dict[str, Callable[[Citizen, int], None]] = {
    "idle": _idle_day,
    "careful": _careful_day,
    "reckless": _reckless_day,
}


# ---------------------------------------------------------------------------
# One run
# ---------------------------------------------------------------------------


def _clock_readings(state: Any) -> dict[str, float]:
    from engine.game import clocks

    return {name: float(clocks.value_of(state, name)) for name in CLOCKS}


def play(seed: int, policy: str, days: int) -> Run:
    """
    One run of ``days`` in-game days, a row per day read at the next 08:00
    (simulate_law.play's shape: a sentence that swallows days repeats the row
    it walked out on).
    """
    from engine.world import law

    c = Citizen(seed, policy)
    everywhere = list(law.load_spec()["jurisdictions"])
    played = 0
    while c.state.world_day <= days:
        played += 1
        start = time.perf_counter()
        first_day = c.state.world_day
        row = Day(day=first_day, band="")
        c.today = row  # type: ignore[assignment]
        c.morning()
        arrests_before = c.run.arrests
        DAYS[policy](c, played)
        c.wait_until(8)
        c.morning()
        row.arrests = c.run.arrests - arrests_before
        row.band = simulate_law._worst_band(c.state, everywhere)
        row.clocks = _clock_readings(c.state)
        row.seconds = time.perf_counter() - start
        c.run.days.append(row)
        for skipped in range(first_day + 1, min(c.state.world_day - 1, days) + 1):
            c.run.days.append(Day(day=skipped, band=row.band, clocks=dict(row.clocks)))
    c.run.days = c.run.days[:days]
    hits = c.state.agendas.get("hits") or []
    c.run.magpie_hits = sum(str(h.get("agenda")) == MAGPIE for h in hits)
    # Every Silas move robs, so his hits ARE his moves.
    c.run.silas_moves = sum(str(h.get("agenda")) == SILAS for h in hits)
    traces = c.state.agendas.get("traces") or []
    c.run.traces = len(traces)
    c.run.unseen_traces = sum(not t.get("seen") for t in traces)
    c.run.company = int(c.state.reputations.get("honest_company", 0))
    return c.run


# ---------------------------------------------------------------------------
# The table
# ---------------------------------------------------------------------------


def _first_day(run: Run, clock: str, floor: float) -> Optional[int]:
    return next((d.day for d in run.days if d.clocks.get(clock, 0.0) >= floor), None)


def _band_floor(clock: str, band: str) -> float:
    """The lowest reading of ``clock`` that shows as ``band`` (schema's banding)."""
    from engine.state.active import active_schema
    from engine.state.schema import VEILED_BANDS

    spec = active_schema().get(clock)
    lo, hi = float(spec.minimum), float(spec.maximum)
    value = lo
    while value <= hi:
        if VEILED_BANDS.index(spec.band(value)) >= VEILED_BANDS.index(band):
            return value
        value += 1.0
    return hi + 1.0


def _median(values: list[Optional[int]]) -> Optional[int]:
    reached = sorted(v for v in values if v is not None)
    return statistics.median_low(reached) if reached else None


def summarise(runs: list[Run], days: int) -> dict[str, Any]:
    from engine.world import law

    bands = list(law.load_spec()["wanted"]["bands"])

    def first_band(run: Run, band: str) -> Optional[int]:
        floor = bands.index(band)
        return next((d.day for d in run.days if bands.index(d.band or bands[0]) >= floor), None)

    ardane: dict[str, Any] = {}
    for band in CLOCK_BANDS:
        floor = _band_floor("ardane_net", band)
        firsts = [_first_day(r, "ardane_net", floor) for r in runs]
        ardane[band] = {"median_day": _median(firsts),
                        "reached": round(sum(f is not None for f in firsts) / len(runs), 3)}
    jobs = [j for r in runs for j in r.player_jobs]
    per_day = []
    for d in range(days):
        rows = [r.days[d] for r in runs if len(r.days) > d]
        per_day.append({
            "day": d + 1,
            "median_band": bands[int(statistics.median_low(
                [bands.index(x.band or bands[0]) for x in rows]))],
            "sought_or_worse": round(sum(bands.index(x.band or bands[0]) >= bands.index("sought")
                                         for x in rows) / len(rows), 3),
            "ardane_mean": round(statistics.mean(x.clocks.get("ardane_net", 0.0) for x in rows), 2),
            "spree_mean": round(statistics.mean(x.clocks.get("magpie_spree", 0.0) for x in rows), 2),
        })
    seed_days = [x for r in runs for x in r.days]
    below_sought = sum(bands.index(x.band or bands[0]) < bands.index("sought")
                       for x in seed_days) / max(1, len(seed_days))
    first_noticed = [first_band(r, "noticed") for r in runs]
    first_sought = [first_band(r, "sought") for r in runs]
    return {
        "runs": len(runs),
        "per_day": per_day,
        "magpie_hits_per_run": round(statistics.mean(r.magpie_hits for r in runs), 2),
        "magpie_hits_min": min(r.magpie_hits for r in runs),
        "magpie_hits_max": max(r.magpie_hits for r in runs),
        "player_jobs": len(jobs),
        "collision_rate": round(sum(j.collided for j in jobs) / len(jobs), 3) if jobs else 0.0,
        "magpie_collision_rate": (round(sum(j.by_magpie for j in jobs) / len(jobs), 3)
                                  if jobs else 0.0),
        "first_noticed_median_day": _median(first_noticed),
        "first_sought_median_day": _median(first_sought),
        "below_sought_seed_days": round(below_sought, 3),
        "sought_by_day_6": round(sum(f is not None and f <= 6 for f in first_sought)
                                 / len(runs), 3),
        "noticed_by_day_6": round(sum(f is not None and f <= 6 for f in first_noticed)
                                  / len(runs), 3),
        "ended_band_counts": dict(Counter(r.days[-1].band for r in runs if r.days)),
        "ardane": ardane,
        "ardane_full": round(sum(_first_day(r, "ardane_net", _band_floor_max("ardane_net"))
                                 is not None for r in runs) / len(runs), 3),
        "silas_moves_per_run": round(statistics.mean(r.silas_moves for r in runs), 2),
        "company_standing_mean": round(statistics.mean(r.company for r in runs), 2),
        "traces_per_run": round(statistics.mean(r.traces for r in runs), 2),
        "traces_max": max(r.traces for r in runs),
        "unseen_traces_per_run": round(statistics.mean(r.unseen_traces for r in runs), 2),
        "arrests_per_run": round(statistics.mean(r.arrests for r in runs), 2),
        "runs_with_an_arrest": round(sum(r.arrests >= 1 for r in runs) / len(runs), 3),
        "magpie_roles": dict(Counter(r.magpie for r in runs)),
        "max_seconds_per_day": round(max((x.seconds for r in runs for x in r.days), default=0.0), 3),
    }


def _band_floor_max(clock: str) -> float:
    from engine.state.active import active_schema

    return float(active_schema().get(clock).maximum)


def role_evenness(seeds: int = ROLE_SEEDS) -> dict[str, int]:
    """Who the seed makes the Magpie over ``seeds`` seeds -- no play needed."""
    from engine.game.state import GameState
    from engine.world import agendas

    return dict(Counter(agendas.role(GameState(rng_seed=s), "magpie") for s in range(seeds)))


def measure(policy: str, seeds: int, days: int) -> dict[str, Any]:
    return summarise([play(seed, policy, days) for seed in range(seeds)], days)


def render(policy: str, report: dict[str, Any]) -> str:
    lines = [f"{policy} ({report['runs']} seeds)",
             "| day | median band | sought+ | ardane (mean) | spree (mean) |",
             "|---|---|---|---|---|"]
    for row in report["per_day"]:
        lines.append(f"| {row['day']} | {row['median_band']} | {row['sought_or_worse']:.0%} | "
                     f"{row['ardane_mean']} | {row['spree_mean']} |")
    ardane = ", ".join(f"{band} day {row['median_day']} ({row['reached']:.0%})"
                       for band, row in report["ardane"].items())
    lines.append(
        f"magpie robberies/run {report['magpie_hits_per_run']} "
        f"({report['magpie_hits_min']}..{report['magpie_hits_max']}); "
        f"player jobs {report['player_jobs']}, collisions {report['collision_rate']:.0%} "
        f"(magpie {report['magpie_collision_rate']:.0%}); first noticed median day "
        f"{report['first_noticed_median_day']}, first sought median day "
        f"{report['first_sought_median_day']}; noticed by day 6 {report['noticed_by_day_6']:.0%}, "
        f"sought by day 6 {report['sought_by_day_6']:.0%}; below sought on "
        f"{report['below_sought_seed_days']:.0%} of seed-days; ended {report['ended_band_counts']}"
    )
    lines.append(f"ardane: {ardane}; full {report['ardane_full']:.0%}")
    lines.append(
        f"silas moves/run {report['silas_moves_per_run']}; company standing "
        f"{report['company_standing_mean']}; traces/run {report['traces_per_run']} "
        f"(max {report['traces_max']}, unseen {report['unseen_traces_per_run']}); "
        f"arrests/run {report['arrests_per_run']}, runs with an arrest "
        f"{report['runs_with_an_arrest']:.0%}; roles {report['magpie_roles']}; "
        f"slowest day {report['max_seconds_per_day']}s"
    )
    return "\n".join(lines)


def _override(assignment: str) -> None:
    """
    Patch one number in the LOADED agendas file, for this process only.

    A tuning aid: the file on disk is what ships. ``<agenda>.<move or
    reaction id>.<key>=N`` -- ``the_magpie.lift_a_shiny.every_hours=36``,
    ``ardane_hunt.takes_a_statement.advance=2``; a comma list for
    ``at_hours``. ``report.precision=0.5`` on a move patches its first
    report effect's precision.
    """
    from engine.world import agendas

    key, _, raw = assignment.partition("=")
    agenda_id, row_id, *rest = key.strip().split(".")
    agenda = agendas.spec()["agendas"][agenda_id]
    row = next(r for r in agenda["moves"] + agenda["reactions"] if r["id"] == row_id)
    if rest[0] == "report":
        effect = next(e for e in row["effects"] if e.get("type") == "report")
        effect[rest[1]] = float(raw)
        return
    if rest[0] == "select":
        body = next(iter(row["select"].values()))
        body[rest[1]] = int(raw)
        return
    if rest[0] == "once":
        row["once"] = raw.strip().lower() in ("1", "true", "yes")
        return
    row[rest[0]] = [int(v) for v in raw.split(",")] if "," in raw else int(raw)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--seeds", type=int, default=40)
    parser.add_argument("--days", type=int, default=10)
    parser.add_argument("--policy", choices=(*POLICIES, "all"), default="all")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--set", action="append", default=[], metavar="KEY=VALUE",
                        help="try a number without editing the file (repeatable)")
    args = parser.parse_args(argv)

    import logging

    logging.disable(logging.WARNING)
    from engine.games import registry

    registry.activate("hue-and-cry")
    for assignment in args.set:
        _override(assignment)
    policies = POLICIES if args.policy == "all" else (args.policy,)
    reports: dict[str, Any] = {p: measure(p, args.seeds, args.days) for p in policies}
    roles = role_evenness(max(ROLE_SEEDS, args.seeds))
    if args.json:
        print(json.dumps({"policies": reports, "roles": roles}, indent=2))
    else:
        print("\n\n".join(render(p, r) for p, r in reports.items()))
        print(f"\nroles over {max(ROLE_SEEDS, args.seeds)} seeds: {roles}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
