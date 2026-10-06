"""
The Supervisor: the Bus Server, the Token Table and the Story Table
===================================================================

``Supervisor`` owns the bus server (``engine.hosting.bus.BusServer``: the
token table lives there, one single-use token per child START, recorded with
its role and story), the story table (one ``Child`` per story, and the front
door), the health checks, the restart policy and the operations
(``ops.py``). Spec §14.3.

THE FRONT DOOR (v0.20.0 T12) is started after the workers, from the same
table. The supervisor mints ONE proxy token per start (``secrets``), handed
to every child in ``CLOCKWORK_PROXY_TOKEN`` and nowhere else: the front door
sends it on every proxied request, and a worker trusts the front door's
forwarded headers only on a request that carries it (spec §14.5). Every
change to the story table (``slug``, ``state``, ``port`` of each worker) is
sent to the front door as a ``stories.changed`` notification, numbered by
``seq`` (``_publish``: after each change is said, and on every tick), so the
front door never asks the bus where a request should go.

THREADS, and what each may do:

- the MAIN thread runs ``run``: every ``TICK_SECONDS`` it looks at each child
  (an exit, the boot deadline, a lost bus link, failed bus health checks, a
  backoff that has run out), starts a child whose backoff is over, and hands
  health checks to the health pool and a crashed child to the reaper. Every
  child's step is guarded: one child's failure never ends the loop.
- the bus's SELECTOR thread runs the handlers below (``ready``,
  ``stories.*``, ``ops.list``, ``lane.*``, ``queue.snapshot``) and the
  ``hello`` admission and close callbacks: each records or answers from
  memory, and never blocks. A ``lane.acquire`` is an entry in the queue
  (``queue.py``), answered when granted; a close frees the connection's
  tickets there.
- the QUEUE's deadline thread answers waiters ``busy`` at their deadline and
  reclaims a ticket held past ``max_hold_seconds`` (``_ticket_reclaimed``,
  T11 fix round 1: never a crash).
- the HEALTH pool sends each child a bus ``health`` and makes a ``GET
  /api/health`` on its port (httpx, ``trust_env=False``), and asks a worker
  to acknowledge a reclaimed ticket (``_ask_reclaimed``): one that does not
  within ``reclaim_ack_seconds`` is hung, and restarted as a crash.
- the REAPER pool stops what is left of a crashed child (terminate, then
  kill, then the log capture's join) and applies the restart policy, so the
  main thread never waits on a dying process.
- the OPERATIONS thread (``ops.py``) runs a start, stop or restart, or a
  model apply (``llm.py``, v0.20.0 T16: drain every story, write the admin
  layer, restart the workers one at a time, roll back), one at a
  time. While it (or the reaper) works on a child the child is marked
  ``stopping`` and the main thread leaves it alone. Once one is final its
  outcome's audit row (for the admin the front door named, under the ref of
  the ``started`` row the front door wrote first) goes to the audit writer
  (v0.20.0 T15).
- the FAN-OUT pool also answers ``llm.health`` and ``llm.models`` (v0.20.0
  T16; ``llm.py``: the model server probed and listed, cached 10 s).
- the FAN-OUT pool (v0.20.0 T15) answers the admin panel's ``sessions.list``,
  ``sessions.end`` and ``sessions.end_owner``: each is a DEFERRED bus request
  (the selector never waits), sent on to every serving worker as the
  ``worker.sessions.*`` request of its name -- every worker AT ONCE, under one
  deadline (``BusServer.request_all``; fix round 1, M7) -- a page at a time,
  each worker's rows projected to ``SESSION_ROW_KEYS``. A worker that does
  not answer within ``FANOUT_SECONDS``, or whose page would pass the bus frame
  (``too_large``), is an ``errors`` row; a whole reply that would pass it is
  answered ``too_large`` by the bus.

``_lock`` guards the story table. Its holder takes the bus server's and the
operations table's locks (leaves) and NEVER logs, waits on a process, a
socket or a bus reply: what it has to say is queued (``_say``) and logged
once the lock is released (``_flush_said``), so a slow log can never hold the
story table (T10 fix round 1).

HEALTH. ``hosting.supervisor.health_failures`` consecutive failed BUS checks,
an exit, a lost bus link, no ``ready`` within ``boot_seconds`` or a
reclaimed lane ticket the worker did not acknowledge (it is hung) restart
the child: these are CRASH restarts. A reclaim the worker acknowledged
restarts nothing and counts for nothing. A failed HTTP check only marks it
``degraded`` (logged as a ``process`` ``unhealthy`` event) and a pass clears
it; it never restarts anything (spec §14.3: a full thread pool makes the
health request wait, and restarting on that would kill the busiest story).

THE RESTART POLICY. Backoff 1, 2, 4 ... 60 s. A crash after ``max_restarts``
crash restarts within ``restart_window_minutes`` HOLDS THE CHILD DOWN: logged
at ERROR, shown in the story table, restarted only by ``stories.restart`` (or
``stories.start``) or a supervisor restart. A restart an admin chose does not
count, and does not forgive: the crash history stays (and its backoff) unless
the admin revives a held-down child. A held-down front door ends the
supervisor, exit 1. A hold-down is written to the audit log
(``story.held_down``, actor ``supervisor``; v0.20.0 T14) with its log line,
after ``_lock`` is released (``_flush_said``), by the audit writer's own
thread (``process.AuditWriter``, T14 fix round 1): a bus handler that
flushes never waits on the audit lock.

A TOKEN IS ACCEPTED ONLY FROM A CHILD STARTING NOW (``_admit``): a crashed or
held-down child's unused token is retired, and ``ready`` is taken once, from
a child in ``starting``.

DRAINING (``_drain``, v0.20.0 T11): the story's new narration admissions are
paused in the queue and the drain waits until the story holds no ticket,
then answers its queued turns busy and asks the worker to let its open
requests finish; one that runs out resumes the story. T10's worker-local
pause is gone.

SHUTDOWN (``shutdown``): from its first moment nothing is restarted,
whatever exits; every worker is drained and stopped together (the bus
``shutdown``, then ``terminate()``, then ``kill()``), THEN the front door
(T18 fix round 1: so a turn drained to its end still reaches its player
through the relay), and the threads are released, all within
``shutdown_seconds`` (which holds a drain, a stop, the terminate grace, the
kill's wait and the front door's reserve: ``engine/hosting/config.py``).

METRICS (v0.20.0 T17, spec §14.10): the store (``metrics.py``) is opened by
``start`` after the bus binds, when ``__main__`` gives it a path
(``<storage.root>/hosting/metrics.sqlite3``), and closed last. Each child's
``metric`` is stamped with the connection's ``process`` and ``story`` and
recorded on the selector thread (``MetricsStore.record`` validates and
queues; it never waits). The supervisor records its own: a ``lane`` event at
each ticket's end (the queue's ``on_event``), a ``process`` event at each
start, ``ready``, unhealthy mark, exit, scheduled restart, hold-down and stop,
and its own ERROR records (``record_error``). ``metrics.query`` (a named query,
never SQL) and ``oracle.snapshot`` (``worker.oracle.snapshot`` to the story's
worker, its projection held to the pinned keys again) are answered from the
fan-out pool.

Version: v0.8.0 [2026-10-06]
"""

