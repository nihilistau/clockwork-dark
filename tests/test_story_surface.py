"""
Story Plugin Surface Tests
==========================

Wave W1: what a story may declare beyond ``paths:``, and what it may not.

The bar every test here defends is the same one: **a story that declares none
of this must behave exactly as it did before the surface existed.** So most of
these come in pairs -- one proving a declaring story gets the new behaviour, one
proving The Clockwork Dark's bytes did not move.

Four seams:

    settings:       a bounded allowlist of engine settings. The interesting
                    tests are the refusals: paths.saves, lmstudio credentials
                    and stack commands must not be reachable from a manifest.
    entry:          entry.location_id was validated, published and consumed by
                    nothing -- procgen carried the flagship's answer as a Python
                    default, so every story started in Edgewood.
    migrations:     one global chain keyed by version meant a step written for
                    one story ran over every story's saves.
    save_summary:   SaveSummary had twelve required Clockwork-shaped fields, so
                    a story with no doom clock could not build a load-menu row.

Version: v0.1.0 [2026-08-08]
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from typing import Any, Iterator

import pytest
import yaml

from engine import config as config_module
from engine.game.state import GameState
from engine.games import manifest as manifest_module
from engine.games import registry
from engine.persistence import migrations as migrations_module
from engine.persistence import saves as saves_module

CLOCKWORK = "clockwork-dark"
GARDEN = "wicked-garden"
UI_SRC = Path(__file__).resolve().parents[1] / "ui" / "src"

#: The row The Clockwork Dark has always written into index.json. Any key added
#: or removed here is a change to a file players already have on disk.
CLOCKWORK_ROW_KEYS = {
    "save_id",
    "slot",
    "player_name",
    "archetype",
    "world_day",
    "world_hour",
    "location_id",
    "evil_phase",
    "turn_number",
    "updated_at",
    "save_version",
    "thumbnail",
    "created_at",
}


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def garden() -> Iterator[Any]:
    """Activate The Wicked Garden for one test, then put it back."""
    manifest = registry.activate(GARDEN)
    try:
        yield manifest
    finally:
        registry.deactivate()


@pytest.fixture
def clockwork_paths() -> dict[str, str]:
    """
    The flagship's declared paths, borrowed by every temp story below.

    A manifest is only activatable if every declared path exists, and inventing
    a whole content tree per test would prove nothing this file is about.
    """
    return dict(registry.discover()[CLOCKWORK].paths)


@pytest.fixture
def temp_story(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clockwork_paths: dict[str, str]
):
    """
    Build and activate a story on disk that this repo does not ship.

    Returns a factory taking the manifest body (and optionally a state.yaml
    body) and returning the slug. ``games_root`` is redirected at the temp
    directory, so discovery finds the temp story and nothing else -- which also
    means a leaked activation cannot reach the real games/.
    """
    root = tmp_path / "games"
    root.mkdir()
    monkeypatch.setattr(registry, "games_root", lambda: root)

    def build(
        body: dict[str, Any],
        *,
        slug: str = "temp-story",
        state: dict[str, Any] | None = None,
    ) -> str:
        directory = root / slug
        directory.mkdir(parents=True, exist_ok=True)
        merged: dict[str, Any] = {
            "id": slug,
            "title": "A Temporary Story",
            "paths": dict(clockwork_paths),
            "entry": {"location_id": "forest_clearing", "archetypes": ["wayfarer"]},
        }
        merged.update(body)
        (directory / "game.yaml").write_text(
            yaml.safe_dump(merged), encoding="utf-8"
        )
        if state is not None:
            (directory / "state.yaml").write_text(
                yaml.safe_dump(state), encoding="utf-8"
            )
        return slug

    try:
        yield build
    finally:
        registry.deactivate()


# ---------------------------------------------------------------------------
# 1. settings: the allowlist
# ---------------------------------------------------------------------------


def test_a_story_declaring_no_settings_installs_exactly_what_it_used_to() -> None:
    """
    The compatibility bar for the whole wave.

    ``config_overlay`` returned ``{"paths": ...}`` and nothing else. A story
    that declares no ``settings:`` must still produce precisely that, or every
    path in the engine is now being merged through an untested code path.

    Only the flagship is checked, because it is the only shipped story that
    declares nothing -- and it is the one whose bytes must not move. The Wicked
    Garden is the other side of the same seam and gets its own test below.
    """
    manifest = registry.discover()[CLOCKWORK]
    assert manifest.settings == {}
    assert manifest.config_overlay() == {"paths": dict(manifest.paths)}
    assert "settings" not in manifest.to_dict()


def test_the_garden_s_declared_settings_reach_the_overlay_and_the_api() -> None:
    """
    The other side: the one shipped story that DOES declare settings.

    Every key it names is on the allowlist, so all of them survive into the
    overlay and are republished over /api/games. A key silently dropped here
    would leave the Garden running the flagship's clock and the flagship's
    governance chain -- a doom ticker under a story with no doom, and a
    narrator instructed to write cosy frontier life at a fae threshold.
    """
    manifest = registry.discover()[GARDEN]
    assert manifest.settings, "the Garden declares settings; this test is about them"

    overlay = manifest.config_overlay()
    assert overlay["world"]["tick_hours"] == 0.0
    assert overlay["world"]["evil_base_rate_per_day"] == 0.0
    assert overlay["governance"]["directives"] == ["SafetyDirective", "StorytellerMind"]

    # Nothing was dropped on the way in: every declared key is an allowed one.
    assert set(manifest.allowed_settings()) == set(manifest.flat_settings())
    assert manifest.to_dict()["settings"] == manifest.allowed_settings()


def test_flatten_settings_dots_the_nesting_and_keeps_lists_whole() -> None:
    flat = manifest_module.flatten_settings(
        {
            "world": {"tick_hours": 1.0, "tick_max_hours": 3.0},
            "governance": {"directives": ["StorytellerMind"]},
            "empty": {},
        }
    )
    assert flat == {
        "world.tick_hours": 1.0,
        "world.tick_max_hours": 3.0,
        # A list is a leaf: the interceptor chains are ordered sequences, and
        # descending into one would produce keys like `governance.directives.0`.
        "governance.directives": ["StorytellerMind"],
        # An empty mapping contributes nothing, so `settings: {}` is legal.
    }


@pytest.mark.parametrize("key", sorted(manifest_module.SETTING_ALLOWLIST))
def test_every_allowlisted_key_carries_its_reason(key: str) -> None:
    """An allowlist entry without a stated reason is a key nobody vetted."""
    assert manifest_module.SETTING_ALLOWLIST[key].strip()


def test_allowlisted_settings_reach_the_running_config(temp_story: Any) -> None:
    slug = temp_story(
        {
            "settings": {
                "world": {"tick_hours": 1.25, "evil_base_rate_per_day": 0.0},
                "awareness": {"reveal_threshold": 5},
                "governance": {"directives": ["StorytellerMind"]},
            }
        }
    )
    registry.activate(slug)

    cfg = config_module.get_config()
    assert cfg.get("world.tick_hours") == 1.25
    assert cfg.get("world.evil_base_rate_per_day") == 0.0
    assert cfg.get("awareness.reveal_threshold") == 5
    assert cfg.get("governance.directives") == ["StorytellerMind"]

    # Deep-merged, not replaced: the sibling keys of an overridden section must
    # survive, or a story setting one world constant would delete the rest.
    assert cfg.get("world.tick_max_hours") == 6.0
    assert cfg.get("governance.post") == ["RulesGovernor"]


@pytest.mark.parametrize(
    "block, dotted",
    [
        ({"paths": {"saves": "somewhere/else"}}, "paths.saves"),
        ({"lmstudio": {"api_key": "stolen"}}, "lmstudio.api_key"),
        ({"lmstudio": {"base_url": "http://evil"}}, "lmstudio.base_url"),
        (
            {"stack": {"services": {"comfyui": {"command": "calc.exe"}}}},
            "stack.services.comfyui.command",
        ),
        ({"scene": {"clockwork": {"port": 1}}}, "scene.clockwork.port"),
        ({"game": {"default": "temp-story"}}, "game.default"),
        ({"media": {"live_generation": True}}, "media.live_generation"),
        ({"world": {"tick_hourz": 1.0}}, "world.tick_hourz"),
    ],
)
def test_a_setting_outside_the_allowlist_refuses_the_launch(
    temp_story: Any, block: dict[str, Any], dotted: str
) -> None:
    """
    Refused loudly, not dropped.

    A story author who believes they moved the save directory and did not would
    debug the save directory. Failing at activation points at the manifest line.
    """
    slug = temp_story({"settings": block})
    with pytest.raises(registry.ActivationError) as excinfo:
        registry.activate(slug)
    assert f"settings.{dotted}" in str(excinfo.value)


def test_a_refused_setting_never_reaches_the_config_even_unvalidated(
    clockwork_paths: dict[str, str],
) -> None:
    """
    The filter lives in ``config_overlay``, not only in ``validate``.

    Validation is the gate, but a caller that builds an overlay directly (a
    test, a script, a future loader) must not be able to route around it.
    """
    manifest = manifest_module.from_dict(
        {
            "title": "Hostile",
            "paths": dict(clockwork_paths),
            "settings": {
                "paths": {"saves": "somewhere/else"},
                "lmstudio": {"api_key": "stolen"},
                "world": {"tick_hours": 1.0},
            },
        },
        slug="hostile",
    )
    overlay = manifest.config_overlay()
    assert overlay["paths"] == dict(clockwork_paths)
    assert "lmstudio" not in overlay
    assert overlay["world"] == {"tick_hours": 1.0}


def test_refusal_reasons_name_the_danger() -> None:
    assert "machine" in manifest_module.refusal_reason("lmstudio.api_key")
    assert "code" in manifest_module.refusal_reason("stack.services.x.command")
    assert "paths:" in manifest_module.refusal_reason("paths.saves")


def test_allowed_settings_are_published_over_the_games_api(temp_story: Any) -> None:
    slug = temp_story({"settings": {"world": {"tick_hours": 1.25}}})
    row = registry.get(slug).to_dict()
    assert row["settings"] == {"world.tick_hours": 1.25}


# ---------------------------------------------------------------------------
# 1b. ui.plugin -- a story declares which client plugin draws it
#
# It used to be inferred: the client matched the server's slug against a
# directory name under ui/src/stories/. That made two stories unable to share a
# look, and a plugin directory is not free -- Vite turns each into its own chunk
# in the COMMITTED dist/ tree, so a scratch story wanting an existing skin had
# to leave build artefacts in the repository to get it.
# ---------------------------------------------------------------------------


def test_every_shipped_story_still_resolves_to_its_own_plugin() -> None:
    """
    The compatibility bar. Not run under `temp_story`, which redirects
    `games_root` at a temp directory and would put the real games out of reach.

    Both shipped stories DECLARE their `ui:` block now, and each declares the
    plugin the slug fallback would have picked -- so the client resolves
    exactly as it did when the block was omitted, but by declaration rather
    than by coincidence of directory naming. The slug fallback itself is still
    real and still held, by the malformed-block test below.
    """
    for shipped in (CLOCKWORK, GARDEN):
        manifest = registry.get(shipped)
        assert manifest.ui_plugin == shipped
        assert manifest.to_dict()["ui_plugin"] == shipped


def test_a_story_may_borrow_another_storys_plugin(temp_story: Any) -> None:
    """`ui: {plugin: wicked-garden}` -- draw me like that one."""
    slug = temp_story({"ui": {"plugin": "wicked-garden"}})
    manifest = registry.get(slug)
    assert manifest.ui_plugin == "wicked-garden"
    assert manifest.to_dict()["ui_plugin"] == "wicked-garden"
    # And the story is still itself: the plugin is a skin, not an identity.
    assert manifest.slug == slug


@pytest.mark.parametrize(
    "bad", ["wicked-garden", ["wicked-garden"], {"plugin": ""}, {}, None]
)
def test_a_malformed_ui_block_falls_back_rather_than_raising(
    temp_story: Any, bad: Any
) -> None:
    """
    A typo costs the story its skin, never its boot.

    Same argument the client makes for a plugin that throws: core alone is a
    playable client, and a manifest is content.
    """
    slug = temp_story({"ui": bad}, slug="ui-fallback")
    assert registry.get(slug).to_dict()["ui_plugin"] == slug


def test_the_client_follows_the_declaration_not_the_directory() -> None:
    """
    The JS half of the seam, read from source.

    `resolveStory` must take `ui_plugin` off the catalogue row and pass it to
    `loadStory`, keeping the running slug separate -- two stories sharing one
    plugin means "which plugin" and "which story" are no longer the same
    question, and anything that conflates them silently mislabels a run.
    """
    text = (UI_SRC / "core" / "story.js").read_text(encoding="utf-8")
    assert "ui_plugin" in text, "the client never reads the declaration"
    assert "BY_SLUG" not in text, "still keyed off the slug"
    assert re.search(r"loadStory\(\s*plugin\s*\|\|\s*slug\s*,\s*slug\s*,\s*title\s*\)", text)


def test_a_borrowed_plugin_lends_its_look_and_not_its_voice() -> None:
    """
    Every naming slot is dropped when a plugin is borrowed.

    Observed before this: a scratch story borrowing the Garden's plugin titled
    its browser tab "The Wicked Garden", drew the Garden's wordmark, and put
    "Step through the hedge" on the Begin button of a story whose whole world is
    one bedroom. That is the same plugin-versus-story conflation the seam
    exists to separate, resurfacing one layer up as copy.

    Listed explicitly rather than inferred: a slot added later is VISUAL by
    default, and a naming slot that is forgotten here leaks a story's fiction
    into another story's screen -- which is exactly the failure this is for.
    """
    text = (UI_SRC / "core" / "story.js").read_text(encoding="utf-8")
    # A borrow is still "the plugin is not this story's own"...
    assert re.search(r"const\s+borrowed\s*=.*plugin\s*!==\s*slug", text)
    # ...with ONE exemption, and it has to be the engine's own plugin. That one
    # has no world to lend and no voice to strip -- no title, no beginLabel,
    # and a Wordmark that renders whatever name it is handed -- so stripping it
    # would blank the only naming it has and leave the story worse dressed than
    # bare core, which is the thing it exists to fix.
    assert re.search(r"const\s+engine\s*=\s*found\.slug\s*===\s*ENGINE_PLUGIN", text)
    assert re.search(r"const\s+borrowed\s*=\s*!engine\s*&&", text)
    block = text.split("const naming")[1].split("return {")[0]
    for slot in ("title", "documentTitle", "Wordmark", "StartIntro", "beginLabel", "onboarding"):
        assert slot in block, f"{slot} survives a borrowed plugin"
    # The story's own plugin is untouched: the whole override is gated on it.
    assert "borrowed" in text.split("const naming")[1].split("\n")[0]


# ---------------------------------------------------------------------------
# 2. entry.location_id is finally consumed
# ---------------------------------------------------------------------------


def test_entry_location_answers_without_activating_anything() -> None:
    registry.deactivate()
    assert registry.peek() is None
    assert registry.entry_location() == "forest_clearing"
    # Still nothing activated: asking where a run starts must not repoint config
    # and clear a dozen caches as a side effect.
    assert registry.peek() is None


def test_entry_location_follows_the_active_story(garden: Any) -> None:
    assert registry.entry_location() == "mortal_threshold"
    assert registry.entry_archetypes() == ["human"]


def test_a_new_run_starts_where_the_manifest_says(garden: Any) -> None:
    """
    The bug: ``new_game_state`` carried ``location_id="forest_clearing"``.

    So ``entry.location_id`` was validated, published over /api/games, and read
    by nothing -- a run of the second story began on an id its map does not
    contain.
    """
    from engine.game.procgen import new_game_state

    state = new_game_state(player_name="Nel", seed=7)
    assert state.location_id == "mortal_threshold"


def test_the_flagship_still_starts_in_the_forest_clearing() -> None:
    from engine.game.procgen import new_game_state

    registry.deactivate()
    assert new_game_state(player_name="Alden", seed=7).location_id == "forest_clearing"


def test_an_explicit_location_still_wins(garden: Any) -> None:
    from engine.game.procgen import new_game_state

    state = new_game_state(player_name="Nel", seed=7, location_id="heart_grove")
    assert state.location_id == "heart_grove"


# ---------------------------------------------------------------------------
# 3. migrations are namespaced per story
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_story_migrations() -> Iterator[None]:
    """Registration is process-global; a leaked step would migrate real saves."""
    yield
    migrations_module.clear_story_migrations()


def _v1_doc() -> dict[str, Any]:
    return {"save_version": 1, "world_day": 3, "world_hour": 9, "procgen": {"seed": 5}}


def test_the_engine_chain_still_runs_for_every_story() -> None:
    """v1 -> v2 touches the SPINE, so it is not namespaced and must not be."""
    for slug in (None, CLOCKWORK, GARDEN, "a-story-nobody-wrote"):
        out = migrations_module.migrate(_v1_doc(), slug=slug)
        assert out["world_clock_hours"] == 2 * 24 + 9
        assert out["rng_seed"] == 5


def test_a_story_step_runs_only_over_that_story_s_saves() -> None:
    def stamp(data: dict[str, Any]) -> dict[str, Any]:
        data["tide"] = 4
        return data

    migrations_module.register_story_migration(GARDEN, 1, stamp)

    assert migrations_module.migrate(_v1_doc(), slug=GARDEN)["tide"] == 4
    # The whole point: a step written for one story must not reach another's.
    assert "tide" not in migrations_module.migrate(_v1_doc(), slug=CLOCKWORK)
    assert "tide" not in migrations_module.migrate(_v1_doc())


def test_the_spine_runs_before_the_story_step() -> None:
    """A story step is entitled to assume the engine's fields are already v+1."""
    seen: dict[str, Any] = {}

    def observe(data: dict[str, Any]) -> dict[str, Any]:
        seen.update(data)
        return data

    migrations_module.register_story_migration(GARDEN, 1, observe)
    migrations_module.migrate(_v1_doc(), slug=GARDEN)
    assert "world_clock_hours" in seen
    assert "world_day" not in seen


