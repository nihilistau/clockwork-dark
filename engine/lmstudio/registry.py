"""
Model Registry
==============

Discovers what LM Studio actually has, and binds logical profiles to real model
ids by CAPABILITY rather than by a hardcoded name.

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
(``engine/lmstudio/routes.py`` has the server's own error line).

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
hid this for months.

Version: v0.2.0 [2026-08-14]
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx

from engine.config import get_config
from engine.lmstudio.routes import MODELS_PATH, models_url, rest_root

logger = logging.getLogger(__name__)

# Architectures that emit a reasoning channel whether or not you asked for one.
# Measured, not guessed: nemotron_h ignores reasoning_effort, enable_thinking
# and `reasoning` on the OpenAI-compatible endpoint (see native.py docstring).
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


@dataclass(frozen=True)
class ModelInfo:
    """One model as LM Studio reports it."""

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
        """
        return self.arch in REASONING_ARCHES or self.reasoning_default == "on"

    @property
    def is_chat_model(self) -> bool:
        """LLM or VLM, and not an encoder/vocoder masquerading as one."""
        if self.type not in ("llm", "vlm"):
            return False
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


class NotV1Models(RuntimeError):
    """The body at ``/api/v1/models`` was not the v1 model list.

    Raised rather than half-parsed, because LM Studio returns 200 for routes it
    does not serve. The message carries what the body actually looked like --
    the compat shape (``data``/``id``) and an ``{"error": ...}`` blob are the
    two that turn up in practice, and they mean different things.
    """


def _describe(payload: Any) -> str:
    """Name what came back, for an error a person can act on."""
    if isinstance(payload, dict):
        if isinstance(payload.get("error"), (dict, str)):
            return "an error body (the server does not serve this route)"
        if isinstance(payload.get("data"), list):
            return (
                "the OpenAI-compat shape ({'data': [{'id': ...}]}), which is "
                "/v1/models answering for a route it does not own"
            )
        return f"a JSON object with keys {sorted(payload)[:6]}"
    return f"{type(payload).__name__}"


def _quant_name(raw: Any) -> str:
    """v1 reports quantization as ``{"name", "bits_per_weight"}``."""
    if isinstance(raw, dict):
        return str(raw.get("name") or "")
    return str(raw or "")


def _loaded_context(instances: Any) -> int:
    """
    The context an instance was ACTUALLY loaded with.

    v1 nests it: ``loaded_instances[].config.context_length``. It is the number
    to budget against -- the live gemma4 advertises 262,144 and is resident at
    160,768.
    """
    best = 0
    for instance in instances or []:
        if not isinstance(instance, dict):
            continue
        config = instance.get("config") or {}
        if isinstance(config, dict):
            best = max(best, int(config.get("context_length") or 0))
    return best


def _capabilities(raw: Any) -> tuple[tuple[str, ...], str]:
    """
    Flatten v1's capability OBJECT into the flat names the engine asks about.

    ``/api/v0/models`` gave a list of strings; v1 gives
    ``{"vision": bool, "trained_for_tool_use": bool, "reasoning": {...}}``.
    Returns (names, reasoning_default).
    """
    if not isinstance(raw, dict):
        return (), ""
    names: list[str] = []
    if raw.get("trained_for_tool_use"):
        names.append("tool_use")
    if raw.get("vision"):
        names.append("vision")
    reasoning = raw.get("reasoning")
    default = ""
    if isinstance(reasoning, dict):
        default = str(reasoning.get("default") or "")
    return tuple(names), default


def _parse(raw: dict[str, Any]) -> ModelInfo:
    """One entry of ``GET /api/v1/models``."""
    caps, reasoning_default = _capabilities(raw.get("capabilities"))
    instances = raw.get("loaded_instances") or []
    return ModelInfo(
        # `key`, not `id`. The value is the same string the chat routes want.
        id=str(raw.get("key", "")),
        type=str(raw.get("type", "llm")),
        arch=str(raw.get("architecture") or ""),
        publisher=str(raw.get("publisher") or ""),
        quantization=_quant_name(raw.get("quantization")),
        # v1 has no `state` field: residency IS the instance list.
        state="loaded" if instances else "not-loaded",
        max_context_length=int(raw.get("max_context_length") or 0),
        loaded_context_length=_loaded_context(instances),
        capabilities=caps,
        reasoning_default=reasoning_default,
    )


