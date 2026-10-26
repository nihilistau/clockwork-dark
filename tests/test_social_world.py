"""
READ RECEIPTS' world (v0.23.0 T11; spec §8.2-§8.5, §20.1's world side).

Phone up and down, the world verbs `do` and `go`, the interruptible advance, work and sleep, the
Places app, and the world turn's side of the narration turnstile. Every world turn runs the real
route or `run_guarded` with the storyteller stubbed from the session's build (`StubNarrator`, F2);
the route-level tests post an OFFERED option's `choice_id` (F3). Every draw a test depends on is forced.
"""

from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest

from tests.social_fixtures import (  # noqa: F401
    _live_session, _matched_in, _phone, _wait_until, receipts_active, there_already,
)
from tests.social_world_stub import StubNarrator


def _choose(scene, session, text: str):
    """Pick the OFFERED option whose text is `text`, by its `choice_id` (pre-flight F3): the route resolves the
    intent from the option shown (`session.last_turn`), never from the client, and typed text carries none."""
    choice = next(c for c in session.last_turn["choices"] if c.get("text") == text)
    assert choice.get("intent"), choice                    # the opening's world choice carries its intent
    return scene.app.test_client().post("/api/game/choice", json={"session_id": session.session_id,
                                                                  "choice_id": choice["id"]})


@pytest.fixture
def office(monkeypatch):
    """The player works office hours (Mon-Fri 9-17, up at 7; 9 at the weekend): a forced schedule, so no
    test depends on the job the creation form's seed drew."""
    from engine.social import windows

    real = windows.schedule_of

    def schedule_of(state, who):
        return SimpleNamespace(job_shape="office") if who == "player" else real(state, who)

    monkeypatch.setattr(windows, "schedule_of", schedule_of)


def _to(state, day: int, hour: float) -> None:
    """Advance (through `clock.advance_time`) to absolute day `day` (0-based), `hour` o'clock."""
    from engine.game import clock

    clock.advance_time(state, day * 24 + hour - state.world_clock_hours)


