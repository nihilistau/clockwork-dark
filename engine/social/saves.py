"""
When the phone saves (v0.22.0 spec §16.5, §17.2).

Every phone save goes through ONE path, `save_now`, which the caller makes
holding the session's turn lock, and which makes exactly the two checks a
turn's save and `SessionStore.owner_write` make: nothing for an ENDING
session (an admin ended its account; checked FIRST, since the archive spill
writes before `_autosave` could refuse, and a purged folder must never be
re-created), and, hosted, nothing for an account `owner_open` says is
closed. Then the archive spill (`archive.spill`, Plan decision 18) and
`default_state._autosave`.

A phone save happens:

- at once, inside the mechanics action, after a match, a stage change, an
  ending or an away advance (`IMMEDIATE`; `turn.run_mechanics` step 4);
- otherwise by **the dirty timer**, `DirtySaver`: `mark_dirty` schedules the
  session `social.autosave_seconds` out; when due it checks liveness
  (`alive`), tries the turn lock non-blocking (busy: again in 1 s), saves if
  still dirty, and lets the lock go through `release_turn`;
- on take (`flush_taken`: the idle sweep and hosted one-run-per-account,
  holding the taken run's lock for good) and on shutdown (`flush_all`:
  local at exit, hosted after a drain).

A harness save store that keeps nothing (`keeps_nothing = True`) schedules
no timer and writes nothing (Plan decision 28).

Liveness (`alive`, spec §16.2): the session is its OWN store's live run under
its id, of the same build (`epoch`), and not ending.
"""

from __future__ import annotations

import atexit
import heapq
import itertools
import logging
import threading
import time
from typing import Any, Callable, Optional

from engine import social
from engine.locks import renew_after_fork
from engine.session.store import release_turn  # re-exported: the one release (Plan decision 31)
from engine.social import archive

logger = logging.getLogger(__name__)

#: Save reasons that save inside the action (spec §16.1 step 4), carried as
#: `save_reason` by the result of the effect that makes them.
IMMEDIATE = frozenset({"match", "stage", "ended", "away"})


def _default_store() -> Any:
    from engine.scenes.default_scene import get_store

    return get_store()


def alive(session: Any, epoch: int, store: Any = None) -> bool:
    """
    The generation check (spec §16.2), against the explicit store, else the
    session's OWN store (Plan decision 28), else the process's: this object
    is the live run under its id, of build `epoch`, and not ending.
    """
    store = store or getattr(session, "store", None) or _default_store()
    if getattr(session, "ending", False) or getattr(session, "epoch", None) != epoch:
        return False
    is_live = getattr(store, "is_live", None)
    if is_live is not None:
        return bool(is_live(session))
    return store.get(session.session_id, session.owner) is session


def keeps_nothing(session: Any) -> bool:
    """A harness save store (`keeps_nothing = True`, T15): no timer, no write, no thread."""
    return bool(getattr(getattr(session, "saves", None), "keeps_nothing", False))


def save_now(session: Any, *, entry: Optional[dict[str, Any]] = None) -> bool:
    """
    Save one phone session. CALLER HOLDS session.lock. True when written;
    False, writing nothing, for an ending session, a keeps-nothing store or a
    closed account. `entry` is the transcript line (a mechanics action's);
    with none, no line is written (a timer's or a flush's save).
    """
    from engine.scenes.default_state import _autosave

    if getattr(session, "ending", False):
        # _autosave refuses an ending session too, but the archive spill below runs BEFORE it and
        # would re-create a purged save folder (R22): refuse here, first.
        logger.info("[social] Not saved: the session is ending (operation=save_now, id=%s)", session.session_id)
        return False
    if keeps_nothing(session):
        session.dirty = False                      # a harness store: nothing to write (Plan decision 28)
        return False
    if entry is None:
        # A transcript line whose save failed (the away advance's): this retry writes it (T16 review M4).
        entry = getattr(session, "pending_entry", None)
    store = getattr(session, "store", None) or _default_store()
    owner_open = getattr(store, "owner_open", None)
    if session.owner and owner_open is not None and not owner_open(session.owner):
        logger.info("[social] Not saved: the account is closed (operation=save_now, id=%s)", session.session_id)
        return False
    compact(session)                               # Plan decision 18: before the envelope is replaced
    # Cleared BEFORE the write (the lock is held, so no action can dirty it
    # meanwhile): a reader that sees the new save sees a clean session.
    session.dirty = False
    if not _autosave(session, "", "", record=entry is not None, entry=entry):
        # The write failed (logged by _autosave, which never raises): still
        # dirty, and the timer tries again autosave_seconds from now -- with
        # this save's transcript line kept for it (T16 review M4).
        if entry is not None:
            session.pending_entry = entry
        mark_dirty(session, "save_failed")
        return False
    session.pending_entry = None
    return True


