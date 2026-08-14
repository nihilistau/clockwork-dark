"""
Engine-Executed Intents, In Every Shipped Story
===============================================

``tests/test_turn_intent.py`` proved the mechanism on ONE game. This file
proves it on all of them, and on the story nobody has written yet.

WHY THIS FILE EXISTS. The intent channel closed the largest defect in the
project -- a narration turn could not change the world -- and the proof was
the flagship's own opening choice, "Follow the smoke toward Edgewood". That is
one authored line in one manifest. The MECHANISM was always story-agnostic
(``legal_intents`` builds its enums from whatever the active story declares),
but the AUTHORING was not: three of the four shipped stories opened on choices
that declared nothing, so The Wicked Garden's "Step through" -- which IS the
crossing the entire first act hangs on -- was a sentence handed to a narrator
with the engine never asked, exactly as the original bug report described. The
mechanism worked and nobody had ever checked that a player could move in three
of the four games.

The two claims here are deliberately different in kind:

1. **Per story, the opening frame is driven end to end.** Whatever intent the
   manifest authored is pulled through the REAL choice -> intent path
   (``resolve_player_action`` + ``resolve_player_intent``, the pair the socket
   handler uses) into a real ``run_turn``, and the assertion is read back off
   ``GameState``. Nothing is asserted about narration.
2. **Per story with a travel graph, travel moves the player.** Derived from
   ``registry.discover()`` rather than a hardcoded list, so a fifth story is
   swept the moment its directory exists -- which is the point. The guard has
   to hold for the story nobody has written, or it only records what today's
   four happen to do.

THE MOCK RULE, INHERITED. Canned replies are built from
``storyteller_turn_schema(...)`` and validated against it with
``tests/schema_check.py``. Every mock in this suite once emitted a
``tool_calls`` array the live grammar forbids, and that is precisely how the
original defect stayed invisible for months. A hand-written payload shape is a
second implementation of the game with different rules.

Version: v0.1.0 [2026-08-15]
"""

from __future__ import annotations

import json
import logging
from typing import Any, Iterator, Optional

import pytest

from schema_check import validate

from engine.game.intents import find_verb, legal_intents
from engine.game.state import GameState
from engine.games import registry
from engine.lmstudio.schemas import storyteller_turn_schema
from engine.persistence import reset_save_store
from engine.persistence.saves import SaveStore
from engine.scenes.default_state import (
    SessionStore,
    resolve_player_action,
    resolve_player_intent,
    run_turn,
)

#: Every installed story. DERIVED, never hardcoded -- this file's whole value
#: is that it covers a story that does not exist yet.
GAMES = tuple(sorted(registry.discover()))

