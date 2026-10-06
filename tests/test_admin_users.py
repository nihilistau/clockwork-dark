"""
The admin panel's Users page (v0.20.0 T14, spec §14.6, §14.8, §14.11).

Through the engine's own front door (``tests/hosting_instance.py::AdminDoor``):

- each action's effect on ``users.json``, and its ``started`` and outcome
  audit rows, sharing a ``ref``;
- a generated password travels ONLY in the body of the response to its own
  ``POST``: no ``Location``, no flash, not in the session cookie (decoded),
  not in any URL the page links, in no later response, no log record and no
  audit line;
- ``must_change``: the front door sends such an account to ``/account`` (403
  JSON elsewhere), ``POST /account`` clears it, and a worker treats it as
  logged out;
- the self and last-admin guards, and two admins revoking each other at
  once (two threads, a ``Barrier``): exactly one succeeds, one admin remains;
- a role change drops the demoted admin's next request;
- delete, keeping or purging the account's folder;
- with the audit append failing, every action is refused and ``users.json``
  is unchanged.
"""

from __future__ import annotations

import json
import logging
import re
import threading
from pathlib import Path
from typing import Any, Iterator

import pytest

from tests.hosting_instance import AdminDoor, csrf_of

JOIN = 30.0

#: The one-time password on its page.
_ONCE_RE = re.compile(r'<p class="secret"><code>([^<]+)</code></p>')


