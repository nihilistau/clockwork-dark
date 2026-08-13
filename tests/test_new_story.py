"""
The story scaffolder and its three templates.

Two kinds of claim, deliberately separated:

    1. The SCAFFOLDER behaves: tokens are rewritten, existing work is never
       overwritten, bad inputs are refused before a file is written.
    2. The TEMPLATES are sound: every scaffolded story validates cleanly
       against the real registry, and the minimal one activates and completes
       a no-LLM turn on the engine default scene -- which is the bar
       tests/test_scene_seam.py sets for a third story being born passing.

THE TEST SEAM. ``registry.discover()`` roots itself at ``project_root()``
(``engine/config.py::_ROOT``), and both ``engine.games.registry`` and
``engine.games.manifest`` import ``project_root`` into their own namespaces --
so patching those two names points discovery AND path validation at a temp
root without touching the config machinery. The scaffolder takes the games
directory as a parameter for the same reason: tests must be able to scaffold
somewhere the repo's own ``games/`` never sees.

Deep content loaders (locations, decks, tables) resolve through config paths
against the REAL repo root and are deliberately not exercised here; what the
templates promise structurally to each other -- a clock forcing a deck that
exists, endings matching epilogue rows, tables naming items that exist -- is
cross-checked at the YAML level instead, so a template edit that breaks a
coupling fails here rather than in a scaffolded story three weeks later.

Version: v0.1.0 [2026-08-14]
"""

from __future__ import annotations

import importlib.util
import json
import pathlib

import pytest
import yaml

from engine.games import registry

# The scaffolder is a script, not a package module; load it from its path.
_SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "new_story.py"
_spec = importlib.util.spec_from_file_location("new_story", _SCRIPT)
new_story = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(new_story)

TEMPLATES = ("minimal", "graph", "deck")

MOCK_STORYTELLER = json.dumps(
    {
        "tool_calls": [],
        "narration": "The scaffolded room answers.",
        "choices": [{"id": "a", "text": "Go on"}, {"id": "b", "text": "Wait"}],
    }
)


@pytest.fixture
def story_root(tmp_path, monkeypatch):
    """
    A temp repo root the registry believes in.

    ``games/`` for the scaffold, ``data/`` because every template declares
    ``paths.saves: data/saves`` and validation checks an output path's PARENT.
    """
    (tmp_path / "games").mkdir()
    (tmp_path / "data").mkdir()
    monkeypatch.setattr("engine.games.manifest.project_root", lambda: tmp_path)
    monkeypatch.setattr("engine.games.registry.project_root", lambda: tmp_path)
    return tmp_path


def _scaffold(root: pathlib.Path, template: str, slug: str = "") -> pathlib.Path:
    slug = slug or f"probe-{template}"
    return new_story.scaffold(slug, template=template, games_root=root / "games")


# ---------------------------------------------------------------------------
# 1. the scaffolder behaves
# ---------------------------------------------------------------------------


def test_the_cli_knows_exactly_the_templates_on_disk():
    assert new_story.available_templates() == sorted(TEMPLATES)


@pytest.mark.parametrize("template", TEMPLATES)
def test_no_token_survives_the_copy(story_root, template):
    """{{slug}} in an emitted file is a template leak the player would see."""
    destination = _scaffold(story_root, template)
    for path in destination.rglob("*"):
        if path.is_file():
            text = path.read_text(encoding="utf-8")
            assert "{{" not in text, f"unrewritten token in {path.name}"


def test_the_title_lands_where_the_title_goes(story_root):
    new_story.scaffold(
        "probe-titled",
        template="minimal",
        title="The Probe, Titled",
        games_root=story_root / "games",
    )
    data = yaml.safe_load(
        (story_root / "games" / "probe-titled" / "game.yaml").read_text(encoding="utf-8")
    )
    assert data["id"] == "probe-titled"
    assert data["title"] == "The Probe, Titled"


def test_an_omitted_title_is_derived_from_the_slug():
    assert new_story.default_title("brass-coast") == "Brass Coast"
    assert new_story.default_title("one") == "One"


def test_an_existing_story_is_never_overwritten(story_root):
    _scaffold(story_root, "minimal", slug="probe-once")
    marker = story_root / "games" / "probe-once" / "game.yaml"
    before = marker.read_text(encoding="utf-8")
    with pytest.raises(ValueError, match="never overwrites"):
        _scaffold(story_root, "graph", slug="probe-once")
    assert marker.read_text(encoding="utf-8") == before


