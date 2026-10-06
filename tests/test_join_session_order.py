"""
``join_session`` joins a room only after the session is found (v0.20.0 T2;
spec survey finding 6, §6.4).

THE DEFECT. ``on_join`` called ``join_room(session_id)`` BEFORE it checked the
session existed, so any socket could sit in any room -- one for a session not
yet created included -- and receive that room's stream when it came. The
socket was answered ``error: session not found`` and stayed in the room.

THE FIX. ``self.store.require`` first; ``join_room`` only on success. The
answers a client sees are unchanged (the local-mode golden pins both joins).
"""

from __future__ import annotations

from typing import Any

from tests.local_golden import scripted_model


def _app() -> tuple[Any, Any]:
    from engine.scenes.default_scene import create_app

    return create_app(testing=True, llm_fn=scripted_model)


def test_an_unknown_session_puts_the_socket_in_no_room() -> None:
    scene, app = _app()
    room = "notyetasession"
    sio = scene.socketio.test_client(app)
    try:
        sio.get_received()
        sio.emit("join_session", {"session_id": room})
        answered = sio.get_received()
        assert [e["name"] for e in answered] == ["error"]
        assert answered[0]["args"][0] == {"message": "session not found"}

        # A later emit to that room must not reach this socket.
        scene.socketio.emit("narration_chunk", {"text": "for someone else"}, to=room)
        assert sio.get_received() == []
    finally:
        sio.disconnect()


def test_a_live_session_still_joins_its_room() -> None:
    """The green control: the room a found session joins does reach it."""
    scene, app = _app()
    new = app.test_client().post("/api/game/new", json={"player_name": "Tess"})
    session_id = new.get_json()["session_id"]
    sio = scene.socketio.test_client(app)
    try:
        sio.get_received()
        sio.emit("join_session", {"session_id": session_id})
        assert [e["name"] for e in sio.get_received()] == ["game_started"]
        scene.socketio.emit("narration_chunk", {"text": "for you"}, to=session_id)
        got = sio.get_received()
        assert [e["name"] for e in got] == ["narration_chunk"]
        assert got[0]["args"][0] == {"text": "for you"}
    finally:
        sio.disconnect()
