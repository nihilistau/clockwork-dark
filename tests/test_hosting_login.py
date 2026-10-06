"""
Hosted mode's login session (v0.20.0 T7, spec §6.2, §6.3, §6.5).

Login, logout and the account page; the signed cookie and its epoch; the two
kinds of CSRF token (the login form's, per session; a logged-in form's,
stateless); the Origin check; plain HTTP decided before CSRF; one failure for
a wrong name and a wrong password, with the dummy hash's work; the two login
buckets; and the cookie key, made once and shared.
"""

from __future__ import annotations

import logging
import os
import stat
from pathlib import Path
from typing import Any, Iterator

import flask
import pytest

from engine.hosting import accounts as accounts_module
from engine.hosting.auth import (
    COOKIE_NAME,
    EPOCH,
    FORM_EXPIRED,
    LOGIN_FAILED,
    LOGIN_LIMITED,
    SECRET_KEY_FILE,
    UID,
    form_token,
)
from tests.hosted_app import Hosted, build, csrf_of, login, new_password, teardown


@pytest.fixture
def hosted(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Hosted]:
    try:
        yield build(monkeypatch, tmp_path)
    finally:
        teardown()


def _cookie(response: Any) -> str:
    return "".join(
        h for k, h in response.headers.items() if k.lower() == "set-cookie" and COOKIE_NAME in h
    )


# -- login, logout ----------------------------------------------------------


def test_login_sets_the_cookie_and_opens_the_game(hosted: Hosted) -> None:
    account, password = hosted.add()
    client = hosted.client()
    assert client.get("/api/archetypes").status_code == 401
    response = login(client, "alice", password)
    assert response.status_code == 303 and response.headers["Location"] == "/"
    cookie = _cookie(response)
    assert COOKIE_NAME in cookie and "HttpOnly" in cookie and "SameSite=Lax" in cookie
    assert "Secure" in cookie
    assert client.get("/api/archetypes").status_code == 200
    with client.session_transaction() as sess:
        assert sess[UID] == account.id and sess[EPOCH] == 1
        assert sess.permanent is True
        assert "login_csrf" not in sess


def test_login_clears_whatever_the_session_held_before(hosted: Hosted) -> None:
    _, password = hosted.add()
    client = hosted.client()
    client.get("/login")
    with client.session_transaction() as sess:
        sess["story"] = "someone-else's"
        sess["planted"] = "by a page before login"
    login(client, "alice", password)
    with client.session_transaction() as sess:
        assert set(sess) == {UID, EPOCH, "_permanent"}


def test_logout_needs_the_form_token_and_ends_the_session(hosted: Hosted) -> None:
    account, password = hosted.add()
    client = hosted.client()
    login(client, "alice", password)
    refused = client.post("/logout", data={"csrf": "nope"})
    assert refused.status_code == 403
    assert client.get("/api/archetypes").status_code == 200
    token = csrf_of(client.get("/").data)
    with hosted.app.test_request_context():
        assert token == form_token(account)
    done = client.post("/logout", data={"csrf": token})
    assert done.status_code == 303 and done.headers["Location"] == "/login"
    assert client.get("/api/archetypes").status_code == 401


def test_rendering_the_page_writes_nothing_to_the_session(hosted: Hosted) -> None:
    _, password = hosted.add()
    client = hosted.client()
    login(client, "alice", password)
    with client:
        page = client.get("/")
        assert page.status_code == 200
        assert b'action="/logout"' in page.data and b'href="/account"' in page.data
        assert flask.session.modified is False
    assert not _cookie(page), "GET / re-issued the cookie"
    api = client.get("/api/archetypes")
    assert not _cookie(api)


def test_the_logout_token_dies_with_a_password_change(hosted: Hosted) -> None:
    _, password = hosted.add()
    client = hosted.client()
    login(client, "alice", password)
    old_token = csrf_of(client.get("/").data)
    new = new_password()
    changed = client.post(
        "/account",
        data={"csrf": old_token, "current": password, "new": new, "confirm": new},
    )
    assert changed.status_code == 200
    assert client.post("/logout", data={"csrf": old_token}).status_code == 403
    fresh = csrf_of(client.get("/").data)
    assert fresh != old_token
    assert client.post("/logout", data={"csrf": fresh}).status_code == 303


