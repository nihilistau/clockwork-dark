"""
LM Studio Backend Router
========================

Picks a transport per request and owns the retry for the empty-narration bug.

THE ROUTING RULE
----------------
LM Studio exposes two chat APIs and neither is a superset of the other
(both verified against a live 0.3.x server):

===========================  =================  ======================
capability                   /api/v1/chat       /v1/chat/completions
===========================  =================  ======================
control reasoning            YES (reasoning=)   NO -- every knob ignored
typed SSE (reasoning split)  YES                emulated from deltas
real token stats             YES                needs stream_options
tool calling                 NO (400)           YES
structured output            NO (400)           YES
===========================  =================  ======================

So: a request that needs tools or ``response_format`` must go OpenAI-compat.
Everything else goes native, because only native can stop a reasoning model
from spending the entire token budget thinking -- the confirmed cause of
``content: ""`` reaching the player as a frozen screen.

THE RETRY
---------
``LMSResponse.starved_by_reasoning`` (finish_reason "length" AND empty content)
is treated as its own failure class, not as "the model wrote nothing". When it
fires, the request is retried once on the native transport with
``reasoning="off"``, which is the only thing that reliably fixes it.

Version: v0.1.0 [2026-08-08]
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable, Generator, Optional

from engine.config import get_config
from engine.lmstudio.client import LMSClient, get_lms_client
from engine.lmstudio.events import LMSResponse, LMSStreamEvent
from engine.lmstudio.gate import inference_slot
from engine.lmstudio.native import NativeClient
from engine.lmstudio.profiles import ModelProfile, resolve_profile

logger = logging.getLogger(__name__)


def _response_format(
    schema: dict[str, Any], *, name: str = "structured_output"
) -> dict[str, Any]:
    """
    Wrap a schema in the OpenAI ``response_format`` envelope.

    Accepts either a bare JSON schema or a pre-built
    ``{"name", "strict", "schema"}`` envelope -- ``schemas.storyteller_turn_schema``
    returns the latter.
    """
    if "schema" in schema and "name" in schema:
        return {"type": "json_schema", "json_schema": schema}
    return {
        "type": "json_schema",
        "json_schema": {"name": name, "strict": True, "schema": schema},
    }


class LMStudioBackend:
    """Routes chat requests to the native or OpenAI-compatible transport."""

    def __init__(
        self,
        *,
        compat: Optional[LMSClient] = None,
        native: Optional[NativeClient] = None,
        prefer_native: Optional[bool] = None,
    ) -> None:
        cfg = get_config()
        self._compat = compat or get_lms_client()
        self._native = native
        self._prefer_native = (
            bool(cfg.get("lmstudio.prefer_native", True))
            if prefer_native is None
            else prefer_native
        )
        self._native_available: Optional[bool] = None
        self._structured_ok: Optional[bool] = None
        self._lock = threading.Lock()

    # -- transport selection -------------------------------------------------

    def native_client(self) -> NativeClient:
        """Lazily construct the native client."""
        with self._lock:
            if self._native is None:
                self._native = NativeClient()
            return self._native

    def native_available(self) -> bool:
        """
        Whether ``/api/v1/chat`` is usable. Probed once per process.

        A probe costs one request that loads no model; the answer is stable for
        the lifetime of the server connection.
        """
        if not self._prefer_native:
            return False
        with self._lock:
            cached = self._native_available
        if cached is not None:
            return cached
        available = self.native_client().is_available()
        with self._lock:
            self._native_available = available
        if not available:
            logger.warning(
                "[backend] Native /api/v1/chat unavailable; falling back to the "
                "OpenAI-compatible endpoint, which CANNOT disable reasoning "
                "(operation=native_available)"
            )
        return available

    def use_native(
        self,
        *,
        tools: Optional[list[dict[str, Any]]] = None,
        response_format: Optional[dict[str, Any]] = None,
    ) -> bool:
        """
        Decide the transport for one request.

        Tools and structured output are rejected outright by ``/api/v1/chat``
        (``unrecognized_keys``), so those requests have no choice.
        """
        if tools or response_format:
            return False
        return self.native_available()

    # -- structured output ---------------------------------------------------

    def structured_output(
        self, schema: Optional[dict[str, Any]]
    ) -> Optional[dict[str, Any]]:
        """
        Build a ``response_format`` payload, honouring ``lmstudio.structured_output``.

        Implements the config key that was previously read NOWHERE -- ``auto``
        was documented as "probes the server once and caches the answer" and no
        probe existed, so the mode silently behaved as "off" everywhere.

        Modes:
            off          -- never constrain output. Frees the request to use the
                            native transport, which is the only one that can
                            turn reasoning off.
            json_schema  -- always send the full schema.
            json_object  -- valid JSON, shape unconstrained. NOTE: LM Studio
                            rejects OpenAI's ``{"type": "json_object"}`` with
                            400 ``'response_format.type' must be 'json_schema'
                            or 'text'``, so this is emitted as a permissive
                            json_schema instead.
            auto         -- probe once; use json_schema if the server accepts it.

        A caveat worth restating: a grammar constrains the CONTENT channel only.
        Reasoning runs ungrammared and uncapped, so structured output offers
        ZERO protection against a reasoning model eating the whole token budget.
        """
        if not schema:
            return None
        mode = str(get_config().get("lmstudio.structured_output", "auto")).lower()
        if mode == "off":
            return None
        if mode == "json_object":
            return _response_format(
                {"type": "object", "additionalProperties": True}, name="json_object"
            )
        if mode == "json_schema":
            return _response_format(schema)
        if mode == "auto" and self._probe_structured_output():
            return _response_format(schema)
        return None

    def _probe_structured_output(self) -> bool:
        """
        One cheap request that asks for a two-field object under a schema.

        Cached for the process. Small quantized models routinely ignore or
        choke on grammars, and finding that out mid-turn costs the player a
        broken narration.
        """
        with self._lock:
            if self._structured_ok is not None:
                return self._structured_ok

        probe_schema = {
            "type": "object",
            "properties": {"ok": {"type": "boolean"}},
            "required": ["ok"],
        }
        ok = False
        try:
            mp = resolve_profile("big")
            response = self._compat.chat(
                [{"role": "user", "content": 'Reply with {"ok": true}'}],
                model=mp.model,
                temperature=0.0,
                max_tokens=2000,
                response_format=_response_format(probe_schema, name="probe"),
            )
            ok = '"ok"' in response.content
        except Exception as exc:  # noqa: BLE001 -- a failed probe means "no"
            logger.warning(
                "[backend] Structured-output probe failed (operation="
                "_probe_structured_output): %s",
                exc,
            )
        logger.info(
            "[backend] Structured-output probe (operation=_probe_structured_output, "
            "supported=%s)",
            ok,
        )
        with self._lock:
            self._structured_ok = ok
        return ok

    # -- calls ---------------------------------------------------------------

    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        profile: str = "big",
        tools: Optional[list[dict[str, Any]]] = None,
        tool_choice: Optional[str] = None,
        response_format: Optional[dict[str, Any]] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        reasoning: Optional[str] = None,
        label: str = "",
        retry_on_starvation: bool = True,
    ) -> LMSResponse:
        """
        Non-streaming completion on the best available transport.

        Args:
            profile: Logical profile; supplies model, lane, reasoning policy.
            reasoning: Override the profile's reasoning policy for this call.
            retry_on_starvation: Retry once with reasoning off if the content
                channel comes back empty behind a full reasoning channel.

        Returns:
            LMSResponse with both output channels populated.
        """
        mp = resolve_profile(profile)
        cap = int(max_tokens or mp.max_tokens)
        temp = float(mp.temperature if temperature is None else temperature)
        mode = str(reasoning or mp.reasoning)

        if self.use_native(tools=tools, response_format=response_format):
            with inference_slot(label=label or profile, lane=mp.lane):
                result = self.native_client().chat(
                    messages,
                    model=mp.model,
                    temperature=temp,
                    max_tokens=cap,
                    reasoning=mode,
                    context_length=mp.context_tokens,
                )
        else:
            with inference_slot(label=label or profile, lane=mp.lane):
                result = self._compat.chat(
                    messages,
                    model=mp.model,
                    temperature=temp,
                    max_tokens=cap,
                    tools=tools,
                    tool_choice=tool_choice,
                    response_format=response_format,
                    ttl=mp.ttl,
                )

        if retry_on_starvation and result.starved_by_reasoning:
            recovered = self._retry_without_reasoning(
                messages, mp, cap=cap, temperature=temp, label=label
            )
            if recovered is not None:
                return recovered
        return result

    def _retry_without_reasoning(
        self,
        messages: list[dict[str, Any]],
        mp: ModelProfile,
        *,
        cap: int,
        temperature: float,
        label: str,
    ) -> Optional[LMSResponse]:
        """
        Second attempt with reasoning switched off.

        Only the native transport can do this. On the OpenAI-compatible
        endpoint every reasoning control is ignored, so a retry there would
        starve exactly the same way and cost the player another full generation.
        """
        if not self.native_available():
            logger.error(
                "[backend] Cannot recover from reasoning starvation: the native "
                "API is unavailable and the OpenAI-compatible endpoint cannot "
                "disable reasoning (operation=_retry_without_reasoning, model=%s)",
                mp.model,
            )
            return None

        logger.warning(
            "[backend] Retrying with reasoning='off' after starvation "
            "(operation=_retry_without_reasoning, model=%s, max_tokens=%s)",
            mp.model,
            cap,
        )
        with inference_slot(label=f"{label or mp.name}:retry", lane=mp.lane):
            return self.native_client().chat(
                messages,
                model=mp.model,
                temperature=temperature,
                max_tokens=cap,
                reasoning="off",
                context_length=mp.context_tokens,
            )

    def chat_stream(
        self,
        messages: list[dict[str, Any]],
        *,
        profile: str = "big",
        tools: Optional[list[dict[str, Any]]] = None,
        tool_choice: Optional[str] = None,
        response_format: Optional[dict[str, Any]] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        reasoning: Optional[str] = None,
        on_event: Optional[Callable[[LMSStreamEvent], None]] = None,
        on_delta: Optional[Callable[[str], None]] = None,
        on_reasoning: Optional[Callable[[str], None]] = None,
    ) -> Generator[str, None, LMSResponse]:
        """
        Streaming completion on the best available transport.

        Yields content deltas only; reasoning is delivered through
        ``on_reasoning`` and the ``reasoning.*`` events. Callers must NOT feed
        reasoning into the tag scanner or the narration JSON decoder.

        Returns:
            LMSResponse via StopIteration.value.
        """
        mp = resolve_profile(profile)
        cap = int(max_tokens or mp.max_tokens)
        temp = float(mp.temperature if temperature is None else temperature)
        mode = str(reasoning or mp.reasoning)

        if self.use_native(tools=tools, response_format=response_format):
            generator = self.native_client().chat_stream(
                messages,
                model=mp.model,
                temperature=temp,
                max_tokens=cap,
                reasoning=mode,
                context_length=mp.context_tokens,
                on_event=on_event,
                on_delta=on_delta,
                on_reasoning=on_reasoning,
            )
        else:
            generator = self._compat.chat_stream(
                messages,
                model=mp.model,
                temperature=temp,
                max_tokens=cap,
                on_event=on_event,
                on_delta=on_delta,
                on_reasoning=on_reasoning,
                response_format=response_format,
                tools=tools,
                tool_choice=tool_choice,
                ttl=mp.ttl,
            )

        with inference_slot(label=profile, lane=mp.lane):
            return (yield from generator)

    def close(self) -> None:
        if self._native is not None:
            self._native.close()


def chat_probe(
    *,
    profile: str = "big",
    timeout: float = 20.0,
    max_tokens: int = 16,
) -> dict[str, Any]:
    """
    Ask the server for one tiny completion and report what actually came back.

    THE GAP THIS CLOSES. Health-checking LM Studio with ``GET /v1/models`` asks
    "is a process listening", which is not the question. On this machine that
    ping answered while every chat call was rejected, so the doctor said ``ok``
    about a service that could not narrate a single turn -- the planner's
    failures were swallowed, the pipeline fell back to canned lines, and nothing
    in the health report pointed at the model.

    Deliberately NOT routed through ``LMSClient``: that raises on a bad status
    and the response body -- the only part that says *why* -- is lost with it.
    This posts the payload itself so the server's own words reach the report.

    Args:
        profile: Which profile's resolved model to probe. Defaults to the
            narration profile, because that is the one a turn depends on.
        timeout: Seconds. Short on purpose -- a doctor that hangs for three
            minutes on a wedged server is a doctor nobody runs. A cold JIT load
            of a large model can legitimately exceed this; the result says
            "timeout" and names that as a possibility rather than claiming the
            server is broken.
        max_tokens: Tiny. This is a liveness question, not a generation.

    Returns:
        ``{"ok", "status", "detail", "model", "bound", "transport",
        "latency_ms", "content"}``. ``status`` is one of ``ok``, ``http``,
        ``timeout``, ``unreachable``, ``empty``.
    """
    import time

    import httpx

    cfg = get_config()
    base = str(cfg.get("lmstudio.base_url", "http://localhost:1234/v1")).rstrip("/")
    key = str(cfg.get("lmstudio.api_key", "") or "")
    headers = {"Authorization": f"Bearer {key}"} if key else {}

    mp = resolve_profile(profile)
    result: dict[str, Any] = {
        "ok": False,
        "status": "unreachable",
        "detail": "",
        "model": mp.model,
        "bound": mp.bound,
        "transport": "openai",
        "latency_ms": 0.0,
        "content": "",
    }

    # A model id the server never confirmed is a guaranteed 400. Say so before
    # spending a request proving it.
    if not mp.bound:
        result["detail"] = (
            f"model {mp.model!r} was never confirmed against the server -- "
            "discovery failed, so every chat request names a model LM Studio "
            "has never heard of"
        )

    payload = {
        "model": mp.model,
        "messages": [{"role": "user", "content": "Reply with the single word: ready"}],
        "temperature": 0.0,
        "max_tokens": max_tokens,
        "stream": False,
    }

    t0 = time.perf_counter()
    try:
        response = httpx.post(
            f"{base}/chat/completions", json=payload, headers=headers, timeout=timeout
        )
    except httpx.TimeoutException:
        result["status"] = "timeout"
        result["latency_ms"] = (time.perf_counter() - t0) * 1000
        result["detail"] = (
            f"no answer in {timeout:g}s -- a cold JIT load of a large model can "
            "take longer than this, so try again once it is resident"
        )
        return result
    except httpx.HTTPError as exc:
        result["status"] = "unreachable"
        result["detail"] = f"{type(exc).__name__}: {exc}"
        return result

    result["latency_ms"] = (time.perf_counter() - t0) * 1000

    if response.status_code != 200:
        body = " ".join(response.text.split())[:300]
        result["status"] = "http"
        result["detail"] = f"HTTP {response.status_code}: {body or '(empty body)'}"
        return result

    try:
        data = response.json()
        message = ((data.get("choices") or [{}])[0].get("message") or {})
        content = str(message.get("content") or "").strip()
    except Exception as exc:  # noqa: BLE001 -- a 200 that is not JSON is its own answer
        result["status"] = "http"
        result["detail"] = f"200 but unreadable: {exc}"
        return result

    result["content"] = content
    if not content:
        # The empty-narration bug, seen from outside. A 200 with no content is
        # the shape a reasoning model returns when it spent the budget thinking.
        result["status"] = "empty"
        result["detail"] = (
            "HTTP 200 with an empty content channel -- the model answered with "
            "reasoning only. Turn reasoning off for this profile."
        )
        return result

    result["ok"] = True
    result["status"] = "ok"
    result["detail"] = f"{content[:60]!r} in {result['latency_ms']:.0f}ms"
    return result


_backend: Optional[LMStudioBackend] = None
_backend_lock = threading.Lock()


def get_backend() -> LMStudioBackend:
    """Process-wide backend singleton."""
    global _backend
    with _backend_lock:
        if _backend is None:
            _backend = LMStudioBackend()
        return _backend


def reset_backend() -> None:
    """Drop the singleton. Tests, and config reloads."""
    global _backend
    with _backend_lock:
        if _backend is not None:
            _backend.close()
        _backend = None
