"""
Native LM Studio client — ``POST /api/v1/chat`` with typed SSE.

WHY THIS EXISTS
---------------
The OpenAI-compatible endpoint cannot control reasoning. Measured on this
machine against ``nvidia/nemotron-3-nano-4b`` (Q4_K_M, nemotron_h), asking for
a three-word greeting on ``POST /v1/chat/completions``::

    baseline                                -> 55  reasoning tokens
    reasoning: "off"                        -> 88  reasoning tokens
    chat_template_kwargs.enable_thinking=0  -> 143 reasoning tokens
    reasoning_effort: "low"                 -> 113 reasoning tokens

Every knob is ignored (``reasoning_effort`` is lmstudio-bug-tracker #988; the
other two are simply not read on that route). The same prompt on
``POST /api/v1/chat`` with ``reasoning: "off"`` returns
``reasoning_output_tokens: 0``. That is the entire reason this module exists:
the native endpoint is the ONLY way to stop a reasoning model from spending the
whole token budget thinking, which is the confirmed cause of the empty-narration
bug (400 tokens requested, 400 spent on reasoning, ``content: ""``).

WHAT THE NATIVE ENDPOINT DOES NOT DO
------------------------------------
Verified by probing the live server -- all four are rejected with
``unrecognized_keys``:

* ``tools``            -- no tool calling
* ``response_format``  -- no structured output / json_schema
* ``ttl``              -- no idle-eviction hint
* per-message ``role`` -- ``input`` is a flat array of ``{type, content}``
  parts, with a separate ``system_prompt``; there is no assistant turn slot

So this is not a drop-in replacement. ``backend.py`` routes each request to
whichever transport can actually serve it.

REQUEST SHAPE (verified)::

    {"model": ..., "system_prompt": ..., "reasoning": "off"|"low"|"medium"|"high"|"on",
     "input": [{"type": "text", "content": "..."}],
     "max_output_tokens": int, "context_length": int, "temperature": float,
     "stream": bool}

RESPONSE SHAPE (verified)::

    {"model_instance_id": ..., "response_id": ...,
     "output": [{"type": "reasoning", "content": ...},
                {"type": "message",   "content": ...}],
     "stats": {"input_tokens", "total_output_tokens", "reasoning_output_tokens",
               "tokens_per_second", "time_to_first_token_seconds"}}

Version: v0.1.0 [2026-08-08]
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Callable, Generator, Optional

import httpx

from engine.config import get_config
from engine.lmstudio.events import NATIVE_EVENT_TYPES, LMSResponse, LMSStreamEvent
from engine.lmstudio.profiles import wire_cap
from engine.lmstudio.routes import CHAT_PATH, rest_root

logger = logging.getLogger(__name__)

# Native `reasoning` values, in the order the docs list them.
REASONING_LEVELS: frozenset[str] = frozenset({"off", "low", "medium", "high", "on"})

# Roles the native `input` array cannot express. Rendered as labelled text so a
# multi-turn history is not silently flattened into an undifferentiated blob.
_ROLE_LABELS = {"assistant": "ASSISTANT", "tool": "TOOL RESULT", "user": ""}


def messages_to_native(
    messages: list[dict[str, Any]],
) -> tuple[str, list[dict[str, str]]]:
    """
    Translate an OpenAI message array into ``(system_prompt, input_parts)``.

    ``/api/v1/chat`` has no per-message role: ``input`` is a flat array of
    ``{"type": "text", "content": ...}`` parts. System blocks are hoisted into
    ``system_prompt`` (joined, order preserved -- the Storyteller builds several
    of them and the persona is the first). Assistant and tool turns keep a text
    label so the model can still tell who said what.

    Args:
        messages: Standard ``[{"role": ..., "content": ...}]`` array.

    Returns:
        The joined system prompt and the native ``input`` parts.
    """
    system_parts: list[str] = []
    input_parts: list[dict[str, str]] = []

    for message in messages:
        role = str(message.get("role", "user"))
        content = message.get("content")
        if not isinstance(content, str):
            # Multimodal content arrays: keep only the text, images are not
            # wired through this path yet.
            if isinstance(content, list):
                content = "".join(
                    str(p.get("text") or p.get("content") or "")
                    for p in content
                    if isinstance(p, dict)
                )
            else:
                content = "" if content is None else str(content)
        if not content.strip():
            continue

        if role == "system":
            system_parts.append(content)
            continue

        label = _ROLE_LABELS.get(role, role.upper())
        text = f"[{label}]\n{content}" if label else content
        input_parts.append({"type": "text", "content": text})

    return "\n\n".join(system_parts), input_parts


class NativeClient:
    """LM Studio native chat client with typed SSE events."""

    def __init__(
        self,
        *,
        base_url: Optional[str] = None,
        timeout: Optional[float] = None,
        api_key: str = "",
    ) -> None:
        cfg = get_config()
        # /api/v1 is a sibling of /v1, not a child. The derivation lives in
        # routes.py so the chat route and the model list cannot drift apart.
        self.root = rest_root(base_url)
        self.timeout = (
            float(cfg.get("lmstudio.timeout_seconds", 300)) if timeout is None else timeout
        )
        self.api_key = api_key or cfg.get("lmstudio.api_key", "") or ""
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        self._client = httpx.Client(timeout=timeout, headers=headers)

    def close(self) -> None:
        self._client.close()

    def is_available(self) -> bool:
        """
        Probe whether this server speaks ``/api/v1/chat``.

        Sends a deliberately invalid body: a server that implements the route
        answers 400 with ``"'input' is required"``, while a server that does not
        answers 404. Both are cheap and neither loads a model.
        """
        try:
            response = self._client.post(
                f"{self.root}{CHAT_PATH}",
                json={},
                timeout=5.0,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("[native] Probe failed (operation=is_available): %s", exc)
            return False
        # 400 = route exists and validated our empty body. 404/405 = no route.
        available = response.status_code in (200, 400, 422)
        logger.info(
            "[native] Native API probe (operation=is_available, url=%s, "
            "status=%s, available=%s)",
            self.root,
            response.status_code,
            available,
        )
        return available

    def _payload(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str,
        temperature: float,
        max_tokens: int,
        reasoning: str,
        context_length: int,
        stream: bool,
        reasoning_budget: int = 0,
    ) -> dict[str, Any]:
        """
        Build the request body.

        ``max_output_tokens`` is the one ceiling this endpoint offers and it
        covers reasoning AND content, so the two budgets are summed here:
        ``max_tokens`` (the answer) plus ``reasoning_budget`` (the thinking),
        the latter dropped when reasoning is off because none will be spent.
        """
        system_prompt, input_parts = messages_to_native(messages)
        if not input_parts:
            # The endpoint rejects an empty `input`. A system-only prompt is a
            # legitimate thing to send, so give it something to answer.
            input_parts = [{"type": "text", "content": "Continue."}]

        payload: dict[str, Any] = {
            "model": model,
            "input": input_parts,
            "temperature": temperature,
            "max_output_tokens": wire_cap(max_tokens, reasoning_budget, reasoning),
            "stream": stream,
        }
        if system_prompt:
            payload["system_prompt"] = system_prompt
        if reasoning in REASONING_LEVELS:
            payload["reasoning"] = reasoning
        if context_length > 0:
            payload["context_length"] = context_length
        return payload

    @staticmethod
    def _from_result(
        result: dict[str, Any],
        *,
        model: str,
        max_tokens: int,
        latency_ms: float,
    ) -> LMSResponse:
        """Build an LMSResponse from a native result object."""
        message_parts: list[str] = []
        reasoning_parts: list[str] = []
        for item in result.get("output") or []:
            if not isinstance(item, dict):
                continue
            content = str(item.get("content") or "")
            if item.get("type") == "reasoning":
                reasoning_parts.append(content)
            elif item.get("type") == "message":
                message_parts.append(content)

        stats = result.get("stats") or {}
        output_tokens = int(stats.get("total_output_tokens", 0) or 0)
        reasoning_tokens = int(stats.get("reasoning_output_tokens", 0) or 0)

        # The native endpoint reports no finish_reason. Hitting the ceiling is
        # inferred from the token count, which is exact: a run capped at 60
        # returns total_output_tokens == 60. Compared against the WIRE cap --
        # content plus reasoning -- because that is the number the server was
        # given. Without this, `truncated` and `starved_by_reasoning` would
        # never fire on the native path and the empty-content bug would go back
        # to being invisible.
        finish_reason = ""
        if max_tokens > 0 and output_tokens >= max_tokens:
            finish_reason = "length"

        return LMSResponse(
            content="".join(message_parts),
            reasoning_content="".join(reasoning_parts),
            reasoning_tokens=reasoning_tokens,
            response_id=str(result.get("response_id", "")),
            model=str(result.get("model_instance_id") or model),
            input_tokens=int(stats.get("input_tokens", 0) or 0),
            output_tokens=output_tokens,
            latency_ms=latency_ms,
            stats=dict(stats),
            finish_reason=finish_reason,
            transport="native",
        )

    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str,
        temperature: float = 0.8,
        max_tokens: int = 1500,
        reasoning: str = "on",
        context_length: int = 0,
        reasoning_budget: int = 0,
    ) -> LMSResponse:
        """
        Non-streaming native completion.

        Args:
            max_tokens: The CONTENT budget -- what the answer may spend.
            reasoning_budget: Headroom for thinking, added on top when
                reasoning is on. The wire cap is their sum.
        """
        payload = self._payload(
            messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            reasoning=reasoning,
            context_length=context_length,
            stream=False,
            reasoning_budget=reasoning_budget,
        )
        cap = int(payload["max_output_tokens"])
        t0 = time.perf_counter()
        response = self._client.post(
            f"{self.root}{CHAT_PATH}", json=payload, timeout=self.timeout
        )
        if response.status_code >= 400:
            # The status alone says nothing. `unrecognized_keys` naming the key
            # it rejected, or a model id it has never heard of, is in the body.
            logger.error(
                "[native] LM Studio refused the request (operation=chat, "
                "status=%s, model=%s): %s",
                response.status_code,
                model,
                " ".join(response.text.split())[:400] or "(empty body)",
            )
        response.raise_for_status()
        result = self._from_result(
            response.json(),
            model=model,
            max_tokens=cap,
            latency_ms=(time.perf_counter() - t0) * 1000,
        )
        _log_outcome("chat", result, max_tokens, reasoning_budget, reasoning)
        return result

    def chat_stream(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str,
        temperature: float = 0.8,
        max_tokens: int = 1500,
        reasoning: str = "on",
        context_length: int = 0,
        reasoning_budget: int = 0,
        on_event: Optional[Callable[[LMSStreamEvent], None]] = None,
        on_delta: Optional[Callable[[str], None]] = None,
        on_reasoning: Optional[Callable[[str], None]] = None,
    ) -> Generator[str, None, LMSResponse]:
        """
        Stream a native completion.

        Yields CONTENT deltas only. Reasoning deltas go to ``on_reasoning`` and
        to ``on_event`` as ``reasoning.*`` events, and are never yielded --
        anything downstream of the yield (the tag scanner, the narration JSON
        decoder) must not see a model musing "maybe [IMAGE:forest]" and fire a
        real image generation off it.

        Args:
            on_event: Receives every typed SSE event, reasoning included.
            on_delta: Receives message content deltas.
            on_reasoning: Receives reasoning deltas, for a live "the world is
                deciding..." channel in the UI.

        Returns:
            LMSResponse via StopIteration.value, with both channels populated.
        """
        payload = self._payload(
            messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            reasoning=reasoning,
            context_length=context_length,
            stream=True,
            reasoning_budget=reasoning_budget,
        )
        cap = int(payload["max_output_tokens"])

        t0 = time.perf_counter()
        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        final_result: dict[str, Any] = {}

        try:
            with self._client.stream(
                "POST", f"{self.root}{CHAT_PATH}", json=payload, timeout=self.timeout
            ) as response:
                response.raise_for_status()
                for etype, data in _iter_sse(response):
                    if etype not in NATIVE_EVENT_TYPES:
                        logger.debug(
                            "[native] Unknown event (operation=chat_stream, type=%s)",
                            etype,
                        )
                    delta = str(data.get("content") or "")

                    if etype == "reasoning.delta" and delta:
                        reasoning_parts.append(delta)
                        if on_reasoning:
                            on_reasoning(delta)
                    elif etype == "message.delta" and delta:
                        content_parts.append(delta)
                        if on_delta:
                            on_delta(delta)
                    elif etype == "chat.end":
                        final_result = data.get("result") or {}
                    elif etype == "error":
                        message = str(data.get("message") or data.get("error") or data)
                        logger.error(
                            "[native] Stream error (operation=chat_stream, model=%s): %s",
                            model,
                            message,
                        )

                    if on_event:
                        on_event(_to_event(etype, data, model))

                    # Yield AFTER the callbacks so a consumer that stops
                    # iterating still saw the event.
                    if etype == "message.delta" and delta:
                        yield delta
        except httpx.HTTPError as exc:
            logger.error(
                "[native] Stream failed (operation=chat_stream, model=%s): %s",
                model,
                exc,
            )
            if on_event:
                on_event(LMSStreamEvent(event_type="error", error=str(exc)))
            raise

        latency = (time.perf_counter() - t0) * 1000
        if final_result:
            result = self._from_result(
                final_result, model=model, max_tokens=cap, latency_ms=latency
            )
            # chat.end is authoritative for stats, but the streamed deltas are
            # authoritative for text: a consumer already saw exactly these.
            result.content = "".join(content_parts) or result.content
            result.reasoning_content = "".join(reasoning_parts) or result.reasoning_content
        else:
            result = LMSResponse(
                content="".join(content_parts),
                reasoning_content="".join(reasoning_parts),
                model=model,
                latency_ms=latency,
                transport="native",
            )
        _log_outcome("chat_stream", result, max_tokens, reasoning_budget, reasoning)
        return result


def _iter_sse(response: httpx.Response) -> Generator[tuple[str, dict[str, Any]], None, None]:
    """
    Parse LM Studio's ``event:``/``data:`` SSE frames.

    The native stream sends the type twice -- once in the ``event:`` line and
    once as ``data.type`` -- so the data field is used as the authority and the
    header line is the fallback.
    """
    current = ""
    for raw_line in response.iter_lines():
        line = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else raw_line
        if not line:
            continue
        if line.startswith("event:"):
            current = line[6:].strip()
        elif line.startswith("data:"):
            body = line[5:].strip()
            if not body or body == "[DONE]":
                continue
            try:
                data = json.loads(body)
            except json.JSONDecodeError:
                logger.debug("[native] Undecodable SSE data (operation=_iter_sse)")
                continue
            if not isinstance(data, dict):
                continue
            yield str(data.get("type") or current), data


def _to_event(etype: str, data: dict[str, Any], model: str) -> LMSStreamEvent:
    """Map one native SSE frame onto LMSStreamEvent."""
    result = data.get("result") or {}
    stats = result.get("stats") if isinstance(result, dict) else None
    arguments = data.get("arguments")
    return LMSStreamEvent(
        event_type=etype,
        content=str(data.get("content") or ""),
        tool_name=str(data.get("tool") or data.get("name") or ""),
        tool_arguments=arguments if isinstance(arguments, dict) else {},
        tool_output=str(data.get("output") or ""),
        tool_call_id=str(data.get("tool_call_id") or data.get("id") or ""),
        response_id=str(
            (result.get("response_id") if isinstance(result, dict) else "")
            or data.get("response_id")
            or ""
        ),
        model_instance_id=str(data.get("model_instance_id") or model),
        stats=dict(stats) if isinstance(stats, dict) else {},
        error=str(data.get("message") or data.get("reason") or data.get("error") or ""),
        load_time_seconds=float(data.get("load_time_seconds") or 0.0),
        progress=float(data.get("progress") or 0.0),
    )


def _log_outcome(
    operation: str,
    result: LMSResponse,
    content_budget: int,
    reasoning_budget: int,
    reasoning: str,
) -> None:
    """
    Say loudly when reasoning ate the whole budget, and WHICH budget was short.

    The production symptom was a frozen screen and a log that said nothing. An
    empty content channel behind a full reasoning channel is a specific,
    diagnosable, retryable failure and must never be reported as "the model
    wrote nothing".

    Both budgets are named because they now fail for different reasons and take
    different fixes: a reasoning overrun wants a bigger ``reasoning_budget`` (or
    ``reasoning: off``), a content overrun wants a bigger ``max_tokens``. One
    number could never tell those two apart.
    """
    cap = wire_cap(content_budget, reasoning_budget, reasoning)
    over_reasoning = result.reasoning_tokens >= max(1, reasoning_budget)
    if result.starved_by_reasoning:
        logger.error(
            "[native] REASONING STARVED THE OUTPUT — content is empty because "
            "the model spent the entire token budget thinking "
            "(operation=%s, model=%s, content_budget=%s, reasoning_budget=%s, "
            "wire_cap=%s, output_tokens=%s, reasoning_tokens=%s, short=%s). "
            "Retry with reasoning='off' or raise reasoning_budget.",
            operation,
            result.model,
            content_budget,
            reasoning_budget,
            cap,
            result.output_tokens,
            result.reasoning_tokens,
            "reasoning_budget" if over_reasoning else "max_tokens",
        )
    elif result.truncated:
        logger.warning(
            "[native] Response hit the token ceiling "
            "(operation=%s, model=%s, content_budget=%s, reasoning_budget=%s, "
            "wire_cap=%s, reasoning_tokens=%s, chars=%s, short=%s)",
            operation,
            result.model,
            content_budget,
            reasoning_budget,
            cap,
            result.reasoning_tokens,
            len(result.content),
            "reasoning_budget" if over_reasoning else "max_tokens",
        )
