"""
Hosted Mode: the Bus
====================

The supervisor and its children talk over ONE TCP connection per child, on
``127.0.0.1``, to a port the OS picked when the supervisor bound (spec §14.2).
Loopback only: workers on another host are NOT WIRED (docs/GOVERNANCE.md).

FRAMING. One UTF-8 JSON object per line, at most ``MAX_FRAME`` bytes (64 KiB,
the newline included), read with a bounded ``readline(limit)`` before
anything parses it. JSON and never pickle: a pickle on a socket is code
execution for whoever holds the token.

- a request is ``{"id": n, "op": "...", "args": {...}}``;
- a reply is ``{"id": n, "ok": true, "result": {...}}`` or
  ``{"id": n, "ok": false, "error": "<code>"}``;
- a message with no ``id`` is a notification.

Either side may send requests, so a message carrying ``op`` is a request and
one carrying ``ok`` is a reply to the receiver's own request.

SIZE, BOTH WAYS. An oversize or malformed INBOUND frame closes the connection
(a peer that sends one is broken). A REPLY that would exceed the cap is never
sent: its sender replaces it with ``{"id": n, "ok": false, "error":
"too_large"}`` and the connection stays up.

CREDENTIALS. The supervisor mints a 32-byte token per child START
(``BusServer.mint``, ``secrets.token_hex(32)``) and records what it is: the
role and, for a worker, its story. The child gets it in its environment only
(``CLOCKWORK_BUS_ADDR``, ``CLOCKWORK_BUS_TOKEN``), reads it ONCE and deletes it
from ``os.environ`` (``BusClient.from_environment``), so a grandchild does not
inherit it. A connection's first message must be ``hello`` carrying the token,
within ``hosting.supervisor.hello_seconds`` (2), or the connection is
closed. The token is compared
with ``hmac.compare_digest`` and is SINGLE-USE: accepted once, refused while
its connection is up, dead once that connection closes. A child may send it
on more than one connection (v0.21.1: ``BusClient.connect`` starts another
attempt when loopback loses or delays one); exactly one is accepted, and each
other is refused and logged ``hello refused (error=refused, ...,
credential=live)`` -- a retry, not a replayed credential. ``CLOCKWORK_BUS_ROLE``
tells a child's own boot what to build; the supervisor never believes it.
No token is ever written to argv, a file, a log line or a reply.

A CLOSED OP TABLE. ``OPS`` names every op, the direction it travels, the roles
allowed to send it TO THE SUPERVISOR, and its argument schema. An unknown op
is answered ``unknown_op``, a bad argument ``bad_args``, a caller its row does
not allow ``forbidden``, each with one WARNING. The requests the supervisor
sends a child (``health``, ``drain``, ``shutdown``, ``lane.reclaimed``, and,
from v0.20.0 T15, its fan-out of the panel's ``sessions.*`` to the workers as
``worker.sessions.list``/``end``/``end_owner``) and its notification
``stories.changed`` (v0.20.0 T12: the story table, to the front door, on
every change) are refused from any child. The supervisor STAMPS what it knows from the connection: ``process``
and ``story`` in every request's arguments are the connection's, whatever the
child sent. The admin a story op acts for (``actor``, ``actor_name``,
``address``, and the ``ref`` of the audit row the front door wrote first) is
the front door's word, from its authenticated request: the one role that may
send those ops -- and the model server's (v0.20.0 T16: ``llm.health``,
``llm.models``, and ``llm.apply``, whose ``changes`` are a flat mapping of
dotted keys to scalars, ``MAX_CHANGES`` at most, that the supervisor
validates against the panel's allowlist).

METRICS (v0.20.0 T17, spec §14.10): ``metric`` is a notification from either
child, one event of the closed metrics schema, whose ``process`` and
``story`` the supervisor stamps from the connection; ``metrics.query`` (a
NAMED query, never SQL, a page at a time) and ``oracle.snapshot`` are the
front door's, and the supervisor asks the story's worker for the latter as
``worker.oracle.snapshot``, refused from any child.

DEFERRED REPLIES (v0.20.0 T11). A ``lane.acquire`` is answered when the
supervisor's queue grants it, not when it arrives: its handler
(``BusServer.handle_deferred``) records the request and returns, and the
reply is queued later from whatever thread frees a slot (``answer``), so the
selector never waits and a ``lane.release`` is never queued behind blocked
acquires. On a child's side a caller that gave up may leave ``on_late`` to
receive a reply that still comes (``BusClient.request``), and
``send_request`` sends one whose reply nobody waits for.

THE LIFELINE. A child whose bus connection closes stops and exits non-zero
(``LIFELINE_EXIT_CODE``) through ``BusClient.on_lost``: a worker must not run
turns outside the supervisor's reach. The supervisor treats a closed
connection as that child down.

THREADS. ``BusServer`` reads every connection on ONE selector thread, which
answers ``hello`` and the quick ops itself and never blocks (its sockets are
non-blocking; a long operation is handed to the supervisor's operations
thread). ``BusClient`` has one reader thread, a pool of four for the requests
the supervisor sends it, and one more thread for ``health`` alone, so a busy
pool never fails a health check. All are classified in
``tests/fixtures/module_state.yaml``.

NO BYTES FROM ANY LOCAL CONNECTION MAY STOP THE BUS (T10 fix round 1). The
port is loopback, but any local process can reach it before any ``hello``:

- ``decode`` refuses a frame nested deeper than ``MAX_DEPTH`` before
  ``json.loads`` sees it (a few thousand ``[`` raised ``RecursionError`` in
  the parser and killed the selector), with ONE linear pass over the bytes
  (``nesting_depth``; round 2: the first, a regex, was quadratic), and turns
  ANY parse failure into ``malformed``;
- each connection's read, write and dispatch run guarded: whatever one
  raises closes that connection alone, logged at most once per
  ``BAD_LINE_LOG_SECONDS`` (the rest counted);
- a connection that has not said ``hello`` is closed by any other first
  frame, and after ``hello_seconds``; at most ``MAX_PENDING`` such
  connections are kept, a newcomer past it evicting the OLDEST (round 2: so
  idle sockets cannot lock a child out), and ``MAX_CONNECTIONS`` in all,
  below Windows' ``select()`` limit; a ``select()`` or ``accept()`` error
  backs off instead of spinning;
- should the loop end anyway, ``on_dead`` tells its owner (the supervisor
  then stops, exit 1) rather than leave a deaf bus running;
- the selector's wake pair is made by ``wake_pair``: on Windows, with no
  AF_UNIX, a loopback pair whose ``accept()`` is bounded and takes only its
  own peer (the stdlib's emulation waited forever when a loopback connect
  never arrived, v0.21.0), so ``BusServer()`` raises rather than hangs.

Version: v0.7.1 [2026-10-07]
"""

from __future__ import annotations

import hmac
import itertools
import json
import logging
import os
import secrets
import selectors
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, MutableMapping, Optional

logger = logging.getLogger(__name__)

#: The largest frame either side reads or sends, in bytes, newline included.
MAX_FRAME = 64 * 1024

#: How long a new connection has to send ``hello``, when its owner names no
#: other: the supervisor passes ``hosting.supervisor.hello_seconds`` (2; T10
#: fix round 2: a real child says hello at once, so 5 s only held a slot
#: open for an idle socket).
HELLO_SECONDS = 2.0

#: The environment a child is given (spec §14.2). Never argv, never a file.
BUS_ADDR_ENV = "CLOCKWORK_BUS_ADDR"
BUS_TOKEN_ENV = "CLOCKWORK_BUS_TOKEN"
BUS_ROLE_ENV = "CLOCKWORK_BUS_ROLE"
#: The front door's proxy token (spec §14.5, minted from v0.20.0 T12); a child
#: reads and deletes it with the bus token.
PROXY_TOKEN_ENV = "CLOCKWORK_PROXY_TOKEN"

#: The two roles a child may have.
FRONTDOOR = "frontdoor"
WORKER = "worker"
ROLES = frozenset({FRONTDOOR, WORKER})

#: Which way an op travels.
TO_SUPERVISOR = "to_supervisor"
TO_CHILD = "to_child"

#: Arguments the supervisor fills from the connection, over anything sent.
STAMPED = ("process", "story")

#: How a child exits when its link to the supervisor is lost.
LIFELINE_EXIT_CODE = 3

#: Connections that have not said hello yet, at most (T10 fix rounds 1-2):
#: one more evicts the OLDEST of them, so a newcomer always gets in. Each may
#: hold up to MAX_FRAME bytes for the hello deadline: 64 of them, 4 MiB.
MAX_PENDING = 64

#: Connections in all, at most: below Windows' select() limit (512 sockets)
#: with room for the listener and the wake pair.
MAX_CONNECTIONS = 256

#: How long the selector waits after a select() or accept() error, so a
#: persistent one cannot spin it.
ERROR_BACKOFF_SECONDS = 0.1

#: A refused connection is logged at most once per this many seconds; the
#: rest are counted into the next line.
BAD_LINE_LOG_SECONDS = 5.0

