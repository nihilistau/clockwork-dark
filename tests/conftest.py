"""Pytest fixtures."""

from __future__ import annotations

import contextlib
import inspect
import os
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Optional

import pytest
import yaml

#: The child-sandbox marker (``engine.config.TEST_SANDBOX_ENV``), spelled out
#: here because this block runs before any engine import.
_SANDBOX_ENV = "CLOCKWORK_TEST_SANDBOX"


def refuse_an_inherited_marker(environ: Mapping[str, str], pid: int) -> None:
    """
    Fail fast when the suite starts with a ``CLOCKWORK_TEST_SANDBOX`` it did
    not set (T5 re-review, N4): a stray export in the owner's shell, or a
    suite run as the child of another. Either way the whole session would run
    sandboxed, in-process config included, and fail with unrelated golden
    diffs. The one value let through is this process's own marker (the second
    import of this file, as ``tests.conftest``, finds it).
    """
    raw = str(environ.get(_SANDBOX_ENV, "") or "").strip()
    if raw and raw.partition(os.pathsep)[0].strip() != str(pid):
        raise pytest.UsageError(
            f"{_SANDBOX_ENV} is already set in this environment ({raw!r}): the "
            "test suite sets its own and cannot run under another's. Unset it "
            f"(it is only ever meant for the suite's child processes) and run again."
        )


# FIRST, before any engine import can start anything: refuse a stray marker,
# then set a pid-only one, so a child started in the window before
# pytest_configure (by this file's import-time code, or another plugin's
# configure hook) is already a sandboxed child -- local.yaml skipped, nothing
# writable, the discard port. pytest_configure upgrades it to <pid>;<layer>.
refuse_an_inherited_marker(os.environ, os.getpid())
os.environ[_SANDBOX_ENV] = os.environ.get(_SANDBOX_ENV) or str(os.getpid())

from engine.game.engine import GameEngine, set_active_engine  # noqa: E402
from engine.game.state import GameState  # noqa: E402


#: The port a URL that names none is dialled on.
_DEFAULT_PORTS = {"http": 80, "https": 443}


def _model_server_urls() -> list[str]:
    """
    Every URL that can mean "the model server" in this process, right now.

    ``llm.base_url`` and the model server's health URL, read from the same
    config the engine dials, so moving the server moves the guard with it --
    and every provider's default base URL (``PROVIDERS``), so a test that
    reaches a vLLM, llama-server or Ollama on its usual loopback port is
    refused even while the config names LM Studio. Until v0.19.0 T3 only the
    configured URL was guarded, and 8000, 8080 and 11434 were open.
    """
    urls: list[str] = []
    try:
        from engine.config import get_config

        cfg = get_config()
        urls += [str(cfg.get(key) or "") for key in ("llm.base_url", "stack.services.llm.health_url")]
    except Exception:  # noqa: BLE001 -- a bad config must not break the guard
        pass
    try:
        from engine.llm.providers import PROVIDERS

        urls += [str(p.default_base_url.value or "") for p in PROVIDERS.values()]
    except Exception:  # noqa: BLE001
        pass
    return [u for u in urls if u]


def _model_endpoints() -> frozenset[tuple[str, int]]:
    """
    Every address that means "the model server", as ``(host, port)``.

    COMPUTED AT CHECK TIME, never frozen at import: the guard asks this on
    every resolve and connect, so a test that repoints ``llm.base_url`` (or a
    provider added to the table) is guarded at once. The import-time snapshot
    this replaced guarded only what the config said when collection began.

    All three loopback spellings are included because a client may resolve
    ``localhost`` to any of them and a guard that only knew one would be a
    guard with a hole in it.

    A URL with no port is guarded on its scheme's default. Until v0.19.0 such
    a URL was skipped, so a hosted ``https://models.example/v1`` server was not
    guarded at all; and two of the three keys read here then
    (``lmstudio.native_url``, ``stack.health_url``) had never existed.
    """
    from urllib.parse import urlparse

    blocked: set[tuple[str, int]] = set()
    for raw in _model_server_urls():
        try:
            parsed = urlparse(raw)
            port = parsed.port or _DEFAULT_PORTS.get(parsed.scheme.lower())
        except Exception:  # noqa: BLE001 -- a bad key must not break the guard
            continue
        if port is None:
            continue
        host = (parsed.hostname or "").lower()
        hosts = {host}
        if host in {"localhost", "127.0.0.1", "::1"}:
            hosts |= {"localhost", "127.0.0.1", "::1"}
        blocked |= {(h, int(port)) for h in hosts if h}
    return frozenset(blocked)


def _is_loopback(name: str) -> bool:
    """
    Whether ``name`` (a host name or an address, lower case) can only mean
    this machine: ``localhost`` (and ``*.localhost``), a loopback address
    (an IPv4-mapped one included), the unspecified address, or empty.
    """
    import ipaddress

    text = name.strip().strip("[]").rstrip(".")
    if text in {"", "localhost"} or text.endswith(".localhost"):
        return True
    try:
        address = ipaddress.ip_address(text.split("%", 1)[0])
    except ValueError:
        return False
    mapped = getattr(address, "ipv4_mapped", None)
    if mapped is not None:
        address = mapped
    return address.is_loopback or address.is_unspecified


def _is_registered_stub(name: str, port: int) -> bool:
    """The loopback port a test registered with ``sandbox_model_stub``."""
    registered = os.environ.get(_STUB_PORT_ENV, "")
    return bool(registered) and registered == str(port) and _is_loopback(name)


#: The resolver the live-call guard wraps. Read at call time, so the guard's own
#: tests can put a stub resolver UNDER the guard (``tests/test_conftest_guard.py``).
_REAL_GETADDRINFO = socket.getaddrinfo
#: Likewise for ``gethostbyname`` and ``socket.connect`` (T8 fix round 2), so
#: the default-deny canary can put a recording stub under EVERY branch it
#: drives and a broken guard sends nothing off the machine.
_REAL_GETHOSTBYNAME = socket.gethostbyname
_REAL_CONNECT = socket.socket.connect

#: The running test's recorded breaches, which ``_no_live_model_calls`` asserts
#: empty at teardown. Module-level only so the guard's own tests can take back
#: the one breach they provoke on purpose.
_BREACHES: list[str] = []


def _empty_model_list() -> dict[str, Any]:
    """
    What model discovery is answered with under the guard: the configured
    provider's model list, empty, in that server's own shape -- so discovery
    parses it and lands on the engine's no-models path for every provider,
    rather than refusing LM Studio's shape as "not a vLLM list".
    """
    from engine.llm.providers import get_provider

    return get_provider().empty_model_list()


@pytest.fixture(autouse=True)
def _no_story_outlives_its_test() -> Iterator[None]:
    """
    A story a test activates is deactivated when that test ends.

    WHY THIS EXISTS. Nineteen test files call ``registry.activate`` and most
    never undo it, so the story active at the start of any test was whatever
    the PREVIOUS file left behind. The suite passed only because alphabetical
    order happened to run flagship-activating files ahead of the ones that
    assume the flagship -- measured in v0.8 when a new file ending on
    neon-city sat in front of ``test_livelihood.py`` and failed 22 of its 41
    tests, every one of which passes alone. The same class as the
    ``_DOOM_DECLARED`` memo below: state that outlives the test that set it.

    ONLY WHEN IT CHANGED. ``deactivate`` resets the whole config overlay, and a
    per-test reset of everything was measured once before at 3m40s -> 6m35s.
    Comparing the active manifest before and after means a test that never
    touches activation pays nothing.
    """
    from engine.games import registry

    before = registry.peek()
    try:
        yield
    finally:
        if registry.peek() is not before:
            registry.deactivate()


@pytest.fixture(autouse=True)
def _no_lane_backend_outlives_its_test() -> Iterator[None]:
    """
    A lane backend a test sets (``engine.llm.gate.set_lane_backend``, v0.20.0
    T11) is gone when it ends, and the test that leaked it fails.

    WHY THIS EXISTS. A supervised worker sets one at startup, for its life;
    a test that builds a supervised app, or plugs in the shared queue, and
    forgets it would send every later test's lanes to a closed bus -- each
    turn then refused busy, far from the test that caused it. The same class
    as the story above: state that outlives the test that set it.
    """
    yield
    gate = sys.modules.get("engine.llm.gate")
    if gate is not None and gate.lane_backend() is not None:
        gate.reset_lane_backend()
        pytest.fail("this test left a lane backend set (engine.llm.gate.set_lane_backend)")


