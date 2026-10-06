"""
Hosted Mode: Accounts
=====================

The operator's accounts, in ``<storage.root>/hosting/users.json`` (spec §6.1).
THIS MODULE IS ITS ONLY WRITER, and every caller goes through it:
``scripts/users.py``, ``POST /account`` and (later) the admin panel.

A row::

    {"id": "u_3f9a1c2b7d4e", "name": "alice", "hash": "scrypt:...",
     "created": 1790000000.0, "epoch": 1, "disabled": false,
     "admin": false, "must_change": false}

- ``id`` is minted once from ``secrets`` (``u_`` + 12 hex digits), never from
  the name, and is the only thing that becomes a path
  (``<root>/users/<id>/``). A row whose id is not of that form is refused
  when the file is read (``ID_RE``), so a hand-edited ``"../.."`` never
  reaches a path.
- ``name`` matches ``^[a-z0-9_-]{2,32}$``.
- ``hash`` is Werkzeug's scrypt (salted, compared in constant time).
- ``epoch`` goes up with a password change, a password reset, a disable and
  a change of role (v0.20.0 T14). A login cookie carries the epoch it was
  issued under, and one carrying an older epoch is dead, so each logs the
  account out everywhere.
- ``admin`` (the admin panel's role) and ``must_change`` (a password an admin
  generated, which its owner must replace at their next login) read as false
  when absent (spec §14.6), so a ``users.json`` from before them needs no
  migration; a row's unknown fields are carried through every write.

THE ADMIN GUARDS ARE INSIDE THE LOCK (spec §14.6). Revoking a role, a
disable and a removal refuse to act on the caller's own account
(``actor_id``) and on the last enabled admin, checked in the SAME
read-modify-write as the change: two admins demoting each other at once
cannot both pass the check and leave none. The CLI passes ``force=True``
after its terminal confirmation: an operator with a shell owns the server.

ONE WRITER ACROSS PROCESSES. Every change is a read-modify-write under an
inter-process lock on ``users.json.lock`` beside the file: an operating-system
lock (``fcntl.flock`` on POSIX, ``msvcrt.locking`` on Windows) on a file that
stays in place. The system releases it when its holder's handle closes, and
when the holder dies, so a killed process never leaves a lock behind and
nothing ever has to judge a lock "stale" and remove it -- removal by path was
the race in v0.20.0 T7's first ``O_CREAT | O_EXCL`` design (a breaker, or a
holder whose lock had been broken, could delete the NEXT holder's lock), and
there is no atomic compare-and-remove of a file to close it with. A holder
can release only its own lock: it is held through the holder's own handle.
So the CLI's ``passwd`` racing a browser's password change cannot lose either
update. A password is hashed BEFORE the lock is taken.

The write is ``write_json_atomic`` WITHOUT a backup: a ``users.json.bak``
would keep the hash a password change retires, and one left by an earlier
build is removed after the replace. On POSIX the hosting directory is 0700
and every file this module makes in it 0600 (``secure_dir``).

A READ IS CACHED on the file's ``(st_ino, st_mtime_ns, st_ctime_ns,
st_size)``: the atomic replace makes a new inode each time, so another
process's same-size rewrite within one clock tick is still seen. This
module's own writes drop the cache directly.

NO ACCOUNT ENUMERATION. ``verify`` runs ``check_password_hash`` against
``DUMMY_HASH`` for a name that does not exist (and for a disabled account),
so a wrong name costs the same work as a wrong password.

BOUNDED HASHING. Each scrypt costs about 32 MiB and 100 ms, so a store built
with ``hash_slots`` (a semaphore, ``hosting.max_concurrent_logins``) hashes
at most that many passwords at once; a caller that waits past
``HASH_WAIT_SECONDS`` gets ``LoginBusy`` before any hashing, whatever the
name.

Version: v0.3.0 [2026-10-05]
"""

from __future__ import annotations

import errno
import filecmp
import json
import logging
import os
import re
import secrets
import shutil
import threading
import time
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, ContextManager, Iterator, Optional

from werkzeug.security import check_password_hash, generate_password_hash

from engine.persistence.atomic import write_json_atomic

logger = logging.getLogger(__name__)

#: An account name: lower-case letters, digits, ``_`` and ``-``, 2 to 32.
NAME_RE = re.compile(r"[a-z0-9_-]{2,32}")

#: An account id, the only account value that becomes a path.
ID_RE = re.compile(r"u_[0-9a-f]{12}")

#: The shortest password accepted, in characters. No composition rules.
MIN_PASSWORD_CHARS = 10

#: The longest password hashed, in characters: a bound on the work one login
#: form can ask for, not a composition rule.
MAX_PASSWORD_CHARS = 1024

#: How long a writer waits for the accounts lock before it gives up.
LOCK_WAIT_SECONDS = 60.0

#: How long a starting server retries its look at ``adopt.lock`` while another
#: server's own look holds it (``hold_server_lock``, v0.20.0 T13).
PROBE_RETRY_SECONDS = 2.0

