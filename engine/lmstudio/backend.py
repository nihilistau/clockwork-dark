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
tools (inline functions)     NO (400)           YES
tools (MCP integrations)     YES                NO -- key not read
structured output            NO (400)           YES
===========================  =================  ======================

So: a request that needs inline ``tools=`` or ``response_format`` must go
OpenAI-compat. Everything else goes native, because only native can stop a
reasoning model from spending the entire token budget thinking -- the confirmed
cause of ``content: ""`` reaching the player as a frozen screen.

``integrations`` INVERTS THE RULE. Tool calling used to be a reason to avoid
the native route; over MCP it is a reason to INSIST on it, because that is the
only route that reads the key at all. A request carrying integrations therefore
goes native or does not go -- falling back to compat would silently drop the
tools and return an answer the model invented instead of resolved. What still
cannot be combined is integrations and ``response_format``: the native route
rejects the latter with 400 ``unrecognized_keys`` even alongside integrations,
which is why the tool call and the grammared narration are two calls.

THE TWO BUDGETS
---------------
``max_tokens`` here, and everywhere below it, means the CONTENT budget: what
the answer may spend. The profile's ``reasoning_budget`` is added on top by the
transport, because only the transport knows whether the reasoning mode it was
handed will actually be honoured -- the native route honours ``off``, the
OpenAI-compatible route ignores it and thinks anyway.

THE RETRY
---------
``LMSResponse.starved_by_reasoning`` (finish_reason "length" AND empty content)
is treated as its own failure class, not as "the model wrote nothing". When it
fires, the request is retried once on the native transport with
``reasoning="off"``, which is the only thing that reliably fixes it.

That retry is now a net under a floor rather than the floor itself. It used to
fire on nearly every narration turn, and each firing cost a full wasted
generation -- 1753-2997 reasoning tokens at ~16 tok/s, so two to three minutes
thrown away before the real answer began. With content and reasoning budgeted
separately it should almost never fire; if it does, the log names which of the
two budgets ran short.

Version: v0.2.0 [2026-08-14]
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable, Generator, Optional

