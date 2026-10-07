"""
The test guards, across processes (v0.20.0 T5; spec §3.5, survey finding 5).

Every guard in ``tests/conftest.py`` is a monkeypatch, and a monkeypatch does
not cross a process boundary: a child started through ``subprocess`` had none
of them. Two lines now hold (``tests/conftest.py::pytest_configure``):

1. THE MARKER, fail closed. ``CLOCKWORK_TEST_SANDBOX=<suite pid>;<layer>`` is
   in the suite's own environment, so every child inherits it however it is
   started. The engine reads it only in a process whose pid differs
   (``engine.config.child_sandbox``): there it never reads or writes
   ``config/local.yaml``, merges the sandbox layer, forces the discard
   ``llm.base_url``, and refuses an ``mcp.json`` write outside the sandbox.
2. THE WRAPPER. ``subprocess.Popen.__init__`` also gives each child a
   ``CLOCKWORK_CONFIG`` ending in the sandbox layer (the caller's files first)
   and restores the marker in an ``env=`` a caller scrubbed.

``CLOCKWORK_CONFIG`` is never exported in this process, where it would rewrite
both goldens.

The child is ``tests/probes/sandbox_child.py``. EVERY test that starts one by
a route a guard might miss (os.system, multiprocessing, asyncio, a re-patched
Popen) first points the home directory and the child's ``_CONFIG_DIR`` at its
own temp directory, and the storage root is already per-test: so even with the
guard absent (the pre-fix commit, a canary) the child could not reach the
owner's ``mcp.json``, ``config/local.yaml`` or saves, and the probe dials no
model server (AGENTS.md "Tests").

Names from ``tests.conftest`` are imported inside the tests, so this file
still runs -- and fails test by test -- against the commit before the fix.
"""

from __future__ import annotations

import ast
import asyncio
import json
import logging
import multiprocessing
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Optional

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
PROBE = REPO / "tests" / "probes" / "sandbox_child.py"
TIMEOUT = 180
DISCARD = "http://127.0.0.1:9/v1"


def _run_probe(*args: str, env: Optional[dict[str, str]] = None) -> dict[str, Any]:
    """Run the probe as a child through ``subprocess`` and return its JSON."""
    done = subprocess.run(
        [sys.executable, str(PROBE), *args],
        cwd=str(REPO),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=TIMEOUT,
    )
    assert done.returncode == 0, f"the probe failed:\n{done.stdout}\n{done.stderr[-4000:]}"
    return json.loads(done.stdout.strip().splitlines()[-1])


def _temp_root(factory: pytest.TempPathFactory) -> Path:
    return Path(factory.getbasetemp()).resolve()


@pytest.fixture
def redirected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """
    Every guarded path pointed at tmp for this process and its children,
    BEFORE any child starts: the home directory (so LM Studio's ``mcp.json``
    locations are temp ones), and a ``_CONFIG_DIR`` stand-in whose
    ``local.yaml`` sets only a marker (passed to the child as an argument).
    ``CLOCKWORK_DATA_DIR`` is already a per-test temp directory (conftest).
    Returns the probe's arguments.
    """
    home = tmp_path / "home"
    home.mkdir()
    for name in ("HOME", "USERPROFILE"):
        monkeypatch.setenv(name, str(home))
    stand_in = tmp_path / "config"
    stand_in.mkdir()
    (stand_in / "local.yaml").write_text(
        yaml.safe_dump({"sandbox_probe": {"marker": "read"}}), encoding="utf-8"
    )
    return ["--config-dir", str(stand_in)]


def _assert_sandboxed(child: dict[str, Any], root: Path) -> None:
    assert child["pid"] != os.getpid()
    assert child["sandboxed"] is True, child
    assert child["base_url"] == DISCARD, child
    assert child["marker"] is None, child  # the stand-in local.yaml was not read
    assert child["written"] is not None, child
    assert Path(child["written"]).resolve() == root / "lm-studio" / "mcp.json", child


# -- the plain route: subprocess.run --------------------------------------------


@pytest.fixture(scope="module")
def plain_child() -> dict[str, Any]:
    """One child, started with no ``env=`` (so from a copy of ``os.environ``)."""
    return _run_probe()


@pytest.mark.process
def test_a_childs_mcp_json_write_lands_in_the_temp_root(
    plain_child: dict[str, Any], tmp_path_factory: pytest.TempPathFactory
) -> None:
    root = _temp_root(tmp_path_factory)
    written = plain_child["written"]
    assert written, plain_child
    assert Path(written).resolve() == root / "lm-studio" / "mcp.json"


@pytest.mark.process
def test_a_child_sees_the_discard_base_url(plain_child: dict[str, Any]) -> None:
    assert plain_child["base_url"] == DISCARD
    assert plain_child["sandboxed"] is True