#: The pause between those retries.
PROBE_RETRY_PAUSE_SECONDS = 0.01

#: How long a login waits for a free hashing slot before it is told "busy".
HASH_WAIT_SECONDS = 2.0

#: ``users.json``'s shape version.
FILE_VERSION = 1

#: The file a running hosted server holds locked for its whole life
#: (``server-<pid>.lock``), so ``adopt`` can refuse while one runs.
SERVER_LOCK_GLOB = "server-*.lock"

#: Checked against when the name is unknown or the account disabled, so a
#: failed login costs the same whatever failed. Hashed once at import, with
#: the same method and cost as every real hash (``generate_password_hash``'s
#: defaults), from a random password no one knows.
DUMMY_HASH = generate_password_hash(secrets.token_urlsafe(24))


class AccountError(ValueError):
    """A refused account operation; the message is safe to show the operator."""


class AccountsFileError(RuntimeError):
    """``users.json`` exists and cannot be read as accounts. Fail closed."""


class LastAdmin(AccountError):
    """The change would leave no enabled admin (spec §14.6)."""


class SelfAction(AccountError):
    """An admin tried to revoke, disable or delete their own account from the panel."""


#: What a change that would leave no admin is told.
LAST_ADMIN = "at least one admin must remain; use scripts/users.py"

#: What an admin acting on their own account is told.
NOT_YOURSELF = "an admin cannot revoke, disable or delete their own account from the panel"

#: The characters of entropy a generated one-time password carries
#: (``secrets.token_urlsafe(12)``: 16 characters, 96 bits).
GENERATED_PASSWORD_BYTES = 12


def generate_password() -> str:
    """A one-time password (``secrets``); shown once, stored only as its hash."""
    return secrets.token_urlsafe(GENERATED_PASSWORD_BYTES)


class LoginBusy(RuntimeError):
    """Every hashing slot stayed taken for ``HASH_WAIT_SECONDS``; nothing was hashed."""


@dataclass(frozen=True)
class Account:
    """One account, as read. ``hash`` never leaves this module's callers' hands."""

    id: str
    name: str
    hash: str
    created: float
    epoch: int
    disabled: bool
    #: The admin panel's role (spec §14.6); absent reads false.
    admin: bool = False
    #: A password an admin generated, to be replaced at the next login.
    must_change: bool = False

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "Account":
        return cls(
            id=str(row["id"]),
            name=str(row["name"]),
            hash=str(row["hash"]),
            created=float(row.get("created") or 0.0),
            epoch=int(row.get("epoch") or 1),
            disabled=bool(row.get("disabled", False)),
            admin=row.get("admin", False) is True,
            # Fail closed both ways: only a literal true grants the role, and
            # any truthy value keeps the account at the change-password page.
            must_change=bool(row.get("must_change", False)),
        )


def check_name(name: Any) -> str:
    """The name, or ``AccountError`` naming the rule."""
    text = str(name or "")
    if not NAME_RE.fullmatch(text):
        raise AccountError(
            "a name is 2 to 32 characters of a-z, 0-9, '_' and '-' (lower case)"
        )
    return text


def check_id(account_id: Any) -> str:
    """The id, or ``AccountError``: ``u_`` and 12 lower-case hex digits."""
    text = str(account_id or "")
    if not ID_RE.fullmatch(text):
        raise AccountError(f"not an account id: {text[:40]!r}")
    return text


def check_password(password: Any) -> str:
    """The password, or ``AccountError`` naming the rule. Never logged."""
    if not isinstance(password, str) or len(password) < MIN_PASSWORD_CHARS:
        raise AccountError(f"a password is at least {MIN_PASSWORD_CHARS} characters")
    if len(password) > MAX_PASSWORD_CHARS:
        raise AccountError(f"a password is at most {MAX_PASSWORD_CHARS} characters")
    return password


def _retrying(action: Callable[[], Any], *, attempts: int = 50) -> Any:
    """
    ``action()``, retried on ``PermissionError``: on Windows ``os.replace``
    fails while another process holds the file open for a read, and a read
    fails for the instant a replace holds it (engine/persistence/atomic.py).
    Every other error, and the last attempt's, is raised.
    """
    for attempt in range(attempts):
        try:
            return action()
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(0.01)
    return None


def mint_id(taken: Any = ()) -> str:
    """A new account id: ``u_`` + 12 hex digits from ``secrets``, not in ``taken``."""
    while True:
        candidate = "u_" + secrets.token_hex(6)
        if candidate not in taken:
            return candidate


# -- files, modes and operating-system locks ----------------------------------


def secure_dir(directory: Path) -> Path:
    """Make ``directory`` (and parents); on POSIX, 0700 even when it existed."""
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name == "posix":
        os.chmod(directory, 0o700)
    return directory


