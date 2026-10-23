"""
Story Content Validation
========================

Cross-check every id reference in ONE story's content tree against the thing
it names -- for any story, through its manifest, without activating it.

THE GAP THIS MODULE CLOSES. ``scripts/validate_content.py`` v0.1.0 was the
flagship's validator: its vocabularies (item tags, skills, bands, evil phases)
were The Clockwork Dark's, its paths were literals into ``data/``, and the
strongest validation pattern in the repo -- the canon-dictionary cross-check
that scans decks and endings in both directions (a flag a scene READS must be
canon or written; a flag a scene WRITES must be canon or read) -- existed only
as bespoke tests for The Wicked Garden. A third story got neither.

Everything here resolves through the story's manifest:

    vocabularies   skills and difficulty bands from the story's own
                   ``rules/skills.yaml`` when it ships one, the engine's canon
                   seven/six otherwise; item tags from the story's items files
                   plus the small engine-known set; evil phase ids only when
                   the story declares a doom clock (``paths.doom_effects``)
    sections       each check runs only when the story declares the path.
                   Undeclared means "this story ships none of this" (the
                   Garden pattern), and the section is skipped silently.

NOTHING IS ACTIVATED. Validation reads YAML straight off the manifest's paths,
so validating every discovered game in one process (tests, doctor) cannot
repoint config or clear a content cache mid-flight.

Severities: ``error`` is a reference that resolves to nothing -- a shop entry
that cannot be bought, a gate that can never open. ``warning`` is an advisory:
real, worth a look, not a broken build. The CLI's ``--strict`` promotes
advisories to failures.

The CLI face is ``scripts/validate_content.py``; the pytest face is
``tests/test_story_content_integrity.py``. Both call into here, so the logic
has one home. ``scripts/author.py`` is the third face: it validates drafts by
handing this module a synthetic manifest whose paths include them.

Version: v0.2.0 [2026-08-14]
"""

from __future__ import annotations

import json
import logging
import re
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator, Optional, Union

import yaml

from engine import yamlio
from engine.game.locations import KNOWN_FLAG_PREFIX
from engine.games.manifest import GameManifest

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Engine-known vocabularies. These are FALLBACKS and floors, not the law: a
# story that ships its own rules/skills.yaml speaks its own vocabulary.
# ---------------------------------------------------------------------------

#: Tags the ENGINE branches on (inventory verbs, barter, procgen). A story may
#: extend these freely in its own items files; it cannot misspell one of these.
ENGINE_ITEM_TAGS = frozenset(
    {"food", "tool", "charm", "trade", "quest", "light", "apparel", "material"}
)

#: The canon seven, used when a story declares no skills.yaml of its own.
ENGINE_SKILLS = frozenset(
    {"persuasion", "stealth", "sympathy", "lore", "craft", "survival", "nerve"}
)

#: The canon six difficulty bands.
ENGINE_BANDS = frozenset({"trivial", "easy", "standard", "hard", "severe", "legendary"})

#: Doom phases. Only meaningful for a story that runs a doom clock.
ENGINE_EVIL_PHASES = frozenset({"dormant", "stirring", "spreading", "consuming"})

#: Flags the ENGINE writes, by prefix. Content never spells these out; a scan
#: that meets one must not report it as unresolvable.
ENGINE_FLAG_PREFIXES: tuple[str, ...] = ("deck_drawn_", "ending_closed_")

#: Flags the ENGINE reads, by prefix: content writes them and nothing in
#: content need gate on them, so a write-only one is not dead weight.
#: ``location_known:<id>`` reveals a secret place (``locations.is_known``).
ENGINE_READ_FLAG_PREFIXES: tuple[str, ...] = (KNOWN_FLAG_PREFIX,)

_IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp", ".gif")

#: Directory name reserved for work in progress (``scripts/author.py`` writes
#: drafts under ``games/<slug>/data/drafts/``). A draft is not shipped content:
#: every directory scan below skips a ``drafts/`` directory nested anywhere
#: under a declared content path, so a story can carry half-finished YAML
#: without failing its own build -- and without the drafts silently joining the
#: live registries either.
DRAFTS_DIRNAME = "drafts"

#: Relative locations (from the story root) where a canon dictionary may live.
CANON_DICTIONARY_CANDIDATES = (
    "data/canon/state-dictionary.json",
    "canon/state-dictionary.json",
)


def _minutes_problem(edge: dict[str, Any]) -> str:
    """What is wrong with an edge's `minutes` (v0.23.0 I3), as the loader judges it; "" for none."""
    try:
        minutes = int(edge["minutes"])
    except (TypeError, ValueError):
        return "minutes must be a whole number"
    if not 0 <= minutes <= 59:
        return f"minutes {minutes} is outside 0-59"
    try:
        hours = int(edge.get("hours", 0))
    except (TypeError, ValueError):
        return ""
    return "hours and minutes are both 0" if hours == 0 and minutes == 0 else ""


@dataclass(frozen=True)
class Issue:
    """One integrity finding, phrased for whoever has to fix the file."""

    source: str
    ref_id: str
    message: str
    severity: str = "error"

    def __str__(self) -> str:
        return f"[{self.severity}] {self.source}: {self.ref_id} -- {self.message}"


def errors_only(issues: Iterable[Issue]) -> list[Issue]:
    """Just the findings that should fail a build."""
    return [i for i in issues if i.severity == "error"]


def warnings_only(issues: Iterable[Issue]) -> list[Issue]:
    """Just the advisories."""
    return [i for i in issues if i.severity != "error"]


# ---------------------------------------------------------------------------
# Document scanners -- shared with the per-story deep tests.
#
# Content files use several spellings for the same reference (``item_id`` in an
# effect, ``requires_item`` in a gate, ``{has_item: ...}`` as a predicate), so
# the scans are by key name across every nested mapping rather than by schema.
# Under-collection is safe; a new spelling escapes silently, which is why the
# key lists are short and shared. tests/test_wicked_garden_scenes.py imports
# these rather than carrying its own copies.
# ---------------------------------------------------------------------------


def walk(node: Any) -> Iterator[dict[str, Any]]:
    """Yield every dict nested anywhere inside a parsed YAML document."""
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from walk(value)


def value_refs(doc: Any) -> set[str]:
    """Every declared-value name a document names, read or written."""
    out: set[str] = set()
    for node in walk(doc):
        if node.get("type") == "value" and node.get("name"):
            out.add(str(node["name"]))
        # `{value: {name: favor, min: 70}}` -- the predicate form.
        inner = node.get("value")
        if isinstance(inner, dict) and (inner.get("name") or inner.get("value")):
            out.add(str(inner.get("name") or inner.get("value")))
        # `{clock: {name: briar_hunger, min: 3}}`
        clock = node.get("clock")
        if isinstance(clock, dict) and (clock.get("name") or clock.get("clock")):
            out.add(str(clock.get("name") or clock.get("clock")))
        # A band names its value directly.
        band = node.get("band")
        if isinstance(band, dict) and (band.get("value") or band.get("name")):
            out.add(str(band.get("value") or band.get("name")))
        # A score row: `{value: corruption, at: 100, weight: 0.4}`
        if isinstance(node.get("value"), str) and "weight" in node:
            out.add(str(node["value"]))
    return out


def clock_refs(doc: Any) -> set[str]:
    """Every clock id a document gates on or advances."""
    out: set[str] = set()
    for node in walk(doc):
        clock = node.get("clock")
        if isinstance(clock, dict) and (clock.get("name") or clock.get("clock")):
            out.add(str(clock.get("name") or clock.get("clock")))
        elif isinstance(clock, str):
            out.add(clock)
        if node.get("type") == "clock" and node.get("name"):
            out.add(str(node["name"]))
    return out


def item_refs(doc: Any) -> set[str]:
    """
    Every item id a document grants, removes or gates on.

    MINTS ARE NOT REFERENCES. ``engine/game/inventory.py`` sanctions effects
    that mint an inventory entry outside the registry -- "Quests, procgen and
    the boon tables can all mint an inventory entry" -- and such an effect
    carries its own inline ``name`` (the flagship's ``sound_work`` boon is the
    shipped example). An item effect that self-describes is therefore excluded
    here; a bare id, which can only mean "look this up", must resolve.
    """
    out: set[str] = set()
    for node in walk(doc):
        if node.get("type") in ("item", "remove_item"):
            item_id = node.get("item_id") or node.get("id")
            if item_id and not str(node.get("name") or "").strip():
                out.add(str(item_id))
        # `item_id` is an item id wherever else it appears -- rewards, vendor
        # rows -- not only under an `item` effect.
        elif isinstance(node.get("item_id"), str):
            out.add(str(node["item_id"]))
        for key in ("has_item", "not_has_item", "item"):
            if key in node:
                raw = node[key]
                if isinstance(raw, dict):
                    if isinstance(raw.get("id"), str):
                        out.add(str(raw["id"]))
                elif key != "item":
                    out.update(str(v) for v in (raw if isinstance(raw, list) else [raw]))
        if isinstance(node.get("requires_item"), str):
            out.add(str(node["requires_item"]))
    return out


def location_refs(doc: Any) -> set[str]:
    """Every location id a document names."""
    out: set[str] = set()
    for node in walk(doc):
        for key in ("at_location", "visited"):
            if key in node:
                raw = node[key]
                out.update(str(v) for v in (raw if isinstance(raw, list) else [raw]))
        for key in ("location", "location_id"):
            if isinstance(node.get(key), str):
                out.add(str(node[key]))
        # A reveal names a place too (engine/game/locations.py::KNOWN_FLAG_PREFIX),
        # so a typo'd id is caught at load like a bad `at_location` -- written
        # by a flag effect, or handed to the narrator in `narrative_flags`.
        if node.get("type") == "flag":
            name = str(node.get("flag") or node.get("name") or "")
            if name.startswith(KNOWN_FLAG_PREFIX):
                out.add(name[len(KNOWN_FLAG_PREFIX):])
        narrative = node.get("narrative_flags")
        if isinstance(narrative, list):
            for raw_flag in narrative:
                name = str(raw_flag)
                if name.startswith(KNOWN_FLAG_PREFIX):
                    out.add(name[len(KNOWN_FLAG_PREFIX):])
        triggers = node.get("triggers")
        if isinstance(triggers, dict):
            for key in ("to", "from"):
                for value in triggers.get(key) or []:
                    out.add(str(value))
            for edge in triggers.get("edges") or []:
                src, _, dst = str(edge).partition(">")
                out.update({src, dst})
    return out


def faction_refs(doc: Any) -> set[str]:
    """Every faction id a document names."""
    out: set[str] = set()
    for node in walk(doc):
        if isinstance(node.get("faction"), str):
            out.add(str(node["faction"]))
    return out


def flags_written(doc: Any) -> set[str]:
    """Every flag a document sets."""
    out: set[str] = set()
    for node in walk(doc):
        if node.get("type") == "flag":
            name = node.get("flag") or node.get("name")
            if name:
                out.add(str(name))
        out.update(str(f) for f in (node.get("set_flags") or []))
    return out


def flags_read(doc: Any) -> set[str]:
    """Every flag a document gates on."""
    out: set[str] = set()
    for node in walk(doc):
        if node.get("type") in ("flag", "value", "item", "remove_item", "track"):
            continue  # an effect, not a predicate
        for key in ("flag", "not_flag"):
            if key in node:
                raw = node[key]
                out.update(str(v) for v in (raw if isinstance(raw, list) else [raw]))
    return out


def engine_owned_flag(flag: str) -> bool:
    """True for flags the engine itself writes, by prefix."""
    return str(flag).startswith(ENGINE_FLAG_PREFIXES)


# ---------------------------------------------------------------------------
# Canon helpers
# ---------------------------------------------------------------------------


def canon_location_ids(locations_doc: Any) -> list[str]:
    """
    The canon location list a story declares INSIDE its graph file.

    A story expresses location canon as a top-level ``canon:`` list beside
    ``locations:`` -- ids that quests, saves and schedules depend on by name,
    which therefore must always be present in the graph. Absent means the
    story pins none, which is legal.
    """
    if not isinstance(locations_doc, dict):
        return []
    raw = locations_doc.get("canon") or []
    if not isinstance(raw, (list, tuple)):
        return []
    return [str(v) for v in raw]


def canon_dictionary_path(manifest: GameManifest) -> Optional[Path]:
    """Where this story's canon state dictionary lives, or None."""
    if manifest.root is None:
        return None
    for rel in CANON_DICTIONARY_CANDIDATES:
        candidate = manifest.root / rel
        if candidate.is_file():
            return candidate
    return None


