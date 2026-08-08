"""
Progress Clocks — a countdown that ends in a scene
==================================================

A clock is a small counter (0-5 is the shape the Wicked Garden day scripts
use) that fills as pressure accumulates and, at its maximum, **forces a
setpiece**. That last clause is the whole point and it is what separates a
clock from a meter. A meter is a quantity the fiction reads; a clock is a
promise the engine keeps. ``briar_hunger`` at 4 is not "the roots are hungrier
than yesterday", it is "one more and the roots interrupt whatever you were
doing".

WHAT THIS IS BUILT ON, AND WHY IT IS NOT A SECOND SYSTEM.
``engine/world/world_effects.py`` already implements threshold -> declarative
world mutation, and implements it well: a beat sets flags, opens discoveries,
seeds rumours, writes permanent world-ledger marks and relocates NPCs, with a
per-beat idempotency flag so firing twice applies once. Exactly one term in it
is Clockwork-specific -- the trigger, ``state.evil_progress >= at_progress``.
Everything after the trigger is generic.

So the generic half moved HERE (``apply_mutations``) and both systems call it.
``world_effects`` is now the doom clock's specialisation: same appliers, same
idempotency, its own trigger and its own ``source`` tag on the world ledger.
The alternative -- copying five appliers into this file -- would have meant two
places to fix the next ``expire_events`` interop surprise, and the last one of
those cost a silent, world-emptying bug (see that module's interop note 1).

WHAT A CLOCK ADDS ON TOP OF A DOOM BEAT:

  * **The trigger is a declared value.** Clocks are declared in the story's
    ``state.yaml`` as ``kind: clock`` with bounds; this module reads them
    through ``StateStore``, so a clock is clamped, journalled and visibility-
    controlled like everything else. Nothing here knows what a clock is called.
  * **``when:``** an optional extra predicate from the shared condition grammar
    (``engine/game/quests.py``), so a beat can be gated on more than a number.
  * **``effects:``** ordinary engine effects, applied through the one validated
    writer. A doom beat never needed these; a clock beat that costs the player
    ten mortal days does.
  * **``forces_scene:``** the setpiece. Recorded as a durable world-ledger entry
    rather than a new ``GameState`` field, so it survives a save with no schema
    migration and can be answered by ``forced_scenes()``.
  * **``advance_when:``** engine-side pressure. A clock that only ever moves
    because an agent asked it to is a clock the agent can decline to wind.

Version: v0.1.0 [2026-08-08]
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

import yaml

from engine.game import effects as effects_module
from engine.game.state import GameState

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parents[2]

#: Flag prefix marking a clock beat as already fired. Mirrors
#: ``world_effects.BEAT_FLAG_PREFIX``; distinct so a clock beat and a doom beat
#: with the same id cannot cancel each other.
BEAT_FLAG_PREFIX = "clock_beat_"

#: Flag prefix for discoveries, matching the convention content gates read.
DISCOVERY_FLAG_PREFIX = "discovery_"

#: Flag prefix marking a forced setpiece as already played, so it drops out of
#: ``forced_scenes`` without the world-ledger entry having to be deleted --
#: the entry is the record that it happened.
SCENE_PLAYED_FLAG_PREFIX = "scene_played_"

#: Expiry horizon for a permanent world mark. ``WorldSim.expire_events``
#: DELETES any world event with no ``expires_day`` on the next day tick, so a
#: permanent entry is written with a far horizon rather than with no expiry.
#: This is the interop fact that cost world_effects a silent bug; it is
#: restated here because this module writes to the same list.
PERMANENT_HORIZON_DAY = 999_999

#: ``source`` tag on world events written by a clock beat, so a narration
#: interceptor can tell a clock mark from a doom mark from a caravan.
SOURCE_CLOCK = "clock"

#: ``at: max`` -- fire when the clock reaches its declared maximum. Spelled
#: rather than repeated as a number so a story can retune a clock's range in
#: ``state.yaml`` without every beat that referenced its top going stale.
AT_MAX = "max"


# ---------------------------------------------------------------------------
# The generic half: threshold -> declarative mutation
# ---------------------------------------------------------------------------


def beat_flag(beat_id: str, *, prefix: str = BEAT_FLAG_PREFIX) -> str:
    """Flag name marking ``beat_id`` as fired."""
    return f"{prefix}{beat_id}"


def has_fired(state: GameState, beat_id: str, *, prefix: str = BEAT_FLAG_PREFIX) -> bool:
    """True if this beat already landed on this save."""
    return bool(state.flags.get(beat_flag(beat_id, prefix=prefix)))


def _apply_flags(state: GameState, spec: dict[str, Any]) -> list[dict[str, str]]:
    """Set world flags through the effect dispatcher, per the one-writer rule."""
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
    *,
    source: str,
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
                "source": source,
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
    Relocate NPCs as the pressure advances.

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
                "[clocks] npc_move destination is not in the location graph, "
                "skipping (operation=_apply_npc_moves, beat=%s, npc=%s, "
                "destination=%s)",
                beat_id,
                npc_id,
                destination,
            )
            continue

        npc = state.procgen.npc_by_id(npc_id)
        if npc is None:
            logger.warning(
                "[clocks] npc_move names an NPC this save does not have, "
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


def _apply_effects(
    state: GameState,
    spec: dict[str, Any],
    *,
    ledger: Optional[Any],
) -> list[dict[str, str]]:
    """Ordinary engine effects, through the one validated writer."""
    rows = spec.get("effects") or []
    if not isinstance(rows, list):
        return []
    applied: list[dict[str, str]] = []
    for receipt in effects_module.apply_effects(state, rows, ledger=ledger):
        if receipt.get("ok"):
            applied.append({"type": "effect", "value": str(receipt.get("text", ""))})
    return applied


def _apply_forced_scene(
    state: GameState,
    beat_id: str,
    spec: dict[str, Any],
    *,
    source: str,
) -> list[dict[str, str]]:
    """
    Record that this beat owes the player a scene.

    Written as a world-ledger entry rather than a new ``GameState`` field for
    the reason given in ``engine/game/state.py``: the shape is story-declared
    and must not force a save migration per field. It also means the fact that
    a setpiece was OWED survives even after it has been played, which is the
    difference between a queue and a history.
    """
    scene_id = str(spec.get("forces_scene") or "").strip()
    if not scene_id:
        return []
    event_id = f"forced_scene:{scene_id}"
    if any(str(e.get("event_id")) == event_id for e in state.world_events):
        return []
    state.world_events.append(
        {
            "event_id": event_id,
            "beat": beat_id,
            "source": source,
            "forces_scene": scene_id,
            "text": str(spec.get("text") or f"The story owes you: {scene_id}"),
            "day": state.world_day,
            "expires_day": PERMANENT_HORIZON_DAY,
        }
    )
    return [{"type": "forced_scene", "value": scene_id}]


def apply_mutations(
    state: GameState,
    beat_id: str,
    spec: dict[str, Any],
    *,
    source: str = SOURCE_CLOCK,
    ledger: Optional[Any] = None,
    flag_prefix: str = BEAT_FLAG_PREFIX,
) -> list[dict[str, str]]:
    """
    Apply one beat's declarative mutations, once.

    THE SHARED ENGINE. ``engine/world/world_effects.py`` calls this with its own
    ``source`` and flag prefix; so does every progress clock. Idempotency is
    owned here rather than by the caller: a caller that fires the same beat
    twice gets one application.

    Args:
        state: Mutable game state.
        beat_id: Unique id, used for the idempotency flag and stamped on every
            world-ledger entry the beat writes.
        spec: The beat's declaration. Every key is optional.
        source: ``source`` tag on world events, so narration can tell a clock
            mark from a doom mark.
        ledger: Optional StoryLedger, for ``effects`` that write facts.
        flag_prefix: Namespace for the idempotency flag.

    Returns:
        One record per mutation actually applied. Empty when the beat has
        already fired or the spec is unusable.
    """
    if not isinstance(spec, dict):
        logger.warning(
            "[clocks] Beat is not a mapping, ignoring (operation=apply_mutations, "
            "beat=%s)",
            beat_id,
        )
        return []
    if has_fired(state, beat_id, prefix=flag_prefix):
        return []

    applied: list[dict[str, str]] = []
    applied += _apply_flags(state, spec)
    applied += _apply_discoveries(state, spec)
    applied += _apply_rumors(state, spec)
    applied += _apply_world_events(state, beat_id, spec, source=source)
    applied += _apply_npc_moves(state, beat_id, spec)
    applied += _apply_effects(state, spec, ledger=ledger)
    applied += _apply_forced_scene(state, beat_id, spec, source=source)

    # Set last: a beat is only "fired" once its effects are in. Setting it
    # first would make a mid-application failure permanent and silent.
    state.flags[beat_flag(beat_id, prefix=flag_prefix)] = True

    logger.info(
        "[clocks] Beat applied (operation=apply_mutations, beat=%s, source=%s, "
        "mutations=%d)",
        beat_id,
        source,
        len(applied),
    )
    return applied


# ---------------------------------------------------------------------------
# Forced setpieces
# ---------------------------------------------------------------------------


def forced_scenes(state: GameState) -> list[str]:
    """
    Setpieces a filled clock owes the player, oldest first, unplayed only.

    A clock at its maximum that nothing acts on is a clock that was only
    counted -- the exact failure ``world_effects`` was written to fix for the
    doom track. This is the query a scene director answers.
    """
    pending: list[str] = []
    for event in state.world_events:
        scene_id = str(event.get("forces_scene") or "")
        if not scene_id:
            continue
        if state.flags.get(f"{SCENE_PLAYED_FLAG_PREFIX}{scene_id}"):
            continue
        if scene_id not in pending:
            pending.append(scene_id)
    return pending


def mark_scene_played(state: GameState, scene_id: str) -> dict[str, Any]:
    """
    Retire a forced setpiece. Through the dispatcher, like every other write.

    Returns:
        The dispatcher's receipt, so a caller can put it in front of the player.
    """
    return effects_module.apply_effect(
        state,
        {
            "type": "flag",
            "flag": f"{SCENE_PLAYED_FLAG_PREFIX}{str(scene_id).strip()}",
            "value": True,
        },
    )


# ---------------------------------------------------------------------------
# The clock table
# ---------------------------------------------------------------------------


def _table_path() -> Optional[Path]:
    """The clock table, or None when the story declares none."""
    from engine.config import get_config

    rel = str(get_config().get("paths.clocks", "") or "").strip()
    return (_ROOT / rel) if rel else None


@lru_cache(maxsize=8)
def _read_table(path_str: str, _mtime: float) -> dict[str, Any]:
    """
    Parse the clock table, memoized on (path, mtime).

    Keyed on mtime as well as path so the cache invalidates on a file edit or a
    repointed ``paths.clocks`` without this module having to be registered in
    engine/games/caches.py, which it does not own -- the pattern
    engine/game/survival.py established for the same reason.
    """
    try:
        with Path(path_str).open(encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
    except (OSError, yaml.YAMLError) as exc:
        logger.error("[clocks] Unreadable clock table: %s", exc)
        return {}
    return data if isinstance(data, dict) else {}


def load_clocks() -> dict[str, Any]:
    """
    Read the story's clock declarations.

    A missing file yields an empty table rather than raising: a story with no
    progress clocks is a story that runs exactly as it did before this module
    existed, which is both shipped games today.
    """
    path = _table_path()
    if path is None:
        return {}
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return {}
    return _read_table(str(path), mtime).get("clocks") or {}


def clock_names() -> list[str]:
    """Every clock the running story declares a beat table for."""
    return sorted(load_clocks())


def _store(state: GameState) -> Optional[Any]:
    """StateStore over the active schema, or None when no story is active."""
    try:
        from engine.state.active import store_for

        return store_for(state)
    except Exception as exc:  # noqa: BLE001 -- introspection must not block a turn
        logger.debug("[clocks] No state store available: %s", exc)
        return None


def value_of(state: GameState, clock: str) -> float:
    """Current reading, or 0.0 when the story does not declare this clock."""
    store = _store(state)
    if store is None or not store.has(clock):
        return 0.0
    return store.get(clock)


def maximum_of(state: GameState, clock: str) -> Optional[float]:
    """The clock's declared ceiling, or None when it is unbounded."""
    store = _store(state)
    if store is None:
        return None
    spec = store.schema.get(clock)
    return None if spec is None else spec.maximum


