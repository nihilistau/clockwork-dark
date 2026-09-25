"""
``scripts/generate_art.py --game <slug>`` -- an art generator for any story.

The script was flagship-shaped: no ``--game``, five hardcoded Edgewood NPC ids,
every location doubled across two evil phases, and ``--promote`` writing into
the flagship's ``things/``. HUE & CRY declares 19 location subjects x 4
dayparts and 15 portraits with an empty manifest, and the tool that was meant
to fill that pack could not name one of them.

Nothing here reaches the real Grok CLI. The provider's subprocess is replaced
per test, and ``tests/conftest.py::_no_real_grok_cli`` fails any test that
gets as far as the real one -- ``test_the_conftest_guard_catches_a_real_cli_call``
is its canary.
"""

from __future__ import annotations

import io
import re
import runpy
import shutil
import sys
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any, Iterator

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
HUE_ART = ROOT / "games" / "hue-and-cry" / "data" / "art"

sys.path.insert(0, str(ROOT))

from scripts import generate_art  # noqa: E402


def _png(path: Path, size: tuple[int, int] = (1280, 720)) -> None:
    from PIL import Image

    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, (200, 150, 90)).save(path, "PNG")


def _run(argv: list[str]) -> tuple[int, str]:
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        code = generate_art.main(argv)
    return code, buffer.getvalue()


@pytest.fixture
def cache_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The disposable generation cache, moved off the repo's data/media."""
    from engine.media.providers import base

    images = tmp_path / "cache" / "images"
    monkeypatch.setattr(base, "IMAGE_DIR", images)
    return images


@pytest.fixture
def hue(tmp_path: Path, cache_dir: Path) -> Iterator[dict[str, Path]]:
    """
    HUE & CRY active, with its manifest and plates redirected to a temp copy.

    ``--promote`` writes into the story's own tree; a test must not.
    """
    from engine.config import deep_merge, overlay, set_overlay
    from engine.games import registry

    registry.activate("hue-and-cry")
    art = tmp_path / "art"
    shutil.copytree(HUE_ART, art)
    set_overlay(
        deep_merge(
            overlay(),
            {
                "paths": {
                    "art_root": str(art / "plates"),
                    "art_manifest": str(art / "manifest.yaml"),
                }
            },
        )
    )
    yield {"art": art, "plates": art / "plates", "manifest": art / "manifest.yaml"}


