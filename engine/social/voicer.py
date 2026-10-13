"""
The voicing pass (v0.22.0 spec §16.2-16.5, §17.1's pushes): after a fast
mechanics action, the due messages are voiced by a separate pass the player
never waits for. It calls the model holding NO lock, and commits each reply
under the turn lock, re-checked against the live state.

THE PASS (`run_pass`), bound to the session OBJECT and its `epoch`, never to
its id, so a resumed run (same id, new object) never shares, reruns or
inherits an old pass:

1. **The generation check** (`saves.alive`: this object is its store's live
   run, of this build, not ending), before admission, before the snapshot
   and before every commit. A pass that fails it ENDS: nothing committed,
   nothing saved, no re-queue, its reference to the session dropped.
2. **Admission** (hosted only), holding no lock and BEFORE anything is
   marked: `admit_turn(label="voice", account=<owner>, deadline_seconds=
   hosting.turn_deadline_seconds, cancel=pass.cancel)` with a SHORT wait,
   `social.voice.admit_wait_seconds`. Busy: the pass answers `busy`, nothing
   marked, and the scheduler re-queues it with backoff (2, 4, 8, 16, 32 s);
   after `social.voice.max_attempts` it is DROPPED (the next action or
   resume requests again). Before admission the inbox is drained under the
   tried lock: applying a parked reply or media result calls no model, so a
   pass that finds nothing else due asks no ticket (final review I1; the
   media hand-off requests a pass when it parks). The voice call then runs INSIDE that ticket
   (`gate.inference_slot` shares an admitted context's narration lane), so
   one account's phone holds at most one narration ticket at a time.
3. **The snapshot**, under the turn lock (tried, never waited for, on the
   `social.voice.commit_retry_ms` schedule): the inbox drained, then the due
   messages to voice read by §11.1's priority (thread focus, then warmth,
   then age), at most `social.voice.max_per_pass` people, one thread each,
   and MARKED in `session.voicing` (message id -> pass id) -- in memory,
   never in state, never in a save. More left: `rerun`.
4. **The call**, per person, sequentially, holding no lock
   (`voicing.voice`, pure over the snapshot); `session.typing` names the
   thread while its call is in flight. Past the pass's deadline
   (`social.voice.pass_deadline_seconds`, hosted also
   `hosting.turn_deadline_seconds`) the rest get fallback lines.
5. **The commit** of each reply as it lands (`commit`, §16.3): liveness;
   still wanted (the message due, marked by THIS pass, the person not
   unmatched, blocked or ended, the thread there); the state-dependent
   re-checks (proposals legal NOW, `agreement.STATE_CHECKS` against the live
   view, a newly failing bubble or fact dropped, none left: the fallback);
   then ONE transaction through `apply_effect` (`social_voiced`, the regard,
   the memory, each proposal), its rollback snapshot SCOPED to what a commit
   can write (`ScopedTransaction`: the person's own rows deep, every other
   row by reference), never the whole state (v0.22.0 T26). The pass's
   last commit saves under its own lock; any other marks the session dirty. Pushed as `phone_message`
   through the room-checked emitter. A commit that cannot take the lock
   parks the reply in the session's inbox (`engine/social/inbox.py`), its
   messages still marked, for the next holder to apply.
6. **The summary**: at most one thread past its verbatim window, summarised
   holding no lock (one-argument `SummaryFn`) and committed like a reply.
7. **Finish**: the admission released; this pass's marks cleared (bar those
   parked in the inbox).

A model call already sent cannot be interrupted: its answer is discarded
when it returns to a cancelled pass.

THE SCHEDULER (`VoicingScheduler`), a process singleton (`get_scheduler`,
double-checked under `_scheduler_lock`): a bounded queue of passes
(`social.voice.queue_max`, the oldest dropped with a log line), one entry
per session object (a request for one queued already does nothing; for one
in flight sets its `rerun`), `social.voice.workers` daemon threads started
lazily, and its leaf `_lock` over the queue and the in-flight table
`{(session_id, epoch): VoicePass}`. `cancel` is fired by the store's release
(`forget`), a hosted drain or a shutdown (`cancel_all`), and, hosted only,
the session's room emptying (`cancel_unwatched`).

`run_until_quiet` runs the same pass synchronously on the caller's thread,
no scheduler and no admission: the replay test, the simulator and
`screenshot_runs.py` voice through it, so their results never depend on
thread timing.
"""

from __future__ import annotations

import copy
import dataclasses
import heapq
import itertools
import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from contextlib import contextmanager
from typing import Any, Callable, Iterator, Optional

from engine import social
from engine.config import get_config, hosting_enabled
from engine.game.effects import EffectContext, apply_effect, effect_kind
from engine.game.state import GameState
from engine.llm.gate import CancelToken
from engine.locks import renew_after_fork
from engine.social import agreement, apps, archive, memory, messaging, relationships, saves, voicing
from engine.social.kinds import Decision, collecting, recorded

logger = logging.getLogger(__name__)

#: A pass's outcomes (`run_pass`).
OUTCOMES: tuple[str, ...] = ("ok", "busy", "dropped", "discarded", "fallback", "cancelled")

#: How long an idle worker waits before it looks at its queue again (a request wakes it sooner).
IDLE_WAIT_SECONDS = 1.0

#: How long `stop` waits for each worker thread to end.
STOP_JOIN_SECONDS = 5.0

#: Every pass's id, process-wide ("v1", "v2", ...): a mark names the pass that took the message.
_PASS_IDS = itertools.count(1)

_release = saves.release_turn        # the one release (Plan decision 31): unlock, then end_after_turn


@dataclass
class VoicePass:
    """One voicing pass over one session OBJECT of one build (`epoch`)."""

    session: Any
    epoch: int
    id: str = field(default_factory=lambda: f"v{next(_PASS_IDS)}")
    cancel: CancelToken = field(default_factory=CancelToken)
    attempts: int = 0
    deadline: float = 0.0
    rerun: bool = False
    #: When run_pass began (the metric's ms), each snapped person's `rev`, the
    #: threads it voiced (the summary looks there first), and the messages
    #: whose reply it parked in the inbox (their marks are kept for the drain).
    started: float = 0.0
    revs: dict[str, Any] = field(default_factory=dict)
    threads: list[str] = field(default_factory=list)
    parked: set[str] = field(default_factory=set)
    #: Each commit's status in this run (`ok`, `fallback`, `discarded`): the pass's ONE metric is read off them.
    statuses: list[str] = field(default_factory=list)

    @property
    def key(self) -> tuple[str, int]:
        return (str(self.session.session_id), int(self.epoch))


# -- settings -----------------------------------------------------------------------------------


def _retry_ms() -> list[int]:
    return [int(x) for x in social.setting("voice.commit_retry_ms", [50, 100, 200, 400, 800])]


