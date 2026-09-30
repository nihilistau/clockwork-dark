"""
Model Registry
==============

Discovers what the model server actually has, and binds logical profiles to
real model ids by CAPABILITY rather than by a hardcoded name.

EVERY SERVER, ONE MODEL LIST (v0.19.0). ``refresh`` asks the configured
provider's own routes through ``engine/llm/discovery.py`` -- one parser per
server, each filling the same ``ModelInfo`` -- and ``llm.declared_models`` fills
what a server does not say. Binding, profiles, the denylist and the ranking are
unchanged. What follows is LM Studio's story, and LM Studio's discovery is
still exactly that: the ``lmstudio`` row's parser is v0.18's, moved.

The bug this replaces: ``config/default.yaml`` named ``local-model``,
``local-model-small`` and ``local-model-draft``. None of those ids exist on the
user's server -- it has 47 models with names like
``nvidia/nemotron-3-nano-4b``. Every request went out with a model id LM Studio
had never heard of, and the failure surfaced far downstream as empty narration
rather than as "you asked for a model that does not exist".

ONE ROUTE, AND ITS SHAPE IS THE PROOF
-------------------------------------
Discovery asks ``GET /api/v1/models`` and nothing else. It used to ask
``/api/v0/models`` with a silent fall back to ``/v1/models``: two APIs and a
ladder for one fact, and the bottom rung was a route LM Studio does not own
(``engine/llm/routes.py`` has the server's own error line).

There is no fallback now, deliberately. LM Studio answers unknown-but-plausible
paths with 200 and an error body -- measured live on ``GET /v1/nonsense`` and
``GET /api/v9/models`` -- so a ladder that reads status codes cannot tell a
served route from an unserved one, and would quietly make the wrong route
normal. What is checked instead is the SHAPE of the answer:

    {"models": [{"key", "type", "publisher", "architecture", "capabilities",
                 "max_context_length", "loaded_instances", ...}]}

Note ``key``, not ``id``, and ``models``, not ``data`` -- the compat shim's
shape is a different API's, and accepting it would half-parse a list into
models with no capabilities and no context lengths. A body that is not v1 is
reported as "this server does not speak the v1 REST API" rather than silently
half-read. A server too old to serve ``/api/v1/models`` therefore fails loudly
here; that is the intended trade, because the alternative is the ladder that
hid this for months. Every other server's list is held to its own shape the
same way (``NotAModelList``).

Version: v0.3.0 [2026-09-29]
"""

from __future__ import annotations

import logging
import threading
from dataclasses import InitVar, dataclass, field
from typing import Any, Optional

import httpx

from engine.config import get_config
from engine.llm.routes import compat_base, route_url

logger = logging.getLogger(__name__)

# Architectures that emit a reasoning channel whether or not you asked for one.
# Measured, not guessed: nemotron_h ignores reasoning_effort, enable_thinking
# and `reasoning` on the OpenAI-compatible endpoint (see lmstudio_native.py docstring).
REASONING_ARCHES: frozenset[str] = frozenset(
    {
        "nemotron_h",
        "qwen3",
        "qwen35",
        "qwen35moe",
        "deepseek2",
        "gpt-oss",
        "glm4moe",
    }
)

# Model ids that must never be bound, with the reason. The user reports
# gemma-4-e4b-it is broken on this machine; binding it produces a load failure
# mid-turn, which reads to the player as a hang.
DENYLIST: dict[str, str] = {
    "gemma-4-e4b-it": "known-broken on this host (user-reported)",
}

# Architectures that are not chat models at all. LM Studio lists VAE, CLIP text
# encoders and TTS vocoders in the same array as the LLMs.
_NON_CHAT_ARCHES: frozenset[str] = frozenset(
    {"clip", "clip_text_model", "nomic-bert", None}  # type: ignore[arg-type]
)


#: ``ModelInfo.source`` for a model from LM Studio's own list (and the default,
#: so a ``ModelInfo`` built by hand means what it meant in v0.18).
LMSTUDIO_SOURCE = "lmstudio_v1"


