"""
Every shipped game can be finished.

NOTHING TESTED THIS. The engine has an ending system, an ending MODULE
(Speak/Act/Seal) and an epilogue system, all three well covered in isolation --
and no test anywhere drove a single story through
``ending_lock -> ending_module -> epilogue``. The consequences were not
theoretical:

* **The Wicked Garden could not be finished by playing it.** Its only
  ``ending_lock`` sits on a card in ``day_09_finale``, and nothing in a running
  game ever dealt a deck.
* **THE LONG CON could not end at all.** No ``endings:``, no ``epilogues:``,
  and its single quest had no ``on_complete`` -- finishing all four stages
  awarded nothing and set no flag.
* **dev-story declared three endings and three epilogue cards** and emitted
  neither ``ending_lock`` nor ``ending_module`` anywhere.

The nearest thing that existed was ``test_wicked_garden_scenes.py``, which
calls ``deck.resolve_card`` directly -- i.e. it tested the offline walker's
path, not the game's. So these tests deliberately assert the CHAIN rather than
its parts, and the graph cases go through ``run_turn``, because "the effect
applies" and "a player can reach the effect" are the two claims that came apart.
"""

from __future__ import annotations

import json
from collections import namedtuple

import pytest

from engine.games import registry
from engine.persistence import reset_save_store

from endings_driver import Door, EndingDoor, drive
# The measured standing A Lantern gates on, pinned to endings.yaml by
# test_hue_and_cry.py::test_a_lanterns_standing_is_the_measured_one.
from test_hue_and_cry import LANTERN_STANDING
# Guildmaster's measured standing, pinned the same way (v0.17 T6).
from test_hue_and_cry import GUILD_STANDING


@pytest.fixture(autouse=True)
def _saves(tmp_path, monkeypatch):
    from engine.persistence.saves import SaveStore

    reset_save_store()
    store = SaveStore(root=tmp_path / "saves")
    monkeypatch.setattr("engine.scenes.default_state.get_save_store", lambda: store)
    yield
    reset_save_store()


def _activate(slug: str):
    registry.activate(slug)


def _finish_chain(state) -> None:
    """Lock an ending and play its module, the way a finale quest does."""
    from engine.game import effects

    effects.apply_effect(state, {"type": "ending_lock"})
    effects.apply_effect(state, {"type": "ending_module"})


def _assert_finale(state, slug: str) -> None:
    from engine.game import endings as endings_module
    from engine.game import epilogue as epilogue_module

    locked = endings_module.locked(state)
    assert locked, f"{slug}: ending_lock produced no locked ending"

    card = epilogue_module.for_state(state)
    assert card is not None, (
        f"{slug}: the ending locked and its module ran, and no epilogue came "
        "back -- the run reaches its end and the player is shown nothing"
    )
    rendered = card.to_dict()
    assert rendered.get("title"), f"{slug}: epilogue has no title"


# -- every game declares a reachable finale ------------------------------


@pytest.mark.parametrize(
    "slug",
    ["clockwork-dark", "neon-city", "wicked-garden", "the-long-con", "dev-story", "hue-and-cry"],
)
def test_every_shipped_game_can_reach_an_epilogue(slug: str) -> None:
    """
    THE HEADLINE GATE. Two of these five could not do this at all.

    Driven through the effect pair the finale quests and finale cards actually
    declare, rather than through one story's content, so it asks the same
    question of a graph story, a deck story and a hybrid.
    """
    _activate(slug)
    try:
        from engine.game.state import GameState

        state = GameState()
        _finish_chain(state)
        _assert_finale(state, slug)
    finally:
        registry.deactivate()


@pytest.mark.parametrize(
    "slug", ["clockwork-dark", "neon-city", "wicked-garden", "the-long-con", "dev-story", "hue-and-cry"]
)
def test_every_shipped_game_declares_a_fail_forward(slug: str) -> None:
    """
    A run that qualifies for nothing still has to land somewhere.

    Without this the finale depends on the player having earned a specific
    ending, and the ones who did not get a locked story with no last page.
    """
    _activate(slug)
    try:
        from engine.game import endings as endings_module

        assert endings_module.fail_forward_id(), f"{slug} declares no fail_forward"
    finally:
        registry.deactivate()


# -- every registered ending, through its own door (v0.17) ---------------
#
# `tests/endings_driver.py` drives ONE ending through ONE real door -- a quest,
# a card beat, a set-piece or a death -- and asserts it locked that ending and
# shows that ending's card. The shape of a row is in its docstring. A story in
# COMPLETE_DOORS must register every ending it declares, so an ending added
# without a door (or a door that locks the wrong ending) fails here, not at
# the end of somebody's run.


def _earn_an_honest_wage(state) -> None:
    """HUE & CRY's labour record (v0.17 T5): a shift for Dock Mag through the
    `work` code a turn runs -- the real roll -- repeated each morning until
    one is paid."""
    from engine.game import economy
    from engine.game.clock import advance_time
    from engine.game.effects import apply_effect

    state.location_id = "tallow_docks"
    for _ in range(8):
        hour = int(state.world_hour)
        if not 5 <= hour < 13:
            advance_time(state, (7 - hour) % 24 or 24)
        apply_effect(state, {"type": "hunger", "delta": -state.hunger})
        apply_effect(state, {"type": "stamina", "delta": state.stats.max_stamina})
        assert economy.work(state, "dock_portering")["worked"]
        if state.flags.get("honest_wage_earned"):
            return
    raise AssertionError("eight mornings on the quay and never paid")


def _to_the_hour(state, hour: int) -> None:
    from engine.game.clock import advance_time
    from engine.game.effects import apply_effect

    apply_effect(state, {"type": "hunger", "delta": -state.hunger})
    advance_time(state, (hour - int(state.world_hour)) % 24 or 24)


def _board_the_evening_barge(state) -> None:
    """HUE & CRY's barge: an honest wage earned (v0.17 T5: the barge takes
    only a thief who has earned Honest After All), then on the docks, in the
    evening, aboard."""
    from engine.game.effects import apply_effect

    assert state.location_id == "tallow_docks"
    _earn_an_honest_wage(state)
    _to_the_hour(state, 18)
    apply_effect(state, {"type": "flag", "flag": "nf_boarded_the_evening_barge"})


def _aboard_without_a_wage(state) -> None:
    """The barge's door, unearned: a clean name, square with the fences, and
    never a day's honest work."""
    from engine.game.effects import apply_effect

    _to_the_hour(state, 18)
    apply_effect(state, {"type": "flag", "flag": "nf_boarded_the_evening_barge"})


