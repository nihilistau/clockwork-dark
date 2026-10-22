"""
Life events, both ways (v0.23.0 spec §11; T17).

A daily hook (``events.daily_hooks``) draws the world's calendar on SOCIAL_LIFE: the player's own events
from ``world_rng``, and each live person's from their own counter (``behaviour.person_rng``). The table is
``life_events.yaml`` (``check_data`` refuses at load any unknown key or malformed row). Life events are
ordinary life -- a boiler, a parcel, a holiday, a job offer, illness, family news (rule 12); nothing here
means anything beyond the fact it states.

**State.** ``people[pid]["life"]`` holds a person's events, ``[{id, at, until?, supported?, request?}]``;
``state.social["player_life"]`` the player's, the same row shape, written only by ``social_life`` with
``who == "player"``. ``people[pid]["news"]`` is what they will tell you next (once), ``["job_now"]`` a
new job's id. A row with ``until`` is RUNNING while ``at <= now < until``. Both stores are bounded at every
save (``forget_past``): the running events and the ones still on cooldown stay, with the newest
``life_events.yaml`` ``kept.past`` besides.

**One writer.** Every write is the ``social_life`` effect (rule 3): ``start`` (the row, the player's flag,
the canon line, the follow-up, the news, the mood, the new job or home, the proposal), ``end`` (the flag
cleared), ``supported``, ``answer`` (the job offer's outcome) and ``news_taken``. The calendar's own
queue entry is a ``life`` event (``events.KINDS``) that ends an event at its ``until``; the daily hook
ends any it missed (an unmatch drops a person's queue).

**What reads it.** ``growth.who_now``'s "Since you met" (``since_lines``); ``convo.decide`` (the news, once,
as situation ``news``); ``convo.available`` (``unavailable``: a holiday); the scene's ``tell_about``
topics and ``world.narration_block`` (``player_news``); ``windows.schedule_of`` (``work_extra``);
``world.go`` (``extra_minutes``: the lift); ``messaging.send`` and ``scene.move`` (``support``).

**Draws.** ``_event_drawn`` is one SOCIAL_LIFE draw per eligible row (lesson 1: forceable); a new job or
home is a counterless key of the person and the event count (``attrs.key``), so no other draw moves.

**The wedding** (§12.1-§12.2, T18): a person row with ``plan: wedding`` is eligible only while they are
``engaged`` and ``relationships.yaml`` ``wedding_after_days`` have passed since ``engaged_since``, with no
wedding plan open; its start queues the wedding's plan (``plans.make_wedding``), and arriving at the
registry office opens the wedding scene (engine/social/scene.py), whose end makes them ``married``.

**Being seen** (§12.4, T18): ``seen_check`` runs at the end of every scene. With anyone ELSE at ``exclusive``
or later (a partner), it draws ``seen.prob`` once (``_seen_drawn``, SOCIAL_LIFE, forceable); on a discovery
each such partner's trust drops by ``seen.trust``, their ``guarded`` count rises by one (``social_growth``
``guard``), their mood is ``hurt`` for ``seen.mood_days`` and their history says "They found out". A fact:
someone saw the player out with someone else. The existing ``cold:`` rule is the repair (MINOR 3).
"""

from __future__ import annotations

import dataclasses
import logging
import re
from typing import Any, Optional

from engine import social
from engine.game.effects import EffectContext, apply_effect, effect_kind
from engine.game.rng import SOCIAL_LIFE, world_rng
from engine.game.state import GameState
from engine.social import apps, attrs, behaviour, events, growth, memory, messaging, places, population, promises
from engine.social import relationships
from engine.social.kinds import recorded, stage_rank

logger = logging.getLogger(__name__)

#: The request a job offer makes (relationships.answer hands it back here).
REQUEST = "stay_or_go"

#: ``social_life``'s ops.
OPS: tuple[str, ...] = ("start", "end", "supported", "answer", "news_taken")

TOP_KEYS = frozenset({"kept", "player", "person", "seen"})
COMMON_KEYS = frozenset({"id", "when", "prob_per_week", "cooldown_days", "text", "lasts_days", "news", "mood",
                         "followup", "unavailable", "support"})
