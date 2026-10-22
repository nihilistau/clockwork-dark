"""Plans kept in place (v0.23.0 addendum 4, W2-W4; C1, I3-I5; T23C)."""

from __future__ import annotations

import pytest

from tests.social_fixtures import (  # noqa: F401
    _force_stage, _set_person, matched, receipts_active, receipts_state,
)
from tests.test_social_plans import _willing_meet


def _plan(state, matched, monkeypatch, *, when="now", kind="drinks", venue="the_anchor", **kw):
    from engine.social import plans

    _willing_meet(monkeypatch)
    pid = matched("matchstick").split(":")[1]
    row = plans.make(state, pid, kind=kind, when=when, venue=venue, **kw)
    assert row is not None
    return pid, state.social["plans"][row["id"]]


def _advance_to(state, at: float) -> None:
    from engine.game import clock

    clock.advance_time(state, max(0.0, at - state.world_clock_hours))


def _arrived_texts(state, pid: str) -> list:
    """Every `arrived` decision of `pid`'s, landed in a thread or still queued."""
    landed = [m for t in state.social["threads"].values() for m in t.get("messages") or ()
              if m.get("from") == pid and (m.get("decision") or {}).get("situation") == "arrived"]
    queued = [e for e in state.social["queue"] if e["pid"] == pid
              and (e.get("decision") or {}).get("situation") == "arrived"]
    return landed + queued


def test_arrival_replays(receipts_state, matched, monkeypatch) -> None:
    """The lateness is a counterless draw keyed on the plan id: the same answer twice, and no stream moves."""
    from engine.social import plans

    _, row = _plan(receipts_state, matched, monkeypatch)
    assert row["arrives_at"] >= row["due_at"] == row["made_at"] and row["arrived"] is False
    counters = dict(receipts_state.rng_counters)
    first = plans._arrival(receipts_state, dict(row), {}, row["made_at"])
    assert first == plans._arrival(receipts_state, dict(row), {}, row["made_at"])
    assert (round(first[0], 4), round(first[1], 4)) == (row["due_at"], row["arrives_at"])
    assert dict(receipts_state.rng_counters) == counters
    travel = plans.places.travel_minutes("the_anchor") / 60.0
    lo, hi = plans._data()["arrival"]["late_minutes"]
    assert travel + lo / 60.0 - 1e-3 <= row["arrives_at"] - row["due_at"] <= travel + hi / 60.0 + 1e-3


def test_plan_arrive_never_opens_a_scene(receipts_state, matched, monkeypatch) -> None:
    from engine import social

    receipts_state.location_id = "the_anchor"
    receipts_state.social["phone_up"] = False
    _, row = _plan(receipts_state, matched, monkeypatch)
    _advance_to(receipts_state, row["arrives_at"] + 0.01)
    assert receipts_state.social["plans"][row["id"]]["arrived"] is True
    assert not social.scene_open(receipts_state)                          # recorded only (I4)
    assert receipts_state.social["plans"][row["id"]]["status"] == "open"


def test_plan_made_where_you_stand_opens_on_arrival(receipts_state, matched, monkeypatch) -> None:
    from engine import social
    from engine.social import plans

    receipts_state.location_id = "the_anchor"
    receipts_state.social["phone_up"] = False
    _, row = _plan(receipts_state, matched, monkeypatch)
    assert plans.meet_if_here(receipts_state).get("quiet")               # not there yet
    _advance_to(receipts_state, row["arrives_at"] + 0.01)
    assert plans.meet_if_here(receipts_state).get("scene")
    assert social.scene_open(receipts_state)
    assert receipts_state.social["plans"][row["id"]]["status"] == "met"


def test_wait_for_them_opens_the_scene(receipts_state, matched, monkeypatch) -> None:
    from engine import social
    from engine.social import scene, world

    receipts_state.location_id = "the_anchor"
    receipts_state.social["phone_up"] = False
    pid, row = _plan(receipts_state, matched, monkeypatch)
    targets = dict(scene.plan_wait_options(receipts_state))
    assert targets == {f"plan:{row['id']}": f"Wait for {scene._name(receipts_state, pid)}"}
    offered = {t for v in world.world_verbs(receipts_state) if v.action == "scene" for t in v.targets}
    assert f"plan:{row['id']}" in offered                                  # on the world row (W2)
    from engine.social import away

    built = [c for c in away.world_choices(receipts_state, prefix="world")
             if c.get("intent") == {"action": "scene", "target": f"plan:{row['id']}"}]
    assert [c["text"] for c in built] == [f"Wait for {scene._name(receipts_state, pid)}"]     # the built row (M3)
    out = scene.move(receipts_state, f"plan:{row['id']}")
    assert out["ok"] and out.get("met") == row["id"], out
    assert social.scene_open(receipts_state) and receipts_state.world_clock_hours >= row["arrives_at"]
    assert not scene.plan_wait_options(receipts_state)


