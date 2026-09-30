"""
The reply is held to the schema that was built for it, on every rung (spec §4.4).

Without the grammar on the wire -- rung 2 (``json_object``) and rung 3 (none)
-- a model can write what the turn schema forbids: an intent the engine never
offered, a key the schema never declared. ``schemas.conform`` runs right
after ``parse_storyteller_response`` and drops:

* an undeclared top-level key;
* any WHOLE choice whose intent verb or target is outside the turn's enums
  (stripping only the intent would leave a choice promising a walk no
  mechanic performs -- itself a rule-1 breach);
* an out-of-enum value of a declared key (an ``npc_id``, where one is
  declared);

and tops the choices up from the generic fallback rows when fewer than two
survive. On rung 1 the grammar already made all of that unsamplable, so it is
a no-op there.

THE RULE-1 AUDIT, PER RUNG (spec §4.4's table). Rule 1 has two halves, and a
storyteller turn is driven from a fixture on each rung to show both hold:

1. an illegal intent is never offered or executed -- on rung 1 by the grammar
   (and, should a server lie, by ``conform``), on rungs 2 and 3 by ``conform``;
2. a legal-then-illegal intent -- offered while legal, gone illegal by the
   time it runs -- produces an engine-authored refusal that reaches the
   narrator's MECHANICAL RESULTS block (``prompts.receipts_block``).
"""

from __future__ import annotations

import json
import logging
from typing import Any

import pytest

from engine.agents.storyteller import _FALLBACK_CHOICES, conform_turn
from engine.llm.schemas import conform, intent_legal, storyteller_turn_schema
from tests.llm_wire import wire
from tests.test_llm_request_shaping import chat_answer, discovery

NARRATION = (
    "The path east narrows between the birches, and somewhere ahead a clock "
    "ticks in the dark. The air smells of oil and cold iron. The bark is scored "
    "with marks that look deliberate, as if someone counted the hours here, and "
    "you keep walking while the ticking keeps pace with you, step for step."
)

LEGAL = {
    "id": "a",
    "text": "Head for the village square",
    "hint": "safe",
    "intent": {"action": "travel", "target": "edgewood_square"},
}
#: Not adjacent to the forest clearing: a road the engine does not offer.
UNREACHABLE = {
    "id": "b",
    "text": "March straight to Millhaven's gate",
    "intent": {"action": "travel", "target": "millhaven_gate"},
}
#: A verb the engine has no skill for at all.
UNOFFERED = {
    "id": "c",
    "text": "Teleport into the bakery",
    "intent": {"action": "teleport", "target": "edgewood_bakery"},
}


def _flagship_schema() -> dict[str, Any]:
    from engine.game.intents import legal_intents
    from engine.game.procgen import new_game_state

    return storyteller_turn_schema(intents=legal_intents(new_game_state(seed=7)))


@pytest.fixture
def flagship() -> Any:
    from engine.games import registry

    registry.activate("clockwork-dark")
    try:
        yield
    finally:
        registry.deactivate()


# -- conform, by itself ----------------------------------------------------------------


def test_a_legal_envelope_is_unchanged(flagship: Any) -> None:
    """Rung 1's case: everything the grammar allows passes untouched."""
    schema = _flagship_schema()
    parsed = {
        "narration": NARRATION,
        "choices": [LEGAL, {"id": "b", "text": "Rest a while"}],
        "ledger_delta": {},
    }
    assert conform(parsed, schema) == parsed
    assert conform(parsed, schema)["choices"] is parsed["choices"]


def test_illegal_choices_go_whole_and_the_fallback_tops_up(flagship: Any, caplog: Any) -> None:
    schema = _flagship_schema()
    parsed = {"narration": NARRATION, "choices": [LEGAL, UNREACHABLE, UNOFFERED]}
    with caplog.at_level(logging.WARNING):
        out = conform(parsed, schema, fallback=_FALLBACK_CHOICES)
    assert out["choices"] == [LEGAL, {"id": "b", "text": "Look around"}]
    assert "millhaven_gate" in caplog.text and "teleport" in caplog.text
    # The input is never mutated.
    assert parsed["choices"] == [LEGAL, UNREACHABLE, UNOFFERED]


