"""
Quest Engine Tests
==================

The load-bearing assertions here are the negative ones.

``test_narrative_flag_rejected_when_not_declared`` and
``test_model_cannot_complete_a_stage_by_flag_alone`` are the reason the module
exists: if a model can raise an arbitrary flag, or if raising a declared flag is
by itself enough to close a stage, then the engine is not adjudicating quests --
it is transcribing whatever the narration claimed.

``test_full_quiet_life_playthrough_never_unlocks_whisper`` is the design one. A
player who bakes bread for a month must reach the end of the domestic content
still in the Quiet Life arc, on a world where the caravan came and went twice.

Version: v0.1.0 [2026-08-07]
"""

from __future__ import annotations

import pytest

from engine.game import quests as quests_mod
from engine.game.plot import PlotFormula
from engine.game.quests import (
    META_KEY,
    STATUS_ACTIVE,
    STATUS_COMPLETED,
    STATUS_FAILED,
    QuestEngine,
    QuestProgress,
    arc_involvement,
    arc_order,
    evaluate_condition,
    load_arcs,
    load_quests,
    progress_records,
)
from engine.game.state import EvilPhase, GameState, InventoryItem
from engine.memory.ledger import StoryLedger

DAY = 24.0


@pytest.fixture(autouse=True)
def _fresh_content() -> None:
    """Content is process-cached; drop it so ordering between tests cannot matter."""
    quests_mod.reset_cache()


def _set_day(state: GameState, day: int, hour: int = 9) -> None:
    """Move the clock without going through travel or rest."""
    state.world_clock_hours = (day - 1) * DAY + hour


def _seen(state: GameState, event_id: str, day: int) -> None:
    """Record a world event as having occurred, the way observe() would."""
    state.world_events.append(
        {"event_id": event_id, "day": day, "expires_day": day + 2}
    )
    QuestEngine.observe(state)
    state.world_events.clear()


# ---------------------------------------------------------------------------
# Content sanity
# ---------------------------------------------------------------------------


def test_content_pack_shape() -> None:
    """Four arcs, six quests each, every stage engine-completable."""
    arcs = load_arcs()
    assert set(arcs) == {"quiet_life", "whisper", "march", "convergence"}

    definitions = load_quests()
    assert len(definitions) == 24

    per_arc: dict[str, int] = {}
    for quest_id, definition in definitions.items():
        per_arc[definition["arc"]] = per_arc.get(definition["arc"], 0) + 1
        assert definition["stages"], f"{quest_id} has no stages"
        for stage in definition["stages"]:
            assert stage.get("id"), f"{quest_id} has an unnamed stage"
            assert stage.get("objective"), f"{quest_id}:{stage['id']} has no objective"
            assert stage.get("complete_when"), (
                f"{quest_id}:{stage['id']} has no engine-evaluable completion"
            )
    assert per_arc == {
        "quiet_life": 6,
        "whisper": 6,
        "march": 6,
        "convergence": 6,
    }


def test_arc_order_is_monotonic_in_involvement() -> None:
    assert arc_order("quiet_life") < arc_order("whisper") < arc_order("march")
    assert arc_order("march") < arc_order("convergence")
    assert arc_involvement("quiet_life") == 0.0
    assert arc_involvement("convergence") == 35.0
    assert arc_involvement("no_such_arc") == 0.0


def test_every_narrative_flag_is_reachable_from_some_stage() -> None:
    """
    No quest may declare a flag it never uses.

    A flag the model is allowed to set but which no ``complete_when`` reads is
    a dead lever: the model spends a tool call and nothing can ever happen.
    """
    for quest_id, definition in load_quests().items():
        declared = set(definition.get("narrative_flags") or [])
        for stage in definition["stages"]:
            declared.update(stage.get("narrative_flags") or [])
        referenced = set()

        def _walk(node: object) -> None:
            if isinstance(node, dict):
                for key, value in node.items():
                    if key in ("flag", "not_flag"):
                        referenced.update(
                            str(v) for v in (value if isinstance(value, list) else [value])
                        )
                    else:
                        _walk(value)
            elif isinstance(node, list):
                for item in node:
                    _walk(item)

        _walk(definition["stages"])
        assert declared <= referenced, (
            f"{quest_id} declares unread narrative flags: {declared - referenced}"
        )


