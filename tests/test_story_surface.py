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
CARILLON = "drowned-carillon"

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
def carillon() -> Iterator[Any]:
    """Activate The Drowned Carillon for one test, then put it back."""
    manifest = registry.activate(CARILLON)
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

    ``config_overlay`` returned ``{"paths": ...}`` and nothing else. Both
    shipped stories must still produce precisely that, or every path in the
    engine is now being merged through an untested code path.
    """
    for slug in (CLOCKWORK, CARILLON):
        manifest = registry.discover()[slug]
        assert manifest.settings == {}
        assert manifest.config_overlay() == {"paths": dict(manifest.paths)}
        assert "settings" not in manifest.to_dict()


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
# 2. entry.location_id is finally consumed
# ---------------------------------------------------------------------------


def test_entry_location_answers_without_activating_anything() -> None:
    registry.deactivate()
    assert registry.peek() is None
    assert registry.entry_location() == "forest_clearing"
    # Still nothing activated: asking where a run starts must not repoint config
    # and clear a dozen caches as a side effect.
    assert registry.peek() is None


def test_entry_location_follows_the_active_story(carillon: Any) -> None:
    assert registry.entry_location() == "bellfounders_quay"
    assert registry.entry_archetypes() == ["net_mender", "lamp_keeper", "bell_founder"]


def test_a_new_run_starts_where_the_manifest_says(carillon: Any) -> None:
    """
    The bug: ``new_game_state`` carried ``location_id="forest_clearing"``.

    So ``entry.location_id`` was validated, published over /api/games, and read
    by nothing -- a run of the second story began on an id its map does not
    contain.
    """
    from engine.game.procgen import new_game_state

    state = new_game_state(player_name="Nel", seed=7)
    assert state.location_id == "bellfounders_quay"


def test_the_flagship_still_starts_in_the_forest_clearing() -> None:
    from engine.game.procgen import new_game_state

    registry.deactivate()
    assert new_game_state(player_name="Alden", seed=7).location_id == "forest_clearing"


def test_an_explicit_location_still_wins(carillon: Any) -> None:
    from engine.game.procgen import new_game_state

    state = new_game_state(player_name="Nel", seed=7, location_id="wet_steps")
    assert state.location_id == "wet_steps"


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
    for slug in (None, CLOCKWORK, CARILLON, "a-story-nobody-wrote"):
        out = migrations_module.migrate(_v1_doc(), slug=slug)
        assert out["world_clock_hours"] == 2 * 24 + 9
        assert out["rng_seed"] == 5


def test_a_story_step_runs_only_over_that_story_s_saves() -> None:
    def stamp(data: dict[str, Any]) -> dict[str, Any]:
        data["tide"] = 4
        return data

    migrations_module.register_story_migration(CARILLON, 1, stamp)

    assert migrations_module.migrate(_v1_doc(), slug=CARILLON)["tide"] == 4
    # The whole point: a step written for one story must not reach another's.
    assert "tide" not in migrations_module.migrate(_v1_doc(), slug=CLOCKWORK)
    assert "tide" not in migrations_module.migrate(_v1_doc())


def test_the_spine_runs_before_the_story_step() -> None:
    """A story step is entitled to assume the engine's fields are already v+1."""
    seen: dict[str, Any] = {}

    def observe(data: dict[str, Any]) -> dict[str, Any]:
        seen.update(data)
        return data

    migrations_module.register_story_migration(CARILLON, 1, observe)
    migrations_module.migrate(_v1_doc(), slug=CARILLON)
    assert "world_clock_hours" in seen
    assert "world_day" not in seen


def test_registering_two_steps_for_one_version_is_refused() -> None:
    migrations_module.register_story_migration(CARILLON, 1, lambda d: d)
    with pytest.raises(migrations_module.MigrationError):
        migrations_module.register_story_migration(CARILLON, 1, lambda d: d)


def test_a_save_carries_the_story_that_wrote_it(tmp_path: Path) -> None:
    from engine.persistence.atomic import read_json

    store = saves_module.SaveStore(root=tmp_path / "saves", slug=CARILLON)
    save_id = store.save(GameState(player_name="Nel"))
    envelope = read_json(tmp_path / "saves" / save_id / "save.json")
    assert envelope["game"] == CARILLON


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

    migrations_module.register_story_migration(CARILLON, 1, stamp)

    store = saves_module.SaveStore(root=tmp_path / "saves", slug=CARILLON)
    save_id = store.save(GameState(player_name="Nel"))

    # Rewrite the envelope back to v1 so the chain has something to do.
    from engine.persistence.atomic import read_json, write_json_atomic

    path = tmp_path / "saves" / save_id / "save.json"
    envelope = read_json(path)
    envelope["save_version"] = 1
    envelope["state"]["save_version"] = 1
    write_json_atomic(path, envelope)

    # A store built on a DIFFERENT slug still runs the Carillon chain, because
    # the envelope says the save is a Carillon save.
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


def test_the_doctor_reports_both_shipped_stories_state() -> None:
    doctor = _doctor()
    report = doctor.Report()
    doctor.check_state_schemas(report)

    rows = {name: (status, detail) for section, name, status, detail in report.rows}
    flagship = next(v for k, v in rows.items() if k.startswith(CLOCKWORK))
    assert flagship[0] == doctor.OK
    assert "14 values" in flagship[1]
    assert "14 field, 0 bag" in flagship[1]
    assert "4 hidden" in flagship[1]

    # A story with no state.yaml runs on the spine. Absent is legal everywhere.
    coast = next(v for k, v in rows.items() if k.startswith(CARILLON))
    assert coast[0] == doctor.OK
    assert "spine" in coast[1]


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