def test_an_intent_with_an_out_of_enum_extra_is_illegal(flagship: Any) -> None:
    schema = _flagship_schema()
    intent_prop = schema["schema"]["properties"]["choices"]["items"]["properties"]["intent"]
    good = {"action": "check", "target": "stealth", "difficulty": "hard"}
    assert intent_legal(intent_prop, good)
    assert not intent_legal(intent_prop, {**good, "difficulty": "impossible"})
    assert not intent_legal(intent_prop, {**good, "bonus": 5})
    assert not intent_legal(intent_prop, "travel")


def test_undeclared_keys_are_dropped_and_named(flagship: Any, caplog: Any) -> None:
    schema = _flagship_schema()
    parsed = {
        "narration": NARRATION,
        "choices": [LEGAL, {"id": "b", "text": "Wait", "hint": "reckless", "cost": 3}],
        "stat_changes": {"gold": 50},
    }
    with caplog.at_level(logging.WARNING):
        out = conform(parsed, schema)
    assert "stat_changes" not in out
    assert out["choices"][1] == {"id": "b", "text": "Wait"}
    for named in ("stat_changes", "cost", "reckless"):
        assert named in caplog.text


def test_an_out_of_enum_npc_id_is_dropped(caplog: Any) -> None:
    """The generic rule: a declared key's enum (the present-NPC one, where declared)."""
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "narration": {"type": "string"},
            "npc_id": {"enum": ["maris", "tobin"]},
        },
    }
    with caplog.at_level(logging.WARNING):
        assert conform({"narration": "x", "npc_id": "ghost"}, schema) == {"narration": "x"}
    assert "ghost" in caplog.text
    assert conform({"narration": "x", "npc_id": "maris"}, schema)["npc_id"] == "maris"


def test_the_parsers_own_keys_survive_and_a_models_are_reset(flagship: Any) -> None:
    """``conform_turn``: the engine's defaults pass; a model-written one is dropped."""
    from engine.agents.storyteller import parse_storyteller_response

    schema = _flagship_schema()
    clean = parse_storyteller_response(
        json.dumps({"narration": NARRATION, "choices": [LEGAL, {"id": "b", "text": "Wait"}]})
    )
    assert conform_turn(clean, schema) == clean
    dirty = parse_storyteller_response(
        json.dumps(
            {
                "narration": NARRATION,
                "choices": [LEGAL, {"id": "b", "text": "Wait"}],
                "tool_calls": [{"name": "move_to", "args": {"location_id": "edgewood_square"}}],
                "tags_inline": "[IMAGE: a fire]",
            }
        )
    )
    out = conform_turn(dirty, schema)
    assert out["tool_calls"] == [] and out["tags_inline"] == ""
    # No schema was built (an injected llm_fn): nothing to conform to.
    assert conform_turn(dirty, None) is dirty


def test_the_choices_are_cut_at_the_schemas_max_items(flagship: Any, caplog: Any) -> None:
    """Five legal choices: the client's shortcuts cover four, and so does the schema."""
    schema = _flagship_schema()
    five = [{"id": "a", "text": f"Option {n}"} for n in range(5)]
    with caplog.at_level(logging.WARNING):
        out = conform({"narration": NARRATION, "choices": five}, schema)
    assert [c["text"] for c in out["choices"]] == [f"Option {n}" for n in range(4)]
    assert [c["id"] for c in out["choices"]] == ["a", "b", "c", "d"]
    assert "maxItems" in caplog.text and "Option 4" in caplog.text


MALFORMED_LEDGERS = {
    "a fact that is a number": {"facts": [42]},
    "names as a list": {"names": ["Maris"]},
    "dispositions as a list": {"npc_disposition": [["maris", 3]]},
    "facts as text": {"facts": "the clock is fast"},
    "a promise with no text, and too many": {
        "promises": [{"to_id": "maris"}, {"text": "a"}, {"text": "b"}]
    },
}


