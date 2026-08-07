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
sys.modules and mask the cycle.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

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


@pytest.mark.parametrize("module", MODULES)
def test_module_imports_first(module):
    """Every module must be safe as the FIRST engine import in a process."""
    result = subprocess.run(
        [sys.executable, "-c", f"import {module}"],
        cwd=str(ROOT),
        capture_output=True,
        timeout=90,
    )
    assert result.returncode == 0, (
        f"{module} cannot be imported first:\n"
        + result.stderr.decode("utf-8", "replace")[-800:]
    )


def test_lazy_reexports_still_resolve():
    """Laziness must not cost the convenience imports."""
    from engine.game import EvilPhase, GameEngine, GameState, PlayerStats
    from engine.world import ScheduleRoll, SimEvent, WorldSim

    assert all(
        obj is not None
        for obj in (EvilPhase, GameEngine, GameState, PlayerStats, ScheduleRoll, SimEvent, WorldSim)
    )
