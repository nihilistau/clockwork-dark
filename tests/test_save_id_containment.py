"""
A save id is a name, never a path (v0.20.0 T2; spec survey finding 1, §4.3).

THE DEFECT. ``SaveStore._dir`` was ``self.root / save_id``, and every door
handed it whatever it was given: ``POST /api/saves``'s body,
``/api/saves/<id>/load``, ``DELETE /api/saves/<id>`` and the socket's
``resume``. Flask's default converter stops ``/`` but not ``..``, ``.`` or
``%2e%2e``, and on Windows it passes ``..%5c..%5cx`` through as ``..\\..\\x``
and ``C:%5cx`` as ``C:\\x``. So a ``DELETE`` could unlink every plain file in
a directory the process could reach, ``DELETE /api/saves/.`` unlinked
``index.json``, and a ``POST`` wrote ``save.json`` anywhere.

THE FIX. ``saves.SAVE_ID_RE`` (``^[A-Za-z0-9_-]{1,64}$``) is checked in
``_dir``, so every store method refuses a bad id with ``ValueError``, and a
loaded envelope's ``session_id`` is held to the same pattern. Every door
answers a refused id exactly as it answers a missing save.

HOW A FAILING RUN STAYS HARMLESS. The store's root is put under this test's
``tmp_path`` before anything runs, and ``_dir`` is wrapped by a guard that
raises (an ``Escape``, which no door catches) whenever the store would touch a
path outside ``tmp_path``: on the unfixed code that is where ``C:\\x`` stops.
Everything else a bad id can reach, the store's parent and a sibling of the
root included, is inside ``tmp_path``, and the tree is compared before and
after every request.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Iterator

import pytest

from tests.local_golden import scripted_model

#: The spec's ids (§4.3), each as ``(label, url form, decoded form)``: the URL
#: form is sent raw in a route's path, and Flask decodes it to the second,
#: which is what the body, the socket and the store are given.
IDS: list[tuple[str, str, str]] = [
    ("dotdot-slash-x", "..%2fx", "../x"),
    ("dotdot", "..", ".."),
    ("dot", ".", "."),
    ("encoded-dotdot", "%2e%2e", ".."),
    ("backslash-dotdot", "..%5c..%5cx", "..\\..\\x"),
    ("drive", "C:%5cx", "C:\\x"),
    ("sixty-five", "a" * 65, "a" * 65),
    # Fix round 1 (review finding 3): Windows device names, any case. `NUL`
    # was a 500 on Windows; `con` saved as a directory no other checkout of
    # the save tree could hold. Refused on every OS, so saves stay portable.
    ("device-nul", "NUL", "NUL"),
    ("device-con", "con", "con"),
    ("device-com1", "Com1", "Com1"),
    ("device-lpt9", "lPt9", "lPt9"),
    ("device-aux", "AUX", "AUX"),
    ("device-prn", "prn", "prn"),
    ("trailing-dot", "x.", "x."),
    ("trailing-space", "x%20", "x "),
]

MISSING_ID = "abc123def456"


class Escape(Exception):
    """The store tried to touch a path outside the test's temp directory."""


