"""
Headless Balance Harness
========================

Play the game N turns with a scripted policy and no LLM in the loop, then
report the numbers that decide whether it is tuned.

WHY THIS EXISTS: every balance constant in this project was chosen before the
world clock worked. ``advance_time`` was ``state.world_day += int(days_elapsed)``
and the only production caller passed 0.25, so the calendar never moved and
``world.evil_base_rate_per_day`` was multiplied by an elapsed time of zero
forever. No number downstream of the clock -- the evil rate, hunger per hour,
stamina costs, encounter frequency, quest deadlines -- has ever been observed
against a clock that runs. This script is how they get observed.

It deliberately does NOT go through ``run_turn``. A narration pass would put a
language model between the policy and the engine, which is exactly the source
of variance a balance run needs to remove. Policies call the same engine
entry points the ``@skill`` tools call, so what is measured here is what the
game does.

Instrumentation note: ``checks.resolve`` and ``encounter.check_death`` are
wrapped for the duration of a run. Both are reached through several layers
(travel, rest, encounters, quest hooks) and passing a recorder down through all
of them would mean changing engine signatures to serve a script. The wrap is
restored in a finally block and never leaves this module.

WHAT P12 ADDED, and why the harness had to grow to see it: foraging, labour
and a working sell side are three systems whose whole point is that the player
can stay alive and get paid, and this script could measure NEITHER. There was
no gold-earned counter because nothing earned gold; no forage counter because
nothing foraged; and every death was reported as one number when the only
death anybody was dying of was starvation. The `livelihood` block and the
`pauper` policy exist so those claims can be checked rather than asserted.

Usage:
    python scripts/simulate.py --turns 200 --seed 42 --policy cautious
    python scripts/simulate.py --policy all --json > balance.json
    python scripts/simulate.py --policy pauper --turns 200   # can you live broke?

Version: v0.2.0 [2026-08-08]
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from engine.config import get_config  # noqa: E402
from engine.game import checks as checks_module  # noqa: E402
from engine.game import encounter as encounter_module  # noqa: E402
from engine.game import survival  # noqa: E402
from engine.game.clock import advance_time  # noqa: E402
from engine.game.engine import GameEngine, active_engine  # noqa: E402
from engine.game.evil_ticker import PHASE_THRESHOLDS  # noqa: E402
from engine.game.locations import LOCATIONS, get_edge  # noqa: E402
from engine.game.procgen import new_game_state  # noqa: E402
from engine.game.quests import QuestEngine  # noqa: E402
from engine.game import economy as economy_module  # noqa: E402
from engine.game import foraging as foraging_module  # noqa: E402
from engine.game import inventory as inventory_module  # noqa: E402
from engine.game import trade as trade_module  # noqa: E402
from engine.game.state import GameState  # noqa: E402
from engine.memory.ledger import StoryLedger  # noqa: E402
from engine.skills.builtin.mechanics import trade as trade_skill  # noqa: E402
from engine.world.world_sim import WorldSim  # noqa: E402

#: Where each vendor stands. This used to be a hardcoded dict here, because
#: games/clockwork-dark/data/economy.yaml names NPCs without saying where they are and nothing in
#: the engine knew either. games/clockwork-dark/data/tables/trade.yaml now declares it, so the
#: harness reads the same file the game does.
def vendor_locations() -> dict[str, str]:
    """Vendor id -> location id, from the active game's trade table."""
    return {
        npc_id: str(profile.get("location") or "")
        for npc_id, profile in trade_module.vendors().items()
        if profile.get("location")
    }


#: The bought staple: what a player with money eats. Foraging is the answer for
#: a player without, and proving that is the point of the `pauper` policy.
STAPLE_FOOD = ("npc_maris", "loaf")

def _default_tick_hours() -> float:
    """
    In-game hours the background world tick adds per turn.

    READ FROM CONFIG, not restated. This was a literal 6.0 whose docstring
    claimed it mirrored the scene's ``REALTIME_TICK_HOURS`` while nothing
    enforced it -- so the instrument used to tune the clock could silently
    measure a different clock than the one that shipped. That is the shape of
    R-03: the number nobody could see was the number that mattered.

    In production the tick is proportional to REAL time elapsed, so this is the
    pacing of a player who thinks for about one ``world.tick_interval_seconds``
    per turn. Pass ``--tick-hours 0`` to measure action time alone.
    """
    from engine.config import get_config

    return float(get_config().get("world.tick_hours", 2.0))


DEFAULT_TICK_HOURS = _default_tick_hours()

#: Turn budget guard for a policy that somehow never terminates an encounter.
MAX_ENCOUNTER_ROUNDS = 8


# ---------------------------------------------------------------------------
# route helper
# ---------------------------------------------------------------------------


