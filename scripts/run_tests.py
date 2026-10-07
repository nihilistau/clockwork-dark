"""
The one way into the test suite (v0.21.1). Subcommands:

  ids      the sorted collected test ids of the FULL suite (--full --collect-only)
  fast     the default tier
  full     every test
  files    explicit files/node ids
  changed  only what a change touched  (Task 6)

``fast``, ``full`` and ``files`` each run pytest with a basetemp of their own
(``basetemp_for``: pytest wipes its basetemp at start, so two runs sharing
one destroy each other's temp trees) and under a wall-clock limit
(``run_bounded``). The per-test limit is pytest-timeout's (pytest.ini).

STOPPING A RUN (K2). On Windows pytest starts suspended, is put in a Job
Object with KILL_ON_JOB_CLOSE (tests/process_jobs.py), and only then
resumed, so every process it starts (xdist workers, a hosted supervisor and
its children, a probe's grandchild) is in the job; past the limit the job is
terminated, and when the run ends -- or this script is interrupted or dies --
the job is closed, which ends anything left in it. The whole tree.

On POSIX pytest leads a new session (its own process group), and pytest's
own pid is held unreaped (``waitid(WNOWAIT)``) until the stop is done, so
neither it nor the group id can have passed to another process: those two
signals are the one place a number names processes. Past the limit, and on
Ctrl+C or an error here: SIGINT to pytest, so its fixture teardowns run (a
hosted supervisor is stopped by its fixture), up to 30 s; then SIGTERM to the
group, 5 s, SIGKILL to the group. After a normal end, SIGKILL to whatever
is left in the group. A child in a session of ITS OWN (``setsid``, as the
hosted supervisor and its children are) is outside the group: it is stopped
only by its test's teardown, or by its own lifeline (the hosted test
supervisor dies with its parent on Linux, tests/hosting_instance.py). A
setsid child with neither survives an overrun on POSIX. Needs ``os.waitid``
(Linux; macOS from Python 3.13).

THE HYBRID FULL RUN (v0.21.1 T5 fix round 1). ``full`` with workers runs
two phases under ONE deadline: ``parallel`` (``-m "not (process or
mcp_server)"`` on the workers, ``--dist loadgroup``), then ``serial`` (``-m
"(process or mcp_server)"``, one process). The expressions are
tests/tiers.py's; a user's own ``-m`` is joined to each with ``and``. Each
phase has its own basetemp and log; the exit code is ``combine``'s; the
summary lists every failed id with a command that re-runs it alone (the
re-run is a human's call: a hosted test that passes alone was this
machine's loopback stall). ``fast`` is the same hybrid over the fast tier
only (its parallel phase, then a short serial tail of its ``loopback`` and
``mcp_server`` tests: T5 fix round 2 measured those failing under xdist in
a fully parallel ``fast``). ``--workers 0`` is one serial run (``full
--workers 0`` is the order-independence check); ``files`` is serial.

THE SOLO RE-RUN (T5 fix round 3). After the phases, every test that failed
in the SERIAL phase -- so is marked ``process``, ``mcp_server`` or
``loopback``: the ones this machine's loopback stalls fail -- is run once
more, serially, in a fresh bounded pass inside the same deadline. If all
pass, the run passes, and the summary lists them under ``FLAKY (passed on
solo re-run):`` -- reported, never hidden. A test that fails again stays a
failure. Never re-run: a failure in the parallel phase (an unmarked,
in-process test: a real failure, maybe an order bug), a run whose storage
check failed, a run that ended 124/2/3/4, or more than ``MAX_RERUN`` ids
(the machine is stalling, not the tests). ``--no-rerun`` turns it off.

  python scripts/run_tests.py full                  # hybrid: parallel, then serial
  python scripts/run_tests.py full --workers 0      # one serial run
  python scripts/run_tests.py files tests/test_imports.py --label mine -- -x
"""

from __future__ import annotations

import argparse
import datetime as _dt
import itertools
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import IO, Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:  # run as a script, sys.path[0] is scripts/
    sys.path.insert(0, str(ROOT))

from tests.process_jobs import CREATE_SUSPENDED, Job  # noqa: E402  (the shared Windows Job Object)
from tests.tiers import FAST_MARKS, phase_marks  # noqa: E402  (the hybrid's -m expressions, defined once)

