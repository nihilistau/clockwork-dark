"""
The Host-header allowlist in local mode (v0.20.0 T2 fix round 1, review
finding 10; ``engine/scenes/host_guard.py``).

Loopback keeps the network out; this keeps a DNS-rebinding page in the owner's
browser out. A request whose Host is not ``localhost``, ``127.0.0.1``,
``[::1]`` or the bound host is refused with a 400 before Flask or Socket.IO
sees it -- ``/socket.io/`` included. A wildcard bind (LAN play) also answers
to any IP literal and this machine's own name.
"""

from __future__ import annotations

import socket
from typing import Any

import pytest

from tests.local_golden import scripted_model


def _app(monkeypatch: pytest.MonkeyPatch, bind: str | None = None) -> tuple[Any, Any]:
    from engine.scenes import flask_scene
    from engine.scenes.default_scene import create_app

    if bind is not None:
        monkeypatch.setattr(flask_scene, "scene_host", lambda name: bind)
    return create_app(testing=True, llm_fn=scripted_model)


def _status(client: Any, path: str, host: str) -> int:
    return client.get(path, headers={"Host": host}).status_code


@pytest.mark.parametrize("host", ["localhost", "localhost:5573", "127.0.0.1:5573", "[::1]:5573", "LOCALHOST"])
def test_the_loopback_names_are_answered(monkeypatch: pytest.MonkeyPatch, host: str) -> None:
    _, app = _app(monkeypatch)
    assert _status(app.test_client(), "/api/health", host) == 200


@pytest.mark.parametrize("host", ["evil.example", "evil.example:5573", "192.168.1.20:5573", "localhost.evil.example"])
def test_any_other_host_is_refused(monkeypatch: pytest.MonkeyPatch, host: str) -> None:
    _, app = _app(monkeypatch)
    client = app.test_client()
    res = client.get("/api/health", headers={"Host": host})
    assert res.status_code == 400
    assert b"Host header not allowed" in res.data


def test_the_socket_door_is_guarded_too(monkeypatch: pytest.MonkeyPatch) -> None:
    """Socket.IO's polling transport answers before Flask's routing: it is wrapped too."""
    _, app = _app(monkeypatch)
    client = app.test_client()
    path = "/socket.io/?EIO=4&transport=polling"
    assert _status(client, path, "evil.example:5573") == 400
    assert _status(client, path, "localhost:5573") == 200


def test_a_named_bind_is_answered(monkeypatch: pytest.MonkeyPatch) -> None:
    _, app = _app(monkeypatch, bind="my-box.lan")
    client = app.test_client()
    assert _status(client, "/api/health", "my-box.lan:5573") == 200
    assert _status(client, "/api/health", "evil.example:5573") == 400


def test_a_wildcard_bind_answers_ip_literals_and_this_machine(monkeypatch: pytest.MonkeyPatch) -> None:
    _, app = _app(monkeypatch, bind="0.0.0.0")
    client = app.test_client()
    assert _status(client, "/api/health", "192.168.1.20:5573") == 200
    assert _status(client, "/api/health", "[fe80::1]:5573") == 200
    assert _status(client, "/api/health", f"{socket.gethostname()}:5573") == 200
    assert _status(client, "/api/health", "evil.example:5573") == 400


def test_run_answers_to_the_host_it_binds(monkeypatch: pytest.MonkeyPatch) -> None:
    """``--host`` beats the config the guard was built from."""
    import flask_socketio

    scene, app = _app(monkeypatch)
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(flask_socketio.SocketIO, "run", lambda self, app_, **kw: calls.append(kw))
    client = app.test_client()
    assert _status(client, "/api/health", "10.0.0.5:5573") == 400
    scene.run(host="10.0.0.5", port=5573)
    assert calls and calls[0]["host"] == "10.0.0.5"
    assert _status(client, "/api/health", "10.0.0.5:5573") == 200
    assert _status(client, "/api/health", "evil.example:5573") == 400


