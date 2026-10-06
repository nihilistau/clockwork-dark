"""
Hosted Mode: Login, Logout and the Account Page
===============================================

The login session is Flask's signed cookie (spec §6.2), ``clockwork_session``:
``{uid, epoch}`` once logged in, and before that only the login form's CSRF
token. Every request re-reads the account (``current_account``), and a
missing, disabled or older-epoch account is logged out.

A PASSWORD AN ADMIN GENERATED (``must_change``, v0.20.0 T14, spec §14.6)
sends its account to ``/account`` at login (``landing``), where the page says
why; ``POST /account`` (``accounts.set_password_by_id``) clears it. The doors
enforce it: the front door's gate sends such an account's pages to
``/account`` and answers its other requests 403, and a worker treats it as
logged out.

A BLUEPRINT ANY APP CAN MOUNT (``auth_blueprint``). A standalone hosted game
app mounts it; under the supervisor the front door does
(``engine/hosting/frontdoor/``), and a worker only reads the cookie, through
``ReadOnlySessionInterface``, whose ``save_session`` does nothing (spec
§6.2's one writer, v0.20.0 T12).

THE PAGES: ``GET``/``POST /login``, ``POST /logout``, ``GET``/``POST
/account`` (change your own password). Plain HTML with inline CSS and no
JavaScript, rendered from ``engine/hosting/templates/`` through this
module's own Jinja environment (``render_page``), so no scene or story
template of the same name can stand in for the login page.

LOGOUT ENDS THIS BROWSER ONLY. The cookie is signed, not stored: a copy
taken before logout stays valid until ``hosting.session_days`` after it was
issued. What ends every copy is the epoch: a password change or a disable.

THE COOKIE KEY is at least 32 characters (``config.MIN_SECRET_KEY_CHARS``),
whether it comes from ``hosting.secret_key`` or the key file, and an
operator's own key uses at least 16 different characters; a weaker one stops
startup.

CSRF (spec §6.3):

- the LOGIN form's token is per session, in the cookie (there is no account
  yet to derive one from);
- every LOGGED-IN form's token (logout, account) is STATELESS: an HMAC of
  ``uid|epoch`` under the cookie key, checked with ``hmac.compare_digest``.
  Rendering one writes nothing to the session, so ``GET /`` sends no cookie,
  and a password change (a new epoch) retires every old token at once.

``POST /login`` DECIDES PLAIN HTTP FIRST: with ``hosting.cookie_secure`` on,
a browser on ``http://`` has already dropped the pre-login cookie that holds
the CSRF token, so it gets a page naming the key rather than a CSRF refusal
it could never get past.

LOGIN FAILURES ARE ONE FAILURE: a wrong name, a wrong password and a disabled
account get the same status, the same page and the same scrypt work
(``accounts.DUMMY_HASH``). Attempts are limited per address (an IPv6 /64),
per ``(address, name)`` and, for addresses that have just failed, together
(``engine/hosting/limits.py``; ``record_failure``), and at most
``hosting.max_concurrent_logins`` hashes run at once; every refusal is the
same 429. A failure is logged with the name and the address, never the
password. Under the supervisor each login is also a ``login`` metric
(v0.20.0 T17): the account's id (null for a name that is no account) and an
outcome (``ok``, ``failed``, ``limited``, ``disabled``, ``must_change``),
never the name typed.

Version: v0.4.0 [2026-10-06]
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from flask import (
    Blueprint,
    current_app,
    redirect,
    request,
    session,
)

from flask.sessions import SecureCookieSessionInterface
from jinja2 import Environment, FileSystemLoader, select_autoescape

from engine.hosting import metrics_emit
from engine.hosting.accounts import (
    Account,
    AccountError,
    AccountStore,
    LoginBusy,
    check_password,
    secure_dir,
)
from engine.hosting.config import HostingConfigError, HostingSettings, check_secret_key
from engine.hosting.limits import ActionLimiter, LoginLimiter, TurnSlots

logger = logging.getLogger(__name__)

#: A per-process key for ``_name_marker``: the marker is not reversible and not
#: comparable across restarts.
_MARKER_KEY = secrets.token_bytes(16)


def _name_marker(name: str) -> str:
    """
    A short stand-in for a submitted login name in a log line (final review,
    finding 2): its length and the first 8 hex of a keyed HMAC. The raw name
    is never logged, because a password typed into the name field would land
    in a log that is not access-limited. Two failures by one name share a
    marker within a process, which is all a reader needs.
    """
    digest = hmac.new(_MARKER_KEY, name.encode("utf-8", "replace"), hashlib.sha256).hexdigest()
    return f"len={len(name)} mac={digest[:8]}"

#: The blueprint's name; its endpoints are ``hosting_auth.<view>``.
BLUEPRINT_NAME = "hosting_auth"

#: ``app.extensions`` key holding the ``HostingState``.
EXTENSION = "engine_hosting"

#: The login cookie's name.
COOKIE_NAME = "clockwork_session"

#: The generated cookie key's file name under ``<storage.root>/hosting/``.
SECRET_KEY_FILE = "secret_key"

#: What every failed login is told, whatever failed.
LOGIN_FAILED = "That name and password do not match."

#: What a login over the limit is told.
LOGIN_LIMITED = "Too many attempts. Wait a minute and try again."

#: What a form whose token does not match is told.
FORM_EXPIRED = "This form has expired. Reload the page and try again."

#: Session keys.
UID = "uid"
EPOCH = "epoch"
LOGIN_CSRF = "login_csrf"

#: The label mixed into a logged-in form's token, so it can never equal any
#: other HMAC made under the same key.
_FORM_LABEL = b"hosting-form-v1|"


#: The login pages' OWN template environment, loading only
#: ``engine/hosting/templates/``. Not Flask's loader, which searches the app's
#: template folder (a scene's, a story's) first, where a ``login.html`` of the
#: same name would replace the login page.
_PAGES = Environment(
    loader=FileSystemLoader(str(Path(__file__).resolve().parent / "templates")),
    autoescape=select_autoescape(["html"]),
)


def render_page(name: str, **context: Any) -> str:
    """Render one of hosted mode's pages from its own templates."""
    return _PAGES.get_template(name).render(**context)