def route(from_id: str, to_id: str) -> list[str]:
    """
    Shortest path through the location graph.

    Args:
        from_id: Current location id.
        to_id: Destination location id.

    Returns:
        Hops after ``from_id``, ending at ``to_id``. Empty when already there
        or when no path exists.
    """
    if from_id == to_id:
        return []
    seen = {from_id}
    queue: deque[tuple[str, list[str]]] = deque([(from_id, [])])
    while queue:
        node, path = queue.popleft()
        for neighbour in (LOCATIONS.get(node, {}).get("connections") or {}):
            if neighbour in seen:
                continue
            step = path + [neighbour]
            if neighbour == to_id:
                return step
            seen.add(neighbour)
            queue.append((neighbour, step))
    return []


# ---------------------------------------------------------------------------
# samples
# ---------------------------------------------------------------------------


@dataclass
class TurnSample:
    """One turn's worth of observable state, recorded after the action ran."""

    turn: int
    day: int
    hour: int
    location_id: str
    action: str
    hp: int
    stamina: int
    stamina_cap: int
    hunger: float
    hunger_stage: str
    gold: int
    evil_progress: float
    evil_phase: str
    awareness: float
    active_arc: str


@dataclass
class CheckSample:
    """One resolved skill check, whatever layer asked for it."""

    skill: str
    difficulty: str
    degree: str
    total: int
    dc: int


@dataclass
class RunResult:
    """Everything one simulated run produced."""

    policy: str
    seed: int
    turns: int
    tick_hours: float
    samples: list[TurnSample] = field(default_factory=list)
    checks: list[CheckSample] = field(default_factory=list)
    quest_events: list[dict[str, Any]] = field(default_factory=list)
    encounters_drawn: list[str] = field(default_factory=list)
    travel_legs: int = 0
    #: Legs on an edge with danger_dc > 0. The village doors are 0 and can
    #: never produce an encounter, so a rate over all legs understates the road
    #: by whatever fraction of the walk was indoors.
    danger_legs: int = 0
    deaths: int = 0
    gold_start: int = 0
    gold_spent: int = 0
    #: Livelihood instrumentation (P12). Before foraging, labour and a working
    #: sell side existed there was nothing here to count: every policy ended
    #: its run at zero gold having earned nothing, and the only food in the
    #: game had a price. These are the numbers that say whether that changed.
    gold_earned: int = 0
    shifts_worked: int = 0
    shifts_refused: int = 0
    forage_attempts: int = 0
    forage_productive: int = 0
    food_foraged: int = 0
    items_foraged: int = 0
    items_sold: int = 0
    starvation_deaths: int = 0
    #: Base worth of everything still in the pack at the last turn. A run that
    #: ends broke but carrying forty coppers of brass has an economy; one that
    #: ends broke and empty does not.
    carried_value_end: int = 0
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# policies
# ---------------------------------------------------------------------------

Action = tuple[str, dict[str, Any]]

#: Skills a policy may drill on when it has nothing else to do. Chosen so the
#: per-skill success table covers every stat in the taxonomy.
_IDLE_CHECKS = {
    "baker": ("craft", "standard"),
    "cautious": ("survival", "easy"),
    "reckless": ("nerve", "hard"),
    "pauper": ("survival", "standard"),
}


def _edible(state: GameState) -> str:
    """
    Id of the best edible item carried, or empty string.

    "Best" means the one that removes the most hunger. Eating the weakest food
    first is what an inventory-order scan does, and it measures a player who
    eats five mushrooms instead of a loaf -- which is not the decision anybody
    makes and understates what the food economy is worth.
    """
    rules = survival.load_rules()
    best, best_value = "", 0.0
    for item in state.inventory:
        if item.qty <= 0:
            continue
        value = survival.food_value(item.id, list(item.tags), rules)
        if value is None:
            continue
        gain = -float(value.get("hunger", -15))
        if gain > best_value:
            best, best_value = item.id, gain
    return best


def _sellable(state: GameState, npc_id: str) -> tuple[str, int]:
    """
    The most valuable thing here this vendor would buy, and what it fetches.

    Food is never offered: the point of carrying food is not starving, and a
    policy that sells its own dinner measures a bug rather than an economy.
    """
    best, best_total = "", 0
    for entry in state.inventory:
        if inventory_module.has_tag(entry.id, "food", entry.tags):
            continue
        quote = trade_module.quote(state, npc_id, entry.id, trade_module.SELL, entry.qty)
        if not quote.get("ok"):
            continue
        total = int(quote.get("total", 0))
        if total > best_total:
            best, best_total = entry.id, total
    return best, best_total