def compact(session: Any) -> int:
    """
    The phone's bounded state, made at every save (CALLER HOLDS the turn lock;
    spec §17.2, v0.22.0 T26): each thread's messages past `social.state_messages`
    -- and a dead thread's every one (`archive.dead`) -- to the archive
    (`archive.spill`), every swiped-only person cut to what dedupe needs
    (`matching.compact_swiped`), answered requests past
    `social.requests_kept` forgotten (`relationships.forget_answered`), and
    a dormant person's older recaps, `current` and `bridge` moved to the
    archive whole (`memory.compact_dormant`, v0.23.0 T6; their next
    conversation brings them back), and closed promises past
    `promises.yaml` `closed_kept` a person forgotten, tallied on the person
    (`promises.forget_closed`, v0.23.0 T9 fix round 1), and closed plans past `plans.yaml` `closed_kept` a
    person likewise (`plans.forget_closed`, v0.23.0 T12), and past life events beyond `life_events.yaml`
    `kept.past` a person (`life.forget_past`, v0.23.0 T17). None changes a
    mechanic or loses a word: the archive, the thread's stamp, the story and
    the tallies answer every later read. How many rows moved, were cut or left.
    """
    from engine.social import life, matching, memory, plans, promises, relationships

    state = session.engine.state
    try:
        directory = archive.save_dir(session)
    except ValueError:                                  # an id the store refuses: no archive to move into
        directory = None
    return (archive.spill(session) + matching.compact_swiped(state) + relationships.forget_answered(state)
            + memory.compact_dormant(state, directory) + promises.forget_closed(state)
            + plans.forget_closed(state) + life.forget_past(state))


def mark_dirty(session: Any, reason: str) -> None:
    """The session's phone state changed since its last save: the timer saves it `autosave_seconds` out."""
    session.dirty = True
    if keeps_nothing(session):
        return                                     # no timer and no DirtySaver thread for a harness (F3)
    get_dirty_saver().schedule(session, time.monotonic() + float(social.setting("autosave_seconds", 10)))


def flush_taken(session: Any) -> None:
    """A run taken for good, its turn lock held by the caller: saved if dirty (spec §16.5)."""
    if getattr(session, "dirty", False):
        save_now(session)


def flush_all(store: Any = None) -> int:
    """
    Every voicing pass cancelled, then every live session of the store (the
    process's by default) that is dirty and whose turn lock is free, saved
    (shutdown, spec §16.5). A session whose
    lock is held is left to its holder. Returns how many were saved.
    """
    store = store or _default_store()
    # The voicing passes first (spec §16.5): a cancelled pass commits nothing
    # more, so no save written here is followed by a stale reply's.
    from engine.social import voicer

    voicer.cancel_all()
    saved = 0
    for session in store.live_sessions():
        if not getattr(session, "dirty", False) or not session.lock.acquire(blocking=False):
            continue
        try:
            if session.dirty and save_now(session):
                saved += 1
        except Exception as exc:  # noqa: BLE001 -- one run's fault must not cost the others theirs
            logger.warning("[social] Flush failed (operation=flush_all, id=%s): %s", session.session_id, exc)
        finally:
            release_turn(session)
    if saved:
        logger.info("[social] Flushed %d phone save(s) (operation=flush_all)", saved)
    return saved


def install_shutdown_flush() -> None:
    """Local shutdown: `flush_all` at interpreter exit, registered once however often the app is built."""
    atexit.unregister(flush_all)
    atexit.register(flush_all)