def _tree(root: Path) -> dict[str, bytes]:
    """Every file under ``root``, relative, with its bytes."""
    return {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, Any]]:
    """
    The app, its save store rooted three directories deep in ``tmp_path``,
    a sentinel file beside the store's root, and the escape guard on ``_dir``.
    """
    from engine.persistence import saves

    base = tmp_path / "d1" / "d2" / "saves"
    base.mkdir(parents=True)
    monkeypatch.setattr(saves, "saves_base", lambda: base)
    saves.reset_save_store()

    real_dir = saves.SaveStore._dir
    tmp = os.path.normcase(os.path.abspath(tmp_path))

    def guarded(self: Any, save_id: str) -> Path:
        path = real_dir(self, save_id)
        full = os.path.normcase(os.path.abspath(path))
        if not (full == tmp or full.startswith(tmp + os.sep)):
            raise Escape(f"the store reached outside its temp directory: {path}")
        return path

    monkeypatch.setattr(saves.SaveStore, "_dir", guarded)

    from engine.scenes.default_scene import create_app

    scene, app = create_app(testing=True, llm_fn=scripted_model)
    client = app.test_client()
    new = client.post("/api/game/new", json={"player_name": "Tess"})
    assert new.status_code == 200, new.get_data(as_text=True)
    body = new.get_json()

    store = saves.get_save_store()
    assert store.root.parent == base
    sentinel = base / "sentinel.txt"
    sentinel.write_text("still here", encoding="utf-8")
    # Victims: a real run where ``../x`` and (on Windows) ``..\..\x`` land
    # from the store's root, so an unfixed DELETE has something to unlink and
    # an unfixed resume something to load. Written through a store rooted
    # elsewhere and copied, so no ``index.json`` appears in ``base``.
    import shutil

    from engine.game.state import GameState

    staging = tmp_path / "staging"
    saves.SaveStore(root=staging, slug=store.slug).save(GameState(), save_id="x")
    for victim in (base / "x", base.parent / "x"):
        shutil.copytree(staging / "x", victim)
    shutil.rmtree(staging)
    if not isinstance(body.get("save_id"), str) or not body["save_id"]:
        pytest.fail(f"no save was written for the new game: {body}")
    yield {
        "scene": scene,
        "app": app,
        "client": client,
        "session_id": body["session_id"],
        "save_id": body["save_id"],
        "store": store,
        "tmp": tmp_path,
        "sentinel": sentinel,
    }
    saves.reset_save_store()


def _unchanged(world: dict[str, Any], before: dict[str, bytes]) -> None:
    after = _tree(world["tmp"])
    assert world["sentinel"].read_text(encoding="utf-8") == "still here"
    created = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    changed = sorted(k for k in set(before) & set(after) if before[k] != after[k])
    assert not (created or removed or changed), {
        "created": created,
        "removed": removed,
        "changed": changed,
    }


# -- the HTTP doors -----------------------------------------------------------


@pytest.mark.parametrize(("label", "url_form", "decoded"), IDS, ids=[i[0] for i in IDS])
def test_post_saves_refuses_the_id_as_a_missing_save(
    world: dict[str, Any], label: str, url_form: str, decoded: str
) -> None:
    client = world["client"]
    missing = client.post(f"/api/saves/{MISSING_ID}/load")
    before = _tree(world["tmp"])
    res = client.post(
        "/api/saves", json={"session_id": world["session_id"], "save_id": decoded, "slot": "1"}
    )
    _unchanged(world, before)
    assert (res.status_code, res.get_json()) == (missing.status_code, missing.get_json())


def test_post_saves_refuses_an_absolute_path(world: dict[str, Any]) -> None:
    client = world["client"]
    target = world["tmp"] / "elsewhere"
    missing = client.post(f"/api/saves/{MISSING_ID}/load")
    before = _tree(world["tmp"])
    res = client.post(
        "/api/saves", json={"session_id": world["session_id"], "save_id": str(target)}
    )
    _unchanged(world, before)
    assert not target.exists()
    assert (res.status_code, res.get_json()) == (missing.status_code, missing.get_json())


@pytest.mark.parametrize(("label", "url_form", "decoded"), IDS, ids=[i[0] for i in IDS])
def test_load_refuses_the_id_as_a_missing_save(
    world: dict[str, Any], label: str, url_form: str, decoded: str
) -> None:
    client = world["client"]
    missing = client.post(f"/api/saves/{MISSING_ID}/load")
    assert missing.status_code == 404
    before = _tree(world["tmp"])
    res = client.post(f"/api/saves/{url_form}/load")
    _unchanged(world, before)
    assert res.status_code == 404
    if res.is_json:
        # The view was reached: its answer is the missing save's, exactly.
        assert res.get_json() == missing.get_json()


