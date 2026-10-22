"""
Plans with no set time (v0.23.0 spec §9): the appointment half of v0.22.0's meet-ups, replaced.

**A plan** is a row in `state.social["plans"]` (`pl<n>` ids, Plan decision 2):

    {id, pid, kind, venue, when, made_at, patience_hours, by, status, episodes_at,
     due_at, arrives_at, arrived}          # the last three only on a `now` / `tonight` row (A4 W3)

It has a time of day in WORDS (`when`: `now`, `tonight` or `soon`), a place (`venue`, a location id; a
`their_place` plan meets at their home and a `your_place` plan at the player's, both read from the kind)
and a person: no slot, no date. `status` is `open`, `met`, `lapsed`, `cancelled` or `stood_up`. `made_at`
and `patience_hours` are the engine's; the payload carries words, never times (`plans` section).

**Making one** (§9.2). Three ways. The player's `ask {what: meet, kind?, venue?, when}` is a request
decided at the person's read (`answer_ask`): yes when the `meet` commitment holds (growth.yaml
`willing.meet`, §6.5) and they have the time (`now` needs them available with `now_min_hours` free, `tonight`
needs their evening, `soon` willingness alone); the venue is the player's or the engine's pick by shared
hobbies (`places.pick_venue`). Their ask is a request of theirs the player answers (`propose_theirs`, the
`ask_meet` proposal; `_daily_invites`, plans.yaml `invite`). A scene's closer makes one in person
(`scene.close`: `in_person=True`, no time to find and no flake, since the two of them are already together).

**Keeping one** (§9.3, addendum 4 W2-W4). A `now` / `tonight` plan is due at `due_at` (`made_at`, or the start
of their evening for `tonight`) and the person gets there at `arrives_at`: their travel (a venue's minutes, their
home's for `your_place`; none for `their_place`, where they are home) plus a lateness drawn from plans.yaml
`arrival.late_minutes` by a counterless `stable_rng` keyed on the plan id (`_arrival`). A plan made in person
(a closer) has both at `made_at` and is `arrived` at once: they come with the player (C1). The `plan_arrive`
event at `arrives_at` only RECORDS it (`arrived`) and, when the player is elsewhere, queues their `arrived`
message; the scene opens where the clock has stopped (`meet_if_here`, `arrive`), never inside the event. The
player who gets there first waits ("Wait for {name}", `scene.wait_for_plan`). Patience runs from `arrives_at`:
after it the person is gone, the plan is `stood_up` at the cost of plans.yaml `stood_up`, and they say so
(`stood_up`). A "running late" message within patience extends it once by `late_grace_hours` (`running_late`). A flake is
drawn when a `now` / `tonight` plan is made (`_flake_drawn`, SOCIAL_SCENE): it shows as their message a
minute later (`plan_flake`) and the plan is `cancelled`. A `soon` plan lapses quietly after
`soon_patience_episodes` of the person's closed episodes (`on_episode_close`), counted in episodes, never
days. One a person never gets to closes quietly `lapse_after_hours` after its patience (`plan_lapse`).

**The wedding** (§12.2, T18) is the engine's own plan, never asked for: life_events.yaml's `wedding` row
queues it (`make_wedding`), kind `wedding` at the registry office (`WEDDING_PLACE`), `when: soon`. It stands
in no other plan's way, never lapses, and opens the wedding scene whenever the player arrives there while
the two of them are engaged.

Every write is the `social_plan` effect (rule 3); every draw is on a named stream (rule 4); no handler moves
the clock (rule 2). A plan is a time, a place and a person: nothing here knows what two people do there.
"""

from __future__ import annotations

import logging
from typing import Any, Optional, Sequence

from engine import social
from engine.game.effects import EffectContext, apply_effect, effect_kind
from engine.game.rng import SOCIAL_PACE, SOCIAL_SCENE, stable_rng
from engine.game.state import GameState
from engine.social import behaviour, convo, events, growth, matching, messaging, places, population
from engine.social import relationships, windows
from engine.social import kinds
from engine.social.kinds import Decision, recorded, stage_rank
from engine.social.payload import section

logger = logging.getLogger(__name__)

#: What a plan is of (plans.yaml `kinds`, checked equal): a venue's `kind` in venues.yaml, or a home.
PLAN_KINDS: tuple[str, ...] = kinds.PLAN_KINDS
#: The plans that meet at a home, so name no venue.
HOME_KINDS: tuple[str, ...] = ("their_place", "your_place")
#: The plan at their home: never with the partner who lives in the player's flat (T18 fix I2).
THEIR_PLACE = "their_place"
#: When a plan is, in words (§9.1).
WHENS: tuple[str, ...] = kinds.PLAN_WHENS
#: A plan's `status` (§9.1).
STATUSES: tuple[str, ...] = ("open", "met", "lapsed", "cancelled", "stood_up")
#: What `ask` takes for a meet-up (the request's `what`) and the person's own proposal (§10.5).
REQUEST = "meet"
PROPOSAL = "ask_meet"
#: The reason a plan's time does not suit them ("not tonight"), a request's `why`.
NOT_TONIGHT = "not_tonight"
#: The player's own home, where a `your_place` plan meets.
HOME = "apt_lounge"
#: The effect moves a regard row may hold.
MOVES: tuple[str, ...] = ("warmth", "trust", "interest")
#: Minutes between a plan made and their flake showing (§9.2): the next minute.
FLAKE_DELAY_HOURS = 1.0 / 60.0
#: The engine's own plan kind (§12.2, T18): the wedding, at the registry office. Never one the player asks for, so
#: it is not in `PLAN_KINDS` (plans.yaml's `kinds` and the `ask` verb's enum).
WEDDING = "wedding"
WEDDING_PLACE = "registry_office"


def _fault(key: str, message: str) -> ValueError:
    return ValueError(f"social: plans.yaml: {key}: {message}")


def _data() -> dict[str, Any]:
    return social.data("plans")


