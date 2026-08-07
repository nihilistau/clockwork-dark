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
    python scripts/generate_art.py --all --provider comfyui

Anything already covered by data/art/manifest.yaml or already on disk is
skipped, so re-running is cheap and interrupting is safe.

Version: v0.2.0 [2026-08-07]
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.game.locations import LOCATIONS  # noqa: E402
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

    return requests


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
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--list", action="store_true", help="Report gaps and exit")
    parser.add_argument("--provider", default=None, help="grokbuild | comfyui | procedural")
    parser.add_argument("--limit", type=int, default=0, help="Stop after N images")
    args = parser.parse_args(argv)

    kinds = set()
    if args.all or args.locations:
        kinds.add("locations")
    if args.all or args.portraits:
        kinds.add("portraits")
    if not kinds:
        parser.print_help()
        return 1

    requests = wanted(kinds)
    gaps = missing(requests)

    print(f"{len(requests)} possible images, {len(requests) - len(gaps)} already covered, "
          f"{len(gaps)} missing")
    if args.list or not gaps:
        for request in gaps[:60]:
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
