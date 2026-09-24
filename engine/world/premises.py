"""
Premises
========

The houses, shops and counting-rooms inside a district: targets a thief can
case and burgle, never nodes on the travel graph. A premise lives INSIDE its
district, so the map, travel, validation and location art are all untouched by
a story growing a hundred of them.

``paths.premises`` names a directory::

    districts.yaml    district_id: {count, types: {type_id: weight}, anchors: [id]}
    names.yaml        pools: {surname, street, trade, craft, given}
    types/<type>.yaml   a generated kind -- pools drawn per premise
    anchors/<id>.yaml   a hand-written premise -- same keys, fixed contents

Generation runs once, inside ``procgen.generate_world``, before any GameState
exists -- hence ``stable_rng(seed, PREMISES)`` rather than ``world_rng``. The
stream is its own so that adding a premise type cannot reshuffle the village
procgen's PROCGEN stream has generated from every recorded seed, and so that a
story which declares no premises draws nothing at all.

Every household member becomes a procgen NPC carrying ``home`` (the premise's
interior id) and a ``routine`` whose ``@home``/``@work`` placeholders are
resolved HERE, to concrete ids. ``npc_sim.resolve_npc`` then treats that
routine as a schedule row, so a household is present, gossips and can be met
with no premise-specific code in the presence path.

Every content fault is a ValueError naming the file. A loot row naming an item
the registry does not have, or a routine sending someone to a place the map
does not have, would otherwise load, validate and do nothing -- the inert-shape
failure this repo has shipped before.

Version: v0.2.0 [2026-09-24]
"""

from __future__ import annotations

import copy
import logging
import random
import string
from pathlib import Path
from typing import Any, Optional

import yaml

from engine.config import get_config
from engine.game.rng import PREMISES, stable_rng
from engine.game.state import GameState

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parents[2]
# The parsed, validated directory. Registered in engine/games/caches.py: a
# story swap that kept it warm would lay one city's houses into another's map.
_SPEC_CACHE: Optional[dict[str, Any]] = None

HOME = "@home"
WORK = "@work"
_PLACEHOLDERS = frozenset({HOME, WORK})
# What a name pattern may say. ``n`` is a house number, drawn, not a pool.
# ``trade`` is any calling a tavern might be named for; ``craft`` is the narrow
# pool of the town's own workshop trades, for signs that must read as one --
# a candle shop signed "Bargeman" was the bug that split them.
_PATTERN_FIELDS = frozenset({"surname", "street", "trade", "craft", "given", "n"})
_HOUSE_NUMBERS = (1, 60)


# ---------------------------------------------------------------------------
# Loading and validation
# ---------------------------------------------------------------------------


def _premises_dir() -> Optional[Path]:
    rel = str(get_config().get("paths.premises", "") or "").strip()
    return (_ROOT / rel) if rel else None


def declared() -> bool:
    """Whether the running story declares premises at all."""
    return _premises_dir() is not None


def _read(path: Path) -> Any:
    try:
        with path.open(encoding="utf-8") as fh:
            return yaml.safe_load(fh)
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"premises: cannot read {path}: {exc}") from exc


def _fail(path: Path, message: str) -> ValueError:
    return ValueError(f"premises: {path.name} ({path}): {message}")


def _weights(path: Path, key: str, raw: Any) -> dict[Any, int]:
    if not isinstance(raw, dict) or not raw:
        raise _fail(path, f"`{key}` must be a non-empty mapping of id -> weight")
    out: dict[Any, int] = {}
    for k, w in raw.items():
        try:
            weight = int(w)
        except (TypeError, ValueError):
            raise _fail(path, f"`{key}.{k}` weight {w!r} is not an integer") from None
        if weight < 0:
            raise _fail(path, f"`{key}.{k}` weight {weight} is negative")
        out[k] = weight
    if not any(out.values()):
        raise _fail(path, f"`{key}` has no positive weight")
    return out


def _check_location(path: Path, where: str, loc: str, locations: Any) -> None:
    if loc not in locations:
        raise _fail(path, f"{where} names unknown location {loc!r}")


