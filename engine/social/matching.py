"""
Matching (v0.22.0 spec §8): compatibility, the like-back, likes you, expiry,
unmatching and blocking. Every number is `apps.yaml`'s `matching:` block
(rule 10, measured by scripts/simulate_social.py at T26).

- **Compatibility** is deterministic (no RNG: the chemistry was drawn at
  generation): the weighted looking-for, hobby, personality, preference and
  distance terms plus the person's chemistry, clamped to [0, 1].
- **The like-back** is drawn ONCE per pair, from
  `stable_rng(seed, f"{SOCIAL_MATCH}:{pid}")`, so un-liking and liking again
  cannot re-roll it. A true draw becomes a match only at a `see_like` event,
  `see_like_hours` later (drawn on a stable key of the same stream), so
  matches arrive over time.
- **Likes you** (an app with `likes_you_per_day`): each `daily`, about
  `likes_you_per_day` x completeness people who would like the player back
  are queued as `likes_you` events through that day, each with a comment
  from their texting style's `like_comments` bank (population.yaml). Liking
  one back is a match at once.
- **Openers**: a match queues the person's possible opener (messaging.py,
  T8: `on_match`), so a match may be written in first by them.
- **Expiry**: a match nobody writes in within `match_expiry_days` expires, an
  engine line in the thread ("This match expired").
- **Unmatch** (either side) and **block** (the player's only): the thread
  leaves the app (`listed` is false), and the contact card's history keeps
  "This match is no longer available".

People's dynamic state (spec §10.1) is per person, with what happened on each
app under `people[pid]["apps"][app]` (`swiped`, `at`, `comment`, `on`,
`liked_you_at`, `matched_at`), so a match on one app does not match the
other. A stage is written only through `social_stage` (relationships.py,
Plan decision 17): `social_person` refuses a `stage` in its `set`. Every
write to a person bumps their `rev` (`relationships.touch`), and their arc
point is drawn at their first `social_person` write.
"""

from __future__ import annotations

from typing import Any, Optional

from engine import social
from engine.game import clock
from engine.game.effects import EffectContext, apply_effect, effect_kind
from engine.social.kinds import recorded
from engine.game.intents import IntentVerb
from engine.game.rng import SOCIAL_MATCH, stable_rng
from engine.game.state import GameState
from engine.social import apps, attrs, events, population, relationships
from engine.social.behaviour import lognormal_minutes
from engine.social.intents import ArgSpec, phone_verb
from engine.social.payload import section
from engine.social.turn import cost_hours

#: The intents, in looking_for_table's canonical key order.
INTENTS: tuple[str, ...] = ("long_term", "short_term", "friendship", "unsure")
#: How an intent reads in a looking_for_table key.
SHORT: tuple[tuple[str, str], ...] = (("long_term", "long"), ("short_term", "short"),
                                     ("friendship", "friendship"), ("unsure", "unsure"))
#: compatibility's terms (matching.weights), which sum to 1.0.
TERMS: tuple[str, ...] = ("looking_for", "hobbies", "personality", "preferences", "distance")
#: The one slider where opposites attract too (spec §8.1): a difference of 2 scores 0.75.
COMPLEMENTARY = "outgoing"
#: The profile fields completeness counts (spec §8.2).
COMPLETENESS_FIELDS: tuple[str, ...] = ("photos", "hobbies", "bios", "attributes", "looking_for")
#: A like's comment, at most (spec §7.1, §17.1): refused, never cut.
COMMENT_MAX = 140

EXPIRED_LINE = "This match expired"
GONE_LINE = "This match is no longer available"


def thread_id(app: str, pid: str) -> str:
    """A thread's id (Plan decision 14)."""
    return f"{app}:{pid}"


def _m() -> dict[str, Any]:
    block = social.data("apps").get("matching")
    if not isinstance(block, dict):
        raise ValueError("social: apps.yaml: matching: required")
    return block


def _no(reason: str) -> dict[str, Any]:
    return {"ok": False, "error": reason}


def _name(state: GameState, pid: str) -> str:
    """A person's first name for a label or a line; the pid when it names nobody."""
    try:
        return population.profile(state, pid).name
    except (ValueError, KeyError, IndexError):
        return pid


# -- compatibility (spec §8.1) ----------------------------------------------------


def _short(intent: str) -> str:
    return dict(SHORT).get(intent, intent)


def looking_for_score(a: str, b: str) -> float:
    if a not in INTENTS or b not in INTENTS:
        return 0.5
    first, second = sorted((a, b), key=INTENTS.index)
    return float((_m().get("looking_for_table") or {}).get(f"{_short(first)}_{_short(second)}", 0.5))


