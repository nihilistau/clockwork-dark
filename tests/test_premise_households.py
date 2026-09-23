from engine.game.clock import set_clock
from engine.game.state import GameState
from engine.world import npc_sim


def _state_with(npc):
    state = GameState(rng_seed=1)
    state.procgen.npcs.append(npc)
    return state


def test_a_generated_person_follows_their_routine() -> None:
    npc = {"id": "gen_cook_1", "name": "Hesk", "role": "cook", "home": "silk_row/prem_1",
           "routine": [{"hours": list(range(6, 10)), "location": "wickmarket",
                        "activity": "haggling for onions"}]}
    state = _state_with(npc)
    set_clock(state, day=1, hour=7)
    assert npc_sim.resolve_npc(state, "gen_cook_1").location_id == "wickmarket"
    set_clock(state, day=1, hour=20)
    assert npc_sim.resolve_npc(state, "gen_cook_1").location_id == "silk_row/prem_1"


def test_a_person_at_home_is_not_on_the_street() -> None:
    npc = {"id": "gen_cook_1", "name": "Hesk", "role": "cook", "home": "silk_row/prem_1",
           "routine": []}
    state = _state_with(npc)
    assert [p.npc_id for p in npc_sim.npcs_at(state, "silk_row")] == []
    assert [p.npc_id for p in npc_sim.npcs_at(state, "silk_row/prem_1")] == ["gen_cook_1"]


def test_interior_ids() -> None:
    assert npc_sim.interior_id("silk_row", "prem_1") == "silk_row/prem_1"
    assert npc_sim.is_interior("silk_row/prem_1") and not npc_sim.is_interior("silk_row")


def test_a_schedule_row_still_wins(monkeypatch) -> None:
    npc = {"id": "gen_cook_1", "name": "Hesk", "role": "cook", "home": "silk_row/prem_1",
           "routine": []}
    state = _state_with(npc)
    monkeypatch.setattr(
        npc_sim,
        "load_npc_schedules",
        lambda: {"npcs": {"gen_cook_1": {"name": "Hesk", "role": "cook",
                                         "home": "lantern_house", "routine": []}}},
    )
    assert npc_sim.resolve_npc(state, "gen_cook_1").location_id == "lantern_house"
