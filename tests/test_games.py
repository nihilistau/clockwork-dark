"""
Multi-Game Engine Tests
=======================

Two questions, and the second is the interesting one.

    1. Does the seam work?   discovery, validation, activation, cache
                             invalidation, save namespacing, the HTTP payload.
    2. Does the engine produce THIS STORY'S outcomes?

A test that asserts "the drowned-carillon locations file loaded" proves a
loader ran. It does not prove the game is playable, and it is exactly the test
that passes while every mechanic still serves the previous story out of a warm
cache. So the retarget section below drives real mechanics -- encounter
eligibility off the edge's danger_dc, approach gating off an item id, a
sympathy check at the legendary band, effect application, a quest predicate --
and asserts the Brass Coast comes out the other end.

Version: v0.1.0 [2026-08-08]
"""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any, Iterator

import pytest

from engine import config as config_module
from engine.game import checks as checks_module
from engine.game import encounter as encounter_module
from engine.game import locations as locations_module
from engine.game import quests as quests_module
from engine.game import reputation as reputation_module
from engine.game.state import EvilPhase, GameState, InventoryItem
from engine.games import ENGINE_VERSION
from engine.games import caches as caches_module
from engine.games import manifest as manifest_module
from engine.games import registry
from engine.persistence import saves as saves_module
from engine.world import npc_sim as npc_sim_module

CLOCKWORK = "clockwork-dark"
CARILLON = "drowned-carillon"


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def carillon() -> Iterator[Any]:
    """
    Activate The Drowned Carillon for one test, then put it back.

    The teardown is not optional. Activation mutates process-global config and
    a dozen module caches, so a leaked activation would fail whichever of the
    other 625 tests happened to run next -- which is the exact failure mode
    this whole package exists to prevent.
    """
    manifest = registry.activate(CARILLON)
    try:
        yield manifest
    finally:
        registry.deactivate()


@pytest.fixture
def coast_state(carillon: Any) -> GameState:
    """A run standing on Bellfounders' Quay with the world already turning."""
    state = GameState()
    state.location_id = carillon.entry_location
    state.evil_phase = EvilPhase.SPREADING
    state.evil_progress = 0.55
    state.awareness = 30
    # world_day and world_hour are derived, not stored: day 12, hour 6.
    state.world_clock_hours = 11 * 24 + 6
    return state


# ---------------------------------------------------------------------------
# 1. manifest parsing and the version gate
# ---------------------------------------------------------------------------


def test_engine_version_matches_the_save_envelope() -> None:
    """
    The gate and the save envelope must agree on what version this is.

    ``engine_requires`` is meaningless if the number it compares against is
    not the number written into every save.
    """
    assert ENGINE_VERSION == saves_module.ENGINE_VERSION


@pytest.mark.parametrize(
    ("requirement", "expected"),
    [
        ("", True),
        (">=0.2.0", True),
        (">=0.1.0", True),
        (">=0.3.0", False),
        ("0.2.0", True),  # bare means >=
        ("0.9", False),
        ("==0.2.0", True),
        ("==0.2.1", False),
        ("<1.0", True),
        (">=0.2.0, <1.0", True),
        (">=0.2.0, <0.2", False),
        ("nonsense", True),  # a typo in a gate must not refuse to launch
    ],
)
def test_version_gate(requirement: str, expected: bool) -> None:
    assert manifest_module.satisfies("0.2.0", requirement) is expected


def test_version_padding_treats_0_2_as_0_2_0() -> None:
    assert manifest_module.satisfies("0.2", "==0.2.0")
    assert manifest_module.parse_version("0.2.0-rc1") == (0, 2, 0)


def test_manifest_carries_unknown_keys_through_to_the_api(carillon: Any) -> None:
    """
    A story may need vocabulary the engine has not learned.

    The Drowned Carillon calls the evil phases low water / spring tide / flood
    mark / full chime. The engine keeps its own ids; the names ride along in
    ``extras`` so a picker can show them.
    """
    assert carillon.extras["phase_names"]["consuming"] == "full chime"
    assert carillon.to_dict()["phase_names"]["dormant"] == "low water"


# ---------------------------------------------------------------------------
# 2. discovery and validation
# ---------------------------------------------------------------------------


def test_discover_finds_both_shipped_games() -> None:
    found = registry.discover()
    assert set(found) >= {CLOCKWORK, CARILLON}
    assert found[CARILLON].title == "The Drowned Carillon"


