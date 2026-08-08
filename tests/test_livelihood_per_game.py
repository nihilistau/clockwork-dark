"""
Livelihood systems across both installed games.

THE BUG THIS FILE EXISTS FOR: ``engine/game/checks.py::_load_table`` hardcoded
``data/tables/`` instead of resolving through ``get_config()``. With two games
installed that meant a natural 20 on the Brass Coast drew an Edgewood forest
boon -- silently, because every content loader in this engine degrades to an
empty list rather than raising. It fixed itself into invisibility.

The second half of the claim matters as much: anything P12 added must exist in
BOTH games or be cleanly absent from one. No crash, no ERROR log, no silently
borrowed content.
"""

from __future__ import annotations

import logging
from typing import Any, Iterator

import pytest

from engine.game import checks as checks_module
from engine.game import economy, foraging, inventory, trade
from engine.game.procgen import new_game_state
from engine.games import registry

GAMES = ("clockwork-dark", "drowned-carillon")


@pytest.fixture
def activated(request: Any) -> Iterator[str]:
    """Activate a game for the duration of a test, then restore the flagship."""
    slug = request.param
    registry.activate(slug)
    try:
        yield slug
    finally:
        registry.activate("clockwork-dark")


@pytest.mark.parametrize("activated", GAMES, indirect=True)
def test_each_game_draws_its_own_boons_and_complications(activated: str):
    boons = {row["id"] for row in checks_module._load_table("boons.yaml", "boons")}
    complications = {
        row["id"] for row in checks_module._load_table("complications.yaml", "complications")
    }
    assert boons, f"{activated} resolved no boon table at all"
    assert complications, f"{activated} resolved no complication table at all"

    if activated == "clockwork-dark":
        assert "forager_luck" in boons
        assert "low_water_luck" not in boons
    else:
        assert "low_water_luck" in boons
        assert "forager_luck" not in boons, "the coast is drawing Edgewood's boons"
        assert "the_note_gets_in" in complications


@pytest.mark.parametrize("activated", GAMES, indirect=True)
def test_every_livelihood_table_id_resolves_in_that_game_registry(activated: str):
    """
    A forage row, a wage in-kind or a vendor stock line naming an item that
    game does not declare is a reference that resolves to nothing, raises
    nothing, and produces a pick the player can never receive.
    """
    known = set(inventory.load_items())
    assert known, f"{activated} loaded an empty item registry"

    missing: list[str] = []
    for table in foraging.load_rules().get("tables") or []:
        for pool in ("common", "uncommon"):
            for row in table.get(pool) or []:
                item_id = str(row.get("item_id"))
                if item_id not in known:
                    missing.append(f"forage/{table.get('id')}/{pool}: {item_id}")

    for job_id, job in economy.jobs().items():
        for row in job.get("in_kind") or []:
            item_id = str(row.get("item_id"))
            if item_id not in known:
                missing.append(f"labour/{job_id}: {item_id}")
        requires_item = (job.get("requires") or {}).get("item")
        if requires_item and str(requires_item) not in known:
            missing.append(f"labour/{job_id}/requires: {requires_item}")

    assert not missing, f"{activated} has dangling item references: {missing}"


@pytest.mark.parametrize("activated", GAMES, indirect=True)
def test_every_job_names_a_place_that_exists(activated: str):
    from engine.game.locations import LOCATIONS

    for job_id, job in economy.jobs().items():
        where = str(job.get("location_id") or "")
        if where:
            assert where in LOCATIONS, f"{activated}: job {job_id} is at nowhere ({where})"


@pytest.mark.parametrize("activated", GAMES, indirect=True)
def test_every_vendor_names_a_place_and_a_faction_that_exist(activated: str):
    from engine.game import reputation
    from engine.game.locations import LOCATIONS

    factions = set(reputation.faction_ids())
    for npc_id, profile in trade.vendors().items():
        where = str(profile.get("location") or "")
        assert where in LOCATIONS, f"{activated}: vendor {npc_id} is at nowhere ({where})"
        faction = str(profile.get("faction") or "")
        if faction:
            assert faction in factions, f"{activated}: vendor {npc_id} bills to {faction}"


@pytest.mark.parametrize("activated", GAMES, indirect=True)
def test_a_broke_player_can_forage_food_in_either_game(activated: str):
    """The soft-lock this whole package closes, checked on both maps."""
    entry = registry.active().entry.get("location_id", "")
    state = new_game_state(seed=42, location_id=entry)
    state.stats.gold = 0

    places = sorted(foraging._all_forageable_places())
    assert places, f"{activated} has no forageable ground at all"

    state.location_id = places[0]
    found = 0
    for _ in range(15):
        for row in foraging.forage(state).get("found", []):
            if inventory.has_tag(str(row["item_id"]), "food"):
                found += int(row["qty"])
        state.stats.stamina = 100
    assert found > 0, f"{activated}: fifteen forages produced no food"


@pytest.mark.parametrize("activated", GAMES, indirect=True)
def test_a_shift_can_be_worked_in_either_game(activated: str):
    jobs = economy.jobs()
    assert jobs, f"{activated} declares no paid work"

    job_id, job = next(iter(sorted(jobs.items())))
    state = new_game_state(seed=42, location_id=str(job.get("location_id") or ""))
    outcome = economy.work(state, job_id)
    assert "check" in outcome, f"{activated}: {job_id} would not run: {outcome}"


@pytest.mark.parametrize("activated", GAMES, indirect=True)
def test_no_livelihood_system_logs_an_error_in_either_game(
    activated: str, caplog: pytest.LogCaptureFixture
):
    """
    Cleanly absent, never noisy.

    A game is allowed to ship without foraging or labour. What it is not
    allowed to do is log an error about it, because that is indistinguishable
    from a broken manifest in a support thread.
    """
    entry = registry.active().entry.get("location_id", "")
    state = new_game_state(seed=42, location_id=entry)

    with caplog.at_level(logging.WARNING):
        foraging.snapshot(state)
        economy.snapshot(state)
        trade.snapshot(state)
        inventory.snapshot(state)
        foraging.forage(state)
        economy.work(state, "a_job_that_does_not_exist")
        trade.quote(state, "npc_nobody", "loaf")

    loud = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert not loud, [r.getMessage() for r in loud]
