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
2. **The turnstile, per call** (v0.23.0 T8, spec §20.1 N1/N3): steps 3-6
   run ONE MODEL CALL AT A TIME, each holding the session's narration
   turnstile (`engine/social/turnstile.py`), which the pass only TRIES
   (`try_acquire_voice`), holding nothing, before the turn lock (the
   declared order). Busy -- a world turn waits for it or holds it -- the
   pass answers `deferred`: not an attempt, nothing marked for that call,
   re-queued on the `commit_retry_ms` schedule. Between two people's calls
   the turnstile is free, so a waiting world turn waits at most one call.
   Up to `social.voice.max_per_pass` calls a pass; more left: `rerun`.
3. **Admission** (hosted only), per call, holding the turnstile and no lock,
   BEFORE anything is marked: `admit_turn(label="voice", account=<owner>,
   deadline_seconds=hosting.turn_deadline_seconds, cancel=pass.cancel)` with
   a SHORT wait, `social.voice.admit_wait_seconds`. Busy: the pass answers
   `busy`, nothing marked, and the scheduler re-queues it with backoff (2,
   4, 8, 16, 32 s); after `social.voice.max_attempts` it is DROPPED (the
   next action or resume requests again), bar an OPEN episode's due reply,
   committed at once as its templated fallback (`commit_open_fallbacks`,
   §20.1; the same at the pass's deadline). Before admission the inbox is
   drained under the tried lock: applying a parked reply or media result
   calls no model, so a call that finds nothing else due asks no ticket
   (final review I1; the media hand-off requests a pass when it parks). The
   voice call then runs INSIDE that ticket (`gate.inference_slot` shares an
   admitted context's narration lane), so one account's phone holds at most
   one narration ticket at a time.
4. **The snapshot**, per call, under the turn lock (tried, never waited for,
   on the `social.voice.commit_retry_ms` schedule): the inbox drained, then
   the ONE person to voice read by §11.1's priority (thread focus, then
   warmth, then age), one thread (`snapshot(limit=1)`), and MARKED in
   `session.voicing` (message id -> pass id) -- in memory, never in state,
   never in a save. The people left beyond it are counted (`p.more`).
5. **The call**, holding the turnstile and no lock (`voicing.voice`, pure
   over the snapshot); `session.typing` names the thread while its call is
   in flight. Past the pass's deadline
   (`social.voice.pass_deadline_seconds`, hosted also
   `hosting.turn_deadline_seconds`) a fallback line instead.
6. **The commit** of the reply as it lands (`commit`, §16.3), still holding
   the turnstile: liveness;
   still wanted (the message due, marked by THIS pass, the person not
   unmatched, blocked or ended, the thread there); the state-dependent
   re-checks (proposals legal NOW, `agreement.STATE_CHECKS` against the live
   view, a newly failing bubble or fact dropped, none left: the fallback);
   then ONE transaction through `apply_effect` (`social_voiced`, the regard,
   the memory, each proposal), its rollback snapshot SCOPED to what a commit
   can write (`ScopedTransaction`: the person's own rows deep, every other
   row by reference), never the whole state (v0.22.0 T26). The pass's
   last commit (its last call, or none left due) saves under its own lock;
   any other marks the session dirty. Pushed as `phone_message`
   through the room-checked emitter. A commit that cannot take the lock
   parks the reply in the session's inbox (`engine/social/inbox.py`), its
   messages still marked, for the next holder to apply. Then the turnstile
   is released.
7. **The recap** (v0.23.0 T6, spec §7.2), under the turnstile too: at most one memory job -- a closed
   episode's recap, or the fold of a person's oldest recap into their story
   -- its view read under the tried lock (`memory.job_view`), the archive
   read and the text written holding no lock (`memory.with_archive`,
   `memory.write_job`: one utility call through the one-argument
   `SummaryFn`), then committed under the lock (`memory.commit_job`, refused
   as stale when its `recap_due` row or the story moved) inside the person's
   scoped transaction. A pass with nothing to voice but a recap due runs it
   without asking a narration ticket.
8. **Finish**: this pass's marks cleared (bar those parked in the inbox).

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
from engine.social import agreement, apps, archive, memory, messaging, relationships, saves, turnstile, voicing
from engine.social.kinds import Decision, collecting, decision_from_row, recorded

logger = logging.getLogger(__name__)

#: A pass's outcomes (`run_pass`).
OUTCOMES: tuple[str, ...] = ("ok", "busy", "dropped", "discarded", "fallback", "cancelled", "deferred")

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
    #: threads it voiced (their people's recaps go first), and the messages
    #: whose reply it parked in the inbox (their marks are kept for the drain).
    started: float = 0.0
    revs: dict[str, Any] = field(default_factory=dict)
    threads: list[str] = field(default_factory=list)
    parked: set[str] = field(default_factory=set)
    #: Each commit's status in this run (`ok`, `fallback`, `discarded`): the pass's ONE metric is read off them.
    statuses: list[str] = field(default_factory=list)
    #: v0.23.0 T8 (spec §20.1 N3): how many times the pass found the session's narration turnstile
    #: busy (`deferred`: never an attempt), and the due people its last snapshot left beyond the one
    #: it took (`snapshot(limit=1)`: whether this call's commit is the pass's last).
    deferrals: int = 0
    more: int = 0
    #: v0.23.0 T11: whether the pass is waiting out a deferral's backoff in the timed queue, which a
    #: world turn's `request(now=True)` brings forward (spec §20.1 step 6).
    deferred_wait: bool = False
    #: The people this run of the pass has snapped (one thread each per pass, §11.1, as v0.22's one
    #: snapshot took them): a per-call snapshot passes over them, their next due messages wait a pass.
    voiced_people: set[str] = field(default_factory=set)

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
#: The ONE-argument summary function, the recap's (None: `memory.production_summary_fn()`, pre-flight F10).
_summary_fn: Optional[memory.SummaryFn] = None
#: `(session_id, event, payload) -> None`: the room-checked background push (`FlaskScene.emit_to_session`).
_emitter: Optional[Callable[[str, str, dict[str, Any]], None]] = None


def set_llm_fn(fn: Optional[voicing.LLMFn]) -> None:
    global _llm_fn
    _llm_fn = fn


def set_summary_fn(fn: Optional[memory.SummaryFn]) -> None:
    """The recap's model function (`RecapFn`, the v0.22 `SummaryFn`): ONE argument, the messages (F10)."""
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
    from engine.social import presence

    view = presence.here_view(state)
    for m in messaging.unvoiced(state):
        if m["id"] in marked or m.get("from") == "player" or m.get("from") == "system":
            continue
        if messaging.held(state, str(m.get("from")), view):
            continue           # with the player (a scene, a plan, or here by chance: W9): it waits, unvoiced (W5)
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
    """Whether a pass would find anything to do in ``session`` -- a due message to voice, or a recap
    (v0.23.0 T6) -- (CALLER HOLDS its lock, or owns its thread)."""
    state = session.engine.state
    return bool(_voiceable(state, session)) or memory.recap_pending(state)


def snapshot(session: Any, p: VoicePass, *, limit: Optional[int] = None) -> list[voicing.PersonSnapshot]:
    """
    The people this pass voices (CALLER HOLDS the turn lock): §11.1's
    priority -- the thread's `focus` desc, then the person's warmth desc, then
    the oldest due message first -- at most ``limit`` PEOPLE (None:
    `social.voice.max_per_pass`), one thread each; each a
    `voicing.snapshot_of` (deep copies) of only the due messages no live pass
    has marked. Then those messages are MARKED for ``p`` in `session.voicing`.
    The due people left beyond the limit are counted on ``p.more``; with no
    ``limit`` they also set ``p.rerun``. ``limit=1`` is the per-call snapshot
    (v0.23.0 T8: the pass takes one person per turnstile hold, and decides
    its own rerun at its end); it passes over the people an earlier call of
    the same pass took (``p.voiced_people``), setting ``p.rerun``, so a pass
    still voices one thread per person, as v0.22's single snapshot did.
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

    per_call = limit is not None
    limit = max(1, int(limit if per_call else social.setting("voice.max_per_pass", 3)))
    taken_people: set[str] = set()
    left_over: set[str] = set()
    snaps: list[voicing.PersonSnapshot] = []
    p.more = 0
    for tid in sorted(by_thread, key=priority):
        pid = str(threads[tid]["pid"])
        earlier = per_call and pid in p.voiced_people      # voiced by an earlier call of this pass
        if pid in taken_people or len(snaps) >= limit or earlier:
            if pid not in taken_people and not earlier:
                left_over.add(pid)                 # one voiced earlier waits for the next pass: not "more"
            if not per_call or pid in taken_people or earlier:
                p.rerun = True                     # one thread per person per pass (§11.1): the rest next pass
            continue
        snap = voicing.snapshot_of(state, tid, _save_dir(session))
        if snap is None:
            continue
        ids = {m["id"] for m in by_thread[tid]}
        due = [m for m in snap.due if m.get("id") in ids]
        if not due:
            continue
        snaps.append(dataclasses.replace(snap, due=due))
        taken_people.add(pid)
        p.voiced_people.add(pid)
        p.revs[pid] = (people.get(pid) or {}).get("rev")
        if tid not in p.threads:
            p.threads.append(tid)
        for m in due:
            session.voicing[str(m["id"])] = p.id
    p.more = len(left_over - taken_people)
    return snaps


def _clear_marks(session: Any, p: VoicePass) -> None:
    """This pass's marks dropped (bar those parked in the inbox): read from a copy (F22)."""
    for mid, owner in tuple(session.voicing.items()):
        if owner == p.id and mid not in p.parked:
            session.voicing.pop(mid, None)


# -- the commit (§16.3) ---------------------------------------------------------------------------


#: The maps of rows in ``state.social`` whose rows name their person by ``pid``:
#: a commit's rollback copies that person's rows of each deep (``ScopedTransaction``).
PERSON_ROW_MAPS: tuple[str, ...] = ("threads", "requests", "media", "games", "promises", "plans")


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
    """The message row's stored decision; an unknown mode or end is clamped, with a log line (T3)."""
    return decision_from_row(row.get("decision"), where=f"voicer:{row.get('id', '')}")


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
                              epoch=p.epoch, store=store, p=p)
        p.statuses.append(status)
        return "committed" if status in ("ok", "fallback") else "discarded"
    finally:
        _release(session)