def _conformed_ledger(delta: Any) -> Any:
    out = conform(
        {"narration": NARRATION, "choices": [LEGAL], "ledger_delta": delta}, _flagship_schema()
    )
    return out.get("ledger_delta", {})


def _applied(delta: Any) -> Any:
    """What ``apply_ledger_delta`` makes of ``delta``: its report and the ledger after."""
    from engine.memory.ledger import StoryLedger, apply_ledger_delta

    ledger = StoryLedger()
    accepted = apply_ledger_delta(ledger, delta, turn=1, day=1, known_npc_ids={"maris"})
    return (
        accepted,
        [(f.text, f.subject_id) for f in ledger.facts],
        [(p.text, p.from_id, p.to_id, p.due_day) for p in ledger.promises],
        {k: r.disposition for k, r in ledger.relations.items()},
        dict(ledger.names),
    )


@pytest.mark.parametrize("name", sorted(MALFORMED_LEDGERS))
def test_conform_holds_the_ledger_delta_to_its_schema(flagship: Any, name: str) -> None:
    delta = _conformed_ledger(MALFORMED_LEDGERS[name])
    # Conforming what survived changes nothing, and the ledger reads it as it
    # reads the reply itself.
    assert _conformed_ledger(delta) == delta
    assert _applied(delta) == _applied(MALFORMED_LEDGERS[name])
    assert isinstance(delta.get("names", {}), dict)
    assert isinstance(delta.get("npc_disposition", {}), dict)
    assert len(delta.get("promises", [])) <= 1


#: Shapes ``apply_ledger_delta`` ACCEPTS (coercing where it coerces) that
#: ``conform`` dropped at T4 (2854f07): every one of these tests failed there.
#: Carried from T4's review: without the grammar on the wire, a reply's
#: ledger was held to a stricter shape than the ledger's own, so a text fact
#: or a promise due on day "3" was lost before the ledger could take it.
LEDGER_ACCEPTS = {
    "a fact as plain text": {"facts": ["The mill burned at dusk."]},
    "text and object facts together": {
        "facts": ["The mill burned.", {"text": "Maris owes a debt.", "subject_id": "maris"}]
    },
    "a due day as a string": {"promises": [{"text": "Return the key", "to_id": "maris", "due_day": "3"}]},
    "a due day as a float": {"promises": [{"text": "Return the key", "to_id": "maris", "due_day": 3.0}]},
    "a due day with a fraction": {"promises": [{"text": "Return the key", "due_day": 3.7}]},
    "a fact whose text is a number": {"facts": [{"text": 42}]},
    "the first three facts, then the filter": {"facts": [42, "a", "b", "c"]},
}


@pytest.mark.parametrize("name", sorted(LEDGER_ACCEPTS))
def test_conform_accepts_exactly_what_the_ledger_accepts(flagship: Any, name: str) -> None:
    raw = LEDGER_ACCEPTS[name]
    delta = _conformed_ledger(raw)
    assert _applied(delta) == _applied(raw)
    assert _applied(raw)[1] or _applied(raw)[2]  # not vacuous: the ledger takes something
    assert _conformed_ledger(delta) == delta


@pytest.mark.parametrize(
    "promise",
    [{"to_id": "maris"}, {"text": "", "to_id": "maris"}, {"text": "   ", "to_id": "maris"}],
    ids=["no_text", "empty", "whitespace"],
)
def test_a_promise_of_nothing_is_refused_by_the_ledger_and_by_conform(
    flagship: Any, promise: dict[str, Any]
) -> None:
    """
    Fix round 1: ``add_promise`` recorded a blank promise owed to Maris, and
    ``conform`` kept it because the ledger did. Both refuse it now. Fails at
    87a7055.
    """
    from engine.memory.ledger import StoryLedger

    raw = {"promises": [promise]}
    assert _applied(raw)[2] == []
    assert _applied(raw)[0]["promises"] == []
    assert _conformed_ledger(raw) == {"promises": []}
    assert StoryLedger().add_promise("  ", to_id="maris") is None


