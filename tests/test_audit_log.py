"""
The audit log (v0.20.0 T14, spec §14.11, §14.3).

``engine/hosting/audit.py`` is the only writer of
``<storage.root>/hosting/audit.jsonl``:

- the closed field set and the action enum are pinned to the spec's;
- a row outside them is refused, never written;
- the write-first helper: a ``started`` row before the action and its
  outcome after, sharing a ``ref``; an action whose started row cannot be
  written never runs;
- two PROCESSES appending at once (``tests/probes/audit_writer.py``): every
  line lands whole;
- after a scripted run of every panel action, a re-auth (good and bad) and
  the CLI's changes, no line holds a password, a hash, the cookie key or a
  token;
- a supervisor holding a crash-looping story down writes ``story.held_down``
  as the actor ``supervisor`` (a real supervisor, ``tests/hosting_instance.py``).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from engine.hosting import audit
from tests.hosting_instance import AdminDoor, HostingInstance, csrf_of

REPO = Path(__file__).resolve().parents[1]
SPEC = REPO / "docs" / "superpowers" / "specs" / "2026-09-30-linux-and-hosting-design.md"
PROBE = REPO / "tests" / "probes" / "audit_writer.py"
ACTOR = audit.Actor("u_0123456789ab", "root", "127.0.0.1")


def _section() -> str:
    text = SPEC.read_text(encoding="utf-8")
    return text.split("### 14.11 The audit log", 1)[1].split("### 14.12", 1)[0]


def _lines(directory: Path) -> list[dict[str, Any]]:
    path = directory / audit.AUDIT_FILE
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_the_field_set_and_the_action_enum_are_the_spec_s() -> None:
    section = _section()
    fields_part = section.split("A closed field set:", 1)[1].split("Never a password", 1)[0]
    named = re.findall(r"`([a-z_.]+)`", fields_part)
    assert set(audit.FIELDS) == {"ts", "actor", "actor_name", "address", "action", "target", "detail", "result", "ref"}
    assert set(audit.FIELDS) <= set(named)
    actions_part = section.split("`action` (one of", 1)[1].split(");", 1)[0]
    assert audit.ACTIONS == set(re.findall(r"`([a-z_]+\.[a-z_]+)`", actions_part))
    assert audit.RESULTS == {"started", "ok", "refused", "error"}


@pytest.mark.parametrize(
    "change",
    [
        {"password": "x"},
        {"action": "account.rate_content"},
        {"result": "maybe"},
        {"actor": "alice"},
        {"ref": "nothex!!"},
        {"detail": {"nested": {"too": {"deep": 1}}}},
        {"detail": "not a mapping"},
        {"target": "x" * 201},
        {"ts": True},
    ],
)
def test_a_row_outside_the_closed_set_is_refused(change: dict[str, Any], tmp_path: Path) -> None:
    row = {
        "ts": time.time(),
        "actor": "cli",
        "actor_name": "cli",
        "address": "",
        "action": "account.create",
        "target": "",
        "detail": {},
        "result": "ok",
        "ref": "0123abcd",
    }
    row.update(change)
    with pytest.raises(audit.AuditRowError):
        audit.check_row(row)


def test_the_write_first_pair_shares_a_ref(tmp_path: Path) -> None:
    with audit.audited("account.disable", "u_000000000001", actor=ACTOR, directory=tmp_path) as ticket:
        ticket.detail["purge"] = False
    with pytest.raises(ValueError):
        with audit.audited(
            "account.set_admin", "u_000000000002", actor=ACTOR, refusals=(ValueError,), directory=tmp_path
        ):
            raise ValueError("a guard")
    with pytest.raises(RuntimeError):
        with audit.audited("account.enable", "u_000000000003", actor=ACTOR, directory=tmp_path):
            raise RuntimeError("it broke")
    audit.refused("account.create", actor=ACTOR, detail={"name": "x"}, directory=tmp_path)
    rows = _lines(tmp_path)
    assert [(r["action"], r["result"]) for r in rows] == [
        ("account.disable", "started"),
        ("account.disable", "ok"),
        ("account.set_admin", "started"),
        ("account.set_admin", "refused"),
        ("account.enable", "started"),
        ("account.enable", "error"),
        ("account.create", "refused"),
    ]
    for first, second in ((0, 1), (2, 3), (4, 5)):
        assert rows[first]["ref"] == rows[second]["ref"]
    assert len({r["ref"] for r in rows}) == 4
    assert rows[1]["detail"] == {"purge": False}
    assert list(rows[0]) == list(audit.FIELDS)
    assert rows[0]["actor"] == ACTOR.id and rows[0]["address"] == "127.0.0.1"
    # Newest first, filtered, a page at a time.
    assert [r["result"] for r in audit.read_recent(2, directory=tmp_path)] == ["refused", "error"]
    assert [r["action"] for r in audit.read_recent(10, 1, action="account.disable", directory=tmp_path)] == [
        "account.disable"
    ]
    assert audit.read_recent(10, actor="cli", directory=tmp_path) == []


def test_an_action_whose_started_row_cannot_be_written_never_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ran: list[str] = []

    def full_disk(_directory: Any, _line: bytes) -> None:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(audit, "_write_line", full_disk)
    with pytest.raises(audit.AuditUnavailable):
        with audit.audited("account.disable", "u_000000000001", actor=ACTOR, directory=tmp_path):
            ran.append("ran")
    assert ran == []
    assert audit.refused("account.create", actor=ACTOR, directory=tmp_path) is None


def test_two_processes_appending_at_once_land_every_line_whole(tmp_path: Path) -> None:
    count = 150
    directory = tmp_path / "hosting"
    directory.mkdir()
    children: list[subprocess.Popen[str]] = []
    try:
        for label in ("left", "right"):
            children.append(
                subprocess.Popen(
                    [sys.executable, str(PROBE), str(directory), str(count), label],
                    cwd=str(REPO),
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
            )
        time.sleep(0.5)  # both imported and waiting
        (directory / "go").write_text("go", encoding="utf-8")
        for child in children:
            _out, err = child.communicate(timeout=120)
            assert child.returncode == 0, err
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=10)
    raw = (directory / audit.AUDIT_FILE).read_text(encoding="utf-8")
    lines = raw.splitlines()
    assert raw.endswith("\n") and len(lines) == 2 * count
    rows = [audit.check_row(json.loads(line)) for line in lines]
    for label in ("left", "right"):
        mine = [r["detail"]["index"] for r in rows if r["detail"]["writer"] == label]
        assert mine == list(range(count)), f"{label}'s rows were lost or reordered"


def test_no_line_holds_a_password_hash_key_or_token(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A scripted run of every panel action, both re-auths and the CLI; then a scan."""
    import importlib
    import secrets as secrets_module

    cookie_key = secrets_module.token_urlsafe(32)
    door = AdminDoor(monkeypatch, tmp_path, env={"CLOCKWORK_SECRET_KEY": cookie_key})
    door.start()
    hashes: set[str] = set()
    passwords: list[str] = []
    try:
        client = door.admin()
        passwords.append(door.passwords["root"])

        def snapshot() -> None:
            for row in json.loads(door.accounts.path.read_text(encoding="utf-8"))["accounts"]:
                hashes.add(row["hash"])

        def post(url: str, **form: str) -> Any:
            answer = client.post(url, data={"csrf": door.token(client), **form})
            snapshot()
            return answer

        once = re.compile(r'<p class="secret"><code>([^<]+)</code></p>')
        assert post("/admin/users", name="bob").status_code == 303
        passwords.append(once.search(client.get("/admin/users/once").get_data(as_text=True)).group(1))
        bob = door.accounts.by_name("bob")
        assert post(f"/admin/users/{bob.id}/reset").status_code == 303
        passwords.append(once.search(client.get("/admin/users/once").get_data(as_text=True)).group(1))
        for action in ("disable", "enable", "grant-admin", "revoke-admin"):
            assert post(f"/admin/users/{bob.id}/{action}").status_code == 303, action
        post(f"/admin/users/{bob.id}/delete", mode="purge", confirm="bob")
        page = client.get("/admin/reauth")
        wrong = "not-the-password-" + secrets_module.token_hex(4)
        passwords.append(wrong)
        assert client.post(
            "/admin/reauth", data={"csrf": csrf_of(page.get_data(as_text=True)), "password": wrong}
        ).status_code == 401
        # The CLI, on the same storage root.
        cli = importlib.import_module("scripts.users")
        typed = "pw-" + secrets_module.token_urlsafe(12)
        passwords.append(typed)
        answers = iter([typed, typed])
        monkeypatch.setattr(cli.getpass, "getpass", lambda _prompt="": next(answers))
        assert cli.main(["add", "carol", "--admin"]) == 0
        snapshot()
        text = (door.data_dir / "hosting" / audit.AUDIT_FILE).read_text(encoding="utf-8")
        actions = {row["action"] for row in map(json.loads, text.splitlines())}
        assert {
            "account.create",
            "account.reset_password",
            "account.disable",
            "account.enable",
            "account.set_admin",
            "account.delete",
            "admin.reauth",
            "admin.reauth_failed",
        } <= actions
        forbidden = {
            "the cookie key": cookie_key,
            "the proxy token": door.proxy_token,
            "the bus token": door.bus_token,
            "scrypt": "scrypt:",
        }
        forbidden.update({f"password {i}": p for i, p in enumerate(passwords)})
        forbidden.update({f"hash {i}": h for i, h in enumerate(sorted(hashes))})
        leaks = [label for label, value in forbidden.items() if value and value in text]
        assert not leaks, leaks
    finally:
        door.stop()


