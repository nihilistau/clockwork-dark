"""
The doors harness (v0.25.0 §10.1; rule 10).

One policy per door, the same seeds, the flagship's real code. A policy
ANSWERS DEALT CARDS through `director.resolve` (the `card` verb's own path,
never `set_narrative_flag` for a card-carried stage), raises any OTHER
pending narrative flag as `scripts/simulate.py` does (the narrator's stand-in
for the side quests), works, eats, rests and travels as `cautious` does, and
stops at a lock or the cap. The deck walker (`simulate_decks.py`) is not asked:
it never travels, and every flagship deck is gated by a place.

Per policy it reports: the share of runs reaching its OWN ending, ANOTHER, or
NONE by the cap; turns, in-game days and evil_progress at the lock (median);
deaths and starvation deaths; and the cards dealt and answered. CARD COVERAGE
is the union over every policy of the cards dealt and answered: every one of
the 34 (§4.3) at least once.

The condition helpers (`stage`, `done`, `locked`) and `inside_window` live
here once (ruling M13): `tests/clockwork_walks.py`, the card-only walks,
imports them.

    python scripts/simulate_doors.py --seeds 40
    python scripts/simulate_doors.py --policy namer --seeds 3 --json
    python scripts/simulate.py --policy doors --seeds 40

Version: v0.1.0 [2026-10-29]
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
if str(_SCRIPTS.parent) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS.parent))

import simulate as sim  # noqa: E402

from engine import yamlio  # noqa: E402
from engine.content import director  # noqa: E402
from engine.game import economy as economy_module  # noqa: E402
from engine.game import endings  # noqa: E402
from engine.game import trade as trade_module  # noqa: E402
from engine.game.quests import QuestEngine, evaluate_condition  # noqa: E402
from engine.games.validation import flags_written  # noqa: E402
from engine.world import npc_sim  # noqa: E402

FLAGSHIP = "clockwork-dark"
CAP_TURNS = 1000
ROOT = _SCRIPTS.parent
SCENES = ROOT / "games" / FLAGSHIP / "data" / "scenes"
#: The press's card: the levy row is the day a run is first dealt it (§10.2).
PRESS_CARD = "P1_a_name_on_the_list"
#: Where a policy waits out the hours outside its goal's window: the nearest place (by road hours)
#: that no deck's `at_location` names, so a repeatable deck at the goal's place sees its trigger
#: fall and comes round again (the walks' ruling B2: a player who stood in the square all night
#: would never be dealt the next card). well_row for the village, the market for the gate, the
#: heartland road for the Join: a four-hour walk home from the gate every afternoon was measured
#: starving the marcher.
#: The village's postings where a policy short of coin goes to work, nearest the square first:
#: the oven (5 and a loaf), the errands (3), then Ilya's bench (11) or the loading (8). Not the
#: forge: its 9 for six hours feeds nobody, and a policy sent there first was measured starving;
#: and not the caravan first, which kept the witness out of the square in Nessa's hours.
EARN_AT = ("edgewood_bakery", "well_row", "tinker_caravan")
#: Meals a policy carries out of the bakery when it can pay for them.
STOCK = 6
#: Things a door's path needs held, which `_common_upkeep` would otherwise sell at the first
#: counter that buys them: the map the heartland road measures, the ration the Hearth banks, the
#: naming's evidence and the price's three offerings. (Measured: a pinner bought the road map and
#: sold it back to Odran the next turn, for sixty days.)
KEEP = frozenset({"road_map", "winter_ration", "nessas_drawing", "brass_shard", "golden_ring",
                  "copied_list", "fourth_verse", "the_written_name", "ninth_pin", "iron_key"})
#: Where an item a goal buys is sold (economy.yaml).
BUY_FROM = {"winter_ration": "npc_maris", "road_map": "npc_odran"}
#: Every door card's NON-locking answer (a policy locks only by its own door).
SAFE = {
    "H1_the_question": "not_yet", "W1_the_list": "keep_it", "M1_strike_the_name": "not_yet",
    "S1_choose_what": "not_yet", "S2_pay_it": "not_yet", "J1_the_pin": "keep_it",
    "T3_take_it_or_dont": "leave_it", "L2_the_weller_boy": "speak_up", "V2_the_vote": "stay",
    "L7_answer_her": "refuse", "P1_a_name_on_the_list": "let_it_be",
    # T10 fix round 2: Q1 gained a third answer; a policy whose door is not The Named Wound declines.
    "Q1_tell_her_or_dont": "not_yet",
}


# -- the condition helpers (ruling M13: here once; tests/clockwork_walks.py imports them) ---------------

def stage(quest: str, index: int) -> dict:
    """``quest`` at stage ``index`` or later."""
    return {"quest_state": {"quest": quest, "stage_at_least": index}}


def done(quest: str) -> dict:
    """``quest`` completed."""
    return {"quest_completed": quest}


def locked(ending: str) -> dict:
    """The run locked to ``ending``."""
    return {"ending": {"locked": ending}}


def settled(quest: str, at_least: Optional[int] = None) -> dict:
    """``quest`` completed (or at stage ``at_least``), or failed: a goal a run cannot be stuck on."""
    reached = done(quest) if at_least is None else stage(quest, at_least)
    return {"any": [reached, {"quest_state": {"quest": quest, "status": "failed"}}]}


def eligible(ending: str) -> dict:
    """Every clause of ``ending``'s gate holds (its door may be dealt)."""
    return {"ending": {"eligible": ending}}


