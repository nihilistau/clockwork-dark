"""
The narrator may not walk an absent character into the scene.

THE LEAK THESE PIN DOWN. The Storyteller persona has always said "Never
introduce a named character who is not present in WORLD STATE", and until now
nothing enforced it. Measured on a fresh run (seed 7, ``forest_clearing``,
turn 0, empty ledger) the live model wrote:

    "You turn your back on Ilya's lantern and begin walking, keeping low where
     the shadows of the salt-sheds stretch long across the mud..."

``npc_ilya`` is the tinker, three locations away, imported wholesale out of the
few-shot examples. The turn passed the evaluator and reached the player. The
per-turn schema already refuses to let ``npc_voices`` name him -- the enum is
built from who is actually in the room -- so the prose was the only channel the
model could smuggle him through.

The other half of these tests is precision. A gate that rejects good turns is
worse than the leak: it burns a retry, delays the player, and teaches nobody
anything. So the cases below also pin what must NOT fire.
"""

from __future__ import annotations

from typing import Iterator

import pytest

from engine.agents.cast import absent_cast, find_intrusion
from engine.agents.evaluator import StorytellerEvaluator
from engine.game.state import GameState
from engine.memory.ledger import StoryLedger
from engine.game.procgen import new_game_state

THE_LEAK = (
    "You turn your back on Ilya's lantern and begin walking, keeping low where "
    "the shadows stretch long across the mud, and the birch closes behind you "
    "like a door drawn quietly to."
)


def _parsed(narration: str = "...") -> dict:
    return {
        "narration": narration,
        "choices": [{"id": "a", "text": "walk on"}, {"id": "b", "text": "wait"}],
    }


@pytest.fixture
def clearing() -> GameState:
    """The measured run: forest_clearing at turn 0, nobody met."""
    return new_game_state(player_name="Traveler", archetype="hearthkeeper", seed=7)


# -- 1. the leak itself ----------------------------------------------------


def test_an_absent_npc_named_in_the_prose_fails_the_turn(clearing):
    result = StorytellerEvaluator().evaluate(
        THE_LEAK,
        _parsed(THE_LEAK),
        tool_receipts=[],
        absent_cast=absent_cast(clearing, StoryLedger()),
    )
    assert result.cast == 0.0
    assert result.passed is False


def test_the_retry_is_told_which_name_to_remove(clearing):
    """
    "Do not invent people" is unactionable -- the model cannot tell which of the
    names it wrote was the wrong one. The note has to say Ilya.
    """
    result = StorytellerEvaluator().evaluate(
        THE_LEAK,
        _parsed(THE_LEAK),
        tool_receipts=[],
        absent_cast=absent_cast(clearing, StoryLedger()),
    )
    assert any("Ilya" in note for note in result.notes)


def test_the_criterion_can_fail_a_turn_that_is_otherwise_good(clearing):
    """
    Weight alone would not do it: the leak was well-written prose with valid
    choices and no mechanical claim, and it scored a comfortable pass. The cast
    criterion is a hard floor for the same reason the receipts one is.
    """
    evaluator = StorytellerEvaluator()
    clean = evaluator.evaluate(THE_LEAK, _parsed(THE_LEAK), tool_receipts=[])
    assert clean.passed is True
    assert clean.overall > StorytellerEvaluator.PASS_THRESHOLD


def test_a_present_npc_may_be_named(clearing):
    """Brindle the cat is in the clearing. Naming her is the correct behaviour."""
    narration = (
        "Brindle washes a paw on the fallen birch and does not look up when you "
        "stand, which is its own kind of answer. The mist has not lifted."
    )
    result = StorytellerEvaluator().evaluate(
        narration,
        _parsed(narration),
        tool_receipts=[],
        absent_cast=absent_cast(clearing, StoryLedger()),
    )
    assert result.cast == 1.0
    assert result.passed is True


# -- 2. story-agnostic -----------------------------------------------------


def test_a_story_with_no_roster_is_unaffected(story_declaring_nothing):
    """
    No NPCs, no criterion. The check must never be the reason a story that
    ships no scheduled cast cannot pass a turn.

    The absence is built rather than borrowed: ``story_declaring_nothing``
    activates a story that declares no ``paths.*`` at all, because an
    unactivated engine still answers ``paths.npc_schedules`` from whichever
    story is active -- which is how a "no roster" assertion could quietly be an
    assertion about the flagship's roster.
    """
    bare = GameState()
    assert bare.procgen.npcs == []
    cast = absent_cast(bare, StoryLedger())
    assert cast == {}
    result = StorytellerEvaluator().evaluate(
        "A name walks past: Ilya, Maris, Brindle, anybody at all.",
        _parsed(),
        tool_receipts=[],
        absent_cast=cast,
    )
    assert result.cast == 1.0


@pytest.fixture
def garden() -> Iterator[GameState]:
    from engine.games.registry import activate, deactivate

    activate("wicked-garden")
    try:
        yield GameState(rng_seed=42, location_id="heart_grove")
    finally:
        deactivate()