from __future__ import annotations

import logging
import os
import secrets
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

from engine.hosting.bus import (
    FRONTDOOR,
    REFUSED as BUS_REFUSED,
    WORKER,
    BusError,
    BusRefusal,
    BusServer,
    Connection,
    TokenRecord,
)
from engine.hosting.config import (
    FRONTDOOR_STOP_RESERVE_SECONDS,
    KILL_WAIT_SECONDS,
    TERMINATE_GRACE_SECONDS,
    HostingSettings,
)
from engine.hosting.metrics_schema import KINDS as METRIC_KINDS, SUPERVISOR_PROCESS, clean_projection
from engine.hosting.supervisor.logs import LogHub
from engine.hosting.supervisor.metrics import MetricsQueryError, MetricsStore, MetricsUnavailable
from engine.hosting.supervisor.queue import LaneQueue
from engine.hosting.supervisor.ops import (
    DONE,
    DRAINING as OP_DRAINING,
    REFUSED,
    RESTARTING as OP_RESTARTING,
    Operation,
    OperationRefused,
    Operations,
)
from engine.hosting.supervisor.process import (
    DEGRADED,
    DRAINING,
    HELD_DOWN,
    READY,
    RESTARTING,
    STARTING,
    STOPPED,
    Child,
    AuditWriter,
    audit_held_down,
    audit_operation,
    backoff,
    operation_audit,
    stop_process,
)

logger = logging.getLogger(__name__)

#: What a worker child runs by default (``python -m engine.hosting.boot``).
DEFAULT_WORKER_MODULE = "engine.hosting.boot"

#: What the front door child runs by default (``python -m engine.hosting.boot
#: --role frontdoor``, v0.20.0 T12).
DEFAULT_FRONTDOOR_MODULE = "engine.hosting.boot"

#: How often the main thread looks at the children, in seconds.
TICK_SECONDS = 0.1

#: The HTTP health check's timeout (spec §14.3), and the bus check's ceiling.
HEALTH_TIMEOUT_SECONDS = 5.0

#: How long a bus ``shutdown`` request waits for its answer, at most.
SHUTDOWN_ASK_SECONDS = 5.0

#: Extra time a drain request is given over the worker's own deadline.
DRAIN_MARGIN_SECONDS = 5.0

#: How long a worker has to acknowledge a reclaimed lane ticket (T11 fix
#: round 1). Its bus pool answers at once when it is alive, so seconds are
#: plenty; one that does not answer is hung.
RECLAIM_ACK_SECONDS = 10.0

#: How long a crashed child's log capture is waited for once its process is gone.
CAPTURE_JOIN_SECONDS = 5.0

#: What a stop or restart whose drain ran out is answered (spec §14.3).
DRAIN_REFUSED = "turns are still running; the story was not stopped"

#: Bus error codes the story ops answer with.
UNKNOWN_STORY = "unknown_story"
BUSY = "busy"
SHUTTING_DOWN = "shutting_down"
#: A ``sessions.end`` for a story whose worker is not serving.
UNAVAILABLE = "unavailable"

#: How long the workers have, all together, to answer one fan-out of
#: ``worker.sessions.*`` (v0.20.0 T15; fix round 1, M7: they are asked at
#: once, so a hung worker costs one deadline, not one per story). A handler
#: reads its store under one leaf lock, so a live worker answers at once; one
#: that does not is shown as an error row. Well inside the front door's own
#: wait (``admin.sessions.BUS_SECONDS``).
FANOUT_SECONDS = 5.0

#: The fan-out pool's threads: a few admins' pages at once.
FANOUT_THREADS = 4

#: Each connection's metrics, at most (fix round 1, I1): a token bucket of
#: ``METRIC_BURST`` filled at ``METRIC_RATE_PER_SECOND``; past it a metric is
#: dropped and counted (``dropped_rate``). A worker sends a few per turn, so
#: only a flood meets it.
METRIC_RATE_PER_SECOND = 100.0
METRIC_BURST = 400.0

#: The states whose worker answers the panel's ``sessions.*``.
SERVING_STATES = frozenset({READY, DEGRADED, DRAINING})

#: The keys a ``sessions.list`` row may carry, exactly: a worker's row is
#: projected to them (and ``story`` stamped) before it is passed on, so
#: nothing else reaches the panel (spec §14.8: metadata only).
SESSION_ROW_KEYS = ("owner", "session_id", "save_id", "created", "last_activity", "turns", "turn_running", "sockets")


