"""
A save resumed while an encounter is open offers that encounter's approaches.

THE BUG. ``engine/scenes/default_state.py::resume_opening`` rebuilt the
resumed frame's choices as "take stock", the first two roads out and "wait",
whatever the state. While a scene is open the engine accepts only its
approaches (``intents.legal_intents``'s encounter branch), so the roads were
refused and nothing on screen was an approach: every approach button of the
encounter panel (``ui/src/core/panels/approaches.js::matchApproaches``) read
"not offered this turn" until one ordinary turn had passed.

The fix builds the resumed choices from ``legal_intents`` -- the very source
the turn builder hands the narrator -- whenever a scene owns the turn. These
tests open every shipped encounter, in every story that has any, and read the
resumed frame.
"""

from __future__ import annotations

import re
from typing import Any

import pytest

from engine.games import registry


def _stories_with_encounters() -> list[str]:
    from engine.game import encounter

    found: list[str] = []
    try:
        for slug in sorted(registry.discover()):
            registry.activate(slug)
            if encounter.all_encounters():
                found.append(slug)
    finally:
        registry.deactivate()
    return found


STORIES = _stories_with_encounters()


def test_the_story_list_is_not_empty() -> None:
    """Without this every parametrized case below could vanish unnoticed."""
    assert {"clockwork-dark", "hue-and-cry", "neon-city", "the-long-con"} <= set(STORIES)


def _intent_targets(choices: list[dict[str, Any]], action: str) -> set[str]:
    return {
        str((c.get("intent") or {}).get("target"))
        for c in choices
        if (c.get("intent") or {}).get("action") == action
    }


@pytest.mark.parametrize("slug", STORIES)
def test_resume_during_an_open_encounter_offers_its_approaches(slug: str) -> None:
    from engine.game import encounter, intents
    from engine.game.procgen import new_game_state
    from engine.memory.ledger import StoryLedger
    from engine.scenes.default_state import resume_opening

    registry.activate(slug)
    rows = encounter.all_encounters()
    assert rows, slug
    for row in rows:
        state = new_game_state(seed=1021)
        # Only the encounter may own the turn here, or the comparison below
        # would be against another gate's verbs.
        state.encounter = {}
        assert not intents.scene_owns_turn(state), (slug, "something else owns turn one")
        encounter.begin(state, str(row["id"]))
        assert encounter.active(state), (slug, row["id"])
        approaches = {a["id"] for a in encounter.available_approaches(state)}
        assert approaches, (slug, row["id"])

        payload = resume_opening(state, StoryLedger())
        choices = payload["choices"]

        assert _intent_targets(choices, "encounter") == approaches, (slug, row["id"], choices)
        # The same source the turn builder uses: every intent the resumed
        # frame offers is one legal_intents would accept right now.
        legal = {verb.action: set(verb.targets) for verb in intents.legal_intents(state)}
        for choice in choices:
            intent = choice.get("intent")
            if not intent:
                continue
            assert intent["action"] in legal, (slug, row["id"], intent)
            assert str(intent.get("target")) in legal[intent["action"]], (slug, row["id"], intent)
        # Roads are refused while the scene is open, so none is offered.
        assert not _intent_targets(choices, "travel"), (slug, row["id"], choices)
        # Ids are unique: they are what the client sends back.
        ids = [c["id"] for c in choices]
        assert len(ids) == len(set(ids)), ids
        _assert_no_raw_id(choices)
        encounter.end(state)


def test_hue_and_cry_watch_stop_resumes_with_its_approaches() -> None:
    """The case found in play: the Lantern watch's stop, reloaded."""
    from engine.game import encounter
    from engine.game.procgen import new_game_state
    from engine.memory.ledger import StoryLedger
    from engine.scenes.default_state import resume_opening

    registry.activate("hue-and-cry")
    state = new_game_state(seed=1021)
    encounter.begin(state, "watch_stop")
    expected = {a["id"] for a in encounter.available_approaches(state)}
    assert expected

    choices = resume_opening(state, StoryLedger())["choices"]
    assert _intent_targets(choices, "encounter") == expected
    # Each reads as the approach's own authored words, which the panel shows.
    texts = {a["id"]: a["text"] for a in encounter.available_approaches(state)}
    for choice in choices:
        intent = choice.get("intent") or {}
        if intent.get("action") == "encounter":
            assert choice["text"] == texts[intent["target"]], choice


# -- every gate (fix round 1) --------------------------------------------------


