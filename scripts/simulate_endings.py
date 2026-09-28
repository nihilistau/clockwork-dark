"""
The Endings Harness
===================

Play HUE & CRY headlessly from the morning barge to two days past the
Hanging Fair with a thief who wants ONE of its endings, and report which of
the eight each run actually reached, and when (AGENTS.md rule 10: the fair's
day and every ending's threshold are set by measurement, not guessed).

ELEVEN POLICIES, the same seeds, the same city. Every one takes the morning
barge's choice (``--opening``, or its own below), is sworn to the Honest
Company its first night (the initiation is dealt at the long table in the
Snuffs at 18:00, as scripts/simulate_acts.py deals it), and from the next
morning plays for its ending:

  investigator_a/b/c  scripts/simulate_acts.py's investigator, one per
                  opening (run, talk, come quietly): it works the Magpie's
                  trail through the city's houses and names the suspect the
                  desk offers. Once the Magpie is unmasked it goes for
                  CLEARED: to the Green while the fair is on (``F3``, "see it
                  done"), or to the captain's desk after it (``D4``, "hear it
                  said"); before the fair it waits for it.
  lantern         The investigator who also goes round the lamps with Wren
                  every dusk (casing stops at ``LANTERN_CASING_ENDS``, the
                  round is at 18:00) and calls at the desk after it: A
                  LANTERN, the badge (``D3``, "take the badge"). It keeps
                  lamping past the unmasking for the badge, and takes
                  Cleared only on the fair's last day (``F3`` on the Green;
                  ``walk_away`` before it, ``not_yet`` at the desk's ``D4``).
  partner         The investigator who never goes to the Watch: when the
                  trail would take a name to the desk, it takes it to the
                  suspects' doors instead -- Silk Row in Lady Imelda's hours
                  (16:00), then the Snuffs at 21:00, where Wren and Silas keep
                  theirs -- and says it (the confrontation's ``say_it``).
                  Partnered, it goes to the fair for PARTNERS (``F6``, "take
                  it together"), or, once the fair is over, up Margrave's Hill
                  after dark (``L1``, the_last_job.yaml, since T8's fix round
                  1). A wrong door is followed by the desk's rule:
                  a clue carried out since, and it tries again.
  heister         A careful burglar (scripts/simulate_jobs.py's method: a
                  small house cased to ``CAREFUL_INTEL``, emptied at the hour
                  nobody is home, walked away from if roused) for
                  ``HEISTER_JOBS`` jobs, one a day, then it lies low in the
                  Snuffs until the fair. On the fair's first morning it goes
                  up the Hill for the heart (``F2``, "lift the heart", a
                  severe stealth roll) and, if it has it, walks it home to the
                  Snuffs: THE LEGEND (the_heart_goes_home). A failed lift
                  lies low again.
  loyalist        The Company's own: its oath answered with every roll
                  (``LOYALIST_OATH``: persuasion, nerve, lore), a shift on
                  Dock Mag's quay every morning, Mother Gannet's Silk Row job
                  struck at her table and done (a Silk Row house, cased and
                  emptied the careful way) and paid, and home to the Porters'
                  Hall every evening, where the needles are offered the
                  night they are earned -- from the Hanging Fair on, since
                  T8's fix round 1: GUILDMASTER (``P1``, "take the chair"). At the fair it stands against Silas Crook if he
                  makes his move (``F4``, a hard persuasion roll: won, he is
                  stopped; lost, THE DAPPER'S CITY).
  dapper          The porter's day (the quay, the lamps, the Snuffs at night)
                  for a porter who likes the look of a plum ribbon: to the
                  Green every day of the fair, and if Silas Crook makes his
                  move there, it stands at his shoulder (``F4``, "stand with
                  him"): THE DAPPER'S CITY.
  porter          Honest work and nothing else: the quay every morning, the
                  lamps every dusk. It goes to the fair on its first morning,
                  watches the Showing, keeps out of the Company's quarrel,
                  and that evening walks down to the evening barge: HONEST
                  AFTER ALL. It tries the barge every evening from then on.
  reckless        simulate_law.py's reckless pickpocket -- Wickmarket at
                  13:00 in its own face, three purses, an hour in the square
                  after each, every day. Held, it tries the jailbreak before
                  the fine or the days (simulate_law.py's ``--break-out``).
                  It is who THE ROPE is for.
  runner          The reckless pickpocket after one honest shift on the quay
                  its first morning (so the barge's wage clause is met, and
                  only its own deeds can keep it ashore), down to the barge
                  every evening from day 2 after the day's purses: the thief
                  with real deeds at the gangplank.

``--break-out all`` has every policy try the jailbreak when held, ``none``
nobody (the control); by default only the two reckless thieves do, and the
rest pay the fine or serve the days, as scripts/simulate_acts.py's
investigator does.

WHAT A POLICY MAY READ. What a player sees: the city, its own purse, pack and
standing, the evidence meter and the desk's gate (as simulate_acts.py reads
them), the fair on the calendar, and the cards and answers on the table. It
never reads ``agenda_role``, a clue's ``points_to``, the Watch's tally or
whether an ending is eligible: every door is taken because the card or the
gangplank OFFERED it. The table below reads the rest, afterwards.

WHAT IS REAL AND WHAT IS NOT. As scripts/simulate_acts.py: every walk,
purchase, case, burgle, stage, flashback, lift, shift, bargain, discharge,
encounter approach, fine, sentence, set piece and card goes through
``tool_dispatcher.execute_intent``; after every action the director deals what
is due (``director.ensure_scene``) and the quest machine runs, as the turn's
end runs them. Boarding the barge is the ``flag`` intent a chosen option
carries (``nf_boarded_the_evening_barge``), taken only when the engine offers
it -- the stage withholds it while a refusal holds, and the harness reads that
refusal (``QuestEngine.stage_refusal``) as the narrator would. What is NOT the
game, and says so: the thief is fed and rested every few hours
(``Burglar.wait_until``), and the burgling policies are handed the price of
a set of lockpicks on day one (``KIT_PURSE``).

A RUN ENDS when an ending locks (``endings.locked``), or at the morning after
the fair's last day + ``DAYS_AFTER_THE_FAIR`` with nothing locked ("none").
The fair's days are read from the loaded schedules (``fair_days``), so a
tuned fair moves the horizon with it.

AGENDAS ARE ON (as simulate_acts.py): the Magpie's robberies are the spine,
and Silas Crook's rise is The Dapper's City.

WHAT IT REPORTS, per policy, over the seeds:

  endings         the share of runs that locked each ending (and none), the
                  door it locked through, and the day it locked (mean, and
                  every day seen)
  first eligible  the share of runs where each earned ending was eligible at
                  the end of some day, and the mean first such day -- how
                  EARLY an ending could have ended the run, whatever the
                  policy chose (Guildmaster before Act III; the barge)
  fair            runs that stood on the Green during the fair, and the day;
                  runs held at any hour of the fair; The Rope by the gallows
                  and by a death in the cells
  jailbreak       tries, escapes, runs that tried
  heist           runs that tried the heart, lifted it, got it home
  barge           runs that asked, times asked, times refused and why (the
                  stage's own refusals, in their order: a theft, a squeeze, own deeds, a fence's
                  debt, no wage, the heart), runs that boarded
  law             arrests, days served, runs with a death (respawns)
  trail           runs unmasked / partnered, and the mean day

Usage:
    python scripts/simulate_endings.py                        # 40 seeds, every policy
    python scripts/simulate_endings.py --policy loyalist --seeds 10
    python scripts/simulate_endings.py --json
    python scripts/simulate_endings.py --fair-day 8          # try the fair two days earlier
    python scripts/simulate_endings.py --break-out none      # nobody breaks out

Version: v0.1.2 [2026-09-28] -- fix round 2: the Hill's night from 20:00, the barge's `squeeze`
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts import simulate_acts, simulate_jobs, simulate_law  # noqa: E402
from scripts.simulate_acts import Investigator  # noqa: E402

POLICIES = ("investigator_a", "investigator_b", "investigator_c", "lantern", "partner",
            "heister", "loyalist", "dapper", "porter", "reckless", "runner")
#: The barge choice each policy takes when ``--opening`` names none: the
#: investigators one each; the others talk their way off (``b``) -- the
#: reckless thieves run (``a``), and the lamplighter comes quietly (``c``).
OPENINGS = {"investigator_a": "a", "investigator_b": "b", "investigator_c": "c",
            "lantern": "c", "partner": "b", "heister": "b", "loyalist": "b",
            "dapper": "b", "porter": "b", "reckless": "a", "runner": "a"}
#: Policies that burgle, and so are handed the lockpicks' price on day one.
BURGLE = ("investigator_a", "investigator_b", "investigator_c", "lantern", "partner",
          "heister", "loyalist")
#: The run's horizon: the morning after the fair's last day + this many days.
DAYS_AFTER_THE_FAIR = 2
#: The hour a day's night ends (Burglar.next_morning wakes at eight).
MORNING = 8
FAIR = "hanging_fair"
GALLOWS_DECK = "the_gallows"
GREEN = "gallows_green"
HOME = "the_snuffs"
DOCKS = "tallow_docks"
MARKET = "wickmarket"
SILK_ROW = "silk_row"
HILL = "margraves_hill"
#: The partners' last job after the fair (the_last_job.yaml: 20:00-05:00).
HILL_HOUR = 20
HILL_DAWN = 5
KIT_PURSE = simulate_acts.KIT_PURSE
#: Wren's round (labour.yaml `lamplighting`: from 18:00, in Wickmarket).
LAMP_HOUR = 18
#: The lamplighter stops casing in time to be at Wren's round by dusk.
LANTERN_CASING_ENDS = 17
#: Dock Mag's gangs (labour.yaml `dock_portering`: 05:00-13:00).
QUAY_HOUR = 6
#: The evening barge's window (the_evening_barge.yaml: 17:00-22:00).
BARGE_HOUR = 17
BOARD = "nf_boarded_the_evening_barge"
BARGE_QUEST = "the_evening_barge"
#: The stage's refusals, in their order (the_evening_barge.yaml; `stole`
#: first since T8's fix round 1, `squeeze` second since fix round 2).
BARGE_REFUSALS = ("stole", "squeeze", "own_deeds", "fence_debt", "no_wage", "the_heart")
#: The suspects' doors (the_confrontation.yaml): Lady Imelda's parlour on
#: Silk Row of an afternoon, and the Snuffs by night for Wren and Silas.
IMELDA_HOUR = 16
SNUFFS_DOOR_HOUR = 21
HEISTER_JOBS = simulate_jobs.JOBS_PER_RUN
CAREFUL_INTEL = simulate_jobs.CAREFUL_INTEL
#: The loyalist's oath, every card answered with a roll (initiation.yaml).
LOYALIST_OATH = ("own_the_name", "stare_down_the_doorman", "sing_the_third_verse")
GANNET_JOB = "gannet_silk_row"
#: Answers every policy gives when a card offers it and the policy wants
#: nothing else from it: the alibi presented, and the answers that leave an
#: ending's door shut (so no run ends where its policy did not choose to).
PRESENT = ("present_it",)
DECLINE = ("watch_it_shine", "keep_out_of_it", "not_yet", "leave_it", "let_it_lie",
           "walk_away")
#: A lock's door when no card was on the table (a quest's on_complete, or
#: death.yaml's terminal).
QUEST_DOORS = {"honest_after_all": "quest:the_evening_barge",
               "the_legend": "quest:the_heart_goes_home"}


class Over(Exception):
    """An ending locked: the run is over."""


@dataclass
class EndRun:
    seed: int
    policy: str
    opening: str
    ending: str = ""                 # "" = nothing locked by the horizon
    ending_day: Optional[int] = None
    ending_hour: Optional[float] = None
    door: str = ""
    first_eligible: dict[str, int] = field(default_factory=dict)
    fair_day: Optional[int] = None   # first day on the Green during the fair
    held_at_fair: bool = False
    arrests: int = 0
    days_served: int = 0
    deaths: int = 0
    break_out_tries: int = 0
    escapes: int = 0
    heist_tried: bool = False
    heist_lifted: bool = False
    barge_tries: int = 0
    barge_refusals: dict[str, int] = field(default_factory=dict)
    unmasked_day: Optional[int] = None
    partnered_day: Optional[int] = None
    guild_standing_at_fair: Optional[int] = None


def fair_days() -> tuple[int, int]:
    """The Hanging Fair's first and last day, read off the loaded schedules."""
    from engine.world import schedules

    spec = schedules.load_schedules()["events"][FAIR]
    first = int(spec["on_day"])
    return first, first + int(spec["duration_days"]) - 1


