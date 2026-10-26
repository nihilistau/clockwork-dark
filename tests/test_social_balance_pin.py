"""
The full-session bands are a pin of hand-measured values (`tests/test_simulate_social.py` `FULL_MEASURED`, v0.24.0
T11), not a replay: the 160 runs take hours. This fast tripwire ties the pin to the data it was measured on
(v0.24.0 T14): a sha256 of the parsed balance files, so a changed value fails here and names the re-measure.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
SOCIAL = ROOT / "games" / "read-receipts" / "data" / "social"
SEP = "|".encode()


def _pin() -> tuple[tuple[str, ...], str]:
    sys.path.insert(0, str(ROOT))
    from tests import test_simulate_social as pinned

    return tuple(pinned.FULL_MEASURED_DATA), str(pinned.FULL_MEASURED_DATA_SHA256)


def _load(names: tuple[str, ...]) -> dict[str, Any]:
    return {name: yaml.safe_load((SOCIAL / f"{name}.yaml").read_text(encoding="utf-8")) for name in names}


def digest(datas: dict[str, Any]) -> str:
    """sha256 over each file's parsed content, in name order (comments and layout never move it)."""
    h = hashlib.sha256()
    for name in sorted(datas):
        h.update(name.encode() + SEP + json.dumps(datas[name], sort_keys=True, separators=(",", ":")).encode() + SEP)
    return h.hexdigest()


def test_the_full_session_pin_matches_the_data_it_was_measured_on() -> None:
    names, pinned = _pin()
    now = digest(_load(names))
    assert now == pinned, (
        "a READ RECEIPTS balance file changed since FULL_MEASURED was measured (" + ", ".join(names) + "): "
        "re-measure the full sessions (rule 10; tests/test_simulate_social.py's docstring has the command), then "
        "update FULL_MEASURED, its CLAUDE.md rows and FULL_MEASURED_DATA_SHA256 (now " + now + ") together")


def test_the_pin_moves_with_any_value_and_not_with_a_comment() -> None:
    """The canary: one value changed moves the digest; the same files re-read (comments ignored) do not."""
    names, _ = _pin()
    datas = _load(names)
    base = digest(datas)
    assert digest(_load(names)) == base
    datas["scenes"] = {**datas["scenes"], "canary_value": 1}
    assert digest(datas) != base