@dataclass
class HostingState:
    """What hosted mode keeps on the app (``app.extensions[EXTENSION]``)."""

    settings: HostingSettings
    accounts: AccountStore
    logins: LoginLimiter
    #: The actions bucket (spec §6.5): per account, over HTTP and the socket.
    actions: Optional[ActionLimiter] = None
    #: This process's ``server-<pid>.lock`` handle (``accounts.hold_server_lock``),
    #: held for the process's life so ``users.py adopt`` refuses while it runs.
    server_lock: Optional[int] = None
    #: The process's HTTP turn slots (``limits.TurnSlots``, v0.20.0 T12): at
    #: most ``hosting.threads`` less a reserve of HTTP turns in flight.
    turn_slots: Optional[TurnSlots] = None


def hosting_state(app: Any = None) -> HostingState:
    """The app's ``HostingState`` (``current_app`` by default)."""
    return (app or current_app).extensions[EXTENSION]


# -- the cookie key -------------------------------------------------------


def secret_key(settings: HostingSettings, directory: Path) -> str:
    """
    The cookie's signing key: ``hosting.secret_key`` when set, else the key in
    ``<directory>/secret_key``, generated there once (32 random bytes, hex).

    The file is created with ``O_CREAT | O_EXCL`` (mode 0600 on POSIX), so
    two processes sharing the root cannot each write a different key: the
    loser reads the winner's.
    """
    if settings.secret_key:
        return check_secret_key(settings.secret_key, source="hosting.secret_key")
    secure_dir(directory)
    path = directory / SECRET_KEY_FILE
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        return _read_key(path)
    try:
        os.write(fd, secrets.token_hex(32).encode("ascii"))
    finally:
        os.close(fd)
    if os.name == "posix":
        os.chmod(path, 0o600)
    logger.info("[hosting] Generated the cookie key (operation=secret_key, path=%s)", path)
    return _read_key(path)


def _read_key(path: Path) -> str:
    """
    The key in ``path``, waiting briefly while it is still empty (a writer
    that has just created it), and refused when it is shorter than
    ``MIN_SECRET_KEY_CHARS`` (a hand-edited file).
    """
    deadline = time.monotonic() + 5.0
    while True:
        text = path.read_text(encoding="ascii", errors="replace").strip()
        if text:
            return check_secret_key(text, source=str(path), configured=False)
        if time.monotonic() > deadline:
            raise HostingConfigError(
                "hosting.secret_key",
                f"{path} holds no usable key; delete it (every login ends) or set "
                "CLOCKWORK_SECRET_KEY",
            )
        time.sleep(0.02)


# -- the account behind a request ------------------------------------------


def current_account() -> Optional[Account]:
    """
    The logged-in account, re-read from ``users.json`` (through its cache).

    A cookie naming an account that is gone, disabled or on an older epoch is
    LOGGED OUT here (the session cleared), so every door that asks sees None.
    """
    uid = session.get(UID)
    if not uid:
        return None
    account = hosting_state().accounts.get(uid)
    if account is None or account.disabled or account.epoch != session.get(EPOCH):
        session.clear()
        return None
    return account


