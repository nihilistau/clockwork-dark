"""
Configuration Manager
=====================

Layered YAML config with environment overrides.

Layers, later wins, deep-merged:

    config/default.yaml     checked in; the documented shape of every setting
    config/<env>.yaml       CLOCKWORK_ENV, e.g. development
    config/local.yaml       gitignored; machine-specific paths live here
                            (skipped in a child of the test suite, which also
                            gets the sandbox layer last and the discard
                            llm.base_url: ``child_sandbox``; no deployment
                            sets its marker, CLOCKWORK_TEST_SANDBOX)
    <the admin layer>       hosted only: <data root>/hosting/admin.yaml, the
                            admin panel's edits, merged when hosting.enabled
                            is on in every other layer and the file exists;
                            allowlisted keys only (v0.20.0 T14, spec §14.9)
    $CLOCKWORK_CONFIG     optional; an operator's file(s) outside the repo,
                            joined by os.pathsep, merged left to right; a
                            missing or unparsable one is an error (v0.20.0)
    <game overlay>          the active game manifest's ``paths:`` block

An operator layer holding a name removed in v0.21.0 (``lmstudio:``,
``stack.services.lmstudio``, ``paths.saves``) is refused at load: see
``LegacyConfigError``.

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
import re
import threading
from pathlib import Path
from typing import Any, Optional

import yaml

from engine.locks import renew_after_fork

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parent.parent
_CONFIG_DIR = _ROOT / "config"
_DEFAULT_PATH = _CONFIG_DIR / "default.yaml"

_instance: Optional["ConfigManager"] = None
#: The pid ``_instance`` was built in: a forked child rebuilds (``get_config``).
_instance_pid: Optional[int] = None

#: THE CONFIG LOCK (v0.20.0: many sessions, one process). Taken to build the
#: singleton (double-checked: a built instance is one read, no lock), to drop
#: it (``reset_config``, ``set_overlay``) and to fill ``_story_paths_by_slug``
#: on a miss. Re-entrant, because a manifest read on that miss can ask for
#: config again.
#:
#: INNERMOST in the engine's one lock order (``engine/locks.py``): every other
#: lock's holder may call ``get_config``, so nothing holding this one takes
#: another. That is why ``reset_config`` drops the instance under it but walks
#: the cache resets (``reset_backend``, ``reset_lanes`` ...) after releasing
#: it, and why warming holds its own lock, not this one.
_config_lock = threading.RLock()
renew_after_fork(globals(), _config_lock=threading.RLock)

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

# -- the model server's block, and the names v0.21.0 refuses ----------------

#: The model server's block.
LLM_BLOCK = "llm"


class ConfigError(ValueError):
    """
    A config the engine refuses to load (v0.21.0). A ``ValueError``, so every
    caller that already stops on a bad layer -- the launcher, the doctor, the
    supervisor's preflight -- stops on this too.
    """


class LegacyConfigError(ConfigError):
    """
    An operator layer holds a key no longer read (spec §10.2): ``lmstudio:``
    (``llm:`` since v0.19.0), ``stack.services.lmstudio``
    (``stack.services.llm``) or ``paths.saves`` (``storage.root`` since
    v0.20.0). Raised by ``get_config`` with EVERY finding of the layers it
    read, so the doctor lists each as a row and an operator fixes them in one
    pass.

    Attributes:
        findings: ``(file, dotted key, message)`` per refused key, in layer order.
    """

    def __init__(self, findings: list[tuple[str, str, str]]) -> None:
        self.findings = list(findings)
        super().__init__("\n".join(message for _, _, message in self.findings))


#: The keys an operator layer may no longer hold, each with its one-line
#: refusal (``{file}`` is the layer's path). Refused, never ignored: an
#: ignored ``lmstudio:`` block points the game at the shipped default server,
#: and an ignored ``paths.saves`` hides every save in the old folder.
LEGACY_REFUSALS: tuple[tuple[str, str], ...] = (
    (
        "lmstudio",
        '{file}: the "lmstudio:" block was renamed "llm:" in v0.19.0 and is no longer read '
        '(v0.21.0). Rename the block; "ttl_seconds" inside it is now "keep_alive_seconds".',
    ),
    (
        "stack.services.lmstudio",
        '{file}: "stack.services.lmstudio" was renamed "stack.services.llm" in v0.19.0 and '
        "is no longer read (v0.21.0).",
    ),
    (
        "paths.saves",
        '{file}: "paths.saves" is no longer read (v0.21.0). Saves live under storage.root as '
        "<root>/saves: set storage.root (or CLOCKWORK_DATA_DIR) to the folder that holds your "
        "saves folder, or move the saves there.",
    ),
)


def legacy_findings(layer: Any, source: str) -> list[tuple[str, str, str]]:
    """
    ``(source, dotted key, message)`` for each ``LEGACY_REFUSALS`` key that
    ``layer`` holds (present at all, whatever its value), in table order.
    """
    found: list[tuple[str, str, str]] = []
    if not isinstance(layer, dict):
        return found
    for dotted, template in LEGACY_REFUSALS:
        node: Any = layer
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                break
            node = node[part]
        else:
            found.append((source, dotted, template.format(file=source)))
    return found


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


#: A secrets-chain scope: the text before an alternative's first ``?``, when
#: it holds no ``:`` (spec §2.2). A ``file:`` or ``env:`` alternative always
#: has its ``:`` first, so ``file:/srv/keys/what?.txt`` is never scoped (N1);
#: a bare variable name never holds a ``?``, so anything else before one is a
#: scope, and ``check_scopes`` refuses it at load unless it names a provider,
#: compared ignoring case (fix round 1: ``^[a-z_]+$`` let ``lm-studio?`` and
#: ``LMStudio?`` through as variable names that are never set).
SCOPE_RE = re.compile(r"[^:]*")


def split_scope(alternative: str) -> tuple[Optional[str], str]:
    """
    One ``${...}`` alternative as ``(scope, the rest)``, or ``(None, whole)``.

    Scoped when it holds a ``?`` and the text before the FIRST one matches
    ``SCOPE_RE`` (no ``:``); anything else is a whole, unscoped alternative.
    The scope is returned as written: compare it with ``scope_matches``.
    """
    alternative = alternative.strip()
    head, mark, rest = alternative.partition("?")
    if mark and SCOPE_RE.fullmatch(head):
        return head.strip(), rest.strip()
    return None, alternative


def scope_matches(scope: str, provider: str) -> bool:
    """Whether a scope names ``provider``, ignoring case and outer space."""
    return scope.strip().casefold() == str(provider or "").strip().casefold()


def _known_scope(scope: str) -> bool:
    from engine.llm.providers import PROVIDERS

    return any(scope_matches(scope, name) for name in PROVIDERS)


def scoped_alternatives(token: str) -> list[tuple[Optional[str], str]]:
    """A ``${...}`` token's body as its ``(scope, alternative)`` pairs, in order."""
    return [split_scope(part) for part in token.split("|") if part.strip()]