def _hosting_deadline() -> Optional[float]:
    """`hosting.turn_deadline_seconds` when hosted, else None."""
    if not hosting_enabled():
        return None
    value = get_config().get("hosting.turn_deadline_seconds", None)
    return float(value) if value is not None else None


def _deadline_seconds() -> float:
    """`social.voice.pass_deadline_seconds`, or hosted `hosting.turn_deadline_seconds` if sooner."""
    own = float(social.setting("voice.pass_deadline_seconds", 300))
    hosted = _hosting_deadline()
    return own if hosted is None else min(own, hosted)


# -- the module's bindings ------------------------------------------------------------------------

#: The model function a scheduled pass uses (None: `voicing.production_llm_fn()`); tests set a stub.
_llm_fn: Optional[voicing.LLMFn] = None
#: The ONE-argument summary function (None: `memory.production_summary_fn()`, pre-flight F10).
_summary_fn: Optional[memory.SummaryFn] = None
#: `(session_id, event, payload) -> None`: the room-checked background push (`FlaskScene.emit_to_session`).
_emitter: Optional[Callable[[str, str, dict[str, Any]], None]] = None


def set_llm_fn(fn: Optional[voicing.LLMFn]) -> None:
    global _llm_fn
    _llm_fn = fn


def set_summary_fn(fn: Optional[memory.SummaryFn]) -> None:
    """The summarizer's model function: ONE argument, the messages (pre-flight F10)."""
    global _summary_fn
    _summary_fn = fn


def set_emitter(fn: Optional[Callable[[str, str, dict[str, Any]], None]]) -> None:
    global _emitter
    _emitter = fn


def emit(session_id: str, event: str, body: dict[str, Any]) -> bool:
    """One background push through the room-checked emitter (`media_ready`, T19); never raises. False: not sent."""
    emitter = _emitter
    if emitter is None:
        return False
    try:
        emitter(str(session_id), event, body)
        return True
    except Exception as exc:  # noqa: BLE001 -- a push never fails what made it
        logger.warning("[social] %s not pushed (operation=emit, id=%s): %s", event, session_id, exc)
        return False


def _report_pass(session: Any, status: str, ms: float = 0.0) -> None:
    """One pass outcome to the `phone` metric (`event: voice_pass`); local mode records nothing."""
    from engine.scenes import default_scene

    default_scene._report_phone(session, "voice_pass", status, ms)


def _elapsed_ms(p: Optional[VoicePass]) -> float:
    return 0.0 if p is None or not p.started else max(0.0, (time.monotonic() - p.started) * 1000.0)


# -- waiting, cancellably ---------------------------------------------------------------------------


def _cancel_wait(cancel: CancelToken, seconds: float) -> None:
    """Wait up to ``seconds``, returning at once if ``cancel`` fires (an Event, never a sleep)."""
    if seconds <= 0 or cancel.cancelled:
        return
    woken = threading.Event()
    cancel.add_hook(woken.set)
    try:
        woken.wait(seconds)
    finally:
        cancel.remove_hook(woken.set)


def _try_lock(session: Any, cancel: CancelToken) -> bool:
    """The turn lock, NON-BLOCKING, on the commit_retry_ms schedule (never a blocking take)."""
    for delay in [0] + _retry_ms():
        if cancel.cancelled:
            return False
        if delay:
            _cancel_wait(cancel, delay / 1000.0)
            if cancel.cancelled:
                return False
        if session.lock.acquire(blocking=False):
            return True
    return False


# -- what is due ------------------------------------------------------------------------------------


def _voiceable(state: GameState, session: Any) -> list[dict[str, Any]]:
    """
    The due messages a pass may take now (CALLER HOLDS the lock, or owns the
    session's thread): theirs, not voiced, not marked by a live pass, in a
    thread still listed, from a person neither gone (unmatched, blocked) nor
    ended. The due messages of a person who LEFT are retired here, the first
    time they are seen (`_withdraw`): never voiced, never shown, not even
    after a reconnect.
    """
    marked = dict(tuple(getattr(session, "voicing", {}).items()))
    threads = (state.social or {}).get("threads") or {}
    out = []
    left: list[dict[str, Any]] = []
    for m in messaging.unvoiced(state):
        if m["id"] in marked or m.get("from") == "player" or (m.get("from") == "system" and not _is_recap(m)):
            continue
        t = threads.get(m["thread_id"])
        if t is None:
            continue
        if _left(state, t, str(t["pid"]) if m.get("from") == "system" else str(m.get("from"))):
            left.append(m)
            continue
        out.append(m)
    if left:
        _withdraw(session, left)
    return out


def _is_recap(message: dict[str, Any]) -> bool:
    """A due meet-up recap (a system card voiced by `meets.voice_recap`, spec §14.4)."""
    from engine.social import meets   # lazily: meets loads after this module

    return meets.is_recap(message)


def _voice(snap: voicing.PersonSnapshot, llm_fn: Optional[voicing.LLMFn]) -> voicing.VoicedReply:
    """One snapshot voiced: a recap by `meets.voice_recap` (its own prompt and check), else `voicing.voice`."""
    if snap.recap:
        from engine.social import meets

        return meets.voice_recap(snap.recap, llm_fn)
    return voicing.voice(snap, llm_fn)


def _deadline_reply(snap: voicing.PersonSnapshot) -> voicing.VoicedReply:
    if snap.recap:
        from engine.social import meets

        return meets.recap_fallback(snap.recap, "deadline")
    return voicing.fallback_reply(snap, "deadline")


def _left(state: GameState, thread: dict[str, Any], pid: str) -> bool:
    """The person left: unmatched or blocked (their thread unlisted, or off every app), or ended."""
    from engine.social import matching

    person = ((state.social or {}).get("people") or {}).get(pid) or {}
    return not matching.listed(thread) or apps.gone(state, pid) or person.get("stage") == "ended"


def _withdraw(session: Any, rows: list[dict[str, Any]]) -> int:
    """
    Retire due messages of a person who left (CALLER HOLDS the lock): through
    `social_voiced` `op: withdraw` -- `voiced: "withdrawn"`, no words -- out of
    the payload and of every later pass. Marks the run dirty. Returns how many.
    """
    state = session.engine.state
    by_thread: dict[str, list[str]] = {}
    for m in rows:
        by_thread.setdefault(str(m["thread_id"]), []).append(str(m["id"]))
    done = 0
    for tid, ids in by_thread.items():
        result = apply_effect(state, {"type": "social_voiced", "op": "withdraw", "thread_id": tid,
                                      "message_ids": ids})
        if result.get("ok"):
            done += len(result.get("message_ids") or ())
        for mid in ids:
            session.voicing.pop(mid, None)
    if done:
        logger.info("[social] Due messages withdrawn: their person left (operation=_withdraw, count=%d)", done)
        saves.mark_dirty(session, "withdrawn")
        for tid in by_thread:
            _push_message(session, tid, [])         # the thread row at once: no "..." left on screen
    return done