from engine.config import get_config
from engine.lmstudio.client import LMSClient, compat_cap, get_lms_client
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
        integrations: Optional[list[Any]] = None,
    ) -> bool:
        """
        Decide the transport for one request.

        Inline ``tools`` and structured output are rejected outright by
        ``/api/v1/chat`` (``unrecognized_keys``), so those requests have no
        choice. ``integrations`` is the opposite case: only the native route
        reads it, so a request carrying MCP servers must go native even though
        it is, in every other sense, a tool call.
        """
        if response_format:
            return False
        if integrations:
            if self.native_available():
                return True
            logger.error(
                "[backend] MCP integrations were requested but the native API is "
                "unavailable (operation=use_native). The OpenAI-compatible route "
                "does not read `integrations`, so the model will answer with NO "
                "tools -- inventing outcomes the engine should have resolved."
            )
            return False
        if tools:
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
                max_tokens=200,
                # This route cannot turn reasoning off, so the probe has to pay
                # for thinking too -- otherwise a reasoning model fails a probe
                # about whether the SERVER supports grammars.
                reasoning_budget=mp.reasoning_budget,
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
        integrations: Optional[list[Any]] = None,
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
            integrations: MCP servers the model may call tools on. Forces the
                native transport -- see ``use_native``.
            reasoning: Override the profile's reasoning policy for this call.
            retry_on_starvation: Retry once with reasoning off if the content
                channel comes back empty behind a full reasoning channel.

        Returns:
            LMSResponse with both output channels populated.
        """
        mp = resolve_profile(profile)
        # `cap` is the CONTENT budget throughout this module. The transports add
        # `reasoning_budget` on top themselves, because only they know whether
        # the mode they were handed will actually be honoured.
        cap = int(max_tokens or mp.max_tokens)
        temp = float(mp.temperature if temperature is None else temperature)
        mode = str(reasoning or mp.reasoning)

        if self.use_native(
            tools=tools, response_format=response_format, integrations=integrations
        ):
            with inference_slot(label=label or profile, lane=mp.lane):
                result = self.native_client().chat(
                    messages,
                    model=mp.model,
                    temperature=temp,
                    max_tokens=cap,
                    reasoning=mode,
                    reasoning_budget=mp.reasoning_budget,
                    context_length=mp.context_tokens,
                    integrations=integrations,
                )
        else:
            with inference_slot(label=label or profile, lane=mp.lane):
                result = self._compat.chat(
                    messages,
                    model=mp.model,
                    temperature=temp,
                    max_tokens=cap,
                    reasoning_budget=mp.reasoning_budget,
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
            "(operation=_retry_without_reasoning, model=%s, content_budget=%s, "
            "reasoning_budget=%s). This is the last-resort net; with the two "
            "budgets set correctly it should not fire.",
            mp.model,
            cap,
            mp.reasoning_budget,
        )
        with inference_slot(label=f"{label or mp.name}:retry", lane=mp.lane):
            return self.native_client().chat(
                messages,
                model=mp.model,
                temperature=temperature,
                max_tokens=cap,
                reasoning="off",
                # Deliberately not granted: the point of the retry is to spend
                # the whole ceiling on the answer.
                reasoning_budget=0,
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
        integrations: Optional[list[Any]] = None,
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
        # The CONTENT budget. The transport adds `reasoning_budget` to it.
        cap = int(max_tokens or mp.max_tokens)
        temp = float(mp.temperature if temperature is None else temperature)
        mode = str(reasoning or mp.reasoning)

        if self.use_native(
            tools=tools, response_format=response_format, integrations=integrations
        ):
            generator = self.native_client().chat_stream(
                messages,
                model=mp.model,
                temperature=temp,
                max_tokens=cap,
                reasoning=mode,
                reasoning_budget=mp.reasoning_budget,
                context_length=mp.context_tokens,
                integrations=integrations,
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
                reasoning_budget=mp.reasoning_budget,
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
    max_tokens: int = 200,
) -> dict[str, Any]:
    """
    Ask for one completion THE WAY A TURN DOES, and report what came back.

    THE GAP THIS CLOSES. Health-checking LM Studio by listing models asks "is a
    process listening", which is not the question. On this machine that ping
    answered while every chat call was rejected, so the doctor said ``ok``
    about a service that could not narrate a single turn -- the planner's
    failures were swallowed, the pipeline fell back to canned lines, and nothing
    in the health report pointed at the model.

    IT MUST TEST THE PATH THE GAME USES. The first version of this probe posted
    raw to the OpenAI-compatible route with a 16-token budget -- a transport and
    a budget no turn ever asks for. On a reasoning model that starves instantly,
    so the doctor reported FAIL while the game beside it narrated fine: the real
    path prefers ``/api/v1/chat`` (where ``reasoning: "off"`` is honoured) and
    retries once on starvation. A health check that fails where the product
    succeeds trains people to ignore it, which is worse than not checking.

    So the probe runs ``LMStudioBackend.chat`` first -- same transport choice,
    same retry -- and only falls back to posting raw when that raises, because
    ``LMSClient`` discards the response body and the body is the only part that
    says *why*.

    Args:
        profile: Which profile's resolved model to probe. Defaults to the
            narration profile, because that is the one a turn depends on.
        timeout: Seconds. Short on purpose -- a doctor that hangs for three
            minutes on a wedged server is a doctor nobody runs. A cold JIT load
            of a large model can legitimately exceed this; the result says
            "timeout" and names that as a possibility rather than claiming the
            server is broken.
        max_tokens: The CONTENT budget for the probe -- enough for a real short
            answer. The profile's ``reasoning_budget`` is added on top by the
            transport, so a model which thinks before it speaks is not scored
            as broken for thinking, and the probe no longer has to guess a
            combined number that covers both.

    Returns:
        ``{"ok", "status", "detail", "model", "bound", "transport",
        "latency_ms", "content"}``. ``status`` is one of ``ok``, ``http``,
        ``timeout``, ``unreachable``, ``empty``.
    """
    import time

    import httpx

    from engine.lmstudio.routes import COMPAT_CHAT_PATH, compat_base

    cfg = get_config()
    # The OpenAI-compatible route, and deliberately so: /v1/chat/completions is
    # genuinely served (unlike /v1/models) and is the only one that takes tools
    # and structured output, which is what the game's real path uses.
    base = compat_base()
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

    messages = [{"role": "user", "content": "Reply with the single word: ready"}]

    # 1. The real path. This is what a turn gets, including the transport
    #    choice and the starvation retry, so its verdict is the product's.
    t_real = time.perf_counter()
    try:
        answer = get_backend().chat(
            messages, profile=profile, max_tokens=max_tokens, temperature=0.0
        )
        content = str(getattr(answer, "content", "") or "").strip()
        if content:
            result["latency_ms"] = (time.perf_counter() - t_real) * 1000
            result["content"] = content
            result["ok"] = True
            result["status"] = "ok"
            result["transport"] = str(getattr(answer, "transport", "") or "backend")
            spent = int(getattr(answer, "reasoning_tokens", 0) or 0)
            thinking = f", {spent} reasoning tokens" if spent else ""
            result["detail"] = (
                f"{content[:60]!r} in {result['latency_ms']:.0f}ms{thinking}"
            )
            return result
        # A 200 with nothing in it, even after the retry. Fall through to the
        # raw post so the report can carry the server's own words.
    except Exception as exc:  # noqa: BLE001 -- the raw post below explains it
        logger.debug("[backend] Probe's real path failed, falling back: %s", exc)

    # 2. The diagnostic path, only reached when the real one could not answer.
    payload = {
        "model": mp.model,
        "messages": messages,
        "temperature": 0.0,
        # Raw compat post: reasoning cannot be turned off here, so the budget
        # for it is granted. A diagnostic that starves where the product does
        # not is a diagnostic that lies.
        "max_tokens": compat_cap(max_tokens, mp.reasoning_budget),
        "stream": False,
    }

    t0 = time.perf_counter()
    try:
        response = httpx.post(
            f"{base}{COMPAT_CHAT_PATH}", json=payload, headers=headers, timeout=timeout
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
            "HTTP 200 with an empty content channel, on the real path AND on a "
            "plain retry -- the model spends its whole budget reasoning. Set "
            f"lmstudio.profiles.{profile}.reasoning: off, or raise its "
            f"reasoning_budget (now {mp.reasoning_budget}) so thinking has room "
            "of its own instead of taking the answer's."
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
