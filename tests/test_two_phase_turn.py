"""
The two-phase turn: mechanics resolve, then narration reports.

``engine/mcp/skills_server.py`` made the ``@skill`` registry reachable by a
model and NOTHING called it -- a NOT WIRED row in docs/AGENTS.md. These tests
hold the wiring that closes it, and the four properties it has to keep:

* with ``lmstudio.mcp.enabled`` false -- the default -- the turn is byte-identical
  to the one that ran before Phase A existed
* with it on, the receipts reach ``receipts_block`` and appear in Phase B's prompt
* Phase A runs BEFORE ``StateTransaction`` opens, or an evaluator retry rolls
  back a skill LM Studio has already been handed the receipt for
* every Phase A failure costs tool calls and nothing else -- the turn still
  completes on Phase B alone

Every model call is injected. These are wiring tests, not model tests; what only
a live run can answer is in ``scripts/mcp_live_proof.py``.

Version: v0.1.0 [2026-08-15]
"""

from __future__ import annotations

import json
from typing import Any, Iterator, Optional

import pytest

from engine.agents import mechanics as mechanics_module
from engine.agents import storyteller as storyteller_module
from engine.agents.mechanics import run_mechanics_phase
from engine.game.engine import GameEngine
from engine.game.procgen import new_game_state
from engine.mcp import skills_server


class _Event:
    """One LM Studio stream frame, in the shape ``chat_stream`` emits."""

    def __init__(
        self,
        event_type: str,
        *,
        tool_name: str = "",
        tool_arguments: Optional[dict[str, Any]] = None,
        tool_output: str = "",
        error: str = "",
    ) -> None:
        self.event_type = event_type
        self.tool_name = tool_name
        self.tool_arguments = tool_arguments or {}
        self.tool_output = tool_output
        self.error = error
        self.content = ""


class _StubClient:
    """
    A native client that replays a fixed event trace.

    Phase A never reads the model's prose -- only the ``tool_call.*`` frames --
    so a stub that emits frames is a complete stand-in for LM Studio here.
    """

    def __init__(self, events: list[_Event], *, raises: Optional[Exception] = None) -> None:
        self.events = events
        self.raises = raises
        self.calls: list[dict[str, Any]] = []

    def is_available(self) -> bool:
        return True

    def chat_stream(self, messages: list[dict[str, Any]], **kwargs: Any) -> Any:
        self.calls.append({"messages": messages, **kwargs})
        if self.raises is not None:
            raise self.raises
        on_event = kwargs.get("on_event")
        for event in self.events:
            if on_event is not None:
                on_event(event)

        def _empty() -> Any:
            return
            yield  # pragma: no cover -- generator marker

        return _empty()


#: Distinguishes "caller said nothing" from "caller said None", which is itself
#: a meaningful answer here: None is how a server reports it could not register.
_DEFAULT = object()


class _StubServer:
    """A skills server that registers without touching mcp.json or a socket."""

    def __init__(self, integration: Any = _DEFAULT) -> None:
        self._integration = (
            {"type": "plugin", "id": "mcp/test"} if integration is _DEFAULT else integration
        )
        self.asked: list[str] = []

    def integration(self, session_id: str, **_kwargs: Any) -> Optional[dict[str, Any]]:
        self.asked.append(session_id)
        return self._integration


#: One read-only receipt in the shape a LIVE round trip actually delivers: the
#: engine's dict, serialised by the skills server, wrapped in MCP's text
#: content-block envelope by the protocol, and handed back on the
#: ``tool_call.success`` frame. Measured on the first live two-phase turn --
#: the earlier assumption that ``tool_output`` was the bare JSON is what put a
#: line of escaped protocol furniture in front of the narrator.
EVIL_STATE = _Event(
    "tool_call.success",
    tool_name="query_evil_state",
    tool_arguments={},
    tool_output=json.dumps(
        [{"type": "text", "text": json.dumps({"phase": "stirring", "progress": 0.21})}]
    ),
)

#: The same receipt from a server that answers plainly, with no envelope.
EVIL_STATE_BARE = _Event(
    "tool_call.success",
    tool_name="query_evil_state",
    tool_arguments={},
    tool_output=json.dumps({"phase": "stirring", "progress": 0.21}),
)


@pytest.fixture
def engine() -> Iterator[GameEngine]:
    """A real run, so a session id and real state exist to resolve."""
    state = new_game_state(player_name="Tester", seed=42)
    yield GameEngine(state)


@pytest.fixture
def phase_a_on(monkeypatch: pytest.MonkeyPatch) -> Iterator[_StubServer]:
    """Phase A enabled, with the server and transport stubbed out."""
    server = _StubServer()
    monkeypatch.setattr(mechanics_module, "mechanics_enabled", lambda: True)
    monkeypatch.setattr(skills_server, "get_skills_server", lambda _resolver: server)
    yield server


# -- the default path -------------------------------------------------------


