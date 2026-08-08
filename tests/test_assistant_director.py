"""
Assistant director tests.

Two properties matter. First, a calm turn must behave exactly like the flat
``help_probability`` roll it replaces, so wiring the director in cannot change
a quiet session. Second, low trust must be able to produce advice that is
wrong — that is the design, not a defect.
"""

from __future__ import annotations

import random

import pytest

from engine.agents.assistant_director import (
    FLAG_GIFT_TURN,
    FLAG_LAST_TURN,
    INTENT_GIFT,
    INTENT_HINT,
    INTENT_QUIP,
    INTENT_SILENT,
    AssistantDirector,
    record_appearance,
)
from engine.game.state import GameState, Wound


class _Scripted(random.Random):
    """Returns a fixed sequence from ``random()``, then repeats the last value."""

    def __init__(self, values: list[float]) -> None:
        super().__init__(0)
        self._values = list(values)

    def random(self) -> float:  # noqa: D102
        return self._values.pop(0) if len(self._values) > 1 else self._values[0]


@pytest.fixture
def director() -> AssistantDirector:
    return AssistantDirector()


@pytest.fixture
def calm() -> GameState:
    """Full health, no encounter, dormant phase — the default session."""
    return GameState(rng_seed=7)


# -- backwards compatibility ------------------------------------------------


def test_a_calm_turn_rolls_exactly_help_probability(director, calm):
    """
    The compatibility contract.

    No struggle, no drama, no recent appearance: the score must be the bare
    ``help_probability``, and the appear roll must be the FIRST draw, so this
    is bit-identical to the legacy ``should_assistant_speak``.
    """
    calm.assistant_mind.help_probability = 0.4

    just_over = director.decide(calm, rng=_Scripted([0.41]))
    just_under = director.decide(calm, rng=_Scripted([0.39]))

    assert just_over.appear is False
    assert just_over.intent == INTENT_SILENT
    assert just_under.appear is True
    assert just_over.score == pytest.approx(0.4)


def test_the_director_matches_the_legacy_roll_on_a_calm_turn(director, calm):
    """
    Run BOTH and compare, rather than asserting the contract in prose.

    ``engine/agents/assistant.py`` still carries ``should_assistant_speak`` and
    its docstring points here. If someone changes the director's score maths
    and a calm session starts behaving differently, this is what says so —
    a comment claiming equivalence proves nothing.
    """
    from engine.agents.assistant import should_assistant_speak

    for probability in (0.0, 0.25, 0.5, 0.75, 1.0):
        calm.assistant_mind.help_probability = probability
        for draw in (0.0, 0.24, 0.26, 0.5, 0.74, 0.76, 1.0):
            legacy = should_assistant_speak(probability, _Scripted([draw]))
            directed = director.decide(calm, rng=_Scripted([draw])).appear
            assert directed is legacy, (
                f"diverged at help_probability={probability}, draw={draw}"
            )


def test_the_same_seed_replays_the_same_decision(director):
    def decide() -> tuple[bool, str]:
        state = GameState(rng_seed=31337)
        result = AssistantDirector().decide(state)
        return result.appear, result.intent

    assert decide() == decide()


# -- appearing when it matters ----------------------------------------------


def test_a_dying_player_gets_a_companion_that_is_not_indifferent(director, calm):
    calm.assistant_mind.help_probability = 0.05
    calm.stats.hp = 2  # 10% of max

    decision = director.decide(calm, rng=_Scripted([0.5]))

    assert decision.appear is True
    assert decision.score >= director.RESCUE_FLOOR


def test_struggle_signals_do_not_stack_past_the_worst_one(director, calm):
    """Wounded AND starving is one bad situation, not two."""
    calm.stats.hp = 2
    calm.stats.stamina = 1
    calm.wounds.append(Wound(id="w", text="Gashed", check_penalty=-2))

    assert director._struggle(calm) <= 1.0


def test_an_encounter_raises_the_odds(director, calm):
    calm.assistant_mind.help_probability = 0.1
    quiet = director.decide(calm, rng=_Scripted([0.3])).score
    calm.encounter = {"id": "wolf", "hp": 4}
    fighting = director.decide(calm, rng=_Scripted([0.3])).score
    assert fighting > quiet


def test_drama_rises_with_the_evil_phase(director):
    dormant = GameState(evil_progress=0.0)
    consuming = GameState(evil_progress=0.9)
    assert director._drama(consuming) > director._drama(dormant)


def test_speaking_twice_running_is_discouraged(director, calm):
    calm.assistant_mind.help_probability = 0.5
    calm.turn_number = 10
    before = director.decide(calm, rng=_Scripted([0.4])).score

    calm.flags[FLAG_LAST_TURN] = 10
    after = director.decide(calm, rng=_Scripted([0.4])).score

    assert after == pytest.approx(before - director.RECENT_PENALTY)


