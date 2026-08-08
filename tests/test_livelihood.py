"""
Foraging, labour and trade — the livelihood systems (P12).

WHAT THESE TESTS ARE DEFENDING. Three claims, and each one is a bug that
shipped:

  1. A broke player can eat. ``scripts/simulate.py`` measured 62-79 starvation
     deaths per 200-turn run on every policy, because the only food in the game
     had a price and every policy ended at zero gold.
  2. A day's work pays. DESIGN.md makes the Quiet Life arc a complete way to
     play and nothing in the engine could hand a player a wage.
  3. Selling works. ``mechanics.trade`` refused any item a vendor had no
     explicit ``buys`` row for, which was almost everything -- so the barter
     system was inert in the direction players use most.

Plus the property that makes the numbers trustworthy at all: every draw runs on
a named RNG stream, so a seed replays and one system's rolls cannot shift
another's.
"""

from __future__ import annotations

import pytest

from engine.game import economy, foraging, inventory, survival, trade
from engine.game.procgen import new_game_state
from engine.game.state import EvilPhase, GameState


# ---------------------------------------------------------------------------
# item registry
# ---------------------------------------------------------------------------


def test_registry_reads_values_the_engine_never_used_to_load():
    """data/items/*.yaml carried a `value` that no runtime code had ever read."""
    assert inventory.value_of("loaf") == 2
    assert inventory.value_of("hide_roll") == 24
    assert inventory.name_of("wild_mushroom") == "Wild mushroom"


def test_registry_tolerates_an_id_it_has_never_heard_of():
    """Quests, boons and procgen all mint ids; a miss must not raise."""
    assert inventory.value_of("a_thing_that_does_not_exist") == 0
    assert inventory.name_of("a_thing_that_does_not_exist") == "a thing that does not exist"
    assert inventory.get_item("a_thing_that_does_not_exist") is None


def test_carried_tags_survive_the_registry_join():
    """A granted item's own tags are honoured on top of the registry row."""
    state = GameState()
    inventory.grant(state, "loaf", 2)
    rows = {r["id"]: r for r in inventory.describe(state)}
    assert rows["loaf"]["qty"] == 2
    assert rows["loaf"]["stack_value"] == 4
    assert "food" in rows["loaf"]["tags"]


# ---------------------------------------------------------------------------
# foraging
# ---------------------------------------------------------------------------


def test_forage_nodes_are_dealt_across_every_forageable_place():
    """
    procgen stamps every node with one hardcoded location. Honouring that would
    put the whole pool in forest_clearing, which both strands the rest of the
    map and defeats depletion.
    """
    state = new_game_state(seed=42)
    places = sorted(foraging._all_forageable_places())
    assert len(places) > 1

    dealt = {p: [n["id"] for n in foraging.nodes_at(state, p)] for p in places}
    flat = [node for ids in dealt.values() for node in ids]
    assert len(flat) == len(set(flat)), "a node was dealt to two places"
    assert sum(1 for ids in dealt.values() if ids) > 1, "every node landed in one place"


def test_forage_is_refused_where_the_tags_do_not_allow_it():
    state = new_game_state(seed=42, location_id="edgewood_square")
    assert not foraging.forageable("edgewood_square")
    outcome = foraging.forage(state)
    assert outcome["success"] is False
    assert "foraging" in outcome["message"].lower()


def test_forage_costs_hours_and_stamina_whether_or_not_it_finds_anything():
    """A failed forage that costs nothing is not a risk and not a decision."""
    state = new_game_state(seed=42)
    before_hours = state.world_clock_hours
    before_stamina = state.stats.stamina

    outcome = foraging.forage(state)

    assert state.world_clock_hours > before_hours
    assert state.stats.stamina < before_stamina
    assert outcome["hours"] > 0


def test_forage_actually_produces_food_a_broke_player_can_eat():
    """The whole point. Food, from nothing, repeatably."""
    state = new_game_state(seed=42)
    state.stats.gold = 0

    found_food = 0
    for _ in range(12):
        for row in foraging.forage(state).get("found", []):
            if inventory.has_tag(str(row["item_id"]), "food"):
                found_food += int(row["qty"])
        state.stats.stamina = 100  # isolate the food question from the rest loop

    assert found_food > 0, "twelve forages produced nothing edible"

    rules = survival.load_rules()
    edible = [
        i.id
        for i in state.inventory
        if survival.food_value(i.id, list(i.tags), rules) is not None
    ]
    assert edible, "foraged food is not recognised as food by the survival rules"

    state.hunger = 80.0
    result = survival.eat(state, edible[0])
    assert result["success"] is True
    assert state.hunger < 80.0


