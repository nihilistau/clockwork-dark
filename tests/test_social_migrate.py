"""
READ RECEIPTS: a v0.22.0 save's phone slice upgraded to v0.23.0 at load (spec §16; v0.23.0 T20).

The fixture (tests/fixtures/social/v022_save, its README says how) was RECORDED by v0.22.0's own code at
60215f4: 10 in-game days, an agreed meet-up, an unanswered player message, a queued `daily`, the location
`home`, and the run's `phone_archive.jsonl`.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from tests.social_fixtures import receipts_active  # noqa: F401

FIXTURE = Path(__file__).parent / "fixtures" / "social" / "v022_save"
FILES = ("save.json", "memory.json", "phone_archive.jsonl")


@pytest.fixture
def v022_store(receipts_active, tmp_path, monkeypatch):
    """A SaveStore over a temp folder holding the recorded save (CLOCKWORK_DATA_DIR in tmp_path)."""
    from engine.persistence.saves import SaveStore

    monkeypatch.setenv("CLOCKWORK_DATA_DIR", str(tmp_path))
    store = SaveStore(tmp_path / "saves", slug="read-receipts")
    target = tmp_path / "saves" / "v022"
    target.mkdir(parents=True)
    for name in FILES:
        shutil.copy(FIXTURE / name, target / name)
    return store


def _raw_social() -> dict:
    return json.loads((FIXTURE / "save.json").read_text(encoding="utf-8"))["state"]["social"]


def _rewrite(store, edit) -> None:
    """Edit the temp copy of the recorded save's envelope in place (``edit(envelope)``)."""
    path = Path(store.path_for("v022")) / "save.json"
    envelope = json.loads(path.read_text(encoding="utf-8"))
    edit(envelope)
    path.write_text(json.dumps(envelope), encoding="utf-8")


def test_the_fixture_is_a_v022_save_as_recorded() -> None:
    """What the tests below rely on is in the recording (spec §16.3), under 200 KB with its archive."""
    social = _raw_social()
    raw = json.loads((FIXTURE / "save.json").read_text(encoding="utf-8"))["state"]
    assert "schema" not in social and raw["location_id"] == "home"
    assert {"daily", "read", "meet_start"} <= {e["kind"] for e in social["queue"]}
    assert [m for m in social["meets"].values() if m["status"] == "agreed"]
    assert "auto_wait" in social["settings"]
    assert sum((FIXTURE / name).stat().st_size for name in FILES) < 200 * 1024


def test_saveStore_load_upgrades_to_schema_2(v022_store) -> None:
    state, _ = v022_store.load("v022")
    assert state.social["schema"] == 2 and state.location_id == "apt_lounge"
    assert all(not t.get("summary") and "summary_through" not in t for t in state.social["threads"].values())
    assert "meets" not in state.social and "auto_wait" not in state.social["settings"]
    assert "meet" not in state.social["counters"]
    assert state.social["phone_up"] is True
    for key in ("promises", "plans", "scene", "household", "at_work"):
        assert key in state.social


def test_v022_home_maps_to_apt_lounge(v022_store) -> None:
    """The flip of T10's alias (spec §24): the migration, not a loader alias, maps it."""
    from engine.social import places

    assert not hasattr(places, "LOCATION_ALIASES")
    state, _ = v022_store.load("v022")
    assert state.location_id == "apt_lounge"


def test_every_table_row_is_applied(v022_store) -> None:
    from engine.social import memory, migrate

    raw = _raw_social()
    state, _ = v022_store.load("v022")
    s = state.social
    for pid, person in raw["people"].items():
        if not person.get("stage"):
            continue
        row = s["people"][pid]
        assert row["growth"]["depth"] == migrate.DEPTH_FROM_STAGE.get(person["stage"], 0)
        assert row["growth"]["openness"] == 0.0 and row["growth"]["peak_depth"] == row["growth"]["depth"]
        assert row["episode"] is None and "attrs" in row
        for key in migrate.DROPPED_PERSON_KEYS:
            assert key not in row
        assert "social.meet" not in (row.get("rng_n") or {})
        for moved in memory.MOVED:                       # v0.22's top-level rows now under memory
            assert moved not in row
            assert memory.part(row, moved) == (person.get(moved) or [])
    kinds = {e["kind"] for e in s["queue"]}
    assert "meet_start" not in kinds and "daily" in kinds
    assert not [e for e in s["queue"] if (e.get("decision") or {}).get("situation") in migrate.RETIRED_SITUATIONS]
    assert not [e for e in s["queue"] if "meet_id" in (e.get("decision") or {})]
    assert [p for p in s["plans"].values() if p["when"] == "soon"]                # the planned meet


