"""
Missing-plate brief — The Wicked Garden
=======================================

Writes ``games/wicked-garden/data/art/MISSING-PLATES.md``: every subject
declared in ``subjects.yaml`` with no image in the shipped pack, with a
ready-to-paste prompt in both dialects and the manifest lines to add once the
files land.

    .\\.venv\\Scripts\\python.exe scripts\\art_missing.py

WHY THIS IS GENERATED RATHER THAN WRITTEN. The prompts come from
``engine.media.art.render_prose`` / ``render_tags`` -- the same two functions the
live Grok and ComfyUI providers call. A hand-written brief is a fourth copy of
the story's art voice, free to drift from the three that ship, and the drift
would only show up as plates that do not match the pack. Re-run this after
editing ``subjects.yaml`` rather than editing the markdown.

Sizes come from ``subjects.yaml``'s ``formats:`` block, the same one the
providers size live requests from, so a hand generation and a pipeline
generation land the same shape.

Version: v0.1.0 [2026-08-09]
"""

from __future__ import annotations

import pathlib
import sys

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from engine.games.registry import activate  # noqa: E402

activate("wicked-garden")

from engine.config import get_config  # noqa: E402
from engine.media.art import format_for, lora_hints, render_prose, render_tags  # noqa: E402

ROOT = pathlib.Path(".")
ART = ROOT / "games" / "wicked-garden" / "data" / "art"
OUT = ART / "MISSING-PLATES.md"

subjects = yaml.safe_load((ART / "subjects.yaml").read_text(encoding="utf-8"))
manifest = yaml.safe_load((ART / "manifest.yaml").read_text(encoding="utf-8"))

#: Read from `subjects.yaml`'s `formats:`, which is what the live providers size
#: their requests from -- so the brief and a live generation cannot disagree.
#: That block used to be a verbatim copy of the flagship's and described a
#: different pack; `tests/test_story_art.py` now holds it to the files on disk.
DIMS = {
    kind: f"{format_for(kind)['width']}x{format_for(kind)['height']}"
    for kind in ("location", "portrait", "item")
}
DIRS = {"location": "scenes", "portrait": "portraits", "item": "items"}
TIMES = ["dawn", "day", "dusk", "night"]

KINDS = [("locations", "location"), ("portraits", "portrait"), ("items", "item")]

#: Places the shared style block fights the subject. It is appended to every
#: prompt and it is written for the Garden -- so on the two subjects that are
#: deliberately NOT the Garden it argues against the thing being drawn. Called
#: out per subject rather than special-cased in `subjects.yaml`, because the
#: block is correct for the twelve locations that are the Garden and the fix is
#: a hand edit at generation time, not a second style.
NOTES = {
    "mortal_threshold": (
        "Renders under the **`mortal`** style variant, not the house style — a drab "
        "modern flat has to read as the opposite of the Garden, and that contrast is "
        "the opening screen's job. So the prompt below carries no vines, petals or "
        "botanical art nouveau, and pushes against them in the negative, because the "
        "LoRA stack it still loads is called `Botanical_Fantasy`. The one flower that "
        "belongs here is in the **night** alt, through the floorboards, and nowhere else."
    ),
    "unknown": (
        "The fallback plate for any location with no art of its own, which is why it "
        "reads as a void. Generating this one first is the cheapest way to stop the "
        "procedural silhouette appearing anywhere — it covers the other five until "
        "they exist. Also on the **`mortal`** variant: this place is defined by having "
        "no botany in it yet."
    ),
    "court_generic": (
        "A crowd plate, used wherever a named courtier is not on screen. Faces at "
        "mid-distance rather than a hero portrait, so it can sit behind dialogue "
        "without any one figure claiming to be somebody."
    ),
}


def slug(subject_id: str) -> str:
    return subject_id.replace("_", "-")


def block(subject_id: str, kind: str, time_of_day: str) -> list[str]:
    positive, negative = render_tags(subject_id, kind=kind, time_of_day=time_of_day)
    return [
        "**Grok Imagine** (prose)",
        "",
        "```text",
        render_prose(subject_id, kind=kind, time_of_day=time_of_day),
        "```",
        "",
        "**ComfyUI** (tags)",
        "",
        "```text",
        positive,
        "```",
        "",
        "```text",
        f"NEGATIVE: {negative}",
        "```",
        "",
    ]


