"""
The tier hooks (v0.21.1); see tests/tiers.py. Registered by tests/conftest.py
(its ``pytest_addoption``), and loadable on its own with ``-p
tests.tier_plugin``, which is how tests/test_suite_tiers.py runs it in an
inner pytester session without the whole conftest (whose sandbox must not
nest).

THE PROCESS GUARD. ``pytest_configure`` wraps ``subprocess.Popen.__init__``
in a recorder for the whole session: a child that would start Python,
gunicorn or pytest (``tiers.starts_an_interpreter``) is recorded against the
test whose setup, call or teardown is running, and against every fixture
whose setup is running then (``pytest_fixture_setup``). At a test's
teardown report, a test not marked ``process`` fails if it started one or
uses a fixture that did -- so every later user of a module fixture is held
to the marker, not only the first. It sees only direct ``subprocess.Popen``
children: a grandchild, or a route that bypasses Popen, is not recorded
(CLAUDE.md, Deliberately deferred). The
conftest's sandbox wrapper, installed later (its ``pytest_configure`` is
``trylast``), calls this recorder rather than the real ``__init__``, so the
chain is sandbox -> recorder -> real: every child is still sandboxed, and
every child is recorded.

THE STALL WATCHDOG (T2). ``add_time_limits`` gives every collected item a
pytest-timeout marker unless it carries its own: 300 s, 900 s for a
``slow``/``process`` item, times ``CLOCKWORK_TIMEOUT_SCALE`` (at least 1).
The ini's method is ``thread`` (its ``os._exit`` skips fixture finalizers);
a ``process`` item uses ``signal`` where SIGALRM exists, so its fixtures
still stop its children (K6; on Windows the session's Job Object does,
tests/process_jobs.py). An inner in-process pytester session on POSIX that
arms SIGALRM replaces the outer test's alarm while it runs. The signal
method has no fallback: a `process` test stuck in C code that never returns
to the interpreter never runs the handler, and the teardown after a fired
alarm has no limit of its own; only run_tests.py's wall-clock limit ends
either, so a bare POSIX `pytest` can hang there.

XDIST (T5). The tier decision (``FAST_KEY``) and the loadgroup decision
(``LOADGROUP_KEY``) are made in the controller and handed to each worker
(``pytest_configure_node``); each worker's deselected count comes back
(``WORKEROUTPUT_KEY``, ``pytest_testnodedown``) so the controller, which
collects nothing, still prints the FAST TIER banner. ``-n N`` alone means
``--dist loadgroup`` (``pytest_cmdline_main``), and a worker marks every
test that shares a wide fixture, or the skills-server port, with one
``xdist_group`` (``xdist_groups``) before xdist's own worker hook reads the
marks (this module's ``pytest_collection_modifyitems`` is ``tryfirst``).
"""

from __future__ import annotations

import os
import signal
import socket
import subprocess
from typing import Any

import pytest

from tests.tiers import TIER_MARKERS, is_bare_run, starts_an_interpreter, tier_of, wants_full

_DESELECTED_KEY = pytest.StashKey[int]()
_PATCH_KEY = pytest.StashKey[pytest.MonkeyPatch]()
#: The ONE tier decision: True when this session runs the fast tier only.
#: Made at ``pytest_configure`` in the process the user started and handed
#: to an xdist worker through ``workerinput`` (a worker is built from
#: resolved args, so its own ``args_source`` would say "not bare").
FAST_KEY = pytest.StashKey[bool]()
#: Every collected node id by tier ("fast", "slow", "process"), recorded
#: BEFORE the fast tier filters anything, in full runs too (K8).
PARTITION_KEY = pytest.StashKey[dict[str, list[str]]]()
WORKERINPUT_KEY = "clockwork_fast_tier"

