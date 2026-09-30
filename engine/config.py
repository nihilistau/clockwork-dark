"""
Configuration Manager
=====================

Layered YAML config with environment overrides.

Layers, later wins, deep-merged:

    config/default.yaml     checked in; the documented shape of every setting
    config/<env>.yaml       CLOCKWORK_ENV, e.g. development
    config/local.yaml       gitignored; machine-specific paths live here
    <game overlay>          the active game manifest's ``paths:`` block

Each layer's legacy ``lmstudio:`` block is renamed ``llm:`` before it merges,
and a legacy key read is answered from its new name: see
``migrate_legacy_llm`` (v0.19.0; the alias goes in v0.21.0).

Deep merge matters for the stack section: overriding one service's ``root``
should not delete every other service, which a shallow update would do.

The game overlay is the top layer on purpose. A game is chosen at launch and
must beat everything the repo shipped, but it must NOT be written into the
YAML files -- so it lives in a process-local variable that survives
``reset_config()``. See ``set_overlay`` and ``engine/games/registry.py``.

``paths.*`` HAS ONE EXTRA LAYER, AND IT IS THE POINT OF THIS MODULE'S v0.4.0.
Until then ``config/default.yaml`` named The Clockwork Dark's own content files
as the engine's defaults, so a story that omitted a key did not read nothing --
it read the flagship's quests, prices and encounters, silently. The defaults are
empty strings now, and an empty ``paths.*`` value is answered from the manifest
of the story this process is running (``registry.entry_manifest()``): the
activated one, or the one ``resolve_slug()`` names when nothing has been
activated yet. Nothing else changes: an unactivated process is by definition
running the default game, so it resolves that game's manifest and sees exactly
the paths this file used to hardcode.

Version: v0.4.0 [2026-08-09]
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

# The active game's config overlay. Deliberately NOT cleared by reset_config():
# activating a game is a session-level decision, and re-reading the YAML layers
# must not silently drop the player back into a different story.
_overlay: dict[str, Any] = {}

#: Keys under this prefix name STORY content. The engine ships none of it.
_PATHS_PREFIX = "paths."

#: Distinguishes "declared, and empty" from "no such key anywhere", which for a
#: ``paths.*`` lookup are different answers -- see ``_story_path``.
_MISSING = object()

#: Manifest ``paths:`` blocks by slug, for the case where no game has been
#: activated and the answer therefore has to be read off disk.
#:
#: DELIBERATELY NOT CLEARED BY reset_config(), and an empty answer is never
#: stored. Cache invalidation runs reloaders that re-read content, and those
#: reloaders ask this question while it is being answered -- so a moment when
#: the manifest cannot be found (a test that has redirected ``games_root``, a
#: directory being written) would otherwise replace a whole story's content
#: paths with nothing and leave the process with an empty world and no error.
#: A manifest's ``paths:`` block does not change while a process runs; a game
#: swap goes through the overlay, which is read ahead of this.
_story_paths_by_slug: dict[str, dict[str, str]] = {}

# -- the model server's block, and its v0.18 name ---------------------------
#
# ``llm:`` was ``lmstudio:`` until v0.19.0, and an owner's config/local.yaml
# still says so. The rename is applied to each LAYER before it merges
# (``migrate_legacy_llm``), not as a fallback read: the shipped default carries
# ``llm.base_url``, so "try ``llm.``, else ``lmstudio.``" would let the default
# beat the owner's own ``lmstudio.base_url``. Removed in v0.21.0.

#: The model server's block.
LLM_BLOCK = "llm"
#: Its name until v0.19.0, in a config layer and under ``stack.services``.
LEGACY_LLM_BLOCK = "lmstudio"
#: Keys renamed inside a legacy block as it moves.
_LEGACY_LLM_KEYS: dict[str, str] = {"ttl_seconds": "keep_alive_seconds"}
#: Dotted reads of an old name, answered from the new one. Most specific first.
_READ_ALIASES: tuple[tuple[str, str], ...] = (
    ("lmstudio.ttl_seconds", "llm.keep_alive_seconds"),
    ("stack.services.lmstudio", "stack.services.llm"),
    ("lmstudio", "llm"),
)


def _read_alias(path: str) -> str:
    """A legacy dotted key, as its ``llm`` name; any other key unchanged."""
    for old, new in _READ_ALIASES:
        if path == old or path.startswith(old + "."):
            return new + path[len(old):]
    return path


def _moved_under(legacy: Any, current: Any) -> Any:
    """A legacy block merged UNDER the current one: the current wins a shared key."""
    if not isinstance(legacy, dict):
        return current
    if not isinstance(current, dict):
        return legacy if current is None else current
    return deep_merge(legacy, current)


def migrate_legacy_llm(layer: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """
    Rename one config layer's legacy model-server blocks to their ``llm`` names.

    ``lmstudio:`` becomes ``llm:`` (its ``ttl_seconds`` becoming
    ``keep_alive_seconds``) and ``stack.services.lmstudio`` becomes
    ``stack.services.llm``. A layer holding both the old and the new block has
    the old one deep-merged UNDER the new: the new wins a key both set, and a
    key only the old one sets is kept, never dropped.

    Used by ``get_config`` on every layer and by the Settings panel when it
    rewrites config/local.yaml, so both apply one rule.

    Args:
        layer: One parsed layer. Not modified.

    Returns:
        The migrated copy, and a description of each rename made (empty when
        the layer held nothing legacy).
    """
    if not isinstance(layer, dict):
        return layer, []
    out = copy.deepcopy(layer)
    renamed: list[str] = []

    if LEGACY_LLM_BLOCK in out:
        legacy = out.pop(LEGACY_LLM_BLOCK)
        if isinstance(legacy, dict):
            moved = {k: v for k, v in legacy.items() if k not in _LEGACY_LLM_KEYS}
            for old, new in _LEGACY_LLM_KEYS.items():
                if old in legacy and new not in legacy:
                    moved[new] = legacy[old]
            legacy = moved
        merged = _moved_under(legacy, out.get(LLM_BLOCK))
        if merged is not None:
            out[LLM_BLOCK] = merged
        renamed.append(f"{LEGACY_LLM_BLOCK}: -> {LLM_BLOCK}:")

    stack = out.get("stack")
    services = stack.get("services") if isinstance(stack, dict) else None
    if isinstance(services, dict) and LEGACY_LLM_BLOCK in services:
        legacy = services.pop(LEGACY_LLM_BLOCK)
        merged = _moved_under(legacy, services.get(LLM_BLOCK))
        if merged is not None:
            services[LLM_BLOCK] = merged
        renamed.append(f"stack.services.{LEGACY_LLM_BLOCK} -> stack.services.{LLM_BLOCK}")

    return out, renamed


#: The layers the current config was aliased from: ``(source, renames)``, one
#: per layer that still said ``lmstudio:``. Rebuilt with the singleton; read
#: by ``scripts/doctor.py``'s ``legacy lmstudio: block`` row (spec §2.2).
_legacy_layers: list[tuple[str, list[str]]] = []


def legacy_llm_layers() -> list[tuple[str, list[str]]]:
    """Each config layer read under its legacy name, as ``(source, renames)``."""
    get_config()
    return [(source, list(renamed)) for source, renamed in _legacy_layers]


def _aliased(layer: dict[str, Any], source: str) -> dict[str, Any]:
    """``migrate_legacy_llm``, with the one WARNING per aliased layer."""
    migrated, renamed = migrate_legacy_llm(layer)
    if renamed:
        _legacy_layers.append((source, list(renamed)))
        logger.warning(
            "[config] Legacy model-server config read under its new name "
            "(operation=get_config, file=%s, renamed=%s). Rename it there: the "
            "lmstudio alias is removed in v0.21.0.",
            source,
            "; ".join(renamed),
        )
    return migrated


def _check_provider(data: dict[str, Any]) -> None:
    """
    Refuse a config naming a model server this build does not speak.

    The legal names are the rows of ``engine/llm/providers.py::PROVIDERS``
    (imported here, not at module load: that package reads this one).
    """
    from engine.llm.providers import PROVIDERS

    block = data.get(LLM_BLOCK)
    if not isinstance(block, dict) or block.get("provider") is None:
        return
    name = block["provider"]
    if name not in PROVIDERS:
        raise ValueError(
            f"llm.provider {name!r} is not a model server this build speaks; "
            f"legal values: {', '.join(PROVIDERS)}"
        )


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


def story_paths() -> dict[str, str]:
    """
    The ``paths:`` block of the story this process is running.

    The activated manifest if there is one, else the manifest ``resolve_slug()``
    names, read off disk and cached per slug. Reading it must not activate
    anything: activation repoints config and clears a dozen content caches, and
    asking where the quests live is not a reason for either.

    Returns:
        Mapping of path key to repo-relative value. Empty when no manifest is
        readable, which is deliberately not an error here -- a caller asking for
        a path it will not get is answered by the loader, not by a raise from
        the config layer.
    """
    try:
        from engine.games import registry

        manifest = registry.peek()
        if manifest is not None:
            return manifest.paths
        slug = registry.resolve_slug()
        cached = _story_paths_by_slug.get(slug)
        if cached is not None:
            return cached
        found = registry.get(slug)
        paths = dict(found.paths) if found is not None else {}
        if paths:
            _story_paths_by_slug[slug] = paths
        return paths
    except Exception as exc:  # noqa: BLE001 -- config must answer, never raise
        logger.debug("[config] No manifest for path lookup (operation=story_paths): %s", exc)
        return {}


class ConfigManager:
    """Dot-notation config access."""

    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    def get(self, path: str, default: Any = None) -> Any:
        """
        Return nested value by dot path.

        ``paths.*`` takes one extra step: the engine's config declares those
        keys empty on purpose, so an empty one is answered from the running
        story's manifest instead. See ``_story_path`` for what that costs the
        caller's ``default``.

        A legacy ``lmstudio.*`` key (and ``stack.services.lmstudio.*``) is
        answered from its ``llm`` name, so an owner's script that still asks
        for the old one keeps working: see ``_READ_ALIASES``.
        """
        path = _read_alias(path)
        node: Any = self._data
        found: Any = _MISSING
        for part in path.split("."):
            if not isinstance(node, dict) or part not in node:
                break
            node = node[part]
        else:
            found = node

        value = default if found is _MISSING else found
        if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
            value = self._expand(value[2:-1], default)

        if path.startswith(_PATHS_PREFIX):
            return self._story_path(
                path[len(_PATHS_PREFIX):],
                value if found is not _MISSING else "",
                declared=found is not _MISSING,
                default=default,
            )
        return value

    def _story_path(self, key: str, value: Any, *, declared: bool, default: Any) -> Any:
        """
        Answer a ``paths.*`` lookup, falling back to the running story's manifest.

        THE CALLER'S DEFAULT IS DELIBERATELY NOT USED FOR A KEY THE CONFIG
        DECLARES. Every such literal in this engine was one story's answer --
        ``data/quests``, ``data/tables``, ``data/world/locations.yaml`` --
        and returning it would rebuild, in Python, exactly the inheritance the
        empty defaults exist to remove. A key the config declares and no story
        claims resolves to "", which every loader reads as "this story ships
        none of this".

        The default still answers a key that appears nowhere: that is not a
        story omitting content, it is a caller asking about a key this build's
        config has never heard of, and its own answer is the only one available.

        Args:
            key: The part after ``paths.``.
            value: What the config layers hold, "" when they hold nothing.
            declared: Whether the key exists in the config at all.
            default: The caller's fallback.
        """
        text = str(value or "").strip()
        if text:
            return text
        from_story = str(story_paths().get(key) or "").strip()
        if from_story:
            return from_story
        if declared:
            logger.debug(
                "[config] Story declares no content for this path "
                "(operation=_story_path, key=paths.%s)",
                key,
            )
            return ""
        return default

    def _expand(self, token: str, default: Any) -> Any:
        """
        Resolve a ``${...}`` reference.

        One alternative:
            ${NAME}             environment variable
            ${env:NAME}         the same, spelled out
            ${file:some/path}   first line of a file, stripped; relative to the
                                repo root; the default when absent or empty

        Or a chain of them, ``${file:a.txt|env:A_KEY|B_KEY}``, tried left to
        right: the first alternative with a non-empty value wins, and the
        caller's default answers when none has one. The split happens only when
        the token holds a ``|``, so a v0.18 token resolves exactly as it did.

        Inside a chain, an alternative written ``<provider>?<alternative>``
        (``lmstudio?file:lmstudio.txt``) is tried only while ``llm.provider``
        is that provider, and skipped otherwise. The shipped key uses it so
        LM Studio's own key sources (``lmstudio.txt``, ``LMSTUDIO_API_KEY``)
        are never sent to another server: an owner who kept LM Studio's key
        there and pointed ``llm.provider`` at a remote ``openai_compat`` host
        would otherwise hand that host the key (AGENTS.md rule 5).

        The file form exists so secrets can live in a gitignored file rather
        than being pasted into a checked-in YAML, and the chain so the
        environment can stand in for the file. v0.18's file form was documented
        as falling back to the environment and never did: a key set only there
        was silently ignored. Expansion happens on every ``get()``, so a
        variable set after the config loaded is seen. No value is ever logged.
        """
        if "|" not in token:
            return self._expand_one(token, default)
        for alternative in token.split("|"):
            alternative = alternative.strip()
            if not alternative:
                continue
            scope, mark, rest = alternative.partition("?")
            if mark:
                if str(self.get("llm.provider", "lmstudio") or "").strip() != scope.strip():
                    continue
                alternative = rest.strip()
            value = self._expand_one(alternative, None)
            if value:
                return value
        return default

    @staticmethod
    def _expand_one(token: str, default: Any) -> Any:
        """One ``${...}`` alternative: ``file:``, ``env:`` or a bare name."""
        if token.startswith("file:"):
            raw_path = token[5:].strip()
            candidate = Path(raw_path)
            path = candidate if candidate.is_absolute() else _ROOT / candidate
            try:
                # utf-8-sig: Notepad's "UTF-8 with BOM" would otherwise put
                # U+FEFF at the front of the key, which strip() keeps and
                # httpx refuses to put in a header.
                value = path.read_text(encoding="utf-8-sig").strip()
                if value:
                    return value.splitlines()[0].strip()
            except OSError:
                logger.debug(
                    "[config] Secret file unreadable (operation=_expand, path=%s)", path
                )
            return default
        if token.startswith("env:"):
            token = token[4:].strip()
        return os.environ.get(token, default)

    def section(self, path: str) -> dict[str, Any]:
        """
        Return a nested dict, or {} if absent.

        ``section("paths")`` answers what ``get("paths.<key>")`` answers, key for
        key. The two disagreeing would be its own trap: a caller iterating the
        section would see the engine's empty string for a key that resolves,
        through the running story's manifest, to a real file.
        """
        value = self.get(path, {})
        block = value if isinstance(value, dict) else {}
        if path != "paths":
            return block
        merged = dict(block)
        for key, declared in story_paths().items():
            if not str(merged.get(key) or "").strip():
                merged[key] = declared
        return merged

    def resolve_path(self, path: str, default: str = "") -> Optional[Path]:
        """
        Resolve a config value as a filesystem path.

        Relative paths are taken against the repo root so the game behaves the
        same regardless of the working directory it was launched from. None
        means the value is empty, which for a ``paths.*`` key means the running
        story ships none of that content -- ``_ROOT / ""`` is the repo root,
        and reading whatever is in it is worse than reading nothing.
        """
        raw = str(self.get(path, default) or "").strip()
        if not raw:
            return None
        candidate = Path(raw)
        return candidate if candidate.is_absolute() else (_ROOT / candidate)

    def as_dict(self) -> dict[str, Any]:
        """The merged tree, migrated: an ``llm`` block and never a ``lmstudio`` one."""
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
    """
    Return singleton ConfigManager, loading layers on first use.

    Each layer has its legacy ``lmstudio:`` blocks renamed BEFORE it merges
    (``migrate_legacy_llm``), so precedence survives the rename. The merged
    ``llm.provider`` is checked last.

    Raises:
        ValueError: ``llm.provider`` names a server this build does not speak.
    """
    global _instance
    if _instance is None:
        _legacy_layers.clear()
        data = _aliased(_load_yaml(_DEFAULT_PATH), str(_DEFAULT_PATH))

        env = os.environ.get("CLOCKWORK_ENV", "").strip()
        if env:
            env_path = _CONFIG_DIR / f"{env}.yaml"
            overlay = _load_yaml(env_path)
            if overlay:
                data = deep_merge(data, _aliased(overlay, str(env_path)))
                logger.info("[config] Environment layer applied (operation=get_config, env=%s)", env)

        local_path = _CONFIG_DIR / "local.yaml"
        local = _load_yaml(local_path)
        if local:
            data = deep_merge(data, _aliased(local, str(local_path)))
            logger.info("[config] Local overrides applied (operation=get_config)")

        if _overlay:
            data = deep_merge(data, _aliased(_overlay, "the game overlay"))
            logger.info(
                "[config] Game overlay applied (operation=get_config, keys=%s)",
                sorted(_overlay),
            )

        _check_provider(data)
        _instance = ConfigManager(data)
    return _instance


def set_overlay(overlay: Optional[dict[str, Any]]) -> None:
    """
    Install (or clear) the top config layer and drop every derived cache.

    This is the supported replacement for reaching into ``ConfigManager._data``
    -- the source project's games/ README told contributors to retarget content
    by mutating that private dict by hand, which no cache invalidation could
    ever be hung off.

    Args:
        overlay: Nested dict merged last over the YAML layers, or None/{} to
            clear it. A copy is taken, so the caller's dict stays theirs.
    """
    global _overlay
    _overlay = copy.deepcopy(overlay) if overlay else {}
    reset_config()


def overlay() -> dict[str, Any]:
    """Return a copy of the active config overlay."""
    return copy.deepcopy(_overlay)


def reset_config() -> None:
    """
    Reset the config singleton and every module cache keyed off it.

    Resetting only the singleton left procgen templates, world schedules,
    ComfyUI templates and the rules engine holding data loaded from the
    previous config, so a test that repointed a path silently got stale
    content -- and the failure surfaced in whichever test happened to run next.

    The list of caches lives in ``engine/games/caches.py`` now rather than
    inline here: it grew past a dozen entries once every content loader had to
    survive a whole-game swap, and it has to be introspectable so
    ``scripts/doctor.py`` can report what a game activation will invalidate.
    """
    global _instance
    _instance = None

    # Imported lazily: engine.games imports engine.config, and a module-level
    # import here would be a cycle.
    try:
        from engine.games.caches import reset_all_caches
    except ImportError:  # pragma: no cover -- engine.games always ships
        logger.warning("[config] Cache registry unavailable (operation=reset_config)")
        return
    reset_all_caches()
