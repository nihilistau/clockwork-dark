"""
Shared setups for The Clockwork Dark's doors and deaths (v0.25.0).

WHY THIS MODULE EXISTS. The stored ``state.evil_phase`` does NOT follow
``state.evil_progress`` by itself: it is re-synced only when the state is
built (``GameState.__post_init__``) or when the doom ticker advances
(``EvilTicker.advance``, inside ``clock.advance_time``), and the doom beats
fire only from ``advance_time`` too (``world_effects.apply_pending_beats``).
A test that writes ``state.evil_progress = 0.85`` alone therefore leaves a
``dormant`` phase and no beat flags behind it -- a state that disagrees with
itself, so a door or a death keyed on the phase reads the wrong world.

``at_reading`` sets the reading the way the engine would have reached it:
the progress, the stored phase synced by the engine's own
``phase_from_progress``, and every doom beat the reading has crossed fired
through ``world_effects.apply_pending_beats`` (the engine's own path, never
flags written by hand). Every setup that sets the reading uses it (T3, and
T6, T7 and T9 extend this module).

THE DOOR SETUPS (v0.25.0 §4.2, §12.1, T6 on), shared by
tests/test_clockwork_dark.py (each door as it lands, T6-T8) and
tests/test_finales.py (the registered rows, T9). A setup puts the run where a
door opens. It writes state as play would -- ``apply_effect`` for flags,
items, standings and stats; ``advance_time`` for time, fed on the way;
``state.location_id`` only to stand somewhere -- with one exception (plan
decision 18): a quest the door needs completed, or at a stage, is written
through the quest module's own record writer, ``quests._write``.

Version: v0.4.0 [2026-10-29]
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "OFFERED", "PAID", "at_pay_it_by_the_narrator", "at_reading", "at_stage", "completed", "effect",
    "fed_until", "flag", "hearth_door", "last_hour_door", "march_door", "named_wound_door", "pin_door",
    "price_door_for", "second_death_door", "stand", "stay_anyway_door", "witness_door",
    # unearned (T9)
    "hearth_consumed", "hearth_knowing", "hearth_larder_unwalked", "hearth_unplaced", "march_marked",
    "march_unmarched", "march_unserved", "march_uncounted", "named_too_late", "named_unbaked",
    "named_undecided", "named_unnamed", "pin_spent", "pin_too_late", "pin_untaken", "pin_unwalked",
    "price_nothing_offered", "price_nothing_open", "wheel_still_turning", "witness_blind", "witness_deaf",
    "witness_early", "witness_too_late", "witness_uncounted",
]


def at_reading(state: Any, progress: float) -> Any:
    """
    Stand ``state`` at doom reading ``progress``, phase and beats in step.

    Args:
        state: A mutable GameState of the active story.
        progress: The reading, 0..1.

    Returns:
        The same state, for chaining.
    """
    from engine.game.evil_ticker import phase_from_progress
    from engine.world import world_effects

    state.evil_progress = float(progress)
    state.evil_phase = phase_from_progress(state.evil_progress)
    world_effects.apply_pending_beats(state)
    return state


def effect(state: Any, **row: Any) -> dict:
    """One effect row through ``effects.apply_effect``, the only writer of game state."""
    from engine.game.effects import apply_effect

    return apply_effect(state, dict(row))


def flag(state: Any, name: str) -> None:
    effect(state, type="flag", flag=name, value=True)


def fed_until(state: Any, day: int, hour: int) -> None:
    """The clock walked to ``day``/``hour`` through ``advance_time``, fed and healed before each step."""
    from engine.game.clock import advance_time

    target = float((day - 1) * 24 + hour)
    while state.world_clock_hours < target:
        if state.hunger > 0:
            effect(state, type="hunger", delta=-state.hunger)
        if state.stats.hp < state.stats.max_hp:
            effect(state, type="hp", delta=state.stats.max_hp - state.stats.hp)
        advance_time(state, min(6.0, target - state.world_clock_hours))


def stand(state: Any, place: str, hour: int) -> None:
    """Stand at ``place`` at the next ``hour`` (today's, if it is still ahead)."""
    day = state.world_day if state.world_hour < hour else state.world_day + 1
    fed_until(state, day, hour)
    state.location_id = place


def _record(state: Any, quest_id: str, index: int, status: str) -> None:
    from engine.game.quests import QuestProgress, _write

    _write(state, QuestProgress(quest_id=quest_id, stage_index=index, status=status,
                                started_day=state.world_day, stage_started_day=state.world_day))


def completed(state: Any, quest_id: str) -> None:
    """``quest_id`` completed (plan decision 18)."""
    _record(state, quest_id, 99, "completed")


def at_stage(state: Any, quest_id: str, index: int) -> None:
    """``quest_id`` active at stage ``index`` (plan decision 18)."""
    _record(state, quest_id, index, "active")


# -- the morning firing (H1, Q1) ---------------------------------------------------------------------

def hearth_door(state: Any) -> None:
    """The Hearth Holds: a place here, the larder walked (H0's flag), awareness low; the bakery at five."""
    completed(state, "bakery_apprentice")
    at_stage(state, "banking_the_fire", 1)
    flag(state, "nf_hearth_taking_stock")
    stand(state, "edgewood_bakery", 5)


def stay_anyway_door(state: Any) -> None:
    """The fail-forward's morning door: the larder walked, but nobody here would miss you yet."""
    at_stage(state, "banking_the_fire", 1)
    flag(state, "nf_hearth_taking_stock")
    stand(state, "edgewood_bakery", 5)


def named_wound_door(state: Any) -> None:
    """The Named Wound: named, decided, and at the last quiet morning's third stage; the bakery at five."""
    completed(state, "naming_the_wound")
    completed(state, "what_edgewood_keeps")
    at_stage(state, "the_last_quiet_thing", 2)
    stand(state, "edgewood_bakery", 5)


# -- the count kept (W1) -----------------------------------------------------------------------------

def witness_door(state: Any) -> None:
    """The Long Witness: eyes open and listened (awareness 50), counted by the saints, three counts
    stayed; the shrine at six in the evening, Wenna lighting her candles."""
    effect(state, type="awareness", delta=50)
    effect(state, type="reputation", faction="unnamed_saints", delta=30)
    fed_until(state, 27, 12)
    stand(state, "edgewood_shrine", 18)


# -- the muster roll (M1) ----------------------------------------------------------------------------

def march_door(state: Any) -> None:
    """The Counted March: the gate visited (the arc), militia at 20, the press seen through; the gate at nine."""
    from engine.game.quests import QuestEngine

    effect(state, type="reputation", faction="militia", delta=20)
    completed(state, "militia_press")
    stand(state, "millhaven_gate", 9)
    QuestEngine.evaluate(state)          # records the visit and opens the march arc, as a turn does


# -- the price (S1, S2) ------------------------------------------------------------------------------

OFFERED = {"the_written_name": "offer_the_name", "ninth_pin": "offer_the_pin", "brass_shard": "offer_the_shard"}
PAID = {"the_written_name": "pay_the_name", "ninth_pin": "pay_the_pin", "brass_shard": "pay_the_shard"}


def _with_ilya_in_the_square(state: Any) -> None:
    """Spreading (the vines have moved Ilya to the square), naming done; the square at ten."""
    at_reading(state, 0.55)                 # a world this far gone; its beats fired as the clock fires them
    effect(state, type="awareness", delta=60)
    completed(state, "naming_the_wound")
    stand(state, "edgewood_square", 10)


def price_door_for(item_id: str):
    """The Price Asked, paying with `item_id`: offered at S1 (its flag and nf_sacrifice_chosen), held, at pay_it."""
    def setup(state: Any) -> None:
        _with_ilya_in_the_square(state)
        effect(state, type="item", item_id=item_id, qty=1)
        at_stage(state, "the_sacrifice", 2)
        flag(state, "nf_sacrifice_understood")
        flag(state, "nf_sacrifice_chosen")
        flag(state, f"sacrifice_offered_{item_id}")
    setup.__name__ = f"price_door_paying_{item_id}"
    return setup


def at_pay_it_by_the_narrator(state: Any) -> None:
    """A v0.24.0-shaped run at pay_it: chosen through the narrator, nothing offered on a card, two things held."""
    _with_ilya_in_the_square(state)
    effect(state, type="item", item_id="the_written_name", qty=1)
    effect(state, type="item", item_id="brass_shard", qty=1)
    at_stage(state, "the_sacrifice", 2)
    flag(state, "nf_sacrifice_understood")
    flag(state, "nf_sacrifice_chosen")


# -- the join (J1) -----------------------------------------------------------------------------------

def pin_door(state: Any) -> None:
    """The Pin and the Join: the pin taken and held, the join walked; standing at the join."""
    completed(state, "naming_the_wound")
    flag(state, "nf_ninth_taken")
    effect(state, type="item", item_id="ninth_pin", name="The ninth pin", qty=1, tags=["named", "unsettling"])
    at_stage(state, "the_heartland_road", 2)
    stand(state, "the_join", 12)


# -- the last hour (Z1) and the second death ----------------------------------------------------------

def last_hour_door(state: Any) -> None:
    """The Stopped Wheel: the reading at 1.0, then a day crossed, which fires `the_last_hour`
    (a `when:` event: fire-once and deterministic, no draw)."""
    at_reading(state, 1.0)
    fed_until(state, state.world_day + 1, 6)


def second_death_door(state: Any) -> None:
    """The fail-forward's terminal: consuming, and marked by a first death there already."""
    from engine.game import encounter

    at_reading(state, 0.85)
    effect(state, type="hp", delta=-int(state.stats.hp))
    first = encounter.check_death(state)
    assert first and not first.get("terminal"), first


# -- unearned (v0.25.0 §12.1): each walks a real door with ONE clause unmet --------------------------
#
# A doom reading is set through `at_reading` (ruling B1), never a bare `state.evil_progress`.

def hearth_unplaced(state: Any) -> None:            # a_place_here: no quiet-life quest done
    stay_anyway_door(state)


def hearth_larder_unwalked(state: Any) -> None:     # larder_kept: H0 never answered
    completed(state, "bakery_apprentice")
    at_stage(state, "banking_the_fire", 1)
    stand(state, "edgewood_bakery", 5)


def hearth_knowing(state: Any) -> None:              # unknowing: awareness past 40
    hearth_door(state)
    effect(state, type="awareness", delta=41)


def hearth_consumed(state: Any) -> None:             # village_stands: the world consuming
    hearth_door(state)
    at_reading(state, 0.85)


def _witness_but(state: Any, *, awareness: int = 50, saints: int = 30, day: int = 27,
                 drawing: bool = False, doom: float = 0.0) -> None:
    effect(state, type="awareness", delta=awareness)
    effect(state, type="reputation", faction="unnamed_saints", delta=saints)
    if drawing:
        completed(state, "childs_drawing")
    fed_until(state, day, 12)
    stand(state, "edgewood_shrine", 18)
    if doom:
        at_reading(state, doom)


def witness_blind(state: Any) -> None:               # eyes_open: awareness 20 (listened by the drawing)
    _witness_but(state, awareness=20, drawing=True)


def witness_deaf(state: Any) -> None:                # listened: awareness 40, no whisper quest
    _witness_but(state, awareness=40)


def witness_uncounted(state: Any) -> None:           # counted
    _witness_but(state, saints=0)


def witness_early(state: Any) -> None:               # stayed_three_counts: day 20
    _witness_but(state, day=20)


def witness_too_late(state: Any) -> None:            # world_still_turning
    _witness_but(state, doom=1.0)


def _march_but(state: Any, *, arc: bool = True, militia: int = 20, served: bool = True,
               marked: bool = False) -> None:
    from engine.game.quests import QuestEngine

    effect(state, type="reputation", faction="militia", delta=militia)
    if served:
        completed(state, "militia_press")
    if marked:
        flag(state, "saints_marked_you")
    if arc:
        stand(state, "millhaven_gate", 9)
        QuestEngine.evaluate(state)
    else:
        stand(state, "edgewood_square", 18)          # Sera's notice-board hours; the gate never visited


def march_unmarched(state: Any) -> None:
    _march_but(state, arc=False)


def march_uncounted(state: Any) -> None:
    _march_but(state, militia=10)


def march_unserved(state: Any) -> None:
    _march_but(state, served=False)


def march_marked(state: Any) -> None:
    _march_but(state, marked=True)


def _named_but(state: Any, *, named: bool = True, decided: bool = True, stage: int = 2, doom: float = 0.0) -> None:
    if named:
        completed(state, "naming_the_wound")
    if decided:
        completed(state, "what_edgewood_keeps")
    at_stage(state, "the_last_quiet_thing", stage)
    stand(state, "edgewood_bakery", 5)
    if doom:
        at_reading(state, doom)


def named_unnamed(state: Any) -> None:
    _named_but(state, named=False)


def named_undecided(state: Any) -> None:
    _named_but(state, decided=False)


def named_unbaked(state: Any) -> None:
    _named_but(state, stage=1)


def named_too_late(state: Any) -> None:
    _named_but(state, doom=1.0)


def price_nothing_open(state: Any) -> None:          # named, chose, paid: no sacrifice, nothing named
    _with_ilya_in_the_square(state)
    from engine.game.quests import progress_records

    state.quests.pop("naming_the_wound", None)
    assert "naming_the_wound" not in progress_records(state)


def price_nothing_offered(state: Any) -> None:       # chose, paid: at choose_what, the name held, not offered
    _with_ilya_in_the_square(state)
    effect(state, type="item", item_id="the_written_name", qty=1)
    at_stage(state, "the_sacrifice", 1)
    flag(state, "nf_sacrifice_understood")


def _pin_but(state: Any, *, taken: bool = True, held: bool = True, stage: int = 2, doom: float = 0.0) -> None:
    completed(state, "naming_the_wound")
    if taken:
        flag(state, "nf_ninth_taken")
    if held:
        effect(state, type="item", item_id="ninth_pin", name="The ninth pin", qty=1, tags=["named", "unsettling"])
    at_stage(state, "the_heartland_road", stage)
    stand(state, "the_join", 12)
    if doom:
        at_reading(state, doom)


def pin_untaken(state: Any) -> None:
    _pin_but(state, taken=False)


def pin_spent(state: Any) -> None:
    _pin_but(state, held=False)


def pin_unwalked(state: Any) -> None:                # join_walked: R2 is dealt, J1 is not
    _pin_but(state, stage=1)


def pin_too_late(state: Any) -> None:
    _pin_but(state, doom=1.0)


def wheel_still_turning(state: Any) -> None:         # wheel_stopped: 0.9, no last hour
    at_reading(state, 0.9)
