"""
The companion in the narration (v0.23.0 T15; spec §10.6, I10, R5).

During an in-person scene the storyteller is handed the companion block (who they are now, where you
are, their memory, this moment), and its prose is held to every texter fact check: the profile, other
people, the stage, and the promises, plans and steps only a closer makes. A first failure is retried once
through the evaluator's retry path, inside the same turn and the same turnstile hold; a second ships the
engine's receipt lines, logged and counted.

The checks were written for a texter's own reply ("I" the person, "you" the player). Over narration "you"
is the player and the companion is named or "she/he/they", so each check is tested both ways here: the
companion's own claim caught, and a mention of someone else not caught. Every draw is forced (F16); the
storyteller is a stub from the session's build (F2).
"""

from __future__ import annotations

import dataclasses
import logging
from typing import Any

import pytest

from tests.social_fixtures import receipts_active  # noqa: F401
from tests.social_world_stub import StubNarrator
from tests.test_social_scene import in_a_scene  # noqa: F401


def test_the_companion_block_carries_who_now_and_memory(in_a_scene) -> None:
    from engine.social import growth, scene

    _, session, state, pid = in_a_scene
    block = scene.companion_block(state, tokens=1200)
    assert growth.who_now(state, pid).splitlines()[0] in block
    assert "Where you are:" in block


def test_a_narrated_promise_no_closer_made_fails(in_a_scene) -> None:
    from engine.social import agreement

    _, session, state, pid = in_a_scene
    view = agreement.scene_view(state, pid)
    failures = agreement.check_scene_prose('"I\'ll text you in the morning," they say.', view, {})
    assert [f.check for f in failures] == ["promise_claimed"]


def test_a_second_failure_ships_the_receipt_lines(in_a_scene) -> None:
    from engine.scenes.default_scene import run_guarded
    from engine.social import scene

    _, session, state, pid = in_a_scene
    narrator = StubNarrator(narration='"Let\'s move in together," they say. It lands.')   # fails twice
    session.storyteller.llm_fn = narrator
    payload, error, busy = run_guarded(session, "Be playful", {"action": "scene", "target": "playful"})
    assert payload is not None and narrator.calls == 2
    assert payload["narration"] == scene.receipt_lines(state)


def test_an_honest_narration_passes_first_time(in_a_scene) -> None:
    from engine.scenes.default_scene import run_guarded

    _, session, state, pid = in_a_scene
    narrator = StubNarrator(narration="You tease them about the quiz team; they laugh.")
    session.storyteller.llm_fn = narrator
    payload, error, busy = run_guarded(session, "Be playful", {"action": "scene", "target": "playful"})
    assert payload["narration"].startswith("You tease") and narrator.calls == 1


def test_the_block_fits_its_budget(in_a_scene) -> None:
    from engine.memory.budget import estimate_messages
    from engine.social import growth, scene

    _, session, state, pid = in_a_scene
    memory_row = state.social["people"][pid].setdefault("memory", {})
    memory_row["episodes"] = [{"recap": f"Recap {i}: " + "they talked about the ferry and the market " * 8,
                               "to_at": float(i)} for i in range(50)]
    memory_row["story"] = "They met on Matchstick and kept talking. " * 60
    block = scene.companion_block(state, tokens=1200)
    assert estimate_messages([{"content": block}]) <= 1200
    for line in growth.who_now(state, pid).splitlines():
        assert line in block                                   # never trimmed
    assert "Recap 49:" in block and "Recap 46:" not in block   # the last 3 recaps


def test_the_fallback_is_counted_in_the_metric(in_a_scene, monkeypatch, caplog) -> None:
    from engine.scenes import default_scene
    from engine.scenes.default_scene import run_guarded

    _, session, state, pid = in_a_scene
    counted: list[tuple[Any, ...]] = []
    monkeypatch.setattr(default_scene, "phone_metric", lambda *row: counted.append(row))
    session.storyteller.llm_fn = StubNarrator(narration='"Let\'s move in together," they say. It lands.')
    with caplog.at_level(logging.INFO, logger="engine.social.scene"):
        payload, _, _ = run_guarded(session, "Be playful", {"action": "scene", "target": "playful"})
    assert payload is not None and len(counted) == 1
    account, event, status, ms = counted[0]                   # a `phone` row through the existing schema (M2)
    assert (event, status) == ("scene_prose", "fallback") and ms >= 0
    logged = [r.getMessage() for r in caplog.records if "operation=scene_prose" in r.getMessage()]
    assert logged and "checks=commitment_claimed" in logged[0]
    assert "move in" not in logged[0].lower()                  # check names only, never the prose


