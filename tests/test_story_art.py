"""
Story-owned art packs.

Until v0.2.1 the art root was a module constant naming the FLAGSHIP's static
tree (``engine/media/providers/shipped.py::ART_ROOT``). A second story could
write a manifest, but every path in it was resolved inside Edgewood's
directory, missed, and fell through to the procedural silhouette. The Wicked
Garden shipped that way: 177 concept assets on disk and not one of them
reachable.

Two things had to become per-story, and this file holds both to their contract:

  1. ``paths.art_root``      WHERE the files are. Defaults to exactly the old
                             constant, so the two shipped games are untouched.
  2. ``GET /story-art/<p>``  HOW the browser gets them. Flask's ``/static``
                             handler is bound to the scene package, not to the
                             active game, so a story keeping plates in its own
                             tree had no URL at all -- the manifest resolved,
                             the file existed, and the browser got a 404.

The regression bar is the last three tests: both shipped games must resolve the
same number of pictures at the same URLs as before this seam existed.

Version: v0.1.0 [2026-08-08]
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator

import pytest
import yaml

from engine.config import get_config, project_root
from engine.games import registry
from engine.media.providers.base import ImageRequest
from engine.media.providers.shipped import (
    ART_ROOT,
    ShippedArtProvider,
    art_root,
    load_manifest,
    reset_manifest_cache,
)

_ROOT = project_root()
GARDEN = "wicked-garden"
SHIPPED = ("clockwork-dark", "drowned-carillon")

# The flagship pack, counted before this seam existed. These are golden
# numbers: they are here to fail loudly if repointing the root moves a picture
# in a story that never asked for one.
FLAGSHIP_RESOLVED = {"locations": 20, "items": 81, "portraits": 4, "enemies": 5}


@pytest.fixture
def garden() -> Iterator[Any]:
    """
    Activate The Wicked Garden, then put the process back.

    Teardown is not optional -- activation mutates process-global config and a
    dozen module caches. Same reasoning as ``tests/test_games.py::carillon``.
    """
    manifest = registry.activate(GARDEN)
    try:
        yield manifest
    finally:
        registry.deactivate()
        reset_manifest_cache()


@pytest.fixture(params=SHIPPED)
def shipped_game(request: Any) -> Iterator[str]:
    slug = str(request.param)
    registry.activate(slug)
    try:
        yield slug
    finally:
        registry.deactivate()
        reset_manifest_cache()


def _count_resolved(manifest: dict[str, Any]) -> dict[str, int]:
    """How many entries in each block resolve to a file that exists."""
    provider = ShippedArtProvider()
    kinds = {"locations": "location", "items": "item", "portraits": "portrait", "enemies": "enemy"}
    out: dict[str, int] = {}
    for block, kind in kinds.items():
        out[block] = sum(
            1
            for subject in manifest.get(block, {})
            if provider.generate(ImageRequest(subject_id=subject, kind=kind)).ok
        )
    return out


# ---------------------------------------------------------------------------
# the seam
# ---------------------------------------------------------------------------


def test_the_default_art_root_is_exactly_the_old_hardcoded_constant() -> None:
    """
    The whole compatibility claim rests on this one line of config.

    Anything else in ``config/default.yaml`` and the two shipped games move
    silently: their manifests are unchanged, so a wrong root simply resolves
    nothing and the game paints silhouettes with no error anywhere.
    """
    assert get_config().get("paths.art_root") == str(ART_ROOT).replace("\\", "/")


def test_an_unconfigured_root_still_answers(monkeypatch: Any) -> None:
    """
    A config with no ``paths.art_root`` at all must fall back to the flagship
    tree rather than to None.

    ``resolve_path`` returns Optional, and the caller that forgot that is how a
    provider starts joining paths onto None. An empty ConfigManager is stubbed
    in rather than deleting the key from the live one -- reaching into
    ``ConfigManager._data`` is the exact practice ``set_overlay`` exists to end.
    """
    from engine.config import ConfigManager
    from engine.media.providers import shipped as shipped_module

    reset_manifest_cache()
    monkeypatch.setattr(shipped_module, "get_config", lambda: ConfigManager({}))
    try:
        assert art_root() == _ROOT / ART_ROOT
    finally:
        reset_manifest_cache()


def test_the_garden_resolves_against_its_own_tree(garden: Any) -> None:
    """The bug this seam fixes, stated as its inverse."""
    assert art_root() == _ROOT / "games" / "wicked-garden" / "data" / "art" / "plates"
    assert art_root() != _ROOT / ART_ROOT


def test_the_garden_serves_from_its_own_url_prefix(garden: Any) -> None:
    """
    ``root:`` is what makes the URL, and it must NOT be ``/static/art``.

    A story-owned pack under /static is a 404 with no log line: Flask's static
    handler belongs to the scene package and knows nothing about the game.
    """
    result = ShippedArtProvider().generate(
        ImageRequest(subject_id="heart_grove", kind="location", time_of_day="night")
    )
    assert result.ok
    assert result.url.startswith("/story-art/")


# ---------------------------------------------------------------------------
# the Garden's pack
# ---------------------------------------------------------------------------


def test_every_garden_manifest_path_is_a_file_on_disk(garden: Any) -> None:
    """
    A manifest entry pointing at nothing degrades silently to the silhouette,
    which is indistinguishable from having no plate at all. Name the offenders.
    """
    manifest = load_manifest()
    root = art_root()
    missing: list[str] = []
    for block in ("locations", "portraits", "items", "stills"):
        entry = manifest.get(block, {})
        for subject, value in entry.items():
            paths = (
                [value.get("base"), *value.get("alts", []), *value.get("corrupted", [])]
                if isinstance(value, dict)
                else [value]
            )
            for relative in [p for p in paths if p]:
                if not (root / str(relative)).is_file():
                    missing.append(f"{block}.{subject} -> {relative}")
    assert not missing, "manifest entries with no file: " + "; ".join(missing)


def test_every_garden_manifest_id_is_a_real_id(garden: Any) -> None:
    """
    The other half of the same failure: a real file behind an id nothing asks
    for is a plate that can never be shown.

    The Sophia wardrobe/expression keys and `player_silhouette` are exempt and
    say so in the manifest -- they are addressable extras, not registry ids.
    """
    manifest = load_manifest()
    base = _ROOT / "games" / "wicked-garden" / "data"

    locations = set(yaml.safe_load((base / "world" / "locations.yaml").read_text(encoding="utf-8"))["locations"])
    npcs = set(yaml.safe_load((base / "world" / "npc_schedules.yaml").read_text(encoding="utf-8")).get("npcs", {}))
    items = {
        str(row["id"])
        for path in (base / "items").glob("*.yaml")
        for row in (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("items", [])
    }

    assert set(manifest["locations"]) <= locations
    assert set(manifest["items"]) <= items
    extras = {k for k in manifest["portraits"] if k.startswith("sophia_") or k == "player_silhouette"}
    assert set(manifest["portraits"]) - extras <= npcs | {"sophia"}


def test_the_garden_resolves_the_plates_it_claims_to(garden: Any) -> None:
    """
    Golden counts, so a future edit that drops a block is loud.

    Eight of fourteen places, eight of nine portraits (plus eight addressable
    extras) and twenty-two of twenty-three items. The gaps are real and are
    listed in the manifest; they are NOT filled by pointing an id at a
    neighbour, and this number going UP without new files is that bug.
    """
    assert _count_resolved(load_manifest()) == {
        "locations": 8,
        "items": 22,
        "portraits": 16,
        "enemies": 0,
    }


def test_the_garden_never_borrows_a_neighbours_picture(garden: Any) -> None:
    """The six places with no plate must resolve to nothing, not to a lookalike."""
    provider = ShippedArtProvider()
    for place in (
        "mortal_threshold",
        "path_first_petals",
        "aviary_unsent",
        "night_market",
        "briar_deep",
        "unknown",
    ):
        for when in ("dawn", "day", "dusk", "night"):
            result = provider.generate(
                ImageRequest(subject_id=place, kind="location", time_of_day=when)
            )
            assert not result.ok, f"{place} at {when} resolved to {result.detail}"


def test_every_gap_has_a_generation_prompt(garden: Any) -> None:
    """
    A missing plate is only acceptable while it is actionable.

    subjects.yaml is the one source both renderers read
    (``engine/media/art.py::render_prose`` and ``::render_tags``), so a gap
    with an entry there is a generation run away from being filled.
    """
    subjects = yaml.safe_load(
        (_ROOT / "games" / "wicked-garden" / "data" / "art" / "subjects.yaml").read_text(
            encoding="utf-8"
        )
    )
    for place in ("mortal_threshold", "path_first_petals", "aviary_unsent", "night_market", "briar_deep", "unknown"):
        assert subjects["locations"][place]["subject"]
    assert subjects["portraits"]["court_generic"]["subject"]
    assert subjects["items"]["sap_sketch"]["subject"]


# ---------------------------------------------------------------------------
# generation targets and style variants
#
# Both of these were found by generating the missing-plate brief and reading it:
# the prompts came out arguing with their own subjects, and the sizes came out
# describing a different story's pack.
# ---------------------------------------------------------------------------


def test_generation_targets_match_the_pack_that_ships(garden: Any) -> None:
    """
    `formats:` is READ -- grokbuild.py and comfy.py size every live request from
    it -- so it has to describe THIS pack.

    The Garden's block arrived as a verbatim copy of the flagship's, whose item
    art is square icons. Its own twenty-two item cards are 3:4 reliquary
    portraits, so a generated item came back 1:1 and sat wrong beside all of
    them. Asserted against the files on disk rather than against numbers typed
    here, because the point is that the two agree.
    """
    from PIL import Image

    from engine.media.art import format_for

    root = _ROOT / "games" / "wicked-garden" / "data" / "art" / "plates"
    for kind, folder in (("location", "scenes"), ("portrait", "portraits"), ("item", "items")):
        plates = sorted((root / folder).glob("*.jpg"))
        assert plates, folder
        sizes = {Image.open(p).size for p in plates}
        assert len(sizes) == 1, f"{folder} is not one size: {sizes}"
        spec = format_for(kind)
        assert (spec["width"], spec["height"]) == sizes.pop(), kind


def test_a_subject_may_opt_out_of_the_house_style(garden: Any) -> None:
    """
    Two of fourteen locations are deliberately NOT the Garden.

    The shared style block puts vines, petals and botanical art nouveau in every
    frame, which is what makes the pack one pack -- and is the opposite of a
    drab mortal flat and a formless void. Being the absence of the Garden is a
    look, so it gets a declared variant rather than a hand edit at generation
    time that nothing records.
    """
    from engine.media.art import render_prose, render_tags

    for subject_id in ("mortal_threshold", "unknown"):
        prose = render_prose(subject_id)
        positive, negative = render_tags(subject_id)
        assert "botanical art nouveau" not in positive, subject_id
        assert "vines" not in prose.lower(), subject_id
        # And the variant pushes the other way, because the LoRA stack it still
        # loads is called Botanical_Fantasy.
        assert "vines" in negative, subject_id

    # Every other location keeps the house style. This is the half that matters:
    # an opt-out that leaked would cost the pack its coherence.
    prose = render_prose("gate_of_briars")
    positive, negative = render_tags("gate_of_briars")
    assert "botanical art nouveau" in positive
    assert "vines" in prose.lower()
    assert "vines" not in negative


def test_an_unknown_variant_falls_back_to_the_house_style() -> None:
    """A typo costs a prompt its exception, not all of its art direction."""
    from engine.media.art import style_for

    registry.activate(GARDEN)
    try:
        assert style_for("no_such_variant", "prose") == style_for("", "prose")
        assert style_for("", "prose") != style_for("mortal", "prose")
    finally:
        registry.deactivate()
        reset_manifest_cache()


def test_a_story_with_no_variants_is_unaffected(shipped_game: str) -> None:
    """
    The flagship declares no `style.variants`. Adding the seam cost it nothing.
    """
    from engine.media.art import render_prose, style_for

    assert style_for("", "prose") == style_for("anything", "prose")
    assert render_prose("forest_clearing")


# ---------------------------------------------------------------------------
# the HTTP route
# ---------------------------------------------------------------------------


def _client(app: Any) -> Any:
    return app.test_client()


def test_story_art_serves_the_active_storys_tree(garden: Any) -> None:
    from content.scenes.clockwork.clockwork_scene import create_app

    _, app = create_app(testing=True)
    response = _client(app).get("/story-art/scenes/heart-grove.jpg")
    assert response.status_code == 200
    assert response.headers["Content-Type"].startswith("image/")


def test_story_art_refuses_to_climb_out_of_the_root(garden: Any) -> None:
    """
    The directory is outside ``static/``, so Flask is not doing this check.

    Same reasoning as ``engine/api/media.py``, and the same helper does it.
    """
    from content.scenes.clockwork.clockwork_scene import create_app

    _, app = create_app(testing=True)
    client = _client(app)
    for attempt in ("../../game.yaml", "..%2f..%2fgame.yaml", "../../../config/default.yaml"):
        assert client.get(f"/story-art/{attempt}").status_code == 404


def test_story_art_404s_rather_than_raising_on_a_miss(garden: Any) -> None:
    from content.scenes.clockwork.clockwork_scene import create_app

    _, app = create_app(testing=True)
    assert _client(app).get("/story-art/scenes/no-such-plate.jpg").status_code == 404


# ---------------------------------------------------------------------------
# the regression bar
# ---------------------------------------------------------------------------


def test_shipped_games_still_resolve_against_the_flagship_tree(shipped_game: str) -> None:
    assert art_root() == _ROOT / ART_ROOT


def test_shipped_games_still_serve_from_static(shipped_game: str) -> None:
    """Their manifests keep ``root: /static/art`` and Flask keeps serving it."""
    result = ShippedArtProvider().generate(
        ImageRequest(subject_id="forest_clearing", kind="location", time_of_day="day")
    )
    assert result.ok
    assert result.url.startswith("/static/art/")


def test_shipped_games_resolve_exactly_what_they_did_before(shipped_game: str) -> None:
    """
    The Drowned Carillon declares no ``art_manifest`` and therefore inherits
    the flagship's. That is pre-existing behaviour, not something this seam
    introduced, and pinning it here is what would catch a change to it.
    """
    assert _count_resolved(load_manifest()) == FLAGSHIP_RESOLVED