@dataclass(frozen=True)
class ModelInfo:
    """
    One model as its server reports it.

    ``source`` names the parser that produced it (``engine/llm/discovery.py``):
    ``lmstudio_v1``, ``openai_models``, ``llamacpp_props`` or ``ollama_show``.
    ``declared_fields`` names what ``llm.declared_models`` filled that the
    server left empty (``context``, ``tools``, ``reasoning``,
    ``reasoning_default``), and ``reasoning_off_trusted`` when a declaration
    says the patch may be ignored; a declaration never changes ``source``, so LM
    Studio's arch checks keep keying on the parser.

    Both are provenance, not facts about the model, so both are init-only
    values kept as attributes rather than fields: ``dataclasses.asdict`` sees
    exactly v0.18's fields, which is what the LM Studio golden pins
    (scenario 18), and ``dataclasses.replace``, ``copy`` and ``pickle`` carry
    them over (``tests/test_llm_discovery.py`` pins that). The cost: ``==``,
    ``hash`` and ``repr`` ignore provenance, so two models that differ only
    in ``source`` compare equal -- compare ``.source`` where it matters.
    """

    id: str
    type: str = "llm"
    arch: str = ""
    publisher: str = ""
    quantization: str = ""
    state: str = "not-loaded"
    max_context_length: int = 0
    loaded_context_length: int = 0
    capabilities: tuple[str, ...] = field(default_factory=tuple)
    #: ``capabilities.reasoning.default`` as v1 reports it: "on", "off" or "".
    reasoning_default: str = ""
    #: Whether ``capabilities`` carried a ``reasoning`` BLOCK at all.
    #:
    #: Not the same question as ``is_reasoning``, and conflating them cost an
    #: agent its turn. 30 of the 42 LLMs measured on the author's machine
    #: publish no reasoning block, and sending those a ``reasoning`` key --
    #: including ``"off"`` -- is a 400: "does not expose reasoning
    #: configuration". This flag was not recoverable downstream, because
    #: ``_capabilities`` flattened the block to its ``default`` string and an
    #: absent block and a block defaulting to off both arrived as "".
    reasoning_configurable: bool = False
    #: ``capabilities.reasoning.allowed_options``, the server's own list of
    #: what this model will accept. Empty means unspecified, NOT "none".
    reasoning_options: tuple[str, ...] = field(default_factory=tuple)
    source: InitVar[str] = LMSTUDIO_SOURCE
    declared_fields: InitVar[tuple[str, ...]] = ()

    def __post_init__(self, source: str, declared_fields: tuple[str, ...]) -> None:
        object.__setattr__(self, "source", str(source or LMSTUDIO_SOURCE))
        object.__setattr__(self, "declared_fields", tuple(declared_fields or ()))

    def accepts_reasoning(self, value: str) -> bool:
        """
        Whether this model will take ``reasoning=<value>`` without a 400.

        Two independent refusals, both of them measured:
          * no reasoning block -> the parameter itself is rejected
          * a block with ``allowed_options`` -> anything outside it is rejected
        """
        if not self.reasoning_configurable:
            return False
        return not self.reasoning_options or value in self.reasoning_options

    @property
    def is_loaded(self) -> bool:
        return self.state == "loaded"

    @property
    def supports_tools(self) -> bool:
        return "tool_use" in self.capabilities

    @property
    def is_reasoning(self) -> bool:
        """
        Whether this model thinks before it answers, unbidden.

        Two sources, because neither is complete. REASONING_ARCHES is measured
        on this machine and covers architectures that ignore every "stop
        thinking" knob. ``reasoning_default`` is the server's own answer, which
        ``/api/v0/models`` never carried -- gemma4 is not in the arch list and
        reports ``reasoning.default = "on"``.

        The arch list is LM Studio's, measured there, and is read only for a
        model from LM Studio's list. For any other source ``reasoning_default``
        is the whole answer, and only a declaration or Ollama's ``thinking``
        capability sets it: nothing guesses from a name (spec §3.2).
        """
        if self.source == LMSTUDIO_SOURCE and self.arch in REASONING_ARCHES:
            return True
        return self.reasoning_default == "on"

    @property
    def is_chat_model(self) -> bool:
        """
        LLM or VLM, and not an encoder/vocoder masquerading as one.

        The arch and 2048-token tests are for LM Studio's list, which mixes
        CLIP encoders and vocoders in with the LLMs. Another server's list
        carries no arch (``/v1/models``) or says what a model is itself
        (Ollama's ``embedding`` capability, read into ``type``).
        """
        if self.type not in ("llm", "vlm"):
            return False
        if self.source != LMSTUDIO_SOURCE:
            return True
        if not self.arch or self.arch in _NON_CHAT_ARCHES:
            return False
        # A 77-token "context window" is a CLIP text encoder.
        return self.max_context_length >= 2048

    @property
    def usable_context(self) -> int:
        """
        Context to budget against.

        ``loaded_context_length`` is what the model was ACTUALLY loaded with and
        is the number that matters -- nemotron advertises a 1,048,576-token
        window but the user loaded it at 20,224. Budgeting against the
        advertised number would overflow the real one and LM Studio truncates
        the prompt silently, dropping the system persona off the front.
        """
        if self.loaded_context_length > 0:
            return self.loaded_context_length
        return self.max_context_length or 8192


