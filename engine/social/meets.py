"""
Meet-ups (v0.22.0 spec §14): dates arranged through the phone, resolved by
the ENGINE, narrated afterwards by the model (rule 1).

**A meet** is a row in `state.social["meets"]` (`t<n>` ids, Plan decision 14):

    {id, pid, venue, day, slot, start, end, hours, status, by, agreed_at,
     flake, band, ended_at}

`day` is the in-game day it is on (1-based, as `state.world_day`); `start`
and `end` are absolute in-game hours (the slot's, relationships.yaml
`meets.slots`); `hours` is the venue's `duration_hours`. `status` is one of
these: `agreed` (planned), `due` (its start has come: go or cancel),
`going` (the clock is moving through it), `done` (resolved into a `band`),
`cancelled` (by the player, or called off: they left), `no_show` (no answer
by the slot's end) or `flaked` (they cancelled). `flake` (whether they will)
is drawn ONCE, when the meet is agreed, on SOCIAL_MEET (spec §14.2), and is
never shown before the start (the payload carries no `flake`).

**Proposing** (§14.1). The player's `propose_meet {pid, venue, day, slot}`
(`day` 1-7 days ahead) is answered at once by the engine: `accept` when the
gates hold (stage `numbers` or past it, relationships.yaml's `meeting`
gate) and both sides are free in that slot (their schedule; the player's
calendar), else `counter` (the nearest free slot that day or the next), else
`not_yet`. The player's `ask {what: meet}` and the person's `ask_meet`
proposal (§10.5) leave the venue and the slot to the engine (`pick`: a venue
by the hobbies they share, ties drawn on SOCIAL_MEET, and the first slot free
for both): the ask is answered at their next read, the proposal is a
request the player answers. An agreed meet moves `numbers` to `meeting`
(that stage's trigger is `meet`).

**The day** (§14.2). A `meet_start` event at the start (queued with no pid,
so a ghost's or an ending's queue drop never strands a plan): a flake (or a
person gone quiet) is shown as an engine line and the meet is `flaked`;
else it is `due` and `wait` stops at it (turn.NOTIFYING), and a second
`meet_start` (`end: true`) at the slot's end makes a meet still `due` a
no-show (`meets.no_show`). `meet {go}` is legal only while `due`; `meet
{cancel}` while planned, at `cancel_cost`, larger the later.

**The outcome** (§14.3). `go` moves the clock through the venue's
`duration_hours` (`clock.advance_time`, from the phone action, never from a
handler, rule 2), then the `social_meet` effect resolves it: `quality`, one
SOCIAL_MEET draw, banded by `band`; the band's `effects` (exact regard), a
history row, `meets_good` for a `good`-or-better band (two move `meeting`
to its branch, §10.3), the recap as a due system card (`kind: recap`), and
-- unless the band or their archetype is in `post_meet`'s lists -- their
`post_meet` text at their pace.

**The recap** (§14.4). Voiced by the voicing pass (engine/social/voicer.py
calls `voice_recap`, not `voicing.voice`): one bare call with
`prompts/date_recap.md` verbatim and five blocks (`recap_messages`, pinned
by test_the_recap_prompt_is_exactly_its_blocks). A recap whose words
contradict the band (`meets.recap_tone`, matched only: how it WENT, never
register, rule 12) is retried once, else the engine's line ("Coffee at The
Copper Kettle with Kai. It was a little awkward.").

Every number is the data's (relationships.yaml `meets:`, venues.yaml; rule
10, unmeasured until T26); every write is the `social_meet` effect or
happens inside a `social_*` handler (rule 3).
"""

from __future__ import annotations

import copy
import dataclasses
import logging
import re
from typing import Any, Optional, Sequence

from engine import social
from engine.game import clock
from engine.game.effects import EffectContext, apply_effect, effect_kind
from engine.game.intents import IntentVerb
from engine.game.rng import SOCIAL_MEET, SOCIAL_PACE
from engine.game.state import GameState
from engine.social import agreement, apps, behaviour, events, matching, messaging, population, relationships
from engine.social.intents import ArgSpec, phone_verb
from engine.social.kinds import Decision, recorded, stage_rank
from engine.social.payload import section
from engine.social.turn import cost_hours

logger = logging.getLogger(__name__)

#: The bands a meet resolves into, best first (relationships.yaml `meets.bands` holds all but the last).
BANDS: tuple[str, ...] = ("great", "good", "fine", "awkward", "bad")
#: The bands that count toward the branch from `meeting` (`meets_good`, spec §10.3).
GOOD_BANDS: tuple[str, ...] = ("great", "good")
#: What `meet` does with a due meet (§7.1).
DOS: tuple[str, ...] = ("go", "cancel")
#: A request's `what` for a meet-up: the player's `ask {what: meet}`, the person's `ask_meet`.
REQUEST = "meet"
#: The person's proposal (§10.5).
PROPOSAL = "ask_meet"
#: The engine's answer for a person gone quiet (ghosted): none at all (T24 review I1).
UNANSWERED = "unanswered"
#: A recap's message kind and its decision's `kind` and `situation`.
RECAP = "recap"
#: The calendar app's kind (apps.yaml): its notifications.
CALENDAR_KIND = "calendar"
#: relationships.yaml `meets.quality` keys (all required).
QUALITY_KEYS: tuple[str, ...] = ("compat", "compat_scale", "chemistry", "warmth", "venue_hobby_bonus", "spread")
#: What a band's `effects` row may move.
EFFECT_MOVES: tuple[str, ...] = ("warmth", "trust", "interest", "mood")
#: The tone lists a recap is checked against (`meets.recap_tone`).
TONES: tuple[str, ...] = ("glowing", "grim")
#: Every key of a venues.yaml row.
VENUE_KEYS: tuple[str, ...] = ("id", "label", "neighbourhood", "kind", "hobbies", "duration_hours")
#: The fewest venues a story with meet-ups ships (the brief's twelve).
MIN_VENUES = 12
#: The recap's word cap (§14.4).
RECAP_WORDS = 120
#: The recap prompt's user blocks, in order (§11.6).
RECAP_BLOCKS: tuple[str, ...] = ("WHO", "WHERE", "HOW IT WENT", "TOPICS", "FORMAT")
#: The recap prompt's system message, verbatim from the story's prompts.
RECAP_FILE = "date_recap.md"
#: The retry line after a recap with no words.
RECAP_ONLY = "Reply with the recap only, as plain text."
#: A recap's failure that is not its band's: it held no words, or the call failed.
EMPTY = "empty"


def _no(reason: str) -> dict[str, Any]:
    return {"ok": False, "error": reason}


def _name(state: GameState, pid: str) -> str:
    return matching._name(state, pid)


def _fault(source: str, key: str, message: str) -> ValueError:
    return ValueError(f"social: {source}: {key}: {message}")