def set_fair_day(day: int) -> None:
    """``--fair-day N``: move the LOADED fair to begin on day ``N``, for this
    process only, and the gallows' last morning with it (the_gallows.yaml's
    ``min_day`` is the fair's last day; tests/test_hue_and_cry.py holds the
    two files together). The interrogation's bill (``the_fair_coming``, from
    day 7) is not moved: no policy here reads it."""
    from engine.content import deck
    from engine.world import schedules

    spec = schedules.load_schedules()["events"][FAIR]
    spec["on_day"] = int(day)
    path = deck._decks_dir() / f"{GALLOWS_DECK}.yaml"
    raw = deck._read_deck(str(path), path.stat().st_mtime)
    clauses = [c for c in raw["when"]["all"] if "min_day" in c]
    assert len(clauses) == 1, raw["when"]
    clauses[0]["min_day"] = fair_days()[1]


class Ender(Investigator):
    """One run for one ending: simulate_acts.py's investigator's turn -- the
    hand dealt and answered after every action -- with the policy's answers
    (``PREFER``) and its day (``day``)."""

    #: Beats this policy takes whenever a card offers them, in order.
    PREFER: tuple[str, ...] = ()

    def __init__(self, seed: int, policy: str, opening: str) -> None:
        super().__init__(seed, opening)
        self.end = EndRun(seed=seed, policy=policy, opening=opening)
        # simulate_law's jailbreak count lives on its own Run; simulate_jobs'
        # Run (the investigator's) has none, so it is given one here.
        self.run.break_out = {}  # type: ignore[attr-defined]
        self._door_card = ""
        self.first, self.last = fair_days()
        #: The last day the run is played (a sentence served past it is not).
        self.horizon = self.last + DAYS_AFTER_THE_FAIR

    # -- the calendar a player reads ------------------------------------------

    def fair_on(self) -> bool:
        from engine.game.quests import evaluate_condition

        return bool(evaluate_condition(self.state, {"event_active": FAIR}))

    def fair_over(self) -> bool:
        from engine.game.quests import evaluate_condition

        return (bool(evaluate_condition(self.state, {"event_seen": FAIR}))
                and not self.fair_on())

    def day_no(self) -> int:
        return int(self.state.world_day)

    # -- the hand ----------------------------------------------------------------

    def choose_beat(self, card_id: str, offered: list[str]) -> str:
        for wanted in (*self.PREFER, *PRESENT, *DECLINE, *simulate_acts.ROLL_FREE):
            if wanted in offered:
                return wanted
        return offered[0]

    def answer_card(self) -> None:
        from engine.content import director

        card = director.current_card(self.state)
        self._door_card = card.id if card else ""
        try:
            super().answer_card()
        finally:
            self._door_card = ""

    # -- the run's end -------------------------------------------------------

    def _note(self) -> None:
        super()._note()
        self.observe()

    def observe(self) -> None:
        """What the table reads after every action; raises ``Over`` on a lock."""
        from engine.game import endings
        from engine.world import law

        day = self.day_no()
        # The last day's night is played out to its morning (fix round 1: a
        # partner made on the last night walks up the Hill after midnight).
        if day > self.horizon and self.state.world_hour >= MORNING:
            raise Over
        if self.end.fair_day is None and self.state.flags.get("saw_the_hanging_fair"):
            self.end.fair_day = day
        if self.fair_on() and law.in_custody(self.state):
            self.end.held_at_fair = True
        if self.end.unmasked_day is None and self.state.flags.get("magpie_unmasked"):
            self.end.unmasked_day = day
        if self.end.partnered_day is None and self.state.flags.get("partners_with_the_magpie"):
            self.end.partnered_day = day
        locked = endings.locked(self.state)
        if locked != endings.NONE_ID:
            if locked != endings.fail_forward_id():
                self.end.first_eligible.setdefault(locked, day)
            if not self.end.ending:
                self.end.ending = locked
                self.end.ending_day = day
                self.end.ending_hour = round(float(self.state.world_clock_hours), 2)
                self.end.door = (f"card:{self._door_card}" if self._door_card
                                 else QUEST_DOORS.get(locked, "death"))
            raise Over

    def wait_until(self, hour: int) -> None:
        super().wait_until(hour)
        self.observe()

    def linger(self, hours: float = 1.0) -> None:
        super().linger(hours)
        self.observe()

    def end_of_day(self) -> None:
        """Which endings the day left eligible (a reading, never a choice)."""
        from engine.game import endings

        day = self.day_no()
        for ending_id in endings.eligible(self.state).eligible:
            if ending_id != endings.fail_forward_id():
                self.end.first_eligible.setdefault(ending_id, day)
        if day == self.first and self.end.guild_standing_at_fair is None:
            self.end.guild_standing_at_fair = int(
                self.state.reputations.get("honest_company", 0))

    def next_morning(self) -> None:
        self.end_of_day()
        super().next_morning()

    # -- the stop and the cell -----------------------------------------------

    def leave_custody(self) -> None:
        from engine.world import law

        before = len(self.run.days_served)
        super().leave_custody()
        if len(self.run.days_served) > before:
            self.end.days_served += self.run.days_served[-1]
        if law.in_custody(self.state):
            # A sentence stopped for the gallows (law.serve_sentence's
            # `interrupted_by`): the hand it stopped for is dealt now.
            self.look()

    # -- composite moves -----------------------------------------------------

    def to_the_green(self) -> None:
        """Onto Gallows Green: the fair deck deals on arrival. Standing there
        already, step off and back, as a player would to see what is new
        (the deck re-arms when the player leaves the Green)."""
        self.enter(GREEN)

    def enter(self, place: str) -> None:
        """Walk into ``place``; standing there already, step out to the
        first public street and back in: a deck deals on the way in (a
        repeatable one re-arms when the player leaves)."""
        from engine.game.locations import LOCATIONS

        if self.state.location_id == place:
            out = sorted(n for n in (LOCATIONS.get(place) or {}).get("connections") or {}
                         if not (LOCATIONS.get(n) or {}).get("secret"))
            if out:
                self.walk(out[0])
        self.walk(place)

    def work(self, job_id: str) -> bool:
        if job_id not in self.legal_targets("work"):
            return False
        return bool(self.act("work", job_id).get("worked"))

    def quay_shift(self) -> None:
        if self.state.world_hour < QUAY_HOUR:
            self.wait_until(QUAY_HOUR)
        self.walk(DOCKS)
        self.work("dock_portering")

    def lamp_round(self) -> None:
        if self.state.world_hour > LAMP_HOUR:
            return
        self.walk(MARKET)
        if self.state.world_hour < LAMP_HOUR:
            self.wait_until(LAMP_HOUR)
        self.work("lamplighting")

    def try_the_barge(self) -> None:
        """Down to the evening barge, and aboard if the gangplank will have you."""
        from engine.game.quests import QuestEngine, load_quests

        if self.state.world_hour >= 22:
            return
        self.walk(DOCKS)
        if self.state.location_id != DOCKS:
            return
        if self.state.world_hour < BARGE_HOUR:
            self.wait_until(BARGE_HOUR)
        self.end.barge_tries += 1
        if BOARD in self.legal_targets("flag"):
            self.act("flag", BOARD)
            return
        stage = (load_quests().get(BARGE_QUEST) or {}).get("stages", [{}])[0]
        why = QuestEngine.stage_refusal(self.state, stage)
        texts = [str(r.get("text") or "") for r in stage.get("refusals") or []]
        key = next((BARGE_REFUSALS[i] for i, t in enumerate(texts)
                    if t and " ".join(t.split()) == " ".join(why.split())), "other")
        self.end.barge_refusals[key] = self.end.barge_refusals.get(key, 0) + 1

    def evening_in_the_snuffs(self, hour: int = 18) -> None:
        self.walk(HOME)
        if self.state.location_id == HOME and self.state.world_hour < hour:
            self.wait_until(hour)
            self.look()   # a turn spent at the long table

    # -- the run -------------------------------------------------------------

    def first_day(self) -> None:
        """The barge's choice, then (burglars) the lockpicks at Marrow's and
        the initiation at the long table, at 18:00 in the Snuffs."""
        from engine.game.effects import apply_effect

        self.morning()
        arrests = self.run.arrests
        self.take_opening(self.end.opening)
        if self.run.arrests > arrests and not self.acts.arrest_hours:
            self.acts.arrest_hours.append(float(self.state.world_clock_hours))
        self.day_one_work()
        if self.end.policy in BURGLE:
            apply_effect(self.state, {"type": "gold", "delta": KIT_PURSE})
            self.walk(HOME)
            if self.state.world_hour < simulate_acts.MARROW_HOUR:
                self.wait_until(simulate_acts.MARROW_HOUR)
            for item in simulate_acts.KIT:
                if f"npc_marrow/{item}" in self.legal_targets("buy"):
                    self.act("buy", f"npc_marrow/{item}")
            self.look()
        else:
            self.evening_in_the_snuffs(simulate_acts.MARROW_HOUR)
        self.acts.evidence_by_morning.append(0)

    def day_one_work(self) -> None:
        """Anything the policy does on its first day before the Snuffs."""

    def day(self) -> None:
        raise NotImplementedError


