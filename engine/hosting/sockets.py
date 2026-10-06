"""
Hosted Mode: the Socket Door
============================

``before_request`` never runs for Socket.IO (``/socket.io/`` is served by
engineio's middleware in front of Flask, and events are dispatched by
python-socketio), so the socket door has its OWN single enforcement point
(spec §6.3): every socket handler is registered through ``FlaskScene.on``,
and in hosted mode ``on`` wraps it in ``SocketDoor.guard``, which
``install()`` sets as ``scene._socket_guard``. Before the handler's body
runs:

- on ``connect``: no live account (or an account that cannot be read), no
  connection (the handler returns ``False``, which python-socketio answers
  as a refused connect); a connection let in is RECORDED (``SocketRegistry``:
  its sid, account and epoch);
- on every other event: the account is RE-READ (``auth.current_account``,
  through ``users.json``'s cache), and one that is missing, disabled or on an
  older epoch (or cannot be read) gets ``error`` ``{"message": "login
  required"}`` and the socket is DISCONNECTED;
- ``disconnect`` passes through: the record is dropped, the body runs (with
  the owner set when the account is still live), and nothing is emitted to,
  or disconnected from, a socket that is already going;
- the owner (``engine.session.store.current_owner``, spec §6.4) is set to the
  account for the body and reset in a ``finally``, so a pool thread reused by
  the next event (or the next request) never inherits it;
- the action events (``ACTION_EVENTS``: ``player_choice``, ``resume``) pass
  the input caps and then the account's actions bucket (spec §6.5,
  ``limit_action``, v0.20.0 T9): a refusal is ``turn_error`` with ``busy:
  false`` and the handler never runs; under the supervisor each refusal is
  a ``turn`` metric, ``refused_cap`` or ``refused_rate`` (v0.20.0 T17);
- anything the body raises is logged under a reference and answered
  ``error`` ``{"message": "The request could not be completed (ref ...)"}``
  (``engine/hosting/errors.py``), never with the exception's words.

A REVOKED LOGIN LEAVES AT ONCE, NOT ON ITS NEXT EVENT (v0.20.0 T8 fix round
1). A socket that sends nothing still RECEIVES its run's turn stream through
the room it joined, so a check on its own events alone would let a stolen
cookie keep reading a player's narration after a password change. So:

- the accounts store tells the door when an account's logins end in this
  process (``AccountStore.on_revoke``: a password change, a disable, a
  removal), and the door disconnects every socket of that account whose
  recorded epoch is no longer live (``revoke``);
- and, for a change made by ANOTHER process (``scripts/users.py``), before
  every emit to a run's room each socket in it is re-checked against
  ``users.json`` and any stale one disconnected first (``check_room``,
  ``scene._room_check``), so it never receives the next delta.

``tests/test_hosting_sockets.py`` enumerates every handler in every namespace
of ``socketio.server.handlers`` and asserts each is in
``scene.guarded_events``, so a handler added with a raw ``@socketio.on``
fails the suite, not a review.

ONE ACCOUNT'S CONNECTIONS ARE CAPPED (v0.20.0 T13 fix round 1): a
``connect`` past ``hosting.max_connections_per_account`` open sockets of
that account is refused (``SocketRegistry.add_within``, the count and the
add one step), as the front door refuses the WebSocket or poll before it,
with an engine-authored refusal (``limits.too_many_connections``) the client
receives as its ``connect_error`` message (T13 re-review N4).

AN ACCOUNT WHOSE PASSWORD AN ADMIN GENERATED (``must_change``, v0.20.0 T14)
is treated as logged out on every event until its owner replaces it.

THREADS. ``SocketRegistry._lock`` is a LEAF (``engine/locks.py``): its holder
reads or writes one dict and takes nothing else; ``users.json`` is read and
sockets are disconnected outside it.

Version: v0.5.0 [2026-10-06]
"""

from __future__ import annotations

import functools
import inspect
import logging
import threading
from typing import Any, Callable, Optional

from flask import request
from flask_socketio import disconnect, emit
from socketio.exceptions import ConnectionRefusedError as SocketRefused

