"""
The Cost-of-Living Harness
==========================

Play HUE & CRY headlessly with four ways of getting by, each paying for its
own bread and bed, and report how many days each one actually keeps (AGENTS.md
rule 10: labour pay is set by measurement, not guessed). It is also the
reproducible cost-of-living measurement v0.14's survival task took from a
scratch script: every policy here eats and sleeps on its own coin, and the
harness never feeds it or restores its stamina.

FOUR POLICIES, the same seeds, the same rules of living:

  porter     Honest work and nothing else. Up at six, on the quay by seven
             for Dock Mag's gangs (`dock_portering`, six hours), then over to
             Wickmarket to go round the lamps with Wren at dusk
             (`lamplighting`) -- the day's two shifts (labour.yaml
             `shifts_per_day`). It never lifts a purse.
  dipper     The other honest day: bread on the quay, then the vats at Marsh &
             Daughters on Chandlers' Rise (`candle_dipping`, six hours), then
             the Wickmarket stalls' errands until they shut
             (`market_errands`).
  careful    simulate_law's careful pickpocket: the porter's smock on day one,
             then one purse a night in the Snuffs at 21:00, the goods sold to
             Marrow across the yard the same hour. Stops are run from, and a
             fine is paid if the purse covers it.
  scrounger  simulate_scrounge's scrounger: four streets a day, what it finds
             eaten or sold. It never steals and never works.

AND TWO MORE, the careful pickpocket on credit (v0.15, the fences' credit,
data/rules/threads.yaml) -- the same day, the same purse, plus one line of
credit it runs whenever a fence will stand it one and its purse is under
``CREDIT_WHEN_BELOW``, and repays at her counter the moment it holds the
debt:

  careful_pell    Pell Hollis's advance (ten crowns, thirteen back inside
                  three days): after breakfast on the quay, on a day it has
                  business with her (a debt open, or a lean purse), it goes
                  by her counter in Wickmarket, buys its bread there, then
                  on to the Snuffs as before.
  careful_marrow  Marrow's slate (five crowns, eight back inside two), at
                  her yard in the Snuffs after the night's sale, on a day it
                  has business with her.

AND FOUR MORE (v0.18 T3), the two questions the owner's v0.14 and v0.15
decisions left open:

  careful_porter  the careful pickpocket who takes a porter's shift when
                  hungry: its day, plus Dock Mag's six hours on a morning
                  it is still `hungry` after breakfast or holds less than a
                  night's bed and the next day's bread (``CREDIT_WHEN_BELOW``).
  burglar         the fencing burglar (``FencingBurglar``): one tier-1/2
                  house a day, cased and waited on until empty, burgled the
                  careful way, and the haul SOLD -- to Pell Hollis at eight
                  the next morning, to Marrow at five -- to live on. It buys
                  lockpicks once it can spare them. The only policy in any
                  harness that turns loot into bread.
  burglar_pell    the burglar, taking Pell's advance when its purse is lean
                  and never repaying it -- a WELSHER, as the owner's v0.15
                  decision named it: shut out of both fences once the line
                  breaks, so its later hauls stay in its pockets
                  (``loot_unsold``).
  burglar_marrow  the same, on Marrow's slate.

Every run also reads, since v0.18 T3, how each death happened
(``simulate_law.cause_of_death``: hunger, the street, custody, the fair's
terminal death, a job, a card) and on which day, and which endings the table
held open when the run was over.

``--no-credit`` runs them as their own control: the same lean-purse days at
her counter, the same bread bought there, and no line ever struck -- because
a detour past a food counter feeds a careful pickpocket by itself (the plain
``careful`` policy passes none after breakfast), the credit's own effect is
the difference between a credit policy and its control, not between it and
``careful``.

A debt it cannot find by the due day breaks: the word goes round, and NO
fence buys from it or stands it credit again, and that fence's collectors
walk the streets for it (streets.yaml `pells_collectors`, `marrows_lads`,
and by day in the fences' districts `..._by_day`) -- counted in
``collectors_met``. It never sets the
advance aside to repay it: a purses-only earner (~1.4 cr a day against
~1.6 of bread and bed) could repay only by not spending the advance at
all, which leaves it exactly where the control is, three crowns poorer.

THE RULES OF LIVING, the same for all four. Whenever it stands at a food
counter it buys the cheapest food until it carries ``STOCK`` meals (one crown
each, while it has the crowns); it eats a carried meal whenever hunger reaches
``EAT_AT``; and it sleeps in the Snuffs in the bed ``--bed`` names --
``flophouse`` (Old Nance's, 1 cr; the default, because bread plus a flophouse
bed is the cost of living the labour table was tuned against), ``bunk`` (the
Porters' Hall, free to the Company's sworn while it has no quarrel with you) or
``rough``. A bed it cannot pay for is a rough night (survival.yaml's
fallback), never a refusal.

THE OATH, A HARNESS STEP (v0.16). The guild bunk waits for the Honest
Company's oath (`guild_initiated`, games/hue-and-cry/data/scenes/
initiation.yaml), which a player takes when ``run_turn`` deals the initiation
deck -- and this harness drives intents, not turns, so nothing would ever deal
it. So the ``bunk`` policy takes it the way a player does: the first night it
comes home to the Snuffs while Mother Gannet holds court (18:00-04:00),
the deck is dealt (``director.ensure_scene``, as ``run_turn`` calls it) and every card is
answered through the ``card`` verb with its roll-free answer (``ROLL_FREE``),
so the oath draws nothing from the check stream the day's lifts and shifts
roll on. The other beds never deal it: their runs are exactly as before.
Every policy reports ``initiation_due_day``, the first day it stood where a
played turn would have been dealt the deck (the Snuffs, free, Gannet at the
long table).

Every walk, shift, lift, sale, purchase, meal and night goes through
``tool_dispatcher.execute_intent``, the production channel a chosen option
takes, exactly as scripts/simulate_law.py drives its thief (this reuses its
``Thief`` and patrol, and runs with agendas off for the same reason: the
Magpie robbing on your name measures the Magpie; ``--agendas`` turns them on).

WHAT IT REPORTS, per policy, averaged over seeds:

  earned_per_day   crowns in: wages, lifted coin, sales
  food_per_day     crowns spent on food
  bed_per_day      crowns spent on beds
  fed_days         share of days that ended below `hungry`
  bed_nights       share of nights under a roof (a paid or granted bed)
  kept_days        share of days that were both -- the "days sustainable"
  saved_per_day    crowns in hand at the end less the purse it started with
  end_gold         crowns in hand at the end, mean (and min)
  min_hp           the lowest hp any seed reached
  runs_at_zero_hp  the share of seeds whose hp reached 0 -- since v0.17 a
                   death, which respawns (death.yaml): counted as it happens
                   (simulate_law.counting_deaths), not sampled
  deaths_per_run   those deaths, mean per run
  arrests          mean per run
  credit_struck    lines of credit struck, mean per run (the credit policies)
  credit_repaid    of those, the share paid off
  credit_broken    of those, the share that came due unpaid
  collectors_met   times a fence's collectors met it on the street, per run
  collectors_hp_lost  hp those meetings cost it, per run
  initiation_due_day  mean first day a played turn would have dealt the
                   initiation (v0.16); `initiated` the share sworn (bunk only)
  kept_days_per_run  kept days counted as DAYS a run (v0.15's credit tables)
  death_causes     deaths a run by cause; ``deaths_by_day`` all runs' deaths
                   by the day they fell on; ``first_death_day`` (v0.18 T3);
                   ``deaths_penniless`` the share with no coin in hand,
                   ``death_gold_mean`` and ``death_places`` (fix round 2)
  jobs_per_run     the burglars: houses opened, ``hauls_per_run`` carried
                   out, ``loot_taken_per_run`` its registry value,
                   ``fenced_per_run`` crowns the counters paid for stolen
                   units (not every sale), and
                   ``loot_unsold`` the stolen goods' value still carried at
                   the end (``loot_unsold_items``, ``runs_with_loot_unsold``);
                   ``kit_bought`` the share that bought lockpicks
  endings_eligible the share of runs each ending was open at the end
                   (``endings_locked`` any locked)

Usage:
    python scripts/simulate_labour.py                    # 40 seeds x 10 days, every policy
    python scripts/simulate_labour.py --policy burglar_pell --days 14   # v0.18 T3
    python scripts/simulate_labour.py --policy porter --bed bunk
    python scripts/simulate_labour.py --policy careful_pell
    python scripts/simulate_labour.py --policy careful_pell --no-credit   # its control
    python scripts/simulate_labour.py --json
    python scripts/simulate_labour.py --endings --days 12 --agendas   # v0.17 T5

ENDINGS I (v0.17 T5), ``--endings``: instead of the living table, the share
of seeds at the end of days 3/5/8/10/12 whose state holds what v0.17's
earned endings read -- A Lantern's standing (``lamps_kept``), Honest After All's
clauses (your own record clean, ``own_record_clean``, and for comparison the
whole file, ``whole_file_clean``; ``square_with_fences``; ``wage_earned``)
and Honest After All itself. The endings.yaml and CHANGELOG tables come from
it; run it with ``--agendas`` to let the Magpie rob on your name.

ENDINGS II (v0.17 T6) adds two keys: ``hall_trusts`` (the Honest Company's
standing at Guildmaster's ``GUILD_STANDING``) and ``silas_won`` (Silas
Crook's rise complete and not stood against). Guildmaster's number comes from
``--endings --policy porter --bed bunk --agendas``: a sworn porter, Silas on.

Version: v0.6.0 [2026-09-29] -- v0.18 T3: the fencing burglar, the adaptive pickpocket, deaths by cause
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, Optional

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts import simulate_law, simulate_scrounge  # noqa: E402
from scripts.simulate_jobs import Burglar  # noqa: E402
from scripts.simulate_law import Thief, agendas_off  # noqa: E402
from scripts.simulate_scrounge import Scrounger  # noqa: E402

POLICIES = ("porter", "dipper", "careful", "scrounger", "careful_pell", "careful_marrow",
            "careful_porter", "burglar", "burglar_pell", "burglar_marrow")
BEDS = {"flophouse": "sleep_flophouse", "bunk": "sleep_guild_bunk", "rough": "sleep_rough"}
HOME = "the_snuffs"
DOCKS = "tallow_docks"
MARKET = "wickmarket"
RISE = "chandlers_rise"
#: Meals carried after a visit to a food counter, while the purse allows.
STOCK = 2
#: Hunger at which a carried meal is eaten (survival.yaml: hungry at 60).
EAT_AT = 50.0
WAKE_HOUR = 6
DUSK_HOUR = 18
#: Things a policy never sells: the careful thief's guise, and food.
KEEP = ("porters_smock",)
ROOFED = ("sleep_flophouse", "sleep_guild_bunk", "sleep_tavern")
#: The initiation deck (v0.16), and the answer the bunk policy gives on each of
#: its cards: the one that asks no dice (a sequence card's only answer is
#: `resolve`). The deck's own test asserts every card carries one.
INITIATION = "initiation"
ROLL_FREE = ("say_nothing", "carry_the_crates", "take_a_bow", "resolve")
#: The credit policies strike a line only while the purse is under this: a
#: day's bread and a flophouse bed (~1.6 cr, CHANGELOG [0.14.0]) and change.
CREDIT_WHEN_BELOW = 3
#: The street scenes that come for a welsher (data/encounters/streets.yaml).
COLLECTORS = ("pells_collectors", "marrows_lads",
              "pells_collectors_by_day", "marrows_lads_by_day")
#: v0.18 T3. The adaptive careful thief takes a porter's shift on a morning
#: its belly or its purse says it must: still `hungry` or worse after
#: breakfast, or under the price of a night's bed and the next day's bread.
HUNGRY = ("hungry", "starving")
#: The fencing burglar's kit, never sold (data/rules/jobs.yaml `tools`), and
#: the price of the picks at Marrow's (economy.yaml): it buys them once it
#: holds that much over a night's bed and the next day's bread.
KIT = ("lockpicks", "smoke_pellet")
LOCKPICKS = "lockpicks"
LOCKPICKS_PRICE = 15
#: Marrow's yard opens at 17:00 (economy.yaml); the burglar sells there on
#: its way to bed. Pell's counter opens at 08:00.
MARROW_OPENS = 17
PELL_OPENS = 8
#: The last hour the burglar waits in a street for a house to empty before
#: it gives the day up and goes to sell and sleep.
JOB_LAST_HOUR = 20
#: The longest the burglar waits without looking at its carried food.
WAIT_STEP_HOURS = 3.0


@dataclass
class Life:
    seed: int
    policy: str
    bed: str
    days: int = 0
    money: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    shifts: int = 0
    wages: int = 0
    fed_days: int = 0
    bed_nights: int = 0
    kept_days: int = 0
    min_hp: int = 999
    min_stamina: int = 999
    start_gold: int = 0
    end_gold: int = 0
    arrests: int = 0
    credit_struck: int = 0
    credit_repaid: int = 0
    credit_broken: int = 0
    collectors_met: int = 0
    collectors_hp: int = 0
    initiation_due_day: Optional[int] = None
    initiated_day: Optional[int] = None
    deaths: int = 0
    #: v0.18 T3: each death as ``simulate_law.death_log`` read it, and what
    #: the endings table read when the run was over (a reading, never a choice).
    death_log: list[dict[str, Any]] = field(default_factory=list)
    eligible_at_end: list[str] = field(default_factory=list)
    locked: str = ""
    #: The fencing burglar's (v0.18 T3): jobs opened and carried out, the
    #: registry value carried out, and the stolen goods still held at the end
    #: -- unsold because no counter would buy them (a welsher's) or because
    #: the run ended first -- by registry value and by count.
    jobs_tried: int = 0
    jobs_carried_out: int = 0
    loot_taken: int = 0
    loot_unsold: int = 0
    loot_unsold_items: int = 0
    kit_bought_day: Optional[int] = None
    #: Crowns the counters paid for STOLEN units only (a sale of a stack
    #: that held a stolen unit); ``money["sell"]`` counts every sale.
    fenced: int = 0


class Living:
    """Pays its own way: the purchases, meals and beds all four policies share."""

    state: Any
    session: Any
    life: Life

    # -- one action = one turn, with the coin it moved booked to its verb ----

    def act(self, action: str, target: str = "") -> dict[str, Any]:
        """``Thief.act``, with the gold each intent moved booked before the patrol runs."""
        from engine.agents.tool_dispatcher import execute_intent
        from engine.game.intents import scene_owns_turn

        scene_at_start = scene_owns_turn(self.state)
        before = int(self.state.stats.gold)
        intent = {"action": action, "target": target} if target else {"action": action}
        receipts = execute_intent(intent, self.session.engine)
        self.life.money[action] += int(self.state.stats.gold) - before
        result = (receipts[0].get("result") if receipts else {}) or {}
        if not scene_at_start:
            self.patrol()  # type: ignore[attr-defined]
        return result if isinstance(result, dict) else {}

    def answer_stop(self) -> None:
        """Count the fences' collectors (streets.yaml), then answer as the policy does."""
        from engine.game import encounter

        met = encounter.active(self.state) and str(self.state.encounter.get("id")) in COLLECTORS
        hp = int(self.state.stats.hp)
        if met:
            self.life.collectors_met += 1
        super().answer_stop()  # type: ignore[misc]
        if met:
            self.life.collectors_hp += max(0, hp - int(self.state.stats.hp))
            self.note()

    def note(self) -> None:
        stats = self.state.stats
        self.life.min_hp = min(self.life.min_hp, int(stats.hp))
        self.life.min_stamina = min(self.life.min_stamina, int(stats.stamina))

    # -- food ----------------------------------------------------------------

    def meals_carried(self) -> int:
        from engine.game import inventory

        return sum(e.qty for e in self.state.inventory if inventory.has_tag(e.id, "food"))

    def provision(self) -> None:
        """Stock up at a food counter if one is open here, then eat if hungry."""
        from engine.game import inventory

        guard = 0
        while self.meals_carried() < STOCK and guard < 4:
            guard += 1
            food = [t for t in self.legal_targets("buy")  # type: ignore[attr-defined]
                    if inventory.has_tag(t.partition("/")[2], "food")]
            if not food:
                break
            cheapest = min(food, key=lambda t: (inventory.value_of(t.partition("/")[2]), t))
            before = self.state.stats.gold
            self.act("buy", cheapest)
            if self.state.stats.gold >= before:
                break  # could not pay
        self.eat()

    def eat(self) -> None:
        from engine.game import inventory

        guard = 0
        while self.state.hunger >= EAT_AT and guard < 6:
            guard += 1
            food = self.legal_targets("eat")  # type: ignore[attr-defined]
            if not food:
                break
            self.act("eat", min(food, key=lambda i: (inventory.value_of(i), i)))
        self.note()

    #: What this policy never sells (the careful thief's guise; the
    #: burglar's kit too).
    keep: tuple[str, ...] = KEEP

    def sells_to(self, npc_id: str) -> bool:
        """Whom it sells to: anyone the sell menu offers (the fencing burglar
        narrows it to the fences)."""
        return True

    def sell_goods(self) -> None:
        from engine.game import inventory

        guard = 0
        while guard < 40:
            guard += 1
            targets = [t for t in self.legal_targets("sell")  # type: ignore[attr-defined]
                       if not inventory.has_tag(t.partition("/")[2], "food")
                       and t.partition("/")[2] not in self.keep
                       and self.sells_to(t.partition("/")[0])]
            if not targets:
                return
            before = self.state.stats.gold
            self.act("sell", targets[0])
            if self.state.stats.gold <= before:
                return

    # -- the end of the day --------------------------------------------------

    def night(self) -> None:
        """Home to the Snuffs, a last meal, the day booked, and a bed."""
        from engine.game import survival

        self.walk(HOME)  # type: ignore[attr-defined]
        self.meet_the_company()
        self.eat()
        self.life.days += 1
        fed = survival.hunger_stage(self.state) not in ("hungry", "starving")
        receipt = self.act("rest", BEDS[self.life.bed])
        roofed = str(receipt.get("kind") or "") in ROOFED
        self.life.fed_days += int(fed)
        self.life.bed_nights += int(roofed)
        self.life.kept_days += int(fed and roofed)
        self.note()

    def meet_the_company(self) -> None:
        """Note the first day the initiation would be dealt here; and, for the
        bunk policy only, take the oath then (the module docstring)."""
        from engine.content import director

        if self.state.flags.get("guild_initiated"):
            return
        if (self.life.initiation_due_day is None
                and director.due(self.state)[0] == INITIATION):
            self.life.initiation_due_day = int(self.state.world_day)
        if self.life.bed != "bunk":
            return
        director.ensure_scene(self.state)
        guard = 0
        while director.active(self.state) and guard < 8:
            guard += 1
            offered = self.legal_targets("card")  # type: ignore[attr-defined]
            if not offered:
                break
            self.act("card", next((b for b in ROLL_FREE if b in offered), offered[0]))
        if self.state.flags.get("guild_initiated"):
            self.life.initiated_day = int(self.state.world_day)

    def work(self, job_id: str) -> None:
        if job_id not in self.legal_targets("work"):  # type: ignore[attr-defined]
            return
        before = self.state.stats.gold
        receipt = self.act("work", job_id)
        if receipt.get("worked"):
            self.life.shifts += 1
            self.life.wages += int(self.state.stats.gold) - before


