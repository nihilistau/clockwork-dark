"""
Game Manifest
=============

``games/<slug>/game.yaml`` -- the whole of what makes a game a game.

A manifest is a small, bounded set of things:

    identity    id, title, version, blurb -- what the picker shows
    a gate      engine_requires -- refuse to load content this build cannot run
    a repoint   paths: deep-merged over the config's ``paths:`` block
    settings:   a SHORT allowlist of engine settings a story may declare
    an entry    where a new run starts and what it may start as
    a state     state: -- the story's own meters, clocks and tracks
    save rows   save_summary: -- which declared values the load menu shows

Most of what a story needs is already content. The engine reads locations,
quests, encounters, factions, rumours, schedules, items, recipes, economy,
rules and art out of ``paths.*`` keys, so a manifest that rewrites those keys
rewrites the game. That is the whole trick, and it is the source project's
idea -- what was missing there was the manifest, the loader, and any way to
validate that the paths point at files that exist.

    id: tide-and-bell
    title: "Tide and Bell"
    version: "0.1.0"
    engine_requires: ">=0.2.0"
    blurb: "A sunken cathedral-organ plays the tide, and the tide answers."
    paths:
      locations: "games/tide-and-bell/data/world/locations.yaml"
      quests: "games/tide-and-bell/data/quests"
    settings:
      world:
        tick_hours: 1.0
    entry:
      location_id: bellfounders_quay
      archetypes: [net_mender, lamp_keeper, bell_founder]
    save_summary: [tide, chapter]

WHY ``settings:`` IS AN ALLOWLIST AND NOT A CONFIG MERGE. ``config_overlay()``
returned ``{"paths": ...}`` and nothing else, deliberately -- a story that could
merge arbitrary config could repoint ``paths.saves`` under another story's runs,
rewrite ``lmstudio.api_key`` (which resolves a gitignored secret file), or set
``stack.services.*.command``, which is arbitrary code executed on the player's
machine at launch. That ceiling is right about the danger and wrong about the
need: a story genuinely cannot declare its own clock rate, its reveal thresholds
or its governance chain today, so every story inherits The Clockwork Dark's
pacing whether it wants it or not.

So ``settings:`` merges only the keys in ``SETTING_ALLOWLIST`` below, each one
listed with the reason it is safe AND the reason a story needs it. A key outside
the list is a validation problem, not a silent drop: a story that thinks it
changed a setting and did not is worse than a story that refuses to launch.

Version: v0.2.0 [2026-08-08]
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

# Config keys a story may declare under ``settings:``, each with WHY it is on
# the list. Dotted, and matched on the whole key -- a value nested any deeper
# than the entries here flattens to a longer key and is refused.
#
# The test for membership is: does this number describe the STORY's shape, and
# would a wrong value cost the player nothing but a different game? Anything
# describing the MACHINE (endpoints, credentials, GPU budgets, ports, service
# commands) is the player's, not the author's, and stays off.
SETTING_ALLOWLIST: dict[str, str] = {
    # -- the world clock and turn shape ---------------------------------
    # R-03: the clock runs at ~11.5 in-game hours per turn, and every constant
    # feeding it was chosen against a doom story that lasts forty days. A story
    # built on a ten-day chapter structure has to be able to say so.
    "world.tick_hours": "in-game hours one background tick grants",
    "world.tick_max_hours": "ceiling on a single tick, however long the player was away",
    "world.tick_interval_seconds": "real seconds between background ticks",
    # R-06: every playstyle converging on the same doomsday clock is this
    # constant. A story with no doom clock at all sets it to 0.
    "world.evil_base_rate_per_day": "how fast background pressure accrues per in-game day",
    # -- what the player is told, and when ------------------------------
    # Reveal thresholds are pure story pacing: they decide when the narration
    # stops being coy. Nothing outside the prompt layer reads them.
    "awareness.reveal_threshold": "awareness at which the story stops hiding itself",
    "awareness.reflection_form_min": "awareness at which reflective narration unlocks",
    "awareness.spoiler_gate_threshold": "awareness below which lore is withheld",
    "assistant.reflection_awareness_min": "awareness at which the companion reflects",
    # -- the governance chain -------------------------------------------
    # These name interceptor CLASSES that already exist in this build; the
    # chains are resolved by name and an unknown name is skipped with a warning
    # (engine/agents/governance.py). A story therefore chooses among shipped
    # behaviours -- it cannot introduce code. Without this a second story is
    # forced through EvilPhaseTone and DoomSignsInterceptor, which narrate a
    # doom clock it does not have.
    "comms.interceptors": "per-message interceptor chain, by class name",
    "governance.directives": "GM prompt directive chain, by class name",
    "governance.commit": "pre-commit governor chain (veto authority), by class name",
    "governance.post": "post-turn governor chain, by class name",
    "governance.media": "media governor chain, by class name",
    # -- set-piece pacing -------------------------------------------------
    # Budget and skip window only ever REDUCE what fires; neither can turn
    # generation on. The cost decision (media.live_generation, image_provider,
    # grok_timeout_seconds) stays with whoever owns the GPU.
    "media.cutscene_budget": "which beats are allowed to spend a cutscene",
    "media.cutscene_skip_after_seconds": "how long a cutscene holds before it can be skipped",
}

# Prefixes refused with a specific reason rather than the generic "not
# allowed". A story author reaching for one of these has a real intent, and a
# message naming the danger is worth more than a list of legal keys.
SETTING_REFUSALS: tuple[tuple[str, str], ...] = (
    ("paths", "paths belong in the manifest's own 'paths:' block, not settings"),
    ("lmstudio", "model endpoint, credentials and token budgets belong to the machine"),
    ("stack", "service roots and commands are code executed on the player's machine"),
    ("scene", "bind host and port belong to the machine"),
    ("game", "a story must not choose which story runs next"),
    ("comfyui", "service endpoint belongs to the machine"),
    ("tts", "service endpoint and measured per-machine performance settings"),
    ("stt", "service endpoint and measured per-machine performance settings"),
)

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


def flatten_settings(block: Any, prefix: str = "") -> dict[str, Any]:
    """
    Turn a nested ``settings:`` mapping into dotted keys.

    ``{"world": {"tick_hours": 1.0}}`` becomes ``{"world.tick_hours": 1.0}``.
    Descent stops at anything that is not a mapping, so a list value (the
    interceptor chains) arrives whole.

    An empty mapping contributes NOTHING rather than a bare key. ``settings: {}``
    and ``settings: {world: {}}`` both have to be legal no-ops: an author
    stubbing out a section should not be told the section name is a forbidden
    setting.
    """
    out: dict[str, Any] = {}
    if not isinstance(block, dict):
        return out
    for key, value in block.items():
        dotted = f"{prefix}{key}"
        if isinstance(value, dict):
            out.update(flatten_settings(value, prefix=f"{dotted}."))
        else:
            out[dotted] = value
    return out


def _nest(target: dict[str, Any], dotted: str, value: Any) -> None:
    """Write ``a.b.c = value`` into a nested dict, creating the branches."""
    parts = dotted.split(".")
    node = target
    for part in parts[:-1]:
        child = node.get(part)
        if not isinstance(child, dict):
            child = {}
            node[part] = child
        node = child
    node[parts[-1]] = value


def refusal_reason(dotted: str) -> str:
    """
    Why a settings key is refused, in words an author can act on.

    Args:
        dotted: The flattened settings key.

    Returns:
        A reason. Falls back to a generic message for a key that is neither
        allowlisted nor in a known-dangerous section -- most often a typo.
    """
    head = dotted.split(".", 1)[0]
    for prefix, reason in SETTING_REFUSALS:
        if head == prefix:
            return reason
    return "not an engine setting a story may declare"


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
        settings: Engine settings this story declares. Only keys in
            ``SETTING_ALLOWLIST`` reach the config; the rest are validation
            problems. Absent is legal and means "the engine's numbers".
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
    settings: dict[str, Any] = field(default_factory=dict)
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

    @property
    def ui_plugin(self) -> str:
        """
        Which client plugin draws this story. Empty means "core alone".

        DECLARED, NOT INFERRED. The client used to pick a plugin by matching the
        server's slug against a directory name under ``ui/src/stories/``, which
        made the two impossible to share: a story wanting another's look had to
        ship a directory named after itself, and every such directory becomes
        its own build chunk in the COMMITTED ``dist/`` tree. So a scratch story
        that only wanted to borrow an existing skin could not do it without
        leaving build artefacts in the repository.

        Naming it here costs nothing for the stories that already match -- an
        omitted ``ui.plugin`` falls back to the slug, which is exactly the old
        behaviour -- and it lets a story say "draw me like that one".
        """
        block = self.extras.get("ui")
        if isinstance(block, dict):
            return str(block.get("plugin") or "").strip()
        return ""

    @property
    def state_schema_path(self) -> Optional[Path]:
        """
        Where this story declares its state, or None if it declares none.

        Defaults to ``state.yaml`` beside the manifest, so a story does not have
        to say the obvious thing. Absent is legal and means "runs on the engine
        spine alone" -- which keeps this layer additive rather than a new
        mandatory file for every existing game.
        """
        declared = str(self.extras.get("state") or "").strip()
        if declared:
            return self.resolve(declared) if self.root is None else (self.root / declared)
        if self.root is None:
            return None
        candidate = self.root / "state.yaml"
        return candidate if candidate.is_file() else None

    @property
    def save_summary(self) -> tuple[str, ...]:
        """
        Declared state values the load menu shows for this story, in order.

        Empty means "the engine's own row", which is what both shipped games
        get and is why their ``index.json`` rows are unchanged. A story with no
        doom clock and no archetype declares its own names here instead of
        inheriting twelve Clockwork-shaped columns it cannot fill.
        """
        raw = self.extras.get("save_summary") or ()
        if isinstance(raw, str):
            return (raw,)
        if isinstance(raw, (list, tuple)):
            return tuple(str(name) for name in raw)
        return ()

    # -- settings ----------------------------------------------------------

    def flat_settings(self) -> dict[str, Any]:
        """This manifest's ``settings:`` block as dotted config keys."""
        return flatten_settings(self.settings)

    def allowed_settings(self) -> dict[str, Any]:
        """Only the declared settings this engine will honour, dotted."""
        return {
            key: value
            for key, value in self.flat_settings().items()
            if key in SETTING_ALLOWLIST
        }

    def refused_settings(self) -> dict[str, str]:
        """Declared settings this engine refuses, mapped to the reason why."""
        return {
            key: refusal_reason(key)
            for key in sorted(self.flat_settings())
            if key not in SETTING_ALLOWLIST
        }

    def config_overlay(self) -> dict[str, Any]:
        """
        The config layer this manifest installs.

        ``paths`` merges exactly as it always has. ``settings`` merges only the
        allowlisted keys -- a refused key never reaches the config even if
        validation was somehow skipped, because the filter lives here rather
        than in the caller.

        ``entry``, ``state`` and ``save_summary`` are game data read through the
        registry, NOT config settings. Putting them in the config would give
        them two homes and let a stale ``config/local.yaml`` silently move a
        game's starting location.
        """
        overlay: dict[str, Any] = {"paths": dict(self.paths)}
        for dotted, value in self.allowed_settings().items():
            _nest(overlay, dotted, value)
        return overlay

    def resolve(self, relative: str) -> Path:
        """Resolve a manifest-relative or repo-relative path to an absolute one."""
        candidate = Path(str(relative))
        return candidate if candidate.is_absolute() else (project_root() / candidate)

    def to_dict(self) -> dict[str, Any]:
        """Serialisable form. This is what ``GET /api/games`` returns."""
        row: dict[str, Any] = {
            "slug": self.slug,
            "id": self.slug,
            "title": self.title,
            "version": self.version,
            "engine_requires": self.engine_requires,
            "blurb": self.blurb,
            "entry_location": self.entry_location,
            "archetypes": self.archetypes,
            "paths": dict(self.paths),
            # Flattened to a stable key rather than left for the client to dig
            # out of the raw `ui:` block below. Empty means "this story's own
            # slug", which is what every story did before the key existed.
            "ui_plugin": self.ui_plugin or self.slug,
            **{k: v for k, v in self.extras.items() if k not in {"paths", "entry"}},
        }
        # Emitted only when declared. A story that declares no settings must
        # produce the payload it produced before this key existed -- the picker
        # and its tests are entitled to a stable shape.
        allowed = self.allowed_settings()
        if allowed:
            row["settings"] = allowed
        return row


_KNOWN_KEYS = {
    "id",
    "title",
    "version",
    "engine_requires",
    "blurb",
    "paths",
    "settings",
    "entry",
}


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
    settings_raw = data.get("settings") or {}
    settings = dict(settings_raw) if isinstance(settings_raw, dict) else {}

    return GameManifest(
        slug=slug,
        title=str(data.get("title") or slug),
        version=str(data.get("version") or "0.0.0"),
        engine_requires=str(data.get("engine_requires") or ""),
        blurb=str(data.get("blurb") or ""),
        paths=paths,
        settings=settings,
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
    "SETTING_ALLOWLIST",
    "SETTING_REFUSALS",
    "SLUG_RE",
    "GameManifest",
    "ManifestError",
    "flatten_settings",
    "from_dict",
    "load",
    "parse_version",
    "refusal_reason",
    "satisfies",
]
