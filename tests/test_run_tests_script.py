"""scripts/run_tests.py (v0.21.1): a unique basetemp per run, a hard
wall-clock limit that stops the run's WHOLE process tree (K2: a Job Object
on Windows, a process group on POSIX), and the argv each subcommand builds.
No real suite is started here: the bounded runs are a sleeping interpreter,
a probe grandchild, and a one-test inner pytest.

A probe grandchild reports its identity (pid AND creation time,
tests/process_identity.py) as it starts and carries a unique token on its
command line. "Survived" means a process whose command line carries the
token is still running, or the reported identity is alive; only a reported
identity is ever terminated, in cleanup."""

from __future__ import annotations

import contextlib
import importlib.util
import json
import os
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Iterator

import pytest

from tests.process_identity import alive, created, of_report, terminate

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("run_tests", ROOT / "scripts" / "run_tests.py")
run_tests = importlib.util.module_from_spec(spec)
spec.loader.exec_module(run_tests)

#: Where a creation time cannot be read (macOS), "alive" is never True, so
#: the tree canaries would prove nothing.
needs_identity = pytest.mark.skipif(
    created(os.getpid()) is None, reason="no process creation time on this platform"
)


def test_two_runs_never_share_a_basetemp(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("CLOCKWORK_TEST_BASETEMP_ROOT", str(tmp_path))
    a, b = run_tests.basetemp_for("agent"), run_tests.basetemp_for("agent")
    assert a != b and a.parent == b.parent == tmp_path
    assert a.name.startswith("agent-")


def test_the_basetemp_is_never_under_the_repo(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("CLOCKWORK_TEST_BASETEMP_ROOT", str(ROOT / "data"))
    with pytest.raises(SystemExit):
        run_tests.basetemp_for("x")


@pytest.mark.parametrize("cmd,expect,absent", [
    (["fast"], ["-m", "pytest", "-q"], ["--full"]),
    (["full"], ["--full"], []),
    (["files", "tests/test_imports.py"], ["tests/test_imports.py"], ["--full"]),
])
def test_each_subcommand_builds_its_argv(cmd, expect, absent, tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("CLOCKWORK_TEST_BASETEMP_ROOT", str(tmp_path))
    argv = run_tests.build_argv(run_tests.parse(cmd))
    for word in expect:
        assert word in argv
    for word in absent:
        assert word not in argv
    assert any(a.startswith("--basetemp=") for a in argv)
    assert "-p" in argv and "no:cacheprovider" in argv


@pytest.mark.parametrize("cmd,workers", [
    (["fast", "--workers", "0"], 0),
    (["files", "tests/test_imports.py"], 0),
    (["full", "--workers", "0"], 0),
    (["files", "tests/test_imports.py", "--workers", "3"], 3),
])
def test_fast_and_full_run_on_workers_and_files_serially(cmd, workers, tmp_path, monkeypatch) -> None:
    """v0.21.1 T5: xdist is the wrapper's default for a whole tier, always
    with ``--dist loadgroup`` (tests/tier_plugin.py's groups); ``--workers 0``
    is serial and passes no xdist flag at all."""
    monkeypatch.setenv("CLOCKWORK_TEST_BASETEMP_ROOT", str(tmp_path))
    phases = run_tests.build_phases(run_tests.parse(cmd))
    assert len(phases) == 1  # one run: files and --workers 0 serial
    argv = phases[0].argv
    if workers:
        at = argv.index("-n")
        assert argv[at + 1] == str(workers)
        assert argv[argv.index("--dist") + 1] == "loadgroup"
    else:
        assert "-n" not in argv and "--dist" not in argv


# -- the hybrid full run (T5 fix round 1) ---------------------------------------------------


def _marks(argv: list[str]) -> str:
    """The phase's -m expression (the first -m is ``python -m pytest``)."""
    return argv[argv.index("-m", 3) + 1]


def test_full_is_two_phases_parallel_then_serial(tmp_path, monkeypatch) -> None:
    from tests.tiers import PARALLEL_MARKS, SERIAL_MARKS

    monkeypatch.setenv("CLOCKWORK_TEST_BASETEMP_ROOT", str(tmp_path))
    parallel, serial = run_tests.build_phases(run_tests.parse(["full", "--label", "h", "--", "-x"]))
    assert (parallel.name, serial.name) == ("parallel", "serial")
    assert _marks(parallel.argv) == PARALLEL_MARKS == f"not ({SERIAL_MARKS})"
    assert _marks(serial.argv) == f"({SERIAL_MARKS})"
    assert parallel.argv[parallel.argv.index("-n") + 1] == str(run_tests.DEFAULT_WORKERS)
    assert parallel.argv[parallel.argv.index("--dist") + 1] == "loadgroup"
    assert "-n" not in serial.argv and "--dist" not in serial.argv
    for phase in (parallel, serial):
        assert "--full" in phase.argv and phase.argv[-1] == "-x"
        assert f"--basetemp={phase.basetemp}" in phase.argv
        assert phase.log == phase.basetemp.with_name(phase.basetemp.name + ".log")
    assert parallel.basetemp != serial.basetemp
    assert SERIAL_MARKS == "process or mcp_server or loopback"


def test_fast_is_its_tier_in_parallel_then_its_loopback_tail_serially(tmp_path, monkeypatch) -> None:
    """T5 fix round 2: ``fast`` names its tier as an expression in both
    phases (a -m is a selection of its own), so the serial tail holds only
    the fast tier's loopback and mcp_server tests."""
    from tests.tiers import FAST_MARKS, SERIAL_MARKS

    monkeypatch.setenv("CLOCKWORK_TEST_BASETEMP_ROOT", str(tmp_path))
    parallel, serial = run_tests.build_phases(run_tests.parse(["fast"]))
    assert _marks(parallel.argv) == f"({FAST_MARKS}) and not ({SERIAL_MARKS})"
    assert _marks(serial.argv) == f"({FAST_MARKS}) and ({SERIAL_MARKS})"
    assert "-n" in parallel.argv and "-n" not in serial.argv
    assert FAST_MARKS == "not slow and not process"
    a, _ = run_tests.build_phases(run_tests.parse(["fast", "--", "-m", "hosted"]))
    assert _marks(a.argv) == f"(({FAST_MARKS}) and (hosted)) and not ({SERIAL_MARKS})"


@pytest.mark.parametrize("extra,parallel,serial", [
    (["-m", "slow"], "(slow) and not (process or mcp_server or loopback)",
     "(slow) and (process or mcp_server or loopback)"),
    (["-mprocess"], "(process) and not (process or mcp_server or loopback)",
     "(process) and (process or mcp_server or loopback)"),
    (["-m", "a", "-m", "b"], "((a) and (b)) and not (process or mcp_server or loopback)",
     "((a) and (b)) and (process or mcp_server or loopback)"),
])
def test_a_users_marker_expression_is_joined_into_each_phase(extra, parallel, serial, tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("CLOCKWORK_TEST_BASETEMP_ROOT", str(tmp_path))
    a, b = run_tests.build_phases(run_tests.parse(["full", "--", *extra, "-x"]))
    assert (_marks(a.argv), _marks(b.argv)) == (parallel, serial)
    assert a.argv.count("-m") == b.argv.count("-m") == 2 and a.argv[-1] == "-x"  # pytest's, the phase's


@pytest.mark.parametrize("extra", [["-n", "4"], ["-n4"], ["--dist", "load"], ["--dist=load"], ["-p", "xdist"]])
def test_xdist_flags_after_the_double_dash_are_refused(extra, tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("CLOCKWORK_TEST_BASETEMP_ROOT", str(tmp_path))
    with pytest.raises(SystemExit, match="--workers"):
        run_tests.build_phases(run_tests.parse(["full", "--", *extra]))


@pytest.mark.parametrize("codes,want", [
    ([0, 0], 0), ([1, 0], 1), ([0, 1], 1), ([5, 0], 0), ([0, 5], 0), ([5, 5], 5),
    ([1, 124], 124), ([124], 124), ([2, 1], 2), ([1, 2], 2), ([3, 1], 3), ([1, 4], 1),
    ([4, 3], 4), ([0], 0), ([], 0),
])
def test_combine(codes, want) -> None:
    assert run_tests.combine(codes) == want


_CLOCK = [1000.0]


class _FakeRun:
    """``run_bounded``'s stand-in: answers ``codes`` in turn, records each
    limit it was given, and moves the fake clock ``spend`` seconds."""

    def __init__(self, codes: list[int], spend: float = 0.0) -> None:
        self.codes, self.spend, self.limits = list(codes), spend, []

    def __call__(self, argv: list[str], log: Path, limit_seconds: float) -> int:
        self.limits.append(limit_seconds)
        _CLOCK[0] += self.spend
        return self.codes.pop(0)


def _phases(tmp_path: Path) -> list[Any]:
    return [run_tests.Phase(n, ["x"], tmp_path / n, tmp_path / f"{n}.log") for n in ("parallel", "serial")]


def test_both_phases_share_one_deadline(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(run_tests.time, "monotonic", lambda: _CLOCK[0])
    fake = _FakeRun([1, 0], spend=400.0)
    phases = _phases(tmp_path)
    assert run_tests.run_phases(phases, 1000.0, runner=fake) == 1  # a failure in A: B still runs
    assert fake.limits == [1000.0, 600.0]
    assert [p.code for p in phases] == [1, 0]


@pytest.mark.parametrize("first", [124, 2, 3, 4])
def test_the_serial_phase_never_runs_after_a_limit_an_interrupt_or_an_error(first, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(run_tests.time, "monotonic", lambda: _CLOCK[0])
    fake = _FakeRun([first, 0])
    phases = _phases(tmp_path)
    assert run_tests.run_phases(phases, 1000.0, runner=fake) == first
    assert len(fake.limits) == 1 and phases[1].code is None


def test_the_serial_phase_is_skipped_as_a_limit_with_under_a_minute_left(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(run_tests.time, "monotonic", lambda: _CLOCK[0])
    fake = _FakeRun([0, 0], spend=950.0)
    phases = _phases(tmp_path)
    assert run_tests.run_phases(phases, 1000.0, runner=fake) == run_tests.EXIT_LIMIT
    assert len(fake.limits) == 1 and phases[1].code == run_tests.EXIT_LIMIT


_LOG = (
    "================ short test summary info ================\n"
    "FAILED t/test_inner.py::test_x - assert False\n"
    "=========== 1 failed in 0.1s ===========\n"
    "(an inner pytester session, captured above the outer summary)\n"
    "=========================== short test summary info ===========================\n"
    "FAILED tests/test_a.py::test_one@tests/test_a.py::instance - AssertionError: no - thing\n"
    "ERROR tests/test_b.py::test_two[x - y]@mcp_port - TimeoutError\n"
    "FAILED tests/test_c.py::test_three[p] - assert 1 == 2\n"
    "ERROR tests/test_b.py::test_two[x - y]@mcp_port - teardown\n"
    "STORAGE CHECK FAILED: the suite changed the owner's real storage\n"
    "=========== 2 failed, 6400 passed, 25 skipped, 2 errors in 400.00s ===========\n"
)


def test_failed_ids_come_from_the_outer_summary_with_the_group_dropped() -> None:
    assert run_tests.failed_ids(_LOG) == [
        "tests/test_a.py::test_one", "tests/test_b.py::test_two[x - y]", "tests/test_c.py::test_three[p]",
    ]


def test_the_summary_names_each_phase_the_storage_line_and_a_solo_rerun_for_each_failure(tmp_path) -> None:
    phases = _phases(tmp_path)
    phases[0].log.write_text(_LOG, encoding="utf-8")
    phases[1].log.write_text("==== 154 passed in 300.00s ====\n", encoding="utf-8")
    phases[0].code, phases[0].seconds, phases[1].code, phases[1].seconds = 1, 420.0, 0, 300.0
    text = "\n".join(run_tests.summarize(phases))
    assert "[parallel] exit 1 in 7.0 min: 2 failed, 6400 passed, 25 skipped, 2 errors in 400.00s" in text
    assert "[serial] exit 0 in 5.0 min: 154 passed in 300.00s" in text
    assert "[parallel] STORAGE CHECK FAILED: the suite changed" in text
    for nodeid in ("tests/test_a.py::test_one", "tests/test_b.py::test_two[x - y]", "tests/test_c.py::test_three[p]"):
        assert f'python scripts/run_tests.py files "{nodeid}"' in text
    assert "python scripts/run_tests.py files tests/test_a.py tests/test_b.py tests/test_c.py" in text


# -- the solo re-run (T5 fix round 3) --------------------------------------------------------


def _summary_log(*lines: str, stats: str = "1 failed, 10 passed in 1.00s") -> str:
    head = "=========================== short test summary info ===========================\n"
    return head + "".join(f"{line}\n" for line in lines) + f"======= {stats} =======\n"


def _ran(tmp_path: Path, parallel: str, serial: str, codes: tuple[int, int] = (0, 1)) -> list[Any]:
    phases = _phases(tmp_path)
    phases[0].log.write_text(parallel, encoding="utf-8")
    phases[1].log.write_text(serial, encoding="utf-8")
    phases[0].code, phases[1].code = codes
    return phases


class _Rerunner:
    """A fake ``run_bounded`` for the re-run: records its argv and writes
    ``log_text`` as the re-run's log."""

    def __init__(self, code: int, log_text: str) -> None:
        self.code, self.text, self.argvs = code, log_text, []

    def __call__(self, argv: list[str], log: Path, limit_seconds: float) -> int:
        self.argvs.append(argv)
        log.write_text(self.text, encoding="utf-8")
        return self.code


_SERIAL_FAIL = _summary_log(
    "FAILED tests/test_hosting_bus.py::test_a - ConnectTimeout",
    "ERROR tests/test_frontdoor_socketio.py::test_b[x - y] - TimeoutError",
)


def test_only_the_serial_phase_s_failures_are_eligible(tmp_path) -> None:
    phases = _ran(tmp_path, _summary_log("FAILED tests/test_pure.py::test_p - assert 1"), _SERIAL_FAIL)
    assert run_tests.rerun_eligible(phases) == [
        "tests/test_hosting_bus.py::test_a", "tests/test_frontdoor_socketio.py::test_b[x - y]",
    ]


def test_every_eligible_id_passing_alone_makes_the_run_pass_and_is_reported_flaky(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("CLOCKWORK_TEST_BASETEMP_ROOT", str(tmp_path))
    phases = _ran(tmp_path, _summary_log(stats="5 passed"), _SERIAL_FAIL)
    fake = _Rerunner(0, "==== 2 passed in 3.00s ====\n")
    code, rerun = run_tests.solo_rerun(phases, 1, time.monotonic() + 600, ["-x"], "lbl", runner=fake)
    assert code == 0
    assert rerun.flaky == ["tests/test_hosting_bus.py::test_a", "tests/test_frontdoor_socketio.py::test_b[x - y]"]
    argv = fake.argvs[0]
    assert "tests/test_frontdoor_socketio.py::test_b[x - y]" in argv and argv[-1] == "-x"
    assert "-n" not in argv and "-m" not in argv[3:]
    text = "\n".join(run_tests.summarize(phases, rerun))
    assert "FLAKY (passed on solo re-run): 2" in text
    assert "  tests/test_hosting_bus.py::test_a" in text
    assert "[rerun] exit 0" in text
    assert "failed; each alone" not in text


def test_a_test_that_fails_again_stays_a_failure(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("CLOCKWORK_TEST_BASETEMP_ROOT", str(tmp_path))
    phases = _ran(tmp_path, _summary_log(stats="5 passed"), _SERIAL_FAIL)
    fake = _Rerunner(1, _summary_log("FAILED tests/test_hosting_bus.py::test_a - again"))
    code, rerun = run_tests.solo_rerun(phases, 1, time.monotonic() + 600, [], "lbl", runner=fake)
    assert code == 1
    assert rerun.refailed == ["tests/test_hosting_bus.py::test_a"]
    assert rerun.flaky == ["tests/test_frontdoor_socketio.py::test_b[x - y]"]
    text = "\n".join(run_tests.summarize(phases, rerun))
    assert 'files "tests/test_hosting_bus.py::test_a"' in text
    assert 'files "tests/test_frontdoor_socketio.py::test_b[x - y]"' not in text


@pytest.mark.parametrize("parallel,code,why", [
    (_summary_log("FAILED tests/test_pure.py::test_p - assert 1"), 1, "unmarked"),
    (_summary_log("STORAGE CHECK FAILED: the suite changed the owner's real storage"), 1, "storage"),
])
def test_an_unmarked_failure_or_a_storage_change_is_never_re_run(parallel, code, why, tmp_path) -> None:
    phases = _ran(tmp_path, parallel, _SERIAL_FAIL, codes=(1, 1))
    fake = _Rerunner(0, "")
    got, rerun = run_tests.solo_rerun(phases, code, time.monotonic() + 600, [], "lbl", runner=fake)
    assert got == 1 and not fake.argvs and why in rerun.skipped


@pytest.mark.parametrize("code", [0, 2, 3, 4, run_tests.EXIT_LIMIT])
def test_only_an_exit_of_1_is_re_run(code, tmp_path) -> None:
    phases = _ran(tmp_path, _summary_log(stats="5 passed"), _SERIAL_FAIL)
    fake = _Rerunner(0, "")
    assert run_tests.solo_rerun(phases, code, time.monotonic() + 600, [], "lbl", runner=fake)[0] == code
    assert not fake.argvs


def test_more_than_the_cap_is_not_re_run_and_the_run_fails(tmp_path) -> None:
    many = [f"FAILED tests/test_hosting_bus.py::test_{n} - x" for n in range(run_tests.MAX_RERUN + 1)]
    phases = _ran(tmp_path, _summary_log(stats="5 passed"), _summary_log(*many))
    fake = _Rerunner(0, "")
    code, rerun = run_tests.solo_rerun(phases, 1, time.monotonic() + 600, [], "lbl", runner=fake)
    assert code == 1 and not fake.argvs
    assert "the machine is stalling, not the tests" in rerun.skipped
    assert run_tests.MAX_RERUN == 40
    assert "solo re-run: not run (41 failed" in "\n".join(run_tests.summarize(phases, rerun))


def test_no_re_run_without_the_time_for_it(tmp_path) -> None:
    phases = _ran(tmp_path, _summary_log(stats="5 passed"), _SERIAL_FAIL)
    fake = _Rerunner(0, "")
    code, rerun = run_tests.solo_rerun(phases, 1, time.monotonic() + 10, [], "lbl", runner=fake)
    assert code == 1 and not fake.argvs and "no time" in rerun.skipped


def test_no_rerun_is_an_option() -> None:
    assert run_tests.parse(["full", "--no-rerun"]).no_rerun is True
    assert run_tests.parse(["fast"]).no_rerun is False


def test_extra_arguments_follow_the_double_dash_and_limits_default_per_command(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("CLOCKWORK_TEST_BASETEMP_ROOT", str(tmp_path))
    args = run_tests.parse(["files", "tests/a.py", "--label", "mine", "--", "-x", "-k", "thing"])
    argv = run_tests.build_argv(args)
    assert argv[-3:] == ["-x", "-k", "thing"]
    assert args.limit_minutes == run_tests.DEFAULT_LIMITS["files"]
    assert args.basetemp.name.startswith("mine-") and f"--basetemp={args.basetemp}" in argv
    assert run_tests.parse(["full", "--limit-minutes", "5"]).limit_minutes == 5


@pytest.mark.process
def test_a_run_past_its_limit_is_stopped_through_its_handle(tmp_path) -> None:
    log = tmp_path / "run.log"
    code = run_tests.run_bounded([sys.executable, "-c", "import time; time.sleep(60)"],
                                 log, limit_seconds=2)
    assert code == run_tests.EXIT_LIMIT
    assert "LIMIT" in log.read_text(encoding="utf-8")


# -- the tree canaries (K2, K6) ----------------------------------------------------------

#: The probe: notes its identity to argv[2], then sleeps. argv[1] is the token.
_PROBE = (
    "import json, sys, time\n"
    "from tests.process_identity import report\n"
    "open(sys.argv[2] + '.tmp', 'w').write(json.dumps(report()))\n"
    "import os; os.replace(sys.argv[2] + '.tmp', sys.argv[2])\n"
    "time.sleep(120)\n"
)

#: Starts the probe, waits until it has reported, then sleeps (K2) or exits.
_PARENT = (
    "import os, subprocess, sys, time\n"
    "probe, token, report, then = sys.argv[1:5]\n"
    "subprocess.Popen([sys.executable, '-c', probe, token, report])\n"
    "deadline = time.monotonic() + 30\n"
    "while not os.path.exists(report) and time.monotonic() < deadline:\n"
    "    time.sleep(0.05)\n"
    "print('PROBE UP', flush=True)\n"
    "if then == 'sleep':\n"
    "    time.sleep(60)\n"
)


def _token() -> str:
    return f"clockworkprobe{uuid.uuid4().hex}"


def _by_command_line(token: str) -> list[str]:
    """Every running process whose command line carries ``token`` (never this one)."""
    if os.name == "nt":
        half = len(token) // 2
        # The token is joined inside PowerShell, so its own command line never carries it.
        script = (
            f"$t = '{token[:half]}' + '{token[half:]}'; "
            "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -and "
            "$_.CommandLine.Contains($t) } | ForEach-Object { \"$($_.ProcessId) $($_.CommandLine)\" }"
        )
        done = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                              capture_output=True, text=True, timeout=120)
        return [line for line in done.stdout.splitlines() if line.strip()]
    found = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit() or int(entry.name) == os.getpid():
            continue
        try:
            cmd = (entry / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
        except OSError:
            continue
        if token in cmd:
            found.append(f"{entry.name} {cmd}")
    return found




def _identity_in(path: Path) -> Any:
    return of_report(json.loads(path.read_text(encoding="utf-8")))


def _reap(report: Path) -> None:
    """Quiet cleanup: end the probe through its reported, verified identity."""
    if report.exists():
        identity = _identity_in(report)
        if alive(identity):
            terminate(identity)


def _assert_gone(token: str, report: Path) -> None:
    """The probe started (it reported), and neither its identity nor any
    process carrying its token is running. A survivor is terminated through
    its verified identity before the assertion fails."""
    assert report.exists(), "the probe grandchild never started; the canary would prove nothing"
    identity = _identity_in(report)
    assert identity.created is not None
    deadline = time.monotonic() + 15
    while alive(identity) and time.monotonic() < deadline:
        time.sleep(0.2)
    left = _by_command_line(token)
    still = alive(identity)
    if still:
        terminate(identity)
    assert not still and not left, f"survived: identity {identity} alive={still}; by command line {left}"


@contextlib.contextmanager
def _no_survivor(token: str, report: Path) -> Iterator[None]:
    """The body, then ``_assert_gone``. If the body fails, its failure is the
    one reported: the probe is only reaped, never asserted over it."""
    try:
        yield
    except BaseException:
        _reap(report)
        raise
    _assert_gone(token, report)


def _wait_for(path: Path, seconds: float = 60) -> None:
    deadline = time.monotonic() + seconds
    while not path.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert path.exists(), f"{path.name} never appeared"


@needs_identity
@pytest.mark.process
@pytest.mark.parametrize("then", ["sleep", "exit"], ids=["overrun", "ends-on-its-own"])
def test_a_bounded_run_leaves_no_grandchild(tmp_path, then) -> None:
    """K2: past the limit the WHOLE tree is stopped, not just the process
    the handle names; and a run that ends on its own takes what it left
    running with it."""
    token, report, log = _token(), tmp_path / "probe.json", tmp_path / "run.log"
    with _no_survivor(token, report):
        code = run_tests.run_bounded(
            [sys.executable, "-c", _PARENT, _PROBE, token, str(report), then], log, limit_seconds=8
        )
        text = log.read_text(encoding="utf-8")
        assert "PROBE UP" in text, text
        if then == "sleep":
            assert code == run_tests.EXIT_LIMIT and "LIMIT" in text
        else:
            assert code == 0


#: The inner suite's conftest: the real add_time_limits with a tier limit a
#: canary can wait out; optionally the conftest's session Job Object (what
#: tests/conftest.py does at pytest_configure); and the session's identity,
#: so the outer test can kill it through a verified handle.
_INNER_CONFTEST = '''
import json
import signal
import tests.tier_plugin as tier_plugin
tier_plugin.TIER_LIMIT = {limit}
def pytest_configure(config):
    if {contained!r}:
        from tests.process_jobs import contain_session
        contain_session()
    from tests.process_identity import report
    with open({session!r} + ".tmp", "w") as out:
        out.write(json.dumps(report()))
    import os; os.replace({session!r} + ".tmp", {session!r})
'''

_INNER_TEST = '''
import os, subprocess, sys, time
import pytest

@pytest.fixture
def probe():
    kwargs = {{}}
    if {own_session!r}:  # outside the run's process group (as the hosted supervisor is)
        kwargs = ({{"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}} if os.name == "nt"
                  else {{"start_new_session": True}})
    proc = subprocess.Popen([sys.executable, "-c", {probe!r}, {token!r}, {report!r}], **kwargs)
    deadline = time.monotonic() + 30
    while not os.path.exists({report!r}) and time.monotonic() < deadline:
        time.sleep(0.05)
    print("PROBE UP", flush=True)
    yield proc
    proc.kill()  # a finalizer: the thread method's os._exit never runs it
    proc.wait()

@pytest.mark.process
def test_stalls_holding_a_child(probe):
    time.sleep(120)
'''


def _inner_suite(tmp_path: Path, token: str, report: Path, *, limit: int = 3,
                 contained: bool = False, own_session: bool = False) -> list[str]:
    suite = tmp_path / "inner"
    suite.mkdir()
    session = tmp_path / "session.json"
    (suite / "pytest.ini").write_text(
        "[pytest]\ntimeout_method = thread\nmarkers =\n    slow: s\n    process: p\n", encoding="utf-8")
    (suite / "conftest.py").write_text(
        _INNER_CONFTEST.format(limit=limit, contained=contained, session=str(session)), encoding="utf-8")
    (suite / "test_inner.py").write_text(
        _INNER_TEST.format(probe=_PROBE, token=token, report=str(report), own_session=own_session),
        encoding="utf-8")
    return [sys.executable, "-m", "pytest", "-s", "-c", str(suite / "pytest.ini"), "--rootdir", str(suite),
            "-p", "tests.tier_plugin", "-p", "no:cacheprovider", f"--basetemp={tmp_path / 'bt'}",
            str(suite / "test_inner.py")]


@needs_identity
@pytest.mark.process
def test_a_timed_out_tests_child_does_not_outlive_a_bounded_run(tmp_path) -> None:
    """K6: a `process` test that times out while its fixture holds a child,
    with NO session job of its own. Under run_tests.py no child survives:
    on Windows the thread method's os._exit skips the finalizer and the run's
    Job Object ends the orphan; on POSIX the signal method lets the
    finalizer run (and the group signal is the backstop)."""
    token, report, log = _token(), tmp_path / "probe.json", tmp_path / "run.log"
    with _no_survivor(token, report):
        code = run_tests.run_bounded(_inner_suite(tmp_path, token, report), log, limit_seconds=120)
        text = log.read_text(encoding="utf-8")
        assert code not in (0, run_tests.EXIT_LIMIT), text
        assert "Timeout" in text, text


@needs_identity
@pytest.mark.process
def test_a_bare_session_whose_test_times_out_leaves_no_child(tmp_path) -> None:
    """K6 with no wrapper at all (a bare `pytest`, as tests/conftest.py
    configures it): on Windows the session's own Job Object ends the child
    the thread method's os._exit orphaned; on POSIX the signal method lets
    the timed-out test's fixture stop it."""
    token, report = _token(), tmp_path / "probe.json"
    with _no_survivor(token, report):
        done = subprocess.run(_inner_suite(tmp_path, token, report, contained=True), cwd=str(ROOT),
                              capture_output=True, text=True, timeout=120)
        assert done.returncode != 0 and "Timeout" in done.stdout + done.stderr, done.stdout + done.stderr


@needs_identity
@pytest.mark.process
def test_an_overrun_stops_a_child_in_a_session_of_its_own(tmp_path) -> None:
    """Review finding 1: a child outside the run's process group (``setsid``,
    as the hosted supervisor is; CREATE_NEW_PROCESS_GROUP on Windows) is
    still stopped when the RUN overruns. POSIX: the group signal cannot
    reach it, so run_bounded first sends pytest SIGINT and its fixture
    teardown stops the child. Windows: the child is still in the run's job."""
    token, report, log = _token(), tmp_path / "probe.json", tmp_path / "run.log"
    with _no_survivor(token, report):
        code = run_tests.run_bounded(
            _inner_suite(tmp_path, token, report, limit=600, own_session=True), log, limit_seconds=15
        )
        text = log.read_text(encoding="utf-8")
        assert "PROBE UP" in text, text
        assert code == run_tests.EXIT_LIMIT and "LIMIT" in text, text


@needs_identity
@pytest.mark.process
@pytest.mark.skipif(os.name != "nt", reason="the session Job Object is Windows-only (POSIX: the signal method)")
def test_a_killed_bare_session_takes_its_descendants(tmp_path) -> None:
    """Controller ruling, item 5: a bare session whose test hangs holding a
    grandchild is killed from outside (its verified identity, as an outer
    bound would); its Job Object ends every descendant with it."""
    token, report, session = _token(), tmp_path / "probe.json", tmp_path / "session.json"
    with _no_survivor(token, report):
        proc = subprocess.Popen(_inner_suite(tmp_path, token, report, limit=600, contained=True),
                                cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            _wait_for(session)
            _wait_for(report)
            assert terminate(_identity_in(session)), "the session could not be killed through its identity"
            proc.wait(timeout=60)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=60)


_LIFELINE_PARENT = (
    "import json, os, subprocess, sys, time\n"
    "from tests.hosting_instance import parent_lifeline\n"
    "from tests.process_identity import report as me\n"
    "probe, token, report, session = sys.argv[1:5]\n"
    "kwargs = parent_lifeline()\n"
    "assert kwargs, 'no lifeline on Linux'\n"
    "subprocess.Popen([sys.executable, '-c', probe, token, report], start_new_session=True, **kwargs)\n"
    "open(session + '.tmp', 'w').write(json.dumps(me())); os.replace(session + '.tmp', session)\n"
    "time.sleep(120)\n"
)


@needs_identity
@pytest.mark.process
@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="PR_SET_PDEATHSIG is Linux-only")
def test_the_hosted_supervisors_lifeline_ends_it_with_its_parent(tmp_path) -> None:
    """Review finding 1(b): a child started with ``parent_lifeline()`` in a
    session of its own (the hosted supervisor's Popen keywords) ends when its
    parent is killed with no teardown at all."""
    token, report, session = _token(), tmp_path / "probe.json", tmp_path / "session.json"
    with _no_survivor(token, report):
        proc = subprocess.Popen([sys.executable, "-c", _LIFELINE_PARENT, _PROBE, token, str(report),
                                 str(session)], cwd=str(ROOT))
        try:
            _wait_for(session)
            _wait_for(report)
            assert terminate(_identity_in(session), signal.SIGKILL)
            proc.wait(timeout=60)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=60)


# -- T5 review F6: an xdist worker's own job -------------------------------------------

_WORKER_CONFTEST = '''
import os
# What tests/conftest.py does at import: a marker naming this process.
os.environ["CLOCKWORK_TEST_SANDBOX"] = str(os.getpid())
def pytest_configure(config):
    if {contained!r}:
        from tests.process_jobs import contain_session, wants_session_job
        if wants_session_job():
            contain_session()
'''

_WORKER_TESTS = '''
import json, os, subprocess, sys, time
import pytest

@pytest.mark.xdist_group("a")
@pytest.mark.timeout(4)
def test_a_dies_holding_a_child():
    subprocess.Popen([sys.executable, "-c", {probe!r}, {token!r}, {report!r}],
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.monotonic() + 30
    while not os.path.exists({report!r}) and time.monotonic() < deadline:
        time.sleep(0.05)
    time.sleep(60)  # the thread method's os._exit ends this worker

@pytest.mark.xdist_group("b")
def test_b_the_child_is_gone_while_the_run_goes_on():
    from tests.process_identity import alive, of_report
    deadline = time.monotonic() + 60
    while not os.path.exists({report!r}) and time.monotonic() < deadline:
        time.sleep(0.05)
    ident = of_report(json.load(open({report!r})))
    deadline = time.monotonic() + 25
    while alive(ident) and time.monotonic() < deadline:
        time.sleep(0.2)
    assert not alive(ident), "SURVIVED its worker"
'''


@needs_identity
@pytest.mark.process
@pytest.mark.skipif(os.name != "nt", reason="a Job Object is Windows'")
@pytest.mark.parametrize("contained", [True, False], ids=["worker-job", "no-worker-job"])
def test_a_dead_workers_child_ends_with_it_not_with_the_run(tmp_path, contained: bool) -> None:
    """F6: one worker's test times out (os._exit) while another worker's
    test watches its child. With the dead worker's own nested job
    (tests/process_jobs.py::wants_session_job, as tests/conftest.py takes
    it) the child is gone while the run goes on. Without one -- the canary
    -- it is still alive, kept only by the controller's job until the run
    ends."""
    token, report = _token(), tmp_path / "probe.json"
    suite = tmp_path / "inner"
    suite.mkdir()
    (suite / "pytest.ini").write_text(
        "[pytest]\ntimeout_method = thread\nmarkers =\n    slow: s\n    process: p\n", encoding="utf-8")
    (suite / "conftest.py").write_text(_WORKER_CONFTEST.format(contained=contained), encoding="utf-8")
    (suite / "test_worker.py").write_text(
        _WORKER_TESTS.format(probe=_PROBE, token=token, report=str(report)), encoding="utf-8")
    argv = [sys.executable, "-m", "pytest", "-c", str(suite / "pytest.ini"), "--rootdir", str(suite),
            "-p", "tests.tier_plugin", "-p", "no:cacheprovider", f"--basetemp={tmp_path / 'bt'}",
            "-n", "2", "--max-worker-restart", "0", "-rA", str(suite / "test_worker.py")]
    log = tmp_path / "inner.log"
    try:
        code = run_tests.run_bounded(argv, log, limit_seconds=150)
        out = log.read_text(encoding="utf-8", errors="replace")
        assert code != run_tests.EXIT_LIMIT, out
        assert report.exists(), out
        b = [line for line in out.splitlines() if "test_b_the_child_is_gone" in line and
             (line.startswith("PASSED") or line.startswith("FAILED"))]
        assert b, out
        if contained:
            assert b[0].startswith("PASSED"), out
        else:
            assert b[0].startswith("FAILED") and "SURVIVED" in out, out
    finally:
        _reap(report)
