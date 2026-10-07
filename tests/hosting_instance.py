"""
A real hosted instance, for the orchestration tests (v0.20.0 T10; spec §9.10).

``HostingInstance`` starts ``python -m engine.hosting.supervisor`` as a real
process, with:

- the test's own ``CLOCKWORK_CONFIG`` file, written under its ``tmp_path``
  (hosting on, ``hosting.stories``, short supervisor durations). The suite's
  ``Popen`` wrapper keeps it and puts the sandbox layer after it (spec §3.5),
  so the supervisor and every child it starts are sandboxed children of the
  suite: ``config/local.yaml`` unread, the model server on the discard port;
- ``CLOCKWORK_DATA_DIR`` under ``tmp_path``, so the cookie key, the logs and
  anything else land there;
- ``tests/probes/fake_worker.py`` as every worker (``--worker-module``) and,
  by default, as the front door (``--frontdoor-module``), whose ``POST
  /bus`` relay is how a test calls the front-door-only ops (``call``) until
  the real front door (T12).

It reads the supervisor's merged output on a thread (``lines``,
``wait_for``), waits for every child's ``ready`` through ``stories.list``,
and stops everything in ``stop`` (also its ``__exit__``): the supervisor's
own shutdown (Ctrl+Break on Windows, SIGTERM on POSIX), then
``terminate()``, then ``kill()``, each with a timeout; then it waits for
every child pid the probes reported to be gone, and kills and fails on any
that is not. Every child binds loopback on an OS-picked port.

``hosting_instance(tmp_path_factory, ...)`` is the factory a module-scoped
fixture calls, so one instance serves a whole test file (spec §9.10's time
budget); a test that needs a fresh one says why.

``worker_module=LANE_CLIENT`` (T11) runs ``tests/probes/lane_client.py`` as
every worker instead, which ``tell`` commands to acquire and release lane
tickets; ``extra`` adds top-level config blocks (``llm.lanes``).

THE FRONT DOOR (v0.20.0 T12). ``frontdoor`` is ``True`` (the fake front door
above), ``False`` (none: the supervisor's ``--no-frontdoor``) or ``"real"``:
the engine's own front door, run by ``tests/probes/frontdoor_relay.py``, whose
side port relays ``call`` to the bus. ``worker_module=SCRIPTED_WORKER`` runs
``tests/probes/scripted_worker.py``, the engine's real hosted worker with a
scripted model. ``add_account`` makes an account in the instance's
``users.json``; ``http()`` is an ``httpx.Client`` on the front door (its cookie
jar is the login) and ``login``/``choose`` drive the front door's forms;
``proxied(process)`` reads what a scripted worker was sent through the front
door. The config always binds the front door to ``127.0.0.1`` on a port the
OS picks (``scene.clockwork.port: 0``).

UNDER GUNICORN (v0.20.0 T13). Where gunicorn runs (the Linux container,
CI), the supervisor serves the scripted worker and the real front door with
gunicorn (``--worker-wsgi`` / ``--frontdoor-wsgi`` name the probes' lazily
built ``app``), so the same tests prove both servers; the fake worker and the
lane client run as themselves everywhere.

``AdminDoor`` (v0.20.0 T14) is the engine's front door alone in THIS process,
with a stand-in worker that only counts what reaches it, for the admin
panel's tests (Flask's test client, no story activated).

``InProcessFrontDoor`` is the same shape in THIS process, for the tests that
look inside (the forwarded headers a worker saw, the timeouts the proxy hands
``httpx``): one hosted worker and the front door, each served by Werkzeug on
a thread on an OS-picked loopback port, over a real loopback bus whose
supervisor side (``stories.list``, ``stories.changed``, the lanes) is played
here.

Version: v0.4.0 [2026-10-05]
"""

from __future__ import annotations

import json
import os
import re
import secrets
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Iterator, Optional

import httpx
import yaml

REPO = Path(__file__).resolve().parents[1]

#: What the probe children run.
FAKE_WORKER = "tests.probes.fake_worker"
#: A worker that only queues, on command (v0.20.0 T11).
LANE_CLIENT = "tests.probes.lane_client"
#: The engine's real hosted worker with a scripted model (v0.20.0 T12).
SCRIPTED_WORKER = "tests.probes.scripted_worker"
#: The engine's real front door, with the suite's bus relay beside it (T12).
FRONTDOOR_RELAY = "tests.probes.frontdoor_relay"

#: The fake worker's control-directory variable (``tests/probes/fake_worker.py``).
CONTROL_ENV = "CLOCKWORK_FAKE_WORKER_DIR"

#: Short supervisor durations: a test waits seconds, not minutes.
FAST_SUPERVISOR = {
    "health_interval_seconds": 1,
    "health_failures": 2,
    "boot_seconds": 3,
    "max_restarts": 2,
    "restart_window_minutes": 10,
    "drain_seconds": 2,
    "stop_seconds": 2,
    "shutdown_seconds": 21,  # >= drain + stop + 7 + the front door's 10 (config.py's cross-check, T18)
}

