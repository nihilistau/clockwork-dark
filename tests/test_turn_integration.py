"""
End-to-end turn tests: streaming, rollback, memory, and the socket contract.

These cover the seams between layers, which is where the audit found most of
the damage -- each piece worked and none of them were connected.
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


def _llm(tool_calls=None, narration=NARRATION):
    def fake(_messages):
        return json.dumps(
            {
                "narration": narration,
                "choices": [
                    {"id": "a", "text": "Wait"},
                    {"id": "b", "text": "Ask again"},
                ],
                "tool_calls": tool_calls or [],
            }
        )

    return fake


@pytest.fixture(autouse=True)
def _isolated_saves(tmp_path, monkeypatch):
    """Keep every test's saves in its own directory."""
    reset_save_store()
    store = SaveStore(root=tmp_path / "saves")
    # run_turn lives in engine/scenes/default_state.py now; the content module
    # is a re-export shim, so the patch must land on the engine module.
    monkeypatch.setattr("engine.scenes.default_state.get_save_store", lambda: store)
    yield
    reset_save_store()


def _events(session, action="The player chooses: Ask about the smoke"):
    captured: list[tuple[str, dict]] = []
    run_turn(session, action, emit_callback=lambda n, p: captured.append((n, p)))
    return captured


# -- streaming -----------------------------------------------------------


def test_narration_streams_to_the_client():
    """
    The client listened for narration_delta and no server code ever emitted it.
    """
    session = SessionStore().create(seed=42, llm_fn=_llm())
    events = _events(session)
    deltas = [p["text"] for n, p in events if n == "narration_delta"]
    assert deltas, "no narration_delta emitted"
    assert "".join(deltas) == NARRATION


def test_streamed_narration_is_not_sent_twice():
    session = SessionStore().create(seed=42, llm_fn=_llm())
    events = _events(session)
    turn = next(p for n, p in events if n == "turn_update")
    # The flag tells the client to finalize the live entry rather than append
    # the whole paragraph again underneath it.
    assert turn["streamed"] is True


def test_no_streaming_without_an_emit_callback():
    session = SessionStore().create(seed=42, llm_fn=_llm())
    payload = run_turn(session, "The player waits.")
    assert payload["narration"] == NARRATION


# -- tool execution ------------------------------------------------------
#
# NOT THE PRODUCTION CHANNEL, and the tests below say so in their names now.
# The live turn grammar forbids a `tool_calls` key outright
# (engine/lmstudio/schemas.py: additionalProperties False, no such property),
# so no model has ever sent one. What these cover is the DISPATCHER -- its
# allowlist, its tolerance of malformed arguments -- which is real code reached
# from `execute_intent` and from an injected llm_fn. The channel a player's
# choice actually travels is the structured intent; see tests/test_turn_intent.py
# and the note at the top of engine/game/intents.py.


def test_the_dispatcher_executes_a_move_it_is_handed():
    session = SessionStore().create(seed=42, llm_fn=_llm(
        tool_calls=[{"name": "move_to", "args": {"location_id": "edgewood_square"}}]
    ))
    run_turn(session, "The player travels.")
    assert session.engine.state.location_id == "edgewood_square"


def test_system_only_skill_is_refused_from_the_model():
    """The unbounded world tick must not be reachable by narration."""
    session = SessionStore().create(seed=42, llm_fn=_llm(
        tool_calls=[{"name": "advance_world_tick", "args": {"days": 5000}}]
    ))
    before = session.engine.state.world_day
    payload = run_turn(session, "The player waits.")
    receipt = payload["tool_receipts"][0]
    assert receipt["success"] is False
    assert "not callable" in receipt["result"]["error"]
    assert session.engine.state.world_day == before


def test_malformed_tool_args_do_not_break_the_turn():
    session = SessionStore().create(seed=42, llm_fn=_llm(
        tool_calls=[{"name": "move_to", "args": ["edgewood_square"]}]
    ))
    payload = run_turn(session, "The player travels.")
    assert payload["narration"] == NARRATION
    assert payload["tool_receipts"][0]["success"] is False


# -- socket contract -----------------------------------------------------


def test_turn_payload_is_json_serializable():
    """
    Everything here is jsonify'd and emitted. Raw bytes anywhere in the tree --
    as the TTS client used to return -- takes the whole turn down.
    """
    session = SessionStore().create(seed=42, llm_fn=_llm())
    json.dumps(run_turn(session, "The player waits."))


def test_client_state_never_leaks_hidden_stats():
    session = SessionStore().create(seed=42, llm_fn=_llm())
    payload = run_turn(session, "The player waits.")
    assert "awareness" not in payload["state"]
    assert "evil_progress" not in payload["state"]
    assert "storyteller_mind" not in payload["state"]


# -- memory --------------------------------------------------------------


def test_memory_accumulates_across_turns():
    session = SessionStore().create(seed=42, llm_fn=_llm())
    for index in range(4):
        run_turn(session, f"The player chooses: action {index}")
    assert len(session.ledger.turn_buffer) == 4
    assert session.ledger.turn_buffer[-1].player_action.endswith("action 3")


