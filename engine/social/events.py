"""
The exact-time event queue (v0.22.0 spec §9.1). Walked inside
`clock.advance_time`; inert for every story without `paths.social`, which
never imports this module.

`state.social["queue"]` is a list kept sorted by `(at, seq)`: `at` an
absolute in-game hour (a float, minute resolution), `seq` from
`state.social["seq"]`, so equal times replay in one order. Every change goes
through `apply_effect` (rule 3): `social_queue` pushes one event,
`social_event` takes the queue's head off and applies it through the
handler its module registered with `@handles(kind)`.

**An event handler writes `state.social` directly; it IS the effect**: it
runs inside `social_event`'s handler, so its writes (a `pending_read` flag, a
person's draw counters, a reconnecting person's `ghosted`) are that effect's
under rule 3, and anything another module owns still goes through its own
`social_*` effect.

**A handler never moves the clock.** The pass runs inside
`clock.advance_time`, under a thread-local guard: a handler that calls
`advance_time` (directly or through a skill) gets
`clock.SocialPassClockError`. An event's consequences are queued at their
own `at`, never waited for. The clock's death check re-enters
`advance_time` only after the pass has ended.

`daily` is this module's own kind: at 04:00 each in-game day it runs every
`daily_hooks` entry in order (each module appends its daily step) and
re-queues itself at the next 04:00. `social_profile` queues the first.

The queue is a plain list (`pop(0)` and `insert` are O(n)); fine at the
bound of `social.max_events_per_advance`. Should a long away advance show it
(spec §15.2), a heap on `(at, seq, event)` replaces it with the replay test
as the guard.
"""

from __future__ import annotations

import bisect
import logging
import math
from typing import Any, Callable, Optional

from engine import social
from engine.game.effects import EffectContext, apply_effect, effect_kind
from engine.social.kinds import recorded
from engine.game.state import GameState

logger = logging.getLogger(__name__)

#: Every kind the release queues (spec §9.1). Each is handled by the module
#: that owns it, registered as that module's task lands.
KINDS: frozenset[str] = frozenset({
    "see_like", "read", "reply", "initiate", "double_text", "expire",
    "likes_you", "game_move", "meet_start", "arc_beat", "daily",
})

#: The in-game hour the day's `daily` event runs (spec §9.1: likes reset,
#: drift, budgets refill, mood decay), before anyone's morning.
DAILY_HOUR = 4.0

#: kind -> handler(state, event) -> dict. Filled by each module that owns a kind.
_HANDLERS: dict[str, Callable[[GameState, dict[str, Any]], dict[str, Any]]] = {}

#: The `daily` event's steps, in order: each module appends its own at import.
daily_hooks: list[Callable[[GameState], None]] = []