def _num(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def check_data(data: dict[str, Any]) -> None:
    """plans.yaml whole, at load: the first fault a ValueError naming file and key."""
    if list(data.get("kinds") or ()) != list(PLAN_KINDS):
        raise _fault("kinds", f"must be exactly {', '.join(PLAN_KINDS)}")
    patience = data.get("patience_hours")
    if not isinstance(patience, dict) or set(patience) != {"now", "tonight"}:
        raise _fault("patience_hours", "must give now and tonight")
    for key, value in patience.items():
        if not _num(value) or value <= 0:
            raise _fault(f"patience_hours.{key}", "must be hours above 0")
    for key in ("now_min_hours", "late_grace_hours", "lapse_after_hours"):
        if not _num(data.get(key)) or data[key] <= 0:
            raise _fault(key, "must be hours above 0")
    for key in ("soon_patience_episodes", "closed_kept"):
        value = data.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value < (1 if key.startswith("soon") else 0):
            raise _fault(key, "must be a whole number" + (" of 1 or more" if key.startswith("soon") else ""))
    cost = data.get("stood_up")
    if not isinstance(cost, dict) or not cost or not set(cost) <= set(MOVES) | {"mood"}:
        raise _fault("stood_up", f"must map {', '.join(MOVES)} to whole numbers")
    for key, value in cost.items():
        if key != "mood" and (not isinstance(value, int) or isinstance(value, bool)):
            raise _fault(f"stood_up.{key}", "must be a whole number")
    flake = (data.get("flake") or {}).get("stage_prob")
    if not isinstance(flake, dict) or "default" not in flake:
        raise _fault("flake.stage_prob", "must map stages to chances and give a default")
    for key, value in flake.items():
        if not _num(value) or not 0 <= value <= 1:
            raise _fault(f"flake.stage_prob.{key}", "must be a chance from 0 to 1")
    invite = data.get("invite")
    if not isinstance(invite, dict) or not isinstance(invite.get("prob"), list) or not invite["prob"]:
        raise _fault("invite.prob", "must list a chance for each depth")
    if not all(_num(p) and 0 <= p <= 1 for p in invite["prob"]):
        raise _fault("invite.prob", "each must be a chance from 0 to 1")
    if invite.get("window") not in windows.INITIATION_WINDOWS:
        raise _fault("invite.window", f"must be one of {', '.join(windows.INITIATION_WINDOWS)}")
    phrases = data.get("running_late")
    if not isinstance(phrases, list) or not all(isinstance(p, str) and p.strip() for p in phrases):
        raise _fault("running_late", "must list phrases")
    arrival = data.get("arrival")
    if arrival is not None:
        if not isinstance(arrival, dict) or set(arrival) - {"late_minutes", "wait_cap_hours"}:
            raise _fault("arrival", "must be {late_minutes, wait_cap_hours}")
        late = arrival.get("late_minutes", [0, 0])
        if (not isinstance(late, list) or len(late) != 2 or not all(_num(v) and v >= 0 for v in late)
                or late[0] > late[1]):
            raise _fault("arrival.late_minutes", "must be [low, high], minutes, 0 or more, low first")
        cap = arrival.get("wait_cap_hours", 2)
        if not _num(cap) or cap <= 0:
            raise _fault("arrival.wait_cap_hours", "must be hours above 0")


# -- reading ----------------------------------------------------------------------------------------------


def _rows(state: GameState) -> dict[str, Any]:
    return (state.social or {}).get("plans") or {}


def get(state: GameState, plan_id: str) -> Optional[dict[str, Any]]:
    row = _rows(state).get(plan_id)
    return row if isinstance(row, dict) else None


def _order(row: dict[str, Any]) -> tuple[float, int]:
    return float(row.get("made_at") or 0.0), int(str(row.get("id") or "pl0")[2:] or 0)


def open_for(state: GameState, pid: Optional[str] = None) -> list[dict[str, Any]]:
    """The plans still open, oldest first; only `pid`'s when given."""
    rows = [r for r in _rows(state).values()
            if isinstance(r, dict) and r.get("status") == "open" and (pid is None or r.get("pid") == pid)]
    return sorted(rows, key=_order)


def place_of(state: GameState, row: dict[str, Any]) -> str:
    """Where the plan meets: its venue, their home for `their_place`, the player's flat for `your_place`."""
    kind = row.get("kind")
    if kind == "their_place":
        return places.home_of(state, str(row["pid"]))
    if kind == "your_place":
        return HOME
    if kind == WEDDING:
        return WEDDING_PLACE
    return str(row.get("venue") or "")


_place_of = place_of


def arrives_at(row: dict[str, Any]) -> float:
    """When the person gets to a `now` / `tonight` plan's place (A4 W3): `arrives_at`, or `made_at` on a row
    written before it existed (they were taken to be there already)."""
    return float(row.get("arrives_at", row.get("made_at") or 0.0))


def has_arrived(row: dict[str, Any]) -> bool:
    """The person is at the plan's place (A4 W4): the `arrived` mark `plan_arrive` (or an in-person plan's
    make) writes; a row written before it existed counts as there."""
    return bool(row.get("arrived", "arrives_at" not in row))


def player_at(state: GameState, row: dict[str, Any], here: Optional[str] = None) -> bool:
    """The player is at the plan's place: any of the flat's seven places for `your_place` (A4 W2), else the
    place itself; never while the player is at work (the shift is left from the hall, which stays its place).
    Reads only."""
    if (state.social or {}).get("at_work"):
        return False
    here = state.location_id if here is None else here
    if row.get("kind") == "your_place":
        return places.is_flat(here)
    return place_of(state, row) == here


def _name(state: GameState, pid: str) -> str:
    return matching._name(state, pid)


def _person(state: GameState, pid: str) -> dict[str, Any]:
    return (state.social.get("people") or {}).get(pid) or {}


def words(kind: str, venue: str, when: str) -> str:
    """A plan in the engine's words, with no time on the clock: "Coffee at The Copper Kettle, tonight"."""
    if kind == "their_place":
        place = "their place"
    elif kind == "your_place":
        place = "yours"
    elif kind == WEDDING:
        place = f"The wedding, at the {places.label(WEDDING_PLACE)}"
    elif venue:
        place = places.place_line(venue)
    else:
        place = (kind or "meeting up").title()
    return f"{place}, {when}" if when else place


def row_words(row: dict[str, Any]) -> str:
    return words(str(row.get("kind") or ""), str(row.get("venue") or ""), str(row.get("when") or ""))


def _meet_stage() -> str:
    """The stage a meet moves to (relationships.yaml: the one whose trigger is `meet`)."""
    for name, row in (social.data("relationships").get("stages") or {}).items():
        if isinstance(row, dict) and row.get("trigger") == "meet":
            return str(name)
    raise ValueError("social: relationships.yaml: stages: no stage has trigger meet (spec §10.3)")


def _from_rank() -> int:
    """How far along a person must be to be asked: the meet stage's `from` (numbers)."""
    row = (social.data("relationships").get("stages") or {}).get(_meet_stage()) or {}
    return min((stage_rank(s) for s in row.get("from") or ()), default=0)


# -- who can be asked, and what they say -------------------------------------------------------------------


def _pending_request(state: GameState, pid: str) -> Optional[dict[str, Any]]:
    """`pid`'s open meet request either way."""
    for r in (state.social.get("requests") or {}).values():
        if r["pid"] == pid and r["what"] == REQUEST and r["status"] in ("pending", "later"):
            return r
    return None


def _ordinary(state: GameState, pid: str) -> list[dict[str, Any]]:
    """`pid`'s open plans but the wedding, which stands in no other plan's way (T18), oldest first."""
    return [r for r in open_for(state, pid) if r.get("kind") != WEDDING]


def _blocked(state: GameState, pid: str, when: Optional[str]) -> bool:
    """An open plan with `pid` stands in the way of a plan `when`: any does, but a `soon` one gives way to a `now` /
    `tonight` plan (spec 9.3: either side's ask turns it into one); `when` None (the menu) asks only of that."""
    rows = _ordinary(state, pid)
    return bool(rows) and (rows[0]["when"] != "soon" or when == "soon")


def ask_refusal(state: GameState, pid: str, when: Optional[str] = None, *, kind: str = "") -> str:
    """Why the player cannot ask `pid` to meet now (`when`: the time of day asked, when known; `kind`: the kind of
    plan asked, when known), in the engine's words; "" when they can."""
    name = _name(state, pid)
    t = messaging.thread(state, messaging.thread_for(state, pid) or "")
    if _gone(state, pid) or t is None:
        return f"{name} is no longer available."
    if t.get("closed"):
        return messaging._closed_reason(state, t)
    person = _person(state, pid)
    if stage_rank(person.get("stage")) < _from_rank() or not relationships.live(person):
        return f"It's too soon to ask {name} to meet."
    if _blocked(state, pid, when):
        return f"You already have plans with {name}."
    if _lives_here(state, pid, kind):
        return f"{name} lives with you."
    waiting = _pending_request(state, pid)
    if waiting is not None:
        return (f"You've already asked {name} to meet." if waiting["from"] == "player"
                else f"{name} has already asked to meet.")
    if relationships.asks_this_episode(state, pid, REQUEST) >= int(social.data("relationships")["asks"]["per_episode"]):
        return relationships.GIVE_IT_A_WHILE
    return ""


def _lives_here(state: GameState, pid: str, kind: str) -> bool:
    """A `their_place` plan with the partner who lives in the player's flat (T18 fix I2): their old home is not
    where they live now, so no such plan is made, asked for or offered."""
    return kind == THEIR_PLACE and relationships.household(state) == pid


def _gone(state: GameState, pid: str) -> bool:
    from engine.social import apps

    return apps.gone(state, pid)


def _tonight_span(state: GameState, pid: str, at: float) -> Optional[tuple[float, float]]:
    """Their evening, if it falls on this day (a plan for "tonight" never means tomorrow evening)."""
    span = windows.resolve(state, pid, str((_data().get("invite") or {}).get("window") or "evening"), at)
    return span if span is not None and span[0] < (at // 24.0 + 1.0) * 24.0 else None


def _why_not(state: GameState, pid: str, when: str, at: float) -> str:
    """Why `pid` cannot meet `when` at `at` ("" when they can): the `meet` commitment (growth.yaml `willing.meet`,
    §6.5), then their time (§4.2). Reads only. The reasons are a request's `why`s."""
    ok, why = growth.willing(state, pid, "meet")
    if not ok:
        return why or "not_yet"
    if when == "now":
        if not convo.available(state, pid, at).yes:
            return NOT_TONIGHT
        left = convo.boundary_minutes(state, pid, at)
        if left is not None and left < float(_data()["now_min_hours"]) * 60.0:
            return NOT_TONIGHT
    elif when == "tonight" and _tonight_span(state, pid, at) is None:
        return NOT_TONIGHT
    return ""


def _flake_drawn(state: GameState, pid: str) -> bool:
    """Whether they will cancel a plan just made (§9.3): their archetype's `flake_prob` joined with the
    relationship's `flake.stage_prob`, one draw on SOCIAL_SCENE (forced by a test, lesson 1). Call inside a
    `social_*` handler: the draw's counter is state (rule 3)."""
    arch = behaviour.archetype(population.profile(state, pid).archetype)
    table = (_data().get("flake") or {}).get("stage_prob") or {}
    stage = _person(state, pid).get("stage")
    by_stage = float(table.get(stage, table.get("default", 0.0)))
    chance = 1.0 - (1.0 - float(arch.flake_prob)) * (1.0 - by_stage)
    return behaviour.person_rng(state, SOCIAL_SCENE, pid).random() < chance


def _patience(when: str) -> float:
    return float((_data().get("patience_hours") or {}).get(when, 0.0))


def _arrival(state: GameState, row: dict[str, Any], effect: dict[str, Any], at: float) -> tuple[float, float]:
    """(due_at, arrives_at) for a `now` / `tonight` row (A4 W3/W4). In person: both `at`, the person comes WITH the
    player (C1). Their place: home already. Else their travel (a venue's, or their home's for `your_place`, I3) plus
    a lateness keyed on the plan id: a counterless `stable_rng`, so it replays and moves no other draw (rule 4)."""
    if effect.get("in_person"):
        return at, at
    pid, when = str(row["pid"]), str(row["when"])
    due = at
    if when == "tonight":
        span = _tonight_span(state, pid, at)
        due = max(at, span[0]) if span else at
    if row["kind"] == THEIR_PLACE:
        return due, due
    place = places.home_of(state, pid) if row["kind"] == "your_place" else place_of(state, row)
    lo, hi = (_data().get("arrival") or {}).get("late_minutes", [0, 20])
    late = stable_rng(state.rng_seed, f"plan_arrival:{row['id']}").uniform(float(lo), float(hi))
    return due, due + (places.travel_minutes(place) + late) / 60.0


def wait_cap_hours() -> float:
    """How long "Wait for {name}" waits at most (plans.yaml `arrival.wait_cap_hours`, A4 W2)."""
    return float((_data().get("arrival") or {}).get("wait_cap_hours", 2))


def _set_arrival(state: GameState, row: dict[str, Any], effect: dict[str, Any], at: float) -> None:
    """A `now` / `tonight` row's `due_at`, `arrives_at` and `arrived` (inside the `social_plan` handler)."""
    if row["when"] == "soon":
        return
    due, arrives = _arrival(state, row, effect, at)
    row.update(due_at=round(due, 4), arrives_at=round(arrives, 4), arrived=bool(effect.get("in_person")))


def _normal(kind: str, venue: str, when: str) -> tuple[str, str, str]:
    """A plan's three words, checked: a kind and a venue the data knows (or neither), `when` one of WHENS."""
    if when not in WHENS:
        raise ValueError(f"plans: {when!r} is not one of {', '.join(WHENS)}")
    if kind and kind not in PLAN_KINDS:
        raise ValueError(f"plans: {kind!r} is no kind of plan")
    if venue and venue not in places.venue_ids():
        raise ValueError(f"plans: {venue!r} is no venue")
    return kind, ("" if kind in HOME_KINDS else venue), when


def make(state: GameState, pid: str, *, kind: str, when: str, venue: str = "", by: str = "player",
         at: Optional[float] = None, migrated: bool = False, in_person: bool = False) -> Optional[dict[str, Any]]:
    """
    A plan with `pid` (spec §9.2): the row, or None when they will not (an open plan with them, the
    `meet` commitment, their time). `migrated=True` (T20 only) carries a v0.22.0 agreed meet over and
    skips the willingness, their time and the flake. `in_person=True` is a scene's closer (§10.4): the
    two of them are together and the closer was offered on its own commitment, so their time and the
    flake are not asked. The venue is the caller's, else the engine's pick by kind and shared hobbies; a
    `their_place` / `your_place` plan names none.
    """
    kind, venue, when = _normal(kind, venue, when)
    at = state.world_clock_hours if at is None else float(at)
    if _lives_here(state, pid, kind) or _blocked(state, pid, when) or (not (migrated or in_person) and _why_not(state, pid, when, at)):
        return None
    standing = _ordinary(state, pid)
    if standing:                                          # a `soon` plan turned into a `now` / `tonight` one (9.3)
        made = apply_effect(state, {"type": "social_plan", "op": "upgrade", "plan_id": standing[0]["id"],
                                    "kind": kind, "venue": venue, "when": when, "by": by, "at": at,
                                    "migrated": bool(migrated), "in_person": bool(in_person)})
    else:
        made = apply_effect(state, {"type": "social_plan", "op": "make", "pid": pid, "kind": kind, "venue": venue,
                                    "when": when, "by": by, "at": at, "migrated": bool(migrated),
                                    "in_person": bool(in_person)})
    return made["plan"] if made.get("ok") else None


def make_wedding(state: GameState, pid: str, *, at: Optional[float] = None) -> Optional[dict[str, Any]]:
    """The wedding's plan (§12.2, T18): queued by life_events.yaml's `wedding` row for a couple engaged
    `wedding_after_days`, at the registry office, `when: soon`. None when one is open already. Inside a
    `social_*` handler (the life event's) or anywhere: it is the `social_plan` effect either way."""
    if any(r.get("kind") == WEDDING for r in open_for(state, pid)):
        return None
    made = apply_effect(state, {"type": "social_plan", "op": "make", "pid": pid, "kind": WEDDING, "venue": "",
                                "when": "soon", "by": "person", "in_person": True,
                                "at": state.world_clock_hours if at is None else float(at)})
    return made["plan"] if made.get("ok") else None


# -- the effect (rule 3) -------------------------------------------------------------------------------------


def _line(state: GameState, pid: str, text: str, at: float) -> None:
    """An engine line in the person's thread (inside a handler only)."""
    t = messaging.thread(state, messaging.thread_for(state, pid) or "")
    if t is not None:
        matching._system_message(state, t, text, at)


def _moved(state: GameState, pid: str, moves: dict[str, Any], at: float) -> None:
    """An engine move of regard (exact: the engine's own), inside a handler."""
    moves = {k: v for k, v in (moves or {}).items() if k in MOVES + ("mood",)}
    if moves:
        apply_effect(state, {"type": "social_regard", "pid": pid, "exact": True, "at": at, **moves})


def _their_pace(state: GameState, pid: str, at: float) -> float:
    """When they would write back about it, at their own pace (a draw on SOCIAL_PACE, inside a handler)."""
    person = population.profile(state, pid)
    arch = behaviour.archetype(person.archetype)
    due = at + behaviour.lognormal_minutes(behaviour.person_rng(state, SOCIAL_PACE, pid), *arch.reply_minutes) / 60.0
    return behaviour.next_awake(person, due) if behaviour.status_at(person, due) == "asleep" else due


def _close_row(row: dict[str, Any], status: str, at: float) -> None:
    row.update(status=status, ended_at=round(at, 4))


@effect_kind("social_plan")
@recorded
def _e_plan(state: GameState, effect: dict[str, Any], ctx: EffectContext) -> dict[str, Any]:
    """
    Engine-only: a plan row's change (spec §9). `op: make` (a new row, the flake drawn for `now` / `tonight`
    and its events queued), `pick` (the engine's venue for a plan of theirs), `arrived` (they are at its place,
    A4 W4), `met`, `lapse`, `cancel` (they
    cannot make it, or they left), `stood_up` (the player came late: the cost and their message), `late`
    (patience extended once), `upgrade` (a `soon` plan becomes a `now` / `tonight` one, spec 9.3) and `forget` (a
    closed row leaves state).
    """
    if not state.social:
        return {"type": "social_plan", "ok": False, "text": "no social slice"}
    op = str(effect.get("op") or "")
    at = float(effect["at"]) if effect.get("at") is not None else state.world_clock_hours
    if op == "make":
        return _make(state, effect, at)
    if op == "pick":
        pid = str(effect["pid"])
        venue = places.pick_venue(state, pid, kind=str(effect.get("kind") or ""))
        relationships.touch(state.social.setdefault("people", {}).setdefault(pid, {}))
        return {"type": "social_plan", "ok": True, "text": f"picked {venue}", "venue": venue,
                "kind": str((places.venue(venue) or {}).get("kind") or "")}
    row = get(state, str(effect.get("plan_id") or ""))
    if row is None:
        return {"type": "social_plan", "ok": False, "text": f"no plan {effect.get('plan_id')!r}"}
    pid, plan_id = str(row["pid"]), str(row["id"])
    if op == "forget":
        if row["status"] == "open":
            return {"type": "social_plan", "ok": False, "text": f"{plan_id} is still open"}
        del _rows(state)[plan_id]
        return {"type": "social_plan", "ok": True, "text": f"{plan_id} forgotten"}
    if row["status"] != "open":
        return {"type": "social_plan", "ok": False, "text": f"{plan_id} is {row['status']}"}
    person = state.social.setdefault("people", {}).setdefault(pid, {})
    if op == "late":
        if row.get("late") or row["when"] == "soon":
            return {"type": "social_plan", "ok": False, "text": f"{plan_id} cannot be extended"}
        row["late"] = True
        row["patience_hours"] = float(row["patience_hours"]) + float(_data()["late_grace_hours"])
        _push_lapse(state, row)                          # the quiet close moves with the new end (C1)
        return {"type": "social_plan", "ok": True, "text": f"{plan_id} extended", "patience_hours": row["patience_hours"]}
    if op == "upgrade":
        return _upgrade(state, row, effect, at)
    if op == "arrived":
        row["arrived"] = True                            # they are at the place (A4 W4, `plan_arrive`)
        relationships.touch(person)
        return {"type": "social_plan", "ok": True, "text": f"{plan_id}: {pid} arrived"}
    if op == "met":
        _close_row(row, "met", at)
        relationships.touch(person)
        return {"type": "social_plan", "ok": True, "text": f"{plan_id} met", "status": "met", "save_reason": "stage"}
    if op in ("lapse", "cancel"):
        status = "lapsed" if op == "lapse" else "cancelled"
        _close_row(row, status, at)
        if effect.get("line"):
            _line(state, pid, str(effect["line"]), at)
        return {"type": "social_plan", "ok": True, "text": f"{plan_id} {status}", "status": status}
    if op == "stood_up":
        _close_row(row, "stood_up", at)
        name = _name(state, pid)
        _moved(state, pid, _data()["stood_up"], at)
        relationships.add_history(state, pid, "stood_up", f"You didn't turn up to {row_words(row)}", at=at)
        _line(state, pid, f"You didn't turn up. {name} waited.", at)
        tid = messaging.thread_for(state, pid)
        if tid and not person.get("ghosted"):
            messaging.queue_due(state, pid, tid, Decision(situation="stood_up", plan_id=plan_id),
                                _their_pace(state, pid, at))
        return {"type": "social_plan", "ok": True, "text": f"{plan_id} stood up", "status": "stood_up",
                "save_reason": "stage"}
    return {"type": "social_plan", "ok": False, "text": f"{op!r} is no plan op"}


def _make(state: GameState, effect: dict[str, Any], at: float) -> dict[str, Any]:
    pid = str(effect["pid"])
    kind, venue, when = str(effect.get("kind") or ""), str(effect.get("venue") or ""), str(effect["when"])
    if not kind:
        kind = str((places.venue(venue) or {}).get("kind") or "") if venue else ""
        kind = kind if kind in PLAN_KINDS else "coffee"
    if kind in HOME_KINDS or kind == WEDDING:
        venue = ""
    elif not venue:
        venue = places.pick_venue(state, pid, kind=kind)
    counters = state.social.setdefault("counters", {})
    counters["plan"] = int(counters.get("plan", 0)) + 1
    plan_id = f"pl{counters['plan']}"
    person = state.social.setdefault("people", {}).setdefault(pid, {})
    row = {"id": plan_id, "pid": pid, "kind": kind, "venue": venue, "when": when, "made_at": round(at, 4),
           "patience_hours": _patience(when), "by": str(effect.get("by") or "player"), "status": "open",
           "episodes_at": int(person.get("episodes_done", 0))}
    state.social.setdefault("plans", {})[plan_id] = row
    _set_arrival(state, row, effect, at)
    relationships.touch(person)
    _schedule(state, row, effect, at)
    _line(state, pid, f"{_name(state, pid)} is in: {row_words(row)}.", at)
    return {"type": "social_plan", "ok": True, "text": f"made {plan_id}", "plan": dict(row), "save_reason": "stage"}


def _push_once(state: GameState, at: float, row: dict[str, Any], kind: str) -> None:
    """Queue the row's `kind` event at `at`, replacing any it already had (an upgrade, a `late`): one each.
    Inside the `social_plan` handler, so the queue's write is that effect's (rule 3)."""
    plan_id = str(row["id"])
    events.cancel(state, str(row["pid"]), {kind}, where=lambda e: e.get("plan_id") == plan_id)
    events.push(state, at, str(row["pid"]), kind, plan_id=plan_id)


def _push_lapse(state: GameState, row: dict[str, Any]) -> None:
    """The quiet close: past the person's arrival, their patience (any grace in it) and `lapse_after_hours`."""
    _push_once(state, arrives_at(row) + float(row["patience_hours"]) + float(_data()["late_grace_hours"])
               + float(_data()["lapse_after_hours"]), row, "plan_lapse")


def _schedule(state: GameState, row: dict[str, Any], effect: dict[str, Any], at: float) -> None:
    """A `now` / `tonight` plan's events, each replacing the row's earlier one of its kind: its quiet close; their
    arrival (`plan_arrive`; never for a plan made in person, where they came with the player, C1); and (never for
    a plan they proposed, a migrated one, or one made in person) the flake draw (spec 9.3)."""
    if row["when"] == "soon":
        return
    pid, plan_id = str(row["pid"]), str(row["id"])
    _push_lapse(state, row)
    if not effect.get("in_person"):
        _push_once(state, arrives_at(row), row, "plan_arrive")
    if (not effect.get("migrated") and not effect.get("in_person") and str(effect.get("by") or "player") != "person"
            and _flake_drawn(state, pid)):
        events.push(state, at + FLAKE_DELAY_HOURS, pid, "plan_flake", plan_id=plan_id)


def _upgrade(state: GameState, row: dict[str, Any], effect: dict[str, Any], at: float) -> dict[str, Any]:
    """A `soon` plan turned into the `now` / `tonight` plan asked for (spec 9.3): the same row and id, the kind and
    venue the ask names (else kept), its patience and events those of the new time of day."""
    when = str(effect["when"])
    if row["when"] != "soon" or when == "soon":
        return {"type": "social_plan", "ok": False, "text": f"{row['id']} cannot be upgraded"}
    kind, venue = str(effect.get("kind") or ""), str(effect.get("venue") or "")
    if kind or venue:
        if not kind:
            kind = str((places.venue(venue) or {}).get("kind") or row["kind"])
        row["kind"] = kind
        row["venue"] = "" if kind in HOME_KINDS else (venue or places.pick_venue(state, str(row["pid"]), kind=kind))
    row.update(when=when, made_at=round(at, 4), patience_hours=_patience(when),
               by=str(effect.get("by") or row["by"]))
    _set_arrival(state, row, effect, at)                 # from the upgrade's `at`, keyed on the same id (C1)
    pid = str(row["pid"])
    relationships.touch(state.social.setdefault("people", {}).setdefault(pid, {}))
    _schedule(state, row, effect, at)
    _line(state, pid, f"{_name(state, pid)} is in: {row_words(row)}.", at)
    return {"type": "social_plan", "ok": True, "text": f"{row['id']} upgraded", "plan": dict(row),
            "save_reason": "stage"}


# -- events -------------------------------------------------------------------------------------------------


@events.handles("plan_flake")
def _on_flake(state: GameState, event: dict[str, Any]) -> dict[str, Any]:
    """They cannot make it after all (§9.3): the plan is cancelled and their message about it is due now."""
    row = get(state, str(event.get("plan_id") or ""))
    if row is None or row["status"] != "open":
        return {"ok": False, "why": "not open"}
    pid, at = str(row["pid"]), float(event["at"])
    apply_effect(state, {"type": "social_plan", "op": "cancel", "plan_id": row["id"], "at": at})
    tid = messaging.initiation_thread(state, pid)
    if tid:
        messaging.queue_due(state, pid, tid, Decision(situation="flake", plan_id=str(row["id"])), at)
    return {"ok": True, "flaked": row["id"]}


@events.handles("plan_lapse")
def _on_lapse(state: GameState, event: dict[str, Any]) -> dict[str, Any]:
    """A plan nobody went to closes quietly; or (`request_id`) their request for a `now` / `tonight` plan the
    player never answered lapses, answered `no` at no cost."""
    at = float(event["at"])
    if event.get("request_id"):
        return _lapse_request(state, str(event["request_id"]), at)
    row = get(state, str(event.get("plan_id") or ""))
    if row is None or row["status"] != "open":
        return {"ok": False, "why": "not open"}
    return apply_effect(state, {"type": "social_plan", "op": "lapse", "plan_id": row["id"], "at": at})


@events.handles("plan_arrive")
def _on_plan_arrive(state: GameState, event: dict[str, Any]) -> dict[str, Any]:
    """The person is there (A4 W4, I4): recorded (`social_plan` `arrived`); and, when the player is not, their
    message saying so (situation `arrived`). Never opens a scene: this runs inside `clock.advance_time`, maybe
    mid-travel. `meet_if_here` opens it where the clock has stopped."""
    row = get(state, str(event.get("plan_id") or ""))
    if row is None or row["status"] != "open":
        return {"ok": True, "quiet": True}
    at = float(event["at"])
    apply_effect(state, {"type": "social_plan", "op": "arrived", "plan_id": row["id"], "at": at})
    pid = str(row["pid"])
    if player_at(state, row):
        if state.social.get("phone_up"):                 # there, eyes on the phone: no model, a buzz (fix round 1, I3)
            tid = messaging.thread_for(state, pid)
            t = messaging.thread(state, tid or "")
            if t is not None:
                messaging.notify(state, str(t.get("app") or ""), str(tid), pid, "arrived", f"{_name(state, pid)}'s here",
                                 at=at)
    elif row["kind"] != THEIR_PLACE:                     # at their own home there is nothing to say
        tid = messaging.initiation_thread(state, pid)
        if tid and not _person(state, pid).get("ghosted"):
            messaging.queue_due(state, pid, tid, Decision(situation="arrived", plan_id=str(row["id"])), at)
    return {"ok": True, "arrived": row["id"]}


def _lapse_request(state: GameState, request_id: str, at: float) -> dict[str, Any]:
    request = (state.social.get("requests") or {}).get(request_id)
    if request is None or request.get("what") != REQUEST or request.get("status") not in ("pending", "later"):
        return {"ok": False, "why": "answered"}
    pid = str(request["pid"])
    apply_effect(state, {"type": "social_request", "op": "answer", "request_id": request_id, "status": "no", "at": at})
    request["lapsed"] = True
    t = messaging.thread(state, messaging.thread_for(state, pid) or "")
    if t is not None and matching.listed(t) and not _gone(state, pid) and _person(state, pid).get("stage") != "ended":
        _line(state, pid, f"{_name(state, pid)}'s plan for {words(str(request.get('kind') or ''), str(request.get('venue') or ''), str(request.get('when') or ''))} lapsed.", at)
    return {"ok": True, "lapsed": request_id}


def on_episode_close(state: GameState, pid: str) -> None:
    """A conversation with `pid` ended (`convo`'s `close` op, inside its handler): a `soon` plan of theirs that has
    waited `soon_patience_episodes` of their episodes since it was made lapses quietly (§9.3; pre-flight F30)."""
    done = int(_person(state, pid).get("episodes_done", 0))
    patience = int(_data().get("soon_patience_episodes", 6))
    for row in _ordinary(state, pid):                    # the wedding waits for the player (T18)
        if row["when"] == "soon" and done - int(row.get("episodes_at", 0)) >= patience:
            apply_effect(state, {"type": "social_plan", "op": "lapse", "plan_id": row["id"]})


def call_off(state: GameState, pid: str, at: float, *, kinds: Optional[Sequence[str]] = None) -> int:
    """`pid` left (unmatched, blocked or ended): every plan with them is called off at no cost, with an engine
    line; only those of `kinds` when given (faded or expired: the wedding's, T18). Called only inside a
    `social_*` handler. The number called off."""
    rows = [r for r in open_for(state, pid) if kinds is None or r.get("kind") in kinds]
    for row in rows:
        apply_effect(state, {"type": "social_plan", "op": "cancel", "plan_id": row["id"], "at": at,
                             "line": f"Plans with {_name(state, pid)} are off: {row_words(row)}."})
    return len(rows)


def running_late(state: GameState, pid: str) -> bool:
    """The player said they are running late (§9.3): patience of a `now` / `tonight` plan with `pid` still ahead is
    extended once by `late_grace_hours`. Whether it was."""
    now = state.world_clock_hours
    for row in open_for(state, pid):
        if row["when"] != "soon" and now <= arrives_at(row) + float(row["patience_hours"]):
            return bool(apply_effect(state, {"type": "social_plan", "op": "late", "plan_id": row["id"]}).get("ok"))
    return False


def on_player_text(state: GameState, pid: str, text: str) -> bool:
    """The player's words in a thread with `pid`: a "running late" phrase extends a plan's patience (`running_late`)."""
    from engine.social import agreement

    phrases = tuple(str(p) for p in _data().get("running_late") or ())
    if phrases and agreement.stated(str(text), phrases):
        return running_late(state, pid)
    return False


def forget_closed(state: GameState) -> int:
    """Bounded state (spec §17.2), made at every save (`saves.compact`): per person, closed plans past the newest
    plans.yaml `closed_kept` leave state through `social_plan` `op: forget`, oldest first. How many left."""
    keep = max(0, int(_data().get("closed_kept", 3)))
    by_person: dict[str, list[dict[str, Any]]] = {}
    for row in _rows(state).values():
        if isinstance(row, dict) and row.get("status") != "open":
            by_person.setdefault(str(row["pid"]), []).append(row)
    gone = 0
    for pid in sorted(by_person):
        closed = sorted(by_person[pid], key=_order)
        for row in closed[:max(0, len(closed) - keep)]:
            gone += bool(apply_effect(state, {"type": "social_plan", "op": "forget", "plan_id": row["id"]}).get("ok"))
    return gone


# -- arriving (§8.5, §9.3) ------------------------------------------------------------------------------------


def _forget_resume(state: GameState) -> None:
    if state.social.get("resume"):                       # picking a plan up ends a cut-short activity (§8.4)
        apply_effect(state, {"type": "social_settings", "field": "resume", "value": None})


def _past_patience(row: dict[str, Any], now: float) -> bool:
    """Patience runs from their arrival, never from when the plan was made (A4 W3)."""
    return now - arrives_at(row) > float(row["patience_hours"])


def arrive(state: GameState, location: str) -> dict[str, Any]:
    """The player arrived at `location` (from `world.go`). A `now`/`tonight` plan there whose person has arrived
    opens its scene; one past its patience (counted from their arrival) is stood up; one whose person is still on
    the way waits ("Wait for {name}"; `meet_if_here` at their arrival); with no plan it is a quiet visit (§8.5,
    §9.3, A4 W2-W4)."""
    now = state.world_clock_hours
    for row in open_for(state):
        wedding = row.get("kind") == WEDDING
        if place_of(state, row) != location or (row["when"] == "soon" and not wedding):
            continue
        if wedding and str(_person(state, str(row["pid"])).get("stage") or "") != "engaged":
            continue                                     # the wedding opens only while the two are engaged (T18)
        if not wedding and _past_patience(row, now):
            _forget_resume(state)
            apply_effect(state, {"type": "social_plan", "op": "stood_up", "plan_id": row["id"], "at": now})
            return {"stood_up": row["id"], "quiet": True}
        if not wedding and not has_arrived(row):
            continue                                     # on their way: the player waits for them (A4 W2)
        _forget_resume(state)
        return _on_arrival_scene(state, row, location)
    return {"quiet": True}


def meet_if_here(state: GameState) -> dict[str, Any]:
    """
    Open the scene of an arrived `now` / `tonight` plan whose place is where the player is, the phone down and no
    scene open (A4 W2). Called only where the clock has stopped (I4): `world.go`, `put_down`, the end of a `do`,
    "Wait for {name}", `end_scene` with `then: stay`, and the world turn after its drain. A `your_place` plan meets
    in the lounge, whichever of the flat's places the player is in ("you let them in"). While the player is at
    the place the person never stands them up, however long the phone or another scene kept them (fix round 1,
    I3): patience is judged only on arriving from elsewhere (`arrive`).
    """
    if not state.social or social.scene_open(state) or state.social.get("phone_up"):
        return {"quiet": True}
    for row in open_for(state):
        if row["when"] == "soon" or row.get("kind") == WEDDING or not has_arrived(row) or not player_at(state, row):
            continue
        if row["kind"] == "your_place" and state.location_id != HOME:
            apply_effect(state, {"type": "social_go", "op": "place", "to": HOME})    # 0 minutes: you let them in
        _forget_resume(state)
        return _on_arrival_scene(state, row, state.location_id)
    return {"quiet": True}


def waiting_here(state: GameState) -> list[dict[str, Any]]:
    """The open `now` / `tonight` plans whose place is where the player is and whose person is not there yet,
    oldest first: what "Wait for {name}" is offered for (A4 W2). Reads only."""
    return [r for r in open_for(state) if r["when"] != "soon" and r.get("kind") != WEDDING
            and not has_arrived(r) and player_at(state, r)]


def _on_arrival_scene(state: GameState, row: dict[str, Any], location: str) -> dict[str, Any]:
    """The plan is kept: its scene opens (spec §10.1, `scene.open_scene`, which records the plan `met`)."""
    from engine.social import scene   # lazily: scene imports this module's peers

    return scene.open_scene(state, str(row["pid"]), location, plan_id=str(row["id"]), kind=str(row.get("kind") or ""))


# -- the player's ask, and theirs ---------------------------------------------------------------------------


def ask_fields(args: Optional[dict[str, Any]]) -> dict[str, str]:
    """An `ask {what: meet}`'s `kind`, `venue` and `when` as the request keeps them (`when` defaults to `soon`:
    willingness alone, so an ask with none is the gentlest). A ValueError for a word the data does not know."""
    args = dict(args or {})
    kind, venue, when = _normal(str(args.get("kind") or ""), str(args.get("venue") or ""),
                                str(args.get("when") or "soon"))
    return {"kind": kind, "venue": venue, "when": when}


def answer_ask(state: GameState, pid: str, request: dict[str, Any], at: float) -> bool:
    """
    The player's `ask {what: meet}` decided at their read (inside the read's handler): yes when the `meet`
    commitment holds and they have the time, else no with its `why`; the request answered and, on yes, the
    plan made (the venue theirs to pick when the player named none). Whether they said yes.
    """
    kind, venue, when = str(request.get("kind") or ""), str(request.get("venue") or ""), str(request.get("when") or "soon")
    why = "open" if _blocked(state, pid, when) else _why_not(state, pid, when, at)
    made = None if why else make(state, pid, kind=kind, when=when, venue=venue, by="player", at=at)
    effect = {"type": "social_request", "op": "answer", "request_id": request["id"],
              "status": "yes" if made else "no", "at": at}
    if not made and why and why in relationships.ASK_WHYS:
        effect["why"] = why
    apply_effect(state, effect)
    return made is not None


def proposal_open(state: GameState, pid: str) -> bool:
    """§10.5 `ask_meet`'s gate beyond its data row: numbers or past it, willing to meet (§9.2: the `meet`
    commitment, not the v0.22 stage gate), nothing asked, and no plan but a `soon` one (an ask turns it into a
    `tonight` plan, §9.3)."""
    stage = _person(state, pid).get("stage")
    return (stage_rank(stage) >= _from_rank() and stage != "winding_down" and not _blocked(state, pid, "tonight")
            and _pending_request(state, pid) is None and growth.willing(state, pid, "meet")[0])


def _their_request(state: GameState, pid: str, thread_id: str, kind: str, venue: str, when: str,
                   at: Optional[float]) -> dict[str, Any]:
    effect: dict[str, Any] = {"type": "social_request", "op": "create", "pid": pid, "from": "them", "what": REQUEST,
                              "thread_id": thread_id, "kind": kind, "venue": venue, "when": when}
    if at is not None:
        effect["at"] = float(at)
    made = apply_effect(state, effect)
    if made.get("ok") and when != "soon":                # unanswered past its patience, it lapses
        made_at = float(at) if at is not None else state.world_clock_hours
        events.push(state, made_at + _patience(when), pid, "plan_lapse", request_id=made["request"]["id"])
    return made


def propose_theirs(state: GameState, pid: str, thread_id: str, at: Optional[float] = None) -> dict[str, Any]:
    """
    Their `ask_meet` (§10.5): the engine picks the venue and, if their evening is free, asks for `tonight` (else
    `soon`), as a request to the player. Called by `relationships.apply_proposal`, re-checked there.
    """
    when_at = state.world_clock_hours if at is None else float(at)
    when = "tonight" if not _why_not(state, pid, "tonight", when_at) else "soon"
    choice = apply_effect(state, {"type": "social_plan", "op": "pick", "pid": pid})
    made = _their_request(state, pid, thread_id, str(choice.get("kind") or ""), str(choice["venue"]), when, at)
    return {"ok": bool(made.get("ok")), "request_id": made["request"]["id"]}


def still_open(state: GameState, request: dict[str, Any]) -> bool:
    """Their meet request can still be said yes to: they are still willing and free, nothing is planned with
    them, and a `now` / `tonight` ask is still inside its patience."""
    pid, when = str(request["pid"]), str(request.get("when") or "soon")
    if _gone(state, pid) or _blocked(state, pid, when):
        return False
    if when != "soon" and state.world_clock_hours - float(request["at"]) > _patience(when):
        return False
    return not _why_not(state, pid, when, state.world_clock_hours)


def accept_theirs(state: GameState, request: dict[str, Any]) -> dict[str, Any]:
    """The player's yes to their ask: re-checked now (`still_open`), then the plan made."""
    if not still_open(state, request):
        return {"ok": False, "error": "That isn't on the table any more."}
    pid = str(request["pid"])
    made = make(state, pid, kind=str(request.get("kind") or ""), when=str(request.get("when") or "soon"),
                venue=str(request.get("venue") or ""), by="person")
    if made is None:
        return {"ok": False, "error": "That isn't on the table any more."}
    return {"ok": True, "plan_id": made["id"]}


def _daily_invites(state: GameState) -> None:
    """The `daily` step: each live person's own invitation for the evening (plans.yaml `invite`), one at most, as a
    request of theirs and a message in their thread inside their window. Nobody asks mid-conversation, with a
    plan open or an ask waiting, or before the stage and the `meet` commitment hold."""
    day_at = events.daily_at(state)
    rule = _data().get("invite") or {}
    prob = [float(p) for p in rule.get("prob") or ()]
    if not prob:
        return
    for pid in messaging.live_people(state):
        person = _person(state, pid)
        if (person.get("ghosted") or convo.episode(state, pid) is not None or not proposal_open(state, pid)
                or _gone(state, pid)):
            continue
        chance = prob[min(growth.depth(state, pid), len(prob) - 1)]
        span = windows.resolve(state, pid, str(rule["window"]), day_at)
        if chance <= 0 or span is None or span[0] >= day_at + 24.0:
            continue
        rng = behaviour.person_rng(state, SOCIAL_SCENE, pid)
        if rng.random() >= chance:
            continue
        at = span[0] + rng.random() * (span[1] - span[0])
        if _why_not(state, pid, "tonight", at):
            continue
        tid = messaging.initiation_thread(state, pid)
        if tid is None:
            continue
        choice = apply_effect(state, {"type": "social_plan", "op": "pick", "pid": pid})
        made = _their_request(state, pid, tid, str(choice.get("kind") or ""), str(choice["venue"]), "tonight", at)
        if made.get("ok"):
            messaging.queue_due(state, pid, tid, Decision(situation="invite", request_id=made["request"]["id"]), at)


if _daily_invites not in events.daily_hooks:
    events.daily_hooks.append(_daily_invites)


# -- the payload (spec §17.3) ----------------------------------------------------------------------------------


@section("plans", time_varying=True)
def _plans_section(state: GameState, session: Any) -> list[dict[str, Any]]:
    """The open plans, oldest first, in words: the player sees a place and a time of day, never when it was made,
    how long it waits or what the person drew (lesson 7)."""
    out: list[dict[str, Any]] = []
    for row in open_for(state):
        pid = str(row["pid"])
        if _gone(state, pid):
            continue
        venue = places.venue(str(row.get("venue") or ""))
        out.append({"id": row["id"], "pid": pid, "name": _name(state, pid), "kind": row["kind"],
                    "venue": str(row.get("venue") or ""), "venue_label": str(venue.get("label") or ""),
                    "place": words(str(row["kind"]), str(row.get("venue") or ""), ""),
                    "when": row["when"], "words": row_words(row), "by": row.get("by")})
    return out


@section("meet_options")
def _meet_options_section(state: GameState, session: Any) -> dict[str, Any]:
    """What an `ask {what: meet}` may name (the contact card's planner): every venue with its words, the plan
    kinds and when they can be. The data's, so it never moves with time; whether a person says yes is the engine's."""
    hoods = {str(r.get("id")): str(r.get("label") or r.get("id")) for r in population.table("neighbourhoods")
             if isinstance(r, dict)}
    return {
        "venues": [{"id": str(r["id"]), "label": str(r.get("label") or r["id"]), "place": places.place_line(str(r["id"])),
                    "kind": str(r.get("kind") or ""),
                    "neighbourhood": hoods.get(str(r.get("neighbourhood") or ""), str(r.get("neighbourhood") or ""))}
                   for r in places.venues() if r.get("id")],
        "kinds": list(PLAN_KINDS),
        "whens": list(WHENS),
    }