class Porter(Living, Thief):
    def __init__(self, seed: int, bed: str) -> None:
        Thief.__init__(self, seed, "porter")
        self.life = Life(seed=seed, policy="porter", bed=bed)

    def day(self, played: int) -> None:
        if self.state.world_hour < WAKE_HOUR:
            self.wait_until(WAKE_HOUR)
        self.walk(DOCKS)
        self.provision()
        self.work("dock_portering")
        self.provision()
        self.walk(MARKET)
        self.eat()
        if self.state.world_hour < DUSK_HOUR:
            self.wait_until(DUSK_HOUR)
        self.work("lamplighting")
        self.provision()


class Dipper(Living, Thief):
    def __init__(self, seed: int, bed: str) -> None:
        Thief.__init__(self, seed, "dipper")
        self.life = Life(seed=seed, policy="dipper", bed=bed)

    def day(self, played: int) -> None:
        if self.state.world_hour < WAKE_HOUR:
            self.wait_until(WAKE_HOUR)
        self.walk(DOCKS)
        self.provision()
        self.walk(RISE)
        self.work("candle_dipping")
        self.walk(MARKET)
        self.provision()
        self.work("market_errands")
        self.provision()


class Careful(Living, Thief):
    def __init__(self, seed: int, bed: str) -> None:
        Thief.__init__(self, seed, "careful")
        self.life = Life(seed=seed, policy="careful", bed=bed)

    def day(self, played: int) -> None:
        if self.state.world_hour < WAKE_HOUR:
            self.wait_until(WAKE_HOUR)
        # Breakfast is on the quay, where Dock Mag sells bread -- after the
        # smock on day one, which is the first thing a careful thief buys
        # (simulate_law's day one, whose own purchase then finds the thief
        # already dressed for it and is skipped here).
        self.walk(DOCKS)
        if played == 1:
            self.act("buy", "npc_dock_mag/porters_smock")
            self.provision()
            self.walk(simulate_law.BUSY_DISTRICT)
            self.wait_until(simulate_law.CAREFUL_CHANGE_HOUR)
            if "porter" in self.legal_targets("guise"):
                self.act("guise", "porter")
            return
        self.provision()
        simulate_law._careful_day(self, played)
        # One purse at 21:00 in the Snuffs; Marrow's yard is open until
        # midnight, across the same street.
        self.sell_goods()
        self.eat()


