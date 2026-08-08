"""
The story-agnostic scene seam.

Three claims are under test, and they are the ones that decide whether a second
story can ship its own screens rather than inheriting the flagship's:

    1. A story declares its scene and its screens in game.yaml, and every
       field defaults to today's behaviour so neither shipped game moves.
    2. The scene mounts what the manifest names -- including nothing.
    3. The session store is the engine's, and the two frames a run opens on
       are the story's, injected rather than inherited.

Plus the boring one that keeps the seam from becoming a hole: a `scene:` block
naming something that is not a dotted import path is refused, not imported.

Version: v0.1.0 [2026-08-08]
"""

from __future__ import annotations

import json

import pytest
from flask import Blueprint, jsonify

from engine.games import registry
from engine.games.manifest import from_dict
from engine.scenes.spec import (
    DEFAULT_SCENE_MODULE,
    DEFAULT_SCENE_NAME,
    DEFAULT_STORY_BLUEPRINT,
    SceneSpec,
    load_story_blueprint,
    resolve_scene,
    scene_port,
)

MOCK_STORYTELLER = json.dumps(
    {
        "tool_calls": [],
        "narration": "Mist clings to the birch trunks.",
        "choices": [{"id": "a", "text": "Walk"}, {"id": "b", "text": "Stay"}],
    }
)


def _manifest(**data):
    """A manifest carrying only the extras a test cares about."""
    return from_dict({"title": "T", **data}, slug="test-game")


# -- 1. what a manifest declares -------------------------------------------


def test_a_manifest_with_no_scene_block_gets_todays_behaviour():
    """
    The compatibility bar. No shipped game declares `scene:`, so every one must
    resolve to the Clockwork scene and the Clockwork story blueprint.
    """
    spec = resolve_scene(_manifest())
    assert spec == SceneSpec()
    assert spec.name == DEFAULT_SCENE_NAME
    assert spec.module == DEFAULT_SCENE_MODULE
    assert spec.blueprint == DEFAULT_STORY_BLUEPRINT


@pytest.mark.parametrize("slug", ["clockwork-dark", "wicked-garden"])
def test_every_shipped_game_resolves_to_the_clockwork_scene(slug):
    manifest = registry.get(slug)
    assert manifest is not None, f"games/{slug}/game.yaml is missing"
    assert resolve_scene(manifest) == SceneSpec()


def test_a_story_may_name_its_own_scene_and_screens():
    """
    The targets here are DELIBERATELY FICTIONAL. `resolve_scene` parses and
    validates a dotted target; it does not import one, and nothing in this test
    ever will. Naming a real module would make the test look like an
    integration check and would tie it to whichever stories happen to ship.
    """
    spec = resolve_scene(
        _manifest(
            scene={
                "name": "example",
                "module": "games.example_story.scene",
                "blueprint": "games.example_story.api:story_blueprint",
            }
        )
    )
    assert spec.name == "example"
    assert spec.module == "games.example_story.scene"
    assert spec.blueprint == "games.example_story.api:story_blueprint"


def test_an_empty_blueprint_means_no_story_screens_not_the_flagships():
    """
    The distinction the seam turns on. Omitting the key inherits Clockwork's
    screens (compatibility); declaring it empty ships none. If these collapsed
    into each other a second story could never opt out.
    """
    assert resolve_scene(_manifest(scene={"blueprint": ""})).blueprint == ""
    assert resolve_scene(_manifest(scene={})).blueprint == DEFAULT_STORY_BLUEPRINT


@pytest.mark.parametrize(
    "value",
    [
        "../../evil",
        "/etc/passwd",
        "content.scenes.clockwork.clockwork_api:story_blueprint()",
        "http://example.com/x.py",
        "mod:attr:extra",
    ],
)
def test_a_scene_target_that_is_not_an_import_path_is_refused(value):
    """A manifest names code to run. It may only name an importable module."""
    spec = resolve_scene(_manifest(scene={"blueprint": value}))
    assert spec == SceneSpec(), "a refused target must fall back, never import"


