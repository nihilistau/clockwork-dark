"""
The phone catalogue (spec §7, §19.2): every legal action resolves through its
skill to a receipt; every illegal one to a refusal in the engine's words,
never [] and never a silent no-op. Legality is re-checked at execution.
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.social_fixtures import (  # noqa: F401
    _act, _engine, _top, matched, matched_numbers, receipts_active, receipts_state,
)


# -- the mechanism --------------------------------------------------------------

def test_an_unknown_action_is_refused_in_words(receipts_state) -> None:
    receipt = _act(receipts_state, "teleport")
    assert receipt["refused"] is True and "teleport" in receipt["result"]["error"]


def test_a_malformed_intent_is_refused_not_dropped(receipts_state) -> None:
    from engine.agents.tool_dispatcher import execute_phone_intent

    receipt = execute_phone_intent({"nonsense": 1}, _engine(receipts_state))
    assert receipt["refused"] is True


def test_an_enum_outside_its_values_is_refused(receipts_state) -> None:
    receipt = _act(receipts_state, "wait", args={"until": "forever"})
    assert receipt["refused"] is True and "until" in receipt["result"]["error"]


def test_text_over_its_cap_is_refused_never_cut(receipts_state) -> None:
    receipt = _act(receipts_state, "edit_profile", target="matchstick",
                   args={"field": "bio"}, text="x" * 601)
    assert receipt["refused"] is True and "600" in receipt["result"]["error"]



def _players_last(state, thread: str) -> dict:
    """The player's newest message in ``thread`` (v0.23.0: a person who is free reads and answers at once,
    so their due reply may already follow it)."""
    return [m for m in state.social["threads"][thread]["messages"] if m["from"] == "player"][-1]

# -- rows: wait, edit_profile, set_receipts ------------------------------------

@pytest.mark.parametrize("until, hours", [("1h", 1.0)])
def test_wait_advances_the_clock_through_advance_time(receipts_state, until, hours) -> None:
    before = receipts_state.world_clock_hours
    receipt = _act(receipts_state, "wait", args={"until": until})
    assert receipt["success"] is True
    assert receipts_state.world_clock_hours == pytest.approx(before + hours)


def test_wait_morning_sleeps_to_conversation_yamls_morning(receipts_state) -> None:
    """v0.23.0 §3.6: `morning` is conversation.yaml's `clock.morning` (7), not a literal 8."""
    _act(receipts_state, "wait", args={"until": "morning"})
    assert receipts_state.world_hour == 7


def test_wait_next_stops_at_the_cap_with_nothing_queued(receipts_state) -> None:
    receipts_state.social["queue"] = []
    before = receipts_state.world_clock_hours
    _act(receipts_state, "wait", args={"until": "next"})
    assert receipts_state.world_clock_hours - before == pytest.approx(8.0)


def test_edit_profile_and_receipts_write_through_effects(receipts_state) -> None:
    assert _act(receipts_state, "edit_profile", target="matchstick", args={"field": "bio"},
                text="climbs, cooks, reads")["success"]
    assert receipts_state.social["player"]["bios"]["matchstick"] == "climbs, cooks, reads"
    assert _act(receipts_state, "set_receipts", target="natter", args={"to": "off"})["success"]
    assert receipts_state.social["settings"]["receipts"] is False


def test_set_wake_stores_wake_for_messages_and_the_payload_says_so(receipts_state) -> None:
    """"Wake me for messages" (v0.23.0 T22): the Settings switch's verb writes the flag the sleep reads."""
    from engine.social import payload

    assert payload.phone_block(receipts_state)["settings"]["wake_for_messages"] is False
    assert _act(receipts_state, "set_wake", args={"to": "on"})["success"]
    assert receipts_state.social["settings"]["wake_for_messages"] is True
    assert payload.phone_block(receipts_state)["settings"]["wake_for_messages"] is True
    assert _act(receipts_state, "set_wake", args={"to": "off"})["success"]
    assert receipts_state.social["settings"]["wake_for_messages"] is False


# -- the channel ----------------------------------------------------------------

def test_a_local_phone_action_over_the_socket_answers_a_turn_update_with_the_phone(receipts_active) -> None:
    """Local mode never admits a turn at all, so this proves the socket path; T14's hosted twin proves no admission (F18)."""
    from engine.scenes.default_scene import create_app

    scene, app = create_app(testing=True)
    http = app.test_client()
    sid = http.post("/api/game/new", json={"player_name": "Sam", "seed": 3}).get_json()["session_id"]
    sock = scene.socketio.test_client(app, flask_test_client=http)
    sock.emit("join_session", {"session_id": sid})
    sock.get_received()
    sock.emit("phone_action", {"session_id": sid, "action": "wait", "target": "", "args": {"until": "1h"}})
    events = {e["name"]: e["args"][0] for e in sock.get_received()}
    assert events["turn_update"]["narration"] == ""
    assert "phone" in events["turn_update"]["state"]


