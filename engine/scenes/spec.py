"""
Scene Resolution
================

Which scene serves a story, and which Blueprint carries its own screens.

A story declares this at the TOP LEVEL of its ``games/<slug>/game.yaml``::

    scene:
      module: games.tide_and_bell.scene       # optional
      blueprint: games.tide_and_bell.api:story_blueprint   # optional
      name: tide-and-bell                             # optional; picks scene.<name>.*

Top level, not under ``settings:``, for the same reason ``phase_names:`` and
``safety:`` are: the manifest keeps unknown top-level keys verbatim in
``extras``, so a story's scene never becomes a config value that a stale
``config/local.yaml`` could silently move. (``settings.scene.*`` is refused
outright -- see ``SETTING_REFUSALS`` -- because bind host and port belong to
the machine, and that stays true.)

EVERY FIELD IS OPTIONAL AND EVERY DEFAULT IS THE ENGINE'S OWN SCENE. A story
that declares nothing runs on ``engine/scenes/default_scene.py`` with the
default story screens from ``engine/scenes/default_api.py`` -- that is the
point of an engine default, and it is what both shipped games run. They still
DECLARE it, explicitly, in their manifests: a shipped story's scene should be
readable from its ``game.yaml`` rather than known only by omission. A story
opts out of the default screens by naming its own ``blueprint:``; it opts out
of the whole scene by naming its own ``module:``.

THE TRUST BOUNDARY. ``blueprint:`` and ``module:`` are import targets, which
means a manifest can name code to run. That is not a new hole: a game
directory already ships the content the engine executes turns against, and
installing one is already a decision to run it. What this module does refuse
is anything that is not a plain dotted import path -- no filesystem paths, no
relative imports, no URLs -- so the target must be something already importable
on this machine's sys.path rather than an arbitrary file.

Version: v0.1.0 [2026-08-08]
"""

from __future__ import annotations

import importlib
import logging
import re
from dataclasses import dataclass
from typing import Any, Optional

logger = logging.getLogger(__name__)

# The engine's own scene -- what a story gets when it declares nothing. Both
# shipped games declare exactly these values in their manifests; the defaults
# exist for the story that has not written a scene: block yet.
#
# THE COMPAT BAR FOR THE v0.3.0 MOVE: these targets used to be
# content.scenes.clockwork.clockwork_scene / clockwork_api, and those modules
# still import (as shims re-exporting the engine's), so a manifest or tool
# naming the old paths keeps working. The scene NAME stays "clockwork" because
# it keys the ``scene.clockwork.*`` config block that carries the port.
DEFAULT_SCENE_NAME = "clockwork"
DEFAULT_SCENE_MODULE = "engine.scenes.default_scene"
DEFAULT_STORY_BLUEPRINT = "engine.scenes.default_api:story_blueprint"

# Last-resort port. The real home is ``scene.<name>.port`` in config; this is
# only what answers when config has no entry for the scene at all.
DEFAULT_SCENE_PORT = 5573
DEFAULT_SCENE_HOST = "0.0.0.0"

# module.path or module.path:factory -- nothing else.
_TARGET_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$")


def scene_port(name: str = DEFAULT_SCENE_NAME, default: int = DEFAULT_SCENE_PORT) -> int:
    """
    The port a scene binds, from ``scene.<name>.port``.

    ONE HOME FOR THE NUMBER. ``SCENE_METADATA["port"]``, ``FlaskScene.run``'s
    default argument and the launcher's ``--list`` line each carried their own
    5573, so changing ``config/default.yaml`` moved one of four.
    """
    from engine.config import get_config

    try:
        return int(get_config().get(f"scene.{name}.port", default) or default)
    except (TypeError, ValueError):
        logger.warning(
            "[scenes] Unusable scene.%s.port, falling back to %s "
            "(operation=scene_port)",
            name,
            default,
        )
        return default


def scene_host(name: str = DEFAULT_SCENE_NAME, default: str = DEFAULT_SCENE_HOST) -> str:
    """The interface a scene binds, from ``scene.<name>.host``."""
    from engine.config import get_config

    return str(get_config().get(f"scene.{name}.host", default) or default)


@dataclass(frozen=True)
class SceneSpec:
    """
    Which scene a story runs on.

    Attributes:
        name: Scene name. Selects the ``scene.<name>.*`` config block, so it is
            also what decides host and port.
        module: Import path exposing ``run_scene`` and ``create_app``.
        blueprint: ``module:factory`` for the story's own screens, or "" for
            none. The factory is called with the scene's SessionStore.
    """

    name: str = DEFAULT_SCENE_NAME
    module: str = DEFAULT_SCENE_MODULE
    blueprint: str = DEFAULT_STORY_BLUEPRINT

    @property
    def port(self) -> int:
        return scene_port(self.name)

    @property
    def host(self) -> str:
        return scene_host(self.name)


