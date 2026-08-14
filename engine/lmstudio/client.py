"""
LMSClient — LM Studio OpenAI-compatible SSE client.

Uses ``POST {base_url}/chat/completions``. This is the fallback transport: it is
the only one that can do tool calling and ``response_format`` structured output,
but it CANNOT control reasoning (see native.py for the measurements). Prefer
``engine.lmstudio.backend`` which routes between this and NativeClient.

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
import time
import uuid
from typing import Any, Callable, Generator, Optional

import httpx

from engine.config import get_config
from engine.lmstudio.events import LMSResponse, LMSStreamEvent, ToolCall
from engine.lmstudio.profiles import ModelProfile, resolve_profile, wire_cap
from engine.lmstudio.routes import compat_base, models_url

logger = logging.getLogger(__name__)

_client_instance: Optional["LMSClient"] = None


def compat_cap(max_tokens: int, reasoning_budget: int) -> int:
    """
    The wire ceiling for this transport, which always budgets for reasoning.

    Unlike the native route, ``/v1/chat/completions`` has no working way to
    turn reasoning off -- every knob is ignored (see native.py for the
    measurements). So a request routed here will think whether or not it was
    asked to, and the reasoning budget is granted UNCONDITIONALLY. Honouring a
    ``reasoning: off`` that the server will ignore is how a schema-constrained
    call ends up with an empty content channel: structured output constrains
    the content channel only, and gives no protection at all against the
    deliberation that precedes it.
    """
    return wire_cap(max_tokens, reasoning_budget, "on")


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
    logger.error(
        "[LMSClient] LM Studio refused the request (operation=%s, status=%s, "
        "model=%s, structured=%s, tools=%s): %s",
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
        # Was hardcoded at 180. See lmstudio.timeout_seconds in
        # config/default.yaml for what that cost the authoring script.
        self.timeout = (
            float(cfg.get("lmstudio.timeout_seconds", 300)) if timeout is None else timeout
        )
        self.api_key = api_key or cfg.get("lmstudio.api_key", "") or ""
        headers: dict[str, str] = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        self._client = httpx.Client(timeout=timeout, headers=headers)

    def close(self) -> None:
        """Close HTTP client."""
        self._client.close()

    def is_available(self) -> bool:
        """
        Return True if this is an LM Studio that can serve a turn.

        Asks ``GET /api/v1/models`` and reads the SHAPE of the answer. It used
        to GET ``{base_url}/models`` -- i.e. ``/v1/models``, a route LM Studio
        does not own and logs an error for -- and call any 200 healthy, which on
        this server is no test at all: unknown paths under ``/v1`` are answered
        200 with an error body.
        """
        from engine.lmstudio.registry import probe_models

        ok, detail = probe_models(
            models_url(self.base_url), api_key=self.api_key, timeout=3.0
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
        VRAM the next profile needs.
        """
        if ttl > 0:
            payload["ttl"] = ttl

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
    ) -> LMSResponse:
        """
        Non-streaming chat completion.

        A real single request, not a drained stream. The old version threw away
        the generator's return value, so latency, finish_reason and token counts
        were lost on the only path actually used -- and tool calls could not be
        returned at all.

        Args:
            max_tokens: The CONTENT budget.
            reasoning_budget: Headroom for thinking, always added here -- this
                transport cannot stop a reasoning model from reasoning.
        """
        resolved = model or resolve_profile("big").model
        cap = compat_cap(max_tokens, reasoning_budget)
        payload: dict[str, Any] = {
            "model": resolved,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": cap,
            "stream": False,
        }
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
                timeout=self.timeout,
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

        result = LMSResponse(
            content=message.get("content") or "",
            reasoning_content=extract_reasoning(message),
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
        _log_outcome("chat", result, max_tokens, reasoning_budget)
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
            reasoning_budget: Headroom for thinking, always added here -- this
                transport cannot stop a reasoning model from reasoning.
        """
        resolved = model or resolve_profile("big").model
        cap = compat_cap(max_tokens, reasoning_budget)
        payload: dict[str, Any] = {
            "model": resolved,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": cap,
            "stream": True,
            # Real token counts instead of the zeros this used to report.
            "stream_options": {"include_usage": True},
        }
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

        try:
            with self._client.stream(
                "POST",
                f"{self.base_url}/chat/completions",
                json=payload,
                timeout=self.timeout,
            ) as response:
                if response.status_code >= 400:
                    response.read()
                _raise_for_status(response, "chat_stream", resolved, payload)
                for raw_line in response.iter_lines():
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
                        if not started_reasoning:
                            started_reasoning = True
                            if on_event:
                                on_event(LMSStreamEvent(event_type="reasoning.start"))
                        reasoning_parts.append(reasoning_delta)
                        if on_reasoning:
                            on_reasoning(reasoning_delta)
                        if on_event:
                            on_event(
                                LMSStreamEvent(
                                    event_type="reasoning.delta",
                                    content=reasoning_delta,
                                )
                            )

                    delta = delta_obj.get("content", "") or ""
                    if delta:
                        if started_reasoning and not started_message and on_event:
                            on_event(LMSStreamEvent(event_type="reasoning.end"))
                        if not started_message:
                            started_message = True
                            if on_event:
                                on_event(LMSStreamEvent(event_type="message.start"))
                        content_parts.append(delta)
                        if on_delta:
                            on_delta(delta)
                        if on_event:
                            on_event(
                                LMSStreamEvent(
                                    event_type="message.delta",
                                    content=delta,
                                )
                            )
                        yield delta
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
        _log_outcome("chat_stream", result, max_tokens, reasoning_budget)
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
    operation: str, result: LMSResponse, content_budget: int, reasoning_budget: int
) -> None:
    """
    Report an empty content channel as the specific failure it is.

    Both budgets are named, and ``short=`` says which one ran out, because the
    two want opposite fixes: more ``reasoning_budget`` versus more
    ``max_tokens``. A single ``max_tokens=3000`` in the log could never
    distinguish "it thought too much" from "it had more to say".
    """
    cap = compat_cap(content_budget, reasoning_budget)
    short = "reasoning_budget" if result.reasoning_tokens >= max(1, reasoning_budget) else "max_tokens"
    if result.starved_by_reasoning:
        logger.error(
            "[LMSClient] REASONING STARVED THE OUTPUT — content is empty because "
            "the model spent the entire token budget thinking "
            "(operation=%s, model=%s, content_budget=%s, reasoning_budget=%s, "
            "wire_cap=%s, output_tokens=%s, reasoning_tokens=%s, "
            "reasoning_chars=%s, short=%s). This transport cannot disable "
            "reasoning; route via engine.lmstudio.backend to use /api/v1/chat "
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
    """Singleton LMS client."""
    global _client_instance
    if _client_instance is None:
        _client_instance = LMSClient()
    return _client_instance


def reset_lms_client() -> None:
    """Reset singleton (tests)."""
    global _client_instance
    if _client_instance is not None:
        _client_instance.close()
    _client_instance = None
