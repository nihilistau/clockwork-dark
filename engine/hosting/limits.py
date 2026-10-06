"""
Hosted Mode: Rate Limits
========================

In-process token buckets (spec §6.5). One hosted process serves every
player (spec §5.1), so a bucket in memory is the whole count.

THE ACTIONS BUCKET (``ActionLimiter``, v0.20.0 T9): per account,
``rate_limits.actions_per_minute`` across new game, choice, resume, save
write and transcribe, on both doors (``engine/hosting/gate.py`` for HTTP,
``engine/hosting/sockets.py`` for the socket). Every action costs the same,
a rest included (AGENTS.md rule 6).

THE INPUT CAPS (``over_cap``): a typed action (``custom_text``) longer than
``hosting.max_input_chars`` and a ``player_name`` longer than
``PLAYER_NAME_MAX_CHARS`` are refused, never cut (survey finding 14). A
length, and nothing else (rule 12).

THE LOGIN BUCKETS are three, and an attempt needs a token from EACH:

- per address (``address_key``): one address guessing many names. An IPv6
  address counts by its /64, because a client is handed the whole prefix
  and could otherwise step through 2^64 addresses; an IPv4 address (an
  IPv4-mapped IPv6 one included) counts by itself;
- per ``(address, username)``: one address guessing ONE name, at HALF the
  per-address count (at least one), so it binds before the address bucket
  does -- a guesser who concentrates on one friend is slowed sooner than
  one spraying names, while a real player's typo leaves room to retry;
- for the whole server (``logins_per_minute_all``), but ONLY for an address
  with a FAILED login in the last ``FAILURE_WINDOW_SECONDS``
  (``record_failure``): together, the addresses that are guessing get that
  many attempts a minute, and an address with no recent failure is exempt.

Never per username alone, which would let anyone lock a friend out by typing
their name from anywhere. A third party exhausting ``(their address,
"alice")`` leaves ``(alice's address, "alice")`` full.

WHY THE SERVER-WIDE BUCKET SPARES CLEAN ADDRESSES (T7 fix round 2). Counting
every attempt let a dozen cheap addresses (one home IPv6 /56 holds 256 /64s)
spend it and refuse every real login, indefinitely. Guessing produces
failures and a real player's login mostly does not, so the cap falls on the
guessers. A clean address is still bounded by its own buckets above, and
every attempt by the hashing slots (``hosting.max_concurrent_logins``), which
is what bounds the CPU and memory.

The address is ``request.remote_addr``: the peer, unless
``hosting.trusted_proxies`` is set, in which case ProxyFix has put the
client's forwarded address there (``engine/hosting/gate.py``).

THE TURN SLOTS (``TurnSlots``, v0.20.0 T12). An HTTP request that may run a
turn (new game, choice, transcribe) holds its server thread for as long as
its turn waits in the model server's queue -- up to
``hosting.queue_wait_seconds`` -- and then runs. Under gunicorn's ``gthread``
pool (``hosting.threads``) enough of them would hold every thread, and login,
the static files and every other request would wait behind them. So at most
``threads - RESERVED_THREADS`` such requests are in flight at once, per
process (a worker, and the front door, which carries every story's); one
more is refused 429 at once (``SERVER_BUSY``), never queued; and one account
may have only ``PER_ACCOUNT_TURNS`` (1) of them in flight, its next refused
429 at once (``TURN_IN_FLIGHT``), so no one account can take every slot. A
turn's body is read in full (``read_body``, within
``hosting.body_read_seconds``, at most ``MAX_CONTENT_LENGTH``) BEFORE it asks
for a slot: a client that trickles its body is answered 408 and never holds
one (v0.20.0 T12 fix round 1). Socket turns are not counted: Socket.IO runs
each event on a thread of its own, outside the pool.

THE LONG HOLDS (``LongHolds``, v0.20.0 T13, from T12's review M3). A turn is
not the only request that keeps a pool thread: a relayed WebSocket holds one
for its whole life, and a Socket.IO polling ``GET`` for up to ``ping_interval
+ ping_timeout``. The FRONT DOOR counts all three against one ``LongHolds``
of ``threads - RESERVED_THREADS`` places (its ``TurnSlots`` takes its place
there too), so ``RESERVED_THREADS`` threads are always left for login, the
picker, the static files and every short request, however many tabs are
open: one more WebSocket or poll is answered 503 (``SERVER_FULL``) at once.
Every request a worker serves comes through the front door, so a worker is
held to the same count without one of its own.

THE BODY-READ DEADLINE UNDER GUNICORN (``read_body``, v0.20.0 T13). Werkzeug's
input has ``read1`` (one ``recv`` per call), so the socket timeout set before
each read bounds the whole body. gunicorn's ``wsgi.input`` has none: its
``read(n)`` loops ``recv`` until it has ``n`` bytes, each ``recv`` restarting
the timeout, so a client sending a byte just inside it could stretch one read
for ever. Where the input has no ``read1`` and the server exposes the socket,
a timer shuts the socket's READ side at the deadline (``socket.shutdown``
wakes the blocked ``recv``), and the body is answered 408 as before.

THE ADMIN ACTIONS BUCKET (v0.20.0 T14, spec §14.7): an ``ActionLimiter`` of
``rate_limits.admin_actions_per_minute`` per admin, spent by every ``POST``
under ``/admin`` (``engine/hosting/admin/guard.py``) and by each error
lookup, ``GET /admin/errors/find`` (v0.20.0 T18), answered 429
(``ADMIN_SLOW_DOWN``).

Thread-safe: each ``LoginLimiter``, ``ActionLimiter``, ``TurnSlots`` and
``LongHolds`` has one lock, a LEAF (engine/locks.py): nothing else is taken
while it is held (``TurnSlots`` takes its ``LongHolds`` place with its own
lock released).

Version: v0.5.0 [2026-10-05]
"""

