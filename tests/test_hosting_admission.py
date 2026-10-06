"""
Admission: a turn takes its narration ticket before it touches anything
(v0.20.0 T9, spec §5.3, survey finding 13).

Hosted, ``run_guarded`` waits for a narration ticket BEFORE ``run_turn``
runs a single mechanic. If none frees up within ``hosting.queue_wait_seconds``
the turn is refused as busy -- HTTP 409, the socket's ``turn_error`` with
``busy: true``, "The storyteller is busy with other players. Try again in a
moment." -- and the state, the save on disk and the transcript are exactly
what they were. Before this, a busy model server became ``fallback_narration``
over a turn whose clock had already moved, committed and autosaved.

The utility lane is optional by design: a planner, the summarizer, the
Assistant or quest evaluation that meets ``InferenceBusy`` mid-turn degrades
as any failure of theirs does, and the turn commits with its narration.

A hosted-only behaviour, so there is no v0.19.0 to fail on; the busy test
fails against T8's ``run_guarded`` (no admission: the turn runs).
"""

from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import pytest

from engine.llm import gate
from engine.llm.gate import InferenceBusy
from tests.hosted_app import Hosted, Lanes, SharedQueue, build, login, teardown

JOIN = 30.0
BUSY = "The storyteller is busy with other players. Try again in a moment."
NARRATION = "Mist clings to the birch trunks."


@pytest.fixture
def lanes() -> Iterator[None]:
    gate.reset_lanes()
    try:
        yield
    finally:
        gate.reset_lanes()


def _build(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, **kwargs: Any) -> Hosted:
    hosting = {"queue_wait_seconds": 1, **kwargs.pop("hosting", {})}
    return build(monkeypatch, tmp_path, hosting=hosting, **kwargs)


@contextmanager
def _served(request: Any) -> Iterator[Lanes]:
    """
    The lanes a test's turns queue in: this process's own (T9) or, for the
    ``shared_queue`` parameter, the supervisor's queue over a real loopback
    bus (T11): spec §5.3's rules hold under both.
    """
    shared = SharedQueue({"narration": 1, "utility": 2}) if getattr(request, "param", "") == "shared_queue" else None
    if shared is not None:
        shared.install()
    try:
        yield Lanes(shared)
    finally:
        if shared is not None:
            shared.close()


BACKENDS = ["own_lanes", "shared_queue"]


@pytest.fixture(params=BACKENDS)
def served(request: Any, lanes: None) -> Iterator[Lanes]:
    with _served(request) as served_lanes:
        yield served_lanes


@pytest.fixture
def hosted(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, served: Lanes) -> Iterator[Hosted]:
    try:
        yield _build(monkeypatch, tmp_path)
    finally:
        teardown()


@contextmanager
def narration_held_elsewhere() -> Iterator[None]:
    """Another player's turn holds the one narration slot until the block ends."""
    taken = threading.Event()
    done = threading.Event()

    def hold() -> None:
        with gate.turn_admission(label="another player"):
            taken.set()
            done.wait(JOIN)

    thread = threading.Thread(target=hold, name="other-player-turn")
    thread.start()
    try:
        assert taken.wait(JOIN), "the other player's turn was never admitted"
        yield
    finally:
        done.set()
        thread.join(JOIN)
        assert not thread.is_alive()


def _player(hosted: Hosted, name: str = "alice") -> tuple[Any, Any, dict[str, Any]]:
    account, password = hosted.add(name)
    client = hosted.client()
    assert login(client, name, password).status_code == 303
    opened = client.post("/api/game/new", json={"seed": 7, "player_name": name})
    assert opened.status_code == 200, opened.get_data(as_text=True)
    return account, client, opened.get_json()


def _disk(hosted: Hosted) -> dict[str, bytes]:
    root = hosted.data_dir / "users"
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _state(hosted: Hosted, account: Any, session_id: str) -> str:
    session = hosted.scene.store.require(session_id, owner=account.id)
    return json.dumps(session.engine.state.to_save_dict(), sort_keys=True, default=str)


def _choice(opened: dict[str, Any]) -> str:
    choices = (opened.get("opening") or {}).get("choices") or []
    return str(choices[0]["id"]) if choices else "a"