def test_the_http_twin(receipts_active) -> None:
    from engine.scenes.default_scene import create_app

    _, app = create_app(testing=True)
    http = app.test_client()
    sid = http.post("/api/game/new", json={"seed": 3}).get_json()["session_id"]
    ok = http.post("/api/phone/action", json={"session_id": sid, "action": "wait", "args": {"until": "1h"}})
    assert ok.status_code == 200 and ok.get_json()["narration"] == ""
    refused = http.post("/api/phone/action", json={"session_id": sid, "action": "wait", "args": {"until": "x"}})
    assert refused.status_code == 200 and refused.get_json()["state"]["phone"]["refusal"]["reason"]


def test_each_phone_action_logs_its_name_and_time_never_its_text(receipts_active, caplog) -> None:
    """
    `routes._run` logs one INFO line per phone action (v0.22.0 T30, spec
    §17.1's cadence measurement): the action's NAME and a monotonic time,
    never the text the player typed.
    """
    import logging
    import re

    from engine.scenes.default_scene import create_app

    _, app = create_app(testing=True)
    http = app.test_client()
    sid = http.post("/api/game/new", json={"seed": 3}).get_json()["session_id"]
    caplog.set_level(logging.INFO, logger="engine.social.routes")
    http.post("/api/phone/action", json={"session_id": sid, "action": "wait", "args": {"until": "1h"}})
    http.post("/api/phone/action", json={"session_id": sid, "action": "send", "target": "nobody",
                                         "args": {"kind": "text"}, "text": "a secret only I typed"})
    lines = [r.getMessage() for r in caplog.records if "operation=phone_action" in r.getMessage()]
    assert len(lines) == 2, lines
    pattern = re.compile(r"^\[social\] Phone action \(operation=phone_action, action=(\w+), t=(\d+\.\d+)\)$")
    found = [pattern.match(line) for line in lines]
    assert all(found), lines
    assert [m.group(1) for m in found] == ["wait", "send"]
    assert float(found[0].group(2)) <= float(found[1].group(2))
    assert not any("secret" in r.getMessage() for r in caplog.records)


def test_an_action_not_in_the_catalogue_is_logged_as_a_fixed_token(receipts_active, caplog) -> None:
    """
    The logged name is a catalogue verb or `?` (T30 review I1): a crafted `action` is the client's own
    text, so it never reaches the log -- neither its words nor an embedded newline that could forge a line.
    """
    import logging

    from engine.scenes.default_scene import create_app

    _, app = create_app(testing=True)
    http = app.test_client()
    sid = http.post("/api/game/new", json={"seed": 3}).get_json()["session_id"]
    caplog.set_level(logging.INFO, logger="engine.social.routes")
    http.post("/api/phone/action", json={"session_id": sid, "action": "x\nsecret words", "args": {}})
    lines = [r.getMessage() for r in caplog.records if "operation=phone_action" in r.getMessage()]
    assert len(lines) == 1 and "action=?," in lines[0], lines
    assert "\n" not in lines[0]
    assert not any("secret" in r.getMessage() for r in caplog.records)


def test_player_choice_is_refused_while_the_phone_is_up(receipts_active) -> None:
    """v0.23.0 T11 (spec §8.2-§8.3; Plan decision 18): the socket choice runs a world turn, refused only while
    the phone is up -- v0.22's "played on the phone" refusal is gone."""
    from engine.scenes.default_scene import create_app
    from engine.social import world

    scene, app = create_app(testing=True)
    http = app.test_client()
    sid = http.post("/api/game/new", json={"seed": 3}).get_json()["session_id"]
    sock = scene.socketio.test_client(app, flask_test_client=http)
    sock.emit("player_choice", {"session_id": sid, "choice_id": "b"})
    errors = [e for e in sock.get_received() if e["name"] == "turn_error"]
    assert errors and errors[0]["args"][0] == {"message": world.PHONE_UP_REFUSAL, "busy": False, "phone_up": True}


