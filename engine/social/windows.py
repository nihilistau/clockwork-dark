"""
Named windows resolved against a schedule (v0.23.0 spec §4.7, §5.1).

A window is resolved against ONE schedule: a person's (`population.profile`)
or the player's (their creation job's shape). Everything is derived; nothing
draws or writes. `resolve` returns the next occurrence of the window that is
not over at `at`, as absolute in-game hours `(start, end)`, or None when this
schedule has no such window within a week.

T3 resolves the initiation windows (`INITIATION_WINDOWS`); T4 adds the
promise windows (`PROMISE_WINDOWS`, plus `at:<hour>`): `morning` from their
waking band (never before `conversation.yaml` `clock.morning`), `tonight`
18:00-24:00 while they are up, `weekend`, `at_work` their work band, `later`
their first free band at least `promises.yaml` `later_min_hours` ahead.

**The speaker rule (spec §5.1, m4).** A promise's window is resolved against
the SENDER's schedule (whoever will write in it), but `at_work` against the
RECEIVER's (whoever is at work): `owner_of`.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Optional

from engine import social
from engine.game.state import GameState
from engine.social import behaviour, population

INITIATION_WINDOWS: tuple[str, ...] = ("waking", "commute", "lunch", "after_work", "evening", "late")
PROMISE_WINDOWS: tuple[str, ...] = ("lunch", "after_work", "tonight", "morning", "weekend", "at_work", "later")

_DAY = 24.0


def schedule_of(state: GameState, who: str) -> Any:
    """Something with `.job_shape`: the person, or the player (their job's shape; office when none).
    The player's job is stored by creation under `player["attributes"]["job"]` (creation.yaml's
    `fields.attributes.job`), the key `agreement.py` already reads -- never `player["job"]` (pre-flight F24)."""
    if who != "player":
        return population.profile(state, who)
    player = state.social.get("player") or {}
    job = str((player.get("attributes") or {}).get("job") or "")
    shapes = {str(r.get("id")): str(r.get("shape")) for r in social.data("population").get("jobs") or []}
    from engine.social import life   # lazily: life imports this module's peers

    return SimpleNamespace(job_shape=shapes.get(job, "office"), work_extra=life.work_extra(state))   # overtime (T17)


def _bands(sched: Any, day: int) -> list[tuple[float, float, str]]:
    week = behaviour._week(sched.job_shape)
    rows = week.get(behaviour.WEEKDAYS[day % 7]) or []
    bands = sorted(((day * _DAY + float(a), day * _DAY + float(b), str(s)) for a, b, s in rows),
                   key=lambda band: band[0])
    extra = getattr(sched, "work_extra", None)
    return _lengthened(bands, extra) if extra else bands


def _lengthened(bands: list[tuple[float, float, str]], extra: list[tuple[float, float, float]]
                ) -> list[tuple[float, float, str]]:
    """A running overtime (T17, life.py `work_extra_hours`): each work band that starts inside the event's
    days ends that many hours later, and a band that followed it starts after (or is gone)."""
    out: list[tuple[float, float, str]] = []
    pushed = 0.0                                   # the latest end a lengthened work band reaches
    for start, end, status in bands:
        hours = sum(h for a, b, h in extra if a <= start < b) if status == "work" else 0.0
        if hours:
            end += hours
            pushed = max(pushed, end)
        elif start < pushed:
            start = pushed
        if end > start:
            out.append((start, end, status))
    return out


def work_bands(state: GameState, who: str, day: int) -> list[tuple[float, float]]:
    """`who`'s work bands on absolute day `day` (0-based), as absolute hours, in order. Read-only."""
    return [(a, b) for a, b, status in _bands(schedule_of(state, who), day) if status == "work"]


def _morning_hour() -> float:
    return float((social.data("conversation").get("clock") or {}).get("morning", 7))


