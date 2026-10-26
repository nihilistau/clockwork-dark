"""The audio budget (spec §8.3): 1 MiB for all shipped audio, 48 KiB a file, Ogg Vorbis of at most 2 channels, 48 kHz."""

from __future__ import annotations

import struct
from pathlib import Path

from tests.test_sound_provenance import _roots

TOTAL = 1_048_576
PER_FILE = 48 * 1024


def _vorbis_header(data: bytes) -> tuple[int, int]:
    at = data.find(b"\x01vorbis")
    assert at >= 0, "no Vorbis identification header"
    channels = data[at + 11]
    (rate,) = struct.unpack("<I", data[at + 12: at + 16])
    return channels, rate


def test_the_budget() -> None:
    files = [p for root in _roots() for p in root.rglob("*.ogg")]
    assert files, "no shipped audio found: the budget would pass on nothing (T14 c12)"
    assert sum(p.stat().st_size for p in files) <= TOTAL
    for path in files:
        data = path.read_bytes()
        assert len(data) <= PER_FILE, path
        assert data[:4] == b"OggS", path
        channels, rate = _vorbis_header(data)
        assert channels <= 2 and rate <= 48000, (path, channels, rate)
