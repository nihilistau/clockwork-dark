"""
LMSClient — the OpenAI-compatible SSE client, for every provider but Ollama.

Uses ``POST {base_url}/chat/completions``. On LM Studio this is the fallback
transport: it is the only one that can do tool calling and ``response_format``
structured output, but it CANNOT control reasoning (see lmstudio_native.py for the
measurements). Prefer ``engine.llm.backend`` which routes between this and
NativeClient. On vLLM, llama-server and a generic server it is the only route,
shaped by the provider row (v0.19.0): the reasoning-off patch and the cap that
goes with it (``reasoning_patch``, ``patched_cap``), ``ttl`` only where the row
keeps it, and inline ``<think>`` moved to the reasoning channel
(``InlineThinkSplitter``). The class name's ``LMS`` is historical.

THE BUG THIS FILE CARRIED
-------------------------
Both read paths took ``message["content"]`` and nothing else::

    delta = (first.get("delta") or {}).get("content", "") or ""   # streaming
    content=message.get("content") or ""                          # non-streaming

A reasoning model that hits ``max_tokens`` while still thinking returns
``{"content": "", "reasoning_content": "<400 tokens>"}`` with
``finish_reason: "length"``. ``content_parts`` stayed empty, the player watched
a frozen screen, and the log said nothing at all. Both paths now read all three
channels LM Studio can use -- ``content``, ``reasoning_content`` (DeepSeek
style, 0.3.9+) and ``reasoning`` (gpt-oss style, 0.3.23+) -- keep reasoning in
its own field, and shout when the content channel came back empty behind a full
reasoning channel.

Version: v0.3.0 [2026-08-08]
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
import weakref
from typing import Any, Callable, Generator, Optional

import httpx

from engine.config import get_config
from engine.llm.events import LMSResponse, LMSStreamEvent, ToolCall
from engine.llm.gate import call_timeout, time_left, turn_expired
from engine.llm.profiles import ModelProfile, resolve_profile, wire_cap
from engine.llm.providers import ReasoningPatch, get_provider
from engine.llm.routes import compat_base
from engine.locks import renew_after_fork

logger = logging.getLogger(__name__)

_client_instance: Optional["LMSClient"] = None
#: Guards building and dropping ``_client_instance`` (v0.20.0), so a release
#: during a build waits for it and drops what it built, rather than leaving a
#: client built from the old config in place (engine/locks.py: #13).
_client_lock = threading.Lock()
renew_after_fork(globals(), _client_lock=threading.Lock)


def compat_cap(max_tokens: int, reasoning_budget: int) -> int:
    """
    The wire ceiling for this transport, which always budgets for reasoning.

    Unlike the native route, ``/v1/chat/completions`` has no working way to
    turn reasoning off -- every knob is ignored (see lmstudio_native.py for the
    measurements). So a request routed here will think whether or not it was
    asked to, and the reasoning budget is granted UNCONDITIONALLY. Honouring a
    ``reasoning: off`` that the server will ignore is how a schema-constrained
    call ends up with an empty content channel: structured output constrains
    the content channel only, and gives no protection at all against the
    deliberation that precedes it.
    """
    return wire_cap(max_tokens, reasoning_budget, "on")


def reasoning_patch(
    model: str, reasoning: Optional[str], *, route: str = "compat"
) -> Optional[ReasoningPatch]:
    """
    What turns thinking off for ``model`` on ``route`` under the configured
    provider, or None (spec §5.1).

    Only ``off`` asks for a patch: ``on`` and the effort levels send nothing on
    a compat route. The model's facts come from the registry's CACHE, never
    the network -- by the time a request body is being built the model is
    bound, and discovery inside a player's turn is what ``cached`` exists to
    prevent. On LM Studio's compat route this is always None (the row's
    grammar route cannot carry it), so its requests are v0.18's.
    """
    if str(reasoning or "") != "off":
        return None
    from engine.llm.registry import get_registry

    return get_provider().reasoning_off_patch(get_registry().cached(model), route)


def patched_cap(
    max_tokens: int, reasoning_budget: int, reasoning: Optional[str],
    patch: Optional[ReasoningPatch],
) -> int:
    """
    The compat wire cap: ``wire_cap(..., mode if patch_trusted else "on")``.

    The reasoning budget is dropped only when a TRUSTED patch went on the wire
    (§5.2). An untrusted one keeps the full "on" cap, so a template that
    ignores ``enable_thinking`` still has room to think and then answer; with
    no patch at all this is ``compat_cap``, v0.18's number.
    """
    if patch is not None and patch.trusted:
        return wire_cap(max_tokens, reasoning_budget, str(reasoning or "on"))
    return compat_cap(max_tokens, reasoning_budget)


_THINK_OPEN = "<think>"
_THINK_CLOSE = "</think>"

#: How many responses this process saw arrive with thinking inline in
#: ``content`` (§4.5). The doctor reads it after its probes, to say which
#: server flag would stop it; ``reset_lms_client`` clears it with the client.
_inline_think_seen = 0


def _note_inline_think() -> None:
    global _inline_think_seen
    _inline_think_seen += 1


def inline_think_seen() -> int:
    """Responses seen with a leading inline ``<think>`` span, this process."""
    return _inline_think_seen


#: Models already warned about ignoring their reasoning-off patch, this process.
_patch_ignored_warned: set[str] = set()


def warn_patch_ignored(model: str) -> None:
    """
    Once per model: its template ignored the reasoning-off patch (measured in
    v0.19.0 T8 on llama-server's ``enable_thinking`` and Ollama's ``think``).
    """
    if model in _patch_ignored_warned:
        return
    _patch_ignored_warned.add(model)
    logger.warning(
        "[llm] The model ignored its reasoning-off patch: it thought anyway, and "
        "the server sent that thinking inside the answer, closed by </think> with "
        "no opening tag -- moved to the reasoning channel (model=%s). Its chat "
        "template opens <think> whatever the patch says. Leave the model "
        "undeclared, or at least never declare `off` in its "
        "llm.declared_models.<id>.reasoning: the patch then stays untrusted, "
        "and an answer to it is read this way (docs/MODEL_SERVERS.md).",
        model,
    )


class InlineThinkSplitter:
    """
    Moves a leading ``<think>…</think>`` span from content to reasoning (§4.5).

    vLLM without ``--reasoning-parser`` and llama-server with
    ``--reasoning-format none`` send a reasoning model's thinking INSIDE
    ``content``. Left there it reaches the narration decoder and the tag
    buffer, and an ``[IMAGE:]`` written while thinking would fire a real image
    generation. Fed the content channel delta by delta (or whole), it returns
    ``(channel, text)`` pieces: ``"reasoning"`` or ``"content"``.

    Only a LEADING span counts: the first non-whitespace text must open the
    tag. The tag may be split across deltas anywhere, including inside
    ``<think>`` or ``</think>``, so a possible prefix is held back until it is
    decided. An unclosed span at the end is reasoning, not content: the
    response then reads as starved, not as narration.

    THINKING WITH NO OPENING TAG (measured on llama-server b7966, v0.19.0
    T8). A chat template that opens ``<think>`` in the PROMPT
    (Qwen3-4B-Thinking-2507's, whatever ``enable_thinking`` says) makes the
    model's first token already thinking. When the server does not split it
    out -- ``--reasoning-format none``, or a request that sent the
    reasoning-off patch, which the server believes -- the thinking arrives in
    ``content`` with NO opening tag, then ``</think>``, then the answer.
    ``hold`` catches it: nothing is released until it is decided, and text up
    to a ``</think>`` that no ``<think>`` opened is reasoning. A whole answer
    (``strip_inline_think``) is always read this way, at no cost. A STREAM
    is held only when its request carried an untrusted patch (``forced_open``)
    AND no grammar (fix round 1): holding shows the player nothing until the
    stream ends, and under a grammar an orphan ``</think>`` cannot arrive in
    the content -- llama-server binds the grammar from the first token, and
    Ollama sends thinking under ``format`` in ``message.thinking`` (both
    measured). So a grammared stream is read as ``start``; only an ungrammared
    ``off`` stream to an undeclared model waits for its end. That, and
    ``--reasoning-format none``, is why docs/MODEL_SERVERS.md names the cost.

    Under ``forced_open`` the close is the signal: a ``<think>`` the thinking
    MENTIONS before its orphan ``</think>`` (a model reasoning about its own
    output format) does not turn it into an answer, so nothing it said --
    ``[IMAGE:]`` included -- reaches the content. Without ``forced_open`` a
    ``<think>`` before any close is read as mid-answer text, as before.

    ``forced_open`` also decides a held answer cut at the cap with no
    ``</think>`` (``flush(truncated=True)``): thinking that never closed, which
    reads as starved -- unless the request carried a grammar (``grammar``)
    and the text starts as JSON (``{`` or ``[``), which is then an answer cut
    off: under a grammar the content provably begins as JSON, so the tell is
    sound there. Without one it is not -- thinking that drafts its JSON opens
    with a brace too (T8 re-review N2) -- so ANY unclosed text cut at the cap
    under an untrusted, ungrammared patch is read as starved: a cut answer,
    prose or JSON, cannot be told from unclosed thinking there
    (docs/MODEL_SERVERS.md). Without ``forced_open``, such text is an answer
    that was cut off. An orphan
    ``</think>`` under ``forced_open`` means the model ignored its patch
    (``patch_ignored``, warned once per model); without it, the server sent
    inline thinking a flag would have split (``inline_think_seen``).
    """

    def __init__(
        self,
        *,
        forced_open: bool = False,
        hold: Optional[bool] = None,
        grammar: bool = False,
    ) -> None:
        self._forced_open = forced_open
        #: The request carried a grammar (``response_format`` / ``format``),
        #: so its content provably begins as JSON: the one case where a
        #: brace-led cut text is an answer, not unclosed thinking.
        self._grammar = grammar
        held = forced_open if hold is None else hold
        # start | maybe_open | thinking | after | content
        self._state = "maybe_open" if held else "start"
        self._held = ""
        #: Whether an orphan ``</think>`` was seen under ``forced_open``.
        self.patch_ignored = False

    def push(self, text: str) -> list[tuple[str, str]]:
        out: list[tuple[str, str]] = []
        if not text:
            return out
        self._held += text
        while self._held:
            if self._state == "content":
                out.append(("content", self._held))
                self._held = ""
            elif self._state == "maybe_open":
                stripped = self._held.lstrip()
                if stripped.startswith(_THINK_OPEN):
                    # A template that writes its own opening tag: the
                    # ordinary leading-span rules decide it.
                    self._state = "start"
                    continue
                if stripped and _THINK_OPEN.startswith(stripped):
                    # Only a proper prefix ("<", "<thi") so far: it may still
                    # be the tag, or thinking that begins with "<". Wait,
                    # rather than decide on where a delta happened to end
                    # (T8 re-review N1).
                    return out
                end = self._held.find(_THINK_CLOSE)
                opened = self._held.find(_THINK_OPEN)
                if not self._forced_open and opened >= 0 and (end < 0 or opened < end):
                    # "<think>" in mid-answer, before any close: not a span.
                    # (Under forced_open the orphan close is the signal, and a
                    # <think> the thinking mentions does not cancel it.)
                    self._state = "content"
                    continue
                if end < 0:
                    return out  # undecided: hold everything back
                if self._forced_open:
                    self.patch_ignored = True
                else:
                    _note_inline_think()
                thought = self._held[:end].strip()
                if thought:
                    out.append(("reasoning", thought))
                self._held = self._held[end + len(_THINK_CLOSE):]
                self._state = "after"
            elif self._state == "start":
                stripped = self._held.lstrip()
                if not stripped:
                    return out  # whitespace so far: undecided
                if stripped.startswith(_THINK_OPEN):
                    _note_inline_think()
                    self._state = "thinking"
                    self._held = stripped[len(_THINK_OPEN):]
                elif _THINK_OPEN.startswith(stripped):
                    return out  # a possible split "<thi": wait for more
                else:
                    self._state = "content"
            elif self._state == "thinking":
                end = self._held.find(_THINK_CLOSE)
                if end >= 0:
                    if end:
                        out.append(("reasoning", self._held[:end]))
                    self._held = self._held[end + len(_THINK_CLOSE):]
                    self._state = "after"
                    continue
                keep = _partial_suffix(self._held, _THINK_CLOSE)
                ready = self._held[: len(self._held) - keep]
                if ready:
                    out.append(("reasoning", ready))
                self._held = self._held[len(ready):]
                return out
            else:  # after: the whitespace between the span and the answer
                stripped = self._held.lstrip()
                if not stripped:
                    self._held = ""
                    return out
                self._held = stripped
                self._state = "content"
        return out

    def flush(self, *, truncated: bool = False) -> list[tuple[str, str]]:
        """
        The end of the response: whatever is held is decided now.

        Args:
            truncated: The response was cut at the cap (finish ``length``).
                Read only in ``forced_open`` mode, where unclosed text is
                then thinking, not an answer.
        """
        held, self._held = self._held, ""
        if not held:
            return []
        if self._state == "thinking":
            return [("reasoning", held)]
        if self._state == "maybe_open":
            # Under a grammar, a cut answer that starts as JSON is an answer;
            # any other unclosed text under an untrusted patch is thinking
            # (the class docstring).
            json_led = self._grammar and held.lstrip()[:1] in ("{", "[")
            if truncated and self._forced_open and not json_led:
                return [("reasoning", held.strip())] if held.strip() else []
            return [("content", held)]
        if self._state == "after" and not held.strip():
            return []
        return [("content", held)]


def _partial_suffix(text: str, tag: str) -> int:
    """Length of the longest tail of ``text`` that is a proper prefix of ``tag``."""
    for size in range(min(len(tag) - 1, len(text)), 0, -1):
        if tag.startswith(text[-size:]):
            return size
    return 0


def strip_inline_think(
    content: str,
    reasoning: str,
    *,
    forced_open: bool = False,
    truncated: bool = False,
    grammar: bool = False,
    model: str = "",
) -> tuple[str, str]:
    """
    A whole (non-streamed) response through ``InlineThinkSplitter``, held:
    the whole text is here, so an orphan ``</think>`` costs nothing to find.

    ``forced_open``, ``truncated`` and ``grammar`` are the splitter's (an
    untrusted reasoning-off patch was sent; the answer was cut at the cap;
    the request carried a grammar). ``model`` names the model in the
    once-per-model warning when its patch was ignored.
    """
    splitter = InlineThinkSplitter(forced_open=forced_open, hold=True, grammar=grammar)
    kept: list[str] = []
    thought: list[str] = [reasoning] if reasoning else []
    for channel, text in splitter.push(content) + splitter.flush(truncated=truncated):
        (thought if channel == "reasoning" else kept).append(text)
    if splitter.patch_ignored:
        warn_patch_ignored(model)
    return "".join(kept), "".join(thought)


def extract_reasoning(payload: dict[str, Any]) -> str:
    """
    Pull reasoning text out of a message or delta object.

    LM Studio uses two different key names depending on how the model was
    converted: ``reasoning_content`` (DeepSeek convention, 0.3.9+, opt-in under
    Settings -> Developer) and ``reasoning`` (gpt-oss convention, 0.3.23+).
    Reading only one of them loses the channel entirely on half the models.
    """
    for key in ("reasoning_content", "reasoning"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
        # Some builds wrap it as {"reasoning": {"content": ...}}.
        if isinstance(value, dict):
            inner = value.get("content")
            if isinstance(inner, str) and inner:
                return inner
    return ""


def parse_tool_calls(raw: Any) -> list[ToolCall]:
    """
    Normalize OpenAI-format tool calls, tolerating what local models emit.

    Arguments arrive as a JSON string per the OpenAI spec, but smaller models
    frequently send an object instead, or a string that is not valid JSON at
    all. All three end up as a dict here, or the call is dropped.
    """
    if not isinstance(raw, list):
        return []

    calls: list[ToolCall] = []
    for index, entry in enumerate(raw):
        if not isinstance(entry, dict):
            continue
        function = entry.get("function") or {}
        name = function.get("name") or entry.get("name") or ""
        if not name:
            continue

        arguments = function.get("arguments", entry.get("arguments", {}))
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments) if arguments.strip() else {}
            except json.JSONDecodeError:
                logger.warning(
                    "[LMSClient] Unparseable tool arguments "
                    "(operation=parse_tool_calls, tool=%s)",
                    name,
                )
                arguments = {}
        if not isinstance(arguments, dict):
            arguments = {}

        calls.append(
            ToolCall(
                id=str(entry.get("id") or f"call_{index}"),
                name=str(name),
                arguments=arguments,
            )
        )
    return calls


class _ToolCallAccumulator:
    """
    Reassembles streamed tool calls.

    On a stream, ``delta.tool_calls[i].function.arguments`` arrives as
    FRAGMENTS -- ``{"loc`` then ``ation": "for`` then ``est"}`` -- keyed by
    ``index``, and the ``id``/``name`` usually appear only on the first
    fragment. Handing those fragments to ``parse_tool_calls`` one at a time
    yields nothing but JSONDecodeErrors, which is why streaming tool calls could
    not work here at all.
    """

    def __init__(self) -> None:
        self._slots: dict[int, dict[str, str]] = {}

    def push(self, raw: Any) -> None:
        if not isinstance(raw, list):
            return
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            index = int(entry.get("index", 0) or 0)
            slot = self._slots.setdefault(index, {"id": "", "name": "", "arguments": ""})
            if entry.get("id"):
                slot["id"] = str(entry["id"])
            function = entry.get("function") or {}
            if function.get("name"):
                slot["name"] = str(function["name"])
            fragment = function.get("arguments")
            if isinstance(fragment, str):
                slot["arguments"] += fragment

    def flush(self) -> list[ToolCall]:
        """Assemble the accumulated fragments into whole tool calls."""
        assembled = [
            {
                "id": slot["id"] or f"call_{index}",
                "function": {"name": slot["name"], "arguments": slot["arguments"]},
            }
            for index, slot in sorted(self._slots.items())
            if slot["name"]
        ]
        self._slots.clear()
        return parse_tool_calls(assembled)

    def __bool__(self) -> bool:
        return bool(self._slots)


def stop_if_turn_expired() -> None:
    """
    Stop a model call whose hosted turn's time is up (v0.20.0 T11 fix round
    1): its deadline passed, or the supervisor reclaimed its ticket
    (``engine.llm.gate.turn_expired``). Raised as a read timeout, so the call
    fails through each client's own ``httpx.HTTPError`` path and the caller's
    model-failure handling (the storyteller's fallback narration). Never
    raises outside an admitted hosted turn.

    Raises:
        httpx.ReadTimeout: the turn may make no more model calls.
    """
    reason = turn_expired()
    if reason:
        raise httpx.ReadTimeout(f"the turn's time is up ({reason})")


class cut_at_deadline:  # noqa: N801 -- used as a context manager, like contextlib's
    """
    A streamed model call's response, CUT at its hosted turn's deadline
    (v0.20.0 T12, T11's N2). ``stop_if_turn_expired`` is asked between a
    stream's chunks, so a stream that stalls without a byte would run on
    until its read timeout -- up to ``llm.timeout_seconds`` past the
    deadline. A timer set to the time left shuts the response's socket at
    the deadline, and the read fails through the client's own
    ``httpx.HTTPError`` path, the model-failure path. Outside an admitted
    hosted turn (``time_left()`` is None: local mode, always) it does nothing
    at all.

    BOUND TO ITS OWN CONNECTION (fix round 1, M1). The socket is taken when
    the stream starts, never when the timer fires, and the cut happens only
    under ``_lock`` while ``done`` is unset; ``finish`` -- called by each
    client the moment its read loop ends, the body read (fix round 2), and
    by ``__exit__`` in any case -- sets ``done`` under the same lock before
    the connection can go back to httpx's pool. So a cut either finishes before the stream ends or never
    happens: it can never reach a pooled connection another call has since
    taken. The socket is ``shutdown`` (which wakes a blocked read on POSIX);
    on Windows, where measured only a close wakes it, it is also closed --
    under the same lock, on the connection still this call's.
    """

    def __init__(self, response: httpx.Response) -> None:
        self.response = response
        self.timer: Optional[threading.Timer] = None
        self.cut = False
        self.done = False
        self._lock = threading.Lock()
        self._sock: Any = None

    @staticmethod
    def _socket_of(response: Any) -> Any:
        stream = getattr(response, "extensions", {}).get("network_stream")
        if stream is None:
            return None
        try:
            return stream.get_extra_info("socket")
        except Exception:  # noqa: BLE001 -- a stream without one cannot be cut this way
            return None

    def __enter__(self) -> "cut_at_deadline":
        left = time_left()
        if left is not None:
            self._sock = self._socket_of(self.response)
            self.timer = threading.Timer(max(0.0, left), self._cut)
            self.timer.daemon = True
            self.timer.start()
        return self

    def finish(self) -> None:
        """
        The stream's body is read (fix round 2, N3): give up the cut NOW,
        before anything the caller does after it. httpx returns an exhausted
        response's connection to its pool, where another call may take it
        while this generator is still suspended at a later yield.
        """
        with self._lock:
            self.done = True
        if self.timer is not None:
            self.timer.cancel()

    def __exit__(self, *_exc: Any) -> None:
        self.finish()

    def _cut(self) -> None:
        """Shut (and on Windows close) THIS call's socket, unless the stream has already ended."""
        with self._lock:
            if self.done:
                return
            self.cut = True
            sock = self._sock
            if sock is not None:
                import socket as socket_module

                try:
                    sock.shutdown(socket_module.SHUT_RDWR)
                except OSError:
                    pass
                if os.name == "nt":
                    try:
                        sock.close()
                    except OSError:
                        pass
        logger.warning(
            "[LMSClient] The turn's deadline passed mid-stream: the model call is cut "
            "(operation=chat_stream, reason=deadline)"
        )


def _raise_for_status(
    response: httpx.Response,
    operation: str,
    model: str,
    payload: dict[str, Any],
) -> None:
    """
    ``raise_for_status``, but the server's own words survive it.

    THE GAP THIS CLOSES. ``httpx.HTTPStatusError`` renders as "Client error
    '400 Bad Request' for url ..." and nothing else. LM Studio puts the ACTUAL
    reason in the body -- "Model 'local-model' not found",
    "'response_format.type' must be 'json_schema' or 'text'", a template error
    naming an unsupported role -- and every one of those was being thrown away
    one frame below the only place that could have used it. The planner catches
    the exception and treats the agent as silent (engine/agents/planner.py), so
    a 400 arrived at the player as a canned line and left no diagnosable trace
    anywhere.
    """
    if response.status_code < 400:
        return
    try:
        body = " ".join(response.text.split())[:400]
    except Exception:  # noqa: BLE001 -- an unreadable body must not mask the status
        body = "(body unreadable)"
    # The configured server's name: LM Studio's line is unchanged, and a
    # llama-server 400 no longer blames LM Studio (measured live, v0.19.0 T8).
    logger.error(
        "[LMSClient] %s refused the request (operation=%s, status=%s, "
        "model=%s, structured=%s, tools=%s): %s",
        get_provider().title,
        operation,
        response.status_code,
        model,
        bool(payload.get("response_format")),
        bool(payload.get("tools")),
        body or "(empty body)",
    )
    response.raise_for_status()


class LMSClient:
    """HTTP client for LM Studio chat completions with SSE streaming."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        *,
        timeout: Optional[float] = None,
        api_key: str = "",
    ) -> None:
        cfg = get_config()
        self.base_url = compat_base(base_url)
        # Was hardcoded at 180. See llm.timeout_seconds in
        # config/default.yaml for what that cost the authoring script.
        self.timeout = (
            float(cfg.get("llm.timeout_seconds", 300)) if timeout is None else timeout
        )
        self.api_key = api_key or cfg.get("llm.api_key", "") or ""
        headers: dict[str, str] = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        self._client = httpx.Client(timeout=timeout, headers=headers)

    def close(self) -> None:
        """Close HTTP client."""
        self._client.close()

    def is_available(self) -> bool:
        """
        Return True if the configured model server can serve a turn.

        The provider row's health probe (``Provider.health_probe``, spec §8):
        on LM Studio ``GET /api/v1/models``, read by its SHAPE -- v0.18's
        request, byte for byte (the golden's summarizer scenario); on vLLM
        ``/health`` then its model list, on llama-server ``/health``, on a
        generic server its model list. It used to be LM Studio's route for
        every provider, so the summarizer this gates read any other server as
        down and summarised deterministically forever.

        Before v0.18 it GET ``{base_url}/models`` -- ``/v1/models``, a route
        LM Studio does not own and logs an error for -- and called any 200
        healthy, which on that server is no test at all: unknown paths under
        ``/v1`` are answered 200 with an error body.
        """
        ok, detail = get_provider().health_probe(
            self.base_url, api_key=self.api_key, timeout=3.0
        )
        if not ok:
            logger.debug(
                "[LMSClient] Health check failed (operation=health): %s", detail
            )
        return ok

    @staticmethod
    def _apply_ttl(payload: dict[str, Any], ttl: int) -> None:
        """
        Ask LM Studio to evict this model after `ttl` idle seconds.

        With 47 models installed and JIT loading on, an un-evicted model holds
        VRAM the next profile needs. Sent only where the provider row's
        ``keep_alive`` is ``ttl`` (LM Studio): any other server would read an
        unknown key, or refuse it.
        """
        if ttl > 0 and get_provider().keep_alive.value == "ttl":
            payload["ttl"] = ttl

    @staticmethod
    def _shape(
        payload: dict[str, Any],
        model: str,
        max_tokens: int,
        reasoning_budget: int,
        reasoning: Optional[str],
    ) -> Optional[ReasoningPatch]:
        """
        The provider's reasoning-off patch merged into ``payload``, and the
        wire cap that goes with it (spec §5.1-5.2). Returns the patch sent.
        """
        patch = reasoning_patch(model, reasoning)
        payload["max_tokens"] = patched_cap(max_tokens, reasoning_budget, reasoning, patch)
        if patch is not None:
            payload.update(json.loads(json.dumps(patch.body)))
        return patch

    @staticmethod
    def _strips_inline_think() -> bool:
        """Whether this server may put thinking inside ``content`` (§4.5)."""
        return get_provider().inline_think.value == "strip"

    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        model: Optional[str] = None,
        temperature: float = 0.8,
        max_tokens: int = 1500,
        tools: Optional[list[dict[str, Any]]] = None,
        tool_choice: Optional[str] = None,
        response_format: Optional[dict[str, Any]] = None,
        ttl: int = 0,
        reasoning_budget: int = 0,
        reasoning: Optional[str] = None,
    ) -> LMSResponse:
        """
        Non-streaming chat completion.

        A real single request, not a drained stream. The old version threw away
        the generator's return value, so latency, finish_reason and token counts
        were lost on the only path actually used -- and tool calls could not be
        returned at all.

        Args:
            max_tokens: The CONTENT budget.
            reasoning_budget: Headroom for thinking, added here unless a
                TRUSTED reasoning-off patch went on the wire (``patched_cap``).
                On LM Studio it is always added: that route cannot stop a
                reasoning model from reasoning.
            reasoning: The mode this request asks for. ``off`` merges the
                provider's patch (``reasoning_patch``); None or any other mode
                sends nothing, as v0.18 did.
        """
        resolved = model or resolve_profile("big").model
        payload: dict[str, Any] = {
            "model": resolved,
            "messages": messages,
            "temperature": temperature,
            "stream": False,
        }
        patch = self._shape(payload, resolved, max_tokens, reasoning_budget, reasoning)
        cap = payload["max_tokens"]
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice or "auto"
        if response_format:
            payload["response_format"] = response_format
        self._apply_ttl(payload, ttl)

        t0 = time.perf_counter()
        try:
            response = self._client.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                timeout=call_timeout(self.timeout),
            )
            _raise_for_status(response, "chat", resolved, payload)
            data = response.json()
        except httpx.HTTPError as exc:
            logger.error(
                "[LMSClient] Chat failed (operation=chat, model=%s): %s", resolved, exc
            )
            raise

        choices = data.get("choices") or []
        first = choices[0] if choices else {}
        message = first.get("message") or {}
        usage = data.get("usage") or {}
        details = usage.get("completion_tokens_details") or {}

        content = message.get("content") or ""
        reasoning_text = extract_reasoning(message)
        if self._strips_inline_think() and isinstance(content, str):
            content, reasoning_text = strip_inline_think(
                content,
                reasoning_text,
                forced_open=patch is not None and not patch.trusted,
                truncated=str(first.get("finish_reason", "")) == "length",
                grammar=bool(response_format),
                model=resolved,
            )

        result = LMSResponse(
            content=content,
            reasoning_content=reasoning_text,
            reasoning_tokens=int(details.get("reasoning_tokens", 0) or 0),
            response_id=str(data.get("id", "")),
            model=str(data.get("model", resolved)),
            input_tokens=int(usage.get("prompt_tokens", 0) or 0),
            output_tokens=int(usage.get("completion_tokens", 0) or 0),
            latency_ms=(time.perf_counter() - t0) * 1000,
            tool_calls=parse_tool_calls(message.get("tool_calls")),
            finish_reason=str(first.get("finish_reason", "")),
            transport="openai",
        )
        _log_outcome("chat", result, max_tokens, reasoning_budget, cap)
        return result

    def chat_stream(
        self,
        messages: list[dict[str, Any]],
        *,
        model: Optional[str] = None,
        temperature: float = 0.8,
        max_tokens: int = 1500,
        on_event: Optional[Callable[[LMSStreamEvent], None]] = None,
        on_delta: Optional[Callable[[str], None]] = None,
        on_reasoning: Optional[Callable[[str], None]] = None,
        response_format: Optional[dict[str, Any]] = None,
        tools: Optional[list[dict[str, Any]]] = None,
        tool_choice: Optional[str] = None,
        ttl: int = 0,
        reasoning_budget: int = 0,
        reasoning: Optional[str] = None,
    ) -> Generator[str, None, LMSResponse]:
        """
        Stream chat completion tokens.

        Yields CONTENT deltas only. Reasoning deltas go to ``on_reasoning`` and
        out as ``reasoning.*`` events; they are deliberately not yielded,
        because everything downstream of the yield (the tag scanner, the
        narration JSON decoder) would otherwise act on the model's private
        musings -- a model writing "maybe [IMAGE:forest]" while thinking must
        not trigger a real image generation.

        Args:
            on_event: Receives typed events, translated into the native
                vocabulary so StreamProcessor sees one shape from both
                transports.
            on_delta: Receives message content deltas.
            on_reasoning: Receives reasoning deltas.
            tools: Function definitions. Streamed tool-call argument fragments
                are accumulated by index and flushed on
                ``finish_reason == "tool_calls"``.
            max_tokens: The CONTENT budget.
            reasoning_budget: Headroom for thinking; see ``chat``.
            reasoning: The mode this request asks for; see ``chat``.

        On a row whose ``inline_think`` is ``strip``, a leading
        ``<think>…</think>`` in the content channel is moved to the reasoning
        channel here, before anything is yielded (``InlineThinkSplitter``).
        """
        resolved = model or resolve_profile("big").model
        payload: dict[str, Any] = {
            "model": resolved,
            "messages": messages,
            "temperature": temperature,
            "stream": True,
            # Real token counts instead of the zeros this used to report.
            "stream_options": {"include_usage": True},
        }
        patch = self._shape(payload, resolved, max_tokens, reasoning_budget, reasoning)
        cap = payload["max_tokens"]
        # An untrusted patch may be ignored, and then the thinking arrives in
        # the content with no opening tag: held back until decided (§4.5) --
        # but only with no grammar on the request, since a grammar binds from
        # the first token and holding would blank the stream (fix round 1).
        forced = patch is not None and not patch.trusted
        splitter = (
            InlineThinkSplitter(
                forced_open=forced,
                hold=forced and not response_format,
                grammar=bool(response_format),
            )
            if self._strips_inline_think()
            else None
        )
        if response_format:
            payload["response_format"] = response_format
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice or "auto"
        self._apply_ttl(payload, ttl)

        t0 = time.perf_counter()
        if on_event:
            on_event(LMSStreamEvent(event_type="chat.start", model_instance_id=resolved))

        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        accumulator = _ToolCallAccumulator()
        finish_reason = ""
        usage: dict[str, Any] = {}
        started_message = False
        started_reasoning = False

        def _reason(text: str) -> None:
            nonlocal started_reasoning
            if not started_reasoning:
                started_reasoning = True
                if on_event:
                    on_event(LMSStreamEvent(event_type="reasoning.start"))
            reasoning_parts.append(text)
            if on_reasoning:
                on_reasoning(text)
            if on_event:
                on_event(LMSStreamEvent(event_type="reasoning.delta", content=text))

        def _content(text: str) -> str:
            nonlocal started_message
            if started_reasoning and not started_message and on_event:
                on_event(LMSStreamEvent(event_type="reasoning.end"))
            if not started_message:
                started_message = True
                if on_event:
                    on_event(LMSStreamEvent(event_type="message.start"))
            content_parts.append(text)
            if on_delta:
                on_delta(text)
            if on_event:
                on_event(LMSStreamEvent(event_type="message.delta", content=text))
            return text

        try:
            with self._client.stream(
                "POST",
                f"{self.base_url}/chat/completions",
                json=payload,
                timeout=call_timeout(self.timeout),
            ) as response, cut_at_deadline(response) as deadline_cut:
                if response.status_code >= 400:
                    response.read()
                _raise_for_status(response, "chat_stream", resolved, payload)
                for raw_line in response.iter_lines():
                    stop_if_turn_expired()
                    line = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else raw_line
                    if not line or not line.startswith("data:"):
                        continue
                    data_str = line[5:].strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        data = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue

                    if data.get("usage"):
                        usage = data["usage"]
                    # Many OpenAI-compatible servers, LM Studio included, send a
                    # final usage-only chunk with "choices": []. Indexing [0] on
                    # that raises IndexError, which is not an httpx.HTTPError and
                    # so escapes the handler below mid-turn.
                    choices = data.get("choices") or []
                    first = choices[0] if choices else {}
                    if first.get("finish_reason"):
                        finish_reason = str(first["finish_reason"])
                    delta_obj = first.get("delta") or {}

                    if delta_obj.get("tool_calls"):
                        accumulator.push(delta_obj["tool_calls"])

                    reasoning_delta = extract_reasoning(delta_obj)
                    if reasoning_delta:
                        _reason(reasoning_delta)

                    delta = delta_obj.get("content", "") or ""
                    pieces = splitter.push(delta) if splitter is not None else (
                        [("content", delta)] if delta else []
                    )
                    for channel, text in pieces:
                        if channel == "reasoning":
                            _reason(text)
                        else:
                            yield _content(text)
                # The body is read: the connection may go back to httpx's
                # pool now, so the cut gives it up before any later yield.
                deadline_cut.finish()
                if splitter is not None:
                    for channel, text in splitter.flush(truncated=finish_reason == "length"):
                        if channel == "reasoning":
                            _reason(text)
                        else:
                            yield _content(text)
                    if splitter.patch_ignored:
                        warn_patch_ignored(resolved)
        except httpx.HTTPError as exc:
            logger.error("[LMSClient] Stream failed (operation=chat_stream): %s", exc)
            if on_event:
                on_event(LMSStreamEvent(event_type="error", error=str(exc)))
            raise

        full = "".join(content_parts)
        latency = (time.perf_counter() - t0) * 1000
        if started_message and on_event:
            on_event(LMSStreamEvent(event_type="message.end"))

        # Flush on tool_calls, and also unconditionally: a model can stop with
        # finish_reason "stop" and still have emitted a complete tool call.
        tool_calls = accumulator.flush()

        details = usage.get("completion_tokens_details") or {}
        # finish_reason travels in stats as well as on the response: a
        # StreamProcessor built from events alone had no other way to learn it,
        # so ProcessedResponse.finish_reason was permanently "" and a truncated
        # generation was indistinguishable from a finished one.
        stats: dict[str, Any] = {"latency_ms": latency, "finish_reason": finish_reason}
        if usage:
            stats.update(
                {
                    "input_tokens": int(usage.get("prompt_tokens", 0) or 0),
                    "total_output_tokens": int(usage.get("completion_tokens", 0) or 0),
                    "reasoning_output_tokens": int(details.get("reasoning_tokens", 0) or 0),
                }
            )
        if on_event:
            on_event(
                LMSStreamEvent(
                    event_type="chat.end",
                    response_id=f"resp_{uuid.uuid4().hex[:12]}",
                    stats=stats,
                )
            )

        result = LMSResponse(
            content=full,
            reasoning_content="".join(reasoning_parts),
            reasoning_tokens=int(details.get("reasoning_tokens", 0) or 0),
            model=resolved,
            input_tokens=int(usage.get("prompt_tokens", 0) or 0),
            output_tokens=int(usage.get("completion_tokens", 0) or 0),
            latency_ms=latency,
            stats=stats,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            transport="openai",
        )
        _log_outcome("chat_stream", result, max_tokens, reasoning_budget, cap)
        return result

    def infer_stream(
        self,
        messages: list[dict[str, Any]],
        *,
        profile: str = "big",
        on_event: Optional[Callable[[LMSStreamEvent], None]] = None,
        on_reasoning: Optional[Callable[[str], None]] = None,
    ) -> Generator[str, None, LMSResponse]:
        """Profile-aware streaming wrapper."""
        mp = resolve_profile(profile)
        return self.chat_stream(
            messages,
            model=mp.model,
            temperature=mp.temperature,
            max_tokens=mp.max_tokens,
            reasoning_budget=mp.reasoning_budget,
            on_event=on_event,
            on_reasoning=on_reasoning,
            ttl=mp.ttl,
        )

    def infer_processed(
        self,
        messages: list[dict[str, Any]],
        *,
        profile: str = "big",
        on_delta: Optional[Callable[[str], None]] = None,
        on_reasoning: Optional[Callable[[str], None]] = None,
    ):
        """
        Stream + tag extraction via StreamProcessor.

        Returns:
            ProcessedResponse from engine.agents.stream_processor
        """
        from engine.agents.stream_processor import StreamProcessor

        proc = StreamProcessor(on_delta=on_delta, on_reasoning=on_reasoning)
        gen = self.infer_stream(messages, profile=profile, on_event=proc.on_event)
        for _chunk in gen:
            pass
        return proc.result()


def _log_outcome(
    operation: str,
    result: LMSResponse,
    content_budget: int,
    reasoning_budget: int,
    cap: Optional[int] = None,
) -> None:
    """
    Report an empty content channel as the specific failure it is.

    Both budgets are named, and ``short=`` says which one ran out, because the
    two want opposite fixes: more ``reasoning_budget`` versus more
    ``max_tokens``. A single ``max_tokens=3000`` in the log could never
    distinguish "it thought too much" from "it had more to say". ``cap`` is
    the number that actually went on the wire.
    """
    if cap is None:
        cap = compat_cap(content_budget, reasoning_budget)
    short = "reasoning_budget" if result.reasoning_tokens >= max(1, reasoning_budget) else "max_tokens"
    if result.starved_by_reasoning:
        logger.error(
            "[LMSClient] REASONING STARVED THE OUTPUT — content is empty because "
            "the model spent the entire token budget thinking "
            "(operation=%s, model=%s, content_budget=%s, reasoning_budget=%s, "
            "wire_cap=%s, output_tokens=%s, reasoning_tokens=%s, "
            "reasoning_chars=%s, short=%s). This transport cannot disable "
            "reasoning; route via engine.llm.backend to use /api/v1/chat "
            "with reasoning='off', or raise reasoning_budget.",
            operation,
            result.model,
            content_budget,
            reasoning_budget,
            cap,
            result.output_tokens,
            result.reasoning_tokens,
            len(result.reasoning_content),
            short,
        )
    elif result.truncated:
        logger.warning(
            "[LMSClient] Response truncated at the wire cap "
            "(operation=%s, model=%s, content_budget=%s, reasoning_budget=%s, "
            "wire_cap=%s, chars=%s, reasoning_tokens=%s, short=%s)",
            operation,
            result.model,
            content_budget,
            reasoning_budget,
            cap,
            len(result.content),
            result.reasoning_tokens,
            short,
        )


def get_lms_client() -> LMSClient:
    """Singleton LMS client (double-checked: no lock once built)."""
    global _client_instance
    client = _client_instance
    if client is not None:
        return client
    with _client_lock:
        if _client_instance is None:
            _client_instance = LMSClient()
        return _client_instance


def reset_lms_client() -> None:
    """Reset singleton (tests), and the inline-``<think>`` count with it."""
    global _client_instance, _inline_think_seen
    _inline_think_seen = 0
    _patch_ignored_warned.clear()
    with _client_lock:
        old, _client_instance = _client_instance, None
    if old is not None:
        old.close()


def release_lms_client() -> None:
    """
    Drop the singleton WITHOUT closing it: a config reload (engine/games/caches.py).

    The next ``get_lms_client()`` builds a client from the new config's base
    URL and key. The old one may still be carrying a turn's stream -- a
    Settings save runs on a Flask thread, mid-narration -- so it is not closed
    here; it closes its connection pool once nothing holds it any more, which
    is when the last call using it has returned.
    """
    global _client_instance
    with _client_lock:
        old, _client_instance = _client_instance, None
    if old is not None:
        # Bound to the httpx client, not to `old`, so it never keeps `old` alive.
        weakref.finalize(old, old._client.close)
