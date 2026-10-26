"""
The world outside the phone (v0.23.0 spec §8.2-§8.5, §20.1's world side; T11).

READ RECEIPTS is played on two layers (§14.1): the phone, whose actions are mechanics with no model
(`turn.run_mechanics`), and the WORLD, an ordinary narrated turn (`default_state.run_turn`) with its
own verbs, `do {activity}` and `go {to}`. This module is the world's half:

- **Phone up, phone down (§8.2).** One saved flag, `state.social["phone_up"]`, written only through
  `social_settings`. Any phone action picks the phone up (`pick_up`, `run_mechanics`' first step);
  the phone verb `put_down` puts it down. While it is up a world turn is refused with
  `PHONE_UP_REFUSAL`, early by the choice route and again under the turn lock (`world_turn_refusal`).
- **Activities (§8.4).** `activities.yaml` beside `paths.locations` (Plan decision 6), checked at
  load (`check_activities`). `do` spends an activity's minutes, or runs it until a clock key;
  an `interruptible` one advances event by event and stops at the first new notification that may
  wake the player (`advance_interruptible`, Plan decision 13). Sleep runs to the player's waking
  band at least `clock.min_sleep_hours` ahead (Plan decision 12). At work the player stays at work
  (`at_work`, `work_until`) and only `carry_on_working` and `leave_early` are offered (m11).
- **Going out (§8.5).** `go` reaches the venues, the cast's homes and the registry office, which
  have no edges (tagged `sentinel`): the open plans' destinations, then the venues ranked by the
  player's shared hobbies and last visit, at most eight. "Head home" comes FIRST from every place
  outside the flat and building and is never gated (pre-flight F33, Plan decision 25). The travel
  is an action's cost (`clock.advance_time`); the `social_go` effect writes the place. The phone's
  Places app (`places_targets`, no cap) lists every venue.
- **The narrator's view (§8.3).** `narration_block`, rendered by `governance.SocialWorld`: where
  the player is and the buzz (count and names, never a message's words), and during a scene who the
  player is with (`scene.narration_line`).
- **Scenes (§10.1, T13).** While a scene is open (`social.scene_open`) the turn's verbs are the
  scene's (`scene_verbs`, delegating to `engine/social/scene.py`): `go` only through a closer, and
  `do` only for scenes.yaml's shared activities, done together and never cut short by the phone.

Rule 6: sleep is offered in the bedroom with no gate, and "Head home" has no gate. Rule 12: an
activity is a time and a place, nothing more.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from engine import social
from engine.game import clock
from engine.game.effects import EffectContext, apply_effect, effect_kind
from engine.game.intents import IntentVerb
from engine.game.state import GameState
from engine.social import places, windows
from engine.social.kinds import recorded
from engine.social.payload import section

logger = logging.getLogger(__name__)

#: What a world turn is answered while the phone is up (§8.2).
PHONE_UP_REFUSAL = "Put the phone down first."

#: The player's flat's entry room: where "Head home" goes (§8.5).
HOME = "apt_lounge"
HOME_LABEL = "Head home"

#: Every option list a world verb offers is capped like the engine's own (`intents._MAX_OPTIONS`).
MAX_OPTIONS = 8

#: The clock keys an activity may run `until` (§8.4).
UNTIL_KEYS: tuple[str, ...] = ("morning", "evening", "work_end")
#: The keys an activity's `when` may hold: a story flag set (`flag`) or unset (`not_flag`).
WHEN_KEYS: tuple[str, ...] = ("flag", "not_flag")
#: Every key an activity row may carry (§8.4); anything else is a load fault.
ROW_KEYS: tuple[str, ...] = ("id", "label", "at", "minutes", "until", "when", "interruptible", "narrate", "say")
#: activities.yaml's top-level keys: the rows, and how a typed world line is read (A4 §3.1).
TOP_KEYS: tuple[str, ...] = ("activities", "typed")

#: The activities that belong to a shift (m11): offered only while `at_work`, never by place.
WORK_ACTIVITIES: tuple[str, ...] = ("carry_on_working", "leave_early")

#: How long before the player's work band "Go to work" is offered (hours) when `conversation.yaml`'s
#: `clock.work_lead_hours` is absent (it is a pacing number and lives in data; this is only the floor).
DEFAULT_WORK_LEAD_HOURS = 2.0


# -- the data -----------------------------------------------------------------------------------


def check_activities(data: dict[str, Any], location_ids: Optional[Any] = None) -> None:
    """`activities.yaml`, checked once at load: a ValueError naming the file and the row on any fault."""
    rows = data.get("activities")
    if not isinstance(rows, list):
        raise ValueError("social: activities.yaml: `activities` must be a list")
    extra_top = sorted(str(k) for k in set(data) - set(TOP_KEYS))
    if extra_top:
        raise ValueError(f"social: activities.yaml: unknown top-level key(s) {', '.join(extra_top)}")
    if location_ids is None:
        from engine.game.locations import load_locations

        location_ids = set(load_locations())
    known = set(location_ids)
    _check_typed(data.get("typed"), known)
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict) or not row.get("id"):
            raise ValueError(f"social: activities.yaml: a row with no id: {row!r}")
        rid = str(row["id"])
        where = f"social: activities.yaml: {rid}"
        if rid in seen:
            raise ValueError(f"{where}: listed twice")
        seen.add(rid)
        extra = sorted(set(row) - set(ROW_KEYS))
        if extra:
            raise ValueError(f"{where}: unknown key(s) {', '.join(extra)}")
        if not isinstance(row.get("label"), str) or not row["label"].strip():
            raise ValueError(f"{where}: `label` must be a line of text")
        at = row.get("at")
        if not isinstance(at, list):
            raise ValueError(f"{where}: `at` must be a list of location ids")
        unknown = sorted(str(a) for a in at if str(a) not in known)
        if unknown:
            raise ValueError(f"{where}: `at` names no location: {', '.join(unknown)}")
        if ("minutes" in row) == ("until" in row):
            raise ValueError(f"{where}: exactly one of `minutes` and `until`")
        if "minutes" in row and (isinstance(row["minutes"], bool) or not isinstance(row["minutes"], (int, float))
                                 or row["minutes"] < 0):
            raise ValueError(f"{where}: `minutes` must be a number, 0 or more")
        if "until" in row and row["until"] not in UNTIL_KEYS:
            raise ValueError(f"{where}: `until` must be one of {', '.join(UNTIL_KEYS)}")
        when = row.get("when", {})
        if not isinstance(when, dict) or set(when) - set(WHEN_KEYS):
            raise ValueError(f"{where}: `when` keys must come from {', '.join(WHEN_KEYS)}")
        if not isinstance(row.get("interruptible", False), bool):
            raise ValueError(f"{where}: `interruptible` must be true or false")
        if not isinstance(row.get("narrate", ""), str):
            raise ValueError(f"{where}: `narrate` must be a line of text")
        say = row.get("say", [])
        if not isinstance(say, list) or not all(isinstance(p, str) and len(p.split()) >= 2 for p in say):
            raise ValueError(f"{where}: `say` must list phrases of two words or more")


def _check_typed(block: Any, known: set[str]) -> None:
    """`typed:` (A4 §3.1): only its cue lists and `rooms`, each a list of words; `rooms` keyed by location ids."""
    if block is None:
        return
    where = "social: activities.yaml: typed"
    if not isinstance(block, dict):
        raise ValueError(f"{where}: must be a mapping")
    from engine.social import typed   # the key names live with their reader

    extra = sorted(str(k) for k in set(block) - set(typed.TYPED_KEYS))
    if extra:
        raise ValueError(f"{where}: unknown key(s) {', '.join(extra)}")
    for key in typed.CUE_KEYS:
        words = block.get(key, [])
        if not isinstance(words, list) or not all(isinstance(w, str) and w.strip() for w in words):
            raise ValueError(f"{where}.{key}: must be a list of words")
    rooms = block.get("rooms", {})
    if not isinstance(rooms, dict):
        raise ValueError(f"{where}.rooms: must map location ids to lists of nouns")
    unknown = sorted(str(r) for r in rooms if str(r) not in known)
    if unknown:
        raise ValueError(f"{where}.rooms: names no location: {', '.join(unknown)}")
    for room, nouns in rooms.items():
        if not isinstance(nouns, list) or not nouns or not all(isinstance(n, str) and n.strip() for n in nouns):
            raise ValueError(f"{where}.rooms.{room}: must be a list of nouns")


def activities() -> list[dict[str, Any]]:
    return [r for r in social.data("activities").get("activities") or () if isinstance(r, dict)]


def _activity(activity_id: str) -> Optional[dict[str, Any]]:
    return next((r for r in activities() if r.get("id") == activity_id), None)


def _when_holds(state: GameState, row: dict[str, Any]) -> bool:
    when = row.get("when") or {}
    flags = getattr(state, "flags", {}) or {}
    if "flag" in when and not flags.get(str(when["flag"])):
        return False
    if "not_flag" in when and flags.get(str(when["not_flag"])):
        return False
    return True


# -- phone up, phone down (§8.2) ------------------------------------------------------------------


def world_turn_refusal(state: GameState) -> str:
    """Why a world turn may not run now ("" when it may). Asked by the choice route and again under the lock."""
    return PHONE_UP_REFUSAL if (getattr(state, "social", None) or {}).get("phone_up") else ""


def pick_up(state: GameState) -> None:
    """Any phone action picks the phone up (§8.2, MINOR 6): free, except during a scene, where someone who
    finds it rude minds (their `in_company` habit, `scene.phone_in_company`)."""
    if not state.social.get("phone_up"):
        apply_effect(state, {"type": "social_settings", "field": "phone_up", "value": True})
        if social.scene_open(state):
            from engine.social import scene   # lazily: scene imports this module's peers

            scene.phone_in_company(state)


def put_down(state: GameState, *, meet: bool = True) -> dict[str, Any]:
    """The phone verb `put_down` (§8.2): free; the world comes forward, and the buzz counts from here. Someone
    who arrived for a plan here while the phone was up is met now (`plans.meet_if_here`, A4 W2); `meet=False`
    for the Places app, whose `go` meets at the far end instead."""
    apply_effect(state, {"type": "social_settings", "field": "phone_up", "value": False})
    counters = state.social.get("counters") or {}
    apply_effect(state, {"type": "social_settings", "field": "buzz_from",
                         "value": int(counters.get("notification", 0))})
    out: dict[str, Any] = {"ok": True, "phone_up": False}
    if meet:
        out.update(_meet(state))
    return out


def _meet(state: GameState) -> dict[str, Any]:
    """`plans.meet_if_here`, its result trimmed to what a receipt carries ({} when nothing happened)."""
    from engine.social import plans   # lazily: plans imports this module's package

    met = plans.meet_if_here(state)
    return {k: v for k, v in met.items() if k in ("met", "scene", "stood_up")}


def _name(state: GameState, pid: str) -> str:
    from engine.social import matching

    return matching._name(state, pid) if pid else ""


def buzz(state: GameState) -> dict[str, Any]:
    """The notifications since the phone was last put down (§8.2): how many, and whose (names only,
    never words). Read off v0.22's `counters["notification"]` (F25) against `buzz_from`; nothing
    while the phone is up."""
    social_ = state.social or {}
    if social_.get("phone_up"):
        return {"count": 0, "who": []}
    count = max(0, int((social_.get("counters") or {}).get("notification", 0)) - int(social_.get("buzz_from") or 0))
    rows = (social_.get("notifications") or [])[-count:] if count else []
    who: list[str] = []
    for row in rows:
        name = _name(state, str(row.get("pid") or ""))
        if name and name not in who:
            who.append(name)
    return {"count": count, "who": who}


def _times(n: int) -> str:
    return {1: "once", 2: "twice"}.get(n, f"{n} times")


def _at_work_line(state: GameState) -> str:
    from engine.social import apps

    job = str(((state.social.get("player") or {}).get("attributes") or {}).get("job") or "")
    label = apps._label_of("jobs", job) if job else ""
    return f"You are at work, as {label}." if label else "You are at work."


def narration_block(state: GameState) -> str:
    """What the narrator is told of the player's world (§8.3), in engine words: where they are, who they are
    with during a scene (T13) and the companion block (T15, §10.6: who they are now, their memory, this
    moment, budgeted to `social.world.companion_tokens`), the buzz, then the plans open (T12). The
    household (T18): who lives with the player and where they are now (`scene.household_line`), and while
    they are home and free with no scene open, the same scene line and companion block for them
    (`scene.narrator_lines`)."""
    if not getattr(state, "social", None):
        return ""
    if state.social.get("at_work"):                      # the shift, not the hall the player left from
        lines = [_at_work_line(state)]
    else:
        lines = [f"You are in {places.label(state.location_id)}."]
    from engine.social import scene   # lazily: scene imports this module's peers

    if social.scene_open(state) or scene.household_present(state):
        lines.append(scene.narrator_lines(state))
    household = scene.household_line(state)
    if household:
        lines.append(household)
    also = also_here_line(state)
    if also:
        lines.append(also)
    b = buzz(state)
    if b["count"] > 0:
        names = ", ".join(b["who"])
        lines.append(f"Your phone has buzzed {_times(b['count'])}" + (f": {names}." if names else "."))
    from engine.social import life, plans   # lazily: each imports this module's package

    for item in life.player_news(state):                   # what is going on in the player's life (§11.2)
        lines.append(f"{item['text']}.")
    for row in plans.open_for(state):
        lines.append(f"You have plans with {_name(state, str(row['pid']))}: {plans.row_words(row)}.")
    return "\n".join(lines)


def _chance_rows(state: GameState) -> list[tuple[str, str]]:
    """(pid, name) of everyone the player knows at this venue by chance now (A4 W9, `presence.chance_here`), less
    the open scene's person; [] off venues (the chance tier is never computed there)."""
    from engine.social import presence   # lazily: presence reads scene, which imports this module's peers

    return [(pid, _name(state, pid)) for pid in presence.chance_here(state, str(state.location_id or ""))]


