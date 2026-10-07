"""
Start a batch of child processes together, a bounded number at a time, and
never leave one running (v0.21.1 T4).

Used by the module fixtures of ``tests/test_imports.py`` (a fresh interpreter
per module) and ``tests/test_simulate_thief.py`` (the CLI goldens): each test
used to start its own child and wait for it, so the file's wall time was the
SUM of its children's. Started together, it is about the longest one.

BOUNDED. At most ``workers`` children run at once (``default_workers``: the
CPU count, capped at 8). This workstation's loopback and CPU stall in bursts
under heavy load (Windows Defender, scanning each new interpreter), and a
batch of 17 cold interpreters at once was the kind of load that provokes it.

NOTHING LEFT RUNNING (preflight K5). Every child's output goes to a file, so
no pipe can fill and wedge it, and the whole batch runs inside one
``try/finally``: on a timeout, an exception (a ``KeyboardInterrupt``, a
failing ``on_start``), or a pytest-timeout raised into the fixture, every
child still running is ended and waited for before the error goes on. A
child is ended by its IDENTITY (pid and creation time, recorded at start,
``tests/process_identity.py``), never by a bare pid; where the platform
cannot tell its creation time (or a child interrupted before its identity
was read), through the ``Popen`` handle, which names a child not yet waited
for, so its pid cannot have been reused.

ONE BUDGET FOR THE BATCH. Each child has its own timeout, and the whole batch
``batch_budget()`` (under a ``process`` test's limit): a slow machine running
few at a time cannot carry the batch, wave by wave, past its first user's
limit.

UNDER XDIST (a note for v0.21.1 T5): ``selected`` reads
``request.session.items``, which in a worker is the WHOLE collection, not the
worker's share. A module whose batch users land on several workers would have
each of them start the whole batch; the fixtures' users must share one
``xdist_group``. ``default_workers`` divides the cap among the workers.
``tests/test_child_batch.py`` is the canary.

Version: v0.1.0 [2026-10-07]
"""

from __future__ import annotations

import os
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Hashable, Mapping, Optional, Sequence

from tests.process_identity import Identity, identify, terminate

#: How long a killed child is given to be reaped.
_REAP_SECONDS = 30.0
#: How often the batch looks at its running children.
_POLL_SECONDS = 0.05


def selected(request: Any, test: str, param: Optional[str] = None) -> list[Any]:
    """
    What a module fixture's batch must start: for each item of the requesting
    module named ``test`` (its ``originalname``) that this session will run,
    its ``param`` value (``None`` without ``param``). A ``-k`` or node-id run
    then starts only the children it reads, and a deselected test's children
    are not started at all.
    """
    return [
        item.callspec.params[param] if param else None
        for item in request.session.items
        if getattr(item, "module", None) is request.module
        and getattr(item, "originalname", None) == test
        and (not param or getattr(item, "callspec", None) is not None)
    ]