# -- reliability: the feature -----------------------------------------------


def test_zero_trust_makes_the_companion_barely_better_than_a_coin(director, calm):
    calm.assistant_mind.help_probability = 1.0
    calm.assistant_mind.trust_level = 0.0

    decision = director.decide(calm, rng=_Scripted([0.0]))

    assert decision.appear is True
    assert decision.reliability == pytest.approx(0.45)


def test_full_trust_makes_it_almost_always_right(director, calm):
    calm.assistant_mind.help_probability = 1.0
    calm.assistant_mind.trust_level = 100.0

    decision = director.decide(calm, rng=_Scripted([0.0]))

    assert decision.reliability == pytest.approx(0.95)


def test_a_distrusted_companion_can_genuinely_mislead(director, calm):
    """``reliable=False`` is a real, reachable outcome."""
    calm.assistant_mind.help_probability = 1.0
    calm.assistant_mind.trust_level = 0.0

    # First draw appears, second draw exceeds reliability 0.45.
    decision = director.decide(calm, rng=_Scripted([0.0, 0.9]))

    assert decision.appear is True
    assert decision.reliable is False


def test_a_trusted_companion_is_reliable_on_the_same_draw(director, calm):
    calm.assistant_mind.help_probability = 1.0
    calm.assistant_mind.trust_level = 100.0
    decision = director.decide(calm, rng=_Scripted([0.0, 0.9]))
    assert decision.reliable is True


# -- intent -----------------------------------------------------------------


def test_a_calm_appearance_is_just_a_quip(director, calm):
    calm.assistant_mind.help_probability = 1.0
    calm.awareness = 0.0
    assert director.decide(calm, rng=_Scripted([0.0])).intent == INTENT_QUIP


def test_a_struggling_player_gets_help_not_banter(director, calm):
    calm.assistant_mind.help_probability = 1.0
    calm.assistant_mind.trust_level = 0.0  # too low to be given anything
    calm.stats.hp = 5

    assert director.decide(calm, rng=_Scripted([0.0])).intent == INTENT_HINT


def test_a_trusted_companion_hands_over_the_right_item(director, calm):
    calm.assistant_mind.help_probability = 1.0
    calm.assistant_mind.trust_level = 80.0
    calm.stats.hp = 5

    decision = director.decide(calm, rng=_Scripted([0.0]))

    assert decision.intent == INTENT_GIFT
    assert decision.gift_item["id"] == "bandage_poultice"


def test_no_gift_when_there_is_no_right_item(director, calm):
    """A bandage for a player who is merely bored is why gifts stop landing."""
    calm.assistant_mind.trust_level = 90.0
    calm.encounter = {"id": "wolf"}  # struggle, but nothing actually wrong
    assert director._pick_gift(calm) is None


def test_gifts_are_on_a_cooldown(director, calm):
    calm.assistant_mind.help_probability = 1.0
    calm.assistant_mind.trust_level = 80.0
    calm.stats.hp = 5
    calm.turn_number = 3
    calm.flags[FLAG_GIFT_TURN] = 1  # within GIFT_COOLDOWN

    assert director.decide(calm, rng=_Scripted([0.0])).intent == INTENT_HINT


# -- bookkeeping ------------------------------------------------------------


def test_deciding_is_side_effect_free(director, calm):
    """
    A previewed decision must not burn the cooldown.

    Retries and rejected drafts re-decide; if deciding recorded an appearance
    the companion would fall silent for reasons the player never saw.
    """
    calm.assistant_mind.help_probability = 1.0
    calm.turn_number = 5
    director.decide(calm, rng=_Scripted([0.0]))
    assert FLAG_LAST_TURN not in calm.flags


def test_recording_an_appearance_sets_the_cooldowns(director, calm):
    calm.assistant_mind.help_probability = 1.0
    calm.assistant_mind.trust_level = 80.0
    calm.stats.hp = 5
    calm.turn_number = 5

    decision = director.decide(calm, rng=_Scripted([0.0]))
    record_appearance(calm, decision)

    assert calm.flags[FLAG_LAST_TURN] == 5
    assert calm.flags[FLAG_GIFT_TURN] == 5


def test_recording_a_silent_turn_records_nothing(director, calm):
    calm.assistant_mind.help_probability = 0.0
    decision = director.decide(calm, rng=_Scripted([1.0]))
    record_appearance(calm, decision)
    assert FLAG_LAST_TURN not in calm.flags


def test_cooldown_flags_survive_a_save(director, calm):
    calm.turn_number = 5
    calm.flags[FLAG_LAST_TURN] = 5
    restored = GameState.from_dict(calm.to_save_dict())
    assert restored.flags[FLAG_LAST_TURN] == 5
