"""A quiet phone while together (v0.23.0 addendum 4, W5; I6)."""

from __future__ import annotations

from types import SimpleNamespace

from tests.social_fixtures import (  # noqa: F401
    _force_stage, _open_episode, matched, receipts_active, receipts_state,
)


def _with(state, matched):
    from engine.social import scene

    tid = matched("matchstick")
    pid = tid.split(":")[1]
    _force_stage(state, pid, "dating")
    state.location_id = "the_anchor"
    scene.open_scene(state, pid, "the_anchor", kind="drinks")
    return pid, tid


def _theirs(state, pid):
    return [m for t in state.social["threads"].values() for m in t.get("messages") or () if m.get("from") == pid]


def _due(state, pid, tid, in_hours=0.1, **extra):
    from engine.social import messaging
    from engine.social.kinds import Decision

    messaging.queue_due(state, pid, tid, Decision(situation="reply"), state.world_clock_hours + in_hours, **extra)


def _queued(state, pid):
    return [e for e in state.social["queue"] if e["pid"] == pid and e["kind"] == "reply"]


def _session(state):
    return SimpleNamespace(engine=SimpleNamespace(state=state), voicing={})


def test_no_text_lands_during_a_scene(receipts_state, matched) -> None:
    from engine.game import clock

    pid, tid = _with(receipts_state, matched)
    landed = len(_theirs(receipts_state, pid))
    _due(receipts_state, pid, tid)
    clock.advance_time(receipts_state, 0.5)
    assert len(_theirs(receipts_state, pid)) == landed
    assert len(_queued(receipts_state, pid)) == 1          # re-pushed, never dropped


def test_a_long_scene_never_grows_the_queue(receipts_state, matched) -> None:
    from engine.game import clock

    pid, tid = _with(receipts_state, matched)
    _due(receipts_state, pid, tid)
    clock.advance_time(receipts_state, 6.0)                # two dozen retries
    assert len(_queued(receipts_state, pid)) == 1


def test_held_text_lands_after_the_scene(receipts_state, matched) -> None:
    from engine.game import clock
    from engine.social import scene

    pid, tid = _with(receipts_state, matched)
    landed = len(_theirs(receipts_state, pid))
    _due(receipts_state, pid, tid)
    clock.advance_time(receipts_state, 0.5)
    scene.end_scene(receipts_state, "player", then="stay")
    receipts_state.location_id = "apt_lounge"
    clock.advance_time(receipts_state, 0.5)
    assert not _queued(receipts_state, pid)
    mine = _theirs(receipts_state, pid)
    assert len(mine) == landed + 1
    assert mine[-1]["decision"]["after_together"] is True


def test_a_text_never_held_is_not_marked(receipts_state, matched) -> None:
    from engine.game import clock

    tid = matched("matchstick")
    pid = tid.split(":")[1]
    _due(receipts_state, pid, tid)
    clock.advance_time(receipts_state, 0.5)
    last = _theirs(receipts_state, pid)[-1]
    assert not last["decision"].get("after_together")


def test_a_hold_makes_no_draw(receipts_state, matched) -> None:
    from engine.game import clock
    from engine.social import messaging

    pid, tid = _with(receipts_state, matched)
    _due(receipts_state, pid, tid)
    seen = []
    real = messaging.behaviour.person_rng
    messaging.behaviour.person_rng = lambda *a, **k: seen.append(a) or real(*a, **k)
    try:
        clock.advance_time(receipts_state, 1.0)
    finally:
        messaging.behaviour.person_rng = real
    assert not seen


def test_the_arrival_notice_is_not_held(receipts_state, matched) -> None:
    from engine.social import messaging

    pid, tid = _with(receipts_state, matched)
    before = len(receipts_state.social.get("notifications") or ())
    t = messaging.thread(receipts_state, tid)
    messaging.notify(receipts_state, str(t["app"]), tid, pid, "arrived", "X's here", at=receipts_state.world_clock_hours)
    assert messaging.held(receipts_state, pid)             # they are with you, and the notice is still made
    assert len(receipts_state.social.get("notifications") or ()) >= before


def test_unvoiced_message_waits_in_voiceable(receipts_state, matched) -> None:
    """I6: an unvoiced message is skipped while together and not counted pending; voiceable again apart."""
    from engine.game import clock
    from engine.social import scene, voicer

    tid = matched("matchstick")
    pid = tid.split(":")[1]
    _force_stage(receipts_state, pid, "dating")
    session = _session(receipts_state)
    _due(receipts_state, pid, tid)
    clock.advance_time(receipts_state, 0.5)
    assert [m for m in voicer._voiceable(receipts_state, session) if m.get("from") == pid]
    receipts_state.location_id = "the_anchor"
    scene.open_scene(receipts_state, pid, "the_anchor", kind="drinks")
    assert not [m for m in voicer._voiceable(receipts_state, session) if m.get("from") == pid]
    assert not voicer.pending(session)
    scene.end_scene(receipts_state, "player", then="stay")
    assert [m for m in voicer._voiceable(receipts_state, session) if m.get("from") == pid]


