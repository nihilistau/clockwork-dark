"""
Hosted mode's socket door (v0.20.0 T8, spec §6.3, §9.3).

``before_request`` never runs for Socket.IO, so every socket handler is
registered through ``FlaskScene.on``, which in hosted mode wraps it in the
socket guard (``engine/hosting/sockets.py``). These tests hold that:

- every event in every namespace of ``socketio.server.handlers`` is in
  ``scene.guarded_events`` -- canaried with a raw ``@socketio.on``, which must
  fail the same check;
- a connect without a login is refused;
- a disabled account's open socket, and one whose epoch a password change
  bumped, is told "login required" and dropped on its next event;
- the owner ``ContextVar`` is unset after each handler (a pool thread reused
  by the next event inherits nothing);
- a handler that raises answers with a reference, never the exception's
  words;
- in local mode ``on`` is ``socketio.on`` itself and guards nothing.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator

import pytest

from engine.session.store import current_owner
from tests.hosted_app import Hosted, build, csrf_of, login, teardown


@pytest.fixture
def hosted(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Hosted]:
    try:
        yield build(monkeypatch, tmp_path)
    finally:
        teardown()


def _registered(scene: Any) -> set[tuple[str, str]]:
    """``(namespace, event)`` of every handler Socket.IO holds, every namespace."""
    return {
        (str(namespace), str(event))
        for namespace, events in scene.socketio.server.handlers.items()
        for event in events
    }


def _unguarded(scene: Any) -> set[tuple[str, str]]:
    return _registered(scene) - scene.guarded_events


def _player(hosted: Hosted, name: str = "alice") -> tuple[Any, Any, Any]:
    """A logged-in HTTP client, its socket and its account."""
    account, password = hosted.add(name)
    client = hosted.client()
    assert login(client, name, password).status_code == 303
    sio = hosted.scene.socketio.test_client(hosted.app, flask_test_client=client)
    return client, sio, account


def _names(received: list[dict[str, Any]]) -> list[str]:
    return [event["name"] for event in received]


# -- every handler is guarded ----------------------------------------------------


def test_every_registered_socket_event_is_guarded(hosted: Hosted) -> None:
    registered = _registered(hosted.scene)
    assert {("/", "connect"), ("/", "join_session"), ("/", "player_choice"), ("/", "resume")} <= registered
    assert not _unguarded(hosted.scene), f"handlers outside the guard: {sorted(_unguarded(hosted.scene))}"


def test_a_raw_socketio_handler_fails_the_enumeration(hosted: Hosted) -> None:
    """The canary: a handler registered around ``self.on`` is caught, in any namespace."""
    socketio = hosted.scene.socketio

    @socketio.on("x")
    def raw(_data: Any) -> None:  # pragma: no cover - never called
        return None

    @socketio.on("y", namespace="/elsewhere")
    def raw_elsewhere(_data: Any) -> None:  # pragma: no cover - never called
        return None

    assert _unguarded(hosted.scene) == {("/", "x"), ("/elsewhere", "y")}


def test_a_handler_registered_through_on_after_install_is_guarded(hosted: Hosted) -> None:
    @hosted.scene.on("later", namespace="/elsewhere")
    def later(_data: Any) -> None:  # pragma: no cover - never called
        return None

    assert ("/elsewhere", "later") in hosted.scene.guarded_events
    assert not _unguarded(hosted.scene)


def test_local_mode_on_is_socketio_on_itself(monkeypatch: pytest.MonkeyPatch) -> None:
    """Local mode guards nothing: ``on`` hands back Socket.IO's own decorator."""
    from engine.scenes.default_scene import create_app, reset_store

    reset_store()
    scene, _app = create_app(testing=True)
    try:
        assert scene._socket_guard is None
        assert scene.guarded_events == set()
        seen: list[Any] = []
        original = scene.socketio.on
        monkeypatch.setattr(scene.socketio, "on", lambda *a, **k: seen.append((a, k)) or original(*a, **k))
        scene.on("probe")(lambda _d: None)
        assert seen == [(("probe", None), {})]
        assert ("/", "probe") not in scene.guarded_events
    finally:
        reset_store()