def _apply_reply(session: Any, pass_id: str, reply: voicing.VoicedReply, *, last: bool = False,
                 snap_rev: Any = None, epoch: Optional[int] = None, store: Any = None,
                 p: Optional[VoicePass] = None) -> str:
    """
    §16.3 steps 2-5, under the turn lock, shared by `commit` and the inbox
    drain: ``ok`` or ``fallback`` (committed) or ``discarded``. With
    ``epoch``, liveness is asked once more just before a save (a local
    resume takes no old lock: finding 7's window, narrowed, not closed).

    Inside the transaction, after the reply's own writes: if the player
    spoke after the snapshot (``reply.through_id``), the NEXT decision is
    queued at once (`convo.after_commit`, v0.23.0 I6) and ``p.rerun`` set, so
    no send made while the model wrote is ever left unanswered. From the
    inbox drain (no pass) the action's own pass request voices it.
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
    raised = reply.followup_raised
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
            raised = fb.followup_raised
    # 4. Apply, in one transaction (rule 3: every write an effect).
    with collecting() as applied:
        with scoped_transaction(state, reply.pid) as tx:
            done = apply_effect(state, {"type": "social_voiced", "thread_id": reply.thread_id,
                                        "message_ids": [m["id"] for m in wanted], "bubbles": lists["bubbles"],
                                        "caption": caption, "fallback": fallback, "followup_raised": raised})
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
                _apply_extras(state, reply, _decision_of(wanted[0]), legal)
            if not recap:
                from engine.social import convo   # lazily: convo imports messaging, as this module does

                if convo.after_commit(state, reply.pid, reply.thread_id, reply.through_id, state.world_clock_hours):
                    if p is not None:
                        p.rerun = True
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
    a job's result (`media.apply_and_push`, T19); an `open_fallback` item a
    dropped or overdue pass's open-episode fallbacks (`commit_open_fallbacks`,
    v0.23.0 T8). Returns how many were applied.
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
        if kind == "open_fallback":
            # A dropped or overdue pass's open-episode fallbacks, parked by a busy lock (§20.1).
            try:
                applied += _open_fallbacks(session, str(item.get("why") or "attempts"))
            except Exception as exc:  # noqa: BLE001 -- one item's fault costs that item, never the player's action
                logger.warning("[social] Inbox fallbacks failed, dropped (operation=drain_inbox): %s", exc)
            continue
        logger.info("[social] Inbox item dropped: no handler (operation=drain_inbox, kind=%s)", kind)
    return applied


_drain_inbox = drain_inbox


# -- the recap (v0.23.0 §7.2) -----------------------------------------------------------------------


def _recap_one(session: Any, p: VoicePass, *, store: Any = None) -> bool:
    """
    At most one memory job (spec §7.2; it replaces v0.22's thread summary):
    a closed episode's recap, or first, when that person's `episodes` are
    full, the fold of their oldest recap into the story. Its view is read
    under the tried lock (`memory.job_view`: the people this pass voiced
    first, then the oldest closed), the archive read and the text written
    holding NO lock (`memory.with_archive`, `memory.write_job`: ONE utility
    call through the one-argument summary function, its deterministic
    fallback on no model), then committed under the lock after the
    generation check, inside the person's scoped transaction
    (`memory.commit_job`: refused as stale when its `recap_due` row or the
    story moved meanwhile; the next pass takes the next job).
    """
    if p.cancel.cancelled or not saves.alive(session, p.epoch, store):
        return False
    if not _try_lock(session, p.cancel):
        return False
    try:
        if not saves.alive(session, p.epoch, store):
            return False
        state = session.engine.state
        threads = (state.social or {}).get("threads") or {}
        prefer = tuple(dict.fromkeys(str(threads[t]["pid"]) for t in p.threads if t in threads))
        view = memory.job_view(state, prefer)
    finally:
        _release(session)
    if view is None:
        return False
    directory = archive.save_dir(session)
    view = memory.job_with_archive(view, directory)   # a recap's older messages, a restore's shelves
    fn = _summary_fn or memory.production_summary_fn()
    text, _by_model = memory.write_job(view, fn)
    if p.cancel.cancelled or not _try_lock(session, p.cancel):
        return False
    try:
        if not saves.alive(session, p.epoch, store):
            return False
        state = session.engine.state
        record = memory.job_record(view)
        if record is not None and directory is not None and not archive.append(directory, [record], kind="recap"):
            logger.warning("[social] A fold's record did not reach the archive (operation=_recap_one, pid=%s)",
                           view["pid"])
        with scoped_transaction(state, str(view["pid"])) as tx:
            result = memory.commit_job(state, view, text)
            tx.commit()
        if result.get("ok"):
            saves.mark_dirty(session, "recap")
        else:
            logger.info("[social] Recap refused at commit (operation=_recap_one, pid=%s): %s",
                        view["pid"], result.get("text"))
        return bool(result.get("ok"))
    finally:
        _release(session)


# -- the pass ---------------------------------------------------------------------------------------


def run_pass(p: VoicePass, *, llm_fn: Optional[voicing.LLMFn], admit: bool, store: Any = None) -> str:
    """
    One pass, ONE MODEL CALL AT A TIME under the session's narration turnstile (§20.1): for each
    person's reply (and then one recap), try the turnstile; busy -> `deferred` (nothing marked for
    that call; not an attempt). Holding it: admission (hosted), the tried snapshot of ONE person,
    the call, the tried commit, then release. A waiting world turn takes it between two calls.
    """
    session = p.session
    # THE GENERATION CHECK, first of four (before admission, snapshot, each commit).
    if p.cancel.cancelled or not saves.alive(session, p.epoch, store):
        return "cancelled"
    gate = turnstile.of(session)
    p.started = time.monotonic()
    p.deadline = p.started + _deadline_seconds()
    p.statuses = []
    p.voiced_people = set()
    limit = max(1, int(social.setting("voice.max_per_pass", 3)))
    try:
        calls = 0
        for i in range(limit):
            if p.cancel.cancelled or not saves.alive(session, p.epoch, store):
                return "cancelled"
            if not gate.try_acquire_voice():
                return _deferred(p)
            p.deferrals = 0                                # a call proceeds: the next deferral starts afresh
            try:
                step = _one_call(p, llm_fn=llm_fn, admit=admit, store=store, final=(i == limit - 1))
            finally:
                gate.release(turnstile.VOICE)
                turnstile.report_share(session)
            if step == "busy" and p.statuses:
                # Busy after this pass committed (admission is per call): its commits are reported, and
                # the scheduler does not count the busy as a failed attempt (`_after`).
                _report_pass(session, _outcome(p.statuses), _elapsed_ms(p))
            if step in ("cancelled", "busy"):
                return step
            if step == "ended":
                return "cancelled"
            if step == "empty":
                break
            calls += 1
        recapped = False
        took = gate.try_acquire_voice()
        if took:
            try:
                recapped = _recap_one(session, p, store=store)   # at most one utility call, under the turnstile too
            finally:
                gate.release(turnstile.VOICE)
                turnstile.report_share(session)
        if time.monotonic() >= p.deadline:
            # Past the deadline: no OPEN episode's due reply is left silent (§20.1, §13.1) -- also when
            # the recap step deferred (the fallbacks call no model and take no turnstile).
            commit_open_fallbacks(session, epoch=p.epoch, cancel=p.cancel, store=store, why="deadline")
        if not took:
            return _deferred(p)
        if (calls == limit or recapped) and _more_due(session):
            p.rerun = True                                 # more left than one pass takes: the scheduler reruns
        outcome = _outcome(p.statuses)
        if p.statuses:
            _report_pass(session, outcome, _elapsed_ms(p))   # ONE voice_pass metric per pass that committed
        return outcome
    finally:
        _clear_marks(session, p)


def _deferred(p: VoicePass) -> str:
    """The turnstile was busy (a world turn waits or holds it, §20.1 N3): not an attempt."""
    if p.statuses:
        _report_pass(p.session, _outcome(p.statuses), _elapsed_ms(p))
    return "deferred"


def _more_due(session: Any) -> bool:
    """Whether anything is still due (`pending`), read under the TRIED turn lock; a busy lock answers
    False (whoever holds it requests a pass after their action)."""
    if not session.lock.acquire(blocking=False):
        return False
    try:
        return pending(session)
    finally:
        _release(session)


def _due_beyond(session: Any, p: VoicePass) -> bool:
    """Whether anything is due to voice for someone this pass has not voiced yet (CALLER HOLDS the
    lock): a call that would snapshot nobody asks no ticket (review M3)."""
    state = session.engine.state
    threads = (state.social or {}).get("threads") or {}
    for m in _voiceable(state, session):
        pid = str((threads.get(m["thread_id"]) or {}).get("pid") or "") if m.get("from") == "system"             else str(m.get("from"))
        if pid not in p.voiced_people:
            return True
    return False


def _more_due_unlocked(session: Any, p: VoicePass) -> bool:
    """The last per-call snapshot's own count of due people beyond the one it took (``p.more``)."""
    return p.more > 0