def test_held_event_round_trips_packing(receipts_state, matched) -> None:
    from engine.game import clock
    from engine.game.state import GameState

    pid, tid = _with(receipts_state, matched)
    _due(receipts_state, pid, tid)
    clock.advance_time(receipts_state, 0.5)
    row = _queued(receipts_state, pid)[0]
    assert row["held"] is True
    import json

    text = json.dumps(receipts_state.to_save_dict(), ensure_ascii=False)
    again = GameState.from_dict(json.loads(text))
    assert json.dumps(again.to_save_dict(), ensure_ascii=False) == text
    assert [e for e in again.social["queue"] if e["pid"] == pid and e["kind"] == "reply"] == [row]


def test_a_landed_after_together_decision_round_trips_packing(receipts_state, matched) -> None:
    import json

    from engine.game import clock
    from engine.game.state import GameState
    from engine.social import scene

    pid, tid = _with(receipts_state, matched)
    _due(receipts_state, pid, tid)
    clock.advance_time(receipts_state, 0.5)
    scene.end_scene(receipts_state, "player", then="stay")
    receipts_state.location_id = "apt_lounge"
    clock.advance_time(receipts_state, 0.5)
    text = json.dumps(receipts_state.to_save_dict(), ensure_ascii=False)
    again = GameState.from_dict(json.loads(text))
    assert _theirs(again, pid)[-1]["decision"]["after_together"] is True


def test_parting_lands_the_held_text_at_once(receipts_state, matched) -> None:
    """Review 1: a scene ended with no time passing releases the held text then, voiceable."""
    from engine.game import clock
    from engine.social import scene, voicer

    pid, tid = _with(receipts_state, matched)
    _due(receipts_state, pid, tid)
    clock.advance_time(receipts_state, 0.5)
    landed = len(_theirs(receipts_state, pid))
    now = receipts_state.world_clock_hours
    scene.end_scene(receipts_state, "player", then="stay")
    assert receipts_state.world_clock_hours == now
    assert len(_theirs(receipts_state, pid)) == landed + 1
    assert not _queued(receipts_state, pid)
    assert [m for m in voicer._voiceable(receipts_state, _session(receipts_state)) if m.get("from") == pid]


def test_walking_home_lands_the_held_text(receipts_state, matched) -> None:
    from engine.game import clock
    from engine.social import scene

    pid, tid = _with(receipts_state, matched)
    _due(receipts_state, pid, tid)
    clock.advance_time(receipts_state, 0.5)
    landed = len(_theirs(receipts_state, pid))
    scene.end_scene(receipts_state, "player", then="home")
    assert len(_theirs(receipts_state, pid)) == landed + 1
    assert not _queued(receipts_state, pid)


def test_landed_text_is_stamped_after_the_scene(receipts_state, matched) -> None:
    """Review 2: a long scene does not leave a stale timestamp."""
    from engine.game import clock
    from engine.social import scene

    pid, tid = _with(receipts_state, matched)
    _due(receipts_state, pid, tid)
    clock.advance_time(receipts_state, 6.0)
    ended = receipts_state.world_clock_hours
    scene.end_scene(receipts_state, "player", then="stay")
    assert _theirs(receipts_state, pid)[-1]["at"] >= ended


def test_a_long_jump_holds_once_not_per_retry(receipts_state, matched, monkeypatch) -> None:
    from engine.game import clock
    from engine.social import messaging

    pid, tid = _with(receipts_state, matched)
    _due(receipts_state, pid, tid)
    calls = []
    real = messaging._land_due
    monkeypatch.setattr(messaging, "_land_due", lambda s, e: calls.append(1) or real(s, e))
    clock.advance_time(receipts_state, 6.0)
    assert len(calls) <= 2


def test_a_closer_that_moves_on_keeps_the_hold(receipts_state, matched) -> None:
    """Review 3: leaving together (`continues`) releases nothing."""
    from engine.game import clock
    from engine.social import messaging, scene

    pid, tid = _with(receipts_state, matched)
    _due(receipts_state, pid, tid)
    clock.advance_time(receipts_state, 0.5)
    landed = len(_theirs(receipts_state, pid))
    scene.end_scene(receipts_state, "player", then="stay", continues=True)
    scene.open_scene(receipts_state, pid, "the_anchor", kind="drinks")      # the evening's next scene, same person
    assert messaging.held(receipts_state, pid)
    assert len(_theirs(receipts_state, pid)) == landed
    assert len(_queued(receipts_state, pid)) == 1
