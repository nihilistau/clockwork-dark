"""
The Admin Panel: its Guard, Re-auth and Headers
===============================================

ONE CHECK OVER EVERY ``/admin`` PATH (spec §14.7), registered by the admin
blueprint with ``before_app_request`` and keyed by the PATH, not by the
blueprint's endpoints: so it covers every rule under ``/admin`` -- one added
later, by anyone, included -- and an unknown ``/admin/...`` path or a method
a rule does not take, which match no admin endpoint at all. The front door's
own gate passes these paths straight here (``frontdoor/gate.py``). In order:

1. no login: a page ``GET`` is sent to ``/login``; anything else is 401
   ``{"error": "login required"}``;
2. logged in, not an admin: 403, with ONE fixed body for every rule
   (``FORBIDDEN``), so the refusal says nothing about which rules exist;
3. an admin whose password an admin generated (``must_change``): a page goes
   to ``/account``, anything else is 403 ``{"error": "password change
   required"}``;
4. an admin whose re-auth (``admin_at`` in the signed session, set by
   ``/admin/reauth``) is older than ``hosting.admin.reauth_minutes``, or who
   has none: a page ``GET`` is sent to the re-auth page, anything else is 401
   ``{"error": "reauth required"}`` (the re-auth page itself and the panel's
   stylesheet and script excepted);
5. every state-changing request (``POST``, ``PUT``, ``PATCH``, ``DELETE``):
   T7's Origin check (``gate.foreign_origin``), the CSRF token (the
   stateless ``uid|epoch`` form token, spec §6.3: a password change retires
   every old one), and the admin actions bucket
   (``rate_limits.admin_actions_per_minute``, 429).

The account is re-read on every request (``auth.current_account``: epoch,
disabled, and now ``admin``), so a demoted admin -- whose epoch went up with
the role change -- is logged out on their next request. No ``GET`` changes
anything.

RE-AUTH (``/admin/reauth``): the admin's password again, under the login
buckets (``hosting.rate_limits.logins_per_minute``, per address and per
name) and the hashing slots. A success is audited (``admin.reauth``) BEFORE
``admin_at`` is set, and refused if that row cannot be written; a failure is
audited (``admin.reauth_failed``).

THE HEADERS on every ``/admin`` response (``after_app_request``, also keyed
by the path, so a refusal carries them too): ``Content-Security-Policy``
(``CSP``), ``X-Frame-Options: DENY``, ``Cache-Control: no-store``,
``Referrer-Policy: no-referrer``, ``X-Content-Type-Options: nosniff``.

Two-factor login for admins, and a network allowlist for ``/admin`` inside
the engine, are NOT WIRED (docs/GOVERNANCE.md): an operator who wants the
panel off the internet denies ``/admin`` at their reverse proxy
(docs/HOSTING.md § The admin panel).

Version: v0.1.0 [2026-10-05]
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from typing import Any, Optional
from urllib.parse import quote, urlsplit

from flask import current_app, g, jsonify, redirect, request, session

from engine.hosting.auth import current_account, form_token_ok, hosting_state
from engine.hosting.frontdoor.gate import PASSWORD_CHANGE_REQUIRED, is_admin_path
from engine.hosting.gate import CROSS_SITE, LOGIN_REQUIRED, STATE_CHANGING, foreign_origin
from engine.hosting.limits import ADMIN_SLOW_DOWN, ActionLimiter

logger = logging.getLogger(__name__)

#: Where the panel's state lives on the front door's app.
ADMIN_EXTENSION = "hosting_admin"

#: The admin blueprint's name; its endpoints are ``hosting_admin.<view>``.
BLUEPRINT_NAME = "hosting_admin"

#: The signed session's key for when this admin last re-authenticated.
ADMIN_AT = "admin_at"

#: What every logged-in non-admin is told, on every ``/admin`` rule.
FORBIDDEN = {"error": "forbidden"}

#: What an admin whose re-auth is stale is told, bar a page ``GET``.
REAUTH_REQUIRED = {"error": "reauth required"}

#: What a state-changing request without this admin's current form token is told.
FORM_REFUSED = {"error": "this form has expired; reload the page and try again"}

#: The re-auth page's path.
REAUTH_PATH = "/admin/reauth"

#: The endpoints a stale re-auth may still reach: the re-auth page, and the
#: panel's own stylesheet and script.
REAUTH_EXEMPT = frozenset(
    {f"{BLUEPRINT_NAME}.reauth", f"{BLUEPRINT_NAME}.reauth_post", f"{BLUEPRINT_NAME}.static"}
)

#: The headers every ``/admin`` response carries (spec §14.7).
HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; "
        "frame-ancestors 'none'; form-action 'self'; base-uri 'none'"
    ),
    "X-Frame-Options": "DENY",
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}


@dataclass
class AdminState:
    """What the panel keeps on the front door's app (``app.extensions[ADMIN_EXTENSION]``)."""

    #: The admin actions bucket: per admin, every state-changing request.
    actions: ActionLimiter
    #: ``hosting.admin.reauth_minutes``, in seconds.
    reauth_seconds: float
    #: Generated passwords waiting to be shown once (``users.OneTimeShown``).
    shown: Any = None