def is_full(state: GameState, clock: str) -> bool:
    """True when the clock has reached its declared maximum."""
    ceiling = maximum_of(state, clock)
    return ceiling is not None and value_of(state, clock) >= ceiling


def _threshold(state: GameState, clock: str, raw: Any) -> Optional[float]:
    """Resolve a beat's ``at:``, including the ``max`` keyword."""
    if isinstance(raw, str) and raw.strip().lower() == AT_MAX:
        return maximum_of(state, clock)
    try:
        return float(raw)
    except (TypeError, ValueError):
        logger.warning(
            "[clocks] Beat has a non-numeric 'at', skipping "
            "(operation=_threshold, clock=%s, at=%r)",
            clock,
            raw,
        )
        return None


def _condition_holds(state: GameState, condition: Any, ledger: Optional[Any]) -> bool:
    """Evaluate an optional ``when:`` against the shared condition grammar."""
    if condition is None:
        return True
    from engine.game.quests import evaluate_condition

    return evaluate_condition(state, condition, ledger=ledger)


# ---------------------------------------------------------------------------
# Advancing and resolving
# ---------------------------------------------------------------------------


def advance(
    state: GameState,
    clock: str,
    delta: float = 1.0,
    *,
    why: str = "",
    by: str = "engine",
    turn: int = 0,
) -> dict[str, Any]:
    """
    Move a clock, through the one validated writer.

    Args:
        state: Mutable game state.
        clock: Declared clock name.
        delta: Segments to add. Negative eases the pressure; a clock that can
            only ever rise is a countdown, not a clock, and the Garden's
            ``sophia_break`` is explicitly meant to fall when she is soothed.
        why: Recorded in the store's write journal.
        by: Writer id, checked against the value's declared ``owners``.
        turn: Turn number, for the journal.

    Returns:
        The dispatcher's receipt, with ``full`` added so a caller does not have
        to re-read the clock to find out whether it just filled.
    """
    receipt = effects_module.apply_effect(
        state,
        {"type": "value", "name": clock, "delta": delta, "why": why},
        by=by,
        turn=turn,
    )
    receipt["full"] = is_full(state, clock)
    return receipt


