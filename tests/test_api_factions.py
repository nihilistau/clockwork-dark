"""GET /api/factions (v0.25.0 E4, spec §6.4): names and band words for the sheet, read-only."""

from __future__ import annotations

import pytest

from engine.games import registry


@pytest.fixture
def client():
    from engine.scenes import default_scene

    registry.activate("clockwork-dark")
    try:
        scene, app = default_scene.create_app(testing=True, llm_fn=lambda m, **k: "{}")
        http = app.test_client()
        body = http.post("/api/game/new", json={"seed": 7}).get_json()
        yield scene, http, body["session_id"]
    finally:
        registry.deactivate()


def test_every_declared_faction_in_order_with_its_band(client) -> None:
    from engine.game import reputation

    scene, http, session_id = client
    state = scene.store.require(session_id).engine.state
    rows = http.get("/api/factions", query_string={"session_id": session_id}).get_json()
    assert [r["id"] for r in rows] == reputation.faction_ids()
    saints = next(r for r in rows if r["id"] == "unnamed_saints")
    assert saints["name"] == reputation.faction_name("unnamed_saints")
    assert saints["band"] == {"id": reputation.standing_id(state, "unnamed_saints"),
                              "label": reputation.standing(state, "unnamed_saints")}
    assert saints["score"] == reputation.get(state, "unnamed_saints")


def test_it_writes_nothing_and_needs_a_session(client) -> None:
    scene, http, session_id = client
    state = scene.store.require(session_id).engine.state
    before = state.to_save_dict()
    http.get("/api/factions", query_string={"session_id": session_id})
    assert state.to_save_dict() == before
    assert http.get("/api/factions").status_code == 404


def test_a_failed_read_answers_no_rows_not_a_500(client, monkeypatch) -> None:
    """T14 (review a5): a malformed band or a read that meets a turn answers `[]`, as /api/people does."""
    from engine.scenes import default_api

    _scene, http, session_id = client

    def broken(_state):
        raise ValueError("a band with no number")

    monkeypatch.setattr(default_api, "faction_rows", broken)
    answer = http.get("/api/factions", query_string={"session_id": session_id})
    assert answer.status_code == 200 and answer.get_json() == []