def _aboard_with_the_heart(state) -> None:
    """The barge's door, unearned by the heart alone: a wage earned, the
    Magpie named rightly, the Showing's heist won (F2's own on_pass effects,
    the sacrilege filed on the Magpie's mask), then aboard at dusk."""
    from engine.game.effects import apply_effect

    _earn_an_honest_wage(state)
    _name_the_magpie_rightly(state)
    _lift_the_heart(state)
    _to_the_hour(state, 18)
    apply_effect(state, {"type": "flag", "flag": "nf_boarded_the_evening_barge"})


def _name_the_magpie_rightly(state) -> None:
    """What the front desk's right naming writes about the Watch's belief
    (lantern_house_desk.yaml `name_them` on_pass): the flag, the link broken."""
    from engine.game.effects import apply_effect

    assert apply_effect(state, {"type": "flag", "flag": "magpie_unmasked"})["ok"]
    assert apply_effect(state, {"type": "law_unlink", "a": "self", "b": "magpie"})["ok"]


def _on_the_green_at_the_fair(state) -> None:
    _fed_until(state, _hanging_fair_day(state), 10)
    state.location_id = "gallows_green"


def _unmasked_at_the_fair(state) -> None:
    """HUE & CRY's Cleared: the Magpie named rightly, then onto the Green
    while the fair is on -- where F3 is dealt."""
    _name_the_magpie_rightly(state)
    _on_the_green_at_the_fair(state)


def _after_the_fair_at_the_desk(state) -> None:
    """The morning after the fair, at the Lantern House. The quests pass runs
    once during the fair, as every turn runs it, recording it as seen."""
    from engine.game.quests import QuestEngine
    from engine.world import schedules

    spec = schedules.load_schedules()["events"]["hanging_fair"]
    _fed_until(state, int(spec["on_day"]), 10)
    QuestEngine.evaluate(state)
    _fed_until(state, int(spec["on_day"]) + int(spec["duration_days"]), 9)
    state.location_id = "lantern_house"


def _unmasked_after_the_fair(state) -> None:
    """HUE & CRY's Cleared, its second door (T5 fix round 1): the fair has
    come and gone, the Magpie named rightly after it, the captain at the
    front desk at nine -- D4."""
    _after_the_fair_at_the_desk(state)
    _name_the_magpie_rightly(state)


def _at_the_desk_with_the_lamps(state, *, standing: int = LANTERN_STANDING) -> None:
    """HUE & CRY's A Lantern: the Magpie named rightly, the Watch's good
    opinion (lamps kept with it), never the captain's file used against her;
    at the Lantern House front desk at nine the next morning, while she is in."""
    from engine.game.effects import apply_effect

    _name_the_magpie_rightly(state)
    apply_effect(state, {"type": "reputation", "faction": "lantern_watch", "delta": standing})
    state.location_id = "lantern_house"
    _to_the_hour(state, 9)


def _at_the_desk_unnamed_with_the_lamps(state) -> None:
    """The Watch's good opinion kept, the Magpie never named: at the desk at nine."""
    from engine.game.effects import apply_effect

    apply_effect(state, {"type": "reputation", "faction": "lantern_watch",
                         "delta": LANTERN_STANDING})
    state.location_id = "lantern_house"
    _to_the_hour(state, 9)


def _at_the_desk_short_of_the_lamps(state) -> None:
    _at_the_desk_with_the_lamps(state, standing=LANTERN_STANDING - 1)


def _swear_mara_on_the_ninth_day(state) -> None:
    """The Garden's E6e: Mara's pact made, the ending sworn, day 9 come."""
    from engine.game.clock import advance_time
    from engine.game.effects import apply_effect

    apply_effect(state, {"type": "flag", "flag": "mara_pact"})
    assert apply_effect(state, {"type": "ending_intent", "ending": "E6e"})["ok"]
    while state.world_day < 9:
        advance_time(state, 24)


def _fed_until(state, day: int, hour: int) -> None:
    """The clock walked to ``day``/``hour`` through `advance_time` -- the path
    that raises a declared world event on its day -- fed before each step."""
    from engine.game.clock import advance_time
    from engine.game.effects import apply_effect

    target = float((day - 1) * 24 + hour)
    while state.world_clock_hours < target:
        if state.hunger > 0:
            apply_effect(state, {"type": "hunger", "delta": -state.hunger})
        advance_time(state, min(6.0, target - state.world_clock_hours))


def _hanging_fair_day(state, *, offset: int = 0) -> int:
    """HUE & CRY's `hanging_fair` (data/world/schedules.yaml): its first day,
    plus ``offset``, bounded by its length."""
    from engine.world import schedules

    spec = schedules.load_schedules()["events"]["hanging_fair"]
    assert 0 <= offset < int(spec["duration_days"])
    return int(spec["on_day"]) + offset


def _held_when_the_fair_comes(state) -> None:
    """Arrested on the quay's charge the day before the fair, and questioned
    -- the interrogation dealt and answered the way a turn deals it."""
    from engine.content import director
    from engine.game.effects import apply_effect

    _fed_until(state, _hanging_fair_day(state) - 1, 12)
    state.location_id = "tallow_docks"
    apply_effect(state, {"type": "report", "deed": "pickpocket", "guise": "magpie",
                         "jurisdiction": "quay", "precision": 0.3})
    assert apply_effect(state, {"type": "arrest"})["ok"]
    assert director.ensure_scene(state)
    while director.active(state):
        director.resolve(state, chosen=director.options(state)[-1]["id"])


def _held_at_the_hanging_fair(state) -> None:
    """HUE & CRY's The Rope, its death door (death.yaml `terminal`): in the
    cells on the quay's charge while the Hanging Fair is on. The fair is the
    declared event (data/world/schedules.yaml), raised by the calendar
    itself: the clock is walked into its first day."""
    _held_when_the_fair_comes(state)
    _fed_until(state, _hanging_fair_day(state), 10)


def _held_on_the_fairs_last_morning(state) -> None:
    """HUE & CRY's The Rope, its hanging door: held since before the fair,
    walked to nine on its last morning, when the gallows deck falls due."""
    from engine.world import schedules

    spec = schedules.load_schedules()["events"]["hanging_fair"]
    _held_when_the_fair_comes(state)
    _fed_until(state, _hanging_fair_day(state, offset=int(spec["duration_days"]) - 1), 9)


# -- endings II (v0.17 T6) ------------------------------------------------

#: Where each suspect is found alone enough to be asked, and an hour they are
#: there (data/scenes/the_confrontation.yaml).
_HAUNTS = {"npc_wren": ("the_snuffs", 22), "npc_silas": ("the_snuffs", 21),
           "npc_imelda": ("silk_row", 10)}


