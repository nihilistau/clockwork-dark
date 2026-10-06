"""
Hosted Mode: the Worker's Sessions Ops
======================================

What a supervised worker answers when the admin panel asks about its live
sessions (v0.20.0 T15, spec §14.8). The front door asks the supervisor
(``sessions.list``, ``sessions.end``, ``sessions.end_owner``), and the
supervisor asks each worker with the ``worker.*`` request of the same name,
which ``register`` puts on this worker's bus client (``install()`` calls it
once the bus is connected):

- ``worker.sessions.list {limit, offset}``: a page of
  ``SessionStore.describe`` (the owner, the session and save ids, created,
  last activity, the turn count, whether a turn is running) plus, per row,
  the sockets in its Socket.IO room (``sockets``), and ``total``. NOTHING ELSE
  FROM THE STATE: no player name, place, day, choice or text (AGENTS.md rule
  12: the panel observes the service and moderates nothing). A page that
  would not fit one bus frame is answered ``too_large`` by the bus itself,
  never cut;
- ``worker.sessions.end {session_id}``: ``SessionStore.end`` -- released
  through ``delete`` and the release hook (its room closed), refused
  ``busy`` while its turn lock is held, ``not_found`` when it is not live;
- ``worker.sessions.end_owner {account}``: ``SessionStore.end_owner`` (an
  account disabled or deleted), ``{ended, busy}``;
- ``worker.oracle.snapshot`` (v0.20.0 T17): this process's Oracle numbers,
  ``{"oracle": metrics_schema.project_oracle(metrics(), recent())}`` -- the
  projection, never the raw dicts, which hold the stat names a model claimed
  and play state (spec §14.10).

Every handler reads the store under its own guard and NO turn lock (a
listing never waits on a turn; ``end`` tries the turn lock without waiting).
Telling the player their session was ended is NOT WIRED (a client event, for
v0.21.0: docs/GOVERNANCE.md): their tab goes quiet, and their run is on disk.

Version: v0.2.0 [2026-10-06]
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

#: Error codes the ``worker.sessions.end`` answer may carry.
NOT_FOUND = "not_found"
BUSY = "busy"

#: The Socket.IO namespace every story's events use.
NAMESPACE = "/"


def sockets_in_room(scene: Any, room: str) -> int:
    """
    How many sockets are in ``room`` (a session id), read from Flask-SocketIO's
    room manager. Never raises: 0 when there is no manager or no such room.
    """
    try:
        manager = scene.socketio.server.manager
        return sum(1 for _ in manager.get_participants(NAMESPACE, room))
    except Exception:  # noqa: BLE001 -- a count, never a reason to fail a listing
        return 0


def register(client: Any, scene: Any) -> None:
    """Answer the supervisor's ``worker.sessions.*`` on ``client`` for ``scene``'s store."""
    from engine.hosting.bus import BusRefusal
    from engine.session.store import SessionBusy

    store = getattr(scene, "store", None)

    def listing(args: dict[str, Any]) -> dict[str, Any]:
        if store is None:
            return {"rows": [], "total": 0}
        rows, total = store.describe(int(args["limit"]), int(args["offset"]))
        for row in rows:
            row["sockets"] = sockets_in_room(scene, row["session_id"])
        return {"rows": rows, "total": total}

    def end(args: dict[str, Any]) -> dict[str, Any]:
        session_id = str(args["session_id"])
        if store is None:
            raise BusRefusal(NOT_FOUND)
        try:
            store.end(session_id)
        except SessionBusy:
            logger.info("[hosting] An admin's end refused: a turn is running (operation=sessions.end, id=%s)", session_id)
            raise BusRefusal(BUSY) from None
        except KeyError:
            raise BusRefusal(NOT_FOUND) from None
        logger.info("[hosting] Session ended by an admin (operation=sessions.end, id=%s)", session_id)
        return {"ended": True}

    def end_owner(args: dict[str, Any]) -> dict[str, Any]:
        account = str(args["account"])
        if store is None:
            return {"ended": 0, "busy": 0}
        ended, busy = store.end_owner(account)
        logger.info(
            "[hosting] An account's sessions ended (operation=sessions.end_owner, account=%s, ended=%d, busy=%d)",
            account,
            ended,
            busy,
        )
        return {"ended": ended, "busy": busy}

    def oracle_snapshot(_args: dict[str, Any]) -> dict[str, Any]:
        # v0.20.0 T17 (spec §14.10): the Oracle holds model output (the stat
        # names of its unearned claims) and play state (evil_progress), so
        # only the projection leaves this process, never the raw dicts.
        from engine.hosting.metrics_schema import project_oracle
        from engine.telemetry.oracle import get_oracle

        oracle = get_oracle()
        return {"oracle": project_oracle(oracle.metrics(), oracle.recent())}

    client.handle("worker.sessions.list", listing)
    client.handle("worker.sessions.end", end)
    client.handle("worker.sessions.end_owner", end_owner)
    client.handle("worker.oracle.snapshot", oracle_snapshot)


__all__ = ["BUSY", "NAMESPACE", "NOT_FOUND", "register", "sockets_in_room"]
