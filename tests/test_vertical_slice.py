"""
Vertical Slice Playtest
=======================

Two long scripted playthroughs against a deterministic mock LLM: the baker who
never leaves Edgewood, and the traveller who walks the Millhaven road until it
hurts.

DESIGN.md has promised this file since PR12 was written and it has never
existed. What it is for is not coverage -- the unit suites have that -- it is
the class of bug that only appears after forty turns of the whole stack running
together, which is every bug the overhaul actually found:

  - the world clock never advanced, because ``int(0.25) == 0``, so the evil
    ticker was multiplied by an elapsed time of zero for the project's entire
    history;
  - a save round trip silently reset hidden state, so resuming a run was not
    the same run;
  - the prompt grew without bound and nothing asserted it fit the window;
  - the ledger was written and never read, so the Storyteller began every turn
    with no idea what it had just said;
  - raw bytes anywhere in a turn payload took the whole turn down at jsonify;
  - stamina was spent by travel and restored by nothing, so a player pinned at
    0 had no legal action left.

Every assertion below is one of those. Failures print the turn, the day and the
state, because "assert False" forty turns into a playthrough is not a bug
report.

The LLM is a fixed function of the turn number, and the policy is a function of
engine state alone, so both runs replay exactly. Summarization is stubbed out:
a playtest that phones a local model is not a test, it is a demo.

Version: v0.1.0 [2026-08-07]
"""

from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Optional
from unittest.mock import patch

import pytest

from content.scenes.clockwork.clockwork_state import SessionStore, run_turn
from engine.agents import storyteller as storyteller_module
from engine.game import encounter as encounter_module
from engine.game import survival
from engine.game.locations import LOCATIONS
from engine.game.quests import QuestEngine
from engine.game.state import GameState
from engine.memory.budget import estimate_messages
from engine.memory.context import default_budget
from engine.persistence import reset_save_store
from engine.persistence.saves import SaveStore

#: Long enough for the clock to roll several days, a quest to close, hunger to
#: bite and the ledger to overflow its buffer more than once.
TURNS = 40

#: The turn after which the run is saved, resumed into a second SessionStore
#: and compared. Late enough that the state is thoroughly non-default.
RESUME_AFTER_TURN = 20

SEED = 42

#: Marker embedded in every narration so a later prompt can be searched for an
#: earlier turn's text.
MARK = "Turn-mark"


# ---------------------------------------------------------------------------
# the mock model
# ---------------------------------------------------------------------------


def narration_for(turn: int, beat: str) -> str:
    """
    Build one turn of narration.

    Shaped to pass the evaluator on the first attempt (40-200 words, grounded
    vocabulary, no mechanical claims), because a retry would replay the turn's
    tool calls and make the playthrough harder to reason about than the thing
    it is testing.
    """
    return (
        f"{beat} The oven ticks as it settles and the village outside is doing "
        "what a village does at this hour, which is very little and all of it "
        "slowly. Rain has got into the boards by the door and nobody has "
        "planed them back. Out on the road a cart goes past without stopping, "
        "and the sound of it takes a long while to leave the trees. Somewhere "
        "behind the shutters a dog gives up on whatever it was worried about. "
        f"{MARK} {turn:03d}."
    )


class ScriptedLLM:
    """
    Deterministic stand-in for the Storyteller and the Assistant.

    The session hands the same callable to both agents, so the persona line is
    what tells them apart -- the Assistant gets prose, the Storyteller gets the
    turn object with whatever tool calls the policy queued for this turn.
    """

    def __init__(self) -> None:
        self.turn = 0
        self.beat = "You work."
        self.tool_calls: list[dict[str, Any]] = []
        self.storyteller_prompts: list[list[dict[str, Any]]] = []
        self.calls = 0

    def __call__(self, messages: list[dict[str, Any]]) -> str:
        self.calls += 1
        if not any("You are the STORYTELLER" in m.get("content", "") for m in messages):
            return "The cat looks at the door, then at you, and settles again."

        self.storyteller_prompts.append([dict(m) for m in messages])
        return json.dumps(
            {
                "narration": narration_for(self.turn, self.beat),
                "choices": [
                    {"id": "a", "text": "Keep working"},
                    {"id": "b", "text": "Step outside"},
                ],
                "tool_calls": self.tool_calls,
            }
        )