def pending(session: Any) -> bool:
    """Whether a pass would find anything to voice in ``session`` (CALLER HOLDS its lock, or owns its thread)."""
    return bool(_voiceable(session.engine.state, session))


def snapshot(session: Any, p: VoicePass) -> list[voicing.PersonSnapshot]:
    """
    The people this pass voices (CALLER HOLDS the turn lock): §11.1's
    priority -- the thread's `focus` desc, then the person's warmth desc, then
    the oldest due message first -- at most `social.voice.max_per_pass`
    PEOPLE, one thread each; each a `voicing.snapshot_of` (deep copies) of
    only the due messages no live pass has marked. Then those messages are
    MARKED for ``p`` in `session.voicing`. More left over: ``p.rerun``.
    """
    state = session.engine.state
    candidates = _voiceable(state, session)
    if not candidates:
        return []
    threads = state.social.get("threads") or {}
    people = state.social.get("people") or {}
    by_thread: dict[str, list[dict[str, Any]]] = {}
    for m in candidates:
        by_thread.setdefault(m["thread_id"], []).append(m)

    def priority(tid: str) -> tuple[float, float, float]:
        t = threads[tid]
        warmth = float((people.get(str(t["pid"])) or {}).get("warmth") or 0)
        return (-float(t.get("focus") or 0), -warmth, float(by_thread[tid][0]["at"]))

    limit = max(1, int(social.setting("voice.max_per_pass", 3)))
    taken_people: set[str] = set()
    snaps: list[voicing.PersonSnapshot] = []
    for tid in sorted(by_thread, key=priority):
        pid = str(threads[tid]["pid"])
        if pid in taken_people or len(snaps) >= limit:
            p.rerun = True
            continue
        recaps = [m for m in by_thread[tid] if _is_recap(m)]
        if recaps:
            # A recap first, alone (its own prompt, spec §14.4); their own due messages wait a pass.
            from engine.social import meets

            snap = meets.recap_snapshot(state, recaps[0])
            if snap is None:                       # its meet is gone (trimmed): retired, never starving the rest
                _withdraw(session, [recaps[0]])
                p.rerun = True
                continue
            if len(by_thread[tid]) > 1:
                p.rerun = True
            due = list(snap.due)
        else:
            snap = voicing.snapshot_of(state, tid)
            if snap is None:
                continue
            ids = {m["id"] for m in by_thread[tid]}
            due = [m for m in snap.due if m.get("id") in ids]
            if not due:
                continue
        snaps.append(dataclasses.replace(snap, due=due))
        taken_people.add(pid)
        p.revs[pid] = (people.get(pid) or {}).get("rev")
        if tid not in p.threads:
            p.threads.append(tid)
        for m in due:
            session.voicing[str(m["id"])] = p.id
    return snaps


def _clear_marks(session: Any, p: VoicePass) -> None:
    """This pass's marks dropped (bar those parked in the inbox): read from a copy (F22)."""
    for mid, owner in tuple(session.voicing.items()):
        if owner == p.id and mid not in p.parked:
            session.voicing.pop(mid, None)


# -- the commit (§16.3) ---------------------------------------------------------------------------


#: The maps of rows in ``state.social`` whose rows name their person by ``pid``:
#: a commit's rollback copies that person's rows of each deep (``ScopedTransaction``).
PERSON_ROW_MAPS: tuple[str, ...] = ("threads", "requests", "media", "games", "meets")


class ScopedTransaction:
    """
    The voiced commit's rollback snapshot (spec §16.3 step 4), SCOPED to what
    one reply's commit can write (v0.22.0 T26; it was ``StateTransaction``'s
    whole-state ``to_save_dict`` under the turn lock, about 0.4 s a commit at
    day 30). A commit writes only the replying person's rows and adds rows:
    ``social_voiced`` their thread's due messages, ``social_regard`` and
    ``social_memory`` their person row, a proposal a request, a media row, a
    game or a meet of theirs, a queued event, a notification, a counter, a
    seq, a draw on a person's or the world's stream. So the snapshot keeps:

    - each map of rows in ``state.social`` (``people`` and
      ``PERSON_ROW_MAPS``) SHALLOW -- a row added or removed is undone --
      with the person's own rows copied DEEP;
    - the queue shallow, the person's queued events deep;
    - every other key of the slice (counters, notifications, apps, settings,
      the player, the scalars) deep: each is small and bounded;
    - ``state.rng_counters`` (``world_rng``'s counters).

    Rollback restores IN PLACE: each container keeps its identity, as
    ``restore_in_place`` keeps the state's. ``tests/test_social_commit_scope.py``
    holds it: every commit of a played run, forced to roll back after all of its
    writes, leaves ``to_save_dict`` byte-identical, and a commit writes nothing
    outside ``social`` and ``rng_counters``.
    """

    def __init__(self, state: GameState, pid: str) -> None:
        self.state = state
        self.pid = str(pid)
        self.committed = False
        slice_ = state.social if isinstance(state.social, dict) else {}
        self._saved: dict[str, tuple[str, Any]] = {}
        for key, value in slice_.items():
            self._saved[key] = self._keep(key, value)
        self._rng = copy.deepcopy(dict(state.rng_counters or {}))

    def _keep(self, key: str, value: Any) -> tuple[str, Any]:
        pid = self.pid
        if key == "people" and isinstance(value, dict):
            rows = dict(value)
            if pid in rows:
                rows[pid] = copy.deepcopy(rows[pid])
            return "map", rows
        if key in PERSON_ROW_MAPS and isinstance(value, dict):
            return "map", {k: (copy.deepcopy(r) if isinstance(r, dict) and str(r.get("pid", "")) == pid else r)
                           for k, r in value.items()}
        if key == "queue" and isinstance(value, list):
            return "list", [copy.deepcopy(e) if isinstance(e, dict) and str(e.get("pid", "")) == pid else e
                            for e in value]
        return "value", copy.deepcopy(value)

    def rollback(self) -> None:
        """Every write since the snapshot undone, each container restored in place."""
        slice_ = self.state.social
        if isinstance(slice_, dict):
            for key in [k for k in slice_ if k not in self._saved]:
                del slice_[key]
            for key, (how, saved) in self._saved.items():
                current = slice_.get(key)
                if how == "map" and isinstance(current, dict):
                    current.clear()
                    current.update(saved)
                elif how == "list" and isinstance(current, list):
                    current[:] = saved
                else:
                    slice_[key] = saved
        counters = self.state.rng_counters
        counters.clear()
        counters.update(self._rng)
        logger.debug("[social] Commit rolled back (operation=rollback, pid=%s)", self.pid)

    def commit(self) -> None:
        self.committed = True