from __future__ import annotations

import ipaddress
import threading
import time
from typing import Any, Callable, Hashable, Optional

#: How many buckets a limiter keeps before it drops the ones that have
#: refilled completely (a full bucket is the same as no bucket).
MAX_TRACKED_BUCKETS = 4096

#: The prefix an IPv6 client is counted by.
IPV6_PREFIX = 64

#: The key of the one server-wide bucket.
ALL = "*"

#: How long after a failed login an address counts against the server-wide
#: bucket: the buckets' own minute.
FAILURE_WINDOW_SECONDS = 60.0


def address_key(address: str) -> str:
    """
    The bucket an address counts against: an IPv6 address's /64 (``2001:db8::/64``),
    an IPv4 address itself (an IPv4-mapped IPv6 address as its IPv4), and any
    text that is not an address as it is.
    """
    text = str(address or "").strip()
    try:
        parsed = ipaddress.ip_address(text.split("%", 1)[0])
    except ValueError:
        return text
    if isinstance(parsed, ipaddress.IPv6Address):
        if parsed.ipv4_mapped is not None:
            return str(parsed.ipv4_mapped)
        return str(ipaddress.ip_network(f"{parsed}/{IPV6_PREFIX}", strict=False))
    return str(parsed)


class TokenBuckets:
    """
    Many token buckets of one size, keyed by anything hashable.

    Args:
        per_minute: Capacity, refilled evenly over a minute.
        clock: Seconds, monotonic (tests pass their own).
    """

    def __init__(self, per_minute: int, *, clock: Optional[Callable[[], float]] = None) -> None:
        self.capacity = float(max(1, int(per_minute)))
        self.rate = self.capacity / 60.0
        self.clock = clock or time.monotonic
        #: key -> (tokens, when they were counted)
        self._buckets: dict[Hashable, tuple[float, float]] = {}

    def level(self, key: Hashable, now: float) -> float:
        """Tokens in ``key``'s bucket at ``now`` (full when never used)."""
        tokens, stamp = self._buckets.get(key, (self.capacity, now))
        return min(self.capacity, tokens + (now - stamp) * self.rate)

    def take(self, key: Hashable, now: float) -> None:
        """Spend one token from ``key`` (the caller checked ``level``)."""
        self._buckets[key] = (self.level(key, now) - 1.0, now)

    def prune(self, now: float) -> None:
        """Forget every bucket that has refilled, once there are too many."""
        if len(self._buckets) <= MAX_TRACKED_BUCKETS:
            return
        full = [key for key in self._buckets if self.level(key, now) >= self.capacity]
        for key in full:
            del self._buckets[key]


