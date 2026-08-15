"""
Skills MCP Server
=================

The transport that finally lets a model CALL the ``@skill`` registry.

WHY THIS EXISTS
---------------
``engine/lmstudio/tools.py`` has built OpenAI tool definitions from the registry
by introspection since v0.2.0, and since ``turn_loop.py`` was retired in bdb69c5
nothing has called it. Nothing anywhere passes ``tools=``. The registry — every
dice roll, every move, every trade — has been unreachable by any model.

It cannot simply be handed to the narration call either. ``/api/v1/chat`` is the
only LM Studio route that can turn reasoning off (``reasoning: "off"`` → 0
reasoning tokens; the OpenAI-compatible route ignores every knob, which is two
to three minutes of wasted thinking per turn), and that route rejects
``response_format`` with 400 ``unrecognized_keys``. It does NOT reject
``integrations``. So tools and the JSON grammar cannot ride the same call, and
tool calling has to arrive the way the native route accepts it: as an MCP
server LM Studio connects to itself.

THE SHAPE, PORTED FROM COSYSIM
------------------------------
CosySim runs this against a live LM Studio and has for a year, so its
combination is the one copied rather than one reasoned out of the spec:

* a real MCP server (``fastmcp``), not a hand-rolled REST endpoint — LM Studio
  speaks the Model Context Protocol and will never call a bespoke ``/tools``
  route however correct it looks (``CosySim/engine/mcp/cosysim_server.py``)
* SSE transport on its own port (``mcp.run(transport="sse", host=, port=)``,
  ``CosySim/scripts/argus/argus_mcp_server.py:117``)
* attached per request as an ephemeral integration naming that URL —
  ``{"type": "ephemeral_mcp", "server_url": ".../sse"}``
  (``CosySim/engine/agents/scene_agent.py:95-99``)

IN-PROCESS, AND WHY THAT IS NOT OPTIONAL
----------------------------------------
Every skill here resolves its state through ``get_active_engine()``, a
``ContextVar`` set by ``set_active_engine()``. An out-of-process server has no
engine to resolve at all. That is why the server runs on a daemon thread inside
the game's own process: LM Studio reaches it over a real socket (it runs the
tool loop itself — see the ``tool_call.*`` events in
``engine/lmstudio/events.py``), and the handler that answers is standing next to
the engine.

HOW LM STUDIO IS POINTED AT IT, AND THE ONE THING THAT DOES NOT WORK
--------------------------------------------------------------------
There are two ways to name an MCP server on a request, and only one of them
can name this one. Measured against the live server on this machine:

* ``{"type": "ephemeral_mcp", "server_url": ...}`` is REFUSED for every
  address this machine can offer, with::

      Unable to connect to remote MCP server 'game-skills' at url
      '<url>'. URL resolves to a non-public address.
      We only allow public addresses for dynamic remote MCP connections.

  Re-measured 2026-08-15 against a live LM Studio, because "it cannot reach
  localhost" is a big claim to rest on one URL. SEVEN forms were tried and all
  seven came back with that same message, ``type: mcp_connection_error``,
  ``param: integrations``:

  ===================================  =========================
  form                                 result
  ===================================  =========================
  SSE  ``http://localhost:8770``       refused
  SSE  ``http://127.0.0.1:8770``       refused
  SSE  ``http://192.168.1.110:8770``   refused  (LAN IP)
  SSE  ``http://<hostname>:8770``      refused
  HTTP ``http://127.0.0.1:8771/mcp``   refused
  HTTP ``http://192.168.1.110:8771``   refused
  a URL already registered in mcp.json refused  (ephemerally)
  ===================================  =========================

  The LAN IP is the informative one: 192.168.1.110 is routable on this
  network and is still "non-public", so the check is against RFC1918 and
  loopback both, not merely ``127.0.0.1``. Streamable HTTP fares no better
  than SSE, so the URL SUFFIX does not decide how the address is classified.
  Registering the same server in ``mcp.json`` first does not launder its URL
  for ephemeral use either -- the two routes are judged independently.

  That is a policy, not a bug, and it is why LM Studio's own docs call
  ``mcp.json`` "the recommended approach for using MCP servers that take
  actions on your computer". An ephemeral integration is a URL the MODEL's
  host was handed at request time; letting one reach into the loopback
  interface would make every prompt a port scanner.

* ``{"type": "plugin", "id": "mcp/<entry>"}``, naming an entry in LM Studio's
  ``mcp.json``, connects to loopback happily and works. Verified end to end:
  the model called ``query_evil_state``, the receipt came back, and
  ``reasoning_output_tokens`` was 0.

So this module WRITES an ``mcp.json`` entry per run and references it by id.
LM Studio picks the file up without a restart -- also measured; the first
request after the write connected. ``mcp_integration()`` still builds the
ephemeral form, because it is correct for a server on a public address, and
because a future LM Studio that lifts the restriction should not need this
module rewritten.

Two forms of the id exist and only one is accepted: ``"mcp/<entry>"``. A bare
``"<entry>"`` is rejected with "Expected 'owner/name'".

SESSION SCOPING
---------------
A process-global "current engine" would serve the wrong player's state to a
tool call that arrived while another session was blocked on a multi-second LLM
call. That is F-09 in docs/DESIGN_REVIEW.md, already fixed once by replacing a
module global with a ``ContextVar``; re-introducing it here would undo the fix
from the other side.

So the caller's session id rides on the integration itself, twice over:

    headers:  {"X-Game-Session": "<id>", "X-Game-Agent": "storyteller"}
    url:      http://127.0.0.1:<port>/mcp/sse?session=<id>&agent=storyteller

The HEADER is what a call is actually read from, and it is the one measured to
work -- through LM Studio itself, not merely through a test client. An MCP
client sets those headers on its whole HTTP session, so they are on the SSE GET
and on every ``/messages`` POST alike, and the handler sees them. On the
``mcp.json`` route they are the entry's own ``headers`` block, which is why
each run gets an entry of its own rather than sharing one.

The query string is deliberately NOT redundant, but it does a different job
than it looks like it does. Measured against a real MCP client over SSE, the
request in scope when a tool runs is the ``/messages`` POST, whose URL the
server itself minted — our parameters are gone by then, and a query-only
integration is refused. What the parameters still buy is a distinct URL per
run, so a client that pools one connection per server URL can never hand two
sessions the same one. They are read as a fallback because under streamable
HTTP the whole call arrives on one request and they ARE visible there.

A call that names no session is REFUSED. There is no fallback to "whatever
engine was last active", because that fallback is exactly the bug.

THE ALLOWLIST, ENFORCED HERE TOO
--------------------------------
``SkillDef.callable_by(agent)`` is checked when listing tools and again when
calling one. ``engine/agents/tool_dispatcher.py`` still checks it as well: this
endpoint is a socket on localhost, reachable by anything on the machine, and
``advance_world_day`` — the unbounded world tick — is one wrong answer away.

DEGRADES CLEANLY
----------------
``fastmcp`` is optional. This module imports without it; ``available()`` says
so, and everything else raises a legible error rather than an ImportError at
startup. A checkout that never installs it plays the game and passes the suite.

Version: v0.1.0 [2026-08-14]
"""

