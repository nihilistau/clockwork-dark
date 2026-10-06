"""
The Supervisor's Children
=========================

One ``Child`` is one process the supervisor runs: a worker for one story
(``worker-<slug>``), or the front door (spec §14.3). It holds the command,
the token record of its CURRENT start, its state and its restart history.
One worker process per story: more than one is NOT WIRED (docs/GOVERNANCE.md),
and so are memory and CPU figures per process.

THE COMMAND is built from ``sys.executable`` and ``-m``, never a shell and
never a hardcoded path (``child_command``, v0.20.0 T13): on POSIX with
gunicorn installed (``gunicorn_runs_here``), ``python -m gunicorn -c
deploy/gunicorn.conf.py <wsgi>:app`` with the role's WSGI module
(``engine.hosting.wsgi`` or ``engine.hosting.frontdoor.wsgi``); otherwise
(Windows, or gunicorn absent) ``python -u -m engine.hosting.boot --role
worker|frontdoor``, Werkzeug with spec §7.2's WARNING. Under gunicorn the
process started is the MASTER and the bus link is its gunicorn worker's: a
link that closes (gunicorn restarting its worker) is the child down, so the
master is stopped and started again with a fresh token, and the respawned
worker's ``hello`` is refused (the token is single-use). Its
environment is the supervisor's own plus ``CLOCKWORK_BUS_ADDR``,
``CLOCKWORK_BUS_TOKEN``, ``CLOCKWORK_BUS_ROLE`` (a boot hint, never trusted
by the supervisor), ``CLOCKWORK_PROXY_TOKEN`` (v0.20.0 T12: the front door's
proxy token, minted once per supervisor start and the same for every child)
and, for a worker, ``CLOCKWORK_GAME``. The tokens reach
the child there and nowhere else: never argv, a file or a log line. (The
child deletes them from ``os.environ`` once read, which keeps them from its
own children; on Linux the starting environment stays readable in
``/proc/<pid>/environ`` to the same user and root, docs/HOSTING.md.) A child
runs from the repository root (``python -m`` puts the working directory first
on ``sys.path``, so the operator's must never shadow the engine), and its
boot ignores Ctrl+Break, which reaches every process on a Windows console:
the supervisor drains and stops it instead.

EACH CHILD IN ITS OWN PROCESS GROUP (``start_new_session=True`` on POSIX,
``CREATE_NEW_PROCESS_GROUP`` on Windows): Ctrl+C reaches a whole console
group, and SIGINT a whole foreground group, so without this every child would
die under the supervisor's feet instead of being drained by it.

STATES: ``starting`` -> ``ready`` (after ``ready`` and a first passing health
check) -> ``draining`` -> ``stopped``; ``degraded`` (the HTTP check failing,
the bus fine); ``restarting`` (waiting out its backoff); ``held_down`` (too
many crashes in the window, restarted only by an admin or a supervisor
restart). A hold-down is also written to the audit log as ``story.held_down``
by the actor ``supervisor`` (``audit_held_down``, v0.20.0 T14).

STOPPING is over the bus first (``shutdown``), then ``terminate()``, then
``kill()``; no POSIX-only signal is ever sent to a child, so the same path
works on Windows.

Version: v0.6.0 [2026-10-06]
"""

from __future__ import annotations

import collections
import logging
import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Deque, Mapping, Optional

from engine.hosting.bus import (
    BUS_ADDR_ENV,
    BUS_ROLE_ENV,
    BUS_TOKEN_ENV,
    FRONTDOOR,
    PROXY_TOKEN_ENV,
    WORKER,
    TokenRecord,
)
from engine.hosting.config import KILL_WAIT_SECONDS, TERMINATE_GRACE_SECONDS

logger = logging.getLogger(__name__)

STARTING = "starting"
READY = "ready"
DEGRADED = "degraded"
DRAINING = "draining"
STOPPED = "stopped"
RESTARTING = "restarting"
HELD_DOWN = "held_down"

#: States in which the child's process is meant to be running.
RUNNING_STATES = frozenset({STARTING, READY, DEGRADED, DRAINING})

#: The restart backoff, by crash restarts so far in the window (spec §14.3).
BACKOFF_SECONDS = (1, 2, 4, 8, 16, 32, 60)

#: The environment variable naming a worker's story.
GAME_ENV = "CLOCKWORK_GAME"

