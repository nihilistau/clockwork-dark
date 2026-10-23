"""No turn or phone payload gains a sound key (spec Non-goals); dev-story's catalogue row never moves."""

from __future__ import annotations

import pytest

from engine.games import registry

SLUGS = sorted(registry.discover())

SOUND_KEYS = {"sound", "sounds", "sfx"}


def _keys(value) -> set[str]:
    """Every dict key anywhere in a JSON value (keys, not substrings)."""
    if isinstance(value, dict):
        return set(value) | {k for v in value.values() for k in _keys(v)}
    if isinstance(value, list):
        return {k for v in value for k in _keys(v)}
    return set()


@pytest.mark.parametrize("slug", SLUGS)
def test_no_payload_carries_a_sound_key(slug) -> None:
    import contextlib

    from engine.scenes.default_scene import create_app, reset_store
    from tests.social_fixtures import _quieted

    registry.activate(slug)
    quiet = _quieted() if slug == "read-receipts" else contextlib.nullcontext()
    try:
        with quiet:
            reset_store()
            _, app = create_app(testing=True, llm_fn=lambda _m: "{}")
            client = app.test_client()
            body = client.post("/api/game/new", json=_new_game_body(slug)).get_json() or {}
            assert not (_keys(body) & SOUND_KEYS), slug
    finally:
        registry.deactivate()


def _new_game_body(slug: str) -> dict:
    """The body every story's /api/game/new takes (tests/social_fixtures.py opens READ RECEIPTS with the same)."""
    return {"seed": 3}


def test_dev_storys_catalogue_row_has_no_sounds_path() -> None:
    row = next(r for r in registry.catalog() if r["slug"] == "dev-story")
    assert "sounds" not in row["paths"]