def also_here_line(state: GameState) -> str:
    """The narrator's "Also here" line (A4 W9): the people the player knows who are at this venue by chance, each
    with their stage in words ("Also here: Sam (just matched)."). Seen, not voiced, until the player goes over.
    "" with nobody."""
    from engine.social import relationships

    people = (state.social or {}).get("people") or {}
    rows = []
    for pid, name in _chance_rows(state):
        stage = str((people.get(pid) or {}).get("stage") or "")
        rows.append(f"{name} ({relationships.stage_words(stage).lower()})" if stage else name)
    return f"Also here: {', '.join(rows)}." if rows else ""


def _around(state: GameState) -> list[str]:
    """The background people (A4 W8, `npc_sim`) here now (on shift: off shift they are off the map), by name."""
    from engine.world import npc_sim

    return [p.name for p in npc_sim.npcs_at(state, str(state.location_id or "")) if p.name]


def here_rows(state: GameState) -> list[dict[str, str]]:
    """The payload's `world.here` (A4 W9): who else is here, NAMES ONLY -- the people the player knows here by chance
    (`kind: contact`), then the background people on shift (`kind: around`). Never a number, a pid or a stage."""
    rows = [{"name": name, "kind": "contact"} for _pid, name in _chance_rows(state) if name]
    rows += [{"name": name, "kind": "around"} for name in _around(state)]
    return rows