def _check_household(
    path: Path, spec: dict[str, Any], locations: Any
) -> None:
    household = spec.get("household") or []
    if not isinstance(household, list):
        raise _fail(path, "`household` must be a list")
    work_at = spec.get("work_at") or []
    if not isinstance(work_at, list):
        raise _fail(path, "`work_at` must be a list")
    for loc in work_at:
        _check_location(path, "`work_at`", str(loc), locations)
    for idx, member in enumerate(household):
        if not isinstance(member, dict) or not str(member.get("role") or "").strip():
            raise _fail(path, f"household[{idx}] needs a `role`")
        routine = member.get("routine") or []
        if not isinstance(routine, list):
            raise _fail(path, f"household[{idx}].routine must be a list")
        for slot in routine:
            if not isinstance(slot, dict) or not isinstance(slot.get("hours"), list):
                raise _fail(path, f"household[{idx}].routine slot {slot!r} needs `hours`")
            loc = str(slot.get("location") or "")
            if loc == WORK and not work_at:
                # @work with nowhere to work would leave the person standing
                # at a literal "@work" that no location matches.
                raise _fail(path, f"household[{idx}] uses {WORK} but `work_at` is empty")
            if loc not in _PLACEHOLDERS:
                _check_location(path, f"household[{idx}].routine", loc, locations)


def _check_patterns(path: Path, patterns: Any, pools: dict[str, list[str]]) -> None:
    if not isinstance(patterns, list) or not patterns:
        raise _fail(path, "`name_patterns` must be a non-empty list")
    for pattern in patterns:
        for _, field, _, _ in string.Formatter().parse(str(pattern)):
            if field is None:
                continue
            if field not in _PATTERN_FIELDS:
                raise _fail(path, f"name pattern {pattern!r} uses unknown field {{{field}}}")
            if field != "n" and not pools.get(field):
                raise _fail(path, f"name pattern {pattern!r} needs the empty `{field}` pool")


def _load_type(path: Path, pools: dict[str, list[str]], items: Any, locations: Any) -> dict[str, Any]:
    spec = _read(path)
    if not isinstance(spec, dict):
        raise _fail(path, "a premise type must be a mapping")
    spec.setdefault("id", path.stem)
    if not str(spec.get("label") or "").strip():
        # The casing board shows this to the PLAYER (state.py's
        # `_premises_block`); an id like "townhouse" reaching the screen in
        # its author's place is the id-as-content bug this repo keeps finding.
        raise _fail(path, "a premise type needs a `label` for the casing board")
    _check_patterns(path, spec.get("name_patterns"), pools)
    raw_tiers = _weights(path, "tiers", spec.get("tiers"))
    try:
        tiers = {int(t): w for t, w in raw_tiers.items()}
    except (TypeError, ValueError):
        raise _fail(path, "`tiers` keys must be integers") from None
    if any(t < 1 for t in tiers):
        raise _fail(path, "`tiers` keys start at 1")
    spec["tiers"] = tiers
    _check_household(path, spec, locations)

    security = spec.get("security") or []
    if not isinstance(security, list) or not all(
        isinstance(s, dict) and s.get("id") for s in security
    ):
        raise _fail(path, "`security` must be a list of {id, text, tier_min}")
    raw_loot = spec.get("loot") or {}
    if not isinstance(raw_loot, dict):
        raise _fail(path, "`loot` must map tier -> rows")
    try:
        loot = {int(t): rows for t, rows in raw_loot.items()}
    except (TypeError, ValueError):
        raise _fail(path, "`loot` keys must be integer tiers") from None
    spec["loot"] = loot
    for tier, weight in tiers.items():
        if weight <= 0:
            continue
        # Tier N draws N features. Too few eligible would hand the richest
        # houses fewer defences than their tier promises, silently.
        eligible = [s for s in security if int(s.get("tier_min", 1)) <= tier]
        if len(eligible) < tier:
            raise _fail(
                path,
                f"tier {tier} draws {tier} security features but only "
                f"{len(eligible)} have tier_min <= {tier}",
            )
        rows = loot.get(tier)
        if not isinstance(rows, list) or not rows:
            raise _fail(path, f"tier {tier} has no `loot` rows")
    for tier, rows in loot.items():
        for row in rows or []:
            if not isinstance(row, dict) or not row.get("item_id"):
                raise _fail(path, f"loot tier {tier} row {row!r} needs `item_id`")
            if str(row["item_id"]) not in items:
                raise _fail(path, f"loot tier {tier} names unknown item {row['item_id']!r}")
            if int(row.get("weight", 1)) <= 0:
                raise _fail(path, f"loot tier {tier} row {row['item_id']!r} has no weight")
    secrets = spec.get("secrets") or []
    if not isinstance(secrets, list) or not all(
        isinstance(s, dict) and s.get("id") for s in secrets
    ):
        raise _fail(path, "`secrets` must be a list of {id, text}")
    return spec


