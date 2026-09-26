"""
The Cost-of-Living Harness
==========================

Play HUE & CRY headlessly with four ways of getting by, each paying for its
own bread and bed, and report how many days each one actually keeps (AGENTS.md
rule 10: labour pay is set by measurement, not guessed). It is also the
reproducible cost-of-living measurement v0.14's survival task took from a
scratch script: every policy here eats and sleeps on its own coin, and the
harness never feeds it or restores its stamina.

FOUR POLICIES, the same seeds, the same rules of living:

  porter     Honest work and nothing else. Up at six, on the quay by seven
             for Dock Mag's gangs (`dock_portering`, six hours), then over to
             Wickmarket to go round the lamps with Wren at dusk
             (`lamplighting`) -- the day's two shifts (labour.yaml
             `shifts_per_day`). It never lifts a purse.
  dipper     The other honest day: bread on the quay, then the vats at Marsh &
             Daughters on Chandlers' Rise (`candle_dipping`, six hours), then
             the Wickmarket stalls' errands until they shut
             (`market_errands`).
  careful    simulate_law's careful pickpocket: the porter's smock on day one,
             then one purse a night in the Snuffs at 21:00, the goods sold to
             Marrow across the yard the same hour. Stops are run from, and a
             fine is paid if the purse covers it.
  scrounger  simulate_scrounge's scrounger: four streets a day, what it finds
             eaten or sold. It never steals and never works.

AND TWO MORE, the careful pickpocket on credit (v0.15, the fences' credit,
data/rules/threads.yaml) -- the same day, the same purse, plus one line of
credit it runs whenever a fence will stand it one and its purse is under
``CREDIT_WHEN_BELOW``, and repays at her counter the moment it holds the
debt:

  careful_pell    Pell Hollis's advance (ten crowns, thirteen back inside
                  three days): after breakfast on the quay, on a day it has
                  business with her (a debt open, or a lean purse), it goes
                  by her counter in Wickmarket, buys its bread there, then
                  on to the Snuffs as before.
  careful_marrow  Marrow's slate (five crowns, eight back inside two), at
                  her yard in the Snuffs after the night's sale, on a day it
                  has business with her.

``--no-credit`` runs them as their own control: the same lean-purse days at
her counter, the same bread bought there, and no line ever struck -- because
a detour past a food counter feeds a careful pickpocket by itself (the plain
``careful`` policy passes none after breakfast), the credit's own effect is
the difference between a credit policy and its control, not between it and
``careful``.

A debt it cannot find by the due day breaks: the word goes round, and NO
fence buys from it or stands it credit again, and that fence's collectors
walk the streets for it (streets.yaml `pells_collectors`, `marrows_lads`,
and by day in the fences' districts `..._by_day`) -- counted in
``collectors_met``. It never sets the
advance aside to repay it: a purses-only earner (~1.4 cr a day against
~1.6 of bread and bed) could repay only by not spending the advance at
all, which leaves it exactly where the control is, three crowns poorer.

THE RULES OF LIVING, the same for all four. Whenever it stands at a food
counter it buys the cheapest food until it carries ``STOCK`` meals (one crown
each, while it has the crowns); it eats a carried meal whenever hunger reaches
``EAT_AT``; and it sleeps in the Snuffs in the bed ``--bed`` names --
``flophouse`` (Old Nance's, 1 cr; the default, because bread plus a flophouse
bed is the cost of living the labour table was tuned against), ``bunk`` (the
Porters' Hall, free while the Honest Company has no quarrel with you) or
``rough``. A bed it cannot pay for is a rough night (survival.yaml's
fallback), never a refusal.

Every walk, shift, lift, sale, purchase, meal and night goes through
``tool_dispatcher.execute_intent``, the production channel a chosen option
takes, exactly as scripts/simulate_law.py drives its thief (this reuses its
``Thief`` and patrol, and runs with agendas off for the same reason: the
Magpie robbing on your name measures the Magpie; ``--agendas`` turns them on).

WHAT IT REPORTS, per policy, averaged over seeds:

  earned_per_day   crowns in: wages, lifted coin, sales
  food_per_day     crowns spent on food
  bed_per_day      crowns spent on beds
  fed_days         share of days that ended below `hungry`
  bed_nights       share of nights under a roof (a paid or granted bed)
  kept_days        share of days that were both -- the "days sustainable"
  saved_per_day    crowns in hand at the end less the purse it started with
  end_gold         crowns in hand at the end, mean (and min)
  min_hp           the lowest hp any seed reached
  runs_at_zero_hp  the share of seeds whose hp reached 0 (no respawn until
                   v0.17's death.yaml: CLAUDE.md)
  arrests          mean per run
  credit_struck    lines of credit struck, mean per run (the credit policies)
  credit_repaid    of those, the share paid off
  credit_broken    of those, the share that came due unpaid
  collectors_met   times a fence's collectors met it on the street, per run
  collectors_hp_lost  hp those meetings cost it, per run

Usage:
    python scripts/simulate_labour.py                    # 40 seeds x 10 days, all four
    python scripts/simulate_labour.py --policy porter --bed bunk
    python scripts/simulate_labour.py --policy careful_pell
    python scripts/simulate_labour.py --policy careful_pell --no-credit   # its control
    python scripts/simulate_labour.py --json

Version: v0.2.1 [2026-09-26]
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, Optional

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts import simulate_law, simulate_scrounge  # noqa: E402
from scripts.simulate_law import Thief, agendas_off  # noqa: E402
from scripts.simulate_scrounge import Scrounger  # noqa: E402

POLICIES = ("porter", "dipper", "careful", "scrounger", "careful_pell", "careful_marrow")
BEDS = {"flophouse": "sleep_flophouse", "bunk": "sleep_guild_bunk", "rough": "sleep_rough"}
HOME = "the_snuffs"
DOCKS = "tallow_docks"
MARKET = "wickmarket"
RISE = "chandlers_rise"
#: Meals carried after a visit to a food counter, while the purse allows.
STOCK = 2
#: Hunger at which a carried meal is eaten (survival.yaml: hungry at 60).
EAT_AT = 50.0
WAKE_HOUR = 6
DUSK_HOUR = 18
#: Things a policy never sells: the careful thief's guise, and food.
KEEP = ("porters_smock",)
ROOFED = ("sleep_flophouse", "sleep_guild_bunk", "sleep_tavern")
#: The credit policies strike a line only while the purse is under this: a
#: day's bread and a flophouse bed (~1.6 cr, CHANGELOG [0.14.0]) and change.
CREDIT_WHEN_BELOW = 3
#: The street scenes that come for a welsher (data/encounters/streets.yaml).
COLLECTORS = ("pells_collectors", "marrows_lads",
              "pells_collectors_by_day", "marrows_lads_by_day")


@dataclass
class Life:
    seed: int
    policy: str
    bed: str
    days: int = 0
    money: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    shifts: int = 0
    wages: int = 0
    fed_days: int = 0
    bed_nights: int = 0
    kept_days: int = 0
    min_hp: int = 999
    min_stamina: int = 999
    start_gold: int = 0
    end_gold: int = 0
    arrests: int = 0
    credit_struck: int = 0
    credit_repaid: int = 0
    credit_broken: int = 0
    collectors_met: int = 0
    collectors_hp: int = 0


class Living:
    """Pays its own way: the purchases, meals and beds all four policies share."""

    state: Any
    session: Any
    life: Life

    # -- one action = one turn, with the coin it moved booked to its verb ----

    def act(self, action: str, target: str = "") -> dict[str, Any]:
        """``Thief.act``, with the gold each intent moved booked before the patrol runs."""
        from engine.agents.tool_dispatcher import execute_intent
        from engine.game.intents import scene_owns_turn

        scene_at_start = scene_owns_turn(self.state)
        before = int(self.state.stats.gold)
        intent = {"action": action, "target": target} if target else {"action": action}
        receipts = execute_intent(intent, self.session.engine)
        self.life.money[action] += int(self.state.stats.gold) - before
        result = (receipts[0].get("result") if receipts else {}) or {}
        if not scene_at_start:
            self.patrol()  # type: ignore[attr-defined]
        return result if isinstance(result, dict) else {}

    def note(self) -> None:
        stats = self.state.stats
        self.life.min_hp = min(self.life.min_hp, int(stats.hp))
        self.life.min_stamina = min(self.life.min_stamina, int(stats.stamina))

    # -- food ----------------------------------------------------------------

    def meals_carried(self) -> int:
        from engine.game import inventory

        return sum(e.qty for e in self.state.inventory if inventory.has_tag(e.id, "food"))

    def provision(self) -> None:
        """Stock up at a food counter if one is open here, then eat if hungry."""
        from engine.game import inventory

        guard = 0
        while self.meals_carried() < STOCK and guard < 4:
            guard += 1
            food = [t for t in self.legal_targets("buy")  # type: ignore[attr-defined]
                    if inventory.has_tag(t.partition("/")[2], "food")]
            if not food:
                break
            cheapest = min(food, key=lambda t: (inventory.value_of(t.partition("/")[2]), t))
            before = self.state.stats.gold
            self.act("buy", cheapest)
            if self.state.stats.gold >= before:
                break  # could not pay
        self.eat()

    def eat(self) -> None:
        from engine.game import inventory

        guard = 0
        while self.state.hunger >= EAT_AT and guard < 6:
            guard += 1
            food = self.legal_targets("eat")  # type: ignore[attr-defined]
            if not food:
                break
            self.act("eat", min(food, key=lambda i: (inventory.value_of(i), i)))
        self.note()

    def sell_goods(self) -> None:
        from engine.game import inventory

        guard = 0
        while guard < 40:
            guard += 1
            targets = [t for t in self.legal_targets("sell")  # type: ignore[attr-defined]
                       if not inventory.has_tag(t.partition("/")[2], "food")
                       and t.partition("/")[2] not in KEEP]
            if not targets:
                return
            before = self.state.stats.gold
            self.act("sell", targets[0])
            if self.state.stats.gold <= before:
                return

    # -- the end of the day --------------------------------------------------

    def night(self) -> None:
        """Home to the Snuffs, a last meal, the day booked, and a bed."""
        from engine.game import survival

        self.walk(HOME)  # type: ignore[attr-defined]
        self.eat()
        self.life.days += 1
        fed = survival.hunger_stage(self.state) not in ("hungry", "starving")
        receipt = self.act("rest", BEDS[self.life.bed])
        roofed = str(receipt.get("kind") or "") in ROOFED
        self.life.fed_days += int(fed)
        self.life.bed_nights += int(roofed)
        self.life.kept_days += int(fed and roofed)
        self.note()

    def work(self, job_id: str) -> None:
        if job_id not in self.legal_targets("work"):  # type: ignore[attr-defined]
            return
        before = self.state.stats.gold
        receipt = self.act("work", job_id)
        if receipt.get("worked"):
            self.life.shifts += 1
            self.life.wages += int(self.state.stats.gold) - before


class Porter(Living, Thief):
    def __init__(self, seed: int, bed: str) -> None:
        Thief.__init__(self, seed, "porter")
        self.life = Life(seed=seed, policy="porter", bed=bed)

    def day(self, played: int) -> None:
        if self.state.world_hour < WAKE_HOUR:
            self.wait_until(WAKE_HOUR)
        self.walk(DOCKS)
        self.provision()
        self.work("dock_portering")
        self.provision()
        self.walk(MARKET)
        self.eat()
        if self.state.world_hour < DUSK_HOUR:
            self.wait_until(DUSK_HOUR)
        self.work("lamplighting")
        self.provision()


class Dipper(Living, Thief):
    def __init__(self, seed: int, bed: str) -> None:
        Thief.__init__(self, seed, "dipper")
        self.life = Life(seed=seed, policy="dipper", bed=bed)

    def day(self, played: int) -> None:
        if self.state.world_hour < WAKE_HOUR:
            self.wait_until(WAKE_HOUR)
        self.walk(DOCKS)
        self.provision()
        self.walk(RISE)
        self.work("candle_dipping")
        self.walk(MARKET)
        self.provision()
        self.work("market_errands")
        self.provision()


class Careful(Living, Thief):
    def __init__(self, seed: int, bed: str) -> None:
        Thief.__init__(self, seed, "careful")
        self.life = Life(seed=seed, policy="careful", bed=bed)

    def day(self, played: int) -> None:
        if self.state.world_hour < WAKE_HOUR:
            self.wait_until(WAKE_HOUR)
        # Breakfast is on the quay, where Dock Mag sells bread -- after the
        # smock on day one, which is the first thing a careful thief buys
        # (simulate_law's day one, whose own purchase then finds the thief
        # already dressed for it and is skipped here).
        self.walk(DOCKS)
        if played == 1:
            self.act("buy", "npc_dock_mag/porters_smock")
            self.provision()
            self.walk(simulate_law.BUSY_DISTRICT)
            self.wait_until(simulate_law.CAREFUL_CHANGE_HOUR)
            if "porter" in self.legal_targets("guise"):
                self.act("guise", "porter")
            return
        self.provision()
        simulate_law._careful_day(self, played)
        # One purse at 21:00 in the Snuffs; Marrow's yard is open until
        # midnight, across the same street.
        self.sell_goods()
        self.eat()


class CarefulOnCredit(Careful):
    """The careful pickpocket, with one fence's line of credit (``CREDIT``)."""

    #: policy -> (thread template, where her counter is)
    CREDIT = {"careful_pell": ("pell_advance", MARKET),
              "careful_marrow": ("marrow_slate", HOME)}

    def __init__(self, seed: int, bed: str, policy: str, strike: bool = True) -> None:
        Careful.__init__(self, seed, bed)
        self.life.policy = policy
        self.template, self.counter = self.CREDIT[policy]
        #: False is the CONTROL (``--no-credit``): the same days, the same
        #: visits to her counter and the same bread bought there, and never a
        #: line struck -- so what credit itself buys is the difference.
        self.strike = strike

    def answer_stop(self) -> None:
        """Count the fences' collectors (streets.yaml), then answer as the careful thief does."""
        from engine.game import encounter

        met = encounter.active(self.state) and str(self.state.encounter.get("id")) in COLLECTORS
        hp = int(self.state.stats.hp)
        if met:
            self.life.collectors_met += 1
        super().answer_stop()
        if met:
            self.life.collectors_hp += max(0, hp - int(self.state.stats.hp))
            self.note()

    def tend_credit(self) -> None:
        """Repay the open line if it can, else strike one if the purse is low."""
        from engine.game import threads

        open_ = [t for t in threads.active(self.state) if t.get("template") == self.template]
        if open_:
            thread_id = str(open_[0]["id"])
            if thread_id in self.legal_targets("discharge"):
                self.act("discharge", thread_id)
            return
        if (self.strike and int(self.state.stats.gold) < CREDIT_WHEN_BELOW
                and self.template in self.legal_targets("bargain")):
            self.act("bargain", self.template)

    def has_business(self) -> bool:
        """A debt open with her, or a lean purse and a fence who has not heard it welshed."""
        from engine.game import threads

        if any(t.get("template") == self.template for t in threads.active(self.state)):
            return True
        welshed = ("welshed_on_pell", "welshed_on_marrow")
        return (int(self.state.stats.gold) < CREDIT_WHEN_BELOW
                and not any(self.state.flags.get(f) for f in welshed))

    def day(self, played: int) -> None:
        if self.counter == MARKET and played > 1 and self.has_business():
            # Breakfast on the quay, then by Pell's counter -- only on a day
            # with business there, so every other day is the careful
            # pickpocket's own -- then the careful day (which walks on to
            # the Snuffs).
            if self.state.world_hour < WAKE_HOUR:
                self.wait_until(WAKE_HOUR)
            self.walk(DOCKS)
            self.provision()
            self.walk(MARKET)
            if self.state.world_hour < 8:
                self.wait_until(8)   # her shutters open at eight
            self.tend_credit()
            self.provision()
            simulate_law._careful_day(self, played)
            self.sell_goods()
            self.eat()
            return
        super().day(played)
        if self.counter == HOME and played > 1 and self.has_business():
            self.tend_credit()   # the yard, after the night's sale
            self.provision()

    def tally(self) -> None:
        from engine.game import threads

        mine = [t for t in self.state.threads if t.get("template") == self.template]
        self.life.credit_struck = len(mine)
        self.life.credit_repaid = sum(t.get("status") == threads.STATUS_DISCHARGED for t in mine)
        self.life.credit_broken = sum(t.get("status") == threads.STATUS_BROKEN for t in mine)


