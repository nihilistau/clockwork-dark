"""
Pre-generate art to fill gaps in the shipped pack.

Generation belongs HERE, not in a turn. A Grok Imagine still takes two to three
minutes; ComfyUI takes seconds but still competes with the language model for
the GPU. Either way, paying that cost while a player waits is the wrong trade,
so the game only ever reads from the shipped pack and the disk cache, and this
script is how those get filled.

    python scripts/generate_art.py --list           what is missing
    python scripts/generate_art.py --locations      every location x daypart
    python scripts/generate_art.py --portraits      every NPC and Assistant form
    python scripts/generate_art.py --items          every item in the registry
    python scripts/generate_art.py --prompts --items    print, generate nothing
    python scripts/generate_art.py --all --provider comfyui

Anything already covered by data/art/manifest.yaml or already on disk is
skipped, so re-running is cheap and interrupting is safe.

WHY --items EXISTS. 52 of the 81 declared items had no packed plate, and this
script could not have filled one in: `wanted()` only ever built location and
portrait requests, so `--all` did not mean all. The item art was reachable by
the SERVING chain (engine/media/providers/shipped.py resolves kind="item") and
unreachable by the GENERATING one.

--prompts renders and prints both dialects for every request without calling a
backend. It is the way to read what would be sent, and it is the way to check a
prompt on a machine where neither backend is installed.

Version: v0.3.0 [2026-08-08]
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.game.locations import LOCATIONS  # noqa: E402
from engine.game.inventory import load_items  # noqa: E402
from engine.media.art import render_prose, render_tags  # noqa: E402
from engine.media.providers import build_provider  # noqa: E402
from engine.media.providers.base import ImageRequest, cached_image  # noqa: E402
from engine.media.providers.shipped import ShippedArtProvider, load_manifest  # noqa: E402

DAYPARTS = ("dawn", "day", "dusk", "night")
PHASES = ("dormant", "spreading")


def wanted(kinds: set[str]) -> list[ImageRequest]:
    """Every image the game could ask for, for the selected kinds."""
    requests: list[ImageRequest] = []

    if "locations" in kinds:
        for location_id in LOCATIONS:
            for moment in DAYPARTS:
                for phase in PHASES:
                    requests.append(
                        ImageRequest(
                            subject_id=location_id,
                            kind="location",
                            time_of_day=moment,
                            evil_phase=phase,
                        )
                    )

    if "portraits" in kinds:
        manifest = load_manifest()
        subjects = set(manifest.get("assistant_forms", {})) | set(manifest.get("portraits", {}))
        subjects |= {"npc_maris", "npc_odran", "npc_ilya", "npc_sera", "npc_brindle"}
        for subject in sorted(subjects):
            requests.append(ImageRequest(subject_id=subject, kind="portrait"))

    if "items" in kinds:
        # One plate per item, no daypart and no phase variants: an item is an
        # object on a dark ground and does not change with the weather. That
        # keeps 81 items at 81 images rather than at 648.
        for item_id in sorted(load_items()):
            requests.append(ImageRequest(subject_id=item_id, kind="item"))

    return requests


def promote_items(dry_run: bool = False) -> list[tuple[str, str]]:
    """
    Move generated item plates out of the disposable cache into the shipped pack.

    WHY THIS STEP HAS TO EXIST. ``.gitignore`` ignores ``data/media/`` -- and it
    is right to: that directory is cache keyed by a sha of the request, it is
    session output, and it is disposable. The pack that ships with the game is
    ``content/scenes/clockwork/static/art/``. So an item plate that is only in
    the cache is art this machine has and nobody else ever will, and the next
    person to clear the cache loses it. Generating and not promoting is the
    difference between "the art exists" and "the art existed here on Friday".

    Copies rather than moves: the cache entry is what makes a re-run cheap, and
    the cache is what the running server is already serving from.

    RECOMPRESSED TO JPEG on the way in, when Pillow is installed. Grok Imagine
    returns a 1024x1024 PNG of about 2 MB; sixty of those is 124 MB of repo for
    sixty pictures of a nail. The pack's own plates are JPEG at a comparable
    size and nobody has ever complained about them, and these are still lifes
    on a flat dark ground -- the format JPEG is least bad at. Without Pillow it
    falls back to a straight copy, because a large picture beats no picture.

    Returns:
        (item_id, relative path under the art root) for every plate promoted,
        which is exactly the ``items:`` block data/art/manifest.yaml wants.
    """
    from engine.media.providers.base import cached_image
    from engine.media.providers.shipped import ART_ROOT

    try:
        from PIL import Image
    except ImportError:
        Image = None  # type: ignore[assignment]

    destination_dir = Path(__file__).resolve().parents[1] / ART_ROOT / "things"
    promoted: list[tuple[str, str]] = []

    for item_id in sorted(load_items()):
        request = ImageRequest(subject_id=item_id, kind="item")
        hit = cached_image(request)
        if hit is None or not hit.path:
            continue
        source = Path(hit.path)
        suffix = ".jpg" if Image is not None else source.suffix
        target = destination_dir / f"{item_id}{suffix}"
        if not dry_run:
            destination_dir.mkdir(parents=True, exist_ok=True)
            if Image is None:
                target.write_bytes(source.read_bytes())
            else:
                with Image.open(source) as image:
                    image.convert("RGB").save(target, "JPEG", quality=88, optimize=True)
        promoted.append((item_id, f"things/{target.name}"))

    return promoted


def print_prompts(requests: list[ImageRequest]) -> None:
    """Render both dialects for each request and print them. Generates nothing."""
    for request in requests:
        prose = render_prose(
            request.subject_id,
            kind=request.kind,
            time_of_day=request.time_of_day,
            evil_phase=request.evil_phase,
        )
        positive, negative = render_tags(
            request.subject_id,
            kind=request.kind,
            time_of_day=request.time_of_day,
            evil_phase=request.evil_phase,
        )
        print(
            f"\n=== {request.kind}: {request.subject_id} "
            f"({request.time_of_day}/{request.evil_phase})"
        )
        print(f"  grok    : {prose}")
        print(f"  comfy + : {positive}")
        print(f"  comfy - : {negative}")


def missing(requests: list[ImageRequest]) -> list[ImageRequest]:
    """Filter to what the shipped pack and cache do not already answer."""
    shipped = ShippedArtProvider()
    gaps = []
    for request in requests:
        if shipped.available() and shipped.generate(request).ok:
            continue
        if cached_image(request):
            continue
        gaps.append(request)
    return gaps


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pre-generate Clockwork Dark art")
    parser.add_argument("--locations", action="store_true")
    parser.add_argument("--portraits", action="store_true")
    parser.add_argument("--items", action="store_true")
    parser.add_argument("--all", action="store_true")
    parser.add_argument(
        "--prompts",
        action="store_true",
        help="Print both prompt dialects for every request and exit",
    )
    parser.add_argument(
        "--missing-only",
        action="store_true",
        help="With --prompts, print only what the shipped pack does not answer",
    )
    parser.add_argument(
        "--promote",
        action="store_true",
        help=(
            "Copy generated item plates from the disposable cache into the "
            "shipped pack and print the data/art/manifest.yaml items: block"
        ),
    )
    parser.add_argument("--list", action="store_true", help="Report gaps and exit")
    parser.add_argument("--provider", default=None, help="grokbuild | comfyui | procedural")
    parser.add_argument("--limit", type=int, default=0, help="Stop after N images")
    args = parser.parse_args(argv)

    if args.promote:
        promoted = promote_items()
        print(f"promoted {len(promoted)} item plates into the shipped pack\n")
        for item_id, relative in promoted:
            print(f"  {item_id}: {relative}")
        return 0

    kinds = set()
    if args.all or args.locations:
        kinds.add("locations")
    if args.all or args.portraits:
        kinds.add("portraits")
    if args.all or args.items:
        kinds.add("items")
    if not kinds:
        parser.print_help()
        return 1

    requests = wanted(kinds)
    gaps = missing(requests)

    if args.prompts:
        print_prompts(gaps if args.missing_only else requests)
        return 0

    print(f"{len(requests)} possible images, {len(requests) - len(gaps)} already covered, "
          f"{len(gaps)} missing")
    if args.list or not gaps:
        for request in gaps[:200]:
            print(f"  missing: {request.kind:9} {request.subject_id:22} "
                  f"{request.time_of_day:5} {request.evil_phase}")
        return 0

    from engine.config import get_config

    name = args.provider or str(get_config().get("media.image_provider", "grokbuild"))
    provider = build_provider(name)
    if provider is None or not provider.available():
        print(f"provider {name!r} is not available", file=sys.stderr)
        return 2

    todo = gaps[: args.limit] if args.limit else gaps
    print(f"generating {len(todo)} with {name} — this is slow by design; leave it running\n")

    started = time.perf_counter()
    for index, request in enumerate(todo, 1):
        label = f"{request.subject_id} ({request.time_of_day}/{request.evil_phase})"
        print(f"  [{index}/{len(todo)}] {label} ... ", end="", flush=True)
        began = time.perf_counter()
        result = provider.generate(request)
        elapsed = time.perf_counter() - began
        print(f"{result.status} in {elapsed:.0f}s" + (f" — {result.detail}" if result.detail else ""))

    print(f"\ndone in {(time.perf_counter() - started) / 60:.1f} min")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