def test_wait_is_capped(receipts_state, matched, monkeypatch) -> None:
    """A `tonight` plan due hours away: "Wait for" waits at most `wait_cap_hours`, then the player is still waiting."""
    from engine import social
    from engine.social import plans, scene

    _willing_meet(monkeypatch)
    monkeypatch.setattr(plans, "_tonight_span", lambda s, p, at: (at + 5.0, at + 9.0))
    pid = matched("matchstick").split(":")[1]
    receipts_state.location_id = "the_anchor"
    receipts_state.social["phone_up"] = False
    row = plans.make(receipts_state, pid, kind="drinks", when="tonight", venue="the_anchor")
    before = receipts_state.world_clock_hours
    out = scene.move(receipts_state, f"plan:{row['id']}")
    assert out["ok"] and not social.scene_open(receipts_state)
    assert receipts_state.world_clock_hours - before == pytest.approx(plans.wait_cap_hours(), abs=1e-4)


def test_a_target_not_offered_is_refused(receipts_state, matched, monkeypatch) -> None:
    """Rule 1: only an offered `plan:<id>` waits (elsewhere, nothing is offered)."""
    from engine.social import scene

    receipts_state.location_id = "merrow_street"
    receipts_state.social["phone_up"] = False
    _, row = _plan(receipts_state, matched, monkeypatch)
    before = receipts_state.world_clock_hours
    assert not scene.move(receipts_state, f"plan:{row['id']}")["ok"]
    assert receipts_state.world_clock_hours == before


@pytest.mark.parametrize("room", ["apt_lounge", "apt_bedroom", "apt_kitchen", "apt_dining", "apt_hall",
                                  "bldg_lift", "bldg_reception"])
def test_your_place_opens_in_the_lounge(receipts_state, matched, monkeypatch, room) -> None:
    from engine.social import places, plans, scene

    assert places.is_flat(room)
    receipts_state.location_id = room
    receipts_state.social["phone_up"] = False
    _, row = _plan(receipts_state, matched, monkeypatch, kind="your_place", venue="")
    assert f"plan:{row['id']}" in dict(scene.plan_wait_options(receipts_state))
    _advance_to(receipts_state, row["arrives_at"] + 0.01)
    assert not _arrived_texts(receipts_state, row["pid"])                # the player is home: no text
    assert plans.meet_if_here(receipts_state).get("scene")
    assert receipts_state.location_id == "apt_lounge"
    assert scene.current(receipts_state)["location"] == "apt_lounge"


def test_your_place_travel_from_their_home(receipts_state, matched, monkeypatch) -> None:
    """I3: the person travels from their own home, not 0 minutes from the lounge."""
    from engine.social import places

    pid, row = _plan(receipts_state, matched, monkeypatch, kind="your_place", venue="")
    trip = places.travel_minutes(places.home_of(receipts_state, pid))
    assert trip > 0
    assert row["arrives_at"] - row["due_at"] >= trip / 60.0 - 1e-3


def test_their_place_arrives_at_due(receipts_state, matched, monkeypatch) -> None:
    _, row = _plan(receipts_state, matched, monkeypatch, kind="their_place", venue="")
    assert row["arrives_at"] == row["due_at"] == row["made_at"]


def test_put_down_meets_if_here(receipts_state, matched, monkeypatch) -> None:
    from engine import social
    from engine.social import world

    receipts_state.location_id = "the_anchor"
    receipts_state.social["phone_up"] = True
    _, row = _plan(receipts_state, matched, monkeypatch)
    _advance_to(receipts_state, row["arrives_at"] + 0.01)
    assert not social.scene_open(receipts_state)                          # the phone was up
    out = world.put_down(receipts_state)
    assert social.scene_open(receipts_state) and out.get("met") == row["id"]


def test_places_go_meets_at_the_far_end_not_here(receipts_state, matched, monkeypatch) -> None:
    """The Places app puts the phone down WITHOUT meeting here, then meets at the venue it goes to."""
    from engine import social
    from engine.social import world

    receipts_state.location_id = "merrow_street"
    receipts_state.social["phone_up"] = True
    _, row = _plan(receipts_state, matched, monkeypatch)
    _advance_to(receipts_state, row["arrives_at"] + 0.01)
    assert world.places_go(receipts_state, "the_anchor")["ok"]
    assert social.scene_open(receipts_state)
    assert receipts_state.social["plans"][row["id"]]["status"] == "met"


def test_go_after_arrival_opens_it(receipts_state, matched, monkeypatch) -> None:
    from engine import social
    from engine.social import world

    receipts_state.location_id = "merrow_street"
    receipts_state.social["phone_up"] = False
    _, row = _plan(receipts_state, matched, monkeypatch)
    _advance_to(receipts_state, row["arrives_at"] + 0.01)
    assert world.go(receipts_state, "the_anchor")["ok"]
    assert social.scene_open(receipts_state)


