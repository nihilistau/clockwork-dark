"""Every shipped sound file is recorded, CC0, from a §8.1 pack, and byte-identical to its record (spec §8.2)."""

from __future__ import annotations

import hashlib
import re
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
            # (T14 d11, spec §8.2) the pack's version, when its own licence text states one ("Casino Audio (1.1)")
            stated = re.search(r"^[ \t]*[^\n(]+\((\d+(?:\.\d+)*)\)[ \t]*$", licence.read_text(encoding="utf-8"), re.M)
            assert row.get("pack_version") == (stated.group(1) if stated else None), row["path"]


def test_the_engine_ships_its_recorded_files() -> None:
    """(T14 c12) The checks above loop over what they find, so an engine root that resolves nowhere would pass
    them all: the engine's files are there, one per provenance row."""
    root = sounds.engine_root()
    rows = yaml.safe_load((root / "PROVENANCE.yaml").read_text(encoding="utf-8"))["files"]
    assert rows and len(list(root.rglob("*.ogg"))) == len(rows)


def test_every_shipped_file_is_bound_somewhere() -> None:
    """Review M8: no dead row. An engine file is used by a sound row in the engine's sounds.yaml or by a story's
    `engine:` row; a story's own file (`files/...` beside its sounds.yaml) by a row of that story's (T14 c12:
    before, a story's own files were never checked)."""
    engine = sounds.load_engine()
    used: dict[Path, set[str]] = {engine["root"]: set()}
    for row in engine["data"]["sounds"].values():
        if "file" in row:
            used[engine["root"]].add(row["file"])
    for manifest in registry.discover().values():
        story = sounds.load_story(manifest)
        if story is None:
            continue
        own = used.setdefault(story["root"], set())
        for row in (story["data"].get("sounds") or {}).values():
            if "file" in row:
                if row["file"].startswith("engine:"):
                    used[engine["root"]].add(row["file"][len("engine:"):])
                else:
                    own.add(row["file"])
    assert len(used) == len(_roots())                 # every declaring story's root, and the engine's
    for root, names in used.items():
        shipped = {p.relative_to(root).as_posix() for p in root.rglob("*.ogg")}
        assert shipped <= names, (root, sorted(shipped - names))