#: The selector's wake pair where the platform has no AF_UNIX socketpair
#: (Windows): how long one attempt waits for its own loopback connection to
#: be accepted, and how many attempts are made before ``BusServer()`` raises.
#: The stdlib's emulation (``socket.socketpair``) waits in ``accept()`` with
#: no bound, and a loopback connect that never reaches the listener -- measured
#: on the owner's workstation: 13 of 3000 never accepted, many more 1-16 s
#: late -- hung the constructor, and with it the test suite (v0.21.0).
WAKE_PAIR_SECONDS = 5.0
WAKE_PAIR_ATTEMPTS = 6

#: A child's connect to the bus, its hello included (``BusClient.connect``):
#: attempt N starts (N - 1) x CONNECT_SECONDS after the first, each on a fresh
#: socket (so a fresh port), and ONE deadline, CONNECT_SECONDS x
#: CONNECT_ATTEMPTS (30 s) from the first start, bounds every connect, read
#: and wait. The same loopback loss as above stranded a worker's single
#: connect until its hello timed out, and the worker exited 1 -- which a
#: model apply restarting it read as "did not start under the new settings"
#: and rolled back (v0.21.1). The deadline sits inside the DEFAULT
#: ``supervisor.boot_seconds`` (120); the child does not read that setting,
#: so under a shorter one the supervisor's boot limit ends the child first and
#: starts it again with a new token, as for any slow boot.
CONNECT_SECONDS = 5.0
CONNECT_ATTEMPTS = 6

#: Error codes.
UNKNOWN_OP = "unknown_op"
BAD_ARGS = "bad_args"
FORBIDDEN = "forbidden"
TOO_LARGE = "too_large"
UNAUTHORIZED = "unauthorized"
REFUSED = "refused"
INTERNAL = "internal"

_STR = "str"
_INT = "int"
_NUMBER = "number"
_BOOL = "bool"
#: A list of story-table rows (``stories.changed``, v0.20.0 T12): each a
#: mapping of exactly ``slug`` (str), ``state`` (str) and ``port`` (int).
_ROWS = "rows"

#: The most rows a ``stories.changed`` notification carries.
MAX_STORY_ROWS = 64

#: A mapping of config changes (``llm.apply``, v0.20.0 T16): at most
#: ``MAX_CHANGES`` dotted keys of at most 64 characters, each a string of at
#: most ``MAX_CHANGE_TEXT`` characters, a number or a boolean (never null, a
#: list or a mapping). Which keys and values are LEGAL is the supervisor's
#: check (``engine.hosting.admin.model.validate_changes``); this is the shape.
_CHANGES = "changes"
MAX_CHANGES = 16
MAX_CHANGE_TEXT = 256

#: A story-table row's keys, as ``stories.changed`` carries them.
STORY_ROW_KEYS = frozenset({"slug", "state", "port"})

#: A flat mapping (v0.20.0 T17): a ``metric``'s event, a ``metrics.query``'s
#: params. At most ``MAX_EVENT_KEYS`` keys of at most 32 characters; WHAT the
#: keys and values may be is the receiver's check (the closed metrics schema,
#: ``engine/hosting/metrics_schema.py``, and the store's named queries), so an
#: event that fails it is counted rejected rather than refused unseen here.
_EVENT = "event"
MAX_EVENT_KEYS = 32

#: The most rows one ``metrics.query`` page carries (the store's ``MAX_PAGE``).
MAX_METRICS_PAGE = 200


@dataclass(frozen=True)
class Arg:
    """One argument: its kind and whether it must be present."""

    kind: str
    required: bool = True
    low: Optional[float] = None
    high: Optional[float] = None
    max_len: int = 256


@dataclass(frozen=True)
class Op:
    """One row of the op table."""

    name: str
    direction: str
    #: The roles that may send it to the supervisor (empty for a TO_CHILD op).
    callers: frozenset[str]
    args: Mapping[str, Arg] = field(default_factory=dict)


_BOTH = frozenset({FRONTDOOR, WORKER})
_FRONT = frozenset({FRONTDOOR})
_WORKER = frozenset({WORKER})
_NONE: frozenset[str] = frozenset()
_SLUG = Arg(_STR, max_len=64)
_ACTOR = Arg(_STR, required=False, max_len=64)
#: The acting admin, as the front door passes it from its authenticated
#: request (v0.20.0 T15): the account's name, the client's resolved address
#: and the audit reference of the ``started`` row the front door wrote first,
#: so the supervisor writes the outcome under the same reference.
_ACTOR_NAME = Arg(_STR, required=False, max_len=64)
_ADDRESS = Arg(_STR, required=False, max_len=64)
_REF = Arg(_STR, required=False, max_len=8)
_STORY_OP = {"slug": _SLUG, "actor": _ACTOR, "actor_name": _ACTOR_NAME, "address": _ADDRESS, "ref": _REF}

#: The most rows one ``sessions.list`` page carries (v0.20.0 T15). A row is
#: some 200 bytes, so a full page stays well inside ``MAX_FRAME``; a reply
#: that does not is answered ``too_large`` (the frame cap), never cut.
MAX_SESSION_PAGE = 200
_PAGE = {"limit": Arg(_INT, low=0, high=MAX_SESSION_PAGE), "offset": Arg(_INT, low=0, high=2**31)}
_SESSION_ID = Arg(_STR, max_len=64)
_ACCOUNT = Arg(_STR, max_len=32)

#: THE op table (spec §14.2). Each later task adds its ops here.
OPS: dict[str, Op] = {
    op.name: op
    for op in (
        Op("hello", TO_SUPERVISOR, _BOTH, {"token": Arg(_STR, max_len=128)}),
        Op("ready", TO_SUPERVISOR, _BOTH, {"port": Arg(_INT, low=1, high=65535)}),
        Op("health", TO_CHILD, _NONE),
        Op("drain", TO_CHILD, _NONE, {"seconds": Arg(_NUMBER, low=0, high=86400)}),
        Op("shutdown", TO_CHILD, _NONE),
        Op("stories.list", TO_SUPERVISOR, _FRONT),
        Op("stories.start", TO_SUPERVISOR, _FRONT, _STORY_OP),
        Op("stories.stop", TO_SUPERVISOR, _FRONT, _STORY_OP),
        Op("stories.restart", TO_SUPERVISOR, _FRONT, _STORY_OP),
        Op("ops.list", TO_SUPERVISOR, _FRONT),
        # T15 (spec §14.8): the panel's live sessions. The front door asks the
        # supervisor, which fans each out to the workers as the `worker.*`
        # request of the same name (refused from any child).
        Op("sessions.list", TO_SUPERVISOR, _FRONT, _PAGE),
        Op("sessions.end", TO_SUPERVISOR, _FRONT, {"slug": _SLUG, "session_id": _SESSION_ID}),
        Op("sessions.end_owner", TO_SUPERVISOR, _FRONT, {"account": _ACCOUNT}),
        Op("worker.sessions.list", TO_CHILD, _NONE, _PAGE),
        Op("worker.sessions.end", TO_CHILD, _NONE, {"session_id": _SESSION_ID}),
        Op("worker.sessions.end_owner", TO_CHILD, _NONE, {"account": _ACCOUNT}),
        # T11 (spec §14.4): the shared queue. `story` is stamped from the
        # connection; a lane.acquire is answered when granted (or `busy` at
        # its deadline, `other_window` at once), not when it arrives.
        Op(
            "lane.acquire",
            TO_SUPERVISOR,
            _WORKER,
            {
                "lane": Arg(_STR, max_len=32),
                "account": Arg(_STR, required=False, max_len=32),
                "timeout": Arg(_NUMBER, low=0, high=86400),
            },
        ),
        Op("lane.release", TO_SUPERVISOR, _WORKER, {"ticket": Arg(_STR, max_len=32)}),
        # T11 fix round 1: a waiting acquire withdrawn by the worker that
        # sent it (its player left), named by that request's id.
        Op("lane.cancel", TO_SUPERVISOR, _WORKER, {"id": Arg(_INT, low=1, high=2**53)}),
        # T11 fix round 1: the supervisor took back a ticket held past
        # max_hold_seconds; the worker acknowledges (or is hung).
        Op("lane.reclaimed", TO_CHILD, _NONE, {"ticket": Arg(_STR, max_len=32)}),
        Op("queue.snapshot", TO_SUPERVISOR, _FRONT),
        # T16 (spec §14.9): the model server. Health and the model list are
        # the supervisor's (cached 10 s), and an apply is an OPERATION,
        # answered {op_id} at once; the front door passes the acting admin
        # and the ref of the started row it wrote first, as for stories.*.
        Op("llm.health", TO_SUPERVISOR, _FRONT),
        Op("llm.models", TO_SUPERVISOR, _FRONT),
        Op(
            "llm.apply",
            TO_SUPERVISOR,
            _FRONT,
            {
                "changes": Arg(_CHANGES),
                "apply_anyway": Arg(_BOOL, required=False),
                # Fix round 1: the admin's "send the API key to this host"
                # (I2), and the admin layer's version the form was built on (I1).
                "send_key": Arg(_BOOL, required=False),
                "version": Arg(_STR, required=False, max_len=64),
                "actor": _ACTOR,
                "actor_name": _ACTOR_NAME,
                "address": _ADDRESS,
                "ref": _REF,
            },
        ),
        # T17 (spec §14.10): metrics. `metric` is a notification from either
        # child (its `process` and `story` stamped by the supervisor); the
        # front door asks for a named query, a page at a time, and for a
        # story's Oracle numbers, which the supervisor asks that story's
        # worker for as `worker.oracle.snapshot` (refused from any child).
        Op("metric", TO_SUPERVISOR, _BOTH, {"event": Arg(_EVENT)}),
        Op(
            "metrics.query",
            TO_SUPERVISOR,
            _FRONT,
            {
                "name": Arg(_STR, max_len=32),
                "params": Arg(_EVENT, required=False),
                "limit": Arg(_INT, low=0, high=MAX_METRICS_PAGE),
                "offset": Arg(_INT, low=0, high=2**31),
            },
        ),
        Op("oracle.snapshot", TO_SUPERVISOR, _FRONT, {"slug": _SLUG}),
        Op("worker.oracle.snapshot", TO_CHILD, _NONE),
        # T12 (spec §14.3): the supervisor's story table, sent to the front
        # door on every change, so routing a request costs no round trip.
        # A notification (no id), from the supervisor only: refused from any
        # child. `seq` orders them (the front door's pool may run two at once).
        Op(
            "stories.changed",
            TO_CHILD,
            _NONE,
            {"stories": Arg(_ROWS), "seq": Arg(_INT, low=0, high=2**53)},
        ),
    )
}


