"""
Model-server providers
======================

The capability matrix, as code: one ``Provider`` row per model server this
build speaks, one ``Cell`` per fact about that server (spec §1.2).

A ROW, NOT A SUBCLASS. Every cell is a fact about someone else's server, and
each can be pinned by a fixture. The backend, the clients, discovery, the stack
and the doctor read a capability from the row -- ``get_provider().probe.value``
-- and never branch on the provider's name. A subclass per server would spread
the same facts over five overrides of the same six methods.

THE TABLE IS ALSO THE DOCUMENTATION. ``docs/MODEL_SERVERS.md`` is written by
hand and carries the same matrix; ``tests/test_llm_providers_table.py`` holds
the two together cell by cell, so neither can drift from the other.

HOW A FACT IS VERIFIED. A cell measured against a live server carries
``verified="<server> <version>"``. A cell taken from the server's documentation
carries ``verified=""``, and the document flags it as unverified. LM Studio's
row is v0.18's behaviour, measured live through v0.18 and pinned request by
request by the golden (``tests/test_llm_golden_lmstudio.py``). llama-server's
and Ollama's were measured live in v0.19.0 (``_LLAMACPP``, ``_OLLAMA``), bar
the cells those constants' comments name, and vLLM's in v0.20.0 (``_VLLM``,
in its Linux image). The generic server's have no one server to be verified on.

WHAT READS WHICH CELL:

* the table's keys -- ``engine/config.py``, which refuses an ``llm.provider``
  that is not one of them;
* ``discovery`` -- ``engine/llm/discovery.py``, through
  ``ModelRegistry.refresh`` and ``registry.probe_models``;
* ``default_base_url`` -- the tests' live-call guard (``tests/conftest.py``)
  and docs/MODEL_SERVERS.md; the engine dials ``llm.base_url``, which the
  owner sets beside ``llm.provider``;
* the request shaping (``backend.py``, ``client.py`` and ``ollama.py``):
  ``chat_transport`` (LM Studio's routing, one
  compat route, or Ollama's ``/api/chat``), ``structured_output`` and
  ``probe`` (the ladder and its probe), ``reasoning_off`` and
  ``grammar_and_reasoning_off_together`` (``reasoning_off_patch``),
  ``inline_think`` and ``keep_alive``;
* ``health`` --``Provider.health_probe``, which
  ``LMSClient.is_available`` and ``OllamaClient.is_available`` (the
  summarizer's gate), the stack's model-server service, ``launcher.py`` and
  ``scripts/doctor.py`` all ask;
* ``mcp_integrations`` --``engine/agents/mechanics.py::mechanics_enabled``,
  the MCP gate, and the doctor's MCP row. ``auth``, ``inline_tools`` and
  ``context_control`` are descriptive: every row's client already sends a
  bearer key when one is set and ``tools=`` where a caller passes them, and
  the one ``per_request`` row's transport (Ollama's) always sends the bound
  context as ``num_ctx``.

Nothing here is a content decision: a provider carries transport facts only
(AGENTS.md rule 12).

Version: v0.1.0 [2026-09-29]
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from engine.llm.routes import (
    CHAT_PATH,
    HEALTH_PATH,
    LLAMACPP_PROPS_PATH,
    MODELS_PATH,
    OLLAMA_CHAT_PATH,
    OLLAMA_PS_PATH,
    OLLAMA_SHOW_PATH,
    OLLAMA_TAGS_PATH,
    OLLAMA_VERSION_PATH,
    OPENAI_MODELS_PATH,
)


@dataclass(frozen=True)
class ReasoningPatch:
    """
    A body fragment that turns reasoning off on one route (spec §5.1).

    ``trusted`` says whether anything may RELY on it: only a trusted patch lets
    the wire cap drop the reasoning budget (§5.2). An untrusted one is sent --
    it costs nothing and may help -- with the full "on" cap beside it.
    """

    body: dict[str, Any]
    trusted: bool = False


@dataclass(frozen=True)
class Cell:
    """
    One fact about one server.

    ``value`` is what the engine reads; ``note`` is the human half (the server
    flag it needs, the condition it holds under); ``verified`` names the server
    and version it was measured against, or is empty when the fact comes from
    that server's documentation.
    """

    value: Any
    note: str = ""
    verified: str = ""


#: The capability fields of a row, in the spec's (and the document's) order.
FIELDS: tuple[str, ...] = (
    "chat_transport",
    "structured_output",
    "probe",
    "reasoning_off",
    "grammar_and_reasoning_off_together",
    "inline_think",
    "discovery",
    "keep_alive",
    "context_control",
    "auth",
    "inline_tools",
    "mcp_integrations",
    "health",
    "default_base_url",
)


@dataclass(frozen=True)
class Provider:
    """One model server's row. Every capability field is a ``Cell``."""

    #: The ``llm.provider`` value.
    name: str
    #: How a person names the server, for messages and the doctor.
    title: str
    #: What to do about a 401, for a status line or an error: identity data,
    #: like ``title``, so no message branches on the provider's name.
    #: LM Studio's is v0.18's wording, byte for byte.
    key_hint: str
    #: What the doctor's key row says when no key is set: identity data, like
    #: ``key_hint``. LM Studio's is v0.18's wording, byte for byte.
    key_missing: str
    chat_transport: Cell
    structured_output: Cell
    probe: Cell
    reasoning_off: Cell
    grammar_and_reasoning_off_together: Cell
    inline_think: Cell
    discovery: Cell
    keep_alive: Cell
    context_control: Cell
    auth: Cell
    inline_tools: Cell
    mcp_integrations: Cell
    health: Cell
    default_base_url: Cell
    #: The doctor's section name, when it is not ``Model server (<name>)``:
    #: identity data, like ``title``. LM Studio's is v0.18's, byte for byte.
    doctor_section: str = ""
    #: What to do about thinking sent inside ``content`` (the doctor's
    #: ``inline <think>`` WARN): identity data, the server flag as advice.
    #: Empty for a server with no such flag.
    inline_think_fix: str = ""

    @property
    def section(self) -> str:
        """The doctor's section for this server (spec §8)."""
        return self.doctor_section or f"Model server ({self.name})"

    def cells(self) -> dict[str, Cell]:
        """Every capability cell, by field name, in ``FIELDS`` order."""
        return {name: getattr(self, name) for name in FIELDS}

    @property
    def v18_ladder(self) -> bool:
        """
        Whether this row's structured output is v0.18's, whole.

        The ``lmstudio_v18`` probe names more than a probe: it is v0.18's
        ladder. A failed probe means no grammar (no ``json_object`` second
        probe), the permissive ``json_schema`` rung and the turn after a failed
        probe go on the wire exactly as v0.18 sent them, and a caller that
        builds its own grammar (the planner) keeps it whatever
        ``llm.structured_output`` says. The golden pins all of it.
        """
        return self.probe.value == "lmstudio_v18"

    def reasoning_off_patch(
        self, model_info: Any, route: str
    ) -> Optional["ReasoningPatch"]:
        """
        The body fragment that turns thinking off on ``route``, or None (§5.1).

        Read from the row, never from its name:

        * a row whose grammar route cannot also carry reasoning off
          (``grammar_and_reasoning_off_together: no``, LM Studio) has no patch
          on ``compat``: that route ignores every knob. Its native route is
          ``native.reasoning_for``'s, unchanged;
        * a model whose server REPORTS its knob (LM Studio's list, Ollama's
          ``thinking`` capability) gets the row's patch only if it accepts
          ``off``. LM Studio's is trusted: its list names the options the
          model takes. Ollama's is NOT, unless a declaration lists ``off``:
          ``thinking`` says a knob exists, not that the template honours
          ``think: false`` (measured, T8 -- ``discovery.NARROWS_REASONING``);
        * a model a DECLARATION sized (``declared_fields`` has ``reasoning``)
          gets the patch, trusted, only if the declaration lists ``off``;
          one that excludes ``off`` gets None;
        * an undeclared model gets the row's patch UNTRUSTED -- a template
          that lacks the variable ignores it, so the wire cap may not rely on
          it (§5.2), and the client reads its answer knowing the thinking may
          arrive in the content (``InlineThinkSplitter(forced_open=True)``).
          A verified ``reasoning_off`` cell does NOT make it trusted: the cell
          says the SERVER passes the patch to the template, and whether the
          template honours it is the model's (measured on llama-server b7966:
          Qwen3-0.6B's does, Qwen3-4B-Thinking-2507's does not);
        * a row with no patch of its own (``openai_compat``) sends
          ``llm.reasoning_off_body`` when the owner declared one, trusted,
          and otherwise nothing.

        Args:
            model_info: The bound model's ``ModelInfo`` from the registry's
                cache, or None when nothing was measured.
            route: ``compat`` or ``native``.
        """
        if route == "compat" and self.grammar_and_reasoning_off_together.value == "no":
            return None

        body = self.reasoning_off.value
        if not body:
            from engine.config import get_config

            declared_body = get_config().get("llm.reasoning_off_body", {}) or {}
            if not isinstance(declared_body, dict) or not declared_body:
                return None
            body = declared_body
            owner_declared = True
        else:
            owner_declared = False

        from engine.llm.discovery import NARROWS_REASONING, REPORTS_CAPABILITIES

        source = str(getattr(model_info, "source", "") or "")
        if model_info is not None and source in REPORTS_CAPABILITIES:
            if not model_info.accepts_reasoning("off"):
                return None
            if source in NARROWS_REASONING and "reasoning" not in tuple(
                getattr(model_info, "declared_fields", ()) or ()
            ):
                # Ollama's `thinking` says only that a knob exists. Measured
                # (Ollama 0.34.4, v0.19.0 T8): qwen3:4b -- the library's own
                # tag, a Thinking-2507 build -- reports it and ignores
                # `think: false`, thinking into the answer. Trusted only when a
                # declaration lists `off`.
                return ReasoningPatch(dict(body), trusted=False)
            return ReasoningPatch(dict(body), trusted=not _declared_untrusted(model_info))
        if model_info is None and self.discovery.value in REPORTS_CAPABILITIES:
            # A server that reports the knob answers 400 to it on a model
            # without one; with nothing measured, nothing is sent.
            return None

        declared = "reasoning" in tuple(getattr(model_info, "declared_fields", ()) or ())
        if declared:
            if not model_info.accepts_reasoning("off"):
                return None
            return ReasoningPatch(dict(body), trusted=not _declared_untrusted(model_info))
        return ReasoningPatch(
            dict(body), trusted=owner_declared and not _declared_untrusted(model_info)
        )

    def health_probe(
        self,
        base_url: Optional[str] = None,
        *,
        api_key: Optional[str] = None,
        timeout: float = 3.0,
    ) -> tuple[bool, str]:
        """
        Is this server up and able to serve a turn? The row's ``health`` cell,
        asked in order (spec §8).

        Each path in the cell is one question, and the first "no" is the
        answer:

        * the row's discovery LIST (LM Studio's ``/api/v1/models``, the
          OpenAI list, Ollama's ``/api/tags``) goes through
          ``registry.probe_models``: answered, authenticated, that server's
          list SHAPE, at least one model. On LM Studio this is the only path,
          and the request and every detail line are v0.18's (the golden,
          scenarios 20 and 23);
        * ``/health`` (vLLM, llama-server) must answer 200 without an error
          body, and a ``status`` in it must be ``ok``. A 503 is a server that
          is up and still LOADING its model: down, with a detail that says
          ``loading`` (llama-server, while ``-m`` loads);
        * ``/api/version`` (Ollama) must answer ``{"version": "..."}``.

        A 200 is never enough on its own: a server can answer a route it does
        not own with 200 and an error body (routes.py, measured on LM Studio).

        The bearer key: ``api_key`` when given (a client's own), else
        ``llm.api_key`` -- and then only when ``base_url`` is the configured
        server's origin, so the key never leaves for another host.

        Returns:
            ``(ok, detail)``, detail written to be read in a status table.
        """
        from engine.llm.discovery import LIST_PATHS
        from engine.llm.registry import probe_models
        from engine.llm.routes import route_url, same_origin

        if api_key is None and base_url and not same_origin(route_url("", base_url)):
            api_key = ""
        list_path = LIST_PATHS[self.discovery.value]
        ok, detail = False, "no health check declared"
        for path in tuple(self.health.value):
            url = route_url(path, base_url)
            if path == list_path:
                ok, detail = probe_models(
                    url, api_key=api_key, timeout=timeout, provider=self.name
                )
            else:
                ok, detail = self._liveness(path, url, api_key=api_key, timeout=timeout)
            if not ok:
                return False, detail
        return ok, detail

    def _liveness(
        self, path: str, url: str, *, api_key: Optional[str], timeout: float
    ) -> tuple[bool, str]:
        """One non-list health route, by its shape (``health_probe``)."""
        import httpx

        from engine.config import get_config
        from engine.llm.registry import _refused_key_detail

        key = str(get_config().get("llm.api_key", "") or "") if api_key is None else api_key
        headers = {"Authorization": f"Bearer {key}"} if key else {}
        try:
            response = httpx.get(url, headers=headers, timeout=timeout)
        except httpx.HTTPError as exc:
            return False, f"{url} unreachable ({type(exc).__name__})"
        if response.status_code == 401:
            return False, _refused_key_detail(self)
        if response.status_code == 503:
            return False, (
                f"loading: {url} answers 503 -- {self.title} is up and still "
                "loading its model; try again once it has"
            )
        if response.status_code >= 400:
            return False, f"HTTP {response.status_code} from {url}"
        try:
            body = response.json() if response.content.strip() else None
        except ValueError:
            body = None
        if isinstance(body, dict) and (body.get("error") or body.get("object") == "error"):
            # `{"error": ...}`, or vLLM's OpenAI-shaped `{"object": "error"}`.
            return False, f"{url} answered 200 with an error body -- it does not serve this route"
        return _LIVENESS_SHAPES[path](url, body)

    def empty_model_list(self) -> dict[str, Any]:
        """
        This server's model list with nothing in it, in its own shape.

        What a server with no models installed answers on the discovery route
        -- and what the tests' discovery pin answers with, so every test runs
        the engine's own no-models path for whichever provider is configured.
        """
        from engine.llm.discovery import empty_model_list

        return empty_model_list(self.discovery.value)