# ---------------------------------------------------------------------------
# policies
# ---------------------------------------------------------------------------

Decision = tuple[str, str, list[dict[str, Any]]]  # (action label, beat, tool calls)


def next_hop(from_id: str, to_id: str) -> str:
    """First step of the shortest path through the location graph, or ''."""
    if from_id == to_id:
        return ""
    queue: deque[tuple[str, str]] = deque([(from_id, "")])
    seen = {from_id}
    while queue:
        node, first = queue.popleft()
        for neighbour in LOCATIONS.get(node, {}).get("connections", {}):
            if neighbour in seen:
                continue
            step = first or neighbour
            if neighbour == to_id:
                return step
            seen.add(neighbour)
            queue.append((neighbour, step))
    return ""


def _edible(state: GameState) -> str:
    """Id of the first thing in the pack that counts as food."""
    rules = survival.load_rules()
    for item in state.inventory:
        if item.qty > 0 and survival.food_value(item.id, list(item.tags), rules):
            return item.id
    return ""


def _pending_flag(state: GameState) -> str:
    """A narrative flag the engine would accept right now, or ''."""
    for flag_id in sorted(QuestEngine.allowed_narrative_flags(state)):
        if not state.flags.get(flag_id):
            return flag_id
    return ""


def _encounter_decision(state: GameState, order: tuple[str, ...]) -> Optional[Decision]:
    """Take the first preferred approach the engine says is legal."""
    if not encounter_module.active(state):
        return None
    legal = {a["id"] for a in encounter_module.available_approaches(state)}
    for approach in order:
        if approach in legal:
            return (
                f"approach:{approach}",
                "The road has produced a problem and you meet it.",
                [{"name": "encounter_approach", "args": {"approach": approach}}],
            )
    return ("approach:flee", "You do not stay.", [{"name": "flee", "args": {}}])


def _upkeep(state: GameState) -> Optional[Decision]:
    """Eat, restock and rest -- the decisions both policies share."""
    if survival.hunger_stage(state) in ("hungry", "starving"):
        item_id = _edible(state)
        if item_id:
            return ("eat", "You eat.", [{"name": "eat", "args": {"item_id": item_id}}])

    if (
        state.location_id == "edgewood_bakery"
        and state.stats.gold >= 2
        and not _edible(state)
    ):
        return (
            "buy",
            "Maris wraps a loaf without being asked twice.",
            [
                {
                    "name": "trade",
                    "args": {"action": "buy", "item_id": "loaf", "npc_id": "npc_maris"},
                }
            ],
        )
    return None


def baker_policy(state: GameState) -> Decision:
    """
    Never leaves Edgewood, never asks a question, never walks a dangerous edge.

    This is the run that has to prove the design's central claim: a player who
    bakes bread is playing the game, and the evil keeps its own hours anyway.
    """
    fight = _encounter_decision(state, ("talk", "pay", "flee"))
    if fight:
        return fight

    if state.location_id != "edgewood_bakery":
        hop = next_hop(state.location_id, "edgewood_bakery")
        if hop:
            return (
                f"move:{hop}",
                "You walk in out of the weather.",
                [{"name": "move_to", "args": {"location_id": hop}}],
            )

    upkeep = _upkeep(state)
    if upkeep:
        return upkeep

    if state.stats.stamina < 40:
        return (
            "rest",
            "You sleep in the room above the ovens.",
            [{"name": "rest", "args": {"kind": "sleep_bed"}}],
        )

    flag_id = _pending_flag(state)
    if flag_id:
        return (
            f"flag:{flag_id}",
            "You do the thing that was asked of you.",
            [{"name": "set_narrative_flag", "args": {"flag_id": flag_id}}],
        )

    return (
        "craft",
        "You shape dough until your forearms complain.",
        [
            {
                "name": "resolve_skill_check",
                "args": {"skill": "craft", "difficulty": "standard", "reason": "baking"},
            }
        ],
    )


