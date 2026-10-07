"""The tiers (v0.21.1): a bare run is fast, --full and any explicit
selection run everything, and an unmarked test that starts an interpreter
fails. Uses pytester in-process (runpytest_inprocess) with the tier hooks
loaded on their own (``-p tests.tier_plugin``): the conftest's sandbox does
not nest. Only the guard's own test starts children, and it is `process`."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

from tests.tiers import starts_an_interpreter

pytest_plugins = ["pytester"]

TESTS = Path(__file__).resolve().parent

_TESTS = '''
import pytest
def test_plain(): pass
@pytest.mark.slow
def test_slow(): pass
@pytest.mark.process
def test_process(): pass
'''


@pytest.fixture
def suite(pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch) -> pytest.Pytester:
    # The real tier hooks, loaded as a plugin; the inner session has its own
    # basetemp under the outer one's tmp_path. An outer CLOCKWORK_FULL_SUITE
    # must not decide what the inner bare run selects.
    monkeypatch.delenv("CLOCKWORK_FULL_SUITE", raising=False)
    pytester.makeini("[pytest]\ntestpaths = t\nmarkers =\n    slow: s\n    process: p\n")
    pytester.mkpydir("t")
    (pytester.path / "t" / "test_x.py").write_text(_TESTS, encoding="utf-8")
    return pytester


def _run(suite: pytest.Pytester, *args: str) -> pytest.RunResult:
    return suite.runpytest_inprocess("-p", "tests.tier_plugin", *args)


def test_a_bare_run_leaves_slow_and_process_out(suite) -> None:
    result = _run(suite)
    result.assert_outcomes(passed=1, deselected=2)
    result.stdout.fnmatch_lines(["*FAST TIER: 2 slow/process tests deselected*--full*"])


def test_full_runs_everything(suite) -> None:
    result = _run(suite, "--full")
    result.assert_outcomes(passed=3)
    result.stdout.no_fnmatch_line("*FAST TIER: *deselected*")


def test_the_environment_variable_runs_everything(suite, monkeypatch) -> None:
    monkeypatch.setenv("CLOCKWORK_FULL_SUITE", "1")
    _run(suite).assert_outcomes(passed=3)


def test_an_explicit_path_runs_everything_it_names(suite) -> None:
    _run(suite, "t/test_x.py").assert_outcomes(passed=3)


def test_the_testpaths_directory_named_explicitly_runs_everything(suite) -> None:
    """CI and the start scripts name `tests` (and pass --full too): naming
    the testpaths directory itself is an explicit selection, never bare."""
    _run(suite, "t").assert_outcomes(passed=3)


def test_last_failed_is_the_users_own_selection(suite) -> None:
    """A slow test that failed last must be re-run by a bare ``--lf``, not
    deselected as if it were fixed (review F6)."""
    (suite.path / "t" / "test_x.py").write_text(
        _TESTS.replace("def test_slow(): pass", "def test_slow(): assert False"), encoding="utf-8"
    )
    _run(suite, "--full").assert_outcomes(passed=2, failed=1)
    rerun = _run(suite, "--lf")
    assert rerun.parseoutcomes().get("failed") == 1 and "passed" not in rerun.parseoutcomes()
    rerun.stdout.no_fnmatch_line("*FAST TIER: *deselected*")


def test_a_marker_expression_is_the_users_own(suite) -> None:
    _run(suite, "-m", "slow").assert_outcomes(passed=1, deselected=2)


def test_a_keyword_expression_is_the_users_own(suite) -> None:
    _run(suite, "-k", "slow or process").assert_outcomes(passed=2, deselected=1)


# -- the stall watchdog (T2) ----------------------------------------------------------


def test_every_test_has_a_time_limit_and_the_tiers_get_more(suite) -> None:
    (suite.path / "t" / "test_y.py").write_text(
        "import pytest\n"
        "def test_fast(request):\n"
        "    assert request.node.get_closest_marker('timeout').args[0] == 300\n"
        "@pytest.mark.slow\n"
        "def test_slow(request):\n"
        "    assert request.node.get_closest_marker('timeout').args[0] == 900\n"
        "@pytest.mark.timeout(42)\n"
        "def test_own(request):\n"
        "    assert request.node.get_closest_marker('timeout').args[0] == 42\n",
        encoding="utf-8")
    _run(suite, "--full", "t/test_y.py").assert_outcomes(passed=3)


def test_the_scale_stretches_every_limit(suite, monkeypatch) -> None:
    monkeypatch.setenv("CLOCKWORK_TIMEOUT_SCALE", "2")
    (suite.path / "t" / "test_z.py").write_text(
        "def test_fast(request):\n"
        "    assert request.node.get_closest_marker('timeout').args[0] == 600\n",
        encoding="utf-8")
    _run(suite, "t/test_z.py").assert_outcomes(passed=1)


def test_a_process_test_uses_the_signal_method_where_there_is_one(suite) -> None:
    """K6: the thread method's ``os._exit`` skips fixture finalizers, so a
    `process` test's limit uses SIGALRM where the platform has it (POSIX);
    on Windows it keeps the ini's method and run_tests.py's Job Object
    reaps what it leaves."""
    import signal

    want = "signal" if hasattr(signal, "SIGALRM") else None
    (suite.path / "t" / "test_m.py").write_text(
        "import pytest\n"
        "@pytest.mark.process\n"
        "def test_proc(request):\n"
        f"    assert request.node.get_closest_marker('timeout').kwargs.get('method') == {want!r}\n"
        "def test_plain(request):\n"
        "    assert 'method' not in request.node.get_closest_marker('timeout').kwargs\n",
        encoding="utf-8")
    _run(suite, "t/test_m.py").assert_outcomes(passed=2)


@pytest.mark.process
def test_a_stalled_test_is_stopped_with_its_stacks(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    # K3: the child's rootdir is pytester's tmp dir (no `pythonpath = .`), so
    # `tests` is importable only through PYTHONPATH.
    monkeypatch.setenv("PYTHONPATH", str(TESTS.parent))
    pytester.makeini("[pytest]\ntimeout_method = thread\nmarkers =\n    slow: s\n    process: p\n")
    pytester.makepyfile(test_stall="import pytest, time\n"
                        "@pytest.mark.timeout(2)\n"
                        "def test_stall():\n    time.sleep(60)\n")
    result = pytester.runpytest_subprocess("-p", "tests.tier_plugin", timeout=60)
    assert result.ret != 0
    result.stdout.fnmatch_lines(["*Timeout*"])


_PARTITION_PROBE = '''
from tests.tier_plugin import PARTITION_KEY
def pytest_terminal_summary(terminalreporter, exitstatus, config):
    for tier, ids in sorted(config.stash[PARTITION_KEY].items()):
        terminalreporter.write_line(f"TIER {tier} " + ",".join(i.split("::")[-1] for i in ids))
'''


@pytest.mark.parametrize("args", [(), ("--full",)], ids=["bare", "full"])
def test_the_partition_is_recorded_before_the_fast_tier_filters(suite, args) -> None:
    (suite.path / "t" / "test_y.py").write_text(
        "import pytest\n@pytest.mark.slow\n@pytest.mark.process\ndef test_both(): pass\n",
        encoding="utf-8",
    )
    (suite.path / "conftest.py").write_text(_PARTITION_PROBE, encoding="utf-8")
    result = _run(suite, *args)
    result.stdout.fnmatch_lines([
        "TIER fast test_plain",
        "TIER process test_process,test_both",
        "TIER slow test_slow",
    ])


def test_a_worker_takes_the_controllers_decision_not_its_own_args() -> None:
    """An xdist worker is built from resolved args (``args_source`` is not
    TESTPATHS), so it must read the controller's decision from workerinput."""
    from types import SimpleNamespace

    from tests.tier_plugin import FAST_KEY, WORKERINPUT_KEY, pytest_configure_node, runs_fast_tier

    for decided in (True, False):
        stash = pytest.Stash()
        stash[FAST_KEY] = decided
        config = SimpleNamespace(stash=stash, getoption=lambda name, default=None: default)
        node = SimpleNamespace(config=config, workerinput={})
        pytest_configure_node(node)
        worker = SimpleNamespace(workerinput=node.workerinput)
        assert runs_fast_tier(worker) is decided  # type: ignore[arg-type]