def _play_hand(state, picks: dict) -> list:
    """Deal what is due here and answer it: ``picks`` by card id, otherwise the
    last option (every door card's last option is its roll-free "not yet")."""
    from engine.content import director

    dealt = director.ensure_scene(state)
    assert dealt and dealt[0]["result"].get("ok"), dealt
    answered = []
    guard = 0
    while director.active(state) and guard < 16:
        guard += 1
        card = director.current_card(state)
        answered.append(card.id)
        chosen = picks.get(card.id) or director.options(state)[-1]["id"]
        assert director.resolve(state, chosen=chosen)["ok"]
    return answered


def _sworn_to_the_company(state) -> None:
    """The initiation, dealt at the long table on the first evening and
    answered roll-free where it can be (its last option), as a player swears."""
    from engine.content import director

    _fed_until(state, 1, 20)
    state.location_id = "the_snuffs"
    dealt = director.ensure_scene(state)
    assert dealt and dealt[0]["result"]["deck_id"] == "initiation", dealt
    while director.active(state):
        card = director.current_card(state)
        options = director.options(state)
        director.resolve(state, chosen=options[-1]["id"] if card.id != "I3_the_oath"
                         else options[0]["id"])
    assert state.flags.get("guild_initiated")


def _the_magpies_partner(state) -> None:
    """PARTNERS' first half: two of the real Magpie's clues carried out of the
    city's houses (the engine's own `clues.take`), then to the Magpie's haunt
    at an hour they are there, where the confrontation deck is dealt, and the
    name said -- rightly."""
    from engine.world import agendas, clues

    magpie = agendas.role(state, "magpie")
    rows = [cid for cid, row in clues.spec()["clues"].items()
            if row["points_to"] == magpie][:2]
    for cid in rows:
        assert clues.take(state, {"id": f"prem_{cid}", "name": "a house", "clue": cid})
    where, hour = _HAUNTS[magpie]
    _fed_until(state, 2, hour)
    state.location_id = where
    card = {"npc_wren": "C1_wrens_stair", "npc_silas": "C1_silas_taproom",
            "npc_imelda": "C1_imeldas_parlour"}[magpie]
    # In the Snuffs of an evening a thief not yet sworn meets the Company
    # first (the initiation is due there too); the confrontation is dealt on
    # the next turn, as a player would find it.
    for _ in range(3):
        if card in _play_hand(state, {card: "say_it"}):
            break
    assert state.flags.get("partners_with_the_magpie")


def _on_the_hill_after_the_fair(state) -> None:
    """The fair come (the quests pass runs once during it) and gone, and up
    on Margrave's Hill at eleven on the night after its last day."""
    from engine.game.quests import QuestEngine
    from engine.world import schedules

    spec = schedules.load_schedules()["events"]["hanging_fair"]
    _fed_until(state, int(spec["on_day"]), 10)
    QuestEngine.evaluate(state)
    _fed_until(state, int(spec["on_day"]) + int(spec["duration_days"]), 23)
    state.location_id = "margraves_hill"


def _partners_on_the_hill_after_the_fair(state) -> None:
    """HUE & CRY's Partners, its second door (T8 fix round 1): the Magpie
    found out and thrown in with, and the fair gone by -- up the Hill by
    night, where the_last_job is dealt."""
    _the_magpies_partner(state)
    _on_the_hill_after_the_fair(state)


def _partners_at_the_fair(state) -> None:
    """HUE & CRY's Partners: the Magpie found out and thrown in with, then
    onto the Green at the Hanging Fair -- where F6 is dealt."""
    _the_magpies_partner(state)
    _on_the_green_at_the_fair(state)


def _the_hearts_getaway_begun(state) -> None:
    """HUE & CRY's The Legend: on the Green at the fair, the fair hand dealt
    and played through the director -- the Showing answered `lift_the_heart`,
    its severe stealth roll forced to succeed (the only thing forced) --
    then the quests pass at the turn's end (the getaway quest starts), then
    one street home to the Snuffs."""
    from unittest import mock

    from engine.content import director
    from engine.game import checks, inventory
    from engine.game.quests import QuestEngine

    real = checks.resolve

    def succeeds(*args, **kwargs):
        result = real(*args, **kwargs)
        result.degree = "success"
        return result

    _on_the_green_at_the_fair(state)
    dealt = director.ensure_scene(state)
    assert dealt and dealt[0]["result"]["deck_id"] == "fair_day", dealt
    assert "F2_the_showing" in dealt[0]["result"]["card_ids"]
    with mock.patch.object(checks, "resolve", succeeds):
        while director.active(state):
            card = director.current_card(state)
            chosen = ("lift_the_heart" if card.id == "F2_the_showing"
                      else director.options(state)[0]["id"])
            assert director.resolve(state, chosen=chosen)["ok"]
    assert inventory.quantity(state, "everflame_heart") == 1
    QuestEngine.evaluate(state)
    state.location_id = "the_snuffs"


def _on_the_green_without_the_heart(state) -> None:
    """The Legend's door, unearned: the fair on, the heart never lifted, the
    thief walks home to the Snuffs anyway."""
    from engine.game.quests import QuestEngine

    _on_the_green_at_the_fair(state)
    QuestEngine.evaluate(state)
    state.location_id = "the_snuffs"


def _at_the_long_table_after_the_fair(state) -> None:
    """The fair come (the quests pass runs once during it, as a turn runs it,
    recording it as seen) and gone, and back at the long table on the first
    evening after it. (T8 fix round 1: Gannet names nobody before the fair.
    The Guildmaster rows run on seed 2, where Silas's rise never fills on its
    own by then; on seed 11 it does on day 7.)"""
    from engine.game.quests import QuestEngine
    from engine.world import schedules

    spec = schedules.load_schedules()["events"]["hanging_fair"]
    _fed_until(state, int(spec["on_day"]), 10)
    QuestEngine.evaluate(state)
    _fed_until(state, int(spec["on_day"]) + int(spec["duration_days"]), 22)
    state.location_id = "the_snuffs"


def _the_hall_at(state, standing: int) -> None:
    """The Hall's good opinion brought to ``standing`` (after the walk, which
    Silas's robberies of the Company's ward can lower)."""
    from engine.game.effects import apply_effect

    now = int(state.reputations.get("honest_company", 0))
    apply_effect(state, {"type": "reputation", "faction": "honest_company",
                         "delta": standing - now})


def _gannets_lever(state) -> None:
    """Gannet's lever held: the strike fund's IOUs read at her house (the
    flag a job's getaway writes, jobs.SECRET_HELD_PREFIX)."""
    from engine.game.effects import apply_effect
    from engine.world import jobs

    apply_effect(state, {"type": "flag",
                         "flag": f"{jobs.SECRET_HELD_PREFIX}prem_gannets_house:fund_of_ious"})


def _gannets_measure_taken(state, *, standing: int = GUILD_STANDING) -> None:
    """HUE & CRY's Guildmaster: sworn on the first evening, the fair come and
    gone, the Hall's good opinion brought to ``standing`` and Gannet's lever
    held -- then at the long table that evening."""
    _sworn_to_the_company(state)
    _at_the_long_table_after_the_fair(state)
    _the_hall_at(state, standing)
    _gannets_lever(state)