def _on_day(sched: Any, window: str, day: int) -> Optional[tuple[float, float]]:
    bands = _bands(sched, day)
    awake = [b for b in bands if b[2] != "asleep"]
    work = [b for b in bands if b[2] == "work"]
    base = day * _DAY
    if window == "waking":
        # The first awake band that is not the tail of the night before (a band from 00:00 that ends by
        # `clock.morning`: a night shift's 00:00-02:00, a student's night out), as `_promise_day`'s morning
        # guards (v0.24.0 T14): without it a bartender slept to the next midnight and a student a day on.
        morning = base + _morning_hour()
        rising = [b for b in awake if not (b[0] <= base and b[1] <= morning)]
        return (rising[0][0], rising[0][0] + 1.0) if rising else None
    if window == "commute" and work:
        return work[0][0] - 1.0, work[0][0]
    if window == "lunch":
        noon = (base + 12.0, base + 14.0)
        if any(b[0] < noon[1] and b[1] > noon[0] for b in awake):
            return noon
        return None
    if window == "after_work" and work:
        return work[-1][1], work[-1][1] + 2.0
    if window == "evening":
        span = (base + 18.0, base + 22.0)
        return span if any(b[0] < span[1] and b[1] > span[0] and b[2] != "work" for b in awake) else None
    if window == "late":
        span = (base + 22.0, base + 25.0)
        return span if any(b[1] > span[0] for b in awake) else None
    return None


def _promise_day(sched: Any, window: str, day: int, *, morning: float) -> Optional[tuple[float, float]]:
    bands = _bands(sched, day)
    awake = [b for b in bands if b[2] != "asleep"]
    work = [b for b in bands if b[2] == "work"]
    base = day * _DAY
    # Their waking band: the first awake band still going at `clock.morning` -- a late-night tail from
    # the night before (a night shift's 00:00-02:00) is not a morning, and 07:00 then would be in bed.
    waking = [b for b in awake if b[1] > base + morning]
    if window == "morning" and waking:
        start = max(waking[0][0], base + morning)
        end = min(start + 3.0, waking[0][1])             # never past the waking band, into work or sleep (M5)
        return (start, end) if start < base + 12.0 else None
    if window == "tonight":
        return (base + 18.0, base + 24.0) if any(b[1] > base + 18.0 for b in awake) else None
    if window == "weekend":
        return (base + 9.0, base + 22.0) if behaviour.WEEKDAYS[day % 7] in ("sat", "sun") else None
    if window == "at_work" and work:
        return work[0][0], work[-1][1]
    if window.startswith("at:"):
        hour = float(window.split(":", 1)[1])
        return base + hour, base + hour + 1.0
    return _on_day(sched, window, day)                    # lunch, after_work


def resolve(state: GameState, who: str, window: str, at: float) -> Optional[tuple[float, float]]:
    """The next occurrence of `window` for `who` that has not ended by `at` (clipped to start no earlier
    than `at`): an initiation window or a promise window. None when this schedule has none within a week."""
    sched = schedule_of(state, who)
    morning = _morning_hour()
    if window == "later":
        lead = float(social.data("promises").get("later_min_hours", 2))
        return first_free(state, who, at + lead)
    first = int(at // _DAY)
    for day in range(first - 1, first + 8):          # the day before: a window that crosses midnight
        span = (_promise_day(sched, window, day, morning=morning) if window in PROMISE_WINDOWS or window.startswith("at:")
                else _on_day(sched, window, day))
        if span is not None and span[1] > at:
            return max(span[0], at), span[1]
    return None


def first_free(state: GameState, who: str, at: float) -> tuple[float, float]:
    """The first free (awake, not working) band starting at or after `at`."""
    sched = schedule_of(state, who)
    first = int(at // _DAY)
    for day in range(first, first + 8):
        for start, end, status in _bands(sched, day):
            if status in ("free", "out") and end > at:
                return max(start, at), end
    raise ValueError(f"social: population.yaml: {who} has no free band in a week")


def owner_of(window: str, *, by: str, pid: str) -> str:
    """Whose schedule resolves a promise's window (m4): the SENDER's, but `at_work` is the RECEIVER's."""
    sender = pid if by == "person" else "player"
    receiver = "player" if by == "person" else pid
    return receiver if window == "at_work" else sender
