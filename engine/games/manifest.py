"""
Game Manifest
=============

``games/<slug>/game.yaml`` -- the whole of what makes a game a game.

A manifest is three things and deliberately nothing else:

    identity    id, title, version, blurb -- what the picker shows
    a gate      engine_requires -- refuse to load content this build cannot run
    a repoint   paths: deep-merged over the config's ``paths:`` block
    an entry    where a new run starts and what it may start as

Everything else a story needs is already content. The engine reads locations,
quests, encounters, factions, rumours, schedules, items, recipes, economy,
rules and art out of ``paths.*`` keys, so a manifest that rewrites those keys
rewrites the game. That is the whole trick, and it is the source project's
idea -- what was missing there was the manifest, the loader, and any way to
validate that the paths point at files that exist.

    id: drowned-carillon
    title: "The Drowned Carillon"
    version: "0.1.0"
    engine_requires: ">=0.2.0"
    blurb: "A sunken cathedral-organ plays the tide, and the tide answers."
    paths:
      locations: "games/drowned-carillon/data/world/locations.yaml"
      quests: "games/drowned-carillon/data/quests"
    entry:
      location_id: bellfounders_quay
      archetypes: [net_mender, lamp_keeper, bell_founder]

Version: v0.1.0 [2026-08-08]
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml

from engine.config import project_root

logger = logging.getLogger(__name__)

MANIFEST_FILENAME = "game.yaml"

# Path keys the engine WRITES rather than reads.
#
# Validation demands that every declared path exists, which is right for
# content and wrong for these two: the save directory is created on first save
# and the lore index is built by scripts/seed_lore.py. Requiring them to exist
# would mean a freshly cloned game cannot be activated until someone has
# already played it. Their PARENT directory is checked instead, which still
# catches the failure that matters -- a path pointing into a directory that
# does not exist.
OUTPUT_PATH_KEYS = frozenset({"saves", "lore_db"})

# Slugs become directory names, config values, save-directory names and URL
# path segments. Keep them boring.
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,63}$")

_SPECIFIER_RE = re.compile(r"^\s*(>=|<=|==|!=|>|<)?\s*([0-9]+(?:\.[0-9]+)*)\s*$")


class ManifestError(ValueError):
    """A manifest that cannot be parsed at all."""


def parse_version(text: str) -> tuple[int, ...]:
    """
    Turn ``"0.2.0"`` into ``(0, 2, 0)``.

    Non-numeric tails are dropped rather than raising: a build tagged
    ``0.2.0-rc1`` compares as ``0.2.0``, which is the answer a gate wants.
    """
    parts: list[int] = []
    for chunk in str(text).strip().split("."):
        match = re.match(r"^(\d+)", chunk)
        if match is None:
            break
        parts.append(int(match.group(1)))
    return tuple(parts) or (0,)


def _pad(left: tuple[int, ...], right: tuple[int, ...]) -> tuple[tuple[int, ...], tuple[int, ...]]:
    """Zero-pad two version tuples to equal length so 0.2 == 0.2.0."""
    width = max(len(left), len(right))
    return (
        left + (0,) * (width - len(left)),
        right + (0,) * (width - len(right)),
    )


def satisfies(engine_version: str, requirement: str) -> bool:
    """
    Test an engine version against a requirement string.

    Args:
        engine_version: The running engine's version, e.g. ``"0.2.0"``.
        requirement: Comma-separated specifiers, e.g. ``">=0.2.0, <1.0"``. An
            empty requirement is satisfied by anything. A bare version means
            ``>=`` -- a manifest saying ``0.2.0`` means "needs at least this",
            which is what every author who omits the operator intends.

    Returns:
        True if every specifier holds. An unparseable specifier is logged and
        treated as satisfied: refusing to launch over a typo in a gate is a
        worse failure than launching.
    """
    requirement = str(requirement or "").strip()
    if not requirement:
        return True

    have = parse_version(engine_version)
    for raw in requirement.split(","):
        if not raw.strip():
            continue
        match = _SPECIFIER_RE.match(raw)
        if match is None:
            logger.warning(
                "[games] Unreadable version specifier, ignoring "
                "(operation=satisfies, specifier=%r)",
                raw,
            )
            continue
        operator = match.group(1) or ">="
        want = parse_version(match.group(2))
        left, right = _pad(have, want)
        ok = {
            ">=": left >= right,
            "<=": left <= right,
            "==": left == right,
            "!=": left != right,
            ">": left > right,
            "<": left < right,
        }[operator]
        if not ok:
            return False
    return True


@dataclass(frozen=True)
class GameManifest:
    """
    One parsed ``game.yaml``.

    Attributes:
        slug: Directory name under ``games/``. Authoritative identity -- the
            manifest's ``id`` must agree with it, and validation says so if it
            does not, because the directory is what the CLI and the save path
            actually use.
        title: Display name for the picker.
        version: The game's own content version, unrelated to the engine's.
        engine_requires: Version gate checked at activation.
        blurb: One or two sentences for the picker card.
        paths: Config ``paths.*`` overrides, repo-relative.
        entry: Starting state -- ``location_id`` and offered ``archetypes``.
        root: Absolute path to ``games/<slug>/``.
        extras: Any other top-level key, kept verbatim so a manifest can carry
            data this dataclass has not learned about yet.
    """

    slug: str
    title: str
    version: str = "0.0.0"
    engine_requires: str = ""
    blurb: str = ""
    paths: dict[str, str] = field(default_factory=dict)
    entry: dict[str, Any] = field(default_factory=dict)
    root: Optional[Path] = None
    extras: dict[str, Any] = field(default_factory=dict)

    # -- derived -----------------------------------------------------------

    @property
    def entry_location(self) -> str:
        """Location id a new run starts in. Empty when the manifest omits it."""
        return str(self.entry.get("location_id") or "")

    @property
    def archetypes(self) -> list[str]:
        """Archetype ids this game offers at character creation."""
        raw = self.entry.get("archetypes") or []
        if isinstance(raw, (list, tuple)):
            return [str(a) for a in raw]
        return [str(raw)]

    def config_overlay(self) -> dict[str, Any]:
        """
        The config layer this manifest installs.

        Only ``paths`` is merged. ``entry`` is game data read through the
        registry, not a config setting -- putting it in the config would give
        it two homes and let a stale ``config/local.yaml`` silently move a
        game's starting location.
        """
        return {"paths": dict(self.paths)}

    def resolve(self, relative: str) -> Path:
        """Resolve a manifest-relative or repo-relative path to an absolute one."""
        candidate = Path(str(relative))
        return candidate if candidate.is_absolute() else (project_root() / candidate)

    def to_dict(self) -> dict[str, Any]:
        """Serialisable form. This is what ``GET /api/games`` returns."""
        return {
            "slug": self.slug,
            "id": self.slug,
            "title": self.title,
            "version": self.version,
            "engine_requires": self.engine_requires,
            "blurb": self.blurb,
            "entry_location": self.entry_location,
            "archetypes": self.archetypes,
            "paths": dict(self.paths),
            **{k: v for k, v in self.extras.items() if k not in {"paths", "entry"}},
        }


_KNOWN_KEYS = {"id", "title", "version", "engine_requires", "blurb", "paths", "entry"}


def from_dict(data: dict[str, Any], *, slug: str, root: Optional[Path] = None) -> GameManifest:
    """
    Build a manifest from an already-parsed document.

    Args:
        data: The parsed YAML mapping.
        slug: Directory name, used as the authoritative id.
        root: Absolute path to the game directory.

    Returns:
        A GameManifest. Never raises for missing optional keys -- absence is
        reported by ``registry.validate`` so one bad manifest surfaces every
        one of its problems at once instead of the first.
    """
    paths_raw = data.get("paths") or {}
    paths = (
        {str(k): str(v) for k, v in paths_raw.items()}
        if isinstance(paths_raw, dict)
        else {}
    )
    entry_raw = data.get("entry") or {}
    entry = dict(entry_raw) if isinstance(entry_raw, dict) else {}

    return GameManifest(
        slug=slug,
        title=str(data.get("title") or slug),
        version=str(data.get("version") or "0.0.0"),
        engine_requires=str(data.get("engine_requires") or ""),
        blurb=str(data.get("blurb") or ""),
        paths=paths,
        entry=entry,
        root=root,
        extras={k: v for k, v in data.items() if k not in _KNOWN_KEYS},
    )


def load(path: Path) -> GameManifest:
    """
    Read one ``games/<slug>/game.yaml``.

    Args:
        path: Path to the manifest file.

    Returns:
        The parsed manifest, with slug taken from the parent directory name.

    Raises:
        ManifestError: The file is unreadable, is not YAML, or is not a
            mapping. Discovery catches this and skips the directory; a direct
            ``activate`` lets it out, because being asked for a specific
            broken game is not something to paper over.
    """
    try:
        with path.open(encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
    except (OSError, yaml.YAMLError) as exc:
        raise ManifestError(f"Unreadable manifest at {path}: {exc}") from exc

    if not isinstance(data, dict):
        raise ManifestError(f"Manifest at {path} is not a mapping")

    root = path.parent
    manifest = from_dict(data, slug=root.name, root=root)

    declared = str(data.get("id") or "").strip()
    if declared and declared != manifest.slug:
        # Not fatal: the directory wins, because it is what the CLI, the save
        # namespace and the API all address. But say so loudly -- a mismatch
        # means someone renamed one of the two and not the other.
        logger.warning(
            "[games] Manifest id disagrees with its directory "
            "(operation=load, dir=%s, id=%s)",
            manifest.slug,
            declared,
        )
    return manifest


__all__ = [
    "MANIFEST_FILENAME",
    "OUTPUT_PATH_KEYS",
    "SLUG_RE",
    "GameManifest",
    "ManifestError",
    "from_dict",
    "load",
    "parse_version",
    "satisfies",
]
