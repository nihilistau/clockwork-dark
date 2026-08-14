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

``GET /api/v0/models`` is used instead of ``GET /v1/models`` because only the
former returns ``state`` (loaded / not-loaded), ``arch``, ``capabilities`` and
``max_context_length`` -- the three facts a binding decision needs.

Version: v0.1.0 [2026-08-08]
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx

from engine.config import get_config

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

    @property
    def is_loaded(self) -> bool:
        return self.state == "loaded"

    @property
    def supports_tools(self) -> bool:
        return "tool_use" in self.capabilities

    @property
    def is_reasoning(self) -> bool:
        """Whether this model thinks before it answers, unbidden."""
        return self.arch in REASONING_ARCHES

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


# What a model is assumed to have when discovery came from /v1/models, which
# reports an id and nothing else. Small enough that a budget built from it fits
# any real chat model, large enough to clear `is_chat_model`.
DEGRADED_ARCH = "unknown"
DEGRADED_CONTEXT = 8192


def _parse(raw: dict[str, Any], *, degraded: bool = False) -> ModelInfo:
    """
    One entry from a discovery route.

    Args:
        degraded: The entry came from ``/v1/models``, which reports an id and
            nothing else. Every capability field is then a guess, and saying so
            here is better than letting `is_chat_model` reject the whole server
            because OpenAI's schema has no `arch` field.
    """
    caps = raw.get("capabilities") or []
    arch = str(raw.get("arch") or "")
    context = int(raw.get("max_context_length") or 0)
    return ModelInfo(
        id=str(raw.get("id", "")),
        type=str(raw.get("type", "llm")),
        arch=arch or (DEGRADED_ARCH if degraded else ""),
        publisher=str(raw.get("publisher") or ""),
        quantization=str(raw.get("quantization") or ""),
        state=str(raw.get("state") or "not-loaded"),
        max_context_length=context or (DEGRADED_CONTEXT if degraded else 0),
        loaded_context_length=int(raw.get("loaded_context_length") or 0),
        capabilities=tuple(str(c) for c in caps if c),
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
        # /api/v0 lives beside /v1, not under it.
        compat = (base_url or cfg.get("lmstudio.base_url", "http://localhost:1234/v1")).rstrip("/")
        self.root = compat[: -len("/v1")] if compat.endswith("/v1") else compat
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
        Re-query the server. Returns [] when it is unreachable.

        ``/api/v0/models`` is the route that carries capabilities, arch and the
        loaded context length. It is also LM Studio's own extension, so it can
        be absent; when it is, ``/v1/models`` still yields the ids, which is
        enough to stop the profile resolver falling back to a placeholder model
        id that the server answers with 400 on every request. A degraded
        binding beats a fictional one.
        """
        payload: Any = None
        degraded = False
        try:
            payload = self._fetch("/api/v0/models")
        except Exception as exc:  # noqa: BLE001 -- offline dev must still boot
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status in (404, 405):
                degraded = True
                logger.warning(
                    "[registry] /api/v0/models is not served; falling back to "
                    "/v1/models, which reports no capabilities or context "
                    "lengths (operation=refresh, url=%s)",
                    self.root,
                )
                try:
                    payload = self._fetch("/v1/models")
                except Exception as inner:  # noqa: BLE001
                    degraded = False
                    logger.error(
                        "[registry] Model discovery failed on both routes "
                        "(operation=refresh, url=%s): %s",
                        self.root,
                        inner,
                    )
            else:
                logger.error(
                    "[registry] Model discovery failed -- every chat request "
                    "will name an unresolved model and be rejected "
                    "(operation=refresh, url=%s): %s",
                    self.root,
                    exc,
                )

        if payload is None:
            with self._lock:
                self._models = []
            return []

        entries = payload.get("data") if isinstance(payload, dict) else payload
        models = [
            _parse(e, degraded=degraded) for e in (entries or []) if isinstance(e, dict)
        ]
        with self._lock:
            self._models = models
        loaded = [m.id for m in models if m.is_loaded]
        logger.info(
            "[registry] Discovered models (operation=refresh, total=%s, loaded=%s, "
            "route=%s)",
            len(models),
            loaded or "none",
            "/v1/models (degraded)" if degraded else "/api/v0/models",
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