#: Environment variables gunicorn reads over (or under) deploy/gunicorn.conf.py,
#: never passed to a child (T13 fix round 1, I3): ``GUNICORN_CMD_ARGS``
#: overrides the conf for every child (a worker rebound off loopback, the
#: forwarded-header trust widened, a worker recycled), and ``WEB_CONCURRENCY``
#: is a default the conf already sets.
GUNICORN_OVERRIDE_ENV = frozenset({"GUNICORN_CMD_ARGS", "WEB_CONCURRENCY"})


def backoff(restarts: int) -> int:
    """The wait before restart number ``restarts + 1`` in the window."""
    return BACKOFF_SECONDS[min(max(0, restarts), len(BACKOFF_SECONDS) - 1)]


def build_command(module: str, role: str) -> list[str]:
    """``[sys.executable, "-u", "-m", module, "--role", role]``: never a shell."""
    return [sys.executable, "-u", "-m", module, "--role", role]


#: The gunicorn configuration every gunicorn child runs with (spec §7.1).
GUNICORN_CONF = Path(__file__).resolve().parents[3] / "deploy" / "gunicorn.conf.py"

#: The WSGI module each role serves under gunicorn (``<module>:app``).
DEFAULT_WSGI = {WORKER: "engine.hosting.wsgi", FRONTDOOR: "engine.hosting.frontdoor.wsgi"}


def gunicorn_runs_here() -> bool:
    """
    Whether gunicorn can serve on this machine: its package importable AND
    its server (``gunicorn.arbiter``, which needs ``fcntl``) importable. On
    Windows the second never is, installed or not, so the supervisor runs the
    boot runner there; on POSIX without gunicorn, likewise (spec §14.3).
    """
    import importlib
    import importlib.util

    try:
        if importlib.util.find_spec("gunicorn") is None:
            return False
        importlib.import_module("gunicorn.arbiter")
    except Exception:  # noqa: BLE001 -- anything but a clean import means "not here"
        return False
    return True


def gunicorn_command(wsgi: str) -> list[str]:
    """``[sys.executable, "-m", "gunicorn", "-c", <deploy/gunicorn.conf.py>, "<wsgi>:app"]``: never a shell."""
    return [sys.executable, "-m", "gunicorn", "-c", str(GUNICORN_CONF), f"{wsgi}:app"]


def child_command(module: str, role: str, wsgi: str = "", *, gunicorn: Optional[bool] = None) -> list[str]:
    """
    The command a child runs: under gunicorn when it has a ``wsgi`` module and
    gunicorn runs here (``gunicorn_runs_here``), else the boot runner
    (``python -m <module> --role <role>``, Werkzeug, with spec §7.2's WARNING).
    """
    use = gunicorn_runs_here() if gunicorn is None else gunicorn
    if wsgi and use:
        return gunicorn_command(wsgi)
    return build_command(module, role)


def child_env(
    base: Mapping[str, str],
    *,
    addr: str,
    token: str,
    role: str,
    slug: str = "",
    proxy_token: str = "",
) -> dict[str, str]:
    """
    The supervisor's environment plus the bus variables, the proxy token
    (when one is given) and, for a worker, ``CLOCKWORK_GAME``. Any bus or
    proxy variable the supervisor itself inherited is replaced, never passed
    on; ``GUNICORN_OVERRIDE_ENV`` (``GUNICORN_CMD_ARGS``, ``WEB_CONCURRENCY``)
    is dropped, so nothing in the operator's environment overrides
    deploy/gunicorn.conf.py.
    """
    env = {
        k: v
        for k, v in base.items()
        if k not in (BUS_ADDR_ENV, BUS_TOKEN_ENV, BUS_ROLE_ENV, PROXY_TOKEN_ENV, GAME_ENV)
        and k not in GUNICORN_OVERRIDE_ENV
    }
    env[BUS_ADDR_ENV] = addr
    env[BUS_TOKEN_ENV] = token
    env[BUS_ROLE_ENV] = role
    if proxy_token:
        env[PROXY_TOKEN_ENV] = proxy_token
    if role == WORKER:
        env[GAME_ENV] = slug
    return env


