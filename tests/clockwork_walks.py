"""
The Clockwork Dark's card-only walks (v0.25.0 §4.4, §12.2): for each ending, a
run from a new game to its lock in which no narrative flag is raised by the
narrator (`QuestEngine.set_narrative_flag` patched to fail by the test) and no
disposition is written. Every stage completes by a dealt card, a place, an
hour, an item, a day, a stat or an engine-written standing.

A WALK is the turn's own order around the narration -- quests, the deal, each
dealt card answered, quests again -- an hour at a time, the player fed through
`apply_effect` (survival is not what is being walked). A stat or a standing the
spec's path earns by work or play (awareness from what the player looks at,
the saints' standing from the shrine shift, the tinkers' from Ilya's) is
written as the effect that work writes. Time moves only through
`advance_time`; an event the path needs that the calendar would bring (the
press) is forced through the world tick's own force hook.

Outside its hours a walk steps to a place no deck reads (`AWAY`) and takes a
turn there before it jumps the clock (ruling B2), so `director.rearm` sees a
repeatable door deck's trigger fall and the deck comes round again.

The condition helpers (`stage`, `done`, `locked`) and `inside_window` live
once, in `scripts/simulate_doors.py` (ruling M13, moved there in v0.25.0
T10), and are imported from it here. That import loads all of
`scripts/simulate.py` (the door harness reuses its `Simulation`) and puts
`scripts/` on `sys.path`, so every walk test pays for it; accepted (T10's
review, Minor 7).

Version: v0.1.2 [2026-10-30]
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from scripts.simulate_doors import done, inside_window, locked, stage

#: Every door card's NON-locking answer: a walk never locks by an unlisted card.
DEFAULT_ANSWERS = {
    "H1_the_question": "not_yet", "W1_the_list": "keep_it", "M1_strike_the_name": "not_yet",
    "S1_choose_what": "not_yet", "S2_pay_it": "not_yet", "J1_the_pin": "keep_it",
    "L2_the_weller_boy": "speak_up", "V2_the_vote": "stay", "L7_answer_her": "refuse",
    "T3_take_it_or_dont": "leave_it", "P1_a_name_on_the_list": "let_it_be",
}

#: Door decks with a person (§6.6), for the presence sweep.
DOOR_DECKS = {
    "the_morning_firing": "npc_maris", "the_count_kept": "npc_wenna",
    "the_muster_roll": "npc_sera", "the_price": "npc_ilya",
}

#: Where a walk waits out the hours outside its window: no deck's `when:` names it (ruling B2).
AWAY = "well_row"


# -- the walk ------------------------------------------------------------------------------------------

class Walk:
    """One run from a new game, played by cards, places, hours, items, days and engine standings only."""

    def __init__(self, seed: int = 7, answers: Optional[dict[str, str]] = None) -> None:
        from engine.game.procgen import new_game_state
        from engine.memory.ledger import StoryLedger

        self.state = new_game_state(seed=seed)
        self.ledger = StoryLedger()
        self.answers = {**DEFAULT_ANSWERS, **(answers or {})}
        self.explicit = frozenset(answers or {})
        self.dealt: list[str] = []

    def give(self, **row: Any) -> None:
        """One effect row through `apply_effect`."""
        from engine.game.effects import apply_effect

        apply_effect(self.state, dict(row))

    def _fed(self) -> None:
        if self.state.hunger > 0:
            self.give(type="hunger", delta=-self.state.hunger)
        if self.state.stats.hp < self.state.stats.max_hp:
            self.give(type="hp", delta=self.state.stats.max_hp - self.state.stats.hp)
        if self.state.stats.stamina < self.state.stats.max_stamina // 2:
            self.give(type="stamina", delta=self.state.stats.max_stamina)

    def turn(self) -> None:
        """What a turn does around the narration: quests, the deal, each dealt card answered, quests."""
        from engine.content import director
        from engine.game.quests import QuestEngine

        QuestEngine.evaluate(self.state, self.ledger)
        director.ensure_scene(self.state, ledger=self.ledger)
        while director.active(self.state):
            card = director.current_card(self.state)
            offered = [o["id"] for o in director.options(self.state)]
            chosen = self.answers.get(card.id, "")
            if card.id in self.explicit:
                # A walk's own answer is the point of the walk: it must be on offer, never a fallback.
                assert chosen in offered, f"{card.id}: the walk's answer {chosen!r} is not offered: {offered}"
            elif chosen not in offered:
                chosen = offered[-1] if card.id in DEFAULT_ANSWERS else ""
            out = director.resolve(self.state, chosen=chosen, ledger=self.ledger)
            assert out.get("ok"), out
            self.dealt.append(card.id)
        QuestEngine.evaluate(self.state, self.ledger)

    def until(self, condition: Any, *, at: str, hours: tuple[int, int] = (0, 24), max_days: int = 40) -> None:
        """Stand at `at`, a turn an hour inside `hours`, until `condition` holds."""
        from engine.game.clock import advance_time
        from engine.game.quests import evaluate_condition

        deadline = self.state.world_day + max_days
        start, end = hours
        while not evaluate_condition(self.state, condition, ledger=self.ledger):
            assert self.state.world_day <= deadline, (
                f"never held in {max_days} days: {condition} at {at}; dealt {self.dealt[-12:]}; "
                f"quests {[(q, r) for q, r in self.state.quests.items() if q in str(condition)]}; "
                f"stats {self.state.stats}; doom {self.state.evil_progress:.3f}")
            self._fed()
            hour = self.state.world_hour
            if inside_window(hour, start, end):
                self.state.location_id = at
                self.turn()
                advance_time(self.state, 1.0)
            else:
                self.state.location_id = AWAY            # ruling B2: the trigger seen to fall
                self.turn()
                advance_time(self.state, float((start - hour) % 24))


# -- the eight walks -----------------------------------------------------------------------------------

def hearth(w: Walk) -> None:
    w.until(stage("bakery_apprentice", 1), at="edgewood_bakery", hours=(7, 11))
    w.until(stage("bakery_apprentice", 2), at="edgewood_bakery", hours=(4, 7))
    w.until(done("bakery_apprentice"), at="edgewood_bakery", hours=(8, 11))
    w.give(type="item", item_id="winter_ration", qty=1)                       # 22 gold, economy.yaml
    w.until({"quest_state": {"quest": "banking_the_fire", "status": "active"}}, at="edgewood_bakery")
    w.until(stage("banking_the_fire", 1), at="edgewood_bakery", hours=(4, 10))
    w.until(locked("the_hearth_holds"), at="edgewood_bakery", hours=(4, 10))


def stay_anyway(w: Walk) -> None:
    w.give(type="awareness", delta=41)                                        # the Hearth's gate shut
    w.give(type="item", item_id="winter_ration", qty=1)
    w.until({"quest_state": {"quest": "banking_the_fire", "status": "active"}}, at="edgewood_square")
    w.until(stage("banking_the_fire", 1), at="edgewood_bakery", hours=(4, 10))
    w.until(locked("the_dark_keeps_its_hours"), at="edgewood_bakery", hours=(4, 10))


def witness(w: Walk) -> None:
    w.give(type="awareness", delta=30)
    w.until({"arc_unlocked": "whisper"}, at="edgewood_square", max_days=30)
    w.until(stage("childs_drawing", 1), at="edgewood_square", hours=(9, 17))
    w.until(stage("childs_drawing", 2), at="edgewood_square", hours=(9, 17))
    w.until(done("childs_drawing"), at="edgewood_square", hours=(9, 17))
    w.give(type="reputation", faction="unnamed_saints", delta=30)            # the shrine's shifts (+3 each)
    w.until({"min_day": 27}, at="edgewood_square", max_days=30)
    w.until(locked("the_long_witness"), at="edgewood_shrine", hours=(18, 22))


def march(w: Walk) -> None:
    from engine.world.world_sim import WorldSim

    w.give(type="awareness", delta=20)
    w.until({"arc_unlocked": "march"}, at="millhaven_gate", hours=(8, 12))
    WorldSim.on_tick(w.state, hours=0.0, force=["militia_press"])            # the press, by the force hook
    w.until(stage("militia_press", 1), at="edgewood_square", hours=(9, 12))
    w.until(stage("militia_press", 2), at="edgewood_square", hours=(9, 12))
    w.until(done("militia_press"), at="edgewood_square", hours=(9, 12))
    w.give(type="reputation", faction="militia", delta=20)                   # the gate's shifts
    w.until(locked("the_counted_march"), at="millhaven_gate", hours=(8, 12))


def _naming(w: Walk) -> None:
    w.give(type="awareness", delta=52)
    w.give(type="item", item_id="brass_shard", qty=1)                        # the works' find
    # G1 waits for `spreading` itself (T9 fix round 1), so the evenings in the square run until the
    # doom gets there: up to 60 days.
    w.until(stage("naming_the_wound", 1), at="edgewood_square", hours=(19, 23), max_days=60)
    w.until(stage("naming_the_wound", 2), at="edgewood_square", hours=(19, 23))
    w.until(done("naming_the_wound"), at="edgewood_square", hours=(19, 23))


def named_wound(w: Walk) -> None:
    _naming(w)
    w.give(type="awareness", delta=10)                                        # 62
    w.until(stage("what_edgewood_keeps", 1), at="edgewood_square", hours=(10, 16))
    w.until(stage("what_edgewood_keeps", 2), at="edgewood_square", hours=(10, 16))
    w.until(done("what_edgewood_keeps"), at="edgewood_square", hours=(10, 16))
    w.until(stage("the_last_quiet_thing", 1), at="edgewood_bakery", hours=(4, 7))
    # The batch asks craft 11. Seed 7 reaches it holding 9 (the wayfarer's 8, plus one gain on the
    # way not traced here): pinned, so a drift in the run's craft fails here rather than being topped up.
    assert w.state.stats.craft == 9, w.state.stats.craft
    w.give(type="craft", delta=2)
    w.until(stage("the_last_quiet_thing", 2), at="edgewood_bakery", hours=(8, 12))
    w.until(locked("the_named_wound"), at="edgewood_bakery", hours=(4, 10))


def price(w: Walk) -> None:
    _naming(w)
    w.give(type="awareness", delta=6)                                         # 58
    w.until(stage("the_sacrifice", 1), at="edgewood_square", hours=(10, 15))
    w.until(stage("the_sacrifice", 2), at="edgewood_square", hours=(10, 15))
    w.until(locked("the_price_asked"), at="edgewood_square", hours=(10, 15))


def pin(w: Walk) -> None:
    _naming(w)
    w.give(type="awareness", delta=8)                                         # 60
    w.until(stage("the_ninth_pin", 1), at="tinker_caravan", hours=(9, 15))
    w.give(type="reputation", faction="tinkers", delta=10)                   # Ilya's shifts and trade
    w.until(stage("the_ninth_pin", 2), at="tinker_caravan", hours=(9, 15))
    w.until(done("the_ninth_pin"), at="tinker_caravan", hours=(9, 15))
    w.give(type="item", item_id="road_map", qty=1)                           # 15 gold, economy.yaml
    w.until(stage("the_heartland_road", 1), at="millhaven_gate", hours=(10, 15))
    w.until(stage("the_heartland_road", 2), at="the_join", hours=(10, 15))
    w.until(locked("the_pin_and_the_join"), at="the_join", hours=(10, 15))


def stopped_wheel(w: Walk) -> None:
    w.until(locked("the_stopped_wheel"), at="edgewood_bakery", max_days=120)


#: ending id -> (walk, its answers).
WALKS: dict[str, tuple[Callable[[Walk], None], dict[str, str]]] = {
    "the_hearth_holds": (hearth, {"H1_the_question": "stay"}),
    "the_dark_keeps_its_hours": (stay_anyway, {"H1_the_question": "stay_anyway"}),
    "the_long_witness": (witness, {"W1_the_list": "give_it"}),
    "the_counted_march": (march, {"M1_strike_the_name": "strike_it"}),
    "the_named_wound": (named_wound, {"Q1_tell_her_or_dont": "tell_her"}),
    "the_price_asked": (price, {"S1_choose_what": "offer_the_shard", "S2_pay_it": "pay_the_shard"}),
    "the_pin_and_the_join": (pin, {"T3_take_it_or_dont": "take_it", "J1_the_pin": "set_it"}),
    "the_stopped_wheel": (stopped_wheel, {}),
}

__all__ = ["AWAY", "DEFAULT_ANSWERS", "DOOR_DECKS", "WALKS", "Walk", "done", "inside_window", "locked", "stage"]