from __future__ import annotations

import json
import logging
import os
import socket
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional

from engine.config import get_config
from engine.lmstudio.tools import skill_to_openai_tool
from engine.skills.registry import AGENT_STORYTELLER, SKILL_REGISTRY, SkillDef

logger = logging.getLogger(__name__)

#: Where a call says which run it belongs to. Read from the HTTP headers of the
#: connection LM Studio opened, falling back to the query string.
SESSION_HEADER = "x-game-session"
AGENT_HEADER = "x-game-agent"
SESSION_PARAM = "session"
AGENT_PARAM = "agent"

#: Every ``mcp.json`` entry this module writes starts with this. Nothing
#: outside the prefix is ever read, rewritten or removed — that file belongs to
#: LM Studio and to whatever else the player has registered in it.
MCP_JSON_PREFIX = "engine-skills-"
#: The namespace LM Studio requires on a plugin id: a bare entry name is
#: rejected with "Expected 'owner/name'".
MCP_JSON_NAMESPACE = "mcp"

#: ``session_id -> GameEngine``. Raises KeyError for a session that is gone.
EngineResolver = Callable[[str], Any]


def available() -> bool:
    """Whether the optional ``fastmcp`` dependency is importable."""
    try:
        import fastmcp  # noqa: F401
    except Exception:  # noqa: BLE001 — absence is the answer, not an error
        return False
    return True


