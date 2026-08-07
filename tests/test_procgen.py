"""Procgen Edgewood tests — seeded consistency and schema."""

from __future__ import annotations

from engine.game.procgen import (
    generate_world,
    load_templates,
    new_game_state,
    npc_by_id,
    npcs_at_location,
    populate_state,
)
from engine.game.state import GameState, ProcgenResult

CANON_NPC_IDS = {
    "npc_maris",
    "npc_odran",
    "npc_ilya",
    "npc_sera",
    "npc_brindle",
}


def test_templates_load():
    templates = load_templates()
    assert "canon_npcs" in templates
    assert len(templates["canon_npcs"]) == 5


def test_same_seed_identical_npcs():
    a = generate_world(424242)
    b = generate_world(424242)
    assert a.npcs == b.npcs
    assert a.buildings == b.buildings
    assert a.forest == b.forest
    assert a.festival == b.festival
    assert a.shrine_mural == b.shrine_mural


def test_different_seeds_differ():
    a = generate_world(1)
    b = generate_world(2)
    proc_a = [n for n in a.npcs if not n.get("canon")]
    proc_b = [n for n in b.npcs if not n.get("canon")]
    assert proc_a != proc_b


def test_different_seeds_produce_different_buildings():
    """
    The village must actually vary.

    The type pool held exactly as many entries as were sampled, so sampling was
    a permutation and every seed built the same seven shops. The old test only
    compared NPCs, so it passed throughout.
    """
    names = [
        tuple(
            sorted(b["name"] for b in generate_world(seed).buildings if not b.get("canon"))
        )
        for seed in (1, 2, 999, 424242)
    ]
    assert len(set(names)) > 1


def test_canon_npcs_always_present():
    result = generate_world(999)
    ids = {n["id"] for n in result.npcs}
    assert CANON_NPC_IDS.issubset(ids)


def test_npc_and_building_counts():
    result = generate_world(12345)
    assert len(result.npcs) == 8
    assert 10 <= len(result.buildings) <= 16
    assert all(n.get("id") and n.get("name") for n in result.npcs)
    assert all(b.get("id") and b.get("name") for b in result.buildings)


def test_building_names_are_unique_within_a_village():
    for seed in (3, 55, 8080):
        names = [b["name"] for b in generate_world(seed).buildings]
        assert len(names) == len(set(names))


def test_npc_names_are_unique():
    for seed in (3, 55, 8080):
        names = [n["name"] for n in generate_world(seed).npcs]
        assert len(names) == len(set(names))


def test_forest_schema():
    result = generate_world(77)
    forest = result.forest
    assert len(forest.get("forage_nodes", [])) == 6
    assert len(forest.get("hidden_paths", [])) == 2
    assert forest.get("barrow_dungeon", {}).get("optional") is True


def test_festival_and_shrine():
    result = generate_world(88)
    assert result.festival.get("name")
    assert result.festival.get("season")
    assert result.shrine_mural
    assert result.bakery_job_day == 3


def test_npcs_at_location():
    result = generate_world(100)
    bakery_npcs = npcs_at_location(result, "edgewood_bakery")
    assert any(n["id"] == "npc_maris" for n in bakery_npcs)
    maris = npc_by_id(result, "npc_maris")
    assert maris is not None
    assert maris["role"] == "baker"


def test_procgen_result_helpers():
    result = generate_world(55)
    assert result.npc_by_id("npc_ilya")["location_id"] == "tinker_caravan"
    square = result.npcs_at("edgewood_square")
    assert len(square) >= 2


def test_populate_state():
    state = GameState()
    procgen = populate_state(state, seed=31415)
    assert state.procgen.seed == 31415
    assert len(procgen.npcs) == 8


def test_new_game_state_defaults():
    state = new_game_state(player_name="Alden", archetype="wayfarer", seed=42)
    assert state.player_name == "Alden"
    assert state.location_id == "forest_clearing"
    assert state.procgen.seed == 42
    assert state.procgen.npc_by_id("npc_maris") is not None


def test_procgen_round_trip():
    state = new_game_state(seed=2026)
    restored = GameState.from_dict(state.to_save_dict())
    assert restored.procgen.seed == 2026
    assert restored.procgen.npcs == state.procgen.npcs
    assert restored.procgen.buildings == state.procgen.buildings
    assert restored.procgen.forest == state.procgen.forest