def test_every_shipped_game_validates() -> None:
    for slug, manifest in registry.discover().items():
        assert registry.validate(manifest) == [], f"{slug} failed validation"


def test_flagship_manifest_never_contradicts_the_config_defaults() -> None:
    """
    Activating clockwork-dark must be a no-op merge.

    This is the compatibility bar in one assertion: if the flagship manifest
    ever disagrees with config/default.yaml, activating the default game
    silently moves content and the rest of the suite starts lying.

    AGREEMENT, not identity. The config declares defaults for optional
    structural systems (clocks, threads, endings, decks, challenge bounds)
    whose files do not exist for this story -- every loader returns empty on a
    missing file, so the default is harmless and makes the path repointable and
    visible to doctor.py. The manifest cannot declare them: validation requires
    a declared path to EXIST, so naming a file this story does not have would
    make the flagship unplayable. Demanding identity here would therefore force
    a choice between "the engine cannot default a path" and "a story must ship
    empty files it never reads".
    """
    defaults = {k: str(v) for k, v in config_module.get_config().section("paths").items()}
    declared = registry.discover()[CLOCKWORK].paths

    # Nothing declared may point somewhere else.
    disagreements = {
        key: (value, defaults[key])
        for key, value in declared.items()
        if key in defaults and value != defaults[key]
    }
    assert not disagreements, f"manifest disagrees with config: {disagreements}"

    # And nothing declared may be a key the engine does not know about, which
    # would be a silently unread path -- the original failure this file guards.
    assert not (set(declared) - set(defaults)), (
        f"manifest declares paths config has never heard of: "
        f"{sorted(set(declared) - set(defaults))}"
    )

    # Every path the config defaults and the manifest omits must be one the
    # engine tolerates being absent.
    # `prompts` joins them for the same reason: the flagship's persona and
    # few-shots are the engine's built-ins, so it ships no prompt directory and
    # declaring one would mean copying its own defaults into a file to satisfy
    # a test.
    # `art_root` likewise: its default IS the flagship's static tree, so the
    # flagship declaring it would be restating the default.
    optional = {
        "clocks", "threads", "endings", "decks", "challenge_bounds",
        "prompts", "art_root",
    }
    missing = set(defaults) - set(declared)
    assert missing <= optional, (
        f"flagship omits content paths that are not optional: {sorted(missing - optional)}"
    )


def test_validation_reports_every_problem_at_once(tmp_path: Path) -> None:
    manifest = manifest_module.from_dict(
        {
            "title": "",
            "engine_requires": ">=99.0.0",
            "paths": {"locations": "nope/missing.yaml", "quests": "also/missing"},
            "entry": {},
        },
        slug="broken-game",
        root=tmp_path,
    )
    problems = registry.validate(manifest)
    assert len(problems) >= 5
    assert any("engine_requires" in p for p in problems)
    assert any("paths.locations" in p for p in problems)
    assert any("paths.quests" in p for p in problems)
    assert any("entry.location_id" in p for p in problems)
    assert any("entry.archetypes" in p for p in problems)


def test_output_paths_are_validated_on_their_parent_not_themselves() -> None:
    """
    A save directory and a lore index do not exist until first use.

    Requiring them to exist would mean a freshly cloned game cannot be
    activated until somebody has already played it.
    """
    manifest = registry.discover()[CARILLON]
    lore_db = manifest.resolve(manifest.paths["lore_db"])
    assert not lore_db.exists()
    assert registry.validate(manifest) == []


def test_activating_a_game_that_does_not_exist_raises() -> None:
    with pytest.raises(registry.ActivationError) as excinfo:
        registry.activate("no-such-game")
    assert "no-such-game" in str(excinfo.value)
    assert registry.peek() is None


# ---------------------------------------------------------------------------
# 3. selection precedence
# ---------------------------------------------------------------------------