def test_go_before_arrival_waits(receipts_state, matched, monkeypatch) -> None:
    """Getting there first opens nothing: the player waits ("Wait for {name}" is offered), no stood-up."""
    from engine import social
    from engine.social import scene, world

    receipts_state.location_id = "merrow_street"
    receipts_state.social["phone_up"] = False
    monkeypatch.setattr(world.places, "travel_minutes", lambda loc: 0)      # the player gets there at once
    _willing_meet(monkeypatch)
    from engine.social import plans

    pid = matched("matchstick").split(":")[1]
    monkeypatch.setattr(plans, "_arrival", lambda s, r, e, at: (at, at + 0.5))
    row = plans.make(receipts_state, pid, kind="drinks", when="now", venue="the_anchor")
    assert world.go(receipts_state, "the_anchor")["ok"]
    assert not social.scene_open(receipts_state)
    assert receipts_state.social["plans"][row["id"]]["status"] == "open"
    assert f"plan:{row['id']}" in dict(scene.plan_wait_options(receipts_state))


def test_arrived_text_when_absent(receipts_state, matched, monkeypatch) -> None:
    receipts_state.location_id = "apt_lounge"
    pid, row = _plan(receipts_state, matched, monkeypatch)
    _advance_to(receipts_state, row["arrives_at"] + 0.01)
    found = _arrived_texts(receipts_state, pid)
    assert found
    decision = found[0].get("decision") or {}
    assert decision.get("plan_id") == row["id"]


def test_activity_stops_at_their_arrival(receipts_state, matched, monkeypatch) -> None:
    from engine import social
    from engine.social import plans, world

    receipts_state.location_id = "apt_lounge"
    receipts_state.social["phone_up"] = False
    _willing_meet(monkeypatch)
    monkeypatch.setattr(plans, "_arrival", lambda s, r, e, at: (at, at + 0.5))   # inside the 90 minutes
    pid = matched("matchstick").split(":")[1]
    row = plans.make(receipts_state, pid, kind="your_place", when="now", venue="")
    out = world.do(receipts_state, "watch_something")                     # 90 minutes, interruptible
    assert receipts_state.world_clock_hours == pytest.approx(row["arrives_at"], abs=1 / 60)
    assert out["stopped"] and "arrive" in out["arrived"].lower() and "buzz" not in out
    assert social.scene_open(receipts_state) and out.get("met") == row["id"]     # met at the activity's end


def test_wait_next_stops_at_an_arrival_here(receipts_state, matched, monkeypatch) -> None:
    """`turn._next_notifying_at` counts a `plan_arrive` at the player's place, and none elsewhere."""
    from engine.social import turn

    receipts_state.location_id = "the_anchor"
    _, row = _plan(receipts_state, matched, monkeypatch)
    arrive = next(e for e in receipts_state.social["queue"] if e["kind"] == "plan_arrive")
    assert turn._arrival_here(receipts_state, arrive)
    assert turn._next_notifying_at(receipts_state) <= row["arrives_at"]
    receipts_state.location_id = "merrow_street"
    assert not turn._arrival_here(receipts_state, arrive)


def test_arrival_during_another_scene(receipts_state, matched, monkeypatch) -> None:
    """I4: they arrive while another scene is open: no scene for them; it opens when that one ends (then: stay)."""
    from engine import social
    from engine.social import scene

    receipts_state.location_id = "the_anchor"
    receipts_state.social["phone_up"] = False
    other = matched("front_porch").split(":")[1]
    assert scene.open_scene(receipts_state, other, "the_anchor", kind="chance")["ok"]
    pid, row = _plan(receipts_state, matched, monkeypatch)
    _advance_to(receipts_state, row["arrives_at"] + 0.01)
    assert scene.current(receipts_state)["pid"] == other
    out = scene.end_scene(receipts_state, "player", then="stay")
    assert social.scene_open(receipts_state) and scene.current(receipts_state)["pid"] == pid
    assert out["next"]["met"] == row["id"]


def test_arrival_during_another_scene_past_patience_still_meets(receipts_state, matched, monkeypatch) -> None:
    """Fix round 1, the I3 ruling: while the player is at the place the person never stands them up, so a scene
    that outlasts their patience is followed by theirs, not by a stood-up."""
    from engine import social
    from engine.social import scene

    receipts_state.location_id = "the_anchor"
    receipts_state.social["phone_up"] = False
    other = matched("front_porch").split(":")[1]
    scene.open_scene(receipts_state, other, "the_anchor", kind="chance")
    pid, row = _plan(receipts_state, matched, monkeypatch)
    _advance_to(receipts_state, row["arrives_at"] + row["patience_hours"] + 0.1)
    scene.end_scene(receipts_state, "player", then="stay")
    assert social.scene_open(receipts_state) and scene.current(receipts_state)["pid"] == pid
    assert receipts_state.social["plans"][row["id"]]["status"] == "met"


def _closer_target(state, closer: str) -> str:
    from engine.social import scene

    offered = [t for t, _ in scene._close_options(state, scene.current(state))]
    return next(t for t in offered if t == closer or t.startswith(f"{closer}:"))


