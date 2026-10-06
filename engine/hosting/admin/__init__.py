"""
The Admin Panel
===============

``/admin`` on the front door (spec §14.7): server-rendered pages, one
stylesheet and one small script, no build step and nothing from ``ui/``
(the React client's overhaul is v0.21.0's; a panel inside it is NOT WIRED,
docs/GOVERNANCE.md). Mounted by the front door ONLY
(``engine/hosting/frontdoor/__init__.py``); a worker's URL map has no
``/admin`` rule.

OBSERVABILITY AND ADMINISTRATION, NOTHING ELSE (AGENTS.md rule 12): the panel
shows how the service runs and administers its accounts. It shows no play
text, rates nothing and moderates nothing.

``admin_blueprint()`` builds the blueprint:

- the guard (``guard.py``), registered with ``before_app_request`` and keyed
  by the path, over EVERY ``/admin`` path: login, the admin role,
  ``must_change``, the re-auth, and on every state-changing request the
  Origin, the CSRF token and the admin actions bucket; and the five response
  headers (``after_app_request``);
- ``GET /admin``: the Overview (the stories and their states, from the front
  door's story table; the accounts and admins counted);
- ``GET /admin/api/overview.json``: the same, for the page's refresh script;
- ``GET``/``POST /admin/reauth`` (``guard.py``);
- the Users page and its actions (``users.py``);
- ``GET /admin/audit``: the audit log, newest first, 50 rows a page, filtered
  by action or actor, read from a bounded tail of the current and rotated
  files, back at most ``audit.AUDIT_MAX_ROWS`` rows (``engine/hosting/audit.py``);
- the Sessions page, its end action and ``/admin/api/sessions.json``
  (``sessions.py``), the Saves page (``saves.py``: each store's
  ``index.json`` through an allowlisted projection, never a save's
  contents), and the Stories page, its start, stop and restart operations and
  ``/admin/api/stories.json`` (``stories.py``), v0.20.0 T15;
- the Model server page, its apply and ``/admin/api/health.json``
  (``model.py``), and the Queue page and ``/admin/api/queue.json``
  (``queue.py``), v0.20.0 T16. ``model.EDITABLE`` is also what the config
  reads to check the admin layer;
- the Metrics and Errors pages and ``/admin/api/metrics.json`` and
  ``/admin/api/errors.json`` (``metrics.py``, v0.20.0 T17): the supervisor's
  metrics store through its named queries, and each story's Oracle through
  its projection -- timings, waits, counts and errors by reference, nothing
  of what was played;
- ``/admin/<path:rest>``, every method: 404 AFTER the guard, so an unknown
  admin path meets the admin checks and never reaches a worker (spec §14.5).

Version: v0.4.0 [2026-10-06]
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

#: The Audit page's rows per page.
AUDIT_PAGE_ROWS = 50

#: The panel's own static files (``/admin/static/...``).
_STATIC = Path(__file__).resolve().parent / "static"


def _overview_data() -> dict[str, Any]:
    """What the Overview shows: metadata only (story states, account counts)."""
    from engine.hosting.auth import hosting_state
    from engine.hosting.frontdoor import frontdoor

    accounts = hosting_state().accounts.all()
    stories = [
        {"slug": str(row.get("slug", "")), "state": str(row.get("state", ""))}
        for row in frontdoor().table.rows()
    ]
    return {
        "stories": stories,
        "accounts": len(accounts),
        "admins": sum(1 for a in accounts if a.admin and not a.disabled),
        "disabled": sum(1 for a in accounts if a.disabled),
    }


def admin_blueprint() -> Any:
    """Build the admin blueprint (a factory, like every blueprint here)."""
    from flask import Blueprint, abort, jsonify, request

    from engine.hosting import audit
    from engine.hosting.admin import guard, users
    from engine.hosting.admin.pages import render
    from engine.hosting.auth import form_token

    blueprint = Blueprint(
        guard.BLUEPRINT_NAME,
        __name__,
        url_prefix="/admin",
        static_folder=str(_STATIC),
        static_url_path="/static",
    )
    blueprint.before_app_request(guard.guard)
    blueprint.after_app_request(guard.headers)

    def page(name: str, **context: Any) -> str:
        admin = guard.admin_account()
        return render(name, admin=admin, csrf=form_token(admin), **context)

    @blueprint.get("")
    def overview() -> Any:
        return page("overview.html", page="overview", data=_overview_data())

    @blueprint.get("/api/overview.json")
    def overview_json() -> Any:
        return jsonify(_overview_data())

    @blueprint.get("/audit")
    def audit_page() -> Any:
        action = str(request.args.get("action", "") or "")
        actor = str(request.args.get("actor", "") or "")
        if action and action not in audit.ACTIONS:
            action = ""
        try:
            number = max(1, min(audit.AUDIT_MAX_ROWS // AUDIT_PAGE_ROWS, int(request.args.get("page", "1") or "1")))
        except ValueError:
            number = 1
        rows, unsearched = audit.read_tail(
            AUDIT_PAGE_ROWS + 1,
            (number - 1) * AUDIT_PAGE_ROWS,
            action=action or None,
            actor=actor[:64] or None,
        )
        from engine.hosting.admin.users import when

        shown = [{**row, "when": when(row["ts"], seconds=True)} for row in rows[:AUDIT_PAGE_ROWS]]
        return page(
            "audit.html",
            page="audit",
            rows=shown,
            more=len(rows) > AUDIT_PAGE_ROWS,
            unsearched=unsearched,
            number=number,
            action=action,
            actor=actor[:64],
            actions=sorted(audit.ACTIONS),
        )

    guard.register_reauth(blueprint)
    users.register(blueprint)
    # v0.20.0 T15: live sessions, saves (metadata only) and story operations.
    from engine.hosting.admin import saves as saves_page, sessions as sessions_page, stories as stories_page

    sessions_page.register(blueprint)
    saves_page.register(blueprint)
    stories_page.register(blueprint)
    # v0.20.0 T16: the model server (health, keys, the apply) and the queue.
    from engine.hosting.admin import model as model_page, queue as queue_page

    model_page.register(blueprint)
    queue_page.register(blueprint)
    # v0.20.0 T17: metrics and errors, metadata only.
    from engine.hosting.admin import metrics as metrics_page

    metrics_page.register(blueprint)

    def unknown(rest: str = "") -> Any:
        # Only ever reached past the guard: an admin asking for a page that
        # does not exist. Never proxied to a worker.
        abort(404)

    blueprint.add_url_rule(
        "/<path:rest>",
        "unknown",
        unknown,
        methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        provide_automatic_options=False,
    )
    return blueprint


def install(app: Any) -> None:
    """Mount the panel on the front door's ``app`` (its hosting state already in place)."""
    from engine.hosting.admin.guard import install_state

    install_state(app)
    app.register_blueprint(admin_blueprint())


__all__ = ["AUDIT_PAGE_ROWS", "admin_blueprint", "install"]
