"""
Pre-generate art to fill gaps in a story's shipped pack.

Generation belongs HERE, not in a turn. A Grok Imagine still takes two to three
minutes; ComfyUI takes seconds but still competes with the language model for
the GPU. Either way, paying that cost while a player waits is the wrong trade,
so the game only ever reads from the shipped pack and the disk cache, and this
script is how those get filled.

THE FLAGSHIP (the default, and ``--game clockwork-dark``) keeps its plan
exactly as it was:

    python scripts/generate_art.py --list           what is missing
    python scripts/generate_art.py --locations      every location x daypart x phase
    python scripts/generate_art.py --portraits      every NPC and Assistant form
    python scripts/generate_art.py --items          every item in the registry
    python scripts/generate_art.py --prompts --items    print, generate nothing
    python scripts/generate_art.py --all --provider comfyui

Anything already covered by games/clockwork-dark/data/art/manifest.yaml or
already on disk is skipped, so re-running is cheap and interrupting is safe.

ANY OTHER STORY (``--game <slug>``) is planned from that story's own
``paths.art_subjects`` -- every declared location at each daypart its
``times:`` block declares (one plate if it declares none), every portrait,
every item -- and nothing else: no flagship ids, no evil-phase doubling.

    python scripts/generate_art.py --game hue-and-cry --dry-run
    python scripts/generate_art.py --game hue-and-cry --only locations:tallow_docks
    python scripts/generate_art.py --game hue-and-cry --only portraits --dayparts night
    python scripts/generate_art.py --game hue-and-cry --promote

``--dry-run`` lists each plate (kind, subject, daypart, target path) and writes
nothing. ``--missing`` (the default) skips a plate the story's manifest already
resolves -- the same test the serving chain uses (``shipped.lookup``), and the
same one ``scripts/art_missing.py`` briefs from, through ``plan_plates``.
Generation lands in the disposable cache (``data/media/images``); ``--promote``
then copies each cached plate under the story's ``paths.art_root`` (JPEG, at
the story's declared ``formats:`` size) and writes it into ``paths.art_manifest``
in the shape ``lookup`` reads: ``locations.<id>.times.<daypart>``,
``portraits.<id>``, ``items.<id>``.

WHY --items EXISTS. 52 of the 81 declared items had no packed plate, and this
script could not have filled one in: `wanted()` only ever built location and
portrait requests, so `--all` did not mean all. The item art was reachable by
the SERVING chain (engine/media/providers/shipped.py resolves kind="item") and
unreachable by the GENERATING one.

--prompts renders and prints both dialects for every request without calling a
backend. It is the way to read what would be sent, and it is the way to check a
prompt on a machine where neither backend is installed.

Version: v0.4.0 [2026-09-25]
"""

from __future__ import annotations

import argparse
import copy
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.game.locations import LOCATIONS  # noqa: E402
from engine.games import registry  # noqa: E402
from engine.game.inventory import load_items  # noqa: E402
from engine.media.art import render_prose, render_tags  # noqa: E402
from engine.media.providers import build_provider  # noqa: E402
from engine.media.providers.base import ImageRequest, cached_image  # noqa: E402
from engine.media.providers.shipped import ShippedArtProvider, load_manifest  # noqa: E402

DAYPARTS = ("dawn", "day", "dusk", "night")
PHASES = ("dormant", "spreading")

#: The flagship's plan below is the flagship's whatever story config names as
#: the default, so its requests name it -- and with it the cache keys every
#: image already generated for it is stored under.
FLAGSHIP = registry.DEFAULT_SLUG


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
                            story=FLAGSHIP,
                        )
                    )

    if "portraits" in kinds:
        manifest = load_manifest()
        subjects = set(manifest.get("assistant_forms", {})) | set(manifest.get("portraits", {}))
        subjects |= {"npc_maris", "npc_odran", "npc_ilya", "npc_sera", "npc_brindle"}
        for subject in sorted(subjects):
            requests.append(ImageRequest(subject_id=subject, kind="portrait", story=FLAGSHIP))

    if "items" in kinds:
        # One plate per item, no daypart and no phase variants: an item is an
        # object on a dark ground and does not change with the weather. That
        # keeps 81 items at 81 images rather than at 648.
        for item_id in sorted(load_items()):
            requests.append(ImageRequest(subject_id=item_id, kind="item", story=FLAGSHIP))

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
        which is exactly the ``items:`` block games/clockwork-dark/data/art/manifest.yaml wants.
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
        request = ImageRequest(subject_id=item_id, kind="item", story=FLAGSHIP)
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


