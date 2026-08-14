"""
The MCP tool layer: engine/mcp/skills_server.py and the `integrations` transport.

WHAT IS REAL HERE AND WHAT IS NOT. The transport tests are mocked -- they pin
the request body, not LM Studio's behaviour. The server tests are NOT mocked:
they stand the real FastMCP server up on a real socket and talk to it with a
real MCP client, because the whole point of this layer is that a hand-rolled
JSON endpoint would look correct and never be called. The live-LM-Studio
evidence lives in scripts/mcp_live_proof.py.

Everything that needs the optional `fastmcp` package skips without it, which is
the same promise engine/mcp/skills_server.py makes to a checkout that never
installs it.
"""

from __future__ import annotations

import asyncio
import json
import socket
from typing import Any, Iterator

import pytest

from engine.game.engine import GameEngine
from engine.game.state import GameState
from engine.lmstudio.backend import LMStudioBackend
from engine.lmstudio.native import NativeClient
from engine.mcp import skills_server
from engine.mcp.skills_server import (
    SkillsServer,
    build_server,
    load_skill_packs,
    mcp_integration,
    skill_input_schema,
    tool_definitions,
)
from engine.skills.registry import (
    AGENT_ASSISTANT,
    AGENT_STORYTELLER,
    AGENT_SYSTEM,
    SKILL_REGISTRY,
)

needs_fastmcp = pytest.mark.skipif(
    not skills_server.available(),
    reason="the optional 'fastmcp' package is not installed",
)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture
def engine() -> GameEngine:
    state = GameState()
    state.session_id = "run-1"
    return GameEngine(state)


@pytest.fixture
def live_server(engine: GameEngine) -> Iterator[SkillsServer]:
    """A real MCP server on a real port, resolving exactly one session."""

    def resolve(session_id: str) -> GameEngine:
        if session_id == "run-1":
            return engine
        raise KeyError(session_id)

    server = SkillsServer(resolve_engine=resolve, port=_free_port())
    assert server.start(), "the skills server did not come up"
    yield server


def _headers(session: str = "run-1", agent: str = AGENT_STORYTELLER) -> dict[str, str]:
    return {"X-Game-Session": session, "X-Game-Agent": agent}


def _call(server: SkillsServer, name: str, args: dict[str, Any], **identity: str) -> Any:
    """Call one tool over real SSE and decode the engine's receipt."""
    from fastmcp import Client
    from fastmcp.client.transports import SSETransport

    async def run() -> str:
        async with Client(SSETransport(server.url, headers=_headers(**identity))) as client:
            result = await client.call_tool(name, args)
            return str(result.content[0].text)

    return json.loads(asyncio.run(run()))


def _list(server: SkillsServer, **identity: str) -> list[str]:
    from fastmcp import Client
    from fastmcp.client.transports import SSETransport

    async def run() -> list[str]:
        async with Client(SSETransport(server.url, headers=_headers(**identity))) as client:
            return sorted(t.name for t in await client.list_tools())

    return asyncio.run(run())


# -- the definitions come from the registry, per agent --------------------


def test_tool_definitions_match_the_registry_allowlist():
    """
    The manifest is the registry, filtered by SkillDef.agents.

    Not a hand-maintained list. The registry's own allowlist is what keeps a
    system-only skill -- the unbounded world tick -- from reaching a model by
    being forgotten somewhere.
    """
    load_skill_packs()
    for agent in (AGENT_STORYTELLER, AGENT_ASSISTANT, AGENT_SYSTEM):
        names = {d["name"] for d in tool_definitions(agent)}
        assert names == {s.name for s in SKILL_REGISTRY.tools_for_agent(agent)}
        assert names, f"{agent} may call nothing at all"


def test_the_world_tick_is_not_offered_to_either_model_facing_agent():
    """advance_world_tick writes time. Only the system agent may call it."""
    load_skill_packs()
    for agent in (AGENT_STORYTELLER, AGENT_ASSISTANT):
        assert "advance_world_tick" not in {d["name"] for d in tool_definitions(agent)}
    assert "advance_world_tick" in {d["name"] for d in tool_definitions(AGENT_SYSTEM)}


