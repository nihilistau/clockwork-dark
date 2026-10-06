"""
The Admin Panel: Sessions
=========================

``GET /admin/sessions`` lists every story's live sessions (v0.20.0 T15, spec
§14.8): the front door asks the supervisor (``sessions.list``), which fans
the request out to every serving worker, a page at a time (``PAGE_ROWS``,
``?page=``). Per live session: the story, the owner's NAME (resolved here,
from ``users.json``; the bus carries only the account id), a short reference
(the full session id travels only in the end form), the save as a stable
hash (``save_ref``, fix round 1: a save id may be one the player chose, so
it is never printed), created, last activity, the turn count, whether a turn is running, and the sockets in
its room. NEVER the player's name, place, day or anything else from the
state (AGENTS.md rule 12: the panel observes the service and moderates
nothing). A story whose worker did not answer, or whose page would not fit
one bus frame (``too_large``), is an error row; so is a whole reply that
would not, and the page is still served.

``POST /admin/sessions/end`` (the story and the session id in the form) ends
one: audited write-first (``session.end``, the session id its target), sent
to that story's worker (``sessions.end``), which releases it through
``SessionStore.delete`` and the release hook (its Socket.IO room closed). It
is REFUSED while the session's turn lock is held ("a turn is running; try
again in a moment"): a turn is never cut mid-flight. The player's tab goes
quiet -- telling them is NOT WIRED (a client event, v0.21.0;
docs/GOVERNANCE.md) -- and their run is on disk.

``GET /admin/api/sessions.json``: the counts per story, for the page's
refresh script (read-only; the table with its forms is as served).

``end_owner(account_id)`` is the Users page's: a disable or a delete ends the
account's live sessions in every story (``sessions.end_owner``).

Version: v0.1.0 [2026-10-05]
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import re
import secrets
from typing import Any, Optional

from flask import jsonify, request

from engine.hosting import audit
from engine.hosting.admin.guard import admin_account
from engine.hosting.admin.pages import render
from engine.hosting.auth import form_token, hosting_state

logger = logging.getLogger(__name__)

#: Rows per page.
PAGE_ROWS = 50

#: How long the panel waits for the supervisor's fan-out (the workers are
#: asked at once, within ``supervisor.server.FANOUT_SECONDS`` all told).
BUS_SECONDS = 30.0

#: The characters of a session id the page shows as its reference.
REF_CHARS = 6

#: A session id as the end form may carry it (``SAVE_ID_RE``'s shape).
_SESSION_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,64}")

#: A row's keys as the page carries them, exactly (metadata only). The save
#: appears only as ``save_ref`` (fix round 1, M2): a save id can be one the
#: player chose, so it is player text, shown as a stable hash like a label
#: would be (``save_ref``), never verbatim.
ROW_KEYS = (
    "story",
    "owner",
    "owner_name",
    "ref",
    "session_id",
    "save_ref",
    "created",
    "last_activity",
    "turns",
    "turn_running",
    "sockets",
)

#: What each refusal of ``sessions.end`` is told, by the bus's code.
END_REFUSALS = (
    ("busy", 409, "Not ended: a turn is running; try again in a moment."),
    ("not_found", 404, "Not ended: that session is no longer live."),
    ("unavailable", 503, "Not ended: that story is not serving now."),
    ("unknown_story", 404, "Not ended: no such story."),
)


class EndRefused(Exception):
    """``sessions.end`` was refused (its bus code)."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


#: Hex digits of a ``save_ref``.
SAVE_REF_CHARS = 10


#: The key ``save_ref`` is computed with: random, made once per front door
#: process and never stored or shown (fix round 2, N5). An unkeyed hash of a
#: short id a player typed could be reversed with a dictionary; a keyed one
#: cannot, by anyone without this process's memory. A front door restart
#: changes every reference, which matters to nobody: they are matched on one
#: screen, never written down.
_SAVE_REF_KEY = secrets.token_bytes(32)


