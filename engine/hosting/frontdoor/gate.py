"""
The Front Door: One Check for Both Doors
========================================

``authenticate(environ)`` is THE check every request through the front door
meets (spec §14.5): the HTTP gate below calls it from ``before_request`` --
so it runs on the proxy's catch-all route as on the front door's own pages --
and the WebSocket door (v0.20.0 T13), which is WSGI middleware no
``before_request`` reaches, calls the same function.

It opens the signed session the way Flask does, through
``app.session_interface.open_session``: inside the request's own context
when one is active (the HTTP gate), else inside ``app.request_context(environ)``
(the WebSocket door). Then it RE-READS the account (``auth.current_account``:
gone, disabled or an older epoch is logged out) and looks the chosen story up
in the front door's story table (``stories.StoryTable``), answering an
``Admission``: the account, the chosen slug, the story's routing row, and
the refusal, if any (``LOGIN``, ``MUST_CHANGE``, ``NO_STORY``,
``UNAVAILABLE``). ``MUST_CHANGE`` (v0.20.0 T14, spec §14.6): an account
whose password an admin generated reaches only its account page (and
logging out) until it chooses its own -- a page goes to ``/account``, any
other request is answered 403 ``{"error": "password change required"}``,
and the WebSocket door answers the same 403.

THE ADMIN PANEL'S PATHS (``/admin`` and under it) are passed straight to the
admin guard (``engine/hosting/admin/guard.py``), which runs every check of
its own, this gate's included.

THE HTTP GATE (``before_request``), in order:

1. a state-changing request whose ``Origin`` (else ``Referer``) names another
   site is refused 403 (``engine.hosting.gate.foreign_origin``, T7's rule);
2. ``authenticate``;
3. the open endpoints (``OPEN``: ``GET /api/health``, the front door's own
   stylesheet, the login form and ``POST /logout``) pass without a login;
4. anything else without a live account: ``GET /`` redirects to ``/login``,
   every other request answers 401 JSON ``{"error": "login required"}`` and
   NEVER reaches a worker.

What a logged-in request may then do with its story is the routes' business
(``stories.py``, ``proxy.py``): the admission is kept on ``g``.

Version: v0.2.0 [2026-10-05]
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

from flask import current_app, g, has_request_context, jsonify, redirect, request, session

from engine.hosting.auth import BLUEPRINT_NAME, current_account, hosting_state
from engine.hosting.gate import CROSS_SITE, LOGIN_REQUIRED, foreign_origin

logger = logging.getLogger(__name__)

#: The session key holding the chosen story's slug (spec §14.5).
STORY = "story"

#: Refusals ``authenticate`` answers.
LOGIN = "login"
NO_STORY = "no_story"
UNAVAILABLE = "unavailable"
#: A live account whose password an admin generated (spec §14.6, T14).
MUST_CHANGE = "must_change"

#: What such an account's requests other than pages are told (403).
PASSWORD_CHANGE_REQUIRED = {"error": "password change required"}

#: The endpoints such an account may reach: its account page, logging out,
#: and what any visitor may (``OPEN``).
MUST_CHANGE_ENDPOINTS = frozenset(
    {f"{BLUEPRINT_NAME}.account_page", f"{BLUEPRINT_NAME}.account_post", f"{BLUEPRINT_NAME}.login"}
)

#: The admin panel's paths, which the panel's own guard answers whole
#: (``engine/hosting/admin/guard.py``): Origin, login, role, re-auth, CSRF.
ADMIN_PREFIX = "/admin"


def is_admin_path(path: str) -> bool:
    """Whether ``path`` is ``/admin`` or under it."""
    text = str(path or "")
    return text == ADMIN_PREFIX or text.startswith(ADMIN_PREFIX + "/")


def is_page(method: str, path: str) -> bool:
    """A browser page load: a ``GET``/``HEAD`` outside ``/api/``, ``/socket.io/`` and the static files."""
    if method not in {"GET", "HEAD"}:
        return False
    return not str(path).startswith(("/api/", "/socket.io", "/static/", "/admin/api/", "/admin/static/"))

#: ``endpoint -> methods`` the front door serves without a login.
OPEN: dict[str, frozenset[str]] = {
    "health": frozenset({"GET", "HEAD"}),
    "static": frozenset({"GET", "HEAD"}),
    f"{BLUEPRINT_NAME}.login": frozenset({"GET", "HEAD"}),
    f"{BLUEPRINT_NAME}.login_post": frozenset({"POST"}),
    f"{BLUEPRINT_NAME}.logout": frozenset({"POST"}),
}


@dataclass(frozen=True)
class Admission:
    """What ``authenticate`` found."""

    account: Any
    story: str
    row: Optional[dict[str, Any]]
    refusal: str

    @property
    def ok(self) -> bool:
        return not self.refusal


def _judge(app: Any) -> Admission:
    """Inside a request context: the account, then the chosen story."""
    from engine.hosting.frontdoor import frontdoor

    account = current_account()
    if account is None:
        return Admission(None, "", None, LOGIN)
    if account.must_change:
        return Admission(account, "", None, MUST_CHANGE)
    slug = str(session.get(STORY) or "")
    door = frontdoor(app)
    row = door.table.get(slug) if slug else None
    if row is None:
        return Admission(account, "", None, NO_STORY)
    if not door.table.routable(row):
        return Admission(account, slug, row, UNAVAILABLE)
    return Admission(account, slug, row, "")


def authenticate(environ: dict[str, Any], app: Any = None) -> Admission:
    """
    The one check of both doors (see the module docstring). ``app`` is the
    front door (``current_app`` by default).
    """
    if has_request_context() and request.environ is environ:
        return _judge(app or current_app._get_current_object())
    if app is None:
        raise RuntimeError("authenticate outside a request needs the front door's app")
    with app.request_context(environ):
        # Pushing the context opens the session through
        # app.session_interface.open_session; nothing here saves it.
        return _judge(app)


def is_open(endpoint: Any, method: str) -> bool:
    """Whether ``endpoint`` answers ``method`` without a login."""
    return method in OPEN.get(str(endpoint or ""), frozenset())


def before_request() -> Any:
    """The front door's gate: Origin, then ``authenticate``, then the open list."""
    if is_admin_path(request.path):
        # The admin guard (registered after this, for these paths) checks all.
        return None
    state = hosting_state()
    foreign = foreign_origin(state.settings.public_origin)
    if foreign:
        logger.warning(
            "[frontdoor] Refused a cross-site request (operation=gate, from=%.80r, "
            "method=%s, path=%.80r)",
            foreign,
            request.method,
            request.path,
        )
        return jsonify(CROSS_SITE), 403
    admission = authenticate(request.environ)
    g.frontdoor_admission = admission
    if admission.refusal == MUST_CHANGE:
        return must_change_refusal()
    if admission.account is not None:
        return None
    if is_open(request.endpoint, request.method):
        return None
    if request.path == "/" and request.method in {"GET", "HEAD"}:
        return redirect("/login", code=302)
    return jsonify(LOGIN_REQUIRED), 401