@dataclass(frozen=True)
class Binding:
    """A logical profile bound to a concrete model."""

    profile: str
    model: ModelInfo
    reason: str = ""


class ModelUnavailable(RuntimeError):
    """No model on the server satisfies a profile's requirements.

    Carries the real available ids, because "model not found" without the list
    of what IS there is the least actionable error in local inference.
    """


class NotAModelList(RuntimeError):
    """A discovery route answered with something that is not its server's list.

    Raised rather than half-parsed, because a server can answer 200 for a route
    it does not serve (LM Studio does). The message carries what the body
    actually looked like -- another server's list and an ``{"error": ...}``
    blob are the two that turn up in practice, and they mean different things.

    Attributes:
        provider: The ``llm.provider`` whose shape was expected.
        body: The parsed body that was refused.
    """

    def __init__(self, provider: str, body: Any, message: str = "") -> None:
        self.provider = provider
        self.body = body
        super().__init__(message or f"{provider}: not a model list")


#: v0.18's name, when only LM Studio's v1 list was checked. Kept for callers
#: and scripts that catch it; the same class.
NotV1Models = NotAModelList


def parse_models_payload(payload: Any) -> list[ModelInfo]:
    """
    Turn a ``/api/v1/models`` body into models, or refuse it.

    LM Studio's parser, which lives in ``engine/llm/discovery.py`` beside
    every other server's since v0.19.0.

    Raises:
        NotAModelList: The body is not the v1 shape. This is the check that a
            status code cannot do -- see the module docstring.
    """
    from engine.llm.discovery import parse_lmstudio_v1

    return parse_lmstudio_v1(payload)


def probe_models(
    url: str = "",
    *,
    api_key: Optional[str] = None,
    timeout: float = 3.0,
    provider: Optional[str] = None,
) -> tuple[bool, str]:
    """
    Ask the model-list route whether this server is a usable model server.

    Used by every liveness check in the project (``engine/stack.py``,
    ``scripts/doctor.py``, ``LMSClient.is_available``) so there is one answer to
    one question. Healthy means: it answered, it authenticated, the body is
    that server's list shape, and there is at least one model in it.

    Provider-aware (v0.19.0): the route and the shape are the configured
    provider's (or ``provider``'s) primary discovery list -- LM Studio's
    ``/api/v1/models``, ``/v1/models`` elsewhere, Ollama's ``/api/tags``. On
    LM Studio every request and every detail line is v0.18's.

    Returns:
        ``(ok, detail)`` -- detail is written to be read in a status table.
    """
    from engine.llm.discovery import LIST_PATHS, parse_list
    from engine.llm.providers import get_provider

    cfg = get_config()
    row = get_provider(provider)
    path = LIST_PATHS[row.discovery.value]
    target = url or route_url(path)
    key = cfg.get("llm.api_key", "") if api_key is None else api_key
    headers = {"Authorization": f"Bearer {key}"} if key else {}

    try:
        response = httpx.get(target, headers=headers, timeout=timeout)
    except httpx.HTTPError as exc:
        return False, f"{target} unreachable ({type(exc).__name__})"

    if response.status_code == 401:
        return False, _refused_key_detail(row)
    if response.status_code >= 400:
        return False, f"HTTP {response.status_code} from {target}"

    try:
        payload = response.json()
    except ValueError:
        return False, f"{target} answered 200 with a body that is not JSON"

    try:
        models = parse_list(row, payload)
    except NotAModelList as exc:
        return False, str(exc)

    if not models:
        return False, f"{target} answers, but the server has no models installed"

    loaded = [m.id for m in models if m.is_loaded]
    # LM Studio's line names its fixed route, as v0.18's did. Any other
    # server's list hangs off a configurable base, so its row names the URL
    # that answered: a relative "/models" says nothing in a doctor row.
    where = path if row.discovery.value == LMSTUDIO_SOURCE else target
    return True, (
        f"{where} answers: {len(models)} models, "
        f"loaded: {', '.join(loaded) if loaded else 'none'}"
    )


