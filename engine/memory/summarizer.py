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
import re
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


#: The most entries the deterministic summary keeps (the newest win).
MAX_RECAP_ENTRIES = 6

#: Where an entry may start: "On day 3, at <Place Name>: " (since v0.21.0) or
#: "On day 3 at <location_id>, " (before it). A match is only a CANDIDATE:
#: model-written prose says "On day 2 at dawn, ..." too, so ``_entry_at``
#: accepts one only when it names a place of the active story.
_ENTRY_START = re.compile(r"(?:(?<=\s)|^)On day (\d+)(,?) at ")
_LEGACY_ID = re.compile(r"([\w-]+), ")
_SNAKE_ID = re.compile(r"[a-z0-9]+(?:_[a-z0-9]+)+")
#: A sentence boundary: end punctuation, space, then a capital or a quote.
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[\"'A-Z])")
#: Titles whose full stop does not end a sentence ("Dr. Vance").
_ABBREVIATIONS = ("Dr.", "Mr.", "Mrs.", "Ms.", "St.")

Entry = tuple[int, str, str]  # (day, place name, sentence without its full stop)


def _place_name(location_id: str) -> str:
    """What the ACTIVE STORY calls a place -- never its raw id (prose)."""
    fallback = str(location_id or "").replace("_", " ").strip()
    try:
        from engine.game.locations import LOCATIONS

        row = LOCATIONS.get(location_id) or {}
        return str(row.get("name") or fallback)
    except Exception:  # noqa: BLE001 -- a summary must not be able to fail
        return fallback


def _known_places() -> tuple[set[str], list[str]]:
    """The active story's location ids, and its place names longest first."""
    try:
        from engine.game.locations import LOCATIONS

        ids = {str(loc_id) for loc_id in LOCATIONS}
    except Exception:  # noqa: BLE001 -- a summary must not be able to fail
        ids = set()
    names = sorted({name for name in (_place_name(i) for i in ids) if name}, key=len, reverse=True)
    return ids, names


def _entry_at(text: str, match: "re.Match[str]", ids: set[str], names: list[str]) -> Optional[tuple[str, int]]:
    """
    (place name, where the sentence starts) if the candidate at ``match`` is a
    deterministic entry, else None: it is prose, and is left as it was.

    The current form is accepted only with a KNOWN place name before its ": "
    -- matched whole, longest first, so a name holding ": " of its own still
    parses. The old form only with a known location id or a snake_case token
    before its ", ": "On day 2 at dawn, the knight rode out." is a model's
    sentence, not an entry. (A pre-fix entry whose id the story has since lost
    is read by its snake_case and named by its words, which the current form
    then cannot recognise again: that one entry stays as text, never dropped.)
    """
    after = match.end()
    if match.group(2) == ",":
        for name in names:
            if text.startswith(name + ": ", after):
                return name, after + len(name) + 2
        return None
    legacy = _LEGACY_ID.match(text, after)
    if legacy and (legacy.group(1) in ids or _SNAKE_ID.fullmatch(legacy.group(1))):
        return _place_name(legacy.group(1)), legacy.end()
    return None


def _split_entries(text: str) -> tuple[str, list[Entry]]:
    """
    ``text`` as (prose, entries): whatever came before the first deterministic
    entry (a model-written summary, say) is the prose, kept as written; each
    entry runs to the next. Reads the pre-v0.21.0 form ("On day 1 at
    tallow_docks, Somewhere..."), naming its place, so an old save's summary
    is repaired on its next fold or display.
    """
    ids, names = _known_places()
    found: list[tuple[int, int, str, int]] = []  # (start, day, place, sentence start)
    for match in _ENTRY_START.finditer(text):
        accepted = _entry_at(text, match, ids, names)
        if accepted is not None:
            found.append((match.start(), int(match.group(1)), accepted[0], accepted[1]))
    if not found:
        return text.strip(), []
    prose = text[: found[0][0]].strip()
    entries: list[Entry] = []
    for index, (_start, day, place, begins) in enumerate(found):
        end = found[index + 1][0] if index + 1 < len(found) else len(text)
        sentence = text[begins:end].strip()
        if sentence.endswith("."):
            sentence = sentence[:-1].rstrip()
        if sentence:
            entries.append((day, place, sentence))
    return prose, entries