# -- the account page ---------------------------------------------------------


def test_a_password_change_keeps_this_window_and_ends_every_other(hosted: Hosted) -> None:
    account, password = hosted.add()
    here, there = hosted.client(), hosted.client()
    login(here, "alice", password)
    login(there, "alice", password)
    assert there.get("/api/archetypes").status_code == 200

    page = here.get("/account")
    assert page.status_code == 200 and b"alice" in page.data
    new = new_password()
    response = here.post(
        "/account",
        data={"csrf": csrf_of(page.data), "current": password, "new": new, "confirm": new},
    )
    assert response.status_code == 200, response.data
    assert COOKIE_NAME in _cookie(response), "this window's cookie was not re-issued"
    assert hosted.state.accounts.get(account.id).epoch == 2
    assert here.get("/api/archetypes").status_code == 200
    assert there.get("/api/archetypes").status_code == 401
    assert there.get("/").status_code == 302
    assert hosted.state.accounts.verify("alice", new) is not None


def test_a_password_change_needs_the_current_password(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Four tries at the current password: more than one (address, name)
    # bucket allows at the default (3), so this test raises the limit.
    hosted = build(
        monkeypatch, tmp_path, hosting={"rate_limits": {"actions_per_minute": 12, "logins_per_minute": 20}}
    )
    try:
        _password_change_needs_the_current_password(hosted)
    finally:
        teardown()


def _password_change_needs_the_current_password(hosted: Hosted) -> None:
    account, password = hosted.add()
    client = hosted.client()
    login(client, "alice", password)
    token = csrf_of(client.get("/account").data)
    new = new_password()
    wrong = client.post(
        "/account", data={"csrf": token, "current": new, "new": new, "confirm": new}
    )
    assert wrong.status_code == 403
    assert hosted.state.accounts.get(account.id).epoch == 1
    differ = client.post(
        "/account", data={"csrf": token, "current": password, "new": new, "confirm": new + "x"}
    )
    assert differ.status_code == 400
    short = client.post(
        "/account", data={"csrf": token, "current": password, "new": "short", "confirm": "short"}
    )
    assert short.status_code == 400
    forged = client.post(
        "/account", data={"csrf": "forged", "current": password, "new": new, "confirm": new}
    )
    assert forged.status_code == 403 and FORM_EXPIRED.encode() in forged.data
    assert hosted.state.accounts.get(account.id).epoch == 1


def test_a_disabled_account_is_logged_out_on_its_next_request(hosted: Hosted) -> None:
    _, password = hosted.add()
    client = hosted.client()
    login(client, "alice", password)
    assert client.get("/api/archetypes").status_code == 200
    hosted.state.accounts.disable("alice")
    assert client.get("/api/archetypes").status_code == 401
    hosted.state.accounts.enable("alice")
    assert client.get("/api/archetypes").status_code == 401, "an old epoch came back to life"


def test_a_removed_account_is_logged_out(hosted: Hosted) -> None:
    _, password = hosted.add()
    client = hosted.client()
    login(client, "alice", password)
    hosted.state.accounts.remove("alice")
    assert client.get("/api/archetypes").status_code == 401


# -- CSRF and Origin ------------------------------------------------------------


def test_the_login_form_needs_its_session_token(hosted: Hosted) -> None:
    _, password = hosted.add()
    client = hosted.client()
    client.get("/login")
    forged = client.post("/login", data={"csrf": "forged", "name": "alice", "password": password})
    assert forged.status_code == 403 and FORM_EXPIRED.encode() in forged.data
    stranger = hosted.client()  # never loaded the form: no token in its cookie
    none = stranger.post("/login", data={"csrf": "", "name": "alice", "password": password})
    assert none.status_code == 403
    assert client.get("/api/archetypes").status_code == 401


@pytest.mark.parametrize(
    "headers",
    [
        {"Origin": "http://127.0.0.1"},
        {"Origin": "https://localhost:8443"},
        {"Origin": "null"},
        {"Referer": "https://127.0.0.1/page"},
    ],
)
def test_a_state_changing_request_from_another_origin_is_refused(
    hosted: Hosted, headers: dict[str, str]
) -> None:
    """Hosts the host guard allows (loopback) but that are not THIS origin."""
    _, password = hosted.add()
    client = hosted.client()
    token = csrf_of(client.get("/login").data)
    refused = client.post(
        "/login", data={"csrf": token, "name": "alice", "password": password}, headers=headers
    )
    assert refused.status_code == 403
    if headers.get("Origin") != "null":  # "null" the host guard refuses first
        assert refused.get_json() == {"error": "cross-site request refused"}
    same = client.post(
        "/login",
        data={"csrf": token, "name": "alice", "password": password},
        headers={"Origin": "https://localhost"},
    )
    assert same.status_code == 303


def test_the_public_origin_is_accepted(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    hosted = build(monkeypatch, tmp_path, hosting={"public_origin": "https://play.example.org"})
    try:
        _, password = hosted.add()
        client = hosted.client()
        token = csrf_of(client.get("/login").data)
        response = client.post(
            "/login",
            data={"csrf": token, "name": "alice", "password": password},
            headers={"Origin": "https://play.example.org"},
        )
        assert response.status_code == 303
        # The public name is also on the host guard's allowlist: the reverse
        # proxy passes it on as the Host.
        assert client.get("/api/health", headers={"Host": "play.example.org"}).status_code == 200
        assert client.get("/api/health", headers={"Host": "evil.example"}).status_code == 400
    finally:
        teardown()


def test_plain_http_is_decided_before_csrf(hosted: Hosted) -> None:
    _, password = hosted.add()
    client = hosted.client()
    page = client.get("/login", base_url="http://localhost")
    assert b"hosting.cookie_secure" in page.data
    response = client.post(
        "/login",
        data={"csrf": "not even checked", "name": "alice", "password": password},
        base_url="http://localhost",
    )
    assert response.status_code == 400
    assert b"hosting.cookie_secure" in response.data
    assert FORM_EXPIRED.encode() not in response.data
    assert not _cookie(response) or "clockwork_session=;" in _cookie(response)


def test_plain_http_logs_in_when_cookie_secure_is_off(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    hosted = build(monkeypatch, tmp_path, hosting={"cookie_secure": False})
    try:
        _, password = hosted.add()
        client = hosted.client()
        response = login(client, "alice", password, base_url="http://localhost")
        assert response.status_code == 303
        assert "Secure" not in _cookie(response)
    finally:
        teardown()


# -- failures are one failure ---------------------------------------------------


def test_a_wrong_name_and_a_wrong_password_fail_identically(
    hosted: Hosted, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, password = hosted.add()
    checked: list[str] = []
    real = accounts_module.check_password_hash
    monkeypatch.setattr(
        accounts_module,
        "check_password_hash",
        lambda stored, pw: checked.append(stored) or real(stored, pw),
    )
    client = hosted.client()
    token = csrf_of(client.get("/login").data)
    wrong_name = client.post("/login", data={"csrf": token, "name": "bob", "password": password})
    assert checked == [accounts_module.DUMMY_HASH], "an unknown name skipped the hash work"
    wrong_password = client.post(
        "/login", data={"csrf": token, "name": "alice", "password": password + "x"}
    )
    assert checked[1] == hosted.state.accounts.by_name("alice").hash
    assert wrong_name.status_code == wrong_password.status_code == 401
    assert wrong_name.data == wrong_password.data
    assert LOGIN_FAILED.encode() in wrong_name.data
    hosted.state.accounts.disable("alice")
    disabled = client.post("/login", data={"csrf": token, "name": "alice", "password": password})
    assert (disabled.status_code, disabled.data) == (401, wrong_name.data)
    assert checked[2] == accounts_module.DUMMY_HASH


def test_a_failure_is_logged_with_a_marker_and_address_never_the_name_or_password(
    hosted: Hosted, caplog: pytest.LogCaptureFixture
) -> None:
    hosted.add()
    client = hosted.client()
    token = csrf_of(client.get("/login").data)
    typed = new_password()
    with caplog.at_level(logging.INFO):
        client.post("/login", data={"csrf": token, "name": "alice", "password": typed})
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "Login failed" in text and "127.0.0.1" in text
    assert "alice" not in text and "mac=" in text
    assert typed not in text


def test_a_password_typed_into_the_name_field_never_reaches_the_log(
    hosted: Hosted, caplog: pytest.LogCaptureFixture
) -> None:
    """Final review, finding 2: the over-limit, busy and failed paths all log a marker."""
    hosted.add()
    client = hosted.client()
    token = csrf_of(client.get("/login").data)
    typed = new_password()
    with caplog.at_level(logging.INFO):
        client.post("/login", data={"csrf": token, "name": typed, "password": "x"})
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "Login failed" in text
    assert typed not in text
    assert "mac=" in text and f"len={len(typed)}" in text


# -- the two login buckets ------------------------------------------------------


def _attempt(client: Any, name: str, password: str, address: str) -> int:
    env = {"REMOTE_ADDR": address}
    token = csrf_of(client.get("/login", environ_base=env).data)
    return client.post(
        "/login", data={"csrf": token, "name": name, "password": password}, environ_base=env
    ).status_code


def test_the_address_and_name_bucket_and_a_friend_elsewhere(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    hosted = build(monkeypatch, tmp_path, hosting={"rate_limits": {"actions_per_minute": 12, "logins_per_minute": 3}})
    try:
        _, password = hosted.add()
        attacker = hosted.client()
        # The (address, name) bucket holds half the address count (2 of 3), so
        # one address guessing one name is stopped before its address is.
        codes = [_attempt(attacker, "alice", "wrong-password-1", "10.0.0.66") for _ in range(3)]
        assert codes == [401, 401, 429]
        assert _attempt(attacker, "bob", "wrong-password-1", "10.0.0.66") == 401
        page = attacker.post(
            "/login",
            data={"csrf": csrf_of(attacker.get("/login", environ_base={"REMOTE_ADDR": "10.0.0.66"}).data),
                  "name": "alice", "password": password},
            environ_base={"REMOTE_ADDR": "10.0.0.66"},
        )
        assert page.status_code == 429 and LOGIN_LIMITED.encode() in page.data
        # A third party typing alice's name does not lock alice out elsewhere.
        alice = hosted.client()
        assert _attempt(alice, "alice", password, "10.0.0.7") == 303
    finally:
        teardown()


def test_the_per_address_bucket_covers_many_names(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    hosted = build(monkeypatch, tmp_path, hosting={"rate_limits": {"actions_per_minute": 12, "logins_per_minute": 3}})
    try:
        client = hosted.client()
        codes = [_attempt(client, f"name{i}", "wrong-password-1", "10.0.0.66") for i in range(4)]
        assert codes == [401, 401, 401, 429]
        assert _attempt(client, "name9", "wrong-password-1", "10.0.0.67") == 401
    finally:
        teardown()


def test_behind_a_trusted_proxy_the_forwarded_address_is_bucketed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    hosted = build(
        monkeypatch,
        tmp_path,
        hosting={"trusted_proxies": 1, "rate_limits": {"actions_per_minute": 12, "logins_per_minute": 2}},
    )
    try:
        client = hosted.client()

        def via_proxy(client_address: str) -> int:
            env = {"REMOTE_ADDR": "127.0.0.1"}
            headers = {"X-Forwarded-For": client_address, "X-Forwarded-Proto": "https"}
            token = csrf_of(client.get("/login", environ_base=env, headers=headers).data)
            return client.post(
                "/login",
                data={"csrf": token, "name": "someone", "password": "wrong-password-1"},
                environ_base=env,
                headers=headers,
            ).status_code

        assert [via_proxy("203.0.113.5") for _ in range(2)] == [401, 429]
        assert via_proxy("203.0.113.6") == 401, "every client shared the proxy's bucket"
    finally:
        teardown()


def test_with_no_trusted_proxy_a_forwarded_address_is_ignored(hosted: Hosted) -> None:
    client = hosted.client()
    statuses = []
    for i in range(6):
        env = {"REMOTE_ADDR": "10.0.0.66"}
        headers = {"X-Forwarded-For": f"203.0.113.{i}"}
        token = csrf_of(client.get("/login", environ_base=env).data)
        statuses.append(
            client.post(
                "/login",
                data={"csrf": token, "name": f"n{i}", "password": "wrong-password-1"},
                environ_base=env,
                headers=headers,
            ).status_code
        )
    assert statuses == [401] * 5 + [429], "a client chose its own address"


def test_the_login_buckets_are_exact_under_threads(monkeypatch: pytest.MonkeyPatch) -> None:
    """Twenty threads at once against a bucket of ten: exactly ten get in, and
    the limiter's lock keeps engine/locks.py's order (it is a leaf)."""
    import threading

    from engine.hosting.limits import LoginLimiter
    from tests import lock_order

    checker = lock_order.install(monkeypatch)
    limiter = LoginLimiter(10, clock=lambda: 100.0)
    barrier = threading.Barrier(20)
    results: list[bool] = []

    def attempt(i: int) -> None:
        barrier.wait(timeout=10)
        results.append(limiter.allow("10.0.0.1", f"name{i}"))

    threads = [threading.Thread(target=attempt, args=(i,)) for i in range(20)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)
    assert not any(thread.is_alive() for thread in threads)
    assert results.count(True) == 10 and len(results) == 20
    assert "engine.hosting.limits.LoginLimiter._lock" in checker.acquired
    assert not checker.violations, lock_order.report(checker)


def test_a_bucket_refills_over_a_minute() -> None:
    from engine.hosting.limits import LoginLimiter

    now = [0.0]
    limiter = LoginLimiter(5, clock=lambda: now[0])
    assert [limiter.allow("a", f"n{i}") for i in range(6)] == [True] * 5 + [False]
    now[0] = 12.0  # a fifth of a minute: one token back
    assert limiter.allow("a", "m1") and not limiter.allow("a", "m2")


@pytest.mark.parametrize(
    ("first", "second", "shared"),
    [
        ("2001:db8:1:2::1", "2001:db8:1:2:ffff::9", True),  # one /64
        ("2001:db8:1:2::1", "2001:db8:1:3::1", False),  # the next /64
        ("::ffff:192.0.2.7", "192.0.2.7", True),  # IPv4-mapped is the IPv4
        ("192.0.2.7", "192.0.2.8", False),
    ],
)
def test_ipv6_counts_by_its_64(first: str, second: str, shared: bool) -> None:
    from engine.hosting.limits import LoginLimiter, address_key

    assert (address_key(first) == address_key(second)) is shared
    limiter = LoginLimiter(2, clock=lambda: 0.0)
    assert limiter.allow(first, "a") and limiter.allow(first, "b")
    assert limiter.allow(second, "c") is (not shared)


def test_the_server_wide_bucket_bounds_only_addresses_that_have_failed() -> None:
    from engine.hosting.limits import LoginLimiter

    now = [0.0]
    limiter = LoginLimiter(5, all_per_minute=4, clock=lambda: now[0])
    # Clean addresses are exempt.
    assert all(limiter.allow(f"10.0.0.{i}", "alice") for i in range(6))
    # Six addresses fail once each; then together they get four more tries.
    for i in range(6):
        limiter.record_failure(f"10.9.0.{i}")
    got = [limiter.allow(f"10.9.0.{i}", "alice") for i in range(6)]
    assert got == [True] * 4 + [False] * 2
    assert limiter.allow("10.0.0.99", "alice"), "a clean address was refused"
    # A failure counts for a minute.
    now[0] = 61.0
    assert limiter.allow("10.9.0.5", "bob")


def test_failures_past_the_window_are_forgotten_by_age() -> None:
    """
    T7 re-review 2: ``_failed`` was pruned only past 4096 entries, so a few
    hundred stale failures stayed for the life of the process. A failure past
    the window counts for nothing and is dropped at the next prune.
    """
    from engine.hosting.limits import LoginLimiter

    now = [0.0]
    limiter = LoginLimiter(5, all_per_minute=60, clock=lambda: now[0])
    for i in range(300):
        limiter.record_failure(f"10.8.{i // 250}.{i % 250}")
    assert len(limiter._failed) == 300
    now[0] = 61.0
    limiter.record_failure("10.7.0.1")
    assert set(limiter._failed) == {"10.7.0.1"}


def test_guessers_on_a_dozen_64s_cannot_refuse_a_clean_login(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Twelve IPv6 /64s guessing wrong passwords drain the server-wide bucket;
    a player on a clean address still logs in (v0.20.0 T7 fix round 2)."""
    hosted = build(
        monkeypatch,
        tmp_path,
        hosting={"rate_limits": {"actions_per_minute": 12, "logins_per_minute": 3, "logins_per_minute_all": 12}},
    )
    try:
        _, password = hosted.add()
        attacker = hosted.client()
        refused = 0
        for attempt in range(3):
            for prefix in range(12):
                code = _attempt(
                    attacker, f"guess{attempt}", "wrong-password-1", f"2001:db8:{prefix:x}::{attempt + 1}"
                )
                refused += code == 429
        assert refused >= 12, "the server-wide bucket never bound the guessers"
        alice = hosted.client()
        assert _attempt(alice, "alice", password, "198.51.100.4") == 303
    finally:
        teardown()


def test_the_server_wide_bucket_over_http(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    hosted = build(
        monkeypatch,
        tmp_path,
        hosting={"rate_limits": {"actions_per_minute": 12, "logins_per_minute": 5, "logins_per_minute_all": 3}},
    )
    try:
        client = hosted.client()
        # Each address's first failure is before it counts as guessing.
        first = [_attempt(client, "someone", "wrong-password-1", f"10.0.1.{i}") for i in range(4)]
        assert first == [401] * 4
        codes = [_attempt(client, "other", "wrong-password-1", f"10.0.1.{i}") for i in range(4)]
        assert codes == [401, 401, 401, 429]
    finally:
        teardown()


def test_a_login_with_every_hashing_slot_taken_is_a_429_without_hashing(
    hosted: Hosted, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, password = hosted.add()
    monkeypatch.setattr(accounts_module, "HASH_WAIT_SECONDS", 0.1)
    slots = hosted.state.accounts.hash_slots
    assert slots is not None
    taken = 0
    while slots.acquire(blocking=False):
        taken += 1
    assert taken == 4, "hosting.max_concurrent_logins defaults to 4"
    hashed: list[str] = []
    real = accounts_module.check_password_hash
    monkeypatch.setattr(
        accounts_module, "check_password_hash", lambda s, p: hashed.append(s) or real(s, p)
    )
    try:
        client = hosted.client()
        token = csrf_of(client.get("/login").data)
        unknown = client.post("/login", data={"csrf": token, "name": "bob", "password": password})
        known = client.post("/login", data={"csrf": token, "name": "alice", "password": password})
        assert unknown.status_code == known.status_code == 429
        assert unknown.data == known.data and LOGIN_LIMITED.encode() in known.data
        assert hashed == []
    finally:
        for _ in range(taken):
            slots.release()
    assert login(hosted.client(), "alice", password).status_code == 303


# -- the cookie key ----------------------------------------------------------------


def test_the_cookie_key_is_made_once_and_shared(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    first = build(monkeypatch, tmp_path)
    try:
        key_file = first.data_dir / "hosting" / SECRET_KEY_FILE
        assert key_file.is_file()
        key = key_file.read_text(encoding="ascii")
        assert len(key) == 64 and first.app.secret_key == key
        if os.name == "posix":
            assert stat.S_IMODE(key_file.stat().st_mode) == 0o600
        second = build(monkeypatch, tmp_path)
        assert second.app.secret_key == key
        assert key_file.read_text(encoding="ascii") == key
        # A cookie from one is valid at the other: one key per instance.
        _, password = first.add()
        client = first.client()
        login(client, "alice", password)
        cookie = client.get_cookie(COOKIE_NAME)
        other = second.client()
        other.set_cookie(COOKIE_NAME, cookie.value, domain="localhost")
        assert other.get("/api/archetypes").status_code == 200
    finally:
        teardown()


@pytest.mark.skipif(os.name != "posix", reason="file modes are POSIX's")
def test_the_cookie_key_file_is_0600(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    hosted = build(monkeypatch, tmp_path)
    try:
        key_file = hosted.data_dir / "hosting" / SECRET_KEY_FILE
        assert stat.S_IMODE(key_file.stat().st_mode) == 0o600
    finally:
        teardown()


def test_a_configured_key_is_used_and_no_file_is_made(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import secrets

    configured = secrets.token_urlsafe(32)
    hosted = build(monkeypatch, tmp_path, env={"CLOCKWORK_SECRET_KEY": configured})
    try:
        assert hosted.app.secret_key == configured
        assert not (hosted.data_dir / "hosting" / SECRET_KEY_FILE).exists()
    finally:
        teardown()


@pytest.mark.parametrize("key", ["x", "changeme"])
def test_a_short_configured_key_stops_startup(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, key: str
) -> None:
    from engine.hosting import HostingConfigError

    try:
        with pytest.raises(HostingConfigError) as caught:
            build(monkeypatch, tmp_path, env={"CLOCKWORK_SECRET_KEY": key})
        assert caught.value.key == "hosting.secret_key"
    finally:
        teardown()


def test_a_short_key_file_stops_startup(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from engine.hosting import HostingConfigError

    key_file = tmp_path / "data" / "hosting" / SECRET_KEY_FILE
    key_file.parent.mkdir(parents=True)
    key_file.write_text("short-key", encoding="ascii")
    try:
        with pytest.raises(HostingConfigError) as caught:
            build(monkeypatch, tmp_path)
        assert caught.value.key == "hosting.secret_key"
        assert str(key_file) in str(caught.value)
    finally:
        teardown()


def test_an_http_origin_is_not_the_https_public_origin(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    hosted = build(monkeypatch, tmp_path, hosting={"public_origin": "https://play.example.org"})
    try:
        _, password = hosted.add()
        client = hosted.client()
        token = csrf_of(client.get("/login").data)
        form = {"csrf": token, "name": "alice", "password": password}
        refused = client.post("/login", data=form, headers={"Origin": "http://play.example.org"})
        assert refused.status_code == 403
        # This request's own origin needs its scheme too.
        assert client.post("/login", data=form, headers={"Origin": "http://localhost"}).status_code == 403
        assert client.post(
            "/login", data=form, headers={"Origin": "https://play.example.org"}
        ).status_code == 303
    finally:
        teardown()


def test_no_app_template_can_stand_in_for_the_login_pages(hosted: Hosted) -> None:
    from jinja2 import ChoiceLoader, DictLoader

    shadow = "SHADOW PAGE"
    env = hosted.app.jinja_env
    env.loader = ChoiceLoader(
        [
            DictLoader({name: shadow for name in ("login.html", "account.html", "hosting/login.html")}),
            env.loader,
        ]
    )
    _, password = hosted.add()
    client = hosted.client()
    page = client.get("/login")
    assert shadow.encode() not in page.data and b'name="csrf"' in page.data
    login(client, "alice", password)
    assert shadow.encode() not in client.get("/account").data


def test_cookie_settings(hosted: Hosted) -> None:
    config = hosted.app.config
    assert config["SESSION_COOKIE_NAME"] == COOKIE_NAME
    assert config["SESSION_COOKIE_HTTPONLY"] is True
    assert config["SESSION_COOKIE_SAMESITE"] == "Lax"
    assert config["SESSION_COOKIE_SECURE"] is True
    assert config["SESSION_REFRESH_EACH_REQUEST"] is False
    assert config["PERMANENT_SESSION_LIFETIME"].days == 14
