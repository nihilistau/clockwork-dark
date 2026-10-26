"""
The per-session narration turnstile (v0.23.0 spec §20.1; N1-N3, m10; Plan decision 3).

One player's world turn and their voice pass must never BOTH ask the
supervisor for a narration ticket: under one account the second would be
refused `other_window`. Only the turnstile's holder may acquire the ticket.

- The WORLD turn waits (`acquire_world`, bounded) BEFORE it tries the turn lock,
  so it never waits holding the lock. While it waits, `world_waiting > 0`.
- A VOICE pass never waits: `try_acquire_voice` succeeds only when nobody holds
  it and no world turn is waiting, and the pass holds it for ONE model call.
  So a world turn waits at most one call.
- The condition's lock (`_cond`) is held only to read or change `holder` and
  `world_waiting`, never across work: a LEAF. The HOLD is a logical lock taken
  before the turn lock and before every ordered lock (engine/locks.py,
  "THE NARRATION TURNSTILE").

Built per session by `SessionStore._build`, only for a story declaring
`paths.social`; a session built by hand gets `NULL` (always free).
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Optional

from engine.config import get_config, hosting_enabled

logger = logging.getLogger(__name__)

WORLD = "world"
VOICE = "voice"


class Turnstile:
    def __init__(self) -> None:
        self._cond = threading.Condition(threading.Lock())
        self.holder: Optional[str] = None
        self.world_waiting = 0
        #: Seconds held, by side: the narration-share metric (T28).
        self.held_seconds: dict[str, float] = {WORLD: 0.0, VOICE: 0.0}
        self._since = 0.0
        #: What the narration-share metric has already been told, and when (monotonic): `take_share`.
        self._told: dict[str, float] = {WORLD: 0.0, VOICE: 0.0}
        self._told_at = time.monotonic()

    def take_share(self, interval: float, now: Optional[float] = None) -> Optional[tuple[float, float]]:
        """
        The narration share not yet reported, as (world seconds, voice seconds) held since the last report,
        once at least `interval` seconds have passed since it (the metric is per minute); else None. Nothing
        held since then is None too, and moves the clock on. The condition's lock is a leaf, taken only to read.
        """
        now = time.monotonic() if now is None else now
        with self._cond:
            if now - self._told_at < float(interval):
                return None
            world = self.held_seconds[WORLD] - self._told[WORLD]
            voice = self.held_seconds[VOICE] - self._told[VOICE]
            self._told = dict(self.held_seconds)
            self._told_at = now
        return (world, voice) if (world > 0.0 or voice > 0.0) else None

    def acquire_world(self, timeout: float) -> bool:
        """Wait at most `timeout` seconds for the turnstile; the caller must hold NO lock (checked by test)."""
        deadline = time.monotonic() + max(0.0, float(timeout))
        with self._cond:
            self.world_waiting += 1
            try:
                while self.holder is not None:
                    left = deadline - time.monotonic()
                    if left <= 0:
                        return False
                    self._cond.wait(left)
                self.holder = WORLD
                self._since = time.monotonic()
                return True
            finally:
                self.world_waiting -= 1

    def try_acquire_voice(self) -> bool:
        """Never waits: free and no world turn waiting, or False."""
        with self._cond:
            if self.holder is not None or self.world_waiting:
                return False
            self.holder = VOICE
            self._since = time.monotonic()
            return True

    def release(self, who: str) -> None:
        with self._cond:
            if self.holder != who:
                raise RuntimeError(f"turnstile released by {who!r} while held by {self.holder!r}")
            self.held_seconds[who] += time.monotonic() - self._since
            self.holder = None
            self._cond.notify_all()


class _NullTurnstile:
    """For a session with no turnstile (built by hand): always free, never waits.
    `held_seconds` is a class-level dict that is NEVER written (`release` is a no-op): it has its
    own module-state row (pre-flight F37)."""

    holder = None
    world_waiting = 0
    held_seconds = {WORLD: 0.0, VOICE: 0.0}

    def take_share(self, interval: float, now: Optional[float] = None) -> None:
        return None

    def acquire_world(self, timeout: float) -> bool:
        return True

    def try_acquire_voice(self) -> bool:
        return True

    def release(self, who: str) -> None:
        return None


NULL = _NullTurnstile()


#: How often, at most, one account's narration share is reported (seconds): the metric is per minute.
SHARE_INTERVAL_SECONDS = 60.0


def report_share(session: Any) -> None:
    """
    Hosted narration-share metric (v0.23.0 T28, spec §20.1): after a side lets the turnstile go, the seconds
    each side held it since the last report, once a minute at most, as two `phone` rows (events
    `narration_world` and `narration_voice`, `ms` the seconds held), through `default_scene`'s phone hook
    (None in local mode: nothing is recorded). Never raises; a failure is logged at warning with its exception
    (v0.24.0 T14: it was swallowed silently).
    """
    try:
        share = of(session).take_share(SHARE_INTERVAL_SECONDS)
        if share is None:
            return
        from engine.scenes import default_scene

        for event, seconds in (("narration_world", share[0]), ("narration_voice", share[1])):
            if seconds > 0.0:
                default_scene._report_phone(session, event, "ok", seconds * 1000.0)
    except Exception:  # noqa: BLE001 -- a metric must never fail a turn or a pass
        logger.warning("narration-share metric not recorded", exc_info=True)


def of(session: Any) -> "Turnstile | _NullTurnstile":
    return getattr(session, "narration_turnstile", None) or NULL


def world_wait_seconds() -> float:
    """Hosted: `hosting.queue_wait_seconds`; local: the per-call timeout, `llm.timeout_seconds` (Plan decision 14)."""
    if hosting_enabled():
        return float(get_config().get("hosting.queue_wait_seconds", 600))
    return float(get_config().get("llm.timeout_seconds", 300))