def _declared_untrusted(model_info: Any) -> bool:
    """
    Whether ``llm.declared_models.<id>.reasoning_off_trusted`` is ``false``.

    The owner's word that this model may IGNORE its reasoning-off patch,
    whatever the server or a declaration says about the knob: the patch is
    still sent, but the wire cap keeps the reasoning budget (§5.2), and a
    request that starves with it on is never repeated (§5.3). Absent, nothing
    changes.
    """
    model_id = str(getattr(model_info, "id", "") or "")
    if not model_id:
        return False
    from engine.config import get_config

    declared = get_config().get("llm.declared_models", {}) or {}
    entry = declared.get(model_id) if isinstance(declared, dict) else None
    return isinstance(entry, dict) and entry.get("reasoning_off_trusted") is False


def _health_body(url: str, body: Any) -> tuple[bool, str]:
    """
    ``/health``: vLLM answers 200 with an empty body, llama-server with
    ``{"status": "ok"}``. Any other ``status`` is not ready (an older
    llama-server said ``"loading model"`` here).
    """
    if isinstance(body, dict) and "status" in body:
        status = str(body.get("status") or "")
        if status != "ok":
            prefix = "loading: " if "load" in status.lower() else ""
            return False, f"{prefix}{url} answers status {status!r}, not 'ok'"
    return True, f"{url} answers: ok"


