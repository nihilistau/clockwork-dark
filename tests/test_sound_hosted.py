"""The sound routes in hosted mode: behind the gate; a story outside hosting.stories is 404 (spec §10)."""

from __future__ import annotations

import pytest

from tests.hosted_app import build, login, teardown

# Not `loopback`: `hosted_app.build` binds nothing, so this runs in the parallel phase.


@pytest.fixture
def hosted(monkeypatch, tmp_path):
    try:
        yield build(monkeypatch, tmp_path, hosting={"stories": ["clockwork-dark"]})
    finally:
        teardown()


def test_the_routes_need_a_login(hosted) -> None:
    client = hosted.client()
    for url in ("/api/sounds", "/api/sounds/catalog", "/sound/_engine/sounds.yaml"):
        assert client.get(url).status_code == 401, url


def test_a_signed_in_account_is_served_and_only_the_hosted_stories_listed(hosted) -> None:
    _, password = hosted.add("alice")
    client = hosted.client()
    assert login(client, "alice", password).status_code in (302, 303)
    assert client.get("/api/sounds").status_code == 200
    stories = [row["slug"] for row in client.get("/api/sounds/catalog").get_json()["stories"]]
    assert stories == ["clockwork-dark"]
    assert client.get("/sound/read-receipts/files/x.ogg").status_code == 404
