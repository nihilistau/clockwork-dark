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

Idempotency is owned here, not by the caller: each beat sets
``doom_beat_<id>`` and is skipped forever after. A caller that fires the same
beat twice gets one application.

Version: v0.1.0 [2026-08-08]
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

import yaml

from engine.config import get_config
from engine.game import effects as effects_module
from engine.game.state import GameState

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parents[2]

# Cleared by engine/games/caches.py on a game swap; a second game ships its own
# beats and must not inherit Edgewood's.
_EFFECTS_CACHE: Optional[dict[str, Any]] = None

#: Flag prefix marking a beat as already fired.
BEAT_FLAG_PREFIX = "doom_beat_"

#: Flag prefix for discoveries, matching the convention content gates read.
DISCOVERY_FLAG_PREFIX = "discovery_"

#: Expiry horizon for a permanent world mark. See interop note 1 above --
#: `None` is not an option, because that is the value expire_events drops.
PERMANENT_HORIZON_DAY = 999_999


def _effects_path() -> Path:
    rel = get_config().get("paths.doom_effects", "data/rules/doom_effects.yaml")
    return _ROOT / str(rel)


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


def _apply_flags(state: GameState, spec: dict[str, Any]) -> list[dict[str, str]]:
    """Set world flags through the effect dispatcher, per the engine's one-writer rule."""
    applied: list[dict[str, str]] = []
    for flag in spec.get("set_flags", []) or []:
        name = str(flag).strip()
        if not name:
            continue
        was_set = bool(state.flags.get(name))
        # Routed through apply_effect rather than poking state.flags directly:
        # the dispatcher is the only validated writer of game state, and a
        # second path into it is how invariants stop being invariants.
        effects_module.apply_effect(state, {"type": "flag", "flag": name, "value": True})
        if not was_set:
            applied.append({"type": "flag", "value": name})
    return applied


def _apply_discoveries(state: GameState, spec: dict[str, Any]) -> list[dict[str, str]]:
    """Open discovery-gated content by setting ``discovery_<key>``."""
    applied: list[dict[str, str]] = []
    for key in spec.get("discoveries", []) or []:
        name = str(key).strip()
        if not name:
            continue
        flag = f"{DISCOVERY_FLAG_PREFIX}{name}"
        was_set = bool(state.flags.get(flag))
        effects_module.apply_effect(state, {"type": "flag", "flag": flag, "value": True})
        if not was_set:
            applied.append({"type": "discovery", "value": name})
    return applied


def _apply_rumors(state: GameState, spec: dict[str, Any]) -> list[dict[str, str]]:
    """Append village chatter, deduped against what is already circulating."""
    applied: list[dict[str, str]] = []
    for raw in spec.get("rumors", []) or []:
        text = str(raw).strip()
        if not text or text in state.rumors:
            continue
        state.rumors.append(text)
        applied.append({"type": "rumor", "value": text})
    return applied


def _apply_world_events(
    state: GameState,
    beat_id: str,
    spec: dict[str, Any],
) -> list[dict[str, str]]:
    """Write permanent marks to the world ledger."""
    applied: list[dict[str, str]] = []
    known = {str(e.get("event_id")) for e in state.world_events}
    for raw in spec.get("world_events", []) or []:
        if not isinstance(raw, dict):
            continue
        event_id = str(raw.get("event_id") or "").strip()
        if not event_id or event_id in known:
            continue
        state.world_events.append(
            {
                **raw,
                "event_id": event_id,
                "beat": beat_id,
                # Marks the entry for DoomSignsInterceptor, which narrates only
                # doom marks and not the transient caravan/militia events.
                "source": "doom",
                "day": state.world_day,
                "expires_day": PERMANENT_HORIZON_DAY,
            }
        )
        known.add(event_id)
        applied.append({"type": "world_event", "value": event_id})
    return applied


def _apply_npc_moves(
    state: GameState,
    beat_id: str,
    spec: dict[str, Any],
) -> list[dict[str, str]]:
    """
    Relocate villagers as the Dark advances.

    Destinations are checked against the live location graph. An unvalidated
    move is worse than no move: the NPC does not vanish, they occupy an id that
    ``npcs_at`` will never return, so they are silently deleted from the world
    with no error anywhere.
    """
    from engine.game.locations import LOCATION_IDS

    moves = spec.get("npc_moves", {}) or {}
    if not isinstance(moves, dict):
        return []

    applied: list[dict[str, str]] = []
    for raw_npc, raw_dest in moves.items():
        npc_id = str(raw_npc).strip()
        destination = str(raw_dest).strip()
        if not npc_id or not destination:
            continue
        if destination not in LOCATION_IDS:
            logger.error(
                "[world_effects] npc_move destination is not in the location "
                "graph, skipping (operation=_apply_npc_moves, beat=%s, npc=%s, "
                "destination=%s)",
                beat_id,
                npc_id,
                destination,
            )
            continue

        npc = state.procgen.npc_by_id(npc_id)
        if npc is None:
            logger.warning(
                "[world_effects] npc_move names an NPC this save does not have, "
                "skipping (operation=_apply_npc_moves, beat=%s, npc=%s)",
                beat_id,
                npc_id,
            )
            continue
        if npc.get("location_id") == destination:
            continue

        npc["location_id"] = destination
        # Read by narration and the UI to explain why someone is standing
        # somewhere they have no business being.
        npc["displaced"] = True
        applied.append({"type": "npc_move", "value": f"{npc_id}->{destination}"})
    return applied


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
    if has_fired(state, beat_id):
        return []

    applied: list[dict[str, str]] = []
    applied += _apply_flags(state, spec)
    applied += _apply_discoveries(state, spec)
    applied += _apply_rumors(state, spec)
    applied += _apply_world_events(state, beat_id, spec)
    applied += _apply_npc_moves(state, beat_id, spec)

    # Set last: a beat is only "fired" once its effects are in. Setting it
    # first would make a mid-application failure permanent and silent.
    state.flags[beat_flag(beat_id)] = True

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