_CURRENT: list[pytest.Item] = []  # the item whose setup/call/teardown is running
_STARTED: dict[str, list[str]] = {}  # nodeid -> interpreter argvs it started
#: The fixtures whose setup is running (``pytest_fixture_setup``), innermost
#: last, and every fixture definition that started an interpreter while on
#: that stack, with the first argv it started. Keyed on the FixtureDef
#: object, so two modules' unrelated ``instance`` fixtures never collide. A
#: module fixture starts its children once, in its first user's setup; this
#: is how its LATER users are held to the marker too (T1 review F1).
_FIXTURE_STACK: list[Any] = []
_PROCESS_FIXTURES: dict[Any, str] = {}
#: THE LOOPBACK GUARD (T5 fix round 2): the same two records for a socket
#: BOUND on a loopback or wildcard address -- an in-process server (a bus, a
#: front door, a WSGI server, a stub). Such tests run in the hybrid's serial
#: phase (``loopback``, tests/tiers.py::SERIAL_MARKS): this workstation's
#: loopback stalls failed them under xdist.
_BOUND: dict[str, list[str]] = {}
_LOOPBACK_FIXTURES: dict[Any, str] = {}
#: Hosts a bind counts for: a server any loopback client can reach.
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "0.0.0.0", "::", ""})
#: Marks that put a test in the serial phase, so a bind is allowed.
SERIAL_MARKERS = ("process", "mcp_server", "loopback")


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--full", action="store_true", dest="clockwork_full", default=False,
        help="run every tier (slow and process too). A bare `pytest` leaves them out.",
    )


def runs_fast_tier(config: pytest.Config) -> bool:
    """This session's tier decision (FAST_KEY), made once (see there)."""
    workerinput = getattr(config, "workerinput", None)
    if workerinput is not None and WORKERINPUT_KEY in workerinput:
        return bool(workerinput[WORKERINPUT_KEY])
    return not wants_full(config) and is_bare_run(config)


#: The controller's "the run is loadgroup" handed to a worker (K7): a worker
#: is built from the command line, which may not name ``--dist`` at all
#: (``pytest_cmdline_main`` below makes ``-n`` alone mean loadgroup), so the
#: worker's own ``loadgroup`` option -- read by xdist's worker hook that
#: suffixes a grouped node id with ``@group`` -- would be False.
LOADGROUP_KEY = "clockwork_loadgroup"


@pytest.hookimpl(optionalhook=True)  # pytest-xdist's hook; absent without xdist
def pytest_configure_node(node: Any) -> None:
    node.workerinput[WORKERINPUT_KEY] = node.config.stash[FAST_KEY]
    node.workerinput[LOADGROUP_KEY] = node.config.getoption("dist", "no") == "loadgroup"


#: The worker's deselected count, handed back to the controller (T1 review
#: F5): the controller collects nothing, so the FAST TIER banner it prints
#: reads the workers' count. Every worker collects the whole suite and
#: deselects the same tests, so any one's count is the run's.
WORKEROUTPUT_KEY = "clockwork_deselected"


@pytest.hookimpl(optionalhook=True)  # pytest-xdist's hook; absent without xdist
def pytest_testnodedown(node: Any, error: Any) -> None:
    got = getattr(node, "workeroutput", {}).get(WORKEROUTPUT_KEY)
    if got is not None:
        config = node.config
        config.stash[_DESELECTED_KEY] = max(config.stash.get(_DESELECTED_KEY, 0), int(got))


def _names_a_dist(args: Any) -> bool:
    return any(
        str(arg) in ("--dist", "--distload", "-d") or str(arg).startswith("--dist=")
        for arg in args or ()
    )


@pytest.hookimpl(tryfirst=True)
def pytest_cmdline_main(config: pytest.Config) -> None:
    """``-n N`` with no ``--dist`` means ``--dist loadgroup`` in this suite:
    the groups (``xdist_groups``) are what keep a wide fixture built once
    and every ``mcp_server`` test on the one skills-server port. A ``--dist``
    the command line (or PYTEST_ADDOPTS) names is kept. Read off the
    arguments, not the option: xdist's own hook (also ``tryfirst``, so either
    may run first) turns an unset "no" into "load"."""
    option = config.option
    if not getattr(option, "numprocesses", None) or getattr(option, "dist", "no") not in ("no", "load"):
        return
    named = (
        _names_a_dist(config.invocation_params.args)
        or _names_a_dist(os.environ.get("PYTEST_ADDOPTS", "").split())
        or _names_a_dist(config.getini("addopts"))  # T5 review F8
    )
    if not named:
        option.dist = "loadgroup"