def _tags(hobbies: Any) -> set[str]:
    rows = {str(row.get("id")): row for row in population.table("hobbies") if isinstance(row, dict)}
    return {str(tag) for h in hobbies or () for tag in (rows.get(str(h)) or {}).get("tags") or ()}


def hobbies_score(player: dict[str, Any], person: population.Person) -> float:
    """Jaccard over the union of each side's hobby tags."""
    mine, theirs = _tags(player.get("hobbies")), _tags(person.hobbies)
    union = mine | theirs
    return len(mine & theirs) / len(union) if union else 0.0


def personality_score(player: dict[str, Any], person: population.Person) -> float:
    """Per slider `1 - |a-b|/4`; `outgoing` also scores 0.75 for a difference of exactly 2."""
    mine = player.get("personality") or {}
    scores: list[float] = []
    for name, theirs in person.personality:
        if name not in mine:
            continue
        diff = abs(int(mine[name]) - int(theirs))
        score = 1.0 - diff / 4.0
        if name == COMPLEMENTARY and diff == 2:
            score = max(score, 0.75)
        scores.append(score)
    return sum(scores) / len(scores) if scores else 0.5


def preferences_score(player: dict[str, Any], person: population.Person) -> float:
    """The age inside their range (1.0, else 0.0), times `dealbreaker_mult` per dealbreaker hit."""
    prefs = dict(person.preferences)
    age = int(player.get("age") or 0)
    score = 1.0 if int(prefs.get("age_min", 0)) <= age <= int(prefs.get("age_max", 999)) else 0.0
    attributes = player.get("attributes") or {}
    mult = float(_m()["dealbreaker_mult"])
    for dealbreaker in prefs.get("dealbreakers") or ():
        attribute, _, value = str(dealbreaker).partition("_")
        if value and str(attributes.get(attribute, "")) == value:
            score *= mult
    return score


def distance_score(player: dict[str, Any], person: population.Person) -> float:
    """`1 - table[a][b]/4`; a player with no neighbourhood scores the middle, 0.5."""
    home = player.get("neighbourhood")
    table = social.data("population").get("distance") or {}
    if not home or home not in table:
        return 0.5
    return 1.0 - float((table[home] or {}).get(person.neighbourhood, 4)) / 4.0


def compatibility(player: dict[str, Any], person: population.Person) -> float:
    """Deterministic, in [0, 1] (spec §8.1)."""
    weights = _m()["weights"]
    terms = {
        "looking_for": looking_for_score(str(player.get("looking_for") or ""), person.intent),
        "hobbies": hobbies_score(player, person),
        "personality": personality_score(player, person),
        "preferences": preferences_score(player, person),
        "distance": distance_score(player, person),
    }
    total = sum(float(weights[name]) * terms[name] for name in TERMS)
    return max(0.0, min(1.0, total + float(person.chemistry)))


# -- the like-back (spec §8.2) -----------------------------------------------------


def _selectivity(person: population.Person) -> float:
    return float(dict(person.preferences).get("selectivity", 0.0))


def completeness_mult(player: dict[str, Any]) -> float:
    low, high = _m()["completeness"]
    filled = sum(bool(player.get(k)) for k in COMPLETENESS_FIELDS)
    photos = min(1.0, len(player.get("photos") or []) / 4.0)
    share = (filled / 5.0 + photos) / 2.0
    return float(low) + (float(high) - float(low)) * share


def like_back_p(state: GameState, app: str, person: population.Person, *, super_: bool) -> float:
    m = _m()
    culture = apps.app(app).get("culture") or {}
    p = (float(m["like_back_base"][app])
         * (float(m["compat_offset"]) + compatibility(state.social["player"], person))
         * max(0.0, 1.0 - _selectivity(person) * float(culture.get("selectivity_mult", 1.0)))
         * completeness_mult(state.social["player"]))
    if super_:
        p *= float(m["super_like_mult"])
    return max(0.0, min(1.0, p))


def likes_back(state: GameState, app: str, person: population.Person, *, super_: bool) -> bool:
    """Drawn ONCE per pair (spec §8.2): un-liking and liking again cannot re-roll it."""
    roll = stable_rng(state.rng_seed, f"{SOCIAL_MATCH}:{person.pid}").random()
    return roll < like_back_p(state, app, person, super_=super_)