def _refused_key_detail(row: Any) -> str:
    """What a 401 means, for a status table. The hint is the row's own."""
    return (
        "listening, but it refuses every request: the API key is missing or "
        f"wrong. {row.key_hint}"
    )


def _refused_key_message(row: Any) -> str:
    """
    Discovery's 401, as an exception message. LM Studio's is v0.18's; any
    other server may also be holding a key that is WRONG, not only missing
    (``llm.api_key`` is a fallback chain, and a stale file wins it).
    """
    wrong = "" if row.discovery.value == LMSTUDIO_SOURCE else ", or it is wrong"
    return (
        f"{row.title} requires an API key and none is configured{wrong}. "
        f"{row.key_hint}. Until then EVERY request is refused, including the "
        "ones the health check does not make."
    )


class ModelRegistry:
    """Caches the server's model list and answers binding questions."""

    def __init__(
        self,
        *,
        base_url: Optional[str] = None,
        api_key: str = "",
        timeout: float = 10.0,
    ) -> None:
        from engine.llm.providers import get_provider

        cfg = get_config()
        #: The configured server's row. One per process, like the config.
        self.provider = get_provider()
        # The configured base. Each discovery route is resolved against it by
        # routes.route_url: the OpenAI list under the base itself, everything
        # else (LM Studio's /api/v1, a sibling of /v1) under the server root.
        self.base_url = compat_base(base_url)
        self.api_key = api_key or cfg.get("llm.api_key", "") or ""
        self.timeout = timeout
        self._models: Optional[list[ModelInfo]] = None
        self._lock = threading.Lock()

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}

    def _fetch(self, path: str, body: Optional[dict[str, Any]] = None) -> Any:
        """
        GET one discovery route (or POST ``body`` to it, as JSON), raising with
        the server's own words.

        Under the SERVER ROOT: ``llm.base_url`` less its ``/v1`` (routes.py).
        POST is Ollama's ``/api/show``; every other discovery route is a GET,
        and LM Studio's request is v0.18's, byte for byte.
        """
        url = route_url(path, self.base_url)
        if body is None:
            response = httpx.get(url, headers=self._headers(), timeout=self.timeout)
        else:
            response = httpx.post(
                url, headers=self._headers(), json=body, timeout=self.timeout
            )
        if response.status_code == 401:
            raise ModelUnavailable(_refused_key_message(self.provider))
        response.raise_for_status()
        return response.json()

    def refresh(self) -> list[ModelInfo]:
        """
        Re-query the server. Returns [] when it is unreachable or not its list.

        The provider's own routes (``discovery.list_models``): on LM Studio one
        request to ``GET /api/v1/models``, and the body has to look like the v1
        model list. There is no second route to try: see the module docstring
        for why a status-code ladder over these APIs is worthless. Every other
        server's body is held to its own shape the same way.
        """
        from engine.llm.discovery import LIST_NAMES, LIST_PATHS, list_models

        cfg = get_config()
        provider = self.provider
        route = LIST_PATHS.get(provider.discovery.value, "")
        declared = cfg.get("llm.declared_models", {}) or {}
        try:
            models = list_models(
                provider,
                self._fetch,
                declared=declared if isinstance(declared, dict) else {},
                context_tokens=int(cfg.get("llm.context_tokens", 8192) or 0),
            )
        except NotAModelList as exc:
            logger.error(
                "[registry] Model discovery got an answer that is not %s "
                "-- every chat request will name an unresolved model "
                "and be rejected (operation=refresh, url=%s): %s",
                LIST_NAMES.get(provider.discovery.value, "a model list"),
                route_url(route, self.base_url),
                exc,
            )
            models = []
        except Exception as exc:  # noqa: BLE001 -- offline dev must still boot
            logger.error(
                "[registry] Model discovery failed -- every chat request "
                "will name an unresolved model and be rejected "
                "(operation=refresh, url=%s): %s",
                route_url(route, self.base_url),
                exc,
            )
            models = []

        with self._lock:
            self._models = models
        if models:
            loaded = [m.id for m in models if m.is_loaded]
            logger.info(
                "[registry] Discovered models (operation=refresh, total=%s, "
                "loaded=%s, route=%s)",
                len(models),
                loaded or "none",
                route,
            )
        return models

    def models(self, *, refresh: bool = False) -> list[ModelInfo]:
        """Cached model list, querying once on first use."""
        if refresh or self._models is None:
            return self.refresh()
        return list(self._models)

    def loaded(self) -> list[ModelInfo]:
        """Chat models currently resident in VRAM."""
        return [m for m in self.models() if m.is_loaded and m.is_chat_model]

    def chat_models(self) -> list[ModelInfo]:
        """Every model that could serve a chat request, loaded or not."""
        return [m for m in self.models() if m.is_chat_model and m.id not in DENYLIST]

    def cached(self, model_id: str) -> Optional[ModelInfo]:
        """
        Look a model up WITHOUT touching the network. None when not discovered.

        ``get`` below refreshes on a cold cache, which is right for callers
        choosing a model and wrong for callers building a request body: by then
        a model has already been bound, so a lookup that can make an HTTP call
        would put discovery inside the request it is about to send -- and inside
        a player's turn. None is a real answer here, meaning "nothing measured",
        and the caller decides what to do with it.
        """
        for model in self._models or ():
            if model.id == model_id:
                return model
        return None

    def get(self, model_id: str) -> Optional[ModelInfo]:
        for model in self.models():
            if model.id == model_id:
                return model
        return None

    def bind(
        self,
        profile: str,
        *,
        prefer: tuple[str, ...] = (),
        require_tools: bool = False,
        prefer_non_reasoning: bool = False,
        min_context: int = 0,
        allow_unloaded: bool = True,
    ) -> Binding:
        """
        Choose a concrete model for a logical profile.

        Args:
            profile: Logical profile name, e.g. "narration" or "utility".
            prefer: Explicit model ids to try first, in order. A configured id
                that is present on the server always wins over inference.
            require_tools: Only bind a model advertising ``tool_use``.
            prefer_non_reasoning: Rank instruct models above reasoning models.
                Utility work (summaries, mechanics) wants an answer, not an
                essay about the answer.
            min_context: Minimum usable context window.
            allow_unloaded: Permit binding a model that is not resident. LM
                Studio will JIT-load it, which costs seconds on the first call.

        Returns:
            Binding naming the chosen model and why it was chosen.

        Raises:
            ModelUnavailable: Nothing qualifies. The message lists the real ids.
        """
        candidates = self.chat_models()

        for model_id in prefer:
            if not model_id:
                continue
            if model_id in DENYLIST:
                logger.warning(
                    "[registry] Configured model is denylisted "
                    "(operation=bind, profile=%s, model=%s, reason=%s)",
                    profile,
                    model_id,
                    DENYLIST[model_id],
                )
                continue
            match = next((m for m in candidates if m.id == model_id), None)
            if match is not None:
                return Binding(profile, match, reason="configured")
            logger.warning(
                "[registry] Configured model not on server "
                "(operation=bind, profile=%s, model=%s)",
                profile,
                model_id,
            )

        pool = [m for m in candidates if m.usable_context >= min_context]
        if require_tools:
            pool = [m for m in pool if m.supports_tools]
        if not allow_unloaded:
            pool = [m for m in pool if m.is_loaded]

        if not pool:
            raise ModelUnavailable(
                f"No {self.provider.title} model satisfies profile {profile!r} "
                f"(require_tools={require_tools}, min_context={min_context}). "
                f"Available chat models: {[m.id for m in candidates] or 'none'}. "
                f"Loaded: {[m.id for m in self.loaded()] or 'none'}."
            )

        # Loaded beats not-loaded above everything else: a JIT load of a 27B
        # model inside a player's turn is a multi-second freeze.
        def rank(model: ModelInfo) -> tuple:
            return (
                0 if model.is_loaded else 1,
                (1 if model.is_reasoning else 0) if prefer_non_reasoning else 0,
                -model.usable_context,
                model.id,
            )

        best = sorted(pool, key=rank)[0]
        reason = "loaded" if best.is_loaded else "discovered"
        logger.info(
            "[registry] Bound profile (operation=bind, profile=%s, model=%s, "
            "reason=%s, arch=%s, ctx=%s, tools=%s, reasoning=%s)",
            profile,
            best.id,
            reason,
            best.arch,
            best.usable_context,
            best.supports_tools,
            best.is_reasoning,
        )
        return Binding(profile, best, reason=reason)


_registry: Optional[ModelRegistry] = None
_registry_lock = threading.Lock()


def get_registry() -> ModelRegistry:
    """Process-wide registry singleton."""
    global _registry
    with _registry_lock:
        if _registry is None:
            _registry = ModelRegistry()
        return _registry


def reset_registry() -> None:
    """Drop the singleton. Tests, and config reloads."""
    global _registry
    with _registry_lock:
        _registry = None