def test_registering_two_steps_for_one_version_is_refused() -> None:
    migrations_module.register_story_migration(GARDEN, 1, lambda d: d)
    with pytest.raises(migrations_module.MigrationError):
        migrations_module.register_story_migration(GARDEN, 1, lambda d: d)


def test_a_save_carries_the_story_that_wrote_it(tmp_path: Path) -> None:
    from engine.persistence.atomic import read_json

    store = saves_module.SaveStore(root=tmp_path / "saves", slug=GARDEN)
    save_id = store.save(GameState(player_name="Nel"))
    envelope = read_json(tmp_path / "saves" / save_id / "save.json")
    assert envelope["game"] == GARDEN


def test_the_load_path_selects_the_chain_from_the_save(tmp_path: Path) -> None:
    """
    A directory can be moved, copied or restored from a backup.

    So the chain that runs over a document is chosen by what the document says
    it is, not by where it was found.
    """
    seen: list[str] = []

    def stamp(data: dict[str, Any]) -> dict[str, Any]:
        seen.append("ran")
        return data

    migrations_module.register_story_migration(GARDEN, 1, stamp)

    store = saves_module.SaveStore(root=tmp_path / "saves", slug=GARDEN)
    save_id = store.save(GameState(player_name="Nel"))

    # Rewrite the envelope back to v1 so the chain has something to do.
    from engine.persistence.atomic import read_json, write_json_atomic

    path = tmp_path / "saves" / save_id / "save.json"
    envelope = read_json(path)
    envelope["save_version"] = 1
    envelope["state"]["save_version"] = 1
    write_json_atomic(path, envelope)

    # A store built on a DIFFERENT slug still runs the Garden chain, because
    # the envelope says the save is a Garden save.
    other = saves_module.SaveStore(root=tmp_path / "saves", slug=CLOCKWORK)
    other.load(save_id)
    assert seen == ["ran"]


