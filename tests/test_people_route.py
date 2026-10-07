"""
``GET /api/people``: who is here, for the people strip (v0.21.0, spec §4.4).

THE LEAK THIS GUARDS (Risk 6). HUE & CRY's NPC ids ARE names (``npc_ardane``)
and a shipped portrait URL is a manifest file name, so either would hand over
the name the strip withholds from a stranger. A row carries an opaque ``key``
and nothing else that identifies it; ``name`` and ``portrait`` only once met;
role and activity pass the awareness spoiler gate. The list is
``merge_npcs_at_location`` -- the call the prompt and the turn schema use --
less crowds, with generated household people capped as PEOPLE HERE caps them.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterator

import pytest

import engine.scenes.default_api as default_api
from engine.agents.prompts import MAX_GENERATED_PRESENT
from engine.game.state import GameState

PLACE = "tallow_docks"

SCHEDULED = [
    {"id": "npc_ardane", "name": "Captain Ardane", "role": "watch_captain", "activity": "reading reports"},
    {"id": "npc_dock_mag", "name": "Dock Mag", "role": "dock_boss", "activity": "shouting at porters"},
]


def _generated(n: int) -> list[dict[str, Any]]:
    return [
        {"id": f"gen_house_{i}", "name": f"Householder {i}", "role": "servant", "activity": "sweeping", "premise": f"prem_{i}"}
        for i in range(n)
    ]


@pytest.fixture
def present(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[dict[str, Any]]]:
    """The rows `merge_npcs_at_location` answers, set per test."""
    rows: list[dict[str, Any]] = []
    import engine.world.world_sim as world_sim

    monkeypatch.setattr(world_sim, "merge_npcs_at_location", lambda state, place: list(rows))
    yield rows


def _state() -> GameState:
    return GameState(rng_seed=7, location_id=PLACE)


def _ledger(*met: str) -> Any:
    return SimpleNamespace(relations={npc_id: SimpleNamespace(met=True) for npc_id in met})


def test_rows_carry_exactly_the_person_keys(present: list[dict[str, Any]]) -> None:
    present.extend(SCHEDULED)
    answer = default_api.people_here(_state(), _ledger("npc_ardane"))
    assert set(answer) == {"people", "more"}
    assert [tuple(row) for row in answer["people"]] == [default_api.PERSON_KEYS] * 2
    assert [row["key"] for row in answer["people"]] == ["p0", "p1"]
    assert all("id" not in row for row in answer["people"])


def test_a_met_person_is_named_and_a_stranger_is_not(present: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(default_api, "shipped_art_url", lambda npc_id, kind: f"/story-art/portraits/{npc_id}.jpg")
    present.extend(SCHEDULED)
    met, stranger = default_api.people_here(_state(), _ledger("npc_ardane"))["people"]
    assert met["known"] is True and met["name"] == "Captain Ardane"
    assert met["portrait"] == "/story-art/portraits/npc_ardane.jpg"
    assert stranger == {
        "key": "p1", "known": False, "name": "", "role_label": "dock boss",
        "activity": "shouting at porters", "portrait": "",
    }


def test_no_unmet_row_names_its_npc_anywhere(present: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Case-insensitive, and by name TOKEN (the content test's own rule:
    ``tests/test_activity_names_nobody.py``), so "frankie" against
    "Frankie DeLuca", or a surname alone, is caught -- not only the full
    name or the exact id.
    """
    from tests.test_activity_names_nobody import identifying_tokens, names_in

    monkeypatch.setattr(default_api, "shipped_art_url", lambda npc_id, kind: f"/story-art/portraits/{npc_id}.jpg")
    present.extend(SCHEDULED)
    for row in default_api.people_here(_state(), _ledger())["people"]:
        text = json.dumps(row)
        for npc in SCHEDULED:
            assert not names_in(text, identifying_tokens(npc["id"], npc["name"], npc["role"])), text


def test_presence_is_asked_about_the_players_own_place(monkeypatch: pytest.MonkeyPatch) -> None:
    import engine.world.world_sim as world_sim

    asked: list[str] = []
    monkeypatch.setattr(world_sim, "merge_npcs_at_location", lambda state, place: asked.append(place) or [])
    state = _state()
    assert default_api.people_here(state, _ledger()) == {"people": [], "more": 0}
    assert asked == [state.location_id] == [PLACE]


