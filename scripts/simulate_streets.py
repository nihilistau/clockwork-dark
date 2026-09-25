"""
The Streets' Balance Harness
============================

Walk HUE & CRY's public streets around the clock and report how often a
street hands the walker a scene -- by time of day, by district, by scene --
and what the scenes cost (AGENTS.md rule 10: the night's danger is set by
measurement, not guessed). The numbers it prints are the ones in
games/hue-and-cry/data/encounters/rules.yaml's header and CHANGELOG.md.

ONE POLICY: the wanderer. A fresh thief in its own face walks one public
street every hour, day and night, to a neighbour the harness picks from its
own ``random.Random(seed)`` (never an engine stream), and answers every scene
the way simulate_law's thieves answer the Lantern: ``run`` where it is
offered, else the first way out that needs no roll. Held, it pays the fine or
serves the days (simulate_law.Thief.leave_custody).

WHAT IS REAL AND WHAT IS NOT. Every walk and every scene approach goes
through ``tool_dispatcher.execute_intent`` -- the production channel -- so the
draw is the engine's own (``encounter.roll_for_encounter`` on the ENCOUNTER
stream, the walker's own stealth taken off the chance) and so is every check.
The Law's patrol runs after each walk, as in play. What is NOT the game: the
walker is fed and rested every six legs through the ``hunger`` and
``stamina`` effects, because twenty-four streets a day is more walking than a
body does, and this harness measures the streets, not the legs.

Usage:
    python scripts/simulate_streets.py                  # 40 seeds x 3 days
    python scripts/simulate_streets.py --seeds 10 --days 2 --json

Version: v0.1.0 [2026-09-25]
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.simulate_law import Thief  # noqa: E402

#: Legs between the harness's feed-and-rest (its one liberty).
REST_EVERY_LEGS = 6
DAYPARTS = ("dawn", "day", "dusk", "night")


@dataclass
class Leg:
    daypart: str
    dest: str
    scene: str = ""
    outcome: str = ""
    gold_lost: int = 0
    arrested: bool = False


@dataclass
class Walk:
    seed: int
    legs: list[Leg] = field(default_factory=list)
    min_hp: int = 999


class Wanderer(Thief):
    def __init__(self, seed: int) -> None:
        super().__init__(seed, "wanderer")
        self.pick = random.Random(seed)
        self.walk_log = Walk(seed=seed)

    def neighbours(self) -> list[str]:
        from engine.game.locations import LOCATIONS

        here = LOCATIONS.get(self.state.location_id) or {}
        return sorted(n for n in (here.get("connections") or {})
                      if not (LOCATIONS.get(n) or {}).get("secret"))

    def leg(self) -> None:
        from engine.game import encounter
        from engine.world import law

        options = self.neighbours()
        if not options:
            return
        dest = self.pick.choice(options)
        gold = int(self.state.stats.gold)
        self.act("travel", dest)
        if self.state.location_id != dest:
            return
        row = Leg(daypart=self.state.time_of_day, dest=dest)
        if encounter.active(self.state):
            row.scene = str(self.state.encounter.get("id") or "")
            arrests = self.run.arrests
            self.answer_stop()
            row.arrested = self.run.arrests > arrests
            row.outcome = "arrested" if row.arrested else ""
            row.gold_lost = max(0, gold - int(self.state.stats.gold)) if not row.arrested else 0
        elif law.in_custody(self.state):
            self.leave_custody()
        self.walk_log.legs.append(row)
        self.walk_log.min_hp = min(self.walk_log.min_hp, int(self.state.stats.hp))


def play(seed: int, days: int) -> Walk:
    from engine.game.clock import advance_time

    w = Wanderer(seed)
    n = 0
    while w.state.world_day <= days:
        if n % REST_EVERY_LEGS == 0:
            w.morning()
        n += 1
        before = w.state.world_clock_hours
        w.leg()
        # One street an hour: a refused or free walk still lets the hour go.
        if w.state.world_clock_hours - before < 1.0 - 1e-9:
            advance_time(w.state, 1.0 - (w.state.world_clock_hours - before))
    return w.walk_log


def summarise(walks: list[Walk]) -> dict[str, Any]:
    legs = [leg for w in walks for leg in w.legs]
    by_part: dict[str, Any] = {}
    for part in DAYPARTS:
        rows = [x for x in legs if x.daypart == part]
        met = [x for x in rows if x.scene]
        by_part[part] = {"legs": len(rows), "scenes": len(met),
                         "rate": round(len(met) / len(rows), 3) if rows else 0.0}
    night = [x for x in legs if x.daypart == "night"]
    by_dest: dict[str, dict[str, Any]] = defaultdict(dict)
    for dest in sorted({x.dest for x in night}):
        rows = [x for x in night if x.dest == dest]
        met = sum(bool(x.scene) for x in rows)
        by_dest[dest] = {"legs": len(rows), "rate": round(met / len(rows), 3)}
    scenes = Counter(x.scene for x in legs if x.scene)
    met = [x for x in legs if x.scene]
    return {
        "walks": len(walks),
        "legs": len(legs),
        "by_daypart": by_part,
        "night_by_destination": dict(by_dest),
        "scenes": dict(scenes.most_common()),
        "robbed_share_of_scenes": (
            round(sum(x.gold_lost > 0 for x in met) / len(met), 3) if met else 0.0),
        "gold_lost_per_night_leg": (
            round(sum(x.gold_lost for x in night) / len(night), 3) if night else 0.0),
        "arrests_per_100_night_legs": (
            round(100 * sum(x.arrested for x in night) / len(night), 2) if night else 0.0),
        "min_hp": min((w.min_hp for w in walks), default=None),
        "median_min_hp": statistics.median_low([w.min_hp for w in walks]) if walks else None,
    }


def measure(seeds: int, days: int) -> dict[str, Any]:
    return summarise([play(seed, days) for seed in range(seeds)])


def render(report: dict[str, Any]) -> str:
    lines = [f"wanderer ({report['walks']} seeds, {report['legs']} legs)",
             "| daypart | legs | scenes | rate |", "|---|---|---|---|"]
    for part, row in report["by_daypart"].items():
        lines.append(f"| {part} | {row['legs']} | {row['scenes']} | {row['rate']:.1%} |")
    lines += ["", "| night, arriving at | legs | rate |", "|---|---|---|"]
    for dest, row in report["night_by_destination"].items():
        lines.append(f"| {dest} | {row['legs']} | {row['rate']:.1%} |")
    lines.append("")
    lines.append(f"scenes: {report['scenes']}")
    lines.append(
        f"robbed in {report['robbed_share_of_scenes']:.0%} of scenes; "
        f"{report['gold_lost_per_night_leg']} cr lost per night leg; "
        f"{report['arrests_per_100_night_legs']} arrests per 100 night legs; "
        f"min hp {report['min_hp']} (median of runs {report['median_min_hp']})")
    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--seeds", type=int, default=40)
    parser.add_argument("--days", type=int, default=3)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    import logging

    logging.disable(logging.WARNING)
    from engine.games import registry

    registry.activate("hue-and-cry")
    report = measure(args.seeds, args.days)
    print(json.dumps(report, indent=2) if args.json else render(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
