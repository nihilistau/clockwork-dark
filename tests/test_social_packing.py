"""The phone's save, packed and bounded (v0.23.0 T9 fix round 2; spec §7.1, §17.2, R8).

A phone save leaves out what it can put back exactly (`engine/social/packing.py`): each message's
decision keeps only its non-default fields, each message's `thread_id` (its thread's own key) is
dropped, and each media row keeps only its non-default fields. Loading restores every row to the
byte, key order included. And state keeps only the conversation going on in a thread (an open
episode's messages), what the player has not read yet, and one screen of the thread the player has
open; a closed conversation's messages live in `phone_archive.jsonl`, behind the thread's stamp
(`archive.spill`), and the open thread's screen is filled from the archive when state holds less.
"""

from __future__ import annotations

import copy
import dataclasses
import json
import sys
from typing import Any
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests.social_fixtures import (  # noqa: E402,F401
    _live_session, _matched_in, _phone, _with, matched, receipts_active, receipts_state,
)


def _played(sessions: int = 2):
    """A harness phone (in memory) after a few sessions: messages with decisions, media, people."""
    import scripts.simulate_social as sim

    with sim._quiet_summaries():
        phone = sim.Phone(3, "romantic_model")
        player = sim.POLICIES["attentive"](phone, 3)
        for _ in range(sessions):
            sim.Session(phone, player, model_seconds=15).play()
    return phone


def test_a_phone_save_round_trips_byte_for_byte_and_is_smaller(receipts_active) -> None:
    from engine.game.state import GameState
    from engine.social.kinds import Decision

    from engine.social import media, messaging

    phone = _played()
    try:
        state = phone.state
        tid, thread = next((k, t) for k, t in state.social["threads"].items() if t["messages"])
        photo = messaging.new_message(state, tid, thread["pid"], "photo", bubbles=["look"], voiced=True)
        media.mark_procedural(state, media.attach(state, thread["pid"], tid, photo["id"], "photo", "selfie_now"))
        full = json.dumps(state.social, ensure_ascii=False)
        saved = state.to_save_dict()
        text = json.dumps(saved, ensure_ascii=False)
        loaded = GameState.from_dict(json.loads(text))
        assert json.dumps(loaded.to_save_dict(), ensure_ascii=False) == text       # save, load, save: the same bytes
        assert json.dumps(loaded.social, ensure_ascii=False) == full              # every row as it was, key order too
        packed = json.dumps(saved["social"], ensure_ascii=False)
        assert len(packed) < len(full)
        decisions = [m["decision"] for t in saved["social"]["threads"].values() for m in t["messages"]
                     if isinstance(m.get("decision"), dict)]
        assert decisions and all(len(d) < len(dataclasses.fields(Decision)) for d in decisions)
        assert not any("thread_id" in m for t in saved["social"]["threads"].values() for m in t["messages"])
        assert any(r.get("_p") == 1 for r in saved["social"]["media"].values()), "no media row packed"
    finally:
        phone.close()


def test_an_unusual_row_is_saved_as_it_is(receipts_active) -> None:
    """Only a row of the exact shape the engine writes is packed: one with a missing or extra key, or a
    message whose `thread_id` is another thread's, goes through untouched and loads the same."""
    from engine.game.state import GameState

    phone = _played(1)
    try:
        state = phone.state
        tid, thread = next((k, t) for k, t in state.social["threads"].items() if t["messages"])
        odd = copy.deepcopy(thread["messages"][-1])
        odd["id"] = "m999999"
        odd["thread_id"] = "elsewhere:p0000"
        odd["decision"] = {"situation": "reply", "extra": 1}
        thread["messages"].append(odd)
        bare = {k: v for k, v in copy.deepcopy(thread["messages"][-2]).items() if k != "thread_id"}
        bare["id"] = "m999998"                        # a message that never had a `thread_id` is never given one
        thread["messages"].append(bare)
        media = next(iter(state.social["media"].values()), None)
        if media is not None:
            media["zz_extra"] = "kept"
        text = json.dumps(state.to_save_dict(), ensure_ascii=False)
        loaded = GameState.from_dict(json.loads(text))
        assert json.dumps(loaded.social, ensure_ascii=False) == json.dumps(state.social, ensure_ascii=False)
        assert loaded.social["threads"][tid]["messages"][-2] == odd
        assert loaded.social["threads"][tid]["messages"][-1] == bare
        assert "thread_id" not in loaded.social["threads"][tid]["messages"][-1]
    finally:
        phone.close()