class Investigating(Ender):
    """The investigator: the trail, then Cleared."""

    PREFER = ("see_it_done", "hear_it_said", "name_them")

    def day(self) -> None:
        from engine.world import law

        if law.in_custody(self.state):
            self.leave_custody()
        if not self.state.flags.get("magpie_unmasked"):
            self.work_the_day()
        if self.state.flags.get("magpie_unmasked"):
            self.cleared()

    def cleared(self) -> None:
        if self.fair_on():
            self.to_the_green()
        elif self.fair_over():
            self.at_the_desk()

    def at_the_desk(self) -> None:
        """The front desk in the captain's hours, whatever the investigator
        has to show: the desk deals what it will."""
        from engine.world import law

        self.enter(simulate_acts.DESK)
        if self.state.location_id != simulate_acts.DESK or law.in_custody(self.state):
            return
        hour = self.state.world_hour
        if any(a <= hour < b for a, b in simulate_acts.ARDANE_WINDOWS):
            self.look()
        else:
            self.visit_desk()


class Lantern(Investigating):
    """The investigator on Wren's lamp round every dusk, for the badge."""

    CASING_ENDS = LANTERN_CASING_ENDS
    PREFER = ("take_the_badge", "name_them")

    def choose_beat(self, card_id: str, offered: list[str]) -> str:
        # It waits for the badge as long as the run lasts, and on its last
        # day hears its name cleared at the desk instead.
        if card_id == "D4_cleared_at_the_desk" and self.day_no() >= self.horizon:
            return "hear_it_said"
        return super().choose_beat(card_id, offered)

    def day_one_work(self) -> None:
        self.lamp_round()

    def day(self) -> None:
        from engine.world import law

        if law.in_custody(self.state):
            self.leave_custody()
        if not self.state.flags.get("magpie_unmasked"):
            self.work_the_day()
        self.lamp_round()
        if self.state.flags.get("magpie_unmasked") or self.has_business_at_the_desk():
            self.at_the_desk()