def load_skill_packs() -> int:
    """
    Import the builtin packs so the registry is populated.

    ``SKILL_REGISTRY`` fills as a side effect of importing the modules that
    decorate into it, so anything that reads the registry before the turn
    pipeline has run sees an EMPTY one. The dispatcher does the same imports for
    the same reason; doing them here rather than importing the dispatcher keeps
    a tool LISTING from dragging in the whole turn machinery.

    Returns:
        How many skills are registered afterwards.
    """
    import engine.skills.builtin.assistant  # noqa: F401 — register skills
    import engine.skills.builtin.items  # noqa: F401 — register skills
    import engine.skills.builtin.livelihood  # noqa: F401 — register skills
    import engine.skills.builtin.mechanics  # noqa: F401 — register skills
    import engine.skills.builtin.quests  # noqa: F401 — register skills

    return SKILL_REGISTRY.count()


def skill_input_schema(skill_def: SkillDef) -> dict[str, Any]:
    """
    The MCP ``inputSchema`` for one skill.

    Deliberately a thin peel off ``engine/lmstudio/tools.skill_to_openai_tool``
    rather than a second walk over the signature. Two schema generators over one
    registry is how a manifest drifts from the code it describes, which is the
    exact failure that module was written to prevent.
    """
    return dict(skill_to_openai_tool(skill_def)["function"]["parameters"])


def tool_definitions(agent: str = AGENT_STORYTELLER) -> list[dict[str, Any]]:
    """
    Every skill the given agent may call, as MCP tool definitions.

    Filtered by the registry's own allowlist, so a system-only skill cannot
    reach a model by being forgotten in a hand-maintained list.
    """
    load_skill_packs()
    return [
        {
            "name": s.name,
            "description": s.description,
            "inputSchema": skill_input_schema(s),
        }
        for s in sorted(SKILL_REGISTRY.tools_for_agent(agent), key=lambda s: s.name)
    ]


# -- request identity --------------------------------------------------------


def _request_identity() -> tuple[str, str]:
    """
    Read ``(session_id, agent)`` off the live HTTP request.

    Returns empty strings when there is no HTTP request in scope at all — an
    in-process client, or a direct unit-test call. The caller decides what an
    unidentified call means; this function never guesses.
    """
    try:
        from fastmcp.server.dependencies import get_http_request
    except Exception:  # noqa: BLE001
        return "", ""

    try:
        request = get_http_request()
    except Exception:  # noqa: BLE001 — RuntimeError when no request is in scope
        return "", ""

    headers = {k.lower(): v for k, v in request.headers.items()}
    params = request.query_params
    session_id = str(headers.get(SESSION_HEADER) or params.get(SESSION_PARAM) or "")
    agent = str(headers.get(AGENT_HEADER) or params.get(AGENT_PARAM) or "")
    return session_id.strip(), agent.strip()


def _requesting_agent(default: str = AGENT_STORYTELLER) -> str:
    _session_id, agent = _request_identity()
    return agent or default


# -- the server --------------------------------------------------------------


