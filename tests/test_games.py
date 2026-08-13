"""
Multi-Game Engine Tests
=======================

Two questions, and the second is the interesting one.

    1. Does the seam work?   discovery, validation, activation, cache
                             invalidation, save namespacing, the HTTP payload.
    2. Does the engine produce THIS STORY'S outcomes?

A test that asserts "the second story's locations file loaded" proves a loader
ran. It does not prove the game is playable, and it is exactly the test that
passes while every mechanic still serves the previous story out of a warm
cache. So the activation section below names, for every loader that holds a
cache, something that exists in exactly one of the two installed stories.

THE SECOND STORY IS THE WICKED GARDEN. It used to be The Drowned Carillon, a
near-copy of the flagship, which made it a weak witness: same mechanics,
different nouns, so a seam could look repointed while nothing structural had
been asked of it. The Garden is the harder case -- no combat, no encounters, no
quests, no economy, no travel graph in the flagship's sense -- and a path it
does not declare falls back to Edgewood's file rather than to nothing, which is
the failure this file exists to catch.

CARILLON CASES REMOVED WITH THE STORY. The retarget section that stood here
drove the Brass Coast's own mechanics end to end: encounter eligibility off an
edge's danger_dc, `stop_your_ears` gated on wax, a sympathy check at the
legendary band, the crit_success block, and the `still_the_carillon` quest
predicate. None of that content exists any more and none of it has a Garden
equivalent -- the Garden has no encounters and no quests at all. The same claim
for the surviving second story ("the engine produces THIS story's outcomes,
driven through the real loaders") lives in tests/test_wicked_garden_scenes.py,
which resolves every value, item, location and flag its ten day-chapters name.

Version: v0.2.0 [2026-08-09]
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator

import pytest

from engine import config as config_module
from engine.game import checks as checks_module
from engine.game import inventory as inventory_module
from engine.game import locations as locations_module
from engine.game import quests as quests_module
from engine.game import reputation as reputation_module
from engine.game.state import GameState
from engine.games import ENGINE_VERSION
from engine.games import caches as caches_module
from engine.games import manifest as manifest_module
from engine.games import registry
from engine.persistence import saves as saves_module
from engine.world import npc_sim as npc_sim_module

CLOCKWORK = "clockwork-dark"
GARDEN = "wicked-garden"


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def garden() -> Iterator[Any]:
    """
    Activate The Wicked Garden for one test, then put it back.

    The teardown is not optional. Activation mutates process-global config and
    a dozen module caches, so a leaked activation would fail whichever of the
    other tests happened to run next -- which is the exact failure mode this
    whole package exists to prevent.
    """
    manifest = registry.activate(GARDEN)
    try:
        yield manifest
    finally:
        registry.deactivate()


# ---------------------------------------------------------------------------
# 1. manifest parsing and the version gate
# ---------------------------------------------------------------------------


def test_engine_version_matches_the_save_envelope() -> None:
    """
    The gate and the save envelope must agree on what version this is.

    ``engine_requires`` is meaningless if the number it compares against is
    not the number written into every save. The string now has ONE home --
    ``engine.games.ENGINE_VERSION``, imported by the save module -- so this
    assertion proves the import stays in place rather than that two copies
    happen to match.
    """
    assert ENGINE_VERSION == saves_module.ENGINE_VERSION
    assert saves_module.ENGINE_VERSION is ENGINE_VERSION


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


def test_manifest_carries_unknown_keys_through_to_the_api(garden: Any) -> None:
    """
    A story may need vocabulary the engine has not learned.

    The Wicked Garden declares a top-level ``safety:`` block, which the
    manifest dataclass has no field for. The engine keeps its own ids; the
    block rides along in ``extras`` and is republished verbatim by
    ``to_dict()``, so a picker can show a content rating for free.

    The assertion is about PASSTHROUGH, so it deliberately does not pin the
    declared tier -- the rating is a content decision this test has no stake
    in. It checks the ceiling arrives, is a real tier name, and survives
    ``to_dict()`` byte-identical to what the manifest holds.
    """
    ceiling = garden.extras["safety"]["intensity"]["ceiling"]
    assert ceiling in ("suggestive", "explicit", "extreme")
    assert garden.to_dict()["safety"]["intensity"]["ceiling"] == ceiling
    assert garden.to_dict()["safety"]["fade"]["available"] is True


# ---------------------------------------------------------------------------
# 2. discovery and validation
# ---------------------------------------------------------------------------


def test_discover_finds_every_shipped_game() -> None:
    """
    A superset check, not an equality one: ``games/`` may also hold a local
    sandbox story that is not committed, and discovery finding one more than
    the repository ships is not a failure.
    """
    found = registry.discover()
    assert set(found) >= {CLOCKWORK, GARDEN}
    assert found[GARDEN].title == "The Wicked Garden"


def test_every_shipped_game_validates() -> None:
    for slug, manifest in registry.discover().items():
        assert registry.validate(manifest) == [], f"{slug} failed validation"


def test_no_story_declares_a_path_the_engine_never_reads() -> None:
    """
    A path key nothing reads is a path silently ignored.

    THIS TEST USED TO ASSERT SOMETHING ELSE. It compared the flagship's manifest
    against ``config/default.yaml``'s ``paths:`` block and demanded they agree --
    meaningful while those defaults named the flagship's own files, and a
    tautology the moment they were emptied. ``section("paths")`` now resolves an
    empty key through the running story's manifest, so the old comparison was
    the manifest against itself.

    What survives is the failure the original was written for, quoted from its
    own comment: "a silently unread path". The engine's vocabulary is the key
    set ``config/default.yaml`` declares; a key outside it is a line an author
    wrote that nothing will ever read.
    """
    vocabulary = set(config_module.get_config().section("paths"))
    assert vocabulary, "the config declares no path keys at all"

    for slug, manifest in registry.discover().items():
        unknown = set(manifest.paths) - vocabulary
        assert not unknown, (
            f"{slug} declares path keys the engine has never heard of: {sorted(unknown)}"
        )


def test_no_story_reads_another_storys_content() -> None:
    """
    The defect the whole seam exists for, asserted directly.

    Every content path a story declares must resolve inside its OWN tree, or
    into engine-owned space -- never into another ``games/<slug>/``.

    Before the engine's defaults were emptied this was false everywhere and
    invisible: The Wicked Garden was reading Edgewood's quests, prices and
    encounters, and the only way to find out was to notice a rumour about grain
    tallies in a fae court.
    """
    offenders: dict[str, list[str]] = {}
    for slug, manifest in registry.discover().items():
        mine = f"games/{slug}/"
        foreign = [
            f"{key}={value}"
            for key, value in manifest.paths.items()
            if str(value).replace("\\", "/").startswith("games/")
            and not str(value).replace("\\", "/").startswith(mine)
        ]
        if foreign:
            offenders[slug] = foreign
    assert offenders == {}, f"stories reading another story's content: {offenders}"

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

    The Garden's own manifest is used, with ``lore_db`` moved to an index
    nobody has built yet. The shipped index is a generated artefact --
    ``scripts/seed_lore.py`` writes it -- so a test asserting the real one is
    absent would read differently on a machine where the seeder has run, which
    is not an assertion at all.
    """
    shipped = registry.discover()[GARDEN]
    paths = dict(shipped.paths)
    paths["lore_db"] = "games/wicked-garden/data/lore/not-yet-seeded.db"
    manifest = manifest_module.from_dict(
        {
            "id": GARDEN,
            "title": shipped.title,
            "engine_requires": shipped.engine_requires,
            "paths": paths,
            "entry": dict(shipped.entry),
        },
        slug=GARDEN,
        root=shipped.root,
    )

    lore_db = manifest.resolve(manifest.paths["lore_db"])
    assert not lore_db.exists()
    assert lore_db.parent.is_dir(), "the parent IS checked, and must be here to check"
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

    monkeypatch.setenv(registry.GAME_ENV_VAR, GARDEN)
    assert registry.resolve_slug() == GARDEN

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


