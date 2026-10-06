"""
Hosted Mode Accounts
====================

The operator makes every account; there is no sign-up page (v0.20.0, spec
§6.1). Every change goes through ``engine/hosting/accounts.py``, the one
writer of ``<storage.root>/hosting/users.json``, under its inter-process lock,
so this works against a running server.

    python scripts/users.py add <name> [--admin]   make an account (--admin: an admin,
                                                   which is how the first admin is made)
    python scripts/users.py admin <name> on|off    grant or revoke the admin role (ends
                                                   every login of it; the last admin
                                                   asks first)
    python scripts/users.py passwd <name>          set a new password (ends every login;
                                                   clears a password an admin generated)
    python scripts/users.py disable <name>         refuse its logins (ends every login)
    python scripts/users.py enable <name>          accept its logins again
    python scripts/users.py list                   every account
    python scripts/users.py remove <name> [--purge]
                                                   delete the account; --purge also
                                                   deletes its saves (asks first)
    python scripts/users.py adopt <name> [--game <slug>]
                                                   move the local player's runs into
                                                   the account's saves (a move, never
                                                   a copy)

A PASSWORD IS READ WITH ``getpass``, TWICE, and never from the command line,
the environment or a file: argv shows up in the process list and the shell's
history, and the environment in every child process.

The storage root is ``CLOCKWORK_DATA_DIR``, else ``storage.root``: the same
the server reads.

EVERY CHANGE IS AUDITED, WRITE-FIRST (v0.20.0 T14, spec §14.11): the row
(actor ``cli``) is appended to ``<storage.root>/hosting/audit.jsonl`` before
the change, and a change whose row cannot be written is refused with nothing
changed (``engine/hosting/audit.py``). ``adopt`` moves runs, not accounts,
and is logged rather than audited.

THE LAST ADMIN. The admin panel refuses to demote, disable or delete the last
enabled admin; this script can, because an operator with a shell owns the
server, but asks to confirm on the terminal first.

Version: v0.2.0 [2026-10-05]
"""

from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path
from typing import Optional

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from engine.hosting import audit  # noqa: E402
from engine.hosting.accounts import (  # noqa: E402
    AccountError,
    AccountStore,
    AccountsFileError,
    adopt,
    check_name,
    check_password,
    purge_user_dir,
    user_dir,
)

#: What a change refused for want of its audit row is told.
NOT_AUDITED = (
    "the audit log cannot be written (<storage.root>/hosting/audit.jsonl), so nothing was "
    "changed: every change is recorded before it is made"
)


def _audited(action: str, target: str, change, *, detail: Optional[dict] = None):  # type: ignore[no-untyped-def]
    """
    ``change(ticket)`` under the write-first rule, as the actor ``cli``:
    its result. A guard refusing inside the accounts lock records ``refused``.
    """
    with audit.audited(
        action, target, actor=audit.CLI_ACTOR, detail=detail, refusals=(AccountError,)
    ) as ticket:
        return change(ticket)


def _read_password(name: str) -> str:
    """A new password for ``name``, typed twice without echo."""
    first = getpass.getpass(f"New password for {name}: ")
    check_password(first)
    second = getpass.getpass("Again: ")
    if first != second:
        raise AccountError("the two passwords differ; nothing was changed")
    return first


def _confirm(prompt: str, expected: str) -> bool:
    answer = input(f"{prompt} Type {expected!r} to confirm: ")
    return answer.strip() == expected


def _list(store: AccountStore) -> int:
    accounts = store.all()
    if not accounts:
        print("No accounts yet. Make one with: python scripts/users.py add <name>")
        return 0
    for account in accounts:
        state = "disabled" if account.disabled else "enabled"
        role = "admin" if account.admin else "player"
        flag = "  must change password" if account.must_change else ""
        print(f"{account.name:<32}  {account.id}  {role:<6}  {state}{flag}")
    if not any(a.admin and not a.disabled for a in accounts):
        print("No enabled admin: the admin panel is unreachable. Make one with: "
              "python scripts/users.py admin <name> on")
    return 0


