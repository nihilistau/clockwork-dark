"""
Inference Gate
==============

Rations concurrent calls to the model server, per LANE.

WHY LANES
---------
The old gate was a single ``BoundedSemaphore(1)`` for the whole process, on the
premise that LM Studio serializes per loaded model anyway. That premise costs
more than it saves: the Assistant turn and the memory summarizer had to queue
behind narration, so the two cheapest calls in the game could each add their
full latency to the turn the player is watching. And when they ran first,
narration waited on THEM -- the frozen screen the single gate was meant to
prevent.

LM Studio supports concurrent requests. So narration gets a lane of its own and
utility work shares another. Narration never waits for a summary again, and
utility calls still cannot stampede the GPU.

Limits are configurable under ``llm.lanes``; a lane with no configured
limit falls back to ``DEFAULT_LANE_LIMIT``.

HOSTED MODE: ONE MODEL SERVER, MANY PLAYERS (v0.20.0, spec §5.3)
---------------------------------------------------------------
Three changes, all effective only when ``hosting.enabled`` (read from config;
this module never imports ``engine.hosting``). Local mode keeps v0.19.0's
lanes exactly: a ``threading.BoundedSemaphore`` per lane and a 180-second wait.

1. **FIFO lanes.** Each lane is a ``FifoSemaphore``: waiters are served in the
   order they arrived. A ``BoundedSemaphore`` lets a new arrival take a freed
   slot ahead of a thread that has been waiting, so under steady load one
   player could wait out a timeout while others kept getting in.
2. **Admission before the turn touches anything** (survey finding 13).
   ``turn_admission`` takes a NARRATION ticket before the turn runs a single
   mechanic, and records the held lane in a ``ContextVar``. Every
   ``inference_slot(lane="narration")`` inside that turn -- the storyteller's
   call, its ``:retry`` and ``:room`` calls, the stream -- sees the held lane
   and runs without queueing again, so an admitted turn can never time out in
   narration (and never be narrated by ``fallback_narration`` over a turn whose
   mechanics already ran). Admission that times out raises ``InferenceBusy``
   before anything has happened, and the caller refuses the turn
   (``engine/scenes/default_scene.py::run_guarded``).

   The held lane is SHARED, not multiplied: calls made under it take the
   ticket's one slot in turn (``_Held.share``, an ``RLock``), so a turn whose
   pipeline plans on two threads (``carrying_held_lane``) still sends one
   narration request at a time, as the operator sized the lane.
3. **A longer wait for a turn, a short one for utility work.** Admission (and
   the narration lane) waits ``hosting.queue_wait_seconds`` (600 by default)
   instead of ``DEFAULT_WAIT_SECONDS``: five players queued behind one
   narration slot on a reasoning model are five turns deep. Every other lane
   waits ``hosting.utility_wait_seconds`` (5) and is then skipped (T9 fix
   round 1): an admitted turn holds the narration slot while its companion
   and summarizer run, and waiting minutes on a utility slot there would hold
   every other player's turn behind someone's voice reply.

THE LANE BACKEND (v0.20.0 T11, spec §14.4). Every lane acquisition goes
through ``_acquire``. Under the supervisor one queue serves every worker
process: the worker's ``install()`` calls ``set_lane_backend`` once, at
startup, with ``engine.hosting.lanes_remote.RemoteLanes``, and from then on
``_acquire`` asks that backend (``LaneBackend``: ``acquire(lane, timeout,
account, story) -> ticket``, ``release(ticket)``) instead of this process's
lanes. This module never imports ``engine.hosting``: the backend is handed
in. The held-lane ``ContextVar`` is consulted FIRST and is unchanged, so a
turn's ``:retry``, ``:room`` and stream calls re-enter its narration ticket
without asking the backend; admission, the waits and the utility lane's
degradation are the same rules whichever backend answers. The held lane
carries the turn's ACCOUNT, so the utility calls an admitted turn makes are
asked for in its name (the supervisor grants those even while the story is
paused, spec §14.4). Local mode sets no backend and keeps
``BoundedSemaphore``; a standalone hosted worker (no supervisor) keeps the
in-process FIFO lanes.

A refusal says why in ``InferenceBusy.reason``: ``busy`` (no slot in time),
``other_window`` (the account's narration ticket is held or awaited by
another worker, spec §5.4), or the bus's own code when the link is down: a
turn is refused then, never run unqueued.

The drain that stops a worker is the supervisor's (it pauses that story's
admissions in its queue and waits for the story's tickets to come back);
T10's worker-local pause is gone.

THE TURN DEADLINE (T11 fix round 1). A hosted turn is admitted with a
wall-clock budget, ``hosting.turn_deadline_seconds``, counted from
admission over the whole turn, its utility calls included. Past it no
model call starts (``inference_slot`` refuses, ``deadline``), no wait
outlasts it, and a call in flight is cut: the model clients take their
timeout through ``call_timeout`` and stop a stream when ``turn_expired``
says so. So a slow model ends the turn through the existing failure path --
the storyteller's engine-authored fallback narration, a utility call's
degradation -- and the turn gives its ticket back on time. The same check
sees a ticket the supervisor RECLAIMED (held past ``max_hold_seconds``):
such a turn makes no further model call, so nothing runs outside the
queue. Local mode has no deadline: every helper answers as if none.

Queue position: ``FifoSemaphore.position(ticket)`` can say where a waiter
stands, and nothing tells the player yet (docs/GOVERNANCE.md, NOT WIRED:
the client has nowhere to show it until v0.21.0's UI).

Version: v0.7.0 [2026-10-05]
"""