def pytest_configure(config: pytest.Config) -> None:
    config.stash[FAST_KEY] = runs_fast_tier(config)
    workerinput = getattr(config, "workerinput", None)
    if workerinput is not None and workerinput.get(LOADGROUP_KEY):
        config.option.loadgroup = True
    previous = subprocess.Popen.__init__

    def recording_init(self: Any, args: Any, *rest: Any, **kwargs: Any) -> None:
        # executable is Popen's third positional (args, bufsize, executable).
        try:
            executable = kwargs.get("executable", rest[1] if len(rest) > 1 else None)
            if starts_an_interpreter(args, executable):
                argv = str(args)[:120]
                if _CURRENT:
                    _STARTED.setdefault(_CURRENT[-1].nodeid, []).append(argv)
                for fixturedef in _FIXTURE_STACK:
                    _PROCESS_FIXTURES.setdefault(fixturedef, argv)
        except Exception:  # noqa: BLE001 -- the guard must never decide whether a child starts
            pass
        previous(self, args, *rest, **kwargs)

    patch = pytest.MonkeyPatch()
    patch.setattr(subprocess.Popen, "__init__", recording_init)
    real_bind = socket.socket.bind

    def recording_bind(self: Any, address: Any) -> Any:
        try:
            host = address[0] if isinstance(address, tuple) else None
            if isinstance(host, str) and host in _LOOPBACK_HOSTS:
                where = f"{host}:{address[1]}"
                if _CURRENT:
                    _BOUND.setdefault(_CURRENT[-1].nodeid, []).append(where)
                for fixturedef in _FIXTURE_STACK:
                    _LOOPBACK_FIXTURES.setdefault(fixturedef, where)
        except Exception:  # noqa: BLE001 -- the guard must never decide whether a bind happens
            pass
        return real_bind(self, address)

    patch.setattr(socket.socket, "bind", recording_bind)
    config.stash[_PATCH_KEY] = patch


@pytest.hookimpl(trylast=True)  # after the conftest's own undo, so the real __init__ is what stays
def pytest_unconfigure(config: pytest.Config) -> None:
    patch = config.stash.get(_PATCH_KEY, None)
    if patch is not None:
        patch.undo()


BASE_LIMIT, TIER_LIMIT = 300, 900


def _scale() -> float:
    try:
        return max(1.0, float(os.environ.get("CLOCKWORK_TIMEOUT_SCALE", "1")))
    except ValueError:
        return 1.0


def _process_method() -> str | None:
    """The timeout method for a ``process`` test: ``signal`` where the
    platform has SIGALRM (POSIX), else the ini's (``thread``).

    The thread method ends a timed-out test's process with ``os._exit``, so
    no fixture finalizer runs and a child the test started is orphaned (K6,
    measured: tests/test_run_tests_script.py). On POSIX the signal method
    raises inside the test instead, so its fixtures stop their children. On
    Windows there is no SIGALRM: the session runs in a kill-on-close Job
    Object (tests/conftest.py, tests/process_jobs.py), so every orphan ends
    when the session does."""
    return "signal" if hasattr(signal, "SIGALRM") else None


def add_time_limits(items: list[pytest.Item]) -> None:
    """Every item gets a timeout marker unless it carries its own (pytest-timeout):
    300 s, 900 s in a tier, times CLOCKWORK_TIMEOUT_SCALE. An explicit
    ``@pytest.mark.timeout(n)`` is not scaled: the test chose it."""
    scale = _scale()
    method = _process_method()
    for item in items:
        if item.get_closest_marker("timeout") is not None:
            continue
        tiered = any(item.get_closest_marker(m) for m in TIER_MARKERS)
        seconds = int((TIER_LIMIT if tiered else BASE_LIMIT) * scale)
        if method and item.get_closest_marker("process") is not None:
            item.add_marker(pytest.mark.timeout(seconds, method=method))
        else:
            item.add_marker(pytest.mark.timeout(seconds))


#: The fixture scopes whose users must share a worker (a session fixture is
#: built once per worker whatever happens, so it is not counted).
_WIDE = ("module", "class", "package")
#: Every ``mcp_server`` test's group: one skills-server port.
MCP_GROUP = "mcp_port"