def _common_upkeep(state: GameState, policy: str) -> Optional[Action]:
    """
    The decisions every policy makes the same way.

    Encounters first (an open scene blocks everything), then food, then rest.
    The rest threshold is the difference between the policies: see callers.
    """
    if encounter_module.active(state):
        approaches = {a["id"] for a in encounter_module.available_approaches(state)}
        for preferred in _APPROACH_PREFERENCE[policy]:
            if preferred in approaches:
                return ("approach", {"approach": preferred})
        return ("approach", {"approach": "flee"})

    if survival.hunger_stage(state) in ("hungry", "starving"):
        item_id = _edible(state)
        if item_id:
            return ("eat", {"item_id": item_id})

    # Sell before you buy. Standing at a counter with a pack full of foraged
    # brass and no money was the exact state the old sell path could not get
    # anybody out of, so a policy that never tries would not notice it was
    # fixed.
    for npc_id, where in vendor_locations().items():
        if where != state.location_id:
            continue
        item_id, total = _sellable(state, npc_id)
        if item_id and total >= 2:
            # The whole stack, not one at a time: a player empties their pack
            # at a counter in one conversation, and selling singly was measured
            # burning fifty turns of two hundred on the same transaction.
            return (
                "sell",
                {
                    "npc_id": npc_id,
                    "item_id": item_id,
                    "qty": inventory_module.quantity(state, item_id),
                },
            )

    # Restock while standing in the only shop that sells food. Buying is
    # unconditional on hunger because the bakery is not on the way to anywhere
    # -- a policy that only shops when already starving never gets there.
    vendor, food_id = STAPLE_FOOD
    price = trade_module.quote(state, vendor, food_id, trade_module.BUY, 1).get(
        "unit_price", 0
    )
    if (
        state.location_id == vendor_locations().get(vendor)
        and price
        and state.stats.gold >= price
        and not _edible(state)
    ):
        # Stock up rather than buying one loaf per turn. At the shipped 6h
        # background tick a turn costs 12 hunger before the action does
        # anything, so buying singly was measured burning more hunger walking
        # back to the counter than the loaf removed.
        return (
            "buy",
            {"npc_id": vendor, "item_id": food_id, "qty": min(4, state.stats.gold // price)},
        )

    # Hungry and broke. These two branches are what did not exist: with no
    # gold, no forage and no wage, the only remaining action was to keep
    # walking until the hunger clock killed you. Every policy gets them,
    # because "I am starving and there is work" is not a playstyle.
    if survival.hunger_stage(state) in ("hungry", "starving") and not _edible(state):
        if foraging_module.forageable(state.location_id) and state.stats.stamina >= 15:
            return ("forage", {})
        # Stamina floor of 45, not 25: a shift is five to eight hours and
        # taking one at 25 stamina was measured putting `cautious` straight
        # into a rest, so the shift cost the hours AND the night. Working
        # yourself into a bed is a net hunger loss.
        if state.stats.gold < 3 and state.stats.stamina >= 45:
            paying = [
                row
                for row in economy_module.available(state)
                if row.get("in_kind")
            ]
            if paying:
                # Only work that FEEDS you. A wage cannot be eaten, and at this
                # pacing the walk back to a counter costs more hunger than the
                # coin buys.
                best = min(paying, key=lambda r: float(r.get("hours", 24)))
                return ("work", {"job_id": best["id"]})
    return None


_APPROACH_PREFERENCE: dict[str, tuple[str, ...]] = {
    # A careful player talks, pays, and leaves. A reckless one swings first.
    "cautious": ("talk", "pay", "sneak", "flee", "fight"),
    "reckless": ("fight", "talk", "sneak", "pay", "flee"),
    "baker": ("talk", "pay", "flee", "sneak", "fight"),
    "pauper": ("talk", "flee", "sneak", "pay", "fight"),
}


def _pending_flag(state: GameState) -> str:
    """
    One narrative flag the engine would currently accept, or empty string.

    In a real turn the Storyteller raises these when the fiction earns them.
    A policy raising the first legal one models a player who actually does the
    thing the objective asks for -- which is what a balance run wants, since
    the alternative measures a game where nobody ever finishes anything.
    """
    allowed = sorted(QuestEngine.allowed_narrative_flags(state))
    for flag_id in allowed:
        if not state.flags.get(flag_id):
            return flag_id
    return ""


def policy_baker(state: GameState) -> Action:
    """
    The thesis case: never leaves Edgewood, never asks a question.

    Exists to answer one question -- how far does the evil get while the player
    is doing something the game says is a complete way to play?
    """
    upkeep = _common_upkeep(state, "baker")
    if upkeep:
        return upkeep

    if state.stats.stamina < 40:
        return ("rest", {"kind": "sleep_bed"})

    # Work if there is work. This is the whole of the Quiet Life arc's economy
    # and until games/clockwork-dark/data/tables/labour.yaml existed there was no such action: the
    # baker policy's entire day was a craft check against nothing, for nothing.
    shift = _best_shift(state)
    if shift:
        return ("work", {"job_id": shift})

    # Nothing on offer here. A village has more than one counter, and which of
    # them is hiring moves with the evil phase, so walking to the next one is
    # a real decision rather than a fallback.
    target = _nearest_hiring(state, ("edgewood_bakery", "well_row", "the_forge", "fallow_farm"))
    if target and target != state.location_id:
        hops = route(state.location_id, target)
        if hops:
            return ("travel", {"to": hops[0]})

    if state.location_id != "edgewood_bakery":
        hops = route(state.location_id, "edgewood_bakery")
        if hops:
            return ("travel", {"to": hops[0]})

    flag_id = _pending_flag(state)
    if flag_id:
        return ("flag", {"flag_id": flag_id})

    skill, difficulty = _IDLE_CHECKS["baker"]
    return ("check", {"skill": skill, "difficulty": difficulty, "hours": 3.0})


def _best_shift(state: GameState) -> str:
    """Highest-paying job on offer where the player stands, or empty string."""
    offers = economy_module.available(state)
    if not offers:
        return ""
    return max(offers, key=lambda row: int(row.get("expected_wage", 0)))["id"]


def _nearest_hiring(state: GameState, candidates: tuple[str, ...]) -> str:
    """First place in the list that currently has work on offer."""
    for location_id in candidates:
        if economy_module.available(state, location_id):
            return location_id
    return ""


def policy_pauper(state: GameState) -> Action:
    """
    Starts broke, stays broke on purpose, and never buys food.

    THIS IS THE POLICY THAT ANSWERS THE QUESTION. Before P12 the only food in
    the game had a price, so "can a player survive without gold" had one
    answer: no, and the measured cost was 62-79 starvation deaths per 200
    turns on every other policy. This one spends nothing, works nothing, and
    lives entirely off what it can find -- so its death count IS the answer.

    It rotates between forage grounds rather than standing in one, because a
    depleted node is meant to make you walk, and a policy that never walks
    measures the depletion curve instead of the food economy.
    """
    upkeep = _common_upkeep(state, "pauper")
    if upkeep:
        return upkeep

    # 40, not 30. The `exhausted` situational in games/clockwork-dark/data/rules/skills.yaml bites
    # at 20 and a forage costs 6, so a policy that rests at 30 spends most of
    # its life inside a -3 on the only check that feeds it.
    if state.stats.stamina < 40:
        return (
            "rest",
            {"kind": "sleep_bed" if state.location_id == "edgewood_square" else "sleep_rough"},
        )

    # Eat before hunger becomes a stamina cap, not after it becomes damage.
    if survival.hunger_stage(state) != "fed":
        item_id = _edible(state)
        if item_id:
            return ("eat", {"item_id": item_id})

    grounds = [
        loc
        for loc in ("forest_clearing", "herb_glen", "deeper_forest")
        if foraging_module.forageable(loc)
    ]
    if not grounds:
        skill, difficulty = _IDLE_CHECKS["pauper"]
        return ("check", {"skill": skill, "difficulty": difficulty, "hours": 2.0})

    here = foraging_module.preview(state)
    # Move on only once the ground under you is genuinely picked over. Rotating
    # sooner was measured spending 54 turns of 200 walking between three woods
    # that are all one hop apart -- travel is the most expensive way to not eat.
    worn = int(here.get("node_uses", 0)) >= 3
    if here.get("available") and not worn:
        return ("forage", {})

    target = grounds[(state.turn_number // 7) % len(grounds)]
    if target != state.location_id:
        hops = route(state.location_id, target)
        if hops:
            return ("travel", {"to": hops[0]})
    return ("forage", {})


def policy_cautious(state: GameState) -> Action:
    """
    Travels, but pays the upkeep first. Rests before it has to, eats early,
    walks the Millhaven road only in daylight.
    """
    upkeep = _common_upkeep(state, "cautious")
    if upkeep:
        return upkeep

    if state.stats.stamina < 60:
        return ("rest", {"kind": "sleep_bed"})

    flag_id = _pending_flag(state)
    if flag_id:
        return ("flag", {"flag_id": flag_id})

    # A loop around the village, extending to Millhaven only by day. The night
    # multiplier on encounter chance is the whole reason this policy differs
    # from `reckless` on the same road.
    circuit = ["edgewood_square", "edgewood_bakery", "edgewood_square", "tinker_caravan"]
    if state.time_of_day == "day" and state.stats.stamina >= 80:
        circuit.append("millhaven_gate")
    target = circuit[state.turn_number % len(circuit)]
    hops = route(state.location_id, target)
    if hops:
        return ("travel", {"to": hops[0]})

    skill, difficulty = _IDLE_CHECKS["cautious"]
    return ("check", {"skill": skill, "difficulty": difficulty, "hours": 2.0})


def policy_reckless(state: GameState) -> Action:
    """
    Walks the dangerous road until it cannot, fights everything, rests only
    when the engine refuses to move it.
    """
    upkeep = _common_upkeep(state, "reckless")
    if upkeep:
        return upkeep

    # 20 is the exact cost of the Millhaven leg (4h * 5). Resting only at the
    # floor is what makes this policy the stamina soft-lock canary.
    if state.stats.stamina < 20:
        return ("rest", {"kind": "sleep_bed"})

    flag_id = _pending_flag(state)
    if flag_id:
        return ("flag", {"flag_id": flag_id})

    target = "millhaven_gate" if state.location_id != "millhaven_gate" else "edgewood_square"
    hops = route(state.location_id, target)
    if hops:
        return ("travel", {"to": hops[0]})

    skill, difficulty = _IDLE_CHECKS["reckless"]
    return ("check", {"skill": skill, "difficulty": difficulty, "hours": 1.0})


POLICIES: dict[str, Callable[[GameState], Action]] = {
    "baker": policy_baker,
    "cautious": policy_cautious,
    "pauper": policy_pauper,
    "reckless": policy_reckless,
}


# ---------------------------------------------------------------------------
# the run
# ---------------------------------------------------------------------------


class Simulation:
    """One scripted playthrough with metric collection."""

    def __init__(
        self,
        *,
        policy: str,
        seed: int,
        turns: int,
        tick_hours: float = DEFAULT_TICK_HOURS,
    ) -> None:
        self.policy_name = policy
        self.policy = POLICIES[policy]
        self.turns = turns
        self.tick_hours = tick_hours
        self.state: GameState = new_game_state(seed=seed)
        self.engine = GameEngine(self.state)
        self.ledger = StoryLedger()
        self.result = RunResult(
            policy=policy,
            seed=seed,
            turns=turns,
            tick_hours=tick_hours,
            gold_start=self.state.stats.gold,
        )

    # -- instrumentation -------------------------------------------------

    def _install_probes(self) -> tuple[Any, Any]:
        """
        Wrap the two engine functions whose results no caller returns upward.

        Returns the originals so the caller can restore them.
        """
        original_resolve = checks_module.resolve
        original_death = encounter_module.check_death

        def recording_resolve(*args: Any, **kwargs: Any) -> Any:
            outcome = original_resolve(*args, **kwargs)
            self.result.checks.append(
                CheckSample(
                    skill=outcome.skill,
                    difficulty=outcome.difficulty,
                    degree=outcome.degree,
                    total=outcome.total,
                    dc=outcome.dc,
                )
            )
            return outcome

        def recording_death(*args: Any, **kwargs: Any) -> Any:
            # Read the cause BEFORE the call: check_death respawns the player
            # and clears the scene, so anything sampled afterwards says
            # "starved" for every death in the run.
            starving = survival.hunger_stage(self.state) == "starving"
            fighting = encounter_module.active(self.state)
            record = original_death(*args, **kwargs)
            if record:
                self.result.deaths += 1
                if starving and not fighting:
                    self.result.starvation_deaths += 1
            return record

        checks_module.resolve = recording_resolve  # type: ignore[assignment]
        encounter_module.check_death = recording_death  # type: ignore[assignment]
        return original_resolve, original_death

    # -- actions ---------------------------------------------------------

    def _execute(self, action: str, args: dict[str, Any]) -> None:
        """Apply one policy decision to the world."""
        state = self.state

        if action == "travel":
            before = state.location_id
            edge = get_edge(before, str(args["to"])) or {}
            move = self.engine.move_to(str(args["to"]))
            if move.success and move.to_id != before:
                self.result.travel_legs += 1
                if int(edge.get("danger_dc", 0) or 0) > 0:
                    self.result.danger_legs += 1
                if move.encounter:
                    self.result.encounters_drawn.append(str(move.encounter.get("id", "")))
            elif not move.success:
                # A refused move still costs the turn; that is the whole point
                # of tracking it. "Not enough stamina" with no rest available
                # is the soft-lock signature.
                self.result.errors.append(f"move refused: {move.message}")
                advance_time(state, 1.0)

        elif action == "rest":
            survival.rest(state, str(args.get("kind", "rest_short")))

        elif action == "eat":
            survival.eat(state, str(args["item_id"]))

        elif action == "buy":
            # Through the registered skill, not a reimplementation of it: the
            # point of a balance run is to measure the code that ships.
            with active_engine(self.engine):
                payload = json.loads(
                    trade_skill(
                        action="buy",
                        item_id=str(args["item_id"]),
                        npc_id=str(args["npc_id"]),
                        qty=int(args.get("qty", 1)),
                    )
                )
            if not payload.get("success"):
                self.result.errors.append(f"buy refused: {payload.get('message', '')}")
            else:
                self.result.gold_spent += int(payload.get("gold_spent", 0))
            advance_time(state, 0.5)

        elif action == "sell":
            # Through the registered skill for the same reason `buy` is: the
            # point of a balance run is to measure the code that ships. This
            # branch is new because before P12 the sell path refused almost
            # everything and there was nothing to measure.
            with active_engine(self.engine):
                payload = json.loads(
                    trade_skill(
                        action="sell",
                        item_id=str(args["item_id"]),
                        npc_id=str(args["npc_id"]),
                        qty=int(args.get("qty", 1)),
                    )
                )
            if payload.get("success"):
                self.result.gold_earned += int(payload.get("gold_gained", 0))
                self.result.items_sold += int(payload.get("qty", 0))
            advance_time(state, 0.5)

        elif action == "forage":
            outcome = foraging_module.forage(state, ledger=self.ledger)
            self.result.forage_attempts += 1
            if outcome.get("found"):
                self.result.forage_productive += 1
            for row in outcome.get("found") or []:
                qty = int(row.get("qty", 0))
                self.result.items_foraged += qty
                if inventory_module.has_tag(str(row.get("item_id")), "food"):
                    self.result.food_foraged += qty
            if not outcome.get("success") and outcome.get("message"):
                self.result.errors.append(f"forage refused: {outcome['message']}")

        elif action == "work":
            outcome = economy_module.work(state, str(args["job_id"]), ledger=self.ledger)
            if outcome.get("message") and "check" not in outcome:
                self.result.shifts_refused += 1
            else:
                self.result.shifts_worked += 1
                self.result.gold_earned += int(outcome.get("wage", 0))

        elif action == "check":
            checks_module.resolve(
                state,
                str(args["skill"]),
                str(args.get("difficulty", "standard")),
                ledger=self.ledger,
            )
            advance_time(state, float(args.get("hours", 1.0)))

        elif action == "approach":
            rounds = 0
            while encounter_module.active(state) and rounds < MAX_ENCOUNTER_ROUNDS:
                encounter_module.resolve_approach(
                    state, str(args["approach"]), ledger=self.ledger
                )
                rounds += 1
                # One approach id may stop being legal mid-scene (gold spent on
                # a toll, for instance). Fall through to walking away.
                legal = {a["id"] for a in encounter_module.available_approaches(state)}
                if args["approach"] not in legal:
                    args = {"approach": "flee"}
            advance_time(state, 0.5)

        elif action == "flag":
            QuestEngine.set_narrative_flag(state, str(args["flag_id"]))
            advance_time(state, 0.5)

        else:  # wait
            advance_time(state, float(args.get("hours", 1.0)))

    # -- loop ------------------------------------------------------------

    def run(self) -> RunResult:
        """
        Play the configured number of turns.

        Returns:
            RunResult with one sample per turn plus every check, quest event
            and encounter the run produced.
        """
        original_resolve, original_death = self._install_probes()
        try:
            for _ in range(self.turns):
                self._one_turn()
        finally:
            checks_module.resolve = original_resolve  # type: ignore[assignment]
            encounter_module.check_death = original_death  # type: ignore[assignment]
        self.result.carried_value_end = inventory_module.carried_value(self.state)
        return self.result

    def _one_turn(self) -> None:
        state = self.state

        # The background world tick, exactly as run_turn applies it.
        if self.tick_hours > 0:
            WorldSim.on_tick(state, hours=self.tick_hours)

        action, args = self.policy(state)
        try:
            self._execute(action, args)
        except Exception as exc:  # noqa: BLE001 — a harness must survive to report
            self.result.errors.append(f"turn {state.turn_number}: {action}: {exc}")

        state.turn_number += 1

        for event in QuestEngine.evaluate(state, self.ledger):
            self.result.quest_events.append(
                {
                    "turn": state.turn_number,
                    "day": state.world_day,
                    "kind": event.kind,
                    "quest_id": event.quest_id,
                }
            )

        self.result.samples.append(
            TurnSample(
                turn=state.turn_number,
                day=state.world_day,
                hour=state.world_hour,
                location_id=state.location_id,
                action=action,
                hp=state.stats.hp,
                stamina=state.stats.stamina,
                stamina_cap=state.effective_stamina_cap,
                hunger=round(state.hunger, 1),
                hunger_stage=state.hunger_stage,
                gold=state.stats.gold,
                evil_progress=round(state.evil_progress, 5),
                evil_phase=state.evil_phase.value,
                awareness=round(state.awareness, 1),
                active_arc=state.active_arc,
            )
        )


# ---------------------------------------------------------------------------
# reporting
# ---------------------------------------------------------------------------


def _distribution(values: list[float]) -> dict[str, float]:
    """Five-number-ish summary. Empty input yields zeros rather than raising."""
    if not values:
        return {"min": 0.0, "p10": 0.0, "median": 0.0, "mean": 0.0, "max": 0.0}
    ordered = sorted(values)
    return {
        "min": round(ordered[0], 2),
        "p10": round(ordered[max(0, int(len(ordered) * 0.10) - 1)], 2),
        "median": round(statistics.median(ordered), 2),
        "mean": round(statistics.fmean(ordered), 2),
        "max": round(ordered[-1], 2),
    }


def _evil_curve(samples: list[TurnSample]) -> list[dict[str, Any]]:
    """One row per in-game day: the reading at the last turn of that day."""
    by_day: dict[int, TurnSample] = {}
    for sample in samples:
        by_day[sample.day] = sample
    return [
        {
            "day": day,
            "evil_progress": by_day[day].evil_progress,
            "evil_phase": by_day[day].evil_phase,
            "turn": by_day[day].turn,
        }
        for day in sorted(by_day)
    ]


def _phase_days(curve: list[dict[str, Any]]) -> dict[str, Optional[int]]:
    """First in-game day each phase was observed."""
    seen: dict[str, Optional[int]] = {phase.value: None for _, phase in PHASE_THRESHOLDS}
    for row in curve:
        phase = str(row["evil_phase"])
        if seen.get(phase) is None:
            seen[phase] = int(row["day"])
    return seen


def _skill_table(checks: list[CheckSample]) -> dict[str, dict[str, Any]]:
    """Attempts and outcome mix per skill."""
    table: dict[str, dict[str, Any]] = {}
    for sample in checks:
        row = table.setdefault(
            sample.skill,
            {"attempts": 0, "crit_success": 0, "success": 0, "partial": 0, "failure": 0},
        )
        row["attempts"] += 1
        row[sample.degree] = row.get(sample.degree, 0) + 1
    for row in table.values():
        wins = row["crit_success"] + row["success"]
        row["success_rate"] = round(wins / row["attempts"], 3) if row["attempts"] else 0.0
        row["partial_rate"] = (
            round(row["partial"] / row["attempts"], 3) if row["attempts"] else 0.0
        )
    return dict(sorted(table.items()))


def summarize(result: RunResult) -> dict[str, Any]:
    """
    Fold a run into the report payload.

    Args:
        result: Completed run.

    Returns:
        JSON-serializable dict: summary, evil curve, distributions, per-skill
        rates, gold movement, encounter frequency and quest outcomes.
    """
    samples = result.samples
    last = samples[-1] if samples else None
    curve = _evil_curve(samples)

    days_elapsed = max(1, (last.day if last else 1) - 1)
    evil_per_day = (last.evil_progress / days_elapsed) if last and days_elapsed else 0.0
    consuming_at = PHASE_THRESHOLDS[-1][0]

    completed = [e for e in result.quest_events if e["kind"] == "completed"]
    failed = [e for e in result.quest_events if e["kind"] == "failed"]
    started = [e for e in result.quest_events if e["kind"] == "started"]
    arcs = [e for e in result.quest_events if e["kind"] == "arc_unlocked"]

    stamina = [float(s.stamina) for s in samples]
    hunger = [float(s.hunger) for s in samples]
    gold = [float(s.gold) for s in samples]

    stage_counts = Counter(s.hunger_stage for s in samples)
    zero_stamina = sum(1 for s in samples if s.stamina <= 0)
    # Where the turns actually went. Added in P12 because "foraging feeds you"
    # and "the policy spent 13% of its turns foraging" are different claims and
    # only the second one explains a death count.
    action_counts = dict(Counter(s.action for s in samples).most_common())

    return {
        "config": {
            "policy": result.policy,
            "seed": result.seed,
            "turns": result.turns,
            "tick_hours": result.tick_hours,
            "evil_base_rate_per_day": float(
                get_config().get("world.evil_base_rate_per_day", 0.01)
            ),
        },
        "summary": {
            "turns_played": len(samples),
            "day_reached": last.day if last else 1,
            "hours_elapsed": round((last.day - 1) * 24 + last.hour, 1) if last else 0.0,
            "in_game_hours_per_turn": (
                round(((last.day - 1) * 24 + last.hour - 8) / len(samples), 2)
                if last and samples
                else 0.0
            ),
            "final_evil_progress": last.evil_progress if last else 0.0,
            "final_evil_phase": last.evil_phase if last else "dormant",
            "final_awareness": last.awareness if last else 0.0,
            "final_arc": last.active_arc if last else "quiet_life",
            "deaths": result.deaths,
            "starvation_deaths": result.starvation_deaths,
            "errors": len(result.errors),
        },
        # Livelihood (P12). The block that tells you whether a player can stay
        # alive and get paid, which is the pair of questions the game had no
        # mechanical answer to.
        "livelihood": {
            "gold_earned": result.gold_earned,
            "gold_spent": result.gold_spent,
            "shifts_worked": result.shifts_worked,
            "shifts_refused": result.shifts_refused,
            "forage_attempts": result.forage_attempts,
            "forage_productive": result.forage_productive,
            "forage_hit_rate": (
                round(result.forage_productive / result.forage_attempts, 3)
                if result.forage_attempts
                else 0.0
            ),
            "items_foraged": result.items_foraged,
            "food_foraged": result.food_foraged,
            "food_per_forage": (
                round(result.food_foraged / result.forage_attempts, 2)
                if result.forage_attempts
                else 0.0
            ),
            "items_sold": result.items_sold,
            "carried_value_end": result.carried_value_end,
            "actions": action_counts,
        },
        "evil": {
            "per_in_game_day": round(evil_per_day, 5),
            "days_to_consuming_projected": (
                round(consuming_at / evil_per_day, 1) if evil_per_day > 0 else None
            ),
            "turns_to_consuming_projected": (
                round((consuming_at / evil_per_day) * (len(samples) / max(1, days_elapsed)), 0)
                if evil_per_day > 0
                else None
            ),
            "first_day_in_phase": _phase_days(curve),
            "curve": curve,
        },
        "stamina": {
            **_distribution(stamina),
            "turns_at_zero": zero_stamina,
            "final_cap": last.stamina_cap if last else 0,
        },
        "hunger": {
            **_distribution(hunger),
            "turns_by_stage": dict(stage_counts),
        },
        "gold": {
            **_distribution(gold),
            "start": result.gold_start,
            "end": last.gold if last else result.gold_start,
            "spent_on_food": result.gold_spent,
            "net": (last.gold if last else result.gold_start) - result.gold_start,
            "per_day": round(
                ((last.gold if last else result.gold_start) - result.gold_start)
                / days_elapsed,
                3,
            ),
        },
        "skills": _skill_table(result.checks),
        "encounters": {
            "travel_legs": result.travel_legs,
            "danger_legs": result.danger_legs,
            "encounters": len(result.encounters_drawn),
            "per_leg": (
                round(len(result.encounters_drawn) / result.travel_legs, 3)
                if result.travel_legs
                else 0.0
            ),
            "per_danger_leg": (
                round(len(result.encounters_drawn) / result.danger_legs, 3)
                if result.danger_legs
                else 0.0
            ),
            "by_id": dict(Counter(result.encounters_drawn)),
        },
        "quests": {
            "started": [e["quest_id"] for e in started],
            "completed": [e["quest_id"] for e in completed],
            "failed": [e["quest_id"] for e in failed],
            "arcs_unlocked": [e["quest_id"] for e in arcs],
        },
        "errors": result.errors[:20],
    }


def _livelihood_line(report: dict[str, Any]) -> str:
    """The livelihood block minus the action histogram, which prints separately."""
    return str({k: v for k, v in report.get("livelihood", {}).items() if k != "actions"})


def _render(report: dict[str, Any]) -> str:
    """Human-readable rendering of one report."""
    cfg, summary = report["config"], report["summary"]
    evil, skills = report["evil"], report["skills"]
    lines = [
        "=" * 68,
        f"policy={cfg['policy']}  seed={cfg['seed']}  turns={cfg['turns']}  "
        f"tick_hours={cfg['tick_hours']}  rate={cfg['evil_base_rate_per_day']}/day",
        "=" * 68,
        f"day reached          {summary['day_reached']} "
        f"({summary['hours_elapsed']}h, {summary['in_game_hours_per_turn']}h/turn)",
        f"evil                 {summary['final_evil_progress']} "
        f"({summary['final_evil_phase']}), {evil['per_in_game_day']}/day",
        f"projected CONSUMING  day {evil['days_to_consuming_projected']} "
        f"(~{evil['turns_to_consuming_projected']} turns)",
        f"phase first seen     {evil['first_day_in_phase']}",
        f"awareness / arc      {summary['final_awareness']} / {summary['final_arc']}",
        f"deaths / errors      {summary['deaths']} "
        f"({summary.get('starvation_deaths', 0)} starvation) / {summary['errors']}",
        "",
        f"stamina              {report['stamina']}",
        f"hunger               {report['hunger']}",
        f"gold                 {report['gold']}",
        f"livelihood           {_livelihood_line(report)}",
        f"turns spent on       {report.get('livelihood', {}).get('actions', {})}",
        f"encounters           {report['encounters']}",
        "",
        "skill                attempts  success  partial",
    ]
    for name, row in skills.items():
        lines.append(
            f"  {name:<18} {row['attempts']:>8}  {row['success_rate']:>7}  "
            f"{row['partial_rate']:>7}"
        )
    quests = report["quests"]
    lines += [
        "",
        f"quests started       {quests['started']}",
        f"quests completed     {quests['completed']}",
        f"quests failed        {quests['failed']}",
        f"arcs unlocked        {quests['arcs_unlocked']}",
    ]
    if report["errors"]:
        lines += ["", "errors:"] + [f"  {e}" for e in report["errors"]]
    return "\n".join(lines)


def simulate(
    *,
    policy: str,
    seed: int,
    turns: int,
    tick_hours: float = DEFAULT_TICK_HOURS,
) -> dict[str, Any]:
    """
    Run one policy and return its report.

    Args:
        policy: One of ``POLICIES``.
        seed: World seed. The same seed replays identically.
        turns: Number of turns to play.
        tick_hours: Background world tick per turn, in in-game hours.

    Returns:
        Report dict, as produced by :func:`summarize`.
    """
    return summarize(
        Simulation(policy=policy, seed=seed, turns=turns, tick_hours=tick_hours).run()
    )


def main(argv: Optional[list[str]] = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Headless balance harness for The Clockwork Dark."
    )
    parser.add_argument("--turns", type=int, default=200, help="Turns to play.")
    parser.add_argument("--seed", type=int, default=42, help="World seed.")
    parser.add_argument(
        "--policy",
        default="cautious",
        choices=[*sorted(POLICIES), "all"],
        help="Scripted policy, or 'all' to run each in turn.",
    )
    parser.add_argument(
        "--tick-hours",
        type=float,
        default=DEFAULT_TICK_HOURS,
        help=(
            "Background world tick per turn, in in-game hours. 0 measures "
            "action time only."
        ),
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON, not prose.")
    args = parser.parse_args(argv)

    names = sorted(POLICIES) if args.policy == "all" else [args.policy]
    reports = [
        simulate(
            policy=name,
            seed=args.seed,
            turns=args.turns,
            tick_hours=args.tick_hours,
        )
        for name in names
    ]

    if args.json:
        payload = reports[0] if len(reports) == 1 else {r["config"]["policy"]: r for r in reports}
        print(json.dumps(payload, indent=2))
    else:
        print("\n\n".join(_render(r) for r in reports))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
