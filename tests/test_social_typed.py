"""Typed world lines (v0.23.0 addendum 4 §3, §3.1, W7; C2, R1): `engine/social/typed.py`."""

from __future__ import annotations

import logging

import pytest

from tests.social_fixtures import (  # noqa: F401
    _force_stage, _live_session, _matched_in, _phone, matched, receipts_active, receipts_state,
)
from tests.social_world_stub import StubNarrator


@pytest.fixture
def kitchen(receipts_state):
    receipts_state.location_id = "apt_kitchen"
    receipts_state.social["phone_up"] = False
    return receipts_state


@pytest.fixture
def lounge(receipts_state):
    receipts_state.location_id = "apt_lounge"
    receipts_state.social["phone_up"] = False
    return receipts_state


# -- the matcher's table (A4 §3.1, R1) ----------------------------------------------------------------------

MATCH_BREAKFAST = ["make breakfast", "Make breakfast.", "*makes breakfast*", "*making breakfast*",
                   "I make breakfast", "I'll make breakfast", "ok, make breakfast", "I'm making breakfast",
                   "I am making breakfast", "now I'm making breakfast", "I’ll make breakfast",
                   "cook breakfast", "  MAKE   breakfast  "]
NONE_IN_KITCHEN = [
    "I'd love to make breakfast for you sometime", "I could make breakfast", "maybe make breakfast",
    "let's make breakfast", "I want to make breakfast", "if I make breakfast", "we should make breakfast",
    "make breakfast for us", "I don't feel like making breakfast", "I'll make breakfast later",
    "made breakfast earlier", "making breakfast is a chore", "she makes breakfast", "makes breakfast",
    "should I make breakfast?", "make breakfast?", "breakfast", "go to work",
    # near-misses beyond the table
    "I'd make breakfast", "I wanna make breakfast", "I wish I could make breakfast", "never make breakfast",
    "I won't make breakfast", "I can't make breakfast", "no, make breakfast", "make breakfast tomorrow",
    "make breakfast tonight", "I'll make breakfast soon", "make breakfast instead of lunch",
    "make breakfast after this", "I'd like to make breakfast", "I'm going to make breakfast",
    "you make breakfast", "we make breakfast", "*breakfast*", "**", "", "   ", "make dinner and make breakfast",
    "I make breakfast and tidy up", "breakfast making", "remake breakfast",
    # habits (review): a habit is talk, not a move
    "i make breakfast every day", "i usually make breakfast", "I always make breakfast", "I often make breakfast",
    "sometimes I make breakfast", "I normally make breakfast", "I generally make breakfast",
    "I regularly make breakfast", "I make breakfast most days", "I make breakfast each day",
]


@pytest.mark.parametrize("line", MATCH_BREAKFAST)
def test_breakfast_matches(kitchen, line) -> None:
    from engine.social import typed

    assert typed.match_offered(kitchen, line) == {"action": "do", "target": "make_breakfast", "typed": True}


@pytest.mark.parametrize("line", NONE_IN_KITCHEN)
def test_near_misses_do_not_match(kitchen, line) -> None:
    from engine.social import typed

    assert typed.match_offered(kitchen, line) == {}


@pytest.mark.parametrize("line", ["do the dishes", "tidy up", "I'll just tidy up", "*does the dishes*",
                                  "let me tidy up"])
def test_tidy_up_matches(kitchen, line) -> None:
    from engine.social import typed

    assert typed.match_offered(kitchen, line) == {"action": "do", "target": "tidy_up", "typed": True}


@pytest.mark.parametrize("line,room", [("go to the hall", "apt_hall"), ("I head into the dining room", "apt_dining"),
                                       ("then pop through to the hall", "apt_hall"),
                                       ("*wanders into the hallway*", "apt_hall"),
                                       ("I'm heading to the hall", "apt_hall"), ("go to the Dining room", "apt_dining")])
def test_room_moves_match(lounge, line, room) -> None:
    from engine.social import typed

    assert typed.match_offered(lounge, line) == {"action": "travel", "target": room, "typed": True}


@pytest.mark.parametrize("line", ["should we go to the hall", "should we go to the hall?", "the hall is a mess",
                                  "go to the hall and tidy up", "I'm off to The Anchor", "go back to mine",
                                  "go to the kitchen",                     # the kitchen is not a door from the lounge
                                  "go all the way over there to the hall", "going to the hall",
                                  "heads to the hall", "go to the hall later", "don't go to the hall",
                                  "go to the hall or the dining room", "hall", "go home"])