EXIT_LIMIT = 124  # what `timeout(1)` returns: the run hit its wall-clock limit
_SEQ = itertools.count()  # two calls in one microsecond still differ

#: minutes; the bare-hang limit for a whole run (the per-test limit is pytest-timeout's)
DEFAULT_LIMITS = {"fast": 45, "full": 120, "files": 60, "changed": 45}

#: pytest-xdist workers for ``fast``/``full`` (v0.21.1 T5, measured in its
#: soak: CHANGELOG). ``files`` runs serially unless asked; ``--workers 0`` is
#: always serial. Workers always run ``--dist loadgroup`` (tests/tier_plugin.py:
#: the tests that share a module fixture, or the skills-server port, share one).
DEFAULT_WORKERS = 6

#: Seconds the serial phase needs at least; with less left it is skipped (124).
MIN_PHASE_SECONDS = 60

#: The most failed ids the solo re-run takes; past it the run fails as it is.
MAX_RERUN = 40

#: Printed by the xdist controller when the owner's storage changed
#: (tests/conftest.py); the summary repeats every such line.
STORAGE_MARK = "STORAGE CHECK FAILED"
#: The serial session's own storage failure (tests/conftest.py::assert_storage_unchanged).
STORAGE_SERIAL_MARK = "the suite changed the owner's real storage"

#: How long a stopped pytest is given for its teardowns (SIGINT on POSIX).
_GRACE_SECONDS = 30
#: How long the rest of the group is given after SIGTERM, before SIGKILL (POSIX).
_MEMBER_GRACE_SECONDS = 5


def collected_ids(basetemp: Path) -> list[str]:
    """Every id ``pytest --full --collect-only -q`` prints, sorted."""
    done = subprocess.run(
        [sys.executable, "-m", "pytest", "tests", "--full", "--collect-only", "-q",
         "-p", "no:cacheprovider", f"--basetemp={basetemp}"],
        cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", timeout=900,
    )
    ids = [line.strip() for line in done.stdout.splitlines() if "::" in line]
    if done.returncode not in (0, 5) or not ids:
        sys.stderr.write(done.stdout[-3000:] + done.stderr[-3000:])
        raise SystemExit(f"collection failed (exit {done.returncode})")
    return sorted(ids)


def compare(before: list[str], after: list[str]) -> list[str]:
    """Lines describing every id lost or gained."""
    b, a = set(before), set(after)
    return [f"LOST  {i}" for i in sorted(b - a)] + [f"GAINED {i}" for i in sorted(a - b)]


def _read_ids(path: Path) -> list[str]:
    # One id a line: a parametrized id can hold spaces, so never split().
    text = path.read_text(encoding="utf-8-sig")
    return [line.strip() for line in text.splitlines() if line.strip()]


# -- basetemp -----------------------------------------------------------------------


def basetemp_root() -> Path:
    raw = os.environ.get("CLOCKWORK_TEST_BASETEMP_ROOT")
    root = Path(raw) if raw else Path(tempfile.gettempdir()) / "claude" / "clockwork-tests"
    root = root.resolve()
    if root == ROOT or ROOT in root.parents:
        raise SystemExit(f"basetemp root {root} is inside the repository; pick one outside it")
    return root


def basetemp_for(label: str) -> Path:
    """A fresh basetemp no other run uses: pytest wipes its basetemp at start,
    so two runs sharing one destroy each other's temp trees."""
    stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    return basetemp_root() / f"{label}-{os.getpid()}-{stamp}-{next(_SEQ)}"


_XDIST_FLAGS = ("-n", "--numprocesses", "--dist", "-d", "--maxprocesses", "--tx")


def _refuse_xdist_flags(extra: list[str]) -> None:
    """xdist is this script's to set (``--workers``): a ``-n``/``--dist`` or
    ``-p xdist`` after ``--`` would fight the phases."""
    for i, arg in enumerate(extra):
        flag = arg.split("=", 1)[0]
        if flag in _XDIST_FLAGS or (arg.startswith("-n") and arg[2:].isdigit()):
            raise SystemExit(f"run_tests.py: {arg!r} after --: use --workers instead")
        if arg in ("-p", "-pxdist") and (arg == "-pxdist" or extra[i + 1: i + 2] == ["xdist"]):
            raise SystemExit("run_tests.py: -p xdist after --: use --workers instead")


