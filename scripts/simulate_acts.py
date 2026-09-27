"""
The Acts Harness
================

Play HUE & CRY's Acts I-II headlessly with a thief who plays the spine ON
PURPOSE -- off the barge, into the Honest Company, through the city's houses
after the Magpie's trail, and across Captain Ardane's desk -- and report how
often, and by when, the reveal lands (AGENTS.md rule 10: v0.16's evidence gate
and the ``false_witness`` deed are set by measurement, not guessed).

ONE POLICY, parametrised by the barge choice:

  investigator  Takes the opening choice ``--opening a|b|c`` (run, talk, come
                quietly) and answers what it led to as every harness thief
                answers a stop or a cell (simulate_law.py: ``run``; held, pay
                the fine if it can, serve if not). Walks to the Snuffs and is
                handed the price of a set of lockpicks (``KIT_PURSE``, the
                careful burglar's liberty in simulate_jobs.py), bought at
                Marrow's yard at 18:00 -- the hour Mother Gannet holds court,
                so the initiation is dealt there and then, and answered
                roll-free (simulate_labour.py's ``ROLL_FREE``).
                From the next morning it WORKS THE TRAIL. By day
                (``CASE_FROM``-``CASE_UNTIL``) it cases the city's generated
                houses one after another, in a fixed walk of the districts
                (``TOUR``), each until casing can tell it nothing more -- the
                only way a player learns a house holds a clue ("something
                here doesn't belong", which a watch learns last). The moment
                a house gives that up, it burgles it simulate_jobs.py's
                careful way: wait for nobody home (watching the street's
                other houses meanwhile, as a player spends the wait), in by
                the best odds, every useful flashback, and walk away if the
                house is roused (``CLUE_TRIES`` tries at most for one house).
                Whenever it has something to show the Lantern House -- a clue
                carried out since it last stood at the desk with evidence at
                the gate (``gate``, read from the desk deck itself), or an
                alibi still open -- it walks to the front desk in the
                captain's hours (06-13, 18-23) and takes what the desk deals:
                it PRESENTS every alibi (there, or in the cells), and NAMES
                the suspect the desk offers -- the one its clues favour, the
                only one the desk will hear -- on the first offer. A wrong
                naming is followed by the owner's retry rule: the desk offers
                again only after a clue carried out since, never the same
                suspect, and the investigator names that one.

It never reads a clue's ``points_to``, nor who the Magpie is: the desk decides
what it may say, as it decides for a player. It never cases the four anchors
(the Hoard's great houses): a clue is never laid in one (clues.py), and a
player learns that by casing one to the end, which this harness does not pay
for. Once the Magpie is unmasked the run keeps its days -- the table reads
each morning to the last -- but stops investigating.

WHAT IS REAL AND WHAT IS NOT. Every walk, purchase, case, burgle, stage,
flashback, abort, encounter approach, fine and sentence goes through
``tool_dispatcher.execute_intent``, as simulate_jobs.py drives it (this reuses
its ``Burglar``); the opening goes through the three halves ``run_turn`` takes
it by (simulate_law.py's ``take_opening``). After every action the director
deals whatever hand is due, as ``run_turn`` places it
(``director.ensure_scene``: after the intent and the patrol), and the hand is
answered through the ``card`` verb -- the initiation and the interrogation
roll-free, the alibi presented, the name said. The quest machine runs after
every action, as the turn's end runs it. What is NOT the game, and says so,
exactly as simulate_jobs.py: the thief is fed and rested every few hours
(``Burglar.wait_until``), and is handed its kit's price on day one.

AGENDAS ARE ON HERE (unlike every earlier harness): the Magpie's robberies
are the spine -- they land on the thief's name, earn the alibis, and who the
Magpie is (``agenda_role``) is read only while the agendas are declared.
``--no-agendas`` is the control; it can never name rightly.

WHAT IT REPORTS, per opening, averaged over seeds:

  opening           passed / filed / stopped / arrested; days served in it
  arrests           runs arrested at least once; arrests and days served a run
  initiation        the day guild_initiated lands (and runs where it never did)
  clues             clues carried out by days 6, 10 and 12; houses cased
  evidence          the evidence meter each morning (histogram, 0-5)
  accusation        runs where the desk offered a name by day 12, and the
                    mean day; runs named rightly first time, on the retry,
                    and never; the day the unlink landed
  wrong naming      the wanted band in the Wick for your own face the moment
                    it was said (and just before), and runs stopped / arrested
                    in the 48 hours after, and to the run's end; and, since
                    real wrong namings are few, the band EVERY offered name
                    would have left your face in had it been wrong, at
                    false_witness severities 2, 3 and 4 -- and at 0, the
                    band it stood in when the name was offered (your heat in the
                    Wick at the offer, plus the severity: exact, since the
                    report lands whole on your own file)
  alibi             runs where an alibi opened, runs that presented one (at
                    the desk / in the cells)

``--gate N`` and ``--set deeds.false_witness=N`` try a number without editing
a file (the loaded desk deck's evidence gate; the loaded law file).

Usage:
    python scripts/simulate_acts.py                      # 40 seeds x 12 days, every opening
    python scripts/simulate_acts.py --opening c --seeds 10
    python scripts/simulate_acts.py --gate 2 --set deeds.false_witness=2
    python scripts/simulate_acts.py --json

Version: v0.1.0 [2026-09-27]
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.simulate_jobs import Burglar  # noqa: E402

OPENINGS = ("a", "b", "c")
DAYS = 12
#: The days the clue count is read at (the brief's 6, 10 and 12).
CLUE_CHECKPOINTS = (6, 10, 12)
#: simulate_jobs.py's careful purse: the lockpicks (15) and change.
KIT_PURSE = 20
KIT = ("lockpicks",)
MARROW_HOUR = 18
#: Casing by day: a watch begun before CASE_UNTIL ends by the evening.
CASE_FROM = 8
CASE_UNTIL = 21
#: The order the investigator walks the city in, the Snuffs first (where the
#: Company sleeps) and then outward. Anchors are never cased (above).
TOUR = ("the_snuffs", "wickmarket", "tallow_docks", "chandlers_rise", "silk_row",
        "gallows_green", "lantern_house", "margraves_hill")
#: Nights at most the investigator tries one clue house before it lets it be.
CLUE_TRIES = 3
DESK = "lantern_house"
DESK_DECK = "lantern_house_desk"
#: Captain Ardane's hours at her desk (npc_schedules.yaml; the desk deck's gate).
ARDANE_WINDOWS = ((6, 13), (18, 23))
#: How each hand is answered: the alibi presented and the name said first;
#: otherwise the roll-free answer every card carries (the initiation's,
#: simulate_labour.ROLL_FREE, and the interrogation's).
PREFERRED = ("present_it", "name_them")
ROLL_FREE = ("say_nothing", "carry_the_crates", "take_a_bow", "answer_straight",
             "sleep_on_it", "resolve")
SUSPECTS = ("npc_wren", "npc_silas", "npc_imelda")
#: The false_witness severities the offer-time reading is made at; 0 is the
#: band the accuser stood in at the offer, before any naming.
FALSE_WITNESS_SWEEP = (0, 2, 3, 4)
#: The window after a wrong naming the table reads stops and arrests in.
AFTER_HOURS = 48


@dataclass
class ActsRun:
    seed: int
    opening: str
    opening_row: dict[str, Any] = field(default_factory=dict)
    opening_days_served: int = 0
    initiated_day: Optional[int] = None
    clue_days: list[int] = field(default_factory=list)       # the day each clue was carried out
    houses_cased: int = 0
    clue_houses_known: int = 0
    clue_jobs: int = 0
    clue_jobs_caught: int = 0
    evidence_by_morning: list[int] = field(default_factory=list)  # day 1..DAYS, read at 08:00
    offered_day: Optional[int] = None                        # first day the desk offered a name
    offer_scores: list[float] = field(default_factory=list)  # your Wick heat at every offer
    namings: list[dict[str, Any]] = field(default_factory=list)
    unmasked_day: Optional[int] = None
    alibi_open_day: Optional[int] = None
    alibi_presented: list[str] = field(default_factory=list)  # "desk" / "cells", once each
    stop_hours: list[float] = field(default_factory=list)
    arrest_hours: list[float] = field(default_factory=list)
    days_served: list[int] = field(default_factory=list)
    min_hp: int = 99


class Investigator(Burglar):
    """simulate_jobs.py's burglar, with the director's hand dealt and answered every turn."""

    def __init__(self, seed: int, opening: str) -> None:
        super().__init__(seed, "careful")
        self.acts = ActsRun(seed=seed, opening=opening)
        self._answering = False
        self._desk_since = -1          # clues carried out when last at the desk
        self._tries: dict[str, int] = {}
        self._cased: set[str] = set()

    # -- one action = one turn, the hand dealt after it --------------------------

    def act(self, action: str, target: str = "") -> dict[str, Any]:
        from engine.game.quests import QuestEngine

        result = super().act(action, target)
        QuestEngine.evaluate(self.state, self.session.ledger)
        # Read before the hand is dealt too: an alibi can open and be
        # presented inside one action (a sentence served, then the desk).
        self._note()
        if not self._answering:
            self.look()
            self._note()
        return result

    def look(self) -> None:
        """``director.ensure_scene``, as run_turn calls it, and the hand answered."""
        from engine.content import director

        self._answering = True
        try:
            for _ in range(6):
                director.ensure_scene(self.state, ledger=self.session.ledger)
                if not director.active(self.state):
                    return
                for _ in range(10):
                    if not director.active(self.state):
                        break
                    self.answer_card()
        finally:
            self._answering = False

    def answer_card(self) -> None:
        from engine.content import director
        from engine.world import law

        card = director.current_card(self.state)
        card_id = card.id if card else ""
        offered = self.legal_targets("card")
        if not offered:
            director.end(self.state)
            return
        beat = next((b for b in PREFERRED if b in offered), None)
        beat = beat or next((b for b in ROLL_FREE if b in offered), offered[0])
        if card_id.startswith("D2_name_"):
            if self.acts.offered_day is None:
                self.acts.offered_day = int(self.state.world_day)
            # Your face's heat in the Wick at every offer, right or wrong: what
            # a false witness of severity N WOULD make of it is the band of
            # this plus N (``summarise``), so the band is read on every offer
            # and not only the few real wrong namings. Exact: the report is
            # filed at precision 1.0 on your own file, which it adds to whole
            # (a file's cooling never exceeds what it holds).
            self.acts.offer_scores.append(round(law.wanted_score(self.state, "self", "wick"), 3))
        before = self._wick_band()
        score_before = law.wanted_score(self.state, "self", "wick")
        wrong_before = len(self._wrong_flags())
        self.act("card", beat)
        if card_id.startswith("D2_name_") and beat == "name_them":
            right = bool(self.state.flags.get("magpie_unmasked"))
            self.acts.namings.append({
                "day": int(self.state.world_day),
                "hour": float(self.state.world_clock_hours),
                "suspect": card_id.removeprefix("D2_name_"),
                "right": right,
                "band_before": before,
                "band_after": self._wick_band(),
                # The score as well as the band: an accuser already `hunted`
                # stays `hunted`, and only the score shows that it paid.
                "score_before": score_before,
                "score_after": law.wanted_score(self.state, "self", "wick"),
                "worst_after": self._worst_self_band(),
                "retry": wrong_before > 0,
            })
            if right and self.acts.unmasked_day is None:
                self.acts.unmasked_day = int(self.state.world_day)
        if beat == "present_it" and self.state.flags.get("alibi_proven"):
            self.acts.alibi_presented.append("cells" if law.in_custody(self.state) else "desk")

    # -- the stop, the cell, and what the table reads ----------------------------

    def patrol(self) -> None:
        stops = self.run.stops
        super().patrol()
        if self.run.stops > stops:
            self.acts.stop_hours.append(float(self.state.world_clock_hours))

    def leave_custody(self) -> None:
        """The interrogation is dealt first -- the cell's first turn -- then the fine or the days."""
        from engine.world import law

        if not law.in_custody(self.state):
            return
        self.acts.arrest_hours.append(float(self.state.world_clock_hours))
        self.look()
        served = len(self.run.days_served)
        super().leave_custody()
        if len(self.run.days_served) > served:
            self.acts.days_served.append(self.run.days_served[-1])

    def _note(self) -> None:
        from engine.game.quests import evaluate_condition

        day = int(self.state.world_day)
        if self.acts.initiated_day is None and self.state.flags.get("guild_initiated"):
            self.acts.initiated_day = day
        if self.acts.alibi_open_day is None and evaluate_condition(
                self.state, {"alibi": {"agenda": "the_magpie", "open": True}}):
            self.acts.alibi_open_day = day
        self.acts.min_hp = min(self.acts.min_hp, int(self.state.stats.hp))

    def _wick_band(self) -> str:
        from engine.world import law

        return law.wanted_band(self.state, "self", "wick")

    def _worst_self_band(self) -> str:
        from engine.world import law

        bands = list(law.load_spec()["wanted"]["bands"])
        worst = max(bands.index(law.wanted_band(self.state, "self", j))
                    for j in law.load_spec()["jurisdictions"])
        return bands[worst]

    def _wrong_flags(self) -> list[str]:
        return [s for s in SUSPECTS
                if self.state.flags.get(f"wrongly_accused_{s.removeprefix('npc_')}")]

    # -- the trail ---------------------------------------------------------------

    def evidence(self) -> int:
        from engine.state.active import store_for

        return int(store_for(self.state).get("evidence") or 0)

    def clue_houses(self) -> list[dict[str, Any]]:
        """Houses whose watch said something here doesn't belong, the clue still inside."""
        from engine.world import clues, premises

        out = []
        for district in TOUR:
            for prem in premises.at(self.state, district):
                if (premises.CLUE_HINT in premises.known(self.state, str(prem["id"]))
                        and clues.in_house(self.state, prem)
                        and self._tries.get(str(prem["id"]), 0) < CLUE_TRIES):
                    out.append(prem)
        return out

    def next_to_case(self) -> Optional[dict[str, Any]]:
        from engine.world import premises

        here = self.state.location_id
        order = ([here] if here in TOUR else []) + [d for d in TOUR if d != here]
        for district in order:
            for prem in sorted(premises.at(self.state, district), key=lambda p: str(p["id"])):
                pid = str(prem["id"])
                if prem.get("anchor") or pid in self._cased:
                    continue
                if premises.unknown_ids(self.state, pid):
                    return prem
                self._cased.add(pid)
        return None

    def case_out(self, prem: dict[str, Any]) -> None:
        """Watch one house until it has nothing more to give, or the day is done."""
        from engine.world import law, premises

        pid = str(prem["id"])
        self.walk(str(prem["district"]))
        for _ in range(12):
            if (law.in_custody(self.state) or self.state.location_id != prem["district"]
                    or not CASE_FROM <= self.state.world_hour < CASE_UNTIL):
                return
            if pid not in self.legal_targets("case"):
                break
            self.act("case", pid)
        if not premises.unknown_ids(self.state, pid) and pid not in self._cased:
            self._finish_casing(pid)

    def burgle_clue_house(self, prem: dict[str, Any]) -> None:
        from engine.world import clues, law

        pid = str(prem["id"])
        self._tries[pid] = self._tries.get(pid, 0) + 1
        self.walk(str(prem["district"]))
        if self.state.location_id != prem["district"] or law.in_custody(self.state):
            return
        if not self.wait_until_empty(prem):
            return
        found = len(clues.found(self.state))
        self.acts.clue_jobs += 1
        row = self.burgle(prem, smart=True, walk_away=True)
        if row.outcome == "caught":
            self.acts.clue_jobs_caught += 1
        if len(clues.found(self.state)) > found:
            self.acts.clue_days.append(int(self.state.world_day))

    def wait_until_empty(self, prem: dict[str, Any]) -> bool:
        """Until nobody is home -- the careful burglar's wait, but spent the
        way a player spends it: watching the street's other houses while the
        casing hours last, an hour's loitering otherwise. False if the house
        is never empty inside a day."""
        from engine.world import law, premises

        pid = str(prem["id"])
        for _ in range(24):
            if law.in_custody(self.state) or self.state.location_id != prem["district"]:
                return False
            if premises.empty_now(self.state, pid):
                return True
            other = self._caseable_here(exclude=pid)
            if other and CASE_FROM <= self.state.world_hour < CASE_UNTIL - 1:
                before = self.state.world_clock_hours
                self.act("case", other)
                if self.state.world_clock_hours > before:
                    if not premises.unknown_ids(self.state, other):
                        self._finish_casing(other)
                    continue
            self.linger(1.0)
        return premises.empty_now(self.state, pid)

    def _caseable_here(self, exclude: str) -> str:
        offered = self.legal_targets("case")
        return next((p for p in sorted(offered) if p != exclude and p not in self._cased
                     and not self._is_anchor(p)), "")

    def _is_anchor(self, pid: str) -> bool:
        from engine.world import premises

        return bool((premises.get(self.state, pid) or {}).get("anchor"))

    def _finish_casing(self, pid: str) -> None:
        from engine.world import premises

        self._cased.add(pid)
        self.acts.houses_cased += 1
        if premises.CLUE_HINT in premises.known(self.state, pid):
            self.acts.clue_houses_known += 1

    # -- the desk ----------------------------------------------------------------

    def has_business_at_the_desk(self) -> bool:
        from engine.game.quests import evaluate_condition

        if self.state.flags.get("magpie_unmasked"):
            return evaluate_condition(self.state, {"alibi": {"agenda": "the_magpie", "open": True}})
        if evaluate_condition(self.state, {"alibi": {"agenda": "the_magpie", "open": True}}):
            return True
        clues_now = len(self.acts.clue_days)
        return self.evidence() >= gate() and clues_now > self._desk_since

    def visit_desk(self) -> None:
        """To the front desk in the captain's hours; the desk deals what it will."""
        from engine.world import law

        self._desk_since = len(self.acts.clue_days)
        self.walk(DESK)
        if self.state.location_id != DESK or law.in_custody(self.state):
            return
        hour = self.state.world_hour
        if not any(a <= hour < b for a, b in ARDANE_WINDOWS):
            nxt = next((a for a, b in ARDANE_WINDOWS if hour < a), ARDANE_WINDOWS[0][0])
            self.wait_until(nxt)
            self.look()   # a turn spent waiting at the desk

    # -- a day -------------------------------------------------------------------

    def work_the_day(self) -> None:
        from engine.world import law

        if law.in_custody(self.state):
            self.leave_custody()
        if self.has_business_at_the_desk():
            self.visit_desk()
        if self.state.flags.get("magpie_unmasked"):
            return
        for _ in range(12):
            if law.in_custody(self.state) or self.state.flags.get("magpie_unmasked"):
                return
            pending = self.clue_houses()
            if pending:
                self.burgle_clue_house(pending[0])
                if self.has_business_at_the_desk() and self._ardane_in_reach():
                    self.visit_desk()
                continue
            if not CASE_FROM <= self.state.world_hour < CASE_UNTIL:
                break
            prem = self.next_to_case()
            if prem is None:
                break
            self.case_out(prem)
        if self.has_business_at_the_desk() and self._ardane_in_reach():
            self.visit_desk()

    def _ardane_in_reach(self) -> bool:
        hour = self.state.world_hour
        return any(a <= hour < b - 1 for a, b in ARDANE_WINDOWS) or hour < ARDANE_WINDOWS[1][0]