def test_room_near_misses(lounge, line) -> None:
    from engine.social import typed

    assert typed.match_offered(lounge, line) == {}


def test_the_kitchen_from_the_hall(receipts_state) -> None:
    """The R1 table's room rows as written: "go to the kitchen" where the kitchen is a door, and its near-misses."""
    from engine.social import typed

    receipts_state.location_id = "apt_hall"
    receipts_state.social["phone_up"] = False
    assert typed.match_offered(receipts_state, "go to the kitchen") == {"action": "travel", "target": "apt_kitchen",
                                                                        "typed": True}
    assert typed.match_offered(receipts_state, "I head into the bedroom")["target"] == "apt_bedroom"
    for line in ("should we go to the kitchen", "should we go to the kitchen?", "the kitchen is a mess",
                 "go to the kitchen and make breakfast", "go to work"):
        assert typed.match_offered(receipts_state, line) == {}, line


def test_not_legal_here_does_not_match(receipts_state) -> None:
    from engine.social import typed

    receipts_state.location_id = "apt_bedroom"
    receipts_state.social["phone_up"] = False
    assert typed.match_offered(receipts_state, "make breakfast") == {}


def test_work_is_never_inferred(receipts_state, monkeypatch) -> None:
    """`go_to_work` legal in the hall: its label and the bare words still never run it (A4 §3)."""
    from engine.game import intents
    from engine.social import typed, world

    receipts_state.location_id = "apt_hall"
    receipts_state.social["phone_up"] = False
    monkeypatch.setattr(world, "_work_offered", lambda s: True)
    assert "go_to_work" in intents.find_verb(intents.legal_intents(receipts_state), "do").targets
    for line in ("go to work", "Go to work.", "*goes to work*", "I'll go to work"):
        assert typed.match_offered(receipts_state, line) == {}, line


def test_a_line_never_names_a_venue_or_a_home(receipts_state) -> None:
    """`go` (venues, homes, home) is never a matcher target: on Merrow Street only the lobby is a room move."""
    from engine.game import intents
    from engine.social import typed

    receipts_state.location_id = "merrow_street"
    receipts_state.social["phone_up"] = False
    assert intents.find_verb(intents.legal_intents(receipts_state), "go") is not None
    for line in ("go to The Anchor", "head to the anchor", "go home", "walk to the copper kettle"):
        assert typed.match_offered(receipts_state, line) == {}, line
    assert typed.match_offered(receipts_state, "go to the lobby")["target"] == "bldg_reception"
    assert typed.match_offered(receipts_state, "get some air")["target"] == "step_outside"


# -- in a scene (W7) ----------------------------------------------------------------------------------------


def _scene(state, matched):
    from engine.social import scene

    pid = matched("matchstick").split(":")[1]
    _force_stage(state, pid, "dating")
    state.location_id = "the_anchor"
    state.social["phone_up"] = False
    assert scene.open_scene(state, pid, "the_anchor", kind="drinks")["ok"]
    return pid


def test_unread_line_is_talk(receipts_state, matched) -> None:
    from engine.social import typed

    _scene(receipts_state, matched)
    assert typed.intent_for(receipts_state, "you have a nice laugh") == {"action": "scene", "target": "talk",
                                                                         "typed": True}


def test_typed_question_asks_about_their_topic(receipts_state, matched) -> None:
    from engine.game import intents
    from engine.social import typed

    _scene(receipts_state, matched)
    ask = next(t for t in intents.find_verb(intents.legal_intents(receipts_state), "scene").options
               if t[0].startswith("ask_about:"))
    label = ask[1].split("Ask about ", 1)[-1]
    assert typed.intent_for(receipts_state, f"so, {label}?") == {"action": "scene", "target": ask[0],
                                                                 "typed": True}


def test_typed_line_names_your_hobby(receipts_state, matched) -> None:
    from engine.game import intents
    from engine.social import population, typed

    _scene(receipts_state, matched)
    targets = intents.find_verb(intents.legal_intents(receipts_state), "scene").targets
    hobby = next(t.split(":", 1)[1] for t in targets if t.startswith("tell_about:") and t != "tell_about:work")
    label = next(str(r.get("label")) for r in population.table("hobbies") if r.get("id") == hobby)
    assert typed.intent_for(receipts_state, f"honestly {label} is my whole weekend") == {
        "action": "scene", "target": f"tell_about:{hobby}", "typed": True}