def _gannets_measure_short_of_the_hall(state) -> None:
    _gannets_measure_taken(state, standing=GUILD_STANDING - 1)


def _gannets_measure_before_the_fair(state) -> None:
    """Guildmaster, unearned by the calendar alone (T8 fix round 1): sworn,
    trusted and measured on the first night -- at the long table, long
    before the Hanging Fair."""
    _sworn_to_the_company(state)
    _the_hall_at(state, GUILD_STANDING)
    _gannets_lever(state)
    _fed_until(state, 1, 22)
    state.location_id = "the_snuffs"


def _silas_has_split_the_company(state) -> None:
    """Silas Crook's clock wound full (clocks.yaml `silas_rise`) and its beat
    fired through the clock table, as `advance_time` fires it."""
    from engine.game import clocks

    clocks.advance(state, "silas_rise", 5, why="test: the Company split")
    clocks.resolve(state)
    assert state.flags.get("silas_splits_the_company")


def _sworn_when_silas_moves(state) -> None:
    """HUE & CRY's The Dapper's City: sworn to the Company, Silas's rise
    complete, and onto the Green at the fair -- where F4 is dealt."""
    _sworn_to_the_company(state)
    _silas_has_split_the_company(state)
    _on_the_green_at_the_fair(state)


def _unsworn_when_silas_moves(state) -> None:
    """The Dapper's City's door, unearned: Silas's rise complete, the thief
    never sworn to the Company."""
    _silas_has_split_the_company(state)
    _on_the_green_at_the_fair(state)


# -- all eight, held (v0.17 T7): one unearned setup per gate clause ---------
#
# Each leaves out exactly ONE clause of its ending's gate (endings.yaml) and
# meets the rest, so the row proves that clause alone keeps the door shut.


def _at_the_desk_having_squeezed_her(state) -> None:
    """A Lantern, unearned by the squeeze alone: the captain's own Magpie
    file read in her office (the flag a job's getaway writes) and struck
    against her while the Watch held something on you -- then the Magpie
    named rightly and the lamps kept, at the desk at nine."""
    from engine.game import threads
    from engine.game.effects import apply_effect
    from engine.world import jobs

    state.location_id = "lantern_house"
    _to_the_hour(state, 19)
    apply_effect(state, {"type": "flag",
                         "flag": f"{jobs.SECRET_HELD_PREFIX}prem_captains_office:magpie_file"})
    assert apply_effect(state, {"type": "report", "deed": "pickpocket", "guise": "magpie",
                                "jurisdiction": "wick", "precision": 1.0})["ok"]
    sealed = threads.seal(state, threads.offer(state, "ardane_magpie_file"))
    assert sealed["ok"], sealed
    _at_the_desk_with_the_lamps(state)


def _aboard_and_sought_on_the_quay(state) -> None:
    """Honest After All, unearned by your own record alone: a wage earned,
    then your own face filed on the Quay until it is `sought` there, aboard
    at dusk."""
    from test_hue_and_cry import _sought_on_the_quay

    _earn_an_honest_wage(state)
    _sought_on_the_quay(state)
    state.location_id = "tallow_docks"
    _aboard_without_a_wage(state)


def _aboard_having_stolen_unseen(state) -> None:
    """Honest After All, unearned by a theft nobody saw (T8 fix round 1, the
    owner's ruling): a wage earned, one purse lifted where nobody was --
    no witness, no report, the Watch's file clean -- then aboard at dusk."""
    from engine.world import law

    _earn_an_honest_wage(state)
    assert law.commit_deed(state, "pickpocket", location="old_bell_tower")["witnesses"] == []
    state.location_id = "tallow_docks"
    _aboard_without_a_wage(state)


def _aboard_having_squeezed(state) -> None:
    """Honest After All, unearned by a squeeze struck and PAID (T8 fix round
    2): nothing committed, nothing filed -- only the Blackmail thread
    remembers -- then aboard at dusk."""
    from test_hue_and_cry import _squeezed_and_paid

    _earn_an_honest_wage(state)
    _squeezed_and_paid(state)
    _aboard_without_a_wage(state)


def _aboard_on_pells_credit(state) -> None:
    """Honest After All, unearned by a fence's open credit alone."""
    from test_hue_and_cry import _on_credit

    _earn_an_honest_wage(state)
    _on_credit(state)
    state.location_id = "tallow_docks"
    _aboard_without_a_wage(state)


def _aboard_having_welshed(state) -> None:
    """Honest After All, unearned by a welsh on a fence's book alone."""
    from test_hue_and_cry import _welshed

    _earn_an_honest_wage(state)
    _welshed(state)
    _aboard_without_a_wage(state)


def _lift_the_heart(state) -> None:
    """F2's `lift_the_heart` on_pass effects, through `apply_effect` (no
    session ledger here, so the ledger fact is left out)."""
    from engine.content import deck
    from engine.game.effects import apply_effect

    card = next(c for c in deck.load_deck("fair_day").cards if c.id == "F2_the_showing")
    beat = next(b for b in card.beats if b["id"] == "lift_the_heart")
    for effect in beat["gate"]["on_pass"]["effects"]:
        if effect["type"] != "ledger_fact":
            assert apply_effect(state, effect)["ok"], effect


def _partners_with_the_heart_already(state) -> None:
    """Partners, unearned by the heart already taken alone: the Magpie found
    out and thrown in with, the heart lifted, then on the Green at the fair."""
    _the_magpies_partner(state)
    _lift_the_heart(state)
    _on_the_green_at_the_fair(state)


def _partners_who_gave_them_up(state) -> None:
    """Partners, out of reach: the Magpie thrown in with, then named at the
    captain's desk all the same -- on the Green at the fair."""
    _the_magpies_partner(state)
    _name_the_magpie_rightly(state)
    _on_the_green_at_the_fair(state)


def _home_with_the_heart_but_held(state) -> None:
    """The Legend, unearned by the Watch's hand alone: the heart lifted and
    the getaway begun, home to the Snuffs -- and arrested there."""
    from engine.game.effects import apply_effect

    _the_hearts_getaway_begun(state)
    apply_effect(state, {"type": "report", "deed": "pickpocket", "guise": "self",
                         "jurisdiction": "wick", "precision": 1.0})
    assert apply_effect(state, {"type": "arrest"})["ok"]
    from engine.world import law

    assert law.in_custody(state)


def _gannets_measure_unsworn(state) -> None:
    """Guildmaster, unearned by the oath alone: the Hall's good opinion and
    Gannet's lever held, never sworn at the long table."""
    _at_the_long_table_after_the_fair(state)
    _the_hall_at(state, GUILD_STANDING)
    _gannets_lever(state)


