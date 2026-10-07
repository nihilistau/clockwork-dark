"""
The front door, routing HTTP to the chosen story's worker (v0.20.0 T12, spec
§14.5, §6.2, §9.10).

ONE instance for the module, every process real (``tests/hosting_instance.py``):
the supervisor, two workers (``tests/probes/scripted_worker.py``: the
engine's own hosted worker, its model scripted, a probe layer counting what
the front door PROXIED to it) and the engine's own front door
(``tests/probes/frontdoor_relay.py``, whose side port lets a test stop a
story through the bus). Every child binds loopback on a port the OS picks
and runs under the suite's child sandbox.

- one login, at the front door; ``GET /`` with no story chosen goes to the
  picker; after ``POST /stories/<a>`` a request reaches worker A, after
  choosing B, worker B;
- the front door's own routes (``/login``, ``/logout``, ``/account``,
  ``/stories``, ``/api/health``, ``/admin/...``) are never proxied, and a
  request with no cookie is refused at the front door;
- a worker's redirect reaches the client unfollowed;
- THE COOKIE (spec §6.2, C4): no proxied response carries ``Set-Cookie`` for
  ``clockwork_session`` (a worker that tries is stripped); a story switch
  and a password change made while a slow proxied response is in flight
  both survive it; the worker's logout form posts to the front door;
- a stopped story answers 503 (page and JSON) once ``stories.changed`` has
  arrived, and no request asks the supervisor for the table (LAST: it stops
  a story).
"""

from __future__ import annotations

import re
import threading
from typing import Any, Iterator

import httpx
import pytest

from tests.hosting_instance import (
    SCRIPTED_WORKER,
    HostingInstance,
    choose,
    csrf_of,
    hosting_instance,
    login,
)

pytestmark = pytest.mark.process

A = "clockwork-dark"
B = "dev-story"
JOIN = 60.0

#: What the front door answers itself; never a worker.
FRONT_PATHS = ("/login", "/logout", "/account", "/stories", "/api/health", "/admin")


@pytest.fixture(scope="module")
def instance(tmp_path_factory: pytest.TempPathFactory) -> Iterator[HostingInstance]:
    yield from hosting_instance(
        tmp_path_factory,
        "frontdoor",
        stories=[A, B],
        frontdoor="real",
        worker_module=SCRIPTED_WORKER,
        supervisor={"boot_seconds": 180, "health_failures": 5},
        hosting={
            "cookie_secure": False,
            "rate_limits": {"actions_per_minute": 1000, "logins_per_minute": 1000, "logins_per_minute_all": 1000},
        },
    )


@pytest.fixture(scope="module")
def player(instance: HostingInstance) -> dict[str, str]:
    return {"name": "rowan", "password": instance.add_account("rowan")}


def _w(slug: str) -> str:
    return f"worker-{slug}"


def _client(instance: HostingInstance, player: dict[str, str], story: str = "") -> httpx.Client:
    http = instance.http()
    assert login(http, player["name"], player["password"]).status_code == 303
    if story:
        assert choose(http, story).status_code == 303
    return http


def _active(http: httpx.Client) -> str:
    response = http.get("/api/games/active")
    assert response.status_code == 200, response.text[:300]
    return str(response.json()["active"])


def _no_session_cookie(response: httpx.Response) -> None:
    cookies = [v for k, v in response.headers.multi_items() if k.lower() == "set-cookie"]
    assert not [c for c in cookies if c.split("=", 1)[0].strip() == "clockwork_session"], cookies


def test_one_login_then_the_picker_then_the_chosen_story(instance: HostingInstance, player: dict[str, str]) -> None:
    http = _client(instance, player)
    try:
        landing = http.get("/")
        assert landing.status_code in (302, 303) and landing.headers["location"] == "/stories"
        picker = http.get("/stories")
        assert picker.status_code == 200
        assert 'action="/stories/clockwork-dark"' in picker.text and 'action="/stories/dev-story"' in picker.text
        before = {s: len(instance.proxied(_w(s))) for s in (A, B)}

        assert choose(http, A).status_code == 303
        page = http.get("/")
        assert page.status_code == 200 and 'id="root"' in page.text
        assert _active(http) == A
        opened = http.post("/api/game/new", json={"seed": 1, "player_name": "Rowan"})
        assert opened.status_code == 200 and opened.json()["session_id"]
        reached_a = instance.proxied(_w(A))[before[A] :]
        assert reached_a == ["GET /", "GET /api/games/active", "POST /api/game/new"]
        assert instance.proxied(_w(B))[before[B] :] == []

        assert choose(http, B).status_code == 303
        assert _active(http) == B
        assert http.post("/api/game/new", json={"seed": 1}).status_code == 200
        assert instance.proxied(_w(B))[before[B] :] == ["GET /api/games/active", "POST /api/game/new"]
    finally:
        http.close()