@pytest.mark.parametrize("line", ["my job is a lot right now", "my work never stops"])
def test_my_job_tells_them_about_work(receipts_state, matched, line) -> None:
    from engine.social import typed

    _scene(receipts_state, matched)
    assert typed.intent_for(receipts_state, line)["target"] == "tell_about:work"


def test_does_that_work_is_not_work(receipts_state, matched) -> None:
    from engine.social import typed

    _scene(receipts_state, matched)
    assert typed.intent_for(receipts_state, "does that work for you")["target"] == "talk"


def test_typed_line_outside_a_scene_without_a_match_is_narrated_only(lounge) -> None:
    from engine.social import typed

    assert typed.intent_for(lounge, "the light is nice today") == {}


@pytest.mark.parametrize("line", ["let's go back to mine", "I'll go to The Anchor", "call it a night",
                                  "same time next week?", "go over to Sam", "I'll text you in the morning",
                                  "marry me", "walk you home", "another round?", "stay the night"])
def test_typed_line_never_leaves_or_commits(receipts_state, matched, line) -> None:
    from engine.social import typed

    _scene(receipts_state, matched)
    got = typed.intent_for(receipts_state, line)
    assert got.get("action") == "scene", got
    assert got["target"].split(":")[0] in ("talk", "ask_about", "tell_about"), got


def test_a_shared_activity_in_a_scene(receipts_state, matched) -> None:
    """In a scene at the flat, a typed shared activity runs it together (`do`, step 1 of the order)."""
    from engine.social import scene, typed

    pid = matched("matchstick").split(":")[1]
    _force_stage(receipts_state, pid, "dating")
    receipts_state.location_id = "apt_kitchen"
    receipts_state.social["phone_up"] = False
    assert scene.open_scene(receipts_state, pid, "apt_kitchen", kind="drinks")["ok"]
    assert typed.intent_for(receipts_state, "make dinner") == {"action": "do", "target": "make_dinner", "typed": True}
    assert typed.intent_for(receipts_state, "make breakfast") == {"action": "scene", "target": "talk", "typed": True}


def test_talk_replaces_phone_in_the_eight(receipts_state, matched) -> None:
    from engine.social import scene

    pid = _scene(receipts_state, matched)
    names = [t.split(":")[0] for t, _ in scene._move_options(receipts_state, pid)]
    assert "talk" in names and "phone" not in names and len(names) <= 8
    assert names[-3:] == ["playful", "quiet", "talk"]
    assert "talk" in scene.MOVES and "talk" in scene.MOVE_WORDS


def test_talk_is_a_wedding_move(receipts_active) -> None:
    from engine import social

    assert "talk" in social.data("scenes")["wedding"]["moves"]


def test_typed_turn_moves_warmth(receipts_state, matched, monkeypatch) -> None:
    """`talk` is scored and spent like any move: a forced landing moves warmth and trust by its row exactly."""
    from engine.agents.tool_dispatcher import execute_intent
    from engine.game.engine import GameEngine
    from engine.social import scene, typed

    pid = _scene(receipts_state, matched)
    monkeypatch.setattr(scene, "_moment_draw", lambda s, p: 0.9)
    person = receipts_state.social["people"][pid]
    warmth, trust = person.get("warmth", 0), person.get("trust", 0)
    intent = typed.intent_for(receipts_state, "you have a nice laugh")
    before = receipts_state.world_clock_hours
    [receipt] = execute_intent(intent, GameEngine(receipts_state))
    assert receipt["success"] and not receipt.get("refused")
    assert receipt["result"]["band"] == "lands"
    assert person["warmth"] == warmth + 2 and person["trust"] == trust + 1
    assert receipts_state.world_clock_hours == pytest.approx(before + 0.25)


def test_the_receipt_says_it_was_typed(receipts_state, matched, monkeypatch) -> None:
    """A4 §3: the receipt carries `typed: true`, and the narrator's line is the engine's reading, never the line."""
    from engine.agents.prompts import receipts_block
    from engine.agents.tool_dispatcher import execute_intent
    from engine.game.engine import GameEngine
    from engine.social import scene, typed

    _scene(receipts_state, matched)
    monkeypatch.setattr(scene, "_moment_draw", lambda s, p: 0.9)
    intent = typed.intent_for(receipts_state, "Qx7typed you have a nice laugh")
    receipts = execute_intent(intent, GameEngine(receipts_state))
    typed.mark(intent, receipts)
    assert receipts[0]["typed"] is True and receipts[0]["intent"]["typed"] is True
    block = receipts_block(receipts)
    assert "The player said this; the engine read it as: You talk (lands)." in block
    assert "qx7typed" not in block.casefold()


