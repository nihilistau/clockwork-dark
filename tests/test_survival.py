"""
Survival tests.

The headline is ``test_no_stamina_softlock``. Everything else exists to keep the
pieces that fix it honest: hunger has to accrue, rest has to be the only thing
that gives stamina back, and rest has to remain legal in every state the player
can reach -- because the moment resting can be refused, the soft-lock is back.
"""

from __future__ import annotations

import pytest

from engine.game import inventory, survival
from engine.game.clock import advance_time, set_clock
from engine.game.engine import GameEngine
from engine.game.state import GameState, InventoryItem


def fed_state(**kwargs) -> GameState:
    state = GameState(rng_seed=4242, **kwargs)
    state.stats.stamina = state.stats.max_stamina
    state.hunger = 0.0
    return state


# -- hunger --------------------------------------------------------------


def test_tick_accrues_hunger_per_hour():
    state = fed_state()
    survival.tick(state, 5)
    assert state.hunger == pytest.approx(10.0)


def test_tick_is_wired_into_the_clock():
    # clock.advance_time imports this module and calls tick; nothing else has
    # to remember to, which is the point.
    state = fed_state()
    advance_time(state, 6)
    assert state.hunger == pytest.approx(12.0)


def test_hunger_is_capped_at_100():
    # hp is raised so starvation damage cannot trigger death mid-test;
    # a respawn would reset the hunger this test exists to measure.
    state = fed_state()
    state.stats.max_hp = state.stats.hp = 9999
    advance_time(state, 200)
    assert state.hunger == 100.0


def test_zero_hours_is_a_no_op():
    state = fed_state()
    state.hunger = 33.0
    out = survival.tick(state, 0)
    assert state.hunger == 33.0
    assert out["hours"] == 0.0


@pytest.mark.parametrize(
    "hunger,stage",
    [(0.0, "fed"), (39.9, "fed"), (40.0, "peckish"), (60.0, "hungry"), (85.0, "starving")],
)
def test_hunger_stages(hunger, stage):
    state = fed_state()
    state.hunger = hunger
    assert survival.hunger_stage(state) == stage


def test_hungry_caps_stamina_below_max():
    state = fed_state()
    assert survival.stamina_cap(state) == 100

    state.hunger = 65.0
    assert survival.stamina_cap(state) == 80

    # The cap is enforced, not merely advertised.
    state.stats.stamina = 100
    out = survival.tick(state, 1)
    assert state.stats.stamina == 80
    assert out["stamina_clamped"] == 20


def test_starving_costs_hp_per_hour():
    """
    Starvation damage tracks the configured rate, whatever it is.

    The assertion used to be a hardcoded ``- 4``, which pinned the test to
    ``starving_hp_per_hour: 1.0`` and made a balance change look like a
    regression. The invariant worth defending is that the rate in
    games/clockwork-dark/data/rules/survival.yaml is the rate the engine charges -- not what that
    number happens to be this week.
    """
    rate = float(survival.load_rules()["hunger"]["starving_hp_per_hour"])
    assert rate > 0, "starvation that costs nothing is not starvation"

    state = fed_state()
    state.hunger = 90.0
    hp_before = state.stats.hp
    survival.tick(state, 4)
    assert state.stats.hp == hp_before - round(rate * 4)


def test_not_starving_costs_no_hp():
    state = fed_state()
    state.hunger = 70.0
    hp_before = state.stats.hp
    survival.tick(state, 4)
    assert state.stats.hp == hp_before


def test_awake_stamina_regen_is_zero_by_design():
    # If this ever passes with a positive number, rest has stopped being a
    # choice and the hours it costs have stopped mattering.
    state = fed_state()
    state.stats.stamina = 40
    advance_time(state, 12)
    assert state.stats.stamina == 40


# -- rest ----------------------------------------------------------------


def test_rest_short_restores_stamina_and_spends_hours():
    state = fed_state(location_id="edgewood_square")
    state.stats.stamina = 30
    set_clock(state, day=1, hour=9)

    out = survival.rest(state, "rest_short")

    assert out["success"] is True
    assert out["kind"] == "rest_short"
    assert state.stats.stamina == 45
    assert state.world_hour == 11
    assert state.hunger == pytest.approx(4.0)


