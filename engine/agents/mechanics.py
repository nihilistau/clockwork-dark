"""
Phase A — The Mechanics Call
============================

The half of a turn that RESOLVES, before the half that narrates.

WHY A TURN IS TWO CALLS AND NOT ONE
-----------------------------------
Because no single LM Studio request can carry both halves. Measured against
the live server, the two routes are disjoint in exactly the wrong way:

===========================  =================  ==================  ============
route                        ``integrations``   ``response_format`` reasoning off
===========================  =================  ==================  ============
``/api/v1/chat``             accepted           400 unrecognized    yes
``/v1/chat/completions``     ignored            accepted            no
===========================  =================  ==================  ============

So tool calling and the narration grammar cannot ride one request. A turn that
wants both has to spend two:

* **Phase A — mechanics.** Native route, ``reasoning: "off"``, ``integrations``
  pointing at the in-process skills server, no grammar, a small token cap. Its
  output is RECEIPTS. Whatever prose it emits is discarded unread.
* **Phase B — narration.** The existing schema-constrained call, handed Phase
  A's receipts through ``prompts.receipts_block`` — the block that already
  says "MECHANICAL RESULTS -- AUTHORITATIVE".

ORDERING IS LOAD-BEARING
------------------------
Phase A runs BEFORE ``StateTransaction`` opens in
``storyteller.run_turn``. A skill called inside that transaction would be rolled
back by an evaluator retry, and the player would be un-moved and un-charged by a
draft they never saw — while LM Studio's tool loop, which has already returned
the receipt, would never learn the roll was undone. Outside the boundary, a
Phase A receipt is exactly as durable as a resolved player intent, which is the
same rule already written at the top of ``run_turn``: a rejected draft must not
un-walk a walk the player actually took.

``tests/test_two_phase_turn.py`` asserts that ordering with a spy, the way
``tests/test_governance_commit.py`` pins the pre-write ordering it depends on,
because it is the kind of invariant a later refactor silently inverts.

EVERY FAILURE COSTS TOOL CALLS AND NOTHING ELSE
-----------------------------------------------
``run_mechanics_phase`` returns a list, and an empty list is a complete answer.
The server not starting, ``fastmcp`` absent, no writable ``mcp.json``, LM Studio
down, the model declining to call anything, a timeout, a malformed receipt — all
of them log at WARNING and return ``[]``, which leaves Phase B running exactly
the turn it runs today. A turn must never fail because the optional half of it
did.

With ``lmstudio.mcp.enabled: false`` — the default — this module returns ``[]``
before building anything at all, so the turn's payload is byte-identical to the
one it sent before this file existed.

SESSION SCOPING, AND WHY THIS IS A MAP AND NOT A GLOBAL
-------------------------------------------------------
``_ENGINES`` is keyed BY SESSION. The distinction matters: F-09 in
docs/DESIGN_REVIEW.md was a process-global "current engine", which served the
wrong player's state to a tool call arriving while another session sat blocked
on a multi-second LLM call. A map keyed by session id is what the server's
``EngineResolver`` was designed to be handed, and an unknown key raises
``KeyError`` so a stale session becomes a legible refusal rather than a wrong
answer.

Version: v0.1.0 [2026-08-15]
"""

from __future__ import annotations

import json
import logging
import threading
from typing import Any, Callable, Optional

from engine.config import get_config
from engine.skills.registry import AGENT_STORYTELLER

logger = logging.getLogger(__name__)

#: ``session_id -> GameEngine``, for tool calls arriving over the socket.
_ENGINES: dict[str, Any] = {}
_ENGINES_LOCK = threading.Lock()


def register_engine(engine: Any) -> str:
    """
    Make one run resolvable by a tool call that names it.

    Idempotent, and called at the top of every mechanics phase rather than once
    at session creation: a session resumed from a save is a different
    ``GameEngine`` object under the same id, and a stale entry would serve the
    pre-reload state.

    Returns:
        The session id now registered.
    """
    session_id = str(engine.state.session_id)
    with _ENGINES_LOCK:
        _ENGINES[session_id] = engine
    return session_id


def release_engine(session_id: str) -> None:
    """Forget a finished run, so its id stops resolving."""
    with _ENGINES_LOCK:
        _ENGINES.pop(str(session_id), None)