# ---------------------------------------------------------------------------
# 4. the load-menu row is story-declared
# ---------------------------------------------------------------------------


def test_a_summary_builds_with_no_arguments_at_all() -> None:
    """
    The story with no doom clock and no archetype.

    Twelve required fields including ``evil_phase`` meant such a story could not
    construct a row; every field is defaulted now.
    """
    row = saves_module.SaveSummary().to_dict()
    assert row["evil_phase"] == ""
    assert row["archetype"] == ""
    assert "values" not in row


def test_the_flagship_row_is_byte_identical(tmp_path: Path) -> None:
    registry.deactivate()
    store = saves_module.SaveStore(root=tmp_path / "saves")
    state = GameState(player_name="Alden", location_id="edgewood_square")
    save_id = store.save(state)

    from engine.persistence.atomic import read_json

    (row,) = read_json(tmp_path / "saves" / "index.json")["saves"]
    assert set(row) == CLOCKWORK_ROW_KEYS
    assert row["save_id"] == save_id
    assert row["evil_phase"] == "dormant"


def test_a_story_declares_the_columns_its_load_menu_shows(
    temp_story: Any, tmp_path: Path
) -> None:
    slug = temp_story(
        {"save_summary": ["hp", "tide"]},
        state={
            "version": 1,
            "meters": {
                # One field-backed (describes an attribute the spine already
                # has) and one bag-backed (a value this story invented), to
                # prove the row does not care which is which.
                "hp": {"backing": "field", "path": "stats.hp", "min": 0, "max": 20},
                "tide": {"min": 0, "max": 8, "label": "The tide"},
            },
        },
    )
    registry.activate(slug)

    store = saves_module.SaveStore(root=tmp_path / "saves", slug=slug)
    state = GameState(player_name="Nel")
    state.meters["tide"] = 6.0
    store.save(state)

    (summary,) = store.list_saves()
    assert summary.values["hp"]["value"] == float(state.stats.hp)
    assert summary.values["tide"] == {"label": "The tide", "kind": "meter", "value": 6.0}