def form_token(account: Account, app: Any = None) -> str:
    """A logged-in form's CSRF token: HMAC-SHA256 of ``uid|epoch`` under the cookie key."""
    key = str((app or current_app).secret_key).encode("utf-8")
    message = _FORM_LABEL + f"{account.id}|{account.epoch}".encode("utf-8")
    return hmac.new(key, message, hashlib.sha256).hexdigest()


def form_token_ok(account: Optional[Account], sent: Any) -> bool:
    """Whether ``sent`` is ``account``'s form token at its current epoch."""
    if account is None or not isinstance(sent, str) or not sent:
        return False
    return hmac.compare_digest(form_token(account).encode("utf-8"), sent.encode("utf-8"))


class ReadOnlySessionInterface(SecureCookieSessionInterface):
    """
    A supervised worker's session (spec §6.2, v0.20.0 T12): the signed cookie
    is read as every door reads it, and never written -- ``save_session``
    does nothing, so a worker never sends ``Set-Cookie``. The front door is
    the cookie's one writer; a response already in flight can then never set
    back a story switch or a password change's new epoch made meanwhile.
    """

    def save_session(self, app: Any, session: Any, response: Any) -> None:
        return None


class PageExtras:
    """
    What ``clockwork.html``'s ``{% if hosting %}`` block reads: the logout
    form's token, computed per request from the cookie (never written to it).
    """

    def __bool__(self) -> bool:
        return True

    @property
    def csrf(self) -> str:
        account = current_account()
        return form_token(account) if account is not None else ""


# -- the pages --------------------------------------------------------------


def _address() -> str:
    return str(request.remote_addr or "")


def _plain_http_refused(settings: HostingSettings) -> bool:
    return settings.cookie_secure and not request.is_secure


def _login_page(message: str = "", status: int = 200) -> Any:
    state = hosting_state()
    token = session.get(LOGIN_CSRF)
    if not token:
        token = session[LOGIN_CSRF] = secrets.token_urlsafe(32)
    return (
        render_page(
            "login.html",
            csrf=token,
            message=message,
            insecure=_plain_http_refused(state.settings),
        ),
        status,
    )


def _plain_http_page() -> Any:
    return (
        render_page("login.html", csrf="", message="", insecure=True, blocked=True),
        400,
    )


#: What a new password equal to the current one is told (T14 fix round 1, M2).
SAME_PASSWORD = "Choose a new password different from your current one."

#: Where an account that must replace an admin-generated password is sent.
ACCOUNT_PAGE = "/account"

#: What the account page tells such an account (spec §14.6).
MUST_CHANGE_TEXT = (
    "An admin set a one-time password for this account. Choose your own "
    "password to go on: type the one-time password as your current one."
)


def landing(account: Account) -> str:
    """Where a logged-in account goes: ``/``, or ``/account`` while it must change its password."""
    return ACCOUNT_PAGE if account.must_change else "/"


def _account_page(account: Account, message: str, status: int) -> Any:
    if not message and account.must_change:
        message = MUST_CHANGE_TEXT
    return (
        render_page(
            "account.html",
            account=account,
            csrf=form_token(account),
            message=message,
            must_change=account.must_change,
        ),
        status,
    )


def _failed_login_metric(state: HostingState, name: str) -> None:
    """
    A failed login as a ``login`` metric (v0.20.0 T17): the account's id when
    the name is one (``disabled`` for a disabled one), null otherwise -- the
    name itself is never recorded. The player was told the one failure
    either way (``LOGIN_FAILED``).
    """
    try:
        found = state.accounts.by_name(name)
    except Exception:  # noqa: BLE001 -- a metric must never fail a login page
        found = None
    if found is None:
        metrics_emit.emit("login", account=None, outcome="failed")
    else:
        metrics_emit.emit("login", account=found.id, outcome="disabled" if found.disabled else "failed")