def lift_markexpr(extra: list[str]) -> tuple[str | None, list[str]]:
    """``(the user's -m expression or None, extra without it)``. Several -m
    are joined by ``and``, as each phase's own is."""
    found: list[str] = []
    rest: list[str] = []
    i = 0
    while i < len(extra):
        arg = extra[i]
        if arg == "-m" and i + 1 < len(extra):
            found.append(extra[i + 1])
            i += 2
            continue
        if arg.startswith("-m") and len(arg) > 2 and not arg.startswith("-m-"):
            found.append(arg[2:].lstrip("="))
            i += 1
            continue
        rest.append(arg)
        i += 1
    if not found:
        return None, rest
    return " and ".join(f"({f})" for f in found) if len(found) > 1 else found[0], rest


class Phase:
    """One pytest run of a ``run_tests.py`` command: its name, argv, basetemp and log."""

    def __init__(self, name: str, argv: list[str], basetemp: Path, log: Path) -> None:
        self.name, self.argv, self.basetemp, self.log = name, argv, basetemp, log
        self.code: int | None = None
        self.seconds = 0.0


def _base_argv(basetemp: Path) -> list[str]:
    return [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
            f"--basetemp={basetemp}", "--durations=25"]


def build_phases(args: argparse.Namespace) -> list[Phase]:
    """The phases a ``fast``/``full``/``files`` command runs: two for a
    ``full`` or ``fast`` with workers (the hybrid; ``fast`` is its tier's
    tests only), one otherwise. A phase's log sits
    beside its basetemp; ``--log`` names the first phase's (the second's is
    beside it, ``.serial`` added)."""
    _refuse_xdist_flags(list(args.extra))
    workers = getattr(args, "workers", 0)
    if args.cmd in ("full", "fast") and workers:
        user, rest = lift_markexpr(list(args.extra))
        if args.cmd == "fast":
            # The fast tier as an expression (a -m is a selection of its own,
            # so the bare-run filter would not apply): its serial tail is its
            # own loopback and mcp_server tests (T5 fix round 2).
            user = f"({FAST_MARKS}) and ({user})" if user else FAST_MARKS
        phases = []
        for name in ("parallel", "serial"):
            basetemp = basetemp_for(f"{args.label}-{name}")
            argv = _base_argv(basetemp) + ["--full", "-m", phase_marks(user, name)]
            if name == "parallel":
                argv += ["-n", str(workers), "--dist", "loadgroup"]
            phases.append(Phase(name, argv + rest, basetemp, basetemp.with_name(basetemp.name + ".log")))
        if args.log:
            phases[0].log = args.log
            phases[1].log = args.log.with_name(args.log.name + ".serial")
        args.basetemp = phases[0].basetemp
        args.rerun_extra = rest
        return phases
    argv = build_argv(args)
    log = args.log or args.basetemp.with_name(args.basetemp.name + ".log")
    return [Phase("run", argv, args.basetemp, log)]


def combine(codes: list[int]) -> int:
    """One exit code for the phases: 124 (a limit) if any; else 2
    (interrupted); else the first of 3, 4 or 1; else 0 -- a phase that
    collected nothing (5) counts as 0, unless every phase did (then 5)."""
    if not codes:
        return 0
    if EXIT_LIMIT in codes:
        return EXIT_LIMIT
    if 2 in codes:
        return 2
    for code in codes:
        if code in (3, 4, 1):
            return code
    if all(code == 5 for code in codes):
        return 5
    bad = [c for c in codes if c not in (0, 5)]
    return bad[0] if bad else 0


#: A phase may run after another that ended with one of these (a failure is
#: not a reason to skip the rest; a limit, an interrupt or an error is).
_GO_ON = (0, 1, 5)