def test_a_supervisor_holding_a_story_down_writes_story_held_down(tmp_path: Path) -> None:
    """
    A fresh instance (it must crash-loop from its first start): one fake
    worker that exits at once, max_restarts 2, so it is held down after its
    third crash. The supervisor writes the row, as the actor supervisor.
    """
    slug = "dev-story"
    instance = HostingInstance(
        tmp_path,
        stories=[slug],
        modes={f"worker-{slug}": "exit_now"},
        frontdoor=False,
        wait_ready=False,
    )
    instance.start()
    try:
        instance.wait_for(rf"worker-{slug} held down: .* after 2 crash restarts", timeout=60)
        path = instance.data_dir / "hosting" / audit.AUDIT_FILE
        rows = instance.until(
            lambda: path.is_file() and [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()],
            15,
            "the audit row",
        )
    finally:
        instance.stop()
    (row,) = [r for r in rows if r["action"] == "story.held_down"]
    assert (row["actor"], row["actor_name"], row["address"]) == ("supervisor", "supervisor", "")
    assert row["target"] == slug and row["result"] == "ok"
    assert row["detail"] == {"crash_restarts": 2, "window_minutes": 10}
    audit.check_row(row)


# -- fix round 1: rotation, a bounded tail, the supervisor's writer -----------------------------