def _auto_advance(state: GameState, clock: str, spec: dict[str, Any], ledger: Optional[Any]) -> list[dict[str, str]]:
    """
    Engine-side pressure: rules that wind a clock without anyone asking.

    A clock that only moves when an agent calls ``advance`` is a clock the
    agent can decline to wind, and the doom track already taught this repo what
    a pressure system that nothing drives looks like.
    """
    applied: list[dict[str, str]] = []
    rules = spec.get("advance_when") or []
    if not isinstance(rules, list):
        return applied

    for index, raw in enumerate(rules):
        if not isinstance(raw, dict):
            continue
        rule_id = str(raw.get("id") or f"{clock}_advance_{index}")
        once = bool(raw.get("once", True))
        if once and has_fired(state, rule_id):
            continue
        if not _condition_holds(state, raw.get("when"), ledger):
            continue
        try:
            step = float(raw.get("by", 1))
        except (TypeError, ValueError):
            step = 1.0
        advance(state, clock, step, why=f"advance_when:{rule_id}")
        if once:
            state.flags[beat_flag(rule_id)] = True
        applied.append({"type": "clock_advance", "value": f"{clock}{step:+g}"})
    return applied


def pending_beats(state: GameState, ledger: Optional[Any] = None) -> list[tuple[str, str]]:
    """
    Beats whose threshold a clock has reached but which have not fired.

    Returned in threshold order per clock, so applying them in sequence tells
    the story in the order it happened even when several are crossed at once --
    which is normal after a load, a big time skip, or a clock slammed several
    segments by one scene.

    Returns:
        ``(clock, beat_id)`` pairs.
    """
    out: list[tuple[str, str]] = []
    for clock, spec in load_clocks().items():
        if not isinstance(spec, dict):
            continue
        current = value_of(state, str(clock))
        crossed: list[tuple[float, str]] = []
        for raw in spec.get("beats") or []:
            if not isinstance(raw, dict):
                continue
            beat_id = str(raw.get("id") or "").strip()
            if not beat_id or has_fired(state, beat_id):
                continue
            at = _threshold(state, str(clock), raw.get("at"))
            if at is None or current < at:
                continue
            if not _condition_holds(state, raw.get("when"), ledger):
                continue
            crossed.append((at, beat_id))
        out.extend((str(clock), beat_id) for _, beat_id in sorted(crossed))
    return out