def save_ref(save_id: str) -> str:
    """
    A save id as the panel shows it (fix round 1, M2; keyed in round 2, N5):
    the first ``SAVE_REF_CHARS`` hex digits of its HMAC-SHA-256 under this
    process's ``_SAVE_REF_KEY``, stable for one save and the same on the
    Sessions and Saves pages, so an admin can match them without the panel
    ever printing -- or letting anyone recover -- an id a player may have
    typed. "" for none.
    """
    if not save_id:
        return ""
    return hmac.new(_SAVE_REF_KEY, save_id.encode("utf-8"), hashlib.sha256).hexdigest()[:SAVE_REF_CHARS]


def bus() -> Any:
    """The front door's bus client."""
    from engine.hosting.frontdoor import frontdoor

    return frontdoor().bus


def ask(op: str, args: Optional[dict[str, Any]] = None, timeout: float = BUS_SECONDS) -> dict[str, Any]:
    """``op`` to the supervisor; raises ``BusError`` (its code) when refused or unanswered."""
    return bus().request(op, args or {}, timeout=timeout)


def actor() -> audit.Actor:
    """The acting admin, as the audit log records them."""
    account = admin_account()
    return audit.Actor(account.id, account.name, str(request.remote_addr or ""))


def page_number() -> int:
    try:
        return max(1, min(100000, int(request.args.get("page", "1") or "1")))
    except ValueError:
        return 1


def sessions_data(number: int = 1, limit: int = PAGE_ROWS) -> dict[str, Any]:
    """One page of live sessions, with each owner's name; errors as rows, never raised."""
    from engine.hosting.bus import BusError

    names = {account.id: account.name for account in hosting_state().accounts.all()}
    try:
        reply = ask("sessions.list", {"limit": int(limit), "offset": (number - 1) * int(limit)})
    except BusError as exc:
        logger.warning("[admin] The sessions list could not be read (operation=sessions.list, error=%s)", exc.code)
        return {"rows": [], "total": 0, "stories": {}, "errors": [{"story": "", "error": exc.code}], "page": number, "more": False}
    rows = []
    for raw in reply.get("rows") or []:
        session_id = str(raw.get("session_id") or "")
        owner = str(raw.get("owner") or "")
        rows.append(
            {
                "story": str(raw.get("story") or ""),
                "owner": owner,
                "owner_name": names.get(owner, "(no account)"),
                "ref": session_id[:REF_CHARS],
                "session_id": session_id,
                "save_ref": save_ref(str(raw.get("save_id") or "")),
                "created": float(raw.get("created") or 0.0),
                "last_activity": float(raw.get("last_activity") or 0.0),
                "turns": int(raw.get("turns") or 0),
                "turn_running": bool(raw.get("turn_running")),
                "sockets": int(raw.get("sockets") or 0),
            }
        )
    total = int(reply.get("total") or 0)
    errors = [
        {"story": str(e.get("story") or ""), "error": str(e.get("error") or "")}
        for e in reply.get("errors") or []
        if isinstance(e, dict)
    ]
    stories = {str(k): int(v) for k, v in (reply.get("stories") or {}).items()}
    return {
        "rows": rows,
        "total": total,
        "stories": stories,
        "errors": errors,
        "page": number,
        "more": number * int(limit) < total,
    }


def live_by_owner(limit: int = 200) -> tuple[dict[str, int], bool]:
    """
    Live sessions per account id, for the Users page, from the first
    ``limit`` sessions; and whether that is all of them. ``({}, False)`` when
    the list cannot be read.
    """
    data = sessions_data(1, limit)
    if data["errors"] and not data["rows"]:
        return {}, False
    counts: dict[str, int] = {}
    for row in data["rows"]:
        counts[row["owner"]] = counts.get(row["owner"], 0) + 1
    return counts, len(data["rows"]) >= data["total"] and not data["errors"]