def inside_window(hour: int, start: int, end: int) -> bool:
    """Whether ``hour`` is in the half-open window ``[start, end)``, which may wrap midnight."""
    if start <= end:
        return start <= hour < end
    return hour >= start or hour < end


def deck_places() -> frozenset[str]:
    """Every place a flagship deck's or card's `at_location` names."""
    out: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "at_location":
                    out.update(str(v) for v in (value if isinstance(value, list) else [value]))
                else:
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    for path in sorted(SCENES.glob("*.yaml")):
        walk(yamlio.safe_load(path.read_text(encoding="utf-8")) or {})
    return frozenset(out)


def away_from(place: str, decks: frozenset[str]) -> str:
    """The nearest place to `place`, by road hours, that no deck names (ties by id)."""
    import heapq

    best: dict[str, float] = {place: 0.0}
    heap: list[tuple[float, str]] = [(0.0, place)]
    while heap:
        hours, node = heapq.heappop(heap)
        if node not in decks and node != place:
            return node
        if hours > best.get(node, float("inf")):
            continue
        for neighbour, edge in sorted((sim.LOCATIONS.get(node, {}).get("connections") or {}).items()):
            cost = hours + float((edge or {}).get("hours", 1) or 0) + 0.001
            if cost < best.get(neighbour, float("inf")):
                best[neighbour] = cost
                heapq.heappush(heap, (cost, neighbour))
    return ""


def _far(place: str) -> bool:
    """A place three or more road hours from the square: the gate and everything past it."""
    hours, here = 0.0, "edgewood_square"
    for hop in sim.route(here, place):
        hours += float((sim.get_edge(here, hop) or {}).get("hours", 0) or 0)
        here = hop
    return hours >= 3


def card_flags() -> frozenset[str]:
    """Every flag a flagship deck beat writes: never raised as a 'pending narrative flag'."""
    out: set[str] = set()
    for path in sorted(SCENES.glob("*.yaml")):
        out |= flags_written(yamlio.safe_load(path.read_text(encoding="utf-8")) or {})
    return frozenset(out)


@dataclass(frozen=True)
class Goal:
    """Pursue until `done` holds: be at `place` (or wherever `npc` is) inside `hours`; there,
    work (`work=True`) or wait; or, with `buy`, buy that item from its vendor."""

    done: Any
    place: str = ""
    npc: str = ""
    hours: tuple[int, int] = (0, 24)
    work: bool = False
    buy: str = ""
    #: The faction whose standing the goal's work should pay ("" = read a `reputation` goal's).
    faction: str = ""
    #: Walk `cautious`'s circuit (the square, the bakery, the caravan, Millhaven by day) until
    #: `done` holds: the player who goes and listens, for a goal that waits on awareness.
    roam: bool = False


@dataclass(frozen=True)
class DoorPolicy:
    ending: str
    goals: tuple[Goal, ...]
    answers: dict[str, str] = field(default_factory=dict)
    #: Arcs whose pending narrative flags this policy raises ("" = all).
    flag_arcs: tuple[str, ...] = ()
    #: `simulate.py`'s upkeep style; "reckless" walks the dangerous road and takes no goal.
    style: str = "cautious"