def admin_state(app: Any = None) -> AdminState:
    """The app's ``AdminState`` (``current_app`` by default)."""
    return (app or current_app).extensions[ADMIN_EXTENSION]


def install_state(app: Any) -> AdminState:
    """Build the panel's state from the app's hosting settings (once, at build)."""
    from engine.hosting.admin.users import OneTimeShown

    settings = hosting_state(app).settings
    state = AdminState(
        actions=ActionLimiter(settings.admin_actions_per_minute),
        reauth_seconds=float(settings.admin_reauth_minutes) * 60.0,
        shown=OneTimeShown(),
    )
    app.extensions[ADMIN_EXTENSION] = state
    return state


def is_page_get(method: str, path: str) -> bool:
    """A page load: a ``GET``/``HEAD`` outside ``/admin/api/`` and ``/admin/static/``."""
    return method in {"GET", "HEAD"} and not path.startswith(("/admin/api/", "/admin/static/"))


def reauth_fresh(now: Optional[float] = None) -> bool:
    """Whether this session's re-auth is younger than ``hosting.admin.reauth_minutes``."""
    raw = session.get(ADMIN_AT)
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return False
    elapsed = (time.time() if now is None else now) - float(raw)
    return 0.0 <= elapsed <= admin_state().reauth_seconds


#: A re-auth ``next`` the panel follows: ``/admin``, or a path under it of
#: printable ASCII with no space (fix round 1, M1: a CR or LF reached
#: ``redirect`` and gave a 500).
_NEXT_RE = re.compile(r"/admin(?:/[\x21-\x7e]*)?")


def safe_next(target: Any) -> str:
    """
    ``target`` when it is a path under ``/admin`` on this site; else
    ``/admin``. A control character (below 0x20, or DEL), a space or any
    other byte outside printable ASCII is refused.
    """
    text = str(target or "")
    if not _NEXT_RE.fullmatch(text):
        return "/admin"
    parts = urlsplit(text)
    if parts.scheme or parts.netloc or text.startswith("//") or "\\" in text:
        return "/admin"
    return text if is_admin_path(parts.path) and parts.path != REAUTH_PATH else "/admin"


def admin_account() -> Any:
    """The admin this request was let in as (set by ``guard``)."""
    return g.get("hosting_admin_account")


def guard() -> Any:
    """The checks over every ``/admin`` path (see the module docstring); None lets it through."""
    path = request.path
    if not is_admin_path(path):
        return None
    method = request.method.upper()
    page = is_page_get(method, path)
    account = current_account()
    if account is None:
        if page:
            return redirect("/login", code=302)
        return jsonify(LOGIN_REQUIRED), 401
    if not account.admin:
        logger.warning(
            "[admin] Refused a non-admin (operation=admin_guard, account=%s, method=%s, path=%.80r)",
            account.id,
            method,
            path,
        )
        return jsonify(FORBIDDEN), 403
    if account.must_change:
        if page:
            return redirect("/account", code=303)
        return jsonify(PASSWORD_CHANGE_REQUIRED), 403
    g.hosting_admin_account = account
    if request.endpoint not in REAUTH_EXEMPT and not reauth_fresh():
        if page:
            return redirect(f"{REAUTH_PATH}?next={quote(path, safe='/')}", code=303)
        return jsonify(REAUTH_REQUIRED), 401
    if method in STATE_CHANGING:
        foreign = foreign_origin(hosting_state().settings.public_origin)
        if foreign:
            logger.warning(
                "[admin] Refused a cross-site request (operation=admin_guard, from=%.80r, path=%.80r)",
                foreign,
                path,
            )
            return jsonify(CROSS_SITE), 403
        if not form_token_ok(account, request.form.get("csrf")):
            logger.warning(
                "[admin] Refused a request without this admin's form token (operation=admin_guard, "
                "account=%s, path=%.80r)",
                account.id,
                path,
            )
            return jsonify(FORM_REFUSED), 403
        if not admin_state().actions.allow(account.id):
            logger.warning(
                "[admin] Refused an admin action over the rate limit (operation=admin_guard, account=%s)",
                account.id,
            )
            return jsonify({"error": ADMIN_SLOW_DOWN}), 429
    return None