# ---------------------------------------------------------------------------
# Arc gates
# ---------------------------------------------------------------------------


def test_quiet_life_is_unlocked_by_default() -> None:
    state = GameState()
    QuestEngine.evaluate(state)
    assert state.arcs_unlocked == ["quiet_life"]
    assert state.active_arc == "quiet_life"


def test_whisper_unlocks_exactly_at_its_threshold() -> None:
    """
    Caravan seen, the wait elapsed, and awareness at the gate -- not before.

    The wait is three days now, not ten: the R-06 retune fit the whole doom
    arc inside roughly forty days, and a ten-day quarantine on the first
    pushback arc spent a third of a run before pushing back was possible
    (games/clockwork-dark/data/quests/arcs.yaml).
    """
    state = GameState()
    _set_day(state, 6)
    _seen(state, "caravan_arrival", 6)

    # Days elapsed but awareness short.
    _set_day(state, 16)
    state.awareness = 14.9
    QuestEngine.evaluate(state)
    assert "whisper" not in state.arcs_unlocked

    # Awareness reached but not enough days.
    other = GameState()
    _set_day(other, 6)
    _seen(other, "caravan_arrival", 6)
    _set_day(other, 8)
    other.awareness = 40.0
    QuestEngine.evaluate(other)
    assert "whisper" not in other.arcs_unlocked

    # Both.
    state.awareness = 15.0
    QuestEngine.evaluate(state)
    assert "whisper" in state.arcs_unlocked
    assert state.active_arc == "whisper"


def test_whisper_never_unlocks_without_the_caravan() -> None:
    state = GameState()
    _set_day(state, 40)
    state.awareness = 20.0
    QuestEngine.evaluate(state)
    assert "whisper" not in state.arcs_unlocked


def test_march_unlocks_on_either_gate() -> None:
    by_travel = GameState()
    by_travel.location_id = "millhaven_gate"
    QuestEngine.evaluate(by_travel)
    assert "march" in by_travel.arcs_unlocked
    assert by_travel.active_arc == "march"

    by_awareness = GameState()
    by_awareness.awareness = 24.9
    QuestEngine.evaluate(by_awareness)
    assert "march" not in by_awareness.arcs_unlocked
    by_awareness.awareness = 25.0
    QuestEngine.evaluate(by_awareness)
    assert "march" in by_awareness.arcs_unlocked


def test_convergence_unlocks_on_phase_or_awareness() -> None:
    by_phase = GameState(evil_progress=0.5)
    assert by_phase.evil_phase is EvilPhase.SPREADING
    QuestEngine.evaluate(by_phase)
    assert "convergence" in by_phase.arcs_unlocked

    by_awareness = GameState()
    by_awareness.awareness = 49.9
    QuestEngine.evaluate(by_awareness)
    assert "convergence" not in by_awareness.arcs_unlocked
    by_awareness.awareness = 50.0
    QuestEngine.evaluate(by_awareness)
    assert "convergence" in by_awareness.arcs_unlocked


def test_arcs_never_regress() -> None:
    """Awareness can fall. The arc the player is in cannot."""
    state = GameState()
    state.awareness = 60.0
    QuestEngine.evaluate(state)
    assert state.active_arc == "convergence"
    unlocked = list(state.arcs_unlocked)

    state.awareness = 0.0
    state.evil_progress = 0.0
    state.location_id = "forest_clearing"
    QuestEngine.evaluate(state)
    assert state.active_arc == "convergence"
    assert state.arcs_unlocked == unlocked


def test_arc_unlock_emits_one_event_only_once() -> None:
    state = GameState()
    state.location_id = "millhaven_gate"
    first = [e for e in QuestEngine.evaluate(state) if e.kind == "arc_unlocked"]
    assert [e.quest_id for e in first] == ["march"]
    second = [e for e in QuestEngine.evaluate(state) if e.kind == "arc_unlocked"]
    assert second == []


