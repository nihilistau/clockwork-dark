"""
Telemetry
=========

In-memory observability for the turn loop. Nothing here is on the critical
path: a collector that raises would trade a visible metric for an invisible
turn failure, so every entry point swallows its own errors.

Version: v0.1.0 [2026-08-08]
"""

from __future__ import annotations

from engine.telemetry.oracle import (
    Oracle,
    TurnRecord,
    UnearnedClaim,
    get_oracle,
    reset_oracle,
)

__all__ = [
    "Oracle",
    "TurnRecord",
    "UnearnedClaim",
    "get_oracle",
    "reset_oracle",
]
