"""
v0.22 -> v0.23 phone saves (spec §16). Idempotent; through ONE engine-only effect, `social_migrate`, whose
handler is the only writer (rule 3), beside the effects of the shapes it builds on (`social_person` for the
fixed attributes, `social_go` `op: place` for the flat, `social_queue` for the reads, `social_plan` for the
soon-plans). A slice it cannot read raises MigrationError: refused, logged, never half-migrated.

Called from ONE place, `engine/persistence/saves.py::SaveStore.load`, after `GameState.from_dict` (which has
already unpacked the slice, `engine/social/packing.py`), so it reads and writes the slice as play does; the
next save packs it again. It touches no file: the run's `phone_archive.jsonl` keeps every row it had, and
nothing is spilled or appended here.

This module names the v0.22 keys it drops (tests/test_social_removed.py exempts it): `meets`, the
`meet_start` queue events, `settings.auto_wait`, a person's `pending_read`, `initiated` and `asks_today`,
the retired `social.meet` stream's counter, a thread's `summary` and `summary_through`, a decision's
`meet_id`, `counters.meet`, and a v0.22 meet-up recap card (a system message of `kind: recap`) that was
never voiced: nothing voices one now (T19).
"""

from __future__ import annotations

import copy
import logging
from typing import Any

from engine.game.effects import EffectContext, apply_effect, effect_kind
from engine.game.state import GameState
from engine.persistence.migrations import MigrationError
from engine.social import apps, attrs, convo, events, growth, kinds, memory, messaging, places, plans, relationships
from engine.social.kinds import recorded

#: Stage -> the depth a v0.22 relationship starts v0.23 at (§16.2).
DEPTH_FROM_STAGE: dict[str, int] = {
    "matched": 0, "talking": 0, "numbers": 1, "meeting": 1,
    "dating": 2, "friends": 2, "fling": 2, "exclusive": 3,
}
#: Queue kinds dropped: re-derived from the threads (`read`), retired (`meet_start`).
DROP_KINDS: frozenset[str] = frozenset({"read", "meet_start"})
#: Initiation situations retired as bare situations (§13.1); the next daily re-queues by window.
RETIRED_SITUATIONS: frozenset[str] = convo.RETIRED_SITUATIONS
#: A person's v0.22 keys with no v0.23 home: dropped (§16.2's `pending_read`; the initiation and ask
#: tallies v0.23 keeps per episode instead).
DROPPED_PERSON_KEYS: tuple[str, ...] = ("pending_read", "initiated", "asks_today")
#: Per-person draw counters of streams v0.23 retired (T19: `rng.SOCIAL_MEET`).
DROPPED_STREAMS: tuple[str, ...] = ("social.meet",)
#: A thread's v0.22 keys: the summary is joined into the person's story.
DROPPED_THREAD_KEYS: tuple[str, ...] = ("summary", "summary_through")
#: A decision's v0.22 key with no v0.23 home (`Decision.meet_id`, removed by T19).
DROPPED_DECISION_KEYS: tuple[str, ...] = ("meet_id",)
#: v0.22 meet statuses carried over as a `soon` plan (§16.2).
PLANNED: tuple[str, ...] = ("agreed", "due")
#: The kind of a plan whose v0.22 meet named no venue v0.23 knows.
DEFAULT_KIND = "drinks"
#: v0.22's meet-up recap card: a system message of this kind.
RECAP_CARD = "recap"

logger = logging.getLogger(__name__)


def upgrade(state: GameState) -> bool:
    """Bring `state.social` to schema 2 in place: True when it changed anything, False at schema 2
    (idempotent). Never half-migrated (pre-flight F6): everything is decided in `_plan`, reading only;
    the writes are applied; `schema` is set LAST by `op: seal`. Any exception anywhere is a
    MigrationError, so `SaveStore.load` refuses the save and the next load starts from the file again."""
    slice_ = state.social
    if not slice_:
        return False
    schema = slice_.get("schema", 1)
    if schema == kinds.SCHEMA:
        return False
    if schema != 1:
        raise MigrationError(f"social: the save's phone state is schema {schema!r}; this build reads 1 and "
                             f"{kinds.SCHEMA}")
    try:
        plan = _plan(state)                              # every change decided first, reading only
        apply_effect(state, {"type": "social_migrate", "op": "apply", "plan": plan})
        for pid in plan["materialise"]:
            attrs.materialise(state, pid)                 # social_person, the counterless keys (I14)
        if state.location_id == "home":
            apply_effect(state, {"type": "social_go", "op": "place", "to": "apt_lounge"})   # Plan decision 16
        for pid, thread_id, when in plan["answer"]:      # `when` decided in _plan (F6)
            events.push(state, when, pid, "read", thread_id=thread_id)
        for row in plan["soon_plans"]:
            if plans.make(state, row["pid"], kind=row["kind"], when="soon", venue=row["venue"], by="player",
                          at=state.world_clock_hours, migrated=True) is None:
                # Never silent: a meet that cannot become a plan (they live here, say) is on the record.
                logger.warning("[social] migration: the agreed meet with %s (%s) could not become a plan "
                               "and is dropped", row["pid"], row["kind"])
        apply_effect(state, {"type": "social_migrate", "op": "seal"})   # schema 2, LAST
    except MigrationError:
        raise
    except Exception as exc:  # noqa: BLE001 -- every fault refuses the save (F6)
        raise MigrationError(f"social: the save's phone state cannot be upgraded: {exc}") from exc
    return True