def test_the_retry_carries_the_correction_inside_the_same_turn(in_a_scene) -> None:
    """The retry is the storyteller's own second call: one turn, one turnstile hold, the correction its note."""
    from engine.scenes.default_scene import run_guarded

    _, session, state, pid = in_a_scene
    gate = session.narration_turnstile
    holders: list[Any] = []

    class Watching(StubNarrator):
        def __call__(self, messages, **kw):
            holders.append(gate.holder)
            return super().__call__(messages, **kw)

    narrator = Watching(narration='"Let\'s move in together," they say. It lands.')
    session.storyteller.llm_fn = narrator
    turn = state.turn_number
    run_guarded(session, "Be playful", {"action": "scene", "target": "playful"})
    assert narrator.calls == 2 and state.turn_number == turn + 1
    storyteller_holds = [h for h in holders if h is not None]
    assert len(set(map(str, storyteller_holds))) == 1          # the same world hold, both calls
    assert "fact check" in narrator.prompts[1] and "fact check" not in narrator.prompts[0]


def test_a_retry_that_agrees_ships_its_prose(in_a_scene) -> None:
    from engine.scenes.default_scene import run_guarded

    _, session, state, pid = in_a_scene

    class Mends(StubNarrator):
        def turn(self, prompt: str) -> str:
            self.narration = ('"Let\'s move in together," they say.' if self.calls == 1
                              else "You tease them about the ferry; they laugh.")
            return super().turn(prompt)

    narrator = Mends()
    session.storyteller.llm_fn = narrator
    payload, _, _ = run_guarded(session, "Be playful", {"action": "scene", "target": "playful"})
    assert narrator.calls == 2 and payload["narration"].startswith("You tease them about the ferry")


def test_with_no_model_a_scene_turn_shows_its_receipt_lines(in_a_scene) -> None:
    """§21's no-model scene: the engine's receipt lines, not the storyteller's generic fallback."""
    from engine.agents.prompts import storyteller_persona
    from engine.scenes.default_scene import run_guarded
    from engine.social import scene

    _, session, state, pid = in_a_scene

    class Down(StubNarrator):
        def __call__(self, messages, **kw):
            persona = storyteller_persona().strip().splitlines()[0]
            if any(persona in str(m.get("content", "")) for m in messages):
                raise ConnectionError("no model server")
            return super().__call__(messages, **kw)

    session.storyteller.llm_fn = Down()
    payload, _, _ = run_guarded(session, "Be playful", {"action": "scene", "target": "playful"})
    assert payload["llm_unavailable"] and payload["narration"] == scene.receipt_lines(state)


def test_a_closer_s_own_promise_may_be_narrated_and_is_not_adopted(in_a_scene) -> None:
    """The promise `call_it_a_night:promise:morning` made passes in the prose; nothing the prose says becomes
    a promise of theirs (the storyteller is not the companion's voice)."""
    from engine.scenes.default_scene import run_guarded

    _, session, state, pid = in_a_scene
    narrator = StubNarrator(narration='"I\'ll text you in the morning," you tell them, and they smile.')
    session.storyteller.llm_fn = narrator
    target = "call_it_a_night:promise:morning"
    payload, _, _ = run_guarded(session, "Call it a night", {"action": "close", "target": target})
    assert narrator.calls == 1 and payload["narration"].startswith('"I\'ll text you')
    rows = list((state.social.get("promises") or {}).values())
    assert [r["by"] for r in rows if r["pid"] == pid] == ["player"]


# -- each check, read over narration both ways (the companion's own claim; someone else's) ----------------


@pytest.fixture
def maya(receipts_active):
    """A view as `scene_view` builds it, for a companion named Maya (she), with Priya another contact."""
    from engine.social import agreement

    view = agreement.view_of({"stage": "numbers", "contacts": ["Priya"],
                              "person": {"name": "Maya", "sex": "female", "age": 29, "job": "nurse",
                                         "neighbourhood": "harbourside"}})
    return dataclasses.replace(view, companion=agreement.companion_words(view.person))


def _checks(view, narration: str, moment: dict[str, Any] | None = None) -> list[str]:
    from engine.social import agreement

    return [f.check for f in agreement.check_scene_prose(narration, view, moment or {})]


@pytest.mark.parametrize("narration", [
    '"Let\'s move in together," Maya says.',
    "Maya says we should move in together.",
    "She asks, will you move in with me.",
    '"Will you marry me?" you ask.',
])
def test_a_step_no_closer_made_is_caught_in_narration(maya, narration: str) -> None:
    assert _checks(maya, narration) == ["commitment_claimed"]


@pytest.mark.parametrize("narration", [
    "Her brother says we should move in together, she tells you.",
    "Priya says we should move in together.",
    "He says we should move in together.",
    "Maya's sister says let's get married.",
])
def test_a_step_someone_else_takes_is_not_caught(maya, narration: str) -> None:
    assert _checks(maya, narration) == []


