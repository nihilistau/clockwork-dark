"""
The Clockwork Dark, overhauled (v0.25.0; spec docs/superpowers/specs/
2026-10-27-v0.25.0-clockwork-dark-overhaul-design.md).

One file for the story's own claims, grown task by task: the cast (T4), the
map (T5), the doors (T6-T7), the critical path and the levy (T8), and the
card-only walks and the presence sweep (T9).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterator

import pytest
import yaml

from engine.games import registry

STORY = Path(__file__).resolve().parents[1] / "games" / "clockwork-dark"
NEW_PEOPLE = ("npc_hallam", "npc_nessa", "npc_wenna", "npc_edrin")

#: Plan decision 2: each person's hours, each covering the day exactly once.
WHERE = {
    "npc_hallam": {"the_forge": range(6, 19), "edgewood_square": (19, 20),
                   "well_row": (21, 22, 23, 0, 1, 2, 3, 4, 5)},
    "npc_nessa": {"fallow_farm": (6, 7, 8, 17, 18, 19, 20, 21, 22, 23, 0, 1, 2, 3, 4, 5),
                  "edgewood_square": range(9, 17)},
    "npc_wenna": {"edgewood_shrine": (6, 7, 18, 19, 20, 21), "well_row": (*range(8, 18), 22, 23, 0, 1, 2, 3, 4, 5)},
    "npc_edrin": {"fallow_farm": range(24)},
}
ASLEEP = {
    "npc_hallam": {21, 22, 23, 0, 1, 2, 3, 4, 5}, "npc_nessa": {21, 22, 23, 0, 1, 2, 3, 4, 5},
    "npc_wenna": {22, 23, 0, 1, 2, 3, 4, 5}, "npc_edrin": {20, 21, 22, 23, 0, 1, 2, 3, 4},
}


@pytest.fixture
def flagship() -> Iterator[None]:
    registry.activate("clockwork-dark")
    try:
        yield
    finally:
        registry.deactivate()


def new_state(seed: int = 7) -> Any:
    from engine.game.procgen import new_game_state

    return new_game_state(seed=seed)


def at_hour(state: Any, hour: int) -> None:
    """Stand on an hour of the current day (tests only; `set_clock` writes no world)."""
    from engine.game.clock import set_clock

    set_clock(state, day=state.world_day, hour=hour)


def _schedules() -> dict:
    return yaml.safe_load((STORY / "data" / "world" / "npc_schedules.yaml").read_text(encoding="utf-8"))


# -- the cast (T4, §3.3) ------------------------------------------------------------------------------


def test_the_four_new_people_cover_every_hour_once() -> None:
    npcs = _schedules()["npcs"]
    for npc_id in NEW_PEOPLE:
        row = npcs[npc_id]
        assert row["name"] and row["role"] and row["home"], npc_id
        hours = sorted(h for slot in row["routine"] for h in slot["hours"])
        assert hours == list(range(24)), npc_id


@pytest.mark.parametrize("npc_id", NEW_PEOPLE)
def test_each_stands_where_the_cast_table_puts_them(flagship, npc_id: str) -> None:
    from engine.world import npc_sim

    state = new_state()
    for place, hours in WHERE[npc_id].items():
        for hour in hours:
            at_hour(state, hour)
            presence = npc_sim.resolve_npc(state, npc_id)
            assert presence.location_id == place, (npc_id, hour)
            assert presence.available is (hour not in ASLEEP[npc_id]), (npc_id, hour)


def test_they_are_not_in_the_procgen_village() -> None:
    """§3.3: the PROCGEN stream draws the template's named list; adding to it would regenerate every seed."""
    template = (STORY / "data" / "procgen_templates" / "edgewood.yaml").read_text(encoding="utf-8")
    assert not any(npc_id in template for npc_id in NEW_PEOPLE)


def test_nessa_has_one_surname() -> None:
    for path in STORY.rglob("*"):
        if path.is_file() and path.suffix in (".yaml", ".md", ".json"):
            text = path.read_text(encoding="utf-8")
            assert "Nessa Weller" not in text and "Weller girl" not in text, path
    assert "Weller" in (STORY / "data" / "quests" / "quiet_life" / "lost_goat.yaml").read_text(encoding="utf-8")