def test_a_closed_conversation_spills_to_its_stamp_and_the_open_thread_keeps_a_screen(
        receipts_active, monkeypatch) -> None:
    """A thread with no conversation going and nothing unread keeps `social.closed_thread_tail` (0) messages
    in state beyond its last turn (`archive.keep_for`) -- the rest in the archive -- while the thread the
    player has open keeps `social.state_messages` (one screen), and its section shows a screen from the
    archive when state holds less."""
    from engine.social import archive, messaging, payload, saves

    monkeypatch.setattr(messaging.convo, "on_player_send", lambda *a, **k: None)    # no conversation opens
    scene, session = _live_session()
    state = session.engine.state
    closed = _matched_in(session, "matchstick")
    opened = _matched_in(session, "front_porch")
    from engine.social import voicer
    from tests.social_stub import StubVoice

    voicer.run_until_quiet(session, StubVoice("zero"))                          # their openers written
    for tid in (closed, opened):
        _phone(scene, session, "open_thread", target=tid)                       # and read
        for i in range(14):
            _phone(scene, session, "send", target=tid, args={"kind": "text"}, text=f"{tid[:4]} {i}")
    _phone(scene, session, "open_thread", target=opened)
    from engine import social

    screen = int(social.setting("state_messages", 8))
    assert int(social.setting("closed_thread_tail", -1)) == 0
    with session.lock:
        saves.save_now(session)
    threads = state.social["threads"]
    # The closed thread keeps only its last turn (the player's run, as far as a reply reads it).
    assert len(threads[closed]["messages"]) == archive.BURST_READ and threads[closed]["archived"] >= 14 - 3
    assert messaging.last_shown(threads[closed])["bubbles"][0].endswith("13")
    assert len(threads[opened]["messages"]) == screen
    # Another thread opened: its screen comes from the archive.
    _phone(scene, session, "open_thread", target=closed)
    with session.lock:
        with payload.building(session, {}):
            section = state.to_client_dict()["phone"]["open_thread"]
    assert [m["bubbles"][0] for m in section["messages"]][-1].endswith("13")
    assert len(section["messages"]) == screen and section["more"] is True
    page = archive.page(session.saves.path_for(session.save_id), state, closed, before="", limit=50)
    assert len(page["messages"]) >= 14                                         # every shown one, paged back


def test_a_conversation_going_on_keeps_its_messages(receipts_state, matched, monkeypatch) -> None:
    """An open episode's messages stay in state whatever the tail (`archive.keep_for`), and so do the
    messages the player has not read yet; with neither, the last turn the conversation's reads count."""
    from engine import social
    from engine.game import clock
    from engine.social import archive, messaging
    from tests.social_fixtures import _open_episode

    monkeypatch.setattr(social, "setting", _with(social.setting, closed_thread_tail=0))
    thread = matched("matchstick")
    pid = thread.split(":")[1]
    for i in range(6):
        messaging.new_message(receipts_state, thread, "player", "text", bubbles=[f"before {i}"])
        clock.advance_time(receipts_state, 1.0)
    t = receipts_state.social["threads"][thread]
    assert archive.keep_for(receipts_state, t) == archive.BURST_READ    # nothing going or unread: the last turn
    _open_episode(receipts_state, pid, thread)
    for i in range(4):
        messaging.new_message(receipts_state, thread, "player", "text", bubbles=[f"during {i}"],
                              at=receipts_state.world_clock_hours)
    assert archive.keep_for(receipts_state, t) == 4
    theirs = messaging.new_message(receipts_state, thread, pid, "text", bubbles=["unread"],
                                   at=receipts_state.world_clock_hours - 5.5)
    t["messages"].sort(key=lambda m: float(m["at"]))
    assert theirs["read_at"] is None
    assert archive.keep_for(receipts_state, t) == len(t["messages"]) - t["messages"].index(theirs)


