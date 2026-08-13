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
has one home.

Version: v0.1.0 [2026-08-13]
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator, Optional, Union

import yaml

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

_IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp", ".gif")

#: Relative locations (from the story root) where a canon dictionary may live.
CANON_DICTIONARY_CANDIDATES = (
    "data/canon/state-dictionary.json",
    "canon/state-dictionary.json",
)


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


def _read_yaml(path: Path) -> Any:
    """Parse one YAML file, returning None on any failure (reported upstream)."""
    try:
        with path.open(encoding="utf-8") as fh:
            return yaml.safe_load(fh)
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

    for path in sorted(directory.rglob("*.yaml")):
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
    if directory is None or not directory.is_dir():
        return []
    return sorted(directory.rglob("*.yaml"))


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
        self._build_registries()

        self.check_state_schema()
        self.check_locations()
        self.check_items()
        self.check_art_manifest()
        self.check_economy()
        self.check_recipes()
        self.check_quests()
        self.check_encounters()
        self.check_tables()
        self.check_npc_schedules()
        self.check_rumors()
        self.check_assistant_hints()
        self.check_lore()
        self.check_decks_and_structures()
        self.check_endings_and_epilogues()
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

        for loc_id, spec in self.locations.items():
            spec = spec if isinstance(spec, dict) else {}
            if not str(spec.get("name") or "").strip():
                self._add(source, str(loc_id), "location has no name; the loader will drop it")
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

            self._check_generic_refs(source, data)

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
        for path in _yaml_files(self._dir("decks")):
            data = _read_yaml(path)
            source = self._rel(path)
            if not isinstance(data, dict):
                self._add(source, "-", "deck file is not a YAML mapping")
                continue
            seen_cards: set[str] = set()
            for card in data.get("cards") or []:
                card_id = str((card or {}).get("id") or "")
                if not card_id:
                    self._add(source, "-", "card has no id")
                    continue
                if card_id in seen_cards:
                    self._add(source, card_id, "duplicate card id in this deck")
                seen_cards.add(card_id)

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
                if flag in canon or flag in read or engine_owned_flag(flag):
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

    # -- endings and epilogues ---------------------------------------------

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
        """The spoiler table, if the story ships one: rows are usable."""
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
    "ENGINE_BANDS",
    "ENGINE_EVIL_PHASES",
    "ENGINE_FLAG_PREFIXES",
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