#: The signed session's key for a done action's one-shot message (v0.20.0
#: T15 fix round 1, M6: every action that changed something answers by
#: POST-redirect-GET, so a reload never runs it again).
DONE_KEY = "admin_done"

#: The longest such message kept (it rides in the signed cookie).
DONE_MAX = 400


def done_redirect(path: str, message: str) -> Any:
    """
    A ``POST`` that changed something answers 303 to ``path`` (an admin page),
    whose next ``GET`` shows ``message`` once (``take_done``). Never a
    secret: a one-time password has its own store (``users.OneTimeShown``).
    """
    session[DONE_KEY] = str(message)[:DONE_MAX]
    return redirect(path, code=303)


def take_done() -> str:
    """The waiting one-shot message, removed; "" when none."""
    value = session.pop(DONE_KEY, "")
    return value if isinstance(value, str) else ""


#: What a re-auth with the wrong password is told.
REAUTH_FAILED = "That is not your password."


def _reauth_page(message: str = "", status: int = 200) -> Any:
    from engine.hosting.admin.pages import render
    from engine.hosting.auth import form_token

    account = admin_account()
    return (
        render(
            "reauth.html",
            admin=account,
            csrf=form_token(account),
            next=safe_next(request.values.get("next")),
            message=message,
        ),
        status,
    )


def register_reauth(blueprint: Any) -> None:
    """``GET``/``POST /admin/reauth`` on the admin blueprint (see the module docstring)."""
    from engine.hosting import audit
    from engine.hosting.accounts import LoginBusy
    from engine.hosting.auth import LOGIN_LIMITED

    @blueprint.get("/reauth")
    def reauth() -> Any:
        return _reauth_page()

    @blueprint.post("/reauth")
    def reauth_post() -> Any:
        state = hosting_state()
        account = admin_account()
        address = str(request.remote_addr or "")
        actor = audit.Actor(account.id, account.name, address)
        if not state.logins.allow(address, account.name):
            return _reauth_page(LOGIN_LIMITED, 429)
        try:
            ok = state.accounts.check_current(account.id, request.form.get("password", ""))
        except LoginBusy:
            return _reauth_page(LOGIN_LIMITED, 429)
        if not ok:
            state.logins.record_failure(address)
            audit.refused("admin.reauth_failed", actor=actor, target=account.id)
            logger.warning(
                "[admin] Re-auth failed (operation=reauth, account=%s, address=%s)", account.id, address
            )
            return _reauth_page(REAUTH_FAILED, 401)
        # Write-first: the row before the change it records (spec §14.11).
        try:
            audit.append("admin.reauth", actor=actor, result=audit.OK, target=account.id)
        except audit.AuditUnavailable:
            return _reauth_page(audit.UNAVAILABLE, 503)
        session[ADMIN_AT] = time.time()
        logger.info("[admin] Re-authenticated (operation=reauth, account=%s)", account.id)
        return redirect(safe_next(request.form.get("next")), code=303)


def headers(response: Any) -> Any:
    """``HEADERS`` on every ``/admin`` response, a refusal's included."""
    if is_admin_path(request.path):
        for name, value in HEADERS.items():
            response.headers[name] = value
    return response


__all__ = [
    "ADMIN_AT",
    "ADMIN_EXTENSION",
    "AdminState",
    "BLUEPRINT_NAME",
    "FORBIDDEN",
    "FORM_REFUSED",
    "HEADERS",
    "REAUTH_EXEMPT",
    "REAUTH_FAILED",
    "REAUTH_PATH",
    "REAUTH_REQUIRED",
    "admin_account",
    "admin_state",
    "guard",
    "headers",
    "install_state",
    "is_page_get",
    "reauth_fresh",
    "register_reauth",
    "safe_next",
]
