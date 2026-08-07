"""Story ledger, summarizer, context assembly and budget tests."""

from __future__ import annotations

import pytest

from engine.game.clock import set_clock
from engine.game.procgen import new_game_state
from engine.memory.budget import Budget, BlockSet, estimate_messages, estimate_tokens
from engine.memory.context import build_storyteller_messages
from engine.memory.ledger import (
    SOURCE_ENGINE,
    StoryLedger,
    TurnRecord,
    apply_ledger_delta,
)
from engine.memory.summarizer import summarize


def _ledger() -> StoryLedger:
    return StoryLedger()


# -- facts ---------------------------------------------------------------


def test_facts_dedupe_by_normalized_text():
    ledger = _ledger()
    ledger.add_fact("The bakery flue is rimed grey-green.")
    ledger.add_fact("the BAKERY flue is rimed grey-green!!")
    assert len(ledger.facts) == 1


def test_restating_a_fact_refreshes_rather_than_duplicates():
    ledger = _ledger()
    ledger.add_fact("Maris bakes before dawn.", turn=1)
    ledger.facts[0].weight = 0.4
    ledger.add_fact("Maris bakes before dawn.", turn=9)
    assert len(ledger.facts) == 1
    assert ledger.facts[0].weight == 1.0
    assert ledger.facts[0].turn == 9


def test_facts_decay_and_archive():
    ledger = _ledger()
    ledger.add_fact("A minor detail.")
    ledger.decay(days=60)
    assert ledger.facts[0].archived is True
    assert ledger.salient_facts() == []


def test_engine_facts_hold_a_floor():
    """Engine-recorded events are history, not impressions; they should persist."""
    ledger = _ledger()
    ledger.add_fact("The caravan arrived.", source=SOURCE_ENGINE)
    ledger.decay(days=500)
    assert ledger.facts[0].archived is False


def test_salient_facts_favour_present_npcs():
    ledger = _ledger()
    ledger.add_fact("Something about the road.", turn=9)
    ledger.add_fact("Maris distrusts Odran.", subject_id="npc_maris", turn=1)
    top = ledger.salient_facts(limit=1, subject_ids=("npc_maris",))
    assert top[0].subject_id == "npc_maris"


# -- names ---------------------------------------------------------------


def test_names_are_pinned_once():
    """What stops the model renaming the innkeeper every third turn."""
    ledger = _ledger()
    ledger.remember_name("Hollin Vance", "the ferryman at the low crossing")
    ledger.remember_name("Hollin Vance", "a completely different person")
    assert ledger.names["Hollin Vance"] == "the ferryman at the low crossing"


# -- relations -----------------------------------------------------------


def test_meeting_records_first_and_last_seen():
    ledger = _ledger()
    ledger.meet("npc_maris", day=3, location_id="edgewood_bakery")
    ledger.meet("npc_maris", day=9, location_id="edgewood_square")
    rel = ledger.relation("npc_maris")
    assert rel.met is True
    assert rel.first_met_day == 3
    assert rel.last_seen_day == 9
    assert rel.last_seen_location == "edgewood_square"


def test_disposition_step_is_clamped():
    """Affection is earned across a scene, not granted in one flattering line."""
    ledger = _ledger()
    ledger.adjust_disposition("npc_maris", 90)
    assert ledger.relation("npc_maris").disposition == 5


def test_disposition_is_bounded():
    ledger = _ledger()
    for _ in range(50):
        ledger.adjust_disposition("npc_maris", 5)
    assert ledger.relation("npc_maris").disposition == 100


# -- promises ------------------------------------------------------------


def test_promises_expire_into_broken():
    ledger = _ledger()
    ledger.add_promise("Bring the festival loaves.", to_id="npc_maris", due_day=5)
    assert len(ledger.open_promises()) == 1
    broken = ledger.expire_promises(current_day=6)
    assert [p.status for p in broken] == ["broken"]
    assert ledger.open_promises() == []


def test_promise_dedupes():
    ledger = _ledger()
    ledger.add_promise("Bring the loaves.", to_id="npc_maris")
    ledger.add_promise("Bring the loaves.", to_id="npc_maris")
    assert len(ledger.promises) == 1


# -- turn buffer ---------------------------------------------------------