def open_private(path: Path) -> int:
    """Open (creating) ``path`` for read and write, 0600 on POSIX."""
    fd = os.open(str(path), os.O_RDWR | os.O_CREAT, 0o600)
    if os.name == "posix":
        os.fchmod(fd, 0o600)
    return fd


def try_lock(fd: int) -> bool:
    """Take the exclusive system lock on ``fd`` without waiting; whether it was got."""
    try:
        if os.name == "nt":
            import msvcrt

            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    return True


def unlock(fd: int) -> None:
    """Release ``fd``'s system lock (closing the handle releases it too)."""
    try:
        if os.name == "nt":
            import msvcrt

            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_UN)
    except OSError:
        logger.warning("[hosting] A system lock would not release (operation=unlock)")


#: What a hosted server that starts during an ``adopt`` is told.
ADOPT_RUNNING = (
    "scripts/users.py adopt is moving runs in this storage root; start the "
    "server again once it has finished"
)

#: What ``adopt`` is told when the hosting lock is taken.
ADOPT_LOCK_BUSY = (
    "the hosting lock is taken (another adopt is running, or a server is "
    "starting); try again in a moment"
)


def hold_server_lock(directory: Path) -> int:
    """
    Take ``<directory>/server-<pid>-<random>.lock`` for this server's life and
    return its handle (never closed by the engine: the system frees it when
    the process ends). ``adopt`` refuses while any such lock is held.

    THE HANDSHAKE WITH ``adopt``. The server takes its own lock FIRST and only
    then looks at ``adopt.lock``; ``adopt`` takes ``adopt.lock`` FIRST and only
    then looks for server locks. Whichever order the two land in, one of them
    sees the other and refuses: a server that finds ``adopt.lock`` held gives
    its own lock back and raises ``AccountError(ADOPT_RUNNING)``.

    A CONCURRENT PROBE IS NOT AN ADOPT (v0.20.0 T13). Every server looks at
    ``adopt.lock`` by taking it for an instant, so servers starting together
    -- the front door and every worker under the supervisor, or gunicorn's
    processes -- can find it held by each other's probe. The probe is
    retried for ``PROBE_RETRY_SECONDS``: another server's probe lets go at
    once, while an ``adopt`` holds the lock for its whole run.
    """
    secure_dir(directory)
    path = directory / f"server-{os.getpid()}-{secrets.token_hex(4)}.lock"
    fd = open_private(path)
    if not try_lock(fd):  # pragma: no cover -- a fresh random name
        os.close(fd)
        raise AccountError("could not take the hosting server lock")
    check = open_private(directory / ADOPT_LOCK)
    try:
        give_up = time.monotonic() + PROBE_RETRY_SECONDS
        while True:
            adopting = not try_lock(check)
            if not adopting:
                unlock(check)
                break
            if time.monotonic() >= give_up:
                break
            time.sleep(PROBE_RETRY_PAUSE_SECONDS)
    finally:
        os.close(check)
    if adopting:
        unlock(fd)
        os.close(fd)
        try:
            path.unlink()
        except OSError:  # removed by adopt's scan, or (Windows) still open elsewhere
            pass
        raise AccountError(ADOPT_RUNNING)
    return fd


#: ``adopt``'s own lock file in the hosting directory.
ADOPT_LOCK = "adopt.lock"


@contextmanager
def adopt_lock(directory: Path) -> Iterator[None]:
    """
    Hold ``<directory>/adopt.lock`` exclusively, without waiting, and refuse
    while any hosted server holds its lock (``running_servers``).

    Raises:
        AccountError: ``ADOPT_LOCK_BUSY``, or a server is running.
    """
    secure_dir(directory)
    fd = open_private(directory / ADOPT_LOCK)
    try:
        if not try_lock(fd):
            raise AccountError(ADOPT_LOCK_BUSY)
        try:
            held = running_servers(directory)
            if held:
                raise AccountError(
                    "a hosted server is running (" + ", ".join(held) + "); stop it before "
                    "adopting runs"
                )
            yield
        finally:
            unlock(fd)
    finally:
        os.close(fd)


def running_servers(directory: Path) -> list[str]:
    """
    The ``server-*.lock`` files a live process still holds. A file whose lock
    can be taken was left by a process that has ended, and is removed; one
    that cannot be opened or removed (on Windows, a server that has opened it
    and not yet locked it) counts as running. Never raises for a lock file.
    """
    held: list[str] = []
    if not directory.is_dir():
        return held
    for path in sorted(directory.glob(SERVER_LOCK_GLOB)):
        try:
            fd = os.open(str(path), os.O_RDWR)
        except OSError:
            held.append(path.name)
            continue
        free = False
        try:
            free = try_lock(fd)
            if free:
                unlock(fd)
        finally:
            os.close(fd)
        if not free:
            held.append(path.name)
            continue
        try:
            path.unlink(missing_ok=True)
        except OSError:
            held.append(path.name)
    return held