def _sworn_and_trusted_without_her_measure(state) -> None:
    """Guildmaster, unearned by Gannet's measure alone: sworn, the Hall's
    good opinion, and neither her blessing nor her lever."""
    _sworn_to_the_company(state)
    _at_the_long_table_after_the_fair(state)
    _the_hall_at(state, GUILD_STANDING)


def _gannets_measure_with_the_heart(state) -> None:
    """Guildmaster, unearned by the heart alone: everything else held, and
    the Everflame's heart under the coat."""
    _gannets_measure_taken(state)
    _lift_the_heart(state)


def _gannets_measure_after_silas_won(state) -> None:
    """Guildmaster, out of reach: sworn, trusted and measured -- and Silas
    Crook's rise complete, nobody having stood against him."""
    _sworn_to_the_company(state)
    _at_the_long_table_after_the_fair(state)
    _silas_has_split_the_company(state)
    _the_hall_at(state, GUILD_STANDING)
    _gannets_lever(state)


def _sworn_before_silas_moves(state) -> None:
    """The Dapper's City, unearned by Silas's rise alone: sworn, on the Green
    at the fair, his clock not yet full."""
    _sworn_to_the_company(state)
    _on_the_green_at_the_fair(state)
    assert not state.flags.get("silas_splits_the_company")


def _sworn_when_silas_was_stopped(state) -> None:
    """The Dapper's City, out of reach: sworn, Silas's rise complete, and
    stood against and beaten (F4 `stand_against_him`'s on_pass effects) --
    on the Green at the fair."""
    from engine.content import deck
    from engine.game.effects import apply_effect

    _sworn_to_the_company(state)
    _silas_has_split_the_company(state)
    card = next(c for c in deck.load_deck("fair_day").cards
                if c.id == "F4_silas_makes_his_move")
    beat = next(b for b in card.beats if b["id"] == "stand_against_him")
    for effect in beat["gate"]["on_pass"]["effects"]:
        if effect["type"] != "ledger_fact":
            assert apply_effect(state, effect)["ok"], effect
    _on_the_green_at_the_fair(state)


def _sworn_when_silas_moves_having_named_one(state) -> None:
    """The Dapper's City, out of reach: sworn, Silas's rise complete, and a
    name laid on the captain's desk (rightly) -- on the Green at the fair."""
    _sworn_to_the_company(state)
    _silas_has_split_the_company(state)
    _name_the_magpie_rightly(state)
    _on_the_green_at_the_fair(state)


def _sworn_when_silas_moves_as_a_partner(state) -> None:
    """The Dapper's City, out of reach: sworn, the Magpie's partner, Silas's
    rise complete -- on the Green at the fair."""
    _sworn_to_the_company(state)
    _the_magpies_partner(state)
    _silas_has_split_the_company(state)
    _on_the_green_at_the_fair(state)


ENDING_DOORS = [
    EndingDoor("hue-and-cry", "honest_after_all", Door.quest("the_evening_barge"),
               _board_the_evening_barge, seed=11),
    # v0.17 T5: Cleared at the fair (F3, the real Magpie taken), A Lantern at
    # the front desk (D3, the captain's badge).
    EndingDoor("hue-and-cry", "cleared",
               Door.card("fair_day", "F3_the_real_magpie", "see_it_done"),
               _unmasked_at_the_fair, seed=11),
    # Cleared after the fair (fix round 1): the captain, at the front desk.
    EndingDoor("hue-and-cry", "cleared",
               Door.card("lantern_house_desk", "D4_cleared_at_the_desk", "hear_it_said"),
               _unmasked_after_the_fair, seed=11),
    EndingDoor("hue-and-cry", "a_lantern",
               Door.card("lantern_house_desk", "D3_the_badge", "take_the_badge"),
               _at_the_desk_with_the_lamps, seed=11),
    # Fix round 2: with both earned, the badge card is also Cleared's door.
    EndingDoor("hue-and-cry", "cleared",
               Door.card("lantern_house_desk", "D3_the_badge", "clear_my_name"),
               _at_the_desk_with_the_lamps, seed=11),
    EndingDoor("hue-and-cry", "the_rope", Door.death(), _held_at_the_hanging_fair, seed=11),
    # The Rope's other door (v0.17 T3): the hanging itself, no death needed.
    EndingDoor("hue-and-cry", "the_rope",
               Door.card("the_gallows", "G1_the_last_morning", "head_up"),
               _held_on_the_fairs_last_morning, seed=11),
    # v0.17 T6. Partners at the fair (F6, the heart taken with the Magpie the
    # confrontation found); The Legend on the getaway home (the quest the
    # heist starts); Guildmaster at the long table (the Porters' Hall); The
    # Dapper's City at the fair (F4), standing with Silas -- or failing to
    # stop him (test_hue_and_cry.py drives that branch on a forced roll).
    EndingDoor("hue-and-cry", "partners",
               Door.card("fair_day", "F6_the_heist_together", "take_it_together"),
               _partners_at_the_fair, seed=11),
    EndingDoor("hue-and-cry", "the_legend", Door.quest("the_heart_goes_home"),
               _the_hearts_getaway_begun, seed=11),
    EndingDoor("hue-and-cry", "guildmaster",
               Door.card("porters_hall", "P1_the_needles", "take_the_chair"),
               _gannets_measure_taken, seed=2),
    # T8 fix round 1: Partners after the fair, up the Hill by night.
    EndingDoor("hue-and-cry", "partners",
               Door.card("the_last_job", "L1_the_heart_by_night", "take_it_together"),
               _partners_on_the_hill_after_the_fair, seed=11),
    EndingDoor("hue-and-cry", "the_dappers_city",
               Door.card("fair_day", "F4_silas_makes_his_move", "stand_with_him"),
               _sworn_when_silas_moves, seed=11),
    # The Garden's finale: F3 locks whatever was earned (here, the sworn E6e);
    # F4, later in the same hand, plays its module.
    EndingDoor("wicked-garden", "E6e", Door.card("day_09_finale", "F3_point_of_no_return"),
               _swear_mara_on_the_ninth_day, seed=7),
]

#: Stories whose every declared ending must have a row above.
COMPLETE_DOORS = {"hue-and-cry"}


@pytest.mark.parametrize("case", ENDING_DOORS, ids=[c.label() for c in ENDING_DOORS])
def test_each_registered_ending_is_reached_through_its_own_door(case: EndingDoor) -> None:
    drive(case)


