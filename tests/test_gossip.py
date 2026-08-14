"""
Gossip — facts moving between people who share a room.

Subject memory made every character remember what passed between them and the
player, which is a hub and spokes: everyone knows what they saw and nobody
knows what anyone else saw. Gossip is the edge between the spokes.

WHAT THESE TESTS PROTECT, in order of how badly it would hurt to lose it:

1. **Determinism.** It draws on its own `world_rng` stream, and it fires on the
   background tick, which runs a variable number of times depending on how long
   the player sat on the menu. Borrowing another stream would let real-world
   idle time shift an encounter roll (CLAUDE.md rule 4).
2. **Restraint.** One transfer per tick, only between people in the same place,
   only facts the speaker knows. A pass that moved everything everywhere would
   flatten the point, which is that the state is UNEVEN.
3. **Attribution.** What lands is where it came from, not just what it was.
"""

from __future__ import annotations

import random

import pytest

from engine.games import registry
from engine.scenes.default_state import SessionStore
from engine.world.gossip import spread


@pytest.fixture
def peopled():
    """A real session, with facts on people who actually share a room."""
    registry.activate("clockwork-dark")
    session = SessionStore().create(seed=42, llm_fn=lambda messages, **kw: "{}")
    ledger = session.ledger
    ledger.remember_name("npc_odran", "Odran")
    for who in ("npc_odran", "npc_villager_1", "npc_villager_2", "npc_villager_3"):
        ledger.add_fact(f"you spoke to {who} about the wood", subject_id=who, turn=1, day=1)
    return session


def test_a_fact_travels_between_people_in_the_same_room(peopled) -> None:
    moved = spread(peopled.engine.state, peopled.ledger, rng=random.Random(7))
    assert moved, "nothing travelled in a room with four people who all know something"


def test_what_lands_says_where_it_came_from(peopled) -> None:
    """
    Attribution is the feature. A bare fact appearing in somebody's head is
    indistinguishable from the narrator inventing it; "heard from Odran" is
    what lets a scene be written about a source.
    """
    spread(peopled.engine.state, peopled.ledger, rng=random.Random(7))
    notes = [n for rec in peopled.ledger.relations.values() for n in rec.notes]
    assert any(n.startswith("heard from ") for n in notes), notes


def test_the_same_seed_moves_the_same_fact(peopled) -> None:
    """
    THE ONE THAT MATTERS. A replayed seed must produce a replayed world.
    """
    first = spread(peopled.engine.state, peopled.ledger, rng=random.Random(7))
    second = spread(peopled.engine.state, peopled.ledger, rng=random.Random(7))
    # Same draw, same pair, same fact -- the second is a no-op only because the
    # listener already knows it, which is itself the dedupe working.
    assert first
    assert second == []


def test_it_stays_quiet_most_of_the_time(peopled) -> None:
    """
    Gossip should feel like weather. A player who notices it every single day
    stops reading it as a world and starts reading it as a mechanic.
    """
    quiet = sum(
        1
        for seed in range(40)
        if not spread(peopled.engine.state, peopled.ledger, rng=random.Random(seed))
    )
    assert quiet > 20, f"only {40 - quiet}/40 ticks were silent"


def test_a_speaker_cannot_pass_on_what_they_do_not_know() -> None:
    """
    The counter-control. Without it this file would pass against a version
    that copied facts to everyone regardless of who knew them.
    """
    registry.activate("clockwork-dark")
    session = SessionStore().create(seed=42, llm_fn=lambda messages, **kw: "{}")
    # A fact about somebody who is NOT in the crowded room.
    session.ledger.add_fact("a secret", subject_id="npc_maris", turn=1, day=1)
    for seed in range(20):
        assert spread(session.engine.state, session.ledger, rng=random.Random(seed)) == []


def test_no_world_no_gossip() -> None:
    """A story with no graph, and a caller with nothing, must not raise."""
    assert spread(None, None) == []


def test_gossip_has_its_own_rng_stream() -> None:
    """
    Named streams are what stop one system's rolls shifting another's. Gossip
    fires on the background tick, whose frequency depends on real elapsed time,
    so sharing a stream would make an encounter roll depend on how long the
    player left the game open.
    """
    from engine.game import rng as rng_module

    assert rng_module.GOSSIP == "gossip"
    names = [
        value
        for key, value in vars(rng_module).items()
        if key.isupper() and isinstance(value, str)
    ]
    assert len(names) == len(set(names)), "two systems share an RNG stream name"
