"""
LMSClient — LM Studio OpenAI-compatible SSE client.

Uses ``POST {base_url}/chat/completions`` with ``stream: true``.
Falls back gracefully when server is unavailable (for tests / offline dev).

Version: v0.1.0 [2026-06-20]
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
from engine.lmstudio.profiles import ModelProfile, resolve_profile

logger = logging.getLogger(__name__)

_client_instance: Optional["LMSClient"] = None


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


class LMSClient:
    """HTTP client for LM Studio chat completions with SSE streaming."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        *,
        timeout: float = 120.0,
        api_key: str = "",
    ) -> None:
        cfg = get_config()
        self.base_url = (base_url or cfg.get("lmstudio.base_url", "http://localhost:1234/v1")).rstrip("/")
        self.timeout = timeout
        self.api_key = api_key or cfg.get("lmstudio.api_key", "") or ""
        headers: dict[str, str] = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        self._client = httpx.Client(timeout=timeout, headers=headers)

    def close(self) -> None:
        """Close HTTP client."""
        self._client.close()

    def is_available(self) -> bool:
        """Return True if LM Studio responds."""
        try:
            r = self._client.get(f"{self.base_url}/models", timeout=3.0)
            return r.status_code == 200
        except Exception as exc:
            logger.debug("[LMSClient] Health check failed (operation=health): %s", exc)
            return False

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
    ) -> LMSResponse:
        """
        Non-streaming chat completion.

        A real single request, not a drained stream. The old version threw away
        the generator's return value, so latency, finish_reason and token counts
        were lost on the only path actually used -- and tool calls could not be
        returned at all.
        """
        resolved = model or resolve_profile("big").model
        payload: dict[str, Any] = {
            "model": resolved,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice or "auto"
        if response_format:
            payload["response_format"] = response_format

        t0 = time.perf_counter()
        try:
            response = self._client.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                timeout=self.timeout,
            )
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPError as exc:
            logger.error("[LMSClient] Chat failed (operation=chat): %s", exc)
            raise

        choices = data.get("choices") or []
        first = choices[0] if choices else {}
        message = first.get("message") or {}
        usage = data.get("usage") or {}

        return LMSResponse(
            content=message.get("content") or "",
            response_id=str(data.get("id", "")),
            model=str(data.get("model", resolved)),
            input_tokens=int(usage.get("prompt_tokens", 0) or 0),
            output_tokens=int(usage.get("completion_tokens", 0) or 0),
            latency_ms=(time.perf_counter() - t0) * 1000,
            tool_calls=parse_tool_calls(message.get("tool_calls")),
            finish_reason=str(first.get("finish_reason", "")),
        )

    def chat_stream(
        self,
        messages: list[dict[str, Any]],
        *,
        model: Optional[str] = None,
        temperature: float = 0.8,
        max_tokens: int = 1500,
        on_event: Optional[Callable[[LMSStreamEvent], None]] = None,
        on_delta: Optional[Callable[[str], None]] = None,
        response_format: Optional[dict[str, Any]] = None,
    ) -> Generator[str, None, LMSResponse]:
        """
        Stream chat completion tokens.

        Yields content deltas. Fires typed LMSStreamEvent via on_event, and
        calls on_delta for each chunk -- the hook the socket layer uses to push
        narration to the browser as it is generated.
        """
        resolved = model or resolve_profile("big").model
        payload: dict[str, Any] = {
            "model": resolved,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }
        if response_format:
            payload["response_format"] = response_format
        t0 = time.perf_counter()
        if on_event:
            on_event(LMSStreamEvent(event_type="chat.start", model_instance_id=resolved))

        content_parts: list[str] = []
        finish_reason = ""
        try:
            with self._client.stream(
                "POST",
                f"{self.base_url}/chat/completions",
                json=payload,
                timeout=self.timeout,
            ) as response:
                response.raise_for_status()
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
                    # Many OpenAI-compatible servers, LM Studio included, send a
                    # final usage-only chunk with "choices": []. Indexing [0] on
                    # that raises IndexError, which is not an httpx.HTTPError and
                    # so escapes the handler below mid-turn.
                    choices = data.get("choices") or []
                    first = choices[0] if choices else {}
                    if first.get("finish_reason"):
                        finish_reason = str(first["finish_reason"])
                    delta = (first.get("delta") or {}).get("content", "") or ""
                    if delta:
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
        if on_event:
            on_event(
                LMSStreamEvent(
                    event_type="chat.end",
                    response_id=f"resp_{uuid.uuid4().hex[:12]}",
                    stats={"latency_ms": latency},
                )
            )
        if finish_reason == "length":
            logger.warning(
                "[LMSClient] Response truncated at max_tokens "
                "(operation=chat_stream, model=%s, chars=%s)",
                resolved,
                len(full),
            )
        return LMSResponse(
            content=full,
            model=resolved,
            latency_ms=latency,
            finish_reason=finish_reason,
        )

    def infer_stream(
        self,
        messages: list[dict[str, Any]],
        *,
        profile: str = "big",
        on_event: Optional[Callable[[LMSStreamEvent], None]] = None,
    ) -> Generator[str, None, LMSResponse]:
        """Profile-aware streaming wrapper."""
        mp = resolve_profile(profile)
        return self.chat_stream(
            messages,
            model=mp.model,
            temperature=mp.temperature,
            max_tokens=mp.max_tokens,
            on_event=on_event,
        )

    def infer_processed(
        self,
        messages: list[dict[str, Any]],
        *,
        profile: str = "big",
        on_delta: Optional[Callable[[str], None]] = None,
    ):
        """
        Stream + tag extraction via StreamProcessor.

        Returns:
            ProcessedResponse from engine.agents.stream_processor
        """
        from engine.agents.stream_processor import StreamProcessor

        proc = StreamProcessor(on_delta=on_delta)
        gen = self.infer_stream(messages, profile=profile, on_event=proc.on_event)
        for _chunk in gen:
            pass
        return proc.result()


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