def _num(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


# -- the data (relationships.yaml `meets:`, venues.yaml; rule 10) ---------------------------------


def _rules() -> dict[str, Any]:
    rules = social.data("relationships").get("meets")
    if not isinstance(rules, dict):
        raise _fault("relationships.yaml", "meets", "required for meet-ups (spec §14.3)")
    return rules


def meet_faults(venues_data: dict[str, Any], relationships_data: dict[str, Any],
                population_data: Optional[dict[str, Any]] = None) -> list[tuple[str, str, str]]:
    """
    Every fault of the meet-up data as (file, key, message): relationships.yaml's `meets:` block whole,
    venues.yaml's kinds and venues (twelve or more, each with every key; its neighbourhood and hobbies
    population.yaml ids when that is given). A story with neither has no meet-ups and no fault.
    """
    out: list[tuple[str, str, str]] = []
    rules = (relationships_data or {}).get("meets")
    if not venues_data and rules is None:
        return out
    rsrc, vsrc = "relationships.yaml", "venues.yaml"
    if not isinstance(rules, dict):
        return [(rsrc, "meets", "required beside venues.yaml (spec §14.3)")]
    slots = rules.get("slots")
    if not isinstance(slots, dict) or not slots:
        out.append((rsrc, "meets.slots", "must map slot ids to [start, end] hours"))
    else:
        for name, span in slots.items():
            if not (isinstance(span, list) and len(span) == 2 and all(_num(v) for v in span)
                    and 0 <= span[0] < span[1] <= 24):
                out.append((rsrc, f"meets.slots.{name}", "must be [start, end], hours with 0 <= start < end <= 24"))
    ahead = rules.get("days_ahead")
    if not (isinstance(ahead, list) and len(ahead) == 2 and all(isinstance(v, int) and not isinstance(v, bool)
                                                                for v in ahead) and 1 <= ahead[0] <= ahead[1]):
        out.append((rsrc, "meets.days_ahead", "must be [first, last], whole days with 1 <= first <= last"))
    quality = rules.get("quality") or {}
    for key in QUALITY_KEYS:
        if not _num(quality.get(key)):
            out.append((rsrc, f"meets.quality.{key}", "required: a number"))
    if _num(quality.get("spread")) and quality["spread"] < 0:
        out.append((rsrc, "meets.quality.spread", "must be 0 or more"))
    bands = rules.get("bands")
    if not isinstance(bands, dict) or list(bands) != list(BANDS[:-1]) or not all(_num(v) for v in bands.values()):
        out.append((rsrc, "meets.bands", f"must give {', '.join(BANDS[:-1])} each a least quality, in that order"))
    elif any(a <= b for a, b in zip(list(bands.values()), list(bands.values())[1:])):
        out.append((rsrc, "meets.bands", "must fall band by band, best first"))
    moods = ((relationships_data.get("mood") or {}).get("values") or ()) if isinstance(relationships_data, dict) else ()
    effects = rules.get("effects")
    if not isinstance(effects, dict) or set(effects) != set(BANDS):
        out.append((rsrc, "meets.effects", f"must give each of {', '.join(BANDS)} a row"))
    else:
        for name, row in effects.items():
            out.extend(_moves_faults(rsrc, f"meets.effects.{name}", row, moods))
    costs = rules.get("cancel_cost")
    if not isinstance(costs, list) or not costs:
        out.append((rsrc, "meets.cancel_cost", "must be a list of {within_hours?, warmth, interest} rows"))
    else:
        last = -1.0
        for i, row in enumerate(costs):
            where = f"meets.cancel_cost[{i}]"
            out.extend(_moves_faults(rsrc, where, row, moods, required=("warmth", "interest")))
            within = row.get("within_hours") if isinstance(row, dict) else None
            if i < len(costs) - 1:
                if not _num(within) or within <= last:
                    out.append((rsrc, f"{where}.within_hours", "required, rising row by row (the last row has none)"))
                else:
                    last = float(within)
            elif within is not None:
                out.append((rsrc, f"{where}.within_hours", "the last row has none: it covers any earlier cancel"))
    out.extend(_moves_faults(rsrc, "meets.no_show", rules.get("no_show"), moods, required=("warmth", "interest")))
    post = rules.get("post_meet") or {}
    if not _num(post.get("pace_mult")) or post["pace_mult"] <= 0:
        out.append((rsrc, "meets.post_meet.pace_mult", "required: a number above 0"))
    if not set(post.get("none_after") or ()) <= set(BANDS):
        out.append((rsrc, "meets.post_meet.none_after", f"must list bands ({', '.join(BANDS)})"))
    if not isinstance(post.get("none_from") or [], list):
        out.append((rsrc, "meets.post_meet.none_from", "must list archetypes"))
    lines = rules.get("recap_lines") or {}
    for name in BANDS:
        if not isinstance(lines.get(name), str) or not lines[name].strip():
            out.append((rsrc, f"meets.recap_lines.{name}", "required: the engine's words for how it went"))
    tone = rules.get("recap_tone") or {}
    for name in TONES:
        value = tone.get(name)
        if not isinstance(value, list) or not all(isinstance(p, str) and p.strip() for p in value):
            out.append((rsrc, f"meets.recap_tone.{name}", "must be a list of phrases"))
    contradicts = tone.get("contradicts") or {}
    for name in BANDS:
        if not set(contradicts.get(name) or ()) <= set(TONES):
            out.append((rsrc, f"meets.recap_tone.contradicts.{name}", f"must list tones ({', '.join(TONES)})"))
    out.extend(_venue_faults(venues_data or {}, population_data))
    return out


def _moves_faults(source: str, where: str, row: Any, moods: Sequence[str],
                  required: tuple[str, ...] = ("warmth", "trust", "interest")) -> list[tuple[str, str, str]]:
    if not isinstance(row, dict):
        return [(source, where, "must be a mapping of warmth, trust, interest and mood")]
    out = []
    for key, value in row.items():
        if key == "within_hours":
            continue
        if key not in EFFECT_MOVES:
            out.append((source, f"{where}.{key}", f"is not one of {', '.join(EFFECT_MOVES)}"))
        elif key == "mood":
            if moods and value not in moods:
                out.append((source, f"{where}.mood", f"{value!r} is no mood value"))
        elif not isinstance(value, int) or isinstance(value, bool):
            out.append((source, f"{where}.{key}", "must be a whole number"))
    for key in required:
        if key not in row:
            out.append((source, f"{where}.{key}", "required"))
    return out


def _venue_faults(data: dict[str, Any], population_data: Optional[dict[str, Any]]) -> list[tuple[str, str, str]]:
    src = "venues.yaml"
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
    places = {str(r.get("id")) for r in (population_data or {}).get("neighbourhoods") or () if isinstance(r, dict)}
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
        if places and row["neighbourhood"] not in places:
            out.append((src, f"{where}.neighbourhood", f"{row['neighbourhood']!r} is no population.yaml neighbourhood"))
        if not isinstance(row["hobbies"], list) or (hobbies and not set(row["hobbies"]) <= hobbies):
            out.append((src, f"{where}.hobbies", "must list population.yaml hobby ids"))
        if not _num(row["duration_hours"]) or not 0 < row["duration_hours"] <= 12:
            out.append((src, f"{where}.duration_hours", "must be hours, above 0 and at most 12"))
    return out


def check_data(venues_data: dict[str, Any], relationships_data: dict[str, Any],
               population_data: Optional[dict[str, Any]] = None) -> None:
    """The meet-up data whole, at load: the first fault a ValueError naming its file and key."""
    faults = meet_faults(venues_data, relationships_data, population_data)
    if faults:
        raise _fault(*faults[0])


def venues() -> list[dict[str, Any]]:
    return [r for r in social.data("venues").get("venues") or () if isinstance(r, dict)]


def venue(venue_id: str) -> dict[str, Any]:
    """A venues.yaml row by id; {} for none."""
    return next((r for r in venues() if r.get("id") == venue_id), {})


def venue_ids() -> tuple[str, ...]:
    return tuple(str(r["id"]) for r in venues())


def place_line(venue_id: str) -> str:
    """The engine's words for a meet-up at `venue_id`: "Coffee at The Copper Kettle"."""
    row = venue(venue_id)
    kind = (social.data("venues").get("kinds") or {}).get(row.get("kind")) or {}
    label = str(row.get("label") or venue_id)
    if not kind:
        return label
    return f"{kind['label']} {kind['at']} {label}"


def recap_line(band_name: str) -> str:
    """The engine's words for how a meet-up went ("It was a little awkward.")."""
    return str((_rules().get("recap_lines") or {}).get(band_name) or "")


def slots() -> dict[str, tuple[float, float]]:
    """Slot id -> (start, end) hours of the day, in the data's order."""
    return {str(k): (float(v[0]), float(v[1])) for k, v in (_rules().get("slots") or {}).items()}


def days_ahead() -> tuple[int, int]:
    first, last = _rules().get("days_ahead") or (1, 7)
    return int(first), int(last)


def _meet_stage() -> str:
    """The stage an agreed meet moves to (relationships.yaml: the one whose trigger is `meet`)."""
    for name, row in (social.data("relationships").get("stages") or {}).items():
        if isinstance(row, dict) and row.get("trigger") == "meet":
            return str(name)
    raise _fault("relationships.yaml", "stages", "no stage has trigger meet (spec §10.3)")


def _from_rank() -> int:
    """How far along a person must be to meet: the meet stage's `from` (numbers)."""
    row = (social.data("relationships").get("stages") or {}).get(_meet_stage()) or {}
    return min((stage_rank(s) for s in row.get("from") or ()), default=0)


# -- reading the rows ----------------------------------------------------------------------------


def _meets(state: GameState) -> dict[str, Any]:
    return state.social.get("meets") or {}


def get(state: GameState, meet_id: str) -> Optional[dict[str, Any]]:
    return _meets(state).get(meet_id)


def _ordered(rows: Any) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda r: (float(r.get("start") or 0.0), int(str(r["id"])[1:] or 0)))


