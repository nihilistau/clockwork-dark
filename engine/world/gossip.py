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
idle time shift an encounter roll (AGENTS.md rule 4).

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

#: How far a rumour travels before it stops being worth repeating.
#:
#: THE CAP IS WHAT MAKES ONWARD TELLING SAFE. A fact used to travel exactly
#: once -- a listener who had heard something could never retell it -- so this
#: was a star around the player and never a chain. Allowing the second hop
#: without a cap turns the thing this module insists must "feel like weather"
#: into the broadcast network it says it must not be: everything reaches
#: everybody, and the interesting state is the UNEVEN one.
MAX_HOPS = 3

#: Marks a note as second-hand, and carries the hop count in a form a listener
#: can read back. Kept as plain prose rather than a structured flag: the note
#: is a string every consumer already renders, and a flag is something a
#: consumer can forget to check and leak as truth.
_HEARD_PREFIX = "heard "


def hops_of(note: str) -> int:
    """How many tellings a heard-note has been through. 0 if it is not one."""
    if not note.startswith(_HEARD_PREFIX):
        return 0
    if "going round" in note:
        return 3
    return 2 if "who had it from" in note else 1


def _key(text: str) -> str:
    """One dedupe key per fact, derived from its words."""
    return "said:" + " ".join(text.lower().split())


def _unnamed_speaker(npc_id: str) -> str:
    """
    What to call a teller the ledger has no name for.

    NEVER THE RAW ID. These notes reach the narrator through `_dossier` in
    engine/agents/prompts.py, and a prompt containing `npc_villager_3` is a
    prompt that can put `npc_villager_3` on the player's screen. Delegates to
    `npc_sim.display_name`, the one place every narrator-facing name now comes
    from, which answers "somebody" when no table names this person.
    """
    from engine.world.npc_sim import display_name

    return display_name(npc_id)


def _heard_hops(record: Any, fact_key: str) -> list[int]:
    """At what removes this listener has already been told this fact."""
    found: list[int] = []
    for known in record.known_facts:
        if not isinstance(known, str) or not known.startswith(f"{fact_key}#h"):
            continue
        try:
            found.append(int(known.rsplit("#h", 1)[1]))
        except ValueError:  # a key from before hops were recorded
            found.append(1)
    return found


def _body_of(note: str) -> str:
    """
    The fact inside a heard-note, ready to be told again. "" if there is none.

    Only the first two hops are recoverable, and deliberately: a third-hand
    note has already had the player taken out of it by `_impersonal`, and
    retelling it would be hop 4, which `retell` refuses anyway.
    """
    if not note.startswith("heard from "):
        return ""
    body = note.split(":", 1)[1].strip() if ":" in note else ""
    return body[len("they say ") :].strip() if body.startswith("they say ") else body


def _source_of(note: str) -> str:
    """Who the teller says they got it from, for the next link in the chain."""
    marker = "heard from "
    if not note.startswith(marker):
        return ""
    who = note[len(marker) :].split(":", 1)[0]
    return who.split(",", 1)[0].strip()


def retell(text: str, speaker: str, *, hops: int = 1, source: str = "") -> str:
    """
    One telling of a fact, worded for how far it has come.

    THE CONTENT NEVER CHANGES. What decays is who vouches for it and how
    firmly, so a narrator can write somebody cagey about a source or
    overconfident about something they got third-hand -- and the engine never
    records a falsehood that a later turn might state as fact. A rumour that
    could go WRONG would mean the ledger holding claims the player can check
    against real state and catch out.

        hop 1  heard from Maris: you asked about the tinker
        hop 2  heard from Corwin, who had it from Maris: they say you asked
               about the tinker
        hop 3  heard it going round: someone was asking about the tinker

    Returns "" past ``MAX_HOPS``, which is the rumour dying rather than
    circulating forever.
    """
    if hops > MAX_HOPS:
        return ""
    if hops <= 1:
        return f"heard from {speaker}: {text}"
    if hops == 2:
        chain = f"{speaker}, who had it from {source}" if source else speaker
        return f"heard from {chain}: they say {text}"
    # Third-hand: nobody remembers who said it first, and the subject blurs.
    return f"heard it going round: {_impersonal(text)}"


