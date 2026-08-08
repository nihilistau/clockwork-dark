"""
The story state layer: schema, store, and the client projection.

This is the seam that lets a second story exist. Before it, `GameState` was one
story's answer welded into the engine -- a story with eight 0-100 meters and
four progress clocks had nowhere to put any of them, because `flags` is booleans
only, and simultaneously inherited a dozen fields it would never read.

Two properties matter most and both are asserted here:

  * `backing: field` DESCRIBES an existing attribute rather than moving it, so
    The Clockwork Dark keeps its typed `stats.hp` and the ten modules that read
    it keep working. This is the only reason the layer was safe to land.
  * A story that declares NOTHING keeps working. Absent is legal, everywhere.

Version: v0.1.0 [2026-08-08]
"""

from __future__ import annotations

import pytest

from engine.game.state import GameState
from engine.state.schema import (
    BACKING_BAG,
    BACKING_FIELD,
    VISIBILITY_HIDDEN,
    SchemaError,
    StateSchema,
    load_schema,
    parse_schema,
)
from engine.state.store import WRITER_ENGINE, StateStore

CLOCKWORK_SCHEMA = "games/clockwork-dark/state.yaml"


def _garden_like() -> StateSchema:
    """A story the engine has never heard of: everything in the bag."""
    return parse_schema(
        {
            "meters": {
                "favor": {"min": 0, "max": 100, "default": 15, "visibility": "veiled"},
                "autonomy": {"min": 0, "max": 100, "default": 70, "visibility": "veiled",
                             "owners": ["sophia"]},
                "time_debt": {"min": 0, "default": 0, "visibility": "public"},
            },
            "clocks": {
                "briar_hunger": {"min": 0, "max": 5, "default": 0, "visibility": "hidden"},
            },
        },
        slug="wicked-garden",
    )


# -- the flagship, described rather than moved --------------------------------


def test_clockwork_schema_is_entirely_field_backed():
    """
    The migration strategy, asserted.

    If any Clockwork value drifts to `bag` backing without its readers being
    moved too, the engine and the schema disagree about where the number lives
    and the story silently reads a default.
    """
    schema = load_schema(CLOCKWORK_SCHEMA, slug="clockwork-dark")

    assert schema.values, "the flagship declares no state"
    assert not schema.bag_backed, (
        f"bag-backed without moving their readers: "
        f"{[v.name for v in schema.bag_backed]}"
    )


def test_field_backed_reads_the_real_attribute():
    schema = load_schema(CLOCKWORK_SCHEMA, slug="clockwork-dark")
    state = GameState()
    state.stats.gold = 41

    assert StateStore(state, schema).get("gold") == 41


def test_field_backed_writes_through_and_keeps_the_attribute_type():
    """
    `hp` is an int and the rest of the engine formats and indexes it as one.

    A store that wrote floats back would turn "hp 18" into "hp 18.0" on the
    sheet and in every prompt, which is the kind of change that looks like a
    rendering bug three layers away.
    """
    schema = load_schema(CLOCKWORK_SCHEMA, slug="clockwork-dark")
    state = GameState()

    StateStore(state, schema).set("hp", 12, why="test")

    assert state.stats.hp == 12
    assert isinstance(state.stats.hp, int)


def test_hidden_values_never_reach_the_client():
    """
    DESIGN.md: the player meets awareness and the doom clock as fiction, never
    as a number. That used to be a hand-maintained allowlist a new field could
    be forgotten from; now it is a property of the declaration.
    """
    schema = load_schema(CLOCKWORK_SCHEMA, slug="clockwork-dark")
    payload = StateStore(GameState(), schema).to_client()

    for hidden in ("awareness", "evil_progress", "plot_involvement", "story_pressure"):
        assert hidden not in payload, f"{hidden} leaked to the browser"
    assert "hp" in payload


# -- a story with no typed fields at all --------------------------------------


def test_bag_backed_values_need_no_engine_field():
    state = GameState()
    store = StateStore(state, _garden_like())

    assert store.get("favor") == 15
    store.adjust("favor", 20, why="she was amused")

    assert store.get("favor") == 35
    assert state.meters["favor"] == 35


def test_clocks_and_meters_do_not_collide():
    """Separate containers, so a clock cannot shadow a meter of the same name."""
    state = GameState()
    store = StateStore(state, _garden_like())

    store.set("briar_hunger", 3, why="test")
    store.set("favor", 50, why="test")

    assert state.clocks["briar_hunger"] == 3
    assert state.meters["favor"] == 50


def test_bag_values_survive_a_save_round_trip():
    state = GameState()
    store = StateStore(state, _garden_like())
    store.set("favor", 62, why="test")
    store.set("briar_hunger", 4, why="test")

    loaded = GameState.from_dict(state.to_save_dict())
    reloaded = StateStore(loaded, _garden_like())

    assert reloaded.get("favor") == 62
    assert reloaded.get("briar_hunger") == 4


# -- bounds -------------------------------------------------------------------


def test_writes_clamp_rather_than_raise():
    """
    A model proposing 140 on a 0-100 scale means "as high as it goes", not
    "crash the turn". The overshoot is still recorded.
    """
    store = StateStore(GameState(), _garden_like())

    store.set("favor", 140, why="overshoot")

    assert store.get("favor") == 100
    assert store.journal[-1].clamped is True


