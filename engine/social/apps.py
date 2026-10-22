"""
The apps (v0.22.0 spec §6): an app is an ENGINE SURFACE, read from
`apps.yaml`. This module holds the table's readers, the dating apps' DECKS and
their daily limits; matching.py holds what happens on them.

**The deck.** A dating app's day's deck is its pool's indices plus its
overlap band, shuffled by `stable_rng(seed, f"{SOCIAL_MATCH}:deck:{app}:{day}")`
(a stable key on an existing stream: no new stream, nothing drawn from a
counter), then filtered LAZILY as cards are shown: a card is the first person
in that order, from `deck_pos`, whom the player has not touched on this app
and whom the player's discovery settings let through (`shows`). So nothing
static is stored: `state.social["apps"][app]` keeps only `likes_left`,
`supers_left`, the deck's `day`, `deck_pos` and `likes_you` (Front Porch's
list). `deck_pos` moves past every card the filter skipped, so someone
filtered out earlier in the day waits for the next day's reshuffle even if
the player widens their discovery settings meanwhile.

A person the player has unmatched or blocked is GONE (`gone`): off every
deck, out of every "Likes you", and never matched again on any app.

A deck's day turns at the `daily` event's hour (04:00, events.DAILY_HOUR),
when `_reset_likes` (a `daily_hooks` step) refills the likes and reshuffles.
Before an app is first touched its state is the day's defaults, read and
never written (`app_state`), so reading a deck writes nothing.

Every write is the engine-only `social_app` effect (rule 3).
"""

from __future__ import annotations

import math
from typing import Any, Optional

from engine import social
from engine.game.effects import EffectContext, apply_effect, effect_kind
from engine.social.kinds import recorded
from engine.game.rng import SOCIAL_MATCH, stable_rng
from engine.game.state import GameState
from engine.social import events, population
from engine.social.payload import section

#: An app's `kind:` (spec §6).
KINDS: tuple[str, ...] = ("dating", "messenger", "games", "gallery", "calendar", "contacts", "settings")
#: What a thread may carry; each has a sender and a renderer (spec §6).
CAPABILITIES: tuple[str, ...] = ("text", "photo", "voice", "video")
#: A dating app's `deck:`.
DECKS: tuple[str, ...] = ("swipe", "browse")
#: Every `cost_minutes` key, each read by the verb that spends it: swipe,
#: like (matching.py, T7), edit (turn.edit_profile, T7), move (a game move,
#: T22). A message's cost is conversation.yaml's `costs:` (v0.23.0 spec §3.3):
#: a `text`, `photo`, `voice` or `video` row here would be read by nothing.
COST_VERBS: tuple[str, ...] = ("swipe", "like", "edit", "move")
#: The `social_app` `set` op's keys (a test or a harness setting a counter).
COUNTERS: tuple[str, ...] = ("likes_left", "supers_left", "day", "deck_pos")


# -- the table ------------------------------------------------------------------


def _all() -> dict[str, Any]:
    rows = social.data("apps").get("apps")
    return rows if isinstance(rows, dict) else {}


def app(name: str) -> dict[str, Any]:
    """The `apps.yaml` row of `name`; a ValueError naming the key when there is none."""
    row = _all().get(name)
    if not isinstance(row, dict):
        raise ValueError(f"social: apps.yaml: apps.{name}: no such app")
    return row


def dating_apps() -> list[str]:
    return [name for name, row in _all().items() if isinstance(row, dict) and row.get("kind") == "dating"]


def capabilities(name: str) -> tuple[str, ...]:
    return tuple(str(c) for c in app(name).get("capabilities") or ())


def label(name: str) -> str:
    return str(app(name).get("label") or name)


def deck_kind(name: str) -> str:
    """`swipe`, `browse`, or "" for an app with no deck."""
    return str(app(name).get("deck") or "")


def deck_apps(kind: str) -> list[str]:
    """The dating apps whose deck is `kind`, in apps.yaml's order."""
    return [name for name in dating_apps() if deck_kind(name) == kind]


def cost_verb(name: str) -> str:
    """The `cost_minutes` key a like or pass on `name`'s deck spends."""
    return "swipe" if deck_kind(name) == "swipe" else "like"


# -- the app's state -------------------------------------------------------------


def deck_day(hours: float) -> int:
    """The deck's day at an absolute in-game hour: it turns at the `daily` event's hour."""
    return math.floor((float(hours) - events.DAILY_HOUR) / 24.0)


def defaults(name: str, day: int) -> dict[str, Any]:
    row = app(name)
    return {
        "likes_left": int(row.get("likes_per_day") or 0),
        "supers_left": int(row.get("super_likes_per_day") or 0),
        "day": int(day),
        "deck_pos": 0,
        "likes_you": [],
    }


def app_state(state: GameState, name: str) -> dict[str, Any]:
    """READ ONLY: the stored state of `name`, or the day's defaults before it is first touched."""
    stored = (state.social.get("apps") or {}).get(name)
    return stored if isinstance(stored, dict) else defaults(name, deck_day(state.world_clock_hours))