class BusError(RuntimeError):
    """A request was answered with an error, or could not be answered."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class BusRefusal(BusError):
    """Raised by a handler to answer ``{"ok": false, "error": code}``."""


class BusClosed(BusError):
    """The connection closed before the reply came."""

    def __init__(self) -> None:
        super().__init__("closed")


class BusTimeout(BusError):
    """No reply within the request's timeout."""

    def __init__(self) -> None:
        super().__init__("timeout")


class FrameError(ValueError):
    """An inbound frame over the cap (``too_large``) or not a JSON object (``malformed``)."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


# ---------------------------------------------------------------------------
# framing
# ---------------------------------------------------------------------------


def encode(message: Mapping[str, Any]) -> bytes:
    """
    One frame: compact JSON and a newline.

    Raises:
        FrameError: ``too_large`` past ``MAX_FRAME``.
    """
    data = json.dumps(message, separators=(",", ":"), ensure_ascii=False).encode("utf-8") + b"\n"
    if len(data) > MAX_FRAME:
        raise FrameError(TOO_LARGE)
    return data


#: The deepest nesting a frame may have. No op needs more than three levels;
#: a deeper frame is refused before ``json.loads`` sees it, because the
#: parser recurses and a few thousand ``[`` raise ``RecursionError`` (T10 fix
#: round 1: one such line from any local process killed the selector thread).
MAX_DEPTH = 16

_QUOTE, _BACKSLASH = 0x22, 0x5C
_OPEN = frozenset(b"[{")
_CLOSE = frozenset(b"]}")


def nesting_depth(line: bytes, limit: Optional[int] = None) -> int:
    """
    The deepest ``[``/``{`` nesting in ``line``, outside strings: ONE linear
    pass that tracks whether it is inside a string and after a backslash,
    as JSON's own lexer does (T10 fix round 2: a regex over strings was
    quadratic on ``"\\"\\"...`` and froze the selector for seconds). It never
    under-counts what the parser would nest: it splits strings exactly where
    the parser does on every prefix the parser reads, and a line that is not
    JSON at all is refused by the parser anyway. ``limit``: stop as soon as
    the depth passes it (the answer is then ``limit + 1``).
    """
    depth = deepest = 0
    in_string = escaped = False
    for byte in line:
        if in_string:
            if escaped:
                escaped = False
            elif byte == _BACKSLASH:
                escaped = True
            elif byte == _QUOTE:
                in_string = False
        elif byte == _QUOTE:
            in_string = True
        elif byte in _OPEN:
            depth += 1
            if depth > deepest:
                deepest = depth
                if limit is not None and deepest > limit:
                    return deepest
        elif byte in _CLOSE:
            depth -= 1
    return deepest


def decode(line: bytes) -> dict[str, Any]:
    """
    One frame's bytes (newline included or not) as its object. Never raises
    anything but ``FrameError``, whatever the bytes are.

    Raises:
        FrameError: ``too_large`` past the cap; ``malformed`` for anything
            but a JSON object (nested past ``MAX_DEPTH`` included).
    """
    if len(line) > MAX_FRAME:
        raise FrameError(TOO_LARGE)
    try:
        if nesting_depth(line, MAX_DEPTH) > MAX_DEPTH:
            raise FrameError("malformed")
        value = json.loads(line.decode("utf-8"))
    except FrameError:
        raise
    except Exception:  # noqa: BLE001 -- UnicodeDecodeError, ValueError, RecursionError, MemoryError ...
        raise FrameError("malformed") from None
    if not isinstance(value, dict):
        raise FrameError("malformed")
    return value


def read_frame(stream: Any) -> Optional[dict[str, Any]]:
    """
    The next frame from a blocking binary ``stream`` (a socket's ``makefile``),
    or None at a clean end of stream. Reads AT MOST ``MAX_FRAME`` bytes: the
    bounded ``readline`` is the only read, before anything parses.

    Raises:
        FrameError: a line with no newline within the cap (``too_large``), a
            line cut off by the end of the stream, or one that is not a JSON
            object (``malformed``).
    """
    line = stream.readline(MAX_FRAME)
    if not line:
        return None
    if not line.endswith(b"\n"):
        raise FrameError(TOO_LARGE if len(line) >= MAX_FRAME else "malformed")
    return decode(line)


def _encode_or_refuse(message: Mapping[str, Any]) -> bytes:
    """``encode``, raising ``BusError("too_large")`` (a request a caller can catch)."""
    try:
        return encode(message)
    except FrameError as exc:
        raise BusError(exc.code) from None


def reply_frame(request_id: Any, result: Optional[Mapping[str, Any]] = None, error: str = "") -> bytes:
    """A reply, or ``too_large`` in its place when the reply would not fit."""
    message: dict[str, Any] = (
        {"id": request_id, "ok": False, "error": error}
        if error
        else {"id": request_id, "ok": True, "result": dict(result or {})}
    )
    try:
        return encode(message)
    except (FrameError, TypeError, ValueError) as exc:
        code = TOO_LARGE if isinstance(exc, FrameError) else INTERNAL
        logger.warning(
            "[bus] Reply replaced (operation=reply, id=%s, error=%s)", request_id, code
        )
        return encode({"id": request_id, "ok": False, "error": code})


def _row_ok(row: Any) -> bool:
    """One ``stories.changed`` row: exactly ``slug``, ``state`` and ``port``, typed."""
    return (
        isinstance(row, dict)
        and set(row) == STORY_ROW_KEYS
        and isinstance(row["slug"], str)
        and len(row["slug"]) <= 64
        and isinstance(row["state"], str)
        and len(row["state"]) <= 32
        and isinstance(row["port"], int)
        and not isinstance(row["port"], bool)
        and 0 <= row["port"] <= 65535
    )


def _change_ok(key: Any, value: Any) -> bool:
    """One ``llm.apply`` change: a short dotted key and a scalar value."""
    if not isinstance(key, str) or not 0 < len(key) <= 64:
        return False
    if isinstance(value, str):
        return len(value) <= MAX_CHANGE_TEXT
    return isinstance(value, (bool, int, float))


def _kind_ok(arg: Arg, value: Any) -> bool:
    if arg.kind == _STR:
        return isinstance(value, str) and len(value) <= arg.max_len
    if arg.kind == _CHANGES:
        return (
            isinstance(value, dict)
            and 0 < len(value) <= MAX_CHANGES
            and all(_change_ok(k, v) for k, v in value.items())
        )
    if arg.kind == _ROWS:
        return isinstance(value, list) and len(value) <= MAX_STORY_ROWS and all(_row_ok(r) for r in value)
    if arg.kind == _EVENT:
        return (
            isinstance(value, dict)
            and len(value) <= MAX_EVENT_KEYS
            and all(isinstance(k, str) and len(k) <= 32 for k in value)
        )
    if isinstance(value, bool):
        return arg.kind == _BOOL
    if arg.kind == _INT:
        ok = isinstance(value, int)
    elif arg.kind == _NUMBER:
        ok = isinstance(value, (int, float))
    else:
        return False
    if not ok:
        return False
    if arg.low is not None and value < arg.low:
        return False
    return arg.high is None or value <= arg.high


def check_args(op: Op, args: Any, *, stamped: bool = False) -> dict[str, Any]:
    """
    ``args`` checked against ``op``'s schema.

    ``stamped``: the receiver is the supervisor, which drops ``process`` and
    ``story`` before the check (they are filled from the connection after).

    Raises:
        BusRefusal: ``bad_args``.
    """
    if args is None:
        args = {}
    if not isinstance(args, dict):
        raise BusRefusal(BAD_ARGS)
    given = {k: v for k, v in args.items() if not (stamped and k in STAMPED)}
    for name in given:
        if name not in op.args:
            raise BusRefusal(BAD_ARGS)
    for name, arg in op.args.items():
        if name not in given:
            if arg.required:
                raise BusRefusal(BAD_ARGS)
            continue
        if not _kind_ok(arg, given[name]):
            raise BusRefusal(BAD_ARGS)
    return given


# ---------------------------------------------------------------------------
# the supervisor's side
# ---------------------------------------------------------------------------


@dataclass
class TokenRecord:
    """What a minted token is. ``state``: ``unused`` -> ``live`` -> ``dead``."""

    token: str = field(repr=False)
    role: str
    story: str
    process: str
    state: str = "unused"


class _Pending:
    """One request awaiting its reply."""

    __slots__ = ("event", "reply", "late", "cancelled")

    def __init__(self) -> None:
        self.event = threading.Event()
        self.reply: Optional[dict[str, Any]] = None
        #: Set when the caller gave up: the reply, should it still come, is
        #: handed here (on the reader thread) instead of being dropped.
        self.late: Optional[Callable[[dict[str, Any]], None]] = None
        #: The caller's wait was called off (``request(cancel=)``).
        self.cancelled = False


class Connection:
    """One child's connection, as the supervisor holds it."""

    def __init__(self, conn_id: int, sock: socket.socket, deadline: float) -> None:
        self.id = conn_id
        self.sock = sock
        self.hello_deadline = deadline
        self.record: Optional[TokenRecord] = None
        self.inbuf = bytearray()
        self.outbuf = bytearray()
        self.closed = False
        self.pending: dict[int, _Pending] = {}
        self.ids = itertools.count(1)

    @property
    def role(self) -> str:
        return self.record.role if self.record else ""

    @property
    def story(self) -> str:
        return self.record.story if self.record else ""

    @property
    def process(self) -> str:
        return self.record.process if self.record else ""


Handler = Callable[[Connection, dict[str, Any]], Optional[Mapping[str, Any]]]
#: ``answer(result, error)``: a deferred request's reply, sent once.
Answer = Callable[[Optional[Mapping[str, Any]], str], None]
DeferredHandler = Callable[[Connection, dict[str, Any], Answer], None]


def _loopback_pair(timeout: float) -> Optional[tuple[socket.socket, socket.socket]]:
    """
    One attempt at a connected loopback pair, ``(accepted, connecting)``, or
    None when the connection was not accepted within ``timeout`` seconds.
    Only OUR connection is taken: one from any other peer (a stray client on
    a reused port) is closed and the wait goes on, to the same deadline.
    """
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        address = listener.getsockname()[:2]
        ours = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            ours.setblocking(False)
            try:
                ours.connect(address)
            except (BlockingIOError, InterruptedError):
                pass
            deadline = time.monotonic() + timeout
            while True:
                left = deadline - time.monotonic()
                if left <= 0:
                    ours.close()
                    return None
                listener.settimeout(left)
                try:
                    accepted, peer = listener.accept()
                except socket.timeout:
                    ours.close()
                    return None
                # By port: a loopback port names one socket, and the connecting
                # side may still report 0.0.0.0 as its host this early.
                try:
                    mine = ours.getsockname()[1]
                except OSError:
                    mine = None
                if peer[1] == mine:
                    accepted.setblocking(True)
                    ours.setblocking(True)
                    return accepted, ours
                accepted.close()  # not ours: never wire a stranger into the selector
        except BaseException:
            ours.close()
            raise
    finally:
        listener.close()


def wake_pair(
    timeout: Optional[float] = None, attempts: Optional[int] = None
) -> tuple[socket.socket, socket.socket]:
    """
    A connected socket pair for waking a selector, never an unbounded wait.

    With AF_UNIX (POSIX) it is ``socket.socketpair()``, which touches no
    network. Without it (Windows) the stdlib emulates one over loopback TCP
    and waits for its own connection in ``accept()`` with no bound, so a
    connect that never arrives hangs forever: here each attempt is bounded by
    ``timeout`` (``WAKE_PAIR_SECONDS``), accepts only its own peer, and
    ``attempts`` (``WAKE_PAIR_ATTEMPTS``) are made.

    Raises:
        OSError: no attempt was accepted in time.
    """
    if hasattr(socket, "AF_UNIX"):
        return socket.socketpair()
    timeout = float(WAKE_PAIR_SECONDS if timeout is None else timeout)
    tries = max(1, int(WAKE_PAIR_ATTEMPTS if attempts is None else attempts))
    for _ in range(tries):
        pair = _loopback_pair(timeout)
        if pair is not None:
            return pair
        logger.warning(
            "[bus] A loopback wake connection was not accepted within %.1fs; trying again (operation=start)",
            timeout,
        )
    raise OSError(f"no loopback wake pair: {tries} attempts of {timeout:.1f}s were not accepted")


class BusServer:
    """
    The supervisor's side: a loopback listener, the token table and one
    selector thread for every connection.

    Handlers (``handle``) run ON the selector thread and must not block: they
    record, answer from memory, or hand work to another thread. ``request``
    is for other threads (the health checks, the operations thread): it
    queues a frame and waits on its own event.
    """

    def __init__(self, *, host: str = "127.0.0.1", hello_seconds: float = HELLO_SECONDS) -> None:
        self.hello_seconds = float(hello_seconds)
        #: A leaf (engine/locks.py): guards the token table, the connections
        #: and their buffers and pending requests; its holder makes no
        #: blocking acquisition and no blocking I/O (the sockets are
        #: non-blocking).
        self._lock = threading.Lock()
        self._tokens: list[TokenRecord] = []
        self._conns: dict[int, Connection] = {}
        self._handlers: dict[str, Handler] = {}
        self._deferred: dict[str, DeferredHandler] = {}
        self._ids = itertools.count(1)
        self.on_hello: Optional[Callable[[Connection], None]] = None
        self.on_close: Optional[Callable[[Connection], None]] = None
        #: Asked before a valid, unused token is accepted (the supervisor:
        #: "is the child this token belongs to starting now?"); False refuses.
        self.admit: Optional[Callable[[TokenRecord], bool]] = None
        #: Called if the selector loop ends while the server is not closing.
        self.on_dead: Optional[Callable[[], None]] = None
        self._bad_log_at = 0.0
        self._bad_suppressed = 0
        self._listener = socket.create_server((host, 0))
        self._listener.setblocking(False)
        self.address: tuple[str, int] = self._listener.getsockname()[:2]
        try:
            # Bounded (``wake_pair``): the stdlib's Windows socketpair could
            # wait in accept() forever.
            self._wake_r, self._wake_w = wake_pair()
        except BaseException:
            self._listener.close()
            raise
        self._wake_r.setblocking(False)
        self._wake_w.setblocking(False)
        self._sel = selectors.DefaultSelector()
        self._sel.register(self._listener, selectors.EVENT_READ, "listen")
        self._sel.register(self._wake_r, selectors.EVENT_READ, "wake")
        self._stopping = threading.Event()
        self._thread: Optional[threading.Thread] = None

    @property
    def addr(self) -> str:
        """``host:port``, as a child's ``CLOCKWORK_BUS_ADDR``."""
        return f"{self.address[0]}:{self.address[1]}"

    # -- lifecycle ------------------------------------------------------------

    def start(self) -> "BusServer":
        thread = threading.Thread(target=self._run, name="bus-selector", daemon=True)
        self._thread = thread
        thread.start()
        return self

    def close(self, timeout: float = 5.0) -> None:
        """Stop the selector thread and close every connection."""
        self._stopping.set()
        self._wake()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout)
        for conn in list(self._conns.values()):
            self._close(conn)
        for sock in (self._listener, self._wake_r, self._wake_w):
            try:
                sock.close()
            except OSError:
                pass
        try:
            self._sel.close()
        except (OSError, ValueError):
            pass

    # -- the token table -------------------------------------------------------

    def mint(self, role: str, *, story: str = "", process: str = "") -> TokenRecord:
        """
        A fresh single-use token for one child start, and what it is. The
        caller hands ``record.token`` to that child's environment and nowhere
        else; it is never logged.
        """
        if role not in ROLES:
            raise ValueError(f"unknown role {role!r}")
        name = process or (FRONTDOOR if role == FRONTDOOR else f"worker-{story}")
        record = TokenRecord(token=secrets.token_hex(32), role=role, story=story, process=name)
        with self._lock:
            # A dead token is refused whether or not it is kept: forgotten
            # ones answer `unauthorized`, so the table does not grow with
            # every restart.
            self._tokens = [r for r in self._tokens if r.state != "dead"]
            self._tokens.append(record)
        return record

    def retire(self, token: str) -> None:
        """A token whose child start is over (it never connected): dead."""
        with self._lock:
            for record in self._tokens:
                if hmac.compare_digest(record.token.encode(), token.encode()):
                    record.state = "dead"

    def _match(self, token: Any) -> Optional[TokenRecord]:
        if not isinstance(token, str) or not token:
            return None
        given = token.encode("utf-8", "replace")
        found = None
        for record in self._tokens:  # every record compared: no early exit
            if hmac.compare_digest(record.token.encode(), given):
                found = record
        return found

    # -- handlers and requests -------------------------------------------------

    def handle(self, op: str, handler: Handler) -> None:
        """Answer ``op`` (a TO_SUPERVISOR row) with ``handler(conn, args)``."""
        if op not in OPS:
            raise ValueError(f"{op!r} is not in the op table")
        self._handlers[op] = handler

    def handle_deferred(self, op: str, handler: DeferredHandler) -> None:
        """
        Answer ``op`` LATER (v0.20.0 T11: a ``lane.acquire`` is answered when
        granted): ``handler(conn, args, answer)`` runs on the selector thread,
        must not block, and calls ``answer(result, error)`` once, from any
        thread, now or later. A ``BusRefusal`` it raises is answered at once.
        """
        if op not in OPS:
            raise ValueError(f"{op!r} is not in the op table")
        self._deferred[op] = handler

    def _answerer(self, conn: Connection, request_id: Any) -> Answer:
        def answer(result: Optional[Mapping[str, Any]], error: str = "") -> None:
            self.answer(conn, request_id, result, error)

        # The request it answers, so a later op (``lane.cancel``) can name it.
        answer.request_id = request_id  # type: ignore[attr-defined]
        return answer

    def answer(
        self, conn: Connection, request_id: Any, result: Optional[Mapping[str, Any]] = None, error: str = ""
    ) -> bool:
        """
        Send the reply to ``conn``'s request ``request_id`` (a deferred one),
        from any thread. Never blocks: the frame is queued and the selector
        writes it. False when the connection is gone (nothing is sent).
        """
        data = reply_frame(request_id, result, error=error)
        with self._lock:
            if conn.closed:
                return False
            conn.outbuf += data
        self._wake()
        return True

    def connections(self) -> list[Connection]:
        with self._lock:
            return [c for c in self._conns.values() if c.record is not None and not c.closed]

    def request(
        self, conn: Connection, op: str, args: Optional[Mapping[str, Any]] = None, timeout: float = 5.0
    ) -> dict[str, Any]:
        """
        Send ``op`` to a child and wait for its reply. Never call it on the
        selector thread.

        Raises:
            BusError: the child answered an error; BusTimeout; BusClosed.
        """
        spec = OPS[op]
        if spec.direction != TO_CHILD:
            raise ValueError(f"{op!r} is not sent to a child")
        payload = check_args(spec, dict(args or {}))
        pending = _Pending()
        with self._lock:
            if conn.closed:
                raise BusClosed()
            request_id = next(conn.ids)
            data = _encode_or_refuse({"id": request_id, "op": op, "args": payload})
            conn.pending[request_id] = pending
            conn.outbuf += data
        self._wake()
        if not pending.event.wait(timeout):
            with self._lock:
                conn.pending.pop(request_id, None)
            raise BusTimeout()
        reply = pending.reply
        if reply is None:
            raise BusClosed()
        if reply.get("ok") is True:
            result = reply.get("result")
            return result if isinstance(result, dict) else {}
        raise BusError(str(reply.get("error") or INTERNAL))

    def request_all(
        self, calls: list[tuple[Connection, str, Mapping[str, Any]]], timeout: float = 5.0
    ) -> list[Any]:
        """
        Send every ``(conn, op, args)`` at once and wait for them TOGETHER, up
        to one ``timeout`` for all (v0.20.0 T15 fix round 1, M7: the panel's
        fan-out asks every worker in parallel, so a hung one costs the page
        one deadline, not one per story). Each answer is its result dict or
        the ``BusError`` it came to (``BusTimeout``, ``BusClosed``, an error
        reply). Never call it on the selector thread.
        """
        deadline = time.monotonic() + max(0.0, timeout)
        # Every call checked BEFORE any is registered or sent (fix round 2,
        # N7): a bad one raises with nothing left pending.
        checked: list[tuple[Connection, str, dict[str, Any]]] = []
        for conn, op, args in calls:
            spec = OPS[op]
            if spec.direction != TO_CHILD:
                raise ValueError(f"{op!r} is not sent to a child")
            checked.append((conn, op, check_args(spec, dict(args or {}))))
        waits: list[Any] = []
        for conn, op, payload in checked:
            pending = _Pending()
            with self._lock:
                if conn.closed:
                    waits.append(BusClosed())
                    continue
                request_id = next(conn.ids)
                try:
                    data = _encode_or_refuse({"id": request_id, "op": op, "args": payload})
                except BusError as exc:
                    waits.append(exc)
                    continue
                conn.pending[request_id] = pending
                conn.outbuf += data
            waits.append((conn, request_id, pending))
        self._wake()
        answers: list[Any] = []
        for wait in waits:
            if isinstance(wait, BusError):
                answers.append(wait)
                continue
            conn, request_id, pending = wait
            if not pending.event.wait(max(0.0, deadline - time.monotonic())):
                with self._lock:
                    conn.pending.pop(request_id, None)
                answers.append(BusTimeout())
                continue
            reply = pending.reply
            if reply is None:
                answers.append(BusClosed())
            elif reply.get("ok") is True:
                result = reply.get("result")
                answers.append(result if isinstance(result, dict) else {})
            else:
                answers.append(BusError(str(reply.get("error") or INTERNAL)))
        return answers

    def notify(self, conn: Connection, op: str, args: Optional[Mapping[str, Any]] = None) -> None:
        """Send a notification (no ``id``, no reply). Raises ``BusError("too_large")``."""
        data = _encode_or_refuse({"op": op, "args": dict(args or {})})
        with self._lock:
            if conn.closed:
                return
            conn.outbuf += data
        self._wake()

    def disconnect(self, conn: Connection) -> None:
        """Close ``conn`` from another thread (the selector closes it)."""
        with self._lock:
            conn.hello_deadline = -1.0
        self._wake()

    # -- the selector thread ---------------------------------------------------

    def _wake(self) -> None:
        try:
            self._wake_w.send(b"\0")
        except (BlockingIOError, OSError):
            pass

    def _run(self) -> None:
        """
        The selector loop. NO BYTES FROM ANY CONNECTION MAY END IT (T10 fix
        round 1): every connection's step is guarded, and a failure closes
        that connection alone. Should the loop itself ever end while the
        server is not closing, ``on_dead`` is called (the supervisor then
        stops, exit 1): a deaf supervisor must not pretend to run.
        """
        try:
            while not self._stopping.is_set():
                self._turn()
        except BaseException:  # noqa: BLE001 -- the last resort, said once
            logger.critical("[bus] The selector loop failed (operation=select)", exc_info=True)
        finally:
            if not self._stopping.is_set():
                logger.critical("[bus] The bus stopped answering; the supervisor must stop (operation=select)")
                callback = self.on_dead
                if callback is not None:
                    try:
                        callback()
                    except Exception:  # noqa: BLE001
                        logger.exception("[bus] on_dead failed (operation=select)")

    def _guarded(self, conn: Connection, step: Callable[[Connection], None]) -> None:
        """Run one connection's ``step``; anything it raises closes that connection only."""
        try:
            step(conn)
        except Exception:  # noqa: BLE001 -- one connection's failure is its own
            self._bad_line(conn, "a frame the bus could not handle", exc_info=True)
            self._close(conn)

    def _turn(self) -> None:
        now = time.monotonic()
        timeout = 0.5
        with self._lock:
            conns = list(self._conns.values())
        for conn in conns:
            if conn.closed:
                continue
            if conn.record is None or conn.hello_deadline < 0:
                if now >= conn.hello_deadline:
                    if conn.record is None:
                        self._bad_line(conn, "no hello in time")
                    self._close(conn)
                    continue
                timeout = min(timeout, max(0.0, conn.hello_deadline - now))
            self._guarded(conn, self._flush)
            if conn.closed:
                continue
            events = selectors.EVENT_READ | (selectors.EVENT_WRITE if conn.outbuf else 0)
            try:
                self._sel.modify(conn.sock, events, conn)
            except (KeyError, ValueError, OSError):
                self._close(conn)
        try:
            ready = self._sel.select(timeout)
        except (OSError, ValueError):
            # Back off rather than spin (a select() past its limit, a closed fd).
            self._stopping.wait(ERROR_BACKOFF_SECONDS)
            return
        for key, mask in ready:
            if key.data == "listen":
                self._accept()
            elif key.data == "wake":
                try:
                    while self._wake_r.recv(4096):
                        pass
                except (BlockingIOError, OSError):
                    pass
            else:
                conn = key.data
                if mask & selectors.EVENT_READ:
                    self._guarded(conn, self._read)
                if not conn.closed and mask & selectors.EVENT_WRITE:
                    self._guarded(conn, self._flush)

    def _bad_line(self, conn: Connection, what: str, *, exc_info: bool = False) -> None:
        """One WARNING per ``BAD_LINE_LOG_SECONDS`` for refused connections; the rest counted."""
        now = time.monotonic()
        with self._lock:
            if now < self._bad_log_at:
                self._bad_suppressed += 1
                return
            suppressed, self._bad_suppressed = self._bad_suppressed, 0
            self._bad_log_at = now + BAD_LINE_LOG_SECONDS
        logger.warning(
            "[bus] Connection closed: %s (operation=read, process=%s%s)",
            what,
            conn.process or "(no hello)",
            f", {suppressed} more not logged" if suppressed else "",
            exc_info=exc_info,
        )

    def _accept(self) -> None:
        try:
            sock, _ = self._listener.accept()
        except (BlockingIOError, InterruptedError):
            return
        except OSError:
            # Out of descriptors, say: the listener stays readable, so wait
            # rather than spin on it.
            self._stopping.wait(ERROR_BACKOFF_SECONDS)
            return
        with self._lock:
            waiting = [c for c in self._conns.values() if c.record is None and not c.closed]
            oldest = min(waiting, key=lambda c: c.id) if len(waiting) >= MAX_PENDING else None
            full = oldest is None and len(self._conns) >= MAX_CONNECTIONS
        if oldest is not None:
            # At the pending cap the OLDEST connection still waiting for its
            # hello goes, never the newcomer: a real child says hello at once,
            # so idle sockets held open cannot lock children out (T10 fix
            # round 2, re-review N2).
            self._bad_line(oldest, "evicted: too many connections waiting for hello")
            self._close(oldest)
        if full:
            # Every slot is a child that said hello: the hard cap (a select()
            # set has a limit). The newcomer is closed at once.
            try:
                sock.close()
            except OSError:
                pass
            return
        sock.setblocking(False)
        conn = Connection(next(self._ids), sock, time.monotonic() + self.hello_seconds)
        with self._lock:
            self._conns[conn.id] = conn
        try:
            self._sel.register(sock, selectors.EVENT_READ, conn)
        except (OSError, ValueError):
            self._close(conn)

    def _read(self, conn: Connection) -> None:
        # Never more than the cap can hold: a partial frame plus this read is
        # at most MAX_FRAME bytes, so a peer cannot grow the buffer past it.
        try:
            data = conn.sock.recv(max(1, MAX_FRAME - len(conn.inbuf)))
        except (BlockingIOError, InterruptedError):
            return
        except OSError:
            self._close(conn)
            return
        if not data:
            self._close(conn)
            return
        conn.inbuf += data
        while not conn.closed:
            end = conn.inbuf.find(b"\n")
            if end < 0:
                break
            line = bytes(conn.inbuf[: end + 1])
            del conn.inbuf[: end + 1]
            try:
                message = decode(line)
            except FrameError as exc:
                self._bad_line(conn, f"a {exc.code} frame")
                self._close(conn)
                return
            self._dispatch(conn, message)
        if not conn.closed and len(conn.inbuf) >= MAX_FRAME:
            self._bad_line(conn, "a too_large frame")
            self._close(conn)

    def _flush(self, conn: Connection) -> None:
        with self._lock:
            if conn.closed or not conn.outbuf:
                return
            try:
                sent = conn.sock.send(conn.outbuf)
            except (BlockingIOError, InterruptedError):
                return
            except OSError:
                sent = -1
            if sent > 0:
                del conn.outbuf[:sent]
        if sent < 0:
            self._close(conn)

    def _send(self, conn: Connection, data: bytes) -> None:
        with self._lock:
            if conn.closed:
                return
            conn.outbuf += data
        self._flush(conn)

    def _close(self, conn: Connection) -> None:
        with self._lock:
            if conn.closed:
                return
            conn.closed = True
            self._conns.pop(conn.id, None)
            if conn.record is not None and conn.record.state == "live":
                conn.record.state = "dead"
            pending = list(conn.pending.values())
            conn.pending.clear()
        try:
            self._sel.unregister(conn.sock)
        except (KeyError, ValueError, OSError):
            pass
        try:
            conn.sock.close()
        except OSError:
            pass
        for waiter in pending:
            waiter.event.set()  # reply None: closed
        if conn.record is not None and self.on_close is not None:
            try:
                self.on_close(conn)
            except Exception:  # noqa: BLE001 -- a callback must not stop the selector
                logger.exception("[bus] on_close failed (operation=close, process=%s)", conn.process)

    def _dispatch(self, conn: Connection, message: dict[str, Any]) -> None:
        if conn.record is None:
            # Spec §14.2: the FIRST message is hello; anything else closes it.
            self._hello(conn, message)
            return
        if "op" not in message:
            self._reply_to_request(conn, message)
            return
        request_id = message.get("id")
        op_name = message.get("op")
        try:
            spec = OPS.get(op_name) if isinstance(op_name, str) else None
            if spec is None:
                logger.warning(
                    "[bus] Refused an unknown op (operation=dispatch, process=%s, error=unknown_op)",
                    conn.process,
                )
                raise BusRefusal(UNKNOWN_OP)
            if spec.direction != TO_SUPERVISOR or conn.role not in spec.callers:
                logger.warning(
                    "[bus] Refused an op its role may not call (operation=dispatch, op=%s, "
                    "process=%s, role=%s, error=forbidden)",
                    spec.name,
                    conn.process,
                    conn.role,
                )
                raise BusRefusal(FORBIDDEN)
            try:
                args = check_args(spec, message.get("args"), stamped=True)
            except BusRefusal:
                logger.warning(
                    "[bus] Refused bad arguments (operation=dispatch, op=%s, process=%s, "
                    "error=bad_args)",
                    spec.name,
                    conn.process,
                )
                raise
            args["process"] = conn.process
            args["story"] = conn.story
            deferred = self._deferred.get(spec.name)
            if deferred is not None:
                if request_id is None:
                    raise BusRefusal(BAD_ARGS)  # nothing to answer later: refused, unanswered
                deferred(conn, args, self._answerer(conn, request_id))
                return
            handler = self._handlers.get(spec.name)
            if handler is None:
                logger.warning(
                    "[bus] Refused an op nothing answers (operation=dispatch, op=%s, "
                    "process=%s, error=unknown_op)",
                    spec.name,
                    conn.process,
                )
                raise BusRefusal(UNKNOWN_OP)
            result = handler(conn, args)
        except BusRefusal as refusal:
            if request_id is not None:
                self._send(conn, reply_frame(request_id, error=refusal.code))
            return
        except Exception:  # noqa: BLE001 -- one bad handler must not stop the selector
            logger.exception(
                "[bus] A handler failed (operation=dispatch, op=%s, process=%s)",
                op_name,
                conn.process,
            )
            if request_id is not None:
                self._send(conn, reply_frame(request_id, error=INTERNAL))
            return
        if request_id is not None:
            self._send(conn, reply_frame(request_id, result or {}))

    def _hello(self, conn: Connection, message: dict[str, Any]) -> None:
        request_id = message.get("id")
        if message.get("op") != "hello":
            self._bad_line(conn, "the first message was not hello")
            self._close(conn)
            return
        args = message.get("args")
        token = args.get("token") if isinstance(args, dict) else None
        with self._lock:
            record = self._match(token)
            usable = record is not None and record.state == "unused"
        # The owner's say (the supervisor: is that child starting now?),
        # asked holding no bus lock -- its own lock comes first in its order.
        admit = self.admit
        if usable and admit is not None:
            try:
                usable = bool(admit(record))  # type: ignore[arg-type]
            except Exception:  # noqa: BLE001 -- a broken check refuses
                logger.exception("[bus] admit failed (operation=hello)")
                usable = False
        with self._lock:
            accepted = usable and record is not None and record.state == "unused"
            if accepted:
                assert record is not None
                record.state = "live"
                conn.record = record
        if not accepted:
            code = UNAUTHORIZED if record is None else REFUSED
            self._bad_line(
                conn,
                f"hello refused (error={code}"
                + ("" if record is None else f", for={record.process}, credential={record.state}")
                + ")",
            )
            data = reply_frame(request_id, error=code)
            with self._lock:
                conn.outbuf += data
            self._flush(conn)
            self._close(conn)
            return
        assert conn.record is not None
        logger.info(
            "[bus] Hello (operation=hello, process=%s, role=%s)", conn.process, conn.role
        )
        self._send(
            conn,
            reply_frame(request_id, {"role": conn.role, "story": conn.story, "process": conn.process}),
        )
        if self.on_hello is not None:
            try:
                self.on_hello(conn)
            except Exception:  # noqa: BLE001
                logger.exception("[bus] on_hello failed (operation=hello, process=%s)", conn.process)

    def _reply_to_request(self, conn: Connection, message: dict[str, Any]) -> None:
        request_id = message.get("id")
        with self._lock:
            pending = conn.pending.pop(request_id, None) if isinstance(request_id, int) else None
        if pending is None:
            return  # a reply to a request that gave up waiting
        pending.reply = message
        pending.event.set()


# ---------------------------------------------------------------------------
# a child's side
# ---------------------------------------------------------------------------


ChildHandler = Callable[[dict[str, Any]], Optional[Mapping[str, Any]]]


def _exit_process(code: int) -> None:
    """Flush the log handlers and leave at once (a reader thread cannot ``sys.exit``)."""
    for handler in list(logging.getLogger().handlers):
        try:
            handler.flush()
        except Exception:  # noqa: BLE001
            pass
    os._exit(code)


class BusClient:
    """
    A child's side of the bus: one connection, one reader thread, a pool of
    four for the requests the supervisor sends.

    ``on_lost`` runs once when the link closes without ``close`` or a
    ``shutdown`` (the lifeline; by default the process exits
    ``LIFELINE_EXIT_CODE``). ``on_shutdown`` runs after the reply to a
    ``shutdown`` request is sent (by default the process exits 0).
    """

    def __init__(self, addr: str, token: str, *, proxy_token: str = "", pool_size: int = 4) -> None:
        host, _, port = addr.rpartition(":")
        self._address = (host or "127.0.0.1", int(port))
        self._token = token
        #: The front door's proxy token (T12), kept here and nowhere else.
        self.proxy_token = proxy_token
        self._pool_size = pool_size
        self._sock: Optional[socket.socket] = None
        self._file: Any = None
        #: A leaf (engine/locks.py): the pending table and the socket's
        #: writes; held across one ``sendall`` of a frame, nothing else.
        self._lock = threading.Lock()
        self._pending: dict[int, _Pending] = {}
        self._ids = itertools.count(1)
        self._handlers: dict[str, ChildHandler] = {}
        self._reader: Optional[threading.Thread] = None
        self._pool: Optional[ThreadPoolExecutor] = None
        self._health_pool: Optional[ThreadPoolExecutor] = None
        self._closing = False
        self._lost = threading.Event()
        self.on_lost: Callable[[], None] = lambda: _exit_process(LIFELINE_EXIT_CODE)
        self.on_shutdown: Callable[[], None] = lambda: _exit_process(0)
        self.hello: dict[str, Any] = {}

    @classmethod
    def from_environment(cls, environ: Optional[MutableMapping[str, str]] = None) -> Optional["BusClient"]:
        """
        A client for ``CLOCKWORK_BUS_ADDR``, or None when it is unset. Reads
        the bus and proxy tokens ONCE and deletes both from ``environ``
        (``os.environ`` by default), so no grandchild inherits them.
        """
        env = os.environ if environ is None else environ
        token = env.pop(BUS_TOKEN_ENV, "") or ""
        proxy = env.pop(PROXY_TOKEN_ENV, "") or ""
        addr = str(env.get(BUS_ADDR_ENV, "") or "").strip()
        if not addr:
            return None
        return cls(addr, token, proxy_token=proxy)

    def handle(self, op: str, handler: ChildHandler) -> None:
        """Answer the supervisor's ``op`` (a TO_CHILD row) on the request pool."""
        if OPS.get(op) is None or OPS[op].direction != TO_CHILD:
            raise ValueError(f"{op!r} is not a request the supervisor sends")
        self._handlers[op] = handler

    @property
    def connected(self) -> bool:
        return self._sock is not None and not self._lost.is_set()

    def connect(self, timeout: Optional[float] = None, attempts: Optional[int] = None) -> dict[str, Any]:
        """
        Connect and say ``hello``; start the reader and the pool.

        On loopback a connect can be lost, or its hello answered late
        (v0.21.1). So attempts are started ``timeout`` (``CONNECT_SECONDS``)
        apart, timed from the first start whatever became of the one before,
        up to ``attempts`` (``CONNECT_ATTEMPTS``), each on a fresh socket; and
        EVERY attempt still open is listened to, so the first answer that
        accepts the token wins and the rest are closed. One deadline,
        ``attempts * timeout`` from the first start, bounds it all: every
        connect, read and wait. An attempt is never given up while it may
        still answer, because the token is single-use -- a late hello the
        server accepted holds it, and every later attempt is refused -- so a
        refusal starts no new attempt and ends the connect once no other
        attempt is open. A refused connect (no supervisor listening) ends it
        when no attempt is open.

        Raises:
            BusError: the token was refused (``unauthorized``, ``refused``);
                ``BusClosed`` when no attempt was answered.
            OSError: no supervisor listening.
        """
        timeout = float(CONNECT_SECONDS if timeout is None else timeout)
        tries = max(1, int(CONNECT_ATTEMPTS if attempts is None else attempts))
        token, self._token = self._token, ""
        try:
            sock, stream, reply = self._hello(token, timeout, tries)
        finally:
            del token
        sock.settimeout(None)
        self._sock = sock
        self._file = stream
        result = reply.get("result")
        self.hello = result if isinstance(result, dict) else {}
        self._pool = ThreadPoolExecutor(max_workers=self._pool_size, thread_name_prefix="bus-request")
        self._health_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="bus-health")
        reader =threading.Thread(target=self._read_loop, name="bus-reader", daemon=True)
        self._reader = reader
        reader.start()
        return self.hello

    def _hello(self, token: str, timeout: float, tries: int) -> tuple[socket.socket, Any, dict[str, Any]]:
        """
        ``connect``'s attempts (see there): the winning ``(sock, stream,
        reply)``. One deadline, ``tries * timeout`` from the first start,
        bounds every wait, every connect and every read; attempt N starts
        ``(N - 1) * timeout`` after the first, however the one before ended.
        """
        selector = selectors.DefaultSelector()
        open_: list[socket.socket] = []
        refusal = ""
        started = 0
        first = time.monotonic()
        deadline = first + tries * timeout
        pause = threading.Event()
        try:
            while True:
                now = time.monotonic()
                if now >= deadline:
                    break
                next_start = first + started * timeout
                if started < tries and not refusal and now >= next_start:
                    if started:
                        logger.warning(
                            "[bus] The supervisor's bus has not answered; attempt %d of %d (operation=connect)",
                            started + 1,
                            tries,
                        )
                    started += 1
                    sock = self._dial(token, min(timeout, deadline - now), refuse_ok=bool(open_))
                    if sock is not None:
                        selector.register(sock, selectors.EVENT_READ)
                        open_.append(sock)
                    continue
                if not open_ and (started >= tries or refusal):
                    break
                # Until the next start (or the deadline), whichever is first.
                until = deadline if (started >= tries or refusal) else min(next_start, deadline)
                if not open_:
                    pause.wait(max(0.0, until - now))  # every attempt lost: wait for the next one's slot
                    continue
                for key, _events in selector.select(max(0.0, until - now)):
                    sock = key.fileobj  # type: ignore[assignment]
                    selector.unregister(sock)
                    open_.remove(sock)
                    sock.settimeout(max(0.001, deadline - time.monotonic()))
                    stream = sock.makefile("rb")
                    try:
                        reply = read_frame(stream)
                    except (OSError, FrameError):
                        reply = None
                    if reply is not None and reply.get("ok") is True:
                        if started > 1:
                            logger.info(
                                "[bus] Connected on one of %d attempts (operation=connect)", started
                            )
                        return sock, stream, reply
                    stream.close()
                    sock.close()
                    if reply is not None:
                        refusal = str(reply.get("error") or "closed")
            if refusal:
                raise BusError(refusal)
            raise BusClosed()
        finally:
            for sock in open_:
                sock.close()
            selector.close()

    def _dial(self, token: str, timeout: float, *, refuse_ok: bool) -> Optional[socket.socket]:
        """
        One attempt's connect and hello, each within ``timeout``: the socket,
        or None when the connect was lost (or refused while ``refuse_ok``:
        another attempt is still open).

        Raises:
            ConnectionRefusedError: nothing listens at the address.
        """
        try:
            sock = socket.create_connection(self._address, timeout=timeout)
        except ConnectionRefusedError:
            if refuse_ok:
                return None
            raise
        except OSError:
            return None  # a timeout, or a reset on the way
        try:
            sock.sendall(encode({"id": 0, "op": "hello", "args": {"token": token}}))
        except OSError:
            sock.close()
            return None
        return sock

    def request(
        self,
        op: str,
        args: Optional[Mapping[str, Any]] = None,
        timeout: float = 10.0,
        *,
        on_late: Optional[Callable[[dict[str, Any]], None]] = None,
        cancel: Any = None,
        on_cancel: Optional[Callable[[int], None]] = None,
    ) -> dict[str, Any]:
        """
        Send ``op`` to the supervisor and wait for its reply.

        ``on_late`` (v0.20.0 T11): when this caller stops waiting (its
        ``timeout``, a cancel, or anything raised while it waits) and the
        reply still comes, the reply is handed to ``on_late`` -- on the reader
        thread, which it must not block -- rather than dropped. ``RemoteLanes``
        uses it to give back a grant nobody is waiting for.

        ``cancel`` (T11 fix round 1): an object with ``add_hook``/``remove_hook``
        (``engine.llm.gate.CancelToken``). When it fires, the wait ends at
        once (``BusError("cancelled")``) and ``on_cancel(request_id)`` runs,
        to tell the supervisor (it must not block).

        Raises:
            BusError: an error reply, or ``cancelled``; BusTimeout; BusClosed.
        """
        pending = _Pending()
        with self._lock:
            if self._sock is None or self._lost.is_set():
                raise BusClosed()
            request_id = next(self._ids)
            data = _encode_or_refuse({"id": request_id, "op": op, "args": dict(args or {})})
            self._pending[request_id] = pending
            try:
                self._sock.sendall(data)
            except OSError:
                self._pending.pop(request_id, None)
                raise BusClosed() from None
        hook: Optional[Callable[[], None]] = None
        if cancel is not None:

            def call_off() -> None:
                self._call_off(request_id, pending, on_late, on_cancel)

            hook = call_off
            cancel.add_hook(hook)
        try:
            arrived = pending.event.wait(timeout)
        except BaseException:
            self._give_up(request_id, pending, on_late)
            raise
        finally:
            if hook is not None:
                cancel.remove_hook(hook)
        if pending.cancelled:
            raise BusError("cancelled")
        if not arrived:
            self._give_up(request_id, pending, on_late)
            raise BusTimeout()
        reply = pending.reply
        if reply is None:
            raise BusClosed()
        if reply.get("ok") is True:
            result = reply.get("result")
            return result if isinstance(result, dict) else {}
        raise BusError(str(reply.get("error") or INTERNAL))

    def _give_up(
        self, request_id: int, pending: _Pending, on_late: Optional[Callable[[dict[str, Any]], None]]
    ) -> None:
        """The caller stopped waiting: forget the request, or keep it for ``on_late``."""
        arrived: Optional[dict[str, Any]] = None
        with self._lock:
            if pending.event.is_set():
                arrived = pending.reply  # came just as the caller gave up
            elif on_late is not None and request_id in self._pending:
                pending.late = on_late
            else:
                self._pending.pop(request_id, None)
        if arrived is not None and on_late is not None:
            on_late(arrived)

    def _call_off(
        self,
        request_id: int,
        pending: _Pending,
        on_late: Optional[Callable[[dict[str, Any]], None]],
        on_cancel: Optional[Callable[[int], None]],
    ) -> None:
        """A cancel fired: end the wait now; a reply still to come goes to ``on_late``."""
        with self._lock:
            if pending.event.is_set() or request_id not in self._pending:
                return  # answered already: the caller takes the answer
            pending.cancelled = True
            pending.late = on_late
            pending.event.set()
        if on_cancel is not None:
            try:
                on_cancel(request_id)
            except Exception:  # noqa: BLE001 -- the wait is over either way
                logger.exception("[bus] A cancel's notice failed (operation=cancel)")

    def send_request(self, op: str, args: Optional[Mapping[str, Any]] = None) -> None:
        """
        Send a request whose reply nobody waits for (it is dropped when it
        comes). For the reader thread, which must never wait on a reply of
        its own. Raises ``BusClosed``.
        """
        with self._lock:
            sock = self._sock
            if sock is None or self._lost.is_set():
                raise BusClosed()
            data = _encode_or_refuse({"id": next(self._ids), "op": op, "args": dict(args or {})})
            try:
                sock.sendall(data)
            except OSError:
                raise BusClosed() from None

    def notify(self, op: str, args: Optional[Mapping[str, Any]] = None) -> None:
        """A notification to the supervisor (no reply). Raises ``BusError("too_large")``."""
        self._write(_encode_or_refuse({"op": op, "args": dict(args or {})}))

    def close(self, timeout: float = 5.0) -> None:
        """Close the link on purpose: no lifeline exit."""
        self._closing = True
        sock = self._sock
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            sock.close()
        reader = self._reader
        if reader is not None and reader is not threading.current_thread():
            reader.join(timeout)
        if self._file is not None:
            try:
                self._file.close()
            except OSError:
                pass
        for pool in (self._pool, self._health_pool):
            if pool is not None:
                pool.shutdown(wait=False, cancel_futures=True)

    # -- internals ---------------------------------------------------------------

    def _write(self, data: bytes) -> None:
        with self._lock:
            sock = self._sock
            if sock is None:
                raise BusClosed()
            try:
                sock.sendall(data)
            except OSError:
                raise BusClosed() from None

    def _read_loop(self) -> None:
        reason = "the supervisor closed it"
        try:
            while True:
                try:
                    message = read_frame(self._file)
                except FrameError as exc:
                    reason = f"a {exc.code} frame"
                    break
                except Exception:  # noqa: BLE001 -- OSError, a closed file, anything: the link is gone
                    break
                if message is None:
                    break
                try:
                    if "op" in message:
                        self._on_request(message)
                    else:
                        self._on_reply(message)
                except Exception:  # noqa: BLE001 -- a frame the child cannot route ends the link
                    reason = "a frame that could not be handled"
                    logger.exception("[bus] A frame from the supervisor failed (operation=read)")
                    break
        finally:
            self._lose(reason)

    def _lose(self, reason: str) -> None:
        self._lost.set()
        with self._lock:
            pending = list(self._pending.values())
            self._pending.clear()
        for waiter in pending:
            waiter.event.set()
        if self._closing:
            return
        logger.error(
            "[bus] The link to the supervisor is lost (%s): exiting (operation=lifeline)", reason
        )
        try:
            self.on_lost()
        except Exception:  # noqa: BLE001
            logger.exception("[bus] The lifeline hook failed (operation=lifeline)")

    def _on_reply(self, message: dict[str, Any]) -> None:
        request_id = message.get("id")
        with self._lock:
            pending = self._pending.pop(request_id, None) if isinstance(request_id, int) else None
            late = pending.late if pending is not None else None
            if pending is not None:
                pending.reply = message
                pending.event.set()
        if late is not None:
            try:
                late(message)
            except Exception:  # noqa: BLE001 -- the reader outlives one late reply
                logger.exception("[bus] A late reply's handler failed (operation=read)")

    def _on_request(self, message: dict[str, Any]) -> None:
        # `health` has a thread of its own: a pool busy with drains (and,
        # later, sessions.* calls) must not fail a bus health check and get
        # a busy worker restarted (T10 fix round 1; spec §14.3).
        pool = self._health_pool if message.get("op") == "health" else self._pool
        if pool is None:
            return
        try:
            pool.submit(self._answer, message)
        except RuntimeError:  # the pool is shut down: closing
            pass

    def _answer(self, message: dict[str, Any]) -> None:
        request_id = message.get("id")
        op_name = message.get("op")
        spec = OPS.get(op_name) if isinstance(op_name, str) else None
        error = ""
        result: Optional[Mapping[str, Any]] = None
        try:
            if spec is None:
                raise BusRefusal(UNKNOWN_OP)
            if spec.direction != TO_CHILD:
                raise BusRefusal(FORBIDDEN)
            args = check_args(spec, message.get("args"))
            handler = self._handlers.get(spec.name)
            if handler is None:
                if spec.name != "shutdown":
                    raise BusRefusal(UNKNOWN_OP)
                result = {}
            else:
                result = handler(args)
        except BusRefusal as refusal:
            error = refusal.code
            logger.warning(
                "[bus] Refused a request from the supervisor (operation=answer, error=%s)", error
            )
        except Exception:  # noqa: BLE001
            logger.exception("[bus] A handler failed (operation=answer, op=%s)", op_name)
            error = INTERNAL
        if request_id is not None:
            try:
                self._write(reply_frame(request_id, result, error=error))
            except BusClosed:
                return
        if spec is not None and spec.name == "shutdown" and not error:
            self._closing = True
            logger.info("[bus] Shutdown asked by the supervisor (operation=shutdown)")
            self.on_shutdown()


__all__ = [
    "Answer",
    "BAD_ARGS",
    "BUS_ADDR_ENV",
    "BUS_ROLE_ENV",
    "BUS_TOKEN_ENV",
    "BusClient",
    "BusClosed",
    "BusError",
    "BusRefusal",
    "BusServer",
    "BusTimeout",
    "Connection",
    "FORBIDDEN",
    "FRONTDOOR",
    "FrameError",
    "HELLO_SECONDS",
    "LIFELINE_EXIT_CODE",
    "MAX_FRAME",
    "MAX_STORY_ROWS",
    "OPS",
    "PROXY_TOKEN_ENV",
    "STORY_ROW_KEYS",
    "TOO_LARGE",
    "UNKNOWN_OP",
    "WAKE_PAIR_ATTEMPTS",
    "WAKE_PAIR_SECONDS",
    "WORKER",
    "check_args",
    "decode",
    "encode",
    "read_frame",
    "reply_frame",
    "wake_pair",
]
