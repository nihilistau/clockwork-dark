"""Under pytest-xdist (v0.21.1) each worker is the suite, not a child of it:
its marker names its own pid, its in-process config is not sandboxed, and
its children still are. Every test here passes serially as well: it
describes the serial suite too."""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

from engine.config import TEST_SANDBOX_ENV, child_sandbox

pytest_plugins = ["pytester"]


def test_the_marker_names_this_process() -> None:
    raw = os.environ[TEST_SANDBOX_ENV]
    assert raw.partition(os.pathsep)[0] == str(os.getpid())


def test_this_process_is_not_a_sandboxed_child() -> None:
    assert child_sandbox() is None


def test_this_process_has_a_storage_root_of_its_own(tmp_path_factory: pytest.TempPathFactory) -> None:
    """The session's ``CLOCKWORK_DATA_DIR`` lies under THIS process's basetemp
    (``popen-gwN`` in a worker), so two workers never share a storage root."""
    from pathlib import Path

    base = Path(tmp_path_factory.getbasetemp()).resolve()
    worker = os.environ.get("PYTEST_XDIST_WORKER")
    if worker:
        assert base.name == f"popen-{worker}", base
    _, _, layer = os.environ[TEST_SANDBOX_ENV].partition(os.pathsep)
    assert Path(layer).resolve().parent == base


@pytest.mark.process
def test_a_child_is_still_sandboxed() -> None:
    done = subprocess.run(
        [sys.executable, "-c",
         "from engine.config import child_sandbox; print(child_sandbox() is not None)"],
        capture_output=True, text=True, timeout=120, check=True)
    assert done.stdout.strip() == "True"


def test_a_worker_takes_no_storage_snapshot_and_a_serial_run_does() -> None:
    """The owner's storage is compared ONCE a run: by the session itself when
    serial, by the controller under xdist, never by each worker."""
    from tests.conftest import _SNAPSHOT_KEY

    taken = getattr(sys, _SNAPSHOT_KEY, None) is not None
    assert taken is (not os.environ.get("PYTEST_XDIST_WORKER"))


_CANARY_PLUGIN = """
import sys
import pytest
from tests import conftest as real

# The controller's two hooks, exactly as tests/conftest.py has them, in an
# inner in-process session that is made to look like an xdist controller.
pytest_sessionfinish = real.pytest_sessionfinish
pytest_terminal_summary = real.pytest_terminal_summary  # carries its trylast mark
"""

_CANARY_TEST = """
import pathlib
def test_writes_into_the_watched_root():
    pathlib.Path({root!r}, "saves", "run.json").write_text("{{}}", encoding="utf-8")
def test_writes_nothing():
    pass
"""


@pytest.mark.parametrize("write", [True, False], ids=["changed", "unchanged"])
def test_the_controller_s_failed_storage_check_is_red_last_and_exit_1(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch, tmp_path, write: bool
) -> None:
    """F1 (T5 fix round 1): a storage change the controller finds turns the
    run's exit to 1 and is printed as a red STORAGE CHECK FAILED section
    AFTER the durations block, just above the stats line -- where the eye
    and run_tests.py's tail look. The hooks are conftest's own, in an inner
    in-process session made to look like a controller over a stand-in root."""
    from tests import conftest

    root = tmp_path / "owner"
    (root / "saves").mkdir(parents=True)
    roots = [(root / "saves", None)]
    monkeypatch.setattr(sys, conftest._SNAPSHOT_KEY, (roots, conftest.storage_snapshot(roots)), raising=False)
    monkeypatch.setattr(conftest, "is_xdist_controller", lambda config: True)
    pytester.makepyfile(canary_plugin=_CANARY_PLUGIN)
    body = _CANARY_TEST.format(root=str(root))
    if not write:
        body = body.replace('.write_text("{}", encoding="utf-8")', '.parent.exists()')
    pytester.makepyfile(test_canary=body)
    pytester.syspathinsert()
    result = pytester.runpytest_inprocess("-p", "canary_plugin", "--color=yes", "--durations=3",
                                          "-p", "no:cacheprovider")
    out = result.stdout.str()
    if not write:
        assert result.ret == 0 and "STORAGE CHECK FAILED" not in out
        return
    assert result.ret == 1, out
    section = out.index("STORAGE CHECK FAILED")
    assert out.index("slowest") < section < out.rindex("2 passed"), out
    assert "\x1b[31m" in out[section - 40: section] or "\x1b[31m" in out[section - 200: section + 40], out
    assert "run.json" in out[section:]
    assert "suspects" in out[section:]


def test_a_worse_exit_is_not_turned_into_1(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """F2: an interrupted or internal-error run keeps its own exit code."""
    from types import SimpleNamespace

    from tests import conftest

    roots = [(tmp_path / "saves", None)]
    (tmp_path / "saves").mkdir()
    monkeypatch.setattr(sys, conftest._SNAPSHOT_KEY, (roots, conftest.storage_snapshot(roots)), raising=False)
    monkeypatch.setattr(conftest, "is_xdist_controller", lambda config: True)
    (tmp_path / "saves" / "run.json").write_text("{}", encoding="utf-8")
    for start, end in ((pytest.ExitCode.OK, pytest.ExitCode.TESTS_FAILED),
                       (pytest.ExitCode.INTERRUPTED, pytest.ExitCode.INTERRUPTED),
                       (pytest.ExitCode.INTERNAL_ERROR, pytest.ExitCode.INTERNAL_ERROR)):
        session = SimpleNamespace(config=SimpleNamespace(stash=pytest.Stash()), exitstatus=start)
        conftest.pytest_sessionfinish(session, int(start))  # type: ignore[arg-type]
        assert session.exitstatus == end


def test_the_suspects_are_the_tests_running_when_a_file_changed() -> None:
    """F4: a changed file's mtime names the tests whose window holds it."""
    from tests.conftest import storage_suspects

    before = {"a": (1, 100 * 10**9, "")}
    after = {"a": (2, 205 * 10**9, ""), "b": (1, 50 * 10**9, ""), "d": (-1, 0, "")}
    windows = {"t1": [200.0, 210.0, "gw0"], "t2": [10.0, 20.0, "gw1"], "t3": [52.0, 60.0, "gw2"]}
    assert storage_suspects(before, after, windows) == ["t3 on gw2", "t1 on gw0"]