def test_phase_a_is_off_by_default(engine: GameEngine) -> None:
    """
    The shipped config runs today's turn, and Phase A never builds anything.

    ``lmstudio.mcp.enabled`` is the single switch. If this ever returns receipts
    on a default checkout, a listening socket and an mcp.json write have been
    turned on for everyone who pulls.
    """
    assert mechanics_module.mechanics_enabled() is False
    assert run_mechanics_phase(engine, "look around") == []


def test_a_disabled_phase_a_leaves_the_prompt_byte_identical(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Phase B's payload with Phase A off equals the payload from before it existed.

    Compared against the ONLY honest baseline: the same turn with the Phase A
    call removed from ``run_turn`` altogether. Anything weaker -- asserting a
    substring is absent, say -- would pass while a stray empty block quietly
    changed the prompt every story sends.
    """
    from engine.session.store import SessionStore

    def messages_for(patch_out_phase_a: bool) -> list[dict[str, Any]]:
        seen: list[list[dict[str, Any]]] = []
        session = SessionStore().create(seed=42, llm_fn=None)
        state = session.engine.state
        if patch_out_phase_a:
            monkeypatch.setattr(
                mechanics_module, "run_mechanics_phase", lambda *a, **k: []
            )

        def recording(messages: list[dict[str, Any]]) -> str:
            seen.append([dict(m) for m in messages])
            return json.dumps(
                {
                    "narration": "The clearing is quiet. " * 12,
                    "choices": [{"text": "Wait"}, {"text": "Walk on"}],
                }
            )

        session.storyteller.llm_fn = recording
        session.storyteller.run_turn("look around")
        assert seen, "the Storyteller was never called"
        return seen[0]

    with_wiring = messages_for(patch_out_phase_a=False)
    without_wiring = messages_for(patch_out_phase_a=True)

    assert with_wiring == without_wiring, (
        "Phase A is off and the prompt still changed -- the default turn is no "
        "longer the turn that shipped"
    )


# -- the wired path ---------------------------------------------------------


def test_receipts_reach_the_narrator(
    engine: GameEngine, phase_a_on: _StubServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    A Phase A tool call lands in Phase B's MECHANICAL RESULTS block.

    This is the whole point of the two-phase split: ``receipts_block`` has said
    "AUTHORITATIVE" since it was written, and the model's own resolutions had no
    way to reach it, because the turn grammar forbids ``tool_calls``.
    """
    from engine.agents.prompts import receipts_block

    client = _StubClient([EVIL_STATE])
    receipts = run_mechanics_phase(engine, "how bad is it out there?", client=client)

    assert [r["skill"] for r in receipts] == ["query_evil_state"]
    assert receipts[0]["success"] is True
    assert receipts[0]["result"] == {"phase": "stirring", "progress": 0.21}
    assert receipts[0]["phase"] == "mechanics", (
        "a model's own resolution must be distinguishable from the player's "
        "declared intent"
    )

    block = receipts_block(receipts)
    assert "MECHANICAL RESULTS -- AUTHORITATIVE" in block
    assert "query_evil_state" in block
    assert "stirring" in block


def test_the_mcp_content_envelope_is_peeled_off(
    engine: GameEngine, phase_a_on: _StubServer
) -> None:
    """
    A skill called over a socket must read the same as one called in-process.

    REGRESSION, from the first live two-phase turn. MCP returns a tool result as
    a content array, so the receipt arrived as
    ``[{"type": "text", "text": "{...}"}]`` and ``receipts_block`` put that
    entire envelope in front of the narrator -- escaped JSON wrapped in protocol
    furniture, where what it needed was ``evil_phase: dormant``.
    """
    from engine.agents.prompts import receipts_block

    wrapped = run_mechanics_phase(engine, "look", client=_StubClient([EVIL_STATE]))
    bare = run_mechanics_phase(engine, "look", client=_StubClient([EVIL_STATE_BARE]))

    assert wrapped[0]["result"] == {"phase": "stirring", "progress": 0.21}
    assert wrapped == bare, "the envelope changed the receipt, so the transport leaked"

    block = receipts_block(wrapped)
    assert "'type': 'text'" not in block and '"type": "text"' not in block, (
        f"MCP protocol furniture reached the narrator: {block}"
    )
    assert "stirring" in block


def test_phase_a_asks_for_no_grammar_and_no_reasoning(
    engine: GameEngine, phase_a_on: _StubServer
) -> None:
    """
    The request shape is the whole reason this is a separate call.

    ``/api/v1/chat`` rejects ``response_format`` and is the only route that
    honours ``reasoning: off``. Send a grammar and it 400s; send it to the
    compat route and ``integrations`` is ignored while reasoning eats the turn.
    """
    client = _StubClient([EVIL_STATE])
    run_mechanics_phase(engine, "look", client=client)

    sent = client.calls[0]
    assert sent["reasoning"] == "off"
    assert sent["reasoning_budget"] == 0
    assert "response_format" not in sent
    assert sent["integrations"] == [{"type": "plugin", "id": "mcp/test"}]
    prompt = "\n".join(str(m.get("content", "")) for m in sent["messages"])
    assert "You do not narrate" in prompt


def test_the_turn_binds_tool_calls_to_its_own_session(
    engine: GameEngine, phase_a_on: _StubServer
) -> None:
    """
    A tool call resolves the run that made it, and an unknown id is a KeyError.

    F-09 was a process-global "current engine" serving the wrong player's state
    to a call that arrived while another session blocked on an LLM. The registry
    is keyed by session precisely so that cannot come back.
    """
    run_mechanics_phase(engine, "look", client=_StubClient([EVIL_STATE]))

    session_id = engine.state.session_id
    assert phase_a_on.asked == [session_id]
    assert mechanics_module.resolve_engine(session_id) is engine
    with pytest.raises(KeyError):
        mechanics_module.resolve_engine("a-session-that-never-existed")

    mechanics_module.release_engine(session_id)
    with pytest.raises(KeyError):
        mechanics_module.resolve_engine(session_id)


# -- ordering ---------------------------------------------------------------


def test_phase_a_runs_before_the_transaction_opens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Mechanics resolve OUTSIDE the rollback boundary, and that ordering is load-bearing.

    A skill called inside the transaction is undone by an evaluator retry, while
    LM Studio -- which ran the tool loop itself -- has already been handed the
    receipt and will never learn the roll was rolled back. The player would be
    un-moved and un-charged by a draft they never saw.

    Asserted with a spy on the construction order, the way
    tests/test_governance_commit.py pins the pre-write ordering it depends on.
    """
    from engine.session.store import SessionStore

    order: list[str] = []
    real_transaction = storyteller_module.StateTransaction

    def spy_transaction(*args: Any, **kwargs: Any) -> Any:
        order.append("transaction")
        return real_transaction(*args, **kwargs)

    def spy_phase_a(*_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
        order.append("phase_a")
        return []

    monkeypatch.setattr(storyteller_module, "StateTransaction", spy_transaction)
    monkeypatch.setattr(mechanics_module, "run_mechanics_phase", spy_phase_a)

    session = SessionStore().create(seed=42, llm_fn=None)
    session.storyteller.llm_fn = lambda _m: json.dumps(
        {
            "narration": "The clearing is quiet. " * 12,
            "choices": [{"text": "Wait"}, {"text": "Walk on"}],
        }
    )
    session.storyteller.run_turn("look around")

    assert order[:2] == ["phase_a", "transaction"], (
        f"Phase A must resolve before the rollback boundary exists, got {order}"
    )


# -- degradation ------------------------------------------------------------


@pytest.mark.parametrize(
    "name,setup",
    [
        ("the transport raises", lambda: {"client": _StubClient([], raises=RuntimeError("LM Studio is down"))}),
        ("the model calls nothing", lambda: {"client": _StubClient([])}),
        (
            "the tool itself failed",
            lambda: {
                "client": _StubClient(
                    [
                        _Event(
                            "tool_call.failure",
                            tool_name="roll_check",
                            tool_output=json.dumps({"error": "no such skill"}),
                        )
                    ]
                )
            },
        ),
        ("the stream errored", lambda: {"client": _StubClient([_Event("error", error="boom")])}),
    ],
)
def test_a_broken_phase_a_never_breaks_the_turn(
    engine: GameEngine, phase_a_on: _StubServer, name: str, setup: Any
) -> None:
    """
    Every Phase A failure costs tool calls and nothing else.

    A turn that could fail because its OPTIONAL half failed would be strictly
    worse than not having the half at all -- so each of these returns a list and
    logs, and none of them raise.
    """
    receipts = run_mechanics_phase(engine, "look", **setup())
    assert isinstance(receipts, list), name
    # A failed tool still yields a receipt -- the narrator needs to know it
    # failed -- but never a successful one.
    assert all(r["success"] is False for r in receipts), name


def test_a_server_that_will_not_start_degrades_to_todays_turn(
    engine: GameEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    No fastmcp, no socket, or no writable mcp.json -- all mean "no tool calls".

    ``get_skills_server`` answers None for each of them, and that is a complete
    answer here rather than an error to propagate.
    """
    monkeypatch.setattr(mechanics_module, "mechanics_enabled", lambda: True)
    monkeypatch.setattr(skills_server, "get_skills_server", lambda _resolver: None)
    assert run_mechanics_phase(engine, "look") == []


def test_a_run_that_cannot_be_registered_degrades(
    engine: GameEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An mcp.json that cannot be written turns tool calling off, not the game."""
    monkeypatch.setattr(mechanics_module, "mechanics_enabled", lambda: True)
    monkeypatch.setattr(
        skills_server, "get_skills_server", lambda _resolver: _StubServer(integration=None)
    )
    assert run_mechanics_phase(engine, "look", client=_StubClient([EVIL_STATE])) == []


def test_a_story_declaring_no_skills_still_narrates(
    engine: GameEngine, phase_a_on: _StubServer
) -> None:
    """
    A model with nothing worth calling returns no receipts, and that is fine.

    Most turns are conversation. The Phase A prompt says so in as many words,
    because a model that believes it must call something will roll dice at a
    greeting.
    """
    assert run_mechanics_phase(engine, "hello", client=_StubClient([])) == []