def must_change_refusal() -> Any:
    """
    What a request of an account that must replace an admin-generated
    password gets (spec §14.6): its account page and logging out are served,
    as is every open endpoint; a page goes to ``/account``; anything else is
    403 ``{"error": "password change required"}`` and never reaches a worker.
    """
    endpoint = str(request.endpoint or "")
    if endpoint in MUST_CHANGE_ENDPOINTS or is_open(endpoint, request.method):
        return None
    if is_page(request.method, request.path):
        return redirect("/account", code=303)
    return jsonify(PASSWORD_CHANGE_REQUIRED), 403


def admission() -> Admission:
    """This request's admission (set by ``before_request``)."""
    found = g.get("frontdoor_admission")
    if found is None:
        found = authenticate(request.environ)
        g.frontdoor_admission = found
    return found


__all__ = [
    "ADMIN_PREFIX",
    "Admission",
    "LOGIN",
    "MUST_CHANGE",
    "MUST_CHANGE_ENDPOINTS",
    "NO_STORY",
    "OPEN",
    "PASSWORD_CHANGE_REQUIRED",
    "STORY",
    "UNAVAILABLE",
    "admission",
    "authenticate",
    "before_request",
    "is_admin_path",
    "is_open",
    "is_page",
    "must_change_refusal",
]