class AccountStore:
    """
    The accounts in one hosting directory.

    Args:
        directory: Where ``users.json`` lives; ``storage.hosting_dir()`` when
            None (read once, here).
        hash_slots: A semaphore bounding concurrent password hashes (hosted
            mode's ``hosting.max_concurrent_logins``); None (the CLI) hashes
            freely.
    """

    def __init__(
        self,
        directory: Optional[Path] = None,
        *,
        hash_slots: Optional[threading.BoundedSemaphore] = None,
    ) -> None:
        if directory is None:
            from engine.persistence.storage import hosting_dir

            directory = hosting_dir()
        self.directory = Path(directory)
        self.path = self.directory / "users.json"
        self.lock_path = self.directory / "users.json.lock"
        self.hash_slots = hash_slots
        #: ``(file identity, rows by id)``, or None. Replaced whole (one
        #: reference swap), never mutated, so a reader on another thread sees
        #: an old snapshot or a new one.
        self._cache: Optional[tuple[tuple[int, ...], dict[str, dict[str, Any]]]] = None
        #: Called with an account id after a change that ends its logins (a
        #: password change, a disable, a removal), in THIS process: hosted
        #: mode's socket door closes that account's open sockets at once
        #: (``engine/hosting/sockets.py``). Appended once at startup, then
        #: only read.
        self._revocation_listeners: list[Callable[[str], None]] = []

    def on_revoke(self, listener: Callable[[str], None]) -> None:
        """Call ``listener(account_id)`` after every change that ends that account's logins."""
        self._revocation_listeners.append(listener)

    def _revoked(self, account_id: str) -> None:
        for listener in list(self._revocation_listeners):
            try:
                listener(account_id)
            except Exception:  # noqa: BLE001 -- the change is written; a listener must not undo it
                logger.exception(
                    "[hosting] A revocation listener failed (operation=_revoked, account=%s)",
                    account_id,
                )

    # -- hashing -----------------------------------------------------------

    def _hashing(self) -> ContextManager[Any]:
        """A hashing slot, or ``LoginBusy`` after ``HASH_WAIT_SECONDS``."""
        slots = self.hash_slots
        if slots is None:
            return nullcontext()
        return _slot(slots)

    # -- reading ---------------------------------------------------------

    def _parse(self, raw: bytes) -> dict[str, dict[str, Any]]:
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise AccountsFileError(f"{self.path} is not readable JSON") from exc
        rows = data.get("accounts") if isinstance(data, dict) else None
        if not isinstance(rows, list):
            raise AccountsFileError(f"{self.path} holds no accounts list")
        out: dict[str, dict[str, Any]] = {}
        for row in rows:
            if not isinstance(row, dict) or not row.get("id") or not row.get("name"):
                raise AccountsFileError(f"{self.path} holds a row with no id or name")
            if not ID_RE.fullmatch(str(row["id"])):
                raise AccountsFileError(
                    f"{self.path} holds a row whose id is not an account id "
                    "(u_ and 12 hex digits)"
                )
            out[str(row["id"])] = row
        return out

    def _read_fresh(self) -> dict[str, dict[str, Any]]:
        """The file as it is now, uncached ({} when there is none yet)."""
        try:
            raw = _retrying(self.path.read_bytes)
        except FileNotFoundError:
            return {}
        return self._parse(raw)

    def _rows(self) -> dict[str, dict[str, Any]]:
        """The rows by id, through the file-identity cache."""
        try:
            info = self.path.stat()
        except FileNotFoundError:
            self._cache = None
            return {}
        key = (info.st_ino, info.st_mtime_ns, info.st_ctime_ns, info.st_size)
        cached = self._cache
        if cached is not None and cached[0] == key:
            return cached[1]
        rows = self._read_fresh()
        self._cache = (key, rows)
        return rows

    def all(self) -> list[Account]:
        """Every account, oldest first."""
        return sorted(
            (Account.from_row(row) for row in self._rows().values()),
            key=lambda a: (a.created, a.name),
        )

    def get(self, account_id: Any) -> Optional[Account]:
        """The account with this id, or None."""
        row = self._rows().get(str(account_id or ""))
        return Account.from_row(row) if row is not None else None

    def by_name(self, name: Any) -> Optional[Account]:
        """The account with this name, or None."""
        text = str(name or "")
        for row in self._rows().values():
            if row.get("name") == text:
                return Account.from_row(row)
        return None

    def verify(self, name: Any, password: Any) -> Optional[Account]:
        """
        The account ``name`` if ``password`` is its password and it is not
        disabled; else None, after the same scrypt work (``DUMMY_HASH``).

        Raises:
            LoginBusy: no hashing slot came free (nothing was hashed).
        """
        text = password if isinstance(password, str) else ""
        if len(text) > MAX_PASSWORD_CHARS:
            text = ""
        account = self.by_name(name) if isinstance(name, str) else None
        with self._hashing():
            if account is None or account.disabled:
                check_password_hash(DUMMY_HASH, text)
                return None
            return account if check_password_hash(account.hash, text) else None

    def check_current(self, account_id: str, password: Any) -> bool:
        """Whether ``password`` is this (enabled) account's password (may raise ``LoginBusy``)."""
        account = self.get(account_id)
        text = password if isinstance(password, str) else ""
        with self._hashing():
            if account is None or account.disabled or len(text) > MAX_PASSWORD_CHARS:
                check_password_hash(DUMMY_HASH, text[:MAX_PASSWORD_CHARS])
                return False
            return check_password_hash(account.hash, text)

    def _hash(self, password: Any) -> str:
        checked = check_password(password)
        with self._hashing():
            return generate_password_hash(checked)

    # -- the lock ----------------------------------------------------------

    @contextmanager
    def _locked(self) -> Iterator[None]:
        """Hold the system lock on ``users.json.lock`` (waits up to ``LOCK_WAIT_SECONDS``)."""
        secure_dir(self.directory)
        fd = _retrying(lambda: open_private(self.lock_path))
        try:
            deadline = time.monotonic() + LOCK_WAIT_SECONDS
            while not try_lock(fd):
                if time.monotonic() > deadline:
                    raise AccountError(
                        f"{self.lock_path} has been held for {LOCK_WAIT_SECONDS:.0f} s; "
                        "another writer is still running"
                    )
                time.sleep(0.01)
            try:
                yield
            finally:
                unlock(fd)
        finally:
            os.close(fd)

    def _change(self, mutate: Callable[[dict[str, dict[str, Any]]], Any]) -> Any:
        """Read, ``mutate`` the rows in place, write: all under the lock."""
        with self._locked():
            rows = self._read_fresh()
            result = mutate(rows)
            ordered = sorted(rows.values(), key=lambda r: (float(r.get("created") or 0), r["name"]))
            payload = {"version": FILE_VERSION, "accounts": ordered}
            _retrying(lambda: write_json_atomic(self.path, payload, keep_backup=False))
            if os.name == "posix":
                os.chmod(self.path, 0o600)
            # A backup an earlier build left would keep retired hashes.
            self.path.with_suffix(self.path.suffix + ".bak").unlink(missing_ok=True)
            self._cache = None
        return result

    # -- writing -----------------------------------------------------------

    @staticmethod
    def _find(rows: dict[str, dict[str, Any]], name: str) -> dict[str, Any]:
        for row in rows.values():
            if row.get("name") == name:
                return row
        raise AccountError(f"no account is named {name!r}")

    @classmethod
    def _locate(cls, rows: dict[str, dict[str, Any]], who: Any, by_id: bool) -> dict[str, Any]:
        """The row named ``who`` (a name), or with the id ``who`` when ``by_id``."""
        if by_id:
            row = rows.get(check_id(who))
            if row is None:
                raise AccountError("that account no longer exists")
            return row
        return cls._find(rows, check_name(who))

    @staticmethod
    def _enabled_admins(rows: dict[str, dict[str, Any]]) -> list[str]:
        """The ids of every enabled admin in ``rows`` (as ``Account.from_row`` reads them)."""
        return [
            account.id
            for account in (Account.from_row(row) for row in rows.values())
            if account.admin and not account.disabled
        ]

    @classmethod
    def _guard(
        cls,
        rows: dict[str, dict[str, Any]],
        row: dict[str, Any],
        *,
        actor_id: Optional[str],
        force: bool,
    ) -> None:
        """
        Spec §14.6's guards, run INSIDE the lock by every change that takes
        an admin's role or logins away (revoke, disable, remove): not the
        caller's own account (``actor_id``), and never the last enabled
        admin. ``force`` (the CLI, after its terminal confirmation) skips both.
        """
        if force:
            return
        if actor_id is not None and str(row.get("id")) == str(actor_id):
            raise SelfAction(NOT_YOURSELF)
        target = Account.from_row(row)
        if target.admin and not target.disabled and cls._enabled_admins(rows) == [target.id]:
            raise LastAdmin(LAST_ADMIN)

    def add(
        self,
        name: Any,
        password: Any,
        *,
        admin: bool = False,
        must_change: bool = False,
    ) -> Account:
        """Create an account. Refuses a taken name."""
        chosen = check_name(name)
        hashed = self._hash(password)

        def mutate(rows: dict[str, dict[str, Any]]) -> Account:
            if any(row.get("name") == chosen for row in rows.values()):
                raise AccountError(f"an account named {chosen!r} already exists")
            row = {
                "id": mint_id(rows),
                "name": chosen,
                "hash": hashed,
                "created": time.time(),
                "epoch": 1,
                "disabled": False,
                "admin": bool(admin),
                "must_change": bool(must_change),
            }
            rows[row["id"]] = row
            return Account.from_row(row)

        return self._change(mutate)

    def create_with_generated_password(self, name: Any, *, admin: bool = False) -> tuple[Account, str]:
        """
        Create an account with a generated one-time password, which its owner
        must replace at first login (``must_change``; spec §14.8). Returns
        ``(account, password)``: the caller shows the password ONCE and keeps
        it nowhere.
        """
        password = generate_password()
        return self.add(name, password, admin=admin, must_change=True), password

    def _bump(self, row: dict[str, Any]) -> None:
        row["epoch"] = int(row.get("epoch") or 1) + 1

    def set_password(self, name: Any, password: Any) -> Account:
        """
        A new password, chosen by its owner (or typed by the operator): the
        epoch goes up, so every other login ends, and ``must_change`` is
        cleared.
        """
        chosen = check_name(name)
        hashed = self._hash(password)

        def mutate(rows: dict[str, dict[str, Any]]) -> Account:
            row = self._find(rows, chosen)
            row["hash"] = hashed
            row["must_change"] = False
            self._bump(row)
            return Account.from_row(row)

        return self._revoking(self._change(mutate))

    def _revoking(self, account: Account) -> Account:
        """``account``, after telling the listeners its logins have ended."""
        self._revoked(account.id)
        return account

    def set_password_by_id(self, account_id: str, password: Any) -> Account:
        """``set_password`` for the account with this id (``POST /account``)."""
        hashed = self._hash(password)

        def mutate(rows: dict[str, dict[str, Any]]) -> Account:
            row = rows.get(str(account_id))
            if row is None:
                raise AccountError("that account no longer exists")
            row["hash"] = hashed
            row["must_change"] = False
            self._bump(row)
            return Account.from_row(row)

        return self._revoking(self._change(mutate))

    def reset_password(self, who: Any, *, by_id: bool = False) -> tuple[Account, str]:
        """
        A generated one-time password for this account (spec §14.8): the
        epoch goes up (every login ends) and ``must_change`` is set. Returns
        ``(account, password)``; the caller shows the password once.
        """
        password = generate_password()
        hashed = self._hash(password)

        def mutate(rows: dict[str, dict[str, Any]]) -> Account:
            row = self._locate(rows, who, by_id)
            row["hash"] = hashed
            row["must_change"] = True
            self._bump(row)
            return Account.from_row(row)

        return self._revoking(self._change(mutate)), password

    def set_admin(
        self,
        who: Any,
        on: bool,
        *,
        by_id: bool = False,
        actor_id: Optional[str] = None,
        force: bool = False,
    ) -> Account:
        """
        Grant or revoke the admin role. A change bumps the epoch, so the
        account's open panel (and every other login) ends on its next
        request. Revoking runs ``_guard`` inside the lock. Granting the role
        an account already has, or revoking one it lacks, changes nothing.
        """

        def mutate(rows: dict[str, dict[str, Any]]) -> tuple[Account, bool]:
            row = self._locate(rows, who, by_id)
            if Account.from_row(row).admin == bool(on):
                return Account.from_row(row), False
            if not on:
                self._guard(rows, row, actor_id=actor_id, force=force)
            row["admin"] = bool(on)
            self._bump(row)
            return Account.from_row(row), True

        account, changed = self._change(mutate)
        return self._revoking(account) if changed else account

    def disable(
        self,
        name: Any,
        *,
        by_id: bool = False,
        actor_id: Optional[str] = None,
        force: bool = False,
    ) -> Account:
        """
        Refuse this account's logins; the epoch goes up, ending its sessions.
        ``_guard`` runs inside the lock (not yourself, not the last admin).
        """

        def mutate(rows: dict[str, dict[str, Any]]) -> Account:
            row = self._locate(rows, name, by_id)
            self._guard(rows, row, actor_id=actor_id, force=force)
            row["disabled"] = True
            self._bump(row)
            return Account.from_row(row)

        return self._revoking(self._change(mutate))

    def enable(self, name: Any, *, by_id: bool = False) -> Account:
        """Accept this account's logins again (the epoch is not changed)."""

        def mutate(rows: dict[str, dict[str, Any]]) -> Account:
            row = self._locate(rows, name, by_id)
            row["disabled"] = False
            return Account.from_row(row)

        return self._change(mutate)

    def remove(
        self,
        name: Any,
        *,
        by_id: bool = False,
        actor_id: Optional[str] = None,
        force: bool = False,
    ) -> Account:
        """
        Delete the account row (its saves stay unless the caller purges them).
        ``_guard`` runs inside the lock (not yourself, not the last admin).
        """

        def mutate(rows: dict[str, dict[str, Any]]) -> Account:
            row = self._locate(rows, name, by_id)
            self._guard(rows, row, actor_id=actor_id, force=force)
            del rows[str(row["id"])]
            return Account.from_row(row)

        return self._revoking(self._change(mutate))

    def is_last_admin(self, name: Any) -> bool:
        """Whether ``name`` is the one enabled admin (the CLI's confirmation asks)."""
        account = self.by_name(name)
        if account is None or not account.admin or account.disabled:
            return False
        return [a.id for a in self.all() if a.admin and not a.disabled] == [account.id]

    def admins(self) -> list[Account]:
        """Every account with the admin role, enabled or not, oldest first."""
        return [account for account in self.all() if account.admin]


