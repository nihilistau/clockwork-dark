"""
A story slug is a name, checked at one choke point (v0.20.0 T2 fix round 1;
review findings 2 and 4).

``manifest.is_valid_slug`` is ``SLUG_RE`` by ``fullmatch`` (a ``$`` let
``"abc\\n"`` through) plus the portable-name rules (``engine.names``: no
Windows device name). Every door that turns a client- or author-named slug
into a path asks it: ``registry.get`` (so ``/api/games/<slug>``), discovery,
``validate``, the studio's ``_safe_path`` and ``scripts/new_story.py``.

The findings: the studio's ``_safe_path("D:", ...)`` resolved onto another
drive, and ``GET /api/games/C:%5c...%5cdev-story`` read a manifest by
absolute path.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from engine.games import registry

REPO = Path(__file__).resolve().parents[1]

BAD = [
    "dev-story\n",
    "C:",
    "c:",
    "D:",
    "C:.",
    "con",
    "nul",
    "com1",
    "../dev-story",
    "a\\b",
    "Dev-Story",
    "",
    None,
    str(REPO / "games" / "dev-story"),
]


@pytest.mark.parametrize("slug", BAD)
def test_a_bad_slug_is_not_a_slug(slug: object) -> None:
    from engine.games.manifest import is_valid_slug

    assert not is_valid_slug(slug)


@pytest.mark.parametrize("slug", ["dev-story", "clockwork-dark", "hue-and-cry", "ab"])
def test_a_real_slug_is(slug: str) -> None:
    from engine.games.manifest import is_valid_slug

    assert is_valid_slug(slug)


@pytest.mark.parametrize("slug", [s for s in BAD if isinstance(s, str) and s])
def test_registry_get_answers_none_for_a_bad_slug(slug: str) -> None:
    assert registry.get(slug) is None


def test_the_games_route_refuses_an_absolute_path() -> None:
    """The review's probe: this answered 200 with dev-story's manifest."""
    from flask import Flask

    from engine.games.api import games_blueprint

    app = Flask(__name__)
    app.register_blueprint(games_blueprint())
    client = app.test_client()
    encoded = str(REPO / "games" / "dev-story").replace("\\", "%5c").replace("/", "%5c")
    res = client.get(f"/api/games/{encoded}")
    assert res.status_code == 404
    assert client.get("/api/games/dev-story").status_code == 200


def test_a_scene_target_with_a_trailing_newline_is_refused() -> None:
    """Finding 4's other half: a `$` pattern checked with `fullmatch`."""
    from engine.scenes.spec import _valid_target

    assert _valid_target("engine.scenes.default_scene")
    assert not _valid_target("engine.scenes.default_scene\n")
    assert not _valid_target("engine.scenes.default_api:story_blueprint\n")


def test_the_studio_refuses_a_drive_as_a_slug() -> None:
    from engine.studio.api import _safe_path

    for slug in ("C:", "c:", "D:", "C:.", "con"):
        with pytest.raises(ValueError):
            _safe_path(slug, "game.yaml")