def test_a_failed_archive_write_leaves_every_message_in_state(receipts_active, monkeypatch) -> None:
    """Review M2: the spill appends to the archive FIRST; when that fails (a full disk, a locked file) nothing
    is trimmed -- every message stays in state, and the next save tries again."""
    from engine import social
    from engine.social import archive, messaging, saves

    monkeypatch.setattr(messaging.convo, "on_player_send", lambda *a, **k: None)
    _scene, session = _live_session()
    state = session.engine.state
    thread = _matched_in(session, "matchstick")
    with session.lock:
        for i in range(12):
            messaging.new_message(state, thread, "player", "text", bubbles=[f"line {i}"])
    before = json.dumps(state.social["threads"][thread]["messages"], sort_keys=True)
    assert int(social.setting("closed_thread_tail", -1)) == 0
    with monkeypatch.context() as patch:
        patch.setattr(archive, "append", lambda *a, **k: False)
        with session.lock:
            assert archive.spill(session) == 0
            saves.save_now(session)                            # the phone's whole save path, too
    assert json.dumps(state.social["threads"][thread]["messages"], sort_keys=True) == before
    assert not state.social["threads"][thread].get("archived")
    with session.lock:
        assert archive.spill(session) > 0                      # the next save's try moves them


def test_the_voices_input_is_the_same_before_and_after_a_save(receipts_active, monkeypatch) -> None:
    """Review M4: a save spills a thread's older messages out of state, and the voice's verbatim tail used to
    shrink with it, so two identical runs with a save at different moments built different prompts. The tail
    is now read through the archive when state is short: the snapshot is equal before and after a spill."""
    from engine.social import archive, messaging, voicing

    monkeypatch.setattr(messaging.convo, "on_player_send", lambda *a, **k: None)
    _scene, session = _live_session()
    state = session.engine.state
    thread = _matched_in(session, "matchstick")
    pid = state.social["threads"][thread]["pid"]
    from engine.game import clock

    with session.lock:
        for i in range(10):
            sender = "player" if i % 2 == 0 else pid
            row = messaging.new_message(state, thread, sender, "text", bubbles=[f"word {i}"],
                                        decision={"situation": "reply"} if sender == pid else None)
            row["read_at"] = state.world_clock_hours
            clock.advance_time(state, 0.1)
        messaging.new_message(state, thread, pid, "text", voiced=False, decision={"situation": "reply"})
        directory = archive.save_dir(session)
        before = voicing.snapshot_of(state, thread, directory)
        assert archive.spill(session) > 0
        assert len(state.social["threads"][thread]["messages"]) < 11, "nothing spilled: the check is vacuous"
        after = voicing.snapshot_of(state, thread, directory)
    assert before.tail == after.tail and len(after.tail) >= 10



def test_a_thread_with_nothing_spilled_never_opens_the_archive(receipts_active, monkeypatch) -> None:
    """Review M4 follow-up: the voice's tail reads the archive only for a thread a save has spilled from
    (`thread["archived"]`), never for a new short one -- the file is shared and large."""
    from engine.social import archive, messaging, voicing

    monkeypatch.setattr(messaging.convo, "on_player_send", lambda *a, **k: None)
    _scene, session = _live_session()
    state = session.engine.state
    thread = _matched_in(session, "matchstick")
    pid = state.social["threads"][thread]["pid"]
    with session.lock:
        messaging.new_message(state, thread, pid, "text", voiced=False, decision={"situation": "reply"})
        directory = archive.save_dir(session)
        calls: list[str] = []
        real = archive.archived_before
        monkeypatch.setattr(archive, "archived_before", lambda *a, **k: calls.append("read") or real(*a, **k))
        assert not state.social["threads"][thread].get("archived")
        assert voicing.snapshot_of(state, thread, directory) is not None
    assert calls == []