def likes_left(state: GameState, name: str) -> int:
    return int(app_state(state, name).get("likes_left", 0))


def supers_left(state: GameState, name: str) -> int:
    return int(app_state(state, name).get("supers_left", 0))


def likes_you(state: GameState, name: str) -> list[dict[str, Any]]:
    return list(app_state(state, name).get("likes_you") or [])


# -- the deck --------------------------------------------------------------------


def order(state: GameState, name: str, day: int) -> list[int]:
    """The day's deck order: pool + overlap band, shuffled on a stable key (no new stream)."""
    indices = list(population.pool(name)) + list(population.overlap(name))
    stable_rng(state.rng_seed, f"{SOCIAL_MATCH}:deck:{name}:{day}").shuffle(indices)
    return indices


def on_app(state: GameState, pid: str, name: str) -> dict[str, Any]:
    """What the player and `pid` have done on `name` (people[pid]["apps"][name]); {} when nothing."""
    person = (state.social.get("people") or {}).get(pid) or {}
    return (person.get("apps") or {}).get(name) or {}


def gone(state: GameState, pid: str) -> bool:
    """Blocked by the player, or unmatched by either side: off every app, for good. Explicit keys only."""
    person = (state.social.get("people") or {}).get(pid) or {}
    return bool(person.get("blocked") or person.get("unmatched_by"))


def touched(state: GameState, pid: str, name: str) -> bool:
    """
    Whether `pid` is off `name`'s deck: swiped or liked there, a "Likes you"
    row there, matched there, or `gone`. Read from explicit keys only -- a
    bare people[pid] (`person_rng`'s counters) means nothing (T5's note).
    """
    if gone(state, pid):
        return True
    mine = on_app(state, pid, name)
    return bool(mine.get("swiped") or mine.get("liked_you_at") is not None or mine.get("matched_at") is not None)


def _limit(state: GameState) -> Optional[int]:
    """discovery.distance's farthest table distance, or None (no neighbourhood, or no setting)."""
    player = state.social.get("player") or {}
    setting = (player.get("discovery") or {}).get("distance")
    table = (social.data("apps").get("matching") or {}).get("discovery_distance") or {}
    if not player.get("neighbourhood") or setting not in table:
        return None
    return int(table[setting])


def shows(state: GameState, person: population.Person) -> bool:
    """The player's discovery settings let `person` onto a deck: the filter's sex, the age range, the distance."""
    player = state.social.get("player") or {}
    discovery = player.get("discovery") or {}
    mode = str((social.data("population").get("filter") or {}).get("sex", "opposite"))
    mine = str(player.get("sex") or "female")
    if mode == "opposite" and person.sex == mine:
        return False
    if mode == "same" and person.sex != mine:
        return False
    if "age_min" in discovery and person.age < int(discovery["age_min"]):
        return False
    if "age_max" in discovery and person.age > int(discovery["age_max"]):
        return False
    limit = _limit(state)
    if limit is not None:
        table = social.data("population").get("distance") or {}
        if int((table.get(player["neighbourhood"]) or {}).get(person.neighbourhood, 0)) > limit:
            return False
    return True


def _scan(state: GameState, name: str) -> Optional[tuple[int, str]]:
    """(position in the day's order, pid) of the top card, or None when the deck is spent."""
    if deck_kind(name) not in DECKS:
        return None
    current = app_state(state, name)
    ordered = order(state, name, int(current["day"]))
    for position in range(int(current.get("deck_pos", 0)), len(ordered)):
        pid = population.pid_for(ordered[position])
        if touched(state, pid, name):
            continue
        if shows(state, population.profile(state, pid)):
            return position, pid
    return None


def top_card(state: GameState, name: str) -> Optional[str]:
    """The pid on top of `name`'s deck now, or None. Reads only."""
    found = _scan(state, name)
    return found[1] if found else None


# -- the effect -------------------------------------------------------------------