@pytest.mark.parametrize("slug", ["clockwork-dark", "wicked-garden", "neon-city", "the-long-con", "dev-story", "hue-and-cry"])
def test_another_story_registers_no_phone_route_or_event(slug) -> None:
    from engine.games import registry
    from engine.scenes.default_scene import create_app

    registry.activate(slug)
    try:
        scene, app = create_app(testing=True)
        rules = {r.rule for r in app.url_map.iter_rules()}
        assert not any(rule.startswith(("/api/phone", "/api/social")) for rule in rules)
        assert "phone_action" not in scene.socketio.server.handlers.get("/", {})
    finally:
        registry.deactivate()


# -- further ----------------------------------------------------------------------

def test_a_target_outside_the_verb_s_options_is_refused_at_execution(receipts_state) -> None:
    receipt = _act(receipts_state, "edit_profile", target="natter", args={"field": "bio"}, text="hi")
    assert receipt["refused"] is True and "natter" in receipt["result"]["error"]
    assert "bios" not in receipts_state.social["player"]


def test_text_on_a_verb_that_takes_none_is_refused(receipts_state) -> None:
    receipt = _act(receipts_state, "wait", args={"until": "1h"}, text="hello")
    assert receipt["refused"] is True and "text" in receipt["result"]["error"]


def test_the_http_choice_is_refused_while_the_phone_is_up(receipts_active) -> None:
    from engine.scenes.default_scene import create_app
    from engine.social import world

    _, app = create_app(testing=True)
    http = app.test_client()
    sid = http.post("/api/game/new", json={"seed": 3}).get_json()["session_id"]
    answered = http.post("/api/game/choice", json={"session_id": sid, "choice_id": "b"})
    assert answered.status_code == 409 and answered.get_json() == {"error": world.PHONE_UP_REFUSAL, "phone_up": True}


def test_a_phone_block_that_cannot_import_is_an_error_not_a_debug_line(receipts_state, monkeypatch, caplog) -> None:
    """Pre-flight F25: T1's quiet ImportError branch is gone; the fault is logged at ERROR."""
    import logging

    from engine import social

    def _broken() -> None:
        raise ImportError("engine.social.payload is missing")

    monkeypatch.setattr(social, "boot", _broken)
    with caplog.at_level(logging.DEBUG, logger="engine.game.state"):
        client = receipts_state.to_client_dict()
    assert "phone" not in client
    assert [r.levelno for r in caplog.records if "Phone block failed" in r.getMessage()] == [logging.ERROR]


def _raise_in_set_receipts(monkeypatch) -> None:
    from engine.social import turn

    def _broken(*_a, **_k):
        raise KeyError("settings slice is malformed")

    monkeypatch.setattr(turn, "set_receipts", _broken)


def test_a_phone_skill_that_raises_is_a_refusal_never_a_silent_no_op(receipts_state, monkeypatch) -> None:
    """Rule 1: a faulting skill still answers the player, in the engine's words."""
    from engine.agents.tool_dispatcher import PHONE_FAULT

    _raise_in_set_receipts(monkeypatch)
    receipt = _act(receipts_state, "set_receipts", target="natter", args={"to": "off"})
    assert receipt["refused"] is True and receipt["success"] is False
    assert receipt["result"]["error"].startswith(PHONE_FAULT)
    assert receipts_state.social["settings"]["receipts"] is True      # nothing changed


def test_a_raising_skill_reaches_the_phone_as_a_refusal_over_http_and_the_socket(receipts_active, monkeypatch) -> None:
    from engine.scenes.default_scene import create_app

    _raise_in_set_receipts(monkeypatch)
    scene, app = create_app(testing=True)
    http = app.test_client()
    sid = http.post("/api/game/new", json={"seed": 3}).get_json()["session_id"]
    body = {"session_id": sid, "action": "set_receipts", "target": "natter", "args": {"to": "off"}}
    answered = http.post("/api/phone/action", json=body)
    assert answered.status_code == 200
    assert answered.get_json()["state"]["phone"]["refusal"]["reason"]
    sock = scene.socketio.test_client(app, flask_test_client=http)
    sock.emit("join_session", {"session_id": sid})
    sock.get_received()
    sock.emit("phone_action", body)
    events = {e["name"]: e["args"][0] for e in sock.get_received()}
    assert events["turn_update"]["state"]["phone"]["refusal"]["reason"]
    assert events["turn_update"]["receipts"][0]["refused"] is True


def test_the_label_is_read_under_the_lock_and_rides_on_the_receipt(receipts_active) -> None:
    from engine.scenes.default_scene import create_app

    _, app = create_app(testing=True)
    http = app.test_client()
    sid = http.post("/api/game/new", json={"seed": 3}).get_json()["session_id"]
    turn = http.post("/api/phone/action", json={"session_id": sid, "action": "wait", "args": {"until": "1h"}})
    assert turn.get_json()["receipts"][0]["label"] == "Wait"