#: ``HostingInstance.call``: the ops that only read, so may be sent again when
#: their answer is lost; how many attempts; how long one connect may take.
READ_OPS = frozenset({"ops.list", "stories.list", "queue.snapshot", "sessions.list"})
CALL_ATTEMPTS = 3
CALL_CONNECT_SECONDS = 5.0


def ready_seconds() -> float:
    """
    How long a new instance is given to be ready: the bus's own bounds on a
    lost loopback connection -- its wake pair (``WAKE_PAIR_SECONDS`` x
    ``WAKE_PAIR_ATTEMPTS``) and a child's connect (one deadline,
    ``CONNECT_SECONDS`` x ``CONNECT_ATTEMPTS``) -- plus 30 s to boot. It was
    a flat 30 s, which the wake pair alone may take (v0.21.1: four lost
    attempts were seen).
    """
    from engine.hosting import bus

    return bus.WAKE_PAIR_SECONDS * bus.WAKE_PAIR_ATTEMPTS + bus.CONNECT_SECONDS * bus.CONNECT_ATTEMPTS + 30.0


#: Environment a child of the test must not inherit from the shell.
_CLEARED = ("CLOCKWORK_STUDIO", "CLOCKWORK_GAME", "CLOCKWORK_SECRET_KEY", "CLOCKWORK_ENV")


#: ``prctl``'s PR_SET_PDEATHSIG (linux/prctl.h).
_PR_SET_PDEATHSIG = 1


def parent_lifeline() -> dict[str, Any]:
    """
    Popen keywords that end a child when the process that started it dies
    (v0.21.1 T2 fix round 1): on Linux, ``prctl(PR_SET_PDEATHSIG, SIGTERM)``
    in the child before it runs, then a check that its parent did not already
    die in between. The supervisor runs in a session of its own
    (``start_new_session``), outside ``scripts/run_tests.py``'s process
    group, so without this a pytest killed past its limit (no teardown) left
    it and every worker running. SIGTERM is the supervisor's own clean
    shutdown, which ends its children (the bus lifeline).

    Empty -- no lifeline -- where there is no ``prctl`` (Windows: the session's
    Job Object, tests/process_jobs.py, ends it instead; macOS: none), or off
    the main thread: PDEATHSIG fires when the THREAD that started the child
    ends, not the process.
    """
    if not sys.platform.startswith("linux") or threading.current_thread() is not threading.main_thread():
        return {}
    import ctypes

    try:
        prctl = ctypes.CDLL(None, use_errno=True).prctl
    except (OSError, AttributeError):
        return {}
    prctl.argtypes = (ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong)
    prctl.restype = ctypes.c_int
    parent = os.getpid()
    sigterm = int(signal.SIGTERM)

    def die_with_parent() -> None:  # runs in the child, between fork and exec
        if prctl(_PR_SET_PDEATHSIG, sigterm, 0, 0, 0) == 0 and os.getppid() != parent:
            os._exit(1)  # the parent died before the lifeline was in place

    return {"preexec_fn": die_with_parent}


#: ``pid_alive`` (a bare-pid liveness probe) was removed in v0.20.0 T15 fix
#: round 2 (N2): the OS reuses pids, so a child is counted or waited for only
#: by its identity, pid AND creation time (``tests/process_identity.py``).


class RetryingTransport(httpx.HTTPTransport):
    """
    ``HTTPTransport`` that sends a request again when loopback lost it
    (v0.21.1): on the owner's workstation fresh loopback connections fail in
    bursts -- connects time out, a connection is reset -- while the processes
    on both ends are fine. A request whose connect failed was never sent, so
    any is sent again; one whose connection was lost under it (read, write,
    protocol error) only if it is a GET or HEAD -- never one that timed out,
    which is more likely the product hanging than loopback. Up to
    ``CALL_ATTEMPTS`` in all.
    """

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        for attempt in range(1, CALL_ATTEMPTS + 1):
            try:
                return super().handle_request(request)
            except (httpx.ConnectError, httpx.ConnectTimeout):
                if attempt == CALL_ATTEMPTS:
                    raise
            except (httpx.ReadError, httpx.RemoteProtocolError, httpx.WriteError):
                if request.method not in ("GET", "HEAD") or attempt == CALL_ATTEMPTS:
                    raise
        raise AssertionError("unreachable")