#: A ``player_name``'s longest, in characters (spec §6.5).
PLAYER_NAME_MAX_CHARS = 40

#: What an action over ``rate_limits.actions_per_minute`` is told: HTTP 429,
#: or the socket's ``turn_error`` with ``busy: false``.
SLOW_DOWN = "You are acting faster than this server allows. Wait a moment, then try again."

#: What an admin past ``rate_limits.admin_actions_per_minute`` is told (429).
ADMIN_SLOW_DOWN = "Too many admin actions in a minute. Wait a moment, then try again."


def too_long(limit: int) -> str:
    """What an input over its cap is told (spec §6.5): HTTP 400, or ``turn_error``."""
    return f"That is longer than this server accepts ({int(limit)} characters)."


#: Every text field a client sends in a request or event body that reaches
#: the engine, held to ``hosting.max_input_chars`` (T9 fix round 1): the typed
#: action, the chosen option's id (an unknown one becomes a sentence in the
#: prompt), a manual save's label (written into the save index), the
#: archetype and the seed.
TEXT_FIELDS = ("custom_text", "choice_id", "slot", "archetype", "seed")


def over_cap(body: Any, max_input_chars: int) -> Optional[str]:
    """
    The refusal for a request body with a text field (``TEXT_FIELDS``) longer
    than ``max_input_chars``, or a ``player_name`` longer than
    ``PLAYER_NAME_MAX_CHARS``; None when every field is within its cap.

    REFUSED, NEVER TRUNCATED: a cut sentence is an action the player did not
    choose. And a LENGTH, in characters, and nothing else (AGENTS.md rule 12):
    nothing here reads what the text says. A value that is not a string is
    measured as the string the door would make of it.
    """
    if not isinstance(body, dict):
        return None
    caps = [(key, int(max_input_chars)) for key in TEXT_FIELDS]
    caps.append(("player_name", PLAYER_NAME_MAX_CHARS))
    for key, limit in caps:
        value = body.get(key)
        if value is not None and len(value if isinstance(value, str) else str(value)) > limit:
            return too_long(limit)
    return None


class ActionLimiter:
    """
    The actions bucket (spec §6.5): per account,
    ``hosting.rate_limits.actions_per_minute`` across new game, choice,
    resume, save write and transcribe, over HTTP and the socket alike.

    Every action costs one token, whatever it is: a rest is counted exactly
    like any other choice (AGENTS.md rule 6, never gate rest differently).

    Thread-safe: one lock, a LEAF (engine/locks.py).

    Args:
        per_minute: The bucket's size, refilled evenly over a minute.
        clock: Seconds, monotonic (tests pass their own).
    """

    def __init__(self, per_minute: int, *, clock: Optional[Callable[[], float]] = None) -> None:
        self.buckets = TokenBuckets(per_minute, clock=clock)
        self.clock = clock or time.monotonic
        self._lock = threading.Lock()

    def allow(self, account_id: str) -> bool:
        """Whether ``account_id`` may act now; if so, one token is spent."""
        with self._lock:
            now = self.clock()
            if self.buckets.level(account_id, now) < 1.0:
                return False
            self.buckets.take(account_id, now)
            self.buckets.prune(now)
            return True