def _beat_spec(clock: str, beat_id: str) -> Optional[dict[str, Any]]:
    spec = load_clocks().get(clock)
    if not isinstance(spec, dict):
        return None
    for raw in spec.get("beats") or []:
        if isinstance(raw, dict) and str(raw.get("id") or "") == beat_id:
            return raw
    return None


def fire_beat(
    state: GameState,
    clock: str,
    beat_id: str,
    *,
    ledger: Optional[Any] = None,
) -> list[dict[str, str]]:
    """
    Apply one clock beat, including any declared reset.

    ``reset_to:`` is what makes a clock recurring rather than a one-way ratchet:
    the Garden's ``ashen_pressure`` fills, spends itself on a setpiece and
    starts filling again. Applied AFTER the mutations, so a beat can read its
    own clock while resolving.
    """
    spec = _beat_spec(clock, beat_id)
    if spec is None:
        logger.warning(
            "[clocks] Unknown beat, ignoring (operation=fire_beat, clock=%s, beat=%s)",
            clock,
            beat_id,
        )
        return []

    applied = apply_mutations(state, beat_id, spec, source=SOURCE_CLOCK, ledger=ledger)
    if not applied and has_fired(state, beat_id):
        return applied

    if "reset_to" in spec:
        try:
            target = float(spec.get("reset_to"))
        except (TypeError, ValueError):
            target = 0.0
        effects_module.apply_effect(
            state,
            {"type": "value", "name": clock, "set": target, "why": f"reset by {beat_id}"},
        )
        applied.append({"type": "clock_reset", "value": f"{clock}={target:g}"})
    return applied