def audit_held_down(child: "Child", window_minutes: int) -> Callable[[], None]:
    """
    The ``story.held_down`` audit row (actor ``supervisor``, spec §14.3,
    §14.11), as a write for the ``AuditWriter``'s thread, queued beside the
    ``held_down`` log line (``Supervisor._apply_policy``) and handed over once
    the supervisor's lock is released (``_flush_said``). Target: the story's
    slug (or the front door's name); detail: the crash restarts and the window.

    EVERYTHING IS CAPTURED NOW, on the queuing thread (T14 fix round 2, N1):
    the row's values AND the audit directory (``storage.hosting_dir()``,
    which reads ``CLOCKWORK_DATA_DIR`` or ``storage.root``). Resolved later
    on the writer's thread, the directory followed whatever the environment
    said by then -- in the suite, after a test's own storage redirect had been
    undone, the owner's real ``data/hosting/``.

    Nothing is refused for want of the row -- the child is already held down
    -- so one that cannot be written is logged (by ``audit.append``) and left.
    """
    from engine.hosting import audit
    from engine.persistence.storage import hosting_dir

    directory = hosting_dir()
    target = child.slug or child.name
    detail = {"crash_restarts": len(child.crashes), "window_minutes": int(window_minutes)}

    def write() -> None:
        try:
            audit.append(
                "story.held_down",
                actor=audit.SUPERVISOR_ACTOR,
                result=audit.OK,
                target=target,
                detail=detail,
                directory=directory,
            )
        except audit.AuditUnavailable:
            pass

    return write


#: The audit action of each story operation (spec §14.11).
STORY_ACTIONS = (("stories.start", "story.start"), ("stories.stop", "story.stop"), ("stories.restart", "story.restart"))


def operation_audit(args: Mapping[str, Any]) -> Optional[dict[str, Any]]:
    """
    Whom a story operation's outcome row is for (v0.20.0 T15), from the bus
    arguments the front door sent (``actor``, ``actor_name``, ``address``,
    ``ref``), and the audit directory, CAPTURED NOW, on the queuing thread
    (T14 fix round 2, N1's lesson). None when the front door named no actor
    and no ``ref`` (no ``started`` row was written, so no outcome is).
    """
    from engine.persistence.storage import hosting_dir

    actor, ref = str(args.get("actor") or ""), str(args.get("ref") or "")
    if not actor or not ref:
        return None
    return {
        "actor": actor,
        "actor_name": str(args.get("actor_name") or ""),
        "address": str(args.get("address") or ""),
        "ref": ref,
        "directory": hosting_dir(),
    }


def audit_operation(op: Any) -> Optional[Callable[[], None]]:
    """
    The outcome row of a final story operation (``ok`` when ``done``,
    ``refused`` otherwise) under the ``ref`` of the front door's ``started``
    row, as a write for the ``AuditWriter``'s thread; None when the operation
    carries no audit (``operation_audit``). Detail: the op id and, when
    refused, its fixed reason.
    """
    from engine.hosting import audit

    info = getattr(op, "audit", None)
    action = dict(STORY_ACTIONS).get(str(op.kind))
    if not info or action is None:
        return None
    result = audit.OK if op.status == "done" else audit.REFUSED
    detail: dict[str, Any] = {"op_id": str(op.op_id)}
    if result != audit.OK and op.reason:
        detail["reason"] = str(op.reason)[: audit.MAX_TEXT]
    actor = audit.Actor(info["actor"], info["actor_name"], info["address"])

    def write() -> None:
        try:
            audit.append(
                action,
                actor=actor,
                result=result,
                target=str(op.slug),
                detail=detail,
                ref=info["ref"],
                directory=info["directory"],
            )
        except audit.AuditUnavailable:
            pass  # logged by append; the started row stands
        except audit.AuditRowError:
            logger.error("[supervisor] An operation's outcome row was malformed (operation=audit, op_id=%s)", op.op_id)

    return write