@pytest.mark.parametrize("closer", ["back_to_yours", "back_to_theirs", "go_somewhere_else"])
def test_back_to_yours_opens_on_arrival(receipts_state, matched, monkeypatch, closer) -> None:
    """C1: a closer that leaves together carries the person; the scene continues at the new place at once."""
    from engine import social
    from engine.social import growth, scene

    monkeypatch.setattr(growth, "willing", lambda s, p, c: (True, ""))
    pid = matched("matchstick").split(":")[1]
    _force_stage(receipts_state, pid, "dating")
    receipts_state.location_id = "the_anchor"
    receipts_state.social["phone_up"] = False
    scene.open_scene(receipts_state, pid, "the_anchor", kind="drinks")
    out = scene.close(receipts_state, _closer_target(receipts_state, closer))
    assert out.get("plan_id"), out
    row = receipts_state.social["plans"][out["plan_id"]]
    assert row["due_at"] == row["arrives_at"] == row["made_at"] and row["arrived"] is True
    assert not [e for e in receipts_state.social["queue"] if e["kind"] == "plan_arrive"
                and e.get("plan_id") == row["id"]]
    assert not _arrived_texts(receipts_state, pid)
    assert social.scene_open(receipts_state) and scene.current(receipts_state)["pid"] == pid
    assert row["status"] == "met"


def test_upgraded_plan_has_arrival(receipts_state, matched, monkeypatch) -> None:
    from engine.game.effects import apply_effect

    pid, row = _plan(receipts_state, matched, monkeypatch, when="soon")
    assert "arrives_at" not in row and not [e for e in receipts_state.social["queue"] if e["kind"] == "plan_arrive"]
    at = receipts_state.world_clock_hours
    assert apply_effect(receipts_state, {"type": "social_plan", "op": "upgrade", "plan_id": row["id"],
                                         "when": "now", "at": at})["ok"]
    row = receipts_state.social["plans"][row["id"]]
    assert row["due_at"] == row["made_at"] and row["arrives_at"] >= row["due_at"] and row["arrived"] is False
    arrivals = [e for e in receipts_state.social["queue"] if e["kind"] == "plan_arrive"]
    assert len(arrivals) == 1 and arrivals[0]["at"] == row["arrives_at"]
    lapses = [e for e in receipts_state.social["queue"] if e["kind"] == "plan_lapse" and e.get("plan_id") == row["id"]]
    assert len(lapses) == 1 and lapses[0]["at"] > row["arrives_at"] + row["patience_hours"]


def test_late_moves_the_lapse_and_replaces_it(receipts_state, matched, monkeypatch) -> None:
    """C1, the `late` op: its window counts from `arrives_at`, and its `plan_lapse` is re-pushed, never doubled."""
    from engine.game.effects import apply_effect

    _, row = _plan(receipts_state, matched, monkeypatch)

    def lapses():
        return [e for e in receipts_state.social["queue"] if e["kind"] == "plan_lapse" and e.get("plan_id") == row["id"]]

    first = lapses()[0]["at"]
    assert apply_effect(receipts_state, {"type": "social_plan", "op": "late", "plan_id": row["id"]})["ok"]
    assert len(lapses()) == 1 and lapses()[0]["at"] == pytest.approx(first + 0.5)


def test_running_late_counts_from_arrival(receipts_state, matched, monkeypatch) -> None:
    from engine.social import plans

    pid, row = _plan(receipts_state, matched, monkeypatch, when="tonight")
    _advance_to(receipts_state, row["arrives_at"] + row["patience_hours"] - 0.1)   # past made_at + patience
    assert receipts_state.world_clock_hours - row["made_at"] > row["patience_hours"]
    assert plans.running_late(receipts_state, pid)


def _tonight_at_noon(state, matched, monkeypatch):
    """A `tonight` plan made at noon, their evening 19:00-23:00 (forced after `_willing_meet`, which forces its own)."""
    from engine.social import plans
    from tests.social_fixtures import _set_clock

    _willing_meet(monkeypatch)
    monkeypatch.setattr(plans, "_tonight_span", lambda s, p, at: (at - at % 24 + 19, at - at % 24 + 23))
    pid = matched("matchstick").split(":")[1]
    _set_clock(state, 12)
    row = plans.make(state, pid, kind="drinks", when="tonight", venue="the_anchor")
    assert row["due_at"] == round(row["made_at"] - row["made_at"] % 24 + 19, 4)
    state.location_id = "merrow_street"
    state.social["phone_up"] = False
    return pid, state.social["plans"][row["id"]]


def test_tonight_made_at_noon_is_kept_at_seven(receipts_state, matched, monkeypatch) -> None:
    from engine.social import world

    _, row = _tonight_at_noon(receipts_state, matched, monkeypatch)
    _advance_to(receipts_state, row["arrives_at"] + 0.25)                 # 7-ish pm: past made_at + 4 h, within patience
    assert receipts_state.world_clock_hours - row["made_at"] > row["patience_hours"]
    assert world.go(receipts_state, "the_anchor")["ok"]
    assert receipts_state.social["plans"][row["id"]]["status"] == "met"