@contextmanager
def scoped_transaction(state: GameState, pid: str) -> Iterator[ScopedTransaction]:
    """One voiced commit's transaction (``ScopedTransaction``): rolled back if the block raises."""
    tx = ScopedTransaction(state, pid)
    try:
        yield tx
    except Exception:
        tx.rollback()
        raise



def _decision_of(row: dict[str, Any]) -> Decision:
    known = {f.name for f in dataclasses.fields(Decision)}
    raw = {k: v for k, v in dict(row.get("decision") or {}).items() if k in known}
    raw.setdefault("situation", "reply")
    return Decision(**raw)


def commit(session: Any, p: VoicePass, reply: voicing.VoicedReply, *, store: Any = None, last: bool = False) -> str:
    """
    One voiced reply committed (spec §16.3): ``committed``, ``discarded``,
    ``inbox`` (the lock stayed busy past the retries: parked, its messages
    still marked) or ``ended`` (the session is no longer this pass's).
    ``last`` saves under this commit's lock (the pass's last commit, §17.2).
    """
    if not _try_lock(session, p.cancel):
        if p.cancel.cancelled or not saves.alive(session, p.epoch, store):
            return "ended"
        session.inbox.put({"kind": "voiced", "payload": reply, "epoch": p.epoch,
                           "account": session.owner, "pass": p.id, "rev": p.revs.get(reply.pid)})
        p.parked.update(reply.message_ids)
        p.rerun = True                                 # the next pass's snapshot drains it if no action does
        logger.info("[social] Reply parked in the inbox (operation=commit, pid=%s, pass=%s)", reply.pid, p.id)
        return "inbox"
    try:
        # 1. Liveness.
        if p.cancel.cancelled or not saves.alive(session, p.epoch, store):
            return "ended"
        status = _apply_reply(session, p.id, reply, last=last, snap_rev=p.revs.get(reply.pid),
                              epoch=p.epoch, store=store)
        p.statuses.append(status)
        return "committed" if status in ("ok", "fallback") else "discarded"
    finally:
        _release(session)


def _apply_reply(session: Any, pass_id: str, reply: voicing.VoicedReply, *, last: bool = False,
                 snap_rev: Any = None, epoch: Optional[int] = None, store: Any = None) -> str:
    """
    §16.3 steps 2-5, under the turn lock, shared by `commit` and the inbox
    drain: ``ok`` or ``fallback`` (committed) or ``discarded``. With
    ``epoch``, liveness is asked once more just before a save (a local
    resume takes no old lock: finding 7's window, narrowed, not closed).
    """
    state = session.engine.state
    slice_ = state.social or {}
    thread = (slice_.get("threads") or {}).get(reply.thread_id)
    person = (slice_.get("people") or {}).get(reply.pid) or {}
    marks = dict(tuple(session.voicing.items()))
    ids = {str(i) for i in reply.message_ids}
    # 2. Still wanted?
    wanted = [m for m in (thread or {}).get("messages", [])
              if str(m["id"]) in ids and m.get("voiced") is False and marks.get(str(m["id"])) == pass_id]
    gone = thread is not None and _left(state, thread, reply.pid)
    if thread is None or not wanted or gone:
        logger.info("[social] Reply discarded (operation=commit, pid=%s, rev_then=%s, rev_now=%s)",
                    reply.pid, snap_rev, person.get("rev"))
        for mid in ids:
            if marks.get(mid) == pass_id:
                session.voicing.pop(mid, None)
        if gone:                                       # their person left: every due message of theirs retired
            _withdraw(session, [m for t in (slice_.get("threads") or {}).values() if t.get("pid") == reply.pid
                                for m in t.get("messages") or [] if m.get("voiced") is False
                                and m.get("from") == reply.pid])
        return "discarded"
    # 3. Re-check what depends on state: proposals legal NOW, the state checks against the live view.
    legal = relationships.legal_proposals(state, reply.pid)
    proposals = [x for x in reply.proposals if x in legal]
    lists = {"bubbles": list(reply.bubbles), "shared": list(reply.shared), "learned": list(reply.learned)}
    regard, caption, fallback = dict(reply.regard), reply.caption, reply.fallback
    recap = _decision_of(wanted[0]).kind == "recap"   # judged by its band at voicing; no regard, no state check
    if not fallback and not recap:
        view = agreement.view_from_state(state, reply.pid)
        found = [f for f in agreement.check(lists, _decision_of(wanted[0]), view) if f.check in agreement.STATE_CHECKS]
        if found:
            logger.info("[social] A reply's state check failed at commit (operation=commit, pid=%s, checks=%s)",
                        reply.pid, sorted({f.check for f in found}))
        for where in agreement.WHERES:
            drop = {f.index for f in found if f.where == where}
            lists[where] = [x for i, x in enumerate(lists[where]) if i not in drop]
        if caption and [f for f in voicing.transcript_failures({"media": {"caption": caption}}, _decision_of(wanted[0]),
                                                               view) if f.check in agreement.STATE_CHECKS]:
            caption = ""                                # a voice note's transcript, re-checked as its bubbles are
        if not lists["bubbles"]:
            fb = voicing.fallback_reply_for(state, reply.pid, reply.thread_id, wanted, "state changed",
                                            failures=list(reply.failures) + [f.check for f in found])
            lists = {"bubbles": list(fb.bubbles), "shared": [], "learned": []}
            regard, caption, fallback, proposals = dict(fb.regard), "", True, []
    # 4. Apply, in one transaction (rule 3: every write an effect).
    with collecting() as applied:
        with scoped_transaction(state, reply.pid) as tx:
            done = apply_effect(state, {"type": "social_voiced", "thread_id": reply.thread_id,
                                        "message_ids": [m["id"] for m in wanted], "bubbles": lists["bubbles"],
                                        "caption": caption, "fallback": fallback})
            if not done.get("ok"):
                tx.rollback()
                logger.info("[social] Reply refused at commit (operation=commit, pid=%s): %s",
                            reply.pid, done.get("text"))
                for m in wanted:
                    session.voicing.pop(str(m["id"]), None)
                return "discarded"
            # The regard a fallback proposes too (relationships.yaml regard.fallback, the §10.2 ruling),
            # clamped against the per-day cap of the in-game day NOW.
            if not recap:
                relationships.apply_regard(state, reply.pid, regard, day=state.world_day, fallback=fallback)
            if not fallback and not recap:
                if lists["shared"]:
                    memory.add_canon(state, reply.pid, lists["shared"])
                if lists["learned"]:
                    memory.add_knows(state, reply.pid, lists["learned"])
                for name in proposals:
                    relationships.apply_proposal(state, reply.pid, name)
            tx.commit()
    for m in wanted:
        session.voicing.pop(str(m["id"]), None)
    if any(m.get("media_id") for m in wanted):
        # The caption is committed: its media job can go now (spec §13.4), not at the next action.
        from engine.social import media

        try:
            media.submit_due(session)
        except Exception as exc:  # noqa: BLE001 -- the reply is committed; the next action submits again
            logger.warning("[social] Media jobs not submitted (operation=commit, id=%s): %s", session.session_id, exc)
    # 5. Save (the pass's last commit, or a reason that saves at once: §17.2), else mark dirty; push.
    reasons = {str(r.get("save_reason") or "") for r in applied if isinstance(r, dict)} & saves.IMMEDIATE
    if (last or reasons) and (epoch is None or saves.alive(session, epoch, store)):
        saves.save_now(session)
    elif last or reasons:
        logger.info("[social] Not saved: the run is no longer this pass's (operation=commit, id=%s)",
                    session.session_id)
    else:
        saves.mark_dirty(session, "voiced")
    _push_message(session, reply.thread_id, [str(m["id"]) for m in wanted])
    return "fallback" if fallback else "ok"