from __future__ import annotations

import collections
import contextvars
import logging
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator, Optional, Protocol, TypeVar

from engine.locks import renew_after_fork

logger = logging.getLogger(__name__)

DEFAULT_WAIT_SECONDS = 180.0
DEFAULT_LANE_LIMIT = 1

#: The lane a turn is admitted to (``turn_admission``).
NARRATION = "narration"

# Narration is the one the player is watching, so it gets a dedicated slot.
# Utility covers the summarizer, the Assistant, mechanics and quest evaluation.
_DEFAULT_LANES: dict[str, int] = {
    "narration": 1,
    "utility": 2,
}

_lanes: dict[str, Any] = {}
_lanes_lock = threading.Lock()
renew_after_fork(globals(), _lanes_lock=threading.Lock)
_limits: dict[str, int] = dict(_DEFAULT_LANES)

_F = TypeVar("_F", bound=Callable[..., Any])

#: ``InferenceBusy.reason`` values a caller may act on.
BUSY = "busy"
OTHER_WINDOW = "other_window"
#: The admitted turn passed its wall-clock deadline (``hosting.turn_deadline_seconds``).
DEADLINE = "deadline"
#: The supervisor took the turn's ticket back (held past ``max_hold_seconds``).
RECLAIMED = "reclaimed"
#: The wait was called off (its player left) before a slot came.
CANCELLED = "cancelled"

#: The clock a turn's deadline is measured on (a test may replace it).
_clock: Callable[[], float] = time.monotonic


class InferenceBusy(RuntimeError):
    """
    The gate could not be acquired, or the turn may make no more model calls.
    ``reason``: ``busy`` (no slot in time), ``other_window`` (the account's
    narration ticket is another worker's, spec §5.4), ``deadline`` (the turn
    passed ``hosting.turn_deadline_seconds``), ``reclaimed`` (the supervisor
    took its ticket back), ``cancelled`` (the wait was called off), or why the
    shared queue could not be asked (its link down).
    """

    def __init__(self, message: str = "", *, reason: str = BUSY) -> None:
        super().__init__(message)
        self.reason = reason


