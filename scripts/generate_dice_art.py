"""
Fill the gaps in the d20 face pack.

WHY THIS IS ITS OWN SCRIPT. `scripts/generate_art.py` generates through the
provider chain, and every provider writes into the disk CACHE
(``data/media/images/<hash>.png``) because that is where generated art belongs:
it is per-machine, gitignored, and rebuilt on demand. The dice faces are the
opposite kind of asset. They are UI furniture -- one plate per number, the same
twenty for every player, every save and every seed -- so they belong in the
SHIPPED pack next to the fourteen that were already there, under a name a human
can read.

The prompts are not duplicated here. Both dialects come out of the same place
as every other subject in the game:

    data/art/subjects.yaml  ->  engine/media/art.py
        render_prose(f"dice_face_{n}", kind="dice")   Grok Imagine  (default)
        render_tags (f"dice_face_{n}", kind="dice")   ComfyUI SDXL  (+negative)

    python scripts/generate_dice_art.py --list      what the pack is missing
    python scripts/generate_dice_art.py --prompts   both dialects, generate nothing
    python scripts/generate_dice_art.py            generate the missing faces
    python scripts/generate_dice_art.py --face 6 --force    redo one

ComfyUI is not driven from here. It is not running on this machine and its
client (engine/media/comfyui.py) submits a bare CLIPTextEncode node rather than
a real SDXL workflow, so a "generate with comfy" flag would be a promise this
script cannot keep. --prompts prints exactly what to paste into a workflow, and
the same strings are mirrored in data/procgen_templates/comfyui.yaml, which is
the file that client reads.

Version: v0.1.0 [2026-08-08]
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.media.art import format_for, render_prose, render_tags  # noqa: E402
from engine.media.providers.shipped import load_manifest  # noqa: E402

ART_ROOT = Path("content/scenes/clockwork/static/art")
SIDES = 20
DEFAULT_TIMEOUT = 900


def _numbered(block: str) -> dict[int, str]:
    raw = load_manifest().get(block, {}) or {}
    return {int(k): str(v) for k, v in raw.items()}


def face_map() -> dict[int, str]:
    """The manifest's number -> source plate map, as ints."""
    return _numbered("dice_plates")


def thumb_map() -> dict[int, str]:
    """The manifest's number -> interface face map, as ints."""
    return _numbered("dice_faces")


def gaps(faces: dict[int, str]) -> list[int]:
    """Faces with no file behind them, in roll order."""
    root = Path(__file__).resolve().parent.parent / ART_ROOT
    missing = []
    for number in range(1, SIDES + 1):
        relative = faces.get(number)
        if not relative or not (root / relative).is_file():
            missing.append(number)
    return missing


def destination(faces: dict[int, str], number: int) -> Path:
    """Where face `number` should land."""
    root = Path(__file__).resolve().parent.parent / ART_ROOT
    # The manifest is authoritative when it names a path -- regenerating a face
    # must overwrite the file the game actually loads, not a near-miss beside
    # it. Only a number the manifest has never heard of gets a fresh name.
    relative = faces.get(number) or f"dice/dice-{number}.jpg"
    return root / relative


def instruction(number: int, target: Path) -> str:
    """
    The headless Grok Build prompt.

    Phrased as an explicit single-tool instruction for the same reason
    engine/media/providers/grokbuild.py phrases it that way: the CLI is a full
    agent and, left vague, will reason, verify and iterate -- which costs
    minutes and extra generations nobody asked for.
    """
    spec = format_for("dice")
    prose = render_prose(f"dice_face_{number}", kind="dice")
    return (
        f"Call image_gen exactly once with aspect_ratio='{spec['aspect']}'.\n"
        f"Prompt: {prose}\n"
        f"Then save the result to '{target.as_posix()}' as JPEG. "
        f"Do not verify, iterate, or generate any variations. "
        f"Reply with the saved path only."
    )


def explain(completed: subprocess.CompletedProcess[bytes]) -> str:
    """Pull a usable reason out of the CLI's JSON envelope."""
    text = (completed.stdout or b"").decode("utf-8", "replace")
    try:
        payload = json.loads(text)
        return str(payload.get("text") or payload.get("error") or "no image produced")[:300]
    except json.JSONDecodeError:
        stderr = (completed.stderr or b"").decode("utf-8", "replace")
        return (stderr or text or "no image produced").strip()[:300]


def generate(number: int, target: Path, command: str, timeout: int) -> str:
    target.parent.mkdir(parents=True, exist_ok=True)
    root = Path(__file__).resolve().parent.parent
    argv = [
        command,
        "-p",
        instruction(number, target),
        "--permission-mode",
        "bypassPermissions",
        "--output-format",
        "json",
        "--cwd",
        str(root),
    ]
    try:
        completed = subprocess.run(argv, capture_output=True, timeout=timeout, cwd=str(root))
    except subprocess.TimeoutExpired:
        return f"failed — timed out after {timeout}s"
    except OSError as exc:
        return f"failed — {exc}"

    if not target.exists() or target.stat().st_size == 0:
        return f"failed — {explain(completed)}"
    return f"ready ({target.stat().st_size // 1024} KB)"