@contextmanager
def _slot(slots: threading.BoundedSemaphore) -> Iterator[None]:
    if not slots.acquire(timeout=HASH_WAIT_SECONDS):
        raise LoginBusy("every password-hashing slot is taken")
    try:
        yield
    finally:
        slots.release()


def users_root() -> Path:
    """``<storage.root>/users``: every account's files, and nothing else."""
    from engine.persistence.storage import data_root

    return data_root() / "users"


def user_dir(account: Account) -> Path:
    """``<storage.root>/users/<id>``: everything of this account's on disk."""
    return users_root() / check_id(account.id)


def purge_user_dir(account: Account) -> bool:
    """
    Delete ``user_dir(account)``; whether there was one. The caller confirms
    first. Refuses anything that does not resolve to a direct child of
    ``users/``.
    """
    directory = user_dir(account)
    root = users_root().resolve()
    resolved = directory.resolve()
    if resolved.parent != root or resolved.name != account.id:
        raise AccountError(f"refusing to delete {resolved}: it is not an account's folder")
    if not directory.is_dir():
        return False
    shutil.rmtree(directory)
    return True


#: Suffix of a run copied to the account's volume and not yet in place.
STAGING_SUFFIX = ".adopting"

#: Suffix of a local run set aside once its copy is in place, to be removed.
ASIDE_SUFFIX = ".adopted"