class HostingInstance:
    """One supervisor and its probe children (see the module docstring)."""

    def __init__(
        self,
        tmp_path: Path,
        *,
        stories: list[str],
        modes: Optional[dict[str, str]] = None,
        supervisor: Optional[dict[str, Any]] = None,
        observability: Optional[dict[str, Any]] = None,
        hosting: Optional[dict[str, Any]] = None,
        frontdoor: Any = True,
        env: Optional[dict[str, str]] = None,
        wait_ready: bool = True,
        worker_module: str = "",
        extra: Optional[dict[str, Any]] = None,
    ) -> None:
        self.tmp_path = tmp_path
        #: What each worker runs (``python -m``): the fake worker by default,
        #: ``LANE_CLIENT`` for the queue's tests (T11).
        self.worker_module = worker_module or FAKE_WORKER
        #: Other top-level config blocks (``llm.lanes``, say).
        self.extra = dict(extra or {})
        self.stories = list(stories)
        self.config_file = tmp_path / "hosting-instance.yaml"
        self.data_dir = tmp_path / "data"
        self.control = tmp_path / "control"
        self.modes = dict(modes or {})
        self.supervisor_keys = {**FAST_SUPERVISOR, **(supervisor or {})}
        self.observability = {"log_max_mb": 1, "log_keep": 2, **(observability or {})}
        self.hosting = dict(hosting or {})
        self.frontdoor = frontdoor
        self.env = dict(env or {})
        self.wait_ready_on_start = wait_ready
        self.proc: Optional[subprocess.Popen] = None
        self.lines: list[str] = []
        self._cond = threading.Condition()
        self._reader: Optional[threading.Thread] = None
        self.returncode: Optional[int] = None
        self.frontdoor_port = 0
        self._http: Any = None

    # -- start --------------------------------------------------------------------

    def write_config(self) -> None:
        block: dict[str, Any] = {
            "enabled": True,
            "stories": self.stories,
            "supervisor": self.supervisor_keys,
            "observability": self.observability,
            **self.hosting,
        }
        # The front door (T12) binds loopback on a port the OS picks, never
        # the owner's scene.clockwork.port.
        tree: dict[str, Any] = {"scene": {"clockwork": {"host": "127.0.0.1", "port": 0}}, **self.extra}
        self.config_file.write_text(
            yaml.safe_dump({**tree, "hosting": block}, sort_keys=True), encoding="utf-8"
        )

    def set_mode(self, process: str, mode: str) -> None:
        """``process``'s mode (``worker-<slug>`` or ``frontdoor``), read at its next check or start."""
        self.control.mkdir(parents=True, exist_ok=True)
        path = self.control / f"{process}.mode"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(mode, encoding="utf-8")
        os.replace(tmp, path)

    def command(self) -> list[str]:
        cmd = [sys.executable, "-u", "-m", "engine.hosting.supervisor", "--worker-module", self.worker_module]
        if self.worker_module == SCRIPTED_WORKER:
            # Where gunicorn runs (v0.20.0 T13), it serves the probe's app.
            cmd += ["--worker-wsgi", SCRIPTED_WORKER]
        if self.frontdoor == "real":
            cmd += ["--frontdoor-module", FRONTDOOR_RELAY, "--frontdoor-wsgi", FRONTDOOR_RELAY]
        elif self.frontdoor:
            cmd += ["--frontdoor-module", FAKE_WORKER]
        else:
            cmd += ["--no-frontdoor"]
        return cmd

    def start(self) -> "HostingInstance":
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.control.mkdir(parents=True, exist_ok=True)
        self.write_config()
        for process, mode in self.modes.items():
            self.set_mode(process, mode)
        env = {k: v for k, v in os.environ.items() if k not in _CLEARED}
        env["CLOCKWORK_CONFIG"] = str(self.config_file)
        env["CLOCKWORK_DATA_DIR"] = str(self.data_dir)
        env[CONTROL_ENV] = str(self.control)
        env.update(self.env)
        kwargs: dict[str, Any] = (
            {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
            if os.name == "nt"
            else {"start_new_session": True, **parent_lifeline()}
        )
        self.proc = subprocess.Popen(
            self.command(),
            cwd=str(REPO),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            **kwargs,
        )
        self._reader = threading.Thread(target=self._read, name="hosting-instance-reader", daemon=True)
        self._reader.start()
        if self.wait_ready_on_start:
            try:
                self.wait_all_ready()
            except BaseException:
                self.stop()
                raise
        return self

    def _read(self) -> None:
        assert self.proc is not None and self.proc.stdout is not None
        for raw in iter(self.proc.stdout.readline, b""):
            line = raw.decode("utf-8", "replace").rstrip("\r\n")
            with self._cond:
                self.lines.append(line)
                self._cond.notify_all()
        with self._cond:
            self._cond.notify_all()

    # -- waiting ------------------------------------------------------------------

    def wait_for(self, pattern: str, timeout: float = 15.0, *, after: int = 0) -> re.Match[str]:
        """The first output line at index >= ``after`` matching ``pattern``."""
        regex = re.compile(pattern)
        deadline = time.monotonic() + timeout
        with self._cond:
            index = after
            while True:
                while index < len(self.lines):
                    found = regex.search(self.lines[index])
                    index += 1
                    if found:
                        return found
                left = deadline - time.monotonic()
                if left <= 0 or (self.proc is not None and self.proc.poll() is not None and index >= len(self.lines)):
                    tail = "\n".join(self.lines[-40:])
                    raise AssertionError(f"no line matching {pattern!r} within {timeout}s; last lines:\n{tail}")
                self._cond.wait(min(left, 0.2))

    def mark(self) -> int:
        """The index of the next output line (for ``wait_for(after=)``)."""
        with self._cond:
            return len(self.lines)

    def until(self, check: Callable[[], Any], timeout: float = 15.0, what: str = "") -> Any:
        """Poll ``check`` every 0.1 s until it answers truthy; fail at ``timeout``."""
        deadline = time.monotonic() + timeout
        pause = threading.Event()
        last: Any = None
        while time.monotonic() < deadline:
            last = check()
            if last:
                return last
            pause.wait(0.1)
        raise AssertionError(f"not within {timeout}s: {what or check} (last: {last!r})")

    def wait_all_ready(self, timeout: Optional[float] = None) -> None:
        if timeout is None:
            timeout = ready_seconds()
        if self.frontdoor:
            match = self.wait_for(r"frontdoor sent ready \(operation=ready, pid=\d+, port=(\d+)\)", timeout)
            self.frontdoor_port = int(match.group(1))
            self.until(
                lambda: all(row["state"] == "ready" for row in self.table().values()),
                timeout,
                "every child ready",
            )
        else:
            for slug in self.stories:
                self.wait_for(rf"worker-{re.escape(slug)} is ready", timeout)

    # -- the front door's relay -----------------------------------------------------

    def relay_port(self) -> int:
        """Where ``call`` reaches the bus: the fake front door itself, or the real one's side door."""
        if self.frontdoor != "real":
            return self.frontdoor_port
        path = self.control / "frontdoor-relay.port"
        return int(self.until(lambda: path.is_file() and path.read_text(encoding="utf-8").strip(), 30, "the relay port"))

    def call(self, op: str, args: Optional[dict[str, Any]] = None, timeout: float = 10.0) -> dict[str, Any]:
        """
        ``op`` sent to the supervisor through the probe front door; its reply.

        A request lost on loopback is sent again (v0.21.1; on the owner's
        workstation a few connects in a thousand are never accepted, or
        accepted seconds late, under load): any op whose connect failed --
        nothing was sent -- and a READ (``READ_OPS``) that got no answer.
        An op that changes something and may have been sent is never resent.
        """
        import httpx

        if self._http is None:
            self._http = httpx.Client(trust_env=False, timeout=timeout + 5)
        for attempt in range(1, CALL_ATTEMPTS + 1):
            try:
                response = self._http.post(
                    f"http://127.0.0.1:{self.relay_port()}/bus",
                    json={"op": op, "args": args or {}, "timeout": timeout},
                    timeout=httpx.Timeout(timeout + 5, connect=CALL_CONNECT_SECONDS),
                )
            except (httpx.ConnectError, httpx.ConnectTimeout):
                if attempt == CALL_ATTEMPTS:
                    raise
            except httpx.TransportError:
                if op not in READ_OPS or attempt == CALL_ATTEMPTS:
                    raise
            else:
                response.raise_for_status()
                return response.json()
        raise AssertionError("unreachable")

    def tell(self, slug: str, payload: dict[str, Any], timeout: float = 10.0) -> dict[str, Any]:
        """
        One command to ``worker-<slug>`` when it is a ``LANE_CLIENT``
        (``tests/probes/lane_client.py``), on the port it reported in ``ready``.
        """
        import httpx

        if self._http is None:
            self._http = httpx.Client(trust_env=False, timeout=timeout + 5)
        port = self.row(f"worker-{slug}")["port"]
        response = self._http.post(f"http://127.0.0.1:{port}/command", json=payload, timeout=timeout)
        response.raise_for_status()
        return response.json()

    def table(self) -> dict[str, dict[str, Any]]:
        """``stories.list``, keyed by process name."""
        reply = self.call("stories.list")
        assert reply["ok"], reply
        return {row["process"]: row for row in reply["result"]["stories"]}

    def row(self, process: str) -> dict[str, Any]:
        return self.table()[process]

    def wait_state(self, process: str, state: str, timeout: float = 15.0) -> dict[str, Any]:
        return self.until(
            lambda: (lambda row: row if row["state"] == state else None)(self.row(process)),
            timeout,
            f"{process} {state}",
        )

    def op(self, op_id: str) -> dict[str, Any]:
        reply = self.call("ops.list")
        assert reply["ok"], reply
        return next(row for row in reply["result"]["ops"] if row["op_id"] == op_id)

    def wait_op(self, op_id: str, timeout: float = 15.0) -> dict[str, Any]:
        return self.until(
            lambda: (lambda row: row if row["status"] in ("done", "refused", "rolled_back") else None)(
                self.op(op_id)
            ),
            timeout,
            f"operation {op_id} finished",
        )

    # -- the probes' reports --------------------------------------------------------

    def reports(self, process: Optional[str] = None) -> list[dict[str, Any]]:
        """Every report a probe child wrote (``process`` only, if named), oldest first."""
        found = []
        for path in sorted(self.control.glob("*.json"), key=lambda p: p.stat().st_mtime_ns):
            name = path.stem.rsplit("-", 1)[0]
            if process is not None and name != process:
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            data["process"] = name
            found.append(data)
        return found

    def child_pids(self) -> set[int]:
        """Every pid a probe reported (for reading only: never signal a bare pid)."""
        return {int(r["pid"]) for r in self.reports()}

    def children(self) -> set[Any]:
        """
        Every child a probe reported, as ``process_identity.Identity`` (its pid
        AND creation time, v0.20.0 T15 fix round 1): what may be counted or
        signalled.
        """
        from tests.process_identity import of_report

        return {of_report(r) for r in self.reports()}

    def own_identity(self, process: str) -> Any:
        """``process``'s newest probe's identity (pid and creation time)."""
        from tests.process_identity import of_report

        found = self.reports(process)
        assert found, f"no report from {process}"
        return of_report(found[-1])

    def kill_child(self, process: str) -> int:
        """
        Make ``process``'s newest probe exit as a crash would (TerminateProcess
        on Windows, SIGTERM on POSIX) -- only if the process holding its pid is
        still that probe (``process_identity.terminate``). Its pid.
        """
        from tests.process_identity import terminate

        identity = self.own_identity(process)
        assert terminate(identity), f"{process} (pid {identity.pid}) is not running as the probe that reported it"
        return int(identity.pid)

    # -- the real front door (T12) ----------------------------------------------------

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.frontdoor_port}"

    def add_account(self, name: str, *, admin: bool = False) -> str:
        """An account in this instance's ``users.json`` (an admin, if asked); its generated password."""
        from engine.hosting.accounts import AccountStore

        password = "pw-" + secrets.token_urlsafe(12)
        AccountStore(self.data_dir / "hosting").add(name, password, admin=admin)
        return password

    def admin_http(self, name: str, password: str, *, retry: bool = False) -> Any:
        """
        An ``httpx.Client`` on the front door logged in as the admin ``name``
        and re-authenticated at ``/admin/reauth`` (v0.20.0 T15). ``retry``:
        as ``http``.
        """
        http = self.http(retry=retry)
        try:
            assert login(http, name, password).status_code == 303
            page = http.get("/admin/reauth")
            assert page.status_code == 200, page.text[:200]
            answer = http.post(
                "/admin/reauth", data={"csrf": csrf_of(page.text), "password": password, "next": "/admin"}
            )
            assert answer.status_code == 303, answer.text[:300]
        except BaseException:
            http.close()
            raise
        return http

    def http(self, *, retry: bool = False) -> Any:
        """
        An ``httpx.Client`` on the front door (no redirects followed, no
        system proxy). With ``retry``, a request lost on loopback is sent
        again (``RetryingTransport``): for a test about something else, not
        one that asserts what a lost connection does.
        """
        import httpx

        transport = RetryingTransport() if retry else None
        return httpx.Client(
            base_url=self.base, trust_env=False, follow_redirects=False, timeout=30.0, transport=transport
        )

    def proxied(self, process: str) -> list[str]:
        """Every ``METHOD path`` a scripted worker was sent through the front door."""
        found: list[str] = []
        for path in sorted(self.control.glob(f"{process}-*.requests")):
            found += [line for line in path.read_text(encoding="utf-8").splitlines() if line]
        return found

    def own_pid(self, process: str) -> int:
        """
        The pid ``process``'s newest probe reported for itself. (The story
        table's pid is the process the supervisor started; under a Windows
        venv that is the launcher, whose child is the probe.)
        """
        found = self.reports(process)
        assert found, f"no report from {process}"
        return int(found[-1]["pid"])

    def checks(self, process: str, pid: int) -> str:
        """The HTTP health checks ``process`` (its own pid ``pid``) answered: ``2``/``5`` each."""
        try:
            return (self.control / f"{process}-{pid}.http").read_text(encoding="ascii")
        except OSError:
            return ""

    def wait_checks(self, process: str, more: int, timeout: float = 15.0) -> str:
        """Wait until ``process``'s newest probe has answered ``more`` HTTP health checks beyond now."""
        pid = self.own_pid(process)
        start = len(self.checks(process, pid))
        return self.until(
            lambda: (lambda seen: seen if len(seen) >= start + more else "")(self.checks(process, pid)),
            timeout,
            f"{more} more health checks of {process}",
        )

    # -- stop -------------------------------------------------------------------------

    def stop(self, timeout: Optional[float] = None) -> Optional[int]:
        """The supervisor's own shutdown, then terminate, then kill; then no orphans."""
        proc = self.proc
        if proc is None:
            return self.returncode
        grace = float(timeout if timeout is not None else self.supervisor_keys["shutdown_seconds"] + 10)
        try:
            if proc.poll() is None:
                try:
                    if os.name == "nt":
                        proc.send_signal(signal.CTRL_BREAK_EVENT)
                    else:
                        proc.send_signal(signal.SIGTERM)
                except OSError:
                    pass
                try:
                    proc.wait(grace)
                except subprocess.TimeoutExpired:
                    proc.terminate()
                    try:
                        proc.wait(10)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait(10)
            self.returncode = proc.returncode
        finally:
            if self._reader is not None:
                self._reader.join(10)
            if self._http is not None:
                self._http.close()
                self._http = None
            self.proc = None
            self._no_orphans()
        return self.returncode

    def _no_orphans(self, timeout: float = 15.0) -> None:
        """
        Every child the probes reported is gone (a lost bus link ends one at
        once). A child is its pid AND its creation time (T15 fix round 1, I2):
        a reported pid now held by ANOTHER process -- the OS reuses pids, and
        this set holds every child a module ever started -- is not one of
        ours, so it is neither counted nor signalled; nor is a report that
        records no creation time. Only a verified child still running is
        terminated, and fails the test.
        """
        from tests.process_identity import alive as running, terminate

        deadline = time.monotonic() + timeout
        pause = threading.Event()
        alive = {child for child in self.children() if running(child)}
        while alive and time.monotonic() < deadline:
            pause.wait(0.1)
            alive = {child for child in alive if running(child)}
        for child in alive:
            terminate(child)
        assert not alive, f"child processes outlived their supervisor: {sorted(c.pid for c in alive)}"

    def __enter__(self) -> "HostingInstance":
        return self.start()

    def __exit__(self, *_exc: Any) -> None:
        self.stop()


