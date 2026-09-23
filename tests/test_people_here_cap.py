"""
PEOPLE HERE names the cast and a few townsfolk, then counts the rest.

THE BUG. HUE & CRY's thirty-one generated houses put about eighty household
people into its districts, every one a real presence -- and
``prompts._npcs_present_block`` listed everybody. Across forty seeds the
busiest district-hour held nineteen people, fifteen of them generated
strangers: a prompt block the size of a parish register.

THE RULE. Every scheduled cast member is listed individually, always.
Generated household people (a ``premise`` key on the procgen row) are listed
individually up to ``prompts.MAX_GENERATED_PRESENT``; the remainder become one
"- and N more townsfolk about their business" line. Procgen people without a
``premise`` key -- the flagship's villagers -- are untouched, so the
flagship's block is byte-identical to the uncapped rendering.

Version: v0.1.0 [2026-09-23]
"""

from __future__ import annotations

from typing import Any

from engine.agents import prompts
from engine.game.clock import set_clock
from engine.game.procgen import new_game_state
from engine.games import registry
from engine.world import npc_sim
from engine.world.world_sim import merge_npcs_at_location


def _uncapped(state: Any) -> str:
    """The block as it rendered before the cap: one line per person present."""
    present = merge_npcs_at_location(state, state.location_id)
    if not present:
        return "PEOPLE HERE: nobody."
    lines = []
    for npc in present:
        npc_id = str(npc.get("id") or "")
        name = npc.get("name") or npc_sim.display_name(npc_id, state)
        role = f" ({npc.get('role')})" if npc.get("role") else ""
        line = f"- {npc_id}: {name}{role}"
        if npc.get("activity"):
            line += f" -- {npc['activity']}"
        if npc.get("visiting"):
            line += " [visiting]"
        lines.append(line)
    return "PEOPLE HERE:\n" + "\n".join(lines)


def _crowded_hue_state() -> tuple[Any, list[dict[str, Any]]]:
    """A HUE & CRY district-hour holding more generated people than the cap."""
    registry.activate("hue-and-cry")
    for seed in range(40):
        state = new_game_state(seed=seed)
        for hour in range(24):
            set_clock(state, day=1, hour=hour)
            for district in ("wickmarket", "chandlers_rise", "tallow_docks", "silk_row"):
                state.location_id = district
                present = merge_npcs_at_location(state, district)
                generated = [p for p in present if p.get("premise")]
                if len(generated) > prompts.MAX_GENERATED_PRESENT + 1:
                    return state, present
    raise AssertionError("no district-hour over the cap in 40 seeds -- fixture broken")


def test_an_over_cap_crowd_collapses_to_one_line() -> None:
    try:
        state, present = _crowded_hue_state()
        block = prompts._npcs_present_block(state)
        generated = [p for p in present if p.get("premise")]
        listed = [p for p in generated if f"- {p['id']}:" in block]
        assert len(listed) == prompts.MAX_GENERATED_PRESENT
        more = len(generated) - prompts.MAX_GENERATED_PRESENT
        assert block.splitlines()[-1] == f"- and {more} more townsfolk about their business"
    finally:
        registry.activate("clockwork-dark")


def test_the_scheduled_cast_is_never_summarised() -> None:
    try:
        state, present = _crowded_hue_state()
        block = prompts._npcs_present_block(state)
        scheduled = set((npc_sim.load_npc_schedules().get("npcs") or {}))
        cast = [p for p in present if p["id"] in scheduled]
        for person in cast:
            assert f"- {person['id']}: {person['name']}" in block, person["id"]
    finally:
        registry.activate("clockwork-dark")


def test_a_story_without_premises_renders_byte_identically() -> None:
    registry.activate("clockwork-dark")
    state = new_game_state(seed=42)
    checked = 0
    for location in sorted({str(n.get("location_id") or "") for n in state.procgen.npcs}):
        if not location:
            continue
        for hour in (3, 9, 13, 19):
            set_clock(state, day=1, hour=hour)
            state.location_id = location
            assert prompts._npcs_present_block(state) == _uncapped(state), (location, hour)
            checked += 1
    assert checked