def load_canon_dictionary(manifest: GameManifest) -> Optional[dict[str, Any]]:
    """The story's canon dictionary, parsed, or None when it ships none."""
    path = canon_dictionary_path(manifest)
    if path is None:
        return None
    try:
        with path.open(encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning(
            "[validation] Unreadable canon dictionary "
            "(operation=load_canon_dictionary, path=%s): %s",
            path,
            exc,
        )
        return None
    return data if isinstance(data, dict) else None


def canon_flags(dictionary: Optional[dict[str, Any]], clocks_doc: Any = None) -> set[str]:
    """
    Flags the story's DESIGN declares, plus the ones its shipped clocks write.

    Three sources, each a different kind of authority:

      1. ``flags.booleans`` in the canon dictionary -- the design's own list.
      2. ``flags.enums``, expanded to one flag per value (``act2_compass`` with
         value ``love_and_door`` is spelled ``act2_compass_love_and_door``,
         because a deck beat cannot write a track). ``none`` is skipped.
      3. ``set_flags`` on a clock beat -- shipped mechanics declare by writing.
    """
    out: set[str] = set()
    flags = (dictionary or {}).get("flags") or {}
    for group in (flags.get("booleans") or {}).values():
        if isinstance(group, (list, tuple)):
            out.update(str(f) for f in group)
    for enum_name, values in (flags.get("enums") or {}).items():
        if not isinstance(values, list):
            continue  # `$ref` entries; the referenced enum is expanded already
        for value in values:
            if str(value) == "none":
                continue
            out.add(f"{enum_name}_{value}")
    if isinstance(clocks_doc, dict):
        for clock in (clocks_doc.get("clocks") or {}).values():
            for beat in (clock or {}).get("beats") or []:
                out.update(str(f) for f in ((beat or {}).get("set_flags") or []))
    return out


# ---------------------------------------------------------------------------
# Per-story vocabularies
# ---------------------------------------------------------------------------


#: Documents already parsed during ONE ``StoryValidator.run`` (None outside a
#: run), keyed by resolved path. Many checks read the same file, and
#: ``check_event_references`` reads every file the story declares; without
#: this a run parsed the story's YAML over again (v0.17 T3 review: the
#: flagship's validation went from 2.7s to 4.7s). Scoped to one run, so an
#: edited file is always read fresh by the next. Callers treat the documents
#: as read-only (none mutates a parsed document).
#:
#: A ``ContextVar`` (v0.20.0): as a module global, two overlapping runs on two
#: threads shared one dict and restored each other's, and the later
#: ``finally`` left the earlier run's documents installed for good.
_RUN_DOCS: ContextVar[Optional[dict[str, Any]]] = ContextVar("validation_run_docs", default=None)


def _read_yaml(path: Path) -> Any:
    """Parse one YAML file, returning None on any failure (reported upstream).

    Memoised for the length of one validator run (``_RUN_DOCS``)."""
    docs = _RUN_DOCS.get()
    key = ""
    if docs is not None:
        try:
            key = str(path.resolve())
        except OSError:
            key = str(path)
        if key in docs:
            return docs[key]
    try:
        with path.open(encoding="utf-8") as fh:
            doc = yamlio.safe_load(fh)
        if docs is not None:
            docs[key] = doc
        return doc
    except (OSError, yaml.YAMLError) as exc:
        logger.error(
            "[validation] Unreadable file (operation=_read_yaml, path=%s): %s",
            path,
            exc,
        )
        return None


def _skills_doc(manifest: GameManifest) -> dict[str, Any]:
    rel = str(manifest.paths.get("rules") or "").strip()
    if not rel:
        return {}
    path = manifest.resolve(rel) / "skills.yaml"
    if not path.is_file():
        return {}
    data = _read_yaml(path)
    return data if isinstance(data, dict) else {}


def story_skills(manifest: GameManifest) -> frozenset[str]:
    """
    The skill vocabulary this story's checks resolve against.

    The story's own ``rules/skills.yaml`` when it ships one; the engine's
    canon seven otherwise, which is what ``engine/game/checks.py`` falls back
    to for a story that rolls dice without declaring a taxonomy.
    """
    declared = set((_skills_doc(manifest).get("skills") or {}))
    return frozenset(str(s) for s in declared) if declared else ENGINE_SKILLS


def story_bands(manifest: GameManifest) -> frozenset[str]:
    """Difficulty bands: the story's ``difficulty:`` table, else the canon six."""
    declared = set((_skills_doc(manifest).get("difficulty") or {}))
    return frozenset(str(b) for b in declared) if declared else ENGINE_BANDS


def story_item_tags(items: dict[str, dict[str, Any]]) -> frozenset[str]:
    """
    The tag vocabulary: the engine-known set plus every tag the story's own
    items declare. Tags are story vocabulary, not an engine enum -- the Garden
    tags by provenance (``gift``, ``sophia``), the flagship by function.
    """
    declared = {
        str(tag) for row in items.values() for tag in (row.get("tags") or [])
    }
    return frozenset(ENGINE_ITEM_TAGS | declared)


def doom_enabled(manifest: GameManifest) -> bool:
    """Whether this story runs the doom clock (declares ``paths.doom_effects``)."""
    return bool(str(manifest.paths.get("doom_effects") or "").strip())


# ---------------------------------------------------------------------------
# Loaders shared by checks and by the flagship's own volume tests
# ---------------------------------------------------------------------------


def load_story_items(
    manifest: GameManifest,
) -> tuple[dict[str, dict[str, Any]], list[Issue]]:
    """
    Build the item registry from the story's ``paths.items`` directory.

    Returns:
        (registry keyed by item id, issues found while building it). Empty
        registry with no issues when the story declares no items.
    """
    issues: list[Issue] = []
    registry: dict[str, dict[str, Any]] = {}
    origin: dict[str, str] = {}

    directory = _declared_dir(manifest, "items")
    if directory is None:
        return registry, issues

    for path in _yaml_files(directory):
        data = _read_yaml(path)
        source = _rel(manifest, path)
        if not isinstance(data, dict):
            issues.append(Issue(source, "-", "file is not a YAML mapping"))
            continue
        for row in data.get("items") or []:
            if not isinstance(row, dict):
                issues.append(Issue(source, "-", "item entry is not a mapping"))
                continue
            item_id = str(row.get("id") or "").strip()
            if not item_id:
                issues.append(Issue(source, "-", "item entry has no id"))
                continue
            if item_id in registry:
                issues.append(
                    Issue(
                        source,
                        item_id,
                        f"duplicate item id, already defined in {origin[item_id]}",
                    )
                )
                continue
            registry[item_id] = row
            origin[item_id] = source
    return registry, issues


def load_story_locations(manifest: GameManifest) -> dict[str, Any]:
    """The raw graph document, or {} when the story declares none."""
    path = _declared_file(manifest, "locations")
    if path is None:
        return {}
    data = _read_yaml(path)
    return data if isinstance(data, dict) else {}


# ---------------------------------------------------------------------------
# Path plumbing
# ---------------------------------------------------------------------------


def _declared_file(manifest: GameManifest, key: str) -> Optional[Path]:
    """The resolved path for a declared file key, or None when undeclared."""
    rel = str(manifest.paths.get(key) or "").strip()
    if not rel:
        return None
    return manifest.resolve(rel)


def _declared_dir(manifest: GameManifest, key: str) -> Optional[Path]:
    """The resolved path for a declared directory key, or None when undeclared."""
    return _declared_file(manifest, key)


def _rel(manifest: GameManifest, path: Path) -> str:
    """Repo-relative path string, for messages a human can paste into an editor."""
    from engine.config import project_root

    try:
        return str(path.relative_to(project_root())).replace("\\", "/")
    except ValueError:
        return str(path)


def _yaml_files(directory: Optional[Path]) -> list[Path]:
    """Every shipped ``*.yaml`` under a directory. A ``drafts/`` subtree is
    work in progress, not content, and is skipped -- see ``DRAFTS_DIRNAME``."""
    if directory is None or not directory.is_dir():
        return []
    return sorted(
        path
        for path in directory.rglob("*.yaml")
        if DRAFTS_DIRNAME not in path.relative_to(directory).parts[:-1]
    )


# ---------------------------------------------------------------------------
# The validator
# ---------------------------------------------------------------------------


class StoryValidator:
    """
    One story, every check. Build it, call ``run()``, read ``issues``.

    Deliberately stateless with respect to the engine: nothing here activates
    the story, touches the config overlay, or warms a content cache.
    """

    def __init__(self, manifest: GameManifest) -> None:
        self.manifest = manifest
        self.issues: list[Issue] = []

        # Registries, built once in run().
        self.items: dict[str, dict[str, Any]] = {}
        self.locations_doc: dict[str, Any] = {}
        self.locations: dict[str, Any] = {}
        self.npc_ids: set[str] = set()
        self.faction_ids: set[str] = set()
        self.declared_values: set[str] = set()
        self.declared_clocks: set[str] = set()
        self.schema_loaded = False

    # -- plumbing ----------------------------------------------------------

    def _file(self, key: str) -> Optional[Path]:
        return _declared_file(self.manifest, key)

    def _dir(self, key: str) -> Optional[Path]:
        return _declared_dir(self.manifest, key)

    def _rel(self, path: Path) -> str:
        return _rel(self.manifest, path)

    def _add(self, source: str, ref_id: str, message: str, severity: str = "error") -> None:
        self.issues.append(Issue(source, ref_id, message, severity))

    # -- orchestration -----------------------------------------------------

    def run(self) -> list[Issue]:
        """Run every applicable check, in dependency order."""
        outer = _RUN_DOCS.get()
        token = _RUN_DOCS.set({} if outer is None else outer)
        try:
            return self._run()
        finally:
            _RUN_DOCS.reset(token)

    def _run(self) -> list[Issue]:
        self._build_registries()

        self.check_retired_paths()
        self.check_ui_panels()
        self.check_state_schema()
        self.check_locations()
        self.check_items()
        self.check_art_manifest()
        self.check_economy()
        self.check_recipes()
        self.check_quests()
        self.check_encounters()
        self.check_tables()
        self.check_collections()
        self.check_npc_schedules()
        self.check_rumors()
        self.check_assistant_hints()
        self.check_lore()
        self.check_decks_and_structures()
        self.check_declared_event_scenes()
        self.check_event_references()
        self.check_endings_and_epilogues()
        self.check_endless()
        self.check_social()
        self.check_opening()
        self.check_law_effects()
        self.check_death_rules()
        self.check_set_pieces()
        self.check_truncated_content()
        self.check_procgen_templates()
        self.check_agents()
        self.check_spoilers()

        errors = errors_only(self.issues)
        logger.info(
            "[validation] Story validated (operation=run, slug=%s, items=%d, "
            "locations=%d, errors=%d, warnings=%d)",
            self.manifest.slug,
            len(self.items),
            len(self.locations),
            len(errors),
            len(self.issues) - len(errors),
        )
        return self.issues

    def _build_registries(self) -> None:
        self.items, item_issues = load_story_items(self.manifest)
        self.issues.extend(item_issues)

        self.locations_doc = load_story_locations(self.manifest)
        raw = self.locations_doc.get("locations")
        self.locations = raw if isinstance(raw, dict) else {}

        npc_path = self._file("npc_schedules")
        if npc_path is not None:
            data = _read_yaml(npc_path) or {}
            self.npc_ids = {str(k) for k in ((data or {}).get("npcs") or {})}

        faction_path = self._file("factions")
        if faction_path is not None:
            data = _read_yaml(faction_path) or {}
            self.faction_ids = {str(k) for k in ((data or {}).get("factions") or {})}

        schema_path = self.manifest.state_schema_path
        if schema_path is not None and schema_path.is_file():
            data = _read_yaml(schema_path)
            if isinstance(data, dict):
                self.declared_values = (
                    {str(k) for k in (data.get("meters") or {})}
                    | {str(k) for k in (data.get("clocks") or {})}
                    | {str(k) for k in (data.get("tracks") or {})}
                )
                self.declared_clocks = {str(k) for k in (data.get("clocks") or {})}
                self.schema_loaded = True

    # -- the manifest --------------------------------------------------------

    def check_ui_panels(self) -> None:
        """``ui.panels`` (spec §2.2): its errors, and an advisory per panel whose system is undeclared."""
        from engine.games.manifest import ui_panel_problems

        errors, advisories = ui_panel_problems(self.manifest)
        for message in errors:
            self._add("game.yaml", "ui.panels", message)
        for message in advisories:
            self._add("game.yaml", "ui.panels", message, severity="warning")

    def check_retired_paths(self) -> None:
        """
        An ADVISORY for a ``paths:`` key the engine no longer reads from a
        story (``manifest.RETIRED_PATH_KEYS``: ``saves``, since v0.20.0). Not
        an error, and not a ``registry.validate`` problem: the story still
        plays, and the key moves nothing.
        """
        for key, note in self.manifest.retired_paths():
            self._add("game.yaml", f"paths.{key}", note, severity="warning")

    # -- state -------------------------------------------------------------

    def check_state_schema(self) -> None:
        """The declared state parses. Malformed is fatal at launch, so it is here."""
        path = self.manifest.state_schema_path
        if path is None or not path.is_file():
            return
        from engine.state.schema import SchemaError, load_schema

        source = self._rel(path)
        try:
            load_schema(path, slug=self.manifest.slug)
        except SchemaError as exc:
            self._add(source, "-", f"state schema will not load: {exc}")

    # -- world -------------------------------------------------------------

    def check_locations(self) -> None:
        """Graph shape: canon present, edges resolve, entry exists and reaches all."""
        path = self._file("locations")
        if path is None:
            return
        source = self._rel(path)
        if not self.locations:
            self._add(source, "-", "graph declares no locations")
            return

        for canon in canon_location_ids(self.locations_doc):
            if canon not in self.locations:
                self._add(source, canon, "canon location id is missing from the graph")

        from engine.game.locations import known_when_problem

        for loc_id, spec in self.locations.items():
            spec = spec if isinstance(spec, dict) else {}
            if not str(spec.get("name") or "").strip():
                self._add(source, str(loc_id), "location has no name; the loader will drop it")
            problem = known_when_problem(spec)
            if problem:
                self._add(source, str(loc_id), f"{problem}; the loader will ignore it")
            if "ring" not in spec:
                self._add(source, str(loc_id), "no ring assigned; the loader will drop it")
            connections = spec.get("connections") or {}
            if not isinstance(connections, dict):
                self._add(source, str(loc_id), "connections is not a mapping")
                continue
            for dst, edge in connections.items():
                edge = edge if isinstance(edge, dict) else {}
                if dst not in self.locations:
                    self._add(source, f"{loc_id}>{dst}", "edge target does not exist")
                    continue
                if "minutes" in edge:
                    problem = _minutes_problem(edge)
                    if problem:
                        self._add(source, f"{loc_id}>{dst}", f"{problem}; the loader will drop the edge")
                if edge.get("one_way"):
                    continue
                back = self.locations.get(dst) or {}
                if loc_id not in ((back.get("connections") or {}) if isinstance(back, dict) else {}):
                    # The loader mirrors a missing return leg rather than
                    # stranding the player, so this is a repair, not a break.
                    self._add(
                        source,
                        f"{loc_id}>{dst}",
                        "edge has no return leg and is not one_way; the loader will mirror it",
                        severity="warning",
                    )

        entry = self.manifest.entry_location
        if entry and entry not in self.locations:
            self._add(source, entry, "entry.location_id is not in the graph")
        elif entry:
            # A place nobody can walk to is content that will never be seen.
            # Measured from the story's own entry, with the loader's mirroring
            # applied -- a one-directional authored edge still carries traffic
            # both ways at runtime.
            reachable: set[str] = set()
            frontier = [entry]
            inbound: dict[str, set[str]] = {}
            for src, spec in self.locations.items():
                spec = spec if isinstance(spec, dict) else {}
                for dst, edge in (spec.get("connections") or {}).items():
                    edge = edge if isinstance(edge, dict) else {}
                    if dst in self.locations and not edge.get("one_way"):
                        inbound.setdefault(str(dst), set()).add(str(src))
            while frontier:
                current = frontier.pop()
                if current in reachable:
                    continue
                reachable.add(current)
                spec = self.locations.get(current) or {}
                spec = spec if isinstance(spec, dict) else {}
                frontier.extend(
                    dst for dst in (spec.get("connections") or {}) if dst in self.locations
                )
                frontier.extend(inbound.get(current, ()))
            for orphan in sorted(set(map(str, self.locations)) - reachable):
                spec = self.locations.get(orphan) or {}
                tags = (spec.get("tags") or []) if isinstance(spec, dict) else []
                if "sentinel" in {str(t) for t in tags}:
                    # A declared sentinel: effects place the player here,
                    # travel never does (the Garden's `unknown`). Unreachable
                    # by walking is its whole design.
                    continue
                self._add(source, orphan, f"unreachable from {entry} by any path")

    # -- items -------------------------------------------------------------

    def check_items(self) -> None:
        """Item field shape and art-key resolution, against the story's own tags."""
        directory = self._dir("items")
        if directory is None or not self.items:
            return
        source = self._rel(directory) + "/*.yaml"

        art_items: dict[str, Any] = {}
        art_path = self._file("art_manifest")
        if art_path is not None:
            art = _read_yaml(art_path)
            if isinstance(art, dict):
                art_items = art.get("items") or {}

        for item_id, row in sorted(self.items.items()):
            if not str(row.get("name") or "").strip():
                self._add(source, item_id, "item has no name")
            if not str(row.get("description") or "").strip():
                self._add(source, item_id, "item has no description")
            if not (row.get("tags") or []):
                self._add(source, item_id, "item has no tags")
            for numeric in ("weight", "value"):
                value = row.get(numeric)
                if not isinstance(value, (int, float)) or value < 0:
                    self._add(source, item_id, f"{numeric} must be a non-negative number")
            art_key = row.get("art")
            if art_key is not None and art_path is not None and str(art_key) not in art_items:
                self._add(
                    source,
                    item_id,
                    f"art key {art_key!r} is not in the art manifest's items:",
                )

    # -- art ---------------------------------------------------------------

    def check_art_manifest(self) -> None:
        """Every path in the manifest resolves to a shipped file; keys name real things."""
        path = self._file("art_manifest")
        if path is None:
            return
        source = self._rel(path)
        data = _read_yaml(path)
        if not isinstance(data, dict):
            self._add(source, "-", "art manifest is not a YAML mapping")
            return

        art_root = self._file("art_root")
        if art_root is not None:

            def walk_paths(node: Any, key: str) -> Iterator[tuple[str, str]]:
                if isinstance(node, str):
                    if node.lower().endswith(_IMAGE_SUFFIXES):
                        yield key, node
                elif isinstance(node, dict):
                    for sub_key, value in node.items():
                        yield from walk_paths(value, str(sub_key))
                elif isinstance(node, list):
                    for value in node:
                        yield from walk_paths(value, key)

            for key, rel_path in walk_paths(data, "root"):
                if not (art_root / rel_path).exists():
                    self._add(source, key, f"art file does not exist: {rel_path}")

        # Keys must name real subjects. A story's art may cover its authored
        # subject list as well as the graph, so both count as "real".
        subject_locations: set[str] = set()
        subject_portraits: set[str] = set()
        subjects_path = self._file("art_subjects")
        if subjects_path is not None:
            subjects = _read_yaml(subjects_path)
            if isinstance(subjects, dict):
                subject_locations = {
                    str(k) for k in (subjects.get("locations") or {}) if str(k) != "defaults"
                }
                subject_portraits = {
                    str(k) for k in (subjects.get("portraits") or {}) if str(k) != "defaults"
                }

        known_locations = set(map(str, self.locations)) | subject_locations
        if known_locations:
            for loc_key in data.get("locations") or {}:
                if str(loc_key) not in known_locations:
                    self._add(
                        source, str(loc_key), "locations: key is not a location or art subject"
                    )

        # Portraits are addressed by subject id, and a story may ship
        # expression VARIANTS of a subject it declares -- `sophia_wrath` is a
        # plate of `sophia`, addressable by exact id. So a key resolves when it
        # is a known npc/subject, extends one (`<subject>_<variant>`), or names
        # the player, who exists in every story without being an NPC. Anything
        # else is a key nothing can be expected to request -- in the flagship's
        # shape, a typo'd npc id.
        known_portraits = self.npc_ids | subject_portraits | {"player"}
        if known_portraits:
            for portrait_key in data.get("portraits") or {}:
                key = str(portrait_key)
                if key in known_portraits or any(
                    key.startswith(f"{known}_") for known in known_portraits
                ):
                    continue
                self._add(
                    source,
                    key,
                    "portraits: key is not a known npc or art subject (nor a "
                    "variant of one); only an exact-id request can reach it",
                    severity="warning",
                )

        # Assistant forms are an ENGINE vocabulary; check only when the story
        # declares the section at all.
        if "assistant_forms" in data:
            try:
                from engine.skills.builtin.assistant import ASSISTANT_FORMS
            except ImportError:  # pragma: no cover -- ships with the engine
                ASSISTANT_FORMS = ()
            forms = set(data.get("assistant_forms") or {})
            for form in sorted(set(ASSISTANT_FORMS) - forms):
                self._add(source, form, "assistant form has no art entry", severity="warning")
            for form in sorted(forms - set(ASSISTANT_FORMS)):
                self._add(source, form, "assistant_forms: key is not a known form")

    # -- economy -----------------------------------------------------------

    def check_economy(self) -> None:
        """Vendors are real NPCs and stock real items at sane prices."""
        path = self._file("economy")
        if path is None:
            return
        source = self._rel(path)
        data = _read_yaml(path)
        if not isinstance(data, dict):
            self._add(source, "-", "economy is not a YAML mapping")
            return
        self.issues.extend(
            check_economy_data(source, data, items=self.items, npc_ids=self.npc_ids)
        )

    # -- recipes -----------------------------------------------------------

    def check_recipes(self) -> None:
        """Recipe skills, bands, stations and every item id on both sides."""
        directory = self._dir("recipes")
        if directory is None:
            return
        skills = story_skills(self.manifest)
        bands = story_bands(self.manifest)
        seen: dict[str, str] = {}

        for path in _yaml_files(directory):
            data = _read_yaml(path)
            source = self._rel(path)
            if not isinstance(data, dict):
                self._add(source, "-", "file is not a YAML mapping")
                continue
            for row in data.get("recipes") or []:
                if not isinstance(row, dict):
                    self._add(source, "-", "recipe entry is not a mapping")
                    continue
                recipe_id = str(row.get("id") or "").strip()
                if not recipe_id:
                    self._add(source, "-", "recipe entry has no id")
                    continue
                if recipe_id in seen:
                    self._add(
                        source,
                        recipe_id,
                        f"duplicate recipe id, already defined in {seen[recipe_id]}",
                    )
                    continue
                seen[recipe_id] = source
                self.issues.extend(
                    check_recipe_row(
                        source,
                        row,
                        items=self.items,
                        locations=set(map(str, self.locations)),
                        skills=skills,
                        bands=bands,
                    )
                )

    # -- quests ------------------------------------------------------------

    def check_quests(self) -> None:
        """Quest arcs, locations, items, factions -- and that every arc is real."""
        directory = self._dir("quests")
        if directory is None:
            return
        arcs_doc = _read_yaml(directory / "arcs.yaml") or {}
        arc_ids = {str(k) for k in ((arcs_doc or {}).get("arcs") or {})}
        quest_paths = [p for p in _yaml_files(directory) if p.name != "arcs.yaml"]

        # Every narrative flag ANY quest in this story declares, gathered before
        # the per-file pass. A flag is global and durable once raised, so its
        # declaring quest and its reading quest need not be the same file, and
        # a stage may legitimately wait on a flag an EARLIER stage declared.
        # Scoping the check per stage produced seven false positives across two
        # shipped stories on exactly those two shapes.
        declared_flags: set[str] = set()
        for path in quest_paths:
            doc = _read_yaml(path)
            if not isinstance(doc, dict):
                continue
            declared_flags.update(str(f) for f in (doc.get("narrative_flags") or []))
            for stage in doc.get("stages") or []:
                if isinstance(stage, dict):
                    declared_flags.update(
                        str(f) for f in (stage.get("narrative_flags") or [])
                    )

        for path in quest_paths:
            data = _read_yaml(path)
            source = self._rel(path)
            if not isinstance(data, dict):
                self._add(source, "-", "quest file is not a YAML mapping")
                continue
            quest_id = str(data.get("id") or "")
            if not quest_id:
                self._add(source, "-", "quest has no id")
            arc = str(data.get("arc") or "")
            # A quest on an arc that does not exist can never become active.
            if arc not in arc_ids:
                self._add(source, quest_id or "-", f"arc {arc!r} is not in arcs.yaml")
            if not data.get("stages"):
                self._add(source, quest_id or "-", "quest has no stages")

            self._check_stage_reachability(source, quest_id, data, declared_flags)
            self._check_stage_refusals(source, quest_id, data)
            self._check_generic_refs(source, data)

    def _check_stage_refusals(self, source: str, quest_id: str, data: dict[str, Any]) -> None:
        """
        A stage's ``refusals: [{when, text}]`` (v0.17, ``QuestEngine.
        stage_refusal``): the narrator's reason a stage will not close. Read
        as the thread and bed refusals are: a list of rows each with a
        ``when`` and a ``text``, the ``when`` in the shared grammar and
        answerable with no ledger -- the objective line is built with none,
        so a ``disposition`` clause would never hold and the reason would
        never be told.
        """
        from engine.game import quests as quests_module

        forbid = {name: reason for name, reason in quests_module.CONTEXT_FREE_FORBIDS.items()
                  if name in quests_module.LEDGER_PREDICATES}
        for stage in data.get("stages") or []:
            if not isinstance(stage, dict) or "refusals" not in stage:
                continue
            ref = f"{quest_id or '-'}/{str(stage.get('id') or '-')}"
            rows = stage["refusals"]
            if not isinstance(rows, list):
                self._add(source, ref, "refusals must be a list of {when, text}")
                continue
            for index, row in enumerate(rows):
                if not isinstance(row, dict) or not str(row.get("text") or "").strip() \
                        or row.get("when") is None:
                    self._add(source, ref, f"refusals[{index}] needs a `when` and a `text`")
                    continue
                problem = quests_module.condition_problem(
                    row.get("when"), where=f"`refusals[{index}].when`", forbid=forbid,
                )
                if problem:
                    self._add(source, ref, problem)

    # -- encounters --------------------------------------------------------

    def check_encounters(self) -> None:
        """Encounter edges resolve in the graph, and referenced ids exist."""
        directory = self._dir("encounters")
        if directory is None:
            return
        for path in _yaml_files(directory):
            data = _read_yaml(path)
            source = self._rel(path)
            if not isinstance(data, dict):
                continue
            self._check_generic_refs(source, data)
            # The edge itself, not just its endpoints: an encounter keyed to a
            # leg that does not exist can never fire, and nothing says so.
            for row in data.get("encounters") or []:
                if isinstance(row, dict) and "min_chance" in row:
                    floor = row["min_chance"]
                    if (isinstance(floor, bool) or not isinstance(floor, (int, float))
                            or not 0.0 < float(floor) <= 1.0):
                        self._add(source, str(row.get("id")),
                                  f"min_chance must be a number in (0, 1], got {floor!r}")
                triggers = (row or {}).get("triggers") or {}
                for edge in triggers.get("edges") or []:
                    src, _, dst = str(edge).partition(">")
                    spec = self.locations.get(src) or {}
                    spec = spec if isinstance(spec, dict) else {}
                    if dst not in (spec.get("connections") or {}):
                        self._add(source, str((row or {}).get("id")), f"dead edge {edge}")

    # -- tables ------------------------------------------------------------

    def check_tables(self) -> None:
        """Referential integrity over the story's random tables."""
        directory = self._dir("tables")
        if directory is None:
            return
        for path in _yaml_files(directory):
            data = _read_yaml(path)
            if data is None:
                continue
            self._check_generic_refs(self._rel(path), data)
            self._check_vendor_refusals(self._rel(path), data)
            if path.name == "labour.yaml":
                self._check_labour_effects(self._rel(path), data)

    def _check_labour_effects(self, source: str, data: Any) -> None:
        """
        A posting's ``effects`` (v0.17, ``economy.work``): an effect kind the
        engine knows, fields that agree with the kind (``_check_effect_rows``),
        and ``degrees`` naming only degrees the job's ``pay`` table knows -- a
        misspelt degree is a row that never fires, and an unknown kind one
        ``apply_effect`` drops, both without a word at the table.
        """
        from engine.game.effects import registered_kinds

        kinds = set(registered_kinds())
        for job in (data.get("jobs") or []) if isinstance(data, dict) else []:
            if not isinstance(job, dict) or "effects" not in job:
                continue
            job_id = str(job.get("id") or "-")
            rows = job["effects"]
            if not isinstance(rows, list):
                self._add(source, job_id, "effects must be a list of effect rows")
                continue
            pay = job.get("pay")
            known = {str(d) for d in pay} if isinstance(pay, dict) else set()
            for index, row in enumerate(rows):
                if not isinstance(row, dict):
                    self._add(source, job_id, f"effects[{index}] is not an effect row")
                    continue
                kind = str(row.get("type") or "")
                if kind not in kinds:
                    self._add(source, job_id, f"effects[{index}]: unknown effect type "
                                              f"{kind!r}; it is dropped when the shift pays")
                degrees = row.get("degrees")
                if degrees is not None:
                    if not isinstance(degrees, list):
                        self._add(source, job_id, f"effects[{index}].degrees must be a list")
                    else:
                        for degree in degrees:
                            if known and str(degree) not in known:
                                self._add(source, job_id,
                                          f"effects[{index}].degrees names {degree!r}, "
                                          "which the job's `pay` table does not; the row "
                                          "never fires on it")
            self._check_effect_rows(source, {"effects": rows})

    def _check_vendor_refusals(self, source: str, data: Any) -> None:
        """A trade profile's ``refuses_to_buy`` (v0.15): words, and a condition that can hold."""
        from engine.game.trade import refuses_to_buy_problem

        vendors = data.get("vendors") if isinstance(data, dict) else None
        for npc_id, profile in (vendors or {}).items() if isinstance(vendors, dict) else ():
            if not isinstance(profile, dict) or "refuses_to_buy" not in profile:
                continue
            problem = refuses_to_buy_problem(profile["refuses_to_buy"])
            if problem:
                self._add(source, str(npc_id), problem)

    def check_collections(self) -> None:
        """
        Collectable sets (``<paths.tables>/collections.yaml``) against the items.

        Runs whenever the story has items, not only when it declares tables:
        an item naming a set in a story with no collections file is the
        undeclared-set error, not a silence.
        """
        if not self.items:
            return
        directory = self._dir("tables")
        path = (directory / "collections.yaml") if directory is not None else None
        data: Any = {}
        source = "collections.yaml (not declared)"
        if path is not None:
            source = self._rel(path)
            if path.is_file():
                data = _read_yaml(path)
        items_dir = self._dir("items")
        items_source = (self._rel(items_dir) + "/*.yaml") if items_dir is not None else "items"
        self.issues.extend(
            check_collections_data(source, data, items=self.items, items_source=items_source)
        )

    # -- schedules, rumors, hints, lore ------------------------------------

    def check_npc_schedules(self) -> None:
        """NPC homes and routine slots point at places that exist."""
        path = self._file("npc_schedules")
        if path is None:
            return
        source = self._rel(path)
        data = _read_yaml(path) or {}
        for npc_id, cfg in ((data or {}).get("npcs") or {}).items():
            home = str((cfg or {}).get("home") or "")
            if home and home not in self.locations:
                self._add(source, str(npc_id), f"home {home!r} is not a location")
            for slot in (cfg or {}).get("routine") or []:
                loc = str((slot or {}).get("location") or "")
                if loc and loc not in self.locations:
                    self._add(source, str(npc_id), f"routine location {loc!r} is not a location")

    def check_rumors(self) -> None:
        """Rumour tiers, awareness gates, speakers -- and phases only where they exist."""
        path = self._file("world_rumors")
        if path is None:
            return
        source = self._rel(path)
        data = _read_yaml(path) or {}
        seen: set[str] = set()
        has_doom = doom_enabled(self.manifest)

        for row in (data or {}).get("rumors") or []:
            if not isinstance(row, dict):
                self._add(source, "-", "rumour entry is not a mapping")
                continue
            rumor_id = str(row.get("id") or "")
            if not rumor_id:
                self._add(source, "-", "rumour has no id")
                continue
            if rumor_id in seen:
                self._add(source, rumor_id, "duplicate rumour id")
            seen.add(rumor_id)
            if not str(row.get("text") or "").strip():
                self._add(source, rumor_id, "rumour has no text")
            tier = row.get("tier")
            if tier not in (1, 2, 3):
                self._add(source, rumor_id, f"tier must be 1-3, got {tier!r}")
            awareness = row.get("min_awareness")
            if not isinstance(awareness, (int, float)) or not 0 <= awareness <= 100:
                self._add(source, rumor_id, f"min_awareness must be 0-100, got {awareness!r}")
            speaker = row.get("source_npc")
            if speaker is not None and str(speaker) not in self.npc_ids:
                self._add(source, rumor_id, f"source_npc {speaker!r} is not a known npc")
            for phase in row.get("requires_phase") or []:
                if not has_doom:
                    self._add(
                        source,
                        rumor_id,
                        f"requires_phase {phase!r}, but this story declares no doom clock",
                    )
                elif str(phase) not in ENGINE_EVIL_PHASES:
                    self._add(source, rumor_id, f"unknown evil phase {phase!r}")

    def check_assistant_hints(self) -> None:
        """Hint tiers and lore snippet gates."""
        path = self._file("assistant_hints")
        if path is None:
            return
        source = self._rel(path)
        data = _read_yaml(path)
        if not isinstance(data, dict):
            self._add(source, "-", "hints file is not a YAML mapping")
            return

        tiers_seen: set[int] = set()
        for index, row in enumerate(data.get("hints") or []):
            label = str((row or {}).get("text") or f"hint[{index}]")[:40]
            tier = (row or {}).get("tier")
            if tier not in (0, 1, 2, 3):
                self._add(source, label, f"tier must be 0-3, got {tier!r}")
            else:
                tiers_seen.add(int(tier))
            if not str((row or {}).get("text") or "").strip():
                self._add(source, label, "hint has no text")
        for tier in (0, 1, 2, 3):
            if tier not in tiers_seen:
                self._add(source, f"tier {tier}", "no hints at this tier")

        for topic, row in (data.get("lore_snippets") or {}).items():
            if not isinstance(row, dict):
                self._add(source, str(topic), "lore snippet is not a mapping")
                continue
            if not str(row.get("text") or "").strip():
                self._add(source, str(topic), "lore snippet has no text")
            min_tier = row.get("min_tier")
            if min_tier not in (1, 2, 3):
                self._add(source, str(topic), f"min_tier must be 1-3, got {min_tier!r}")

    def check_lore(self) -> None:
        """
        Lore markdown chunks the way ``engine/lore/manager.py`` will chunk it.

        A section whose body is under forty characters is silently dropped at
        ingest, so a file of short stubs looks fine on disk and contributes
        nothing to retrieval.
        """
        directory = self._dir("lore")
        if directory is None or not directory.is_dir():
            return
        for path in sorted(directory.glob("*.md")):
            source = self._rel(path)
            try:
                text = path.read_text(encoding="utf-8")
            except OSError as exc:
                self._add(source, "-", f"unreadable: {exc}")
                continue
            sections = list(text.split("\n## ")[1:])
            if not sections:
                self._add(source, "-", "no '##' sections; nothing will be ingested")
                continue
            for section in sections:
                title, _, body = section.partition("\n")
                if len(body.strip()) < 40:
                    self._add(
                        source,
                        title.strip(),
                        "section body under 40 chars; the lore ingest will drop it",
                    )

    # -- structural systems: decks, clocks, threads ------------------------

    def _structural_docs(self) -> dict[str, Any]:
        """
        Every structural document that reads or writes flags, values and clocks:
        the decks, the clock table, the thread table and the ending table.
        Keyed by repo-relative source for messages.
        """
        docs: dict[str, Any] = {}
        for path in _yaml_files(self._dir("decks")):
            data = _read_yaml(path)
            if data is not None:
                docs[self._rel(path)] = data
        for key in ("clocks", "threads", "endings"):
            path = self._file(key)
            if path is not None and path.is_file():
                data = _read_yaml(path)
                if data is not None:
                    docs[self._rel(path)] = data
        return docs

    def _labour_flags_written(self) -> set[str]:
        """Flags a labour posting's ``effects`` write (``economy.work``)."""
        directory = self._dir("tables")
        path = directory / "labour.yaml" if directory is not None else None
        doc = _read_yaml(path) if path is not None and path.is_file() else None
        if not isinstance(doc, dict):
            return set()
        rows = [row for job in (doc.get("jobs") or []) if isinstance(job, dict)
                for row in (job.get("effects") or []) if isinstance(row, dict)]
        return flags_written({"effects": rows})

    def _collection_flags_written(self) -> set[str]:
        """Flags a collection's completion ``effects`` write
        (``inventory.evaluate_collections``, ``tables/collections.yaml``)."""
        directory = self._dir("tables")
        path = directory / "collections.yaml" if directory is not None else None
        doc = _read_yaml(path) if path is not None and path.is_file() else None
        if not isinstance(doc, dict):
            return set()
        rows = [row for entry in (doc.get("collections") or []) if isinstance(entry, dict)
                for row in (entry.get("effects") or []) if isinstance(row, dict)]
        return flags_written({"effects": rows})

    def check_decks_and_structures(self) -> None:
        """
        Decks, clocks and threads: ids unique, every reference resolves, and
        the two-direction flag check that made the Garden's content safe.
        """
        docs = self._structural_docs()
        if not docs:
            return

        # Card ids unique per deck; a duplicated id makes `resolve_card`
        # ambiguous about which card a client chose.
        #
        # The deck and card ids are collected in this same pass because
        # `check_forced_scenes` below needs both, and walking the deck
        # directory twice to answer one question would be silly.
        known_decks: set[str] = set()
        known_cards: set[str] = set()
        for path in _yaml_files(self._dir("decks")):
            data = _read_yaml(path)
            source = self._rel(path)
            if not isinstance(data, dict):
                self._add(source, "-", "deck file is not a YAML mapping")
                continue
            known_decks.add(str(data.get("id") or path.stem))
            if "repeatable" in data and not isinstance(data["repeatable"], bool):
                # The loader reads only `is True`, so `repeatable: "yes"` would
                # load as a one-shot deck its author believed re-deals.
                self._add(
                    source,
                    str(data.get("id") or path.stem),
                    f"repeatable must be true or false, got {data['repeatable']!r}",
                )
            seen_cards: set[str] = set()
            for card in data.get("cards") or []:
                card_id = str((card or {}).get("id") or "")
                if not card_id:
                    self._add(source, "-", "card has no id")
                    continue
                if card_id in seen_cards:
                    self._add(source, card_id, "duplicate card id in this deck")
                seen_cards.add(card_id)
                known_cards.add(card_id)
                self._check_beat_shapes(source, card_id, card)

        self._check_forced_scenes(known_decks, known_cards)

        # Thread templates' optional keys (v0.15: `repeatable`, `broken_text`).
        threads_path = self._file("threads")
        threads_doc = _read_yaml(threads_path) if threads_path is not None else None
        if isinstance(threads_doc, dict):
            from engine.game.threads import template_key_problems

            source = self._rel(threads_path)  # type: ignore[arg-type]
            for template_id, raw in (threads_doc.get("templates") or {}).items():
                for problem in template_key_problems(raw):
                    self._add(source, str(template_id), problem)

        # Clock table: every clock it drives must be declared in state.yaml as
        # a clock. A clock the schema does not declare is a write the store
        # refuses, silently, at the exact moment the setpiece should fire.
        clocks_path = self._file("clocks")
        clocks_doc = _read_yaml(clocks_path) if clocks_path is not None else None
        if isinstance(clocks_doc, dict) and self.schema_loaded:
            source = self._rel(clocks_path)  # type: ignore[arg-type]
            for clock_id in (clocks_doc.get("clocks") or {}):
                if str(clock_id) not in self.declared_clocks:
                    self._add(
                        source,
                        str(clock_id),
                        "clock is not declared in state.yaml (kind: clock)",
                    )

        # Every clock gated on anywhere must be declared.
        if self.schema_loaded:
            for source, doc in docs.items():
                for clock_id in sorted(clock_refs(doc)):
                    if clock_id not in self.declared_clocks and clock_id not in self.declared_values:
                        self._add(source, clock_id, "clock is not declared in state.yaml")

        # Effect rows that apply_effect will drop on the floor.
        for source, doc in docs.items():
            self._check_effect_rows(source, doc)

        # Generic reference resolution over every structural document.
        for source, doc in docs.items():
            self._check_generic_refs(source, doc)
            if self.schema_loaded:
                for name in sorted(value_refs(doc) - self.declared_values):
                    self._add(source, name, "value is not declared in state.yaml")

        # The two-direction flag check, generalised from the Garden's tests.
        dictionary = load_canon_dictionary(self.manifest)
        canon = canon_flags(dictionary, clocks_doc)
        written: set[str] = set()
        read: set[str] = set()
        for doc in docs.values():
            written |= flags_written(doc)
            read |= flags_read(doc)
        # A labour posting's own `effects` (v0.17, economy.work) write flags a
        # gate may read -- HUE & CRY's `honest_wage_earned`, read by an ending.
        # Writers only: the labour table is not a structural document.
        written |= self._labour_flags_written()
        # And a collection's completion `effects` (v0.17 T6): HUE & CRY's
        # `magpies_hoard_complete`, read by The Legend. Writers only, too.
        written |= self._collection_flags_written()

        for source, doc in docs.items():
            for flag in sorted(flags_read(doc)):
                if flag in canon or flag in written or engine_owned_flag(flag):
                    continue
                self._add(
                    source,
                    flag,
                    "flag is read but never written and not canon; this gate can never open",
                )
            for flag in sorted(flags_written(doc)):
                if (
                    flag in canon
                    or flag in read
                    or engine_owned_flag(flag)
                    or flag.startswith(ENGINE_READ_FLAG_PREFIXES)
                ):
                    continue
                # Without a canon dictionary there is no declared vocabulary to
                # hold a write-only flag against, so it is advisory dead weight
                # rather than a provable typo.
                self._add(
                    source,
                    flag,
                    "flag is written but never read and not canon",
                    severity="error" if dictionary is not None else "warning",
                )

    def _check_stage_reachability(
        self, source: str, quest_id: str, data: Any, declared_flags: set[str]
    ) -> None:
        """
        Stages that end instantly, and stages nothing can ever end.

        TWO WAYS TO AUTHOR A QUEST WITH NO MIDDLE, both of which load, validate
        and play:

        1. An EMPTY predicate. ``evaluate_condition`` documents that an empty
           condition is True -- "no condition is a satisfied one" -- so
           ``complete_when: {all: [{}]}`` completes the instant the stage opens.
        2. A ``flag:`` predicate naming a flag NO quest in the story declares.
           ``allowed_narrative_flags`` builds the narrator's entire permitted
           vocabulary from ``narrative_flags`` lists, so a flag that appears in
           none of them can never be raised by the only thing that raises them.

        ONLY THE FIRST IS CHECKED HERE, and the second is worth recording as a
        thing this file deliberately does NOT do. Flag reachability was tried
        twice and abandoned twice. Scoped to the quest and its current stage it
        reported seven stages across two shipped stories, every one a false
        positive: a flag is durable once raised, so a stage may legitimately
        wait on one an EARLIER stage declared, and a flag branch under ``any:``
        need not be satisfiable when a sibling timeout is. Widened to the whole
        quests directory it still reported four, because
        ``collection_brass_evidence_complete`` and its kind are raised by the
        COLLECTIONS system rather than by the narrator -- flags are global and
        several engine systems write them, so "who could raise this" is a
        question about every content type at once, not about quests.

        Answering it properly means the two-direction sweep
        ``check_decks_and_structures`` already runs for structural documents,
        extended across quests, tables and effects. That is a real job and this
        is not the place to half-do it: a check that fails ``--strict`` on
        correct content is worse than no check, which is the same lesson the
        gate check taught earlier.
        """
        del declared_flags  # see the docstring: the flag half is not checked here
        for stage in data.get("stages") or []:
            if not isinstance(stage, dict):
                continue
            ref = f"{quest_id or '-'}/{str(stage.get('id') or '-')}"

            for node in walk(stage.get("complete_when")):
                # A predicate dict with no keys at all. Structural keys are not
                # predicates, so `{all: [...]}` is not the empty case.
                if not node:
                    self._add(
                        source,
                        ref,
                        "empty predicate in `complete_when`; an empty condition "
                        "evaluates TRUE, so this stage completes the moment it opens",
                    )

    def _check_effect_rows(self, source: str, doc: Any) -> None:
        """
        Effect rows whose kind and fields disagree, which ``apply_effect``
        discards without a word.

        ``_e_value`` resolves its target from ``name``/``value``/``id`` and
        returns ``_unknown`` when none is present -- deliberately, so old or
        foreign content cannot abort a turn. The cost of that mercy is that a
        ``value`` row carrying another kind's fields (``item_id``/``qty`` is
        the one a drafting model reaches for) is a no-op that reads like a
        working effect. A whole nine-day deck set came back that way: every
        beat had effects, no meter could move, and nothing anywhere said so.
        """
        wants = {"value": ("name", "value", "id"), "flag": ("flag",), "item": ("item_id", "item")}
        for node in walk(doc):
            kind = node.get("type")
            if not isinstance(kind, str) or kind not in wants:
                continue
            if any(key in node for key in wants[kind]):
                continue
            # Name the foreign keys it DID carry -- "value(item_id, qty)" says
            # which other kind's row this was written as, which is the whole
            # diagnosis. Bare "value" would send the author hunting.
            carried = ", ".join(sorted(k for k in node if k != "type")) or "nothing"
            self._add(
                source,
                f"{kind}({carried})",
                f"`{kind}` effect names no "
                f"`{wants[kind][0]}`; apply_effect discards this row in silence",
            )

    #: A beat text that is ONLY a declared value and a signed number --
    #: "composure +1", "favor -2". Anchored and whole-string on purpose: prose
    #: that happens to mention a meter is fine and common, and only a text
    #: consisting of nothing else is unambiguously a receipt in the wrong slot.
    _RECEIPT_AS_PROSE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*([+-])\s*\d+(\.\d+)?\s*$")

    def _check_beat_prose(self, source: str, ref: str, beat: Any) -> None:
        """
        Beat text that is a mechanical receipt rather than a sentence.

        A drafting model, asked for a beat whose effect moves ``composure``,
        will sometimes write ``text: composure +1`` -- putting the delta in
        the slot the PLAYER reads. The effect beside it is correct, so nothing
        breaks and nothing warns; the story simply says "composure +1" out
        loud. In a story whose meters are declared ``veiled`` that is the one
        thing the visibility setting exists to prevent, and the narrator
        persona forbids it in the same words.

        Seen in a drafted finale: four of eight beats read ``composure +1``,
        ``suspicion +1``, ``favor +1``.
        """
        texts: list[str] = []
        gate = (beat or {}).get("gate")
        if isinstance(gate, dict):
            for branch in ("on_pass", "on_fail"):
                node = gate.get(branch)
                if isinstance(node, dict) and isinstance(node.get("text"), str):
                    texts.append(node["text"])
        band = (beat or {}).get("band")
        if isinstance(band, dict) and isinstance(band.get("text"), str):
            texts.append(band["text"])

        known = self.declared_values | self.declared_clocks
        for text in texts:
            match = self._RECEIPT_AS_PROSE.match(text)
            if match is None:
                continue
            name = match.group(1)
            if self.schema_loaded and name not in known:
                continue
            self._add(
                source,
                ref,
                f"beat text is a mechanical receipt ({text.strip()!r}), not prose; "
                "the player reads this slot",
            )

    #: A sentence that is an author's note, not a line the player could pick:
    #: "Sets `x`, which...", "Resolve with `y`.", "Always.", "RARE and...".
    _DESIGN_NOTE = re.compile(
        r"(?:^|(?<=[.!?])\s+)(?:Sets\b|Resolve\b|Always\.|INTENT\b|CONSTRAINTS\b|RARE\b|MENU\b)"
    )

    def _check_beat_label(self, source: str, ref: str, beat: Any) -> None:
        """
        ADVISORY: a menu beat whose text carries an author's note and that has
        no ``label:``.

        A menu beat's chip reads ``director.player_label``: the beat's
        ``label``, else the first sentence of its text with backticked spans
        removed. Its text is the NARRATOR's direction, and authors write notes
        into it ("Sets `resisted_call`, which is the only thing..."); without
        a label, a note in the first sentence is what the player reads (v0.21.0
        K1: 41 beats, in the Wicked Garden and Dev Story). An advisory, not an
        error: the narrator is meant to read the note.
        """
        if not isinstance(beat, dict) or str(beat.get("label") or "").strip():
            return
        text = str(beat.get("text") or "")
        if "`" not in text and not self._DESIGN_NOTE.search(text):
            return
        self._add(
            source,
            ref,
            "menu beat text carries an author's note (a `code` span or a 'Sets'/"
            "'Resolve'/'Always.'/'RARE' sentence) and no `label:`; the player's "
            "chip is cut from that text -- add a `label:`",
            severity="warning",
        )

    def _check_forced_scenes(
        self, known_decks: set[str], known_cards: set[str]
    ) -> None:
        """
        Every ``forces_scene:`` names a deck or a card that actually exists.

        A CLOCK IS A PROMISE THE ENGINE KEEPS -- that is the sentence in
        ``engine/game/clocks.py``'s own docstring, and it is the whole
        difference between a clock and a meter. ``forces_scene`` is how the
        promise is written down, and until this check existed the word
        ``forces_scene`` appeared NOWHERE in this validator. The result: The
        Wicked Garden's four forced scenes all named label-shaped fragments
        rather than ids, so four clocks filled, raised a scene nothing could
        resolve, and left it pending forever -- measured at 100% pending across
        a 40-run walk, with zero validation errors reported.

        Both forms are legal, because both are useful and both ship:
        naming a DECK deals that whole deck; naming a CARD forces that one card
        into the next hand. Only naming neither is an error.
        """
        clocks_path = self._file("clocks")
        if clocks_path is None:
            return
        doc = _read_yaml(clocks_path)
        if not isinstance(doc, dict):
            return
        source = self._rel(clocks_path)

        def _walk(node: Any) -> Any:
            if isinstance(node, dict):
                if "forces_scene" in node:
                    yield str(node.get("forces_scene") or "").strip()
                for value in node.values():
                    yield from _walk(value)
            elif isinstance(node, list):
                for value in node:
                    yield from _walk(value)

        for scene_id in _walk(doc):
            self._check_scene_ref(source, scene_id, known_decks, known_cards, "clock's")

    def _check_scene_ref(
        self,
        source: str,
        scene_id: str,
        known_decks: set[str],
        known_cards: set[str],
        whose: str,
    ) -> None:
        """One ``forces_scene`` value: empty, a deck, a card, or an error."""
        if not scene_id:
            self._add(source, "-", "forces_scene is empty")
            return
        if scene_id in known_decks or scene_id in known_cards:
            return
        if not known_decks:
            self._add(
                source,
                scene_id,
                "forces_scene is declared but this story ships no decks, "
                f"so the {whose} promise can never be kept",
            )
        else:
            self._add(
                source,
                scene_id,
                "forces_scene names neither a deck nor a card that exists "
                "(engine/content/director.py resolves it against both)",
            )

    def check_declared_event_scenes(self) -> None:
        """
        Every ``forces_scene:`` on a declared world event names a deck or card.

        Its own check rather than a branch of ``check_decks_and_structures``,
        which returns early for a story with no decks, clocks, threads or
        endings -- and "an event forces a scene in a story with no decks" is
        exactly the case that must be reported. The event's promise is kept by
        the same director that keeps a clock's (``clocks.forced_scenes``).
        """
        path = self._file("world_schedules")
        if path is None or not path.is_file():
            return
        doc = _read_yaml(path)
        events = doc.get("events") if isinstance(doc, dict) else None
        if not isinstance(events, dict):
            return
        declared = [
            (str(event_id), str(spec.get("forces_scene") or "").strip())
            for event_id, spec in events.items()
            if isinstance(spec, dict) and "forces_scene" in spec
        ]
        if not declared:
            return

        known_decks: set[str] = set()
        known_cards: set[str] = set()
        for deck_path in _yaml_files(self._dir("decks")):
            data = _read_yaml(deck_path)
            if not isinstance(data, dict):
                continue
            known_decks.add(str(data.get("id") or deck_path.stem))
            for card in data.get("cards") or []:
                card_id = str((card or {}).get("id") or "") if isinstance(card, dict) else ""
                if card_id:
                    known_cards.add(card_id)

        source = self._rel(path)
        for _event_id, scene_id in declared:
            self._check_scene_ref(source, scene_id, known_decks, known_cards, "event's")

    #: Condition predicates whose value names a world event (a string or a list).
    EVENT_PREDICATES = ("event_active", "event_seen", "held_before_event")
    #: Events the engine raises itself: the flagship's three schedule slots
    #: (known only when the story's schedules file declares the block) and the
    #: procgen festival (``schedules.declared_events_due``).
    ENGINE_EVENT_IDS = frozenset({"festival"})

    def _story_yaml_files(self) -> list[Path]:
        """Every YAML file a declared ``paths.*`` entry resolves to, once each."""
        seen: dict[str, Path] = {}
        for key in sorted(self.manifest.paths):
            directory = self._dir(key)
            if directory is not None and directory.is_dir():
                for path in _yaml_files(directory):
                    seen.setdefault(str(path.resolve()), path)
                continue
            path = self._file(key)
            if path is not None and path.is_file() and path.suffix == ".yaml":
                seen.setdefault(str(path.resolve()), path)
        return [seen[k] for k in sorted(seen)]

    def check_event_references(self) -> None:
        """
        Every event a condition names is an event the story can raise (v0.17).

        ``{event_active: hanging_fiar}`` is a predicate that is false forever
        and says nothing: nothing checked an event id against anything, so a
        typo in the Hanging Fair's gallows gate would have hanged nobody, ever.
        The events a story can raise are its ``world_schedules``' ``events:``
        (and any engine slot block that file declares -- the flagship's
        caravan, tinker, militia), the procgen festival, and every
        ``event_id`` its own content emits (a clock beat's or a doom phase's
        ``world_events``). Checked: ``event_active``, ``event_seen``,
        ``held_before_event`` and ``days_since_event``'s mapping form.
        """
        files = self._story_yaml_files()
        docs = [(path, _read_yaml(path)) for path in files]
        known: set[str] = set(self.ENGINE_EVENT_IDS)
        sched_path = self._file("world_schedules")
        if sched_path is not None and sched_path.is_file():
            sched = _read_yaml(sched_path)
            if isinstance(sched, dict):
                known |= {str(k) for k in (sched.get("events") or {})}
                known |= {str(k) for k, v in sched.items()
                          if k not in ("events", "rumors") and isinstance(v, dict)}
        for _path, doc in docs:
            for node in walk(doc):
                if node.get("event_id") and isinstance(node.get("event_id"), str):
                    known.add(node["event_id"])
        for path, doc in docs:
            for node in walk(doc):
                named: list[str] = []
                for key in self.EVENT_PREDICATES:
                    if key in node:
                        value = node[key]
                        named += [str(v) for v in (value if isinstance(value, list) else [value])]
                since = node.get("days_since_event")
                if isinstance(since, dict):
                    named.append(str(since.get("event") or since.get("event_id") or ""))
                for event_id in named:
                    if event_id and event_id not in known:
                        self._add(
                            self._rel(path),
                            event_id,
                            f"a condition names event '{event_id}', which the story "
                            "never raises (no `world_schedules` event, engine slot "
                            "or `event_id` declares it), so it is false forever",
                        )

    def _check_beat_shapes(self, source: str, card_id: str, card: Any) -> None:
        """
        ``_resolve_gate`` starts at ``passed = True`` and only lowers it on a
        ``when`` threshold or a ``check`` roll (engine/content/deck.py). So a
        gate carrying neither always takes ``on_pass`` -- and an ``on_fail``
        written beside it is text no seed can ever reach.

        Only that pairing is reported. A gate with ``on_pass`` alone and no
        condition is a shipped idiom, not a defect: it is how both deck
        stories write "this beat always happens, and here is what it costs"
        (205 beats in the Garden alone). Flagging those would fail
        ``--strict`` on a convention the engine supports.

        Caught on drafted content that read as a working story and validated
        clean -- the model writes gates that look conditional. Nothing else
        here looks at beat shape, and a beat that runs without erroring is
        exactly the defect a green suite keeps.
        """
        is_menu = "menu" in ((card or {}).get("tags") or [])
        for beat in (card or {}).get("beats") or []:
            gate = (beat or {}).get("gate")
            ref = f"{card_id}/{(beat or {}).get('id') or '-'}"
            self._check_beat_prose(source, ref, beat)
            if is_menu:
                self._check_beat_label(source, ref, beat)

            # One beat is one question. `_bind_beat` keeps the gate, drops the
            # band and logs -- at deck-load time, into a stream nobody reads
            # during authoring. The band's text and award are then authored
            # content that cannot run at any seed.
            if isinstance(gate, dict) and isinstance((beat or {}).get("band"), dict):
                self._add(
                    source,
                    ref,
                    "beat declares both `gate` and `band`; the loader keeps the "
                    "gate and discards the band",
                )

            if not isinstance(gate, dict):
                continue
            if "when" in gate or isinstance(gate.get("check"), dict):
                continue
            if not isinstance(gate.get("on_fail"), dict):
                continue
            self._add(
                source,
                ref,
                "gate has neither `when` nor `check`, so it always passes and "
                "`on_fail` is unreachable",
            )

    # -- endings and epilogues ---------------------------------------------

    def check_endless(self) -> None:
        """`endless: true` refuses `paths.endings` and `paths.epilogues` (spec §2.4)."""
        raw = self.manifest.extras.get("endless")
        if raw is not None and not isinstance(raw, bool):
            self._add("game.yaml", "endless", "must be true or false")
        if raw is True:
            for key in ("endings", "epilogues"):
                if self.manifest.paths.get(key):
                    self._add("game.yaml", "endless", f"an endless story may not declare paths.{key}")

    def check_social(self) -> None:
        """`paths.social` (spec §2.1): each file parses; each data task adds its own checks."""
        directory = self._dir("social")
        if directory is None:
            return
        from engine import social

        for name in social.FILES:
            try:
                social.load_file(directory, name)
            except ValueError as exc:
                self._add(f"social/{name}.yaml", name, str(exc))
        self._check_population(directory)
        self._check_creation(directory)
        self._check_behaviours(directory)
        self._check_apps(directory)
        self._check_relationships(directory)
        self._check_media(directory)
        self._check_texter(directory)
        self._check_games(directory)
        self._check_meets(directory)
        self._check_growth(directory)
        self._check_conversation(directory)
        self._check_promises(directory)
        self._check_plans(directory)
        self._check_life_events(directory)
        self._check_scenes(directory)

    def _check_scenes(self, directory: Path) -> None:
        """scenes.yaml (v0.23.0 spec §10, §19.6): `scene.check_data` -- the check `load_all` runs, passed the
        population.yaml trait ids (a move's `fit.traits`, pre-flight F23)."""
        from engine import social
        from engine.social import scene

        try:
            data = social.load_file(directory, "scenes")
            population_data = social.load_file(directory, "population")
        except ValueError:
            return  # reported by check_social
        if not data:
            return
        traits = frozenset(str(t["id"]) for t in population_data.get("traits") or []
                           if isinstance(t, dict) and t.get("id"))
        try:
            scene.check_data(data, traits=traits)
        except ValueError as exc:
            # scene's faults read "social: scenes.yaml: <key>: <message>".
            parts = str(exc).split(": ", 3)
            self._add("social/scenes.yaml", parts[2] if len(parts) == 4 else "scenes",
                      parts[3] if len(parts) == 4 else str(exc))

    def _check_plans(self, directory: Path) -> None:
        """plans.yaml (v0.23.0 spec §9): `plans.check_data` -- the check `load_all` runs."""
        from engine import social
        from engine.social import plans

        try:
            data = social.load_file(directory, "plans")
        except ValueError:
            return  # reported by check_social
        if not data:
            return
        try:
            plans.check_data(data)
        except ValueError as exc:
            # plans' faults read "social: plans.yaml: <key>: <message>".
            parts = str(exc).split(": ", 3)
            self._add("social/plans.yaml", parts[2] if len(parts) == 4 else "plans",
                      parts[3] if len(parts) == 4 else str(exc))

    def _check_life_events(self, directory: Path) -> None:
        """life_events.yaml (v0.23.0 spec §11): `life.check_data` -- the check `load_all` runs."""
        from engine import social
        from engine.social import life

        try:
            data = social.load_file(directory, "life_events")
            relationships_data = social.load_file(directory, "relationships")
        except ValueError:
            return  # reported by check_social
        if not data:
            return
        moods = (relationships_data.get("mood") or {}).get("values") if isinstance(relationships_data, dict) else None
        try:
            life.check_data(data, moods=tuple(moods) if isinstance(moods, list) else None)
        except ValueError as exc:
            # life's faults read "social: life_events.yaml: <key>: <message>".
            parts = str(exc).split(": ", 3)
            self._add("social/life_events.yaml", parts[2] if len(parts) == 4 else "life_events",
                      parts[3] if len(parts) == 4 else str(exc))
        decks_dir = self._file("decks")
        for row in data.get("player") or ():
            if not isinstance(row, dict):
                continue
            rid = str(row.get("id") or "")
            if (row.get("flag") or row.get("news")) and "lasts_days" not in row:
                self._add("social/life_events.yaml", f"player.{rid}.lasts_days",
                          "a row with a flag or news needs lasts_days (news shows only while it runs)")
            deck_id = row.get("scene")
            if not deck_id:
                continue
            path = decks_dir / f"{deck_id}.yaml" if decks_dir else None
            if path is None or not path.is_file():
                self._add("social/life_events.yaml", f"player.{rid}.scene", f"no deck {deck_id!r} in paths.decks")
                continue
            deck = yamlio.safe_load(path.read_text(encoding="utf-8")) or {}
            # The deck's `when:` must READ the flag (pre-flight F22): the beats' own clear-effects name it too,
            # so a substring of the file could never fail.
            if row.get("flag") and str(row["flag"]) not in flags_read(deck.get("when")):
                self._add("social/life_events.yaml", f"player.{rid}.scene",
                          f"deck {deck_id!r}'s when: does not read the row's flag {row.get('flag')!r}")

    def _check_promises(self, directory: Path) -> None:
        """promises.yaml (v0.23.0 spec §5): `promises.check_data` -- the check `load_all` runs."""
        from engine import social
        from engine.social import promises

        try:
            data = social.load_file(directory, "promises")
        except ValueError:
            return  # reported by check_social
        if not data:
            return
        try:
            promises.check_data(data)
        except ValueError as exc:
            # promises' faults read "social: promises.yaml: <key>: <message>".
            parts = str(exc).split(": ", 3)
            self._add("social/promises.yaml", parts[2] if len(parts) == 4 else "promises",
                      parts[3] if len(parts) == 4 else str(exc))

    def _check_conversation(self, directory: Path) -> None:
        """conversation.yaml (v0.23.0 spec §3.3, §4): `convo.check_data`, every per-archetype key a
        behaviours.yaml archetype -- the check `load_all` runs."""
        from engine import social
        from engine.social import convo

        try:
            data = social.load_file(directory, "conversation")
            behaviours = social.load_file(directory, "behaviours")
        except ValueError:
            return  # reported by check_social
        if not data:
            return
        archetypes = behaviours.get("archetypes") if isinstance(behaviours.get("archetypes"), dict) else {}
        try:
            convo.check_data(data, archetypes=archetypes)
        except ValueError as exc:
            # convo's faults read "social: conversation.yaml: <key>: <message>".
            parts = str(exc).split(": ", 3)
            self._add("social/conversation.yaml", parts[2] if len(parts) == 4 else "conversation",
                      parts[3] if len(parts) == 4 else str(exc))

    def _check_growth(self, directory: Path) -> None:
        """Growth (v0.23.0 spec §6.7, §19.6): `growth.check_data` over growth.yaml, topics.yaml and
        layers.yaml, every `trait_mult` key a population.yaml trait -- the check `load_all` runs."""
        from engine import social
        from engine.social import growth

        try:
            data = social.load_file(directory, "growth")
            topics = social.load_file(directory, "topics")
            layers = social.load_file(directory, "layers")
            population = social.load_file(directory, "population")
        except ValueError:
            return  # reported by check_social
        if not data:
            return
        traits = frozenset(str(t["id"]) for t in population.get("traits") or []
                           if isinstance(t, dict) and t.get("id"))
        try:
            growth.check_data(data, topics, layers, traits=traits)
        except ValueError as exc:
            # growth's faults read "social: <file>.yaml: <key>: <message>".
            parts = str(exc).split(": ", 3)
            if len(parts) == 4:
                self._add(f"social/{parts[1]}", parts[2], parts[3])
            else:
                self._add("social/growth.yaml", "growth", str(exc))

    def _check_meets(self, directory: Path) -> None:
        """Meet-ups (v0.22.0 T24; v0.23.0 T13): relationships.yaml's `meets:` block (`post_meet` and the band
        words, `scene.meets_faults`), and venues.yaml's kinds and twelve or more venues, each neighbourhood and
        hobby a population.yaml id (`places.venue_faults`)."""
        from engine import social
        from engine.social import places, scene

        try:
            venues = social.load_file(directory, "venues")
            relationships_data = social.load_file(directory, "relationships")
            population_data = social.load_file(directory, "population")
        except ValueError:
            return  # reported by check_social
        if not venues and "meets" not in relationships_data:
            return
        faults = (places.venue_faults(venues, population_data or None)
                  + scene.meets_faults(relationships_data, venues_declared=bool(venues)))
        for source, key, message in faults:
            self._add(f"social/{source}", key, message)

    def _check_games(self, directory: Path) -> None:
        """`games.yaml` (spec §21, v0.22.0 T22-T23): `wordgame`'s premiums 11x11, its bag 72 tiles with
        two blanks, its numbers and `words.txt` beside it; `this_or_that`'s numbers, its tags (each
        hobby, trait and slider one population.yaml knows) and its bank of 60 or more pairs."""
        from engine import social

        try:
            data = social.load_file(directory, "games")
        except ValueError:
            return  # reported by check_social
        if "wordgame" in data:
            from engine.social.games import wordgame

            for key, message in wordgame.data_faults(data["wordgame"], directory):
                self._add(f"social/{wordgame.WORDS_FILE}" if key == wordgame.WORDS_FILE else "social/games.yaml",
                          key, message)
        if "this_or_that" in data:
            from engine.social.games import this_or_that

            try:
                population = social.load_file(directory, "population")
            except ValueError:
                population = None  # reported by check_social
            for key, message in this_or_that.data_faults(data["this_or_that"], population or None):
                self._add("social/games.yaml", key, message)

    def _check_media(self, directory: Path) -> None:
        """`media.yaml` (spec §13.1, v0.22.0 T19) whole, and what it names elsewhere: every subject's
        `requires_flag` a population.yaml flag, every `when` a schedule status, every `unlock_stage`
        a stage, every `mood_mult` key a relationships.yaml mood value."""
        from engine import social
        from engine.social import media

        try:
            data = social.load_file(directory, "media")
            population_data = social.load_file(directory, "population")
            relationships_data = social.load_file(directory, "relationships")
        except ValueError:
            return  # reported by check_social
        for key, message in media.media_faults(data, population_data, relationships_data):
            self._add("social/media.yaml", key, message)

    def _check_texter(self, directory: Path) -> None:
        """`prompts/texter.md` (spec §11.3-11.4, v0.22.0 T13): its persona, instruction table and
        fallbacks parse, every situation the engine or behaviours.yaml emits has a row, and every
        fallback archetype is declared."""
        from engine import social
        from engine.social import voicing

        source = f"prompts/{voicing.TEXTER_FILE}"
        path = directory.parent.parent / "prompts" / voicing.TEXTER_FILE
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            self._add(source, "file", "missing: a story declaring paths.social needs it")
            return
        try:
            prompt = voicing.parse_texter(text)
        except ValueError as exc:
            parts = str(exc).split(": ", 3)
            key, message = (parts[2], parts[3]) if len(parts) == 4 else ("texter", str(exc))
            self._add(source, key, message)
            return
        try:
            behaviours = social.load_file(directory, "behaviours")
        except ValueError:
            behaviours = {}  # reported by check_social
        for key, message in voicing.situation_faults(prompt, behaviours):
            self._add(source, key, message)

    def _check_relationships(self, directory: Path) -> None:
        """`relationships.yaml` (spec §10, v0.22.0 T9) whole, and what behaviours.yaml names in it:
        every initiation's `stage_min` a stage, every arc's `then.stage` a stage and its measures the
        ones the engine counts, every `warmth_cap_band` a band."""
        from engine import social
        from engine.social import relationships

        source = "social/relationships.yaml"
        try:
            data = social.load_file(directory, "relationships")
            behaviours = social.load_file(directory, "behaviours")
        except ValueError:
            return  # reported by check_social
        if not data:
            return
        try:
            relationships.check_data(data)
        except ValueError as exc:
            parts = str(exc).split(": ", 3)
            key, message = (parts[2], parts[3]) if len(parts) == 4 else ("relationships", str(exc))
            self._add(source, key, message)
            return
        from engine.social import agreement

        for key, message in agreement.check_phrases(data):   # spec §11.5's phrase lists (T11)
            self._add(source, key, message)
        stages = set(data["stages"])
        bands = {str(row["name"]) for row in data["bands"]}
        bsource = "social/behaviours.yaml"
        rows = behaviours.get("archetypes") if isinstance(behaviours.get("archetypes"), dict) else {}
        for name, row in rows.items():
            if not isinstance(row, dict):
                continue
            band = row.get("warmth_cap_band")
            if band is not None and band not in bands:   # relationships.check_cap_bands, one row per fault
                self._add(bsource, f"archetypes.{name}.warmth_cap_band", f"{band!r} is no relationships.yaml band")
            for i, init in enumerate(row.get("initiations") or []):
                stage = ((init or {}).get("when") or {}).get("stage_min") if isinstance(init, dict) else None
                if stage is not None and stage not in stages:
                    self._add(bsource, f"archetypes.{name}.initiations[{i}].when.stage_min",
                              f"{stage!r} is no relationships.yaml stage")
        arcs = behaviours.get("arcs") if isinstance(behaviours.get("arcs"), dict) else {}
        for name, spec in arcs.items():
            if not isinstance(spec, dict):
                continue
            for point, allowed in (("at", relationships.ARC_POINTS), ("from", relationships.ARC_STARTS)):
                for measure in (spec.get(point) or {}) if isinstance(spec.get(point), dict) else ():
                    if measure not in allowed:
                        self._add(bsource, f"arcs.{name}.{point}", f"{measure!r} is not one of {', '.join(allowed)}")
            then = ((spec.get("beat") or {}).get("then") or {}) if isinstance(spec.get("beat"), dict) else {}
            for key, value in then.items() if isinstance(then, dict) else ():
                if key == "stage":
                    if value not in stages:
                        self._add(bsource, f"arcs.{name}.beat.then.stage", f"{value!r} is no relationships.yaml stage")
                elif key not in relationships.ARC_MOVES:
                    self._add(bsource, f"arcs.{name}.beat.then", f"{key!r} is not one of stage, "
                                                                  f"{', '.join(relationships.ARC_MOVES)}")
            each = spec.get("each_day") or {}
            for key in each if isinstance(each, dict) else ():
                if key not in relationships.ARC_MOVES:
                    self._add(bsource, f"arcs.{name}.each_day", f"{key!r} is not one of "
                                                                f"{', '.join(relationships.ARC_MOVES)}")

    def _check_apps(self, directory: Path) -> None:
        """`apps.yaml` (spec §6, §8, v0.22.0 T7): every app's kind, capabilities and costs; the
        dating apps' decks, limits and culture weights; and the `matching:` block whole."""
        from engine import social
        from engine.social import apps as social_apps
        from engine.social import matching, messaging
        from engine.social.events import DAILY_HOUR as daily_hour
        from engine.social.kinds import stage_rank

        source = "social/apps.yaml"
        try:
            data = social.load_file(directory, "apps")
        except ValueError:
            return  # reported by check_social
        if not data:
            return

        def add(key: str, message: str) -> None:
            self._add(source, key, message)

        def number(value: Any) -> bool:
            return isinstance(value, (int, float)) and not isinstance(value, bool)

        rows = data.get("apps")
        if not isinstance(rows, dict) or not rows:
            add("apps", "must be a non-empty mapping of apps")
            rows = {}
        dating: list[str] = []
        for name, row in rows.items():
            where = f"apps.{name}"
            if not isinstance(row, dict):
                add(where, "must be a mapping")
                continue
            kind = row.get("kind")
            if kind not in social_apps.KINDS:
                add(f"{where}.kind", f"must be one of {', '.join(social_apps.KINDS)}, not {kind!r}")
            caps = row.get("capabilities", [])
            if not isinstance(caps, list) or any(c not in social_apps.CAPABILITIES for c in caps):
                add(f"{where}.capabilities", f"each must be one of {'|'.join(social_apps.CAPABILITIES)}, not {caps!r}")
            costs = row.get("cost_minutes", {})
            if not isinstance(costs, dict):
                add(f"{where}.cost_minutes", "must be a mapping of verb to minutes")
                costs = {}
            for verb, minutes in costs.items():
                if verb not in social_apps.COST_VERBS:
                    add(f"{where}.cost_minutes", f"{verb!r} is no verb that reads a cost "
                                                 f"({', '.join(social_apps.COST_VERBS)})")
                elif not number(minutes) or minutes < 0:
                    add(f"{where}.cost_minutes", f"{verb}: must be minutes, 0 or more, not {minutes!r}")
            if "unlock" in row and stage_rank(row["unlock"]) < 0:
                add(f"{where}.unlock", f"must be a live stage (spec §10.3), not {row['unlock']!r}")
            if kind != "dating":
                continue
            dating.append(str(name))
            if row.get("first_message", "either") not in messaging.FIRST_MESSAGE:
                add(f"{where}.first_message", f"must be one of {', '.join(messaging.FIRST_MESSAGE)}, "
                                              f"not {row.get('first_message')!r}")
            if row.get("deck") not in social_apps.DECKS:
                add(f"{where}.deck", f"must be one of {', '.join(social_apps.DECKS)}")
            for key in ("likes_per_day", "match_expiry_days"):
                value = row.get(key)
                if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                    add(f"{where}.{key}", f"must be a whole number above 0, not {value!r}")
            for key in ("super_likes_per_day", "likes_you_per_day"):
                value = row.get(key, 0)
                if not number(value) or value < 0:
                    add(f"{where}.{key}", f"must be a number, 0 or more, not {value!r}")
            culture = row.get("culture")
            if not isinstance(culture, dict):
                add(f"{where}.culture", "required: {archetype_weights, intent_weights, selectivity_mult}")
                continue
            for key in ("archetype_weights", "intent_weights"):
                weights = culture.get(key)
                if not isinstance(weights, dict) or not weights:
                    add(f"{where}.culture.{key}", "required: a mapping of id to a weight above 0")
                    continue
                for ident, weight in weights.items():
                    if not number(weight) or weight <= 0:
                        add(f"{where}.culture.{key}", f"{ident}: weight must be above 0, not {weight!r}")
                    if key == "intent_weights" and ident not in matching.INTENTS:
                        add(f"{where}.culture.{key}", f"{ident!r} is not an intent ({', '.join(matching.INTENTS)})")
            # An unknown archetype id is _check_behaviours' (it reads behaviours.yaml's rows).
            mult = culture.get("selectivity_mult", 1.0)
            if not number(mult) or mult < 0:
                add(f"{where}.culture.selectivity_mult", f"must be a number, 0 or more, not {mult!r}")

        block = data.get("matching")
        if not isinstance(block, dict):
            add("matching", "required (spec §8)")
            return
        weights = block.get("weights")
        if not isinstance(weights, dict) or set(weights) != set(matching.TERMS) \
                or not all(number(w) and w >= 0 for w in weights.values()):
            add("matching.weights", f"must give each of {', '.join(matching.TERMS)} a weight, 0 or more")
        elif abs(sum(float(w) for w in weights.values()) - 1.0) > 1e-6:
            add("matching.weights", f"must sum to 1.0, not {sum(float(w) for w in weights.values()):g}")
        shorts = [short for _, short in matching.SHORT]
        pairs = {f"{a}_{b}" for i, a in enumerate(shorts) for b in shorts[i:]}
        table = block.get("looking_for_table")
        if not isinstance(table, dict):
            add("matching.looking_for_table", "required: a mapping of intent pairs to 0-1")
        else:
            for key, value in table.items():
                if key not in pairs:
                    add("matching.looking_for_table", f"{key!r} is no pair in the order {', '.join(shorts)}")
                elif not number(value) or not 0 <= value <= 1:
                    add("matching.looking_for_table", f"{key}: must be 0-1, not {value!r}")
        for key, low, high in (("dealbreaker_mult", 0, 1), ("compat_offset", 0, None), ("super_like_mult", 0, None)):
            value = block.get(key)
            if not number(value) or value < low or (high is not None and value > high):
                add(f"matching.{key}", f"must be a number {low}{'-' + str(high) if high is not None else ' or more'}, "
                                       f"not {value!r}")
        for key in ("chemistry", "completeness"):
            value = block.get(key)
            if not (isinstance(value, list) and len(value) == 2 and all(number(v) for v in value)
                    and value[0] <= value[1]):
                add(f"matching.{key}", f"must be [low, high], numbers with low <= high, not {value!r}")
        base = block.get("like_back_base")
        if not isinstance(base, dict):
            add("matching.like_back_base", "required: a base chance per dating app")
        else:
            for name in dating:
                if not number(base.get(name)) or base[name] < 0:
                    add("matching.like_back_base", f"{name}: must be a number, 0 or more")
        see = block.get("see_like_hours")
        if not (isinstance(see, dict) and number(see.get("median")) and see["median"] > 0
                and number(see.get("spread")) and see["spread"] >= 0
                and (("max" not in see) or (number(see["max"]) and see["max"] > 0))):
            add("matching.see_like_hours", "must be {median > 0, spread >= 0, max? > 0}")
        window = block.get("likes_you_hours")
        if not (isinstance(window, list) and len(window) == 2 and all(number(h) for h in window)
                and daily_hour <= window[0] < window[1] <= daily_hour + 24):
            add("matching.likes_you_hours", f"must be [start, end] clock hours within the deck's day "
                                            f"({daily_hour:g} to {daily_hour + 24:g}), not {window!r}")
        reach = block.get("discovery_distance")
        if not (isinstance(reach, dict) and reach
                and all(isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= 4 for v in reach.values())):
            add("matching.discovery_distance", "must map each discovery distance to a whole number 0-4")

    def _check_behaviours(self, directory: Path) -> None:
        """`behaviours.yaml` (spec §5, v0.22.0 T5): every archetype whole, every arc's shape,
        every archetype an app draws declared, and every job shape's week well formed."""
        from engine import social
        from engine.social import behaviour

        source = "social/behaviours.yaml"
        try:
            data = social.load_file(directory, "behaviours")
            apps = social.load_file(directory, "apps")
            population = social.load_file(directory, "population")
        except ValueError:
            return  # reported by check_social

        def report(exc: ValueError, fallback: str) -> None:
            # behaviour's faults read "social: behaviours.yaml: <key>: <message>".
            parts = str(exc).split(": ", 3)
            key, message = (parts[2], parts[3]) if len(parts) == 4 else (fallback, str(exc))
            self._add(source, key, message)

        if data:
            arcs = data.get("arcs") or {}
            if not isinstance(arcs, dict):
                self._add(source, "arcs", "must be a mapping")
                arcs = {}
            for name, spec in arcs.items():
                try:
                    behaviour.check_arc(str(name), spec)
                except ValueError as exc:
                    report(exc, f"arcs.{name}")
            rows = data.get("archetypes")
            if not isinstance(rows, dict) or not rows:
                self._add(source, "archetypes", "must be a non-empty mapping of archetypes")
                rows = {}
            for name, row in rows.items():
                try:
                    behaviour.build_archetype(str(name), row, arcs)
                except ValueError as exc:
                    report(exc, f"archetypes.{name}")
            if "pacing" in data:                             # v0.22.0's block: its terms moved (v0.23.0 T3)
                self._add(source, "pacing", "went in v0.23.0: the reply and ghost terms are conversation.yaml's "
                                            "`reply:` block")
            try:
                behaviour.check_canon(data)                  # spec §12.1, v0.22.0 T12
            except ValueError as exc:
                report(exc, "canon")
            for app, spec in (apps.get("apps") or {}).items() if isinstance(apps.get("apps"), dict) else ():
                weights = ((spec or {}).get("culture") or {}).get("archetype_weights") if isinstance(spec, dict) else None
                for name in weights or {}:
                    if name not in rows:
                        self._add("social/apps.yaml", f"apps.{app}.culture.archetype_weights",
                                  f"{name!r} is not a behaviours.yaml archetype")

        schedules = population.get("schedules")
        if not population or schedules is None:
            return
        psource = "social/population.yaml"
        if not isinstance(schedules, dict):
            self._add(psource, "schedules", "must be a mapping of job shape to week")
            return
        for row in population.get("jobs") or []:
            if isinstance(row, dict) and row.get("shape") not in schedules:
                self._add(psource, "jobs", f"{row.get('id')}: shape {row.get('shape')!r} has no schedules entry")
        for shape, week in schedules.items():
            if not isinstance(week, dict) or set(week) - set(behaviour.WEEKDAYS):
                self._add(psource, f"schedules.{shape}", f"must map weekdays ({', '.join(behaviour.WEEKDAYS)}) to bands")
                continue
            for day, bands in week.items():
                for band in bands or []:
                    ok = (isinstance(band, list) and len(band) == 3
                          and all(isinstance(h, (int, float)) and not isinstance(h, bool) for h in band[:2])
                          and 0 <= band[0] < band[1] <= 24 and band[2] in behaviour.STATUSES)
                    if not ok:
                        self._add(psource, f"schedules.{shape}.{day}",
                                  f"{band!r}: a band is [start, end, status], 0 <= start < end <= 24, "
                                  f"status one of {', '.join(behaviour.STATUSES)}")

    def _check_creation(self, directory: Path) -> None:
        """`creation.yaml` (spec §3, v0.22.0 T4): every field's shape, and every `of_table` a real table."""
        from engine import social
        from engine.social.creation import FIELD_KINDS

        source = "social/creation.yaml"
        try:
            form = social.load_file(directory, "creation")
            population = social.load_file(directory, "population")
        except ValueError:
            return  # reported by check_social
        if not form:
            return
        start = form.get("start_hour")
        if start is not None and (isinstance(start, bool) or not isinstance(start, int) or not 0 <= start <= 23):
            self._add(source, "start_hour", f"must be a whole hour 0-23, not {start!r}")
        fields = form.get("fields")
        if not isinstance(fields, dict) or not fields:
            self._add(source, "fields", "must be a non-empty mapping of fields")
            return

        def whole(value: Any) -> bool:
            return isinstance(value, int) and not isinstance(value, bool)

        def walk(mapping: dict[str, Any], prefix: str) -> None:
            for name, spec in mapping.items():
                key = f"fields.{prefix}{name}"
                if not isinstance(spec, dict):
                    self._add(source, key, "must be a field ({kind: ...}) or a mapping of fields")
                    continue
                if "kind" not in spec:
                    walk(spec, f"{prefix}{name}.")
                    continue
                kind = spec.get("kind")
                if kind not in FIELD_KINDS:
                    self._add(source, key, f"kind must be one of {', '.join(sorted(FIELD_KINDS))}, not {kind!r}")
                    continue
                for bound in ("min", "max"):
                    if bound in spec and not whole(spec[bound]):
                        self._add(source, key, f"{bound} must be a whole number")
                if whole(spec.get("min")) and whole(spec.get("max")) and spec["min"] > spec["max"]:
                    self._add(source, key, f"min {spec['min']} is above max {spec['max']}")
                ids: list[str] = []
                if kind in ("choice", "multi"):
                    named = spec.get("of_table")
                    if named:
                        rows = population.get(str(named))
                        if not isinstance(rows, list) or not rows:
                            self._add(source, key, f"of_table {named!r} names no population.yaml table")
                            continue
                        ids = [str(row.get("id")) for row in rows if isinstance(row, dict)]
                    else:
                        raw = spec.get("of")
                        if not isinstance(raw, list) or not raw or not all(isinstance(v, str) for v in raw):
                            self._add(source, key, "needs `of` (a list of ids, quoted where YAML reads a boolean) or `of_table`")
                            continue
                        ids = list(raw)
                if kind == "choice" and "default" in spec and str(spec["default"]) not in ids:
                    self._add(source, key, f"default {spec['default']!r} is not one of its choices")
                if kind == "multi" and whole(spec.get("min")) and spec["min"] > len(ids):
                    self._add(source, key, f"min {spec['min']} is more than its {len(ids)} choices")
                if kind == "multi" and whole(spec.get("max")) and spec["max"] > len(ids):
                    self._add(source, key, f"max {spec['max']} is more than its {len(ids)} choices")
                if kind == "int":
                    default = spec.get("default")
                    if not whole(default):
                        self._add(source, key, "an int field needs a whole-number default")
                    elif (whole(spec.get("min")) and default < spec["min"]) or (whole(spec.get("max")) and default > spec["max"]):
                        self._add(source, key, f"default {default} is outside its range")
                if kind == "text" and not isinstance(spec.get("default"), str):
                    self._add(source, key, "a text field needs a text default")
                if kind == "text" and not whole(spec.get("max")):
                    self._add(source, key, "a text field needs a whole-number max (free text is never unbounded)")
                if kind == "sliders":
                    raw = spec.get("of")
                    if not isinstance(raw, list) or not raw or not all(isinstance(v, str) for v in raw):
                        self._add(source, key, "needs `of`, a list of slider names")
                    if not (whole(spec.get("min")) and whole(spec.get("max"))):
                        self._add(source, key, "needs whole-number min and max")
                # population.yaml's attribute tables draw ids the player can also pick
                # (its `attribute_tables` comment): each must be one of this field's.
                if prefix == "attributes." and kind == "choice" and name in (population.get("attribute_tables") or []):
                    drawn = {str(row.get("id")) for row in population.get(name) or [] if isinstance(row, dict)}
                    missing = sorted(drawn - set(ids))
                    if missing:
                        self._add(source, key, f"population.yaml's {name} table draws {missing}, not among its choices")

        walk(fields, "")

        # creation.apply refuses a discovery range whose age_min is above its
        # age_max; the form's own defaults must not be one.
        discovery = fields.get("discovery")
        if isinstance(discovery, dict):
            low = (discovery.get("age_min") or {}).get("default") if isinstance(discovery.get("age_min"), dict) else None
            high = (discovery.get("age_max") or {}).get("default") if isinstance(discovery.get("age_max"), dict) else None
            if whole(low) and whole(high) and low > high:
                self._add(source, "fields.discovery", f"the default age_min {low} is above the default age_max {high}")

    def _check_population(self, directory: Path) -> None:
        """`population.yaml` (spec §4, v0.22.0 T3): the filter, the city, the pools and every weight."""
        from engine import social
        from engine.social import population

        source = "social/population.yaml"
        try:
            data = social.load_file(directory, "population")
        except ValueError:
            return  # reported by check_social
        if not data:
            return

        def add(key: str, message: str) -> None:
            self._add(source, key, message)

        spec = data.get("filter")
        if not isinstance(spec, dict) or spec.get("sex") not in population.FILTER_MODES:
            add("filter.sex", f"must be one of {', '.join(population.FILTER_MODES)}")

        hoods = [row.get("id") for row in data.get("neighbourhoods") or [] if isinstance(row, dict)]
        if len(hoods) != 11 or len(set(hoods)) != 11:
            add("neighbourhoods", f"must be exactly eleven distinct ids, not {len(set(hoods))}")
        table = data.get("distance")
        if not isinstance(table, dict) or set(table) != set(hoods):
            add("distance", "must have one row per neighbourhood, and no other")
        else:
            for a in hoods:
                row = table.get(a)
                if not isinstance(row, dict) or set(row) != set(hoods):
                    add("distance", f"{a}: must name every neighbourhood")
                    continue
                for b in hoods:
                    value = row.get(b)
                    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 4:
                        add("distance", f"{a}.{b}: must be a whole number 0-4")
                    elif (a == b and value != 0) or (table.get(b) or {}).get(a) != value:
                        add("distance", f"{a}.{b}: must be 0 on the diagonal and symmetric")

        bounds = data.get("age_bounds")
        values = [bounds.get(k) for k in ("min", "max")] if isinstance(bounds, dict) else [None, None]
        if not all(isinstance(v, int) and not isinstance(v, bool) for v in values) or values[0] > values[1]:
            add("age_bounds", "must be {min, max}, whole numbers with min <= max (the apps' own age floor is data)")

        for row in data.get("jobs") or []:
            if isinstance(row, dict) and row.get("article") not in (None, "a", "an"):
                add("jobs", f"{row.get('id')}: article must be a or an, not {row.get('article')!r}")

        names = data.get("names") if isinstance(data.get("names"), dict) else {}
        for sex in ("female", "male"):
            if not names.get(sex):
                add(f"names.{sex}", "must be a non-empty list of names")

        for key, rows in data.items():
            if isinstance(rows, list) and rows and all(isinstance(row, dict) for row in rows):
                self._check_weights(source, key, rows)
        for key, rows in (data.get("appearance") or {}).items():
            self._check_weights(source, f"appearance.{key}", rows if isinstance(rows, list) else [])

        styles = {row.get("id") for row in data.get("texting_styles") or [] if isinstance(row, dict)}
        for style, bank in (data.get("bios") or {}).items():
            if style not in styles:
                add(f"bios.{style}", "is not a declared texting_styles id")
            for text in bank or []:
                unknown = population.template_fields(str(text)) - population.BIO_FIELDS
                if unknown:
                    add(f"bios.{style}", f"{text!r} names {sorted(unknown)}; a template may name only {sorted(population.BIO_FIELDS)}")
        for style, bank in (data.get("like_comments") or {}).items():
            if style not in styles:
                add(f"like_comments.{style}", "is not a declared texting_styles id")
            for text in bank or []:
                unknown = population.template_fields(str(text)) - population.BIO_FIELDS
                if unknown:
                    add(f"like_comments.{style}", f"{text!r} names {sorted(unknown)}; a template may name only {sorted(population.BIO_FIELDS)}")
        for app, bank in (data.get("prompts") or {}).items():
            for row in bank or []:
                if not isinstance(row, dict):
                    add(f"prompts.{app}", f"{row!r}: must be a mapping {{q, a_by_hobby, a_any}}")
                    continue
                answers = [a for rows in (row.get("a_by_hobby") or {}).values() for a in rows] + list(row.get("a_any") or [])
                if not row.get("a_any"):
                    add(f"prompts.{app}", f"{row.get('q')!r}: needs `a_any`, the answer for a person with none of its hobbies")
                for text in answers:
                    unknown = population.template_fields(str(text)) - population.BIO_FIELDS
                    if unknown:
                        add(f"prompts.{app}", f"{text!r} names {sorted(unknown)}")

        for name in data.get("attribute_tables") or []:
            if not data.get(name):
                add("attribute_tables", f"{name}: names no table")

    def _check_weights(self, source: str, key: str, rows: list[Any]) -> None:
        for row in rows:
            if not isinstance(row, dict) or "weight" not in row:
                continue
            weight = row["weight"]
            if isinstance(weight, bool) or not isinstance(weight, (int, float)) or weight <= 0:
                self._add(source, key, f"{row.get('id')}: weight must be a positive number, not {weight!r}")

    def check_endings_and_epilogues(self) -> None:
        """Every declared ending resolves to an epilogue; fail_forward is real."""
        endings_path = self._file("endings")
        if endings_path is None:
            return
        source = self._rel(endings_path)
        doc = _read_yaml(endings_path)
        if not isinstance(doc, dict):
            self._add(source, "-", "endings table is not a YAML mapping")
            return

        # Mirror engine/game/endings.py::declared() exactly: a class that
        # declares a `variants:` block contributes each variant id as an
        # ending; a class that declares none IS the ending, keyed by the class
        # id (dev-story's whole table is this shape, and its endings.yaml
        # documents the contract). A validator stricter than the loader fails
        # content the engine plays happily.
        variants: set[str] = set()
        for class_id, body in (doc.get("classes") or {}).items():
            block = (body or {}).get("variants") or {}
            for ending_id in block or {str(class_id): body}:
                if str(ending_id) in variants:
                    self._add(source, str(ending_id), "duplicate ending id")
                variants.add(str(ending_id))

        fail_forward = str(doc.get("fail_forward") or "").strip()
        if not fail_forward:
            self._add(
                source,
                "fail_forward",
                "no fail_forward declared; a run that earns nothing has no ending",
                severity="warning",
            )
        elif fail_forward not in variants:
            self._add(source, fail_forward, "fail_forward names an undeclared ending")

        epilogues_dir = self._dir("epilogues")
        if epilogues_dir is None:
            self._add(
                source,
                "-",
                "endings are declared but paths.epilogues is not; every finale ends on a blank page",
                severity="warning",
            )
            return
        index_doc = _read_yaml(epilogues_dir / "epilogue_index.yaml") or {}
        cards_doc = _read_yaml(epilogues_dir / "epilogue_cards.yaml") or {}
        index_source = self._rel(epilogues_dir / "epilogue_index.yaml")
        cards_source = self._rel(epilogues_dir / "epilogue_cards.yaml")

        index_ids = {str(row.get("id")) for row in (index_doc.get("endings") or []) if isinstance(row, dict)}
        cards = cards_doc.get("cards") or {}
        card_ids = {str(k) for k in cards}

        prose_source = str(index_doc.get("prose_source") or "").strip()
        if prose_source and not (epilogues_dir / prose_source).is_file():
            self._add(index_source, prose_source, "prose_source file does not exist")

        for missing in sorted(variants - index_ids):
            self._add(index_source, missing, "declared ending has no epilogue index entry")
        for missing in sorted(variants - card_ids):
            self._add(cards_source, missing, "declared ending has no epilogue card")
        for extra in sorted(index_ids - variants):
            self._add(index_source, extra, "epilogue index entry names an undeclared ending")
        for extra in sorted(card_ids - variants):
            self._add(cards_source, extra, "epilogue card names an undeclared ending")

        for ending_id, card in cards.items():
            if not isinstance(card, dict):
                self._add(cards_source, str(ending_id), "epilogue card is not a mapping")
                continue
            for side in ("card_m", "card_g"):
                if not str(card.get(side) or "").strip():
                    self._add(cards_source, str(ending_id), f"epilogue card has no {side} prose")

    # -- the opening's authored choices --------------------------------------

    def check_opening(self) -> None:
        """
        ``entry.opening`` choices that carry ``deed``/``on_pass``/``on_fail``
        (``engine/game/authored_choice.py``): the deed is one the law file
        lists, an ``encounter`` is a declared scene, and every effect is one an
        authored choice may use. Each would otherwise commit, open or apply
        nothing on the player's first move, with nothing said.
        """
        from engine.game.authored_choice import problems

        opening = (self.manifest.entry or {}).get("opening")
        choices = (opening or {}).get("choices") if isinstance(opening, dict) else None
        if not isinstance(choices, list):
            return
        deeds: set[str] = set()
        law_path = self._file("law")
        law_doc = _read_yaml(law_path) if law_path is not None else None
        if isinstance(law_doc, dict) and isinstance(law_doc.get("deeds"), dict):
            deeds = {str(k) for k in law_doc["deeds"]}
        encounters: set[str] = set()
        directory = self._dir("encounters")
        for path in _yaml_files(directory) if directory is not None else []:
            doc = _read_yaml(path)
            for row in (doc or {}).get("encounters") or [] if isinstance(doc, dict) else []:
                if isinstance(row, dict) and row.get("id"):
                    encounters.add(str(row["id"]))
        source = "game.yaml"
        for row in choices:
            if not isinstance(row, dict):
                continue
            for problem in problems(row, deeds=deeds, encounters=encounters,
                                    values=self.declared_values):
                self._add(source, f"entry.opening.{row.get('id') or '?'}", problem)

    # -- law effects in content (v0.17 T4 fix round 1) ----------------------

    def check_law_effects(self) -> None:
        """
        Two effect-row mistakes that load and do nothing, in ANY story file.

        A ``report`` whose ``deed``, ``guise`` or ``jurisdiction`` the law file
        does not declare is refused at runtime (``effects._e_report``) and
        files nothing -- a set-piece's "the Watch writes up the escape", or a
        card's squeezed victim, that never reaches the Watch. A value holding
        ``{`` is an agenda placeholder filled when the move fires, and left to
        the agendas loader. And an effect of an ``effects.ENGINE_ONLY_EFFECTS``
        kind is the engine's own bookkeeping, which a story naming it forges.
        """
        from engine.game.effects import ENGINE_ONLY_EFFECTS

        law_path = self._file("law")
        law_doc = _read_yaml(law_path) if law_path is not None else None
        declared: dict[str, set[str]] = {}
        if isinstance(law_doc, dict):
            for field, key in (("deed", "deeds"), ("guise", "guises"),
                               ("jurisdiction", "jurisdictions")):
                table = law_doc.get(key)
                declared[field] = {str(k) for k in table} if isinstance(table, dict) else set()
        bands: set[str] = set()
        if isinstance(law_doc, dict) and isinstance(law_doc.get("wanted"), dict):
            bands = {str(b) for b in (law_doc["wanted"].get("bands") or [])}
        for path in self._story_yaml_files():
            doc = _read_yaml(path)
            if doc is None:
                continue
            source = self._rel(path)
            is_law_file = law_path is not None and path.resolve() == law_path.resolve()
            for node in walk(doc):
                # A `wanted` CONDITION anywhere (v0.17 `own`): the loader of an
                # agenda gate checks its own, but an ending, a stage or a card
                # had nothing -- `own: "yes"` read as false, a band typo as a
                # gate that never opens. (The law file's own `wanted:` table is
                # not a condition.)
                clause = node.get("wanted")
                if declared and not is_law_file and isinstance(clause, dict) and "min" in clause:
                    self._check_wanted_clause(source, clause, bands, declared)
                # A `committed_deed` condition (v0.17) naming a deed the law
                # file does not list counts nothing, ever.
                if declared and "committed_deed" in node:
                    named = node["committed_deed"]
                    for deed in (named if isinstance(named, list) else [named]):
                        if str(deed or "") not in declared["deed"]:
                            self._add(source, f"committed_deed({deed})",
                                      f"`committed_deed` names deed {deed!r}, which the law "
                                      "file does not declare; the condition is false forever")
                kind = str(node.get("type") or "").strip().lower()
                if kind in ENGINE_ONLY_EFFECTS:
                    self._add(source, kind, f"`{kind}` is the engine's own bookkeeping; "
                                            "no story file may apply it")
                if kind != "report" or not declared:
                    continue
                for field, known in declared.items():
                    value = node.get(field)
                    if isinstance(value, str) and "{" in value:
                        continue
                    if str(value or "") not in known:
                        self._add(source, f"report({field}: {value})",
                                  f"`report` names {field} {value!r}, which the law file "
                                  f"does not declare; it is refused and files nothing")

    def _check_wanted_clause(self, source: str, clause: dict[str, Any], bands: set[str],
                             declared: dict[str, set[str]]) -> None:
        """One ``{wanted: {...}}`` condition: a band, known faces and places,
        and ``own`` a boolean when present."""
        ref = f"wanted({', '.join(f'{k}: {v}' for k, v in clause.items())})"
        if bands and str(clause.get("min") or "") not in bands:
            self._add(source, ref, f"`wanted.min` {clause.get('min')!r} is not a wanted "
                                   "band; the condition is false forever")
        for field in ("guise", "jurisdiction"):
            value = clause.get(field)
            if isinstance(value, str) and "{" in value:
                continue  # an agenda placeholder, the agendas loader's to check
            if value and declared.get(field) and str(value) not in declared[field]:
                self._add(source, ref, f"`wanted.{field}` {value!r} is not declared in "
                                       "the law file; the condition is false forever")
        if "own" in clause and not isinstance(clause["own"], bool):
            self._add(source, ref, "`wanted.own` must be true or false")

    # -- death rules -------------------------------------------------------

    def check_death_rules(self) -> None:
        """
        death.yaml's ``terminal: {when, ending}``: a declared ending, a real
        condition. The same check the loader raises on
        (``encounter.death_terminal_problem``), so doctor finds it before a
        player dies into it.
        """
        from engine.game.encounter import (death_respawn_problem, death_terminal_problem,
                                           declared_ending_ids)

        rules_dir = self._dir("rules")
        if rules_dir is None or not (rules_dir / "death.yaml").is_file():
            return
        path = rules_dir / "death.yaml"
        source = self._rel(path)
        doc = _read_yaml(path)
        if not isinstance(doc, dict):
            self._add(source, "-", "death rules are not a YAML mapping")
            return
        # `respawn.in_custody` (v0.17): `true` or a mapping, never a location.
        problem = death_respawn_problem(doc.get("respawn"))
        if problem:
            self._add(source, "respawn.in_custody", problem)
        terminal = doc.get("terminal")
        if not isinstance(terminal, dict):
            return
        # Mirror engine/game/endings.py::declared(), as check_endings does.
        endings_path = self._file("endings")
        endings_doc = _read_yaml(endings_path) if endings_path is not None else None
        problem = death_terminal_problem(terminal, declared_ending_ids(endings_doc))
        if problem:
            self._add(source, str(terminal.get("ending") or "terminal"), problem)

    # -- set-pieces --------------------------------------------------------

    def check_set_pieces(self) -> None:
        """
        ``paths.challenges`` (v0.17): each set-piece has an id, stands at a
        place the graph holds, gates on a readable ``requires:`` and on flag
        LISTS, grants one flag name, carries a challenge the spec validator
        accepts, applies only effects a set-piece may, and frees the player
        (``release``) only from a challenge's success outcome. The rules live
        in ``set_pieces.set_piece_problems``; the runtime loader keeps what
        this reports, so nothing else says it.
        """
        from engine.challenges.set_pieces import set_piece_effect_types, set_piece_problems

        directory = self._dir("challenges")
        if directory is None:
            return
        locations = {str(k) for k in self.locations} if self.locations else None
        effect_types = set_piece_effect_types(self.declared_values)
        seen: dict[str, str] = {}
        for path in _yaml_files(directory):
            source = self._rel(path)
            doc = _read_yaml(path)
            if not isinstance(doc, dict):
                self._add(source, "-", "set-piece file is not a YAML mapping")
                continue
            pieces = doc.get("set_pieces")
            if pieces is None:
                continue
            if not isinstance(pieces, list):
                self._add(source, "set_pieces", "`set_pieces` is not a list")
                continue
            for index, raw in enumerate(pieces):
                piece_id = str((raw or {}).get("id") or "").strip() if isinstance(raw, dict) else ""
                ref = piece_id or f"set_pieces[{index}]"
                if isinstance(raw, dict) and not piece_id:
                    self._add(source, ref, "set-piece has no id; the loader will skip it")
                if piece_id:
                    if piece_id in seen:
                        self._add(
                            source, ref,
                            f"duplicate set-piece id, already defined in {seen[piece_id]}; "
                            "the loader keeps the first",
                        )
                        continue
                    seen[piece_id] = source
                for problem in set_piece_problems(
                    raw, locations=locations, effect_types=effect_types
                ):
                    self._add(source, ref, problem)

    # -- content the loader would cut short (v0.17 T8 fix round 2) ----------

    def _cuts(self, source: str, ref: str, adjustments: list[str]) -> None:
        """Report every recorded cut: text past its cap, effects past four."""
        from engine.challenges import spec as spec_module

        for note in adjustments:
            if spec_module.TEXT_CUT in note or spec_module.EFFECTS_CUT in note:
                self._add(source, ref, f"{note}: the loader cuts it, silently, at play "
                                       "time -- shorten it or split it")

    def check_truncated_content(self) -> None:
        """
        Authored text or effects the loader would cut off (v0.17 T8 fix round
        2). Every bounder clamps rather than rejects -- right for a model's
        output mid-turn, wrong for a story's own file, where the cut is a line
        whose end (or an effect) simply never plays. Asked of the REAL
        bounders, so the caps cannot drift apart: each deck card
        (``deck.bound_beats`` for its beats; its title and text against the
        deck's own caps), each ending's module beats, each thread template
        and renegotiation (``threads._offer_from_spec``, plus its terms,
        label and broken text), each authored opening choice
        (``authored_choice.bound``) and each set-piece's challenge
        (``spec.validate``). A bounder records a cut in its adjustments
        (``spec.TEXT_CUT`` / ``spec.EFFECTS_CUT``); this reports it.
        """
        from engine.challenges import spec as spec_module
        from engine.content import deck as deck_module
        from engine.game import authored_choice
        from engine.game import threads as threads_module

        def over(source: str, ref: str, what: str, value: Any, limit: int) -> None:
            text = str(value or "").strip()
            if len(text) > limit:
                self._cuts(source, ref, [f"{what} was {len(text)} "
                                         f"{spec_module.TEXT_CUT} {limit}"])

        for path in _yaml_files(self._dir("decks")):
            data = _read_yaml(path)
            if not isinstance(data, dict):
                continue
            source = self._rel(path)
            deck_id = str(data.get("id") or path.stem)
            for card in data.get("cards") or []:
                if not isinstance(card, dict):
                    continue
                card_id = str(card.get("id") or "-")
                over(source, card_id, "card title", card.get("title"), 120)
                over(source, card_id, "card text", card.get("text"), deck_module.MAX_TEXT)
                for beat in deck_module.bound_beats(card.get("beats"), deck_id, card_id):
                    self._cuts(source, f"{card_id}/{beat['id']}", beat.get("adjustments") or [])

        endings_path = self._file("endings")
        doc = _read_yaml(endings_path) if endings_path is not None else None
        if isinstance(doc, dict):
            source = self._rel(endings_path)
            for ending_id, body in (doc.get("classes") or {}).items():
                if not isinstance(body, dict):
                    continue
                for beat in deck_module.bound_beats(body.get("beats"), str(ending_id), "module"):
                    self._cuts(source, f"{ending_id}/{beat['id']}", beat.get("adjustments") or [])

        threads_path = self._file("threads")
        doc = _read_yaml(threads_path) if threads_path is not None else None
        if isinstance(doc, dict):
            source = self._rel(threads_path)
            for template_id, raw in (doc.get("templates") or {}).items():
                if not isinstance(raw, dict):
                    continue
                bodies = [(str(template_id), raw)] + [
                    (f"{template_id}/{vid}", {**raw, **vraw})
                    for vid, vraw in (raw.get("renegotiations") or {}).items()
                    if isinstance(vraw, dict)]
                for ref, body in bodies:
                    adjustments: list[str] = []
                    threads_module._offer_from_spec(
                        str(template_id), body, source="", to_id="", thread_id="",
                        negotiated=[], adjustments=adjustments)
                    self._cuts(source, ref, adjustments)
                    over(source, ref, "terms", body.get("terms"),
                         threads_module.MAX_TERMS_CHARS)
                    over(source, ref, "label", body.get("label"), 120)
                    over(source, ref, "broken text",
                         " ".join(str(body.get("broken_text") or "").split()),
                         threads_module.MAX_TERMS_CHARS)

        opening = (self.manifest.entry or {}).get("opening")
        choices = (opening or {}).get("choices") if isinstance(opening, dict) else None
        for row in choices if isinstance(choices, list) else []:
            if isinstance(row, dict):
                self._cuts("game.yaml", f"entry.opening.{row.get('id') or '?'}",
                           authored_choice.bound(row).get("adjustments") or [])

        directory = self._dir("challenges")
        for path in _yaml_files(directory) if directory is not None else []:
            data = _read_yaml(path)
            pieces = data.get("set_pieces") if isinstance(data, dict) else None
            for raw in pieces if isinstance(pieces, list) else []:
                if isinstance(raw, dict) and isinstance(raw.get("challenge"), dict):
                    result = spec_module.validate(raw["challenge"], authored=True)
                    self._cuts(self._rel(path), str(raw.get("id") or "-"),
                               result.adjustments)

    def check_procgen_templates(self) -> None:
        """
        ``hidden_path_placements`` (v0.14): every pinned ``from`` and
        ``leads_to`` is a place in the story's graph. procgen accepts any
        string there, and a typo would move -- or silently strand -- a secret
        place's only way in, the "loads, validates and does nothing" shape.
        """
        path = self._file("procgen_templates")
        if path is None or not self.locations:
            return
        doc = _read_yaml(path)
        if not isinstance(doc, dict):
            return
        source = self._rel(path)
        for index, row in enumerate(doc.get("hidden_path_placements") or []):
            if not isinstance(row, dict):
                self._add(source, f"placement[{index}]", "a placement must be a mapping")
                continue
            for key in ("from", "leads_to"):
                value = row.get(key)
                if value and str(value) not in self.locations:
                    self._add(source, str(value),
                              f"placement[{index}] `{key}` is not a place in the story's graph")

    # -- agents ------------------------------------------------------------

    def check_agents(self) -> None:
        """
        The story's cast, if it declares one: roles valid, prompt files EXIST,
        reads name knowledge scopes, writes name declared values.

        The prompt-file check is a hard error on purpose. An agent whose
        persona file is missing does not fail -- it silently never plans, and
        the other agent leads every turn by default. That trap shipped once.
        """
        if self.manifest.root is None:
            return
        path = self.manifest.root / "agents.yaml"
        if not path.is_file():
            return
        source = self._rel(path)

        from engine.agents.knowledge import SCOPES
        from engine.agents.roster import RosterError, load_roster

        try:
            roster = load_roster(path, slug=self.manifest.slug)
        except RosterError as exc:
            self._add(source, "-", f"agent roster will not load: {exc}")
            return

        for agent in roster.agents.values():
            if not agent.prompt:
                self._add(
                    source,
                    agent.id,
                    "agent declares no prompt file; it will never plan a turn",
                    severity="warning",
                )
            else:
                prompt_path = self.manifest.root / agent.prompt
                if not prompt_path.is_file():
                    self._add(
                        source,
                        agent.id,
                        f"prompt file does not exist: {agent.prompt} "
                        "(a missing persona silently never plans)",
                    )
            for scope in agent.reads:
                if scope not in SCOPES:
                    self._add(
                        source,
                        agent.id,
                        f"reads unknown knowledge scope {scope!r} (known: {sorted(SCOPES)})",
                    )
            if self.schema_loaded:
                for value in agent.all_writes:
                    if value not in self.declared_values:
                        self._add(
                            source,
                            agent.id,
                            f"writes {value!r}, which state.yaml does not declare",
                        )
            elif agent.all_writes:
                self._add(
                    source,
                    agent.id,
                    "declares writes but the story has no state.yaml; every write "
                    "will be refused",
                )

    # -- spoilers ----------------------------------------------------------

    def check_spoilers(self) -> None:
        """The spoiler table, if the story ships one: rows are usable, and a
        row's ``location:`` is a real place."""
        rules_dir = self._dir("rules")
        if rules_dir is None:
            return
        path = rules_dir / "spoilers.yaml"
        if not path.is_file():
            return
        source = self._rel(path)
        data = _read_yaml(path)
        if not isinstance(data, dict):
            self._add(source, "-", "spoiler table is not a YAML mapping")
            return
        seen: set[str] = set()
        for index, row in enumerate(data.get("spoilers") or []):
            if not isinstance(row, dict):
                self._add(source, f"row[{index}]", "spoiler row is not a mapping")
                continue
            term = str(row.get("term") or "").strip()
            instead = str(row.get("instead") or "").strip()
            if not term or not instead:
                self._add(
                    source,
                    term or f"row[{index}]",
                    "spoiler row needs both term: and instead:; the gate skips it otherwise",
                )
                continue
            if term.lower() in seen:
                self._add(source, term, "duplicate spoiler term", severity="warning")
            seen.add(term.lower())
            # `location:` lifts the row once the player knows that place
            # (interceptors.story_spoiler_terms). `locations.is_known` treats
            # an id the graph does not hold as nobody's secret, so a typo'd
            # id would lift the row on turn one and leak the name it hides.
            location = row.get("location")
            if location is not None and str(location).strip() not in self.locations:
                self._add(
                    source,
                    str(location),
                    f"spoiler row {term!r} names location {location!r}, which is not "
                    "in the story's graph; the row would lift at once and leak its term",
                )

    # -- shared reference scan ---------------------------------------------

    def _check_generic_refs(self, source: str, doc: Any) -> None:
        """Items, locations and factions named anywhere in a document exist."""
        if self.items or self._dir("items") is not None:
            for item_id in sorted(item_refs(doc)):
                if item_id not in self.items:
                    self._add(source, item_id, "item is not in the story's items files")
        if self.locations:
            for loc_id in sorted(location_refs(doc)):
                if loc_id and loc_id not in self.locations:
                    self._add(source, loc_id, "location is not in the story's graph")
        if self.faction_ids or self._file("factions") is not None:
            for faction in sorted(faction_refs(doc)):
                if faction not in self.faction_ids:
                    self._add(source, faction, "faction is not in the story's factions file")


# ---------------------------------------------------------------------------
# Reusable single-block checks. These take explicit data so negative-control
# tests (and authoring tools) can feed them broken inputs without a manifest.
# ---------------------------------------------------------------------------


def check_economy_data(
    source: str,
    data: dict[str, Any],
    *,
    items: dict[str, dict[str, Any]],
    npc_ids: set[str],
) -> list[Issue]:
    """Vendors are real NPCs and stock real items at sane prices."""
    issues: list[Issue] = []
    for vendor_id, vendor in data.items():
        if not isinstance(vendor, dict):
            issues.append(Issue(source, str(vendor_id), "vendor entry is not a mapping"))
            continue
        if str(vendor_id) not in npc_ids:
            issues.append(
                Issue(
                    source,
                    str(vendor_id),
                    "top-level key is not an npc id in the story's npc schedules",
                )
            )
        for side in ("sells", "buys"):
            for item_id, entry in (vendor.get(side) or {}).items():
                if str(item_id) not in items:
                    issues.append(
                        Issue(
                            source,
                            str(item_id),
                            f"{vendor_id}.{side} references an item not in the story's items files",
                        )
                    )
                price = (entry or {}).get("price") if isinstance(entry, dict) else None
                if not isinstance(price, int) or price < 0:
                    issues.append(
                        Issue(
                            source,
                            str(item_id),
                            f"{vendor_id}.{side} price must be a non-negative integer",
                        )
                    )
    return issues


def check_collections_data(
    source: str,
    data: Any,
    *,
    items: dict[str, dict[str, Any]],
    items_source: str = "items",
) -> list[Issue]:
    """
    One collections table against the item registry
    (engine/game/inventory.py::evaluate_collections reads both).

    Four faults, each silent at runtime: a member the registry lacks (the set
    lists a thing nothing can grant, and never completes); a ``counts`` key
    that is not a member (a quantity nobody is asked for); an item whose
    ``collection:`` names no declared set (a "collect" verb for nothing); and a
    member that does not name its own set -- the ``item`` effect settles a set
    only on an item that says it belongs to one, so that piece landing last
    never closes it.
    """
    issues: list[Issue] = []
    rows = (data or {}).get("collections") if isinstance(data, dict) else None
    if data and not isinstance(rows, list):
        issues.append(Issue(source, "-", "`collections` must be a list of sets"))
        rows = []
    declared: set[str] = set()
    for row in rows or []:
        if not isinstance(row, dict) or not str(row.get("id") or "").strip():
            issues.append(Issue(source, "-", "a set needs an `id`"))
            continue
        set_id = str(row["id"])
        if set_id in declared:
            issues.append(Issue(source, set_id, "duplicate set id"))
        declared.add(set_id)
        members = [str(m) for m in (row.get("items") or [])]
        if not members:
            issues.append(Issue(source, set_id, "a set with no `items` can never complete"))
        for member in members:
            spec = items.get(member)
            if spec is None:
                issues.append(Issue(source, member, f"{set_id} names an item not in the story's items files"))
            elif str(spec.get("collection") or "") != set_id:
                issues.append(Issue(
                    source, member,
                    f"member of {set_id} but its item row says collection: "
                    f"{spec.get('collection')!r}, so landing it last never closes {set_id}",
                ))
        counts = row.get("counts") or {}
        if not isinstance(counts, dict):
            issues.append(Issue(source, set_id, "`counts` must map item id -> quantity"))
            counts = {}
        for key, qty in counts.items():
            if str(key) not in members:
                issues.append(Issue(source, set_id, f"counts names {key!r}, which is not a member"))
            if not isinstance(qty, int) or isinstance(qty, bool) or qty < 1:
                issues.append(Issue(source, set_id, f"counts for {key!r} must be a positive integer"))
    for item_id, spec in sorted(items.items()):
        named = str((spec or {}).get("collection") or "")
        if named and named not in declared:
            issues.append(Issue(items_source, item_id, f"collection {named!r} is not a declared set"))
    return issues


def check_recipe_row(
    source: str,
    row: dict[str, Any],
    *,
    items: dict[str, dict[str, Any]],
    locations: set[str],
    skills: frozenset[str],
    bands: frozenset[str],
) -> list[Issue]:
    """One recipe: skill, band, station, and every item id on both sides."""
    issues: list[Issue] = []
    recipe_id = str(row.get("id"))

    skill = str(row.get("skill") or "")
    if skill not in skills:
        issues.append(
            Issue(source, recipe_id, f"unknown skill {skill!r} (known: {sorted(skills)})")
        )
    band = str(row.get("band") or "")
    if band not in bands:
        issues.append(Issue(source, recipe_id, f"unknown difficulty band {band!r}"))
    hours = row.get("hours")
    if not isinstance(hours, (int, float)) or hours < 0:
        issues.append(Issue(source, recipe_id, "hours must be a non-negative number"))

    station = row.get("station")
    if station is not None and str(station) not in locations:
        issues.append(Issue(source, recipe_id, f"station {station!r} is not a location id"))

    inputs = row.get("inputs") or []
    if not inputs:
        issues.append(Issue(source, recipe_id, "recipe consumes nothing"))
    for entry in inputs:
        item_id = str((entry or {}).get("id") or "")
        if item_id not in items:
            issues.append(
                Issue(source, recipe_id, f"input item {item_id!r} is not in the items files")
            )

    for key in ("output", "salvage"):
        block = row.get(key)
        if block is None:
            if key == "output":
                issues.append(Issue(source, recipe_id, "recipe produces nothing"))
            continue
        item_id = str((block or {}).get("id") or "")
        if item_id not in items:
            issues.append(
                Issue(source, recipe_id, f"{key} item {item_id!r} is not in the items files")
            )

    for tool_id in row.get("tools") or []:
        if str(tool_id) not in items:
            issues.append(
                Issue(source, recipe_id, f"tool {tool_id!r} is not in the items files")
            )
    return issues


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------


def validate_story(target: Union[str, GameManifest]) -> list[Issue]:
    """
    Run every applicable check for one story.

    Args:
        target: A slug (resolved through the registry, WITHOUT activating
            anything) or an already-loaded manifest.

    Returns:
        Every finding, errors and warnings together, in check order. A slug
        that names no game returns a single error rather than raising, so a
        caller iterating games can report rather than die.
    """
    if isinstance(target, GameManifest):
        manifest = target
    else:
        from engine.games import registry

        found = registry.get(str(target))
        if found is None:
            return [
                Issue(
                    f"games/{target}",
                    str(target),
                    "no such game: games/<slug>/game.yaml not found or unreadable",
                )
            ]
        manifest = found
    return StoryValidator(manifest).run()


def summarize(issues: Iterable[Issue]) -> tuple[int, int]:
    """(errors, warnings) for a finished run."""
    materialised = list(issues)
    errors = len(errors_only(materialised))
    return errors, len(materialised) - errors


__all__ = [
    "CANON_DICTIONARY_CANDIDATES",
    "DRAFTS_DIRNAME",
    "ENGINE_BANDS",
    "ENGINE_EVIL_PHASES",
    "ENGINE_FLAG_PREFIXES",
    "ENGINE_READ_FLAG_PREFIXES",
    "ENGINE_ITEM_TAGS",
    "ENGINE_SKILLS",
    "Issue",
    "StoryValidator",
    "canon_dictionary_path",
    "canon_flags",
    "canon_location_ids",
    "check_economy_data",
    "check_recipe_row",
    "clock_refs",
    "doom_enabled",
    "engine_owned_flag",
    "errors_only",
    "faction_refs",
    "flags_read",
    "flags_written",
    "item_refs",
    "load_canon_dictionary",
    "load_story_items",
    "load_story_locations",
    "location_refs",
    "story_bands",
    "story_item_tags",
    "story_skills",
    "summarize",
    "validate_story",
    "value_refs",
    "walk",
    "warnings_only",
]