def test_tonight_does_not_open_in_the_afternoon(receipts_state, matched, monkeypatch) -> None:
    from engine import social
    from engine.social import world
    from tests.social_fixtures import _set_clock

    _, row = _tonight_at_noon(receipts_state, matched, monkeypatch)
    _set_clock(receipts_state, 14)
    world.go(receipts_state, "the_anchor")
    assert not social.scene_open(receipts_state)
    assert receipts_state.social["plans"][row["id"]]["status"] == "open"


def test_patience_counts_from_arrival(receipts_state, matched, monkeypatch) -> None:
    from engine.social import places, world

    receipts_state.location_id = "merrow_street"
    receipts_state.social["phone_up"] = False
    _, row = _plan(receipts_state, matched, monkeypatch)
    travel = places.travel_minutes("the_anchor") / 60.0                   # the go's own minutes land inside it
    _advance_to(receipts_state, row["arrives_at"] + row["patience_hours"] - 0.05 - travel)
    world.go(receipts_state, "the_anchor")
    assert receipts_state.world_clock_hours - row["made_at"] > row["patience_hours"]
    assert receipts_state.social["plans"][row["id"]]["status"] == "met"


def test_patience_past_arrival_is_stood_up(receipts_state, matched, monkeypatch) -> None:
    from engine.social import world

    receipts_state.location_id = "merrow_street"
    receipts_state.social["phone_up"] = False
    _, row = _plan(receipts_state, matched, monkeypatch)
    _advance_to(receipts_state, row["arrives_at"] + row["patience_hours"] + 0.05)
    world.go(receipts_state, "the_anchor")
    assert receipts_state.social["plans"][row["id"]]["status"] == "stood_up"


def test_flake_has_no_arrival(receipts_state, matched, monkeypatch) -> None:
    from engine.social import plans

    _willing_meet(monkeypatch, flake=True)
    pid = matched("matchstick").split(":")[1]
    row = plans.make(receipts_state, pid, kind="drinks", when="now", venue="the_anchor")
    _advance_to(receipts_state, row["arrives_at"] + 0.01)
    assert receipts_state.social["plans"][row["id"]]["status"] == "cancelled"
    assert not receipts_state.social["plans"][row["id"]].get("arrived")
    assert not _arrived_texts(receipts_state, pid)


def _view(state, pid):
    from engine.social import agreement

    return agreement.view_from_state(state, pid)


def test_im_here_fails_before_arrival(receipts_state, matched, monkeypatch) -> None:
    from engine.social import agreement
    from engine.social.kinds import Decision

    pid, row = _plan(receipts_state, matched, monkeypatch)
    reply = {"bubbles": ["i'm here! where are you?"], "shared": [], "learned": []}
    found = agreement.check(reply, Decision(situation="reply"), _view(receipts_state, pid))
    assert [f.check for f in found] == ["arrival_claimed"]


def test_im_here_passes_after_arrival(receipts_state, matched, monkeypatch) -> None:
    from engine.social import agreement
    from engine.social.kinds import Decision

    pid, row = _plan(receipts_state, matched, monkeypatch)
    _advance_to(receipts_state, row["arrives_at"] + 0.01)
    reply = {"bubbles": ["i'm here! where are you?"], "shared": [], "learned": []}
    assert agreement.check(reply, Decision(situation="reply"), _view(receipts_state, pid)) == []


def test_arrival_claimed_is_rechecked_at_commit(receipts_state, matched, monkeypatch) -> None:
    """I5: judged on the snapshot in the pass, then again on the state under the lock (a STATE check, which
    `voicer.commit` re-runs against `view_from_state`). A snapshot taken after arrival agrees with the state."""
    from engine.social import agreement, voicing
    from engine.social.kinds import Decision

    assert "arrival_claimed" in agreement.STATE_CHECKS
    assert "arrival_claimed" not in agreement.SCENE_PROSE_CHECKS            # together, "I'm here" is no claim
    pid, row = _plan(receipts_state, matched, monkeypatch)
    snap_before = agreement.view_from_state(receipts_state, pid)
    reply = {"bubbles": ["just got here x"], "shared": [], "learned": []}
    assert [f.check for f in agreement.check(reply, Decision(situation="reply"), snap_before)] == ["arrival_claimed"]
    assert {"arrives_at", "due_at", "arrived"} <= set(snap_before.plans[0])     # the snapshot's plan rows carry them
    assert voicing.CORRECTIONS["arrival_claimed"].startswith("Your reply said")