def test_the_worlds_fields_round_trip(receipts_state) -> None:
    """v0.23.0 T11: the world's state -- the phone down, at work until an hour, the buzz's mark, "wake me for
    messages", an activity a buzz cut short, the player's place, and a promised message's notification naming its promise -- loads back
    exactly, and save, load, save gives the same bytes."""
    from engine.game.effects import apply_effect
    from engine.game.state import GameState
    from engine.social import messaging

    state = receipts_state
    for field, value in (("phone_up", False), ("at_work", True), ("work_until", 41.5), ("buzz_from", 3),
                         ("wake_for_messages", True), ("resume", {"activity": "sleep", "until": 55.0})):
        assert apply_effect(state, {"type": "social_settings", "field": field, "value": value})["ok"], field
    assert apply_effect(state, {"type": "social_go", "op": "place", "to": "the_anchor"})["ok"]
    messaging.notify(state, "texts", "texts:p0001", "p0001", "text", "New message", promise_id="pr7")
    text = json.dumps(state.to_save_dict(), ensure_ascii=False)
    loaded = GameState.from_dict(json.loads(text))
    assert json.dumps(loaded.to_save_dict(), ensure_ascii=False) == text
    assert json.dumps(loaded.social, ensure_ascii=False) == json.dumps(state.social, ensure_ascii=False)
    assert (loaded.social["phone_up"], loaded.social["at_work"], loaded.social["work_until"],
            loaded.social["buzz_from"], loaded.social["settings"]["wake_for_messages"]) == (False, True, 41.5, 3, True)
    assert loaded.location_id == "the_anchor" and loaded.social["notifications"][-1]["promise_id"] == "pr7"
    assert loaded.social["resume"] == {"activity": "sleep", "until": 55.0}


def test_plans_round_trip_every_status_and_a_plan_decision_packs(receipts_state, matched, monkeypatch) -> None:
    """v0.23.0 T12: plan rows (open and closed, `late`, a home plan with no venue) load back exactly, key order
    included, and save, load, save gives the same bytes; a flake's and a stood-up message's decision carries its
    `plan_id` (packed to its non-default fields like any decision)."""
    from engine.game.effects import apply_effect
    from engine.game.state import GameState
    from engine.social import convo, growth, messaging, plans
    from engine.social.convo import Availability
    from engine.social.kinds import Decision

    real = growth.willing
    monkeypatch.setattr(growth, "willing", lambda s, p, c: (True, "") if c == "meet" else real(s, p, c))
    monkeypatch.setattr(convo, "available", lambda s, p, at: Availability(True))
    monkeypatch.setattr(convo, "boundary_minutes", lambda s, p, at: None)
    monkeypatch.setattr(plans, "_flake_drawn", lambda s, p: False)
    monkeypatch.setattr(plans, "_tonight_span", lambda s, p, at: (at, at + 3.0))
    state = receipts_state
    thread = matched("matchstick")
    pid = thread.split(":", 1)[1]
    rows = []
    for kind, when, venue, end in (("coffee", "now", "copper_kettle", "met"), ("drinks", "tonight", "the_anchor", "stood_up"),
                                   ("their_place", "soon", "", "lapse"), ("walk", "soon", "westcliff_path", "cancel"),
                                   ("film", "tonight", "the_rialto", "")):
        row = plans.make(state, pid, kind=kind, when=when, venue=venue)
        rows.append(row["id"])
        if end:
            apply_effect(state, {"type": "social_plan", "op": end, "plan_id": row["id"]})
    apply_effect(state, {"type": "social_plan", "op": "late", "plan_id": rows[-1]})
    messaging.new_message(state, thread, pid, "text", voiced=False,
                          decision=dataclasses.asdict(Decision(situation="flake", plan_id=rows[0])))
    text = json.dumps(state.to_save_dict(), ensure_ascii=False)
    loaded = GameState.from_dict(json.loads(text))
    assert json.dumps(loaded.to_save_dict(), ensure_ascii=False) == text
    assert json.dumps(loaded.social, ensure_ascii=False) == json.dumps(state.social, ensure_ascii=False)
    assert [loaded.social["plans"][i]["status"] for i in rows] == ["met", "stood_up", "lapsed", "cancelled", "open"]
    assert loaded.social["plans"][rows[-1]]["late"] is True and loaded.social["plans"][rows[2]]["venue"] == ""
    assert loaded.social["threads"][thread]["messages"][-1]["decision"]["plan_id"] == rows[0]
    # v0.23.0 T23C: a `now` / `tonight` row's arrival fields load back as written; a `soon` row has none.
    for i in (rows[0], rows[1], rows[-1]):
        kept = loaded.social["plans"][i]
        assert (kept["due_at"], kept["arrives_at"], kept["arrived"]) == (
            state.social["plans"][i]["due_at"], state.social["plans"][i]["arrives_at"], False)
        assert isinstance(kept["arrives_at"], float) and kept["arrives_at"] >= kept["due_at"]
    assert not {"due_at", "arrives_at", "arrived"} & set(loaded.social["plans"][rows[2]])