def build_thumbs(size: int, watermark_strip: float) -> int:
    """
    Derive the interface face set from the source plates.

    Two things happen here and both of them are about the image the PLAYER
    gets, not the one the painter made:

      1. The bottom strip comes off. Every plate Grok Imagine produces carries
         a provider watermark in its bottom-right corner, and the fourteen
         plates that shipped do not -- so without this the five new faces would
         be the only ones in the set with a signature on them. The die is
         centred in all twenty, so the strip costs nothing but the mark.
      2. It is squared and scaled to `size`. The toast paints a ~96px die.
    """
    try:
        from PIL import Image  # noqa: PLC0415 -- optional, like grokbuild.py's crop
    except ImportError:
        print("Pillow is not installed; `pip install Pillow` to build thumbs", file=sys.stderr)
        return 2

    root = Path(__file__).resolve().parent.parent / ART_ROOT
    plates, thumbs = face_map(), thumb_map()
    built = 0
    for number in range(1, SIDES + 1):
        source, target = plates.get(number), thumbs.get(number)
        if not source or not target:
            print(f"  face {number:2}: no mapping", file=sys.stderr)
            continue
        source_path, target_path = root / source, root / target
        if not source_path.is_file():
            print(f"  face {number:2}: missing plate {source}", file=sys.stderr)
            continue

        with Image.open(source_path) as image:
            image = image.convert("RGB")
            width, height = image.size
            keep = int(height * (1.0 - watermark_strip))
            side = min(width, keep)
            # Centre horizontally, top-anchored vertically: the strip we are
            # dropping is at the bottom, so anchoring there would put it back.
            left = (width - side) // 2
            face = image.crop((left, 0, left + side, side))
            face = face.resize((size, size), Image.LANCZOS)
            target_path.parent.mkdir(parents=True, exist_ok=True)
            face.save(target_path, "JPEG", quality=88, optimize=True)
        built += 1
        print(f"  face {number:2} -> {target} ({target_path.stat().st_size // 1024} KB)")

    print(f"\n{built}/{SIDES} faces built at {size}px")
    return 0 if built == SIDES else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate missing d20 face plates")
    parser.add_argument("--list", action="store_true", help="Report gaps and exit")
    parser.add_argument("--prompts", action="store_true", help="Print both dialects and exit")
    parser.add_argument("--face", type=int, action="append", help="Only this number (repeatable)")
    parser.add_argument("--force", action="store_true", help="Regenerate even if the file exists")
    parser.add_argument("--command", default="grok", help="Grok Build CLI executable")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    parser.add_argument(
        "--thumbs",
        action="store_true",
        help="Rebuild the interface face set from the source plates and exit",
    )
    parser.add_argument("--size", type=int, default=256, help="Thumb edge in px")
    parser.add_argument(
        "--watermark-strip",
        type=float,
        default=0.06,
        help="Fraction of the plate's height to drop off the bottom",
    )
    args = parser.parse_args(argv)

    faces = face_map()
    if not faces:
        print("data/art/manifest.yaml has no dice_plates: map", file=sys.stderr)
        return 2

    if args.thumbs:
        return build_thumbs(args.size, args.watermark_strip)

    todo = args.face or (list(range(1, SIDES + 1)) if args.force else gaps(faces))
    if args.face and not args.force:
        todo = [n for n in todo if n in gaps(faces)]

    if args.prompts:
        for number in args.face or range(1, SIDES + 1):
            positive, negative = render_tags(f"dice_face_{number}", kind="dice")
            print(f"\n=== d20 face {number}")
            print(f"  grok    : {render_prose(f'dice_face_{number}', kind='dice')}")
            print(f"  comfy + : {positive}")
            print(f"  comfy - : {negative}")
        return 0

    print(f"{SIDES} faces, {SIDES - len(gaps(faces))} on disk, {len(gaps(faces))} missing")
    if args.list or not todo:
        for number in gaps(faces):
            print(f"  missing: {number:2}  -> {destination(faces, number).name}")
        return 0

    command = shutil.which(args.command) or (
        args.command if Path(args.command).is_file() else None
    )
    if command is None:
        print(f"{args.command!r} is not on PATH — see --prompts", file=sys.stderr)
        return 2

    print(f"generating {len(todo)}: {todo} — two to three minutes each, leave it running\n")
    started = time.perf_counter()
    for index, number in enumerate(todo, 1):
        target = destination(faces, number)
        print(f"  [{index}/{len(todo)}] face {number:2} -> {target.name} ... ", end="", flush=True)
        began = time.perf_counter()
        status = generate(number, target, command, args.timeout)
        print(f"{status} in {time.perf_counter() - began:.0f}s")

    print(f"\ndone in {(time.perf_counter() - started) / 60:.1f} min")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