def _subjects() -> dict[str, Any]:
    return yaml.safe_load((HUE_ART / "subjects.yaml").read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# The plan
# ---------------------------------------------------------------------------


def test_the_plan_is_the_storys_declared_subjects_and_nothing_else(hue: dict) -> None:
    subjects = _subjects()
    plan = generate_art.plan_plates()

    locations = [p for p in plan if p.kind == "location"]
    portraits = [p for p in plan if p.kind == "portrait"]
    items = [p for p in plan if p.kind == "item"]

    # Dayparts as DECLARED, per subject -- not a fixed four, not two phases.
    expected = {
        (sid, dp)
        for sid, entry in subjects["locations"].items()
        for dp in (entry.get("times") or {})
    }
    assert {(p.subject_id, p.time_of_day) for p in locations} == expected
    assert len(locations) == 19 * 4
    assert {p.subject_id for p in portraits} == set(subjects["portraits"])
    assert len(portraits) == 15
    assert items == []

    # No flagship id leaks in, and nothing is doubled by evil phase.
    ids = {p.subject_id for p in plan}
    assert not ids & {"npc_maris", "npc_odran", "forest_clearing", "edgewood_square"}
    assert {p.request().evil_phase for p in plan} == {"dormant"}

    # Targets are under the story's art root, in the brief's directories.
    by_key = {(p.kind, p.subject_id, p.time_of_day): p for p in plan}
    assert by_key[("location", "tallow_docks", "night")].target == "scenes/tallow-docks-night.jpg"
    assert by_key[("portrait", "npc_brask", "")].target == "portraits/npc-brask.jpg"
    # An empty manifest resolves nothing.
    assert not any(p.resolved for p in plan)


def test_a_dry_run_lists_every_plate_and_writes_nothing(hue: dict) -> None:
    before = hue["manifest"].read_bytes()
    code, out = _run(["--game", "hue-and-cry", "--dry-run"])
    assert code == 0
    rows = [line for line in out.splitlines() if line.startswith("  plan:")]
    assert len(rows) == 19 * 4 + 15
    assert any(
        "location" in r and "tallow_docks" in r and "night" in r
        and "scenes/tallow-docks-night.jpg" in r
        for r in rows
    )
    assert hue["manifest"].read_bytes() == before
    assert sorted(p.name for p in hue["plates"].rglob("*")) == [".gitkeep"]


def test_only_narrows_the_plan_to_a_subject_or_a_kind(hue: dict) -> None:
    code, out = _run(["--game", "hue-and-cry", "--dry-run", "--only", "locations:tallow_docks"])
    assert code == 0
    rows = [line for line in out.splitlines() if line.startswith("  plan:")]
    assert len(rows) == 4 and all("tallow_docks" in r for r in rows)

    _, out = _run(["--game", "hue-and-cry", "--dry-run", "--only", "portraits"])
    rows = [line for line in out.splitlines() if line.startswith("  plan:")]
    assert len(rows) == 15 and all("portrait" in r for r in rows)

    _, out = _run(
        ["--game", "hue-and-cry", "--dry-run", "--only", "locations:tallow_docks",
         "--dayparts", "night"]
    )
    rows = [line for line in out.splitlines() if line.startswith("  plan:")]
    assert len(rows) == 1 and "scenes/tallow-docks-night.jpg" in rows[0]


def test_only_refuses_a_subject_the_story_does_not_declare(hue: dict) -> None:
    # A typo must not plan nothing and report success.
    with pytest.raises(SystemExit) as raised:
        _run(["--game", "hue-and-cry", "--dry-run", "--only", "locations:forest_clearing"])
    assert raised.value.code == 2


# ---------------------------------------------------------------------------
# Generation, with the CLI stubbed
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_grok(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """The Grok CLI, replaced: records each instruction and writes a PNG."""
    from engine.media.providers import grokbuild

    instructions: list[str] = []

    def run(argv: list[str], **_: Any) -> Any:
        instruction = argv[argv.index("-p") + 1]
        instructions.append(instruction)
        destination = re.search(r"save the result to '([^']+)'", instruction).group(1)
        _png(Path(destination))
        return grokbuild.subprocess.CompletedProcess(argv, 0, b"{}", b"")

    monkeypatch.setattr(grokbuild.GrokImagineProvider, "_resolve_command", lambda self: "grok")
    monkeypatch.setattr(grokbuild.subprocess, "run", run)
    return instructions


def test_generation_sends_the_storys_own_prompt(hue: dict, fake_grok: list[str]) -> None:
    from engine.media.art import render_prose

    code, out = _run(
        ["--game", "hue-and-cry", "--only", "locations:tallow_docks", "--dayparts", "night",
         "--provider", "grokbuild"]
    )
    assert code == 0, out
    assert len(fake_grok) == 1
    instruction = fake_grok[0]
    prose = render_prose("tallow_docks", kind="location", time_of_day="night")
    assert prose in instruction
    assert "one shaded lantern moving between the crates" in instruction  # the night slot
    assert "candle-making port city" in instruction  # the house style
    assert "aspect_ratio='16:9'" in instruction
    # Generation fills the cache; the pack is only written by --promote.
    assert sorted(p.name for p in hue["plates"].rglob("*")) == [".gitkeep"]


def test_promote_writes_plates_and_the_manifest_lookup_reads(
    hue: dict, cache_dir: Path
) -> None:
    from PIL import Image

    from engine.media.providers.base import ImageRequest
    from engine.media.providers.shipped import lookup

    night = ImageRequest(subject_id="tallow_docks", kind="location", time_of_day="night")
    brask = ImageRequest(subject_id="npc_brask", kind="portrait")
    _png(cache_dir / f"{night.cache_key()}.png", (1280, 720))
    _png(cache_dir / f"{brask.cache_key()}.png", (1024, 1024))

    code, out = _run(["--game", "hue-and-cry", "--promote"])
    assert code == 0, out

    scene = hue["plates"] / "scenes" / "tallow-docks-night.jpg"
    portrait = hue["plates"] / "portraits" / "npc-brask.jpg"
    # Landed at the story's declared formats, as JPEG.
    with Image.open(scene) as image:
        assert (image.format, image.size) == ("JPEG", (1344, 768))
    with Image.open(portrait) as image:
        assert (image.format, image.size) == ("JPEG", (768, 1024))

    text = hue["manifest"].read_text(encoding="utf-8")
    assert "EMPTY UNTIL v1.0" in text  # the header comment survives
    data = yaml.safe_load(text)
    assert data["locations"] == {
        "tallow_docks": {"times": {"night": "scenes/tallow-docks-night.jpg"}}
    }
    assert data["portraits"] == {"npc_brask": "portraits/npc-brask.jpg"}
    assert data["root"] == "/story-art" and data["items"] == {}

    # The serving chain now finds them, and only for the slot that was drawn.
    assert lookup(night) == "scenes/tallow-docks-night.jpg"
    assert lookup(brask) == "portraits/npc-brask.jpg"
    assert lookup(ImageRequest(subject_id="tallow_docks", time_of_day="dawn")) is None

    # --missing (the default) now skips exactly those two.
    plan = generate_art.plan_plates()
    resolved = {(p.subject_id, p.time_of_day) for p in plan if p.resolved}
    assert resolved == {("tallow_docks", "night"), ("npc_brask", "")}


def test_a_promote_dry_run_writes_nothing(hue: dict, cache_dir: Path) -> None:
    from engine.media.providers.base import ImageRequest

    night = ImageRequest(subject_id="tallow_docks", kind="location", time_of_day="night")
    _png(cache_dir / f"{night.cache_key()}.png")
    before = hue["manifest"].read_bytes()

    code, out = _run(["--game", "hue-and-cry", "--promote", "--dry-run"])
    assert code == 0
    assert "scenes/tallow-docks-night.jpg" in out
    assert hue["manifest"].read_bytes() == before
    assert sorted(p.name for p in hue["plates"].rglob("*")) == [".gitkeep"]


MANIFEST_WITH_HISTORY = """\
# A header that explains the pack.
version: 1
root: "/story-art"

# ---- Locations ----
locations:
  # The quay, drawn once already.
  tallow_docks:
    base: scenes/old-docks.jpg   # hand-imported
    times:
      dawn: scenes/tallow-docks-dawn.jpg

  wickmarket: {base: scenes/wickmarket.jpg}

# ---- Portraits ----
portraits:
  npc_ardane: portraits/npc-ardane.jpg  # the captain
items: {}
"""


def test_the_manifest_write_keeps_what_was_there() -> None:
    merged = generate_art.merge_manifest_text(
        MANIFEST_WITH_HISTORY,
        [
            ("locations", "tallow_docks", "night", "scenes/tallow-docks-night.jpg"),
            ("locations", "the_snuffs", "day", "scenes/the-snuffs-day.jpg"),
            ("portraits", "npc_brask", "", "portraits/npc-brask.jpg"),
            ("items", "tallow_candle", "", "items/tallow-candle.jpg"),
        ],
    )
    for comment in (
        "# A header that explains the pack.",
        "# ---- Locations ----",
        "# ---- Portraits ----",
        "wickmarket: {base: scenes/wickmarket.jpg}",
        "npc_ardane: portraits/npc-ardane.jpg  # the captain",
    ):
        assert comment in merged, comment
    data = yaml.safe_load(merged)
    assert data["locations"]["tallow_docks"] == {
        "base": "scenes/old-docks.jpg",
        "times": {
            "dawn": "scenes/tallow-docks-dawn.jpg",
            "night": "scenes/tallow-docks-night.jpg",
        },
    }
    assert data["locations"]["wickmarket"] == {"base": "scenes/wickmarket.jpg"}
    assert data["locations"]["the_snuffs"] == {"times": {"day": "scenes/the-snuffs-day.jpg"}}
    assert data["portraits"] == {
        "npc_ardane": "portraits/npc-ardane.jpg",
        "npc_brask": "portraits/npc-brask.jpg",
    }
    assert data["items"] == {"tallow_candle": "items/tallow-candle.jpg"}
    # A new portrait lands inside its own section, above nothing it should not.
    assert merged.index("npc_brask") > merged.index("# ---- Portraits ----")


def test_the_manifest_write_adds_a_section_the_file_lacks() -> None:
    merged = generate_art.merge_manifest_text(
        "version: 1\nroot: /story-art\n", [("portraits", "pip", "", "portraits/pip.jpg")]
    )
    assert yaml.safe_load(merged) == {
        "version": 1, "root": "/story-art", "portraits": {"pip": "portraits/pip.jpg"}
    }


def test_a_quoted_key_collision_refuses_instead_of_appending() -> None:
    """The entry finder matches bare keys; a quoted one it missed used to get
    a second, bare entry appended -- a duplicate key the re-parse could not
    see, because the last one wins."""
    text = 'version: 1\nportraits:\n  "npc_brask": portraits/old-brask.jpg\n'
    with pytest.raises(ValueError, match="npc_brask"):
        generate_art.merge_manifest_text(
            text, [("portraits", "npc_brask", "", "portraits/npc-brask.jpg")]
        )


@pytest.mark.parametrize("broken", [
    "locations: [\n",                     # parser error
    "version: 1\nversion: 2\n",           # a duplicate key already there
    "a: &x 1\nb: *y\n",                   # composer error
])
def test_a_manifest_yaml_cannot_read_is_a_value_error(broken: str) -> None:
    with pytest.raises(ValueError):
        generate_art.merge_manifest_text(broken, [("portraits", "pip", "", "portraits/pip.jpg")])


def test_a_broken_manifest_is_reported_not_a_traceback(hue: dict, cache_dir: Path) -> None:
    from engine.media.providers.base import ImageRequest

    night = ImageRequest(subject_id="tallow_docks", kind="location", time_of_day="night")
    _png(cache_dir / f"{night.cache_key()}.png")
    hue["manifest"].write_text("locations: [\n", encoding="utf-8")
    with pytest.raises(SystemExit) as caught:
        _run(["--game", "hue-and-cry", "--promote"])
    assert caught.value.code == 2
    assert sorted(p.name for p in hue["plates"].rglob("*")) == [".gitkeep"]


def test_promote_refuses_a_target_outside_the_art_root(hue: dict, cache_dir: Path) -> None:
    from engine.media.providers.base import ImageRequest

    brask = ImageRequest(subject_id="npc_brask", kind="portrait")
    _png(cache_dir / f"{brask.cache_key()}.png", (768, 1024))
    before = hue["manifest"].read_bytes()
    stray = generate_art.Plate("portrait", "npc_brask", "", "../../escaped.jpg", False)
    with pytest.raises(ValueError, match="art root"):
        generate_art.promote_plates([stray])
    assert not (hue["plates"].parent.parent / "escaped.jpg").exists()
    assert hue["manifest"].read_bytes() == before


def test_the_flagship_promote_dry_run_says_it_promoted_nothing(cache_dir: Path) -> None:
    code, out = _run(["--promote", "--dry-run"])
    assert code == 0
    assert out.startswith("would promote 0 item plates"), out
    assert "promoted nothing" in out


# ---------------------------------------------------------------------------
# art_missing.py agrees
# ---------------------------------------------------------------------------


def _brief(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    out = tmp_path / "brief.md"
    monkeypatch.setattr(
        sys, "argv", ["art_missing.py", "--game", "hue-and-cry", "--out", str(out)]
    )
    with redirect_stdout(io.StringIO()):
        runpy.run_path(str(ROOT / "scripts" / "art_missing.py"), run_name="__main__")
    return out.read_text(encoding="utf-8")


def test_the_missing_brief_agrees_with_the_generator(
    hue: dict, cache_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from engine.media.providers.base import ImageRequest

    night = ImageRequest(subject_id="tallow_docks", kind="location", time_of_day="night")
    _png(cache_dir / f"{night.cache_key()}.png")
    assert _run(["--game", "hue-and-cry", "--promote"])[0] == 0

    brief = _brief(tmp_path, monkeypatch)
    listed = set(re.findall(r"- \*\*File:\*\* `([^`]+)`", brief))
    wanted = {p.target for p in generate_art.plan_plates() if not p.resolved}
    assert listed == wanted
    assert "scenes/tallow-docks-night.jpg" not in listed
    assert "scenes/tallow-docks-dawn.jpg" in listed
    # The sizes table is this story's formats, not a copied constant.
    assert "| location | 1344x768 |" in brief


# ---------------------------------------------------------------------------
# The flagship default is unchanged
# ---------------------------------------------------------------------------


def _legacy_recipe() -> list[tuple[str, str, str, str]]:
    """The plan exactly as v0.12's generate_art.wanted() built it."""
    from engine.game.inventory import load_items
    from engine.game.locations import LOCATIONS
    from engine.media.providers.shipped import load_manifest

    rows = [
        (loc, "location", moment, phase)
        for loc in LOCATIONS
        for moment in ("dawn", "day", "dusk", "night")
        for phase in ("dormant", "spreading")
    ]
    manifest = load_manifest()
    portraits = set(manifest.get("assistant_forms", {})) | set(manifest.get("portraits", {}))
    portraits |= {"npc_maris", "npc_odran", "npc_ilya", "npc_sera", "npc_brindle"}
    rows += [(s, "portrait", "dawn", "dormant") for s in sorted(portraits)]
    rows += [(i, "item", "dawn", "dormant") for i in sorted(load_items())]
    return rows


def test_the_flagship_plan_is_the_one_it_always_was(cache_dir: Path) -> None:
    from engine.games import registry

    requests = generate_art.wanted({"locations", "portraits", "items"})
    assert [
        (r.subject_id, r.kind, r.time_of_day, r.evil_phase) for r in requests
    ] == _legacy_recipe()
    assert registry.peek() is None


@pytest.mark.parametrize("argv", [[], ["--game", "clockwork-dark"]])
def test_the_flagship_dry_run_lists_the_legacy_gaps(cache_dir: Path, argv: list[str]) -> None:
    from engine.games import registry

    gaps = generate_art.missing(generate_art.wanted({"locations", "portraits", "items"}))
    code, out = _run([*argv, "--all", "--dry-run"])
    assert code == 0
    rows = [line for line in out.splitlines() if line.startswith("  plan:")]
    assert len(rows) == len(gaps)
    for row, request in zip(rows, gaps):
        assert request.subject_id in row and request.kind in row
    # Same summary line --list has always printed.
    total = len(generate_art.wanted({"locations", "portraits", "items"}))
    assert out.splitlines()[0] == (
        f"{total} possible images, {total - len(gaps)} already covered, {len(gaps)} missing"
    )
    # The flagship path activates nothing, exactly as before.
    assert registry.peek() is None


def test_the_flagship_list_output_is_unchanged(cache_dir: Path) -> None:
    code, out = _run(["--all", "--list"])
    assert code == 0
    gaps = generate_art.missing(generate_art.wanted({"locations", "portraits", "items"}))
    expected = [
        f"  missing: {r.kind:9} {r.subject_id:22} {r.time_of_day:5} {r.evil_phase}"
        for r in gaps[:200]
    ]
    assert out.splitlines()[1:] == expected


# ---------------------------------------------------------------------------
# The guard
# ---------------------------------------------------------------------------


def test_the_conftest_guard_catches_a_real_cli_call(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
    cache_dir: Path,
    tmp_path: Path,
) -> None:
    """
    Canary for ``tests/conftest.py::_no_real_grok_cli``.

    A test that reaches the provider's subprocess without stubbing it must
    fail. The guard raises at the call AND records the breach for teardown,
    because a worker thread may swallow the raise; this test clears the record
    after checking it, which is the only reason it passes.

    The command is a path that does not exist, so with the guard removed this
    fails SAFELY -- the real subprocess raises FileNotFoundError, the provider
    reports a failed result, and no AssertionError is raised -- rather than
    launching whatever `grok` is on PATH.
    """
    from engine.media.providers.base import ImageRequest
    from engine.media.providers.grokbuild import GrokImagineProvider

    nowhere = str(tmp_path / "no-such-grok.exe")
    monkeypatch.setattr(GrokImagineProvider, "_resolve_command", lambda self: nowhere)
    with pytest.raises(AssertionError, match="Grok CLI"):
        GrokImagineProvider().generate(ImageRequest(subject_id="tallow_docks"))
    calls = request.node.grok_cli_calls
    assert calls == [nowhere]
    calls.clear()


# ---------------------------------------------------------------------------
# The generation cache is per story (except the flagship's, which is as it was)
# ---------------------------------------------------------------------------


def test_the_flagship_cache_keys_are_the_ones_already_on_disk() -> None:
    """
    Known keys, computed from the pre-v0.13 formula: sha256 of
    ``kind|subject|daypart|phase``. A change here orphans every cached
    flagship image.
    """
    from engine.games import registry
    from engine.media.providers.base import ImageRequest

    assert registry.peek() is None
    implicit = ImageRequest(subject_id="forest_clearing")
    explicit = ImageRequest(subject_id="forest_clearing", story="clockwork-dark")
    assert implicit.cache_key() == explicit.cache_key() == "0f90787dd6246069"
    assert ImageRequest(subject_id="npc_maris", kind="portrait").cache_key() == "ad26221dd5a99957"
    # The legacy flagship plan names its story, so a config default pointing
    # elsewhere cannot move its keys.
    assert {r.story for r in generate_art.wanted({"portraits"})} == {"clockwork-dark"}


def test_two_stories_sharing_a_subject_id_share_no_cache_entry() -> None:
    from engine.games import registry
    from engine.media.providers.base import ImageRequest

    garden = ImageRequest(subject_id="sophia", kind="portrait", story="wicked-garden")
    bench = ImageRequest(subject_id="sophia", kind="portrait", story="dev-story")
    flagship = ImageRequest(subject_id="sophia", kind="portrait", story="clockwork-dark")
    assert len({garden.cache_key(), bench.cache_key(), flagship.cache_key()}) == 3

    # A request made while a story runs belongs to that story.
    registry.activate("dev-story")
    assert ImageRequest(subject_id="sophia", kind="portrait").cache_key() == bench.cache_key()


def test_promote_never_copies_another_storys_image(
    tmp_path: Path, cache_dir: Path
) -> None:
    from engine.config import deep_merge, overlay, set_overlay
    from engine.games import registry
    from engine.media.providers.base import ImageRequest

    registry.activate("dev-story")
    art = tmp_path / "bench-art"
    (art / "plates").mkdir(parents=True)
    shutil.copy(ROOT / "games" / "dev-story" / "data" / "art" / "manifest.yaml", art)
    set_overlay(deep_merge(overlay(), {"paths": {
        "art_root": str(art / "plates"), "art_manifest": str(art / "manifest.yaml"),
    }}))

    # The Garden's sophia is in the cache; the bench's is not.
    garden = ImageRequest(subject_id="sophia", kind="portrait", story="wicked-garden")
    _png(cache_dir / f"{garden.cache_key()}.png", (768, 1024))
    code, out = _run(["--game", "dev-story", "--only", "portraits:sophia", "--promote"])
    assert code == 0, out
    assert "promoted 0 plates" in out
    assert not (art / "plates" / "portraits" / "sophia.jpg").exists()

    bench = ImageRequest(subject_id="sophia", kind="portrait", story="dev-story")
    _png(cache_dir / f"{bench.cache_key()}.png", (768, 1024))
    code, out = _run(["--game", "dev-story", "--only", "portraits:sophia", "--promote"])
    assert "promoted 1 plates" in out
    assert (art / "plates" / "portraits" / "sophia.jpg").exists()
