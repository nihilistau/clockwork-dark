"""
Content integrity — the flagship's own assertions.

WHY THIS FILE EXISTS: after P9 the data tree carries several hundred ids that
only mean something because another file agrees with them. A vendor stocks an
item id, a recipe consumes one, a quest grants one, the art manifest keys one,
and none of those files import each other. At this volume the dominant defect
is not a broken function, it is `wild_mushroom` versus `wild_mushrooms` -- a
reference that resolves to nothing, raises nothing, and quietly produces a shop
entry that cannot be bought.

THE REFERENTIAL PASS ITSELF MOVED. ``engine/games/validation.py`` runs it for
EVERY story through its manifest, ``tests/test_story_content_integrity.py``
asserts it per game, and ``scripts/validate_content.py`` is the CLI face. What
stays here is what is genuinely The Clockwork Dark's: its canon ids, its
original edge costs, its content volumes, and the unit tests for the location
loader.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from engine.game.locations import (
    CANON_IDS,
    CANONICAL_LOCATION_IDS,
    LOCATIONS,
    can_travel,
    get_edge,
    load_locations,
)
from engine.games import registry, validation
from engine.skills.builtin.assistant import HINTS_BY_TIER, LORE_SNIPPETS

_ROOT = Path(__file__).resolve().parents[1]
# The flagship's content tree. These tests are flagship-specific by charter,
# so the literal path is fine here -- engine code resolves via the manifest.
_DATA = _ROOT / "games" / "clockwork-dark" / "data"


def _flagship():
    manifest = registry.get("clockwork-dark")
    assert manifest is not None
    return manifest


# ---------------------------------------------------------------------------
# locations
# ---------------------------------------------------------------------------


def test_canon_ids_survive_the_move_to_yaml():
    """CLAUDE.md pins these five. Renaming one invalidates every save file."""
    for canon in CANON_IDS:
        assert canon in LOCATIONS, canon
    assert CANONICAL_LOCATION_IDS == frozenset(CANON_IDS)


def test_the_graph_declares_the_same_canon_the_engine_pins():
    """
    The `canon:` list in data/world/locations.yaml and the module tuple in
    engine/game/locations.py are two homes for one fact. The graph's copy is
    what the story validator enforces; this holds the two together so neither
    can drift.
    """
    doc = validation.load_story_locations(_flagship())
    assert validation.canon_location_ids(doc) == list(CANON_IDS)


def test_original_edge_costs_are_unchanged():
    """
    The five original places kept their exact travel numbers.

    data/encounters/*.yaml and data/quests/** were balanced against these, and
    tests/test_encounter.py asserts content exists for every dangerous edge.
    """
    assert get_edge("forest_clearing", "edgewood_square") == {
        "hours": 1,
        "danger_dc": 8,
        "awareness_delta": 0,
        "one_way": False,
    }
    assert get_edge("edgewood_square", "millhaven_gate") == {
        "hours": 4,
        "danger_dc": 12,
        "awareness_delta": 2,
        "one_way": False,
    }
    assert get_edge("edgewood_square", "edgewood_bakery")["hours"] == 0
    assert not can_travel("forest_clearing", "millhaven_gate")


def test_graph_expanded_into_concentric_rings():
    """DESIGN.md § Setting: deep forest, Edgewood, the Marches, the road in."""
    assert len(LOCATIONS) >= 18
    rings = {int(spec["ring"]) for spec in LOCATIONS.values()}
    assert {0, 1, 2}.issubset(rings)


def test_procgen_targets_are_now_reachable():
    """
    engine/game/procgen.py has always generated content for these ids.

    They were not in the graph, so `move_to` rejected them and every hidden
    path and barrow the generator produced was dead content.
    """
    for generated in ("deeper_forest", "old_barrows", "herb_glen"):
        assert generated in LOCATIONS, generated


def test_loader_skips_a_malformed_entry_instead_of_crashing(tmp_path: Path):
    """A bad entry must cost one place, not the whole map."""
    bad = tmp_path / "locations.yaml"
    bad.write_text(
        "version: 1\n"
        "locations:\n"
        "  good_place:\n"
        "    name: Good\n"
        "    ring: 1\n"
        "    evil_multiplier: 1.0\n"
        "    connections: {}\n"
        "  no_ring:\n"
        "    name: Bad\n"
        "    connections: {}\n"
        "  no_name:\n"
        "    ring: 1\n"
        "    connections: {}\n",
        encoding="utf-8",
    )
    graph = load_locations(bad)
    assert set(graph) == {"good_place"}


def test_loader_drops_an_edge_to_nowhere(tmp_path: Path):
    """A typo'd edge target must not become a room you can never leave."""
    bad = tmp_path / "locations.yaml"
    bad.write_text(
        "version: 1\n"
        "locations:\n"
        "  a:\n"
        "    name: A\n"
        "    ring: 0\n"
        "    connections:\n"
        "      nowhere: { hours: 1, danger_dc: 0, awareness_delta: 0 }\n",
        encoding="utf-8",
    )
    graph = load_locations(bad)
    assert graph["a"]["connections"] == {}


def test_loader_mirrors_a_missing_return_edge(tmp_path: Path):
    """One-directional edges are typos; the loader repairs rather than strands."""
    bad = tmp_path / "locations.yaml"
    bad.write_text(
        "version: 1\n"
        "locations:\n"
        "  a:\n"
        "    name: A\n"
        "    ring: 0\n"
        "    connections:\n"
        "      b: { hours: 2, danger_dc: 3, awareness_delta: 1 }\n"
        "  b:\n"
        "    name: B\n"
        "    ring: 0\n"
        "    connections: {}\n",
        encoding="utf-8",
    )
    graph = load_locations(bad)
    assert graph["b"]["connections"]["a"]["hours"] == 2
    assert graph["b"]["connections"]["a"]["mirrored"] is True


def test_loader_honours_one_way(tmp_path: Path):
    """An explicit one_way edge is a design choice and must survive."""
    one_way = tmp_path / "locations.yaml"
    one_way.write_text(
        "version: 1\n"
        "locations:\n"
        "  a:\n"
        "    name: A\n"
        "    ring: 0\n"
        "    connections:\n"
        "      b: { hours: 1, danger_dc: 0, awareness_delta: 0, one_way: true }\n"
        "  b:\n"
        "    name: B\n"
        "    ring: 0\n"
        "    connections: {}\n",
        encoding="utf-8",
    )
    graph = load_locations(one_way)
    assert graph["b"]["connections"] == {}


def test_loader_returns_empty_on_a_missing_file(tmp_path: Path):
    """An unreadable map is logged, not raised -- it must not abort a turn."""
    assert load_locations(tmp_path / "does_not_exist.yaml") == {}


# ---------------------------------------------------------------------------
# volume
# ---------------------------------------------------------------------------


def _load_all(directory: str, key: str) -> list[dict]:
    rows: list[dict] = []
    for path in sorted((_DATA / directory).rglob("*.yaml")):
        with path.open(encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        rows.extend(data.get(key) or [])
    return rows


def test_item_registry_is_a_real_registry():
    items, issues = validation.load_story_items(_flagship())
    assert not issues, "\n".join(str(i) for i in issues)
    assert len(items) >= 60
    tagged = {
        tag for row in items.values() for tag in (row.get("tags") or [])
    }
    # The flagship uses exactly the engine's tag set -- its items predate
    # per-story tags and the engine branches on every one of these.
    assert validation.ENGINE_ITEM_TAGS == tagged


def test_every_quest_item_has_a_registry_entry():
    """P7 introduced these in quest effects and nowhere else."""
    items, _ = validation.load_story_items(_flagship())
    for item_id in (
        "festival_honey",
        "cut_reed",
        "winter_ration",
        "nessas_drawing",
        "fourth_verse",
        "brass_shard",
        "copied_list",
        "the_written_name",
        "ninth_pin",
    ):
        assert item_id in items, item_id


def test_recipes_cover_baking_herbalism_and_mending():
    recipes = _load_all("recipes", "recipes")
    assert len(recipes) >= 14
    assert {"baking", "herbalism", "mending"} <= {r.get("category") for r in recipes}
    assert {r["skill"] for r in recipes} <= validation.story_skills(_flagship())
    assert {r["band"] for r in recipes} <= validation.story_bands(_flagship())


def test_lore_corpus_expanded():
    files = sorted((_DATA / "lore").glob("*.md"))
    assert len(files) >= 18
    sections = sum(f.read_text(encoding="utf-8").count("\n## ") for f in files)
    assert sections >= 60


def test_assistant_hint_corpus_loaded_from_yaml():
    """The literals are gone; the pools come from data/assistant/hints.yaml."""
    total = sum(len(pool) for pool in HINTS_BY_TIER.values())
    assert total >= 40
    for tier in (1, 2, 3):
        assert HINTS_BY_TIER[tier], tier
    assert "clockwork_dark" in LORE_SNIPPETS
    assert LORE_SNIPPETS["clockwork_dark"]["min_tier"] == 3


def test_assistant_hints_stay_in_world():
    """
    The Assistant is folklore, not a tutorial.

    Mechanical vocabulary in a hint is the single failure mode that breaks the
    fiction, and it is easy to introduce by accident while writing content.
    """
    banned = ("DC ", "roll ", "stat ", "quest log", "the player", "click", "%")
    for pool in HINTS_BY_TIER.values():
        for hint in pool:
            lowered = hint.lower()
            for token in banned:
                assert token not in lowered, f"{token!r} in hint: {hint}"


def test_rumor_pool_expanded_across_tiers():
    with (_DATA / "world" / "rumors.yaml").open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    rumors = data["rumors"]
    assert len(rumors) >= 55
    per_tier: dict[int, int] = {}
    for row in rumors:
        per_tier[row["tier"]] = per_tier.get(row["tier"], 0) + 1
    for tier in (1, 2, 3):
        assert per_tier.get(tier, 0) >= 15, per_tier


@pytest.mark.parametrize("directory", ["items", "recipes"])
def test_new_data_directories_are_versioned(directory: str):
    """Every content file declares a schema version, as the rest of the tree does."""
    for path in sorted((_DATA / directory).rglob("*.yaml")):
        with path.open(encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        assert data.get("version") == 1, path


# ---------------------------------------------------------------------------
# few-shot examples
# ---------------------------------------------------------------------------

#: Scenery that exists ONLY in prompts/examples.json. See the test below.
EXAMPLE_ONLY_NOUNS = ("Coldharrow", "Harrowmere", "salt-house", "drover")


def test_the_few_shots_are_set_somewhere_the_game_is_not():
    """
    A few-shot donates its FURNITURE, not just its format.

    Both examples used to be set in real Edgewood -- Maris at her flue, a
    watchman at the gate -- and the model duly imported them. A fresh run whose
    opening was a forest clearing narrated "you turn your back on the watchman",
    and it read as plausible, because Edgewood does have a gate watch. That is
    the whole problem: the leak was invisible.

    They are now set at Coldharrow and Harrowmere, which exist nowhere in this
    story. The model may still borrow the scenery -- that is what few-shots do
    -- but borrowing it is now a visible bug rather than a plausible sentence.
    This test keeps those nouns unique, so the diagnostic stays sharp.
    """
    examples = _ROOT / "games" / "clockwork-dark" / "prompts" / "examples.json"
    text = examples.read_text(encoding="utf-8")
    for noun in EXAMPLE_ONLY_NOUNS:
        assert noun.lower() in text.lower(), f"examples no longer mention {noun!r}"

    haystack = [p for p in _DATA.rglob("*") if p.is_file() and p.suffix in {".yaml", ".json", ".md"}]
    for noun in EXAMPLE_ONLY_NOUNS:
        for path in haystack:
            body = path.read_text(encoding="utf-8", errors="ignore")
            assert noun.lower() not in body.lower(), (
                f"{noun!r} is example-only scenery but now appears in {path.name}; "
                "either rename it here or pick different scenery for the few-shot, "
                "or a leaked example stops being detectable"
            )


def test_the_few_shots_still_voice_real_npcs():
    """
    Foreign scenery, real cast: `npc_id` is an enum built from whoever is in the
    room, so an example naming an invented id would teach a shape the grammar
    can never accept.
    """
    import json

    examples = _ROOT / "games" / "clockwork-dark" / "prompts" / "examples.json"
    rows = json.loads(examples.read_text(encoding="utf-8"))
    voiced = set()
    for row in rows:
        if row.get("role") != "assistant":
            continue
        payload = json.loads(row["content"])
        for voice in payload.get("npc_voices") or []:
            voiced.add(voice["npc_id"])
        for subject in (payload.get("ledger_delta") or {}).get("npc_disposition") or {}:
            voiced.add(subject)
    assert voiced, "the examples no longer demonstrate npc_voices at all"

    schedules = _DATA / "world" / "npc_schedules.yaml"
    known = set((yaml.safe_load(schedules.read_text(encoding="utf-8")) or {}).get("npcs") or {})
    assert voiced <= known, f"examples voice unknown npcs: {sorted(voiced - known)}"