from engine.hosting.auth import current_account
from engine.hosting import metrics_emit
from engine.hosting.errors import REQUEST_FAILED, public_error
from engine.hosting.limits import SLOW_DOWN, over_cap, too_many_connections
from engine.session.store import current_owner

logger = logging.getLogger(__name__)

#: What a socket without a live account is told before it is dropped.
LOGIN_REQUIRED = {"message": "login required"}

#: The events that are actions (spec §6.5): the action limit and the input
#: caps apply to these.
ACTION_EVENTS = frozenset({"player_choice", "resume"})

#: Socket.IO's own lifecycle events: ``connect`` admits or refuses,
#: ``disconnect`` only ever cleans up.
CONNECT = "connect"
DISCONNECT = "disconnect"


def limit_action(
    event: str,
    account: Any,
    args: tuple[Any, ...],
    *,
    actions: Any = None,
    max_input_chars: Optional[int] = None,
) -> Optional[dict[str, Any]]:
    """
    The input caps and the action limit for one action event (spec §6.5):
    the ``turn_error`` payload that refuses it (``busy: false``), or None.

    The caps first, so a refused oversize message spends no token: a
    ``custom_text`` over ``max_input_chars`` (or a ``player_name`` over 40) is
    refused, never cut. Then one token from the account's actions bucket,
    whatever the action (a rest costs what any choice costs).
    """
    body = args[0] if args else None
    if max_input_chars is not None:
        text = over_cap(body, max_input_chars)
        if text is not None:
            logger.info(
                "[hosting] Refused an action over the input cap (operation=limit_action, "
                "event=%s, account=%s)",
                event,
                getattr(account, "id", ""),
            )
            metrics_emit.refused(getattr(account, "id", ""), "refused_cap")
            return {"message": text, "busy": False}
    if actions is not None and not actions.allow(account.id):
        logger.info(
            "[hosting] Refused an action over the rate limit (operation=limit_action, "
            "event=%s, account=%s)",
            event,
            account.id,
        )
        metrics_emit.refused(account.id, "refused_rate")
        return {"message": SLOW_DOWN, "busy": False}
    return None


def _refuse_connect(text: str) -> Any:
    """Refuse a ``connect`` with ``text`` as the client's ``connect_error`` message (never returns)."""
    raise SocketRefused(text)


def _takes_arguments(handler: Callable[..., Any]) -> bool:
    """Whether ``handler`` accepts positional arguments (a connect handler may take none)."""
    try:
        parameters = inspect.signature(handler).parameters.values()
    except (TypeError, ValueError):
        return True
    return any(
        p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD, p.VAR_POSITIONAL)
        for p in parameters
    )


def _sid() -> str:
    return str(getattr(request, "sid", "") or "")