class ScroungeLiving(Living, Scrounger):
    def __init__(self, seed: int, bed: str) -> None:
        Scrounger.__init__(self, seed, "scrounger")
        self.life = Life(seed=seed, policy="scrounger", bed=bed)

    def day(self, played: int) -> None:
        if self.state.world_hour < simulate_scrounge.START_HOUR:
            self.wait_until(simulate_scrounge.START_HOUR)
        simulate_scrounge._day(self, simulate_scrounge._streets("scrounger", played))
        self.walk(HOME)
        self.sell_junk()
        self.eat_if_hungry()


CLASSES = {"porter": Porter, "dipper": Dipper, "careful": Careful,
           "scrounger": ScroungeLiving}


def play(seed: int, policy: str, days: int, bed: str = "flophouse",
         strike: bool = True) -> Life:
    if policy in CarefulOnCredit.CREDIT:
        person = CarefulOnCredit(seed, bed, policy, strike)
    else:
        person = CLASSES[policy](seed, bed)
    person.life.start_gold = int(person.state.stats.gold)
    played = 0
    while person.state.world_day <= days:
        played += 1
        person.day(played)
        person.night()
    person.life.end_gold = int(person.state.stats.gold)
    person.life.arrests = int(person.run.arrests)
    if isinstance(person, CarefulOnCredit):
        person.tally()
    return person.life


