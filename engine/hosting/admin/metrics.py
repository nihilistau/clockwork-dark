"""
The Admin Panel: Metrics and Errors
===================================

v0.20.0 T17, spec §14.10. OBSERVABILITY, NOT MODERATION (AGENTS.md rule 12):
both pages show how the service ran -- timings, waits, counts, and errors by
reference -- and nothing of what was played. Every value comes from the
supervisor's metrics store through a NAMED query (``metrics.query``, never
SQL; ``engine/hosting/supervisor/metrics.py``) or from a story's Oracle
through its projection (``oracle.snapshot``; ``metrics_schema.project_oracle``),
so what can reach these pages is the closed schema's: timestamps, numbers,
account ids (whose names are resolved here from ``users.json``), slugs,
process names, references, exception class names, logger names and enum
members.

- ``GET /admin/metrics``: turn duration p50/p95 per story and hour, the
  admission and lane waits, busy and error counts per story and hour,
  per-account usage per day (turns, sessions, active days, a page at a time),
  and each story's Oracle numbers (where ``/api/metrics``' went: hosted mode
  answers that route 404, spec §6.7);
- ``GET /admin/errors``: the recent ``error`` rows, newest first, a page at a
  time -- a player's ``ref`` is found here, and its full traceback read in
  that process's log file on disk (``<storage.root>/hosting/logs/
  <process>.log``), which the panel never shows -- the metrics the store
  rejected or dropped, and the recent ``process`` events;
- ``GET /admin/errors/find?ref=3fa9c2e1`` (fix round 1, M5): the one error
  with that reference;
- ``GET /admin/api/metrics.json`` and ``/admin/api/errors.json``: the same.

Fix round 1 also shows the refusals counted per minute (``refusals``), the
metrics dropped by rate, by size and by each child (its ``health`` reply),
and the usage window actually in force (the retention, when shorter than 30
days).

``query`` is also what the Queue page (the recent waits' p50/p95) and the
Users page (each account's last login) read.

Version: v0.2.0 [2026-10-06]
"""

from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

#: Rows per page (the usage table, the errors).
PAGE_ROWS = 50

#: Rows of each hourly table shown (the newest first).
HOUR_ROWS = 48

#: How long a page waits for the supervisor.
BUS_SECONDS = 10.0

#: The window the Metrics page reads, in hours.
WINDOW_HOURS = 24

#: The usage table's window, in days (or the retention, when shorter).
USAGE_DAYS = 30

#: The Queue page's window for its recent waits, in hours.
QUEUE_WINDOW_HOURS = 1

#: The most pages of last logins the Users page reads (``MAX_PAGE`` rows each).
LAST_LOGIN_PAGES = 5


def query(
    name: str, *, hours: Optional[int] = None, limit: int = PAGE_ROWS, offset: int = 0, ref: Optional[str] = None
) -> dict[str, Any]:
    """
    One named query's page from the supervisor: ``{"rows", "total", "error"}``.
    Never raises: a refusal or no answer is ``error`` (its code), no rows.
    """
    from engine.hosting.admin.sessions import ask
    from engine.hosting.bus import BusError

    args: dict[str, Any] = {"name": name, "limit": int(limit), "offset": int(offset)}
    params: dict[str, Any] = {}
    if hours is not None:
        params["hours"] = int(hours)
    if ref is not None:
        params["ref"] = ref
    if params:
        args["params"] = params
    try:
        reply = ask("metrics.query", args, timeout=BUS_SECONDS)
    except BusError as exc:
        logger.warning("[admin] A metrics query was not answered (operation=metrics.query, name=%s, error=%s)", name, exc.code)
        return {"rows": [], "total": 0, "error": exc.code}
    rows = [row for row in reply.get("rows") or [] if isinstance(row, dict)]
    return {"rows": rows, "total": int(reply.get("total") or 0), "error": ""}


def _names() -> dict[str, str]:
    from engine.hosting.auth import hosting_state

    return {account.id: account.name for account in hosting_state().accounts.all()}


def _when(stamp: Any, *, seconds: bool = True) -> str:
    from engine.hosting.admin.users import when

    return when(float(stamp or 0.0), seconds=seconds) if stamp else ""


def _day(stamp: Any) -> str:
    return _when(stamp, seconds=False)[:10]


def oracle_rows() -> list[dict[str, Any]]:
    """Each story's Oracle numbers (the projection), or its error code."""
    from engine.hosting.admin.sessions import ask
    from engine.hosting.bus import BusError
    from engine.hosting.frontdoor import frontdoor

    rows = []
    for story in frontdoor().table.rows():
        slug = str(story.get("slug", ""))
        try:
            oracle = ask("oracle.snapshot", {"slug": slug}, timeout=BUS_SECONDS).get("oracle") or {}
            error = ""
        except BusError as exc:
            oracle, error = {}, exc.code
        rows.append({"story": slug, "oracle": oracle, "error": error})
    return rows


def usage_days() -> int:
    """The usage table's window, in days: ``USAGE_DAYS``, or the retention in force when shorter (M8)."""
    from engine.hosting.auth import hosting_state

    return max(1, min(USAGE_DAYS, int(hosting_state().settings.retention_days)))