def hosting_instance(tmp_path_factory: Any, name: str = "hosting", **kwargs: Any) -> Iterator[HostingInstance]:
    """
    For a module-scoped fixture: ``yield from hosting_instance(tmp_path_factory, stories=[...])``.
    The instance is stopped however the module ends.
    """
    instance = HostingInstance(tmp_path_factory.mktemp(name), **kwargs)
    instance.start()
    try:
        yield instance
    finally:
        instance.stop()


_CSRF_RE = re.compile(r'name="csrf" value="([^"]*)"')


def csrf_of(text: str) -> str:
    """The first form token on a page."""
    match = _CSRF_RE.search(text)
    assert match, f"no csrf field on the page: {text[:200]!r}"
    return match.group(1)


def login(http: Any, name: str, password: str) -> Any:
    """The front door's login form, filled: the POST's response (303 on success)."""
    page = http.get("/login")
    assert page.status_code == 200, page.text[:200]
    return http.post("/login", data={"csrf": csrf_of(page.text), "name": name, "password": password})


def choose(http: Any, slug: str) -> Any:
    """``POST /stories/<slug>`` with the picker's own token: its response (303)."""
    page = http.get("/stories")
    assert page.status_code == 200, page.text[:200]
    return http.post(f"/stories/{slug}", data={"csrf": csrf_of(page.text)})