def _one_call(p: VoicePass, *, llm_fn: Optional[voicing.LLMFn], admit: bool, store: Any,
              final: bool = False) -> str:
    """
    One person's reply, HOLDING THE TURNSTILE: `voiced`, `empty`, `busy`, `cancelled` or `ended`.
    ``final``: the pass's last call, so its commit saves (§17.2) whether or not more are due.
    """
    session = p.session
    admission = None
    try:
        if admit:
            from engine.llm.gate import InferenceBusy, admit_turn

            # Nothing due to voice: no narration ticket asked for at all. What is parked in the
            # inbox is drained HERE, before admission: applying it calls no model (final review
            # I1). Tried on the commit_retry_ms schedule; a lock still busy is no answer, so it admits.
            if _try_lock(session, p.cancel):
                try:
                    if not saves.alive(session, p.epoch, store):
                        return "cancelled"
                    _drain_inbox(session)              # each item re-validated (§16.4)
                    due = _due_beyond(session, p)          # not the people this pass already voiced
                finally:
                    _release(session)
                if not due:
                    return "empty"                     # a recap waiting is a utility call: no ticket
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
                logger.info("[social] Voicing call not admitted (operation=run_pass, pass=%s, reason=%s)",
                            p.id, getattr(exc, "reason", ""))
                return "cancelled" if p.cancel.cancelled else "busy"   # nothing marked for this call
        if p.cancel.cancelled or not saves.alive(session, p.epoch, store):
            return "cancelled"
        if not _try_lock(session, p.cancel):
            return "cancelled" if p.cancel.cancelled else "busy"
        try:
            if not saves.alive(session, p.epoch, store):
                return "cancelled"
            _drain_inbox(session)                      # each item re-validated (§16.4)
            snaps = snapshot(session, p, limit=1)      # READ, then MARK, one person
        finally:
            _release(session)
        if not snaps:
            return "empty"
        snap = snaps[0]
        if p.cancel.cancelled or not saves.alive(session, p.epoch, store):
            return "cancelled"
        if time.monotonic() >= p.deadline:
            reply = voicing.fallback_reply(snap, "deadline")
        else:
            session.typing.add(snap.thread_id)         # read by every payload built meanwhile (§9.4)
            try:
                reply = voicing.voice(snap, llm_fn)
            finally:
                session.typing.discard(snap.thread_id)
        if p.cancel.cancelled:
            return "cancelled"                         # an answer that came back after cancel is discarded
        result = commit(session, p, reply, store=store, last=final or not _more_due_unlocked(session, p))
        return "ended" if result == "ended" else "voiced"
    finally:
        if admission is not None:
            admission.release()


