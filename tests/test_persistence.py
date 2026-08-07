"""Save/load, atomic writes and schema migration tests."""

from __future__ import annotations

import json
from dataclasses import asdict

import pytest

from engine.game.clock import set_clock
from engine.game.state import (
    CURRENT_SAVE_VERSION,
    AgentMind,
    GameState,
    InventoryItem,
)
from engine.persistence.atomic import read_json, write_json_atomic
from engine.persistence.migrations import MigrationError, migrate
from engine.persistence.saves import SaveStore


@pytest.fixture()
def store(tmp_path):
    return SaveStore(root=tmp_path / "saves")


def _state() -> GameState:
    state = GameState(
        player_name="Alden",
        location_id="edgewood_square",
        awareness=33.0,
        evil_progress=0.55,
        inventory=[InventoryItem(id="loaf", name="Loaf", qty=3)],
        assistant_mind=AgentMind(trust_level=71.0),
        rng_seed=99,
    )
    set_clock(state, day=12, hour=17)
    state.turn_number = 40
    return state


# -- atomic writes -------------------------------------------------------


def test_atomic_write_and_read(tmp_path):
    target = tmp_path / "a.json"
    write_json_atomic(target, {"x": 1})
    assert read_json(target) == {"x": 1}


def test_atomic_write_leaves_no_temp_files(tmp_path):
    target = tmp_path / "a.json"
    write_json_atomic(target, {"x": 1})
    write_json_atomic(target, {"x": 2})
    assert [p.name for p in tmp_path.iterdir() if p.suffix == ".tmp"] == []


def test_atomic_write_keeps_backup(tmp_path):
    target = tmp_path / "a.json"
    write_json_atomic(target, {"x": 1})
    write_json_atomic(target, {"x": 2})
    assert read_json(target) == {"x": 2}
    assert json.loads((tmp_path / "a.json.bak").read_text()) == {"x": 1}


def test_corrupt_primary_falls_back_to_backup(tmp_path):
    """A truncated save must not cost the run."""
    target = tmp_path / "a.json"
    write_json_atomic(target, {"x": 1})
    write_json_atomic(target, {"x": 2})
    target.write_text("{ this is not json")
    assert read_json(target) == {"x": 1}


def test_failed_write_leaves_original_intact(tmp_path, monkeypatch):
    target = tmp_path / "a.json"
    write_json_atomic(target, {"good": True})

    def boom(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr("engine.persistence.atomic.os.replace", boom)
    with pytest.raises(OSError):
        write_json_atomic(target, {"good": False})

    assert read_json(target) == {"good": True}
    assert [p.name for p in tmp_path.iterdir() if p.suffix == ".tmp"] == []


# -- save / load ---------------------------------------------------------


def test_save_load_round_trip(store):
    original = _state()
    save_id = store.save(original)
    restored, _memory = store.load(save_id)
    assert asdict(restored) == asdict(original)


def test_load_preserves_hidden_and_minds(store):
    save_id = store.save(_state())
    restored, _ = store.load(save_id)
    assert restored.awareness == 33.0
    assert restored.evil_progress == 0.55
    assert restored.assistant_mind.trust_level == 71.0
    assert restored.world_day == 12
    assert restored.world_hour == 17


def test_save_reuses_id(store):
    state = _state()
    first = store.save(state)
    second = store.save(state, save_id=first)
    assert first == second
    assert len(store.list_saves()) == 1


def test_index_summarizes_run(store):
    store.save(_state())
    (summary,) = store.list_saves()
    assert summary.player_name == "Alden"
    assert summary.world_day == 12
    assert summary.evil_phase == "spreading"
    assert summary.turn_number == 40


def test_memory_is_stored_alongside(store):
    save_id = store.save(_state(), memory={"summary": "The oven went cold."})
    _state_out, memory = store.load(save_id)
    assert memory["summary"] == "The oven went cold."


def test_load_missing_save_raises(store):
    with pytest.raises(FileNotFoundError):
        store.load("nope")


def test_delete_removes_save_and_index_row(store):
    save_id = store.save(_state())
    assert store.delete(save_id) is True
    assert store.list_saves() == []
    assert store.exists(save_id) is False


def test_transcript_appends(store):
    save_id = store.save(_state())
    store.append_transcript(save_id, {"turn": 1, "narration": "You wake."})
    store.append_transcript(save_id, {"turn": 2, "narration": "You walk."})
    lines = (store.root / save_id / "transcript.jsonl").read_text().strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[1])["turn"] == 2


# -- migrations ----------------------------------------------------------


def test_v1_folds_day_and_hour_into_one_clock():
    migrated = migrate(
        {"save_version": 1, "world_day": 12, "world_hour": 17, "procgen": {"seed": 5}}
    )
    assert migrated["world_clock_hours"] == 11 * 24 + 17
    assert "world_day" not in migrated
    assert migrated["save_version"] == CURRENT_SAVE_VERSION


def test_v1_seeds_rng_from_procgen():
    migrated = migrate({"save_version": 1, "procgen": {"seed": 4242}})
    assert migrated["rng_seed"] == 4242
    assert migrated["rng_counters"] == {}


def test_v1_backfills_survival_and_attributes():
    migrated = migrate({"save_version": 1, "stats": {"stamina": 80}})
    assert migrated["hunger"] == 0.0
    assert migrated["wounds"] == []
    assert migrated["stats"]["max_stamina"] == 80
    assert migrated["stats"]["grit"] == 10


def test_v1_drops_the_junk_dice_flag():
    migrated = migrate({"save_version": 1, "flags": {"_last_dice": True, "met": True}})
    assert migrated["flags"] == {"met": True}


def test_migrated_v1_document_loads():
    """End to end: a v1 save produces a usable GameState."""
    migrated = migrate(
        {
            "save_version": 1,
            "player_name": "Old Save",
            "world_day": 3,
            "world_hour": 9,
            "evil_progress": 0.25,
            "procgen": {"seed": 7},
        }
    )
    state = GameState.from_dict(migrated)
    assert state.player_name == "Old Save"
    assert state.world_day == 3
    assert state.world_hour == 9
    assert state.evil_phase.value == "stirring"


def test_future_save_is_refused_not_mangled():
    with pytest.raises(MigrationError):
        migrate({"save_version": CURRENT_SAVE_VERSION + 5})


def test_current_version_is_a_noop():
    doc = {"save_version": CURRENT_SAVE_VERSION, "player_name": "X"}
    assert migrate(doc)["player_name"] == "X"


def test_migration_does_not_mutate_input():
    original = {"save_version": 1, "world_day": 4, "world_hour": 2}
    migrate(original)
    assert original["world_day"] == 4, "load must not rewrite the caller's dict"
