"""
A session carries its save store (v0.20.0 T3; spec §4.4).

``GameSession`` has an ``owner`` ("" for the local player; an account in
hosted mode) and ``saves``, the ``SaveStore`` it was created or resumed from,
set when it is built. The autosave, ``SessionStore.create`` and ``resume`` and
the save routes use that store, never "whatever the process singleton is".
``get_save_store()`` stays, as ``save_store_for("", active story)``: local
mode resolves the same object it always did. ``save_store_for(owner, slug)``
caches one store per pair, each with its own index lock, and an account's
store never runs the legacy flat-directory migration, which exists only for
the local owner's old ``data/saves/``.

``CLOCKWORK_DATA_DIR`` is ``tmp_path`` in every test that builds an account's
store, so nothing is written under the repository's ``data/``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from engine.games import registry
from engine.persistence import saves
from engine.persistence.saves import InvalidSaveId, SaveStore, get_save_store, save_store_for
from engine.scenes import default_state
from engine.scenes.default_state import DefaultSessionStore
from engine.session.store import GameSession
from tests.local_golden import scripted_model

SLUG = "clockwork-dark"


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "data"
    monkeypatch.setenv("CLOCKWORK_DATA_DIR", str(root))
    saves.reset_save_store()
    yield root
    saves.reset_save_store()


def test_a_session_has_an_owner_and_its_store(data_dir: Path) -> None:
    session = DefaultSessionStore().create(seed=5, llm_fn=scripted_model)
    assert isinstance(session, GameSession)
    assert session.owner == ""
    assert session.saves is get_save_store()
    assert session.save_id and session.saves.exists(session.save_id)

    fields = GameSession.__dataclass_fields__
    assert fields["owner"].default == ""


def test_the_local_store_is_get_save_store_for_the_active_story(data_dir: Path) -> None:
    active = registry.active_slug()
    assert save_store_for("", active) is get_save_store()
    assert save_store_for("", None) is get_save_store()
    assert save_store_for() is get_save_store()
    # Under the conftest's redirect of the local save base, as before.
    assert get_save_store().root == saves.saves_base() / active


def test_two_owners_get_two_stores_two_directories_and_two_locks(data_dir: Path) -> None:
    alice = save_store_for("alice", SLUG)
    bob = save_store_for("bob", SLUG)
    assert alice is not bob
    assert alice is save_store_for("alice", SLUG)
    assert alice.root == data_dir / "users" / "alice" / "saves" / SLUG
    assert bob.root == data_dir / "users" / "bob" / "saves" / SLUG
    assert alice.root != get_save_store().root
    assert alice._lock is not bob._lock
    assert alice.slug == bob.slug == SLUG


@pytest.mark.parametrize("owner", ["../x", "..", "a/b", "nul", "x" * 65])
def test_an_owner_that_is_not_a_name_is_refused(data_dir: Path, owner: str) -> None:
    with pytest.raises(InvalidSaveId):
        save_store_for(owner, SLUG)
    assert not (data_dir / "users").exists()


def test_create_and_resume_use_the_owners_store(data_dir: Path) -> None:
    sessions = DefaultSessionStore()
    created = sessions.create(seed=9, llm_fn=scripted_model, owner="alice")
    alice = save_store_for("alice", None)
    assert created.owner == "alice" and created.saves is alice
    assert alice.exists(created.save_id)
    assert not get_save_store().exists(created.save_id)

    resumed = sessions.resume(created.save_id, llm_fn=scripted_model, owner="alice")
    assert resumed.owner == "alice" and resumed.saves is alice
    # Another owner cannot reach it: it is simply not in their store.
    with pytest.raises(FileNotFoundError):
        sessions.resume(created.save_id, llm_fn=scripted_model, owner="bob")
    with pytest.raises(FileNotFoundError):
        sessions.resume(created.save_id, llm_fn=scripted_model)


def test_the_autosave_writes_through_the_sessions_store(
    data_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Not through the process singleton: patching ``get_save_store`` AFTER the
    session is built moves nothing -- the session already has its store.
    """
    session = DefaultSessionStore().create(seed=11, llm_fn=scripted_model, owner="alice")
    elsewhere = SaveStore(root=tmp_path / "elsewhere", slug=SLUG)
    monkeypatch.setattr(default_state, "get_save_store", lambda: elsewhere)

    default_state._autosave(session, "look about you", "The lamps gutter.")
    assert session.saves.exists(session.save_id)
    transcript = session.saves.root / session.save_id / "transcript.jsonl"
    lines = [json.loads(x) for x in transcript.read_text(encoding="utf-8").splitlines() if x]
    assert lines[-1]["action"] == "look about you"
    assert not (tmp_path / "elsewhere").exists()


def test_a_hand_built_session_autosaves_to_the_local_store(data_dir: Path) -> None:
    built = DefaultSessionStore().create(seed=13, llm_fn=scripted_model)
    bare = GameSession(
        engine=built.engine,
        storyteller=built.storyteller,
        assistant=built.assistant,
        save_id=built.save_id,
        ledger=built.ledger,
    )
    assert bare.saves is None
    default_state._autosave(bare, "wait", "Nothing moves.")
    assert get_save_store().exists(bare.save_id)