# -- rows: swipe, like, like_back, pass, unmatch, block (T7) --------------------

def _verb(state, action):
    from engine.social import intents

    return next((v for v in intents.legal_phone_intents(state) if v.action == action), None)


def test_swipe_is_legal_on_the_top_card_while_likes_remain(receipts_state) -> None:
    from engine.game.effects import apply_effect

    pid = _top(receipts_state, "matchstick")
    assert _verb(receipts_state, "swipe").targets == (pid,)
    assert _act(receipts_state, "swipe", target="p0001" if pid != "p0001" else "p0002",
                args={"dir": "like"})["refused"] is True                     # not the top card
    apply_effect(receipts_state, {"type": "social_app", "app": "matchstick", "op": "set", "values": {"likes_left": 0}})
    assert _verb(receipts_state, "swipe") is None
    refused = _act(receipts_state, "swipe", target=pid, args={"dir": "pass"})
    assert refused["refused"] is True and refused["result"]["error"] == "No likes left today."


def test_like_is_legal_on_the_browse_card_with_a_comment_up_to_140(receipts_state) -> None:
    pid = _top(receipts_state, "front_porch")
    verb = _verb(receipts_state, "like")
    assert verb.targets == (pid,) and "photo_0" in verb.extra["on"] and "prompt_0" in verb.extra["on"]
    assert _act(receipts_state, "like", target=pid, args={"on": "photo_0", "comment": "y" * 141})["refused"] is True
    assert _act(receipts_state, "like", target=pid, args={"on": "nowhere"})["refused"] is True
    missing = _act(receipts_state, "like", target=pid, args={"comment": "hi"})     # spec §7.1: `on` is required
    assert missing["refused"] is True and "on is required" in missing["result"]["error"]
    assert _act(receipts_state, "like", target=pid, args={"on": "prompt_0", "comment": "y" * 140})["success"]
    assert receipts_state.social["people"][pid]["apps"]["front_porch"]["comment"] == "y" * 140


def test_like_back_takes_only_a_likes_you_pid(receipts_state) -> None:
    from engine.game import clock

    assert _verb(receipts_state, "like_back") is None
    clock.advance_time(receipts_state, 24 * 3)
    waiting = [row["pid"] for row in receipts_state.social["apps"]["front_porch"]["likes_you"]]
    assert set(_verb(receipts_state, "like_back").targets) == set(waiting)
    assert _act(receipts_state, "like_back", target=_top(receipts_state, "front_porch"))["refused"] is True
    assert _act(receipts_state, "like_back", target=waiting[0])["success"]


def test_pass_takes_the_browse_card_or_a_likes_you_pid(receipts_state) -> None:
    from engine.game import clock

    clock.advance_time(receipts_state, 24 * 3)
    top = _top(receipts_state, "front_porch")
    waiting = receipts_state.social["apps"]["front_porch"]["likes_you"][0]["pid"]
    assert {top, waiting} <= set(_verb(receipts_state, "pass").targets)
    assert _act(receipts_state, "pass", target=_top(receipts_state, "matchstick"))["refused"] is True
    assert _act(receipts_state, "pass", target=top)["success"]
    assert _act(receipts_state, "pass", target=waiting)["success"]
    assert all(row["pid"] != waiting for row in receipts_state.social["apps"]["front_porch"]["likes_you"])


def test_unmatch_takes_only_a_match(receipts_state, matched) -> None:
    assert _verb(receipts_state, "unmatch") is None
    assert _act(receipts_state, "unmatch", target="p0001")["refused"] is True
    pid = matched("matchstick").split(":", 1)[1]
    assert _verb(receipts_state, "unmatch").targets == (pid,)
    assert _act(receipts_state, "unmatch", target=pid)["success"]


def test_block_takes_anyone_with_a_thread(receipts_state, matched) -> None:
    assert _verb(receipts_state, "block") is None
    pid = matched("matchstick").split(":", 1)[1]
    assert _act(receipts_state, "unmatch", target=pid)["success"]
    assert _verb(receipts_state, "block").targets == (pid,)            # an unmatched thread still counts
    assert _act(receipts_state, "block", target=pid)["success"]
    assert _verb(receipts_state, "block") is None


# -- rows: send, open_thread, ask (T8) -------------------------------------------