# -- the login, on connect and on every event ------------------------------------------


def test_a_connect_without_a_login_is_refused(hosted: Hosted) -> None:
    client = hosted.client()
    sio = hosted.scene.socketio.test_client(hosted.app, flask_test_client=client)
    assert not sio.is_connected()
    # And a logged-in browser's socket is let in.
    _, logged_in, _ = _player(hosted)
    assert logged_in.is_connected()


def _other_writer(hosted: Hosted) -> Any:
    """
    The accounts file as ANOTHER process sees it (``scripts/users.py``): its
    own ``AccountStore``, so no listener in this server hears its changes.
    """
    from engine.hosting.accounts import AccountStore

    return AccountStore(hosted.data_dir / "hosting")


def _revoke(store: Any, account: Any, how: str) -> None:
    if how == "password":
        store.set_password_by_id(account.id, "pw-a-new-password-1")
    elif how == "disable":
        store.disable(account.name)
    else:
        store.remove(account.name)


@pytest.mark.parametrize("how", ["password", "disable", "remove"])
def test_a_change_made_elsewhere_drops_the_socket_on_its_next_event(hosted: Hosted, how: str) -> None:
    """Another process changed the account: this server hears nothing until the socket speaks."""
    _, sio, account = _player(hosted)
    assert sio.is_connected()
    _revoke(_other_writer(hosted), account, how)
    sio.emit("join_session", {"session_id": "abc123def456"})
    received = sio.get_received() if sio.is_connected() else []
    assert not sio.is_connected(), "the socket of a dead login stayed open"
    assert all(e["name"] != "game_started" for e in received)


@pytest.mark.parametrize("how", ["password", "disable", "remove"])
def test_a_change_made_here_drops_every_socket_of_the_account_at_once(hosted: Hosted, how: str) -> None:
    """
    Fix round 1 (C1): a socket that sends nothing still receives its run's
    stream through its room, so a revoked login must be dropped at once, not
    on its next event. Fails on 1849d9a: the silent socket stayed connected.
    """
    _, sio, account = _player(hosted)
    _, second, _ = _thief(hosted, account)
    assert sio.is_connected() and second.is_connected()
    _revoke(hosted.state.accounts, account, how)
    assert not sio.is_connected() and not second.is_connected(), "a revoked login kept its sockets"
    assert len(hosted.scene._socket_door.registry) == 0


def _thief(hosted: Hosted, account: Any) -> tuple[Any, Any, str]:
    """A second browser logged in as ``account`` (a copied cookie, a shared password)."""
    password = hosted.passwords[account.name]
    client = hosted.client()
    assert login(client, account.name, password).status_code == 303
    sio = hosted.scene.socketio.test_client(hosted.app, flask_test_client=client)
    return client, sio, password


@pytest.mark.parametrize("writer", ["here", "elsewhere"])
def test_a_silent_stale_socket_gets_no_more_of_the_stream_after_a_password_change(
    hosted: Hosted, writer: str
) -> None:
    """
    The review's probe: a thief's socket joins alice's run and then sends
    nothing. Alice changes her password, logs in afresh and plays a turn over
    her new socket. The thief must receive none of it -- whether the change
    was made through this server (the revocation listener) or by another
    process (the room check before each emit). Fails on 1849d9a: the thief
    got narration_delta and turn_update.
    """
    client, mine, account = _player(hosted)
    session_id = client.post("/api/game/new", json={"seed": 7}).get_json()["session_id"]
    _, thief, _ = _thief(hosted, account)
    thief.emit("join_session", {"session_id": session_id})
    assert "game_started" in _names(thief.get_received())

    store = hosted.state.accounts if writer == "here" else _other_writer(hosted)
    store.set_password_by_id(account.id, "pw-a-new-password-1")
    hosted.passwords[account.name] = "pw-a-new-password-1"
    fresh = hosted.client()
    assert login(fresh, account.name, "pw-a-new-password-1").status_code == 303
    now = hosted.scene.socketio.test_client(hosted.app, flask_test_client=fresh)
    now.emit("join_session", {"session_id": session_id})
    now.emit("player_choice", {"session_id": session_id, "choice_id": "a"})
    assert "turn_update" in _names(now.get_received()), "the fresh login's turn never ran"
    assert not thief.is_connected(), "the stale socket is still connected"
    _assert_received_nothing(thief)