def key_source_name(alternative: str) -> tuple[str, str]:
    """
    A chain alternative as ``(its name as written, "holds a key" | "is set")``:
    a ``file:`` one's file, an ``env:`` or bare one's variable. Shared by the
    doctor's key rows and the admin panel's key row (v0.20.0 T16), so both
    name a source the same way. Never a value.
    """
    if alternative.startswith("file:"):
        return alternative[5:].strip(), "holds a key"
    if alternative.startswith("env:"):
        return alternative[4:].strip(), "is set"
    return alternative, "is set"


def _is_template(value: Any) -> bool:
    return isinstance(value, str) and value.startswith("${") and value.endswith("}")


def _leaves(node: Any, prefix: str = "") -> list[tuple[str, Any]]:
    """Every leaf of a config tree, as ``(dotted key, value)``, in order."""
    if not isinstance(node, dict):
        return [(prefix, node)] if prefix else []
    out: list[tuple[str, Any]] = []
    for key, value in node.items():
        dotted = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, dict) and value:
            out.extend(_leaves(value, dotted))
        else:
            out.append((dotted, value))
    return out


def check_scopes(data: dict[str, Any]) -> None:
    """
    Refuse, at load, a scope that names no provider, and a templated provider.

    N2 (v0.20.0): a misspelt scope (``lmstuido?file:lmstudio.txt``) never
    matched and was never reported. It is the same mistake as an unknown
    ``llm.provider``, and refused the same way, naming the dotted key and the
    scope. N3: ``llm.provider`` selects a code path and is not a secret, so a
    ``${...}`` there is refused outright.

    Run by ``get_config`` on the merged tree, and by the Settings panel on the
    tree it is about to write, so the panel never writes a file the next load
    refuses (``engine/api/settings.py``).

    Raises:
        ValueError: Either.
    """
    from engine.llm.providers import PROVIDERS

    block = data.get(LLM_BLOCK)
    if isinstance(block, dict) and isinstance(block.get("provider"), str):
        if "${" in block["provider"]:
            raise ValueError(
                "llm.provider is a ${...} reference; it selects the model "
                "server's code path, is not a secret, and must be written out: "
                f"one of {', '.join(PROVIDERS)}"
            )
    for dotted, value in _leaves(data):
        if not _is_template(value):
            continue
        for scope, _ in scoped_alternatives(value[2:-1]):
            if scope is not None and not _known_scope(scope):
                raise ValueError(
                    f"{dotted} scopes an alternative to {scope!r}, which is not "
                    f"a model server this build speaks; legal scopes: "
                    f"{', '.join(PROVIDERS)}"
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

        # `live_paths`: a retired key a manifest still declares (`saves`,
        # v0.20.0) answers nothing, exactly as `config_overlay` drops it.
        manifest = registry.peek()
        if manifest is not None:
            return manifest.live_paths()
        slug = registry.resolve_slug()
        cached = _story_paths_by_slug.get(slug)
        if cached is not None:
            return cached
        # A miss is filled under the config lock (once per slug per process).
        with _config_lock:
            cached = _story_paths_by_slug.get(slug)
            if cached is not None:
                return cached
            found = registry.get(slug)
            paths = found.live_paths() if found is not None else {}
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
        #: Where the API key would have come from, ``(kind, name)``, when it
        #: is WITHHELD because an admin moved ``llm.base_url`` to another
        #: origin without sending it there (v0.20.0 T16 fix round 1); None
        #: otherwise. Never the value.
        self.withheld_key: Optional[tuple[str, str]] = None

    def get(self, path: str, default: Any = None) -> Any:
        """
        Return nested value by dot path.

        ``paths.*`` takes one extra step: the engine's config declares those
        keys empty on purpose, so an empty one is answered from the running
        story's manifest instead. See ``_story_path`` for what that costs the
        caller's ``default``.
        """
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
        the token holds a ``|``, so a v0.18 token resolves exactly as it did
        (a lone alternative is scoped too since v0.20.0, but no v0.18 token
        held a ``?`` with no ``:`` before it: no variable name has one).

        An alternative written ``<provider>?<alternative>``
        (``lmstudio?file:lmstudio.txt``) is tried only while ``llm.provider``
        is that provider, compared ignoring case, and skipped otherwise. It is
        scoped when the text before its first ``?`` holds no ``:``
        (``SCOPE_RE``), so ``file:/srv/keys/what?.txt`` is one whole unscoped
        alternative (N1, v0.20.0: it used to be read as the scope
        ``file:/srv/keys/what`` and skipped in silence). A scope that names no
        provider (``lmstuido?``, ``lm-studio?``) is refused when the config
        loads (``check_scopes``), and the provider is read raw
        (``_provider_raw``). The shipped key uses it so
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
            scope, alternative = split_scope(token)
            if scope is None:
                return self._expand_one(token, default)
            if not scope_matches(scope, self._provider_raw()):
                return default
            return self._expand_one(alternative, default)
        for scope, alternative in scoped_alternatives(token):
            if scope is not None and not scope_matches(scope, self._provider_raw()):
                continue
            value = self._expand_one(alternative, None)
            if value:
                return value
        return default

    def secret_source(self, path: str) -> tuple[str, str]:
        """
        Where the value at ``path`` comes from, never the value (v0.20.0 T16,
        spec §14.9: the admin panel shows an API key as present or absent and
        its source): ``("environment", <variable>)``, ``("file", <file as
        written>)``, ``("config", <path>)`` for a literal value in a layer, or
        ``("", "")`` when nothing answers. A ``${...}`` chain is walked as
        ``_expand`` walks it -- left to right, a scoped alternative only for
        its provider -- and the first alternative with a value names the
        source. The names come from ``key_source_name``, the doctor's.
        """
        raw = self._raw(path)
        if raw is None or (isinstance(raw, str) and not raw.strip()):
            return "", ""
        if not _is_template(raw):
            return "config", path
        for scope, alternative in scoped_alternatives(raw[2:-1]):
            if scope is not None and not scope_matches(scope, self._provider_raw()):
                continue
            if self._expand_one(alternative, None):
                name, _verb = key_source_name(alternative)
                return ("file" if alternative.startswith("file:") else "environment"), name
        return "", ""

    def _provider_raw(self) -> str:
        """
        ``llm.provider`` as written, for the scope test: read through ``_raw``,
        never ``get``, so a provider that is itself a ``${...}`` chain is a
        string that matches no scope rather than a recursion (N3, v0.20.0).
        ``get_config`` refuses such a provider at load; a hand-built manager
        does not, and must not recurse.
        """
        raw = self._raw("llm.provider", "lmstudio")
        return str(raw or "").strip()

    def _raw(self, path: str, default: Any = None) -> Any:
        """
        The value at a dotted path as the layers hold it: a plain walk, with
        no ``${...}`` expansion and no ``paths.*`` fallback.
        """
        node: Any = self._data
        for part in path.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

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
        """The merged tree."""
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


# -- CLOCKWORK_CONFIG: an operator's file outside the repo (v0.20.0, spec §2.1)

#: The environment variable naming the external layer's file(s).
EXTERNAL_CONFIG_ENV = "CLOCKWORK_CONFIG"

#: The test suite's child-process sandbox marker (v0.20.0, spec §3.5):
#: ``<the suite's pid><os.pathsep><the sandbox config layer's path>``. The
#: suite's conftest writes it into its OWN environment before collection, so
#: every process it starts inherits it, however it is started (``subprocess``,
#: ``os.system``, ``multiprocessing``...). NO DEPLOYMENT SETS IT. It means
#: nothing in the process whose pid it names (the suite itself, so both
#: goldens are unaffected); in any OTHER process it means "a child of the test
#: suite" -- see ``child_sandbox``.
TEST_SANDBOX_ENV = "CLOCKWORK_TEST_SANDBOX"

#: What a sandboxed child's ``llm.base_url`` is forced to: the discard port,
#: which refuses the connection, so no child ever reaches a model server.
TEST_SANDBOX_BASE_URL = "http://127.0.0.1:9/v1"


class ChildSandbox:
    """
    This process is a child of the test suite (``TEST_SANDBOX_ENV``).

    ``layer`` is the sandbox config file the marker names, and ``root`` the
    directory holding it: the only place a sandboxed child may write the
    owner-shaped files (LM Studio's ``mcp.json``). Both are None when the
    marker names no path, and then nothing is writable at all (fail closed).
    """

    def __init__(self, layer: Optional[Path]) -> None:
        self.layer = layer
        self.root = layer.parent if layer is not None else None

    def contains(self, path: Path) -> bool:
        """Whether ``path`` resolves inside ``root`` (never, with no root)."""
        if self.root is None:
            return False
        try:
            Path(path).resolve().relative_to(self.root.resolve())
        except (ValueError, OSError):
            return False
        return True


def child_sandbox() -> Optional[ChildSandbox]:
    """
    The sandbox this process runs in as a child of the test suite, or None.

    None when ``CLOCKWORK_TEST_SANDBOX`` is unset (every real run) or names
    THIS process's pid (the suite itself). Any other value -- another pid, or
    one that does not parse -- is a child, fail closed. While it is set:

    - ``get_config`` never reads ``config/local.yaml``, merges the sandbox
      layer last among the external files, and forces ``llm.base_url`` to
      the discard port, ``llm.api_key`` to the sandbox layer's own (none
      otherwise: v0.20.0 T16 fix round 1) and ``llm.mcp.enabled`` off;
    - ``engine/mcp/skills_server.py``'s two writers refuse a target outside
      ``root`` (every target, with no root);
    - the Settings panel neither reads nor writes ``config/local.yaml``.
    """
    raw = os.environ.get(TEST_SANDBOX_ENV, "").strip()
    if not raw:
        return None
    pid, sep, path = raw.partition(os.pathsep)
    if pid.strip() == str(os.getpid()):
        return None
    _warn_once_sandboxed()
    return ChildSandbox(Path(path.strip()) if sep and path.strip() else None)


#: Set once this process has logged that it runs sandboxed.
_SANDBOX_WARNED = False


def _warn_once_sandboxed() -> None:
    """
    One WARNING per process: a real game with a stray marker (the owner's
    shell exported it) would otherwise just fail every narration, with only an
    INFO line to say why (T5 re-review, N4).
    """
    global _SANDBOX_WARNED
    if _SANDBOX_WARNED:
        return
    _SANDBOX_WARNED = True
    logger.warning(
        "[config] %s is set, so this process runs as a child of a test suite: "
        "config/local.yaml is ignored, the model server and every service are "
        "off, and nothing is saved to the owner's files (operation=child_sandbox). "
        "If this is not a test run, unset %s.",
        TEST_SANDBOX_ENV,
        TEST_SANDBOX_ENV,
    )


def stray_sandbox_message() -> Optional[str]:
    """
    What the doctor and ``launcher.py --check`` say (a FAIL) when this process
    runs sandboxed -- which, outside the test suite, means a stray
    ``CLOCKWORK_TEST_SANDBOX`` in the environment. None otherwise.
    """
    if child_sandbox() is None:
        return None
    return (
        f"{TEST_SANDBOX_ENV} is set: this process runs as a child of a test "
        "suite (config/local.yaml ignored, no model server, nothing saved). "
        f"Unset {TEST_SANDBOX_ENV} unless this is a test run."
    )


#: The loopback port a test's stub model server listens on, registered by the
#: suite's conftest (``tests/conftest.py::sandbox_model_stub``) for the
#: children of that test. A sandboxed child keeps the SANDBOX LAYER's
#: ``llm.base_url`` only when it is loopback on exactly this port; any other
#: value, or no registration, is the discard port (T5 re-review, N3; for the
#: hosted supervisor's stub server, v0.20.0 T16). No deployment sets it.
TEST_MODEL_STUB_PORT_ENV = "CLOCKWORK_TEST_MODEL_STUB_PORT"

#: What every other service URL is forced to in a sandboxed child.
TEST_SANDBOX_SERVICE_URL = "http://127.0.0.1:9"

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def _sandbox_model_url(layer_url: Any) -> str:
    """
    The ``llm.base_url`` a sandboxed child may use: the sandbox layer's own
    value when it is loopback on the registered stub port, else the discard
    port.
    """
    from urllib.parse import urlsplit

    registered = os.environ.get(TEST_MODEL_STUB_PORT_ENV, "").strip()
    if not registered.isdigit() or not isinstance(layer_url, str):
        return TEST_SANDBOX_BASE_URL
    try:
        parts = urlsplit(layer_url)
        port = parts.port
    except ValueError:
        return TEST_SANDBOX_BASE_URL
    host = (parts.hostname or "").lower()
    # Plain http only (v0.20.0 T16, from T5's re-review): the stub is a
    # loopback test server, and no other scheme is one.
    if parts.scheme == "http" and host in _LOOPBACK_HOSTS and port == int(registered):
        return layer_url
    return TEST_SANDBOX_BASE_URL


def _force_sandbox(data: dict[str, Any], sandbox_layer: dict[str, Any]) -> None:
    """
    What a sandboxed child is held to, whatever its layers say: no model
    server but a registered loopback stub, no MCP bridge, no ComfyUI, no TTS,
    no STT server, and no managed service (a marker with no layer merges no
    layer, so these cannot rest on it).
    """
    llm = data.get(LLM_BLOCK)
    if not isinstance(llm, dict):
        llm = data[LLM_BLOCK] = {}
    layer_llm = sandbox_layer.get(LLM_BLOCK) if isinstance(sandbox_layer, dict) else None
    llm["base_url"] = _sandbox_model_url(
        layer_llm.get("base_url") if isinstance(layer_llm, dict) else None
    )
    # No API key but the sandbox layer's own (v0.20.0 T16 fix round 1): the
    # shipped chain reads key files in the repository root (the owner's
    # lmstudio.txt) and LMSTUDIO_API_KEY, and a child of the suite must never
    # read either or send one to a stub. A test that needs a key names it in
    # the sandbox layer (``sandbox_model_stub``'s ``api_key``).
    llm["api_key"] = layer_llm.get("api_key", "") if isinstance(layer_llm, dict) else ""
    mcp = llm.get("mcp") if isinstance(llm.get("mcp"), dict) else {}
    llm["mcp"] = {**mcp, "enabled": False}
    for block, flags in (("comfyui", ("enabled",)), ("tts", ("enabled", "assistant_enabled")), ("stt", ())):
        section = data.get(block)
        if not isinstance(section, dict):
            section = data[block] = {}
        section["base_url"] = TEST_SANDBOX_SERVICE_URL
        for flag in flags:
            section[flag] = False
    stack = data.get("stack")
    services = stack.get("services") if isinstance(stack, dict) else None
    if isinstance(services, dict):
        for spec in services.values():
            if isinstance(spec, dict):
                spec["manage"] = False

#: Each external file the current config merged, with the dotted keys it set.
#: Rebuilt with the singleton.
_external_layers: list[tuple[str, list[str]]] = []


def external_config_paths() -> list[Path]:
    """
    The files ``CLOCKWORK_CONFIG`` names, in merge order.

    Several may be joined by ``os.pathsep`` (``;`` on Windows, ``:`` on
    POSIX): merged left to right, so the last wins. Empty entries are
    ignored, so an unset or empty variable names nothing.
    """
    raw = os.environ.get(EXTERNAL_CONFIG_ENV, "")
    return [Path(part.strip()) for part in raw.split(os.pathsep) if part.strip()]


def _load_external(path: Path) -> dict[str, Any]:
    """
    One ``CLOCKWORK_CONFIG`` file. Unlike every other layer, a file that is
    missing, unreadable, does not parse or is not a mapping is a startup
    ERROR, not a warning: an operator who pointed at a file meant it, and
    running on the defaults instead would, hosted, mean the wrong settings.

    Raises:
        ValueError: Naming the path.
    """
    if not path.is_file():
        raise ValueError(f"{EXTERNAL_CONFIG_ENV} names {path}, which is not a file")
    try:
        with path.open(encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
    except OSError as exc:
        # A permissions problem is not a syntax problem: said as what it is.
        raise ValueError(
            f"{EXTERNAL_CONFIG_ENV} names {path}, which cannot be read "
            f"({type(exc).__name__})"
        ) from None
    except (UnicodeDecodeError, yaml.YAMLError) as exc:
        # Where, never what: this file may hold a secret (rule 5), so the
        # message carries a line and column and none of the file's text
        # (a YAML error parsed from a string quotes the offending line).
        mark = getattr(exc, "problem_mark", None)
        where = (
            f"line {mark.line + 1}, column {mark.column + 1}"
            if mark is not None
            else type(exc).__name__
        )
        raise ValueError(
            f"{EXTERNAL_CONFIG_ENV} names {path}, which does not parse ({where})"
        ) from None
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError(
            f"{EXTERNAL_CONFIG_ENV} names {path}, which is not a mapping of config keys"
        )
    return data


def external_config_layers() -> list[tuple[str, list[str]]]:
    """Each ``CLOCKWORK_CONFIG`` file merged, as ``(path, its dotted keys)``."""
    get_config()
    return [(source, list(keys)) for source, keys in _external_layers]


def external_config_keys() -> list[str]:
    """
    Every dotted key the ``CLOCKWORK_CONFIG`` files set, sorted.
    These outrank ``config/local.yaml``, so the Settings panel cannot change
    them: it names them in its answer (``shadowed``), and the doctor lists
    them. Keys only -- never a value.
    """
    return sorted({key for _, keys in external_config_layers() for key in keys})


# -- the admin layer: the admin panel's edits (v0.20.0 T14, spec §14.9) ------

#: The admin layer the current config merged, ``(path, its dotted keys)``, or
#: None (hosting off, or no file). Rebuilt with the singleton.
_admin_layer: Optional[tuple[str, list[str]]] = None

#: The environment variable that beats ``storage.root`` (``engine.persistence
#: .storage.DATA_DIR_ENV``, which imports this module, so it is restated here).
_DATA_DIR_ENV = "CLOCKWORK_DATA_DIR"

#: ``storage.root`` when no layer sets it (``storage.DEFAULT_ROOT``).
_DEFAULT_DATA_ROOT = "data"


def _truthy_path(data: dict[str, Any], dotted: str) -> bool:
    """Whether ``dotted`` is set truthy in the raw tree (``hosting_enabled``'s reading)."""
    node: Any = data
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return False
        node = node[part]
    return bool(node)


def _admin_layer_path(data: dict[str, Any]) -> Path:
    """
    ``<data root>/hosting/admin.yaml``: the root from ``CLOCKWORK_DATA_DIR``,
    else ``storage.root`` in the tree merged WITHOUT the layer, anchored at
    the project root as ``storage.data_root`` anchors it -- read from that
    tree, never through ``get_config``, which is being built.
    """
    from engine.hosting.admin.model import ADMIN_LAYER_FILE

    raw = os.environ.get(_DATA_DIR_ENV, "").strip()
    if not raw:
        storage = data.get("storage") if isinstance(data, dict) else None
        raw = str((storage or {}).get("root") or "").strip() if isinstance(storage, dict) else ""
        raw = raw or _DEFAULT_DATA_ROOT
    root = Path(os.path.expanduser(raw))
    if not root.is_absolute():
        root = project_root() / root
    return root / "hosting" / ADMIN_LAYER_FILE


def _load_admin_layer(path: Path) -> dict[str, Any]:
    """
    The admin layer, checked: a file that does not parse, is not a mapping,
    or holds a key outside the panel's allowlist (``engine.hosting.admin.model
    .EDITABLE``) is a startup error naming it. Hand edits are possible, and
    checked. Values are never in a message (rule 5).

    Raises:
        ValueError: Naming the path, and the key where one is refused.
    """
    from engine.hosting.admin.model import EDITABLE, LAYER_ONLY

    try:
        with path.open(encoding="utf-8") as handle:
            raw = yaml.safe_load(handle)
    except OSError as exc:
        raise ValueError(f"the admin layer {path} cannot be read ({type(exc).__name__})") from None
    except (UnicodeDecodeError, yaml.YAMLError) as exc:
        mark = getattr(exc, "problem_mark", None)
        where = f"line {mark.line + 1}, column {mark.column + 1}" if mark is not None else type(exc).__name__
        raise ValueError(f"the admin layer {path} does not parse ({where})") from None
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError(f"the admin layer {path} is not a mapping of config keys")
    found = legacy_findings(raw, str(path))
    if found:
        raise LegacyConfigError(found)
    layer = raw
    for key, value in _leaves(layer):
        if isinstance(value, dict):
            continue  # an empty section sets nothing
        if key not in EDITABLE and key not in LAYER_ONLY:
            raise ValueError(
                f"the admin layer {path} sets {key}, which the admin panel may not edit "
                "(engine/hosting/admin/model.py EDITABLE); remove it from the file"
            )
    return layer


def url_origin(url: Any) -> str:
    """
    A URL's origin as ``scheme://host:port`` -- the scheme and host lowercased,
    the port explicit (80 for http, 443 for https) -- or "" when it has none
    (v0.20.0 T16 fix round 1: the API key follows a base URL only to the
    origin it was given for).
    """
    from urllib.parse import urlsplit

    if not isinstance(url, str) or not url.strip():
        return ""
    try:
        parts = urlsplit(url.strip())
        port = parts.port
    except ValueError:
        return ""
    scheme = (parts.scheme or "").lower()
    host = (parts.hostname or "").lower()
    if not scheme or not host:
        return ""
    if port is None:
        port = {"http": 80, "https": 443}.get(scheme)
    if ":" in host:
        host = f"[{host}]"
    return f"{scheme}://{host}:{port}" if port is not None else f"{scheme}://{host}"


#: The admin layer's own key (beside the panel's ``EDITABLE`` ones): the
#: origin the API key may be sent to while the layer sets ``llm.base_url``.
KEY_ORIGIN_KEY = "api_key_origin"


def _key_withheld(data: dict[str, Any], layer: dict[str, Any], external_keys: set[str]) -> bool:
    """
    Whether the API key must be withheld (v0.20.0 T16 fix round 1, the
    admin layer's ``llm.api_key_origin``): the layer sets ``llm.base_url``
    (and no ``CLOCKWORK_CONFIG`` file does, which would win), it names the
    origin the key was given for, and the base URL in force is on another
    origin. An admin who moved the model server to a new host without
    ticking "send the API key to this host" moved it without the key.
    """
    layer_llm = layer.get(LLM_BLOCK) if isinstance(layer, dict) else None
    if not isinstance(layer_llm, dict) or "base_url" not in layer_llm or KEY_ORIGIN_KEY not in layer_llm:
        return False
    if "llm.base_url" in external_keys:
        return False
    llm = data.get(LLM_BLOCK) if isinstance(data.get(LLM_BLOCK), dict) else {}
    return url_origin(llm.get("base_url")) != str(layer_llm.get(KEY_ORIGIN_KEY) or "")


def admin_layer() -> Optional[tuple[str, list[str]]]:
    """The admin layer the running config merged, as ``(path, its dotted keys)``, or None."""
    get_config()
    found = _admin_layer
    return (found[0], list(found[1])) if found is not None else None


def admin_layer_keys() -> list[str]:
    """
    Every dotted key the admin layer sets, sorted; [] when hosting is off or there is no file. Keys only, never a
    value (the doctor's rows, the Model server page's).
    """
    found = admin_layer()
    return sorted(found[1]) if found is not None else []


def get_config() -> ConfigManager:
    """
    Return singleton ConfigManager, loading layers on first use.

    An operator layer holding a refused name raises ``LegacyConfigError``
    naming it. The merged tree's secrets-chain scopes and ``llm.provider``
    are checked last.

    Raises:
        LegacyConfigError: an operator layer holds lmstudio:,
            stack.services.lmstudio or paths.saves.
        ValueError: ``llm.provider`` names a server this build does not speak
            or is a ``${...}`` reference; a ``${...}`` alternative is scoped
            to a name that is no provider; or a ``CLOCKWORK_CONFIG`` file is
            missing, unparsable or not a mapping.
    """
    instance = _instance
    if instance is not None and _instance_pid in (None, os.getpid()):
        # The hot path: built, and built in this process. One read, no lock.
        return instance
    with _config_lock:
        return _build_config()


def _build_config() -> ConfigManager:
    """``get_config``'s slow path, run under ``_config_lock`` (double-checked)."""
    global _instance, _instance_pid, _admin_layer
    if _instance is not None and _instance_pid not in (None, os.getpid()):
        # A forked child (multiprocessing's fork start method) inherits the
        # parent's singleton; it is rebuilt, so a child of the test suite
        # gets its sandbox rather than the suite's config.
        _instance = None
    if _instance is None:
        _instance_pid = os.getpid()
        sandbox = child_sandbox()
        refused: list[tuple[str, str, str]] = []
        data = _load_yaml(_DEFAULT_PATH)

        env = os.environ.get("CLOCKWORK_ENV", "").strip()
        if env:
            env_path = _CONFIG_DIR / f"{env}.yaml"
            overlay = _load_yaml(env_path)
            if overlay:
                refused += legacy_findings(overlay, str(env_path))
                data = deep_merge(data, overlay)
                logger.info("[config] Environment layer applied (operation=get_config, env=%s)", env)

        local_path = _CONFIG_DIR / "local.yaml"
        # A test suite's child process never reads the owner's hand-kept file
        # (TEST_SANDBOX_ENV: set by the suite's conftest, never by a deployment).
        local = {} if sandbox is not None else _load_yaml(local_path)
        if sandbox is not None:
            logger.info(
                "[config] Local overrides skipped in the test sandbox "
                "(operation=get_config, path=%s)",
                local_path,
            )
        if local:
            refused += legacy_findings(local, str(local_path))
            data = deep_merge(data, local)
            logger.info("[config] Local overrides applied (operation=get_config)")

        _external_layers.clear()
        externals = external_config_paths()
        if sandbox is not None and sandbox.layer is not None:
            # Last, whatever route started this child: one started past the
            # suite's Popen wrapper (os.system, multiprocessing) never had it
            # in CLOCKWORK_CONFIG. A missing layer file raises, fail closed.
            mine = os.path.normcase(os.path.abspath(sandbox.layer))
            externals = [
                p for p in externals if os.path.normcase(os.path.abspath(p)) != mine
            ] + [sandbox.layer]
        sandbox_layer_data: dict[str, Any] = {}
        external_data: list[dict[str, Any]] = []
        for external_path in externals:
            layer = _load_external(external_path)
            if sandbox is not None and sandbox.layer is not None and external_path == sandbox.layer:
                sandbox_layer_data = layer
            else:
                # The suite's own sandbox layer is not an operator's.
                refused += legacy_findings(layer, str(external_path))
            _external_layers.append(
                (str(external_path), sorted(key for key, _ in _leaves(layer)))
            )
            external_data.append(layer)
            # Keys only, never values (rule 5): an operator's file is where a
            # hosted deployment keeps its secrets.
            logger.info(
                "[config] External config applied (operation=get_config, file=%s, keys=%d)",
                external_path,
                len(_external_layers[-1][1]),
            )
        # A story's overlay never carries a refused name: config_overlay drops
        # paths.saves and SETTING_REFUSALS refuses lmstudio.
        overlay_data = copy.deepcopy(_overlay) if _overlay else {}

        if refused:
            # Every operator layer read so far, at once (spec §10.2): the
            # admin layer below is read only when hosting is on, and raises
            # its own findings from _load_admin_layer. A file read twice
            # (CLOCKWORK_ENV=local) is reported once.
            raise LegacyConfigError(list(dict.fromkeys(refused)))

        def above_local(base: dict[str, Any]) -> dict[str, Any]:
            merged = base
            for layer in external_data:
                if layer:
                    merged = deep_merge(merged, layer)
            if overlay_data:
                merged = deep_merge(merged, overlay_data)
            return merged

        # THE ADMIN LAYER (v0.20.0 T14, spec §14.9), in two passes: every
        # other layer merged first; only when hosting.enabled is on THERE, and
        # <data root>/hosting/admin.yaml exists, is the config merged again
        # with the layer at its rank, between local.yaml and CLOCKWORK_CONFIG.
        # The layer cannot turn hosting on: hosting.* is outside its allowlist.
        _admin_layer = None
        admin_data: dict[str, Any] = {}
        first = above_local(data)
        if _truthy_path(first, "hosting.enabled"):
            admin_path = _admin_layer_path(first)
            if admin_path.is_file():
                layer = _load_admin_layer(admin_path)
                admin_data = layer
                _admin_layer = (
                    str(admin_path),
                    sorted(key for key, value in _leaves(layer) if not isinstance(value, dict)),
                )
                if layer:
                    data = deep_merge(data, layer)
                logger.info(
                    "[config] Admin layer applied (operation=get_config, file=%s, keys=%d)",
                    admin_path,
                    len(_admin_layer[1]),
                )
                first = above_local(data)
        data = first
        if _overlay:
            logger.info(
                "[config] Game overlay applied (operation=get_config, keys=%s)",
                sorted(_overlay),
            )

        # The API key follows an admin-set base URL only to the origin it was
        # given for (v0.20.0 T16 fix round 1): withheld -- resolved empty --
        # otherwise, and where it would have come from remembered for the
        # Model server page (never the value).
        withheld: Optional[tuple[str, str]] = None
        if _admin_layer is not None and admin_data:
            external_keys = {key for _, keys in _external_layers for key in keys}
            if _key_withheld(data, admin_data, external_keys):
                source = ConfigManager(data).secret_source("llm.api_key")
                if source[0]:
                    withheld = source
                llm_block = data.get(LLM_BLOCK)
                if isinstance(llm_block, dict):
                    llm_block["api_key"] = ""
                logger.warning(
                    "[config] The API key is withheld: llm.base_url (the admin layer's) is on "
                    "another origin than the key was given for (operation=get_config)"
                )

        if sandbox is not None:
            # A child of the test suite, whatever its layers say (a layer that
            # failed to name these, a marker with no layer): no model server
            # but a registered loopback stub, no MCP bridge, no ComfyUI, TTS
            # or STT server, no managed service (_force_sandbox).
            _force_sandbox(data, sandbox_layer_data)

        check_scopes(data)
        _check_provider(data)
        _instance = ConfigManager(data)
        _instance.withheld_key = withheld
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
    with _config_lock:
        # Never swapped under a build in flight, which would merge the old one.
        _overlay = copy.deepcopy(overlay) if overlay else {}
    reset_config()


def overlay() -> dict[str, Any]:
    """Return a copy of the active config overlay."""
    return copy.deepcopy(_overlay)


def hosting_enabled() -> bool:
    """
    Whether hosted mode is on (``hosting.enabled``; v0.20.0, spec §6).

    Read here so the engine can ask WITHOUT importing ``engine.hosting``,
    which local mode never loads. Truthy, not ``is True``: a value that is not
    a boolean turns the hosted branch on, where ``engine.hosting.install``
    refuses it by name, rather than running local mode against what the
    operator wrote.
    """
    return bool(get_config().get("hosting.enabled", False))


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

    The instance is dropped under the config lock, so a build already in
    flight (built from the layers as they were) finishes first and is dropped
    rather than published after the reset. The cache walk runs after the lock
    is released: its resets take the subsystem locks, whose holders call
    ``get_config`` (the lock order at ``_config_lock``). Hosted mode never
    resets while serving (spec §5.2); locally this is a Settings save or a
    story activation.
    """
    global _instance
    with _config_lock:
        _instance = None

    # Imported lazily: engine.games imports engine.config, and a module-level
    # import here would be a cycle.
    try:
        from engine.games.caches import reset_all_caches
    except ImportError:  # pragma: no cover -- engine.games always ships
        logger.warning("[config] Cache registry unavailable (operation=reset_config)")
        return
    reset_all_caches()