def test_a_worked_node_gives_less_and_recovers_when_left_alone():
    """
    Depletion, and the regrowth rule that keeps it from being a wall.

    The recovery half matters as much as the depletion half: a node that only
    ever gets worse rebuilds the starvation soft-lock one layer in.
    """
    state = new_game_state(seed=42)
    node_id = foraging.preview(state)["node_id"]

    fresh = foraging.depletion_multiplier(state, 0)
    for _ in range(6):
        foraging.forage(state)
        state.stats.stamina = 100
    worked = foraging.node_uses(state, node_id)
    assert worked > 0, "working the ground left no mark on it"
    assert foraging.depletion_multiplier(state, worked) < fresh

    # The clock's expiry sweep IS the regrowth rule.
    from engine.game.clock import advance_time

    recovery = int(foraging.load_rules()["forage"]["depletion"]["recovery_days"])
    advance_time(state, 24.0 * (recovery + 2))
    assert foraging.node_uses(state, node_id) == 0


def test_depletion_never_reaches_zero_yield():
    """
    A floored multiplier, not a wall.

    A node that eventually gives nothing at all is the same soft-lock this
    module exists to remove, moved one step further in.
    """
    state = new_game_state(seed=42)
    cfg = foraging.load_rules()["forage"]
    best_degree = max(cfg["picks"], key=lambda d: cfg["picks"][d])
    picks = int(cfg["picks"][best_degree])
    assert round(picks * foraging.depletion_multiplier(state, 50)) >= 1


def test_season_and_phase_are_itemised_rather_than_folded_in():
    """The receipt has to show the arithmetic, like every other check does."""
    state = new_game_state(seed=42)
    state.world_clock_hours = 24.0 * 100  # deep into a later season
    state.evil_progress = 0.7
    state.evil_phase = EvilPhase.SPREADING

    preview = foraging.preview(state)
    labels = {row["label"] for row in preview["modifiers"]}
    assert any("spreading" in label for label in labels)
    assert preview["season"] in foraging.load_rules()["forage"]["season"]["order"]


def test_forage_replays_identically_for_a_seed():
    """Determinism is the property that makes a balance number mean anything."""

    def run() -> list[tuple[str, int]]:
        state = new_game_state(seed=1234)
        out: list[tuple[str, int]] = []
        for _ in range(6):
            for row in foraging.forage(state).get("found", []):
                out.append((str(row["item_id"]), int(row["qty"])))
            state.stats.stamina = 100
        return out

    assert run() == run()


# ---------------------------------------------------------------------------
# labour
# ---------------------------------------------------------------------------


def test_a_shift_pays_coin_and_moves_standing():
    state = new_game_state(seed=42, location_id="edgewood_bakery")
    gold_before = state.stats.gold

    outcome = economy.work(state, "oven_shift")

    assert "check" in outcome, outcome
    assert state.stats.gold >= gold_before
    assert outcome["wage_breakdown"]["base_wage"] > 0


def test_the_daily_cap_is_what_stops_labour_being_an_infinite_gold_button():
    state = new_game_state(seed=42, location_id="edgewood_bakery")
    first = economy.work(state, "oven_shift")
    assert "check" in first

    second = economy.work(state, "oven_shift")
    assert "check" not in second
    assert second["success"] is False


def test_work_is_refused_at_the_wrong_counter():
    state = new_game_state(seed=42, location_id="forest_clearing")
    outcome = economy.work(state, "oven_shift")
    assert outcome["success"] is False
    assert "edgewood_bakery" in outcome["message"]


def test_nobody_hires_when_the_village_is_emptying():
    """
    The evil phase changes what your LIFE is, not only what the monsters are.

    A job whose demand falls to zero leaves the board entirely rather than
    offering a shift that pays nothing.
    """
    state = new_game_state(seed=42, location_id="edgewood_bakery")
    assert any(row["id"] == "oven_shift" for row in economy.available(state))

    state.evil_progress = 0.95
    state.evil_phase = EvilPhase.CONSUMING
    assert not any(row["id"] == "oven_shift" for row in economy.available(state))

    refusal = economy.work(state, "oven_shift")
    assert refusal["success"] is False
    assert "hiring" in refusal["message"].lower()


