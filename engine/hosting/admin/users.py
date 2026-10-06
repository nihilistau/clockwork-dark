"""
The Admin Panel: Users
======================

``GET /admin/users`` lists every account (spec §14.8): name, id, created,
admin, disabled, ``must_change`` and live sessions (v0.20.0 T15: counted from
the first page of the supervisor's ``sessions.list``, "?" when it cannot be
read). The last login (T17) is not shown yet. Each action is a ``POST`` form, goes through
``engine/hosting/accounts.py`` (the one writer of ``users.json``) and is
audited WRITE-FIRST (``audit.audited``: the ``started`` row before the
change, the action refused with an error page if it cannot be written, the
outcome after with the same ``ref``; a refusal before starting is one
``refused`` row):

- ``POST /admin/users`` (create: a name) and ``POST
  /admin/users/<id>/reset``: a one-time password is generated
  (``accounts.generate_password``) and its owner must replace it at first
  login (``must_change``). It is shown ONCE, by POST-redirect-GET (fix round
  1, M3): the ``POST`` keeps it in ``OneTimeShown`` -- this front door's
  memory, never a file -- under an unguessable token, puts only that token
  in the admin's session and answers 303 to ``GET /admin/users/once``, which
  takes it out and renders it (``password_once.html``); a reload of that
  page finds nothing and says the password was already shown, and never
  runs the reset again. The session keeps a list of tokens (fix round 2,
  N5), so two resets in two tabs each show their password once. The store
  is PER FRONT DOOR PROCESS: the shipped front door is one process (N6). The password itself never travels in a URL, the
  cookie (signed, not encrypted), a log line or an audit row. An admin never
  knows a player's real password;
- ``.../disable`` and ``.../enable``;
- ``.../grant-admin`` and ``.../revoke-admin``;
- ``.../delete``: the account's name typed to confirm, and ``keep`` (its
  ``<root>/users/<id>/`` stays; ids are never reissued) or ``purge`` (it is
  deleted). The account is disabled first, then removed (spec §14.8; fix
  round 1, M5), both in the one audited action.

A disable, a reset, a revoke and a delete end the account's logins (the
epoch, or the row, is gone), and the front door's revocation listener closes
its relayed WebSockets without waiting on them (``ws_relay.revoke``). A
disable and a delete also END ITS LIVE SESSIONS in every story (v0.20.0 T15,
``sessions.end_owner`` through the supervisor), inside the audited action,
whose outcome row counts them (``sessions_ended``, ``sessions_busy``, or
``sessions_error``). A session whose turn is running is left to finish: the
account's next request or event is refused by the gate, and the idle sweep
releases it.

THE GUARDS (spec §14.6): an admin cannot revoke their own role, or disable or
delete themselves, here; the last enabled admin cannot be demoted, disabled
or deleted. Checked first (one ``refused`` row) and again INSIDE the
accounts lock (``AccountStore._guard``), where two admins revoking each
other at once cannot both pass.

The page also shows each account's last successful login (v0.20.0 T17), from
the supervisor's metrics store (``admin/metrics.last_logins``).

Version: v0.4.0 [2026-10-06]
"""

from __future__ import annotations

import logging
import secrets
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from flask import abort, redirect, request, session

from engine.hosting import audit
from engine.hosting.accounts import (
    ID_RE,
    LAST_ADMIN,
    NOT_YOURSELF,
    Account,
    AccountError,
    LoginBusy,
    check_name,
    purge_user_dir,
)
from engine.hosting.admin.guard import admin_account
from engine.hosting.admin.pages import render
from engine.hosting.admin.sessions import end_owner
from engine.hosting.auth import form_token, hosting_state

logger = logging.getLogger(__name__)

#: Delete's two modes.
KEEP = "keep"
PURGE = "purge"

#: What a delete with purge is told while the account's sessions are not all
#: ended (fix round 1, I1): a turn still running, or a story that did not answer.
PURGE_WAITING = (
    "Not deleted: {name} has a turn still running, or a story did not answer, so their saves "
    "were not deleted. The account is disabled now; try the delete again in a moment."
)