class LoginLimiter:
    """
    The login buckets (spec §6.5).

    Args:
        per_minute: ``rate_limits.logins_per_minute``, per address; the
            ``(address, name)`` bucket holds half of it (at least one).
        all_per_minute: ``rate_limits.logins_per_minute_all``, shared by
            every address with a recent failed login; None leaves the
            server-wide bucket out.
        clock: Seconds, monotonic (tests pass their own).
    """

    def __init__(
        self,
        per_minute: int,
        *,
        all_per_minute: Optional[int] = None,
        clock: Optional[Callable[[], float]] = None,
    ) -> None:
        self.address = TokenBuckets(per_minute, clock=clock)
        self.pair = TokenBuckets(max(1, (int(per_minute) + 1) // 2), clock=clock)
        self.everyone = TokenBuckets(all_per_minute, clock=clock) if all_per_minute else None
        self.clock = clock or time.monotonic
        self._lock = threading.Lock()
        #: address bucket -> when its last login failed
        self._failed: dict[str, float] = {}
        #: When ``_failed`` was last pruned of entries past the window.
        self._failed_pruned = self.clock()

    def _recently_failed(self, address_bucket: str, now: float) -> bool:
        when = self._failed.get(address_bucket)
        return when is not None and now - when < FAILURE_WINDOW_SECONDS

    def allow(self, address: str, username: str) -> bool:
        """
        Whether a login attempt from ``address`` for ``username`` may go
        ahead; if so, one token is spent from each bucket that applies (the
        server-wide one only for an address with a recent failure). A refused
        attempt spends nothing.
        """
        address_bucket = address_key(address)
        pair_key = (address_bucket, str(username or "").strip().lower()[:64])
        with self._lock:
            now = self.clock()
            if self.pair.level(pair_key, now) < 1.0 or self.address.level(address_bucket, now) < 1.0:
                return False
            guessing = self.everyone is not None and self._recently_failed(address_bucket, now)
            if guessing and self.everyone.level(ALL, now) < 1.0:
                return False
            self.pair.take(pair_key, now)
            self.address.take(address_bucket, now)
            if guessing:
                self.everyone.take(ALL, now)
            self.pair.prune(now)
            self.address.prune(now)
            return True

    def record_failure(self, address: str) -> None:
        """A login from ``address`` failed: it counts against the server-wide bucket for a while."""
        address_bucket = address_key(address)
        with self._lock:
            now = self.clock()
            self._failed[address_bucket] = now
            # Pruned BY AGE, at most once a window (v0.20.0 T8): a failure
            # older than the window counts for nothing, so nothing is kept
            # past it, however few addresses there are.
            if now - self._failed_pruned >= FAILURE_WINDOW_SECONDS or (
                len(self._failed) > MAX_TRACKED_BUCKETS
            ):
                self._failed_pruned = now
                for key in [k for k, t in self._failed.items() if now - t >= FAILURE_WINDOW_SECONDS]:
                    del self._failed[key]


#: Threads of each process's pool kept free of HTTP turns, for login, the
#: static files, polling and everything else (``TurnSlots``).
RESERVED_THREADS = 4

#: What an HTTP turn is told when every turn slot of the process is taken.
SERVER_BUSY = "Every turn slot on this server is in use. Try again in a moment."


def turn_slot_limit(threads: int) -> int:
    """How many HTTP turns a process of ``threads`` threads lets in at once (at least one)."""
    return max(1, int(threads) - RESERVED_THREADS)


#: HTTP turns one account may have in flight at once, per process (fix round 1).
PER_ACCOUNT_TURNS = 1

#: What an account's second HTTP turn in flight is told.
TURN_IN_FLIGHT = "Your last turn is still on its way. Wait for it, then try again."

#: ``TurnSlots.try_enter``'s refusals.
FULL = "full"
ACCOUNT = "account"


#: What a WebSocket or a polling request is told when every long hold of the
#: front door is in use (``LongHolds``).
SERVER_FULL = "Every connection this server keeps open is in use. Try again in a moment."


def too_many_connections(cap: int) -> str:
    """What an account past ``hosting.max_connections_per_account`` is told."""
    return (
        f"You already have {int(cap)} game connections open on this server, the most it "
        "allows one player. Close a tab, then try again."
    )


class LongHolds:
    """
    At most ``limit`` requests that hold a pool thread for long -- relayed
    WebSockets, polling ``GET``s and HTTP turns -- in flight at once in this
    process (the front door's; see the module docstring), and, for a
    connection taken FOR an account (a WebSocket or a poll; v0.20.0 T13 fix
    round 1), at most ``per_account`` of them that account's
    (``hosting.max_connections_per_account``), so no one player can take every
    place. ``try_take`` never waits.

    Thread-safe: one lock, a LEAF (engine/locks.py).
    """

    def __init__(self, limit: int, *, per_account: Optional[int] = None) -> None:
        self.limit = max(1, int(limit))
        self.per_account = max(1, int(per_account)) if per_account is not None else None
        self._lock = threading.Lock()
        self._inside = 0
        #: account -> {connection key -> [polls, sockets, upgrade_joined]};
        #: the key "" is a request that names no Engine.IO session.
        self._by_account: dict[str, dict[str, list[int]]] = {}

    @staticmethod
    def _count(conn: str, record: list[int]) -> int:
        """The connections one record counts as (see ``try_take``)."""
        polls, sockets, joined = record
        shared = 1 if (conn and joined and polls >= 1 and sockets >= 1) else 0
        return polls + sockets - shared

    @classmethod
    def _connections(cls, held: dict[str, list[int]]) -> int:
        """One account's connections."""
        return sum(cls._count(conn, record) for conn, record in held.items())

    def try_take(self, account: str = "", connection: str = "", *, upgrade: bool = False) -> str:
        """
        Take a place: "" when taken; ``ACCOUNT`` when ``account`` (if named)
        would hold more than ``per_account`` connections; ``FULL`` when all
        ``limit`` are in use.

        ``connection``: the request's Engine.IO session id (the ``sid`` of a
        poll, or of a WebSocket upgrading from polling), when it names one;
        ``upgrade``: the request is that WebSocket. Every hold counts toward
        the account's cap but ONE: a session's single WebSocket upgrade joins
        the poll it upgrades for free (v0.20.0 T13 re-review N1), since during
        the upgrade the tab's last poll and its WebSocket are open together.
        A second WebSocket, or any further poll, naming a held session counts
        as a connection of its own (T14 fix round 1, I1: engineio does not
        refuse concurrent polls of one session, so a free join for every
        poll let one account hold every place). Each hold still takes its
        own place among the ``limit``, being a thread each.
        """
        key = str(account or "")
        conn = str(connection or "")
        with self._lock:
            held = self._by_account.get(key, {})
            record = held.get(conn) if conn else None
            free = bool(upgrade and record is not None and record[1] == 0 and record[0] >= 1 and not record[2])
            if (
                key
                and self.per_account is not None
                and not free
                and self._connections(held) >= self.per_account
            ):
                return ACCOUNT
            if self._inside >= self.limit:
                return FULL
            self._inside += 1
            if key:
                record = self._by_account.setdefault(key, {}).setdefault(conn, [0, 0, 0])
                if upgrade:
                    record[1] += 1
                    if free:
                        record[2] = 1
                else:
                    record[0] += 1
            return ""

    def give_back(self, account: str = "", connection: str = "", *, upgrade: bool = False) -> None:
        """Give a place back (once per successful ``try_take``, with the same arguments)."""
        key = str(account or "")
        conn = str(connection or "")
        with self._lock:
            self._inside = max(0, self._inside - 1)
            if not key:
                return
            held = self._by_account.get(key)
            record = held.get(conn) if held is not None else None
            if held is None or record is None:
                return
            index = 1 if upgrade else 0
            record[index] = max(0, record[index] - 1)
            if record[0] == 0 or record[1] == 0:
                record[2] = 0  # the upgrade's pairing is over
            if record[0] == 0 and record[1] == 0:
                held.pop(conn, None)
            if not held:
                self._by_account.pop(key, None)

    def of_account(self, account: str) -> int:
        """Connections ``account`` holds now (a WebSocket upgrading from its poll counts once with it)."""
        with self._lock:
            return self._connections(self._by_account.get(str(account), {}))

    @property
    def inside(self) -> int:
        """Long holds in flight now."""
        with self._lock:
            return self._inside


class TurnSlots:
    """
    At most ``limit`` HTTP turns in flight in this process, and at most
    ``per_account`` of them one account's (see the module docstring).
    ``try_enter`` never waits: a full house, or an account already sending
    a turn, is answered at once. A turn's body is read BEFORE it asks for a
    slot (``read_body``), so a client trickling its body never holds one.
    ``pool``: the process's ``LongHolds`` (the front door's), which a turn
    takes a place in as well, so turns, WebSockets and polls share one count.

    Thread-safe: one lock, a LEAF (engine/locks.py); the ``pool`` place is
    taken with it released.
    """

    def __init__(
        self, limit: int, *, per_account: int = PER_ACCOUNT_TURNS, pool: Optional[LongHolds] = None
    ) -> None:
        self.limit = max(1, int(limit))
        self.per_account = max(1, int(per_account))
        self.pool = pool
        self._lock = threading.Lock()
        self._inside = 0
        self._by_account: dict[str, int] = {}

    def try_enter(self, account: str) -> str:
        """
        Take a slot for ``account``: "" when taken; ``ACCOUNT`` when that
        account already has ``per_account`` in flight, ``FULL`` when every
        slot (or every place of ``pool``) is in use (nothing taken either way).
        """
        key = str(account)
        with self._lock:
            if self._by_account.get(key, 0) >= self.per_account:
                return ACCOUNT
            if self._inside >= self.limit:
                return FULL
            self._inside += 1
            self._by_account[key] = self._by_account.get(key, 0) + 1
        if self.pool is not None and self.pool.try_take():
            self._release(key)
            return FULL
        return ""

    def _release(self, key: str) -> None:
        with self._lock:
            self._inside = max(0, self._inside - 1)
            left = self._by_account.get(key, 0) - 1
            if left > 0:
                self._by_account[key] = left
            else:
                self._by_account.pop(key, None)

    def leave(self, account: str) -> None:
        """Give ``account``'s slot back (once per successful ``try_enter``)."""
        self._release(str(account))
        if self.pool is not None:
            self.pool.give_back()

    @property
    def inside(self) -> int:
        """HTTP turns in flight now."""
        with self._lock:
            return self._inside


def refusal_text(reason: str) -> str:
    """What a turn ``TurnSlots`` refused is told."""
    return TURN_IN_FLIGHT if reason == ACCOUNT else SERVER_BUSY


class BodyTooLarge(Exception):
    """A request body past ``MAX_CONTENT_LENGTH`` (answered 413)."""


class BodyTimeout(Exception):
    """A request body that did not arrive within ``hosting.body_read_seconds`` (answered 408)."""


#: What a body that did not arrive in time is told.
BODY_TIMEOUT = "The request did not arrive in time."

#: How much of a body one read asks for.
_BODY_CHUNK = 64 * 1024


def _client_socket(environ: dict[str, Any]) -> Any:
    """The client's socket, where the server exposes it (Werkzeug, gunicorn); else None."""
    for key in ("werkzeug.socket", "gunicorn.socket"):
        sock = environ.get(key)
        if sock is not None and hasattr(sock, "settimeout"):
            return sock
    return None


class _ReadWatchdog:
    """
    At ``seconds`` from now, shut ``sock``'s read side (``SHUT_RD``): a
    ``recv`` blocked in a server's own read loop wakes with nothing, and
    ``read_body`` answers 408 (see the module docstring). The write side is
    left open for that answer. ``cancel`` once the body is in.
    """

    def __init__(self, sock: Any, seconds: float) -> None:
        self._sock = sock
        self.fired = False
        self._timer = threading.Timer(max(0.0, seconds), self._fire)
        self._timer.daemon = True
        self._timer.name = "hosting-body-deadline"
        self._timer.start()

    def _fire(self) -> None:
        import socket

        self.fired = True
        try:
            self._sock.shutdown(socket.SHUT_RD)
        except OSError:  # already closed by the client: the read has ended anyway
            pass

    def cancel(self) -> None:
        self._timer.cancel()
        self._timer.join(_WATCHDOG_JOIN_SECONDS)


#: How long ``_ReadWatchdog.cancel`` waits for a timer that is firing.
_WATCHDOG_JOIN_SECONDS = 5.0


def read_body(environ: dict[str, Any], limit: Optional[int], seconds: float) -> bytes:
    """
    Read a request's whole body from ``environ["wsgi.input"]`` within
    ``seconds`` (``hosting.body_read_seconds``), counted for the WHOLE body,
    not per read, and at most ``limit`` bytes; then put it back as a
    ``BytesIO`` with its ``CONTENT_LENGTH``, so the app reads it as ever.
    (A chunked body never reaches it in hosted mode: both doors refuse
    ``Transfer-Encoding`` 411 first, ``gate.refuse_chunked``, fix round 2.)
    Called for a turn route BEFORE its turn slot is taken (fix round 1):
    a client that trickles a body holds a thread for ``seconds`` at most,
    and never a slot. The client's socket's timeout is set to what is left
    before each read, where the server exposes the socket; a body that runs
    out leaves it set, so the server closes that connection.

    Raises:
        BodyTooLarge: past ``limit``.
        BodyTimeout: not all there within ``seconds``.
    """
    import io

    raw_length = str(environ.get("CONTENT_LENGTH") or "").strip()
    length: Optional[int] = int(raw_length) if raw_length.isdigit() else None
    terminated = bool(environ.get("wsgi.input_terminated"))
    if length is None and not terminated:
        return b""
    if length is not None and limit is not None and length > limit:
        raise BodyTooLarge()
    stream = environ["wsgi.input"]
    want = length if length is not None else (int(limit) + 1 if limit is not None else None)
    reader = getattr(stream, "read1", None)
    sock = _client_socket(environ)
    before = sock.gettimeout() if sock is not None else None
    budget = max(0.0, float(seconds))
    deadline = time.monotonic() + budget
    watchdog: Optional[_ReadWatchdog] = None
    if reader is None:
        reader = stream.read
        if sock is not None:
            # gunicorn (T13): one read() loops recv() until it has its size,
            # so the per-read timeout alone does not bound the body.
            watchdog = _ReadWatchdog(sock, budget)
    chunks: list[bytes] = []
    got = 0
    try:
        while want is None or got < want:
            left = deadline - time.monotonic()
            if left <= 0 or (watchdog is not None and watchdog.fired):
                raise BodyTimeout()
            if sock is not None:
                sock.settimeout(left)
            size = _BODY_CHUNK if want is None else min(_BODY_CHUNK, want - got)
            try:
                data = reader(size)
            except (TimeoutError, OSError):
                raise BodyTimeout() from None
            if watchdog is not None and watchdog.fired:
                raise BodyTimeout()
            if not data:
                break
            chunks.append(data)
            got += len(data)
            if limit is not None and got > limit:
                raise BodyTooLarge()
    finally:
        if watchdog is not None:
            watchdog.cancel()
    if sock is not None:
        sock.settimeout(before)
    body = b"".join(chunks)
    environ["wsgi.input"] = io.BytesIO(body)
    environ["CONTENT_LENGTH"] = str(len(body))
    return body


__all__ = [
    "ALL",
    "ActionLimiter",
    "FAILURE_WINDOW_SECONDS",
    "IPV6_PREFIX",
    "LoginLimiter",
    "LongHolds",
    "MAX_TRACKED_BUCKETS",
    "PLAYER_NAME_MAX_CHARS",
    "ACCOUNT",
    "ADMIN_SLOW_DOWN",
    "BODY_TIMEOUT",
    "BodyTimeout",
    "BodyTooLarge",
    "FULL",
    "PER_ACCOUNT_TURNS",
    "RESERVED_THREADS",
    "SERVER_BUSY",
    "SERVER_FULL",
    "TURN_IN_FLIGHT",
    "SLOW_DOWN",
    "TEXT_FIELDS",
    "TokenBuckets",
    "TurnSlots",
    "address_key",
    "over_cap",
    "read_body",
    "refusal_text",
    "too_long",
    "turn_slot_limit",
]
