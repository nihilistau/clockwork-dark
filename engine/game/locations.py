"""
Location Graph
==============

Travel edges, evil multipliers, awareness deltas -- loaded and validated from
``data/world/locations.yaml``.

THE GAP THIS MODULE CLOSES: the graph used to be a literal Python dict of five
places. It was the last world noun not expressed as content, which meant the
map could not be edited by anything but a Python programmer, and it meant the
ids ``engine/game/procgen.py`` generates content for -- ``deeper_forest``,
``old_barrows``, ``herb_glen`` -- were not in the graph at all, so ``move_to``
rejected them and every forage node, hidden path and barrow the generator has
ever produced was unreachable. The graph now comes from YAML, the generator's
targets are in it, and the file is checked on load.

WHY VALIDATE ON LOAD RATHER THAN TRUST THE FILE: a location graph fails
silently. A typo in an edge target does not raise; it produces a place you can
walk into and never leave, and nobody notices until a playtest. So the loader
checks every edge target, every numeric range, and edge symmetry, and it
*repairs or drops* rather than raising -- a malformed entry must never take a
running session down mid-turn.

Every public name predates this rewrite and keeps its signature:
``LOCATIONS``, ``CANONICAL_LOCATION_IDS``, ``get_location``, ``get_edge``,
``can_travel``, ``evil_multiplier_for``.

Note on ``CANONICAL_LOCATION_IDS``: it is the five ids pinned by CLAUDE.md
("Canon IDs -- do not rename"), NOT the whole graph. Use ``LOCATION_IDS`` for
"every place that exists".

Version: v0.2.0 [2026-08-07]
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

import yaml

from engine.config import get_config

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parents[2]

# The five ids CLAUDE.md pins as canon. Renaming any of these invalidates
# data/quests/**, data/encounters/**, data/world/npc_schedules.yaml and every
# save file ever written.
CANON_IDS: tuple[str, ...] = (
    "forest_clearing",
    "edgewood_square",
    "edgewood_bakery",
    "tinker_caravan",
    "millhaven_gate",
)

CANONICAL_LOCATION_IDS = frozenset(CANON_IDS)

# Validation bounds. Deliberately generous -- these catch a transposed digit or
# a missing key, not a designer's judgement about how bad a road is.
_RING_RANGE = (0, 4)
_EVIL_MULTIPLIER_RANGE = (0.1, 3.0)
_HOURS_RANGE = (0, 48)
_DANGER_DC_RANGE = (0, 30)
_AWARENESS_DELTA_RANGE = (-10, 10)

_EDGE_DEFAULTS: dict[str, int] = {"hours": 1, "danger_dc": 0, "awareness_delta": 0}


def _locations_path() -> Path:
    """Path to the graph file, overridable via ``paths.locations``."""
    rel = get_config().get("paths.locations", "data/world/locations.yaml")
    return _ROOT / str(rel)


def _in_range(value: float, bounds: tuple[float, float]) -> bool:
    return bounds[0] <= value <= bounds[1]


def _clean_edge(
    src: str, dst: str, raw: Any, known_ids: set[str]
) -> Optional[dict[str, Any]]:
    """
    Validate one outbound edge.

    Args:
        src: Origin location id, for logging.
        dst: Destination location id.
        raw: The edge mapping as written in YAML.
        known_ids: Every location id declared in the file.

    Returns:
        A normalised edge dict, or None if the edge must be dropped.
    """
    if dst not in known_ids:
        logger.error(
            "[locations] Edge target does not exist, dropping edge "
            "(operation=_clean_edge, src=%s, dst=%s)",
            src,
            dst,
        )
        return None
    if not isinstance(raw, dict):
        logger.error(
            "[locations] Edge is not a mapping, dropping edge "
            "(operation=_clean_edge, edge=%s>%s)",
            src,
            dst,
        )
        return None

    edge: dict[str, Any] = dict(raw)
    for key, fallback in _EDGE_DEFAULTS.items():
        try:
            edge[key] = int(edge.get(key, fallback))
        except (TypeError, ValueError):
            logger.error(
                "[locations] Non-numeric %s, using default "
                "(operation=_clean_edge, edge=%s>%s, value=%s)",
                key,
                src,
                dst,
                edge.get(key),
            )
            edge[key] = fallback

    for key, bounds in (
        ("hours", _HOURS_RANGE),
        ("danger_dc", _DANGER_DC_RANGE),
        ("awareness_delta", _AWARENESS_DELTA_RANGE),
    ):
        if not _in_range(edge[key], bounds):
            logger.error(
                "[locations] %s out of range, clamping "
                "(operation=_clean_edge, edge=%s>%s, value=%s)",
                key,
                src,
                dst,
                edge[key],
            )
            edge[key] = int(max(bounds[0], min(bounds[1], edge[key])))

    edge["one_way"] = bool(edge.get("one_way", False))
    return edge


def _clean_location(loc_id: str, raw: Any) -> Optional[dict[str, Any]]:
    """
    Validate one location entry, ignoring its edges.

    Returns:
        A normalised location dict without ``connections``, or None if the
        entry is unusable and must be skipped.
    """
    if not isinstance(raw, dict):
        logger.error(
            "[locations] Entry is not a mapping, skipping "
            "(operation=_clean_location, id=%s)",
            loc_id,
        )
        return None

    name = str(raw.get("name") or "").strip()
    if not name:
        logger.error(
            "[locations] Entry has no name, skipping "
            "(operation=_clean_location, id=%s)",
            loc_id,
        )
        return None

    try:
        ring = int(raw.get("ring"))
    except (TypeError, ValueError):
        logger.error(
            "[locations] Missing or non-numeric ring, skipping "
            "(operation=_clean_location, id=%s)",
            loc_id,
        )
        return None
    if not _in_range(ring, _RING_RANGE):
        logger.error(
            "[locations] Ring out of range, skipping "
            "(operation=_clean_location, id=%s, ring=%s)",
            loc_id,
            ring,
        )
        return None

    try:
        multiplier = float(raw.get("evil_multiplier", 1.0))
    except (TypeError, ValueError):
        multiplier = 1.0
    if not _in_range(multiplier, _EVIL_MULTIPLIER_RANGE):
        logger.error(
            "[locations] evil_multiplier out of range, clamping "
            "(operation=_clean_location, id=%s, value=%s)",
            loc_id,
            multiplier,
        )
        multiplier = max(
            _EVIL_MULTIPLIER_RANGE[0], min(_EVIL_MULTIPLIER_RANGE[1], multiplier)
        )

    cleaned = dict(raw)
    cleaned["name"] = name
    cleaned["ring"] = ring
    cleaned["evil_multiplier"] = multiplier
    cleaned["tags"] = [str(t) for t in (raw.get("tags") or [])]
    cleaned["connections"] = {}
    return cleaned


def _mirror_missing_returns(graph: dict[str, dict[str, Any]]) -> None:
    """
    Enforce bidirectionality.

    A one-directional edge is almost always a typo, and the failure mode is a
    room the player walks into and cannot leave. Rather than drop the forward
    edge (losing authored content) the return leg is synthesised with the same
    travel cost and no awareness gain, and the omission is logged so it gets
    written properly in the file.
    """
    for src, spec in graph.items():
        for dst, edge in list(spec["connections"].items()):
            if edge.get("one_way"):
                continue
            if src in graph[dst]["connections"]:
                continue
            logger.warning(
                "[locations] Missing return edge, mirroring "
                "(operation=_mirror_missing_returns, edge=%s>%s)",
                src,
                dst,
            )
            graph[dst]["connections"][src] = {
                "hours": edge["hours"],
                "danger_dc": edge["danger_dc"],
                "awareness_delta": 0,
                "one_way": False,
                "mirrored": True,
            }


def load_locations(path: Optional[Path] = None) -> dict[str, dict[str, Any]]:
    """
    Read and validate the location graph.

    Args:
        path: Optional override for the YAML file, used by tests and tools.

    Returns:
        Mapping of location id to validated location spec. Empty only if the
        file is missing or unreadable, which is logged rather than raised --
        an unreadable map must not abort a turn mid-travel.
    """
    source = path or _locations_path()
    try:
        with source.open(encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
    except (OSError, yaml.YAMLError) as exc:
        logger.error(
            "[locations] Unreadable location graph "
            "(operation=load_locations, path=%s): %s",
            source,
            exc,
        )
        return {}

    raw_locations = data.get("locations")
    if not isinstance(raw_locations, dict):
        logger.error(
            "[locations] No `locations` mapping in file "
            "(operation=load_locations, path=%s)",
            source,
        )
        return {}

    # Pass 1: entries. Edges are resolved afterwards so that a forward
    # reference to a place defined later in the file is legal.
    graph: dict[str, dict[str, Any]] = {}
    for loc_id, raw in raw_locations.items():
        cleaned = _clean_location(str(loc_id), raw)
        if cleaned is not None:
            graph[str(loc_id)] = cleaned

    # Pass 2: edges, now that the full id set is known.
    known_ids = set(graph)
    for loc_id, raw in raw_locations.items():
        if str(loc_id) not in graph:
            continue
        connections = (raw or {}).get("connections") or {}
        if not isinstance(connections, dict):
            logger.error(
                "[locations] `connections` is not a mapping, treating as empty "
                "(operation=load_locations, id=%s)",
                loc_id,
            )
            continue
        for dst, edge_raw in connections.items():
            edge = _clean_edge(str(loc_id), str(dst), edge_raw, known_ids)
            if edge is not None:
                graph[str(loc_id)]["connections"][str(dst)] = edge

    _mirror_missing_returns(graph)

    missing_canon = [cid for cid in CANON_IDS if cid not in graph]
    if missing_canon:
        logger.error(
            "[locations] Canon ids absent from the graph "
            "(operation=load_locations, missing=%s)",
            missing_canon,
        )

    edge_count = sum(len(s["connections"]) for s in graph.values())
    logger.info(
        "[locations] Loaded location graph "
        "(operation=load_locations, places=%s, edges=%d)",
        len(graph),
        edge_count,
    )
    return graph


LOCATIONS: dict[str, dict[str, Any]] = load_locations()

# Every place that exists, as opposed to the five canon ids above.
LOCATION_IDS = frozenset(LOCATIONS)


def reload_locations(path: Optional[Path] = None) -> dict[str, dict[str, Any]]:
    """
    Re-read the graph in place, keeping the module-level ``LOCATIONS`` object.

    Mutating the existing dict rather than rebinding it matters: several
    modules do ``from engine.game.locations import LOCATIONS`` at import time
    and would otherwise keep a stale reference forever.

    Args:
        path: Optional override for the YAML file.

    Returns:
        The refreshed ``LOCATIONS`` mapping.
    """
    global LOCATION_IDS
    fresh = load_locations(path)
    LOCATIONS.clear()
    LOCATIONS.update(fresh)
    LOCATION_IDS = frozenset(LOCATIONS)
    return LOCATIONS


def get_location(location_id: str) -> Optional[dict[str, Any]]:
    """Return location metadata or None."""
    return LOCATIONS.get(location_id)


def get_edge(from_id: str, to_id: str) -> Optional[dict[str, Any]]:
    """Return travel edge metadata if valid."""
    loc = LOCATIONS.get(from_id)
    if not loc:
        return None
    connections = loc.get("connections", {})
    return connections.get(to_id)


def can_travel(from_id: str, to_id: str) -> bool:
    """Return True if direct edge exists."""
    return get_edge(from_id, to_id) is not None


def evil_multiplier_for(location_id: str) -> float:
    """Return evil tick multiplier for location."""
    loc = LOCATIONS.get(location_id, {})
    return float(loc.get("evil_multiplier", 1.0))


def ring_of(location_id: str) -> int:
    """
    Return the concentric ring a place sits in (0 = deep forest).

    Args:
        location_id: Location id.

    Returns:
        Ring number, or 1 (Edgewood) for an unknown id -- the neutral middle
        of the map is a safer guess than either extreme.
    """
    loc = LOCATIONS.get(location_id)
    if loc is None:
        return 1
    return int(loc.get("ring", 1))


def locations_in_ring(ring: int) -> list[str]:
    """Return every location id in a ring, sorted for determinism."""
    return sorted(lid for lid, spec in LOCATIONS.items() if int(spec.get("ring", -1)) == ring)


def neighbours(location_id: str) -> list[str]:
    """Return every id directly reachable from a location, sorted."""
    loc = LOCATIONS.get(location_id)
    if loc is None:
        return []
    return sorted(loc.get("connections", {}))