@pytest.mark.process
def test_a_childs_own_config_file_is_kept_and_the_sandbox_wins(tmp_path: Path) -> None:
    """The caller's CLOCKWORK_CONFIG comes first, the sandbox layer last."""
    own = tmp_path / "hosted.yaml"
    own.write_text(
        yaml.safe_dump({"hosting": {"enabled": True}, "llm": {"base_url": "http://127.0.0.1:5999/v1"}}),
        encoding="utf-8",
    )
    child = _run_probe(env=dict(os.environ, CLOCKWORK_CONFIG=str(own)))
    assert child["hosting"] is True, child
    assert child["base_url"] == DISCARD, child


@pytest.mark.process
def test_a_child_does_not_read_config_local_yaml(
    redirected: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    The ``_CONFIG_DIR`` stand-in's ``local.yaml`` is never read by the child.
    The in-process half is the control: the same stand-in, read here (the
    suite's own pid, so not sandboxed), IS read.
    """
    import engine.config as config

    child = _run_probe(*redirected)
    assert child["marker"] is None, child

    monkeypatch.setattr(config, "_CONFIG_DIR", Path(redirected[1]))
    monkeypatch.setattr(config, "_instance", None)
    try:
        assert config.get_config().get("sandbox_probe.marker") == "read"
    finally:
        monkeypatch.undo()
        config.reset_config()


def _shipped_base_url() -> str:
    """``llm.base_url`` from the YAML layers this process reads (default, then local)."""
    import engine.config as config

    value = ""
    for path in (config._DEFAULT_PATH, config._CONFIG_DIR / "local.yaml"):
        migrated = config._load_yaml(path)
        block = migrated.get("llm") if isinstance(migrated, dict) else None
        if isinstance(block, dict) and block.get("base_url"):
            value = str(block["base_url"])
    return value


def test_nothing_but_the_inert_marker_is_exported_in_this_process() -> None:
    from engine.config import child_sandbox, external_config_paths, get_config

    assert "CLOCKWORK_CONFIG" not in os.environ
    pid, _, layer = os.environ["CLOCKWORK_TEST_SANDBOX"].partition(os.pathsep)
    assert pid == str(os.getpid()) and Path(layer).is_file()
    assert child_sandbox() is None  # the marker names this process: inert here
    assert external_config_paths() == []
    assert get_config().get("llm.base_url") == _shipped_base_url()
    assert get_config().get("llm.base_url") != DISCARD


# -- every other route a child can be started by (T5 fix round 1) ---------------


def _via_os_system(argv: list[str], out: Path) -> None:
    command = [sys.executable, str(PROBE), *argv, "--out", str(out)]
    if os.name == "nt":
        # cmd /c strips one pair of outer quotes: wrap the whole line in one.
        line = '"' + subprocess.list2cmdline(command) + '"'
    else:
        import shlex

        line = " ".join(shlex.quote(part) for part in command)
    assert os.system(line) == 0


def _via_multiprocessing_spawn(argv: list[str], out: Path) -> None:
    from tests.probes.sandbox_child import report_to_file

    process = multiprocessing.get_context("spawn").Process(
        target=report_to_file, args=(argv, str(out))
    )
    process.start()
    try:
        process.join(TIMEOUT)
        assert not process.is_alive(), "the spawned child did not finish"
        assert process.exitcode == 0
    finally:
        if process.is_alive():
            process.kill()
            process.join(10)


def _via_asyncio(argv: list[str], out: Path) -> None:
    async def run() -> int:
        child = await asyncio.create_subprocess_exec(
            sys.executable, str(PROBE), *argv, "--out", str(out)
        )
        return await asyncio.wait_for(child.wait(), TIMEOUT)

    assert asyncio.run(run()) == 0


def _unwrapped_popen_init() -> Callable[..., None]:
    """``Popen.__init__`` from under the conftest's wrapper, whatever its vintage."""
    init = subprocess.Popen.__init__
    real = getattr(init, "__wrapped__", None)
    if real is not None:
        return real
    for cell in getattr(init, "__closure__", None) or ():
        value = cell.cell_contents
        if callable(value) and getattr(value, "__qualname__", "") == "Popen.__init__":
            return value
    return init


def _via_repatched_popen(argv: list[str], out: Path) -> None:
    patch = pytest.MonkeyPatch()
    patch.setattr(subprocess.Popen, "__init__", _unwrapped_popen_init())
    try:
        done = subprocess.run(
            [sys.executable, str(PROBE), *argv, "--out", str(out)], timeout=TIMEOUT
        )
    finally:
        patch.undo()
    assert done.returncode == 0


@pytest.mark.parametrize(
    "start",
    [_via_os_system, _via_multiprocessing_spawn, _via_asyncio, _via_repatched_popen],
    ids=["os.system", "multiprocessing-spawn", "asyncio", "repatched-Popen"],
)
@pytest.mark.process
def test_a_child_started_by_any_route_is_sandboxed(
    start: Callable[[list[str], Path], None],
    redirected: list[str],
    tmp_path: Path,
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    out = tmp_path / "report.json"
    start(redirected, out)
    child = json.loads(out.read_text(encoding="utf-8"))
    _assert_sandboxed(child, _temp_root(tmp_path_factory))


# -- the doors no wrapper sees, kept out of the code -----------------------------

#: ``os`` attributes that start a process without ``subprocess.Popen``.
_UNWRAPPED_OS = ("system", "spawn", "exec", "posix_spawn", "fork", "startfile", "popen")
#: Modules that start processes without ``subprocess.Popen``.
_UNWRAPPED_MODULES = ("multiprocessing", "pty")
#: The one file allowed to use them: this one, which starts a child by each.
_ALLOWED = {"tests/test_subprocess_sandbox.py"}


def _unwrapped_calls(tree: ast.AST) -> list[str]:
    """Every process door in ``tree`` that bypasses ``subprocess.Popen``."""
    found: list[str] = []
    os_names = {"os"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "os" and alias.asname:
                    os_names.add(alias.asname)
                if alias.name.split(".")[0] in _UNWRAPPED_MODULES:
                    found.append(f"import {alias.name} (line {node.lineno})")
        if isinstance(node, ast.ImportFrom) and node.module:
            root = node.module.split(".")[0]
            if root in _UNWRAPPED_MODULES:
                found.append(f"from {node.module} import ... (line {node.lineno})")
            if node.module == "os":
                found += [
                    f"from os import {alias.name} (line {node.lineno})"
                    for alias in node.names
                    if alias.name.startswith(_UNWRAPPED_OS)
                ]
            if node.module == "concurrent.futures":
                found += [
                    f"from concurrent.futures import {alias.name} (line {node.lineno})"
                    for alias in node.names
                    if alias.name == "ProcessPoolExecutor"
                ]
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id in os_names
            and node.attr.startswith(_UNWRAPPED_OS)
        ):
            found.append(f"{node.value.id}.{node.attr} (line {node.lineno})")
        if isinstance(node, ast.Attribute) and node.attr == "ProcessPoolExecutor":
            found.append(f"ProcessPoolExecutor (line {node.lineno})")
    return found


def test_no_code_starts_a_process_the_guards_cannot_see() -> None:
    """
    ``os.system``/``spawn*``/``exec*``/``posix_spawn*``/``fork``/``startfile``/
    ``popen``, ``multiprocessing``, ``pty`` and ``ProcessPoolExecutor`` bypass
    the ``Popen`` wrapper (the marker still reaches them, but only this file
    may use them, to prove it). Scanned in ``tests/``, ``engine/``,
    ``scripts/`` and ``launcher.py``. ``getattr(os, ...)`` is not seen.
    """
    files = [REPO / "launcher.py"]
    for folder in ("tests", "engine", "scripts"):
        files += sorted((REPO / folder).rglob("*.py"))
    offenders: dict[str, list[str]] = {}
    for path in files:
        name = path.relative_to(REPO).as_posix()
        if name in _ALLOWED:
            continue
        found = _unwrapped_calls(ast.parse(path.read_text(encoding="utf-8"), str(path)))
        if found:
            offenders[name] = found
    assert offenders == {}


def test_the_scan_sees_each_door() -> None:
    """The scan's own canary: each spelling it must catch, caught."""
    source = (
        "import os\nimport os as o\nimport multiprocessing\nimport pty\n"
        "from os import execvp\nfrom concurrent.futures import ProcessPoolExecutor\n"
        "os.system('x')\no.spawnv(0, 'x', [])\nos.fork()\nos.startfile('x')\n"
    )
    assert len(_unwrapped_calls(ast.parse(source))) == 8


def test_the_callers_files_come_first_and_the_layer_is_not_repeated(tmp_path: Path) -> None:
    from tests.conftest import sandbox_env

    layer = tmp_path / "sandbox-config.yaml"
    marker = f"123{os.pathsep}{layer}"
    first, second = str(tmp_path / "a.yaml"), str(tmp_path / "b.yaml")
    env = sandbox_env({"CLOCKWORK_CONFIG": os.pathsep.join([first, second])}, layer, marker)
    assert env["CLOCKWORK_CONFIG"].split(os.pathsep) == [first, second, str(layer)]
    assert env["CLOCKWORK_TEST_SANDBOX"] == marker
    again = sandbox_env(env, layer, marker)
    assert again["CLOCKWORK_CONFIG"] == env["CLOCKWORK_CONFIG"]
    # A bytes-keyed env (POSIX os.environb style) stays bytes-keyed.
    raw = sandbox_env({b"PATH": b"/bin"}, layer, marker)
    assert all(isinstance(k, bytes) and isinstance(v, bytes) for k, v in raw.items())
    assert raw[b"CLOCKWORK_TEST_SANDBOX"] == os.fsencode(marker)


# -- the engine's side of the marker ---------------------------------------------


def _foreign_marker(layer: Optional[Path]) -> str:
    """A marker naming a pid that is not this process: this process is then a child."""
    return f"{os.getpid() + 1}{os.pathsep}{layer}" if layer is not None else str(os.getpid() + 1)


def test_the_mcp_json_writers_refuse_a_target_outside_the_sandbox(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from engine.mcp import skills_server

    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    outside = tmp_path / "owner" / "mcp.json"
    outside.parent.mkdir()
    outside.write_text('{"mcpServers": {"theirs": {}}}', encoding="utf-8")
    monkeypatch.setenv("CLOCKWORK_TEST_SANDBOX", _foreign_marker(sandbox / "layer.yaml"))

    with caplog.at_level(logging.WARNING, logger="engine.mcp.skills_server"):
        assert skills_server.backup_once(outside) is None
        with pytest.raises(PermissionError):
            skills_server._write_json_atomic(outside, {"mcpServers": {}})
        entry = skills_server.register_session(
            "http://127.0.0.1:9/mcp", "outside", path=outside, settle_seconds=0
        )
    assert entry is None
    assert outside.read_text(encoding="utf-8") == '{"mcpServers": {"theirs": {}}}'
    assert sorted(p.name for p in outside.parent.iterdir()) == ["mcp.json"]
    refusals = [r for r in caplog.records if "Refused to touch a file outside" in r.getMessage()]
    assert len(refusals) == 4, refusals  # each writer, called directly and by register_session
    assert all(r.levelno == logging.WARNING for r in refusals)

    inside = sandbox / "mcp.json"
    assert skills_server.register_session(
        "http://127.0.0.1:9/mcp", "inside", path=inside, settle_seconds=0
    )
    assert "engine-skills-inside" in inside.read_text(encoding="utf-8")


def test_a_marker_with_no_sandbox_refuses_every_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fail closed: a child whose marker names no layer may write nowhere."""
    from engine.mcp import skills_server

    monkeypatch.setenv("CLOCKWORK_TEST_SANDBOX", _foreign_marker(None))
    with pytest.raises(PermissionError):
        skills_server._write_json_atomic(tmp_path / "mcp.json", {"mcpServers": {}})
    assert not (tmp_path / "mcp.json").exists()


def test_the_suites_own_marker_changes_nothing(tmp_path: Path) -> None:
    """In the suite's own process (its pid in the marker) the writers are unchanged."""
    from engine.mcp import skills_server

    assert os.environ["CLOCKWORK_TEST_SANDBOX"].startswith(f"{os.getpid()}{os.pathsep}")
    target = tmp_path / "mcp.json"
    skills_server._write_json_atomic(target, {"mcpServers": {}})
    assert json.loads(target.read_text(encoding="utf-8")) == {"mcpServers": {}}


def test_a_child_neither_reads_nor_writes_local_yaml_through_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The Settings panel, in a child of the suite: nothing read, nothing written."""
    import engine.config as config
    from engine.api import settings

    directory = tmp_path / "config"
    directory.mkdir()
    local = directory / "local.yaml"
    local.write_text(yaml.safe_dump({"world": {"tick_interval_seconds": 11}}), encoding="utf-8")
    before = local.read_bytes()
    layer = tmp_path / "sandbox-config.yaml"
    layer.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(config, "_CONFIG_DIR", directory)
    monkeypatch.setattr(config, "_instance", None)
    monkeypatch.setattr(settings, "_LOCAL_CONFIG", local)
    monkeypatch.setenv("CLOCKWORK_TEST_SANDBOX", _foreign_marker(layer))
    try:
        assert settings._read_local() == ({}, "")
        result = settings.apply_settings({"world.tick_interval_seconds": 5})
        assert result["ok"] is False and "test sandbox" in result["error"], result
        assert local.read_bytes() == before
        assert config.get_config().get("llm.base_url") == DISCARD
    finally:
        monkeypatch.undo()
        config.reset_config()


def test_a_test_process_cannot_write_the_owners_local_yaml() -> None:
    """
    The conftest's audit hook refuses (raises inside the call) a write aimed
    at the real ``config/local.yaml``. Opened ``r+`` -- no create, no
    truncate -- so even a broken hook would change nothing.
    """
    from tests.conftest import REAL_SAVES_WRITES

    real = REPO / "config" / "local.yaml"
    try:
        with pytest.raises(PermissionError, match="config/local.yaml"):
            open(real, "r+", encoding="utf-8").close()  # noqa: SIM115
    finally:
        taken = [entry for entry in REAL_SAVES_WRITES if "local.yaml" in entry[1]]
        for entry in taken:
            REAL_SAVES_WRITES.remove(entry)
    assert taken, "the refusal was not recorded"


# -- the session snapshot of the owner's storage (controller note N3) ----------


@pytest.mark.process
def test_the_storage_snapshot_sees_a_childs_write(tmp_path_factory: pytest.TempPathFactory) -> None:
    """A write by ANOTHER process -- which no audit hook here can see -- shows
    in the snapshot the session compares at its end."""
    from tests.conftest import snapshot_changes, storage_snapshot

    watched = [(_temp_root(tmp_path_factory) / "lm-studio", "mcp.json")]
    before = storage_snapshot(watched)
    assert snapshot_changes(before, storage_snapshot(watched)) == []
    _run_probe()
    changes = snapshot_changes(before, storage_snapshot(watched))
    assert changes and all("mcp.json" in change for change in changes), changes


def test_the_storage_snapshot_sees_added_removed_and_changed(tmp_path: Path) -> None:
    from tests.conftest import snapshot_changes, storage_snapshot

    tree = tmp_path / "tree"
    (tree / "saves").mkdir(parents=True)
    kept = tree / "saves" / "kept.json"
    kept.write_text("1", encoding="utf-8")
    gone = tree / "gone.json"
    gone.write_text("x", encoding="utf-8")
    before = storage_snapshot([(tree, None)])
    kept.write_text("22", encoding="utf-8")
    gone.unlink()
    (tree / "users").mkdir()
    changes = snapshot_changes(before, storage_snapshot([(tree, None)]))
    kinds = sorted(change.split(" ", 1)[0] for change in changes)
    assert kinds == ["added", "changed", "removed"], changes
    changed = next(c for c in changes if c.startswith("changed"))
    assert "was 1 bytes" in changed and "now 2 bytes" in changed


def test_a_restore_that_keeps_size_and_mtime_still_shows(tmp_path: Path) -> None:
    """The owner's small files are hashed: copy2-style restores are seen."""
    from tests.conftest import snapshot_changes, storage_snapshot

    target = tmp_path / "mcp.json"
    target.write_text("aaaa", encoding="utf-8")
    stat = target.stat()
    before = storage_snapshot([(tmp_path, "mcp.json")])
    target.write_text("bbbb", encoding="utf-8")
    os.utime(target, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    changes = snapshot_changes(before, storage_snapshot([(tmp_path, "mcp.json")]))
    assert len(changes) == 1 and "sha256" in changes[0], changes


def test_the_real_storage_roots_cover_every_owner_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests import conftest

    home = tmp_path / "home"
    for name in ("HOME", "USERPROFILE"):
        monkeypatch.setenv(name, str(home))
    roots = set(conftest._real_storage_roots())
    data = conftest._REAL_DATA_ROOT
    for name in ("saves", "users", "hosting", "media"):
        assert (data / name, None) in roots, name
    assert (conftest._REAL_SAVES_DIR, None) in roots
    assert (home / ".cache" / "lm-studio", "mcp.json") in roots
    assert (home / ".lmstudio", "mcp.json") in roots
    assert (REPO / "config", "local.yaml") in roots


def test_a_change_under_a_watched_root_fails_the_session_check(tmp_path: Path) -> None:
    """``_real_storage_is_untouched``'s teardown, on a stand-in root."""
    from tests.conftest import assert_storage_unchanged, storage_snapshot

    roots = [(tmp_path / "saves", None), (tmp_path, "local.yaml")]
    (tmp_path / "saves").mkdir()
    before = storage_snapshot(roots)
    assert_storage_unchanged(before, roots)
    (tmp_path / "saves" / "run.json").write_text("{}", encoding="utf-8")
    with pytest.raises(AssertionError, match=r"added .*run\.json .*bytes"):
        assert_storage_unchanged(before, roots)


# -- fix round 2 ------------------------------------------------------------------
#
# N1: the wrapper hands every child the marker it captured at configure time,
# whatever os.environ or env= says when the child is spawned.


@pytest.mark.process
def test_a_child_is_sandboxed_after_the_marker_is_deleted_here(
    redirected: list[str], monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory
) -> None:
    monkeypatch.delenv("CLOCKWORK_TEST_SANDBOX")
    child = _run_probe(*redirected)
    _assert_sandboxed(child, _temp_root(tmp_path_factory))


@pytest.mark.process
def test_a_child_is_sandboxed_after_the_environment_is_cleared(
    redirected: list[str], tmp_path: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    from unittest import mock

    # Only what a Python child needs to start (and the redirected home).
    keep = {
        name: os.environ[name]
        for name in ("SYSTEMROOT", "SystemRoot", "PATH", "HOME", "USERPROFILE", "TEMP", "TMP")
        if name in os.environ
    }
    with mock.patch.dict(os.environ, keep, clear=True):
        assert "CLOCKWORK_TEST_SANDBOX" not in os.environ
        child = _run_probe(*redirected)
    _assert_sandboxed(child, _temp_root(tmp_path_factory))


@pytest.mark.process
def test_a_child_is_sandboxed_when_its_env_scrubs_the_marker(
    redirected: list[str], tmp_path_factory: pytest.TempPathFactory
) -> None:
    env = {k: v for k, v in os.environ.items() if not k.startswith("CLOCKWORK_")}
    child = _run_probe(*redirected, env=env)
    _assert_sandboxed(child, _temp_root(tmp_path_factory))


# Import-time gap and N4: a pid-only marker from the top of conftest; a stray one refused.


class _AsAChild:
    """This process, briefly treated as a child of the suite: a foreign marker."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.monkeypatch = monkeypatch

    def __call__(self, layer: Optional[Path] = None) -> Any:
        import engine.config as config

        self.monkeypatch.setenv("CLOCKWORK_TEST_SANDBOX", _foreign_marker(layer))
        self.monkeypatch.setattr(config, "_instance", None)
        self.monkeypatch.setattr(config, "_SANDBOX_WARNED", False)
        return config.get_config()


@pytest.fixture
def as_a_child(monkeypatch: pytest.MonkeyPatch) -> Any:
    import engine.config as config

    try:
        yield _AsAChild(monkeypatch)
    finally:
        monkeypatch.undo()
        config.reset_config()


def test_a_pid_only_marker_is_a_child_with_nothing_writable(as_a_child: Any, tmp_path: Path) -> None:
    """What a child started before pytest_configure gets: no layer, fail closed."""
    from engine.config import TEST_SANDBOX_BASE_URL, child_sandbox

    cfg = as_a_child(None)
    sandbox = child_sandbox()
    assert sandbox is not None and sandbox.root is None
    assert not sandbox.contains(tmp_path / "mcp.json")
    assert cfg.get("llm.base_url") == TEST_SANDBOX_BASE_URL


def test_the_marker_is_set_before_any_engine_import() -> None:
    """The conftest sets its pid-only marker before it imports the engine."""
    source = (REPO / "tests" / "conftest.py").read_text(encoding="utf-8")
    assert source.index("os.environ[_SANDBOX_ENV] =") < source.index("from engine")
    assert source.index("refuse_an_inherited_marker(os.environ") < source.index("from engine")


def test_a_stray_marker_is_refused_by_the_conftest() -> None:
    from tests.conftest import refuse_an_inherited_marker

    refuse_an_inherited_marker({}, 42)
    refuse_an_inherited_marker({"CLOCKWORK_TEST_SANDBOX": f"42{os.pathsep}x"}, 42)
    for stray in ("7", f"7{os.pathsep}x", "garbage"):
        with pytest.raises(pytest.UsageError, match="already set"):
            refuse_an_inherited_marker({"CLOCKWORK_TEST_SANDBOX": stray}, 42)


@pytest.mark.process
def test_a_suite_started_under_a_marker_fails_fast(tmp_path: Path) -> None:
    """
    A pytest run as a child of this one inherits this suite's marker and
    stops at conftest import, before collecting anything, with the reason.
    """
    done = subprocess.run(
        [sys.executable, "-m", "pytest", str(REPO / "tests" / "test_ci_workflow.py"),
         "--co", "-q", "-p", "no:cacheprovider", f"--basetemp={tmp_path / 'nested'}"],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=TIMEOUT,
    )
    assert done.returncode != 0
    assert "is already set in this environment" in done.stdout + done.stderr


def test_a_sandboxed_process_warns_once(as_a_child: Any, caplog: pytest.LogCaptureFixture) -> None:
    from engine.config import child_sandbox

    with caplog.at_level(logging.WARNING, logger="engine.config"):
        as_a_child(None)
        child_sandbox()
        child_sandbox()
    warnings = [r for r in caplog.records if "runs as a child of a test suite" in r.getMessage()]
    assert len(warnings) == 1 and warnings[0].levelno == logging.WARNING


def _doctor() -> Any:
    import importlib.util

    spec = importlib.util.spec_from_file_location("doctor_sandbox_under_test", REPO / "scripts" / "doctor.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_the_doctor_fails_a_stray_marker(as_a_child: Any) -> None:
    doctor = _doctor()
    clean = doctor.Report()
    doctor.check_config(clean)
    assert not [row for row in clean.rows if row[1] == "CLOCKWORK_TEST_SANDBOX"]

    as_a_child(None)
    report = doctor.Report()
    doctor.check_config(report)
    rows = [row for row in report.rows if row[1] == "CLOCKWORK_TEST_SANDBOX"]
    assert len(rows) == 1 and rows[0][2] == doctor.FAIL, rows
    assert "Unset CLOCKWORK_TEST_SANDBOX" in rows[0][3]


def test_launcher_check_fails_a_stray_marker(
    as_a_child: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import launcher
    from engine import stack

    monkeypatch.setattr(stack.StackManager, "status", lambda self: [])
    assert launcher.main(["--check"]) == 0
    assert "CLOCKWORK_TEST_SANDBOX" not in capsys.readouterr().out

    as_a_child(None)
    assert launcher.main(["--check"]) == 1
    assert "FAIL  CLOCKWORK_TEST_SANDBOX" in capsys.readouterr().out


# N2: ComfyUI, TTS, STT and every managed service off in a child, whatever its layers say.


def test_a_child_has_every_other_service_off(as_a_child: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from engine.config import TEST_SANDBOX_SERVICE_URL

    own = tmp_path / "services-on.yaml"
    own.write_text(
        yaml.safe_dump(
            {
                "comfyui": {"enabled": True, "base_url": "http://localhost:8188"},
                "tts": {"enabled": True, "assistant_enabled": True, "base_url": "http://127.0.0.1:8123"},
                "stt": {"base_url": "http://localhost:5051"},
                "stack": {"services": {"comfyui": {"manage": True}, "voxtral_tts": {"manage": True}}},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("CLOCKWORK_CONFIG", str(own))
    cfg = as_a_child(None)  # no layer at all: the force holds on its own
    assert cfg.get("comfyui.enabled") is False
    assert cfg.get("tts.enabled") is False and cfg.get("tts.assistant_enabled") is False
    for key in ("comfyui.base_url", "tts.base_url", "stt.base_url"):
        assert cfg.get(key) == TEST_SANDBOX_SERVICE_URL, key
    services = cfg.get("stack.services")
    assert services and all(spec.get("manage") is False for spec in services.values()), services


def test_the_session_layer_turns_every_other_service_off(tmp_path_factory: pytest.TempPathFactory) -> None:
    layer = yaml.safe_load((_temp_root(tmp_path_factory) / "sandbox-config.yaml").read_text(encoding="utf-8"))
    assert layer["comfyui"]["enabled"] is False and layer["tts"]["enabled"] is False
    assert layer["stt"]["base_url"].endswith(":9")
    assert all(spec["manage"] is False for spec in layer["stack"]["services"].values())


# N3: a child keeps the sandbox layer's llm.base_url only on the registered loopback stub port.


@pytest.mark.parametrize(
    ("layer_url", "registered", "kept"),
    [
        ("http://127.0.0.1:5555/v1", "5555", True),
        ("http://localhost:5555/v1", "5555", True),
        ("http://127.0.0.1:5555/v1", "5556", False),
        ("http://127.0.0.1:5555/v1", None, False),
        ("http://10.0.0.7:5555/v1", "5555", False),
        ("http://models.example:5555/v1", "5555", False),
        # v0.20.0 T16 (from T5's re-review): plain http only.
        ("https://127.0.0.1:5555/v1", "5555", False),
        ("ftp://127.0.0.1:5555/v1", "5555", False),
    ],
    ids=[
        "loopback-registered",
        "localhost-registered",
        "other-port",
        "unregistered",
        "lan-host",
        "remote-host",
        "https-scheme",
        "other-scheme",
    ],
)
def test_a_child_uses_only_a_registered_loopback_stub(
    as_a_child: Any,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    layer_url: str,
    registered: Optional[str],
    kept: bool,
) -> None:
    layer = tmp_path / "sandbox-config.yaml"
    layer.write_text(yaml.safe_dump({"llm": {"base_url": layer_url}}), encoding="utf-8")
    if registered is None:
        monkeypatch.delenv("CLOCKWORK_TEST_MODEL_STUB_PORT", raising=False)
    else:
        monkeypatch.setenv("CLOCKWORK_TEST_MODEL_STUB_PORT", registered)
    cfg = as_a_child(layer)
    assert cfg.get("llm.base_url") == (layer_url if kept else DISCARD)


@pytest.mark.process
def test_a_child_dials_a_registered_stub_and_nothing_else(
    sandbox_model_stub: Any, redirected: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    url = sandbox_model_stub(5555)
    assert _run_probe(*redirected)["base_url"] == url
    # A caller's own env= cannot register a port: only this process's registration counts.
    monkeypatch.delenv("CLOCKWORK_TEST_MODEL_STUB_PORT")
    env = dict(os.environ, CLOCKWORK_TEST_MODEL_STUB_PORT="5555")
    assert _run_probe(*redirected, env=env)["base_url"] == DISCARD


# v0.20.0 T16 fix round 1 (I3): a child has NO API key but the sandbox layer's own.
# The shipped chain reads key files in the repository root (the owner's
# lmstudio.txt) and LMSTUDIO_API_KEY; a child of the suite must read neither,
# nor send one to a stub that records what it is sent.

_CHILD_KEY = "sk-t16-child-sentinel"


def test_a_child_has_no_api_key_unless_the_sandbox_layer_names_one(
    as_a_child: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    own = tmp_path / "own.yaml"
    own.write_text(
        yaml.safe_dump({"llm": {"provider": "openai_compat", "api_key": "${env:T16_CHILD_KEY}"}}), encoding="utf-8"
    )
    monkeypatch.setenv("CLOCKWORK_CONFIG", str(own))
    monkeypatch.setenv("T16_CHILD_KEY", _CHILD_KEY)
    layer = tmp_path / "sandbox-config.yaml"
    layer.write_text(yaml.safe_dump({"llm": {"base_url": DISCARD}}), encoding="utf-8")
    cfg = as_a_child(layer)
    has_key = bool(cfg.get("llm.api_key"))
    assert has_key is False, "a child resolved an API key the sandbox layer does not name"
    assert cfg.secret_source("llm.api_key") == ("", "")
    layer.write_text(yaml.safe_dump({"llm": {"base_url": DISCARD, "api_key": "${env:T16_CHILD_KEY}"}}), encoding="utf-8")
    cfg = as_a_child(layer)
    assert cfg.get("llm.api_key") == _CHILD_KEY
    assert cfg.secret_source("llm.api_key") == ("environment", "T16_CHILD_KEY")


def test_a_child_on_lm_studio_reads_no_key_file_and_no_lm_studio_variable(
    as_a_child: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The shipped chain, provider lmstudio: the repo-root key files and LMSTUDIO_API_KEY are not read."""
    monkeypatch.delenv("CLOCKWORK_CONFIG", raising=False)
    monkeypatch.setenv("LMSTUDIO_API_KEY", _CHILD_KEY)
    monkeypatch.setenv("CLOCKWORK_LLM_API_KEY", _CHILD_KEY)
    layer = tmp_path / "sandbox-config.yaml"
    layer.write_text(yaml.safe_dump({"llm": {"base_url": DISCARD}}), encoding="utf-8")
    cfg = as_a_child(layer)
    assert cfg.get("llm.provider") == "lmstudio"
    has_key = bool(cfg.get("llm.api_key"))
    assert has_key is False, "a child resolved the shipped key chain"


class _KeyStub:
    """An OpenAI-compatible model list on loopback that records only WHETHER each request carried a key."""

    def __init__(self, expected: str) -> None:
        import threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

        self.seen: list[tuple[str, bool, bool]] = []
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args: Any) -> None:
                return

            def do_GET(self) -> None:  # noqa: N802
                auth = self.headers.get("Authorization")
                stub.seen.append((self.path, auth is not None, auth == f"Bearer {expected}"))
                body = json.dumps({"object": "list", "data": [{"id": "stub", "object": "model"}]}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, name="t16-key-stub", daemon=True)
        self.thread.start()

    @property
    def port(self) -> int:
        return int(self.server.server_address[1])

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(10)
        assert not self.thread.is_alive()


@pytest.mark.process
def test_a_child_sends_no_key_to_the_registered_stub_unless_the_layer_names_one(
    sandbox_model_stub: Any, redirected: list[str], tmp_path: Path
) -> None:
    """
    A real child, provider openai_compat (so the chain's environment
    alternative answers), the key a sentinel in its environment: it probes the
    registered stub with NO Authorization header. Named in the sandbox layer,
    the key is sent. On e094d4e the first probe carried the sentinel.
    """
    stub = _KeyStub(_CHILD_KEY)
    try:
        own = tmp_path / "own.yaml"
        own.write_text(yaml.safe_dump({"llm": {"provider": "openai_compat"}}), encoding="utf-8")
        sandbox_model_stub(stub.port)
        env = dict(os.environ, CLOCKWORK_CONFIG=str(own), CLOCKWORK_LLM_API_KEY=_CHILD_KEY)
        child = _run_probe(*redirected, "--probe-model", env=env)
        assert child["probed"] is True and child["api_key_set"] is False and child["api_key_kind"] == "", child
        assert stub.seen and not any(carried for _path, carried, _ok in stub.seen), stub.seen

        stub.seen.clear()
        sandbox_model_stub(stub.port, api_key="${env:CLOCKWORK_LLM_API_KEY}")
        child = _run_probe(*redirected, "--probe-model", env=env)
        assert child["probed"] is True and child["api_key_set"] is True and child["api_key_kind"] == "environment"
        assert stub.seen and all(ok for _path, _carried, ok in stub.seen), stub.seen
    finally:
        stub.stop()