#: Shapes on which conform and the ledger already agreed at T4 -- refusals,
#: and one the ledger coerces -- held there.
LEDGER_AGREES = {
    "a due day that is no number": {"promises": [{"text": "Soon", "due_day": "soon"}]},
    "a due day that is a bool": {"promises": [{"text": "Soon", "due_day": True}]},
    "a disposition that is no number": {"npc_disposition": {"maris": "fond"}},
    "a disposition as a string number": {"npc_disposition": {"maris": "3"}},
    "a fact with no text": {"facts": [{"subject_id": "maris"}]},
    "a fact that is a list": {"facts": [["the", "mill"]]},
    "an undeclared ledger key": {"moods": {"maris": "wary"}},
}


@pytest.mark.parametrize("name", sorted(LEDGER_AGREES))
def test_conform_and_the_ledger_still_agree(flagship: Any, name: str) -> None:
    raw = LEDGER_AGREES[name]
    delta = _conformed_ledger(raw)
    assert _applied(delta) == _applied(raw)
    assert _conformed_ledger(delta) == delta


#: ``json.loads`` reads ``Infinity``, and ``int(inf)`` raises OverflowError,
#: which the ledger did not catch: the delta raised after the turn committed.
#: Both fail at T4 (2854f07).
LEDGER_OVERFLOWS = {
    "a due day past any int": {"promises": [{"text": "Soon", "due_day": float("inf")}]},
    "a disposition past any int": {"npc_disposition": {"maris": float("-inf")}},
}


@pytest.mark.parametrize("name", sorted(LEDGER_OVERFLOWS))
def test_a_value_past_any_int_is_refused_not_raised(flagship: Any, name: str) -> None:
    raw = LEDGER_OVERFLOWS[name]
    delta = _conformed_ledger(raw)
    assert _applied(delta) == _applied(raw)
    assert _applied(raw)[0]["dispositions"] == {}
    assert all(due is None for *_rest, due in _applied(raw)[2])


@pytest.mark.parametrize("name", sorted(MALFORMED_LEDGERS))
def test_apply_ledger_delta_skips_a_malformed_entry_rather_than_raising(name: str) -> None:
    """The second guard, for a caller that did not conform (and for LM Studio ``off``)."""
    from engine.memory.ledger import StoryLedger, apply_ledger_delta

    accepted = apply_ledger_delta(
        StoryLedger(), MALFORMED_LEDGERS[name], turn=1, day=1, known_npc_ids={"maris"}
    )
    assert accepted["names"] == [] and accepted["dispositions"] == {}


def test_the_format_block_names_the_whole_contract(flagship: Any) -> None:
    """
    §4.2: the envelope's keys, the choice ids and hints, and each verb's
    legal targets THIS turn -- the contract the grammar would have carried.
    """
    from engine.llm.schemas import render_format_block

    block = render_format_block(_flagship_schema())
    for text in (
        '"narration" (required)',
        '"choices" (required)',
        '"ledger_delta" (optional)',
        '"a", "b", "c", "d"',
        '"safe", "risky", "costly", "unknown"',
        '{"action": "travel", "target": "deeper_forest" | "edgewood_square" | "herb_glen"}',
        '"action": "check"',
        '"difficulty": "trivial"',
    ):
        assert text in block, text
    assert "millhaven_gate" not in block  # not a road from here
    assert render_format_block(_flagship_schema()) == block  # deterministic


# -- through a turn, per rung -----------------------------------------------------------

RUNGS = {"json_schema": 1, "json_object": 2, "off": 3}


def _turn_on(llm_server: Any, mode: str) -> Any:
    from engine.agents.storyteller import StorytellerAgent
    from engine.game.engine import GameEngine
    from engine.game.procgen import new_game_state

    model = "Qwen/Qwen3-8B"
    llm_server(
        "vllm",
        structured_output=mode,
        profiles={"big": {"model": model}, "small": {"model": model}},
    )
    return StorytellerAgent(GameEngine(new_game_state(seed=7)))