def test_the_input_schema_is_the_one_engine_lmstudio_tools_builds():
    """
    One home for signature introspection, not two.

    A second walk over the same signatures is how a manifest drifts from the
    code it describes -- the exact failure engine/lmstudio/tools.py exists to
    prevent.
    """
    from engine.lmstudio.tools import skill_to_openai_tool

    load_skill_packs()
    rest = SKILL_REGISTRY.get("rest")
    assert rest is not None
    assert skill_input_schema(rest) == skill_to_openai_tool(rest)["function"]["parameters"]
    assert skill_input_schema(rest)["properties"]["kind"] == {"type": "string"}


# -- the server enforces the allowlist on both list and call --------------


@needs_fastmcp
def test_listing_shows_only_what_the_requesting_agent_may_call(live_server):
    """
    Filtered at the server, not only at the dispatcher.

    A tool the model is allowed to SEE and then refused is a wasted turn and a
    confused narrator, so the listing is agent-specific too.
    """
    storyteller = _list(live_server, agent=AGENT_STORYTELLER)
    assistant = _list(live_server, agent=AGENT_ASSISTANT)

    assert storyteller == sorted(
        s.name for s in SKILL_REGISTRY.tools_for_agent(AGENT_STORYTELLER)
    )
    assert assistant == sorted(
        s.name for s in SKILL_REGISTRY.tools_for_agent(AGENT_ASSISTANT)
    )
    assert "advance_world_tick" not in storyteller
    assert set(storyteller).isdisjoint(assistant)


@needs_fastmcp
def test_calling_a_skill_the_agent_may_not_call_is_refused(live_server):
    """
    Belt and braces with the dispatcher's own check.

    This endpoint is a socket on localhost, reachable by anything on the
    machine. Hiding the world tick from the listing is not the same as
    refusing it.
    """
    refused = _call(live_server, "advance_world_tick", {}, agent=AGENT_STORYTELLER)
    assert "not callable by storyteller" in refused["error"]

    also_refused = _call(live_server, "query_evil_state", {}, agent=AGENT_ASSISTANT)
    assert "not callable by assistant" in also_refused["error"]


@needs_fastmcp
def test_a_call_that_names_no_session_is_refused(live_server):
    """
    Never served from a process global.

    That fallback is F-09: one session rebinding the active engine while
    another was blocked on a multi-second LLM call, so skills resolved against
    the wrong player's state.
    """
    from fastmcp import Client
    from fastmcp.client.transports import SSETransport

    async def run() -> str:
        async with Client(SSETransport(live_server.url)) as client:
            result = await client.call_tool("query_quests", {})
            return str(result.content[0].text)

    assert "no session named" in json.loads(asyncio.run(run()))["error"]


@needs_fastmcp
def test_a_call_naming_an_unknown_session_is_refused(live_server):
    """A stale id is a legible refusal, not somebody else's game."""
    refused = _call(live_server, "query_quests", {}, session="run-does-not-exist")
    assert refused["error"] == "Unknown session: run-does-not-exist"


@needs_fastmcp
def test_a_call_is_served_against_the_session_it_names(live_server, engine):
    """The engine bound to the call is the one whose id the caller sent."""
    engine.state.evil_progress = 0.42
    served = _call(live_server, "query_evil_state", {}, session="run-1")
    assert served["evil_progress"] == pytest.approx(0.42)


# -- a mutating skill still funnels through the single writer -------------


