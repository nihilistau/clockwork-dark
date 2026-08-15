"""
The prompt that was budgeted and the prompt that goes on the wire are the same.

Two separate defects, both invisible because an over-budget prompt does not
raise -- LM Studio just truncates it, from the front, taking the persona first.

1. ``BlockSet.fit`` was given the whole window, and the caller then appended the
   few-shot examples, the turn buffer, the receipts, the agreed block and the
   player's own line ON TOP. Everything after ``fit`` was unaccounted for.

2. ``_trim_history`` located the evictable history by counting leading
   ``system`` messages -- and the examples are spliced in at index 2, so the
   count stopped there and treated every later system block as droppable
   history. The running summary is one of those. ``EVICTION_ORDER`` puts the
   summary LAST on purpose ("losing it costs the model every memory it has")
   and the trimmer was popping it FIRST.
"""

from __future__ import annotations

from engine.memory.budget import Budget, estimate_messages
from engine.memory.context import build_storyteller_messages
from engine.memory.ledger import StoryLedger, TurnRecord
from engine.game.state import GameState


def _crowded_ledger(weight: int = 40) -> StoryLedger:
    """
    A ledger whose turn buffer alone will overflow any sane window.

    The buffer is a bounded deque, so pressure comes from long exchanges rather
    than many of them -- which is also the realistic shape: narration is the
    biggest thing in the prompt.
    """
    ledger = StoryLedger()
    for index in range(ledger.turn_buffer.maxlen or 6):
        ledger.record_turn(
            TurnRecord(
                turn=index,
                day=1,
                location_id="forest_clearing",
                player_action=(
                    f"The player does the {index}th considered thing. "
                    + "They take their time about it. " * weight
                ),
                narration=(
                    f"Turn {index}. "
                    + "The room holds its quiet and the hour moves on. " * weight
                ),
            )
        )
    return ledger


def _summary_text(messages) -> str:
    return "\n".join(
        m["content"] for m in messages if m["role"] == "system"
    )


def test_the_assembled_prompt_respects_the_budget_it_was_given():
    """
    Including everything appended after ``fit`` -- which used to be free.
    """
    state = GameState(location_id="forest_clearing")
    ledger = _crowded_ledger()
    budget = Budget(context_tokens=4000, reserve_output=400)

    messages = build_storyteller_messages(
        state,
        ledger,
        "The player asks what the smoke means.",
        budget=budget,
        receipts=[{"skill": "move_to", "result": {"ok": True}, "success": True}],
        agreed_block="AGREED: the baker speaks first.",
    )

    assert estimate_messages(messages) <= budget.available, (
        "the prompt overflows the window it was budgeted against; LM Studio "
        "would silently truncate it from the front"
    )


def test_the_running_summary_outlives_the_turn_history():
    """
    Under pressure, history goes and the summary stays -- EVICTION_ORDER's
    stated contract, which the trimmer inverted.
    """
    state = GameState(location_id="forest_clearing")
    ledger = _crowded_ledger()
    ledger.summary = (
        "SUMMARY-SENTINEL: the player came out of the wood, took work at the "
        "bakery, and has not yet gone up to the gate."
    )
    budget = Budget(context_tokens=3000, reserve_output=400)

    messages = build_storyteller_messages(
        state,
        ledger,
        "The player asks what the smoke means.",
        budget=budget,
    )

    kept = _summary_text(messages)
    assert "SUMMARY-SENTINEL" in kept, (
        "the running summary was evicted before the turn history -- the "
        "trimmer is treating system blocks after the few-shot splice as "
        "droppable history"
    )
    # And the pressure was real: history actually got trimmed.
    assert estimate_messages(messages) <= budget.available


def test_the_players_own_line_always_survives():
    """The request cannot be trimmed out of the request."""
    state = GameState(location_id="forest_clearing")
    ledger = _crowded_ledger(120)
    budget = Budget(context_tokens=2200, reserve_output=400)

    messages = build_storyteller_messages(
        state,
        ledger,
        "SENTINEL-ACTION: the player asks what the smoke means.",
        budget=budget,
    )

    assert messages[-1]["content"].startswith("SENTINEL-ACTION")


def test_history_is_dropped_as_whole_exchanges():
    """
    Never a narrator's reply without the line it was replying to.
    """
    state = GameState(location_id="forest_clearing")
    ledger = _crowded_ledger()
    budget = Budget(context_tokens=3000, reserve_output=400)

    messages = build_storyteller_messages(
        state,
        ledger,
        "The player asks what the smoke means.",
        budget=budget,
    )

    # Walk the history region: an assistant message must always be preceded by
    # a user message.
    for index, message in enumerate(messages):
        if message["role"] == "assistant":
            assert messages[index - 1]["role"] == "user", (
                "an orphaned narration survived trimming -- the model is "
                "reading an answer to a question that was dropped"
            )