def test_a_veiled_column_shows_a_band_and_never_the_number(
    temp_story: Any, tmp_path: Path
) -> None:
    slug = temp_story(
        {"save_summary": ["dread"]},
        state={
            "version": 1,
            "meters": {
                "dread": {"min": 0, "max": 100, "visibility": "veiled"},
            },
        },
    )
    registry.activate(slug)

    store = saves_module.SaveStore(root=tmp_path / "saves", slug=slug)
    state = GameState()
    state.meters["dread"] = 91.0
    store.save(state)

    (summary,) = store.list_saves()
    assert "value" not in summary.values["dread"]
    assert summary.values["dread"]["band"] == "utmost"


def test_a_hidden_value_is_refused_on_the_load_menu(
    temp_story: Any, tmp_path: Path
) -> None:
    """The load menu is a screen the player reads. Hidden means hidden."""
    slug = temp_story(
        {"save_summary": ["hp", "secret"]},
        state={
            "version": 1,
            "meters": {
                "hp": {"backing": "field", "path": "stats.hp", "min": 0, "max": 20},
                "secret": {"min": 0, "max": 1, "visibility": "hidden"},
            },
        },
    )
    registry.activate(slug)

    store = saves_module.SaveStore(root=tmp_path / "saves", slug=slug)
    store.save(GameState())

    (summary,) = store.list_saves()
    assert "secret" not in summary.values
    assert "hp" in summary.values


