"""
The Engine Assumes No Story
===========================

Phase 2 of the engine/story seam: every place the engine used to hold The
Clockwork Dark's answer as "the" default, asserted neutral. Each block below
names the default that was welded in and proves three things about it -- the
flagship still gets its own answer (from its own files), the second story gets
ITS own answer, and a story that declares nothing gets NOTHING rather than the
flagship.

    outage line     storyteller.py held "The forest holds its breath..." as a
                    Python literal; it is `entry.fallback_narration` now
    canon ids       locations.py held the flagship's five as CANON_IDS; the
                    graph file's own `canon:` list now
    procgen         the placement ids (edgewood_square, forest_clearing, the
                    barrow, the margin targets) were literals; template now,
                    and no template means no generation
    doom clock      ~30 modules read evil_progress unconditionally; the reads
                    are now behind `doom_enabled()`, which asks what the story
                    DECLARED -- the engine's own config rate does not count
    Place line      world_state_block resolved through the flagship-shaped
                    graph import; a story with no graph now gets the id
                    verbatim and a state with no position gets no line

Version: v0.1.0 [2026-08-13]
"""

from __future__ import annotations

import pytest

from engine.agents import prompts
from engine.agents import storyteller as storyteller_module
from engine.config import set_overlay
from engine.game import locations as locations_module
from engine.game import procgen
from engine.game.evil_ticker import EvilTicker, doom_enabled, reset_doom_capability
from engine.game.state import GameState
from engine.games import manifest as manifest_module
from engine.games import registry

FLAGSHIP_OUTAGE_LINE = "The forest holds its breath. Smoke drifts from a distant chimney."


@pytest.fixture(autouse=True)
def _restore_active_game():
    """Leave the process on whatever story it was running."""
    before = registry.active_slug()
    yield
    set_overlay(None)
    registry.activate(before)


def _synthetic_manifest(**entry) -> manifest_module.GameManifest:
    """A story that declares as little as possible."""
    entry.setdefault("location_id", "somewhere")
    entry.setdefault("archetypes", [])
    return manifest_module.from_dict(
        {"title": "Synthetic", "entry": entry}, slug="synthetic"
    )


# ---------------------------------------------------------------------------
# The outage line (entry.fallback_narration)
# ---------------------------------------------------------------------------


def test_the_flagship_outage_line_is_declared_not_hardcoded():
    """The exact sentence that lived in storyteller.py, now from its manifest."""
    registry.activate("clockwork-dark")
    assert storyteller_module.fallback_narration() == FLAGSHIP_OUTAGE_LINE
    assert registry.active().fallback_narration == FLAGSHIP_OUTAGE_LINE


def test_the_garden_outage_stays_in_the_gardens_register():
    registry.activate("wicked-garden")
    line = storyteller_module.fallback_narration()
    assert line != FLAGSHIP_OUTAGE_LINE
    assert "garden" in line.lower() or "briar" in line.lower()
    for noun in ("forest", "chimney", "smoke"):
        assert noun not in line.lower(), f"the Garden was handed the flagship's {noun!r}"


def test_a_story_that_declares_no_outage_line_gets_the_neutral_one(monkeypatch):
    monkeypatch.setattr(registry, "entry_manifest", _synthetic_manifest)
    line = storyteller_module.fallback_narration()
    assert line == storyteller_module.NEUTRAL_FALLBACK_NARRATION
    for noun in ("forest", "chimney", "garden", "briar", "edgewood", "village"):
        assert noun not in line.lower(), f"the neutral line names {noun!r}"


# ---------------------------------------------------------------------------
# Canon location ids
# ---------------------------------------------------------------------------


def test_canon_ids_are_the_active_storys_declaration():
    registry.activate("clockwork-dark")
    assert locations_module.CANON_IDS == (
        "forest_clearing",
        "edgewood_square",
        "edgewood_bakery",
        "tinker_caravan",
        "millhaven_gate",
    )
    assert locations_module.CANONICAL_LOCATION_IDS == frozenset(
        locations_module.CANON_IDS
    )


def test_a_story_that_pins_no_canon_gets_an_empty_tuple():
    registry.activate("wicked-garden")
    assert locations_module.CANON_IDS == ()
    assert locations_module.CANONICAL_LOCATION_IDS == frozenset()
    # And its graph is still fully loaded -- canon is a pin, not a gate.
    assert locations_module.LOCATIONS


def test_canon_swaps_with_the_active_game():
    registry.activate("wicked-garden")
    assert locations_module.CANON_IDS == ()
    registry.activate("clockwork-dark")
    assert "forest_clearing" in locations_module.CANON_IDS


# ---------------------------------------------------------------------------
# Procgen: template-driven, and silent without a template
# ---------------------------------------------------------------------------


def test_a_story_with_no_templates_generates_nothing():
    """
    The Garden declares no `procgen_templates` -- and used to receive six
    forage nodes, two hidden paths and a barrow anyway, placed on flagship ids
    its own map does not contain, because the placement ids and pools were
    code defaults.
    """
    registry.activate("wicked-garden")
    result = procgen.generate_world(4242)
    assert result.npcs == []
    assert result.buildings == []
    assert result.forest["forage_nodes"] == []
    assert result.forest["hidden_paths"] == []
    assert result.forest["barrow_dungeon"] == {}
    assert result.festival == {}
    assert result.shrine_mural == ""