class CreditLine:
    """One fence's line of credit (``CREDIT``), for a policy that is ``Living``."""

    #: policy -> (thread template, where her counter is)
    CREDIT = {"careful_pell": ("pell_advance", MARKET),
              "careful_marrow": ("marrow_slate", HOME),
              "burglar_pell": ("pell_advance", MARKET),
              "burglar_marrow": ("marrow_slate", HOME)}
    #: Whether it pays the debt back when it can. The careful pickpocket
    #: tries (v0.15); the burglar on credit WELSHES (v0.18 T3, the ruling:
    #: takes the line and never repays it), which is the cost it measures.
    repays = True
    state: Any
    life: Life
    act: Any
    legal_targets: Any

    def open_credit(self, policy: str, strike: bool) -> None:
        self.life.policy = policy
        self.template, self.counter = self.CREDIT[policy]
        #: False is the CONTROL (``--no-credit``): the same days, the same
        #: visits to her counter and the same bread bought there, and never a
        #: line struck -- so what credit itself buys is the difference.
        self.strike = strike

    def tend_credit(self) -> None:
        """Repay the open line if it can (and repays), else strike one if the purse is low."""
        from engine.game import threads

        open_ = [t for t in threads.active(self.state) if t.get("template") == self.template]
        if open_:
            thread_id = str(open_[0]["id"])
            if self.repays and thread_id in self.legal_targets("discharge"):
                self.act("discharge", thread_id)
            return
        if (self.strike and int(self.state.stats.gold) < CREDIT_WHEN_BELOW
                and self.template in self.legal_targets("bargain")):
            self.act("bargain", self.template)

    def has_business(self) -> bool:
        """A debt open with her, or a lean purse and a fence who has not heard it welshed."""
        from engine.game import threads

        if any(t.get("template") == self.template for t in threads.active(self.state)):
            return True
        welshed = ("welshed_on_pell", "welshed_on_marrow")
        return (int(self.state.stats.gold) < CREDIT_WHEN_BELOW
                and not any(self.state.flags.get(f) for f in welshed))

    def tally(self) -> None:
        from engine.game import threads

        mine = [t for t in self.state.threads if t.get("template") == self.template]
        self.life.credit_struck = len(mine)
        self.life.credit_repaid = sum(t.get("status") == threads.STATUS_DISCHARGED for t in mine)
        self.life.credit_broken = sum(t.get("status") == threads.STATUS_BROKEN for t in mine)