def road_policy(state: GameState) -> Decision:
    """Walks the Millhaven road, which is the only dangerous edge in the game."""
    fight = _encounter_decision(state, ("talk", "pay", "sneak", "fight", "flee"))
    if fight:
        return fight

    upkeep = _upkeep(state)
    if upkeep:
        return upkeep

    # 20 is exactly the Millhaven leg's stamina cost. Resting at the floor is
    # what makes this run the soft-lock canary.
    if state.stats.stamina < 20:
        return (
            "rest",
            "You put your back against a wall and stop.",
            [{"name": "rest", "args": {"kind": "sleep_bed"}}],
        )

    flag_id = _pending_flag(state)
    if flag_id:
        return (
            f"flag:{flag_id}",
            "You do the thing that was asked of you.",
            [{"name": "set_narrative_flag", "args": {"flag_id": flag_id}}],
        )

    target = (
        "edgewood_square" if state.location_id == "millhaven_gate" else "millhaven_gate"
    )
    hop = next_hop(state.location_id, target)
    if hop:
        return (
            f"move:{hop}",
            "The road goes on and you go on with it.",
            [{"name": "move_to", "args": {"location_id": hop}}],
        )
    return (
        "wait",
        "You wait, and the hour turns over.",
        [{"name": "resolve_skill_check", "args": {"skill": "nerve", "difficulty": "easy"}}],
    )


# ---------------------------------------------------------------------------
# the run
# ---------------------------------------------------------------------------


@dataclass
class Playthrough:
    """Everything one scripted run recorded, for assertions and diagnostics."""

    name: str
    rows: list[dict[str, Any]] = field(default_factory=list)
    payloads: list[dict[str, Any]] = field(default_factory=list)
    #: What the Storyteller actually received, interceptors included.
    prompts: list[list[dict[str, Any]]] = field(default_factory=list)
    #: What ``build_storyteller_messages`` produced, before the interceptor
    #: pass rewrote the system blocks. The two differ, which is the point.
    assembled: list[list[dict[str, Any]]] = field(default_factory=list)
    quest_events: list[dict[str, Any]] = field(default_factory=list)
    resume: dict[str, Any] = field(default_factory=dict)
    start: dict[str, Any] = field(default_factory=dict)
    final_state: Optional[GameState] = None
    ledger_facts: int = 0
    error: str = ""

    def table(self, *, limit: int = TURNS) -> str:
        """Whole per-turn table, for embedding in a failure message."""
        header = (
            f"--- {self.name} ---\n"
            "turn  day hr  location          action            "
            "hp  stam  hunger  evil    phase"
        )
        lines = [
            f"{r['turn']:>4}  {r['day']:>3} {r['hour']:>2}  {r['location_id']:<17} "
            f"{r['action']:<17} {r['hp']:>3}  {r['stamina']:>4}  {r['hunger']:>6}  "
            f"{r['evil_progress']:.5f} {r['evil_phase']}"
            for r in self.rows[:limit]
        ]
        return "\n".join([header, *lines])

    def at(self, index: int) -> str:
        """One-line description of a turn, for a targeted failure message."""
        if not self.rows:
            return f"{self.name}: no turns recorded"
        row = self.rows[index]
        return (
            f"{self.name} turn {row['turn']} (day {row['day']}, hour {row['hour']}) "
            f"at {row['location_id']}: action={row['action']} hp={row['hp']} "
            f"stamina={row['stamina']} hunger={row['hunger']} "
            f"evil={row['evil_progress']:.5f} ({row['evil_phase']}) "
            f"arc={row['active_arc']} awareness={row['awareness']}"
        )


