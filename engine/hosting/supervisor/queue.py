"""
One Queue Across Processes
==========================

The supervisor holds the model server's lanes for EVERY worker (spec §14.4):
one structure, sized by ``llm.lanes``, that each worker reaches over the bus
(``lane.acquire``, ``lane.release``, ``lane.cancel``) through
``engine.hosting.lanes_remote``.

NOT T9'S ``FifoSemaphore``. That class blocks a thread per waiter and serves
strictly the head of its line. This one answers waiters without a thread
each, and skips a paused story's waiters. Each lane is a deque of waiter
entries (ticket, story, account, connection, since, deadline) and a set of
holders, and a grant goes to the FIRST ELIGIBLE entry in arrival order:

- GRANTS ARE ASYNCHRONOUS. An acquire that cannot be granted at once is an
  entry, answered by whatever frees a slot (a release, a cancel, a resume, a
  reclaim) or by the ONE deadline thread (``busy`` at its deadline).
  ``acquire``, ``release``, ``cancel`` and ``close_connection`` never wait:
  the bus's selector thread calls them, so a release never queues behind
  blocked acquires.
- TICKETS BELONG TO THE CONNECTION. ``story`` is stamped from it, never taken
  from the arguments; releasing another connection's ticket (or one never
  granted, or twice) is ``bad_args``; a connection that closes releases
  every ticket it held and cancels its waits, so a crashed worker cannot
  leak a lane.
- A WAIT CAN BE CALLED OFF (``cancel``, T11 fix round 1): a worker whose
  waiting turn's player left (the socket disconnected) withdraws it, so the
  player holds no place and no account claim for the rest of the wait.
- ONE NARRATION TICKET PER ACCOUNT, across every connection: a narration
  acquire for an account that already holds or awaits one is answered at
  once with ``other_window`` (spec §5.4). The utility lane has no such rule.
  THE ACCOUNT IS THE WORKER'S WORD: a worker is a token-authenticated child
  inside the trust boundary, taking the account from its own login-checked
  session; the queue checks only its shape (``accounts.ID_RE``). The rule
  is fairness between one operator's players, not a security boundary.
- PAUSE means NO NEW NARRATION ADMISSIONS for a story (a drain) or for all
  (a model-settings change, spec §14.9). What it does NOT stop: a utility
  acquire from an account that holds a narration ticket ON THE SAME
  CONNECTION (an admitted turn's planner, summarizer, Assistant or quest
  evaluation) is granted as always, so a pause can never hold an admitted
  turn, nor the drain waiting on it (design review C1). A paused story's
  waiters keep their places and grants SKIP them, so a paused story at the
  head of a lane never delays another story's waiter. Other utility
  acquires from a paused story (a voice reply outside any turn) wait with
  its narration waiters. ``resume`` grants in arrival order.
- CLOSING (``close_story``): once a drain has found the story idle, its
  waiters are answered ``busy`` (a turn queued but not admitted never
  started, spec §14.3) and its new acquires are refused at once, until
  ``resume``.
- LANES: those ``llm.lanes`` names (``engine.llm.gate.lane_limits``, the
  one source of the defaults), and a lane named nowhere is opened at
  ``DEFAULT_LANE_LIMIT`` when first asked for -- as the gate opens it in a
  worker's own process -- so a profile's custom lane works the same
  everywhere (T11 fix round 1). A lane name is a short identifier.
- RESIZE only while every lane is paused for all and no ticket is held.
  A model apply then NARROWS the pause to each story (``narrow_pause``,
  v0.20.0 T16) and resumes each as its worker is ready again.
- ``max_hold_seconds`` (T11 fix round 1: a backstop, every healthy turn
  ends by ``hosting.turn_deadline_seconds``): a ticket held past it is
  RECLAIMED -- an ERROR (a ``process`` ``unhealthy`` event), the slot given
  to the next waiter at once, and ``on_reclaim`` told, which asks the worker
  to acknowledge (and restarts it only if it does not: hung). A reclaim is
  never a crash. The worker's later release of a reclaimed ticket is
  accepted quietly.
- ``snapshot`` holds ids, slugs, enums and numbers only (spec §14.10).
- METRICS (v0.20.0 T17): each ticket's end -- a release, a reclaim, its
  connection's close (``granted``, with its wait and its hold), a deadline
  (``timeout``), a cancel, a close or a drain (``cancelled``), the one
  narration ticket per account (``other_window``) -- is handed to
  ``on_event`` as a ``lane`` metric, with ``_cond`` released. A lane the
  metrics schema does not name (a profile's custom lane) is not recorded.

LOCKING. ``_cond`` (a condition over an ``RLock``, never re-entered) is a
leaf in the supervisor's process (``engine/locks.py``,
``tests/lock_order.py``): its holder counts, appends and pops, and never
logs, sends a frame or calls back. The answers a change produces are
collected under it and sent after it is released, and so is every log line
and callback.

Version: v0.3.0 [2026-10-06]
"""