def test_the_whereabouts_line(receipts_state, matched, monkeypatch) -> None:
    """The texter's plan line, written from the snapshot's row alone (I5)."""
    from engine.social import voicing

    _, row = _plan(receipts_state, matched, monkeypatch)
    assert voicing.whereabouts(row, row["made_at"]) == "You are on your way to The Anchor."
    arrived = {**row, "arrived": True, "arrives_at": 19 + 40 / 60}
    assert voicing.whereabouts(arrived, 20.0) == "You are at The Anchor, waiting for them since 19:40."
    assert voicing.whereabouts({**row, "when": "soon"}, row["made_at"]) == ""
    assert voicing.whereabouts({k: v for k, v in row.items() if k != "arrives_at"}, row["made_at"]) == ""


def test_owner_playtest_meet_at_the_cafe_you_are_in(receipts_state, matched, monkeypatch) -> None:
    """§7(a), the owner's scenario: a meet planned at the café the player is already in. They arrive, a scene
    opens, and no "I'm there" text from them reaches the player before they do."""
    from engine import social
    from engine.social import agreement, scene
    from engine.social.kinds import Decision

    receipts_state.location_id = "copper_kettle"
    receipts_state.social["phone_up"] = True
    pid, row = _plan(receipts_state, matched, monkeypatch, kind="coffee", venue="copper_kettle")
    reply = {"bubbles": ["I'm here!"], "shared": [], "learned": []}
    assert "arrival_claimed" in [f.check for f in agreement.check(reply, Decision(situation="reply"),
                                                                  _view(receipts_state, pid))]
    from engine.social import world

    world.put_down(receipts_state)
    assert not social.scene_open(receipts_state)                           # not there yet
    assert f"plan:{row['id']}" in dict(scene.plan_wait_options(receipts_state))
    out = scene.move(receipts_state, f"plan:{row['id']}")
    assert out["ok"] and out.get("met") == row["id"]
    assert social.scene_open(receipts_state) and scene.current(receipts_state)["pid"] == pid
    assert not _arrived_texts(receipts_state, pid)                         # the player was there: no text at all


def test_read_paths_draw_and_write_nothing_for_presence(receipts_state, matched, monkeypatch) -> None:
    import copy

    from engine.social import presence

    receipts_state.location_id = "the_anchor"
    pid, row = _plan(receipts_state, matched, monkeypatch)
    before = copy.deepcopy(receipts_state.to_save_dict())
    counters = dict(receipts_state.rng_counters)
    assert presence.where(receipts_state, pid) == "" and not presence.with_player(receipts_state, pid)
    _advance_to(receipts_state, row["arrives_at"] + 0.01)
    before = copy.deepcopy(receipts_state.to_save_dict())
    counters = dict(receipts_state.rng_counters)
    view = presence.here_view(receipts_state)
    assert presence.where(receipts_state, pid, view) == "the_anchor" == presence.where(receipts_state, pid)
    assert presence.with_player(receipts_state, pid) and presence.with_player(receipts_state, pid, view)
    assert receipts_state.to_save_dict() == before and dict(receipts_state.rng_counters) == counters


def test_a_plan_without_arrival_fields_still_keeps(receipts_state, matched, monkeypatch) -> None:
    """A `now` row written before T23C (no `due_at` / `arrives_at` / `arrived`) reads as arrived at `made_at`, as
    the engine read it before: `go` opens it within patience."""
    from engine import social
    from engine.social import world

    receipts_state.location_id = "merrow_street"
    receipts_state.social["phone_up"] = False
    _, row = _plan(receipts_state, matched, monkeypatch)
    for key in ("due_at", "arrives_at", "arrived"):
        row.pop(key)
    assert world.go(receipts_state, "the_anchor")["ok"]
    assert social.scene_open(receipts_state)


def test_the_world_fingerprint_sees_plans_and_arrivals(receipts_state, matched, monkeypatch) -> None:
    """T23A's row is rebuilt when a plan is made or its person arrives (A4 W1 + W2-W4)."""
    from engine.social import turn

    receipts_state.location_id = "merrow_street"
    first = turn.world_fingerprint(receipts_state)
    _, row = _plan(receipts_state, matched, monkeypatch)
    made = turn.world_fingerprint(receipts_state)
    assert made[-1] != first[-1]
    row["arrived"] = True                                                   # only the arrival differs
    assert turn.world_fingerprint(receipts_state)[-1] != made[-1]



# -- fix round 1 ---------------------------------------------------------------------------------------------


def _check(state, pid, text):
    from engine.social import agreement
    from engine.social.kinds import Decision

    reply = {"bubbles": [text], "shared": [], "learned": []}
    return [f.check for f in agreement.check(reply, Decision(situation="reply"), agreement.view_from_state(state, pid))]


def test_arrival_claims_need_an_open_plan(receipts_state, matched, monkeypatch) -> None:
    """I2(a): with no plan open with the player, "I'm at the bar" is an ordinary reply; with one, it is judged."""
    from engine.social import plans

    pid = matched("matchstick").split(":")[1]
    assert _check(receipts_state, pid, "I'm at the bar with work people") == []
    assert _check(receipts_state, pid, "just got here, long shift ahead") == []
    _willing_meet(monkeypatch)
    assert plans.make(receipts_state, pid, kind="drinks", when="now", venue="the_anchor")
    assert _check(receipts_state, pid, "I'm at the bar") == ["arrival_claimed"]


