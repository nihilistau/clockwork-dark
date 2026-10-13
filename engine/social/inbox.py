"""
The session inbox (v0.22.0 spec §16.4): results that could not take a
session's turn lock, parked until its next holder applies them.

No thread ever WAITS for a turn lock (a leaf may not be taken blocking, and a
turn lock is only ever tried): a voicing pass whose commit is still refused
after `social.voice.commit_retry_ms` -- and, from T19, the media worker's
hand-off -- puts its result here, after its liveness check, and moves on. The
next mechanics action (`turn.run_mechanics` step 1) and the next pass's
snapshot drain it under the turn lock (`voicer.drain_inbox`), re-validating
each item as a commit does (its epoch equal to the session's; a media
result's account equal to the session's owner) before `apply_effect`.

One inbox per `GameSession` OBJECT (`GameSession.inbox`), never saved: a
released session's inbox dies with it. Its voiced replies were never shown
and are voiced again from the save's due messages; its media rows resubmit
on resume (T19). That loss is a docs/GOVERNANCE.md row.
"""

from __future__ import annotations

import threading
from collections import deque
from typing import Any


class SessionInbox:
    """
    Results that could not take a session's turn lock (spec §16.4): a media
    hand-off, a commit past its retries. One per GameSession OBJECT; its lock
    is a LEAF (its holder takes nothing). Drained under the turn lock by the
    next mechanics action and the next pass's snapshot, each item re-validated.
    A released session's inbox dies with it (NOT WIRED row: its voiced replies
    are re-voiced from the save's due messages; its media rows resubmit).
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._items: deque[dict[str, Any]] = deque()

    def put(self, item: dict[str, Any]) -> None:
        with self._lock:
            self._items.append(item)

    def drain(self) -> list[dict[str, Any]]:
        with self._lock:
            items = list(self._items)
            self._items.clear()
        return items

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)


__all__ = ["SessionInbox"]
