"""
A process is its pid AND its creation time (v0.20.0 T15 fix round 1, I2).

The suite's side of ``engine/hosting/process_identity.py`` (moved there in
fix round 2, N1, when the gunicorn worker's stop of its master needed it):
a child's probe reports its pid with its creation time (``report()``), and
the orphan guard counts or signals a pid only while the process holding it
has that creation time (``alive``, ``terminate``). A pid whose identity
cannot be checked is never signalled. See the engine module for the clock
each platform uses and why the tolerance is zero.

Imported by the probes (no pytest here), ``tests/hosting_instance.py`` and
the tests that kill a child on purpose.

Version: v0.2.0 [2026-10-06]
"""

from __future__ import annotations

from typing import Any

from engine.hosting.process_identity import Identity, alive, created, identify, me, same, terminate


def report() -> dict[str, Any]:
    """What a probe writes about itself: ``{"pid", "created"}``."""
    own = me()
    return {"pid": own.pid, "created": own.created}


def of_report(data: dict[str, Any]) -> Identity:
    """The identity a probe's report records (``created`` None for a report without one)."""
    raw = data.get("created")
    stamp = float(raw) if isinstance(raw, (int, float)) and not isinstance(raw, bool) else None
    return Identity(int(data["pid"]), stamp)


__all__ = ["Identity", "alive", "created", "identify", "me", "of_report", "report", "same", "terminate"]