def _move_run(source: Path, target: Path) -> None:
    """
    Move one run's directory, leaving exactly one complete copy whatever fails.

    A rename where the file system allows it. Across volumes (``EXDEV``):

    1. copy to ``<target>.adopting`` and compare every file;
    2. rename the source aside to ``<source>.adopted`` (same volume, atomic).
       If that fails (on Windows, a file a running local game holds) the
       copy is ROLLED BACK and the source is untouched;
    3. rename the copy into place (if that fails, the source is renamed back
       and the copy rolled back);
    4. remove the set-aside source. If that fails part way, the complete copy
       is the account's, and the half-removed ``.adopted`` folder is not a run
       (no index ever lists a name with a dot): the error names it, and the
       next ``adopt`` removes it.
    """
    try:
        os.rename(source, target)
        return
    except OSError as exc:
        if exc.errno != errno.EXDEV:
            raise
    staging = target.with_name(target.name + STAGING_SUFFIX)
    if staging.exists():
        shutil.rmtree(staging)
    shutil.copytree(source, staging)
    for original in (p for p in source.rglob("*") if p.is_file()):
        copied = staging / original.relative_to(source)
        if not copied.is_file() or not filecmp.cmp(original, copied, shallow=False):
            shutil.rmtree(staging, ignore_errors=True)
            raise AccountError(f"the copy of {source.name} did not verify; nothing was moved")
    aside = source.with_name(source.name + ASIDE_SUFFIX)
    try:
        os.rename(source, aside)
    except OSError as exc:
        shutil.rmtree(staging, ignore_errors=True)
        raise AccountError(
            f"could not move {source} ({exc.strerror or exc}); it is unchanged and "
            "nothing was copied. Stop anything using it (a local game) and run adopt again"
        ) from None
    try:
        os.rename(staging, target)
    except OSError as exc:
        try:
            os.rename(aside, source)
        except OSError as back:
            # Neither move went through (v0.20.0 T8): the run is whole in the
            # set-aside folder, which the next adopt renames back
            # (`_finish_leftovers`); the copy is dropped, so no second run
            # is ever left beside it.
            shutil.rmtree(staging, ignore_errors=True)
            raise AccountError(
                f"could not put the copy of {source.name} in place ({exc.strerror or exc}), "
                f"nor move the local run back from {aside} ({back.strerror or back}); "
                "it is whole there: run adopt again to restore it"
            ) from None
        shutil.rmtree(staging, ignore_errors=True)
        raise AccountError(
            f"could not put the copy of {source.name} in place ({exc.strerror or exc}); "
            "the local run is unchanged"
        ) from None
    try:
        shutil.rmtree(aside)
    except OSError as exc:
        raise AccountError(
            f"{source.name} is now the account's, but its old local folder {aside} could "
            f"not be removed ({exc.strerror or exc}); run adopt again to remove it, or "
            "delete it by hand"
        ) from None