class Partner(Investigating):
    """The investigator who takes the trail to the Magpie's door, not the Watch's."""

    PREFER = ("say_it", "take_it_together")

    def __init__(self, seed: int, policy: str, opening: str) -> None:
        super().__init__(seed, policy, opening)
        self._door_since = -1

    def has_business_at_the_desk(self) -> bool:
        return False

    def trail_done(self) -> bool:
        return bool(self.state.flags.get("partners_with_the_magpie"))

    def day(self) -> None:
        from engine.world import law

        if law.in_custody(self.state):
            self.leave_custody()
        if self.state.flags.get("partners_with_the_magpie"):
            self.the_heart_together()
            return
        self.work_the_day()
        if self.has_business_at_a_door():
            self.at_the_doors()
        if self.state.flags.get("partners_with_the_magpie"):
            self.the_heart_together()

    def the_heart_together(self) -> None:
        """Where the partnership said: the Green while the fair is on, the
        Hill after dark once it is over (the_last_job.yaml, T8 fix round 1)."""
        from engine.world import law

        if self.fair_on():
            self.to_the_green()
        elif self.fair_over():
            self.walk(HILL)
            if self.state.location_id == HILL and not law.in_custody(self.state):
                if HILL_DAWN <= self.state.world_hour < HILL_HOUR:
                    self.wait_until(HILL_HOUR)
                self.look()

    def has_business_at_a_door(self) -> bool:
        return (self.evidence() >= simulate_acts.gate()
                and len(self.acts.clue_days) > self._door_since)

    def at_the_doors(self) -> None:
        """Lady Imelda's parlour of an afternoon, then the Snuffs by night:
        whichever door the trail leads to deals its card there."""
        from engine.world import law

        self._door_since = len(self.acts.clue_days)
        if self.state.world_hour < IMELDA_HOUR + 2:
            self.walk(SILK_ROW)
            if self.state.location_id == SILK_ROW and not law.in_custody(self.state):
                if self.state.world_hour < IMELDA_HOUR:
                    self.wait_until(IMELDA_HOUR)
                self.look()
        if self.state.flags.get("partners_with_the_magpie") or law.in_custody(self.state):
            return
        self.walk(HOME)
        if self.state.location_id == HOME and not law.in_custody(self.state):
            if 5 <= self.state.world_hour < SNUFFS_DOOR_HOUR:
                self.wait_until(SNUFFS_DOOR_HOUR)
            self.look()


