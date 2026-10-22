"""
The social slice, schema 2, and the contracts later tasks build on (v0.23.0 T1;
spec §4.1, §4.2, §16, §19.1, §22).
"""

from __future__ import annotations

import json

import pytest

from tests.social_fixtures import matched, receipts_active, receipts_state  # noqa: F401


def test_the_slice_v2_skeleton() -> None:
    from engine.social import kinds

    slice_ = kinds.empty_slice()
    assert slice_["schema"] == kinds.SCHEMA == 2
    for key in ("promises", "plans", "scene", "household", "phone_up", "at_work"):
        assert key in slice_, key
    assert slice_["phone_up"] is True and slice_["at_work"] is False and slice_["household"] == ""
    assert "auto_wait" not in slice_["settings"] and slice_["settings"]["wake_for_messages"] is False
    assert {"episode", "promise", "plan"} <= set(slice_["counters"])
    assert "notify" not in slice_["counters"]          # F25: v0.22's "notification" counter is reused


#: The v0.23 effect kinds that have LANDED, each with its handler (pre-flight F1, Plan decision 23).
#: Empty at T1. Each task that lands a handler adds its kind here AND to kinds.SOCIAL_EFFECT_KINDS
#: in the same commit: T2 social_growth, T3 social_episode, T4 social_promise, T11 social_go,
#: T12 social_plan, T13 social_scene (and T13 removes social_meet from both), T17 social_life,
#: T18 social_household, T20 social_migrate.
NEW_KINDS: set[str] = {"social_growth", "social_episode", "social_promise", "social_go", "social_plan", "social_scene",
                       "social_life", "social_household", "social_migrate"}
#: v0.22 kinds a v0.23 task retires (T13 retired "social_meet" when it deleted meets.py).
RETIRED_KINDS: set[str] = {"social_meet"}


def test_the_landed_kinds_are_engine_only() -> None:
    from engine.game.effects import ENGINE_ONLY_EFFECTS
    from engine.social.kinds import SOCIAL_EFFECT_KINDS

    assert NEW_KINDS <= SOCIAL_EFFECT_KINDS <= ENGINE_ONLY_EFFECTS
    assert not (RETIRED_KINDS & SOCIAL_EFFECT_KINDS)
    # test_social_seam.py::test_every_social_kind_has_a_handler (in <GUARDS>) holds at every task,
    # because no kind is named before its handler is registered.


def test_the_long_term_stages_rank_after_exclusive() -> None:
    from engine.social.kinds import stage_rank

    assert stage_rank("exclusive") < stage_rank("living_together") < stage_rank("engaged") < stage_rank("married")
    assert stage_rank("winding_down") == -1


def test_the_four_new_streams_are_distinct() -> None:
    from engine.game import rng

    names = [rng.SOCIAL_CONVO, rng.SOCIAL_GROWTH, rng.SOCIAL_LIFE, rng.SOCIAL_SCENE]
    assert len(set(names)) == 4
    assert not set(names) & {rng.SOCIAL_POPULATION, rng.SOCIAL_MATCH, rng.SOCIAL_PACE,
                             rng.SOCIAL_BEHAVIOUR, rng.SOCIAL_MEDIA, rng.SOCIAL_GAME}


def test_a_decision_carries_mode_and_end_with_defaults() -> None:
    from engine.social.kinds import Decision

    d = Decision(situation="reply")
    assert (d.mode, d.min_bubbles, d.end, d.reason, d.promise_id, d.followup_id, d.plan_id) == (
        "quick", 1, "none", "", "", "", "")


def test_an_attribute_is_the_same_whatever_was_drawn_before(receipts_state) -> None:
    """Counterless (I14): drawing a person's other streams first never changes an attribute."""
    from engine.game.rng import SOCIAL_CONVO
    from engine.social import attrs, behaviour

    @attrs.drawer("probe_t1", SOCIAL_CONVO)
    def _probe(state, pid, rng):  # registered for this test only
        return rng.random()

    try:
        first = attrs.of(receipts_state, "p0007")["probe_t1"]
        for _ in range(5):
            behaviour.person_rng(receipts_state, SOCIAL_CONVO, "p0007")
        assert attrs.of(receipts_state, "p0007")["probe_t1"] == first
    finally:
        attrs.FIXED.pop("probe_t1", None)