def test_an_accounts_store_never_migrates(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    The legacy migration folds a pre-namespacing flat ``data/saves/`` into a
    story's namespace; it is the local owner's alone. A flat-looking account
    directory is left exactly as it is.
    """
    calls: list[Any] = []
    real = saves._migrate_legacy
    monkeypatch.setattr(saves, "_migrate_legacy", lambda base, slug: calls.append((base, slug)) or real(base, slug))
    monkeypatch.setattr(saves, "_migrated", set())

    base = data_dir / "users" / "alice" / "saves"
    base.mkdir(parents=True)
    (base / "index.json").write_text('{"saves": []}', encoding="utf-8")
    (base / "abc123").mkdir()
    (base / "abc123" / "save.json").write_text("{}", encoding="utf-8")

    save_store_for("alice", SLUG)
    assert calls == []
    assert (base / "index.json").is_file() and (base / "abc123" / "save.json").is_file()
    assert not (base / SLUG).exists()

    # The local owner's store does run it (and finds nothing to move here).
    save_store_for("", SLUG)
    assert calls == [(saves.saves_base(), SLUG)]


# -- v0.20.0 T8: one index lock per folder, and owner ids folded ---------------


def test_owner_ids_differing_only_in_case_share_one_store_and_one_folder(data_dir: Path) -> None:
    """
    On a case-insensitive file system ``u_ABC...`` and ``u_abc...`` are one
    folder: two stores over it would hold two index locks (T3's review).
    The owner is folded before it reaches a path or the cache key.
    """
    upper = save_store_for("u_ABCDEF012345", SLUG)
    lower = save_store_for("u_abcdef012345", SLUG)
    assert upper is lower
    assert upper.root == data_dir / "users" / "u_abcdef012345" / "saves" / SLUG


def test_every_store_for_one_folder_shares_one_index_lock(data_dir: Path, tmp_path: Path) -> None:
    before = save_store_for("", SLUG)
    saves.reset_save_store()  # what every config reset does
    after = save_store_for("", SLUG)
    assert after is not before
    assert after._lock is before._lock, "a reset's replacement store took a second index lock"
    assert SaveStore(root=tmp_path / "f", slug=SLUG)._lock is SaveStore(root=tmp_path / "f", slug=SLUG)._lock
    assert SaveStore(root=tmp_path / "F", slug=SLUG)._lock is SaveStore(root=tmp_path / "f", slug=SLUG)._lock
    assert SaveStore(root=tmp_path / "g", slug=SLUG)._lock is not before._lock


def test_a_save_through_a_replacement_store_waits_for_the_old_stores_writer(
    data_dir: Path,
) -> None:
    """
    T6 round 2's finding, forced: a turn still saving through the store a
    reset dropped holds the folder's index lock; a save through the
    replacement for the same folder must wait for it, not race it (two locks
    over one ``index.json``: on Windows the second ``os.replace`` fails and
    that autosave is lost).
    """
    import threading

    session = DefaultSessionStore().create(seed=21, llm_fn=scripted_model)
    old = session.saves
    saves.reset_save_store()
    new = save_store_for("", SLUG)
    assert new is not old
    done = threading.Event()

    def save_through_the_new_store() -> None:
        new.save(session.engine.state, save_id=session.save_id)
        done.set()

    with old._lock:  # the old store's writer, mid index write
        worker = threading.Thread(target=save_through_the_new_store, daemon=True)
        worker.start()
        assert not done.wait(0.5), "the replacement store wrote the index under the old one's writer"
    worker.join(timeout=30)
    assert not worker.is_alive(), "the save never finished"
    assert done.is_set()


def test_a_forked_child_starts_with_no_folder_lock_and_no_cached_store(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Fix round 1 (M8): a folder's RLock another thread held at fork stays
    held in the child, so the child must build its stores and their locks
    afresh. Windows never forks, so the after-fork hook is called by hand,
    as ``renew_after_fork`` would register it.
    """
    import threading

    from engine import locks

    # What the module registered at import (fails on 1849d9a: only the lock).
    assert ("engine.persistence.saves", "_index_locks") in locks.RENEWED_AFTER_FORK
    assert ("engine.persistence.saves", "_stores") in locks.RENEWED_AFTER_FORK
    hooks: list[Any] = []
    monkeypatch.setattr(locks.os, "register_at_fork", lambda **kw: hooks.append(kw["after_in_child"]), raising=False)
    monkeypatch.setattr(locks, "RENEWED_AFTER_FORK", list(locks.RENEWED_AFTER_FORK))
    held = save_store_for("", SLUG)
    lock = held._lock
    # The same registration, captured so the child's hook can be run here.
    locks.renew_after_fork(
        vars(saves),
        _index_locks_lock=threading.Lock,
        _index_locks=type(saves._index_locks),
        _stores=lambda: None,
    )
    lock.acquire()  # a parent's other thread, mid index write, at the fork
    try:
        hooks[-1]()  # the child
        fresh = save_store_for("", SLUG)
        assert fresh is not held and fresh._lock is not lock
        assert fresh._lock.acquire(blocking=False), "the child's folder lock is not free"
        fresh._lock.release()
    finally:
        lock.release()
