"""
A process that does nothing (v0.20.0 T15 fix round 1): it waits until its
stdin closes, or a minute at most, then exits 0. ``tests/test_supervisor.py``
starts one as a stand-in for a process the suite did NOT start as a hosting
child (a reused pid), so the orphan guard's refusal to signal it can be
tested on a process the test owns.

Run as ``python -m tests.probes.idle_child`` from the repository root.
"""

from __future__ import annotations

import sys
import threading


def main() -> int:
    done = threading.Event()

    def wait_for_eof() -> None:
        try:
            sys.stdin.read()
        finally:
            done.set()

    threading.Thread(target=wait_for_eof, daemon=True).start()
    done.wait(60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
