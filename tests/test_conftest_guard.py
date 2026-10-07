"""
The live-call guard in ``tests/conftest.py`` covers whatever server is configured.

FINDING 2. ``_model_endpoints`` skipped any URL without an explicit port, so a
hosted ``https://models.example/v1`` base URL -- the kind v0.20's hosted mode
and any remote OpenAI-compatible server use -- was not guarded at all. It also
read ``lmstudio.native_url`` and ``stack.health_url``, neither of which has ever
existed. It now reads ``llm.base_url`` and the model server's health URL, and a
URL with no port is guarded on its scheme's default one.

The endpoints are read through the real layer loader: the config directory is
``tmp_path``, the shipped ``default.yaml`` is the bottom layer.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator

import pytest
import yaml

import engine.config as config
from conftest import _empty_model_list, _model_endpoints  # the loaded conftest, not a copy

REPO = Path(__file__).resolve().parents[1]
LOOPBACK = {"localhost", "127.0.0.1", "::1"}


@pytest.fixture
def local(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    """Write a ``local.yaml`` under ``tmp_path`` and answer the guard's endpoints."""
    monkeypatch.delenv("CLOCKWORK_ENV", raising=False)
    monkeypatch.setattr(config, "_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config, "_DEFAULT_PATH", REPO / "config" / "default.yaml")
    monkeypatch.setattr(config, "_overlay", {})
    monkeypatch.setattr(config, "_instance", None)

    def endpoints(data: dict[str, Any]) -> frozenset[tuple[str, int]]:
        (tmp_path / "local.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")
        config._instance = None
        return _model_endpoints()

    yield endpoints


def test_a_remote_https_base_url_is_guarded_on_443(local: Any) -> None:
    """FINDING 2: no port in the URL used to mean no guard at all."""
    blocked = local({"llm": {"base_url": "https://models.example/v1"}})
    assert ("models.example", 443) in blocked


def test_a_portless_url_is_guarded(local: Any) -> None:
    """The port hole on its own: v0.18 read this key, and still skipped it."""
    blocked = local({"llm": {"base_url": "https://models.example/v1"}})
    assert ("models.example", 443) in blocked


def test_a_plain_http_url_without_a_port_is_guarded_on_80(local: Any) -> None:
    blocked = local({"llm": {"base_url": "http://gpu-box.lan/v1"}})
    assert ("gpu-box.lan", 80) in blocked


def test_the_health_url_is_guarded_too(local: Any) -> None:
    blocked = local(
        {"stack": {"services": {"llm": {"health_url": "http://health.example:8081/health"}}}}
    )
    assert ("health.example", 8081) in blocked
    # And the base URL is still there beside it, on every loopback spelling.
    assert {(host, 1234) for host in LOOPBACK} <= blocked


def test_the_shipped_config_guards_every_loopback_spelling() -> None:
    assert {(host, 1234) for host in LOOPBACK} <= _model_endpoints()


@pytest.mark.loopback
def test_a_guarded_host_name_is_refused_whatever_it_resolves_to(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Through the real guard, not set membership. ``models.example`` is made to
    resolve to a live local listener, and only its NAME is guarded: the
    connect sees 127.0.0.1, so the guard has to catch the name before it
    resolves. Checked at ``connect`` alone this connected (review finding 1).
    """
    import socket

    import conftest

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]
    real_resolve = conftest._REAL_GETADDRINFO

    def resolve(host: Any, service: Any, *args: Any, **kwargs: Any) -> Any:
        if host == "models.example":
            host = "127.0.0.1"
        return real_resolve(host, service, *args, **kwargs)

    monkeypatch.setattr(conftest, "_REAL_GETADDRINFO", resolve)
    monkeypatch.setattr(conftest, "_model_endpoints", lambda: frozenset({("models.example", port)}))
    breaches = conftest._BREACHES
    before = len(breaches)
    connection = None
    try:
        with pytest.raises(AssertionError, match="models.example"):
            connection = socket.create_connection(("models.example", port), timeout=2)
        assert breaches[before:] == [f"models.example:{port}"]
    finally:
        # The breach was provoked on purpose; the guard's teardown must not fail on it.
        del breaches[before:]
        if connection is not None:
            connection.close()
        listener.close()


@pytest.mark.parametrize(
    "how",
    ["getaddrinfo", "create_connection", "gethostbyname", "connect_literal_ip"],
)
def test_any_host_off_this_machine_is_refused(monkeypatch: pytest.MonkeyPatch, how: str) -> None:
    """
    The canary for the default-deny guard (v0.20.0 T8 fix round 1): a fake
    non-loopback name, and a literal non-loopback address, are refused and
    recorded for the teardown assertion. The resolver UNDER the guard is a
    stub that records, so a broken guard would show here as a lookup it let
    through -- never as a real query leaving the machine.
    """
    import socket

    import conftest

    let_through: list[Any] = []

    def recording(host: Any, *args: Any, **kwargs: Any) -> Any:
        let_through.append(host)
        raise OSError("the stub resolver answers nothing")

    monkeypatch.setattr(conftest, "_REAL_GETADDRINFO", recording)
    # Every branch has a stub beneath it (T8 fix round 2): gethostbyname's
    # and connect's real calls are read at call time too.
    monkeypatch.setattr(conftest, "_REAL_GETHOSTBYNAME", recording)
    monkeypatch.setattr(conftest, "_REAL_CONNECT", lambda _sock, address: recording(address))
    breaches = conftest._BREACHES
    before = len(breaches)
    try:
        with pytest.raises(AssertionError, match="not loopback"):
            if how == "getaddrinfo":
                socket.getaddrinfo("stt-canary.invalid", 5051)
            elif how == "create_connection":
                socket.create_connection(("stt-canary.invalid", 5051), timeout=1)
            elif how == "gethostbyname":
                socket.gethostbyname("stt-canary.invalid")
            else:
                probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                try:
                    probe.connect(("192.0.2.1", 9))  # TEST-NET-1: never routed
                finally:
                    probe.close()
        assert len(breaches) == before + 1
        assert let_through == []
    finally:
        del breaches[before:]


@pytest.mark.loopback
def test_loopback_is_still_allowed() -> None:
    import socket

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    try:
        with socket.create_connection(("localhost", listener.getsockname()[1]), timeout=2):
            pass
    finally:
        listener.close()


def test_discovery_is_answered_with_an_empty_model_list() -> None:
    """
    The discovery pin is in force for an ordinary test, and answers the
    active provider's empty list, so a turn budgets on the engine's own
    no-models path rather than opening a socket.
    """
    from engine.llm.registry import ModelRegistry

    assert _empty_model_list() == {"models": []}
    assert ModelRegistry()._fetch("/api/v1/models") == _empty_model_list()


@pytest.mark.parametrize("provider", ["lmstudio", "vllm", "llamacpp", "ollama", "openai_compat"])
def test_the_discovery_pin_answers_each_providers_own_empty_list(
    local: Any, provider: str
) -> None:
    """
    Under every provider the pinned discovery parses -- it is that server's
    list shape, empty -- so refresh lands on the no-models path, not on a
    NotAModelList for LM Studio's shape arriving at a vLLM parser.
    """
    from engine.llm.providers import PROVIDERS
    from engine.llm.registry import ModelRegistry

    base = PROVIDERS[provider].default_base_url.value or "https://models.example/v1"
    local({"llm": {"provider": provider, "base_url": base}})
    assert _empty_model_list() == PROVIDERS[provider].empty_model_list()
    registry = ModelRegistry()
    assert registry._fetch("/whatever") == PROVIDERS[provider].empty_model_list()
    assert registry.refresh() == []


def test_the_ollama_probe_is_pinned_and_sends_nothing(local: Any) -> None:
    """
    CANARY (v0.19.0 T5). ``OllamaClient.is_available`` is a door like
    ``NativeClient``'s: it asks ``/api/version`` through an ``httpx.Client``
    INSTANCE, which no module-level ``httpx`` patch touches. The conftest
    pins it False for every test. Here the wire seam sits under it with no
    answers: pinned, it sends nothing; take the pin out of
    ``_no_live_model_calls`` and the probe's request reaches the seam, which
    fails this test at the ``with`` block's exit (and, off the seam, the
    socket guard would refuse localhost:11434 at teardown).
    """
    from engine.llm.ollama import OllamaClient
    from tests.llm_wire import wire

    local({"llm": {"provider": "ollama", "base_url": "http://localhost:11434"}})
    with wire([]) as seam:
        assert OllamaClient().is_available() is False
    assert seam.requests == []


def _default_ports() -> list[tuple[str, int]]:
    from urllib.parse import urlparse

    from engine.llm.providers import PROVIDERS

    ports = []
    for provider in PROVIDERS.values():
        url = provider.default_base_url.value
        if url:
            ports.append((provider.name, int(urlparse(url).port)))
    return ports


@pytest.mark.parametrize(
    "provider,port", _default_ports(), ids=[name for name, _ in _default_ports()]
)
def test_every_providers_default_port_is_refused(provider: str, port: int) -> None:
    """
    CANARY (v0.19.0 T3). Under the shipped config -- LM Studio on 1234 -- a
    test that dials vLLM's 8000, llama-server's 8080 or Ollama's 11434 on
    loopback is refused by the real guard, by name, before anything
    resolves. Take the provider defaults out of ``_model_server_urls`` and
    the three non-LM Studio cases connect (or fail to) unrefused.
    """
    import socket

    import conftest

    breaches = conftest._BREACHES
    before = len(breaches)
    connection = None
    try:
        with pytest.raises(AssertionError, match=f"localhost:{port}"):
            connection = socket.create_connection(("localhost", port), timeout=2)
        assert breaches[before:] == [f"localhost:{port}"]
    finally:
        # Provoked on purpose; the guard's teardown must not fail on it.
        del breaches[before:]
        if connection is not None:
            connection.close()


def test_the_guarded_endpoints_follow_the_config_at_check_time(
    local: Any,
) -> None:
    """
    Not frozen at import: a base URL the config names only after collection
    is guarded the moment it is named.
    """
    assert ("late.example", 9999) not in _model_endpoints()
    blocked = local({"llm": {"base_url": "http://late.example:9999/v1"}})
    assert ("late.example", 9999) in blocked


# -- the owner's LM Studio files (`_no_owner_lm_studio_files`, v0.19.0 T6) -------------
#
# Every canary below is safe with its guard REMOVED: the home directory is a
# fake one under tmp_path, the out-of-root target's directory does not exist
# (so nothing can be written there, guarded or not), and the server cannot
# start (`available` is False). What the guard's absence changes is only
# what these tests assert, never what reaches the owner's disk.

#: What an owner's mcp.json holds before a test runs: somebody else's server.
_OWNERS = {"mcpServers": {"owners-server": {"url": "https://owner.example/mcp"}}}


@pytest.fixture
def fake_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """
    A home directory with an LM Studio ``mcp.json`` in it, standing in for
    the owner's: ``Path.home`` and the environment both point at it, so an
    unredirected ``mcp_json_path`` would find THIS file, never the real one.
    """
    home = tmp_path / "home"
    sentinel = home / ".cache" / "lm-studio" / "mcp.json"
    sentinel.parent.mkdir(parents=True)
    sentinel.write_text(__import__("json").dumps(_OWNERS), encoding="utf-8")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    for name in ("USERPROFILE", "HOME"):
        monkeypatch.setenv(name, str(home))
    return sentinel


def test_mcp_json_is_redirected_off_the_home_directory(
    llm_server: Any, fake_home: Path
) -> None:
    """
    CANARY. Under an LM Studio, MCP-enabled config, registering a session
    with no ``path`` lands in the test's own temp directory. Take the
    redirect out of ``_no_owner_lm_studio_files`` and ``mcp_json_path`` finds
    the (fake) home's file: the session is registered in it and a backup is
    left beside it, and this test fails.
    """
    from engine.mcp import skills_server

    llm_server("lmstudio", mcp={"enabled": True, "mcp_json": ""})
    before = fake_home.read_bytes()
    target = skills_server.mcp_json_path()
    assert target != fake_home
    assert skills_server.register_session(
        "http://127.0.0.1:1/mcp/sse", "canary", settle_seconds=0
    ) == "engine-skills-canary"
    assert fake_home.read_bytes() == before
    assert sorted(p.name for p in fake_home.parent.iterdir()) == ["mcp.json"]
    assert "engine-skills-canary" in target.read_text(encoding="utf-8")


def test_a_write_outside_the_temp_root_is_refused_and_recorded(
    request: Any, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """
    CANARY. A caller that names its own ``path`` outside every test's temp
    root is refused by the writers, and the refusal is recorded. The target's
    directory does not exist, so even unguarded nothing is written -- but
    nothing is then recorded either, and this test fails.
    """
    from engine.mcp import skills_server

    root = Path(tmp_path_factory.getbasetemp()).resolve()
    outside = root.parent / f"{root.name}-not-a-test-dir" / "mcp.json"
    assert not outside.parent.exists()
    breaches = request.node.lm_studio_breaches
    assert skills_server.register_session(
        "http://127.0.0.1:1/mcp/sse", "canary", path=outside, settle_seconds=0
    ) is None
    seen = list(breaches)
    breaches.clear()  # provoked on purpose; the guard's teardown would fail it
    # The backup comes first, and its refusal stops the registration there.
    assert seen == [f"back up {outside}"]
    assert not outside.parent.exists()


def test_an_unmarked_test_cannot_start_a_skills_server(
    request: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    CANARY. ``SkillsServer.start`` answers False to a test not marked
    ``mcp_server``, and records it. ``available`` is False here, so the real
    method would start nothing either -- but it records nothing, and this
    test fails.
    """
    from engine.mcp import skills_server

    monkeypatch.setattr(skills_server, "available", lambda: False)
    server = skills_server.SkillsServer(resolve_engine=lambda _sid: None, port=1)
    assert server.start(wait_seconds=0.0) is False
    breaches = request.node.lm_studio_breaches
    seen = list(breaches)
    breaches.clear()  # provoked on purpose
    assert seen == ["start a skills server"]


@pytest.mark.loopback
def test_the_session_holds_every_guarded_loopback_port(pytestconfig: pytest.Config) -> None:
    """A throwaway server can never be handed a model server's default port
    (this machine's ephemeral range starts at 1024; one test got 8080 and the
    guard failed it, v0.21.0). Each guarded port is held by the session, or
    in use by something else -- either way the OS cannot assign it."""
    import socket

    from tests.conftest import guarded_loopback_ports

    ports = guarded_loopback_ports()
    assert {8000, 8080, 11434} <= set(ports), ports  # vLLM, llama-server, Ollama
    held = {sock.getsockname()[1] for sock in getattr(pytestconfig, "_clockwork_held_ports", [])}
    for port in ports:
        if port in held:
            continue
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            with pytest.raises(OSError):
                probe.bind(("127.0.0.1", port))
        finally:
            probe.close()


def test_each_test_gets_its_own_guard_dirs_without_a_numbered_scan(tmp_path_factory) -> None:
    """v0.21.1 T4: the per-test saves, data and LM Studio dirs come from a
    counter under ``<basetemp>/guards``, not from ``mktemp``'s scan of the
    whole basetemp root."""
    import os

    from tests.conftest import guard_dir

    base = Path(tmp_path_factory.getbasetemp()).resolve()
    first, second = guard_dir(tmp_path_factory, "data"), guard_dir(tmp_path_factory, "data")
    assert first != second
    assert first.parent.parent == second.parent.parent == base / "guards"
    assert Path(os.environ["CLOCKWORK_DATA_DIR"]).resolve().parent.parent == base / "guards"


def test_two_conftest_copies_never_hand_out_the_same_guard_dir(tmp_path_factory) -> None:
    """Preflight K4: ``from tests.conftest import ...`` loads a SECOND copy of
    the conftest. Its counter must be the first copy's (kept on ``sys``), and
    a ``guards/<n>`` that exists already is skipped, never reused."""
    import sys

    import conftest as loaded
    import tests.conftest as copy

    assert loaded is not copy, "expected two copies; the test proves nothing otherwise"
    assert loaded.guard_dir is not copy.guard_dir
    made = []
    for _ in range(5):
        made.append(loaded.guard_dir(tmp_path_factory, "x"))
        made.append(copy.guard_dir(tmp_path_factory, "x"))
    assert len({p.parent for p in made}) == len(made)

    # A slot made behind the counter's back (another session in this process
    # with the same basetemp) is skipped.
    seq = getattr(sys, loaded._GUARD_SEQ_KEY)
    ahead = int(made[-1].parent.name) + 1
    (made[-1].parent.parent / str(ahead)).mkdir()
    skipped = copy.guard_dir(tmp_path_factory, "x")
    assert int(skipped.parent.name) > ahead
    assert next(seq) > ahead


def test_an_empty_guard_dir_is_dropped_and_a_used_one_kept(tmp_path_factory) -> None:
    from conftest import _drop_if_empty, guard_dir

    empty, used = guard_dir(tmp_path_factory, "data"), guard_dir(tmp_path_factory, "data")
    (used / "save.json").write_text("{}", encoding="utf-8")
    _drop_if_empty(empty)
    _drop_if_empty(used)
    assert not empty.parent.exists()
    assert (used / "save.json").is_file()


#: What `test_a_test_records_its_guard_dirs` saw, for the test after it.
_GUARDS_SEEN: list[Path] = []


def test_a_test_records_its_guard_dirs() -> None:
    """The first of an ordered pair (review finding 5): record this test's
    saves, data and LM Studio guard dirs, and write nothing into them."""
    import os

    from engine.mcp import skills_server
    from engine.persistence import saves

    _GUARDS_SEEN[:] = [
        Path(saves.saves_base()),
        Path(os.environ["CLOCKWORK_DATA_DIR"]),
        Path(skills_server.mcp_json_path()).parent,
    ]
    assert all(path.is_dir() and path.parent.parent.name == "guards" for path in _GUARDS_SEEN)


def test_the_guard_dirs_a_test_left_empty_are_gone_after_it() -> None:
    """The second: both autouse guards dropped the previous test's empty dirs
    at its teardown, with their ``guards/<n>``."""
    if not _GUARDS_SEEN:
        pytest.skip("the recording test did not run first in this process")
    assert not [path.parent for path in _GUARDS_SEEN if path.parent.exists()]
