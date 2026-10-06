"""
Hosted mode's HTTP gate and what hosted mode turns off (v0.20.0 T7, spec
§6.3, §6.7, §7.2).

- EVERY rule x method in the URL map (the story's blueprint included)
  answers 401 without a login, except the open list; ``GET /`` redirects to
  the login page. Enumerated from the app itself, so a route added later is
  covered without editing this file; a rule whose converter this file cannot
  fill FAILS rather than being skipped.
- A blueprint registered AFTER ``install()`` is still behind the gate (the
  canary for "one hook, not a list").
- ``X-Forwarded-For`` with ``trusted_proxies: 0``: one WARNING per process.
- The §6.7 refusals raise ``HostingConfigError`` naming their keys; the
  settings panel's ``POST`` is 403 and its ``GET`` says ``writable: false``;
  ``/api/metrics`` is 404.
- Socket.IO: the hosted CORS value is never ``[]``, a cross-origin handshake
  is refused and a same-origin one accepted; messages are capped at 64 KiB.
- ``install()`` warms the process; the launcher warns, and exits 1 on a
  refusal.
"""

from __future__ import annotations

import logging
import re
import sys
from pathlib import Path
from typing import Any, Iterator

import pytest
from flask import Blueprint, jsonify

from engine.hosting import HostingConfigError
from engine.hosting.gate import OPEN
from tests.hosted_app import Hosted, build, login, teardown


@pytest.fixture
def hosted(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Hosted]:
    try:
        yield build(monkeypatch, tmp_path)
    finally:
        teardown()


#: A value for each converter the engine's rules use. A new converter fails
#: the enumeration (below) until it is given one here.
_SAMPLES = {"default": "x", "string": "x", "path": "x/y", "int": "1", "float": "1.0", "uuid": "0" * 32}
_ARG_RE = re.compile(r"<(?:(\w+)(?:\([^)]*\))?:)?(\w+)>")


def _url(rule: Any) -> str:
    def fill(match: re.Match[str]) -> str:
        converter = match.group(1) or "default"
        assert converter in _SAMPLES, f"no sample for converter {converter!r} in {rule.rule}"
        return _SAMPLES[converter]

    return _ARG_RE.sub(fill, rule.rule)


def _every_rule_and_method(app: Any) -> list[tuple[str, str, str]]:
    out = []
    for rule in app.url_map.iter_rules():
        for method in sorted(rule.methods or ()):
            out.append((rule.endpoint, method, _url(rule)))
    return out


def test_every_rule_and_method_needs_a_login_but_the_open_list(hosted: Hosted) -> None:
    app = hosted.app
    cases = _every_rule_and_method(app)
    endpoints = {endpoint for endpoint, _, _ in cases}
    # The story's own blueprint is mounted and enumerated too.
    from engine.scenes.spec import resolve_scene

    assert resolve_scene().blueprint, "the flagship declares a story blueprint"
    assert "/api/clues" in {rule.rule for rule in app.url_map.iter_rules()}
    assert {"hosting_auth.login", "hosting_auth.account_page", "index", "health"} <= endpoints
    client = hosted.client()
    wrong: list[str] = []
    for endpoint, method, url in cases:
        response = client.open(url, method=method)
        if endpoint == "index" and method in {"GET", "HEAD"}:
            expected_ok = response.status_code == 302 and response.headers["Location"] == "/login"
        elif method in OPEN.get(endpoint, frozenset()):
            expected_ok = response.status_code != 401
        else:
            expected_ok = response.status_code == 401 and (
                method == "HEAD" or response.get_json() == {"error": "login required"}
            )
        if not expected_ok:
            wrong.append(f"{method} {url} ({endpoint}) -> {response.status_code}")
    assert not wrong, "\n".join(wrong)
    # An unknown URL says nothing about which routes exist.
    assert client.get("/api/no-such-route").status_code == 401
    assert client.post("/api/health").status_code == 401


def test_the_open_list_is_exactly_the_spec_s(hosted: Hosted) -> None:
    assert OPEN == {
        "health": frozenset({"GET", "HEAD"}),
        "static": frozenset({"GET", "HEAD"}),
        "hosting_auth.login": frozenset({"GET", "HEAD"}),
        "hosting_auth.login_post": frozenset({"POST"}),
        "hosting_auth.logout": frozenset({"POST"}),
    }
    client = hosted.client()
    assert client.get("/api/health").status_code == 200
    assert client.get("/static/dist/favicon.svg").status_code == 200
    assert client.get("/login").status_code == 200