# -- activities (§8.4) ----------------------------------------------------------------------------


def _player_work_band(state: GameState, now: float) -> Optional[tuple[float, float]]:
    """The player's current or next work band (absolute hours), or None when their job has none."""
    try:
        return windows.resolve(state, "player", "at_work", now)
    except ValueError:                                     # a job shape the population does not know
        return None


def _player_work_end(state: GameState, now: float) -> Optional[float]:
    band = _player_work_band(state, now)
    return float(band[1]) if band else None


def _work_offered(state: GameState) -> bool:
    """"Go to work" is offered from the hall from a little before the player's work band until it ends."""
    now = state.world_clock_hours
    band = _player_work_band(state, now)
    lead = float((social.data("conversation").get("clock") or {}).get("work_lead_hours", DEFAULT_WORK_LEAD_HOURS))
    return bool(band) and band[0] - now <= lead


def _wakes(state: GameState, row: dict[str, Any], *, sleeping: bool) -> bool:
    """Whether notification `row` stops the activity: any, awake; asleep, only a person's promise or a
    late_night person's message, and only with "wake me for messages" on (§8.4)."""
    if not sleeping:
        return True
    if not (state.social.get("settings") or {}).get("wake_for_messages"):
        return False
    pid = str(row.get("pid") or "")
    if row.get("promise_id"):
        return True
    from engine.social import attrs

    return bool(pid) and attrs.of(state, pid)["habits"]["late_night"] != "no"