def test_a_busy_turn_over_http_is_409_and_changes_nothing(hosted: Hosted) -> None:
    account, client, opened = _player(hosted)
    session_id = opened["session_id"]
    before_state = _state(hosted, account, session_id)
    before_disk = _disk(hosted)
    assert any(name.endswith(".jsonl") or "save" in name for name in before_disk), before_disk

    with narration_held_elsewhere():
        response = client.post(
            "/api/game/choice", json={"session_id": session_id, "choice_id": _choice(opened)}
        )
    assert response.status_code == 409
    assert response.get_json() == {"error": BUSY}
    assert _state(hosted, account, session_id) == before_state
    assert _disk(hosted) == before_disk

    # Once the slot is free, the same turn plays.
    played = client.post("/api/game/choice", json={"session_id": session_id, "choice_id": _choice(opened)})
    assert played.status_code == 200
    assert NARRATION in played.get_json()["narration"]
    assert _disk(hosted) != before_disk


def test_a_busy_turn_over_the_socket_is_busy_and_changes_nothing(hosted: Hosted) -> None:
    account, client, opened = _player(hosted)
    session_id = opened["session_id"]
    sio = hosted.scene.socketio.test_client(hosted.app, flask_test_client=client)
    assert sio.is_connected()
    sio.emit("join_session", {"session_id": session_id})
    assert [e["name"] for e in sio.get_received()] == ["game_started"]
    before_state = _state(hosted, account, session_id)
    before_disk = _disk(hosted)

    with narration_held_elsewhere():
        sio.emit("player_choice", {"session_id": session_id, "choice_id": _choice(opened)})
        received = sio.get_received()
    assert received == [
        {"name": "turn_error", "args": [{"message": BUSY, "busy": True}], "namespace": "/"}
    ]
    assert _state(hosted, account, session_id) == before_state
    assert _disk(hosted) == before_disk
    sio.disconnect()


def test_the_admitted_turn_releases_its_ticket(hosted: Hosted, served: Lanes) -> None:
    _account, client, opened = _player(hosted)
    response = client.post(
        "/api/game/choice", json={"session_id": opened["session_id"], "choice_id": _choice(opened)}
    )
    assert response.status_code == 200
    narration = served.view("narration")
    if served.shared is None:
        assert isinstance(narration, gate.FifoSemaphore)
    assert narration.held == 0 and narration.waiting == 0
    assert gate.held_lane() is None


def _transcript(hosted: Hosted, account: Any, session_id: str) -> str:
    """The run's turn records (the ledger), as text."""
    session = hosted.scene.store.require(session_id, owner=account.id)
    return json.dumps(session.ledger.to_dict(), sort_keys=True, default=str)


@pytest.fixture
def own_lanes(lanes: None) -> Iterator[None]:
    yield


def test_with_the_supervisor_s_link_down_a_turn_is_refused_unrun(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, own_lanes: None
) -> None:
    """
    T11, fail closed (spec §14.4): with ``RemoteLanes`` over a bus that is
    not connected, a turn is answered busy -- 409, ``busy: true`` on the
    socket -- at once, and the state, the save bytes and the transcript are
    unchanged. Never run unqueued.
    """
    from engine.hosting.bus import BusClient
    from engine.hosting.lanes_remote import RemoteLanes

    hosted = _build(monkeypatch, tmp_path)
    try:
        account, client, opened = _player(hosted)
        session_id = opened["session_id"]
        before = (_state(hosted, account, session_id), _disk(hosted), _transcript(hosted, account, session_id))
        closed = BusClient("127.0.0.1:9", "0" * 64)  # never connected: the link is down
        closed.on_lost = lambda: None
        gate.set_lane_backend(RemoteLanes(closed))
        response = client.post("/api/game/choice", json={"session_id": session_id, "choice_id": _choice(opened)})
        assert response.status_code == 409
        assert response.get_json() == {"error": BUSY}
        sio = hosted.scene.socketio.test_client(hosted.app, flask_test_client=client)
        sio.emit("join_session", {"session_id": session_id})
        sio.get_received()
        sio.emit("player_choice", {"session_id": session_id, "choice_id": _choice(opened)})
        assert sio.get_received() == [
            {"name": "turn_error", "args": [{"message": BUSY, "busy": True}], "namespace": "/"}
        ]
        sio.disconnect()
        after = (_state(hosted, account, session_id), _disk(hosted), _transcript(hosted, account, session_id))
        assert after == before
    finally:
        teardown()