@pytest.mark.parametrize("marks,tier", [
    ((), "fast"), (("slow",), "slow"), (("process",), "process"), (("slow", "process"), "process"),
])
def test_every_test_has_exactly_one_tier(marks, tier) -> None:
    from tests.tiers import tier_of

    assert tier_of(marks) == tier


@pytest.mark.parametrize("args,executable,expected", [
    ([sys.executable, "-c", "pass"], None, True),
    (["python3", "x.py"], None, True),
    (["C:/Python311/python.exe", "-m", "x"], None, True),
    (["gunicorn", "-c", "x"], None, True),
    (["/usr/bin/env", "-m", "gunicorn"], None, True),
    (f'"{sys.executable}" -c pass', None, True),
    (["git", "rev-parse", "HEAD"], None, False),
    (["sh", "-c", "true"], None, False),
    (["docker", "ps"], None, False),
    (["anything"], sys.executable, True),
], ids=[
    "this-interpreter", "python3", "python.exe-path", "gunicorn", "env-m-gunicorn",
    "quoted-string", "git", "sh", "docker", "executable-kwarg",
])
def test_what_counts_as_starting_an_interpreter(args, executable, expected) -> None:
    assert starts_an_interpreter(args, executable) is expected


# -- the process guard -----------------------------------------------------------------