def run_phases(phases: list[Phase], limit_seconds: float, runner: Any = None) -> int:
    """Run ``phases`` in order under ONE deadline; a later phase gets what is
    left, and is skipped (124) with less than ``MIN_PHASE_SECONDS`` or after
    a phase that ended 124, 2, 3 or 4."""
    runner = runner or run_bounded
    deadline = time.monotonic() + limit_seconds
    codes: list[int] = []
    for i, phase in enumerate(phases):
        left = deadline - time.monotonic()
        if i and (codes[-1] not in _GO_ON or left < MIN_PHASE_SECONDS):
            if codes[-1] in _GO_ON:  # skipped for time: the run hit its limit
                phase.code = EXIT_LIMIT
                codes.append(EXIT_LIMIT)
            break
        started = time.monotonic()
        phase.code = runner(phase.argv, phase.log, limit_seconds=max(1.0, left))
        phase.seconds = time.monotonic() - started
        codes.append(phase.code)
    return combine(codes)


class Rerun:
    """What the solo re-run did: the ids it took (``eligible``), those that
    passed (``flaky``) and failed again (``refailed``), its Phase, or why it
    did not run (``skipped``)."""

    def __init__(self) -> None:
        self.eligible: list[str] = []
        self.flaky: list[str] = []
        self.refailed: list[str] = []
        self.skipped = ""
        self.phase: Phase | None = None


def rerun_eligible(phases: list[Phase]) -> list[str]:
    """The failed ids the solo re-run may take: the SERIAL phase's (its
    selection is exactly the ``process``/``mcp_server``/``loopback`` tests).
    A parallel-phase failure is an unmarked test's and is never re-run."""
    out: list[str] = []
    for phase in phases:
        if phase.name == "serial" and phase.code is not None:
            out += [i for i in failed_ids(_read(phase.log)) if i not in out]
    return out


def solo_rerun(phases: list[Phase], code: int, deadline: float, extra: list[str], label: str,
               runner: Any = None, cap: int = MAX_RERUN) -> tuple[int, Rerun]:
    """The failure rule, automated (module docstring): re-run the eligible
    ids once, serially, and return ``(the run's exit code, what happened)``."""
    runner = runner or run_bounded
    result = Rerun()
    if code != 1:
        return code, result
    texts = [_read(phase.log) for phase in phases]
    if any(STORAGE_MARK in t or STORAGE_SERIAL_MARK in t for t in texts):
        result.skipped = "the owner's storage changed: nothing is re-run"
        return code, result
    unmarked = [i for phase, t in zip(phases, texts) if phase.name != "serial" for i in failed_ids(t)]
    if unmarked or any(p.code not in (None, 0, 5) for p in phases if p.name != "serial"):
        result.skipped = "a parallel-phase (unmarked) test failed: a real failure, never re-run"
        return code, result
    result.eligible = rerun_eligible(phases)
    if not result.eligible:
        result.skipped = "no failed id to re-run"
        return code, result
    if len(result.eligible) > cap:
        result.skipped = (f"{len(result.eligible)} failed, over the {cap} the re-run takes: "
                          "the machine is stalling, not the tests")
        return code, result
    left = deadline - time.monotonic()
    if left < MIN_PHASE_SECONDS:
        result.skipped = "no time left under the run's limit"
        return code, result
    basetemp = basetemp_for(f"{label}-rerun")
    phase = Phase("rerun", _base_argv(basetemp) + list(result.eligible) + list(extra), basetemp,
                  basetemp.with_name(basetemp.name + ".log"))
    started = time.monotonic()
    phase.code = runner(phase.argv, phase.log, limit_seconds=max(1.0, left))
    phase.seconds = time.monotonic() - started
    result.phase = phase
    again = failed_ids(_read(phase.log))
    if phase.code == 0:
        result.flaky = list(result.eligible)
        return 0, result
    if phase.code == 1:
        result.refailed = [i for i in result.eligible if i in again] or list(result.eligible)
        result.flaky = [i for i in result.eligible if i not in result.refailed]
        return 1, result
    result.refailed = list(result.eligible)
    return combine([code, phase.code]), result


def _last_summary(text: str) -> list[str]:
    """The lines after the LAST ``short test summary info`` heading (an
    inner pytester session prints its own earlier, in a captured section)."""
    lines = text.splitlines()
    marks = [i for i, line in enumerate(lines) if line.startswith("=") and "short test summary info" in line]
    return lines[marks[-1] + 1:] if marks else []


