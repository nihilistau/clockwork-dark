"""
"For N days" lasts N days.

Every timed mechanic ran one day long. ``resolve_day(default_days=N)`` returns
``world_day + N``, and ``clock._sweep_expiries`` keeps an effect while
``expires_day >= world_day`` -- so ``{days: 1}`` applied on day 5 stamped 6 and
was in force on day 5 AND day 6.

The comparator was deliberately not the thing that changed.
``economy._record_shift`` stamps ``expires_day = world_day`` to mean "today
only", and flipping the sweep to ``<=`` would evict the daily shift markers on
the first intra-day ``advance_time``, resetting the work cap several times a
day. So durations convert through ``effects.duration_day`` instead, and the
sweep keeps its two distinct invariants:

    expires_day   the last day still in force  -> dropped when it is PAST
    heals_on_day  the day it heals             -> dropped when it ARRIVES

Wounds were the second one read as the first, which kept a three-day wound for
four.
"""

from __future__ import annotations

import pytest

from engine.game import effects as effects_module
from engine.game.clock import advance_time
from engine.game.state import GameState


def _fresh(day: int = 5) -> GameState:
    """
    A state parked at 06:00 on ``day``, with the survival systems quiet.

    Fed and rested on the way, because ``advance_time`` runs the whole world:
    an unattended state walked forward five days starves, and the starvation
    rules apply WOUNDS of their own. The first version of this file was reading
    those instead of the ones under test.
    """
    state = GameState(location_id="forest_clearing")
    # advance_time is the only writer of world time; get there through it.
    while state.world_day < day or state.world_hour != 6:
        advance_time(state, 1)
        state.hunger = 0.0
        state.stats.hp = state.stats.max_hp
        state.wounds.clear()
    return state


def _skip_to_day(state: GameState, day: int) -> None:
    """Walk to ``day``, keeping the survival systems out of the way."""
    guard = 0
    while state.world_day < day:
        advance_time(state, 6)
        state.hunger = 0.0
        state.stats.hp = state.stats.max_hp
        guard += 1
        assert guard < 400, "clock did not advance"


@pytest.mark.parametrize("days", [1, 2, 3])
def test_a_check_penalty_lasts_exactly_the_days_it_declares(days: int) -> None:
    state = _fresh()
    start = state.world_day
    effects_module.apply_effect(
        state,
        {"type": "check_penalty", "days": days, "delta": -2, "text": "sodden"},
    )

    for offset in range(days):
        _skip_to_day(state, start + offset)
        assert any(e.kind == "check_penalty" for e in state.active_effects), (
            f"a {days}-day penalty was already gone on day {offset + 1} of {days}"
        )

    _skip_to_day(state, start + days)
    assert not [e for e in state.active_effects if e.kind == "check_penalty"], (
        f"a {days}-day penalty outlasted its own duration"
    )


def test_an_absolute_expiry_written_by_content_is_still_a_date() -> None:
    """
    ``duration_day`` converts DURATIONS. An authored ``expires_day`` is a date
    and must pass through untouched.
    """
    state = _fresh()
    target = state.world_day + 4
    effects_module.apply_effect(
        state,
        {
            "type": "check_penalty",
            "expires_day": target,
            "delta": -1,
            "text": "pinned",
        },
    )
    effect = next(e for e in state.active_effects if e.kind == "check_penalty")
    assert effect.expires_day == target


@pytest.mark.parametrize("days", [1, 3, 5])
def test_a_wound_heals_on_the_day_it_says(days: int) -> None:
    state = _fresh()
    start = state.world_day
    effects_module.apply_effect(
        state,
        {
            "type": "wound",
            "text": "turned ankle",
            "severity": 2,
            "heals_on_day": f"+{days}",
        },
    )
    # Tracked by id, not by "are there any wounds": the survival rules apply
    # wounds of their own as the days pass, and this is about THIS one.
    mine = next(w.id for w in state.wounds if w.text == "turned ankle")

    def _open() -> bool:
        return any(w.id == mine for w in state.wounds)

    _skip_to_day(state, start + days - 1)
    assert _open(), f"a wound healing on +{days} was gone a day early"

    _skip_to_day(state, start + days)
    assert not _open(), f"a wound healing on +{days} was still open that day"


def test_a_shift_marker_survives_its_own_day() -> None:
    """
    The invariant the sweep comparator protects.

    ``_record_shift`` stamps ``expires_day = world_day`` for "today only", and
    ``advance_time`` runs several times within a day. If the sweep dropped an
    effect on the day it expires, the daily work cap would reset every few
    hours.
    """
    from engine.game.economy import _record_shift, shifts_worked

    state = _fresh()  # parked at 06:00
    day = state.world_day
    _record_shift(state, "oven_shift")
    assert shifts_worked(state) == 1

    advance_time(state, 6)  # 12:00, same day
    assert state.world_day == day, "this test needs to stay inside one day"
    assert shifts_worked(state) == 1, (
        "the shift marker was swept within its own day -- the daily cap resets "
        "every time the clock ticks"
    )


def test_duration_day_is_inclusive_of_today() -> None:
    state = _fresh()
    assert effects_module.duration_day(state, 1) == state.world_day
    assert effects_module.duration_day(state, 2) == state.world_day + 1
    # Nonsense input cannot reach into yesterday.
    assert effects_module.duration_day(state, 0) == state.world_day
    assert effects_module.duration_day(state, -4) == state.world_day