def test_the_story_and_bridge_come_from_the_threads(v022_store) -> None:
    """§16.2: thread summaries joined (oldest thread first, capped) into the story; the bridge is the
    last voiced bubbles of the person's newest thread. Planted summaries, so a summary is there to join."""
    from engine.social import memory

    raw = _raw_social()
    tid, pid = next((t, row["pid"]) for t, row in sorted(raw["threads"].items())
                    if any(m.get("voiced") is True and m["from"] == row["pid"] for m in row["messages"]))

    def plant(envelope):
        envelope["state"]["social"]["threads"][tid]["summary"] = "They met over a dog photo."

    _rewrite(v022_store, plant)
    state, _ = v022_store.load("v022")
    row = state.social["people"][pid]
    assert memory.part(row, "story") == "They met over a dog photo."
    bridge = memory.part(row, "bridge")
    assert bridge and sum(len(m["bubbles"]) for m in bridge) <= 6
    newest = raw["threads"][tid]["messages"]
    spoken = [m for m in newest if m["from"] in ("player", pid) and m.get("voiced") is True and m["bubbles"]]
    assert memory.full_message(bridge[-1], pid)["id"] == spoken[-1]["id"]


def test_the_unanswered_message_is_answered(v022_store) -> None:
    """Pre-flight F16: the read's episode-start draws are forced (`_replies_forced`: no ghost, always a
    reply, always available), so `left_on_read` can never decide this by seed."""
    from engine.game import clock
    from tests.social_fixtures import _replies_forced

    state, _ = v022_store.load("v022")
    reads = [e for e in state.social["queue"] if e["kind"] == "read"]
    assert reads
    with _replies_forced():
        clock.advance_time(state, 24)
    pid, tid = reads[0]["pid"], reads[0]["thread_id"]
    msgs = state.social["threads"][tid]["messages"]
    assert msgs[-1]["from"] != "player" or state.social["people"][pid].get("ghosted")


def test_migration_queues_no_read_for_a_person_who_left(v022_store) -> None:
    """(Review Focus 3) an unanswered thread whose person ended gets no read."""
    state, _ = v022_store.load("v022")
    pid = next(e["pid"] for e in state.social["queue"] if e["kind"] == "read")   # the control: read when live

    def end(envelope):
        envelope["state"]["social"]["people"][pid]["stage"] = "ended"

    _rewrite(v022_store, end)
    state, _ = v022_store.load("v022")
    assert not [e for e in state.social["queue"] if e["kind"] == "read" and e["pid"] == pid]


def test_a_reply_already_on_its_way_gets_no_second_read(v022_store) -> None:
    """A v0.22 `reply` still queued is kept (§16.2's "other due"), so its person is not read again."""
    raw = _raw_social()
    replies = [e for e in raw["queue"] if e["kind"] == "reply"]
    assert replies, "the recording queued a reply"
    state, _ = v022_store.load("v022")
    for event in replies:
        assert [e for e in state.social["queue"] if e["kind"] == "reply" and e["seq"] == event["seq"]]
        assert not [e for e in state.social["queue"] if e["kind"] == "read" and e["pid"] == event["pid"]]