def build_server(resolve_engine: EngineResolver, *, name: str = "") -> Any:
    """
    Build a FastMCP server exposing the registry, scoped per request.

    Args:
        resolve_engine: ``session_id -> GameEngine``. Called on every tool call.
            Raising ``KeyError`` for an unknown id is what turns a stale session
            into a legible refusal instead of a wrong answer.
        name: MCP server name advertised to the client.

    Returns:
        A ``fastmcp.FastMCP`` instance with one tool per registered skill.

    Raises:
        RuntimeError: if ``fastmcp`` is not installed.
    """
    try:
        from fastmcp import FastMCP
        from fastmcp.server.middleware import Middleware
        from fastmcp.tools import Tool
        from fastmcp.tools.tool import ToolResult
    except ImportError as exc:  # pragma: no cover — exercised by the skip path
        raise RuntimeError(
            "The MCP skills server needs the optional 'fastmcp' package. "
            "Install it with: pip install fastmcp"
        ) from exc

    cfg = get_config()
    label = name or str(cfg.get("lmstudio.mcp.server_label", "game-skills"))
    load_skill_packs()

    class SkillTool(Tool):  # type: ignore[misc]
        """One registered ``@skill``, as an MCP tool."""

        skill_name: str = ""

        async def run(self, arguments: dict[str, Any]) -> Any:
            return ToolResult(content=_invoke(self.skill_name, arguments))

    def _invoke(skill_name: str, arguments: dict[str, Any]) -> str:
        """
        Resolve the caller's engine, re-check the allowlist, run the skill.

        Everything mutating still goes through ``execute_tool``, so a skill
        called over MCP funnels into ``effects.apply_effect`` exactly as one
        called from the turn pipeline does. This is a transport, not a second
        way to write game state.
        """
        # Imported here rather than at module scope: importing the dispatcher
        # imports every builtin skill pack, and this module is imported by the
        # config layer's consumers long before a game exists.
        from engine.agents.tool_dispatcher import execute_tool

        session_id, agent = _request_identity()
        agent = agent or AGENT_STORYTELLER

        if not session_id:
            logger.warning(
                "[mcp] Refused a tool call that named no session "
                "(operation=call_tool, skill=%s)",
                skill_name,
            )
            return json.dumps(
                {
                    "error": (
                        "no session named — send the run's id in the "
                        f"{SESSION_HEADER} header or the ?{SESSION_PARAM}= query "
                        "parameter of the integration URL"
                    )
                }
            )

        skill_def = SKILL_REGISTRY.get(skill_name)
        if skill_def is None:
            return json.dumps({"error": f"Unknown skill: {skill_name}"})
        if not skill_def.callable_by(agent):
            logger.warning(
                "[mcp] Refused a skill the agent may not call "
                "(operation=call_tool, skill=%s, agent=%s)",
                skill_name,
                agent,
            )
            return json.dumps({"error": f"{skill_name} is not callable by {agent}"})

        try:
            engine = resolve_engine(session_id)
        except KeyError:
            logger.warning(
                "[mcp] Refused a tool call for an unknown session "
                "(operation=call_tool, skill=%s, session=%s)",
                skill_name,
                session_id,
            )
            return json.dumps({"error": f"Unknown session: {session_id}"})

        receipt = execute_tool(skill_name, arguments if isinstance(arguments, dict) else {}, engine)
        logger.debug(
            "[mcp] Tool call served (operation=call_tool, skill=%s, agent=%s, "
            "session=%s, success=%s)",
            skill_name,
            agent,
            session_id,
            receipt.get("success"),
        )
        return json.dumps(receipt["result"])

    class AgentAllowlist(Middleware):  # type: ignore[misc]
        """
        Hide from ``tools/list`` whatever the requesting agent may not call.

        The dispatcher and ``_invoke`` both re-check on the way in. This hook is
        about not TEMPTING the model: a listed tool it is refused for is a
        wasted turn and a confused narrator.
        """

        async def on_list_tools(self, context: Any, call_next: Any) -> Any:
            tools = await call_next(context)
            agent = _requesting_agent()
            permitted = {s.name for s in SKILL_REGISTRY.tools_for_agent(agent)}
            return [t for t in tools if t.name in permitted]

    server = FastMCP(
        label,
        instructions=(
            "Mechanical tools for a text RPG. The engine resolves outcomes; you "
            "narrate them. Call a tool for anything with a mechanical result — "
            "dice, movement, inventory, trade, quests — and never invent the "
            "number yourself. Each call returns the engine's receipt as JSON."
        ),
        middleware=[AgentAllowlist()],
    )

    # Every skill is registered once, for every agent. The middleware above and
    # the check inside ``_invoke`` are what make the list agent-specific; the
    # registration cannot be, because one server serves both agents.
    for skill_def in sorted(SKILL_REGISTRY.all_tools(), key=lambda s: s.name):
        server.add_tool(
            SkillTool(
                name=skill_def.name,
                description=skill_def.description,
                parameters=skill_input_schema(skill_def),
                skill_name=skill_def.name,
            )
        )

    logger.info(
        "[mcp] Skills server built (operation=build_server, label=%s, tools=%s)",
        label,
        SKILL_REGISTRY.count(),
    )
    return server