def play(
    name: str,
    policy: Callable[[GameState], Decision],
    store_root: Any,
) -> Playthrough:
    """
    Run one scripted playthrough end to end.

    Args:
        name: Label used in diagnostics.
        policy: Chooses the action for a turn from engine state alone.
        store_root: Directory for this run's saves.

    Returns:
        Playthrough with one row per turn, every prompt the Storyteller saw,
        every turn payload, and the mid-run resume comparison.
    """
    run = Playthrough(name=name)
    save_store = SaveStore(root=store_root)
    llm = ScriptedLLM()

    build = storyteller_module.build_storyteller_messages

    def recording_build(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        """Capture the prompt as assembled, before interceptors touch it."""
        messages = build(*args, **kwargs)
        run.assembled.append([dict(m) for m in messages])
        return messages

    with patch(
        "content.scenes.clockwork.clockwork_state.get_save_store",
        lambda: save_store,
    ), patch(
        # A playtest must not depend on a local model being up, and 40 turns
        # overflow the turn buffer several times over.
        "content.scenes.clockwork.clockwork_state._summarizer_fn",
        lambda: None,
    ), patch.object(
        storyteller_module, "build_storyteller_messages", recording_build
    ):
        session = SessionStore().create(seed=SEED, llm_fn=llm)
        state = session.engine.state
        run.start = {
            "world_day": state.world_day,
            "evil_progress": state.evil_progress,
            "location_id": state.location_id,
        }

        for index in range(TURNS):
            action, beat, tool_calls = policy(state)
            llm.turn = index + 1
            llm.beat = beat
            llm.tool_calls = tool_calls

            # Force the background world tick every turn: production runs it
            # once per `world.tick_interval_seconds` of REAL time, which no
            # test should wait for. This models a player who thinks.
            state.last_sim_tick_at = 0.0

            try:
                payload = run_turn(session, f"The player chooses: {action}")
            except Exception as exc:  # noqa: BLE001 — recorded, then asserted on
                run.error = f"turn {index + 1} ({action}): {type(exc).__name__}: {exc}"
                break

            run.payloads.append(payload)
            run.quest_events.extend(payload.get("quest_events", []))
            run.rows.append(
                {
                    "turn": state.turn_number,
                    "day": state.world_day,
                    "hour": state.world_hour,
                    "location_id": state.location_id,
                    "action": action,
                    "hp": state.stats.hp,
                    "stamina": state.stats.stamina,
                    "stamina_cap": state.effective_stamina_cap,
                    "hunger": round(state.hunger, 1),
                    "evil_progress": state.evil_progress,
                    "evil_phase": state.evil_phase.value,
                    "awareness": state.awareness,
                    "active_arc": state.active_arc,
                    "arcs_unlocked": list(state.arcs_unlocked),
                }
            )

            if index + 1 == RESUME_AFTER_TURN:
                run.resume = _resume_check(session)

        run.prompts = llm.storyteller_prompts
        run.ledger_facts = len(session.ledger.facts)
        run.final_state = session.engine.state

    return run


def _resume_check(session: Any) -> dict[str, Any]:
    """
    Reload the autosave into a fresh SessionStore and diff it against the live
    run.

    Returns the two save dicts plus the ledger sizes, so a mismatch can be
    reported as a field list rather than "assert a == b" on a 40-key dict.
    """
    live = session.engine.state.to_save_dict()
    live_ledger = session.ledger.to_dict()

    resumed = SessionStore().resume(session.save_id, llm_fn=lambda _m: "")
    loaded = resumed.engine.state.to_save_dict()
    loaded_ledger = resumed.ledger.to_dict()

    differing = sorted(
        key for key in set(live) | set(loaded) if live.get(key) != loaded.get(key)
    )
    return {
        "save_id": session.save_id,
        "differing_fields": differing,
        "live_turn": live.get("turn_number"),
        "loaded_turn": loaded.get("turn_number"),
        "live_facts": len(live_ledger.get("facts", [])),
        "loaded_facts": len(loaded_ledger.get("facts", [])),
        "live_buffer": len(live_ledger.get("turn_buffer", [])),
        "loaded_buffer": len(loaded_ledger.get("turn_buffer", [])),
        "live_clock": live.get("world_clock_hours"),
        "loaded_clock": loaded.get("world_clock_hours"),
    }


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def baker_run(tmp_path_factory: pytest.TempPathFactory) -> Playthrough:
    """Forty turns of never leaving the village. Run once, asserted many times."""
    reset_save_store()
    run = play("baker", baker_policy, tmp_path_factory.mktemp("baker_saves"))
    reset_save_store()
    return run


@pytest.fixture(scope="module")
def road_run(tmp_path_factory: pytest.TempPathFactory) -> Playthrough:
    """Forty turns of walking the only dangerous road in the game."""
    reset_save_store()
    run = play("road", road_policy, tmp_path_factory.mktemp("road_saves"))
    reset_save_store()
    return run


@pytest.fixture(scope="module")
def runs(baker_run: Playthrough, road_run: Playthrough) -> list[Playthrough]:
    return [baker_run, road_run]


# ---------------------------------------------------------------------------
# 1. the run completes at all
# ---------------------------------------------------------------------------


def test_no_unhandled_exception(runs: list[Playthrough]) -> None:
    """
    Forty turns of the whole stack with no exception escaping run_turn.

    Quest evaluation, media, autosave and the agents all have their own
    swallow-and-continue guards; this asserts none of them was needed.
    """
    for run in runs:
        assert not run.error, f"{run.error}\n{run.table()}"
        assert len(run.rows) == TURNS, (
            f"{run.name} stopped after {len(run.rows)} turns\n{run.table()}"
        )


def test_every_turn_payload_is_json_serializable(runs: list[Playthrough]) -> None:
    """
    Everything here is jsonify'd and emitted over the socket.

    Raw bytes anywhere in the tree -- as the TTS client used to return -- takes
    the whole turn down, and it only shows up on the turn that happens to carry
    audio or an image.
    """
    for run in runs:
        for index, payload in enumerate(run.payloads):
            try:
                json.dumps(payload)
            except (TypeError, ValueError) as exc:
                pytest.fail(f"{run.at(index)}\nunserializable payload: {exc}")


# ---------------------------------------------------------------------------
# 2. the clock, and the evil that hangs off it
# ---------------------------------------------------------------------------


def test_the_world_clock_advanced(runs: list[Playthrough]) -> None:
    """
    ``state.world_day += int(days_elapsed)`` with days_elapsed=0.25 was the
    only production caller. The calendar did not move for the whole life of
    the project.
    """
    for run in runs:
        end = run.rows[-1]
        assert end["day"] > run.start["world_day"], (
            f"clock did not move: started day {run.start['world_day']}, "
            f"ended day {end['day']}\n{run.table()}"
        )
        assert end["day"] >= 5, (
            f"{TURNS} turns advanced only to day {end['day']}; the clock is "
            f"barely running\n{run.at(-1)}"
        )


def test_evil_rose_with_the_clock(runs: list[Playthrough]) -> None:
    """The point of the whole system: it ticks whether you engage or not."""
    for run in runs:
        end = run.rows[-1]
        assert end["evil_progress"] > run.start["evil_progress"], (
            f"evil did not advance over {TURNS} turns and "
            f"{end['day'] - run.start['world_day']} days\n{run.at(-1)}"
        )


def test_evil_never_recedes(runs: list[Playthrough]) -> None:
    """Monotonic by construction; asserted because nothing else asserts it."""
    for run in runs:
        previous = run.start["evil_progress"]
        for index, row in enumerate(run.rows):
            assert row["evil_progress"] >= previous, (
                f"evil went backward: {previous} -> {row['evil_progress']}\n"
                f"{run.at(index)}"
            )
            previous = row["evil_progress"]


def test_the_baker_pays_the_same_clock_as_the_traveller(
    baker_run: Playthrough, road_run: Playthrough
) -> None:
    """
    "Evil ticks in the background whether they become a hero or a baker."

    Not an equality: the bakery's evil_multiplier is 0.7 and Millhaven's is
    1.2, so the roads should be worse. It must not be free to stay home.
    """
    baker_end = baker_run.rows[-1]["evil_progress"]
    road_end = road_run.rows[-1]["evil_progress"]
    assert baker_end > 0.0, f"the baker's world stood still\n{baker_run.at(-1)}"
    assert road_end >= baker_end * 0.9, (
        f"the dangerous road advanced evil less than staying home: "
        f"road={road_end:.5f} baker={baker_end:.5f}"
    )


# ---------------------------------------------------------------------------
# 3. persistence
# ---------------------------------------------------------------------------


def test_a_mid_run_save_resumes_identically(runs: list[Playthrough]) -> None:
    """
    The old ``to_dict(include_hidden=)`` dropped both AgentMinds, so a round
    trip reset evil progress, awareness and trust to defaults -- and the client
    called /api/game/new on every reconnect, which discarded the run outright.
    """
    for run in runs:
        check = run.resume
        assert check, f"{run.name}: no resume check ran"
        assert check["differing_fields"] == [], (
            f"{run.name}: save round trip changed {check['differing_fields']}\n"
            f"{run.at(RESUME_AFTER_TURN - 1)}"
        )
        assert check["live_clock"] == check["loaded_clock"], (
            f"{run.name}: world clock did not survive the round trip: "
            f"{check['live_clock']} -> {check['loaded_clock']}"
        )
        assert check["live_facts"] == check["loaded_facts"], (
            f"{run.name}: ledger facts lost on resume: "
            f"{check['live_facts']} -> {check['loaded_facts']}"
        )
        assert check["live_buffer"] == check["loaded_buffer"], (
            f"{run.name}: turn buffer lost on resume: "
            f"{check['live_buffer']} -> {check['loaded_buffer']}"
        )


# ---------------------------------------------------------------------------
# 4. the prompt
# ---------------------------------------------------------------------------


def test_the_assembled_prompt_never_exceeds_the_budget(
    runs: list[Playthrough],
) -> None:
    """
    The memory layer's own contract: whatever the ledger, summary, lore block
    and turn buffer grow to, ``build_storyteller_messages`` returns something
    that fits. Nothing defends the budget at runtime by design (see
    engine/memory/budget.py) -- it is asserted here instead.
    """
    budget = default_budget()
    for run in runs:
        assert run.assembled, f"{run.name}: no prompts were assembled"
        for index, messages in enumerate(run.assembled):
            tokens = estimate_messages(messages)
            assert tokens <= budget.available, (
                f"{run.name}: assembled prompt {index + 1} of "
                f"{len(run.assembled)} estimated {tokens} tokens against a "
                f"budget of {budget.available}\n"
                f"{run.at(min(index, len(run.rows) - 1))}"
            )


# REGRESSION GUARD. This was an xfail: _build_messages ran the whole PRE
# interceptor chain over the system blocks AFTER build_storyteller_messages
# had fitted them to the budget, so LoreInjectInterceptor appended a lore
# block per system message, none of it counted. ~7.5k sent against a 6198
# budget, over the 8192 window once reserve_output is added, and invisible
# until someone seeds the lore DB. Lore now lives in context.py, inside the
# budget; only the awareness gate runs after fitting.
def test_the_prompt_that_is_sent_also_fits_the_budget(
    runs: list[Playthrough],
) -> None:
    """The budget that matters is the one on the bytes that reach the model."""
    budget = default_budget()
    for run in runs:
        for index, messages in enumerate(run.prompts):
            tokens = estimate_messages(messages)
            assert tokens <= budget.available, (
                f"{run.name}: sent prompt {index + 1} of {len(run.prompts)} "
                f"estimated {tokens} tokens against a budget of "
                f"{budget.available}\n{run.at(min(index, len(run.rows) - 1))}"
            )


def test_the_storyteller_saw_its_own_earlier_turns(runs: list[Playthrough]) -> None:
    """
    The whole point of the ledger. It was written every turn and read by
    nothing, so the narrator began each turn with no idea what it had said.
    """
    for run in runs:
        assert len(run.prompts) >= TURNS, (
            f"{run.name}: only {len(run.prompts)} Storyteller prompts for "
            f"{TURNS} turns"
        )
        final = "\n".join(m.get("content", "") for m in run.prompts[-1])
        marks = [
            f"{MARK} {turn:03d}"
            for turn in range(1, TURNS)
            if f"{MARK} {turn:03d}" in final
        ]
        assert marks, (
            f"{run.name}: the last prompt carried no earlier narration at all\n"
            f"{run.at(-1)}"
        )
        assert f"The player chooses: {run.rows[-2]['action']}" in final, (
            f"{run.name}: the last prompt did not carry the previous player "
            f"action\n{run.at(-2)}"
        )


def test_the_ledger_accumulated_facts(runs: list[Playthrough]) -> None:
    """Engine-sourced facts -- quests, deaths, effects -- must pile up."""
    for run in runs:
        assert run.ledger_facts > 0, (
            f"{run.name}: {TURNS} turns produced no ledger facts\n{run.table()}"
        )


# ---------------------------------------------------------------------------
# 5. quests and arcs
# ---------------------------------------------------------------------------


def test_at_least_one_quest_completed(runs: list[Playthrough]) -> None:
    """
    ``GameState.quests`` had no writer anywhere for four PRs. Four arcs were
    documented and none of them existed in code.
    """
    for run in runs:
        completed = [e["quest_id"] for e in run.quest_events if e["kind"] == "completed"]
        started = [e["quest_id"] for e in run.quest_events if e["kind"] == "started"]
        assert started, f"{run.name}: no quest ever started\n{run.table()}"
        assert completed, (
            f"{run.name}: {len(started)} quests started, none completed: "
            f"{started}\n{run.table()}"
        )


def test_the_baker_never_unlocks_the_whisper_arc(baker_run: Playthrough) -> None:
    """
    The Whisper gate is awareness >= 15 on top of the caravan having come.
    A player who never goes looking must never be dragged across it -- that is
    the difference between an arc and a timer.
    """
    final = baker_run.final_state
    assert final is not None
    assert "whisper" not in final.arcs_unlocked, (
        f"the baker was pulled into the Whisper arc at awareness "
        f"{final.awareness}\n{baker_run.table()}"
    )
    assert final.awareness < 15, (
        f"the baker's awareness reached {final.awareness} without leaving "
        f"Edgewood\n{baker_run.table()}"
    )


def test_the_road_run_goes_somewhere_the_baker_does_not(
    baker_run: Playthrough, road_run: Playthrough
) -> None:
    """The two runs must actually diverge, or the pair proves nothing."""
    baker_places = {r["location_id"] for r in baker_run.rows}
    road_places = {r["location_id"] for r in road_run.rows}
    assert "millhaven_gate" in road_places, (
        f"the road run never reached Millhaven\n{road_run.table()}"
    )
    assert "millhaven_gate" not in baker_places, (
        f"the baker left the village\n{baker_run.table()}"
    )


# ---------------------------------------------------------------------------
# 6. the soft-lock
# ---------------------------------------------------------------------------


def test_stamina_never_pins_at_zero(runs: list[Playthrough]) -> None:
    """
    Travel spent stamina; nothing in the codebase raised it. Five round trips
    to Millhaven left the player at 0 with every edge refusing on "Not enough
    stamina" and no action in the game able to give any back.

    Resting must therefore always be reachable, and a run must never end its
    last stretch pinned at the floor.
    """
    for run in runs:
        longest = worst = 0
        worst_index = 0
        for index, row in enumerate(run.rows):
            if row["stamina"] <= 0:
                longest += 1
                if longest > worst:
                    worst = longest
                    worst_index = index
            else:
                longest = 0
        assert worst <= 2, (
            f"{run.name}: stamina sat at 0 for {worst} consecutive turns\n"
            f"{run.at(worst_index)}\n{run.table()}"
        )
        assert run.rows[-1]["stamina"] > 0, (
            f"{run.name}: the run ended pinned at 0 stamina\n{run.at(-1)}"
        )


def test_rest_is_always_a_legal_action_at_zero_stamina(
    runs: list[Playthrough],
) -> None:
    """
    The fix is structural, not statistical: from the end state of each run,
    dropped to zero stamina, resting still returns stamina. A location gate on
    rest would rebuild the soft-lock, so a downgrade to sleeping rough must
    never become a refusal.
    """
    for run in runs:
        state = run.final_state
        assert state is not None
        state.stats.stamina = 0
        outcome = survival.rest(state, "sleep_bed")
        assert outcome.get("success"), (
            f"{run.name}: rest refused at 0 stamina in {state.location_id}: "
            f"{outcome}"
        )
        assert state.stats.stamina > 0, (
            f"{run.name}: rest at {state.location_id} restored nothing: {outcome}"
        )