def planned(state: GameState, pid: Optional[str] = None) -> list[dict[str, Any]]:
    """Meets still on (`agreed` or `due`), soonest first; only `pid`'s when given."""
    return _ordered(r for r in _meets(state).values()
                    if r.get("status") in agreement.PLANNED and (pid is None or r.get("pid") == pid))


def _person(state: GameState, pid: str) -> dict[str, Any]:
    return (state.social.get("people") or {}).get(pid) or {}


def _pending_request(state: GameState, pid: str) -> Optional[dict[str, Any]]:
    """`pid`'s open meet request either way; theirs only while it can still be met (`still_open`)."""
    for r in (state.social.get("requests") or {}).values():
        if (r["pid"] == pid and r["what"] == REQUEST and r["status"] in ("pending", "later")
                and (r["from"] == "player" or still_open(state, r))):
            return r
    return None


# -- time and who is free --------------------------------------------------------------------------


def slot_start(day: int, slot: str) -> float:
    return (int(day) - 1) * 24.0 + slots()[slot][0]


def slot_end(day: int, slot: str) -> float:
    return (int(day) - 1) * 24.0 + slots()[slot][1]


def when_words(row: dict[str, Any]) -> str:
    """ "Fri 14:00" for a meet row (or anything with a `start`)."""
    start = float(row.get("start") or 0.0)
    minutes = int(round(start * 60)) % (24 * 60)
    return f"{behaviour.weekday_of(start).title()} {minutes // 60:02d}:{minutes % 60:02d}"


def person_free(state: GameState, pid: str, start: float, hours: float) -> bool:
    """`pid` is free or out (not at work, not asleep) at the start, the middle and the end of a meet."""
    person = population.profile(state, pid)
    points = (start, start + hours / 2.0, start + max(0.0, hours - 1.0 / 60.0))
    return all(behaviour.status_at(person, at) in messaging.FREE for at in points)


def player_free(state: GameState, start: float, hours: float) -> bool:
    """No planned meet of the player's overlaps [start, start + hours)."""
    end = start + hours
    return not any(float(r["start"]) < end and start < float(r["start"]) + float(r["hours"])
                   for r in planned(state))


def slot_free(state: GameState, pid: str, day: int, slot: str, hours: float) -> bool:
    start = slot_start(day, slot)
    return (start > state.world_clock_hours and person_free(state, pid, start, hours)
            and player_free(state, start, hours))


def _ahead(state: GameState, day: int) -> int:
    return int(day) - int(state.world_day)


def counter_view(state: GameState, pid: str, counter: dict[str, Any]) -> dict[str, Any]:
    """
    A counter-offer line's `counter` as the player sees it (T30 follow-up): the venue, the slot, the day
    as days ahead (what `propose_meet` takes), its words, and `open` -- whether proposing it now would be
    taken: the day still in range, the venue known, no refusal, and the slot still free. A hint only;
    `propose_meet` decides again (rule 1).
    """
    venue_id, slot = str(counter.get("venue") or ""), str(counter.get("slot") or "")
    day = int(counter.get("day") or 0)
    ahead = _ahead(state, day)
    first, last = days_ahead()
    row = venue(venue_id)
    open_ = (bool(row) and slot in slots() and first <= ahead <= last and not propose_refusal(state, pid)
             and slot_free(state, pid, day, slot, float(row.get("duration_hours") or 0)))
    return {"venue": venue_id, "slot": slot, "days_ahead": ahead,
            "when": when_words({"start": slot_start(day, slot)}), "open": open_}


def nearest_free(state: GameState, pid: str, day: int, slot: str, hours: float) -> Optional[tuple[int, str]]:
    """The free slot nearest the one asked for, on that day or the next (inside `days_ahead`), else None."""
    first, last = days_ahead()
    wanted = slot_start(day, slot)
    options = [(d, s) for d in (day, day + 1) for s in slots()
               if (d, s) != (day, slot) and first <= _ahead(state, d) <= last]
    options.sort(key=lambda o: (abs(slot_start(*o) - wanted), slot_start(*o)))
    return next((o for o in options if slot_free(state, pid, o[0], o[1], hours)), None)


def first_free(state: GameState, pid: str, hours: float) -> Optional[tuple[int, str]]:
    """The first slot free for both, from `days_ahead`'s first day on (an engine-picked meet)."""
    first, last = days_ahead()
    for ahead in range(first, last + 1):
        for slot in slots():
            if slot_free(state, pid, state.world_day + ahead, slot, hours):
                return state.world_day + ahead, slot
    return None


def gate_open(state: GameState, pid: str) -> bool:
    """Stage `numbers` or past it, live, and relationships.yaml's `meeting` gate (§10.3, §14.1)."""
    stage = _person(state, pid).get("stage")
    return (stage_rank(stage) >= _from_rank() and relationships.live(_person(state, pid))
            and stage != "winding_down" and relationships.gate_holds(state, pid, _meet_stage()))


def pick_venue(state: GameState, pid: str) -> str:
    """
    A venue for an engine-picked meet (§10.5's `ask_meet`, the player's `ask {what: meet}`): those
    whose hobbies both hold, else theirs, else any; ties drawn once on SOCIAL_MEET (call inside a
    `social_*` handler: the draw's counter is state, rule 3).
    """
    person = population.profile(state, pid)
    mine = set((state.social.get("player") or {}).get("hobbies") or ())
    theirs = set(person.hobbies)
    rows = venues()
    for pool in ([r for r in rows if set(r["hobbies"]) & mine & theirs],
                 [r for r in rows if set(r["hobbies"]) & theirs], rows):
        if pool:
            ids = sorted(str(r["id"]) for r in pool)
            return ids[0] if len(ids) == 1 else behaviour.person_rng(state, SOCIAL_MEET, pid).choice(ids)
    raise _fault("venues.yaml", "venues", "no venue to meet at")


# -- the outcome --------------------------------------------------------------------------------------


def quality(state: GameState, meet: dict[str, Any]) -> float:
    """A meet's quality (§14.3): one SOCIAL_MEET draw (call inside a `social_*` handler, rule 3)."""
    q = _rules()["quality"]
    person = population.profile(state, meet["pid"])
    dyn = state.social["people"][meet["pid"]]
    place = venue(meet["venue"])
    shared = bool(set(place.get("hobbies") or []) & set(person.hobbies)
                  & set(state.social["player"].get("hobbies") or []))
    rng = behaviour.person_rng(state, SOCIAL_MEET, meet["pid"])
    return (float(q["compat"]) * matching.compatibility(state.social["player"], person) * float(q["compat_scale"])
            + float(q["chemistry"]) * person.chemistry
            + float(q["warmth"]) * float(dyn.get("warmth", 0))
            + (float(q["venue_hobby_bonus"]) if shared else 0.0)
            + rng.gauss(0.0, float(q["spread"])))


