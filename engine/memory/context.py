"""
Context Assembly
================

Builds the Storyteller's message array from engine state plus the ledger.

Ordering is deliberate and is the whole point of this module:

    0  persona + rules + few-shot   stable, byte-identical every turn
    1  world state                  volatile
    2  the story so far             slow-moving summary
    3  threads: facts, names, debts volatile
    4  lore (RAG)                   volatile
    5+ recent turns                 volatile
    n  the player's action          volatile

Stable content first means the KV prefix cache survives between turns. The old
prompt put HP and the current hour in the middle of the standing rules, so
nothing cached and every turn re-processed the entire prompt.

Version: v0.2.0 [2026-08-07]
"""

from __future__ import annotations

import logging

from typing import Any, Optional

from engine.config import get_config
from engine.game.state import GameState
from engine.memory.budget import BlockSet, Budget
from engine.memory.ledger import StoryLedger

logger = logging.getLogger(__name__)


def default_budget() -> Budget:
    """
    Token allowance for the narration prompt.

    Derived from the RESOLVED model rather than the static config guess. The
    config said 8192; the loaded model reports a 20,224 real context window
    (`loaded_context_length`, which is also not the 1,048,576 it advertises).
    Budgeting against the static number threw away more than half the window
    on every turn.
    """
    try:
        return Budget.for_profile("big")
    except Exception as exc:  # noqa: BLE001 — never block a turn on introspection
        logger.debug("[memory] Profile budget unavailable, using config: %s", exc)
        cfg = get_config()
        return Budget(
            context_tokens=int(cfg.get("lmstudio.context_tokens", 8192)),
            reserve_output=int(cfg.get("lmstudio.reserve_output", 900)),
        )


def present_npc_ids(state: GameState) -> tuple[str, ...]:
    """NPC ids at the player's location, used to bias memory retrieval."""
    from engine.world.world_sim import merge_npcs_at_location

    if not state.procgen.npcs:
        return ()
    return tuple(
        str(n.get("id"))
        for n in merge_npcs_at_location(state, state.location_id)
        if n.get("id")
    )


def build_storyteller_messages(
    state: GameState,
    ledger: StoryLedger,
    player_action: str,
    *,
    evil_snapshot: Optional[dict[str, Any]] = None,
    lore_block: str = "",
    receipts: Optional[list[dict[str, Any]]] = None,
    include_examples: bool = True,
    budget: Optional[Budget] = None,
    retry_note: str = "",
) -> list[dict[str, str]]:
    """
    Assemble the Storyteller prompt.

    Args:
        state: Current game state.
        ledger: Narrative memory.
        player_action: What the player just did.
        evil_snapshot: GM-only escalation state.
        lore_block: Pre-rendered RAG context, if any.
        receipts: Tool receipts to narrate (Phase B). When present, the model is
            told these are authoritative.
        include_examples: Few-shot exchanges. Disable for the cheap mechanics
            pass where they cost tokens and buy nothing.
        budget: Token allowance; defaults from config.
        retry_note: Evaluator feedback for a repair attempt.

    Returns:
        Chat message array, trimmed to fit the budget.
    """
    # Imported here, not at module scope. `engine.agents.prompts` lives in a
    # package whose __init__ eagerly imports StorytellerAgent, which imports
    # this module -- so a top-level import made `import engine.memory` fail
    # outright whenever it was the first engine package loaded. It only
    # appeared to work because something else always imported engine.agents
    # first.
    from engine.agents.prompts import (
        storyteller_examples,
        storyteller_persona,
        memory_blocks,
        receipts_block,
        world_state_block,
    )

    budget = budget or default_budget()
    npc_ids = present_npc_ids(state)
    summary_block, threads_block = memory_blocks(ledger, present_npc_ids=npc_ids)

    blocks = BlockSet()
    blocks.add("persona", "system", storyteller_persona(), evictable=False)
    blocks.add(
        "world",
        "system",
        world_state_block(state, evil_snapshot or {}),
        evictable=False,
    )
    blocks.add("summary", "system", summary_block)
    blocks.add("threads", "system", threads_block)
    blocks.add("lore", "system", lore_block)

    # GM directives -- evil-phase tone, what the Dark has already done, the
    # Storyteller's disposition -- as ONE budgeted block.
    #
    # Deliberately not run through the PRE interceptor chain. That chain shapes
    # a system prompt in place, and StorytellerAgent runs it over every system
    # message AFTER this function has already fitted the prompt to the budget,
    # so each shaper's text is appended once per block and none of the copies
    # are counted. That is R-01, measured at 7,550 tokens against a 6,198
    # budget. Building the text from an empty seed and adding it here means it
    # is fitted like everything else.
    from engine.agents.governance import get_governance

    blocks.add(
        "directives",
        "system",
        get_governance().build_directives(state, player_action=player_action),
    )

    messages = blocks.fit(budget)

    if include_examples:
        # Examples sit immediately after the stable system blocks so they stay
        # inside the cacheable prefix.
        insert_at = 2
        messages = messages[:insert_at] + storyteller_examples() + messages[insert_at:]

    for record in ledger.turn_buffer:
        messages.append({"role": "user", "content": record.player_action})
        if record.narration:
            messages.append({"role": "assistant", "content": record.narration})

    if receipts:
        block = receipts_block(receipts)
        if block:
            messages.append({"role": "system", "content": block})

    messages.append({"role": "user", "content": player_action})

    if retry_note:
        messages.append({"role": "user", "content": retry_note})

    return _trim_history(messages, budget)


def _trim_history(
    messages: list[dict[str, str]],
    budget: Budget,
) -> list[dict[str, str]]:
    """
    Drop the oldest turn-history pairs until the prompt fits.

    History is trimmed rather than the system blocks because the running
    summary already covers the same ground in compressed form.
    """
    from engine.memory.budget import estimate_messages

    if estimate_messages(messages) <= budget.available:
        return messages

    # Everything before the first non-example user/assistant history pair is
    # structural and must survive; find where history begins.
    system_count = 0
    for message in messages:
        if message["role"] == "system":
            system_count += 1
        else:
            break

    head = messages[:system_count]
    tail = messages[system_count:]

    # Always keep the final player action (and any retry note).
    keep_tail = 2 if tail and tail[-1]["role"] == "user" else 1
    while len(tail) > keep_tail and estimate_messages(head + tail) > budget.available:
        tail.pop(0)

    return head + tail
