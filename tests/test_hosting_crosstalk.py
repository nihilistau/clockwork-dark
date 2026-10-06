"""
No cross-talk between two players in one hosted process (v0.20.0 T8, spec
§5.1, §9.3).

Two accounts play interleaved turns on two threads -- a scripted model, fixed
seeds, and a ``threading.Barrier`` before every turn so both turns are in
flight at once -- and each player's payload sequence must equal that
player's solo run, turn for turn. The threads are a pool's, reused from turn
to turn as gunicorn's gthread reuses them, and after the run each one is
checked for leftovers: the engine's ``threading.local`` guards clear, and the
request owner (``current_owner``) unset.
"""

from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Iterator

import pytest

from engine.session.store import current_owner
from tests.hosted_app import Hosted, build, login, teardown
from tests.local_golden import Normaliser, _first_choice

TURNS = 3
SEEDS = {"alice": 41, "bob": 42}
#: Generous: a turn on the scripted model takes well under a second.
WAIT = 60.0


@pytest.fixture
def hosted(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Hosted]:
    try:
        yield build(monkeypatch, tmp_path)
    finally:
        teardown()


def _client(hosted: Hosted, name: str, password: str) -> Any:
    client = hosted.client()
    assert login(client, name, password).status_code == 303
    return client


def _new(client: Any, name: str) -> dict[str, Any]:
    response = client.post("/api/game/new", json={"seed": SEEDS[name], "player_name": name})
    assert response.status_code == 200
    return response.get_json()


def _turn(client: Any, session_id: str, last: dict[str, Any]) -> dict[str, Any]:
    response = client.post(
        "/api/game/choice", json={"session_id": session_id, "choice_id": _first_choice(last)}
    )
    assert response.status_code == 200, response.get_data(as_text=True)
    return response.get_json()


def _normalised(sequence: list[dict[str, Any]]) -> list[Any]:
    norm = Normaliser()
    norm.learn(sequence)
    return norm(sequence)


def _solo(client: Any, name: str) -> list[dict[str, Any]]:
    opened = _new(client, name)
    sequence = [opened]
    last = opened.get("opening") or {}
    for _ in range(TURNS):
        last = _turn(client, opened["session_id"], last)
        sequence.append(last)
    return sequence


def _leftovers() -> dict[str, Any]:
    """What a reused thread still holds from the work it ran before."""
    from engine.game import clock, encounter, inventory

    return {
        "owner": current_owner.get(),
        "clock_depth": getattr(clock._guard, "depth", 0),
        "death_guard": getattr(encounter._death_guard, "active", False),
        "terminal_lock_guard": getattr(encounter._terminal_lock_guard, "active", False),
        "evaluating_collections": getattr(inventory._evaluating_collections, "active", False),
        "thread": threading.get_ident(),
    }


def test_two_players_interleaved_each_get_their_solo_run(hosted: Hosted) -> None:
    passwords = {name: hosted.add(name)[1] for name in SEEDS}

    solo = {name: _normalised(_solo(_client(hosted, name, passwords[name]), name)) for name in SEEDS}
    assert solo["alice"] != solo["bob"], "two seeds gave one run: the comparison would prove nothing"

    clients = {name: _client(hosted, name, passwords[name]) for name in SEEDS}
    barrier = threading.Barrier(len(SEEDS), timeout=WAIT)
    runs: dict[str, list[dict[str, Any]]] = {}
    last: dict[str, dict[str, Any]] = {}
    sessions: dict[str, str] = {}

    def opening(name: str) -> None:
        barrier.wait()
        opened = _new(clients[name], name)
        runs[name] = [opened]
        sessions[name] = opened["session_id"]
        last[name] = opened.get("opening") or {}

    def turn(name: str) -> None:
        barrier.wait()  # both turns start together, on two threads
        last[name] = _turn(clients[name], sessions[name], last[name])
        runs[name].append(last[name])

    with ThreadPoolExecutor(max_workers=len(SEEDS), thread_name_prefix="crosstalk") as pool:
        for step in [opening] + [turn] * TURNS:
            futures = [pool.submit(step, name) for name in SEEDS]
            for future in futures:
                future.result(timeout=WAIT)
        # Each pool thread, reused for every turn above, is clear now.
        probe = threading.Barrier(len(SEEDS), timeout=WAIT)

        def check() -> dict[str, Any]:
            probe.wait()  # hold both threads, so each runs one probe
            return _leftovers()

        leftovers = [f.result(timeout=WAIT) for f in [pool.submit(check) for _ in SEEDS]]

    assert len({row.pop("thread") for row in leftovers}) == len(SEEDS)
    clear = {
        "owner": None,
        "clock_depth": 0,
        "death_guard": False,
        "terminal_lock_guard": False,
        "evaluating_collections": False,
    }
    assert leftovers == [clear] * len(SEEDS)
    for name in SEEDS:
        assert _normalised(runs[name]) == solo[name], f"{name}'s interleaved run differs from their solo run"
    assert sessions["alice"] != sessions["bob"]