def test_scene_rules_engine_sees_the_new_map(garden: Any) -> None:
    """
    The stale re-export that would reject every legal move in a new game.

    ``engine/mcp/scene_rules_engine.py`` does ``from ... import LOCATION_IDS``
    at import time, and ``reload_locations`` REBINDS that frozenset rather
    than mutating it. Without the RE_EXPORTS pass, R001 would validate travel
    against Edgewood while the player stood in the Heart Grove.
    """
    from engine.mcp import scene_rules_engine

    assert "heart_grove" in scene_rules_engine.LOCATION_IDS
    assert "edgewood_square" not in scene_rules_engine.LOCATION_IDS


# ---------------------------------------------------------------------------
# 5. activation actually repoints every content system
# ---------------------------------------------------------------------------


def test_activation_repoints_every_content_system(garden: Any) -> None:
    """
    One assertion per loader that holds a cache. Each would pass on a stale
    cache if the previous game's content were still in it, which is why every
    one names something that exists in exactly one of the two games.

    Only the systems the Garden DECLARES are asserted here. An undeclared path
    does not resolve to nothing -- it resolves to whatever the config defaults
    to -- so demanding Garden content out of a loader the Garden never
    repointed would be asserting the engine invents it. What the Garden
    declares no path for (quests, encounters, recipes, economy) is checked the
    other way round below: it must not serve Edgewood's.
    """
    assert set(locations_module.LOCATIONS) == {
        "mortal_threshold",
        "gate_of_briars",
        "path_first_petals",
        "heart_grove",
        "guest_house",
        "feasting_glade",
        "mirror_pools",
        "aviary_unsent",
        "night_market",
        "thorn_labyrinth",
        "winter_spindle",
        "root_crypts",
        "briar_deep",
        "unknown",
    }
    assert set(reputation_module.load_factions()["factions"]) == {
        "rose_court",
        "winter_ash",
        "root_and_briar",
        "bloomkin",
        "night_market",
        "honeyed_dead",
        "border_watch",
    }
    assert set(npc_sim_module.load_npc_schedules()["npcs"]) == {
        "mother_briar",
        "ashen_vale",
        "lior",
        "thornwake",
        "elias",
        "mara_quill",
        "bloomkin_generic",
        "court_generic",
    }
    assert set(checks_module.load_archetypes()["archetypes"]) == {"human"}
    assert checks_module.load_archetypes()["default"] == "human"

    # The item registry, which is what every grant, gate and collection reads.
    items = inventory_module.load_items()
    assert "briar_key" in items
    assert "loaf" not in items, "the Garden is serving Edgewood's pantry"

    # Random tables are per-game too, as of the paths.tables fix. Before it,
    # engine/game/checks.py hardcoded data/tables/ and a second story drew
    # Edgewood's draws.
    collection_ids = {row["id"] for row in inventory_module.load_collections()}
    assert "sophias_gifts" in collection_ids
    assert "nine_pins" not in collection_ids

    from engine.world import schedules as schedules_module

    # The three world-event slots are the ENGINE's ids, so the Garden keeps
    # their names and fills them with its own content -- which makes the
    # location, not the key, the thing worth asserting.
    assert schedules_module.load_schedules()["caravan_arrival"]["location_id"] == "night_market"
    rumor_ids = {r["id"] for r in schedules_module.load_rumors()["rumors"]}
    assert "the_law_of_tens_is_not_a_metaphor" in rumor_ids
    assert "brass_lamb" not in rumor_ids

    # And the systems the Garden has no content for stay empty rather than
    # inheriting the flagship's. This is the half that used to fail silently:
    # a story with no quests would otherwise offer to apprentice at a bakery
    # four hundred miles and one world away.
    from engine.game import trade as trade_module
    from engine.skills.builtin import mechanics as mechanics_module

    assert "bakery_apprentice" not in quests_module.load_quests()
    assert "quiet_life" not in quests_module.load_arcs()
    assert "npc_maris" not in trade_module.load_economy()
    assert "bind_sympathy_charm" not in mechanics_module._load_recipes()