def _push_message(session: Any, thread_id: str, message_ids: list[str]) -> None:
    """
    `phone_message` (§17.3) through the room-checked emitter; never raises. With no
    ids (a withdrawal) it carries no message, only the thread row, the badges and
    the notification, so the thread's "..." goes at once. A withdrawn message is
    never pushed.
    """
    emitter = _emitter
    if emitter is None:
        return
    from engine.social import matching
    from engine.social import payload as phone_payload

    state = session.engine.state
    t = messaging.thread(state, thread_id)
    if t is None or not matching.listed(t):
        return
    views = [messaging.message_view(state, t, m) for m in t.get("messages") or []
             if str(m["id"]) in message_ids and messaging.shown(m)]   # a withdrawn one is never pushed
    body = {"message": views[-1] if views else None, "messages": views,
            "thread": phone_payload.thread_row(state, thread_id, session),
            "badges": messaging.badges(state), "notification": messaging.latest_notification(state, thread_id)}
    try:
        emitter(str(session.session_id), "phone_message", body)
    except Exception as exc:  # noqa: BLE001 -- a push never fails a commit
        logger.warning("[social] phone_message not pushed (operation=_push_message, id=%s): %s",
                       session.session_id, exc)


def drain_inbox(session: Any) -> int:
    """
    Apply what waits in the session's inbox (CALLER HOLDS the turn lock),
    each item re-validated (§16.4): its epoch must be the session's (and a
    media result's account its owner's), else it is dropped with a log
    line. A `voiced` item is a parked reply (`_apply_reply`); a `media` item
    a job's result (`media.apply_and_push`, T19). Returns how many were applied.
    """
    inbox = getattr(session, "inbox", None)
    if inbox is None or not len(inbox):
        return 0
    applied = 0
    for item in inbox.drain():
        kind = item.get("kind")
        if item.get("epoch") != session.epoch:
            logger.info("[social] Inbox item dropped: another build's (operation=drain_inbox, kind=%s)", kind)
            continue
        if kind == "voiced":
            pass_id = str(item.get("pass") or "")
            try:
                status = _apply_reply(session, pass_id, item["payload"], snap_rev=item.get("rev"))
            except Exception as exc:  # noqa: BLE001 -- one item's fault costs that item, never the player's action
                logger.warning("[social] Inbox item failed, dropped (operation=drain_inbox, pass=%s): %s",
                               pass_id, exc)
                for mid in getattr(item.get("payload"), "message_ids", ()) or ():
                    if session.voicing.get(str(mid)) == pass_id:
                        session.voicing.pop(str(mid), None)
                continue
            applied += status in ("ok", "fallback")
            continue
        if kind == "media":
            # A media job's result (spec §13.4 step 8): it must be this owner's (§16.4).
            if str(item.get("account") or "") != str(session.owner or ""):
                logger.info("[social] Inbox item dropped: another account's media (operation=drain_inbox)")
                continue
            from engine.social import media

            try:
                applied += bool(media.apply_and_push(session, item["payload"], float(item.get("ms") or 0.0),
                                                     str(item.get("digest") or "")))
            except Exception as exc:  # noqa: BLE001 -- one item's fault costs that item, never the player's action
                logger.warning("[social] Inbox media result failed, dropped (operation=drain_inbox): %s", exc)
            continue
        logger.info("[social] Inbox item dropped: no handler (operation=drain_inbox, kind=%s)", kind)
    return applied


_drain_inbox = drain_inbox


# -- the summary (§12.3) ----------------------------------------------------------------------------


def _summarise_one(session: Any, p: VoicePass, *, store: Any = None) -> bool:
    """
    At most one thread past its verbatim window summarised (spec §12.3):
    its view read under the lock (`memory.thread_view`), the archive read and
    the summary written holding NO lock (`with_archive`, `summarize_thread`,
    the ONE-argument summary function), then committed under the lock after
    the generation check (`commit_summary`, refused if it went stale).
    """
    if p.cancel.cancelled or not saves.alive(session, p.epoch, store):
        return False
    if not _try_lock(session, p.cancel):
        return False
    try:
        if not saves.alive(session, p.epoch, store):
            return False
        state = session.engine.state
        rows = (state.social or {}).get("threads") or {}
        threads = list(rows)
        order = [t for t in p.threads if t in threads] + [t for t in threads if t not in p.threads]
        verbatim = max(1, int(social.setting("memory.verbatim", 24)))
        view = None
        for tid in order:
            t = rows[tid]
            if len(t.get("messages") or []) <= verbatim and not t.get("archived_through"):
                continue                               # nothing past the verbatim window: no copy made
            if (t.get("stamp") and not t.get("messages")) or archive.dead(state, t):
                continue                               # a dead thread, emptied or about to be: no model call (T26)
            candidate = memory.thread_view(state, tid)
            if candidate is not None and (candidate.get("overflow") or candidate.get("needs_archive")):
                view = candidate
                break
    finally:
        _release(session)
    if view is None:
        return False
    view = memory.with_archive(view, archive.save_dir(session))
    if not view.get("overflow"):
        return False
    fn = _summary_fn or memory.production_summary_fn()
    text, _by_model = memory.summarize_thread(view, fn)
    if p.cancel.cancelled or not _try_lock(session, p.cancel):
        return False
    try:
        if not saves.alive(session, p.epoch, store):
            return False
        result = memory.commit_summary(session.engine.state, view, text)
        if result.get("ok"):
            saves.mark_dirty(session, "summary")
        return bool(result.get("ok"))
    finally:
        _release(session)


# -- the pass ---------------------------------------------------------------------------------------


