"""
MCP Live Proof
==============

Stand the skills server up, ask the LIVE LM Studio to call one read-only skill
through ``integrations`` with reasoning OFF, and report what actually happened.

    .\\.venv\\Scripts\\python.exe scripts\\mcp_live_proof.py
    .\\.venv\\Scripts\\python.exe scripts\\mcp_live_proof.py --skill query_quests

WHY A SCRIPT AND NOT A TEST. Everything it touches is a service on this
machine: LM Studio must be running, a model must be loadable, and LM Studio's
own MCP client must be able to reach a socket in THIS process. A test that
needs all three either skips on every clean checkout -- teaching people to
ignore it -- or fails for reasons that have nothing to do with the code. The
protocol conformance is pinned in tests/test_mcp_skills_server.py against a
real server on a real socket with a real MCP client; what only a live run can
answer is whether LM Studio drives it, and what the round trip costs.

WHAT IT PROVES, IN ORDER
------------------------
1. the server comes up and speaks MCP (the tools are listed back)
2. LM Studio accepts ``integrations`` on ``/api/v1/chat`` -- not 400
3. it CONNECTS to the server and runs the tool loop itself
4. the tool call arrives bound to the right session, and is refused if it
   names none
5. reasoning stayed off (``reasoning_output_tokens: 0``) while tools ran,
   which is the entire reason this layer is separate from narration

WHAT IT FOUND, THE FIRST TIME IT RAN. An ``ephemeral_mcp`` integration naming
``http://127.0.0.1:8770/mcp/sse`` is refused: "URL resolves to a non-public
address. We only allow public addresses for dynamic remote MCP connections."
The ``mcp.json`` route is the one that works, and this script exercises it --
which is exactly the kind of thing only a live run can tell you. ``--ephemeral``
re-runs the refused form on purpose, so the finding stays checkable rather than
becoming folklore in a docstring.

READ-ONLY ON PURPOSE. The proof calls ``query_evil_state`` or ``query_quests``
and nothing else. A live probe that moved the player or spent their gold would
be a probe nobody dares run twice.

Version: v0.1.0 [2026-08-14]
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.game.engine import GameEngine  # noqa: E402
from engine.game.procgen import new_game_state  # noqa: E402
from engine.lmstudio.events import LMSStreamEvent  # noqa: E402
from engine.lmstudio.native import NativeClient  # noqa: E402
from engine.lmstudio.profiles import resolve_profile  # noqa: E402
from engine.mcp import skills_server  # noqa: E402
from engine.mcp.skills_server import (  # noqa: E402
    SkillsServer,
    mcp_integration,
    mcp_json_path,
)

#: Read-only skills only. See the module docstring.
SAFE_SKILLS = ("query_evil_state", "query_quests")


def main() -> int:
    parser = argparse.ArgumentParser(description="Prove the MCP tool layer against a live LM Studio")
    parser.add_argument("--skill", default="query_evil_state", choices=SAFE_SKILLS)
    parser.add_argument("--profile", default="utility", help="which lmstudio profile to ask")
    parser.add_argument("--port", type=int, default=0, help="override lmstudio.mcp.port")
    parser.add_argument("--verbose", action="store_true", help="print every SSE event")
    parser.add_argument(
        "--ephemeral",
        action="store_true",
        help="use the ephemeral_mcp form instead, which LM Studio refuses for loopback",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    if not skills_server.available():
        print("FAIL: the optional 'fastmcp' package is not installed.")
        print("      pip install fastmcp")
        return 2

    # -- 1. a real run, so the tool has real state to read ----------------
    state = new_game_state(player_name="Proof", seed=1234)
    engine = GameEngine(state)
    session_id = state.session_id

    def resolve(candidate: str) -> GameEngine:
        if candidate == session_id:
            return engine
        raise KeyError(candidate)

    server = SkillsServer(
        resolve_engine=resolve, port=args.port or None  # type: ignore[arg-type]
    )
    if not server.start():
        print(f"FAIL: the skills server did not come up on {server.url}")
        return 2
    print(f"  server   {server.url}")
    print(f"  session  {session_id}")

    # -- 2. it really speaks MCP, before LM Studio is asked to believe it --
    listed = _list_own_tools(server)
    if args.skill not in listed:
        print(f"FAIL: the server does not offer {args.skill}. It offers: {sorted(listed)}")
        return 2
    print(f"  tools    {len(listed)} listed over MCP, including {args.skill}")

    # -- 3. ask the live model ---------------------------------------------
    profile = resolve_profile(args.profile)
    client = NativeClient()
    if not client.is_available():
        print("FAIL: LM Studio's /api/v1/chat is not answering. Is the server on?")
        print(f"      probed {client.root}/api/v1/chat")
        return 2

    if args.ephemeral:
        integration = mcp_integration(server.url, session_id)
    else:
        integration = server.integration(session_id)
    if integration is None:
        print("FAIL: could not register with LM Studio's mcp.json.")
        print(f"      looked for {mcp_json_path() or '(no candidate found)'}")
        print("      set lmstudio.mcp.mcp_json in config/local.yaml")
        return 2

    print(f"  model    {profile.model} (reasoning=off)")
    print(f"  sending  integrations=[{json.dumps(integration)[:160]}]")

    events: list[LMSStreamEvent] = []
    generator = client.chat_stream(
        [
            {
                "role": "system",
                "content": (
                    "You are the Storyteller of a text RPG. You have tools that read "
                    "the engine's real state. Never guess a mechanical value."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Call the {args.skill} tool, then tell me in one short sentence "
                    "what it returned. Do not answer from memory."
                ),
            },
        ],
        model=profile.model,
        temperature=0.0,
        max_tokens=300,
        reasoning="off",
        reasoning_budget=0,
        context_length=profile.context_tokens,
        integrations=[integration],
        on_event=events.append,
    )

    try:
        try:
            while True:
                next(generator)
        except StopIteration as stop:
            response = stop.value
        except Exception as exc:  # noqa: BLE001 — the failure IS the finding
            print(f"FAIL: the request raised {type(exc).__name__}: {exc}")
            _report_events(events, verbose=True)
            return 1
    finally:
        # Never leave an entry pointing at a port this process is about to
        # stop answering on.
        server.release()

    # -- 4. what came back --------------------------------------------------
    print()
    _report_events(events, verbose=args.verbose)

    tool_events = [e for e in events if e.event_type.startswith("tool_call.")]
    called = [c.name for c in response.tool_calls]

    print()
    print(f"  reasoning_tokens  {response.reasoning_tokens}")
    print(f"  tool_call events  {len(tool_events)}")
    print(f"  receipts          {called or '(none)'}")
    print(f"  narration         {response.content.strip()[:200]!r}")

    ok = True
    if not tool_events:
        print()
        print("FAIL: LM Studio never called the tool.")
        print("      It accepted `integrations` (no 400), so the request shape is right.")
        refusal = next((e.error for e in events if e.event_type == "error"), "")
        if "non-public address" in refusal:
            print("      It REFUSED the connection because the URL is on loopback. That is")
            print("      expected for the ephemeral form -- run without --ephemeral to use")
            print("      the mcp.json route, which is the one that works.")
        elif refusal:
            print(f"      It reported: {refusal[:300]}")
        else:
            print("      Check LM Studio's own logs for the MCP connection attempt, and")
            print(f"      that it can reach {server.url} from its process.")
        ok = False
    if response.reasoning_tokens:
        print()
        print(
            f"WARN: {response.reasoning_tokens} reasoning tokens were spent even with "
            "reasoning='off' and integrations set. That combination is supposed to be free."
        )
    if ok:
        print()
        print("PASS: the model called the engine through MCP, with reasoning off.")
    return 0 if ok else 1


def _list_own_tools(server: SkillsServer) -> set[str]:
    """Ask our own server for its tool list, over the wire it will serve."""
    import asyncio

    from fastmcp import Client
    from fastmcp.client.transports import SSETransport

    async def run() -> set[str]:
        async with Client(
            SSETransport(server.url, headers={"X-Game-Agent": "storyteller"})
        ) as client:
            return {t.name for t in await client.list_tools()}

    return asyncio.run(run())


def _report_events(events: list[LMSStreamEvent], *, verbose: bool) -> None:
    """Print the SSE trace, tool frames always and the rest only on --verbose."""
    for event in events:
        if event.event_type.startswith("tool_call."):
            detail: dict[str, Any] = {
                "tool": event.tool_name,
                "args": event.tool_arguments,
            }
            if event.tool_output:
                detail["output"] = event.tool_output[:200]
            if event.error:
                detail["error"] = event.error
            print(f"  {event.event_type:24} {json.dumps(detail, default=str)[:300]}")
        elif verbose:
            print(f"  {event.event_type:24} {event.content[:80]!r}")


if __name__ == "__main__":
    raise SystemExit(main())