def test_a_turn_whose_account_holds_narration_in_another_story_is_told_other_window(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, own_lanes: None
) -> None:
    """
    T11, spec §5.4 across stories: the account's narration ticket is held by
    another worker (another story's window), so this turn is answered at
    once, busy, "A turn is still running in your other window.", with
    nothing changed.
    """
    shared = SharedQueue({"narration": 2, "utility": 2})
    shared.install()
    hosted = _build(monkeypatch, tmp_path)
    try:
        account, client, opened = _player(hosted)
        session_id = opened["session_id"]
        before = (_state(hosted, account, session_id), _disk(hosted))
        elsewhere = shared.lanes(story="hue-and-cry")
        ticket = elsewhere.acquire("narration", 1.0, account.id)
        try:
            response = client.post("/api/game/choice", json={"session_id": session_id, "choice_id": _choice(opened)})
        finally:
            elsewhere.release(ticket)
        assert response.status_code == 409
        assert response.get_json() == {"error": "A turn is still running in your other window."}
        assert (_state(hosted, account, session_id), _disk(hosted)) == before
        # A free slot was there all along (the lane holds two): only the
        # account rule refused it. Once the other window's turn is over:
        played = client.post("/api/game/choice", json={"session_id": session_id, "choice_id": _choice(opened)})
        assert played.status_code == 200
    finally:
        teardown()
        shared.close()


# -- the turn deadline (T11 fix round 1, ruling (a)) ---------------------------


class _Clock:
    def __init__(self) -> None:
        self.now = 5000.0

    def __call__(self) -> float:
        return self.now


def _slow_model(clock: _Clock, seconds: float, calls: list[str]) -> Any:
    """
    A model call that takes ``seconds`` of the deadline clock, then asks for
    its narration slot as the real backend does (``inference_slot``) --
    the injected ``llm_fn`` otherwise bypasses the gate.
    """
    from tests.hosted_app import SCRIPTED_REPLY

    def model(_messages: Any) -> str:
        clock.now += seconds
        with gate.inference_slot(lane="narration", label="storyteller", timeout=1):
            calls.append("narrated")
            return SCRIPTED_REPLY

    return model


def test_a_slow_but_healthy_turn_under_the_deadline_completes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, served: Lanes
) -> None:
    """
    Ruling (a): a turn whose model takes 40 s of a 60-second deadline -- far
    past any per-phase timeout, under the deadline -- narrates and commits,
    and its ticket comes back. Fails on 31cb510 (no such key).
    """
    clock = _Clock()
    monkeypatch.setattr(gate, "_clock", clock)
    calls: list[str] = []
    hosted = _build(
        monkeypatch, tmp_path, hosting={"turn_deadline_seconds": 60}, llm_fn=_slow_model(clock, 40.0, calls)
    )
    try:
        _account, client, opened = _player(hosted)
        calls.clear()
        response = _turn_response(client, opened)
        assert response.status_code == 200
        assert NARRATION in response.get_json()["narration"]
        assert "narrated" in calls
        assert served.view("narration").held == 0
    finally:
        teardown()


def test_a_turn_past_its_deadline_ends_through_the_fallback_and_frees_its_ticket(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, served: Lanes
) -> None:
    """
    Ruling (a): the model takes 90 s of a 60-second deadline. Its narration
    call is refused at the deadline and the turn ends through the
    storyteller's existing failure path -- the engine-authored fallback
    narration, as any model failure does -- commits as such a turn always
    has, and gives its ticket back. Fails on 31cb510 (no such key; and
    nothing bounded the turn).
    """
    from engine.agents.storyteller import fallback_narration

    clock = _Clock()
    monkeypatch.setattr(gate, "_clock", clock)
    calls: list[str] = []
    hosted = _build(
        monkeypatch, tmp_path, hosting={"turn_deadline_seconds": 60}, llm_fn=_slow_model(clock, 90.0, calls)
    )
    try:
        _account, client, opened = _player(hosted)
        calls.clear()
        response = _turn_response(client, opened)
        assert response.status_code == 200, response.get_data(as_text=True)
        narration = response.get_json()["narration"]
        assert NARRATION not in narration and fallback_narration() in narration
        assert "narrated" not in calls, "a model call ran past the deadline"
        narration_lane = served.view("narration")
        assert narration_lane.held == 0 and narration_lane.waiting == 0
    finally:
        teardown()