def run_pass(p: VoicePass, *, llm_fn: Optional[voicing.LLMFn], admit: bool, store: Any = None) -> str:
    """The pass body, shared by the scheduler and `run_until_quiet` (see the module docstring)."""
    session = p.session
    # THE GENERATION CHECK, first of four (before admission, snapshot, each commit).
    if p.cancel.cancelled or not saves.alive(session, p.epoch, store):
        return "cancelled"
    p.started = time.monotonic()
    p.deadline = p.started + _deadline_seconds()
    p.statuses = []
    admission = None
    if admit:
        from engine.llm.gate import InferenceBusy, admit_turn

        # Nothing due: no narration ticket asked for at all (a swipe that
        # landed while a pass held the lock requests one more pass). What is
        # parked in the inbox (a media result, a reply) is drained HERE, before
        # admission: applying it calls no model, so it never waits on a ticket
        # (final review I1). Tried on the commit_retry_ms schedule, never
        # waited for; a lock still busy is no answer, so it admits.
        if _try_lock(session, p.cancel):
            try:
                if not saves.alive(session, p.epoch, store):
                    return "cancelled"
                _drain_inbox(session)                  # each item re-validated (§16.4)
                due = pending(session)
            finally:
                _release(session)
            if not due:
                return "ok"
        elif p.cancel.cancelled:
            return "cancelled"

        try:
            admission = admit_turn(
                timeout=float(social.setting("voice.admit_wait_seconds", 5)),
                label="voice",
                account=str(session.owner or ""),
                deadline_seconds=_hosting_deadline(),
                cancel=p.cancel,
            )
        except InferenceBusy as exc:
            logger.info("[social] Voicing pass not admitted (operation=run_pass, pass=%s, reason=%s)",
                        p.id, getattr(exc, "reason", ""))
            return "cancelled" if p.cancel.cancelled else "busy"   # nothing marked yet
    try:
        if p.cancel.cancelled or not saves.alive(session, p.epoch, store):
            return "cancelled"
        if not _try_lock(session, p.cancel):
            return "cancelled" if p.cancel.cancelled else "busy"
        try:
            if not saves.alive(session, p.epoch, store):
                return "cancelled"
            _drain_inbox(session)                      # each item re-validated (§16.4)
            snaps = snapshot(session, p)               # READ, then MARK in session.voicing
        finally:
            _release(session)
        for i, snap in enumerate(snaps):
            if p.cancel.cancelled or not saves.alive(session, p.epoch, store):
                return "cancelled"
            if time.monotonic() >= p.deadline:
                reply = _deadline_reply(snap)
            elif snap.recap:
                reply = _voice(snap, llm_fn)           # a system card: nobody is typing it
            else:
                session.typing.add(snap.thread_id)     # read by every payload built meanwhile (§9.4)
                try:
                    reply = _voice(snap, llm_fn)
                finally:
                    session.typing.discard(snap.thread_id)
            if p.cancel.cancelled:
                return "cancelled"                     # an answer that came back after cancel is discarded
            result = commit(session, p, reply, store=store, last=(i == len(snaps) - 1))
            if result == "ended":
                return "cancelled"
        if admission is not None:
            admission.release()                        # the summary is a utility call: not on the ticket
            admission = None
        _summarise_one(session, p, store=store)        # at most one utility call, holding no lock
        outcome = _outcome(p.statuses)
        if p.statuses:
            _report_pass(session, outcome, _elapsed_ms(p))   # ONE voice_pass metric per pass that committed
        return outcome
    finally:
        if admission is not None:
            admission.release()
        _clear_marks(session, p)


def _outcome(statuses: list[str]) -> str:
    """A pass's outcome from its commits: any fallback, else any committed, else all discarded; none: ok."""
    if "fallback" in statuses:
        return "fallback"
    if "ok" in statuses or not statuses:
        return "ok"
    return "discarded"


def run_until_quiet(session: Any, llm_fn: Optional[voicing.LLMFn], *, max_passes: int = 50) -> int:
    """
    Voice ``session`` until nothing is left to voice (spec §16.2):
    `run_pass` run synchronously on the caller's thread, no scheduler, no
    admission. The caller owns the session's thread (a harness, a replay).
    Returns the passes run.
    """
    passes = 0
    while passes < max_passes and (pending(session) or len(session.inbox)):
        outcome = run_pass(VoicePass(session, session.epoch), llm_fn=llm_fn, admit=False)
        passes += 1
        if outcome in ("cancelled", "busy"):
            break
    return passes


# -- the scheduler ----------------------------------------------------------------------------------