def metrics_data(number: int = 1) -> dict[str, Any]:
    """What the Metrics page shows (see the module docstring). Never raises."""
    names = _names()
    days = usage_days()
    durations = query("turn_durations", hours=WINDOW_HOURS, limit=HOUR_ROWS)
    waits = query("waits", hours=WINDOW_HOURS, limit=PAGE_ROWS)
    outcomes = query("outcomes", hours=WINDOW_HOURS, limit=HOUR_ROWS)
    refusals = query("refusals", hours=WINDOW_HOURS, limit=HOUR_ROWS)
    usage = query("usage", hours=days * 24, limit=PAGE_ROWS, offset=(number - 1) * PAGE_ROWS)
    for row in durations["rows"] + outcomes["rows"] + refusals["rows"]:
        row["hour"] = _when(row.get("hour"), seconds=False)
    for row in usage["rows"]:
        row["day"] = _day(row.get("day"))
        row["name"] = names.get(str(row.get("account") or ""), "")
    errors = sorted({r["error"] for r in (durations, waits, outcomes, refusals, usage) if r["error"]})
    return {
        "window_hours": WINDOW_HOURS,
        "usage_days": days,
        "durations": durations["rows"],
        "waits": waits["rows"],
        "outcomes": outcomes["rows"],
        "refusals": refusals["rows"],
        "usage": usage["rows"],
        "usage_total": usage["total"],
        "page": number,
        "more": number * PAGE_ROWS < usage["total"],
        "oracle": oracle_rows(),
        "errors": errors,
    }


def errors_data(number: int = 1, ref: Optional[str] = None) -> dict[str, Any]:
    """
    What the Errors page shows. Never raises. ``ref`` (fix round 1, M5): only
    the error row with that reference, when it is one (8 hex digits); a
    malformed one asks nothing and says so.
    """
    from engine.hosting.metrics_schema import REF_PATTERN

    looked = ""
    if ref is not None:
        ref = ref.strip().lower()
        if not REF_PATTERN.fullmatch(ref):
            looked, ref = "not a reference (8 hex digits, as the player saw it)", None
            recent = {"rows": [], "total": 0, "error": ""}
        else:
            recent = query("recent_errors", limit=PAGE_ROWS, ref=ref)
            looked = "" if recent["rows"] else "no error kept with that reference"
    else:
        recent = query("recent_errors", limit=PAGE_ROWS, offset=(number - 1) * PAGE_ROWS)
    rejected = query("metrics_rejected", limit=1)
    processes = query("recent_processes", limit=PAGE_ROWS)
    for row in recent["rows"] + processes["rows"]:
        row["when"] = _when(row.get("ts"))
    counts = rejected["rows"][0] if rejected["rows"] else {}
    children = counts.get("children") if isinstance(counts.get("children"), dict) else {}
    errors = sorted({r["error"] for r in (recent, rejected, processes) if r["error"]})
    return {
        "errors_rows": recent["rows"],
        "errors_total": recent["total"],
        "page": number,
        "more": ref is None and number * PAGE_ROWS < recent["total"],
        "ref": ref or "",
        "looked": looked,
        "rejected": int(counts.get("rejected") or 0),
        "dropped": int(counts.get("dropped") or 0),
        "dropped_rate": int(counts.get("dropped_rate") or 0),
        "dropped_size": int(counts.get("dropped_size") or 0),
        "children": [{"process": str(p), "dropped": int(n or 0)} for p, n in sorted(children.items())],
        "processes": processes["rows"],
        "errors": errors,
    }


def recent_waits() -> dict[str, Any]:
    """The Queue page's recent waits (``QUEUE_WINDOW_HOURS``): admission and each lane, p50/p95."""
    found = query("waits", hours=QUEUE_WINDOW_HOURS, limit=PAGE_ROWS)
    return {"rows": found["rows"], "error": found["error"]}


def last_logins() -> tuple[dict[str, float], bool]:
    """Each account's last successful login (wall time), and whether it could be read."""
    from engine.hosting.bus import MAX_METRICS_PAGE as MAX_PAGE

    found: dict[str, float] = {}
    for page in range(LAST_LOGIN_PAGES):
        reply = query("last_login", limit=MAX_PAGE, offset=page * MAX_PAGE)
        if reply["error"]:
            return found, False
        for row in reply["rows"]:
            found[str(row.get("account") or "")] = float(row.get("ts") or 0.0)
        if (page + 1) * MAX_PAGE >= reply["total"]:
            break
    return found, True


def register(blueprint: Any) -> None:
    """The Metrics and Errors pages and their JSON, on the admin blueprint."""
    from flask import jsonify

    from engine.hosting.admin.guard import admin_account
    from engine.hosting.admin.pages import render
    from engine.hosting.admin.sessions import page_number
    from engine.hosting.auth import form_token

    def page(name: str, **context: Any) -> str:
        admin = admin_account()
        return render(name, admin=admin, csrf=form_token(admin), **context)

    @blueprint.get("/metrics")
    def metrics_page() -> Any:
        return page("metrics.html", page="metrics", data=metrics_data(page_number()))

    @blueprint.get("/api/metrics.json")
    def metrics_json() -> Any:
        return jsonify(metrics_data(page_number()))

    @blueprint.get("/errors")
    def errors_page() -> Any:
        return page("errors.html", page="errors", data=errors_data(page_number()))

    @blueprint.get("/api/errors.json")
    def errors_json() -> Any:
        return jsonify(errors_data(page_number()))

    @blueprint.get("/errors/find")
    def errors_find() -> Any:
        # Fix round 1 (M5): one error by the reference a player quotes.
        from flask import jsonify, request

        from engine.hosting.admin.guard import admin_state
        from engine.hosting.limits import ADMIN_SLOW_DOWN

        # A lookup an admin can repeat as fast as a script can ask (v0.20.0
        # T18): spent from the same bucket as the panel's actions.
        if not admin_state().actions.allow(admin_account().id):
            return jsonify({"error": ADMIN_SLOW_DOWN}), 429
        ref = str(request.args.get("ref", "") or "")[:64]
        return page("errors.html", page="errors", data=errors_data(1, ref=ref))


__all__ = ["errors_data", "last_logins", "metrics_data", "query", "recent_waits", "register"]