def auth_blueprint(name: str = BLUEPRINT_NAME) -> Blueprint:
    """Build the login blueprint. Factory, not a singleton (see games/api.py)."""
    blueprint = Blueprint(name, __name__)

    @blueprint.get("/login")
    def login() -> Any:
        account = current_account()
        if account is not None:
            return redirect(landing(account), code=303)
        return _login_page()

    @blueprint.post("/login")
    def login_post() -> Any:
        state = hosting_state()
        # 1. Plain HTTP under cookie_secure: decided before CSRF (spec §6.2).
        if _plain_http_refused(state.settings):
            return _plain_http_page()
        # 2. The login form's own token, from the pre-login cookie.
        expected = session.get(LOGIN_CSRF)
        sent = request.form.get("csrf", "")
        if not expected or not hmac.compare_digest(
            str(expected).encode("utf-8"), str(sent).encode("utf-8")
        ):
            return _login_page(FORM_EXPIRED, 403)
        name = request.form.get("name", "")
        password = request.form.get("password", "")
        address = _address()
        # 3. The buckets, before any hashing; then a hashing slot.
        if not state.logins.allow(address, name):
            logger.warning(
                "[hosting] Login refused, over the limit (operation=login, "
                "name=<%s>, address=%s)",
                _name_marker(name),
                address,
            )
            metrics_emit.emit("login", account=None, outcome="limited")
            return _login_page(LOGIN_LIMITED, 429)
        try:
            account = state.accounts.verify(name, password)
        except LoginBusy:
            logger.warning(
                "[hosting] Login refused, every hashing slot busy (operation=login, "
                "name=<%s>, address=%s)",
                _name_marker(name),
                address,
            )
            metrics_emit.emit("login", account=None, outcome="limited")
            return _login_page(LOGIN_LIMITED, 429)
        if account is None:
            state.logins.record_failure(address)
            logger.warning(
                "[hosting] Login failed (operation=login, name=<%s>, address=%s)",
                _name_marker(name),
                address,
            )
            _failed_login_metric(state, name)
            return _login_page(LOGIN_FAILED, 401)
        # 4. A fresh session: nothing the browser held before survives.
        session.clear()
        session[UID] = account.id
        session[EPOCH] = account.epoch
        session.permanent = True
        logger.info("[hosting] Logged in (operation=login, account=%s, address=%s)", account.id, address)
        metrics_emit.emit("login", account=account.id, outcome="must_change" if account.must_change else "ok")
        return redirect(landing(account), code=303)

    @blueprint.post("/logout")
    def logout() -> Any:
        account = current_account()
        if account is not None and not form_token_ok(account, request.form.get("csrf")):
            return _account_page(account, FORM_EXPIRED, 403)
        session.clear()
        return redirect("/login", code=303)

    @blueprint.get("/account")
    def account_page() -> Any:
        account = current_account()
        if account is None:
            return redirect("/login", code=303)
        return _account_page(account, "", 200)

    @blueprint.post("/account")
    def account_post() -> Any:
        state = hosting_state()
        account = current_account()
        if account is None:
            return redirect("/login", code=303)

        def page(message: str, status: int, *, who: Account = account) -> Any:
            return _account_page(who, message, status)

        if not form_token_ok(account, request.form.get("csrf")):
            return page(FORM_EXPIRED, 403)
        current = request.form.get("current", "")
        new = request.form.get("new", "")
        confirm = request.form.get("confirm", "")
        if not state.logins.allow(_address(), account.name):
            return page(LOGIN_LIMITED, 429)
        try:
            current_ok = state.accounts.check_current(account.id, current)
        except LoginBusy:
            return page(LOGIN_LIMITED, 429)
        if not current_ok:
            state.logins.record_failure(_address())
            logger.warning(
                "[hosting] Password change refused, wrong current password "
                "(operation=account, account=%s, address=%s)",
                account.id,
                _address(),
            )
            return page("Your current password is not right.", 403)
        if new != confirm:
            return page("The new password and its confirmation differ.", 400)
        if new == current:
            # Fix round 1, M2: a one-time password an admin generated must be
            # REPLACED, so the admin never knows the player's real one.
            return page(SAME_PASSWORD, 400)
        try:
            check_password(new)
            changed = state.accounts.set_password_by_id(account.id, new)
        except AccountError as exc:
            return page(f"Not changed: {exc}.", 400)
        except LoginBusy:
            return page(LOGIN_LIMITED, 429)
        # The epoch went up: every other browser and socket is logged out.
        # THIS window's cookie is re-issued with the new epoch.
        session[EPOCH] = changed.epoch
        session.permanent = True
        logger.info("[hosting] Password changed (operation=account, account=%s)", account.id)
        return page("Your password is changed. Every other login has ended.", 200, who=changed)

    return blueprint


__all__ = [
    "BLUEPRINT_NAME",
    "COOKIE_NAME",
    "EPOCH",
    "EXTENSION",
    "FORM_EXPIRED",
    "HostingState",
    "LOGIN_CSRF",
    "ACCOUNT_PAGE",
    "LOGIN_FAILED",
    "LOGIN_LIMITED",
    "MUST_CHANGE_TEXT",
    "SAME_PASSWORD",
    "landing",
    "PageExtras",
    "ReadOnlySessionInterface",
    "SECRET_KEY_FILE",
    "UID",
    "auth_blueprint",
    "current_account",
    "form_token",
    "form_token_ok",
    "hosting_state",
    "render_page",
    "secret_key",
]