def band(q: float) -> str:
    """The first of great, good, fine, awkward whose least quality `q` reaches, else `bad`."""
    for name, least in (_rules().get("bands") or {}).items():
        if q >= float(least):
            return str(name)
    return BANDS[-1]


def cancel_cost(hours_before: float) -> dict[str, Any]:
    """What cancelling `hours_before` the start costs (`meets.cancel_cost`'s first matching row)."""
    rows = _rules()["cancel_cost"]
    for row in rows:
        if row.get("within_hours") is None or float(hours_before) <= float(row["within_hours"]):
            return {k: v for k, v in row.items() if k in EFFECT_MOVES}
    return {k: v for k, v in rows[-1].items() if k in EFFECT_MOVES}


def _moved(state: GameState, pid: str, moves: dict[str, Any], at: float) -> None:
    """An engine move of regard (exact: the engine's own, past every cap), inside a handler."""
    moves = {k: v for k, v in (moves or {}).items() if k in EFFECT_MOVES}
    if moves:
        apply_effect(state, {"type": "social_regard", "pid": pid, "exact": True, "at": at, **moves})


def _post_meet_skipped(state: GameState, pid: str, band_name: str) -> bool:
    post = _rules()["post_meet"]
    return (band_name in (post.get("none_after") or ())
            or population.profile(state, pid).archetype in (post.get("none_from") or ()))


def _their_pace(state: GameState, pid: str, at: float) -> float:
    person = population.profile(state, pid)
    arch = behaviour.archetype(person.archetype)
    minutes = behaviour.lognormal_minutes(behaviour.person_rng(state, SOCIAL_PACE, pid), *arch.reply_minutes)
    due = at + minutes * float(_rules()["post_meet"]["pace_mult"]) / 60.0
    return behaviour.next_awake(person, due) if behaviour.status_at(person, due) == "asleep" else due


def _calendar_app() -> str:
    for name, row in (social.data("apps").get("apps") or {}).items():
        if isinstance(row, dict) and row.get("kind") == CALENDAR_KIND:
            return str(name)
    return ""


def _line(state: GameState, pid: str, text: str, at: float,
          extra: Optional[dict[str, Any]] = None) -> None:
    """An engine line in the person's thread (inside a handler only)."""
    tid = messaging.thread_for(state, pid)
    t = messaging.thread(state, tid) if tid else None
    if t is not None:
        matching._system_message(state, t, text, at, extra)


# -- the effect (rule 3) --------------------------------------------------------------------------------


def _trim(state: GameState) -> None:
    """Bounded state (spec §17.2): meets over and done past `social.meets_kept` leave, oldest first."""
    rows = _meets(state)
    over = sorted((r for r in rows.values() if r.get("status") not in agreement.PLANNED + ("going",)),
                  key=lambda r: (float(r.get("ended_at") or r.get("start") or 0.0), int(str(r["id"])[1:] or 0)))
    keep = int(social.setting("meets_kept", 20))
    for row in over[:max(0, len(over) - keep)]:
        del rows[row["id"]]


def _count_ask(state: GameState, pid: str) -> None:
    """One player ask of a meet-up today (§10.6's pacing, the `asks_today` count `social_request` keeps)."""
    person_state = state.social.setdefault("people", {}).setdefault(pid, {})
    asked = person_state.get("asks_today")
    if not isinstance(asked, dict) or asked.get("day") != state.world_day:
        asked = person_state["asks_today"] = {"day": state.world_day}
    asked[REQUEST] = int(asked.get(REQUEST, 0)) + 1


def _agree(state: GameState, effect: dict[str, Any], at: float) -> dict[str, Any]:
    pid, venue_id, slot = str(effect["pid"]), str(effect["venue"]), str(effect["slot"])
    day = int(effect["day"])
    counters = state.social.setdefault("counters", {})
    counters["meet"] = int(counters.get("meet", 0)) + 1
    mid = f"t{counters['meet']}"
    arch = behaviour.archetype(population.profile(state, pid).archetype)
    flake = behaviour.person_rng(state, SOCIAL_MEET, pid).random() < float(arch.flake_prob)
    row = {"id": mid, "pid": pid, "venue": venue_id, "day": day, "slot": slot,
           "start": slot_start(day, slot), "end": slot_end(day, slot),
           "hours": float(venue(venue_id)["duration_hours"]), "status": "agreed",
           "by": str(effect.get("by") or "player"), "agreed_at": at, "flake": flake, "band": None, "ended_at": None}
    state.social.setdefault("meets", {})[mid] = row
    person_state = state.social.setdefault("people", {}).setdefault(pid, {})
    relationships.touch(person_state)
    events.push(state, row["start"], "", "meet_start", meet_id=mid)
    target = _meet_stage()
    if relationships.can_reach(state, pid, target):
        relationships.set_stage(state, pid, target, at=at)
    _line(state, pid, f"{_name(state, pid)} is in: {place_line(venue_id)}, {when_words(row)}.", at)
    return {"type": "social_meet", "ok": True, "text": f"agreed {mid}", "meet_id": mid, "save_reason": "stage"}


