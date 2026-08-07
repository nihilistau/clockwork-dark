"""
Configuration Manager
=====================

Layered YAML config with environment overrides.

Layers, later wins, deep-merged:

    config/default.yaml     checked in; the documented shape of every setting
    config/<env>.yaml       CLOCKWORK_ENV, e.g. development
    config/local.yaml       gitignored; machine-specific paths live here

Deep merge matters for the stack section: overriding one service's ``root``
should not delete every other service, which a shallow update would do.

Version: v0.2.0 [2026-08-07]
"""

from __future__ import annotations

import copy
import logging
import os
from pathlib import Path
from typing import Any, Optional

import yaml

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parent.parent
_CONFIG_DIR = _ROOT / "config"
_DEFAULT_PATH = _CONFIG_DIR / "default.yaml"

_instance: Optional["ConfigManager"] = None


def project_root() -> Path:
    """Repository root. Used to resolve relative paths in config."""
    return _ROOT


def deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge overlay into a copy of base."""
    result = copy.deepcopy(base)
    for key, value in overlay.items():
        if (
            key in result
            and isinstance(result[key], dict)
            and isinstance(value, dict)
        ):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


class ConfigManager:
    """Dot-notation config access."""

    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    def get(self, path: str, default: Any = None) -> Any:
        """Return nested value by dot path."""
        node: Any = self._data
        for part in path.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        if isinstance(node, str) and node.startswith("${") and node.endswith("}"):
            return self._expand(node[2:-1], default)
        return node

    def _expand(self, token: str, default: Any) -> Any:
        """
        Resolve a ``${...}`` reference.

        Two forms:
            ${NAME}             environment variable
            ${file:some/path}   first line of a file, stripped

        The file form exists so secrets can live in a gitignored file rather
        than being pasted into a checked-in YAML. It falls back to the
        environment when the file is absent, so either mechanism works alone.
        """
        if token.startswith("file:"):
            raw_path = token[5:].strip()
            candidate = Path(raw_path)
            path = candidate if candidate.is_absolute() else _ROOT / candidate
            try:
                value = path.read_text(encoding="utf-8").strip()
                if value:
                    return value
            except OSError:
                logger.debug(
                    "[config] Secret file unreadable (operation=_expand, path=%s)", path
                )
            return default
        return os.environ.get(token, default)

    def section(self, path: str) -> dict[str, Any]:
        """Return a nested dict, or {} if absent."""
        value = self.get(path, {})
        return value if isinstance(value, dict) else {}

    def resolve_path(self, path: str, default: str = "") -> Optional[Path]:
        """
        Resolve a config value as a filesystem path.

        Relative paths are taken against the repo root so the game behaves the
        same regardless of the working directory it was launched from.
        """
        raw = str(self.get(path, default) or "").strip()
        if not raw:
            return None
        candidate = Path(raw)
        return candidate if candidate.is_absolute() else (_ROOT / candidate)

    def as_dict(self) -> dict[str, Any]:
        return copy.deepcopy(self._data)


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with path.open(encoding="utf-8") as handle:
            return yaml.safe_load(handle) or {}
    except (OSError, yaml.YAMLError) as exc:
        logger.warning("[config] Unreadable config (operation=_load_yaml, path=%s): %s", path, exc)
        return {}


def get_config() -> ConfigManager:
    """Return singleton ConfigManager, loading layers on first use."""
    global _instance
    if _instance is None:
        data = _load_yaml(_DEFAULT_PATH)

        env = os.environ.get("CLOCKWORK_ENV", "").strip()
        if env:
            overlay = _load_yaml(_CONFIG_DIR / f"{env}.yaml")
            if overlay:
                data = deep_merge(data, overlay)
                logger.info("[config] Environment layer applied (operation=get_config, env=%s)", env)

        local = _load_yaml(_CONFIG_DIR / "local.yaml")
        if local:
            data = deep_merge(data, local)
            logger.info("[config] Local overrides applied (operation=get_config)")

        _instance = ConfigManager(data)
    return _instance


def reset_config() -> None:
    """
    Reset the config singleton and every module cache keyed off it.

    Resetting only the singleton left procgen templates, world schedules,
    ComfyUI templates and the rules engine holding data loaded from the
    previous config, so a test that repointed a path silently got stale
    content -- and the failure surfaced in whichever test happened to run next.
    """
    global _instance
    _instance = None

    # These are all `Optional[dict]` guarded by `is not None`, so they must be
    # set back to None -- clearing the dict in place would leave an empty-but-
    # populated cache that never reloads.
    for module_name, attr in (
        ("engine.game.procgen", "_TEMPLATE_CACHE"),
        ("engine.world.schedules", "_SCHEDULE_CACHE"),
        ("engine.media.comfyui", "_TEMPLATE_CACHE"),
        ("engine.mcp.scene_rules_engine", "_rules_instance"),
    ):
        try:
            module = __import__(module_name, fromlist=[attr])
        except ImportError:
            continue
        if hasattr(module, attr):
            setattr(module, attr, None)