class Heister(Ender):
    """A careful burglar until the fair, then the heart."""

    PREFER = ("lift_the_heart",)

    def __init__(self, seed: int, policy: str, opening: str) -> None:
        super().__init__(seed, policy, opening)
        self.jobs_done = 0
        self._tried: set[str] = set()

    def choose_beat(self, card_id: str, offered: list[str]) -> str:
        beat = super().choose_beat(card_id, offered)
        if beat == "lift_the_heart":
            self.end.heist_tried = True
        return beat

    def day(self) -> None:
        from engine.game.inventory import holds
        from engine.world import law

        if law.in_custody(self.state):
            self.leave_custody()
        if holds(self.state, "everflame_heart"):
            self.walk(HOME)
            return
        if self.fair_on() and not self.end.heist_tried:
            self.to_the_green()
            if holds(self.state, "everflame_heart"):
                self.end.heist_lifted = True
                self.walk(HOME)
            return
        if self.day_no() < self.first and self.jobs_done < HEISTER_JOBS:
            self.one_job()
            return
        self.walk(HOME)

    def one_job(self) -> None:
        options = [p for p in self.candidates(simulate_jobs._small)
                   if str(p["id"]) not in self._tried]
        prem = simulate_jobs._pick(options, self.run.seed, self.jobs_done)
        self.jobs_done += 1
        if prem is None:
            return
        self._tried.add(str(prem["id"]))
        self.walk(str(prem["district"]))
        if self.state.location_id != prem["district"]:
            return
        self.case_until(str(prem["id"]), CAREFUL_INTEL)
        if self.wait_for_empty(str(prem["id"])):
            self.burgle(prem, smart=True, walk_away=True)