def _next_event_at(state: GameState) -> Optional[float]:
    queue = state.social.get("queue") or []
    return float(queue[0]["at"]) if queue else None


def advance_interruptible(state: GameState, until_at: float, *, sleeping: bool = False) -> dict[str, Any]:
    """
    Advance toward `until_at`, event by event, stopping at the first new notification that may wake
    the player (Plan decision 13), or at the arrival of someone they planned to meet HERE (A4 W4: a
    `plan_arrive` at the player's place; `arrived` names them). Every step goes through
    `clock.advance_time` (rule 2).
    Returns {"stopped": bool, "at": float, "who": [names], "arrived": [names]}.
    """
    from engine.social import plans   # lazily: plans imports this module's package

    notes = state.social.setdefault("notifications", [])
    seen = int(state.social.get("counters", {}).get("notification", 0))     # v0.22's counter (F25)
    awaited = [str(r["id"]) for r in plans.waiting_here(state)]
    while state.world_clock_hours < until_at - 1e-9:
        now = state.world_clock_hours
        nxt = _next_event_at(state)
        step_to = until_at if nxt is None or nxt >= until_at else max(nxt, now + 1.0 / 60.0)
        clock.advance_time(state, min(step_to, until_at) - now)
        here = [r for r in (plans.get(state, i) for i in awaited)
                if r is not None and r.get("status") == "open" and plans.has_arrived(r)]
        if here:
            return {"stopped": True, "at": state.world_clock_hours, "who": [],
                    "arrived": sorted({_name(state, str(r["pid"])) for r in here} - {""})}
        count = int(state.social.get("counters", {}).get("notification", 0))
        if count > seen:
            fresh = notes[-min(len(notes), count - seen):]
            waking = [r for r in fresh if _wakes(state, r, sleeping=sleeping)]
            if waking:
                return {"stopped": True, "at": state.world_clock_hours,
                        "who": sorted({_name(state, str(r.get("pid") or "")) for r in waking} - {""}), "arrived": []}
            seen = count
    return {"stopped": False, "at": state.world_clock_hours, "who": [], "arrived": []}