PLAYER_KEYS = COMMON_KEYS | {"label", "sign_off", "flag", "scene", "schedule", "effects"}
PERSON_KEYS = COMMON_KEYS | {"canon", "blocked_by_open_promise", "proposal", "job", "home", "plan"}
#: A person row's `plan:` (T18): the wedding's, queued `wedding_after_days` after the engagement.
WEDDING = "wedding"
#: The stage the wedding row waits on (§12.1).
ENGAGED = "engaged"
#: A partner, for being seen: someone at this stage or later (§12.4).
PARTNER_STAGE = "exclusive"
WHEN_KEYS = frozenset({"stage_min", "stages"})
SCHEDULE_KEYS = frozenset({"work_extra_hours", "lift_extra_minutes"})
SEEN_KEYS = frozenset({"prob", "trust", "mood_days"})
PROPOSALS: tuple[str, ...] = (REQUEST,)
#: A follow-up's ``when`` (relationships.followup_due_at reads exactly these).
_WHEN_RE = re.compile(r"^(tomorrow|days:\d{1,2}|after:[a-z_]+)$")
_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")


# -- the data ----------------------------------------------------------------------------------------------


def _data() -> dict[str, Any]:
    return social.data("life_events")


def _fault(key: str, message: str) -> ValueError:
    return ValueError(f"social: life_events.yaml: {key}: {message}")


def _number(where: str, value: Any, *, whole: bool = False, above_zero: bool = False) -> None:
    if isinstance(value, bool) or not isinstance(value, int if whole else (int, float)):
        raise _fault(where, f"must be a {'whole number' if whole else 'number'}, not {value!r}")
    if value < 0 or (above_zero and value == 0):
        raise _fault(where, f"must be {'above' if above_zero else 'at least'} 0, not {value!r}")


def check_data(data: dict[str, Any], *, moods: Optional[tuple[str, ...]] = None,
               stages: Optional[tuple[str, ...]] = None) -> None:
    """Refuse a malformed life_events.yaml at load (a ValueError naming file and key). Empty is fine."""
    from engine.social.kinds import STAGES

    stages = stages or STAGES
    if not isinstance(data, dict):
        raise _fault("(top)", "must be a mapping")
    extra = sorted(set(data) - TOP_KEYS)
    if extra:
        raise _fault("(top)", f"unknown key(s) {extra} (allowed: {sorted(TOP_KEYS)})")
    kept = data.get("kept")
    if kept is not None:
        if not isinstance(kept, dict) or set(kept) - {"past"}:
            raise _fault("kept", "must be {past: n}")
        _number("kept.past", kept.get("past"), whole=True)
    seen = data.get("seen")
    if seen is not None:
        if not isinstance(seen, dict) or set(seen) - SEEN_KEYS:
            raise _fault("seen", f"must be a mapping of {sorted(SEEN_KEYS)}")
        if "prob" in seen:
            _number("seen.prob", seen["prob"])
            if seen["prob"] > 1:
                raise _fault("seen.prob", f"must be a chance from 0 to 1, not {seen['prob']!r}")
        if "trust" in seen and (isinstance(seen["trust"], bool) or not isinstance(seen["trust"], int)
                                or seen["trust"] > 0):
            raise _fault("seen.trust", f"must be a whole number, 0 or less, not {seen['trust']!r}")
        if "mood_days" in seen:
            _number("seen.mood_days", seen["mood_days"], above_zero=True)
    for side, allowed in (("player", PLAYER_KEYS), ("person", PERSON_KEYS)):
        rows = data.get(side)
        if rows in (None, {}):
            continue
        if not isinstance(rows, list):
            raise _fault(side, "must be a list of rows")
        ids: set[str] = set()
        for i, row in enumerate(rows):
            where = f"{side}[{i}]"
            if not isinstance(row, dict):
                raise _fault(where, "must be a mapping")
            extra = sorted(set(row) - allowed)
            if extra:
                raise _fault(where, f"unknown key(s) {extra} (allowed: {sorted(allowed)})")
            rid = row.get("id")
            if not isinstance(rid, str) or not _ID_RE.match(rid):
                raise _fault(where, f"id must be a lower-case word, not {rid!r}")
            if rid in ids:
                raise _fault(where, f"id {rid!r} is repeated")
            ids.add(rid)
            where = f"{side}.{rid}"
            _check_row(where, side, row, moods=moods, stages=stages)


