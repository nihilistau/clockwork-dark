"""
The Admin Panel: Stories
========================

``GET /admin/stories`` (v0.20.0 T15, spec §14.8): per story, its state
(spec §14.3: ``starting``, ``ready``, ``degraded``, ``draining``,
``restarting``, ``held_down``, ``stopped``), pid, loopback port, uptime,
crash restarts in the window, its last exit (code and when), when it was
held down, its live sessions, and the progress of its last operation
(``queued``, ``draining``, ``restarting``, ``done``, ``refused`` with the
reason). Read from the supervisor (``stories.list``, ``ops.list``,
``sessions.list``): the front door's own copy of the table carries only what
routing needs.

``POST /admin/stories/start``, ``/stop`` and ``/restart`` (the story in the
form) are the supervisor's OPERATIONS (spec §14.3): each answers AT ONCE,
with the operation's id -- no request waits for a drain -- by a 303 to the
page (fix round 1: a reload never queues it again), which shows its
progress. One whose bus reply never came (``timeout``) writes no outcome
row: the supervisor writes it, if the op was queued. One runs at a time ("another operation is running"). A stop
or restart DRAINS first: the story's new turns are paused in the model
server's queue, the turns already admitted finish, the ones still waiting are
answered busy (they never started, so nothing is lost), and only then is the
worker stopped. A drain that outlasts ``hosting.supervisor.drain_seconds``
changes nothing -- the story keeps serving, and the operation is shown
``refused`` ("turns are still running; the story was not stopped"). A stop
lasts until the next start or supervisor restart. A restart (or a start) of a
held-down story clears its hold, and a restart an admin chose is never
counted toward ``max_restarts``.

AUDITED ACROSS TWO PROCESSES (spec §14.11): the front door writes the
``started`` row BEFORE it sends the op (refusing it, with nothing sent, when
that row cannot be written), and passes the acting admin and the row's
``ref`` with it; the supervisor writes the outcome (``ok`` or ``refused``)
under the same ``ref`` when the operation is final. A refusal the supervisor
answers at once (another operation running, an unknown story) is written
here, as the outcome.

Telling the players of a stopped or restarted story is NOT WIRED (a client
event, v0.21.0; docs/GOVERNANCE.md): their tab gets the front door's "stopped
by the operator" or "restarting" answer, and their runs are on disk.

``GET /admin/api/stories.json``: the states and the last operations, for the
page's refresh script.

Version: v0.1.0 [2026-10-05]
"""

from __future__ import annotations

import logging
from typing import Any

from flask import jsonify, request

from engine.hosting import audit
from engine.hosting.admin.guard import admin_account
from engine.hosting.admin.pages import render
from engine.hosting.admin.sessions import actor, ask
from engine.hosting.auth import form_token, hosting_state

logger = logging.getLogger(__name__)

#: How long a story op's bus round trip may take: it is answered at once.
OP_SECONDS = 10.0

#: Each action: its bus op and its audit action.
ACTIONS = (
    ("start", "stories.start", "story.start"),
    ("stop", "stories.stop", "story.stop"),
    ("restart", "stories.restart", "story.restart"),
)

#: The bus codes that leave it unknown whether the op was queued.
UNANSWERED = frozenset({"timeout", "closed"})

#: What a refusal answered at once is told, by the bus's code.
OP_REFUSALS = (
    ("busy", 409, "another operation is running; wait for it to finish"),
    ("unknown_story", 404, "no such story"),
    ("shutting_down", 503, "the server is shutting down"),
)


def stories_data() -> dict[str, Any]:
    """Every story's row, its last operation and its live sessions; errors as text, never raised."""
    from engine.hosting.admin.sessions import sessions_data
    from engine.hosting.admin.users import when
    from engine.hosting.bus import BusError

    errors: list[str] = []
    try:
        table = [r for r in ask("stories.list").get("stories") or [] if r.get("role", "worker") == "worker"]
    except BusError as exc:
        table, errors = [], [f"the story table could not be read ({exc.code})"]
    try:
        operations = ask("ops.list").get("ops") or []
    except BusError as exc:
        operations, errors = [], errors + [f"the operations could not be read ({exc.code})"]
    last: dict[str, dict[str, Any]] = {}
    for op in operations:
        last[str(op.get("slug") or "")] = op
    sessions = sessions_data(1, 0)
    rows = []
    for raw in table:
        slug = str(raw.get("slug") or "")
        op = last.get(slug) or {}
        last_exit = raw.get("last_exit")
        rows.append(
            {
                "slug": slug,
                "state": str(raw.get("state") or ""),
                "pid": int(raw.get("pid") or 0),
                "port": int(raw.get("port") or 0),
                "uptime": int(float(raw.get("uptime") or 0)),
                "restarts": int(raw.get("restarts") or 0),
                "last_exit": "" if last_exit is None else int(last_exit),
                "last_exit_at": when(float(raw.get("last_exit_at") or 0), seconds=True) if raw.get("last_exit_at") else "",
                "held_down_at": when(float(raw.get("held_down_at") or 0), seconds=True) if raw.get("held_down_at") else "",
                "sessions": sessions["stories"].get(slug, ""),
                "op": str(op.get("kind") or "").replace("stories.", ""),
                "op_id": str(op.get("op_id") or ""),
                "op_status": str(op.get("status") or ""),
                "op_reason": str(op.get("reason") or ""),
                "op_by": str(op.get("actor") or ""),
            }
        )
    return {"stories": rows, "errors": errors}