def when(stamp: float, *, seconds: bool = False) -> str:
    """A timestamp as the panel shows it, in UTC."""
    try:
        moment = datetime.fromtimestamp(float(stamp), tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return "?"
    return moment.strftime("%Y-%m-%d %H:%M:%S" if seconds else "%Y-%m-%d %H:%M UTC")


def _actor() -> audit.Actor:
    account = admin_account()
    return audit.Actor(account.id, account.name, str(request.remote_addr or ""))


def users_page(message: str = "", status: int = 200) -> Any:
    """The Users page, with ``message`` above the list."""
    from engine.hosting.admin.guard import take_done
    from engine.hosting.admin.sessions import live_by_owner

    admin = admin_account()
    message = message or take_done()
    # Live sessions per account (v0.20.0 T15), counted from the first page of
    # the supervisor's list; "?" when it cannot be read.
    live, complete = live_by_owner()
    readable = bool(live) or complete
    # Each account's last successful login (v0.20.0 T17), from the metrics
    # store; "?" when it cannot be read, "" for none in the retention window.
    from engine.hosting.admin.metrics import last_logins

    logins, logins_read = last_logins()
    rows = [
        {
            "id": account.id,
            "name": account.name,
            "created": when(account.created),
            "admin": account.admin,
            "disabled": account.disabled,
            "must_change": account.must_change,
            "is_self": account.id == admin.id,
            "live": live.get(account.id, 0) if readable else "?",
            "last_login": (when(logins[account.id]) if account.id in logins else "") if logins_read else "?",
        }
        for account in hosting_state().accounts.all()
    ]
    return (
        render(
            "users.html",
            admin=admin,
            csrf=form_token(admin),
            rows=rows,
            message=message,
            page="users",
            live_complete=complete,
        ),
        status,
    )


#: The session key holding the token of the password waiting to be shown.
ONCE_KEY = "admin_once"

#: Where a generated password is shown, once.
ONCE_PATH = "/admin/users/once"


class OneTimeShown:
    """
    Generated passwords waiting to be shown once (fix round 1, M3), in this
    front door's memory only: ``token -> (admin id, deadline, view)``. A
    token is ``secrets.token_urlsafe(32)``; ``take`` hands a view only to the
    admin who made it, and only once; an entry not taken within
    ``TTL_SECONDS`` is dropped, and at most ``MAX_WAITING`` wait (the oldest
    go first). A restart of the front door forgets them all: the admin resets
    the password again.

    Thread-safe: one lock, a leaf (nothing is taken under it).
    """

    TTL_SECONDS = 600.0
    MAX_WAITING = 256

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._waiting: dict[str, tuple[str, float, dict[str, Any]]] = {}

    def _expire(self, now: float) -> None:
        for token in [t for t, (_a, deadline, _v) in self._waiting.items() if deadline <= now]:
            del self._waiting[token]
        while len(self._waiting) >= self.MAX_WAITING:
            del self._waiting[next(iter(self._waiting))]

    def put(self, admin_id: str, view: dict[str, Any]) -> str:
        """Keep ``view`` for ``admin_id``; its token."""
        token = secrets.token_urlsafe(32)
        now = time.monotonic()
        with self._lock:
            self._expire(now)
            self._waiting[token] = (str(admin_id), now + self.TTL_SECONDS, dict(view))
        return token

    def take(self, admin_id: str, token: Any) -> Optional[dict[str, Any]]:
        """The view kept under ``token`` for ``admin_id``, removed; None when gone or not theirs."""
        if not isinstance(token, str) or not token:
            return None
        with self._lock:
            self._expire(time.monotonic())
            found = self._waiting.get(token)
            if found is None or found[0] != str(admin_id):
                return None
            del self._waiting[token]
            return found[2]

    def __len__(self) -> int:
        with self._lock:
            return len(self._waiting)


def _password_once(account: Account, password: str, what: str) -> Any:
    """
    Keep the generated password for one showing and send the admin to it
    (303): the ``POST``'s answer carries no password, so a reload of the page
    that shows it can never re-run the action.
    """
    from engine.hosting.admin.guard import admin_state

    admin = admin_account()
    token = admin_state().shown.put(
        admin.id, {"name": account.name, "id": account.id, "password": password, "what": what}
    )
    # One token per POST, kept in a list (fix round 2, N5): two resets in two
    # tabs each keep theirs, and each GET shows one of them.
    waiting = [t for t in session.get(ONCE_KEY) or [] if isinstance(t, str)]
    session[ONCE_KEY] = (waiting + [token])[-MAX_TOKENS:]
    return redirect(ONCE_PATH, code=303)


#: Tokens one admin's session keeps waiting at most (``OneTimeShown`` holds
#: each for ``TTL_SECONDS``); past it the oldest token is dropped.
MAX_TOKENS = 16


def once_page() -> Any:
    """
    ``GET /admin/users/once``: the oldest waiting password of this admin's
    session, shown and forgotten; 'already shown' when none is left.
    """
    from engine.hosting.admin.guard import admin_state

    admin = admin_account()
    waiting = [t for t in session.get(ONCE_KEY) or [] if isinstance(t, str)]
    view = None
    while waiting and view is None:
        view = admin_state().shown.take(admin.id, waiting.pop(0))
    if waiting:
        session[ONCE_KEY] = waiting
    else:
        session.pop(ONCE_KEY, None)
    return (
        render("password_once.html", admin=admin, csrf=form_token(admin), view=view, page="users"),
        200,
    )


def _guard_refusal(target: Account, *, demoting: bool) -> str:
    """Spec §14.6's guards, checked before starting: the refusal's words, or ""."""
    admin = admin_account()
    if target.id == admin.id:
        return NOT_YOURSELF
    if demoting and target.admin and not target.disabled:
        enabled = [a.id for a in hosting_state().accounts.all() if a.admin and not a.disabled]
        if enabled == [target.id]:
            return LAST_ADMIN
    return ""


def _target(account_id: str) -> Account:
    """The account an action names, or 404 (an unknown or malformed id)."""
    if not ID_RE.fullmatch(str(account_id or "")):
        abort(404)
    found = hosting_state().accounts.get(account_id)
    if found is None:
        abort(404)
    return found


def _run(
    action: str,
    target: Account,
    change: Callable[[audit.Ticket], Any],
    *,
    detail: Optional[dict[str, Any]] = None,
    done: str,
) -> Any:
    """
    ``change`` under the write-first rule: the Users page with ``done``, or
    its refusal (409 a guard inside the lock, 503 the audit log unwritable).
    ``change`` may return a response of its own (the password page).
    """
    try:
        with audit.audited(action, target.id, actor=_actor(), detail=detail, refusals=(AccountError,)) as ticket:
            answer = change(ticket)
    except audit.AuditUnavailable:
        return users_page(audit.UNAVAILABLE, 503)
    except AccountError as exc:
        return users_page(f"Not changed: {exc}.", 409)
    except LoginBusy:
        return users_page("The server is busy hashing passwords. Try again in a moment.", 429)
    logger.info(
        "[admin] Account changed (operation=%s, account=%s, by=%s)", action, target.id, admin_account().id
    )
    if answer is not None:
        return answer
    # POST-redirect-GET (fix round 1, M6): a reload shows the list, never re-runs it.
    from engine.hosting.admin.guard import done_redirect

    return done_redirect("/admin/users", done)


def register(blueprint: Any) -> None:
    """The Users page and its actions, on the admin blueprint."""

    @blueprint.get("/users")
    def users() -> Any:
        return users_page()

    @blueprint.get("/users/once")
    def users_once() -> Any:
        return once_page()

    @blueprint.post("/users")
    def users_create() -> Any:
        name = str(request.form.get("name", "") or "").strip()
        actor = _actor()
        try:
            check_name(name)
        except AccountError as exc:
            audit.refused("account.create", actor=actor, detail={"name": name[:32]})
            return users_page(f"Not created: {exc}.", 400)
        accounts = hosting_state().accounts
        if accounts.by_name(name) is not None:
            audit.refused("account.create", actor=actor, detail={"name": name})
            return users_page(f"Not created: an account named {name!r} already exists.", 409)
        try:
            with audit.audited(
                "account.create", "", actor=actor, detail={"name": name}, refusals=(AccountError,)
            ) as ticket:
                account, password = accounts.create_with_generated_password(name)
                ticket.target = account.id
        except audit.AuditUnavailable:
            return users_page(audit.UNAVAILABLE, 503)
        except AccountError as exc:
            return users_page(f"Not created: {exc}.", 409)
        except LoginBusy:
            return users_page("The server is busy hashing passwords. Try again in a moment.", 429)
        logger.info("[admin] Account created (operation=account.create, account=%s, by=%s)", account.id, actor.id)
        return _password_once(account, password, "created")

    @blueprint.post("/users/<account_id>/reset")
    def users_reset(account_id: str) -> Any:
        target = _target(account_id)

        def change(_ticket: audit.Ticket) -> Any:
            account, password = hosting_state().accounts.reset_password(target.id, by_id=True)
            return _password_once(account, password, "reset")

        return _run("account.reset_password", target, change, done="")

    @blueprint.post("/users/<account_id>/disable")
    def users_disable(account_id: str) -> Any:
        target = _target(account_id)
        refusal = _guard_refusal(target, demoting=True)
        if refusal:
            audit.refused("account.disable", actor=_actor(), target=target.id)
            return users_page(f"Not changed: {refusal}.", 409)
        me = admin_account().id

        def change(ticket: audit.Ticket) -> Any:
            hosting_state().accounts.disable(target.id, by_id=True, actor_id=me)
            # v0.20.0 T15 (spec §14.8): its live sessions end in every story.
            ticket.detail.update(end_owner(target.id))
            return None

        return _run(
            "account.disable",
            target,
            change,
            done=f"Disabled {target.name}; every login of it has ended, and its live sessions with them.",
        )

    @blueprint.post("/users/<account_id>/enable")
    def users_enable(account_id: str) -> Any:
        target = _target(account_id)
        return _run(
            "account.enable",
            target,
            lambda _t: hosting_state().accounts.enable(target.id, by_id=True) and None,
            done=f"Enabled {target.name}.",
        )

    def _set_admin(account_id: str, on: bool) -> Any:
        target = _target(account_id)
        if not on:
            refusal = _guard_refusal(target, demoting=True)
            if refusal:
                audit.refused("account.set_admin", actor=_actor(), target=target.id, detail={"admin": False})
                return users_page(f"Not changed: {refusal}.", 409)
        me = admin_account().id
        return _run(
            "account.set_admin",
            target,
            lambda _t: hosting_state().accounts.set_admin(target.id, on, by_id=True, actor_id=me) and None,
            detail={"admin": on},
            done=f"{target.name} is {'now' if on else 'no longer'} an admin.",
        )

    @blueprint.post("/users/<account_id>/grant-admin")
    def users_grant_admin(account_id: str) -> Any:
        return _set_admin(account_id, True)

    @blueprint.post("/users/<account_id>/revoke-admin")
    def users_revoke_admin(account_id: str) -> Any:
        return _set_admin(account_id, False)

    @blueprint.post("/users/<account_id>/delete")
    def users_delete(account_id: str) -> Any:
        target = _target(account_id)
        mode = str(request.form.get("mode", "") or "")
        purge = mode == PURGE
        actor = _actor()
        if mode not in (KEEP, PURGE):
            audit.refused("account.delete", actor=actor, target=target.id)
            return users_page("Not deleted: choose keep or purge for the account's saves.", 400)
        if str(request.form.get("confirm", "") or "") != target.name:
            audit.refused("account.delete", actor=actor, target=target.id, detail={"purge": purge})
            return users_page(f"Not deleted: type {target.name} to confirm.", 400)
        refusal = _guard_refusal(target, demoting=True)
        if refusal:
            audit.refused("account.delete", actor=actor, target=target.id, detail={"purge": purge})
            return users_page(f"Not deleted: {refusal}.", 409)
        me = admin_account().id

        def change(ticket: audit.Ticket) -> Any:
            accounts = hosting_state().accounts
            # Spec §14.8: disabled first (every login ends, and T15's
            # session-ending hook on a disable runs), then removed; each
            # guarded inside the accounts lock.
            accounts.disable(target.id, by_id=True, actor_id=me)
            ended = end_owner(target.id)
            ticket.detail.update(ended)
            if purge and (ended.get("sessions_busy") or ended.get("sessions_error")):
                # Fix round 1 (I1): its saves are not deleted while one of its
                # turns may still write, or a story could not say. The
                # account stays disabled; a retry in a moment goes through.
                ticket.result = audit.REFUSED
                ticket.detail["reason"] = "sessions_not_ended"
                return users_page(PURGE_WAITING.format(name=target.name), 409)
            removed = accounts.remove(target.id, by_id=True, actor_id=me)
            if purge:
                ticket.detail["purged"] = purge_user_dir(removed)
                # Fix round 2 (N3): re-checked after the delete. A request
                # the gate let in before the disable could still have made a
                # run (its first save refused now, but its session live): end
                # whatever the stories hold for it, and purge again if
                # anything wrote the folder back.
                again = end_owner(target.id)
                if again.get("sessions_ended") or again.get("sessions_busy") or purge_user_dir(removed):
                    ticket.detail["purge_recheck"] = True
                    purge_user_dir(removed)
            return None

        kept = "Its saves are deleted." if purge else "Its saves are kept on disk."
        return _run(
            "account.delete",
            target,
            change,
            detail={"purge": purge},
            done=f"Deleted {target.name}. {kept}",
        )


__all__ = ["KEEP", "ONCE_KEY", "ONCE_PATH", "OneTimeShown", "PURGE", "once_page", "register", "users_page", "when"]
