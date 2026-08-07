"""
Content Integrity Validator
===========================

Cross-check every id reference in the data tree against the thing it names.

THE GAP THIS SCRIPT CLOSES: P9 took the content from roughly two hundred ids
to well over six hundred, spread across locations, items, recipes, quests,
encounters, factions, rumours, lore, art and the economy -- and every one of
those files refers to ids owned by another one. At that volume the dominant
failure is not a bug in a function, it is `wild_mushroom` versus
`wild_mushrooms`: a reference that resolves to nothing, raises nothing, and
produces a shop entry that cannot be bought or an encounter that cannot fire.
Unit tests do not catch that. Only a referential-integrity pass does, and it
is worth more here than any amount of coverage on the loaders.

Every finding names the file and the offending id, because the only useful
form of this failure is one a content author can act on without reading
Python.

Version: v0.1.0 [2026-08-07]

Usage:
    python scripts/validate_content.py
    python scripts/validate_content.py --warnings   # include advisories
"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator, Optional

import yaml

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from engine.game.locations import CANON_IDS, LOCATIONS  # noqa: E402
from engine.skills.builtin.assistant import ASSISTANT_FORMS  # noqa: E402

logger = logging.getLogger(__name__)

# Vocabularies that are structural rather than content. A tag or a difficulty
# band outside these sets is a typo, not a design choice, because the engine
# has no branch for it.
ITEM_TAGS = frozenset(
    {"food", "tool", "charm", "trade", "quest", "light", "apparel", "material"}
)
SKILLS = frozenset(
    {"persuasion", "stealth", "sympathy", "lore", "craft", "survival", "nerve"}
)
BANDS = frozenset({"trivial", "easy", "standard", "hard", "severe", "legendary"})
EVIL_PHASES = frozenset({"dormant", "stirring", "spreading", "consuming"})

ART_ROOT = _ROOT / "content" / "scenes" / "clockwork" / "static" / "art"
_IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp", ".gif")


@dataclass(frozen=True)
class Issue:
    """One integrity finding, phrased for whoever has to fix the file."""

    source: str
    ref_id: str
    message: str
    severity: str = "error"

    def __str__(self) -> str:
        return f"[{self.severity}] {self.source}: {self.ref_id} -- {self.message}"


# ---------------------------------------------------------------------------
# loading helpers
# ---------------------------------------------------------------------------


def _read_yaml(path: Path) -> Any:
    """Parse one YAML file, returning None on any failure (reported upstream)."""
    try:
        with path.open(encoding="utf-8") as fh:
            return yaml.safe_load(fh)
    except (OSError, yaml.YAMLError) as exc:
        logger.error(
            "[validate_content] Unreadable file (operation=_read_yaml, path=%s): %s",
            path,
            exc,
        )
        return None


def _rel(path: Path) -> str:
    """Repo-relative path string, for messages a human can paste into an editor."""
    try:
        return str(path.relative_to(_ROOT)).replace("\\", "/")
    except ValueError:
        return str(path)


def _walk(node: Any) -> Iterator[Any]:
    """Yield every dict nested anywhere inside a parsed YAML document."""
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk(value)


def _yaml_files(*relative: str) -> list[Path]:
    """Every ``*.yaml`` under the given repo-relative directories, sorted."""
    out: list[Path] = []
    for rel in relative:
        directory = _ROOT / rel
        if directory.is_dir():
            out.extend(sorted(directory.rglob("*.yaml")))
    return out


# ---------------------------------------------------------------------------
# registries
# ---------------------------------------------------------------------------


def load_items() -> tuple[dict[str, dict[str, Any]], list[Issue]]:
    """
    Build the item registry from data/items/*.yaml.

    Returns:
        (registry keyed by item id, issues found while building it).
    """
    issues: list[Issue] = []
    registry: dict[str, dict[str, Any]] = {}
    origin: dict[str, str] = {}

    for path in _yaml_files("data/items"):
        data = _read_yaml(path)
        if not isinstance(data, dict):
            issues.append(Issue(_rel(path), "-", "file is not a YAML mapping"))
            continue
        for row in data.get("items") or []:
            if not isinstance(row, dict):
                issues.append(Issue(_rel(path), "-", "item entry is not a mapping"))
                continue
            item_id = str(row.get("id") or "").strip()
            if not item_id:
                issues.append(Issue(_rel(path), "-", "item entry has no id"))
                continue
            if item_id in registry:
                issues.append(
                    Issue(
                        _rel(path),
                        item_id,
                        f"duplicate item id, already defined in {origin[item_id]}",
                    )
                )
                continue
            registry[item_id] = row
            origin[item_id] = _rel(path)
    return registry, issues


def load_npc_ids() -> set[str]:
    """Every NPC id declared in data/world/npc_schedules.yaml."""
    data = _read_yaml(_ROOT / "data/world/npc_schedules.yaml") or {}
    return {str(k) for k in (data.get("npcs") or {})}


def load_faction_ids() -> set[str]:
    """Every faction id declared in data/world/factions.yaml."""
    data = _read_yaml(_ROOT / "data/world/factions.yaml") or {}
    return {str(k) for k in (data.get("factions") or {})}


def load_arc_ids() -> set[str]:
    """Every arc id declared in data/quests/arcs.yaml."""
    data = _read_yaml(_ROOT / "data/quests/arcs.yaml") or {}
    return {str(k) for k in (data.get("arcs") or {})}


def load_recipes() -> tuple[list[tuple[str, dict[str, Any]]], list[Issue]]:
    """Every recipe as (source file, definition), plus duplicate-id findings."""
    issues: list[Issue] = []
    rows: list[tuple[str, dict[str, Any]]] = []
    seen: dict[str, str] = {}

    for path in _yaml_files("data/recipes"):
        data = _read_yaml(path)
        if not isinstance(data, dict):
            issues.append(Issue(_rel(path), "-", "file is not a YAML mapping"))
            continue
        for row in data.get("recipes") or []:
            if not isinstance(row, dict):
                issues.append(Issue(_rel(path), "-", "recipe entry is not a mapping"))
                continue
            recipe_id = str(row.get("id") or "").strip()
            if not recipe_id:
                issues.append(Issue(_rel(path), "-", "recipe entry has no id"))
                continue
            if recipe_id in seen:
                issues.append(
                    Issue(
                        _rel(path),
                        recipe_id,
                        f"duplicate recipe id, already defined in {seen[recipe_id]}",
                    )
                )
                continue
            seen[recipe_id] = _rel(path)
            rows.append((_rel(path), row))
    return rows, issues


# ---------------------------------------------------------------------------
# checks
# ---------------------------------------------------------------------------


def check_locations() -> list[Issue]:
    """Graph shape: canon ids present, edges resolve, edges symmetric, all reachable."""
    issues: list[Issue] = []
    source = "data/world/locations.yaml"

    for canon in CANON_IDS:
        if canon not in LOCATIONS:
            issues.append(Issue(source, canon, "canon location id is missing"))

    for loc_id, spec in LOCATIONS.items():
        for dst, edge in (spec.get("connections") or {}).items():
            if dst not in LOCATIONS:
                issues.append(
                    Issue(source, f"{loc_id}>{dst}", "edge target does not exist")
                )
                continue
            if edge.get("one_way"):
                continue
            if loc_id not in (LOCATIONS[dst].get("connections") or {}):
                issues.append(
                    Issue(
                        source,
                        f"{loc_id}>{dst}",
                        "edge is not bidirectional and is not marked one_way",
                    )
                )
        if "ring" not in spec:
            issues.append(Issue(source, loc_id, "no ring assigned"))

    # A place nobody can walk to is content that will never be seen. The start
    # location is fixed at forest_clearing (data/rules/death.yaml respawns
    # there too), so reachability is measured from it.
    reachable: set[str] = set()
    frontier = ["forest_clearing"] if "forest_clearing" in LOCATIONS else []
    while frontier:
        current = frontier.pop()
        if current in reachable:
            continue
        reachable.add(current)
        frontier.extend((LOCATIONS[current].get("connections") or {}).keys())
    for orphan in sorted(set(LOCATIONS) - reachable):
        issues.append(
            Issue(source, orphan, "unreachable from forest_clearing by any path")
        )
    return issues


def check_items(items: dict[str, dict[str, Any]], art: dict[str, Any]) -> list[Issue]:
    """Item field shape and art-key resolution."""
    issues: list[Issue] = []
    source = "data/items/*.yaml"
    art_items = (art.get("items") or {}) if isinstance(art, dict) else {}

    for item_id, row in sorted(items.items()):
        if not str(row.get("name") or "").strip():
            issues.append(Issue(source, item_id, "item has no name"))
        if not str(row.get("description") or "").strip():
            issues.append(Issue(source, item_id, "item has no description"))
        tags = {str(t) for t in (row.get("tags") or [])}
        if not tags:
            issues.append(Issue(source, item_id, "item has no tags"))
        for tag in sorted(tags - ITEM_TAGS):
            issues.append(
                Issue(source, item_id, f"unknown tag {tag!r} (known: {sorted(ITEM_TAGS)})")
            )
        for numeric in ("weight", "value"):
            value = row.get(numeric)
            if not isinstance(value, (int, float)) or value < 0:
                issues.append(
                    Issue(source, item_id, f"{numeric} must be a non-negative number")
                )
        art_key = row.get("art")
        if art_key is not None and str(art_key) not in art_items:
            issues.append(
                Issue(
                    source,
                    item_id,
                    f"art key {art_key!r} is not in data/art/manifest.yaml items:",
                )
            )
    return issues


def check_art_manifest() -> list[Issue]:
    """Every path in the manifest resolves to a shipped file; keys name real things."""
    issues: list[Issue] = []
    path = _ROOT / "data/art/manifest.yaml"
    source = _rel(path)
    data = _read_yaml(path)
    if not isinstance(data, dict):
        return [Issue(source, "-", "manifest is not a YAML mapping")]

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
        if not (ART_ROOT / rel_path).exists():
            issues.append(
                Issue(source, key, f"art file does not exist: {rel_path}")
            )

    for loc_key in (data.get("locations") or {}):
        if str(loc_key) not in LOCATIONS:
            issues.append(
                Issue(source, str(loc_key), "locations: key is not a location id")
            )

    npc_ids = load_npc_ids()
    for portrait_key in (data.get("portraits") or {}):
        if str(portrait_key) not in npc_ids:
            issues.append(
                Issue(source, str(portrait_key), "portraits: key is not a known npc id")
            )

    forms = set(data.get("assistant_forms") or {})
    missing_forms = set(ASSISTANT_FORMS) - forms
    for form in sorted(missing_forms):
        issues.append(
            Issue(source, form, "assistant form has no art entry", severity="warning")
        )
    for form in sorted(forms - set(ASSISTANT_FORMS)):
        issues.append(Issue(source, form, "assistant_forms: key is not a known form"))
    return issues


def check_economy(items: dict[str, dict[str, Any]], npc_ids: set[str]) -> list[Issue]:
    """Vendors are real NPCs and stock real items at sane prices."""
    issues: list[Issue] = []
    path = _ROOT / "data/economy.yaml"
    source = _rel(path)
    data = _read_yaml(path)
    if not isinstance(data, dict):
        return [Issue(source, "-", "economy is not a YAML mapping")]

    for vendor_id, vendor in data.items():
        if not isinstance(vendor, dict):
            issues.append(Issue(source, str(vendor_id), "vendor entry is not a mapping"))
            continue
        if str(vendor_id) not in npc_ids:
            issues.append(
                Issue(
                    source,
                    str(vendor_id),
                    "top-level key is not an npc id in data/world/npc_schedules.yaml",
                )
            )
        for side in ("sells", "buys"):
            for item_id, entry in (vendor.get(side) or {}).items():
                if str(item_id) not in items:
                    issues.append(
                        Issue(
                            source,
                            str(item_id),
                            f"{vendor_id}.{side} references an item not in data/items/",
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


def check_recipes(items: dict[str, dict[str, Any]]) -> list[Issue]:
    """Recipe skills, bands, stations and every item id on both sides."""
    issues: list[Issue] = []
    rows, issues_loading = load_recipes()
    issues.extend(issues_loading)

    for source, row in rows:
        recipe_id = str(row.get("id"))
        skill = str(row.get("skill") or "")
        if skill not in SKILLS:
            issues.append(
                Issue(source, recipe_id, f"unknown skill {skill!r} (known: {sorted(SKILLS)})")
            )
        band = str(row.get("band") or "")
        if band not in BANDS:
            issues.append(
                Issue(source, recipe_id, f"unknown difficulty band {band!r}")
            )
        hours = row.get("hours")
        if not isinstance(hours, (int, float)) or hours < 0:
            issues.append(Issue(source, recipe_id, "hours must be a non-negative number"))

        station = row.get("station")
        if station is not None and str(station) not in LOCATIONS:
            issues.append(
                Issue(source, recipe_id, f"station {station!r} is not a location id")
            )

        inputs = row.get("inputs") or []
        if not inputs:
            issues.append(Issue(source, recipe_id, "recipe consumes nothing"))
        for entry in inputs:
            item_id = str((entry or {}).get("id") or "")
            if item_id not in items:
                issues.append(
                    Issue(source, recipe_id, f"input item {item_id!r} is not in data/items/")
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
                    Issue(source, recipe_id, f"{key} item {item_id!r} is not in data/items/")
                )

        for tool_id in row.get("tools") or []:
            if str(tool_id) not in items:
                issues.append(
                    Issue(source, recipe_id, f"tool {tool_id!r} is not in data/items/")
                )
    return issues


def _referenced_ids(
    paths: Iterable[Path],
) -> tuple[dict[str, set[str]], dict[str, set[str]], dict[str, set[str]]]:
    """
    Harvest item, location and faction references out of arbitrary content YAML.

    Content files use several spellings for the same reference -- ``item_id``
    in an effect, ``requires_item`` in an approach gate, ``{id: ...}`` under a
    ``has_item`` predicate -- so the scan is by key name across every nested
    mapping rather than by schema. A new spelling silently escapes this, which
    is why the key list is kept short and shared.

    Returns:
        Three mappings of repo-relative file to the ids it names.
    """
    items: dict[str, set[str]] = {}
    locations: dict[str, set[str]] = {}
    factions: dict[str, set[str]] = {}

    item_keys = ("item_id", "requires_item")
    item_block_keys = ("has_item", "not_has_item", "item")
    location_keys = ("at_location", "visited", "location", "location_id")
    list_location_keys = ("to", "from")

    for path in paths:
        data = _read_yaml(path)
        if data is None:
            continue
        key = _rel(path)
        for node in _walk(data):
            for name in item_keys:
                if isinstance(node.get(name), str):
                    items.setdefault(key, set()).add(node[name])
            for name in item_block_keys:
                block = node.get(name)
                if isinstance(block, dict) and isinstance(block.get("id"), str):
                    items.setdefault(key, set()).add(block["id"])
            for name in location_keys:
                if isinstance(node.get(name), str):
                    locations.setdefault(key, set()).add(node[name])
            if isinstance(node.get("faction"), str):
                factions.setdefault(key, set()).add(node["faction"])
            triggers = node.get("triggers")
            if isinstance(triggers, dict):
                for name in list_location_keys:
                    for value in triggers.get(name) or []:
                        locations.setdefault(key, set()).add(str(value))
                for edge in triggers.get("edges") or []:
                    src, _, dst = str(edge).partition(">")
                    locations.setdefault(key, set()).update({src, dst})
    return items, locations, factions


def check_quests(
    items: dict[str, dict[str, Any]],
    faction_ids: set[str],
) -> list[Issue]:
    """Quest arcs, locations, items, factions -- and that every arc is real."""
    issues: list[Issue] = []
    arc_ids = load_arc_ids()
    quest_paths = [p for p in _yaml_files("data/quests") if p.name != "arcs.yaml"]

    for path in quest_paths:
        data = _read_yaml(path)
        source = _rel(path)
        if not isinstance(data, dict):
            issues.append(Issue(source, "-", "quest file is not a YAML mapping"))
            continue
        quest_id = str(data.get("id") or "")
        if not quest_id:
            issues.append(Issue(source, "-", "quest has no id"))
        arc = str(data.get("arc") or "")
        # A quest on an arc that does not exist can never become active: the
        # arc gate in data/quests/arcs.yaml is what makes it reachable at all.
        if arc not in arc_ids:
            issues.append(
                Issue(source, quest_id or "-", f"arc {arc!r} is not in data/quests/arcs.yaml")
            )
        if not data.get("stages"):
            issues.append(Issue(source, quest_id or "-", "quest has no stages"))

    ref_items, ref_locations, ref_factions = _referenced_ids(quest_paths)
    for source, ids in sorted(ref_items.items()):
        for item_id in sorted(ids):
            if item_id not in items:
                issues.append(Issue(source, item_id, "item is not in data/items/"))
    for source, ids in sorted(ref_locations.items()):
        for loc_id in sorted(ids):
            if loc_id not in LOCATIONS:
                issues.append(
                    Issue(source, loc_id, "location is not in data/world/locations.yaml")
                )
    for source, ids in sorted(ref_factions.items()):
        for faction in sorted(ids):
            if faction not in faction_ids:
                issues.append(
                    Issue(source, faction, "faction is not in data/world/factions.yaml")
                )
    return issues


def check_encounters(
    items: dict[str, dict[str, Any]],
    faction_ids: set[str],
) -> list[Issue]:
    """Encounter edges resolve in the graph, and referenced ids exist."""
    issues: list[Issue] = []
    paths = _yaml_files("data/encounters")
    ref_items, ref_locations, ref_factions = _referenced_ids(paths)

    for source, ids in sorted(ref_locations.items()):
        for loc_id in sorted(ids):
            if loc_id and loc_id not in LOCATIONS:
                issues.append(
                    Issue(source, loc_id, "location is not in data/world/locations.yaml")
                )
    for source, ids in sorted(ref_items.items()):
        for item_id in sorted(ids):
            if item_id not in items:
                issues.append(Issue(source, item_id, "item is not in data/items/"))
    for source, ids in sorted(ref_factions.items()):
        for faction in sorted(ids):
            if faction not in faction_ids:
                issues.append(
                    Issue(source, faction, "faction is not in data/world/factions.yaml")
                )

    # The edge itself, not just its endpoints: an encounter keyed to a leg
    # that does not exist can never fire, and nothing at runtime says so.
    for path in paths:
        data = _read_yaml(path)
        if not isinstance(data, dict):
            continue
        source = _rel(path)
        for row in data.get("encounters") or []:
            triggers = (row or {}).get("triggers") or {}
            for edge in triggers.get("edges") or []:
                src, _, dst = str(edge).partition(">")
                if dst not in (LOCATIONS.get(src, {}).get("connections") or {}):
                    issues.append(
                        Issue(source, str(row.get("id")), f"dead edge {edge}")
                    )
    return issues


def check_npc_schedules() -> list[Issue]:
    """NPC homes and routine slots point at places that exist."""
    issues: list[Issue] = []
    path = _ROOT / "data/world/npc_schedules.yaml"
    source = _rel(path)
    data = _read_yaml(path) or {}
    for npc_id, cfg in (data.get("npcs") or {}).items():
        home = str((cfg or {}).get("home") or "")
        if home and home not in LOCATIONS:
            issues.append(Issue(source, str(npc_id), f"home {home!r} is not a location"))
        for slot in (cfg or {}).get("routine") or []:
            loc = str((slot or {}).get("location") or "")
            if loc and loc not in LOCATIONS:
                issues.append(
                    Issue(source, str(npc_id), f"routine location {loc!r} is not a location")
                )
    return issues


def check_rumors(npc_ids: set[str]) -> list[Issue]:
    """Rumour tiers, awareness gates, phases and speakers."""
    issues: list[Issue] = []
    path = _ROOT / "data/world/rumors.yaml"
    source = _rel(path)
    data = _read_yaml(path) or {}
    seen: set[str] = set()

    for row in data.get("rumors") or []:
        if not isinstance(row, dict):
            issues.append(Issue(source, "-", "rumour entry is not a mapping"))
            continue
        rumor_id = str(row.get("id") or "")
        if not rumor_id:
            issues.append(Issue(source, "-", "rumour has no id"))
            continue
        if rumor_id in seen:
            issues.append(Issue(source, rumor_id, "duplicate rumour id"))
        seen.add(rumor_id)
        if not str(row.get("text") or "").strip():
            issues.append(Issue(source, rumor_id, "rumour has no text"))
        tier = row.get("tier")
        if tier not in (1, 2, 3):
            issues.append(Issue(source, rumor_id, f"tier must be 1-3, got {tier!r}"))
        awareness = row.get("min_awareness")
        if not isinstance(awareness, (int, float)) or not 0 <= awareness <= 100:
            issues.append(
                Issue(source, rumor_id, f"min_awareness must be 0-100, got {awareness!r}")
            )
        speaker = row.get("source_npc")
        if speaker is not None and str(speaker) not in npc_ids:
            issues.append(Issue(source, rumor_id, f"source_npc {speaker!r} is not a known npc"))
        for phase in row.get("requires_phase") or []:
            if str(phase) not in EVIL_PHASES:
                issues.append(Issue(source, rumor_id, f"unknown evil phase {phase!r}"))
    return issues


def check_assistant_hints() -> list[Issue]:
    """Hint tiers and lore snippet gates."""
    issues: list[Issue] = []
    path = _ROOT / "data/assistant/hints.yaml"
    source = _rel(path)
    data = _read_yaml(path)
    if not isinstance(data, dict):
        return [Issue(source, "-", "hints file is not a YAML mapping")]

    tiers_seen: set[int] = set()
    for index, row in enumerate(data.get("hints") or []):
        label = str((row or {}).get("text") or f"hint[{index}]")[:40]
        tier = (row or {}).get("tier")
        if tier not in (0, 1, 2, 3):
            issues.append(Issue(source, label, f"tier must be 0-3, got {tier!r}"))
        else:
            tiers_seen.add(int(tier))
        if not str((row or {}).get("text") or "").strip():
            issues.append(Issue(source, label, "hint has no text"))
    for tier in (0, 1, 2, 3):
        if tier not in tiers_seen:
            issues.append(Issue(source, f"tier {tier}", "no hints at this tier"))

    for topic, row in (data.get("lore_snippets") or {}).items():
        if not isinstance(row, dict):
            issues.append(Issue(source, str(topic), "lore snippet is not a mapping"))
            continue
        if not str(row.get("text") or "").strip():
            issues.append(Issue(source, str(topic), "lore snippet has no text"))
        min_tier = row.get("min_tier")
        if min_tier not in (1, 2, 3):
            issues.append(
                Issue(source, str(topic), f"min_tier must be 1-3, got {min_tier!r}")
            )
    return issues


def check_lore() -> list[Issue]:
    """
    Lore markdown chunks the way engine/lore/manager.py will chunk it.

    A section whose body is under forty characters is silently dropped at
    ingest, so a file of short stubs looks fine on disk and contributes
    nothing to retrieval.
    """
    issues: list[Issue] = []
    lore_dir = _ROOT / "data/lore"
    for path in sorted(lore_dir.glob("*.md")):
        source = _rel(path)
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            issues.append(Issue(source, "-", f"unreadable: {exc}"))
            continue
        sections = [s for s in text.split("\n## ")[1:]]
        if not sections:
            issues.append(Issue(source, "-", "no '##' sections; nothing will be ingested"))
            continue
        for section in sections:
            title, _, body = section.partition("\n")
            if len(body.strip()) < 40:
                issues.append(
                    Issue(
                        source,
                        title.strip(),
                        "section body under 40 chars; the lore ingest will drop it",
                    )
                )
    return issues


# ---------------------------------------------------------------------------
# entry points
# ---------------------------------------------------------------------------


def validate() -> list[Issue]:
    """
    Run every cross-reference check.

    Returns:
        Every finding, errors and warnings together, in check order.
    """
    items, issues = load_items()
    npc_ids = load_npc_ids()
    faction_ids = load_faction_ids()
    art = _read_yaml(_ROOT / "data/art/manifest.yaml") or {}

    issues.extend(check_locations())
    issues.extend(check_items(items, art))
    issues.extend(check_art_manifest())
    issues.extend(check_economy(items, npc_ids))
    issues.extend(check_recipes(items))
    issues.extend(check_quests(items, faction_ids))
    issues.extend(check_encounters(items, faction_ids))
    issues.extend(check_npc_schedules())
    issues.extend(check_rumors(npc_ids))
    issues.extend(check_assistant_hints())
    issues.extend(check_lore())

    errors = [i for i in issues if i.severity == "error"]
    logger.info(
        "[validate_content] Validation complete "
        "(operation=validate, items=%d, locations=%d, errors=%d, warnings=%d)",
        len(items),
        len(LOCATIONS),
        len(errors),
        len(issues) - len(errors),
    )
    return issues


def errors_only(issues: Optional[list[Issue]] = None) -> list[Issue]:
    """Just the findings that should fail a build."""
    return [i for i in (issues if issues is not None else validate()) if i.severity == "error"]


def main(argv: Optional[list[str]] = None) -> int:
    """CLI entry point. Exit 0 when there are no errors."""
    parser = argparse.ArgumentParser(description="Validate cross-file content integrity")
    parser.add_argument(
        "--warnings",
        action="store_true",
        help="Print advisory findings as well as errors",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    issues = validate()
    errors = [i for i in issues if i.severity == "error"]
    warnings = [i for i in issues if i.severity != "error"]

    for issue in errors:
        print(issue)
    if args.warnings:
        for issue in warnings:
            print(issue)

    print(
        f"[validate_content] {len(errors)} error(s), {len(warnings)} warning(s) "
        f"across {len(LOCATIONS)} locations."
    )
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
