"""
The Admin Panel: the Queue
==========================

``GET /admin/queue`` (v0.20.0 T16, spec §14.9, §14.4) renders the
supervisor's ``queue.snapshot``: per lane of the model server, its limit,
whether it is paused, who holds a slot and for how long, and who waits, in
order, with their story and wait so far; and the stories whose new turns are
paused (a drain, a model apply). Who is an ACCOUNT ID, as the snapshot
carries it, with the account's name resolved here from ``users.json`` (the
bus carries ids and numbers only). Never play text: the snapshot holds slugs,
ids, enums and times, and nothing else is read (AGENTS.md rule 12: the panel
observes the service and moderates nothing).

Below the live view, the recent waits' p50 and p95 over the last hour
(v0.20.0 T17): a turn's wait for admission and each lane's wait and hold,
from the supervisor's metrics store (``admin/metrics.py``).

``GET /admin/api/queue.json``: the live view, for the page's refresh script.

Version: v0.2.0 [2026-10-06]
"""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

logger = logging.getLogger(__name__)

#: How long the page waits for the snapshot (the selector answers it at once).
BUS_SECONDS = 10.0


def queue_data(now: Optional[float] = None) -> dict[str, Any]:
    """
    The snapshot, flattened for the page: ``lanes`` (lane, limit, paused,
    held, waiting), ``holders`` and ``waiters`` (lane, position, story,
    account, name, seconds), ``paused_stories``, ``closing_stories``,
    ``error``. Never raises.
    """
    from engine.hosting.admin.sessions import ask
    from engine.hosting.auth import hosting_state
    from engine.hosting.bus import BusError

    now = time.time() if now is None else float(now)
    try:
        snapshot = ask("queue.snapshot", timeout=BUS_SECONDS)
    except BusError as exc:
        logger.warning("[admin] The queue could not be read (operation=queue.snapshot, error=%s)", exc.code)
        return {"lanes": [], "holders": [], "waiters": [], "paused_stories": [], "closing_stories": [], "error": exc.code}
    names = {account.id: account.name for account in hosting_state().accounts.all()}

    def row(lane: str, position: int, entry: Any) -> dict[str, Any]:
        entry = entry if isinstance(entry, dict) else {}
        account = str(entry.get("account") or "")
        since = float(entry.get("since") or 0.0)
        return {
            "lane": lane,
            "position": position,
            "story": str(entry.get("story") or ""),
            "account": account,
            "name": names.get(account, "") if account else "",
            "seconds": round(max(0.0, now - since), 1) if since else 0.0,
        }

    lanes, holders, waiters = [], [], []
    for raw in snapshot.get("lanes") or []:
        if not isinstance(raw, dict):
            continue
        lane = str(raw.get("lane") or "")
        held = [row(lane, i + 1, e) for i, e in enumerate(raw.get("holders") or [])]
        waiting = [row(lane, i + 1, e) for i, e in enumerate(raw.get("waiters") or [])]
        lanes.append(
            {
                "lane": lane,
                "limit": int(raw.get("limit") or 0),
                "paused": "paused" if raw.get("paused") else "",
                "held": len(held),
                "waiting": len(waiting),
            }
        )
        holders += held
        waiters += waiting
    return {
        "lanes": lanes,
        "holders": holders,
        "waiters": waiters,
        "paused_stories": [str(s) for s in snapshot.get("paused_stories") or []],
        "closing_stories": [str(s) for s in snapshot.get("closing_stories") or []],
        "error": "",
    }


def queue_page() -> Any:
    from engine.hosting.admin.guard import admin_account, take_done
    from engine.hosting.admin.metrics import QUEUE_WINDOW_HOURS, recent_waits
    from engine.hosting.admin.pages import render
    from engine.hosting.auth import form_token

    admin = admin_account()
    return render(
        "queue.html",
        admin=admin,
        csrf=form_token(admin),
        page="queue",
        data=queue_data(),
        # v0.20.0 T17: the recent waits' p50 and p95, from the metrics store.
        waits=recent_waits(),
        window=QUEUE_WINDOW_HOURS,
        message=take_done(),
    )


def register(blueprint: Any) -> None:
    """The Queue page and ``/admin/api/queue.json``, on the admin blueprint."""
    from flask import jsonify

    @blueprint.get("/queue")
    def queue() -> Any:
        return queue_page()

    @blueprint.get("/api/queue.json")
    def queue_json() -> Any:
        return jsonify(queue_data())


__all__ = ["queue_data", "register"]