#: The naming's way in: the Whisper heard, the child's drawing kept (the evidence G1's stage
#: asks), and awareness enough for `naming_the_wound`'s preconditions (52).
NAMING = (
    Goal({"arc_unlocked": "whisper"}, roam=True),
    Goal(settled("childs_drawing"), place="edgewood_square", hours=(9, 17)),
    Goal({"min_awareness": 52}, roam=True),
    Goal(stage("naming_the_wound", 1), place="edgewood_square", hours=(19, 23)),
    Goal({"min_phase": "spreading"}, place="edgewood_bakery", work=True),
    Goal(stage("naming_the_wound", 2), place="edgewood_square", hours=(19, 23)),
    Goal(done("naming_the_wound"), place="edgewood_square", hours=(19, 23)),
)

#: The craft the batch asks (`the_last_quiet_thing`'s `the_batch`: 11). A wayfarer starts at 8,
#: and three quiet-life quests pay +1 each: the apprenticeship, Teward's roof (the reeds cut
#: in the clearing) and the shrine's mural (which itself asks 10). The namer does all three.
#: A run that has not finished them by day 30 (a quest stuck below its craft) gives them up.
def _craft_goal(condition: dict, **where: Any) -> Goal:
    return Goal({"any": [condition, {"min_day": 30}]}, **where)


CRAFT = (
    _craft_goal(settled("bakery_apprentice", 1), place="edgewood_bakery", hours=(7, 11)),
    _craft_goal(settled("bakery_apprentice", 2), place="edgewood_bakery", hours=(4, 7)),
    _craft_goal(settled("bakery_apprentice"), place="edgewood_bakery", hours=(8, 11), work=True),
    _craft_goal(settled("neighbours_roof", 1), place="edgewood_square", hours=(8, 18)),
    _craft_goal(settled("neighbours_roof", 2), place="forest_clearing", hours=(8, 18)),
    _craft_goal(settled("neighbours_roof"), place="edgewood_square", hours=(8, 18)),
    _craft_goal(settled("shrine_mural"), place="edgewood_square", hours=(8, 18)),
)

ROAD_MAP = Goal({"has_item": {"id": "road_map", "qty": 1}}, buy="road_map")
TINKERS = Goal({"reputation": {"faction": "tinkers", "min": 10}}, place="tinker_caravan", work=True)