def test_a_pending_recap_card_is_dropped(v022_store) -> None:
    """T19 removed v0.22's meet-up recap card; a save may still hold one never voiced (a system message of
    `kind: recap`). The migration drops it with `meets`, and the done meet-up counts as a scene."""
    raw = _raw_social()
    tid = next(t for t, row in sorted(raw["threads"].items()) if row["messages"])
    pid = raw["threads"][tid]["pid"]
    card_id = "m9999"

    def plant(envelope):
        social = envelope["state"]["social"]
        at = social["threads"][tid]["messages"][-1]["at"]
        social["threads"][tid]["messages"].append({
            "id": card_id, "thread_id": tid, "from": "system", "kind": "recap", "at": at, "bubbles": [],
            "voiced": False, "decision": {"situation": "recap", "kind": "recap", "max_bubbles": 1, "media_kind": "",
                                          "subject": "", "reveal": "", "request_id": "", "game_id": "",
                                          "meet_id": "t9"},
            "media_id": None, "read_at": None, "transcript": None})
        social["meets"]["t9"] = {"id": "t9", "pid": pid, "venue": "the_anchor", "day": 3, "slot": "evening",
                                 "start": 67.0, "end": 69.0, "hours": 2.0, "status": "done", "by": "player",
                                 "agreed_at": 40.0, "flake": False, "band": "good", "ended_at": 69.0}

    _rewrite(v022_store, plant)
    state, _ = v022_store.load("v022")
    ids = {m["id"] for t in state.social["threads"].values() for m in t["messages"]}
    assert card_id not in ids
    assert not [m for t in state.social["threads"].values() for m in t["messages"] if m["kind"] == "recap"]
    assert state.social["people"][pid]["scenes_done"] == 1


def test_a_pending_meet_ask_becomes_a_soon_plan_ask(v022_store) -> None:
    """§16.2: a pending `meet` request keeps its venue and kind as words, `when: soon`, and loses its slot."""
    raw = _raw_social()
    pid = next(t["pid"] for t in raw["threads"].values())

    def plant(envelope):
        envelope["state"]["social"]["requests"]["r99"] = {
            "id": "r99", "pid": pid, "from": "them", "what": "meet", "status": "pending", "at": 200.0,
            "thread_id": "", "mult": 1.0, "asks": 1, "venue": "copper_kettle", "day": 14, "slot": "morning"}

    _rewrite(v022_store, plant)
    state, _ = v022_store.load("v022")
    row = state.social["requests"]["r99"]
    assert (row["when"], row["kind"], row["venue"]) == ("soon", "coffee", "copper_kettle")
    assert "day" not in row and "slot" not in row


def test_a_fault_mid_upgrade_refuses_the_save_and_never_marks_it_done(v022_store, monkeypatch) -> None:
    """Pre-flight F6: a fault after the first write is a MigrationError, the load refuses the save, and the
    slice is NOT at schema 2 (so it is never mistaken for a finished upgrade)."""
    from engine.game.state import GameState
    from engine.persistence.migrations import MigrationError, migrate as engine_migrate
    from engine.social import migrate, plans

    def boom(*a, **k):
        raise RuntimeError("forced fault after the first write")

    monkeypatch.setattr(plans, "make", boom)
    with pytest.raises(MigrationError):
        v022_store.load("v022")
    raw = json.loads((FIXTURE / "save.json").read_text(encoding="utf-8"))["state"]
    state = GameState.from_dict(engine_migrate(dict(raw), slug="read-receipts"))   # SaveStore.load's pre-step
    with pytest.raises(MigrationError):
        migrate.upgrade(state)
    assert state.social.get("schema") != 2
    assert state.social.get("phone_up") is True          # the first write had landed: the fault came after it


def test_an_unknown_schema_is_refused(v022_store) -> None:
    from engine.persistence.migrations import MigrationError

    _rewrite(v022_store, lambda envelope: envelope["state"]["social"].__setitem__("schema", 3))
    with pytest.raises(MigrationError):
        v022_store.load("v022")


def test_the_upgrade_is_idempotent(v022_store) -> None:
    from engine.social import migrate

    state, _ = v022_store.load("v022")
    before = json.dumps(state.to_save_dict(), sort_keys=True, default=str)
    assert migrate.upgrade(state) is False
    assert json.dumps(state.to_save_dict(), sort_keys=True, default=str) == before


class _FixedTime:
    """The saves module's `time`, its wall clock fixed (an envelope's `updated_at`), the rest real."""

    def __init__(self, real) -> None:
        self._real = real

    def time(self) -> float:
        return 1_800_000_000.0

    def __getattr__(self, name):
        return getattr(self._real, name)


def test_save_load_save_round_trips_byte_for_byte(v022_store, monkeypatch) -> None:
    """The migrated (unpacked) slice packs on save, unpacks on load, and packs to the same bytes again
    (engine/social/packing.py); the second load is a no-op upgrade."""
    from engine.persistence import saves as saves_mod
    from engine.social import migrate

    monkeypatch.setattr(saves_mod, "time", _FixedTime(saves_mod.time))
    path = Path(v022_store.path_for("v022")) / "save.json"
    state, mem = v022_store.load("v022")
    v022_store.save(state, save_id="v022", memory=mem)
    first = path.read_bytes()
    again, mem2 = v022_store.load("v022")
    assert again.social["schema"] == 2 and migrate.upgrade(again) is False
    v022_store.save(again, save_id="v022", memory=mem2)
    assert path.read_bytes() == first


