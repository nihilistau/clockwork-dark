"""
The world moved
===============

A per-turn journal of what changed while the player was not looking, so the
narrator can mention it on the turn it happened and never again.

WHAT IT CLOSES. The engine already produced this material and threw it away.
``clocks.resolve`` returned the beats it fired and ``advance_time`` discarded
the list; roughly fifteen authored ``text:`` lines across the shipped clock
tables were read only when a beat forced a scene; ``ledger.expire_promises``
returned the promises it broke to nobody; and a veiled meter crossing a band
was a ready story beat that nothing surfaced. Each entry is now written by the
system that caused it, in that system's own words.

PRESENTATION, NOT RULES. Nothing reads this journal to make a decision -- the
change it describes has already been applied through ``effects.apply_effect``
or the clock. It is saved with the state all the same, deliberately: an entry
pending at save time is a change the player has not yet been told about, and
losing it on reload would be the same bug one layer down.

THE LIFECYCLE, and why it has two steps. Prompt assembly MARKS what it
rendered (``mark_shown``); the turn CLEARS what was marked once the narrator
has written (``clear_shown``). Draining at build time would lose every entry
on an evaluator retry, which rebuilds the prompt; clearing everything at the
end of the turn would lose what the quest step journalled after the narration
was already written.

Version: v0.1.0 [2026-09-23]
"""

from __future__ import annotations

from typing import Any

#: Every kind of entry, named for the system that writes it. A closed set, so
#: a typo is a ValueError at the writer rather than an entry nobody renders.
KINDS = ("beat", "event", "rumor", "promise", "band", "standing", "gossip")

#: The most a single turn carries. A long rest can cross a lot; the narrator
#: needs the latest few, not an inventory.
MAX_ENTRIES = 8


def note(state: Any, kind: str, text: str, *, location_id: str = "") -> None:
    """
    Journal one change. Deduplicated on its text; oldest dropped past the cap.

    Args:
        state: Live game state.
        kind: One of ``KINDS``.
        text: The words the narrator will see. Authored prose where the source
            has it; never an id, never a veiled number.
        location_id: Where it happened, when it is a local thing. Empty means
            the player would know wherever they stand.

    Raises:
        ValueError: On an unknown kind -- a programming error at the writer.
    """
    if kind not in KINDS:
        raise ValueError(f"unknown moved kind {kind!r}")
    text = " ".join(str(text or "").split())
    if not text:
        return
    journal = state.moved
    if any(entry.get("text") == text for entry in journal):
        return
    journal.append({"kind": kind, "text": text, "location_id": str(location_id or "")})
    del journal[:-MAX_ENTRIES]


def visible(state: Any) -> list[dict[str, Any]]:
    """The entries the player could know about from where they stand."""
    here = str(getattr(state, "location_id", "") or "")
    return [
        entry
        for entry in state.moved
        if not entry.get("location_id") or entry.get("location_id") == here
    ]


def mark_shown(state: Any) -> None:
    """Flag what the prompt just rendered. Idempotent across retries."""
    for entry in visible(state):
        entry["shown"] = True


def clear_shown(state: Any) -> None:
    """Drop what the narrator has now been told. Unshown entries carry over."""
    state.moved = [entry for entry in state.moved if not entry.get("shown")]


__all__ = ["KINDS", "MAX_ENTRIES", "clear_shown", "mark_shown", "note", "visible"]
