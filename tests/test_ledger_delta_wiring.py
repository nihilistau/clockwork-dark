"""
The model's proposed memory must actually reach the ledger.

`ledger_delta` is in the turn schema, the model fills it in on most turns, and
`parse_storyteller_response` defaults it -- and until now it was dropped on the
floor. `apply_ledger_delta` had exactly one caller, `turn_loop.commit_ledger`,
in a module nothing imported -- retired since to `engine/agents/turn_loop.py.bak`,
which is why this file is the only thing standing between that function and
being dropped on the floor again. So the Storyteller could narrate "Maris will
not meet your eye now" and the record of it never existed; the next turn's
prompt was assembled from a ledger that had never heard of it.

The validating layer is the point of the wiring, not an obstacle to it: the
model PROPOSES and the engine decides what is admitted. These tests assert both
halves -- that a good delta lands, and that a greedy one is bounded.

Version: v0.1.0 [2026-08-08]
"""

from __future__ import annotations

import json

import pytest

from content.scenes.clockwork.clockwork_state import SessionStore, run_turn
from engine.persistence import reset_save_store
from engine.persistence.saves import SaveStore

NARRATION = (
    "Maris does not stop working while she answers. Her hands go on shaping the "
    "dough, one turn and a press, and the smell of it fills the low room. The "
    "oven ticks as it heats, and she does not look up once."
)


def _llm(delta):
    def fake(_messages):
        return json.dumps(
            {
                "narration": NARRATION,
                "choices": [
                    {"id": "a", "text": "Wait"},
                    {"id": "b", "text": "Ask again"},
                ],
                "tool_calls": [],
                "ledger_delta": delta,
            }
        )

    return fake


@pytest.fixture(autouse=True)
def _isolated_saves(tmp_path, monkeypatch):
    reset_save_store()
    store = SaveStore(root=tmp_path / "saves")
    monkeypatch.setattr(
        "engine.scenes.default_state.get_save_store", lambda: store
    )
    yield
    reset_save_store()


def _run(delta):
    session = SessionStore().create(seed=42, llm_fn=_llm(delta))
    run_turn(session, "The player chooses: Ask about the smoke")
    return session


def test_a_proposed_fact_reaches_the_ledger():
    session = _run({"facts": [{"text": "The bakery oven has been cold for a week."}]})

    texts = [f.text for f in session.ledger.facts]
    assert any("oven has been cold" in t for t in texts), (
        f"the model's fact never reached the ledger; have {texts}"
    )


def test_a_proposed_name_is_pinned():
    session = _run({"names": {"npc_maris": "Maris Hearth"}})

    assert session.ledger.names.get("npc_maris") == "Maris Hearth"


def test_a_proposed_promise_is_recorded():
    session = _run(
        {
            "promises": [
                {"text": "Bring back flour by Thirdday", "from_id": "player",
                 "to_id": "npc_maris", "due_day": 3}
            ]
        }
    )

    assert session.ledger.promises, "no promise was recorded"
    assert "flour" in session.ledger.promises[0].text


def test_disposition_moves_but_is_clamped():
    """
    The bound is the feature.

    A model that decides an NPC now adores the player must not be able to say so
    by fifty points in one turn.
    """
    session = _run({"npc_disposition": {"npc_maris": 90}})

    relation = session.ledger.relations.get("npc_maris")
    assert relation is not None, "the disposition proposal did not create a relation"
    assert relation.disposition <= 10, (
        f"disposition jumped to {relation.disposition} in a single turn"
    )


def test_a_fact_about_an_unknown_subject_is_dropped():
    """Subjects must resolve to an NPC the engine knows; the model may not invent one."""
    session = _run(
        {"facts": [{"text": "A stranger watches.", "subject_id": "npc_not_real"}]}
    )

    subjects = {f.subject_id for f in session.ledger.facts}
    assert "npc_not_real" not in subjects


def test_a_flood_of_facts_is_capped():
    session = _run(
        {"facts": [{"text": f"Observation number {i}."} for i in range(25)]}
    )

    from engine.memory.ledger import MAX_FACTS_PER_TURN

    fresh = [f for f in session.ledger.facts if "Observation number" in f.text]
    assert len(fresh) <= MAX_FACTS_PER_TURN


def test_an_absent_delta_is_harmless():
    """Most turns propose nothing; that must not be an error path."""
    session = _run({})

    assert session.ledger is not None
