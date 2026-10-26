"""
Places (v0.23.0 spec §8.1, §10.5): the flat and the building, the cast's homes, the venues.

READ RECEIPTS' world graph is data (``locations.yaml``); this module is the social side's reading of
it. The venues are rows of ``venues.yaml`` whose ids are location ids, the four home templates are
rows of ``homes.yaml`` (also location ids), and each person is drawn ONE home, once, from a
counterless key (``attrs`` drawer ``home``; stream ``SOCIAL_SCENE``). Names and descriptions only:
a place carries no meaning beyond where it is.

Since v0.23.0 T13 the venues' reading and checks live here too, moved from v0.22's ``meets.py``
(deleted): ``venues``, ``venue``, ``place_line`` ("Coffee at The Copper Kettle"), ``pick_venue``
(the engine's pick for a plan by the hobbies two people share, ties drawn on SOCIAL_VENUE) and
``venue_faults`` (venues.yaml whole, at load and in the validator).
"""

from __future__ import annotations

import random
from typing import Any, Optional

from engine import social
from engine.game.locations import LOCATIONS
from engine.game.rng import SOCIAL_SCENE, SOCIAL_VENUE
from engine.game.state import GameState
from engine.social import attrs, population

#: The player's flat and building: tagged `home` or `building` in locations.yaml (the cast's homes are
#: tagged `residence`, so they are not the player's).
_FLAT_TAGS = ("home", "building")


def _homes() -> dict[str, Any]:
    return social.data("homes") or {}


def venue_ids() -> tuple[str, ...]:
    return tuple(str(r["id"]) for r in social.data("venues").get("venues") or () if isinstance(r, dict))


# -- the venues (venues.yaml; moved from meets.py by v0.23.0 T13) ----------------------------------

#: Every key of a venues.yaml row (`travel_minutes` is optional: 0 when absent).
VENUE_KEYS: tuple[str, ...] = ("id", "label", "neighbourhood", "kind", "hobbies", "duration_hours")
#: The fewest venues a story with meet-ups ships (the v0.22 brief's twelve).
MIN_VENUES = 12


def venues() -> list[dict[str, Any]]:
    return [r for r in social.data("venues").get("venues") or () if isinstance(r, dict)]


def venue(venue_id: str) -> dict[str, Any]:
    """A venues.yaml row by id; {} for none."""
    return next((r for r in venues() if r.get("id") == venue_id), {})


def place_line(venue_id: str) -> str:
    """The engine's words for meeting at `venue_id`: "Coffee at The Copper Kettle"."""
    row = venue(venue_id)
    kind = (social.data("venues").get("kinds") or {}).get(row.get("kind")) or {}
    name = str(row.get("label") or venue_id)
    if not kind:
        return name
    return f"{kind['label']} {kind['at']} {name}"


def pick_venue(state: GameState, pid: str, kind: str = "") -> str:
    """
    A venue for an engine-picked plan (the player's `ask {what: meet}`, their ask): of the venues of `kind`
    when given (and when any exist), those whose hobbies both hold, else theirs, else any; ties drawn once on
    SOCIAL_VENUE (call inside a `social_*` handler: the draw's counter is state, rule 3).
    """
    from engine.social import behaviour   # lazily: behaviour reads population, as this module does

    ids = fitting_venues(state, pid, kind)
    if not ids:
        raise ValueError("social: venues.yaml: venues: no venue to meet at")
    return ids[0] if len(ids) == 1 else behaviour.person_rng(state, SOCIAL_VENUE, pid).choice(ids)


def fitting_venues(state: GameState, pid: str, kind: str = "") -> list[str]:
    """
    The venues that fit `pid`, sorted by id (`pick_venue`'s overlap, v0.23.0 A4 W9): of the venues of `kind`
    when given (and when any exist), those whose hobbies both hold, else theirs, else any. Draws nothing and
    writes nothing: the chance tier (`presence`) reads it on every pass. [] only with no venue at all.
    """
    person = population.profile(state, pid)
    mine = set((state.social.get("player") or {}).get("hobbies") or ())
    theirs = set(person.hobbies)
    rows = venues()
    rows = [r for r in rows if r.get("kind") == kind] or rows if kind else rows
    for pool in ([r for r in rows if set(r["hobbies"]) & mine & theirs],
                 [r for r in rows if set(r["hobbies"]) & theirs], rows):
        if pool:
            return sorted(str(r["id"]) for r in pool)
    return []