POLICIES: dict[str, DoorPolicy] = {
    "baker": DoorPolicy("the_hearth_holds", (
        Goal(stage("bakery_apprentice", 1), place="edgewood_bakery", hours=(7, 11)),
        Goal(stage("bakery_apprentice", 2), place="edgewood_bakery", hours=(4, 7)),
        Goal(done("bakery_apprentice"), place="edgewood_bakery", hours=(8, 11), work=True),
        Goal({"has_item": {"id": "winter_ration", "qty": 1}}, buy="winter_ration"),
        Goal({"quest_state": {"quest": "banking_the_fire", "status": "active"}}, place="edgewood_bakery", work=True),
        Goal(stage("banking_the_fire", 1), place="edgewood_bakery", hours=(4, 10)),
        Goal(locked("the_hearth_holds"), place="edgewood_bakery", hours=(4, 10)),
    ), {"H1_the_question": "stay"}, flag_arcs=("quiet_life",)),
    "settler": DoorPolicy("the_dark_keeps_its_hours", (
        Goal({"min_awareness": 41}, roam=True),
        Goal({"has_item": {"id": "winter_ration", "qty": 1}}, buy="winter_ration"),
        Goal({"quest_state": {"quest": "banking_the_fire", "status": "active"}}, place="edgewood_square", work=True),
        Goal(stage("banking_the_fire", 1), place="edgewood_bakery", hours=(4, 10)),
        Goal(locked("the_dark_keeps_its_hours"), place="edgewood_bakery", hours=(4, 10)),
    ), {"H1_the_question": "stay_anyway"}),
    "witness": DoorPolicy("the_long_witness", (
        Goal({"arc_unlocked": "whisper"}, roam=True),
        Goal(settled("childs_drawing"), place="edgewood_square", hours=(9, 17)),
        # The door's own gate (the saints' standing, the day), so a measured lever moving one of
        # its numbers moves the policy with it: the shrine's shift is the saints' work.
        Goal(eligible("the_long_witness"), place="edgewood_shrine", work=True, faction="unnamed_saints"),
        Goal(locked("the_long_witness"), place="edgewood_shrine", hours=(18, 22)),
    ), {"W1_the_list": "give_it"}),
    "marcher": DoorPolicy("the_counted_march", (
        Goal({"arc_unlocked": "march"}, place="millhaven_gate", hours=(8, 12)),
        Goal({"event_seen": "militia_press"}, place="edgewood_square", work=True),
        Goal(settled("militia_press"), npc="npc_sera", hours=(8, 12)),
        Goal(eligible("the_counted_march"), place="millhaven_gate", work=True, faction="militia"),
        Goal(locked("the_counted_march"), place="millhaven_gate", hours=(8, 12)),
    ), {"M1_strike_the_name": "strike_it", "L2_the_weller_boy": "give_his_name"}),
    "namer": DoorPolicy("the_named_wound", CRAFT + NAMING + (
        Goal(done("what_edgewood_keeps"), place="edgewood_square", hours=(10, 16)),
        Goal(stage("the_last_quiet_thing", 1), place="edgewood_bakery", hours=(4, 7)),
        Goal(stage("the_last_quiet_thing", 2), place="edgewood_bakery", hours=(8, 12), work=True),
        Goal(locked("the_named_wound"), place="edgewood_bakery", hours=(4, 10)),
    ), {"Q1_tell_her_or_dont": "tell_her"}),
    "payer": DoorPolicy("the_price_asked", NAMING + (
        Goal(stage("the_sacrifice", 1), npc="npc_ilya", hours=(8, 20)),
        Goal(stage("the_sacrifice", 2), npc="npc_ilya", hours=(8, 20)),
        Goal(locked("the_price_asked"), npc="npc_ilya", hours=(8, 20)),
    ), {"S1_choose_what": "offer_the_name", "S2_pay_it": "pay_the_name"}),
    # Ilya's standing first, before the naming: his bench takes one shift a day (+2 each), the
    # pin's `ask_for_it` card is dealt on the first visit after the naming, and `pay_for_it`,
    # which asks the tinkers at 10, expires five days after it.
    # And the road map bought early too: by the convergence the bread costs 1.45-2x, and a
    # pinner earning five or eleven a shift was measured never saving the map's fifteen.
    "pinner": DoorPolicy("the_pin_and_the_join", (TINKERS, ROAD_MAP) + NAMING + (
        TINKERS,
        Goal(stage("the_ninth_pin", 1), place="tinker_caravan", hours=(9, 15)),
        Goal(done("the_ninth_pin"), place="tinker_caravan", hours=(9, 15)),
        ROAD_MAP,
        Goal(settled("the_heartland_road", 1), place="millhaven_gate", hours=(10, 15)),
        # `settled`: a walk that expired is counted as expired, not chased for the rest of the run.
        Goal(settled("the_heartland_road", 2), place="the_join", hours=(10, 15)),
        Goal(locked("the_pin_and_the_join"), place="the_join", hours=(10, 15)),
    ), {"T3_take_it_or_dont": "take_it", "J1_the_pin": "set_it"}),
    "drifter": DoorPolicy("the_stopped_wheel", (
        Goal(locked("the_stopped_wheel"), place="edgewood_bakery", work=True),
    )),
    "reckless": DoorPolicy("the_dark_keeps_its_hours", (), style="reckless"),
}


def _faction_of(condition: Any) -> str:
    """The faction a `reputation` goal asks for, or ""."""
    if isinstance(condition, dict) and isinstance(condition.get("reputation"), dict):
        return str(condition["reputation"].get("faction") or "")
    return ""


