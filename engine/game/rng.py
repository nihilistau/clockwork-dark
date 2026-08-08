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
LOOT = "loot"
BOON = "boon"
COMPLICATION = "complication"
DICE = "dice"
ASSISTANT = "assistant"
PROCGEN = "procgen"
# Multi-step challenges roll on their own stream so composing one mid-scene
# cannot shift the outcome of the encounter or skill check around it.
CHALLENGE = "challenge"
# Livelihood streams (P12). Separate from LOOT on purpose: what a forage node
# yields, what a day's labour is worth and whether a vendor moves on a price
# are three independent questions, and folding them into one stream would mean
# that adding a shift at the forge silently reshuffled every mushroom in the
# forest for every seed ever recorded.
FORAGE = "forage"
LABOUR = "labour"
TRADE = "trade"


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
