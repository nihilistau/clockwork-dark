"""
Encounter art resolution.

An encounter declares ``art:`` as a key into ``data/art/manifest.yaml``'s
``enemies:`` block, ``engine/game/encounter.py::begin`` copies it onto the
scene alongside ``art_kind: enemy``, and
``engine/media/providers/shipped.py::lookup`` turns it into a file in the
shipped pack. That chain is four files long, every link degrades silently
rather than raising, and nothing tested it end to end -- so an encounter whose
art key had a typo, or whose picture was never drawn, would simply show the
procedural silhouette and nobody would find out which of the two had happened.

These tests walk the whole chain for every encounter that declares art, and
name any key that does not resolve to a file so it can be generated.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from engine.game import encounter as encounter_module
from engine.game.state import GameState
from engine.media.providers.base import ImageRequest
from engine.media.providers.shipped import lookup

_ROOT = Path(__file__).resolve().parents[1]


def _declared_art() -> dict[str, list[str]]:
    """Art key -> the encounter ids that use it, across the active game."""
    out: dict[str, list[str]] = {}
    for row in encounter_module.all_encounters():
        key = str(row.get("art") or "")
        if key:
            out.setdefault(key, []).append(str(row.get("id")))
    return out


def test_encounters_declare_art_at_all():
    """A guard on the guard: an empty sweep would pass every test below."""
    assert _declared_art(), "no encounter in the active game declares an art key"


def test_every_declared_art_key_resolves_to_a_shipped_file():
    """
    The failing case is actionable by design: it names the key and the
    encounters that wanted it, which is the list somebody has to hand to
    scripts/generate_art.py.
    """
    unresolved: list[str] = []
    for key, users in sorted(_declared_art().items()):
        path = lookup(ImageRequest(subject_id=key, kind="enemy"))
        if not path:
            unresolved.append(f"{key} (wanted by {sorted(users)})")
    assert not unresolved, "encounter art with no shipped picture: " + "; ".join(unresolved)


def test_the_manifest_key_and_the_file_on_disk_agree():
    """`lookup` returns None for a missing file, so check the mapping directly."""
    manifest = yaml.safe_load(
        (_ROOT / "data/art/manifest.yaml").read_text(encoding="utf-8")
    )
    art_root = _ROOT / "content/scenes/clockwork/static/art"
    for key in sorted(_declared_art()):
        relative = (manifest.get("enemies") or {}).get(key)
        assert relative, f"{key} is not in the manifest's enemies: block"
        assert (art_root / relative).is_file(), f"{key} -> {relative} is not on disk"


def test_a_begun_scene_carries_the_art_key_through_to_the_ui_payload():
    """
    The wiring itself, not just the data. If ``begin`` stopped copying ``art``
    onto the scene the manifest would still be perfect and every encounter
    would still be a grey silhouette.
    """
    keyed = _declared_art()
    encounter_id = sorted(next(iter(keyed.values())))[0]
    key = next(k for k, v in keyed.items() if encounter_id in v)

    state = GameState()
    scene = encounter_module.begin(state, encounter_id)
    assert scene.get("art") == key
    assert scene.get("art_kind") == "enemy"
    assert encounter_module.snapshot(state)["art"] == key