def _expected_from_legal_intents(state: Any) -> set[tuple[str, Any]]:
    """
    ``(action, target)`` for every choice the resume can offer, built from
    ``legal_intents`` alone: each target of each verb, and a verb that takes
    no target as ``(action, None)``. Left out, as ``_scene_resume_choices``
    documents: a verb with ``extra`` fields, and a puzzle step (``challenge``
    with no options), whose target is typed.
    """
    from engine.game import intents

    out: set[tuple[str, Any]] = set()
    for verb in intents.legal_intents(state):
        if verb.extra:
            continue
        if not verb.options:
            if verb.action != "challenge":
                out.add((verb.action, None))
            continue
        out.update((verb.action, target) for target in verb.targets)
    return out


def _resumed_intents(state: Any) -> set[tuple[str, Any]]:
    from engine.memory.ledger import StoryLedger
    from engine.scenes.default_state import resume_opening

    choices = resume_opening(state, StoryLedger())["choices"]
    ids = [c["id"] for c in choices]
    assert len(ids) == len(set(ids)), ids
    assert ids[0] == "resume_look" and ids[-1] == "resume_wait", ids
    pairs = [
        (c["intent"]["action"], c["intent"].get("target"))
        for c in choices
        if c.get("intent")
    ]
    assert len(pairs) == len(set(pairs)), pairs
    _assert_no_raw_id(choices)
    return set(pairs)


_RAW_ID = re.compile(r"^[a-z_]+$")


def _assert_no_raw_id(choices: list[dict[str, Any]]) -> None:
    """
    Encfix round 2: no raw engine id reaches a player-facing choice. A
    choice's text is never a bare lowercase identifier, and never its own
    intent's action or target id.
    """
    for choice in choices:
        text = str(choice.get("text") or "").strip()
        assert text, choice
        assert not _RAW_ID.match(text), choice
        intent = choice.get("intent") or {}
        assert text != str(intent.get("action") or ""), choice
        assert text != str(intent.get("target") or ""), choice


def test_resume_during_a_job_offers_the_jobs_verbs_abort_included() -> None:
    """A HUE & CRY burglary under way: its approach, any flashback, and ``abort``."""
    from engine.game import intents
    from engine.game.clock import set_clock
    from engine.game.procgen import new_game_state
    from engine.world import jobs, premises

    registry.activate("hue-and-cry")
    state = new_game_state(seed=3)
    set_clock(state, day=1, hour=23)
    state.location_id = "wickmarket"
    prem = next(p for p in premises.at(state, "wickmarket") if p["tier"] == 1)
    assert jobs.begin(state, prem["id"])["ok"]
    assert intents._job_open(state)

    expected = _expected_from_legal_intents(state)
    assert ("abort", None) in expected and any(a == "job" for a, _ in expected), expected
    assert _resumed_intents(state) == expected


def test_resume_during_a_dealt_card_offers_its_beats() -> None:
    """A Wicked Garden card on the table: its beats, as ``card`` intents."""
    from engine.content import director
    from engine.game import intents
    from engine.game.procgen import new_game_state

    registry.activate("wicked-garden")
    state = new_game_state(seed=1021)
    director.end(state)
    receipt = director.begin(state, "day_00_prologue")
    assert receipt.get("ok"), receipt
    assert intents._card_open(state)

    expected = _expected_from_legal_intents(state)
    assert expected and {a for a, _ in expected} == {"card"}, expected
    assert _resumed_intents(state) == expected


@pytest.mark.parametrize("slug", ["clockwork-dark", "hue-and-cry"])
def test_resume_during_a_running_set_piece_offers_its_step(slug: str) -> None:
    """Every shipped set-piece, started: its step's options; a puzzle offers none."""
    from engine.challenges import runner, set_pieces
    from engine.game import intents
    from engine.game.procgen import new_game_state

    registry.activate(slug)
    set_pieces.reset_set_piece_cache()
    try:
        pieces = set_pieces.load_set_pieces()
        assert pieces, slug
        kinds: set[str] = set()
        for piece_id, piece in sorted(pieces.items()):
            state = new_game_state(seed=1021)
            started = runner.start(state, piece.get("challenge") or {}, authored=True)
            assert started.status != runner.STATUS_ERROR, (piece_id, started)
            assert intents._challenge_open(state), piece_id
            kinds.add(str(state.challenge.get("kind")))
            expected = _expected_from_legal_intents(state)
            assert _resumed_intents(state) == expected, piece_id
            if state.challenge.get("kind") != "puzzle":
                assert expected and {a for a, _ in expected} == {"challenge"}, (piece_id, expected)
        assert "skill_gauntlet" in kinds, kinds
    finally:
        set_pieces.reset_set_piece_cache()


