"""
The Law's Balance Harness
=========================

Play HUE & CRY headlessly with a scripted thief and report the numbers that
decide whether the Lantern Watch is tuned (AGENTS.md rule 10: balance
constants are set by measurement, not guessed).

THREE POLICIES, one city, the same seeds:

  careful   Buys a porter's smock from Dock Mag on day one and puts it on in
            an empty Wickmarket after the stalls close, with nobody there to
            see the change; it wears it from then on. From day two it spends
            its days in the Snuffs -- the ward no Lantern walks -- and lifts
            ONE purse there each night at 21:00, among the warehousemen
            drinking their wages.
  reckless  Walks into Wickmarket every afternoon in its own face, the hours
            the whole Watch buys its lunch there, and lifts up to
            ``RECKLESS_LIFTS`` purses, lingering an hour in the square after
            each one. It sleeps in the square.
  briber    The reckless thief, answering every stop with the Lantern's bribe
            whenever its purse covers the price, running otherwise.

Neither picks a Lantern's pocket, and both pick the least watchful mark on
offer: they differ in when, where and in whose face.

Careful and reckless answer a Lantern's stop the same way -- ``run`` -- so
the arrest count measures how often the Watch catches each, not a different
taste in surrender; the briber exists to show what coin buys. Held, a thief
pays the fine if it can and serves the days if not.

WHAT IS REAL AND WHAT IS NOT. Every lift, walk, purchase, guise change,
encounter approach, fine and sentence goes through
``tool_dispatcher.execute_intent`` -- the production channel a chosen option
takes -- so legality, witnesses, reports, cooling and confiscation are the
engine's own. The patrol runs once per action, after it, exactly as
``run_turn`` places it (and, as there, not on an action that answered an open
scene). Waiting and sleeping advance the clock through
``clock.advance_time``, the one writer of time. What is NOT the game: the
harness feeds the thief and restores its stamina each morning through the
``hunger`` and ``stamina`` effects, because HUE & CRY ships no food loop yet
and this harness measures the Law, not starvation. No narration runs.

AGENDAS ARE OFF HERE BY DEFAULT (v0.12). Since v0.12 the Magpie robs a
shining house most nights and each robbery lands on the thief's own name
(law.yaml `links`) -- so with agendas on, a thief who lifts nothing is
`sought` within five days, and "does a careful thief stay below sought" stops
measuring the thief. This harness measures what the thief's OWN conduct earns
from the Watch, so it runs with `paths.agendas` declared off
(``agendas_off``); ``--agendas`` runs it with the city's agendas on, and
scripts/simulate_agendas.py measures the two together.

THE OPENING (v0.16). ``--opening a|b|c`` has every thief take that choice
off the morning barge first -- run, talk, or come quietly -- through the same
three halves ``run_turn`` takes it by (``resolve_player_intent``, then
``resolve_authored_choice``, applied by ``authored_choice.resolve``), then
answer a stop or a cell the way its policy answers any, before its first
day. Without the flag no thief takes the opening (every table before v0.16),
so the default numbers are unchanged. With it, the report gains an
``opening`` block: how often the choice passed, was filed, opened the stop,
ended in a cell, and the thief's band on the Quay each morning for three days.

THE BREAK-OUT (v0.17). ``--break-out`` has a held thief try the story's
jailbreak (the ``set_piece`` verb, then each ``challenge`` step) before the
fine or the days, attempt after attempt until it walks out or its hp is down
to ``BREAK_OUT_HP_FLOOR``. The report gains a ``break_out`` block: attempts,
escapes, hidings, the Wick's band on the thief's own face the moment it
walked out, and stops back into a cell within a day. With ``--set
deeds.escape=N`` it is how the ``escape`` deed's severity was set (law.yaml).
Without the flag nobody breaks out, so every table before it is unchanged;
every run also counts the clock advances a served day took
(``max_advances_per_day_served``), the cost guard tests/test_hue_and_cry.py
holds instead of a wall-clock one.

Usage:
    python scripts/simulate_law.py                    # 40 seeds x 10 days, both
    python scripts/simulate_law.py --opening a --policy careful --set deeds.resisting_watch=3
    python scripts/simulate_law.py --seeds 10 --days 5 --policy reckless
    python scripts/simulate_law.py --agendas          # with the Magpie and co. on
    python scripts/simulate_law.py --break-out --policy reckless --set deeds.escape=4
    python scripts/simulate_law.py --json

Version: v0.6.0 [2026-09-27]
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterator, Optional

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

#: The ward the reckless thief works and the one every table row reports on:
#: Wickmarket's, where the whole Watch walks at lunch.
BUSY_JURISDICTION = "wick"
BUSY_DISTRICT = "wickmarket"
QUIET_DISTRICT = "the_snuffs"
#: Purses the reckless thief tries each afternoon (one per mark per day is
#: the engine's rule; this is how many marks it bothers with).
RECKLESS_LIFTS = 3
#: The hour the reckless thief starts in the square: the Watch's lunch.
RECKLESS_HOUR = 13
#: The careful thief's hours: smock on in an empty market on night one; each
#: night after, one lift in the Snuffs.
CAREFUL_CHANGE_HOUR = 23
CAREFUL_LIFT_HOUR = 21
POLICIES = ("careful", "reckless", "briber")
#: The watch-house the opening happens under: the barge docks on the Quay.
OPENING_JURISDICTION = "quay"
#: Mornings of the Quay band the ``opening`` block reports.
OPENING_MORNINGS = 3
#: ``--break-out``: the thief stops trying at this hp or below -- the
#: jailbreak's hiding is 3 (data/challenges/lantern_house.yaml), so one more
#: failure would be a death -- and pays or serves instead.
BREAK_OUT_HP_FLOOR = 3


@dataclass
class DayRow:
    day: int
    band: str               # the policy's worst band in the busy ward, end of day
    worst_band: str         # its worst band in any ward
    lifts: int = 0
    witnessed: int = 0
    reported: int = 0
    arrests: int = 0
    seconds: float = 0.0


@dataclass
class Run:
    seed: int
    policy: str
    days: list[DayRow] = field(default_factory=list)
    arrests: int = 0
    hp_after_sentence: list[int] = field(default_factory=list)
    stops: int = 0
    fines_paid: int = 0
    income: int = 0          # crowns lifted
    bribes: int = 0          # stops answered with coin
    bribe_gold: int = 0
    days_served: list[int] = field(default_factory=list)
    #: ``clock.advance_time`` calls a served sentence took, per day of it
    #: (v0.17 T4): the cost guard, counted rather than timed.
    advances_per_day_served: list[float] = field(default_factory=list)
    #: ``--break-out`` only: attempts, beatings, escapes, the Wick's band on
    #: your face the moment you walked out, and stops back into a cell within
    #: a day of an escape (see ``Thief.try_break_out``).
    break_out: dict[str, Any] = field(default_factory=dict)
    #: ``--opening`` only: what the barge choice did (see ``take_opening``).
    opening: dict[str, Any] = field(default_factory=dict)
    #: Deaths ``check_death`` handled (``counting_deaths``), respawns included.
    deaths: int = 0


#: Deaths per live state, while ``counting_deaths`` is installed. Keyed by
#: ``id(state)``; each ``Thief`` clears its own entry when it is made, so a
#: recycled id never inherits a finished run's count.
_DEATHS: dict[int, int] = {}


@contextmanager
def counting_deaths() -> Iterator[None]:
    """
    Count every death ``encounter.check_death`` handles, per state, for the
    duration (v0.17). A harness switch, like ``agendas_off``.

    Since HUE & CRY ships death.yaml (v0.17), hp 0 RESPAWNS: the thief wakes
    at 8 hp inside the very ``advance_time`` that starved it, so a harness
    that samples hp between actions no longer sees the 0. Every caller
    reaches the rules through the module attribute (``encounter.check_death``
    -- the clock, a round, a job stage, a card), so the wrapper sees them
    all. Nested use is a no-op.
    """
    from engine.game import encounter

    real = encounter.check_death
    if getattr(real, "counts_deaths", False):
        yield
        return

    def counted(state: Any, *args: Any, **kwargs: Any) -> Any:
        record = real(state, *args, **kwargs)
        if record and record.get("died"):
            _DEATHS[id(state)] = _DEATHS.get(id(state), 0) + 1
        return record

    counted.counts_deaths = True  # type: ignore[attr-defined]
    encounter.check_death = counted  # type: ignore[assignment]
    try:
        yield
    finally:
        encounter.check_death = real  # type: ignore[assignment]


def deaths(state: Any) -> int:
    """How many times ``state`` died while ``counting_deaths`` was installed."""
    return _DEATHS.get(id(state), 0)


@contextmanager
def _counting_advances() -> Iterator[list[int]]:
    """
    Count every ``clock.advance_time`` call for the duration, into the one
    element of the yielded list (v0.17 T4).

    What a served sentence costs is how many times it moves the clock --
    every call runs the world's hour: rumour, agendas, the director's
    question. Counted, not timed: the per-day wall-clock guard it replaces
    swung 0.7-1.25s between identical runs on the owner's machine.
    """
    from engine.game import clock

    real = clock.advance_time
    calls = [0]

    def counted(*args: Any, **kwargs: Any) -> Any:
        calls[0] += 1
        return real(*args, **kwargs)

    clock.advance_time = counted  # type: ignore[assignment]
    try:
        yield calls
    finally:
        clock.advance_time = real  # type: ignore[assignment]


@contextmanager
def agendas_off() -> Iterator[None]:
    """
    The active story with its agendas switched off, for the duration: no
    Magpie, no captain's net, no Silas -- the city as it played before v0.12.

    A harness switch, not a content one. ``agendas.declared`` answers False
    inside the block, and every agenda entry point asks it first (``begin``,
    the prompt blocks, the masks), so the pass never runs. It cannot be done
    by blanking ``paths.agendas`` in the config overlay: an empty ``paths.*``
    key is answered from the story's manifest (``engine/config.py``).
    """
    from engine.world import agendas

    declared = agendas.declared
    agendas.declared = lambda: False  # type: ignore[assignment]
    try:
        yield
    finally:
        agendas.declared = declared  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# The engine, driven the way a chosen option drives it
# ---------------------------------------------------------------------------


class _KeepsNothing:
    """A save store that writes nothing.

    ``SessionStore.create`` writes a run's first save, and every harness run
    used to land one per seed in the owner's real ``data/saves/<slug>/`` --
    tens of thousands of runs nobody played, crowding the load menu's index.
    A measurement is not a run anybody will load, so the harnesses' session
    store is handed this instead: no directory, no path, nothing to clean up.
    The run itself is untouched (a save reads the state, never writes it).
    """

    def save(self, state: Any, **_: Any) -> str:
        return ""


_KEEPS_NOTHING = _KeepsNothing()


class Thief:
    """One run: a session, an action counter, and the patrol after each action."""

    #: ``--break-out`` (v0.17 T4): held, try the story's jailbreak before the
    #: fine or the days. Off by default -- and for every harness that
    #: subclasses Thief -- so every table before it is unchanged.
    break_out = False

    def __init__(self, seed: int, policy: str) -> None:
        from engine.scenes.default_state import SessionStore

        self.session = SessionStore(save_store=lambda: _KEEPS_NOTHING).create(
            seed=seed, llm_fn=lambda m, **k: "{}")
        self.state = self.session.engine.state
        _DEATHS.pop(id(self.state), None)
        self.run = Run(seed=seed, policy=policy)
        self.today: Optional[DayRow] = None

    # -- one action = one turn ---------------------------------------------

    def act(self, action: str, target: str = "") -> dict[str, Any]:
        """Run one intent, then the watch's turn, as ``run_turn`` orders them."""
        from engine.agents.tool_dispatcher import execute_intent
        from engine.game.intents import scene_owns_turn
        from engine.world import law

        scene_at_start = scene_owns_turn(self.state)
        intent = {"action": action, "target": target} if target else {"action": action}
        receipts = execute_intent(intent, self.session.engine)
        result = (receipts[0].get("result") if receipts else {}) or {}
        if not scene_at_start:
            self.patrol()
        return result if isinstance(result, dict) else {}

    def patrol(self) -> None:
        from engine.world import law

        if law.patrol(self.state) is not None:
            self.run.stops += 1
            self.answer_stop()

    def answer_stop(self) -> None:
        """Run -- or, for the briber, pay whenever the purse covers it. A failed run is the cells.

        Answers any open scene, not only the Lantern's stop: since v0.14 a
        night street can hand the walker one (data/encounters/streets.yaml).
        Every threat there offers `run` too, so the policy is the same; a
        scene with no `run` (the lamplighter) takes its first way out that
        needs no roll.
        """
        from engine.game import encounter
        from engine.world import law

        guard = 0
        while encounter.active(self.state) and guard < 6:
            guard += 1
            offered = self.legal_targets("encounter")
            if self.run.policy == "briber" and "bribe" in offered:
                before = self.state.stats.gold
                self.act("encounter", "bribe")
                self.run.bribes += 1
                self.run.bribe_gold += before - self.state.stats.gold
                continue
            if "run" in offered or not offered:
                self.act("encounter", "run")
                continue
            auto = [a["id"] for a in encounter.available_approaches(self.state) if a["auto"]]
            self.act("encounter", (auto or offered)[0])
        if law.in_custody(self.state):
            self.run.arrests += 1
            if self.today is not None:
                self.today.arrests += 1
            tally = getattr(self.run, "break_out", None)
            if self.break_out and tally is not None:
                now = float(self.state.world_clock_hours)
                if any(now - h <= 24.0 for h in tally.get("escape_hours", [])):
                    tally["rearrested_within_a_day"] = tally.get("rearrested_within_a_day", 0) + 1
            self.leave_custody()

    def leave_custody(self) -> None:
        from engine.world import law

        if self.break_out and self.try_break_out():
            return
        held = law.custody(self.state)
        if self.state.stats.gold >= int(held.get("fine") or 0):
            self.act("pay_fine")
            self.run.fines_paid += 1
        else:
            with _counting_advances() as calls:
                receipt = self.act("serve")
            self.run.hp_after_sentence.append(int(self.state.stats.hp))
            self.run.days_served.append(int(receipt.get("days") or 0))
            # Other harnesses subclass Thief with Runs of their own; only
            # this one's reads the count.
            counts = getattr(self.run, "advances_per_day_served", None)
            if counts is not None and receipt.get("days"):
                counts.append(calls[0] / int(receipt["days"]))

    def try_break_out(self) -> bool:
        """
        The jailbreak, while one is offered and the thief can take another
        hiding (``BREAK_OUT_HP_FLOOR``). True when it walked out. Since fix
        round 1 a failed try closes the break-out until tomorrow
        (``retry: next_day``), so in practice this is ONE try an arrest: the
        thief does not sit a day in the cell unserved to try again, it pays
        or serves. Every attempt goes through ``execute_intent`` -- the
        ``set_piece`` verb, then ``challenge`` for each step -- so the rolls,
        the hiding, the ``release`` and the ``escape`` report are the engine's.
        """
        from engine.world import law

        tally = self.run.break_out
        while law.in_custody(self.state):
            offered = self.legal_targets("set_piece")
            if not offered or self.state.stats.hp <= BREAK_OUT_HP_FLOOR:
                return False
            tally["attempts"] = tally.get("attempts", 0) + 1
            self.act("set_piece", offered[0])
            guard = 0
            while self.state.challenge and guard < 8:
                guard += 1
                self.act("challenge", "attempt")
            if law.in_custody(self.state):
                tally["beatings"] = tally.get("beatings", 0) + 1
                continue
            tally["escapes"] = tally.get("escapes", 0) + 1
            tally.setdefault("wick_band_after", []).append(
                law.wanted_band(self.state, law.SELF_GUISE, BUSY_JURISDICTION))
            tally.setdefault("escape_hours", []).append(float(self.state.world_clock_hours))
            return True
        return False

    def legal_targets(self, action: str) -> list[str]:
        from engine.game import intents

        verb = intents.find_verb(intents.legal_intents(self.state), action)
        return [t for t, _label in (verb.options if verb else ())]

    def take_opening(self, choice_id: str) -> None:
        """The morning barge's choice, the way ``run_turn`` takes it, then
        whatever it led to answered as the policy answers any stop or cell."""
        from engine.agents.tool_dispatcher import execute_intent
        from engine.game import authored_choice, encounter
        from engine.scenes.default_state import (resolve_authored_choice,
                                                 resolve_player_intent)
        from engine.world import law

        filed_before = len(self.state.law.get("reports") or [])
        intent = resolve_player_intent(self.session, choice_id)
        consequences = resolve_authored_choice(self.session, choice_id)
        receipts = execute_intent(intent, self.session.engine) if intent else []
        receipts += authored_choice.resolve(self.state, consequences, intent, receipts)
        mine = next((r["result"] for r in receipts if r.get("skill") == "authored_choice"), {})
        self.run.opening = {
            "passed": bool(mine.get("passed")),
            # Anything the choice put on file: its deed's report, or a branch's.
            "reported": len(self.state.law.get("reports") or []) > filed_before,
            "stopped": encounter.active(self.state),
        }
        arrests = self.run.arrests
        self.answer_stop()
        if law.in_custody(self.state):  # came quietly: no stop to answer
            self.run.arrests += 1
            self.leave_custody()
        self.run.opening["arrested"] = self.run.arrests > arrests

    # -- composite moves ----------------------------------------------------

    def wait_until(self, hour: int) -> None:
        """Advance the clock to the next ``hour`` o'clock (a wait, not a turn)."""
        from engine.game.clock import advance_time

        now = self.state.world_clock_hours
        target = (int(now // 24) * 24) + hour
        while target < now - 1e-9:
            target += 24
        if target - now > 1e-9:
            advance_time(self.state, target - now)

    def linger(self, hours: float = 1.0) -> None:
        """Stand about for an hour -- one turn, so the patrol gets its look."""
        from engine.game.clock import advance_time

        advance_time(self.state, hours)
        self.patrol()

    def walk(self, destination: str) -> None:
        from engine.game.locations import get_edge

        if self.state.location_id == destination:
            return
        from engine.game import encounter

        path = _route(self.state.location_id, destination)
        for step in path:
            if self.state.location_id != step and get_edge(self.state.location_id, step):
                self.act("travel", step)
                if encounter.active(self.state):
                    # A night street met the walker on arrival (v0.14).
                    self.answer_stop()
            if self.state.location_id != step:
                return  # held, or refused: the day's plan is over

    def lift_one(self) -> bool:
        """Lift the easiest legal mark. False when there is nobody to rob.

        Both thieves pick the least watchful pocket on offer (its role's
        alertness band), because neither is a fool about WHOSE purse -- they
        differ in when, where and in whose face.
        """
        from engine.game.intents import DIFFICULTY_BANDS
        from engine.world import npc_sim, thievery

        from engine.world import law

        roles = set(law.load_spec().get("roles") or [])

        def role_of(npc_id: str) -> str:
            presence = npc_sim.resolve_npc(self.state, npc_id)
            return presence.role if presence else ""

        # Nobody here picks a Lantern's own pocket: that is a different
        # policy (and a different joke).
        marks = [m for m in self.legal_targets("lift") if role_of(m) not in roles]
        if not marks:
            return False
        bands = list(DIFFICULTY_BANDS)

        def ease(npc_id: str) -> int:
            band = thievery.alertness_for(role_of(npc_id))
            return bands.index(band) if band in bands else len(bands)

        receipt = self.act("lift", min(marks, key=ease))
        if receipt.get("ok"):
            self.run.income += int(receipt.get("gold") or 0)
        if receipt.get("ok") and self.today is not None:
            self.today.lifts += 1
            self.today.witnessed += int(bool(receipt.get("seen_by")))
            self.today.reported += int(bool(receipt.get("reported")))
        return bool(receipt.get("ok"))

    def morning(self) -> None:
        """The harness's one liberty: the thief is fed and rested."""
        from engine.game.effects import apply_effect

        if self.state.hunger > 0:
            apply_effect(self.state, {"type": "hunger", "delta": -self.state.hunger})
        gap = self.state.stats.max_stamina - self.state.stats.stamina
        if gap > 0:
            apply_effect(self.state, {"type": "stamina", "delta": gap})


def _route(start: str, goal: str) -> list[str]:
    """Shortest walk over PUBLIC streets (no secret places), start excluded."""
    from collections import deque

    from engine.game.locations import LOCATIONS

    def neighbours(loc: str) -> list[str]:
        row = LOCATIONS.get(loc) or {}
        return sorted(
            n for n in (row.get("connections") or {})
            if not (LOCATIONS.get(n) or {}).get("secret")
        )

    prev: dict[str, Optional[str]] = {start: None}
    queue = deque([start])
    while queue:
        here = queue.popleft()
        if here == goal:
            break
        for n in neighbours(here):
            if n not in prev:
                prev[n] = here
                queue.append(n)
    if goal not in prev:
        return []
    path: list[str] = []
    node: Optional[str] = goal
    while node is not None and node != start:
        path.append(node)
        node = prev[node]
    return list(reversed(path))


# ---------------------------------------------------------------------------
# Policies: one in-game day each
# ---------------------------------------------------------------------------


def _careful_day(thief: Thief, day: int) -> None:
    from engine.world import law

    if day == 1:
        # Dock Mag's crate is on the quay from 05:00: the smock is the first
        # thing a careful thief buys. It goes on in Wickmarket at 23:00, when
        # the stalls are shut and the square is empty -- a change of face
        # nobody sees links nothing -- and it stays on: a porter is a porter
        # all day. Day one is spent setting up, so it lifts nothing.
        thief.act("buy", "npc_dock_mag/porters_smock")
        thief.walk(BUSY_DISTRICT)
        thief.wait_until(CAREFUL_CHANGE_HOUR)
        if "porter" in thief.legal_targets("guise"):
            thief.act("guise", "porter")
        thief.walk(QUIET_DISTRICT)
        return
    # The day goes by in the Snuffs, where no Lantern walks; the lift is at
    # night, among the warehousemen drinking their wages.
    thief.walk(QUIET_DISTRICT)
    thief.wait_until(CAREFUL_LIFT_HOUR)
    if law.current_guise(thief.state) == "porter":
        thief.lift_one()


def _reckless_day(thief: Thief, day: int) -> None:
    thief.walk(BUSY_DISTRICT)
    thief.wait_until(RECKLESS_HOUR)
    for _ in range(RECKLESS_LIFTS):
        thief.lift_one()
        thief.linger(1.0)


DAYS: dict[str, Callable[[Thief, int], None]] = {
    "careful": _careful_day,
    "reckless": _reckless_day,
    # The reckless thief's day, answering every stop with coin when it can.
    "briber": _reckless_day,
}


def _worst_band(state: Any, jurisdictions: list[str]) -> str:
    from engine.world import law

    bands = law.load_spec()["wanted"]["bands"]
    guises = list(law.load_spec()["guises"])
    worst = 0
    for j in jurisdictions:
        for g in guises:
            worst = max(worst, bands.index(law.wanted_band(state, g, j) or bands[0]))
    return bands[worst]


def play(seed: int, policy: str, days: int, opening: str = "",
         break_out: bool = False) -> Run:
    """
    One run of ``days`` IN-GAME days. A row per in-game day, read at the next
    08:00. A sentence that swallows days fills them with the band read when
    the prisoner walks out (they were in a cell; nothing new was filed).
    ``opening`` is the barge choice taken first, or "" for none;
    ``break_out`` has a held thief try the jailbreak first (``Thief.try_break_out``).
    """
    with counting_deaths():
        return _play(seed, policy, days, opening, break_out)


def _play(seed: int, policy: str, days: int, opening: str, break_out: bool = False) -> Run:
    from engine.world import law

    thief = Thief(seed, policy)
    thief.break_out = break_out
    everywhere = list(law.load_spec()["jurisdictions"])
    if opening:
        thief.take_opening(opening)
    played = 0
    while thief.state.world_day <= days:
        played += 1
        start = time.perf_counter()
        first_day = thief.state.world_day
        row = DayRow(day=first_day, band="", worst_band="")
        thief.today = row
        thief.morning()
        DAYS[policy](thief, played)
        # Sleep to the next 08:00: the day ends at breakfast.
        thief.wait_until(8)
        row.band = _worst_band(thief.state, [BUSY_JURISDICTION])
        row.worst_band = _worst_band(thief.state, everywhere)
        if opening:
            thief.run.opening.setdefault("quay", []).append(
                _worst_band(thief.state, [OPENING_JURISDICTION]))
        row.seconds = time.perf_counter() - start
        thief.run.days.append(row)
        for skipped in range(first_day + 1, min(thief.state.world_day - 1, days) + 1):
            thief.run.days.append(DayRow(day=skipped, band=row.band, worst_band=row.worst_band,
                                         seconds=0.0))
    thief.run.days = thief.run.days[:days]
    thief.run.deaths = deaths(thief.state)
    return thief.run


# ---------------------------------------------------------------------------
# The table
# ---------------------------------------------------------------------------


def summarise(runs: list[Run], days: int) -> dict[str, Any]:
    from engine.world import law

    bands = law.load_spec()["wanted"]["bands"]
    sought = bands.index("sought")
    wanted = bands.index("wanted")
    per_day = []
    for d in range(days):
        rows = [r.days[d] for r in runs if len(r.days) > d]
        lifts = sum(x.lifts for x in rows)
        per_day.append({
            "day": d + 1,
            "median_band": bands[int(statistics.median_low([bands.index(x.band) for x in rows]))],
            "witnessed": round(sum(x.witnessed for x in rows) / lifts, 2) if lifts else 0.0,
            "reported": round(sum(x.reported for x in rows) / lifts, 2) if lifts else 0.0,
            "seconds": round(statistics.mean([x.seconds for x in rows if x.seconds] or [0.0]), 3),
        })
    first_sought = []
    for r in runs:
        hit = next((x.day for x in r.days if bands.index(x.worst_band) >= sought), None)
        first_sought.append(hit)
    seed_days = [x for r in runs for x in r.days]
    below_sought = sum(bands.index(x.worst_band) < sought for x in seed_days) / len(seed_days)
    wanted_by_4 = sum(
        any(bands.index(x.band) >= wanted for x in r.days[:4]) for r in runs
    ) / len(runs)
    arrested = sum(r.arrests >= 1 for r in runs) / len(runs)
    hp = [h for r in runs for h in r.hp_after_sentence]
    reached = [d for d in first_sought if d is not None]
    return {
        "runs": len(runs),
        "per_day": per_day,
        "below_sought_seed_days": round(below_sought, 3),
        "wanted_by_day_4": round(wanted_by_4, 3),
        "first_sought_median_day": statistics.median_low(reached) if reached else None,
        "never_sought": sum(d is None for d in first_sought),
        "arrests_per_run": round(statistics.mean(r.arrests for r in runs), 2),
        "runs_with_an_arrest": round(arrested, 3),
        "stops_per_run": round(statistics.mean(r.stops for r in runs), 2),
        "min_hp_after_sentence": min(hp) if hp else None,
        "deaths_per_run": round(statistics.mean(r.deaths for r in runs), 2),
        "runs_with_a_death": round(sum(r.deaths > 0 for r in runs) / len(runs), 3),
        "sentences_served": len(hp),
        "fines_paid": sum(r.fines_paid for r in runs),
        "max_days_served": max((d for r in runs for d in r.days_served), default=None),
        "max_advances_per_day_served": max(
            (a for r in runs for a in r.advances_per_day_served), default=None),
        "bribes_per_run": round(statistics.mean(r.bribes for r in runs), 2),
        "bribe_share_of_income": (
            round(sum(r.bribe_gold for r in runs) / sum(r.income for r in runs), 3)
            if sum(r.income for r in runs) else 0.0
        ),
        "max_seconds_per_day": round(max(x.seconds for x in seed_days), 3),
        **({"opening": _opening_summary(runs, bands)} if runs and runs[0].opening else {}),
        **({"break_out": _break_out_summary(runs, bands)}
           if any(r.break_out for r in runs) else {}),
    }


def _opening_summary(runs: list[Run], bands: list[str]) -> dict[str, Any]:
    """What ``--opening`` did, across the seeds: rates, and the Quay each morning."""
    n = len(runs)

    def rate(key: str) -> float:
        return round(sum(bool(r.opening.get(key)) for r in runs) / n, 3)

    mornings = []
    for d in range(OPENING_MORNINGS):
        seen = [r.opening["quay"][d] for r in runs if len(r.opening.get("quay") or []) > d]
        mornings.append({band: seen.count(band) for band in bands if seen.count(band)})
    return {"passed": rate("passed"), "reported": rate("reported"), "stopped": rate("stopped"),
            "arrested": rate("arrested"), "quay_band_by_morning": mornings}


def _break_out_summary(runs: list[Run], bands: list[str]) -> dict[str, Any]:
    """What ``--break-out`` did, across the seeds."""
    def total(key: str) -> int:
        return sum(int(r.break_out.get(key, 0)) for r in runs)

    after = [b for r in runs for b in r.break_out.get("wick_band_after", [])]
    return {
        "attempts": total("attempts"),
        "escapes": total("escapes"),
        "beatings": total("beatings"),
        "escape_rate_per_attempt": (round(total("escapes") / total("attempts"), 3)
                                    if total("attempts") else None),
        "arrests": sum(r.arrests for r in runs),
        "escape_rate_per_arrest": (round(total("escapes") / sum(r.arrests for r in runs), 3)
                                   if sum(r.arrests for r in runs) else None),
        "wick_band_after_escape": {b: after.count(b) for b in bands if after.count(b)},
        "rearrested_within_a_day": total("rearrested_within_a_day"),
    }


def measure(policy: str, seeds: int, days: int, opening: str = "",
            break_out: bool = False) -> dict[str, Any]:
    runs = [play(seed, policy, days, opening, break_out) for seed in range(seeds)]
    return summarise(runs, days)


def render(policy: str, report: dict[str, Any]) -> str:
    lines = [f"{policy} ({report['runs']} seeds)",
             "| day | median band (wick) | witnessed | reported | s/day |",
             "|---|---|---|---|---|"]
    for row in report["per_day"]:
        lines.append(f"| {row['day']} | {row['median_band']} | {row['witnessed']:.2f} | "
                     f"{row['reported']:.2f} | {row['seconds']:.3f} |")
    lines.append(
        f"below sought on {report['below_sought_seed_days']:.0%} of seed-days; "
        f"wanted by day 4 on {report['wanted_by_day_4']:.0%} of seeds; "
        f"first sought median day {report['first_sought_median_day']} "
        f"({report['never_sought']} never); arrests/run {report['arrests_per_run']}, "
        f"runs with an arrest {report['runs_with_an_arrest']:.0%}; stops/run "
        f"{report['stops_per_run']}; min hp after a sentence {report['min_hp_after_sentence']} "
        f"({report['sentences_served']} served, longest {report['max_days_served']} days, "
        f"at most {report['max_advances_per_day_served']} clock advances a day; "
        f"{report['fines_paid']} fines paid); deaths/run {report['deaths_per_run']} "
        f"({report['runs_with_a_death']:.0%} of runs); bribes/run {report['bribes_per_run']}, "
        f"{report['bribe_share_of_income']:.0%} of lifted income; "
        f"slowest day {report['max_seconds_per_day']}s"
    )
    if "opening" in report:
        o = report["opening"]
        lines.append(
            f"opening: passed {o['passed']:.0%}, filed {o['reported']:.0%}, stopped "
            f"{o['stopped']:.0%}, arrested {o['arrested']:.0%}; the Quay by morning "
            f"{o['quay_band_by_morning']}"
        )
    if "break_out" in report:
        b = report["break_out"]
        lines.append(
            f"break-out: {b['escapes']} escapes in {b['attempts']} attempts "
            f"({b['escape_rate_per_attempt']} a try; {b['escape_rate_per_arrest']} of "
            f"{b['arrests']} arrests), {b['beatings']} hidings; the Wick on "
            f"your face as you walked out {b['wick_band_after_escape']}; back in a cell "
            f"within a day {b['rearrested_within_a_day']}"
        )
    return "\n".join(lines)


def _override(assignment: str) -> None:
    """
    Patch one number in the LOADED law file, for this process only.

    A tuning aid: the file on disk is what ships, and every number in it is
    one this harness measured. ``wanted.thresholds=0,2,4,7,11`` takes a list.
    """
    from engine.world import law

    key, _, raw = assignment.partition("=")
    parts = key.strip().split(".")
    if parts[0] == "stop":
        # stop.<approach>.<key>=N patches the loaded watch_stop scene.
        from engine.game import encounter

        row = encounter.get_definition("watch_stop") or {}
        row["approaches"][parts[1]][parts[2]] = int(float(raw))
        return
    node: Any = law.load_spec()
    for part in parts[:-1]:
        node = node[int(part) if isinstance(node, list) else part]
    value: Any = [float(v) for v in raw.split(",")] if "," in raw else float(raw)
    if parts[0] == "deeds":
        value = int(value)
    last = parts[-1]
    if isinstance(node, dict) and last.isdigit() and int(last) in node:
        node[int(last)] = value
    else:
        node[last] = value


@contextmanager
def _nothing() -> Iterator[None]:
    yield


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--seeds", type=int, default=40)
    parser.add_argument("--days", type=int, default=10)
    parser.add_argument("--policy", choices=(*POLICIES, "all"), default="all")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--opening", choices=("a", "b", "c"), default="",
                        help="take this barge choice first (run, talk, come quietly)")
    parser.add_argument("--agendas", action="store_true",
                        help="measure with the story's agendas on (off by default; see above)")
    parser.add_argument("--break-out", action="store_true",
                        help="held, try the jailbreak before the fine or the days (v0.17)")
    parser.add_argument(
        "--set", action="append", default=[], metavar="KEY=VALUE",
        help="try a number without editing the file: wanted.cool_per_day=0.75, "
             "recognise.sought=0.05, notice.base=0.5, deeds.pickpocket=2 (repeatable)",
    )
    args = parser.parse_args(argv)

    import logging

    logging.disable(logging.WARNING)
    from engine.games import registry

    registry.activate("hue-and-cry")
    with (_nothing() if args.agendas else agendas_off()):
        for assignment in args.set:
            _override(assignment)
        policies = POLICIES if args.policy == "all" else (args.policy,)
        reports = {p: measure(p, args.seeds, args.days, args.opening, args.break_out)
                   for p in policies}
    if args.json:
        print(json.dumps(reports, indent=2))
    else:
        print("\n\n".join(render(p, r) for p, r in reports.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