def test_someone_elses_arrival_is_no_claim(receipts_state, matched, monkeypatch) -> None:
    """I2(b): a contact's name or "my <relation>" before the phrase makes it someone else's arrival."""
    from engine.social import matching

    other = matched("front_porch").split(":")[1]                         # matched first: it moves the clock
    pid, _ = _plan(receipts_state, matched, monkeypatch)
    first = matching._name(receipts_state, other).split()[0]
    assert _check(receipts_state, pid, "my mum just got here, gotta go") == []
    assert _check(receipts_state, pid, "my friend got us a table") == []
    assert "arrival_claimed" not in _check(receipts_state, pid, f"{first} just got here")   # (another_person's own)
    assert _check(receipts_state, pid, "ok just got here") == ["arrival_claimed"]


def test_phone_up_at_the_place_buzzes_and_never_stands_up(receipts_state, matched, monkeypatch) -> None:
    """I3: they arrive while the player sits at the place with the phone up: a no-model "<name>'s here" lands
    through the notify path, patience runs out without a stood-up, and putting the phone down opens the scene."""
    from engine import social
    from engine.social import matching, world

    receipts_state.location_id = "the_anchor"
    receipts_state.social["phone_up"] = True
    pid, row = _plan(receipts_state, matched, monkeypatch)
    _advance_to(receipts_state, row["arrives_at"] + 0.01)
    name = matching._name(receipts_state, pid)
    notes = [n for n in receipts_state.social.get("notifications") or () if n.get("pid") == pid]
    assert notes and notes[-1]["kind"] == "arrived" and notes[-1]["preview"] == f"{name}'s here"
    assert not _arrived_texts(receipts_state, pid)                         # no model text: they can see you
    _advance_to(receipts_state, row["arrives_at"] + row["patience_hours"] + 0.5)
    assert receipts_state.social["plans"][row["id"]]["status"] == "open"
    out = world.put_down(receipts_state)
    assert out.get("met") == row["id"] and social.scene_open(receipts_state)
    assert receipts_state.social["plans"][row["id"]]["status"] == "met"


def test_phone_down_at_the_place_meets_at_once(receipts_state, matched, monkeypatch) -> None:
    """I3: the phone already down, they arrive during an activity there: the scene opens at its end, no buzz."""
    from engine import social
    from engine.social import plans, world

    receipts_state.location_id = "apt_lounge"
    receipts_state.social["phone_up"] = False
    _willing_meet(monkeypatch)
    monkeypatch.setattr(plans, "_arrival", lambda s, r, e, at: (at, at + 0.25))
    pid = matched("matchstick").split(":")[1]
    plans.make(receipts_state, pid, kind="your_place", when="now", venue="")
    world.do(receipts_state, "read")
    assert social.scene_open(receipts_state)
    assert not [n for n in receipts_state.social.get("notifications") or () if n.get("kind") == "arrived"]


def test_wait_meets_if_here(receipts_state, matched, monkeypatch) -> None:
    """I1: the phone's `wait` ends with `meet_if_here` (quiet while the phone is up, as any phone action has it)."""
    from engine.social import plans, turn

    calls = []
    real = plans.meet_if_here
    monkeypatch.setattr(plans, "meet_if_here", lambda s: calls.append(1) or real(s))
    turn.wait(receipts_state, {"until": "1h"})
    assert calls


def test_a_room_move_across_their_arrival_shows_the_scene_in_the_same_frame(receipts_active, monkeypatch) -> None:
    """I1 (symptom (d)): a `your_place` arrival during a one-minute room move. The returned frame is the scene's:
    its choices are the scene's moves and closers, it says "<name> arrives.", and `last_turn` agrees."""
    from engine import social
    from engine.session.store import release_turn
    from engine.social import matching, plans
    from tests.social_fixtures import _live_session, _matched_in, _phone
    from tests.social_world_stub import StubNarrator

    scene_app, session = _live_session(llm_fn=StubNarrator())
    state = session.engine.state
    pid = _matched_in(session, "matchstick").split(":")[1]
    _force_stage(state, pid, "numbers")
    _phone(scene_app, session, "wait", args={"until": "1h"})            # a time jump: the row is rebuilt, rooms on it
    _phone(scene_app, session, "put_down")
    _willing_meet(monkeypatch)
    monkeypatch.setattr(plans, "_arrival", lambda s, r, e, at: (at, at + 0.5 / 60.0))   # inside the move's minute
    assert session.lock.acquire(blocking=False)
    try:
        assert plans.make(state, pid, kind="your_place", when="now", venue="")
    finally:
        release_turn(session)
    move = next(c for c in session.last_turn["choices"] if (c.get("intent") or {}).get("action") == "travel")
    resp = scene_app.app.test_client().post("/api/game/choice", json={"session_id": session.session_id,
                                                                      "choice_id": move["id"]})
    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_json()
    assert social.scene_open(state)
    actions = {(c.get("intent") or {}).get("action") for c in body["choices"]}
    assert "close" in actions and "travel" not in actions and "go" not in actions, body["choices"]
    assert f"{matching._name(state, pid)} arrives." in body["narration"]
    assert session.last_turn["choices"] == body["choices"]