def resolve(state: GameState, *, ledger: Optional[Any] = None) -> list[dict[str, str]]:
    """
    Wind every clock its rules say to wind, then fire everything now crossed.

    Safe to call every turn; it is a cheap dict scan when nothing is pending.
    Auto-advance runs first so a rule that fills a clock this turn fires that
    clock's beat on the same turn rather than one turn late -- a setpiece that
    arrives a turn after the thing that caused it reads as unrelated.

    Returns:
        Flat list of mutation records across every clock.
    """
    applied: list[dict[str, str]] = []
    for clock, spec in load_clocks().items():
        if isinstance(spec, dict):
            applied += _auto_advance(state, str(clock), spec, ledger)

    for clock, beat_id in pending_beats(state, ledger):
        applied += fire_beat(state, clock, beat_id, ledger=ledger)
    return applied


def status(state: GameState) -> dict[str, dict[str, Any]]:
    """
    Every declared clock's reading, ceiling and fullness. For prompts and UI.

    Reads through the store, so a clock declared ``visibility: hidden`` is
    still reported here -- this is a server-side view. The client projection is
    ``StateStore.to_client``, which honours visibility.
    """
    out: dict[str, dict[str, Any]] = {}
    for clock in load_clocks():
        name = str(clock)
        ceiling = maximum_of(state, name)
        out[name] = {
            "value": value_of(state, name),
            "max": ceiling,
            "full": is_full(state, name),
        }
    return out