# -- the open-episode fallback (§20.1's last bullet) ---------------------------------------------------


#: Each open-episode fallback batch's pass id ("f1", "f2", ...): its messages are marked under it.
_FALLBACK_IDS = itertools.count(1)


def commit_open_fallbacks(session: Any, *, epoch: Optional[int] = None, cancel: Optional[CancelToken] = None,
                          store: Any = None, why: str = "attempts") -> int:
    """
    No OPEN episode left silent (spec §20.1, §13.1): when a pass is DROPPED
    after `social.voice.max_attempts` or reaches its deadline, every due
    reply-family message whose person has an open chat episode is committed
    as the templated fallback (`voicing.fallback_reply_for`, through
    `_apply_reply`). Run HOLDING NOTHING (the dropping thread, or the pass's
    own after its last call); the turn lock is tried on the commit_retry_ms
    schedule, and a lock still busy parks the job in the session's inbox
    (`{kind: open_fallback}`) for the lock's next holder. Returns how many
    replies it committed.
    """
    epoch = session.epoch if epoch is None else epoch
    cancel = cancel or CancelToken()
    if cancel.cancelled or not saves.alive(session, epoch, store):
        return 0
    if not _try_lock(session, cancel):
        if cancel.cancelled or not saves.alive(session, epoch, store):
            return 0
        session.inbox.put({"kind": "open_fallback", "epoch": epoch, "account": session.owner, "why": why})
        logger.info("[social] Open-episode fallbacks parked in the inbox (operation=commit_open_fallbacks, id=%s)",
                    session.session_id)
        return 0
    try:
        if not saves.alive(session, epoch, store):
            return 0
        return _open_fallbacks(session, why)
    finally:
        _release(session)