class Loyalist(Ender):
    """The Company's own, for Mother Gannet's needles."""

    PREFER = (*LOYALIST_OATH, "take_the_chair", "stand_against_him")

    def __init__(self, seed: int, policy: str, opening: str) -> None:
        super().__init__(seed, policy, opening)
        self._silas_answered = False

    def choose_beat(self, card_id: str, offered: list[str]) -> str:
        if card_id == "F4_silas_makes_his_move":
            self._silas_answered = True
        return super().choose_beat(card_id, offered)

    def day(self) -> None:
        from engine.world import law

        if law.in_custody(self.state):
            self.leave_custody()
        if self.fair_on() and not self._silas_answered:
            self.to_the_green()
        self.quay_shift()
        self.gannets_job()
        self.evening_in_the_snuffs()

    def gannets_job(self) -> None:
        """Struck at her table, a Silk Row house emptied, the job paid."""
        from engine.game import threads

        mine = [t for t in self.state.threads if t.get("template") == GANNET_JOB]
        if not mine:
            self.walk(HOME)
            if GANNET_JOB in self.legal_targets("bargain"):
                self.act("bargain", GANNET_JOB)
            mine = [t for t in self.state.threads if t.get("template") == GANNET_JOB]
        open_ = [t for t in mine if t.get("status") == threads.STATUS_ACTIVE]
        if not open_:
            return
        thread_id = str(open_[0]["id"])
        if thread_id not in self.legal_targets("discharge"):
            self.silk_row_job()
        if thread_id in self.legal_targets("discharge"):
            self.act("discharge", thread_id)

    def silk_row_job(self) -> None:
        from engine.world import jobs, premises

        robbed = set(jobs.robbed(self.state))
        houses = sorted((p for p in premises.at(self.state, SILK_ROW)
                         if not p.get("anchor") and str(p["id"]) not in robbed),
                        key=lambda p: (int(p.get("tier") or 0), str(p["id"])))
        if not houses:
            return
        prem = houses[0]
        self.walk(SILK_ROW)
        if self.state.location_id != SILK_ROW:
            return
        self.case_until(str(prem["id"]), CAREFUL_INTEL)
        if self.wait_for_empty(str(prem["id"])):
            self.burgle(prem, smart=True, walk_away=True)


class Porter(Ender):
    """Honest work, the fair, and the evening barge."""

    def day_one_work(self) -> None:
        self.quay_shift()

    def day(self) -> None:
        from engine.world import law

        if law.in_custody(self.state):
            self.leave_custody()
        if self.fair_on() and self.end.fair_day is None:
            self.to_the_green()
        self.quay_shift()
        if self.fair_on() or self.fair_over():
            self.try_the_barge()
        else:
            self.lamp_round()
        self.evening_in_the_snuffs()