# ---------------------------------------------------------------------------
# Predicates -- one assertion per supported type
# ---------------------------------------------------------------------------


def test_predicate_flag_and_not_flag() -> None:
    state = GameState()
    assert not evaluate_condition(state, {"flag": "x"})
    assert evaluate_condition(state, {"not_flag": "x"})
    state.flags["x"] = True
    assert evaluate_condition(state, {"flag": "x"})
    assert not evaluate_condition(state, {"not_flag": "x"})


def test_predicate_at_location_and_visited() -> None:
    state = GameState()
    state.location_id = "edgewood_bakery"
    assert evaluate_condition(state, {"at_location": "edgewood_bakery"})
    assert evaluate_condition(state, {"at_location": ["forest_clearing", "edgewood_bakery"]})
    assert not evaluate_condition(state, {"visited": "edgewood_bakery"})
    QuestEngine.observe(state)
    assert evaluate_condition(state, {"visited": "edgewood_bakery"})
    # Visits are durable: leaving does not un-visit.
    state.location_id = "forest_clearing"
    assert evaluate_condition(state, {"visited": "edgewood_bakery"})


def test_predicate_item_quantity() -> None:
    state = GameState()
    state.inventory.append(InventoryItem(id="loaf", name="Loaf", qty=2))
    assert evaluate_condition(state, {"has_item": {"id": "loaf", "qty": 2}})
    assert not evaluate_condition(state, {"has_item": {"id": "loaf", "qty": 3}})
    assert evaluate_condition(state, {"not_has_item": {"id": "loaf", "qty": 3}})


def test_predicate_disposition_requires_a_ledger() -> None:
    """No ledger means unproven, and unproven means the stage stays shut."""
    state = GameState()
    ledger = StoryLedger()
    ledger.adjust_disposition("npc_maris", 5, clamp_step=False)
    ledger.adjust_disposition("npc_maris", 20, clamp_step=False)
    condition = {"disposition": {"npc": "npc_maris", "min": 20}}

    assert not evaluate_condition(state, condition)
    assert evaluate_condition(state, condition, ledger=ledger)
    assert not evaluate_condition(
        state, {"disposition": {"npc": "npc_maris", "min": 40}}, ledger=ledger
    )


def test_predicate_reputation() -> None:
    state = GameState()
    state.reputations["edgewood"] = 12
    assert evaluate_condition(state, {"reputation": {"faction": "edgewood", "min": 12}})
    assert not evaluate_condition(state, {"reputation": {"faction": "edgewood", "min": 13}})
    assert evaluate_condition(state, {"reputation": {"faction": "militia", "max": 0}})


def test_predicate_day_hour_and_time_of_day() -> None:
    state = GameState()
    _set_day(state, 5, hour=23)
    assert evaluate_condition(state, {"min_day": 5})
    assert not evaluate_condition(state, {"min_day": 6})
    assert evaluate_condition(state, {"max_day": 5})
    assert evaluate_condition(state, {"time_of_day": "night"})
    # Wraps across midnight rather than evaluating to the empty set.
    assert evaluate_condition(state, {"hour_between": [22, 4]})
    _set_day(state, 5, hour=3)
    assert evaluate_condition(state, {"hour_between": [22, 4]})
    _set_day(state, 5, hour=12)
    assert not evaluate_condition(state, {"hour_between": [22, 4]})
    assert evaluate_condition(state, {"hour_between": [10, 15]})


def test_predicate_awareness_phase_gold_and_stat() -> None:
    state = GameState(evil_progress=0.6)
    state.awareness = 30.0
    state.stats.gold = 20
    state.stats.craft = 12
    assert evaluate_condition(state, {"min_awareness": 30})
    assert evaluate_condition(state, {"max_awareness": 30})
    assert evaluate_condition(state, {"min_phase": "spreading"})
    assert not evaluate_condition(state, {"min_phase": "consuming"})
    assert evaluate_condition(state, {"max_phase": "spreading"})
    assert evaluate_condition(state, {"min_gold": 20})
    assert evaluate_condition(state, {"min_stat": {"stat": "craft", "min": 12}})
    assert not evaluate_condition(state, {"min_stat": {"stat": "craft", "min": 13}})