from __future__ import annotations

import collections
import itertools
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Deque, Mapping, Optional

from engine.hosting.accounts import ID_RE
from engine.llm.gate import DEFAULT_LANE_LIMIT, NARRATION, lane_limits

logger = logging.getLogger(__name__)

#: Error codes an acquire is answered with.
BUSY = "busy"
OTHER_WINDOW = "other_window"
CANCELLED = "cancelled"
BAD_ARGS = "bad_args"

#: An account id as ``engine/hosting/accounts.py`` mints it, or "" (none).
ACCOUNT_RE = re.compile(rf"^(?:{ID_RE.pattern})?$")

#: A lane's name: a short identifier (a profile's ``lane:``).
LANE_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")

#: The longest an acquire may ask to wait, in seconds.
MAX_WAIT_SECONDS = 86400.0

#: Reclaimed tickets remembered per queue (for a quiet late release), at most.
MAX_RECLAIMED = 1024

#: ``reply(result, error)``: answers one acquire (a bus reply). Called once.
Reply = Callable[[Optional[dict[str, Any]], str], None]


class QueueRefusal(RuntimeError):
    """An operation the queue refuses (``code``: ``bad_args``, ``refused``)."""

    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self.code = code


@dataclass
class _Entry:
    """A waiter or a holder: one ticket."""

    ticket: str
    lane: str
    story: str
    account: str
    owner: Any
    #: Wall-clock seconds at arrival (or at the grant, for a holder): shown.
    since: float
    #: Monotonic: the waiter's deadline, or the holder's max-hold deadline.
    deadline: float
    #: The bus request this waiter answers (``cancel`` names it), or None.
    request: Any = None
    reply: Optional[Reply] = field(default=None, repr=False)
    #: Monotonic: when it arrived, and when it was granted (0: not yet), for
    #: its ``lane`` metric (v0.20.0 T17).
    arrived: float = 0.0
    granted: float = 0.0


@dataclass
class _Lane:
    limit: int
    waiters: Deque[_Entry] = field(default_factory=collections.deque)
    holders: dict[str, _Entry] = field(default_factory=dict)


#: One answer to send once ``_cond`` is released: (entry, result, error).
_Answer = tuple[_Entry, Optional[dict[str, Any]], str]

#: The lanes a ``lane`` metric names (the schema's enum): a profile's custom
#: lane is not recorded (docs/HOSTING.md § Metrics).
METRIC_LANES = frozenset({"narration", "utility"})

#: Lane metric outcomes (``engine/hosting/metrics_schema.py``).
GRANTED = "granted"
TIMEOUT = "timeout"


def _lane_event(entry: _Entry, outcome: str, now: float) -> Optional[dict[str, Any]]:
    """
    One ticket's end as a ``lane`` metric (v0.20.0 T17): its wait (arrival
    to grant, or to now when never granted) and its hold (grant to now), or
    None for a lane the schema does not name.
    """
    if entry.lane not in METRIC_LANES:
        return None
    granted = entry.granted or 0.0
    waited_until = granted if granted else now
    return {
        "ts": round(time.time(), 3),
        "story": entry.story,
        "account": entry.account or None,
        "lane": entry.lane,
        "wait_ms": round(max(0.0, waited_until - entry.arrived) * 1000.0, 1),
        "hold_ms": round(max(0.0, now - granted) * 1000.0, 1) if granted else 0.0,
        "outcome": outcome,
    }