# -- a wait called off, a drained story's queued turn (T11 fix round 1) ---------


def test_a_socket_turn_s_wait_is_called_off_when_its_socket_disconnects(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, own_lanes: None
) -> None:
    """
    #2: under the supervisor's queue, a socket turn waits behind another
    player's; its socket goes. The wait leaves the queue AT ONCE -- while the
    other turn still holds the slot -- so the player holds no place and no
    account claim; the turn is answered skipped, unrun. On 31cb510 the
    entry waited out its whole queue wait.
    """
    shared = SharedQueue({"narration": 1, "utility": 2})
    shared.install()
    hosted = _build(monkeypatch, tmp_path, hosting={"queue_wait_seconds": 60})
    try:
        account, client, opened = _player(hosted)
        session_id = opened["session_id"]
        sio = hosted.scene.socketio.test_client(hosted.app, flask_test_client=client)
        sio.emit("join_session", {"session_id": session_id})
        sio.get_received()
        sid = hosted.scene.socketio.server.manager.sid_from_eio_sid(sio.eio_sid, "/")
        before = (_state(hosted, account, session_id), _disk(hosted))
        narration = shared.view("narration")
        finished = threading.Event()
        with narration_held_elsewhere():
            thread = threading.Thread(
                target=lambda: (
                    sio.emit("player_choice", {"session_id": session_id, "choice_id": _choice(opened)}),
                    finished.set(),
                ),
                name="waiting-socket-turn",
            )
            thread.start()
            assert narration.wait_until_waiting(1, timeout=JOIN), "the socket turn never queued"
            hosted.scene.socketio.server.disconnect(sid, namespace="/")
            # Gone from the line while the other turn still holds the slot.
            assert shared.queue.wait_for(lambda s: not _lane_row(s)["waiters"], JOIN), "the wait was not called off"
            assert narration.held == 1
            thread.join(JOIN)
            assert not thread.is_alive() and finished.is_set()
        assert (_state(hosted, account, session_id), _disk(hosted)) == before
    finally:
        teardown()
        shared.close()


def test_a_double_clicked_turn_s_wait_is_still_called_off_when_its_socket_disconnects(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, own_lanes: None
) -> None:
    """
    v0.20.0 T12 (T11's N1): the waiting turns are kept per EVENT, not per
    socket. A double-click is two ``player_choice`` events on one sid: the
    first waits in the queue, the second is answered at once (the run is
    busy). The second's bookkeeping must not drop the first's: when the
    socket goes, the first wait still leaves the queue at once. On 3a7da4f
    the second event overwrote the sid's entry and then popped it, so the
    first waited out its whole queue wait after the player had gone.
    """
    shared = SharedQueue({"narration": 1, "utility": 2})
    shared.install()
    hosted = _build(monkeypatch, tmp_path, hosting={"queue_wait_seconds": 60})
    try:
        _account, client, opened = _player(hosted)
        session_id = opened["session_id"]
        sio = hosted.scene.socketio.test_client(hosted.app, flask_test_client=client)
        sio.emit("join_session", {"session_id": session_id})
        sio.get_received()
        sid = hosted.scene.socketio.server.manager.sid_from_eio_sid(sio.eio_sid, "/")
        narration = shared.view("narration")
        finished = threading.Event()
        with narration_held_elsewhere():
            thread = threading.Thread(
                target=lambda: (
                    sio.emit("player_choice", {"session_id": session_id, "choice_id": _choice(opened)}),
                    finished.set(),
                ),
                name="waiting-socket-turn",
            )
            thread.start()
            assert narration.wait_until_waiting(1, timeout=JOIN), "the socket turn never queued"
            # The second click, on the same socket: answered without waiting.
            sio.emit("player_choice", {"session_id": session_id, "choice_id": _choice(opened)})
            assert narration.waiting == 1
            hosted.scene.socketio.server.disconnect(sid, namespace="/")
            assert shared.queue.wait_for(lambda s: not _lane_row(s)["waiters"], JOIN), (
                "the first click's wait was not called off"
            )
            thread.join(JOIN)
            assert not thread.is_alive() and finished.is_set()
        assert hosted.scene._waiting_turns == {}
    finally:
        teardown()
        shared.close()


