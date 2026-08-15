"""
The screen, the save and the world agree at the end of a turn.

They did not. ``run_turn`` snapshotted ``state.to_client_dict()`` into the
payload, and THEN ran quest evaluation -- which applies real effects: reward
gold, items, boons, and the ``ending_lock``/``ending_module`` pair a finale
quest carries. The autosave below it then persisted the post-quest state.

So finishing a quest stage that paid 40 gold showed the player the purse from
before the reward while writing the one after it to disk, and a run that ENDED
on this turn reported the ending on the next one. Nothing failed; the numbers
just disagreed with each other for exactly one turn, which is the hardest kind
of wrong to notice.

These tests pin the ordering rather than the symptom: whatever quest evaluation
does to the world, the payload has to have seen it.
"""

from __future__ import annotations

import json

import pytest

from engine.persistence import reset_save_store
from engine.persistence.saves import SaveStore
from engine.scenes.default_state import SessionStore, run_turn

NARRATION = (
    "The oven ticks as it cools, and the room keeps the smell of the morning's "
    "bread. Nothing here is in a hurry, and neither is she."
)


def _llm(_messages):
    return json.dumps(
        {
            "narration": NARRATION,
            "choices": [
                {"id": "a", "text": "Wait"},
                {"id": "b", "text": "Ask again"},
            ],
        }
    )


@pytest.fixture(autouse=True)
def _isolated_saves(tmp_path, monkeypatch):
    reset_save_store()
    store = SaveStore(root=tmp_path / "saves")
    monkeypatch.setattr("engine.scenes.default_state.get_save_store", lambda: store)
    yield
    reset_save_store()


def test_the_payload_shows_what_quest_evaluation_did():
    """
    A reward applied by quest evaluation is in the payload the browser renders.

    Driven through a stubbed ``_evaluate_quests`` rather than a real quest
    chain on purpose: the property under test is the ORDER of two steps in
    ``run_turn``, and tying it to one story's quest content would make it a
    test of that content instead.
    """
    session = SessionStore().create(seed=42, llm_fn=_llm)
    state = session.engine.state
    before = state.stats.gold

    def _paying_quest(sess):
        from engine.game import effects

        effects.apply_effect(sess.engine.state, {"type": "gold", "delta": 40})
        return [{"kind": "completed", "quest_id": "q", "text": "Paid."}]

    import engine.scenes.default_state as ds

    original = ds._evaluate_quests
    ds._evaluate_quests = _paying_quest
    try:
        turn = run_turn(session, "The player chooses: Wait")
    finally:
        ds._evaluate_quests = original

    assert state.stats.gold == before + 40, "the effect did not apply at all"
    assert turn["state"]["stats"]["gold"] == before + 40, (
        "the payload carried the purse from before the reward -- quest "
        "evaluation ran after the client dict was built"
    )
    assert turn["quest_events"], "the event itself went missing"


def test_the_payload_state_matches_the_world_it_describes():
    """
    The general invariant, independent of quests: nothing mutates the world
    between the snapshot and the end of the turn.
    """
    session = SessionStore().create(seed=42, llm_fn=_llm)
    turn = run_turn(session, "The player chooses: Wait")
    assert turn["state"] == session.engine.state.to_client_dict()


def test_an_ending_locked_by_a_quest_is_reported_on_its_own_turn():
    """
    A run that ends on this turn says so on this turn.

    ``turn_payload["ending"]`` was computed BEFORE quest evaluation, so the
    three flagship quests that end the story reported the finale one full turn
    late -- the player took another action in a story that had already
    finished.

    The effect pair is the one the real finale quests declare, verbatim from
    ``games/clockwork-dark/data/quests/convergence/the_last_quiet_thing.yaml``:
    an id-less lock (whatever the run earned) plus the module that plays it.
    Both are needed -- ``epilogue.for_state`` deliberately withholds the cards
    on the locking turn until the module has run, because the lock is the
    decision and the module is the scene.
    """
    session = SessionStore().create(seed=42, llm_fn=_llm)

    def _ending_quest(sess):
        from engine.game import effects

        effects.apply_effect(sess.engine.state, {"type": "ending_lock"})
        effects.apply_effect(sess.engine.state, {"type": "ending_module"})
        return [{"kind": "completed", "quest_id": "q", "text": "Done."}]

    import engine.scenes.default_state as ds

    original = ds._evaluate_quests
    ds._evaluate_quests = _ending_quest
    try:
        turn = run_turn(session, "The player chooses: Wait")
    finally:
        ds._evaluate_quests = original

    assert "ending" in turn, (
        "the ending was locked during this turn and the payload did not carry "
        "it -- it would have surfaced on the next turn instead"
    )
