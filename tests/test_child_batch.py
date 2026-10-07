"""
``tests/child_batch.py``: a batch of children started together never leaves
one running (v0.21.1 T4, preflight K5).

The batch fixtures of ``tests/test_imports.py`` and
``tests/test_simulate_thief.py`` start up to eight interpreters at once. An
exception mid-batch (a ``KeyboardInterrupt``, a pytest-timeout raised into the
fixture) or one child's deadline must end and reap every child still running,
by its identity (pid and creation time), never a bare pid. Each test here
records the identities as the children start and checks, after the batch,
that no process with any of them is alive.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from tests.child_batch import Done, run_together
from tests.process_identity import Identity, alive, created

pytestmark = pytest.mark.process

#: A child that would outlive any test unless it is ended.
SLEEPER = [sys.executable, "-c", "import time; time.sleep(120)"]
QUICK = [sys.executable, "-c", "import sys; sys.stdout.write('ok'); sys.stderr.write('e')"]


class _Boom(Exception):
    pass


#: Where a creation time cannot be read (POSIX without /proc, macOS: untested
#: per AGENTS.md) identities are unknown; the batch ends children through
#: their handles there, and the "alive" check below cannot see them.
_IDENTITIES_KNOWN = created(os.getpid()) is not None


@pytest.mark.parametrize("raised", [_Boom, KeyboardInterrupt], ids=["exception", "keyboard-interrupt"])
def test_an_exception_mid_batch_leaves_no_child_running(tmp_path: Path, raised: type) -> None:
    """Mid-batch: an ordinary exception, and a ``BaseException`` (what a
    Ctrl+C or pytest-timeout's signal method raises into the fixture)."""
    started: list[Identity] = []

    def on_start(key: object, identity: Identity) -> None:
        started.append(identity)
        if len(started) == 3:
            raise raised("injected mid-batch")

    with pytest.raises(raised):
        run_together(
            {n: SLEEPER for n in range(6)},
            out_dir=tmp_path, timeout=120, workers=4, on_start=on_start,
        )
    assert len(started) == 3
    if _IDENTITIES_KNOWN:
        assert all(identity.created is not None for identity in started), started
    assert not [identity for identity in started if alive(identity)]


def test_the_batch_budget_ends_the_running_and_starts_no_more(tmp_path: Path) -> None:
    """One budget for the whole batch: past it, a running child is ended and
    one still waiting is never started, both answering as timed out."""
    started: list[Identity] = []
    done = run_together(
        {"a": SLEEPER, "b": SLEEPER, "c": QUICK},
        out_dir=tmp_path, timeout=120, workers=1, budget=2,
        on_start=lambda key, identity: started.append(identity),
    )
    assert len(started) == 1
    assert all(run.timed_out for run in done.values()), done
    assert b"not started" in done["c"].stderr
    assert not [identity for identity in started if alive(identity)]


def test_a_child_past_its_deadline_is_ended_and_the_rest_still_run(tmp_path: Path) -> None:
    started: list[Identity] = []
    done = run_together(
        {"slow": SLEEPER, "quick": QUICK},
        out_dir=tmp_path, timeout=3, workers=2,
        on_start=lambda key, identity: started.append(identity),
    )
    assert done["slow"].timed_out
    assert done["quick"] == Done(0, b"ok", b"e")
    assert not [identity for identity in started if alive(identity)]


def test_the_batch_is_bounded_and_answers_in_the_order_asked(tmp_path: Path) -> None:
    started: list[Identity] = []
    most: list[int] = []

    def on_start(key: object, identity: Identity) -> None:
        started.append(identity)
        most.append(sum(alive(i) for i in started))

    nap = [sys.executable, "-c", "import sys, time; time.sleep(1); sys.stdout.write('ok')"]
    done = run_together({k: nap for k in "edcba"}, out_dir=tmp_path, timeout=60, workers=2,
                        on_start=on_start)
    assert list(done) == list("edcba")
    assert all(run.returncode == 0 and run.stdout == b"ok" for run in done.values())
    assert len(started) == 5 and max(most) <= 2, most