def _distinct(entries: list[Entry]) -> list[Entry]:
    """
    Deduplicated and bounded: a sentence said again keeps only its LATEST
    entry (a run of turns that each open on the same ambient line -- every
    fallback-narrated turn does -- is one entry, not one per turn), and only
    the newest MAX_RECAP_ENTRIES entries survive. Recent material matters more.
    """
    seen: set[str] = set()
    kept: list[Entry] = []
    for day, place, sentence in reversed(entries):
        key = " ".join(sentence.casefold().split())
        if key in seen:
            continue
        seen.add(key)
        kept.append((day, place, sentence))
    return list(reversed(kept))[-MAX_RECAP_ENTRIES:]


def _render(prose: str, entries: list[Entry]) -> str:
    parts = [prose] if prose else []
    parts.extend(f"On day {day}, at {place}: {sentence}." for day, place, sentence in entries)
    return " ".join(parts)


def _within_words(prose: str, entries: list[Entry], limit: int) -> str:
    """
    ``prose`` and ``entries`` under ``limit`` words, cut on boundaries: the
    oldest entries go first (never the newest), then the prose loses its
    oldest SENTENCES; a word slice only if one entry alone is over the cap. A
    mid-entry cut left a headless fragment that every later fold kept as prose.
    """
    entries = list(entries)
    while len(entries) > 1 and len(_render(prose, entries).split()) > limit:
        entries.pop(0)
    text = _render(prose, entries)
    if len(text.split()) <= limit:
        return text
    budget = limit - len(_render("", entries).split())
    if prose and budget > 0:
        tail = " ".join(prose.split()[-budget:])
        stop = tail.find(". ")
        prose = tail[stop + 2:] if stop >= 0 else ""
    else:
        prose = ""
    text = _render(prose, entries)
    words = text.split()
    return text if len(words) <= limit else " ".join(words[-limit:])


def tidy_summary(text: str, *, shown: str = "") -> str:
    """
    The deterministic entries in ``text`` made readable: place names for ids,
    each sentence once, the newest MAX_RECAP_ENTRIES. Model prose is returned
    byte for byte. The resume recap shows a summary through this, so a save
    written before v0.21.0 reads cleanly at once rather than on its next
    eviction.

    ``shown``: narration the player is about to read beneath the recap. An
    entry whose sentence that narration already holds (casefolded, spaces
    normalised) is dropped, so a resumed run does not say its last line twice
    -- a fallback-narrated run opens every turn on the same sentence.
    """
    text = str(text or "")
    prose, entries = _split_entries(text)
    if not entries:
        return text
    entries = _distinct(entries)
    seen = " ".join(str(shown or "").casefold().split())
    if seen:
        entries = [e for e in entries if " ".join(e[2].casefold().split()) not in seen]
    return _render(prose, entries)


def _first_sentence(text: str) -> str:
    """
    The first sentence of ``text``, without its closing punctuation.

    It was ``split(".")[0]``, which cut "Dr. Vance waits." to "Dr": a title's
    full stop (``_ABBREVIATIONS``) does not end a sentence, and neither does a
    stop not followed by a space and a capital ("1.5 crowns").
    """
    text = " ".join(str(text or "").split())
    for match in _SENTENCE_END.finditer(text):
        head = text[:match.start()]
        if head.split()[-1] in _ABBREVIATIONS:
            continue
        return head.rstrip(".!?").strip()
    return text.rstrip(".!?").strip()


def _fallback_summary(existing: str, turns: list[TurnRecord]) -> str:
    """
    Deterministic compression used when no LLM is available.

    Keeps the summary honest rather than letting it silently stop updating when
    the model is down.

    One entry per evicted turn: "On day 3, at The Lantern House: <the turn's
    first sentence>." Named by the story's own ``locations.yaml`` (rule 5),
    never the id. WHAT IT KEEPS (v0.21.0): it used to append an entry per turn
    whatever it said, and a fallback-narrated run opens every turn on the same
    ambient line, so the resume recap repeated one sentence once per turn. Now
    a sentence already summarised moves to its newest entry instead of being
    added again (so identical turns leave one entry, dated by the latest), and
    only the newest MAX_RECAP_ENTRIES entries are kept, under the word cap,
    which drops whole entries, oldest first. A model-written summary ahead of
    the entries is kept as written; only a candidate naming a place of the
    story is read as an entry (``_entry_at``).
    """
    prose, entries = _split_entries(existing or "")
    for record in turns:
        sentence = _first_sentence(record.narration)
        if sentence:
            entries.append((record.day, _place_name(record.location_id), sentence))
    return _within_words(prose, _distinct(entries), MAX_SUMMARY_WORDS)


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
