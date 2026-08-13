"""
Content integrity — cross-file referential checks.

WHY THIS FILE EXISTS: after P9 the data tree carries several hundred ids that
only mean something because another file agrees with them. A vendor stocks an
item id, a recipe consumes one, a quest grants one, the art manifest keys one,
and none of those files import each other. At this volume the dominant defect
is not a broken function, it is `wild_mushroom` versus `wild_mushrooms` -- a
reference that resolves to nothing, raises nothing, and quietly produces a shop
entry that cannot be bought. A referential-integrity pass catches that class
outright and is worth more here than any unit test on the loaders.

The heavy lifting lives in scripts/validate_content.py so the same checks can
run from the command line during content work.
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
from engine.skills.builtin.assistant import HINTS_BY_TIER, LORE_SNIPPETS
from scripts import validate_content

_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# the whole tree
# ---------------------------------------------------------------------------


def test_content_tree_has_no_broken_references():
    """The one assertion this file exists for."""
    errors = validate_content.errors_only()
    assert not errors, "\n".join(str(e) for e in errors)


def test_validator_reports_warnings_separately():
    """Advisories must not be able to fail a build by accident."""
    issues = validate_content.validate()
    assert all(i.severity in {"error", "warning"} for i in issues)


def test_validator_actually_detects_a_broken_reference():
    """
    Negative control.

    A green integrity suite is only meaningful if the checks can go red. This
    feeds the economy check a registry that is missing every item it stocks.
    """
    npc_ids = validate_content.load_npc_ids()
    issues = validate_content.check_economy(items={}, npc_ids=npc_ids)
    assert issues
    assert any("not in games/clockwork-dark/data/items/" in i.message for i in issues)


def test_validator_detects_a_dead_recipe_input():
    """The recipe check must notice an input that no longer exists."""
    issues = validate_content.check_recipes(items={})
    assert any("input item" in i.message for i in issues)


# ---------------------------------------------------------------------------
# locations
# ---------------------------------------------------------------------------


def test_canon_ids_survive_the_move_to_yaml():
    """CLAUDE.md pins these five. Renaming one invalidates every save file."""
    for canon in CANON_IDS:
        assert canon in LOCATIONS, canon
    assert CANONICAL_LOCATION_IDS == frozenset(CANON_IDS)


def test_original_edge_costs_are_unchanged():
    """
    The five original places kept their exact travel numbers.

    games/clockwork-dark/data/encounters/*.yaml and games/clockwork-dark/data/quests/** were balanced against these, and
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
    for path in sorted((_ROOT / directory).rglob("*.yaml")):
        with path.open(encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        rows.extend(data.get(key) or [])
    return rows


def test_item_registry_is_a_real_registry():
    items, issues = validate_content.load_items()
    assert not issues, "\n".join(str(i) for i in issues)
    assert len(items) >= 60
    tagged = {
        tag for row in items.values() for tag in (row.get("tags") or [])
    }
    assert validate_content.ITEM_TAGS == tagged


def test_every_quest_item_has_a_registry_entry():
    """P7 introduced these in quest effects and nowhere else."""
    items, _ = validate_content.load_items()
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
    recipes = _load_all("games/clockwork-dark/data/recipes", "recipes")
    assert len(recipes) >= 14
    assert {"baking", "herbalism", "mending"} <= {r.get("category") for r in recipes}
    assert {r["skill"] for r in recipes} <= validate_content.SKILLS
    assert {r["band"] for r in recipes} <= validate_content.BANDS


def test_lore_corpus_expanded():
    files = sorted((_ROOT / "games" / "clockwork-dark" / "data" / "lore").glob("*.md"))
    assert len(files) >= 18
    sections = sum(f.read_text(encoding="utf-8").count("\n## ") for f in files)
    assert sections >= 60


def test_assistant_hint_corpus_loaded_from_yaml():
    """The literals are gone; the pools come from games/clockwork-dark/data/assistant/hints.yaml."""
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
    with (_ROOT / "games" / "clockwork-dark" / "data" / "world" / "rumors.yaml").open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    rumors = data["rumors"]
    assert len(rumors) >= 55
    per_tier: dict[int, int] = {}
    for row in rumors:
        per_tier[row["tier"]] = per_tier.get(row["tier"], 0) + 1
    for tier in (1, 2, 3):
        assert per_tier.get(tier, 0) >= 15, per_tier


@pytest.mark.parametrize("directory", ["games/clockwork-dark/data/items", "games/clockwork-dark/data/recipes"])
def test_new_data_directories_are_versioned(directory: str):
    """Every content file declares a schema version, as the rest of the tree does."""
    for path in sorted((_ROOT / directory).rglob("*.yaml")):
        with path.open(encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        assert data.get("version") == 1, path