@effect_kind("social_meet")
@recorded
def _e_meet(state: GameState, effect: dict[str, Any], ctx: EffectContext) -> dict[str, Any]:
    """
    Engine-only: a meet row's change (spec §14). `op: propose` (the player's proposal and the
    engine's answer, an `agree` with it on `accept`), `agree` (a new row: the flake drawn, its
    `meet_start` queued, `numbers` moved to `meeting`), `start` / `end` (its events), `go`,
    `resolve` (the band and all that follows), `cancel` (by the player, at `cost`).
    """
    if not state.social:
        return {"type": "social_meet", "ok": False, "text": "no social slice"}
    op = str(effect.get("op") or "")
    at = float(effect["at"]) if effect.get("at") is not None else state.world_clock_hours
    if op == "propose":
        pid = str(effect["pid"])
        _count_ask(state, pid)
        relationships.touch(state.social.setdefault("people", {}).setdefault(pid, {}))
        tid = str(effect.get("thread_id") or "")
        if tid:
            apply_effect(state, {"type": "social_message", "thread_id": tid, "from": "player", "kind": "request",
                                 "bubbles": [], "ask": REQUEST, "at": at})
        answer = str(effect.get("answer") or "")
        if answer == "accept":
            made = _agree(state, {**effect, "by": "player"}, at)
            return {**made, "answer": answer}
        name = _name(state, pid)
        if answer == UNANSWERED:
            return {"type": "social_meet", "ok": True, "text": f"{pid}: no answer", "answer": answer}
        if answer == "counter":
            day, slot = int(effect["counter_day"]), str(effect["counter_slot"])
            # The line carries the counter, so the player can take it in one tap (T30 follow-up).
            _line(state, pid, f"{name} can't make that. {when_words({'start': slot_start(day, slot)})} works.", at,
                  {"counter": {"venue": str(effect.get("venue") or ""), "day": day, "slot": slot}})
        else:
            _line(state, pid, f"{name} isn't ready to meet up yet.", at)
        return {"type": "social_meet", "ok": True, "text": f"{pid}: {answer}", "answer": answer}
    if op == "agree":
        return _agree(state, effect, at)
    if op == "lapse":
        return _lapse(state, str(effect.get("request_id") or ""), at)
    if op == "pick":
        # The engine picks a meet for them (their `ask_meet`, the player's `ask {what: meet}`): the
        # venue (a SOCIAL_MEET draw for ties, a state write) and the first slot free for both.
        pid = str(effect["pid"])
        venue_id = pick_venue(state, pid)
        found = first_free(state, pid, float(venue(venue_id)["duration_hours"]))
        relationships.touch(state.social.setdefault("people", {}).setdefault(pid, {}))
        if found is None:
            return {"type": "social_meet", "ok": False, "text": f"no slot free for {pid}"}
        return {"type": "social_meet", "ok": True, "text": f"picked {venue_id}", "venue": venue_id,
                "day": found[0], "slot": found[1]}
    row = _meets(state).get(str(effect.get("meet_id") or ""))
    if row is None:
        return {"type": "social_meet", "ok": False, "text": f"no meet {effect.get('meet_id')!r}"}
    mid, pid = str(row["id"]), str(row["pid"])
    person_state = state.social.setdefault("people", {}).setdefault(pid, {})
    name = _name(state, pid)
    if op == "start":
        if row["status"] != "agreed":
            return {"type": "social_meet", "ok": False, "text": f"{mid} is {row['status']}"}
        if apps.gone(state, pid) or not relationships.live(person_state):
            row.update(status="cancelled", ended_at=at)
            _trim(state)
            return {"type": "social_meet", "ok": True, "text": f"{mid} called off", "status": "cancelled"}
        tid = messaging.thread_for(state, pid) or ""
        if row.get("flake") or person_state.get("ghosted"):
            row.update(status="flaked", ended_at=at)
            relationships.add_history(state, pid, "flaked", f"{name} cancelled {place_line(row['venue'])}", at=at)
            _line(state, pid, f"{name} cancelled.", at)
            messaging.notify(state, _calendar_app(), tid, pid, "meet_flaked", f"{name} cancelled", at=at)
            _trim(state)
            return {"type": "social_meet", "ok": True, "text": f"{mid} flaked", "status": "flaked"}
        row["status"] = "due"
        events.push(state, row["end"], "", "meet_start", meet_id=mid, end=True)
        messaging.notify(state, _calendar_app(), tid, pid, "meet_start",
                         f"{place_line(row['venue'])} with {name}, {when_words(row)}", at=at)
        return {"type": "social_meet", "ok": True, "text": f"{mid} due", "status": "due"}
    if op == "end":
        if row["status"] != "due":
            return {"type": "social_meet", "ok": False, "text": f"{mid} is {row['status']}"}
        row.update(status="no_show", ended_at=at)
        _moved(state, pid, _rules()["no_show"], at)
        relationships.add_history(state, pid, "no_show", f"You didn't turn up to {place_line(row['venue'])}", at=at)
        _line(state, pid, f"You didn't turn up. {name} waited.", at)
        place = place_line(row["venue"])
        messaging.notify(state, _calendar_app(), messaging.thread_for(state, pid) or "", pid, "meet_missed",
                         f"You missed {place[:1].lower()}{place[1:]} with {name}", at=at)
        _trim(state)
        return {"type": "social_meet", "ok": True, "text": f"{mid} no-show", "status": "no_show"}
    if op == "go":
        if row["status"] != "due":
            return {"type": "social_meet", "ok": False, "text": f"{mid} is {row['status']}"}
        row["status"] = "going"
        relationships.touch(person_state)
        return {"type": "social_meet", "ok": True, "text": f"{mid} going", "status": "going"}
    if op == "resolve":
        if row["status"] != "going":
            return {"type": "social_meet", "ok": False, "text": f"{mid} is {row['status']}"}
        return _resolve(state, row, at)
    if op == "cancel":
        if row["status"] not in agreement.PLANNED:
            return {"type": "social_meet", "ok": False, "text": f"{mid} is {row['status']}"}
        row.update(status="cancelled", ended_at=at)
        _moved(state, pid, dict(effect.get("cost") or {}), at)
        relationships.add_history(state, pid, "cancelled", f"You cancelled {place_line(row['venue'])}", at=at)
        _line(state, pid, f"You cancelled {place_line(row['venue'])}.", at)
        _trim(state)
        return {"type": "social_meet", "ok": True, "text": f"{mid} cancelled", "status": "cancelled"}
    return {"type": "social_meet", "ok": False, "text": f"{op!r} is no meet op"}


def _resolve(state: GameState, row: dict[str, Any], at: float) -> dict[str, Any]:
    """The meet's band and all it moves (inside `social_meet`): §14.3-14.4."""
    mid, pid = str(row["id"]), str(row["pid"])
    person_state = state.social["people"][pid]
    got = band(quality(state, row))
    row.update(status="done", band=got, ended_at=at)
    if got in GOOD_BANDS:
        person_state["meets_good"] = int(person_state.get("meets_good", 0)) + 1
    relationships.touch(person_state)
    _moved(state, pid, (_rules()["effects"] or {}).get(got) or {}, at)
    relationships.add_history(state, pid, "meet", f"{place_line(row['venue'])}: {recap_line(got)}", at=at)
    relationships.advance_stage(state, pid, at=at)             # two good-or-better: meeting -> its branch (§10.3)
    tid = messaging.thread_for(state, pid)
    if tid:
        messaging.new_message(state, tid, "system", RECAP, at=at, voiced=False, decision=dataclasses.asdict(
            Decision(situation=RECAP, kind=RECAP, max_bubbles=1, meet_id=mid)))
        if not _post_meet_skipped(state, pid, got) and not person_state.get("ghosted"):
            messaging.queue_due(state, pid, tid, Decision(situation="post_meet", meet_id=mid),
                                _their_pace(state, pid, at))
    _trim(state)
    return {"type": "social_meet", "ok": True, "text": f"{mid} went {got}", "status": "done", "band": got,
            "save_reason": "stage"}


def _lapse(state: GameState, request_id: str, at: float) -> dict[str, Any]:
    """
    Their meet request whose slot can no longer be met (passed, taken, the gate gone): answered `no` by
    the engine, at no cost, with an engine line (T24 review I2). Inside `social_meet` only.
    """
    request = (state.social.get("requests") or {}).get(request_id)
    if request is None or request.get("what") != REQUEST or request.get("status") not in ("pending", "later"):
        return {"type": "social_meet", "ok": False, "text": f"no open meet request {request_id!r}"}
    pid = str(request["pid"])
    apply_effect(state, {"type": "social_request", "op": "answer", "request_id": request_id, "status": "no",
                         "at": at})
    request["lapsed"] = True
    t = messaging.thread(state, messaging.thread_for(state, pid) or "")
    if (t is not None and matching.listed(t) and not apps.gone(state, pid)
            and _person(state, pid).get("stage") != "ended"):   # nothing said in a thread they left (review M1)
        _line(state, pid, f"{_name(state, pid)}'s plan for {place_line(str(request.get('venue') or ''))} lapsed.",
              at)
    return {"type": "social_meet", "ok": True, "text": f"{request_id} lapsed"}


def call_off(state: GameState, pid: str, at: float) -> int:
    """
    `pid` left (unmatched, blocked or ended): every plan with them is called off at no cost, with an
    engine line, freeing the player's slot (T24 review M7). Called only inside a `social_*` handler (the
    unmatch's or the stage's), so the write is that effect's (rule 3). The number called off.
    """
    rows = planned(state, pid)
    for row in rows:
        row.update(status="cancelled", ended_at=at)
        _line(state, pid, f"Plans with {_name(state, pid)} are off: {place_line(str(row['venue']))}.", at)
    if rows:
        _trim(state)
    return len(rows)


def _lapse_stale(state: GameState) -> None:
    """Each morning (a `daily` step): their meet requests that can no longer be met lapse (`_lapse`)."""
    at = events.daily_at(state)
    for request in sorted((state.social.get("requests") or {}).values(), key=lambda r: int(str(r["id"])[1:] or 0)):
        if (request.get("what") == REQUEST and request.get("from") == "them"
                and request.get("status") in ("pending", "later") and not still_open(state, request)):
            apply_effect(state, {"type": "social_meet", "op": "lapse", "request_id": request["id"], "at": at})


if _lapse_stale not in events.daily_hooks:
    events.daily_hooks.append(_lapse_stale)