class VoicingScheduler:
    """
    The process's voicing passes (see the module docstring). ``time_fn`` and
    ``sleep_fn`` drive the backoff (tests inject a fake clock); ``admit``
    answers whether a pass takes an admission (hosted mode, read per pass).
    """

    def __init__(self, *, workers: Optional[int] = None, queue_max: Optional[int] = None,
                 time_fn: Callable[[], float] = time.monotonic,
                 sleep_fn: Optional[Callable[[float], None]] = None,
                 admit: Callable[[], bool] = hosting_enabled) -> None:
        self._lock = threading.Lock()                # LEAF: the queues and the in-flight table only
        self._wake = threading.Event()
        self._ready: deque[VoicePass] = deque()
        self._timed: list[tuple[float, int, VoicePass]] = []
        self._seq = itertools.count()
        self._queued: dict[tuple[str, int], VoicePass] = {}
        self._in_flight: dict[tuple[str, int], VoicePass] = {}
        #: Keys requested while their in-flight pass was CANCELLED (a room emptied, then the
        #: player came back): that pass will not rerun, so a fresh one is queued when it ends.
        self._rerequested: set[tuple[str, int]] = set()
        self._threads: list[threading.Thread] = []
        self._workers = workers
        self._queue_max = queue_max
        self._time = time_fn
        self._sleep = sleep_fn
        self._admit = admit
        self._paused = False
        self._stopped = False

    # -- the switches --

    def pause(self) -> None:
        """Paused: `request` queues nothing and no worker starts a pass (the tests' direct-pass mode)."""
        with self._lock:
            self._paused = True

    def resume(self) -> None:
        with self._lock:
            self._paused = False
            start = bool(self._ready or self._timed)
        if start:
            self._start_workers()
        self._wake.set()

    # -- requests --

    def request(self, session: Any) -> None:
        """A pass for ``session`` (idempotent): queued, or ``rerun`` set on the one in flight."""
        key = (str(session.session_id), int(session.epoch))
        limit = max(1, int(self._queue_max or social.setting("voice.queue_max", 64)))   # read before the leaf
        dropped: Optional[VoicePass] = None
        with self._lock:
            if self._paused or self._stopped:
                return
            if key in self._queued:
                return
            running = self._in_flight.get(key)
            if running is not None:
                if running.cancel.cancelled:
                    self._rerequested.add(key)       # queued afresh once it ends (_after)
                else:
                    running.rerun = True
                return
            p = VoicePass(session, int(session.epoch))
            self._queued[key] = p
            self._ready.append(p)
            if len(self._queued) > limit:
                dropped = self._ready.popleft() if self._ready else None
                if dropped is not None:
                    self._queued.pop(dropped.key, None)
        if dropped is not None:
            logger.info("[social] Voicing queue full: the oldest request dropped (operation=request, id=%s)",
                        dropped.session.session_id)
        self._start_workers()
        self._wake.set()

    def _start_workers(self) -> None:
        count = max(1, int(self._workers or social.setting("voice.workers", 2)))
        new: list[threading.Thread] = []
        with self._lock:
            if self._stopped:
                return
            while len(self._threads) < count:
                thread = threading.Thread(target=self._run, name=f"social-voicer-{len(self._threads) + 1}",
                                          daemon=True)
                self._threads.append(thread)
                new.append(thread)
        for thread in new:
            thread.start()

    # -- the worker --

    def _next(self) -> tuple[Optional[VoicePass], Optional[float]]:
        """(a pass to run now, marked in flight) or (None, seconds until the next timed one, or None)."""
        with self._lock:
            if self._paused or self._stopped:
                return None, None
            now = self._time()
            while self._timed and self._timed[0][0] <= now:
                _due, _seq, p = heapq.heappop(self._timed)
                self._ready.append(p)
            if self._ready:
                p = self._ready.popleft()
                self._queued.pop(p.key, None)
                self._in_flight[p.key] = p
                return p, None
            return None, (self._timed[0][0] - now) if self._timed else None

    def _run(self) -> None:
        while not self._stopped:
            self._wake.clear()
            p, wait = self._next()
            if p is None:
                if wait is not None and self._sleep is not None:
                    self._sleep(wait)
                else:
                    self._wake.wait(IDLE_WAIT_SECONDS if wait is None else min(wait, IDLE_WAIT_SECONDS))
                continue
            outcome = "cancelled"
            try:
                llm_fn = _llm_fn or voicing.production_llm_fn()
                outcome = run_pass(p, llm_fn=llm_fn, admit=bool(self._admit()))
            except Exception as exc:  # noqa: BLE001 -- the worker outlives one pass's fault
                logger.warning("[social] Voicing pass failed (operation=run_pass, pass=%s): %s", p.id, exc)
                outcome = "cancelled"
            self._after(p, outcome)

    def _after(self, p: VoicePass, outcome: str) -> None:
        """Out of flight; re-queued (busy with backoff, a rerun at once) or dropped -- one step under the lock."""
        session_alive = saves.alive(p.session, p.epoch)
        live = outcome in ("ok", "fallback", "discarded", "busy") and not p.cancel.cancelled and session_alive
        limit = max(1, int(social.setting("voice.max_attempts", 6)))      # read before the leaf
        dropped = False
        with self._lock:
            if self._in_flight.get(p.key) is p:
                self._in_flight.pop(p.key, None)
            # A request that landed between a cancel's judgement and its firing set
            # `rerun` on a pass that was about to be cancelled: fresh, as I1's is.
            fresh = p.key in self._rerequested or (p.rerun and p.cancel.cancelled)
            self._rerequested.discard(p.key)
            if not live:
                if fresh and session_alive and not self._stopped and p.key not in self._queued:
                    successor = VoicePass(p.session, p.epoch)
                    self._queued[p.key] = successor
                    self._ready.append(successor)
                    self._wake.set()
                return
            if self._stopped or p.key in self._queued:
                return
            if outcome == "busy":
                p.attempts += 1
                if p.attempts >= limit:
                    dropped = True
                else:
                    self._queued[p.key] = p
                    heapq.heappush(self._timed, (self._time() + float(2 ** p.attempts), next(self._seq), p))
            elif p.rerun or fresh:
                p.rerun, p.attempts = False, 0
                self._queued[p.key] = p
                self._ready.append(p)
        if outcome == "busy":
            _report_pass(p.session, "dropped" if dropped else "busy", _elapsed_ms(p))
        if dropped:
            logger.info("[social] Voicing pass dropped after %d busy attempts (operation=_after, id=%s); "
                        "its messages stay due", p.attempts, p.session.session_id)
        self._wake.set()

    # -- cancelling --

    def _all(self) -> list[VoicePass]:
        """CALLER HOLDS _lock."""
        return list(self._ready) + [entry[2] for entry in self._timed] + list(self._in_flight.values())

    def _remove(self, gone: list[VoicePass]) -> None:
        """Drop ``gone`` from the queues (CALLER HOLDS _lock); in-flight ones leave on their own."""
        ids = {id(p) for p in gone}
        self._ready = deque(p for p in self._ready if id(p) not in ids)
        self._timed = [entry for entry in self._timed if id(entry[2]) not in ids]
        heapq.heapify(self._timed)
        for p in gone:
            if self._queued.get(p.key) is p:
                self._queued.pop(p.key, None)

    def _cancel_where(self, doomed: Callable[[VoicePass], bool]) -> int:
        with self._lock:
            candidates = self._all()
        gone = [p for p in candidates if doomed(p)]         # judged holding no lock (liveness takes leaves)
        with self._lock:
            self._remove(gone)
        for p in gone:
            p.cancel.cancel()
        return len(gone)

    def forget(self, session_id: str) -> int:
        """Cancel every pass of ``session_id`` whose (id, epoch) no longer matches a live store entry."""
        return self._cancel_where(lambda p: p.key[0] == session_id and not saves.alive(p.session, p.epoch))

    def cancel_unwatched(self, has_listeners: Callable[[str], bool]) -> int:
        """Cancel every pass whose session's room has no socket left (hosted)."""
        def doomed(p: VoicePass) -> bool:
            try:
                return not has_listeners(p.key[0])
            except Exception:  # noqa: BLE001 -- a room that cannot be read is not judged empty
                return False

        return self._cancel_where(doomed)

    def cancel_all(self) -> int:
        """Cancel everything (a hosted drain, a shutdown)."""
        return self._cancel_where(lambda p: True)

    def in_flight(self) -> int:
        """Passes inside `run_pass` now."""
        with self._lock:
            return len(self._in_flight)

    def queued(self) -> list[VoicePass]:
        """The passes waiting (ready and timed), oldest first; a copy."""
        with self._lock:
            return list(self._ready) + [entry[2] for entry in sorted(self._timed, key=lambda e: (e[0], e[1]))]

    def stop(self) -> None:
        """Cancel everything and end the workers (each joined, bounded)."""
        with self._lock:
            self._stopped = True
            threads = list(self._threads)
        self.cancel_all()
        self._wake.set()
        for thread in threads:
            if thread is not threading.current_thread():
                thread.join(STOP_JOIN_SECONDS)
        with self._lock:
            self._ready.clear()
            self._timed.clear()
            self._queued.clear()