def test_the_front_door_s_own_routes_are_never_proxied(instance: HostingInstance, player: dict[str, str]) -> None:
    http = _client(instance, player, A)
    anonymous = instance.http()
    try:
        assert http.get("/api/health").json() == {"status": "ok", "role": "frontdoor"}
        assert http.get("/account").status_code == 200
        assert http.get("/stories").status_code == 200
        # The admin panel (T14) refuses a player with its one fixed body.
        assert http.get("/admin").status_code == 403
        assert http.get("/admin/users").status_code == 403
        assert http.post("/admin/x", data={}).status_code == 403
        # An odd method on a front door path is the front door's too.
        assert http.put("/login").status_code == 405
        assert http.delete("/stories").status_code == 405
        # No cookie: refused at the front door, whatever the path.
        assert anonymous.get("/api/games").status_code == 401
        assert anonymous.post("/api/game/new", json={}).status_code == 401
        assert anonymous.get("/socket.io/", params={"EIO": "4", "transport": "polling"}).status_code == 401
        assert anonymous.get("/admin/x").headers["location"] == "/login"
        assert anonymous.post("/admin/x").status_code == 401
        assert anonymous.get("/").headers["location"] == "/login"
        page = http.get("/account")
        assert http.post("/logout", data={"csrf": csrf_of(page.text)}).status_code == 303
    finally:
        http.close()
        anonymous.close()
    for slug in (A, B):
        for line in instance.proxied(_w(slug)):
            path = line.split(" ", 1)[1]
            assert not any(path == p or path.startswith(p + "/") for p in FRONT_PATHS), line


def test_a_request_without_a_cookie_never_reaches_a_worker(instance: HostingInstance) -> None:
    before = {s: list(instance.proxied(_w(s))) for s in (A, B)}
    anonymous = instance.http()
    try:
        for path in ("/api/games", "/api/game/state", "/socket.io/?EIO=4&transport=polling", "/static/x.js"):
            assert anonymous.get(path).status_code == 401
        assert anonymous.post("/api/game/choice", json={}).status_code == 401
    finally:
        anonymous.close()
    assert {s: list(instance.proxied(_w(s))) for s in (A, B)} == before


def test_a_worker_s_redirect_reaches_the_client_unfollowed(instance: HostingInstance, player: dict[str, str]) -> None:
    http = _client(instance, player, A)
    try:
        answer = http.get("/probe/redirect")
        assert answer.status_code == 302 and answer.headers["location"] == "/probe/elsewhere"
        assert instance.proxied(_w(A))[-1] == "GET /probe/redirect"
        assert "GET /probe/elsewhere" not in instance.proxied(_w(A))
    finally:
        http.close()


def test_no_proxied_response_carries_the_session_cookie(instance: HostingInstance, player: dict[str, str]) -> None:
    """A worker that tries to write ``clockwork_session`` is stripped; the login stands."""
    http = _client(instance, player, A)
    evil = instance.control / f"{_w(A)}.evil"
    evil.write_text("1", encoding="utf-8")
    try:
        for path in ("/", "/api/games", "/api/games/active"):
            response = http.get(path)
            assert response.status_code == 200, (path, response.status_code)
            _no_session_cookie(response)
        assert http.cookies.get("clockwork_session") not in (None, "evil")
        assert _active(http) == A
    finally:
        evil.unlink()
        http.close()


