"""
Behaviour: the engine runs the people (v0.22.0 spec §5).

`behaviours.yaml` declares archetypes (NUMBERS and moves, spec §5.1) and
arcs (§5.3). `archetype(name)` builds one `Archetype` from its row, raising a
`ValueError` that names `behaviours.yaml` and the key at fault (the load
rule, spec §2.1); `engine/games/validation.py` runs the same builders over
every row, so a story that validates clean loads clean.

A person's week (§5.2) comes from `population.yaml` `schedules[job_shape]`:
per weekday, `[start_hour, end_hour, status]` bands, any hour no band covers
asleep. `status_at` and `next_awake` are DERIVED, never stored, and draw
nothing (the `npc_sim` rule). Day 1 is a Monday.

Per-person draws (§5.4) go through `person_rng`: `stable_rng(seed,
f"{stream}:{pid}:{n}")` with `n` the person's own counter in
`people[pid]["rng_n"][stream]`, so one person's history never shifts
another's. It writes that counter, so it is called only from inside a
`social_*` effect handler (rule 3).
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any, Optional

from engine import social
from engine.game import detmath
from engine.game.rng import stable_rng
from engine.game.state import GameState
from engine.social.kinds import stage_rank

#: Day 1 is a Monday; `schedules` rows are keyed by these.
WEEKDAYS: tuple[str, ...] = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")

#: What a schedule band may say a person is doing (spec §5.2).
STATUSES: tuple[str, ...] = ("asleep", "work", "free", "out")

#: Every key an archetype row must carry (spec §5.1).
ARCHETYPE_KEYS: tuple[str, ...] = (
    "reply_minutes", "reply_prob", "opener_prob", "ghost_per_episode",
    "left_on_read_sensitivity", "warmth_mult", "warmth_cap_band", "cool_off_step", "flake_prob",
    "double_text", "initiations", "media", "games", "arc", "growth", "promise_prob", "offer_number_prob",
)

#: An archetype's `growth:` block (v0.23.0 spec §6.2): pace, the phone and in-person depth caps,
#: and the loss multiplier (a ghoster's openness "decays twice as fast", Plan decision 19).
GROWTH_KEYS: tuple[str, ...] = ("pace", "cap", "cap_in_person", "decay_mult")

#: Spec §10.5: `cool_off` lowers interest by the archetype's step, at most this.
COOL_OFF_STEP_MAX = 5

#: An initiation row's keys (v0.23.0 spec §4.7).
INITIATION_KEYS: frozenset[str] = frozenset({"id", "kind", "window", "prob", "when", "instruction"})

#: An initiation's `when` conditions, read by messaging.when_holds (T8).
WHEN_KEYS: tuple[str, ...] = ("stage_min", "hours_since_player", "days_since_last", "ghosted", "weekend")


@dataclass(frozen=True)
class Archetype:
    name: str
    reply_minutes: tuple[float, float]       # (median, spread), lognormal: an opener's or a game's delay
    reply_prob: float                        # the reply draw at an episode's start (v0.23.0 §4.6)
    opener_prob: float
    ghost_per_episode: float                 # the ghost draw at an episode's start (v0.23.0 §4.6)
    left_on_read_sensitivity: float
    warmth_mult: float
    warmth_cap_band: Optional[str]
    cool_off_step: int
    flake_prob: float
    double_text: dict[str, Any]
    initiations: tuple[dict[str, Any], ...]
    media: dict[str, Any]
    games: dict[str, Any]
    arc: Optional[str]
    growth: dict[str, Any]                   # {pace, cap, cap_in_person, decay_mult} (v0.23.0 §6.2)
    promise_prob: float = 0.0                # a sign-off carries a promise (v0.23.0 §5.2; drawn from T4)
    offer_number_prob: float = 0.0           # they offer their number at depth 1 (v0.23.0 §15; drawn from T5)


# -- loading ------------------------------------------------------------------


def _fault(key: str, message: str) -> ValueError:
    return ValueError(f"social: behaviours.yaml: {key}: {message}")


def _number(row: dict[str, Any], key: str, where: str, *, low: float = 0.0, high: Optional[float] = None) -> float:
    value = row.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _fault(f"{where}.{key}", f"must be a number, not {value!r}")
    if value < low or (high is not None and value > high):
        span = f"{low} to {high}" if high is not None else f"at least {low}"
        raise _fault(f"{where}.{key}", f"must be {span}, not {value!r}")
    return float(value)


def _whole(row: dict[str, Any], key: str, where: str, *, low: int = 0, high: Optional[int] = None) -> int:
    value = row.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise _fault(f"{where}.{key}", f"must be a whole number, not {value!r}")
    if value < low or (high is not None and value > high):
        raise _fault(f"{where}.{key}", f"must be {low} to {high}, not {value!r}" if high is not None
                     else f"must be at least {low}, not {value!r}")
    return value


def _mapping(row: dict[str, Any], key: str, where: str) -> dict[str, Any]:
    value = row.get(key)
    if not isinstance(value, dict):
        raise _fault(f"{where}.{key}", f"must be a mapping, not {value!r}")
    return value


def _latency(row: dict[str, Any], key: str, where: str) -> tuple[float, float]:
    spec = _mapping(row, key, where)
    median = _number(spec, "median", f"{where}.{key}")
    if median <= 0:
        raise _fault(f"{where}.{key}.median", "must be above 0")
    return median, _number(spec, "spread", f"{where}.{key}")


def _initiation(raw: Any, where: str) -> dict[str, Any]:
    """One `initiations:` row (v0.23.0 spec §4.7): {id, kind, window, prob: [d0..d4], when?, instruction?}."""
    from engine.social import growth, windows   # lazily: both import this module

    if not isinstance(raw, dict):
        raise _fault(where, "must be a mapping {id, kind, window, prob, ...}")
    if not isinstance(raw.get("id"), str) or not raw["id"]:
        raise _fault(f"{where}.id", "must be a non-empty id")
    where = f"{where}({raw['id']})"
    if not isinstance(raw.get("kind"), str) or not raw["kind"]:
        raise _fault(f"{where}.kind", "must be a message kind")
    retired = sorted(k for k in ("at_hours", "prob_per_day") if k in raw)
    if retired:
        raise _fault(where, f"{', '.join(retired)} went in v0.23.0: a row names its `window` and `prob` per depth")
    if raw.get("window") not in windows.INITIATION_WINDOWS:
        raise _fault(f"{where}.window", f"must be one of {', '.join(windows.INITIATION_WINDOWS)}, "
                                        f"not {raw.get('window')!r}")
    prob = raw.get("prob")
    if (not isinstance(prob, list) or len(prob) != len(growth.RUNGS)
            or not all(isinstance(v, (int, float)) and not isinstance(v, bool) and 0 <= v <= 1 for v in prob)):
        raise _fault(f"{where}.prob", f"must be {len(growth.RUNGS)} chances 0-1, one per depth, not {prob!r}")
    if "when" in raw:
        when = raw["when"]
        if not isinstance(when, dict):
            raise _fault(f"{where}.when", "must be a mapping of conditions")
        unknown = sorted(str(k) for k in when if k not in WHEN_KEYS)
        if unknown:
            raise _fault(f"{where}.when", f"has unknown conditions {', '.join(unknown)} "
                                          f"(known: {', '.join(WHEN_KEYS)})")
        if "stage_min" in when and stage_rank(when["stage_min"]) < 0:
            raise _fault(f"{where}.when", f"stage_min {when['stage_min']!r} is no live stage")
        for key in ("hours_since_player", "days_since_last"):
            if key in when:
                _number(when, key, f"{where}.when")
        for key in ("ghosted", "weekend"):
            if key in when and not isinstance(when[key], bool):
                raise _fault(f"{where}.when", f"{key} must be true or false")
    if "instruction" in raw and (not isinstance(raw["instruction"], str) or not raw["instruction"]):
        raise _fault(f"{where}.instruction", "must be a situation id")
    unknown = sorted(str(k) for k in raw if k not in INITIATION_KEYS)
    if unknown:
        raise _fault(where, f"has unknown keys {', '.join(unknown)}")
    return dict(raw)


def build_archetype(name: str, row: Any, arcs: dict[str, Any]) -> Archetype:
    """One archetype row -> `Archetype`; a `ValueError` naming the key at fault."""
    where = f"archetypes.{name}"
    if not isinstance(row, dict):
        raise _fault(where, "must be a mapping")
    missing = [key for key in ARCHETYPE_KEYS if key not in row]
    if missing:
        raise _fault(where, f"is missing {', '.join(missing)}")
    unknown = sorted(set(row) - set(ARCHETYPE_KEYS))
    if unknown:
        raise _fault(where, f"has unknown keys {', '.join(map(str, unknown))}")

    band = row["warmth_cap_band"]
    if band is not None and (not isinstance(band, str) or not band):
        raise _fault(f"{where}.warmth_cap_band", "must be a closeness band id or null")
    arc = row["arc"]
    if arc is not None and (not isinstance(arc, str) or arc not in arcs):
        raise _fault(f"{where}.arc", f"{arc!r} names no arcs entry")

    double = _mapping(row, "double_text", where)
    _number(double, "after_hours", f"{where}.double_text")
    _number(double, "prob", f"{where}.double_text", high=1.0)
    _whole(double, "max_in_row", f"{where}.double_text")

    raw_inits = row["initiations"]
    if not isinstance(raw_inits, list):
        raise _fault(f"{where}.initiations", "must be a list")
    initiations = tuple(_initiation(item, f"{where}.initiations[{i}]") for i, item in enumerate(raw_inits))
    ids = [item["id"] for item in initiations]
    if len(set(ids)) != len(ids):
        raise _fault(f"{where}.initiations", "names an id twice")

    media = _mapping(row, "media", where)
    _number(media, "offer_mult", f"{where}.media")
    _number(media, "accept_mult", f"{where}.media")
    games = _mapping(row, "games", where)
    _number(games, "skill", f"{where}.games", high=1.0)
    _number(games, "invite_prob_per_day", f"{where}.games", high=1.0)
    growth = _growth(row, where)

    return Archetype(
        name=name,
        reply_minutes=_latency(row, "reply_minutes", where),
        reply_prob=_number(row, "reply_prob", where, high=1.0),
        opener_prob=_number(row, "opener_prob", where, high=1.0),
        ghost_per_episode=_number(row, "ghost_per_episode", where, high=1.0),
        left_on_read_sensitivity=_number(row, "left_on_read_sensitivity", where),
        warmth_mult=_number(row, "warmth_mult", where),
        warmth_cap_band=band,
        cool_off_step=_whole(row, "cool_off_step", where, high=COOL_OFF_STEP_MAX),
        flake_prob=_number(row, "flake_prob", where, high=1.0),
        double_text=dict(double),
        initiations=initiations,
        media=dict(media),
        games=dict(games),
        arc=arc,
        growth=growth,
        promise_prob=_number(row, "promise_prob", where, high=1.0),
        offer_number_prob=_number(row, "offer_number_prob", where, high=1.0),
    )


def _growth(row: dict[str, Any], where: str) -> dict[str, Any]:
    """The `growth:` block (v0.23.0 spec §6.2): every key, pace above 0, each cap a depth 0-4."""
    block = _mapping(row, "growth", where)
    at = f"{where}.growth"
    missing = [key for key in GROWTH_KEYS if key not in block]
    if missing:
        raise _fault(at, f"is missing {', '.join(missing)}")
    unknown = sorted(str(k) for k in block if k not in GROWTH_KEYS)
    if unknown:
        raise _fault(at, f"has unknown keys {', '.join(unknown)}")
    if _number(block, "pace", at) <= 0:
        raise _fault(f"{at}.pace", "must be above 0")
    _whole(block, "cap", at, high=4)
    _whole(block, "cap_in_person", at, high=4)
    _number(block, "decay_mult", at)
    return dict(block)


def _span(spec: dict[str, Any], key: str, where: str) -> None:
    """`{<measure>: [low, high]}`: one measure, two numbers, low <= high."""
    value = spec.get(key)
    if not isinstance(value, dict) or len(value) != 1:
        raise _fault(f"{where}.{key}", "must be a mapping of one measure to [low, high]")
    (measure, bounds), = value.items()
    if (not isinstance(bounds, list) or len(bounds) != 2
            or not all(isinstance(b, (int, float)) and not isinstance(b, bool) and b >= 0 for b in bounds)
            or bounds[0] > bounds[1]):
        raise _fault(f"{where}.{key}.{measure}", f"must be [low, high], numbers with low <= high, not {bounds!r}")


def check_arc(name: str, spec: Any) -> dict[str, Any]:
    """One `arcs:` row's SHAPE (spec §5.3); its stage names are T9's check, its canon `reveal` `check_canon`."""
    where = f"arcs.{name}"
    if not isinstance(spec, dict):
        raise _fault(where, "must be a mapping")
    points = [k for k in ("at", "from") if k in spec]
    if len(points) != 1:
        raise _fault(where, "needs exactly one of at (a point) or from (a start)")
    _span(spec, points[0], where)
    moves = [k for k in ("beat", "each_day") if k in spec]
    if not moves:
        raise _fault(where, "needs beat or each_day")
    for key in moves:
        if not isinstance(spec[key], dict) or not spec[key]:
            raise _fault(f"{where}.{key}", "must be a non-empty mapping")
    return dict(spec)


def _arcs() -> dict[str, Any]:
    arcs = social.data("behaviours").get("arcs") or {}
    if not isinstance(arcs, dict):
        raise _fault("arcs", "must be a mapping")
    return arcs


def archetype(name: str) -> Archetype:
    """The archetype `name` of the active story; a `ValueError` naming behaviours.yaml and the key."""
    rows = social.data("behaviours").get("archetypes") or {}
    if not isinstance(rows, dict) or name not in rows:
        raise _fault(f"archetypes.{name}", "no such archetype")
    return build_archetype(name, rows[name], _arcs())


def arc_spec(name: str) -> dict[str, Any]:
    """The arc `name`, its shape checked (drawing its point and its beat are T9's)."""
    arcs = _arcs()
    if name not in arcs:
        raise _fault(f"arcs.{name}", "no such arc")
    return check_arc(name, arcs[name])


#: A canon row's longest text: a `shared` fact's cap (spec §11.2).
CANON_TEXT_MAX = 140


def check_canon(data: dict[str, Any]) -> dict[str, str]:
    """
    The `canon:` table (spec §12.1, v0.22.0 T12): id -> one fact in prose,
    non-empty, at most CANON_TEXT_MAX characters; and every arc beat's
    `reveal` names a row. A ValueError naming behaviours.yaml and the key.
    """
    rows = data.get("canon") or {}
    if not isinstance(rows, dict):
        raise _fault("canon", "must be a mapping of canon id to its text")
    for key, text in rows.items():
        if not isinstance(text, str) or not text.strip() or len(text) > CANON_TEXT_MAX:
            raise _fault(f"canon.{key}", f"must be a fact in prose of 1-{CANON_TEXT_MAX} characters")
    arcs = data.get("arcs") if isinstance(data.get("arcs"), dict) else {}
    for name, spec in arcs.items():
        beat = spec.get("beat") if isinstance(spec, dict) else None
        reveal = beat.get("reveal") if isinstance(beat, dict) else None
        if reveal is not None and str(reveal) not in rows:
            raise _fault(f"arcs.{name}.beat.reveal", f"{reveal!r} is no canon row")
    return {str(k): str(v) for k, v in rows.items()}


def canon_text(row_id: str) -> str:
    """A canon row's text (an arc's `reveal`); a ValueError naming behaviours.yaml when there is none."""
    rows = social.data("behaviours").get("canon") or {}
    if not isinstance(rows, dict) or row_id not in rows:
        raise _fault(f"canon.{row_id}", "no such canon row")
    return str(rows[row_id])


# -- the week -----------------------------------------------------------------


def _week(shape: str) -> dict[str, list[Any]]:
    schedules = social.data("population").get("schedules") or {}
    week = schedules.get(shape) if isinstance(schedules, dict) else None
    if not isinstance(week, dict):
        raise ValueError(f"social: population.yaml: schedules.{shape}: no such job shape")
    return week


def weekday_of(absolute_hour: float) -> str:
    return WEEKDAYS[int(absolute_hour // 24) % 7]


def status_at(person: Any, absolute_hour: float) -> str:
    """`asleep | work | free | out` for `person` at an absolute in-game hour. Derived; draws nothing."""
    week = _week(person.job_shape)
    hour = absolute_hour % 24
    for start, end, status in week.get(weekday_of(absolute_hour)) or []:
        if start <= hour < end:
            return str(status)
    return "asleep"


def next_awake(person: Any, absolute_hour: float) -> float:
    """`absolute_hour` itself when awake, else the start of their next waking band."""
    if status_at(person, absolute_hour) != "asleep":
        return float(absolute_hour)
    week = _week(person.job_shape)
    first_day = int(absolute_hour // 24)
    for day in range(first_day, first_day + 8):
        for start, _end, status in sorted(week.get(WEEKDAYS[day % 7]) or [], key=lambda band: band[0]):
            at = day * 24.0 + float(start)
            if at > absolute_hour and status != "asleep":
                return at
    raise ValueError(f"social: population.yaml: schedules.{person.job_shape}: a week with no waking hour")


# -- draws ----------------------------------------------------------------------


def person_rng(state: GameState, stream: str, pid: str) -> random.Random:
    """One draw on ``stream`` for ``pid``: its own counter in people[pid]["rng_n"][stream]."""
    person = state.social["people"].setdefault(pid, {})
    counters = person.setdefault("rng_n", {})
    n = int(counters.get(stream, 0)) + 1
    counters[stream] = n
    return stable_rng(state.rng_seed, f"{stream}:{pid}:{n}")


def lognormal_minutes(rng: random.Random, median: float, spread: float) -> float:
    """A lognormal latency in minutes around `median`, floored at half a minute (platform-neutral: detmath)."""
    return max(0.5, detmath.lognormal(rng, median, spread))