def test_send_is_legal_on_a_thread_and_checks_the_app_s_capabilities(receipts_state, matched) -> None:
    assert _verb(receipts_state, "send") is None                         # no thread yet
    thread = matched("matchstick")
    assert _verb(receipts_state, "send").targets == (thread,)
    assert _act(receipts_state, "send", target=thread, args={"kind": "text"}, text="hi there")["success"]
    over = _act(receipts_state, "send", target=thread, args={"kind": "text"}, text="x" * 601)
    assert over["refused"] and "600" in over["result"]["error"]
    voice = _act(receipts_state, "send", target=thread, args={"kind": "voice"}, text="(voice)")
    assert voice["refused"] and voice["result"]["error"] == "Matchstick can't send voice notes"
    assert _act(receipts_state, "send", target=thread, args={"kind": "smoke"}, text="hi")["refused"]
    assert _act(receipts_state, "send", target="matchstick:p9999", args={"kind": "text"}, text="hi")["refused"]


def test_send_after_an_unmatch_is_refused_with_the_reason(receipts_state, matched) -> None:
    thread = matched("matchstick")
    assert _act(receipts_state, "unmatch", target=thread.split(":", 1)[1])["success"]
    refused = _act(receipts_state, "send", target=thread, args={"kind": "text"}, text="hello?")
    assert refused["refused"] and "unmatched" in refused["result"]["error"]


def test_open_thread_marks_read_and_sets_focus(receipts_state, matched) -> None:
    from engine.social import messaging

    assert _verb(receipts_state, "open_thread") is None
    thread = matched("matchstick")
    pid = thread.split(":", 1)[1]
    messaging.new_message(receipts_state, thread, pid, "text", bubbles=["hey"])
    assert receipts_state.social["threads"][thread]["unread"] == 1
    assert _act(receipts_state, "open_thread", target=thread)["success"]
    assert receipts_state.social["threads"][thread]["unread"] == 0
    assert receipts_state.social["threads"][thread]["focus"] >= 1
    assert receipts_state.social["open_thread"] == thread
    assert _act(receipts_state, "unmatch", target=pid)["success"]
    assert _verb(receipts_state, "open_thread") is None                  # an unmatched thread is gone


def test_ask_number_is_legal_only_at_talking(receipts_state, matched) -> None:
    from tests.social_fixtures import _force_stage

    thread = matched("matchstick")
    pid = thread.split(":", 1)[1]
    assert _verb(receipts_state, "ask") is None                          # matched, not talking
    assert _act(receipts_state, "ask", target=thread, args={"what": "number"})["refused"] is True
    _force_stage(receipts_state, pid, "talking")
    assert _verb(receipts_state, "ask").targets == (thread,)
    assert _act(receipts_state, "ask", target=thread, args={"what": "meet"})["refused"] is True   # too soon: numbers first
    asked = _act(receipts_state, "ask", target=thread, args={"what": "number"})
    assert asked["success"], asked
    request = _players_last(receipts_state, thread)
    assert request["from"] == "player" and request["kind"] == "request" and request["ask"] == "number"


# -- rows: ask (number, exclusive), answer, end (T9) -------------------------------

def test_ask_exclusive_is_legal_only_at_dating_and_says_what_it_asks(receipts_state, matched) -> None:
    from engine.social import intents
    from tests.social_fixtures import _force_stage

    thread = matched("matchstick")
    pid = thread.split(":", 1)[1]
    _force_stage(receipts_state, pid, "dating")
    verb = _verb(receipts_state, "ask")
    assert verb.targets == (thread,) and verb.extra["what"] == ("exclusive", "meet")   # a meet-up too, from numbers on (T24)
    assert _act(receipts_state, "ask", target=thread, args={"what": "number"})["refused"] is True
    label = intents.label_of(receipts_state, {"action": "ask", "target": thread, "args": {"what": "exclusive"}})
    assert label.startswith("Ask ") and label.endswith(" to be exclusive")
    asked = _act(receipts_state, "ask", target=thread, args={"what": "exclusive"})
    assert asked["success"], asked
    assert _players_last(receipts_state, thread)["ask"] == "exclusive"


def test_a_spent_ask_is_give_it_a_while_while_other_threads_are_offered(receipts_state, matched) -> None:
    from tests.social_fixtures import _force_stage

    first = matched("matchstick")
    second = matched("front_porch")
    for thread in (first, second):
        _force_stage(receipts_state, thread.split(":", 1)[1], "talking")
    for _ in range(2):
        assert _act(receipts_state, "ask", target=first, args={"what": "number"})["success"]
    assert _verb(receipts_state, "ask").targets == (second,)          # the spent one is not offered
    refused = _act(receipts_state, "ask", target=first, args={"what": "number"})
    assert refused["refused"] and refused["result"]["error"] == "Give it a while"


