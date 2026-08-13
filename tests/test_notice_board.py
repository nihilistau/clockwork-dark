"""
The notice board — the server half of a render GOVERNANCE.md listed as unbuilt.

The contract catalogue (games/clockwork-dark/data/tables/labour.yaml, read through
engine/game/economy.py) has existed since P12 with no surface a client could
ask. ``notice_board`` is that surface: a pure view-model of the state, plus a
``GET /api/notices`` route on the story blueprint.

What has to stay true:

  1. The board and the ``query_work`` skill can never disagree -- the rows ARE
     ``economy.available``'s rows, so anything posted is takeable.
  2. A place with no work posts an empty board, not an error.
  3. The route is session-scoped: wages move with standing, phase and shifts
     already worked, so a board without a run is meaningless.
"""

from __future__ import annotations

import json

from content.scenes.clockwork.clockwork_api import notice_board
from engine.game import economy
from engine.game.procgen import new_game_state

MOCK_STORYTELLER = json.dumps(
    {
        "narration": "The square is quiet.",
        "choices": [{"id": "a", "text": "Wait"}],
        "tool_calls": [],
    }
)


# ---------------------------------------------------------------------------
# the view-model
# ---------------------------------------------------------------------------


def test_the_board_posts_exactly_what_the_work_skill_would_offer():
    state = new_game_state(seed=42, location_id="edgewood_square")

    board = notice_board(state)

    assert board["configured"] is True
    assert board["location_id"] == "edgewood_square"
    posted = {row["id"] for row in board["notices"]}
    offered = {row["id"] for row in economy.available(state)}
    assert posted == offered, "the board and query_work disagree about the work"


def test_every_notice_carries_its_wage_arithmetic():
    state = new_game_state(seed=42, location_id="edgewood_square")

    for row in notice_board(state)["notices"]:
        for key in ("id", "name", "skill", "difficulty", "hours",
                    "expected_wage", "wage_breakdown"):
            assert key in row, f"notice {row.get('id')} lost its {key}"


def test_a_place_with_no_work_posts_an_empty_board_not_an_error():
    state = new_game_state(seed=42, location_id="forest_clearing")

    board = notice_board(state)

    assert board["notices"] == []
    assert board["location_name"] == "Forest Clearing"


def test_the_board_names_work_posted_elsewhere():
    """The reason a notice board exists in the fiction: a reason to travel."""
    state = new_game_state(seed=42, location_id="forest_clearing")

    elsewhere = notice_board(state)["elsewhere"]

    assert elsewhere, "no jobs posted for other places at all"
    for row in elsewhere:
        assert row["location_id"] != "forest_clearing"
        assert "hiring" in row


# ---------------------------------------------------------------------------
# the route
# ---------------------------------------------------------------------------


def _app():
    from content.scenes.clockwork.clockwork_scene import create_app, reset_store

    reset_store()
    scene, app = create_app(testing=True, llm_fn=lambda _m: MOCK_STORYTELLER)
    return scene, app.test_client()


def test_the_route_requires_a_session():
    _, client = _app()
    assert client.get("/api/notices").status_code == 404


def test_the_route_serves_the_active_locations_board():
    scene, client = _app()
    started = client.post("/api/game/new", json={"player_name": "T"}).get_json()

    payload = client.get(
        "/api/notices", query_string={"session_id": started["session_id"]}
    ).get_json()

    assert payload["location_id"] == started["state"]["location_id"]
    assert "notices" in payload
    assert "shifts_per_day" in payload