class AuditWriter:
    """
    The supervisor's audit rows, written on a thread of their own (T14 fix
    round 1, M6): ``submit`` puts a write on a bounded queue and returns at
    once, so a bus handler that flushes the supervisor's queued messages
    (``Supervisor._flush_said``) never waits on the audit lock or an
    ``fsync``. The thread (``supervisor-audit``) starts with the first
    submission and is joined by ``close``; a full queue drops the row and
    logs it (the event's log line stands).

    Thread-safe: ``queue.Queue``, and one leaf lock for the thread's start.
    """

    #: Rows waiting at most; past it a row is dropped and logged.
    MAX_WAITING = 256

    def __init__(self) -> None:
        import queue

        self._queue: Any = queue.Queue(maxsize=self.MAX_WAITING)
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._closed = False

    def submit(self, write: Callable[[], None]) -> None:
        """Hand ``write`` to the writer thread; never blocks."""
        import queue

        fresh: Optional[threading.Thread] = None
        with self._lock:
            if self._closed:
                return
            if self._thread is None:
                fresh = self._thread = threading.Thread(target=self._drain, name="supervisor-audit", daemon=True)
        if fresh is not None:
            # Started with the leaf released (v0.20.0 T15): a thread's start
            # waits on the new thread, and nothing waits under a leaf.
            fresh.start()
        try:
            self._queue.put_nowait(write)
        except queue.Full:
            logger.error("[supervisor] An audit row was dropped: its queue is full (operation=audit)")

    def _drain(self) -> None:
        while True:
            write = self._queue.get()
            if write is None:
                return
            try:
                write()
            except Exception:  # noqa: BLE001 -- one row's failure must not end the writer
                logger.exception("[supervisor] An audit row failed (operation=audit)")

    def close(self, timeout: float = 5.0) -> None:
        """Write what is queued, then stop the thread (within ``timeout``)."""
        with self._lock:
            self._closed = True
            thread = self._thread
        if thread is None:
            return
        try:
            self._queue.put(None, timeout=max(0.0, timeout))
        except Exception:  # noqa: BLE001 -- a full queue: the daemon thread ends with the process
            return
        try:
            thread.join(max(0.0, timeout))
        except RuntimeError:
            pass  # built by a submit still starting it: it drains the queue, None last, and ends


def group_kwargs() -> dict[str, Any]:
    """``Popen`` keywords that start a child in its own process group."""
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


@dataclass
class Child:
    """One supervised process and what the supervisor knows of it."""

    role: str
    slug: str
    module: str
    #: The WSGI module it serves under gunicorn (``<wsgi>:app``), or "" for
    #: the boot runner only (a test probe's runner, v0.20.0 T13).
    wsgi: str = ""
    state: str = STOPPED
    #: The argv of its current start (logged; it carries no secret).
    command: list[str] = field(default_factory=list)
    popen: Optional[subprocess.Popen] = None
    record: Optional[TokenRecord] = field(default=None, repr=False)
    conn: Any = None
    port: int = 0
    spawned_at: float = 0.0
    ready_sent: bool = False
    #: Monotonic times of the crash restarts counted toward ``max_restarts``.
    crashes: Deque[float] = field(default_factory=collections.deque)
    restart_at: float = 0.0
    health_failures: int = 0
    check_due: float = 0.0
    checking: bool = False
    #: A deliberate stop is under way: an exit is not a crash.
    stopping: bool = False
    #: A model apply owns this child's restart (v0.20.0 T16): the main
    #: thread leaves it alone -- no crash detection, no health checks, no
    #: respawn -- while the operations thread boots it under the new admin
    #: layer and waits for it to be ready (or rolls back). Never a crash.
    applying: bool = False
    capture: Any = None
    last_reason: str = ""
    #: It held a lane ticket past ``max_hold_seconds`` (v0.20.0 T11): a crash
    #: restart is due.
    stuck: bool = False
    #: When its current process started (wall time), for the Stories page's
    #: uptime (v0.20.0 T15).
    started_at: float = 0.0
    #: Its last process's exit code (None: it has not exited, or it was
    #: killed with no code) and when (wall time), and when it was last held
    #: down: the Stories page shows them (spec §14.8).
    last_exit: Optional[int] = None
    last_exit_at: float = 0.0
    held_down_at: float = 0.0

    def record_exit(self) -> None:
        """Note the exit code of the process just stopped or reaped, and when."""
        code = self.popen.poll() if self.popen is not None else None
        if code is not None:
            self.last_exit = int(code)
            self.last_exit_at = time.time()

    @property
    def name(self) -> str:
        return FRONTDOOR if self.role == FRONTDOOR else f"worker-{self.slug}"

    @property
    def pid(self) -> int:
        return self.popen.pid if self.popen is not None else 0

    def alive(self) -> bool:
        return self.popen is not None and self.popen.poll() is None

    def row(self, window_seconds: float, now: float) -> dict[str, Any]:
        """
        The story table's row: metadata only (spec §14.10). ``uptime``
        (seconds, v0.20.0 T15) counts while its process runs; ``last_exit``,
        ``last_exit_at`` and ``held_down_at`` (wall time, 0 for never) are the
        Stories page's.
        """
        alive = self.alive()
        return {
            "slug": self.slug,
            "process": self.name,
            "role": self.role,
            "state": self.state,
            "port": self.port,
            "pid": self.pid if alive else 0,
            "restarts": sum(1 for t in self.crashes if now - t <= window_seconds),
            "uptime": round(max(0.0, time.time() - self.started_at), 1) if alive and self.started_at else 0.0,
            "last_exit": self.last_exit,
            "last_exit_at": round(self.last_exit_at, 3),
            "held_down_at": round(self.held_down_at, 3),
        }

    def spawn(
        self,
        *,
        addr: str,
        record: TokenRecord,
        environ: Mapping[str, str],
        cwd: Optional[str] = None,
        proxy_token: str = "",
    ) -> subprocess.Popen:
        """
        Start the process for ``record`` (this start's token). ``cwd`` is the
        repository root (``python -m`` puts the working directory first on
        ``sys.path``, so it is never the operator's own: T10 fix round 1).
        ``proxy_token`` is the supervisor's (spec §14.5).
        """
        env = child_env(
            environ,
            addr=addr,
            token=record.token,
            role=self.role,
            slug=self.slug,
            proxy_token=proxy_token,
        )
        self.command = child_command(self.module, self.role, self.wsgi)
        self.popen = subprocess.Popen(  # noqa: S603 -- sys.executable and -m, no shell
            self.command,
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            **group_kwargs(),
        )
        del env
        self.record = record
        self.conn = None
        self.port = 0
        self.ready_sent = False
        self.health_failures = 0
        self.checking = False
        self.stuck = False
        self.spawned_at = time.monotonic()
        self.started_at = time.time()
        self.state = STARTING
        return self.popen