def test_an_unbounded_meter_is_not_clamped():
    store = StateStore(GameState(), _garden_like())

    store.set("time_debt", 500, why="ten days a day")

    assert store.get("time_debt") == 500


# -- the write journal and the ACL --------------------------------------------


def test_the_engine_may_always_write():
    store = StateStore(GameState(), _garden_like())

    store.set("favor", 30, by=WRITER_ENGINE, why="toll")

    assert store.get("favor") == 30
    assert not store.refusals()


def test_an_agent_may_write_only_what_it_owns():
    store = StateStore(GameState(), _garden_like())

    store.set("autonomy", 40, by="sophia", why="she took something")

    assert store.get("autonomy") == 40


def test_a_write_by_a_non_owner_is_refused_and_recorded():
    """
    Recording the refusal matters more than the refusal.

    An agent repeatedly trying to move a value it does not own is a prompt
    defect, and it is completely invisible if the attempt is only ever dropped.
    """
    store = StateStore(GameState(), _garden_like())

    store.set("favor", 99, by="sophia", why="she would like to")

    assert store.get("favor") == 15, "a non-owner moved the value"
    refused = store.refusals()
    assert len(refused) == 1
    assert refused[0].name == "favor"
    assert refused[0].by == "sophia"


def test_values_are_engine_only_unless_a_story_says_otherwise():
    """A story must say a value is agent-writable, not forget to say it is not."""
    schema = _garden_like()

    assert schema.get("favor").owners == ()
    assert schema.get("autonomy").owners == ("sophia",)


def test_the_journal_records_why():
    store = StateStore(GameState(), _garden_like())
    store.adjust("favor", 5, by=WRITER_ENGINE, why="kept a promise", turn=7)

    record = store.journal[-1]
    assert record.why == "kept a promise"
    assert record.turn == 7
    assert (record.before, record.after) == (15, 20)


# -- veiled presentation ------------------------------------------------------


def test_a_veiled_meter_ships_a_band_and_never_its_number():
    """
    The Garden's rule: meters are read as a rose opening, not as 63/100.
    """
    store = StateStore(GameState(), _garden_like())
    store.set("favor", 63, why="test")

    row = store.to_client()["favor"]

    assert "value" not in row, "a veiled meter leaked its integer"
    assert row["band"] in {"none", "faint", "some", "strong", "utmost"}


def test_bands_move_with_the_value():
    store = StateStore(GameState(), _garden_like())

    store.set("favor", 0, why="t")
    low = store.to_client()["favor"]["band"]
    store.set("favor", 100, why="t")
    high = store.to_client()["favor"]["band"]

    assert low != high


# -- absent is legal ----------------------------------------------------------


def test_a_story_with_no_schema_file_gets_an_empty_schema(tmp_path):
    """
    A story that declares no state must keep running.

    Refusing to start over a missing optional file would turn an additive change
    into a breaking one for every existing game.

    Both shipped stories now ship a state.yaml, so the absent case is written
    against a path in a temp directory rather than against whichever story
    happens not to have declared one this week -- the property is about the
    LOADER, not about the current content of games/.
    """
    absent = tmp_path / "example-story" / "state.yaml"
    assert not absent.exists()

    schema = load_schema(absent, slug="example-story")

    assert schema.values == {}
    assert schema.slug == "example-story"


def test_an_empty_schema_projects_nothing_and_does_not_raise():
    store = StateStore(GameState(), StateSchema())

    assert store.to_client() == {}
    assert store.snapshot() == {}


# -- malformed declarations fail at load, not mid-turn ------------------------


def test_field_backing_without_a_path_is_rejected():
    """
    Without the address the store would fall through to the bag and the story
    would read zeros where it expected the engine's real value -- silently.
    """
    with pytest.raises(SchemaError, match="path"):
        parse_schema({"meters": {"hp": {"backing": BACKING_FIELD}}}, slug="broken")


def test_an_unknown_backing_is_rejected():
    with pytest.raises(SchemaError, match="backing"):
        parse_schema({"meters": {"x": {"backing": "elsewhere"}}}, slug="broken")


def test_an_unknown_visibility_is_rejected():
    with pytest.raises(SchemaError, match="visibility"):
        parse_schema({"meters": {"x": {"visibility": "sort of"}}}, slug="broken")


def test_inverted_bounds_are_rejected():
    with pytest.raises(SchemaError, match="min"):
        parse_schema({"meters": {"x": {"min": 10, "max": 2}}}, slug="broken")


def test_a_name_declared_twice_is_rejected():
    with pytest.raises(SchemaError, match="twice"):
        parse_schema(
            {"meters": {"x": {"max": 5}}, "clocks": {"x": {"max": 5}}}, slug="broken"
        )


def test_reading_an_undeclared_value_raises():
    """
    Zero is a legitimate value for almost every meter in the game, so a quiet
    zero for a name nobody declared would be indistinguishable from real state.
    """
    store = StateStore(GameState(), _garden_like())

    with pytest.raises(KeyError):
        store.get("hp")


def test_backing_constants_are_the_only_two():
    assert {BACKING_FIELD, BACKING_BAG} == {"field", "bag"}
    assert VISIBILITY_HIDDEN == "hidden"