def _load_anchor(path: Path, items: Any, locations: Any) -> dict[str, Any]:
    spec = _read(path)
    if not isinstance(spec, dict):
        raise _fail(path, "an anchor must be a mapping")
    spec.setdefault("id", path.stem)
    for key in ("district", "name", "label"):
        if not str(spec.get(key) or "").strip():
            raise _fail(path, f"an anchor needs a fixed `{key}`")
    _check_location(path, "`district`", str(spec["district"]), locations)
    try:
        spec["tier"] = int(spec.get("tier"))
    except (TypeError, ValueError):
        raise _fail(path, "an anchor needs an integer `tier`") from None
    _check_household(path, spec, locations)

    security = spec.get("security") or []
    if not isinstance(security, list) or not all(
        isinstance(s, dict) and s.get("id") for s in security
    ):
        raise _fail(path, "`security` must be a list of {id, text}")
    loot = spec.get("loot") or []
    if not isinstance(loot, list):
        raise _fail(path, "an anchor's `loot` is a fixed list of item ids")
    ids = [str(r.get("item_id") if isinstance(r, dict) else r) for r in loot]
    for item_id in ids:
        if item_id not in items:
            raise _fail(path, f"loot names unknown item {item_id!r}")
    spec["loot"] = ids
    secrets = spec.get("secrets") or []
    if not isinstance(secrets, list) or not all(
        isinstance(s, dict) and s.get("id") for s in secrets
    ):
        raise _fail(path, "`secrets` must be a list of {id, text}")
    if len(secrets) > 1:
        # A premise holds ONE secret; keeping the first of several would drop
        # authored content without a word.
        raise _fail(path, f"an anchor holds one secret, {len(secrets)} are written")
    return spec


def _load() -> dict[str, Any]:
    """Parse and validate the declared directory once per activation."""
    global _SPEC_CACHE
    if _SPEC_CACHE is not None:
        return _SPEC_CACHE
    root = _premises_dir()
    if root is None:
        _SPEC_CACHE = {"districts": {}, "pools": {}, "types": {}, "anchors": {}}
        return _SPEC_CACHE
    if not root.is_dir():
        # Declared and absent is a broken install, not "no premises": the
        # story promised a city full of houses and would ship an empty one.
        raise ValueError(f"premises: declared directory {root} does not exist")

    from engine.game.inventory import load_items
    from engine.game.locations import LOCATIONS

    items = load_items()

    names_path = root / "names.yaml"
    names = _read(names_path) if names_path.exists() else {}
    raw_pools = (names or {}).get("pools") or {}
    if not isinstance(raw_pools, dict):
        raise _fail(names_path, "`pools` must be a mapping of pool -> list")
    pools = {str(k): [str(v) for v in (vals or [])] for k, vals in raw_pools.items()}

    types: dict[str, dict[str, Any]] = {}
    for path in sorted((root / "types").glob("*.yaml")):
        spec = _load_type(path, pools, items, LOCATIONS)
        types[str(spec["id"])] = spec
    anchors: dict[str, dict[str, Any]] = {}
    for path in sorted((root / "anchors").glob("*.yaml")):
        spec = _load_anchor(path, items, LOCATIONS)
        anchors[str(spec["id"])] = spec

    districts_path = root / "districts.yaml"
    raw_districts = _read(districts_path) if districts_path.exists() else None
    if not isinstance(raw_districts, dict):
        raise _fail(districts_path, "must map district_id -> {count, types, anchors}")
    districts: dict[str, dict[str, Any]] = {}
    listed: dict[str, str] = {}
    for district_id, cfg in raw_districts.items():
        district_id = str(district_id)
        _check_location(districts_path, "district", district_id, LOCATIONS)
        cfg = cfg or {}
        try:
            count = int(cfg.get("count", 0))
        except (TypeError, ValueError):
            raise _fail(districts_path, f"{district_id}.count is not an integer") from None
        weights = _weights(districts_path, f"{district_id}.types", cfg.get("types")) if count else {}
        for type_id in weights:
            if str(type_id) not in types:
                raise _fail(districts_path, f"{district_id} names unknown type {type_id!r}")
        for anchor_id in cfg.get("anchors") or []:
            anchor_id = str(anchor_id)
            if anchor_id not in anchors:
                raise _fail(districts_path, f"{district_id} names unknown anchor {anchor_id!r}")
            if anchors[anchor_id]["district"] != district_id:
                raise _fail(
                    districts_path,
                    f"anchor {anchor_id!r} is listed in {district_id} but declares "
                    f"district {anchors[anchor_id]['district']!r}",
                )
            if anchor_id in listed:
                raise _fail(districts_path, f"anchor {anchor_id!r} is listed twice")
            listed[anchor_id] = district_id
        districts[district_id] = {
            "count": count,
            "types": {str(k): v for k, v in weights.items()},
            "anchors": sorted(str(a) for a in cfg.get("anchors") or []),
        }
    unplaced = sorted(set(anchors) - set(listed))
    if unplaced:
        # An anchor no district lists is authored content the city never holds.
        raise _fail(districts_path, f"anchors not listed in any district: {unplaced}")
    if any(d["anchors"] or d["count"] for d in districts.values()):
        if not (pools.get("given") and pools.get("surname")):
            raise _fail(names_path, "households need the `given` and `surname` pools")

    _SPEC_CACHE = {"districts": districts, "pools": pools, "types": types, "anchors": anchors}
    return _SPEC_CACHE


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------