def test_the_archive_is_neither_lost_nor_duplicated(v022_store) -> None:
    """The migration touches no file: the archive keeps its rows, byte for byte, and no row it holds comes
    back into state (a page shows each message once)."""
    from engine.social import archive

    directory = Path(v022_store.path_for("v022"))
    before = (directory / archive.ARCHIVE_FILE).read_bytes()
    filed = {(json.loads(line).get("thread_id"), json.loads(line).get("id"))
             for line in before.decode("utf-8").splitlines() if line.strip()}
    assert filed
    state, mem = v022_store.load("v022")
    v022_store.save(state, save_id="v022", memory=mem)
    assert (directory / archive.ARCHIVE_FILE).read_bytes() == before
    in_state = {(tid, m["id"]) for tid, t in state.social["threads"].items() for m in t["messages"]}
    assert not filed & in_state
    for tid in {t for t, _ in filed if t}:
        page = archive.page(directory, state, tid, "", 500)
        ids = [m["id"] for m in page["messages"]]
        assert len(ids) == len(set(ids))


def test_the_build_guard_fails_a_schema_1_state(receipts_active) -> None:
    from engine.game import procgen
    from engine.session.store import SessionStore

    state = procgen.new_game_state(player_name="Sam", seed=3)
    state.social["schema"] = 1
    with pytest.raises(RuntimeError, match="schema-1 slice reached _build"):
        SessionStore()._build(state)


@pytest.mark.parametrize("route", ["local_resume", "hosted_resume", "save_store_direct"])
def test_each_route_upgrades_before_the_first_payload(route, v022_store, monkeypatch, tmp_path) -> None:
    """§16.3 step 1: `payload.phone_block` spied; each route sees schema 2 before its first call."""
    from engine.social import payload
    from tests.social_fixtures import _resume_by

    seen: list[int] = []
    real = payload.phone_block

    def spy(state, *a, **k):
        seen.append(int(state.social.get("schema", 1)))
        return real(state, *a, **k)

    monkeypatch.setattr(payload, "phone_block", spy)
    out = _resume_by(route, v022_store, "v022", tmp_path)
    assert seen and set(seen) == {2}
    assert (out.get("state") or out).get("phone") is not None or route == "local_resume"


def test_after_migration_a_send_a_reply_and_a_plan_work(v022_store) -> None:
    from engine.game import clock
    from engine.social import plans
    from tests.social_fixtures import _act, _replies_forced, _voice_all
    from tests.social_stub import StubVoice

    state, _ = v022_store.load("v022")
    s = state.social
    planned = [p for p in s["plans"].values() if p["when"] == "soon"]
    assert planned and plans.open_for(state, planned[0]["pid"])
    tid = next(t for t, row in sorted(s["threads"].items())
               if row["app"] in ("matchstick", "front_porch", "texts", "natter")
               and not s["people"][row["pid"]].get("ghosted") and s["people"][row["pid"]].get("stage") == "talking")
    pid = s["threads"][tid]["pid"]
    with _replies_forced():
        assert _act(state, "send", target=tid, args={"kind": "text"}, text="still on for that drink?")["success"]
        clock.advance_time(state, 2)
    _voice_all(state, StubVoice("zero"))
    msgs = s["threads"][tid]["messages"]
    sent = max(i for i, m in enumerate(msgs) if m["from"] == "player")
    assert [m for m in msgs[sent + 1:] if m["from"] == pid and m["voiced"] is True]



