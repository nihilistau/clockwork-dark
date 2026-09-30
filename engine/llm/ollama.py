"""
OllamaClient -- Ollama's native ``POST /api/chat``, for every Ollama request.

WHY NOT OLLAMA'S ``/v1/chat/completions``
-----------------------------------------
That route cannot set ``num_ctx``. Ollama's default context is a few thousand
tokens, and it truncates a longer prompt FROM THE FRONT, silently: the system
persona is the first thing to go. That is the defect that once dropped the
persona on LM Studio (``reserve_output``'s comment), arriving by a new door.
The compat route's reasoning control is also less direct than ``think``.
``/api/chat`` takes the grammar (``format``), ``think``, ``options.num_ctx``
and tools together in one request, so it is strictly better for this engine
(spec §6).

REQUEST SHAPE (from Ollama's API reference; ``authored`` until recorded live)::

    {"model": ..., "messages": [{"role", "content", ...}],
     "format": <schema> | "json", "think": bool,
     "options": {"temperature", "num_predict", "num_ctx"},
     "keep_alive": <seconds>, "tools": [...], "stream": bool}

* ``messages`` keep OpenAI's roles: ``/api/chat`` has per-message roles, so
  nothing is flattened (unlike LM Studio's native route).
* ``format`` is the structured-output rung. The backend hands this client the
  OpenAI shape every other row sends (``backend.wire_form``) and a caller may
  pass its own (the planner, ``scripts/author.py``); both are translated here
  (``ollama_format``): ``json_schema`` -> the schema itself, ``json_object`` ->
  ``"json"``. Anything else is REFUSED -- the request is not sent, and the
  error names the caller's label -- never silently dropped, because a request
  that lost its grammar would come back as prose the caller then fails to
  parse, with nothing in the log to say why.
* ``think`` goes only where ``/api/show`` listed ``thinking`` (``think_for``):
  Ollama answers 400 to ``think`` on a model without the capability.
* ``options.num_predict`` is the wire cap (``patched_cap``, spec §5.2): the
  content budget alone only when a trusted ``think: false`` went on the wire.
* ``options.num_ctx`` is ALWAYS sent: the profile's bound context, the number
  the prompt budget was sized against.
* ``keep_alive`` is ``llm.keep_alive_seconds`` (the profile's ``ttl``).

RESPONSE SHAPE::

    {"model", "created_at",
     "message": {"role", "content", "thinking", "tool_calls": [...]},
     "done": true, "done_reason": "stop" | "length" | ...,
     "prompt_eval_count", "eval_count", ...}

Streamed, the same object arrives once per line (NDJSON), each carrying a
delta, and the last with ``done: true`` and the counts. ``message.thinking``
is the reasoning channel -- ``on_reasoning`` and the ``reasoning.*`` events,
never the generator -- and a leading ``<think>`` inside ``content`` is moved
there too (the row's ``inline_think: strip``, ``client.InlineThinkSplitter``).
``done_reason: "length"`` stays ``length``, so ``starved_by_reasoning`` fires.
Ollama reports no reasoning-token count, so a starved request's retry is
``think: false`` or nothing (``backend._retry_on_compat``, spec §5.3).

The same ``LMSResponse`` / ``LMSStreamEvent`` vocabulary as ``lmstudio_native.py`` and
``client.py``, so nothing downstream learns a third shape.

Version: v0.1.0 [2026-09-29]
"""

from __future__ import annotations

import json
import logging
import time
import uuid
import weakref
from typing import Any, Callable, Generator, Optional

import httpx

from engine.config import get_config
from engine.llm.client import (
    InlineThinkSplitter,
    parse_tool_calls,
    patched_cap,
    reasoning_patch,
    strip_inline_think,
    warn_patch_ignored,
)
from engine.llm.events import LMSResponse, LMSStreamEvent
from engine.llm.providers import get_provider
from engine.llm.routes import OLLAMA_CHAT_PATH, route_url