def _mean(values: list[float]) -> float:
    return round(statistics.fmean(values), 2) if values else 0.0


def measure(policy: str, seeds: int, days: int, bed: str = "flophouse",
            strike: bool = True) -> dict[str, Any]:
    lives = [play(seed, policy, days, bed, strike) for seed in range(seeds)]
    earning = ("work", "lift", "sell")

    def per_day(life: Life, value: float) -> float:
        return value / max(1, life.days)

    return {
        "seeds": seeds,
        "days": days,
        "bed": bed,
        "earned_per_day": _mean([per_day(l, sum(max(0, l.money[k]) for k in earning))
                                 for l in lives]),
        "wages_per_shift": _mean([l.wages / l.shifts for l in lives if l.shifts]),
        "shifts_per_day": _mean([per_day(l, l.shifts) for l in lives]),
        "food_per_day": _mean([per_day(l, -l.money["buy"]) for l in lives]),
        "bed_per_day": _mean([per_day(l, -l.money["rest"]) for l in lives]),
        "fed_days": _mean([per_day(l, l.fed_days) for l in lives]),
        "bed_nights": _mean([per_day(l, l.bed_nights) for l in lives]),
        "kept_days": _mean([per_day(l, l.kept_days) for l in lives]),
        "saved_per_day": _mean([per_day(l, l.end_gold - l.start_gold) for l in lives]),
        "end_gold": _mean([float(l.end_gold) for l in lives]),
        "end_gold_min": min(l.end_gold for l in lives),
        "min_hp": min(l.min_hp for l in lives),
        "runs_at_zero_hp": round(sum(l.min_hp <= 0 for l in lives) / len(lives), 3),
        "min_stamina": min(l.min_stamina for l in lives),
        "arrests_per_run": _mean([float(l.arrests) for l in lives]),
        "fines_per_run": _mean([float(-l.money["pay_fine"]) for l in lives]),
        **_credit(lives),
    }