def _valid_target(target: str) -> bool:
    """True when ``target`` is a plain dotted import path, optionally ``:attr``."""
    module, _, attr = str(target).partition(":")
    if not _TARGET_RE.match(module):
        return False
    return not attr or bool(_TARGET_RE.match(attr))


def resolve_scene(manifest: Any = None) -> SceneSpec:
    """
    The scene spec for a story.

    Args:
        manifest: A GameManifest, or None to ask the registry for the one a new
            run would use. ``entry_manifest()`` is used rather than ``active()``
            because reading a manifest must never activate a game as a side
            effect -- that repoints config and clears a dozen caches.

    Returns:
        A SceneSpec. Falls back to every default when the manifest is missing,
        declares no ``scene:`` block, or declares one that is not a mapping.
    """
    if manifest is None:
        try:
            from engine.games.registry import entry_manifest

            manifest = entry_manifest()
        except Exception as exc:  # noqa: BLE001 — a scene must still start
            logger.debug("[scenes] No manifest for scene resolution: %s", exc)
            manifest = None

    block = getattr(manifest, "extras", {}).get("scene") if manifest is not None else None
    if not isinstance(block, dict):
        if block is not None:
            logger.warning(
                "[scenes] Ignoring a 'scene:' block that is not a mapping "
                "(operation=resolve_scene, slug=%s)",
                getattr(manifest, "slug", "?"),
            )
        return SceneSpec()

    spec = SceneSpec(
        name=str(block.get("name") or DEFAULT_SCENE_NAME),
        module=str(block.get("module") or DEFAULT_SCENE_MODULE),
        # An explicit empty string means "ship no story screens at all", which
        # is a real choice and must not fall back to the flagship's.
        blueprint=(
            DEFAULT_STORY_BLUEPRINT
            if block.get("blueprint") is None
            else str(block.get("blueprint"))
        ),
    )

    for field, value in (("module", spec.module), ("blueprint", spec.blueprint)):
        if value and not _valid_target(value):
            logger.error(
                "[scenes] Refusing a scene.%s that is not a dotted import path "
                "(operation=resolve_scene, slug=%s, value=%r)",
                field,
                getattr(manifest, "slug", "?"),
                value,
            )
            return SceneSpec()
    return spec


def load_story_blueprint(target: str, *args: Any, **kwargs: Any) -> Optional[Any]:
    """
    Import ``module:factory`` and call it, returning the Blueprint.

    Args:
        target: Dotted import path, optionally ``:attr``. Empty means the story
            ships no screens of its own -- returns None without a warning,
            because that is a declaration and not a failure.
        *args: Passed to the factory. Today: the scene's SessionStore.

    Returns:
        The Blueprint, or None. A target that will not import is logged and
        skipped: a story whose codex is broken should still be playable,
        exactly as a story with a missing quest directory is.
    """
    if not target:
        return None
    if not _valid_target(target):
        logger.error("[scenes] Not an import path (operation=load_story_blueprint, target=%r)", target)
        return None

    module_path, _, attr = target.partition(":")
    attr = attr or "story_blueprint"
    try:
        module = importlib.import_module(module_path)
        factory = getattr(module, attr)
    except (ImportError, AttributeError) as exc:
        logger.error(
            "[scenes] Story blueprint will not load, its screens will 404 "
            "(operation=load_story_blueprint, target=%s): %s",
            target,
            exc,
        )
        return None
    return factory(*args, **kwargs)


def ensure_active_game() -> None:
    """
    Activate the default game if nothing is active yet.

    The launcher does this for a CLI run, but a scene is also constructed
    directly by tests and by any other host -- and without it the registry sits
    inactive, so ``/api/games/active`` reported a slug with a null manifest and
    every content path still resolved through the un-overlaid config.
    """
    try:
        from engine.games.registry import ActivationError, active, peek

        if peek() is None:
            active()
    except ActivationError as exc:
        logger.error(
            "[scenes] No game could be activated (operation=ensure_active_game): %s",
            exc,
        )
    except ImportError:
        pass


__all__ = [
    "DEFAULT_SCENE_HOST",
    "DEFAULT_SCENE_MODULE",
    "DEFAULT_SCENE_NAME",
    "DEFAULT_SCENE_PORT",
    "DEFAULT_STORY_BLUEPRINT",
    "SceneSpec",
    "ensure_active_game",
    "load_story_blueprint",
    "resolve_scene",
    "scene_host",
    "scene_port",
]
