"""
One turn at a time per session, at BOTH doors.

There are two ways into ``run_turn``: the Socket.IO ``player_choice`` handler
and ``POST /api/game/choice``. The socket handler took ``session.lock`` and
wrapped the call; the HTTP route did neither. So two concurrent posts, or one
post racing an in-flight socket turn, mutated a single ``GameState`` at the
same time -- and ``engine/session/store.py``'s own comment on that lock says
this corrupts state "in ways no test would reproduce".

It also meant a raise inside the HTTP turn returned a Flask HTML traceback to
a client that only ever parses JSON.

Both doors go through ``run_guarded`` now. These tests hold the lock and knock.
"""

from __future__ import annotations

import json

import pytest

from engine.persistence import reset_save_store
from engine.persistence.saves import SaveStore

MOCK = json.dumps(
    {
        "narration": "The room keeps its quiet, and the hour goes on being early.",
        "choices": [{"id": "a", "text": "Wait"}, {"id": "b", "text": "Listen"}],
    }
)


@pytest.fixture(autouse=True)
def _isolated_saves(tmp_path, monkeypatch):
    reset_save_store()
    store = SaveStore(root=tmp_path / "saves")
    monkeypatch.setattr("engine.scenes.default_state.get_save_store", lambda: store)
    yield
    reset_save_store()


def _client_and_session():
    from engine.scenes.default_scene import create_app, get_store, reset_store

    reset_store()
    _, app = create_app(testing=True, llm_fn=lambda _m: MOCK)
    client = app.test_client()
    started = client.post("/api/game/new", json={"seed": 42}).get_json()
    session = get_store().require(started["session_id"])
    return client, session


def test_the_http_door_takes_the_session_lock():
    """
    A post that arrives while a turn is running is refused, not run.

    Before this it ran straight into ``run_turn`` alongside the turn already in
    flight.
    """
    client, session = _client_and_session()

    assert session.lock.acquire(blocking=False), "lock should be free"
    try:
        response = client.post(
            "/api/game/choice",
            json={"session_id": session.engine.state.session_id, "choice_id": "a"},
        )
    finally:
        session.lock.release()

    assert response.status_code == 409
    assert "already in progress" in response.get_json()["error"]


def test_the_http_door_releases_the_lock_afterwards():
    """A turn that completes must not leave the session wedged."""
    client, session = _client_and_session()

    response = client.post(
        "/api/game/choice",
        json={"session_id": session.engine.state.session_id, "choice_id": "a"},
    )
    assert response.status_code == 200
    assert session.lock.acquire(blocking=False), "the lock was never released"
    session.lock.release()


def test_a_raising_turn_answers_json_not_an_html_traceback(monkeypatch):
    """
    The HTTP route had no exception handler at all, so a bug inside a turn
    reached a JSON client as a Flask HTML 500 page.
    """
    client, session = _client_and_session()

    def _boom(*_args, **_kwargs):
        raise RuntimeError("the turn broke")

    monkeypatch.setattr("engine.scenes.default_scene.run_turn", _boom)

    response = client.post(
        "/api/game/choice",
        json={"session_id": session.engine.state.session_id, "choice_id": "a"},
    )

    assert response.status_code == 500
    assert "the turn broke" in response.get_json()["error"]
    # And it still let go of the lock on the way out.
    assert session.lock.acquire(blocking=False), "a raise wedged the session"
    session.lock.release()


def test_contention_is_reported_as_busy_rather_than_as_a_dead_turn():
    """
    The socket path's busy emit carries ``busy: True``.

    This is what stops the client tearing down the RUNNING turn's prose when a
    second keypress arrives: the reducer deletes the in-flight streaming entry
    on a plain ``turn_error``, so a stray double-press used to wipe text the
    first turn had already put on screen.
    """
    from engine.scenes.default_scene import run_guarded

    _, session = _client_and_session()

    assert session.lock.acquire(blocking=False)
    try:
        payload, error, busy = run_guarded(session, "The player waits", None)
    finally:
        session.lock.release()

    assert payload is None
    assert busy is True
    assert "already in progress" in error