# -- through the route (C2) ---------------------------------------------------------------------------------


def _turn(scene, session, text: str):
    return scene.app.test_client().post("/api/game/choice", json={
        "session_id": session.session_id, "choice_id": "custom", "custom_text": text})


def test_typed_turn_runs_the_offered_choice(receipts_active, caplog) -> None:
    """Through the route: a typed "tidy up" in the lounge runs `do tidy_up` (30 minutes), with no refusal, and
    only the action and target are logged."""
    scene, session = _live_session(llm_fn=StubNarrator())
    _phone(scene, session, "put_down")
    session.engine.state.location_id = "apt_lounge"
    before = session.engine.state.world_clock_hours
    with caplog.at_level(logging.INFO):
        resp = _turn(scene, session, "tidy up, Qx7typed")
    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_json()
    assert session.engine.state.world_clock_hours == pytest.approx(before + 0.5)
    receipts = body["tool_receipts"]
    assert any(r.get("typed") and (r.get("intent") or {}).get("target") == "tidy_up" for r in receipts), receipts
    assert not any(r.get("refused") for r in receipts)
    assert "operation=typed_reading, action=do, target=tidy_up" in caplog.text
    assert "qx7typed" not in caplog.text.casefold()


def test_an_unmatched_typed_line_moves_no_time(receipts_active) -> None:
    """Outside a scene, a line that names nothing on offer is narrated only: no mechanic and no time (A8)."""
    scene, session = _live_session(llm_fn=StubNarrator())
    _phone(scene, session, "put_down")
    session.engine.state.location_id = "apt_lounge"
    before = session.engine.state.world_clock_hours
    resp = _turn(scene, session, "the light is nice today")
    assert resp.status_code == 200, resp.get_data(as_text=True)
    assert session.engine.state.world_clock_hours == pytest.approx(before)
    assert not any(r.get("refused") or r.get("typed") for r in resp.get_json()["tool_receipts"])


def test_a_client_intent_is_ignored(receipts_active) -> None:
    """Rule 1: the route is not widened. An `intent` the client adds beside typed text is never run."""
    scene, session = _live_session(llm_fn=StubNarrator())
    _phone(scene, session, "put_down")
    session.engine.state.location_id = "apt_lounge"
    before = session.engine.state.world_clock_hours
    resp = scene.app.test_client().post("/api/game/choice", json={
        "session_id": session.session_id, "choice_id": "custom", "custom_text": "the light is nice",
        "intent": {"action": "do", "target": "watch_something"}})
    assert resp.status_code == 200, resp.get_data(as_text=True)
    assert session.engine.state.world_clock_hours == pytest.approx(before)


def test_typed_reading_is_under_the_lock(receipts_active, monkeypatch) -> None:
    """C2: a voicing commit closes the scene between the route and the lock; the typed turn reads the closed
    state after the drain and is never refused."""
    from engine.social import scene as social_scene, typed, voicer

    scene, session = _live_session(llm_fn=StubNarrator())
    state = session.engine.state
    pid = _matched_in(session, "matchstick").split(":")[1]
    with session.lock:
        _force_stage(state, pid, "dating")
        state.location_id = "the_anchor"
        assert social_scene.open_scene(state, pid, "the_anchor", kind="drinks")["ok"]
    _phone(scene, session, "put_down")
    assert typed.intent_for(state, "you have a nice laugh")["target"] == "talk"     # what the route would see
    real = voicer.drain_inbox
    read: list[dict] = []
    real_intent_for = typed.intent_for

    def drain_and_close(sess):
        real(sess)
        if social_scene.current(sess.engine.state).get("pid"):
            social_scene.end_scene(sess.engine.state, "theirs", then="stay")

    def spy(st, text):
        read.append({"scene": bool(social_scene.current(st).get("pid")), "got": real_intent_for(st, text)})
        return read[-1]["got"]

    monkeypatch.setattr(voicer, "drain_inbox", drain_and_close)
    monkeypatch.setattr(typed, "intent_for", spy)
    resp = _turn(scene, session, "you have a nice laugh")
    assert resp.status_code == 200, resp.get_data(as_text=True)
    assert read == [{"scene": False, "got": {}}]
    assert not any(r.get("refused") for r in resp.get_json()["tool_receipts"])