_GATE: list[int] = []


def gate() -> int:
    """The evidence the desk asks before the captain hears a name, read off the loaded deck."""
    if not _GATE:
        found = _find_gates(_desk_raw())
        _GATE.append(min(found) if found else 0)
    return _GATE[0]


def _desk_raw() -> dict[str, Any]:
    from engine.content import deck

    path = deck._decks_dir() / f"{DESK_DECK}.yaml"
    return deck._read_deck(str(path), path.stat().st_mtime)


def _find_gates(node: Any, set_to: Optional[int] = None) -> list[int]:
    """Every ``{value: {name: evidence, min: N}}`` under ``node`` (optionally rewritten)."""
    out: list[int] = []
    if isinstance(node, dict):
        value = node.get("value")
        if isinstance(value, dict) and value.get("name") == "evidence" and "min" in value:
            if set_to is not None:
                value["min"] = set_to
            out.append(int(value["min"]))
        for child in node.values():
            out += _find_gates(child, set_to)
    elif isinstance(node, list):
        for child in node:
            out += _find_gates(child, set_to)
    return out


def set_gate(n: int) -> None:
    """Patch the LOADED desk deck's evidence gate, for this process only."""
    _find_gates(_desk_raw(), n)
    _GATE.clear()


def play(seed: int, opening: str, days: int = DAYS) -> ActsRun:
    from engine.game.effects import apply_effect
    from engine.world import law

    inv = Investigator(seed, opening)
    inv.morning()
    arrests = inv.run.arrests
    inv.take_opening(opening)
    inv.acts.opening_row = dict(inv.run.opening)
    inv.acts.opening_days_served = sum(inv.acts.days_served)
    if inv.run.arrests > arrests and not inv.acts.arrest_hours:
        inv.acts.arrest_hours.append(float(inv.state.world_clock_hours))
    apply_effect(inv.state, {"type": "gold", "delta": KIT_PURSE})
    inv.walk("the_snuffs")
    inv.wait_until(MARROW_HOUR)
    for item in KIT:
        if f"npc_marrow/{item}" in inv.legal_targets("buy"):
            inv.act("buy", f"npc_marrow/{item}")
    inv.look()
    # Day 1's morning was the barge: nothing carried out yet.
    inv.acts.evidence_by_morning.append(0)
    while True:
        inv.next_morning()
        today = int(inv.state.world_day)
        # A morning spent in a cell reads what the thief walked in with.
        while len(inv.acts.evidence_by_morning) < min(today, days):
            inv.acts.evidence_by_morning.append(inv.evidence())
        if today > days:
            break
        started = inv.state.world_clock_hours
        inv.work_the_day()
        if inv.state.world_clock_hours <= started + 1e-9:
            # A day with nothing left to do (the Magpie unmasked, or nothing
            # left to case) ends where it began, at 08:00: sleep through it.
            inv.wait_until(7)
    inv.acts.evidence_by_morning = inv.acts.evidence_by_morning[:days]
    inv.acts.min_hp = min(inv.acts.min_hp, int(inv.run.min_hp))
    return inv.acts