def _until(state: GameState, row: dict[str, Any]) -> float:
    now = state.world_clock_hours
    clock_rows = social.data("conversation").get("clock") or {}
    if row.get("until") == "morning":
        span = windows.resolve(state, "player", "waking", now + float(clock_rows.get("min_sleep_hours", 4)))
        if span is None:
            morning = float(clock_rows.get("morning", 7))
            return now + ((morning - now % 24) % 24 or 24.0)
        return float(span[0])
    if row.get("until") == "evening":
        evening = float(clock_rows.get("evening", 18))
        return now + ((evening - now % 24) % 24 or 24.0)
    if row.get("until") == "work_end":
        end = state.social.get("work_until") or _player_work_end(state, now)
        return float(end) if end is not None else now
    return now + float(row.get("minutes", 0)) / 60.0


def do(state: GameState, activity_id: str) -> dict[str, Any]:
    """The world verb `do {activity}` (§8.4): its time spent through `clock.advance_time` (rule 2)."""
    row = _activity(activity_id)
    if row is None:
        return {"ok": False, "error": f"no activity {activity_id!r}"}
    if social.scene_open(state):                         # with someone: a shared activity, together (§10.1)
        from engine.social import scene

        shared = scene.shared_activity(state, activity_id)
        return shared if shared is not None else {"ok": False, "error": f"you can't {activity_id} together here"}
    if activity_id == "go_to_work":
        until = _player_work_end(state, state.world_clock_hours)
        if until is None:
            return {"ok": False, "error": "you have no work to go to"}
        apply_effect(state, {"type": "social_settings", "field": "at_work", "value": True})
        apply_effect(state, {"type": "social_settings", "field": "work_until", "value": until})
    if activity_id == "leave_early":
        _end_work(state)
        return {"ok": True, "activity": activity_id, "narrate": row.get("narrate", ""), **_meet(state)}
    target = _until(state, row)
    resume = state.social.get("resume") or {}
    if resume:
        # "Carry on" (§8.4): the same activity again resumes to its ORIGINAL end; anything else forgets it.
        if resume.get("activity") == activity_id and float(resume.get("until") or 0.0) > state.world_clock_hours:
            target = float(resume["until"])
        apply_effect(state, {"type": "social_settings", "field": "resume", "value": None})
    if row.get("interruptible"):
        stopped = advance_interruptible(state, target, sleeping=activity_id == "sleep")
    else:
        clock.advance_time(state, max(0.0, target - state.world_clock_hours))
        stopped = {"stopped": False, "at": state.world_clock_hours, "who": [], "arrived": []}
    if state.social.get("at_work") and state.world_clock_hours >= float(state.social.get("work_until") or 0) - 1e-9:
        _end_work(state)
    result: dict[str, Any] = {"ok": True, "activity": activity_id, "narrate": row.get("narrate", ""),
                              "stopped": stopped["stopped"]}
    if stopped["stopped"]:
        if stopped.get("arrived"):                       # someone you planned to meet arrives here (A4 W4)
            result["arrived"] = " and ".join(stopped["arrived"]) + (" arrives." if len(stopped["arrived"]) == 1
                                                                     else " arrive.")
        else:
            result["buzz"] = "Your phone buzzes: " + ", ".join(stopped["who"])
        result["resume_until"] = target                  # "Carry on" resumes to the original end
        apply_effect(state, {"type": "social_settings", "field": "resume",
                             "value": {"activity": activity_id, "until": target}})
    result.update(_meet(state))                          # the clock has stopped: anyone here is met (A4 W2)
    return result


