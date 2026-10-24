"""Every shipped sound file is recorded, CC0, from a §8.1 pack, and byte-identical to its record (spec §8.2)."""

from __future__ import annotations

import hashlib
from pathlib import Path

import yaml

from engine.games import registry, sounds

PACKS = {"Casino Audio", "RPG Audio", "Impact Sounds", "Sci-fi Sounds"}
ROW_KEYS = {"path", "sha256", "bytes", "author", "pack", "source_url", "archive", "archive_sha256", "member",
            "licence", "licence_file", "downloaded", "imported", "pack_version"}


def _roots() -> list[Path]:
    roots = [sounds.engine_root()]
    for manifest in registry.discover().values():
        if (manifest.paths or {}).get("sounds"):
            roots.append(manifest.resolve(manifest.paths["sounds"]))
    return roots


def test_every_file_has_one_row_and_every_row_a_file() -> None:
    for root in _roots():
        files = {p.relative_to(root).as_posix() for p in root.rglob("*.ogg")}
        prov = root / "PROVENANCE.yaml"
        rows = (yaml.safe_load(prov.read_text(encoding="utf-8")) or {}).get("files", []) if prov.is_file() else []
        paths = [r["path"] for r in rows]
        assert len(paths) == len(set(paths)), root
        assert set(paths) == files, (root, sorted(set(paths) ^ files))


def test_every_row_is_cc0_kenney_from_a_named_pack_and_matches_its_bytes() -> None:
    for root in _roots():
        prov = root / "PROVENANCE.yaml"
        if not prov.is_file():
            continue
        for row in yaml.safe_load(prov.read_text(encoding="utf-8"))["files"]:
            assert set(row) <= ROW_KEYS and ROW_KEYS - {"pack_version"} <= set(row), row["path"]
            assert row["licence"] == "CC0-1.0" and row["pack"] in PACKS, row["path"]
            assert row["author"] == "Kenney (www.kenney.nl)", row["path"]
            licence = root / row["licence_file"]
            assert licence.is_file() and "CC0" in licence.read_text(encoding="utf-8"), row["licence_file"]
            assert row["licence_file"] == f"LICENSES/kenney-{Path(row['path']).parent.name}.txt", row["path"]
            data = (root / row["path"]).read_bytes()
            assert len(data) == row["bytes"], row["path"]
            assert hashlib.sha256(data).hexdigest() == row["sha256"], row["path"]
            assert row["path"] == row["path"].lower(), row["path"]                  # lower-cased at import (rule 11)
            assert Path(row["member"]).name.lower() == Path(row["path"]).name       # the original case kept


def test_every_shipped_file_is_bound_somewhere() -> None:
    """Review M8: no dead row. A file is used by a sound row in the engine's or a story's sounds.yaml."""
    used: set[str] = set()
    engine = sounds.load_engine()
    for row in engine["data"]["sounds"].values():
        if "file" in row:
            used.add(row["file"])
    for manifest in registry.discover().values():
        story = sounds.load_story(manifest)
        for row in ((story or {}).get("data", {}).get("sounds") or {}).values():
            if "file" in row:
                used.add(row["file"][len("engine:"):] if row["file"].startswith("engine:") else row["file"])
    shipped = {p.relative_to(engine["root"]).as_posix() for p in engine["root"].rglob("*.ogg")}
    assert shipped - used <= UNBOUND_UNTIL_T10, sorted(shipped - used - UNBOUND_UNTIL_T10)
    assert UNBOUND_UNTIL_T10 <= shipped - used, "a path bound now must leave UNBOUND_UNTIL_T10"


#: The engine files no sound binds until the palettes land (T9 removed its three: cloth1, cloth2, dooropen_1; T10 deletes this list).
UNBOUND_UNTIL_T10: frozenset[str] = frozenset({
    "files/kenney/casino-audio/card-slide-1.ogg", "files/kenney/casino-audio/card-place-1.ogg",
    "files/kenney/casino-audio/chips-stack-1.ogg", "files/kenney/rpg-audio/metallatch.ogg",
    "files/kenney/rpg-audio/handlecoins.ogg", "files/kenney/rpg-audio/bookflip1.ogg",
    "files/kenney/rpg-audio/doorclose_1.ogg",
    "files/kenney/impact-sounds/impactbell_heavy_000.ogg", "files/kenney/impact-sounds/impactwood_light_000.ogg",
    "files/kenney/sci-fi-sounds/laserretro_000.ogg", "files/kenney/sci-fi-sounds/forcefield_000.ogg",
})