def _lane_row(snapshot: dict[str, Any], lane: str = "narration") -> dict[str, Any]:
    return next(row for row in snapshot["lanes"] if row["lane"] == lane)


def test_a_drained_story_s_queued_turn_is_answered_busy_and_changes_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, own_lanes: None
) -> None:
    """
    #8: at a successful drain (``close_story``), a turn still queued in that
    story is answered busy -- 409, it never started -- and the state and the
    save are untouched.
    """
    shared = SharedQueue({"narration": 1, "utility": 2})
    shared.install()
    hosted = _build(monkeypatch, tmp_path, hosting={"queue_wait_seconds": 60})
    try:
        account, client, opened = _player(hosted)
        session_id = opened["session_id"]
        before = (_state(hosted, account, session_id), _disk(hosted))
        results: dict[str, Any] = {}
        holder = shared.lanes(story="hue-and-cry")
        ticket = holder.acquire("narration", 1.0)
        try:
            thread = threading.Thread(
                target=lambda: results.__setitem__("turn", _turn_response(client, opened)), name="queued-turn"
            )
            thread.start()
            assert shared.view("narration").wait_until_waiting(1, timeout=JOIN)
            shared.queue.pause(shared.story)
            assert shared.queue.close_story(shared.story) == 1
            thread.join(JOIN)
            assert not thread.is_alive()
        finally:
            holder.release(ticket)
        assert results["turn"].status_code == 409
        assert results["turn"].get_json() == {"error": BUSY}
        assert (_state(hosted, account, session_id), _disk(hosted)) == before
    finally:
        teardown()
        shared.close()


def test_local_run_guarded_takes_no_admission(monkeypatch: pytest.MonkeyPatch, lanes: None) -> None:
    """Local mode: v0.19.0's run_guarded, unwrapped (no ticket is ever taken)."""
    from engine.scenes import default_scene

    def refuse(**_kwargs: Any) -> Any:
        raise AssertionError("local mode took an admission")

    monkeypatch.setattr(gate, "admit_turn", refuse)
    monkeypatch.setattr(gate, "turn_admission", refuse)
    session = type("S", (), {"lock": threading.Lock(), "session_id": "s"})()
    monkeypatch.setattr(default_scene, "run_turn", lambda *_a, **_k: {"narration": "ok"})
    assert default_scene.run_guarded(session, "act", None) == ({"narration": "ok"}, "", False)


# -- fix round 1 --------------------------------------------------------------


def test_another_players_utility_work_cannot_hold_a_turn_past_the_narration_wait(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, served: Lanes
) -> None:
    """
    I1: every utility slot is taken by other players' work (voice replies,
    say). Alice's admitted turn asks for one for her companion; it waits only
    ``utility_wait_seconds``, skips, and her turn ends -- so Bob, queued
    behind her for the one narration slot, is admitted inside his
    ``queue_wait_seconds``. Fails on 1e0557f, where Alice's companion waited
    the full queue wait holding the narration slot, and Bob was refused busy.
    """
    from engine.agents.assistant import AssistantAgent

    # Two utility calls in Alice's turn: at the old wait (the queue wait,
    # 4 s each) she would hold the narration slot 8 s, past Bob's 4 s; at
    # one second each she holds it about 2.
    hosted = _build(
        monkeypatch, tmp_path, hosting={"queue_wait_seconds": 4, "utility_wait_seconds": 1}
    )
    try:
        _alice, alice_client, alice_run = _player(hosted, "alice")
        _bob, bob_client, bob_run = _player(hosted, "bob")
        companion_asked = threading.Event()
        skipped: list[str] = []

        def through_the_gate(_self: Any, _messages: Any) -> str:
            companion_asked.set()
            for _call in range(2):
                try:
                    with gate.inference_slot(lane="utility", label="assistant"):
                        return ""
                except InferenceBusy:
                    skipped.append("assistant")
            raise InferenceBusy("no utility slot")

        real_run = AssistantAgent.run_turn
        monkeypatch.setattr(AssistantAgent, "_infer", through_the_gate)
        monkeypatch.setattr(
            AssistantAgent, "run_turn", lambda self, context, force_speak=False: real_run(self, context, force_speak=True)
        )
        taken = served.take_all("utility")  # other players' slow utility work
        assert len(taken) >= 1
        results: dict[str, Any] = {}
        try:
            alice = threading.Thread(
                target=lambda: results.__setitem__("alice", _turn_response(alice_client, alice_run)),
                name="alice-turn",
            )
            alice.start()
            assert companion_asked.wait(JOIN), "alice's turn never reached her companion"
            # Alice holds the narration slot now; Bob queues behind her.
            results["bob"] = _turn_response(bob_client, bob_run)
            alice.join(JOIN)
            assert not alice.is_alive()
        finally:
            for release in taken:
                release()
        assert results["alice"].status_code == 200
        assert results["bob"].status_code == 200, results["bob"].get_data(as_text=True)
        assert "assistant" in skipped
        assert served.view("narration").held == 0
    finally:
        teardown()