def _open_fallbacks(session: Any, why: str) -> int:
    """`commit_open_fallbacks`' work (CALLER HOLDS the turn lock): the due reply-family messages no live
    pass has marked, of people with an open chat episode, each thread's committed as one fallback."""
    from engine.social import convo   # lazily: convo imports messaging, as this module does

    state = session.engine.state
    threads = (state.social or {}).get("threads") or {}
    by_thread: dict[str, list[dict[str, Any]]] = {}
    for m in _voiceable(state, session):
        if m.get("from") == "system" or (m.get("decision") or {}).get("situation") not in convo._REPLY_SITUATIONS:
            continue
        by_thread.setdefault(str(m["thread_id"]), []).append(m)
    done = 0
    for tid, rows in by_thread.items():
        t = threads.get(tid) or {}
        pid = str(t.get("pid") or "")
        ep = convo.episode(state, pid)
        if ep is None or ep.get("kind", "chat") != "chat":
            continue
        try:
            reply = voicing.fallback_reply_for(state, pid, tid, rows, why)
        except ValueError as exc:
            logger.info("[social] No open-episode fallback (operation=_open_fallbacks, pid=%s): %s", pid, exc)
            continue
        pass_id = f"f{next(_FALLBACK_IDS)}"
        for m in rows:
            session.voicing[str(m["id"])] = pass_id
        try:
            status = _apply_reply(session, pass_id, reply)
        finally:
            for m in rows:
                if session.voicing.get(str(m["id"])) == pass_id:
                    session.voicing.pop(str(m["id"]), None)
        done += status in ("ok", "fallback")
    if done:
        logger.info("[social] Open episodes answered by their fallback (operation=_open_fallbacks, why=%s, count=%d)",
                    why, done)
    return done


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
        if outcome in ("cancelled", "busy", "deferred"):
            break                                      # a held turnstile defers at once (pre-flight F17)
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

    def request(self, session: Any, *, now: bool = False) -> None:
        """A pass for ``session`` (idempotent): queued, or ``rerun`` set on the one in flight. ``now``
        (a world turn that has just released the turnstile, spec §20.1 step 6): a pass waiting out a
        DEFERRAL's backoff is brought forward to run at once; a busy admission's backoff is kept."""
        key = (str(session.session_id), int(session.epoch))
        limit = max(1, int(self._queue_max or social.setting("voice.queue_max", 64)))   # read before the leaf
        dropped: Optional[VoicePass] = None
        with self._lock:
            if self._paused or self._stopped:
                return
            if key in self._queued:
                waiting = self._queued[key]
                if now and waiting.deferred_wait:
                    self._timed = [row for row in self._timed if row[2] is not waiting]
                    heapq.heapify(self._timed)
                    waiting.deferred_wait = False
                    self._ready.append(waiting)
                    self._wake.set()
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
                p.deferred_wait = False
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
        live = (outcome in ("ok", "fallback", "discarded", "busy", "deferred") and not p.cancel.cancelled
                and session_alive)
        limit = max(1, int(social.setting("voice.max_attempts", 6)))      # read before the leaf
        retry_ms = _retry_ms() or [0]                                       # read before the leaf
        progressed = bool(p.statuses)                                       # this run committed something
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
            if outcome == "deferred":
                # Not an attempt (§20.1 N3): re-queued on the commit_retry_ms schedule; the world turn's own
                # request (after its turn) re-queues it sooner. No scheduler thread ever waits on a turnstile.
                p.deferrals = getattr(p, "deferrals", 0) + 1
                delay_ms = retry_ms[min(p.deferrals, len(retry_ms)) - 1]
                self._queued[p.key] = p
                p.deferred_wait = True                     # `request(now=True)` may bring it forward
                heapq.heappush(self._timed, (self._time() + delay_ms / 1000.0, next(self._seq), p))
                self._wake.set()
                return
            if outcome == "busy" and progressed:
                # Busy after a commit of this run (admission is per call): progress, not a failed
                # attempt -- re-queued on the first backoff step, its commits already reported.
                p.attempts = 0
                self._queued[p.key] = p
                heapq.heappush(self._timed, (self._time() + 2.0, next(self._seq), p))
            elif outcome == "busy":
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
        if outcome == "busy" and not progressed:
            _report_pass(p.session, "dropped" if dropped else "busy", _elapsed_ms(p))
        if dropped:
            logger.info("[social] Voicing pass dropped after %d busy attempts (operation=_after, id=%s); "
                        "its messages stay due", p.attempts, p.session.session_id)
            # ...bar an OPEN episode's reply, which is never left silent (§20.1): its templated fallback,
            # committed here on the dropping thread holding nothing (the turn lock tried, else parked).
            try:
                commit_open_fallbacks(p.session, epoch=p.epoch, cancel=p.cancel)
            except Exception as exc:  # noqa: BLE001 -- the worker outlives one fallback's fault
                logger.warning("[social] Open-episode fallbacks failed (operation=_after, id=%s): %s",
                               p.session.session_id, exc)
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