@effect_kind("social_app")
@recorded
def _e_app(state: GameState, effect: dict[str, Any], ctx: EffectContext) -> dict[str, Any]:
    """
    Engine-only: one app's counters and lists. Ops: `reset` (the day's likes,
    a fresh deck), `deal` (a card acted on: `like` spends a like, `super` a
    super like too; the deck moves past it), `drop_like` (a "Likes you" row
    answered), `liked_by` (a "Likes you" row added), `set` (named counters).
    """
    if not state.social:
        return {"type": "social_app", "ok": False, "text": "no social slice"}
    name = str(effect.get("app") or "")
    try:
        app(name)
    except ValueError as exc:
        return {"type": "social_app", "ok": False, "text": str(exc)}
    slot = state.social.setdefault("apps", {})
    current = slot.get(name)
    if not isinstance(current, dict):
        current = slot[name] = defaults(name, deck_day(state.world_clock_hours))
    op = effect.get("op")
    pid = str(effect.get("pid") or "")
    if op == "reset":
        current.update(defaults(name, int(effect["day"])), likes_you=current.get("likes_you") or [])
    elif op == "deal":
        if effect.get("spend") in ("like", "super"):
            current["likes_left"] = max(0, int(current.get("likes_left", 0)) - 1)
        if effect.get("spend") == "super":
            current["supers_left"] = max(0, int(current.get("supers_left", 0)) - 1)
        if effect.get("position") is not None:
            current["deck_pos"] = int(effect["position"]) + 1
        current["likes_you"] = [row for row in current.get("likes_you") or [] if row.get("pid") != pid]
    elif op == "drop_like":
        current["likes_you"] = [row for row in current.get("likes_you") or [] if row.get("pid") != pid]
    elif op == "liked_by":
        current.setdefault("likes_you", []).append(dict(effect["row"]))
    elif op == "set":
        values = dict(effect.get("values") or {})
        unknown = sorted(set(values) - set(COUNTERS))
        if unknown:
            return {"type": "social_app", "ok": False, "text": f"social_app set: no counter {unknown}"}
        current.update({key: int(value) for key, value in values.items()})
    else:
        return {"type": "social_app", "ok": False, "text": f"social_app: unknown op {op!r}"}
    return {"type": "social_app", "ok": True, "text": f"{name} {op}"}


def deal(state: GameState, name: str, pid: str, spend: str = "") -> dict[str, Any]:
    """Record `pid` acted on from `name`'s deck (`spend`: "", like or super)."""
    found = _scan(state, name)
    position = found[0] if found and found[1] == pid else None
    return apply_effect(state, {"type": "social_app", "app": name, "op": "deal", "pid": pid,
                                "spend": spend, "position": position})


# -- the day ----------------------------------------------------------------------


def _reset_likes(state: GameState) -> None:
    """The `daily` step (spec §9.1): every dating app's likes refilled and its deck reshuffled."""
    day = deck_day(events.daily_at(state))
    for name in dating_apps():
        apply_effect(state, {"type": "social_app", "app": name, "op": "reset", "day": day})


if _reset_likes not in events.daily_hooks:
    events.daily_hooks.append(_reset_likes)


# -- the payload ---------------------------------------------------------------------


def _label_of(table: str, ident: str) -> str:
    for row in population.table(table):
        if isinstance(row, dict) and row.get("id") == ident:
            return str(row.get("label", ident))
    return ident


def card(state: GameState, name: str, pid: str) -> dict[str, Any]:
    """What a deck shows of `pid` on `name`: the profile's facts, never a hidden value."""
    person = population.profile(state, pid)
    browse = deck_kind(name) == "browse"
    out: dict[str, Any] = {
        "pid": pid,
        "name": person.name,
        "age": person.age,
        "job": _label_of("jobs", person.job),
        "neighbourhood": _label_of("neighbourhoods", person.neighbourhood),
        "bio": person.bio.get(name, ""),
        "photos": [{"id": f"photo_{i}", "caption": _label_of("photo_set", photo)}
                   for i, photo in enumerate(person.photos)],
        "hobbies": [_label_of("hobbies", h) for h in person.hobbies],
        "also_on": [label(other) for other in population.apps_of(pid) if other != name],
        "avatar_url": _avatar(state, pid),
    }
    if browse:
        out["prompts"] = [{"id": f"prompt_{i}", "q": q, "a": a} for i, (q, a) in enumerate(person.prompts)]
        mine = set((state.social.get("player") or {}).get("hobbies") or [])
        shared = [h for h in person.hobbies if h in mine]
        out["shared"] = f"You both like {_label_of('hobbies', shared[0]).lower()}" if shared else ""
    return out


def _avatar(state: GameState, pid: str) -> str:
    """Their ready portrait's URL (spec §13.4, T19), else "": the client draws the procedural tile."""
    from engine.social import media   # lazily: media imports this module

    return media.portrait_url(state, pid)


def like_targets(state: GameState, pid: str) -> tuple[str, ...]:
    """The `on:` values a like on `pid` may name: photo_<n> and prompt_<n>."""
    person = population.profile(state, pid)
    return (tuple(f"photo_{i}" for i in range(len(person.photos)))
            + tuple(f"prompt_{i}" for i in range(len(person.prompts))))


@section("deck", time_varying=True)
def _deck_section(state: GameState, session: Any) -> dict[str, Any]:
    """Per dating app: its deck kind, the top card (or None) and what is left today."""
    out: dict[str, Any] = {}
    for name in dating_apps():
        if deck_kind(name) not in DECKS:
            continue
        top = top_card(state, name)
        out[name] = {
            "app": name,
            "deck": deck_kind(name),
            "card": card(state, name, top) if top else None,
            "likes_left": likes_left(state, name),
            "supers_left": supers_left(state, name),
        }
    return out