def _turn_response(client: Any, opened: dict[str, Any]) -> Any:
    return client.post(
        "/api/game/choice", json={"session_id": opened["session_id"], "choice_id": _choice(opened)}
    )


def test_a_turn_whose_player_left_while_it_waited_is_not_played(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, served: Lanes
) -> None:
    """
    M3: a socket turn queued behind another player's; its socket goes away
    while it waits. Once admitted it is skipped -- nothing changes -- and
    the slot goes straight back. Fails on 1e0557f, which played it. (A wait
    long enough that the queued turn is admitted, not timed out.)
    """
    hosted = _build(monkeypatch, tmp_path, hosting={"queue_wait_seconds": 60})
    try:
        _left_while_waiting(hosted, served)
    finally:
        teardown()


def _left_while_waiting(hosted: Hosted, served: Lanes) -> None:
    account, client, opened = _player(hosted)
    session_id = opened["session_id"]
    sio = hosted.scene.socketio.test_client(hosted.app, flask_test_client=client)
    sio.emit("join_session", {"session_id": session_id})
    sio.get_received()
    sid = hosted.scene.socketio.server.manager.sid_from_eio_sid(sio.eio_sid, "/")
    before_state = _state(hosted, account, session_id)
    before_disk = _disk(hosted)
    narration = served.view("narration")
    finished = threading.Event()

    with narration_held_elsewhere():
        thread = threading.Thread(
            target=lambda: (
                sio.emit("player_choice", {"session_id": session_id, "choice_id": _choice(opened)}),
                finished.set(),
            ),
            name="queued-socket-turn",
        )
        thread.start()
        assert narration.wait_until_waiting(1, timeout=JOIN), "the socket turn never queued"
        hosted.scene.socketio.server.disconnect(sid, namespace="/")  # the player closes the tab
    thread.join(JOIN)
    assert not thread.is_alive() and finished.is_set()
    assert _state(hosted, account, session_id) == before_state
    assert _disk(hosted) == before_disk
    assert narration.held == 0 and narration.waiting == 0


# -- the utility lane degrades; the turn commits ------------------------------


def _turn(client: Any, opened: dict[str, Any]) -> dict[str, Any]:
    response = client.post(
        "/api/game/choice", json={"session_id": opened["session_id"], "choice_id": _choice(opened)}
    )
    assert response.status_code == 200, response.get_data(as_text=True)
    payload = response.get_json()
    assert NARRATION in payload["narration"]
    return payload


def _busy(calls: list[str], name: str) -> Any:
    def raise_busy(*_args: Any, **_kwargs: Any) -> Any:
        calls.append(name)
        raise InferenceBusy(f"Inference busy: {name}")

    return raise_busy


def test_a_busy_planner_degrades_and_the_turn_commits(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, served: Lanes) -> None:
    from engine.agents import planner

    calls: list[str] = []
    monkeypatch.setattr(planner, "_infer", _busy(calls, "planner"))
    hosted = _build(monkeypatch, tmp_path, env={"CLOCKWORK_GAME": "dev-story"})
    try:
        _account, client, opened = _player(hosted)
        before = client.get(f"/api/game/state?session_id={opened['session_id']}").get_json()
        payload = _turn(client, opened)
        assert calls, "no planner ran: the test proves nothing"
        assert payload["state"]["turn_number"] == before["state"]["turn_number"] + 1
    finally:
        teardown()