class SkillsServer:
    """
    The registry, served over MCP on a socket LM Studio can reach.

    Runs on a daemon thread in the game's own process — see the module
    docstring for why out-of-process is not an option.

        server = SkillsServer(resolve_engine=store.require)
        server.start()
        integration = server.integration(session_id, agent="storyteller")
    """

    def __init__(
        self,
        *,
        resolve_engine: EngineResolver,
        host: Optional[str] = None,
        port: Optional[int] = None,
        path: Optional[str] = None,
    ) -> None:
        cfg = get_config()
        self.host = host or str(cfg.get("lmstudio.mcp.host", "127.0.0.1"))
        self.port = int(port if port is not None else cfg.get("lmstudio.mcp.port", 8770))
        self.path = path or str(cfg.get("lmstudio.mcp.path", "/mcp/sse"))
        self.label = str(cfg.get("lmstudio.mcp.server_label", "game-skills"))
        self._resolve_engine = resolve_engine
        self._thread: Optional[threading.Thread] = None
        self._server: Optional[Any] = None
        self._registered: set[str] = set()

    @property
    def url(self) -> str:
        """The SSE endpoint LM Studio connects to."""
        return f"http://{self.host}:{self.port}{self.path}"

    def is_listening(self, timeout: float = 0.5) -> bool:
        """Whether something is accepting connections on the port."""
        try:
            with socket.create_connection((self.host, self.port), timeout=timeout):
                return True
        except OSError:
            return False

    def start(self, *, wait_seconds: float = 10.0) -> bool:
        """
        Start the server and block until the port accepts connections.

        Returns:
            True once the socket is up. False if ``fastmcp`` is missing or the
            port never came up — never raises, because a missing tool layer must
            cost tool calling and not the game.
        """
        if self._thread is not None and self._thread.is_alive():
            return True
        if not available():
            logger.warning(
                "[mcp] Not starting the skills server: the optional 'fastmcp' "
                "package is not installed (operation=start). Tool calling is off; "
                "everything else runs."
            )
            return False

        try:
            self._server = build_server(self._resolve_engine)
        except Exception as exc:  # noqa: BLE001 — the game outranks the tool layer
            logger.error("[mcp] Could not build the skills server (operation=start): %s", exc)
            return False

        def _run() -> None:
            try:
                # SSE, on its own port. This is the combination CosySim proves
                # against a live LM Studio; see the module docstring.
                self._server.run(  # type: ignore[union-attr]
                    transport="sse",
                    host=self.host,
                    port=self.port,
                    path=self.path,
                    show_banner=False,
                )
            except Exception as exc:  # noqa: BLE001
                logger.error("[mcp] Skills server stopped (operation=run): %s", exc)

        self._thread = threading.Thread(target=_run, name="mcp-skills", daemon=True)
        self._thread.start()

        deadline = time.monotonic() + wait_seconds
        while time.monotonic() < deadline:
            if self.is_listening():
                # A crashed process leaves its mcp.json entries behind, all
                # pointing at a port nothing answers on. LM Studio would then
                # spend a failed connection on each of them at every request.
                unregister_sessions(all_ours=True)
                logger.info(
                    "[mcp] Skills server listening (operation=start, url=%s, tools=%s)",
                    self.url,
                    SKILL_REGISTRY.count(),
                )
                return True
            time.sleep(0.1)

        logger.error(
            "[mcp] Skills server never came up (operation=start, url=%s)", self.url
        )
        return False

    def integration(
        self,
        session_id: str,
        *,
        agent: str = AGENT_STORYTELLER,
        allowed_tools: Optional[list[str]] = None,
    ) -> Optional[dict[str, Any]]:
        """
        The ``integrations`` entry that binds one request to one run.

        Registers the run in LM Studio's ``mcp.json`` and returns the plugin
        reference to it. The ephemeral form is NOT used, because LM Studio
        refuses a loopback URL there — see the module docstring for the exact
        refusal.

        Args:
            session_id: The run this call may touch. Required — a call with no
                session is refused server-side rather than served from a global.
            agent: Caller identity, checked against each skill's allowlist on
                both list and call.
            allowed_tools: Narrow further than the agent allowlist already does.
                Defaults to ``lmstudio.mcp.allowed_tools``; empty means "every
                skill this agent may call".

        Returns:
            The integration dict, or None when registration was not possible —
            which means no tool calling for this request, never a broken turn.
        """
        mode = str(get_config().get("lmstudio.mcp.integration", "plugin")).lower()
        if mode == "ephemeral":
            return mcp_integration(
                self.url,
                session_id,
                agent=agent,
                server_label=self.label,
                allowed_tools=allowed_tools,
            )

        # Registered ONCE per run. Rewriting the file every turn would put the
        # settle pause in the player's critical path, and give LM Studio's
        # watcher a reason to reload mid-narration.
        entry = _entry_name(session_id)
        if session_id not in self._registered:
            if register_session(self.url, session_id, agent=agent) is None:
                return None
            self._registered.add(session_id)
        payload = plugin_integration(entry)
        if allowed_tools is None:
            declared = get_config().get("lmstudio.mcp.allowed_tools", []) or []
            allowed_tools = [str(t) for t in declared]
        if allowed_tools:
            payload["allowed_tools"] = list(allowed_tools)
        return payload

    def release(self, session_id: str = "") -> None:
        """
        Drop a run's ``mcp.json`` entry, or every entry this process wrote.

        An entry left behind points at a port that will not be listening after
        this process exits, and LM Studio spends a connection attempt on each
        one at every request.
        """
        if session_id:
            unregister_sessions(session_id)
            self._registered.discard(session_id)
        else:
            unregister_sessions(*self._registered)
            self._registered.clear()