def handles(kind: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Register `fn(state, event) -> dict` as the handler of queued `kind` events."""
    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        _HANDLERS[kind] = fn
        return fn
    return decorator


def _max_events() -> int:
    return int(social.setting("max_events_per_advance", 2000))


def next_daily(after_hours: float) -> float:
    """The first `DAILY_HOUR` strictly after `after_hours`."""
    at = math.floor(after_hours / 24.0) * 24.0 + DAILY_HOUR
    return at if at > after_hours else at + 24.0


def push(state: GameState, at: float, pid: str, kind: str, **data: Any) -> dict[str, Any]:
    """Queue one event (through `social_queue`); the receipt carries it under `event`."""
    return apply_effect(state, {"type": "social_queue", "at": float(at), "pid": pid, "kind": kind, "data": data})


@effect_kind("social_queue")
@recorded
def _e_queue(state: GameState, effect: dict[str, Any], ctx: EffectContext) -> dict[str, Any]:
    """Engine-only: insert one event at its `(at, seq)` place."""
    slice_ = state.social
    if not slice_:
        return {"type": "social_queue", "ok": False, "text": "no social slice to queue into"}
    slice_["seq"] = int(slice_.get("seq", 0)) + 1
    event = {"at": float(effect["at"]), "seq": slice_["seq"], "pid": str(effect.get("pid", "")),
             "kind": str(effect["kind"]), **dict(effect.get("data") or {})}
    queue = slice_.setdefault("queue", [])
    keys = [(e["at"], e["seq"]) for e in queue]
    queue.insert(bisect.bisect_right(keys, (event["at"], event["seq"])), event)
    return {"type": "social_queue", "ok": True, "text": f"queued {event['kind']}", "event": event}


@effect_kind("social_event")
@recorded
def _e_event(state: GameState, effect: dict[str, Any], ctx: EffectContext) -> dict[str, Any]:
    """Engine-only: take `event` off the queue and apply it through its kind's handler."""
    event = effect["event"]
    queue = state.social.get("queue") or []
    for i, queued in enumerate(queue):
        if queued["seq"] == event["seq"]:
            del queue[i]
            break
    handler = _HANDLERS.get(event["kind"])
    if handler is None:
        known = "a release kind whose module is not loaded" if event["kind"] in KINDS else "an unknown kind"
        logger.error("[social] No handler for a queued event; dropped (operation=advance, kind=%s, pid=%s): %s",
                     event["kind"], event.get("pid", ""), known)
        return {"type": "social_event", "ok": False, "text": f"no handler for {event['kind']}", "event": event}
    out = handler(state, event) or {}
    return {"type": "social_event", "ok": bool(out.get("ok", True)), "text": event["kind"],
            "event": event, "result": out}


def advance(state: GameState, from_hours: float, to_hours: float) -> list[dict[str, Any]]:
    """
    Apply every event with `at <= to_hours`, in `(at, seq)` order, bounded; the receipts, in order.

    Each event is isolated (final review M2): a handler that raises costs that
    event alone -- logged at ERROR with its kind and person, dropped from the
    queue if it is still there, an `ok: False` receipt -- and the pass goes on,
    as `_daily`'s failing hook never ends the chain. The clock has already
    moved when this runs, so a raise out of here would leave the advance's
    other due events waiting at past `at`s and its caller (an action, the away
    advance) unfinished. A handler that tries to move the clock
    (`clock.SocialPassClockError`, rule 2) is still raised: that is the
    engine's own bug, never one event's.
    """
    if not state.social:
        return []
    applied: list[dict[str, Any]] = []
    limit = _max_events()
    while True:
        queue = state.social.get("queue") or []
        if not queue or queue[0]["at"] > to_hours:
            break
        if len(applied) >= limit:
            logger.error("[social] Event pass stopped at social.max_events_per_advance=%d "
                         "(operation=advance, from=%.2f, to=%.2f, left=%d)", limit, from_hours, to_hours, len(queue))
            break
        event = queue[0]
        try:
            applied.append(apply_effect(state, {"type": "social_event", "event": event}))
        except Exception as exc:  # noqa: BLE001 -- one event's fault costs that event, never the pass
            from engine.game.clock import SocialPassClockError

            if isinstance(exc, SocialPassClockError):
                raise                                  # a rule-2 breach is the engine's bug: never swallowed
            logger.error("[social] Event handler failed; event dropped (operation=advance, kind=%s, pid=%s, at=%.2f): "
                         "%r", event.get("kind"), event.get("pid", ""), float(event.get("at") or 0.0), exc,
                         exc_info=True)
            live = state.social.get("queue") or []
            for i, queued in enumerate(live):
                if queued is event or queued.get("seq") == event.get("seq"):
                    del live[i]
                    break
            applied.append({"type": "social_event", "ok": False, "text": f"handler failed: {event.get('kind')}",
                            "event": event})
    return applied


def cancel(state: GameState, pid: str, kinds: Optional[set[str]] = None, *,
           where: Optional[Callable[[dict[str, Any]], bool]] = None) -> int:
    """Drop pid's queued events (a ghost, an unmatch, a moot opener), of `kinds` and matching
    `where` when given; the number dropped. With `social_event`, the queue's one remover.

    A dropped `read` also clears its thread's `pending_read` mark (messaging.schedule_reply), so
    a later send in that thread schedules a read again (after a ghost and a reconnect, say).

    Called only from inside a `social_*` handler, so the write is that effect's (rule 3).
    """
    queue = state.social.get("queue", [])
    keep = [e for e in queue if not (e["pid"] == pid and (kinds is None or e["kind"] in kinds)
                                     and (where is None or where(e)))]
    dropped = len(queue) - len(keep)
    if dropped:
        kept = {id(e) for e in keep}
        pending = ((state.social.get("people") or {}).get(pid) or {}).get("pending_read")
        if isinstance(pending, dict):
            for event in queue:
                if id(event) not in kept and event["kind"] == "read":
                    pending.pop(event.get("thread_id"), None)
    state.social["queue"] = keep
    return dropped


def daily_at(state: GameState) -> float:
    """
    The in-game hour of the `daily` being run, for a `daily_hooks` step.

    The pass runs with the clock already at the advance's END, so a hook
    must not read the clock for its day. `_daily` queues the next `daily`
    (24 hours on) before it runs any hook, so during a hook the earliest
    queued `daily` is exactly a day after this one.
    """
    ats = [float(e["at"]) for e in state.social.get("queue", []) if e["kind"] == "daily"]
    return (min(ats) - 24.0) if ats else next_daily(state.world_clock_hours) - 24.0


@handles("daily")
def _daily(state: GameState, event: dict[str, Any]) -> dict[str, Any]:
    """The next day's `daily` first, so a failing hook never ends the chain; then each module's step, in order."""
    push(state, next_daily(float(event["at"])), "", "daily")
    for hook in list(daily_hooks):
        hook(state)
    return {"ok": True, "hooks": len(daily_hooks)}
