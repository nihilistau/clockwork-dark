"""
A released run tells its tab why (v0.21.0, spec §6.5, F6).

Hosted mode keeps one live run per account: a resume or a new game in
another tab releases this one, an admin can end it, and the idle sweep puts
it away. Until v0.21.0 the release only closed the run's Socket.IO room, so
the tab went quiet with no word. Now the room hears
``session_ended {"reason", "session_id"}`` first -- the id, so a tab that
has already left that run (it pressed Begin) ignores it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator

import pytest

from tests.hosted_app import Hosted, build, teardown
from tests.test_hosting_sessions import _age, _client, _new, _socket


@pytest.fixture
def hosted(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Hosted]:
    try:
        yield build(monkeypatch, tmp_path)
    finally:
        teardown()


def _ended(sio: Any) -> list[dict[str, Any]]:
    return [e["args"][0] for e in sio.get_received() if e["name"] == "session_ended"]


def _joined(hosted: Hosted, client: Any, session_id: str) -> Any:
    tab = _socket(hosted, client)
    tab.emit("join_session", {"session_id": session_id})
    assert [e["name"] for e in tab.get_received()] == ["game_started"]
    return tab


def test_a_resume_in_another_tab_tells_the_old_tab_elsewhere(hosted: Hosted) -> None:
    _alice, client = _client(hosted, "alice")
    opened = _new(client)
    old_tab = _joined(hosted, client, opened["session_id"])
    new_tab = _socket(hosted, client)
    new_tab.emit("resume", {"save_id": opened["save_id"]})
    resumed = new_tab.get_received()
    assert [e["name"] for e in resumed] == ["game_resumed"]
    offered = resumed[0]["args"][0]["opening"]["choices"][0]["id"]  # a resumed frame's own id
    assert old_tab.get_received() == [
        {"name": "session_ended", "args": [{"reason": "elsewhere", "session_id": opened["session_id"]}], "namespace": "/"}
    ]
    # The room is closed after it: the old tab hears no more of the run.
    new_tab.emit("player_choice", {"session_id": opened["session_id"], "choice_id": offered})
    assert "turn_update" in [e["name"] for e in new_tab.get_received()]
    assert old_tab.get_received() == []


def test_a_new_game_releases_the_old_run_and_never_the_new_one(hosted: Hosted) -> None:
    _alice, client = _client(hosted, "alice")
    first = _new(client, seed=1)
    tab = _joined(hosted, client, first["session_id"])
    second = _new(client, seed=2)
    tab.emit("join_session", {"session_id": second["session_id"]})
    events = tab.get_received()
    ended = [e["args"][0] for e in events if e["name"] == "session_ended"]
    assert ended == [{"reason": "elsewhere", "session_id": first["session_id"]}]
    assert "game_started" in [e["name"] for e in events]
    tab.emit("player_choice", {"session_id": second["session_id"], "choice_id": "a"})
    assert _ended(tab) == []


def test_a_new_game_in_another_tab_tells_the_first_tab_elsewhere(hosted: Hosted) -> None:
    # The same account, two tabs: the second tab's Begin releases the first
    # tab's run, and only the first tab hears why.
    _alice, client = _client(hosted, "alice")
    first = _new(client, seed=1)
    first_tab = _joined(hosted, client, first["session_id"])
    second_tab = _socket(hosted, client)
    second = _new(client, seed=2)
    second_tab.emit("join_session", {"session_id": second["session_id"]})
    assert [e["name"] for e in second_tab.get_received()] == ["game_started"]
    assert _ended(first_tab) == [{"reason": "elsewhere", "session_id": first["session_id"]}]
    second_tab.emit("player_choice", {"session_id": second["session_id"], "choice_id": "a"})
    assert "turn_update" in [e["name"] for e in second_tab.get_received()]
    assert first_tab.get_received() == []


def test_an_admin_end_says_ended(hosted: Hosted) -> None:
    _alice, client = _client(hosted, "alice")
    opened = _new(client)
    tab = _joined(hosted, client, opened["session_id"])
    hosted.scene.store.end(opened["session_id"])
    assert _ended(tab) == [{"reason": "ended", "session_id": opened["session_id"]}]


def test_the_idle_sweep_says_idle(hosted: Hosted) -> None:
    _alice, client = _client(hosted, "alice")
    opened = _new(client)
    tab = _joined(hosted, client, opened["session_id"])
    _age(hosted, opened["session_id"])
    hosted.scene.store.sweep_idle()
    assert _ended(tab) == [{"reason": "idle", "session_id": opened["session_id"]}]


def test_local_mode_emits_nothing_on_a_release() -> None:
    import json

    from engine.scenes.default_scene import create_app, reset_store

    reset_store()
    try:
        scene, app = create_app(testing=True, llm_fn=lambda _m: json.dumps({"narration": "x", "choices": []}))
        assert scene.store.on_release is None
        session_id = app.test_client().post("/api/game/new", json={"seed": 4}).get_json()["session_id"]
        sio = scene.socketio.test_client(app)
        sio.emit("join_session", {"session_id": session_id})
        sio.get_received()
        scene.store.delete(session_id)
        assert sio.get_received() == []
    finally:
        reset_store()


def test_the_room_is_rechecked_before_it_is_told(hosted: Hosted, monkeypatch: pytest.MonkeyPatch) -> None:
    # Like every room emit (default_scene's `_emit`): a socket whose login was
    # revoked is dropped before it hears anything (T12 fix round 1).
    _alice, client = _client(hosted, "alice")
    opened = _new(client)
    tab = _joined(hosted, client, opened["session_id"])
    original = hosted.scene._room_check
    assert original is not None
    checked: list[str] = []

    def check(room: str, *args: Any, **kwargs: Any) -> None:
        checked.append(room)
        original(room, *args, **kwargs)

    monkeypatch.setattr(hosted.scene, "_room_check", check)
    hosted.scene.store.end(opened["session_id"])
    assert checked == [opened["session_id"]]
    assert _ended(tab) == [{"reason": "ended", "session_id": opened["session_id"]}]