class Dapper(Porter):
    """A sworn porter who likes the look of a plum ribbon."""

    PREFER = ("stand_with_him",)

    def day(self) -> None:
        from engine.world import law

        if law.in_custody(self.state):
            self.leave_custody()
        if self.fair_on():
            self.to_the_green()
        self.quay_shift()
        self.lamp_round()
        self.evening_in_the_snuffs()


class Reckless(Ender):
    """The reckless pickpocket; held, it breaks out if it can."""

    break_out = True

    def day(self) -> None:
        from engine.world import law

        if law.in_custody(self.state):
            self.leave_custody()
        simulate_law._reckless_day(self, self.day_no())


class Runner(Reckless):
    """The reckless pickpocket after one honest shift, down to the barge every evening."""

    def day_one_work(self) -> None:
        self.quay_shift()

    def day(self) -> None:
        super().day()
        self.try_the_barge()


CLASSES = {"investigator_a": Investigating, "investigator_b": Investigating,
           "investigator_c": Investigating, "lantern": Lantern, "partner": Partner,
           "heister": Heister, "loyalist": Loyalist, "dapper": Dapper, "porter": Porter,
           "reckless": Reckless, "runner": Runner}


def play(seed: int, policy: str, opening: str = "") -> EndRun:
    with simulate_law.counting_deaths():
        return _play(seed, policy, opening or OPENINGS[policy])


def _play(seed: int, policy: str, opening: str) -> EndRun:
    p = CLASSES[policy](seed, policy, opening)
    try:
        p.first_day()
        while True:
            p.next_morning()
            if p.day_no() > p.horizon:
                break
            started = p.state.world_clock_hours
            p.day()
            if p.state.world_clock_hours <= started + 1e-9:
                p.wait_until(7)   # a day with nothing to do: slept through
    except Over:
        pass
    end = p.end
    end.arrests = int(p.run.arrests)
    end.deaths = simulate_law.deaths(p.state)
    jail = p.run.break_out  # type: ignore[attr-defined]
    end.break_out_tries = int(jail.get("attempts", 0))
    end.escapes = int(jail.get("escapes", 0))
    return end


# ---------------------------------------------------------------------------
# The table
# ---------------------------------------------------------------------------


def _mean(values: list[float]) -> Optional[float]:
    return round(statistics.fmean(values), 2) if values else None


def _share(n: int, of: int) -> float:
    return round(n / of, 3) if of else 0.0


def declared_endings() -> list[str]:
    from engine.game import endings

    return list(endings.declared())


def summarise(runs: list[EndRun]) -> dict[str, Any]:
    n = len(runs)
    ids = declared_endings()
    endings_seen = {e: [r for r in runs if r.ending == e] for e in ids}
    return {
        "seeds": n,
        "opening": runs[0].opening if runs else "",
        "fair": list(fair_days()),
        "endings": {**{e: _share(len(rs), n) for e, rs in endings_seen.items() if rs},
                    "none": _share(sum(not r.ending for r in runs), n)},
        "lock_day": {e: _mean([float(r.ending_day) for r in rs])
                     for e, rs in endings_seen.items() if rs},
        "lock_days": {e: {str(d): sum(r.ending_day == d for r in rs)
                          for d in sorted({r.ending_day for r in rs})}
                      for e, rs in endings_seen.items() if rs},
        "doors": {e: {d: sum(r.door == d for r in rs) for d in sorted({r.door for r in rs})}
                  for e, rs in endings_seen.items() if rs},
        "first_eligible": {e: {"share": _share(sum(e in r.first_eligible for r in runs), n),
                               "mean_day": _mean([float(r.first_eligible[e]) for r in runs
                                                  if e in r.first_eligible])}
                           for e in ids if any(e in r.first_eligible for r in runs)},
        "fair_arrived": _share(sum(r.fair_day is not None for r in runs), n),
        "fair_arrived_day": _mean([float(r.fair_day) for r in runs if r.fair_day is not None]),
        "held_at_fair": _share(sum(r.held_at_fair for r in runs), n),
        "rope_by_gallows": sum(r.ending == "the_rope" and r.door.startswith("card:")
                               for r in runs),
        "rope_by_death": sum(r.ending == "the_rope" and r.door == "death" for r in runs),
        "arrests_per_run": _mean([float(r.arrests) for r in runs]),
        "days_served_per_run": _mean([float(r.days_served) for r in runs]),
        "runs_with_a_death": _share(sum(r.deaths > 0 for r in runs), n),
        "jailbreak": {"runs_tried": _share(sum(r.break_out_tries > 0 for r in runs), n),
                      "tries": sum(r.break_out_tries for r in runs),
                      "escapes": sum(r.escapes for r in runs)},
        "heist": {"tried": _share(sum(r.heist_tried for r in runs), n),
                  "lifted": _share(sum(r.heist_lifted for r in runs), n),
                  "home": _share(sum(r.ending == "the_legend" for r in runs), n)},
        "barge": {"runs_asked": _share(sum(r.barge_tries > 0 for r in runs), n),
                  "asked": sum(r.barge_tries for r in runs),
                  "refused": {k: sum(r.barge_refusals.get(k, 0) for r in runs)
                              for k in (*BARGE_REFUSALS, "other")
                              if any(r.barge_refusals.get(k) for r in runs)},
                  "runs_refused_for_a_theft": _share(
                      sum(bool(r.barge_refusals.get("stole")) for r in runs), n),
                  "runs_refused_for_own_deeds": _share(
                      sum(bool(r.barge_refusals.get("own_deeds")) for r in runs), n),
                  "boarded": _share(sum(r.ending == "honest_after_all" for r in runs), n)},
        "unmasked": _share(sum(r.unmasked_day is not None for r in runs), n),
        "unmasked_mean_day": _mean([float(r.unmasked_day) for r in runs
                                    if r.unmasked_day is not None]),
        "partnered": _share(sum(r.partnered_day is not None for r in runs), n),
        "partnered_mean_day": _mean([float(r.partnered_day) for r in runs
                                     if r.partnered_day is not None]),
        "guild_standing_at_fair": _mean([float(r.guild_standing_at_fair) for r in runs
                                         if r.guild_standing_at_fair is not None]),
    }