class Supervisor:
    """The children, their health and restarts, and the operations (spec §14.3)."""

    def __init__(
        self,
        settings: HostingSettings,
        *,
        hub: LogHub,
        worker_module: str = DEFAULT_WORKER_MODULE,
        frontdoor_module: Optional[str] = None,
        environ: Optional[Mapping[str, str]] = None,
        cwd: Optional[str] = None,
        lanes: Optional[Mapping[str, int]] = None,
        worker_wsgi: str = "",
        frontdoor_wsgi: str = "",
        metrics_path: Optional[Path] = None,
    ) -> None:
        self.settings = settings
        self.hub = hub
        self._environ = environ
        self._cwd = cwd
        self.children: list[Child] = [
            Child(role=WORKER, slug=s, module=worker_module, wsgi=worker_wsgi) for s in settings.stories
        ]
        if frontdoor_module:
            self.children.append(Child(role=FRONTDOOR, slug="", module=frontdoor_module, wsgi=frontdoor_wsgi))
        self._lock = threading.RLock()
        self._said: list[tuple[int, str, tuple[Any, ...]]] = []
        #: Audit rows to write once ``_lock`` is released (v0.20.0 T14).
        self._audits: list[Callable[[], None]] = []
        #: Writes them on its own thread (fix round 1, M6).
        self._audit_writer = AuditWriter()
        self.shutting_down = threading.Event()
        self.stop_event = threading.Event()
        self.exit_code = 0
        self.server = BusServer(hello_seconds=float(settings.hello_seconds))
        self.server.on_hello = self._on_hello
        self.server.on_close = self._on_close
        self.server.admit = self._admit
        self.server.on_dead = self._bus_died
        self.server.handle("ready", self._ready)
        #: The front door's proxy token (spec §14.5): one per supervisor
        #: start, the same for every child; never logged, never on argv.
        self._proxy_token = secrets.token_hex(32)
        #: The ``stories.changed`` sequence, and the routing rows last sent.
        self._seq = 0
        self._published: Optional[list[dict[str, Any]]] = None
        self.server.handle("stories.list", self._stories_list)
        self.server.handle("stories.start", lambda c, a: self._submit("stories.start", a))
        self.server.handle("stories.stop", lambda c, a: self._submit("stories.stop", a))
        self.server.handle("stories.restart", lambda c, a: self._submit("stories.restart", a))
        self.server.handle("ops.list", lambda _c, _a: {"ops": self.ops.rows()})
        # The one queue for every worker (spec §14.4): answered on the
        # selector thread, which never waits; a grant is sent when it happens.
        self.queue = LaneQueue(
            lanes,
            max_hold_seconds=float(settings.max_hold_seconds),
            on_reclaim=self._ticket_reclaimed,
        )
        self.queue.attach(self.server)
        #: How long a worker has to acknowledge a reclaimed ticket before it
        #: is taken as hung (an instance attribute so a test can shorten it).
        self.reclaim_ack_seconds = RECLAIM_ACK_SECONDS
        self.ops = Operations(self._perform, on_final=self._operation_final)
        self._health = ThreadPoolExecutor(max_workers=8, thread_name_prefix="supervisor-health")
        self._reaper = ThreadPoolExecutor(max_workers=4, thread_name_prefix="supervisor-reaper")
        # The panel's live sessions (v0.20.0 T15): answered later, from the
        # fan-out pool, never on the selector thread, which must not wait on
        # a worker's reply.
        self._fanout = ThreadPoolExecutor(max_workers=FANOUT_THREADS, thread_name_prefix="supervisor-fanout")
        self.server.handle_deferred("sessions.list", self._deferred(self._sessions_list))
        self.server.handle_deferred("sessions.end", self._deferred(self._sessions_end))
        self.server.handle_deferred("sessions.end_owner", self._deferred(self._sessions_end_owner))
        # The model server (v0.20.0 T16, spec §14.9): its health and model
        # list from the fan-out pool (each may wait on the model server), and
        # the apply as an operation, answered with its id at once.
        from engine.hosting.supervisor.llm import ModelServer

        self.llm = ModelServer(self)
        self.server.handle_deferred("llm.health", self._deferred(self.llm.health))
        self.server.handle_deferred("llm.models", self._deferred(self.llm.models))
        self.server.handle("llm.apply", lambda _c, a: self.llm.submit(a))
        # Metrics (v0.20.0 T17, spec §14.10): the store is opened by start(),
        # after the bus binds; None (no path) keeps nothing, which is how a
        # supervisor built inside the test suite's own process runs. Each
        # child's `metric` is stamped and recorded on the selector thread
        # (record never waits); a query and an Oracle snapshot are answered
        # from the fan-out pool.
        self.metrics: Optional[MetricsStore] = (
            MetricsStore(
                metrics_path,
                retention_days=settings.retention_days,
                stories=settings.stories,
                max_mb=settings.metrics_max_mb,
            )
            if metrics_path is not None
            else None
        )
        #: Each connection's metric token bucket, ``conn.id -> [tokens,
        #: monotonic time]`` (fix round 1, I1): read and written on the
        #: selector thread only (``_metric``), popped by ``_on_close``.
        self._metric_buckets: dict[int, list[float]] = {}
        self.metric_rate = METRIC_RATE_PER_SECOND
        self.metric_burst = METRIC_BURST
        self.server.handle("metric", self._metric)
        self.server.handle_deferred("metrics.query", self._deferred(self._metrics_query))
        self.server.handle_deferred("oracle.snapshot", self._deferred(self._oracle_snapshot))
        self.queue.on_event = self._lane_event
        self._http: Any = None

    # -- saying things outside the lock -------------------------------------------

    def _say(self, level: int, message: str, *args: Any) -> None:
        """Queue a log line (the caller holds ``_lock``); ``_flush_said`` logs it."""
        self._said.append((level, message, args))

    def _flush_said(self) -> None:
        with self._lock:
            said, self._said = self._said, []
            audits, self._audits = self._audits, []
        for level, message, args in said:
            logger.log(level, message, *args)
        for write in audits:
            # On the writer's own thread (fix round 1, M6): this may be a bus
            # handler, which must never wait on the audit lock or an fsync.
            self._audit_writer.submit(write)
        self._publish()

    # -- the story table ---------------------------------------------------------

    def story_table(self) -> list[dict[str, Any]]:
        window = self.settings.restart_window_minutes * 60.0
        now = time.monotonic()
        with self._lock:
            return [child.row(window, now) for child in self.children]

    def routing_rows(self) -> list[dict[str, Any]]:
        """What the front door routes by: each worker's ``slug``, ``state`` and ``port``."""
        with self._lock:
            return [
                {"slug": c.slug, "state": c.state, "port": int(c.port)}
                for c in self.children
                if c.role == WORKER
            ]

    def _stories_list(self, _conn: Connection, _args: dict[str, Any]) -> dict[str, Any]:
        """``stories.list``: the table and the ``seq`` it is current at (selector thread)."""
        with self._lock:
            table, seq = self.story_table(), self._seq
        # Said at INFO: the front door reads it once per connect and is then
        # kept current by stories.changed, so a line per request would show.
        logger.info("[supervisor] Story table read (operation=stories.list, seq=%d)", seq)
        return {"stories": table, "seq": seq}

    def _publish(self) -> None:
        """
        Send the front door ``stories.changed`` when the routing rows differ
        from those last sent (or it has never been sent them). Numbered, so
        a front door that handles two at once keeps the newer. Never blocks:
        ``notify`` only queues the frame for the selector.
        """
        with self._lock:
            front = self.child(role=FRONTDOOR)
            conn = front.conn if front is not None else None
            if conn is None:
                self._published = None
                return
            rows = self.routing_rows()
            if rows == self._published:
                return
            self._seq += 1
            try:
                self.server.notify(conn, "stories.changed", {"stories": rows, "seq": self._seq})
            except BusError:
                return
            self._published = rows

    def child(self, slug: str = "", role: str = WORKER) -> Optional[Child]:
        for child in self.children:
            if child.role == role and (role == FRONTDOOR or child.slug == slug):
                return child
        return None

    # -- lifecycle ---------------------------------------------------------------

    def start(self) -> None:
        """Bind the bus, then start every worker in list order, then the front door."""
        import httpx

        self._http = httpx.Client(trust_env=False, timeout=HEALTH_TIMEOUT_SECONDS)
        self.queue.start()
        self.server.start()
        logger.info(
            "[supervisor] Bus listening (operation=start, bus=%s, stories=%s)",
            self.server.addr,
            ",".join(self.settings.stories),
        )
        self._open_metrics()  # spec §14.3 step 3: after the bus binds
        for child in self.children:
            with self._lock:
                self._spawn(child)
            self._flush_said()

    def run(self, stop: Optional[threading.Event] = None, signals: Optional[list[int]] = None) -> int:
        """
        The main loop, until ``stop`` (a signal) or ``stop_event``; then the
        shutdown. ``signals`` is what the signal handler recorded: it is said
        here, never in the handler (which may run while this thread holds a
        log lock).
        """
        stop = stop or self.stop_event
        while not (stop.wait(TICK_SECONDS) or self.stop_event.is_set()):
            try:
                self.tick()
            except Exception:  # noqa: BLE001 -- the loop outlives any one tick
                logger.exception("[supervisor] A tick failed (operation=tick)")
        for signum in list(signals or []):
            logger.info("[supervisor] Signal %d: shutting down (operation=signal)", signum)
        self.shutdown()
        return self.exit_code

    def _spawn(self, child: Child) -> None:
        """Start ``child`` with a fresh token (the caller holds ``_lock``)."""
        self._retire(child)
        record = self.server.mint(child.role, story=child.slug, process=child.name)
        environ = os.environ if self._environ is None else self._environ
        try:
            popen = child.spawn(
                addr=self.server.addr,
                record=record,
                environ=environ,
                cwd=self._cwd,
                proxy_token=self._proxy_token,
            )
        except BaseException:
            self.server.retire(record.token)
            raise
        try:
            child.capture = self.hub.capture(child.name, popen.stdout)
        except BaseException:
            # A process nobody reads would block on its own output: kill and
            # reap it now, never leave it to the next respawn (T10 fix round 2).
            self.server.retire(record.token)
            try:
                popen.kill()
                popen.wait(KILL_WAIT_SECONDS)
            except Exception:  # noqa: BLE001 -- best effort; the lifeline ends it anyway
                pass
            child.popen = None
            raise
        child.stopping = False
        self._process_event(child, "started")
        self._say(
            logging.INFO,
            "[supervisor] Started %s (operation=spawn, pid=%d, state=%s, command=%s)",
            child.name,
            popen.pid,
            child.state,
            " ".join(child.command[1:]),
        )

    def _retire(self, child: Child) -> None:
        """Retire ``child``'s token if it was never used: no later hello may take it."""
        record = child.record
        if record is not None and record.state == "unused":
            self.server.retire(record.token)

    def _bus_died(self) -> None:
        """The selector loop ended on its own: a deaf supervisor must not pretend to run."""
        logger.critical("[supervisor] The bus stopped: shutting down, exit 1 (operation=select)")
        self.exit_code = 1
        self.stop_event.set()

    # -- the bus's handlers (selector thread: never block) ------------------------

    def _owner(self, record: Any) -> Optional[Child]:
        for child in self.children:
            if child.record is not None and child.record is record:
                return child
        return None

    def _admit(self, record: TokenRecord) -> bool:
        """A hello is accepted only for the child this token was minted for, starting now."""
        with self._lock:
            child = self._owner(record)
            return (
                child is not None
                and child.state == STARTING
                and not child.stopping
                and child.conn is None
                and not self.shutting_down.is_set()
            )

    def _on_hello(self, conn: Connection) -> None:
        with self._lock:
            child = self._owner(conn.record)
            if child is not None:
                child.conn = conn

    def _on_close(self, conn: Connection) -> None:
        # Tickets belong to the connection: a crashed worker leaks no lane.
        freed = self.queue.close_connection(conn.id)
        self._metric_buckets.pop(conn.id, None)
        with self._lock:
            child = self._owner(conn.record)
            if child is not None and child.conn is conn:
                child.conn = None
                if not child.stopping and not self.shutting_down.is_set():
                    child.last_reason = "the bus link closed"
        if freed:
            logger.info(
                "[supervisor] %s's lane tickets freed with its connection (operation=close, tickets=%d)",
                conn.process,
                freed,
            )

    # -- the queue (its handlers are attached in __init__) -------------------------

    def _ticket_reclaimed(self, owner: Any, story: str, ticket: str) -> None:
        """
        The queue reclaimed a ticket held past ``max_hold_seconds`` (its
        deadline thread; the place is already passed on). The worker is told,
        on the health pool so the deadline thread never waits, and given
        ``reclaim_ack_seconds`` to acknowledge (T11 fix round 1). A reclaim is
        never a crash.
        """
        with self._lock:
            child = next((c for c in self.children if c.conn is not None and c.conn.id == owner), None)
            conn = child.conn if child is not None else None
        if child is None or conn is None:
            return  # gone already: its connection's close freed everything
        self._process_event(child, "unhealthy")  # spec §14.4: a reclaim is an unhealthy event, never a crash
        try:
            self._health.submit(self._ask_reclaimed, child, conn, ticket)
        except RuntimeError:  # shutting down: the shutdown stops it
            pass

    def _ask_reclaimed(self, child: Child, conn: Connection, ticket: str) -> None:
        """
        Ask the worker to acknowledge a reclaim. One that does not within
        ``reclaim_ack_seconds`` is hung: restarted, as a crash (it is one).
        """
        try:
            self.server.request(conn, "lane.reclaimed", {"ticket": ticket}, timeout=self.reclaim_ack_seconds)
        except BusError as exc:
            with self._lock:
                if child.conn is conn:
                    child.stuck = True
                    self._say(
                        logging.ERROR,
                        "[supervisor] %s did not acknowledge a reclaimed lane ticket within %ss: "
                        "it is hung, restarting it (operation=max_hold, event=unhealthy, error=%s)",
                        child.name,
                        self.reclaim_ack_seconds,
                        exc.code,
                    )
            self._flush_said()
            return
        logger.warning(
            "[supervisor] %s acknowledged a reclaimed lane ticket; not restarted (operation=max_hold)",
            child.name,
        )

    def _ready(self, conn: Connection, args: dict[str, Any]) -> dict[str, Any]:
        try:
            with self._lock:
                child = self._owner(conn.record)
                if child is None or child.conn is not conn:
                    raise BusRefusal(UNKNOWN_STORY)
                if child.ready_sent or child.state != STARTING:
                    # Once per start: a port is never repointed later.
                    self._say(
                        logging.WARNING,
                        "[supervisor] %s sent ready again; refused (operation=ready)",
                        child.name,
                    )
                    raise BusRefusal(BUS_REFUSED)
                child.port = int(args["port"])
                child.ready_sent = True
                child.check_due = 0.0
                self._process_event(child, "ready")
                self._say(
                    logging.INFO,
                    "[supervisor] %s sent ready (operation=ready, pid=%d, port=%d)",
                    child.name,
                    child.pid,
                    child.port,
                )
        finally:
            self._flush_said()
        return {}

    def _submit(self, kind: str, args: dict[str, Any]) -> dict[str, Any]:
        if self.shutting_down.is_set():
            raise BusRefusal(SHUTTING_DOWN)
        slug = str(args.get("slug") or "")
        if self.child(slug) is None:
            raise BusRefusal(UNKNOWN_STORY)
        try:
            # The outcome's audit row is written for the admin the front door
            # named (v0.20.0 T15), its directory captured here, now.
            audit = operation_audit(args)
            name = str(args.get("actor_name") or args.get("actor") or "")
            return {"op_id": self.ops.submit(kind, slug, name, audit=audit)}
        except OperationRefused:
            raise BusRefusal(BUSY) from None

    def _operation_final(self, op: Operation) -> None:
        """An operation is final (the operations thread): its outcome row, on the audit writer's thread."""
        write = audit_operation(op)
        if write is not None:
            self._audit_writer.submit(write)

    # -- metrics (v0.20.0 T17, spec §14.10) ------------------------------------------

    def _open_metrics(self) -> None:
        """
        Open the store, best effort (fix round 1, I2): one that will not open
        is moved aside and made fresh by ``MetricsStore.open``; one that will
        not open even fresh leaves the supervisor running WITHOUT metrics --
        a WARNING and a ``metrics.disabled`` audit row -- never a refused
        start.
        """
        store = self.metrics
        if store is None:
            return
        try:
            store.open()
        except MetricsUnavailable as exc:
            self.metrics = None
            logger.warning(
                "[supervisor] Running without metrics: the store would not open, even fresh "
                "(operation=metrics.open, path=%s, error=%s)",
                store.path,
                exc,
            )
            from engine.hosting import audit

            directory = store.path.parent
            target = store.path.name
            detail = {"error": str(exc)[:64]}

            def write() -> None:
                try:
                    audit.append(
                        "metrics.disabled",
                        actor=audit.SUPERVISOR_ACTOR,
                        result=audit.ERROR,
                        target=target,
                        detail=detail,
                        directory=directory,
                    )
                except audit.AuditUnavailable:
                    pass

            self._audit_writer.submit(write)

    def record(self, event: Mapping[str, Any]) -> None:
        """Keep one metric (validated by the store; never blocks). A no-op with no store."""
        store = self.metrics
        if store is not None:
            store.record(event)

    def record_error(self, fields: Mapping[str, Any]) -> None:
        """The supervisor's own ERROR records (``metrics_emit.ErrorMetricHandler``'s sink)."""
        self.record({"kind": "error", "ts": time.time(), "process": SUPERVISOR_PROCESS, **fields})

    def _metric(self, conn: Connection, args: dict[str, Any]) -> None:
        """
        A child's ``metric`` (the selector thread): its ``process`` and
        ``story`` are the CONNECTION's, whatever it sent (spec §14.2), stamped
        on every kind that has them; the store validates the rest and counts
        what fails.
        """
        store = self.metrics
        if store is None:
            return
        now = time.monotonic()
        bucket = self._metric_buckets.setdefault(conn.id, [self.metric_burst, now])
        bucket[0] = min(self.metric_burst, bucket[0] + (now - bucket[1]) * self.metric_rate)
        bucket[1] = now
        if bucket[0] < 1.0:
            store.count("dropped_rate")
            return
        bucket[0] -= 1.0
        event = dict(args.get("event") or {})
        fields = METRIC_KINDS.get(str(event.get("kind", "")), {})
        if "process" in fields:
            event["process"] = conn.process
        if "story" in fields:
            event["story"] = conn.story
        self.record(event)

    def _lane_event(self, event: Mapping[str, Any]) -> None:
        """One lane ticket's end, from the queue (any thread, no lock held)."""
        self.record({"kind": "lane", **event})

    def _process_event(self, child: Child, event: str, exit_code: Optional[int] = None) -> None:
        """One ``process`` event of ``child`` (the caller may hold ``_lock``: record never waits)."""
        self.record(
            {"kind": "process", "ts": time.time(), "process": child.name, "event": event, "exit_code": exit_code}
        )

    def _metrics_query(self, args: dict[str, Any]) -> dict[str, Any]:
        """``metrics.query {name, params, limit, offset}`` (the fan-out pool): a named query's page."""
        store = self.metrics
        if store is None:
            raise BusRefusal(UNAVAILABLE)
        try:
            return store.query(args["name"], args.get("params") or {}, int(args["limit"]), int(args["offset"]))
        except MetricsQueryError as exc:
            logger.warning("[supervisor] A metrics query was refused (operation=metrics.query, error=%s)", exc.code)
            raise BusRefusal("bad_args") from None

    def _oracle_snapshot(self, args: dict[str, Any]) -> dict[str, Any]:
        """
        ``oracle.snapshot {slug}`` (the fan-out pool): that story's worker's
        Oracle numbers, projected there and held to the projection's keys
        again here (``metrics_schema.clean_projection``).
        """
        slug = str(args["slug"])
        if self.child(slug) is None:
            raise BusRefusal(UNKNOWN_STORY)
        conn = dict(self._serving()).get(slug)
        if conn is None:
            raise BusRefusal(UNAVAILABLE)
        reply = self.server.request(conn, "worker.oracle.snapshot", {}, timeout=FANOUT_SECONDS)
        return {"oracle": clean_projection(reply.get("oracle"))}

    # -- the panel's live sessions (v0.20.0 T15; the fan-out pool) ----------------

    def _deferred(self, work: Callable[[dict[str, Any]], dict[str, Any]]) -> Callable[..., None]:
        """
        A deferred bus handler (selector thread: never blocks) that runs
        ``work(args)`` on the fan-out pool and answers with its result, or
        with the code of the ``BusError`` it raised.
        """

        def handler(_conn: Connection, args: dict[str, Any], answer: Callable[..., None]) -> None:
            if self.shutting_down.is_set():
                raise BusRefusal(SHUTTING_DOWN)
            try:
                self._fanout.submit(self._answer_with, work, args, answer)
            except RuntimeError:  # the pool is shut down: closing
                raise BusRefusal(SHUTTING_DOWN) from None

        return handler

    @staticmethod
    def _answer_with(work: Callable[[dict[str, Any]], dict[str, Any]], args: dict[str, Any], answer: Any) -> None:
        try:
            result = work(args)
        except BusError as exc:
            answer(None, exc.code)
            return
        except Exception:  # noqa: BLE001 -- answered, never left hanging
            logger.exception("[supervisor] A sessions request failed (operation=sessions)")
            answer(None, "internal")
            return
        answer(result, "")

    def _serving(self) -> list[tuple[str, Connection]]:
        """Each worker that answers the panel now, in ``hosting.stories`` order: ``(slug, conn)``."""
        with self._lock:
            return [
                (c.slug, c.conn)
                for c in self.children
                if c.role == WORKER and c.conn is not None and c.ready_sent and c.state in SERVING_STATES
            ]

    def _sessions_list(self, args: dict[str, Any]) -> dict[str, Any]:
        """
        ``sessions.list {limit, offset}``: every serving worker's live sessions
        as ONE list, a page at a time, in story order then each worker's own
        (when each was built). Every worker is asked at once (``request_all``),
        all within one ``FANOUT_SECONDS``: for the first page, each worker's
        first rows; for a later one, each worker's total, then the rows of it
        that the page holds. A worker that does not answer, or answers
        ``too_large``, is an ``errors`` row, never a lost page. Each row is projected to
        ``SESSION_ROW_KEYS`` and stamped with its ``story``.
        """
        want, skip = int(args["limit"]), int(args["offset"])
        deadline = time.monotonic() + FANOUT_SECONDS
        serving = self._serving()
        errors: list[dict[str, str]] = []
        totals: dict[str, int] = {}
        # Fix round 1 (M7): every worker is asked AT ONCE, under one deadline
        # for the whole fan-out. The first page (or a count) is one round:
        # each worker's first rows; a later page needs each worker's total
        # first, to know which of its rows the page holds.
        first = {"limit": want if skip == 0 else 0, "offset": 0}
        answers = self.server.request_all(
            [(conn, "worker.sessions.list", first) for _slug, conn in serving], timeout=FANOUT_SECONDS
        )
        replies: dict[str, dict[str, Any]] = {}
        for (slug, _conn), answer in zip(serving, answers):
            if isinstance(answer, BusError):
                logger.warning(
                    "[supervisor] A worker did not list its sessions (operation=sessions.list, story=%s, error=%s)",
                    slug,
                    answer.code,
                )
                errors.append({"story": slug, "error": answer.code})
                continue
            totals[slug] = int(answer.get("total") or 0)
            replies[slug] = answer
        # Which rows of each worker the page holds: (offset, limit) by story.
        slices: dict[str, tuple[int, int]] = {}
        left, before = want, 0
        for slug, _conn in serving:
            if slug not in totals:
                continue
            start = max(0, skip - before)
            take = max(0, min(left, totals[slug] - start))
            before += totals[slug]
            if take:
                slices[slug] = (start, take)
                left -= take
        if skip and slices:
            second = [(conn, slug) for slug, conn in serving if slug in slices]
            later = self.server.request_all(
                [
                    (conn, "worker.sessions.list", {"offset": slices[slug][0], "limit": slices[slug][1]})
                    for conn, slug in second
                ],
                timeout=max(0.0, deadline - time.monotonic()),
            )
            for (_conn, slug), answer in zip(second, later):
                if isinstance(answer, BusError):
                    errors.append({"story": slug, "error": answer.code})
                    slices.pop(slug, None)
                else:
                    replies[slug] = answer
        rows: list[dict[str, Any]] = []
        for slug, _conn in serving:
            if slug not in slices:
                continue
            got = [r for r in replies[slug].get("rows") or [] if isinstance(r, dict)]
            if not skip:
                got = got[: slices[slug][1]]
            rows += [{"story": slug, **{k: r.get(k) for k in SESSION_ROW_KEYS}} for r in got[: slices[slug][1]]]
        return {"rows": rows, "total": sum(totals.values()), "stories": totals, "errors": errors}

    def _sessions_end(self, args: dict[str, Any]) -> dict[str, Any]:
        """``sessions.end {slug, session_id}``: that story's worker ends it (``busy``, ``not_found``)."""
        slug = str(args["slug"])
        if self.child(slug) is None:
            raise BusRefusal(UNKNOWN_STORY)
        conn = dict(self._serving()).get(slug)
        if conn is None:
            raise BusRefusal(UNAVAILABLE)
        return self.server.request(
            conn, "worker.sessions.end", {"session_id": str(args["session_id"])}, timeout=FANOUT_SECONDS
        )

    def _sessions_end_owner(self, args: dict[str, Any]) -> dict[str, Any]:
        """``sessions.end_owner {account}``: every serving worker ends the account's sessions."""
        ended = busy = 0
        errors: list[dict[str, str]] = []
        serving = self._serving()
        # Every worker at once, under one deadline (fix round 1, M7).
        answers = self.server.request_all(
            [(conn, "worker.sessions.end_owner", {"account": str(args["account"])}) for _slug, conn in serving],
            timeout=FANOUT_SECONDS,
        )
        for (slug, _conn), reply in zip(serving, answers):
            if isinstance(reply, BusError):
                errors.append({"story": slug, "error": reply.code})
                continue
            ended += int(reply.get("ended") or 0)
            busy += int(reply.get("busy") or 0)
        return {"ended": ended, "busy": busy, "errors": errors}

    # -- the main thread ---------------------------------------------------------

    def tick(self) -> None:
        """Look at every child once: crashes, deadlines, due restarts and health checks."""
        now = time.monotonic()
        crashed: list[tuple[Child, str]] = []
        due: list[Child] = []
        with self._lock:
            for child in self.children:
                try:
                    self._tick_one(child, now, crashed, due)
                except Exception as exc:  # noqa: BLE001 -- one child's failure is its own
                    # A respawn that failed (Popen, the capture) is a crash:
                    # retried after the backoff, and held down after
                    # max_restarts of them in the window (T10 fix round 2).
                    self._apply_policy(child, f"could not be started ({type(exc).__name__})")
        self._flush_said()
        self._publish()
        for child, reason in crashed:
            try:
                self._reaper.submit(self._crash, child, reason)
            except RuntimeError:  # shutting down: the shutdown stops it
                pass
        for child in due:
            try:
                self._health.submit(self._check, child)
            except RuntimeError:  # the pool is shut down
                child.checking = False

    def _tick_one(self, child: Child, now: float, crashed: list[tuple[Child, str]], due: list[Child]) -> None:
        if child.stopping or child.applying or child.state in (STOPPED, HELD_DOWN):
            return
        if child.state == RESTARTING:
            if not self.shutting_down.is_set() and now >= child.restart_at:
                self._spawn(child)
            return
        reason = self._crash_reason(child, now)
        if reason:
            child.stopping = True  # claimed: the operations thread leaves it
            crashed.append((child, reason))
            return
        if (
            child.conn is not None
            and child.ready_sent
            and child.state in (STARTING, READY, DEGRADED)
            and not child.checking
            and now >= child.check_due
        ):
            child.checking = True
            due.append(child)

    def _crash_reason(self, child: Child, now: float) -> str:
        code = child.popen.poll() if child.popen is not None else None
        if code is not None:
            return f"exited with code {code}"
        if child.stuck:
            return "hung: a reclaimed lane ticket was not acknowledged"
        if not child.ready_sent and now - child.spawned_at > self.settings.boot_seconds:
            return f"no ready within boot_seconds ({self.settings.boot_seconds})"
        if child.health_failures >= self.settings.health_failures:
            return f"{child.health_failures} failed bus health checks"
        if child.conn is None and child.record is not None and child.record.state == "dead":
            return child.last_reason or "the bus link closed"
        return ""

    def _crash(self, child: Child, reason: str) -> None:
        """On the reaper: stop what is left of a crashed child, then apply the restart policy."""
        try:
            stop_process(child.popen, ask=None, stop_seconds=0.0, name=child.name)
            self._join_capture(child, CAPTURE_JOIN_SECONDS)
        finally:
            with self._lock:
                child.record_exit()
                self._process_event(child, "exited", child.last_exit)
                self._retire(child)
                self._apply_policy(child, reason)
            self._flush_said()

    def _apply_policy(self, child: Child, reason: str) -> None:
        """The restart policy (the caller holds ``_lock``)."""
        child.stopping = False
        child.conn = None
        child.port = 0
        if self.shutting_down.is_set():
            child.state = STOPPED
            return
        now = time.monotonic()
        window = self.settings.restart_window_minutes * 60.0
        while child.crashes and now - child.crashes[0] > window:
            child.crashes.popleft()
        if len(child.crashes) >= self.settings.max_restarts:
            child.state = HELD_DOWN
            child.held_down_at = time.time()
            self._process_event(child, "held_down")
            # The audit row, its values and directory captured NOW (fix round
            # 2, N1), handed to the writer once _lock is released.
            self._audits.append(audit_held_down(child, self.settings.restart_window_minutes))
            self._say(
                logging.ERROR,
                "[supervisor] %s held down: %s after %d crash restarts in %d minutes "
                "(operation=restart, event=held_down)",
                child.name,
                reason,
                len(child.crashes),
                self.settings.restart_window_minutes,
            )
            if child.role == FRONTDOOR:
                self._say(logging.ERROR, "[supervisor] The front door is held down: exiting (operation=restart)")
                self.exit_code = 1
                self.stop_event.set()
            return
        delay = backoff(len(child.crashes))
        child.crashes.append(now)
        child.restart_at = now + delay
        child.state = RESTARTING
        self._process_event(child, "restarted")
        self._say(
            logging.WARNING,
            "[supervisor] %s crashed (%s): restarting in %ds (operation=restart, restarts=%d)",
            child.name,
            reason,
            delay,
            len(child.crashes),
        )

    def _join_capture(self, child: Child, timeout: float) -> None:
        capture = child.capture
        if capture is not None:
            capture.join(max(0.0, timeout))

    # -- health (the pool) -------------------------------------------------------

    def _check(self, child: Child) -> None:
        interval = float(self.settings.health_interval_seconds)
        try:
            conn, port = child.conn, child.port
            bus_ok = conn is not None
            if conn is not None:
                try:
                    answer = self.server.request(conn, "health", timeout=min(HEALTH_TIMEOUT_SECONDS, interval))
                except BusError:
                    bus_ok = False
                else:
                    # The child's own dropped metrics (fix round 1, M6), for the Errors page.
                    store = self.metrics
                    if store is not None and "metrics_dropped" in answer:
                        store.child_dropped(child.name, answer.get("metrics_dropped"))
            http_ok = bool(port) and self._http_ok(port)
            with self._lock:
                if child.stopping or child.conn is not conn or conn is None:
                    return
                self._apply_health(child, bus_ok, http_ok)
        finally:
            with self._lock:
                child.checking = False
                child.check_due = time.monotonic() + interval
            self._flush_said()

    def _apply_health(self, child: Child, bus_ok: bool, http_ok: bool) -> None:
        """One check's result (the caller holds ``_lock``)."""
        if bus_ok:
            child.health_failures = 0
        else:
            child.health_failures += 1
            self._say(
                logging.WARNING,
                "[supervisor] %s failed a bus health check (operation=health, failures=%d)",
                child.name,
                child.health_failures,
            )
        if child.state == STARTING and bus_ok:
            child.state = READY if http_ok else DEGRADED
            self._say(
                logging.INFO,
                "[supervisor] %s is %s (operation=health, pid=%d, port=%d)",
                child.name,
                child.state,
                child.pid,
                child.port,
            )
        elif child.state == READY and not http_ok:
            child.state = DEGRADED
            self._process_event(child, "unhealthy")
            self._say(
                logging.WARNING,
                "[supervisor] %s is degraded: its HTTP health check failed; not restarted "
                "(operation=health, event=unhealthy)",
                child.name,
            )
        elif child.state == DEGRADED and http_ok:
            child.state = READY
            self._say(logging.INFO, "[supervisor] %s is ready again (operation=health)", child.name)

    def _http_ok(self, port: int) -> bool:
        try:
            response = self._http.get(f"http://127.0.0.1:{int(port)}/api/health")
        except Exception:  # noqa: BLE001 -- any failure is a failed check
            return False
        return response.status_code == 200

    # -- operations (the operations thread) ---------------------------------------

    def _perform(self, op: Operation, step: Any) -> None:
        if op.kind == "llm.apply":
            self.llm.perform(op, step)
            return
        child = self.child(op.slug)
        if child is None:
            op.reason = UNKNOWN_STORY
            step(REFUSED)
            return
        with self._lock:
            state = child.state
            if op.kind == "stories.start" and state not in (STOPPED, HELD_DOWN):
                op.reason = "the story is already running"
            elif op.kind == "stories.stop" and state == STOPPED:
                op.reason = "the story is not running"
            elif child.stopping:
                op.reason = "the story is restarting after a crash"
            if not op.reason:
                child.stopping = True
        if op.reason:
            step(REFUSED)
            return
        drained = False
        try:
            if op.kind != "stories.start" and state in (READY, DEGRADED) and child.conn is not None:
                drained = child.role == WORKER
                step(OP_DRAINING)
                with self._lock:
                    child.state = DRAINING
                if not self._drain(child, float(self.settings.drain_seconds)):
                    with self._lock:
                        if child.state == DRAINING:
                            child.state = state
                    op.reason = DRAIN_REFUSED
                    step(REFUSED)
                    return
            if op.kind != "stories.stop":
                step(OP_RESTARTING)
            self._stop(child, float(self.settings.stop_seconds))
            # The old connection's tickets and waits went with it; the new
            # worker queues as any other (a stopped story has nothing queued).
            self.queue.resume(child.slug)
            drained = False
            with self._lock:
                child.state = STOPPED
                if op.kind != "stories.stop" and not self.shutting_down.is_set():
                    # A restart an admin chose does not count, and does not
                    # forgive: the crash history is kept, unless this revives
                    # a held-down child (spec §14.3; T10 fix round 1).
                    if state == HELD_DOWN:
                        child.crashes.clear()
                    self._spawn(child)
            self._flush_said()
            step(DONE)
        finally:
            if drained:
                # A drain paused (and perhaps closed) the story, and the stop
                # after it raised: never leave it refusing every turn (T11
                # fix round 1). A refused drain resumed it already.
                self.queue.resume(child.slug)
            with self._lock:
                child.stopping = False

    def _drain(self, child: Child, seconds: float) -> bool:
        """
        Spec §14.3, through the queue (v0.20.0 T11): pause the story's new
        narration admissions, and wait -- at most ``seconds`` -- until it
        holds no lane ticket, which an admitted turn reaches in its own time
        (its utility calls are still granted, so nothing it waits on is
        paused). Then its waiters are answered busy (they never started) and
        the worker is asked to let the requests it is still answering finish
        (the bus ``drain``). False when it does not finish, and the story is
        resumed: if the wait for its tickets ran out, nothing changed (its
        waiters keep their places); if the worker's own drain then failed,
        the waiters were already answered busy -- nothing lost, as they never
        started, but they are gone from the line.
        """
        deadline = time.monotonic() + max(0.0, seconds)
        slug = child.slug if child.role == WORKER else ""
        if slug:
            self.queue.pause(slug)
            if not self.queue.wait_until_idle(slug, seconds):
                self.queue.resume(slug)
                logger.warning(
                    "[supervisor] %s did not drain: a lane ticket is still held; resumed "
                    "(operation=drain, held=%d)",
                    child.name,
                    self.queue.held(slug),
                )
                return False
            refused = self.queue.close_story(slug)
            logger.info(
                "[supervisor] Drained %s: it holds no lane ticket (operation=drain, refused=%d)",
                child.name,
                refused,
            )
        conn = child.conn
        if conn is None:
            return True
        left = max(0.0, deadline - time.monotonic())
        try:
            result = self.server.request(conn, "drain", {"seconds": left}, timeout=left + DRAIN_MARGIN_SECONDS)
        except BusError as exc:
            logger.warning("[supervisor] %s did not drain (operation=drain, error=%s)", child.name, exc.code)
            result = {}
        if result.get("drained"):
            return True
        if slug:
            self.queue.resume(slug)
        return False

    def _stop(self, child: Child, stop_seconds: float, *, grace: float = TERMINATE_GRACE_SECONDS,
              kill_wait: float = KILL_WAIT_SECONDS, join: float = CAPTURE_JOIN_SECONDS) -> str:
        conn = child.conn

        def ask() -> None:
            if conn is not None:
                self.server.request(conn, "shutdown", timeout=max(0.0, min(SHUTDOWN_ASK_SECONDS, stop_seconds)))

        how = stop_process(
            child.popen,
            ask=ask if conn is not None else None,
            stop_seconds=stop_seconds,
            name=child.name,
            grace=grace,
            kill_wait=kill_wait,
        )
        self._join_capture(child, join)
        with self._lock:
            child.record_exit()
            self._process_event(child, "stopped", child.last_exit)
            self._retire(child)
        logger.info("[supervisor] Stopped %s (operation=stop, how=%s)", child.name, how)
        return how

    # -- shutdown ----------------------------------------------------------------

    def shutdown(self) -> None:
        """
        Drain and stop everything, and release the threads, within
        ``shutdown_seconds``: each worker gets what is left of it, less the
        front door's reserve, for its drain, then its stop, then the
        terminate grace and the kill's wait; then the front door is stopped
        in the reserve (``hosting.supervisor.shutdown_seconds`` is checked to
        hold all five).
        """
        if self.shutting_down.is_set():
            return
        self.shutting_down.set()
        total = float(self.settings.shutdown_seconds)
        deadline = time.monotonic() + total
        logger.info("[supervisor] Shutting down (operation=shutdown, within=%ds)", int(total))
        with self._lock:
            running = []
            for child in self.children:
                child.stopping = True
                if child.alive():
                    running.append(child)

        def left() -> float:
            return max(0.0, deadline - time.monotonic())

        tail = float(TERMINATE_GRACE_SECONDS + KILL_WAIT_SECONDS)
        # THE FRONT DOOR LAST (T18 fix round 1): the workers drain and stop
        # first, together, inside the shutdown less the front door's reserve;
        # only then is the front door stopped, so a turn drained to its end
        # reaches its player through the relay before the relay closes.
        door = [child for child in running if child.role == FRONTDOOR]
        workers = [child for child in running if child.role != FRONTDOOR]
        reserve = float(FRONTDOOR_STOP_RESERVE_SECONDS) if door else 0.0

        def one(child: Child, until: Callable[[], float]) -> None:
            stop_for = min(float(self.settings.stop_seconds), max(0.0, until() - tail))
            if child.state in (READY, DEGRADED) and child.conn is not None:
                self._drain(child, min(float(self.settings.drain_seconds), max(0.0, until() - stop_for - tail)))
            stop_for = min(stop_for, max(0.0, until() - tail))
            grace = min(float(TERMINATE_GRACE_SECONDS), max(0.0, until() - KILL_WAIT_SECONDS))
            self._stop(child, stop_for, grace=grace, kill_wait=min(KILL_WAIT_SECONDS, until()), join=min(1.0, until()))

        def before_door() -> float:
            return max(0.0, left() - reserve)

        pool: Optional[ThreadPoolExecutor] = None
        if workers:
            pool = ThreadPoolExecutor(max_workers=len(workers), thread_name_prefix="supervisor-stop")
            futures = [pool.submit(one, child, before_door) for child in workers]
            for future in futures:
                try:
                    future.result(timeout=before_door() + 1.0)
                except Exception:  # noqa: BLE001 -- the deadline, or a stop that failed
                    pass
        for child in door:
            try:
                one(child, left)
            except Exception:  # noqa: BLE001 -- a stop that failed; the deadline's kill below
                logger.exception("[supervisor] The front door's stop failed (operation=shutdown)")
        for child in self.children:
            if child.alive():
                logger.error("[supervisor] Killing %s at the shutdown deadline (operation=shutdown)", child.name)
                try:
                    child.popen.kill()  # type: ignore[union-attr]
                    child.popen.wait(min(KILL_WAIT_SECONDS, max(0.1, left())))  # type: ignore[union-attr]
                except Exception:  # noqa: BLE001
                    pass
            with self._lock:
                child.state = STOPPED
        if pool is not None:
            pool.shutdown(wait=False, cancel_futures=True)
        self.close(timeout=left())
        logger.info("[supervisor] Shut down (operation=shutdown)")

    def close(self, timeout: float = 5.0) -> None:
        """Release the threads, the bus and the HTTP client, within ``timeout``."""
        deadline = time.monotonic() + max(0.0, timeout)

        def left() -> float:
            return max(0.0, deadline - time.monotonic())

        self.ops.close(timeout=left())
        self.queue.close(timeout=left())
        self._fanout.shutdown(wait=False, cancel_futures=True)
        self._health.shutdown(wait=False, cancel_futures=True)
        self._reaper.shutdown(wait=False, cancel_futures=True)
        self.server.close(timeout=left())
        self._audit_writer.close(timeout=left())
        if self.metrics is not None:
            self.metrics.close(timeout=max(1.0, left()))  # what is queued is written, briefly
        if self._http is not None:
            self._http.close()
        for child in self.children:
            self._join_capture(child, left())


__all__ = [
    "DEFAULT_FRONTDOOR_MODULE",
    "DEFAULT_WORKER_MODULE",
    "DRAIN_REFUSED",
    "Supervisor",
    "TICK_SECONDS",
]