#: An age as the story's text gives it: "a six-year-old", "She is six", "Nessa Fallow, nine".
_AGE = re.compile(
    r"\b(\w+)[- ]years?[- ]old\b|\bshe is (\w+)\b|\bNessa(?: Fallow)?, (\w+)\b", re.IGNORECASE
)
_NUMBER_WORDS = {"one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
                 "eleven", "twelve", "thirteen", "fourteen"}


def test_nessa_is_nine_everywhere_the_story_gives_her_age() -> None:
    """v0.25.0 T4 fix round 1 (the controller's ruling): the cast line, the portrait and the
    quest gave a narrator two ages. Every age in a file that speaks of Nessa (or of her
    drawing, `childs_drawing`) is nine."""
    ages: list[tuple[str, str]] = []
    for path in STORY.rglob("*"):
        if not (path.is_file() and path.suffix in (".yaml", ".md", ".json")) or path.name == "CHANGELOG.md":
            continue
        text = path.read_text(encoding="utf-8")
        if "Nessa" not in text and path.name != "childs_drawing.yaml":
            continue
        for match in _AGE.finditer(text):
            word = next(g for g in match.groups() if g).lower()
            if word in _NUMBER_WORDS or word.isdigit():
                ages.append((path.name, word))
    assert ages, "no age found: the pattern no longer reads the story"
    assert all(word == "nine" for _, word in ages), ages


def test_the_vines_bring_ilya_to_the_square(flagship) -> None:
    from engine.world import npc_sim, world_effects

    state = new_state()
    at_hour(state, 10)
    assert npc_sim.resolve_npc(state, "npc_ilya").location_id == "tinker_caravan"
    world_effects.apply_beat(state, "vines_breach_forest")
    assert npc_sim.resolve_npc(state, "npc_ilya").location_id == "edgewood_square"


def test_the_tower_empties_the_fallow_holding_and_brings_sera_in(flagship) -> None:
    from engine.world import npc_sim, world_effects

    state = new_state()
    at_hour(state, 10)
    world_effects.apply_beat(state, "tower_assembles")
    for npc_id, place in (("npc_edrin", "refugee_camp"), ("npc_nessa", "refugee_camp"),
                          ("npc_sera", "edgewood_square")):
        assert npc_sim.resolve_npc(state, npc_id).location_id == place, npc_id


def test_a_pin_still_outranks_a_doom_move(flagship) -> None:
    from engine.game.effects import apply_effect
    from engine.world import npc_sim, world_effects

    state = new_state()
    at_hour(state, 10)
    world_effects.apply_beat(state, "vines_breach_forest")
    apply_effect(state, {"type": "flag", "flag": "npc_pin_npc_ilya", "value": True})
    assert npc_sim.resolve_npc(state, "npc_ilya").location_id == "tinker_caravan"


def test_the_codex_lists_the_declared_people_named_once_met(flagship) -> None:
    from types import SimpleNamespace

    from engine.scenes import default_api

    state = new_state()
    unmet = default_api.codex_souls(state, SimpleNamespace(relations={}))["souls"]
    met = default_api.codex_souls(state, SimpleNamespace(relations={"npc_hallam": SimpleNamespace(met=True)}))["souls"]
    assert len(unmet) == len(state.procgen.npcs) + len(NEW_PEOPLE)
    assert "Hallam" in [s["name"] for s in met] and "Hallam" not in [s["name"] for s in unmet]
    assert sum(1 for s in met if s["name"] == "Hallam") == 1


def test_the_prompt_names_the_four_and_nothing_else_moved() -> None:
    prompt = (STORY / "prompts" / "storyteller.md").read_text(encoding="utf-8")
    for name in ("Hallam", "Nessa Fallow", "Wenna", "Edrin Fallow"):
        assert name in prompt
    for word in ("intensity", "explicit", "safety", "content limit"):
        assert word not in prompt.lower()          # rule 12
