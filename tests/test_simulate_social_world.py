"""READ RECEIPTS' balance harness, its world (v0.23.0 T29 Step 2; v0.24.0 §13, T11).

`scripts/simulate_social.py`'s full sessions put the phone down and play the world through the engine's own
narrated turn (`World.turn`, `default_scene.run_guarded`, narrated by the harness's `StubNarration`): dinner,
bed, work, the plans and their scenes, the morning after a stay-over (one `quiet`, then see them out), and the
four life decks of v0.24.0 §12.2, walked to on a day they run. These are the fast unit tests of those pieces
(every draw a test depends on is forced); the balance measurement itself is `tests/test_simulate_social.py`'s
(`slow`).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))                    # scripts.* importable (tests/test_generate_art_cli.py:33)

import scripts.simulate_social as sim  # noqa: E402
from tests.social_fixtures import _force_stage, _matched_in, receipts_active  # noqa: E402,F401


@pytest.fixture
def phone(receipts_active):
    with sim._quiet_summaries():
        made = sim.Phone(3, "neutral_model")
        try:
            yield made
        finally:
            made.close()


def _world(phone: Any, policy: str = "attentive") -> Any:
    player = sim.POLICIES[policy](phone, 3)
    player.in_world = True
    player.world = sim.World(phone, player)
    return player.world


def _until_hour(phone: Any, hour: float) -> None:
    """The phone's `wait 1h` until the clock reads ``hour`` o'clock or later, the same day or the next."""
    for _ in range(30):
        if hour <= phone.now % 24 < hour + 1.0:
            return
        phone.act("wait", args={"until": "1h"})
    raise AssertionError(f"never reached {hour}:00")


def _locked(phone: Any):
    from contextlib import contextmanager

    from engine.session.store import release_turn

    @contextmanager
    def held():
        assert phone.session.lock.acquire(blocking=False)
        try:
            yield
        finally:
            release_turn(phone.session)

    return held()


def _met(phone: Any, monkeypatch: pytest.MonkeyPatch, *commitments: str) -> str:
    """A match at numbers, every draw a plan or a scene reads forced (pre-flight F16): ``commitments`` willing,
    available now, no boundary, no flake."""
    from engine.social import convo, growth, plans
    from engine.social.convo import Availability

    real = growth.willing
    monkeypatch.setattr(growth, "willing", lambda s, p, c: (True, "") if c in commitments else real(s, p, c))
    monkeypatch.setattr(convo, "available", lambda s, p, at: Availability(True))
    monkeypatch.setattr(convo, "boundary_minutes", lambda s, p, at: None)
    monkeypatch.setattr(plans, "_flake_drawn", lambda s, p: False)
    pid = _matched_in(phone.session, "matchstick").split(":")[1]
    with _locked(phone):
        _force_stage(phone.state, pid, "numbers")
    return pid


def _moments(monkeypatch: pytest.MonkeyPatch, band: str = "fine") -> None:
    """Every moment `band` and the evening `fine`, so no scene closes early on a draw."""
    from engine.social import scene as social_scene

    monkeypatch.setattr(social_scene, "_moment_draw", lambda s, p: 0.0)
    monkeypatch.setattr(social_scene, "_prior_draw", lambda s, p: 0.0)
    monkeypatch.setattr(social_scene, "_band_of", lambda score: band)
    monkeypatch.setattr(social_scene, "_scene_band", lambda average: "fine")


# -- the storyteller -------------------------------------------------------------------------------------------


def test_the_harness_storyteller_answers_under_the_live_grammar(phone) -> None:
    from engine.game.intents import legal_intents
    from engine.llm.schemas import storyteller_turn_schema
    from tests.schema_check import validate

    turn = phone.narrator.turn()
    assert not validate(turn, storyteller_turn_schema(intents=legal_intents(phone.state))["schema"])
    assert sim.StubNarration()([{"role": "user", "content": "summarise"}]) == "Nothing is said, at length."


# -- the phone's wait --------------------------------------------------------------------------------------------


def test_the_phone_waits_no_further_than_the_worlds_next_step(phone, monkeypatch) -> None:
    from engine.social import turn

    player = sim.POLICIES["attentive"](phone, 3)
    _until_hour(phone, 9)                                        # well before bedtime
    monkeypatch.setattr(turn, "_next_notifying_at", lambda state: None)
    now = phone.now
    assert player.wait_for_more(stop_at=now) is True
    assert phone.now == now                                      # due now: nothing waited
    assert player.wait_for_more(stop_at=now + 3.0) is True
    assert phone.now == pytest.approx(now + 1.0)                 # an hour toward it, never past it
    assert player.wait_for_more() is False                       # T9's wait, unchanged: nothing comes


# -- dinner, bed, work -----------------------------------------------------------------------------------------


def test_dinner_is_made_and_eaten_in_the_kitchen(phone) -> None:
    world = _world(phone)
    _until_hour(phone, sim.DINNER_HOUR)
    assert world.dinner()
    assert phone.state.location_id == "apt_kitchen"
    assert world.counts["dinners"] == 1 and phone.world_refused == 0 and phone.world_actions >= 3
    assert not world.dinner()                                    # once an evening


def test_bed_walks_to_the_bedroom_and_sleeps_to_the_morning(phone) -> None:
    world = _world(phone)
    _until_hour(phone, 21)
    before = phone.now
    world.bed()
    assert phone.state.location_id == "apt_bedroom"
    assert phone.now > before + 4 and sim.HOUR_WAKE <= phone.now % 24 < sim.MORNING_ENDS
    assert phone.world_refused == 0


def test_a_work_day_goes_from_the_hall_and_comes_back_there(phone) -> None:
    world = _world(phone)
    band = world._work_band()
    assert band is not None, "the harness player has no work band"
    for _ in range(48):
        if sim._day_of(band[0]) == world.day and phone.now >= band[0] - sim.WORK_LEAD_HOURS:
            break
        phone.act("wait", args={"until": "1h"})
        band = world._work_band()
    assert world.work()
    assert world.counts["work_days"] == 1
    assert not phone.state.social.get("at_work") and phone.now >= band[1] - 1e-6
    assert phone.state.location_id == "apt_hall" and phone.world_refused == 0


# -- the four life decks (v0.24.0 §12.2, §13) -------------------------------------------------------------------


@pytest.mark.parametrize("deck", sorted(sim.DECK_ROOMS))
def test_a_running_life_deck_is_walked_to_and_its_first_beat_taken(phone, deck) -> None:
    from engine.game.effects import apply_effect

    world = _world(phone)
    state = phone.state
    with _locked(phone):
        started = apply_effect(state, {"type": "social_life", "op": "start", "who": "player", "id": deck,
                                       "at": state.world_clock_hours})
    assert started.get("ok") and state.flags.get(f"life_{deck}")
    assert world.deck()
    assert state.location_id == sim.DECK_ROOMS[deck]
    assert not state.flags.get(f"life_{deck}")                  # every beat clears its flag
    assert world.counts["decks"] == {deck: 1} and phone.world_refused == 0
    assert not world.deck()                                      # once: nothing running now


# -- plans and scenes --------------------------------------------------------------------------------------------


def test_a_plan_is_kept_at_its_place_and_the_evening_spent(phone, monkeypatch) -> None:
    from engine import social
    from engine.social import places, plans

    pid = _met(phone, monkeypatch, "meet")
    _moments(monkeypatch)
    with _locked(phone):
        row = plans.make(phone.state, pid, kind="drinks", when="now", venue="the_anchor")
    assert row is not None
    world = _world(phone)
    rec = sim.Recorder()
    with sim._recording(rec):
        assert world.plan()
    assert plans.get(phone.state, row["id"])["status"] == "met"
    assert [s["pid"] for s in rec.scenes] == [pid] and rec.scenes[0]["moments"] == len(sim.DATE_MOVES)
    assert not social.scene_open(phone.state) and places.is_flat(phone.state.location_id)
    assert phone.world_refused == 0


def test_an_evening_moves_on_once_and_never_back_and_forth(phone, monkeypatch) -> None:
    """Found by the first devoted run (92 scenes in 15 sessions): with both homes willing, "back to yours" from
    the venue, then "back to theirs" from the flat, then "back to yours" again... An evening moves on once."""
    from engine import social
    from engine.social import plans

    pid = _met(phone, monkeypatch, "meet", "come_over", "go_to_theirs")
    _moments(monkeypatch)
    with _locked(phone):
        row = plans.make(phone.state, pid, kind="drinks", when="now", venue="the_anchor")
    assert row is not None
    world = _world(phone)
    rec = sim.Recorder()
    with sim._recording(rec):
        assert world.plan()
    assert [s["kind"] for s in rec.scenes] == ["drinks", "your_place"]
    assert not social.scene_open(phone.state) and phone.world_refused == 0


def test_a_stay_over_opens_the_morning_and_the_next_session_sees_them_out(phone, monkeypatch) -> None:
    """v0.24.0 §13: an accepted stay-over ends the session; the morning scene opens at the player's morning,
    and the policy takes one `quiet` and sees them out. The morning is no second scene (spec §12.1)."""
    from engine import social
    from engine.social import scene as social_scene

    pid = _met(phone, monkeypatch, "meet", "stay_over", "come_over", "go_to_theirs")
    _moments(monkeypatch)
    monkeypatch.setattr(social_scene, "stay_offered", lambda s: True)
    monkeypatch.setattr(social_scene, "_stay_drawn", lambda s, p: True)
    state = phone.state
    _until_hour(phone, 20)
    with _locked(phone):
        state.social["phone_up"] = False
        state.location_id = "apt_lounge"
        assert social_scene.open_scene(state, pid, "apt_lounge", kind="your_place")["ok"]
        state.social["scene"]["energy"] = 100.0
    world = _world(phone)
    rec = sim.Recorder()
    with sim._recording(rec):
        world.scene()
        assert world.stayed and world.counts["stay_overs"] == 1
        assert social_scene.current(state)["kind"] == social_scene.MORNING
        assert state.location_id == "apt_kitchen"
        world.stayed = False                                     # the next session
        world.scene()
    assert not social.scene_open(state) and state.location_id == "apt_kitchen"
    assert [(s["kind"], s["moments"]) for s in rec.scenes] == [("your_place", 2), ("morning", 1)]
    assert phone.world_refused == 0


# -- a full session --------------------------------------------------------------------------------------------


def test_a_full_session_plays_the_world_and_ends_in_the_morning(phone) -> None:
    player = sim.POLICIES["attentive"](phone, 3)
    span = sim.Session(phone, player, model_seconds=15).play()
    assert player.in_world and player.world is not None
    assert phone.world_actions > 0 and phone.world_charges
    assert {kind for *_rest, kind in phone.world_charges} <= {"world", "moment"}
    assert sim.HOUR_WAKE <= phone.now % 24 < sim.MORNING_ENDS and phone.now > span["end"]
    assert phone.world_refused == 0, phone.refusals


def test_a_phone_only_session_is_t9s(phone) -> None:
    player = sim.POLICIES["attentive"](phone, 3)
    sim.Session(phone, player, model_seconds=15, world=False).play()
    assert not player.in_world and player.world is None
    assert phone.world_actions == 0 and not phone.world_charges


# -- the session's shape (v0.24.0 T11: the phone's share of a session) ---------------------------------------


def test_the_real_clock_caps_the_phone_and_not_the_world() -> None:
    clock = sim.RealClock(15, budget=100.0, phone_budget=60.0)
    clock.charge("send")                                         # 30 s on the phone
    assert clock.phone_spent == 30.0 and not clock.phone_over
    clock.spent += 35.0                                          # a world turn: the session's, not the phone's
    assert clock.phone_spent == 30.0 and clock.spent == 65.0 and not clock.over
    clock.charge("send")
    assert clock.phone_over and not clock.over
    uncapped = sim.RealClock(15, budget=100.0)                   # no phone budget: the session's (T9's)
    assert uncapped.phone_budget == 100.0


def test_a_full_sessions_phone_is_capped_and_its_day_goes_on(phone, monkeypatch) -> None:
    player = sim.POLICIES["attentive"](phone, 3)

    def hungry_look() -> None:                                   # a phone that would take the whole session
        while not player.over():
            phone.clock.charge("send")
            phone.charges.append(("", phone.now, sim.REAL_SECONDS["send"], 0.0, False))

    monkeypatch.setattr(player, "look", hungry_look)
    phone.act("wait", args={"until": "morning"})                 # a whole day ahead (a run opens at 20:00)
    clocks: list[Any] = []
    real = sim.RealClock

    def recording(*args: Any, **kwargs: Any) -> Any:
        clocks.append(real(*args, **kwargs))
        return clocks[-1]

    sim.RealClock = recording                                    # type: ignore[misc]
    try:
        sim.Session(phone, player, model_seconds=15).play()
    finally:
        sim.RealClock = real                                     # type: ignore[misc]
    clock = clocks[0]
    assert clock.phone_budget == pytest.approx(sim.PHONE_SHARE * sim.SESSION_REAL_SECONDS)
    phone_seconds = sum(seconds for _pid, _at, seconds, _m, _e in phone.charges)
    # The cap stops the phone at the action that reaches it; only the wind-down's "talk later"s come after.
    assert phone_seconds <= clock.phone_budget + 600.0
    assert player.world.counts["dinners"] == 1, player.world.counts    # the day went on to dinner
    assert phone.world_refused == 0, phone.refusals


def test_a_phone_only_session_has_no_phone_cap(phone) -> None:
    player = sim.POLICIES["attentive"](phone, 3)
    clocks: list[Any] = []
    real = sim.RealClock

    def recording(*args: Any, **kwargs: Any) -> Any:
        clocks.append(real(*args, **kwargs))
        return clocks[-1]

    sim.RealClock = recording                                    # type: ignore[misc]
    try:
        sim.Session(phone, player, model_seconds=15, world=False).play()
    finally:
        sim.RealClock = real                                     # type: ignore[misc]
    assert clocks[0].phone_budget == clocks[0].budget


# -- the report --------------------------------------------------------------------------------------------------


def _run(policy: str, **world: Any) -> dict[str, Any]:
    """A folded run's minimum, with a world (``world``'s keys over a quiet default)."""
    base: dict[str, Any] = {
        "seed": 0, "sessions": 2, "policy": policy, "voice": "neutral_model", "model_seconds": 15.0,
        "end": 14 * 24.0, "spans": [{"start": 7.0, "end": 23.0, "real_seconds": 2400.0},
                                    {"start": 31.0, "end": 14 * 24.0, "real_seconds": 2400.0}],
        "people": [], "episodes": [], "starts": [], "cold": [], "promises": [], "charges": [],
        "prompt_tokens": {}, "short_full": 0, "full": 0, "actions": 0, "refused": 0, "refusals": {}, "unquiet": 0,
        "wall_seconds": 0.0, "archetypes": [],
        "scenes": [], "life": [], "plans_made": [], "plans_closed": {}, "world_charges": [], "world_actions": 0,
        "world_refused": 0, "world_counts": {"decks": {}}, "jump_events": None, "active_20h": None,
        "stage_real": {}, "real_total": 1.0,
    }
    base.update(world)
    return base


def _scene(pid: str, kind: str, band: str, at: float) -> dict[str, Any]:
    return {"pid": pid, "kind": kind, "band": band, "opened_at": at, "at": at + 2, "reason": "player", "moments": 2}


def test_the_report_folds_the_worlds_rows() -> None:
    person = {"pid": "p1", "archetype": "steady", "pace": 1.0, "matched_at": 8.0, "talking_at": None,
              "numbers_at": None, "depth1_at": None, "ghosted_at": None, "left_at": None, "band_at": {},
              "theirs": [], "charges": [], "initiations": 0, "depth_at": {"2": 40.0}, "depth_real": {"2": 3.5},
              "matched_real": 0.5}
    attentive = _run("attentive", people=[person],
                     scenes=[_scene("p1", "drinks", "great", 35.0), _scene("p1", "morning", "bad", 55.0),
                             _scene("p1", "your_place", "good", 38.0)],
                     life=[{"who": "player", "pid": "", "id": "lift_out", "at": 30.0, "depth": 0},
                           {"who": "person", "pid": "p1", "id": "holiday", "at": 50.0, "depth": 2}],
                     world_counts={"decks": {"lift_out": 1, "boiler": 1}},
                     world_charges=[[35.0, 60.0, "world"], [40.0, 15.0, "moment"]],
                     jump_events=120, active_20h=4)
    devoted = _run("devoted", stage_real={"together": 8.0, "living_together": 25.0})
    rep = sim.fold([attentive, devoted])
    # The morning after counts as no scene (spec §12.1): two scenes, great and good.
    assert (rep["scene_band.great"], rep["scene_band.good"], rep["scene_band.bad"]) == (0.5, 0.5, 0.0)
    assert rep["sessions_to_first_scene"] == 1.0                 # matched in session 0, first scene in session 1
    assert rep["real_hours_to_depth.fast.2"] == 3.0 and rep["real_hours_to_depth.fast.3"] is None
    weeks = (14 * 24.0 - 7.0) / (7 * 24.0)
    assert rep["life_events.player_per_week"] == round(1 / weeks, 3)
    assert rep["life_decks_met_per_week"] == round(1 / weeks, 3)  # the four decks only: boiler is not one
    assert rep["also.decks_met_per_run"] == {"boiler": 1.0, "lift_out": 1.0}
    assert rep["life_events.person_per_month_d2plus"] == round(1 / ((14 * 24.0 - 40.0) / (30 * 24.0)), 3)
    assert rep["devoted.together_10h"] == 1.0 and rep["devoted.living_together_20h"] == 0.0
    assert rep["devoted.married_40h"] == 0.0
    assert rep["active_relationships_20h.attentive"] == 4.0 and rep["active_relationships_20h.bachelor"] is None
    assert rep["events_per_jump_morning_day60"] == 120
    assert rep["ratio.world"] == round(75.0 / (75.0 / 60.0), 3)
    assert set(sim.UNBANDED_ROWS) <= set(sim.REPORT_ROWS)


def test_a_run_folded_from_before_the_world_reports_none_for_its_rows() -> None:
    old = _run("attentive")
    for key in ("scenes", "life", "plans_made", "plans_closed", "world_charges", "world_actions", "world_refused",
                "world_counts", "jump_events", "active_20h", "stage_real", "real_total"):
        old.pop(key)
    rep = sim.fold([old])
    assert rep["scene_band.great"] is None and rep["life_decks_met_per_week"] is None and rep["ratio.world"] is None


def test_a_capped_phone_still_keeps_the_players_promise(phone) -> None:
    """Past the phone's share the player still keeps a promise whose window is open (one message): the cap
    stops browsing and chatting, never a word the player gave (T11's re-time: 17.5% kept without this)."""
    tid = _matched_in(phone.session, "matchstick")
    pid = tid.split(":")[1]
    player = sim.POLICIES["attentive"](phone, 3)
    now = phone.now
    phone.state.social.setdefault("promises", {})["p_test"] = {
        "id": "p_test", "pid": pid, "by": "player", "status": "open", "window": "tonight",
        "opens_at": now - 0.1, "closes_at": now + 2.0}
    phone.clock = player.clock = sim.RealClock(15, budget=2400.0, phone_budget=0.0)
    try:
        assert player.over()
        player.keep_due_promises()
    finally:
        phone.clock = player.clock = None
    from engine.social import messaging

    last = messaging.last_shown(messaging.thread(phone.state, tid))
    assert last is not None and last.get("from") == "player"
