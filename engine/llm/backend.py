"""
LM Studio Backend Router
========================

Picks a transport per request and owns the retry for the empty-narration bug.

EVERY SERVER, ONE ROUTER (v0.19.0). What follows is the ``lmstudio`` provider
row's story (``engine/llm/providers.py``), and on that row every request,
probe and retry is v0.18's, pinned by the golden. Every other row has ONE chat
route (``route_client``): ``compat`` (vLLM, llama-server, a generic
OpenAI-compatible server) is ``LMSClient``; ``ollama_native`` is
``OllamaClient`` on ``/api/chat``, which also sends the bound context as
``num_ctx`` and translates the grammar to ``format`` (``engine/llm/ollama.py``).
The router reads the row for the rest: the structured-output ladder and its
``constraint_won`` probe (``structured_output``), the format block for a rung
with no grammar on the wire (``with_format_block``), the reasoning-off patch
and its trust (``client.reasoning_patch``), and a starvation retry that keeps
the grammar and never repeats a patched request (``_retry_on_compat``).

THE ROUTING RULE (the ``lmstudio`` row)
---------------------------------------
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

import json
import logging
import threading
from typing import Any, Callable, Generator, Optional

from engine.config import get_config
from engine.llm.client import (
    LMSClient,
    compat_cap,
    get_lms_client,
    reasoning_patch,
)
from engine.llm.events import LMSResponse, LMSStreamEvent
from engine.llm.gate import inference_slot
from engine.llm.lmstudio_native import NativeClient
from engine.llm.ollama import OllamaClient, get_ollama_client
from engine.llm.profiles import ModelProfile, resolve_profile
from engine.llm.providers import Provider, get_provider
from engine.locks import renew_after_fork

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


#: The rungs of the structured-output ladder (spec §4.1).
RUNG_SCHEMA = 1  # the full strict schema
RUNG_OBJECT = 2  # valid JSON, shape free
RUNG_NONE = 3  # no grammar on the wire

#: What a probe-less mode resolves to.
_MODE_RUNGS = {"json_schema": RUNG_SCHEMA, "json_object": RUNG_OBJECT, "off": RUNG_NONE}


def wire_form(token: str, schema: dict[str, Any]) -> dict[str, Any]:
    """
    One rung of the ladder, in the row's own wire form.

    ``token`` is one entry of ``Provider.structured_output``:

    * ``json_schema`` -- the full schema as OpenAI's ``response_format``;
    * ``json_schema_permissive`` -- LM Studio's ``json_object``: it rejects
      OpenAI's ``{"type": "json_object"}`` with 400 ``'response_format.type'
      must be 'json_schema' or 'text'``, so it is v0.18's permissive schema;
    * ``json_object`` -- ``{"type": "json_object"}``;
    * ``ollama_format_schema`` / ``ollama_format_json`` -- the OpenAI shapes of
      the same two rungs, which the Ollama transport translates to ``format``
      (``ollama.ollama_format``, spec §6), as it does a caller's own.
    """
    if token in ("json_schema", "ollama_format_schema"):
        return _response_format(schema)
    if token == "json_schema_permissive":
        return _response_format(
            {"type": "object", "additionalProperties": True}, name="json_object"
        )
    if token in ("json_object", "ollama_format_json"):
        return {"type": "json_object"}
    raise ValueError(f"no structured-output wire form named {token!r}")


#: The ``constraint_won`` probe's schema: the three constructs the turn schema
#: depends on -- ``enum``, ``anyOf`` and ``additionalProperties: false``.
CONSTRAINT_PROBE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"answer": {"anyOf": [{"type": "string", "enum": ["yes"]}]}},
    "required": ["answer"],
    "additionalProperties": False,
}
#: It asks for a value OUTSIDE that schema, so only an enforced grammar wins.
CONSTRAINT_PROBE_PROMPT = 'Reply with exactly {"answer": "no", "note": "free"}'
#: The rung-2 probe asks for prose; only a grammar makes it a JSON object.
OBJECT_PROBE_PROMPT = "In one sentence, say what colour the sky is at dusk."


class LMStudioBackend:
    """Routes chat requests to the native or OpenAI-compatible transport."""

    def __init__(
        self,
        *,
        compat: Optional[LMSClient] = None,
        native: Optional[NativeClient] = None,
        prefer_native: Optional[bool] = None,
        ollama: Optional[OllamaClient] = None,
    ) -> None:
        cfg = get_config()
        self._compat = compat or get_lms_client()
        self._native = native
        # Built on first use, and only on the `ollama_native` row.
        self._ollama = ollama
        self._prefer_native = (
            bool(cfg.get("llm.prefer_native", True))
            if prefer_native is None
            else prefer_native
        )
        self._native_available: Optional[bool] = None
        # v0.18's probe answer (the `lmstudio_v18` ladder), cached per process.
        self._structured_ok: Optional[bool] = None
        # Every other row's probed rung, cached per process.
        self._probed_rung: Optional[int] = None
        self._lock = threading.Lock()

    @staticmethod
    def provider() -> Provider:
        """The configured model server's row; every branch below reads it."""
        return get_provider()

    # -- transport selection -------------------------------------------------

    def _ollama_row(self) -> bool:
        return self.provider().chat_transport.value == "ollama_native"

    def route_client(self) -> Any:
        """
        The one chat route of a row that is not LM Studio's routed pair --
        ``OllamaClient`` on the ``ollama_native`` row, else ``LMSClient`` --
        and LM Studio's compat route. Both take ``LMSClient.chat``'s
        arguments; ``route_extras`` adds what only Ollama's takes.
        """
        if not self._ollama_row():
            return self._compat
        with self._lock:
            if self._ollama is None:
                self._ollama = get_ollama_client()
            return self._ollama

    def route_extras(self, mp: ModelProfile, label: str) -> dict[str, Any]:
        """
        ``/api/chat``'s own arguments: the bound context, ALWAYS sent as
        ``num_ctx`` (Ollama truncates a longer prompt from the front,
        silently, at its small default), and the caller's label, which a
        refused ``response_format`` names. Nothing on any other route, so
        LM Studio's calls are v0.18's.
        """
        if not self._ollama_row():
            return {}
        return {"context_length": mp.context_tokens, "label": label or mp.name}

    def server_available(self) -> bool:
        """
        Whether the configured model server can serve a turn: the row's
        health probe (spec §8), asked by the client that carries this row's
        turns -- ``OllamaClient`` on the ``ollama_native`` row, the compat
        client everywhere else (on LM Studio, v0.18's request). The
        summarizer's gate (``engine/scenes/default_state.py``).
        """
        return bool(self.route_client().is_available())

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

        The routing above is the ``lmstudio`` row's (``chat_transport:
        lmstudio_routed``). Every other row has one chat route
        (``route_client``: compat, or Ollama's ``/api/chat``) and never asks
        about ``/api/v1/chat``, which is LM Studio's alone -- and has no MCP
        integrations to carry (§7).
        """
        if self.provider().chat_transport.value != "lmstudio_routed":
            if integrations:
                logger.error(
                    "[backend] MCP integrations were requested, but %s has no "
                    "route that reads them -- only LM Studio's native API does "
                    "(operation=use_native). The model will answer with NO "
                    "tools.",
                    self.provider().title,
                )
            return False
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
        Build a ``response_format`` payload, honouring ``llm.structured_output``.

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

        THE LADDER (v0.19.0, spec §4.1). The modes above are rungs --
        ``json_schema`` (1), ``json_object`` (2), none (3) -- each sent in the
        provider row's own wire form (``wire_form``). On the ``lmstudio`` row
        every rung is exactly v0.18's. ``auto`` probes once per process, by
        the row's ``probe``: ``lmstudio_v18`` is the probe above, untouched,
        and a no means no grammar; ``constraint_won`` must see the grammar beat
        the prompt, and a server that fails it is asked for rung 2 before it
        lands on rung 3.
        """
        if not schema:
            return None
        return self.rung_format(self.structured_rung(), schema)

    def structured_mode(self) -> str:
        """``llm.structured_output``, lower-cased."""
        return str(get_config().get("llm.structured_output", "auto")).lower()

    def structured_rung(self) -> int:
        """
        The rung this process sends a schema on (1, 2 or 3).

        ``auto`` probes on first use and caches the answer, so ask this after
        ``structured_output`` has run for a real schema, never before one
        exists -- v0.18 probed only then, and the golden pins when.
        """
        mode = self.structured_mode()
        if mode in _MODE_RUNGS:
            return _MODE_RUNGS[mode]
        if mode != "auto":
            return RUNG_NONE  # v0.18: an unknown mode sent no grammar
        if self.provider().v18_ladder:
            return RUNG_SCHEMA if self._probe_structured_output() else RUNG_NONE
        return self._probe_ladder()

    def rung_format(self, rung: int, schema: dict[str, Any]) -> Optional[dict[str, Any]]:
        """``schema`` at ``rung``, in the configured row's wire form."""
        if rung == RUNG_NONE:
            return None
        tokens = tuple(self.provider().structured_output.value)
        return wire_form(tokens[0] if rung == RUNG_SCHEMA else tokens[1], schema)

    def caller_format(self, envelope: dict[str, Any]) -> Optional[dict[str, Any]]:
        """
        A grammar a caller built for itself -- the planner's (finding 4).

        On a v0.18-ladder row (LM Studio) it goes exactly as v0.18 sent it,
        whatever ``llm.structured_output`` says: the planner never lost its
        grammar there, including under ``off``, and the golden pins that
        (scenarios 09 and 10). On every other row it rides the ladder: the
        rung this process resolved, in the row's wire form, and on rung 3
        nothing -- the caller's own parse-failure path answers.
        """
        if self.provider().v18_ladder:
            return _response_format(envelope)
        return self.structured_output(envelope)

    def format_block_due(self) -> bool:
        """
        Whether a request carrying a schema also carries its format block (§4.2).

        Rungs 2 and 3 put no shape on the wire, so the prompt has to. On a
        v0.18-ladder row only an explicit ``off`` does: v0.18's ``json_object``
        rung and the turn after a failed probe are pinned byte for byte by
        the golden (scenarios 05 and 08), and ``off`` is the one sanctioned
        change (scenario 06).
        """
        rung = self.structured_rung()
        if rung == RUNG_SCHEMA:
            return False
        if self.provider().v18_ladder:
            return self.structured_mode() == "off"
        return True

    def with_format_block(
        self, messages: list[dict[str, Any]], schema: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """
        ``messages`` with the schema's format block appended to the system
        message when ``format_block_due``; otherwise ``messages`` unchanged.

        Appended to the LAST system message, after a blank line, so the
        native route's joined ``system_prompt`` grows by exactly the block.
        A request with no system message gains one, first.
        """
        if not schema or not self.format_block_due():
            return messages
        from engine.llm.schemas import render_format_block

        block = render_format_block(schema)
        out = [dict(m) for m in messages]
        for message in reversed(out):
            if message.get("role") == "system":
                message["content"] = f"{message.get('content') or ''}\n\n{block}"
                return out
        return [{"role": "system", "content": block}] + out

    def _probe_ladder(self) -> int:
        """
        The ``constraint_won`` probes: rung 1 if the grammar beat the prompt,
        else rung 2 if a ``json_object`` request came back as a JSON object,
        else rung 3. Cached for the process.
        """
        with self._lock:
            if self._probed_rung is not None:
                return self._probed_rung
        tokens = tuple(self.provider().structured_output.value)
        rung = RUNG_NONE
        if self._probe_constraint_won(wire_form(tokens[0], dict(CONSTRAINT_PROBE_SCHEMA))):
            rung = RUNG_SCHEMA
        elif self._probe_json_object(wire_form(tokens[1], dict(CONSTRAINT_PROBE_SCHEMA))):
            rung = RUNG_OBJECT
        logger.info(
            "[backend] Structured-output probe (operation=_probe_ladder, "
            "provider=%s, grammar=%s)",
            self.provider().name,
            {RUNG_SCHEMA: "json_schema", RUNG_OBJECT: "json_object"}.get(rung, "none"),
        )
        with self._lock:
            self._probed_rung = rung
        return rung

    def _probe_request(self, prompt: str, response_format: dict[str, Any]) -> str:
        """One probe request on the row's chat route; its content, or raises."""
        mp = resolve_profile("big")
        return self.route_client().chat(
            [{"role": "user", "content": prompt}],
            model=mp.model,
            temperature=0.0,
            max_tokens=200,
            # As v0.18's probe: pay for thinking, so a reasoning model does not
            # fail a probe about whether the SERVER supports grammars.
            reasoning_budget=mp.reasoning_budget,
            # And ask for none (v0.19.0 T8, measured): Ollama's qwen3:4b, sent
            # `think: true` under the probe's `format`, thought 13k characters
            # past a 3400-token cap and failed both probes -- a server that
            # enforces grammars landed on rung 3. With the grammar on the
            # request, `off` binds it from the first token even on a template
            # that ignores the patch (Ollama 0.34.4, llama-server b7966).
            reasoning="off",
            response_format=response_format,
            **self.route_extras(mp, "probe"),
        ).content

    def _probe_constraint_won(self, response_format: dict[str, Any]) -> bool:
        """
        Did the grammar beat the prompt?

        The prompt asks for ``{"answer": "no", "note": "free"}``; the schema
        allows only ``{"answer": "yes"}``. A server that accepts
        ``response_format`` and ignores it echoes the prompt and fails, which
        v0.18's ``'"ok"' in content`` check could not tell apart. A refusal
        (400) fails too.
        """
        try:
            content = self._probe_request(CONSTRAINT_PROBE_PROMPT, response_format)
            return json.loads(content.strip()) == {"answer": "yes"}
        except Exception as exc:  # noqa: BLE001 -- a failed probe means "no"
            logger.warning(
                "[backend] json_schema probe failed (operation=_probe_constraint_won, "
                "provider=%s): %s",
                self.provider().name,
                exc,
            )
            return False

    def _probe_json_object(self, response_format: dict[str, Any]) -> bool:
        """A prose question under ``json_object``: passes only as a JSON object."""
        try:
            content = self._probe_request(OBJECT_PROBE_PROMPT, response_format)
            return isinstance(json.loads(content.strip()), dict)
        except Exception as exc:  # noqa: BLE001 -- a failed probe means "no"
            logger.warning(
                "[backend] json_object probe failed (operation=_probe_json_object, "
                "provider=%s): %s",
                self.provider().name,
                exc,
            )
            return False

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
                result = self.route_client().chat(
                    messages,
                    model=mp.model,
                    temperature=temp,
                    max_tokens=cap,
                    reasoning_budget=mp.reasoning_budget,
                    tools=tools,
                    tool_choice=tool_choice,
                    response_format=response_format,
                    ttl=mp.ttl,
                    reasoning=mode,
                    **self.route_extras(mp, label or profile),
                )

        if retry_on_starvation and result.starved_by_reasoning:
            recovered = self._retry_without_reasoning(
                messages,
                mp,
                cap=cap,
                temperature=temp,
                label=label,
                starved=result,
                response_format=response_format,
                tools=tools,
                tool_choice=tool_choice,
                reasoning=mode,
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
        starved: Optional[LMSResponse] = None,
        response_format: Optional[dict[str, Any]] = None,
        tools: Optional[list[dict[str, Any]]] = None,
        tool_choice: Optional[str] = None,
        reasoning: Optional[str] = None,
    ) -> Optional[LMSResponse]:
        """
        Second attempt with reasoning switched off.

        On LM Studio only the native transport can do this. On its
        OpenAI-compatible endpoint every reasoning control is ignored, so a
        retry there would starve exactly the same way and cost the player
        another full generation.

        On every other row -- ``compat`` and Ollama's ``/api/chat`` alike (spec
        §5.3) -- the route that starved is also the route that can say
        ``off``: the retry is the SAME request -- same
        ``response_format``, so the grammar survives the retry, which LM
        Studio cannot offer -- plus the provider's patch, IF the starved
        request did not already carry it. A request that starved WITH the
        patch is never repeated: ``_retry_with_room``, else stand down.
        """
        if self.provider().chat_transport.value != "lmstudio_routed":
            return self._retry_on_compat(
                messages,
                mp,
                cap=cap,
                temperature=temperature,
                label=label,
                starved=starved,
                response_format=response_format,
                tools=tools,
                tool_choice=tool_choice,
                reasoning=str(reasoning or mp.reasoning),
            )

        if not self.native_available():
            logger.error(
                "[backend] Cannot recover from reasoning starvation: the native "
                "API is unavailable and the OpenAI-compatible endpoint cannot "
                "disable reasoning (operation=_retry_without_reasoning, model=%s)",
                mp.model,
            )
            return None

        # The model has to be ABLE to stop thinking. 30 of the 42 LLMs measured
        # on the author's machine publish no reasoning block, and this retry
        # used to send them `reasoning="off"` regardless -- a 400 that the
        # planner turned into a silent agent, so a two-agent story ran on one.
        #
        # Standing down rather than retrying anyway is the same argument the
        # branch above makes about the OpenAI-compatible endpoint. Worse here:
        # `wire_cap` returns the content budget UNCHANGED when reasoning is off,
        # so a second attempt would carry 320 tokens where the starved first
        # attempt carried 3,520, and a model that thinks whatever you ask it
        # cannot do better with less.
        from engine.llm.registry import get_registry

        info = get_registry().cached(mp.model)
        if info is not None and not info.accepts_reasoning("off"):
            return self._retry_with_room(
                messages, mp, cap=cap, temperature=temperature, label=label,
                starved=starved,
            )

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

    def recover_starved(
        self,
        messages: list[dict[str, Any]],
        *,
        profile: str = "big",
        response_format: Optional[dict[str, Any]] = None,
        starved: Optional[LMSResponse] = None,
        reasoning: Optional[str] = None,
        label: str = "",
    ) -> Optional[LMSResponse]:
        """
        Recover a STREAMED request that starved (spec §5.3), once.

        The storyteller streams narration, so the non-streamed ``chat``'s own
        retry never sees that starvation; this is its recovery, and it keeps
        the same rules:

        * on LM Studio (``lmstudio_routed``) it is v0.18's call, byte for
          byte: one non-streamed request with ``reasoning="off"``, the grammar
          kept (golden 16);
        * on any other row (compat, or Ollama's ``/api/chat``) it is
          ``_retry_on_compat``, given the mode the
          stream ran in: the same request plus the provider's patch if the
          stream lacked it, and never the identical request again -- a stream
          that already carried the patch, or a row with no patch at all, gets
          measured room or stands down.

        Args:
            reasoning: The mode the starved stream ran in (the profile's when
                None).

        Returns:
            The recovered response, or None when it stood down.
        """
        mp = resolve_profile(profile)
        if self.provider().chat_transport.value == "lmstudio_routed":
            return self.chat(
                messages,
                profile=profile,
                reasoning="off",
                response_format=response_format,
                label=label or f"{profile}:recover",
                retry_on_starvation=False,
            )
        return self._retry_on_compat(
            messages,
            mp,
            cap=int(mp.max_tokens),
            temperature=float(mp.temperature),
            label=label or f"{profile}:recover",
            starved=starved,
            response_format=response_format,
            tools=None,
            tool_choice=None,
            reasoning=str(reasoning or mp.reasoning),
        )

    def _retry_on_compat(
        self,
        messages: list[dict[str, Any]],
        mp: ModelProfile,
        *,
        cap: int,
        temperature: float,
        label: str,
        starved: Optional[LMSResponse],
        response_format: Optional[dict[str, Any]],
        tools: Optional[list[dict[str, Any]]],
        tool_choice: Optional[str],
        reasoning: str,
    ) -> Optional[LMSResponse]:
        """
        The §5.3 retry on every row but LM Studio's: the patch once, never
        twice. On Ollama the patch is ``think: false`` on the same
        ``/api/chat`` request, same ``format`` and ``num_ctx``.
        """
        carried_patch = reasoning_patch(mp.model, reasoning)
        carried = carried_patch is not None
        patch = None if carried else reasoning_patch(mp.model, "off")
        if patch is None:
            return self._retry_with_room(
                messages,
                mp,
                cap=cap,
                temperature=temperature,
                label=label,
                starved=starved,
                response_format=response_format,
                tools=tools,
                tool_choice=tool_choice,
                patched=carried,
                patch_trusted=bool(carried_patch is not None and carried_patch.trusted),
            )
        logger.warning(
            "[backend] Retrying with the reasoning-off patch after starvation, "
            "grammar kept (operation=_retry_on_compat, provider=%s, model=%s, "
            "patch_trusted=%s, content_budget=%s, reasoning_budget=%s)",
            self.provider().name,
            mp.model,
            patch.trusted,
            cap,
            mp.reasoning_budget,
        )
        with inference_slot(label=f"{label or mp.name}:retry", lane=mp.lane):
            return self.route_client().chat(
                messages,
                model=mp.model,
                temperature=temperature,
                max_tokens=cap,
                reasoning_budget=mp.reasoning_budget,
                tools=tools,
                tool_choice=tool_choice,
                response_format=response_format,
                ttl=mp.ttl,
                reasoning="off",
                **self.route_extras(mp, f"{label or mp.name}:retry"),
            )

    def _retry_with_room(
        self,
        messages: list[dict[str, Any]],
        mp: ModelProfile,
        *,
        cap: int,
        temperature: float,
        label: str,
        starved: Optional[LMSResponse],
        response_format: Optional[dict[str, Any]] = None,
        tools: Optional[list[dict[str, Any]]] = None,
        tool_choice: Optional[str] = None,
        patched: bool = False,
        patch_trusted: bool = False,
    ) -> Optional[LMSResponse]:
        """
        Second attempt for a model that CANNOT be told to stop thinking.

        ``patched`` says the starved request already carried the provider's
        reasoning-off patch (``_retry_on_compat``), and ``patch_trusted``
        whether that patch was trusted (a declaration listed ``off``); they
        decide only what the stand-down log advises.

        30 of the 42 LLMs measured on the author's machine publish no reasoning
        block, and lfm2.5 is the awkward kind: it thinks hard and offers no
        knob. Asking it for ``reasoning="off"`` was a 400 the planner turned
        into a silent agent -- a two-agent story running on one, with nothing
        failing anywhere.

        Simply standing down is not enough either, and neither is repeating the
        call: ``wire_cap`` returns the content budget UNCHANGED when reasoning
        is off, so the old retry would have carried 320 tokens where the attempt
        that starved carried 3,520.

        THE ROOM IS MEASURED, NOT GUESSED. The starved response reports exactly
        what the model spent thinking, so the retry asks for that much again
        plus the full content budget. No magic multiplier: the number comes from
        what this model just did with this prompt. With no measurement there is
        nothing to size the retry from, and it stands down rather than spend a
        player's turn on a coin flip.
        """
        routed = self.provider().chat_transport.value == "lmstudio_routed"
        spent = int(getattr(starved, "reasoning_tokens", 0) or 0)
        if spent <= 0:
            if routed:
                logger.error(
                    "[backend] Cannot recover from reasoning starvation: this model "
                    "exposes no reasoning configuration and the starved response "
                    "reported no reasoning tokens, so there is nothing to size a "
                    "retry from (operation=_retry_with_room, model=%s). Raise "
                    "llm.profiles.*.max_tokens, or load a model that exposes "
                    "the knob.",
                    mp.model,
                )
            elif not str(getattr(starved, "reasoning_content", "") or "").strip() and (
                int(getattr(starved, "output_tokens", 0) or 0) <= 0
            ):
                # Nothing thought, nothing said and nothing spent: not
                # starvation at all, but a response that ended with neither
                # channel and no token count -- most often a stream cut before
                # its done line (ollama.py warns about that one), or a server
                # that answered empty. No declaration fixes a dropped
                # connection, so none is advised. (A model that thinks in a
                # channel the server hides still reports the tokens it spent,
                # and is advised below.)
                logger.error(
                    "[backend] The response came back with no content AND no "
                    "reasoning -- a stream that ended without its done line, or "
                    "an empty answer -- so there is no thinking to make room for "
                    "and nothing is retried (operation=_retry_with_room, "
                    "provider=%s, model=%s, patch_sent=%s). Check the server's "
                    "own log for why it stopped.",
                    self.provider().name,
                    mp.model,
                    patched,
                )
            elif patched and not patch_trusted:
                # It thought through an UNTRUSTED patch (an undeclared model,
                # v0.19.0 T8): the cap already kept the reasoning budget, so
                # marking it untrusted would change nothing. Only room, or a
                # template that honours the patch, can help.
                logger.error(
                    "[backend] Cannot recover from reasoning starvation: the "
                    "request already carried the reasoning-off patch, untrusted "
                    "(the model is undeclared, so the cap already kept its "
                    "reasoning budget), and the model thought through all of it; "
                    "the response reported no reasoning tokens to size a retry "
                    "from, and a patched request is never repeated "
                    "(operation=_retry_with_room, provider=%s, model=%s). Raise "
                    "llm.profiles.*.max_tokens or reasoning_budget, or use a "
                    "model whose chat template honours the patch.",
                    self.provider().name,
                    mp.model,
                )
            elif patched:
                # It thought, WITH a trusted patch on: the patch did not take.
                # A declaration cannot make it take; only room can.
                logger.error(
                    "[backend] Cannot recover from reasoning starvation: the "
                    "request already carried the reasoning-off patch and the "
                    "model thought anyway, and the response reported no "
                    "reasoning tokens to size a retry from; a patched request "
                    "is never repeated (operation=_retry_with_room, provider=%s, "
                    "model=%s). Raise llm.profiles.*.max_tokens, or set "
                    "llm.declared_models.<id>.reasoning_off_trusted: false so "
                    "the cap keeps the reasoning budget.",
                    self.provider().name,
                    mp.model,
                )
            else:
                # It thought, and no patch was available to send: a
                # declaration is what would give it one (spec §5.3).
                logger.error(
                    "[backend] Cannot recover from reasoning starvation: the "
                    "starved response reported no reasoning tokens, so there is "
                    "nothing to size a retry from, and this model has no "
                    "reasoning-off patch to send (operation=_retry_with_room, "
                    "provider=%s, model=%s). Declare the model's `reasoning` in "
                    "llm.declared_models (so the patch is sent and the cap "
                    "right), declare llm.reasoning_off_body on a generic "
                    "server, or raise llm.profiles.*.max_tokens.",
                    self.provider().name,
                    mp.model,
                )
            return None

        room = spent + max(1, cap)
        logger.warning(
            "[backend] Retrying with measured room after starvation: this model "
            "cannot be told to stop thinking, so the answer is given space "
            "BESIDE the thinking rather than instead of it "
            "(operation=_retry_with_room, model=%s, reasoning_spent=%s, "
            "content_budget=%s, new_cap=%s)",
            mp.model,
            spent,
            cap,
            room,
        )
        if not routed:
            with inference_slot(label=f"{label or mp.name}:room", lane=mp.lane):
                return self.route_client().chat(
                    messages,
                    model=mp.model,
                    temperature=temperature,
                    max_tokens=room,
                    reasoning_budget=0,
                    tools=tools,
                    tool_choice=tool_choice,
                    response_format=response_format,
                    ttl=mp.ttl,
                    **self.route_extras(mp, f"{label or mp.name}:room"),
                )
        with inference_slot(label=f"{label or mp.name}:room", lane=mp.lane):
            return self.native_client().chat(
                messages,
                model=mp.model,
                temperature=temperature,
                # The whole ceiling, with the reasoning it will spend anyway
                # already inside it. The `reasoning` key itself is omitted on
                # the wire for this model -- see native.reasoning_for.
                max_tokens=room,
                reasoning=mp.reasoning,
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
            generator = self.route_client().chat_stream(
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
                reasoning=mode,
                **self.route_extras(mp, profile),
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

    from engine import net
    from engine.llm.client import strip_inline_think
    from engine.llm.routes import COMPAT_CHAT_PATH, OLLAMA_CHAT_PATH, compat_base, route_url

    cfg = get_config()
    row = get_provider()
    # The diagnostic post goes to the route this row's turns use. On every
    # row but Ollama's that is the OpenAI-compatible route, deliberately:
    # /v1/chat/completions is genuinely served on LM Studio (unlike
    # /v1/models) and is the only one there that takes tools and structured
    # output, which is what the game's real path uses. On Ollama's it is
    # /api/chat, in Ollama's own shape (v0.19.0): the compat route is one the
    # engine never uses there, so its answer would diagnose nothing.
    native_ollama = row.chat_transport.value == "ollama_native"
    url = route_url(OLLAMA_CHAT_PATH) if native_ollama else f"{compat_base()}{COMPAT_CHAT_PATH}"
    key = str(cfg.get("llm.api_key", "") or "")
    headers = {"Authorization": f"Bearer {key}"} if key else {}

    mp = resolve_profile(profile)
    result: dict[str, Any] = {
        "ok": False,
        "status": "unreachable",
        "detail": "",
        "model": mp.model,
        "bound": mp.bound,
        "transport": "ollama" if native_ollama else "openai",
        "latency_ms": 0.0,
        "content": "",
    }

    # A model id the server never confirmed is a guaranteed 400. Say so before
    # spending a request proving it.
    if not mp.bound:
        result["detail"] = (
            f"model {mp.model!r} was never confirmed against the server -- "
            "discovery failed, so every chat request names a model "
            f"{get_provider().title} has never heard of"
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
    # Raw post: reasoning is not turned off here, so the budget for it is
    # granted. A diagnostic that starves where the product does not is a
    # diagnostic that lies.
    cap = compat_cap(max_tokens, mp.reasoning_budget)
    payload: dict[str, Any]
    if native_ollama:
        payload = {
            "model": mp.model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": 0.0, "num_predict": cap},
        }
    else:
        payload = {
            "model": mp.model,
            "messages": messages,
            "temperature": 0.0,
            "max_tokens": cap,
            "stream": False,
        }

    t0 = time.perf_counter()
    try:
        response = net.post(url, json=payload, headers=headers, timeout=timeout)
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
        if native_ollama:
            message = data.get("message") or {}
        else:
            message = ((data.get("choices") or [{}])[0].get("message") or {})
        content = str(message.get("content") or "")
    except Exception as exc:  # noqa: BLE001 -- a 200 that is not JSON is its own answer
        result["status"] = "http"
        result["detail"] = f"200 but unreadable: {exc}"
        return result
    if row.inline_think.value == "strip":
        # Thinking sent inside content is not an answer (§4.5).
        content, _ = strip_inline_think(content, "")
    content = content.strip()

    result["content"] = content
    if not content:
        # The empty-narration bug, seen from outside. A 200 with no content is
        # the shape a reasoning model returns when it spent the budget thinking.
        result["status"] = "empty"
        result["detail"] = (
            "HTTP 200 with an empty content channel, on the real path AND on a "
            "plain retry -- the model spends its whole budget reasoning. Set "
            f"llm.profiles.{profile}.reasoning: off, or raise its "
            f"reasoning_budget (now {mp.reasoning_budget}) so thinking has room "
            "of its own instead of taking the answer's."
        )
        return result

    result["ok"] = True
    result["status"] = "ok"
    result["detail"] = f"{content[:60]!r} in {result['latency_ms']:.0f}ms"
    return result


#: The router serves every provider row, so this is its provider-neutral name.
#: ``LMStudioBackend`` -- like the ``LMS`` prefix of ``LMSClient``,
#: ``LMSResponse`` and ``LMSStreamEvent`` -- is historical: the package was
#: ``engine/lmstudio/`` until v0.19.0 and the classes keep their names.
LLMBackend = LMStudioBackend


_backend: Optional[LMStudioBackend] = None
_backend_lock = threading.Lock()
renew_after_fork(globals(), _backend_lock=threading.Lock)


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
