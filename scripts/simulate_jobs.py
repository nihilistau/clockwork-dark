"""
The Jobs Balance Harness
========================

Play HUE & CRY's burglaries headlessly with a scripted thief and report the
numbers that decide whether jobs are tuned (AGENTS.md rule 10: balance
constants are set by measurement, not guessed).

FOUR POLICIES, one city, the same seeds:

  blind        Burgles tier-1/2 houses uncased, carrying nothing, at whatever
               hour it happens to arrive; always goes in by the door, never
               calls on a flashback, and never walks away from a job.
  careful      Buys lockpicks from Marrow on day one. For each job it picks a
               tier-1/2 house, watches it until it knows at least
               ``CAREFUL_INTEL`` things about it, then waits in the street for
               the hour nobody is home (``premises.empty_now``) and goes in by
               the way in with the best odds the job shows it. It calls on every
               flashback that would help, and walks away (``abort``) the moment
               the house is roused.
  greedy       The careful thief's method -- lockpicks, a smoke pellet, casing,
               flashbacks -- turned on a tier-3+ house and then the Margrave's
               Treasury, at eleven at night, and it never walks away.
  greedy_bare  The Treasury alone, the way ``blind`` would do it: uncased,
               no tools, no flashbacks, by the door at eleven at night. The
               control for "near-impossible without prep and tools".

Every run answers a stop the way ``scripts/simulate_law.py``'s thieves do --
``run`` -- so an arrest counts how often the watch catches the policy, not a
taste in surrender. Held, a thief pays the fine if it can and serves the days
if not.

WHAT IS REAL AND WHAT IS NOT. Every purchase, walk, case, burgle, stage,
flashback, abort, encounter approach, fine and sentence goes through
``tool_dispatcher.execute_intent`` -- the production channel a chosen option
takes -- so legality, odds, witnesses, the alarm, the watch and the arrest are
the engine's own. The patrol runs after every action that did not answer an
open scene or job, exactly as ``run_turn`` places it. Waiting advances the
clock through ``clock.advance_time``. What is NOT the game, and says so:

  * the thief is fed and rested every few hours while it waits
    (``hunger``/``stamina`` effects), as simulate_law.py does each morning --
    HUE & CRY ships no food loop yet, and a day waited unfed starves hp away
    that this table would otherwise blame on a job;
  * careful and greedy are handed the price of their kit on day one
    (``KIT_PURSE``, a ``gold`` effect): the run starts with 5 crowns and this
    harness measures jobs, not how long a thief lifts purses to afford picks.
    What a job is worth at a fence is reported beside it so the price can be
    judged against the take;
  * the careful thief chooses its way in by ``jobs.band_for`` -- the same odds
    the narrator is handed as reasons, a feature the house has not been cased
    for included ("a good lock on the street door, not yet cased").

AGENDAS ARE OFF HERE BY DEFAULT (v0.12), for simulate_law.py's reason: the
Magpie's robberies land on the thief's own name and would be counted as
what the jobs earned. ``--agendas`` turns them on; scripts/simulate_agendas.py
measures jobs and agendas together (collisions included).

Usage:
    python scripts/simulate_jobs.py                     # 40 seeds, every policy
    python scripts/simulate_jobs.py --seeds 10 --policy careful
    python scripts/simulate_jobs.py --set tier_band.1=trivial --json
    python scripts/simulate_jobs.py --agendas

Version: v0.2.0 [2026-09-25]
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.simulate_law import Thief as _LawThief  # noqa: E402

POLICIES = ("blind", "careful", "greedy", "greedy_bare")
#: Jobs blind and careful each attempt per run, one a day.
JOBS_PER_RUN = 3
#: How much a careful thief knows about a house before it goes in: the
#: occupancy line (always first) and one more.
CAREFUL_INTEL = 2
#: How much the greedy thief watches a great house first: until watching can
#: tell it nothing more (casing refuses a house it knows everything about).
GREEDY_INTEL = 99
#: What careful and greedy are handed on day one to buy their kit with.
KIT_PURSE = {"careful": 20, "greedy": 30}
#: Marrow's yard opens at 17:00 (data/economy.yaml).
MARROW_HOUR = 18
#: The greedy thief's hour: the first of the night, when a great house has
#: just gone to bed and the dawn shift is as far off as it will ever be.
GREEDY_HOUR = 23
TREASURY = "prem_margraves_treasury"
#: Bands a prepped thief does not spend a shift flashback on.
EASY_ENOUGH = ("trivial", "easy")
#: The longest the harness lets the thief go unfed while it waits.
FEED_EVERY_HOURS = 6.0
#: A job longer than this many turns is a harness bug, not a burglary.
MAX_TURNS = 40
#: Districts a thief walks to rob (the three secret places hold no houses).
PUBLIC_DISTRICTS = ("tallow_docks", "wickmarket", "the_snuffs", "silk_row",
                    "chandlers_rise", "lantern_house", "margraves_hill", "gallows_green")


@dataclass
class JobRow:
    seed: int
    policy: str
    premise: str
    type: str
    tier: int
    outcome: str = ""
    alarm: int = 0              # the alarm at the close
    raised: bool = False        # the alarm reached max at some point
    flashbacks: int = 0
    prep_at_start: int = 0
    deeds_filed: int = 0        # distinct burglary deeds the watch filed
    witnesses: int = 0
    arrested: bool = False
    loot_value: int = 0         # registry value of what was carried out
    turns: int = 0
    min_hp: int = 0


@dataclass
class Run:
    """What ``simulate_law.Thief`` reads and writes, plus the jobs."""
    seed: int
    policy: str
    jobs: list[JobRow] = field(default_factory=list)
    arrests: int = 0
    stops: int = 0
    fines_paid: int = 0
    income: int = 0
    bribes: int = 0
    bribe_gold: int = 0
    days_served: list[int] = field(default_factory=list)
    hp_after_sentence: list[int] = field(default_factory=list)
    min_hp: int = 99
    worst_band: str = ""        # the worst wanted band anywhere when the run ends


class Burglar(_LawThief):
    """simulate_law.py's thief -- the same action channel, stop and custody -- robbing houses."""

    def __init__(self, seed: int, policy: str) -> None:
        super().__init__(seed, policy)
        self.run = Run(seed=seed, policy=policy)  # type: ignore[assignment]

    def act(self, action: str, target: str = "") -> dict[str, Any]:
        """simulate_law's action, then the turn-end observation ``run_turn`` makes.

        ``QuestEngine.observe`` is what records ``visited`` -- the fact a
        flashback's ``requires: {visited: "{district}"}`` reads. Skipping it
        (simulate_law never needed it) would measure a bribed servant nobody
        can ever call on.
        """
        from engine.game.quests import QuestEngine

        result = super().act(action, target)
        QuestEngine.observe(self.state)
        return result

    # -- reading the world ----------------------------------------------------

    def burglary_deeds(self) -> set[str]:
        from engine.world import jobs

        deed = jobs.spec()["alarm"]["deed"]
        return {str(r.get("deed_id")) for r in self.state.law.get("reports") or []
                if r.get("deed") == deed}

    def candidates(self, keep: Callable[[dict[str, Any]], bool]) -> list[dict[str, Any]]:
        from engine.world import jobs, premises

        taken = set(jobs.robbed(self.state))
        out = []
        for district in PUBLIC_DISTRICTS:
            for prem in premises.at(self.state, district):
                if str(prem["id"]) not in taken and keep(prem):
                    out.append(prem)
        return out

    def case_until(self, premise_id: str, intel: int) -> None:
        from engine.world import law, premises

        for _ in range(12):
            if len(premises.known(self.state, premise_id)) >= intel:
                return
            if law.in_custody(self.state) or premise_id not in self.legal_targets("case"):
                return
            self.act("case", premise_id)

    def wait_for_empty(self, premise_id: str) -> bool:
        """Stand in the street, an hour a turn, until nobody is home. False if that never comes."""
        from engine.world import law, premises

        for _ in range(24):
            if law.in_custody(self.state):
                return False
            if premises.empty_now(self.state, premise_id):
                return True
            self.linger(1.0)
        return premises.empty_now(self.state, premise_id)

    # -- the job itself --------------------------------------------------------

    def best_entry(self) -> str:
        from engine.game.intents import DIFFICULTY_BANDS
        from engine.world import jobs

        bands = list(DIFFICULTY_BANDS)
        entries = jobs.spec()["entries"]

        def cost(eid: str) -> tuple[int, int]:
            band, _ = jobs.band_for(self.state, "entry", eid)
            # A fall costs hp: on equal odds, take the way in that cannot hurt.
            return bands.index(band), int(bool(entries[eid]["hurts"]))

        return min(self.legal_targets("job"), key=cost)

    def call_flashbacks(self, row: JobRow) -> None:
        from engine.world import jobs

        for _ in range(4):
            kinds = self.legal_targets("flashback")
            useful = []
            for kind in kinds:
                effect = jobs.spec()["flashbacks"][kind]["effect"]
                stage = jobs.current_stage(self.state)
                if "remove_obstacle" in effect:
                    job = jobs.active(self.state) or {}
                    # Only once the house has been read: `_ensure_obstacles`
                    # does that the same way a roll would. An empty house has
                    # nobody to have bribed.
                    if job.get("obstacles") or (stage == "inside" and "obstacles" not in job
                                                and not self.empty_inside()):
                        useful.append(kind)
                elif jobs.band_for(self.state, str(stage))[0] not in EASY_ENOUGH:
                    # Prep is scarce: a shift is spent where the odds are poor,
                    # and kept for a later stage where they are fine already.
                    useful.append(kind)
            if not useful:
                return
            receipt = self.act("flashback", useful[0])
            if not receipt.get("ok"):
                return
            row.flashbacks += 1

    def empty_inside(self) -> bool:
        from engine.world import jobs, premises

        job = jobs.active(self.state) or {}
        return premises.empty_now(self.state, str(job.get("premise") or ""))

    def burgle(self, prem: dict[str, Any], *, smart: bool, walk_away: bool) -> JobRow:
        """Open a job on ``prem`` (the thief is already in its district) and play it out."""
        from engine.game import encounter
        from engine.game.inventory import value_of
        from engine.world import jobs, law

        row = JobRow(seed=self.run.seed, policy=self.run.policy, premise=str(prem["id"]),
                     type=str(prem.get("type")), tier=int(prem.get("tier") or 0),
                     prep_at_start=int(self.state.jobs.get("prep") or 0),
                     min_hp=int(self.state.stats.hp))
        deeds_before = self.burglary_deeds()
        opened = self.act("burgle", row.premise)
        if not opened.get("ok"):
            row.outcome = "refused"
            return row
        alarm_max = int(jobs.spec()["alarm"]["max"])
        levels = [*jobs.spec()["alarm"]["bands"], jobs.RAISED]
        loot: list[str] = []
        for _ in range(MAX_TURNS):
            job = jobs.active(self.state)
            if job is None:
                break
            loot = [str(i) for i in job.get("loot") or []]
            row.alarm = int(job.get("alarm") or 0)
            row.raised = row.raised or row.alarm >= alarm_max
            if walk_away and row.alarm >= alarm_max:
                self.act("abort")
                continue
            if smart:
                self.call_flashbacks(row)
            stage = jobs.current_stage(self.state)
            options = self.legal_targets("job")
            if not options:
                self.act("abort")
                continue
            choice = self.best_entry() if smart and stage == "entry" else options[0]
            receipt = self.act("job", choice)
            row.turns += 1
            row.witnesses += len(receipt.get("witnesses") or [])
            row.min_hp = min(row.min_hp, int(self.state.stats.hp))
            band = str(receipt.get("alarm_band") or "")
            if band in levels:
                row.alarm = levels.index(band)
                row.raised = row.raised or row.alarm >= alarm_max
        else:
            self.act("abort")
        last = self.state.jobs.get("last") or {}
        row.outcome = str(last.get("outcome") or "")
        if row.outcome == "caught":
            row.alarm = alarm_max
            row.raised = True
        if row.outcome in jobs.CARRIED_OUT:
            row.loot_value = sum(value_of(i) for i in loot)
        arrests_before = self.run.arrests
        if encounter.active(self.state):
            self.answer_stop()
        row.arrested = self.run.arrests > arrests_before or law.in_custody(self.state)
        if law.in_custody(self.state):
            self.leave_custody()
        row.deeds_filed = len(self.burglary_deeds() - deeds_before)
        row.min_hp = min(row.min_hp, int(self.state.stats.hp))
        self.run.min_hp = min(self.run.min_hp, row.min_hp)
        self.run.jobs.append(row)
        return row

    def wait_until(self, hour: int) -> None:
        """simulate_law's wait, fed and rested every few hours on the way.

        A job day can end at nine in the morning and the next start at eight
        the day after: waited in one piece, that is a day unfed, and HUE &
        CRY's hunger takes the hp this harness would then report as the job's.
        """
        from engine.game.clock import advance_time

        now = self.state.world_clock_hours
        target = (int(now // 24) * 24) + hour
        while target < now - 1e-9:
            target += 24
        while target - self.state.world_clock_hours > 1e-9:
            step = min(FEED_EVERY_HOURS, target - self.state.world_clock_hours)
            advance_time(self.state, step)
            self.morning()

    def next_morning(self) -> None:
        self.wait_until(8)
        self.morning()

    def buy_kit(self, items: tuple[str, ...]) -> None:
        from engine.game.effects import apply_effect

        apply_effect(self.state, {"type": "gold", "delta": KIT_PURSE[self.run.policy]})
        self.walk("the_snuffs")
        self.wait_until(MARROW_HOUR)
        for item in items:
            self.act("buy", f"npc_marrow/{item}")


# ---------------------------------------------------------------------------
# Policies: one run each
# ---------------------------------------------------------------------------


def _pick(options: list[dict[str, Any]], seed: int, n: int) -> Optional[dict[str, Any]]:
    """A deterministic, seed-spread choice (the harness's, never the engine's streams)."""
    if not options:
        return None
    ordered = sorted(options, key=lambda p: str(p["id"]))
    return ordered[(seed * 7 + n * 3) % len(ordered)]


def _small(prem: dict[str, Any]) -> bool:
    return int(prem.get("tier") or 0) <= 2 and not prem.get("anchor")


def _blind(b: Burglar) -> None:
    for n in range(JOBS_PER_RUN):
        prem = _pick(b.candidates(_small), b.run.seed, n)
        if prem is None:
            return
        b.walk(str(prem["district"]))
        # "Whenever": an hour spread across the day by seed and job.
        b.wait_until((b.run.seed * 5 + n * 11 + 9) % 24)
        if b.state.location_id == prem["district"]:
            b.burgle(prem, smart=False, walk_away=False)
        b.next_morning()


def _careful(b: Burglar) -> None:
    b.buy_kit(("lockpicks",))
    b.next_morning()
    tried: set[str] = set()
    for n in range(JOBS_PER_RUN):
        options = [p for p in b.candidates(_small) if str(p["id"]) not in tried]
        prem = _pick(options, b.run.seed, n)
        if prem is None:
            return
        tried.add(str(prem["id"]))
        b.walk(str(prem["district"]))
        if b.state.location_id != prem["district"]:
            b.next_morning()
            continue
        b.case_until(str(prem["id"]), CAREFUL_INTEL)
        if b.wait_for_empty(str(prem["id"])):
            b.burgle(prem, smart=True, walk_away=True)
        b.next_morning()


def _great_house_job(b: Burglar, prem: dict[str, Any], *, prepped: bool) -> None:
    b.walk(str(prem["district"]))
    if b.state.location_id != prem["district"]:
        return
    if prepped:
        b.case_until(str(prem["id"]), GREEDY_INTEL)
    b.wait_until(GREEDY_HOUR)
    b.burgle(prem, smart=prepped, walk_away=False)


def _greedy(b: Burglar) -> None:
    from engine.game.inventory import holds
    from engine.world import premises

    b.buy_kit(("lockpicks", "smoke_pellet"))
    b.next_morning()
    great = _pick(b.candidates(lambda p: int(p.get("tier") or 0) >= 3 and not p.get("anchor")),
                  b.run.seed, 0)
    if great is not None:
        _great_house_job(b, great, prepped=True)
        b.next_morning()
    # Restock the pellet the first job may have spent.
    if not holds(b.state, "smoke_pellet"):
        b.walk("the_snuffs")
        b.wait_until(MARROW_HOUR)
        b.act("buy", "npc_marrow/smoke_pellet")
        b.next_morning()
    treasury = premises.get(b.state, TREASURY)
    if treasury is not None:
        _great_house_job(b, treasury, prepped=True)


def _greedy_bare(b: Burglar) -> None:
    from engine.world import premises

    treasury = premises.get(b.state, TREASURY)
    if treasury is not None:
        _great_house_job(b, treasury, prepped=False)


PLAYS: dict[str, Callable[[Burglar], None]] = {
    "blind": _blind,
    "careful": _careful,
    "greedy": _greedy,
    "greedy_bare": _greedy_bare,
}


def play(seed: int, policy: str) -> Run:
    from engine.world import law
    from scripts.simulate_law import _worst_band

    b = Burglar(seed, policy)
    b.morning()
    PLAYS[policy](b)
    b.run.worst_band = _worst_band(b.state, list(law.load_spec()["jurisdictions"]))
    return b.run


# ---------------------------------------------------------------------------
# The table
# ---------------------------------------------------------------------------


def _rates(rows: list[JobRow]) -> dict[str, Any]:
    n = len(rows)
    if not n:
        return {"jobs": 0}

    def share(*outcomes: str) -> float:
        return round(sum(r.outcome in outcomes for r in rows) / n, 3)

    carried = [r for r in rows if r.outcome in ("clean", "noisy")]
    return {
        "jobs": n,
        "clean": share("clean"),
        "noisy": share("noisy"),
        "carried_out": share("clean", "noisy"),
        "caught": share("caught"),
        "aborted": share("aborted"),
        "hurt": share("hurt"),
        "raised": round(sum(r.raised for r in rows) / n, 3),
        "mean_alarm": round(statistics.mean(r.alarm for r in rows), 2),
        "flashbacks": round(statistics.mean(r.flashbacks for r in rows), 2),
        "prep_at_start": round(statistics.mean(r.prep_at_start for r in rows), 2),
        "deeds_filed": round(statistics.mean(r.deeds_filed for r in rows), 2),
        "arrests": round(sum(r.arrested for r in rows) / n, 3),
        "loot_per_job": round(statistics.mean(r.loot_value for r in rows), 1),
        "loot_per_haul": round(statistics.mean(r.loot_value for r in carried), 1) if carried else 0.0,
        "min_hp": min(r.min_hp for r in rows),
    }


def summarise(runs: list[Run]) -> dict[str, Any]:
    rows = [r for run in runs for r in run.jobs if r.outcome != "refused"]
    by_tier: dict[str, Any] = {}
    for tier in sorted({r.tier for r in rows}):
        by_tier[str(tier)] = _rates([r for r in rows if r.tier == tier])
    treasury = [r for r in rows if r.premise == TREASURY]
    from engine.world import law

    bands = list(law.load_spec()["wanted"]["bands"])

    def ended_at_least(band: str) -> float:
        floor = bands.index(band)
        return round(sum(bands.index(r.worst_band or bands[0]) >= floor for r in runs)
                     / max(1, len(runs)), 3)

    return {
        "ended_sought": ended_at_least("sought"),
        "ended_wanted": ended_at_least("wanted"),
        "runs": len(runs),
        "all": _rates(rows),
        "tier_1_2": _rates([r for r in rows if r.tier <= 2]),
        "by_tier": by_tier,
        "treasury": _rates(treasury),
        "refused": sum(r.outcome == "refused" for run in runs for r in run.jobs),
        "min_hp": min((run.min_hp for run in runs), default=None),
    }


def measure(policy: str, seeds: int) -> dict[str, Any]:
    return summarise([play(seed, policy) for seed in range(seeds)])


_COLUMNS = ("jobs", "clean", "noisy", "caught", "aborted", "hurt", "mean_alarm",
            "flashbacks", "prep_at_start", "deeds_filed", "arrests", "loot_per_haul")


def render(policy: str, report: dict[str, Any]) -> str:
    lines = [f"{policy} ({report['runs']} seeds)",
             "| rows | " + " | ".join(_COLUMNS) + " |",
             "|---" * (len(_COLUMNS) + 1) + "|"]

    def line(label: str, r: dict[str, Any]) -> None:
        if not r.get("jobs"):
            return
        cells = []
        for key in _COLUMNS:
            value = r[key]
            if key in ("clean", "noisy", "caught", "aborted", "hurt", "arrests"):
                cells.append(f"{value:.0%}")
            else:
                cells.append(str(value))
        lines.append(f"| {label} | " + " | ".join(cells) + " |")

    line("all", report["all"])
    for tier, r in report["by_tier"].items():
        line(f"tier {tier}", r)
    line("treasury", report["treasury"])
    lines.append(f"runs ending sought or worse {report['ended_sought']:.0%}, wanted or worse "
                 f"{report['ended_wanted']:.0%}; min hp {report['min_hp']}; "
                 f"refused opens {report['refused']}")
    return "\n".join(lines)


def _override(assignment: str) -> None:
    """
    Patch one number in the LOADED jobs file, for this process only.

    A tuning aid: the file on disk is what ships. ``tier_band.1=trivial``,
    ``features.good_lock.shift=2``, ``alarm.watch_delay_hours=3``,
    ``deeds.burglary=2`` (the Law's severity).
    """
    from engine.world import jobs, law

    key, _, raw = assignment.partition("=")
    parts = key.strip().split(".")
    node: Any = law.load_spec() if parts[0] == "deeds" else jobs.spec()
    if parts[0] == "deeds":
        node["deeds"][parts[1]] = int(raw)
        return
    for part in parts[:-1]:
        if isinstance(node, list) or (isinstance(node, dict) and part.isdigit() and int(part) in node):
            node = node[int(part)]
        else:
            node = node[part]
    last = parts[-1]
    value: Any
    if "," in raw:
        # A list: `alarm.bands=quiet,uneasy,stirring,restless,roused`.
        value = [v.strip() for v in raw.split(",")]
    else:
        try:
            value = int(raw)
        except ValueError:
            try:
                value = float(raw)
            except ValueError:
                value = raw
    if isinstance(node, dict) and last.isdigit() and int(last) in node:
        node[int(last)] = value
    else:
        node[last] = value


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--seeds", type=int, default=40)
    parser.add_argument("--policy", choices=(*POLICIES, "all"), default="all")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--agendas", action="store_true",
                        help="measure with the story's agendas on (off by default; see above)")
    parser.add_argument("--set", action="append", default=[], metavar="KEY=VALUE",
                        help="try a number without editing the file (repeatable)")
    args = parser.parse_args(argv)

    import logging

    logging.disable(logging.WARNING)
    from engine.games import registry

    registry.activate("hue-and-cry")
    from scripts.simulate_law import _nothing, agendas_off

    with (_nothing() if args.agendas else agendas_off()):
        for assignment in args.set:
            _override(assignment)
        policies = POLICIES if args.policy == "all" else (args.policy,)
        reports = {p: measure(p, args.seeds) for p in policies}
    if args.json:
        print(json.dumps(reports, indent=2))
    else:
        print("\n\n".join(render(p, r) for p, r in reports.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
