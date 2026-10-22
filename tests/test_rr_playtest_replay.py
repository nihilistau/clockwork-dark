"""The owner's playtest, replayed (v0.23.0 addendum 4 §7, T23H).

One sequence walked end to end through the real routes (`/api/phone/action`, `/api/game/choice`), with the
storyteller stubbed from the session's build and every draw forced: ask to meet at the venue the player is in,
put the phone down, wait for them, see the arrival line and the scene's moves in one frame, type a line, leave,
and see the held texts land. Each of the owner's symptoms (a)-(d) is asserted where it used to happen.
"""

from __future__ import annotations

from tests.social_fixtures import (  # noqa: F401
    _force_stage, _live_session, _matched_in, _phone, receipts_active,
)
from tests.social_world_stub import StubNarrator

VENUE = "the_anchor"


def _choose(scene, session, choice_id: str):
    return scene.app.test_client().post("/api/game/choice", json={"session_id": session.session_id,
                                                                  "choice_id": choice_id})


def _typed(scene, session, text: str):
    return scene.app.test_client().post("/api/game/choice", json={
        "session_id": session.session_id, "choice_id": "custom", "custom_text": text})


def _actions(choices) -> set:
    return {(c.get("intent") or {}).get("action") for c in choices}


def _theirs(state, pid: str) -> list:
    return [m for t in state.social["threads"].values() for m in t.get("messages") or () if m.get("from") == pid]


def _set_up(monkeypatch):
    """A live session, a match at numbers, every draw a plan reads forced."""
    from tests.test_social_plans import _willing_meet

    _willing_meet(monkeypatch)
    scene, session = _live_session(llm_fn=StubNarrator())
    thread = _matched_in(session, "matchstick")
    pid = thread.split(":")[1]
    with session.lock:
        _force_stage(session.engine.state, pid, "numbers")
        from engine.social import messaging

        messaging.open_numbers(session.engine.state, pid)
    return scene, session, thread, pid


def _make_the_plan(scene, session, thread: str, pid: str) -> dict:
    """The player's `ask {what: meet}` for a `now` drink at The Anchor, made over the phone route, then read:
    the plan the person's answer makes."""
    from engine.social import plans

    body = _phone(scene, session, "ask", target=thread,
                  args={"what": "meet", "kind": "drinks", "venue": VENUE, "when": "now"})
    assert not any(r.get("refused") for r in body.get("tool_receipts") or []), body
    state = session.engine.state
    for _ in range(12):
        if plans.open_for(state, pid):
            break
        _phone(scene, session, "wait", args={"until": "1h"})
        if state.location_id != VENUE:                       # the wait never moves the player; a guard anyway
            raise AssertionError(state.location_id)
    (row,) = plans.open_for(state, pid)
    return row


def test_the_owners_playtest_end_to_end(receipts_active, monkeypatch) -> None:
    from engine import social
    from engine.social import matching, plans

    scene, session, thread, pid = _set_up(monkeypatch)
    state = session.engine.state
    name = matching._name(state, pid)

    # the player is at The Anchor before asking, through the Places app
    arrived = _phone(scene, session, "go", VENUE)
    assert state.location_id == VENUE
    # (b) the row after a Places arrival holds the venue's choices and no "go to <here>"
    assert all((c.get("intent") or {}).get("target") != VENUE for c in arrived["choices"])
    # (c) the row IS the frame: last_turn and the row agree, and the place is the venue, not "the city"
    assert session.last_turn["choices"] == arrived["choices"]

    row = _make_the_plan(scene, session, thread, pid)
    assert row["venue"] == VENUE and row["when"] == "now"

    # put the phone down: (d) the row is not empty without a refresh, and "Wait for" is on it
    down = _phone(scene, session, "put_down")
    assert down["choices"] and session.last_turn["choices"] == down["choices"]
    assert not social.scene_open(state)
    wait = next(c for c in down["choices"] if (c.get("intent") or {}).get("target") == f"plan:{row['id']}")
    assert wait["text"] == f"Wait for {name}"
    assert all((c.get("intent") or {}).get("target") != VENUE for c in down["choices"])
    # (a) before they arrive nobody has landed an "I'm here"
    assert not [m for m in _theirs(state, pid) if (m.get("decision") or {}).get("situation") == "arrived"]

    # wait for them: the arrival line and the scene's moves in the SAME frame
    resp = _choose(scene, session, wait["id"])
    assert resp.status_code == 200, resp.get_data(as_text=True)
    frame = resp.get_json()
    assert social.scene_open(state)
    # the engine's arrival words ride the wait's receipt (the stub narrator does not repeat a receipt's words)
    assert any(f"{name} arrives." in str(r) for r in frame["tool_receipts"]), frame["tool_receipts"]
    assert {"scene", "close"} <= _actions(frame["choices"]), frame["choices"]
    assert session.last_turn["choices"] == frame["choices"]
    assert plans.get(state, row["id"])["status"] == "met"

    # type a line to them in the scene: it runs as `talk`, and the row is never empty
    typed = _typed(scene, session, "you have a nice laugh")
    assert typed.status_code == 200, typed.get_data(as_text=True)
    said = typed.get_json()
    assert any("talk" in str(r.get("intent") or r.get("args") or r) for r in said["tool_receipts"]), said["tool_receipts"]
    assert said["choices"]
    assert social.scene_open(state)

    # nothing lands while together: a due text is held, never dropped
    from engine.game import clock
    from engine.social import messaging
    from engine.social.kinds import Decision

    landed = len(_theirs(state, pid))
    with session.lock:
        messaging.queue_due(state, pid, thread, Decision(situation="reply"), state.world_clock_hours + 0.02)
        clock.advance_time(state, 0.2)
    assert len(_theirs(state, pid)) == landed
    assert [e for e in state.social["queue"] if e["pid"] == pid and e["kind"] == "reply"]

    # leave: the held text lands when the scene ends
    leave = next(c for c in said["choices"] if (c.get("intent") or {}).get("action") == "close")
    out = _choose(scene, session, leave["id"])
    assert out.status_code == 200, out.get_data(as_text=True)
    assert len(_theirs(state, pid)) > landed                     # the held text, and the scene's own after-text
    assert not [e for e in state.social["queue"] if e["pid"] == pid and e["kind"] == "reply" and e.get("held")]
    assert out.get_json()["choices"]


