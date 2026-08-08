"""
Inference Gate
==============

Rations concurrent calls to LM Studio, per LANE.

WHY LANES
---------
The old gate was a single ``BoundedSemaphore(1)`` for the whole process, on the
premise that LM Studio serializes per loaded model anyway. That premise costs
more than it saves: the Assistant turn and the memory summarizer had to queue
behind narration, so the two cheapest calls in the game could each add their
full latency to the turn the player is watching. And when they ran first,
narration waited on THEM -- the frozen screen the single gate was meant to
prevent.

LM Studio supports concurrent requests. So narration gets a lane of its own and
utility work shares another. Narration never waits for a summary again, and
utility calls still cannot stampede the GPU.

Limits are configurable under ``lmstudio.lanes``; a lane with no configured
limit falls back to ``DEFAULT_LANE_LIMIT``.

Version: v0.3.0 [2026-08-08]
"""

from __future__ import annotations

import logging
import threading
from contextlib import contextmanager
from typing import Iterator, Optional

logger = logging.getLogger(__name__)

DEFAULT_WAIT_SECONDS = 180.0
DEFAULT_LANE_LIMIT = 1

# Narration is the one the player is watching, so it gets a dedicated slot.
# Utility covers the summarizer, the Assistant, mechanics and quest evaluation.
_DEFAULT_LANES: dict[str, int] = {
    "narration": 1,
    "utility": 2,
}

_lanes: dict[str, threading.BoundedSemaphore] = {}
_lanes_lock = threading.Lock()
_limits: dict[str, int] = dict(_DEFAULT_LANES)


class InferenceBusy(RuntimeError):
    """The gate could not be acquired in time."""


def _configured_limit(lane: str) -> int:
    """Lane size from config, falling back to the shipped defaults."""
    try:
        from engine.config import get_config

        configured = (get_config().get("lmstudio.lanes", {}) or {}).get(lane)
        if configured is not None:
            return max(1, int(configured))
    except Exception:  # noqa: BLE001 -- config must never break inference
        pass
    return max(1, int(_limits.get(lane, DEFAULT_LANE_LIMIT)))


def _semaphore(lane: str) -> threading.BoundedSemaphore:
    """Get or create the semaphore for a lane."""
    with _lanes_lock:
        existing = _lanes.get(lane)
        if existing is None:
            limit = _configured_limit(lane)
            existing = threading.BoundedSemaphore(limit)
            _lanes[lane] = existing
            logger.info(
                "[lmstudio] Lane opened (operation=_semaphore, lane=%s, limit=%s)",
                lane,
                limit,
            )
        return existing


@contextmanager
def inference_slot(
    *,
    timeout: float = DEFAULT_WAIT_SECONDS,
    label: str = "",
    lane: Optional[str] = None,
) -> Iterator[None]:
    """
    Hold a slot in one lane for the duration of the block.

    Args:
        timeout: Seconds to wait for a slot.
        label: Diagnostic name for the caller, used in the error message.
        lane: Lane to queue in. Defaults to "utility" -- the conservative
            choice, since anything that has not opted into its own lane is by
            definition not the thing on screen.

    Raises:
        InferenceBusy: If no slot frees up within timeout. Better a clear error
            the UI can show than a request that hangs forever.
    """
    resolved_lane = lane or "utility"
    semaphore = _semaphore(resolved_lane)
    if not semaphore.acquire(timeout=timeout):
        raise InferenceBusy(
            f"Inference busy: waited {timeout:.0f}s for a slot in lane "
            f"{resolved_lane!r} ({label or 'unnamed'})"
        )
    try:
        yield
    finally:
        semaphore.release()


def set_lane_limit(lane: str, limit: int) -> None:
    """
    Resize one lane. Startup and tests only; not safe while calls are in flight.
    """
    with _lanes_lock:
        _limits[lane] = max(1, int(limit))
        _lanes[lane] = threading.BoundedSemaphore(_limits[lane])
    logger.info(
        "[lmstudio] Lane resized (operation=set_lane_limit, lane=%s, limit=%s)",
        lane,
        _limits[lane],
    )


def set_concurrency(limit: int) -> None:
    """
    Resize every lane to the same limit.

    Kept for the callers that predate lanes; ``set_lane_limit`` is the finer
    tool. Not thread-safe; call at startup only.
    """
    for lane in set(list(_lanes) + list(_DEFAULT_LANES)):
        set_lane_limit(lane, limit)
    logger.info(
        "[lmstudio] Inference concurrency set (operation=set_concurrency, limit=%s)",
        limit,
    )


def reset_lanes() -> None:
    """Drop all lanes so the next acquire rebuilds them from config. Tests."""
    with _lanes_lock:
        _lanes.clear()
        _limits.clear()
        _limits.update(_DEFAULT_LANES)