def test_plans_stay_bounded_in_a_long_save(receipts_state, matched, monkeypatch) -> None:
    """Closed plans past `closed_kept` a person leave at every save (`plans.forget_closed`, via `saves.compact`),
    so a long game holds a few plan rows a person, never one for every plan ever made."""
    from engine.game.effects import apply_effect
    from engine.social import convo, growth, plans
    from engine.social.convo import Availability

    real = growth.willing
    monkeypatch.setattr(growth, "willing", lambda s, p, c: (True, "") if c == "meet" else real(s, p, c))
    monkeypatch.setattr(convo, "available", lambda s, p, at: Availability(True))
    state = receipts_state
    pid = matched("matchstick").split(":", 1)[1]
    for _ in range(40):
        row = plans.make(state, pid, kind="coffee", when="soon", venue="copper_kettle")
        apply_effect(state, {"type": "social_plan", "op": "cancel", "plan_id": row["id"]})
    assert len(state.social["plans"]) == 40
    assert plans.forget_closed(state) == 37 and len(state.social["plans"]) == 3
    assert len(json.dumps(state.social["plans"])) < 1200                    # a few hundred bytes a row, three rows


def test_an_open_scene_round_trips_and_stays_bounded(receipts_state, matched, monkeypatch) -> None:
    """v0.23.0 T13: an open scene's row (its prior, energy, moments and running sum) loads back exactly, and save,
    load, save gives the same bytes; however long the evening, it keeps at most `social.scene_moments_kept`
    moments (the average reads the running sum, never the whole list)."""
    from engine import social
    from engine.game.state import GameState
    from engine.social import plans, scene, world
    from tests.social_fixtures import _force_stage, _scene_forced

    state = receipts_state
    pid = matched("matchstick").split(":", 1)[1]
    monkeypatch.setattr(scene, "_moment_draw", lambda s, p: 0.0)
    with _scene_forced():
        _force_stage(state, pid, "numbers")
        state.social["phone_up"] = False
        plans.make(state, pid, kind="drinks", when="now", venue="the_anchor")
        state.location_id = "merrow_street"
        world.go(state, "the_anchor")
        for i in range(40):
            if i % 3 == 2:
                scene.close(state, "another_round")
            assert scene.move(state, "quiet")["ok"] and social.scene_open(state), i
    row = state.social["scene"]
    row["stay_asked"] = True                           # T16: a "not tonight" lives on the row
    assert row["count"] == 40 and len(row["moments"]) == int(social.setting("scene_moments_kept", 12))
    text = json.dumps(state.to_save_dict(), ensure_ascii=False)
    loaded = GameState.from_dict(json.loads(text))
    assert json.dumps(loaded.to_save_dict(), ensure_ascii=False) == text
    assert loaded.social["scene"] == row and social.scene_open(loaded)
    assert len(json.dumps(row)) < 2000