def _impersonal(text: str) -> str:
    """
    Take the player out of the sentence, the way a third-hand story does.

    "you asked about the tinker" -> "someone was asking about the tinker".
    Deliberately crude and deliberately narrow: it rewrites a leading "you
    <verb>ed" and leaves everything else alone, because a cleverer rewriter
    would be a sentence generator and this is a prefix.
    """
    if not text.startswith("you "):
        return text
    rest = text[4:]
    verb, _, tail = rest.partition(" ")
    if verb.endswith("ed") and len(verb) > 3:
        stem = verb[:-2]
        if stem.endswith(("k", "p", "t", "l", "s", "n", "r", "m", "g", "w", "h")):
            return f"someone was {stem}ing {tail}".rstrip()
    return f"someone {rest}"


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

    # What the speaker can pass on: what they SAW, and what they were TOLD.
    #
    # The second half is the chain. `recall` returns facts filed against the
    # speaker, and a fact somebody merely heard is a NOTE -- so a listener
    # could never become a teller, and gossip was a star around the player
    # rather than anything that travels. Each carries how far it has already
    # come, which is what `retell` words the telling from and what `MAX_HOPS`
    # eventually stops.
    tellable: list[tuple[str, str, int, str]] = [
        (_key(f.text), f.text, 1, "")
        for f in ledger.recall(speaker, limit=4)
        if f.text
    ]
    speaker_record = ledger.subject(speaker, kind="npc")
    for note in speaker_record.notes:
        body = _body_of(note)
        if body:
            tellable.append((_key(body), body, hops_of(note) + 1, _source_of(note)))
    if not tellable:
        return []
    fact_key, fact_text, hops, source = tellable[draw.randrange(len(tellable))]

    record = ledger.subject(listener, kind="npc")
    # Keyed on the TEXT, not on a fact id, because half of what can be told is
    # now a note and a note has no id.
    #
    # AND ON THE HOP, which is what lets a rumour finish travelling. Keyed on
    # the fact alone, a listener who had heard something could never hear it
    # again -- and in a five-NPC village that is everybody within about four
    # tellings, so the third-hand version had nowhere left to go. Measured
    # across 40 runs of 80 tellings: a second hop in 37, a third in 12, and
    # raising SPREAD_CHANCE from 0.35 to 0.8 did not move that at all. It made
    # the same small number of tellings happen sooner. The cast was the cap,
    # not the dice.
    #
    # So you may hear a story again if the version reaching you is FURTHER
    # from its source than the one you hold. That is not a repeat: "someone
    # was asking about the tinker" arriving after you were told who and when
    # is new information about how far the thing has travelled, and it is the
    # shape a rumour actually has. Bounded three ways -- strictly more
    # degraded each time, MAX_HOPS overall, and MAX_HEARD_PER_SUBJECT on the
    # record -- so it cannot become the same sentence arriving forever.
    heard_at = _heard_hops(record, fact_key)
    if heard_at and hops <= min(heard_at):
        return []
    # Nobody is told their own news. Once a fact can travel more than one hop
    # it can come back round to the person it started with -- measured, and it
    # read as "heard from Maris, who had it from Odran" sitting in ODRAN's own
    # memory, which invites a narrator to write him learning something he was
    # there for.
    if any(_key(f.text) == fact_key for f in ledger.recall(listener, limit=8) if f.text):
        return []

    names = getattr(ledger, "names", {}) or {}
    speaker_name = names.get(speaker) or _unnamed_speaker(speaker)

    line = retell(fact_text, speaker_name, hops=hops, source=source)
    record.known_facts.append(f"{fact_key}#h{hops}")
    if not line:
        # Past the cap. Marked known anyway, so it stops being offered to this
        # listener: the rumour dies rather than circulating forever.
        return []

    heard = sum(1 for note in record.notes if note.startswith(_HEARD_PREFIX))
    if heard < MAX_HEARD_PER_SUBJECT:
        ledger.note(listener, line, kind="npc")

    # Journalled AT THE ROOM it happened in, so it only reaches the prose when
    # the player is standing there -- which is the scene worth having: you walk
    # in on somebody telling somebody else about you. Anywhere else it stays
    # off-screen, the way gossip should.
    from engine.game import moved
    from engine.world.npc_sim import display_name

    moved.note(
        state,
        "gossip",
        f"{speaker_name} is telling {display_name(listener, state)} about you: {fact_text}",
        location_id=place_id,
    )

    logger.debug(
        "[gossip] Fact travelled (operation=spread, from=%s, to=%s, at=%s)",
        speaker,
        listener,
        place_id,
    )
    return [f"{speaker_name} told {listener} about: {fact_text}"]