logger = logging.getLogger(__name__)

_client_instance: Optional["OllamaClient"] = None


class UnsupportedResponseFormat(ValueError):
    """A ``response_format`` with no ``format`` equivalent on ``/api/chat``."""


def ollama_format(response_format: Optional[dict[str, Any]], *, label: str = "") -> Any:
    """
    An OpenAI-shaped ``response_format`` as Ollama's ``format``, or None.

    ``{"type": "json_schema", "json_schema": {"schema": S, ...}}`` is ``S``;
    ``{"type": "json_object"}`` is ``"json"``. Anything else raises
    ``UnsupportedResponseFormat`` after an ERROR naming the caller's
    ``label``, so the request is refused rather than sent without its grammar.
    """
    if not response_format:
        return None
    kind = response_format.get("type") if isinstance(response_format, dict) else None
    if kind == "json_object":
        return "json"
    if kind == "json_schema":
        envelope = response_format.get("json_schema")
        schema = envelope.get("schema") if isinstance(envelope, dict) else None
        if isinstance(schema, dict):
            return schema
    shape = (
        sorted(response_format) if isinstance(response_format, dict) else type(response_format).__name__
    )
    logger.error(
        "[ollama] Refused a response_format with no Ollama `format` equivalent: "
        "only json_schema (with a schema) and json_object translate, and a "
        "request is never sent without the grammar its caller asked for "
        "(operation=ollama_format, caller=%s, type=%r, keys=%s)",
        label or "(unlabelled)",
        kind,
        shape,
    )
    raise UnsupportedResponseFormat(
        f"{label or 'a caller'} passed a response_format of type {kind!r}, which "
        "Ollama's /api/chat cannot express (json_schema with a schema, or json_object)"
    )


#: ``think`` values Ollama documents as effort levels (gpt-oss), rather than
#: ``true``/``false``.
EFFORT_LEVELS: frozenset[str] = frozenset({"low", "medium", "high"})


def think_for(model: str, reasoning: Optional[str]) -> Optional[Any]:
    """
    The ``think`` value this request may carry, or None to omit it (spec §5.1).

    Only a model whose ``/api/show`` listed ``thinking`` takes the key at all;
    any other answers 400 ("does not support thinking"). Its options are
    ``off``/``on`` unless ``llm.declared_models.<id>.reasoning`` narrowed them
    (``discovery.NARROWS_REASONING``):

    * ``off`` is the provider row's patch (``{"think": false}``), sent only
      where the options include ``off``; UNTRUSTED unless a declaration lists
      ``off`` (measured, v0.19.0 T8: the library's ``qwen3:4b`` reports
      ``thinking`` and thinks through ``think: false``, into the answer), and
      then trusted unless it also says ``reasoning_off_trusted: false``;
    * an effort level (``low``/``medium``/``high``) the options name is sent
      AS that string -- the gpt-oss form, which ignores ``true``/``false``;
    * ``on``, or an effort level the options do not name, is ``true`` where
      the options include ``on``, else nothing.

    A model discovery never measured gets nothing: that is the no-server
    path, not a capability decision.
    """
    mode = str(reasoning or "on")
    if mode == "off":
        patch = reasoning_patch(model, "off")
        return None if patch is None else bool(patch.body.get("think"))
    from engine.llm.registry import get_registry

    info = get_registry().cached(model)
    if info is None or not info.reasoning_configurable:
        return None
    if mode in EFFORT_LEVELS and mode in info.reasoning_options:
        return mode
    if info.accepts_reasoning("on"):
        return True
    return None


def _forced_open(model: str, reasoning: Optional[str]) -> bool:
    """Whether this request sent an UNTRUSTED ``think: false`` (``client.InlineThinkSplitter``)."""
    if str(reasoning or "") != "off":
        return False
    patch = reasoning_patch(model, "off")
    return patch is not None and not patch.trusted


