"""
Who reaches the admin panel (v0.20.0 T14, spec §14.7, §14.5, §9.10).

Every rule under ``/admin`` in the front door's URL map, times every method it
accepts (bar ``HEAD`` and ``OPTIONS``), is driven through the engine's own
front door (``tests/hosting_instance.py::AdminDoor``, in this process, with a
"worker" that only counts what reaches it):

- anonymous: 401 ``{"error": "login required"}``, or the login redirect for a
  page ``GET``;
- logged in, not an admin: 403 with ONE fixed body, byte for byte the same on
  every rule;
- an admin whose re-auth is stale: the re-auth page for a page ``GET``, 401
  ``{"error": "reauth required"}`` otherwise;
- an unknown ``/admin/x``: answered the same way (anonymous 401, non-admin
  403, admin 404) and never proxied (the worker's count);
- every ``POST``: refused without the CSRF token, with an old epoch's token
  and with a foreign ``Origin``; and the admin actions bucket;
- every response carries the five headers;
- a worker's URL map has no ``/admin`` rule;
- the canary: a route added under ``/admin`` after the panel is built is
  still refused, and without the guard it would not be.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Iterator

import pytest

from tests.hosting_instance import AdminDoor, csrf_of

# In-process loopback servers: the hybrid run's serial phase (tests/tiers.py).
pytestmark = pytest.mark.loopback

#: What a non-admin is told on every rule.
FORBIDDEN_BODY = b'{"error":"forbidden"}\n'

#: A path parameter's stand-in, by name.
_ARG_RE = re.compile(r"<(?:[a-z]+:)?([a-z_]+)>")


@pytest.fixture
def door(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[AdminDoor]:
    instance = AdminDoor(monkeypatch, tmp_path)
    instance.start()
    try:
        yield instance
    finally:
        instance.stop()


def _cases(door: AdminDoor, target_id: str = "u_000000000000") -> list[tuple[str, str, str]]:
    """``(endpoint, method, url)`` for every /admin rule and method (bar HEAD, OPTIONS)."""
    found = []
    for rule in door.app.url_map.iter_rules():
        if not (rule.rule == "/admin" or rule.rule.startswith("/admin/")):
            continue

        def fill(match: re.Match[str]) -> str:
            name = match.group(1)
            if name == "account_id":
                return target_id
            if name == "filename":
                return "admin.css"
            return "x/y"

        url = _ARG_RE.sub(fill, rule.rule)
        for method in sorted((rule.methods or set()) - {"HEAD", "OPTIONS"}):
            found.append((rule.endpoint, method, url))
    assert len(found) >= 12, found
    return found


def _page(method: str, url: str) -> bool:
    return method == "GET" and not url.startswith(("/admin/api/", "/admin/static/"))


def _headers_ok(response: Any) -> None:
    from engine.hosting.admin.guard import HEADERS

    for name, value in HEADERS.items():
        assert response.headers.get(name) == value, (name, response.status_code)


def test_the_panel_s_rules_are_the_ones_this_file_expects(door: AdminDoor) -> None:
    """A rule added to the panel shows up here (and so in every test below)."""
    rules = {rule.rule for rule in door.app.url_map.iter_rules() if rule.rule.startswith("/admin")}
    assert {
        "/admin",
        "/admin/<path:rest>",
        "/admin/reauth",
        "/admin/users",
        "/admin/audit",
        "/admin/api/overview.json",
        "/admin/static/<path:filename>",
        "/admin/users/<account_id>/reset",
        "/admin/users/<account_id>/disable",
        "/admin/users/<account_id>/enable",
        "/admin/users/<account_id>/grant-admin",
        "/admin/users/<account_id>/revoke-admin",
        "/admin/users/<account_id>/delete",
        # v0.20.0 T15 (pinned in fix round 1, M5):
        "/admin/sessions",
        "/admin/sessions/end",
        "/admin/api/sessions.json",
        "/admin/saves",
        "/admin/stories",
        "/admin/stories/start",
        "/admin/stories/stop",
        "/admin/stories/restart",
        "/admin/api/stories.json",
        # v0.20.0 T16:
        "/admin/model",
        "/admin/api/health.json",
        "/admin/queue",
        "/admin/api/queue.json",
        # v0.20.0 T17:
        "/admin/metrics",
        "/admin/api/metrics.json",
        "/admin/errors",
        "/admin/api/errors.json",
        "/admin/errors/find",  # T17 fix round 1 (M5)
    } <= rules


def test_anonymous_is_refused_on_every_rule_and_method(door: AdminDoor) -> None:
    client = door.client()
    for endpoint, method, url in _cases(door) + [("unknown", "GET", "/admin/x"), ("unknown", "POST", "/admin/x")]:
        response = client.open(url, method=method)
        _headers_ok(response)
        if _page(method, url):
            assert response.status_code == 302 and response.headers["Location"].endswith("/login"), (method, url)
        else:
            assert response.status_code == 401, (endpoint, method, url, response.status_code)
            assert response.get_json() == {"error": "login required"}
    assert door.reached == [], "an anonymous /admin request reached the worker"


def test_a_non_admin_gets_one_fixed_refusal_everywhere(door: AdminDoor) -> None:
    door.add("player")
    target = door.add("victim")
    client = door.login("player")
    bodies = set()
    for _endpoint, method, url in _cases(door, target.id) + [("unknown", "GET", "/admin/x")]:
        response = client.open(url, method=method, data={"csrf": "x"} if method != "GET" else None)
        _headers_ok(response)
        assert response.status_code == 403, (method, url, response.status_code)
        bodies.add(response.get_data())
    assert bodies == {FORBIDDEN_BODY}, bodies
    assert door.accounts.get(target.id) is not None and not door.accounts.get(target.id).disabled
    assert door.reached == []


def test_a_stale_re_auth_is_sent_to_the_re_auth_page_or_refused(door: AdminDoor) -> None:
    other = door.add("other")
    client = door.admin()
    with client.session_transaction() as session:
        session["admin_at"] = time.time() - 16 * 60  # past reauth_minutes (15)
    exempt = {"hosting_admin.reauth", "hosting_admin.reauth_post", "hosting_admin.static"}
    for endpoint, method, url in _cases(door, other.id):
        if endpoint in exempt:
            continue
        response = client.open(url, method=method, data={"csrf": "x"} if method != "GET" else None)
        _headers_ok(response)
        if _page(method, url):
            assert response.status_code == 303, (method, url, response.status_code)
            assert response.headers["Location"].startswith("/admin/reauth?next=")
        else:
            assert response.status_code == 401 and response.get_json() == {"error": "reauth required"}, (method, url)
    # Never re-authenticated at all: the same.
    fresh = door.login("root")
    assert fresh.get("/admin").status_code == 303
    assert door.accounts.get(other.id) is not None and not door.accounts.get(other.id).disabled


def test_an_unknown_admin_path_meets_the_guard_then_404_and_is_never_proxied(door: AdminDoor) -> None:
    door.add("player")
    anonymous = door.client()
    assert anonymous.get("/admin/x").status_code == 302
    assert anonymous.post("/admin/x").status_code == 401
    assert anonymous.delete("/admin/x/y").status_code == 401
    player = door.login("player")
    assert player.get("/admin/x").get_data() == FORBIDDEN_BODY
    admin = door.admin()
    for method in ("GET", "POST"):
        response = admin.open("/admin/no/such/page", method=method, data={"csrf": door.token(admin)})
        assert response.status_code == 404, method
        _headers_ok(response)
    # The proxy's own reserved answer for "/admin/" is the front door's too.
    assert admin.get("/admin/").status_code in (404, 405)
    assert door.reached == [], f"an /admin path reached the worker: {door.reached}"
    # ... while an ordinary path does, so the counter counts.
    stories = admin.get("/stories")
    token = csrf_of(stories.get_data(as_text=True))
    assert admin.post(f"/stories/{door.story}", data={"csrf": token}).status_code == 303
    assert admin.get("/api/games/active").status_code == 200
    assert door.reached == ["GET /api/games/active"]


def _post_cases(door: AdminDoor, target_id: str) -> list[tuple[str, str]]:
    return [(endpoint, url) for endpoint, method, url in _cases(door, target_id) if method == "POST"]


def test_every_post_needs_the_token_of_this_epoch_and_this_site(door: AdminDoor) -> None:
    other = door.add("other")
    client = door.admin()
    old_token = door.token(client)
    before = door.accounts.path.read_bytes()
    posts = _post_cases(door, other.id)
    assert len(posts) >= 8
    for _endpoint, url in posts:
        missing = client.post(url, data={"name": "newcomer", "confirm": "other", "mode": "purge"})
        assert missing.status_code == 403 and missing.get_json()["error"].startswith("this form has expired"), url
        _headers_ok(missing)
        form = {"csrf": old_token, "name": "newcomer", "confirm": "other", "mode": "purge"}
        # Another site: refused before Flask, by the front door's host guard.
        foreign = client.post(url, data=form, headers={"Origin": "https://evil.example"})
        assert foreign.status_code == 403, url
        # Another origin on this host (a port the host guard lets by): the
        # panel's own Origin check (T7's rule, scheme and port included).
        sibling = client.post(url, data=form, headers={"Origin": "http://localhost:9999"})
        assert sibling.status_code == 403 and sibling.get_json() == {"error": "cross-site request refused"}, url
        _headers_ok(sibling)
    # A password change (a new epoch) retires every token issued before it.
    account = client.get("/account")
    changed = client.post(
        "/account",
        data={
            "csrf": csrf_of(account.get_data(as_text=True)),
            "current": door.passwords["root"],
            "new": "a-brand-new-password",
            "confirm": "a-brand-new-password",
        },
    )
    assert changed.status_code == 200
    assert door.token(client) != old_token
    for _endpoint, url in posts:
        stale = client.post(url, data={"csrf": old_token, "name": "newcomer", "confirm": "other", "mode": "purge"})
        assert stale.status_code == 403, url
    del before  # the password change itself rewrote users.json; what matters is below
    assert door.accounts.by_name("newcomer") is None and door.accounts.get(other.id) is not None
    assert not door.accounts.get(other.id).disabled


def test_the_admin_actions_bucket(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    door = AdminDoor(monkeypatch, tmp_path, hosting={"rate_limits": {"admin_actions_per_minute": 3}})
    door.start()
    try:
        client = door.admin()  # the re-auth POST spends one
        token = door.token(client)
        codes = [client.post("/admin/users", data={"csrf": token, "name": "X"}).status_code for _ in range(3)]
        assert codes == [400, 400, 429], codes
        refused = client.post("/admin/users", data={"csrf": token, "name": "fine-name"})
        assert refused.status_code == 429 and "Too many admin actions" in refused.get_json()["error"]
        _headers_ok(refused)
        assert door.accounts.by_name("fine-name") is None
        # Another admin has a bucket of their own.
        other = door.admin("other-admin")
        assert other.post("/admin/users", data={"csrf": door.token(other), "name": "fine-name"}).status_code == 303
    finally:
        door.stop()


def test_the_error_lookup_spends_the_admin_actions_bucket(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """
    v0.20.0 T18 (T17 re-review N3): ``GET /admin/errors/find`` asks the
    supervisor's store for each lookup, so a script cannot repeat it without
    limit: it spends the same bucket as the panel's actions.
    """
    door = AdminDoor(monkeypatch, tmp_path, hosting={"rate_limits": {"admin_actions_per_minute": 3}})
    door.start()
    try:
        client = door.admin()  # the re-auth POST spends one
        codes = [client.get("/admin/errors/find", query_string={"ref": "3fa9c2e1"}).status_code for _ in range(3)]
        assert codes[-1] == 429 and 429 not in codes[:2], codes
        refused = client.get("/admin/errors/find", query_string={"ref": "3fa9c2e1"})
        assert refused.status_code == 429 and "Too many admin actions" in refused.get_json()["error"]
    finally:
        door.stop()


def test_a_worker_has_no_admin_rule(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The panel is the front door's; a hosted game app (a worker) mounts none of it."""
    from tests import hosted_app

    hosted = hosted_app.build(monkeypatch, tmp_path)
    try:
        rules = [rule.rule for rule in hosted.app.url_map.iter_rules()]
        assert not [rule for rule in rules if rule == "/admin" or rule.startswith("/admin/")], rules
        assert "hosting_admin" not in hosted.app.blueprints
    finally:
        hosted_app.teardown()


