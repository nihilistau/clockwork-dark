"""
The admin panel's Saves page (v0.20.0 T15, spec §14.8, §14.10).

Each account's saves, per story, read straight from each store's
``index.json`` through ONE allowlisted projection: the save id, its kind
(``auto`` or ``manual``, never a manual slot's label), the turn, when it was
written, its save format and its size on disk. Never the player's name,
archetype, place, phase, the story's ``values``, a thumbnail, a
``save.json`` or a transcript -- the page opens no file but an index. A
missing or malformed index is an empty row set, not an error page.

In this process (``tests/hosting_instance.py::AdminDoor``: the engine's front
door, no worker needed -- the page reads storage, not the bus).
"""

from __future__ import annotations

import builtins
import io
import json
import os
from pathlib import Path
from typing import Any, Iterator

import pytest

from tests.hosting_instance import AdminDoor

A = "clockwork-dark"
B = "dev-story"

#: What a player wrote, and what the state holds: none of it may be shown.
MARKERS = ("Q9SAVEID", "Q9LABEL", "Q9PLAYER", "Q9ARCH", "Q9PLACE", "Q9VALUE", "Q9THUMB", "Q9NARRATION", "Q9STATE")


@pytest.fixture
def door(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[AdminDoor]:
    instance = AdminDoor(monkeypatch, tmp_path, hosting={"stories": [A, B]})
    instance.start()
    try:
        yield instance
    finally:
        instance.stop()


def _store(door: AdminDoor, account_id: str, slug: str) -> Path:
    from engine.persistence.storage import saves_dir

    folder = saves_dir(account_id, slug)
    assert str(folder).startswith(str(door.tmp_path)), folder
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _write_run(folder: Path, save_id: str, slot: str, turn: int, updated: float) -> dict[str, Any]:
    """A save folder with its files (contents the page must never read) and its index row."""
    run = folder / save_id
    run.mkdir()
    (run / "save.json").write_text(json.dumps({"state": {"player_name": "Q9STATE"}}), encoding="utf-8")
    (run / "transcript.jsonl").write_text(json.dumps({"narration": "Q9NARRATION"}) + "\n", encoding="utf-8")
    (run / "memory.json").write_text("{}", encoding="utf-8")
    return {
        "save_id": save_id,
        "slot": slot,
        "player_name": "Q9PLAYER",
        "archetype": "Q9ARCH",
        "world_day": 4,
        "world_hour": 9,
        "location_id": "Q9PLACE",
        "evil_phase": "stirring",
        "turn_number": turn,
        "updated_at": updated,
        "save_version": 7,
        "thumbnail": "Q9THUMB.png",
        "values": {"coin": {"label": "Q9VALUE", "value": 3}},
        "created_at": updated - 60,
    }


def _index(folder: Path, rows: list[dict[str, Any]]) -> None:
    (folder / "index.json").write_text(json.dumps({"saves": rows}), encoding="utf-8")


def _expected_size(run: Path) -> int:
    return sum(p.stat().st_size for p in run.iterdir() if p.is_file())


def test_the_projection_is_the_allowlist_and_nothing_else(door: AdminDoor) -> None:
    from engine.hosting.admin.saves import SAVE_KEYS, read_index
    from engine.hosting.admin.sessions import save_ref

    assert SAVE_KEYS == ("save_ref", "kind", "turn_number", "updated_at", "save_version", "size")
    player = door.add("wren")
    folder = _store(door, player.id, A)
    rows = [
        # A save id the player chose (POST /api/saves takes one): player text.
        _write_run(folder, "Q9SAVEID-my-ford", "Q9LABEL-by-the-ford", 12, 1_800_000_100.0),
        _write_run(folder, "bbbb2222", "auto", 15, 1_800_000_200.0),
    ]
    _index(folder, rows)
    projected = read_index(folder)
    assert [set(row) for row in projected] == [set(SAVE_KEYS)] * 2
    assert projected == [
        {
            "save_ref": save_ref("bbbb2222"),
            "kind": "auto",
            "turn_number": 15,
            "updated_at": 1_800_000_200.0,
            "save_version": 7,
            "size": _expected_size(folder / "bbbb2222"),
        },
        {
            "save_ref": save_ref("Q9SAVEID-my-ford"),
            "kind": "manual",
            "turn_number": 12,
            "updated_at": 1_800_000_100.0,
            "save_version": 7,
            "size": _expected_size(folder / "Q9SAVEID-my-ford"),
        },
    ]
    assert save_ref("bbbb2222") == save_ref("bbbb2222") != save_ref("bbbb2223") and len(save_ref("x")) == 10
    # Keyed (fix round 2, N5): not the plain SHA-256 a dictionary could reverse.
    import hashlib

    assert save_ref("Q9SAVEID-my-ford") != hashlib.sha256(b"Q9SAVEID-my-ford").hexdigest()[:10]

    client = door.admin()
    page = client.get("/admin/saves")
    assert page.status_code == 200
    text = page.get_data(as_text=True)
    assert save_ref("Q9SAVEID-my-ford") in text and save_ref("bbbb2222") in text
    assert "manual" in text and ">auto<" in text
    assert "bbbb2222" not in text and "Q9SAVEID" not in text
    assert "wren" in text and player.id in text
    for marker in MARKERS:
        assert marker not in text, marker
    assert "style=" not in text and "<script>" not in text


def test_the_page_opens_no_save_and_no_transcript(door: AdminDoor) -> None:
    """Every file open while the page is served is recorded: an index, never a save's own files."""
    player = door.add("moss")
    for slug in (A, B):
        folder = _store(door, player.id, slug)
        _index(folder, [_write_run(folder, f"run{slug[:3]}", "auto", 2, 1_800_000_000.0)])
    client = door.admin()
    opened: list[str] = []
    real_open, real_os_open = builtins.open, os.open

    def spy_open(file: Any, *args: Any, **kwargs: Any) -> Any:
        opened.append(os.fspath(file) if not isinstance(file, int) else "")
        return real_open(file, *args, **kwargs)

    def spy_os_open(path: Any, *args: Any, **kwargs: Any) -> Any:
        opened.append(os.fspath(path))
        return real_os_open(path, *args, **kwargs)

    with pytest.MonkeyPatch.context() as spy:  # its own, so only the spies are undone
        spy.setattr(builtins, "open", spy_open)
        spy.setattr(io, "open", spy_open)
        spy.setattr(os, "open", spy_os_open)
        page = client.get("/admin/saves")
    assert page.status_code == 200
    names = [Path(p).name for p in opened if p]
    assert names.count("index.json") == 2, names
    assert not [n for n in names if n in ("save.json", "transcript.jsonl", "memory.json")], names
    from engine.hosting.admin.sessions import save_ref

    assert save_ref("runclo") in page.get_data(as_text=True) and save_ref("rundev") in page.get_data(as_text=True)


@pytest.mark.parametrize(
    "content",
    [None, b"", b"{not json", b"\xff\xfe\x00", b"[1, 2, 3]", b'{"saves": "nope"}', b'{"saves": [{"save_id": "../x"}, 7]}'],
    ids=["missing", "empty", "malformed", "not utf-8", "a list", "saves not a list", "no valid row"],
)
def test_a_missing_or_malformed_index_is_no_rows_not_an_error(door: AdminDoor, content: Any) -> None:
    from engine.hosting.admin.saves import read_index

    player = door.add("fern")
    folder = _store(door, player.id, A)
    if content is not None:
        (folder / "index.json").write_bytes(content)
    assert read_index(folder) == []
    page = door.admin().get("/admin/saves")
    assert page.status_code == 200
    text = page.get_data(as_text=True)
    assert "fern" in text and "No saves." in text


def test_accounts_come_a_page_at_a_time(door: AdminDoor) -> None:
    from engine.hosting.admin.saves import ACCOUNTS_PER_PAGE

    for number in range(ACCOUNTS_PER_PAGE + 1):
        door.add(f"player-{number:02d}")
    client = door.admin()  # "root": the 22nd account, sorted after the players
    first = client.get("/admin/saves").get_data(as_text=True)
    second = client.get("/admin/saves?page=2").get_data(as_text=True)
    assert "player-00" in first and "player-19" in first and "player-20" not in first
    assert 'href="/admin/saves?page=2"' in first
    assert "player-20" in second and "root" in second and "player-00" not in second
