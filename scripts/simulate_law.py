"""
The Law's Balance Harness
=========================

Play HUE & CRY headlessly with a scripted thief and report the numbers that
decide whether the Lantern Watch is tuned (AGENTS.md rule 10: balance
constants are set by measurement, not guessed).

THREE POLICIES, one city, the same seeds:

  careful   Buys a porter's smock from Dock Mag on day one and puts it on in
            an empty Wickmarket after the stalls close, with nobody there to
            see the change; it wears it from then on. From day two it spends
            its days in the Snuffs -- the ward no Lantern walks -- and lifts
            ONE purse there each night at 21:00, among the warehousemen
            drinking their wages.
  reckless  Walks into Wickmarket every afternoon in its own face, the hours
            the whole Watch buys its lunch there, and lifts up to
            ``RECKLESS_LIFTS`` purses, lingering an hour in the square after
            each one. It sleeps in the square.
  briber    The reckless thief, answering every stop with the Lantern's bribe
            whenever its purse covers the price, running otherwise.

Neither picks a Lantern's pocket, and both pick the least watchful mark on
offer: they differ in when, where and in whose face.

Careful and reckless answer a Lantern's stop the same way -- ``run`` -- so
the arrest count measures how often the Watch catches each, not a different
taste in surrender; the briber exists to show what coin buys. Held, a thief
pays the fine if it can and serves the days if not.

WHAT IS REAL AND WHAT IS NOT. Every lift, walk, purchase, guise change,
encounter approach, fine and sentence goes through
``tool_dispatcher.execute_intent`` -- the production channel a chosen option
takes -- so legality, witnesses, reports, cooling and confiscation are the
engine's own. The patrol runs once per action, after it, exactly as
``run_turn`` places it (and, as there, not on an action that answered an open
scene). Waiting and sleeping advance the clock through
``clock.advance_time``, the one writer of time. What is NOT the game: the
harness feeds the thief and restores its stamina each morning through the
``hunger`` and ``stamina`` effects, because HUE & CRY ships no food loop yet
and this harness measures the Law, not starvation. No narration runs.

AGENDAS ARE OFF HERE BY DEFAULT (v0.12). Since v0.12 the Magpie robs a
shining house most nights and each robbery lands on the thief's own name
(law.yaml `links`) -- so with agendas on, a thief who lifts nothing is
`sought` within five days, and "does a careful thief stay below sought" stops
measuring the thief. This harness measures what the thief's OWN conduct earns
from the Watch, so it runs with `paths.agendas` declared off
(``agendas_off``); ``--agendas`` runs it with the city's agendas on, and
scripts/simulate_agendas.py measures the two together.

Usage:
    python scripts/simulate_law.py                    # 40 seeds x 10 days, both
    python scripts/simulate_law.py --seeds 10 --days 5 --policy reckless
    python scripts/simulate_law.py --agendas          # with the Magpie and co. on
    python scripts/simulate_law.py --json

Version: v0.4.0 [2026-09-25]
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterator, Optional

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

#: The ward the reckless thief works and the one every table row reports on:
#: Wickmarket's, where the whole Watch walks at lunch.
BUSY_JURISDICTION = "wick"
BUSY_DISTRICT = "wickmarket"
QUIET_DISTRICT = "the_snuffs"
#: Purses the reckless thief tries each afternoon (one per mark per day is
#: the engine's rule; this is how many marks it bothers with).
RECKLESS_LIFTS = 3
#: The hour the reckless thief starts in the square: the Watch's lunch.
RECKLESS_HOUR = 13
#: The careful thief's hours: smock on in an empty market on night one; each
#: night after, one lift in the Snuffs.
CAREFUL_CHANGE_HOUR = 23
CAREFUL_LIFT_HOUR = 21
POLICIES = ("careful", "reckless", "briber")


@dataclass
class DayRow:
    day: int
    band: str               # the policy's worst band in the busy ward, end of day
    worst_band: str         # its worst band in any ward
    lifts: int = 0
    witnessed: int = 0
    reported: int = 0
    arrests: int = 0
    seconds: float = 0.0


@dataclass
class Run:
    seed: int
    policy: str
    days: list[DayRow] = field(default_factory=list)
    arrests: int = 0
    hp_after_sentence: list[int] = field(default_factory=list)
    stops: int = 0
    fines_paid: int = 0
    income: int = 0          # crowns lifted
    bribes: int = 0          # stops answered with coin
    bribe_gold: int = 0
    days_served: list[int] = field(default_factory=list)


@contextmanager
def agendas_off() -> Iterator[None]:
    """
    The active story with its agendas switched off, for the duration: no
    Magpie, no captain's net, no Silas -- the city as it played before v0.12.

    A harness switch, not a content one. ``agendas.declared`` answers False
    inside the block, and every agenda entry point asks it first (``begin``,
    the prompt blocks, the masks), so the pass never runs. It cannot be done
    by blanking ``paths.agendas`` in the config overlay: an empty ``paths.*``
    key is answered from the story's manifest (``engine/config.py``).
    """
    from engine.world import agendas

    declared = agendas.declared
    agendas.declared = lambda: False  # type: ignore[assignment]
    try:
        yield
    finally:
        agendas.declared = declared  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# The engine, driven the way a chosen option drives it
# ---------------------------------------------------------------------------


class Thief:
    """One run: a session, an action counter, and the patrol after each action."""

    def __init__(self, seed: int, policy: str) -> None:
        from engine.scenes.default_state import SessionStore

        self.session = SessionStore().create(seed=seed, llm_fn=lambda m, **k: "{}")
        self.state = self.session.engine.state
        self.run = Run(seed=seed, policy=policy)
        self.today: Optional[DayRow] = None

    # -- one action = one turn ---------------------------------------------

    def act(self, action: str, target: str = "") -> dict[str, Any]:
        """Run one intent, then the watch's turn, as ``run_turn`` orders them."""
        from engine.agents.tool_dispatcher import execute_intent
        from engine.game.intents import scene_owns_turn
        from engine.world import law

        scene_at_start = scene_owns_turn(self.state)
        intent = {"action": action, "target": target} if target else {"action": action}
        receipts = execute_intent(intent, self.session.engine)
        result = (receipts[0].get("result") if receipts else {}) or {}
        if not scene_at_start:
            self.patrol()
        return result if isinstance(result, dict) else {}

    def patrol(self) -> None:
        from engine.world import law

        if law.patrol(self.state) is not None:
            self.run.stops += 1
            self.answer_stop()

    def answer_stop(self) -> None:
        """Run -- or, for the briber, pay whenever the purse covers it. A failed run is the cells.

        Answers any open scene, not only the Lantern's stop: since v0.14 a
        night street can hand the walker one (data/encounters/streets.yaml).
        Every threat there offers `run` too, so the policy is the same; a
        scene with no `run` (the lamplighter) takes its first way out that
        needs no roll.
        """
        from engine.game import encounter
        from engine.world import law

        guard = 0
        while encounter.active(self.state) and guard < 6:
            guard += 1
            offered = self.legal_targets("encounter")
            if self.run.policy == "briber" and "bribe" in offered:
                before = self.state.stats.gold
                self.act("encounter", "bribe")
                self.run.bribes += 1
                self.run.bribe_gold += before - self.state.stats.gold
                continue
            if "run" in offered or not offered:
                self.act("encounter", "run")
                continue
            auto = [a["id"] for a in encounter.available_approaches(self.state) if a["auto"]]
            self.act("encounter", (auto or offered)[0])
        if law.in_custody(self.state):
            self.run.arrests += 1
            if self.today is not None:
                self.today.arrests += 1
            self.leave_custody()

    def leave_custody(self) -> None:
        from engine.world import law

        held = law.custody(self.state)
        if self.state.stats.gold >= int(held.get("fine") or 0):
            self.act("pay_fine")
            self.run.fines_paid += 1
        else:
            receipt = self.act("serve")
            self.run.hp_after_sentence.append(int(self.state.stats.hp))
            self.run.days_served.append(int(receipt.get("days") or 0))

    def legal_targets(self, action: str) -> list[str]:
        from engine.game import intents

        verb = intents.find_verb(intents.legal_intents(self.state), action)
        return [t for t, _label in (verb.options if verb else ())]

    # -- composite moves ----------------------------------------------------

    def wait_until(self, hour: int) -> None:
        """Advance the clock to the next ``hour`` o'clock (a wait, not a turn)."""
        from engine.game.clock import advance_time

        now = self.state.world_clock_hours
        target = (int(now // 24) * 24) + hour
        while target < now - 1e-9:
            target += 24
        if target - now > 1e-9:
            advance_time(self.state, target - now)

    def linger(self, hours: float = 1.0) -> None:
        """Stand about for an hour -- one turn, so the patrol gets its look."""
        from engine.game.clock import advance_time

        advance_time(self.state, hours)
        self.patrol()

    def walk(self, destination: str) -> None:
        from engine.game.locations import get_edge

        if self.state.location_id == destination:
            return
        from engine.game import encounter

        path = _route(self.state.location_id, destination)
        for step in path:
            if self.state.location_id != step and get_edge(self.state.location_id, step):
                self.act("travel", step)
                if encounter.active(self.state):
                    # A night street met the walker on arrival (v0.14).
                    self.answer_stop()
            if self.state.location_id != step:
                return  # held, or refused: the day's plan is over

    def lift_one(self) -> bool:
        """Lift the easiest legal mark. False when there is nobody to rob.

        Both thieves pick the least watchful pocket on offer (its role's
        alertness band), because neither is a fool about WHOSE purse -- they
        differ in when, where and in whose face.
        """
        from engine.game.intents import DIFFICULTY_BANDS
        from engine.world import npc_sim, thievery

        from engine.world import law

        roles = set(law.load_spec().get("roles") or [])

        def role_of(npc_id: str) -> str:
            presence = npc_sim.resolve_npc(self.state, npc_id)
            return presence.role if presence else ""

        # Nobody here picks a Lantern's own pocket: that is a different
        # policy (and a different joke).
        marks = [m for m in self.legal_targets("lift") if role_of(m) not in roles]
        if not marks:
            return False
        bands = list(DIFFICULTY_BANDS)

        def ease(npc_id: str) -> int:
            band = thievery.alertness_for(role_of(npc_id))
            return bands.index(band) if band in bands else len(bands)

        receipt = self.act("lift", min(marks, key=ease))
        if receipt.get("ok"):
            self.run.income += int(receipt.get("gold") or 0)
        if receipt.get("ok") and self.today is not None:
            self.today.lifts += 1
            self.today.witnessed += int(bool(receipt.get("seen_by")))
            self.today.reported += int(bool(receipt.get("reported")))
        return bool(receipt.get("ok"))

    def morning(self) -> None:
        """The harness's one liberty: the thief is fed and rested."""
        from engine.game.effects import apply_effect

        if self.state.hunger > 0:
            apply_effect(self.state, {"type": "hunger", "delta": -self.state.hunger})
        gap = self.state.stats.max_stamina - self.state.stats.stamina
        if gap > 0:
            apply_effect(self.state, {"type": "stamina", "delta": gap})


def _route(start: str, goal: str) -> list[str]:
    """Shortest walk over PUBLIC streets (no secret places), start excluded."""
    from collections import deque

    from engine.game.locations import LOCATIONS

    def neighbours(loc: str) -> list[str]:
        row = LOCATIONS.get(loc) or {}
        return sorted(
            n for n in (row.get("connections") or {})
            if not (LOCATIONS.get(n) or {}).get("secret")
        )

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


# ---------------------------------------------------------------------------
# Policies: one in-game day each
# ---------------------------------------------------------------------------


def _careful_day(thief: Thief, day: int) -> None:
    from engine.world import law

    if day == 1:
        # Dock Mag's crate is on the quay from 05:00: the smock is the first
        # thing a careful thief buys. It goes on in Wickmarket at 23:00, when
        # the stalls are shut and the square is empty -- a change of face
        # nobody sees links nothing -- and it stays on: a porter is a porter
        # all day. Day one is spent setting up, so it lifts nothing.
        thief.act("buy", "npc_dock_mag/porters_smock")
        thief.walk(BUSY_DISTRICT)
        thief.wait_until(CAREFUL_CHANGE_HOUR)
        if "porter" in thief.legal_targets("guise"):
            thief.act("guise", "porter")
        thief.walk(QUIET_DISTRICT)
        return
    # The day goes by in the Snuffs, where no Lantern walks; the lift is at
    # night, among the warehousemen drinking their wages.
    thief.walk(QUIET_DISTRICT)
    thief.wait_until(CAREFUL_LIFT_HOUR)
    if law.current_guise(thief.state) == "porter":
        thief.lift_one()


def _reckless_day(thief: Thief, day: int) -> None:
    thief.walk(BUSY_DISTRICT)
    thief.wait_until(RECKLESS_HOUR)
    for _ in range(RECKLESS_LIFTS):
        thief.lift_one()
        thief.linger(1.0)


DAYS: dict[str, Callable[[Thief, int], None]] = {
    "careful": _careful_day,
    "reckless": _reckless_day,
    # The reckless thief's day, answering every stop with coin when it can.
    "briber": _reckless_day,
}


def _worst_band(state: Any, jurisdictions: list[str]) -> str:
    from engine.world import law

    bands = law.load_spec()["wanted"]["bands"]
    guises = list(law.load_spec()["guises"])
    worst = 0
    for j in jurisdictions:
        for g in guises:
            worst = max(worst, bands.index(law.wanted_band(state, g, j) or bands[0]))
    return bands[worst]


def play(seed: int, policy: str, days: int) -> Run:
    """
    One run of ``days`` IN-GAME days. A row per in-game day, read at the next
    08:00. A sentence that swallows days fills them with the band read when
    the prisoner walks out (they were in a cell; nothing new was filed).
    """
    from engine.world import law

    thief = Thief(seed, policy)
    everywhere = list(law.load_spec()["jurisdictions"])
    played = 0
    while thief.state.world_day <= days:
        played += 1
        start = time.perf_counter()
        first_day = thief.state.world_day
        row = DayRow(day=first_day, band="", worst_band="")
        thief.today = row
        thief.morning()
        DAYS[policy](thief, played)
        # Sleep to the next 08:00: the day ends at breakfast.
        thief.wait_until(8)
        row.band = _worst_band(thief.state, [BUSY_JURISDICTION])
        row.worst_band = _worst_band(thief.state, everywhere)
        row.seconds = time.perf_counter() - start
        thief.run.days.append(row)
        for skipped in range(first_day + 1, min(thief.state.world_day - 1, days) + 1):
            thief.run.days.append(DayRow(day=skipped, band=row.band, worst_band=row.worst_band,
                                         seconds=0.0))
    thief.run.days = thief.run.days[:days]
    return thief.run


# ---------------------------------------------------------------------------
# The table
# ---------------------------------------------------------------------------


def summarise(runs: list[Run], days: int) -> dict[str, Any]:
    from engine.world import law

    bands = law.load_spec()["wanted"]["bands"]
    sought = bands.index("sought")
    wanted = bands.index("wanted")
    per_day = []
    for d in range(days):
        rows = [r.days[d] for r in runs if len(r.days) > d]
        lifts = sum(x.lifts for x in rows)
        per_day.append({
            "day": d + 1,
            "median_band": bands[int(statistics.median_low([bands.index(x.band) for x in rows]))],
            "witnessed": round(sum(x.witnessed for x in rows) / lifts, 2) if lifts else 0.0,
            "reported": round(sum(x.reported for x in rows) / lifts, 2) if lifts else 0.0,
            "seconds": round(statistics.mean([x.seconds for x in rows if x.seconds] or [0.0]), 3),
        })
    first_sought = []
    for r in runs:
        hit = next((x.day for x in r.days if bands.index(x.worst_band) >= sought), None)
        first_sought.append(hit)
    seed_days = [x for r in runs for x in r.days]
    below_sought = sum(bands.index(x.worst_band) < sought for x in seed_days) / len(seed_days)
    wanted_by_4 = sum(
        any(bands.index(x.band) >= wanted for x in r.days[:4]) for r in runs
    ) / len(runs)
    arrested = sum(r.arrests >= 1 for r in runs) / len(runs)
    hp = [h for r in runs for h in r.hp_after_sentence]
    reached = [d for d in first_sought if d is not None]
    return {
        "runs": len(runs),
        "per_day": per_day,
        "below_sought_seed_days": round(below_sought, 3),
        "wanted_by_day_4": round(wanted_by_4, 3),
        "first_sought_median_day": statistics.median_low(reached) if reached else None,
        "never_sought": sum(d is None for d in first_sought),
        "arrests_per_run": round(statistics.mean(r.arrests for r in runs), 2),
        "runs_with_an_arrest": round(arrested, 3),
        "stops_per_run": round(statistics.mean(r.stops for r in runs), 2),
        "min_hp_after_sentence": min(hp) if hp else None,
        "sentences_served": len(hp),
        "fines_paid": sum(r.fines_paid for r in runs),
        "max_days_served": max((d for r in runs for d in r.days_served), default=None),
        "bribes_per_run": round(statistics.mean(r.bribes for r in runs), 2),
        "bribe_share_of_income": (
            round(sum(r.bribe_gold for r in runs) / sum(r.income for r in runs), 3)
            if sum(r.income for r in runs) else 0.0
        ),
        "max_seconds_per_day": round(max(x.seconds for x in seed_days), 3),
    }


def measure(policy: str, seeds: int, days: int) -> dict[str, Any]:
    runs = [play(seed, policy, days) for seed in range(seeds)]
    return summarise(runs, days)


def render(policy: str, report: dict[str, Any]) -> str:
    lines = [f"{policy} ({report['runs']} seeds)",
             "| day | median band (wick) | witnessed | reported | s/day |",
             "|---|---|---|---|---|"]
    for row in report["per_day"]:
        lines.append(f"| {row['day']} | {row['median_band']} | {row['witnessed']:.2f} | "
                     f"{row['reported']:.2f} | {row['seconds']:.3f} |")
    lines.append(
        f"below sought on {report['below_sought_seed_days']:.0%} of seed-days; "
        f"wanted by day 4 on {report['wanted_by_day_4']:.0%} of seeds; "
        f"first sought median day {report['first_sought_median_day']} "
        f"({report['never_sought']} never); arrests/run {report['arrests_per_run']}, "
        f"runs with an arrest {report['runs_with_an_arrest']:.0%}; stops/run "
        f"{report['stops_per_run']}; min hp after a sentence {report['min_hp_after_sentence']} "
        f"({report['sentences_served']} served, longest {report['max_days_served']} days; "
        f"{report['fines_paid']} fines paid); bribes/run {report['bribes_per_run']}, "
        f"{report['bribe_share_of_income']:.0%} of lifted income; "
        f"slowest day {report['max_seconds_per_day']}s"
    )
    return "\n".join(lines)


def _override(assignment: str) -> None:
    """
    Patch one number in the LOADED law file, for this process only.

    A tuning aid: the file on disk is what ships, and every number in it is
    one this harness measured. ``wanted.thresholds=0,2,4,7,11`` takes a list.
    """
    from engine.world import law

    key, _, raw = assignment.partition("=")
    parts = key.strip().split(".")
    if parts[0] == "stop":
        # stop.<approach>.<key>=N patches the loaded watch_stop scene.
        from engine.game import encounter

        row = encounter.get_definition("watch_stop") or {}
        row["approaches"][parts[1]][parts[2]] = int(float(raw))
        return
    node: Any = law.load_spec()
    for part in parts[:-1]:
        node = node[int(part) if isinstance(node, list) else part]
    value: Any = [float(v) for v in raw.split(",")] if "," in raw else float(raw)
    if parts[0] == "deeds":
        value = int(value)
    last = parts[-1]
    if isinstance(node, dict) and last.isdigit() and int(last) in node:
        node[int(last)] = value
    else:
        node[last] = value


@contextmanager
def _nothing() -> Iterator[None]:
    yield


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--seeds", type=int, default=40)
    parser.add_argument("--days", type=int, default=10)
    parser.add_argument("--policy", choices=(*POLICIES, "all"), default="all")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--agendas", action="store_true",
                        help="measure with the story's agendas on (off by default; see above)")
    parser.add_argument(
        "--set", action="append", default=[], metavar="KEY=VALUE",
        help="try a number without editing the file: wanted.cool_per_day=0.75, "
             "recognise.sought=0.05, notice.base=0.5, deeds.pickpocket=2 (repeatable)",
    )
    args = parser.parse_args(argv)

    import logging

    logging.disable(logging.WARNING)
    from engine.games import registry

    registry.activate("hue-and-cry")
    with (_nothing() if args.agendas else agendas_off()):
        for assignment in args.set:
            _override(assignment)
        policies = POLICIES if args.policy == "all" else (args.policy,)
        reports = {p: measure(p, args.seeds, args.days) for p in policies}
    if args.json:
        print(json.dumps(reports, indent=2))
    else:
        print("\n\n".join(render(p, r) for p, r in reports.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