# ---------------------------------------------------------------------------
# The table
# ---------------------------------------------------------------------------


def _mean(values: list[float]) -> Optional[float]:
    return round(statistics.fmean(values), 2) if values else None


def _share(n: int, of: int) -> float:
    return round(n / of, 3) if of else 0.0


def summarise(runs: list[ActsRun], days: int) -> dict[str, Any]:
    from engine.world import law

    n = len(runs)
    bands = list(law.load_spec()["wanted"]["bands"])
    first_wrong = [next((x for x in r.namings if not x["right"]), None) for r in runs]
    wrongs = [(r, w) for r, w in zip(runs, first_wrong) if w is not None]

    def after(r: ActsRun, w: dict[str, Any], hours: list[float], window: Optional[float]) -> bool:
        return any(h > w["hour"] and (window is None or h <= w["hour"] + window) for h in hours)

    def band_counts(key: str) -> dict[str, int]:
        seen = [w[key] for _, w in wrongs]
        return {b: seen.count(b) for b in bands if seen.count(b)}

    all_wrong = [x for r in runs for x in r.namings if not x["right"]]
    return {
        "seeds": n,
        "days": days,
        "gate": gate(),
        "false_witness": int(law.load_spec()["deeds"]["false_witness"]),
        "opening": {
            "passed": _share(sum(bool(r.opening_row.get("passed")) for r in runs), n),
            "filed": _share(sum(bool(r.opening_row.get("reported")) for r in runs), n),
            "stopped": _share(sum(bool(r.opening_row.get("stopped")) for r in runs), n),
            "arrested": _share(sum(bool(r.opening_row.get("arrested")) for r in runs), n),
            "days_served_mean": _mean([float(r.opening_days_served) for r in runs]),
        },
        "arrested_runs": _share(sum(bool(r.arrest_hours) for r in runs), n),
        "arrests_per_run": _mean([float(len(r.arrest_hours)) for r in runs]),
        "days_served_per_run": _mean([float(sum(r.days_served)) for r in runs]),
        "stops_per_run": _mean([float(len(r.stop_hours)) for r in runs]),
        "initiated": _share(sum(r.initiated_day is not None for r in runs), n),
        "initiated_day": {str(d): sum(r.initiated_day == d for r in runs)
                          for d in sorted({r.initiated_day for r in runs
                                           if r.initiated_day is not None})},
        "houses_cased_per_run": _mean([float(r.houses_cased) for r in runs]),
        "clue_houses_known_per_run": _mean([float(r.clue_houses_known) for r in runs]),
        "clue_jobs_per_run": _mean([float(r.clue_jobs) for r in runs]),
        "clue_jobs_caught": _share(sum(r.clue_jobs_caught for r in runs),
                                   sum(r.clue_jobs for r in runs)),
        "clues_by_day": {str(d): _mean([float(sum(x <= d for x in r.clue_days)) for r in runs])
                         for d in CLUE_CHECKPOINTS},
        "clues_histogram_by_day": {
            str(d): {str(k): sum(sum(x <= d for x in r.clue_days) == k for r in runs)
                     for k in range(9) if any(sum(x <= d for x in r.clue_days) == k for r in runs)}
            for d in CLUE_CHECKPOINTS},
        "evidence_by_morning": [
            {str(v): sum(len(r.evidence_by_morning) > d and r.evidence_by_morning[d] == v
                         for r in runs)
             for v in range(6)
             if any(len(r.evidence_by_morning) > d and r.evidence_by_morning[d] == v
                    for r in runs)}
            for d in range(days)],
        "offered": _share(sum(r.offered_day is not None for r in runs), n),
        "offered_mean_day": _mean([float(r.offered_day) for r in runs if r.offered_day is not None]),
        "named": _share(sum(bool(r.namings) for r in runs), n),
        "right_first": _share(sum(bool(r.namings) and r.namings[0]["right"] for r in runs), n),
        "wrong_first": _share(sum(bool(r.namings) and not r.namings[0]["right"] for r in runs), n),
        "right_on_retry": _share(sum(len(r.namings) > 1 and r.namings[0]["right"] is False
                                     and any(x["right"] for x in r.namings[1:]) for r in runs), n),
        "retried": _share(sum(len(r.namings) > 1 for r in runs), n),
        "wrong_twice": _share(sum(sum(not x["right"] for x in r.namings) >= 2 for r in runs), n),
        "unmasked": _share(sum(r.unmasked_day is not None for r in runs), n),
        "unmasked_mean_day": _mean([float(r.unmasked_day) for r in runs
                                    if r.unmasked_day is not None]),
        "unmasked_by_day": {str(d): sum(r.unmasked_day is not None and r.unmasked_day <= d
                                        for r in runs) for d in (6, 8, 10, 12)},
        "wrong_namings": len(all_wrong),
        "wrong_band_before": band_counts("band_before"),
        "wrong_band_after": band_counts("band_after"),
        "wrong_worst_after": band_counts("worst_after"),
        "offers": sum(len(r.offer_scores) for r in runs),
        "if_wrong_by_severity": {
            str(sev): {b: sum(law.band_for(x + sev) == b for r in runs for x in r.offer_scores)
                       for b in bands
                       if any(law.band_for(x + sev) == b for r in runs for x in r.offer_scores)}
            for sev in FALSE_WITNESS_SWEEP},
        "wrong_all_band_after": {b: sum(x["band_after"] == b for x in all_wrong)
                                 for b in bands if any(x["band_after"] == b for x in all_wrong)},
        "after_wrong_stopped_48h": _share(sum(after(r, w, r.stop_hours, AFTER_HOURS)
                                              for r, w in wrongs), len(wrongs)),
        "after_wrong_arrested_48h": _share(sum(after(r, w, r.arrest_hours, AFTER_HOURS)
                                               for r, w in wrongs), len(wrongs)),
        "after_wrong_stopped": _share(sum(after(r, w, r.stop_hours, None) for r, w in wrongs),
                                      len(wrongs)),
        "after_wrong_arrested": _share(sum(after(r, w, r.arrest_hours, None) for r, w in wrongs),
                                       len(wrongs)),
        "alibi_opened": _share(sum(r.alibi_open_day is not None for r in runs), n),
        "alibi_open_mean_day": _mean([float(r.alibi_open_day) for r in runs
                                      if r.alibi_open_day is not None]),
        "alibi_presented": _share(sum(bool(r.alibi_presented) for r in runs), n),
        "alibi_presented_at": {door: sum(door in r.alibi_presented for r in runs)
                               for door in ("desk", "cells")},
        "min_hp": min((r.min_hp for r in runs), default=None),
    }