def _check_row(where: str, side: str, row: dict[str, Any], *, moods: Optional[tuple[str, ...]],
               stages: tuple[str, ...]) -> None:
    _number(f"{where}.prob_per_week", row.get("prob_per_week", 0))
    _number(f"{where}.cooldown_days", row.get("cooldown_days", 0), whole=True)
    if "lasts_days" in row:
        _number(f"{where}.lasts_days", row["lasts_days"], whole=True, above_zero=True)
    if not str(row.get("text") or row.get("canon") or "").strip():
        raise _fault(where, "needs a plain fact in `text` (or `canon`)")
    when = row.get("when") or {}
    if not isinstance(when, dict) or set(when) - WHEN_KEYS:
        raise _fault(f"{where}.when", f"must be a mapping of {sorted(WHEN_KEYS)}")
    if side == "player" and when:
        raise _fault(f"{where}.when", "the player's events take no `when`")
    for key in ("stage_min",):
        if key in when and when[key] not in stages:
            raise _fault(f"{where}.when.{key}", f"{when[key]!r} is no stage")
    if "stages" in when and (not isinstance(when["stages"], list) or set(when["stages"]) - set(stages)):
        raise _fault(f"{where}.when.stages", "must list stages")
    news = row.get("news")
    if news is not None and news != ("player_news" if side == "player" else "news"):
        raise _fault(f"{where}.news", f"must be {'player_news' if side == 'player' else 'news'}")
    follow = row.get("followup")
    if follow is not None:
        if not isinstance(follow, dict) or set(follow) - {"about", "when"}:
            raise _fault(f"{where}.followup", "must be {about, when}")
        if not str(follow.get("about") or "").strip() or not _WHEN_RE.match(str(follow.get("when") or "")):
            raise _fault(f"{where}.followup", "needs `about` and a `when` of tomorrow, days:<n> or after:<window>")
    mood = row.get("mood")
    if mood is not None:
        if not isinstance(mood, dict) or set(mood) - {"value", "days"}:
            raise _fault(f"{where}.mood", "must be {value, days}")
        if moods is not None and mood.get("value") not in moods:
            raise _fault(f"{where}.mood.value", f"{mood.get('value')!r} is no mood")
        _number(f"{where}.mood.days", mood.get("days"), whole=True, above_zero=True)
    for key in ("unavailable", "support", "blocked_by_open_promise"):
        if key in row and not isinstance(row[key], bool):
            raise _fault(f"{where}.{key}", "must be true or false")
    if (row.get("unavailable") or row.get("support")) and "lasts_days" not in row:
        raise _fault(where, "`unavailable` and `support` need `lasts_days`: they are a window")
    if row.get("proposal") is not None and row["proposal"] not in PROPOSALS:
        raise _fault(f"{where}.proposal", f"must be one of {', '.join(PROPOSALS)}")
    if row.get("job") is not None and row["job"] != "draw":
        raise _fault(f"{where}.job", "must be `draw`")
    if row.get("home") is not None and row["home"] != "redraw":
        raise _fault(f"{where}.home", "must be `redraw`")
    if row.get("plan") is not None:
        if row["plan"] != WEDDING:
            raise _fault(f"{where}.plan", f"must be `{WEDDING}`")
        if (row.get("when") or {}).get("stages") != [ENGAGED]:
            raise _fault(f"{where}.when", f"the wedding's row waits on `stages: [{ENGAGED}]`")
    if side == "player":
        schedule = row.get("schedule")
        if schedule is not None:
            if not isinstance(schedule, dict) or set(schedule) - SCHEDULE_KEYS:
                raise _fault(f"{where}.schedule", f"must be a mapping of {sorted(SCHEDULE_KEYS)}")
            for key, value in schedule.items():
                _number(f"{where}.schedule.{key}", value, above_zero=True)
            if "lasts_days" not in row:
                raise _fault(where, "a `schedule` needs `lasts_days`")
        if "effects" in row and not isinstance(row["effects"], list):
            raise _fault(f"{where}.effects", "must be a list")
        if row.get("news") and not str(row.get("label") or "").strip():
            raise _fault(where, "a player event with news needs a `label` (its tell_about topic)")


def _rows(side: str) -> list[dict[str, Any]]:
    rows = _data().get(side)
    return list(rows) if isinstance(rows, list) else []


def row_of(side: str, event_id: str) -> Optional[dict[str, Any]]:
    return next((r for r in _rows(side) if r.get("id") == event_id), None)


def line_of(row: dict[str, Any]) -> str:
    """The row's plain fact: its public `canon` line, else its `text`."""
    return str(row.get("canon") or row.get("text") or "")


def _past_kept() -> int:
    return max(0, int((_data().get("kept") or {}).get("past", 4)))


# -- the stores --------------------------------------------------------------------------------------------


def _side(who: str) -> str:
    return "player" if who == "player" else "person"


