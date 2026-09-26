"""
The Great Houses Harness
========================

Play HUE & CRY headlessly with a thief who goes after the great houses --
the Magpie's Hoard, and the secrets the houses keep -- and report how often a
twelve-day run completes the Hoard and what blackmail pays (AGENTS.md rule
10: v0.15's guild economy is measured, not guessed).

ONE POLICY, the same seeds:

  hoarder  The simulate_jobs greedy thief's method -- lockpicks and smoke
           pellets from Marrow (four, on day one; another whenever it is
           out), the house cased until casing can tell it nothing more (by
           day and evening only, ``CASE_FROM``-``CASE_UNTIL``, so the
           watching never eats the night), flashbacks where the odds are
           poor, in at eleven at night, never walking away -- turned on
           the four anchors (the Treasury with a forged Margrave's Hill
           pass it makes at the Porters' Hall bench from makings bought at
           Pell Hollis's counter on day one -- ``PASS_TRIES`` attempts'
           worth, tried at the bench of a morning until one takes) one a
           night, easiest first (``ANCHORS``), a caught job tried again the
           next night. It keeps everything it carries out (a hoarder, not a
           fence). Of a morning, while either of the two secret places that
           hold a Hoard piece is unknown to it, it scrounges the streets
           whose hidden paths lead to them (``SCROUNGE``), two forages a
           morning, and it walks to a secret place the moment it knows the
           way. And the morning after it carries a house's secret out it
           squeezes: to the person's door at their hour (``SQUEEZES``),
           strikes the thread, and collects on the spot, which every
           squeeze allows at the hour it is struck at here. (The captain's
           squeeze is struck only while the Watch holds something on it;
           until then it is tried again each day.)

The Hoard is complete when all six pieces are carried at once
(``magpies_hoard_complete``); four are one burglary each, two are found by
standing in a secret place.

WHAT IS REAL AND WHAT IS NOT. Every purchase, walk, forage, case, burgle,
stage, flashback, bargain, discharge, encounter approach, fine and sentence
goes through ``tool_dispatcher.execute_intent``, as simulate_jobs.py drives
it (this reuses its ``Burglar``), and the quest machine runs after every
action as the turn's end runs it (``QuestEngine.evaluate``) -- which is how a
find in a secret place is made. What is NOT the game, and says so, exactly as
simulate_jobs.py: the thief is fed and rested every few hours
(``Burglar.wait_until``), and is handed the price of its kit on day one
(``KIT_PURSE``: the picks and four pellets; ``PASS_PURSE``: the pass's
makings), and is fed and rested before each attempt at the bench.
``--no-pass`` is the control without the pass. Agendas are OFF by default, for
simulate_jobs.py's reason (``--agendas`` turns them on; an agenda's robbery
never takes a Hoard piece in any case).

WHAT IT REPORTS, averaged over seeds:

  completed         share of runs that completed the Hoard by the last day,
                    and the mean day it was completed on
  pieces            mean pieces held at the end; per piece, the share of
                    runs holding it
  anchors           per anchor: runs that carried its score out, attempts
                    per run, caught share of attempts
  places_found      per secret place, the share of runs that found it
  squeezes          per blackmail thread: runs that held its secret, struck
                    it, collected it, and let it break; crowns collected, and
                    Watch reports the collection made go missing (the
                    captain's price is her files, not coin)
  blackmail_crowns  crowns a run collected from squeezes, mean

``--severity`` instead replays the claim docs make for the ``blackmail``
deed's severity (data/rules/law.yaml): one blackmail report filed up the
Rise at precision 1.0, then quiet days, at severities 1-4 -- alone, and
beside a lift seen up the Rise (a ``pickpocket`` report, precision 1.0) --
and prints the Rise's wanted band at the start of each day.

Usage:
    python scripts/simulate_hoard.py                  # 40 seeds x 12 days
    python scripts/simulate_hoard.py --seeds 10 --days 20
    python scripts/simulate_hoard.py --no-pass        # the control, without the Hill pass
    python scripts/simulate_hoard.py --severity
    python scripts/simulate_hoard.py --json

Version: v0.2.0 [2026-09-26]
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts import simulate_jobs  # noqa: E402
from scripts.simulate_jobs import Burglar  # noqa: E402

POLICIES = ("hoarder",)
DAYS = 12
#: Easiest first: the two tier-3 anchors, Vessaline House (4), the Treasury (5).
ANCHORS = ("prem_gannets_house", "prem_captains_office",
           "prem_vessaline_manor", "prem_margraves_treasury")
#: The secret place -> the Hoard piece found by standing in it.
FINDS = {"old_bell_tower": "mitre_of_saint_wick", "the_undercroft": "harbourmasters_chain"}
#: Streets whose hidden paths lead toward the finds (locations.yaml's header):
#: the Snuffs' grating (the Undercroft), Gallows Green's churchyard (the
#: tower), Wickmarket and the Rise (the Rooftop Road, from which the tower is
#: seen). Two a morning, in turn.
SCROUNGE = ("the_snuffs", "gallows_green", "wickmarket", "chandlers_rise")
FORAGES_A_MORNING = 2
#: Scrounging stops for the day at this hour: the evening is the job's.
SCROUNGE_UNTIL = 15
#: template -> (where the squeezed party receives, the hour it strikes AND
#: collects at) -- an hour inside both its `requires` and its
#: `discharge_requires` (data/rules/threads.yaml).
SQUEEZES = {
    "gannet_ious": ("the_snuffs", 12),
    "quill_light_crowns": ("margraves_hill", 14),
    "vessaline_memoir": ("silk_row", 16),
    "ardane_magpie_file": ("lantern_house", 18),
}
#: The picks (15) and four smoke pellets (4 each) at Marrow's prices, all
#: bought on day one.
KIT_PURSE = 31
KIT = ("lockpicks", "smoke_pellet", "smoke_pellet", "smoke_pellet", "smoke_pellet")
#: The forged Margrave's Hill pass (data/rules/jobs.yaml `tools`: -1 at the
#: Treasury's approach and door). Nobody sells one: it is made at the Porters'
#: Hall bench (data/recipes/workshop.yaml `forge_hill_pass`, hard, three
#: hours, a vellum offcut and candle ends -- 3 + 1 crowns at Pell Hollis's
#: counter). The hoarder buys the makings for ``PASS_TRIES`` attempts on day
#: one, as a player would, and is handed their price with its kit.
PASS_RECIPE = "forge_hill_pass"
PASS_ITEM = "forged_pass"
PASS_MAKINGS = ("vellum_offcut", "candle_ends")
PASS_TRIES = 5
PASS_PURSE = PASS_TRIES * (3 + 1)
PELL = "npc_pell_hollis"
PELL_HOUR = 8
#: No attempt at the bench is begun after this hour: the evening is the job's.
BENCH_UNTIL = 15
#: Casing is done between these hours: a two-hour watch started at 21:00
#: ends at the job's hour.
CASE_FROM = 8
CASE_UNTIL = 21
MARROW_HOUR = simulate_jobs.MARROW_HOUR
JOB_HOUR = simulate_jobs.GREEDY_HOUR
HOARD_FLAG = "magpies_hoard_complete"


@dataclass
class HoardRun:
    seed: int
    completed_day: Optional[int] = None
    pieces: list[str] = field(default_factory=list)
    carried: dict[str, int] = field(default_factory=dict)    # anchor -> 1 once robbed
    attempts: dict[str, int] = field(default_factory=dict)
    caught: dict[str, int] = field(default_factory=dict)
    found: dict[str, int] = field(default_factory=dict)      # place -> day found
    held: set[str] = field(default_factory=set)              # templates whose secret was held
    struck: set[str] = field(default_factory=set)
    collected: dict[str, int] = field(default_factory=dict)  # template -> crowns
    quashed: dict[str, int] = field(default_factory=dict)    # template -> reports lost
    broken: set[str] = field(default_factory=set)
    arrests: int = 0
    min_hp: int = 99
    pass_day: Optional[int] = None                           # the day the pass was made
    pass_tries: int = 0
    treasury_with_pass: int = 0                              # Treasury attempts carrying it


class Hoarder(Burglar):
    def __init__(self, seed: int, with_pass: bool = True) -> None:
        super().__init__(seed, "greedy")
        self.hoard = HoardRun(seed=seed)
        #: False is the CONTROL (``--no-pass``): v0.15's first measurement,
        #: made before the hoarder carried the Hill pass.
        self.with_pass = with_pass

    def act(self, action: str, target: str = "") -> dict[str, Any]:
        """Burglar's action, then the quest machine as a turn's end runs it."""
        from engine.game.quests import QuestEngine

        result = super().act(action, target)
        QuestEngine.evaluate(self.state, self.session.ledger)
        if self.hoard.completed_day is None and self.state.flags.get(HOARD_FLAG):
            self.hoard.completed_day = int(self.state.world_day)
        for place in FINDS:
            if place not in self.hoard.found and self.state.location_id == place:
                self.hoard.found[place] = int(self.state.world_day)
        return result

    # -- walking, secret ways included once known ------------------------------

    def walk_known(self, destination: str) -> None:
        from engine.game import encounter
        from engine.game.locations import get_edge

        for step in _route_known(self.state, self.state.location_id, destination):
            if self.state.location_id != step and get_edge(self.state.location_id, step):
                self.act("travel", step)
                if encounter.active(self.state):
                    self.answer_stop()
            if self.state.location_id != step:
                return

    def at_hour(self, place: str, hour: int) -> bool:
        """At ``place`` by ``hour`` today (or tomorrow, if it has passed)."""
        self.walk_known(place)
        if self.state.location_id != place:
            return False
        self.wait_until(hour)
        return self.state.location_id == place

    # -- the day's parts ---------------------------------------------------------

    def visit_finds(self) -> None:
        from engine.game.inventory import holds
        from engine.game.locations import is_known

        for place, piece in FINDS.items():
            if is_known(self.state, place) and not holds(self.state, piece):
                self.walk_known(place)

    def scrounge(self, day: int) -> None:
        from engine.game import foraging
        from engine.game.locations import is_known

        if all(is_known(self.state, p) for p in FINDS):
            return
        self.morning()   # the harness's liberty, before a morning in the gutters
        for n in range(FORAGES_A_MORNING):
            if self.state.world_hour >= SCROUNGE_UNTIL:
                return
            street = SCROUNGE[(2 * day + n) % len(SCROUNGE)]
            self.walk(street)
            if self.state.location_id != street:
                return
            nodes = self.legal_targets("forage")
            if nodes:
                self.act("forage", min(nodes, key=lambda x: (foraging.node_uses(self.state, x), x)))

    def squeeze(self) -> None:
        """Every squeeze whose secret is held and not yet struck: strike it and collect."""
        from engine.game import threads
        from engine.world import law

        for template, (place, hour) in sorted(SQUEEZES.items(), key=lambda kv: kv[1][1]):
            if not self._secret_held(template) or template in self.hoard.struck:
                continue
            self.hoard.held.add(template)
            if law.in_custody(self.state) or not self.at_hour(place, hour):
                continue
            if template not in self.legal_targets("bargain"):
                continue   # Ardane with nothing filed, or an hour missed
            self.act("bargain", template)
            mine = [t for t in threads.active(self.state) if t.get("template") == template]
            if not mine:
                continue
            self.hoard.struck.add(template)
            before = int(self.state.stats.gold)
            files = len(self.state.law.get("reports") or [])
            thread_id = str(mine[0]["id"])
            if thread_id in self.legal_targets("discharge"):
                self.act("discharge", thread_id)
                self.hoard.collected[template] = int(self.state.stats.gold) - before
                self.hoard.quashed[template] = files - len(self.state.law.get("reports") or [])

    def _secret_held(self, template: str) -> bool:
        from engine.world import jobs, premises

        for pid in ANCHORS:
            prem = premises.get(self.state, pid) or {}
            secret = str(prem.get("secret") or "")
            rows = premises.spec(str(prem.get("type") or "")).get("secrets") or []
            row = next((r for r in rows if str(r.get("id")) == secret), None)
            if row and str(row.get("thread") or "") == template:
                return bool(self.state.flags.get(jobs.secret_flag(pid, secret)))
        return False

    def next_anchor(self) -> Optional[dict[str, Any]]:
        from engine.world import jobs, premises

        for pid in ANCHORS:
            if pid not in jobs.robbed(self.state):
                return premises.get(self.state, pid)
        return None

    def case_by_evening(self, premise_id: str) -> None:
        """simulate_jobs' casing until casing can tell it nothing more -- but
        only by day and evening, so the watching never runs past the job's
        hour and into tomorrow."""
        from engine.world import law

        for _ in range(12):
            hour = self.state.world_hour
            if not CASE_FROM <= hour < CASE_UNTIL:
                return
            if law.in_custody(self.state) or premise_id not in self.legal_targets("case"):
                return
            self.act("case", premise_id)

    def forge_pass(self) -> None:
        """At the bench while there is no pass and there are makings, until BENCH_UNTIL."""
        from engine.game.inventory import holds
        from engine.world import law

        if not self.with_pass or holds(self.state, PASS_ITEM) or law.in_custody(self.state):
            return
        if not all(holds(self.state, m) for m in PASS_MAKINGS):
            return
        self.walk("the_snuffs")
        while (self.state.location_id == "the_snuffs" and not holds(self.state, PASS_ITEM)
               and self.state.world_hour < BENCH_UNTIL
               and PASS_RECIPE in self.legal_targets("craft")):
            self.morning()   # the harness's liberty, as before a morning in the gutters
            self.act("craft", PASS_RECIPE)
            self.hoard.pass_tries += 1
        if holds(self.state, PASS_ITEM) and self.hoard.pass_day is None:
            self.hoard.pass_day = int(self.state.world_day)

    def job(self) -> None:
        from engine.game.inventory import holds
        from engine.world import law

        prem = self.next_anchor()
        if prem is None or law.in_custody(self.state):
            return
        pid = str(prem["id"])
        if not holds(self.state, "smoke_pellet"):
            # Out of pellets (four were bought on day one): Marrow's yard
            # before the night's job.
            self.walk("the_snuffs")
            self.wait_until(MARROW_HOUR)
            if "npc_marrow/smoke_pellet" in self.legal_targets("buy"):
                self.act("buy", "npc_marrow/smoke_pellet")
        self.walk(str(prem["district"]))
        if self.state.location_id != prem["district"]:
            return
        self.case_by_evening(pid)
        if pid in self.legal_targets("case"):
            return   # more to learn about it: another evening's watching first
        self.wait_until(JOB_HOUR)
        if self.state.location_id != prem["district"] or law.in_custody(self.state):
            return
        self.hoard.attempts[pid] = self.hoard.attempts.get(pid, 0) + 1
        if pid == "prem_margraves_treasury" and holds(self.state, PASS_ITEM):
            self.hoard.treasury_with_pass += 1
        row = self.burgle(prem, smart=True, walk_away=False)
        if row.outcome == "caught":
            self.hoard.caught[pid] = self.hoard.caught.get(pid, 0) + 1
        if row.outcome in ("clean", "noisy"):
            self.hoard.carried[pid] = 1


def _route_known(state: Any, start: str, goal: str) -> list[str]:
    """simulate_law._route, with a secret place walkable once the player knows it."""
    from engine.game.locations import LOCATIONS, is_known

    def neighbours(loc: str) -> list[str]:
        row = LOCATIONS.get(loc) or {}
        return sorted(n for n in (row.get("connections") or {})
                      if not (LOCATIONS.get(n) or {}).get("secret") or is_known(state, n))

    prev: dict[str, Optional[str]] = {start: None}
    queue = deque([start])
    while queue:
        here = queue.popleft()
        if here == goal:
            break
        for n in neighbours(here):
            if n not in prev:
                prev[n] = here
                queue.append(n)
    if goal not in prev:
        return []
    path: list[str] = []
    node: Optional[str] = goal
    while node is not None and node != start:
        path.append(node)
        node = prev[node]
    return list(reversed(path))


def play(seed: int, days: int = DAYS, with_pass: bool = True) -> HoardRun:
    from engine.game.effects import apply_effect
    from engine.world import law

    h = Hoarder(seed, with_pass)
    h.morning()
    apply_effect(h.state, {"type": "gold",
                           "delta": KIT_PURSE + (PASS_PURSE if with_pass else 0)})
    if with_pass:
        # Pell's counter for the makings, then the bench until mid-afternoon.
        h.walk("wickmarket")
        if h.state.world_hour < PELL_HOUR:
            h.wait_until(PELL_HOUR)
        for _ in range(PASS_TRIES):
            for making in PASS_MAKINGS:
                h.act("buy", f"{PELL}/{making}")
        h.forge_pass()
        h.walk("the_snuffs")
        if h.state.world_hour < MARROW_HOUR:
            h.wait_until(MARROW_HOUR)
    else:
        h.walk("the_snuffs")
        h.wait_until(MARROW_HOUR)
    for item in KIT:
        h.act("buy", f"npc_marrow/{item}")
    played = 1
    while h.state.world_day <= days:
        started = h.state.world_clock_hours
        if law.in_custody(h.state):
            h.leave_custody()
        h.visit_finds()
        h.squeeze()
        h.forge_pass()
        h.scrounge(played)
        h.visit_finds()
        h.job()
        # A secret carried out tonight is squeezed tomorrow, first thing: the
        # thread is struck the day it is held, well inside its two days.
        h.next_morning()
        if h.state.world_clock_hours <= started + 1e-9:
            # A day with nothing left to do ends where it began, at 08:00:
            # sleep through it to tomorrow's.
            h.wait_until(7)
            h.next_morning()
        played += 1
    return _close(h)


def _close(h: Hoarder) -> HoardRun:
    from engine.game import threads
    from engine.game.inventory import holds

    run = h.hoard
    run.pieces = [p for p in _pieces() if holds(h.state, p)]
    for t in h.state.threads:
        if t.get("template") in SQUEEZES and t.get("status") == threads.STATUS_BROKEN:
            run.broken.add(str(t["template"]))
    run.arrests = int(h.run.arrests)
    run.min_hp = int(h.run.min_hp)
    return run


def _pieces() -> list[str]:
    from engine.game.inventory import load_collections

    row = next(c for c in load_collections() if c.get("id") == "magpies_hoard")
    return [str(i) for i in row["items"]]


# ---------------------------------------------------------------------------
# The table
# ---------------------------------------------------------------------------


def _mean(values: list[float]) -> float:
    return round(statistics.fmean(values), 2) if values else 0.0


def _share(n: int, of: int) -> float:
    return round(n / of, 3) if of else 0.0


def summarise(runs: list[HoardRun], days: int) -> dict[str, Any]:
    n = len(runs)
    done = [r.completed_day for r in runs if r.completed_day is not None]
    return {
        "seeds": n,
        "days": days,
        "completed": _share(len(done), n),
        "completed_mean_day": _mean([float(d) for d in done]) if done else None,
        "pieces_mean": _mean([float(len(r.pieces)) for r in runs]),
        "pieces_histogram": {str(k): sum(len(r.pieces) == k for r in runs) for k in range(7)},
        "pieces": {p: _share(sum(p in r.pieces for r in runs), n) for p in _pieces()},
        "anchors": {
            pid: {
                "carried_out": _share(sum(r.carried.get(pid, 0) for r in runs), n),
                "attempts_per_run": _mean([float(r.attempts.get(pid, 0)) for r in runs]),
                "caught_share": _share(sum(r.caught.get(pid, 0) for r in runs),
                                       sum(r.attempts.get(pid, 0) for r in runs)),
            }
            for pid in ANCHORS
        },
        "places_found": {
            place: {
                "share": _share(sum(place in r.found for r in runs), n),
                "mean_day": _mean([float(r.found[place]) for r in runs if place in r.found]),
            }
            for place in FINDS
        },
        "squeezes": {
            t: {
                "held": _share(sum(t in r.held for r in runs), n),
                "struck": _share(sum(t in r.struck for r in runs), n),
                "collected": _share(sum(t in r.collected for r in runs), n),
                "broken": _share(sum(t in r.broken for r in runs), n),
                "crowns_when_collected": _mean([float(r.collected[t]) for r in runs
                                                if t in r.collected]),
                "reports_quashed_when_collected": _mean([float(r.quashed[t]) for r in runs
                                                         if t in r.quashed]),
            }
            for t in SQUEEZES
        },
        "blackmail_crowns": _mean([float(sum(r.collected.values())) for r in runs]),
        "arrests_per_run": _mean([float(r.arrests) for r in runs]),
        "pass_made": _share(sum(r.pass_day is not None for r in runs), n),
        "pass_mean_day": _mean([float(r.pass_day) for r in runs if r.pass_day is not None]),
        "pass_tries_per_run": _mean([float(r.pass_tries) for r in runs]),
        "treasury_tries_with_pass": _share(
            sum(r.treasury_with_pass for r in runs),
            sum(r.attempts.get("prem_margraves_treasury", 0) for r in runs)),
        "min_hp": min((r.min_hp for r in runs), default=None),
    }


def measure(seeds: int, days: int = DAYS, with_pass: bool = True) -> dict[str, Any]:
    report = summarise([play(seed, days, with_pass) for seed in range(seeds)], days)
    report["with_pass"] = with_pass
    return report


def render(report: dict[str, Any]) -> str:
    label = "hoarder" if report.get("with_pass", True) else "hoarder --no-pass (control)"
    lines = [f"{label}: {report['seeds']} seeds x {report['days']} days",
             f"  Hoard completed      {report['completed']:.0%} of runs"
             f" (mean day {report['completed_mean_day']})",
             f"  pieces held, mean    {report['pieces_mean']}  {report['pieces_histogram']}"]
    for piece, share in report["pieces"].items():
        lines.append(f"    {piece:24} {share:.0%}")
    lines.append("  anchors (carried out / attempts a run / caught share)")
    for pid, r in report["anchors"].items():
        lines.append(f"    {pid:26} {r['carried_out']:.0%} / {r['attempts_per_run']}"
                     f" / {r['caught_share']:.0%}")
    lines.append("  secret places found (share, mean day)")
    for place, r in report["places_found"].items():
        lines.append(f"    {place:26} {r['share']:.0%}  day {r['mean_day']}")
    lines.append("  squeezes (held / struck / collected / broken, crowns, reports quashed)")
    for t, r in report["squeezes"].items():
        lines.append(f"    {t:26} {r['held']:.0%} / {r['struck']:.0%} / {r['collected']:.0%}"
                     f" / {r['broken']:.0%}, {r['crowns_when_collected']} cr,"
                     f" {r['reports_quashed_when_collected']} reports")
    lines.append(f"  Hill pass made {report['pass_made']:.0%} (mean day {report['pass_mean_day']},"
                 f" {report['pass_tries_per_run']} tries a run); carried on"
                 f" {report['treasury_tries_with_pass']:.0%} of Treasury tries")
    lines.append(f"  blackmail crowns a run {report['blackmail_crowns']};"
                 f" arrests a run {report['arrests_per_run']}; min hp {report['min_hp']}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# --severity: the blackmail deed's weight, replayed
# ---------------------------------------------------------------------------


def severity_sweep(severities: tuple[int, ...] = (1, 2, 3, 4),
                   days: int = 7) -> dict[str, dict[str, list[str]]]:
    """
    One blackmail report filed up the Rise at precision 1.0 (what a squeeze's
    ``on_break`` files), then quiet days: the Rise's wanted band for the
    player's own face at the start of each day, day 0 the moment it is
    filed. ``alone``, and ``beside_a_lift``: the same, with one lift seen up
    the Rise filed beside it (a ``pickpocket`` report, precision 1.0).
    The severity is patched in the LOADED law file for this process only.
    """
    from engine.game.clock import advance_time
    from engine.game.effects import apply_effect
    from engine.world import law
    from scripts.simulate_law import Thief

    shipped = law.load_spec()["deeds"]["blackmail"]
    out: dict[str, dict[str, list[str]]] = {}
    try:
        for severity in severities:
            law.load_spec()["deeds"]["blackmail"] = severity
            row: dict[str, list[str]] = {}
            for label, extra in (("alone", False), ("beside_a_lift", True)):
                state = Thief(0, "severity").state
                apply_effect(state, {"type": "report", "deed": "blackmail", "guise": "self",
                                     "jurisdiction": "rise", "precision": 1.0})
                if extra:
                    apply_effect(state, {"type": "report", "deed": "pickpocket",
                                         "guise": "self", "jurisdiction": "rise",
                                         "precision": 1.0})
                bands = [law.wanted_band(state, "self", "rise")]
                for _ in range(days):
                    advance_time(state, 24.0)
                    bands.append(law.wanted_band(state, "self", "rise"))
                row[label] = bands
            out[str(severity)] = row
    finally:
        law.load_spec()["deeds"]["blackmail"] = shipped
    return out


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--seeds", type=int, default=40)
    parser.add_argument("--days", type=int, default=DAYS)
    parser.add_argument("--no-pass", action="store_true",
                        help="the control: no forged Hill pass (v0.15's first measurement)")
    parser.add_argument("--agendas", action="store_true",
                        help="measure with the story's agendas on (off by default)")
    parser.add_argument("--severity", action="store_true",
                        help="replay the blackmail deed's severity measurement instead")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    import logging

    logging.disable(logging.WARNING)
    from engine.games import registry
    from scripts.simulate_law import _nothing, agendas_off

    registry.activate("hue-and-cry")
    if args.severity:
        # Agendas always off here: the Magpie's robberies file on the
        # player's name and would be read as the squeeze's weight.
        with agendas_off():
            sweep = severity_sweep()
        if args.json:
            print(json.dumps(sweep, indent=2))
        else:
            for severity, row in sweep.items():
                for label, bands in row.items():
                    print(f"severity {severity} {label:14} " + " ".join(bands))
        return 0
    with (_nothing() if args.agendas else agendas_off()):
        report = measure(args.seeds, args.days, not args.no_pass)
    print(json.dumps(report, indent=2) if args.json else render(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