def measure(policy: str, seeds: int, opening: str = "") -> dict[str, Any]:
    return summarise([play(seed, policy, opening) for seed in range(seeds)])


def reach(reports: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Each declared ending: the policies that reached it, and the best rate."""
    out = {}
    for ending_id in declared_endings():
        rates = {p: r["endings"].get(ending_id, 0.0) for p, r in reports.items()}
        best = max(rates.values(), default=0.0)
        out[ending_id] = {"best": best,
                          "best_policy": next((p for p, v in rates.items() if v == best and v),
                                              ""),
                          "policies": sorted(p for p, v in rates.items() if v)}
    return out


def render(policy: str, r: dict[str, Any]) -> str:
    lines = [f"{policy} (opening {r['opening']}): {r['seeds']} seeds, fair days "
             f"{r['fair'][0]}-{r['fair'][1]}"]
    for e, share in r["endings"].items():
        extra = ""
        if e in r["lock_day"]:
            extra = (f"  locks day {r['lock_day'][e]} {r['lock_days'][e]}  via "
                     f"{r['doors'][e]}")
        lines.append(f"  {e:18} {share:>6.0%}{extra}")
    lines.append("  first eligible   " + ", ".join(
        f"{e} {v['share']:.0%} (day {v['mean_day']})" for e, v in r["first_eligible"].items()))
    lines.append(f"  fair             on the Green {r['fair_arrived']:.0%} (day "
                 f"{r['fair_arrived_day']}); held during it {r['held_at_fair']:.0%}; the Rope "
                 f"by the gallows {r['rope_by_gallows']}, by a death {r['rope_by_death']}")
    lines.append(f"  law              arrests/run {r['arrests_per_run']}, days served/run "
                 f"{r['days_served_per_run']}, runs with a death {r['runs_with_a_death']:.0%};"
                 f" jailbreak {r['jailbreak']}")
    lines.append(f"  heist            {r['heist']}")
    lines.append(f"  barge            {r['barge']}")
    lines.append(f"  trail            unmasked {r['unmasked']:.0%} (day {r['unmasked_mean_day']}),"
                 f" partnered {r['partnered']:.0%} (day {r['partnered_mean_day']});"
                 f" Company standing on the fair's first night {r['guild_standing_at_fair']}")
    return "\n".join(lines)


def render_reach(rows: dict[str, dict[str, Any]]) -> str:
    lines = ["reach: each ending's best rate over the policies"]
    for e, row in rows.items():
        lines.append(f"  {e:18} {row['best']:>6.0%}  {row['best_policy'] or '-':15}"
                     f" reached by {row['policies']}")
    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--seeds", type=int, default=40)
    parser.add_argument("--policy", choices=(*POLICIES, "all"), default="all")
    parser.add_argument("--opening", choices=("a", "b", "c"), default=None,
                        help="every policy takes this barge choice (default: its own)")
    parser.add_argument("--fair-day", type=int, default=None,
                        help="try the fair on another first day (the loaded schedules only)")
    parser.add_argument("--break-out", choices=("policy", "all", "none"), default="policy",
                        help="who tries the jailbreak when held: the reckless thieves (policy),"
                             " every policy, or nobody (the control)")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if args.break_out != "policy":
        for cls in set(CLASSES.values()):
            cls.break_out = args.break_out == "all"

    import logging

    logging.disable(logging.WARNING)
    from engine.games import registry

    registry.activate("hue-and-cry")
    if args.fair_day is not None:
        set_fair_day(args.fair_day)
    policies = POLICIES if args.policy == "all" else (args.policy,)
    reports = {p: measure(p, args.seeds, args.opening or "") for p in policies}
    rows = reach(reports)
    if args.json:
        print(json.dumps({"policies": reports, "reach": rows}, indent=2))
    else:
        print("\n\n".join([*(render(p, r) for p, r in reports.items()), render_reach(rows)]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
