"""Places (v0.23.0 spec §8.1, §10.5): the flat, the minutes edge, the cast's homes, the venues."""

from __future__ import annotations

import pytest

from tests.social_fixtures import matched, receipts_active, receipts_state  # noqa: F401


def test_a_minutes_edge_defaults_hours_to_zero_and_charges_minutes(receipts_state) -> None:
    from engine.game.engine import GameEngine
    from engine.game.locations import get_edge

    assert get_edge("apt_hall", "apt_kitchen")["hours"] == 0
    assert receipts_state.location_id == "apt_lounge"
    engine = GameEngine(receipts_state)
    before = receipts_state.world_clock_hours
    assert engine.move_to("apt_hall").success
    result = engine.move_to("apt_kitchen")
    assert result.success and result.hours == 0 and result.minutes == 1
    assert receipts_state.world_clock_hours == pytest.approx(before + 2 / 60)
    assert result.to_dict()["minutes"] == 1


def test_a_minutes_edge_outside_range_is_a_load_error() -> None:
    from engine.game import locations

    # `_clean_edge(src, dst, raw, known_ids)` takes FOUR arguments (locations.py; pre-flight F20).
    with pytest.raises(ValueError, match="outside 0-59"):
        locations._clean_edge("a", "b", {"minutes": 60}, {"a", "b"})
    with pytest.raises(ValueError, match="both 0"):
        locations._clean_edge("a", "b", {"minutes": 0}, {"a", "b"})
    with pytest.raises(ValueError, match="whole number"):
        locations._clean_edge("a", "b", {"minutes": "soon"}, {"a", "b"})


def test_a_malformed_minutes_edge_is_dropped_by_the_loader_and_logged(tmp_path, caplog) -> None:
    from engine.game import locations

    path = tmp_path / "locations.yaml"
    path.write_text(
        "version: 1\nrings: {0: x}\nlocations:\n"
        "  a: {name: A, ring: 0, evil_multiplier: 0.1, summary: s, tags: [], connections: {b: {minutes: 60}}}\n"
        "  b: {name: B, ring: 0, evil_multiplier: 0.1, summary: s, tags: [], connections: {a: {minutes: 5}}}\n",
        encoding="utf-8")
    with caplog.at_level("ERROR"):
        graph = locations.load_locations(path)
    # the loader mirrors b>a back, so a>b exists, but only as that mirror and never as the 60-minute row
    mirrored = graph["a"]["connections"]["b"]
    assert mirrored.get("mirrored") and mirrored["minutes"] == 5 and mirrored["hours"] == 0   # never a free move
    assert graph["b"]["connections"]["a"]["minutes"] == 5
    assert "outside 0-59" in caplog.text


def test_the_travel_label_reads_minutes(receipts_state) -> None:
    from engine.game.intents import legal_intents

    travel = next(v for v in legal_intents(receipts_state) if v.action == "travel")
    assert dict(travel.options)["apt_dining"] == "Dining room, 1 min"


def test_a_phone_story_move_is_inert(receipts_state) -> None:
    """§8.1 (I3), seam pin 7: 50 room moves change awareness, plot pressure and encounters not at all.
    Every move is asserted to SUCCEED and the clock to advance exactly 50 minutes, so a refused move
    can never make the test vacuous."""
    from engine.game.engine import GameEngine

    engine = GameEngine(receipts_state)
    # Plot pressure is a pure function of involvement and patience, first written by a move (a fresh
    # state holds 0.0, never computed): one move settles it, then 50 more must leave it where it is.
    assert engine.move_to("apt_dining").success
    awareness, pressure = receipts_state.awareness, receipts_state.story_pressure
    before = receipts_state.world_clock_hours
    for i in range(50):
        assert engine.move_to("apt_lounge" if i % 2 == 0 else "apt_dining").success, i
    assert receipts_state.world_clock_hours == pytest.approx(before + 50 / 60)
    assert receipts_state.awareness == awareness and receipts_state.story_pressure == pressure
    assert not receipts_state.encounter


def test_from_dict_keeps_a_location_as_saved(receipts_active) -> None:
    """The v0.22 `home` alias is retired (v0.23.0 T20): the migration maps it at load
    (tests/test_social_migrate.py::test_v022_home_maps_to_apt_lounge), `from_dict` renames nothing."""
    from engine.game.state import GameState
    from engine.social import places

    assert not hasattr(places, "LOCATION_ALIASES")
    assert GameState.from_dict({"location_id": "apt_kitchen", "social": {}}).location_id == "apt_kitchen"


def test_every_venue_is_a_location_with_travel_minutes(receipts_active) -> None:
    from engine.game.locations import LOCATIONS
    from engine.social import places

    assert len(places.venue_ids()) == 15
    for vid in places.venue_ids():
        assert vid in LOCATIONS and places.travel_minutes(vid) > 0
    for hid in places.home_ids():
        assert hid in LOCATIONS and places.travel_minutes(hid) > 0 and places.is_home(hid)


def test_the_graph_has_28_locations_and_the_flat_is_seven(receipts_active) -> None:
    from engine.game.locations import LOCATIONS
    from engine.social import places

    assert len(LOCATIONS) == 28
    flat = [lid for lid in LOCATIONS if places.is_flat(lid)]
    assert sorted(flat) == sorted(["apt_bedroom", "apt_lounge", "apt_kitchen", "apt_dining", "apt_hall",
                                   "bldg_lift", "bldg_reception"])
    assert places.is_outside_flat("merrow_street") and not places.is_outside_flat("apt_hall")
    assert places.label("apt_dining") == "Dining room"