def events_of(state: GameState, who: str) -> list[dict[str, Any]]:
    """``who``'s life rows, oldest first (a read; the store is written only by ``social_life``)."""
    slice_ = getattr(state, "social", None) or {}
    if who == "player":
        return list(slice_.get("player_life") or [])
    return list(((slice_.get("people") or {}).get(who) or {}).get("life") or [])


def _store(state: GameState, who: str) -> list[dict[str, Any]]:
    """The live list a ``social_life`` handler appends to (``setdefault``: no other task creates it)."""
    if who == "player":
        return state.social.setdefault("player_life", [])
    return state.social.setdefault("people", {}).setdefault(who, {}).setdefault("life", [])


def running(state: GameState, who: str, at: Optional[float] = None) -> list[dict[str, Any]]:
    """``who``'s events running at ``at`` (default now): ``at <= t < until``."""
    t = state.world_clock_hours if at is None else float(at)
    # `at` is stored to four places, so an event begun this very minute is running (a hair of slack).
    return [e for e in events_of(state, who)
            if e.get("until") is not None and float(e["at"]) - 1e-3 <= t < float(e["until"])]


def _last_at(state: GameState, who: str, event_id: str) -> Optional[float]:
    ats = [float(e["at"]) for e in events_of(state, who) if e.get("id") == event_id]
    return max(ats) if ats else None


def _person_stage(state: GameState, pid: str) -> str:
    return str(((state.social.get("people") or {}).get(pid) or {}).get("stage") or "")


def _eligible(state: GameState, who: str, row: dict[str, Any], day_at: float) -> bool:
    """Not running now, past its cooldown, and (a person's) at a stage its `when` allows; a `home: redraw` row
    (moving house) never for the partner who lives in the player's flat (T18 fix I2)."""
    last = _last_at(state, who, str(row["id"]))
    if last is not None and day_at < last + 24.0 * float(row.get("cooldown_days", 0)):
        return False
    if any(e.get("id") == row["id"] for e in running(state, who, day_at)):
        return False
    if who != "player":
        when = row.get("when") or {}
        stage = _person_stage(state, who)
        if stage_rank(stage) < 0:
            return False
        if "stage_min" in when and stage_rank(stage) < stage_rank(when["stage_min"]):
            return False
        if "stages" in when and stage not in when["stages"]:
            return False
        if row.get("plan") == WEDDING and not _wedding_due(state, who, day_at):
            return False
        if row.get("home") == "redraw" and relationships.household(state) == who:
            return False                                 # they live in the player's flat: no move of their own (T18)
    return True


def _wedding_due(state: GameState, pid: str, day_at: float) -> bool:
    """`wedding_after_days` (relationships.yaml, R15) have passed since `engaged_since`, and no wedding plan is
    open with them (T18)."""
    from engine.social import plans   # lazily: plans imports this module's peers

    since = ((state.social.get("people") or {}).get(pid) or {}).get("engaged_since")
    after = float(social.data("relationships").get("wedding_after_days", 14))
    if since is None or day_at < float(since) + 24.0 * after:
        return False
    return not any(r.get("kind") == plans.WEDDING for r in plans.open_for(state, pid))


def _event_drawn(state: GameState, who: str, row: dict[str, Any]) -> bool:
    """A week's odds as a day's (prob_per_week / 7), one SOCIAL_LIFE draw (lesson 1: forceable)."""
    rng = (world_rng(state, SOCIAL_LIFE) if who == "player"
           else behaviour.person_rng(state, SOCIAL_LIFE, who))
    return rng.random() < float(row.get("prob_per_week", 0)) / 7.0


# -- the daily hook ----------------------------------------------------------------------------------------


def _expire(state: GameState, day_at: float) -> None:
    """End what ran out in the day just gone, in case its own queue entry did not (an unmatch drops a person's
    queue). An end is idempotent, so one that did is ended again to no effect."""
    for who in ["player", *sorted((state.social.get("people") or {}))]:
        for e in events_of(state, who):
            if e.get("until") is not None and day_at - 24.0 < float(e["until"]) <= day_at:
                apply_effect(state, {"type": "social_life", "op": "end", "who": who, "id": e["id"],
                                     "at": float(e["at"])})


def daily(state: GameState) -> None:
    """events.daily_hooks entry: end what has run its days; then the player's draws; then each live person's."""
    day_at = events.daily_at(state)
    _expire(state, day_at)
    for row in _rows("player"):
        if _eligible(state, "player", row, day_at) and _event_drawn(state, "player", row):
            apply_effect(state, {"type": "social_life", "op": "start", "who": "player", "id": row["id"], "at": day_at})
    for pid in messaging.live_people(state):
        for row in _rows("person"):
            if row.get("blocked_by_open_promise") and promises.open_by(state, pid, by="person"):
                continue                                  # a holiday waits for open promises (§5.3)
            if _eligible(state, pid, row, day_at) and _event_drawn(state, pid, row):
                apply_effect(state, {"type": "social_life", "op": "start", "who": pid, "id": row["id"], "at": day_at})