lines: list[str] = [
    "# Missing plates — The Wicked Garden",
    "",
    "Eight subjects are authored in `subjects.yaml` and have no image in",
    "`plates/`, so each falls through the resolution chain to the procedural",
    "silhouette. One of them is `mortal_threshold`, the entry location, which is",
    "why a new run opens on a placeholder.",
    "",
    "**Generated, not written.** Every prompt below is the output of",
    "`engine.media.art.render_prose` / `render_tags` against the shipped",
    "`subjects.yaml`, so it is exactly what the live pipeline would send — not a",
    "fourth copy of the art voice free to drift from the three that ship. After",
    "editing a subject, re-run the generator rather than editing the prompts here:",
    "",
    "```powershell",
    ".\\.venv\\Scripts\\python.exe scripts\\art_missing.py",
    "```",
    "",
    "## Order to work in",
    "",
    "1. **`unknown`** — the fallback plate. One image and the procedural silhouette",
    "   stops appearing anywhere, including for the five locations below it.",
    "2. **`mortal_threshold`** — the entry location, so this is the first screen of",
    "   every new run.",
    "3. The rest, in any order. Each one only shows up if the player goes there.",
    "",
    "## Sizes",
    "",
    "| Kind | Size | Directory |",
    "| --- | --- | --- |",
    "| location | 1280x720 | `plates/scenes/` |",
    "| portrait | 768x1024 | `plates/portraits/` |",
    "| item | 768x1024 | `plates/items/` |",
    "",
    "Read from `subjects.yaml`'s `formats:` block, which is also what the live Grok",
    "and ComfyUI providers size their requests from — so generating by hand and",
    "generating through the pipeline land the same shape. `tests/test_story_art.py`",
    "holds that block to the plates actually on disk. JPEG, same as the rest.",
    "",
    "## After the files land",
    "",
    "Add each to `manifest.yaml` under its kind. Locations take",
    "`{base: ..., alts: [...]}`; portraits and items take a bare path. Paths are",
    "relative to `paths.art_root`. The ready-to-paste block is at the bottom.",
    "",
    "---",
    "",
]

pastable: dict[str, list[str]] = {"locations": [], "portraits": [], "items": []}

for section, kind in KINDS:
    have = set(manifest.get(section) or {})
    want = [k for k in (subjects.get(section) or {}) if k != "defaults"]
    missing = [k for k in want if k not in have]
    if not missing:
        continue

    lines += [f"## {section.capitalize()} ({len(missing)})", ""]
    for subject_id in missing:
        name = slug(subject_id)
        target = f"{DIRS[kind]}/{name}.jpg"
        lines += [
            f"### `{subject_id}`",
            "",
            f"- **File:** `{target}`",
            f"- **Size:** {DIMS[kind]}",
            "",
        ]
        if subject_id in NOTES:
            lines += [NOTES[subject_id], ""]

        if kind == "location":
            # The renderer defaults to dawn, so dawn is the base plate. The
            # other three are real authored variants -- mortal_threshold's night
            # has a rose coming up through the floorboards -- and worth having,
            # but the game is complete without them.
            lines += ["#### Base — dawn", ""]
            lines += block(subject_id, kind, "dawn")
            alts = []
            for time_of_day in TIMES[1:]:
                lines += [f"<details><summary>Alt — {time_of_day}"
                          f" (`{DIRS[kind]}/{name}-{time_of_day}.jpg`)</summary>", ""]
                lines += block(subject_id, kind, time_of_day)
                lines += ["</details>", ""]
                alts.append(f"{DIRS[kind]}/{name}-{time_of_day}.jpg")
            pastable["locations"].append(
                f"  {subject_id}:\n"
                f"    base: {target}\n"
                f"    alts: []   # optional: {', '.join(alts)}"
            )
        else:
            lines += block(subject_id, kind, "dawn")
            pastable[section].append(f"  {subject_id}: {target}")

        lines += ["---", ""]

hints = lora_hints()
if hints:
    lines += [
        "## LoRA hints",
        "",
        "From `subjects.yaml` `style.loras`. ComfyUI only; Grok ignores them.",
        "",
        "```yaml",
        yaml.safe_dump(hints, sort_keys=False).rstrip(),
        "```",
        "",
    ]

lines += ["## Manifest block to paste", "", "```yaml"]
for section in ("locations", "portraits", "items"):
    if pastable[section]:
        lines += [f"{section}:", *pastable[section]]
lines += ["```", ""]

OUT.write_text("\n".join(lines), encoding="utf-8")
print(f"wrote {OUT} ({len(lines)} lines)")
print("subjects covered:", sum(len(v) for v in pastable.values()))
