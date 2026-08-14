"""
Engine-Executed Intents
=======================

The tests that would have caught the defect these exist for: **a narration turn
could not change the world.**

A player picked "Follow the smoke toward Edgewood". The model narrated them
walking into the village. The save afterwards read::

    turn 1 | location_id 'forest_clearing' | world_clock_hours 10.0 | stamina 100

No move, no hours, no stamina. The suite did not notice for months, and the
reason it did not is the reason ``_validate`` exists at the bottom of this file:
every mock Storyteller in ``tests/`` emitted a ``tool_calls`` array, the live
grammar has forbidden that key since structured output landed
(``additionalProperties: False`` with no such property), and so the entire test
suite was exercising a channel no real model could ever reach. A mock that can
emit a shape the sampler cannot is not a stand-in for the model. It is a second
implementation of the game with different rules.

So the rule here is: build the canned reply from the REAL schema
(``storyteller_turn_schema``) and check it against the REAL schema. A test that
hand-writes a payload shape is testing its own imagination.

Version: v0.1.0 [2026-08-14]
"""

from __future__ import annotations

import json
from typing import Any, Optional

import pytest

from schema_check import validate

from content.scenes.clockwork.clockwork_state import (
    SessionStore,
    resolve_player_intent,
    run_turn,
)
from engine.game.intents import legal_intents
from engine.game.state import GameState
from engine.lmstudio.schemas import storyteller_turn_schema
from engine.persistence import reset_save_store
from engine.persistence.saves import SaveStore

NARRATION = (
    "You come out of the trees where the ferns give up and the ruts begin, and "
    "Edgewood is there in the grey the way a held breath is there. Smoke goes "
    "up off three chimneys and leans west. Somebody has been burning wet wood "
    "and not enjoying it. The road under your boots has been mended badly and "
    "recently, which is its own kind of news, and a dog you cannot see is "
    "making an opinion known about your arrival."
)