#: Each earned ending's REAL door, walked with the gate unmet: the setup
#: stands the player where the door is and leaves out ONE clause the ending
#: asks, meeting the rest. The door must not open -- the driver fails where
#: it would have locked -- and nothing is locked. (`match`: the driver's own
#: words for why. `clause`: the endings.yaml clause id the setup leaves out
#: -- or a tuple, where one state change fails two at once; the test asserts
#: these are the ONLY reasons the ending is not eligible, so each row proves
#: that clause keeps the door shut. v0.17 T7: every clause of
#: every earned ending has a row -- `test_every_gate_clause_has_an_unearned_row`.)
UnearnedDoor = namedtuple("UnearnedDoor", "ending_id door setup match clause seed",
                          defaults=(11,))

UNEARNED_DOORS = [
    # Cleared: on the Green at the fair, the Magpie never named. The fair is
    # dealt; F3 is not in the hand.
    UnearnedDoor("cleared", Door.card("fair_day", "F3_the_real_magpie", "see_it_done"),
                 _on_the_green_at_the_fair, "is not in the hand", "unmasked"),
    # Cleared after the fair: at the desk the morning after, never named.
    UnearnedDoor("cleared", Door.card("lantern_house_desk", "D4_cleared_at_the_desk",
                                      "hear_it_said"),
                 _after_the_fair_at_the_desk, "does not hold", "unmasked"),
    # Cleared through the badge card, never named: nothing at the desk.
    UnearnedDoor("cleared", Door.card("lantern_house_desk", "D3_the_badge", "clear_my_name"),
                 _at_the_desk_unnamed_with_the_lamps, "does not hold", "unmasked"),
    # (Cleared's `no_wrong_name_standing` holds whenever `unmasked` does --
    # it is `any: [no wrong naming, unmasked]` -- so `unmasked` is its one
    # clause a state can lack.)
    #
    # A Lantern: at the desk in her hours, named rightly, one short of the
    # Watch's good opinion. Nothing at the desk is dealt.
    UnearnedDoor("a_lantern", Door.card("lantern_house_desk", "D3_the_badge", "take_the_badge"),
                 _at_the_desk_short_of_the_lamps, "does not hold", "lamps_kept"),
    # A Lantern: the lamps kept, never named.
    UnearnedDoor("a_lantern", Door.card("lantern_house_desk", "D3_the_badge", "take_the_badge"),
                 _at_the_desk_unnamed_with_the_lamps, "does not hold", "unmasked"),
    # A Lantern: named and the lamps kept, the captain's own file struck
    # against her.
    UnearnedDoor("a_lantern", Door.card("lantern_house_desk", "D3_the_badge", "take_the_badge"),
                 _at_the_desk_having_squeezed_her, "does not hold", "never_squeezed_her"),
    # Honest After All: aboard at dusk, never a wage. The quest never completes.
    UnearnedDoor("honest_after_all", Door.quest("the_evening_barge"), _aboard_without_a_wage,
                 "never completed", "an_honest_wage"),
    # Honest After All with the heart (T6 review round 1): an honest wage, the
    # Magpie named rightly -- so the heist's sacrilege is the Magpie's alone
    # and your own record is clean -- and the Everflame's heart in the pack.
    # (Since T8 fix round 1 a hand on the heart is thieving too, so the heart
    # never shuts it alone: `empty_handed` fails with `never_stole`.)
    UnearnedDoor("honest_after_all", Door.quest("the_evening_barge"), _aboard_with_the_heart,
                 "never completed", ("never_stole", "empty_handed")),
    # Honest After All: one purse lifted where nobody saw (T8 fix round 1).
    UnearnedDoor("honest_after_all", Door.quest("the_evening_barge"),
                 _aboard_having_stolen_unseen, "never completed", "never_stole"),
    # ...and by a squeeze struck and paid (T8 fix round 2).
    UnearnedDoor("honest_after_all", Door.quest("the_evening_barge"),
                 _aboard_having_squeezed, "never completed", "never_stole"),
    # Honest After All: your own face sought on the Quay; on Pell's credit;
    # welshed on Marrow's book.
    UnearnedDoor("honest_after_all", Door.quest("the_evening_barge"),
                 _aboard_and_sought_on_the_quay, "never completed", "a_clean_name"),
    UnearnedDoor("honest_after_all", Door.quest("the_evening_barge"), _aboard_on_pells_credit,
                 "never completed", "square_with_the_fences"),
    UnearnedDoor("honest_after_all", Door.quest("the_evening_barge"), _aboard_having_welshed,
                 "never completed", "square_with_the_fences"),
    # v0.17 T6. Partners: on the Green at the fair, never having found the
    # Magpie out. The fair is dealt; F6 is not in the hand.
    UnearnedDoor("partners", Door.card("fair_day", "F6_the_heist_together", "take_it_together"),
                 _on_the_green_at_the_fair, "is not in the hand", "in_league"),
    # Partners: the heart already taken alone; the Magpie given up.
    UnearnedDoor("partners", Door.card("fair_day", "F6_the_heist_together", "take_it_together"),
                 _partners_with_the_heart_already, "is not in the hand", "nothing_shared_yet"),
    UnearnedDoor("partners", Door.card("fair_day", "F6_the_heist_together", "take_it_together"),
                 _partners_who_gave_them_up, "is not in the hand", "never_gave_them_up"),
    # Partners after the fair: up the Hill by night, never having found the
    # Magpie out. Nothing on the Hill is dealt.
    UnearnedDoor("partners",
                 Door.card("the_last_job", "L1_the_heart_by_night", "take_it_together"),
                 _on_the_hill_after_the_fair, "does not hold", "in_league"),
    # The Legend: home to the Snuffs with the heart never lifted. The getaway
    # never starts.
    UnearnedDoor("the_legend", Door.quest("the_heart_goes_home"), _on_the_green_without_the_heart,
                 "never completed", "the_heart"),
    # The Legend: home with the heart, and held. The arrest takes the heart
    # with it (a `named` item is always hot: effects.py's arrest confiscates
    # every hot unit), so `still_free` never fails alone -- both reasons.
    UnearnedDoor("the_legend", Door.quest("the_heart_goes_home"), _home_with_the_heart_but_held,
                 "never completed", ("the_heart", "still_free")),
    # Guildmaster: sworn and Gannet's lever held, one short of the Hall's
    # good opinion. Nothing at the long table is dealt.
    UnearnedDoor("guildmaster", Door.card("porters_hall", "P1_the_needles", "take_the_chair"),
                 _gannets_measure_short_of_the_hall, "does not hold", "the_hall_trusts_you", seed=2),
    # Guildmaster: never sworn; no measure of Gannet's; the heart; Silas won.
    UnearnedDoor("guildmaster", Door.card("porters_hall", "P1_the_needles", "take_the_chair"),
                 _gannets_measure_unsworn, "does not hold", "sworn", seed=2),
    UnearnedDoor("guildmaster", Door.card("porters_hall", "P1_the_needles", "take_the_chair"),
                 _sworn_and_trusted_without_her_measure, "does not hold", "gannets_measure", seed=2),
    UnearnedDoor("guildmaster", Door.card("porters_hall", "P1_the_needles", "take_the_chair"),
                 _gannets_measure_with_the_heart, "does not hold", "no_heart_in_the_hall", seed=2),
    UnearnedDoor("guildmaster", Door.card("porters_hall", "P1_the_needles", "take_the_chair"),
                 _gannets_measure_after_silas_won, "does not hold", "silas_has_not_won", seed=2),
    # Guildmaster: everything else held on the first night, before the fair
    # (T8 fix round 1, the owner's ruling).
    UnearnedDoor("guildmaster", Door.card("porters_hall", "P1_the_needles", "take_the_chair"),
                 _gannets_measure_before_the_fair, "does not hold", "the_fair_has_come",
                 seed=2),
    # The Dapper's City: Silas's rise complete, the thief never sworn. The
    # fair is dealt; F4 is not in the hand.
    UnearnedDoor("the_dappers_city",
                 Door.card("fair_day", "F4_silas_makes_his_move", "stand_with_him"),
                 _unsworn_when_silas_moves, "is not in the hand", "sworn"),
    # The Dapper's City: sworn, Silas not yet risen (seed 2: on seed 11 his
    # clock fills on its own before the fair); stopped; a name taken to the
    # captain; the Magpie's partner.
    UnearnedDoor("the_dappers_city",
                 Door.card("fair_day", "F4_silas_makes_his_move", "stand_with_him"),
                 _sworn_before_silas_moves, "is not in the hand", "silas_won", seed=2),
    UnearnedDoor("the_dappers_city",
                 Door.card("fair_day", "F4_silas_makes_his_move", "stand_with_him"),
                 _sworn_when_silas_was_stopped, "is not in the hand", "nobody_stopped_him"),
    UnearnedDoor("the_dappers_city",
                 Door.card("fair_day", "F4_silas_makes_his_move", "stand_with_him"),
                 _sworn_when_silas_moves_having_named_one, "is not in the hand",
                 "nobody_stopped_him"),
    UnearnedDoor("the_dappers_city",
                 Door.card("fair_day", "F4_silas_makes_his_move", "stand_with_him"),
                 _sworn_when_silas_moves_as_a_partner, "is not in the hand",
                 "nobody_stopped_him"),
]


