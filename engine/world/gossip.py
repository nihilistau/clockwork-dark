"""
Gossip
======

Facts moving between people who share a room.

WHAT THIS IS FOR. Subject memory made every character remember what passed
between them and the player. That is still a hub and spokes: everyone knows
what they saw, nobody knows what anyone else saw, and the world stays a set of
private conversations. Gossip is the edge between the spokes -- you can be
talked about behind your back, and a thing you said to one person can be waiting
for you in somebody else's mouth two days later.

DELIBERATELY SMALL. One transfer per tick at most, only between NPCs who are in
the same place, and only facts the player was actually involved in. A pass that
moved everything everywhere would flatten the whole point: the interesting
state is the UNEVEN one, where the baker knows and the gate corporal does not.

ATTRIBUTION IS THE FEATURE. What lands in the listener is not the bare fact but
where it came from -- "heard from Maris: you asked about the tinker". That is
what lets a narrator write somebody being cagey about a source, and it is what
makes the memory legible when a player asks how anyone knew.

Draws on ``world_rng(state, GOSSIP)`` -- its own stream, because this fires on
the background tick, which runs a variable number of times depending on how
long the player sat on the menu. Borrowing another stream would let real-world
idle time shift an encounter roll (CLAUDE.md rule 4).

Version: v0.1.0 [2026-08-15]
"""

from __future__ import annotations

import logging
import random
from typing import Any, Optional

from engine.game.rng import GOSSIP, world_rng

logger = logging.getLogger(__name__)

#: Chance per tick that anything is said at all. Low: gossip should feel like
#: weather rather than a broadcast network, and a player who notices it every
#: single day stops reading it as a world and starts reading it as a mechanic.
SPREAD_CHANCE = 0.35

#: How many notes a listener will carry about things they were told. The note
#: cap in the ledger is the real bound; this keeps one loud subject from
#: filling it.
MAX_HEARD_PER_SUBJECT = 3


def spread(
    state: Any,
    ledger: Any,
    *,
    rng: Optional[random.Random] = None,
) -> list[str]:
    """
    Move at most one fact between two NPCs sharing a location.

    Args:
        state: Live game state. Read only -- gossip writes to the LEDGER, which
            is where memory lives; nothing here touches meters or the clock.
        ledger: The story ledger.
        rng: Override, for tests. Otherwise the named gossip stream.

    Returns:
        Human-readable lines describing what moved, for the turn log. Empty is
        the ordinary case and not a failure.
    """
    if state is None or ledger is None:
        return []

    draw = rng if rng is not None else world_rng(state, GOSSIP)
    if draw.random() >= SPREAD_CHANCE:
        return []

    try:
        from engine.game.locations import LOCATIONS
        from engine.world.world_sim import merge_npcs_at_location
    except Exception as exc:  # noqa: BLE001 -- a story with no graph has no rooms
        logger.debug("[gossip] No world to gossip in: %s", exc)
        return []

    # Rooms with at least two people in them, in a stable order so a seed
    # replays. `sorted` matters more than it looks: dict order over LOCATIONS
    # is insertion order, which content edits change.
    crowded: list[tuple[str, list[str]]] = []
    for place_id in sorted(LOCATIONS):
        try:
            here = [
                str(npc.get("id"))
                for npc in merge_npcs_at_location(state, place_id)
                if npc.get("id")
            ]
        except Exception:  # noqa: BLE001 -- one bad room must not stop the pass
            continue
        if len(here) >= 2:
            crowded.append((place_id, sorted(here)))
    if not crowded:
        return []

    place_id, present = crowded[draw.randrange(len(crowded))]
    speaker = present[draw.randrange(len(present))]
    listeners = [npc for npc in present if npc != speaker]
    if not listeners:
        return []
    listener = listeners[draw.randrange(len(listeners))]

    # Only what the speaker actually knows, and only facts -- a speaker cannot
    # pass on somebody else's disposition or a note about themselves.
    tellable = [f for f in ledger.recall(speaker, limit=4) if f.text]
    if not tellable:
        return []
    fact = tellable[draw.randrange(len(tellable))]

    record = ledger.subject(listener, kind="npc")
    if fact.id in record.known_facts:
        return []

    speaker_name = (getattr(ledger, "names", {}) or {}).get(speaker) or speaker
    record.known_facts.append(fact.id)
    heard = sum(1 for note in record.notes if note.startswith("heard from "))
    if heard < MAX_HEARD_PER_SUBJECT:
        ledger.note(listener, f"heard from {speaker_name}: {fact.text}", kind="npc")

    logger.debug(
        "[gossip] Fact travelled (operation=spread, from=%s, to=%s, at=%s)",
        speaker,
        listener,
        place_id,
    )
    return [f"{speaker_name} told {listener} about: {fact.text}"]