def _text(content: Any) -> str:
    """A message's content as text: a multimodal array keeps its text parts."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            str(p.get("text") or p.get("content") or "") for p in content if isinstance(p, dict)
        )
    return "" if content is None else str(content)


def messages_to_ollama(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    OpenAI messages as ``/api/chat`` messages.

    Roles pass through. Content is text (images are not wired through this
    path), and an assistant turn's OpenAI ``tool_calls`` carry their
    arguments as an object, which is how ``/api/chat`` takes them.
    """
    out: list[dict[str, Any]] = []
    for message in messages:
        row = dict(message)
        row["content"] = _text(message.get("content"))
        calls = message.get("tool_calls")
        if isinstance(calls, list):
            row["tool_calls"] = [
                {"function": {"name": c.name, "arguments": dict(c.arguments)}}
                for c in parse_tool_calls(calls)
            ]
        out.append(row)
    return out


class OllamaClient:
    """Ollama's ``/api/chat``, streamed (NDJSON) and not."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        *,
        timeout: Optional[float] = None,
        api_key: str = "",
    ) -> None:
        cfg = get_config()
        # Ollama's base has no /v1; ``route_url`` puts /api/* on the server
        # root either way, so a base written with one still works.
        self.chat_url = route_url(OLLAMA_CHAT_PATH, base_url)
        self.root = self.chat_url[: -len(OLLAMA_CHAT_PATH)]
        self.timeout = (
            float(cfg.get("llm.timeout_seconds", 300)) if timeout is None else timeout
        )
        # None locally; a reverse proxy in front of Ollama may want one.
        self.api_key = api_key or cfg.get("llm.api_key", "") or ""
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        self._client = httpx.Client(timeout=timeout, headers=headers)

    def close(self) -> None:
        self._client.close()

    def is_available(self) -> bool:
        """
        Whether an Ollama answers here and can serve a turn: the ``ollama``
        row's health probe (``Provider.health_probe``, spec §8), the same
        question ``LMSClient.is_available`` asks under this row --
        ``GET /api/version`` must return ``{"version": ...}``, then
        ``GET /api/tags`` must be Ollama's list with a model in it. Each is
        shape-checked, because a server can answer a route it does not own
        with 200 and an error body.

        Asked by the summarizer's gate through
        ``LMStudioBackend.server_available`` on this row.
        """
        from engine.llm.providers import get_provider

        available, detail = get_provider("ollama").health_probe(
            self.root, api_key=self.api_key, timeout=5.0
        )
        logger.info(
            "[ollama] Ollama probe (operation=is_available, root=%s, "
            "available=%s): %s",
            self.root,
            available,
            detail,
        )
        return available

    # -- the request ---------------------------------------------------------

    def _payload(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str,
        temperature: float,
        max_tokens: int,
        reasoning_budget: int,
        reasoning: Optional[str],
        context_length: int,
        ttl: int,
        tools: Optional[list[dict[str, Any]]],
        response_format: Optional[dict[str, Any]],
        stream: bool,
        label: str,
    ) -> dict[str, Any]:
        grammar = ollama_format(response_format, label=label or model)
        patch = reasoning_patch(model, reasoning)
        num_ctx = int(context_length or 0) or int(get_config().get("llm.context_tokens", 8192) or 8192)
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages_to_ollama(messages),
            "options": {
                "temperature": temperature,
                "num_predict": patched_cap(max_tokens, reasoning_budget, reasoning, patch),
                # ALWAYS: without it Ollama truncates a long prompt from the
                # front, silently (the module docstring).
                "num_ctx": num_ctx,
            },
            "stream": stream,
        }
        if grammar is not None:
            payload["format"] = grammar
        think = think_for(model, reasoning)
        if think is not None:
            payload["think"] = think
        if tools:
            payload["tools"] = tools
        # 0 sends nothing, so Ollama's own default applies (config/default.yaml):
        # Ollama reads `keep_alive: 0` as "unload after this request".
        if ttl > 0 and get_provider().keep_alive.value == "keep_alive":
            payload["keep_alive"] = int(ttl)
        return payload

    @staticmethod
    def _raise_for_status(response: httpx.Response, operation: str, model: str, label: str) -> None:
        """``raise_for_status``, with Ollama's own words (``{"error": ...}``) logged first."""
        if response.status_code < 400:
            return
        try:
            body = " ".join(response.text.split())[:400]
        except Exception:  # noqa: BLE001 -- an unreadable body must not mask the status
            body = "(body unreadable)"
        logger.error(
            "[ollama] Ollama refused the request (operation=%s, status=%s, "
            "model=%s, caller=%s): %s",
            operation,
            response.status_code,
            model,
            label or "(unlabelled)",
            body or "(empty body)",
        )
        response.raise_for_status()

    @staticmethod
    def _stats(data: dict[str, Any], finish_reason: str, latency: float) -> dict[str, Any]:
        return {
            "latency_ms": latency,
            "finish_reason": finish_reason,
            "input_tokens": int(data.get("prompt_eval_count", 0) or 0),
            "total_output_tokens": int(data.get("eval_count", 0) or 0),
        }

    # -- calls ----------------------------------------------------------------

    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str,
        temperature: float = 0.8,
        max_tokens: int = 1500,
        tools: Optional[list[dict[str, Any]]] = None,
        tool_choice: Optional[str] = None,
        response_format: Optional[dict[str, Any]] = None,
        ttl: int = 0,
        reasoning_budget: int = 0,
        reasoning: Optional[str] = None,
        context_length: int = 0,
        label: str = "",
    ) -> LMSResponse:
        """
        Non-streaming ``/api/chat``. ``LMSClient.chat``'s signature, plus the
        context to send as ``num_ctx`` and the caller's label (named in a
        refusal). ``tool_choice`` has no ``/api/chat`` key and is not sent.

        Raises:
            UnsupportedResponseFormat: ``response_format`` cannot be expressed
                as ``format``; nothing was sent.
        """
        payload = self._payload(
            messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            reasoning_budget=reasoning_budget,
            reasoning=reasoning,
            context_length=context_length,
            ttl=ttl,
            tools=tools,
            response_format=response_format,
            stream=False,
            label=label,
        )
        t0 = time.perf_counter()
        try:
            response = self._client.post(self.chat_url, json=payload, timeout=self.timeout)
            self._raise_for_status(response, "chat", model, label)
            data = response.json()
        except httpx.HTTPError as exc:
            logger.error("[ollama] Chat failed (operation=chat, model=%s): %s", model, exc)
            raise

        message = data.get("message") if isinstance(data.get("message"), dict) else {}
        content = str(message.get("content") or "")
        reasoning_text = str(message.get("thinking") or "")
        finish = str(data.get("done_reason") or "")
        if get_provider().inline_think.value == "strip":
            content, reasoning_text = strip_inline_think(
                content,
                reasoning_text,
                forced_open=_forced_open(model, reasoning),
                truncated=finish == "length",
                grammar="format" in payload,
                model=model,
            )
        latency = (time.perf_counter() - t0) * 1000
        result = LMSResponse(
            content=content,
            reasoning_content=reasoning_text,
            model=str(data.get("model") or model),
            input_tokens=int(data.get("prompt_eval_count", 0) or 0),
            output_tokens=int(data.get("eval_count", 0) or 0),
            latency_ms=latency,
            stats=self._stats(data, finish, latency),
            tool_calls=parse_tool_calls(message.get("tool_calls")),
            finish_reason=finish,
            transport="ollama",
        )
        _log_outcome("chat", result, max_tokens, reasoning_budget, payload)
        return result

    def chat_stream(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str,
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
        context_length: int = 0,
        label: str = "",
    ) -> Generator[str, None, LMSResponse]:
        """
        Stream ``/api/chat`` (NDJSON: one JSON object per line).

        Yields CONTENT deltas only. ``message.thinking`` -- and a leading
        ``<think>`` span inside ``message.content`` -- goes to ``on_reasoning``
        and the ``reasoning.*`` events and is never yielded: everything
        downstream of the yield (the tag scanner, the narration decoder) would
        otherwise act on the model's musings. Events are the native
        vocabulary, as ``LMSClient.chat_stream`` emits them.

        Returns:
            LMSResponse via StopIteration.value.

        Raises:
            UnsupportedResponseFormat: nothing was sent.
            RuntimeError: an ``{"error": ...}`` line arrived mid-stream.
        """
        payload = self._payload(
            messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            reasoning_budget=reasoning_budget,
            reasoning=reasoning,
            context_length=context_length,
            ttl=ttl,
            tools=tools,
            response_format=response_format,
            stream=True,
            label=label,
        )
        # An untrusted `think: false` may be ignored, and then the thinking
        # arrives in the content with no opening tag: held until decided --
        # but only with no `format` on the request: under one Ollama sends
        # thinking in `message.thinking` (measured), and holding would blank
        # the stream (fix round 1).
        forced = _forced_open(model, reasoning)
        splitter = (
            InlineThinkSplitter(
                forced_open=forced,
                hold=forced and "format" not in payload,
                grammar="format" in payload,
            )
            if get_provider().inline_think.value == "strip"
            else None
        )
        t0 = time.perf_counter()
        if on_event:
            on_event(LMSStreamEvent(event_type="chat.start", model_instance_id=model))

        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        raw_calls: list[Any] = []
        final: dict[str, Any] = {}
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
                "POST", self.chat_url, json=payload, timeout=self.timeout
            ) as response:
                if response.status_code >= 400:
                    response.read()
                self._raise_for_status(response, "chat_stream", model, label)
                for data in _iter_ndjson(response):
                    if data.get("error"):
                        message = str(data["error"])
                        logger.error(
                            "[ollama] Stream error (operation=chat_stream, model=%s, "
                            "caller=%s): %s",
                            model,
                            label or "(unlabelled)",
                            message,
                        )
                        if on_event:
                            on_event(LMSStreamEvent(event_type="error", error=message))
                        raise RuntimeError(f"Ollama stream error: {message}")
                    delta = data.get("message") if isinstance(data.get("message"), dict) else {}
                    if isinstance(delta.get("tool_calls"), list):
                        raw_calls.extend(delta["tool_calls"])
                    thinking = str(delta.get("thinking") or "")
                    if thinking:
                        _reason(thinking)
                    text = str(delta.get("content") or "")
                    pieces = splitter.push(text) if splitter is not None else (
                        [("content", text)] if text else []
                    )
                    for channel, piece in pieces:
                        if channel == "reasoning":
                            _reason(piece)
                        else:
                            yield _content(piece)
                    if data.get("done"):
                        final = data
                        break
                if splitter is not None:
                    cut = final.get("done_reason") == "length" or not final.get("done")
                    for channel, piece in splitter.flush(truncated=cut):
                        if channel == "reasoning":
                            _reason(piece)
                        else:
                            yield _content(piece)
                    if splitter.patch_ignored:
                        warn_patch_ignored(model)
        except httpx.HTTPError as exc:
            logger.error("[ollama] Stream failed (operation=chat_stream, model=%s): %s", model, exc)
            if on_event:
                on_event(LMSStreamEvent(event_type="error", error=str(exc)))
            raise

        latency = (time.perf_counter() - t0) * 1000
        if started_message and on_event:
            on_event(LMSStreamEvent(event_type="message.end"))
        finish = str(final.get("done_reason") or "")
        if not final.get("done"):
            # The connection closed before Ollama's `done` line. Read as
            # finished, a cut stream would reach the player as a whole turn;
            # read as truncated, the storyteller holds back the severed tail
            # (and an empty one is retried as starved).
            finish = "length"
            logger.warning(
                "[ollama] Stream ended with no `done` line; treated as truncated "
                "(operation=chat_stream, model=%s, caller=%s, chars=%s)",
                model,
                label or "(unlabelled)",
                sum(len(p) for p in content_parts),
            )
        stats = self._stats(final, finish, latency)
        if on_event:
            on_event(
                LMSStreamEvent(
                    event_type="chat.end",
                    response_id=f"resp_{uuid.uuid4().hex[:12]}",
                    stats=stats,
                )
            )
        result = LMSResponse(
            content="".join(content_parts),
            reasoning_content="".join(reasoning_parts),
            model=str(final.get("model") or model),
            input_tokens=stats["input_tokens"],
            output_tokens=stats["total_output_tokens"],
            latency_ms=latency,
            stats=stats,
            tool_calls=parse_tool_calls(raw_calls),
            finish_reason=finish,
            transport="ollama",
        )
        _log_outcome("chat_stream", result, max_tokens, reasoning_budget, payload)
        return result


