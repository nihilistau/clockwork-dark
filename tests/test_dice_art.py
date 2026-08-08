"""
The d20 face pack, and the two places that have to agree about it.

WHY THIS EXISTS. `dice_result` carries no image url and
engine/media/providers/shipped.py has no ``kind == "dice"`` branch, so the
browser resolves the painted face itself from a path it builds in the story's
own DiceToast. That is a second copy of a mapping whose first copy
is data/art/manifest.yaml, and a second copy nobody checks is how this codebase
got a manifest entry pointing at ``things/mushrooms.png``, a file that never
existed.

Five faces (6, 8, 11, 16, 18) did not exist at all before this pack, so
"show the number that was rolled" was impossible for a quarter of the range and
nothing failed. It fails here now.
"""

from __future__ import annotations

import re
import struct
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
ART = ROOT / "content" / "scenes" / "clockwork" / "static" / "art"
MANIFEST = ROOT / "data" / "art" / "manifest.yaml"
SUBJECTS = ROOT / "data" / "art" / "subjects.yaml"
TOAST = (
    ROOT / "ui" / "src" / "stories" / "clockwork-dark" / "parts" / "DiceToast.jsx"
)
EFFECTS = ROOT / "ui" / "src" / "styles" / "effects.css"

SIDES = 20

# A UI face is a 256px square. The source plates are 350-800 KB each; pointing
# the interface map back at one would quietly put 12 MB of dice art on the wire.
MAX_FACE_BYTES = 64 * 1024


@pytest.fixture(scope="module")
def manifest() -> dict:
    return yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))


def _jpeg_size(path: Path) -> tuple[int, int]:
    """(width, height) of a JPEG, without pulling in Pillow."""
    data = path.read_bytes()
    index = 2
    while index < len(data):
        if data[index] != 0xFF:
            index += 1
            continue
        marker = data[index + 1]
        if marker in (0xC0, 0xC1, 0xC2, 0xC3):
            height, width = struct.unpack(">HH", data[index + 5 : index + 9])
            return width, height
        if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
            index += 2
            continue
        (length,) = struct.unpack(">H", data[index + 2 : index + 4])
        index += 2 + length
    raise AssertionError(f"no SOF marker in {path}")


def test_every_face_of_the_die_has_a_plate(manifest):
    """A d20 rolls 1-20. All twenty need a picture or the feature is a lie."""
    plates = {int(k): v for k, v in (manifest.get("dice_plates") or {}).items()}
    assert sorted(plates) == list(range(1, SIDES + 1))
    missing = [n for n, rel in plates.items() if not (ART / rel).is_file()]
    assert missing == [], f"dice_plates points at files that are not there: {missing}"


def test_every_face_of_the_die_has_an_interface_image(manifest):
    faces = {int(k): v for k, v in (manifest.get("dice_faces") or {}).items()}
    assert sorted(faces) == list(range(1, SIDES + 1))
    missing = [n for n, rel in faces.items() if not (ART / rel).is_file()]
    assert missing == [], (
        f"dice_faces points at files that are not there: {missing} — "
        "rebuild with `python scripts/generate_dice_art.py --thumbs`"
    )


def test_the_interface_faces_are_small_squares(manifest):
    """
    Square because the plates are painted square and the toast draws a square;
    small because a 96px die is not worth a 700 KB download.
    """
    faces = {int(k): v for k, v in (manifest.get("dice_faces") or {}).items()}
    for number, relative in sorted(faces.items()):
        path = ART / relative
        width, height = _jpeg_size(path)
        assert width == height, f"face {number} is {width}x{height}, not square"
        assert path.stat().st_size <= MAX_FACE_BYTES, (
            f"face {number} is {path.stat().st_size // 1024} KB — "
            "this map should point at the derived faces, not the source plates"
        )


def test_the_client_builds_the_same_paths_the_manifest_declares(manifest):
    """
    The browser has no access to the manifest, so it rebuilds these paths from
    a template. If someone renames a face in the pack, this is what notices.
    """
    root = str(manifest.get("root", "/static/art")).rstrip("/")
    faces = {int(k): v for k, v in (manifest.get("dice_faces") or {}).items()}

    source = TOAST.read_text(encoding="utf-8")
    template = re.search(r"return\s+`([^`]*\$\{[^`]*)`", source)
    assert template, "DiceToast.jsx no longer builds a face path from a template"
    pattern = template.group(1)

    for number, relative in sorted(faces.items()):
        built = pattern.replace(
            "${String(number).padStart(2, \"0\")}", f"{number:02d}"
        )
        assert built == f"{root}/{relative}", (
            f"face {number}: client builds {built}, manifest says {root}/{relative}"
        )


def test_every_face_has_a_saved_prompt_for_both_pipelines():
    """
    Rule 9 of CLAUDE.md, applied to art: the pack is reproducible or it is a
    pile of files somebody once made. One spec, two dialects.
    """
    from engine.media.art import render_prose, render_tags, reset_subjects_cache

    reset_subjects_cache()
    spec = yaml.safe_load(SUBJECTS.read_text(encoding="utf-8"))
    assert sorted(spec["dice_faces"]) == sorted(
        f"dice_face_{n}" for n in range(1, SIDES + 1)
    )

    for number in range(1, SIDES + 1):
        subject = f"dice_face_{number}"
        prose = render_prose(subject, kind="dice")
        positive, negative = render_tags(subject, kind="dice")
        # The numeral is the entire point of the plate; a prompt that renders
        # to the bare id means the subject is not reachable from the renderer.
        assert f"numeral {number} " in prose, f"{subject} prose lost its numeral"
        assert f"numeral {number} " in positive, f"{subject} tags lost its numeral"
        assert negative, "the ComfyUI dialect must carry the house negative prompt"


def test_the_comfyui_client_has_the_dice_prompts_too():
    """ComfyUI reads its own template file; it gets an equivalent, not a stub."""
    templates = yaml.safe_load(
        (ROOT / "data" / "procgen_templates" / "comfyui.yaml").read_text(encoding="utf-8")
    )
    faces = {int(k): v for k, v in (templates.get("dice") or {}).get("faces", {}).items()}
    assert sorted(faces) == list(range(1, SIDES + 1))
    assert templates["dice"]["shared_detail"].strip()
    for number, prompt in faces.items():
        assert f"numeral {number} " in prompt


def test_the_roll_animation_agrees_with_its_stylesheet():
    """
    The component decides WHEN the die stops being a decoy; the stylesheet
    decides what it looks like until then. If those two drift the die settles
    visually on a face that is not the one the engine rolled.
    """
    source = TOAST.read_text(encoding="utf-8")
    css = EFFECTS.read_text(encoding="utf-8")

    for name, token in (("TUMBLE_MS", "--dur-roll-tumble"), ("LEAVE_MS", "--dur-roll-leave")):
        js = re.search(rf"^const {name} = (\d+);", source, re.M)
        assert js, f"{name} is gone from DiceToast.jsx"
        styled = re.search(rf"{token}:\s*(\d+)ms", css)
        assert styled, f"{token} is gone from effects.css"
        assert js.group(1) == styled.group(1), (
            f"{name} is {js.group(1)}ms but {token} is {styled.group(1)}ms"
        )