def _gone(state: GameState, pid: str) -> bool:
    """A person who left: unmatched, blocked, ended, faded, expired or ghosted (Review Focus 3)."""
    person = (state.social.get("people") or {}).get(pid) or {}
    return bool(person.get("ghosted")) or apps.gone(state, pid) or person.get("stage") in (
        "ended", "faded", "expired", "winding_down")


def _plan_kind(venue: str) -> tuple[str, str]:
    """(kind, venue) for a v0.22 meet or meet ask: the venue's own kind; a venue v0.23 does not know is
    dropped (the engine picks one when the plan is made) and the kind is `DEFAULT_KIND`."""
    if venue and venue in places.venue_ids():
        return str(places.venue(venue).get("kind") or DEFAULT_KIND), venue
    return DEFAULT_KIND, ""


def _decision(d: Any, *, due: bool) -> Any:
    """A stored v0.22 decision as v0.23 reads it: its retired keys dropped and, for a message still due,
    `mode: quick` (§16.2's "voiced as reply, mode quick")."""
    if not isinstance(d, dict) or not d:
        return d
    out = {k: v for k, v in d.items() if k not in DROPPED_DECISION_KEYS}
    if due:
        out.setdefault("mode", "quick")
    return out


def _due_pending(s: dict[str, Any], queue: list[dict[str, Any]], pid: str) -> bool:
    """`pid` already has a reply on its way: a kept due event, or a due message not yet voiced."""
    if any(e.get("pid") == pid and e.get("kind") in messaging.DUE_KINDS for e in queue):
        return True
    return any(m.get("from") == pid and m.get("voiced") is False
               for t in (s.get("threads") or {}).values() if t.get("pid") == pid for m in t.get("messages") or ())


def _plan(state: GameState) -> dict[str, Any]:
    """Every change the upgrade makes, decided reading only (F6)."""
    s = state.social
    people = s.get("people") or {}
    threads = s.get("threads") or {}
    meets = s.get("meets") or {}
    queue = []
    for event in s.get("queue") or []:
        kind = str(event["kind"])
        if kind in DROP_KINDS:
            continue
        situation = str((event.get("decision") or {}).get("situation") or "")
        if kind == "initiate" and situation in RETIRED_SITUATIONS:
            continue
        row = copy.deepcopy(event)
        if "decision" in row:
            row["decision"] = _decision(row["decision"], due=kind in messaging.DUE_KINDS)
        queue.append(row)
    by_pid: dict[str, list[dict[str, Any]]] = {}
    for tid in sorted(threads):
        by_pid.setdefault(str(threads[tid]["pid"]), []).append(threads[tid])
    growth_rows, stories, bridges, answer, materialise = {}, {}, {}, [], []
    for pid, person in sorted(people.items()):
        if not person.get("stage"):
            continue                                       # swiped-only people: nothing to grow
        materialise.append(pid)
        depth = DEPTH_FROM_STAGE.get(str(person["stage"]), 0)
        growth_rows[pid] = {**growth.record(state, pid), "depth": depth, "openness": 0.0, "peak_depth": depth}
        own = sorted(by_pid.get(pid, []), key=lambda t: (float(t.get("opened_at") or 0.0), str(t["thread_id"])))
        stories[pid] = memory.cap_story(" ".join(str(t.get("summary") or "").strip() for t in own
                                                 if str(t.get("summary") or "").strip()))
        newest = max(own, key=lambda t: (messaging.last_at(t), str(t["thread_id"])), default=None)
        if newest is None:
            continue
        bridges[pid] = memory.bridge_of(list(newest.get("messages") or []), pid)
        last = messaging.last_shown(newest, spoken=True)
        if (last is not None and last.get("from") == "player" and not _gone(state, pid)
                and messaging.is_open(newest) and not _due_pending(s, queue, pid)):
            when = convo.next_available(state, pid, state.world_clock_hours)    # may raise: decided HERE (F6)
            answer.append((pid, str(newest["thread_id"]), when))
    soon_plans = []
    for mid in sorted(meets, key=lambda m: (str(m)[:1], int(str(m)[1:]) if str(m)[1:].isdigit() else 0)):
        row = meets[mid]
        if str(row.get("status") or "") in PLANNED and not _gone(state, str(row["pid"])):
            kind, venue = _plan_kind(str(row.get("venue") or ""))
            if any(p["pid"] == str(row["pid"]) for p in soon_plans):
                continue                                   # one open plan per person: two agreed meets collapse into one
            soon_plans.append({"pid": str(row["pid"]), "kind": kind, "venue": venue})
    scenes_done: dict[str, int] = {}
    for row in meets.values():
        if row.get("status") == "done":
            scenes_done[str(row["pid"])] = scenes_done.get(str(row["pid"]), 0) + 1
    meet_asks = {}
    for rid, r in (s.get("requests") or {}).items():
        if r.get("what") == "meet" and r.get("status") in relationships.OPEN_STATUSES:
            meet_asks[rid] = _plan_kind(str(r.get("venue") or ""))
    recap_cards = [(tid, str(m["id"])) for tid, t in sorted(threads.items()) for m in t.get("messages") or ()
                   if m.get("kind") == RECAP_CARD and m.get("from") == "system" and m.get("voiced") is not True]
    return {"growth": growth_rows, "stories": stories, "bridges": bridges, "answer": answer,
            "materialise": materialise, "queue": queue, "soon_plans": soon_plans,
            "scenes_done": scenes_done, "meet_asks": meet_asks, "recap_cards": recap_cards}