def test_predicate_quest_state_and_completed() -> None:
    state = GameState()
    assert evaluate_condition(state, {"quest_state": {"quest": "lost_goat", "status": "not_started"}})
    state.quests["lost_goat"] = QuestProgress(
        quest_id="lost_goat", stage_index=2, status=STATUS_ACTIVE
    ).to_dict()
    assert evaluate_condition(state, {"quest_state": {"quest": "lost_goat", "status": "active"}})
    assert evaluate_condition(state, {"quest_state": {"quest": "lost_goat", "stage_at_least": 2}})
    assert not evaluate_condition(state, {"quest_completed": "lost_goat"})
    state.quests["lost_goat"]["status"] = STATUS_COMPLETED
    assert evaluate_condition(state, {"quest_completed": "lost_goat"})


def test_predicate_events_and_days_since() -> None:
    state = GameState()
    _set_day(state, 6)
    assert not evaluate_condition(state, {"event_seen": "caravan_arrival"})
    _seen(state, "caravan_arrival", 6)
    assert evaluate_condition(state, {"event_seen": "caravan_arrival"})
    # The event has expired out of world_events, which is exactly why the day
    # is written down separately.
    assert not evaluate_condition(state, {"event_active": "caravan_arrival"})

    _set_day(state, 15)
    assert not evaluate_condition(
        state, {"days_since_event": {"event": "caravan_arrival", "days": 10}}
    )
    _set_day(state, 16)
    assert evaluate_condition(
        state, {"days_since_event": {"event": "caravan_arrival", "days": 10}}
    )
    # Short form: the sibling event_seen clause supplies the event.
    assert evaluate_condition(
        state, [{"event_seen": "caravan_arrival"}, {"days_since_event": 10}]
    )


def test_predicate_arc_stage_timing_and_procgen() -> None:
    state = GameState()
    state.procgen.bakery_job_day = 5
    _set_day(state, 4)
    assert not evaluate_condition(state, {"procgen_day": "bakery_job_day"})
    _set_day(state, 5)
    assert evaluate_condition(state, {"procgen_day": "bakery_job_day"})
    assert not evaluate_condition(state, {"procgen_day": "no_such_field"})

    assert evaluate_condition(state, {"arc_unlocked": "quiet_life"})
    assert evaluate_condition(state, {"active_arc": "quiet_life"})

    record = QuestProgress(quest_id="x", started_day=1, stage_started_day=3)
    assert evaluate_condition(state, {"days_in_stage": 2}, progress=record)
    assert not evaluate_condition(state, {"days_in_stage": 3}, progress=record)
    assert evaluate_condition(state, {"days_since_started": 4}, progress=record)
    # Stage-relative predicates cannot be judged without a record.
    assert not evaluate_condition(state, {"days_in_stage": 2})

    state.turn_number = 7
    assert evaluate_condition(state, {"min_turn": 7})


def test_condition_groups_and_unknown_predicates() -> None:
    state = GameState()
    state.flags["a"] = True
    assert evaluate_condition(state, {"any": [{"flag": "a"}, {"flag": "b"}]})
    assert not evaluate_condition(state, {"all": [{"flag": "a"}, {"flag": "b"}]})
    assert evaluate_condition(state, {"none": [{"flag": "b"}]})
    assert not evaluate_condition(state, {"none": [{"flag": "a"}]})
    assert evaluate_condition(state, None)
    assert evaluate_condition(state, [])
    # A predicate this build does not understand must fail shut, never open.
    assert not evaluate_condition(state, {"vibes_are_good": True})
    assert not evaluate_condition(state, "nonsense")


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


def test_quest_starts_when_procgen_day_is_reached() -> None:
    """The gap this closes: procgen.bakery_job_day had no reader anywhere."""
    state = GameState()
    state.procgen.bakery_job_day = 4
    _set_day(state, 3)
    QuestEngine.evaluate(state)
    assert "bakery_apprentice" not in progress_records(state)

    _set_day(state, 4)
    events = QuestEngine.evaluate(state)
    assert any(e.kind == "started" and e.quest_id == "bakery_apprentice" for e in events)
    record = progress_records(state)["bakery_apprentice"]
    assert record.status == STATUS_ACTIVE
    assert record.started_day == 4


