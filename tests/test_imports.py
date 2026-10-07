"""
Import-order tests.

Two package cycles hid here, both invisible in normal runs because some other
module always happened to import the packages in a lucky order:

    engine.memory  -> context -> agents.prompts -> agents/__init__
                   -> storyteller -> memory.context   (partial)

    engine.world/__init__ -> schedules -> engine.game/__init__
                          -> engine.game.engine -> world_sim
                          -> world.schedules             (partial)

Each module is imported in a FRESH subprocess so nothing else can prime
sys.modules and mask the cycle. The subprocesses run together, a bounded batch
one module fixture starts (v0.21.1 T4, tests/child_batch.py).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from tests.child_batch import Done, run_together, selected

pytestmark = pytest.mark.process

ROOT = Path(__file__).resolve().parent.parent

MODULES = [
    "engine.agents",
    "engine.game",
    "engine.game.checks",
    "engine.game.clock",
    "engine.game.effects",
    "engine.game.engine",
    "engine.game.survival",
    "engine.game.transaction",
    "engine.lore",
    "engine.media.providers",
    "engine.memory",
    "engine.persistence",
    "engine.skills",
    "engine.world",
    "engine.world.npc_sim",
    "engine.world.schedules",
    "engine.world.world_sim",
]


@pytest.fixture(scope="module")
def first_imports(
    request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory
) -> dict[str, Done]:
    """Every selected module's fresh-interpreter import, started together (a
    bounded batch, tests/child_batch.py) -- each child still its own
    interpreter, which is the point -- and read back by each test."""
    wanted = set(selected(request, "test_module_imports_first", "module"))
    return run_together(
        {module: [sys.executable, "-c", f"import {module}"] for module in MODULES if module in wanted},
        out_dir=tmp_path_factory.mktemp("imports"),
        cwd=ROOT,
        timeout=180,
    )


@pytest.mark.parametrize("module", MODULES)
def test_module_imports_first(module, first_imports):
    """Every module must be safe as the FIRST engine import in a process."""
    done = first_imports[module]
    err = "timed out after 180 s" if done.timed_out else done.stderr.decode("utf-8", "replace")[-800:]
    assert done.returncode == 0, f"{module} cannot be imported first:\n{err}"


def test_lazy_reexports_still_resolve():
    """Laziness must not cost the convenience imports."""
    from engine.game import EvilPhase, GameEngine, GameState, PlayerStats
    from engine.world import ScheduleRoll, SimEvent, WorldSim

    assert all(
        obj is not None
        for obj in (EvilPhase, GameEngine, GameState, PlayerStats, ScheduleRoll, SimEvent, WorldSim)
    )