_GUARDED = '''
import subprocess, sys, pytest
def test_unmarked_starts_python():
    subprocess.run([sys.executable, "-c", "pass"], check=True)
@pytest.mark.process
def test_marked_starts_python():
    subprocess.run([sys.executable, "-c", "pass"], check=True)
def test_unmarked_runs_git():
    subprocess.run(["git", "--version"], check=True, capture_output=True)
'''


@pytest.mark.process  # this test's inner session starts real interpreters
def test_an_unmarked_test_that_starts_an_interpreter_fails(pytester: pytest.Pytester) -> None:
    pytester.makeini("[pytest]\nmarkers =\n    slow: s\n    process: p\n")
    pytester.makepyfile(test_guarded=_GUARDED)
    result = pytester.runpytest_inprocess("-p", "tests.tier_plugin", "--full")
    result.assert_outcomes(passed=3, errors=1)
    result.stdout.fnmatch_lines(["*test_unmarked_starts_python*not marked*process*"])


_LOOPBACK = '''
import socket, pytest

def _serve():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen(1)
    s.close()

@pytest.fixture(scope="module")
def server():
    _serve()
    return "up"

@pytest.mark.loopback
def test_marked_binds():
    _serve()
def test_unmarked_binds():
    _serve()
@pytest.mark.process
def test_process_binds():
    _serve()
def test_unmarked_uses_a_fixture_that_bound(server): pass
@pytest.mark.loopback
def test_marked_uses_it(server): pass
def test_later_unmarked_user(server): pass
def test_connects_to_a_dead_port_only():
    s = socket.socket()
    s.settimeout(1)
    s.connect_ex(("127.0.0.1", 9))
    s.close()
def test_binds_elsewhere_is_not_loopback():
    pass
'''


def test_an_unmarked_test_that_binds_a_loopback_server_fails(pytester: pytest.Pytester) -> None:
    """T5 fix round 2: a test (or a fixture it uses) that binds an
    in-process loopback server must be marked ``loopback`` (or ``process``
    / ``mcp_server``), so it runs in the hybrid's serial phase and never
    drifts back to the parallel one. A connect alone (a dead port) is not a
    server and is not held to the marker."""
    pytester.makeini("[pytest]\nmarkers =\n    slow: s\n    process: p\n    mcp_server: m\n    loopback: l\n")
    pytester.makepyfile(test_lb=_LOOPBACK)
    result = pytester.runpytest_inprocess("-p", "tests.tier_plugin", "--full", "-rfE")
    result.assert_outcomes(passed=8, errors=3)  # the three unmarked fail at teardown
    result.stdout.fnmatch_lines([
        "*test_unmarked_binds*bound a loopback server (127.0.0.1:0)*not marked `loopback`*",
        "*test_unmarked_uses_a_fixture_that_bound*bound a loopback server*not marked `loopback`*",
        "*test_later_unmarked_user*uses a fixture `server`*that bound*not marked `loopback`*",
    ])