@events.handles("meet_start")
def _on_meet_start(state: GameState, event: dict[str, Any]) -> dict[str, Any]:
    """A meet's start (or, `end: true`, its slot's end): through `social_meet` (`start` / `end`); or, with a
    `request_id`, the start of the slot a request of theirs offered: it lapses if still unanswered."""
    if event.get("request_id"):
        request = (state.social.get("requests") or {}).get(str(event["request_id"])) or {}
        if request.get("status") not in ("pending", "later"):
            return {"ok": False, "why": "answered"}
        return apply_effect(state, {"type": "social_meet", "op": "lapse", "request_id": str(event["request_id"]),
                                    "at": float(event["at"])})
    op = "end" if event.get("end") else "start"
    return apply_effect(state, {"type": "social_meet", "op": op, "meet_id": str(event.get("meet_id") or ""),
                                "at": float(event["at"])})


# -- the player's actions ---------------------------------------------------------------------------------


def propose_refusal(state: GameState, pid: str) -> str:
    """Why the player cannot propose a meet-up to `pid` now, in the engine's words; "" when they can."""
    name = _name(state, pid)
    t = messaging.thread(state, messaging.thread_for(state, pid) or "")
    if apps.gone(state, pid) or t is None:
        return f"{name} is no longer available."
    if t.get("closed"):
        return messaging._closed_reason(state, t)
    person_state = _person(state, pid)
    if stage_rank(person_state.get("stage")) < _from_rank() or not relationships.live(person_state):
        return f"It's too soon to ask {name} to meet."
    if planned(state, pid):
        return f"You already have plans with {name}."
    waiting = _pending_request(state, pid)
    if waiting is not None:
        return (f"You've already asked {name} to meet." if waiting["from"] == "player"
                else f"{name} has already asked to meet.")
    if relationships.asks_today(state, pid, REQUEST) >= int(social.data("relationships")["asks"]["per_day"]):
        return relationships.GIVE_IT_A_DAY
    return ""


def propose(state: GameState, pid: str, venue_id: str, day: int, slot: str) -> dict[str, Any]:
    """
    The player's `propose_meet` (§14.1), `day` days ahead: answered at once by the engine -- `accept`
    (a Calendar row and a `meet_start` event), `counter` (the nearest free slot that day or the next)
    or `not_yet` -- then the message's minutes pass.
    """
    refusal = propose_refusal(state, pid)
    if refusal:
        return _no(refusal)
    first, last = days_ahead()
    if not venue(venue_id):
        return _no(f"There's no {venue_id} to meet at.")
    if slot not in slots():
        return _no(f"{slot} is no time to meet.")
    if not first <= int(day) <= last:
        return _no(f"Pick a day {first} to {last} days ahead.")
    tid = messaging.thread_for(state, pid) or ""
    on = state.world_day + int(day)
    hours = float(venue(venue_id)["duration_hours"])
    counter: Optional[tuple[int, str]] = None
    if _person(state, pid).get("ghosted"):
        answer = UNANSWERED                            # gone quiet: no answer, no row, no stage (T24 review I1)
    elif not gate_open(state, pid):
        answer = "not_yet"
    elif slot_free(state, pid, on, slot, hours):
        answer = "accept"
    else:
        counter = nearest_free(state, pid, on, slot, hours)
        answer = "counter" if counter is not None else "not_yet"
    effect: dict[str, Any] = {"type": "social_meet", "op": "propose", "pid": pid, "thread_id": tid,
                              "venue": venue_id, "day": on, "slot": slot, "answer": answer}
    if counter is not None:
        effect.update(counter_day=counter[0], counter_slot=counter[1])
    made = apply_effect(state, effect)
    if not made.get("ok"):
        return _no(str(made.get("text")))
    t = messaging.thread(state, tid)
    if t is not None:
        clock.advance_time(state, cost_hours(state, str(t["app"]), "text"))
    out: dict[str, Any] = {"ok": True, "pid": pid, "answer": answer}
    if made.get("meet_id"):
        out["meet_id"] = made["meet_id"]
    if counter is not None:
        out["counter"] = {"day": _ahead(state, counter[0]), "slot": counter[1]}
    return out


def go_refusal(state: GameState, row: Optional[dict[str, Any]]) -> str:
    """Why the player cannot go to `row` now; "" when it is due."""
    if row is None:
        return "There's no such meet-up."
    status = row.get("status")
    if status == "due":
        return ""
    if status == "agreed":
        return f"It isn't time yet: {place_line(row['venue'])} is {when_words(row)}."
    if status == "flaked":
        return f"{_name(state, str(row['pid']))} cancelled."
    return "That meet-up is over."


def go(state: GameState, meet_id: str) -> dict[str, Any]:
    """`meet {go}` (§14.3): the venue's duration through `clock.advance_time`, then the band resolved."""
    row = get(state, meet_id)
    refusal = go_refusal(state, row)
    if refusal:
        return _no(refusal)
    went = apply_effect(state, {"type": "social_meet", "op": "go", "meet_id": meet_id})
    if not went.get("ok"):
        return _no(str(went.get("text")))
    clock.advance_time(state, float(row["hours"]))
    made = apply_effect(state, {"type": "social_meet", "op": "resolve", "meet_id": meet_id})
    if not made.get("ok"):
        return _no(str(made.get("text")))
    return {"ok": True, "meet_id": meet_id, "pid": row["pid"], "band": made["band"]}


def cancel(state: GameState, meet_id: str) -> dict[str, Any]:
    """`meet {cancel}` (§14.2): at `cancel_cost`, larger the later, then the message's minutes."""
    row = get(state, meet_id)
    if row is None:
        return _no("There's no such meet-up.")
    if row.get("status") not in agreement.PLANNED:
        return _no(go_refusal(state, row) or "That meet-up is over.")
    cost = cancel_cost(float(row["start"]) - state.world_clock_hours)
    made = apply_effect(state, {"type": "social_meet", "op": "cancel", "meet_id": meet_id, "cost": cost})
    if not made.get("ok"):
        return _no(str(made.get("text")))
    t = messaging.thread(state, messaging.thread_for(state, str(row["pid"])) or "")
    if t is not None:
        clock.advance_time(state, cost_hours(state, str(t["app"]), "text"))
    return {"ok": True, "meet_id": meet_id, "pid": row["pid"], "cancelled": True}


def meet(state: GameState, meet_id: str, do: str) -> dict[str, Any]:
    """The `meet` verb: `go` or `cancel`."""
    if do == "go":
        return go(state, meet_id)
    if do == "cancel":
        return cancel(state, meet_id)
    return _no(f"You can go or cancel, not {do!r}.")


# -- asks and proposals: the engine picks (§10.5, §10.6) -----------------------------------------------


def ask_refusal(state: GameState, pid: str) -> str:
    """Why the player's `ask {what: meet}` is refused (`propose_refusal`'s words)."""
    return propose_refusal(state, pid)


def proposal_open(state: GameState, pid: str) -> bool:
    """§10.5 `ask_meet`'s gate beyond its data row: numbers or past it, nothing planned or asked."""
    stage = _person(state, pid).get("stage")
    return (stage_rank(stage) >= _from_rank() and stage != "winding_down" and not planned(state, pid)
            and _pending_request(state, pid) is None)


def propose_theirs(state: GameState, pid: str, thread_id: str, at: Optional[float] = None) -> dict[str, Any]:
    """
    Their `ask_meet` (§10.5): the engine picks the venue and the first slot free for both, and makes it
    a request to the player (`social_request` carrying `venue`, `day` and `slot`); not open when no slot
    is free. Called by `relationships.apply_proposal`, re-checked there.
    """
    choice = apply_effect(state, {"type": "social_meet", "op": "pick", "pid": pid})
    if not choice.get("ok"):
        return _no(str(choice.get("text")))
    effect: dict[str, Any] = {"type": "social_request", "op": "create", "pid": pid, "from": "them",
                              "what": REQUEST, "thread_id": thread_id, "venue": choice["venue"],
                              "day": choice["day"], "slot": choice["slot"]}
    if at is not None:
        effect["at"] = float(at)
    made = apply_effect(state, effect)
    if made.get("ok"):                                # unanswered by the slot's start, it lapses (review I2)
        events.push(state, slot_start(int(choice["day"]), str(choice["slot"])), "", "meet_start",
                    request_id=made["request"]["id"])
    return {"ok": bool(made.get("ok")), "request_id": made["request"]["id"]}