def stop_process(
    popen: Optional[subprocess.Popen],
    *,
    ask: Optional[Callable[[], None]],
    stop_seconds: float,
    name: str,
    grace: float = TERMINATE_GRACE_SECONDS,
    kill_wait: float = KILL_WAIT_SECONDS,
) -> str:
    """
    Stop ``popen``: ``ask()`` (the bus ``shutdown``), wait ``stop_seconds``,
    then ``terminate()``, wait ``grace``, then ``kill()`` and wait
    ``kill_wait``. Answers how it ended: ``exited``, ``terminated`` or
    ``killed``.
    """
    if popen is None or popen.poll() is not None:
        return "exited"
    if ask is not None:
        try:
            ask()
        except Exception:  # noqa: BLE001 -- a child that cannot answer is terminated
            logger.info("[supervisor] %s did not take the bus shutdown (operation=stop)", name)
        try:
            popen.wait(max(0.0, stop_seconds))
            return "exited"
        except subprocess.TimeoutExpired:
            pass
    logger.warning("[supervisor] Terminating %s (operation=stop, pid=%d)", name, popen.pid)
    try:
        popen.terminate()
    except OSError:
        pass
    try:
        popen.wait(max(0.0, grace))
        return "terminated"
    except subprocess.TimeoutExpired:
        pass
    logger.error("[supervisor] Killing %s (operation=stop, pid=%d)", name, popen.pid)
    try:
        popen.kill()
    except OSError:
        pass
    try:
        popen.wait(max(0.0, kill_wait))
    except subprocess.TimeoutExpired:
        logger.error("[supervisor] %s did not die (operation=stop, pid=%d)", name, popen.pid)
    return "killed"


__all__ = [
    "BACKOFF_SECONDS",
    "Child",
    "DEGRADED",
    "DRAINING",
    "GAME_ENV",
    "HELD_DOWN",
    "READY",
    "RESTARTING",
    "RUNNING_STATES",
    "STARTING",
    "STOPPED",
    "DEFAULT_WSGI",
    "GUNICORN_CONF",
    "GUNICORN_OVERRIDE_ENV",
    "AuditWriter",
    "STORY_ACTIONS",
    "audit_held_down",
    "audit_operation",
    "operation_audit",
    "backoff",
    "build_command",
    "child_command",
    "child_env",
    "gunicorn_command",
    "gunicorn_runs_here",
    "group_kwargs",
    "stop_process",
]