def test_a_recorded_step_passes(maya) -> None:
    view = dataclasses.replace(maya, recorded=frozenset({"come_over"}))
    assert _checks(view, '"You should come over," she says.') == []
    assert _checks(maya, '"You should come over," she says.') == ["commitment_claimed"]


def test_a_plan_is_hers_or_another_s(maya) -> None:
    assert _checks(maya, "She says see you tomorrow.") == ["plan_claimed"]
    assert _checks(maya, "Her sister says see you tomorrow.") == []
    assert _checks(maya, "He says see you tomorrow.") == []
    planned = dataclasses.replace(maya, plans=({"status": "open"},))
    assert _checks(planned, "She says see you tomorrow.") == []


def test_a_promise_is_hers_or_another_s(maya) -> None:
    assert _checks(maya, '"I\'ll text you in the morning," she says.') == ["promise_claimed"]
    assert _checks(maya, "Her mum will text you in the morning.") == []
    held = dataclasses.replace(maya, promise_windows=("morning",))
    assert _checks(held, '"I\'ll text you in the morning," she says.') == []


def test_a_stage_is_hers_or_another_s(maya) -> None:
    assert _checks(maya, '"You\'re my girlfriend now," she says.') == ["stage_claimed"]
    assert _checks(maya, "He's my boyfriend now, she says of the man at the bar.") == []


@pytest.mark.parametrize("narration,caught", [
    ('"I\'m 34," Maya says.', True),
    ('"I\'m 34," she tells you.', True),
    ("Maya is 34.", True),
    ("She works as a paramedic.", True),
    ('"I\'m 34," you say.', False),
    ("Her sister is 35.", False),
    ("Priya lives in Old Town.", False),
    ('"I\'m 29," she says. She lives in Harbourside.', False),
])
def test_her_profile_is_read_from_her_words_and_the_narration_s_statements(maya, narration, caught) -> None:
    assert _checks(maya, narration) == (["profile_contradicted"] if caught else [])


@pytest.mark.parametrize("narration,caught", [
    ('"Priya told me all about it," she says.', True),
    ("She asks how Priya is doing.", True),
    ("You think of Priya, and let it go.", False),
    ('"Priya says hi," you tell her.', False),
])
def test_another_person_is_caught_only_in_her_mouth(maya, narration, caught) -> None:
    assert _checks(maya, narration) == (["another_person"] if caught else [])


def test_a_texter_reply_still_reads_as_before(receipts_active) -> None:
    """Without `companion` (every texter reply) the third-person skip stands: "she says let's move in" is
    someone else's in a text."""
    from engine.social import agreement
    from engine.social.kinds import Decision

    view = agreement.view_of({"stage": "numbers", "person": {"name": "Maya", "age": 29}})
    reply = {"bubbles": ["she says let's move in together"]}
    assert [f.check for f in agreement.check(reply, Decision(situation="reply"), view)
            if f.check == "commitment_claimed"] == []


def test_the_prose_is_checked_one_sentence_at_a_time() -> None:
    from engine.social import agreement

    assert agreement._sentences('"Hi," she says. You sit. "Again?" She laughs') == [
        '"Hi," she says.', "You sit.", '"Again?"', "She laughs"]


# -- fix round 1 (review I1, M1-M6, concern 4) ----------------------------------------------------------------

_MOVE_IN = '"Let\'s move in together," they say. It lands.'


class _DraftChoices(StubNarrator):
    """A stub whose choices' words are its own ("DRAFT ..."), so a test can tell them from the engine's."""

    def turn(self, prompt: str) -> str:
        import json

        payload = json.loads(super().turn(prompt))
        for i, row in enumerate(payload["choices"]):
            row["text"] = f"DRAFT {i}"
        return json.dumps(payload)


def test_a_closing_turn_is_narrated_with_the_block_it_is_checked_against(in_a_scene) -> None:
    """I1: a closer ends the scene before the prompt is built; the block built before the intent still
    reaches that turn's prompt, and the prose is still checked (a contradiction is retried)."""
    from engine import social
    from engine.scenes.default_scene import run_guarded

    _, session, state, pid = in_a_scene
    narrator = StubNarrator(narration='"Let\'s move in together," they say at the door.')
    session.storyteller.llm_fn = narrator
    run_guarded(session, "Call it a night", {"action": "close", "target": "call_it_a_night"})
    assert not social.scene_open(state)
    assert narrator.calls == 2
    assert "WITH YOU IN PERSON" in narrator.prompts[0] and "You are with" in narrator.prompts[0]


def test_an_open_scene_s_block_is_not_doubled(in_a_scene) -> None:
    from engine.scenes.default_scene import run_guarded

    _, session, state, pid = in_a_scene
    narrator = StubNarrator(narration="You tease them about the ferry; they laugh.")
    session.storyteller.llm_fn = narrator
    run_guarded(session, "Be playful", {"action": "scene", "target": "playful"})
    assert narrator.prompts[0].count("WITH YOU IN PERSON: ") == 1