def test_a_job_the_end_of_the_world_creates_rather_than_destroys():
    """Not every livelihood dies with the village. Some only start then."""
    state = new_game_state(seed=42, location_id="refugee_camp")
    assert not economy.available(state)

    state.evil_progress = 0.7
    state.evil_phase = EvilPhase.SPREADING
    assert any(row["id"] == "refugee_camp_hands" for row in economy.available(state))


def test_standing_prices_the_work():
    """Reputation earns rent. This is the first thing in the game that pays it."""
    poor = new_game_state(seed=42, location_id="edgewood_bakery")
    rich = new_game_state(seed=42, location_id="edgewood_bakery")
    rich.reputations["edgewood"] = 90

    job = economy.get_job("oven_shift")
    assert economy.wage_multiplier(rich, job)["standing"] > economy.wage_multiplier(poor, job)["standing"]


def test_a_job_behind_a_standing_gate_is_absent_until_the_gate_opens():
    state = new_game_state(seed=42, location_id="tinker_caravan")
    state.reputations["tinkers"] = -80
    assert not any(row["id"] == "tinker_bench" for row in economy.available(state))

    state.reputations["tinkers"] = 10
    assert any(row["id"] == "tinker_bench" for row in economy.available(state))


# ---------------------------------------------------------------------------
# trade
# ---------------------------------------------------------------------------


def test_selling_works_for_an_item_with_no_buys_row():
    """
    THE BUG. The old path refused anything a vendor had no explicit `buys` row
    for, so a foraged mushroom, a granted hide and a dug-up shard were worth
    nothing to everybody in the world.
    """
    state = new_game_state(seed=42, location_id="tinker_caravan")
    inventory.grant(state, "hide_roll", 1)
    assert "hide_roll" not in trade.vendor("npc_ilya").get("buys", {})

    quote = trade.quote(state, "npc_ilya", "hide_roll", trade.SELL, 1)
    assert quote["ok"] is True
    assert quote["unit_price"] > 0

    gold_before = state.stats.gold
    sale = trade.sell(state, "npc_ilya", "hide_roll", 1)
    assert sale["success"] is True
    assert state.stats.gold > gold_before
    assert inventory.quantity(state, "hide_roll") == 0


def test_a_vendor_will_not_deal_in_what_they_do_not_deal_in():
    state = new_game_state(seed=42, location_id="edgewood_bakery")
    inventory.grant(state, "wooden_shield", 1)
    quote = trade.quote(state, "npc_maris", "wooden_shield", trade.SELL, 1)
    assert quote["ok"] is False


def test_quest_items_are_nobody_elses_business():
    state = new_game_state(seed=42, location_id="tinker_caravan")
    inventory.grant(state, "nessas_drawing", 1)
    assert trade.deals_in("npc_ilya", "nessas_drawing") is False


def test_the_spread_means_a_round_trip_loses_money():
    """Arbitrage is not supposed to be a living. Work and foraging are."""
    state = new_game_state(seed=42, location_id="tinker_caravan")
    buy = trade.quote(state, "npc_odran", "whetstone", trade.BUY, 1)
    sell = trade.quote(state, "npc_odran", "whetstone", trade.SELL, 1)
    assert sell["unit_price"] < buy["unit_price"]


def test_scarcity_moves_prices_with_the_evil_phase():
    """A player feels the doomsday clock in their purse before they see it."""
    calm = new_game_state(seed=42, location_id="edgewood_bakery")
    grim = new_game_state(seed=42, location_id="edgewood_bakery")
    grim.evil_progress = 0.95
    grim.evil_phase = EvilPhase.CONSUMING

    assert trade.scarcity_multiplier(grim, "loaf") > trade.scarcity_multiplier(calm, "loaf")
    assert (
        trade.quote(grim, "npc_maris", "loaf", trade.BUY, 1)["unit_price"]
        > trade.quote(calm, "npc_maris", "loaf", trade.BUY, 1)["unit_price"]
    )


def test_reputation_reads_opposite_ways_on_the_two_sides():
    """Being trusted must not make your sales worse."""
    stranger = new_game_state(seed=42, location_id="edgewood_bakery")
    friend = new_game_state(seed=42, location_id="edgewood_bakery")
    friend.reputations["edgewood"] = 90
    for state in (stranger, friend):
        inventory.grant(state, "honeycomb", 1)

    assert (
        trade.quote(friend, "npc_maris", "loaf", trade.BUY, 1)["unit_price"]
        <= trade.quote(stranger, "npc_maris", "loaf", trade.BUY, 1)["unit_price"]
    )
    assert (
        trade.quote(friend, "npc_maris", "honeycomb", trade.SELL, 1)["unit_price"]
        >= trade.quote(stranger, "npc_maris", "honeycomb", trade.SELL, 1)["unit_price"]
    )