def mcp_integration(
    server_url: str,
    session_id: str,
    *,
    agent: str = AGENT_STORYTELLER,
    server_label: str = "game-skills",
    allowed_tools: Optional[list[str]] = None,
) -> dict[str, Any]:
    """
    Build one ``ephemeral_mcp`` integration payload.

    The documented shape (lmstudio.ai/docs/developer/core/mcp) is
    ``{type, server_label, server_url}`` required, ``allowed_tools`` and
    ``headers`` optional. The session and agent go in BOTH the headers and the
    URL — see the module docstring for why one is not enough.

    NOT the form this server is normally reached by. LM Studio refuses an
    ephemeral integration whose URL resolves to a non-public address, and this
    one is on loopback by design. Kept because it is correct for a server on a
    public address, and so that a future LM Studio which lifts the restriction
    needs no new code — set ``lmstudio.mcp.integration: ephemeral`` and it is
    already wired.
    """
    if not session_id:
        raise ValueError("an MCP integration must name a session")
    if allowed_tools is None:
        declared = get_config().get("lmstudio.mcp.allowed_tools", []) or []
        allowed_tools = [str(t) for t in declared]

    separator = "&" if "?" in server_url else "?"
    scoped = f"{server_url}{separator}{SESSION_PARAM}={session_id}&{AGENT_PARAM}={agent}"

    payload: dict[str, Any] = {
        "type": "ephemeral_mcp",
        "server_label": server_label,
        "server_url": scoped,
        "headers": {
            "X-Game-Session": session_id,
            "X-Game-Agent": agent,
        },
    }
    if allowed_tools:
        payload["allowed_tools"] = list(allowed_tools)
    return payload


def plugin_integration(entry_name: str) -> dict[str, Any]:
    """
    Reference an ``mcp.json`` entry by id.

    ``mcp/<entry>`` is the only accepted spelling; a bare ``<entry>`` is
    rejected with "Invalid artifact identifier format. Expected 'owner/name'".
    """
    return {"type": "plugin", "id": f"{MCP_JSON_NAMESPACE}/{entry_name}"}


def mcp_json_path() -> Optional[Path]:
    """
    Where LM Studio keeps ``mcp.json``.

    Config first (``lmstudio.mcp.mcp_json``), then the known locations. Not a
    literal: rule 5, and the directory moved once already between LM Studio
    builds (``~/.lmstudio`` and ``~/.cache/lm-studio`` both exist in the wild).

    Returns None when no candidate exists, which means "no local tool calling"
    rather than "crash".
    """
    declared = str(get_config().get("lmstudio.mcp.mcp_json", "") or "")
    if declared:
        return Path(declared).expanduser()
    home = Path.home()
    for candidate in (
        home / ".cache" / "lm-studio" / "mcp.json",
        home / ".lmstudio" / "mcp.json",
    ):
        if candidate.exists():
            return candidate
    return None