def test_resume_during_an_open_encounter_matches_legal_intents_exactly() -> None:
    """The encounter gate, held to the same exact comparison as the others."""
    from engine.game import encounter
    from engine.game.procgen import new_game_state

    registry.activate("hue-and-cry")
    state = new_game_state(seed=1021)
    encounter.begin(state, "watch_stop")
    expected = _expected_from_legal_intents(state)
    assert expected and {a for a, _ in expected} == {"encounter"}, expected
    assert _resumed_intents(state) == expected


def test_resume_in_a_cell_offers_the_ways_out_and_no_road() -> None:
    """
    Custody is not a scene, so the old resume took the road branch: two roads
    the cell refuses (``_travel`` offers none while held) and no ``pay_fine``
    or ``serve``. It now offers exactly what ``legal_intents`` does.
    """
    from engine.game.effects import apply_effect
    from engine.game.procgen import new_game_state
    from engine.world import law

    registry.activate("hue-and-cry")
    state = new_game_state(seed=1021)
    state.location_id = "wickmarket"
    receipt = apply_effect(state, {"type": "arrest"})
    assert law.in_custody(state), receipt

    expected = _expected_from_legal_intents(state)
    assert ("serve", None) in expected, expected
    assert not any(a == "travel" for a, _ in expected), expected
    resumed = _resumed_intents(state)
    assert resumed == expected
    # With the fine in hand both ways out are offered.
    state.stats.gold = 10_000
    expected = _expected_from_legal_intents(state)
    assert {("pay_fine", None), ("serve", None)} <= expected, expected
    assert _resumed_intents(state) == expected


def test_no_target_verbs_are_worded_from_the_engine_table_on_every_turn() -> None:
    """
    Encfix round 2: ``describe_intent`` worded a verb with no target by its
    id, so a narrated turn's chip -- and the resumed frame -- read "abort",
    "serve", "pay_fine". Every such verb the gates build is worded from
    ``intents.ENGINE_CHOICE_WORDS``, a turn's chip included.
    """
    from engine.game import intents
    from engine.game.clock import set_clock
    from engine.game.effects import apply_effect
    from engine.game.procgen import new_game_state
    from engine.scenes.default_state import _label_intents
    from engine.world import jobs, premises

    registry.activate("hue-and-cry")
    held = new_game_state(seed=1021)
    held.location_id = "wickmarket"
    apply_effect(held, {"type": "arrest"})
    held.stats.gold = 10_000
    burgling = new_game_state(seed=3)
    set_clock(burgling, day=1, hour=23)
    burgling.location_id = "wickmarket"
    prem = next(p for p in premises.at(burgling, "wickmarket") if p["tier"] == 1)
    assert jobs.begin(burgling, prem["id"])["ok"]

    seen: set[str] = set()
    for state in (held, burgling):
        for verb in intents.legal_intents(state):
            if verb.options or verb.action == "challenge":
                continue
            seen.add(verb.action)
            words = intents.describe_intent(state, {"action": verb.action})
            assert words == intents.ENGINE_CHOICE_WORDS[verb.action], verb.action
            assert not _RAW_ID.match(words), words
            # A narrator that wrote the id as the choice's text gets the words.
            labelled = _label_intents(state, [{"id": "a", "text": verb.action, "intent": {"action": verb.action}}])
            assert labelled[0]["text"] == words, labelled
    assert seen == {"abort", "pay_fine", "serve"}, seen


def test_a_set_piece_is_labelled_by_its_authored_title() -> None:
    """
    Encfix round 2: ``_set_piece`` read a piece-level ``title`` the files do
    not carry (it is on the piece's ``challenge:``), so the cell's way out read
    "lantern_house_break" on a chip and on the resumed frame.
    """
    from engine.game import intents
    from engine.game.effects import apply_effect
    from engine.game.procgen import new_game_state

    registry.activate("hue-and-cry")
    state = new_game_state(seed=1021)
    state.location_id = "wickmarket"
    apply_effect(state, {"type": "arrest"})
    verb = intents.find_verb(intents.legal_intents(state), "set_piece")
    assert verb is not None and verb.options, verb
    assert dict(verb.options)["lantern_house_break"] == "The Ring on the Nail"


def test_resume_with_no_scene_open_is_unchanged() -> None:
    """The ordinary resume keeps its roads (the local-mode golden pins it)."""
    from engine.game.procgen import new_game_state
    from engine.memory.ledger import StoryLedger
    from engine.scenes.default_state import resume_opening

    registry.activate("hue-and-cry")
    state = new_game_state(seed=1021)
    choices = resume_opening(state, StoryLedger())["choices"]
    assert choices[0]["id"] == "resume_look"
    assert choices[-1]["id"] == "resume_wait"
    assert _intent_targets(choices, "travel")
    assert not _intent_targets(choices, "encounter")
