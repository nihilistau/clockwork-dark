"""
Game Registry
=============

Discover the games on disk, validate one, activate it.

    discover()          scan games/*/game.yaml
    validate(manifest)  every declared path must exist -- returns problems
    activate(slug)      merge paths over config, invalidate every cache
    active()            the manifest currently in force
    reset_all_caches()  re-exported; the public form of "reload everything"

WHY VALIDATION IS A HARD GATE AT ACTIVATION: every content loader in this
engine is deliberately forgiving. A missing quest directory logs a warning and
yields no quests; an unreadable location graph logs and yields an empty map.
That is right for a running turn and wrong for a launch -- a manifest with a
typo in ``paths.locations`` would boot into a game with no world at all and no
error anywhere near the cause. So the paths are checked once, up front, and a
game with a broken manifest refuses to activate.

WHY THE DEFAULT GAME CHANGES NOTHING: ``games/clockwork-dark/game.yaml``
declares exactly the paths ``config/default.yaml`` already had. Activating it
is a no-op merge, which is the point -- the flagship game shipping as a game
must not move a single content file.

Selection precedence, first hit wins:

    explicit argument       registry.activate("drowned-carillon")
    CLOCKWORK_GAME          environment variable
    config game.default     config/default.yaml

Version: v0.1.0 [2026-08-08]
"""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import Any, Optional

from engine.config import get_config, project_root, set_overlay
from engine.games import ENGINE_VERSION
from engine.games.caches import registered_caches, reset_all_caches
from engine.games.manifest import (
    MANIFEST_FILENAME,
    OUTPUT_PATH_KEYS,
    SLUG_RE,
    GameManifest,
    ManifestError,
    satisfies,
)

logger = logging.getLogger(__name__)

GAMES_DIRNAME = "games"
DEFAULT_SLUG = "clockwork-dark"
GAME_ENV_VAR = "CLOCKWORK_GAME"

# Activation mutates process-global config and a dozen module caches. The scene
# server is threaded, so a second activation racing the first would interleave
# "config repointed" with "caches still warm" -- exactly the stale-content bug
# this package exists to prevent.
_lock = threading.RLock()

_active: Optional[GameManifest] = None


class ActivationError(RuntimeError):
    """A game exists but cannot be activated. Carries every reason at once."""

    def __init__(self, slug: str, problems: list[str]) -> None:
        self.slug = slug
        self.problems = list(problems)
        detail = "; ".join(self.problems) or "unknown"
        super().__init__(f"Cannot activate game {slug!r}: {detail}")


def games_root() -> Path:
    """Directory holding one subdirectory per game."""
    return project_root() / GAMES_DIRNAME


# ---------------------------------------------------------------------------
# discovery
# ---------------------------------------------------------------------------


def discover() -> dict[str, GameManifest]:
    """
    Find every game on disk.

    Returns:
        Mapping of slug to manifest, sorted by slug. A directory whose
        manifest will not parse is logged and skipped rather than raising --
        one broken game must not hide the working ones from the picker.
    """
    from engine.games import manifest as manifest_module

    root = games_root()
    found: dict[str, GameManifest] = {}
    if not root.is_dir():
        logger.warning("[games] No games directory (operation=discover, path=%s)", root)
        return found

    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        path = child / MANIFEST_FILENAME
        if not path.is_file():
            continue
        if not SLUG_RE.match(child.name):
            logger.warning(
                "[games] Skipping game with an unusable slug "
                "(operation=discover, slug=%s)",
                child.name,
            )
            continue
        try:
            found[child.name] = manifest_module.load(path)
        except ManifestError as exc:
            logger.warning("[games] Skipping unloadable game (operation=discover): %s", exc)

    logger.info(
        "[games] Discovered games (operation=discover, count=%d, slugs=%s)",
        len(found),
        sorted(found),
    )
    return found


def get(slug: str) -> Optional[GameManifest]:
    """Load one manifest by slug, or None if there is no such game."""
    path = games_root() / str(slug) / MANIFEST_FILENAME
    if not path.is_file():
        return None
    from engine.games import manifest as manifest_module

    try:
        return manifest_module.load(path)
    except ManifestError as exc:
        logger.warning("[games] Manifest will not load (operation=get, slug=%s): %s", slug, exc)
        return None


# ---------------------------------------------------------------------------
# validation
# ---------------------------------------------------------------------------


def validate(manifest: GameManifest) -> list[str]:
    """
    Check a manifest against this engine and this filesystem.

    Args:
        manifest: The manifest to check.

    Returns:
        A list of human-readable problems, empty when the game is sound.
        Every problem is collected -- a manifest with four missing files
        should say so once, not across four launch attempts.
    """
    problems: list[str] = []

    if not SLUG_RE.match(manifest.slug):
        problems.append(f"slug {manifest.slug!r} is not a usable directory name")

    if not manifest.title.strip():
        problems.append("title is empty")

    if not satisfies(ENGINE_VERSION, manifest.engine_requires):
        problems.append(
            f"engine {ENGINE_VERSION} does not satisfy "
            f"engine_requires {manifest.engine_requires!r}"
        )

    if not manifest.paths:
        problems.append("declares no paths, so it cannot differ from the engine defaults")

    for key, value in sorted(manifest.paths.items()):
        if not str(value).strip():
            problems.append(f"paths.{key} is empty")
            continue
        resolved = manifest.resolve(value)
        if key in OUTPUT_PATH_KEYS:
            if not resolved.parent.is_dir():
                problems.append(
                    f"paths.{key} -> {value} lives in a directory that does not exist"
                )
        elif not resolved.exists():
            problems.append(f"paths.{key} -> {value} does not exist")

    if not manifest.entry_location:
        problems.append("entry.location_id is missing, so a new run has nowhere to start")
    if not manifest.archetypes:
        problems.append("entry.archetypes is empty, so character creation has nothing to offer")

    if problems:
        logger.warning(
            "[games] Manifest failed validation (operation=validate, slug=%s, problems=%d)",
            manifest.slug,
            len(problems),
        )
    return problems