def _version_body(url: str, body: Any) -> tuple[bool, str]:
    """``/api/version``: Ollama's ``{"version": "..."}``, and nothing else."""
    if isinstance(body, dict) and isinstance(body.get("version"), str):
        return True, f"{url} answers: version {body['version']}"
    return False, f"{url} answered 200, but not with Ollama's {{\"version\": ...}}"


#: The liveness routes of the ``health`` cells, each checked by its own shape.
_LIVENESS_SHAPES = {
    HEALTH_PATH: _health_body,
    OLLAMA_VERSION_PATH: _version_body,
}


# -- the rows -----------------------------------------------------------------

#: LM Studio's row is v0.18, and the golden holds it there.
_LMS = "LM Studio 0.3"
#: llama-server, run live in v0.19.0 T8 on the owner's workstation (Windows,
#: the Vulkan build): Qwen3-4B-Thinking-2507, Qwen3-0.6B and Phi-3.1-mini, the
#: fixtures under tests/fixtures/llm/llamacpp/ and tests/test_llm_live.py.
#: `mcp_integrations` stays unverified: nothing there was measured.
_LLAMACPP = "llama.cpp server b7966"
#: Ollama, run live in v0.19.0 T8 (the portable Windows build, CUDA on the
#: RTX 2060): qwen3:4b from the library and a GGUF imported by a Modelfile.
#: `auth`'s pass-through (no proxy was run) and `mcp_integrations` stay
#: unverified.
_OLLAMA = "Ollama 0.34.4"
#: vLLM, run live in v0.20.0 T19: the `vllm/vllm-openai:v0.31.0` image under
#: Docker Desktop's WSL2 backend, the GPU an RTX 2060 (sm_75: the V1 engine,
#: the TRITON_ATTN backend, `--dtype half`), Qwen/Qwen3-1.7B. The fixtures
#: under tests/fixtures/llm/vllm/ and tests/test_llm_live.py.
#: `mcp_integrations` stays unverified: nothing there was measured.
_VLLM = "vLLM 0.31.0"