class CancelToken:
    """
    Calls off a wait for a slot: a hosted socket turn's admission is cancelled
    when its socket disconnects, so a player who left holds no place in the
    queue (and, under the supervisor, no account claim) for the rest of the
    wait. ``cancel`` runs every hook added (now or later), once each; hooks
    must not block. Lock-free: list appends and removals are atomic.
    """

    def __init__(self) -> None:
        self._cancelled = threading.Event()
        self._hooks: list[Callable[[], None]] = []

    @property
    def cancelled(self) -> bool:
        return self._cancelled.is_set()

    def cancel(self) -> None:
        self._cancelled.set()
        for hook in list(self._hooks):
            self._run(hook)

    def add_hook(self, hook: Callable[[], None]) -> None:
        self._hooks.append(hook)
        if self._cancelled.is_set():
            self._run(hook)

    def remove_hook(self, hook: Callable[[], None]) -> None:
        try:
            self._hooks.remove(hook)
        except ValueError:
            pass

    @staticmethod
    def _run(hook: Callable[[], None]) -> None:
        try:
            hook()
        except Exception:  # noqa: BLE001 -- a cancel never raises into its caller
            logger.exception("[llm] A cancel hook failed (operation=cancel)")


class LaneBackend(Protocol):
    """
    Where lane tickets come from when this process does not hold its own
    lanes (spec §14.4): ``acquire`` answers a ticket once granted, or raises
    ``InferenceBusy``; ``release`` gives it back. ``story`` is advisory: the
    supervisor stamps it from the worker's connection. ``cancel`` (a
    ``CancelToken``) is passed only when a caller has one. A backend may also
    answer ``reclaimed(ticket)``: whether the ticket was taken back.
    """

    def acquire(self, lane: str, timeout: float, account: str, story: str) -> Any: ...

    def release(self, ticket: Any) -> None: ...


#: The lane backend, or None (this process's own lanes). Set once at startup
#: by a supervised worker's ``install()`` (``set_lane_backend``), before
#: anything is served; read on every acquisition.
_backend: Optional[LaneBackend] = None


def set_lane_backend(backend: LaneBackend) -> None:
    """
    Take lane tickets from ``backend`` from now on. STARTUP ONLY: a worker's
    ``install()`` calls it once, before anything is served, and nothing
    changes it after (a ticket taken from one backend goes back to it).
    """
    global _backend
    _backend = backend
    logger.info(
        "[llm] Lane backend set (operation=set_lane_backend, backend=%s)", type(backend).__name__
    )


def reset_lane_backend() -> None:
    """Back to this process's own lanes. Tests only."""
    global _backend
    _backend = None


def lane_backend() -> Optional[LaneBackend]:
    """The lane backend in use, or None (this process's own lanes)."""
    return _backend


class FifoSemaphore:
    """
    A counting semaphore that serves its waiters in arrival order.

    A ``Condition`` over a deque of tickets: an acquire that cannot be served
    at once joins the back of the line and is granted only when it is at the
    front and a slot is free. A waiter that gives up (its timeout, or an
    exception while it waits) leaves the line, and the one behind it moves
    up; nothing it did costs a slot.

    One thread blocks per waiter, which is right inside one process (T9). The
    cross-process queue (T11) is the supervisor's own structure, not this.

    The internal condition's lock is private: its holder only counts, and
    takes no other lock (``engine/locks.py``).
    """

    def __init__(self, value: int = 1) -> None:
        if int(value) < 1:
            raise ValueError("a lane needs at least one slot")
        self.limit = int(value)
        self._held = 0
        self._waiters: collections.deque[object] = collections.deque()
        self._cond = threading.Condition(threading.Lock())

    @property
    def held(self) -> int:
        """Slots taken now."""
        with self._cond:
            return self._held

    @property
    def waiting(self) -> int:
        """Waiters in line now."""
        with self._cond:
            return len(self._waiters)

    def acquire(
        self,
        blocking: bool = True,
        timeout: Optional[float] = None,
        *,
        ticket: Optional[object] = None,
    ) -> bool:
        """
        Take a slot, in arrival order.

        Args:
            blocking: False takes a slot only if one is free and nobody waits.
            timeout: Seconds to wait; None waits for as long as it takes.
            ticket: The waiter's identity in line, for ``position``; one is
                made when not given.

        Returns:
            True once a slot is held; False when ``timeout`` ran out first.
        """
        with self._cond:
            if not self._waiters and self._held < self.limit:
                self._held += 1
                return True
            if not blocking:
                return False
            me = ticket if ticket is not None else object()
            self._waiters.append(me)
            self._cond.notify_all()  # for wait_until_waiting
            deadline = None if timeout is None else time.monotonic() + max(0.0, float(timeout))
            try:
                while True:
                    if self._waiters[0] is me and self._held < self.limit:
                        self._waiters.popleft()
                        self._held += 1
                        # A second free slot may serve the next in line too.
                        self._cond.notify_all()
                        return True
                    if deadline is None:
                        self._cond.wait()
                        continue
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        return False
                    self._cond.wait(remaining)
            finally:
                # Gave up (timeout) or was interrupted while waiting: leave the
                # line, so the one behind moves up. A granted ticket is gone
                # from the line already.
                if me in self._waiters:
                    self._waiters.remove(me)
                    self._cond.notify_all()

    def release(self) -> None:
        """Free a slot; the first waiter in line takes it."""
        with self._cond:
            if self._held <= 0:
                raise ValueError("FifoSemaphore released too many times")
            self._held -= 1
            self._cond.notify_all()

    def position(self, ticket: object) -> Optional[int]:
        """``ticket``'s place in line (0 is next), or None when it is not waiting."""
        with self._cond:
            for index, waiter in enumerate(self._waiters):
                if waiter is ticket:
                    return index
            return None

    def wait_until_waiting(self, count: int, timeout: float) -> bool:
        """Block until at least ``count`` are in line (tests and diagnostics)."""
        with self._cond:
            return self._cond.wait_for(lambda: len(self._waiters) >= count, timeout)