def _end_work(state: GameState) -> None:
    """The shift is over (its band ended, or `leave_early`): back in the hall (m11)."""
    apply_effect(state, {"type": "social_settings", "field": "at_work", "value": False})
    apply_effect(state, {"type": "social_settings", "field": "work_until", "value": None})
    apply_effect(state, {"type": "social_go", "op": "place", "to": "apt_hall"})


# -- going out (§8.5) -----------------------------------------------------------------------------


def _venue_rows() -> list[dict[str, Any]]:
    return [r for r in social.data("venues").get("venues") or () if isinstance(r, dict) and r.get("id")]


def _open_plans(state: GameState) -> list[dict[str, Any]]:
    rows = [r for r in ((state.social or {}).get("plans") or {}).values()
            if isinstance(r, dict) and r.get("status") == "open"]
    return sorted(rows, key=lambda r: (float(r.get("made_at") or 0.0), str(r.get("id") or "")))


def _plan_destinations(state: GameState) -> list[str]:
    """Where the open plans meet (spec §9.1): `plans.place_of` -- a plan's `venue`, their home for `their_place`,
    the registry office for the wedding (T18)."""
    from engine.social import plans   # lazily: plans imports this module's package

    out: list[str] = []
    for row in _open_plans(state):
        where = plans.place_of(state, row) if row.get("pid") else str(row.get("venue") or "")
        if where and where not in out and places.is_outside_flat(where):
            out.append(where)
    return out


def _last_visit(state: GameState, venue: str) -> float:
    """When the player last met someone at `venue` (a `met` plan there), or -1: read, never written."""
    met = [float(r.get("made_at") or 0.0) for r in ((state.social or {}).get("plans") or {}).values()
           if isinstance(r, dict) and r.get("status") == "met" and r.get("venue") == venue]
    return max(met) if met else -1.0


def _ranked_venues(state: GameState) -> list[str]:
    """Every venue, ranked by the hobbies the player shares with it, then the most recently visited."""
    hobbies = {str(h) for h in ((state.social or {}).get("player") or {}).get("hobbies") or ()}
    rows = _venue_rows()
    order = {str(r["id"]): i for i, r in enumerate(rows)}

    def rank(row: dict[str, Any]) -> tuple[int, float, int]:
        vid = str(row["id"])
        shared = len(hobbies & {str(h) for h in row.get("hobbies") or ()})
        return -shared, -_last_visit(state, vid), order[vid]

    return [str(r["id"]) for r in sorted(rows, key=rank)]


def _offers_the_city(location_id: str) -> bool:
    """The other `go` targets are offered from the flat, the building, the street and a venue (§8.5);
    from a home or the registry office the way out is "Head home" alone."""
    return places.is_flat(location_id) or location_id == "merrow_street" or location_id in places.venue_ids()