@pytest.fixture
def door(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[AdminDoor]:
    instance = AdminDoor(monkeypatch, tmp_path)
    instance.start()
    try:
        yield instance
    finally:
        instance.stop()


def _rows(door: AdminDoor) -> list[dict[str, Any]]:
    path = door.data_dir / "hosting" / "audit.jsonl"
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _post(door: AdminDoor, client: Any, url: str, **form: str) -> Any:
    return client.post(url, data={"csrf": door.token(client), **form})


def _pair(rows: list[dict[str, Any]], action: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """The last started/outcome pair of ``action``, checked to share a ref."""
    mine = [row for row in rows if row["action"] == action]
    started, outcome = mine[-2], mine[-1]
    assert started["result"] == "started" and outcome["ref"] == started["ref"], mine
    return started, outcome


def _once(response: Any) -> str:
    found = _ONCE_RE.search(response.get_data(as_text=True))
    assert found, response.get_data(as_text=True)[:400]
    return found.group(1)


def _shown(client: Any, posted: Any) -> tuple[str, Any]:
    """Follow a create's or reset's 303 to the page that shows the password: ``(password, that page)``."""
    assert posted.status_code == 303 and posted.headers["Location"] == "/admin/users/once", posted.status_code
    page = client.get("/admin/users/once")
    assert page.status_code == 200
    return _once(page), page


def _session_text(door: AdminDoor, response: Any, client: Any) -> str:
    """Every Set-Cookie of ``response``, and the client's session cookie, decoded."""
    serializer = door.app.session_interface.get_signing_serializer(door.app)
    texts = [value for name, value in response.headers.items() if name.lower() == "set-cookie"]
    cookie = client.get_cookie("clockwork_session")
    if cookie is not None:
        texts.append(json.dumps(serializer.loads(cookie.value)))
    return "\n".join(texts)


# -- create and reset: the password once ----------------------------------------------


def test_create_shows_a_one_time_password_once_and_nowhere_else(
    door: AdminDoor, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    client = door.admin()
    posted = _post(door, client, "/admin/users", name="bob")
    password, response = _shown(client, posted)
    assert len(password) >= 10
    assert password not in posted.get_data(as_text=True), "the POST's own answer carries no password"
    bob = door.accounts.by_name("bob")
    assert bob is not None and bob.must_change and not bob.admin
    assert door.accounts.verify("bob", password) is not None
    # Nowhere but that one page.
    for answer in (posted, response):
        assert password not in "\n".join(f"{k}: {v}" for k, v in answer.headers.items())
        assert password not in _session_text(door, answer, client)
    links = re.findall(r'(?:href|action|src)="([^"]*)"', response.get_data(as_text=True))
    assert links and not [link for link in links if password in link]
    # Shown ONCE: a reload says so, and shows nothing.
    reload = client.get("/admin/users/once")
    assert reload.status_code == 200 and "Already shown" in reload.get_data(as_text=True)
    later = [client.get(url) for url in ("/admin", "/admin/users", "/admin/audit", "/admin/api/overview.json")]
    assert not [r for r in later + [reload] if password in r.get_data(as_text=True)]
    assert password not in caplog.text
    assert password not in (door.data_dir / "hosting" / "audit.jsonl").read_text(encoding="utf-8")
    assert password not in door.accounts.path.read_text(encoding="utf-8")
    started, outcome = _pair(_rows(door), "account.create")
    assert started["target"] == "" and started["detail"] == {"name": "bob"}
    assert (outcome["result"], outcome["target"]) == ("ok", bob.id)
    assert started["actor"] == door.accounts.by_name("root").id and started["actor_name"] == "root"


def test_create_refuses_a_bad_or_taken_name_with_one_refused_row(door: AdminDoor) -> None:
    client = door.admin()
    door.add("taken")
    before = door.accounts.path.read_bytes()
    assert _post(door, client, "/admin/users", name="Not A Name").status_code == 400
    assert _post(door, client, "/admin/users", name="taken").status_code == 409
    assert door.accounts.path.read_bytes() == before
    rows = [row for row in _rows(door) if row["action"] == "account.create"]
    assert [row["result"] for row in rows] == ["refused", "refused"]


def test_reset_generates_a_password_ends_logins_and_sets_must_change(
    door: AdminDoor, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    bob = door.add("bob")
    bob_client = door.login("bob")
    client = door.admin()
    posted = _post(door, client, f"/admin/users/{bob.id}/reset")
    password, response = _shown(client, posted)
    after = door.accounts.get(bob.id)
    assert after.must_change and after.epoch == bob.epoch + 1
    assert door.accounts.verify("bob", door.passwords["bob"]) is None
    assert door.accounts.verify("bob", password) is not None
    assert bob_client.get("/stories").status_code == 401, "the old login survived a reset"
    assert password not in caplog.text and password not in _session_text(door, response, client)
    started, outcome = _pair(_rows(door), "account.reset_password")
    assert started["target"] == outcome["target"] == bob.id and outcome["result"] == "ok"
    assert password not in json.dumps(_rows(door))
    # Fix round 1, M3: reloading the page never runs the reset again.
    for _ in range(2):
        reload = client.get("/admin/users/once")
        assert "Already shown" in reload.get_data(as_text=True)
    assert door.accounts.get(bob.id).epoch == after.epoch
    assert door.accounts.verify("bob", password) is not None
    assert len([r for r in _rows(door) if r["action"] == "account.reset_password"]) == 2


def test_two_resets_in_two_tabs_each_keep_their_password(door: AdminDoor) -> None:
    """
    Fix round 2, N5: on ab77837 the session held ONE token, so a second
    reset (another tab) before the first page loaded orphaned the first
    password. Each POST now keeps its own token; each GET shows one, once.
    """
    bob, carol = door.add("bob"), door.add("carol")
    client = door.admin()
    token = door.token(client)
    for account in (bob, carol):
        posted = client.post(f"/admin/users/{account.id}/reset", data={"csrf": token})
        assert posted.status_code == 303
    first = _once(client.get("/admin/users/once"))
    second = _once(client.get("/admin/users/once"))
    assert first != second
    assert door.accounts.verify("bob", first) is not None or door.accounts.verify("bob", second) is not None
    assert door.accounts.verify("carol", first) is not None or door.accounts.verify("carol", second) is not None
    assert {door.accounts.verify("bob", p) is not None for p in (first, second)} == {True, False}
    assert "Already shown" in client.get("/admin/users/once").get_data(as_text=True)


def test_a_waiting_password_is_only_its_admin_s_and_lives_in_memory(door: AdminDoor) -> None:
    """Fix round 1, M3: another admin's session cannot take it; the store is memory, keyed by an unguessable token."""
    from engine.hosting.admin.guard import admin_state
    from engine.hosting.admin.users import ONCE_KEY

    root = door.admin()
    other = door.admin("other-admin")
    posted = _post(door, root, "/admin/users", name="bob")
    assert posted.status_code == 303
    with root.session_transaction() as session:
        (token,) = session[ONCE_KEY]
    assert len(token) >= 40
    with other.session_transaction() as session:
        session[ONCE_KEY] = [token]
    stolen = other.get("/admin/users/once")
    assert "Already shown" in stolen.get_data(as_text=True)
    assert len(admin_state(door.app).shown) == 1, "another admin's attempt must not consume it"
    password, _page = _shown(root, posted)
    assert door.accounts.verify("bob", password) is not None
    assert len(admin_state(door.app).shown) == 0
    for path in door.data_dir.rglob("*"):
        if path.is_file() and path.suffix != ".lock":  # a held lock file cannot be read on Windows
            assert password.encode() not in path.read_bytes(), f"the password reached {path}"


# -- must_change, at both doors ------------------------------------------------------------


def test_must_change_reaches_only_the_account_page_until_it_is_changed(door: AdminDoor) -> None:
    client = door.admin()
    password, _page = _shown(client, _post(door, client, "/admin/users", name="newbie"))
    newbie = door.client()
    page = newbie.get("/login")
    logged = newbie.post(
        "/login", data={"csrf": csrf_of(page.get_data(as_text=True)), "name": "newbie", "password": password}
    )
    assert logged.status_code == 303 and logged.headers["Location"].endswith("/account")
    for url in ("/", "/stories", "/admin", "/admin/users"):
        found = newbie.get(url)
        assert found.status_code in (303, 403), url
        if found.status_code == 303:
            assert found.headers["Location"].endswith("/account"), url
    assert newbie.get("/api/games/active").status_code == 403
    assert newbie.get("/api/games/active").get_json() == {"error": "password change required"}
    assert newbie.post("/api/game/new", json={}).status_code == 403
    assert door.reached == [], "a must-change account reached the worker"
    account = newbie.get("/account")
    assert account.status_code == 200 and "one-time password" in account.get_data(as_text=True).lower()
    # Fix round 1, M2: the one-time password cannot be kept as the new one.
    same = newbie.post(
        "/account",
        data={
            "csrf": csrf_of(account.get_data(as_text=True)),
            "current": password,
            "new": password,
            "confirm": password,
        },
    )
    assert same.status_code == 400 and "different from your current one" in same.get_data(as_text=True)
    assert door.accounts.by_name("newbie").must_change
    assert door.accounts.verify("newbie", password) is not None
    changed = newbie.post(
        "/account",
        data={
            "csrf": csrf_of(account.get_data(as_text=True)),
            "current": password,
            "new": "my-own-password-1",
            "confirm": "my-own-password-1",
        },
    )
    assert changed.status_code == 200
    assert not door.accounts.by_name("newbie").must_change
    assert newbie.get("/stories").status_code == 200


def test_a_worker_treats_must_change_as_logged_out(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The worker's own gate (here a hosted game app): logged out, bar its account page."""
    from tests import hosted_app

    hosted = hosted_app.build(monkeypatch, tmp_path, hosting={"cookie_secure": False})
    try:
        _account, password = hosted.state.accounts.create_with_generated_password("newbie")
        client = hosted.app.test_client()
        logged = hosted_app.login(client, "newbie", password, base_url="http://localhost")
        assert logged.status_code == 303 and logged.headers["Location"].endswith("/account")
        for url in ("/api/games/active", "/api/saves"):
            assert client.get(url, base_url="http://localhost").status_code == 401, url
        assert client.get("/", base_url="http://localhost").status_code == 302
        assert client.get("/account", base_url="http://localhost").status_code == 200
        socket = hosted.scene.socketio.test_client(hosted.app, flask_test_client=client)
        assert not socket.is_connected()
    finally:
        hosted_app.teardown()


# -- disable, enable, the role --------------------------------------------------------------


def test_disable_and_enable(door: AdminDoor) -> None:
    bob = door.add("bob")
    bob_client = door.login("bob")
    client = door.admin()
    done = _post(door, client, f"/admin/users/{bob.id}/disable")
    # POST-redirect-GET (T15 fix round 1, M6): the note shows once on the page.
    assert done.status_code == 303 and done.headers["Location"] == "/admin/users"
    page = client.get("/admin/users").get_data(as_text=True)
    assert "Disabled bob" in page and "Disabled bob" not in client.get("/admin/users").get_data(as_text=True)
    assert door.accounts.get(bob.id).disabled and door.accounts.get(bob.id).epoch == bob.epoch + 1
    assert bob_client.get("/stories").status_code == 401
    started, outcome = _pair(_rows(door), "account.disable")
    assert outcome["result"] == "ok" and outcome["target"] == bob.id
    assert _post(door, client, f"/admin/users/{bob.id}/enable").status_code == 303
    assert not door.accounts.get(bob.id).disabled
    assert _pair(_rows(door), "account.enable")[1]["result"] == "ok"
    assert client.post(f"/admin/users/u_0123456789ab/disable", data={"csrf": door.token(client)}).status_code == 404


def test_grant_and_revoke_admin_and_the_demoted_admin_is_dropped_at_once(door: AdminDoor) -> None:
    bob = door.add("bob")
    client = door.admin()
    assert _post(door, client, f"/admin/users/{bob.id}/grant-admin").status_code == 303
    assert door.accounts.get(bob.id).admin
    _started, granted = _pair(_rows(door), "account.set_admin")
    assert granted["detail"] == {"admin": True} and granted["result"] == "ok"
    bob_admin = door.admin("bob")
    assert bob_admin.get("/admin/users").status_code == 200
    assert _post(door, client, f"/admin/users/{bob.id}/revoke-admin").status_code == 303
    assert not door.accounts.get(bob.id).admin
    # The role change bumped the epoch: bob's very next request is logged out.
    assert bob_admin.get("/admin/users").status_code == 302
    assert bob_admin.get("/admin/api/overview.json").status_code == 401


def test_the_self_guards_refuse_with_one_refused_row(door: AdminDoor) -> None:
    client = door.admin()
    root = door.accounts.by_name("root")
    before = door.accounts.path.read_bytes()
    for action, url, form in (
        ("account.disable", f"/admin/users/{root.id}/disable", {}),
        ("account.set_admin", f"/admin/users/{root.id}/revoke-admin", {}),
        ("account.delete", f"/admin/users/{root.id}/delete", {"mode": "keep", "confirm": "root"}),
    ):
        response = _post(door, client, url, **form)
        assert response.status_code == 409, url
        assert "own account" in response.get_data(as_text=True)
        assert _rows(door)[-1]["action"] == action and _rows(door)[-1]["result"] == "refused"
    assert door.accounts.path.read_bytes() == before


def test_two_admins_revoking_each_other_at_once_leave_exactly_one(door: AdminDoor) -> None:
    """Through the panel: one succeeds; the other is refused (or already logged out)."""
    from engine.hosting.accounts import LastAdmin

    alice = door.add("alice", admin=True)
    bob = door.add("bob", admin=True)
    clients = {"alice": door.admin("alice"), "bob": door.admin("bob")}
    tokens = {name: door.token(c) for name, c in clients.items()}
    for name in ("root",):
        assert door.accounts.by_name(name) is None
    barrier = threading.Barrier(2)
    answers: dict[str, int] = {}

    def revoke(actor: str, target_id: str) -> None:
        barrier.wait(JOIN)
        answers[actor] = clients[actor].post(
            f"/admin/users/{target_id}/revoke-admin", data={"csrf": tokens[actor]}
        ).status_code

    threads = [
        threading.Thread(target=revoke, args=("alice", bob.id)),
        threading.Thread(target=revoke, args=("bob", alice.id)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(JOIN)
        assert not thread.is_alive(), "a revoking request hung"
    # The winner's POST is answered 303 (POST-redirect-GET, T15 fix round 1).
    assert sorted(answers.values())[0] == 303 and sorted(answers.values())[1] in (401, 409), answers
    assert len([a for a in door.accounts.all() if a.admin and not a.disabled]) == 1

    # And at the store, where the guard is: the same race, many times over,
    # never leaves none (the check and the change are one read-modify-write).
    for round_ in range(5):
        one = door.accounts.add(f"x{round_}", "pw-0123456789", admin=True)
        two = door.accounts.add(f"y{round_}", "pw-0123456789", admin=True)
        for account in door.accounts.all():
            if account.admin and account.id not in (one.id, two.id):
                door.accounts.set_admin(account.id, False, by_id=True, force=True)
        gate = threading.Barrier(2)
        outcomes: list[str] = []

        def store_revoke(actor: Any, target: Any) -> None:
            gate.wait(JOIN)
            try:
                door.accounts.set_admin(target.id, False, by_id=True, actor_id=actor.id)
                outcomes.append("ok")
            except LastAdmin:
                outcomes.append("last")

        racers = [
            threading.Thread(target=store_revoke, args=(one, two)),
            threading.Thread(target=store_revoke, args=(two, one)),
        ]
        for racer in racers:
            racer.start()
        for racer in racers:
            racer.join(JOIN)
            assert not racer.is_alive()
        assert sorted(outcomes) == ["last", "ok"], outcomes
        assert len([a for a in door.accounts.all() if a.admin and not a.disabled]) == 1


# -- delete -------------------------------------------------------------------------------------


def _saves_of(door: AdminDoor, account_id: str) -> Path:
    folder = door.data_dir / "users" / account_id / "saves" / "clockwork-dark" / "abc123def456"
    folder.mkdir(parents=True)
    (folder / "save.json").write_text("{}", encoding="utf-8")
    return door.data_dir / "users" / account_id


def test_a_purge_checks_again_after_its_delete(door: AdminDoor) -> None:
    """
    T15 fix round 2 (N3): a request the gate let in before the disable could
    still write the account's folder after the purge. The purge asks the
    stories again once it is done, and deletes the folder again when anything
    of the account was still there -- simulated by the supervisor stand-in,
    whose second ``sessions.end_owner`` finds one session and finds the folder
    written back. On 9098e90 there was no second look: the folder stayed.
    """
    bob = door.add("bob")
    folder = _saves_of(door, bob.id)
    calls: list[str] = []

    def end_owner(_conn: Any, args: dict[str, Any]) -> dict[str, Any]:
        calls.append(str(args["account"]))
        if len(calls) == 2:  # after the purge: a late write put the folder back
            back = folder / "saves" / "clockwork-dark" / "late0000"
            back.mkdir(parents=True)
            (back / "save.json").write_text("{}", encoding="utf-8")
            return {"ended": 1, "busy": 0, "errors": []}
        return {"ended": 0, "busy": 0, "errors": []}

    door.server.handle("sessions.end_owner", end_owner)
    client = door.admin()
    done = _post(door, client, f"/admin/users/{bob.id}/delete", mode="purge", confirm="bob")
    assert done.status_code == 303
    assert calls == [bob.id, bob.id] and not folder.exists()
    _started, outcome = _pair(_rows(door), "account.delete")
    assert outcome["result"] == "ok" and outcome["detail"]["purge_recheck"] is True


@pytest.mark.parametrize("mode", ["keep", "purge"])
def test_delete_keeps_or_purges_the_account_s_folder(door: AdminDoor, mode: str) -> None:
    bob = door.add("bob")
    folder = _saves_of(door, bob.id)
    client = door.admin()
    wrong = _post(door, client, f"/admin/users/{bob.id}/delete", mode=mode, confirm="not-bob")
    assert wrong.status_code == 400 and door.accounts.get(bob.id) is not None
    assert _rows(door)[-1]["result"] == "refused"
    done = _post(door, client, f"/admin/users/{bob.id}/delete", mode=mode, confirm="bob")
    assert done.status_code == 303
    assert door.accounts.get(bob.id) is None
    assert folder.is_dir() is (mode == "keep")
    _started, outcome = _pair(_rows(door), "account.delete")
    assert outcome["result"] == "ok" and outcome["detail"]["purge"] is (mode == "purge")


def test_delete_disables_the_account_first_then_removes_it(
    door: AdminDoor, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fix round 1, M5 (spec §14.8): disabled first, so a disable's hooks run for a delete too."""
    bob = door.add("bob")
    client = door.admin()
    accounts = door.accounts
    calls: list[tuple[str, bool]] = []
    real_disable, real_remove = accounts.disable, accounts.remove

    def disable(*args: Any, **kwargs: Any) -> Any:
        calls.append(("disable", accounts.get(bob.id) is not None))
        return real_disable(*args, **kwargs)

    def remove(*args: Any, **kwargs: Any) -> Any:
        found = accounts.get(bob.id)
        calls.append(("remove", found is not None and found.disabled))
        return real_remove(*args, **kwargs)

    monkeypatch.setattr(accounts, "disable", disable)
    monkeypatch.setattr(accounts, "remove", remove)
    assert _post(door, client, f"/admin/users/{bob.id}/delete", mode="keep", confirm="bob").status_code == 303
    assert calls == [("disable", True), ("remove", True)], calls
    assert accounts.get(bob.id) is None
    _started, outcome = _pair(_rows(door), "account.delete")
    assert outcome["result"] == "ok"


# -- the audit log failing -----------------------------------------------------------------


def test_every_action_is_refused_when_its_audit_row_cannot_be_written(
    door: AdminDoor, monkeypatch: pytest.MonkeyPatch
) -> None:
    from engine.hosting import audit

    bob = door.add("bob")
    door.add("carol", admin=True)
    client = door.admin()
    token = door.token(client)
    before = door.accounts.path.read_bytes()

    def full_disk(_directory: Any, _line: bytes) -> None:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(audit, "_write_line", full_disk)
    for url, form in (
        ("/admin/users", {"name": "dave"}),
        (f"/admin/users/{bob.id}/reset", {}),
        (f"/admin/users/{bob.id}/disable", {}),
        (f"/admin/users/{bob.id}/enable", {}),
        (f"/admin/users/{bob.id}/grant-admin", {}),
        (f"/admin/users/{door.accounts.by_name('carol').id}/revoke-admin", {}),
        (f"/admin/users/{bob.id}/delete", {"mode": "purge", "confirm": "bob"}),
    ):
        response = client.post(url, data={"csrf": token, **form})
        assert response.status_code == 503, url
        assert "audit log cannot be written" in response.get_data(as_text=True)
    assert door.accounts.path.read_bytes() == before
    # Re-auth is refused too: no row, no fresh admin_at.
    page = client.get("/admin/reauth")
    answer = client.post(
        "/admin/reauth",
        data={"csrf": csrf_of(page.get_data(as_text=True)), "password": door.passwords["root"]},
    )
    assert answer.status_code == 503