def test_deactivation_restores_the_flagship_content(garden: Any) -> None:
    assert "heart_grove" in locations_module.LOCATIONS
    registry.deactivate()
    assert "edgewood_square" in locations_module.LOCATIONS
    assert "heart_grove" not in locations_module.LOCATIONS
    assert "bakery_apprentice" in quests_module.load_quests()


def test_reset_config_does_not_drop_the_active_game(garden: Any) -> None:
    """
    Re-reading the YAML layers must not silently move the player's story.

    ``reset_config`` is called from a dozen places. If it cleared the overlay,
    any one of them would put a Wicked Garden session back onto Edgewood's
    content mid-turn.
    """
    config_module.reset_config()
    assert config_module.get_config().get("paths.locations").startswith("games/wicked-garden")
    assert "heart_grove" in locations_module.LOCATIONS


# ---------------------------------------------------------------------------
# 6. per-game save namespacing
# ---------------------------------------------------------------------------


def test_saves_are_namespaced_by_game(garden: Any) -> None:
    assert saves_module.saves_root().name == GARDEN
    assert saves_module.saves_root(CLOCKWORK).name == CLOCKWORK
    assert saves_module.saves_root(GARDEN) != saves_module.saves_root(CLOCKWORK)


def test_save_store_follows_the_active_game(garden: Any) -> None:
    """The cached store must be dropped on activation, or it keeps the old root."""
    assert saves_module.get_save_store().root.name == GARDEN
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