def _finish_leftovers(source: Path, target: Path) -> None:
    """
    Clear what an interrupted cross-volume ``adopt`` left, so a re-run goes on:
    a ``.adopted`` folder whose run is in the account's store is removed (one
    whose run is not is renamed back), and a ``.adopting`` copy is removed.
    """
    if source.is_dir():
        for aside in sorted(source.glob("*" + ASIDE_SUFFIX)):
            save_id = aside.name[: -len(ASIDE_SUFFIX)]
            if (target / save_id).is_dir():
                try:
                    shutil.rmtree(aside)
                except OSError as exc:
                    raise AccountError(
                        f"could not remove the old local folder {aside} "
                        f"({exc.strerror or exc}); delete it by hand"
                    ) from None
            elif not (source / save_id).exists():
                os.rename(aside, source / save_id)
    if target.is_dir():
        for staging in sorted(target.glob("*" + STAGING_SUFFIX)):
            shutil.rmtree(staging, ignore_errors=True)


def adopt(
    account: Account, slug: Optional[str] = None, *, hosting_directory: Optional[Path] = None
) -> dict[str, list[str]]:
    """
    Move the local player's runs into ``account``'s saves (spec §4.2).

    Each ``<local saves>/<slug>/<save_id>/`` directory is MOVED, never
    duplicated: renamed, or across volumes copied, verified and then removed.
    Both stores' indexes are rebuilt from disk afterwards, even when a move
    fails part way. Nothing moves if any save id is already in the account's
    store (the whole adoption is refused, naming them). It holds
    ``adopt.lock`` throughout (``adopt_lock``): it refuses while a hosted
    server runs, and a server that starts meanwhile refuses to start. A local
    game on the same story should be stopped too, since its autosave writes
    the folder being moved. A re-run after an interrupted cross-volume move
    finishes it (``_finish_leftovers``).

    Args:
        account: Whose store receives the runs.
        slug: One story, or None for every story with local saves.
        hosting_directory: The hosting directory (``storage.hosting_dir()``).

    Returns:
        ``{slug: [save ids moved]}``.
    """
    from engine.persistence import storage

    check_id(account.id)
    with adopt_lock(Path(hosting_directory or storage.hosting_dir())):
        return _adopt(account, slug)


