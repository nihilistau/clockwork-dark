"""
Rate limits and input caps on both doors (v0.20.0 T9, spec §6.5, survey
finding 14).

- The actions bucket: per account, ``hosting.rate_limits.actions_per_minute``
  across new game, choice, resume, save write and transcribe, over HTTP (429)
  and over the socket (``turn_error``, ``busy: false``) alike. A rest is
  counted exactly like any other choice (AGENTS.md rule 6).
- The input caps: a typed action (``custom_text``) longer than
  ``hosting.max_input_chars`` and a ``player_name`` longer than 40 characters
  are REFUSED, never cut (HTTP 400, socket ``turn_error`` ``busy: false``),
  and change nothing. A length and nothing else (rule 12).
- Socket.IO caps a message at 64 KiB; Flask caps a request body (the voice
  upload) at ``hosting.max_upload_mb``.

Each bucket test swaps in a one-token ``ActionLimiter`` on a clock that never
moves, so the second action is the one refused, whatever the wall clock does.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any, Callable, Iterator

import pytest

from engine.hosting.limits import SLOW_DOWN, ActionLimiter, too_long
from tests.hosted_app import Hosted, build, login, teardown

CAP = 10
UPLOAD_MB = 1


@pytest.fixture
def hosted(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Hosted]:
    try:
        yield build(
            monkeypatch,
            tmp_path,
            hosting={"max_input_chars": CAP, "max_upload_mb": UPLOAD_MB},
        )
    finally:
        teardown()


def _player(hosted: Hosted, name: str = "alice") -> tuple[Any, Any, dict[str, Any]]:
    account, password = hosted.add(name)
    client = hosted.client()
    assert login(client, name, password).status_code == 303
    opened = client.post("/api/game/new", json={"seed": 5, "player_name": "Wren"})
    assert opened.status_code == 200, opened.get_data(as_text=True)
    return account, client, opened.get_json()


def _one_token(hosted: Hosted) -> None:
    """From now on: one action, and the clock never refills it."""
    hosted.state.actions = ActionLimiter(1, clock=lambda: 0.0)
    door = hosted.scene._socket_door
    door.actions = hosted.state.actions


def _turn_number(hosted: Hosted, account: Any, session_id: str) -> int:
    return hosted.scene.store.require(session_id, owner=account.id).engine.state.turn_number


# -- the actions bucket over HTTP ---------------------------------------------


def _http_actions(opened: dict[str, Any]) -> dict[str, Callable[[Any], Any]]:
    return {
        "new game": lambda c: c.post("/api/game/new", json={"seed": 9}),
        "choice": lambda c: c.post(
            "/api/game/choice", json={"session_id": opened["session_id"], "choice_id": "a"}
        ),
        "save write": lambda c: c.post("/api/saves", json={"session_id": opened["session_id"]}),
        "resume": lambda c: c.post(f"/api/saves/{opened['save_id']}/load"),
        "transcribe": lambda c: c.post(
            "/api/voice/transcribe",
            data={"session_id": opened["session_id"]},
            content_type="multipart/form-data",
        ),
    }


@pytest.mark.parametrize("action", ["new game", "choice", "save write", "resume", "transcribe"])
def test_each_http_action_spends_from_the_bucket(hosted: Hosted, action: str) -> None:
    _account, client, opened = _player(hosted)
    _one_token(hosted)
    act = _http_actions(opened)[action]
    first = act(client)
    assert first.status_code != 429, first.get_data(as_text=True)
    second = act(client)
    assert second.status_code == 429
    assert second.get_json() == {"error": SLOW_DOWN}


def test_the_bucket_is_per_account(hosted: Hosted) -> None:
    _alice, alice_client, _ = _player(hosted, "alice")
    _bob, bob_client, _ = _player(hosted, "bob")
    _one_token(hosted)
    assert alice_client.post("/api/game/new", json={"seed": 1}).status_code == 200
    assert alice_client.post("/api/game/new", json={"seed": 2}).status_code == 429
    assert bob_client.post("/api/game/new", json={"seed": 3}).status_code == 200


def test_reading_is_not_an_action(hosted: Hosted) -> None:
    _account, client, opened = _player(hosted)
    _one_token(hosted)
    for _ in range(3):
        assert client.get(f"/api/game/state?session_id={opened['session_id']}").status_code == 200
        assert client.get("/api/saves").status_code == 200
    assert client.post("/api/game/new", json={"seed": 1}).status_code == 200


# -- the actions bucket over the socket ---------------------------------------


def _sio(hosted: Hosted, client: Any) -> Any:
    sio = hosted.scene.socketio.test_client(hosted.app, flask_test_client=client)
    assert sio.is_connected()
    return sio


SLOW = {"name": "turn_error", "args": [{"message": SLOW_DOWN, "busy": False}], "namespace": "/"}


@pytest.mark.parametrize("event", ["player_choice", "resume"])
def test_each_socket_action_spends_from_the_bucket(hosted: Hosted, event: str) -> None:
    _account, client, opened = _player(hosted)
    sio = _sio(hosted, client)
    sio.emit("join_session", {"session_id": opened["session_id"]})
    sio.get_received()
    data = (
        {"session_id": opened["session_id"], "choice_id": "a"}
        if event == "player_choice"
        else {"save_id": opened["save_id"]}
    )
    _one_token(hosted)
    sio.emit(event, data)
    first = [e["name"] for e in sio.get_received()]
    assert first and "turn_error" not in first, first
    sio.emit(event, data)
    assert sio.get_received() == [SLOW]
    sio.disconnect()


def test_http_and_socket_share_one_bucket(hosted: Hosted) -> None:
    _account, client, opened = _player(hosted)
    sio = _sio(hosted, client)
    _one_token(hosted)
    assert client.post("/api/game/new", json={"seed": 1}).status_code == 200
    sio.emit("resume", {"save_id": opened["save_id"]})
    assert sio.get_received() == [SLOW]
    sio.disconnect()


def _with_choices(hosted: Hosted, account: Any, session_id: str) -> None:
    """Offer a rest and a walk, the rest with a real rest intent."""
    from engine.game import survival

    kinds = [str(k) for k in survival.rest_kinds() if str(k)]
    assert kinds, "the flagship has no rest: the test proves nothing"
    session = hosted.scene.store.require(session_id, owner=account.id)
    session.last_turn = {
        "narration": "",
        "choices": [
            {"id": "r", "text": "Rest a while", "intent": {"action": "rest", "target": kinds[0]}},
            {"id": "w", "text": "Walk on"},
        ],
    }


@pytest.mark.parametrize("first,second", [("r", "w"), ("w", "r")])
def test_a_rest_is_counted_exactly_like_any_other_choice(hosted: Hosted, first: str, second: str) -> None:
    account, client, opened = _player(hosted)
    session_id = opened["session_id"]
    _with_choices(hosted, account, session_id)
    _one_token(hosted)
    played = client.post("/api/game/choice", json={"session_id": session_id, "choice_id": first})
    assert played.status_code == 200, played.get_data(as_text=True)
    _with_choices(hosted, account, session_id)
    refused = client.post("/api/game/choice", json={"session_id": session_id, "choice_id": second})
    assert refused.status_code == 429
    assert refused.get_json() == {"error": SLOW_DOWN}


# -- the input caps -----------------------------------------------------------


def test_custom_text_over_the_cap_is_refused_over_http_not_cut(hosted: Hosted) -> None:
    account, client, opened = _player(hosted)
    session_id = opened["session_id"]
    _one_token(hosted)
    before = _turn_number(hosted, account, session_id)
    refused = client.post(
        "/api/game/choice", json={"session_id": session_id, "custom_text": "x" * (CAP + 1)}
    )
    assert refused.status_code == 400
    assert refused.get_json() == {"error": too_long(CAP)}
    assert refused.get_json()["error"] == f"That is longer than this server accepts ({CAP} characters)."
    assert _turn_number(hosted, account, session_id) == before
    # At the cap it plays, on the token the refusal did not spend.
    played = client.post("/api/game/choice", json={"session_id": session_id, "custom_text": "y" * CAP})
    assert played.status_code == 200
    assert _turn_number(hosted, account, session_id) == before + 1


def test_custom_text_over_the_cap_is_refused_over_the_socket_not_cut(hosted: Hosted) -> None:
    account, client, opened = _player(hosted)
    session_id = opened["session_id"]
    sio = _sio(hosted, client)
    sio.emit("join_session", {"session_id": session_id})
    sio.get_received()
    before = _turn_number(hosted, account, session_id)
    sio.emit("player_choice", {"session_id": session_id, "custom_text": "x" * (CAP + 1)})
    assert sio.get_received() == [
        {"name": "turn_error", "args": [{"message": too_long(CAP), "busy": False}], "namespace": "/"}
    ]
    assert _turn_number(hosted, account, session_id) == before
    sio.disconnect()


def test_a_player_name_over_40_is_refused(hosted: Hosted) -> None:
    _account, client, _opened = _player(hosted)
    refused = client.post("/api/game/new", json={"seed": 1, "player_name": "n" * 41})
    assert refused.status_code == 400
    assert refused.get_json() == {"error": too_long(40)}
    assert client.post("/api/game/new", json={"seed": 1, "player_name": "n" * 40}).status_code == 200


@pytest.mark.parametrize(
    ("rule", "field"),
    [
        ("/api/saves", "slot"),
        ("/api/game/new", "archetype"),
        ("/api/game/new", "seed"),
        ("/api/game/choice", "choice_id"),
    ],
)
def test_every_text_field_is_held_to_the_cap(hosted: Hosted, rule: str, field: str) -> None:
    """
    Fix round 1 (I2): a save's label (written into the save index), the
    archetype, the seed and a choice id are held to ``max_input_chars`` like
    the typed action: refused 400, never cut. Fails on 1e0557f.
    """
    _account, client, opened = _player(hosted)
    body = {"session_id": opened["session_id"], "seed": 1, field: "z" * (CAP + 1)}
    refused = client.post(rule, json=body)
    assert refused.status_code == 400, refused.get_data(as_text=True)
    assert refused.get_json() == {"error": too_long(CAP)}
    at_cap = dict(body, **{field: "z" * CAP})
    assert client.post(rule, json=at_cap).status_code != 400


def test_a_transcript_over_the_cap_gets_no_reply(
    hosted: Hosted, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Fix round 1 (I2): a voice transcript longer than ``max_input_chars`` is
    not sent to the companion (the same words typed would be refused): the
    player keeps the transcript and is told why. Fails on 1e0557f.
    """
    from engine.agents.assistant import AssistantAgent
    from engine.media import stt

    long_words = "w" * (CAP + 1)
    monkeypatch.setattr(stt, "transcribe_audio", lambda _audio, **_k: {"success": True, "transcript": long_words})

    def never(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("the companion was asked about an over-long transcript")

    monkeypatch.setattr(AssistantAgent, "process_voice_input", never)
    _account, client, opened = _player(hosted)
    response = client.post(
        "/api/voice/transcribe",
        data={"session_id": opened["session_id"], "audio": (io.BytesIO(b"RIFF0000WAVE"), "a.wav")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 200
    body = response.get_json()
    assert body["assistant"] is None
    assert body["error"] == too_long(CAP)
    assert body["stt"]["transcript"] == long_words, "the transcript was cut"


def test_saves_per_story_are_capped(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """
    Fix round 1 (I2): ``hosting.max_saves_per_story`` caps the rows an account
    keeps in one story -- a new run or a save under a new id is refused 409
    with the engine's words; overwriting one that is there is not; deleting
    one makes room. Fails on 1e0557f.
    """
    from engine.session.store import saves_full_message

    hosted = build(monkeypatch, tmp_path, hosting={"max_saves_per_story": 2})
    try:
        _account, client, opened = _player(hosted)  # row 1: the run's autosave
        session_id = opened["session_id"]
        second = client.post("/api/saves", json={"session_id": session_id, "slot": "camp"})
        assert second.status_code == 200  # row 2
        full = {"error": saves_full_message(2)}
        third = client.post("/api/saves", json={"session_id": session_id, "slot": "again"})
        assert (third.status_code, third.get_json()) == (409, full)
        new_run = client.post("/api/game/new", json={"seed": 2})
        assert (new_run.status_code, new_run.get_json()) == (409, full)
        overwrite = client.post(
            "/api/saves", json={"session_id": session_id, "save_id": second.get_json()["save_id"], "slot": "camp"}
        )
        assert overwrite.status_code == 200
        assert client.delete(f"/api/saves/{second.get_json()['save_id']}").get_json() == {"deleted": True}
        assert client.post("/api/saves", json={"session_id": session_id, "slot": "again"}).status_code == 200
    finally:
        teardown()


def test_two_saves_at_once_cannot_both_take_the_last_row(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """
    v0.20.0 T15 (the controller's note after T9's re-review): the cap's count
    and the save's write are ONE step under the save folder's index lock. Two
    manual saves under new ids, at the cap less one, are let past the early
    check together (a barrier in ``list_saves``, which that check counts
    with); exactly one is written, the other refused 409 with the engine's
    words, and the index holds the cap. Fails on bebdcb2, where both wrote
    and the account kept 3 rows under a cap of 2.
    """
    import threading

    from engine.persistence.saves import SaveStore
    from engine.session.store import saves_full_message

    hosted = build(monkeypatch, tmp_path, hosting={"max_saves_per_story": 2})
    try:
        account, first, opened = _player(hosted)  # row 1: the run's autosave
        second = hosted.client()
        assert login(second, account.name, hosted.passwords[account.name]).status_code == 303
        barrier = threading.Barrier(2, timeout=5)
        real = SaveStore.list_saves

        def counted_together(self: SaveStore) -> Any:
            rows = real(self)
            try:
                barrier.wait()
            except threading.BrokenBarrierError:
                pass
            return rows

        monkeypatch.setattr(SaveStore, "list_saves", counted_together)
        answers: list[Any] = []
        errors: list[BaseException] = []

        def save(client: Any, slot: str) -> None:
            try:
                answers.append(client.post("/api/saves", json={"session_id": opened["session_id"], "slot": slot}))
            except BaseException as exc:  # noqa: BLE001 -- reported below
                errors.append(exc)

        threads = [threading.Thread(target=save, args=(c, s)) for c, s in ((first, "camp"), (second, "ford"))]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(30)
        assert not any(t.is_alive() for t in threads) and not errors, errors
        monkeypatch.setattr(SaveStore, "list_saves", real)
        codes = sorted(a.status_code for a in answers)
        assert codes == [200, 409], [(a.status_code, a.get_json()) for a in answers]
        refused = next(a for a in answers if a.status_code == 409)
        # Since T15 fix round 2 (N3) a manual save takes the run's turn lock,
        # so the second may be refused as busy before it ever counts; either
        # way it is refused in the engine's words and nothing past the cap is
        # written.
        assert refused.get_json()["error"] in (saves_full_message(2), "A turn is already in progress.")
        rows = first.get("/api/saves").get_json()["saves"]
        assert len(rows) == 2, rows
    finally:
        teardown()


def test_a_socket_message_is_capped_at_64_kib(hosted: Hosted) -> None:
    assert hosted.scene.socketio.server.eio.max_http_buffer_size == 65536


def test_the_upload_is_capped_at_max_upload_mb(hosted: Hosted) -> None:
    _account, client, opened = _player(hosted)
    assert hosted.app.config["MAX_CONTENT_LENGTH"] == UPLOAD_MB * 1024 * 1024
    too_big = io.BytesIO(b"\0" * (UPLOAD_MB * 1024 * 1024 + 1))
    response = client.post(
        "/api/voice/transcribe",
        data={"session_id": opened["session_id"], "audio": (too_big, "a.webm")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 413
    assert "Traceback" not in response.get_data(as_text=True)


# -- v0.20.0 T13: the body-read deadline without read1, and the long holds -------------


class _LoopingInput:
    """
    gunicorn's ``wsgi.input`` in miniature (``gunicorn.http.body.Body``): no
    ``read1``, and ``read(n)`` loops ``recv`` until it has ``n`` bytes or the
    peer closes, each ``recv`` under the socket's own timeout.
    """

    def __init__(self, sock: Any) -> None:
        self.sock = sock

    def read(self, size: int) -> bytes:
        out = b""
        while len(out) < size:
            data = self.sock.recv(size - len(out))
            if not data:
                break
            out += data
        return out


def test_a_trickled_body_is_cut_at_the_deadline_without_read1() -> None:
    """
    A client sends a 40-byte body one byte every 0.15 s (6 s in all, each
    byte well inside the per-read timeout). With ``read1`` gone, as under
    gunicorn, one ``read`` used to loop for the whole 6 s and return the
    body; now the read is cut at the 1 s deadline and answered as a timeout.
    """
    import socket
    import threading
    import time

    from engine.hosting.limits import BodyTimeout, read_body

    listener = socket.create_server(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    client = socket.create_connection(("127.0.0.1", port), timeout=10)
    server, _addr = listener.accept()
    listener.close()
    stop = threading.Event()

    def trickle() -> None:
        for _ in range(40):
            if stop.wait(0.15):
                return
            try:
                client.sendall(b"x")
            except OSError:
                return

    sender = threading.Thread(target=trickle, name="trickle")
    sender.start()
    environ = {"CONTENT_LENGTH": "40", "wsgi.input": _LoopingInput(server), "gunicorn.socket": server}
    began = time.monotonic()
    try:
        with pytest.raises(BodyTimeout):
            read_body(environ, 1024, 1.0)
        took = time.monotonic() - began
    finally:
        stop.set()
        sender.join(10)
        client.close()
        server.close()
    assert not sender.is_alive()
    assert took < 2.5, f"the read ran {took:.1f}s past a 1s deadline"


def test_a_body_that_arrives_in_time_is_read_whole_without_read1() -> None:
    import socket

    from engine.hosting.limits import read_body

    listener = socket.create_server(("127.0.0.1", 0))
    client = socket.create_connection(listener.getsockname()[:2], timeout=10)
    server, _addr = listener.accept()
    listener.close()
    try:
        client.sendall(b'{"choice_id": "a"}')
        environ = {"CONTENT_LENGTH": "18", "wsgi.input": _LoopingInput(server), "gunicorn.socket": server}
        assert read_body(environ, 1024, 5.0) == b'{"choice_id": "a"}'
        assert environ["wsgi.input"].read() == b'{"choice_id": "a"}'
        # The socket is still readable both ways: nothing shut it.
        client.sendall(b"more")
        assert server.recv(4) == b"more"
    finally:
        client.close()
        server.close()


def test_turn_slots_take_their_place_among_the_long_holds() -> None:
    from engine.hosting.limits import ACCOUNT, FULL, LongHolds, TurnSlots

    holds = LongHolds(2)
    slots = TurnSlots(2, pool=holds)
    assert holds.try_take() == ""  # a WebSocket holds one place
    assert slots.try_enter("alice") == ""
    assert holds.inside == 2
    assert slots.try_enter("bob") == FULL, "a turn took a place the WebSockets had filled"
    assert slots.inside == 1, "a refused turn kept its slot"
    assert slots.try_enter("alice") == ACCOUNT
    slots.leave("alice")
    assert holds.inside == 1 and slots.inside == 0
    assert slots.try_enter("bob") == ""
    assert holds.try_take() == "full"
    holds.give_back()
    slots.leave("bob")
    assert holds.inside == 0


def test_long_holds_cap_one_account_s_connections() -> None:
    """Fix round 1, I4: past ``per_account``, an account is refused while another still gets in."""
    from engine.hosting.limits import ACCOUNT, FULL, LongHolds

    holds = LongHolds(5, per_account=2)
    assert [holds.try_take("alice") for _ in range(3)] == ["", "", ACCOUNT]
    assert holds.of_account("alice") == 2 and holds.inside == 2
    assert holds.try_take("bob") == ""
    holds.give_back("alice")
    assert holds.try_take("alice") == ""
    assert holds.try_take("carol") == "" and holds.try_take("carol") == ""
    assert holds.inside == 5 and holds.try_take("dave") == FULL
    assert holds.try_take() == FULL  # a turn's place counts toward the whole only


def test_three_tabs_upgrading_at_once_fit_a_cap_of_four() -> None:
    """
    T13 re-review N1: a tab upgrading from polling holds its last poll AND its
    new WebSocket for a moment. Counted apiece, three tabs opening together
    (six holds) passed a cap of four and got 429. Holds that name one
    Engine.IO session are ONE connection to the account's cap -- each still a
    place among the whole, being a thread each. On 6ceffa8 the fifth hold was
    refused ACCOUNT.
    """
    from engine.hosting.limits import ACCOUNT, LongHolds

    holds = LongHolds(32, per_account=4)
    for tab in ("s1", "s2", "s3"):
        assert holds.try_take("alice", tab) == "", f"{tab}'s poll"
        assert holds.try_take("alice", tab, upgrade=True) == "", f"{tab}'s upgrading WebSocket"
    assert holds.of_account("alice") == 3 and holds.inside == 6
    # The polls end as the upgrades complete; the WebSockets stay.
    for tab in ("s1", "s2", "s3"):
        holds.give_back("alice", tab)
    assert holds.of_account("alice") == 3 and holds.inside == 3
    # A fourth tab fits; a fifth connection does not, named or not.
    assert holds.try_take("alice", "s4") == ""
    assert holds.try_take("alice", "s5") == ACCOUNT and holds.try_take("alice") == ACCOUNT
    # A request naming no session is its own connection, as before.
    for tab in ("s1", "s2", "s3"):
        holds.give_back("alice", tab, upgrade=True)
    holds.give_back("alice", "s4")
    assert holds.of_account("alice") == 0 and holds.inside == 0
    assert [holds.try_take("bob") for _ in range(5)] == ["", "", "", "", ACCOUNT]


def test_concurrent_polls_naming_one_session_each_count(  # T14 fix round 1, I1
) -> None:
    """
    The reviewer's probe: at a cap of 4, with 10 places, one account repeats
    ONE Engine.IO sid. engineio (4.13.4) refuses no concurrent poll of a
    session, so on 75791db every poll after the first joined it for free --
    ten places taken, ``of_account`` 1, and another account refused FULL.
    Now each poll counts; only the session's single WebSocket upgrade joins
    its poll, and a second WebSocket naming it counts too.
    """
    from engine.hosting.limits import ACCOUNT, LongHolds

    holds = LongHolds(10, per_account=4)
    answers = [holds.try_take("u_a", "sid1") for _ in range(12)]
    assert answers == [""] * 4 + [ACCOUNT] * 8, answers
    assert holds.of_account("u_a") == 4 and holds.inside == 4
    assert holds.try_take("u_b", "other") == "", "another account was locked out"
    # The one upgrade still joins (free); a second WebSocket on the sid does not.
    assert holds.try_take("u_a", "sid1", upgrade=True) == ""
    assert holds.try_take("u_a", "sid1", upgrade=True) == ACCOUNT
    assert holds.of_account("u_a") == 4
    # A poll after the upgrade's pairing is over counts again.
    for _ in range(4):
        holds.give_back("u_a", "sid1")
    assert holds.of_account("u_a") == 1  # the WebSocket alone
    assert [holds.try_take("u_a", "sid1") for _ in range(4)] == ["", "", "", ACCOUNT]
    assert holds.of_account("u_a") == 4