# ---------------------------------------------------------------------------
# Any story: the plan is the story's own subjects.yaml
# ---------------------------------------------------------------------------

#: (manifest section, request kind, directory under the art root). The
#: directories are the ones scripts/art_missing.py has always briefed.
SECTIONS = (
    ("locations", "location", "scenes"),
    ("portraits", "portrait", "portraits"),
    ("items", "item", "items"),
)


@dataclass(frozen=True)
class Plate:
    """
    One picture a story's subjects declare, and where it would land.

    ``time_of_day`` is a daypart for a location whose subject declares
    ``times:``, and "" for a location that declares none (one plate, written as
    the manifest's ``base``), a portrait or an item.
    """

    kind: str
    subject_id: str
    time_of_day: str
    target: str
    resolved: bool

    @property
    def section(self) -> str:
        return next(section for section, kind, _ in SECTIONS if kind == self.kind)

    @property
    def slot(self) -> str:
        """The manifest key this plate is written under inside its entry."""
        if self.kind != "location":
            return ""
        return self.time_of_day or "base"

    def request(self) -> ImageRequest:
        # "dawn" is what the renderer defaults to, so a daypart-less plate
        # renders exactly the prompt art_missing.py has always shown for it.
        return ImageRequest(
            subject_id=self.subject_id, kind=self.kind, time_of_day=self.time_of_day or "dawn"
        )


def plan_plates() -> list[Plate]:
    """
    Every plate the ACTIVE story's ``subjects.yaml`` declares, in file order.

    ``resolved`` is the serving chain's own answer (``shipped.lookup``), so
    "missing" here means exactly "the player would see the procedural
    silhouette". A location entry with a ``base:`` therefore resolves every
    daypart -- the story chose one plate for all of them -- and one with only
    ``times:`` resolves only the dayparts it names. ``scripts/art_missing.py``
    briefs from this same function, so the brief and the generator cannot
    disagree about what is missing.

    No evil-phase doubling: phase variants are a runtime doom question, and a
    story's ``corrupted:`` pool stays hand-filled (The Wicked Garden declares a
    ``corruption:`` prompt clause and says in its manifest that a pool would be
    dead content).
    """
    from engine.media.art import load_subjects
    from engine.media.providers.shipped import lookup

    subjects = load_subjects()
    plates: list[Plate] = []
    for section, kind, directory in SECTIONS:
        for subject_id, entry in (subjects.get(section) or {}).items():
            if subject_id == "defaults":
                continue
            name = subject_id.replace("_", "-")
            dayparts: list[str] = [""]
            if kind == "location":
                dayparts = list((entry or {}).get("times") or {}) or [""]
            for daypart in dayparts:
                target = f"{directory}/{name}-{daypart}.jpg" if daypart else f"{directory}/{name}.jpg"
                request = ImageRequest(
                    subject_id=subject_id, kind=kind, time_of_day=daypart or "dawn"
                )
                plates.append(
                    Plate(kind, subject_id, daypart, target, lookup(request) is not None)
                )
    return plates


def parse_only(values: list[str]) -> list[tuple[str, str]]:
    """``["locations:tallow_docks,portraits"]`` -> ``[("location", "tallow_docks"), ("portrait", "")]``."""
    aliases = {}
    for section, kind, _ in SECTIONS:
        aliases[section] = aliases[kind] = kind
    selectors: list[tuple[str, str]] = []
    for value in values:
        for token in filter(None, (t.strip() for t in value.split(","))):
            head, _, subject = token.partition(":")
            if head not in aliases:
                raise ValueError(f"--only {token!r}: kind must be one of {', '.join(aliases)}")
            selectors.append((aliases[head], subject.strip()))
    return selectors