def test_answer_takes_only_an_open_request_of_theirs(receipts_state, matched) -> None:
    from engine.social import relationships
    from tests.social_fixtures import _at, _force_stage, _set_person

    assert _verb(receipts_state, "answer") is None
    thread = matched("matchstick")
    pid = thread.split(":", 1)[1]
    _force_stage(receipts_state, pid, "talking")
    _set_person(receipts_state, pid, **_at(relationships.gate_spec("numbers")))
    rid = relationships.apply_proposal(receipts_state, pid, "offer_number")["request_id"]
    assert _verb(receipts_state, "answer").targets == (rid,)
    assert _act(receipts_state, "answer", target=rid, args={"reply": "maybe"})["refused"] is True
    assert _act(receipts_state, "answer", target="r999", args={"reply": "yes"})["refused"] is True
    assert _act(receipts_state, "answer", target=rid, args={"reply": "later"})["success"]
    assert _verb(receipts_state, "answer").targets == (rid,)          # later: still open
    assert _act(receipts_state, "answer", target=rid, args={"reply": "yes"})["success"]
    assert _verb(receipts_state, "answer") is None


def test_end_takes_a_live_relationship(receipts_state, matched) -> None:
    assert _verb(receipts_state, "end") is None
    pid = matched("matchstick").split(":", 1)[1]
    assert _verb(receipts_state, "end").targets == (pid,)
    assert _act(receipts_state, "end", target=pid)["success"]
    assert _verb(receipts_state, "end") is None
    assert _act(receipts_state, "end", target=pid)["refused"] is True


# -- rows: ask for media, send media (T19) -----------------------------------------


def test_ask_offers_a_photo_only_where_the_app_carries_it_and_the_stage_allows(receipts_state, matched) -> None:
    from engine.social import messaging
    from tests.social_fixtures import _force_stage

    thread = matched("matchstick")
    pid = thread.split(":", 1)[1]
    _force_stage(receipts_state, pid, "talking")
    assert "photo" not in _verb(receipts_state, "ask").extra["what"]          # Matchstick carries text only
    refused = _act(receipts_state, "ask", target=thread, args={"what": "photo"})
    assert refused["refused"] and refused["result"]["error"] == "Matchstick can't send photos"
    _force_stage(receipts_state, pid, "numbers")
    messaging.open_numbers(receipts_state, pid)
    verb = _verb(receipts_state, "ask")
    natter, texts = f"natter:{pid}", f"texts:{pid}"
    assert natter in verb.targets and texts in verb.targets
    assert {"photo", "voice", "video"} <= set(verb.extra["what"])
    asked = _act(receipts_state, "ask", target=natter, args={"what": "photo"})
    assert asked["success"], asked
    message = _players_last(receipts_state, natter)
    assert message["kind"] == "request" and message["ask"] == "photo"
    video = _act(receipts_state, "ask", target=texts, args={"what": "video"})
    assert video["refused"] and video["result"]["error"] == "Texts can't send videos"


def test_ask_for_a_video_is_too_soon_before_numbers(receipts_state, matched) -> None:
    from engine.agents.tool_dispatcher import execute_phone_intent
    from engine.game.effects import apply_effect
    from tests.social_fixtures import _force_stage

    thread = matched("matchstick")
    pid = thread.split(":", 1)[1]
    _force_stage(receipts_state, pid, "talking")
    # A Natter thread open while still `talking` (forced): video unlocks only at `numbers`.
    assert apply_effect(receipts_state, {"type": "social_message", "op": "open", "thread_id": f"natter:{pid}"})["ok"]
    refused = execute_phone_intent({"action": "ask", "target": f"natter:{pid}", "args": {"what": "video"}},
                                   _engine(receipts_state))
    assert refused["refused"] and refused["result"]["error"].startswith("It's too soon to ask")
    assert refused["result"]["error"].endswith("for a video.")


def test_send_takes_a_camera_roll_photo_or_a_subject(receipts_state, matched) -> None:
    from engine.social import messaging
    from tests.social_fixtures import _force_stage

    pid = matched("matchstick").split(":", 1)[1]
    _force_stage(receipts_state, pid, "numbers")
    messaging.open_numbers(receipts_state, pid)
    natter = f"natter:{pid}"
    receipts_state.social["player"]["photos"] = ["hike_squint", "mirror_jacket"]   # the creation's camera roll
    verb = _verb(receipts_state, "send")
    assert verb.extra["photo_id"] == ("hike_squint", "mirror_jacket")
    assert "my_coffee" in verb.extra["subject"]
    sent = _act(receipts_state, "send", target=natter, args={"kind": "photo", "photo_id": "mirror_jacket"})
    assert sent["success"], sent
    assert _players_last(receipts_state, natter)["media_id"]
    stranger = _act(receipts_state, "send", target=natter, args={"kind": "photo", "photo_id": "dog_cuddle"})
    assert stranger["refused"] and "photo_id" in stranger["result"]["error"]
    filmed = _act(receipts_state, "send", target=natter, args={"kind": "video", "subject": "my_coffee"}, text="cosy")
    assert filmed["success"], filmed