def test_stage_advances_only_when_every_predicate_holds() -> None:
    state = GameState()
    state.procgen.bakery_job_day = 1
    QuestEngine.evaluate(state)

    # Flag set but standing in the wrong room.
    state.location_id = "forest_clearing"
    assert QuestEngine.set_narrative_flag(state, "nf_bakery_asked_for_work")
    QuestEngine.evaluate(state)
    assert progress_records(state)["bakery_apprentice"].stage_index == 0

    state.location_id = "edgewood_bakery"
    events = QuestEngine.evaluate(state)
    assert any(e.kind == "stage_complete" for e in events)
    assert progress_records(state)["bakery_apprentice"].stage_index == 1


def test_quest_completes_and_pays_through_the_effect_dispatcher() -> None:
    state = GameState()
    state.procgen.bakery_job_day = 1
    state.stats.gold = 0
    ledger = StoryLedger()
    QuestEngine.evaluate(state, ledger)

    state.location_id = "edgewood_bakery"
    QuestEngine.set_narrative_flag(state, "nf_bakery_asked_for_work")
    QuestEngine.evaluate(state, ledger)

    _set_day(state, 1, hour=5)  # stage 2: before dawn at the bakery
    QuestEngine.evaluate(state, ledger)
    assert progress_records(state)["bakery_apprentice"].stage_index == 2

    _set_day(state, 8, hour=9)  # stage 3: the paid week
    events = QuestEngine.evaluate(state, ledger)
    assert any(e.kind == "completed" and e.quest_id == "bakery_apprentice" for e in events)

    record = progress_records(state)["bakery_apprentice"]
    assert record.status == STATUS_COMPLETED
    assert state.stats.gold == 6
    assert state.reputations["edgewood"] == 8
    assert state.flags["quest_bakery_apprentice_done"] is True
    assert any("baker's hands" in f.text for f in ledger.facts)


def test_stage_expiry_fails_the_quest_on_the_day_after_the_deadline() -> None:
    state = GameState()
    state.procgen.bakery_job_day = 1
    QuestEngine.evaluate(state)
    state.location_id = "edgewood_bakery"
    QuestEngine.set_narrative_flag(state, "nf_bakery_asked_for_work")
    QuestEngine.evaluate(state)
    _set_day(state, 1, hour=5)
    QuestEngine.evaluate(state)
    record = progress_records(state)["bakery_apprentice"]
    assert record.stage_index == 2 and record.stage_started_day == 1

    # Off the premises, so the stage cannot close on its own terms. Not
    # Millhaven -- that trips this quest's fail_when and would prove nothing
    # about the deadline.
    state.location_id = "forest_clearing"

    # expires_after_days: 9 -- day 10 is still inside the window.
    _set_day(state, 10)
    QuestEngine.evaluate(state)
    assert progress_records(state)["bakery_apprentice"].status == STATUS_ACTIVE

    _set_day(state, 11)
    events = QuestEngine.evaluate(state)
    assert any(e.kind == "failed" for e in events)
    assert progress_records(state)["bakery_apprentice"].status == STATUS_FAILED


def test_fail_when_predicate_fails_the_quest() -> None:
    """Walking to Millhaven mid-apprenticeship costs the job, by content rule."""
    state = GameState()
    state.procgen.bakery_job_day = 1
    QuestEngine.evaluate(state)
    state.location_id = "edgewood_bakery"
    QuestEngine.set_narrative_flag(state, "nf_bakery_asked_for_work")
    QuestEngine.evaluate(state)
    _set_day(state, 1, hour=5)
    QuestEngine.evaluate(state)

    state.location_id = "millhaven_gate"
    events = QuestEngine.evaluate(state)
    failed = [e for e in events if e.kind == "failed"]
    assert failed and failed[0].quest_id == "bakery_apprentice"
    assert progress_records(state)["bakery_apprentice"].status == STATUS_FAILED
    assert state.reputations["edgewood"] == -3
    # A failed quest is finished: it does not resume or re-fail.
    assert QuestEngine.evaluate(state) == [] or all(
        e.quest_id != "bakery_apprentice" or e.kind != "failed"
        for e in QuestEngine.evaluate(state)
    )