def _weighted(rng: random.Random, weights: dict[Any, int]) -> Any:
    # Sorted keys: a YAML mapping's order is the author's, and a reorder in the
    # file must not change what a recorded seed generates.
    keys = sorted(weights, key=str)
    return rng.choices(keys, weights=[weights[k] for k in keys], k=1)[0]


def _household(
    rng: random.Random,
    spec: dict[str, Any],
    pools: dict[str, list[str]],
    district_id: str,
    premise_id: str,
) -> list[dict[str, Any]]:
    from engine.world.npc_sim import interior_id

    home = interior_id(district_id, premise_id)
    stem = premise_id.removeprefix("prem_")
    work_at = [str(w) for w in spec.get("work_at") or []]
    members: list[dict[str, Any]] = []
    seen: dict[str, int] = {}
    for member in spec.get("household") or []:
        role = str(member["role"])
        seen[role] = seen.get(role, 0) + 1
        suffix = role if seen[role] == 1 else f"{role}_{seen[role]}"
        # One workplace per person, drawn once: a clerk who worked at a
        # different counting-house every hour would be unfindable.
        work = rng.choice(work_at) if work_at else ""
        routine = []
        for slot in member.get("routine") or []:
            loc = str(slot.get("location") or "")
            resolved = home if loc == HOME else work if loc == WORK else loc
            routine.append({**slot, "location": resolved})
        members.append(
            {
                "id": f"gen_{stem}_{suffix}",
                "name": f"{rng.choice(pools['given'])} {rng.choice(pools['surname'])}",
                "role": role,
                "home": home,
                "premise": premise_id,
                "routine": routine,
            }
        )
    return members


def _name(rng: random.Random, spec: dict[str, Any], pools: dict[str, list[str]]) -> str:
    pattern = str(rng.choice(spec["name_patterns"]))
    fields = {k: rng.choice(v) for k, v in sorted(pools.items()) if v}
    fields["n"] = str(rng.randint(*_HOUSE_NUMBERS))
    return pattern.format_map(fields)


