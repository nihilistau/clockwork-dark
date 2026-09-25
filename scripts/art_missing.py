"""
Missing-plate brief — for any story
===================================

Writes ``<story>/data/art/MISSING-PLATES.md``: every subject declared in that
story's ``subjects.yaml`` with no image in its shipped pack, with a
ready-to-paste prompt in both dialects and the manifest lines to add once the
files land.

    .\\.venv\\Scripts\\python.exe scripts\\art_missing.py --game wicked-garden
    .\\.venv\\Scripts\\python.exe scripts\\art_missing.py --game dev-story

WHY THIS TAKES A SLUG. It used to `activate("wicked-garden")` and hardcode that
story's directory -- written for one story on the day that story needed it,
which is the same shape as every other flagship-shaped default this repo has
been pulling out of the engine. A tool that can only brief one story is a tool
the second story quietly does without. The default is the ACTIVE game, so
running it with no argument still does the obvious thing.

WHY THIS IS GENERATED RATHER THAN WRITTEN. The prompts come from
``engine.media.art.render_prose`` / ``render_tags`` -- the same two functions the
live Grok and ComfyUI providers call. A hand-written brief is another copy of
the story's art voice, free to drift from the ones that ship, and the drift
would only show up as plates that do not match the pack. Re-run this after
editing ``subjects.yaml`` rather than editing the markdown.

Sizes come from ``subjects.yaml``'s ``formats:`` block, the same one the
providers size live requests from, so a hand generation and a pipeline
generation land the same shape.

WHAT COUNTS AS MISSING, AND WHERE A PLATE GOES, is
``scripts/generate_art.py::plan_plates`` -- the function the generator plans
from -- so this brief and ``generate_art.py --game <slug> --dry-run`` list the
same plates at the same paths. It used to count a subject as present the moment
its id appeared in the manifest, whether or not the file existed, and to name
the dawn plate ``scenes/<id>.jpg`` where the generator writes
``scenes/<id>-dawn.jpg``: two views of one pack that drifted the first time a
plate was promoted.

    --out PATH    write the brief somewhere other than the story's art dir

Version: v0.3.0 [2026-09-25]
"""

from __future__ import annotations

import argparse
import pathlib
import sys

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from engine.games.registry import discover, resolve_slug  # noqa: E402
from scripts.generate_art import activate_story, plan_plates  # noqa: E402

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument(
    "--game",
    default="",
    help="Story slug. Defaults to the active game (config `game.default`).",
)
parser.add_argument(
    "--out",
    default="",
    help="Where to write the brief (default: <story>/data/art/MISSING-PLATES.md).",
)
args = parser.parse_args()

SLUG = args.game or resolve_slug()
if SLUG not in discover():
    parser.error(f"no such game '{SLUG}'. Installed: {', '.join(sorted(discover()))}")
manifest_obj = activate_story(SLUG)

from engine.config import get_config  # noqa: E402
from engine.media.art import format_for, lora_hints, render_prose, render_tags  # noqa: E402

ROOT = pathlib.Path(".")

# The story's OWN art directory, taken from its manifest rather than assembled
# from the slug. A story is free to keep its pack somewhere else, and
# `paths.art_subjects` is the one place that is already true.
ART = pathlib.Path(str(get_config().get("paths.art_subjects", ""))).parent
if not ART.is_dir():
    parser.error(f"'{SLUG}' declares no readable paths.art_subjects (looked in {ART})")
OUT = pathlib.Path(args.out) if args.out else ART / "MISSING-PLATES.md"

subjects = yaml.safe_load((ART / "subjects.yaml").read_text(encoding="utf-8"))

#: Read from `subjects.yaml`'s `formats:`, which is what the live providers size
#: their requests from -- so the brief and a live generation cannot disagree.
#: That block used to be a verbatim copy of the flagship's and described a
#: different pack; `tests/test_story_art.py` now holds it to the files on disk.
DIMS = {
    kind: f"{format_for(kind)['width']}x{format_for(kind)['height']}"
    for kind in ("location", "portrait", "item")
}
DIRS = {"location": "scenes", "portrait": "portraits", "item": "items"}
KINDS = [("locations", "location"), ("portraits", "portrait"), ("items", "item")]

#: The generator's own plan, narrowed to what the serving chain cannot answer.
GAPS = [plate for plate in plan_plates() if not plate.resolved]