def _gate_clause_ids(body: dict) -> list[tuple[str, bool]]:
    """``(clause id, is_completable)`` for every clause `endings.eligible`
    reports on: the named top-level clauses of `requires` and `completable`."""
    from engine.game import endings

    out = [(str(c.get("id")), False)
           for c in endings._clause_list(body.get("requires")) if isinstance(c, dict)]
    out += [(str(c.get("id")), True)
            for c in endings._clause_list(body.get("completable")) if isinstance(c, dict)]
    return out


def _clauses(row: UnearnedDoor) -> tuple[str, ...]:
    return (row.clause,) if isinstance(row.clause, str) else tuple(row.clause)


@pytest.mark.parametrize("row", UNEARNED_DOORS,
                         ids=[f"{r.ending_id}:{r.door.label()}:{r.setup.__name__.strip('_')}"
                              for r in UNEARNED_DOORS])
def test_an_unearned_ending_cannot_lock_at_its_door(row: UnearnedDoor) -> None:
    from endings_driver import drive_ending

    _activate("hue-and-cry")
    try:
        from engine.game import endings
        from engine.game.procgen import new_game_state

        state = new_game_state(seed=row.seed, location_id="tallow_docks")
        with pytest.raises(AssertionError, match=row.match):
            drive_ending(None, row.ending_id, row.door, row.setup, state=state)
        assert endings.locked(state) == endings.NONE_ID
        report = endings.eligible(state)
        assert row.ending_id not in report.eligible
        # The row leaves out exactly the clause it names, and nothing else.
        body = endings.declared()[row.ending_id]
        kinds = dict(_gate_clause_ids(body))
        expected = []
        for clause in _clauses(row):
            reason = str(body["lock_reasons"][clause])
            expected.append(f"cannot complete: {reason}" if kinds[clause] else reason)
        assert report.locked[row.ending_id] == expected, (row.clause, report.locked[row.ending_id])
    finally:
        registry.deactivate()


def test_every_gate_clause_has_an_unearned_row() -> None:
    """v0.17 T7: where an ending has several gate clauses, EACH has a row
    above -- not just one -- except Cleared's `no_wrong_name_standing`, which
    cannot fail while its `requires` holds (see the row comment)."""
    _activate("hue-and-cry")
    try:
        from engine.game import endings

        wanted = {(ending_id, clause)
                  for ending_id, body in endings.declared().items()
                  if ending_id != endings.fail_forward_id()
                  for clause, _ in _gate_clause_ids(body)}
    finally:
        registry.deactivate()
    covered = {(r.ending_id, c) for r in UNEARNED_DOORS for c in _clauses(r)}
    unfailable = {("cleared", "no_wrong_name_standing")}
    assert wanted - covered == unfailable, sorted(wanted - covered)
    assert covered <= wanted, sorted(covered - wanted)


# -- The Rope, all in one place (v0.17 T7) --------------------------------
#
# Its two doors are ENDING_DOORS rows above (hp 0 held at the fair: death.yaml
# `terminal`; the hanging: the_gallows G1). These are the deaths that are NOT
# the Rope, through the same calendar walk the doors use: the fair raised by
# `advance_time`, the arrest by the quay's charge. (tests/test_hue_and_cry.py's
# "v0.17 Task 2" section has the respawn's own details: the purse, the wound,
# the stay and the fine kept.)


def _free_at_the_fair(state) -> None:
    _on_the_green_at_the_fair(state)


def _free_on_the_first_day(state) -> None:
    state.location_id = "tallow_docks"


@pytest.mark.parametrize("setup,held,wakes_at", [
    (_free_on_the_first_day, False, "the_snuffs"),
    (_free_at_the_fair, False, "the_snuffs"),
    (_held_when_the_fair_comes, True, "lantern_house"),
], ids=["free-an-ordinary-day", "free-at-the-fair", "held-the-day-before"])
def test_a_death_that_is_not_the_rope_respawns(setup, held, wakes_at) -> None:
    """Ordinary hp 0 is a setback, not an ending: the thief wakes (still
    held, if held -- dying is no way out of the cells), nothing is locked,
    and no epilogue shows. Only held AND at the fair is the Rope."""
    _activate("hue-and-cry")
    try:
        from engine.game import encounter, endings, epilogue
        from engine.game.effects import apply_effect
        from engine.game.procgen import new_game_state
        from engine.world import law

        state = new_game_state(seed=11, location_id="tallow_docks")
        setup(state)
        assert law.in_custody(state) is held
        apply_effect(state, {"type": "hp", "delta": -int(state.stats.hp)})
        death = encounter.check_death(state)
        assert death and death["died"] and not death["terminal"], death
        assert bool(death.get("kept_in_custody")) is held
        assert law.in_custody(state) is held
        assert state.location_id == wakes_at
        assert state.stats.hp > 0 and not state.ended
        assert endings.locked(state) == endings.NONE_ID
        assert epilogue.for_state(state) is None
    finally:
        registry.deactivate()


