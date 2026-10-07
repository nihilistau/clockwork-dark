"""
The engine's one shared HTTP client (``engine/net.py``, v0.21.1 T3b).

``httpx.get`` / ``httpx.post`` build a new client, and with it a new SSL
context and a fresh load of the certifi CA bundle, for EVERY request -- about
0.21 s each on the owner's Windows PC, plain ``http://`` included. These pin:

* the cost is paid once per process: N discovery refreshes, a liveness probe
  and the engine's own long-lived clients build at most ONE SSL context
  between them (it was one per request and one per client);
* sharing the client changed nothing a request can see: every request still
  opens its own connection (so the suite's socket guard still sees, and
  refuses, every one -- no pooled connection skips ``connect``), and no
  cookie from one answer rides on the next request.
"""

from __future__ import annotations

import socket
import ssl
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Iterator

import httpx
import pytest

from engine.config import reset_config
from engine.llm.registry import ModelRegistry, probe_models, reset_registry
from tests.llm_wire import wire

_V1_BODY = {
    "models": [
        {
            "key": "a-model",
            "type": "llm",
            "architecture": "gemma3",
            "max_context_length": 32768,
            "loaded_instances": [{"config": {"context_length": 16384}}],
            "capabilities": {"trained_for_tool_use": True},
        }
    ]
}


def _fresh_net(monkeypatch: pytest.MonkeyPatch) -> None:
    """Start this test with no shared client or context built yet (no-op before T3b)."""
    try:
        from engine import net
    except ImportError:  # the code before T3b: every request builds its own
        return
    net.close()
    monkeypatch.setattr(net, "_ssl_context", None)


@pytest.fixture
def contexts(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[str]]:
    """Every SSL context ``httpx`` builds for ``verify=True`` in the test, counted."""
    reset_config()
    reset_registry()
    _fresh_net(monkeypatch)
    made: list[str] = []
    real = ssl.create_default_context

    def counting(*args: Any, **kwargs: Any) -> ssl.SSLContext:
        made.append(str(kwargs.get("cafile") or kwargs.get("capath") or ""))
        return real(*args, **kwargs)

    # httpx's create_ssl_context does `import ssl` and calls this attribute.
    monkeypatch.setattr(ssl, "create_default_context", counting)
    yield made
    _fresh_net(monkeypatch)
    reset_registry()
    reset_config()


@pytest.mark.real_discovery
def test_discovery_builds_one_ssl_context_however_often_it_refreshes(
    contexts: list[str],
) -> None:
    """
    FAILED before T3b: five refreshes, a probe and two model clients built
    eight SSL contexts (~1.7 s here); now they share one.
    """
    refreshes = 5
    with wire([{"status": 200, "json": _V1_BODY}] * (refreshes + 1), exhaust=True):
        registry = ModelRegistry(base_url="http://x/v1")
        for _ in range(refreshes):
            assert [m.id for m in registry.refresh()] == ["a-model"]
        ok, detail = probe_models("http://x/api/v1/models", provider="lmstudio")
        assert ok, detail

    from engine.llm.client import LMSClient
    from engine.llm.lmstudio_native import NativeClient

    for client in (LMSClient(), NativeClient()):
        client._client.close()

    assert len(contexts) <= 1, (
        f"{len(contexts)} SSL contexts for {refreshes} refreshes, a probe and two "
        "clients: each one reloads the CA bundle (~0.21 s on Windows)"
    )


# -- the same request as httpx.get made -----------------------------------


class _Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), _Handler)
        self.connections = 0
        self.cookies: list[str] = []


class _Handler(BaseHTTPRequestHandler):
    # HTTP/1.1 and a Content-Length: the SERVER would keep the connection
    # open, so only the client decides whether a second request reuses it.
    protocol_version = "HTTP/1.1"
    server: _Server

    def setup(self) -> None:
        super().setup()
        self.server.connections += 1

    def do_GET(self) -> None:  # noqa: N802 -- http.server's name
        self.server.cookies.append(self.headers.get("Cookie", ""))
        body = b"{}"
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Set-Cookie", "session=abc; Path=/")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args: Any) -> None:
        pass


@pytest.fixture
def server() -> Iterator[_Server]:
    httpd = _Server()
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield httpd
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


@pytest.mark.loopback
def test_every_request_opens_its_own_connection(
    server: _Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    No keep-alive: three requests, three ``connect`` calls through the suite's
    socket guard (which wraps ``socket.socket.connect``), three connections
    accepted -- as three ``httpx.get`` calls made. A pooled connection would
    reach the server without passing the guard.
    """
    from engine import net

    port = server.server_address[1]
    guarded = socket.socket.connect
    dialled: list[Any] = []

    def counting(sock: Any, address: Any) -> Any:
        if isinstance(address, tuple) and len(address) >= 2 and address[1] == port:
            dialled.append(address)
        return guarded(sock, address)

    monkeypatch.setattr(socket.socket, "connect", counting)
    for _ in range(3):
        assert net.get(f"http://127.0.0.1:{port}/health", timeout=5.0).status_code == 200
    assert len(dialled) == 3
    assert server.connections == 3


@pytest.mark.loopback
def test_no_cookie_rides_from_one_request_to_the_next(server: _Server) -> None:
    """A throwaway client's jar died with it; the shared one keeps nothing."""
    from engine import net

    port = server.server_address[1]
    for _ in range(2):
        response = net.get(f"http://127.0.0.1:{port}/", timeout=5.0)
        assert response.headers["set-cookie"].startswith("session=")
    assert server.cookies == ["", ""]
    assert not net.client().cookies


def test_the_guard_refuses_a_forbidden_host_through_the_shared_client_every_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    The conftest guard (``_no_live_model_calls``) still refuses a host off this
    machine when the request goes through the shared client, on the first
    request AND the second. The resolver under the guard is a recording stub,
    so a broken guard shows as a lookup let through, never a real query.
    """
    import conftest

    from engine import net

    let_through: list[Any] = []

    def recording(host: Any, *args: Any, **kwargs: Any) -> Any:
        let_through.append(host)
        raise OSError("the stub resolver answers nothing")

    monkeypatch.setattr(conftest, "_REAL_GETADDRINFO", recording)
    monkeypatch.setattr(conftest, "_REAL_CONNECT", lambda _sock, address: recording(address))
    breaches = conftest._BREACHES
    before = len(breaches)
    try:
        for _ in range(2):
            with pytest.raises(AssertionError, match="not loopback"):
                net.get("http://net-canary.invalid:5051/v1/models", timeout=1.0)
        assert len(breaches) == before + 2
        assert let_through == []
    finally:
        del breaches[before:]


def test_the_request_is_built_as_httpx_get_builds_it() -> None:
    """Same defaults: verify on, environment trusted, no redirect followed."""
    from engine import net

    shared = net.client()
    assert shared.follow_redirects is False
    assert shared.trust_env is True
    with httpx.Client(verify=net.ssl_context()) as throwaway:
        assert shared.timeout == throwaway.timeout
        assert dict(shared.headers) == dict(throwaway.headers)
    assert net.ssl_context().verify_mode == ssl.CERT_REQUIRED
    assert net.ssl_context().check_hostname is True
