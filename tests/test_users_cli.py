"""
``scripts/users.py``, the operator's account tool (v0.20.0 T7, spec §6.1).

Run over a ``tmp_path`` storage root with ``getpass`` stubbed: passwords come
from ``getpass``, twice, and never from argv or the environment.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator

import pytest

from engine.hosting.accounts import AccountStore
from tests.hosted_app import new_password


@pytest.fixture
def cli(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Any]:
    import importlib

    monkeypatch.setenv("CLOCKWORK_DATA_DIR", str(tmp_path / "data"))
    module = importlib.import_module("scripts.users")
    yield module


def _typed(monkeypatch: pytest.MonkeyPatch, cli: Any, *answers: str) -> list[str]:
    """Stub getpass with ``answers``; returns the prompts it was asked."""
    queue = list(answers)
    prompts: list[str] = []

    def fake(prompt: str = "") -> str:
        prompts.append(prompt)
        return queue.pop(0)

    monkeypatch.setattr(cli.getpass, "getpass", fake)
    return prompts


def _store(tmp_path: Path) -> AccountStore:
    return AccountStore(tmp_path / "data" / "hosting")


def test_add_reads_the_password_twice_through_getpass(
    cli: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    password = new_password()
    prompts = _typed(monkeypatch, cli, password, password)
    assert cli.main(["add", "alice"]) == 0
    assert len(prompts) == 2
    account = _store(tmp_path).by_name("alice")
    assert account is not None and _store(tmp_path).verify("alice", password) is not None
    out = capsys.readouterr().out
    assert account.id in out and password not in out


def test_a_mismatched_second_entry_changes_nothing(
    cli: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _typed(monkeypatch, cli, new_password(), new_password())
    assert cli.main(["add", "alice"]) == 1
    assert "differ" in capsys.readouterr().err
    assert _store(tmp_path).by_name("alice") is None


def test_a_short_password_is_refused(
    cli: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _typed(monkeypatch, cli, "short", "short")
    assert cli.main(["add", "alice"]) == 1
    assert _store(tmp_path).by_name("alice") is None


def test_no_password_is_taken_from_argv_or_the_environment(
    cli: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # No option accepts a password on the command line.
    with pytest.raises(SystemExit):
        cli.main(["add", "alice", "--password", new_password()])
    for sub, extra in (("add", {"admin"}), ("passwd", set())):
        parser = cli._build_parser()
        actions = parser._subparsers._group_actions[0].choices[sub]._actions
        assert {a.dest for a in actions} == {"help", "name"} | extra
    assert next(
        a for a in cli._build_parser()._subparsers._group_actions[0].choices["add"]._actions if a.dest == "admin"
    ).nargs == 0, "--admin is a flag, never a value"
    # The environment is never read for one: the typed one wins over any variable.
    planted = new_password()
    for name in ("PASSWORD", "CLOCKWORK_PASSWORD", "USERS_PASSWORD"):
        monkeypatch.setenv(name, planted)
    typed = new_password()
    _typed(monkeypatch, cli, typed, typed)
    assert cli.main(["add", "alice"]) == 0
    store = _store(tmp_path)
    assert store.verify("alice", typed) is not None
    assert store.verify("alice", planted) is None


def test_passwd_disable_enable_list_and_the_epoch(
    cli: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    first = new_password()
    _typed(monkeypatch, cli, first, first)
    cli.main(["add", "alice"])
    second = new_password()
    _typed(monkeypatch, cli, second, second)
    assert cli.main(["passwd", "alice"]) == 0
    store = _store(tmp_path)
    assert store.verify("alice", second) is not None and store.by_name("alice").epoch == 2
    assert cli.main(["disable", "alice"]) == 0
    assert store.by_name("alice").disabled and store.by_name("alice").epoch == 3
    capsys.readouterr()
    assert cli.main(["list"]) == 0
    listed = capsys.readouterr().out
    assert "alice" in listed and "disabled" in listed
    assert cli.main(["enable", "alice"]) == 0
    assert not store.by_name("alice").disabled
    listing = capsys.readouterr().out
    assert second not in listing and "scrypt" not in listing
    assert cli.main(["passwd", "nobody"]) == 1


def test_remove_keeps_the_saves_and_purge_asks_first(
    cli: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    for name in ("alice", "bob"):
        password = new_password()
        _typed(monkeypatch, cli, password, password)
        cli.main(["add", name])
    store = _store(tmp_path)
    alice, bob = store.by_name("alice"), store.by_name("bob")
    for account in (alice, bob):
        saves = tmp_path / "data" / "users" / account.id / "saves" / "clockwork-dark" / "abc123"
        saves.mkdir(parents=True)
        (saves / "save.json").write_text("{}", encoding="utf-8")

    assert cli.main(["remove", "alice"]) == 0
    assert store.by_name("alice") is None
    assert (tmp_path / "data" / "users" / alice.id).is_dir(), "remove without --purge deleted saves"

    monkeypatch.setattr("builtins.input", lambda _prompt="": "not bob")
    assert cli.main(["remove", "bob", "--purge"]) == 1
    assert store.by_name("bob") is not None and (tmp_path / "data" / "users" / bob.id).is_dir()
    monkeypatch.setattr("builtins.input", lambda _prompt="": "bob")
    assert cli.main(["remove", "bob", "--purge"]) == 0
    assert store.by_name("bob") is None
    assert not (tmp_path / "data" / "users" / bob.id).exists()


def test_adopt_moves_one_story_s_runs(
    cli: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from engine.persistence import saves

    password = new_password()
    _typed(monkeypatch, cli, password, password)
    cli.main(["add", "alice"])
    run = saves.saves_base() / "clockwork-dark" / "abc123def456"
    run.mkdir(parents=True)
    (run / "save.json").write_text(
        json.dumps({"save_id": "abc123def456", "state": {"turn_number": 1}}), encoding="utf-8"
    )
    assert cli.main(["adopt", "alice", "--game", "clockwork-dark"]) == 0
    alice = _store(tmp_path).by_name("alice")
    assert not run.exists()
    moved = tmp_path / "data" / "users" / alice.id / "saves" / "clockwork-dark" / "abc123def456"
    assert (moved / "save.json").is_file()
    assert cli.main(["adopt", "nobody"]) == 1


def test_adopt_while_a_server_runs_is_a_clean_refusal(
    cli: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    import os

    from engine.hosting.accounts import hold_server_lock

    password = new_password()
    _typed(monkeypatch, cli, password, password)
    cli.main(["add", "alice"])
    fd = hold_server_lock(tmp_path / "data" / "hosting")
    try:
        capsys.readouterr()
        assert cli.main(["adopt", "alice"]) == 1
        err = capsys.readouterr().err
        assert "hosted server is running" in err and "Traceback" not in err
    finally:
        os.close(fd)


# -- the admin role and the audit rows (v0.20.0 T14, spec §6.1, §14.6, §14.11) --------


def _audit_rows(tmp_path: Path) -> list[dict[str, Any]]:
    path = tmp_path / "data" / "hosting" / "audit.jsonl"
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _add(cli: Any, monkeypatch: pytest.MonkeyPatch, name: str, *flags: str) -> str:
    password = new_password()
    _typed(monkeypatch, cli, password, password)
    assert cli.main(["add", name, *flags]) == 0
    return password


def test_add_admin_makes_the_first_admin_and_admin_on_off_changes_the_role(
    cli: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _add(cli, monkeypatch, "root", "--admin")
    _add(cli, monkeypatch, "alice")
    store = _store(tmp_path)
    assert store.by_name("root").admin and not store.by_name("alice").admin
    assert not store.by_name("root").must_change, "an operator typed this password: nothing to change"
    epoch = store.by_name("alice").epoch
    assert cli.main(["admin", "alice", "on"]) == 0
    assert store.by_name("alice").admin and store.by_name("alice").epoch == epoch + 1
    capsys.readouterr()
    assert cli.main(["list"]) == 0
    listing = capsys.readouterr().out
    assert "root" in listing and "admin" in listing
    assert cli.main(["admin", "alice", "off"]) == 0
    assert not store.by_name("alice").admin and store.by_name("alice").epoch == epoch + 2
    assert cli.main(["admin", "nobody", "on"]) == 1


def test_revoking_the_last_admin_asks_on_the_terminal_first(
    cli: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _add(cli, monkeypatch, "root", "--admin")
    store = _store(tmp_path)
    for command in (["admin", "root", "off"], ["disable", "root"], ["remove", "root"]):
        monkeypatch.setattr("builtins.input", lambda _prompt="": "no")
        assert cli.main(command) == 1, command
        assert store.by_name("root") is not None and store.by_name("root").admin
        assert not store.by_name("root").disabled
    monkeypatch.setattr("builtins.input", lambda _prompt="": "root")
    assert cli.main(["admin", "root", "off"]) == 0
    assert not store.by_name("root").admin
    capsys.readouterr()
    assert cli.main(["list"]) == 0
    assert "No enabled admin" in capsys.readouterr().out


def test_passwd_clears_a_password_an_admin_generated(
    cli: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    store = _store(tmp_path)
    _account, _once = store.create_with_generated_password("alice")
    assert store.by_name("alice").must_change
    _typed(monkeypatch, cli, "x" * 12, "x" * 12)
    assert cli.main(["passwd", "alice"]) == 0
    assert not store.by_name("alice").must_change


def test_every_change_is_audited_as_cli_write_first(
    cli: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    first = _add(cli, monkeypatch, "root", "--admin")
    _add(cli, monkeypatch, "alice")
    alice = _store(tmp_path).by_name("alice")
    second = new_password()
    _typed(monkeypatch, cli, second, second)
    assert cli.main(["passwd", "alice"]) == 0
    for command in (["admin", "alice", "on"], ["admin", "alice", "off"], ["disable", "alice"], ["enable", "alice"]):
        assert cli.main(command) == 0, command
    assert cli.main(["remove", "alice"]) == 0
    rows = _audit_rows(tmp_path)
    assert {row["actor"] for row in rows} == {"cli"} and {row["actor_name"] for row in rows} == {"cli"}
    assert [(row["action"], row["result"]) for row in rows] == [
        (action, result)
        for action in (
            "account.create",
            "account.create",
            "account.passwd",
            "account.set_admin",
            "account.set_admin",
            "account.disable",
            "account.enable",
            "account.delete",
        )
        for result in ("started", "ok")
    ]
    for started, outcome in zip(rows[::2], rows[1::2]):
        assert started["ref"] == outcome["ref"]
    assert rows[3]["target"] == alice.id and rows[2]["target"] == ""
    assert rows[-1]["detail"] == {"purge": False}
    text = (tmp_path / "data" / "hosting" / "audit.jsonl").read_text(encoding="utf-8")
    assert first not in text and second not in text and "scrypt" not in text


def test_a_change_whose_audit_row_cannot_be_written_is_refused(
    cli: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from engine.hosting import audit

    _add(cli, monkeypatch, "alice")
    before = (tmp_path / "data" / "hosting" / "users.json").read_bytes()

    def full_disk(_directory: Any, _line: bytes) -> None:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(audit, "_write_line", full_disk)
    capsys.readouterr()
    for command in (["disable", "alice"], ["admin", "alice", "on"], ["remove", "alice"]):
        assert cli.main(command) == 1, command
        assert "audit log cannot be written" in capsys.readouterr().err
    _typed(monkeypatch, cli, "y" * 12, "y" * 12)
    assert cli.main(["add", "bob"]) == 1
    assert (tmp_path / "data" / "hosting" / "users.json").read_bytes() == before