def test_the_serial_marks_and_the_guard_agree() -> None:
    """Every marker the guard accepts puts a test in the serial phase."""
    from tests.tier_plugin import SERIAL_MARKERS
    from tests.tiers import SERIAL_MARKS

    assert set(SERIAL_MARKS.split(" or ")) == set(SERIAL_MARKERS)


_SHARED = '''
import subprocess, sys, pytest
@pytest.fixture(scope="module")
def instance():
    subprocess.run([sys.executable, "-c", "pass"], check=True)
    return "up"
@pytest.mark.process
def test_first_user_marked(instance): pass
def test_second_user_unmarked(instance): pass
def test_third_user_unmarked(instance): pass
def test_no_fixture(): pass
'''


@pytest.mark.process  # the inner module fixture starts a real interpreter
def test_every_unmarked_user_of_a_fixture_that_starts_one_fails(pytester: pytest.Pytester) -> None:
    """The fixture starts its child once, in its FIRST user's setup; its later
    users start nothing themselves and must fail all the same (review F1)."""
    pytester.makeini("[pytest]\nmarkers =\n    slow: s\n    process: p\n")
    pytester.makepyfile(test_shared=_SHARED)
    result = pytester.runpytest_inprocess("-p", "tests.tier_plugin", "--full")
    result.assert_outcomes(passed=4, errors=2)
    result.stdout.fnmatch_lines(["*test_second_user_unmarked*fixture `instance`*not marked*process*"])
    result.stdout.no_fnmatch_line("*ERROR*test_no_fixture*")
    result.stdout.no_fnmatch_line("*ERROR*test_first_user_marked*")


# -- xdist (T5): groups, and the tiers in real workers ----------------------------------

_GROUPS = '''
import pytest
@pytest.fixture(scope="module")
def measured(): return 1
@pytest.fixture(scope="module")
def other(): return 2
@pytest.fixture(scope="module")
def third(): return 3
def test_free(): pass
def test_uses_measured(measured): pass
def test_also_measured(measured): pass
def test_uses_other(other): pass
def test_third_and_other(third, other): pass
@pytest.mark.mcp_server
def test_mcp(): pass
'''


def test_tests_sharing_a_wide_fixture_share_a_group(pytester: pytest.Pytester) -> None:
    pytester.makeini("[pytest]\nmarkers =\n    slow: s\n    process: p\n    mcp_server: m\n")
    pytester.makepyfile(test_g=_GROUPS)
    from tests.tier_plugin import xdist_group_for, xdist_groups

    items, _ = pytester.inline_genitems("-p", "tests.tier_plugin")
    groups = {item.name: xdist_group_for(item) for item in items}
    assert groups["test_free"] is None
    assert groups["test_uses_measured"] == groups["test_also_measured"] == "test_g.py::measured"
    assert groups["test_uses_other"] == "test_g.py::other"
    assert groups["test_third_and_other"] == "test_g.py::other+third"
    assert groups["test_mcp"] == "mcp_port"
    # The final groups join every two keys a test spans: `other` is built
    # in ONE worker although one of its users also uses `third`.
    final = {item.name: xdist_groups(items).get(item.nodeid) for item in items}
    assert final["test_free"] is None
    assert final["test_uses_other"] == final["test_third_and_other"] == "test_g.py::other"
    assert final["test_uses_measured"] == final["test_also_measured"] == "test_g.py::measured"
    assert final["test_mcp"] == "mcp_port"