@needs_fastmcp
def test_a_mutating_skill_still_goes_through_apply_effect(
    live_server, engine, monkeypatch: pytest.MonkeyPatch
):
    """
    The MCP layer is a TRANSPORT, not a second way to write game state.

    ``effects.apply_effect`` is the only writer (critical rule 3). A skill
    reached over MCP runs through the same ``execute_tool`` the turn pipeline
    uses, so the funnel is intact -- this test is what stops a future
    "optimisation" from calling ``skill_def.func`` directly here.
    """
    from engine.game import effects as effects_module

    seen: list[dict[str, Any]] = []
    real = effects_module.apply_effect

    def spy(state: Any, effect: dict[str, Any], **kwargs: Any) -> Any:
        seen.append(dict(effect))
        return real(state, effect, **kwargs)

    monkeypatch.setattr(effects_module, "apply_effect", spy)

    engine.state.stats.stamina = 40
    receipt = _call(live_server, "rest", {"kind": "rest_short"})

    assert receipt.get("error") is None, receipt
    assert engine.state.stats.stamina > 40
    assert any(e.get("type") == "stamina" for e in seen), seen


# -- the integration payload ----------------------------------------------


def test_an_integration_must_name_a_session():
    with pytest.raises(ValueError):
        mcp_integration("http://127.0.0.1:8770/mcp/sse", "")


# -- the mcp.json route, which is the one that works locally --------------


def test_registering_writes_one_entry_and_touches_nothing_else(tmp_path):
    """
    That file is LM Studio's, and whatever else the player registered in it.

    Only keys under the `engine-skills-` prefix are ever written or removed.
    """
    path = tmp_path / "mcp.json"
    path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "system-controller": {"command": "python", "args": ["server.py"]},
                    "hf-mcp-server": {"url": "https://huggingface.co/mcp"},
                }
            }
        ),
        encoding="utf-8",
    )

    name = skills_server.register_session(
        "http://127.0.0.1:8770/mcp/sse", "run-1", path=path, settle_seconds=0
    )
    assert name == "engine-skills-run-1"

    servers = json.loads(path.read_text(encoding="utf-8"))["mcpServers"]
    assert set(servers) == {"system-controller", "hf-mcp-server", "engine-skills-run-1"}
    assert servers["system-controller"] == {"command": "python", "args": ["server.py"]}
    # The session can only travel in the entry's static headers, which is why
    # each run gets an entry of its own rather than sharing one.
    assert servers["engine-skills-run-1"]["headers"]["X-Game-Session"] == "run-1"
    assert servers["engine-skills-run-1"]["url"] == "http://127.0.0.1:8770/mcp/sse"

    assert skills_server.unregister_sessions("run-1", path=path) == 1
    after = json.loads(path.read_text(encoding="utf-8"))["mcpServers"]
    assert set(after) == {"system-controller", "hf-mcp-server"}


def test_pruning_removes_only_this_projects_entries(tmp_path):
    """
    A crashed process leaves entries pointing at a dead port.

    LM Studio then spends a failed connection on each of them at every
    request, so a fresh start clears them -- and nothing else.
    """
    path = tmp_path / "mcp.json"
    path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "engine-skills-old-1": {"url": "http://127.0.0.1:8770/mcp/sse"},
                    "engine-skills-old-2": {"url": "http://127.0.0.1:8770/mcp/sse"},
                    "somebody-elses": {"url": "https://example.test/mcp"},
                }
            }
        ),
        encoding="utf-8",
    )
    assert skills_server.unregister_sessions(path=path, all_ours=True) == 2
    assert set(json.loads(path.read_text(encoding="utf-8"))["mcpServers"]) == {
        "somebody-elses"
    }


def test_a_plugin_id_carries_the_namespace_lm_studio_demands():
    """A bare entry name is rejected: "Expected 'owner/name'"."""
    assert skills_server.plugin_integration("engine-skills-run-1") == {
        "type": "plugin",
        "id": "mcp/engine-skills-run-1",
    }


def test_registration_survives_a_file_that_is_not_there(tmp_path):
    """No mcp.json means no tool calling, never a crash."""
    missing = tmp_path / "nested" / "mcp.json"
    assert (
        skills_server.register_session(
            "http://127.0.0.1:8770/mcp/sse", "run-1", path=missing, settle_seconds=0
        )
        is None
    )
    assert skills_server.unregister_sessions("run-1", path=missing) == 0