def default_workers() -> int:
    """The CPU count, at least 2 and at most 8, shared among the xdist workers
    when there are some (``PYTEST_XDIST_WORKER_COUNT``; at least 1 each)."""
    cap = max(2, min(os.cpu_count() or 2, 8))
    try:
        sharing = int(os.environ.get("PYTEST_XDIST_WORKER_COUNT", "") or 1)
    except ValueError:
        sharing = 1
    return max(1, cap // max(1, sharing))


def batch_budget() -> float:
    """How long a whole batch may take: four fifths of a ``process`` test's
    limit (``tests/tier_plugin.py``, scaled), so a hung child is ended -- and
    fails only the test that reads it -- before the first user's own limit
    ends the whole module (or, on Windows, the whole run)."""
    from tests.tier_plugin import TIER_LIMIT, _scale

    return 0.8 * TIER_LIMIT * _scale()


@dataclass(frozen=True)
class Done:
    """What one child left: its exit code (None when it was ended at its
    deadline, or never started because the batch's had passed), its stdout
    and stderr bytes."""

    returncode: Optional[int]
    stdout: bytes
    stderr: bytes

    @property
    def timed_out(self) -> bool:
        return self.returncode is None


@dataclass
class _Running:
    proc: subprocess.Popen
    identity: Identity
    deadline: float
    out: Path
    err: Path


def _end(proc: subprocess.Popen, identity: Optional[Identity]) -> None:
    """End ``proc`` (by its identity, else through its unreaped handle) and reap it."""
    if proc.poll() is None:
        kill = getattr(signal, "SIGKILL", signal.SIGTERM)
        known = identity is not None and identity.created is not None
        if not (known and terminate(identity, kill)) and proc.poll() is None:
            proc.kill()
    proc.wait(timeout=_REAP_SECONDS)


def run_together(
    commands: Mapping[Hashable, Sequence[str]],
    *,
    out_dir: Path,
    timeout: float,
    cwd: Optional[Path] = None,
    workers: Optional[int] = None,
    budget: Optional[float] = None,
    on_start: Optional[Callable[[Hashable, Identity], None]] = None,
) -> dict[Hashable, Done]:
    """
    Run every argv in ``commands`` (key -> argv), ``workers`` at a time, each
    with its own ``timeout`` seconds from its start, and answer key -> ``Done``.

    The whole batch has ``budget`` seconds (``batch_budget()`` by default):
    past it, every child still running is ended and none is started, each
    answering as timed out, so a slow wave cannot carry the batch past its
    first user's limit.

    ``on_start(key, identity)`` is called after each child starts (the canary
    records identities through it; a raise there is a raise mid-batch).
    Children are started in ``commands``' order.
    """
    limit = workers or default_workers()
    end_of_batch = time.monotonic() + (batch_budget() if budget is None else budget)
    out_dir.mkdir(parents=True, exist_ok=True)
    pending = list(enumerate(commands.items()))
    running: dict[Hashable, _Running] = {}
    results: dict[Hashable, Done] = {}
    # Every child ever started, appended in the same statement as its start:
    # the finally walks THIS list, so a child is covered from the moment
    # Popen returns, before its identity or its entry in `running` exists.
    born: list[subprocess.Popen] = []
    identities: dict[int, Identity] = {}
    try:
        while pending or running:
            while pending and len(running) < limit and time.monotonic() < end_of_batch:
                index, (key, argv) = pending.pop(0)
                out, err = out_dir / f"{index}.out", out_dir / f"{index}.err"
                with open(out, "wb") as so, open(err, "wb") as se:
                    born.append(subprocess.Popen(
                        list(argv), cwd=str(cwd) if cwd else None,
                        stdin=subprocess.DEVNULL, stdout=so, stderr=se,
                    ))
                proc = born[-1]
                identities[id(proc)] = identify(proc.pid)
                deadline = min(time.monotonic() + timeout, end_of_batch)
                running[key] = _Running(proc, identities[id(proc)], deadline, out, err)
                if on_start is not None:
                    on_start(key, identities[id(proc)])
            if time.monotonic() >= end_of_batch:
                for _, (key, _argv) in pending:
                    results[key] = Done(None, b"", b"not started: the batch's budget had passed")
                pending = []
            for key, child in list(running.items()):
                code = child.proc.poll()
                if code is None and time.monotonic() < child.deadline:
                    continue
                if code is None:
                    _end(child.proc, child.identity)
                del running[key]
                results[key] = Done(code, child.out.read_bytes(), child.err.read_bytes())
            if running:
                time.sleep(_POLL_SECONDS)
    finally:
        # Every child is ended even when one of them will not be reaped; the
        # first such failure is raised after the rest have been tried.
        failure: Optional[BaseException] = None
        for proc in born:
            try:
                _end(proc, identities.get(id(proc)))
            except BaseException as exc:  # noqa: BLE001 -- re-raised below
                failure = failure or exc
        if failure is not None:
            raise failure
    return {key: results[key] for key in commands}