def _assert_received_nothing(sio: Any) -> None:
    """
    Fix round 2 (N1): read the test client's RAW queue, which keeps every
    packet it got even after a disconnect (``get_received`` raises once it is
    disconnected, so a "received nothing" check through it was vacuous and a
    leaked delta passed).
    """
    leaked = [packet["name"] for packet in sio.queue if packet["name"] != "error"]
    assert leaked == [], f"the stale socket received {leaked}"


@pytest.mark.parametrize("writer", ["here", "elsewhere"])
def test_a_silent_stale_socket_gets_nothing_of_a_turn_in_flight_after_a_disable(
    hosted: Hosted, writer: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    A disable lands while a turn of the account's is running (the model
    call is where it happens here). Nothing the turn emits afterwards may
    reach the account's silent socket. Fails on 1849d9a.
    """
    client, mine, account = _player(hosted)
    session_id = client.post("/api/game/new", json={"seed": 7}).get_json()["session_id"]
    _, thief, _ = _thief(hosted, account)
    thief.emit("join_session", {"session_id": session_id})
    assert "game_started" in _names(thief.get_received())
    session = hosted.scene.store._sessions[session_id]
    real = session.storyteller.llm_fn
    store = hosted.state.accounts if writer == "here" else _other_writer(hosted)
    disabled: list[bool] = []

    def disabling(messages: Any, *args: Any, **kwargs: Any) -> Any:
        if not disabled:
            disabled.append(True)
            store.disable(account.name)
        return real(messages, *args, **kwargs)

    monkeypatch.setattr(session.storyteller, "llm_fn", disabling)
    emitted: list[str] = []
    real_check = hosted.scene._room_check

    def counting_check(room: str) -> None:
        emitted.append(room)
        real_check(room)

    monkeypatch.setattr(hosted.scene, "_room_check", counting_check)
    mine.emit("join_session", {"session_id": session_id})
    mine.get_received()
    mine.emit("player_choice", {"session_id": session_id, "choice_id": "a"})
    assert disabled, "the turn never reached the model"
    assert not thief.is_connected(), "the disabled account's silent socket is still connected"
    _assert_received_nothing(thief)
    assert emitted, "the turn never emitted to its room: the test would prove nothing"


def test_logout_closes_no_socket(hosted: Hosted) -> None:
    """
    The residual HOSTING.md states: logging out ends this browser's cookie,
    not a socket another tab already has open (only an epoch change does).
    """
    client, sio, _ = _player(hosted)
    token = csrf_of(client.get("/account").data)
    assert client.post("/logout", data={"csrf": token}).status_code == 303
    assert sio.is_connected()


def test_a_connect_whose_account_cannot_be_read_is_refused(
    hosted: Hosted, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fix round 1 (M1): an unreadable ``users.json`` at connect fails closed, not open."""
    account, password = hosted.add("alice")
    client = hosted.client()
    assert login(client, "alice", password).status_code == 303

    def unreadable(_account_id: Any) -> Any:
        raise OSError("users.json is not readable")

    monkeypatch.setattr(hosted.state.accounts, "get", unreadable)
    sio = hosted.scene.socketio.test_client(hosted.app, flask_test_client=client)
    assert not sio.is_connected()
    assert len(hosted.scene._socket_door.registry) == 0