def test_the_scene_correction_speaks_of_the_companion_in_the_third_person(in_a_scene) -> None:
    """M1: in the narrator's frame, the companion by name; the texter's lines are untouched."""
    from engine.social import agreement, scene, voicing

    _, session, state, pid = in_a_scene
    name = scene._name(state, pid)
    check = scene.prose_check(state, pid, [])
    for found, said in ((agreement.Failure("another_person", "bubbles", 0, "Priya"), f"someone {name} does not know"),
                        (agreement.Failure("commitment_claimed", "bubbles", 0, "let's move in"), f"you and {name}")):
        line = check.correction([found])
        assert said in line and "someone you do not know" not in line and "Your reply" not in line
    assert voicing.CORRECTIONS["another_person"] == ("Your reply named {detail}, someone you do not know. "
                                                     "Rewrite it without naming them.")


def test_a_scene_promise_is_judged_by_who_made_it(maya) -> None:
    """M3: the player's promise is not hers -- "she'll text you" fails on it -- and hers is not the player's."""
    players = dataclasses.replace(maya, player_windows=("morning",))
    assert _checks(players, '"I\'ll text you in the morning," you tell her.') == []
    assert _checks(players, "She'll text you in the morning, she says.") == ["promise_claimed"]
    assert _checks(players, '"I\'ll text you in the morning," she says.') == ["promise_claimed"]
    hers = dataclasses.replace(maya, promise_windows=("morning",))
    assert _checks(hers, '"I\'ll text you in the morning," she says.') == []
    assert _checks(hers, '"I\'ll text you in the morning," you tell her.') == ["promise_claimed"]


def test_a_person_with_no_pronoun_set_is_read_through_they(receipts_active) -> None:
    """M4: a sex outside the pronoun table gets the "they" forms only, and every check still runs."""
    from engine.social import agreement

    view = agreement.view_of({"stage": "numbers", "person": {"name": "Maya", "sex": "unspecified", "age": 29}})
    words = agreement.companion_words(view.person)
    assert {"they", "them", "maya"} <= words and not words & {"she", "he", "her", "him"}
    view = dataclasses.replace(view, companion=words)
    assert _checks(view, "They say let's move in together.") == ["commitment_claimed"]
    assert _checks(view, "Maya says let's move in together.") == ["commitment_claimed"]
    assert _checks(view, "She says let's move in together.") == []


def test_a_scene_turn_streams_nothing_its_check_rejects(in_a_scene) -> None:
    """M5: a scene turn's stream is held until its prose passes; a rejected draft never reaches the screen."""
    from engine.scenes.default_scene import run_guarded

    _, session, state, pid = in_a_scene
    sent: list[str] = []

    def emit(event: str, body: dict[str, Any]) -> None:
        if event == "narration_delta":
            sent.append(str(body.get("text") or ""))

    session.storyteller.llm_fn = StubNarrator(narration=_MOVE_IN)
    run_guarded(session, "Be playful", {"action": "scene", "target": "playful"}, emit_callback=emit)
    assert "move in" not in "".join(sent)
    sent.clear()
    session.storyteller.llm_fn = StubNarrator(narration="You tease them about the ferry; they laugh.")
    run_guarded(session, "Be playful", {"action": "scene", "target": "playful"}, emit_callback=emit)
    assert "You tease them" in "".join(sent)


def test_the_receipt_lines_ship_with_the_engine_s_choices(in_a_scene) -> None:
    """M6: with the receipt lines, the choices are the engine's legal moves, never the rejected draft's."""
    from engine.game.intents import legal_intents
    from engine.scenes.default_scene import run_guarded

    _, session, state, pid = in_a_scene
    session.storyteller.llm_fn = _DraftChoices(narration=_MOVE_IN)
    payload, _, _ = run_guarded(session, "Be playful", {"action": "scene", "target": "playful"})
    texts = [c["text"] for c in payload["choices"]]
    assert texts and not any("DRAFT" in t for t in texts)
    legal = {(v.action, t) for v in legal_intents(state) for t in v.targets}
    assert all((c["intent"]["action"], c["intent"].get("target", "")) in legal for c in payload["choices"])


def test_the_block_says_who_you_and_they_are(in_a_scene) -> None:
    """Concern 4: one framing line at the top says whom "you" and "they" mean inside the block."""
    from engine.social import scene

    _, session, state, pid = in_a_scene
    name = scene._name(state, pid)
    lines = scene.companion_block(state, tokens=1200).splitlines()
    assert lines[0] == f"WITH YOU IN PERSON: {name}"
    assert f'"you" means {name}' in lines[1] and '"they" means you' in lines[1]