def test_every_room_reaches_the_street_by_one_minute_edges(receipts_active) -> None:
    from engine.game.locations import get_edge, neighbours

    seen, frontier = {"apt_lounge"}, ["apt_lounge"]
    while frontier:
        here = frontier.pop()
        for there in neighbours(here):
            assert get_edge(here, there)["minutes"] == 1
            if there not in seen:
                seen.add(there)
                frontier.append(there)
    assert seen == {"apt_bedroom", "apt_lounge", "apt_kitchen", "apt_dining", "apt_hall", "bldg_lift",
                    "bldg_reception", "merrow_street"}


def test_a_person_has_one_stable_home(receipts_state, matched) -> None:
    from engine.social import attrs, places

    pid = matched("matchstick").split(":")[1]
    first = places.home_of(receipts_state, pid)
    assert first in places.home_ids() and places.home_label(receipts_state, pid)
    assert places.home_of(receipts_state, pid) == first == attrs.of(receipts_state, pid)["home"]


def test_the_home_weights_pick_the_neighbourhood_row_then_the_young_row(receipts_active) -> None:
    from types import SimpleNamespace

    from engine.social import places

    assert set(places._weights(SimpleNamespace(neighbourhood="westcliff", age=22))) == \
        {"home_westcliff_house", "home_harbour_studio"}
    assert set(places._weights(SimpleNamespace(neighbourhood="old_town", age=22))) == \
        {"home_terrace_share", "home_harbour_studio", "home_quays_loft"}
    assert len(places._weights(SimpleNamespace(neighbourhood="old_town", age=40))) == 4


def test_a_home_round_trips_through_a_save(receipts_state, matched) -> None:
    from engine.game.state import GameState
    from engine.social import attrs, places

    pid = matched("matchstick").split(":")[1]
    attrs.materialise(receipts_state, pid)
    stored = receipts_state.social["people"][pid]["attrs"]["home"]
    again = GameState.from_dict(receipts_state.to_save_dict())
    assert again.social["people"][pid]["attrs"]["home"] == stored == places.home_of(again, pid)


def test_the_art_skeleton_has_a_base_for_every_location_and_no_alts(receipts_active) -> None:
    from pathlib import Path

    import yaml

    from engine.game.locations import LOCATIONS

    root = Path(__file__).resolve().parents[1]
    rows = yaml.safe_load((root / "games/read-receipts/data/art/subjects.yaml").read_text(encoding="utf-8"))["locations"]
    assert set(rows) == set(LOCATIONS)
    for lid, row in rows.items():
        assert row["base"] in ("dawn", "day", "dusk", "night"), lid
        assert "alts" not in row and "negative" not in row, lid      # `times:` since T26 (the 48 plates)


def test_a_one_way_minutes_edge_mirrors_to_the_same_cost(tmp_path) -> None:
    from engine.game import locations

    path = tmp_path / "locations.yaml"
    path.write_text(
        "version: 1\nrings: {0: x}\nlocations:\n"
        "  a: {name: A, ring: 0, evil_multiplier: 0.1, summary: s, tags: [], connections: {b: {minutes: 7}}}\n"
        "  b: {name: B, ring: 0, evil_multiplier: 0.1, summary: s, tags: [], connections: {}}\n"
        "  c: {name: C, ring: 0, evil_multiplier: 0.1, summary: s, tags: [], connections: {d: {hours: 2}}}\n"
        "  d: {name: D, ring: 0, evil_multiplier: 0.1, summary: s, tags: [], connections: {}}\n",
        encoding="utf-8")
    graph = locations.load_locations(path)
    back = graph["b"]["connections"]["a"]
    assert back["minutes"] == 7 and back["hours"] == 0 and back["mirrored"]
    assert "minutes" not in graph["d"]["connections"]["c"] and graph["d"]["connections"]["c"]["hours"] == 2


def test_every_venue_home_and_the_registry_has_travel_minutes(receipts_active) -> None:
    from engine.social import places

    for lid in (*places.venue_ids(), *places.home_ids(), "registry_office"):
        assert places.travel_minutes(lid) > 0, lid
    assert places.travel_minutes("registry_office") == 20


def test_the_validator_reports_a_malformed_minutes_edge_as_an_error(tmp_path) -> None:
    from engine.games import validation
    from tests.test_story_content_integrity import _story

    locations = tmp_path / "locations.yaml"
    for bad, words in (("{minutes: 60}", "outside 0-59"), ("{minutes: 0}", "both 0"), ("{minutes: soon}", "whole number")):
        locations.write_text(
            "locations:\n"
            f"  a: {{name: A, ring: 0, connections: {{b: {bad}}}}}\n"
            "  b: {name: B, ring: 0, connections: {a: {minutes: 1}}}\n", encoding="utf-8")
        issues = validation.validate_story(_story(tmp_path, {"locations": str(locations)}))
        messages = "\n".join(str(i) for i in validation.errors_only(issues))
        assert "a>b" in messages and words in messages, (bad, messages)
    locations.write_text(
        "locations:\n  a: {name: A, ring: 0, connections: {b: {minutes: 5}}}\n"
        "  b: {name: B, ring: 0, connections: {a: {minutes: 5}}}\n", encoding="utf-8")
    issues = validation.validate_story(_story(tmp_path, {"locations": str(locations)}))
    assert not validation.errors_only(issues)