def _nodeid(rest: str) -> str:
    """The node id at the start of a ``FAILED``/``ERROR`` line's remainder:
    up to the first `` - `` that leaves the brackets balanced, ``@group``
    (xdist's loadgroup suffix) dropped."""
    cut = len(rest)
    start = 0
    while True:
        at = rest.find(" - ", start)
        if at < 0:
            break
        if rest[:at].count("[") == rest[:at].count("]"):
            cut = at
            break
        start = at + 3
    nodeid = rest[:cut].strip()
    if nodeid.rfind("@") > nodeid.rfind("]"):
        nodeid = nodeid[:nodeid.rfind("@")]
    return nodeid


def failed_ids(text: str) -> list[str]:
    """Every failed or errored id in a log's (outer) summary, once each, in order."""
    out: list[str] = []
    for line in _last_summary(text):
        for kind in ("FAILED ", "ERROR "):
            if line.startswith(kind):
                nodeid = _nodeid(line[len(kind):])
                if nodeid and nodeid not in out:
                    out.append(nodeid)
    return out


def _stats_line(text: str) -> str:
    for line in reversed(text.splitlines()):
        stripped = line.strip("= ").strip()
        if any(word in stripped for word in (" passed", " failed", " error", "no tests ran", " skipped")):
            return stripped
    return "(no result line)"


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def summarize(phases: list[Phase], rerun: Rerun | None = None) -> list[str]:
    """The run's summary: each phase's result line and minutes (the solo
    re-run's too); every ``STORAGE CHECK FAILED`` line; the ``FLAKY (passed
    on solo re-run):`` ids; every id still failed, with a command that
    re-runs it alone."""
    out: list[str] = []
    failed: list[str] = []
    rerun = rerun or Rerun()
    shown = list(phases) + ([rerun.phase] if rerun.phase is not None else [])
    for phase in shown:
        text = _read(phase.log)
        if phase.code is None:
            out.append(f"[{phase.name}] not run")
            continue
        out.append(f"[{phase.name}] exit {phase.code} in {phase.seconds / 60:.1f} min: {_stats_line(text)}"
                   f"  (log: {phase.log})")
        out += [f"[{phase.name}] {line.strip()}" for line in text.splitlines() if STORAGE_MARK in line]
        if phase.name != "rerun":
            failed += [i for i in failed_ids(text) if i not in failed]
    if rerun.skipped:
        out.append(f"solo re-run: not run ({rerun.skipped})")
    if rerun.flaky:
        out.append(f"FLAKY (passed on solo re-run): {len(rerun.flaky)}")
        out += [f"  {nodeid}" for nodeid in rerun.flaky]
    failed = [i for i in failed if i not in rerun.flaky]
    if failed:
        out.append(f"{len(failed)} failed; each alone (a test that needs its module's earlier tests: its file):")
        script = "python scripts/run_tests.py files"
        out += [f'  {script} "{nodeid}"' for nodeid in failed]
        files = sorted({nodeid.split("::", 1)[0] for nodeid in failed})
        out.append(f"  {script} {' '.join(files)}")
    return out


def build_argv(args: argparse.Namespace) -> list[str]:
    """The pytest command line for ``fast``/``full``/``files``. Sets
    ``args.basetemp`` to the fresh basetemp it names."""
    args.basetemp = basetemp_for(args.label)
    argv = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
            f"--basetemp={args.basetemp}", "--durations=25"]
    if args.cmd == "full":
        argv.append("--full")
    if args.cmd == "files":
        argv += list(args.paths)
    if getattr(args, "workers", 0):
        argv += ["-n", str(args.workers), "--dist", "loadgroup"]
    return argv + list(args.extra)


# -- the bounded run ------------------------------------------------------------------


def _start(argv: list[str], out: IO[str]) -> tuple[subprocess.Popen, Job | None]:
    if os.name == "nt":
        job = Job()
        try:
            proc = subprocess.Popen(argv, cwd=str(ROOT), stdout=out, stderr=subprocess.STDOUT,
                                    creationflags=CREATE_SUSPENDED)
        except BaseException:
            job.close()
            raise
        try:
            job.adopt(proc)
        except BaseException:
            proc.kill()  # through its handle; still suspended, it has started nothing
            proc.wait()
            job.close()
            raise
        return proc, job
    proc = subprocess.Popen(argv, cwd=str(ROOT), stdout=out, stderr=subprocess.STDOUT,
                            start_new_session=True)
    return proc, None