def test_an_ungrouped_guard_fixture_does_not_pull_its_module_together(pytester: pytest.Pytester) -> None:
    """F3: a wide fixture in ``UNGROUPED`` (a cheap per-worker guard) groups
    nothing; the module's other wide fixtures still do."""
    from tests.tier_plugin import UNGROUPED, xdist_groups

    assert "_no_supervisor_test_writes_the_real_storage_root" in UNGROUPED
    pytester.makeini("[pytest]\nmarkers =\n    slow: s\n    process: p\n    mcp_server: m\n")
    pytester.makepyfile(test_u="""
import pytest
@pytest.fixture(scope="module", autouse=True)
def _no_supervisor_test_writes_the_real_storage_root(): yield
@pytest.fixture(scope="module")
def instance(): return 1
def test_free(): pass
def test_also_free(): pass
def test_user(instance): pass
""")
    items, _ = pytester.inline_genitems("-p", "tests.tier_plugin")
    groups = xdist_groups(items)
    final = {item.name: groups.get(item.nodeid) for item in items}
    assert final == {"test_free": None, "test_also_free": None, "test_user": "test_u.py::instance"}


@pytest.mark.parametrize("module,fixture", [
    ("test_imports.py", "first_imports"), ("test_simulate_thief.py", "cli_runs"),
])
def test_every_user_of_a_child_batch_shares_one_group(
    pytester: pytest.Pytester, module: str, fixture: str
) -> None:
    """A batch fixture (tests/child_batch.py) starts every SELECTED user's
    child, and under xdist every worker selects the whole collection: its
    users must all run in one worker, or each worker holding one starts the
    whole batch (T4 review, a note for T5). Collected from the real files,
    with the tier hooks alone (no conftest: nothing runs)."""
    from tests.tier_plugin import xdist_groups

    items, _ = pytester.inline_genitems(
        str(TESTS / module), "-p", "tests.tier_plugin", "--noconftest", "-p", "no:cacheprovider"
    )
    users = [item for item in items if fixture in getattr(item, "fixturenames", ())]
    assert len(users) >= 3, [item.nodeid for item in items]
    groups = xdist_groups(items)
    assert {groups.get(item.nodeid) for item in users} == {f"tests/{module}::{fixture}"}


