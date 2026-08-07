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

Usage:
    python scripts/simulate.py --turns 200 --seed 42 --policy cautious
    python scripts/simulate.py --policy all --json > balance.json

Version: v0.1.0 [2026-08-07]
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
from engine.game.state import GameState  # noqa: E402
from engine.memory.ledger import StoryLedger  # noqa: E402
from engine.skills.builtin.mechanics import trade as trade_skill  # noqa: E402
from engine.world.world_sim import WorldSim  # noqa: E402

#: Where each vendor stands. The economy table (data/economy.yaml) names NPCs;
#: it does not say where they are, and nothing else in the engine does either.
VENDOR_LOCATIONS: dict[str, str] = {
    "npc_maris": "edgewood_bakery",
    "npc_odran": "tinker_caravan",
    "npc_ilya": "tinker_caravan",
}

#: The only repeatable food in the game, and its price.
STAPLE_FOOD = ("npc_maris", "loaf", 2)

#: In-game hours the background world tick adds per turn. Mirrors
#: ``content/scenes/clockwork/clockwork_state.py::REALTIME_TICK_HOURS``. In
#: production that tick only fires when ``world.tick_interval_seconds`` of REAL
#: time has passed, so this is the pacing of a player who thinks for a minute
#: per turn. Set it to 0 to measure action time alone.
DEFAULT_TICK_HOURS = 6.0

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
}


def _edible(state: GameState) -> str:
    """Id of the first edible item carried, or empty string."""
    rules = survival.load_rules()
    for item in state.inventory:
        if item.qty > 0 and survival.food_value(item.id, list(item.tags), rules):
            return item.id
    return ""


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

    # Restock while standing in the only shop that sells food. Buying is
    # unconditional on hunger because the bakery is not on the way to anywhere
    # -- a policy that only shops when already starving never gets there.
    vendor, food_id, price = STAPLE_FOOD
    if (
        state.location_id == VENDOR_LOCATIONS[vendor]
        and state.stats.gold >= price
        and not _edible(state)
    ):
        return ("buy", {"npc_id": vendor, "item_id": food_id})
    return None


_APPROACH_PREFERENCE: dict[str, tuple[str, ...]] = {
    # A careful player talks, pays, and leaves. A reckless one swings first.
    "cautious": ("talk", "pay", "sneak", "flee", "fight"),
    "reckless": ("fight", "talk", "sneak", "pay", "flee"),
    "baker": ("talk", "pay", "flee", "sneak", "fight"),
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

    if state.location_id != "edgewood_bakery":
        hops = route(state.location_id, "edgewood_bakery")
        if hops:
            return ("travel", {"to": hops[0]})

    flag_id = _pending_flag(state)
    if flag_id:
        return ("flag", {"flag_id": flag_id})

    skill, difficulty = _IDLE_CHECKS["baker"]
    return ("check", {"skill": skill, "difficulty": difficulty, "hours": 3.0})


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
            record = original_death(*args, **kwargs)
            if record:
                self.result.deaths += 1
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
                    )
                )
            if not payload.get("success"):
                self.result.errors.append(f"buy refused: {payload.get('message', '')}")
            else:
                self.result.gold_spent += int(payload.get("gold_spent", 0))
            advance_time(state, 0.5)

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
            "errors": len(result.errors),
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
        f"deaths / errors      {summary['deaths']} / {summary['errors']}",
        "",
        f"stamina              {report['stamina']}",
        f"hunger               {report['hunger']}",
        f"gold                 {report['gold']}",
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
