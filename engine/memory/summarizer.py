"""
Rolling Summarizer
==================

Compresses evicted turns into the running summary.

Nothing leaves the turn buffer without passing through here, so the model's
long-term memory degrades gracefully rather than falling off a cliff at turn
seven.

Runs after the turn completes, in the "utility" inference lane so it can no
longer stall the narration stream the player is watching.

FAILURE IS LOUD NOW
-------------------
When the LLM call returned an empty string -- which is exactly what a reasoning
model does when ``max_tokens`` is spent on thinking -- this module fell back to
deterministic compression with no log line at all, then logged "Summary
updated". The player's long-term memory silently degraded to keyword salad and
nothing anywhere said so. Every fallback path now says which one it took and
why.

Version: v0.3.0 [2026-08-08]
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from engine.memory.ledger import StoryLedger, TurnRecord

logger = logging.getLogger(__name__)

MAX_SUMMARY_WORDS = 250

SUMMARIZER_PROMPT = """\
You maintain the running memory of a dark-fantasy RPG session.

Rewrite the summary below so it also covers the new events. Rules:
- At most {max_words} words. Prose, past tense, third person ("the traveller").
- Keep EVERY proper noun: people, places, objects with names.
- Keep every unresolved promise, debt, threat, and open question.
- Keep what changed about the world, not what the weather was like.
- Drop moment-to-moment detail. Compress old material harder than new.
- Output only the summary. No preamble, no headings, no commentary.
"""


def _render_turns(turns: list[TurnRecord]) -> str:
    lines = []
    for record in turns:
        lines.append(f"[day {record.day}, {record.location_id}]")
        lines.append(f"The traveller: {record.player_action}")
        if record.narration:
            lines.append(record.narration)
        for outcome in record.outcomes:
            lines.append(f"({outcome})")
    return "\n".join(lines)


def _fallback_summary(existing: str, turns: list[TurnRecord]) -> str:
    """
    Deterministic compression used when no LLM is available.

    Keeps the summary honest rather than letting it silently stop updating when
    the model is down.
    """
    parts = [existing.strip()] if existing.strip() else []
    for record in turns:
        sentence = record.narration.strip().split(".")[0]
        if sentence:
            parts.append(f"On day {record.day} at {record.location_id}, {sentence}.")
    text = " ".join(parts)
    words = text.split()
    if len(words) > MAX_SUMMARY_WORDS:
        # Drop from the front: recent material matters more.
        text = " ".join(words[-MAX_SUMMARY_WORDS:])
    return text


def summarize(
    ledger: StoryLedger,
    evicted: list[TurnRecord],
    *,
    llm_fn: Optional[Callable[[list[dict[str, Any]]], str]] = None,
    max_words: int = MAX_SUMMARY_WORDS,
) -> str:
    """
    Fold evicted turns into the ledger's summary. Returns the new summary.

    Never raises: losing the summary must not lose the turn.
    """
    if not evicted:
        return ledger.summary

    if llm_fn is None:
        logger.warning(
            "[memory] No summarizer LLM; using deterministic compression "
            "(operation=summarize, turns=%s). Long-term memory will degrade.",
            len(evicted),
        )
        ledger.summary = _fallback_summary(ledger.summary, evicted)
        ledger.summary_through_turn = evicted[-1].turn
        return ledger.summary

    messages = [
        {"role": "system", "content": SUMMARIZER_PROMPT.format(max_words=max_words)},
        {
            "role": "user",
            "content": (
                f"CURRENT SUMMARY:\n{ledger.summary or '(nothing yet)'}\n\n"
                f"NEW EVENTS:\n{_render_turns(evicted)}"
            ),
        },
    ]

    try:
        result = (llm_fn(messages) or "").strip()
    except Exception as exc:  # noqa: BLE001 — summarization is best-effort
        logger.warning("[memory] Summarizer failed (operation=summarize): %s", exc)
        result = ""

    if not result:
        # The confirmed production path: the model returned "" because it spent
        # the whole token cap reasoning. This used to fall through in silence.
        logger.error(
            "[memory] Summarizer returned NOTHING; falling back to deterministic "
            "compression (operation=summarize, turns=%s). If the model is a "
            "reasoning model, its max_tokens went entirely to reasoning — the "
            "summarizer must run on a reasoning='off' profile.",
            len(evicted),
        )
        result = _fallback_summary(ledger.summary, evicted)
        used_llm = False
    else:
        used_llm = True

    words = result.split()
    if len(words) > max_words * 1.3:
        result = " ".join(words[: int(max_words * 1.3)])

    ledger.summary = result
    ledger.summary_through_turn = evicted[-1].turn
    logger.info(
        "[memory] Summary updated (operation=summarize, through_turn=%s, words=%s, "
        "source=%s)",
        ledger.summary_through_turn,
        len(result.split()),
        "llm" if used_llm else "deterministic-fallback",
    )
    return ledger.summary
