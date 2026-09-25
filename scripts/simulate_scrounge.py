"""
The Scrounging Harness
======================

Play HUE & CRY headlessly with a thief who lives on what the streets drop,
and report what a day of it is worth against what a day costs (AGENTS.md rule
10: forage yields are set by measurement, not guessed).

TWO POLICIES, the same seeds:

  scrounger  Lives on scrounging alone and never steals. Every day from 07:00
             it walks a loop of the five scroungeable streets -- the Snuffs,
             the docks, Wickmarket, Chandlers' Rise, the Green -- and works
             each once (five attempts, ten hours, plus the walking). It eats
             what it finds when it gets hungry, sells every non-food thing at
             the first counter open to it, buys bread with that coin only
             when it is hungry and has nothing to eat, and sleeps rough in the
             Snuffs (free, and a survival roll).
  mornings   The same thief, but it scrounges only its first two streets and
             then stops for the day -- the sideline a pickpocket would make of
             it, to read what scrounging adds per hour rather than per day.

Every scrounge, walk, sale, purchase, meal and night's sleep goes through
``tool_dispatcher.execute_intent``, the production channel a chosen option
takes, exactly as scripts/simulate_law.py drives its thief (this reuses its
``Thief``, and runs with agendas off for the same reason: a Magpie robbing on
the thief's name measures the Magpie). The harness does NOT feed the thief or
restore its stamina: whether scrounging keeps it alive is the question.

WHAT IT REPORTS, per policy, averaged over seeds:

  cr_per_day       what it sold, in crowns (the income scrounging adds)
  food_per_day     hunger taken off by food it FOUND (a heel of bread is 25)
  value_per_day    registry value of everything found, food included
  value_per_hour   the same, per hour spent scrounging
  hungry_days      days that ended at `hungry` or worse (of the run)
  min_hp           the lowest hp any seed reached
  ways_found       share of runs that found each secret way, and by which day

Usage:
    python scripts/simulate_scrounge.py                 # 40 seeds x 10 days, both
    python scripts/simulate_scrounge.py --seeds 10 --days 5 --policy scrounger
    python scripts/simulate_scrounge.py --json

Version: v0.1.0 [2026-09-25]
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

from scripts.simulate_law import Thief, agendas_off  # noqa: E402

POLICIES = ("scrounger", "mornings")
#: The loop, in walking order. Chandlers' Rise and the Green are both off
#: Wickmarket, so the loop passes through it twice.
LOOP = ("the_snuffs", "tallow_docks", "wickmarket")
LAST_STREETS = ("chandlers_rise", "gallows_green")
MORNING_STREETS = 2
START_HOUR = 7
#: The mornings thief goes to bed at the same hour as the scrounger, whose
#: loop ends about then; the afternoon goes on something the harness does not
#: model (a pickpocket's evening).
SUPPER_HOUR = 20
#: Stamina under which the thief sits down for `rest_short` before working a
#: street (survival.yaml: two hours, 15 stamina).
TIRED_AT = 15
BED = "the_snuffs"
#: Hunger at which the thief eats what it carries, and at which it spends
#: coin on bread when it carries nothing (survival.yaml: hungry at 60).
EAT_AT = 50.0
BUY_AT = 60.0
SECRET_WAYS = ("rooftop_road", "the_undercroft", "old_bell_tower")


@dataclass
class Run:
    seed: int
    policy: str
    forages: int = 0
    productive: int = 0
    hours_scrounging: float = 0.0
    value_found: int = 0
    food_found: float = 0.0
    sold: int = 0
    bought: int = 0
    hungry_days: int = 0
    min_hp: int = 999
    min_stamina: int = 999
    ways: dict[str, int] = field(default_factory=dict)   # secret -> day found


class Scrounger(Thief):
    def __init__(self, seed: int, policy: str) -> None:
        super().__init__(seed, policy)
        self.log = Run(seed=seed, policy=policy)

    def note(self) -> None:
        stats = self.state.stats
        self.log.min_hp = min(self.log.min_hp, int(stats.hp))
        self.log.min_stamina = min(self.log.min_stamina, int(stats.stamina))

    def scrounge(self) -> None:
        from engine.game import foraging, inventory, survival

        nodes = self.legal_targets("forage")
        if not nodes:
            return
        # The least-worked node, as `foraging._pick_node` would take it.
        receipt = self.act("forage", min(
            nodes, key=lambda n: (foraging.node_uses(self.state, n), n)))
        self.log.forages += 1
        self.log.hours_scrounging += float(receipt.get("hours") or 0.0)
        found = receipt.get("found") or []
        if found:
            self.log.productive += 1
        rules = survival.load_rules()
        for row in found:
            qty = int(row.get("qty") or 0)
            item_id = str(row.get("item_id"))
            self.log.value_found += qty * int(inventory.value_of(item_id))
            meal = survival.food_value(item_id, list(inventory.tags_of(item_id)), rules) or {}
            self.log.food_found += qty * -float(meal.get("hunger") or 0)
        found_way = receipt.get("discovery")
        if found_way:
            self.log.ways.setdefault(str(found_way.get("leads_to")), self.state.world_day)
        self.note()

    def eat_if_hungry(self) -> None:
        from engine.game import inventory

        guard = 0
        while self.state.hunger >= EAT_AT and guard < 6:
            guard += 1
            food = self.legal_targets("eat")
            if not food:
                break
            # The least valuable first: bread before biscuit before pie.
            self.act("eat", min(food, key=lambda i: (inventory.value_of(i), i)))
        if self.state.hunger >= BUY_AT and not self.legal_targets("eat"):
            for target in self.legal_targets("buy"):
                if target.endswith(("/heel_of_bread", "/ship_biscuit", "/eel_pie")):
                    before = self.state.stats.gold
                    self.act("buy", target)
                    if self.state.stats.gold < before:
                        self.log.bought += 1
                        food = self.legal_targets("eat")
                        if food:
                            self.act("eat", food[0])
                    break
        self.note()

    def sell_junk(self) -> None:
        from engine.game import inventory

        guard = 0
        while guard < 40:
            guard += 1
            targets = [t for t in self.legal_targets("sell")
                       if not inventory.has_tag(t.partition("/")[2], "food")]
            if not targets:
                return
            before = self.state.stats.gold
            self.act("sell", targets[0])
            gained = self.state.stats.gold - before
            if gained <= 0:
                return
            self.log.sold += gained

    def at(self, street: str) -> None:
        self.walk(street)
        self.sell_junk()
        self.eat_if_hungry()
        self.note()


def _day(s: Scrounger, streets: tuple[str, ...]) -> None:
    for street in streets:
        s.at(street)
        if s.state.location_id != street:
            return
        if s.state.stats.stamina < TIRED_AT:
            # Nobody scrounges on their last legs: an hour on a bollard first.
            s.act("rest", "rest_short")
        s.scrounge()
        s.sell_junk()
        s.eat_if_hungry()


def _streets(policy: str, day: int) -> tuple[str, ...]:
    if policy == "mornings":
        return LOOP[:MORNING_STREETS]
    # Chandlers' Rise and the Green take turns as the fourth street: both hang
    # off Wickmarket, and the whole loop is more walking than a day holds.
    return (*LOOP, LAST_STREETS[day % len(LAST_STREETS)])


def play(seed: int, policy: str, days: int) -> Run:
    from engine.game import survival

    s = Scrounger(seed, policy)
    played = 0
    while s.state.world_day <= days:
        played += 1
        # A new run starts at 08:00 on day one; every later day starts when
        # the thief wakes, or at START_HOUR if it woke before the bread did.
        if s.state.world_hour < START_HOUR:
            s.wait_until(START_HOUR)
        _day(s, _streets(policy, played))
        s.walk(BED)
        s.sell_junk()
        s.eat_if_hungry()
        if survival.hunger_stage(s.state) in ("hungry", "starving"):
            s.log.hungry_days += 1
        if policy == "mornings":
            s.wait_until(SUPPER_HOUR)  # the afternoon goes on something else
            s.eat_if_hungry()
        s.act("rest", "sleep_rough")
        s.note()
    return s.log


def _mean(values: list[float]) -> float:
    return round(statistics.fmean(values), 2) if values else 0.0


def measure(policy: str, seeds: int, days: int) -> dict[str, Any]:
    runs = [play(seed, policy, days) for seed in range(seeds)]
    per_day = float(days)
    report: dict[str, Any] = {
        "seeds": seeds,
        "days": days,
        "forages_per_day": _mean([r.forages / per_day for r in runs]),
        "productive_rate": _mean([r.productive / r.forages for r in runs if r.forages]),
        "cr_per_day": _mean([r.sold / per_day for r in runs]),
        "food_per_day": _mean([r.food_found / per_day for r in runs]),
        "value_per_day": _mean([r.value_found / per_day for r in runs]),
        "value_per_hour": _mean([r.value_found / r.hours_scrounging
                                 for r in runs if r.hours_scrounging]),
        "bread_bought_per_day": _mean([r.bought / per_day for r in runs]),
        "hungry_days": _mean([float(r.hungry_days) for r in runs]),
        "min_hp": min(r.min_hp for r in runs),
        "min_stamina": min(r.min_stamina for r in runs),
        "ways_found": {
            secret: {
                "share": round(sum(1 for r in runs if secret in r.ways) / len(runs), 2),
                "mean_day": _mean([float(r.ways[secret]) for r in runs if secret in r.ways]),
            }
            for secret in SECRET_WAYS
        },
    }
    return report


def render(policy: str, report: dict[str, Any]) -> str:
    lines = [f"{policy}: {report['seeds']} seeds x {report['days']} days"]
    for key, value in report.items():
        if key in ("seeds", "days"):
            continue
        lines.append(f"  {key:22} {value}")
    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--seeds", type=int, default=40)
    parser.add_argument("--days", type=int, default=10)
    parser.add_argument("--policy", choices=(*POLICIES, "all"), default="all")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    import logging

    logging.disable(logging.WARNING)
    from engine.games import registry

    registry.activate("hue-and-cry")
    with agendas_off():
        policies = POLICIES if args.policy == "all" else (args.policy,)
        reports = {p: measure(p, args.seeds, args.days) for p in policies}
    if args.json:
        print(json.dumps(reports, indent=2))
    else:
        print("\n\n".join(render(p, r) for p, r in reports.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