events.daily_hooks.append(daily)


@events.handles("life")
def _on_life(state: GameState, event: dict[str, Any]) -> dict[str, Any]:
    """A queued event reaches its end: its flag is cleared (``social_life`` ``end``)."""
    who = "player" if event.get("who") == "player" else str(event.get("pid") or "")
    return apply_effect(state, {"type": "social_life", "op": "end", "who": who, "id": str(event.get("id") or ""),
                                "at": float(event.get("began") or 0.0)})


# -- the effect --------------------------------------------------------------------------------------------


def _fail(text: str) -> dict[str, Any]:
    return {"type": "social_life", "ok": False, "text": text}


@effect_kind("social_life")
@recorded
def _e_life(state: GameState, effect: dict[str, Any], ctx: EffectContext) -> dict[str, Any]:
    """
    Engine-only: life events (spec §11). Ops: ``start`` (``who``, ``id``, ``at``: the row, and per its data the
    player's flag, canon, follow-up, news, mood, new job or home, the job offer's request), ``end`` (the
    flag cleared), ``supported`` (``who``, ``id``: their support gained once), ``answer`` (``pid``, ``stays``:
    the job offer settled) and ``news_taken`` (``pid``: their news told).
    """
    if not state.social:
        return _fail("no social slice")
    op = str(effect.get("op") or "")
    if op not in OPS:
        return _fail(f"{op!r} is no life op")
    who = str(effect.get("who") or effect.get("pid") or "")
    if not who:
        return _fail("no one named")
    if who != "player" and who not in (state.social.get("people") or {}):
        return _fail(f"no person {who}")
    at = float(effect["at"]) if effect.get("at") is not None else state.world_clock_hours
    if op == "start":
        return _start(state, who, str(effect.get("id") or ""), at)
    if op == "end":
        return _end(state, who, str(effect.get("id") or ""), at)
    if op == "supported":
        for e in running(state, who):
            if e["id"] == effect.get("id") and not e.get("supported"):
                e["supported"] = True
                return {"type": "social_life", "ok": True, "text": f"{who} supported in {e['id']}"}
        return _fail("nothing to support")
    if op == "news_taken":
        person = state.social["people"][who]
        taken = person.pop("news", None)
        relationships.touch(person)
        return {"type": "social_life", "ok": bool(taken), "text": f"{who} news told", "news": taken}
    return _answer(state, who, bool(effect.get("stays")), str(effect.get("ask") or ""), at)


def _start(state: GameState, who: str, event_id: str, at: float) -> dict[str, Any]:
    row = row_of(_side(who), event_id)
    if row is None:
        return _fail(f"{event_id!r} is no {_side(who)} life event")
    if any(e.get("id") == event_id for e in running(state, who, at)):
        return _fail(f"{event_id} is already running")
    entry: dict[str, Any] = {"id": event_id, "at": round(at, 4)}
    until = None
    if row.get("lasts_days"):
        until = round(at + 24.0 * float(row["lasts_days"]), 4)
        entry["until"] = until
    _store(state, who).append(entry)
    if until is not None:
        events.push(state, until, "" if who == "player" else who, "life", id=event_id, began=round(at, 4),
                    who="player" if who == "player" else "")
    out: dict[str, Any] = {"type": "social_life", "ok": True, "text": f"{who}: {event_id}", "who": who, "id": event_id}
    if who == "player":
        if row.get("flag"):
            apply_effect(state, {"type": "flag", "flag": str(row["flag"]), "value": True})
        for effect in row.get("effects") or []:
            apply_effect(state, dict(effect))
        return out
    _start_person(state, who, row, entry, at)
    return out