def test_a_scene_block_that_is_not_a_mapping_is_ignored():
    assert resolve_scene(_manifest(scene="clockwork")) == SceneSpec()
    assert resolve_scene(_manifest(scene=["clockwork"])) == SceneSpec()


def test_resolve_scene_without_a_manifest_does_not_activate_a_game():
    """Asking which scene serves a story must not repoint config."""
    registry.deactivate()
    try:
        assert resolve_scene() == SceneSpec()
        assert registry.peek() is None, "resolve_scene activated a game as a side effect"
    finally:
        registry.activate("clockwork-dark")


# -- the port has one home --------------------------------------------------


def test_the_port_comes_from_config_not_a_literal():
    from engine.config import get_config

    assert scene_port("clockwork") == int(get_config().get("scene.clockwork.port"))


def test_an_unknown_scene_falls_back_rather_than_failing_to_bind():
    assert scene_port("no-such-scene", default=6000) == 6000


def test_scene_metadata_no_longer_carries_a_second_copy_of_the_port():
    """
    R: the number lived in config, SCENE_METADATA, FlaskScene.run and the
    launcher's --list line. Four homes, one of which the config could move.
    """
    from content.scenes.clockwork.clockwork_scene import SCENE_METADATA

    assert "port" not in SCENE_METADATA


# -- 2. what the scene mounts ----------------------------------------------


def _probe_blueprint(store):
    blueprint = Blueprint("probe_story", __name__)

    @blueprint.get("/api/probe")
    def probe():
        return jsonify({"store": store is not None})

    return blueprint


def test_load_story_blueprint_declines_quietly_on_an_empty_target():
    assert load_story_blueprint("", None) is None


def test_load_story_blueprint_survives_a_target_that_will_not_import():
    """A broken codex costs its own screens, never the whole scene."""
    assert load_story_blueprint("no.such.module:factory", None) is None
    assert load_story_blueprint("engine.api.art:no_such_factory", None) is None


def test_the_scene_mounts_the_blueprint_the_manifest_names(monkeypatch):
    monkeypatch.setattr(
        "engine.games.registry.entry_manifest",
        lambda: _manifest(scene={"blueprint": f"{__name__}:_probe_blueprint"}),
    )
    from content.scenes.clockwork.clockwork_scene import create_app, reset_store

    reset_store()
    _, app = create_app(testing=True, llm_fn=lambda _m: MOCK_STORYTELLER)
    client = app.test_client()

    assert client.get("/api/probe").get_json() == {"store": True}
    # Edgewood's journal is not served to a story that did not ask for it.
    assert client.get("/api/quests").status_code == 404
    # ...but every shared route still is.
    assert client.get("/api/settings").status_code == 200
    assert client.get("/api/saves").status_code == 200
    assert client.get("/api/archetypes").status_code == 200


def test_a_story_can_ship_no_screens_at_all(monkeypatch):
    monkeypatch.setattr(
        "engine.games.registry.entry_manifest",
        lambda: _manifest(scene={"blueprint": ""}),
    )
    from content.scenes.clockwork.clockwork_scene import create_app, reset_store

    reset_store()
    _, app = create_app(testing=True, llm_fn=lambda _m: MOCK_STORYTELLER)
    rules = {r.rule for r in app.url_map.iter_rules()}

    for story_route in ("/api/quests", "/api/codex/places", "/api/items", "/api/trade"):
        assert story_route not in rules
    for shared_route in ("/api/saves", "/api/settings", "/api/art", "/api/metrics"):
        assert shared_route in rules