def see_like_hours(state: GameState, app: str, pid: str) -> float:
    """When a mutual like becomes a match: lognormal hours, capped; a stable key per pair and app."""
    spec = _m()["see_like_hours"]
    rng = stable_rng(state.rng_seed, f"{SOCIAL_MATCH}:{pid}:see_like:{app}")
    # lognormal_minutes is unit-free but for its 0.5 floor: read in HOURS here, a 30-minute floor.
    hours = lognormal_minutes(rng, float(spec["median"]), float(spec["spread"]))
    return min(hours, float(spec.get("max", hours)))


# -- threads -------------------------------------------------------------------------


def listed(thread: dict[str, Any]) -> bool:
    """Whether a thread shows in its app: not unmatched, not blocked (an expired match keeps its line)."""
    return thread.get("closed") not in ("unmatched", "blocked")


def _threads_of(state: GameState, pid: str) -> list[dict[str, Any]]:
    return [t for t in (state.social.get("threads") or {}).values() if t.get("pid") == pid]


def live_matches(state: GameState) -> list[str]:
    """Pids with an open thread on a dating app: who may be unmatched."""
    dating = set(apps.dating_apps())
    seen: list[str] = []
    for thread in (state.social.get("threads") or {}).values():
        if thread.get("app") in dating and not thread.get("closed") and thread["pid"] not in seen:
            seen.append(thread["pid"])
    return seen