def _socket_player(hosted: Hosted, name: str, password: str) -> tuple[Any, str]:
    """A logged-in socket in its own new run's room."""
    client = _client(hosted, name, password)
    session_id = _new(client, name)["session_id"]
    sio = hosted.scene.socketio.test_client(hosted.app, flask_test_client=client)
    assert sio.is_connected()
    sio.emit("join_session", {"session_id": session_id})
    assert [e["name"] for e in sio.get_received()] == ["game_started"]
    return sio, session_id


def _stream(sio: Any, session_id: str, last_choice: list[str]) -> list[dict[str, Any]]:
    """One socket turn; what the socket received, as names and payloads."""
    sio.emit("player_choice", {"session_id": session_id, "choice_id": last_choice[0]})
    received = [{"name": e["name"], "args": e["args"]} for e in sio.get_received()]
    finals = [e["args"][0] for e in received if e["name"] == "turn_update" and e["args"]]
    if finals:
        last_choice[0] = _first_choice(finals[-1]) or last_choice[0]
    return received


def test_two_players_socket_streams_interleaved_each_get_their_solo_stream(hosted: Hosted) -> None:
    """
    Fix round 1 (M5): the socket path, where each turn is streamed to its
    run's room, interleaved on two threads behind a barrier per turn. Each
    socket receives exactly its own solo stream, and nothing of the other's.
    """
    passwords = {name: hosted.add(name)[1] for name in SEEDS}

    solo: dict[str, list[Any]] = {}
    for name in SEEDS:
        sio, session_id = _socket_player(hosted, name, passwords[name])
        choice = ["a"]
        solo[name] = _normalised([_stream(sio, session_id, choice) for _ in range(TURNS)])
        sio.disconnect()
    assert solo["alice"] != solo["bob"], "two seeds gave one stream: the comparison would prove nothing"

    players = {name: _socket_player(hosted, name, passwords[name]) for name in SEEDS}
    choices = {name: ["a"] for name in SEEDS}
    streams: dict[str, list[Any]] = {name: [] for name in SEEDS}
    barrier = threading.Barrier(len(SEEDS), timeout=WAIT)

    def turn(name: str) -> None:
        sio, session_id = players[name]
        barrier.wait()
        streams[name].append(_stream(sio, session_id, choices[name]))

    with ThreadPoolExecutor(max_workers=len(SEEDS), thread_name_prefix="crosstalk-sio") as pool:
        for _ in range(TURNS):
            for future in [pool.submit(turn, name) for name in SEEDS]:
                future.result(timeout=WAIT)

    for name in SEEDS:
        assert _normalised(streams[name]) == solo[name], f"{name}'s socket stream differs from their solo stream"
    alice_ids = {players["alice"][1]}
    assert not any(players["bob"][1] in json.dumps(turn) for turn in streams["alice"])
    assert not any(sid in json.dumps(turn) for sid in alice_ids for turn in streams["bob"])