#: Long enough to clear the turn schema's ``minLength`` on narration, and
#: story-neutral: it must be sampleable in a fae garden, a bedroom, a rain-lit
#: market and a birch wood alike, because the same string is checked against
#: all four grammars.
NARRATION = (
    "The way ahead resolves itself the way a held breath resolves itself, "
    "which is to say all at once and without ceremony. What was ahead of you "
    "is around you now. Something that had been keeping still while you "
    "decided has gone back to whatever it does when it is not being watched, "
    "and the light has changed by the small amount that means time has "
    "genuinely passed rather than merely been described."
)


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolated_saves(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Keep every test's saves in its own directory."""
    reset_save_store()
    store = SaveStore(root=tmp_path / "saves")
    # Both homes. `DefaultSessionStore` resolves the first at call time, and
    # `engine.session.store` holds the second as the bare `SessionStore`
    # default. No `raising=False` on either: if one of these names moves, this
    # fixture must fail rather than quietly let a test write into `data/saves`.
    monkeypatch.setattr("engine.scenes.default_state.get_save_store", lambda: store)
    monkeypatch.setattr("engine.session.store.get_save_store", lambda: store)
    yield
    reset_save_store()


@pytest.fixture
def activated(request: Any) -> Iterator[str]:
    """
    Activate one story for the duration of a test, then restore the flagship.

    Restoring matters more than it looks: ``registry.activate`` repoints every
    ``paths.*`` key process-wide, so a test that left another story active
    would hand the next test somebody else's content and the failure would
    surface somewhere unrelated.
    """
    slug = request.param
    registry.activate(slug)
    try:
        yield slug
    finally:
        registry.activate("clockwork-dark")


# ---------------------------------------------------------------------------
# a mock that cannot emit a shape the sampler could not
# ---------------------------------------------------------------------------


def canned_reply(state: GameState) -> str:
    """
    One Storyteller reply, built and then CHECKED against the live grammar.

    Deliberately declares NO intent of its own. What is on trial in this file
    is the intent the AUTHOR wrote into ``entry.opening`` or the one the test
    picked off the live catalogue -- both of which reach ``run_turn`` through
    the player's choice, not through the model's reply. A model-declared intent
    here would be a second moving part in a test about the first one.
    """
    payload = {
        "narration": NARRATION,
        "choices": [
            {"id": "a", "text": "Go on"},
            {"id": "b", "text": "Stand a while and look"},
        ],
    }
    schema = storyteller_turn_schema(intents=legal_intents(state))
    errors = validate(payload, schema["schema"])
    assert not errors, (
        "this canned reply could not be sampled from the live grammar: "
        + "; ".join(errors)
    )
    return json.dumps(payload)


def scripted(state: GameState) -> Any:
    """An llm_fn answering every Storyteller call with the same valid turn."""
    reply = canned_reply(state)

    def fake(messages: list[dict[str, Any]], **kwargs: Any) -> str:
        if not any("STORYTELLER" in str(m.get("content", "")) for m in messages):
            # Any other agent in the cast. Kept short and shapeless: their
            # grammars are not what this file is testing.
            return "Nothing is said, at length."
        return reply

    return fake


def _session_at_entry() -> Any:
    """
    A fresh run of whatever story is active, wired to the scripted model.

    EVERY agent, not just the Storyteller. Wiring only the narrator left the
    Assistant -- and, through ``run_turn`` -> ``run_pipeline``, the whole
    story roster -- resolving the real backend, so this file made blocking HTTP
    calls to LM Studio on every turn while reading as though it were mocked. It
    was 69% of the suite's wall clock and the assertions were quietly dependent
    on a live model's output.

    The Storyteller's is assigned after ``create`` rather than passed into it
    because ``scripted`` needs the state that ``create`` returns; the Assistant
    has no such constraint and could take it either way, so both are set here
    where the pairing is visible. ``tests/conftest.py::_no_live_model_calls``
    fails the test if either is ever missed again.
    """
    session = SessionStore().create(seed=42, llm_fn=None)
    fake = scripted(session.engine.state)
    session.storyteller.llm_fn = fake
    session.assistant.llm_fn = fake
    return session


def _snapshot(state: GameState) -> dict[str, Any]:
    """The three things a move is supposed to change, read off state."""
    return {
        "location_id": state.location_id,
        "clock": float(state.world_clock_hours),
        "stamina": float(state.stats.stamina),
        "gold": float(state.stats.gold),
    }


def _edge_hours(from_id: str, to_id: str) -> float:
    """Declared hours on a leg, or 0.0 for an edge that prices none."""
    from engine.game.locations import get_edge

    return float((get_edge(from_id, to_id) or {}).get("hours") or 0.0)


# ---------------------------------------------------------------------------
# 1. the guard: travel moves the player, in every story that has roads
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("activated", GAMES, indirect=True)
def test_a_travel_intent_moves_the_player_in_every_story(activated: str) -> None:
    """
    THE GUARD THAT MAKES THIS TRUE FOR THE FIFTH STORY.

    For every discovered story that declares a travel graph, picking a travel
    intent off that story's OWN live catalogue and driving it through
    ``run_turn`` must change ``location_id``. No story ids appear here; the
    destination is whatever ``legal_intents`` offers from the entry location,
    which is by construction something the engine will accept.

    A story with no graph is skipped rather than failed. "This story has no
    travel" is a legitimate authoring decision (see the deck shape), and a test
    that demanded roads would be the engine dictating story structure.
    """
    session = _session_at_entry()
    state = session.engine.state

    travel = find_verb(legal_intents(state), "travel")
    if travel is None or not travel.targets:
        pytest.skip(f"{activated} declares no travel graph at its entry location")

    target = travel.targets[0]
    before = _snapshot(state)

    payload = run_turn(
        session,
        f"The player chooses: {travel.label_for(target)}",
        intent={"action": "travel", "target": target},
    )

    after = _snapshot(state)
    assert after["location_id"] == target, (
        f"{activated}: the turn resolved a walk to {target} and the player is "
        f"still at {after['location_id']}. before={before} after={after} "
        f"receipts={payload.get('tool_receipts')}"
    )
    assert payload["intent_resolved"] is True, payload.get("tool_receipts")

    # The clock is asserted only where the story PRICED the leg. Dev Story's
    # house has `hours: 0` on every interior door on purpose -- a bedroom is
    # not a road -- so demanding time here would fail a story for being
    # correctly authored. Where hours ARE declared, they must be spent: a walk
    # that costs nothing is the same defect as a walk that does not happen.
    hours = _edge_hours(before["location_id"], target)
    if hours > 0:
        assert after["clock"] > before["clock"], (
            f"{activated}: {before['location_id']} -> {target} declares "
            f"{hours}h and the clock did not move: "
            f"{before['clock']} -> {after['clock']}"
        )


@pytest.mark.parametrize("activated", GAMES, indirect=True)
def test_every_legal_travel_target_is_somewhere_that_exists(activated: str) -> None:
    """
    The enum is built from the graph, so it cannot name a place off the map.

    Cheap, and it fails loudly on the one content mistake that produces a
    refusal a player reads as the game being broken: an edge naming an id that
    was renamed or never existed.
    """
    from engine.game.locations import LOCATIONS

    session = _session_at_entry()
    travel = find_verb(legal_intents(session.engine.state), "travel")
    if travel is None:
        pytest.skip(f"{activated} declares no travel graph at its entry location")

    unknown = [t for t in travel.targets if t not in LOCATIONS]
    assert not unknown, f"{activated}: travel offers places that do not exist: {unknown}"


# ---------------------------------------------------------------------------
# 2. the authored openings, driven through the real choice -> intent path
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("activated", GAMES, indirect=True)
def test_the_opening_frame_declares_at_least_one_mechanic(activated: str) -> None:
    """
    Every shipped story's first frame offers at least one option that DOES
    something, where the fiction has something for it to do.

    This is the authoring half of the fix, and it is the half that was missing.
    Only the flagship's opening had ever been updated: the Garden's "Step
    through" IS the crossing and declared nothing, NEON CITY's opening likewise,
    and Dev Story -- the bench authors copy -- demonstrated the mechanism not at
    all. Three of four first frames could not move a player.

    Skipped, not failed, for a story whose entry location genuinely affords no
    mechanic: if ``legal_intents`` offers nothing at the entry, an opening that
    declares nothing is right.
    """
    session = _session_at_entry()
    if not legal_intents(session.engine.state):
        pytest.skip(f"{activated} affords no mechanic at all at its entry location")

    declared = [
        row.get("intent")
        for row in (session.last_turn.get("choices") or [])
        if isinstance(row, dict) and row.get("intent")
    ]
    assert declared, (
        f"{activated}: the engine would honour "
        f"{[v.action for v in legal_intents(session.engine.state)]} at the entry "
        "location and not one opening choice declares an intent, so the first "
        "thing the player is offered cannot change the world"
    )


@pytest.mark.parametrize("activated", GAMES, indirect=True)
def test_every_authored_opening_intent_resolves(activated: str) -> None:
    """
    EVERY intent an opening declares is executed for real, through the path the
    socket handler uses -- ``resolve_player_action`` for the sentence and
    ``resolve_player_intent`` for the mechanic -- and the outcome is read back
    off ``GameState``.

    An author's opening is written by hand rather than sampled from a grammar,
    so nothing constrains it at authoring time; ``execute_intent`` re-checks it
    against the live world. That means a mistyped destination in a manifest
    produces a REFUSAL, silently, in a log nobody is reading during a
    playtest -- and the player watches the narrator walk them somewhere the
    save disagrees about. This is the test that catches it.

    Each opening choice gets its own fresh session: resolving (a) can move the
    player somewhere (b) is no longer legal from, and a shared session would
    make this test order-dependent for no reason.
    """
    probe = _session_at_entry()
    rows = [
        row
        for row in (probe.last_turn.get("choices") or [])
        if isinstance(row, dict) and row.get("intent")
    ]
    if not rows:
        pytest.skip(f"{activated}: no opening choice declares an intent")

    for row in rows:
        choice_id = str(row.get("id"))
        session = _session_at_entry()
        state = session.engine.state

        # The real pair, not a hand-built intent dict. This is the seam that
        # was missing for the life of the project: `resolve_player_action`
        # turned a choice into a SENTENCE and nothing turned it into a
        # mechanic.
        action = resolve_player_action(session, choice_id)
        intent = resolve_player_intent(session, choice_id)
        assert intent == row["intent"], (
            f"{activated}/{choice_id}: the choice -> intent path lost the "
            f"declared mechanic: {row['intent']!r} -> {intent!r}"
        )

        # Declared at authoring time, so check it against what the engine will
        # actually accept RIGHT NOW rather than trusting the manifest.
        verb = find_verb(legal_intents(state), str(intent.get("action")))
        assert verb is not None, (
            f"{activated}/{choice_id}: opening declares "
            f"{intent.get('action')!r}, a verb this story cannot honour at "
            f"{state.location_id}"
        )
        target = str(intent.get("target") or "")
        if target:
            assert target in verb.targets, (
                f"{activated}/{choice_id}: opening declares target {target!r}, "
                f"which is not reachable from {state.location_id}. Legal: "
                f"{list(verb.targets)}"
            )

        before = _snapshot(state)
        payload = run_turn(session, action, intent=intent)
        after = _snapshot(state)

        assert payload["intent_resolved"] is True, (
            f"{activated}/{choice_id}: the engine refused the opening's own "
            f"intent {intent!r}: {payload.get('tool_receipts')}"
        )

        # Verb-aware, because "did something happen" means a different thing
        # per verb and a blanket `after != before` would be wrong twice over:
        # it would fail a `check`, which legitimately moves no clock and spends
        # no coin (the roll IS the outcome), and it would pass a `travel` that
        # burned stamina without arriving anywhere.
        action = str(intent.get("action"))
        if action == "travel":
            assert after["location_id"] == target, (
                f"{activated}/{choice_id}: narration and state diverged -- the "
                f"turn resolved a walk to {target} and the player is still at "
                f"{after['location_id']}. before={before} after={after}"
            )
            if _edge_hours(before["location_id"], target) > 0:
                assert after["clock"] > before["clock"], (
                    f"{activated}/{choice_id}: a priced leg took no time. "
                    f"before={before} after={after}"
                )
        elif action == "buy":
            assert after["gold"] < before["gold"], (
                f"{activated}/{choice_id}: a purchase that cost nothing. "
                f"before={before} after={after}"
            )
        elif action == "check":
            # A failed roll is an OUTCOME, not a refusal (see
            # REFUSAL_KEY_FOR_ACTION in engine/game/intents.py -- `check` has
            # none). What must be true is that dice were actually thrown
            # against a real DC, rather than the narrator being left to decide.
            rolled = [
                r.get("result", {})
                for r in payload.get("tool_receipts") or []
                if str(r.get("skill")) == "resolve_skill_check"
            ]
            assert rolled and all("dc" in r and "dice" in r for r in rolled), (
                f"{activated}/{choice_id}: a check intent produced no roll: "
                f"{payload.get('tool_receipts')}"
            )


@pytest.mark.parametrize("activated", GAMES, indirect=True)
def test_no_story_can_walk_itself_into_a_stamina_soft_lock(activated: str) -> None:
    """
    CLAUDE.md rule 6, held one layer down from where it is usually stated.

    The rule is "never gate rest", because rest is the only thing that restores
    stamina and a gate rebuilds the soft-lock the game shipped with. A story
    that ships no ``survival.yaml`` gates nothing -- it has no rest verb AT
    ALL, which is the same soft-lock arrived at by absence instead of by a
    gate, and it is worse because there is nothing to un-gate.

    Measured before the fix: The Wicked Garden, which declares a travel graph
    and deliberately no survival rules, hit "Not enough stamina." on its
    FOURTEENTH leg and could never walk again. Dev Story leaked one point per
    interior door toward the same end.

    So: a story either has a way to restore stamina, or walking must not spend
    it. This walks the graph far past the old failure point and asserts no leg
    is ever refused for want of stamina.
    """
    from engine.game import survival

    session = _session_at_entry()
    state = session.engine.state
    engine = session.engine

    if survival.rest_kinds():
        pytest.skip(f"{activated} ships rest, so stamina is a real resource")

    for step in range(40):
        travel = find_verb(legal_intents(state), "travel")
        if travel is None or not travel.targets:
            break
        target = travel.targets[step % len(travel.targets)]
        result = engine.move_to(target)
        assert "stamina" not in str(result.message).lower(), (
            f"{activated} has no way to restore stamina and refused a walk for "
            f"want of it on leg {step}: {result.message} "
            f"(stamina={state.stats.stamina})"
        )


# ---------------------------------------------------------------------------
# 3. cleanly absent, never noisy
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("activated", GAMES, indirect=True)
def test_asking_what_is_legal_is_silent_in_every_story(
    activated: str, caplog: pytest.LogCaptureFixture
) -> None:
    """
    Building the intent catalogue must not WARN about content a story ships
    none of.

    ``legal_intents`` probes every verb the engine knows -- travel, rest, eat,
    check, buy, flag -- and each probe reads its own rules file. For The Wicked
    Garden and Dev Story, which declare a ``paths.rules`` directory (for
    archetypes, clocks, endings, threads) and deliberately ship no
    ``survival.yaml`` or ``skills.yaml``, that logged two WARNINGs per turn
    naming files nobody meant to write. The repo's rule is "undeclared means
    ships none, silently", and for the fixed-name files found INSIDE
    ``paths.rules`` (docs/AUTHORING.md §2.2) an absent file is the only way to
    say it -- there is no key to omit.

    A story that declares a rules path pointing at a directory that is NOT
    THERE is still loud. That case is a real fault and is asserted separately
    below.
    """
    session = _session_at_entry()
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        legal_intents(session.engine.state)

    loud = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert not loud, [r.getMessage() for r in loud]


def test_a_rules_path_pointing_at_nothing_is_still_loud(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """
    Quietening the probe must not hide a genuinely broken manifest.

    The two cases have to stay distinguishable: a rules DIRECTORY that exists
    with no ``survival.yaml`` in it means "this story ships no hunger", and a
    rules directory that does not exist means the manifest points at nothing.
    The first is silent; the second is the fault this asserts still shouts.
    """
    from engine.game import checks as checks_module
    from engine.game import survival as survival_module

    class _Stub:
        """A config whose ``paths.rules`` names a directory that is not there."""

        def get(self, key: str, default: Any = None) -> Any:
            if key == "paths.rules":
                return "games/no-such-story-at-all/data/rules"
            return default

    monkeypatch.setattr(survival_module, "get_config", _Stub)
    monkeypatch.setattr(checks_module, "get_config", _Stub)

    caplog.clear()
    with caplog.at_level(logging.WARNING):
        assert survival_module.load_rules() == {}
        assert checks_module.load_skill_rules() == {}

    messages = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert len(messages) == 2, messages
    assert all("directory missing" in m.lower() for m in messages), messages