@pytest.mark.parametrize(("label", "url_form", "decoded"), IDS, ids=[i[0] for i in IDS])
def test_delete_refuses_the_id_as_a_missing_save(
    world: dict[str, Any], label: str, url_form: str, decoded: str
) -> None:
    client = world["client"]
    missing = client.delete(f"/api/saves/{MISSING_ID}")
    before = _tree(world["tmp"])
    res = client.delete(f"/api/saves/{url_form}")
    _unchanged(world, before)
    if res.is_json:
        assert (res.status_code, res.get_json()) == (missing.status_code, missing.get_json())
    else:
        # The router refused it before the view (a ``/`` in the id).
        assert res.status_code == 404


def test_the_url_doors_reach_the_view_for_the_windows_forms(world: dict[str, Any]) -> None:
    """
    The design review's probe: ``%5c`` is not a ``/``, so the router hands
    ``..\\..\\x`` and ``C:\\x`` to the view. Those are the ids that reached
    another directory on Windows, and they must be answered BY THE VIEW as a
    missing save (a router 404 would prove nothing about the store).
    """
    client = world["client"]
    for url_form in ("..%5c..%5cx", "C:%5cx", "%2e%2e"):
        res = client.post(f"/api/saves/{url_form}/load")
        assert res.is_json and res.status_code == 404, url_form
        res = client.delete(f"/api/saves/{url_form}")
        assert res.is_json, url_form


def test_the_url_doors_refuse_an_absolute_path(world: dict[str, Any]) -> None:
    from urllib.parse import quote

    client = world["client"]
    target = world["tmp"] / "elsewhere"
    target.mkdir()
    (target / "save.json").write_text("{}", encoding="utf-8")
    before = _tree(world["tmp"])
    quoted = quote(str(target), safe="")
    load = client.post(f"/api/saves/{quoted}/load")
    delete = client.delete(f"/api/saves/{quoted}")
    _unchanged(world, before)
    assert (target / "save.json").is_file()
    assert load.status_code == 404
    if delete.is_json:
        assert delete.get_json() == {"deleted": False}


# -- the socket's resume --------------------------------------------------------


def _resume(world: dict[str, Any], save_id: str) -> list[dict[str, Any]]:
    sio = world["scene"].socketio.test_client(world["app"])
    try:
        sio.get_received()
        sio.emit("resume", {"save_id": save_id})
        return sio.get_received()
    finally:
        sio.disconnect()


@pytest.mark.parametrize(("label", "url_form", "decoded"), IDS, ids=[i[0] for i in IDS])
def test_resume_refuses_the_id_as_a_missing_save(
    world: dict[str, Any], label: str, url_form: str, decoded: str
) -> None:
    missing = _resume(world, MISSING_ID)
    assert [e["name"] for e in missing] == ["resume_failed"]
    wording = missing[0]["args"][0]["message"].replace(MISSING_ID, "{id}")
    before = _tree(world["tmp"])
    got = _resume(world, decoded)
    _unchanged(world, before)
    assert [e["name"] for e in got] == ["resume_failed"]
    assert got[0]["args"][0] == {"message": wording.replace("{id}", decoded)}


def test_resume_refuses_an_absolute_path(world: dict[str, Any]) -> None:
    from engine.game.state import GameState
    from engine.persistence.saves import SaveStore

    # A real save, outside the store's root: resume must not load it.
    elsewhere = world["tmp"] / "elsewhere" / "clockwork-dark"
    SaveStore(root=elsewhere, slug="clockwork-dark").save(GameState(), save_id="real")
    before = _tree(world["tmp"])
    got = _resume(world, str(elsewhere / "real"))
    _unchanged(world, before)
    assert [e["name"] for e in got] == ["resume_failed"]


# -- the store itself -----------------------------------------------------------


def _store_ids(world: dict[str, Any]) -> list[str]:
    return [decoded for _, _, decoded in IDS] + [str(world["tmp"] / "elsewhere"), ""]