@pytest.fixture(autouse=True)
def _content_caches_are_per_test() -> Iterator[None]:
    """
    Drop every memoized content answer after each test.

    WHY THIS EXISTS. The engine memoizes answers derived from the active
    story's manifest -- ``evil_ticker._DOOM_DECLARED`` is the one that bit --
    and invalidates them through ``engine/games/caches.py`` when a story is
    ACTIVATED or deactivated. That contract is correct in production, where
    the manifest only ever changes by activation.

    Tests break it. ``tests/test_scene_seam.py`` monkeypatches
    ``engine.games.registry.entry_manifest`` to return a synthetic manifest
    without activating anything, something asks ``doom_enabled()`` inside that
    window, and the answer -- False, because the synthetic manifest declares no
    doom -- is memoized into a module global. The monkeypatch is undone at
    teardown; the memo is not, and nothing calls the invalidator because
    nothing activated.

    The result was a test that passed alone, passed in the full suite, and
    failed in between: ``test_turn_integration.py::test_world_advances_over_a_session``
    watched ``advance_time`` produce exactly zero evil, because the ticker had
    been told this story has no doom clock by a manifest belonging to a
    different test. It cost real time to find precisely because the config, the
    active slug and the resolved paths were all identical -- only the memo
    differed.

    SCOPED TO THE MANIFEST-DERIVED MEMOS, not to ``reset_all_caches()``. The
    full reset also runs the RELOADERS, which include
    ``lmstudio.profiles/registry/backend/gate`` -- those are derived from CONFIG
    rather than from the manifest, they cannot be poisoned this way, and
    clearing them per test forces model re-resolution on every single one. That
    version took the suite from 3m40s to 6m35s and broke two prompt-budget
    tests, because a cleared profile cache resolves the budget from config
    fallbacks instead of from the bound model.

    ``NULLED_ATTRIBUTES`` is exactly the set at risk -- each entry is a plain
    ``Optional`` memo of something read out of the active story -- and setting
    them to None costs nothing.
    """
    import sys

    from engine.games.caches import NULLED_ATTRIBUTES

    try:
        yield
    finally:
        for module_name, attribute in NULLED_ATTRIBUTES:
            module = sys.modules.get(module_name)
            if module is not None and hasattr(module, attribute):
                setattr(module, attribute, None)


_REPO_ROOT = Path(__file__).resolve().parents[1]

#: The storage-root environment variable (``engine/persistence/storage.py``).
_DATA_DIR_ENV = "CLOCKWORK_DATA_DIR"


def _resolve_real_storage() -> tuple[Path, Path]:
    """
    The owner's REAL storage root and local save directory, resolved once at
    import with ``CLOCKWORK_DATA_DIR`` removed for the call: the config's
    ``storage.root`` (``data`` by default, anchored at the repository), and
    its ``saves/`` or the owner's legacy ``paths.saves`` alias. Whatever the
    shell exported, these are the directories a test must never write.
    """
    from engine.persistence import storage

    exported = os.environ.pop(_DATA_DIR_ENV, None)
    try:
        return storage.data_root(), storage.saves_dir("", None)
    finally:
        if exported is not None:
            os.environ[_DATA_DIR_ENV] = exported


_REAL_DATA_ROOT, _REAL_SAVES_DIR = _resolve_real_storage()


def _resolve_real_mcp_json_dir() -> Optional[Path]:
    """
    The directory of an ``llm.mcp.mcp_json`` the owner declared, read with the
    owner's config -- an exported ``CLOCKWORK_CONFIG`` included, so resolved
    BEFORE ``_clear_inherited_environment`` removes it (T5 fix round 1, review
    minor 8).
    """
    try:
        from engine.config import get_config

        declared = str(get_config().get("llm.mcp.mcp_json", "") or "").strip()
    except Exception:  # noqa: BLE001 -- the home locations are still watched
        return None
    return Path(declared).expanduser().parent if declared else None


_REAL_MCP_JSON_DIR = _resolve_real_mcp_json_dir()

#: The owner's own ``config/local.yaml``: never written by a test process
#: (``_saves_audit_hook`` refuses it) and snapshotted for the session.
_REAL_CONFIG_DIR = _REPO_ROOT / "config"
_REAL_LOCAL_YAML: frozenset[str] = frozenset(
    os.path.normcase(os.path.abspath(p))
    for p in (_REAL_CONFIG_DIR / "local.yaml", _REAL_CONFIG_DIR / "local.yaml.tmp")
)

#: The external config layer's variable, and the child-sandbox marker the
#: engine honours (v0.20.0 T5, spec §3.5): ``engine/config.py``,
#: ``engine/mcp/skills_server.py`` and ``engine/api/settings.py``.
_CONFIG_ENV = "CLOCKWORK_CONFIG"

#: A storage root the owner's shell exported, kept so the session snapshot
#: (``_real_storage_is_untouched``) watches it as well as the default one.
_EXPORTED_DATA_ROOT: Optional[Path] = (
    Path(os.environ[_DATA_DIR_ENV]).expanduser().resolve()
    if os.environ.get(_DATA_DIR_ENV, "").strip()
    else None
)


def _clear_inherited_environment() -> None:
    """
    Remove ``CLOCKWORK_CONFIG``, ``CLOCKWORK_DATA_DIR`` and
    ``CLOCKWORK_TEST_SANDBOX`` from THIS process's environment, once, at
    session start (conftest import, before any test module is collected).

    ``CLOCKWORK_CONFIG`` ranks above ``config/local.yaml``: exported by the
    owner's shell or a CI runner, it would rewrite the config every in-process
    test sees, and both goldens with it. ``CLOCKWORK_DATA_DIR`` would move the
    storage root under every test that does not set its own. The real storage
    above was resolved first, with the owner's config, so the guards still
    watch the directories the owner actually uses.

    The sandbox marker is not touched here: a stray one was refused at the
    top of this file (``refuse_an_inherited_marker``), and this session's own
    is set there and upgraded in ``pytest_configure``.
    """
    had_config = os.environ.pop(_CONFIG_ENV, None) is not None
    os.environ.pop(_DATA_DIR_ENV, None)
    if had_config:
        from engine.config import reset_config

        reset_config()


_clear_inherited_environment()


def _real_saves_dir() -> Path:
    """The owner's real local save directory (see ``_resolve_real_storage``)."""
    return _REAL_SAVES_DIR


#: The owner's real run-time data, as normalized prefixes, resolved once: the
#: local saves, every account's saves (``users/``) and hosted mode's accounts
#: and cookie key (``hosting/``), all under the real storage root (v0.20.0 T3
#: fix round 1: the guard watched only ``saves/``, and an account's store is
#: built on ``data_root()``, not on the redirected ``saves_base``).
_REAL_PREFIXES: tuple[str, ...] = tuple(
    os.path.normcase(os.path.abspath(p)) + os.sep
    for p in (_REAL_SAVES_DIR, _REAL_DATA_ROOT / "users", _REAL_DATA_ROOT / "hosting")
)

#: Writes THIS process attempted under the real save directory, as
#: ``(event, path)``. Filled by ``_saves_audit_hook``, drained per test.
#:
#: Kept on ``sys`` rather than in this module because this file is imported
#: TWICE: pytest loads it as ``conftest`` and a test's ``from tests.conftest
#: import ...`` loads a second copy. Two lists (and two hooks) would let a test
#: clear one while the fixture asserted on the other.
_SHARED_KEY = "_clockwork_dark_real_saves_writes"
_shared: Any = getattr(sys, _SHARED_KEY, None)
_HOOK_INSTALLED = _shared is not None
if _shared is None:
    _shared = []
    setattr(sys, _SHARED_KEY, _shared)
REAL_SAVES_WRITES: list[tuple[str, str]] = _shared

#: ``os.open`` flags that mean the file is being written, not just read.
_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_TRUNC

#: Audit events that change the filesystem at a path (the first argument, and
#: for a rename the second as well).
_WRITE_EVENTS = frozenset({"os.rename", "os.mkdir", "os.remove", "os.rmdir"})