def _iter_ndjson(response: httpx.Response) -> Generator[dict[str, Any], None, None]:
    """One JSON object per line; a line that is not one is skipped, not fatal."""
    for raw_line in response.iter_lines():
        line = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else raw_line
        if not line.strip():
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            logger.debug("[ollama] Undecodable NDJSON line (operation=_iter_ndjson)")
            continue
        if isinstance(data, dict):
            yield data


def _log_outcome(
    operation: str,
    result: LMSResponse,
    content_budget: int,
    reasoning_budget: int,
    payload: dict[str, Any],
) -> None:
    """
    Name the empty-content failure for what it is, and both budgets.

    Ollama reports no reasoning-token count, so ``short=`` cannot be read off
    the answer: the log says whether ``think: false`` was already on the
    request instead, which is what decides the retry (spec §5.3).
    """
    cap = payload.get("options", {}).get("num_predict")
    if result.starved_by_reasoning:
        logger.error(
            "[ollama] REASONING STARVED THE OUTPUT -- content is empty because "
            "the model spent the entire token budget thinking (operation=%s, "
            "model=%s, content_budget=%s, reasoning_budget=%s, num_predict=%s, "
            "num_ctx=%s, think=%s, reasoning_chars=%s)",
            operation,
            result.model,
            content_budget,
            reasoning_budget,
            cap,
            payload.get("options", {}).get("num_ctx"),
            payload.get("think", "omitted"),
            len(result.reasoning_content),
        )
    elif result.truncated:
        logger.warning(
            "[ollama] Response truncated at the wire cap (operation=%s, model=%s, "
            "content_budget=%s, reasoning_budget=%s, num_predict=%s, chars=%s)",
            operation,
            result.model,
            content_budget,
            reasoning_budget,
            cap,
            len(result.content),
        )


def get_ollama_client() -> OllamaClient:
    """Singleton Ollama client, built from the config in force."""
    global _client_instance
    if _client_instance is None:
        _client_instance = OllamaClient()
    return _client_instance


def release_ollama_client() -> None:
    """
    Drop the singleton WITHOUT closing it: a config reload
    (``engine/games/caches.py``), as ``client.release_lms_client`` does. The
    next ``get_ollama_client()`` dials the new base URL with the new key; a
    turn still streaming through the old one finishes, and its pool closes
    once nothing holds it.
    """
    global _client_instance
    old = _client_instance
    _client_instance = None
    if old is not None:
        weakref.finalize(old, old._client.close)


__all__ = [
    "OllamaClient",
    "UnsupportedResponseFormat",
    "get_ollama_client",
    "messages_to_ollama",
    "ollama_format",
    "release_ollama_client",
    "think_for",
]