@dataclass
class _Held:
    """A lane held across a whole turn (``turn_admission``)."""

    lane: str
    #: The account the turn was admitted for ("" when none was named): the
    #: utility calls made under it are asked for in its name (spec §14.4).
    account: str = ""
    #: ``_clock()`` time past which the turn makes no more model calls
    #: (hosted: ``hosting.turn_deadline_seconds`` after admission), or None.
    deadline: Optional[float] = None
    #: The ticket and the backend it came from (None: this process's lanes),
    #: so a ticket the supervisor reclaimed is seen.
    ticket: Any = None
    backend: Any = None
    #: The calls made under the one ticket take its one slot in turn.
    share: Any = field(default_factory=threading.RLock)

    def expired(self) -> str:
        """Why this turn may make no more model calls (``deadline``, ``reclaimed``), or ""."""
        if self.deadline is not None and _clock() >= self.deadline:
            return DEADLINE
        reclaimed = getattr(self.backend, "reclaimed", None)
        if reclaimed is not None and self.ticket is not None and reclaimed(self.ticket):
            return RECLAIMED
        return ""


@dataclass
class _Slot:
    """One acquired slot: how to free it, and its ticket (None in this process's lanes)."""

    release: Callable[[], None]
    ticket: Any = None
    backend: Any = None


#: The lane this context's turn was admitted to; None outside an admitted
#: turn, and always None in local mode.
_held_lane: contextvars.ContextVar[Optional[_Held]] = contextvars.ContextVar(
    "engine_llm_gate_held_lane", default=None
)


def _hosted() -> bool:
    """``hosting.enabled``, read from config; False if config cannot be read."""
    try:
        from engine.config import hosting_enabled

        return hosting_enabled()
    except Exception:  # noqa: BLE001 -- config must never break inference
        return False


def default_wait(lane: str = NARRATION) -> float:
    """
    How long a lane or an admission waits when the caller names no timeout.

    Local mode: ``DEFAULT_WAIT_SECONDS`` for every lane. Hosted mode: the
    narration lane (a turn's admission, and the narration calls it shares)
    waits ``hosting.queue_wait_seconds``; every other lane waits only
    ``hosting.utility_wait_seconds`` (T9 fix round 1). A utility call is
    optional by design and every caller degrades without it, so a long wait
    bought nothing and cost everyone: an admitted turn waiting on a utility
    slot held the server's narration slot idle behind someone else's
    companion or voice reply.
    """
    if not _hosted():
        return DEFAULT_WAIT_SECONDS
    try:
        from engine.config import get_config

        cfg = get_config()
        if lane == NARRATION:
            return float(cfg.get("hosting.queue_wait_seconds", 600))
        return float(cfg.get("hosting.utility_wait_seconds", 5))
    except Exception:  # noqa: BLE001 -- config must never break inference
        return DEFAULT_WAIT_SECONDS