def _append(directory: Path, count: int, start: int = 0) -> None:
    for index in range(start, start + count):
        audit.append(
            "account.enable",
            actor=ACTOR,
            result=audit.OK,
            target="u_000000000001",
            detail={"index": index},
            directory=directory,
        )


def test_the_log_rotates_by_size_and_keeps_audit_keep_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """M4: past audit_max_mb the file becomes .1 (the rest shift up); the oldest beyond audit_keep goes."""
    _append(tmp_path, 1)
    line = len((tmp_path / audit.AUDIT_FILE).read_bytes())
    monkeypatch.setattr(audit, "rotation", lambda: (line * 10, 2))
    _append(tmp_path, 59, start=1)
    names = sorted(p.name for p in tmp_path.iterdir() if p.name.startswith(audit.AUDIT_FILE) and not p.name.endswith(".lock"))
    assert names == ["audit.jsonl", "audit.jsonl.1", "audit.jsonl.2"], names
    for index in range(3):
        assert audit.rotated_path(tmp_path, index).stat().st_size <= line * 10
    on_disk = sum(
        len(audit.rotated_path(tmp_path, index).read_bytes().splitlines()) for index in range(3)
    )
    kept = [row["detail"]["index"] for row in audit.read_recent(1000, directory=tmp_path)]
    assert kept == list(range(59, 59 - on_disk, -1)), "newest first, across the files, none lost"
    assert 20 <= on_disk < 60, "the oldest files were deleted"
    newest = audit.read_recent(12, directory=tmp_path)
    assert [row["detail"]["index"] for row in newest] == kept[:12]


