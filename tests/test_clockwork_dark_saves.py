"""
v0.24.0 flagship saves load and play under v0.25.0 (spec §11.1, §12.4).

The nine fixtures are recorded by plan T0 from the v0.24.0 tree, under
``CLOCKWORK_FLAGSHIP_RECORD=1``. Each is ``GameState.to_save_dict()`` as
v0.24.0 wrote it. A fixture is CONSTRUCTED, not played: the builders below
write quest records and a doom reading directly, which no gameplay path
does -- the point is the shape of a save v0.24.0 could hold, not the road
to it. Read back through the save migrator, as ``SaveStore.load`` does.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable

import pytest

from tests.flagship_overhaul_recorder import VOLATILE

SAVES =Path(__file__).parent / "fixtures" / "clockwork_dark_v0240"
RECORD = os.environ.get("CLOCKWORK_FLAGSHIP_RECORD") == "1"
NAMES = (
    "1_new_run", "2_caravan_active", "3_seam_solved", "4_seam_unsolved", "5_at_the_question",
    "6_at_choose_what", "7_at_pay_it_by_narrator", "8_old_press", "9_locked_hearth",
)


def _new(seed: int = 7) -> Any:
    from engine.game.procgen import new_game_state

    return new_game_state(seed=seed)


def _effect(state: Any, **row: Any) -> None:
    from engine.game.effects import apply_effect

    apply_effect(state, dict(row))


def _flag(state: Any, flag: str) -> None:
    _effect(state, type="flag", flag=flag, value=True)


def _to_day(state: Any, day: int) -> None:
    from engine.game.clock import advance_time

    while state.world_day < day:
        advance_time(state, 24.0)


def _quest(state: Any, quest_id: str, stage: int, *, status: str = "active") -> None:
    from engine.game.quests import QuestProgress

    state.quests[quest_id] = QuestProgress(
        quest_id=quest_id, stage_index=stage, status=status,
        started_day=max(1, state.world_day - 1), stage_started_day=state.world_day,
    ).to_dict()


def _doom(state: Any, progress: float) -> None:
    """A world this far gone, its doom beats fired the way advance_time fires them."""
    from engine.world import world_effects

    state.evil_progress = float(progress)
    world_effects.apply_pending_beats(state)


def _item(state: Any, item_id: str) -> None:
    _effect(state, type="item", item_id=item_id, qty=1)


def _force(state: Any, event_id: str) -> None:
    """An event forced through the world tick, then seen as a turn sees it (`QuestEngine.observe`)."""
    from engine.game.quests import QuestEngine
    from engine.world.world_sim import WorldSim

    WorldSim.on_tick(state, hours=1.0, force=[event_id])
    QuestEngine.evaluate(state)


def _b1(s: Any) -> None:
    s.turn_number = 1


def _b2(s: Any) -> None:
    _to_day(s, 6)
    _force(s, "caravan_arrival")


def _b3(s: Any) -> None:
    _doom(s, 0.72)
    _flag(s, "seam_opened")


def _b4(s: Any) -> None:
    _doom(s, 0.72)


def _b5(s: Any) -> None:
    _to_day(s, 20)
    _quest(s, "bakery_apprentice", 3, status="completed")
    _quest(s, "banking_the_fire", 1)
    _flag(s, "nf_hearth_taking_stock")


def _sacrifice_open(s: Any) -> None:
    _doom(s, 0.55)
    _effect(s, type="awareness", delta=60)
    _quest(s, "naming_the_wound", 3, status="completed")
    _item(s, "the_written_name")
    _item(s, "brass_shard")


def _b6(s: Any) -> None:
    _sacrifice_open(s)
    _quest(s, "the_sacrifice", 1)
    _flag(s, "nf_sacrifice_understood")


def _b7(s: Any) -> None:
    _sacrifice_open(s)
    _flag(s, "nf_sacrifice_understood")
    _flag(s, "nf_sacrifice_chosen")
    _quest(s, "the_sacrifice", 2)


def _b8(s: Any) -> None:
    _effect(s, type="awareness", delta=25)
    _to_day(s, 4)
    _force(s, "militia_press")
    _to_day(s, 20)


def _b9(s: Any) -> None:
    _quest(s, "bakery_apprentice", 3, status="completed")
    _flag(s, "nf_hearth_book_closed")
    _effect(s, type="ending_lock", ending="the_hearth_holds")
    _effect(s, type="ending_module")


BUILDERS: dict[str, Callable[[Any], None]] = dict(zip(NAMES, (_b1, _b2, _b3, _b4, _b5, _b6, _b7, _b8, _b9)))


def load_fixture(name: str) -> Any:
    """A recorded v0.24.0 state, migrated as SaveStore.load migrates one."""
    from engine.game.state import GameState
    from engine.persistence.migrations import migrate

    raw = json.loads((SAVES / f"{name}.json").read_text(encoding="utf-8"))
    return GameState.from_dict(migrate(raw, slug="clockwork-dark"))


@pytest.fixture
def flagship():
    from engine.games import registry

    registry.activate("clockwork-dark")
    try:
        yield
    finally:
        registry.deactivate()


def test_the_v0240_saves_exist_or_are_made_now(flagship) -> None:
    """Under CLOCKWORK_FLAGSHIP_RECORD=1 (plan T0, in the v0.24.0 worktree) this WRITES the nine."""
    if RECORD:
        SAVES.mkdir(parents=True, exist_ok=True)
        for name, build in BUILDERS.items():
            state = _new()
            build(state)
            # session_id (minted per state) and last_sim_tick_at (the wall
            # clock) differed between plan T0's two recordings; the rest
            # was byte-identical. Dropped so a fixture is reproducible.
            raw = {k: v for k, v in state.to_save_dict().items() if k not in VOLATILE}
            (SAVES / f"{name}.json").write_text(
                json.dumps(raw, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    assert sorted(p.stem for p in SAVES.glob("*.json")) == sorted(NAMES)


@pytest.mark.parametrize("name", NAMES)
def test_each_v0240_save_loads(flagship, name: str) -> None:
    state = load_fixture(name)
    assert state.save_version == 2 and state.world_day >= 1