def _exited(proc: subprocess.Popen, seconds: float) -> bool:
    """Whether ``proc`` exits within ``seconds``. On POSIX it is NOT reaped
    (``WNOWAIT``), so its pid -- its process group's id -- stays held."""
    if os.name == "nt":
        try:
            proc.wait(timeout=seconds)
            return True
        except subprocess.TimeoutExpired:
            return False
    deadline = time.monotonic() + seconds
    while True:
        try:
            got = os.waitid(os.P_PID, proc.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
        except ChildProcessError:
            return True  # already reaped (never by this module: defensive)
        if got is not None:
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.2)


def _signal_group(proc: subprocess.Popen, signum: int) -> None:
    """Signal the process group ``proc`` leads (POSIX), while its pid is held."""
    if proc.returncode is not None:
        return  # reaped: the group id is no longer ours to name
    try:
        os.killpg(proc.pid, signum)
    except (ProcessLookupError, PermissionError):
        pass


def _interrupt_leader(proc: subprocess.Popen) -> None:
    """SIGINT to pytest alone (POSIX), while it is unreaped: pytest turns it
    into KeyboardInterrupt and runs every fixture's teardown, which is what
    stops a child in a session of its own (the hosted supervisor). Not
    ``proc.send_signal``: that polls first, and a poll would reap the leader
    and give up the group id."""
    if proc.returncode is not None or _exited(proc, 0):
        return
    try:
        os.kill(proc.pid, signal.SIGINT)  # our own unreaped child: its pid cannot have changed hands
    except (ProcessLookupError, PermissionError):
        pass


def _stop_posix(proc: subprocess.Popen) -> None:
    """The POSIX stop, leader unreaped throughout: SIGINT to pytest and up to
    ``_GRACE_SECONDS`` for its teardowns; then SIGTERM to the group and a
    fixed ``_MEMBER_GRACE_SECONDS`` (a zombie leader still counts as a member,
    so the group cannot be polled empty); then SIGKILL to the group; then
    reap. A child in another session is reached only through the teardowns
    (or its own lifeline, tests/hosting_instance.py)."""
    _interrupt_leader(proc)
    _exited(proc, _GRACE_SECONDS)
    _signal_group(proc, signal.SIGTERM)
    time.sleep(_MEMBER_GRACE_SECONDS)
    _signal_group(proc, signal.SIGKILL)
    proc.wait()


def run_bounded(argv: list[str], log: Path, limit_seconds: float) -> int:
    """Run ``argv`` with its output to ``log``; past the limit, stop it and
    every process it started (module docstring) and return EXIT_LIMIT.
    When it ends on its own, anything it left running is ended too, and so
    it is when this function is interrupted (Ctrl+C) or fails."""
    if os.name != "nt" and not hasattr(os, "waitid"):
        raise SystemExit("run_tests.py needs os.waitid (Linux; macOS from Python 3.13)")
    log.parent.mkdir(parents=True, exist_ok=True)
    with open(log, "w", encoding="utf-8", errors="replace") as out:
        out.write(f"$ {' '.join(argv)}\n")
        out.flush()
        proc, job = _start(argv, out)
        try:
            if _exited(proc, limit_seconds):
                if job is None:
                    _signal_group(proc, signal.SIGKILL)  # leftovers only: the leader has exited
                return proc.wait()
            if job is not None:
                if not job.terminate(EXIT_LIMIT):
                    out.write("\nTerminateJobObject failed; the job's close ends the tree\n")
                try:
                    proc.wait(timeout=_GRACE_SECONDS)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=_GRACE_SECONDS)
            else:
                _stop_posix(proc)
            out.write(f"\nLIMIT: stopped after {limit_seconds:.0f} s (run_tests.py)\n")
            return EXIT_LIMIT
        finally:
            if job is not None:
                job.close()  # ends whatever is still in it, on every path
            elif proc.returncode is None:
                _stop_posix(proc)  # Ctrl+C or an error here: never leave the run detached


