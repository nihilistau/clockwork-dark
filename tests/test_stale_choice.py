"""
A choice id the frame no longer offers is refused, before any turn runs.

v0.21.0 final review, finding 8. After a server restart the client's "Try
again" re-sent the dropped turn's chip id into a RESUMED frame, whose choices
are ``resume_*``. Nothing matched it, so no intent ran and the narrator was
handed "The player chooses option 3": a move nobody made, narrated over a
mechanic that never ran (rule 1). ``default_state.stale_choice`` now refuses
it -- HTTP 409, or a ``turn_error`` with ``busy: false`` -- and the frame,
the turn count and the save stay as they were.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

NARRATION = json.dumps(
    {"narration": "Mist clings to the birch trunks.", "choices": [{"id": "a", "text": "Walk on"}]}
)


@pytest.fixture
def scene_app() -> Any:
    from content.scenes.clockwork.clockwork_scene import create_app, reset_store

    reset_store()
    calls: list[Any] = []

    def model(messages: Any, *_a: Any, **_k: Any) -> str:
        calls.append(messages)
        return NARRATION

    scene, app = create_app(testing=True, llm_fn=model)
    yield scene, app, calls
    reset_store()


def test_an_id_not_on_offer_is_refused_over_http(scene_app: Any) -> None:
    scene, app, calls = scene_app
    client = app.test_client()
    started = client.post("/api/game/new", json={"seed": 7}).get_json()
    session = scene.store.require(started["session_id"])
    before = session.engine.state.turn_number

    answer = client.post(
        "/api/game/choice", json={"session_id": started["session_id"], "choice_id": "c3_from_a_dead_turn"}
    )
    assert answer.status_code == 409, answer.get_data(as_text=True)
    body = answer.get_json()
    assert body.get("stale_choice") is True and "no longer on offer" in body["error"]
    assert session.engine.state.turn_number == before
    assert not calls, "a refused id must reach no narrator"

    # The ids the frame DOES hold still play, and typed text always does.
    real = (session.last_turn.get("choices") or [])[0]["id"]
    assert client.post(
        "/api/game/choice", json={"session_id": started["session_id"], "choice_id": real}
    ).status_code == 200
    assert client.post(
        "/api/game/choice",
        json={"session_id": started["session_id"], "choice_id": "custom", "custom_text": "I wait."},
    ).status_code == 200


def test_an_id_not_on_offer_is_a_socket_turn_error_that_is_not_busy(scene_app: Any) -> None:
    scene, app, calls = scene_app
    flask_client = app.test_client()
    started = flask_client.post("/api/game/new", json={"seed": 7}).get_json()
    session_id = started["session_id"]
    socket = scene.socketio.test_client(app, flask_test_client=flask_client)
    socket.emit("join_session", {"session_id": session_id})
    socket.get_received()

    socket.emit("player_choice", {"session_id": session_id, "choice_id": "resume_go_nowhere"})
    received = socket.get_received()
    names = [e["name"] for e in received]
    assert "turn_update" not in names and "turn_started" not in names, names
    error = next(e for e in received if e["name"] == "turn_error")["args"][0]
    assert error["busy"] is False and error["stale_choice"] is True, error
    assert not calls


def test_stale_choice_answers_only_for_a_chip_id() -> None:
    from types import SimpleNamespace

    from engine.scenes.default_state import STALE_CHOICE, stale_choice

    import threading

    session = SimpleNamespace(
        last_turn={"choices": [{"id": "resume_look", "text": "Take stock"}]},
        lock=threading.Lock(),
    )
    assert stale_choice(session, "resume_look") == ""
    assert stale_choice(session, "custom", "I wait") == ""
    assert stale_choice(session, "c3", "typed text wins") == ""
    assert stale_choice(session, "") == ""
    assert stale_choice(session, "c3") == STALE_CHOICE


def test_a_press_during_a_running_turn_is_left_to_the_busy_guard() -> None:
    """A running turn may have swapped in its new frame before its
    turn_update reaches the page: an old-frame press then is busy, not stale
    (N1), so the controls are never re-enabled mid-turn."""
    import threading
    from types import SimpleNamespace

    from engine.scenes.default_state import stale_choice

    session = SimpleNamespace(
        last_turn={"choices": [{"id": "n1", "text": "New frame"}]},
        lock=threading.Lock(),
    )
    with session.lock:
        assert stale_choice(session, "old_frame_chip") == ""