@pytest.mark.process  # real xdist workers are interpreters
def test_a_dist_the_ini_names_is_kept_and_mcp_tests_are_warned_about(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F8: ``--dist load`` in the ini's addopts is the user's choice (not
    overridden by ``-n`` alone meaning loadgroup), and with mcp_server tests
    collected a warning says they may race for the skills-server port."""
    suite = _xdist_suite(pytester, monkeypatch)
    suite.makeini(
        "[pytest]\ntestpaths = t\naddopts = --dist load\n"
        "markers =\n    slow: s\n    process: p\n    mcp_server: m\n"
    )
    result = suite.runpytest_subprocess("-p", "tests.tier_plugin", "-n", "2", "--full", "-v", timeout=240)
    outcomes = result.parseoutcomes()
    assert outcomes.get("passed") == 9 and outcomes.get("warnings", 0) >= 1, outcomes  # one per worker
    result.stdout.fnmatch_lines(["*LoadScheduling*", "*mcp_server tests under a --dist other than loadgroup*"])
    result.stdout.no_fnmatch_line("*@mcp_port*")


def _xdist_suite(pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch) -> pytest.Pytester:
    # K3: the inner run's rootdir is pytester's tmp dir, so `tests` is
    # importable only through PYTHONPATH (its workers inherit it).
    monkeypatch.setenv("PYTHONPATH", str(TESTS.parent))
    monkeypatch.delenv("CLOCKWORK_FULL_SUITE", raising=False)
    pytester.makeini(
        "[pytest]\ntestpaths = t\nmarkers =\n    slow: s\n    process: p\n    mcp_server: m\n"
    )
    pytester.mkpydir("t")
    (pytester.path / "t" / "test_x.py").write_text(_TESTS, encoding="utf-8")
    (pytester.path / "t" / "test_g.py").write_text(_GROUPS, encoding="utf-8")
    return pytester


@pytest.mark.process  # real xdist workers are interpreters
@pytest.mark.parametrize("args,passed", [((), 7), (("--full",), 9)], ids=["bare", "full"])
def test_real_workers_run_the_fast_tier_on_a_bare_run_and_every_tier_with_full(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch, args: tuple[str, ...], passed: int
) -> None:
    """K1 and T1 review F5, in two real workers: a bare `pytest -n 2`
    deselects slow and process tests in every worker (the controller's
    decision, handed on), and the controller -- which collects nothing --
    still prints the FAST TIER banner with the workers' count."""
    suite = _xdist_suite(pytester, monkeypatch)
    result = suite.runpytest_subprocess("-p", "tests.tier_plugin", "-n", "2", *args, timeout=240)
    result.assert_outcomes(passed=passed)
    if args:
        result.stdout.no_fnmatch_line("*FAST TIER: *deselected*")
    else:
        result.stdout.fnmatch_lines(["*FAST TIER: 2 slow/process tests deselected*--full*"])


@pytest.mark.process  # real xdist workers are interpreters
def test_real_workers_carry_the_groups_on_their_node_ids(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    """K7: the groups are marked in the WORKERS (whose ``dist`` is "no"), and
    `-n 2` alone means `--dist loadgroup` here, so xdist suffixes each grouped
    node id with ``@group`` and runs a group on one worker."""
    suite = _xdist_suite(pytester, monkeypatch)
    result = suite.runpytest_subprocess(
        "-p", "tests.tier_plugin", "-n", "2", "--full", "-v", "t/test_g.py", timeout=240
    )
    result.assert_outcomes(passed=6)
    out = result.stdout.str()
    import re

    ran = {nodeid: gw for gw, nodeid in re.findall(r"\[(gw\d+)\][^\n]*?PASSED (\S+)", out)}
    assert ran.get("t/test_g.py::test_uses_measured@t/test_g.py::measured"), out
    assert ran.get("t/test_g.py::test_also_measured@t/test_g.py::measured"), out
    assert ran["t/test_g.py::test_uses_measured@t/test_g.py::measured"] == \
        ran["t/test_g.py::test_also_measured@t/test_g.py::measured"]
    assert ran["t/test_g.py::test_uses_other@t/test_g.py::other"] == \
        ran["t/test_g.py::test_third_and_other@t/test_g.py::other"]
    assert "t/test_g.py::test_mcp@mcp_port" in ran, out
    assert "t/test_g.py::test_free" in ran, out


def test_the_recorder_never_decides_whether_a_child_starts(monkeypatch: pytest.MonkeyPatch) -> None:
    """A classification that raises is swallowed: Popen's own outcome stands
    (review F7)."""
    import subprocess

    from tests import tier_plugin

    def boom(*_a: object, **_k: object) -> bool:
        raise TypeError("an argv shape the guard cannot read")

    monkeypatch.setattr(tier_plugin, "starts_an_interpreter", boom)
    with pytest.raises(OSError):
        subprocess.Popen(["clockwork-no-such-program-t1"])


# -- the static marker list (so a dropped marker fails) --------------------------------

#: Modules whose every test is `process` (module pytestmark). Kept by hand on
#: purpose: silently dropping a marker must fail here.
WHOLE_MODULE_PROCESS = {
    "test_admin_no_play_text.py", "test_docker_smoke.py", "test_frontdoor_routing.py",
    "test_hosting_wsgi.py", "test_imports.py",
}

#: Modules whose every test is `slow` (module pytestmark), held the same way.
WHOLE_MODULE_SLOW = {"test_vertical_slice.py"}


def _module_marks(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    marks: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "pytestmark" for t in node.targets
        ):
            marks |= {n.attr for n in ast.walk(node.value) if isinstance(n, ast.Attribute)}
    return marks


@pytest.mark.parametrize("name", sorted(WHOLE_MODULE_PROCESS))
def test_a_whole_process_module_keeps_its_marker(name: str) -> None:
    assert "process" in _module_marks(TESTS / name), f"{name} lost `pytestmark = pytest.mark.process`"


@pytest.mark.parametrize("name", sorted(WHOLE_MODULE_SLOW))
def test_a_whole_slow_module_keeps_its_marker(name: str) -> None:
    assert "slow" in _module_marks(TESTS / name), f"{name} lost `pytestmark = pytest.mark.slow`"