def lane_limits(configured: Any = None) -> dict[str, int]:
    """
    ``llm.lanes`` (``configured``) as lane sizes: the shipped defaults, each
    overridden by a configured size (at least 1); an unreadable size is
    skipped. THE one source of the defaults: this process's lanes and the
    supervisor's queue both read it. A lane named nowhere is opened at
    ``DEFAULT_LANE_LIMIT`` when first asked for, here and under the
    supervisor alike.
    """
    limits = dict(_DEFAULT_LANES)
    if isinstance(configured, dict):
        for lane, size in configured.items():
            try:
                limits[str(lane)] = max(1, int(size))
            except (TypeError, ValueError):
                continue
    return limits


def _configured_limit(lane: str) -> int:
    """Lane size from config, falling back to the shipped defaults."""
    try:
        from engine.config import get_config

        configured = (get_config().get("llm.lanes", {}) or {}).get(lane)
        if configured is not None:
            return max(1, int(configured))
    except Exception:  # noqa: BLE001 -- config must never break inference
        pass
    return max(1, int(_limits.get(lane, DEFAULT_LANE_LIMIT)))


def _semaphore(lane: str) -> Any:
    """
    Get or create the semaphore for a lane: a ``FifoSemaphore`` in hosted
    mode, a ``threading.BoundedSemaphore`` in local mode. One built in the
    other mode (a test that switched modes) is rebuilt; a real process never
    switches.
    """
    hosted = _hosted()  # read before the lock: config is the innermost lock
    limit = _configured_limit(lane)
    with _lanes_lock:
        existing = _lanes.get(lane)
        if existing is None or isinstance(existing, FifoSemaphore) != hosted:
            existing = FifoSemaphore(limit) if hosted else threading.BoundedSemaphore(limit)
            _lanes[lane] = existing
            logger.info(
                "[llm] Lane opened (operation=_semaphore, lane=%s, limit=%s, fifo=%s)",
                lane,
                limit,
                hosted,
            )
        return existing


def _acquire(
    lane: str, timeout: float, label: str, account: str = "", cancel: Optional[CancelToken] = None
) -> _Slot:
    """
    Take a slot in ``lane``; answer how to free it.

    THE ONE PLACE A LANE IS ACQUIRED (``inference_slot`` and ``admit_turn``
    both come here): through the lane backend when one is set (the
    supervisor's queue, v0.20.0 T11), else this process's own lanes.
    ``cancel`` calls off a backend's wait (this process's own lanes take no
    cancel: a T9 turn whose player left is skipped once admitted).

    Raises:
        InferenceBusy: no slot within ``timeout``, or the backend refused.
    """
    backend = _backend
    if backend is not None:
        if cancel is not None:
            ticket = backend.acquire(lane, float(timeout), account, "", cancel=cancel)  # type: ignore[call-arg]
        else:
            ticket = backend.acquire(lane, float(timeout), account, "")
        return _Slot(lambda: backend.release(ticket), ticket, backend)
    semaphore = _semaphore(lane)
    if not semaphore.acquire(timeout=timeout):
        raise InferenceBusy(
            f"Inference busy: waited {timeout:.0f}s for a slot in lane "
            f"{lane!r} ({label or 'unnamed'})"
        )
    return _Slot(semaphore.release)


def time_left() -> Optional[float]:
    """Seconds before this context's admitted turn passes its deadline, or None (no deadline)."""
    held = _held_lane.get()
    if held is None or held.deadline is None:
        return None
    return held.deadline - _clock()


def turn_expired() -> str:
    """
    Why this context's admitted turn may make no more model calls --
    ``deadline`` or ``reclaimed`` -- or "" (none held, or still in time).
    A model client asks it between a stream's chunks and stops the call.
    """
    held = _held_lane.get()
    return held.expired() if held is not None else ""