def request(session: Any, *, now: bool = False) -> None:
    """A voicing pass for ``session``; ``now`` brings forward one waiting out a deferral (a world turn's
    step 6, spec §20.1)."""
    get_scheduler().request(session, now=now)


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
    takes the words as its preview. The follow-up a message's decision
    carries is closed only when `followup_raised` names it (the words raised
    it, v0.23.0 T7).

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
    from engine.social import promises   # lazily: promises imports messaging, as this module does

    if effect.get("op") == "withdraw":
        _retire(state, t, rows)
        promises.on_voiced(state, [m["id"] for m in rows], withdrawn=True)    # never written: void (review M2)
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
    promises.on_voiced(state, [m["id"] for m in rows])   # they wrote in this commit: a promise kept (review M2)
    pid = str(t["pid"])
    raised = str(effect.get("followup_raised") or "")
    for m in spoken:
        if m.get("from") == pid:
            memory.note_spoken(state, pid, m)        # the person's memory, whatever the app (v0.23.0 §7.1)
        followup = str((m.get("decision") or {}).get("followup_id") or "")
        # Closed only when the words raised it (T6 review M3; v0.23.0 T7): a reply that did not ask leaves
        # it open, and the next decision carries it again.
        if followup and followup == raised and any(str(r.get("id")) == followup for r in memory.part(
                (state.social.get("people") or {}).get(pid) or {}, "open")):
            memory.close_open(state, pid, followup)  # asked how it went: the follow-up is done (§7.3)
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