def test_the_ephemeral_form_is_not_what_a_loopback_server_is_reached_by(
    tmp_path, monkeypatch: pytest.MonkeyPatch
):
    """
    Measured against the live server: an ephemeral integration naming a
    loopback URL is refused with "URL resolves to a non-public address. We only
    allow public addresses for dynamic remote MCP connections." So the default
    is the mcp.json plugin form, and `ephemeral` stays available for a server
    that really is public.
    """
    path = tmp_path / "mcp.json"
    path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(skills_server, "mcp_json_path", lambda: path)
    monkeypatch.setattr(skills_server, "get_config", lambda: _config({"register_settle_seconds": 0}))

    server = SkillsServer(resolve_engine=lambda _sid: None, port=8770)
    payload = server.integration("run-1")
    assert payload == {"type": "plugin", "id": "mcp/engine-skills-run-1"}
    assert "engine-skills-run-1" in json.loads(path.read_text(encoding="utf-8"))["mcpServers"]

    # Registered once, not once per turn: the settle pause after writing must
    # never land in a turn's critical path.
    path.write_text(json.dumps({"mcpServers": {}}), encoding="utf-8")
    assert server.integration("run-1") == payload
    assert json.loads(path.read_text(encoding="utf-8"))["mcpServers"] == {}


class _config:
    """Minimal get_config stand-in for the lmstudio.mcp keys."""

    def __init__(self, overrides: dict[str, Any]) -> None:
        self._overrides = overrides

    def get(self, key: str, default: Any = None) -> Any:
        return self._overrides.get(key.rsplit(".", 1)[-1], default)


def test_the_integration_carries_the_session_in_headers_and_url():
    """
    The header is what a call is read from; the URL keeps connections distinct.

    Measured: under SSE the request in scope when a tool runs is the
    ``/messages`` POST, whose URL the server minted -- so a query-only
    integration is refused. What the query still buys is a URL that differs per
    run, so a pooling client cannot hand two sessions one connection.
    """
    payload = mcp_integration(
        "http://127.0.0.1:8770/mcp/sse", "run-1", agent=AGENT_STORYTELLER
    )
    assert payload["type"] == "ephemeral_mcp"
    assert payload["server_label"]
    assert payload["headers"]["X-Game-Session"] == "run-1"
    assert payload["headers"]["X-Game-Agent"] == AGENT_STORYTELLER
    assert "session=run-1" in payload["server_url"]
    # Empty allowed_tools means "everything this agent may call"; sending an
    # empty list would mean the opposite to LM Studio.
    assert "allowed_tools" not in payload


def test_allowed_tools_is_sent_only_when_it_narrows_something():
    payload = mcp_integration(
        "http://127.0.0.1:8770/mcp/sse", "run-1", allowed_tools=["query_quests"]
    )
    assert payload["allowed_tools"] == ["query_quests"]


# -- the transport: integrations ride native, response_format never does ---


def test_the_native_payload_carries_integrations_and_no_response_format():
    """
    Both halves matter, and they are the reason this layer exists separately.

    ``/api/v1/chat`` rejects ``response_format`` with 400 ``unrecognized_keys``
    -- including alongside ``integrations`` -- so the tool call and the
    grammared narration can never be one request.
    """
    client = NativeClient(base_url="http://test.local/v1")
    integration = mcp_integration("http://127.0.0.1:8770/mcp/sse", "run-1")
    payload = client._payload(
        [{"role": "user", "content": "look around"}],
        model="m",
        temperature=0.5,
        max_tokens=100,
        reasoning="off",
        context_length=4096,
        stream=False,
        integrations=[integration],
    )
    assert payload["integrations"] == [integration]
    assert payload["reasoning"] == "off"
    assert "response_format" not in payload
    assert "tools" not in payload
    client.close()


