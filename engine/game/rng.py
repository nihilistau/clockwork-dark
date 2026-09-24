"""
Deterministic RNG
=================

Named, replayable random streams.

The world sim previously built ``random.Random(seed + world_day * 9973)`` fresh
on every tick. Because the day never advanced, every tick drew the identical
first float forever: the caravan either never came or came every single tick,
fixed at world generation. Worse, all three schedule rolls consumed that one
frozen draw in order, so they were perfectly correlated.

Two properties matter here:

  1. Same seed replays identically (debugging, balance runs, bug reports).
  2. Consecutive draws differ (the actual point of a random number).

A per-state counter gives both. Naming the streams gives a third: adding an
encounter roll cannot shift the caravan schedule, because they draw from
different streams.

Version: v0.3.0 [2026-08-08]
"""

from __future__ import annotations

import hashlib
import random

from engine.game.state import GameState

# Canonical stream names. Use these rather than string literals at call sites
# so a typo becomes an ImportError instead of a silently divergent stream.
SCHEDULE_CARAVAN = "schedule.caravan"
SCHEDULE_TINKER = "schedule.tinker"
SCHEDULE_MILITIA = "schedule.militia"
ENCOUNTER = "encounter"
BOON = "boon"
COMPLICATION = "complication"
DICE = "dice"
ASSISTANT = "assistant"
PROCGEN = "procgen"
# Multi-step challenges roll on their own stream so composing one mid-scene
# cannot shift the outcome of the encounter or skill check around it.
CHALLENGE = "challenge"
# Foraging (P12) draws its own stream, so that adding a shift at the forge
# cannot silently reshuffle every mushroom in the forest for every seed ever
# recorded. It is the only livelihood verb that rolls: work and trade price
# their outcomes from the tables outright, which is why neither has a stream.
FORAGE = "forage"
# Structural streams (W4). Separate for the same reason as everything above: a
# deck-drawn scene must lay out the same chambers on a replay of a seed even
# after a later build adds a hidden check to one of its beats, and an arbitrary
# thread cut must be reproducible from a bug report.
DECK = "deck"
BEAT = "beat"
THREAD = "thread"
# Gossip moves facts between NPCs who share a room. Its own stream because it
# fires on the background tick, which runs a variable number of times depending
# on how long the player sat on the menu -- borrowing any other stream would let
# real-world idle time shift an encounter roll.
GOSSIP = "gossip"
# Premises are laid out at world generation, before any GameState exists, so
# they draw ``stable_rng(seed, PREMISES)``. Not PROCGEN: sharing that stream
# would make a story adding its first townhouse reshuffle the village every
# recorded seed has already generated.
PREMISES = "premises"
# Which row of a mark's purse a lift comes away with. Its own stream so that a
# story adding a purse row cannot shift a forage find, and so that the dice of
# the stealth check itself (DICE) replay identically whatever the purse holds.
THIEVERY = "thievery"
# Who saw a deed, and whether a reporter went to the watch. Its own stream so
# that a story adding a witness to a street cannot shift the dice of the lift
# itself (DICE) or what came out of the purse (THIEVERY) on a replayed seed.
LAW = "law"
# A burglary's stage rolls and its loot draw. Its own stream so that a story
# adding a loot row or a security feature cannot shift the Law's witness rolls
# (LAW) or an ordinary check's dice (DICE) on a replayed seed.
JOB = "job"


def _mix(seed: int, stream: str, counter: int) -> int:
    """
    Stable 64-bit mix of (seed, stream, counter).

    Python's ``hash()`` of a str is salted per process (PYTHONHASHSEED), so it
    cannot be used here -- the same save would replay differently on each run.
    """
    payload = f"{seed}|{stream}|{counter}".encode("utf-8")
    return int.from_bytes(hashlib.blake2b(payload, digest_size=8).digest(), "big")


def world_rng(state: GameState, stream: str) -> random.Random:
    """
    Return a fresh RNG for one draw on a named stream.

    Each stream carries its own counter. A single shared counter would make
    the streams interdependent -- adding an encounter roll would silently
    shift every subsequent caravan outcome, which defeats the point of naming
    them and makes balance changes unreproducible against old seeds.
    """
    count = state.rng_counters.get(stream, 0) + 1
    state.rng_counters[stream] = count
    return random.Random(_mix(state.rng_seed, stream, count))


def peek_rng(state: GameState, stream: str, *, offset: int = 0) -> random.Random:
    """Return an RNG without advancing the counter. Tests and previews only."""
    count = state.rng_counters.get(stream, 0) + offset
    return random.Random(_mix(state.rng_seed, stream, count))


def stable_rng(seed: int, stream: str) -> random.Random:
    """
    RNG that does not depend on game state at all.

    For generation that must be reproducible from a seed alone -- procgen, art
    variant selection, silhouette composition.
    """
    return random.Random(_mix(seed, stream, 0))