def select(
    plates: list[Plate],
    *,
    kinds: Optional[set[str]] = None,
    only: Optional[list[tuple[str, str]]] = None,
    dayparts: Optional[set[str]] = None,
    missing_only: bool = True,
) -> list[Plate]:
    """
    Narrow a plan. A selector naming a subject the story does not declare is
    an error, not an empty plan -- a typo must not report success.
    """
    declared = {(p.kind, p.subject_id) for p in plates}
    for kind, subject in only or []:
        if subject and (kind, subject) not in declared:
            raise ValueError(f"the story declares no {kind} subject {subject!r}")
    chosen = []
    for plate in plates:
        if kinds and plate.kind not in kinds:
            continue
        if only and not any(
            plate.kind == kind and (not subject or plate.subject_id == subject)
            for kind, subject in only
        ):
            continue
        if dayparts and plate.kind == "location" and plate.time_of_day not in dayparts:
            continue
        if missing_only and plate.resolved:
            continue
        chosen.append(plate)
    return chosen


class _UniqueKeyLoader(yaml.SafeLoader):
    """``yaml.SafeLoader`` that refuses a mapping holding the same key twice.

    PyYAML keeps the LAST of two equal keys without a word. The manifest editor
    finds an entry by its bare key, so a quoted key it missed (``"npc_brask":``)
    got a second, bare entry appended -- and a plain re-parse saw only the new
    value and passed. Read through this, the collision is an error.
    """


def _construct_unique_mapping(loader: yaml.SafeLoader, node: yaml.MappingNode,
                              deep: bool = False) -> dict[Any, Any]:
    loader.flatten_mapping(node)
    seen: set[Any] = set()
    for key_node, _value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in seen:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping", node.start_mark,
                f"found duplicate key {key!r}", key_node.start_mark,
            )
        seen.add(key)
    return loader.construct_mapping(node, deep=deep)


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_unique_mapping
)


def _parse_manifest(text: str, what: str) -> Any:
    """The manifest as data, or a ValueError the CLI reports without a traceback."""
    try:
        return yaml.load(text, Loader=_UniqueKeyLoader) or {}  # noqa: S506 -- a SafeLoader
    except yaml.YAMLError as exc:
        raise ValueError(f"{what}: {exc}") from None


def merge_manifest_text(text: str, entries: list[tuple[str, str, str, str]]) -> str:
    """
    Add plates to a manifest's text, keeping every line outside the entries it
    changes.

    Args:
        text: The manifest as it stands.
        entries: ``(section, subject_id, slot, relative path)``; ``slot`` is a
            daypart (-> ``times.<daypart>``), ``"base"``, or "" for a portrait
            or item.

    WHY TEXT AND NOT A YAML ROUND TRIP. A story's manifest is mostly comments --
    the Garden's explains where every plate came from and why some were not
    imported -- and ``yaml.safe_dump`` would drop all of them. ruamel.yaml keeps
    comments but is not a dependency of this repo, and one operator tool is not
    a reason to add one. So only the lines of an entry that changes are
    rewritten (a new entry is appended to the end of its section, a new section
    to the end of the file): comments OUTSIDE the changed entries survive, and
    a comment inside an entry that is rewritten is dropped with it. The result
    is re-parsed -- refusing a duplicate key, so a quoted key the entry finder
    missed cannot hide behind a new bare one -- and compared with the intended
    data before anything is returned: a manifest this cannot edit safely, or
    cannot read, raises ValueError instead of being written wrong.
    """
    text = text if text.endswith("\n") or not text else text + "\n"
    merged = copy.deepcopy(_parse_manifest(text, "the manifest is not valid YAML"))
    if not isinstance(merged, dict):
        raise ValueError("the manifest is not a YAML mapping")
    touched: dict[str, list[str]] = {}
    for section, subject_id, slot, relative in entries:
        block = merged.get(section)
        if not isinstance(block, dict):
            block = merged[section] = {}
        if section == "locations":
            entry = block.get(subject_id)
            entry = dict(entry) if isinstance(entry, dict) else {}
            if slot == "base":
                entry["base"] = relative
            else:
                times = entry.get("times")
                times = dict(times) if isinstance(times, dict) else {}
                times[slot] = relative
                entry["times"] = times
            block[subject_id] = entry
        else:
            block[subject_id] = relative
        touched.setdefault(section, [])
        if subject_id not in touched[section]:
            touched[section].append(subject_id)

    lines = text.splitlines(keepends=True)
    for section, subject_ids in touched.items():
        lines = _rewrite_section(lines, section, subject_ids, merged[section])
    out = "".join(lines)
    if _parse_manifest(out, "could not update the manifest safely") != merged:
        raise ValueError("could not update the manifest without changing other entries")
    return out