def end_owner(account_id: str) -> dict[str, Any]:
    """
    End ``account_id``'s live sessions in every story (a disable or delete):
    ``{"ended", "busy"}``, or ``{"sessions_error": code}`` when the
    supervisor could not be asked. Never raises.
    """
    from engine.hosting.bus import BusError

    try:
        reply = ask("sessions.end_owner", {"account": account_id})
    except BusError as exc:
        logger.warning(
            "[admin] An account's sessions were not ended (operation=sessions.end_owner, account=%s, error=%s)",
            account_id,
            exc.code,
        )
        return {"sessions_error": exc.code}
    result = {"sessions_ended": int(reply.get("ended") or 0), "sessions_busy": int(reply.get("busy") or 0)}
    if reply.get("errors"):
        result["sessions_error"] = ",".join(sorted({str(e.get("error")) for e in reply["errors"]}))[: audit.MAX_TEXT]
    return result


def when(stamp: float) -> str:
    from engine.hosting.admin.users import when as shown

    return shown(stamp, seconds=True) if stamp else ""


def sessions_page(message: str = "", status: int = 200) -> Any:
    from engine.hosting.admin.guard import take_done

    admin = admin_account()
    message = message or take_done()
    number = page_number()
    data = sessions_data(number)
    for row in data["rows"]:
        row["created_text"] = when(row["created"])
        row["last_activity_text"] = when(row["last_activity"])
    return (
        render(
            "sessions.html",
            admin=admin,
            csrf=form_token(admin),
            page="sessions",
            data=data,
            number=number,
            message=message,
        ),
        status,
    )


def register(blueprint: Any) -> None:
    """The Sessions page, its JSON and the end action, on the admin blueprint."""
    from engine.hosting.bus import BusError

    @blueprint.get("/sessions")
    def sessions() -> Any:
        return sessions_page()

    @blueprint.get("/api/sessions.json")
    def sessions_json() -> Any:
        data = sessions_data(1, 0)
        return jsonify(
            {
                "total": data["total"],
                "stories": [{"slug": slug, "sessions": count} for slug, count in sorted(data["stories"].items())],
                "errors": data["errors"],
            }
        )

    @blueprint.post("/sessions/end")
    def sessions_end() -> Any:
        slug = str(request.form.get("slug", "") or "")
        session_id = str(request.form.get("session_id", "") or "")
        who = actor()
        if slug not in hosting_state().settings.stories or not _SESSION_ID_RE.fullmatch(session_id):
            audit.refused("session.end", actor=who, target=session_id[:64], detail={"story": slug[:64]})
            return sessions_page("Not ended: no such session.", 400)
        try:
            with audit.audited(
                "session.end", session_id, actor=who, detail={"story": slug}, refusals=(EndRefused,)
            ):
                try:
                    ask("sessions.end", {"slug": slug, "session_id": session_id})
                except BusError as exc:
                    raise EndRefused(exc.code) from None
        except audit.AuditUnavailable:
            return sessions_page(audit.UNAVAILABLE, 503)
        except EndRefused as refusal:
            for code, status, text in END_REFUSALS:
                if refusal.code == code:
                    return sessions_page(text, status)
            return sessions_page(f"Not ended: the supervisor answered {refusal.code}.", 502)
        logger.info(
            "[admin] Session ended (operation=session.end, story=%s, id=%s, by=%s)", slug, session_id, who.id
        )
        # POST-redirect-GET (fix round 1, M6): a reload never ends it again.
        from engine.hosting.admin.guard import done_redirect

        return done_redirect(
            "/admin/sessions", f"Ended session {session_id[:REF_CHARS]} in {slug}. The player's run is on disk."
        )


__all__ = [
    "END_REFUSALS",
    "PAGE_ROWS",
    "REF_CHARS",
    "ROW_KEYS",
    "ask",
    "end_owner",
    "live_by_owner",
    "register",
    "sessions_data",
    "sessions_page",
]