def _goes_nowhere(state: GameState) -> bool:
    return social.scene_open(state) or bool((state.social or {}).get("at_work"))


def go_targets(state: GameState) -> list[tuple[str, str]]:
    """The world verb `go`'s targets, (location id, label), at most eight (§8.5, N5; Plan decision 25)."""
    if _goes_nowhere(state):
        return []
    here = state.location_id
    out: list[tuple[str, str]] = []
    if places.is_outside_flat(here):
        out.append((HOME, HOME_LABEL))                   # first and always: the way back has no gate
    if _offers_the_city(here):
        seen = {HOME, here}
        for where in _plan_destinations(state) + _ranked_venues(state):
            if where not in seen:
                seen.add(where)
                out.append((where, places.label(where)))
    return out[:MAX_OPTIONS]


def places_targets(state: GameState) -> list[tuple[str, str]]:
    """The Places app's list (§8.5): every venue but the one the player is at, with no cap; none during
    a scene or at work. The phone verb `go` accepts exactly these, and the `places` section lists them."""
    if _goes_nowhere(state):
        return []
    return [(vid, places.label(vid)) for vid in (str(r["id"]) for r in _venue_rows()) if vid != state.location_id]


def go(state: GameState, to: str, *, targets: Optional[list[tuple[str, str]]] = None) -> dict[str, Any]:
    """`go {to}`: the travel (`travel_minutes`, an action's cost through `clock.advance_time`, rule 2), then
    the place (`social_go` op `place`), then the arrival. `targets` defaults to the world verb's own."""
    legal = dict(go_targets(state) if targets is None else targets)
    if to not in legal:
        return {"ok": False, "error": f"you can't get to {to} from here right now"}
    if state.social.get("resume"):                       # walking out ends a cut-short activity (§8.4)
        apply_effect(state, {"type": "social_settings", "field": "resume", "value": None})
    from engine.social import life   # lazily: life imports this module's peers

    left = str(state.location_id or "")
    minutes = places.travel_minutes(to if to != HOME else left)
    # The lift's minutes (§11.2, v0.24.0 §12.2) only for a move whose path passes the lift: exactly one end in
    # the flat upstairs (`places.is_upstairs`, its `home`-tagged rooms). A move from the lobby or the lift is
    # already downstairs (v0.24.0 T14). The cast's homes are `residence`, never upstairs. A room-by-room walk
    # through `bldg_lift` with core `travel` pays nothing extra (docs/GOVERNANCE.md, NOT WIRED).
    if places.is_upstairs(left) != places.is_upstairs(to):
        minutes += life.extra_minutes(state)
    clock.advance_time(state, minutes / 60.0)
    apply_effect(state, {"type": "social_go", "op": "place", "to": to})
    result: dict[str, Any] = {"ok": True, "to": to, "label": legal[to], "minutes": minutes}
    result.update(_arrive(state, to))
    from engine.social import messaging   # lazily: messaging imports this module's peers

    messaging.release_held(state)         # whoever was with the player and is not now: their held texts land (W5)
    return result


def places_go(state: GameState, to: str) -> dict[str, Any]:
    """The phone's Places app (§8.5): the phone goes down and the player goes."""
    targets = places_targets(state)
    if to not in dict(targets):
        return {"ok": False, "error": f"you can't get to {to} from here right now"}
    put_down(state, meet=False)
    return go(state, to, targets=targets)


def _arrive(state: GameState, to: str) -> dict[str, Any]:
    """The arrival: a plan there opens (or is stood up), else a quiet visit (`plans.arrive`, spec §8.5, §9.3); then,
    the clock stopped, anyone who arrived for a plan here is met (`plans.meet_if_here`: a `your_place` plan in any
    of the flat's places, A4 W2)."""
    from engine.social import plans   # lazily: plans imports this module's package

    out = plans.arrive(state, to)
    if out.get("quiet") and not out.get("stood_up"):
        met = plans.meet_if_here(state)
        if not met.get("quiet") or met.get("stood_up"):
            out = met
    return out