_COMPAT_JSON = ("json_schema", "json_object")
_THINKING_OFF = {"chat_template_kwargs": {"enable_thinking": False}}
#: Every server but LM Studio: the key the server was started with
#: (``--api-key``, or whatever sits in front of it), in the secrets chain.
_KEY_HINT = (
    "Put the key the server was started with in llm_api_key.txt, "
    "or set llm.api_key in config/local.yaml (docs/MODEL_SERVERS.md)"
)


def _key_missing(title: str) -> str:
    """Every server but LM Studio: the doctor's line for a key that is not set."""
    return f"not set - fine only if {title} was started without one (docs/MODEL_SERVERS.md)"


PROVIDERS: dict[str, Provider] = {
    "lmstudio": Provider(
        name="lmstudio",
        title="LM Studio",
        key_hint=(
            "Set llm.api_key in config/local.yaml, or turn off "
            "'Require API key' in LM Studio's server settings"
        ),
        key_missing="not set - fine only if LM Studio's 'Require API key' is off",
        chat_transport=Cell(
            "lmstudio_routed",
            f"native {CHAT_PATH} when possible, compat for grammar and tools (v0.18's rule)",
            _LMS,
        ),
        structured_output=Cell(
            ("json_schema", "json_schema_permissive"),
            "response_format on compat; LM Studio rejects json_object, "
            "so it goes as a permissive json_schema",
            _LMS,
        ),
        probe=Cell("lmstudio_v18", "the {ok: boolean} probe, byte-identical", _LMS),
        reasoning_off=Cell(
            {"reasoning": "off"},
            "native only, where the registry says the model accepts it; compat ignores every knob",
            _LMS,
        ),
        grammar_and_reasoning_off_together=Cell(
            "no", "the root cause of the two-minute turn", _LMS
        ),
        inline_think=Cell("pass", "the server splits reasoning out itself", _LMS),
        discovery=Cell("lmstudio_v1", f"GET {MODELS_PATH}, shape-checked", _LMS),
        keep_alive=Cell("ttl", "seconds, on compat only", _LMS),
        context_control=Cell("server", "context_length on native", _LMS),
        auth=Cell("bearer", "optional", _LMS),
        inline_tools=Cell(True, "compat tools=", _LMS),
        mcp_integrations=Cell(True, "native integrations, the mcp.json plugin", _LMS),
        health=Cell((MODELS_PATH,), "shape-checked", _LMS),
        default_base_url=Cell("http://localhost:1234/v1", "", _LMS),
        doctor_section="LM Studio",
    ),
    "vllm": Provider(
        name="vllm",
        title="vLLM",
        key_hint=_KEY_HINT,
        key_missing=_key_missing("vLLM"),
        chat_transport=Cell("compat", "", _VLLM),
        structured_output=Cell(
            _COMPAT_JSON,
            "response_format; with --reasoning-parser the grammar binds after the thinking",
            _VLLM,
        ),
        probe=Cell("constraint_won", "", _VLLM),
        reasoning_off=Cell(
            _THINKING_OFF,
            "on the same request as the grammar; whether the template honours it is the model's",
            _VLLM,
        ),
        grammar_and_reasoning_off_together=Cell("yes", "", _VLLM),
        inline_think=Cell("strip", "unless served with --reasoning-parser", _VLLM),
        discovery=Cell(
            "openai_models", f"GET base_url{OPENAI_MODELS_PATH} and its max_model_len", _VLLM
        ),
        keep_alive=Cell(None, "", _VLLM),
        context_control=Cell("server", "--max-model-len", _VLLM),
        auth=Cell("bearer", "optional, --api-key", _VLLM),
        inline_tools=Cell(
            True, "tools=, needs --enable-auto-tool-choice and a --tool-call-parser", _VLLM
        ),
        mcp_integrations=Cell(False),
        health=Cell(
            (HEALTH_PATH, OPENAI_MODELS_PATH),
            "/health answers 200, empty; nothing listens while loading; the list shape-checked",
            _VLLM,
        ),
        default_base_url=Cell("http://localhost:8000/v1", "", _VLLM),
        inline_think_fix=(
            "start vLLM with --reasoning-parser <parser> (qwen3, deepseek_r1, ... "
            "per the model family)"
        ),
    ),
    "llamacpp": Provider(
        name="llamacpp",
        title="llama.cpp server",
        key_hint=_KEY_HINT,
        key_missing=_key_missing("llama.cpp server"),
        chat_transport=Cell("compat", "", _LLAMACPP),
        structured_output=Cell(
            _COMPAT_JSON, "response_format; the server converts the schema to GBNF",
            _LLAMACPP,
        ),
        probe=Cell("constraint_won", "", _LLAMACPP),
        reasoning_off=Cell(
            _THINKING_OFF, "needs --jinja; whether the template honours it is the model's",
            _LLAMACPP,
        ),
        grammar_and_reasoning_off_together=Cell("yes", "", _LLAMACPP),
        inline_think=Cell("strip", "unless --reasoning-format is not none", _LLAMACPP),
        discovery=Cell(
            "llamacpp_props",
            f"GET base_url{OPENAI_MODELS_PATH}, then GET {LLAMACPP_PROPS_PATH} for n_ctx",
            _LLAMACPP,
        ),
        keep_alive=Cell(None, "", _LLAMACPP),
        context_control=Cell("server", "-c", _LLAMACPP),
        auth=Cell("bearer", "optional, --api-key", _LLAMACPP),
        inline_tools=Cell(True, "tools=, needs --jinja", _LLAMACPP),
        mcp_integrations=Cell(False),
        health=Cell((HEALTH_PATH,), '{"status": "ok"}; 503 while loading', _LLAMACPP),
        default_base_url=Cell("http://localhost:8080/v1", "", _LLAMACPP),
        inline_think_fix=(
            "start llama-server with --jinja --reasoning-format deepseek "
            "(any value but none)"
        ),
    ),
    "ollama": Provider(
        name="ollama",
        title="Ollama",
        key_hint=_KEY_HINT,
        key_missing=_key_missing("Ollama"),
        chat_transport=Cell("ollama_native", f"POST {OLLAMA_CHAT_PATH}", _OLLAMA),
        structured_output=Cell(
            ("ollama_format_schema", "ollama_format_json"),
            "format: <schema> and format: json on /api/chat",
            _OLLAMA,
        ),
        probe=Cell("constraint_won", "", _OLLAMA),
        reasoning_off=Cell(
            {"think": False},
            f"only where {OLLAMA_SHOW_PATH} lists thinking; trusted only once declared",
            _OLLAMA,
        ),
        grammar_and_reasoning_off_together=Cell("yes", "", _OLLAMA),
        inline_think=Cell("strip", "", _OLLAMA),
        discovery=Cell(
            "ollama_show",
            f"GET {OLLAMA_TAGS_PATH}, POST {OLLAMA_SHOW_PATH} per model, GET {OLLAMA_PS_PATH}",
            _OLLAMA,
        ),
        keep_alive=Cell("keep_alive", "seconds", _OLLAMA),
        context_control=Cell("per_request", "options.num_ctx", _OLLAMA),
        auth=Cell("bearer", "none locally; passed through if set, for a reverse proxy"),
        inline_tools=Cell(True, f"tools on {OLLAMA_CHAT_PATH}", _OLLAMA),
        mcp_integrations=Cell(False),
        health=Cell((OLLAMA_VERSION_PATH, OLLAMA_TAGS_PATH), "the list shape-checked", _OLLAMA),
        default_base_url=Cell("http://localhost:11434", "no /v1", _OLLAMA),
    ),
    "openai_compat": Provider(
        name="openai_compat",
        title="OpenAI-compatible server",
        key_hint=_KEY_HINT,
        key_missing=_key_missing("the OpenAI-compatible server"),
        chat_transport=Cell("compat"),
        structured_output=Cell(
            _COMPAT_JSON, "response_format; probed: json_schema, then json_object, then none"
        ),
        probe=Cell("constraint_won"),
        reasoning_off=Cell(None, "unless llm.reasoning_off_body declares a body patch"),
        grammar_and_reasoning_off_together=Cell(
            "if_declared", "only once llm.reasoning_off_body declares a patch"
        ),
        inline_think=Cell("strip"),
        discovery=Cell(
            "openai_models",
            f"GET base_url{OPENAI_MODELS_PATH} ids, and max_model_len if reported; "
            "capabilities declared",
        ),
        keep_alive=Cell(None),
        context_control=Cell("server"),
        auth=Cell("bearer", "optional"),
        inline_tools=Cell(True, "tools="),
        mcp_integrations=Cell(False),
        health=Cell((OPENAI_MODELS_PATH,), "the list under base_url, shape-checked"),
        default_base_url=Cell(None, "must be set"),
    ),
}

#: The provider a config that names none is served by.
DEFAULT_PROVIDER = "lmstudio"


def get_provider(name: str | None = None) -> Provider:
    """
    The configured provider's row, or ``name``'s.

    ``llm.provider`` is validated when the config loads (``engine/config.py``),
    so an unknown configured name never reaches here; an unknown ``name``
    passed by a caller raises ``KeyError`` naming the legal ones.
    """
    if name is None:
        from engine.config import get_config

        name = str(get_config().get("llm.provider") or DEFAULT_PROVIDER)
    try:
        return PROVIDERS[name]
    except KeyError:
        raise KeyError(
            f"no model server named {name!r}; legal values: {', '.join(PROVIDERS)}"
        ) from None
