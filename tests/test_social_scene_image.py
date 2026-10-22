"""READ RECEIPTS' scene plate reaches every frame (v0.23.0, a player-facing fix).

The world layer draws core's ``ScenePlate`` from the client's ``sceneImage``, which is reduced from a frame's
``scene_image``. The resume frame, a phone action's answer and a world turn's payload carried none, so the plate
fell back to the procedural wash although the place's art was shipped and served. Every frame kind now carries the
plate for where the player is and the hour it is, looked up here independently through ``providers.peek``.
"""

from __future__ import annotations

from tests.social_fixtures import (  # noqa: F401
    _live_session, _matched_in, _phone, receipts_active,
)
from tests.social_world_stub import StubNarrator


def _plate(state) -> str:
    """The shipped plate for the state's place and daypart (the lookup the engine is meant to use)."""
    from engine.media.providers import ImageRequest, peek

    url = peek(ImageRequest(subject_id=state.location_id, kind="location", time_of_day=state.time_of_day,
                            evil_phase=state.evil_phase.value)).url
    assert url.startswith("/story-art/scenes/"), (state.location_id, state.time_of_day, url)
    return url


def _slug(location_id: str) -> str:
    return location_id.replace("_", "-")


def test_the_resume_frame_carries_the_plate(receipts_active) -> None:
    from engine.scenes.default_state import resume_opening

    _, session = _live_session(llm_fn=StubNarrator())
    state = session.engine.state
    frame = resume_opening(state, session.ledger)
    assert frame["resumed"] and frame["scene_image"] == _plate(state)
    assert _slug(state.location_id) in frame["scene_image"]


def test_a_phone_action_carries_the_plate_and_follows_a_go(receipts_active) -> None:
    scene, session = _live_session(llm_fn=StubNarrator())
    state = session.engine.state
    body = _phone(scene, session, "put_down")
    home = _plate(state)
    assert body["scene_image"] == home
    body = _phone(scene, session, "go", "the_anchor")
    assert state.location_id == "the_anchor"
    assert body["scene_image"] == _plate(state) != home and "the-anchor" in body["scene_image"]
    # A refresh is sent `last_turn`: it must not keep the flat's plate after the move.
    assert session.last_turn["scene_image"] == body["scene_image"]


def test_a_phone_wait_into_another_daypart_moves_the_plate(receipts_active) -> None:
    scene, session = _live_session(llm_fn=StubNarrator())
    state = session.engine.state
    _phone(scene, session, "go", "the_anchor")              # night and dusk plates both shipped there
    before = (state.time_of_day, _plate(state))
    body = _phone(scene, session, "wait", args={"until": "evening"})
    if state.time_of_day == before[0]:
        body = _phone(scene, session, "wait", args={"until": "morning"})
    assert state.time_of_day != before[0]
    assert body["scene_image"] == _plate(state)


def test_a_world_turn_room_move_carries_the_new_rooms_plate(receipts_active) -> None:
    scene, session = _live_session(llm_fn=StubNarrator())
    state = session.engine.state
    _phone(scene, session, "wait", args={"until": "1h"})     # a time jump: the row is rebuilt, the rooms on it
    _phone(scene, session, "put_down")
    start = state.location_id
    move = next(c for c in session.last_turn["choices"] if (c.get("intent") or {}).get("action") == "travel")
    resp = scene.app.test_client().post("/api/game/choice", json={"session_id": session.session_id,
                                                                  "choice_id": move["id"]})
    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_json()
    assert state.location_id == move["intent"]["target"] != start
    assert body["scene_image"] == _plate(state) and _slug(state.location_id) in body["scene_image"]
    assert session.last_turn["scene_image"] == body["scene_image"]


def test_the_arrival_frame_carries_the_plate(receipts_active, monkeypatch) -> None:
    """T23C's second turn_update (a plan's arrival opening a scene) carries the plate, as its HTTP answer does."""
    from engine.scenes import default_scene
    from engine.social import plans
    from tests.test_social_plans import _willing_meet

    scene, session = _live_session(llm_fn=StubNarrator())
    state = session.engine.state
    pid = _matched_in(session, "matchstick").split(":")[1]
    _phone(scene, session, "put_down")
    _willing_meet(monkeypatch)
    monkeypatch.setattr(plans, "_arrival", lambda s, r, e, at: (at, at))
    state.location_id = "apt_lounge"
    row = plans.make(state, pid, kind="your_place", when="now", venue="")
    state.social["plans"][row["id"]]["arrived"] = True
    sent: list[tuple[str, dict]] = []
    frame = {"narration": "You look around.", "choices": [{"id": "x", "text": "Look around"}]}
    payload, _, _ = default_scene._meet_if_here(session, (dict(frame), "", False),
                                                lambda event, body: sent.append((event, body)))
    plate = _plate(state)
    assert "apt-lounge" in plate
    assert payload["scene_image"] == plate == sent[0][1]["scene_image"] == session.last_turn["scene_image"]
