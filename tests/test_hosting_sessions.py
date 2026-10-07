"""
One live session per player, and the idle sweep (v0.20.0 T9, spec §5.4,
survey finding 7).

Hosted, an account has at most one live run per story. Starting or resuming
another releases the old one through ``SessionStore.delete``'s teardown,
unless its turn is running, which is refused with 409 "A turn is still
running in your other window." A resume of the SAME save rebuilds the run
under the same id (the id is in the save), and the released engine can never
autosave over it: its turn lock is kept, so a request that found it before
the release is refused as busy. The release hook closes the run's room, so
the old tab leaves it before the new socket joins and goes quiet.

A disconnected player's run is released by the idle sweep, which hosted mode
forces on, on a socket's disconnect and on ``require`` (at most once a
minute), and which never takes a session whose turn lock is held. The client
reconnects with ``resume`` and the run comes back from its autosave.

Finding 7 is recorded, not fixed, locally (spec §4.4): local mode keeps every
session (the last test).
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any, Iterator

import pytest

from tests.hosted_app import Hosted, build, login, teardown

JOIN = 30.0
OTHER_WINDOW = "A turn is still running in your other window."
#: Older than any idle_ttl_minutes the config allows to matter.
LONG_AGO = 86_400.0


@pytest.fixture
def hosted(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Hosted]:
    try:
        yield build(monkeypatch, tmp_path)
    finally:
        teardown()


def _client(hosted: Hosted, name: str) -> tuple[Any, Any]:
    account, password = hosted.add(name)
    client = hosted.client()
    assert login(client, name, password).status_code == 303
    return account, client


def _new(client: Any, seed: int = 7) -> dict[str, Any]:
    response = client.post("/api/game/new", json={"seed": seed, "player_name": "Wren"})
    assert response.status_code == 200, response.get_data(as_text=True)
    return response.get_json()


def _live(hosted: Hosted) -> dict[str, Any]:
    store = hosted.scene.store
    with store._guard:
        return dict(store._sessions)


def _socket(hosted: Hosted, client: Any) -> Any:
    sio = hosted.scene.socketio.test_client(hosted.app, flask_test_client=client)
    assert sio.is_connected()
    return sio


def _age(hosted: Hosted, session_id: str) -> None:
    hosted.scene.store._seen[session_id] = time.monotonic() - LONG_AGO


def test_an_account_has_one_live_session(hosted: Hosted) -> None:
    alice, alice_client = _client(hosted, "alice")
    bob, bob_client = _client(hosted, "bob")
    bobs = _new(bob_client, seed=3)
    first = _new(alice_client, seed=1)
    second = _new(alice_client, seed=2)

    live = _live(hosted)
    assert set(live) == {bobs["session_id"], second["session_id"]}
    assert live[second["session_id"]].owner == alice.id
    assert live[bobs["session_id"]].owner == bob.id
    gone = alice_client.get(f"/api/game/state?session_id={first['session_id']}")
    assert gone.status_code == 404
    # The first run is still on disk, in alice's menu.
    saves = alice_client.get("/api/saves").get_json()["saves"]
    assert first["save_id"] in {row["save_id"] for row in saves}


def test_a_new_run_is_refused_while_the_other_windows_turn_runs(hosted: Hosted) -> None:
    alice, client = _client(hosted, "alice")
    first = _new(client)
    session = hosted.scene.store.require(first["session_id"], owner=alice.id)
    sio = _socket(hosted, client)

    assert session.lock.acquire(blocking=False)  # its turn is running
    try:
        refused = client.post("/api/game/new", json={"seed": 2})
        assert refused.status_code == 409
        assert refused.get_json() == {"error": OTHER_WINDOW}
        loaded = client.post(f"/api/saves/{first['save_id']}/load")
        assert loaded.status_code == 409
        assert loaded.get_json() == {"error": OTHER_WINDOW}
        sio.emit("resume", {"save_id": first["save_id"]})
        assert sio.get_received() == [
            {"name": "resume_failed", "args": [{"message": OTHER_WINDOW}], "namespace": "/"}
        ]
        assert set(_live(hosted)) == {first["session_id"]}, "the running turn's session was released"
    finally:
        session.lock.release()

    assert _new(client, seed=2)["session_id"] != first["session_id"]
    sio.disconnect()


def test_a_resume_of_the_same_save_rebuilds_its_id_and_the_old_engine_never_saves(hosted: Hosted) -> None:
    from engine.scenes.default_scene import run_guarded

    alice, client = _client(hosted, "alice")
    opened = _new(client)
    old = hosted.scene.store.require(opened["session_id"], owner=alice.id)

    resumed = client.post(f"/api/saves/{opened['save_id']}/load")
    assert resumed.status_code == 200
    assert resumed.get_json()["session_id"] == opened["session_id"]
    new = hosted.scene.store.require(opened["session_id"], owner=alice.id)
    assert new is not old

    saves = hosted.data_dir / "users"
    before = {p: p.read_bytes() for p in saves.rglob("*") if p.is_file()}
    # A request that found the old run before the release: refused, nothing written.
    payload, error, busy = run_guarded(old, "The player chooses: Walk on", None)
    assert (payload, busy) == (None, True), error
    after = {p: p.read_bytes() for p in saves.rglob("*") if p.is_file()}
    assert after == before


def test_the_old_tab_leaves_the_room_and_hears_nothing_after(hosted: Hosted) -> None:
    alice, client = _client(hosted, "alice")
    opened = _new(client)
    old_tab = _socket(hosted, client)
    old_tab.emit("join_session", {"session_id": opened["session_id"]})
    assert [e["name"] for e in old_tab.get_received()] == ["game_started"]

    new_tab = _socket(hosted, client)
    new_tab.emit("resume", {"save_id": opened["save_id"]})
    resumed = new_tab.get_received()
    assert [e["name"] for e in resumed] == ["game_resumed"]
    # Press a choice the RESUMED frame offers (its ids are `resume_*`): since
    # v0.21.0 an id the frame does not hold is refused as stale.
    offered = resumed[0]["args"][0]["opening"]["choices"][0]["id"]
    new_tab.emit("player_choice", {"session_id": opened["session_id"], "choice_id": offered})
    heard = [e["name"] for e in new_tab.get_received()]
    assert "turn_update" in heard
    # v0.21.0 (spec §6.5): told why, once, and then nothing more of the run.
    assert [(e["name"], e["args"][0]["reason"]) for e in old_tab.get_received()] == [("session_ended", "elsewhere")]
    old_tab.disconnect()
    new_tab.disconnect()


def test_the_release_hook_closes_the_room(hosted: Hosted) -> None:
    store = hosted.scene.store
    assert store.on_release is not None
    closed: list[str] = []
    real = hosted.scene.socketio.close_room
    hosted.scene.socketio.close_room = lambda room, namespace=None: (closed.append(room), real(room, namespace=namespace))
    try:
        alice, client = _client(hosted, "alice")
        first = _new(client, seed=1)
        _new(client, seed=2)
    finally:
        del hosted.scene.socketio.close_room
    assert closed == [first["session_id"]]


def test_the_sweep_runs_on_a_socket_disconnect(hosted: Hosted) -> None:
    alice, alice_client = _client(hosted, "alice")
    _bob, bob_client = _client(hosted, "bob")
    idle = _new(alice_client)
    _age(hosted, idle["session_id"])

    sio = _socket(hosted, bob_client)
    assert idle["session_id"] in _live(hosted)
    sio.disconnect()
    assert idle["session_id"] not in _live(hosted)


def test_a_storys_own_disconnect_handler_does_not_remove_the_sweep(hosted: Hosted) -> None:
    """
    Fix round 1 (M1): the sweep is the socket door's own after-disconnect
    step, so a story registering its own ``disconnect`` (which replaces the
    body) keeps it. Fails on 1e0557f, where the story's handler replaced it.
    """
    alice, alice_client = _client(hosted, "alice")
    _bob, bob_client = _client(hosted, "bob")
    story_ran: list[bool] = []
    hosted.scene.on("disconnect")(lambda *_a: story_ran.append(True))
    idle = _new(alice_client)
    _age(hosted, idle["session_id"])

    sio = _socket(hosted, bob_client)
    sio.disconnect()
    assert story_ran == [True], "the story's own handler did not run"
    assert idle["session_id"] not in _live(hosted), "the sweep did not run"


def test_the_sweep_runs_on_require_at_most_once_a_minute(hosted: Hosted) -> None:
    alice, alice_client = _client(hosted, "alice")
    _bob, bob_client = _client(hosted, "bob")
    _carol, carol_client = _client(hosted, "carol")
    bobs = _new(bob_client)
    idle = _new(alice_client)
    store = hosted.scene.store

    _age(hosted, idle["session_id"])
    store._last_sweep = time.monotonic() - 120.0
    assert bob_client.get(f"/api/game/state?session_id={bobs['session_id']}").status_code == 200
    assert idle["session_id"] not in _live(hosted), "require did not sweep"

    # Within the minute: the next require does not sweep again.
    carols = _new(carol_client)
    _age(hosted, carols["session_id"])
    store._last_sweep = time.monotonic()
    assert bob_client.get(f"/api/game/state?session_id={bobs['session_id']}").status_code == 200
    assert carols["session_id"] in _live(hosted), "require swept twice within a minute"


def test_the_sweep_never_takes_a_held_lock(hosted: Hosted) -> None:
    alice, client = _client(hosted, "alice")
    opened = _new(client)
    session = hosted.scene.store.require(opened["session_id"], owner=alice.id)
    _age(hosted, opened["session_id"])

    holding = threading.Event()
    done = threading.Event()
    released: list[bool] = []

    def turn() -> None:
        assert session.lock.acquire(blocking=False)
        holding.set()
        done.wait(JOIN)
        session.lock.release()  # its own lock, still its to release
        released.append(True)

    thread = threading.Thread(target=turn, name="running-turn")
    thread.start()
    try:
        assert holding.wait(JOIN)
        assert hosted.scene.store.sweep_idle() == []
        assert opened["session_id"] in _live(hosted)
    finally:
        done.set()
        thread.join(JOIN)
    assert not thread.is_alive() and released == [True]
    assert not session.lock.locked()


def test_a_reconnect_resumes_a_swept_run(hosted: Hosted) -> None:
    alice, client = _client(hosted, "alice")
    opened = _new(client)
    _age(hosted, opened["session_id"])
    assert hosted.scene.store.sweep_idle() == [opened["session_id"]]
    assert _live(hosted) == {}

    sio = _socket(hosted, client)
    sio.emit("resume", {"save_id": opened["save_id"]})
    received = sio.get_received()
    assert [e["name"] for e in received] == ["game_resumed"]
    assert received[0]["args"][0]["session_id"] == opened["session_id"]
    assert set(_live(hosted)) == {opened["session_id"]}
    sio.disconnect()


def test_local_mode_keeps_every_session_and_does_not_sweep() -> None:
    """Local mode: v0.19.0's store, two runs live at once, the sweep off."""
    from engine.config import hosting_enabled
    from engine.scenes.default_state import SessionStore

    assert not hosting_enabled()
    store = SessionStore()
    first = store.create(seed=1)
    second = store.create(seed=2)
    assert store.get(first.session_id) is first
    assert store.get(second.session_id) is second
    store._seen[first.session_id] = time.monotonic() - LONG_AGO
    assert store.sweep_idle() == []