def test_a_migrated_soon_plan_keeps_without_arrival_fields_and_upgrades_with_them(v022_store, monkeypatch) -> None:
    """v0.23.0 T23C: a v0.22 agreed meet migrates as a `soon` plan, which carries no `due_at` / `arrives_at` /
    `arrived` (a `soon` plan names no time). It still works: `arrive` and `meet_if_here` pass it by, and an
    upgrade to `now` gives it its arrival (from the upgrade's own `at`) and its `plan_arrive`."""
    from engine.game.effects import apply_effect
    from engine.social import plans

    state, _ = v022_store.load("v022")
    row = next(p for p in state.social["plans"].values() if p["when"] == "soon" and p["status"] == "open")
    assert not {"due_at", "arrives_at", "arrived"} & set(row)
    state.location_id = plans.place_of(state, row) or state.location_id
    state.social["phone_up"] = False
    assert plans.arrive(state, state.location_id) == {"quiet": True}
    assert plans.meet_if_here(state) == {"quiet": True}
    monkeypatch.setattr(plans, "_flake_drawn", lambda s, p: False)
    at = state.world_clock_hours
    assert apply_effect(state, {"type": "social_plan", "op": "upgrade", "plan_id": row["id"], "when": "now",
                                "at": at})["ok"]
    assert row["due_at"] == round(at, 4) and row["arrives_at"] >= row["due_at"] and row["arrived"] is False
    assert [e for e in state.social["queue"] if e["kind"] == "plan_arrive" and e.get("plan_id") == row["id"]]

# -- fix round 1: the table's rows the recording does not reach, planted onto it ---------------------------------

STAGED = ("numbers", "meeting", "dating", "friends", "fling", "exclusive")
DECISION = {"situation": "reply", "kind": "text", "max_bubbles": 2, "media_kind": "", "subject": "", "reveal": "",
            "request_id": "", "game_id": "", "meet_id": "t3"}


def _talking(raw: dict, n: int) -> list[str]:
    """`n` people at `talking` in the recording that have a thread, in id order."""
    with_thread = {t["pid"] for t in raw["threads"].values()}
    pids = [p for p, r in sorted(raw["people"].items()) if r.get("stage") == "talking" and p in with_thread]
    assert len(pids) >= n
    return pids[:n]


@pytest.mark.parametrize("stage", STAGED)
def test_each_past_talking_stage_maps_to_its_depth(stage, v022_store) -> None:
    """Section 16.2: numbers/meeting 1, dating/friends/fling 2, exclusive 3: a row of the table each
    (removing its line fails its own case); `knows` and `told` move under `memory` with it."""
    from engine.social import memory

    pid = _talking(_raw_social(), 1)[0]

    def plant(envelope):
        row = envelope["state"]["social"]["people"][pid]
        row["stage"] = stage
        row["knows"] = ["knows-" + pid]
        row["told"] = ["told-" + pid]

    _rewrite(v022_store, plant)
    state, _ = v022_store.load("v022")
    row = state.social["people"][pid]
    depth = {"numbers": 1, "meeting": 1, "dating": 2, "friends": 2, "fling": 2, "exclusive": 3}[stage]
    assert row["growth"]["depth"] == depth and row["growth"]["peak_depth"] == depth
    assert row["growth"]["openness"] == 0.0
    assert "knows" not in row and "told" not in row
    assert memory.part(row, "knows") == ["knows-" + pid] and memory.part(row, "told") == ["told-" + pid]


def test_an_initiation_of_a_retired_situation_is_dropped_and_another_due_kept_quick(v022_store) -> None:
    pids = _talking(_raw_social(), 3)

    def plant(envelope):
        queue = envelope["state"]["social"]["queue"]
        queue.append({"at": 400.0, "seq": 9001, "pid": pids[0], "kind": "initiate",
                      "decision": {**DECISION, "situation": "good_morning"}})
        queue.append({"at": 401.0, "seq": 9002, "pid": pids[1], "kind": "initiate",
                      "decision": {**DECISION, "situation": "late_night"}})
        queue.append({"at": 402.0, "seq": 9003, "pid": pids[2], "kind": "double_text", "thread_id": "x",
                      "decision": {**DECISION, "situation": "double_text"}})

    _rewrite(v022_store, plant)
    state, _ = v022_store.load("v022")
    seqs = {e["seq"]: e for e in state.social["queue"]}
    assert 9001 not in seqs and 9002 not in seqs
    kept = seqs[9003]
    assert kept["decision"]["mode"] == "quick" and "meet_id" not in kept["decision"]


