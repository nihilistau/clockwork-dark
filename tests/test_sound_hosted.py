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


# T4 review #6 (decided in T9, when the first story that declares sounds exists): a story that declares sounds but is not
# in `hosting.stories` is outside the door. READ RECEIPTS declares since v0.24.0 T9, so the catalogue assertion bites; the file
# route is made to bite by giving that story a real .ogg (the stub manifest below), so a 404 can only be the gate's.
def _with_a_receipts_file(monkeypatch, tmp_path) -> None:
    from types import SimpleNamespace

    from engine.games import registry

    root = tmp_path / "rr-sounds"
    (root / "files").mkdir(parents=True)
    (root / "files" / "a.ogg").write_bytes(b"OggS" + b"\x00" * 60)
    real = registry.get
    stub = SimpleNamespace(paths={"sounds": "rr-sounds"}, resolve=lambda _p: root, title="Read Receipts")
    monkeypatch.setattr(registry, "get", lambda slug: stub if slug == "read-receipts" else real(slug))


def test_read_receipts_declares_sounds_so_its_absence_means_something() -> None:
    from engine.games import registry, sounds

    assert sounds.load_story(registry.discover()["read-receipts"]) is not None


def test_a_declaring_story_outside_hosting_stories_is_404_and_absent(hosted, monkeypatch, tmp_path) -> None:
    _with_a_receipts_file(monkeypatch, tmp_path)
    _, password = hosted.add("alice")
    client = hosted.client()
    assert login(client, "alice", password).status_code in (302, 303)
    assert client.get("/sound/read-receipts/files/a.ogg").status_code == 404
    slugs = [row["slug"] for row in client.get("/api/sounds/catalog").get_json()["stories"]]
    assert "read-receipts" not in slugs


def test_the_same_file_is_served_when_the_story_is_hosted(monkeypatch, tmp_path) -> None:
    """The positive control: with the story in `hosting.stories` the stub's file is served, so the 404 above is the gate's."""
    _with_a_receipts_file(monkeypatch, tmp_path)
    app = build(monkeypatch, tmp_path, hosting={"stories": ["clockwork-dark", "read-receipts"]})
    try:
        _, password = app.add("alice")
        client = app.client()
        assert login(client, "alice", password).status_code in (302, 303)
        assert client.get("/sound/read-receipts/files/a.ogg").status_code == 200
        slugs = [row["slug"] for row in client.get("/api/sounds/catalog").get_json()["stories"]]
        assert "read-receipts" in slugs
    finally:
        teardown()