def _start_person(state: GameState, pid: str, row: dict[str, Any], entry: dict[str, Any], at: float) -> None:
    person = state.social["people"][pid]
    relationships.touch(person)
    if row.get("canon"):
        memory.add_canon(state, pid, [str(row["canon"])])
    follow = row.get("followup")
    if follow:
        due = relationships.followup_due_at(state, pid, str(follow["when"]), at)
        if due is not None:
            memory.add_open(state, pid, {"kind": "followup", "about": str(follow["about"]), "due_at": due,
                                         "by": "person"})
    if row.get("news"):
        person["news"] = {"id": str(row["id"]), "text": line_of(row)}
    mood = row.get("mood")
    if mood:
        apply_effect(state, {"type": "social_regard", "pid": pid, "mood": str(mood["value"]), "at": at,
                             "mood_hours": 24.0 * float(mood["days"])})
    count = sum(1 for e in events_of(state, pid) if e.get("id") == row["id"])
    if row.get("job") == "draw":
        job = _draw_job(state, pid, count)
        if job:
            person["job_now"] = job
    if row.get("home") == "redraw":
        home = _draw_home(state, pid, count)
        if home:
            stored = dict(person.get("attrs") or {})
            apply_effect(state, {"type": "social_person", "pid": pid, "set": {"attrs": {**stored, "home": home}}})
    if row.get("plan") == WEDDING:
        from engine.social import plans   # lazily: plans imports this module's peers

        made_plan = plans.make_wedding(state, pid, at=at)
        if made_plan:
            entry["plan"] = str(made_plan["id"])
    if row.get("proposal") == REQUEST:
        made = apply_effect(state, {"type": "social_request", "op": "create", "pid": pid, "from": "them",
                                    "what": REQUEST, "at": at, "thread_id": messaging.thread_for(state, pid) or ""})
        if made.get("ok"):
            entry["request"] = made["request"]["id"]


def _end(state: GameState, who: str, event_id: str, at: float) -> dict[str, Any]:
    """The player's flag for the event cleared (a person's event holds none). Idempotent."""
    row = row_of(_side(who), event_id) or {}
    flag = str(row.get("flag") or "")
    if who == "player" and flag and state.flags.get(flag):
        apply_effect(state, {"type": "flag", "flag": flag, "value": False})
    return {"type": "social_life", "ok": True, "text": f"{who}: {event_id} over"}


# -- a new job, a new home ---------------------------------------------------------------------------------


def _draw_job(state: GameState, pid: str, count: int) -> str:
    """A new job: the person's own counterless key plus the event count (``attrs.key``), never their current one."""
    jobs = [r for r in population.table("jobs") if isinstance(r, dict)]
    current = job_now(state, pid) or population.profile(state, pid).job
    pool = [r for r in jobs if r.get("id") != current]
    if not pool:
        return ""
    rng = attrs.key(state.rng_seed, SOCIAL_LIFE, pid, f"job:{count}")
    return str(population._weighted(rng, pool)["id"])


def _draw_home(state: GameState, pid: str, count: int) -> str:
    weights = places._weights(population.profile(state, pid))
    current = places.home_of(state, pid)
    ids = [h for h in places.home_ids() if float(weights.get(h, 0)) > 0 and h != current]
    if not ids:
        return ""
    rng = attrs.key(state.rng_seed, SOCIAL_LIFE, pid, f"home:{count}")
    return str(rng.choices(ids, weights=[float(weights[h]) for h in ids])[0])


def job_now(state: GameState, pid: str) -> str:
    """The job they took since you met ("" when none): ``who_now`` reads it, ``population.profile`` stays the seed's."""
    return str(((state.social.get("people") or {}).get(pid) or {}).get("job_now") or "")


def person_now(state: GameState, pid: str) -> Any:
    """``population.profile`` with the life overlay (their new job and its shape): what they say of themselves now."""
    person = population.profile(state, pid)
    job = job_now(state, pid)
    if not job:
        return person
    row = next((r for r in population.table("jobs") if isinstance(r, dict) and r.get("id") == job), None)
    if row is None:
        return person
    return dataclasses.replace(person, job=job, job_shape=str(row.get("shape") or person.job_shape))


# -- reads -------------------------------------------------------------------------------------------------


def since_lines(state: GameState, pid: str, limit: int) -> list[str]:
    """What has happened in their life since you met, as plain facts: the newest ``limit``, oldest first (§11.3)."""
    rows = events_of(state, pid)
    lines: list[str] = []
    for e in rows[-max(0, int(limit)):] if limit else []:
        row = row_of("person", str(e.get("id")))
        if row is not None and line_of(row):
            lines.append(line_of(row))
    return lines


def player_news(state: GameState) -> list[dict[str, Any]]:
    """The player's running events with news: `{id, text, label, topic, sign_off}`, oldest first (§11.2)."""
    out: list[dict[str, Any]] = []
    for e in running(state, "player"):
        row = row_of("player", str(e["id"]))
        if row is not None and row.get("news"):
            out.append({"id": row["id"], "text": line_of(row), "label": str(row.get("label") or ""),
                        "topic": f"life_{row['id']}", "sign_off": str(row.get("sign_off") or "")})
    return out


