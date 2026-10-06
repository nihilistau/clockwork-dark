"""
A second writer of ``users.json``, in its own process (v0.20.0 T7).

``tests/test_hosting_accounts.py`` starts two of these at once, each changing
a DIFFERENT account, to prove the inter-process lock: every change of both
must land (a read-modify-write without the lock loses the other's).

    python tests/probes/accounts_writer.py <hosting dir> <name> <rounds> <go file>
    python tests/probes/accounts_writer.py <hosting dir> <name> hold <unused>

``hold`` takes the accounts lock, prints ``held`` and keeps it until the
test kills the process (the lock must die with it).

The new password is read from stdin (a generated test value, never argv). The
probe waits for ``<go file>`` to exist so both start writing together, then
sets the password once and toggles the account ``rounds`` times (disable,
enable: each disable bumps the epoch). Prints ``done`` and exits 0.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from engine.hosting.accounts import AccountStore  # noqa: E402


def main(argv: list[str]) -> int:
    if argv[2] == "hold":
        # Take the accounts lock, say so, and keep it until killed.
        store = AccountStore(Path(argv[0]))
        with store._locked():
            print("held", flush=True)
            time.sleep(120)
        return 0
    directory, name, rounds, go = Path(argv[0]), argv[1], int(argv[2]), Path(argv[3])
    password = sys.stdin.readline().rstrip("\n")
    deadline = time.monotonic() + 60
    while not go.exists():
        if time.monotonic() > deadline:
            print("no go file", file=sys.stderr)
            return 2
        time.sleep(0.005)
    store = AccountStore(directory)
    store.set_password(name, password)
    for _ in range(rounds):
        store.disable(name)
        store.enable(name)
    print("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
