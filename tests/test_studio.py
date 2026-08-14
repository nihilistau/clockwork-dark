"""
The studio — authoring a story from the browser.

WHAT IT ADDS THAT THE TERMINAL DOES NOT HAVE. `scripts/author.py --promote` is
all-or-nothing and blind: it validates, then moves every draft into the live
tree at once. A drafting model produces content that loads, validates and plays
while doing nothing -- four such shapes were found in one nine-day draft and
are now ungrammatical -- and what remains is a matter of TASTE, which no
validator will ever catch. "Accept this one, rewrite that one, throw the third
away" is the verb that did not exist.

THE SECURITY TESTS ARE NOT DECORATION. This blueprint writes to disk on
request. A studio that can be talked into writing `../../engine/game/state.py`
is remote code execution with a nice front end, so `_safe_path` is tested
harder than anything else here -- including the shapes that are not substrings
anyone would grep for.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from engine.studio.api import _safe_path, studio_blueprint


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def client():
    """A Flask test client with only the studio mounted."""
    from flask import Flask

    app = Flask(__name__)
    app.register_blueprint(studio_blueprint())
    app.config.update(TESTING=True)
    return app.test_client()


# ---------------------------------------------------------------------------
# the rail
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "relative",
    [
        "../../engine/game/state.py",
        "../clockwork-dark/game.yaml",
        "data/../../../etc/passwd",
        "/etc/passwd",
        "C:/Windows/system.ini",
    ],
)
def test_a_path_cannot_escape_the_story(relative: str) -> None:
    """
    `resolve()` then `is_relative_to`, not string matching: `games/x/../../engine`
    contains no `..` a naive check would find once the OS has normalised it,
    and an absolute path contains no `..` at all.
    """
    with pytest.raises(ValueError):
        _safe_path("dev-story", relative)


@pytest.mark.parametrize("slug", ["", "..", "../clockwork-dark", "a/b", ".hidden", "no-such-story"])
def test_a_bad_slug_is_refused(slug: str) -> None:
    with pytest.raises(ValueError):
        _safe_path(slug, "game.yaml")


def test_a_real_path_resolves(tmp_path: Path) -> None:
    """The green control -- without it every refusal above proves nothing."""
    resolved = _safe_path("dev-story", "game.yaml")
    assert resolved.is_file()
    assert resolved.name == "game.yaml"


# ---------------------------------------------------------------------------
# reading
# ---------------------------------------------------------------------------


def test_every_story_is_listed_with_its_health(client) -> None:
    body = client.get("/api/studio/stories").get_json()
    slugs = {row["slug"] for row in body["stories"]}
    assert {"clockwork-dark", "wicked-garden", "neon-city", "dev-story"} <= slugs
    for row in body["stories"]:
        assert row["health"]["errors"] == 0, f"{row['slug']} is not clean"


def test_a_story_lists_its_editable_files(client) -> None:
    body = client.get("/api/studio/story/dev-story").get_json()
    paths = {row["path"] for row in body["files"]}
    assert "game.yaml" in paths
    assert any(p.endswith(".md") for p in paths)
    # Never a .py, a .db or a picture: this is a story editor, not a file
    # browser for the machine.
    assert not any(p.endswith(".py") for p in paths)


def test_reading_a_file_returns_it_verbatim(client) -> None:
    body = client.get("/api/studio/file?slug=dev-story&path=game.yaml").get_json()
    assert "id: dev-story" in body["text"]


def test_reading_outside_the_story_is_refused(client) -> None:
    response = client.get("/api/studio/file?slug=dev-story&path=../../launcher.py")
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# writing
# ---------------------------------------------------------------------------


def test_broken_yaml_never_reaches_disk(client, tmp_path: Path) -> None:
    """
    Parsed BEFORE anything touches disk. A syntax error is a 400 and not a
    broken story -- the editor cannot save what the game cannot read.
    """
    original = (ROOT / "games" / "dev-story" / "game.yaml").read_text(encoding="utf-8")
    response = client.put(
        "/api/studio/file",
        json={"slug": "dev-story", "path": "game.yaml", "text": "id: [unclosed\n"},
    )
    assert response.status_code == 400
    assert "YAML" in response.get_json()["error"]
    assert (ROOT / "games" / "dev-story" / "game.yaml").read_text(encoding="utf-8") == original


def test_a_write_reports_the_health_it_caused(client) -> None:
    """
    Validation runs AFTER the write and is reported rather than enforced. A
    story mid-edit is allowed to be briefly wrong; the author has to be told
    that it is.
    """
    path = ROOT / "games" / "dev-story" / "README.md"
    original = path.read_text(encoding="utf-8")
    try:
        body = client.put(
            "/api/studio/file",
            json={"slug": "dev-story", "path": "README.md", "text": original + "\n"},
        ).get_json()
        assert body["ok"] is True
        assert body["health"]["errors"] == 0
    finally:
        path.write_text(original, encoding="utf-8", newline="\n")


def test_writing_outside_the_story_is_refused(client) -> None:
    response = client.put(
        "/api/studio/file",
        json={"slug": "dev-story", "path": "../../launcher.py", "text": "print(1)"},
    )
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# validation and the review queue
# ---------------------------------------------------------------------------


def test_validation_is_reported_per_issue(client) -> None:
    body = client.get("/api/studio/validate/dev-story").get_json()
    assert body["issues"] == []


def test_drafts_carry_their_text(client, tmp_path: Path) -> None:
    """
    A review queue that listed filenames would be a worse `ls`. The point is to
    READ what the model wrote before it becomes part of the story.
    """
    draft = ROOT / "games" / "dev-story" / "data" / "drafts" / "item" / "probe.yaml"
    draft.parent.mkdir(parents=True, exist_ok=True)
    draft.write_text("items:\n  probe: {name: Probe}\n", encoding="utf-8")
    try:
        body = client.get("/api/studio/drafts/dev-story").get_json()
        rows = {row["path"]: row for row in body["drafts"]}
        key = "data/drafts/item/probe.yaml"
        assert key in rows
        assert "Probe" in rows[key]["text"]
        assert rows[key]["kind"] == "item"
    finally:
        draft.unlink(missing_ok=True)


def test_a_draft_can_be_thrown_away(client) -> None:
    draft = ROOT / "games" / "dev-story" / "data" / "drafts" / "item" / "reject_me.yaml"
    draft.parent.mkdir(parents=True, exist_ok=True)
    draft.write_text("items:\n  x: {name: X}\n", encoding="utf-8")

    response = client.post(
        "/api/studio/draft/reject",
        json={"slug": "dev-story", "path": "data/drafts/item/reject_me.yaml"},
    )
    assert response.status_code == 200
    assert not draft.exists()


def test_only_a_draft_may_be_rejected(client) -> None:
    """
    The counter-control. `reject` deletes, so it must refuse anything that is
    not in a drafts tree -- otherwise it is a delete-any-file endpoint.
    """
    response = client.post(
        "/api/studio/draft/reject",
        json={"slug": "dev-story", "path": "game.yaml"},
    )
    assert response.status_code == 400
    assert (ROOT / "games" / "dev-story" / "game.yaml").is_file()


def test_drafts_are_invisible_to_validation(client) -> None:
    """
    A half-finished draft must not fail the build. `DRAFTS_DIRNAME` is skipped
    by every loader and by the validator until a promote moves it.
    """
    draft = ROOT / "games" / "dev-story" / "data" / "drafts" / "item" / "nonsense.yaml"
    draft.parent.mkdir(parents=True, exist_ok=True)
    draft.write_text("items:\n  broken: {tags: [not-a-real-tag]}\n", encoding="utf-8")
    try:
        assert client.get("/api/studio/validate/dev-story").get_json()["issues"] == []
    finally:
        draft.unlink(missing_ok=True)