def topic_label(topic: str) -> str:
    """The words of a player-life tell_about topic (``life_<id>``); "" for any other topic."""
    row = row_of("player", topic[5:]) if topic.startswith("life_") else None
    return str((row or {}).get("label") or "")


def topic_text(topic: str) -> str:
    row = row_of("player", topic[5:]) if topic.startswith("life_") else None
    return line_of(row) if row else ""


def sign_off_reason(state: GameState) -> str:
    """The words for why the PLAYER ends a chat while an event of theirs with a `sign_off` runs ("" when none)."""
    for item in reversed(player_news(state)):
        if item["sign_off"]:
            return item["sign_off"]
    return ""


def unavailable(state: GameState, pid: str, at: float) -> bool:
    """A holiday (any running event of theirs that says `unavailable`) at ``at``: they do not answer."""
    for e in running(state, pid, at):
        row = row_of("person", str(e["id"]))
        if row is not None and row.get("unavailable"):
            return True
    return False


def work_extra(state: GameState) -> list[tuple[float, float, float]]:
    """``(from, to, hours)`` for each running player event that lengthens the work band (``windows``)."""
    out: list[tuple[float, float, float]] = []
    for e in events_of(state, "player"):
        row = row_of("player", str(e.get("id"))) or {}
        hours = float((row.get("schedule") or {}).get("work_extra_hours", 0) or 0)
        if hours and e.get("until") is not None:
            out.append((float(e["at"]), float(e["until"]), hours))
    return out


def extra_minutes(state: GameState) -> int:
    """Minutes added to getting about while the lift is out (a running `lift_extra_minutes`)."""
    total = 0.0
    for e in running(state, "player"):
        row = row_of("player", str(e["id"])) or {}
        total += float((row.get("schedule") or {}).get("lift_extra_minutes", 0) or 0)
    return int(total)


# -- support (§6.3) ----------------------------------------------------------------------------------------


def support(state: GameState, pid: str) -> float:
    """A reply of yours, or a scene with them, while a hard event of theirs runs: `support`, once per event.
    The openness gained (0.0 when there was nothing to support)."""
    for e in running(state, pid):
        row = row_of("person", str(e["id"]))
        if row is None or not row.get("support") or e.get("supported"):
            continue
        marked = apply_effect(state, {"type": "social_life", "op": "supported", "who": pid, "id": e["id"]})
        if marked.get("ok"):
            return growth.gain(state, pid, "support")
    return 0.0


# -- the news (convo.decide) -------------------------------------------------------------------------------


def take_news(state: GameState, pid: str) -> str:
    """Their news for the next reply, told once ("" when none): inside a social handler (rule 3)."""
    news = ((state.social.get("people") or {}).get(pid) or {}).get("news")
    if not isinstance(news, dict) or not news.get("text"):
        return ""
    apply_effect(state, {"type": "social_life", "op": "news_taken", "pid": pid})
    return str(news["text"])


# -- the job offer (§11.3) ---------------------------------------------------------------------------------


def _answer(state: GameState, pid: str, stays: bool, ask: str, at: float) -> dict[str, Any]:
    if stays:
        relationships.add_history(state, pid, "stayed", "They turned the job down and stayed", at=at)
        growth.gain(state, pid, "support")
        return {"type": "social_life", "ok": True, "text": f"{pid} stays", "stays": True}
    relationships.set_stage(state, pid, "ended", at=at, by="them", kind="ended",
                            line="They took the job elsewhere", drop_queue=True)
    return {"type": "social_life", "ok": True, "text": f"{pid} goes", "stays": False}


def answer_stay_or_go(state: GameState, pid: str, *, ask: str) -> dict[str, Any]:
    """
    The player's answer to the job offer: "ask them to stay" (``ask="stay"``) or "tell them to go"
    (``"go"``). The engine decides by ``growth.willing(state, pid, "stay_or_go")``: asked to stay, they stay
    when they are willing and go when they are not; told to go, they go. Staying is a history row and
    `support`; going is the stage `ended`. The pending request, if there is one, is settled.
    """
    if ask not in ("stay", "go"):
        return {"ok": False, "error": f"answer stay or go, not {ask!r}"}
    ok, why = growth.willing(state, pid, REQUEST)
    stays = ask == "stay" and ok
    for r in relationships.pending_offers(state, pid, REQUEST):
        apply_effect(state, {"type": "social_request", "op": "answer", "request_id": r["id"],
                             "status": "yes" if ask == "stay" else "no"})
    result = apply_effect(state, {"type": "social_life", "op": "answer", "pid": pid, "stays": stays, "ask": ask})
    return {"ok": bool(result.get("ok")), "pid": pid, "stays": stays, "why": "" if stays else why}