def _entry_name(session_id: str) -> str:
    return f"{MCP_JSON_PREFIX}{session_id}"


#: Set once per process, so a run leaves ONE backup rather than one per turn.
_backed_up: set[Path] = set()


def backup_once(path: Path) -> Optional[Path]:
    """
    Copy ``mcp.json`` to a timestamped sibling before this process first writes.

    That file is not ours. It holds whatever MCP servers the player has
    registered, and this module edits it in place; a backup is the difference
    between a bug here costing a run and costing their setup. Taken ONCE per
    process — a per-turn backup would bury the good copy under near-identical
    ones.

    Returns:
        The backup path, the existing one if this process already took it, or
        None when there was nothing to copy or the copy failed. A failed backup
        is logged and does NOT stop the write: the file's own atomic rename is
        what protects it from corruption, and refusing to register would cost
        tool calling for a belt-and-braces measure.
    """
    if path in _backed_up or not path.exists():
        return None
    stamp = time.strftime("%Y%m%dT%H%M%S")
    backup = path.with_name(f"{path.name}.bak-{stamp}")
    try:
        backup.write_bytes(path.read_bytes())
    except OSError as exc:
        logger.warning(
            "[mcp] Could not back up mcp.json before writing "
            "(operation=backup_once, path=%s): %s",
            path,
            exc,
        )
        return None
    _backed_up.add(path)
    logger.info(
        "[mcp] Backed up mcp.json before the first write "
        "(operation=backup_once, backup=%s)",
        backup,
    )
    return backup


def _write_json_atomic(path: Path, document: dict[str, Any]) -> None:
    """
    Serialise to a sibling temp file and rename it into place.

    ``write_text`` truncates first, so a process that dies mid-write leaves
    LM Studio a half-written file and the player's other servers gone with it.
    ``os.replace`` is atomic on Windows and POSIX alike, which is the same
    reason ``engine/api/settings.py`` writes ``config/local.yaml`` this way.
    """
    temp = path.with_name(f"{path.name}.tmp")
    temp.write_text(json.dumps(document, indent=2), encoding="utf-8")
    os.replace(temp, path)


def register_session(
    server_url: str,
    session_id: str,
    *,
    agent: str = AGENT_STORYTELLER,
    path: Optional[Path] = None,
    settle_seconds: Optional[float] = None,
) -> Optional[str]:
    """
    Write one ``mcp.json`` entry binding this run to this server.

    ONE ENTRY PER RUN, not one shared entry rewritten per request. The session
    id can only travel in the entry's static ``headers``, so a shared entry
    would have to be rewritten before every call -- and two sessions narrating
    at once would race for it. That race IS F-09, rebuilt in a config file.

    Only keys under this module's own prefix are ever touched, and everything
    else in the file is preserved byte-for-byte in content and re-serialised.
    LM Studio picks the change up without a restart, but NOT instantly: a
    request sent in the same breath as the write can come back with

        Cannot find plugin handle for plugin: mcp/engine-skills-<id>

    It watches the file and reloads asynchronously. ``settle_seconds`` is the
    pause after writing that closes that race
    (``lmstudio.mcp.register_settle_seconds``). It is affordable because this
    is called ONCE per run, when the session is created, rather than on every
    turn — put it in a turn's critical path and it becomes a stall the player
    feels.

    Args:
        settle_seconds: Override the configured pause. Zero skips it, which is
            what a test that never talks to LM Studio wants.

    Returns:
        The entry name, or None when there is no writable ``mcp.json`` -- in
        which case local tool calling is simply off.
    """
    target = path or mcp_json_path()
    if target is None:
        logger.warning(
            "[mcp] No LM Studio mcp.json found, so this server cannot be "
            "registered (operation=register_session). Set lmstudio.mcp.mcp_json "
            "in config/local.yaml. Tool calling is off; the game is unaffected."
        )
        return None

    name = _entry_name(session_id)
    try:
        document = json.loads(target.read_text(encoding="utf-8")) if target.exists() else {}
        if not isinstance(document, dict):
            document = {}
        servers = document.setdefault("mcpServers", {})
        if not isinstance(servers, dict):
            logger.error(
                "[mcp] mcp.json has a mcpServers key that is not an object; "
                "refusing to rewrite it (operation=register_session, path=%s)",
                target,
            )
            return None
        servers[name] = {
            "url": server_url,
            "headers": {
                "X-Game-Session": session_id,
                "X-Game-Agent": agent,
            },
        }
        backup_once(target)
        _write_json_atomic(target, document)
    except (OSError, json.JSONDecodeError) as exc:
        logger.error(
            "[mcp] Could not register with LM Studio (operation=register_session, "
            "path=%s): %s",
            target,
            exc,
        )
        return None

    settle = (
        float(get_config().get("lmstudio.mcp.register_settle_seconds", 1.5))
        if settle_seconds is None
        else float(settle_seconds)
    )
    if settle > 0:
        time.sleep(settle)

    logger.info(
        "[mcp] Registered with LM Studio (operation=register_session, entry=%s, "
        "url=%s, settled=%.1fs)",
        name,
        server_url,
        settle,
    )
    return name