def parse_models_payload(payload: Any) -> list[ModelInfo]:
    """
    Turn a ``/api/v1/models`` body into models, or refuse it.

    Raises:
        NotV1Models: The body is not the v1 shape. This is the check that a
            status code cannot do -- see the module docstring.
    """
    if not isinstance(payload, dict) or not isinstance(payload.get("models"), list):
        raise NotV1Models(
            f"{MODELS_PATH} did not answer with the v1 model list "
            f"({{'models': [...]}}); it returned {_describe(payload)}"
        )
    entries = [e for e in payload["models"] if isinstance(e, dict)]
    # An empty list is a legitimate answer: a server with nothing installed.
    if entries and not any(e.get("key") for e in entries):
        raise NotV1Models(
            f"{MODELS_PATH} answered with a 'models' array whose entries carry "
            "no 'key' -- this is not the v1 REST API"
        )
    return [_parse(e) for e in entries]


def probe_models(
    url: str = "",
    *,
    api_key: Optional[str] = None,
    timeout: float = 3.0,
) -> tuple[bool, str]:
    """
    Ask the one model-list route whether this server is a usable LM Studio.

    Used by every liveness check in the project (``engine/stack.py``,
    ``scripts/doctor.py``, ``LMSClient.is_available``) so there is one answer to
    one question. Healthy means: it answered, it authenticated, the body is the
    v1 shape, and there is at least one model in it.

    Returns:
        ``(ok, detail)`` -- detail is written to be read in a status table.
    """
    cfg = get_config()
    target = url or models_url()
    key = cfg.get("lmstudio.api_key", "") if api_key is None else api_key
    headers = {"Authorization": f"Bearer {key}"} if key else {}

    try:
        response = httpx.get(target, headers=headers, timeout=timeout)
    except httpx.HTTPError as exc:
        return False, f"{target} unreachable ({type(exc).__name__})"

    if response.status_code == 401:
        return False, (
            "listening, but it refuses every request: the API key is missing or "
            "wrong. Set lmstudio.api_key in config/local.yaml, or turn off "
            "'Require API key' in LM Studio's server settings"
        )
    if response.status_code >= 400:
        return False, f"HTTP {response.status_code} from {target}"

    try:
        payload = response.json()
    except ValueError:
        return False, f"{target} answered 200 with a body that is not JSON"

    try:
        models = parse_models_payload(payload)
    except NotV1Models as exc:
        return False, str(exc)

    if not models:
        return False, f"{target} answers, but the server has no models installed"

    loaded = [m.id for m in models if m.is_loaded]
    return True, (
        f"{MODELS_PATH} answers: {len(models)} models, "
        f"loaded: {', '.join(loaded) if loaded else 'none'}"
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
        cfg = get_config()
        # /api/v1 lives beside /v1, not under it. One derivation, in routes.py.
        self.root = rest_root(base_url)
        self.api_key = api_key or cfg.get("lmstudio.api_key", "") or ""
        self.timeout = timeout
        self._models: Optional[list[ModelInfo]] = None
        self._lock = threading.Lock()

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}

    def _fetch(self, path: str) -> Any:
        """GET one discovery route, raising with the server's own words."""
        response = httpx.get(
            f"{self.root}{path}", headers=self._headers(), timeout=self.timeout
        )
        if response.status_code == 401:
            raise ModelUnavailable(
                "LM Studio requires an API key and none is configured. Set "
                "lmstudio.api_key in config/local.yaml, or turn off "
                "'Require API key' in LM Studio's server settings. Until then "
                "EVERY request is refused, including the ones the health check "
                "does not make."
            )
        response.raise_for_status()
        return response.json()

    def refresh(self) -> list[ModelInfo]:
        """
        Re-query the server. Returns [] when it is unreachable or not v1.

        One request to ``GET /api/v1/models``, and the body has to look like the
        v1 model list. There is no second route to try: see the module
        docstring for why a status-code ladder over these APIs is worthless.
        """
        try:
            payload = self._fetch(MODELS_PATH)
            models = parse_models_payload(payload)
        except NotV1Models as exc:
            logger.error(
                "[registry] Model discovery got an answer that is not the v1 "
                "model list -- every chat request will name an unresolved model "
                "and be rejected (operation=refresh, url=%s%s): %s",
                self.root,
                MODELS_PATH,
                exc,
            )
            models = []
        except Exception as exc:  # noqa: BLE001 -- offline dev must still boot
            logger.error(
                "[registry] Model discovery failed -- every chat request "
                "will name an unresolved model and be rejected "
                "(operation=refresh, url=%s%s): %s",
                self.root,
                MODELS_PATH,
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
                MODELS_PATH,
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
                f"No LM Studio model satisfies profile {profile!r} "
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
