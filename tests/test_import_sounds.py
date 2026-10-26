"""scripts/import_sounds.py: copies named members byte-for-byte, lower-cases, records, extracts nothing else."""

from __future__ import annotations

import hashlib
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.process
SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "import_sounds.py"


def test_an_import(tmp_path) -> None:
    archive = tmp_path / "pack" / "kenney_rpg-audio.zip"
    archive.parent.mkdir()
    body = b"OggS" + b"\x01vorbis" + b"\x00" * 40
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("Audio/metalLatch.ogg", body)
        zf.writestr("Audio/other.ogg", b"OggS")
        zf.writestr("License.txt", "CC0 1.0 Universal")
    out = tmp_path / "sounds"
    out.mkdir()
    done = subprocess.run([sys.executable, "-I", str(SCRIPT), "--archive", str(archive), "--pack", "RPG Audio",
                           "--page", "https://kenney.nl/assets/rpg-audio", "--member", "Audio/metalLatch.ogg",
                           "--licence-member", "License.txt", "--downloaded", "2026-10-24", "--to", str(out)],
                          capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    target = out / "files" / "kenney" / "rpg-audio" / "metallatch.ogg"
    assert target.read_bytes() == body
    assert not (out / "files" / "kenney" / "rpg-audio" / "other.ogg").exists()
    row = yaml.safe_load((out / "PROVENANCE.yaml").read_text(encoding="utf-8"))["files"][0]
    assert row["path"] == "files/kenney/rpg-audio/metallatch.ogg" and row["member"] == "Audio/metalLatch.ogg"
    assert row["sha256"] == hashlib.sha256(body).hexdigest() and row["licence"] == "CC0-1.0"
    assert row["licence_file"] == "LICENSES/kenney-rpg-audio.txt"
    assert (out / "LICENSES" / "kenney-rpg-audio.txt").read_text(encoding="utf-8") == "CC0 1.0 Universal"