def test_the_media_and_art_routes_need_a_login(hosted: Hosted) -> None:
    client = hosted.client()
    for url in ("/api/art", "/api/media/images/x.png", "/api/audio/x.wav", "/story-art/scenes/bakery.jpg"):
        assert client.get(url).status_code == 401, url


def test_a_blueprint_registered_after_install_is_still_refused(hosted: Hosted) -> None:
    late = Blueprint("late", __name__)

    @late.get("/api/late")
    def late_route() -> Any:
        return jsonify({"secret": "should never be served without a login"})

    hosted.app.register_blueprint(late)
    client = hosted.client()
    assert client.get("/api/late").status_code == 401
    _, password = hosted.add()
    login(client, "alice", password)
    assert client.get("/api/late").status_code == 200


def test_a_logged_in_player_reaches_the_game(hosted: Hosted) -> None:
    _, password = hosted.add()
    client = hosted.client()
    login(client, "alice", password)
    page = client.get("/")
    assert page.status_code == 200 and b'id="root"' in page.data
    assert client.get("/api/archetypes").status_code == 200


# -- forwarded headers -----------------------------------------------------------


def test_x_forwarded_for_is_warned_about_once(
    hosted: Hosted, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from engine.hosting import gate

    monkeypatch.setattr(gate, "_FORWARDED_WARNED", False)
    client = hosted.client()
    with caplog.at_level(logging.WARNING, logger="engine.hosting.gate"):
        for _ in range(3):
            client.get("/api/health", headers={"X-Forwarded-For": "203.0.113.9"})
        client.get("/api/health")
    warnings = [r for r in caplog.records if "X-Forwarded-For" in r.getMessage()]
    assert len(warnings) == 1
    assert "hosting.trusted_proxies" in warnings[0].getMessage()


def test_forwarded_headers_are_deleted_when_no_proxy_is_trusted(hosted: Hosted) -> None:
    seen: dict[str, Any] = {}

    @hosted.app.get("/api/echo-forwarded")
    def echo() -> Any:
        from flask import request

        seen.update({k: v for k, v in request.environ.items() if k.startswith("HTTP_X_FORWARDED")})
        seen["remote"] = request.remote_addr
        return jsonify({})

    _, password = hosted.add()
    client = hosted.client()
    login(client, "alice", password)
    client.get(
        "/api/echo-forwarded",
        headers={"X-Forwarded-For": "203.0.113.9", "X-Forwarded-Host": "evil.example"},
    )
    assert seen == {"remote": "127.0.0.1"}


def test_a_trusted_proxy_s_headers_are_resolved_then_deleted(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    hosted = build(monkeypatch, tmp_path, hosting={"trusted_proxies": 1})
    try:
        seen: dict[str, Any] = {}

        @hosted.app.get("/api/echo-forwarded")
        def echo() -> Any:
            from flask import request

            seen.update({k: v for k, v in request.environ.items() if k.startswith("HTTP_X_FORWARDED")})
            seen["remote"] = request.remote_addr
            seen["scheme"] = request.scheme
            return jsonify({})

        _, password = hosted.add()
        client = hosted.client()
        login(client, "alice", password)
        client.get(
            "/api/echo-forwarded",
            base_url="http://localhost",
            headers={"X-Forwarded-For": "203.0.113.9", "X-Forwarded-Proto": "https"},
        )
        assert seen == {"remote": "203.0.113.9", "scheme": "https"}
    finally:
        teardown()


# -- what hosted mode turns off ---------------------------------------------------


def test_the_studio_is_refused_at_startup(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    try:
        with pytest.raises(HostingConfigError) as caught:
            build(monkeypatch, tmp_path, env={"CLOCKWORK_STUDIO": "1"})
        assert caught.value.key == "CLOCKWORK_STUDIO"
    finally:
        teardown()


def test_the_mcp_skills_server_is_refused_at_startup(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    try:
        with pytest.raises(HostingConfigError) as caught:
            build(monkeypatch, tmp_path, extra={"llm": {"mcp": {"enabled": True}}})
        assert caught.value.key == "llm.mcp.enabled"
        assert "llm.mcp.enabled" in str(caught.value)
    finally:
        teardown()


def test_a_server_refuses_to_start_while_adopt_runs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from engine.hosting.accounts import ADOPT_RUNNING, adopt_lock

    try:
        with adopt_lock(tmp_path / "data" / "hosting"):
            with pytest.raises(HostingConfigError) as caught:
                build(monkeypatch, tmp_path)
        assert caught.value.key == "scripts/users.py adopt"
        assert ADOPT_RUNNING in str(caught.value)
    finally:
        teardown()
    try:
        build(monkeypatch, tmp_path)  # starts once adopt has let go
    finally:
        teardown()


def test_an_invalid_hosting_block_is_refused_at_startup(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    try:
        with pytest.raises(HostingConfigError) as caught:
            build(monkeypatch, tmp_path, hosting={"expose_metrics": True})
        assert caught.value.key == "hosting.expose_metrics"
    finally:
        teardown()


def test_settings_are_read_only_hosted(hosted: Hosted, tmp_path: Path) -> None:
    from engine.api import settings

    _, password = hosted.add()
    client = hosted.client()
    login(client, "alice", password)
    got = client.get("/api/settings")
    assert got.status_code == 200 and got.get_json()["writable"] is False
    refused = client.post("/api/settings", json={"changes": {"world.tick_interval_seconds": 30}})
    assert refused.status_code == 403
    assert refused.get_json()["error"] == settings.HOSTED_REFUSAL == "Set by the server's operator."


def test_metrics_are_404_hosted(hosted: Hosted) -> None:
    _, password = hosted.add()
    client = hosted.client()
    login(client, "alice", password)
    assert client.get("/api/metrics").status_code == 404


# -- Socket.IO ------------------------------------------------------------------


def _handshake(client: Any, origin: str) -> int:
    return client.get("/socket.io/?EIO=4&transport=polling", headers={"Origin": origin}).status_code


def test_hosted_socketio_is_same_origin_only(hosted: Hosted) -> None:
    server = hosted.scene.socketio.server.eio
    assert server.cors_allowed_origins is None, "hosted CORS must be same-origin, never [] or *"
    assert server.max_http_buffer_size == 65536
    client = hosted.client()
    # Loopback on another port: the host guard lets it through (it compares
    # hosts), engineio's same-origin check refuses it.
    assert _handshake(client, "https://localhost:8080") == 400
    assert _handshake(client, "http://localhost") == 400
    assert _handshake(client, "https://localhost") == 200


def test_hosted_socketio_answers_the_public_origin(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    hosted = build(monkeypatch, tmp_path, hosting={"public_origin": "https://play.example.org"})
    try:
        server = hosted.scene.socketio.server.eio
        assert server.cors_allowed_origins == ["https://play.example.org"]
        client = hosted.client()
        assert _handshake(client, "https://play.example.org") == 200
        assert _handshake(client, "https://localhost") == 400
    finally:
        teardown()


def test_the_hosted_cors_value_is_never_empty() -> None:
    from engine.scenes.flask_scene import socketio_options

    assert socketio_options(False) == {"cors_allowed_origins": "*", "async_mode": "threading"}
    hosted = socketio_options(True)
    assert hosted["cors_allowed_origins"] != []
    assert hosted["max_http_buffer_size"] == 65536


# -- install() -------------------------------------------------------------------


def test_install_warms_the_process_before_serving(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import engine.agents.governance as governance
    import engine.game.quests as quests
    import engine.games.caches as caches
    import engine.llm.backend as backend
    import engine.llm.registry as registry
    import engine.lore.manager as lore
    import engine.telemetry.oracle as oracle

    called: list[str] = []

    class FakeBackend:
        def route_client(self) -> None:
            called.append("route_client")

    monkeypatch.setattr(caches, "warm_all_caches", lambda: called.append("warm_all_caches"))
    monkeypatch.setattr(quests, "_ensure_grammar", lambda: called.append("_ensure_grammar"))
    monkeypatch.setattr(governance, "get_governance", lambda: called.append("get_governance"))
    monkeypatch.setattr(lore, "get_lore_manager", lambda: called.append("get_lore_manager"))
    monkeypatch.setattr(backend, "get_backend", lambda: called.append("get_backend") or FakeBackend())
    monkeypatch.setattr(registry, "get_registry", lambda: called.append("get_registry"))
    monkeypatch.setattr(oracle, "get_oracle", lambda: called.append("get_oracle"))
    try:
        build(monkeypatch, tmp_path, warm=True)
    finally:
        teardown()
    assert called == [
        "warm_all_caches",
        "_ensure_grammar",
        "get_governance",
        "get_lore_manager",
        "get_backend",
        "route_client",
        "get_registry",
        "get_oracle",
    ]


def test_the_template_block_renders_only_for_a_logged_in_player(hosted: Hosted) -> None:
    assert set(hosted.scene.template_extras) == {"hosting"}
    _, password = hosted.add()
    client = hosted.client()
    login(client, "alice", password)
    page = client.get("/").data.decode("utf-8")
    line = next(l for l in page.splitlines() if 'id="root"' in l)
    assert 'action="/logout"' in line, "the block is not inline on the root line"


# -- the launcher -----------------------------------------------------------------


def test_the_launcher_warns_and_exits_1_on_a_refusal(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """
    Since v0.20.0 T12 hosted mode runs the supervisor in the foreground (its
    ``main``, stubbed here), never the scene in-process; the supervisor's own
    exit code (1 on a refusal it names) is the launcher's.
    """
    import launcher
    import engine.hosting.supervisor.__main__ as supervisor_main
    from engine.scenes import default_scene
    from tests.hosted_app import hosting_layer

    hosting_layer(monkeypatch, tmp_path)
    ran: list[Any] = []
    monkeypatch.setattr(default_scene, "run_scene", lambda **kw: ran.append(("scene", kw)))
    monkeypatch.setattr(supervisor_main, "main", lambda argv=None: ran.append(("supervisor", argv)) or 0)
    try:
        assert launcher.main(["--no-stack"]) == 0
        out = capsys.readouterr().out
        assert "WARNING: " + launcher.HOSTED_DEV_SERVER_WARNING in out
        assert ran == [("supervisor", [])]

        def refuse(argv: Any = None) -> int:
            print("Hosted mode refused to start: llm.mcp.enabled: refused for this test", file=sys.stderr)
            return 1

        monkeypatch.setattr(supervisor_main, "main", refuse)
        assert launcher.main(["--no-stack"]) == 1
        assert "llm.mcp.enabled" in capsys.readouterr().err
    finally:
        teardown()


# -- the front door's rules, enumerated (v0.20.0 T12) -----------------------------------


def test_every_front_door_rule_and_method_needs_a_login_but_its_open_list(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """
    The same enumeration at the front door (``InProcessFrontDoor``): every
    rule and method it holds -- its own pages, ``/admin`` and under it, and
    the proxy's catch-all with a sample path -- answers an anonymous request
    401 JSON (``GET /`` redirects to ``/login``), bar the open list, and NONE
    of them reaches the worker.
    """
    from engine.hosting.frontdoor.gate import OPEN as FRONT_OPEN
    from tests.hosting_instance import InProcessFrontDoor

    assert FRONT_OPEN == {
        "health": frozenset({"GET", "HEAD"}),
        "static": frozenset({"GET", "HEAD"}),
        "hosting_auth.login": frozenset({"GET", "HEAD"}),
        "hosting_auth.login_post": frozenset({"POST"}),
        "hosting_auth.logout": frozenset({"POST"}),
    }
    door = InProcessFrontDoor(monkeypatch, tmp_path).start()
    reached: list[str] = []
    worker_layer = door.hosted.app.wsgi_app

    def counting(environ: dict[str, Any], start_response: Any) -> Any:
        if "HTTP_X_CLOCKWORK_PROXY" in environ:
            reached.append(f"{environ.get('REQUEST_METHOD')} {environ.get('PATH_INFO')}")
        return worker_layer(environ, start_response)

    door.hosted.app.wsgi_app = counting
    try:
        cases = _every_rule_and_method(door.front_app)
        endpoints = {endpoint for endpoint, _, _ in cases}
        assert {"proxy", "proxy_root", "hosting_admin.overview", "hosting_admin.unknown", "frontdoor_stories.index",
                "frontdoor_stories.picker", "frontdoor_stories.choose", "hosting_auth.account_page", "health",
                "static"} <= endpoints
        client = door.front_app.test_client()
        wrong: list[str] = []
        for endpoint, method, url in cases:
            response = client.open(url, method=method)
            admin_page = (
                endpoint.startswith("hosting_admin.")
                and method in {"GET", "HEAD"}
                and not url.startswith(("/admin/api/", "/admin/static/"))
            )
            if (endpoint == "frontdoor_stories.index" and method in {"GET", "HEAD"}) or admin_page:
                # The admin panel's pages, like the game's, go to the login (T14).
                expected_ok = response.status_code == 302 and response.headers["Location"].endswith("/login")
            elif method in FRONT_OPEN.get(endpoint, frozenset()):
                expected_ok = response.status_code != 401
            else:
                expected_ok = response.status_code == 401 and (
                    method == "HEAD" or response.get_json() == {"error": "login required"}
                )
            if not expected_ok:
                wrong.append(f"{method} {url} ({endpoint}) -> {response.status_code}")
        assert not wrong, "\n".join(wrong)
        assert reached == [], reached
    finally:
        door.stop()