def test_the_shared_set_carries_every_route_the_client_already_calls():
    """
    The client is being restructured against the current contract. These paths
    are not negotiable; a blueprint that quietly dropped one would only be
    found in the browser.
    """
    from content.scenes.clockwork.clockwork_scene import create_app, reset_store

    reset_store()
    _, app = create_app(testing=True, llm_fn=lambda _m: MOCK_STORYTELLER)
    rules = {r.rule for r in app.url_map.iter_rules()}

    for route in (
        "/",
        "/api/health",
        "/api/games",
        "/api/games/active",
        "/api/games/<slug>",
        "/api/archetypes",
        "/api/saves",
        "/api/saves/<save_id>",
        "/api/saves/<save_id>/load",
        "/api/settings",
        "/api/art",
        "/api/metrics",
        "/api/audio/<path:name>",
        "/api/media/<path:name>",
        "/api/voice/transcribe",
        "/api/game/new",
        "/api/game/state",
        "/api/game/choice",
        "/api/quests",
        "/api/codex/places",
        "/api/codex/souls",
        "/api/codex/things",
        "/api/items",
        "/api/recipes",
        "/api/trade",
    ):
        assert route in rules, f"{route} is no longer served"


# -- 3. the session store is the engine's ----------------------------------


def test_a_story_that_declares_no_opening_gets_a_blank_frame(tmp_path, monkeypatch):
    """
    An empty frame is correct-but-blank. Another story's forest is wrong AND
    looks deliberate, which is worse.

    The opening became DATA after this test was written: a story declares it in
    `entry.opening` and the engine store reads the active manifest, so no story
    needs a subclass to open on something. What has to stay true is that a
    story which declares nothing inherits nothing.
    """
    from engine.persistence.saves import SaveStore
    from engine.session import SessionStore

    monkeypatch.setattr("engine.games.registry.entry_manifest", lambda: None)

    store = SessionStore(save_store=lambda: SaveStore(root=tmp_path / "s", slug="t"))
    session = store.create(seed=1, llm_fn=lambda _m: MOCK_STORYTELLER)

    assert session.last_turn["narration"] == ""
    assert session.last_turn["choices"] == []
    assert "birch" not in json.dumps(session.last_turn)


def test_the_engine_store_opens_on_the_active_storys_declared_frame(tmp_path):
    """
    The other half: a story that DOES declare one gets its own, from the
    manifest, with no story code involved.
    """
    from engine.persistence.saves import SaveStore
    from engine.session import SessionStore

    store = SessionStore(save_store=lambda: SaveStore(root=tmp_path / "s", slug="t"))
    session = store.create(seed=1, llm_fn=lambda _m: MOCK_STORYTELLER)

    # The flagship is the active game under test, and it declares an opening.
    assert session.last_turn["narration"], "the declared opening never loaded"
    assert session.last_turn["choices"]


def test_the_clockwork_store_is_the_engine_store_with_its_frames_bound(tmp_path):
    from content.scenes.clockwork.clockwork_state import (
        ClockworkSessionStore,
        opening_narration,
    )
    from engine.session import SessionStore as EngineSessionStore

    assert issubclass(ClockworkSessionStore, EngineSessionStore)

    import content.scenes.clockwork.clockwork_state as state_module
    from engine.persistence.saves import SaveStore

    saves = SaveStore(root=tmp_path / "s", slug="clockwork-dark")
    original = state_module.get_save_store
    state_module.get_save_store = lambda: saves
    try:
        session = ClockworkSessionStore().create(seed=1, llm_fn=lambda _m: MOCK_STORYTELLER)
    finally:
        state_module.get_save_store = original

    assert session.last_turn["narration"] == opening_narration()
    assert session.last_turn["choices"]
    assert "assistant" in session.last_turn
    # The save landed in the temp store, which is the seam every existing test
    # patches. It must survive the move into engine/session.
    assert session.save_id and (tmp_path / "s").exists()


def test_game_session_is_importable_from_both_homes():
    from content.scenes.clockwork.clockwork_state import GameSession as StoryName
    from engine.session import GameSession as EngineName

    assert StoryName is EngineName