class CarefulOnCredit(CreditLine, Careful):
    """The careful pickpocket, with one fence's line of credit (``CREDIT``)."""

    def __init__(self, seed: int, bed: str, policy: str, strike: bool = True) -> None:
        Careful.__init__(self, seed, bed)
        self.open_credit(policy, strike)

    def day(self, played: int) -> None:
        if self.counter == MARKET and played > 1 and self.has_business():
            # Breakfast on the quay, then by Pell's counter -- only on a day
            # with business there, so every other day is the careful
            # pickpocket's own -- then the careful day (which walks on to
            # the Snuffs).
            if self.state.world_hour < WAKE_HOUR:
                self.wait_until(WAKE_HOUR)
            self.walk(DOCKS)
            self.provision()
            self.walk(MARKET)
            if self.state.world_hour < 8:
                self.wait_until(8)   # her shutters open at eight
            self.tend_credit()
            self.provision()
            simulate_law._careful_day(self, played)
            self.sell_goods()
            self.eat()
            return
        super().day(played)
        if self.counter == HOME and played > 1 and self.has_business():
            self.tend_credit()   # the yard, after the night's sale
            self.provision()


class CarefulPorter(Careful):
    """v0.18 T3: the careful pickpocket who takes a porter's shift when hungry.

    The careful day, the same purse at 21:00 and the same sale to Marrow --
    and on a morning its belly or its purse says it must (``needs_a_shift``),
    a shift on Dock Mag's gang (``dock_portering``, 07:00, six hours) before
    it walks on to the Snuffs. It is in the porter's smock from day one, so
    the shift is its own guise's work.
    """

    def __init__(self, seed: int, bed: str) -> None:
        Careful.__init__(self, seed, bed)
        self.life.policy = "careful_porter"

    def needs_a_shift(self) -> bool:
        """Still `hungry` or worse after breakfast, or under a night's bed and
        the next day's bread (``CREDIT_WHEN_BELOW``) -- both on the player's
        own screen (the hunger stage, the purse)."""
        from engine.game import survival

        return (survival.hunger_stage(self.state) in HUNGRY
                or int(self.state.stats.gold) < CREDIT_WHEN_BELOW)

    def day(self, played: int) -> None:
        if self.state.world_hour < WAKE_HOUR:
            self.wait_until(WAKE_HOUR)
        self.walk(DOCKS)
        if played == 1:
            self.act("buy", "npc_dock_mag/porters_smock")
        self.provision()
        if self.needs_a_shift():
            self.work("dock_portering")
            self.provision()
        if played == 1:
            # Careful's day one from here: the smock goes on in an empty
            # Wickmarket at 23:00.
            self.walk(simulate_law.BUSY_DISTRICT)
            self.wait_until(simulate_law.CAREFUL_CHANGE_HOUR)
            if "porter" in self.legal_targets("guise"):
                self.act("guise", "porter")
            return
        simulate_law._careful_day(self, played)
        self.sell_goods()
        self.eat()