@section("world", time_varying=True)
def _world_section(state: GameState, session: Any) -> dict[str, Any]:
    """The two layers' switch (v0.23.0 T21, spec §14.1): whether the phone is up, whether the player is at
    work, where they are (the place's label), the buzz (count and names, never a message's words), the
    household card (T23: who lives with the player and where they are, in words; {} with none) and who else is
    here (A4 W9, `here_rows`: names and a kind, never a number)."""
    from engine.social import scene   # lazily: scene imports this module's peers

    social_ = state.social or {}
    return {"phone_up": bool(social_.get("phone_up")), "at_work": bool(social_.get("at_work")),
            "location": places.label(state.location_id), "buzz": buzz(state),
            "household": scene.household_card(state), "here": here_rows(state)}


@section("places")
def _places_section(state: GameState, session: Any) -> dict[str, Any]:
    """The Places app's venue list (pre-flight F18; T22's client reads `phone.places.venues`): built from
    `places_targets`, the SAME function the phone verb `go` accepts, so every listed venue is accepted.
    Names only: no travel minutes, no rank."""
    return {"venues": [{"id": vid, "label": name} for vid, name in places_targets(state)]}


# -- the verbs ------------------------------------------------------------------------------------


def _label(row: dict[str, Any]) -> str:
    return str(row.get("label") or row.get("id"))


def world_verbs(state: GameState) -> tuple[IntentVerb, ...]:
    """The world verbs legal now (§8.4, §8.5): `do` (the activities here whose `when` holds) and `go`; and
    `scene` (T18, §12.3) to spend time with the household partner when they are home and free, to wait for a plan's
    person (A4 W2) and to go over to someone here by chance (A4 W9), at most eight."""
    here = state.location_id
    options = [(str(r["id"]), _label(r)) for r in activities()
               if here in (r.get("at") or ()) and str(r["id"]) not in WORK_ACTIVITIES and _when_holds(state, r)
               and (r["id"] != "go_to_work" or _work_offered(state))]
    verbs: list[IntentVerb] = []
    if options:
        verbs.append(IntentVerb("do", tuple(options[:MAX_OPTIONS])))
    targets = go_targets(state)
    if targets:
        verbs.append(IntentVerb("go", tuple(targets)))
    from engine.social import scene   # lazily: scene imports this module's peers

    together = scene.at_home_options(state)           # the household partner at home and free (§12.3, T18)
    together += scene.plan_wait_options(state)        # "Wait for {name}": a plan here, its person on the way (A4 W2)
    together += scene.approach_options(state)         # "Go over to {name}": someone you know, here by chance (A4 W9)
    if together:
        verbs.append(IntentVerb("scene", tuple(together[:MAX_OPTIONS])))
    return tuple(verbs)


def scene_verbs(state: GameState) -> tuple[IntentVerb, ...]:
    """While a scene is open (§10.1): its moves, its closers and the shared activities (`scene.scene_verbs`)."""
    from engine.social import scene   # lazily: scene imports this module's peers

    return scene.scene_verbs(state)


def work_verbs(state: GameState) -> tuple[IntentVerb, ...]:
    """At work (m11): only `carry_on_working` and `leave_early`; the phone stays usable."""
    rows = {str(r["id"]): r for r in activities()}
    options = tuple((a, _label(rows[a])) for a in WORK_ACTIVITIES if a in rows)
    return (IntentVerb("do", options),) if options else ()


# -- the effect (Plan decision 16) ----------------------------------------------------------------


@effect_kind("social_go")
@recorded
def _e_go(state: GameState, effect: dict[str, Any], ctx: EffectContext) -> dict[str, Any]:
    """
    Engine-only: where the player is (§8.5). `op: place` writes `state.location_id` and nothing else
    (the `arrest` precedent, effects.py). The travel itself is charged by the caller, `go`, through
    `clock.advance_time` before the place is written (rule 2): this handler moves no clock.
    """
    from engine.game.locations import LOCATIONS

    op = str(effect.get("op") or "")
    to = str(effect.get("to") or "")
    if op != "place":
        return {"type": "social_go", "ok": False, "text": f"unknown op {op!r} (the travel is go's own)"}
    if to not in LOCATIONS:
        return {"type": "social_go", "ok": False, "text": f"no location {to!r}"}
    state.location_id = to
    return {"type": "social_go", "ok": True, "text": f"now at {to}"}
