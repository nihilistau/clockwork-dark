"""
Fixed per-person attributes (v0.23.0 spec §4.2, I14; Plan decision 7).

Each attribute is drawn ONCE per person from a counterless key,
``stable_rng(seed, f"{stream}:{pid}:{name}")`` -- never ``person_rng`` -- so
no draw order anywhere can change it. Its owning module registers a drawer
here at import; ``materialise`` writes them all at first match through
``social_person`` (rule 3); ``of`` answers a read path from the stored row,
computing any missing attribute from the same key and WRITING NOTHING.
"""

from __future__ import annotations

import random
from typing import Any, Callable

from engine.game.effects import apply_effect
from engine.game.rng import stable_rng
from engine.game.state import GameState

Drawer = Callable[[GameState, str, random.Random], Any]

#: name -> (stream, drawer). Filled at import by each owning module (registration).
FIXED: dict[str, tuple[str, Drawer]] = {}


def drawer(name: str, stream: str) -> Callable[[Drawer], Drawer]:
    """Register ``fn(state, pid, rng) -> value`` as the drawer of attribute ``name`` on ``stream``."""
    def register(fn: Drawer) -> Drawer:
        FIXED[name] = (stream, fn)
        return fn
    return register


def key(seed: int, stream: str, pid: str, name: str) -> random.Random:
    """The attribute's own generator: counterless, so it is the same whenever it is asked."""
    return stable_rng(seed, f"{stream}:{pid}:{name}")


def _compute(state: GameState, pid: str, name: str) -> Any:
    stream, fn = FIXED[name]
    return fn(state, pid, key(state.rng_seed, stream, pid, name))


def of(state: GameState, pid: str) -> dict[str, Any]:
    """Every registered attribute of ``pid``: stored where materialised, computed (never written) where not."""
    stored = ((state.social.get("people") or {}).get(pid) or {}).get("attrs") or {}
    out = dict(stored)
    for name in FIXED:
        if name not in out:
            out[name] = _compute(state, pid, name)
    return out


def materialise(state: GameState, pid: str) -> None:
    """Write every registered attribute not yet stored, once, through ``social_person`` (rule 3)."""
    stored = ((state.social.get("people") or {}).get(pid) or {}).get("attrs") or {}
    missing = {name: _compute(state, pid, name) for name in FIXED if name not in stored}
    if missing:
        apply_effect(state, {"type": "social_person", "pid": pid, "set": {"attrs": {**stored, **missing}}})