def resolve_engine(session_id: str) -> Any:
    """
    The ``EngineResolver`` handed to the skills server.

    Raises:
        KeyError: for a session that was never registered or has ended. The
            server turns that into a refusal naming the id, which is the only
            honest answer — there is deliberately no fallback to "whatever
            engine was last active", because that fallback IS F-09.
    """
    with _ENGINES_LOCK:
        engine = _ENGINES.get(str(session_id))
    if engine is None:
        raise KeyError(session_id)
    return engine


def mechanics_enabled() -> bool:
    """Whether Phase A should run at all. One switch: ``lmstudio.mcp.enabled``."""
    return bool(get_config().get("lmstudio.mcp.enabled", False))


def _unwrap_mcp_content(payload: Any) -> Any:
    """
    Peel MCP's content-block envelope off a tool result.

    MEASURED, on the first live two-phase turn. ``execute_tool`` returns the
    engine's own dict, but by the time it has crossed MCP and come back through
    LM Studio's ``tool_call.success`` frame it arrives as the protocol's content
    array::

        [{"type": "text", "text": "{\\"evil_progress\\": 0.0, ...}"}]

    Left alone, ``receipts_block`` renders that whole envelope at the narrator --
    a line of escaped JSON wrapped in protocol furniture, when what it needs is
    ``evil_phase: dormant``. Unwrapped, the receipt is indistinguishable from one
    the turn pipeline produced in-process, which is the point: a skill called
    over a socket must read the same as a skill called directly.

    Returns the inner value when the payload is a text content array, and the
    payload untouched otherwise -- so a server that answers plainly is not
    mangled by a rule written for one that does not.
    """
    if isinstance(payload, list) and len(payload) == 1 and isinstance(payload[0], dict):
        block = payload[0]
        if block.get("type") == "text" and "text" in block:
            inner = str(block.get("text") or "")
            try:
                return json.loads(inner)
            except json.JSONDecodeError:
                return inner
    return payload


def _receipt_from_event(event: Any) -> Optional[dict[str, Any]]:
    """
    Turn one ``tool_call.success``/``tool_call.failure`` frame into a receipt.

    The frame's ``tool_output`` is what the skills server returned, wrapped in
    MCP's content envelope — see :func:`_unwrap_mcp_content`. Unwrapped, it is
    ``execute_tool``'s own ``result``, so the receipt this builds is the same
    shape ``receipts_block`` already renders for a resolved player intent.

    A frame whose output will not parse still yields a receipt, marked
    unsuccessful, because a tool that ran and returned something unreadable is a
    fact the narrator needs more than it needs a tidy list.
    """
    name = str(getattr(event, "tool_name", "") or "")
    if not name:
        return None

    raw = str(getattr(event, "tool_output", "") or "")
    failed = str(getattr(event, "event_type", "")).endswith("failure")
    try:
        result = _unwrap_mcp_content(json.loads(raw)) if raw else {}
    except json.JSONDecodeError:
        result = {"raw": raw}

    if not isinstance(result, dict):
        result = {"value": result}

    success = not failed and "error" not in result
    return {
        "skill": name,
        "args": dict(getattr(event, "tool_arguments", {}) or {}),
        "result": result,
        "success": success,
        # Marks where this came from, for anything downstream that wants to
        # tell a model's resolution from the player's own declared intent.
        "phase": "mechanics",
    }


def mechanics_messages(state: Any, player_action: str) -> list[dict[str, str]]:
    """
    The Phase A prompt: resolve, do not narrate.

    Deliberately tiny. This call is not writing the turn, and every token spent
    telling it how to write prose is a token spent encouraging it to. The system
    line is the story-neutral half; nothing here names a story, because Phase A
    is engine work and a narrator's persona belongs to Phase B.
    """
    from engine.agents.prompts import mechanics_prompt

    return [
        {"role": "system", "content": mechanics_prompt(state)},
        {"role": "user", "content": player_action},
    ]