def answer_request(state: GameState, request_id: str, reply: str) -> dict[str, Any]:
    """``relationships.answer`` for a job offer: yes asks them to stay, no tells them to go, later leaves it open."""
    request = (state.social.get("requests") or {}).get(request_id) or {}
    pid = str(request.get("pid") or "")
    if reply == "later":
        apply_effect(state, {"type": "social_request", "op": "answer", "request_id": request_id, "status": "later"})
        return {"ok": True, "request_id": request_id, "pid": pid, "answer": "later"}
    out = answer_stay_or_go(state, pid, ask="stay" if reply == "yes" else "go")
    return {**out, "request_id": request_id, "answer": reply}


# -- being seen (§12.4, T18) -------------------------------------------------------------------------------


def partners(state: GameState, but: str = "") -> list[str]:
    """Everyone the player is together with (`exclusive` or later), but `but`, sorted (a read)."""
    people = (getattr(state, "social", None) or {}).get("people") or {}
    return sorted(pid for pid, row in people.items()
                  if pid != but and isinstance(row, dict) and stage_rank(row.get("stage")) >= stage_rank(PARTNER_STAGE)
                  and not apps.gone(state, pid))


def _seen_drawn(state: GameState) -> bool:
    """Whether someone saw: one SOCIAL_LIFE draw against `seen.prob` (lesson 1: forceable)."""
    prob = float((_data().get("seen") or {}).get("prob", 0) or 0)
    return world_rng(state, SOCIAL_LIFE).random() < prob


def seen_check(state: GameState, pid: str) -> list[str]:
    """
    At the end of a scene with ``pid`` (§12.4): with a partner other than ``pid``, one draw (`_seen_drawn`); on a
    discovery each such partner's trust drops by `seen.trust`, `guarded` rises by one, their mood is `hurt` for
    `seen.mood_days`, and their history says "They found out". Inside the scene's `end` handler, or anywhere:
    every write is a `social_*` effect. The partners who found out ([] when none did, or there was none).
    """
    found = partners(state, but=pid)
    seen = _data().get("seen") or {}
    if not found or not seen or not _seen_drawn(state):
        return []
    at = state.world_clock_hours
    for partner in found:
        apply_effect(state, {"type": "social_regard", "pid": partner, "exact": True, "at": at,
                             "trust": int(seen.get("trust", 0)), "mood": "hurt",
                             "mood_hours": 24.0 * float(seen.get("mood_days", 1))})
        apply_effect(state, {"type": "social_growth", "op": "guard", "pid": partner})
        relationships.add_history(state, partner, "seen", "They found out", at=at)
    return found


# -- bounded state (spec §17.2) ----------------------------------------------------------------------------


def forget_past(state: GameState) -> int:
    """
    At every save (``saves.compact``): per person (and the player), the running events and the ones still on
    their cooldown stay, with the newest ``life_events.yaml`` ``kept.past`` besides; older leave state. A
    reader needing a gone one is served by what it left (the canon line in their memory). How many left.
    """
    keep = _past_kept()
    now = state.world_clock_hours
    gone = 0
    slice_ = state.social or {}
    stores: list[tuple[str, list[dict[str, Any]], dict[str, Any], str]] = []
    if slice_.get("player_life"):
        stores.append(("player", slice_["player_life"], slice_, "player_life"))
    for pid, person in (slice_.get("people") or {}).items():
        if isinstance(person, dict) and person.get("life"):
            stores.append((pid, person["life"], person, "life"))
    for who, rows, holder, key in stores:
        def held(e: dict[str, Any], who: str = who) -> bool:
            row = row_of(_side(who), str(e.get("id"))) or {}
            on_cooldown = now < float(e["at"]) + 24.0 * float(row.get("cooldown_days", 0))
            return on_cooldown or (e.get("until") is not None and now < float(e["until"]))

        past = [e for e in rows if not held(e)]
        drop = {id(e) for e in past[:max(0, len(past) - keep)]}
        if drop:
            holder[key] = [e for e in rows if id(e) not in drop]
            gone += len(drop)
        if not holder[key]:
            del holder[key]
    return gone