def _num(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def venue_faults(data: dict[str, Any], population_data: Optional[dict[str, Any]] = None) -> list[tuple[str, str, str]]:
    """Every fault of venues.yaml as (file, key, message): its kinds, and twelve or more venues, each with every
    key, its neighbourhood and hobbies population.yaml ids when that is given. No venues.yaml, no fault."""
    src = "venues.yaml"
    if not data:
        return []
    out: list[tuple[str, str, str]] = []
    kinds = data.get("kinds")
    if not isinstance(kinds, dict) or not kinds:
        out.append((src, "kinds", "must map kind ids to {label, at}"))
        kinds = {}
    for name, row in kinds.items():
        if not isinstance(row, dict) or not all(isinstance(row.get(k), str) and row[k].strip() for k in ("label", "at")):
            out.append((src, f"kinds.{name}", "must be {label, at}, each words"))
    rows = data.get("venues")
    if not isinstance(rows, list) or len(rows) < MIN_VENUES:
        out.append((src, "venues", f"must list {MIN_VENUES} venues or more"))
        rows = rows if isinstance(rows, list) else []
    hoods = {str(r.get("id")) for r in (population_data or {}).get("neighbourhoods") or () if isinstance(r, dict)}
    hobbies = {str(r.get("id")) for r in (population_data or {}).get("hobbies") or () if isinstance(r, dict)}
    seen: set[str] = set()
    for i, row in enumerate(rows):
        where = f"venues[{i}]"
        if not isinstance(row, dict) or any(k not in row for k in VENUE_KEYS):
            out.append((src, where, f"must carry {', '.join(VENUE_KEYS)}"))
            continue
        if row["id"] in seen:
            out.append((src, f"{where}.id", f"{row['id']!r} is listed twice"))
        seen.add(str(row["id"]))
        if not isinstance(row["label"], str) or not row["label"].strip():
            out.append((src, f"{where}.label", "required: the place's name"))
        if row["kind"] not in kinds:
            out.append((src, f"{where}.kind", f"{row['kind']!r} is no kinds id"))
        if hoods and row["neighbourhood"] not in hoods:
            out.append((src, f"{where}.neighbourhood", f"{row['neighbourhood']!r} is no population.yaml neighbourhood"))
        if not isinstance(row["hobbies"], list) or (hobbies and not set(row["hobbies"]) <= hobbies):
            out.append((src, f"{where}.hobbies", "must list population.yaml hobby ids"))
        if not _num(row["duration_hours"]) or not 0 < row["duration_hours"] <= 12:
            out.append((src, f"{where}.duration_hours", "must be hours, above 0 and at most 12"))
    return out


def home_ids() -> tuple[str, ...]:
    return tuple(str(k) for k in (_homes().get("templates") or {}))


def travel_minutes(location_id: str) -> int:
    """Minutes to get to a venue or a home from anywhere in the city; 0 for any other place."""
    for row in social.data("venues").get("venues") or ():
        if isinstance(row, dict) and row.get("id") == location_id:
            return int(row.get("travel_minutes", 0) or 0)
    return int((_homes().get("travel_minutes") or {}).get(location_id, 0) or 0)


def label(location_id: str) -> str:
    """The location's name, as the player reads it."""
    return str((LOCATIONS.get(location_id) or {}).get("name") or location_id)


def is_home(location_id: str) -> bool:
    """One of the cast's four home templates."""
    return location_id in home_ids()


def is_flat(location_id: str) -> bool:
    """One of the seven rooms of the player's flat and building."""
    tags = (LOCATIONS.get(location_id) or {}).get("tags") or ()
    return any(t in tags for t in _FLAT_TAGS)


def is_upstairs(location_id: str) -> bool:
    """One of the flat's own rooms (tagged `home`): above the building's lift, which the lobby and the lift
    itself (tagged `building`) are not."""
    return "home" in ((LOCATIONS.get(location_id) or {}).get("tags") or ())


def is_outside_flat(location_id: str) -> bool:
    """Anywhere that is not the flat or the building (the street, a venue, a home, the registry)."""
    return location_id in LOCATIONS and not is_flat(location_id)


def _weights(person: Any) -> dict[str, float]:
    """The row for this person: a neighbourhood's if it has one, else the young row, else the default."""
    table = _homes().get("weights") or {}
    row = (table.get("neighbourhood") or {}).get(person.neighbourhood)
    if not row and int(person.age) < 27:
        row = table.get("age_under_27")
    return dict(row or table.get("default") or {})


@attrs.drawer("home", SOCIAL_SCENE)
def _home(state: GameState, pid: str, rng: random.Random) -> str:
    person = population.profile(state, pid)
    weights = _weights(person)
    ids = [h for h in home_ids() if float(weights.get(h, 0)) > 0]
    if not ids:
        return home_ids()[0] if home_ids() else ""
    return rng.choices(ids, weights=[float(weights[h]) for h in ids])[0]


def home_of(state: GameState, pid: str) -> str:
    """Their home's template id (a location id)."""
    return str(attrs.of(state, pid)["home"])


def home_label(state: GameState, pid: str) -> str:
    """Their home in a phrase ("a loft in the Quays")."""
    template = (_homes().get("templates") or {}).get(home_of(state, pid)) or {}
    return str(template.get("label") or "")