def _person(s: dict[str, Any], pid: str, row: dict[str, Any], plan: dict[str, Any]) -> None:
    """One staged person's v0.23 rows (inside the handler)."""
    person = s["people"][pid]
    person["episode"] = None
    person["scenes_done"] = int(plan["scenes_done"].get(pid, 0))
    person.setdefault("episodes_done", 0)
    person["growth"] = dict(row)
    memory.writable_part(person, "story")             # made, every part present, v0.22's top-level rows moved in
    mem = person["memory"]
    if plan["stories"].get(pid) and not mem.get("story"):
        mem["story"] = plan["stories"][pid]
    if plan["bridges"].get(pid) and not mem.get("bridge"):
        mem["bridge"] = copy.deepcopy(plan["bridges"][pid])
    memory.prune(person)


@effect_kind("social_migrate")
@recorded
def _e_migrate(state: GameState, effect: dict[str, Any], ctx: EffectContext) -> dict[str, Any]:
    """
    Engine-only: the v0.22 -> v0.23 upgrade of the phone slice (spec §16.2), decided by `_plan`.
    `op: apply` makes every write of the table but `schema`; `op: seal` sets `schema` and is the LAST
    write of an upgrade (pre-flight F6).
    """
    s = state.social
    if not s:
        return {"type": "social_migrate", "ok": False, "text": "no social slice"}
    if effect.get("op") == "seal":
        s["schema"] = kinds.SCHEMA
        return {"type": "social_migrate", "ok": True, "text": f"schema {kinds.SCHEMA}", "op": "seal"}
    if effect.get("op") != "apply":
        return {"type": "social_migrate", "ok": False, "text": f"{effect.get('op')!r} is no migrate op"}
    plan = effect["plan"]
    fresh = kinds.empty_slice()
    for key in ("promises", "plans", "scene", "household", "at_work"):
        s.setdefault(key, copy.deepcopy(fresh[key]))
    s["phone_up"] = True
    settings = s.setdefault("settings", {})
    settings.pop("auto_wait", None)
    settings.setdefault("wake_for_messages", False)
    counters = s.setdefault("counters", {})
    counters.pop("meet", None)
    for key, value in fresh["counters"].items():
        counters.setdefault(key, value)
    for person in (s.get("people") or {}).values():
        for key in DROPPED_PERSON_KEYS:
            person.pop(key, None)
        streams = person.get("rng_n")
        if isinstance(streams, dict):
            for stream in DROPPED_STREAMS:
                streams.pop(stream, None)
    for pid, row in plan["growth"].items():
        _person(s, pid, row, plan)
    cards = set(plan["recap_cards"])
    for tid, t in (s.get("threads") or {}).items():
        for key in DROPPED_THREAD_KEYS:
            t.pop(key, None)
        if any(tid == c[0] for c in cards):
            t["messages"] = [m for m in t.get("messages") or [] if (tid, str(m["id"])) not in cards]
        for m in t.get("messages") or []:
            if m.get("decision"):
                m["decision"] = _decision(m["decision"], due=m.get("voiced") is False)
    s["queue"] = sorted(plan["queue"], key=lambda e: (float(e["at"]), int(e.get("seq", 0))))
    for rid, (kind, venue) in plan["meet_asks"].items():
        request = s["requests"][rid]                   # a pending meet ask becomes a `soon` plan ask (T12)
        for key in ("day", "slot", "lapsed"):
            request.pop(key, None)
        request.update(kind=kind, venue=venue, when="soon")
    s.pop("meets", None)
    # `schema` is NOT set here: `op: seal` sets it after every other write has landed (F6).
    return {"type": "social_migrate", "ok": True, "text": "applied", "op": "apply"}