# ---------------------------------------------------------------------------
# activation
# ---------------------------------------------------------------------------


def resolve_slug(explicit: Optional[str] = None) -> str:
    """
    Decide which game to run.

    Args:
        explicit: A slug from the command line, or None.

    Returns:
        The chosen slug: the argument, else ``CLOCKWORK_GAME``, else
        ``game.default`` from config, else ``clockwork-dark``.
    """
    if explicit and str(explicit).strip():
        return str(explicit).strip()
    from_env = os.environ.get(GAME_ENV_VAR, "").strip()
    if from_env:
        return from_env
    return str(get_config().get("game.default", DEFAULT_SLUG) or DEFAULT_SLUG)


def activate(slug: Optional[str] = None) -> GameManifest:
    """
    Make a game the active one.

    Installs the manifest's ``paths`` as the top config layer, then invalidates
    every content cache built from the previous paths. Activation is atomic
    from a caller's point of view: a manifest that fails validation raises
    before anything is repointed, so a failed swap leaves the previous game
    running rather than a half-loaded hybrid of the two.

    Args:
        slug: Game to activate, or None to use ``resolve_slug()``.

    Returns:
        The activated manifest.

    Raises:
        ActivationError: No such game, or the manifest failed validation.
    """
    global _active

    with _lock:
        chosen = resolve_slug(slug)
        manifest = get(chosen)
        if manifest is None:
            available = sorted(discover())
            raise ActivationError(
                chosen, [f"no games/{chosen}/{MANIFEST_FILENAME}; available: {available}"]
            )

        problems = validate(manifest)
        if problems:
            raise ActivationError(chosen, problems)

        # set_overlay() calls reset_config(), which calls reset_all_caches().
        # One call site, so there is no ordering to get wrong.
        set_overlay(manifest.config_overlay())
        _active = manifest

        logger.info(
            "[games] Game activated (operation=activate, slug=%s, title=%s, "
            "version=%s, paths=%d, caches=%d)",
            manifest.slug,
            manifest.title,
            manifest.version,
            len(manifest.paths),
            len(registered_caches()),
        )
        return manifest


def deactivate() -> None:
    """
    Drop the active game and its config overlay.

    Leaves the engine on ``config/default.yaml``'s paths, which are the
    flagship game's. Tests use this to get back to the baseline.
    """
    global _active
    with _lock:
        _active = None
        set_overlay(None)
        logger.info("[games] Game deactivated (operation=deactivate)")


def active() -> GameManifest:
    """
    The manifest currently in force, activating the default game if needed.

    Callers that must not trigger activation as a side effect should use
    ``active_slug()`` or ``peek()`` instead.

    Returns:
        The active manifest.

    Raises:
        ActivationError: Nothing is active and the default game will not load.
    """
    if _active is None:
        return activate()
    return _active


def peek() -> Optional[GameManifest]:
    """The active manifest, or None. Never activates anything."""
    return _active


def active_slug() -> str:
    """
    Slug of the active game, without forcing activation.

    This is what the save namespace is built from, and ``saves_root()`` is
    called on paths where an implicit YAML load and a dozen cache resets would
    be a genuinely surprising side effect. So it answers from the resolution
    rules instead: an unactivated process is, by definition, running whatever
    ``resolve_slug()`` would pick.
    """
    if _active is not None:
        return _active.slug
    return resolve_slug()


def catalog() -> list[dict[str, Any]]:
    """
    Every discovered game as picker-ready dicts, newest problems included.

    Returns:
        One dict per game with the manifest fields plus ``playable`` and
        ``problems``, sorted with playable games first and then by title. This
        is the payload behind ``GET /api/games``.
    """
    current = active_slug()
    rows: list[dict[str, Any]] = []
    for slug, manifest in discover().items():
        problems = validate(manifest)
        row = manifest.to_dict()
        row["playable"] = not problems
        row["problems"] = problems
        row["active"] = slug == current
        rows.append(row)
    rows.sort(key=lambda r: (not r["playable"], str(r["title"]).lower()))
    return rows


__all__ = [
    "DEFAULT_SLUG",
    "GAME_ENV_VAR",
    "ActivationError",
    "activate",
    "active",
    "active_slug",
    "catalog",
    "deactivate",
    "discover",
    "games_root",
    "get",
    "peek",
    "reset_all_caches",
    "resolve_slug",
    "validate",
]
