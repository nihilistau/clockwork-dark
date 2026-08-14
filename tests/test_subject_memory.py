"""
Subject memory — people, places, and anything else worth remembering.

THE DEFECT THIS CLOSES. The ledger could always hold a fact about a room:
``LedgerFact.subject_id`` has been there since it was written. Nothing ever
passed a location id as a subject, and ``memory_blocks`` took
``present_npc_ids`` alone, so a fact filed against a place was stored, ranked
against every other fact in one shared top-six, and reached the prompt only if
it happened to win. Returning somewhere never felt like returning, and the
reason was invisible: nothing was broken, the room's fact was simply not
chosen.

Retrieval is per-subject and budgeted per subject now, which is the difference
between "remembered if lucky" and "remembered".

The negative controls matter as much as the green ones: a memory test that
cannot go red would pass just as happily against the old people-only code.
"""

from __future__ import annotations

import json

import pytest

from engine.agents.prompts import memory_blocks
from engine.memory.ledger import NPCRelation, StoryLedger, SubjectMemory


@pytest.fixture
def ledger() -> StoryLedger:
    led = StoryLedger()
    led.meet("maris", day=2, location_id="edgewood_bakery")
    led.remember_name("maris", "the baker")
    led.add_fact("You told Maris your name was Corin.", subject_id="maris", turn=3, day=2)
    led.add_fact("You broke the shutter getting in.", subject_id="edgewood_bakery", turn=4, day=2)
    led.note("edgewood_bakery", "The shutter is still hanging off one hinge.")
    return led


# ---------------------------------------------------------------------------
# the ledger
# ---------------------------------------------------------------------------


def test_a_place_is_a_subject_like_anyone_else(ledger: StoryLedger) -> None:
    assert [f.text for f in ledger.recall("edgewood_bakery")] == [
        "You broke the shutter getting in."
    ]
    assert ledger.subject("edgewood_bakery").kind == "place"


def test_recall_is_per_subject_and_cannot_be_crowded_out(ledger: StoryLedger) -> None:
    """
    THE ACTUAL BUG, pinned. A talkative NPC used to be able to fill the one
    shared top-six and push a room's only fact out of the prompt entirely.
    """
    for index in range(20):
        ledger.add_fact(f"Maris said thing {index}.", subject_id="maris", turn=5, day=2)

    assert [f.text for f in ledger.recall("edgewood_bakery")] == [
        "You broke the shutter getting in."
    ], "twenty facts about a person buried the one fact about the room"


def test_notes_do_not_decay_the_way_facts_do(ledger: StoryLedger) -> None:
    """
    A note is durable state, not an impression. "The shutter is still hanging
    off one hinge" must not fade because nothing mentioned it for a week --
    that is the whole difference between a note and a fact.
    """
    ledger.decay(days=400)
    assert ledger.subject("edgewood_bakery").notes == [
        "The shutter is still hanging off one hinge."
    ]


def test_notes_are_deduplicated_and_bounded(ledger: StoryLedger) -> None:
    for _ in range(3):
        ledger.note("edgewood_bakery", "The shutter is still hanging off one hinge.")
    assert len(ledger.subject("edgewood_bakery").notes) == 1

    for index in range(20):
        ledger.note("edgewood_bakery", f"note {index}")
    assert len(ledger.subject("edgewood_bakery").notes) <= 6


def test_forget_takes_the_facts_too(ledger: StoryLedger) -> None:
    """
    A forget that left the facts behind for `salient_facts` to surface later
    would be a lie told to whoever asked for it.
    """
    dropped = ledger.forget("edgewood_bakery")
    assert dropped == 1
    assert ledger.recall("edgewood_bakery") == []
    assert "edgewood_bakery" not in ledger.relations
    assert not [f for f in ledger.facts if f.subject_id == "edgewood_bakery"]
    # ...and takes nothing else with it.
    assert [f.text for f in ledger.recall("maris")] == [
        "You told Maris your name was Corin."
    ]


def test_a_subject_survives_export_and_import(ledger: StoryLedger) -> None:
    payload = ledger.export_subject("edgewood_bakery")
    ledger.forget("edgewood_bakery")
    assert ledger.import_subject(payload) is True
    assert [f.text for f in ledger.recall("edgewood_bakery")] == [
        "You broke the shutter getting in."
    ]
    assert ledger.subject("edgewood_bakery").notes == [
        "The shutter is still hanging off one hinge."
    ]


def test_import_replaces_rather_than_merges(ledger: StoryLedger) -> None:
    """
    Importing is how a carry-over layer seeds a new run. Merging would make the
    result depend on whatever the fresh run had already invented about somebody
    it has not met yet.
    """
    payload = ledger.export_subject("maris")
    ledger.add_fact("Maris has never seen you before.", subject_id="maris", turn=9, day=9)
    ledger.import_subject(payload)
    assert [f.text for f in ledger.recall("maris")] == [
        "You told Maris your name was Corin."
    ]


def test_the_save_format_survives_the_new_fields(ledger: StoryLedger) -> None:
    restored = StoryLedger.from_dict(ledger.to_dict())
    assert restored.subject("edgewood_bakery").notes == [
        "The shutter is still hanging off one hinge."
    ]
    assert restored.subject("edgewood_bakery").kind == "place"


def test_an_old_save_loads_as_exactly_what_it_was() -> None:
    """
    `kind` and `notes` did not exist when the shipped saves were written.
    Defaults have to make such a record an NPC with no notes, or every save on
    disk changes meaning on upgrade.
    """
    restored = StoryLedger.from_dict(
        {"relations": {"maris": {"npc_id": "maris", "disposition": 12, "met": True}}}
    )
    record = restored.relations["maris"]
    assert record.kind == "npc"
    assert record.notes == []
    assert record.disposition == 12