class SocketRegistry:
    """Every open socket's ``sid -> (account id, epoch, namespace)``."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sids: dict[str, tuple[str, int, str]] = {}

    def add(self, sid: str, account_id: str, epoch: int, namespace: str) -> None:
        with self._lock:
            self._sids[sid] = (account_id, int(epoch), namespace)

    def add_within(self, sid: str, account_id: str, epoch: int, namespace: str, cap: Optional[int]) -> bool:
        """
        ``add``, unless ``account_id`` already has ``cap`` sockets open (then
        nothing is added and False is answered): the count and the add are
        one step under the lock, so two connects at once cannot both pass.
        """
        with self._lock:
            if cap is not None and sum(1 for e in self._sids.values() if e[0] == account_id) >= cap:
                return False
            self._sids[sid] = (account_id, int(epoch), namespace)
            return True

    def forget(self, sid: str) -> Optional[tuple[str, int, str]]:
        with self._lock:
            return self._sids.pop(sid, None)

    def get(self, sid: str) -> Optional[tuple[str, int, str]]:
        with self._lock:
            return self._sids.get(sid)

    def of_account(self, account_id: str) -> list[str]:
        with self._lock:
            return [sid for sid, entry in self._sids.items() if entry[0] == account_id]

    def __len__(self) -> int:
        with self._lock:
            return len(self._sids)


class SocketDoor:
    """
    The socket guard, the registry of open sockets, and the two ways a
    revoked login is shut out (see the module docstring).

    Args:
        scene: The ``FlaskScene`` whose Socket.IO server the sockets are on.
        accounts: The ``AccountStore`` every check re-reads.
    """

    def __init__(
        self,
        scene: Any,
        accounts: Any,
        *,
        actions: Any = None,
        max_input_chars: Optional[int] = None,
        max_connections: Optional[int] = None,
    ) -> None:
        self.scene = scene
        self.accounts = accounts
        self.registry = SocketRegistry()
        #: ``hosting.max_connections_per_account``, None for no cap.
        self.max_connections = max_connections
        #: The actions bucket (``limits.ActionLimiter``), None for none.
        self.actions = actions
        #: ``hosting.max_input_chars``, None for no cap.
        self.max_input_chars = max_input_chars
        #: Run by the guard itself after every ``disconnect`` body (hosted
        #: mode's idle sweep, ``engine.hosting.install_sessions``), so a
        #: story's own ``disconnect`` handler cannot replace it (T9 fix round 1).
        self.after_disconnect: Optional[Callable[[], Any]] = None

    # -- liveness ---------------------------------------------------------

    def _live(self, sid: str) -> bool:
        """Whether ``sid``'s recorded login is still live (unknown, unreadable: no)."""
        entry = self.registry.get(sid)
        if entry is None:
            return False
        account_id, epoch, _namespace = entry
        try:
            account = self.accounts.get(account_id)
        except Exception:  # noqa: BLE001 -- an unreadable users.json is not a live login
            logger.exception("[hosting] Account unreadable (operation=_live, sid=%s)", sid)
            return False
        return account is not None and not account.disabled and account.epoch == epoch

    def drop(self, sid: str, namespace: str = "/") -> None:
        """Disconnect ``sid`` (and forget it), from any thread."""
        entry = self.registry.forget(sid)
        space = entry[2] if entry is not None else namespace
        try:
            self.scene.socketio.server.disconnect(sid, namespace=space)
        except Exception:  # noqa: BLE001 -- already gone is fine
            logger.debug("[hosting] Socket already gone (operation=drop, sid=%s)", sid)
        logger.info("[hosting] Socket dropped, login no longer live (operation=drop, sid=%s)", sid)

    def revoke(self, account_id: str) -> None:
        """An account's logins ended in this process: drop each of its sockets that is not live."""
        for sid in self.registry.of_account(account_id):
            if not self._live(sid):
                self.drop(sid)

    def check_room(self, room: str, namespace: str = "/") -> None:
        """
        Before an emit to ``room``: disconnect every socket in it whose login
        is no longer live (a change another process made, which no listener
        heard), so it never receives what is about to be sent.
        """
        try:
            members = [sid for sid, _eio in self.scene.socketio.server.manager.get_participants(namespace, room)]
        except Exception:  # noqa: BLE001 -- no such room: nobody to check
            return
        for sid in members:
            if not self._live(sid):
                self.drop(sid, namespace)

    # -- the guard ----------------------------------------------------------

    def guard(self, event: str, namespace: str, handler: Callable[..., Any]) -> Callable[..., Any]:
        """``handler`` behind the socket door (see the module docstring)."""
        takes_arguments = _takes_arguments(handler)

        def call(args: tuple[Any, ...]) -> Any:
            return handler(*args) if takes_arguments else handler()

        @functools.wraps(handler)
        def guarded(*args: Any) -> Any:
            if event == DISCONNECT:
                return self._on_disconnect(call, args)
            try:
                account = current_account()
            except Exception as exc:  # noqa: BLE001 -- unreadable accounts: no login (M1)
                public_error(exc, REQUEST_FAILED, where=f"socket:{event}:account")
                account = None
            if account is None or account.must_change:
                # A password an admin generated must be replaced first, at
                # the front door's /account (spec §14.6): logged out here.
                return self._refuse(event)
            token = current_owner.set(account.id)
            try:
                if event in ACTION_EVENTS:
                    refusal = limit_action(
                        event,
                        account,
                        args,
                        actions=self.actions,
                        max_input_chars=self.max_input_chars,
                    )
                    if refusal is not None:
                        emit("turn_error", refusal)
                        return None
                if event == CONNECT:
                    # One account's open connections are capped here too
                    # (hosting.max_connections_per_account, T13 fix round 1,
                    # I4); the place is taken before the body runs and given
                    # back if it refuses.
                    sid = _sid()
                    if not self.registry.add_within(sid, account.id, account.epoch, namespace, self.max_connections):
                        logger.warning(
                            "[hosting] Socket refused: too many connections for one account "
                            "(operation=socket_guard, account=%s, cap=%s)",
                            account.id,
                            self.max_connections,
                        )
                        # An engine-authored refusal the client can show
                        # (T13 re-review N4): Socket.IO sends it as the
                        # connect_error's message, where `return False`
                        # gave only a generic connect failure.
                        refusal = too_many_connections(int(self.max_connections or 0))
                        return _refuse_connect(refusal)
                    try:
                        result = call(args)
                    except BaseException:
                        self.registry.forget(sid)
                        raise
                    if result is False:
                        self.registry.forget(sid)
                    return result
                return call(args)
            except SocketRefused:
                raise  # Flask-SocketIO hands it to the client as connect_error
            except Exception as exc:  # noqa: BLE001 -- the door's last line
                text, _ref = public_error(
                    exc, REQUEST_FAILED, where=f"socket:{event}", account=account.id
                )
                if event == CONNECT:
                    return False
                emit("error", {"message": text})
                return None
            finally:
                current_owner.reset(token)

        return guarded

    def _refuse(self, event: str) -> Any:
        if event == CONNECT:
            logger.info(
                "[hosting] Socket refused, no login (operation=socket_guard, "
                "event=connect, address=%s)",
                request.remote_addr or "",
            )
            return False
        logger.info(
            "[hosting] Socket dropped, no live login (operation=socket_guard, "
            "event=%.40s, sid=%s)",
            event,
            _sid(),
        )
        self.registry.forget(_sid())
        emit("error", dict(LOGIN_REQUIRED))
        disconnect()
        return None

    def _on_disconnect(self, call: Callable[[tuple[Any, ...]], Any], args: tuple[Any, ...]) -> Any:
        """A socket is going: forget it, run the body, emit and disconnect nothing."""
        self.registry.forget(_sid())
        try:
            account = current_account()
        except Exception:  # noqa: BLE001 -- cleanup runs regardless
            account = None
        token = current_owner.set(account.id) if account is not None else None
        try:
            return call(args)
        except Exception as exc:  # noqa: BLE001 -- logged; nobody is left to tell
            public_error(exc, REQUEST_FAILED, where="socket:disconnect")
            return None
        finally:
            if token is not None:
                current_owner.reset(token)
            after = self.after_disconnect
            if after is not None:
                try:
                    after()
                except Exception as exc:  # noqa: BLE001 -- housekeeping; logged
                    public_error(exc, REQUEST_FAILED, where="socket:after_disconnect")


