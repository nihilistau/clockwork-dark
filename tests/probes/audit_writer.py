"""
A probe for ``tests/test_audit_log.py`` (v0.20.0 T14): append ``count`` audit
rows as fast as it can, through ``engine.hosting.audit.append`` -- the one
writer -- so two of these at once prove every line lands whole.

    python -m tests.probes.audit_writer <directory> <count> <label>

``directory`` is the hosting directory (under the test's ``tmp_path``);
``label`` goes in each row's ``detail`` so the test can tell the writers'
rows apart. It waits for ``<directory>/go`` to exist before it starts, so
both writers begin together. Run under the suite's child sandbox.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

#: How long the probe waits for the go file before it gives up.
GO_WAIT_SECONDS = 30.0


def main(argv: list[str]) -> int:
    from engine.hosting import audit

    directory, count, label = Path(argv[0]), int(argv[1]), argv[2]
    deadline = time.monotonic() + GO_WAIT_SECONDS
    while not (directory / "go").exists():
        if time.monotonic() > deadline:
            return 2
        time.sleep(0.005)
    padding = "p" * 150  # long lines, so a torn write would show
    for index in range(count):
        audit.append(
            "session.end",
            actor=audit.SUPERVISOR_ACTOR,
            result=audit.OK,
            target=f"{label}-{index}",
            detail={"writer": label, "index": index, "padding": padding},
            directory=directory,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