#: Wide fixtures that do NOT pull their users into one group (T5 review F3):
#: cheap guards that are right per worker, each checking its own share.
#: ``test_supervisor.py``'s autouse module guard snapshots the real root's
#: ``hosting/`` and ``users/`` around the module; grouped, it put all 59 of
#: the module's tests on one worker.
UNGROUPED = frozenset({"_no_supervisor_test_writes_the_real_storage_root"})


def _wide_fixtures(item: pytest.Item) -> list[str]:
    info = getattr(item, "_fixtureinfo", None)
    if info is None:
        return []
    return sorted(
        name for name, defs in info.name2fixturedefs.items()
        if defs and defs[-1].scope in _WIDE and name not in UNGROUPED
    )


def xdist_group_for(item: pytest.Item) -> str | None:
    """The group an item must share a worker with, or None to spread freely.

    One skills-server port: every mcp_server test runs in one worker. Else
    the module/class/package fixtures it uses: their users stay together so
    each such fixture is built once, not once per worker. A test with none
    is free (most of the suite). Session fixtures are per worker anyway and
    are not counted. ``xdist_groups`` then merges every two groups that share
    a fixture, so this is the item's own key, not always its final group.
    """
    if item.get_closest_marker("mcp_server") is not None:
        return MCP_GROUP
    names = _wide_fixtures(item)
    if not names:
        return None
    return f"{_file_of(item)}::{'+'.join(names)}"


def _file_of(item: pytest.Item) -> str:
    return item.nodeid.split("::", 1)[0]


def xdist_groups(items: list[pytest.Item]) -> dict[str, str]:
    """Every grouped item's FINAL group, by node id: the connected components
    of "uses the same wide fixture" (the fixture of one file: two modules'
    same-named fixtures are two fixtures) and "is an mcp_server test". A test
    whose fixtures span two keys joins them, so EVERY user of a fixture --
    the child batches of tests/test_imports.py and test_simulate_thief.py
    included (tests/child_batch.py) -- runs in one worker, and the fixture
    is built once. A component holding an mcp_server test is ``mcp_port``;
    any other is named by its smallest key."""
    parent: dict[str, str] = {}

    def find(key: str) -> str:
        parent.setdefault(key, key)
        while parent[key] != key:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    keys_of: dict[str, list[str]] = {}
    for item in items:
        keys = [f"{_file_of(item)}::{name}" for name in _wide_fixtures(item)]
        if item.get_closest_marker("mcp_server") is not None:
            keys.append(MCP_GROUP)
        if not keys:
            continue
        keys_of[item.nodeid] = keys
        for key in keys:
            find(key)
        for key in keys[1:]:
            union(keys[0], key)
    has_mcp = {find(MCP_GROUP)} if MCP_GROUP in parent else set()
    out: dict[str, str] = {}
    for nodeid, keys in keys_of.items():
        root = find(keys[0])
        out[nodeid] = MCP_GROUP if root in has_mcp else root
    return out


def _groups_wanted(config: pytest.Config) -> bool:
    """Whether to mark groups (K7): in an xdist worker of a ``loadgroup`` run
    (the only process that collects in one). xdist sets the worker's ``dist``
    to "no", so ``dist`` is the wrong thing to read there; its ``loadgroup``
    option is set from the command line, and from the controller's decision
    (``LOADGROUP_KEY``) in ``pytest_configure``."""
    return bool(getattr(config.option, "loadgroup", False))


