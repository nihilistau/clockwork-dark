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
    """The opening, one turn (a typed line, the stub narrator) and, for READ RECEIPTS, one phone action (spec
    §14.1). Each answered 200 with a body, so an error can never pass as "no sound key" (v0.24.0 T14)."""
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
            payloads = {}
            opened = client.post("/api/game/new", json=_new_game_body(slug))
            assert opened.status_code == 200, (slug, opened.get_data(as_text=True)[:400])
            payloads["opening"] = opened.get_json()
            sid = payloads["opening"]["session_id"]
            if slug == "read-receipts":
                phone = client.post("/api/phone/action", json={"session_id": sid, "action": "wait", "target": "",
                                                               "args": {"until": "1h"}, "text": ""})
                assert phone.status_code == 200, (slug, phone.get_data(as_text=True)[:400])
                payloads["phone"] = phone.get_json()
                client.post("/api/phone/action", json={"session_id": sid, "action": "put_down", "target": "",
                                                        "args": {}, "text": ""})
            turn = client.post("/api/game/choice", json={"session_id": sid, "choice_id": "",
                                                         "custom_text": "look around"})
            assert turn.status_code == 200, (slug, turn.get_data(as_text=True)[:400])
            payloads["turn"] = turn.get_json()
            for name, body in payloads.items():
                assert isinstance(body, dict) and body, (slug, name)
                assert not (_keys(body) & SOUND_KEYS), (slug, name)
    finally:
        registry.deactivate()


def _new_game_body(slug: str) -> dict:
    """The body every story's /api/game/new takes (tests/social_fixtures.py opens READ RECEIPTS with the same)."""
    return {"seed": 3}


def test_dev_storys_catalogue_row_has_no_sounds_path() -> None:
    row = next(r for r in registry.catalog() if r["slug"] == "dev-story")
    assert "sounds" not in row["paths"]