def test_a_match_materialises_and_a_read_writes_nothing(receipts_state, matched) -> None:
    from engine.game.rng import SOCIAL_CONVO
    from engine.social import attrs

    @attrs.drawer("probe_t1b", SOCIAL_CONVO)
    def _probe(state, pid, rng):
        return round(rng.random(), 6)

    try:
        before = json.dumps(receipts_state.to_save_dict(), sort_keys=True, default=str)
        attrs.of(receipts_state, "p0011")                       # an unmatched person: computed only
        assert json.dumps(receipts_state.to_save_dict(), sort_keys=True, default=str) == before
        pid = matched("matchstick").split(":")[1]
        assert "probe_t1b" in receipts_state.social["people"][pid]["attrs"]
    finally:
        attrs.FIXED.pop("probe_t1b", None)


def test_scene_open_is_false_for_a_story_without_paths_social() -> None:
    from types import SimpleNamespace

    from engine import social

    assert social.scene_open(SimpleNamespace(social={"scene": {"pid": "p0001"}})) is False


def test_scene_open_reads_the_slice(receipts_state) -> None:
    from engine import social

    assert social.scene_open(receipts_state) is False
    receipts_state.social["scene"] = {"pid": "p0001"}        # a read-only probe (`social_scene` writes it, T13)
    try:
        assert social.scene_open(receipts_state) is True
    finally:
        receipts_state.social["scene"] = {}


def test_read_paths_draw_and_write_nothing(receipts_state, matched) -> None:
    """§19.1 (I14): building the payload and every hint leaves the save and every counter unchanged.
    Extended by each task that adds a read path (T3 availability, T4 promises, T5 hints, T11 world)."""
    from engine.social import intents, payload, promises

    pid = matched("matchstick").split(":")[1]
    promises.make(receipts_state, pid, by="person", window="tonight")      # T4: the promises section reads it
    promises.make(receipts_state, pid, by="player", window="morning")
    from engine.game.effects import apply_effect
    from engine.social import convo, growth

    apply_effect(receipts_state, {"type": "social_person", "pid": pid,                 # T5: depth 1, so the hints
                                  "set": {"warmth": 40, "trust": 30, "episodes_done": 1}})          # read their days and the gate
    apply_effect(receipts_state, {"type": "social_growth", "op": "gain", "pid": pid, "amount": 100})
    assert growth.depth(receipts_state, pid) == 1
    before = json.dumps(receipts_state.to_save_dict(), sort_keys=True, default=str)
    for _ in range(3):
        assert payload.phone_block(receipts_state)["hints"][pid]["available_words"]   # T5: the hints section
        receipts_state.to_client_dict()
        intents.legal_phone_intents(receipts_state)                         # T4: `wait`'s promise targets
        for commitment in growth.COMMITMENTS:                               # T5: willingness, read-only
            growth.willing(receipts_state, pid, commitment)
        growth.closer_soon(receipts_state, pid)
        convo.cap_key(receipts_state, pid)
        assert payload.phone_block(receipts_state)["places"]["venues"]        # T11: the Places section
        from engine.game.intents import legal_intents
        from engine.social import world

        legal_intents(receipts_state)                                       # T11: the world verbs
        world.narration_block(receipts_state)                               # T11: the narrator's world
        world.buzz(receipts_state)
        world.places_targets(receipts_state)
        assert payload.phone_block(receipts_state)["scene"] == {}            # T13: the scene section
        from engine.social import scene

        scene.scene_verbs(receipts_state)                                   # T13: the scene's verbs (none open)
    assert json.dumps(receipts_state.to_save_dict(), sort_keys=True, default=str) == before


def test_a_decision_refuses_a_mode_or_end_it_does_not_know() -> None:
    from engine.social.kinds import DECISION_ENDS, MODES, Decision

    for mode in MODES:
        assert Decision(situation="reply", mode=mode).mode == mode
    for end in DECISION_ENDS:
        assert Decision(situation="reply", end=end).end == end
    with pytest.raises(ValueError, match="mode"):
        Decision(situation="reply", mode="sprint")
    with pytest.raises(ValueError, match="end"):
        Decision(situation="reply", end="sign-off")