@pytest.mark.parametrize("host", ["[::1].evil.example", "[::1].evil.example:5573", "[::1]x", "[::1]:5573.evil"])
def test_a_bracketed_host_must_be_exactly_bracketed(monkeypatch: pytest.MonkeyPatch, host: str) -> None:
    """T2 re-review nit: ``[::1].evil.example`` was read as ``::1`` and let through."""
    _, app = _app(monkeypatch)
    assert _status(app.test_client(), "/api/health", host) == 400


# -- cross-site writes (T2 re-review, N1) --------------------------------------
#
# A page on another site can POST text/plain (a "simple" request, no preflight)
# to /api/game/new and every other state-changing route, and the owner's
# browser sends it to 127.0.0.1 with Host: localhost -- so the Host check alone
# let it start a game on the owner's model. Such a request carries an Origin
# (or a Referer) naming the other site.


def _post_new(client: Any, **headers: str) -> Any:
    return client.post(
        "/api/game/new",
        data='{"seed": 7}',
        content_type="text/plain",
        headers={"Host": "localhost:5573", **headers},
    )


@pytest.mark.parametrize(
    "headers",
    [
        {"Origin": "http://evil.example"},
        {"Origin": "https://evil.example:5573"},
        {"Origin": "null"},
        {"Origin": "http://localhost@evil.example"},
        {"Origin": "http://[::1].evil.example"},
        {"Referer": "http://evil.example/page.html"},
        # An Origin decides when both are present: a local Referer does not
        # launder a foreign Origin.
        {"Origin": "http://evil.example", "Referer": "http://localhost:5573/"},
    ],
)
def test_a_cross_site_write_is_refused(monkeypatch: pytest.MonkeyPatch, headers: dict[str, str]) -> None:
    scene, app = _app(monkeypatch)
    # The scene's session store is process-wide, so an earlier test's sessions
    # may be in it: what matters is that this request adds none.
    before = set(scene.store._sessions)
    res = _post_new(app.test_client(), **headers)
    assert res.status_code == 403, res.data
    assert b"Origin not allowed" in res.data
    assert set(scene.store._sessions) == before, "a game was started for a page on another site"


@pytest.mark.parametrize(
    "headers",
    [
        {},  # curl, a script: no browser, no Origin
        {"Origin": "http://localhost:5573"},
        {"Origin": "http://127.0.0.1:5573"},
        {"Origin": "http://[::1]:5573"},
        {"Referer": "http://localhost:5573/"},
    ],
)
def test_a_same_site_or_headerless_write_passes(monkeypatch: pytest.MonkeyPatch, headers: dict[str, str]) -> None:
    _, app = _app(monkeypatch)
    res = _post_new(app.test_client(), **headers)
    assert res.status_code == 200, res.data


@pytest.mark.parametrize("method", ["get", "head", "options"])
def test_a_cross_site_read_is_not_refused(monkeypatch: pytest.MonkeyPatch, method: str) -> None:
    _, app = _app(monkeypatch)
    client = app.test_client()
    res = getattr(client, method)(
        "/api/health", headers={"Host": "localhost:5573", "Origin": "http://evil.example"}
    )
    assert res.status_code != 403


_HANDSHAKE = "/socket.io/?EIO=4&transport=polling"


@pytest.mark.parametrize(
    ("headers", "status"),
    [
        # T3 fix round 1, review finding 1: the handshake is a GET that hands a
        # foreign page a readable sid, and the upgrade is a GET too.
        ({"Origin": "http://evil.example"}, 403),
        ({"Origin": "null"}, 403),
        ({"Origin": "http://evil.example", "Upgrade": "websocket", "Connection": "Upgrade"}, 403),
        ({"Origin": "http://localhost:5573"}, 200),
        ({"Origin": "http://127.0.0.1:5573"}, 200),
        ({}, 200),  # a same-origin polling GET sends no Origin; neither does the golden
    ],
)
def test_the_socket_handshake_is_guarded_by_origin(
    monkeypatch: pytest.MonkeyPatch, headers: dict[str, str], status: int
) -> None:
    _, app = _app(monkeypatch)
    res = app.test_client().get(_HANDSHAKE, headers={"Host": "localhost:5573", **headers})
    assert res.status_code == status, res.data