class _Slow:
    """``worker-<slug>`` holds a ``GET path`` until released; the request runs on its own thread."""

    def __init__(self, instance: HostingInstance, slug: str, http: httpx.Client, path: str) -> None:
        self.instance = instance
        self.process = _w(slug)
        self.http = http
        self.path = path
        self.answers: list[httpx.Response] = []
        for suffix in ("entered", "release"):
            (instance.control / f"{self.process}.{suffix}").unlink(missing_ok=True)
        (instance.control / f"{self.process}.slow").write_text(path, encoding="utf-8")
        self.thread = threading.Thread(target=lambda: self.answers.append(http.get(path)), name="slow-proxied")

    def __enter__(self) -> "_Slow":
        self.thread.start()
        entered = self.instance.control / f"{self.process}.entered"
        self.instance.until(entered.exists, JOIN, "the slow request in flight at the worker")
        return self

    def release(self) -> httpx.Response:
        (self.instance.control / f"{self.process}.release").write_text("1", encoding="utf-8")
        self.thread.join(JOIN)
        assert not self.thread.is_alive(), "the slow request never finished"
        return self.answers[0]

    def __exit__(self, *_exc: Any) -> None:
        (self.instance.control / f"{self.process}.release").write_text("1", encoding="utf-8")
        self.thread.join(JOIN)
        for suffix in ("slow", "entered", "release"):
            (self.instance.control / f"{self.process}.{suffix}").unlink(missing_ok=True)


def test_a_story_switch_survives_a_slow_response_in_flight(instance: HostingInstance, player: dict[str, str]) -> None:
    """
    C4: ``POST /stories/B`` lands while a proxied response for story A is
    still in flight. That response carries no cookie (the front door writes
    it only for a request that changed the session), so the switch stands.
    """
    http = _client(instance, player, A)
    try:
        with _Slow(instance, A, http, "/api/games") as slow:
            assert choose(http, B).status_code == 303
            answer = slow.release()
        assert answer.status_code == 200
        _no_session_cookie(answer)
        assert _active(http) == B
    finally:
        http.close()


def test_a_password_change_survives_a_slow_response_in_flight(instance: HostingInstance) -> None:
    """
    C4: the new epoch's cookie is issued to this window while a proxied
    response from before the change is in flight; the window stays logged in.
    """
    name = "sage"
    password = instance.add_account(name)
    http = instance.http()
    assert login(http, name, password).status_code == 303
    assert choose(http, A).status_code == 303
    try:
        with _Slow(instance, A, http, "/api/games") as slow:
            page = http.get("/account")
            new = password + "-new"
            changed = http.post(
                "/account", data={"csrf": csrf_of(page.text), "current": password, "new": new, "confirm": new}
            )
            assert changed.status_code == 200, changed.text[:300]
            answer = slow.release()
        # The slow request reached the worker's gate only after the change,
        # carrying the cookie it was sent with: an epoch retired meanwhile.
        # It is refused -- and, like every proxied answer, writes no cookie.
        assert answer.status_code == 401
        _no_session_cookie(answer)
        assert http.get("/api/games").status_code == 200, "the password change's own window was logged out"
        assert _active(http) == A
    finally:
        http.close()


def test_the_worker_s_logout_form_posts_to_the_front_door(instance: HostingInstance, player: dict[str, str]) -> None:
    http = _client(instance, player, A)
    try:
        page = http.get("/")
        assert page.status_code == 200
        line = next(l for l in page.text.splitlines() if 'action="/logout"' in l)
        token = re.search(r'name="csrf" value="([^"]+)"', line).group(1)  # type: ignore[union-attr]
        before = list(instance.proxied(_w(A)))
        out = http.post("/logout", data={"csrf": token})
        assert out.status_code == 303 and out.headers["location"] == "/login"
        assert instance.proxied(_w(A)) == before, "the logout reached a worker"
        assert http.get("/api/games").status_code == 401
    finally:
        http.close()


def test_a_stopped_story_answers_503_without_asking_the_supervisor(
    instance: HostingInstance, player: dict[str, str]
) -> None:
    """LAST in the module: it stops story B."""
    http = _client(instance, player, B)
    try:
        op = instance.call("stories.stop", {"slug": B})
        assert op["ok"], op
        assert instance.wait_op(op["result"]["op_id"], 60)["status"] == "done"
        instance.until(lambda: http.get("/api/games").status_code == 503, 30, "the front door told B stopped")
        mark = instance.mark()
        page = http.get("/")
        assert page.status_code == 503
        assert "stopped by the operator" in page.text
        assert http.get("/api/games").json() == {"error": "story unavailable"}
        assert http.post("/api/game/new", json={}).status_code == 503
        # Story A is still served.
        assert choose(http, A).status_code == 303
        assert _active(http) == A
        assert not [l for l in instance.lines[mark:] if "operation=stories.list" in l], (
            "a request asked the supervisor for the story table"
        )
    finally:
        http.close()

