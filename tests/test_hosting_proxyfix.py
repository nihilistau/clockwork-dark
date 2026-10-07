"""
Forwarded headers through the front door (v0.20.0 T12, spec §7.3, §14.5).

Under the supervisor ``hosting.trusted_proxies`` is the FRONT DOOR's: its
``ProxyFix`` resolves the client's address, scheme and host, and then every
``X-Forwarded-*`` header is deleted. The front door REPLACES the forwarded
headers it sends a worker with what it resolved, and carries the boot's proxy
token (``X-Clockwork-Proxy``). A worker (``gate.ProxyTokenHeaders``, its
outermost WSGI layer, outside engineio) trusts one hop -- ``ProxyFix(x_for=1,
x_proto=1, x_host=1)`` -- only on a request carrying that token, and DELETES
every forwarded header on any other, so engineio's own same-origin check
(which reads ``X-Forwarded-Host``/``-Proto`` raw) never sees one the front
door did not send. The token header itself never reaches the worker's Flask
``request.headers``.

All of it in this process (``tests/hosting_instance.py::InProcessFrontDoor``):
a hosted worker and the front door on Werkzeug threads over a loopback bus,
with a recorder put just inside the worker's token layer and another just
outside it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Iterable, Iterator

import pytest

from tests.engineio_wire import PollingClient
from tests.hosting_instance import InProcessFrontDoor

# In-process loopback servers: the hybrid run's serial phase (tests/tiers.py).
pytestmark = pytest.mark.loopback

CLIENT_ADDRESS = "203.0.113.7"


class _Recorder:
    """A WSGI layer that keeps what each request's environ held when it passed."""

    def __init__(self, app: Callable[..., Iterable[bytes]]) -> None:
        self.app = app
        self.seen: list[dict[str, Any]] = []

    def __call__(self, environ: dict[str, Any], start_response: Callable[..., Any]) -> Any:
        self.seen.append(
            {
                "path": environ.get("PATH_INFO", ""),
                "remote": environ.get("REMOTE_ADDR"),
                "scheme": environ.get("wsgi.url_scheme"),
                "host": environ.get("HTTP_HOST"),
                "forwarded": {k: v for k, v in environ.items() if k.startswith("HTTP_X_FORWARDED_")},
                "rfc7239": environ.get("HTTP_FORWARDED"),
                "proxy": environ.get("HTTP_X_CLOCKWORK_PROXY"),
            }
        )
        return self.app(environ, start_response)

    def last(self, path_prefix: str) -> dict[str, Any]:
        found = [row for row in self.seen if str(row["path"]).startswith(path_prefix)]
        assert found, f"nothing reached {path_prefix}: {[r['path'] for r in self.seen]}"
        return found[-1]


class Watched:
    """The in-process instance, with recorders inside and outside the worker's token layer."""

    def __init__(self, door: InProcessFrontDoor) -> None:
        from engine.hosting.gate import ProxyTokenHeaders

        self.door = door
        app = door.hosted.app
        layer = app.wsgi_app
        assert isinstance(layer, ProxyTokenHeaders), "the worker's outermost layer is not the token check"
        self.inside = _Recorder(layer.inner)
        layer.inner = self.inside
        self.outside = _Recorder(layer)
        app.wsgi_app = self.outside
        #: ``request.headers`` as the worker's Flask saw them, per path.
        self.flask_headers: list[tuple[str, dict[str, str]]] = []

        @app.before_request
        def _keep_headers() -> None:
            from flask import request

            self.flask_headers.append((request.path, dict(request.headers)))


def _door(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, **hosting: Any) -> Iterator[Watched]:
    door = InProcessFrontDoor(monkeypatch, tmp_path, hosting=hosting)
    door.start()
    try:
        yield Watched(door)
    finally:
        door.stop()


@pytest.fixture
def trusting(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Watched]:
    """The front door behind one trusted reverse proxy (``trusted_proxies: 1``)."""
    yield from _door(monkeypatch, tmp_path, trusted_proxies=1)


@pytest.fixture
def plain(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Watched]:
    """The front door with nothing in front (``trusted_proxies: 0``, the default)."""
    yield from _door(monkeypatch, tmp_path)


def test_under_one_trusted_proxy_the_front_door_sees_the_forwarded_address(trusting: Watched) -> None:
    """HTTP and a polling handshake alike: the worker is told the client's address."""
    http = trusting.door.logged_in()
    try:
        assert http.get("/api/games", headers={"X-Forwarded-For": CLIENT_ADDRESS}).status_code == 200
        assert trusting.inside.last("/api/games")["remote"] == CLIENT_ADDRESS
        poll = PollingClient(http, trusting.door.base, headers={"X-Forwarded-For": CLIENT_ADDRESS})
        poll.handshake()
        assert trusting.inside.last("/socket.io")["remote"] == CLIENT_ADDRESS
        poll.close()
    finally:
        http.close()


def test_with_no_trusted_proxy_a_forwarded_address_is_ignored(plain: Watched) -> None:
    http = plain.door.logged_in()
    try:
        assert http.get("/api/games", headers={"X-Forwarded-For": CLIENT_ADDRESS}).status_code == 200
        assert plain.inside.last("/api/games")["remote"] == "127.0.0.1"
        poll = PollingClient(http, plain.door.base, headers={"X-Forwarded-For": CLIENT_ADDRESS})
        poll.handshake()
        assert plain.inside.last("/socket.io")["remote"] == "127.0.0.1"
        poll.close()
    finally:
        http.close()