def test_the_flagships_generation_is_unchanged_and_template_fed():
    registry.activate("clockwork-dark")
    result = procgen.generate_world(999)

    villagers = [n for n in result.npcs if not n.get("canon")]
    assert villagers
    assert all(n["location_id"] == "edgewood_square" for n in villagers)

    assert len(result.forest["forage_nodes"]) == 6
    assert all(
        f["location_id"] == "forest_clearing" for f in result.forest["forage_nodes"]
    )
    assert result.forest["barrow_dungeon"]["id"] == "barrow_dungeon"
    targets = {"deeper_forest", "old_barrows", "herb_glen"}
    assert result.forest["hidden_paths"]
    assert all(p["leads_to"] in targets for p in result.forest["hidden_paths"])


def test_entry_location_falls_back_to_the_graph_not_a_noun(monkeypatch):
    """No manifest answer: the first id in the loaded graph, then ''."""
    registry.activate("clockwork-dark")
    monkeypatch.setattr(registry, "entry_location", lambda default="": "")
    assert procgen.entry_location_id() == next(iter(locations_module.LOCATIONS))

    monkeypatch.setattr(locations_module, "LOCATIONS", {})
    assert procgen.entry_location_id() == ""


# ---------------------------------------------------------------------------
# The doom clock as a declared capability
# ---------------------------------------------------------------------------


def test_the_flagship_declares_doom_and_still_ticks():
    registry.activate("clockwork-dark")
    assert doom_enabled() is True
    state = GameState(location_id="forest_clearing")
    EvilTicker.advance(state, days_elapsed=5.0)
    assert state.evil_progress > 0.0


def test_the_garden_declares_no_doom():
    registry.activate("wicked-garden")
    assert doom_enabled() is False


def test_the_answer_swaps_with_activation():
    """The cached answer is invalidated by the caches registry, not by luck."""
    registry.activate("clockwork-dark")
    assert doom_enabled() is True
    registry.activate("wicked-garden")
    assert doom_enabled() is False
    registry.activate("clockwork-dark")
    assert doom_enabled() is True


def test_the_ticker_no_ops_for_an_undeclared_doom_even_with_an_engine_rate(monkeypatch):
    """
    The engine's config default (`world.evil_base_rate_per_day: 0.01`) must
    not enable doom for a story that never mentioned it. An engine number is
    not a story declaring an apocalypse.
    """
    registry.activate("clockwork-dark")  # engine config now has a nonzero rate
    monkeypatch.setattr(registry, "entry_manifest", _synthetic_manifest)
    reset_doom_capability()
    try:
        assert doom_enabled() is False
        state = GameState(location_id="somewhere")
        result = EvilTicker.advance(state, days_elapsed=10.0)
        assert result == 0.0
        assert state.evil_progress == 0.0
        # The monotonic contract survives the no-op.
        with pytest.raises(ValueError):
            EvilTicker.advance(state, days_elapsed=-1.0)
    finally:
        reset_doom_capability()


def test_a_declared_nonzero_rate_enables_doom_without_doom_effects(monkeypatch):
    synthetic = manifest_module.from_dict(
        {
            "title": "Synthetic",
            "entry": {"location_id": "somewhere", "archetypes": []},
            "settings": {"world": {"evil_base_rate_per_day": 0.05}},
        },
        slug="synthetic",
    )
    monkeypatch.setattr(registry, "entry_manifest", lambda: synthetic)
    reset_doom_capability()
    try:
        assert doom_enabled() is True
    finally:
        reset_doom_capability()


def test_the_gardens_prompt_carries_no_doom_line():
    registry.activate("wicked-garden")
    state = GameState(location_id="the_gate")
    block = prompts.world_state_block(
        state, {"evil_phase": "dormant", "story_pressure": 0.0}
    )
    assert "the pattern is" not in block
    assert "dormant" not in block
    # The engine's own pacing tone stays: it is not doom's.
    assert "the story wants to be" in block


def test_the_flagships_prompt_still_names_the_phase():
    registry.activate("clockwork-dark")
    state = GameState(location_id="forest_clearing")
    block = prompts.world_state_block(
        state, {"evil_phase": "stirring", "story_pressure": 80.0}
    )
    assert "the pattern is stirring" in block
    assert "the story wants to be urgent" in block


# ---------------------------------------------------------------------------
# The Place line for a story with no graph
# ---------------------------------------------------------------------------


def test_a_story_with_no_graph_gets_its_id_verbatim():
    registry.activate("clockwork-dark")
    set_overlay({"paths": {"locations": "games/no-such-story/world/locations.yaml"}})
    assert locations_module.LOCATIONS == {}

    state = GameState(location_id="nowhere_in_particular")
    block = prompts.world_state_block(state, {})
    assert "Place: nowhere_in_particular" in block.splitlines()
    # No flagship name leaked in as the display half.
    assert "forest" not in block.lower()


def test_a_state_with_no_position_has_no_place_line():
    registry.activate("clockwork-dark")
    set_overlay({"paths": {"locations": "games/no-such-story/world/locations.yaml"}})
    state = GameState()
    block = prompts.world_state_block(state, {})
    assert "Place:" not in block
