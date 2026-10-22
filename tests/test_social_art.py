"""READ RECEIPTS' art subjects and manifest (v0.23.0 T26, spec §18.1).

The engine reads ``locations:`` (a mapping of id to ``{subject, details, times: {daypart: {setting, light}}}``,
``engine/media/art.py``), so the pack is written in that shape with a ``base:`` per place, which the
manifest and ``shipped.lookup`` read.
"""
from __future__ import annotations

import re
from pathlib import Path

from engine import yamlio
from tests.social_fixtures import receipts_active  # noqa: F401

DAYPARTS = {"dawn", "day", "dusk", "night"}
ART = Path(__file__).resolve().parents[1] / "games" / "read-receipts" / "data" / "art"
WORLD = ART.parent / "world" / "locations.yaml"


def _load(name: str) -> dict:
    return yamlio.safe_load((ART / name).read_text(encoding="utf-8"))


def _subjects() -> dict:
    return _load("subjects.yaml")["locations"]


def test_there_are_48_plates_on_the_engines_dayparts() -> None:
    rows = _subjects()
    assert sum(len(row["times"]) for row in rows.values()) == 48
    for place, row in rows.items():
        assert set(row["times"]) <= DAYPARTS, place
        assert row["base"] in row["times"], place
        assert "alts" not in row, place


def test_every_location_of_the_world_has_a_subject() -> None:
    world = yamlio.safe_load(WORLD.read_text(encoding="utf-8"))
    ids = set(world["locations"]) if "locations" in world else set(world)
    assert len(ids) == 28
    assert set(_subjects()) == ids


def test_the_manifest_lists_only_plates_that_exist() -> None:
    """Every manifest row naming a missing file is a validator error."""
    manifest = _load("manifest.yaml")["locations"]
    for place, entry in manifest.items():
        assert "alts" not in entry and place in _subjects()
        for rel in [entry.get("base"), *entry.get("times", {}).values()]:
            assert (ART / "plates" / rel).is_file(), rel


def test_validate_content_reports_no_error_for_the_story() -> None:
    from engine.games import validation

    errors = validation.errors_only(validation.validate_story("read-receipts"))
    assert not errors, [str(e) for e in errors]


def test_no_subject_carries_a_negative_key_or_no_x_term() -> None:
    data = _load("subjects.yaml")
    assert "negative" not in data["style"]
    texts = [data["style"]["prose"], data["style"]["tags"]]
    for place, row in data["locations"].items():
        assert "negative" not in row, place
        texts += [row["subject"], row["details"]]
        for slot in row["times"].values():
            assert set(slot) == {"setting", "light"}, place
            texts += list(slot.values())
    for text in texts:
        assert not re.search(r"(?i)\bno\s+\w+", text), text


def test_lookup_pools_the_base_for_an_undeclared_daypart(receipts_active) -> None:
    from engine.media.providers import shipped
    from engine.media.providers.base import ImageRequest

    def find(subject: str, part: str):
        return shipped.lookup(
            ImageRequest(subject_id=subject, kind="location", time_of_day=part, story="read-receipts")
        )

    for place, row in _subjects().items():
        for part in DAYPARTS - set(row["times"]):
            assert find(place, part) == find(place, row["base"]), (place, part)


def test_the_story_activates_and_validates_with_its_art_paths(receipts_active) -> None:
    """Pre-flight F41: with the art paths declared and an empty `art_root`, the story still activates."""
    from engine.games import registry

    row = next(r for r in registry.catalog() if r["slug"] == "read-receipts")
    assert row["playable"] and not row["problems"], row["problems"]
    assert row["paths"]["art_root"] == "games/read-receipts/data/art/plates"