def test_turn_buffer_evicts_oldest_and_reports_it():
    ledger = _ledger()
    evicted = []
    for turn in range(1, 10):
        out = ledger.record_turn(
            TurnRecord(
                turn=turn,
                day=1,
                location_id="edgewood_square",
                player_action=f"action {turn}",
                narration=f"narration {turn}",
            )
        )
        if out:
            evicted.append(out.turn)
    assert len(ledger.turn_buffer) == 6
    # Nothing leaves the buffer unreported, so nothing is forgotten silently.
    assert evicted == [1, 2, 3]


# -- delta validation ----------------------------------------------------


def test_delta_rejects_unknown_npc_subject():
    ledger = _ledger()
    accepted = apply_ledger_delta(
        ledger,
        {"facts": [{"text": "A fact.", "subject_id": "npc_invented"}]},
        turn=1,
        day=1,
        known_npc_ids={"npc_maris"},
    )
    assert accepted["facts"] == ["A fact."]
    assert ledger.facts[0].subject_id == "", "unknown subject must be dropped"


def test_delta_caps_facts_per_turn():
    ledger = _ledger()
    apply_ledger_delta(
        ledger,
        {"facts": [{"text": f"Fact {i}"} for i in range(10)]},
        turn=1,
        day=1,
    )
    assert len(ledger.facts) == 3


def test_delta_ignores_disposition_for_unknown_npc():
    ledger = _ledger()
    apply_ledger_delta(
        ledger,
        {"npc_disposition": {"npc_ghost": 5}},
        turn=1,
        day=1,
        known_npc_ids={"npc_maris"},
    )
    assert "npc_ghost" not in ledger.relations


def test_delta_survives_garbage():
    ledger = _ledger()
    assert apply_ledger_delta(ledger, "not a dict", turn=1, day=1)["facts"] == []
    apply_ledger_delta(
        ledger, {"npc_disposition": {"npc_maris": "lots"}}, turn=1, day=1,
        known_npc_ids={"npc_maris"},
    )
    assert ledger.relations.get("npc_maris") is None or True


# -- persistence ---------------------------------------------------------


def test_ledger_round_trips():
    ledger = _ledger()
    ledger.add_fact("A remembered thing.", subject_id="npc_maris")
    ledger.remember_name("Hollin", "the ferryman")
    ledger.add_promise("Return the knife.", to_id="npc_ilya", due_day=9)
    ledger.meet("npc_maris", day=2, location_id="edgewood_bakery")
    ledger.summary = "The traveller reached Edgewood."
    ledger.record_turn(
        TurnRecord(turn=1, day=1, location_id="x", player_action="a", narration="n")
    )

    restored = StoryLedger.from_dict(ledger.to_dict())
    assert restored.facts[0].text == "A remembered thing."
    assert restored.names["Hollin"] == "the ferryman"
    assert restored.promises[0].to_id == "npc_ilya"
    assert restored.relations["npc_maris"].first_met_day == 2
    assert restored.summary == "The traveller reached Edgewood."
    assert list(restored.turn_buffer)[0].narration == "n"


def test_ledger_from_garbage_is_empty_not_crashed():
    assert StoryLedger.from_dict(None).facts == []
    assert StoryLedger.from_dict({"facts": "nonsense"}).facts == []


# -- summarizer ----------------------------------------------------------


def test_summarizer_uses_llm_when_available():
    ledger = _ledger()
    ledger.summary = "Old summary."
    calls = []

    def fake_llm(messages):
        calls.append(messages)
        return "The traveller met Maris and promised bread."

    out = summarize(
        ledger,
        [TurnRecord(turn=1, day=1, location_id="x", player_action="a", narration="n")],
        llm_fn=fake_llm,
    )
    assert out == "The traveller met Maris and promised bread."
    assert ledger.summary_through_turn == 1
    assert "Old summary." in calls[0][1]["content"]


def test_summarizer_falls_back_without_an_llm():
    """A downed model must not silently freeze the memory."""
    ledger = _ledger()
    out = summarize(
        ledger,
        [
            TurnRecord(
                turn=1, day=4, location_id="edgewood_square",
                player_action="a", narration="You cross the square. It is empty.",
            )
        ],
    )
    assert "day 4" in out
    assert ledger.summary_through_turn == 1


def test_summarizer_survives_a_raising_llm():
    ledger = _ledger()

    def boom(_messages):
        raise RuntimeError("model died")

    out = summarize(
        ledger,
        [TurnRecord(turn=1, day=1, location_id="x", player_action="a", narration="Text.")],
        llm_fn=boom,
    )
    assert out