@pytest.hookimpl(tryfirst=True)  # the groups must be marked before xdist's worker hook reads them
def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    add_time_limits(items)
    config.stash[_DESELECTED_KEY] = 0
    partition: dict[str, list[str]] = {"fast": [], **{m: [] for m in TIER_MARKERS}}
    tiers = []
    for item in items:
        tier = tier_of({m for m in TIER_MARKERS if item.get_closest_marker(m)})
        partition[tier].append(item.nodeid)
        tiers.append(tier)
    config.stash[PARTITION_KEY] = partition
    if config.stash.get(FAST_KEY, False):
        keep, drop = [], []
        for item, tier in zip(items, tiers):
            (keep if tier == "fast" else drop).append(item)
        if drop:
            config.hook.pytest_deselected(items=drop)
            items[:] = keep
        config.stash[_DESELECTED_KEY] = len(drop)
    workeroutput = getattr(config, "workeroutput", None)
    if workeroutput is not None:
        workeroutput[WORKEROUTPUT_KEY] = config.stash[_DESELECTED_KEY]
    if (hasattr(config, "workerinput") and not _groups_wanted(config)
            and any(item.get_closest_marker("mcp_server") for item in items)):
        # T5 review F8: an explicit --dist other than loadgroup drops the
        # mcp_port group, so two skills servers may be up at once.
        import warnings

        warnings.warn(pytest.PytestWarning(
            "mcp_server tests under a --dist other than loadgroup are not kept to one "
            "worker (tests/tier_plugin.py): they may race for the skills-server port"))
    if _groups_wanted(config):
        groups = xdist_groups(items)
        for item in items:
            group = groups.get(item.nodeid)
            if group is not None:
                item.add_marker(pytest.mark.xdist_group(name=group))


@pytest.hookimpl(wrapper=True)
def pytest_runtest_protocol(item: pytest.Item, nextitem: Any) -> Any:
    _CURRENT.append(item)
    try:
        return (yield)
    finally:
        _CURRENT.pop()


@pytest.hookimpl(wrapper=True)
def pytest_fixture_setup(fixturedef: Any, request: Any) -> Any:
    _FIXTURE_STACK.append(fixturedef)
    try:
        return (yield)
    finally:
        _FIXTURE_STACK.pop()


def _process_fixture_of(item: pytest.Item, record: dict[Any, str] | None = None) -> str | None:
    """The first fixture in the item's closure that started an interpreter
    (or, with ``record``, that is in that record)."""
    record = _PROCESS_FIXTURES if record is None else record
    info = getattr(item, "_fixtureinfo", None)
    if info is None:
        return None
    for name, defs in info.name2fixturedefs.items():
        for fixturedef in defs:
            if fixturedef in record:
                return f"fixture `{name}` ({record[fixturedef]})"
    return None


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: Any) -> Any:
    report = yield
    if call.when != "teardown":
        return report
    started = _STARTED.pop(item.nodeid, None)
    bound = _BOUND.pop(item.nodeid, None)
    if not report.passed:
        return report
    if not any(item.get_closest_marker(m) for m in SERIAL_MARKERS):
        how = f"bound a loopback server ({bound[0]})" if bound else None
        if how is None:
            via = _process_fixture_of(item, _LOOPBACK_FIXTURES)
            how = f"uses a {via} that bound a loopback server" if via else None
        if how:
            report.outcome = "failed"
            report.longrepr = (
                f"{item.nodeid} {how} but is not marked `loopback` (or `process`). "
                "Mark it (or its module) so it runs in the hybrid's serial phase "
                "(tests/tiers.py::SERIAL_MARKS, tests/tier_plugin.py)."
            )
            return report
    if item.get_closest_marker("process") is not None:
        return report
    how = f"started an interpreter ({started[0]})" if started else None
    if how is None:
        via = _process_fixture_of(item)
        how = f"uses a {via} that starts an interpreter" if via else None
    if how:
        report.outcome = "failed"
        report.longrepr = (
            f"{item.nodeid} {how} but is not marked "
            "`process`. Mark it (or its module: pytestmark = pytest.mark.process) so "
            "the fast tier stays fast (tests/tier_plugin.py)."
        )
    return report


def _banner(config: pytest.Config) -> str | None:
    n = config.stash.get(_DESELECTED_KEY, 0)
    if not n:
        return None
    return f"FAST TIER: {n} slow/process tests deselected -- run --full before a release"


def pytest_report_header(config: pytest.Config) -> str | None:
    if config.stash.get(FAST_KEY, False):
        return "FAST TIER: slow/process tests left out; --full for everything"
    if wants_full(config):
        return "FULL SUITE: every tier"
    return "EXPLICIT SELECTION: every tier it names"


def pytest_terminal_summary(terminalreporter: Any, exitstatus: int, config: pytest.Config) -> None:
    line = _banner(config)
    if line:
        terminalreporter.write_line(line, yellow=True, bold=True)
