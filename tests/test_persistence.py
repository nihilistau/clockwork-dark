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


def test_concurrent_saves_do_not_lose_entries_from_the_index(tmp_path):
    """
    Two sessions autosaving at once both stay in the load menu.

    The index was read-modify-written with no lock, on a PROCESS-WIDE singleton
    shared by every session under threading-mode Socket.IO. Session B loaded the
    index before A wrote it, so B's write dropped A's row: A's `save.json`
    survived on disk and the run disappeared from `list_saves()` -- the only
    place a player can see it -- permanently.
    """
    import threading

    from engine.game.state import GameState
    from engine.persistence.saves import SaveStore

    store = SaveStore(root=tmp_path / "saves", slug="clockwork-dark")
    ids = [f"run{n:02d}" for n in range(24)]
    barrier = threading.Barrier(len(ids))
    errors: list[BaseException] = []

    def _save(save_id: str) -> None:
        try:
            barrier.wait(timeout=10)
            store.save(GameState(location_id="forest_clearing"), save_id=save_id)
        except BaseException as exc:  # noqa: BLE001 -- reported below
            errors.append(exc)

    threads = [threading.Thread(target=_save, args=(i,)) for i in ids]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)

    assert not errors, f"a concurrent save raised: {errors[0]!r}"
    listed = {s.save_id for s in store.list_saves()}
    missing = set(ids) - listed
    assert not missing, f"{len(missing)} concurrent saves were lost from the index"


def test_the_index_is_bounded_and_never_drops_a_manual_slot(tmp_path, monkeypatch):
    """
    Autosaves are pruned oldest-first; a named slot is not prunable at all.

    The index is re-parsed and fsynced every turn and grew by one row per run
    ever started, with nothing that ever removed one -- a working checkout
    measured 537 KB across 1302 entries. But the index IS the load menu, so a
    bound that could drop a save the player deliberately named would delete
    their run from the only place they can see it.
    """
    from engine.game.state import GameState
    from engine.persistence.saves import AUTOSAVE_SLOT, SaveStore

    monkeypatch.setattr(
        "engine.persistence.saves.SaveStore._index_limit", lambda self: 10
    )
    store = SaveStore(root=tmp_path / "saves", slug="clockwork-dark")
    state = GameState(location_id="forest_clearing")

    store.save(state, save_id="keepsake", slot="chapter-one")
    for n in range(40):
        store.save(state, save_id=f"auto{n:02d}", slot=AUTOSAVE_SLOT)

    listed = store.list_saves()
    assert len(listed) <= 10, f"index is unbounded at {len(listed)} entries"
    assert "keepsake" in {s.save_id for s in listed}, (
        "a manual save slot was pruned -- the player's named run is gone from "
        "the load menu"
    )
    # The survivors are the NEWEST autosaves, not an arbitrary subset.
    autos = sorted(s.save_id for s in listed if s.slot == AUTOSAVE_SLOT)
    assert autos and autos[-1] == "auto39"


def test_compact_reduces_an_index_that_grew_before_the_bound_existed(
    tmp_path, monkeypatch
):
    """Pruning otherwise only happens on the next save, which may never come."""
    from engine.game.state import GameState
    from engine.persistence.saves import AUTOSAVE_SLOT, SaveStore

    store = SaveStore(root=tmp_path / "saves", slug="clockwork-dark")
    state = GameState(location_id="forest_clearing")
    for n in range(30):
        store.save(state, save_id=f"auto{n:02d}", slot=AUTOSAVE_SLOT)
    assert len(store.list_saves()) == 30

    monkeypatch.setattr(
        "engine.persistence.saves.SaveStore._index_limit", lambda self: 5
    )
    dropped = store.compact()

    assert dropped == 25
    assert len(store.list_saves()) == 5


def test_reindex_restores_rows_that_pruning_hid(tmp_path, monkeypatch):
    """
    Pruning is reversible, which is what makes it safe to do automatically.

    The index is a derived LISTING, not the data: every run's real content is
    its own `save.json`, so dropping a row hides a run from the load menu
    without touching it. `reindex()` walks the directories and puts them back.
    """
    from engine.game.state import GameState
    from engine.persistence.saves import AUTOSAVE_SLOT, SaveStore

    store = SaveStore(root=tmp_path / "saves", slug="clockwork-dark")
    state = GameState(location_id="forest_clearing")
    for n in range(30):
        store.save(state, save_id=f"auto{n:02d}", slot=AUTOSAVE_SLOT)
    assert len(store.list_saves()) == 30

    # Prune hard.
    monkeypatch.setattr(
        "engine.persistence.saves.SaveStore._index_limit", lambda self: 5
    )
    store.compact()
    assert len(store.list_saves()) == 5
    # The runs themselves are untouched -- this is the whole claim.
    assert len(list((tmp_path / "saves").iterdir())) >= 30

    # Raise the bound and rebuild.
    monkeypatch.setattr(
        "engine.persistence.saves.SaveStore._index_limit", lambda self: 100
    )
    restored = store.reindex()

    assert restored == 30, "reindex did not recover every save on disk"
    assert {s.save_id for s in store.list_saves()} == {
        f"auto{n:02d}" for n in range(30)
    }


def test_reindex_recovers_from_a_corrupt_index(tmp_path):
    """An unreadable index used to mean every run was gone, as far as a player
    could tell. The saves were always right there."""
    from engine.game.state import GameState
    from engine.persistence.saves import SaveStore

    store = SaveStore(root=tmp_path / "saves", slug="clockwork-dark")
    state = GameState(location_id="forest_clearing")
    for n in range(4):
        store.save(state, save_id=f"run{n}")

    (tmp_path / "saves" / "index.json").write_text("{ this is not json",
                                                   encoding="utf-8")
    assert store.list_saves() == []

    assert store.reindex() == 4
    assert len(store.list_saves()) == 4
