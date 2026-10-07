"""
The suite's tiers (v0.21.1). Pure functions, so tests/test_suite_tiers.py can
test them without a pytest session.

  slow     measures balance or plays a long run. Rule 10: it KEEPS ITS LENGTH;
           only its tier moves.
  process  it, or a fixture it uses, starts a Python interpreter, gunicorn or
           a hosted supervisor (git/sh probes do not count). The Popen
           recorder in tests/tier_plugin.py enforces this marker: an unmarked
           test that starts an interpreter fails.

A BARE run (``pytest`` with no path, node id, -m or -k) leaves both tiers out.
``--full`` or CLOCKWORK_FULL_SUITE=1 keeps them. Any explicit selection runs
everything it names.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import pytest

TIER_MARKERS = ("slow", "process")

#: The HYBRID run's two phases (v0.21.1 T5 fix rounds 1-2), defined once
#: for scripts/run_tests.py, CI (T7) and tests/test_ci_workflow.py. Phase A
#: runs on xdist workers; phase B serially: the process tier (hosted
#: supervisors, children and front doors), the skills server's tests
#: (``mcp_server``: an in-process uvicorn) and every test that binds an
#: in-process loopback server (``loopback``: buses, front doors, WSGI and
#: health servers; enforced by tests/tier_plugin.py's bind recorder) -- the
#: ones this workstation's loopback stalls failed under xdist (CLAUDE.md,
#: deferred). The two are exact complements, so together they run every
#: test once.
SERIAL_MARKS = "process or mcp_server or loopback"
PARALLEL_MARKS = f"not ({SERIAL_MARKS})"


#: What a bare run (the FAST tier) selects, as an expression: ``run_tests.py
#: fast`` names it in both of its phases, since any ``-m`` is a selection of
#: its own and would otherwise run every tier.
FAST_MARKS = "not slow and not process"


def phase_marks(user: str | None, phase: str) -> str:
    """A phase's ``-m`` expression, with a user's own ``-m`` joined by ``and``."""
    own = {"parallel": PARALLEL_MARKS, "serial": f"({SERIAL_MARKS})"}[phase]
    return f"({user}) and {own}" if user else own
FULL_ENV = "CLOCKWORK_FULL_SUITE"
_INTERPRETERS = ("python", "pythonw", "gunicorn", "pytest")


def tier_of(marks: Any) -> str:
    """The one tier a test's marks put it in: "process" over "slow" over
    "fast" (a test that is both is a process test), so the three partition
    the suite."""
    marks = set(marks)
    if "process" in marks:
        return "process"
    if "slow" in marks:
        return "slow"
    return "fast"


def wants_full(config: Any) -> bool:
    return bool(config.getoption("clockwork_full", False)) or os.environ.get(FULL_ENV) == "1"


#: Options that narrow a run to what the user picked, as -m and -k do:
#: ``--lf`` and ``--sw`` re-run what failed last, and a failure in a slow
#: or process test must not be deselected as if it were fixed.
_NARROWING = ("markexpr", "keyword", "lf", "stepwise")


def is_bare_run(config: Any) -> bool:
    """True when the args came from ``testpaths`` and nothing narrowed them.

    ``cd tests; pytest`` has args from the invocation directory, so it is not
    bare and runs every tier."""
    from_testpaths = config.args_source == pytest.Config.ArgsSource.TESTPATHS
    narrowed = any(bool(config.getoption(name, None)) for name in _NARROWING)
    return from_testpaths and not narrowed


def _first_word(args: Any, executable: Any) -> str:
    if executable:
        return os.fsdecode(executable)
    if isinstance(args, (str, bytes, os.PathLike)):
        text = os.fsdecode(args).strip()
        if text.startswith('"'):
            return text[1:].split('"', 1)[0]
        return text.split(" ", 1)[0]
    argv = list(args or [])
    return os.fsdecode(argv[0]) if argv else ""


def _argv(args: Any) -> list[str]:
    if isinstance(args, (str, bytes, os.PathLike)):
        return os.fsdecode(args).split()
    return [os.fsdecode(a) for a in (args or [])]


def starts_an_interpreter(args: Any, executable: Any = None) -> bool:
    """Would this Popen start Python, gunicorn or pytest?"""
    first = _first_word(args, executable)
    if not first:
        return False
    try:
        if os.path.normcase(os.path.abspath(first)) == os.path.normcase(sys.executable):
            return True
    except (OSError, ValueError):
        pass
    name = Path(first).name.lower()
    stem = name[:-4] if name.endswith(".exe") else name
    if any(stem == n or stem.startswith(n + "3") for n in _INTERPRETERS):
        return True
    argv = _argv(args)
    return any(a == "-m" and i + 1 < len(argv) and argv[i + 1] in ("gunicorn", "pytest")
               for i, a in enumerate(argv))