def test_the_ropes_two_doors_are_registered() -> None:
    """The death at the fair and the hanging, both driven above."""
    doors = {c.door.label() for c in ENDING_DOORS if c.ending_id == "the_rope"}
    assert doors == {"death", "card:the_gallows/G1_the_last_morning/head_up"}, doors


@pytest.mark.parametrize("slug", sorted(COMPLETE_DOORS))
def test_a_complete_story_registers_a_door_for_every_ending(slug: str) -> None:
    _activate(slug)
    try:
        from engine.game import endings as endings_module

        declared = set(endings_module.declared())
    finally:
        registry.deactivate()
    registered = {c.ending_id for c in ENDING_DOORS if c.slug == slug}
    assert declared - registered == set(), (
        f"{slug}: endings with no registered door: {sorted(declared - registered)}"
    )
    assert registered - declared == set(), (
        f"{slug}: doors registered for endings it does not declare: "
        f"{sorted(registered - declared)}"
    )


# -- the graph shape, through a real turn --------------------------------


@pytest.mark.parametrize("slug", ["clockwork-dark", "neon-city", "hue-and-cry"])
def test_a_graph_story_reports_its_ending_on_the_turn_it_happens(slug: str) -> None:
    """
    Through ``run_turn``, not through the effect dispatcher.

    This is the difference the whole file exists for: the effects applied
    correctly the entire time, and no player could reach them. It also pins the
    payload ordering -- quest evaluation runs BEFORE the client dict is built,
    so a quest-fired ending is reported on its own turn rather than the next.
    """
    _activate(slug)
    try:
        from engine.scenes.default_state import SessionStore, run_turn
        import engine.scenes.default_state as ds

        llm = lambda _m: json.dumps(  # noqa: E731
            {
                "narration": "The hour closes over the whole of it, and holds.",
                "choices": [{"id": "a", "text": "Wait"}],
            }
        )
        session = SessionStore().create(seed=7, llm_fn=llm)

        def _ending_quest(sess):
            _finish_chain(sess.engine.state)
            return [{"kind": "completed", "quest_id": "finale", "text": "Done."}]

        original = ds._evaluate_quests
        ds._evaluate_quests = _ending_quest
        try:
            turn = run_turn(session, "The player chooses: Wait")
        finally:
            ds._evaluate_quests = original

        assert "ending" in turn, (
            f"{slug}: the story ended on this turn and the payload did not say so"
        )
        assert turn["ending"].get("title")
    finally:
        registry.deactivate()


# -- the deck shape, through the director --------------------------------


def test_the_wicked_garden_reaches_its_finale_deck_by_playing() -> None:
    """
    The Garden's only ``ending_lock`` is on a card in ``day_09_finale``.

    Nothing dealt that deck, so the largest body of authored prose in the repo
    ended in a deck the player could never see. This walks the scheduling rule
    that now deals it.
    """
    _activate("wicked-garden")
    try:
        from engine.content import deck, director
        from engine.game.state import GameState

        state = GameState(location_id="mortal_threshold")
        # Day 9's deck is gated on the day it belongs to.
        state.meters["garden_days"] = 9.0
        while state.world_day < 9:
            from engine.game.clock import advance_time

            advance_time(state, 24)

        # Every earlier deck has been played by the time the finale is due.
        for day in range(9):
            for deck_id in deck.deck_ids():
                if deck_id.startswith(f"day_{day:02d}"):
                    state.flags[f"{director.PLAYED_FLAG_PREFIX}{deck_id}"] = True

        deck_id, _forced, source = director.due(state)
        assert deck_id == "day_09_finale", (
            f"the finale deck is not what comes due on day 9; got {deck_id!r}"
        )
        assert source == "scheduled"
    finally:
        registry.deactivate()


def test_the_finale_deck_actually_carries_the_lock() -> None:
    """
    The other half: the deck that comes due is the one holding the ending.

    Asserted against the loaded deck rather than the YAML, so a card whose
    effect was renamed or dropped fails here rather than at the end of
    somebody's run.
    """
    _activate("wicked-garden")
    try:
        from engine.content import deck

        finale = deck.load_deck("day_09_finale")
        assert finale is not None

        kinds = {
            str(effect.get("type"))
            for card in finale.cards
            for beat in card.beats
            for effect in (
                (beat.get("gate") or {}).get("on_pass", {}).get("effects", [])
                or beat.get("effects")
                or []
            )
            if isinstance(effect, dict)
        }
        assert "ending_lock" in kinds, (
            "day_09_finale no longer locks an ending -- the Garden has no "
            "authored way to end again"
        )
    finally:
        registry.deactivate()


# -- the hybrid shape ----------------------------------------------------


def test_the_long_cons_clock_can_fill_from_the_graph() -> None:
    """
    ``the_frame`` was deadlocked at 1 of 4 segments.

    Its three advance rules key on ``heat >= 55``, ``standing <= 20`` and one
    flag -- and the ONLY content that wrote heat or standing was the deck the
    clock is supposed to force. The clock could not fill without the scene, and
    the scene could not arrive without the clock. The case quest moves both
    meters now, so playing the case is what brings the car to the kerb.
    """
    _activate("the-long-con")
    try:
        from engine.game import clocks
        from engine.game.state import GameState

        state = GameState(location_id="the_office")
        state.meters["heat"] = 60.0
        state.meters["standing"] = 15.0
        state.flags["nf_opened_the_cold_room"] = True

        clocks.resolve(state)

        assert clocks.value_of(state, "the_frame") >= 3, (
            "the frame cannot fill from graph play; it is still waiting on the "
            "deck it is supposed to force"
        )
    finally:
        registry.deactivate()


def test_the_long_cons_case_quest_ends_the_story() -> None:
    """The quest had no ``on_complete`` at all: four stages, then nothing."""
    _activate("the-long-con")
    try:
        import yaml

        raw = yaml.safe_load(
            open(
                "games/the-long-con/data/quests/the_case/"
                "the_dead_man_photographed.yaml",
                encoding="utf-8",
            )
        )
        effects = [
            str(e.get("type"))
            for e in ((raw.get("on_complete") or {}).get("effects") or [])
            if isinstance(e, dict)
        ]
        assert "ending_lock" in effects and "ending_module" in effects, (
            "closing the case does not end the story"
        )
    finally:
        registry.deactivate()