@pytest.mark.parametrize("bad", ["", "Has Spaces", "UPPER", "-leading", "a"])
def test_a_bad_slug_is_refused_before_anything_is_written(story_root, bad):
    with pytest.raises(ValueError, match="slug"):
        new_story.scaffold(bad, template="minimal", games_root=story_root / "games")
    assert list((story_root / "games").iterdir()) == []


def test_an_unknown_template_is_refused_with_the_real_list(story_root):
    with pytest.raises(ValueError, match="minimal"):
        new_story.scaffold("probe-x", template="nope", games_root=story_root / "games")


# ---------------------------------------------------------------------------
# 2. every template emits a story the registry accepts
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("template", TEMPLATES)
def test_a_scaffolded_story_is_discovered_and_validates_clean(story_root, template):
    """
    The whole point of a template: registry.validate() == [] on day one.

    Discovery is asserted too, so the test fails if the scaffolder ever emits
    somewhere discover() does not look.
    """
    _scaffold(story_root, template)
    found = registry.discover()
    slug = f"probe-{template}"
    assert slug in found, f"discover() cannot see the scaffolded {template} story"
    assert registry.validate(found[slug]) == []


@pytest.mark.parametrize("template", TEMPLATES)
def test_every_template_declares_the_engine_default_scene(story_root, template):
    """
    tests/test_scene_seam.py holds every SHIPPED game to this; a template
    that scaffolds a drifting scene block would seed stories that fail it.
    """
    from engine.scenes.spec import SceneSpec, resolve_scene

    _scaffold(story_root, template)
    manifest = registry.get(f"probe-{template}")
    assert manifest is not None
    assert isinstance((manifest.extras or {}).get("scene"), dict)
    assert resolve_scene(manifest) == SceneSpec()


def test_the_minimal_roster_parses_and_is_pipeline_sized(story_root):
    """
    Two agents is MIN_AGENTS: the scaffold ships the multi-agent turn ON.
    Parsed directly rather than through active_roster(), which swallows
    roster errors into an empty cast by design.
    """
    from engine.agents.roster import load_roster

    destination = _scaffold(story_root, "minimal")
    roster = load_roster(destination / "agents.yaml", slug="probe-minimal")
    assert set(roster.agents) == {"world", "alex"}
    assert len(roster.pipeline_agents()) == 2
    assert roster.rules, "the negotiation table went missing"
    # The one interesting permission in the scaffold: reason-required write.
    assert roster.agents["alex"].needs_reason("standing")


@pytest.mark.parametrize(
    "template,expected",
    [
        ("minimal", {"standing"}),
        ("deck", {"favor", "composure", "suspicion"}),
    ],
)
def test_declared_state_schemas_parse(story_root, template, expected):
    from engine.state.schema import load_schema

    _scaffold(story_root, template)
    manifest = registry.get(f"probe-{template}")
    assert manifest is not None
    path = manifest.state_schema_path
    assert path is not None and path.is_file()
    schema = load_schema(path, slug=manifest.slug)
    assert set(schema.values) == expected


# ---------------------------------------------------------------------------
# 3. the minimal story plays a turn on the engine default scene
# ---------------------------------------------------------------------------


def test_the_minimal_scaffold_activates_and_completes_a_turn(story_root, monkeypatch):
    """
    tests/test_scene_seam.py proves a hand-written scratch manifest can do
    this; this proves the SCAFFOLDED one can -- activation included, so the
    manifest, schema, roster and opening all load through the real gates.
    Content paths resolve against the real repo root and find nothing, which
    is the forgiving-loader path every story runs until its content lands.
    """
    import engine.scenes.default_state as state_module
    from engine.persistence.saves import SaveStore
    from engine.scenes.default_state import DefaultSessionStore, run_turn

    _scaffold(story_root, "minimal")
    try:
        manifest = registry.activate("probe-minimal")
        assert manifest.slug == "probe-minimal"

        saves = SaveStore(root=story_root / "data" / "saves", slug="probe-minimal")
        monkeypatch.setattr(state_module, "get_save_store", lambda: saves)

        session = DefaultSessionStore().create(seed=7, llm_fn=lambda _m: MOCK_STORYTELLER)
        # The opening is the template's own, not any shipped story's.
        assert "kettle" in session.last_turn["narration"]
        assert len(session.last_turn["choices"]) == 3

        payload = run_turn(session, "The player chooses: Say something first")
        for key in ("narration", "choices", "state", "assistant", "tool_receipts"):
            assert key in payload, f"the turn payload lost {key}"
        assert payload["narration"], "the turn produced no narration"
    finally:
        # Undone before monkeypatch restores project_root, so this must not
        # try to activate a real game -- deactivate alone leaves the process
        # on the config default, which is how every other teardown leaves it.
        registry.deactivate()