class InProcessFrontDoor:
    """
    The front door and one hosted worker in THIS process (see the module
    docstring). Build with ``start()``; ``stop()`` (also on a failed start)
    shuts both servers, the bus, the queue, the server locks and the config.
    """

    def __init__(
        self,
        monkeypatch: Any,
        tmp_path: Path,
        *,
        story: str = "clockwork-dark",
        hosting: Optional[dict[str, Any]] = None,
        extra: Optional[dict[str, Any]] = None,
        llm_fn: Any = "scripted",
        env: Optional[dict[str, str]] = None,
    ) -> None:
        self.monkeypatch = monkeypatch
        self.env = dict(env or {})
        #: Every bus token minted here (the secrets crawl scans for them).
        self.tokens: list[str] = []
        self.tmp_path = tmp_path
        self.story = story
        self.hosting = {"cookie_secure": False, **(hosting or {})}
        self.extra = dict(extra or {})
        self.llm_fn = llm_fn
        self.proxy_token = secrets.token_hex(32)
        self.exits: list[int] = []
        self.state = "ready"
        self.seq = 0
        self.hosted: Any = None
        self.front_app: Any = None
        self.worker_port = 0
        self.front_port = 0
        self._servers: list[tuple[Any, threading.Thread]] = []
        self._clients: list[Any] = []
        self.server: Any = None
        self.queue: Any = None

    # -- start / stop -----------------------------------------------------------------

    def start(self) -> "InProcessFrontDoor":
        try:
            self._start()
        except BaseException:
            self.stop()
            raise
        return self

    def _serve(self, app: Any) -> int:
        from werkzeug.serving import make_server

        server = make_server("127.0.0.1", 0, app, threaded=True)
        thread = threading.Thread(target=server.serve_forever, name="inprocess-serve", daemon=True)
        thread.start()
        self._servers.append((server, thread))
        return int(server.server_port)

    def _start(self) -> None:
        from engine.hosting import BUS_EXTENSION
        from engine.hosting import bus as bus_module
        from engine.hosting.bus import BusClient, BusServer
        from engine.hosting.supervisor.queue import LaneQueue
        from tests import hosted_app

        # A lost link must fail a test, never end this process.
        self.monkeypatch.setattr(bus_module, "_exit_process", self.exits.append)
        self.queue = LaneQueue({"narration": 1, "utility": 2}).start()
        self.server = BusServer().start()
        self.queue.attach(self.server)
        self.server.on_close = lambda conn: self.queue.close_connection(conn.id)
        self.server.handle("stories.list", lambda _c, _a: {"stories": self.rows(), "seq": self.seq})
        self.server.handle("ready", lambda _c, _a: {})
        record = self.server.mint("worker", story=self.story, process=f"worker-{self.story}")
        self.tokens.append(record.token)
        env = {
            **self.env,
            "CLOCKWORK_BUS_ADDR": self.server.addr,
            "CLOCKWORK_BUS_TOKEN": record.token,
            "CLOCKWORK_PROXY_TOKEN": self.proxy_token,
        }
        kwargs: dict[str, Any] = {} if self.llm_fn == "scripted" else {"llm_fn": self.llm_fn}
        self.hosted = hosted_app.build(
            self.monkeypatch,
            self.tmp_path,
            hosting=self.hosting,
            extra={"scene": {"clockwork": {"host": "127.0.0.1", "port": 0}}, **self.extra},
            env=env,
            **kwargs,
        )
        worker_bus = self.hosted.app.extensions[BUS_EXTENSION]
        worker_bus.on_lost = lambda: None
        self._clients.append(worker_bus)
        self.worker_port = self._serve(self.hosted.app)

        from engine.hosting.frontdoor import create_frontdoor_app

        front = self.server.mint("frontdoor", process="frontdoor")
        self.tokens.append(front.token)
        client = BusClient(self.server.addr, front.token, proxy_token=self.proxy_token)
        client.on_lost = lambda: None
        self._clients.append(client)
        self.front_app = create_frontdoor_app(bus=client)
        self.front_port = self._serve(self.front_app)

    def stop(self) -> None:
        from tests import hosted_app

        for server, thread in self._servers:
            server.shutdown()
            server.server_close()
            thread.join(10)
            assert not thread.is_alive(), "an in-process server did not stop"
        self._servers.clear()
        if self.front_app is not None:
            from engine.hosting.auth import hosting_state
            from engine.hosting.frontdoor import frontdoor

            frontdoor(self.front_app).proxy.close()
            state = hosting_state(self.front_app)
            if state.server_lock is not None:
                os.close(state.server_lock)
                state.server_lock = None
        for client in self._clients:
            client.close()
        self._clients.clear()
        if self.server is not None:
            self.server.close()
        if self.queue is not None:
            self.queue.close()
        hosted_app.teardown()
        assert not self.exits, f"a lifeline fired in this process: {self.exits}"

    # -- the supervisor's side ----------------------------------------------------------

    def rows(self) -> list[dict[str, Any]]:
        return [{"slug": self.story, "state": self.state, "port": self.worker_port, "role": "worker"}]

    def set_state(self, state: str, timeout: float = 10.0) -> None:
        """Send the front door ``stories.changed`` with the worker in ``state``; wait until it has it."""
        from engine.hosting.frontdoor import frontdoor

        self.state = state
        self.seq += 1
        conn = next(c for c in self.server.connections() if c.role == "frontdoor")
        rows = [{k: r[k] for k in ("slug", "state", "port")} for r in self.rows()]
        self.server.notify(conn, "stories.changed", {"stories": rows, "seq": self.seq})
        table = frontdoor(self.front_app).table
        deadline = time.monotonic() + timeout
        pause = threading.Event()
        while table.seq < self.seq:
            assert time.monotonic() < deadline, "the front door never had the change"
            pause.wait(0.02)

    # -- clients -------------------------------------------------------------------------

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.front_port}"

    @property
    def worker_base(self) -> str:
        return f"http://127.0.0.1:{self.worker_port}"

    def http(self, base: Optional[str] = None) -> Any:
        import httpx

        return httpx.Client(base_url=base or self.base, trust_env=False, follow_redirects=False, timeout=30.0)

    def logged_in(self, name: str = "alice", *, chosen: bool = True) -> Any:
        """A front door client logged in as a new account ``name`` (and the story chosen)."""
        _account, password = self.hosted.add(name)
        http = self.http()
        response = login(http, name, password)
        assert response.status_code == 303, response.text[:300]
        if chosen:
            assert choose(http, self.story).status_code == 303
        return http