def still_open(state: GameState, request: dict[str, Any]) -> bool:
    """Their `ask_meet` request can still be said yes to: the gate holds and its slot is still free."""
    pid = str(request["pid"])
    day, slot, venue_id = int(request.get("day") or 0), str(request.get("slot") or ""), str(request.get("venue") or "")
    return (gate_open(state, pid) and not planned(state, pid) and slot in slots() and bool(venue(venue_id))
            and slot_free(state, pid, day, slot, float(venue(venue_id)["duration_hours"])))


def accept_theirs(state: GameState, request: dict[str, Any]) -> dict[str, Any]:
    """The player's yes to their `ask_meet`: re-checked now (`still_open`), then agreed."""
    if not still_open(state, request):
        return _no("That isn't on the table any more.")
    pid = str(request["pid"])
    day, slot, venue_id = int(request["day"]), str(request["slot"]), str(request["venue"])
    return apply_effect(state, {"type": "social_meet", "op": "agree", "pid": pid, "venue": venue_id, "day": day,
                                "slot": slot, "by": "them"})


def answer_ask(state: GameState, pid: str, request: dict[str, Any], at: float) -> bool:
    """
    The player's `ask {what: meet}` decided at their read (inside the read's handler): yes when the gate
    holds and a slot is free for both, the engine picking the venue and the slot; the request answered,
    and on yes the meet agreed. Whether they said yes.
    """
    accepted = False
    if gate_open(state, pid) and not planned(state, pid):
        choice = apply_effect(state, {"type": "social_meet", "op": "pick", "pid": pid})
        if choice.get("ok"):
            made = apply_effect(state, {"type": "social_meet", "op": "agree", "pid": pid, "venue": choice["venue"],
                                        "day": choice["day"], "slot": choice["slot"], "by": "player", "at": at})
            accepted = bool(made.get("ok"))
    apply_effect(state, {"type": "social_request", "op": "answer", "request_id": request["id"],
                         "status": "yes" if accepted else "no", "at": at})
    return accepted


# -- the catalogue (spec §7.1) ----------------------------------------------------------------------------


def _proposable(state: GameState) -> list[str]:
    pids = {t["pid"] for t in (state.social.get("threads") or {}).values() if matching.listed(t)}
    return sorted(p for p in pids if not propose_refusal(state, p))


def _propose_label(state: GameState, intent: dict[str, Any]) -> str:
    args = intent.get("args") or {}
    return f"Ask {_name(state, str(intent.get('target') or ''))} to {place_line(str(args.get('venue') or ''))}"


def _propose_refuse(state: GameState, intent: dict[str, Any]) -> str:
    pid = str(intent.get("target") or "")
    known = {t["pid"] for t in (state.social.get("threads") or {}).values()}
    return propose_refusal(state, pid) if pid in known else ""


@phone_verb("propose_meet", payload={"venue": ArgSpec("enum", required=True),
                                     "day": ArgSpec("int", min=1, max=7, required=True),
                                     "slot": ArgSpec("enum", required=True)},
            skill="social_propose_meet", label=_propose_label, refuse=_propose_refuse)
def _propose_verb(state: GameState) -> Optional[IntentVerb]:
    pids = _proposable(state) if venues() else []
    if not pids:
        return None
    return IntentVerb("propose_meet", options=tuple((p, _name(state, p)) for p in pids),
                      extra={"venue": venue_ids(), "slot": tuple(slots())})


def _meet_label(state: GameState, intent: dict[str, Any]) -> str:
    row = get(state, str(intent.get("target") or "")) or {}
    do = str((intent.get("args") or {}).get("do") or "")
    what = f"{place_line(str(row.get('venue') or ''))} with {_name(state, str(row.get('pid') or ''))}"
    return f"Cancel {what}" if do == "cancel" else f"Go: {what}"


def _meet_refuse(state: GameState, intent: dict[str, Any]) -> str:
    row = get(state, str(intent.get("target") or ""))
    if row is None:
        return ""
    if str((intent.get("args") or {}).get("do") or "") == "cancel" and row.get("status") in agreement.PLANNED:
        return ""
    return go_refusal(state, row) or ""


@phone_verb("meet", payload={"do": ArgSpec("enum", DOS, required=True)}, skill="social_meet",
            label=_meet_label, refuse=_meet_refuse)
def _meet_verb(state: GameState) -> Optional[IntentVerb]:
    # Every planned meet: cancel is open while it is planned; `go` only once it is due (refused in
    # words by `go` before: "It isn't time yet").
    rows = planned(state)
    if not rows:
        return None
    return IntentVerb("meet", options=tuple((r["id"], f"{place_line(r['venue'])} with {_name(state, r['pid'])}")
                                            for r in rows))


# -- the payload (spec §17.3) ----------------------------------------------------------------------------


@section("calendar", time_varying=True)
def _calendar_section(state: GameState, session: Any) -> list[dict[str, Any]]:
    """Every meet kept, soonest first: what the player may see (never the flake drawn, never a quality)."""
    out: list[dict[str, Any]] = []
    for row in _ordered(_meets(state).values()):
        place = venue(str(row["venue"]))
        out.append({"id": row["id"], "pid": row["pid"], "name": _name(state, str(row["pid"])),
                    "venue": row["venue"], "venue_label": str(place.get("label") or row["venue"]),
                    "place": place_line(str(row["venue"])), "neighbourhood": str(place.get("neighbourhood") or ""),
                    "day": row["day"], "slot": row["slot"], "when": when_words(row), "start": row["start"],
                    "end": row["end"], "hours": row["hours"], "status": row["status"], "by": row.get("by"),
                    "band": row.get("band") if row.get("status") == "done" else None,
                    "recap_line": recap_line(str(row["band"])) if row.get("status") == "done" else ""})
    return out


@section("meet_options")
def _meet_options_section(state: GameState, session: Any) -> dict[str, Any]:
    """
    What a `propose_meet` may name (v0.22.0 T29, the contact card's planner): every venue with its
    words, every slot with its start hour, and the days ahead (venues.yaml, relationships.yaml
    `meets:`). The data's, so it never moves with time; whether a person says yes is the engine's.
    """
    first, last = days_ahead()
    places = {str(r.get("id")): str(r.get("label") or r.get("id")) for r in population.table("neighbourhoods")
              if isinstance(r, dict)}
    return {
        "venues": [{"id": str(r["id"]), "label": str(r.get("label") or r["id"]), "place": place_line(str(r["id"])),
                    "neighbourhood": places.get(str(r.get("neighbourhood") or ""), str(r.get("neighbourhood") or ""))}
                   for r in venues() if r.get("id")],
        "slots": [{"id": k, "start": v[0]} for k, v in slots().items()],
        "days": [first, last],
    }


# -- the recap (spec §14.4, §11.6) -------------------------------------------------------------------------


def _hobby_labels(ids: Sequence[str]) -> list[str]:
    labels = {str(r.get("id")): str(r.get("label") or r.get("id")) for r in population.table("hobbies")
              if isinstance(r, dict)}
    return [labels.get(h, h.replace("_", " ")) for h in ids]


def view_of(*, name: str, venue_id: str, band_name: str, topics: Sequence[str] = (), pid: str = "",
            thread_id: str = "", message_ids: Sequence[str] = (), meet_id: str = "", when: str = "",
            about: str = "") -> dict[str, Any]:
    """A recap's view (what `recap_messages` and `voice_recap` read, pure): labels from the data."""
    place = venue(venue_id)
    places = {str(r.get("id")): str(r.get("label") or r.get("id"))
              for r in population.table("neighbourhoods") if isinstance(r, dict)}
    return {"meet_id": meet_id, "pid": pid, "thread_id": thread_id, "message_ids": list(message_ids),
            "name": name, "about": about, "venue": venue_id, "place": place_line(venue_id),
            "neighbourhood": places.get(str(place.get("neighbourhood") or ""), ""), "when": when,
            "band": band_name, "band_line": recap_line(band_name), "topics": list(topics)}


