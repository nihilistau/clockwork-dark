"""
Hosted Mode: the Lanes, Held by the Supervisor
==============================================

``RemoteLanes`` is the lane backend a supervised worker plugs into the gate
(``engine.llm.gate.set_lane_backend``, from ``engine.hosting.install``), so
every worker queues in ONE queue, the supervisor's (spec §14.4,
``engine/hosting/supervisor/queue.py``). The gate's rules are unchanged: a
turn is admitted (a narration ``lane.acquire``) before it runs anything, its
narration calls re-enter the held ticket without a bus request, and a busy
utility lane degrades as it always has.

- ``acquire`` sends ``lane.acquire {lane, account, timeout}`` and waits for
  the grant. The bus request's own timeout is STRICTLY LONGER than the
  acquire's (``BUS_MARGIN_SECONDS``), so the supervisor -- which answers
  ``busy`` at the acquire's deadline -- always answers first.
- ``cancel`` (a ``gate.CancelToken``; T11 fix round 1): a hosted socket
  turn's admission is called off when its socket disconnects. The wait ends
  at once (``InferenceBusy``, ``cancelled``) and ``lane.cancel`` withdraws
  the waiter at the supervisor, so the departed player holds no place and no
  account claim.
- A GRANT NOBODY WAITS FOR (it crossed a cancel on the wire, or the bus
  timed out) is released at once from the bus's reader thread and counted
  (``abandoned_grants``; a ``lane`` event, outcome ``cancelled``), so the
  slot goes to the next waiter.
- ``release`` sends ``lane.release``; one that cannot be sent is logged and
  left to the connection: the lifeline ends this worker, and the
  supervisor frees every ticket of a closed connection.
- A RECLAIMED TICKET (held past ``max_hold_seconds``; T11 fix round 1): the
  supervisor's ``lane.reclaimed`` is acknowledged by ``reclaimed_ticket``,
  and ``reclaimed(ticket)`` then answers True, so the turn holding it makes
  no further model call (``engine.llm.gate``); its later release is
  accepted quietly by the supervisor. Only a ticket this worker still holds
  is noted (v0.20.0 T12, T11's N3): a ``lane.reclaimed`` that arrives after
  its ticket was released is acknowledged and forgotten, so nothing is kept
  that no release would ever remove.
- FAIL CLOSED. With the bus down, ``acquire`` raises ``InferenceBusy`` at
  once (the turn is refused, never run unqueued), and the lifeline ends the
  worker.

Version: v0.3.0 [2026-10-05]
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Optional

from engine.hosting.bus import BusClient, BusClosed, BusError
from engine.llm.gate import BUSY, CANCELLED, OTHER_WINDOW, CancelToken, InferenceBusy

logger = logging.getLogger(__name__)

#: How much longer than the acquire's own timeout its bus request waits.
BUS_MARGIN_SECONDS = 5.0

#: How long a ``lane.release`` waits for its acknowledgement.
RELEASE_SECONDS = 5.0

#: What a turn refused by the account rule is told (spec §5.4's wording).
OTHER_WINDOW_TEXT = "A turn is still running in your other window."


class RemoteLanes:
    """The gate's lane backend under the supervisor (see the module docstring)."""

    def __init__(self, bus: BusClient, *, margin: float = BUS_MARGIN_SECONDS) -> None:
        if margin <= 0:
            raise ValueError("the bus must wait longer than the acquire")
        self.bus = bus
        self.margin = float(margin)
        #: Grants that came after their caller gave up, each released at once.
        #: Written only on the bus's reader thread (the one ``on_late`` runs
        #: on), so it needs no lock; a reader elsewhere sees a whole int.
        self.abandoned_grants = 0
        #: Tickets the supervisor reclaimed and this worker acknowledged,
        #: while still held. With ``_held`` under ``_lock``, a leaf: written
        #: on turn threads (acquire, release) and the bus pool (a reclaim).
        self._reclaimed: set[str] = set()
        #: Tickets granted to this worker and not yet released.
        self._held: set[str] = set()
        self._lock = threading.Lock()

    def acquire(
        self,
        lane: str,
        timeout: float,
        account: str = "",
        story: str = "",
        *,
        cancel: Optional[CancelToken] = None,
    ) -> str:
        """
        A ticket in ``lane``, once the supervisor grants one. ``story`` is
        not sent: the supervisor stamps it from this connection. ``cancel``
        calls the wait off (and withdraws it at the supervisor).

        Raises:
            InferenceBusy: ``busy`` (no slot in ``timeout``), ``other_window``
                (the account's narration ticket is another worker's),
                ``cancelled``, or the bus's code (the link is down).
        """
        if not self.bus.connected:
            raise InferenceBusy(
                f"Inference busy: the supervisor's queue is unreachable (lane {lane!r})",
                reason="closed",
            )
        args: dict[str, Any] = {"lane": lane, "timeout": max(0.0, float(timeout))}
        if account:
            args["account"] = account
        try:
            result = self.bus.request(
                "lane.acquire",
                args,
                timeout=float(timeout) + self.margin,
                on_late=self._late,
                cancel=cancel,
                on_cancel=self._withdraw,
            )
        except BusError as exc:
            if exc.code == OTHER_WINDOW:
                raise InferenceBusy(OTHER_WINDOW_TEXT, reason=OTHER_WINDOW) from None
            if exc.code == BUSY:
                raise InferenceBusy(
                    f"Inference busy: waited {float(timeout):.0f}s for a slot in lane {lane!r}",
                    reason=BUSY,
                ) from None
            if exc.code == CANCELLED:
                raise InferenceBusy(
                    f"Inference wait called off: the player left (lane {lane!r})", reason=CANCELLED
                ) from None
            raise InferenceBusy(
                f"Inference busy: the supervisor's queue did not answer ({exc.code}) in lane {lane!r}",
                reason=exc.code,
            ) from None
        ticket = result.get("ticket")
        if not isinstance(ticket, str) or not ticket:
            raise InferenceBusy(f"Inference busy: no ticket in the grant (lane {lane!r})", reason="internal")
        with self._lock:
            self._held.add(ticket)
        return ticket

    def release(self, ticket: Any) -> None:
        """Give ``ticket`` back. Never raises: a closed link frees it at the supervisor."""
        with self._lock:
            self._held.discard(str(ticket))
            self._reclaimed.discard(str(ticket))
        try:
            self.bus.request("lane.release", {"ticket": str(ticket)}, timeout=RELEASE_SECONDS)
        except BusError as exc:
            logger.warning(
                "[lanes] A lane release was not acknowledged (operation=lane.release, error=%s); "
                "the supervisor frees it with this worker's connection",
                exc.code,
            )

    def reclaimed(self, ticket: Any) -> bool:
        """Whether the supervisor took ``ticket`` back (the gate stops its turn's model calls)."""
        with self._lock:
            return str(ticket) in self._reclaimed

    def reclaimed_ticket(self, ticket: str) -> dict[str, Any]:
        """
        The bus ``lane.reclaimed`` handler: note it while the ticket is still
        held, and acknowledge (the reply) either way.
        """
        with self._lock:
            held = str(ticket) in self._held
            if held:
                self._reclaimed.add(str(ticket))
        if not held:
            logger.info(
                "[lanes] A reclaim came for a ticket already released; acknowledged "
                "(operation=lane.reclaimed)"
            )
            return {}
        logger.warning(
            "[lanes] The supervisor reclaimed a lane ticket held past max_hold_seconds; this "
            "turn makes no further model call (operation=lane.reclaimed)"
        )
        return {}

    def _withdraw(self, request_id: int) -> None:
        """A cancelled wait: withdraw it at the supervisor (never waits: any thread)."""
        try:
            self.bus.send_request("lane.cancel", {"id": int(request_id)})
        except BusError:
            pass  # the link is gone: the connection's close drops the waiter

    def _late(self, reply: dict[str, Any]) -> None:
        """A reply after its caller gave up (the reader thread): a grant goes straight back."""
        if reply.get("ok") is not True:
            return
        result = reply.get("result")
        ticket = result.get("ticket") if isinstance(result, dict) else None
        if not isinstance(ticket, str) or not ticket:
            return
        self.abandoned_grants += 1
        try:
            self.bus.send_request("lane.release", {"ticket": ticket})
        except BusClosed:
            pass  # the connection's close frees it
        logger.warning(
            "[lanes] A grant came after its caller gave up; released at once "
            "(operation=lane.acquire, event=lane, outcome=cancelled, count=%d)",
            self.abandoned_grants,
        )


__all__ = ["BUS_MARGIN_SECONDS", "OTHER_WINDOW_TEXT", "RELEASE_SECONDS", "RemoteLanes"]
