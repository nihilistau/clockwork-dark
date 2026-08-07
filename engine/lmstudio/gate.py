"""
Inference Gate
==============

Serializes calls to LM Studio.

LM Studio serializes per loaded model anyway, so concurrent requests do not go
faster -- they interleave badly. The visible symptom is the one that matters:
if the Assistant turn or the summarizer fires while a narration stream is in
flight, the text on screen freezes mid-sentence until the other call finishes.

Holding the gate for the duration of a stream also gives the turn a natural
place to enforce a deadline.

Version: v0.2.0 [2026-08-07]
"""

from __future__ import annotations

import logging
import threading
from contextlib import contextmanager
from typing import Iterator

logger = logging.getLogger(__name__)

_gate = threading.BoundedSemaphore(1)
DEFAULT_WAIT_SECONDS = 180.0


class InferenceBusy(RuntimeError):
    """The gate could not be acquired in time."""


@contextmanager
def inference_slot(
    *,
    timeout: float = DEFAULT_WAIT_SECONDS,
    label: str = "",
) -> Iterator[None]:
    """
    Hold the single inference slot for the duration of the block.

    Raises:
        InferenceBusy: If the slot does not free up within timeout. Better a
            clear error the UI can show than a request that hangs forever.
    """
    if not _gate.acquire(timeout=timeout):
        raise InferenceBusy(
            f"Inference busy: waited {timeout:.0f}s for a slot ({label or 'unnamed'})"
        )
    try:
        yield
    finally:
        _gate.release()


def set_concurrency(limit: int) -> None:
    """
    Resize the gate. Tests, and setups running more than one model server.

    Not thread-safe; call at startup only.
    """
    global _gate
    _gate = threading.BoundedSemaphore(max(1, int(limit)))
    logger.info("[lmstudio] Inference concurrency set (operation=set_concurrency, limit=%s)", limit)
