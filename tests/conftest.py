"""Pytest fixtures."""

from __future__ import annotations

import socket
from pathlib import Path
from typing import Any, Iterator

import pytest
import yaml

from engine.game.engine import GameEngine, set_active_engine
from engine.game.state import GameState


def _model_endpoints() -> frozenset[tuple[str, int]]:
    """
    Every address that means "the model server", as ``(host, port)``.

    Read from the same config the engine dials, so moving the server moves the
    guard with it. All three loopback spellings are included because a client
    may resolve ``localhost`` to any of them and a guard that only knew one
    would be a guard with a hole in it.
    """
    from urllib.parse import urlparse

    from engine.config import get_config

    blocked: set[tuple[str, int]] = set()
    for key in ("lmstudio.base_url", "lmstudio.native_url", "stack.health_url"):
        try:
            raw = str(get_config().get(key) or "")
        except Exception:  # noqa: BLE001 -- a missing key must not break collection
            continue
        if not raw:
            continue
        parsed = urlparse(raw)
        port = parsed.port
        if port is None:
            continue
        host = (parsed.hostname or "").lower()
        hosts = {host}
        if host in {"localhost", "127.0.0.1", "::1"}:
            hosts |= {"localhost", "127.0.0.1", "::1"}
        blocked |= {(h, int(port)) for h in hosts if h}
    return frozenset(blocked)


#: Resolved once. Collection-time cost only, and the config is already loaded.
MODEL_ENDPOINTS = _model_endpoints()


@pytest.fixture(autouse=True)
def _no_live_model_calls(request: Any, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
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
    """
    if request.node.get_closest_marker("live") or not MODEL_ENDPOINTS:
        yield
        return

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
    # Answering with an empty v1 payload puts every test on the engine's own
    # no-models-available path, which it already handles (it logs and carries
    # on). A test that wants real discovery patches `_fetch` itself, and its
    # patch wins because it is applied later.
    # ...unless the test is ABOUT discovery. `test_lmstudio_health.py` mocks
    # `httpx` and asserts on what the registry does with the answer, and this
    # pin sits above that layer -- it would replace the very code under test.
    # Such a file marks itself `real_discovery`; the socket guard still applies
    # to it, so its mocks are still required to be complete.
    if not request.node.get_closest_marker("real_discovery"):
        try:
            from engine.lmstudio.registry import ModelRegistry

            monkeypatch.setattr(
                ModelRegistry, "_fetch", lambda self, path: {"models": []}, raising=True
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
        from engine.lmstudio.native import NativeClient

        monkeypatch.setattr(NativeClient, "is_available", lambda self: False)
    except Exception as exc:  # noqa: BLE001
        print(f"[conftest] could not pin the native probe: {exc}")

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

        monkeypatch.setattr(_default_state, "_summarizer_fn", lambda: None)
    except Exception as exc:  # noqa: BLE001
        print(f"[conftest] could not pin the summarizer: {exc}")

    real_connect = socket.socket.connect
    breaches: list[str] = []

    def guarded(self: Any, address: Any) -> Any:
        # AF_UNIX addresses are plain strings and can never be the model
        # server; anything without a (host, port) shape is none of our business.
        if isinstance(address, tuple) and len(address) >= 2:
            host = str(address[0]).lower()
            try:
                port = int(address[1])
            except (TypeError, ValueError):
                port = -1
            if (host, port) in MODEL_ENDPOINTS:
                breaches.append(f"{host}:{port}")
                raise AssertionError(
                    f"{request.node.nodeid} opened a real connection to the "
                    f"model server at {host}:{port}."
                )
        return real_connect(self, address)

    monkeypatch.setattr(socket.socket, "connect", guarded)
    yield
    assert not breaches, (
        f"{request.node.nodeid} tried to reach the real model server "
        f"({', '.join(sorted(set(breaches)))}). Tests must inject their own "
        "model -- `run_turn` passes `session.storyteller.llm_fn` through to "
        "`run_pipeline`, so setting it on the session covers every agent. "
        "Mark the test @pytest.mark.live if it genuinely needs the server "
        "running."
    )


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