# -- the process's scheduler --------------------------------------------------------------------------

#: The process's one VoicingScheduler, built on first use (double-checked under `_scheduler_lock`).
_scheduler: Optional[VoicingScheduler] = None
_scheduler_lock = threading.Lock()


def get_scheduler() -> VoicingScheduler:
    global _scheduler
    scheduler = _scheduler
    if scheduler is not None:
        return scheduler
    with _scheduler_lock:
        if _scheduler is None:
            _scheduler = VoicingScheduler()
        return _scheduler


def _existing() -> Optional[VoicingScheduler]:
    return _scheduler


def request(session: Any) -> None:
    get_scheduler().request(session)


def request_if_due(session: Any) -> bool:
    """
    After a phone action released its lock: a pass requested when anything is
    due. The turn lock is TRIED to read that (never waited for); held by
    someone else, the pass is requested anyway (idempotent, and a pass in
    flight takes it as `rerun`). True when requested.
    """
    if session.lock.acquire(blocking=False):
        try:
            due = pending(session)
        finally:
            _release(session)
        if not due:
            return False
    request(session)
    return True


def forget(session_id: str) -> None:
    scheduler = _existing()
    if scheduler is not None:
        scheduler.forget(session_id)


def cancel_all() -> None:
    scheduler = _existing()
    if scheduler is not None:
        scheduler.cancel_all()


def cancel_unwatched(has_listeners: Callable[[str], bool]) -> int:
    scheduler = _existing()
    return scheduler.cancel_unwatched(has_listeners) if scheduler is not None else 0


def in_flight() -> int:
    scheduler = _existing()
    return scheduler.in_flight() if scheduler is not None else 0


def reset() -> None:
    """Cancel everything, stop the workers, drop the singleton, the functions back to None (tests' teardown)."""
    global _scheduler, _llm_fn, _summary_fn, _emitter
    with _scheduler_lock:
        scheduler, _scheduler = _scheduler, None
    if scheduler is not None:
        scheduler.stop()
    _llm_fn = None
    _summary_fn = None
    _emitter = None


renew_after_fork(globals(), _scheduler_lock=threading.Lock)


# -- the effect ---------------------------------------------------------------------------------------


@effect_kind("social_voiced")
@recorded
def _e_voiced(state: GameState, effect: dict[str, Any], ctx: EffectContext) -> dict[str, Any]:
    """
    Engine-only: a due burst's words committed (spec §16.3 step 4). The
    `message_ids` still due in `thread_id` take the `bubbles` in order, one
    each and the last message the rest, with `voiced: True` (or `"fallback"`
    for an engine-written line). With fewer bubbles than messages the later
    messages are WITHDRAWN (`voiced: "withdrawn"`), never voiced with no
    words. A `caption` goes on the message's media row when it has one (T19
    reads it), else on the message. A "New message" notification of theirs
    takes the words as its preview.

    `op: withdraw`: the messages are retired unvoiced (their person left):
    `voiced: "withdrawn"`, no words, their "New message" notifications
    dropped, the thread's unread recounted. Bumps `rev` either way.
    """
    if not state.social:
        return {"type": "social_voiced", "ok": False, "text": "no social slice"}
    tid = str(effect.get("thread_id") or "")
    t = (state.social.get("threads") or {}).get(tid)
    if t is None:
        return {"type": "social_voiced", "ok": False, "text": f"no thread {tid}"}
    ids = [str(x) for x in effect.get("message_ids") or ()]
    rows = [m for m in t.get("messages") or [] if str(m["id"]) in ids and m.get("voiced") is False]
    if not rows:
        return {"type": "social_voiced", "ok": False, "text": f"nothing due of {ids} in {tid}"}
    if effect.get("op") == "withdraw":
        _retire(state, t, rows)
        relationships.touch(state.social.setdefault("people", {}).setdefault(str(t["pid"]), {}))
        return {"type": "social_voiced", "ok": True, "text": f"{len(rows)} message(s) withdrawn in {tid}",
                "message_ids": [m["id"] for m in rows], "withdrawn": True}
    bubbles = [str(b) for b in effect.get("bubbles") or () if str(b).strip()]
    if not bubbles:
        return {"type": "social_voiced", "ok": False, "text": "no words"}
    fallback = bool(effect.get("fallback"))
    spoken, extra = rows[:len(bubbles)], rows[len(bubbles):]
    n = len(spoken)
    for i, m in enumerate(spoken):
        m["bubbles"] = bubbles[i:i + 1] if i < n - 1 else bubbles[n - 1:]
        m["voiced"] = "fallback" if fallback else True
    if extra:
        _retire(state, t, extra)                     # more messages than bubbles: the rest never voiced wordless
    caption = str(effect.get("caption") or "")
    if caption:
        for m in spoken:
            if not (m.get("decision") or {}).get("media_kind"):
                continue
            media = (state.social.get("media") or {}).get(str(m.get("media_id") or ""))
            if media is not None:
                media["caption"] = caption
            else:
                m["caption"] = caption
    at_words = {float(m["at"]): m["bubbles"][0] for m in spoken if m["bubbles"]}
    for row in state.social.get("notifications") or []:
        if row.get("thread_id") == tid and row.get("preview") == messaging.NEW_MESSAGE \
                and float(row.get("at", -1)) in at_words:
            row["preview"] = at_words[float(row["at"])][:messaging.PREVIEW_CHARS]
    relationships.touch(state.social.setdefault("people", {}).setdefault(str(t["pid"]), {}))
    return {"type": "social_voiced", "ok": True, "text": f"{n} message(s) voiced in {tid}",
            "message_ids": [m["id"] for m in spoken], "withdrawn_ids": [m["id"] for m in extra],
            "fallback": fallback}


def _retire(state: GameState, t: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    """Rows withdrawn (inside `social_voiced` only): no words, their "New message" notifications gone."""
    times = set()
    for m in rows:
        m["voiced"] = messaging.WITHDRAWN
        m["bubbles"] = []
        times.add(float(m["at"]))
    tid = t["thread_id"]
    notes = state.social.get("notifications") or []
    keep = [n for n in notes if not (n.get("thread_id") == tid and n.get("preview") == messaging.NEW_MESSAGE
                                     and float(n.get("at", -1)) in times)]
    if len(keep) != len(notes):
        state.social["notifications"] = keep
    messaging.recount(t)


__all__ = [
    "OUTCOMES", "VoicePass", "VoicingScheduler", "cancel_all", "cancel_unwatched", "commit", "drain_inbox",
    "emit", "forget", "get_scheduler", "in_flight", "pending", "request", "request_if_due", "reset", "run_pass",
    "run_until_quiet", "set_emitter", "set_llm_fn", "set_summary_fn", "snapshot",
]