def test_a_foreign_websocket_upgrade_on_any_path_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """The Upgrade header alone makes a request a socket door."""
    _, app = _app(monkeypatch)
    res = app.test_client().get(
        "/api/health",
        headers={"Host": "localhost:5573", "Origin": "http://evil.example", "Upgrade": "WebSocket"},
    )
    assert res.status_code == 403


def test_an_ordinary_cross_site_read_still_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    """A GET of a Flask route stays open: no CORS header, so the browser keeps the page from reading it."""
    _, app = _app(monkeypatch)
    res = app.test_client().get(
        "/api/saves", headers={"Host": "localhost:5573", "Origin": "http://evil.example"}
    )
    assert res.status_code == 200
    assert "Access-Control-Allow-Origin" not in res.headers


def test_the_socket_path_comes_from_the_socketio_instance(monkeypatch: pytest.MonkeyPatch) -> None:
    scene, _ = _app(monkeypatch)
    assert scene.host_guard.socket_path == "/socket.io"


def test_the_socket_door_refuses_a_cross_site_post(monkeypatch: pytest.MonkeyPatch) -> None:
    """Socket.IO's polling transport POSTs its packets: the same rule holds there."""
    _, app = _app(monkeypatch)
    client = app.test_client()
    res = client.post(
        "/socket.io/?EIO=4&transport=polling&sid=x",
        data="40",
        content_type="text/plain",
        headers={"Host": "localhost:5573", "Origin": "http://evil.example"},
    )
    assert res.status_code == 403


# -- v0.20.0 T5 (T3 re-review N1, N2) -----------------------------------------------


def test_a_custom_socket_path_is_guarded(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    N1: Flask-SocketIO POPS ``path`` from ``server_options`` while it builds
    its middleware, so the guard, reading it there after construction, always
    got the default: a scene serving Socket.IO elsewhere had its handshake
    unguarded. The path is read off the constructed server now.
    """
    from flask_socketio import SocketIO

    from engine.scenes import flask_scene

    monkeypatch.setattr(
        flask_scene,
        "SocketIO",
        lambda app, **kwargs: SocketIO(app, path="game-io", **kwargs),
    )
    scene, app = _app(monkeypatch)
    assert scene.host_guard.socket_path == "/game-io"
    client = app.test_client()
    handshake = "/game-io/?EIO=4&transport=polling"
    foreign = client.get(handshake, headers={"Host": "localhost:5573", "Origin": "http://evil.example"})
    assert foreign.status_code == 403, foreign.data
    same = client.get(handshake, headers={"Host": "localhost:5573"})
    assert same.status_code == 200, same.data


@pytest.mark.parametrize(
    "path",
    [
        _HANDSHAKE,
        # Engine.IO's JSONP polling: loaded by a <script> tag, which sends a
        # Referer and no Origin.
        "/socket.io/?EIO=4&transport=polling&j=0",
    ],
    ids=["polling", "jsonp"],
)
def test_a_socket_request_with_only_a_foreign_referer_is_refused(
    monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    """N2: with no Origin, the socket door falls back to the Referer, as every other door does."""
    _, app = _app(monkeypatch)
    client = app.test_client()
    foreign = client.get(path, headers={"Host": "localhost:5573", "Referer": "http://evil.example/page"})
    assert foreign.status_code == 403, foreign.data
    local = client.get(path, headers={"Host": "localhost:5573", "Referer": "http://localhost:5573/"})
    assert local.status_code != 403, local.data


def test_socketio_path_reads_the_constructed_server() -> None:
    from flask import Flask
    from flask_socketio import SocketIO

    from engine.scenes.flask_scene import socketio_path

    assert socketio_path(SocketIO(Flask("a"), path="/custom/io")).strip("/") == "custom/io"
    assert socketio_path(SocketIO(Flask("b"))).strip("/") == "socket.io"
    assert socketio_path(SocketIO()).strip("/") == "socket.io"  # no app bound yet
