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
  arrests          mean per run

Usage:
    python scripts/simulate_labour.py                    # 40 seeds x 10 days, all four
    python scripts/simulate_labour.py --policy porter --bed bunk
    python scripts/simulate_labour.py --json

Version: v0.1.0 [2026-09-25]
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

POLICIES = ("porter", "dipper", "careful", "scrounger")
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


def play(seed: int, policy: str, days: int, bed: str = "flophouse") -> Life:
    person = CLASSES[policy](seed, bed)
    person.life.start_gold = int(person.state.stats.gold)
    played = 0
    while person.state.world_day <= days:
        played += 1
        person.day(played)
        person.night()
    person.life.end_gold = int(person.state.stats.gold)
    person.life.arrests = int(person.run.arrests)
    return person.life


def _mean(values: list[float]) -> float:
    return round(statistics.fmean(values), 2) if values else 0.0


def measure(policy: str, seeds: int, days: int, bed: str = "flophouse") -> dict[str, Any]:
    lives = [play(seed, policy, days, bed) for seed in range(seeds)]
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
        "min_stamina": min(l.min_stamina for l in lives),
        "arrests_per_run": _mean([float(l.arrests) for l in lives]),
        "fines_per_run": _mean([float(-l.money["pay_fine"]) for l in lives]),
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
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    import logging

    logging.disable(logging.WARNING)
    from engine.games import registry

    registry.activate("hue-and-cry")
    with (_nothing() if args.agendas else agendas_off()):
        policies = POLICIES if args.policy == "all" else (args.policy,)
        reports = {p: measure(p, args.seeds, args.days, args.bed) for p in policies}
    if args.json:
        print(json.dumps(reports, indent=2))
    else:
        print("\n\n".join(render(p, r) for p, r in reports.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
