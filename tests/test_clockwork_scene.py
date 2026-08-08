"""Clockwork Flask scene tests."""

from __future__ import annotations

import json

import pytest

MOCK_STORYTELLER = """
Mist clings to the birch trunks.

```json
{
  "tool_calls": [],
  "narration": "Mist clings to the birch trunks. Edgewood waits ahead.",
  "choices": [
    {"id": "a", "text": "Walk toward the village"},
    {"id": "b", "text": "Stay in the clearing"}
  ],
  "tags_inline": "[IMAGE:forest_clearing_dawn]"
}
```
"""


@pytest.fixture
def scene_app():
    from content.scenes.clockwork.clockwork_scene import create_app, reset_store

    reset_store()
    scene, app = create_app(
        testing=True,
        llm_fn=lambda _messages: MOCK_STORYTELLER,
    )
    app.config["TESTING"] = True
    return scene, app


def test_health(scene_app):
    _, app = scene_app
    client = app.test_client()
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.get_json()["status"] == "ok"


def test_index_loads(scene_app):
    _, app = scene_app
    client = app.test_client()
    res = client.get("/")
    assert res.status_code == 200
    # The page title is the ACTIVE STORY's, not a constant.
    #
    # This used to assert b"CLOCKWORK DARK", which the template rendered from a
    # hardcoded `display_name` -- so every story served by this scene package
    # opened a browser tab named after the flagship. Reproduced by launching a
    # second story and reading `document.title`.
    #
    # Asserted against the registry rather than a literal, so the test says
    # "the title follows the story" instead of re-pinning it to one name.
    from engine.games.registry import peek

    expected = (peek().title if peek() else "A story").encode()
    assert expected in res.data


def test_new_game(scene_app):
    _, app = scene_app
    client = app.test_client()
    res = client.post("/api/game/new", json={"player_name": "Alden"})
    assert res.status_code == 200
    data = res.get_json()
    assert data["session_id"]
    assert data["state"]["player_name"] == "Alden"
    assert data["opening"]["narration"]
    assert "awareness" not in data["state"]


def test_choice_rest_turn_update(scene_app):
    _, app = scene_app
    client = app.test_client()
    new_res = client.post("/api/game/new", json={})
    session_id = new_res.get_json()["session_id"]

    res = client.post(
        "/api/game/choice",
        json={"session_id": session_id, "choice_id": "a"},
    )
    assert res.status_code == 200
    data = res.get_json()
    assert "birch" in data["narration"].lower()
    assert len(data["choices"]) >= 2
    assert data["state"]["location_id"]


def test_get_state(scene_app):
    _, app = scene_app
    client = app.test_client()
    new_res = client.post("/api/game/new", json={})
    session_id = new_res.get_json()["session_id"]
    res = client.get(f"/api/game/state?session_id={session_id}")
    assert res.status_code == 200
    assert res.get_json()["state"]["session_id"] == session_id


def test_socket_turn_update(scene_app):
    scene, app = scene_app
    flask_client = app.test_client()
    new_res = flask_client.post("/api/game/new", json={})
    session_id = new_res.get_json()["session_id"]

    socket_client = scene.socketio.test_client(
        app,
        flask_test_client=flask_client,
    )
    socket_client.emit("join_session", {"session_id": session_id})
    socket_client.emit(
        "player_choice",
        {"session_id": session_id, "choice_id": "a"},
    )
    received = socket_client.get_received()
    names = [entry["name"] for entry in received]
    assert "game_started" in names
    assert "turn_update" in names
    turn = next(e for e in received if e["name"] == "turn_update")
    assert "narration" in turn["args"][0]