def test_integrations_are_a_reason_to_use_native_not_to_avoid_it():
    """
    The routing rule inverts for MCP.

    Inline ``tools=`` must go OpenAI-compat because the native route rejects
    them. ``integrations`` is the opposite: only the native route reads the key
    at all, so falling back to compat would silently drop the tools and return
    an answer the model invented instead of resolved.
    """
    backend = LMStudioBackend(prefer_native=True)
    backend._native_available = True

    assert backend.use_native(integrations=[{"type": "ephemeral_mcp"}]) is True
    assert backend.use_native(tools=[{"type": "function"}]) is False
    assert (
        backend.use_native(
            integrations=[{"type": "ephemeral_mcp"}],
            response_format={"type": "json_schema"},
        )
        is False
    )


def test_integrations_cannot_be_served_when_the_native_route_is_down():
    """
    Refused loudly rather than answered without tools.

    A silent compat fallback here is worse than a failure: the model answers,
    the narration reads fine, and every mechanical outcome in it was invented.
    """
    backend = LMStudioBackend(prefer_native=True)
    backend._native_available = False
    assert backend.use_native(integrations=[{"type": "ephemeral_mcp"}]) is False


def test_tool_call_events_are_collected_into_the_response():
    """
    The SSE plumbing in events.py was built and unused. Wired, not duplicated.

    LM Studio runs the tool loop itself and reports each call back through
    ``tool_call.*``. Those receipts are what a player's log needs, so they are
    collected rather than merely logged.
    """
    import httpx

    frames = [
        'event: tool_call.start\ndata: {"type":"tool_call.start","tool":"query_quests"}\n\n',
        'event: tool_call.arguments\ndata: {"type":"tool_call.arguments","arguments":{}}\n\n',
        'event: tool_call.success\ndata: {"type":"tool_call.success","tool":"query_quests",'
        '"id":"call_1","arguments":{},"output":"{}"}\n\n',
        'event: message.delta\ndata: {"type":"message.delta","content":"Two are open."}\n\n',
        'event: chat.end\ndata: {"type":"chat.end","result":{"response_id":"r1",'
        '"stats":{"input_tokens":10,"total_output_tokens":5,'
        '"reasoning_output_tokens":0}}}\n\n',
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content)["integrations"]
        return httpx.Response(
            200,
            content="".join(frames).encode(),
            headers={"content-type": "text/event-stream"},
        )

    client = NativeClient(base_url="http://test.local/v1")
    client._client = httpx.Client(transport=httpx.MockTransport(handler))

    generator = client.chat_stream(
        [{"role": "user", "content": "what is open?"}],
        model="m",
        reasoning="off",
        integrations=[mcp_integration("http://127.0.0.1:8770/mcp/sse", "run-1")],
    )
    deltas: list[str] = []
    try:
        while True:
            deltas.append(next(generator))
    except StopIteration as stop:
        response = stop.value

    assert deltas == ["Two are open."]
    assert [c.name for c in response.tool_calls] == ["query_quests"]
    assert response.reasoning_tokens == 0
    client.close()


# -- degrades cleanly ------------------------------------------------------


def test_the_server_declines_to_start_without_the_optional_package(
    monkeypatch: pytest.MonkeyPatch,
):
    """
    A missing dependency costs tool calling, never the game.

    Every other generation feature here degrades this way -- the shipped art
    pack and the text fallbacks are what runs out of the box.
    """
    monkeypatch.setattr(skills_server, "available", lambda: False)
    server = SkillsServer(resolve_engine=lambda _sid: None, port=_free_port())
    assert server.start(wait_seconds=0.1) is False
    assert server.is_listening() is False


def test_build_server_says_what_is_missing(monkeypatch: pytest.MonkeyPatch):
    """An ImportError three frames deep is not an answer anybody can act on."""
    import builtins

    real_import = builtins.__import__

    def refuse(name: str, *args: Any, **kwargs: Any) -> Any:
        if name.startswith("fastmcp"):
            raise ImportError("no fastmcp")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", refuse)
    with pytest.raises(RuntimeError, match="pip install fastmcp"):
        build_server(lambda _sid: None)