# -- the command line ---------------------------------------------------------------------


def parse(argv: list[str] | None) -> argparse.Namespace:
    argv = list(sys.argv[1:] if argv is None else argv)
    extra: list[str] = []
    if "--" in argv:
        cut = argv.index("--")
        argv, extra = argv[:cut], argv[cut + 1:]
    parser = argparse.ArgumentParser(prog="run_tests.py")
    sub = parser.add_subparsers(dest="cmd", required=True)
    ids = sub.add_parser("ids", help="the sorted ids of the full suite")
    ids.add_argument("--out", type=Path)
    ids.add_argument("--compare", type=Path, help="a previous --out file")
    ids.add_argument("--basetemp", type=Path, required=True)
    for name, text in (("fast", "the fast tier (a bare pytest)"), ("full", "every test (--full)"),
                       ("files", "the files or node ids named")):
        run = sub.add_parser(name, help=text)
        if name == "files":
            run.add_argument("paths", nargs="+")
        default_workers = 0 if name == "files" else DEFAULT_WORKERS
        run.add_argument("--workers", type=int, default=default_workers,
                         help=f"pytest-xdist workers (0: serial; default {default_workers})")
        run.add_argument("--label", default="run", help="names the basetemp and the log")
        run.add_argument("--limit-minutes", type=float, default=None,
                         help=f"wall-clock limit for the whole run (default {DEFAULT_LIMITS[name]})")
        run.add_argument("--keep", action="store_true", help="keep the basetemp even when the run passes")
        run.add_argument("--no-rerun", action="store_true",
                         help="no solo re-run of the serial phase's failures (fast/full)")
        run.add_argument("--log", type=Path, default=None,
                         help="the run's log (default <basetemp>.log, copied to <root>/<label>-latest.log)")
    args = parser.parse_args(argv)
    args.extra = extra
    if args.cmd != "ids" and args.limit_minutes is None:
        args.limit_minutes = DEFAULT_LIMITS[args.cmd]
    if extra and args.cmd == "ids":
        parser.error("ids takes no extra pytest arguments")
    return args


def _tail(path: Path, n: int) -> str:
    try:
        return "\n".join(path.read_text(encoding="utf-8", errors="replace").splitlines()[-n:])
    except OSError:
        return ""


def main(argv: list[str] | None = None) -> int:
    args = parse(argv)
    if args.cmd == "ids":
        got = collected_ids(args.basetemp)
        if args.out:
            args.out.write_text("\n".join(got) + "\n", encoding="utf-8")
        print(f"{len(got)} ids")
        if args.compare:
            diff = compare(_read_ids(args.compare), got)
            print("\n".join(diff) or "IDENTICAL")
            return 1 if diff else 0
        return 0
    root = basetemp_root()
    root.mkdir(parents=True, exist_ok=True)
    # Each phase its own log beside its own basetemp, so concurrent runs
    # never share one; <label>-latest.log is a copy for convenience only.
    phases = build_phases(args)
    started = time.monotonic()
    deadline = started + args.limit_minutes * 60
    code = run_phases(phases, args.limit_minutes * 60)
    rerun = Rerun()
    if len(phases) > 1 and not args.no_rerun:
        code, rerun = solo_rerun(phases, code, deadline, getattr(args, "rerun_extra", []), args.label)
    took = time.monotonic() - started
    if args.log is None:
        try:
            with open(root / f"{args.label}-latest.log", "w", encoding="utf-8") as latest:
                for phase in phases:
                    latest.write(f"=== {phase.name} ===\n{_read(phase.log)}\n")
        except OSError:
            pass  # another run holds it: each phase's own log is named below
    print(_tail(phases[-1].log if phases[-1].code is not None else phases[0].log, 15))
    print()
    print("\n".join(summarize(phases, rerun)))
    print(f"\nexit {code} in {took / 60:.1f} min")
    for phase in phases + ([rerun.phase] if rerun.phase is not None else []):
        if args.keep or (phase.code not in (0, None) and code != 0):
            print(f"basetemp kept: {phase.basetemp}")
        else:
            shutil.rmtree(phase.basetemp, ignore_errors=True)  # this run's own, never the root
    return code


if __name__ == "__main__":
    raise SystemExit(main())