def _adopt(account: Account, slug: Optional[str]) -> dict[str, list[str]]:
    """``adopt``'s work, run under ``adopt_lock``."""
    from engine.games.manifest import is_valid_slug
    from engine.persistence import saves, storage

    base = saves.saves_base()
    if slug is not None:
        if not is_valid_slug(slug):
            raise AccountError(f"not a story slug: {slug!r}")
        slugs = [slug]
    else:
        slugs = sorted(p.name for p in base.iterdir() if p.is_dir() and is_valid_slug(p.name)) if base.is_dir() else []

    plan: dict[str, list[str]] = {}
    clashes: list[str] = []
    for chosen in slugs:
        source = saves.saves_root(chosen)
        if not source.is_dir():
            continue
        target = storage.saves_dir(account.id, chosen)
        _finish_leftovers(source, target)
        ids: list[str] = []
        for directory in sorted(p for p in source.iterdir() if p.is_dir()):
            try:
                saves.check_save_id(directory.name)
            except saves.InvalidSaveId:
                continue
            if (target / directory.name).exists():
                clashes.append(f"{chosen}/{directory.name}")
            ids.append(directory.name)
        if ids:
            plan[chosen] = ids
    if clashes:
        raise AccountError(
            f"{account.name} already has saves with these ids; nothing was moved: "
            + ", ".join(clashes)
        )
    for chosen, ids in plan.items():
        source = saves.saves_root(chosen)
        target = storage.saves_dir(account.id, chosen)
        target.mkdir(parents=True, exist_ok=True)
        try:
            for save_id in ids:
                _move_run(source / save_id, target / save_id)
        finally:
            saves.SaveStore(root=source, slug=chosen).reindex()
            saves.SaveStore(root=target, slug=chosen).reindex()
        logger.info(
            "[hosting] Adopted local runs (operation=adopt, account=%s, slug=%s, count=%d)",
            account.id,
            chosen,
            len(ids),
        )
    return plan


__all__ = [
    "Account",
    "AccountError",
    "AccountStore",
    "AccountsFileError",
    "DUMMY_HASH",
    "GENERATED_PASSWORD_BYTES",
    "LAST_ADMIN",
    "LastAdmin",
    "NOT_YOURSELF",
    "SelfAction",
    "generate_password",
    "FILE_VERSION",
    "HASH_WAIT_SECONDS",
    "ADOPT_LOCK",
    "ADOPT_LOCK_BUSY",
    "ADOPT_RUNNING",
    "ASIDE_SUFFIX",
    "ID_RE",
    "STAGING_SUFFIX",
    "adopt_lock",
    "LOCK_WAIT_SECONDS",
    "LoginBusy",
    "MAX_PASSWORD_CHARS",
    "MIN_PASSWORD_CHARS",
    "NAME_RE",
    "SERVER_LOCK_GLOB",
    "adopt",
    "check_id",
    "check_name",
    "check_password",
    "hold_server_lock",
    "mint_id",
    "open_private",
    "purge_user_dir",
    "running_servers",
    "secure_dir",
    "try_lock",
    "unlock",
    "user_dir",
    "users_root",
]