def call_timeout(timeout: float) -> float:
    """
    A model call's timeout, cut to what is left of this context's turn
    deadline (hosted). Unchanged with no deadline (local mode, always).
    """
    left = time_left()
    if left is None:
        return timeout
    return max(0.001, min(float(timeout), left))


def _refuse_expired(held: _Held, label: str) -> None:
    reason = held.expired()
    if reason:
        raise InferenceBusy(
            f"Inference refused: the turn's {'deadline passed' if reason == DEADLINE else 'ticket was reclaimed'} "
            f"({label or 'unnamed'})",
            reason=reason,
        )


@contextmanager
def inference_slot(
    *,
    timeout: Optional[float] = None,
    label: str = "",
    lane: Optional[str] = None,
) -> Iterator[None]:
    """
    Hold a slot in one lane for the duration of the block.

    Args:
        timeout: Seconds to wait for a slot; None is ``default_wait()``.
        label: Diagnostic name for the caller, used in the error message.
        lane: Lane to queue in. Defaults to "utility" -- the conservative
            choice, since anything that has not opted into its own lane is by
            definition not the thing on screen.

    A lane this context's turn already holds (``turn_admission``) is entered
    without queueing: the call shares the turn's ticket. Inside an admitted
    turn with a deadline (hosted), no call starts once the deadline has
    passed or the ticket was reclaimed, and no wait outlasts the deadline:
    the caller meets ``InferenceBusy`` and fails as any model failure does
    (the storyteller's engine-authored fallback, a utility's degradation).

    Raises:
        InferenceBusy: If no slot frees up within timeout, or the turn's time
            is up. Better a clear error the UI can show than a request that
            hangs forever.
    """
    resolved_lane = lane or "utility"
    wait = default_wait(resolved_lane) if timeout is None else float(timeout)
    held = _held_lane.get()
    if held is not None:
        _refuse_expired(held, label)
        left = time_left()
        if left is not None:
            wait = max(0.0, min(wait, left))
    if held is not None and held.lane == resolved_lane:
        if not held.share.acquire(timeout=wait):
            raise InferenceBusy(
                f"Inference busy: waited {wait:.0f}s for this turn's own slot in "
                f"lane {resolved_lane!r} ({label or 'unnamed'})"
            )
        try:
            yield
        finally:
            held.share.release()
        return

    slot = _acquire(resolved_lane, wait, label, held.account if held is not None else "")
    try:
        yield
    finally:
        slot.release()


class Admission:
    """A turn's narration ticket, held until ``release`` (``admit_turn``)."""

    def __init__(self, release: Optional[Callable[[], None]], token: Optional[contextvars.Token]) -> None:
        self._release = release
        self._token = token

    def release(self) -> None:
        """
        Give the ticket back (idempotent), in the context that took it.

        The slot first, the ContextVar after, in a ``finally``: a reset that
        raises (a token from another context) must never keep the slot, or
        the narration lane would be wedged for the process's life.
        """
        release, self._release = self._release, None
        token, self._token = self._token, None
        try:
            if release is not None:
                release()
        finally:
            if token is not None:
                _held_lane.reset(token)


def admit_turn(
    *,
    timeout: Optional[float] = None,
    label: str = "",
    account: str = "",
    deadline_seconds: Optional[float] = None,
    cancel: Optional[CancelToken] = None,
) -> Admission:
    """
    Take a narration ticket for one turn, BEFORE the turn runs anything
    (spec §5.3). While it is held, this context's narration calls re-enter it.

    ``account``: whose turn it is (hosted: the session's owner). Under the
    supervisor an account holds one narration ticket at a time across every
    story (spec §5.4), and the turn's utility calls are asked in its name.

    ``deadline_seconds`` (hosted: ``hosting.turn_deadline_seconds``): from
    admission, the turn's wall-clock budget. Past it no model call starts and
    a running one is cut (``call_timeout``, ``turn_expired``), so the turn
    ends through the model-failure path and gives its ticket back.

    ``cancel``: calls off the wait (the player left before a slot came).

    Already holding narration (a nested admission): answered with an admission
    that holds nothing new.

    Raises:
        InferenceBusy: no narration slot within ``timeout`` (``default_wait()``),
            ``other_window`` (the account's ticket is another's), or
            ``cancelled``.
    """
    held = _held_lane.get()
    if held is not None and held.lane == NARRATION:
        return Admission(None, None)
    wait = default_wait() if timeout is None else float(timeout)
    slot = _acquire(NARRATION, wait, label or "turn", account, cancel)
    deadline = None if deadline_seconds is None else _clock() + float(deadline_seconds)
    try:
        token = _held_lane.set(
            _Held(NARRATION, account, deadline=deadline, ticket=slot.ticket, backend=slot.backend)
        )
    except BaseException:
        slot.release()
        raise
    return Admission(slot.release, token)