def _chat_bodies(seam: Any) -> list[dict[str, Any]]:
    return [
        json.loads(r["body"]) for r in seam.requests if r["url"].endswith("/chat/completions")
    ]


def _reply(choices: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
    return chat_answer(json.dumps({"narration": NARRATION, "choices": choices, **extra}))


@pytest.mark.real_discovery
def test_a_rung_2_envelope_keeps_the_legal_choice_and_tops_up(
    llm_server: Any, flagship: Any
) -> None:
    """One legal and two illegal choices: the legal one, plus a fallback row."""
    agent = _turn_on(llm_server, "json_object")
    reply = _reply([LEGAL, UNREACHABLE, UNOFFERED])
    with wire(discovery("vllm") + [reply, reply]) as seam:
        result = agent.run_turn("I look east.")
    body = _chat_bodies(seam)[0]
    assert body["response_format"] == {"type": "json_object"}
    assert [c["text"] for c in result.choices] == [LEGAL["text"], "Look around"]
    assert result.choices[0]["intent"] == LEGAL["intent"]
    assert "intent" not in result.choices[1]
    payload = json.dumps(result.to_dict())
    for illegal in (UNREACHABLE, UNOFFERED):
        assert illegal["text"] not in payload
        assert illegal["intent"]["target"] not in payload


@pytest.mark.real_discovery
@pytest.mark.parametrize("mode", sorted(RUNGS))
def test_rule_1_an_illegal_intent_is_never_offered_or_executed(
    llm_server: Any, flagship: Any, mode: str
) -> None:
    """
    Half one, on each rung. The fixture reply offers an unreachable road and
    an unknown verb, and carries a ``tool_calls`` walk besides -- the reply a
    server that ignored (or never had) the grammar can send. On rung 1 a
    server that honours the grammar could not send it; ``conform`` holds even
    if one lies.
    """
    agent = _turn_on(llm_server, mode)
    before = agent.engine.state.location_id
    reply = _reply(
        [LEGAL, UNREACHABLE, UNOFFERED],
        tool_calls=[{"name": "move_to", "args": {"location_id": "millhaven_gate"}}],
    )
    with wire(discovery("vllm") + [reply, reply]) as seam:
        result = agent.run_turn("I look east.")

    first = _chat_bodies(seam)[0]
    system = "\n".join(m["content"] for m in first["messages"] if m["role"] == "system")
    if RUNGS[mode] == 1:
        assert first["response_format"]["type"] == "json_schema"
        assert "OUTPUT FORMAT" not in system
    else:
        # No shape on the wire, so the prompt carries it, with this turn's roads.
        assert "OUTPUT FORMAT" in system and "edgewood_square" in system

    schema = agent._turn_schema
    intent_prop = schema["schema"]["properties"]["choices"]["items"]["properties"]["intent"]
    offered = [c["intent"] for c in result.choices if c.get("intent")]
    assert offered == [LEGAL["intent"]]
    assert all(intent_legal(intent_prop, i) for i in offered)
    assert agent.engine.state.location_id == before
    assert result.tool_receipts == []


@pytest.mark.real_discovery
def test_a_dropped_stat_claim_still_reaches_r003_and_the_oracle(
    llm_server: Any, flagship: Any
) -> None:
    """
    Rung 3: ``stat_changes`` is not in the schema, so ``conform`` drops it from
    the turn -- and keeps it aside, because R003 and the oracle exist to count
    exactly this claim. Nothing applies the fifty gold.
    """
    from engine.telemetry import get_oracle

    agent = _turn_on(llm_server, "off")
    gold = agent.engine.state.stats.gold
    before = get_oracle().metrics().get("unearned_claims_total", 0)
    reply = _reply([LEGAL, {"id": "b", "text": "Wait"}], stat_changes={"gold": 50})
    with wire(discovery("vllm") + [reply, reply]):
        result = agent.run_turn("I look east.")
    assert result.parsed["stat_changes"] == {}
    assert result.parsed["conformed_away"]["stat_changes"] == {"gold": 50}
    assert any(v["rule_id"] == "R003" for v in result.governance)
    assert get_oracle().metrics()["unearned_claims_total"] == before + 1
    assert agent.engine.state.stats.gold == gold


@pytest.mark.real_discovery
def test_a_dropped_skill_check_claim_still_fails_the_evaluator(
    llm_server: Any, flagship: Any
) -> None:
    """Rung 3: a check claimed with no roll behind it is retried, as it always was."""
    agent = _turn_on(llm_server, "off")
    claims = _reply([LEGAL, {"id": "b", "text": "Wait"}], skill_check={"skill": "stealth"})
    clean = _reply([LEGAL, {"id": "b", "text": "Wait"}])
    with wire(discovery("vllm") + [claims, clean]) as seam:
        result = agent.run_turn("I creep east.")
    assert result.retries == 1
    retry = _chat_bodies(seam)[1]
    prompt = "\n".join(m["content"] for m in retry["messages"])
    assert "skill_check requested in JSON but no resolve_skill_check called." in prompt


@pytest.mark.real_discovery
@pytest.mark.parametrize("name", sorted(MALFORMED_LEDGERS))
def test_a_malformed_ledger_delta_does_not_break_a_rung_3_turn(
    llm_server: Any, flagship: Any, name: str, tmp_path: Any, monkeypatch: Any
) -> None:
    """The whole turn, through the session: the ledger is applied after commit."""
    from engine.persistence import reset_save_store
    from engine.persistence.saves import SaveStore
    from engine.scenes.default_state import SessionStore, run_turn

    reset_save_store()
    store = SaveStore(root=tmp_path / "saves")
    monkeypatch.setattr("engine.scenes.default_state.get_save_store", lambda: store)
    model = "Qwen/Qwen3-8B"
    llm_server(
        "vllm",
        structured_output="off",
        profiles={"big": {"model": model}, "small": {"model": model}},
    )
    session = SessionStore().create(seed=42)
    reply = _reply(
        [LEGAL, {"id": "b", "text": "Wait"}], ledger_delta=MALFORMED_LEDGERS[name]
    )
    try:
        with wire(discovery("vllm") + [reply] * 4):
            payload = run_turn(session, "I look east.")
    finally:
        reset_save_store()
    assert payload["narration"]
    assert payload.get("error") is None


@pytest.mark.real_discovery
@pytest.mark.parametrize("mode", sorted(RUNGS))
def test_rule_1_a_legal_then_illegal_intent_is_refused_in_the_prose(
    llm_server: Any, flagship: Any, mode: str
) -> None:
    """
    Half two, on each rung. The road to the square is offered from the
    clearing; before it runs, the player is somewhere it does not reach from.
    ``execute_intent`` refuses it, and the refusal is in the narrator's prompt.
    """
    from engine.agents.tool_dispatcher import execute_intent
    from engine.game.intents import legal_intents

    agent = _turn_on(llm_server, mode)
    state = agent.engine.state
    travel = next(v for v in legal_intents(state) if v.action == "travel")
    assert LEGAL["intent"]["target"] in travel.targets  # legal when offered
    state.location_id = "herb_glen"  # ...and not from here

    receipts = execute_intent(LEGAL["intent"], agent.engine)
    assert receipts and receipts[0].get("refused") is True
    assert state.location_id == "herb_glen"

    reply = _reply([{"id": "a", "text": "Turn back"}, {"id": "b", "text": "Rest"}])
    with wire(discovery("vllm") + [reply, reply]) as seam:
        result = agent.run_turn("I head for the square.", intent_receipts=receipts)
    first = _chat_bodies(seam)[0]
    prompt = "\n".join(m["content"] for m in first["messages"])
    assert "MECHANICAL RESULTS" in prompt
    assert "REFUSED:" in prompt and "did NOT happen" in prompt
    assert result.tool_receipts == receipts
    assert state.location_id == "herb_glen"