def test_the_world_turns_meet_rebuilds_its_frame(receipts_active, monkeypatch) -> None:
    """I1, `default_scene._meet_if_here` directly: nothing to meet leaves the result alone; a scene opened rewrites
    the returned payload's choices and narration and the session's `last_turn`."""
    from engine import social
    from engine.scenes import default_scene
    from engine.social import plans
    from tests.social_fixtures import _live_session, _matched_in, _phone
    from tests.social_world_stub import StubNarrator

    scene_app, session = _live_session(llm_fn=StubNarrator())
    state = session.engine.state
    pid = _matched_in(session, "matchstick").split(":")[1]
    _phone(scene_app, session, "put_down")
    frame = {"narration": "You look around.", "choices": [{"id": "x", "text": "Look around"}]}
    result = (dict(frame), "", False)
    assert default_scene._meet_if_here(session, result) == result         # nothing arrived: untouched
    _willing_meet(monkeypatch)
    monkeypatch.setattr(plans, "_arrival", lambda s, r, e, at: (at, at))
    state.location_id = "apt_lounge"
    row = plans.make(state, pid, kind="your_place", when="now", venue="")
    state.social["plans"][row["id"]]["arrived"] = True
    payload, error, busy = default_scene._meet_if_here(session, (dict(frame), "", False))
    assert social.scene_open(state) and not error and not busy
    assert payload["narration"].startswith("You look around.") and payload["narration"].endswith("arrives.")
    assert {(c.get("intent") or {}).get("action") for c in payload["choices"]} >= {"scene", "close"}
    assert session.last_turn["choices"] == payload["choices"]


def test_commit_drops_an_arrival_claim_made_stale(receipts_active, monkeypatch) -> None:
    """M1: a real stale case. The snapshot has no plan, so "I'm at the bar" passes in the pass; a plan is made
    before the commit and they have not arrived, so the commit's state re-check drops the bubble (a fallback)."""
    import threading

    from engine.social import plans
    from tests.social_fixtures import _live_session, _matched_in, _wait_until
    from tests.social_stub import StubVoice
    from tests.test_social_voicer import _due, _reply_json, _start_pass, _theirs

    scene_app, session = _live_session()
    state = session.engine.state
    thread = _matched_in(session, "matchstick")
    pid = thread.split(":")[1]
    _force_stage(state, pid, "numbers")
    _due(scene_app, session, thread)
    gate = threading.Event()
    stub = StubVoice("zero", block=gate, script=[_reply_json("I'm at the bar")])
    p, t, out = _start_pass(session, stub)
    _wait_until(lambda: stub.calls == 1)                                   # passed the pass's own check: no plan
    _willing_meet(monkeypatch)
    assert plans.make(state, pid, kind="drinks", when="now", venue="the_anchor")
    gate.set()
    t.join(5)
    last = _theirs(session, thread)[-1]
    assert out["r"] == "fallback" and "I'm at the bar" not in last["bubbles"]


def test_the_second_socket_update_carries_only_the_arrival_line(receipts_active, monkeypatch) -> None:
    """Re-review: the client appends a non-streamed turn_update's narration, so the second emit carries the arrival line
    alone (with the rebuilt choices); the HTTP result and last_turn keep the whole text."""
    from engine.scenes import default_scene
    from engine.social import matching, plans
    from tests.social_fixtures import _live_session, _matched_in, _phone
    from tests.social_world_stub import StubNarrator

    scene_app, session = _live_session(llm_fn=StubNarrator())
    state = session.engine.state
    pid = _matched_in(session, "matchstick").split(":")[1]
    _phone(scene_app, session, "put_down")
    _willing_meet(monkeypatch)
    monkeypatch.setattr(plans, "_arrival", lambda s, r, e, at: (at, at))
    state.location_id = "apt_lounge"
    row = plans.make(state, pid, kind="your_place", when="now", venue="")
    state.social["plans"][row["id"]]["arrived"] = True
    sent = []
    frame = {"narration": "You look around.", "choices": [{"id": "x", "text": "Look around"}]}
    payload, _, _ = default_scene._meet_if_here(session, (dict(frame), "", False),
                                                lambda event, body: sent.append((event, body)))
    line = f"{matching._name(state, pid)} arrives."
    assert [e for e, _ in sent] == ["turn_update"]
    assert sent[0][1]["narration"] == line and sent[0][1]["choices"] == payload["choices"]
    assert payload["narration"] == "You look around.\n\n" + line == session.last_turn["narration"]