def test_the_canary_a_late_admin_route_is_still_refused_and_the_guard_is_what_refuses(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """
    A route added under /admin after the panel is built -- by anyone, on the
    app itself -- is covered: the guard is keyed by the path. And the guard is
    load-bearing: with it taken out, the same route is served to anyone.
    """
    from engine.hosting.admin.guard import guard

    door = AdminDoor(monkeypatch, tmp_path)
    door.start()
    try:
        door.app.add_url_rule("/admin/late", "late", lambda: "the late route's secret", methods=["GET", "POST"])
        door.add("player")
        assert door.client().get("/admin/late").status_code == 302
        assert door.client().post("/admin/late").status_code == 401
        assert door.login("player").get("/admin/late").get_data() == FORBIDDEN_BODY
        hooks = door.app.before_request_funcs[None]
        assert guard in hooks
        hooks.remove(guard)
        try:
            exposed = door.client().get("/admin/late")
            assert exposed.status_code == 200 and b"secret" in exposed.get_data()
        finally:
            hooks.append(guard)
        assert door.client().get("/admin/late").status_code == 302
    finally:
        door.stop()


@pytest.mark.parametrize(
    "target",
    [
        "/admin/\r\nX-Evil: 1",
        "/admin/users\n",
        "/admin/\x00",
        "/admin/\x1f",
        "/admin/\x7f",
        "/admin/a b",
        "/admin/é",
        "//evil.example/admin",
        "https://evil.example/admin",
        "/admin\\..\\x",
        "/stories",
        "/administrator",
    ],
)
def test_the_re_auth_next_refuses_anything_but_a_plain_admin_path(door: AdminDoor, target: str) -> None:
    """Fix round 1, M1: on 75791db a CR or LF passed and the redirect raised (a 500)."""
    from engine.hosting.admin.guard import safe_next

    assert safe_next(target) == "/admin"
    assert safe_next("/admin/users?page=2") == "/admin/users?page=2"
    client = door.admin()
    page = client.get("/admin/reauth")
    answer = client.post(
        "/admin/reauth",
        data={"csrf": csrf_of(page.get_data(as_text=True)), "password": door.passwords["root"], "next": target},
    )
    assert answer.status_code == 303 and answer.headers["Location"] == "/admin"


def test_the_admin_pages_render_for_an_admin_with_no_javascript(door: AdminDoor) -> None:
    """Every page a GET reaches works as served: the forms are plain POSTs, nothing needs the script."""
    other = door.add("other")
    client = door.admin()
    for url in ("/admin", "/admin/users", "/admin/audit", "/admin/audit?page=2&action=account.create",
                "/admin/reauth", "/admin/api/overview.json", "/admin/static/admin.css", "/admin/static/admin.js"):
        response = client.get(url)
        assert response.status_code == 200, url
        _headers_ok(response)
    users = client.get("/admin/users").get_data(as_text=True)
    assert f'action="/admin/users/{other.id}/disable"' in users and 'method="post"' in users
    assert "style=" not in users and "<script>" not in users, "the CSP allows neither inline styles nor scripts"
    overview = json.loads(client.get("/admin/api/overview.json").get_data(as_text=True))
    assert overview == {
        "stories": [{"slug": door.story, "state": "ready"}],
        "accounts": 2,
        "admins": 1,
        "disabled": 0,
    }
