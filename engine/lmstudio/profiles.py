"""
Model Profiles
==============

Maps logical profiles to concrete LM Studio models, inference defaults, a
reasoning policy and a concurrency lane.

WHAT CHANGED AND WHY
--------------------
The old version read ``lmstudio.models.{big,small,draft}`` from config, which
held ``local-model``, ``local-model-small`` and ``local-model-draft``. None of
those ids exist on the user's server. Every request named a model LM Studio had
never heard of. Resolution now goes through ``registry.ModelRegistry``, which
asks the server what it actually has and binds by capability.

Profiles also now carry a ``reasoning`` policy. This is the load-bearing field:
utility work (summaries, mechanics, the Assistant, quest evaluation) runs with
``reasoning="off"`` so a 400-token cap buys 400 tokens of ANSWER rather than 400
tokens of deliberation and an empty string. Narration keeps reasoning on,
because a slow local turn is more interesting with the model's thinking visible
than with a frozen screen.

Version: v0.3.0 [2026-08-08]
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Any, Optional

from engine.config import get_config
from engine.lmstudio.registry import ModelInfo, ModelUnavailable, get_registry

logger = logging.getLogger(__name__)

# Used only when the server is unreachable, so that offline dev and unit tests
# still produce a ModelProfile instead of raising.
OFFLINE_MODEL = "local-model"


@dataclass
class ModelProfile:
    """Resolved model profile for inference."""

    name: str
    model: str
    temperature: float = 0.8
    max_tokens: int = 1500
    # off | low | medium | high | on. Honoured only on the native transport;
    # the OpenAI-compatible endpoint ignores every reasoning control.
    reasoning: str = "on"
    # Concurrency lane. Narration owns its own so a summarizer or Assistant
    # call cannot stall the text the player is watching appear.
    lane: str = "utility"
    # Idle seconds before LM Studio may evict the model. Matters with 47
    # installed models competing for VRAM.
    ttl: int = 900
    # Context window the bound model was actually loaded with, for the budget.
    context_tokens: int = 8192
    supports_tools: bool = False
    arch: str = ""
    is_reasoning_model: bool = False
    # Whether `model` is an id the SERVER confirmed it has. False means the
    # placeholder below -- an id LM Studio has never heard of, which it answers
    # with HTTP 400 on every single request. Callers that report health must be
    # able to tell those two apart; nothing could, which is how "doctor says ok,
    # every chat call 400s" stayed true for months.
    bound: bool = False

    @property
    def reasoning_disabled(self) -> bool:
        return self.reasoning == "off"


# Defaults per profile. `max_tokens` caps reasoning + content COMBINED, so a
# reasoning-on profile needs headroom for both; a reasoning-off profile does
# not. See engine/memory/budget.py for why raising these is only safe once the
# budget is derived from the real context window.
_PROFILE_DEFAULTS: dict[str, dict[str, Any]] = {
    # Narration. Reasoning stays ON and is shown to the player as a live
    # "the world is deciding..." channel.
    "big": {
        "temperature": 0.85,
        "max_tokens": 3000,
        "reasoning": "on",
        "lane": "narration",
        "require_tools": True,
        "prefer_non_reasoning": False,
        "min_context": 8192,
    },
    # Utility: summarizer, mechanics, Assistant, quest evaluation. Reasoning
    # OFF -- these calls want an answer, not an essay about the answer.
    "small": {
        "temperature": 0.6,
        "max_tokens": 900,
        "reasoning": "off",
        "lane": "utility",
        "require_tools": False,
        "prefer_non_reasoning": True,
        "min_context": 4096,
    },
    "draft": {
        "temperature": 0.3,
        "max_tokens": 256,
        "reasoning": "off",
        "lane": "utility",
        "require_tools": False,
        "prefer_non_reasoning": True,
        "min_context": 4096,
    },
}

_cache: dict[str, ModelProfile] = {}
_cache_lock = threading.Lock()
# The ConfigManager the cache was built against. Held by reference, not by id():
# keeping the object alive means a later config cannot land on a recycled id and
# silently pass the identity check.
_cache_config: Any = None


def _invalidate_if_config_changed() -> None:
    """
    Drop cached bindings when the config singleton has been replaced.

    ``reset_config()`` invalidates the caches listed in engine/games/caches.py,
    which this module is not registered in (that file belongs to another
    subsystem). Keying the cache on the live config object gets the same
    guarantee locally: a test or a game swap that repoints ``lmstudio.profiles``
    cannot be served a binding built from the previous config.
    """
    global _cache_config
    current = get_config()
    if _cache_config is not current:
        _cache.clear()
        _cache_config = current


def _config_for(profile: str) -> dict[str, Any]:
    """Merge shipped defaults with the `lmstudio.profiles.<name>` overlay."""
    cfg = get_config()
    base = dict(_PROFILE_DEFAULTS.get(profile, _PROFILE_DEFAULTS["big"]))
    overlay = (cfg.get(f"lmstudio.profiles.{profile}", {}) or {})
    if isinstance(overlay, dict):
        base.update(overlay)
    return base


def _preferred_ids(profile: str, settings: dict[str, Any]) -> tuple[str, ...]:
    """
    Explicit model ids to try before inferring one.

    Reads ``lmstudio.profiles.<name>.model`` first, then the legacy
    ``lmstudio.models.<name>`` mapping so an existing local.yaml keeps working.
    """
    cfg = get_config()
    candidates = [
        settings.get("model"),
        (cfg.get("lmstudio.models", {}) or {}).get(profile),
    ]
    return tuple(str(c) for c in candidates if c)


def _bind(profile: str, settings: dict[str, Any]) -> Optional[ModelInfo]:
    """Ask the registry for a concrete model, or None when offline."""
    registry = get_registry()
    try:
        binding = registry.bind(
            profile,
            prefer=_preferred_ids(profile, settings),
            require_tools=bool(settings.get("require_tools", False)),
            prefer_non_reasoning=bool(settings.get("prefer_non_reasoning", False)),
            min_context=int(settings.get("min_context", 0) or 0),
        )
        return binding.model
    except ModelUnavailable as exc:
        # A tools-only requirement is a preference, not a law: retry without it
        # before giving up, so a server with no tool-capable model still plays.
        if settings.get("require_tools"):
            logger.warning(
                "[profiles] No tool-capable model; retrying without the "
                "requirement (operation=_bind, profile=%s)",
                profile,
            )
            try:
                return registry.bind(
                    profile,
                    prefer=_preferred_ids(profile, settings),
                    require_tools=False,
                    prefer_non_reasoning=bool(settings.get("prefer_non_reasoning", False)),
                    min_context=int(settings.get("min_context", 0) or 0),
                ).model
            except ModelUnavailable:
                pass
        logger.error("[profiles] Profile bind failed (operation=_bind, profile=%s): %s", profile, exc)
        return None


def resolve_profile(profile: str, *, refresh: bool = False) -> ModelProfile:
    """
    Resolve a profile name to a model id and inference defaults.

    Resolution is cached per process: discovery is one HTTP round-trip and must
    not sit inside a player's turn.

    Args:
        profile: One of big, small, draft, or a custom key under
            ``lmstudio.profiles``.
        refresh: Re-query the server, ignoring the cache.

    Returns:
        ModelProfile bound to a model that exists on the server, or to
        ``OFFLINE_MODEL`` when the server is unreachable.
    """
    with _cache_lock:
        _invalidate_if_config_changed()
        if not refresh and profile in _cache:
            return _cache[profile]

    settings = _config_for(profile)
    cfg = get_config()
    info = _bind(profile, settings)

    if info is None:
        # Offline or nothing qualifies. Keep the old placeholder so callers get
        # a ModelProfile rather than an exception, but the log above already
        # named the real problem.
        resolved = ModelProfile(
            name=profile,
            model=(_preferred_ids(profile, settings) or (OFFLINE_MODEL,))[0],
            temperature=float(settings["temperature"]),
            max_tokens=int(settings["max_tokens"]),
            reasoning=str(settings["reasoning"]),
            lane=str(settings["lane"]),
            ttl=int(cfg.get("lmstudio.ttl_seconds", 900) or 0),
            context_tokens=int(cfg.get("lmstudio.context_tokens", 8192)),
        )
    else:
        resolved = ModelProfile(
            name=profile,
            model=info.id,
            temperature=float(settings["temperature"]),
            max_tokens=int(settings["max_tokens"]),
            reasoning=str(settings["reasoning"]),
            lane=str(settings["lane"]),
            ttl=int(cfg.get("lmstudio.ttl_seconds", 900) or 0),
            context_tokens=info.usable_context,
            supports_tools=info.supports_tools,
            arch=info.arch,
            is_reasoning_model=info.is_reasoning,
            bound=True,
        )
        logger.info(
            "[profiles] Resolved profile (operation=resolve_profile, profile=%s, "
            "model=%s, reasoning=%s, lane=%s, max_tokens=%s, ctx=%s)",
            profile,
            resolved.model,
            resolved.reasoning,
            resolved.lane,
            resolved.max_tokens,
            resolved.context_tokens,
        )

    with _cache_lock:
        _cache[profile] = resolved
    return resolved


def reset_profiles() -> None:
    """Drop cached bindings. Tests, and after a config reload."""
    global _cache_config
    with _cache_lock:
        _cache.clear()
        _cache_config = None