class DoorRun(sim.Simulation):
    """One policy, one seed, to a lock or the cap."""

    def __init__(self, policy: str, seed: int, cap: int = CAP_TURNS) -> None:
        self.door = POLICIES[policy]
        super().__init__(policy="reckless" if self.door.style == "reckless" else "cautious",
                         seed=seed, turns=cap)
        self.policy = self._decide
        self.door_name = policy
        self.answers = {**SAFE, **self.door.answers}
        self.card_flags = card_flags()
        self.deck_places = deck_places()
        self.dealt: set[str] = set()
        self.answered: set[str] = set()
        #: card id -> the in-game day it was first dealt (the levy row reads the press's).
        self.first_dealt: dict[str, int] = {}
        #: card id -> how many times it was dealt (a stage that waits re-deals its card).
        self.fallbacks: dict[str, int] = {}
        self.deal_counts: dict[str, int] = {}
        self.lock: Optional[dict[str, Any]] = None
        #: `--trace`: per turn, the goal pursued and the standings (off for a table run).
        self.tracing = False
        self.trace: list[str] = []

    # -- the turn ------------------------------------------------------------------------------

    def run(self) -> sim.RunResult:
        original_resolve, original_death = self._install_probes()
        try:
            for _ in range(self.turns):
                self._one_turn()
                self._deal_and_answer()
                if self.tracing:
                    self.trace.append(f"goal {self.goal_index()} rep {dict(self.state.reputations)} "
                                      f"scene {director.active(self.state)}")
                if self._locked_now() or self.state.ended:
                    break
        finally:
            sim.checks_module.resolve = original_resolve
            sim.encounter_module.check_death = original_death
        return self.result

    def _deal_and_answer(self) -> None:
        director.ensure_scene(self.state, ledger=self.ledger)
        while director.active(self.state):
            card = director.current_card(self.state)
            self.dealt.add(card.id)
            self.first_dealt.setdefault(card.id, int(self.state.world_day))
            self.deal_counts[card.id] = self.deal_counts.get(card.id, 0) + 1
            offered = [o["id"] for o in director.options(self.state)]
            chosen = self.answers.get(card.id, "")
            if chosen not in offered:
                chosen = offered[-1] if card.id in SAFE else ""
            if not chosen and len(offered) > 1:
                # A menu the policy has no answer for takes the director's first offered beat: counted,
                # so a lock it makes shows as forced, not chosen (Q1 before fix round 2's `not_yet`).
                self.fallbacks[card.id] = self.fallbacks.get(card.id, 0) + 1
            out = director.resolve(self.state, chosen=chosen, ledger=self.ledger)
            if out.get("ok"):
                self.answered.add(card.id)
            else:
                self.result.errors.append(f"card {card.id} refused {chosen!r}: {out.get('error')}")
                director.end(self.state)
        for event in QuestEngine.evaluate(self.state, self.ledger):
            self.result.quest_events.append({"turn": self.state.turn_number, "day": self.state.world_day,
                                             "kind": event.kind, "quest_id": event.quest_id})

    def goal_index(self) -> Optional[int]:
        """The index of the first goal not yet held (the one the run was pursuing), or None."""
        return next((i for i, g in enumerate(self.door.goals)
                     if not evaluate_condition(self.state, g.done, ledger=self.ledger)), None)

    def detail(self) -> dict[str, Any]:
        """This run's own row: where it ended and why."""
        return {"seed": self.result.seed, "lock": (self.lock or {}).get("ending"),
                "turn": self.state.turn_number, "day": self.state.world_day,
                "evil": round(self.state.evil_progress, 3), "phase": self.state.evil_phase.value,
                "awareness": round(self.state.awareness, 1), "goal": self.goal_index(),
                "deaths": self.result.deaths, "starved": self.result.starvation_deaths,
                "gold": self.state.stats.gold, "where": self.state.location_id,
                "craft": self.state.stats.craft, "standing": dict(self.state.reputations),
                "actions": dict(sim.Counter(x.action for x in self.result.samples).most_common())}

    def arc_day(self, arc: str) -> Optional[int]:
        """The in-game day `arc` opened, or None."""
        return next((int(e["day"]) for e in self.result.quest_events
                     if e["kind"] == "arc_unlocked" and e["quest_id"] == arc), None)

    def _locked_now(self) -> bool:
        locked_id = endings.locked(self.state)
        if locked_id == endings.NONE_ID:
            return False
        if self.lock is None:
            self.lock = {"ending": locked_id, "turn": self.state.turn_number, "day": self.state.world_day,
                         "evil_progress": round(self.state.evil_progress, 4)}
        return True

    # -- the decision --------------------------------------------------------------------------

    def _decide(self, state: Any) -> sim.Action:
        upkeep = sim._common_upkeep(state, self.door.style)
        if upkeep and not (upkeep[0] == "sell" and upkeep[1].get("item_id") in KEEP):
            return upkeep
        if state.stats.stamina < 50:
            return ("rest", {"kind": "sleep_bed"})
        flag_id = self._pending_flag(state)
        if flag_id:
            return ("flag", {"flag_id": flag_id})
        if self.door.style == "reckless":
            return sim.policy_reckless(state)
        goal = next((g for g in self.door.goals
                     if not evaluate_condition(state, g.done, ledger=self.ledger)), None)
        if goal is None:
            return ("wait", {"hours": 1.0})
        if goal.buy:
            return self._buying(state, goal.buy)
        provision = self._provision(state, goal.place or self._where(goal.npc))
        if provision:
            return provision
        restock = self._stock_up(state) or self._restock(state)
        if restock:
            return restock
        if goal.roam:
            return self._roam(state)
        if state.stats.gold < 4:
            earn = self._earn(state)
            if earn:
                return earn
        start, end = goal.hours
        inside = inside_window(state.world_hour, start, end)
        place = goal.place or self._where(goal.npc)
        if not inside and place:
            # Outside the window: near the goal's place but at none a deck names, so the goal's
            # deck re-arms (B2).
            place = away_from(place, self.deck_places) or place
        if place and state.location_id != place:
            hops = sim.route(state.location_id, place)
            if hops:
                return ("travel", {"to": hops[0]})
        if inside and goal.work:
            job = self._job_here(state, goal.faction or _faction_of(goal.done))
            if job:
                return ("work", {"job_id": job})
        return ("wait", {"hours": 1.0})

    def _provision(self, state: Any, place: str) -> Optional[sim.Action]:
        """Bound for a place a road away from the bakery (the gate and past it) and still in the
        village, carrying fewer than `STOCK` meals and the price of one: go by the bakery first.
        (Measured in T10's review: a pinner left the square for the gate with no bread, turned back
        hungry from the gate, and missed the Join's window; `_stock_up` alone fires only at the
        counter, which the road to the gate never passes.)"""
        if not place or not _far(place) or _far(state.location_id):
            return None
        vendor, food_id = sim.STAPLE_FOOD
        where = sim.vendor_locations().get(vendor, "")
        price = sim.trade_module.quote(state, vendor, food_id, sim.trade_module.BUY, 1).get("unit_price", 0)
        if (not where or self._carried_food(state) >= STOCK or not price or state.stats.gold < price
                or state.location_id == where):
            return None
        hops = sim.route(state.location_id, where)
        return ("travel", {"to": hops[0]}) if hops else None

    def _carried_food(self, state: Any) -> int:
        rules = sim.survival.load_rules()
        return sum(int(i.qty) for i in state.inventory
                   if i.qty > 0 and sim.survival.food_value(i.id, list(i.tags), rules) is not None)

    def _stock_up(self, state: Any) -> Optional[sim.Action]:
        """At the bakery's counter with fewer than `STOCK` meals and the coin: buy up to it. A
        policy whose door is four hours from the nearest loaf (the gate, the Join) otherwise
        spends its days walking back for bread (measured: the pinner reached the heartland road
        on day 108)."""
        vendor, food_id = sim.STAPLE_FOOD
        if state.location_id != sim.vendor_locations().get(vendor):
            return None
        have = self._carried_food(state)
        price = sim.trade_module.quote(state, vendor, food_id, sim.trade_module.BUY, 1).get("unit_price", 0)
        if have >= STOCK or not price or state.stats.gold < price:
            return None
        return ("buy", {"npc_id": vendor, "item_id": food_id,
                        "qty": min(STOCK - have, state.stats.gold // price)})

    def _restock(self, state: Any) -> Optional[sim.Action]:
        """Hungry, nothing carried and the price of a loaf in hand: walk to the bakery's counter
        (`_common_upkeep` buys there). `cautious` passes it every lap; a policy that stands at
        one door all day does not, and was measured starving between laps of nothing."""
        if sim.survival.hunger_stage(state) not in ("hungry", "starving") or sim._edible(state):
            return None
        vendor, food_id = sim.STAPLE_FOOD
        price = sim.trade_module.quote(state, vendor, food_id, sim.trade_module.BUY, 1).get("unit_price", 0)
        where = sim.vendor_locations().get(vendor, "")
        if not price or state.stats.gold < price or not where or where == state.location_id:
            return None
        hops = sim.route(state.location_id, where)
        return ("travel", {"to": hops[0]}) if hops else None

    def _roam(self, state: Any) -> sim.Action:
        """`cautious`'s circuit, its travel half only (its flag half would raise card flags)."""
        circuit = ["edgewood_square", "edgewood_bakery", "edgewood_square", "tinker_caravan"]
        if state.time_of_day == "day" and state.stats.stamina >= 80:
            circuit.append("millhaven_gate")
        hops = sim.route(state.location_id, circuit[state.turn_number % len(circuit)])
        if hops:
            return ("travel", {"to": hops[0]})
        return ("wait", {"hours": 1.0})

    def _pending_flag(self, state: Any) -> str:
        allowed = QuestEngine.allowed_narrative_flags(state)
        for definition, record in QuestEngine.active_quests(state):
            if self.door.flag_arcs and str(definition.get("arc")) not in self.door.flag_arcs:
                continue
            current = QuestEngine.current_stage(definition, record) or {}
            for flag_id in [*(definition.get("narrative_flags") or []), *(current.get("narrative_flags") or [])]:
                if flag_id in allowed and flag_id not in self.card_flags and not state.flags.get(flag_id):
                    return str(flag_id)
        return ""

    def _where(self, npc_id: str) -> str:
        presence = npc_sim.resolve_npc(self.state, npc_id) if npc_id else None
        return presence.location_id if presence is not None else ""

    def _job_here(self, state: Any, faction: str = "") -> str:
        """A job open here: the one paying `faction`'s standing when the goal asks one (the
        caravan offers the merchants' loading before Ilya's bench), else the first."""
        rows = economy_module.available(state, state.location_id)
        mine = [r for r in rows if faction and r.get("faction") == faction]
        rows = mine or rows
        return str(rows[0]["id"]) if rows else ""

    def _earn(self, state: Any) -> Optional[sim.Action]:
        """Work the best-paid job here, else walk to the best-paid village posting still hiring
        today (the bakery's one oven shift a day does not save fifteen gold for a road map)."""
        rows = economy_module.available(state, state.location_id)
        if rows:
            best = max(rows, key=lambda r: int(r.get("expected_wage", 0) or 0))
            return ("work", {"job_id": str(best["id"])})
        where = sim._nearest_hiring(state, EARN_AT)
        hops = sim.route(state.location_id, where) if where else []
        return ("travel", {"to": hops[0]}) if hops else None

    def _buying(self, state: Any, item_id: str) -> sim.Action:
        vendor = BUY_FROM[item_id]
        listing = trade_module.browse(state, vendor)
        row = next((r for r in (listing.get("sells") or []) if r.get("item_id") == item_id), None)
        if row is None or not row.get("affordable"):
            return self._earn(state) or ("wait", {"hours": 1.0})
        place = self._where(vendor)
        if place and state.location_id != place:
            hops = sim.route(state.location_id, place)
            if hops:
                return ("travel", {"to": hops[0]})
        return ("buy", {"npc_id": vendor, "item_id": item_id, "qty": 1})


def run_policy(name: str, seeds: list[int], cap: int = CAP_TURNS) -> dict[str, Any]:
    """One policy over the seeds: its row of the table."""
    own = other = none = deaths = starved = 0
    turns: list[int] = []
    days: list[int] = []
    evil: list[float] = []
    dealt: set[str] = set()
    answered: set[str] = set()
    errors: list[str] = []
    whisper_days: list[Optional[int]] = []
    press_days: list[int] = []
    deal_counts: dict[str, list[int]] = {}
    fallbacks: dict[str, int] = {}
    results: list[sim.RunResult] = []
    details: list[dict[str, Any]] = []
    ending = POLICIES[name].ending
    for seed in seeds:
        run = DoorRun(name, seed, cap)
        run.run()
        results.append(run.result)
        details.append(run.detail())
        whisper_days.append(run.arc_day("whisper"))
        if PRESS_CARD in run.first_dealt:
            press_days.append(run.first_dealt[PRESS_CARD])
        for card_id, count in run.fallbacks.items():
            fallbacks[card_id] = fallbacks.get(card_id, 0) + count
        for card_id, count in run.deal_counts.items():
            deal_counts.setdefault(card_id, []).append(count)
        deaths += run.result.deaths
        starved += run.result.starvation_deaths
        dealt |= run.dealt
        answered |= run.answered
        errors += run.result.errors[:3]
        if run.lock is None:
            none += 1
            continue
        if run.lock["ending"] == ending:
            own += 1
            turns.append(run.lock["turn"])
            days.append(run.lock["day"])
            evil.append(run.lock["evil_progress"])
        else:
            other += 1
    n = len(seeds)
    return {
        "policy": name, "ending": ending, "runs": n,
        "own": round(own / n, 3), "other": round(other / n, 3), "none": round(none / n, 3),
        "median_turns": statistics.median(turns) if turns else None,
        "median_day": statistics.median(days) if days else None,
        "median_evil": statistics.median(evil) if evil else None,
        "deaths": deaths, "starvation_deaths": starved,
        "whisper_by_day_20": round(sum(1 for d in whisper_days if d is not None and d <= 20) / n, 3),
        "median_whisper_day": statistics.median(d for d in whisper_days if d is not None)
        if any(d is not None for d in whisper_days) else None,
        "press_dealt": round(len(press_days) / n, 3),
        "median_press_day": statistics.median(press_days) if press_days else None,
        "bands": sim.band_rates(results),
        #: per card, the most times one run dealt it (a waiting stage re-deals its card).
        "max_deals": {c: max(v) for c, v in sorted(deal_counts.items())},
        #: per menu card, the times it was resolved with no answer of the policy's (the first beat).
        "fallback_answers": dict(sorted(fallbacks.items())),
        "dealt": sorted(dealt), "answered": sorted(answered), "errors": errors[:10],
        "runs_detail": details,
    }


def main(argv: Optional[list[str]] = None) -> int:
    from engine.games import registry

    parser = argparse.ArgumentParser(description="The Clockwork Dark's doors harness (v0.25.0 §10.1)")
    parser.add_argument("--policy", default="all", help=f"{', '.join(POLICIES)} or all")
    parser.add_argument("--seeds", type=int, default=40)
    parser.add_argument("--seed", type=int, default=0, help="the first seed")
    parser.add_argument("--cap", type=int, default=CAP_TURNS)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--trace", action="store_true",
                        help="one policy, the first seed: print each turn's sample instead of the table")
    args = parser.parse_args(argv)
    names = list(POLICIES) if args.policy == "all" else [args.policy]
    if any(n not in POLICIES for n in names):
        parser.error(f"--policy: one of {', '.join(POLICIES)} or all")
    seeds = list(range(args.seed, args.seed + args.seeds))
    if args.trace:
        registry.activate(FLAGSHIP)
        try:
            run = DoorRun(names[0], seeds[0], args.cap)
            run.tracing = True
            run.run()
        finally:
            registry.deactivate()
        for x, extra in zip(run.result.samples, run.trace):
            print(f"t{x.turn} d{x.day} h{x.hour:02d} {x.location_id:18} {x.action:8} hp{x.hp} st{x.stamina} "
                  f"hu{x.hunger:.0f}/{x.hunger_stage} g{x.gold} ev{x.evil_progress:.3f} aw{x.awareness} {x.active_arc} "
                  f"| {extra}")
        print(json.dumps(run.detail()), run.result.errors[:20], sorted(run.first_dealt.items(), key=lambda kv: kv[1]))
        return 0
    registry.activate(FLAGSHIP)
    try:
        rows = [run_policy(name, seeds, args.cap) for name in names]
    finally:
        registry.deactivate()
    all_cards = sorted(c["id"] for p in sorted(SCENES.glob("*.yaml"))
                       for c in (yamlio.safe_load(p.read_text(encoding="utf-8")) or {}).get("cards", []))
    covered = sorted(set().union(*(set(r["answered"]) for r in rows)))
    report = {"seeds": [seeds[0], seeds[-1]], "cap": args.cap, "policies": rows,
              "coverage": {"cards": len(all_cards), "answered": len(covered),
                           "missing": sorted(set(all_cards) - set(covered))}}
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        for r in rows:
            print(f"{r['policy']:9} own {r['own']:.0%} other {r['other']:.0%} none {r['none']:.0%} "
                  f"turns {r['median_turns']} day {r['median_day']} evil {r['median_evil']} "
                  f"deaths {r['deaths']} (starved {r['starvation_deaths']})")
        print(f"coverage: {len(covered)}/{len(all_cards)}; missing {report['coverage']['missing']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
