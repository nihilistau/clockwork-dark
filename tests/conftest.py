"""Pytest fixtures."""

from __future__ import annotations

import os
import socket
import sys
from pathlib import Path
from typing import Any, Iterator, Optional

import pytest
import yaml

from engine.game.engine import GameEngine, set_active_engine
from engine.game.state import GameState


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


#: The resolver the live-call guard wraps. Read at call time, so the guard's own
#: tests can put a stub resolver UNDER the guard (``tests/test_conftest_guard.py``).
_REAL_GETADDRINFO = socket.getaddrinfo

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


#: The owner's real save directory, as the engine resolves ``paths.saves``
#: (a relative path is relative to the repository, where the game runs).
_REPO_ROOT = Path(__file__).resolve().parents[1]


def _real_saves_dir() -> Path:
    from engine.config import get_config

    base = Path(str(get_config().get("paths.saves", "data/saves") or "data/saves"))
    return base if base.is_absolute() else _REPO_ROOT / base


#: The real save directory as a normalized prefix, resolved once. The owner's
#: ``paths.saves`` does not move during a run.
_REAL_SAVES_PREFIX = os.path.normcase(os.path.abspath(_real_saves_dir())) + os.sep

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
    return full == _REAL_SAVES_PREFIX[:-1] or full.startswith(_REAL_SAVES_PREFIX)


def _saves_audit_hook(event: str, args: tuple[Any, ...]) -> None:
    """
    Record any attempt by this process to write under the real save directory.

    Runs on every audit event, so it rejects cheaply: event name first, then
    (for ``open``) whether the open is a write at all, and only then resolves
    a path. It must never raise -- an exception here would surface inside
    whatever unrelated call raised the event.
    """
    try:
        if event == "open":
            path, mode, flags = args
            if isinstance(mode, str):
                if not any(c in mode for c in "wax+"):
                    return
            elif not (int(flags or 0) & _WRITE_FLAGS):
                return
            if _under_real_saves(path):
                REAL_SAVES_WRITES.append((event, os.fspath(path)))
        elif event in _WRITE_EVENTS:
            paths = args[:2] if event == "os.rename" else args[:1]
            for path in paths:
                if _under_real_saves(path):
                    REAL_SAVES_WRITES.append((event, os.fspath(path)))
    except Exception:  # noqa: BLE001 -- see the docstring
        return


# Installed once per process, by whichever copy of this file loads first: an
# audit hook cannot be removed, and a second would double every entry.
if not _HOOK_INSTALLED:
    sys.addaudithook(_saves_audit_hook)


@pytest.fixture(autouse=True)
def _no_test_writes_real_saves(
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[None]:
    """
    Every test's saves go to a temp directory, never the owner's ``data/saves``.

    WHY THIS EXISTS. ``paths.saves`` is an engine output, so no story overlay
    moves it, and every test that built a session through
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
    """
    from engine.persistence import saves

    real = _real_saves_dir()
    base = tmp_path_factory.mktemp("saves")
    redirect = pytest.MonkeyPatch()
    redirect.setattr(saves, "saves_base", lambda: base)
    saves.reset_save_store()
    REAL_SAVES_WRITES.clear()
    roots: list[Path] = []
    try:
        yield
        store = saves._store
        roots = [saves.saves_base()] + ([store.root] if store is not None else [])
    finally:
        saves.reset_save_store()
        redirect.undo()
        breaches = list(REAL_SAVES_WRITES)
        REAL_SAVES_WRITES.clear()
    assert not breaches, (
        f"this test wrote into the real save directory {real}: {breaches[:5]}"
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

    Only the model server is blocked, not sockets in general: the suite has
    every right to talk to itself, and a blanket ban would be a different and
    much more annoying test.

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

    real_connect = socket.socket.connect
    breaches: list[str] = []
    global _BREACHES
    _BREACHES = breaches

    def refuse(host: Any, port: Any, how: str) -> None:
        name = str(host).lower()
        try:
            number = int(port)
        except (TypeError, ValueError):
            number = -1
        # Asked now, not at import: see `_model_endpoints`.
        if (name, number) in _model_endpoints():
            breaches.append(f"{name}:{number}")
            raise AssertionError(
                f"{request.node.nodeid} {how} the model server at {name}:{number}."
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
        # AF_UNIX addresses are plain strings and can never be the model
        # server; anything without a (host, port) shape is none of our business.
        if isinstance(address, tuple) and len(address) >= 2:
            refuse(address[0], address[1], "opened a real connection to")
        return real_connect(self, address)

    guard.setattr(socket, "getaddrinfo", guarded_resolve)
    guard.setattr(socket.socket, "connect", guarded)
    try:
        yield
    finally:
        guard.undo()
        _BREACHES = []
    assert not breaches, (
        f"{request.node.nodeid} tried to reach the real model server "
        f"({', '.join(sorted(set(breaches)))}). Tests must inject their own "
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
        # Not one optional content path. `saves` is an engine OUTPUT rather
        # than story content and every story shares it, so it is the only key
        # here -- and it is checked on its parent, not for existence.
        "paths": {"saves": "data/saves"},
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