def test_evaluate_is_idempotent() -> None:
    state = GameState()
    state.procgen.bakery_job_day = 1
    first = QuestEngine.evaluate(state)
    assert first
    assert QuestEngine.evaluate(state) == []


# ---------------------------------------------------------------------------
# The model's one lever
# ---------------------------------------------------------------------------


def test_narrative_flag_rejected_when_not_declared() -> None:
    """
    The whole point of the module.

    A flag no active quest declared is refused and leaves no trace on state --
    otherwise the model can write arbitrary keys into ``state.flags`` and any
    ``complete_when`` that reads a flag becomes model-controlled.
    """
    state = GameState()
    state.procgen.bakery_job_day = 1
    QuestEngine.evaluate(state)

    assert QuestEngine.allowed_narrative_flags(state) == {"nf_bakery_asked_for_work"}
    assert QuestEngine.set_narrative_flag(state, "nf_bakery_asked_for_work") is True

    for bogus in ("quest_bakery_apprentice_done", "nf_goat_found", "", "main_quest_started"):
        assert QuestEngine.set_narrative_flag(state, bogus) is False
        assert bogus not in state.flags


def test_narrative_flags_are_scoped_to_the_current_stage() -> None:
    """A later stage's flag is out of reach, so stages cannot be skipped."""
    state = GameState()
    state.procgen.bakery_job_day = 1
    QuestEngine.evaluate(state)
    # lost_goat's second-stage flag belongs to a quest that has not started.
    assert QuestEngine.set_narrative_flag(state, "nf_goat_found") is False

    _set_day(state, 2)
    state.location_id = "edgewood_square"
    QuestEngine.evaluate(state)
    QuestEngine.evaluate(state)
    assert "lost_goat" in progress_records(state)
    # Stage 0 is in play; stage 1's flag is not yet offered.
    assert "nf_goat_promised" in QuestEngine.allowed_narrative_flags(state)
    assert "nf_goat_found" not in QuestEngine.allowed_narrative_flags(state)
    assert QuestEngine.set_narrative_flag(state, "nf_goat_found") is False


def test_model_cannot_complete_a_stage_by_flag_alone() -> None:
    """
    Raising every legal flag is not a completion.

    The bakery's second stage needs a room and an hour. No sequence of tool
    calls the model can make will satisfy either.
    """
    state = GameState()
    state.procgen.bakery_job_day = 1
    QuestEngine.evaluate(state)
    state.location_id = "edgewood_bakery"
    QuestEngine.set_narrative_flag(state, "nf_bakery_asked_for_work")
    QuestEngine.evaluate(state)
    assert progress_records(state)["bakery_apprentice"].stage_index == 1

    _set_day(state, 1, hour=13)
    for _ in range(5):
        for flag in list(QuestEngine.allowed_narrative_flags(state)):
            QuestEngine.set_narrative_flag(state, flag)
        QuestEngine.evaluate(state)
    assert progress_records(state)["bakery_apprentice"].stage_index == 1


def test_accepted_flags_are_recorded_on_the_quest() -> None:
    state = GameState()
    state.procgen.bakery_job_day = 1
    QuestEngine.evaluate(state)
    QuestEngine.set_narrative_flag(state, "nf_bakery_asked_for_work")
    assert progress_records(state)["bakery_apprentice"].flags_seen == [
        "nf_bakery_asked_for_work"
    ]


# ---------------------------------------------------------------------------
# Prompt surface and persistence
# ---------------------------------------------------------------------------


def test_active_objectives_are_prompt_ready() -> None:
    state = GameState()
    state.procgen.bakery_job_day = 1
    QuestEngine.evaluate(state)
    lines = QuestEngine.active_objectives(state)

    assert lines == ["Flour on Your Sleeves - Ask Maris at the bakery whether she needs hands."]
    for line in lines:
        # Nothing a narrator could leak as a number or an id.
        assert "nf_" not in line
        assert "quest_" not in line
        assert "{" not in line and "}" not in line
        assert line == line.strip()