def _apply_extras(state: GameState, reply: voicing.VoicedReply, decision: Any, legal: tuple[str, ...]) -> None:
    """
    A model reply's own keys beside its proposals (v0.23.0 T7), each re-checked against the state NOW
    (rule 1; inside the commit's transaction): its `promise` (spec §5.2 route 3) while the proposal is
    legal and the decision made none, else -- or a window its words promise (`stated_promise`, fix round
    1, review I1) -- adopted through `relationships.adopt_promise`; its `followups` (§7.3, `relationships.apply_followups`, held to
    the proposal row); and the layer it opened up about (§6.4: `growth`'s `reveal` op) only while that
    layer is still the one due.
    """
    from engine.social import growth   # lazily: growth reads population, which this module's package loads

    if reply.promise and relationships.PROMISE_PROPOSAL in legal and not decision.promise_id:
        relationships.apply_proposal(state, reply.pid, relationships.PROMISE_PROPOSAL, args=dict(reply.promise))
    elif not decision.promise_id and (reply.promise or reply.stated_promise):
        # Said in the words (or by key outside a winding conversation): adopted, re-checked (review I1).
        window = str((reply.promise or {}).get("window") or reply.stated_promise)
        relationships.adopt_promise(state, reply.pid, window, about=str((reply.promise or {}).get("about") or ""))
    if reply.followups:
        relationships.apply_followups(state, reply.pid, [dict(f) for f in reply.followups])
    if reply.reveal and growth.record(state, reply.pid).get("reveal_due") == reply.reveal:
        apply_effect(state, {"type": "social_growth", "op": "reveal", "pid": reply.pid, "layer": reply.reveal})


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


def _save_dir(session: Any) -> Any:
    """The run's save directory for the snapshot's archive read (None when it has none or the id is refused)."""
    try:
        return archive.save_dir(session)
    except ValueError:
        return None