# -- the player's voice note (T21, spec §13.7) -------------------------------------------------


def test_the_player_sends_a_voice_note_by_transcript(receipts_state, matched_numbers, tmp_path, monkeypatch) -> None:
    """`send {kind: voice, audio_transcript}`: a player message of kind voice, its transcript, no audio kept."""
    from engine.persistence import storage

    monkeypatch.setattr(storage, "media_dir", lambda: tmp_path)
    natter = matched_numbers("natter")
    before = receipts_state.world_clock_hours
    receipt = _act(receipts_state, "send", target=natter, args={"kind": "voice", "audio_transcript": "on my way"})
    assert receipt["success"], receipt
    sent = _players_last(receipts_state, natter)
    assert sent["from"] == "player" and sent["kind"] == "voice" and sent["voiced"] is True
    assert sent["transcript"] == "on my way" and sent["bubbles"] == [] and sent["media_id"] is None
    assert not any(r["kind"] == "voice" for r in (receipts_state.social.get("media") or {}).values())
    assert list(tmp_path.rglob("*")) == []                       # no audio file kept anywhere
    assert receipts_state.world_clock_hours > before              # natter's cost_minutes.voice spent


def test_a_players_voice_note_is_cut_by_length_and_needs_words(receipts_state, matched_numbers) -> None:
    from engine.social import media

    natter = matched_numbers("natter")
    empty = _act(receipts_state, "send", target=natter, args={"kind": "voice", "audio_transcript": "   "})
    assert empty["refused"] and empty["result"]["error"] == "Say something first."
    long = " ".join(f"w{i}" for i in range(100))
    assert _act(receipts_state, "send", target=natter, args={"kind": "voice", "audio_transcript": long})["success"]
    kept = _players_last(receipts_state, natter)["transcript"]
    assert kept.split() == long.split()[:media.voice_max_words()]
    over = _act(receipts_state, "send", target=natter, args={"kind": "voice", "audio_transcript": "x" * 601})
    assert over["refused"]                                          # the catalogue's own character cap
    texts = _act(receipts_state, "send", target=natter.replace("natter:", "texts:"),
                 args={"kind": "voice", "audio_transcript": "hi"})
    assert texts["refused"] and texts["result"]["error"] == "Texts can't send voice notes"


# -- rows: game_invite, game_move (T22) --------------------------------------------

def test_game_invite_is_legal_once_games_unlock_and_none_is_running(receipts_state, matched) -> None:
    from tests.social_fixtures import _force_stage

    pid = matched("matchstick").split(":", 1)[1]
    assert _verb(receipts_state, "game_invite") is None                    # matched: the games app opens at talking
    early = _act(receipts_state, "game_invite", target=pid, args={"game": "wordgame"})
    assert early["refused"] and early["result"]["error"].startswith("It's too soon to play a game with")
    _force_stage(receipts_state, pid, "talking")
    verb = _verb(receipts_state, "game_invite")
    assert verb.targets == (pid,) and tuple(verb.extra["game"]) == ("wordgame", "this_or_that")
    assert _act(receipts_state, "game_invite", target=pid, args={"game": "chess"})["refused"] is True
    assert _act(receipts_state, "game_invite", target=pid, args={"game": "wordgame"})["success"]
    assert _verb(receipts_state, "game_invite") is None                    # one running with them