@pytest.fixture(autouse=True)
def _isolated_saves(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    """Keep every test's saves in its own directory."""
    reset_save_store()
    store = SaveStore(root=tmp_path / "saves")
    monkeypatch.setattr(
        "engine.scenes.default_state.get_save_store", lambda: store
    )
    yield
    reset_save_store()


# ---------------------------------------------------------------------------
# a mock model that cannot lie about its own shape
# ---------------------------------------------------------------------------


def canned_reply(
    state: GameState,
    *,
    narration: str = NARRATION,
    intent: Optional[dict[str, Any]] = None,
) -> str:
    """
    One Storyteller reply, built and then CHECKED against the live grammar.

    The check is the point. ``intent`` is placed on the first choice, and if the
    catalogue for this state does not allow it the schema rejects it here --
    which is exactly what the sampler would do, and exactly what no mock in this
    repository used to do.
    """
    choices: list[dict[str, Any]] = [
        {"id": "a", "text": "Go on into the village"},
        {"id": "b", "text": "Stand a while and look"},
    ]
    if intent is not None:
        choices[0]["intent"] = intent

    payload = {"narration": narration, "choices": choices}
    schema = storyteller_turn_schema(intents=legal_intents(state))
    errors = validate(payload, schema["schema"])
    assert not errors, (
        "this canned reply could not be sampled from the live grammar: "
        + "; ".join(errors)
    )
    return json.dumps(payload)


def scripted(state: GameState, **kwargs: Any) -> Any:
    """An llm_fn that answers every Storyteller call with the same turn."""
    reply = canned_reply(state, **kwargs)

    def fake(messages: list[dict[str, Any]]) -> str:
        if not any(
            "STORYTELLER" in str(m.get("content", "")) for m in messages
        ):
            return "The cat says nothing, at length."
        return reply

    return fake


def opening_intent(session: Any, choice_id: str) -> dict[str, Any]:
    """The intent the manifest's opening frame put on one of its choices."""
    return resolve_player_intent(session, choice_id)


# ---------------------------------------------------------------------------
# 1. the bug report, as a test
# ---------------------------------------------------------------------------


def test_a_travel_choice_actually_moves_the_player() -> None:
    """
    THE TEST THAT FAILS ON MAIN.

    Drive one real turn through ``run_turn`` with the flagship's own opening
    choice -- "Follow the smoke toward Edgewood" -- and assert the three things
    the bug report showed had not happened: the player moved, the clock turned
    over, and the walk cost stamina.

    Before ``engine/game/intents.py`` there was no mechanism for any of it. The
    choice became the string ``"The player chooses: Follow the smoke toward
    Edgewood"``, the string went to a narrator, and the narrator's only channel
    back into the engine was a ``tool_calls`` key the grammar forbids. Every
    assertion below fails on main, with the state completely unmoved.
    """
    session = SessionStore().create(seed=42, llm_fn=None)
    state = session.engine.state
    session.storyteller.llm_fn = scripted(state)

    intent = opening_intent(session, "a")
    assert intent == {"action": "travel", "target": "edgewood_square"}, (
        "the flagship's opening no longer declares the walk that the original "
        f"bug report was about; got {intent!r}"
    )

    before = {
        "location_id": state.location_id,
        "clock": state.world_clock_hours,
        "stamina": state.stats.stamina,
    }
    assert before["location_id"] == "forest_clearing"

    payload = run_turn(
        session, "The player chooses: Follow the smoke toward Edgewood",
        intent=intent,
    )

    after = {
        "location_id": state.location_id,
        "clock": state.world_clock_hours,
        "stamina": state.stats.stamina,
    }
    assert after["location_id"] == "edgewood_square", (
        f"narration and state diverged: the turn narrated a walk to Edgewood "
        f"and the player is still at {after['location_id']}. before={before} "
        f"after={after}"
    )
    assert after["clock"] > before["clock"], (
        f"the walk took no time at all: {before['clock']} -> {after['clock']}"
    )
    assert after["stamina"] < before["stamina"], (
        f"the walk cost no stamina: {before['stamina']} -> {after['stamina']}"
    )
    assert payload["intent_resolved"] is True, payload.get("tool_receipts")


def test_the_move_is_reported_to_the_narrator_before_it_writes() -> None:
    """
    The receipt has to reach the prompt, or the narrator is guessing again.

    ``receipts_block`` -- "MECHANICAL RESULTS -- AUTHORITATIVE" -- was written
    for exactly this and had never once been populated in production: its only
    inputs came from the forbidden ``tool_calls`` array, so on every live turn
    it was handed an empty list and returned "".
    """
    session = SessionStore().create(seed=42, llm_fn=None)
    state = session.engine.state
    seen: list[list[dict[str, Any]]] = []

    reply = canned_reply(state)

    def recording(messages: list[dict[str, Any]]) -> str:
        seen.append([dict(m) for m in messages])
        return reply

    session.storyteller.llm_fn = recording
    run_turn(
        session,
        "The player chooses: Follow the smoke toward Edgewood",
        intent={"action": "travel", "target": "edgewood_square"},
    )

    assert seen, "the Storyteller was never called"
    prompt = "\n".join(str(m.get("content", "")) for m in seen[0])
    assert "MECHANICAL RESULTS" in prompt, (
        "the engine resolved the move and did not tell the narrator about it"
    )
    assert "edgewood_square" in prompt


def test_the_resolved_move_survives_a_rejected_draft() -> None:
    """
    A retry rolls the DRAFT back, never the walk.

    ``StorytellerAgent.run_turn`` snapshots state so a narration the evaluator
    rejects cannot keep its side effects. The player's own chosen intent is
    resolved before that snapshot is taken, so a rejected draft must not
    un-walk it -- the alternative is a player who is moved or not moved
    depending on how well the model wrote.
    """
    session = SessionStore().create(seed=42, llm_fn=None)
    state = session.engine.state
    # Too short to pass the evaluator, which forces the retry path.
    session.storyteller.llm_fn = scripted(state, narration="You go. " * 30)

    run_turn(
        session,
        "The player chooses: Follow the smoke toward Edgewood",
        intent={"action": "travel", "target": "edgewood_square"},
    )
    assert state.location_id == "edgewood_square"


# ---------------------------------------------------------------------------
# 2. the enum is the guarantee
# ---------------------------------------------------------------------------


def test_the_travel_enum_holds_only_places_you_can_reach() -> None:
    """
    Illegal destinations must be UNSAMPLABLE, not caught afterwards.

    ``forest_clearing`` connects to Edgewood Square, the deeper forest and the
    herb glen. ``millhaven_gate`` is two legs away, so it must not appear --
    the same rule that already makes ``npc_id`` an enum of who is in the room.
    """
    state = GameState(session_id="t", location_id="forest_clearing")
    travel = next(v for v in legal_intents(state) if v.action == "travel")

    assert set(travel.targets) == {
        "deeper_forest",
        "edgewood_square",
        "herb_glen",
    }, travel.targets
    assert "millhaven_gate" not in travel.targets, (
        "an unreachable destination is in the grammar; the model can sample a "
        "walk the engine will refuse"
    )
    assert "forest_clearing" not in travel.targets, "walking to where you are"


def test_an_unreachable_destination_is_not_in_the_schema() -> None:
    """The same claim, one layer up, where the sampler actually reads it."""
    state = GameState(session_id="t", location_id="forest_clearing")
    schema = storyteller_turn_schema(intents=legal_intents(state))
    blob = json.dumps(schema)

    assert "edgewood_square" in blob
    assert "millhaven_gate" not in blob


def test_a_choice_may_decline_to_declare_anything() -> None:
    """Pure conversation stays pure: ``intent`` is never required."""
    state = GameState(session_id="t", location_id="forest_clearing")
    schema = storyteller_turn_schema(intents=legal_intents(state))
    item = schema["schema"]["properties"]["choices"]["items"]

    assert "intent" in item["properties"]
    assert item["required"] == ["id", "text"]
    assert validate({"id": "a", "text": "Ask what she meant"}, item) == []


def test_the_verbs_branch_so_targets_cannot_be_crossed() -> None:
    """
    ``{"action": "travel", "target": "persuasion"}`` must be ungrammatical.

    A flat ``action`` enum beside a flat ``target`` enum would make every
    verb's targets legal for every other verb, which quietly turns "unreachable
    destinations are unsamplable" back into "unreachable destinations are
    validated later, if someone remembers".
    """
    state = GameState(session_id="t", location_id="forest_clearing")
    schema = storyteller_turn_schema(intents=legal_intents(state))
    item = schema["schema"]["properties"]["choices"]["items"]

    good = {"id": "a", "text": "Walk", "intent": {"action": "travel", "target": "edgewood_square"}}
    crossed = {"id": "a", "text": "Walk", "intent": {"action": "travel", "target": "persuasion"}}

    assert validate(good, item) == []
    assert validate(crossed, item), "a travel intent accepted a skill as a place"


# ---------------------------------------------------------------------------
# 3. refusals are engine-authored and reach the prose
# ---------------------------------------------------------------------------


def test_an_intent_that_went_illegal_is_refused_and_the_narrator_is_told() -> None:
    """
    Declared on turn N, executed on turn N+1, and the world moved in between.

    Here the stamina is gone by the time the walk runs. The engine must refuse
    it, the refusal must reach the prompt as a refusal, and the player must not
    be moved -- a silent no-op is what produced the original bug report, only
    with the narration still describing the walk.
    """
    session = SessionStore().create(seed=42, llm_fn=None)
    state = session.engine.state
    seen: list[list[dict[str, Any]]] = []
    reply = canned_reply(state)

    def recording(messages: list[dict[str, Any]]) -> str:
        seen.append([dict(m) for m in messages])
        return reply

    session.storyteller.llm_fn = recording
    state.stats.stamina = 1  # not enough for any leg out of here

    payload = run_turn(
        session,
        "The player chooses: Follow the smoke toward Edgewood",
        intent={"action": "travel", "target": "edgewood_square"},
    )

    assert state.location_id == "forest_clearing", "refused and moved anyway"
    assert payload["intent_resolved"] is False

    receipt = payload["tool_receipts"][0]
    assert receipt["refused"] is True
    assert receipt["success"] is False
    assert "stamina" in receipt["result"]["error"].lower()

    prompt = "\n".join(str(m.get("content", "")) for m in seen[0])
    assert "REFUSED" in prompt, (
        "the engine said no and the narrator was never told, so the prose is "
        "free to describe a walk that did not happen"
    )


def test_an_intent_for_a_road_that_does_not_exist_is_refused() -> None:
    """A destination outside the catalogue never reaches a skill at all."""
    session = SessionStore().create(seed=42, llm_fn=None)
    state = session.engine.state
    session.storyteller.llm_fn = scripted(state)

    payload = run_turn(
        session,
        "The player walks to Millhaven.",
        intent={"action": "travel", "target": "millhaven_gate"},
    )

    assert state.location_id == "forest_clearing"
    receipt = payload["tool_receipts"][0]
    assert receipt["refused"] is True
    assert "not a legal travel target" in receipt["result"]["error"]


def test_a_turn_with_no_intent_behaves_exactly_as_before() -> None:
    """Backwards compatibility: an old save and a silent model both still play."""
    session = SessionStore().create(seed=42, llm_fn=None)
    state = session.engine.state
    session.storyteller.llm_fn = scripted(state)
    before = state.location_id

    payload = run_turn(session, "The player listens.")

    assert state.location_id == before
    assert payload["tool_receipts"] == []
    assert "intent" not in payload
    assert payload["narration"] == NARRATION


# ---------------------------------------------------------------------------
# 4. story-agnostic
# ---------------------------------------------------------------------------


def test_a_story_with_nothing_declared_gets_the_schema_it_always_had(
    story_declaring_nothing: str,
) -> None:
    """
    No graph, no dice, no economy -- so no ``intent`` property at all.

    Not "an empty intent object", which would still change the grammar and
    still cost tokens in every prompt. The property is absent, so the payload
    such a story sends is byte-for-byte the one it sent before intents existed.
    """
    state = GameState(session_id="t", location_id="nowhere")
    assert legal_intents(state) == ()

    with_intents = storyteller_turn_schema(intents=legal_intents(state))
    without = storyteller_turn_schema()
    assert with_intents == without

    item = with_intents["schema"]["properties"]["choices"]["items"]
    assert "intent" not in item["properties"]


def test_a_deck_story_gets_travel_and_no_dice() -> None:
    """
    The Wicked Garden declares a place graph and no checks whatsoever.

    So its narrator gets ``travel`` -- the Garden's walks are real and cost
    real hours -- and must NOT get ``check``, because inventing a dice verb for
    a story that ships no skill rules is the engine putting a mechanic into a
    story that deliberately has none.
    """
    from engine.games import registry

    registry.activate("wicked-garden")
    try:
        state = GameState(session_id="t", location_id="path_first_petals")
        actions = {v.action for v in legal_intents(state)}
        travel = next(v for v in legal_intents(state) if v.action == "travel")

        assert "travel" in actions
        assert "check" not in actions, (
            "a story that ships no dice was handed a dice verb: " f"{actions}"
        )
        assert "heart_grove" in travel.targets
        assert "briar_deep" not in travel.targets
    finally:
        registry.activate("clockwork-dark")


def test_a_one_way_door_stays_one_way() -> None:
    """
    The Garden's whole first act hangs on this edge, so the enum must honour it.

    ``mortal_threshold -> gate_of_briars`` is declared ``one_way``. Going home
    is an ENDING in that story, resolved by the endings spine; if the catalogue
    mirrored the edge back the model could offer the walk and every ending in
    E1 would be free.
    """
    from engine.games import registry

    registry.activate("wicked-garden")
    try:
        state = GameState(session_id="t", location_id="gate_of_briars")
        travel = next(v for v in legal_intents(state) if v.action == "travel")
        assert "mortal_threshold" not in travel.targets
    finally:
        registry.activate("clockwork-dark")


def test_an_open_encounter_suppresses_everything_else() -> None:
    """
    While a scene is running the engine already owns the option list.

    Offering ``travel`` here would let the narrator walk the player out of a
    confrontation the encounter system still believes is open.
    """
    state = GameState(session_id="t", location_id="edgewood_square")
    state.encounter = {
        "id": "road_toll_bandits",
        "intro": "Three men step out of the alders.",
    }
    verbs = legal_intents(state)
    assert [v.action for v in verbs] == ["encounter"], [v.action for v in verbs]
    assert "talk" in verbs[0].targets, verbs[0].targets


def test_a_scene_whose_definition_vanished_is_still_not_a_way_out() -> None:
    """
    A missing encounter row must not become an escape hatch.

    ``available_approaches`` returns nothing for an id it cannot look up. If
    the catalogue fell through to the ordinary verbs on that, a content bug
    would quietly hand the narrator a road out of a fight the engine still
    believes is open -- and the fight would stay open behind them.
    """
    state = GameState(session_id="t", location_id="forest_clearing")
    state.encounter = {"id": "no_such_encounter", "intro": "Something."}
    assert legal_intents(state) == ()


# ---------------------------------------------------------------------------
# 5. the guard -- no mock may emit a shape the sampler cannot
#
# The enforcement lives in the mocks themselves (see tests/schema_check.py and
# ScriptedLLM in tests/test_vertical_slice.py, which validates every one of its
# eighty replies as it produces them). What is asserted here is the lock that
# made all of it necessary.
# ---------------------------------------------------------------------------


def test_the_grammar_still_forbids_a_tool_call() -> None:
    """
    The lock that made the intent channel necessary, asserted rather than assumed.

    Not a thing to fix -- the mechanic belongs in the choice, where the enums
    can be built per turn. This exists so that anyone who reintroduces
    ``tool_calls`` to a mock finds out here instead of in six months of play.
    """
    state = GameState(session_id="t", location_id="forest_clearing")
    schema = storyteller_turn_schema(intents=legal_intents(state))["schema"]
    reply = {
        "narration": NARRATION,
        "choices": [{"id": "a", "text": "Go"}, {"id": "b", "text": "Stay"}],
        "tool_calls": [{"name": "move_to", "args": {"location_id": "edgewood_square"}}],
    }
    errors = validate(reply, schema)
    assert any("tool_calls" in e for e in errors), errors