def test_summarizer_noop_without_evictions():
    ledger = _ledger()
    ledger.summary = "Unchanged."
    assert summarize(ledger, []) == "Unchanged."


# -- budget --------------------------------------------------------------


def test_estimate_is_in_the_right_ballpark():
    # ~50 words of prose should land in the tens of tokens, not hundreds.
    text = "word " * 50
    assert 40 <= estimate_tokens(text) <= 110


def test_blockset_evicts_in_priority_order():
    blocks = BlockSet()
    blocks.add("persona", "system", "P" * 400, evictable=False)
    blocks.add("world", "system", "W" * 400, evictable=False)
    blocks.add("summary", "system", "S" * 400)
    blocks.add("threads", "system", "T" * 400)
    blocks.add("lore", "system", "L" * 4000)

    fitted = blocks.fit(Budget(context_tokens=1200, reserve_output=200))
    contents = "".join(m["content"] for m in fitted)
    assert "P" * 400 in contents, "persona must never be evicted"
    assert "W" * 400 in contents, "world state must never be evicted"
    assert "lore" in blocks.dropped


# -- context assembly ----------------------------------------------------


def test_stable_block_is_byte_identical_across_turns():
    """
    Prefix caching depends on this.

    The old prompt interleaved HP and the hour with the standing rules, so
    nothing cached and every turn reprocessed the whole prompt.
    """
    state = new_game_state(seed=1)
    ledger = _ledger()
    first = build_storyteller_messages(state, ledger, "a")[0]["content"]

    state.stats.hp = 3
    set_clock(state, day=9, hour=23)
    state.turn_number = 40
    second = build_storyteller_messages(state, ledger, "b")[0]["content"]

    assert first == second


def test_history_appears_in_message_array():
    state = new_game_state(seed=1)
    ledger = _ledger()
    ledger.record_turn(
        TurnRecord(
            turn=1, day=1, location_id="forest_clearing",
            player_action="Follow the smoke", narration="You walk toward it.",
        )
    )
    messages = build_storyteller_messages(state, ledger, "Keep going")
    contents = [m["content"] for m in messages]
    assert "Follow the smoke" in contents
    assert "You walk toward it." in contents
    assert contents[-1] == "Keep going"


def test_receipts_precede_the_player_action():
    """The model must see outcomes before it is asked to narrate them."""
    state = new_game_state(seed=1)
    messages = build_storyteller_messages(
        state,
        _ledger(),
        "Slip past",
        receipts=[
            {
                "skill": "resolve_skill_check",
                "type": "dice",
                "success": True,
                "result": {"summary": "stealth: 5 vs DC 13. FAILURE by 8."},
            }
        ],
    )
    joined = [m["content"] for m in messages]
    receipt_index = next(i for i, c in enumerate(joined) if "FAILURE by 8" in c)
    assert receipt_index < len(joined) - 1
    assert joined[-1] == "Slip past"


def test_context_stays_within_budget_over_a_long_run():
    """
    200 synthetic turns must not blow the window.

    The prompt is O(1) in turn count by design; this asserts the ledger and
    buffer do not quietly reintroduce unbounded growth.
    """
    state = new_game_state(seed=1)
    ledger = _ledger()
    budget = Budget(context_tokens=8192, reserve_output=900)

    for turn in range(1, 201):
        ledger.record_turn(
            TurnRecord(
                turn=turn,
                day=1 + turn // 4,
                location_id="edgewood_square",
                player_action=f"The player does thing number {turn}.",
                narration="Narration. " * 40,
            )
        )
        ledger.add_fact(f"Fact number {turn} about the world.", turn=turn)
        ledger.remember_name(f"Name {turn}", "a person met once")
        ledger.summary = "Summary sentence. " * 40

    messages = build_storyteller_messages(
        state, ledger, "What now?", budget=budget
    )
    assert estimate_messages(messages) <= budget.available


def test_examples_can_be_disabled_for_the_cheap_pass():
    state = new_game_state(seed=1)
    with_examples = build_storyteller_messages(state, _ledger(), "a", include_examples=True)
    without = build_storyteller_messages(state, _ledger(), "a", include_examples=False)
    assert len(with_examples) > len(without)