class LaneQueue:
    """The supervisor's lanes (see the module docstring)."""

    def __init__(
        self,
        limits: Optional[Mapping[str, int]] = None,
        *,
        max_hold_seconds: float = 1200.0,
        on_reclaim: Optional[Callable[[Any, str, str], None]] = None,
    ) -> None:
        self._cond = threading.Condition(threading.RLock())
        sizes = lane_limits(dict(limits)) if limits is not None else lane_limits()
        self._lanes: dict[str, _Lane] = {name: _Lane(size) for name, size in sizes.items()}
        self._tickets = itertools.count(1)
        self.max_hold_seconds = float(max_hold_seconds)
        #: ``on_reclaim(owner, story, ticket)``: a ticket was taken back.
        self.on_reclaim = on_reclaim
        self._paused_all = False
        self._paused: set[str] = set()
        self._closing: set[str] = set()
        #: Reclaimed ticket -> its owner, so its late release is quiet.
        self._reclaimed: "collections.OrderedDict[str, Any]" = collections.OrderedDict()
        self._stopping = False
        self._thread: Optional[threading.Thread] = None
        #: ``on_event(event)``: one ticket's end as a ``lane`` metric (v0.20.0
        #: T17), called with ``_cond`` released; None records nothing.
        self.on_event: Optional[Callable[[dict[str, Any]], None]] = None

    def _ended(self, entry: _Entry, outcome: str, now: float, events: list[dict[str, Any]]) -> None:
        """Note ``entry``'s end for ``on_event`` (the caller holds ``_cond``)."""
        if self.on_event is None:
            return
        event = _lane_event(entry, outcome, now)
        if event is not None:
            events.append(event)

    def _emit(self, events: list[dict[str, Any]]) -> None:
        """Hand each event to ``on_event``, with ``_cond`` released."""
        callback = self.on_event
        if callback is None:
            return
        for event in events:
            try:
                callback(event)
            except Exception:  # noqa: BLE001 -- a metric must never stop the queue
                logger.warning("[queue] A lane metric was not recorded (operation=on_event)")

    def _answer_events(self, answers: list[_Answer], now: float, events: list[dict[str, Any]]) -> None:
        """The metric of each refusal in ``answers`` (the caller holds ``_cond``)."""
        for entry, _result, error in answers:
            if error:
                self._ended(entry, _OUTCOME_OF.get(error, CANCELLED), now, events)

    # -- lifecycle --------------------------------------------------------------

    def start(self) -> "LaneQueue":
        """Start the ONE deadline thread (waiters' deadlines, holders' max hold)."""
        thread = threading.Thread(target=self._deadlines, name="lane-queue-deadlines", daemon=True)
        self._thread = thread
        thread.start()
        return self

    def close(self, timeout: float = 5.0) -> None:
        """Stop the deadline thread; every waiter is answered ``busy``."""
        events: list[dict[str, Any]] = []
        with self._cond:
            self._stopping = True
            answers: list[_Answer] = []
            for lane in self._lanes.values():
                while lane.waiters:
                    answers.append((lane.waiters.popleft(), None, BUSY))
            self._answer_events(answers, time.monotonic(), events)
            self._cond.notify_all()
        self._send(answers)
        self._emit(events)
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout)

    # -- the bus's calls (the selector thread: never wait) ------------------------

    def attach(self, server: Any) -> None:
        """
        Answer ``lane.acquire`` (deferred: when granted), ``lane.release``,
        ``lane.cancel`` and ``queue.snapshot`` on ``server`` (a ``BusServer``).
        Its owner calls ``close_connection(conn.id)`` from the server's close
        callback.
        """
        from engine.hosting.bus import BusRefusal

        def refused(conn: Any, op: str, refusal: QueueRefusal) -> BusRefusal:
            logger.warning(
                "[queue] Refused (operation=%s, process=%s, error=%s)", op, conn.process, refusal.code
            )
            return BusRefusal(refusal.code)

        def acquire(conn: Any, args: dict[str, Any], answer: Any) -> None:
            try:
                self.acquire(
                    owner=conn.id,
                    story=conn.story,  # stamped from the connection, never the arguments
                    lane=str(args["lane"]),
                    account=str(args.get("account") or ""),
                    timeout=float(args["timeout"]),
                    reply=answer,
                    request=getattr(answer, "request_id", None),
                )
            except QueueRefusal as refusal:
                raise refused(conn, "lane.acquire", refusal) from None

        def release(conn: Any, args: dict[str, Any]) -> dict[str, Any]:
            try:
                self.release(owner=conn.id, ticket=str(args["ticket"]))
            except QueueRefusal as refusal:
                raise refused(conn, "lane.release", refusal) from None
            return {}

        def cancel(conn: Any, args: dict[str, Any]) -> dict[str, Any]:
            return {"cancelled": self.cancel(owner=conn.id, request=args["id"])}

        server.handle_deferred("lane.acquire", acquire)
        server.handle("lane.release", release)
        server.handle("lane.cancel", cancel)
        server.handle("queue.snapshot", lambda _conn, _args: self.snapshot())

    def acquire(
        self,
        *,
        owner: Any,
        story: str,
        lane: str,
        account: str,
        timeout: float,
        reply: Reply,
        request: Any = None,
    ) -> None:
        """
        One acquire: answered through ``reply`` -- at once (a grant, a
        refusal) or later (a grant, ``busy`` at its deadline, ``cancelled``).
        ``request`` names it for ``cancel``.

        Raises:
            QueueRefusal: ``bad_args`` (a lane name that is not an
                identifier, an account that is not an id, a negative or huge
                timeout).
        """
        if not isinstance(lane, str) or not LANE_RE.fullmatch(lane):
            raise QueueRefusal(BAD_ARGS, "not a lane name")
        if not isinstance(account, str) or not ACCOUNT_RE.fullmatch(account):
            raise QueueRefusal(BAD_ARGS, "not an account id")
        wait = float(timeout)
        if not 0.0 <= wait <= MAX_WAIT_SECONDS:
            raise QueueRefusal(BAD_ARGS, "timeout out of range")
        now = time.monotonic()
        answers: list[_Answer] = []
        events: list[dict[str, Any]] = []
        opened = False
        with self._cond:
            entry = _Entry(
                ticket=f"t{next(self._tickets)}",
                lane=lane,
                story=story,
                account=account,
                owner=owner,
                since=time.time(),
                deadline=now + wait,
                request=request,
                reply=reply,
                arrived=now,
            )
            if self._stopping or story in self._closing:
                answers.append((entry, None, BUSY))
            elif lane == NARRATION and account and self._account_in_narration(account):
                answers.append((entry, None, OTHER_WINDOW))
            else:
                if lane not in self._lanes:
                    # Named nowhere: opened at the default size, as the gate
                    # opens it in a worker's own process.
                    self._lanes[lane] = _Lane(DEFAULT_LANE_LIMIT)
                    opened = True
                self._lanes[lane].waiters.append(entry)
                answers += self._grant()
                self._cond.notify_all()
            self._answer_events(answers, now, events)
        if opened:
            logger.info("[queue] Lane opened (operation=acquire, lane=%s, limit=%d)", lane, DEFAULT_LANE_LIMIT)
        self._send(answers)
        self._emit(events)

    def release(self, *, owner: Any, ticket: str) -> None:
        """
        Give ``ticket`` back; the first eligible waiter takes the slot. A
        ticket this queue reclaimed from ``owner`` is accepted quietly (the
        worker's turn ended after the reclaim).

        Raises:
            QueueRefusal: ``bad_args`` (no such ticket held by ``owner``).
        """
        events: list[dict[str, Any]] = []
        with self._cond:
            found = None
            for lane in self._lanes.values():
                entry = lane.holders.get(ticket)
                if entry is not None and entry.owner == owner:
                    found = lane
                    break
            if found is None:
                if self._reclaimed.get(ticket, _NOBODY) == owner:
                    del self._reclaimed[ticket]
                    return
                raise QueueRefusal(BAD_ARGS, "not a ticket this connection holds")
            self._ended(found.holders.pop(ticket), GRANTED, time.monotonic(), events)
            answers = self._grant()
            self._cond.notify_all()
        self._send(answers)
        self._emit(events)

    def cancel(self, *, owner: Any, request: Any) -> bool:
        """
        Withdraw ``owner``'s waiting acquire ``request`` (its player left):
        answered ``cancelled``; its place and its account claim go with it.
        False when it is not waiting (granted already, or never queued).
        """
        answers: list[_Answer] = []
        events: list[dict[str, Any]] = []
        with self._cond:
            for lane in self._lanes.values():
                for entry in lane.waiters:
                    if entry.owner == owner and entry.request is not None and entry.request == request:
                        lane.waiters.remove(entry)
                        answers.append((entry, None, CANCELLED))
                        break
                if answers:
                    break
            if answers:
                answers += self._grant()
                self._cond.notify_all()
            self._answer_events(answers, time.monotonic(), events)
        self._send(answers)
        self._emit(events)
        return bool(answers)

    def close_connection(self, owner: Any) -> int:
        """
        A connection closed: every ticket it held is released and every wait
        it had is cancelled (nothing to answer: it is gone). Answers how many
        tickets it held.
        """
        events: list[dict[str, Any]] = []
        with self._cond:
            now = time.monotonic()
            freed = 0
            for lane in self._lanes.values():
                for ticket in [t for t, e in lane.holders.items() if e.owner == owner]:
                    self._ended(lane.holders.pop(ticket), GRANTED, now, events)
                    freed += 1
                kept = [e for e in lane.waiters if e.owner != owner]
                for gone in (e for e in lane.waiters if e.owner == owner):
                    self._ended(gone, CANCELLED, now, events)
                if len(kept) != len(lane.waiters):
                    lane.waiters = collections.deque(kept)
            for ticket in [t for t, o in self._reclaimed.items() if o == owner]:
                del self._reclaimed[ticket]
            answers = self._grant()
            self._cond.notify_all()
        self._send(answers)
        self._emit(events)
        return freed

    # -- pause, resume, drain, resize (other threads) -----------------------------

    def pause(self, story: Optional[str] = None) -> None:
        """No new narration admissions for ``story`` (None: for every story)."""
        with self._cond:
            if story is None:
                self._paused_all = True
            else:
                self._paused.add(story)
            self._cond.notify_all()
        logger.info("[queue] Paused (operation=pause, story=%s)", story or "*")

    def narrow_pause(self, stories: Any) -> None:
        """
        Turn a pause for every story into a pause of each of ``stories``, at
        once (v0.20.0 T16, spec §14.9 step 5): a model apply drains with every
        lane paused for all, resizes, then resumes each story on its own as
        its worker comes back ``ready`` (``resume(story)``) -- which a pause
        for all would override. Grants follow for any story not named.
        """
        with self._cond:
            self._paused.update(str(story) for story in stories)
            self._paused_all = False
            answers = self._grant()
            self._cond.notify_all()
        self._send(answers)
        logger.info("[queue] Pause narrowed to each story (operation=pause)")

    def resume(self, story: Optional[str] = None) -> None:
        """Lift a pause (and a closing) for ``story`` (None: all); grants in arrival order."""
        with self._cond:
            if story is None:
                self._paused_all = False
                self._paused.clear()
                self._closing.clear()
            else:
                self._paused.discard(story)
                self._closing.discard(story)
            answers = self._grant()
            self._cond.notify_all()
        self._send(answers)
        logger.info("[queue] Resumed (operation=resume, story=%s)", story or "*")

    def close_story(self, story: str) -> int:
        """
        A drained story is stopping: its waiters are answered ``busy`` (they
        never started) and its new acquires are refused at once, until
        ``resume``. Answers how many waiters were refused.
        """
        answers: list[_Answer] = []
        events: list[dict[str, Any]] = []
        with self._cond:
            self._closing.add(story)
            for lane in self._lanes.values():
                kept: Deque[_Entry] = collections.deque()
                for entry in lane.waiters:
                    if entry.story == story:
                        answers.append((entry, None, BUSY))
                    else:
                        kept.append(entry)
                lane.waiters = kept
            self._answer_events(answers, time.monotonic(), events)
            self._cond.notify_all()
        self._send(answers)
        self._emit(events)
        return len(answers)

    def paused(self, story: str) -> bool:
        with self._cond:
            return self._is_paused(story)

    def held(self, story: Optional[str] = None) -> int:
        """Tickets held now, in every lane, by ``story`` (None: by anyone)."""
        with self._cond:
            return self._held(story)

    def wait_until_idle(self, story: Optional[str], timeout: float) -> bool:
        """
        Block until ``story`` (None: everyone) holds no ticket in any lane, at
        most ``timeout`` seconds: a drain. True once idle. Never call it on the
        selector thread.
        """
        with self._cond:
            return self._cond.wait_for(lambda: self._held(story) == 0, max(0.0, float(timeout)))

    def wait_for(self, predicate: Callable[[dict[str, Any]], bool], timeout: float) -> bool:
        """Block until ``predicate(snapshot())`` holds (tests and diagnostics)."""
        deadline = time.monotonic() + max(0.0, float(timeout))
        with self._cond:
            while True:
                if predicate(self._snapshot()):
                    return True
                left = deadline - time.monotonic()
                if left <= 0:
                    return False
                self._cond.wait(left)

    def resize(self, lane: str, limit: int) -> None:
        """
        Resize ``lane`` (a new lane is added). Only while every lane is paused
        for all and no ticket is held in any lane.

        Raises:
            QueueRefusal: ``refused`` otherwise.
        """
        with self._cond:
            if not self._paused_all or self._held(None):
                raise QueueRefusal(
                    "refused", "lanes are resized only while paused for all with no ticket held"
                )
            existing = self._lanes.get(lane)
            if existing is None:
                self._lanes[lane] = _Lane(max(1, int(limit)))
            else:
                existing.limit = max(1, int(limit))
            self._cond.notify_all()
        logger.info("[queue] Lane resized (operation=resize, lane=%s, limit=%d)", lane, max(1, int(limit)))

    def snapshot(self) -> dict[str, Any]:
        """Per lane: limit, paused, holders and waiters in order -- ids, slugs and numbers only."""
        with self._cond:
            return self._snapshot()

    # -- internals (``_cond`` held) ------------------------------------------------

    def _is_paused(self, story: str) -> bool:
        return self._paused_all or story in self._paused

    def _held(self, story: Optional[str]) -> int:
        return sum(
            1
            for lane in self._lanes.values()
            for entry in lane.holders.values()
            if story is None or entry.story == story
        )

    def _account_in_narration(self, account: str) -> bool:
        lane = self._lanes[NARRATION]
        return any(e.account == account for e in lane.holders.values()) or any(
            e.account == account for e in lane.waiters
        )

    def _holds_narration(self, entry: _Entry) -> bool:
        """Whether ``entry``'s account holds narration ON ITS OWN CONNECTION (its own turn)."""
        return bool(entry.account) and any(
            e.account == entry.account and e.owner == entry.owner
            for e in self._lanes[NARRATION].holders.values()
        )

    def _eligible(self, entry: _Entry) -> bool:
        if not self._is_paused(entry.story):
            return True
        # A paused story admits no new turn; an admitted turn's own utility
        # calls are granted as always (spec §14.4, design review C1).
        return entry.lane != NARRATION and self._holds_narration(entry)

    def _grant(self) -> list[_Answer]:
        """Every grant the free slots allow, first eligible in arrival order."""
        answers: list[_Answer] = []
        now = time.monotonic()
        for lane in self._lanes.values():
            if len(lane.holders) >= lane.limit or not lane.waiters:
                continue
            kept: Deque[_Entry] = collections.deque()
            while lane.waiters:
                entry = lane.waiters.popleft()
                if len(lane.holders) < lane.limit and self._eligible(entry):
                    entry.since = time.time()
                    entry.granted = now
                    entry.deadline = now + self.max_hold_seconds
                    lane.holders[entry.ticket] = entry
                    answers.append((entry, {"ticket": entry.ticket}, ""))
                else:
                    kept.append(entry)
            lane.waiters = kept
        return answers

    def _snapshot(self) -> dict[str, Any]:
        lanes = []
        for name, lane in sorted(self._lanes.items()):
            lanes.append(
                {
                    "lane": name,
                    "limit": lane.limit,
                    "paused": self._paused_all,
                    "holders": [_row(e) for e in sorted(lane.holders.values(), key=lambda e: e.since)],
                    "waiters": [_row(e) for e in lane.waiters],
                }
            )
        return {
            "lanes": lanes,
            "paused_stories": sorted(self._paused),
            "closing_stories": sorted(self._closing),
        }

    # -- answering (no lock held) ------------------------------------------------

    @staticmethod
    def _send(answers: list[_Answer]) -> None:
        for entry, result, error in answers:
            reply, entry.reply = entry.reply, None
            if reply is None:
                continue
            try:
                reply(result, error)
            except Exception:  # noqa: BLE001 -- one bad answer must not stop the rest
                logger.exception("[queue] An answer failed (operation=reply, lane=%s)", entry.lane)

    # -- the deadline thread ---------------------------------------------------------

    def _deadlines(self) -> None:
        while True:
            answers: list[_Answer] = []
            reclaimed: list[_Entry] = []
            events: list[dict[str, Any]] = []
            with self._cond:
                if self._stopping:
                    return
                now = time.monotonic()
                upcoming: list[float] = []
                for lane in self._lanes.values():
                    if lane.waiters and any(e.deadline <= now for e in lane.waiters):
                        kept: Deque[_Entry] = collections.deque()
                        for entry in lane.waiters:
                            if entry.deadline <= now:
                                answers.append((entry, None, BUSY))
                                self._ended(entry, TIMEOUT, now, events)
                            else:
                                kept.append(entry)
                        lane.waiters = kept
                    upcoming += [e.deadline for e in lane.waiters]
                    for ticket, entry in list(lane.holders.items()):
                        if entry.deadline <= now:
                            # The backstop: taken back, the place passed on.
                            del lane.holders[ticket]
                            self._ended(entry, GRANTED, now, events)
                            reclaimed.append(entry)
                            self._reclaimed[ticket] = entry.owner
                            while len(self._reclaimed) > MAX_RECLAIMED:
                                self._reclaimed.popitem(last=False)
                        else:
                            upcoming.append(entry.deadline)
                if reclaimed:
                    answers += self._grant()
                if answers or reclaimed:
                    self._cond.notify_all()
                else:
                    # Woken by every change (a new waiter, a grant, a close)
                    # or at the next deadline.
                    self._cond.wait(max(0.0, min(upcoming) - now) if upcoming else None)
                    continue
            self._send(answers)
            self._emit(events)
            for entry in reclaimed:
                logger.error(
                    "[queue] A lane ticket was held past max_hold_seconds (%ds): reclaimed, its "
                    "place passed on, its worker asked to acknowledge (operation=max_hold, "
                    "event=unhealthy, process=worker-%s, lane=%s)",
                    int(self.max_hold_seconds),
                    entry.story,
                    entry.lane,
                )
                callback = self.on_reclaim
                if callback is not None:
                    try:
                        callback(entry.owner, entry.story, entry.ticket)
                    except Exception:  # noqa: BLE001
                        logger.exception("[queue] on_reclaim failed (operation=max_hold)")


#: No owner (a reclaimed ticket's lookup default).
_NOBODY = object()

#: A refusal's ``lane`` metric outcome: ``busy`` answered by a close or a
#: drain is a wait called off (its deadline's ``busy`` is ``timeout``,
#: recorded where the deadline thread answers it).
_OUTCOME_OF = {BUSY: CANCELLED, OTHER_WINDOW: OTHER_WINDOW, CANCELLED: CANCELLED}


def _row(entry: _Entry) -> dict[str, Any]:
    return {"story": entry.story, "account": entry.account, "since": round(entry.since, 3)}


__all__ = [
    "BUSY",
    "CANCELLED",
    "LANE_RE",
    "LaneQueue",
    "OTHER_WINDOW",
    "QueueRefusal",
]