def test_game_move_is_legal_only_on_the_players_turn(receipts_state, matched) -> None:
    from tests.social_fixtures import _force_stage

    pid = matched("matchstick").split(":", 1)[1]
    _force_stage(receipts_state, pid, "talking")
    assert _verb(receipts_state, "game_move") is None
    gid = _act(receipts_state, "game_invite", target=pid, args={"game": "wordgame"})["result"]["game_id"]
    assert _verb(receipts_state, "game_move").targets == (gid,)
    assert _act(receipts_state, "game_move", target=gid, args={"move": "dance"})["refused"] is True
    assert _act(receipts_state, "game_move", target="g99", args={"move": "pass"})["refused"] is True
    assert _act(receipts_state, "game_move", target=gid, args={"move": "pass"})["success"]
    assert _verb(receipts_state, "game_move").targets == (gid,)            # their turn: still offered, to resign
    late = _act(receipts_state, "game_move", target=gid, args={"move": "pass"})
    assert late["refused"] and late["result"]["error"] == "It's not your turn"
    assert _act(receipts_state, "game_move", target=gid, args={"move": "resign"})["success"]
    assert _verb(receipts_state, "game_move") is None                      # over
    over = _act(receipts_state, "game_move", target=gid, args={"move": "resign"})
    assert over["refused"] and over["result"]["error"] == "That game is over."


def test_game_move_carries_this_or_thats_five_answers(receipts_state, matched) -> None:
    """T23 (spec §7.1's row): `game_move` takes `answers: [a|b x5]`; the catalogue refuses any other
    count or value, naming `answers`, before the engine sees it."""
    from tests.social_fixtures import _force_stage

    pid = matched("matchstick").split(":", 1)[1]
    _force_stage(receipts_state, pid, "talking")
    gid = _act(receipts_state, "game_invite", target=pid, args={"game": "this_or_that"})["result"]["game_id"]
    for bad, problem in ((["a"] * 4, "answers must have exactly 5 items"),
                         (["a"] * 6, "answers must have exactly 5 items"),
                         (["a", "b", "c", "a", "b"], "answers[2] must be one of: a, b"),
                         ("aaaaa", "answers must be a list")):
        refused = _act(receipts_state, "game_move", target=gid, args={"move": "answer", "answers": bad})
        assert refused["refused"] and refused["result"]["error"] == problem, refused
    ok = _act(receipts_state, "game_move", target=gid, args={"move": "answer", "answers": ["a", "b", "a", "b", "b"]})
    assert ok["success"], ok
    assert receipts_state.social["games"][gid]["picks"]["player"] == ["a", "b", "a", "b", "b"]


# -- rows: ask {what: meet} (T24; v0.23.0 T12: a plan with no set time) -----------------------------


def test_ask_meet_is_legal_from_numbers_and_checks_its_payload(receipts_state, matched) -> None:
    from engine.social import messaging, places
    from tests.social_fixtures import _force_stage

    thread = matched("matchstick")
    pid = thread.split(":", 1)[1]
    _force_stage(receipts_state, pid, "talking")
    early = _act(receipts_state, "ask", target=thread, args={"what": "meet", "when": "soon"})
    assert early["refused"] and early["result"]["error"].startswith("It's too soon"), early      # before numbers
    _force_stage(receipts_state, pid, "numbers")
    messaging.open_numbers(receipts_state, pid)
    verb = _verb(receipts_state, "ask")
    assert "meet" in verb.extra["what"] and verb.extra["venue"] == places.venue_ids()
    for args, problem in (({"venue": "the_moon", "when": "soon"}, "venue must be one of"),
                          ({"venue": "copper_kettle", "when": "midnight"}, "when must be one of"),
                          ({"kind": "tango", "when": "soon"}, "kind must be one of")):
        refused = _act(receipts_state, "ask", target=thread, args={"what": "meet", **args})
        assert refused["refused"] and refused["result"]["error"].startswith(problem), refused
    made = _act(receipts_state, "ask", target=thread,
                args={"what": "meet", "kind": "coffee", "venue": "copper_kettle", "when": "tonight"})
    assert made["success"], made
    row = receipts_state.social["requests"][made["result"]["request_id"]]
    assert (row["what"], row["kind"], row["venue"], row["when"]) == ("meet", "coffee", "copper_kettle", "tonight")
    assert "day" not in row and "slot" not in row                          # a plan has no slot
    again = _act(receipts_state, "ask", target=thread, args={"what": "meet", "when": "soon"})
    assert again["refused"] and "already asked" in again["result"]["error"], again


def test_an_ask_with_no_words_for_a_plan_is_a_soon_plan_the_engine_fills(receipts_state, matched) -> None:
    from engine.social import messaging
    from tests.social_fixtures import _force_stage

    thread = matched("matchstick")
    pid = thread.split(":", 1)[1]
    _force_stage(receipts_state, pid, "numbers")
    messaging.open_numbers(receipts_state, pid)
    made = _act(receipts_state, "ask", target=thread, args={"what": "meet"})
    assert made["success"], made
    row = receipts_state.social["requests"][made["result"]["request_id"]]
    assert (row["kind"], row["venue"], row["when"]) == ("", "", "soon")