def test_d_the_row_is_never_empty_after_a_phone_action(receipts_active, monkeypatch) -> None:
    """(d): `put_down` with and without a time jump, and a Places arrival: each answers with a non-empty row."""
    scene, session, _thread, _pid = _set_up(monkeypatch)
    assert _phone(scene, session, "put_down")["choices"]
    _phone(scene, session, "wait", args={"until": "1h"})
    assert _phone(scene, session, "put_down")["choices"]
    assert _phone(scene, session, "go", VENUE)["choices"]
    assert _phone(scene, session, "put_down")["choices"]


def test_typing_at_home_runs_an_offered_choice_and_narrates_the_rest(receipts_active, monkeypatch) -> None:
    """§7.5 step 8: a line naming an offered activity runs it; one naming nothing is narrated only."""
    scene, session, _thread, _pid = _set_up(monkeypatch)
    _phone(scene, session, "put_down")
    state = session.engine.state
    state.location_id = "apt_lounge"
    before = state.world_clock_hours
    ran = _typed(scene, session, "tidy up").get_json()
    assert state.world_clock_hours > before
    assert any(r.get("typed") for r in ran["tool_receipts"])
    after = state.world_clock_hours
    said = _typed(scene, session, "the light is nice today").get_json()
    assert state.world_clock_hours == after
    assert not any(r.get("typed") or r.get("refused") for r in said["tool_receipts"])
    assert said["choices"]


def test_b_head_home_reaches_the_rooms(receipts_active, monkeypatch) -> None:
    """(b): from the venue, "Head home" is on the row and, once taken, the row offers the flat's rooms."""
    scene, session, _thread, _pid = _set_up(monkeypatch)
    _phone(scene, session, "go", VENUE)
    row = _phone(scene, session, "put_down")["choices"]
    home = next((c for c in row if (c.get("intent") or {}).get("target") == "apt_lounge"), None)
    assert home, row
    resp = _choose(scene, session, home["id"])
    assert resp.status_code == 200, resp.get_data(as_text=True)
    assert session.engine.state.location_id == "apt_lounge"
    assert "travel" in _actions(resp.get_json()["choices"]), resp.get_json()["choices"]


def test_c_the_place_is_the_venue_never_the_city(receipts_active, monkeypatch) -> None:
    """(c): after the Places arrival the location and its name are the venue's, not "the city"."""
    scene, session, _thread, _pid = _set_up(monkeypatch)
    _phone(scene, session, "go", VENUE)
    _phone(scene, session, "put_down")
    state = session.engine.state
    assert state.location_id == VENUE
    assert "city" not in str(state.location_name or "").casefold()
    assert "city" not in str(state.location_id).casefold()


def test_d_a_refresh_returns_the_row_the_player_last_saw(receipts_active, monkeypatch) -> None:
    """(d): the join frame a refresh gets carries the same choices as the last answer."""
    scene, session, _thread, _pid = _set_up(monkeypatch)
    _phone(scene, session, "go", VENUE)
    seen = _phone(scene, session, "put_down")["choices"]
    assert seen
    sock = scene.socketio.test_client(scene.app, flask_test_client=scene.app.test_client())
    sock.emit("join_session", {"session_id": session.session_id})
    frames = [e["args"][0] for e in sock.get_received() if e["name"] == "game_started"]
    assert frames and frames[-1]["opening"]["choices"] == seen
