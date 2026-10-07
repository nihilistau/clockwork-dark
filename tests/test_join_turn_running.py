"""
``join_session`` says whether a turn is still running (v0.21.0, spec §6.2, S6).

A rejoining client cannot otherwise tell that ``last_turn`` is the PREVIOUS
turn while another is still being played: it would re-enable every control
over a turn the server is still running (spec §6.3, transitions 16-17).
"""

from __future__ import annotations

import json
from typing import Any

SCRIPTED = json.dumps({"narration": "Lamps.", "choices": [{"id": "a", "text": "Wait"}]})


def _started(sio: Any) -> dict[str, Any]:
    (event,) = [e for e in sio.get_received() if e["name"] == "game_started"]
    return event["args"][0]


def test_join_session_answers_turn_running() -> None:
    from engine.scenes.default_scene import create_app, reset_store

    reset_store()
    try:
        scene, app = create_app(testing=True, llm_fn=lambda _m: SCRIPTED)
        session_id = app.test_client().post("/api/game/new", json={"seed": 5}).get_json()["session_id"]
        sio = scene.socketio.test_client(app)
        sio.get_received()

        sio.emit("join_session", {"session_id": session_id})
        assert _started(sio)["turn_running"] is False

        session = scene.store.require(session_id)
        assert session.lock.acquire(blocking=False)
        try:
            sio.emit("join_session", {"session_id": session_id})
            assert _started(sio)["turn_running"] is True
        finally:
            session.lock.release()

        sio.emit("join_session", {"session_id": session_id})
        assert _started(sio)["turn_running"] is False
        sio.disconnect()
    finally:
        reset_store()


def test_turn_running_is_read_before_the_opening() -> None:
    """
    Review finding 2: read after `opening`, a turn ending between the two
    reads answers the OLD opening with `turn_running: false` -- controls live
    over a stale turn. Read first, the worst case is a fresh opening marked
    running, which the client's re-join recovers from.
    """
    from engine.scenes.default_scene import create_app, reset_store

    reset_store()
    try:
        scene, app = create_app(testing=True, llm_fn=lambda _m: SCRIPTED)
        session_id = app.test_client().post("/api/game/new", json={"seed": 5}).get_json()["session_id"]
        session = scene.store.require(session_id)
        order: list[str] = []

        class SpyLock:
            def locked(self) -> bool:
                order.append("turn_running")
                return False

        original_class, original_lock = type(session), session.lock
        spy = type(
            "SpySession",
            (original_class,),
            {"last_turn": property(lambda self: order.append("opening") or self.__dict__["last_turn"])},
        )
        session.lock = SpyLock()  # type: ignore[assignment]
        session.__class__ = spy
        try:
            sio = scene.socketio.test_client(app)
            sio.get_received()
            sio.emit("join_session", {"session_id": session_id})
            _started(sio)
            sio.disconnect()
        finally:
            session.__class__ = original_class
            session.lock = original_lock
        assert order == ["turn_running", "opening"], order
    finally:
        reset_store()