def test_a_disconnect_handler_runs_for_a_dead_login_and_emits_nothing(
    hosted: Hosted, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Fix round 1 (M2): ``disconnect`` passes the guard -- its body runs (it is
    cleanup) even when the login is dead, the socket is forgotten, and the
    guard neither emits to nor disconnects a socket already going.
    """
    import engine.hosting.sockets as sockets

    ran: list[Any] = []

    @hosted.scene.on("disconnect")
    def cleanup(*_args: Any) -> None:
        ran.append(current_owner.get())

    assert ("/", "disconnect") in hosted.scene.guarded_events
    _, sio, account = _player(hosted)
    _other_writer(hosted).disable(account.name)
    sent: list[Any] = []
    monkeypatch.setattr(sockets, "emit", lambda *a, **k: sent.append(a))
    sio.disconnect()
    assert ran == [None], "the cleanup body did not run, or ran as the dead account"
    assert sent == []
    assert len(hosted.scene._socket_door.registry) == 0


def test_a_dropped_socket_is_told_login_required(hosted: Hosted, monkeypatch: pytest.MonkeyPatch) -> None:
    """The ``error`` payload the guard emits before it disconnects."""
    import engine.hosting.sockets as sockets

    _, sio, account = _player(hosted)
    sent: list[tuple[str, Any]] = []
    monkeypatch.setattr(sockets, "emit", lambda event, payload: sent.append((event, payload)))
    monkeypatch.setattr(sockets, "disconnect", lambda: sent.append(("disconnect", None)))
    _other_writer(hosted).disable(account.name)
    sio.emit("player_choice", {"session_id": "abc123def456", "choice_id": "a"})
    assert sent == [("error", {"message": "login required"}), ("disconnect", None)]


# -- the owner -----------------------------------------------------------------------


def test_the_owner_is_set_for_the_body_and_unset_after_it(hosted: Hosted) -> None:
    seen: list[Any] = []

    @hosted.scene.on("whoami")
    def whoami(_data: Any) -> None:
        seen.append(current_owner.get())

    _, sio, account = _player(hosted)
    # The test client runs each handler on this thread: the thread a pool
    # would reuse for the next event.
    assert current_owner.get() is None
    sio.emit("whoami", {})
    assert seen == [account.id]
    assert current_owner.get() is None, "the owner outlived the handler"


def test_the_owner_is_unset_after_a_handler_that_raises(hosted: Hosted) -> None:
    @hosted.scene.on("boom")
    def boom(_data: Any) -> None:
        raise RuntimeError("http://model-host.internal:1234/v1 refused (ConnectError)")

    _, sio, _ = _player(hosted)
    sio.emit("boom", {})
    assert current_owner.get() is None
    errors = [e for e in sio.get_received() if e["name"] == "error"]
    assert len(errors) == 1
    message = errors[0]["args"][0]["message"]
    assert message.startswith("The request could not be completed (ref ")
    assert "model-host" not in message and "RuntimeError" not in message


def test_an_http_request_resets_the_owner_too(hosted: Hosted) -> None:
    client, _sio, _ = _player(hosted)
    assert client.get("/api/saves").status_code == 200
    assert current_owner.get() is None


def test_the_public_name_reaches_the_socket_door(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The host guard answers the public name on /socket.io/ too (T2's allowlist)."""
    hosted = build(monkeypatch, tmp_path, hosting={"public_origin": "https://play.example.org"})
    try:
        client = hosted.client()
        assert (
            client.get(
                "/socket.io/?EIO=4&transport=polling",
                headers={"Host": "play.example.org", "Origin": "https://play.example.org"},
            ).status_code
            == 200
        )
        assert (
            client.get(
                "/socket.io/?EIO=4&transport=polling",
                headers={"Host": "evil.example", "Origin": "https://play.example.org"},
            ).status_code
            == 400
        )
    finally:
        teardown()