def test_sleep_in_a_bed_fills_the_tank():
    state = fed_state(location_id="edgewood_bakery")
    state.stats.stamina = 5
    state.stats.hp = 10

    out = survival.rest(state, "sleep_bed")

    assert out["kind"] == "sleep_bed"
    assert state.stats.stamina == survival.stamina_cap(state)
    assert state.stats.hp == 12
    assert out["hours"] == 8.0


def test_sleeping_in_a_bed_where_there_is_none_downgrades_rather_than_refuses():
    state = fed_state(location_id="forest_clearing")
    state.stats.stamina = 10

    out = survival.rest(state, "sleep_bed")

    assert out["success"] is True
    assert out["kind"] == "sleep_rough"
    assert out["requested_kind"] == "sleep_bed"
    assert state.stats.stamina > 10


def test_sleep_rough_rolls_a_survival_check():
    state = fed_state(location_id="forest_clearing")
    state.stats.stamina = 0
    out = survival.rest(state, "sleep_rough")
    assert out["check"] is not None
    assert out["check"]["skill"] == "survival"
    assert "summary" in out["check"]


def test_sleep_rough_failure_costs_hp_and_gives_less():
    # Wits 3 makes the standard survival check unreachable, so this always fails.
    state = fed_state(location_id="forest_clearing")
    state.stats.wits = 3
    state.stats.stamina = 0
    state.stats.hp = 20

    out = survival.rest(state, "sleep_rough")

    assert out["failed_check"] is True
    assert state.stats.stamina == 25
    assert state.stats.hp == 18


def test_sleep_rough_success_gives_more():
    state = fed_state(location_id="forest_clearing")
    state.stats.wits = 18
    state.stats.stamina = 0
    state.stats.hp = 20

    out = survival.rest(state, "sleep_rough")
    if not out["failed_check"]:
        assert state.stats.stamina == 55
        assert state.stats.hp == 20


def test_rest_never_exceeds_the_hunger_cap():
    state = fed_state(location_id="edgewood_square")
    state.hunger = 70.0
    state.stats.stamina = 10
    survival.rest(state, "sleep_bed")
    assert state.stats.stamina == survival.stamina_cap(state) == 80


def test_unknown_rest_kind_falls_back_instead_of_failing():
    state = fed_state()
    state.stats.stamina = 20
    out = survival.rest(state, "nap_in_a_hedge")
    assert out["success"] is True
    assert state.stats.stamina > 20


def test_rest_advances_the_evil_clock():
    state = fed_state(location_id="edgewood_square")
    state.stats.stamina = 10
    before = state.evil_progress
    survival.rest(state, "sleep_bed")
    assert state.evil_progress > before


def test_all_configured_rest_kinds_are_usable():
    for kind in survival.rest_kinds():
        state = fed_state(location_id="edgewood_square")
        state.stats.stamina = 0
        assert survival.rest(state, kind)["success"] is True


# -- eating --------------------------------------------------------------


def test_eat_reduces_hunger_and_consumes_the_item():
    state = fed_state()
    state.hunger = 80.0
    state.inventory.append(InventoryItem(id="loaf", name="Loaf of bread", qty=2))

    out = survival.eat(state, "loaf")

    assert out["success"] is True
    assert state.hunger == pytest.approx(45.5)  # 80 + 0.5 (0.25h tick) - 35
    assert state.inventory[0].qty == 1


def test_eat_the_last_one_empties_the_stack():
    state = fed_state()
    state.inventory.append(InventoryItem(id="loaf", name="Loaf", qty=1))
    survival.eat(state, "loaf")
    assert state.inventory == []


def test_eat_what_you_do_not_have_fails_softly():
    state = fed_state()
    out = survival.eat(state, "loaf")
    assert out["success"] is False
    assert "none" in out["message"].lower()


def test_eat_something_inedible_fails_softly():
    state = fed_state()
    state.inventory.append(InventoryItem(id="whetstone", name="Whetstone", qty=1))
    out = survival.eat(state, "whetstone")
    assert out["success"] is False
    assert state.inventory[0].qty == 1


def test_tagged_food_is_edible_without_a_table_entry():
    state = fed_state()
    state.hunger = 50.0
    state.inventory.append(
        InventoryItem(id="strange_root", name="Strange root", qty=1, tags=["forage"])
    )
    out = survival.eat(state, "strange_root")
    assert out["success"] is True
    assert state.hunger < 50.0