class DirtySaver:
    """
    One thread and a heap of (due, seq, session, epoch) (spec §17.2). Marking a
    session dirty schedules it at now + social.autosave_seconds. When due:
    liveness, a NON-BLOCKING try of the turn lock (busy -> again in 1 s), save
    if still dirty, release, end_after_turn. So a swipe with no follow-up is on
    disk within autosave_seconds (plus any busy retry).
    """

    BUSY_RETRY_SECONDS = 1.0

    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._lock = threading.Lock()            # LEAF: guards the heap only
        self._wake = threading.Event()
        self._heap: list[tuple[float, int, Any, int]] = []
        self._seq = itertools.count()
        self._clock = clock
        self._stopped = False
        self._thread: Optional[threading.Thread] = None
        #: (session id, epoch) of every run with an entry in the heap: ONE
        #: entry per live run, however many actions dirty it meanwhile.
        self._queued: set[tuple[str, int]] = set()

    def schedule(self, session: Any, due: float) -> None:
        """
        Save `session` at `due` if still dirty. A run already in the heap
        keeps its earlier entry (it saves sooner, never later, than
        autosave_seconds after this action); a popped one may be queued again.
        """
        key = (session.session_id, session.epoch)
        with self._lock:
            if key not in self._queued:
                self._queued.add(key)
                heapq.heappush(self._heap, (due, next(self._seq), session, session.epoch))
            start = self._thread is None
            if start:
                self._thread = threading.Thread(target=self._run, name="social-dirty-saver", daemon=True)
        if start:
            self._thread.start()
        self._wake.set()

    def _pop_due(self) -> Optional[tuple[Any, int]]:
        with self._lock:
            if self._heap and self._heap[0][0] <= self._clock():
                _due, _seq, session, epoch = heapq.heappop(self._heap)
                self._queued.discard((session.session_id, epoch))
                return session, epoch
            return None

    def _next_wait(self) -> float:
        with self._lock:
            # At most 5 s: a schedule wakes it sooner, and a far-off due never overflows the wait.
            return 5.0 if not self._heap else min(5.0, max(0.0, self._heap[0][0] - self._clock()))

    def _run(self) -> None:
        while not self._stopped:
            item = self._pop_due()
            if item is None:
                self._wake.wait(self._next_wait())
                self._wake.clear()
                continue
            session, epoch = item
            try:
                if not alive(session, epoch) or not session.dirty:
                    continue
                if not session.lock.acquire(blocking=False):
                    self.schedule(session, self._clock() + self.BUSY_RETRY_SECONDS)
                    continue
                try:
                    if session.dirty:
                        save_now(session)
                finally:
                    release_turn(session)                 # the one release (Plan decision 31)
            except Exception as exc:  # noqa: BLE001 -- the timer outlives one run's fault
                logger.warning("[social] Timed save failed (operation=DirtySaver, id=%s): %s",
                               getattr(session, "session_id", ""), exc)

    def stop(self) -> None:
        self._stopped = True
        self._wake.set()


#: The process's one DirtySaver, built on first use (double-checked under
#: `_saver_lock`; `reset_dirty_saver` stops and drops it).
_saver: Optional[DirtySaver] = None
_saver_lock = threading.Lock()


def get_dirty_saver() -> DirtySaver:
    global _saver
    saver = _saver
    if saver is not None:
        return saver
    with _saver_lock:
        if _saver is None:
            _saver = DirtySaver()
        return _saver


def reset_dirty_saver() -> None:
    """Stop the process's DirtySaver and drop it (tests' teardown; T14's `_quiet_voicer`)."""
    global _saver
    with _saver_lock:
        saver, _saver = _saver, None
    if saver is not None:
        saver.stop()


renew_after_fork(globals(), _saver_lock=threading.Lock)


__all__ = [
    "IMMEDIATE",
    "DirtySaver",
    "alive",
    "flush_all",
    "flush_taken",
    "get_dirty_saver",
    "install_shutdown_flush",
    "keeps_nothing",
    "mark_dirty",
    "release_turn",
    "reset_dirty_saver",
    "save_now",
]