def stories_page(message: str = "", status: int = 200) -> Any:
    from engine.hosting.admin.guard import take_done

    admin = admin_account()
    message = message or take_done()
    return (
        render(
            "stories.html",
            admin=admin,
            csrf=form_token(admin),
            page="stories",
            data=stories_data(),
            message=message,
        ),
        status,
    )


def _operate(action: str, op_name: str, audit_action: str) -> Any:
    """One story operation: the started row, the op sent, its id at once (see the module docstring)."""
    from engine.hosting.bus import BusError

    slug = str(request.form.get("slug", "") or "")
    who = actor()
    if slug not in hosting_state().settings.stories:
        audit.refused(audit_action, actor=who, target=slug[:64])
        return stories_page(f"Not done: no story {slug[:64]!r} here.", 404)
    ref = audit.new_ref()
    try:
        audit.append(audit_action, actor=who, result=audit.STARTED, target=slug, ref=ref)
    except audit.AuditUnavailable:
        return stories_page(audit.UNAVAILABLE, 503)
    try:
        reply = ask(
            op_name,
            {"slug": slug, "actor": who.id, "actor_name": who.name, "address": who.address[:64], "ref": ref},
            timeout=OP_SECONDS,
        )
    except BusError as exc:
        if exc.code in UNANSWERED:
            # Fix round 1 (M3): the op may have been queued and its answer
            # lost; the supervisor then writes its outcome under this ref,
            # so no outcome is written here (one outcome per reference). One
            # never queued leaves a started row with no outcome, which the
            # audit log allows (a process gone mid-action).
            logger.warning(
                "[admin] A story operation went unanswered (operation=%s, story=%s, error=%s)", op_name, slug, exc.code
            )
            return stories_page(f"Not confirmed: the supervisor did not answer ({exc.code}); see the operations below.", 504)
        try:
            audit.append(audit_action, actor=who, result=audit.REFUSED, target=slug, detail={"error": exc.code}, ref=ref)
        except audit.AuditUnavailable:
            pass  # logged; the started row stands
        for code, status, text in OP_REFUSALS:
            if exc.code == code:
                return stories_page(f"Not done: {text}.", status)
        return stories_page(f"Not done: the supervisor answered {exc.code}.", 502)
    op_id = str(reply.get("op_id") or "")
    logger.info("[admin] Story operation queued (operation=%s, story=%s, op_id=%s, by=%s)", op_name, slug, op_id, who.id)
    drains = "" if action == "start" else " It drains first: the turns already running finish."
    # POST-redirect-GET (fix round 1, M6): a reload never queues it again.
    from engine.hosting.admin.guard import done_redirect

    return done_redirect(
        "/admin/stories", f"{action.capitalize()} of {slug} queued as {op_id}.{drains} Its progress is below."
    )


def register(blueprint: Any) -> None:
    """The Stories page, its JSON and the three operations, on the admin blueprint."""

    @blueprint.get("/stories")
    def stories() -> Any:
        return stories_page()

    @blueprint.get("/api/stories.json")
    def stories_json() -> Any:
        data = stories_data()
        keys = ("slug", "state", "restarts", "sessions", "op", "op_status")
        return jsonify({"stories": [{k: row[k] for k in keys} for row in data["stories"]], "errors": data["errors"]})

    for action, op_name, audit_action in ACTIONS:

        def view(op_name: str = op_name, audit_action: str = audit_action, action: str = action) -> Any:
            return _operate(action, op_name, audit_action)

        blueprint.add_url_rule(f"/stories/{action}", f"stories_{action}", view, methods=["POST"])


__all__ = ["ACTIONS", "OP_REFUSALS", "register", "stories_data", "stories_page"]