def _dump_entry(subject_id: str, value: Any, indent: int) -> list[str]:
    body = yaml.safe_dump(
        {subject_id: value}, sort_keys=False, default_flow_style=False, allow_unicode=True
    )
    return [" " * indent + line + "\n" for line in body.splitlines()]


def _indent_of(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _is_content(line: str) -> bool:
    stripped = line.strip()
    return bool(stripped) and not stripped.startswith("#")


def _rewrite_section(
    lines: list[str], section: str, subject_ids: list[str], block: dict[str, Any]
) -> list[str]:
    header = re.compile(rf"^{re.escape(section)}:(.*)$")
    at = next((i for i, line in enumerate(lines) if header.match(line.rstrip("\r\n"))), None)

    if at is None:
        added = [line for sid in subject_ids for line in _dump_entry(sid, block[sid], 2)]
        return [*lines, "\n", f"{section}:\n", *added]

    inline = header.match(lines[at].rstrip("\r\n")).group(1).split("#", 1)[0].strip()
    if inline:
        # `locations: {}` or a flow mapping: the section becomes a block.
        rebuilt = [line for sid in block for line in _dump_entry(sid, block[sid], 2)]
        return [*lines[:at], f"{section}:\n", *rebuilt, *lines[at + 1:]]

    # A block section runs until the next top-level key.
    last = at
    indent = 0
    end = at + 1
    while end < len(lines):
        line = lines[end]
        if _is_content(line) and _indent_of(line) == 0:
            break
        if _is_content(line):
            last = end
            indent = indent or _indent_of(line)
        end += 1
    indent = indent or 2

    for sid in subject_ids:
        key = re.compile(rf"^ {{{indent}}}{re.escape(sid)}:(\s|$)")
        start = next((i for i in range(at + 1, last + 1) if key.match(lines[i])), None)
        new = _dump_entry(sid, block[sid], indent)
        if start is None:
            lines = [*lines[: last + 1], *new, *lines[last + 1:]]
            last += len(new)
            continue
        stop = start
        for i in range(start + 1, last + 1):
            if _is_content(lines[i]) and _indent_of(lines[i]) <= indent:
                break
            if _is_content(lines[i]):
                stop = i
        lines = [*lines[:start], *new, *lines[stop + 1:]]
        last += len(new) - (stop + 1 - start)
    return lines


def _save_plate(source: Path, target: Path, kind: str) -> None:
    """
    Write a cached plate into the pack: JPEG at the story's declared size.

    ``formats:`` is what the live providers size requests from and what
    ``tests/test_story_art.py`` holds a shipped pack to, so a promoted plate is
    fitted (centre crop, then resample) to it rather than kept at whatever the
    backend returned. Without Pillow it is a straight copy, as in
    ``promote_items``: a large picture beats no picture.
    """
    from engine.media.art import format_for

    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        from PIL import Image, ImageOps
    except ImportError:
        target.write_bytes(source.read_bytes())
        return
    spec = format_for(kind)
    with Image.open(source) as image:
        fitted = ImageOps.fit(image.convert("RGB"), (int(spec["width"]), int(spec["height"])))
        fitted.save(target, "JPEG", quality=88, optimize=True)


def promote_plates(plates: list[Plate], *, dry_run: bool = False) -> list[Plate]:
    """
    Copy each plate's cached image under the active story's art root and add
    it to the story's manifest. Plates with nothing in the cache are skipped.

    The manifest text is computed BEFORE any file is written, so a manifest
    ``merge_manifest_text`` refuses to edit leaves the pack untouched.
    """
    from engine.config import get_config
    from engine.media.providers.shipped import reset_manifest_cache

    try:
        import PIL  # noqa: F401
        suffix: Optional[str] = ".jpg"
    except ImportError:
        suffix = None

    root = get_config().resolve_path("paths.art_root")
    manifest_path = get_config().resolve_path("paths.art_manifest")
    if root is None or manifest_path is None:
        raise ValueError("the story declares no paths.art_root / paths.art_manifest")

    work: list[tuple[Plate, Path, Path]] = []
    home = root.resolve()
    for plate in plates:
        hit = cached_image(plate.request())
        if hit is None or not hit.path:
            continue
        source = Path(hit.path)
        target = plate.target if suffix else str(Path(plate.target).with_suffix(source.suffix))
        destination = root / target
        # A subject id is a file name here; one carrying `..` or a separator
        # must not write outside the pack. Checked for every plate before any
        # file is written.
        if not destination.resolve().is_relative_to(home):
            raise ValueError(
                f"{plate.kind} {plate.subject_id!r} would be written to {target!r}, "
                "outside the story's art root"
            )
        work.append((Plate(plate.kind, plate.subject_id, plate.time_of_day, target, True),
                     source, destination))

    if not work or dry_run:
        return [plate for plate, _, _ in work]

    raw = manifest_path.read_bytes() if manifest_path.exists() else b""
    crlf = b"\r\n" in raw
    text = raw.decode("utf-8").replace("\r\n", "\n")
    updated = merge_manifest_text(
        text, [(p.section, p.subject_id, p.slot, p.target) for p, _, _ in work]
    )
    for plate, source, target in work:
        _save_plate(source, target, plate.kind)
    if crlf:
        updated = updated.replace("\n", "\r\n")
    manifest_path.write_bytes(updated.encode("utf-8"))
    reset_manifest_cache()
    return [plate for plate, _, _ in work]


def activate_story(slug: str) -> Any:
    """Activate ``slug`` unless it is already the running story."""
    current = registry.peek()
    if current is not None and current.slug == slug:
        return current
    return registry.activate(slug)


def _generate(todo: list[ImageRequest], name: str, label: Any) -> int:
    """Run a provider over ``todo``. Blocks for minutes per image, by design."""
    provider = build_provider(name)
    if provider is None or not provider.available():
        print(f"provider {name!r} is not available", file=sys.stderr)
        return 2

    print(f"generating {len(todo)} with {name} — this is slow by design; leave it running\n")

    started = time.perf_counter()
    for index, request in enumerate(todo, 1):
        print(f"  [{index}/{len(todo)}] {label(request)} ... ", end="", flush=True)
        began = time.perf_counter()
        result = provider.generate(request)
        elapsed = time.perf_counter() - began
        print(f"{result.status} in {elapsed:.0f}s" + (f" — {result.detail}" if result.detail else ""))

    print(f"\ndone in {(time.perf_counter() - started) / 60:.1f} min")
    return 0


def _provider_name(args: argparse.Namespace) -> str:
    from engine.config import get_config

    return args.provider or str(get_config().get("media.image_provider", "grokbuild"))


def story_main(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    """``--game <slug>`` for any story but the flagship."""
    if args.game not in registry.discover():
        parser.error(f"no such game {args.game!r}; installed: {', '.join(sorted(registry.discover()))}")
    activate_story(args.game)

    kinds = {kind for (section, kind, _) in SECTIONS if args.all or getattr(args, section)}
    try:
        only = parse_only(args.only or [])
        dayparts = {d.strip() for d in (args.dayparts or "").split(",") if d.strip()}
        plates = select(
            plan_plates(), kinds=kinds, only=only, dayparts=dayparts, missing_only=args.missing
        )
    except ValueError as exc:
        parser.error(str(exc))

    if args.promote:
        try:
            promoted = promote_plates(plates, dry_run=args.dry_run)
        except ValueError as exc:
            parser.error(str(exc))
        verb = "would promote" if args.dry_run else "promoted"
        print(f"{verb} {len(promoted)} plates into {args.game}'s pack\n")
        for plate in promoted:
            print(f"  {plate.kind:9} {plate.subject_id:24} {plate.time_of_day or '-':5} {plate.target}")
        return 0

    if args.prompts:
        print_prompts([plate.request() for plate in plates])
        return 0

    cached = {plate for plate in plates if cached_image(plate.request())}
    print(f"{args.game}: {len(plates)} plates planned, {len(cached)} already generated "
          f"(waiting for --promote)")
    if args.dry_run or args.list:
        for plate in plates:
            state = "cached" if plate in cached else ("resolved" if plate.resolved else "missing")
            print(f"  plan: {plate.kind:9} {plate.subject_id:24} {plate.time_of_day or '-':5} "
                  f"{plate.target:40} {state}")
        return 0

    todo = [plate.request() for plate in plates if plate not in cached]
    todo = todo[: args.limit] if args.limit else todo
    if not todo:
        print("nothing to generate")
        return 0
    code = _generate(todo, _provider_name(args), lambda r: f"{r.kind} {r.subject_id} ({r.time_of_day})")
    if code == 0:
        print(f"then: scripts/generate_art.py --game {args.game} --promote")
    return code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pre-generate a story's art")
    parser.add_argument(
        "--game",
        default=registry.DEFAULT_SLUG,
        help=(
            "Story slug (default: the flagship, whose plan is unchanged). Any "
            "other story is planned from its own paths.art_subjects."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List each plate (kind, subject, daypart, target) and write nothing",
    )
    parser.add_argument(
        "--only",
        action="append",
        metavar="KIND[:ID]",
        help="Only these, e.g. --only locations:tallow_docks or --only portraits (repeatable)",
    )
    parser.add_argument(
        "--dayparts",
        default="",
        help="Only these location dayparts, comma-separated (e.g. day,night)",
    )
    parser.add_argument(
        "--missing",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Skip plates the manifest already resolves (default on)",
    )
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
            "Flagship: copy generated item plates from the disposable cache into the "
            "shipped pack and print the games/clockwork-dark/data/art/manifest.yaml items: block. "
            "--game <slug>: copy every generated plate under the story's paths.art_root "
            "and write it into its paths.art_manifest"
        ),
    )
    parser.add_argument("--list", action="store_true", help="Report gaps and exit")
    parser.add_argument("--provider", default=None, help="grokbuild | comfyui | procedural")
    parser.add_argument("--limit", type=int, default=0, help="Stop after N images")
    args = parser.parse_args(argv)

    if args.game != registry.DEFAULT_SLUG:
        return story_main(args, parser)

    # ---- The flagship: the plan it always had. -------------------------------
    # Nothing below activates a story, and without one of the new flags every
    # line printed is the line v0.12 printed (tests/test_generate_art_cli.py).
    if args.promote:
        promoted = promote_items(dry_run=args.dry_run)
        if args.dry_run:
            print(f"would promote {len(promoted)} item plates into the shipped pack "
                  "(dry run: promoted nothing)\n")
        else:
            print(f"promoted {len(promoted)} item plates into the shipped pack\n")
        for item_id, relative in promoted:
            print(f"  {item_id}: {relative}")
        return 0

    try:
        only = parse_only(args.only or [])
    except ValueError as exc:
        parser.error(str(exc))
    only_kinds = {kind for kind, _ in only}

    kinds = set()
    if args.all or args.locations or "location" in only_kinds:
        kinds.add("locations")
    if args.all or args.portraits or "portrait" in only_kinds:
        kinds.add("portraits")
    if args.all or args.items or "item" in only_kinds:
        kinds.add("items")
    if not kinds:
        parser.print_help()
        return 1

    requests = wanted(kinds)
    if only:
        requests = [
            r for r in requests
            if any(r.kind == kind and (not sid or r.subject_id == sid) for kind, sid in only)
        ]
    dayparts = {d.strip() for d in (args.dayparts or "").split(",") if d.strip()}
    if dayparts:
        requests = [r for r in requests if r.kind != "location" or r.time_of_day in dayparts]
    gaps = missing(requests) if args.missing else list(requests)

    if args.prompts:
        print_prompts(gaps if args.missing_only else requests)
        return 0

    print(f"{len(requests)} possible images, {len(requests) - len(gaps)} already covered, "
          f"{len(gaps)} missing")
    if args.dry_run:
        # The flagship's generation target is the cache; --promote moves items on.
        from engine.media.providers.base import IMAGE_DIR as cache  # noqa: PLC0415

        for request in gaps:
            print(f"  plan: {request.kind:9} {request.subject_id:22} {request.time_of_day:5} "
                  f"{request.evil_phase:9} {(cache / (request.cache_key() + '.png')).as_posix()}")
        return 0
    if args.list or not gaps:
        for request in gaps[:200]:
            print(f"  missing: {request.kind:9} {request.subject_id:22} "
                  f"{request.time_of_day:5} {request.evil_phase}")
        return 0

    todo = gaps[: args.limit] if args.limit else gaps
    return _generate(
        todo,
        _provider_name(args),
        lambda r: f"{r.subject_id} ({r.time_of_day}/{r.evil_phase})",
    )

if __name__ == "__main__":
    raise SystemExit(main())