def test_an_unvoiced_due_message_is_kept_as_a_quick_reply(v022_store) -> None:
    raw = _raw_social()
    pid = _talking(raw, 1)[0]
    tid = next(t for t, row in sorted(raw["threads"].items()) if row["pid"] == pid)

    def plant(envelope):
        thread = envelope["state"]["social"]["threads"][tid]
        thread["messages"].append({
            "id": "m9998", "thread_id": tid, "from": pid, "kind": "text", "at": thread["messages"][-1]["at"],
            "bubbles": [], "voiced": False, "media_id": None, "read_at": None, "transcript": None,
            "decision": dict(DECISION)})

    _rewrite(v022_store, plant)
    state, _ = v022_store.load("v022")
    msg = next(m for m in state.social["threads"][tid]["messages"] if m["id"] == "m9998")
    assert msg["voiced"] is False
    assert msg["decision"]["mode"] == "quick" and "meet_id" not in msg["decision"]


def test_a_voiced_message_decision_is_not_made_quick(v022_store) -> None:
    raw = _raw_social()
    tid = next(t for t, row in sorted(raw["threads"].items()) if row["messages"])

    def plant(envelope):
        msg = envelope["state"]["social"]["threads"][tid]["messages"][0]
        assert msg["voiced"] is True
        msg["decision"] = dict(DECISION)

    _rewrite(v022_store, plant)
    state, _ = v022_store.load("v022")
    decision = state.social["threads"][tid]["messages"][0]["decision"]
    assert "mode" not in decision and "meet_id" not in decision


def test_a_voiced_recap_card_is_kept(v022_store) -> None:
    """Deviation (d): only a recap card never voiced is dropped; one the player read is history."""
    raw = _raw_social()
    tid = next(t for t, row in sorted(raw["threads"].items()) if row["messages"])

    def plant(envelope):
        thread = envelope["state"]["social"]["threads"][tid]
        thread["messages"].append({
            "id": "m9997", "thread_id": tid, "from": "system", "kind": "recap", "at": thread["messages"][-1]["at"],
            "bubbles": ["You had a good evening."], "voiced": True, "decision": None, "media_id": None,
            "read_at": None, "transcript": None})

    _rewrite(v022_store, plant)
    state, _ = v022_store.load("v022")
    assert "m9997" in {m["id"] for m in state.social["threads"][tid]["messages"]}


def test_two_agreed_meets_with_one_person_become_one_plan(v022_store) -> None:
    pid = next(m["pid"] for m in _raw_social()["meets"].values() if m["status"] == "agreed")

    def plant(envelope):
        meets = envelope["state"]["social"]["meets"]
        first = next(m for m in meets.values() if m["status"] == "agreed")
        meets["t88"] = {**first, "id": "t88", "venue": "copper_kettle"}

    _rewrite(v022_store, plant)
    state, _ = v022_store.load("v022")
    soon = [p for p in state.social["plans"].values() if p["pid"] == pid and p["when"] == "soon"]
    assert len(soon) == 1 and state.social["schema"] == 2


def test_a_meet_that_cannot_become_a_plan_is_logged_not_dropped_silently(v022_store, monkeypatch, caplog) -> None:
    from engine.social import plans

    pid = next(m["pid"] for m in _raw_social()["meets"].values() if m["status"] == "agreed")
    monkeypatch.setattr(plans, "make", lambda *a, **k: None)
    with caplog.at_level("WARNING", logger="engine.social.migrate"):
        state, _ = v022_store.load("v022")
    assert state.social["schema"] == 2
    assert [r for r in caplog.records if pid in r.getMessage() and "could not become a plan" in r.getMessage()]


def test_a_newer_schema_whose_unpacking_fails_is_a_migration_error(v022_store, monkeypatch) -> None:
    from engine.persistence.migrations import MigrationError
    from engine.social import packing

    def broken(slice_):
        raise KeyError("a packed form this build does not know")

    _rewrite(v022_store, lambda envelope: envelope["state"]["social"].__setitem__("schema", 3))
    monkeypatch.setattr(packing, "unpack", broken)
    with pytest.raises(MigrationError, match="schema 3"):
        v022_store.load("v022")


def test_the_build_guard_reads_the_current_schema_not_a_literal(receipts_active, monkeypatch) -> None:
    from engine.game import procgen
    from engine.session.store import SessionStore
    from engine.social import kinds

    monkeypatch.setattr(kinds, "SCHEMA", 3)
    state = procgen.new_game_state(player_name="Sam", seed=3)
    state.social["schema"] = 2
    with pytest.raises(RuntimeError, match="schema-2 slice reached _build"):
        SessionStore()._build(state)