#: Per-subject warnings, KEYED BY STORY.
#:
#: These were a flat dict when this script served one story, so running it
#: against a second one printed The Wicked Garden's notes over another story's
#: subjects the moment an id collided -- the same defect this repo spent a night
#: pulling out of the engine, reproduced in a tool written to describe it.
#:
#: A note here is about a specific story's art direction, so it is that story's
#: to carry. An unlisted story gets none, which is correct: there is nothing
#: generic to say about a subject nobody has looked at yet.
NOTES_BY_STORY: dict[str, dict[str, str]] = {}
NOTES_BY_STORY["wicked-garden"] = {
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

NOTES = NOTES_BY_STORY.get(SLUG, {})


def _order_section(missing_ids: set[str]) -> list[str]:
    """
    "Do these first", derived from THIS story rather than written for one.

    The old version named `unknown` and `mortal_threshold` in prose, which are
    The Wicked Garden's subjects -- so every other story was told to generate
    two ids it does not have. What generalises is the reasoning, not the ids:
    a fallback plate covers every gap at once, and the entry location is the
    first screen of every run. Both are lookups.
    """
    lines = ["## Order to work in", ""]
    step = 1

    # A subject literally named `unknown` is the engine's fallback for a place
    # with no art of its own, so one image silences every silhouette at once.
    if "unknown" in missing_ids:
        lines += [
            f"{step}. **`unknown`** — the fallback plate. One image and the procedural",
            "   silhouette stops appearing for every location that has none of its own.",
        ]
        step += 1

    entry = manifest_obj.entry_location
    if entry and entry in missing_ids:
        lines += [
            f"{step}. **`{entry}`** — the entry location, so this is the first screen of",
            "   every new run.",
        ]
        step += 1

    if step == 1:
        # Nothing about this story earns a "do this first", and a numbered list
        # of one item reads like the other items went missing.
        return lines + [
            "Any order. None of these is a fallback plate or the entry location, so",
            "each one only shows up if the player goes there.",
        ]

    lines += [
        f"{step}. The rest, in any order. Each one only shows up if the player goes there."
    ]
    return lines


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


# Which subjects have no plate, computed BEFORE the prose so the prose can be
# about this story rather than about the one this script was written for. The
# header used to hardcode "Eight subjects" and name the Garden's entry location.
_MISSING: set[str] = {plate.subject_id for plate in GAPS}

_ORDER_SECTION = _order_section(_MISSING)
_entry = manifest_obj.entry_location

lines: list[str] = [
    f"# Missing plates — {manifest_obj.title}",
    "",
    f"{len(_MISSING)} subject(s) are authored in `subjects.yaml` and have no image in",
    "`plates/`, so each falls through the resolution chain to the procedural",
    "silhouette.",
    *(
        [
            f"One of them is `{_entry}`, the entry location, which is why a new run",
            "opens on a placeholder.",
        ]
        if _entry in _MISSING
        else []
    ),
    "",
    "**Generated, not written.** Every prompt below is the output of",
    "`engine.media.art.render_prose` / `render_tags` against the shipped",
    "`subjects.yaml`, so it is exactly what the live pipeline would send — not a",
    "fourth copy of the art voice free to drift from the three that ship. After",
    "editing a subject, re-run the generator rather than editing the prompts here:",
    "",
    "```powershell",
    # WITH the slug. Without it this re-runs against the DEFAULT game, so the
    # brief was telling a reader to overwrite a different story's file.
    f".\\.venv\\Scripts\\python.exe scripts\\art_missing.py --game {SLUG}",
    "```",
    "",
    *_ORDER_SECTION,
    "",
    "## Sizes",
    "",
    "| Kind | Size | Directory |",
    "| --- | --- | --- |",
    # From DIMS, not typed: this table used to say 1280x720 for every story,
    # under a sentence claiming it was read from `formats:`.
    *(f"| {kind} | {DIMS[kind]} | `{DIRS[kind]}/` under `paths.art_root` |"
      for kind in ("location", "portrait", "item")),
    "",
    "Read from `subjects.yaml`'s `formats:` block, which is also what the live Grok",
    "and ComfyUI providers size their requests from — so generating by hand and",
    "generating through the pipeline land the same shape. `tests/test_story_art.py`",
    "holds that block to the plates actually on disk. JPEG, same as the rest.",
    "",
    "## After the files land",
    "",
    "`scripts/generate_art.py --game " + SLUG + " --promote` writes each plate the",
    "generator made into `manifest.yaml` itself. For a plate made by hand, add it",
    "under its kind: a location's plates go under `times: {<daypart>: ...}` (or",
    "`base:` for a location whose subject declares no `times:` -- note that a",
    "`base:` then answers every daypart); portraits and items take a bare path.",
    "Paths are relative to `paths.art_root`. The ready-to-paste block is at the",
    "bottom.",
    "",
    "---",
    "",
]

pastable: dict[str, list[str]] = {"locations": [], "portraits": [], "items": []}

for section, kind in KINDS:
    gaps = [plate for plate in GAPS if plate.kind == kind]
    if not gaps:
        continue
    by_subject: dict[str, list] = {}
    for plate in gaps:
        by_subject.setdefault(plate.subject_id, []).append(plate)

    lines += [f"## {section.capitalize()} ({len(by_subject)})", ""]
    for subject_id, plates in by_subject.items():
        lines += [f"### `{subject_id}`", ""]
        if kind != "location":
            lines += [f"- **File:** `{plates[0].target}`", f"- **Size:** {DIMS[kind]}", ""]
        else:
            lines += [f"- **Size:** {DIMS[kind]}", ""]
        if subject_id in NOTES:
            lines += [NOTES[subject_id], ""]

        if kind != "location":
            lines += block(subject_id, kind, "dawn")
            pastable[section].append(f"  {subject_id}: {plates[0].target}")
            lines += ["---", ""]
            continue

        # One plate per declared daypart the manifest cannot answer. The first
        # is open; the rest fold, because a brief of 76 open prompts is a wall.
        entry: list[str] = [f"  {subject_id}:"]
        times = [p for p in plates if p.time_of_day]
        for index, plate in enumerate(plates):
            label = plate.time_of_day or "base"
            request = plate.request()
            if index:
                lines += [f"<details><summary>{label} (`{plate.target}`)</summary>", ""]
            else:
                lines += [f"#### {label}", ""]
            lines += [f"- **File:** `{plate.target}`", ""]
            lines += block(subject_id, kind, request.time_of_day)
            if index:
                lines += ["</details>", ""]
        if times:
            entry.append("    times:")
            entry += [f"      {p.time_of_day}: {p.target}" for p in times]
        for plate in plates:
            if not plate.time_of_day:
                entry.append(f"    base: {plate.target}")
        pastable["locations"] += entry

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
print(f"subjects covered: {len(_MISSING)} ({len(GAPS)} plates)")
