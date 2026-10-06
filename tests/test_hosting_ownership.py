"""
Ownership: every door that names a session or a save (v0.20.0 T8, spec §6.4,
§9.3).

Two accounts, A and B. For every door in spec §6.4's table, B naming A's
session id or save id gets BYTE FOR BYTE the answer a nonexistent id gets,
and A's files are unchanged on disk afterwards -- so another player's ids
cannot even be probed for existence. ``join_session`` on A's id puts B in no
room: A's turn stream never reaches B. The five ``_optional_session`` routes
answer B with the story-wide data a request with no session gets. And a
hosted request with the owner unset fails closed.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any, Iterator

import pytest

from engine.session.store import OwnerUnset
from tests.hosted_app import Hosted, build, login, teardown
from tests.local_golden import OPTIONAL_SESSION_ROUTES, STORY_ROUTES, wav_bytes

#: An id shaped like a real one that names nothing.
NOBODY = "000000000000"


class _Stt:
    """Speech-to-text that answers at once: no provider is ever loaded here,
    even when a door this file guards is broken and lets B through."""

    name = "ownership_stub"

    def transcribe(self, _audio: bytes, **_kw: Any) -> dict[str, Any]:
        return {"success": True, "transcript": "wait", "source": "live", "provider": self.name}


@pytest.fixture
def hosted(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Hosted]:
    import engine.agents.assistant as assistant
    import engine.media.stt as stt

    monkeypatch.setattr(stt, "get_stt_provider", lambda *a, **k: _Stt())
    monkeypatch.setattr(assistant, "transcribe_audio", lambda audio, **_k: _Stt().transcribe(audio))
    try:
        yield build(monkeypatch, tmp_path)
    finally:
        teardown()


class Player:
    """One logged-in account: an HTTP client, a socket, and a run."""

    def __init__(self, hosted: Hosted, name: str, seed: int) -> None:
        self.account, password = hosted.add(name)
        self.client = hosted.client()
        assert login(self.client, name, password).status_code == 303
        self.sio = hosted.scene.socketio.test_client(hosted.app, flask_test_client=self.client)
        assert self.sio.is_connected()
        created = self.client.post("/api/game/new", json={"seed": seed}).get_json()
        self.session_id: str = created["session_id"]
        self.save_id: str = created["save_id"]
        self.dir = hosted.data_dir / "users" / self.account.id

    def files(self) -> dict[str, bytes]:
        return {
            str(p.relative_to(self.dir)): p.read_bytes() for p in sorted(self.dir.rglob("*")) if p.is_file()
        }


@pytest.fixture
def pair(hosted: Hosted) -> tuple[Player, Player]:
    return Player(hosted, "alice", 11), Player(hosted, "bob", 12)


def _answer(response: Any) -> tuple[int, bytes]:
    return response.status_code, response.data


def _socket_answer(sio: Any, event: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    sio.get_received()
    sio.emit(event, payload)
    return sio.get_received()


def _voice(client: Any, session_id: str) -> Any:
    return client.post(
        "/api/voice/transcribe",
        data={"session_id": session_id, "transcribe_only": "1", "audio": (io.BytesIO(wav_bytes()), "a.wav")},
        content_type="multipart/form-data",
    )


# -- the table ---------------------------------------------------------------------


def test_new_game_is_owned_by_the_account(hosted: Hosted, pair: tuple[Player, Player]) -> None:
    a, b = pair
    store = hosted.scene.store
    assert store._sessions[a.session_id].owner == a.account.id
    assert store._sessions[b.session_id].owner == b.account.id
    # Its first save is in the account's own store, under its id.
    assert (a.dir / "saves" / "clockwork-dark" / a.save_id / "save.json").is_file()
    assert not (hosted.data_dir / "saves" / "clockwork-dark" / a.save_id).exists()


def test_every_http_door_answers_another_accounts_id_as_a_missing_one(
    hosted: Hosted, pair: tuple[Player, Player]
) -> None:
    a, b = pair
    before = a.files()
    doors = {
        "GET /api/game/state": lambda sid, _save: b.client.get("/api/game/state", query_string={"session_id": sid}),
        "POST /api/game/choice": lambda sid, _save: b.client.post(
            "/api/game/choice", json={"session_id": sid, "choice_id": "a"}
        ),
        "POST /api/saves": lambda sid, _save: b.client.post("/api/saves", json={"session_id": sid}),
        "POST /api/saves/<id>/load": lambda _sid, save: b.client.post(f"/api/saves/{save}/load"),
        "DELETE /api/saves/<id>": lambda _sid, save: b.client.delete(f"/api/saves/{save}"),
        "POST /api/voice/transcribe": lambda sid, _save: _voice(b.client, sid),
    }
    for rule in STORY_ROUTES:
        doors[f"GET {rule}"] = lambda sid, _save, rule=rule: b.client.get(rule, query_string={"session_id": sid})
    differ = []
    for door, call in doors.items():
        theirs = _answer(call(a.session_id, a.save_id))
        nobody = _answer(call(NOBODY, NOBODY))
        if theirs != nobody:
            differ.append(f"{door}: A's id {theirs} != a missing id {nobody}")
    assert not differ, "\n".join(differ)
    assert a.files() == before, "B changed A's files"
    # B's own list never shows A's runs.
    listed = {row["save_id"] for row in b.client.get("/api/saves").get_json()["saves"]}
    assert a.save_id not in listed and b.save_id in listed


def test_the_optional_session_routes_answer_story_wide_data(
    hosted: Hosted, pair: tuple[Player, Player]
) -> None:
    a, b = pair
    for rule in sorted(OPTIONAL_SESSION_ROUTES):
        theirs = _answer(b.client.get(rule, query_string={"session_id": a.session_id}))
        story_wide = _answer(b.client.get(rule))
        assert theirs[0] == 200 and theirs == story_wide, rule
    # A, naming its own session, still gets its own run's view.
    assert a.client.get("/api/quests", query_string={"session_id": a.session_id}).status_code == 200


def test_every_socket_door_answers_another_accounts_id_as_a_missing_one(
    hosted: Hosted, pair: tuple[Player, Player]
) -> None:
    a, b = pair
    before = a.files()
    for event, payload_of in (
        ("join_session", lambda sid, _save: {"session_id": sid}),
        ("player_choice", lambda sid, _save: {"session_id": sid, "choice_id": "a"}),
        ("resume", lambda _sid, save: {"save_id": save}),
    ):
        theirs = _socket_answer(b.sio, event, payload_of(a.session_id, a.save_id))
        nobody = _socket_answer(b.sio, event, payload_of(NOBODY, NOBODY))
        assert theirs, event
        if event == "resume":
            # The missing save's words name the id that was asked for.
            assert [e["name"] for e in theirs] == [e["name"] for e in nobody] == ["resume_failed"]
            assert theirs[0]["args"][0]["message"].replace(a.save_id, NOBODY) == nobody[0]["args"][0]["message"]
        else:
            assert theirs == nobody, event
    assert a.files() == before, "B changed A's files"


def test_join_session_on_anothers_id_puts_them_in_no_room(
    hosted: Hosted, pair: tuple[Player, Player]
) -> None:
    a, b = pair
    assert [e["name"] for e in _socket_answer(a.sio, "join_session", {"session_id": a.session_id})] == [
        "game_started"
    ]
    assert [e["name"] for e in _socket_answer(b.sio, "join_session", {"session_id": a.session_id})] == ["error"]
    rooms = hosted.scene.socketio.server.manager.rooms.get("/", {})
    assert b.sio.eio_sid not in {
        eio for sid, eio in (rooms.get(a.session_id) or {}).items()
    }, "B sits in A's room"
    # A plays a turn: its stream reaches A, and nothing of it reaches B.
    a.sio.emit("player_choice", {"session_id": a.session_id, "choice_id": "a"})
    assert any(e["name"] == "turn_update" for e in a.sio.get_received())
    assert b.sio.get_received() == []


def test_hosted_never_answers_as_the_local_player(hosted: Hosted, pair: tuple[Player, Player]) -> None:
    """Fix round 1 (M3): an explicit ``owner=""`` is refused hosted, like an unset one."""
    a, _b = pair
    store = hosted.scene.store
    for call in (
        lambda: store.require(a.session_id, owner=""),
        lambda: store.resume(a.save_id, owner=""),
        lambda: store.create(seed=1, owner=""),
    ):
        with pytest.raises(OwnerUnset):
            call()
    assert not (hosted.data_dir / "saves").exists(), "a hosted call reached the local player's store"


def test_a_rebuild_never_replaces_another_owners_live_session(
    hosted: Hosted, pair: tuple[Player, Player]
) -> None:
    """
    Fix round 1 (M3): a save carrying A's live session id, in B's store (a
    copied save), is refused rather than replacing A's session and putting
    B in A's room.
    """
    import shutil

    from engine.session.store import SessionConflict

    a, b = pair
    copied = b.dir / "saves" / "clockwork-dark" / "copyofalices"
    shutil.copytree(a.dir / "saves" / "clockwork-dark" / a.save_id, copied)
    envelope = json.loads((copied / "save.json").read_text(encoding="utf-8"))
    envelope["save_id"] = "copyofalices"
    (copied / "save.json").write_text(json.dumps(envelope), encoding="utf-8")
    store = hosted.scene.store
    alices = store._sessions[a.session_id]
    with pytest.raises(SessionConflict):
        store.resume("copyofalices", owner=b.account.id)
    assert store._sessions[a.session_id] is alices
    # Over the doors: answered as a save that will not load, never as A's run.
    response = b.client.post("/api/saves/copyofalices/load")
    assert response.status_code == 500 and response.get_json() == {"error": "save could not be read"}
    events = _socket_answer(b.sio, "resume", {"save_id": "copyofalices"})
    assert [e["name"] for e in events] == ["resume_failed"]
    assert store._sessions[a.session_id] is alices


def test_get_is_owner_checked_like_require(hosted: Hosted, pair: tuple[Player, Player]) -> None:
    """Fix round 1 (M4): ``SessionStore.get`` is no side door around §6.4."""
    a, b = pair
    store = hosted.scene.store
    assert store.get(a.session_id, owner=a.account.id) is store._sessions[a.session_id]
    assert store.get(a.session_id, owner=b.account.id) is None
    with pytest.raises(OwnerUnset):
        store.get(a.session_id)


def test_a_hosted_request_with_the_owner_unset_fails_closed(
    hosted: Hosted, pair: tuple[Player, Player], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A path that escaped both gates (no owner set) reaches nobody's runs."""
    import contextvars

    import engine.hosting.gate as gate

    a, _b = pair
    store = hosted.scene.store
    # In code, outside any request: the store refuses.
    with pytest.raises(OwnerUnset):
        store.require(a.session_id)
    with pytest.raises(KeyError):
        store.require(a.session_id)
    with pytest.raises(OwnerUnset):
        store.resume(a.save_id)
    with pytest.raises(OwnerUnset):
        store.create(seed=1)
    # Over HTTP, with a gate that forgot to set the owner.
    monkeypatch.setattr(gate, "current_owner", contextvars.ContextVar("unused", default=None))
    assert a.client.get("/api/game/state", query_string={"session_id": a.session_id}).status_code == 404
    assert a.client.get("/api/saves").status_code == 401
    assert a.client.post(f"/api/saves/{a.save_id}/load").status_code == 401
    assert a.client.delete(f"/api/saves/{a.save_id}").status_code == 401
    created = a.client.post("/api/game/new", json={"seed": 3})
    assert created.status_code == 500 and "session_id" not in (created.get_json() or {})
    assert (a.dir / "saves" / "clockwork-dark" / a.save_id).is_dir()