def test_prior_turns_reach_the_next_prompt():
    """The whole point: the Storyteller must see what it already said."""
    seen: list[list[dict]] = []

    def capturing(messages):
        seen.append(messages)
        return _llm()(messages)

    session = SessionStore().create(seed=42, llm_fn=capturing)
    run_turn(session, "The player chooses: Ask Maris her name")
    run_turn(session, "The player chooses: Ask about the flue")

    # The Storyteller and the Assistant share the injected llm_fn, and the
    # Assistant only speaks on a probability roll -- so "the last prompt" is
    # not reliably the Storyteller's. Select by persona instead.
    storyteller_prompts = [
        m for m in seen if any("You are the STORYTELLER" in x["content"] for x in m)
    ]
    assert len(storyteller_prompts) >= 2

    second_prompt = [m["content"] for m in storyteller_prompts[-1]]
    assert any("Ask Maris her name" in c for c in second_prompt)
    assert any(NARRATION in c for c in second_prompt)


def test_assistant_agency_is_reproducible_from_seed():
    """
    Whether the companion speaks must replay identically.

    The agency roll used an unseeded random.Random(), so the same seed produced
    a different companion every run -- and made this suite intermittently flaky.
    """
    def spoke(seed):
        session = SessionStore().create(seed=seed, llm_fn=_llm())
        return [
            run_turn(session, f"turn {i}")["assistant"]["spoke"] for i in range(6)
        ]

    assert spoke(4242) == spoke(4242)


def test_memory_survives_a_restart():
    store = SessionStore()
    session = store.create(seed=42, llm_fn=_llm())
    for index in range(3):
        run_turn(session, f"The player chooses: action {index}")
    save_id = session.save_id

    resumed = SessionStore().resume(save_id, llm_fn=_llm())
    assert len(resumed.ledger.turn_buffer) == 3
    assert resumed.engine.state.turn_number == session.engine.state.turn_number


def test_world_advances_over_a_session():
    """The regression that matters most: the clock used to never move."""
    session = SessionStore().create(seed=42, llm_fn=_llm())
    start_day = session.engine.state.world_day
    start_evil = session.engine.state.evil_progress

    for index in range(8):
        session.engine.state.last_sim_tick_at = 0.0
        run_turn(session, f"The player chooses: action {index}")

    assert session.engine.state.world_day > start_day
    assert session.engine.state.evil_progress > start_evil


# -- the pipeline path, all the way to the socket ------------------------
#
# Nothing exercised the emit block with a multi-agent roster. The pipeline
# tests drive `run_pipeline` directly and stop at its result; the turn tests
# ran the flagship, whose companion is `pipeline: false` and which therefore
# takes the one branch that produces a real assistant result. So the branches
# where `assistant_result` is None -- BOTH of the ones a pipeline story takes
# -- reached `emit_callback` untested, and every Wicked Garden turn died on
# `'NoneType' object has no attribute 'spoke'` after its payload was built.


@pytest.fixture
def garden():
    """The Wicked Garden active, the way a `--game wicked-garden` run has it."""
    from engine.games.registry import activate, deactivate

    activate("wicked-garden")
    try:
        yield
    finally:
        deactivate()


def _plans(monkeypatch, answers):
    """
    Run the REAL pipeline over the Garden's shipped roster, with only the model
    injected -- the roster, the negotiation and the commit are the ones a live
    turn uses. `run_turn` deliberately passes no `llm_fn`, so the seam has to be
    opened here rather than through the session's.
    """
    from engine.scenes import default_state as module

    real = module.run_pipeline

    def planning(state, player_action, **kwargs):
        def llm(messages):
            system = messages[0]["content"]
            for marker, answer in answers.items():
                if marker in system:
                    return json.dumps(answer)
            return json.dumps({"intent": "silent", "beat": ""})

        return real(state, player_action, llm_fn=llm, **kwargs)

    monkeypatch.setattr(module, "run_pipeline", planning)


def test_a_pipeline_turn_reaches_the_client_when_a_character_speaks(garden, monkeypatch):
    _plans(monkeypatch, {
        "SOPHIA": {"intent": "speak", "beat": "she answers", "line": "There you are."},
    })
    session = SessionStore().create(seed=42, llm_fn=_llm())

    events = _events(session, "The player chooses: step through")

    turn = next(p for n, p in events if n == "turn_update")
    assert turn["negotiation"]["ran"] is True
    # The companion column carries HER line -- the slot is "the other voice",
    # and `character` marks who it is.
    assert turn["assistant"]["character"] == "sophia"
    assert turn["assistant"]["text"] == "There you are."
    assert turn["assistant"]["spoke"] is True


def test_a_silent_pipeline_turn_reaches_the_client(garden, monkeypatch):
    """
    Silence is a real outcome of a negotiation and must not take the turn down.

    This is the branch the live Garden bug fired on: both agents plan silent,
    the pipeline still ran, and no companion is summoned to fill the gap.
    """
    _plans(monkeypatch, {})
    session = SessionStore().create(seed=42, llm_fn=_llm())

    events = _events(session, "The player chooses: wait")

    turn = next(p for n, p in events if n == "turn_update")
    assert turn["negotiation"]["ran"] is True
    assert turn["assistant"]["spoke"] is False
    # No line, so no line event -- the column renders from the turn payload.
    assert not [n for n, _ in events if n == "assistant_speak"]
