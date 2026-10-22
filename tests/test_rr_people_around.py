"""Background people through npc_sim, and the narrator's brief (v0.23.0 addendum 4, W8, W10)."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from tests.social_fixtures import receipts_active, receipts_state  # noqa: F401

STORY = Path(__file__).resolve().parents[1] / "games" / "read-receipts"


def _rows() -> dict:
    return (yaml.safe_load((STORY / "data/world/npc_schedules.yaml").read_text(encoding="utf-8")) or {})["npcs"]


def test_the_story_declares_its_schedules(receipts_active) -> None:
    from engine.config import get_config

    assert str(get_config().get("paths.npc_schedules", "")).endswith("data/world/npc_schedules.yaml")


def test_staff_have_no_home_and_name_real_places(receipts_active) -> None:
    from engine.game.locations import LOCATIONS

    rows = _rows()
    assert len(rows) == 7
    for npc_id, row in rows.items():
        assert "home" not in row, npc_id
        assert row["name"] and row["role"], npc_id
        assert all(slot["location"] in LOCATIONS for slot in row["routine"]), npc_id


def test_staff_names_are_not_contact_names() -> None:
    pop = yaml.safe_load((STORY / "data/social/population.yaml").read_text(encoding="utf-8"))
    pool = {n.lower() for names in pop["names"].values() for n in names}
    for row in _rows().values():
        assert row["name"].split()[0].lower() not in pool, row["name"]


def test_the_validator_passes_the_file(receipts_active) -> None:
    from engine.games import validation

    report = validation.validate_story("read-receipts")
    assert not [e for e in getattr(report, "errors", []) if "npc_schedules" in str(e)]


def test_staff_present_on_shift_only(receipts_state) -> None:
    from engine.world import npc_sim
    from tests.social_fixtures import _set_clock

    _set_clock(receipts_state, 9)
    on = [p.npc_id for p in npc_sim.npcs_at(receipts_state, "copper_kettle")]
    _set_clock(receipts_state, 3)
    off = [p.npc_id for p in npc_sim.npcs_at(receipts_state, "copper_kettle")]
    assert on == ["marcelline_barista"] and not off
    # Off shift is off the map entirely, not at some home.
    assert npc_sim.resolve_npc(receipts_state, "marcelline_barista").location_id == ""


def test_people_here_names_the_barista(receipts_state) -> None:
    from engine.agents import prompts
    from tests.social_fixtures import _set_clock

    _set_clock(receipts_state, 9)
    receipts_state.location_id = "copper_kettle"
    block = prompts._npcs_present_block(receipts_state)
    assert "Marcelline Duarte" in block and "nobody" not in block.lower()
    _set_clock(receipts_state, 18)
    assert "nobody" in prompts._npcs_present_block(receipts_state).lower()


def test_the_roster_is_the_seven_and_no_contact(receipts_state) -> None:
    from engine.world import npc_sim

    roster = set(npc_sim.known_npc_ids(receipts_state))
    assert roster == set(_rows()) and len(roster) == 7


def test_a_present_barista_passes_the_gate_and_a_contact_still_checks(receipts_state) -> None:
    from engine.agents import cast
    from engine.social import agreement
    from tests.social_fixtures import _set_clock

    _set_clock(receipts_state, 9)
    receipts_state.location_id = "copper_kettle"
    absent = cast.absent_cast(receipts_state)
    assert "marcelline_barista" not in absent                 # here, so nameable
    prose = "Marcelline slides your flat white across and Sam's name buzzes on your phone."
    assert cast.find_intrusion(prose, absent) in (None, "")
    # An absent worker named from elsewhere is still an intrusion (the gate is unchanged).
    receipts_state.location_id = "apt_lounge"
    absent = cast.absent_cast(receipts_state)
    assert "marcelline_barista" in absent
    assert cast.find_intrusion("Marcelline texts you.", absent)
    # Contact names are still the agreement check's: staff names do not enter its forms.
    assert not agreement.name_forms("Sam") & agreement.name_forms("Marcelline Duarte")


def test_npc_sim_costs_nothing_per_turn_and_keeps_nothing(receipts_state) -> None:
    import json
    import time

    from engine.world import npc_sim

    before = len(json.dumps(receipts_state.to_save_dict(), default=str))
    start = time.perf_counter()
    for _ in range(200):
        npc_sim.npcs_at(receipts_state, "copper_kettle")
    per_call_ms = (time.perf_counter() - start) * 1000 / 200
    assert per_call_ms < 20
    assert len(json.dumps(receipts_state.to_save_dict(), default=str)) == before


def _brief() -> str:
    return (STORY / "prompts" / "storyteller.md").read_text(encoding="utf-8")


def test_storyteller_has_choices_section() -> None:
    text = _brief()
    assert "## CHOICES" in text and "80" in text and "200" in text and "WHO IS AROUND" in text


def test_the_brief_renders_a_band_as_a_reaction() -> None:
    text = _brief()
    assert "## TYPED LINES" in text and "never print that word" in text


def test_the_brief_carries_no_register_language() -> None:
    text = _brief().lower()
    for word in ("rating", "intensity", "explicit", "fade", "tier", "boundary", "safety", "mature", "nsfw"):
        assert not re.search(rf"\b{word}", text), word