def test_a_busy_summarizer_degrades_and_the_turn_commits(monkeypatch: pytest.MonkeyPatch, hosted: Hosted) -> None:
    from engine.scenes import default_state

    calls: list[str] = []
    monkeypatch.setattr(default_state, "_summarizer_fn", lambda: _busy(calls, "summarizer"))
    account, client, opened = _player(hosted)
    session = hosted.scene.store.require(opened["session_id"], owner=account.id)
    real = session.ledger.record_turn
    # Every turn evicts one: the summarizer is asked each time.
    monkeypatch.setattr(session.ledger, "record_turn", lambda record: (real(record), record)[1])
    _turn(client, opened)
    assert calls == ["summarizer"]
    assert session.ledger.summary, "the deterministic fallback did not fill the summary"


def test_a_busy_assistant_degrades_and_the_turn_commits(monkeypatch: pytest.MonkeyPatch, hosted: Hosted) -> None:
    from engine.agents.assistant import AssistantAgent

    calls: list[str] = []
    monkeypatch.setattr(AssistantAgent, "_infer", _busy(calls, "assistant"))
    account, client, opened = _player(hosted)
    session = hosted.scene.store.require(opened["session_id"], owner=account.id)
    real = session.assistant.run_turn
    monkeypatch.setattr(session.assistant, "run_turn", lambda context: real(context, force_speak=True))
    payload = _turn(client, opened)
    assert calls == ["assistant"]
    assert payload["assistant"]["spoke"] is False


def test_busy_quest_evaluation_degrades_and_the_turn_commits(monkeypatch: pytest.MonkeyPatch, hosted: Hosted) -> None:
    from engine.game.quests import QuestEngine

    calls: list[str] = []
    monkeypatch.setattr(QuestEngine, "evaluate", staticmethod(_busy(calls, "quests")))
    _account, client, opened = _player(hosted)
    _turn(client, opened)
    assert calls == ["quests"]


# -- HTTP turns never hold every thread (v0.20.0 T12) ---------------------------


def test_http_turns_waiting_in_the_queue_never_hold_every_thread(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, own_lanes: None
) -> None:
    """
    The T9 review's finding, closed in T12: an HTTP turn waits in the model
    server's queue on its request thread, for up to ``queue_wait_seconds``,
    so under gunicorn's pool (``hosting.threads``) enough of them would hold
    every thread and starve login, the static files and everything else. At
    most ``threads - RESERVED_THREADS`` HTTP turns are in flight per process
    (``limits.TurnSlots``); one more is answered 429 AT ONCE, while every
    other request is still served, and the slot comes back when the turn
    ends. Here ``threads: 5`` leaves one slot. Fails on 3a7da4f, where the
    second turn queued (and here would have waited out its queue wait).
    """
    from engine.hosting.limits import RESERVED_THREADS, SERVER_BUSY

    hosted = _build(monkeypatch, tmp_path, hosting={"threads": RESERVED_THREADS + 1, "queue_wait_seconds": 60})
    try:
        _alice, alice, alice_run = _player(hosted, "alice")
        _bob, bob, bob_run = _player(hosted, "bob")
        narration = gate._semaphore("narration")
        answers: list[Any] = []
        with narration_held_elsewhere():
            thread = threading.Thread(
                target=lambda: answers.append(
                    alice.post(
                        "/api/game/choice",
                        json={"session_id": alice_run["session_id"], "choice_id": _choice(alice_run)},
                    )
                ),
                name="waiting-http-turn",
            )
            thread.start()
            assert narration.wait_until_waiting(1, timeout=JOIN), "the HTTP turn never queued"
            refused = bob.post(
                "/api/game/choice", json={"session_id": bob_run["session_id"], "choice_id": _choice(bob_run)}
            )
            assert refused.status_code == 429 and refused.get_json() == {"error": SERVER_BUSY}
            assert narration.waiting == 1, "the refused turn queued"
            # Everything that is not a turn is still served.
            assert bob.get("/api/health").status_code == 200
            assert bob.get("/api/games").status_code == 200
        thread.join(JOIN)
        assert not thread.is_alive() and answers[0].status_code == 200
        assert hosted.state.turn_slots.inside == 0
        played = bob.post(
            "/api/game/choice", json={"session_id": bob_run["session_id"], "choice_id": _choice(bob_run)}
        )
        assert played.status_code == 200, played.get_data(as_text=True)
    finally:
        teardown()
