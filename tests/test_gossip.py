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


# ---------------------------------------------------------------------------
# A rumour gets further from its source
# ---------------------------------------------------------------------------
#
# WHAT WAS MISSING. A fact travelled once and stopped. `spread` refuses when
# `fact.id in record.known_facts`, so a listener who has heard something can
# never retell it -- gossip was a star around the player, never a chain, and
# what landed was the fact VERBATIM with a name on it, no matter how far it had
# come.
#
# The decay is what makes onward telling safe to allow. Without it, letting a
# fact hop again turns the thing the module docstring insists must "feel like
# weather" into the broadcast network it says it must not be.
#
# THE CONTENT NEVER CHANGES. What decays is who vouches for it and how firmly,
# so a narrator can write somebody cagey about a source or overconfident about
# something they got third-hand -- and the engine never records a falsehood it
# might later state as fact.


def _notes(ledger) -> list[str]:
    return [n for rec in ledger.relations.values() for n in rec.notes]


def test_a_second_hand_telling_names_the_chain_not_just_the_speaker(peopled) -> None:
    """Hop 2 says who told them AND who told that person."""
    from engine.world.gossip import retell

    assert retell("you asked about the tinker", "Corwin", hops=2, source="Maris") == (
        "heard from Corwin, who had it from Maris: they say you asked about the tinker"
    )


def test_a_first_hand_telling_is_unchanged(peopled) -> None:
    """
    Hop 1 keeps today's wording exactly.

    `test_what_lands_says_where_it_came_from` asserts on that prefix, and the
    whole attribution feature is built on it.
    """
    from engine.world.gossip import retell

    assert retell("you asked about the tinker", "Maris", hops=1) == (
        "heard from Maris: you asked about the tinker"
    )


def test_a_far_travelled_rumour_loses_its_source(peopled) -> None:
    """Third-hand and beyond, nobody remembers who said it first."""
    from engine.world.gossip import retell

    far = retell("you asked about the tinker", "Corwin", hops=3, source="Maris")
    assert far == "heard it going round: someone was asking about the tinker"
    assert "Corwin" not in far and "Maris" not in far


def test_a_rumour_dies_rather_than_circulating_forever(peopled) -> None:
    """
    The cap is what keeps this weather rather than a broadcast network.

    Without it, allowing onward telling means every fact eventually reaches
    everybody, which is precisely the flattening the module was written to
    avoid: the interesting state is the UNEVEN one.
    """
    from engine.world.gossip import MAX_HOPS, retell

    assert retell("x", "Corwin", hops=MAX_HOPS + 1) == ""


def test_a_fact_can_now_travel_onward(peopled) -> None:
    """
    A listener may retell what they were told, which they could not before.

    Driven through the real `spread` over many ticks rather than asserted on a
    helper, because the refusal that blocked it lives in `spread`.
    """
    from engine.world.gossip import spread as spread_fn

    state, ledger = peopled.engine.state, peopled.ledger
    rng = random.Random(11)
    for _ in range(60):
        spread_fn(state, ledger, rng=rng)

    onward = [n for n in _notes(ledger) if "who had it from" in n or "going round" in n]
    assert onward, "no fact ever made a second hop in 60 ticks"


def test_the_chain_replays_from_a_seed(peopled) -> None:
    """Determinism survives the change -- rule 4, and the first thing this
    file says it protects."""
    from engine.world.gossip import spread as spread_fn

    def run() -> list[str]:
        registry.activate("clockwork-dark")
        session = SessionStore().create(seed=42, llm_fn=lambda messages, **kw: "{}")
        led = session.ledger
        led.remember_name("npc_odran", "Odran")
        for who in ("npc_odran", "npc_villager_1", "npc_villager_2", "npc_villager_3"):
            led.add_fact(f"you spoke to {who} about the wood", subject_id=who, turn=1, day=1)
        rng = random.Random(5)
        for _ in range(40):
            spread_fn(session.engine.state, led, rng=rng)
        return sorted(_notes(led))

    assert run() == run()


def test_nobody_is_told_their_own_news(peopled) -> None:
    """
    A rumour that travels more than one hop can circle back to its source.

    Measured once the chain was allowed: "heard from Maris, who had it from
    Odran" landed in ODRAN's own memory, which invites a narrator to write him
    learning something he was standing there for.
    """
    from engine.world.gossip import _key, spread as spread_fn

    state, ledger = peopled.engine.state, peopled.ledger
    rng = random.Random(11)
    for _ in range(80):
        spread_fn(state, ledger, rng=rng)

    for who, rec in ledger.relations.items():
        own = {_key(f.text) for f in ledger.recall(who, limit=8) if f.text}
        for note in rec.notes:
            if not note.startswith("heard "):
                continue
            body = note.split(":", 1)[1].strip() if ":" in note else ""
            body = body[len("they say ") :] if body.startswith("they say ") else body
            assert _key(body) not in own, f"{who} was told their own news: {note}"