def unregister_sessions(
    *session_ids: str,
    path: Optional[Path] = None,
    all_ours: bool = False,
) -> int:
    """
    Remove entries this module wrote, and only those.

    Args:
        session_ids: Which runs to drop.
        all_ours: Drop every ``engine-skills-`` entry instead. This is what a fresh
            start does: a crashed process leaves entries behind pointing at a
            port nothing is listening on, and LM Studio would then spend a
            connection attempt on each of them at every request.

    Returns:
        How many entries were removed.
    """
    target = path or mcp_json_path()
    if target is None or not target.exists():
        return 0
    try:
        document = json.loads(target.read_text(encoding="utf-8"))
        servers = document.get("mcpServers") if isinstance(document, dict) else None
        if not isinstance(servers, dict):
            return 0
        if all_ours:
            doomed = [k for k in servers if str(k).startswith(MCP_JSON_PREFIX)]
        else:
            doomed = [_entry_name(s) for s in session_ids if _entry_name(s) in servers]
        for key in doomed:
            servers.pop(key, None)
        if doomed:
            backup_once(target)
            _write_json_atomic(target, document)
            logger.info(
                "[mcp] Unregistered (operation=unregister_sessions, entries=%s)",
                len(doomed),
            )
        return len(doomed)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning(
            "[mcp] Could not clean up mcp.json (operation=unregister_sessions, "
            "path=%s): %s",
            target,
            exc,
        )
        return 0


_server: Optional[SkillsServer] = None
_server_lock = threading.Lock()


def active_server() -> Optional[SkillsServer]:
    """
    The running server, or None -- and never starts one.

    Teardown needs to ask "is there a server holding this session?" without
    that question being the thing that boots a server. ``get_skills_server``
    starts one on first use, which makes it exactly the wrong call to reach for
    while cleaning a session up.
    """
    return _server


def get_skills_server(
    resolve_engine: Optional[EngineResolver] = None,
) -> Optional[SkillsServer]:
    """
    The process's skills server, started on first use.

    Returns None when ``lmstudio.mcp.enabled`` is false, when ``fastmcp`` is
    absent, or when no resolver has ever been supplied — all three of which mean
    "no tool calling", never "no game".
    """
    global _server
    with _server_lock:
        if _server is not None:
            return _server
        if not bool(get_config().get("lmstudio.mcp.enabled", False)):
            return None
        if resolve_engine is None:
            return None
        server = SkillsServer(resolve_engine=resolve_engine)
        if not server.start():
            return None
        _server = server
        return _server


def reset_skills_server() -> None:
    """Drop the singleton. Tests, and config reloads."""
    global _server
    with _server_lock:
        _server = None


__all__ = [
    "AGENT_HEADER",
    "MCP_JSON_NAMESPACE",
    "MCP_JSON_PREFIX",
    "EngineResolver",
    "SESSION_HEADER",
    "SkillsServer",
    "available",
    "backup_once",
    "build_server",
    "get_skills_server",
    "load_skill_packs",
    "mcp_integration",
    "mcp_json_path",
    "plugin_integration",
    "register_session",
    "reset_skills_server",
    "skill_input_schema",
    "tool_definitions",
    "unregister_sessions",
]