def run_mechanics_phase(
    engine: Any,
    player_action: str,
    *,
    agent: str = AGENT_STORYTELLER,
    client: Any = None,
    on_event: Optional[Callable[[Any], None]] = None,
) -> list[dict[str, Any]]:
    """
    Resolve this turn's mechanics by letting the model call the ``@skill``
    registry, and return what the engine actually did.

    Args:
        engine: The run this turn belongs to. Registered so a tool call naming
            its session resolves to it and to nothing else.
        player_action: The player's choice or free text, verbatim.
        agent: Caller identity, checked against each skill's allowlist on both
            list and call — so a system-only skill stays out of reach.
        client: Transport override for tests. Anything with ``chat_stream``.
        on_event: Sink for the raw stream events, for diagnostics.

    Returns:
        Receipts in ``receipts_block`` shape. EMPTY whenever tool calling is
        off, unavailable, or failed — see the module docstring. Never raises.
    """
    if not mechanics_enabled():
        return []

    try:
        return _run_mechanics_phase(
            engine, player_action, agent=agent, client=client, on_event=on_event
        )
    except Exception as exc:  # noqa: BLE001 — the turn outranks its optional half
        logger.warning(
            "[mechanics] Phase A failed; narrating without receipts "
            "(operation=run_mechanics_phase): %s",
            exc,
        )
        return []


def _run_mechanics_phase(
    engine: Any,
    player_action: str,
    *,
    agent: str,
    client: Any,
    on_event: Optional[Callable[[Any], None]],
) -> list[dict[str, Any]]:
    """The body of :func:`run_mechanics_phase`, minus the blanket guard."""
    from engine.lmstudio.profiles import resolve_profile
    from engine.mcp.skills_server import get_skills_server

    session_id = register_engine(engine)

    server = get_skills_server(resolve_engine)
    if server is None:
        logger.warning(
            "[mechanics] No skills server, so Phase A is skipped "
            "(operation=run_mechanics_phase, session=%s). Narration runs "
            "unchanged; the model simply cannot call the engine this turn.",
            session_id,
        )
        return []

    integration = server.integration(session_id, agent=agent)
    if integration is None:
        logger.warning(
            "[mechanics] Could not register this run with LM Studio, so Phase A "
            "is skipped (operation=run_mechanics_phase, session=%s). Set "
            "lmstudio.mcp.mcp_json in config/local.yaml if mcp.json is elsewhere.",
            session_id,
        )
        return []

    if client is None:
        from engine.lmstudio.native import NativeClient

        client = NativeClient()
        # `integrations` is read by the NATIVE route only, and it is also the
        # only route that honours reasoning: off. There is no compat fallback
        # here on purpose: one would silently drop the tools and spend two
        # minutes reasoning to produce nothing this phase can use.
        if not client.is_available():
            logger.warning(
                "[mechanics] LM Studio's native route is not answering, so "
                "Phase A is skipped (operation=run_mechanics_phase, root=%s).",
                getattr(client, "root", "?"),
            )
            return []

    cfg = get_config()
    profile = resolve_profile(str(cfg.get("lmstudio.mcp.phase_a.profile", "utility")))
    max_tokens = int(cfg.get("lmstudio.mcp.phase_a.max_tokens", 400))

    events: list[Any] = []

    def _collect(event: Any) -> None:
        events.append(event)
        if on_event is not None:
            on_event(event)

    generator = client.chat_stream(
        mechanics_messages(engine.state, player_action),
        model=profile.model,
        temperature=0.0,
        max_tokens=max_tokens,
        reasoning="off",
        reasoning_budget=0,
        context_length=profile.context_tokens,
        integrations=[integration],
        on_event=_collect,
    )

    # Drained rather than consumed: Phase A's prose is not the turn's prose, and
    # streaming it to the player would put the model's mechanical muttering on
    # screen ahead of the narration that reports it.
    try:
        while True:
            next(generator)
    except StopIteration:
        pass

    receipts: list[dict[str, Any]] = []
    for event in events:
        if not str(getattr(event, "event_type", "")).startswith("tool_call."):
            continue
        if str(event.event_type) not in ("tool_call.success", "tool_call.failure"):
            continue
        receipt = _receipt_from_event(event)
        if receipt is not None:
            receipts.append(receipt)

    if receipts:
        logger.info(
            "[mechanics] Phase A resolved %s call(s) (operation=run_mechanics_phase, "
            "session=%s, skills=%s)",
            len(receipts),
            session_id,
            [r["skill"] for r in receipts],
        )
    else:
        error = next(
            (
                e.error
                for e in events
                if str(getattr(e, "event_type", "")) == "error" and getattr(e, "error", "")
            ),
            "",
        )
        logger.info(
            "[mechanics] Phase A called nothing (operation=run_mechanics_phase, "
            "session=%s)%s",
            session_id,
            f": {error}" if error else "",
        )
    return receipts


__all__ = [
    "mechanics_enabled",
    "mechanics_messages",
    "register_engine",
    "release_engine",
    "resolve_engine",
    "run_mechanics_phase",
]