@pytest.mark.parametrize("where,line,want", [
    ("bldg_reception", "step outside", ("travel", "merrow_street")),     # the activity is the street's, not here
    ("merrow_street", "step outside", ("do", "step_outside")),           # the street is where you are
    ("apt_hall", "go to bed", ("travel", "apt_bedroom")),
    ("apt_bedroom", "go to bed", ("do", "sleep")),
    ("apt_hall", "go to the lounge and go to work", None),
    ("apt_hall", "*goes to the bedroom*", ("travel", "apt_bedroom")),
])
def test_rooms_and_activities_together(receipts_state, where, line, want) -> None:
    from engine.social import typed

    receipts_state.location_id = where
    receipts_state.social["phone_up"] = False
    got = typed.match_offered(receipts_state, line)
    assert got == ({} if want is None else {"action": want[0], "target": want[1], "typed": True})


# -- the data, checked at load ------------------------------------------------------------------------------


def _activities_data():
    import copy

    from engine import social

    return copy.deepcopy(social.data("activities"))


@pytest.mark.parametrize("mutate,fault", [
    (lambda d: d["activities"][0].__setitem__("say", ["breakfast"]), "two words or more"),
    (lambda d: d["activities"][0].__setitem__("say", "make breakfast"), "two words or more"),
    (lambda d: d["typed"]["rooms"].__setitem__("apt_attic", ["attic"]), "names no location: apt_attic"),
    (lambda d: d["typed"]["rooms"].__setitem__("apt_hall", []), "typed.rooms.apt_hall"),
    (lambda d: d["typed"].__setitem__("synonyms", ["x"]), "unknown key(s) synonyms"),
    (lambda d: d["typed"].__setitem__("modals", "would"), "typed.modals"),
    (lambda d: d.__setitem__("phrasebook", {}), "unknown top-level key(s) phrasebook"),
])
def test_the_activities_loader_refuses_bad_typed_data(receipts_active, mutate, fault) -> None:
    from engine.social import world

    data = _activities_data()
    world.check_activities(data)                                   # the shipped file passes
    mutate(data)
    with pytest.raises(ValueError, match="activities.yaml") as raised:
        world.check_activities(data)
    assert fault in str(raised.value)


def test_every_offerable_activity_has_say_phrases(receipts_active) -> None:
    """Each activity a player can be offered by place carries `say:` (A4 §3.1); the work rows carry none."""
    from engine.social import typed, world

    for row in world.activities():
        if row["id"] in typed.NEVER:
            assert not row.get("say"), row["id"]
        elif row.get("at"):
            assert row.get("say"), row["id"]


def test_put_something_on_is_not_a_film(lounge) -> None:
    """Review: "put something on" alone was too broad; only a phrase that says watching is read as watching."""
    from engine.social import typed

    assert typed.match_offered(lounge, "put something on the table") == {}
    assert typed.match_offered(lounge, "put something on") == {}
    for line in ("put something on to watch", "put a film on"):
        assert typed.match_offered(lounge, line) == {"action": "do", "target": "watch_something", "typed": True}


def test_mark_says_the_reading_once() -> None:
    """Review: an intent that ever returned two receipts carries the reading once, on the first that ran."""
    from engine.social import typed

    receipts = [{"skill": "social_do", "success": True, "result": {"ok": True}, "intent": {"action": "do"}},
                {"skill": "social_do", "success": True, "result": {"ok": True}, "intent": {"action": "do"}}]
    typed.mark({"action": "do", "target": "tidy_up", "typed": True}, receipts)
    assert [bool(r.get("typed_line")) for r in receipts] == [True, False]
    assert all(r["typed"] for r in receipts)


def test_a_reading_that_raises_is_narrated_only(receipts_active, monkeypatch, caplog) -> None:
    """Review: if `intent_for` raises, the error is logged (never the line) and the turn is narrated only."""
    from engine.social import typed

    def boom(_state, _text):
        raise RuntimeError("forced")

    scene, session = _live_session(llm_fn=StubNarrator())
    _phone(scene, session, "put_down")
    session.engine.state.location_id = "apt_lounge"
    before = session.engine.state.world_clock_hours
    monkeypatch.setattr(typed, "intent_for", boom)
    with caplog.at_level(logging.INFO):
        resp = _turn(scene, session, "tidy up, Qx7typed")
    assert resp.status_code == 200, resp.get_data(as_text=True)
    assert session.engine.state.world_clock_hours == pytest.approx(before)
    assert not any(r.get("refused") or r.get("typed") for r in resp.get_json()["tool_receipts"])
    assert "Reading a typed line failed" in caplog.text
    assert "qx7typed" not in caplog.text.casefold()