def test_selection_precedence(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(registry.GAME_ENV_VAR, raising=False)
    assert registry.resolve_slug() == CLOCKWORK

    monkeypatch.setenv(registry.GAME_ENV_VAR, CARILLON)
    assert registry.resolve_slug() == CARILLON

    # An explicit argument beats the environment.
    assert registry.resolve_slug(CLOCKWORK) == CLOCKWORK


# ---------------------------------------------------------------------------
# 4. the cache audit
# ---------------------------------------------------------------------------


def test_every_registered_cache_names_a_real_target() -> None:
    """
    The registry must not accumulate entries for things that moved.

    A stale entry is silent: it clears nothing and the audit still looks
    complete. Importing each module and checking the attribute is the only way
    to know the list is honest, so it is checked here rather than trusted.
    """
    import importlib

    for module_name, attr in caches_module.NULLED_ATTRIBUTES:
        module = importlib.import_module(module_name)
        assert hasattr(module, attr), f"{module_name} has no {attr}"

    for module_name, attr in caches_module.LRU_CACHES:
        module = importlib.import_module(module_name)
        func = getattr(module, attr, None)
        assert callable(getattr(func, "cache_clear", None)), f"{module_name}.{attr} is not lru_cached"

    for module_name, attr in caches_module.RELOADERS:
        module = importlib.import_module(module_name)
        assert callable(getattr(module, attr, None)), f"{module_name}.{attr} is not callable"

    for dst_name, dst_attr, src_name, src_attr in caches_module.RE_EXPORTS:
        assert hasattr(importlib.import_module(dst_name), dst_attr)
        assert hasattr(importlib.import_module(src_name), src_attr)


def test_reset_all_caches_is_idempotent_and_never_imports() -> None:
    import sys

    sys.modules.pop("engine.media.comfyui", None)
    caches_module.reset_all_caches()
    caches_module.reset_all_caches()
    assert "engine.media.comfyui" not in sys.modules


def test_scene_rules_engine_sees_the_new_map(carillon: Any) -> None:
    """
    The stale re-export that would reject every legal move in a new game.

    ``engine/mcp/scene_rules_engine.py`` does ``from ... import LOCATION_IDS``
    at import time, and ``reload_locations`` REBINDS that frozenset rather
    than mutating it. Without the RE_EXPORTS pass, R001 would validate travel
    against Edgewood while the player stood on a quay.
    """
    from engine.mcp import scene_rules_engine

    assert "bellfounders_quay" in scene_rules_engine.LOCATION_IDS
    assert "edgewood_square" not in scene_rules_engine.LOCATION_IDS


# ---------------------------------------------------------------------------
# 5. activation actually repoints every content system
# ---------------------------------------------------------------------------


def test_activation_repoints_every_content_system(carillon: Any) -> None:
    """
    One assertion per loader that holds a cache. Each would pass on a stale
    cache if the previous game's content were still in it, which is why every
    one names something that exists in exactly one of the two games.
    """
    assert set(locations_module.LOCATIONS) == {
        "tide_flats",
        "bellfounders_quay",
        "net_lofts",
        "lamp_house",
        "wet_steps",
        "sunken_nave",
        "choir_loft",
    }
    assert set(quests_module.load_arcs()) == {"tide_work", "the_stilling"}
    assert "still_the_carillon" in quests_module.load_quests()
    assert "bakery_apprentice" not in quests_module.load_quests()
    assert set(reputation_module.load_factions()["factions"]) == {
        "quayfolk",
        "bell_wardens",
        "inland_factors",
    }
    assert set(npc_sim_module.load_npc_schedules()["npcs"]) == {
        "npc_cael",
        "npc_vesh",
        "npc_halloran",
        "npc_orsel",
    }
    assert set(checks_module.load_archetypes()["archetypes"]) == {
        "net_mender",
        "lamp_keeper",
        "bell_founder",
    }
    assert checks_module.load_archetypes()["default"] == "net_mender"

    from engine.skills.builtin import assistant as assistant_module

    assert "the_carillon" in assistant_module.LORE_SNIPPETS
    assert "the_barrows" not in assistant_module.LORE_SNIPPETS

    from engine.skills.builtin import mechanics as mechanics_module

    # The economy loader moved out of the skill module and into
    # engine/game/trade.py, which is now what prices a trade. The assertion is
    # unchanged: activating a game must repoint paths.economy.
    from engine.game import trade as trade_module

    economy = trade_module.load_economy()
    assert set(economy) == {"npc_cael", "npc_vesh", "npc_halloran"}
    assert "damp_a_casting" in mechanics_module._load_recipes()
    assert "bind_sympathy_charm" not in mechanics_module._load_recipes()

    # Random tables are per-game too, as of the paths.tables fix. Before it,
    # engine/game/checks.py hardcoded data/tables/ and this coast drew
    # Edgewood's boons.
    from engine.game import checks as checks_for_tables

    boon_ids = {b["id"] for b in checks_for_tables._load_table("boons.yaml", "boons")}
    assert "low_water_luck" in boon_ids
    assert "forager_luck" not in boon_ids

    from engine.world import schedules as schedules_module

    assert "factor_arrival" in schedules_module.load_schedules()
    assert "caravan_arrival" not in schedules_module.load_schedules()
    rumor_ids = {r["id"] for r in schedules_module.load_rumors()["rumors"]}
    assert "the_interval" in rumor_ids


def test_deactivation_restores_the_flagship_content(carillon: Any) -> None:
    assert "bellfounders_quay" in locations_module.LOCATIONS
    registry.deactivate()
    assert "edgewood_square" in locations_module.LOCATIONS
    assert "bellfounders_quay" not in locations_module.LOCATIONS
    assert "bakery_apprentice" in quests_module.load_quests()


def test_reset_config_does_not_drop_the_active_game(carillon: Any) -> None:
    """
    Re-reading the YAML layers must not silently move the player's story.

    ``reset_config`` is called from a dozen places. If it cleared the overlay,
    any one of them would put a Drowned Carillon session back onto Edgewood's
    content mid-turn.
    """
    config_module.reset_config()
    assert config_module.get_config().get("paths.locations").startswith("games/drowned-carillon")
    assert "bellfounders_quay" in locations_module.LOCATIONS


# ---------------------------------------------------------------------------
# 6. per-game save namespacing
# ---------------------------------------------------------------------------


def test_saves_are_namespaced_by_game(carillon: Any) -> None:
    assert saves_module.saves_root().name == CARILLON
    assert saves_module.saves_root(CLOCKWORK).name == CLOCKWORK
    assert saves_module.saves_root(CARILLON) != saves_module.saves_root(CLOCKWORK)


def test_save_store_follows_the_active_game(carillon: Any) -> None:
    """The cached store must be dropped on activation, or it keeps the old root."""
    assert saves_module.get_save_store().root.name == CARILLON
    registry.deactivate()
    assert saves_module.get_save_store().root.name == CLOCKWORK


def test_legacy_flat_saves_migrate_into_the_default_namespace(tmp_path: Path) -> None:
    """
    A pre-namespacing data/saves/ is folded into the active game, once.

    Detected by an index.json sitting directly in the base directory; the
    namespaced layout never has one there.
    """
    base = tmp_path / "saves"
    (base / "abc123").mkdir(parents=True)
    (base / "abc123" / "save.json").write_text("{}", encoding="utf-8")
    (base / "index.json").write_text(
        json.dumps({"saves": [{"save_id": "abc123"}]}), encoding="utf-8"
    )

    saves_module._migrate_legacy(base, CLOCKWORK)

    assert (base / CLOCKWORK / "index.json").is_file()
    assert (base / CLOCKWORK / "abc123" / "save.json").is_file()
    assert not (base / "index.json").exists()


def test_migration_never_overwrites_an_existing_save(tmp_path: Path) -> None:
    base = tmp_path / "saves"
    (base / "abc123").mkdir(parents=True)
    (base / "abc123" / "save.json").write_text("legacy", encoding="utf-8")
    (base / "index.json").write_text("{}", encoding="utf-8")
    (base / CLOCKWORK / "abc123").mkdir(parents=True)
    (base / CLOCKWORK / "abc123" / "save.json").write_text("newer", encoding="utf-8")

    saves_module._migrate_legacy(base, CLOCKWORK)

    assert (base / CLOCKWORK / "abc123" / "save.json").read_text(encoding="utf-8") == "newer"
    assert (base / "abc123" / "save.json").read_text(encoding="utf-8") == "legacy"


def test_a_run_saves_and_loads_inside_its_own_namespace(tmp_path: Path, carillon: Any) -> None:
    store = saves_module.SaveStore(root=saves_module.saves_root().parent / CARILLON)
    store.root = tmp_path / CARILLON

    state = GameState()
    state.location_id = "sunken_nave"
    state.player_name = "Vesh's second pair of hands"
    save_id = store.save(state)

    loaded, _memory = store.load(save_id)
    assert loaded.location_id == "sunken_nave"
    assert (tmp_path / CARILLON / "index.json").is_file()


# ---------------------------------------------------------------------------
# 7. the HTTP payload behind the picker
# ---------------------------------------------------------------------------


def test_games_api_lists_both_games() -> None:
    from flask import Flask

    from engine.games.api import games_blueprint

    app = Flask(__name__)
    app.register_blueprint(games_blueprint())
    client = app.test_client()

    payload = client.get("/api/games").get_json()
    slugs = {row["slug"] for row in payload["games"]}
    assert {CLOCKWORK, CARILLON} <= slugs
    assert payload["default"] == CLOCKWORK

    carillon_row = next(r for r in payload["games"] if r["slug"] == CARILLON)
    assert carillon_row["playable"] is True
    assert carillon_row["problems"] == []
    assert carillon_row["entry_location"] == "bellfounders_quay"
    assert carillon_row["archetypes"] == ["net_mender", "lamp_keeper", "bell_founder"]

    one = client.get(f"/api/games/{CARILLON}").get_json()
    assert one["title"] == "The Drowned Carillon"
    assert client.get("/api/games/nope").status_code == 404


def test_games_api_never_activates_as_a_side_effect() -> None:
    from flask import Flask

    from engine.games.api import games_blueprint

    registry.deactivate()
    app = Flask(__name__)
    app.register_blueprint(games_blueprint())
    body = app.test_client().get("/api/games/active").get_json()
    assert body["manifest"] is None
    assert body["active"] == CLOCKWORK
    assert registry.peek() is None


# ---------------------------------------------------------------------------
# 8. the retarget proof: the engine produces THIS STORY'S outcomes
# ---------------------------------------------------------------------------


def _force_degree(monkeypatch: pytest.MonkeyPatch, degree: str) -> None:
    """
    Pin every skill check to one degree.

    ``resolve_approach`` takes no rng, so the dice are pinned at the seam
    instead. Everything downstream of the degree -- outcome selection, effect
    application, resolve stripping, scene termination -- is the real engine.
    """
    real_resolve = checks_module.resolve

    def fake_resolve(state: GameState, skill: str, difficulty: str, **kwargs: Any) -> Any:
        result = real_resolve(state, skill, difficulty, **kwargs)
        object.__setattr__(result, "degree", degree)
        return result

    monkeypatch.setattr(encounter_module.checks_module, "resolve", fake_resolve)


def test_every_dangerous_leg_on_this_coast_has_content(carillon: Any) -> None:
    """
    A danger roll with an empty table is a roll that can never pay off.

    The flagship suite asserts this for Edgewood. It has to hold for any game
    or the encounter system is decorative in the new one.
    """
    state = GameState()
    state.evil_phase = EvilPhase.SPREADING

    checked = 0
    for src, spec in locations_module.LOCATIONS.items():
        for dst, edge in spec["connections"].items():
            if int(edge.get("danger_dc", 0)) <= 0:
                continue
            checked += 1
            assert encounter_module.trigger_chance(state, src, dst) > 0.0
            assert encounter_module.eligible(state, src, dst), f"no content for {src}>{dst}"
    assert checked >= 6, "expected the coast to have dangerous legs in both directions"


def test_the_loft_stair_produces_the_tide_cantor(coast_state: GameState) -> None:
    """
    Trigger probability comes off this game's edge and this game's rules file.

    The Tide-Cantor is eligible on exactly one leg, and it is the only thing
    eligible there -- so drawing it is a statement about content, not luck.
    """
    eligible = encounter_module.eligible(coast_state, "sunken_nave", "choir_loft")
    assert [row["id"] for row in eligible] == ["the_tide_cantor"]

    drawn = encounter_module.roll_for_encounter(
        coast_state, "sunken_nave", "choir_loft", rng=random.Random(1)
    )
    assert drawn is not None and drawn["id"] == "the_tide_cantor"


def test_unmaking_is_a_sympathy_check_at_the_legendary_band(coast_state: GameState) -> None:
    """
    The source's sharpest idea, surviving the port.

    Sympathy "unmaking" keys off content, not code. Engine written for a brass
    thing in a birch stand four hundred miles inland offers `unmake_it`
    against a sea-chime because a YAML file said so.
    """
    encounter_module.begin(coast_state, "the_tide_cantor")
    offered = {a["id"]: a for a in encounter_module.available_approaches(coast_state)}

    assert offered["unmake_it"]["skill"] == "sympathy"
    assert offered["unmake_it"]["difficulty"] == "legendary"
    assert coast_state.encounter["threat"]["name"] == "The Tide-Cantor"
    assert coast_state.encounter["threat"]["resolve"] == 9


def test_wax_gates_an_approach_the_flagship_game_has_never_heard_of(
    coast_state: GameState,
) -> None:
    """
    ``default_approaches`` is table content, and its gate is an item id.

    ``stop_your_ears`` is merged into EVERY encounter in this game and into
    none in the flagship, and the engine enforces its ``requires_item`` gate
    without knowing what wax is.
    """
    encounter_module.begin(coast_state, "the_tide_cantor")
    assert "stop_your_ears" not in {a["id"] for a in encounter_module.available_approaches(coast_state)}

    coast_state.inventory.append(
        InventoryItem(id="wax_earplugs", name="Wax earplugs", qty=2, tags=["charm"])
    )
    assert "stop_your_ears" in {a["id"] for a in encounter_module.available_approaches(coast_state)}

    # And the flagship game has no such approach anywhere.
    registry.deactivate()
    flagship = GameState()
    flagship.evil_phase = EvilPhase.SPREADING
    encounter_module.begin(flagship, "brass_in_the_birch")
    assert "stop_your_ears" not in {
        a["id"] for a in encounter_module.available_approaches(flagship)
    }


def test_naming_the_cantor_unmakes_it_and_yields_this_story_s_relic(
    coast_state: GameState, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    The whole chain, end to end, through untouched engine code.

    A `sympathy` check resolves, the crit_success block applies, the scene
    ends, a flag no other game sets is set, and an item id no other game
    defines lands in the inventory.
    """
    _force_degree(monkeypatch, "crit_success")
    encounter_module.begin(coast_state, "the_tide_cantor")

    receipt = encounter_module.resolve_approach(coast_state, "unmake_it")

    assert receipt["ok"] is True
    assert receipt["degree"] == "crit_success"
    assert "unmade" in receipt["text"] or "name" in receipt["text"]
    assert coast_state.flags.get("nf_cantor_unmade") is True
    # A crit_success is terminal per this game's rules.yaml `ends_on`, so the
    # scene is over in one round rather than grinding down 9 resolve.
    assert encounter_module.active(coast_state) is False
    assert receipt["round"] == 1

    carried = {item.id: item.qty for item in coast_state.inventory}
    assert carried.get("tuning_fork") == 1
    assert coast_state.awareness >= 10


def test_the_relic_satisfies_the_quest_stage_it_was_written_for(
    coast_state: GameState,
) -> None:
    """
    The ported contract's completion condition, evaluated by the quest engine.

    ``still_the_carillon`` finishes on any one of three things: the Cantor's
    fork, a damping cloth, or the flag set by unmaking it. All three are
    ordinary engine predicates over this game's content.
    """
    quest = quests_module.load_quests()["still_the_carillon"]
    final = quest["stages"][-1]
    assert final["id"] == "still_the_pipes"

    predicate = final["complete_when"]
    assert quests_module.evaluate_condition(coast_state, predicate) is False

    coast_state.inventory.append(
        InventoryItem(id="tuning_fork", name="Drowned tuning-fork", qty=1, tags=["quest"])
    )
    assert quests_module.evaluate_condition(coast_state, predicate) is True


def test_the_quiet_life_is_a_whole_arc_here_too(carillon: Any) -> None:
    """
    The thesis, transplanted: mending nets is a way to finish the game.

    ``tide_work`` is the default arc, it is worth zero plot involvement, and
    nothing gates it.
    """
    arcs = quests_module.load_arcs()
    assert arcs["tide_work"]["default"] is True
    assert quests_module.arc_involvement("tide_work") == 0.0
    assert quests_module.arc_involvement("the_stilling") == 20.0
    assert quests_module.arc_order("tide_work") < quests_module.arc_order("the_stilling")

    tide_work = [q for q in quests_module.load_quests().values() if q["arc"] == "tide_work"]
    assert {q["id"] for q in tide_work} == {"carry_the_lamp_oil", "mend_the_nets"}


def test_archetype_bonuses_come_from_this_game_s_rules(carillon: Any) -> None:
    """
    A bell-founder is better at sympathy than a net-mender, per this game's
    archetypes.yaml, and engine/game/checks.py reads that file and no other.
    """
    founder = GameState()
    founder.archetype = "bell_founder"
    mender = GameState()
    mender.archetype = "net_mender"

    founder_mods = dict(checks_module.gather_modifiers(founder, "sympathy"))
    mender_mods = dict(checks_module.gather_modifiers(mender, "sympathy"))
    assert sum(founder_mods.values()) > sum(mender_mods.values())