def test_a_met_person_with_no_authored_name_is_never_shown_as_an_id(
    present: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Presence falls back to the raw id for a nameless person (finding 6)."""
    from engine.world import npc_sim

    monkeypatch.setattr(npc_sim, "display_name", lambda npc_id, state=None: "the night porter")
    present.append({"id": "npc_porter", "name": "npc_porter", "role": "porter", "activity": "dozing"})
    (row,) = default_api.people_here(_state(), _ledger("npc_porter"))["people"]
    assert row["name"] == "the night porter"


def test_crowds_are_dropped(present: list[dict[str, Any]]) -> None:
    present.extend([*SCHEDULED, {"id": "dock_crowd", "name": "the crowd", "role": "", "activity": "milling"}])
    rows = default_api.people_here(_state(), _ledger())["people"]
    assert len(rows) == 2


def test_generated_people_are_capped_as_the_prompt_caps_them(present: list[dict[str, Any]]) -> None:
    present.extend([*SCHEDULED, *_generated(MAX_GENERATED_PRESENT + 3)])
    answer = default_api.people_here(_state(), _ledger())
    assert len(answer["people"]) == 2 + MAX_GENERATED_PRESENT
    assert answer["more"] == 3


def test_role_and_activity_pass_the_spoiler_gate(present: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch) -> None:
    import engine.lore.interceptors as interceptors

    monkeypatch.setattr(
        interceptors, "spoiler_terms",
        lambda state=None: [(re.compile(r"thieves' guild", re.IGNORECASE), "a certain company")],
    )
    present.append({"id": "npc_silas", "name": "Silas Crook", "role": "thieves' guild head", "activity": "counting the thieves' guild's take"})
    state = _state()
    state.awareness = 0.0
    (row,) = default_api.people_here(state, _ledger("npc_silas"))["people"]
    assert "guild" not in row["role_label"] and "a certain company" in row["role_label"]
    assert "guild" not in row["activity"]
    assert row["name"] == "Silas Crook"  # names are never masked (masking points)


# -- the route ------------------------------------------------------------------

SCRIPTED = json.dumps({"narration": "The quay is loud.", "choices": [{"id": "a", "text": "Wait"}]})


@pytest.fixture
def app() -> Iterator[Any]:
    from engine.scenes.default_scene import create_app, reset_store

    reset_store()
    scene, flask_app = create_app(testing=True, llm_fn=lambda _m: SCRIPTED)
    yield scene, flask_app.test_client()
    reset_store()


def test_the_route_answers_for_a_live_session(app: Any) -> None:
    _scene, client = app
    started = client.post("/api/game/new", json={"seed": 7}).get_json()
    answer = client.get("/api/people", query_string={"session_id": started["session_id"]})
    assert answer.status_code == 200
    body = answer.get_json()
    assert set(body) == {"people", "more"}
    # A SET on the wire: Flask's JSON provider sorts keys, so the response's
    # order is alphabetical (the builder's own order is pinned above).
    assert all(set(row) == set(default_api.PERSON_KEYS) for row in body["people"])


def test_an_unknown_session_is_a_404(app: Any) -> None:
    _scene, client = app
    for query in ({}, {"session_id": "000000000000"}):
        answer = client.get("/api/people", query_string=query)
        assert answer.status_code == 404 and answer.get_json() == {"error": "session not found"}


def test_a_failure_inside_answers_an_empty_list(app: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    _scene, client = app
    started = client.post("/api/game/new", json={"seed": 7}).get_json()

    def broken(state: Any, ledger: Any = None) -> Any:
        raise RuntimeError("a half-moved world")

    monkeypatch.setattr(default_api, "people_here", broken)
    answer = client.get("/api/people", query_string={"session_id": started["session_id"]})
    assert answer.status_code == 200 and answer.get_json() == {"people": [], "more": 0}


def test_hosted_another_accounts_session_is_a_404(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from tests.hosted_app import build, login, teardown

    hosted = build(monkeypatch, tmp_path)
    try:
        clients = {}
        for name in ("alice", "bob"):
            _account, password = hosted.add(name)
            client = hosted.client()
            assert login(client, name, password).status_code == 303
            clients[name] = client
        mine = clients["alice"].post("/api/game/new", json={"seed": 3}).get_json()["session_id"]
        theirs = clients["bob"].get("/api/people", query_string={"session_id": mine})
        nobody = clients["bob"].get("/api/people", query_string={"session_id": "000000000000"})
        assert (theirs.status_code, theirs.data) == (nobody.status_code, nobody.data) == (404, nobody.data)
        assert clients["alice"].get("/api/people", query_string={"session_id": mine}).status_code == 200
    finally:
        teardown()