def test_eating_lifts_the_stamina_cap_again():
    state = fed_state()
    state.hunger = 70.0
    state.inventory.append(InventoryItem(id="loaf", name="Loaf", qty=1))
    assert survival.stamina_cap(state) == 80
    survival.eat(state, "loaf")
    assert survival.stamina_cap(state) == 100


# -- the bug ------------------------------------------------------------


def test_travel_alone_drains_stamina_to_zero():
    """
    The pre-fix failure mode, pinned so it cannot come back silently.

    Travel spends stamina and nothing else in the game gives it back. Five round
    trips to millhaven_gate (40 stamina each) is all it took.
    """
    state = fed_state(location_id="edgewood_square")
    engine = GameEngine(state)

    legs = 0
    while True:
        destination = (
            "millhaven_gate" if state.location_id == "edgewood_square" else "edgewood_square"
        )
        if not engine.move_to(destination).success:
            break
        legs += 1
        assert legs < 20, "travel should have exhausted stamina long before this"

    assert legs == 5  # 100 stamina / 20 per leg
    assert state.stats.stamina == 0


def test_rest_is_the_way_out_of_zero_stamina():
    state = fed_state(location_id="edgewood_square")
    state.stats.stamina = 0
    engine = GameEngine(state)
    assert engine.move_to("millhaven_gate").success is False

    survival.rest(state, "sleep_bed")

    assert state.stats.stamina > 20
    assert engine.move_to("millhaven_gate").success is True


def test_no_stamina_softlock():
    """
    Forty travel legs with rest and food available: never stuck, never dead.

    "Stuck" is the precise failure being ruled out -- stamina at zero with no
    action in the game capable of raising it. The loop asserts, on every leg,
    that a legal recovery action exists and that taking it actually helps.
    """
    state = fed_state(location_id="edgewood_square")
    state.inventory.append(
        InventoryItem(id="loaf", name="Loaf of bread", qty=60, tags=["food"])
    )
    engine = GameEngine(state)

    legs_completed = 0
    for _ in range(40):
        destination = (
            "millhaven_gate" if state.location_id == "edgewood_square" else "edgewood_square"
        )
        # 60 loaves is 36 kg -- over the carry limit, so travel is priced at
        # the overload multiplier until enough of the bread has been eaten.
        # Recomputed per leg because the pack lightens as the loop eats.
        cost = max(1, int(4 * 5 * inventory.travel_stamina_multiplier(state)))

        recoveries = 0
        while state.stats.stamina < cost:
            # Eat before the hunger cap can make the trip unaffordable.
            if state.hunger >= 50.0:
                assert survival.eat(state, "loaf")["success"] is True

            before = state.stats.stamina
            outcome = survival.rest(state, "rest_short")

            assert outcome["success"] is True, "rest must never be refused"
            assert state.stats.stamina > before, (
                f"rest gave nothing back at stamina={before}, hunger={state.hunger:.0f}"
            )
            assert survival.stamina_cap(state) >= cost, (
                "hunger cap must never make travel unaffordable while food is available"
            )

            recoveries += 1
            assert recoveries < 20, "recovery is not converging"

        result = engine.move_to(destination)
        assert result.success is True, result.message
        legs_completed += 1

        assert state.stats.hp > 0, "starved to death with food in the pack"
        assert state.stats.stamina >= 0

    assert legs_completed == 40
    assert state.world_day > 1  # the evil clock ran the whole time


def test_sleeping_the_night_also_clears_the_softlock():
    """The same guarantee via the 8h path, which is where a real player lands."""
    state = fed_state(location_id="edgewood_square")
    state.inventory.append(InventoryItem(id="loaf", name="Loaf", qty=40, tags=["food"]))
    engine = GameEngine(state)

    for _ in range(20):
        destination = (
            "millhaven_gate" if state.location_id == "edgewood_square" else "edgewood_square"
        )
        while state.hunger >= 50.0:
            assert survival.eat(state, "loaf")["success"] is True
        if state.stats.stamina < 20:
            survival.rest(state, "sleep_bed")
        assert state.stats.stamina >= 20
        assert engine.move_to(destination).success is True

    assert state.stats.hp > 0


def test_snapshot_reports_what_the_ui_needs():
    state = fed_state()
    state.hunger = 65.0
    snap = survival.snapshot(state)
    assert snap["stage"] == "hungry"
    assert snap["stamina_cap"] == 80
    assert set(snap) >= {"hunger", "stage", "stamina", "stamina_cap", "hp", "wounds"}