def _under_real_saves(path: Any) -> bool:
    if isinstance(path, bytes):
        path = os.fsdecode(path)
    if not isinstance(path, (str, os.PathLike)):
        return False  # a file descriptor, or dir_fd-relative: no path to judge
    full = os.path.normcase(os.path.abspath(os.fspath(path)))
    return any(full == prefix[:-1] or full.startswith(prefix) for prefix in _REAL_PREFIXES)


def _saves_audit_hook(event: str, args: tuple[Any, ...]) -> None:
    """
    Record any attempt by this process to write under the real save directory.

    Runs on every audit event, so it rejects cheaply: event name first, then
    (for ``open``) whether the open is a write at all, and only then resolves
    a path. It never raises for its own failures -- an exception here would
    surface inside whatever unrelated call raised the event.

    ONE DELIBERATE RAISE: a write aimed at the owner's real
    ``config/local.yaml`` (or its ``.tmp`` sibling, the Settings panel's
    atomic write) is REFUSED with a ``PermissionError`` from inside the call,
    as well as recorded (T5 fix round 1, review finding 2): that file is the
    owner's hand-kept config, and the panel's writer resolves it from the
    checkout, not from any redirect a test made.
    """
    refuse: Optional[str] = None
    try:
        if event == "open":
            path, mode, flags = args
            if isinstance(mode, str):
                if not any(c in mode for c in "wax+"):
                    return
            elif not (int(flags or 0) & _WRITE_FLAGS):
                return
            paths: tuple[Any, ...] = (path,)
        elif event in _WRITE_EVENTS:
            paths = args[:2] if event == "os.rename" else args[:1]
        else:
            return
        for path in paths:
            if _under_real_saves(path):
                REAL_SAVES_WRITES.append((event, os.fspath(path)))
            elif _is_real_local_yaml(path):
                REAL_SAVES_WRITES.append((event, os.fspath(path)))
                refuse = os.fspath(path)
    except Exception:  # noqa: BLE001 -- see the docstring
        return
    if refuse is not None:
        raise PermissionError(
            f"a test tried to write the owner's config/local.yaml ({refuse}); "
            "redirect it (settings._LOCAL_CONFIG, engine.config._CONFIG_DIR) to tmp_path"
        )


def _is_real_local_yaml(path: Any) -> bool:
    if isinstance(path, bytes):
        path = os.fsdecode(path)
    if not isinstance(path, (str, os.PathLike)):
        return False
    return os.path.normcase(os.path.abspath(os.fspath(path))) in _REAL_LOCAL_YAML


# Installed once per process, by whichever copy of this file loads first: an
# audit hook cannot be removed, and a second would double every entry.
if not _HOOK_INSTALLED:
    sys.addaudithook(_saves_audit_hook)


# -- child processes: the sandbox layer (v0.20.0 T5, spec §3.5) ---------------

#: What a child's ``llm.base_url`` is: the discard port, which refuses.
SANDBOX_BASE_URL = "http://127.0.0.1:9/v1"

#: The sandbox layer's file name, in the session's temp root.
SANDBOX_LAYER_NAME = "sandbox-config.yaml"


def sandbox_layer(root: Path, services: Iterable[str]) -> dict[str, Any]:
    """
    The config layer every child process ends its ``CLOCKWORK_CONFIG`` with
    (spec §3.5): the model server on the discard port, the MCP bridge off and
    its ``mcp.json`` in the temp root, the storage root in the temp root, and
    no managed service started.
    """
    return {
        "llm": {
            "base_url": SANDBOX_BASE_URL,
            "mcp": {"enabled": False, "mcp_json": str(root / "lm-studio" / "mcp.json")},
        },
        "storage": {"root": str(root / "data")},
        "stack": {"services": {name: {"manage": False} for name in sorted(services)}},
        # Every other server a child could dial, off and on the discard port
        # (engine.config._force_sandbox holds a child to the same, layer or
        # none: T5 re-review, N2).
        "comfyui": {"enabled": False, "base_url": SANDBOX_SERVICE_URL},
        "tts": {"enabled": False, "assistant_enabled": False, "base_url": SANDBOX_SERVICE_URL},
        "stt": {"base_url": SANDBOX_SERVICE_URL},
    }


#: What a child's other service URLs are: the discard port.
SANDBOX_SERVICE_URL = "http://127.0.0.1:9"

#: The companion variable naming a test's stub model port
#: (``engine.config.TEST_MODEL_STUB_PORT_ENV``).
_STUB_PORT_ENV = "CLOCKWORK_TEST_MODEL_STUB_PORT"


def _pass_stub_port(env: dict[Any, Any]) -> None:
    """Set the child's stub port from THIS process's registration, or drop it."""
    as_bytes = any(isinstance(key, bytes) for key in env)
    key: Any = os.fsencode(_STUB_PORT_ENV) if as_bytes else _STUB_PORT_ENV
    registered = os.environ.get(_STUB_PORT_ENV, "")
    if registered:
        env[key] = os.fsencode(registered) if as_bytes else registered
    else:
        env.pop(key, None)