def test_life_events_round_trip_and_stay_bounded(receipts_state, matched) -> None:
    """v0.23.0 T17: a person's `life` and the player's `player_life` load back exactly, and save, load, save gives
    the same bytes; at every save the running events and the ones still on cooldown stay, with the newest
    `life_events.yaml` `kept.past` besides (`life.forget_past`), so a long game never holds every event ever drawn."""
    from engine import social
    from engine.game.effects import apply_effect
    from engine.game.state import GameState
    from engine.social import life

    state = receipts_state
    pid = matched("matchstick").split(":", 1)[1]
    keep = social.data("life_events")["kept"]["past"]
    for day in range(40):                                          # forty parcels and forty pets, a day apart
        for who, event in (("player", "parcel"), (pid, "new_pet")):
            apply_effect(state, {"type": "social_life", "op": "start", "who": who, "id": event, "at": 24.0 * day})
    state.world_clock_hours = 24.0 * 41 + 24.0 * 200                # every cooldown is long over; none is running
    assert len(state.social["player_life"]) == 40 and len(state.social["people"][pid]["life"]) == 40
    assert life.forget_past(state) == 2 * (40 - keep)
    assert len(state.social["player_life"]) == keep and len(state.social["people"][pid]["life"]) == keep
    assert [e["at"] for e in state.social["player_life"]] == [24.0 * d for d in range(40 - keep, 40)]   # the newest
    apply_effect(state, {"type": "social_life", "op": "start", "who": "player", "id": "boiler",
                         "at": state.world_clock_hours})            # one running: kept whatever the bound
    text = json.dumps(state.to_save_dict(), ensure_ascii=False)
    loaded = GameState.from_dict(json.loads(text))
    assert json.dumps(loaded.to_save_dict(), ensure_ascii=False) == text
    assert json.dumps(loaded.social, ensure_ascii=False) == json.dumps(state.social, ensure_ascii=False)
    assert loaded.social["player_life"] == state.social["player_life"]
    assert loaded.social["people"][pid]["life"] == state.social["people"][pid]["life"]
    assert life.forget_past(loaded) == 0 and len(loaded.social["player_life"]) == keep + 1


def test_a_cooldown_outlives_the_bound(receipts_state, matched) -> None:
    """A past event still within its cooldown is kept past `kept.past`: pruning must not let a once-a-year
    event (the birthday, the job offer) come round again early."""
    from engine import social
    from engine.game.effects import apply_effect
    from engine.social import life

    state = receipts_state
    pid = matched("matchstick").split(":", 1)[1]
    keep = social.data("life_events")["kept"]["past"]
    apply_effect(state, {"type": "social_life", "op": "start", "who": pid, "id": "birthday", "at": 100.0})
    for i in range(keep + 3):
        apply_effect(state, {"type": "social_life", "op": "start", "who": pid, "id": "new_pet", "at": 110.0 + 200.0 * i})
    state.world_clock_hours = 110.0 + 200.0 * (keep + 3) + 5000.0     # the pets' cooldowns are over, a year is not
    assert state.world_clock_hours < 100.0 + 24.0 * 365
    life.forget_past(state)
    ids = [e["id"] for e in state.social["people"][pid]["life"]]
    assert "birthday" in ids and ids.count("new_pet") == keep


def test_the_saves_compaction_prunes_life(receipts_state, matched, monkeypatch) -> None:
    from engine.social import life, saves

    calls: list[Any] = []
    monkeypatch.setattr(life, "forget_past", lambda state: calls.append(state) or 0)
    scene, session = _live_session()
    saves.compact(session)
    assert calls == [session.engine.state]


def test_the_household_and_the_long_term_dates_round_trip(receipts_state, matched) -> None:
    """v0.23.0 T18: the household (`state.social["household"]`, the partner's pid), `exclusive_since` and
    `engaged_since` load back exactly, and save, load, save gives the same bytes."""
    from engine.game.effects import apply_effect
    from engine.game.state import GameState

    state = receipts_state
    pid = matched("matchstick").split(":", 1)[1]
    for stage in ("exclusive", "engaged"):
        assert apply_effect(state, {"type": "social_stage", "pid": pid, "stage": stage, "at": 100.25})["ok"]
    assert apply_effect(state, {"type": "social_household", "op": "move_in", "pid": pid})["ok"]
    text = json.dumps(state.to_save_dict(), ensure_ascii=False)
    loaded = GameState.from_dict(json.loads(text))
    assert json.dumps(loaded.to_save_dict(), ensure_ascii=False) == text
    assert json.dumps(loaded.social, ensure_ascii=False) == json.dumps(state.social, ensure_ascii=False)
    person = loaded.social["people"][pid]
    assert (loaded.social["household"], person["exclusive_since"], person["engaged_since"]) == (pid, 100.25, 100.25)