def _generated_premise(
    rng: random.Random,
    type_id: str,
    spec: dict[str, Any],
    pools: dict[str, list[str]],
    district_id: str,
    index: int,
    used_names: set[str],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    premise_id = f"prem_{district_id}_{index}"
    for _ in range(20):
        name = _name(rng, spec, pools)
        if name not in used_names:
            break
    else:
        # Twenty collisions: disambiguate rather than emit two houses the
        # player cannot tell apart (procgen's villager rule).
        name = f"{name} (the {index})"
    used_names.add(name)
    tier = int(_weighted(rng, spec["tiers"]))
    eligible = sorted(
        (s for s in spec.get("security") or [] if int(s.get("tier_min", 1)) <= tier),
        key=lambda s: str(s["id"]),
    )
    security = sorted(str(s["id"]) for s in rng.sample(eligible, tier))
    rows = spec["loot"][tier]
    loot = sorted(
        str(r["item_id"])
        for r in rng.choices(rows, weights=[int(r.get("weight", 1)) for r in rows], k=tier)
    )
    secrets = spec.get("secrets") or []
    secret = str(rng.choice(secrets)["id"]) if secrets else ""
    household = _household(rng, spec, pools, district_id, premise_id)
    premise = {
        "id": premise_id,
        "district": district_id,
        "type": type_id,
        "anchor": False,
        "name": name,
        "tier": tier,
        "household": [m["id"] for m in household],
        "security": security,
        "loot": loot,
        "secret": secret,
    }
    return premise, household


def _anchor_premise(
    rng: random.Random, anchor_id: str, spec: dict[str, Any], pools: dict[str, list[str]]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    premise_id = f"prem_{anchor_id}"
    district_id = str(spec["district"])
    # Only the household's names and workplaces are drawn; everything a thief
    # would come for is written by hand.
    household = _household(rng, spec, pools, district_id, premise_id)
    secrets = spec.get("secrets") or []
    premise = {
        "id": premise_id,
        "district": district_id,
        "type": anchor_id,
        "anchor": True,
        "name": str(spec["name"]),
        "tier": int(spec["tier"]),
        "household": [m["id"] for m in household],
        "security": [str(s["id"]) for s in spec.get("security") or []],
        "loot": list(spec["loot"]),
        "secret": str(secrets[0]["id"]) if secrets else "",
    }
    return premise, household


def generate(seed: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """
    Lay out every district's premises from the seed.

    Returns:
        ``(premises, household_npcs)``; ``([], [])`` when the story declares
        none. Districts are walked in sorted order, each district's anchors
        first and then its ``count`` generated premises -- anchors are in
        ADDITION to the count, so an author adding a hand-written manor does
        not silently lose a generated house.
    """
    if not declared():
        return [], []
    spec = _load()
    rng = stable_rng(seed, PREMISES)
    pools = spec["pools"]
    premises: list[dict[str, Any]] = []
    npcs: list[dict[str, Any]] = []
    used_names: set[str] = set()
    for district_id in sorted(spec["districts"]):
        cfg = spec["districts"][district_id]
        for anchor_id in cfg["anchors"]:
            prem, household = _anchor_premise(rng, anchor_id, spec["anchors"][anchor_id], pools)
            used_names.add(prem["name"])
            premises.append(prem)
            npcs.extend(household)
        for index in range(1, cfg["count"] + 1):
            type_id = str(_weighted(rng, cfg["types"]))
            prem, household = _generated_premise(
                rng, type_id, spec["types"][type_id], pools, district_id, index, used_names
            )
            premises.append(prem)
            npcs.extend(household)
    logger.info(
        "[premises] Generated (operation=generate, seed=%s, premises=%s, people=%s)",
        seed,
        len(premises),
        len(npcs),
    )
    return premises, npcs


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------


def at(state: GameState, location_id: str) -> list[dict[str, Any]]:
    """The premises inside a district, in generation order."""
    return [p for p in state.procgen.premises if p.get("district") == location_id]


def get(state: GameState, premise_id: str) -> Optional[dict[str, Any]]:
    """One premise by id, or None."""
    for prem in state.procgen.premises:
        if prem.get("id") == premise_id:
            return prem
    return None


def spec(type_or_anchor_id: str) -> dict[str, Any]:
    """
    The authored definition of a type or anchor, for text lookups.

    A copy, so a caller dressing up a security line cannot edit the cache
    every later premise reads. Empty for an unknown id.
    """
    loaded = _load()
    found = loaded["types"].get(type_or_anchor_id) or loaded["anchors"].get(type_or_anchor_id)
    return copy.deepcopy(found) if found else {}


def definitions() -> dict[str, dict[str, Any]]:
    """
    Every authored type and anchor, as ``{"types": {...}, "anchors": {...}}``.

    A copy, for the ``spec`` reason. Read by ``jobs`` at load, which checks
    its security features, anchors and tier bands against what the city can
    actually hold. Empty maps for a story that declares no premises.
    """
    loaded = _load()
    return {
        "types": copy.deepcopy(loaded["types"]),
        "anchors": copy.deepcopy(loaded["anchors"]),
    }


# ---------------------------------------------------------------------------
# Casing: what watching a house tells you
# ---------------------------------------------------------------------------

#: In-game hours one watch costs. Spent through ``clock.advance_time`` like
#: every other hour in the game, so a watch ticks hunger, the doom clock and
#: every routine exactly as waiting would.
CASE_HOURS = 2
#: The Law's deed kind a watch commits, where the story declares a Law.
LOITERING_DEED = "loitering"

OCCUPANCY = "occupancy"
LOOT_HINT = "loot"
SECRET_HINT = "secret"
_SECURITY_PREFIX = "security:"


def _ordered_ids(state: GameState, prem: dict[str, Any]) -> list[str]:
    """
    Every intel id the house holds, in the order a watcher learns them.

    Occupancy is always first: it is what a watcher on the street sees in the
    first hour, and every later question (when to go in) hangs off it. The rest
    is shuffled on a stream keyed by the run's seed AND the premise, so two
    houses of one type do not give up their secrets in the same order, and a
    replayed seed cases every house identically. ``stable_rng`` rather than
    ``world_rng``: this runs on every prompt build, and a counter consumed
    there would make the order depend on how often the UI rendered.
    """
    rest = [f"{_SECURITY_PREFIX}{s}" for s in prem.get("security") or []]
    if prem.get("loot"):
        rest.append(LOOT_HINT)
    if prem.get("secret"):
        rest.append(SECRET_HINT)
    rng = stable_rng(int(state.rng_seed), f"{PREMISES}:{prem.get('id')}")
    rng.shuffle(rest)
    return [OCCUPANCY, *rest]


def _occupancy_text(state: GameState, prem: dict[str, Any]) -> str:
    """
    The longest run of hours today when nobody in the household is home.

    Resolved through ``npc_sim.resolve_npc`` on a SHALLOW COPY whose clock is
    set to each hour in turn -- never ``advance_time`` on the real state, which
    would run the whole world forward to answer a question. The copy shares
    flags and events, so a quest pin holding the cook at home keeps the house
    occupied here exactly as it does on the street.
    """
    from engine.world.npc_sim import interior_id, resolve_npc

    home = interior_id(str(prem.get("district")), str(prem.get("id")))
    day_start = (state.world_day - 1) * 24
    scratch = copy.copy(state)
    empty: list[bool] = []
    for hour in range(24):
        scratch.world_clock_hours = float(day_start + hour)
        inside = False
        for npc_id in prem.get("household") or []:
            here = resolve_npc(scratch, str(npc_id))
            if here is not None and here.location_id == home:
                inside = True
                break
        empty.append(not inside)
    if all(empty):
        return "empty all day and night"
    best_start, best_len = -1, 0
    for start in range(24):
        # A run starts where the previous hour (wrapping midnight) was occupied.
        if not empty[start] or empty[start - 1]:
            continue
        length = 0
        while empty[(start + length) % 24]:
            length += 1
        if length > best_len:
            best_start, best_len = start, length
    if best_len == 0:
        return "never empty"
    end = (best_start + best_len) % 24
    return f"empty from {best_start:02d}:00 to {end:02d}:00"


def _security_text(prem: dict[str, Any], feature_id: str) -> str:
    for row in spec(str(prem.get("type") or "")).get("security") or []:
        if isinstance(row, dict) and str(row.get("id")) == feature_id:
            return str(row.get("text") or feature_id.replace("_", " "))
    return feature_id.replace("_", " ")


def _loot_text(prem: dict[str, Any]) -> str:
    from engine.game.inventory import name_of, value_of

    loot = [str(i) for i in prem.get("loot") or []]
    # max() keeps the first of equals, and loot is stored sorted, so a tie
    # names the same piece on every build.
    best = max(loot, key=value_of)
    return f"worth it: {name_of(best)}"


def _text_for(state: GameState, prem: dict[str, Any], intel_id: str) -> str:
    if intel_id == OCCUPANCY:
        return _occupancy_text(state, prem)
    if intel_id == LOOT_HINT:
        return _loot_text(prem)
    if intel_id == SECRET_HINT:
        # That a secret EXISTS, never what it is: the lever itself is found by
        # going in, not by watching the door.
        return "somebody here is hiding something"
    return _security_text(prem, intel_id.removeprefix(_SECURITY_PREFIX))


def intel_for(state: GameState, premise_id: str) -> list[dict[str, str]]:
    """
    Everything casing can learn about one premise, in learning order.

    Returns:
        ``[{"id", "text"}]``; empty for an unknown premise.
    """
    prem = get(state, premise_id)
    if prem is None:
        return []
    return [
        {"id": intel_id, "text": _text_for(state, prem, intel_id)}
        for intel_id in _ordered_ids(state, prem)
    ]


def known(state: GameState, premise_id: str) -> list[str]:
    """The intel ids already learned about a premise, in learning order."""
    return list(state.premise_intel.get(premise_id) or [])


def unknown_ids(state: GameState, premise_id: str) -> list[str]:
    """
    The intel ids still to learn, WITHOUT composing their texts.

    The ``case`` verb builder calls this on every prompt build for every house
    in the district; the occupancy text alone resolves each household member
    across twenty-four hours, which is work only a watch that happens needs.
    """
    prem = get(state, premise_id)
    if prem is None:
        return []
    seen = set(known(state, premise_id))
    return [i for i in _ordered_ids(state, prem) if i not in seen]


def empty_now(state: GameState, premise_id: str) -> bool:
    """
    Whether nobody in the household resolves inside the house RIGHT NOW.

    Unlike the occupancy INTEL line, which reads the longest empty run across
    a scratch copy walked through all twenty-four hours, this resolves the
    household against the real, current world clock -- the casing board's
    "go now" marker, not a fact a watch has to earn. For an unknown premise,
    empty rather than raising: a board is free to just not mark a house it
    cannot find.
    """
    from engine.world.npc_sim import interior_id, resolve_npc

    prem = get(state, premise_id)
    if prem is None:
        return True
    home = interior_id(str(prem.get("district")), str(prem.get("id")))
    for npc_id in prem.get("household") or []:
        here = resolve_npc(state, str(npc_id))
        if here is not None and here.location_id == home:
            return False
    return True


def case(state: GameState, premise_id: str) -> dict[str, Any]:
    """
    Watch a house for ``CASE_HOURS`` and learn the next thing about it.

    Refuses -- ``ok: False`` with a ``message`` the narrator is handed -- for a
    house that does not exist, is not in the player's district, or has nothing
    left to give. A refusal spends no time: standing outside a house you
    already know everything about is not a watch.

    Returns:
        ``{"ok", "premise", "learned", "known", "of", "hours"}`` on a watch,
        plus ``seen_by`` and ``reported`` where the story declares a Law.
    """
    from engine.game.clock import advance_time
    from engine.game.effects import apply_effect
    from engine.world import law

    prem = get(state, premise_id)
    if prem is None:
        return {"ok": False, "message": "there is no such house to watch"}
    name = str(prem.get("name") or "the house")
    if prem.get("district") != state.location_id:
        return {"ok": False, "premise": name, "message": f"{name} is not in this district"}
    order = _ordered_ids(state, prem)
    remaining = unknown_ids(state, premise_id)
    if not remaining:
        return {
            "ok": False,
            "premise": name,
            "message": f"there is nothing more to learn by watching {name}",
        }

    advance_time(state, CASE_HOURS)
    receipt = apply_effect(
        state, {"type": "intel", "premise": premise_id, "intel": remaining[0]}
    )
    if receipt.get("ok"):
        # "Restored between jobs" means casing again, not a free reset: prep
        # refills only through a watch that actually revealed something, and
        # only where a story has jobs to spend it on. `job_prep` clamps to
        # `prep.max` on its own.
        from engine.world import jobs

        if jobs.declared():
            apply_effect(
                state, {"type": "job_prep", "delta": int(jobs.spec()["prep"]["per_case"])}
            )
    seen: Optional[dict[str, Any]] = None
    if law.declared():
        # Two hours watching one door is loitering. Committed as the watch
        # ENDS, so the witnesses are whoever is on the street by then and the
        # row is stamped with the day it ended on. Severity 0 in the contract:
        # remembered, never reported on its own.
        seen = law.commit_deed(state, LOITERING_DEED)
    logger.info(
        "[premises] Cased (operation=case, premise=%s, intel=%s, known=%s/%s)",
        premise_id,
        remaining[0],
        len(known(state, premise_id)),
        len(order),
    )
    return {
        "ok": True,
        "premise": name,
        "learned": str(receipt.get("text") or ""),
        "known": len(known(state, premise_id)),
        "of": len(order),
        "hours": CASE_HOURS,
        # Only with a Law, so a story without one keeps a byte-identical receipt.
        **({"seen_by": seen["witnesses"], "reported": seen["reported"]} if seen else {}),
    }