@pytest.fixture
def sandbox_model_stub(monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    """
    Let this test's children dial a stub model server on loopback.

    Yields ``register(port)``: the session's sandbox layer names
    ``http://127.0.0.1:<port>/v1`` as ``llm.base_url`` and the companion
    variable registers the port, for this test only (both restored at
    teardown). A sandboxed child keeps that URL only because both agree and
    it is loopback (``engine.config._sandbox_model_url``); anything else is
    the discard port. For the hosted supervisor's stub server (v0.20.0 T16).
    """
    with _model_stub_registration(monkeypatch) as register:
        yield register


@contextlib.contextmanager
def _model_stub_registration(monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    """
    ``sandbox_model_stub``'s body, shared with ``sandbox_model_stub_module``
    (v0.20.0 T16): yields ``register(port)``, and restores the session layer
    at the end (``monkeypatch`` restores the variable). The layer is rewritten
    IN PLACE, so the tests that use either run serially (they do: the suite
    has no parallel workers).
    """
    _, layer = session_sandbox()
    original = layer.read_bytes()

    def register(port: int, api_key: Optional[str] = None) -> str:
        # ``api_key``: the key the children use (v0.20.0 T16 fix round 1). A
        # child has NONE unless the sandbox layer names one, so it never
        # reads the repository's key files; a test that needs a key names a
        # sentinel (or a ``${env:...}`` chain to one) here.
        url = f"http://127.0.0.1:{int(port)}/v1"
        data = yaml.safe_load(original.decode("utf-8")) or {}
        data.setdefault("llm", {})["base_url"] = url
        if api_key is not None:
            data["llm"]["api_key"] = api_key
        layer.write_text(yaml.safe_dump(data, sort_keys=True), encoding="utf-8")
        monkeypatch.setenv(_STUB_PORT_ENV, str(int(port)))
        return url

    try:
        yield register
    finally:
        layer.write_bytes(original)


@pytest.fixture(scope="module")
def sandbox_model_stub_module() -> Iterator[Any]:
    """
    ``sandbox_model_stub`` for a whole test FILE (v0.20.0 T16): a module's
    shared hosted instance -- its supervisor, and every worker it restarts --
    reads the session layer at each start and each config re-read, so the
    registration lasts as long as the instance. Restored at the module's end.
    """
    with pytest.MonkeyPatch.context() as monkeypatch:
        with _model_stub_registration(monkeypatch) as register:
            yield register


def sandbox_marker(pid: int, layer: Path) -> str:
    """``CLOCKWORK_TEST_SANDBOX``'s value: the suite's pid, ``os.pathsep``, the layer."""
    return f"{pid}{os.pathsep}{layer}"


def session_sandbox() -> tuple[Path, Path]:
    """
    This session's sandbox ``(root, layer)``, read back from the marker
    ``pytest_configure`` put in ``os.environ`` (so either import of this file
    answers the same).
    """
    raw = os.environ.get(_SANDBOX_ENV, "")
    _, _, layer = raw.partition(os.pathsep)
    assert layer, f"{_SANDBOX_ENV} is not set: pytest_configure did not run"
    return Path(layer).parent, Path(layer)


def sandbox_env(env: Optional[Mapping[Any, Any]], layer: Path, marker: str) -> dict[Any, Any]:
    """
    The environment a child is started with: ``env`` (or, when None, a copy
    of this process's ``os.environ``) plus ``CLOCKWORK_TEST_SANDBOX=<marker>``
    and a ``CLOCKWORK_CONFIG`` ending in ``layer``.

    A ``CLOCKWORK_CONFIG`` the caller set is KEPT: its files come first and
    the sandbox layer last (spec §2.1, the last file wins), so a test can turn
    hosting on in a child and the sandbox still wins on every key it sets. A
    copy of the layer already in the caller's list (a child's environment
    handed on to its own child) is not repeated. A caller's env with BYTES
    keys (POSIX ``os.environb`` style) keeps bytes keys and values.
    """
    out = dict(os.environ if env is None else env)
    as_bytes = any(isinstance(key, bytes) for key in out)
    config_key: Any = os.fsencode(_CONFIG_ENV) if as_bytes else _CONFIG_ENV
    sandbox_key: Any = os.fsencode(_SANDBOX_ENV) if as_bytes else _SANDBOX_ENV
    current = out.get(config_key, "") or ""
    if isinstance(current, bytes):
        current = os.fsdecode(current)
    mine = os.path.normcase(os.path.abspath(str(layer)))
    theirs = [
        part
        for part in str(current).split(os.pathsep)
        if part.strip() and os.path.normcase(os.path.abspath(part.strip())) != mine
    ]
    joined = os.pathsep.join(theirs + [str(layer)])
    out[config_key] = os.fsencode(joined) if as_bytes else joined
    out[sandbox_key] = os.fsencode(marker) if as_bytes else marker
    return out


def _stack_service_names() -> set[str]:
    """Every service ``stack.services`` names, in the shipped and the owner's config."""
    names: set[str] = set()
    default = yaml.safe_load((_REPO_ROOT / "config" / "default.yaml").read_text(encoding="utf-8"))
    for tree in (default, _owner_config_tree()):
        stack = tree.get("stack") if isinstance(tree, dict) else None
        services = stack.get("services") if isinstance(stack, dict) else None
        if isinstance(services, dict):
            names |= {str(name) for name in services}
    return names


def _owner_config_tree() -> dict[str, Any]:
    try:
        from engine.config import get_config

        return get_config().as_dict()
    except Exception:  # noqa: BLE001 -- the shipped names still cover the stack
        return {}


#: The ``Popen.__init__`` the wrapper wraps, read when pytest imports this
#: file (before ``pytest_configure``). The wrapper also carries it as
#: ``__wrapped__``, which is how a test reaches past it: a second import of
#: this file (``from tests.conftest import``) comes after the patch.
_REAL_POPEN_INIT = getattr(subprocess.Popen.__init__, "__wrapped__", subprocess.Popen.__init__)


@pytest.hookimpl(trylast=True)
def pytest_configure(config: pytest.Config) -> None:
    """
    Every child process the suite starts runs under the sandbox layer.
    Installed here, before collection, so nothing the suite starts precedes
    it (T5 fix round 1: it was a session fixture, set up at the first test).

    WHY THIS EXISTS. Every guard below this one is a monkeypatch, and a
    monkeypatch cannot cross a process boundary: a test that ran a script
    through ``subprocess.run`` (``test_simulate_thief.py``, ``test_imports.py``)
    started a process with none of them, which read the owner's
    ``config/local.yaml``, could dial the owner's model server and write the
    owner's LM Studio ``mcp.json`` (v0.19.0 carried item 4, survey finding 5).
    An environment variable does cross it.

    TWO LINES, THE SECOND FAIL-CLOSED (T5 fix round 1, review finding 1).

    1. THE MARKER. ``CLOCKWORK_TEST_SANDBOX=<this pid>;<the layer>`` is
       written into THIS process's ``os.environ``, so every child inherits it
       however it is started -- ``subprocess``, ``os.system``,
       ``multiprocessing`` spawn, a test that re-patched ``Popen``. It is
       inert here: the engine reads it only in a process whose pid differs
       (``engine.config.child_sandbox``), where it means "a child of the test
       suite": ``get_config`` never reads ``config/local.yaml``, merges the
       sandbox layer last and forces ``llm.base_url`` to the discard port;
       ``skills_server``'s writers refuse anything outside the sandbox root;
       the Settings panel neither reads nor writes ``local.yaml``. Only the
       suite's own pid is exempt, so both goldens are untouched.
    2. THE WRAPPER. ``subprocess.Popen.__init__`` -- which ``run``, ``call``,
       ``check_output`` and asyncio's subprocesses go through -- also puts
       the marker back into an ``env=`` a caller scrubbed, and ends the
       child's ``CLOCKWORK_CONFIG`` with the layer (``sandbox_env``; spec
       §3.5), keeping the caller's own files first.

    ``CLOCKWORK_CONFIG`` IS NOT EXPORTED IN THIS PROCESS: it outranks
    ``config/local.yaml``, and set here it would rewrite the config every
    in-process test reads, and both goldens (the v0.19.0 request fixtures,
    scenario 23's URL, the doctor baselines, the local-mode golden) with it.
    ``tests/test_subprocess_sandbox.py`` pins that, and starts children by
    every route above.
    """
    factory = getattr(config, "_tmp_path_factory", None)
    if factory is None:  # pragma: no cover -- the tmp_path plugin is always on
        factory = pytest.TempPathFactory.from_config(config, _ispytest=True)
    root = Path(factory.getbasetemp()).resolve()
    (root / "lm-studio").mkdir(parents=True, exist_ok=True)
    (root / "data").mkdir(parents=True, exist_ok=True)
    layer = root / SANDBOX_LAYER_NAME
    layer.write_text(
        yaml.safe_dump(sandbox_layer(root, _stack_service_names()), sort_keys=True),
        encoding="utf-8",
    )
    # The pid-only marker set at import is upgraded to name the layer, and
    # CAPTURED: the wrapper hands every child this value whatever os.environ
    # or the call's env= says at spawn time (T5 re-review, N1: a test's
    # delenv or patch.dict(clear=True) left the child an empty marker).
    marker = sandbox_marker(os.getpid(), layer)
    os.environ[_SANDBOX_ENV] = marker

    signature = inspect.signature(_REAL_POPEN_INIT)

    def sandboxed_init(self: Any, *args: Any, **kwargs: Any) -> None:
        bound = signature.bind(self, *args, **kwargs)
        env = sandbox_env(bound.arguments.get("env"), layer, marker)
        # A stub model port reaches a child only if THIS process registered
        # it now (sandbox_model_stub); one in a caller's env= is dropped.
        _pass_stub_port(env)
        bound.arguments["env"] = env
        _REAL_POPEN_INIT(*bound.args, **bound.kwargs)

    sandboxed_init.__wrapped__ = _REAL_POPEN_INIT  # type: ignore[attr-defined]
    patch = pytest.MonkeyPatch()
    patch.setattr(subprocess.Popen, "__init__", sandboxed_init)
    config._clockwork_sandbox_patch = patch  # type: ignore[attr-defined]


def pytest_unconfigure(config: pytest.Config) -> None:
    patch = getattr(config, "_clockwork_sandbox_patch", None)
    if patch is not None:
        patch.undo()


# -- the owner's real storage, across processes (v0.20.0 T5, controller N3) ---

#: ``(directory, name prefix)``: every entry under the directory (recursively)
#: when the prefix is None, else only its direct entries whose names start so.
SnapshotRoot = tuple[Path, Optional[str]]

#: A snapshot: path -> (size, mtime_ns, sha256 or ""); a directory is
#: (-1, 0, ""). The hash is taken only for a prefix root's entries -- the
#: owner's small, high-value files (``mcp.json*``, ``local.yaml``) -- so a
#: restore that keeps size and mtime (``copy2``, ``os.utime``) still shows.
Snapshot = dict[str, tuple[int, int, str]]


def _digest(path: str) -> str:
    import hashlib

    try:
        with open(path, "rb") as handle:
            return hashlib.sha256(handle.read()).hexdigest()
    except OSError:
        return ""


def storage_snapshot(roots: Iterable[SnapshotRoot]) -> Snapshot:
    """
    Names, sizes and mtimes of every entry under ``roots`` (a missing root is
    empty), and a content hash of each entry a prefix root matches. Cheap
    enough to take twice a session over the owner's thousands of saves, and
    blind to HOW a write happened -- which is the point.

    IT PROVES "NET UNCHANGED", NOT "NEVER TOUCHED": a file created and removed
    within the session, or an empty directory made and removed, leaves no
    trace. The audit hook (``_saves_audit_hook``) is the in-process "never
    touched" check; the child-process sandbox is what keeps children off.
    """
    out: Snapshot = {}

    def record(path: str, hashed: bool) -> None:
        try:
            st = os.lstat(path)
        except OSError:
            return
        is_dir = os.path.isdir(path) and not os.path.islink(path)
        key = os.path.normcase(os.path.abspath(path))
        if is_dir:
            out[key] = (-1, 0, "")
        else:
            out[key] = (st.st_size, st.st_mtime_ns, _digest(path) if hashed else "")

    for directory, prefix in roots:
        base = str(directory)
        if not os.path.isdir(base):
            continue
        if prefix is not None:
            try:
                names = os.listdir(base)
            except OSError:
                continue
            for name in names:
                if name.startswith(prefix):
                    record(os.path.join(base, name), True)
            continue
        record(base, False)
        for current, dirs, files in os.walk(base):
            for name in dirs + files:
                record(os.path.join(current, name), False)
    return out


def _describe(entry: tuple[int, int, str]) -> str:
    size, mtime, digest = entry
    if size < 0:
        return "directory"
    return f"{size} bytes, mtime_ns {mtime}" + (f", sha256 {digest[:12]}" if digest else "")


def snapshot_changes(before: Snapshot, after: Snapshot) -> list[str]:
    """
    Every path added, removed or changed between two snapshots, sorted, each
    with its size and mtime before and after, so the owner can judge it.
    """
    changed = []
    for path in sorted(set(before) | set(after)):
        if path not in before:
            changed.append(f"added {path} ({_describe(after[path])})")
        elif path not in after:
            changed.append(f"removed {path} (was {_describe(before[path])})")
        elif before[path] != after[path]:
            changed.append(
                f"changed {path} (was {_describe(before[path])}; now {_describe(after[path])})"
            )
    return changed


def _real_storage_roots() -> list[SnapshotRoot]:
    """
    The owner's real run-time folders: under the real storage root (and one
    the owner's shell exported) ``saves/``, ``users/``, ``hosting/`` and
    ``media/`` (whose ``tts/`` is the audio); the real local save base, which
    the legacy ``paths.saves`` alias can put elsewhere; every ``mcp.json*``
    beside the owner's LM Studio ``mcp.json`` (the file, and its backups),
    under the home directory as it is NOW and the owner's declared
    ``llm.mcp.mcp_json``; and ``config/local.yaml`` (and its ``.tmp``).
    """
    roots: list[SnapshotRoot] = [(_REAL_SAVES_DIR, None)]
    data_roots = [_REAL_DATA_ROOT] + ([_EXPORTED_DATA_ROOT] if _EXPORTED_DATA_ROOT else [])
    for data_root in data_roots:
        roots += [(data_root / name, None) for name in ("saves", "users", "hosting", "media")]
    home = Path.home()
    lm_studio = {home / ".cache" / "lm-studio", home / ".lmstudio"}
    if _REAL_MCP_JSON_DIR is not None:
        lm_studio.add(_REAL_MCP_JSON_DIR)
    roots += [(directory, "mcp.json") for directory in sorted(lm_studio)]
    roots.append((_REAL_CONFIG_DIR, "local.yaml"))
    return roots


def assert_storage_unchanged(before: Snapshot, roots: list[SnapshotRoot]) -> None:
    """
    Raise when ``roots`` differ from ``before``, naming every change with its
    size and mtime before and after.

    Two false alarms it cannot tell from the suite: the owner's own game
    writing (an autosave, a generated plate) and LM Studio itself rewriting
    its ``mcp.json`` (the owner editing its servers) while the suite runs.
    """
    changes = snapshot_changes(before, storage_snapshot(roots))
    assert not changes, (
        f"the suite changed the owner's real storage, config/local.yaml or LM "
        f"Studio files ({len(changes)}): {changes[:10]}. If the owner's own "
        "game was saving, or LM Studio rewrote its mcp.json, while the suite "
        "ran, that is a false alarm; the sizes and mtimes above tell which."
    )


#: The roots and their snapshot, taken at conftest IMPORT -- before
#: collection -- by whichever copy of this file loads first (kept on ``sys``
#: for the reason ``_SHARED_KEY`` is).
_SNAPSHOT_KEY = "_clockwork_dark_storage_before"
if getattr(sys, _SNAPSHOT_KEY, None) is None:
    _roots_now = _real_storage_roots()
    setattr(sys, _SNAPSHOT_KEY, (_roots_now, storage_snapshot(_roots_now)))


@pytest.fixture(scope="session", autouse=True)
def _real_storage_is_untouched() -> Iterator[list[SnapshotRoot]]:
    """
    The owner's real saves, accounts, hosting files, media, ``config/local.yaml``
    and LM Studio ``mcp.json`` are byte-for-byte where they were when the
    session began (the snapshot taken at conftest import).

    WHY, BESIDE THE AUDIT HOOK. ``_saves_audit_hook`` sees only THIS process,
    and only ``open``/``mkdir``/``rename``/``remove``: not sqlite, not
    ``os.link``/``symlink``/``truncate``, not a child process, and not the
    real ``media/`` folder (controller note N3, v0.20.0 T5). A snapshot of
    names, sizes and mtimes (and hashes of the small owner files), compared
    at session end, catches every one of those that leaves a net change,
    whatever wrote it. It is reported as an error on the session's last test.
    """
    roots, before = getattr(sys, _SNAPSHOT_KEY)
    yield roots
    assert_storage_unchanged(before, roots)


@pytest.fixture(autouse=True)
def _no_test_writes_real_saves(
    tmp_path_factory: pytest.TempPathFactory,
    request: pytest.FixtureRequest,
) -> Iterator[None]:
    """
    Every test's saves go to a temp directory, never the owner's ``data/saves``.

    WHY THIS EXISTS. Saves are an engine output (the storage root's
    ``saves/``), so no story overlay moves them, and every test that built a session through
    ``SessionStore().create`` (or played a turn, which autosaves) wrote a real
    run into the owner's load menu -- a pile of tens of thousands, found in
    v0.15. A handful of tests redirected their own store; the rest never
    thought to. Now the one function every namespaced root is built from,
    ``saves.saves_base``, answers a per-test temp directory, and the cached
    process-wide store is dropped on the way in and out, so a
    ``get_save_store()``, a ``saves_root()`` and a store a test patches in for
    itself all land somewhere disposable. A test that builds a
    ``SaveStore(root=...)`` of its own (the legacy-migration tests) is
    untouched: it already named its directory.

    HOW A BREACH IS SEEN, WITHOUT SCANNING THE TREE. The first version
    snapshotted every file under the real directory before and after each
    test: O(saves) twice per test, cheap only while the folder was empty (the
    owner's had ~6k), and wrong whenever the owner's own game autosaved while
    the suite ran. Now two O(1) checks, both about THIS process only:

      * an audit hook (``_saves_audit_hook``, ``sys.addaudithook``) records
        every write-mode ``open``, ``mkdir``, ``rename``/``replace`` and
        ``remove`` this process aims under the real directory -- whatever
        route reached it, ``write_json_atomic`` or a bare ``write_text``;
      * the redirect is still in force at teardown: ``saves_base`` and the
        cached store's root are not under the real directory.

    Asserted at teardown, for ``_no_live_model_calls``' reason: a save failure
    is logged and forgiven (``SessionStore.create``), so the only honest check
    is one nothing in the test body can catch.

    ITS OWN MonkeyPatch, not the test's ``monkeypatch`` fixture. A test that
    calls ``monkeypatch.undo()`` mid-body (``test_forced_and_repeatable_decks``
    does, to drop a spy) would otherwise undo the redirect with it, and every
    save for the rest of that test would land in the owner's folder -- found
    by the teardown check below the first time it ran.

    THE STORAGE ROOT TOO (v0.20.0 T3 fix round 1). An account's saves
    (``save_store_for(owner, ...)``), hosted mode's files and generated media
    are built on ``storage.data_root()``, not on ``saves_base``, so the
    redirect above never reached them. ``CLOCKWORK_DATA_DIR`` is set to a
    per-test temp directory as well, and the audit hook watches the REAL
    root's ``saves/``, ``users/`` and ``hosting/``. A test that pins the
    DEFAULT root (the local-mode golden's ``save_base.json``) opts out of the
    variable with ``@pytest.mark.default_storage_root``; the hook still
    watches it.
    """
    from engine.persistence import saves

    real = _real_saves_dir()
    base = tmp_path_factory.mktemp("saves")
    redirect = pytest.MonkeyPatch()
    redirect.setattr(saves, "saves_base", lambda: base)
    if request.node.get_closest_marker("default_storage_root") is None:
        redirect.setenv(_DATA_DIR_ENV, str(tmp_path_factory.mktemp("data")))
    else:
        redirect.delenv(_DATA_DIR_ENV, raising=False)
    saves.reset_save_store()
    REAL_SAVES_WRITES.clear()
    roots: list[Path] = []
    try:
        yield
        roots = [saves.saves_base()] + [
            store.root for store in saves.cached_save_stores()
        ]
        # Only the stores the test BUILT are checked here (an account's
        # included), not where the root resolves now: the test's own
        # `monkeypatch` (which another autouse fixture may have set up before
        # this one) can still hold a `delenv` of the variable at this point.
        # The audit hook is the guard for the root itself.
    finally:
        saves.reset_save_store()
        redirect.undo()
        breaches = list(REAL_SAVES_WRITES)
        REAL_SAVES_WRITES.clear()
    assert not breaches, (
        f"this test wrote into the real save directory {real} (or the real "
        f"storage root's users/ or hosting/, or the owner's config/local.yaml): "
        f"{breaches[:5]}"
    )
    escaped = [str(r) for r in roots if _under_real_saves(r)]
    assert not escaped, (
        f"the save redirect was not in force at teardown; saves resolve to {escaped}"
    )


@pytest.fixture(autouse=True)
def _no_live_model_calls(request: Any) -> Iterator[None]:
    """
    Fail any test that opens a real connection to the model server.

    WHY THIS EXISTS. ``tests/test_turn_intent_per_game.py`` stubbed
    ``session.storyteller.llm_fn`` and believed it was hermetic. It was not:
    ``run_turn`` called ``run_pipeline`` with no ``llm_fn``, so every
    multi-agent story's plan calls went to LM Studio for real. Nothing failed
    -- the pipeline is deliberately forgiving of a model outage -- so the only
    symptom was the clock: **69% of the entire suite's wall time**, 171s for one
    NEON CITY test against 8.4s for the same test on the flagship. Measured
    before the fix; the file now runs in 53s total.

    Slowness was the mild symptom. The real ones were that the suite needed LM
    Studio up to run at full speed, and that a live model's plans vary between
    runs, so those assertions were quietly non-deterministic.

    A test that genuinely wants the model marks itself ``@pytest.mark.live``.
    Everything else gets an error naming the address, which is the difference
    between finding this in a second and finding it in an afternoon of reading
    duration tables.

    DEFAULT-DENY (v0.20.0 T8 fix round 1). The suite may talk to itself --
    loopback (``localhost``, ``127.0.0.0/8``, ``::1``, the unspecified
    address, which can only mean this machine) and AF_UNIX -- and to nothing
    else: a name or address off this machine is refused when it is RESOLVED
    (``getaddrinfo``, ``gethostbyname``, ``gethostbyname_ex``,
    ``gethostbyaddr``) or connected to (``connect``, ``connect_ex``), so not
    even a DNS lookup leaves. It was model-server-only until a test with a
    fake STT host in its config made a real lookup for it. On loopback the
    model server's own ports stay refused, bar the one port a test
    registered with ``sandbox_model_stub``.

    ITS LIMITS (T8 fix round 2). It guards the Python-level resolvers and
    ``connect``/``connect_ex``. It does NOT refuse a UDP ``sendto`` or
    ``sendmsg`` to an address off this machine, nor a call a C extension
    makes on ``_socket`` (or the OS) directly; nothing in the suite does
    either today. Child processes are not covered by it at all: they run
    under T5's sandbox config (the discard port), not this guard.

    WHY THE VIOLATION IS RECORDED AND RE-RAISED AT TEARDOWN. The first version
    of this guard only raised at the call site, and it did not work: the
    pipeline runs its plans in a thread pool and swallows agent-side failures on
    purpose, so the refusal was caught, the plans came back silent, and the test
    passed in 1.5s looking perfectly healthy. The guard was defeated by exactly
    the forgiveness that hid the original bug. So the breach is also recorded in
    a list this fixture asserts on AFTER the test body, where nothing is left to
    catch it.

    ITS OWN MonkeyPatch, for ``_no_test_writes_real_saves``' reason. Installed
    through the test's ``monkeypatch``, the socket guard and the three pins
    below went with a mid-test ``monkeypatch.undo()``
    (``test_forced_and_repeatable_decks`` does one to drop a spy), and the
    rest of that test could reach the model unwatched. A test's own later
    patch of ``_fetch`` or ``is_available`` still wins, and is undone before
    this guard is, since the ``monkeypatch`` fixture is set up after it.
    """
    if request.node.get_closest_marker("live"):
        yield
        return

    guard = pytest.MonkeyPatch()
    # Model DISCOVERY is pinned before the socket guard goes up, because it is
    # not a leak to be caught -- it is a legitimate dependency to be made
    # deterministic. Sizing a prompt needs the model's context window, so
    # `build_storyteller_messages` -> `default_budget` -> `resolve_profile`
    # queries the registry on the way to building a turn, BEFORE the injected
    # `llm_fn` short-circuit is ever reached. That call is real, and it means a
    # test budgets differently depending on whether LM Studio happens to be
    # running -- which is the same non-determinism the socket guard exists to
    # remove, arriving through a door the guard cannot tell apart from a bug.
    #
    # Answering with an empty model list (`_empty_model_list`, the provider's
    # shape) puts every test on the engine's own no-models-available path,
    # which it already handles (it logs and carries on). A test that wants real discovery patches `_fetch` itself, and its
    # patch wins because it is applied later.
    # ...unless the test is ABOUT discovery. `test_lmstudio_health.py` mocks
    # `httpx` and asserts on what the registry does with the answer, and this
    # pin sits above that layer -- it would replace the very code under test.
    # Such a file marks itself `real_discovery`; the socket guard still applies
    # to it, so its mocks are still required to be complete.
    if not request.node.get_closest_marker("real_discovery"):
        try:
            from engine.llm.registry import ModelRegistry

            # `body` is Ollama's POST /api/show; no show is asked of an empty list.
            guard.setattr(
                ModelRegistry,
                "_fetch",
                lambda self, path, body=None: _empty_model_list(),
                raising=True,
            )
        except Exception as exc:  # noqa: BLE001 -- never block collection on this
            print(f"[conftest] could not pin model discovery: {exc}")

    # The native-transport probe is a THIRD unmocked door. `native_available()`
    # asks `/api/v1/chat` whether the route exists, and it does so through
    # `NativeClient._client.post` -- an httpx.Client INSTANCE method, which a
    # `monkeypatch.setattr(httpx, "post", ...)` does not touch. That is why
    # `test_lmstudio_health.py` reached the network despite opening with
    # "Everything here is mocked": its mocks were complete for the layer it
    # knew about.
    #
    # Answering False is the deterministic choice, and it is the answer a
    # machine with no LM Studio gets. A test that needs the native route
    # available patches this itself and wins, being applied later.
    try:
        from engine.llm.lmstudio_native import NativeClient

        guard.setattr(NativeClient, "is_available", lambda self: False)
    except Exception as exc:  # noqa: BLE001
        print(f"[conftest] could not pin the native probe: {exc}")
    # Ollama's probe (`/api/version`) is the same kind of door, through its
    # own `httpx.Client` instance, and is pinned the same way (v0.19.0 T5;
    # canary: tests/test_conftest_guard.py).
    try:
        from engine.llm.ollama import OllamaClient

        guard.setattr(OllamaClient, "is_available", lambda self: False)
    except Exception as exc:  # noqa: BLE001
        print(f"[conftest] could not pin the Ollama probe: {exc}")

    # The summarizer is its own model call on the "small" profile, fired when
    # the ledger evicts a turn -- so any test that runs enough turns reaches
    # LM Studio no matter how carefully it wired its agents.
    # ``summarize(llm_fn=None)`` already falls back to deterministic
    # compression, which is both hermetic and repeatable.
    #
    # `test_vertical_slice.py` has patched exactly this for its own 40-turn
    # playtest since it was written, with the note "a playtest must not depend
    # on a local model being up". It was right, and it was the only file that
    # did it. Promoting it here is the difference between one author
    # remembering and the suite guaranteeing.
    try:
        from engine.scenes import default_state as _default_state

        guard.setattr(_default_state, "_summarizer_fn", lambda: None)
    except Exception as exc:  # noqa: BLE001
        print(f"[conftest] could not pin the summarizer: {exc}")

    real_connect_ex = socket.socket.connect_ex
    breaches: list[str] = []
    global _BREACHES
    _BREACHES = breaches

    def refuse(host: Any, port: Any, how: str) -> None:
        name = str(host).lower()
        try:
            number = int(port)
        except (TypeError, ValueError):
            number = -1
        # Asked now, not at import: see `_model_endpoints`. The one model
        # endpoint a test may dial is the loopback stub it registered with
        # `sandbox_model_stub`.
        if (name, number) in _model_endpoints() and not _is_registered_stub(name, number):
            breaches.append(f"{name}:{number}")
            raise AssertionError(
                f"{request.node.nodeid} {how} the model server at {name}:{number}."
            )
        # DEFAULT-DENY (v0.20.0 T8 fix round 1): nothing but this machine's
        # own loopback. A fake STT host in a test's config was resolved for
        # real (a DNS lookup leaving the machine) because only the model
        # server's addresses were refused.
        if not _is_loopback(name):
            breaches.append(f"{name}:{number}")
            raise AssertionError(
                f"{request.node.nodeid} {how} {name}:{number}, which is not loopback. "
                "Tests reach nothing off this machine: stub the client."
            )

    # BY NAME, BEFORE RESOLUTION. `socket.create_connection` -- which httpx's
    # transport calls -- resolves the host first, so `connect` below only ever
    # sees an IP address. A hosted `https://models.example/v1` is guarded as
    # ("models.example", 443), and that tuple can only match here: checked at
    # `connect` alone, the name was dead weight in the set and the server was
    # reachable (v0.19.0 T2 review, finding 1).
    def guarded_resolve(host: Any, port: Any, *args: Any, **kwargs: Any) -> Any:
        if isinstance(host, (str, bytes)):
            text = host.decode("ascii", "replace") if isinstance(host, bytes) else host
            refuse(text, port, "resolved the address of")
        return _REAL_GETADDRINFO(host, port, *args, **kwargs)

    # And by address, for a literal IP that needs no resolving.
    def guarded(self: Any, address: Any) -> Any:
        # AF_UNIX addresses are plain strings and never leave the machine;
        # anything without a (host, port) shape is none of our business.
        if isinstance(address, tuple) and len(address) >= 2:
            refuse(address[0], address[1], "opened a real connection to")
        return _REAL_CONNECT(self, address)

    def guarded_ex(self: Any, address: Any) -> Any:
        if isinstance(address, tuple) and len(address) >= 2:
            refuse(address[0], address[1], "opened a real connection to")
        return real_connect_ex(self, address)

    # The older resolvers, which getaddrinfo's guard does not see.
    real_by_name_ex = socket.gethostbyname_ex
    real_by_addr = socket.gethostbyaddr

    def guarded_by_name(host: Any) -> Any:
        refuse(host, 0, "resolved the address of")
        return _REAL_GETHOSTBYNAME(host)

    def guarded_by_name_ex(host: Any) -> Any:
        refuse(host, 0, "resolved the address of")
        return real_by_name_ex(host)

    def guarded_by_addr(host: Any) -> Any:
        refuse(host, 0, "looked up the name of")
        return real_by_addr(host)

    guard.setattr(socket, "getaddrinfo", guarded_resolve)
    guard.setattr(socket, "gethostbyname", guarded_by_name)
    guard.setattr(socket, "gethostbyname_ex", guarded_by_name_ex)
    guard.setattr(socket, "gethostbyaddr", guarded_by_addr)
    guard.setattr(socket.socket, "connect", guarded)
    guard.setattr(socket.socket, "connect_ex", guarded_ex)
    try:
        yield
    finally:
        guard.undo()
        _BREACHES = []
    assert not breaches, (
        f"{request.node.nodeid} tried to reach the real model server or a host "
        f"off this machine ({', '.join(sorted(set(breaches)))}). Tests must inject their own "
        "model -- `run_turn` passes `session.storyteller.llm_fn` through to "
        "`run_pipeline`, so setting it on the session covers every agent. "
        "Mark the test @pytest.mark.live if it genuinely needs the server "
        "running."
    )


@pytest.fixture(autouse=True)
def _no_real_grok_cli(request: Any, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """
    Fail any test that would launch the real Grok Build CLI.

    WHY THIS EXISTS. ``_no_live_model_calls`` above guards SOCKETS to the model
    server. The Grok image provider (``engine/media/providers/grokbuild.py``)
    reaches no socket of ours: it shells out to the CLI with
    ``subprocess.run``, and the CLI does its own networking and auth. So a test
    that forgot to stub it would launch a two-to-three-minute generation
    against the owner's account -- and, where no ``grok`` is installed, would
    pass quietly on the provider's "failed" result instead. v0.13.0 made
    ``scripts/generate_art.py`` drive that provider for any story, which is
    when the gap started to matter.

    The module's ``subprocess`` is swapped for a shim whose ``run`` refuses.
    Everything in that module that calls ``subprocess`` is the CLI, so nothing
    else is caught. A test that stubs the CLI patches ``run`` on the shim, and
    its patch wins, being applied later.

    Recorded AND raised, for the reason the socket guard gives: the media
    worker runs generation on a thread pool that forgives a raise. The record
    lives on ``request.node.grok_cli_calls`` so the canary
    (``tests/test_generate_art_cli.py::test_the_conftest_guard_catches_a_real_cli_call``)
    can check it and clear it. ``@pytest.mark.live`` opts out.
    """
    if request.node.get_closest_marker("live"):
        yield
        return

    import subprocess
    import types

    from engine.media.providers import grokbuild

    calls: list[str] = []
    request.node.grok_cli_calls = calls

    def refuse(argv: Any, *args: Any, **kwargs: Any) -> Any:
        command = str(argv[0]) if isinstance(argv, (list, tuple)) and argv else str(argv)
        calls.append(command)
        raise AssertionError(
            f"{request.node.nodeid} tried to launch the real Grok CLI ({command}). "
            "Stub `grokbuild.subprocess.run`, or mark the test @pytest.mark.live."
        )

    shim = types.SimpleNamespace(
        run=refuse,
        TimeoutExpired=subprocess.TimeoutExpired,
        CompletedProcess=subprocess.CompletedProcess,
    )
    monkeypatch.setattr(grokbuild, "subprocess", shim)
    yield
    assert not calls, (
        f"{request.node.nodeid} tried to launch the real Grok CLI "
        f"({', '.join(sorted(set(calls)))}). Tests must stub the provider."
    )


def _inside(path: Any, root: Path) -> bool:
    """Whether ``path`` resolves under ``root``."""
    try:
        Path(path).resolve().relative_to(root)
    except (ValueError, OSError):
        return False
    return True


@pytest.fixture(autouse=True)
def _no_owner_lm_studio_files(
    request: Any, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[None]:
    """
    Keep every test off the owner's LM Studio ``mcp.json``, and off a real
    skills server.

    WHY THIS EXISTS. ``engine/mcp/skills_server.py`` edits LM Studio's own
    ``mcp.json`` in place (``register_session``, ``unregister_sessions``, and
    ``SkillsServer.start``'s prune of stale entries), taking a ``.bak-*``
    beside it first. ``mcp_json_path`` finds that file under the owner's home.
    Nothing in the suite redirected it: a test was safe only if it passed its
    own ``path`` or stubbed the server. In v0.19.0 T6 a canary that forced
    Phase A on started a real server, which registered a session in the
    owner's real ``mcp.json`` and left backups beside it -- the file is not
    ours, and it holds the owner's other MCP servers and their credentials.

    Three things, for every test:

    * ``mcp_json_path`` answers a path in this test's own temp directory
      (a ``llm.mcp.mcp_json`` already under the temp root is kept);
    * the two writers, ``backup_once`` and ``_write_json_atomic``, refuse any
      target outside the temp root -- recorded AND raised (as an ``OSError``,
      which the registration code turns into "tool calling is off"), because
      Phase A forgives a raise on purpose, so the record is asserted at
      teardown, where nothing is left to catch it (``_no_live_model_calls``'
      reason);
    * ``SkillsServer.start`` refuses -- recorded, and answering False, its own
      "could not start" -- unless the test is marked
      ``@pytest.mark.mcp_server``. A marked test's server still registers
      only into the temp directory.

    The record lives on ``request.node.lm_studio_breaches`` so the canary
    (``tests/test_conftest_guard.py``) can take back the one it provokes. The
    skills-server singleton and the MCP gate's once-per-process ERROR flag are
    reset at teardown, so no test inherits another's.
    """
    from engine.agents import mechanics
    from engine.mcp import skills_server

    root = Path(tmp_path_factory.getbasetemp()).resolve()
    breaches: list[str] = []
    request.node.lm_studio_breaches = breaches
    sandbox: list[Path] = []

    real_backup = skills_server.backup_once
    real_write = skills_server._write_json_atomic
    real_start = skills_server.SkillsServer.start
    # The unredirected lookup, for a test that checks the lookup itself under
    # a faked home inside tmp_path (tests/test_mcp_json_posix.py). It only
    # answers a path; the guarded writers below still refuse outside the root.
    request.node.real_mcp_json_path = skills_server.mcp_json_path

    def redirected() -> Optional[Path]:
        from engine.config import get_config

        declared = str(get_config().get("llm.mcp.mcp_json", "") or "")
        if declared and _inside(Path(declared).expanduser(), root):
            return Path(declared).expanduser()
        if not sandbox:
            sandbox.append(tmp_path_factory.mktemp("lm-studio") / "mcp.json")
        return sandbox[0]

    def refuse_outside(path: Any, what: str) -> None:
        if not _inside(path, root):
            breaches.append(f"{what} {path}")
            raise PermissionError(
                f"{request.node.nodeid} tried to {what} {path}, outside the test's "
                "temp directory: the owner's LM Studio files are not the suite's"
            )

    def guarded_backup(path: Path) -> Any:
        refuse_outside(path, "back up")
        return real_backup(path)

    def guarded_write(path: Path, document: Any) -> None:
        refuse_outside(path, "write")
        real_write(path, document)

    def guarded_start(self: Any, *args: Any, **kwargs: Any) -> bool:
        if not request.node.get_closest_marker("mcp_server"):
            breaches.append("start a skills server")
            return False
        return real_start(self, *args, **kwargs)

    guard = pytest.MonkeyPatch()
    guard.setattr(skills_server, "mcp_json_path", redirected)
    guard.setattr(skills_server, "backup_once", guarded_backup)
    guard.setattr(skills_server, "_write_json_atomic", guarded_write)
    guard.setattr(skills_server.SkillsServer, "start", guarded_start)
    try:
        yield
    finally:
        guard.undo()
        skills_server._server = None
        mechanics._mcp_refusal_logged = False
    assert not breaches, (
        f"{request.node.nodeid} reached for LM Studio's own files or a real "
        f"skills server ({'; '.join(breaches)}). Pass a tmp_path, or mark the "
        "test @pytest.mark.mcp_server if it must stand a server up."
    )


@pytest.fixture
def llm_server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    """
    Name a model server through the REAL config layers, for a request test.

    Yields ``configure(provider, **llm)``: it writes a temp ``local.yaml``
    whose ``llm:`` block names ``provider``, its default base URL (or a
    hosted one for a row with none), a fixed test key and ``llm``'s extra
    keys, and drops every config-derived LLM singleton (registry, profiles,
    backend, the compat client) so the next request is built from it.

    Nothing here opens a socket: the requests themselves are answered by
    ``tests/llm_wire.py``, and the guard stays up. The repo's own
    ``config/local.yaml`` is never read or written -- ``_CONFIG_DIR`` points
    at ``tmp_path``.
    """
    import engine.config as config
    from engine.llm.client import reset_lms_client

    root = Path(__file__).resolve().parents[1]
    directory = tmp_path / "llm_config"
    directory.mkdir()
    real = {name: getattr(config, name) for name in ("_CONFIG_DIR", "_DEFAULT_PATH", "_overlay")}
    for name in ("CLOCKWORK_ENV", "CLOCKWORK_LLM_API_KEY", "LMSTUDIO_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(config, "_CONFIG_DIR", directory)
    monkeypatch.setattr(config, "_DEFAULT_PATH", root / "config" / "default.yaml")
    monkeypatch.setattr(config, "_overlay", {})
    # Restored at teardown too, as a second line: see the `finally` below.
    monkeypatch.setattr(config, "_instance", None)

    def configure(provider: str, **llm: Any) -> None:
        from engine.llm.providers import PROVIDERS

        block: dict[str, Any] = {
            "provider": provider,
            "api_key": "shaping-test-key",
            "base_url": PROVIDERS[provider].default_base_url.value
            or "https://models.example/v1",
        }
        block.update(llm)
        (directory / "local.yaml").write_text(
            yaml.safe_dump({"llm": block}), encoding="utf-8"
        )
        config.reset_config()
        reset_lms_client()

    try:
        yield configure
    finally:
        # The REAL config is put back BEFORE the reset. `reset_config` runs
        # every cache reloader (locations, governance, lanes, ...), and each
        # reads the config: reset while `_CONFIG_DIR` still pointed here, they
        # were all rebuilt from this test's local.yaml, and the singleton with
        # them -- so the next test ran against this test's server.
        for name, value in real.items():
            setattr(config, name, value)
        config.reset_config()
        reset_lms_client()


@pytest.fixture
def game_state() -> GameState:
    """Fresh game state."""
    return GameState()


@pytest.fixture
def story_declaring_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[str]:
    """
    Activate a story on disk that declares no optional content paths at all.

    THE ABSENCE HAS TO BE BUILT, NOT BORROWED. Several tests assert that an
    undeclared ``paths.*`` key makes its system inert, and they used to read
    that claim off The Clockwork Dark because the flagship happened to declare
    no clocks, threads, endings, decks or epilogues. "The flagship declares
    none" and "an undeclared path is inert" are different statements -- only
    the second is about the engine -- and the difference stopped being
    academic the day the flagship shipped a finale: three tests failed that
    were never testing the flagship's content in the first place.

    An empty config overlay is NOT enough to build this. ``paths.*`` falls
    back to the ACTIVE MANIFEST when the config layers hold nothing
    (``engine/config.py::_story_path``), which is the whole point of the
    engine/story seam -- so the only way to have a story that declares nothing
    is to activate one.

    Yields the temp slug. ``games_root`` is redirected at the temp directory,
    so discovery finds this story and nothing else, and a leaked activation
    cannot reach the real ``games/``.
    """
    from engine.games import registry

    slug = "declares-nothing"
    directory = tmp_path / "games" / slug
    directory.mkdir(parents=True)
    manifest: dict[str, Any] = {
        "id": slug,
        "title": "A Story That Declares Nothing",
        # Not one optional content path. `lore_db` is an engine OUTPUT rather
        # than story content (checked on its parent, not for existence), so it
        # is the only key here, pointed into this test's temp directory. (It
        # was `saves`, which since v0.20.0 is no story key at all.)
        "paths": {"lore_db": str(tmp_path / "lore.db")},
        "entry": {"location_id": "nowhere", "archetypes": []},
    }
    directory.joinpath("game.yaml").write_text(
        yaml.safe_dump(manifest), encoding="utf-8"
    )
    monkeypatch.setattr(registry, "games_root", lambda: tmp_path / "games")
    registry.activate(slug)
    try:
        yield slug
    finally:
        # Back to "no story activated", which is the state a fresh process
        # starts in: `resolve_slug()` then answers from config as it always did.
        registry.deactivate()


@pytest.fixture
def engine(game_state: GameState) -> GameEngine:
    """Game engine with active context bound."""
    eng = GameEngine(game_state)
    set_active_engine(eng)
    return eng