@contextmanager
def turn_admission(
    *,
    timeout: Optional[float] = None,
    label: str = "",
    account: str = "",
    deadline_seconds: Optional[float] = None,
    cancel: Optional[CancelToken] = None,
) -> Iterator[None]:
    """``admit_turn`` as a block: the ticket is given back however it ends."""
    admission = admit_turn(
        timeout=timeout, label=label, account=account, deadline_seconds=deadline_seconds, cancel=cancel
    )
    try:
        yield
    finally:
        admission.release()


def held_lane() -> Optional[str]:
    """The lane this context's turn holds, or None."""
    held = _held_lane.get()
    return held.lane if held is not None else None


def carrying_held_lane(fn: _F) -> _F:
    """
    ``fn``, carrying this context's held lane into whatever thread runs it.

    A pool thread copies no ``ContextVar``, so a planner the pipeline runs on
    one would queue for the narration slot its own turn holds, and wait out
    the whole queue. Only the held lane is carried, nothing else of the
    caller's context. Holding none (local mode, always): ``fn`` itself.
    """
    held = _held_lane.get()
    if held is None:
        return fn

    def carried(*args: Any, **kwargs: Any) -> Any:
        token = _held_lane.set(held)
        try:
            return fn(*args, **kwargs)
        finally:
            _held_lane.reset(token)

    return carried  # type: ignore[return-value]


def set_lane_limit(lane: str, limit: int) -> None:
    """
    Resize one lane. Startup and tests only; not safe while calls are in flight.
    """
    hosted = _hosted()
    with _lanes_lock:
        _limits[lane] = max(1, int(limit))
        _lanes[lane] = (
            FifoSemaphore(_limits[lane]) if hosted else threading.BoundedSemaphore(_limits[lane])
        )
    logger.info(
        "[llm] Lane resized (operation=set_lane_limit, lane=%s, limit=%s)",
        lane,
        _limits[lane],
    )


def set_concurrency(limit: int) -> None:
    """
    Resize every lane to the same limit.

    Kept for the callers that predate lanes; ``set_lane_limit`` is the finer
    tool. Not thread-safe; call at startup only.
    """
    for lane in set(list(_lanes) + list(_DEFAULT_LANES)):
        set_lane_limit(lane, limit)
    logger.info(
        "[llm] Inference concurrency set (operation=set_concurrency, limit=%s)",
        limit,
    )


def reset_lanes() -> None:
    """Drop all lanes so the next acquire rebuilds them from config. Tests."""
    with _lanes_lock:
        _lanes.clear()
        _limits.clear()
        _limits.update(_DEFAULT_LANES)


__all__ = [
    "Admission",
    "BUSY",
    "CANCELLED",
    "CancelToken",
    "DEADLINE",
    "DEFAULT_LANE_LIMIT",
    "DEFAULT_WAIT_SECONDS",
    "FifoSemaphore",
    "InferenceBusy",
    "LaneBackend",
    "NARRATION",
    "OTHER_WINDOW",
    "RECLAIMED",
    "admit_turn",
    "call_timeout",
    "carrying_held_lane",
    "default_wait",
    "held_lane",
    "inference_slot",
    "lane_backend",
    "lane_limits",
    "time_left",
    "turn_expired",
    "reset_lane_backend",
    "reset_lanes",
    "set_lane_backend",
    "set_concurrency",
    "set_lane_limit",
    "turn_admission",
]