class AdminDoor:
    """
    The engine's front door in THIS process, with no engine behind it (v0.20.0
    T14): the admin panel's tests need the front door's own routes, and a
    "worker" that only COUNTS what reaches it, so a test can prove an
    ``/admin`` path never does. A light loopback bus answers ``stories.list``
    with one ready story on the counter's port. Requests go through Flask's
    test client (``client()``); hosting is on through a temp ``local.yaml``
    (``tests/hosted_app.hosting_layer``), the storage root under ``tmp_path``.
    """

    def __init__(
        self,
        monkeypatch: Any,
        tmp_path: Path,
        *,
        story: str = "clockwork-dark",
        hosting: Optional[dict[str, Any]] = None,
        extra: Optional[dict[str, Any]] = None,
        env: Optional[dict[str, str]] = None,
    ) -> None:
        self.monkeypatch = monkeypatch
        self.tmp_path = tmp_path
        self.story = story
        rates = {"logins_per_minute": 1000, "logins_per_minute_all": 1000, "admin_actions_per_minute": 1000}
        given = dict(hosting or {})
        rates.update(given.pop("rate_limits", {}) or {})
        self.hosting = {"cookie_secure": False, "rate_limits": rates, **given}
        self.extra = dict(extra or {})
        self.env = dict(env or {})
        self.proxy_token = secrets.token_hex(32)
        #: Every ``METHOD path`` the counting worker was sent.
        self.reached: list[str] = []
        self.exits: list[int] = []
        self.app: Any = None
        self.data_dir = tmp_path / "data"
        self._servers: list[tuple[Any, threading.Thread]] = []
        self._clients: list[Any] = []
        self.server: Any = None
        self.passwords: dict[str, str] = {}

    def start(self) -> "AdminDoor":
        try:
            self._start()
        except BaseException:
            self.stop()
            raise
        return self

    def _counter(self, environ: dict[str, Any], start_response: Callable[..., Any]) -> list[bytes]:
        self.reached.append(f"{environ.get('REQUEST_METHOD')} {environ.get('PATH_INFO')}")
        start_response("200 OK", [("Content-Type", "application/json")])
        return [b'{"worker": "counted"}']

    def _start(self) -> None:
        from werkzeug.serving import make_server

        from engine.hosting import bus as bus_module
        from engine.hosting.bus import BusClient, BusServer
        from engine.hosting.frontdoor import create_frontdoor_app
        from tests import hosted_app

        self.monkeypatch.setattr(bus_module, "_exit_process", self.exits.append)
        hosted_app.hosting_layer(
            self.monkeypatch,
            self.tmp_path,
            hosting=self.hosting,
            extra={"scene": {"clockwork": {"host": "127.0.0.1", "port": 0}}, **self.extra},
        )
        for name, value in self.env.items():
            self.monkeypatch.setenv(name, value)
        worker = make_server("127.0.0.1", 0, self._counter, threaded=True)
        thread = threading.Thread(target=worker.serve_forever, name="admin-door-counter", daemon=True)
        thread.start()
        self._servers.append((worker, thread))
        port = int(worker.server_port)
        self.server = BusServer().start()
        self.server.handle(
            "stories.list",
            lambda _c, _a: {"stories": [{"slug": self.story, "state": "ready", "port": port, "role": "worker"}], "seq": 1},
        )
        # A supervisor with no worker to ask (v0.20.0 T15 fix round 1): the
        # panel's sessions ops answer "none live" rather than unknown_op, as
        # a real one with no serving story would.
        self.server.handle("sessions.list", lambda _c, _a: {"rows": [], "total": 0, "stories": {}, "errors": []})
        self.server.handle("sessions.end_owner", lambda _c, _a: {"ended": 0, "busy": 0, "errors": []})
        # T17: a metrics store with nothing in it yet.
        self.server.handle("metrics.query", lambda _c, _a: {"rows": [], "total": 0})
        front = self.server.mint("frontdoor", process="frontdoor")
        self.bus_token = front.token
        client = BusClient(self.server.addr, front.token, proxy_token=self.proxy_token)
        client.on_lost = lambda: None
        self._clients.append(client)
        self.app = create_frontdoor_app(bus=client)
        self.app.testing = True

    def stop(self) -> None:
        from tests import hosted_app

        for server, thread in self._servers:
            server.shutdown()
            server.server_close()
            thread.join(10)
            assert not thread.is_alive(), "the counting worker did not stop"
        self._servers.clear()
        if self.app is not None:
            from engine.hosting.auth import hosting_state
            from engine.hosting.frontdoor import frontdoor

            frontdoor(self.app).proxy.close()
            state = hosting_state(self.app)
            if state.server_lock is not None:
                os.close(state.server_lock)
                state.server_lock = None
        for client in self._clients:
            client.close()
        self._clients.clear()
        if self.server is not None:
            self.server.close()
            self.server = None
        hosted_app.teardown()
        assert not self.exits, f"a lifeline fired in this process: {self.exits}"

    # -- accounts and clients ---------------------------------------------------------

    @property
    def accounts(self) -> Any:
        from engine.hosting.auth import hosting_state

        return hosting_state(self.app).accounts

    def add(self, name: str, *, admin: bool = False) -> Any:
        """An account (its password kept in ``passwords``); the account."""
        password = "pw-" + secrets.token_urlsafe(12)
        self.passwords[name] = password
        return self.accounts.add(name, password, admin=admin)

    def client(self) -> Any:
        return self.app.test_client()

    def login(self, name: str, password: Optional[str] = None) -> Any:
        """A test client logged in as ``name``."""
        client = self.client()
        page = client.get("/login")
        token = csrf_of(page.get_data(as_text=True))
        answer = client.post(
            "/login", data={"csrf": token, "name": name, "password": password or self.passwords[name]}
        )
        assert answer.status_code == 303, answer.get_data(as_text=True)[:300]
        return client

    def reauth(self, client: Any, name: str) -> None:
        """Re-authenticate ``client`` (an admin) through ``/admin/reauth``."""
        page = client.get("/admin/reauth")
        assert page.status_code == 200, page.status_code
        answer = client.post(
            "/admin/reauth",
            data={"csrf": csrf_of(page.get_data(as_text=True)), "password": self.passwords[name], "next": "/admin"},
        )
        assert answer.status_code == 303, answer.get_data(as_text=True)[:300]

    def admin(self, name: str = "root") -> Any:
        """A logged-in, re-authenticated admin's client (the account made if need be)."""
        if self.accounts.by_name(name) is None:
            self.add(name, admin=True)
        client = self.login(name)
        self.reauth(client, name)
        return client

    def token(self, client: Any) -> str:
        """The client's admin form token (from the Users page)."""
        return csrf_of(client.get("/admin/users").get_data(as_text=True))


__all__ = [
    "AdminDoor",
    "CONTROL_ENV",
    "FAKE_WORKER",
    "FAST_SUPERVISOR",
    "FRONTDOOR_RELAY",
    "HostingInstance",
    "InProcessFrontDoor",
    "LANE_CLIENT",
    "SCRIPTED_WORKER",
    "choose",
    "csrf_of",
    "hosting_instance",
    "login",
]