def test_objectives_track_the_current_stage_and_drop_on_completion() -> None:
    state = GameState()
    state.procgen.bakery_job_day = 1
    QuestEngine.evaluate(state)
    state.location_id = "edgewood_bakery"
    QuestEngine.set_narrative_flag(state, "nf_bakery_asked_for_work")
    QuestEngine.evaluate(state)
    assert "bank the oven" in QuestEngine.active_objectives(state)[0]

    state.quests["bakery_apprentice"]["status"] = STATUS_COMPLETED
    assert QuestEngine.active_objectives(state) == []


def test_ledger_open_threads_track_active_quests() -> None:
    """``open_threads`` was declared for quest ids and never written to."""
    state = GameState()
    state.procgen.bakery_job_day = 1
    ledger = StoryLedger()
    QuestEngine.evaluate(state, ledger)
    assert ledger.open_threads == ["bakery_apprentice"]
    assert any("Began" in fact.text for fact in ledger.facts)


def test_quest_round_trips_through_save_dict() -> None:
    state = GameState()
    state.procgen.bakery_job_day = 1
    _set_day(state, 3)
    state.location_id = "edgewood_bakery"
    QuestEngine.evaluate(state)
    QuestEngine.set_narrative_flag(state, "nf_bakery_asked_for_work")
    QuestEngine.evaluate(state)

    saved = state.to_save_dict()
    restored = GameState.from_dict(saved)

    before = progress_records(state)["bakery_apprentice"]
    after = progress_records(restored)["bakery_apprentice"]
    assert after == before
    assert restored.quests[META_KEY]["visited"] == state.quests[META_KEY]["visited"]
    assert restored.active_arc == state.active_arc
    assert restored.arcs_unlocked == state.arcs_unlocked
    # And the restored save keeps playing from where it stopped.
    assert QuestEngine.active_objectives(restored) == QuestEngine.active_objectives(state)


def test_meta_block_is_never_mistaken_for_a_quest() -> None:
    state = GameState(location_id="forest_clearing")
    QuestEngine.evaluate(state)
    assert META_KEY in state.quests
    assert META_KEY not in progress_records(state)
    assert state.to_client_dict()["quests"][META_KEY]["visited"] == ["forest_clearing"]


# ---------------------------------------------------------------------------
# Plot formula
# ---------------------------------------------------------------------------


def test_plot_involvement_uses_the_arc_not_a_dead_flag() -> None:
    """
    ``flags["main_quest_started"]`` was worth 15 points to a flag no code set.

    Quiet Life is deliberately worth zero: a baker is not behind schedule.
    """
    state = GameState()
    baseline = PlotFormula.compute(state)
    assert PlotFormula.arc_weight(state) == 0.0

    state.flags["main_quest_started"] = True
    assert PlotFormula.compute(state) == baseline

    # Entering an arc means having a quest record in it. A march quest makes
    # the player a march participant wherever the world ladder stands.
    state.quests["militia_press"] = {"quest_id": "militia_press", "status": "active"}
    assert PlotFormula.compute(state) == pytest.approx(baseline + 20.0)
    state.quests["the_sacrifice"] = {"quest_id": "the_sacrifice", "status": "active"}
    assert PlotFormula.compute(state) == pytest.approx(baseline + 35.0)


def test_plot_involvement_ignores_the_world_driven_arc_ladder() -> None:
    """
    ``active_arc`` climbs on WORLD state (Convergence unlocks on
    ``min_phase: spreading``), so it cannot be the involvement term: a baker
    who never asked a question was collecting Convergence's 35 points for
    standing in a village while the world fell -- and involvement feeds the
    doom clock's inaction bonus (R-06), so the most disengaged run in the game
    slowed its own doom exactly when the doom got going.
    """
    state = GameState()
    baseline = PlotFormula.compute(state)
    state.active_arc = "convergence"
    assert PlotFormula.compute(state) == pytest.approx(baseline)
    assert PlotFormula.arc_weight(state) == 0.0


