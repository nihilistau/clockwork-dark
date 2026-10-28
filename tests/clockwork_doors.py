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

Version: v0.3.0 [2026-10-29]
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "OFFERED", "PAID", "at_pay_it_by_the_narrator", "at_reading", "at_stage", "completed", "effect",
    "fed_until", "flag", "hearth_door", "last_hour_door", "march_door", "named_wound_door", "pin_door",
    "price_door_for", "second_death_door", "stand", "stay_anyway_door", "witness_door",
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