def test_every_store_method_refuses_a_bad_id(world: dict[str, Any]) -> None:
    from engine.game.state import GameState

    store = world["store"]
    for bad in _store_ids(world):
        before = _tree(world["tmp"])
        with pytest.raises(ValueError):
            store.save(GameState(), save_id=bad) if bad else store._dir(bad)
        with pytest.raises(ValueError):
            store.load(bad)
        with pytest.raises(ValueError):
            store.exists(bad)
        with pytest.raises(ValueError):
            store.delete(bad)
        with pytest.raises(ValueError):
            store.append_transcript(bad, {"turn": 1})
        _unchanged(world, before)


def test_a_loaded_envelope_whose_session_id_is_a_path_is_refused(world: dict[str, Any]) -> None:
    """
    ``session_id`` is persisted in the save and becomes the socket's room, so a
    hand-edited save must not smuggle one in: the load is refused, at the store
    and at the socket, as a missing save.
    """
    from engine.game.state import GameState

    store = world["store"]
    state = GameState()
    state.session_id = "../x"
    save_id = store.save(state, save_id="smuggled")
    with pytest.raises(ValueError):
        store.load(save_id)
    got = _resume(world, save_id)
    assert [e["name"] for e in got] == ["resume_failed"]
    missing = _resume(world, MISSING_ID)
    assert got[0]["args"][0]["message"] == missing[0]["args"][0]["message"].replace(
        MISSING_ID, save_id
    )
    res = world["client"].post(f"/api/saves/{save_id}/load")
    assert (res.status_code, res.get_json()) == (404, {"error": "save not found"})


def test_a_minted_id_round_trips(world: dict[str, Any]) -> None:
    from engine.game.state import GameState
    from engine.persistence.saves import SAVE_ID_RE

    store = world["store"]
    state = GameState()
    assert SAVE_ID_RE.fullmatch(state.session_id)
    save_id = store.save(state)
    assert re.fullmatch(r"[0-9a-f]{12}", save_id) and SAVE_ID_RE.fullmatch(save_id)
    assert store.exists(save_id)
    loaded, _ = store.load(save_id)
    assert loaded.session_id == state.session_id
    assert SAVE_ID_RE.fullmatch(world["save_id"])
    assert store.delete(save_id)
    assert not store.exists(save_id)


def test_the_pattern_is_the_spec_s() -> None:
    from engine.persistence.saves import SAVE_ID_RE

    assert SAVE_ID_RE.pattern == r"^[A-Za-z0-9_-]{1,64}$"
    assert SAVE_ID_RE.fullmatch("a" * 64) and not SAVE_ID_RE.fullmatch("a" * 65)
    assert not SAVE_ID_RE.fullmatch("abc\n")


# -- fix round 1 ------------------------------------------------------------------


def test_the_refusal_is_its_own_exception() -> None:
    """Review finding 1: the doors catch THIS, never every ValueError."""
    from engine.persistence.saves import InvalidSaveId, check_save_id

    assert issubclass(InvalidSaveId, ValueError)
    for bad in ("..", "NUL", "con.txt", "x.", "x ", "", 7):
        with pytest.raises(InvalidSaveId):
            check_save_id(bad)
    assert check_save_id("Console") == "Console"  # a device name only when whole
    assert check_save_id("com10") == "com10"


def _corrupt(world: dict[str, Any]) -> str:
    """A real save whose envelope's ``save_version`` makes ``migrate`` raise."""
    import json

    from engine.game.state import GameState

    store = world["store"]
    save_id = store.save(GameState(), save_id="corrupt1")
    path = store.root / save_id / "save.json"
    envelope = json.loads(path.read_text(encoding="utf-8"))
    envelope["state"]["save_version"] = "abc"
    envelope["save_version"] = "abc"
    path.write_text(json.dumps(envelope), encoding="utf-8")
    return save_id


def test_a_corrupt_save_is_not_answered_as_missing(
    world: dict[str, Any], caplog: pytest.LogCaptureFixture
) -> None:
    """
    Review finding 1: a save that is THERE and will not load is an error the
    owner's log names, not "save not found" with nothing logged.
    """
    save_id = _corrupt(world)
    caplog.clear()
    res = world["client"].post(f"/api/saves/{save_id}/load")
    assert res.status_code == 500
    assert res.get_json() != {"error": "save not found"}
    assert any(save_id in r.getMessage() and r.levelname == "ERROR" for r in caplog.records)

    caplog.clear()
    got = _resume(world, save_id)
    assert [e["name"] for e in got] == ["resume_failed"]
    assert got[0]["args"][0]["message"] != f"No readable save: {save_id}"
    assert any(save_id in r.getMessage() and r.levelname == "ERROR" for r in caplog.records)


