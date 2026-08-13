"""
Livelihood systems, per game that has them.

THE BUG THIS FILE EXISTS FOR: ``engine/game/checks.py::_load_table`` hardcoded
the flagship's tables directory instead of resolving through ``get_config()``.
With two games
installed that meant a natural 20 in the second story drew an Edgewood forest
boon -- silently, because every content loader in this engine degrades to an
empty list rather than raising. It fixed itself into invisibility.

WHY THIS PARAMETRIZE HAS ONE ENTRY. It used to have two, and the second was The
Drowned Carillon, which ran the same livelihood systems over different nouns --
forage tables, jobs, vendors, an economy. That story is gone. The other shipped
story, The Wicked Garden, is deliberately NOT added in its place: it declares no
``paths.economy``, no forage rules and no travel graph, and prices every item at
zero because there is no coin in it. Adding it here would assert a system it
does not run, and each of these tests would be asserting that an empty table is
a bug when it is the design.

What the Garden IS held to is the last test in this file, which is the half of
the claim that still generalises: a game is allowed to ship without foraging or
labour, but it is not allowed to be NOISY about it.

Version: v0.2.0 [2026-08-09]
"""

from __future__ import annotations

import logging
from typing import Any, Iterator

import pytest

from engine.game import checks as checks_module
from engine.game import economy, foraging, inventory, trade
from engine.game.procgen import new_game_state
from engine.games import registry

#: Games that declare livelihood content. See the module docstring for why
#: The Wicked Garden is not one of them; Dev Story ships items but no economy,
#: forage rules or vendors, so it belongs with the Garden below. STATIC on
#: purpose -- whether a story runs these systems is an authoring decision read
#: from its content, and a derived list would assert whatever it found.
GAMES = ("clockwork-dark",)

#: Every installed story, for the one claim that holds regardless. Derived,
#: because "cleanly absent, never noisy" is owed to any story that exists.
ALL_GAMES = tuple(sorted(registry.discover()))


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
    assert "forager_luck" in boons


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
def test_a_broke_player_can_forage_food_where_there_is_ground_to_forage(activated: str):
    """The soft-lock this whole package closes, checked on every map that has one."""
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
def test_a_shift_can_be_worked_where_there_is_paid_work(activated: str):
    jobs = economy.jobs()
    assert jobs, f"{activated} declares no paid work"

    job_id, job = next(iter(sorted(jobs.items())))
    state = new_game_state(seed=42, location_id=str(job.get("location_id") or ""))
    outcome = economy.work(state, job_id)
    assert "check" in outcome, f"{activated}: {job_id} would not run: {outcome}"


@pytest.mark.parametrize("activated", ALL_GAMES, indirect=True)
def test_no_livelihood_system_logs_an_error_in_any_game(
    activated: str, caplog: pytest.LogCaptureFixture
):
    """
    Cleanly absent, never noisy.

    A game is allowed to ship without foraging or labour. What it is not
    allowed to do is log an error about it, because that is indistinguishable
    from a broken manifest in a support thread.

    This is the one test in the file that runs over EVERY installed story, and
    it is the reason the rest may safely run over only the flagship: The Wicked
    Garden has none of these systems, so this is the whole of what the engine
    owes it -- silence.
    """
    entry = registry.active().entry.get("location_id", "")
    state = new_game_state(seed=42, location_id=entry)

    # Only the seven calls below are on trial. Building the state is setup, and
    # it is noisy for a reason that has nothing to do with livelihood: a story
    # declaring no `paths.procgen_templates` has empty name pools and procgen
    # says so once per new run. Letting that land here would make this test
    # fail for a fact about character generation.
    caplog.clear()

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