def test_the_rotation_keys_ship_and_reach_the_writer(monkeypatch: pytest.MonkeyPatch) -> None:
    import yaml

    from engine.hosting.config import validate
    from tests.test_hosting_config import DEFAULT

    settings = validate(yaml.safe_load(DEFAULT.read_text(encoding="utf-8"))["hosting"])
    assert (settings.audit_max_mb, settings.audit_keep) == (20, 10)
    assert audit.rotation() == (20 * 1024 * 1024, 10)


def test_the_audit_page_reads_only_a_bounded_tail(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    M4: on 75791db read_recent read and parsed the whole file for every
    page. Now it reads backwards in blocks and stops at offset + n rows,
    goes back at most AUDIT_MAX_ROWS, and reads at most MAX_SCAN_BYTES.
    """
    row = {
        "ts": 1.0,
        "actor": "cli",
        "actor_name": "cli",
        "address": "",
        "action": "account.enable",
        "target": "u_000000000001",
        "detail": {},
        "result": "ok",
        "ref": "0123abcd",
    }
    oldest = dict(row, action="account.create")
    lines = [json.dumps(oldest)] + [json.dumps(dict(row, detail={"index": i})) for i in range(30_000)]
    (tmp_path / audit.AUDIT_FILE).write_text("\n".join(lines) + "\n", encoding="utf-8")
    size = (tmp_path / audit.AUDIT_FILE).stat().st_size
    assert size > 2_000_000
    opened: list[int] = []
    real = audit._lines_backwards

    def counting(path: Path, budget: list[int]) -> Any:
        before = budget[0]
        yield from real(path, budget)
        opened.append(before - budget[0])

    monkeypatch.setattr(audit, "_lines_backwards", counting)
    newest = audit.read_recent(5, directory=tmp_path)
    assert [r["detail"]["index"] for r in newest] == [29999, 29998, 29997, 29996, 29995]
    assert audit.read_recent(10, offset=10**6, directory=tmp_path) == []
    # A filter matching only the oldest row, under a small scan budget: not
    # found, never the whole file, and said to be unsearched (fix round 2, N4).
    monkeypatch.setattr(audit, "FILTER_SCAN_BYTES", 256 * 1024)
    opened.clear()
    rows, unsearched = audit.read_tail(5, action="account.create", directory=tmp_path)
    assert rows == [] and unsearched
    assert opened and max(opened) <= 256 * 1024 + 64 * 1024 < size
    # Unfiltered, the newest page is read without exhausting anything.
    assert audit.read_tail(5, directory=tmp_path)[1] is False
    # With a budget past the whole file, the filter finds the row and nothing is unsearched.
    monkeypatch.setattr(audit, "FILTER_SCAN_BYTES", size + 1)
    rows, unsearched = audit.read_tail(5, action="account.create", directory=tmp_path)
    assert [r["action"] for r in rows] == ["account.create"] and unsearched is False


def test_a_rotation_shifts_first_and_a_blocked_move_leaves_no_gap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Fix round 2, N2: on ab77837 the oldest file was deleted before the
    shifts, so a shift a reader blocked (Windows) left a gap -- and the
    reader stopped at the gap. Now the moves run oldest first, a blocked one
    undoes those made, and the overflow is deleted only after all went.
    """
    _append(tmp_path, 1)
    line = len((tmp_path / audit.AUDIT_FILE).read_bytes())
    monkeypatch.setattr(audit, "rotation", lambda: (line * 3, 3))
    _append(tmp_path, 11, start=1)  # current + .1 .2 .3
    before = {index: audit.rotated_path(tmp_path, index).read_bytes() for index in range(4)}
    real = audit._replace

    def blocked(source: Path, target: Path) -> bool:
        if source.name == audit.AUDIT_FILE:  # the last move, current -> .1, is held by a reader
            return False
        return real(source, target)

    monkeypatch.setattr(audit, "_replace", blocked)
    _append(tmp_path, 1, start=100)
    for index in range(1, 4):
        assert audit.rotated_path(tmp_path, index).read_bytes() == before[index], f".{index} moved or lost"
    assert not audit.rotated_path(tmp_path, 4).exists()
    assert (tmp_path / audit.AUDIT_FILE).read_bytes().startswith(before[0]), "the append went on"
    monkeypatch.setattr(audit, "_replace", real)
    _append(tmp_path, 1, start=101)  # the next append rotates for real
    assert not audit.rotated_path(tmp_path, 4).exists()
    kept = [r["detail"]["index"] for r in audit.read_recent(1000, directory=tmp_path)]
    assert kept[0] == 101 and len(kept) == len(set(kept))
    # A gap in the chain (a file an operator moved away) does not stop the reader.
    audit.rotated_path(tmp_path, 2).unlink()
    assert [r["detail"]["index"] for r in audit.read_recent(1000, directory=tmp_path)][-1] == kept[-1]


def test_a_reader_racing_a_rotation_returns_no_duplicates(tmp_path: Path) -> None:
    """
    Fix round 2, N3: a rotation between the reader's current file and .1
    renames the file just read to .1, which the reader then reads again.
    Seen here as the state it leaves: .1 a copy of what was current.
    """
    _append(tmp_path, 6)
    current = tmp_path / audit.AUDIT_FILE
    audit.rotated_path(tmp_path, 1).write_bytes(current.read_bytes())
    rows = audit.read_recent(100, directory=tmp_path)
    assert [r["detail"]["index"] for r in rows] == [5, 4, 3, 2, 1, 0]


def test_the_audit_page_says_older_rows_were_not_searched(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Fix round 2, N4: a filtered view that ran out of its byte budget says so."""
    door = AdminDoor(monkeypatch, tmp_path)
    door.start()
    try:
        client = door.admin()
        for _ in range(600):  # well past one 64 KiB block
            audit.append("account.enable", actor=ACTOR, result=audit.OK, target="u_000000000001")
        assert "not searched" not in client.get("/admin/audit?action=account.create").get_data(as_text=True)
        monkeypatch.setattr(audit, "FILTER_SCAN_BYTES", 1024)
        page = client.get("/admin/audit?action=account.create").get_data(as_text=True)
        assert "Older rows not searched" in page
        assert "not searched" not in client.get("/admin/audit").get_data(as_text=True)
    finally:
        door.stop()


def test_the_held_down_row_goes_where_the_storage_root_pointed_when_it_was_queued(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Fix round 2, N1: the row's directory is resolved on the QUEUING thread.
    On ab77837 the writer thread resolved it when it ran, so a storage root
    redirected meanwhile -- in the suite, a test's redirect undone at its
    teardown, falling back to the owner's real data/ -- received the row.
    Here the writer is held behind a gate while CLOCKWORK_DATA_DIR moves to
    another temp directory; the row must land in the first.
    """
    import copy

    import yaml

    from engine.hosting.config import validate
    from engine.hosting.supervisor.logs import LogHub
    from engine.hosting.supervisor.server import Supervisor
    from tests.test_hosting_config import DEFAULT

    first, second = tmp_path / "first", tmp_path / "second"
    monkeypatch.setenv("CLOCKWORK_DATA_DIR", str(first))
    block = copy.deepcopy(yaml.safe_load(DEFAULT.read_text(encoding="utf-8"))["hosting"])
    block.update({"enabled": True, "stories": ["dev-story"]})
    hub = LogHub(tmp_path / "logs", max_mb=1, keep=2, echo=None)
    sup = Supervisor(validate(block), hub=hub)
    gate = threading.Event()
    try:
        sup._audit_writer.submit(lambda: gate.wait(15))  # the writer, busy
        child = sup.children[0]
        child.crashes.extend([time.monotonic()] * sup.settings.max_restarts)
        with sup._lock:
            sup._apply_policy(child, "a test crash")
        sup._flush_said()
        monkeypatch.setenv("CLOCKWORK_DATA_DIR", str(second))
        gate.set()
        sup._audit_writer.close(timeout=10)
    finally:
        gate.set()
        sup._audit_writer.close(timeout=10)
        sup.ops.close()
        sup._health.shutdown(wait=False)
        sup._reaper.shutdown(wait=False)
        hub.close()
    assert not (second / "hosting" / audit.AUDIT_FILE).exists(), "the row followed the moved storage root"
    (row,) = _lines(first / "hosting")
    assert row["action"] == "story.held_down"


def test_a_bus_handler_never_waits_on_the_audit_lock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    M6: the supervisor's held-down row used to be written by whichever
    thread flushed next -- a bus handler among them -- which then waited on
    the audit lock (up to 5 s) and an fsync. Now the flush hands it to the
    audit writer's own thread and returns at once; the row lands once the
    lock is free.
    """
    import copy

    import yaml

    from engine.hosting.accounts import open_private, try_lock, unlock
    from engine.hosting.config import validate
    from engine.hosting.supervisor.logs import LogHub
    from engine.hosting.supervisor.server import Supervisor
    from tests.test_hosting_config import DEFAULT

    data = tmp_path / "data"
    monkeypatch.setenv("CLOCKWORK_DATA_DIR", str(data))
    block = copy.deepcopy(yaml.safe_load(DEFAULT.read_text(encoding="utf-8"))["hosting"])
    block.update({"enabled": True, "stories": ["dev-story"]})
    hub = LogHub(tmp_path / "logs", max_mb=1, keep=2, echo=None)
    sup = Supervisor(validate(block), hub=hub)
    sup.server.start()
    hosting = data / "hosting"
    hosting.mkdir(parents=True)
    held = open_private(hosting / audit.AUDIT_LOCK)
    assert try_lock(held)
    try:
        child = sup.children[0]
        child.crashes.extend([time.monotonic()] * sup.settings.max_restarts)
        with sup._lock:
            sup._apply_policy(child, "a test crash")
        began = time.monotonic()
        sup._flush_said()
        took = time.monotonic() - began
        assert took < 0.5, f"the flush waited {took:.1f}s on the audit lock"
        assert not (hosting / audit.AUDIT_FILE).exists()
        assert any(t.name == "supervisor-audit" for t in threading.enumerate())
        unlock(held)
        deadline = time.monotonic() + 15
        path = hosting / audit.AUDIT_FILE
        while not path.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        (row,) = _lines(hosting)
        assert row["action"] == "story.held_down" and row["actor"] == "supervisor"
    finally:
        try:
            unlock(held)
        except OSError:
            pass
        os.close(held)
        sup.ops.close()
        sup._health.shutdown(wait=False)
        sup._reaper.shutdown(wait=False)
        sup._audit_writer.close(timeout=10)
        sup.server.close()
        hub.close()
    assert not any(t.name == "supervisor-audit" for t in threading.enumerate())