def test_plot_involvement_survives_an_unknown_arc() -> None:
    state = GameState()
    state.active_arc = "arc_from_a_future_content_pack"
    assert PlotFormula.compute(state) >= 0.0


# ---------------------------------------------------------------------------
# The design assertion
# ---------------------------------------------------------------------------


def test_full_quiet_life_playthrough_never_unlocks_whisper() -> None:
    """
    A month of domestic play, two caravans, every quiet_life quest finished --
    and the player is still in the Quiet Life arc.

    "The game never punishes the baker for baking" is only true if the baker
    path is genuinely self-contained. The Whisper gate is awareness, not the
    caravan: Odran arrives on a schedule the player does not control, so an
    arrival-only gate would drag every baker into the horror story on a dice
    roll they never made.
    """
    state = GameState()
    state.procgen.bakery_job_day = 2
    ledger = StoryLedger()

    # Odran comes and goes twice, entirely without the player's involvement.
    _set_day(state, 6)
    _seen(state, "caravan_arrival", 6)
    _set_day(state, 20)
    _seen(state, "tinker_camp", 20)

    domestic = [
        "nf_bakery_asked_for_work",
        "nf_goat_promised",
        "nf_goat_found",
        "nf_mural_examined",
        "nf_mural_asked_elders",
        "nf_roof_offered",
        "nf_stores_counted",
        "nf_stores_shared",
        "nf_festival_agreed",
    ]
    rooms = [
        "edgewood_bakery",
        "edgewood_square",
        "forest_clearing",
        "edgewood_square",
    ]

    for day in range(1, 41):
        for hour in (5, 9, 14, 23):
            _set_day(state, day, hour)
            state.location_id = rooms[day % len(rooms)]
            for flag in domestic:
                QuestEngine.set_narrative_flag(state, flag)
            QuestEngine.evaluate(state, ledger)
            assert "whisper" not in state.arcs_unlocked, (
                f"whisper unlocked on day {day} at {state.awareness} awareness"
            )

    records = progress_records(state)
    finished = [
        quest_id
        for quest_id, record in records.items()
        if record.status == STATUS_COMPLETED
    ]
    # The domestic content really did play out; this is not a vacuous pass.
    assert len(finished) >= 4, finished
    assert state.awareness < 15.0
    assert state.active_arc == "quiet_life"
    assert state.arcs_unlocked == ["quiet_life"]
    assert state.reputations.get("edgewood", 0) > 0


# ---------------------------------------------------------------------------
# Skills
# ---------------------------------------------------------------------------


def test_quest_skills_return_legible_receipts(engine) -> None:
    """A rejection must tell the model what it could have said instead."""
    import json

    import engine.skills.builtin.quests as quest_skills

    state = engine.state
    state.procgen.bakery_job_day = 1
    QuestEngine.evaluate(state)

    listing = json.loads(quest_skills.query_quests())
    assert listing["active_arc"] == "quiet_life"
    assert listing["narrative_flags"] == ["nf_bakery_asked_for_work"]
    assert listing["objectives"]

    rejected = json.loads(quest_skills.set_narrative_flag("i_finished_the_quest"))
    assert rejected["success"] is False
    assert rejected["allowed"] == ["nf_bakery_asked_for_work"]

    accepted = json.loads(quest_skills.set_narrative_flag("nf_bakery_asked_for_work"))
    assert accepted["success"] is True
    assert state.flags["nf_bakery_asked_for_work"] is True


def test_quest_skills_are_storyteller_only() -> None:
    import engine.skills.builtin.quests  # noqa: F401 -- registration side effect
    from engine.skills.registry import (
        AGENT_ASSISTANT,
        AGENT_STORYTELLER,
        SKILL_REGISTRY,
    )

    for name in ("set_narrative_flag", "query_quests"):
        definition = SKILL_REGISTRY.get(name)
        assert definition is not None, f"{name} not registered"
        assert definition.callable_by(AGENT_STORYTELLER)
        assert not definition.callable_by(AGENT_ASSISTANT)

    # There is deliberately no tool that completes a quest.
    for definition in SKILL_REGISTRY.all_tools():
        assert "complete_quest" not in definition.name
        assert "advance_quest" not in definition.name