def test_a_smuggled_session_id_is_logged(
    world: dict[str, Any], caplog: pytest.LogCaptureFixture
) -> None:
    from engine.game.state import GameState
    from engine.persistence.saves import InvalidSaveId

    store = world["store"]
    state = GameState()
    state.session_id = "../x"
    save_id = store.save(state, save_id="smuggled2")
    caplog.clear()
    with pytest.raises(InvalidSaveId):
        store.load(save_id)
    assert any(
        r.levelname == "WARNING" and save_id in r.getMessage() and "session id" in r.getMessage()
        for r in caplog.records
    )


def test_ids_that_differ_only_in_case_are_one_id(world: dict[str, Any]) -> None:
    """
    Review finding 5, decided as REFUSE THE SECOND: on Windows `abc` and `ABC`
    are one directory, so a second id that differs only in case would share
    (and a delete of it would remove) the first run's files. Refused on every
    OS, as a missing save, so a save tree means the same thing everywhere.
    Minted ids are lowercase hex and never meet this.
    """
    client = world["client"]
    store = world["store"]
    first = client.post(
        "/api/saves", json={"session_id": world["session_id"], "save_id": "MyRun"}
    )
    assert first.get_json() == {"save_id": "MyRun"}
    before = _tree(world["tmp"])

    twin = client.post("/api/saves", json={"session_id": world["session_id"], "save_id": "myrun"})
    assert (twin.status_code, twin.get_json()) == (404, {"error": "save not found"})
    load = client.post("/api/saves/MYRUN/load")
    assert (load.status_code, load.get_json()) == (404, {"error": "save not found"})
    delete = client.delete("/api/saves/myRun")
    assert delete.get_json() == {"deleted": False}
    got = _resume(world, "myrun")
    assert got[0]["args"][0] == {"message": "No readable save: myrun"}
    _unchanged(world, before)
    from engine.persistence.saves import InvalidSaveId

    if store.exists("MyRun") and (store.root / "mYrUn").exists():
        # A case-insensitive filesystem: the twin names the first run's
        # directory, and every store method refuses it.
        with pytest.raises(InvalidSaveId):
            store.exists("mYrUn")
    else:
        assert not store.exists("mYrUn")
    assert [s.save_id for s in store.list_saves()].count("MyRun") == 1
    assert not [s for s in store.list_saves() if s.save_id.lower() == "myrun" and s.save_id != "MyRun"]
    # The exact id still works, end to end.
    assert client.post("/api/saves/MyRun/load").status_code == 200
    assert client.delete("/api/saves/MyRun").get_json() == {"deleted": True}


def test_reindex_skips_a_directory_whose_name_is_not_an_id(
    world: dict[str, Any], caplog: pytest.LogCaptureFixture
) -> None:
    """Review finding 11: a stray `foo.bak` must not become a load-menu row."""
    import shutil

    store = world["store"]
    good = world["save_id"]
    stray = store.root / "foo.bak"
    shutil.copytree(store.root / good, stray)
    # An envelope with no id of its own is indexed under its directory's name.
    import json

    envelope = json.loads((stray / "save.json").read_text(encoding="utf-8"))
    envelope.pop("save_id", None)
    (stray / "save.json").write_text(json.dumps(envelope), encoding="utf-8")
    caplog.clear()
    store.reindex()
    ids = [s.save_id for s in store.list_saves()]
    assert good in ids
    assert "foo.bak" not in ids and "foo.bak" not in [s.save_id for s in store.list_saves()]
    assert any(
        r.levelname == "WARNING" and "foo.bak" in r.getMessage() for r in caplog.records
    )
