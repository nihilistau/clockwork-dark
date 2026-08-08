"""
World Effects — the doom clock made tangible
============================================

Declarative world mutations fired when the Dark crosses a beat.

THE PROBLEM THIS SOLVES: ``evil_progress`` was a number that went up and
changed the adjectives in the prompt. Nothing in the world moved. A player at
0.85 walked into the same square, met the same five villagers standing in the
same places, and read tenser prose about it. The doom clock was counted, never
felt.

A beat now *changes the world*, and every change lands on a ``GameState`` field
that already exists -- ``flags``, ``rumors``, ``world_events``, and the NPC
records on ``procgen`` -- so all of it serialises through ``to_save_dict`` with
no schema migration and no new persistence code:

  * **flags**       durable world state the prompt shapers and content gates read.
  * **discoveries** ``discovery_<key>`` flags, so gated content can open.
  * **rumors**      village chatter, which the square and notice board already read.
  * **world_events** a ledger of what the Dark has done, so narration stays
    consistent with the state (see ``DoomSignsInterceptor``).
  * **npc_moves**   villagers relocate, so the margins empty and the square
    fills. This is the one the player actually notices.

TWO INTEROP FACTS THAT SHAPE THE SCHEMA, both learned the hard way:

  1. ``WorldSim.expire_events`` **deletes any world event with no
     ``expires_day``**, and does it on the next day tick. A doom mark is
     permanent, so it is written with a far-future horizon rather than no
     expiry -- otherwise every beat's ledger entry would silently vanish within
     a day of being written, and ``DoomSignsInterceptor`` would narrate an
     empty world.
  2. Our world events are keyed ``event_id``, not ``id``. ``apply_events`` and
     ``expire_events`` both dedupe on it.

WHAT MOVED, AND WHY THIS FILE GOT SHORTER. Everything after the trigger was
generic: setting a flag, opening a discovery, seeding a rumour, writing a
permanent mark and relocating an NPC are not facts about a doom clock, they are
facts about a *beat*. Progress clocks needed all five and copying them would
have meant two homes for the ``expire_events`` interop above -- the exact
surprise that cost this module a silent, world-emptying bug. So the appliers,
the idempotency flag and the interop live in ``engine/game/clocks.py`` now, and
this module is the doom clock's specialisation of them: its own trigger
(``evil_progress >= at_progress``), its own ``doom`` source tag, its own
``doom_beat_<id>`` flag namespace.

Idempotency is still owned below the caller, not by it: a caller that fires the
same beat twice gets one application.

Version: v0.2.0 [2026-08-08]
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

import yaml

from engine.config import get_config
from engine.game import clocks
from engine.game.state import GameState

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parents[2]

# Cleared by engine/games/caches.py on a game swap; a second game ships its own
# beats and must not inherit Edgewood's.
_EFFECTS_CACHE: Optional[dict[str, Any]] = None

#: Flag prefix marking a beat as already fired. This module's own namespace, so
#: a doom beat and a clock beat sharing an id cannot cancel each other.
BEAT_FLAG_PREFIX = "doom_beat_"

#: ``source`` tag stamped on every world event a doom beat writes.
#: ``DoomSignsInterceptor`` narrates only these and not the transient
#: caravan/militia events, so it is load-bearing rather than decorative.
DOOM_SOURCE = "doom"

#: Re-exported from engine/game/clocks.py, which owns them now. Kept as names
#: here because content, tests and the doctor script all refer to them through
#: this module, and moving a constant is not a reason to break a caller.
DISCOVERY_FLAG_PREFIX = clocks.DISCOVERY_FLAG_PREFIX
PERMANENT_HORIZON_DAY = clocks.PERMANENT_HORIZON_DAY


def _effects_path() -> Optional[Path]:
    """The doom beat table, or None when the story declares none."""
    rel = str(get_config().get("paths.doom_effects", "") or "").strip()
    return (_ROOT / rel) if rel else None


def load_doom_effects() -> dict[str, Any]:
    """
    Read and cache the beat table.

    A missing or malformed file yields an empty table rather than raising: a
    game with no doom effects is a game where the clock is only counted, which
    is the previous behaviour and is playable.
    """
    global _EFFECTS_CACHE
    if _EFFECTS_CACHE is not None:
        return _EFFECTS_CACHE

    path = _effects_path()
    if path is None:
        logger.debug(
            "[world_effects] Story declares no doom effects "
            "(operation=load_doom_effects)"
        )
        _EFFECTS_CACHE = {}
        return _EFFECTS_CACHE

    try:
        with path.open(encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
    except FileNotFoundError:
        logger.info(
            "[world_effects] No doom effects file; beats will not fire "
            "(operation=load_doom_effects, path=%s)",
            path,
        )
        data = {}
    except (OSError, yaml.YAMLError) as exc:
        logger.error(
            "[world_effects] Unreadable doom effects file "
            "(operation=load_doom_effects, path=%s): %s",
            path,
            exc,
        )
        data = {}

    if not isinstance(data, dict):
        logger.error(
            "[world_effects] Doom effects file is not a mapping "
            "(operation=load_doom_effects, path=%s)",
            path,
        )
        data = {}

    _EFFECTS_CACHE = data
    return _EFFECTS_CACHE


def reset_doom_effects_cache() -> None:
    """Drop the cached table. Game swap and tests."""
    global _EFFECTS_CACHE
    _EFFECTS_CACHE = None


def beat_flag(beat_id: str) -> str:
    """Flag name marking ``beat_id`` as fired."""
    return f"{BEAT_FLAG_PREFIX}{beat_id}"


def has_fired(state: GameState, beat_id: str) -> bool:
    """True if this beat already landed on this save."""
    return bool(state.flags.get(beat_flag(beat_id)))


def pending_beats(state: GameState) -> list[str]:
    """
    Beats whose threshold the world has reached but which have not fired.

    Returned in threshold order, so applying them in sequence tells the story
    in the order it happened even when several are crossed at once -- which is
    normal on a load, a big time skip, or a fresh save at high progress.
    """
    table = load_doom_effects()
    crossed: list[tuple[float, str]] = []
    for beat_id, spec in table.items():
        if not isinstance(spec, dict):
            continue
        try:
            threshold = float(spec.get("at_progress", 1.0))
        except (TypeError, ValueError):
            logger.warning(
                "[world_effects] Beat has non-numeric at_progress, skipping "
                "(operation=pending_beats, beat=%s)",
                beat_id,
            )
            continue
        if state.evil_progress >= threshold and not has_fired(state, str(beat_id)):
            crossed.append((threshold, str(beat_id)))
    return [beat_id for _, beat_id in sorted(crossed)]


def apply_beat(state: GameState, beat_id: str) -> list[dict[str, str]]:
    """
    Apply one doom beat's world mutations.

    Args:
        state: Mutable game state.
        beat_id: Key in the doom effects table.

    Returns:
        One record per mutation actually applied, for logs and telemetry.
        Empty when the beat is unknown or has already fired.
    """
    spec = load_doom_effects().get(beat_id)
    if not isinstance(spec, dict):
        logger.warning(
            "[world_effects] Unknown doom beat, ignoring "
            "(operation=apply_beat, beat=%s)",
            beat_id,
        )
        return []

    # The appliers, the idempotency flag and the world-ledger interop live in
    # engine/game/clocks.py now. This module keeps the one thing that was ever
    # Clockwork-specific -- the trigger, `evil_progress >= at_progress` -- plus
    # the `doom` source tag that DoomSignsInterceptor filters on.
    applied = clocks.apply_mutations(
        state,
        beat_id,
        spec,
        source=DOOM_SOURCE,
        flag_prefix=BEAT_FLAG_PREFIX,
    )
    if applied or has_fired(state, beat_id):
        logger.info(
            "[world_effects] Doom beat applied (operation=apply_beat, beat=%s, "
            "progress=%.3f, mutations=%d)",
            beat_id,
            state.evil_progress,
            len(applied),
        )
    return applied


def apply_pending_beats(state: GameState) -> list[dict[str, str]]:
    """
    Fire every beat the world has crossed, in threshold order.

    Safe to call every turn; it is a cheap dict scan when nothing is pending.

    Returns:
        Flat list of mutation records across all beats fired.
    """
    applied: list[dict[str, str]] = []
    for beat_id in pending_beats(state):
        applied.extend(apply_beat(state, beat_id))
    return applied


def doom_signs(state: GameState, *, limit: int = 3) -> list[str]:
    """
    The most recent permanent marks, newest last.

    Used by the prompt shaper and available to any UI that wants to show what
    the Dark has done without re-deriving it from flags.
    """
    signs = [
        str(event.get("text", "")).strip()
        for event in state.world_events
        if event.get("source") == "doom" and event.get("text")
    ]
    return signs[-max(0, int(limit)) :] if limit else []


__all__ = [
    "BEAT_FLAG_PREFIX",
    "DISCOVERY_FLAG_PREFIX",
    "PERMANENT_HORIZON_DAY",
    "apply_beat",
    "apply_pending_beats",
    "beat_flag",
    "doom_signs",
    "has_fired",
    "load_doom_effects",
    "pending_beats",
    "reset_doom_effects_cache",
]