def _system_message(state: GameState, thread: dict[str, Any], text: str, at: float,
                    extra: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """
    An engine line in a thread (called only inside a `social_*` handler: rule 3). `extra` adds keys the
    line carries for the client (a meet-up counter's `counter`, T30 follow-up).
    """
    counters = state.social.setdefault("counters", {})
    counters["message"] = int(counters.get("message", 0)) + 1
    message = {
        "id": f"m{counters['message']}", "thread_id": thread["thread_id"], "from": "system",
        "kind": "system", "at": float(at), "bubbles": [text], "voiced": True, "decision": None,
        "media_id": None, "read_at": None, "transcript": None,
    }
    if extra:
        message.update(extra)
    thread.setdefault("messages", []).append(message)
    return message


# -- the effects ---------------------------------------------------------------------


@effect_kind("social_person")
@recorded
def _e_person(state: GameState, effect: dict[str, Any], ctx: EffectContext) -> dict[str, Any]:
    """
    Engine-only: one person's dynamic slice (spec §10.1). `set` merges
    top-level fields; `app` with `app_set` merges into people[pid]["apps"][app]
    (and adds the app to `seen_on`). A `stage` is refused: `social_stage` is
    its one writer. Their first write draws their arc point.
    """
    if not state.social:
        return {"type": "social_person", "ok": False, "text": "no social slice"}
    pid = str(effect.get("pid") or "")
    if not pid:
        return {"type": "social_person", "ok": False, "text": "social_person needs a pid"}
    if effect.get("op") == "compact":
        return _compact_person(state, pid)
    changes = dict(effect.get("set") or {})
    if "stage" in changes:
        return {"type": "social_person", "ok": False, "text": "a stage moves only through social_stage"}
    person = state.social.setdefault("people", {}).setdefault(pid, {})
    relationships.ensure_arc_point(state, pid, person)
    relationships.touch(person)
    for key, value in changes.items():
        person[str(key)] = value
    if effect.get("app"):
        name = str(effect["app"])
        person.setdefault("apps", {}).setdefault(name, {}).update(dict(effect.get("app_set") or {}))
        seen = person.setdefault("seen_on", [])
        if name not in seen:
            seen.append(name)
    return {"type": "social_person", "ok": True, "text": f"{pid} updated"}


#: What a person the player only swiped keeps of each app row once compacted (`compact_swiped`):
#: what `apps.touched` reads, so they stay off that deck and out of its "Likes you".
SWIPED_KEEPS: tuple[str, ...] = ("swiped", "liked_you_at")
#: The only keys a swiped-only person's row may hold to be compacted; anything else is a relationship.
SWIPED_ROW_KEYS: frozenset[str] = frozenset({"apps", "arc_point", "rev", "seen_on"})


def _compact_person(state: GameState, pid: str) -> dict[str, Any]:
    """`op: compact`: a swiped-only row cut to what dedupe needs, in place (`compact_swiped` chose it)."""
    person = (state.social.get("people") or {}).get(pid)
    if not isinstance(person, dict) or not set(person) <= SWIPED_ROW_KEYS:
        return {"type": "social_person", "ok": False, "text": f"{pid} is not a swiped-only row"}
    rows = {name: {k: row[k] for k in SWIPED_KEEPS if k in row}
            for name, row in (person.get("apps") or {}).items() if isinstance(row, dict)}
    person.clear()
    person["apps"] = rows
    return {"type": "social_person", "ok": True, "text": f"{pid} compacted"}


def compact_swiped(state: GameState) -> int:
    """
    Bounded state (spec §17.2, v0.22.0 T26): every person the player only
    swiped or liked -- never matched, no thread, nothing queued, asked, sent,
    played or planned with them, not waiting in a "Likes you", holding only
    a swipe -- is cut to `{"apps": {app: {swiped | liked_you_at}}}` through
    `social_person` `op: compact` (rule 3). What goes is what nothing reads
    again: the swipe's time and comment, `seen_on`, `rev`, and `arc_point`
    (drawn on a stable key, so it is drawn the same if they are ever met).
    Returns how many were cut. Called by the phone's save (saves.compact).
    """
    slice_ = state.social or {}
    people = slice_.get("people") or {}
    busy: set[str] = {str(t.get("pid")) for t in (slice_.get("threads") or {}).values()}
    busy |= {str(e.get("pid")) for e in slice_.get("queue") or []}
    for key in ("requests", "media", "games", "plans"):
        busy |= {str(r.get("pid")) for r in (slice_.get(key) or {}).values() if isinstance(r, dict)}
    for app_state in (slice_.get("apps") or {}).values():
        busy |= {str(r.get("pid")) for r in (app_state or {}).get("likes_you") or [] if isinstance(r, dict)}
    cut = 0
    for pid in sorted(people):
        person = people[pid]
        if pid in busy or not isinstance(person, dict) or not set(person) <= SWIPED_ROW_KEYS:
            continue
        rows = person.get("apps") or {}
        if not rows or any(not isinstance(r, dict) or r.get("matched_at") is not None for r in rows.values()):
            continue
        if set(person) == {"apps"} and all(set(r) <= set(SWIPED_KEEPS) for r in rows.values()):
            continue                                   # already as small as it gets
        cut += bool(apply_effect(state, {"type": "social_person", "op": "compact", "pid": pid}).get("ok"))
    return cut


@effect_kind("social_match")
@recorded
def _e_match(state: GameState, effect: dict[str, Any], ctx: EffectContext) -> dict[str, Any]:
    """Engine-only: a mutual match and its thread (`op: match`), or a silent match expiring (`op: expire`)."""
    if not state.social:
        return {"type": "social_match", "ok": False, "text": "no social slice"}
    name, pid = str(effect["app"]), str(effect["pid"])
    at = float(effect.get("at", state.world_clock_hours))
    tid = thread_id(name, pid)
    threads = state.social.setdefault("threads", {})
    person = state.social.setdefault("people", {}).setdefault(pid, {})
    if effect.get("op", "match") == "expire":
        thread = threads.get(tid)
        if thread is None or thread.get("closed"):
            return {"type": "social_match", "ok": False, "text": f"{tid} is not an open match"}
        if (thread.get("stamp") or {}).get("spoken") or any(   # an emptied thread's stamp (T26)
                m.get("kind") != "system" and m.get("voiced") != "withdrawn"   # withdrawn: never sent
                for m in thread.get("messages") or []):
            return {"type": "social_match", "ok": False, "text": f"{tid} has been written in"}
        _system_message(state, thread, EXPIRED_LINE, at)
        thread["closed"] = "expired"
        relationships.touch(person)
        if person.get("stage") == "matched" and not any(
                t.get("pid") == pid and not t.get("closed") for t in threads.values()):
            relationships.set_stage(state, pid, "expired", at=at, history=False)
        relationships.add_history(state, pid, "expired", f"The match on {apps.label(name)} expired", at=at)
        return {"type": "social_match", "ok": True, "text": f"{tid} expired", "thread_id": tid}
    if tid in threads:
        return {"type": "social_match", "ok": False, "text": f"{tid} already exists"}
    threads[tid] = {"thread_id": tid, "app": name, "pid": pid, "messages": [], "focus": 0, "unread": 0,
                    "archived": 0, "opened_at": None}
    person.setdefault("apps", {}).setdefault(name, {})["matched_at"] = at
    person.setdefault("matched_at", at)
    relationships.touch(person)
    if person.get("stage") in (None, "", "expired"):
        relationships.set_stage(state, pid, "matched", at=at, history=False)
    relationships.add_history(state, pid, "matched", f"Matched on {apps.label(name)}", at=at)
    days = float(apps.app(name).get("match_expiry_days") or 0)
    if days > 0:
        events.push(state, at + days * 24.0, pid, "expire", app=name)
    from engine.social import messaging   # lazily: messaging imports this module

    # The match is news of its own, opener or not (T30 follow-up; §15.3 counts "1 new match").
    messaging.notify(state, name, tid, pid, "match", messaging.NEW_MATCH, at=at)
    attrs.materialise(state, pid)   # v0.23.0: their fixed attributes, written once at first match (I14)
    messaging.on_match(state, name, pid, at)   # their possible opener (spec §8.3)
    return {"type": "social_match", "ok": True, "text": f"matched {tid}", "thread_id": tid,
            "save_reason": "match"}   # saved at once (spec §17.2)


@effect_kind("social_unmatch")
@recorded
def _e_unmatch(state: GameState, effect: dict[str, Any], ctx: EffectContext) -> dict[str, Any]:
    """
    Engine-only: an unmatch by either side (`by`: player | them) closes the
    person's open dating-app threads; a block (the player's, `block: true`)
    closes every thread of theirs. Their queued events are cancelled and the
    card's history keeps the line. A partner who lived with the player moves
    out (`social_household`, v0.23.0 T18); their stage is left as it was, and
    `apps.gone` keeps them out of every reader from here on.
    """
    if not state.social:
        return {"type": "social_unmatch", "ok": False, "text": "no social slice"}
    pid, by = str(effect["pid"]), str(effect.get("by") or "player")
    block = bool(effect.get("block"))
    at = float(effect.get("at", state.world_clock_hours))
    dating = set(apps.dating_apps())
    closed: list[str] = []
    for thread in _threads_of(state, pid):
        if thread.get("closed") == "blocked" or (not block and thread.get("closed")):
            continue
        if block or thread.get("app") in dating:
            thread["closed"] = "blocked" if block else "unmatched"
            closed.append(thread["thread_id"])
    if not closed and not block:
        return {"type": "social_unmatch", "ok": False, "text": f"{pid} has no open match"}
    person = state.social.setdefault("people", {}).setdefault(pid, {})
    # Either way they are gone from every app (apps.gone): out of every "Likes you" too.
    for slot in (state.social.get("apps") or {}).values():
        slot["likes_you"] = [row for row in slot.get("likes_you") or [] if row.get("pid") != pid]
    relationships.touch(person)
    if block:
        person["blocked"] = True
        relationships.add_history(state, pid, "blocked", "Blocked", at=at)
    else:
        person["unmatched_by"] = by
        relationships.add_history(state, pid, "unmatched", GONE_LINE, at=at)
    events.cancel(state, pid)
    from engine.social import plans   # lazily: plans imports this module

    plans.call_off(state, pid, at)                  # their plans called off at no cost (T24 review M7)
    if relationships.household(state) == pid:       # they lived with the player: they move out (T18 fix I1)
        apply_effect(state, {"type": "social_household", "op": "move_out", "pid": pid, "at": at})
    return {"type": "social_unmatch", "ok": True, "text": f"{pid} {'blocked' if block else 'unmatched'}",
            "closed": closed}


# -- the queued events ------------------------------------------------------------------


@events.handles("see_like")
def _see_like(state: GameState, event: dict[str, Any]) -> dict[str, Any]:
    """The person sees the player's like: a mutual like becomes a match now."""
    pid, name = str(event["pid"]), str(event["app"])
    if apps.gone(state, pid):
        return {"ok": False, "why": "gone"}
    return apply_effect(state, {"type": "social_match", "app": name, "pid": pid, "at": float(event["at"])})


@events.handles("expire")
def _expire(state: GameState, event: dict[str, Any]) -> dict[str, Any]:
    return apply_effect(state, {"type": "social_match", "op": "expire", "app": str(event["app"]),
                                "pid": str(event["pid"]), "at": float(event["at"])})


def comment_for(state: GameState, app: str, person: population.Person) -> str:
    """A liker's comment: one of their texting style's `like_comments`, on a stable key."""
    data = social.data("population")
    bank = list((data.get("like_comments") or {}).get(person.texting_style) or [])
    if not bank:
        return ""
    words = population.template_words(data, person.hobbies, person.job, person.neighbourhood)
    text = stable_rng(state.rng_seed, f"{SOCIAL_MATCH}:{person.pid}:comment:{app}").choice(bank)
    return str(text).format_map(words)


@events.handles("likes_you")
def _likes_you(state: GameState, event: dict[str, Any]) -> dict[str, Any]:
    """Someone likes the player first: a "Likes you" row, unless the player got to them first."""
    pid, name = str(event["pid"]), str(event["app"])
    if apps.touched(state, pid, name):
        return {"ok": False, "why": "touched"}
    at = float(event["at"])
    row = {"pid": pid, "comment": str(event.get("comment") or ""), "at": at}
    apply_effect(state, {"type": "social_person", "pid": pid, "app": name, "app_set": {"liked_you_at": at}})
    return apply_effect(state, {"type": "social_app", "app": name, "op": "liked_by", "row": row})


def _queue_likes_you(state: GameState) -> None:
    """The `daily` step: about `likes_you_per_day` x completeness likers per app, spread over the day."""
    day_at = events.daily_at(state)
    day = apps.deck_day(day_at)
    player = state.social.get("player") or {}
    for name in apps.dating_apps():
        per_day = float(apps.app(name).get("likes_you_per_day") or 0)
        if per_day <= 0:
            continue
        rng = stable_rng(state.rng_seed, f"{SOCIAL_MATCH}:likes_you:{name}:{day}")
        expected = per_day * completeness_mult(player)
        count = int(expected) + (1 if rng.random() < expected - int(expected) else 0)
        candidates = apps.order(state, name, day)
        rng.shuffle(candidates)
        picked: list[population.Person] = []
        for index in candidates:
            if len(picked) >= count:
                break
            pid = population.pid_for(index)
            if apps.gone(state, pid) or apps.touched(state, pid, name) or any(e.get("pid") == pid and e["kind"] == "likes_you"
                                                     for e in state.social.get("queue", [])):
                continue
            person = population.profile(state, pid)
            if apps.shows(state, person) and likes_back(state, name, person, super_=False):
                picked.append(person)
        start, end = (float(h) for h in _m()["likes_you_hours"])
        for person in picked:
            # Inside the deck's day's likes_you_hours (clock hours; the day starts at the daily's 04:00).
            at = day_at + (start - events.DAILY_HOUR) + rng.uniform(0.0, end - start)
            events.push(state, at, person.pid, "likes_you", app=name, comment=comment_for(state, name, person))


if _queue_likes_you not in events.daily_hooks:
    events.daily_hooks.append(_queue_likes_you)


# -- the player's actions ------------------------------------------------------------------


def like(state: GameState, app: str, pid: str, *, super_: bool = False, comment: str = "",
         on: str = "") -> dict[str, Any]:
    """Like (or super like) the top card of `app`'s deck (spec §8.2)."""
    row = apps.app(app)
    if apps.likes_left(state, app) <= 0:
        return _no("No likes left today.")
    if super_ and apps.supers_left(state, app) <= 0:
        return _no("No super likes left today.")
    if comment and not row.get("comment_on_like"):
        return _no(f"{apps.label(app)} doesn't send a comment with a like.")
    if len(comment) > COMMENT_MAX:
        return _no(f"A comment is at most {COMMENT_MAX} characters.")
    if apps.top_card(state, app) != pid:
        return _no(f"{_name(state, pid)} isn't on your {apps.label(app)} deck any more.")
    person = population.profile(state, pid)
    now = state.world_clock_hours
    apps.deal(state, app, pid, "super" if super_ else "like")
    apply_effect(state, {"type": "social_person", "pid": pid, "app": app, "app_set": {
        "swiped": "super" if super_ else "like", "at": now, "comment": comment, "on": on}})
    if likes_back(state, app, person, super_=super_):
        events.push(state, now + see_like_hours(state, app, pid), pid, "see_like", app=app)
    clock.advance_time(state, cost_hours(state, app, apps.cost_verb(app)))
    return {"ok": True, "app": app, "pid": pid, "name": person.name, "liked": "super" if super_ else "like"}


def pass_(state: GameState, app: str, pid: str) -> dict[str, Any]:
    """Pass on `app`'s top card, or on a "Likes you" row."""
    waiting = any(r.get("pid") == pid for r in apps.likes_you(state, app))
    if apps.top_card(state, app) != pid and not waiting:
        return _no(f"{_name(state, pid)} isn't on {apps.label(app)} any more.")
    now = state.world_clock_hours
    apps.deal(state, app, pid)
    apply_effect(state, {"type": "social_person", "pid": pid, "app": app, "app_set": {"swiped": "pass", "at": now}})
    if apps.deck_kind(app) == "swipe":
        clock.advance_time(state, cost_hours(state, app, "swipe"))
    return {"ok": True, "app": app, "pid": pid, "name": _name(state, pid), "passed": True}


def like_back(state: GameState, app: str, pid: str, *, comment: str = "") -> dict[str, Any]:
    """Like someone who liked the player first: a match at once (they already liked)."""
    if not any(r.get("pid") == pid for r in apps.likes_you(state, app)):
        return _no(f"{_name(state, pid)} isn't in your Likes any more.")
    if apps.gone(state, pid):
        return _no(f"{_name(state, pid)} is no longer available.")
    if len(comment) > COMMENT_MAX:
        return _no(f"A comment is at most {COMMENT_MAX} characters.")
    now = state.world_clock_hours
    apply_effect(state, {"type": "social_app", "app": app, "op": "drop_like", "pid": pid})
    apply_effect(state, {"type": "social_person", "pid": pid, "app": app, "app_set": {
        "swiped": "like", "at": now, "comment": comment}})
    matched = apply_effect(state, {"type": "social_match", "app": app, "pid": pid, "at": now})
    clock.advance_time(state, cost_hours(state, app, "like"))
    return {"ok": bool(matched.get("ok")), "app": app, "pid": pid, "name": _name(state, pid),
            "thread_id": thread_id(app, pid), **({} if matched.get("ok") else {"error": matched["text"]})}


def swipe(state: GameState, app: str, pid: str, direction: str) -> dict[str, Any]:
    if direction == "pass":
        return pass_(state, app, pid)
    return like(state, app, pid, super_=direction == "super")


def unmatch(state: GameState, pid: str, *, by: str) -> dict[str, Any]:
    if pid not in live_matches(state):
        return _no(f"You're not matched with {_name(state, pid)}.")
    result = apply_effect(state, {"type": "social_unmatch", "pid": pid, "by": by})
    return {"ok": bool(result.get("ok")), "pid": pid, "name": _name(state, pid), "unmatched": True}


def block(state: GameState, pid: str) -> dict[str, Any]:
    if not any(t.get("closed") != "blocked" for t in _threads_of(state, pid)):
        return _no("There's no one to block there.")
    result = apply_effect(state, {"type": "social_unmatch", "pid": pid, "by": "player", "block": True})
    return {"ok": bool(result.get("ok")), "pid": pid, "name": _name(state, pid), "blocked": True}


# -- which app a target is on --------------------------------------------------------------


def _top_cards(state: GameState, kind: str) -> list[tuple[str, str]]:
    """(app, pid) for every `kind` deck with a top card and likes left."""
    out = []
    for name in apps.deck_apps(kind):
        if apps.likes_left(state, name) <= 0:
            continue
        top = apps.top_card(state, name)
        if top:
            out.append((name, top))
    return out


def _waiting(state: GameState) -> list[tuple[str, str]]:
    """(app, pid) for every "Likes you" row."""
    return [(name, row["pid"]) for name in apps.dating_apps() for row in apps.likes_you(state, name)]


def app_for(state: GameState, action: str, pid: str) -> Optional[str]:
    """The app a deck or "Likes you" action on `pid` is on, the first that offers it."""
    if action == "swipe":
        pairs = _top_cards(state, "swipe")
    elif action == "like":
        pairs = _top_cards(state, "browse")
    elif action == "like_back":
        pairs = _waiting(state)
    else:   # pass: a browse card, or a "Likes you" row
        pairs = [(n, apps.top_card(state, n) or "") for n in apps.deck_apps("browse")] + _waiting(state)
    return next((name for name, target in pairs if target == pid), None)


# -- the catalogue (spec §7.1) -------------------------------------------------------------


def _options(state: GameState, pairs: list[tuple[str, str]]) -> tuple[tuple[str, str], ...]:
    seen: dict[str, str] = {}
    for _, pid in pairs:
        if pid and pid not in seen:
            seen[pid] = _name(state, pid)
    return tuple(seen.items())


def _swipe_why_not(state: GameState) -> str:
    names = apps.deck_apps("swipe")
    if names and all(apps.likes_left(state, n) <= 0 for n in names):
        return "No likes left today."
    return "No one new to show right now." if names else ""


def _like_why_not(state: GameState) -> str:
    names = apps.deck_apps("browse")
    if names and all(apps.likes_left(state, n) <= 0 for n in names):
        return "No likes left today."
    return "No one new to show right now." if names else ""


def _direction_label(state: GameState, intent: dict[str, Any]) -> str:
    name = _name(state, str(intent.get("target") or ""))
    direction = str((intent.get("args") or {}).get("dir") or "")
    return {"like": f"Swipe right on {name}", "pass": f"Swipe left on {name}",
            "super": f"Super like {name}"}.get(direction, f"Swipe on {name}")


@phone_verb("swipe", payload={"dir": ArgSpec("enum", ("like", "pass", "super"), required=True)},
            skill="social_swipe", label=_direction_label, why_not=_swipe_why_not)
def _swipe_verb(state: GameState) -> Optional[IntentVerb]:
    pairs = _top_cards(state, "swipe")
    if not pairs:
        return None
    directions = ("like", "pass", "super")
    if all(apps.supers_left(state, name) <= 0 for name, _ in pairs):
        directions = ("like", "pass")
    return IntentVerb("swipe", options=_options(state, pairs), extra={"dir": directions})


@phone_verb("like", payload={"on": ArgSpec("enum", required=True), "comment": ArgSpec("text", max_len=COMMENT_MAX)},
            skill="social_like", label=lambda s, i: f"Like {_name(s, str(i.get('target') or ''))}",
            why_not=_like_why_not)
def _like_verb(state: GameState) -> Optional[IntentVerb]:
    pairs = _top_cards(state, "browse")
    if not pairs:
        return None
    on: list[str] = []
    for _, pid in pairs:
        on.extend(v for v in apps.like_targets(state, pid) if v not in on)
    return IntentVerb("like", options=_options(state, pairs), extra={"on": tuple(on)})


@phone_verb("like_back", payload={"comment": ArgSpec("text", max_len=COMMENT_MAX)}, skill="social_like_back",
            label=lambda s, i: f"Like {_name(s, str(i.get('target') or ''))} back")
def _like_back_verb(state: GameState) -> Optional[IntentVerb]:
    pairs = _waiting(state)
    return IntentVerb("like_back", options=_options(state, pairs)) if pairs else None


@phone_verb("pass", payload={}, skill="social_pass",
            label=lambda s, i: f"Pass on {_name(s, str(i.get('target') or ''))}")
def _pass_verb(state: GameState) -> Optional[IntentVerb]:
    pairs = [(n, apps.top_card(state, n) or "") for n in apps.deck_apps("browse")] + _waiting(state)
    options = _options(state, pairs)
    return IntentVerb("pass", options=options) if options else None


@phone_verb("unmatch", payload={}, skill="social_unmatch",
            label=lambda s, i: f"Unmatch {_name(s, str(i.get('target') or ''))}")
def _unmatch_verb(state: GameState) -> Optional[IntentVerb]:
    pids = live_matches(state)
    return IntentVerb("unmatch", options=tuple((p, _name(state, p)) for p in pids)) if pids else None


@phone_verb("block", payload={}, skill="social_block",
            label=lambda s, i: f"Block {_name(s, str(i.get('target') or ''))}")
def _block_verb(state: GameState) -> Optional[IntentVerb]:
    pids: list[str] = []
    for thread in (state.social.get("threads") or {}).values():
        if thread.get("closed") != "blocked" and thread["pid"] not in pids:
            pids.append(thread["pid"])
    return IntentVerb("block", options=tuple((p, _name(state, p)) for p in pids)) if pids else None


# -- the skills' entry points (engine/skills/builtin/social.py) ---------------------------


def act(state: GameState, action: str, target: str, args: dict[str, Any]) -> dict[str, Any]:
    """One deck action, its app found from the target (the catalogue has already checked it)."""
    if action in ("unmatch", "block"):
        return unmatch(state, target, by="player") if action == "unmatch" else block(state, target)
    app = app_for(state, action, target)
    if app is None:
        return _no(f"{_name(state, target)} isn't there any more.")
    if action == "swipe":
        return swipe(state, app, target, str(args.get("dir") or ""))
    if action == "like":
        return like(state, app, target, comment=str(args.get("comment") or ""), on=str(args.get("on") or ""))
    if action == "like_back":
        return like_back(state, app, target, comment=str(args.get("comment") or ""))
    return pass_(state, app, target)


# -- the payload ------------------------------------------------------------------------------


@section("likes_you", time_varying=True)
def _likes_you_section(state: GameState, session: Any) -> list[dict[str, Any]]:
    """Every "Likes you" row on an app that shows them: who, their comment, when."""
    out: list[dict[str, Any]] = []
    for name in apps.dating_apps():
        if not apps.app(name).get("likes_you_visible"):
            continue
        for row in apps.likes_you(state, name):
            person = population.profile(state, row["pid"])
            out.append({"app": name, "pid": row["pid"], "name": person.name, "age": person.age,
                        "comment": row.get("comment", ""), "at": row.get("at")})
    return out