def _credit(lives: list[Life]) -> dict[str, float]:
    """The credit columns, for a policy that ran a line of credit at all."""
    struck = sum(l.credit_struck for l in lives)
    if not struck:
        return {}
    return {
        "credit_struck": _mean([float(l.credit_struck) for l in lives]),
        "credit_repaid": round(sum(l.credit_repaid for l in lives) / struck, 2),
        "credit_broken": round(sum(l.credit_broken for l in lives) / struck, 2),
        "collectors_met": _mean([float(l.collectors_met) for l in lives]),
        "collectors_hp_lost": _mean([float(l.collectors_hp) for l in lives]),
    }


def render(policy: str, report: dict[str, Any]) -> str:
    lines = [f"{policy}: {report['seeds']} seeds x {report['days']} days, bed={report['bed']}"]
    for key, value in report.items():
        if key in ("seeds", "days", "bed"):
            continue
        lines.append(f"  {key:18} {value}")
    return "\n".join(lines)


@contextmanager
def _nothing() -> Iterator[None]:
    yield


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--seeds", type=int, default=40)
    parser.add_argument("--days", type=int, default=10)
    parser.add_argument("--policy", choices=(*POLICIES, "all"), default="all")
    parser.add_argument("--bed", choices=tuple(BEDS), default="flophouse")
    parser.add_argument("--agendas", action="store_true",
                        help="measure with the story's agendas on (off by default)")
    parser.add_argument("--no-credit", action="store_true",
                        help="the credit policies' control: the same visits, no line struck")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    import logging

    logging.disable(logging.WARNING)
    from engine.games import registry

    registry.activate("hue-and-cry")
    with (_nothing() if args.agendas else agendas_off()):
        policies = POLICIES if args.policy == "all" else (args.policy,)
        reports = {p: measure(p, args.seeds, args.days, args.bed, not args.no_credit)
                   for p in policies}
    if args.json:
        print(json.dumps(reports, indent=2))
    else:
        print("\n\n".join(render(p, r) for p, r in reports.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