# ---------------------------------------------------------------------------
# 4. the couplings each template promises itself, checked at the YAML level
# ---------------------------------------------------------------------------


def _read(path: pathlib.Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def test_the_deck_templates_structures_agree_with_each_other(story_root):
    destination = _scaffold(story_root, "deck")

    state = _read(destination / "state.yaml")
    clocks = _read(destination / "data" / "rules" / "clocks.yaml")
    endings = _read(destination / "data" / "rules" / "endings.yaml")
    index = _read(destination / "data" / "epilogues" / "epilogue_index.yaml")
    deck_files = {p.stem for p in (destination / "data" / "scenes").glob("*.yaml")}

    # A clock is declared twice, and the halves must be about the same clock.
    assert set(clocks["clocks"]) <= set(state["clocks"])

    # A forced scene names a deck that exists, by filename id.
    for name, clock in clocks["clocks"].items():
        for beat in clock.get("beats") or []:
            forced = beat.get("forces_scene")
            if forced:
                assert forced in deck_files, f"{name} forces a deck that does not exist"

    # Every ending has its epilogue row, and no row is an orphan.
    assert set(endings["classes"]) == {row["id"] for row in index["endings"]}
    # The fail-forward ending is a declared class, so eligibility can never
    # name something that cannot lock.
    assert endings["fail_forward"] in endings["classes"]

    # The index's prose file is the one that ships.
    assert (destination / "data" / "epilogues" / str(index["prose_source"])).is_file()


def test_the_graph_templates_ids_all_resolve(story_root):
    """The silent bug of the graph shape: a table naming a missing item."""
    destination = _scaffold(story_root, "graph")

    items = {
        row["id"]
        for row in _read(destination / "data" / "items" / "goods.yaml")["items"]
    }
    locations = set(
        _read(destination / "data" / "world" / "locations.yaml")["locations"]
    )

    forage = _read(destination / "data" / "tables" / "forage.yaml")
    for table in forage["tables"]:
        for pool in ("common", "uncommon"):
            for row in table.get(pool) or []:
                assert row["item_id"] in items, f"forage names missing {row['item_id']}"

    labour = _read(destination / "data" / "tables" / "labour.yaml")
    for job in labour["jobs"]:
        assert job["location_id"] in locations
        for row in job.get("in_kind") or []:
            assert row["item_id"] in items, f"wage in-kind names missing {row['item_id']}"

    for npc, stock in _read(destination / "data" / "economy.yaml").items():
        for side in ("sells", "buys"):
            for item_id in stock.get(side) or {}:
                assert item_id in items, f"{npc} {side} missing {item_id}"

    trade = _read(destination / "data" / "tables" / "trade.yaml")
    for npc, profile in (trade.get("vendors") or {}).items():
        assert profile["location"] in locations, f"{npc} trades at nowhere"

    # Danger and encounters agree: the one edge with a nonzero danger_dc is
    # the one the encounter file triggers on, both directions.
    encounters = _read(destination / "data" / "encounters" / "road.yaml")
    edges = {
        edge
        for row in encounters["encounters"]
        for edge in (row.get("triggers") or {}).get("edges") or []
    }
    assert {"crossroads>old_wood", "old_wood>crossroads"} <= edges


def test_each_template_carries_its_own_readme(story_root):
    """The scaffold's first instruction is 'read the README'; ship one."""
    for template in TEMPLATES:
        destination = _scaffold(story_root, template)
        readme = destination / "README.md"
        assert readme.is_file(), f"{template} scaffolds no README"
        assert "dev-story" in readme.read_text(encoding="utf-8"), (
            f"{template}'s README does not point at the worked example"
        )