def test_haggling_moves_the_price_and_is_capped_at_one_argument_a_day():
    state = new_game_state(seed=42, location_id="edgewood_bakery")
    before = trade.quote(state, "npc_maris", "loaf", trade.BUY, 1)["unit_price"]

    first = trade.haggle(state, "npc_maris", "loaf", trade.BUY, offer=1)
    assert "check" in first
    assert first["counter"] == trade.quote(state, "npc_maris", "loaf", trade.BUY, 1)["unit_price"]
    assert first["points_moved"] != 0 or first["counter"] == before

    second = trade.haggle(state, "npc_maris", "loaf", trade.BUY, offer=1)
    assert "check" not in second
    assert "today" in second["message"]


def test_a_bargain_lasts_a_day_and_no_longer():
    """The clock's expiry sweep is the rule. No session object, no new field."""
    from engine.game.clock import advance_time

    state = new_game_state(seed=42, location_id="edgewood_bakery")
    trade.haggle(state, "npc_maris", "loaf", trade.BUY, offer=1)
    advance_time(state, 48.0)
    assert trade.haggle_points(state, "npc_maris") == 0
    assert trade.haggle_attempts(state, "npc_maris") == 0


def test_a_greedier_offer_is_a_harder_check():
    state = new_game_state(seed=42, location_id="tinker_caravan")
    quote = trade.quote(state, "npc_odran", "hobnail_boots", trade.BUY, 1)["unit_price"]

    modest = trade.haggle(state, "npc_odran", "hobnail_boots", trade.BUY, offer=int(quote * 0.97))
    fresh = new_game_state(seed=42, location_id="tinker_caravan")
    greedy = trade.haggle(fresh, "npc_odran", "hobnail_boots", trade.BUY, offer=int(quote * 0.5))

    bands = ["trivial", "easy", "standard", "hard", "severe", "legendary"]
    assert bands.index(greedy["difficulty"]) > bands.index(modest["difficulty"])


def test_buying_is_refused_rather_than_going_into_debt():
    state = new_game_state(seed=42, location_id="edgewood_bakery")
    state.stats.gold = 0
    outcome = trade.buy(state, "npc_maris", "winter_ration", 1)
    assert outcome["success"] is False
    assert state.stats.gold == 0


def test_the_legacy_trade_tool_still_answers_the_old_signature():
    """
    scripts/simulate.py, the vertical slice and any narration that already
    learned this tool must keep working after the rewrite.
    """
    import json

    from engine.game.engine import GameEngine, active_engine
    from engine.skills.builtin.mechanics import trade as trade_skill

    state = new_game_state(seed=42, location_id="edgewood_bakery")
    state.stats.gold = 20
    with active_engine(GameEngine(state)):
        payload = json.loads(
            trade_skill(action="buy", item_id="loaf", npc_id="npc_maris")
        )
    assert payload["success"] is True
    assert inventory.quantity(state, "loaf") >= 1


# ---------------------------------------------------------------------------
# the skill surface
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "forage",
        "query_forage",
        "work",
        "query_work",
        "trade_browse",
        "trade_quote",
        "trade_haggle",
        "trade_buy",
        "trade_sell",
        "query_inventory",
    ],
)
def test_every_livelihood_tool_is_registered_for_the_storyteller(name: str):
    from engine.skills.registry import AGENT_ASSISTANT, AGENT_STORYTELLER, SKILL_REGISTRY

    definition = SKILL_REGISTRY.get(name)
    assert definition is not None, f"{name} is not registered"
    assert definition.callable_by(AGENT_STORYTELLER)
    # The Assistant narrates and hints; it does not move gold or food.
    assert not definition.callable_by(AGENT_ASSISTANT)


def test_the_tools_return_json_not_prose():
    """Engine resolves mechanics, LLMs narrate. Every receipt is structured."""
    import json

    from engine.game.engine import GameEngine, active_engine
    from engine.skills.registry import SKILL_REGISTRY

    state = new_game_state(seed=42)
    with active_engine(GameEngine(state)):
        for name in ("query_forage", "query_work", "query_inventory"):
            payload = json.loads(SKILL_REGISTRY.invoke(name))
            assert isinstance(payload, dict), name