def recap_view(state: GameState, message: dict[str, Any]) -> Optional[dict[str, Any]]:
    """The view of a due recap message (CALLER HOLDS the turn lock): copies only. None when its meet is gone."""
    decision = dict(message.get("decision") or {})
    row = get(state, str(decision.get("meet_id") or ""))
    if row is None or row.get("status") != "done":
        return None
    pid = str(row["pid"])
    person = population.profile(state, pid)
    mine = (state.social.get("player") or {}).get("hobbies") or ()
    shared = [h for h in person.hobbies if h in mine] or list(person.hobbies[:2])
    jobs = {str(r.get("id")): str(r.get("label") or r.get("id")) for r in population.table("jobs")
            if isinstance(r, dict)}
    about = f"{person.age}, {population.in_sentence(jobs.get(person.job, person.job))}"
    return view_of(name=person.name, venue_id=str(row["venue"]), band_name=str(row["band"]),
                   topics=_hobby_labels(shared), pid=pid, thread_id=str(message["thread_id"]),
                   message_ids=[str(message["id"])], meet_id=str(row["id"]),
                   when=f"{behaviour.weekday_of(float(row['start'])).title()} {row['slot']}", about=about)


def recap_prompt() -> str:
    """`prompts/date_recap.md`, verbatim (§11.6); a ValueError when the story has none."""
    directory = social.social_dir()
    if directory is None:
        raise ValueError(f"social: {RECAP_FILE}: no story declares paths.social")
    path = directory.parent.parent / "prompts" / RECAP_FILE
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"social: {RECAP_FILE}: cannot be read ({exc})") from None


def _flat(text: str) -> str:
    """A block body with no blank line inside it (the user message's blocks part on blank lines)."""
    return re.sub(r"\n\s*\n+", "\n", str(text)).strip("\n")


def recap_messages(view: dict[str, Any]) -> list[dict[str, str]]:
    """Exactly the recap's blocks (§11.6): system `date_recap.md` verbatim; user WHO, WHERE, HOW IT WENT,
    TOPICS, FORMAT. Nothing else is added (pinned by test_the_recap_prompt_is_exactly_its_blocks)."""
    who = str(view.get("name") or "them") + (f", {view['about']}" if view.get("about") else "")
    where = str(view.get("place") or "") + (f", in {view['neighbourhood']}" if view.get("neighbourhood") else "")
    if view.get("when"):
        where += f", {view['when']}"
    topics = ", ".join(str(t) for t in view.get("topics") or ()) or "nothing in particular"
    went = f"{view.get('band')}: {view.get('band_line')}"
    fmt = (f"At most {RECAP_WORDS} words, in the second person, in the past tense. One paragraph of plain "
           "text: the recap only.")
    bodies = (who, where, went, topics, fmt)
    user = "\n\n".join(f"{title}\n{_flat(body)}" for title, body in zip(RECAP_BLOCKS, bodies))
    return [{"role": "system", "content": recap_prompt()}, {"role": "user", "content": user}]


def fallback_line(view: dict[str, Any]) -> str:
    """The engine's recap: "Coffee at The Copper Kettle with Kai. It was a little awkward." """
    return f"{view.get('place')} with {view.get('name')}. {view.get('band_line')}".strip()


def tone_failure(text: str, band_name: str) -> str:
    """The first `meets.recap_tone` phrase of a tone that contradicts `band_name` stated in `text`; ""."""
    tone = _rules().get("recap_tone") or {}
    for name in (tone.get("contradicts") or {}).get(band_name) or ():
        hit = agreement.stated(text, tone.get(name) or ())
        if hit:
            return hit
    return ""


def _clean(raw: Any) -> str:
    """A recap's words: one paragraph, at most RECAP_WORDS words."""
    words = str(raw or "").split() if isinstance(raw, str) else []
    return " ".join(words[:RECAP_WORDS])


def _reply(view: dict[str, Any], text: str, *, fallback: bool, failures: Sequence[str]) -> Any:
    from engine.social.voicing import VoicedReply   # lazily: voicing's package loads this module's

    return VoicedReply(pid=str(view.get("pid") or ""), thread_id=str(view.get("thread_id") or ""),
                       message_ids=tuple(str(m) for m in view.get("message_ids") or ()), bubbles=[text], caption="",
                       regard={}, learned=[], shared=[], proposals=[], fallback=fallback, failures=list(failures))


def recap_fallback(view: dict[str, Any], why: str, *, failures: Sequence[str] = ()) -> Any:
    """The engine's recap as a `VoicedReply` (no regard: the meet's effects were the engine's, at once)."""
    logger.info("[social] Recap fallback (operation=recap_fallback, meet=%s, why=%s, failures=%s)",
                view.get("meet_id"), why, list(failures))
    return _reply(view, fallback_line(view), fallback=True, failures=failures)


def voice_recap(view: dict[str, Any], llm_fn: Any) -> Any:
    """
    The recap voiced (§14.4): one bare call (the `texter` profile in production, plain text), its band
    checked (`tone_failure`), retried once with a one-line correction, else the engine's line. Pure over
    `view`: writes no state (the voicing pass commits it).
    """
    if llm_fn is None:
        return recap_fallback(view, "no model")
    try:
        msgs = recap_messages(view)
    except ValueError as exc:                       # a content fault: never raised
        logger.error("[social] A content fault; the recap falls back (operation=voice_recap): %s", exc)
        return recap_fallback(view, "content fault")
    failures: list[str] = []
    for attempt in range(2):
        try:
            raw = llm_fn(msgs, {})
        except Exception as exc:  # noqa: BLE001 -- no server, a starved reply: the engine's line
            logger.info("[social] Recap call failed (operation=voice_recap, meet=%s): %s", view.get("meet_id"), exc)
            return recap_fallback(view, "call failed", failures=failures)
        text = _clean(raw)
        if not text:
            failures.append(EMPTY)
            msgs = msgs + [{"role": "assistant", "content": str(raw)}, {"role": "user", "content": RECAP_ONLY}]
            continue
        hit = tone_failure(text, str(view.get("band") or ""))
        if not hit:
            return _reply(view, text, fallback=False, failures=failures)
        failures.append("band")
        if attempt == 0:
            msgs = msgs + [{"role": "assistant", "content": text},
                           {"role": "user", "content": f"Your recap said \"{hit}\", but how it went was: "
                                                       f"{view.get('band_line')} Rewrite it to agree with that."}]
    return recap_fallback(view, "two failures", failures=failures)


def recap_snapshot(state: GameState, message: dict[str, Any]) -> Any:
    """
    The voicing snapshot of one due recap (CALLER HOLDS the turn lock; engine/social/voicer.py): a
    `PersonSnapshot` whose `due` is that message and whose `recap` is its view (deep copies only).
    None when its meet is gone.
    """
    from engine.social.voicing import PersonSnapshot   # lazily: voicing's package loads this module's

    view = recap_view(state, message)
    if view is None:
        return None
    pid = str(view["pid"])
    person = population.profile(state, pid)
    at = float(state.world_clock_hours)
    return PersonSnapshot(
        pid=pid, thread_id=str(message["thread_id"]), profile=dataclasses.asdict(person),
        dynamic=copy.deepcopy(_person(state, pid)), tail=[], summary="", due=[copy.deepcopy(message)],
        proposals=(), player=copy.deepcopy(state.social.get("player") or {}),
        now={"day": int(state.world_day), "at": at}, contacts=(), seed=int(state.rng_seed),
        meets=agreement.meets_of(state, pid), recap=view)


def is_recap(message: dict[str, Any]) -> bool:
    """A due recap card (a system message the voicing pass voices through `voice_recap`)."""
    return message.get("kind") == RECAP and (message.get("decision") or {}).get("kind") == RECAP