def test_the_old_class_name_is_the_same_class() -> None:
    """Not a subclass: an alias, so the two names cannot drift apart."""
    assert NPCRelation is SubjectMemory


# ---------------------------------------------------------------------------
# what actually reaches the model
# ---------------------------------------------------------------------------


def test_the_room_reaches_the_prompt(ledger: StoryLedger) -> None:
    _, block = memory_blocks(ledger, present_npc_ids=(), location_id="edgewood_bakery")
    assert "THIS PLACE, AS YOU LEFT IT" in block
    assert "still hanging off one hinge" in block


def test_a_room_is_silent_when_nothing_is_remembered_about_it(ledger: StoryLedger) -> None:
    """The counter-control: no empty heading for a place with no history."""
    _, block = memory_blocks(ledger, present_npc_ids=(), location_id="millhaven_gate")
    assert "THIS PLACE" not in block


def test_a_character_arrives_with_a_dossier(ledger: StoryLedger) -> None:
    ledger.subject("maris").owed.append("a loaf, unpaid")
    ledger.subject("maris").tags.append("sharp about money")
    _, block = memory_blocks(ledger, present_npc_ids=("maris",), location_id="")

    assert "WHO IS HERE, AND WHAT THEY REMEMBER" in block
    assert "the baker (maris)" in block
    assert "your name was Corin" in block
    assert "a loaf, unpaid" in block
    assert "sharp about money" in block


def test_the_dossier_never_prints_a_fact_id(ledger: StoryLedger) -> None:
    """
    `known_facts` holds fact IDs, not prose. Rendering it put
    `knows: 208572d68f9613c9` in front of the model -- and the facts it indexes
    are already on the `remembers:` lines in readable form.
    """
    ledger.add_fact("Something else.", subject_id="maris", turn=6, day=3)
    _, block = memory_blocks(ledger, present_npc_ids=("maris",), location_id="")
    for fact in ledger.facts:
        assert fact.id not in block


def test_an_unmet_character_gets_no_dossier(ledger: StoryLedger) -> None:
    ledger.subject("odran", kind="npc")
    _, block = memory_blocks(ledger, present_npc_ids=("odran",), location_id="")
    assert "odran" not in block


def test_a_declared_topic_reaches_the_prompt(ledger: StoryLedger) -> None:
    ledger.add_fact("The seal was already broken.", subject_id="the_ledger_case", turn=7, day=3)
    _, block = memory_blocks(
        ledger, present_npc_ids=(), location_id="", topic_ids=("the_ledger_case",)
    )
    assert "ON THE LEDGER CASE" in block
    assert "seal was already broken" in block


# ---------------------------------------------------------------------------
# the tool path
# ---------------------------------------------------------------------------


def test_recall_subject_answers_for_an_unknown_subject(engine) -> None:
    """
    "Nothing is remembered about this person" is a real answer, not an error --
    it is exactly what the narrator needs before inventing a history.
    """
    from engine.skills.builtin.memory import recall_subject

    # A bare engine carries no ledger -- the session owns it -- so the tool
    # reports that rather than inventing an empty memory, which would read
    # to the narrator as "this person is a stranger".
    answer = json.loads(recall_subject(subject_id="nobody_at_all"))
    assert answer["ok"] is False
    assert "ledger" in answer["reason"]


def test_recall_subject_refuses_an_empty_id(engine) -> None:
    from engine.skills.builtin.memory import recall_subject

    assert json.loads(recall_subject(subject_id=""))["ok"] is False


# ---------------------------------------------------------------------------
# clues — the third kind of knowing
# ---------------------------------------------------------------------------


def test_a_clue_is_a_fact_and_needs_no_new_storage(ledger: StoryLedger) -> None:
    """
    Clues decay, archive, recall and persist exactly like everything else
    because they ARE facts, with a `kind`. A parallel container would be a
    second thing to keep in step with the save format.
    """
    ledger.learn("The shutter was forced from the inside.", subject_id="edgewood_bakery", turn=5, day=3)
    assert [c.text for c in ledger.clues()] == ["The shutter was forced from the inside."]
    # ...and it is recalled with the place, because a clue carries a subject.
    assert any("forced from the inside" in f.text for f in ledger.recall("edgewood_bakery"))


def test_clues_are_not_ordinary_facts(ledger: StoryLedger) -> None:
    """The counter-control: the board must not fill with every fact in the run."""
    assert ledger.facts, "fixture has facts to be confused with clues"
    assert ledger.clues() == []


def test_clues_survive_the_save(ledger: StoryLedger) -> None:
    ledger.learn("Odran lied about the caravan.", subject_id="npc_odran", turn=6, day=3)
    restored = StoryLedger.from_dict(ledger.to_dict())
    assert [c.text for c in restored.clues()] == ["Odran lied about the caravan."]


def test_the_board_resolves_a_subject_to_something_readable(ledger: StoryLedger) -> None:
    """
    A board of raw ids is a debug view. `edgewood_bakery` becomes "Edgewood
    Bakery" through the active story's graph, and a named person becomes their
    name.
    """
    from engine.games import registry
    from engine.scenes.default_api import clue_board

    registry.activate("clockwork-dark")
    ledger.remember_name("npc_odran", "Odran")
    ledger.learn("The shutter was forced.", subject_id="edgewood_bakery", turn=5, day=3)
    ledger.learn("Odran lied.", subject_id="npc_odran", turn=6, day=3)

    about = {row["about"] for row in clue_board(None, ledger)}
    assert about == {"Edgewood Bakery", "Odran"}


def test_no_ledger_no_board() -> None:
    from engine.scenes.default_api import clue_board

    assert clue_board(None, None) == []