def test_a_client_s_forwarded_headers_reach_a_worker_replaced(plain: Watched) -> None:
    """
    What a worker is SENT carries the front door's resolution -- one address,
    the scheme and host the front door served -- never the client's claims;
    and once past the token check, no forwarded header and no token is left.
    """
    http = plain.door.logged_in()
    claims = {"X-Forwarded-For": "198.51.100.1", "X-Forwarded-Host": "evil.example", "X-Forwarded-Proto": "https"}
    try:
        assert http.get("/api/games", headers=claims).status_code == 200
        sent = plain.outside.last("/api/games")
        assert sent["forwarded"] == {
            "HTTP_X_FORWARDED_FOR": "127.0.0.1",
            "HTTP_X_FORWARDED_PROTO": "http",
            "HTTP_X_FORWARDED_HOST": f"127.0.0.1:{plain.door.front_port}",
        }
        assert sent["proxy"] == plain.door.proxy_token
        inside = plain.inside.last("/api/games")
        assert inside["forwarded"] == {} and inside["proxy"] is None
        assert inside["remote"] == "127.0.0.1"
        assert inside["host"] == f"127.0.0.1:{plain.door.front_port}"
        assert inside["scheme"] == "http"
    finally:
        http.close()


@pytest.mark.parametrize("token", [None, "wrong"])
def test_a_worker_deletes_forwarded_headers_without_the_proxy_token(plain: Watched, token: Any) -> None:
    """Straight to the worker, with no token or a wrong one: nothing forwarded is believed, or kept."""
    headers = {"X-Forwarded-For": "198.51.100.2", "X-Forwarded-Host": "evil.example", "X-Forwarded-Proto": "https"}
    if token is not None:
        headers["X-Clockwork-Proxy"] = token
    direct = plain.door.http(plain.door.worker_base)
    try:
        direct.get("/api/health", headers=headers)
        inside = plain.inside.last("/api/health")
        assert inside["forwarded"] == {} and inside["proxy"] is None
        assert inside["remote"] == "127.0.0.1"
        assert inside["host"] == f"127.0.0.1:{plain.door.worker_port}"
        assert inside["scheme"] == "http"
    finally:
        direct.close()


def test_engineio_never_trusts_a_forwarded_host_the_front_door_did_not_send(plain: Watched) -> None:
    """
    A polling handshake straight to the worker, with no token, a foreign
    ``Origin`` and an ``X-Forwarded-Host`` naming that origin: engineio's
    same-origin check would accept it on the raw header; with the header
    deleted first it is refused (400, engineio's own words). The origin is a
    loopback name on another port, so the host guard (which compares hosts,
    not ports) lets it through to engineio. Through the front door, the same
    handshake from the front door's own origin passes: ``Host`` is kept and
    the forwarded host is trusted through the token.
    """
    origin = "http://localhost:1"
    direct = plain.door.http(plain.door.worker_base)
    try:
        refused = PollingClient(
            direct,
            plain.door.worker_base,
            headers={"Origin": origin, "X-Forwarded-Host": "localhost:1", "X-Forwarded-Proto": "http"},
        ).handshake_response()
        assert refused.status_code == 400
        assert "Not an accepted origin" in refused.text
    finally:
        direct.close()
    http = plain.door.logged_in()
    try:
        poll = PollingClient(http, plain.door.base, headers={"Origin": plain.door.base})
        poll.handshake()
        assert poll.connect()["type"] == "connect"
        poll.close()
    finally:
        http.close()


def test_rfc_7239_forwarded_never_reaches_a_worker(plain: Watched) -> None:
    """
    Fix round 1 (M2): a client's ``Forwarded`` is dropped like its
    ``X-Forwarded-*`` -- through the front door (it is not even sent on) and
    straight at a worker without the token. On eb1d4d4 the worker's Flask
    saw ``for=6.6.6.6;host=evil.example;proto=https`` unchanged.
    """
    claim = {"Forwarded": "for=6.6.6.6;host=evil.example;proto=https"}
    http = plain.door.logged_in()
    direct = plain.door.http(plain.door.worker_base)
    try:
        assert http.get("/api/games", headers=claim).status_code == 200
        assert plain.outside.last("/api/games")["rfc7239"] is None
        assert plain.inside.last("/api/games")["rfc7239"] is None
        direct.get("/api/health", headers=claim)
        assert plain.inside.last("/api/health")["rfc7239"] is None
        assert not any(
            name.lower() == "forwarded" for _p, headers in plain.flask_headers for name in headers
        )
    finally:
        http.close()
        direct.close()


def test_the_proxy_token_never_reaches_the_worker_s_flask_headers(plain: Watched) -> None:
    http = plain.door.logged_in()
    try:
        assert http.get("/api/games").status_code == 200
        headers = dict(next(h for p, h in reversed(plain.flask_headers) if p == "/api/games"))
        assert not any(name.lower() == "x-clockwork-proxy" for name in headers)
        assert not any(name.lower().startswith("x-forwarded-") for name in headers)
        assert plain.door.proxy_token not in repr(plain.flask_headers)
    finally:
        http.close()