def _forget_only(*_args: Any) -> None:
    """The default ``disconnect`` body: the guard itself forgets the socket."""


def install(scene: Any, accounts: Any, *, actions: Any = None, settings: Any = None) -> SocketDoor:
    """
    Put every socket handler ``scene`` registers from now on behind the
    door, shut out a revoked login at once (``accounts.on_revoke``) and
    before every room emit (``scene._room_check``), and register the
    ``disconnect`` handler that forgets a closed socket (a story's own,
    registered later through ``scene.on``, replaces its body; the guard
    still forgets). ``actions`` (the actions bucket) and ``settings``'
    ``max_input_chars`` limit the action events (spec §6.5).
    """
    door = SocketDoor(
        scene,
        accounts,
        actions=actions,
        max_input_chars=getattr(settings, "max_input_chars", None),
        max_connections=getattr(settings, "max_connections_per_account", None),
    )
    scene._socket_guard = door.guard
    scene._room_check = door.check_room
    scene._socket_door = door
    accounts.on_revoke(door.revoke)
    scene.on(DISCONNECT)(_forget_only)
    return door


__all__ = [
    "ACTION_EVENTS",
    "CONNECT",
    "DISCONNECT",
    "LOGIN_REQUIRED",
    "SocketDoor",
    "SocketRegistry",
    "install",
    "limit_action",
]
