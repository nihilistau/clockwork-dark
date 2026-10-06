"""
The engine's process-wide state, pinned (v0.20.0 T6, spec §5.2 and §9.2).

``tests/module_state_scan.py`` walks every module under ``engine/`` (pure AST,
nothing imported) and lists each module-level name rebound through ``global``
or bound to a container, ``None`` or a ``threading``/``contextvars`` object,
each ``@lru_cache`` function and each ``threading.Thread(`` site. This file
asserts that list EQUALS the keys of ``tests/fixtures/module_state.yaml``, where
each site carries a verdict. A new module global, cache or thread therefore
fails the suite until someone classifies it -- the moment to ask whether it
races when many sessions share one process (AGENTS.md "Tests").

Canary-checked (T6's report): a module-level ``_X: dict = {}`` added to an
engine module fails ``test_the_scan_equals_the_inventory``; and, in memory,
one snippet per kind of site (``CANARIES``) appended to a real engine module
yields an unclassified site.

Version: v0.1.0 [2026-10-01]
"""

from __future__ import annotations

import pytest

from tests.module_state_scan import ROOT, VERDICTS, load_inventory, scan, scan_source


def test_the_scan_equals_the_inventory():
    found = scan()
    classified = set(load_inventory())
    unclassified = sorted(found - classified)
    gone = sorted(classified - found)
    assert not unclassified, (
        "module state with no verdict in tests/fixtures/module_state.yaml "
        f"(classify each; spec §5.2 names the verdicts): {unclassified}"
    )
    assert not gone, f"module_state.yaml rows the scan no longer finds (remove them): {gone}"


def test_every_row_has_a_known_verdict():
    bad = {site: row for site, row in load_inventory().items() if not isinstance(row, dict) or row.get("verdict") not in VERDICTS}
    assert not bad, f"rows without a known verdict ({sorted(VERDICTS)}): {bad}"


def test_every_warmed_row_names_its_loader_and_no_other_row_but_a_locked_one_does():
    for site, row in load_inventory().items():
        if row["verdict"] == "warmed":
            assert row.get("loader"), f"{site} is warmed but names no loader"
        elif row.get("loader"):
            assert row["verdict"] == "locked", f"{site} names a loader but is {row['verdict']}"


def test_the_race_fixes_carry_their_verdicts():
    rows = load_inventory()
    assert rows["engine.game.inventory._evaluating_collections"]["verdict"] == "per_context"
    assert rows["engine.games.validation._RUN_DOCS"]["verdict"] == "per_context"
    for site in (
        "engine.game.quests._grammar_loaded",
        "engine.config._instance",
        "engine.telemetry.oracle._oracle",
        "engine.persistence.saves._migrated",
        "engine.persistence.saves._stores",
    ):
        assert rows[site]["verdict"] == "locked", site


# -- the scan's rules, each shown on a synthetic module ----------------------


def test_the_scan_catches_a_new_module_dict():
    """The canary's shape, as a unit: `_X: dict = {}` is a site."""
    assert scan_source("_X: dict = {}\n", "engine.fake") == {"engine.fake._X"}


def test_the_scan_catches_each_kind_of_site():
    source = (
        "import threading, functools\n"
        "from contextvars import ContextVar\n"
        "from functools import lru_cache\n"
        "_NONE = None\n"
        "_LIST = []\n"
        "_SET = set()\n"
        "_COMP = {k: 1 for k in 'ab'}\n"
        "_LOCK = threading.Lock()\n"
        "_VAR = ContextVar('v', default=None)\n"
        "_FLAG = False\n"
        "_TUPLE = (1, 2)\n"
        "_TEXT = 'x'\n"
        "__all__ = ['f']\n"
        "if True:\n"
        "    _NESTED = {}\n"
        "def rebind():\n"
        "    global _FLAG\n"
        "    _FLAG = True\n"
        "@lru_cache(maxsize=2)\n"
        "def cached(x):\n"
        "    return x\n"
        "@functools.lru_cache(maxsize=1)\n"
        "def cached_too():\n"
        "    return 1\n"
        "class Worker:\n"
        "    def start(self):\n"
        "        threading.Thread(target=print).start()\n"
        "        threading.Thread(target=print).start()\n"
    )
    assert scan_source(source, "engine.fake") == {
        "engine.fake._NONE",
        "engine.fake._LIST",
        "engine.fake._SET",
        "engine.fake._COMP",
        "engine.fake._LOCK",
        "engine.fake._VAR",
        "engine.fake._FLAG",  # rebound through `global`
        "engine.fake._NESTED",
        "engine.fake.cached()",
        "engine.fake.cached_too()",
        "engine.fake.Worker.start#Thread",
        "engine.fake.Worker.start#Thread2",
    }


#: One snippet per kind of site the scan must see (T6 fix round 1: the first
#: scan saw none of the first six).
CANARIES = {
    "class-level cache": "class _Canary:\n    _cache = {}\n",
    "registry instance": "_REG = SomeRegistry()\n",
    "random instance": "import random\n_RNG = random.Random()\n",
    "queue instance": "import queue\n_Q = queue.Queue()\n",
    "thread pool": (
        "from concurrent.futures import ThreadPoolExecutor\n"
        "def _fan_out():\n    with ThreadPoolExecutor(max_workers=2) as pool:\n        pass\n"
    ),
    "timer": "import threading\ndef _later():\n    threading.Timer(1.0, print).start()\n",
    "Thread subclass": "import threading\nclass _Worker(threading.Thread):\n    pass\n",
    "Thread at module scope": "import threading\n_T = threading.Thread(target=print)\n",
    "Thread at class scope": "import threading\nclass _Holder:\n    t = threading.Thread(target=print)\n",
    "module dict": "_X: dict = {}\n",
}


@pytest.mark.parametrize("kind", sorted(CANARIES))
def test_a_new_site_of_each_kind_in_a_real_engine_module_fails_the_pin(kind):
    """
    The canary, per kind, in memory: a real engine module's source with the
    snippet appended yields a site the inventory does not classify, so
    ``test_the_scan_equals_the_inventory`` would fail on it.
    """
    source = (ROOT / "engine" / "names.py").read_text(encoding="utf-8")
    before = scan_source(source, "engine.names")
    after = scan_source(source + "\n" + CANARIES[kind], "engine.names")
    new = after - before
    assert new, f"the scan does not see a {kind}"
    assert not new & set(load_inventory()), f"a {kind} would be classified already: {new}"