def test_an_agent_companion_is_not_scored_as_an_absent_npc(garden):
    """
    Sophia is The Wicked Garden's companion and an AGENT, not a scheduled NPC:
    she has goals and a roster entry, not a routine, and where she is is a thing
    she decides. She is deliberately absent from the schedule file, so she must
    never appear in the absent cast -- narrating her is the story working.
    """
    cast = absent_cast(garden, StoryLedger())
    assert all("sophia" not in npc_id.lower() for npc_id in cast)
    narration = (
        "Sophia does not turn around. The petals go on falling through the light "
        "that is not coming from anywhere, and she lets the silence do the work."
    )
    result = StorytellerEvaluator().evaluate(
        narration, _parsed(narration), tool_receipts=[], absent_cast=cast
    )
    assert result.cast == 1.0


def test_a_crowd_id_is_never_a_named_character(garden):
    """
    ``bloomkin_generic`` and ``court_generic`` are crowds. Their tokens are
    species and place words that belong in ordinary prose, and scoring them
    would fail every scene that mentions the court.
    """
    cast = absent_cast(garden, StoryLedger())
    assert all("generic" not in npc_id for npc_id in cast)


# -- 3. precision ----------------------------------------------------------


def test_a_name_the_player_used_is_not_the_narrators_intrusion():
    """
    "Ask about Ilya" must be answerable. Repeating a name the player supplied is
    not an introduction.
    """
    cast = {"npc_ilya": ("Ilya",)}
    assert find_intrusion(THE_LEAK, cast) == "Ilya"
    assert find_intrusion(THE_LEAK, cast, player_action="ask about Ilya") is None


def test_a_possessive_still_counts():
    """The measured leak was "Ilya's lantern", not "Ilya"."""
    assert find_intrusion("You turn from Ilya's lantern.", {"npc_ilya": ("Ilya",)})


def test_an_ordinary_word_that_is_also_a_name_does_not_fire():
    """
    A roster that names somebody "Mother Briar" must not fail every narration
    containing a briar or a mother. The full name is matched; the common token
    on its own is not a sighting.
    """
    cast = absent_cast_forms("mother_briar", "")
    assert "Mother" not in cast
    assert find_intrusion("The briar closes over the path.", {"x": cast}) is None
    assert find_intrusion("Mother Briar rises through the roots.", {"x": cast})


def test_a_rank_is_not_treated_as_a_name(clearing):
    """
    Measured on the live roster: ``Sergeant Sera Venn`` used to contribute
    "Sergeant", which would have failed any scene mentioning the militia. The
    derivation walks past the rank to the given name.
    """
    forms = absent_cast(clearing, StoryLedger())["npc_sera"]
    assert "Sergeant" not in forms
    assert "Sera" in forms
    assert find_intrusion("A Sergeant leans on the gate post.", {"npc_sera": forms}) is None
    assert find_intrusion("Sera leans on the gate post.", {"npc_sera": forms}) == "Sera"


def test_a_role_worn_as_a_name_is_matched_only_whole():
    """
    NEON CITY has The Archivist, the dev bench has The Lunch Lady. Splitting a
    given name off those would leave "Archivist" and "Lunch" as name tokens, and
    "Lunch was a quiet affair" is not a character sighting.
    """
    forms = absent_cast_forms("the_lunch_lady", "The Lunch Lady")
    assert forms == ("The Lunch Lady",)
    assert find_intrusion("Lunch was a quiet affair.", {"x": forms}) is None
    assert find_intrusion("The Lunch Lady says nothing.", {"x": forms})


def test_a_lowercase_word_is_not_a_name_sighting():
    """
    Matching is case-sensitive on purpose: a name in prose is capitalised, and
    requiring that is what keeps a name like "Lior" from firing on a sentence
    that never mentions the character.
    """
    assert find_intrusion("the lior of it all", {"lior": ("Lior",)}) is None
    assert find_intrusion("Lior sits on the water.", {"lior": ("Lior",)}) == "Lior"


def test_a_character_the_player_has_met_is_a_callback_not_an_intrusion(clearing):
    """
    Once someone has been introduced, referring to them while they are elsewhere
    is legitimate storytelling -- "the tinker had warned you about the road" is
    exactly what the running summary is FOR. Only an introduction out of nowhere
    is the bug.
    """
    ledger = StoryLedger()
    ledger.meet("npc_ilya", day=1, location_id="tinker_caravan")
    assert "npc_ilya" not in absent_cast(clearing, ledger)
    result = StorytellerEvaluator().evaluate(
        THE_LEAK,
        _parsed(THE_LEAK),
        tool_receipts=[],
        absent_cast=absent_cast(clearing, ledger),
    )
    assert result.cast == 1.0


def absent_cast_forms(npc_id: str, name: str) -> tuple[str, ...]:
    from engine.agents.cast import _surface_forms

    return _surface_forms(npc_id, name)