def _next_monday(state) -> int:
    from engine.social import behaviour

    day = int(state.world_clock_hours // 24) + 1
    while behaviour.WEEKDAYS[day % 7] != "mon":
        day += 1
    return day


# -- phone up, phone down (§8.2) -----------------------------------------------------------------------


def test_world_choices_are_refused_while_the_phone_is_up(receipts_active) -> None:
    scene, session = _live_session(llm_fn=StubNarrator())
    assert session.engine.state.social["phone_up"] is True
    resp = _choose(scene, session, "Tidy up a bit")
    assert resp.status_code == 409 and resp.get_json() == {"error": "Put the phone down first.", "phone_up": True}


def test_the_socket_choice_is_refused_while_the_phone_is_up(receipts_active) -> None:
    scene, session = _live_session(llm_fn=StubNarrator())
    choice = next(c for c in session.last_turn["choices"] if c.get("text") == "Tidy up a bit")
    sock = scene.socketio.test_client(scene.app, flask_test_client=scene.app.test_client())
    sock.emit("player_choice", {"session_id": session.session_id, "choice_id": choice["id"]})
    errors = [e["args"][0] for e in sock.get_received() if e["name"] == "turn_error"]
    assert errors == [{"message": "Put the phone down first.", "busy": False, "phone_up": True}]


def test_put_down_then_a_world_turn_runs(receipts_active) -> None:
    """Through the real route, by choice_id (F3), with the storyteller stubbed from the session's build (F2)."""
    stub = StubNarrator()
    scene, session = _live_session(llm_fn=stub)
    _phone(scene, session, "put_down")
    assert session.engine.state.social["phone_up"] is False
    before = session.engine.state.world_clock_hours
    resp = _choose(scene, session, "Tidy up a bit")
    assert resp.status_code == 200, resp.get_data(as_text=True)
    assert session.engine.state.world_clock_hours == pytest.approx(before + 0.5)   # do tidy_up ran: 30 minutes
    body = resp.get_json()
    assert stub.calls == 1 and "Tidy up" in body["narration"]
    assert any(r.get("skill") == "social_do" and not r.get("refused") for r in body["tool_receipts"])
    assert "You are in Lounge." in stub.prompts[-1]                # SocialWorld's block reached the prompt


def test_a_phone_actions_answer_carries_the_worlds_choices(receipts_active) -> None:
    """v0.23.0 T23 (found by the layout probe): the client keeps a turn's choices, so a phone action's answer
    with none left the world dead once the phone was put down. The answer carries `away.world_choices`."""
    from engine.social import away

    scene, session = _live_session(llm_fn=StubNarrator())
    body = _phone(scene, session, "put_down")
    assert body["choices"] and body["choices"] == session.last_turn["choices"]    # nothing moved: the frame's row stays
    body = _phone(scene, session, "wait", args={"until": "morning"})
    assert body["choices"] == away.world_choices(session.engine.state, prefix="world")
    assert any(c["text"] == "Look around" or c.get("intent") for c in body["choices"])


def test_any_phone_action_picks_the_phone_up(receipts_active) -> None:
    scene, session = _live_session()
    _phone(scene, session, "put_down")
    _phone(scene, session, "wait", args={"until": "1h"})
    assert session.engine.state.social["phone_up"] is True


def test_the_buzz_counts_names_never_words(receipts_active) -> None:
    """§8.2: notifications since the phone went down, as a count and names; the narrator is told no words."""
    from engine.session.store import release_turn
    from engine.social import messaging, world

    scene, session = _live_session()
    thread = _matched_in(session, "matchstick")
    state = session.engine.state
    pid = thread.split(":")[1]
    _phone(scene, session, "put_down")
    assert world.buzz(state) == {"count": 0, "who": []}
    assert session.lock.acquire(blocking=False)
    try:
        messaging.new_message(state, thread, pid, "text", bubbles=["the_secret_words_q7"])
    finally:
        release_turn(session)
    name = messaging._name(state, pid)
    assert world.buzz(state) == {"count": 1, "who": [name]}
    block = world.narration_block(state)
    assert f"Your phone has buzzed once: {name}." in block and "the_secret_words_q7" not in block


# -- activities (§8.4) ----------------------------------------------------------------------------------


def test_a_promise_into_the_work_band_interrupts_the_shift(receipts_active, office) -> None:
    """§19.2 (I11): "message me at work" lands mid-shift; the shift stops at the buzz; Carry on resumes."""
    from engine.game.intents import legal_intents
    from engine.social import promises, world

    scene, session = _live_session()
    state = session.engine.state
    pid = _matched_in(session, "matchstick").split(":")[1]
    _phone(scene, session, "put_down")
    _to(state, _next_monday(state), 8.0)
    state.location_id = "apt_hall"                       # a test placement (no mechanic reads it before the act)
    assert "go_to_work" in dict(next(v for v in legal_intents(state) if v.action == "do").options)
    state.social["queue"] = []                           # a test placement: nobody else writes first, so the draw is moot
    row = promises.make(state, pid, by="person", window="at_work")
    assert row is not None
    result = world.do(state, "go_to_work")
    for _ in range(40):                                  # the promise is the only writer: carry on until it lands
        if any(n.get("promise_id") == row["id"] for n in state.social["notifications"]):
            break
        assert result["stopped"] and state.social["at_work"] is True, result
        result = world.do(state, "carry_on_working")
    assert result["stopped"] and result["buzz"].startswith("Your phone buzzes")
    assert row["opens_at"] <= state.world_clock_hours <= row["closes_at"]
    assert state.social["at_work"] is True
    assert [v.action for v in legal_intents(state)] == ["do"]                        # m11: work verbs only
    assert dict(legal_intents(state)[0].options) == {"carry_on_working": "Carry on working",
                                                     "leave_early": "Leave early"}
    resumed = world.do(state, "carry_on_working")
    assert resumed["ok"]


def test_leave_early_goes_back_to_the_hall(receipts_active, office) -> None:
    from engine.social import world

    scene, session = _live_session()
    state = session.engine.state
    _to(state, _next_monday(state), 8.5)
    state.location_id = "apt_hall"
    state.social["queue"] = []                           # a test placement: nothing writes during the shift
    result = world.do(state, "go_to_work")
    assert not result["stopped"] and state.world_clock_hours % 24 == pytest.approx(17.0)   # the band's end
    assert state.social["at_work"] is False and "work_until" not in state.social
    assert state.location_id == "apt_hall"
    _to(state, _next_monday(state) + 1, 8.5)               # Tuesday
    state.location_id = "apt_hall"
    state.social["at_work"] = True                         # placed mid-shift
    state.social["work_until"] = state.world_clock_hours + 8.0
    before = state.world_clock_hours
    assert world.do(state, "leave_early")["ok"]
    assert state.social["at_work"] is False and "work_until" not in state.social
    assert state.location_id == "apt_hall" and state.world_clock_hours == before   # no cost beyond the time spent


def test_sleep_lands_in_the_morning_and_promises_wait(receipts_active, office) -> None:
    """(Review Focus 5, Plan decision 12) 02:00 sleeps to today's 07:00; 21:00 and 06:30 to tomorrow's; a night
    promise waits for the morning unless "wake me for messages" is on."""
    from engine.social import promises, world
    from tests.social_stub import StubVoice

    scene, session = _live_session()
    state = session.engine.state
    pid = _matched_in(session, "matchstick").split(":")[1]
    state.location_id = "apt_bedroom"
    monday = _next_monday(state)
    for day, start, lands in ((monday, 2.0, monday * 24 + 7.0), (monday + 1, 21.0, (monday + 2) * 24 + 7.0),
                              (monday + 3, 6.5, (monday + 4) * 24 + 7.0)):
        _to(state, day, start)
        result = world.do(state, "sleep")
        assert not result["stopped"]
        assert state.world_clock_hours == pytest.approx(lands, abs=1e-6), (day, start, state.world_clock_hours)
    # Asleep, wake_for_messages off: their 03:00 promise lands and the sleep runs on to the morning.
    _to(state, monday + 5, 1.0)
    row = promises.make(state, pid, by="person", window="at:3")
    assert row is not None and row["opens_at"] < state.world_clock_hours + 7
    result = world.do(state, "sleep")
    assert not result["stopped"] and state.world_clock_hours % 24 == pytest.approx(9.0)   # Saturday: up at 9
    assert any(n.get("promise_id") == row["id"] for n in state.social["notifications"])
    from engine.social import voicer

    voicer.run_until_quiet(session, StubVoice("zero"))
    assert state.social["promises"][row["id"]]["status"] == "kept"
    # On: the next night's promise wakes them.
    state.social["settings"]["wake_for_messages"] = True     # a test placement of the Settings switch
    _to(state, monday + 6, 1.0)
    again = promises.make(state, pid, by="person", window="at:3")
    result = world.do(state, "sleep")
    assert result["stopped"] and 3.0 <= state.world_clock_hours % 24 < 4.0 + 1e-6
    assert result["buzz"] == f"Your phone buzzes: {world._name(state, pid)}"
    assert again["opens_at"] <= state.world_clock_hours


@pytest.mark.parametrize("shape, weekday, start, wake_day, wake_hour", [
    ("nights", 2, 2.5, 2, 12.0),     # a bartender home from Tuesday's shift at Wed 02:30: up at Wed 12:00
    ("student", 0, 22.0, 1, 10.0),   # a student asleep at Mon 22:00: up for Tuesday's 10:00 lecture
    ("student", 0, 20.5, 1, 10.0),   # ... and at 20:30, not at Tuesday's 00:30 (the tail of Monday night)
])
def test_sleep_wakes_a_night_worker_and_a_student_in_their_morning(receipts_active, monkeypatch, shape, weekday,
                                                                   start, wake_day, wake_hour) -> None:
    """(v0.24.0 T14 a1) `waking` is the first awake band that is not the tail of the night before (a band from
    00:00 that ends by `clock.morning`), as the `morning` promise window already guards: before, a bartender
    slept through to Thursday 00:00 and a student to Wednesday 10:00."""
    from engine.social import windows, world

    real = windows.schedule_of
    monkeypatch.setattr(windows, "schedule_of",
                        lambda state, who: SimpleNamespace(job_shape=shape) if who == "player" else real(state, who))
    scene, session = _live_session()
    state = session.engine.state
    state.location_id = "apt_bedroom"
    monday = _next_monday(state)
    _to(state, monday + weekday, start)
    result = world.do(state, "sleep")
    assert not result["stopped"]
    assert state.world_clock_hours == pytest.approx((monday + wake_day) * 24 + wake_hour, abs=1e-6)
    # The initiation window itself, as a person of that shape would read it (the same line).
    span = windows.resolve(state, "player", "waking", (monday + wake_day) * 24 + 0.0)
    assert span is not None and span[0] == pytest.approx((monday + wake_day) * 24 + wake_hour)


def test_carry_on_resumes_to_the_original_end(receipts_active, office) -> None:
    """§8.4: "Carry on" after a buzz resumes the activity to the end it had, not a fresh one: woken at 06:00 on
    a weekday, sleeping on lands at 07:00 that morning (a fresh sleep from 06:00 would run to the next day's)."""
    from engine.social import promises, world

    scene, session = _live_session()
    state = session.engine.state
    pid = _matched_in(session, "matchstick").split(":")[1]
    state.location_id = "apt_bedroom"
    monday = _next_monday(state)
    _to(state, monday, 1.0)
    state.social["settings"]["wake_for_messages"] = True     # a test placement of the Settings switch
    assert promises.make(state, pid, by="person", window="at:6") is not None
    stops = []
    result = world.do(state, "sleep")
    while result["stopped"]:
        stops.append(state.world_clock_hours)
        assert result["resume_until"] == pytest.approx(monday * 24 + 7.0)
        assert state.social["resume"] == {"activity": "sleep", "until": pytest.approx(monday * 24 + 7.0)}
        assert len(stops) < 10
        result = world.do(state, "sleep")
    assert any(at >= monday * 24 + 6.0 for at in stops), stops
    assert state.world_clock_hours == pytest.approx(monday * 24 + 7.0)
    assert "resume" not in state.social
    state.location_id = "apt_lounge"
    world.do(state, "tidy_up")                                 # any other activity forgets a cut-short one
    assert "resume" not in state.social


def test_sleep_is_offered_in_the_bedroom_with_no_gate(receipts_active) -> None:
    """Rule 6: no state of the player keeps sleep off the bedroom's menu."""
    from engine.game.intents import legal_intents

    scene, session = _live_session()
    state = session.engine.state
    state.location_id = "apt_bedroom"
    for phone_up in (True, False):
        state.social["phone_up"] = phone_up
        verbs = {v.action: v for v in legal_intents(state)}
        assert "sleep" in verbs["do"].targets


def test_an_activity_is_offered_only_where_it_is_and_when_it_holds(receipts_active) -> None:
    from engine.game.intents import legal_intents

    scene, session = _live_session()
    state = session.engine.state
    state.location_id = "bldg_reception"
    do = {v.action: v for v in legal_intents(state)}.get("do")
    assert do is None or "collect_parcel" not in do.targets
    state.flags["life_parcel"] = True
    assert "collect_parcel" in {v.action: v for v in legal_intents(state)}["do"].targets
    state.location_id = "apt_kitchen"
    kitchen = {v.action: v for v in legal_intents(state)}["do"].targets
    assert "make_dinner" in kitchen and "sleep" not in kitchen and "carry_on_working" not in kitchen


@pytest.mark.parametrize("row, fault", [
    ({"id": "x", "label": "X", "at": ["apt_lounge"], "minutes": 5, "until": "morning"}, "exactly one"),
    ({"id": "x", "label": "X", "at": ["apt_lounge"]}, "exactly one"),
    ({"id": "x", "label": "X", "at": ["nowhere_q9"], "minutes": 5}, "nowhere_q9"),
    ({"id": "x", "label": "X", "at": [], "until": "noon"}, "until"),
    ({"id": "x", "label": "X", "at": [], "minutes": 5, "when": {"stage": "dating"}}, "when"),
    ({"id": "x", "label": "X", "at": [], "minutes": 5, "mood": "low"}, "mood"),
])
def test_a_malformed_activity_is_a_load_fault_naming_the_file(row, fault) -> None:
    from engine.social import world

    with pytest.raises(ValueError, match="activities.yaml") as raised:
        world.check_activities({"activities": [row]}, location_ids={"apt_lounge"})
    assert fault in str(raised.value)


def test_the_shipped_activities_load(receipts_active) -> None:
    from engine import social
    from engine.social import world

    rows = social.data("activities")["activities"]
    world.check_activities({"activities": rows})
    assert {r["id"] for r in rows} >= {"sleep", "go_to_work", "carry_on_working", "leave_early", "tidy_up"}


# -- going out (§8.5) -----------------------------------------------------------------------------------


def test_every_location_reaches_home(receipts_active) -> None:
    """§8.5 (N5): from each of the 28 locations, with no scene open, a legal sequence reaches apt_lounge."""
    from engine.agents.tool_dispatcher import execute_intent
    from engine.game.engine import GameEngine
    from engine.game.intents import legal_intents
    from engine.game.locations import LOCATIONS

    scene, session = _live_session()
    state = session.engine.state
    state.social["phone_up"] = False
    assert len(LOCATIONS) == 28
    for start in sorted(LOCATIONS):
        state.location_id = start
        state.social["at_work"] = False
        for _ in range(6):
            if state.location_id == "apt_lounge":
                break
            verbs = {v.action: v for v in legal_intents(state)}
            if "go" in verbs and "apt_lounge" in verbs["go"].targets:
                (receipt,) = execute_intent({"action": "go", "target": "apt_lounge"}, GameEngine(state))
            elif "travel" in verbs:
                target = "apt_lounge" if "apt_lounge" in verbs["travel"].targets else (
                    "apt_hall" if "apt_hall" in verbs["travel"].targets else verbs["travel"].targets[0])
                (receipt,) = execute_intent({"action": "travel", "target": target}, GameEngine(state))
            else:
                pytest.fail(f"no way on from {state.location_id}")
            assert not receipt.get("refused"), receipt
        assert state.location_id == "apt_lounge", start


def test_head_home_comes_first_from_everywhere_outside_the_flat(receipts_active) -> None:
    """Plan decision 25 (F33): "Head home" first and always, so the 8-option cap never drops it."""
    from engine.game.locations import LOCATIONS
    from engine.social import places, world

    scene, session = _live_session()
    state = session.engine.state
    for loc in sorted(LOCATIONS):
        state.location_id = loc
        targets = world.go_targets(state)
        assert len(targets) <= 8
        if places.is_outside_flat(loc):
            assert targets[0] == ("apt_lounge", "Head home"), loc
        else:
            assert "apt_lounge" not in dict(targets), loc
        assert loc not in dict(targets)


def test_every_sentinel_place_is_a_go_target(receipts_active, monkeypatch) -> None:
    """The edgeless places (venues, homes, the registry office: tagged `sentinel`) are reached only by `go`:
    each is a legal target in some state -- a venue from the Places app and, like a home or the registry, as an
    open plan's destination (spec §9.1's row: a venue's is made by `plans.make`; a home's and the registry's
    belong to T16 and T17, so their rows are placed whole by hand) -- and `go` puts the player there, charging
    its travel minutes."""
    from engine.agents.tool_dispatcher import execute_intent, execute_phone_intent
    from engine.game.engine import GameEngine
    from engine.game.locations import LOCATIONS
    from engine.social import convo, growth, plans, places, world
    from engine.social import scene as scene_
    from engine.social.convo import Availability

    scene, session = _live_session()
    state = session.engine.state
    pid = _matched_in(session, "matchstick").split(":")[1]
    real = growth.willing
    monkeypatch.setattr(growth, "willing", lambda s, p, c: (True, "") if c == "meet" else real(s, p, c))
    monkeypatch.setattr(convo, "available", lambda s, p, at: Availability(True))
    monkeypatch.setattr(convo, "boundary_minutes", lambda s, p, at: None)
    monkeypatch.setattr(plans, "_flake_drawn", lambda s, p: False)
    monkeypatch.setattr(plans, "_arrival", there_already)               # T23C: they are there when it is made
    sentinels = sorted(loc for loc, row in LOCATIONS.items() if "sentinel" in (row.get("tags") or ()))
    assert len(sentinels) == 20 and "registry_office" in sentinels
    for loc in sentinels:
        state.location_id = "apt_lounge"
        state.social["plans"] = {}
        if loc in places.venue_ids():
            assert plans.make(state, pid, kind="", when="now", venue=loc), loc
        else:
            state.social["plans"] = {"pl1": {"id": "pl1", "pid": pid, "kind": "visit", "venue": loc, "when": "now",
                                             "made_at": state.world_clock_hours, "patience_hours": 1.5,
                                             "by": "player", "status": "open", "episodes_at": 0}}
        assert loc in dict(world.go_targets(state)), loc
        before = state.world_clock_hours
        (receipt,) = execute_intent({"action": "go", "target": loc}, GameEngine(state))
        assert receipt["success"] and state.location_id == loc, receipt
        assert state.world_clock_hours == pytest.approx(before + places.travel_minutes(loc) / 60.0)
        assert receipt["result"].get("scene") == pid                     # the plan kept: its scene opens (T13)
        scene_.end_scene(state, "player", then="stay")
    state.social["plans"] = {}
    for vid in places.venue_ids():
        state.location_id = "apt_lounge"
        state.social["phone_up"] = True
        receipt = execute_phone_intent({"action": "go", "target": vid}, GameEngine(state))
        assert receipt["success"] and state.location_id == vid and state.social["phone_up"] is False, receipt


def test_the_places_section_lists_the_go_verbs_targets_with_no_numbers(receipts_active) -> None:
    """Pre-flight F18: the Places app's venue list is a payload section, `{id, label}` rows only, and every
    listed venue is one the phone verb `go` accepts."""
    import json

    from engine.social import intents as phone
    from engine.social import payload

    scene, session = _live_session(llm_fn=StubNarrator())
    state = session.engine.state
    block = payload.phone_block(state)
    venues = block["places"]["venues"]
    assert venues and all(set(v) == {"id", "label"} for v in venues)
    assert "travel_minutes" not in json.dumps(block["places"])
    verb = next(v for v in phone.legal_phone_intents(state) if v.action == "go")
    assert [v["id"] for v in venues] == list(verb.targets)


def test_the_world_section_carries_the_layers_switch_in_words_only(receipts_active) -> None:
    """v0.23.0 T21: `phone.world` is what the client's two layers read -- the phone's state, the place's name
    and the buzz as a count and names. A planted sentinel in a message's words never reaches it."""
    import json

    from engine.session.store import release_turn
    from engine.social import messaging, payload, world

    scene, session = _live_session()
    thread = _matched_in(session, "matchstick")
    state = session.engine.state
    pid = thread.split(":")[1]
    first = payload.phone_block(state)["world"]
    assert first == {"phone_up": True, "at_work": False, "location": world.places.label(state.location_id),
                     "buzz": {"count": 0, "who": []}, "household": {}, "here": []}
    _phone(scene, session, "put_down")
    assert session.lock.acquire(blocking=False)
    try:
        messaging.new_message(state, thread, pid, "text", bubbles=["MSG-7c1e55"])
    finally:
        release_turn(session)
    out = payload.phone_block(state)["world"]
    assert out["phone_up"] is False and out["buzz"] == {"count": 1, "who": [messaging._name(state, pid)]}
    assert "MSG-7c1e55" not in json.dumps(out)


def test_social_go_writes_the_place_and_nothing_else(receipts_active) -> None:
    from engine.game.effects import apply_effect

    scene, session = _live_session()
    state = session.engine.state
    before = state.world_clock_hours
    assert apply_effect(state, {"type": "social_go", "op": "place", "to": "the_anchor"})["ok"]
    assert state.location_id == "the_anchor" and state.world_clock_hours == before
    assert not apply_effect(state, {"type": "social_go", "op": "place", "to": "nowhere_q9"})["ok"]
    assert not apply_effect(state, {"type": "social_go", "op": "travel", "to": "the_anchor"})["ok"]


# -- the world turn and the turnstile (§20.1) -----------------------------------------------------------


def test_a_send_during_a_world_turn_is_busy_and_changes_nothing(receipts_active) -> None:
    """(Review Focus 2, server half) the phone answers busy; the thread is unchanged."""
    import json

    scene, session = _live_session()
    thread = _matched_in(session, "matchstick")
    assert session.lock.acquire(blocking=False)              # a world turn is running
    try:
        before = json.dumps(session.engine.state.social["threads"][thread], default=str)
        resp = scene.app.test_client().post("/api/phone/action", json={
            "session_id": session.session_id, "action": "send", "target": thread,
            "args": {"kind": "text"}, "text": "still there?"})
        assert resp.status_code == 409 and resp.get_json().get("busy") is True
        assert json.dumps(session.engine.state.social["threads"][thread], default=str) == before
    finally:
        session.lock.release()


def test_phone_send_during_world_wait_is_not_refused(receipts_active) -> None:
    """§20.1: the world turn waits on the turnstile; a send meanwhile is answered; the world turn then refuses.
    `run_guarded` is called directly with the engine-offered intent (F3's second option)."""
    from engine.scenes.default_scene import run_guarded
    from engine.social.turnstile import VOICE

    scene, session = _live_session(llm_fn=StubNarrator())
    thread = _matched_in(session, "matchstick")
    _phone(scene, session, "put_down")
    gate = session.narration_turnstile
    assert gate.try_acquire_voice()                          # a voice call in flight
    out: list = []
    t = threading.Thread(target=lambda: out.append(run_guarded(session, "Tidy up", {"action": "do",
                                                                                     "target": "tidy_up"})))
    t.start()
    try:
        _wait_until(lambda: gate.world_waiting == 1)
        sent = _phone(scene, session, "send", target=thread, args={"kind": "text"}, text="hey")   # answered
        assert not sent["receipts"][0].get("refused"), sent["receipts"]
    finally:
        gate.release(VOICE)
        t.join(5.0)
    payload, error, busy = out[0]
    assert payload is None and error == "Put the phone down first." and not busy
    assert gate.holder is None


def test_reply_parked_during_world_turn_is_delivered(receipts_active) -> None:
    """§20.1 N2: a reply a pass parked in the inbox while the turnstile was held is committed by the world turn,
    before its buzz is built, and counted in that buzz."""
    import dataclasses

    from engine.scenes.default_scene import run_guarded
    from engine.session.store import release_turn
    from engine.social import messaging, voicing, world
    from engine.social.kinds import Decision

    stub = StubNarrator()
    scene, session = _live_session(llm_fn=stub)
    thread = _matched_in(session, "matchstick")
    state = session.engine.state
    pid = thread.split(":")[1]
    _phone(scene, session, "put_down")
    assert session.lock.acquire(blocking=False)
    try:                                                     # their reply falls due while the phone is down
        due = messaging.new_message(state, thread, pid, "text", voiced=False,
                                    decision=dataclasses.asdict(Decision(situation="reply")))
        snap = voicing.snapshot_of(state, thread)
    finally:
        release_turn(session)
    session.voicing[due["id"]] = "vT11"                      # marked by the pass that parked it
    session.inbox.put({"kind": "voiced", "payload": voicing.fallback_reply(snap, "test"), "epoch": session.epoch,
                       "account": "", "pass": "vT11"})
    payload, error, busy = run_guarded(session, "Tidy up", {"action": "do", "target": "tidy_up"})
    assert payload is not None, error
    assert not len(session.inbox)
    landed = next(m for m in state.social["threads"][thread]["messages"] if m["id"] == due["id"])
    assert landed["voiced"] is not False and landed["bubbles"]
    name = messaging._name(state, pid)
    assert name in world.buzz(state)["who"]
    assert f"buzzed once: {name}" in stub.prompts[-1] or f": {name}" in stub.prompts[-1]


def test_a_world_turn_brings_a_deferred_pass_forward(receipts_active, monkeypatch) -> None:
    """§20.1 step 6: a voice pass deferred by the world turn waits out a backoff (up to 800 ms) unless the turn,
    releasing the turnstile, requests it at once -- it is moved to the ready queue."""
    from engine.scenes.default_scene import run_guarded
    from engine.social import voicer

    scene, session = _live_session(llm_fn=StubNarrator())
    _phone(scene, session, "put_down")
    monkeypatch.setattr(voicer.VoicingScheduler, "_start_workers", lambda self: None)   # driven by hand
    sched = voicer.VoicingScheduler(workers=0, time_fn=lambda: 0.0)
    monkeypatch.setattr(voicer, "get_scheduler", lambda: sched)
    p = voicer.VoicePass(session, session.epoch)
    sched._in_flight[p.key] = p
    sched._after(p, "deferred")                                # the pass met the world turn: timed
    assert p.deferred_wait and sched._timed and not sched._ready
    assert sched._next() == (None, pytest.approx(0.05))       # it would wait its backoff
    payload, error, busy = run_guarded(session, "Tidy up", {"action": "do", "target": "tidy_up"})
    assert payload is not None, error
    assert list(sched._ready) == [p] and not sched._timed and not p.deferred_wait
    assert sched._next()[0] is p                               # run at once


def test_a_phone_action_does_not_bring_a_deferred_pass_forward(receipts_active, monkeypatch) -> None:
    """Only the world turn's request is `now`: any other request leaves a deferral's backoff alone."""
    from engine.social import voicer

    scene, session = _live_session()
    monkeypatch.setattr(voicer.VoicingScheduler, "_start_workers", lambda self: None)
    sched = voicer.VoicingScheduler(workers=0, time_fn=lambda: 0.0)
    p = voicer.VoicePass(session, session.epoch)
    sched._in_flight[p.key] = p
    sched._after(p, "deferred")
    sched.request(session)
    assert not sched._ready and sched._timed and p.deferred_wait


def test_a_promised_message_notification_carries_its_promise_id(receipts_active) -> None:
    """Pre-flight F35: the notification row of a person's promised message names the promise, so a sleeper
    with "wake me for messages" on is woken by it (`world._wakes`); the client's rows keep their shape."""
    from engine.game import clock
    from engine.social import messaging, promises, world

    scene, session = _live_session(llm_fn=StubNarrator())
    state = session.engine.state
    pid = _matched_in(session, "matchstick").split(":")[1]
    row = promises.make(state, pid, by="person", window="later")
    clock.advance_time(state, row["closes_at"] - state.world_clock_hours + 0.05)
    notes = [n for n in state.social["notifications"] if n.get("promise_id") == row["id"]]
    assert notes and world._wakes(state, {**notes[-1]}, sleeping=False)
    assert not world._wakes(state, notes[-1], sleeping=True)        # wake_for_messages is off by default
    state.social["settings"]["wake_for_messages"] = True     # a read-only probe of `_wakes`' asleep branch
    assert world._wakes(state, notes[-1], sleeping=True)
    assert all("promise_id" not in n for n in messaging.notification_rows(state))
    assert sum("promise_id" in n for n in state.social["notifications"]) == len(notes)   # no other row moves


def test_a_go_after_an_interrupted_sleep_does_not_resume_the_sleep(receipts_active, office) -> None:
    """Fix round 1 (review minor 1): walking out ends a cut-short activity; sleeping again later starts fresh."""
    from engine.social import promises, world

    scene, session = _live_session()
    state = session.engine.state
    pid = _matched_in(session, "matchstick").split(":")[1]
    state.location_id = "apt_bedroom"
    monday = _next_monday(state)
    _to(state, monday, 1.0)
    state.social["settings"]["wake_for_messages"] = True
    state.social["queue"] = []
    assert promises.make(state, pid, by="person", window="at:3") is not None
    result = world.do(state, "sleep")
    assert result["stopped"] and state.social["resume"]["activity"] == "sleep"
    went = world.go(state, "apt_lounge", targets=[("apt_lounge", "Lounge")])
    assert went["ok"] and "resume" not in state.social
    state.location_id = "apt_bedroom"
    state.social["settings"]["wake_for_messages"] = False
    _to(state, monday, 4.5)
    again = world.do(state, "sleep")
    assert not again["stopped"] and "resume_until" not in again
    assert state.world_clock_hours > monday * 24 + 7.0 - 1e-9          # a fresh end, not the old 07:00 resume


def test_the_narrator_is_told_the_player_is_at_work(receipts_active, office) -> None:
    """Fix round 1 (review minor 2): during a shift the block says work, not the hall the player left from."""
    from engine.social import world

    scene, session = _live_session()
    state = session.engine.state
    state.location_id = "apt_hall"
    assert world.narration_block(state).startswith("You are in Hall.")
    state.social["at_work"] = True
    block = world.narration_block(state)
    assert block.startswith("You are at work") and "Hall" not in block
    assert state.location_id == "apt_hall"                  # the place itself does not move


def test_the_work_lead_is_data(receipts_active, office, monkeypatch) -> None:
    """Fix round 1 (review minor 3): `clock.work_lead_hours` in conversation.yaml sets how early work is offered."""
    from engine.social import world
    import engine.social as social

    scene, session = _live_session()
    state = session.engine.state
    _to(state, _next_monday(state), 6.5)                    # 2.5 h before the 9:00 band
    assert world._work_offered(state) is False
    real = social.data

    def patched(name):
        data = real(name)
        if name == "conversation":
            data = {**data, "clock": {**data["clock"], "work_lead_hours": 3}}
        return data

    monkeypatch.setattr(social, "data", patched)
    assert world._work_offered(state) is True


def test_a_raise_before_the_world_turn_is_a_generic_error_not_a_500(receipts_active, monkeypatch) -> None:
    """Fix round 1 (review minor 4): the inbox drain is inside the turn's error handler, so a raise there
    comes back as the turn's error (text, not busy) and the turn lock and turnstile are released."""
    from engine.scenes.default_scene import run_guarded
    from engine.social import voicer

    scene, session = _live_session(llm_fn=StubNarrator())
    _phone(scene, session, "put_down")

    def boom(_session):
        raise RuntimeError("drain failed")

    monkeypatch.setattr(voicer, "drain_inbox", boom)
    payload, error, busy = run_guarded(session, "Look around", None)
    assert payload is None and not busy and error
    monkeypatch.undo()
    assert session.lock.acquire(blocking=False)             # released
    session.lock.release()
    payload, error, busy = run_guarded(session, "Look around", None)
    assert payload is not None and not error


def test_a_raise_in_the_post_turn_drain_keeps_the_turns_payload(receipts_active, monkeypatch) -> None:
    """The turn is committed by then: the second drain's failure is logged, never the player's error."""
    from engine.scenes.default_scene import run_guarded
    from engine.social import voicer

    scene, session = _live_session(llm_fn=StubNarrator())
    _phone(scene, session, "put_down")
    real = voicer.drain_inbox
    calls = []

    def second_boom(sess):
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError("post drain failed")
        return real(sess)

    monkeypatch.setattr(voicer, "drain_inbox", second_boom)
    payload, error, busy = run_guarded(session, "Look around", None)
    assert len(calls) == 2 and payload is not None and not error and not busy
    assert session.lock.acquire(blocking=False)
    session.lock.release()


# -- the world's row survives phone actions (v0.23.0 T23A; addendum 4 W1) ------------------------------


def test_a_phone_rows_choice_is_not_stale(receipts_active) -> None:
    """A4 W1 gap 1: after a narrated turn, a phone action's row is the frame; picking from it runs, never 409."""
    scene, session = _live_session(llm_fn=StubNarrator())
    _phone(scene, session, "put_down")
    assert _choose(scene, session, "Tidy up a bit").status_code == 200          # a narrated turn: last_turn is the narrator's
    body = _phone(scene, session, "wait", args={"until": "1h"})                                 # the clock moves: the row is rebuilt
    pick = next(c for c in body["choices"] if c.get("intent"))
    assert pick["id"].startswith("world_")
    _phone(scene, session, "put_down")
    resp = scene.app.test_client().post("/api/game/choice", json={"session_id": session.session_id,
                                                                  "choice_id": pick["id"]})
    assert resp.status_code == 200, resp.get_data(as_text=True)


def test_refresh_after_phone_action_matches_the_row(receipts_active) -> None:
    scene, session = _live_session(llm_fn=StubNarrator())
    body = _phone(scene, session, "wait", args={"until": "1h"})
    assert session.last_turn["choices"] == body["choices"]


def test_phone_glance_keeps_the_narrators_choices(receipts_active) -> None:
    """Nothing in the world changed (a settings toggle costs no time): the narrator's row stays."""
    scene, session = _live_session(llm_fn=StubNarrator())
    _phone(scene, session, "put_down")
    _choose(scene, session, "Tidy up a bit")
    narrated = list(session.last_turn["choices"])
    body = _phone(scene, session, "set_receipts", "natter", args={"to": "off"})
    assert body["choices"] == narrated


def test_put_down_across_a_jump_gives_the_new_row(receipts_active) -> None:
    """I1: a clock advance changes the fingerprint, so the row is rebuilt from what is legal now."""
    from engine.social import away, turn

    scene, session = _live_session(llm_fn=StubNarrator())
    before = turn.world_fingerprint(session.engine.state)
    body = _phone(scene, session, "wait", args={"until": "morning"})
    assert turn.world_fingerprint(session.engine.state) != before
    assert body["choices"] == away.world_choices(session.engine.state, prefix="world")


def test_head_home_row_reaches_the_rooms(receipts_active) -> None:
    """I2: the rebuilt row carries the flat's room moves (core `travel`)."""
    from engine.social import away

    scene, session = _live_session(llm_fn=StubNarrator())
    state = session.engine.state
    rooms = {c["intent"]["target"] for c in away.world_choices(state, prefix="world")
             if (c.get("intent") or {}).get("action") == "travel"}
    assert {"apt_hall", "apt_dining"} <= rooms                                  # the lounge's two doors


@pytest.mark.parametrize("loc", sorted(__import__("engine.social.places", fromlist=["LOCATIONS"]).LOCATIONS))
def test_no_go_target_is_here(receipts_active, loc) -> None:
    from engine.game import procgen
    from engine.social import away

    state = procgen.new_game_state(player_name="Sam", seed=4242)
    state.location_id = loc
    assert all((c.get("intent") or {}).get("target") != loc for c in away.world_choices(state)
               if (c.get("intent") or {}).get("action") in ("go", "travel"))


def test_scene_opened_by_phone_is_said(receipts_active, monkeypatch) -> None:
    """A Places-app arrival that keeps a plan opens the scene; the answer says so in the engine's words."""
    from engine.social import plans

    scene, session = _live_session(llm_fn=StubNarrator())
    state = session.engine.state
    pid = _matched_in(session, "matchstick").split(":")[1]
    monkeypatch.setattr(plans, "_flake_drawn", lambda s, p: False)
    with session.lock:
        row = plans.make(state, pid, kind="drinks", when="now", venue="the_anchor", in_person=True)
    body = _phone(scene, session, "go", "the_anchor")
    assert row and body["narration"] and "the_anchor" not in body["narration"]


def test_a_fingerprint_fault_never_fails_the_phone_action(receipts_active, monkeypatch) -> None:
    from engine.social import away, turn

    scene, session = _live_session(llm_fn=StubNarrator())

    def boom(state, legal=None):
        raise RuntimeError("forced")

    monkeypatch.setattr(turn, "world_fingerprint", boom)
    body = _phone(scene, session, "put_down")
    assert body["choices"] == away.world_choices(session.engine.state, prefix="world")


def test_a_narrators_choice_runs_after_put_down(receipts_active) -> None:
    scene, session = _live_session(llm_fn=StubNarrator())
    _phone(scene, session, "put_down")
    assert _choose(scene, session, "Tidy up a bit").status_code == 200
    _phone(scene, session, "put_down")
    narrated = next(c for c in session.last_turn["choices"] if c.get("intent"))
    resp = scene.app.test_client().post("/api/game/choice", json={"session_id": session.session_id,
                                                                  "choice_id": narrated["id"]})
    assert resp.status_code == 200, resp.get_data(as_text=True)