class FencingBurglar(Living, Burglar):
    """v0.18 T3: a burglar who lives on what the fences pay for its hauls.

    No other policy sells a haul (simulate_jobs and simulate_endings feed
    their thieves and keep the loot). This one pays its own way like every
    policy here, and every day it:

      * breakfasts on the quay (06:00);
      * goes by Pell Hollis's counter in Wickmarket when she opens (08:00)
        if it carries anything to sell -- sells it, and buys a biscuit;
      * robs one house: a tier-1/2 house it has not tried (simulate_jobs'
        ``_small``, spread by seed as its careful thief's are), in that
        house's district, watched until it knows
        ``simulate_jobs.CAREFUL_INTEL`` things about it, then waited on
        until the casing board says nobody is home (``premises.empty_now``)
        -- never past ``JOB_LAST_HOUR`` -- and burgled simulate_jobs'
        careful way: the best way in the job shows, every useful flashback
        it can pay for without going short (``legal_targets``), walked away
        from the moment the house is roused;
      * walks home to the Snuffs, waits for Marrow's yard (17:00), sells her
        what it still carries, and buys lockpicks once it holds their price
        and a day's living (``LOCKPICKS_PRICE``, ``CREDIT_WHEN_BELOW``).

    It eats a carried meal whenever hunger reaches ``EAT_AT``, waits
    included (``WAIT_STEP_HOURS``), and is never fed or rested by the
    harness. It answers a stop as every thief here does (``run``), and a cell
    by the fine or the days. What it acts on is what a player sees: the
    city's houses as simulate_jobs' thieves pick them (``Burglar.candidates``:
    every house in a public district, less the ones it robbed), what casing
    has told it, the casing board's "go now", the job's own odds
    (``jobs.band_for``), its purse and hunger, and the sell menu.
    """

    keep = KEEP + KIT

    def sells_to(self, npc_id: str) -> bool:
        """Only a fence (trade.yaml ``fence: true``): an honest counter
        refuses a hot unit and reports the offer as a `fencing` deed, and
        every trade profile says which it is."""
        from engine.game import trade

        return bool(trade.vendor(npc_id).get("fence"))

    def __init__(self, seed: int, bed: str, policy: str = "burglar") -> None:
        Burglar.__init__(self, seed, policy)
        self.life = Life(seed=seed, policy=policy, bed=bed)
        self.tried: set[str] = set()

    def act(self, action: str, target: str = "") -> dict[str, Any]:
        """``Living.act`` (the coin booked), then the turn-end observation
        ``Burglar.act`` makes (a flashback reads ``visited``)."""
        from engine.game.quests import QuestEngine

        stolen_before = self.stolen_held()[1] if action == "sell" else 0
        gold_before = int(self.state.stats.gold)
        result = Living.act(self, action, target)
        if action == "sell" and self.stolen_held()[1] < stolen_before:
            self.life.fenced += int(self.state.stats.gold) - gold_before
        QuestEngine.observe(self.state)
        return result

    def legal_targets(self, action: str) -> list[str]:
        """The menu -- less any flashback whose coin (the bribed servant's five
        crowns, jobs.yaml ``cost.gold``) would leave it under a night's bed and
        the next day's bread: a thief living hand to mouth does not bribe a
        servant with its supper."""
        options = super().legal_targets(action)
        if action != "flashback":
            return options
        from engine.world import jobs

        purse = int(self.state.stats.gold)
        flashbacks = jobs.spec()["flashbacks"]

        def coin(kind: str) -> int:
            return int(((flashbacks.get(kind) or {}).get("cost") or {}).get("gold") or 0)

        return [k for k in options if not coin(k) or purse - coin(k) >= CREDIT_WHEN_BELOW]

    # -- waiting: never fed, but it eats what it carries ----------------------

    def wait_until(self, hour: int) -> None:
        """``simulate_law.Thief.wait_until`` (not ``Burglar``'s, which feeds),
        in steps of ``WAIT_STEP_HOURS`` with a carried meal eaten between."""
        from engine.game.clock import advance_time

        now = self.state.world_clock_hours
        target = (int(now // 24) * 24) + hour
        while target < now - 1e-9:
            target += 24
        while target - self.state.world_clock_hours > 1e-9:
            advance_time(self.state, min(WAIT_STEP_HOURS,
                                         target - self.state.world_clock_hours))
            self.eat()

    def linger(self, hours: float = 1.0) -> None:
        super().linger(hours)
        self.eat()

    # -- the day ----------------------------------------------------------------

    def stolen_held(self) -> tuple[int, int]:
        """(registry value, units) of stolen goods carried, hot or cool."""
        from engine.game.inventory import value_of
        from engine.world import thievery

        value = units = 0
        for item_id in sorted(self.state.provenance or {}):
            split = thievery.heat_split(self.state, item_id)
            stolen = int(split["hot"]) + int(split["cool"])
            units += stolen
            value += stolen * int(value_of(item_id))
        return value, units

    def business_at(self, place: str) -> bool:
        """Anything to do at the fence's counter at ``place`` (the credit
        policies add their line)."""
        return self.stolen_held()[1] > 0

    def at_the_counter(self, place: str) -> None:
        """At a fence's counter: sell what it carries (a credit policy tends
        its line first)."""
        self.sell_goods()

    def day(self, played: int) -> None:
        if self.state.world_hour < WAKE_HOUR:
            self.wait_until(WAKE_HOUR)
        self.walk(DOCKS)
        self.provision()
        if self.business_at(MARKET):
            self.walk(MARKET)
            if self.state.world_hour < PELL_OPENS:
                self.wait_until(PELL_OPENS)
            if self.state.location_id == MARKET:
                self.at_the_counter(MARKET)
                self.provision()
        self.job()
        self.walk(HOME)
        if WAKE_HOUR <= self.state.world_hour < MARROW_OPENS:
            self.wait_until(MARROW_OPENS)
        if self.state.location_id == HOME:
            self.at_the_counter(HOME)
            self.buy_kit()
        self.eat()

    def job(self) -> None:
        from engine.world import law, premises
        from scripts.simulate_jobs import CAREFUL_INTEL, _pick, _small

        options = [p for p in self.candidates(_small) if str(p["id"]) not in self.tried]
        prem = _pick(options, self.life.seed, len(self.tried))
        if prem is None:
            return
        premise_id = str(prem["id"])
        self.tried.add(premise_id)
        self.walk(str(prem["district"]))
        if self.state.location_id != prem["district"]:
            return
        self.case_until(premise_id, CAREFUL_INTEL)

        def still_there() -> bool:
            return (not law.in_custody(self.state)
                    and self.state.location_id == prem["district"])

        while (still_there() and not premises.empty_now(self.state, premise_id)
               and WAKE_HOUR <= self.state.world_hour < JOB_LAST_HOUR):
            self.linger(1.0)
        if not still_there() or not premises.empty_now(self.state, premise_id):
            return
        before = len(self.run.jobs)
        row = self.burgle(prem, smart=True, walk_away=True)
        if len(self.run.jobs) > before and row.outcome != "refused":
            self.life.jobs_tried += 1
            self.life.jobs_carried_out += int(row.loot_value > 0)
            self.life.loot_taken += int(row.loot_value)

    def buy_kit(self) -> None:
        """Lockpicks at Marrow's, once it holds their price and a day's living."""
        from engine.game.inventory import holds

        wanted = f"npc_marrow/{LOCKPICKS}"
        if (not holds(self.state, LOCKPICKS)
                and int(self.state.stats.gold) >= LOCKPICKS_PRICE + CREDIT_WHEN_BELOW
                and wanted in self.legal_targets("buy")):
            self.act("buy", wanted)
            if holds(self.state, LOCKPICKS) and self.life.kit_bought_day is None:
                self.life.kit_bought_day = int(self.state.world_day)

    def tally_loot(self) -> None:
        self.life.loot_unsold, self.life.loot_unsold_items = self.stolen_held()


class BurglarOnCredit(CreditLine, FencingBurglar):
    """The fencing burglar with one fence's line: struck when its purse is
    under ``CREDIT_WHEN_BELOW`` and she will stand it, and NEVER repaid
    (``repays``) -- the welsher the owner's v0.15 decision named. Once the
    line breaks neither fence buys (``refuses_to_buy``; the sell menu stops
    offering them), and what it steals after that stays in its pockets."""

    repays = False

    def __init__(self, seed: int, bed: str, policy: str, strike: bool = True) -> None:
        FencingBurglar.__init__(self, seed, bed, policy)
        self.open_credit(policy, strike)

    def business_at(self, place: str) -> bool:
        return (FencingBurglar.business_at(self, place)
                or (place == self.counter and self.has_business()))

    def at_the_counter(self, place: str) -> None:
        if place == self.counter and self.has_business():
            self.tend_credit()
        FencingBurglar.at_the_counter(self, place)


class ScroungeLiving(Living, Scrounger):
    def __init__(self, seed: int, bed: str) -> None:
        Scrounger.__init__(self, seed, "scrounger")
        self.life = Life(seed=seed, policy="scrounger", bed=bed)

    def day(self, played: int) -> None:
        if self.state.world_hour < simulate_scrounge.START_HOUR:
            self.wait_until(simulate_scrounge.START_HOUR)
        simulate_scrounge._day(self, simulate_scrounge._streets("scrounger", played))
        self.walk(HOME)
        self.sell_junk()
        self.eat_if_hungry()


CLASSES = {"porter": Porter, "dipper": Dipper, "careful": Careful,
           "scrounger": ScroungeLiving, "careful_porter": CarefulPorter,
           "burglar": FencingBurglar}


def play(seed: int, policy: str, days: int, bed: str = "flophouse",
         strike: bool = True, each_night: Optional[Any] = None) -> Life:
    with simulate_law.counting_deaths():
        return _play(seed, policy, days, bed, strike, each_night)


def _play(seed: int, policy: str, days: int, bed: str, strike: bool,
          each_night: Optional[Any] = None) -> Life:
    person: Any
    if policy.startswith("careful_") and policy in CreditLine.CREDIT:
        person = CarefulOnCredit(seed, bed, policy, strike)
    elif policy in CreditLine.CREDIT:
        person = BurglarOnCredit(seed, bed, policy, strike)
    else:
        person = CLASSES[policy](seed, bed)
    person.life.start_gold = int(person.state.stats.gold)
    played = 0
    while person.state.world_day <= days:
        played += 1
        person.day(played)
        person.night()
        if each_night is not None:
            each_night(person.state, played)
    person.life.end_gold = int(person.state.stats.gold)
    person.life.arrests = int(person.run.arrests)
    person.life.deaths = simulate_law.deaths(person.state)
    person.life.death_log = simulate_law.death_log(person.state)
    _read_the_ending(person.state, person.life)
    if isinstance(person, CreditLine):
        person.tally()
    if isinstance(person, FencingBurglar):
        person.tally_loot()
    return person.life


def _mean(values: list[float]) -> float:
    return round(statistics.fmean(values), 2) if values else 0.0


def measure(policy: str, seeds: int, days: int, bed: str = "flophouse",
            strike: bool = True, first: int = 0) -> dict[str, Any]:
    """``seeds`` runs, from seed ``first`` (scripts/simulate.py's ``--seed``; 0 here)."""
    lives = [play(seed, policy, days, bed, strike) for seed in range(first, first + seeds)]
    return summarise(lives, days, bed)


def summarise(lives: list[Life], days: int, bed: str = "flophouse") -> dict[str, Any]:
    """The table for ``lives`` (one policy's runs), as ``measure`` reports it."""
    seeds = len(lives)
    earning = ("work", "lift", "sell")

    def per_day(life: Life, value: float) -> float:
        return value / max(1, life.days)

    return {
        "seeds": seeds,
        "days": days,
        "bed": bed,
        "earned_per_day": _mean([per_day(l, sum(max(0, l.money.get(k, 0)) for k in earning))
                                 for l in lives]),
        "wages_per_shift": _mean([l.wages / l.shifts for l in lives if l.shifts]),
        "shifts_per_day": _mean([per_day(l, l.shifts) for l in lives]),
        "food_per_day": _mean([per_day(l, -l.money.get("buy", 0)) for l in lives]),
        "bed_per_day": _mean([per_day(l, -l.money.get("rest", 0)) for l in lives]),
        "fed_days": _mean([per_day(l, l.fed_days) for l in lives]),
        "bed_nights": _mean([per_day(l, l.bed_nights) for l in lives]),
        "kept_days": _mean([per_day(l, l.kept_days) for l in lives]),
        # The same, counted in DAYS a run (v0.15's credit tables, v0.18 T3).
        "kept_days_per_run": _mean([float(l.kept_days) for l in lives]),
        "saved_per_day": _mean([per_day(l, l.end_gold - l.start_gold) for l in lives]),
        "end_gold": _mean([float(l.end_gold) for l in lives]),
        "end_gold_min": min(l.end_gold for l in lives),
        "min_hp": min(l.min_hp for l in lives),
        # Since v0.17 hp 0 respawns inside the hour that reached it, so the
        # sampled `min_hp` rarely shows the 0: a run "at zero" is one that
        # died (`simulate_law.counting_deaths`), or was sampled at 0.
        "runs_at_zero_hp": round(sum(l.min_hp <= 0 or l.deaths > 0 for l in lives)
                                 / len(lives), 3),
        "deaths_per_run": _mean([float(l.deaths) for l in lives]),
        **_deaths(lives),
        "min_stamina": min(l.min_stamina for l in lives),
        "arrests_per_run": _mean([float(l.arrests) for l in lives]),
        "fines_per_run": _mean([float(-l.money.get("pay_fine", 0)) for l in lives]),
        **_credit(lives),
        **_loot(lives),
        **_endings_at_end(lives),
        "initiation_due_day": _mean([float(l.initiation_due_day) for l in lives
                                     if l.initiation_due_day is not None]),
        "initiation_never_due": round(sum(l.initiation_due_day is None for l in lives)
                                      / len(lives), 3),
        **({"initiated": round(sum(l.initiated_day is not None for l in lives) / len(lives), 3),
            "initiated_day": _mean([float(l.initiated_day) for l in lives
                                    if l.initiated_day is not None])}
           if bed == "bunk" else {}),
    }


def _deaths(lives: list[Life]) -> dict[str, Any]:
    """v0.18 T3: the deaths by cause (``simulate_law.cause_of_death``), a run,
    and by the day they fell on, counted over every run -- for a policy that
    died at all."""
    log = [d for l in lives for d in l.death_log]
    if not log:
        return {}
    causes = {c: round(sum(d["cause"] == c for d in log) / len(lives), 2)
              for c in simulate_law.DEATH_CAUSES if any(d["cause"] == c for d in log)}
    return {
        "death_causes": causes,
        "deaths_by_day": {str(day): sum(d["day"] == day for d in log)
                          for day in sorted({d["day"] for d in log})},
        "first_death_day": _mean([float(l.death_log[0]["day"]) for l in lives if l.death_log]),
        # Fix round 2: what it held and where it lay when it died.
        "deaths_penniless": round(sum(d.get("gold", 0) == 0 for d in log) / len(log), 3),
        "death_gold_mean": _mean([float(d.get("gold", 0)) for d in log]),
        "death_places": {place: sum(d.get("location") == place for d in log)
                         for place in sorted({str(d.get("location")) for d in log})},
    }


def _loot(lives: list[Life]) -> dict[str, Any]:
    """v0.18 T3: the fencing burglar's hauls -- for a policy that robbed a house."""
    if not any(l.jobs_tried for l in lives):
        return {}
    return {
        "jobs_per_run": _mean([float(l.jobs_tried) for l in lives]),
        "hauls_per_run": _mean([float(l.jobs_carried_out) for l in lives]),
        "loot_taken_per_run": _mean([float(l.loot_taken) for l in lives]),
        # What the counters paid for stolen units -- a sale that took a
        # stolen unit out of its pockets -- not every sale (``Life.fenced``).
        "fenced_per_run": _mean([float(l.fenced) for l in lives]),
        "loot_unsold": _mean([float(l.loot_unsold) for l in lives]),
        "loot_unsold_items": _mean([float(l.loot_unsold_items) for l in lives]),
        "runs_with_loot_unsold": round(sum(l.loot_unsold_items > 0 for l in lives)
                                       / len(lives), 3),
        "kit_bought": round(sum(l.kit_bought_day is not None for l in lives) / len(lives), 3),
    }


def _endings_at_end(lives: list[Life]) -> dict[str, Any]:
    """v0.18 T3: which endings the table held open when the run was over
    (``endings.eligible``, the fail-forward aside), and any locked -- a
    share of runs each. Read at the end, never by a choice."""
    names = sorted({e for l in lives for e in l.eligible_at_end})
    locked = sorted({l.locked for l in lives if l.locked})
    return {
        "endings_eligible": {e: round(sum(e in l.eligible_at_end for l in lives) / len(lives), 3)
                             for e in names},
        **({"endings_locked": {e: round(sum(l.locked == e for l in lives) / len(lives), 3)
                               for e in locked}} if locked else {}),
    }


def _read_the_ending(state: Any, life: Life) -> None:
    """The endings table at the end of a run (a reading, never a choice)."""
    from engine.game import endings

    fail_forward = endings.fail_forward_id()
    life.eligible_at_end = sorted(e for e in endings.eligible(state).eligible
                                  if e != fail_forward)
    locked = str(endings.locked(state) or "")
    life.locked = "" if locked == endings.NONE_ID else locked


def _credit(lives: list[Life]) -> dict[str, float]:
    """The credit columns, for a policy that ran a line of credit at all."""
    struck = sum(l.credit_struck for l in lives)
    if not struck:
        return {}
    return {
        "credit_struck": _mean([float(l.credit_struck) for l in lives]),
        "credit_repaid": round(sum(l.credit_repaid for l in lives) / struck, 2),
        "credit_broken": round(sum(l.credit_broken for l in lives) / struck, 2),
        "collectors_met": _mean([float(l.collectors_met) for l in lives]),
        "collectors_hp_lost": _mean([float(l.collectors_hp) for l in lives]),
    }


def render(policy: str, report: dict[str, Any]) -> str:
    lines = [f"{policy}: {report['seeds']} seeds x {report['days']} days, bed={report['bed']}"]
    for key, value in report.items():
        if key in ("seeds", "days", "bed"):
            continue
        lines.append(f"  {key:18} {value}")
    return "\n".join(lines)


@contextmanager
def _nothing() -> Iterator[None]:
    yield


#: The days `--endings` reports (end of day N).
ENDING_DAYS = (3, 5, 8, 10, 12)
#: A Lantern's standing (endings.yaml `a_lantern` `lamps_kept`), and the
#: wanted bands Honest After All allows (below `sought`).
LAMPS_KEPT = 5
CLEAN_BANDS = ("unknown", "noticed")
#: Guildmaster's standing with the Honest Company (endings.yaml `guildmaster`
#: `the_hall_trusts_you`, v0.17 T6), measured here: `hall_trusts`.
GUILD_STANDING = 5


def ending_snapshot(state: Any) -> dict[str, bool]:
    """What endings I (v0.17 T5) read, at the end of a day: the Watch's
    standing, your own record and the whole file (`wanted` with and without
    `own`), the fences, the labour record, and Honest After All itself; and
    (T6) the Honest Company's standing Guildmaster asks, and Silas's win."""
    from engine.game import endings
    from engine.game.quests import evaluate_condition
    from engine.world import law

    places = ("quay", "wick", "rise")
    return {
        "lamps_kept": int(state.reputations.get("lantern_watch", 0)) >= LAMPS_KEPT,
        "own_record_clean": all(law.wanted_band(state, "self", j, own=True) in CLEAN_BANDS
                                for j in places),
        "whole_file_clean": all(law.wanted_band(state, "self", j) in CLEAN_BANDS
                                for j in places),
        "square_with_fences": not evaluate_condition(state, {"any": [
            {"thread": {"tag": "Credit"}}, {"flag": "welshed_on_pell"},
            {"flag": "welshed_on_marrow"}]}),
        "wage_earned": bool(state.flags.get("honest_wage_earned")),
        "honest_after_all": "honest_after_all" in endings.eligible(state).eligible,
        # Endings II (v0.17 T6): Guildmaster's standing, and whether Silas
        # Crook's rise has won (which shuts it until he is stood against).
        "hall_trusts": int(state.reputations.get("honest_company", 0)) >= GUILD_STANDING,
        "silas_won": bool(state.flags.get("silas_splits_the_company"))
        and not state.flags.get("silas_stopped"),
    }


def measure_endings(policy: str, seeds: int, days: int, bed: str = "flophouse",
                    strike: bool = True) -> dict[str, Any]:
    """``--endings``: for each day in ``ENDING_DAYS``, the share of seeds
    whose snapshot holds each key at the end of that day."""
    nights: dict[int, list[dict[str, bool]]] = defaultdict(list)

    def each_night(state: Any, played: int) -> None:
        if played in ENDING_DAYS:
            nights[played].append(ending_snapshot(state))

    for seed in range(seeds):
        play(seed, policy, days, bed, strike, each_night)
    return {str(day): {key: round(sum(s[key] for s in rows) / len(rows), 3)
                       for key in rows[0]}
            for day, rows in sorted(nights.items())}


def render_endings(policy: str, report: dict[str, Any]) -> str:
    days = list(report)
    keys = list(report[days[0]]) if days else []
    lines = [f"{policy} -- share of seeds at the end of day", f"  {'':20}" +
             "".join(f"{d:>7}" for d in days)]
    for key in keys:
        lines.append(f"  {key:20}" + "".join(f"{report[d][key]:>7.0%}" for d in days))
    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--seeds", type=int, default=40)
    parser.add_argument("--days", type=int, default=10)
    parser.add_argument("--policy", choices=(*POLICIES, "all"), default="all")
    parser.add_argument("--bed", choices=tuple(BEDS), default="flophouse")
    parser.add_argument("--agendas", action="store_true",
                        help="measure with the story's agendas on (off by default)")
    parser.add_argument("--no-credit", action="store_true",
                        help="the credit policies' control: the same visits, no line struck")
    parser.add_argument("--endings", action="store_true",
                        help="report what v0.17's endings read at the end of days "
                             "3/5/8/10/12 (run with --days 12)")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    import logging

    logging.disable(logging.WARNING)
    from engine.games import registry

    registry.activate("hue-and-cry")
    with (_nothing() if args.agendas else agendas_off()):
        policies = POLICIES if args.policy == "all" else (args.policy,)
        if args.endings:
            reports = {p: measure_endings(p, args.seeds, args.days, args.bed,
                                          not args.no_credit) for p in policies}
        else:
            reports = {p: measure(p, args.seeds, args.days, args.bed, not args.no_credit)
                       for p in policies}
    if args.json:
        print(json.dumps(reports, indent=2))
    elif args.endings:
        print("\n\n".join(render_endings(p, r) for p, r in reports.items()))
    else:
        print("\n\n".join(render(p, r) for p, r in reports.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