def _confirm_last_admin(store: AccountStore, name: str, what: str) -> bool:
    """For the last enabled admin: the terminal confirmation (True to go on)."""
    if not store.is_last_admin(name):
        return True
    return _confirm(
        f"{name} is the last enabled admin: {what} leaves the admin panel with no one who can open it.",
        name,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Make and manage hosted mode's accounts (docs/HOSTING.md § Accounts).",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    add = commands.add_parser("add", help="make an account")
    add.add_argument("name")
    add.add_argument("--admin", action="store_true", help="make it an admin (the first admin is made so)")
    role = commands.add_parser("admin", help="grant or revoke the admin role; every login of the account ends")
    role.add_argument("name")
    role.add_argument("state", choices=["on", "off"])
    for command, text in (
        ("passwd", "set a new password; every login of the account ends"),
        ("disable", "refuse the account's logins; every login ends"),
        ("enable", "accept the account's logins again"),
    ):
        sub = commands.add_parser(command, help=text)
        sub.add_argument("name")
    commands.add_parser("list", help="every account")
    remove = commands.add_parser("remove", help="delete an account")
    remove.add_argument("name")
    remove.add_argument(
        "--purge", action="store_true", help="also delete the account's saves (asks first)"
    )
    adopt_cmd = commands.add_parser(
        "adopt", help="move the local player's runs into this account's saves"
    )
    adopt_cmd.add_argument("name")
    adopt_cmd.add_argument("--game", default=None, help="one story's runs only")
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = _build_parser().parse_args(argv)
    store = AccountStore()
    try:
        if args.command == "list":
            return _list(store)
        if args.command == "add":
            check_name(args.name)
            if store.by_name(args.name) is not None:
                raise AccountError(f"an account named {args.name!r} already exists")
            password = _read_password(args.name)

            def create(ticket: audit.Ticket):  # type: ignore[no-untyped-def]
                made = store.add(args.name, password, admin=args.admin)
                ticket.target = made.id
                return made

            account = _audited("account.create", "", create, detail={"name": args.name, "admin": args.admin})
            print(f"Made {account.name} ({account.id}){' as an admin' if account.admin else ''}.")
            return 0
        if args.command == "admin":
            account = store.by_name(args.name)
            if account is None:
                raise AccountError(f"no account is named {args.name!r}")
            on = args.state == "on"
            if not on and not _confirm_last_admin(store, account.name, "revoking its role"):
                print("Nothing was changed.")
                return 1
            changed = _audited(
                "account.set_admin",
                account.id,
                lambda _t: store.set_admin(account.name, on, force=True),
                detail={"admin": on},
            )
            print(
                f"{changed.name} is {'now' if changed.admin else 'no longer'} an admin; "
                "every login of it has ended."
            )
            return 0
        if args.command == "passwd":
            account = store.by_name(args.name)
            if account is None:
                raise AccountError(f"no account is named {args.name!r}")
            password = _read_password(args.name)
            _audited("account.passwd", account.id, lambda _t: store.set_password(args.name, password))
            print(f"Changed {args.name}'s password; every login of it has ended.")
            return 0
        if args.command == "disable":
            account = store.by_name(args.name)
            if account is None:
                raise AccountError(f"no account is named {args.name!r}")
            if not _confirm_last_admin(store, account.name, "disabling it"):
                print("Nothing was changed.")
                return 1
            _audited("account.disable", account.id, lambda _t: store.disable(args.name, force=True))
            print(f"Disabled {args.name}; every login of it has ended.")
            return 0
        if args.command == "enable":
            account = store.by_name(args.name)
            if account is None:
                raise AccountError(f"no account is named {args.name!r}")
            _audited("account.enable", account.id, lambda _t: store.enable(args.name))
            print(f"Enabled {args.name}.")
            return 0
        if args.command == "remove":
            account = store.by_name(args.name)
            if account is None:
                raise AccountError(f"no account is named {args.name!r}")
            if args.purge and not _confirm(
                f"This deletes {account.name}'s account AND every save in {user_dir(account)}.",
                account.name,
            ):
                print("Nothing was changed.")
                return 1
            if not _confirm_last_admin(store, account.name, "deleting it"):
                print("Nothing was changed.")
                return 1

            def delete(ticket: audit.Ticket):  # type: ignore[no-untyped-def]
                store.remove(account.name, force=True)
                if args.purge:
                    ticket.detail["purged"] = purge_user_dir(account)
                return ticket.detail.get("purged", False)

            purged = _audited("account.delete", account.id, delete, detail={"purge": bool(args.purge)})
            kept = "" if purged or not user_dir(account).exists() else (
                f" Its saves are kept in {user_dir(account)}."
            )
            print(f"Removed {account.name}.{' Its saves are deleted.' if purged else ''}{kept}")
            return 0
        if args.command == "adopt":
            account = store.by_name(args.name)
            if account is None:
                raise AccountError(f"no account is named {args.name!r}")
            moved = adopt(account, args.game)
            if not moved:
                print("No local runs to move.")
            for slug, ids in moved.items():
                print(f"Moved {len(ids)} run(s) of {slug} into {account.name}'s saves.")
            return 0
    except audit.AuditUnavailable:
        print(f"users.py: {NOT_AUDITED}", file=sys.stderr)
        return 1
    except (AccountError, AccountsFileError) as exc:
        print(f"users.py: {exc}", file=sys.stderr)
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