def measure(opening: str, seeds: int, days: int = DAYS) -> dict[str, Any]:
    return summarise([play(seed, opening, days) for seed in range(seeds)], days)


def render(opening: str, r: dict[str, Any]) -> str:
    o = r["opening"]
    label = {"a": "run", "b": "talk", "c": "come quietly"}.get(opening, opening)
    lines = [
        f"investigator, opening {opening} ({label}): {r['seeds']} seeds x {r['days']} days"
        f" (evidence gate {r['gate']}, false_witness {r['false_witness']})",
        f"  opening   passed {o['passed']:.0%}, filed {o['filed']:.0%}, stopped {o['stopped']:.0%},"
        f" arrested {o['arrested']:.0%}, days served {o['days_served_mean']}",
        f"  law       runs arrested {r['arrested_runs']:.0%}; arrests/run {r['arrests_per_run']};"
        f" days served/run {r['days_served_per_run']}; stops/run {r['stops_per_run']};"
        f" min hp {r['min_hp']}",
        f"  company   initiated {r['initiated']:.0%}, by day {r['initiated_day']}",
        f"  trail     houses cased/run {r['houses_cased_per_run']}, clue houses known/run"
        f" {r['clue_houses_known_per_run']}, clue jobs/run {r['clue_jobs_per_run']}"
        f" (caught {r['clue_jobs_caught']:.0%})",
        f"            clues by day {r['clues_by_day']}",
    ]
    for d, hist in r["clues_histogram_by_day"].items():
        lines.append(f"              day {d:>2}: {hist}")
    lines.append("  evidence each morning (value: runs)")
    for d, hist in enumerate(r["evidence_by_morning"], start=1):
        lines.append(f"              day {d:>2}: {hist}")
    lines += [
        f"  desk      a name offered {r['offered']:.0%} (mean day {r['offered_mean_day']});"
        f" named {r['named']:.0%}: right first {r['right_first']:.0%}, wrong first"
        f" {r['wrong_first']:.0%}, retried {r['retried']:.0%}, right on the retry"
        f" {r['right_on_retry']:.0%}, wrong twice {r['wrong_twice']:.0%}",
        f"            unmasked {r['unmasked']:.0%} (mean day {r['unmasked_mean_day']});"
        f" by day {r['unmasked_by_day']}",
        f"  wrong     {r['wrong_namings']} wrong namings; own face in the Wick, first wrong naming:"
        f" before {r['wrong_band_before']} -> after {r['wrong_band_after']};"
        f" worst anywhere after {r['wrong_worst_after']}; every wrong naming after"
        f" {r['wrong_all_band_after']}",
        f"            every name offered ({r['offers']}), had it been wrong, by false_witness"
        f" severity: {r['if_wrong_by_severity']}",
        f"            stopped within 48h {r['after_wrong_stopped_48h']:.0%}, arrested within 48h"
        f" {r['after_wrong_arrested_48h']:.0%}; to the run's end stopped"
        f" {r['after_wrong_stopped']:.0%}, arrested {r['after_wrong_arrested']:.0%}",
        f"  alibi     opened {r['alibi_opened']:.0%} (mean day {r['alibi_open_mean_day']}),"
        f" presented {r['alibi_presented']:.0%} {r['alibi_presented_at']}",
    ]
    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--seeds", type=int, default=40)
    parser.add_argument("--days", type=int, default=DAYS)
    parser.add_argument("--opening", choices=(*OPENINGS, "all"), default="all")
    parser.add_argument("--gate", type=int, default=None,
                        help="try the desk's evidence gate at N (the loaded deck only)")
    parser.add_argument("--no-agendas", action="store_true",
                        help="the control: no Magpie robbing (and so no right naming)")
    parser.add_argument("--set", action="append", default=[], metavar="KEY=VALUE",
                        help="a law number, as simulate_law.py: deeds.false_witness=2")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    import logging

    logging.disable(logging.WARNING)
    from engine.games import registry
    from scripts.simulate_law import _nothing, _override, agendas_off

    registry.activate("hue-and-cry")
    if args.gate is not None:
        set_gate(args.gate)
    with (agendas_off() if args.no_agendas else _nothing()):
        for assignment in args.set:
            _override(assignment)
        openings = OPENINGS if args.opening == "all" else (args.opening,)
        reports = {o: measure(o, args.seeds, args.days) for o in openings}
    if args.json:
        print(json.dumps(reports, indent=2))
    else:
        print("\n\n".join(render(o, r) for o, r in reports.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