def test_a_run_saves_and_loads_inside_its_own_namespace(tmp_path: Path, garden: Any) -> None:
    store = saves_module.SaveStore(root=saves_module.saves_root().parent / GARDEN)
    store.root = tmp_path / GARDEN

    state = GameState()
    state.location_id = "heart_grove"
    state.player_name = "The guest who was not eaten"
    save_id = store.save(state)

    loaded, _memory = store.load(save_id)
    assert loaded.location_id == "heart_grove"
    assert (tmp_path / GARDEN / "index.json").is_file()


# ---------------------------------------------------------------------------
# 7. the HTTP payload behind the picker
# ---------------------------------------------------------------------------


def test_games_api_lists_every_shipped_game() -> None:
    from flask import Flask

    from engine.games.api import games_blueprint

    app = Flask(__name__)
    app.register_blueprint(games_blueprint())
    client = app.test_client()

    payload = client.get("/api/games").get_json()
    slugs = {row["slug"] for row in payload["games"]}
    assert {CLOCKWORK, GARDEN} <= slugs
    assert payload["default"] == CLOCKWORK

    garden_row = next(r for r in payload["games"] if r["slug"] == GARDEN)
    assert garden_row["playable"] is True
    assert garden_row["problems"] == []
    assert garden_row["entry_location"] == "mortal_threshold"
    assert garden_row["archetypes"] == ["human"]

    one = client.get(f"/api/games/{GARDEN}").get_json()
    assert one["title"] == "The Wicked Garden"
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
#
# This section used to be long. It drove The Drowned Carillon's own mechanics
# end to end -- encounter eligibility off an edge's danger_dc, an approach
# gated on an item id the flagship has never heard of, a sympathy check at the
# legendary band, a crit_success effect block, a quest predicate -- and that
# content went with the story. The Garden has no encounters, no danger legs and
# no quests to drive, so those cases have no equivalent here and are not
# reconstructed against content that does not exist.
#
# The claim itself survives, one file over: tests/test_wicked_garden_scenes.py
# drives the Garden's ten day-chapters through the real deck loader and
# resolves every value, item, location and flag they name.
#
# What stays here is the one retarget assertion that IS about the manifest
# seam rather than about a mechanic: which rules directory a check reads.
# ---------------------------------------------------------------------------


def test_archetype_bonuses_come_from_this_game_s_rules(garden: Any) -> None:
    """
    Same engine call, two answers, and the only difference is which story is
    active.

    The flagship's ``wayfarer`` carries a survival bonus declared in Edgewood's
    archetypes.yaml. The Garden declares exactly one archetype and gives it no
    bonuses at all -- it has no skills to be good at, and being mortal is the
    point rather than a build. So ``gather_modifiers`` must find the flagship's
    bonus under the flagship and find nothing under the Garden; finding the
    wayfarer's +2 here would mean checks are still reading Edgewood's file.
    """
    human = GameState()
    human.archetype = "human"
    garden_mods = dict(checks_module.gather_modifiers(human, "survival"))
    assert "wayfarer" not in garden_mods
    assert sum(garden_mods.values()) == 0

    registry.deactivate()
    wayfarer = GameState()
    wayfarer.archetype = "wayfarer"
    flagship_mods = dict(checks_module.gather_modifiers(wayfarer, "survival"))
    assert flagship_mods["wayfarer"] == 2
    assert sum(flagship_mods.values()) > sum(garden_mods.values())