# ---------------------------------------------------------------------------
# Predicates
# ---------------------------------------------------------------------------


def _p_clock(state: GameState, value: Any, ctx: Any) -> bool:
    """
    ``{clock: {name: briar_hunger, min: 3}}`` -- compare a clock's reading.

    ``full: true`` is accepted as sugar for "at its declared maximum", because
    that is the question content actually asks and spelling it as
    ``min: <the number I hope is still the max>`` goes stale silently.
    """
    if not isinstance(value, dict):
        return False
    name = str(value.get("name") or value.get("clock") or "")
    if not name:
        return False
    if "full" in value:
        return is_full(state, name) is bool(value["full"])
    current = value_of(state, name)
    if "min" in value and current < float(value["min"]):
        return False
    if "max" in value and current > float(value["max"]):
        return False
    return True


def _p_value(state: GameState, value: Any, ctx: Any) -> bool:
    """
    ``{value: {name: favor, min: 70}}`` -- compare ANY declared story value.

    The predicate that makes the grammar story-agnostic. Without it, a gate in
    a story built on favor and autonomy would have to be written against
    ``min_stat``, which reads ``GameState.stats`` and knows nothing about them.
    An undeclared name is False, never True: a gate the engine cannot evaluate
    stays shut.
    """
    if not isinstance(value, dict):
        return False
    name = str(value.get("name") or value.get("value") or "")
    store = _store(state)
    if not name or store is None or not store.has(name):
        return False
    current = store.get(name)
    if "min" in value and current < float(value["min"]):
        return False
    if "max" in value and current > float(value["max"]):
        return False
    if "equals" in value and current != float(value["equals"]):
        return False
    return True


def _p_track(state: GameState, value: Any, ctx: Any) -> bool:
    """
    ``{track: {name: act2_compass, is: love_and_door}}`` -- an enum-valued value.

    ``is`` accepts a list, which reads as "any of these".
    """
    if not isinstance(value, dict):
        return False
    name = str(value.get("name") or value.get("track") or "")
    if not name:
        return False
    current = state.tracks.get(name)
    if "is" in value:
        wanted = value["is"]
        options = wanted if isinstance(wanted, list) else [wanted]
        return current in options
    if "set" in value:
        return (current is not None) is bool(value["set"])
    return current is not None


def _p_forced_scene(state: GameState, value: Any, ctx: Any) -> bool:
    """``{forced_scene: briar_threshold}`` -- a clock owes this setpiece."""
    pending = forced_scenes(state)
    wanted = value if isinstance(value, list) else [value]
    return all(str(v) in pending for v in wanted)


def _register() -> None:
    """
    Extend the shared condition grammar.

    Called at import time so a condition file loaded by any consumer sees these
    the moment this module is imported, and never sees a half-registered table.
    """
    from engine.game.quests import register_predicate

    register_predicate("clock", _p_clock)
    register_predicate("value", _p_value)
    register_predicate("track", _p_track)
    register_predicate("forced_scene", _p_forced_scene)


_register()


__all__ = [
    "AT_MAX",
    "BEAT_FLAG_PREFIX",
    "DISCOVERY_FLAG_PREFIX",
    "PERMANENT_HORIZON_DAY",
    "SCENE_PLAYED_FLAG_PREFIX",
    "SOURCE_CLOCK",
    "advance",
    "apply_mutations",
    "beat_flag",
    "clock_names",
    "fire_beat",
    "forced_scenes",
    "has_fired",
    "is_full",
    "load_clocks",
    "mark_scene_played",
    "maximum_of",
    "pending_beats",
    "resolve",
    "status",
    "value_of",
]