def test_a_save_summary_that_is_not_a_list_fails_validation(temp_story: Any) -> None:
    slug = temp_story({"save_summary": {"hp": True}})
    with pytest.raises(registry.ActivationError) as excinfo:
        registry.activate(slug)
    assert "save_summary" in str(excinfo.value)


# ---------------------------------------------------------------------------
# 5. the doctor learns state schemas
# ---------------------------------------------------------------------------


def _doctor():
    """Load scripts/doctor.py as a module; scripts/ is not a package."""
    path = Path(__file__).resolve().parents[1] / "scripts" / "doctor.py"
    spec = importlib.util.spec_from_file_location("_doctor_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_doctor_reports_every_shipped_story_s_state() -> None:
    """
    The two shipped stories describe their state in opposite ways, and the
    doctor's whole job here is that the difference is visible at a glance.

    The flagship's fifteen values are every one FIELD-backed: the schema
    describes attributes `GameState` already had, which is the only reason the
    layer was safe to land over a game people were mid-run on. The Garden's
    thirteen are every one BAG-backed and mostly veiled or hidden, because none
    of them existed before it declared them.

    Fifteen, not the original fourteen: `doom_resistance` joined when the
    flagship shipped endings, because its gate table reads earned reprieve
    through the `value` predicate and an undeclared name is False, never True
    -- an ending scored on a value nobody declared would have foreshadowed
    nothing, silently. It is FIELD-backed like its siblings (the attribute has
    existed on `GameState` since R-06) and hidden like awareness, which is why
    the hidden count moves with it.
    """
    doctor = _doctor()
    report = doctor.Report()
    doctor.check_state_schemas(report)

    rows = {name: (status, detail) for section, name, status, detail in report.rows}
    flagship = next(v for k, v in rows.items() if k.startswith(CLOCKWORK))
    assert flagship[0] == doctor.OK
    assert "15 values" in flagship[1]
    assert "15 field, 0 bag" in flagship[1]
    assert "5 hidden" in flagship[1]

    garden_row = next(v for k, v in rows.items() if k.startswith(GARDEN))
    assert garden_row[0] == doctor.OK
    assert "13 values" in garden_row[1]
    assert "0 field, 13 bag" in garden_row[1]
    assert "6 veiled" in garden_row[1]


def test_the_doctor_passes_a_story_that_declares_no_state(temp_story: Any) -> None:
    """
    Absent is legal everywhere, and the doctor must say so rather than warn.

    Both shipped stories now ship a state.yaml, so the absent case is built
    here instead of borrowed from one of them -- `temp_story` writes a manifest
    and no state.yaml, and redirects `games_root` at it, so this is the only
    story the doctor can see.
    """
    doctor = _doctor()
    slug = temp_story({})

    report = doctor.Report()
    doctor.check_state_schemas(report)

    rows = {name: (status, detail) for section, name, status, detail in report.rows}
    row = next(v for k, v in rows.items() if k.startswith(slug))
    assert not report.failed
    assert row[0] == doctor.OK
    assert "spine" in row[1]


def test_the_doctor_fails_loudly_on_a_malformed_schema(temp_story: Any) -> None:
    doctor = _doctor()
    temp_story(
        {},
        state={
            "version": 1,
            # backing: field with no path. The store would silently fall through
            # to the bag and the story would read zeros forever.
            "meters": {"broken": {"backing": "field"}},
        },
    )
    report = doctor.Report()
    doctor.check_state_schemas(report)
    assert report.failed
    assert any("broken" in detail for _, _, _, detail in report.rows)


def test_the_doctor_catches_a_summary_column_that_does_not_exist(
    temp_story: Any,
) -> None:
    """
    At save time an unresolvable column is a logged warning nobody reads.

    Here it is a FAIL, which is the whole reason the doctor learned schemas.
    """
    doctor = _doctor()
    temp_story(
        {"save_summary": ["nope"]},
        state={"version": 1, "meters": {"tide": {"min": 0, "max": 8}}},
    )
    report = doctor.Report()
    doctor.check_state_schemas(report)
    assert report.failed
    assert any("nope" in detail for _, _, _, detail in report.rows)
