"""
Model Profiles
==============

Maps logical profiles (big, small, draft) to configured model names.

Version: v0.1.0 [2026-06-20]
"""

from __future__ import annotations

from dataclasses import dataclass

from engine.config import get_config


@dataclass
class ModelProfile:
    """Resolved model profile for inference."""

    name: str
    model: str
    temperature: float = 0.8
    max_tokens: int = 1500


_PROFILE_DEFAULTS: dict[str, dict[str, float | int]] = {
    "big": {"temperature": 0.85, "max_tokens": 1500},
    "small": {"temperature": 0.95, "max_tokens": 300},
    "draft": {"temperature": 0.3, "max_tokens": 256},
}


def resolve_profile(profile: str) -> ModelProfile:
    """
    Resolve a profile name to model id and inference defaults.

    Args:
        profile: One of big, small, draft (or custom key in config).

    Returns:
        ModelProfile with model name from config.
    """
    cfg = get_config()
    models = cfg.get("lmstudio.models", {}) or {}
    model = models.get(profile) or models.get("big") or "local-model"
    defaults = _PROFILE_DEFAULTS.get(profile, _PROFILE_DEFAULTS["big"])
    return ModelProfile(
        name=profile,
        model=str(model),
        temperature=float(defaults["temperature"]),
        max_tokens=int(defaults["max_tokens"]),
    )