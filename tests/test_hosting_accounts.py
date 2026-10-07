"""
Hosted mode's accounts (v0.20.0 T7, spec §6.1).

``engine/hosting/accounts.py`` is the one writer of ``users.json``: names and
passwords checked, ids minted from ``secrets`` (never from the name), the
epoch bumped by a password change and a disable, reads cached on
``(st_mtime_ns, st_size)``, every write a read-modify-write under an
``O_CREAT | O_EXCL`` lock file (proved with two PROCESSES), a stale lock
broken, and ``adopt`` MOVING the local player's runs, refusing a clash.

Every file lives under ``tmp_path``; passwords are generated per test.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from engine.hosting import accounts as accounts_module
from engine.hosting.accounts import (
    DUMMY_HASH,
    AccountError,
    AccountStore,
    AccountsFileError,
    adopt,
)
from tests.hosted_app import new_password

REPO = Path(__file__).resolve().parents[1]
PROBE = REPO / "tests" / "probes" / "accounts_writer.py"


@pytest.fixture
def store(tmp_path: Path) -> AccountStore:
    return AccountStore(tmp_path / "hosting")


# -- names and passwords ------------------------------------------------------


@pytest.mark.parametrize("name", ["al", "alice", "a_b-c9", "x" * 32])
def test_good_names_are_accepted(store: AccountStore, name: str) -> None:
    assert store.add(name, new_password()).name == name


@pytest.mark.parametrize(
    "name", ["a", "x" * 33, "Alice", "al ice", "../x", "a.b", "aliçe", "", "alice\n"]
)
def test_bad_names_are_refused(store: AccountStore, name: str) -> None:
    with pytest.raises(AccountError):
        store.add(name, new_password())
    assert not store.path.exists()


def test_a_password_is_at_least_ten_characters(store: AccountStore) -> None:
    with pytest.raises(AccountError, match="at least 10"):
        store.add("alice", "short-pw1")
    assert store.add("alice", "0123456789").name == "alice"


def test_a_taken_name_is_refused(store: AccountStore) -> None:
    store.add("alice", new_password())
    with pytest.raises(AccountError, match="already exists"):
        store.add("alice", new_password())
    assert len(store.all()) == 1


def test_the_hash_is_scrypt_and_verify_checks_it(store: AccountStore) -> None:
    password = new_password()
    account = store.add("alice", password)
    assert account.hash.startswith("scrypt:")
    assert password not in store.path.read_text(encoding="utf-8")
    assert store.verify("alice", password) == account
    assert store.verify("alice", password + "x") is None


def test_an_unknown_name_costs_a_dummy_hash_check(
    store: AccountStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    store.add("alice", new_password())
    checked: list[str] = []
    real = accounts_module.check_password_hash
    monkeypatch.setattr(
        accounts_module,
        "check_password_hash",
        lambda stored, pw: checked.append(stored) or real(stored, pw),
    )
    assert store.verify("nobody", new_password()) is None
    assert checked == [DUMMY_HASH]
    assert DUMMY_HASH.split("$", 1)[0] == store.by_name("alice").hash.split("$", 1)[0]


def test_ids_are_minted_never_derived_from_names(store: AccountStore) -> None:
    first = store.add("alice", new_password())
    store.remove("alice")
    second = store.add("alice", new_password())
    for account in (first, second):
        assert account.id.startswith("u_") and len(account.id) == 14
        assert "alice" not in account.id
        int(account.id[2:], 16)
    assert first.id != second.id


# -- the epoch ---------------------------------------------------------------


def test_a_password_change_and_a_disable_bump_the_epoch(store: AccountStore) -> None:
    account = store.add("alice", new_password())
    assert account.epoch == 1
    assert store.set_password("alice", new_password()).epoch == 2
    disabled = store.disable("alice")
    assert disabled.epoch == 3 and disabled.disabled
    enabled = store.enable("alice")
    assert enabled.epoch == 3 and not enabled.disabled
    assert store.set_password_by_id(account.id, new_password()).epoch == 4


# -- the admin role and must_change (v0.20.0 T14, spec §6.1, §14.6) --------------------


def test_a_row_without_the_new_fields_reads_them_as_false(store: AccountStore) -> None:
    """A users.json from before T14 needs no migration; only a literal true grants the role."""
    account = store.add("alice", new_password())
    data = json.loads(store.path.read_text(encoding="utf-8"))
    for row in data["accounts"]:
        del row["admin"], row["must_change"]
    store.path.write_text(json.dumps(data), encoding="utf-8")
    store._cache = None
    found = store.get(account.id)
    assert found is not None and found.admin is False and found.must_change is False
    data["accounts"][0]["admin"] = "yes"
    store.path.write_text(json.dumps(data), encoding="utf-8")
    store._cache = None
    assert store.get(account.id).admin is False


def test_add_records_the_role_and_must_change(store: AccountStore) -> None:
    plain = store.add("alice", new_password())
    root = store.add("root", new_password(), admin=True)
    assert (plain.admin, plain.must_change) == (False, False)
    assert (root.admin, root.must_change) == (True, False)
    rows = {row["name"]: row for row in json.loads(store.path.read_text(encoding="utf-8"))["accounts"]}
    assert rows["alice"]["admin"] is False and rows["alice"]["must_change"] is False


def test_a_generated_password_must_be_changed_and_its_owner_s_own_clears_it(store: AccountStore) -> None:
    account, once = store.create_with_generated_password("alice")
    assert account.must_change and len(once) >= 10
    assert once not in store.path.read_text(encoding="utf-8")
    assert store.verify("alice", once) is not None
    changed = store.set_password_by_id(account.id, new_password())
    assert not changed.must_change and changed.epoch == 2
    reset, again = store.reset_password(account.id, by_id=True)
    assert reset.must_change and reset.epoch == 3 and again != once
    assert store.verify("alice", again) is not None
    assert not store.set_password("alice", new_password()).must_change


def test_a_role_change_bumps_the_epoch_and_a_no_op_does_not(store: AccountStore) -> None:
    revoked: list[str] = []
    store.on_revoke(revoked.append)
    store.add("root", new_password(), admin=True)
    account = store.add("alice", new_password())
    granted = store.set_admin("alice", True)
    assert granted.admin and granted.epoch == 2 and revoked == [account.id]
    assert store.set_admin("alice", True).epoch == 2 and revoked == [account.id]
    demoted = store.set_admin(account.id, False, by_id=True)
    assert not demoted.admin and demoted.epoch == 3 and revoked == [account.id, account.id]


def test_the_guards_refuse_yourself_and_the_last_admin_inside_the_lock(store: AccountStore) -> None:
    from engine.hosting.accounts import LAST_ADMIN, LastAdmin, SelfAction

    root = store.add("root", new_password(), admin=True)
    other = store.add("other", new_password(), admin=True)
    with pytest.raises(SelfAction):
        store.set_admin(root.id, False, by_id=True, actor_id=root.id)
    with pytest.raises(SelfAction):
        store.disable(root.id, by_id=True, actor_id=root.id)
    with pytest.raises(SelfAction):
        store.remove(root.id, by_id=True, actor_id=root.id)
    store.set_admin(other.id, False, by_id=True, actor_id=root.id)
    for change in (
        lambda: store.set_admin(root.id, False, by_id=True, actor_id=other.id),
        lambda: store.disable(root.id, by_id=True, actor_id=other.id),
        lambda: store.remove(root.id, by_id=True, actor_id=other.id),
    ):
        with pytest.raises(LastAdmin, match=LAST_ADMIN.split(";")[0]):
            change()
    assert store.get(root.id).admin and not store.get(root.id).disabled
    # A disabled admin is not "an admin who remains": it does not count.
    store.set_admin(other.id, True, by_id=True)
    store.disable(other.id, by_id=True)
    with pytest.raises(LastAdmin):
        store.set_admin(root.id, False, by_id=True)
    # The CLI's force, after its terminal confirmation.
    assert not store.set_admin(root.id, False, by_id=True, force=True).admin
    assert store.admins() == [store.get(other.id)]


def test_a_disabled_account_does_not_verify_and_costs_the_same_work(
    store: AccountStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    password = new_password()
    store.add("alice", password)
    store.disable("alice")
    checked: list[str] = []
    real = accounts_module.check_password_hash
    monkeypatch.setattr(
        accounts_module,
        "check_password_hash",
        lambda stored, pw: checked.append(stored) or real(stored, pw),
    )
    assert store.verify("alice", password) is None
    assert checked == [DUMMY_HASH]


# -- the cache -------------------------------------------------------------------


def test_reads_are_cached_on_mtime_and_size(
    store: AccountStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    account = store.add("alice", new_password())
    reads: list[int] = []
    real = store._read_fresh
    monkeypatch.setattr(store, "_read_fresh", lambda: reads.append(1) or real())
    for _ in range(5):
        assert store.get(account.id) == account
    assert len(reads) == 1, "a second read of an unchanged file re-parsed it"

    # Another writer (a second store: another process's view) changes the file.
    other = AccountStore(store.directory)
    time.sleep(0.01)
    other.disable("alice")
    assert store.get(account.id).disabled
    assert len(reads) == 2


def test_own_writes_drop_the_cache_without_waiting_on_mtime(store: AccountStore) -> None:
    account = store.add("alice", new_password())
    assert store.get(account.id).epoch == 1
    # Freeze the file's mtime: only the dropped cache can show the change.
    stat = store.path.stat()
    store.set_password("alice", new_password())
    os.utime(store.path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    assert store.get(account.id).epoch == 2


def test_another_writer_s_same_size_rewrite_in_one_tick_is_seen(store: AccountStore) -> None:
    """A passwd from another process rewrites a file of the same size; with the
    mtime put back as it was (one coarse clock tick), only the new inode shows it."""
    account = store.add("alice", new_password())
    assert store.get(account.id).epoch == 1
    before = store.path.stat()
    AccountStore(store.directory).set_password("alice", new_password())
    after = store.path.stat()
    assert after.st_size == before.st_size
    os.utime(store.path, ns=(before.st_atime_ns, before.st_mtime_ns))
    assert store.get(account.id).epoch == 2, "a stale cached epoch survived another writer"


def test_a_row_whose_id_is_not_an_account_id_fails_closed(store: AccountStore) -> None:
    store.add("alice", new_password())
    data = json.loads(store.path.read_text(encoding="utf-8"))
    data["accounts"][0]["id"] = "../.."
    store.path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(AccountsFileError, match="not an account id"):
        store.all()


def test_purge_refuses_anything_but_an_account_folder(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from engine.hosting.accounts import Account, purge_user_dir

    monkeypatch.setenv("CLOCKWORK_DATA_DIR", str(tmp_path / "data"))
    precious = tmp_path / "data" / "saves"
    precious.mkdir(parents=True)
    (precious / "keep.txt").write_text("x", encoding="utf-8")
    forged = Account(id="../saves", name="x", hash="", created=0.0, epoch=1, disabled=False)
    with pytest.raises(AccountError):
        purge_user_dir(forged)
    assert (precious / "keep.txt").exists()


def test_no_backup_of_old_hashes_is_kept(store: AccountStore) -> None:
    store.add("alice", new_password())
    old_hash = store.by_name("alice").hash
    backup = store.path.with_suffix(".json.bak")
    backup.write_text(json.dumps({"accounts": [{"hash": old_hash}]}), encoding="utf-8")
    store.set_password("alice", new_password())
    assert not backup.exists(), "users.json.bak kept a retired hash"
    assert old_hash not in "".join(
        p.read_text(encoding="utf-8", errors="replace") for p in store.directory.iterdir() if p.is_file()
    )


@pytest.mark.skipif(os.name != "posix", reason="file modes are POSIX's")
def test_every_file_under_hosting_is_private(store: AccountStore) -> None:
    import stat

    store.directory.mkdir(parents=True, mode=0o755)
    os.chmod(store.directory, 0o755)
    store.add("alice", new_password())
    store.set_password("alice", new_password())
    assert stat.S_IMODE(store.directory.stat().st_mode) == 0o700
    for path in store.directory.iterdir():
        assert stat.S_IMODE(path.stat().st_mode) & 0o077 == 0, path


def test_hashing_waits_for_a_slot_then_is_busy_the_same_for_every_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from engine.hosting.accounts import LoginBusy

    slots = threading.BoundedSemaphore(1)
    store = AccountStore(tmp_path / "hosting", hash_slots=slots)
    password = new_password()
    store.add("alice", password)
    monkeypatch.setattr(accounts_module, "HASH_WAIT_SECONDS", 0.2)
    hashed: list[str] = []
    real = accounts_module.check_password_hash
    monkeypatch.setattr(
        accounts_module,
        "check_password_hash",
        lambda stored, pw: hashed.append(stored) or real(stored, pw),
    )
    assert slots.acquire(timeout=1)
    try:
        for name, typed in (("nobody", password), ("alice", password + "x"), ("alice", password)):
            started = time.monotonic()
            with pytest.raises(LoginBusy):
                store.verify(name, typed)
            assert 0.15 <= time.monotonic() - started < 2.0
        with pytest.raises(LoginBusy):
            store.check_current(store.by_name("alice").id, password)
        with pytest.raises(LoginBusy):
            store.set_password("alice", new_password())
        assert hashed == [], "a password was hashed without a slot"
    finally:
        slots.release()
    assert store.verify("alice", password) is not None


def test_hashing_is_bounded_under_threads(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Eight logins at once through two slots: never more than two hashes run."""
    slots = threading.BoundedSemaphore(2)
    store = AccountStore(tmp_path / "hosting", hash_slots=slots)
    password = new_password()
    store.add("alice", password)
    running = [0]
    peak = [0]
    guard = threading.Lock()
    real = accounts_module.check_password_hash

    def counted(stored: str, pw: str) -> bool:
        with guard:
            running[0] += 1
            peak[0] = max(peak[0], running[0])
        try:
            time.sleep(0.05)
            return real(stored, pw)
        finally:
            with guard:
                running[0] -= 1

    monkeypatch.setattr(accounts_module, "check_password_hash", counted)
    barrier = threading.Barrier(8)
    results: list[object] = []

    def attempt() -> None:
        barrier.wait(timeout=10)
        results.append(store.verify("alice", password))

    threads = [threading.Thread(target=attempt) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    assert not any(t.is_alive() for t in threads)
    assert peak[0] <= 2 and len(results) == 8


def test_a_malformed_file_fails_closed(store: AccountStore) -> None:
    store.directory.mkdir(parents=True)
    store.path.write_text("{not json", encoding="utf-8")
    with pytest.raises(AccountsFileError):
        store.get("u_000000000000")


def test_unknown_row_fields_survive_a_write(store: AccountStore) -> None:
    account = store.add("alice", new_password())
    data = json.loads(store.path.read_text(encoding="utf-8"))
    data["accounts"][0]["admin"] = True
    store.path.write_text(json.dumps(data), encoding="utf-8")
    store.set_password("alice", new_password())
    row = json.loads(store.path.read_text(encoding="utf-8"))["accounts"][0]
    assert row["admin"] is True and row["id"] == account.id


# -- the lock -----------------------------------------------------------------


def test_two_processes_changing_two_accounts_at_once_both_land(
    store: AccountStore, tmp_path: Path
) -> None:
    """Each probe sets its account's password, then disables and enables it
    ``ROUNDS`` times: every write of both must land (epoch 1 + 1 + ROUNDS)."""
    rounds = 15
    alice = store.add("alice", new_password())
    bob = store.add("bob", new_password())
    go = tmp_path / "go"
    passwords = {"alice": new_password(), "bob": new_password()}
    children: list[subprocess.Popen[str]] = []
    try:
        for name in ("alice", "bob"):
            child = subprocess.Popen(
                [sys.executable, str(PROBE), str(store.directory), name, str(rounds), str(go)],
                cwd=str(REPO),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            assert child.stdin is not None
            child.stdin.write(passwords[name] + "\n")
            child.stdin.close()
            # Closed by hand: on POSIX communicate() would flush it again and
            # raise ValueError (found in the Linux container run, T13).
            child.stdin = None
            children.append(child)
        time.sleep(0.5)  # both imported and waiting
        go.write_text("go", encoding="utf-8")
        for child in children:
            out, err = child.communicate(timeout=120)
            assert child.returncode == 0, err
            assert "done" in out
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=10)
    fresh = AccountStore(store.directory)
    for account, name in ((alice, "alice"), (bob, "bob")):
        now = fresh.get(account.id)
        assert now.epoch == 1 + 1 + rounds, f"{name}: a write was lost ({now.epoch})"
        assert not now.disabled
        assert fresh.verify(name, passwords[name]) is not None


def _held_lock(store: AccountStore) -> int:
    """Take the accounts lock through a handle of the test's own (another holder)."""
    from engine.hosting.accounts import open_private, secure_dir, try_lock

    secure_dir(store.directory)
    fd = open_private(store.lock_path)
    assert try_lock(fd)
    return fd


def _write_in_thread(store: AccountStore) -> tuple[threading.Thread, threading.Event]:
    done = threading.Event()

    def write() -> None:
        store.disable("alice")
        done.set()

    worker = threading.Thread(target=write)
    worker.start()
    return worker, done


def test_a_writer_waits_for_a_held_lock_and_goes_on_when_it_is_freed(store: AccountStore) -> None:
    from engine.hosting.accounts import unlock

    store.add("alice", new_password())
    fd = _held_lock(store)
    worker, done = _write_in_thread(store)
    try:
        assert not done.wait(0.3), "a writer ignored a held lock"
        unlock(fd)
        assert done.wait(10)
    finally:
        os.close(fd)
        worker.join(timeout=10)
    assert not worker.is_alive()
    assert store.by_name("alice").disabled


def test_a_lock_file_left_behind_blocks_nobody(store: AccountStore) -> None:
    """A process that dies holding the lock leaves at most a FILE; the system
    lock died with it. v0.20.0 T7's first design read a fresh leftover file as
    held and waited 30 s before breaking it (and breaking by path was a race)."""
    store.add("alice", new_password())
    store.lock_path.write_text("12345 1790000000.000\n", encoding="utf-8")
    worker, done = _write_in_thread(store)
    try:
        assert done.wait(5), "a leftover lock file blocked a writer"
    finally:
        worker.join(timeout=60)
    assert store.by_name("alice").disabled


def _first_line(stream: Any, timeout: float) -> str:
    """
    The first line of ``stream`` within ``timeout`` seconds, or a failure: a
    bare ``readline`` would wait forever on a child that never prints.
    """
    lines: list[str] = []
    reader = threading.Thread(target=lambda: lines.append(stream.readline()), name="first-line", daemon=True)
    reader.start()
    reader.join(timeout)
    assert lines, f"the child printed no line within {timeout}s"
    return lines[0]


def test_a_killed_holder_frees_the_lock(store: AccountStore, tmp_path: Path) -> None:
    store.add("alice", new_password())
    child = subprocess.Popen(
        [sys.executable, str(PROBE), str(store.directory), "alice", "hold", str(tmp_path / "go")],
        cwd=str(REPO),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert child.stdout is not None
        assert _first_line(child.stdout, 30).strip() == "held"
        worker, done = _write_in_thread(store)
        try:
            assert not done.wait(0.3), "the child's lock was not held"
            child.kill()
            child.wait(timeout=10)
            assert done.wait(10), "a killed holder's lock was never freed"
        finally:
            worker.join(timeout=60)
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=10)
    assert store.by_name("alice").disabled


def test_a_release_frees_only_the_holder_s_own_lock(store: AccountStore) -> None:
    """A lets go while B waits; B takes it; a third writer then waits for B."""
    from engine.hosting.accounts import unlock

    store.add("alice", new_password())
    first = _held_lock(store)
    b_has_it = threading.Event()
    b_may_go = threading.Event()

    def b() -> None:
        with store._locked():
            b_has_it.set()
            b_may_go.wait(10)

    holder = threading.Thread(target=b)
    holder.start()
    try:
        assert not b_has_it.wait(0.3)
        unlock(first)
        os.close(first)
        assert b_has_it.wait(10)
        worker, done = _write_in_thread(store)
        try:
            assert not done.wait(0.3), "a third writer got in while B held the lock"
            b_may_go.set()
            assert done.wait(10)
        finally:
            worker.join(timeout=10)
    finally:
        b_may_go.set()
        holder.join(timeout=10)
    assert not holder.is_alive()


# -- adopt -------------------------------------------------------------------------


def _local_run(base: Path, slug: str, save_id: str) -> Path:
    directory = base / slug / save_id
    directory.mkdir(parents=True)
    envelope = {
        "save_id": save_id,
        "slot": "autosave",
        "updated_at": 1790000000.0,
        "created_at": 1790000000.0,
        "state": {"player_name": "Ada", "turn_number": 3},
    }
    (directory / "save.json").write_text(json.dumps(envelope), encoding="utf-8")
    (directory / "transcript.jsonl").write_text("{}\n", encoding="utf-8")
    return directory


def test_adopt_moves_the_local_runs_never_copies(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from engine.persistence import saves, storage

    monkeypatch.setenv("CLOCKWORK_DATA_DIR", str(tmp_path / "data"))
    store = AccountStore(storage.hosting_dir())
    account = store.add("alice", new_password())
    base = saves.saves_base()
    first = _local_run(base, "clockwork-dark", "abc123def456")
    second = _local_run(base, "hue-and-cry", "fff000aaa111")
    before = (first / "save.json").read_bytes()

    moved = adopt(account, "clockwork-dark")
    assert moved == {"clockwork-dark": ["abc123def456"]}
    target = storage.saves_dir(account.id, "clockwork-dark") / "abc123def456"
    assert not first.exists(), "adopt copied the run instead of moving it"
    assert (target / "save.json").read_bytes() == before
    assert (target / "transcript.jsonl").exists()
    assert second.exists(), "--game moved another story's runs"
    index = json.loads((target.parent / "index.json").read_text(encoding="utf-8"))
    assert [row["save_id"] for row in index["saves"]] == ["abc123def456"]
    assert str(target).startswith(str(tmp_path / "data" / "users" / account.id))

    assert adopt(account) == {"hue-and-cry": ["fff000aaa111"]}
    assert not second.exists()


def test_adopt_refuses_an_id_already_in_the_account_and_moves_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from engine.persistence import saves, storage

    monkeypatch.setenv("CLOCKWORK_DATA_DIR", str(tmp_path / "data"))
    store = AccountStore(storage.hosting_dir())
    account = store.add("alice", new_password())
    base = saves.saves_base()
    clash = _local_run(base, "clockwork-dark", "abc123def456")
    other = _local_run(base, "clockwork-dark", "bbb222ccc333")
    theirs = storage.saves_dir(account.id, "clockwork-dark") / "abc123def456"
    theirs.mkdir(parents=True)
    (theirs / "save.json").write_text("{}", encoding="utf-8")

    with pytest.raises(AccountError, match="abc123def456"):
        adopt(account, "clockwork-dark")
    assert clash.exists() and other.exists(), "a refused adoption moved something"
    assert (theirs / "save.json").read_text(encoding="utf-8") == "{}"


def _cross_device(monkeypatch: pytest.MonkeyPatch, base: Path) -> None:
    """``os.rename`` from the local saves to anywhere else answers EXDEV."""
    import errno

    real_rename = os.rename

    def cross_device(src: object, dst: object) -> None:
        if str(src).startswith(str(base)) and not str(dst).startswith(str(base)):
            raise OSError(errno.EXDEV, "Invalid cross-device link")
        real_rename(src, dst)

    monkeypatch.setattr(os, "rename", cross_device)


def _local_index_ids(base: Path, slug: str) -> list[str]:
    index = base / slug / "index.json"
    if not index.is_file():
        return []
    return [row["save_id"] for row in json.loads(index.read_text(encoding="utf-8"))["saves"]]


def test_a_cross_volume_move_whose_source_removal_fails_leaves_one_copy_and_reruns(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The verified copy is in place, then removing the local run fails half
    way (a file a local game holds, on Windows): exactly one complete run
    must remain visible, and running adopt again must finish the job."""
    import shutil as shutil_module

    from engine.persistence import saves, storage

    monkeypatch.setenv("CLOCKWORK_DATA_DIR", str(tmp_path / "data"))
    account = AccountStore(storage.hosting_dir()).add("alice", new_password())
    base = saves.saves_base()
    run = _local_run(base, "clockwork-dark", "abc123def456")
    before = {p.name: p.read_bytes() for p in run.iterdir()}
    _cross_device(monkeypatch, base)
    real_rmtree = shutil_module.rmtree
    failed: list[str] = []

    def half_way(path: object, *args: object, **kwargs: object) -> None:
        here = Path(str(path))
        if not failed and here.parent == run.parent and here.name.startswith(run.name):
            first = sorted(p for p in here.iterdir() if p.is_file())[0]
            first.unlink()
            failed.append(here.name)
            raise PermissionError(13, "The process cannot access the file", str(here))
        real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(shutil_module, "rmtree", half_way)
    with pytest.raises(AccountError, match="run adopt again"):
        adopt(account, "clockwork-dark")
    target = storage.saves_dir(account.id, "clockwork-dark") / "abc123def456"
    assert {p.name: p.read_bytes() for p in target.iterdir()} == before
    assert not run.exists(), "the half-removed local run is still a run"
    assert "abc123def456" not in _local_index_ids(base, "clockwork-dark")
    # A re-run removes the leftover and moves nothing twice.
    assert adopt(account, "clockwork-dark") == {}
    assert not any(p.name.startswith("abc123def456") for p in (base / "clockwork-dark").iterdir())
    assert {p.name: p.read_bytes() for p in target.iterdir()} == before


def test_a_cross_volume_move_that_cannot_take_the_source_rolls_the_copy_back(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from engine.hosting.accounts import ASIDE_SUFFIX, STAGING_SUFFIX
    from engine.persistence import saves, storage

    monkeypatch.setenv("CLOCKWORK_DATA_DIR", str(tmp_path / "data"))
    account = AccountStore(storage.hosting_dir()).add("alice", new_password())
    base = saves.saves_base()
    run = _local_run(base, "clockwork-dark", "abc123def456")
    before = {p.name: p.read_bytes() for p in run.iterdir()}
    _cross_device(monkeypatch, base)
    cross = os.rename

    def held(src: object, dst: object) -> None:
        if str(dst).endswith(ASIDE_SUFFIX):
            raise PermissionError(13, "The process cannot access the file", str(src))
        cross(src, dst)

    monkeypatch.setattr(os, "rename", held)
    with pytest.raises(AccountError, match="unchanged"):
        adopt(account, "clockwork-dark")
    target_dir = storage.saves_dir(account.id, "clockwork-dark")
    assert {p.name: p.read_bytes() for p in run.iterdir()} == before
    assert not (target_dir / "abc123def456").exists()
    assert not (target_dir / ("abc123def456" + STAGING_SUFFIX)).exists()
    monkeypatch.setattr(os, "rename", cross)
    assert adopt(account, "clockwork-dark") == {"clockwork-dark": ["abc123def456"]}
    assert not run.exists()


def test_a_cross_volume_move_that_can_neither_place_the_copy_nor_move_back_reruns(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """
    T7 re-review 2: when putting the verified copy in place fails AND moving
    the local run back from its set-aside folder fails too, the second
    failure was an unhandled ``OSError``. Now: an ``AccountError`` saying
    where the run is, the copy dropped, and a re-run restoring and moving it.
    """
    from engine.hosting.accounts import ASIDE_SUFFIX, STAGING_SUFFIX
    from engine.persistence import saves, storage

    monkeypatch.setenv("CLOCKWORK_DATA_DIR", str(tmp_path / "data"))
    account = AccountStore(storage.hosting_dir()).add("alice", new_password())
    base = saves.saves_base()
    run = _local_run(base, "clockwork-dark", "abc123def456")
    before = {p.name: p.read_bytes() for p in run.iterdir()}
    _cross_device(monkeypatch, base)
    cross = os.rename

    def stuck(src: object, dst: object) -> None:
        if str(src).endswith(STAGING_SUFFIX) or str(src).endswith(ASIDE_SUFFIX):
            raise PermissionError(13, "The process cannot access the file", str(src))
        cross(src, dst)

    monkeypatch.setattr(os, "rename", stuck)
    with pytest.raises(AccountError, match="run adopt again"):
        adopt(account, "clockwork-dark")
    aside = run.with_name(run.name + ASIDE_SUFFIX)
    target_dir = storage.saves_dir(account.id, "clockwork-dark")
    assert {p.name: p.read_bytes() for p in aside.iterdir()} == before
    assert not (target_dir / "abc123def456").exists()
    assert not (target_dir / ("abc123def456" + STAGING_SUFFIX)).exists()
    monkeypatch.setattr(os, "rename", cross)
    assert adopt(account, "clockwork-dark") == {"clockwork-dark": ["abc123def456"]}
    assert {p.name: p.read_bytes() for p in (target_dir / "abc123def456").iterdir()} == before
    assert not aside.exists() and not run.exists()


def test_adopt_across_volumes_copies_verifies_and_removes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``os.rename`` answers EXDEV (another mount, a Docker volume): the run is
    copied, checked file by file, and only then removed from the source."""
    import errno

    from engine.persistence import saves, storage

    monkeypatch.setenv("CLOCKWORK_DATA_DIR", str(tmp_path / "data"))
    store = AccountStore(storage.hosting_dir())
    account = store.add("alice", new_password())
    base = saves.saves_base()
    run = _local_run(base, "clockwork-dark", "abc123def456")
    before = {p.name: p.read_bytes() for p in run.iterdir()}
    _cross_device(monkeypatch, base)
    assert adopt(account, "clockwork-dark") == {"clockwork-dark": ["abc123def456"]}
    target = storage.saves_dir(account.id, "clockwork-dark") / "abc123def456"
    assert {p.name: p.read_bytes() for p in target.iterdir()} == before
    assert not run.exists(), "the source was left behind after the copy"
    assert not target.with_name("abc123def456.adopting").exists()


def test_adopt_refuses_while_a_hosted_server_holds_its_lock(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from engine.hosting.accounts import hold_server_lock, running_servers
    from engine.persistence import saves, storage

    monkeypatch.setenv("CLOCKWORK_DATA_DIR", str(tmp_path / "data"))
    store = AccountStore(storage.hosting_dir())
    account = store.add("alice", new_password())
    run = _local_run(saves.saves_base(), "clockwork-dark", "abc123def456")
    fd = hold_server_lock(storage.hosting_dir())
    try:
        with pytest.raises(AccountError, match="hosted server is running"):
            adopt(account, "clockwork-dark")
        assert run.exists()
    finally:
        os.close(fd)
    # The server is gone: its leftover lock file is cleared and adopt goes on.
    assert running_servers(storage.hosting_dir()) == []
    assert adopt(account, "clockwork-dark") == {"clockwork-dark": ["abc123def456"]}


def test_a_server_starting_mid_scan_is_never_a_traceback(tmp_path: Path) -> None:
    """A server that has opened its lock file and not yet locked it: the scan
    must not crash (on Windows the file cannot be removed while open) and must
    not take it for a dead server's on Windows."""
    from engine.hosting.accounts import open_private, running_servers, secure_dir

    directory = secure_dir(tmp_path / "hosting")
    starting = directory / "server-4242-abcd0123.lock"
    fd = open_private(starting)  # opened, not locked
    try:
        held = running_servers(directory)
        if os.name == "nt":
            assert held == [starting.name]
        else:
            assert held == [] and not starting.exists()
    finally:
        os.close(fd)


def test_adopt_holds_the_lock_and_a_second_adopt_is_refused_cleanly(tmp_path: Path) -> None:
    from engine.hosting.accounts import ADOPT_LOCK_BUSY, adopt_lock

    directory = tmp_path / "hosting"
    with adopt_lock(directory):
        with pytest.raises(AccountError) as caught:
            with adopt_lock(directory):
                pass
        assert str(caught.value) == ADOPT_LOCK_BUSY


def test_a_server_cannot_take_its_lock_while_adopt_runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from engine.hosting.accounts import ADOPT_RUNNING, adopt_lock, hold_server_lock

    # An adopt holds adopt.lock for its whole run: past the probe's retries
    # (shortened here, 2 s shipped) the server is refused.
    monkeypatch.setattr(accounts_module, "PROBE_RETRY_SECONDS", 0.2)
    directory = tmp_path / "hosting"
    with adopt_lock(directory):
        with pytest.raises(AccountError) as caught:
            hold_server_lock(directory)
        assert str(caught.value) == ADOPT_RUNNING
        assert list(directory.glob("server-*.lock")) == [], "the refused server left its lock file"
    fd = hold_server_lock(directory)
    os.close(fd)


# -- servers starting together (v0.20.0 T13) -------------------------------------------


def test_a_server_starting_during_another_server_s_probe_is_not_refused(tmp_path: Path) -> None:
    """
    Another server's look at ``adopt.lock`` holds it for an instant; one
    starting at that instant used to be refused as if an adopt ran
    (``ADOPT_RUNNING``). Here a probe holds the lock for 0.3 s while a server
    starts: it retries and starts.
    """
    from engine.hosting.accounts import ADOPT_LOCK, hold_server_lock, open_private, secure_dir, try_lock, unlock

    directory = secure_dir(tmp_path / "hosting")
    probe = open_private(directory / ADOPT_LOCK)
    assert try_lock(probe)

    def let_go() -> None:
        unlock(probe)
        os.close(probe)

    timer = threading.Timer(0.3, let_go)
    timer.start()
    fd = None
    try:
        fd = hold_server_lock(directory)
    finally:
        timer.join(10)
        assert not timer.is_alive()
        if fd is not None:
            os.close(fd)
    assert fd is not None


def test_n_servers_starting_at_once_never_refuse_each_other(tmp_path: Path) -> None:
    """Sixteen servers released together by a barrier, twenty times: every one starts."""
    from engine.hosting.accounts import hold_server_lock, secure_dir

    directory = secure_dir(tmp_path / "hosting")
    count = 16
    for _round in range(20):
        barrier = threading.Barrier(count)
        held: list[int] = []
        failed: list[BaseException] = []
        guard = threading.Lock()

        def start() -> None:
            barrier.wait(10)
            try:
                fd = hold_server_lock(directory)
            except BaseException as exc:  # noqa: BLE001 -- recorded and asserted below
                with guard:
                    failed.append(exc)
                return
            with guard:
                held.append(fd)

        threads = [threading.Thread(target=start, name=f"server-start-{i}") for i in range(count)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(30)
        assert not any(t.is_alive() for t in threads), "a server start hung"
        for fd in held:
            os.close(fd)
        assert not failed, f"servers refused each other: {failed[:3]!r}"
        assert len(held) == count
