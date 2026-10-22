"""
Conversations as episodes (v0.23.0 spec §3.3, §3.5, §4.1-§4.7).

It replaces v0.22.0's reply LATENCY (lognormal read and reply delays) with
episodes: a burst of conversation that answers at once while it is going,
and ends at a natural point, nudged by the person's day and character.

**An episode** lives at ``people[pid]["episode"]`` (§4.1), written only by
the ``social_episode`` effect (rule 3). It opens when the person answers a
cold message (the per-episode-start draws, §4.6), when an initiation of
theirs lands (§4.7), or when a scene starts (``scene.open_scene``, kind
``scene``, T13). A chat closes when it lapses (no message either way for
``episode_gap_minutes``, the ``episode_lapse`` event), when a new
conversation begins after a sign-off, or when the two meet in person (end
``met``); a scene episode never lapses and closes only at the scene's end
(``scene_end``, m9). The closed row joins ``recap_due`` (T6 recaps it).

**Instant replies (§4.3).** In an open episode the player's send queues the
person's ``read`` at the SEND's minute, so the send's own ``advance_time``
walks read, decision and due message: no ``wait``. A person who is not
available (their schedule and phone habits, ``available``) reads at
``next_available``: a schedule boundary, never a draw (§3.5 item 3).

**Sends while they type (I6).** A due reply no voicing pass has MARKED is
re-decided in place by a later send (one reply per burst); a MARKED one is
never touched: the pass's commit sees the player spoke after its snapshot
and queues the NEXT decision then (``after_commit``). ``MARKED`` carries the
marks into the mechanics action (Plan decision 9).

**The nudge (§4.4).** Each decision weighs the episode's length against its
drawn target, the person's energy, and the minutes to their next schedule
boundary; past ``talk.winding_at`` they start to wind down, past
``talk.sign_off_at`` they sign off, with the engine's reason (``reasons:``)
for the voice to put in their words. Nothing here is a fixed gap.

Every draw is ``person_rng(state, SOCIAL_CONVO, pid)`` inside a social
handler (rule 4), split into a function a test can force (``_target_draw``,
``_ghost_factor``, ``_reply_factor``, ``_promise_drawn``). Every number is
``conversation.yaml``'s (rule 10; unmeasured until T9's simulator).
"""

from __future__ import annotations

import contextlib
import dataclasses
import logging
import math
import random
import re
from contextvars import ContextVar
from typing import Any, Iterable, Iterator, NamedTuple, Optional

from engine import social
from engine.game.effects import EffectContext, apply_effect, effect_kind
from engine.game.rng import SOCIAL_CONVO
from engine.game.state import GameState
from engine.social import apps, attrs, behaviour, events, growth, messaging, population, promises, relationships, windows
from engine.social.kinds import Decision, decision_from_row, recorded, stage_rank

logger = logging.getLogger(__name__)

#: The due messages a live voicing pass has marked, visible to the running action (Plan decision 9).
MARKED: ContextVar[frozenset[str]] = ContextVar("social_marked", default=frozenset())

#: The situations a burst re-decides: the person's side of a conversation already going.
_REPLY_SITUATIONS: frozenset[str] = frozenset({"reply", "answer_request", "promised_message", "followup", "news",
                                               "opens_up", "offer_number"})

#: An episode that is still going (any other `end` is closed and gone from the row).
OPEN_ENDS: tuple[str, ...] = ("none", "winding", "signed_off")

#: The `social_episode` ops.
EPISODE_OPS: tuple[str, ...] = ("open", "exchange", "end", "close", "redecide", "one_more")

#: The sign-offs, by what ended the conversation, each with its own away time (`talk.away_after_sign_off`,
#: T3 review M6): their next schedule `boundary`, a `glance` at work, `energy` spent, `length` reached,
#: or the `player` saying "talk later".
SIGN_OFF_KEYS: tuple[str, ...] = ("boundary", "glance", "energy", "length", "player")

#: The `conversation.yaml` `reasons:` keys (the engine's words for why talk ends), and `reasons_recap:`'s.
REASON_KEYS: tuple[str, ...] = ("work", "lunch_over", "asleep", "out", "early", "energy", "length", "glance", "player")

#: Initiation situations retired as bare situations (spec §13.1): a window's row says `window_message`.
RETIRED_SITUATIONS: frozenset[str] = frozenset({"good_morning", "check_in", "late_night"})

#: The phone habits (spec §4.2) and the values each may take.
HABITS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("at_work", ("never", "glances", "chatty")),
    ("late_night", ("no", "sometimes", "night_owl")),
    ("in_company", ("rude_not_to", "glances")),
)


def _data() -> dict[str, Any]:
    return social.data("conversation")


def _talk() -> dict[str, Any]:
    return _data().get("talk") or {}


# -- load-time check (conversation.yaml) -----------------------------------------------------------


def _fault(key: str, message: str) -> ValueError:
    return ValueError(f"social: conversation.yaml: {key}: {message}")


def _is_num(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _num(block: dict[str, Any], key: str, where: str, *, low: float = 0.0, high: Optional[float] = None) -> None:
    value = block.get(key)
    if not _is_num(value) or value < low or (high is not None and value > high):
        span = f"{low} to {high}" if high is not None else f"at least {low}"
        raise _fault(f"{where}.{key}" if where else key, f"must be a number {span}, not {value!r}")


def _pair(value: Any, where: str, *, whole: bool = False) -> None:
    ok = (isinstance(value, list) and len(value) == 2 and all(_is_num(v) and v >= 0 for v in value)
          and value[0] <= value[1] and (not whole or all(isinstance(v, int) for v in value)))
    if not ok:
        raise _fault(where, f"must be [low, high]{', whole numbers' if whole else ''} with low <= high, not {value!r}")


def _block(data: dict[str, Any], key: str) -> dict[str, Any]:
    value = data.get(key)
    if not isinstance(value, dict):
        raise _fault(key, "must be a mapping")
    return value


def check_data(data: dict[str, Any], *, archetypes: Iterable[str] = ()) -> None:
    """conversation.yaml whole (spec §3.3, §4): every block the engine reads, each the shape it reads.
    With ``archetypes``, every per-archetype key must name one (or be ``default``). A ValueError
    naming the file and the key."""
    known = set(archetypes) | {"default"}
    costs = _block(data, "costs")
    for kind in ("text", "voice", "photo", "video"):
        _num(costs, kind, "costs")
    clock = _block(data, "clock")
    _num(clock, "evening", "clock", high=23)
    _num(clock, "morning", "clock", high=23)
    _num(clock, "min_sleep_hours", "clock")
    if "work_lead_hours" in clock:
        _num(clock, "work_lead_hours", "clock")
    if not _is_num(data.get("episode_gap_minutes")) or data["episode_gap_minutes"] <= 0:
        raise _fault("episode_gap_minutes", "must be a number above 0")
    if "together" in data:
        _num(_block(data, "together"), "hold_retry_minutes", "together", low=1.0)
    habits = _block(data, "habits")
    weights = _block(habits, "weights")
    if "default" not in weights:
        raise _fault("habits.weights", "must have a `default` row")
    for arch, table in weights.items():
        where = f"habits.weights.{arch}"
        if archetypes and arch not in known:
            raise _fault(where, f"{arch!r} is not a behaviours.yaml archetype")
        if not isinstance(table, dict):
            raise _fault(where, "must be a mapping of habit to option weights")
        for habit, options in HABITS:
            row = table.get(habit)
            if not isinstance(row, dict) or not row:
                raise _fault(f"{where}.{habit}", f"must weigh {', '.join(options)}")
            for name, weight in row.items():
                if name not in options:
                    raise _fault(f"{where}.{habit}", f"{name!r} is not one of {', '.join(options)}")
                _num(row, name, f"{where}.{habit}")
            if sum(float(w) for w in row.values()) <= 0:
                raise _fault(f"{where}.{habit}", "weighs nothing above 0")
        unknown = sorted(str(k) for k in table if k not in dict(HABITS))
        if unknown:
            raise _fault(where, f"has unknown habits {', '.join(unknown)}")
    _num(habits, "night_owl_shift_hours", "habits", high=12)
    talk = _block(data, "talk")
    exchanges = _block(talk, "exchanges")
    if "default" not in exchanges:
        raise _fault("talk.exchanges", "must have a `default` row")
    for arch, span in exchanges.items():
        if archetypes and arch not in known:
            raise _fault(f"talk.exchanges.{arch}", f"{arch!r} is not a behaviours.yaml archetype")
        _pair(span, f"talk.exchanges.{arch}", whole=True)
        if span[0] < 1:
            raise _fault(f"talk.exchanges.{arch}", "must be at least 1")
    per_depth = talk.get("per_depth")
    if not (isinstance(per_depth, list) and len(per_depth) == len(growth.RUNGS)
            and all(_is_num(v) and v > 0 for v in per_depth)):
        raise _fault("talk.per_depth", f"must be {len(growth.RUNGS)} numbers above 0, one per depth")
    late = _block(talk, "late_mult")
    for key in ("default", "night_owl"):
        _num(late, key, "talk.late_mult")
    for key in ("work_mult", "energy_per_exchange", "short_player_chars", "short_extra_energy",
                "topic_energy_back", "boundary_minutes", "winding_at", "sign_off_at", "player_chars_kept"):
        _num(talk, key, "talk")
    if float(talk["winding_at"]) > float(talk["sign_off_at"]):
        raise _fault("talk.winding_at", "must not be above sign_off_at")
    _pair(talk.get("after_sign_off"), "talk.after_sign_off", whole=True)
    away = talk.get("away_after_sign_off")
    if not isinstance(away, dict) or set(away) != set(SIGN_OFF_KEYS):
        raise _fault("talk.away_after_sign_off", f"must give minutes for exactly {', '.join(SIGN_OFF_KEYS)}")
    for key in SIGN_OFF_KEYS:
        _num(away, key, "talk.away_after_sign_off")
    modes = _block(data, "modes")
    for key in ("chatting_after", "deep_energy", "deep_player_chars"):
        _num(modes, key, "modes")
    if "deep_as_chatting" in modes and not isinstance(modes["deep_as_chatting"], bool):
        raise _fault("modes.deep_as_chatting", f"must be true or false, not {modes['deep_as_chatting']!r}")
    caps = _block(modes, "caps")
    from engine.social.kinds import MODES

    for mode in MODES:
        row = caps.get(mode)
        if not isinstance(row, dict):
            raise _fault(f"modes.caps.{mode}", "must be a mapping {bubbles, bubble_chars, max_tokens}")
        _pair(row.get("bubbles"), f"modes.caps.{mode}.bubbles", whole=True)
        if row["bubbles"][0] < 1:
            raise _fault(f"modes.caps.{mode}.bubbles", "must start at 1 or more")
        _num(row, "bubble_chars", f"modes.caps.{mode}", low=1)
        _num(row, "max_tokens", f"modes.caps.{mode}", low=1)
    reply = _block(data, "reply")
    depth_factor = reply.get("depth_factor")
    if not (isinstance(depth_factor, list) and len(depth_factor) == len(growth.RUNGS)
            and all(_is_num(v) and v >= 0 for v in depth_factor)):
        raise _fault("reply.depth_factor", f"must be {len(growth.RUNGS)} numbers 0 or more, one per depth")
    _pair(reply.get("interest_factor"), "reply.interest_factor")
    stage_factor = _block(reply, "stage_factor")
    from engine.social.kinds import STAGES

    for stage in stage_factor:
        if stage != "default" and stage not in STAGES:
            raise _fault("reply.stage_factor", f"{stage!r} is not a stage (or default)")
        _num(stage_factor, stage, "reply.stage_factor")
    if "default" not in stage_factor:
        raise _fault("reply.stage_factor", "must have a `default` row")
    _num(_block(data, "initiation"), "skip_if_talked_minutes", "initiation")
    if not _is_num(data.get("left_on_read_quiet_minutes")) or data["left_on_read_quiet_minutes"] < 0:
        raise _fault("left_on_read_quiet_minutes", "must be minutes, 0 or more")
    reasons = _block(data, "reasons")
    for key in REASON_KEYS:
        if not isinstance(reasons.get(key), str) or not reasons[key].strip():
            raise _fault(f"reasons.{key}", "must be the engine's words, a non-empty line")
    recap = _block(data, "reasons_recap")
    if set(recap) != set(REASON_KEYS):
        raise _fault("reasons_recap", f"must give a recap line for exactly {', '.join(REASON_KEYS)}")
    for key in REASON_KEYS:
        if not isinstance(recap.get(key), str) or not recap[key].strip():
            raise _fault(f"reasons_recap.{key}", "must be the recap's words, a non-empty line")


# -- the fixed habits (I14) -----------------------------------------------------------------------


@attrs.drawer("habits", SOCIAL_CONVO)
def _habits(state: GameState, pid: str, rng: random.Random) -> dict[str, str]:
    arch = population.profile(state, pid).archetype
    weights = (_data().get("habits") or {}).get("weights") or {}
    table = weights.get(arch) or weights.get("default") or {}
    out: dict[str, str] = {}
    for habit in ("at_work", "late_night", "in_company"):
        options = sorted((table.get(habit) or {}).items())
        names, counts = [n for n, _ in options], [float(w) for _, w in options]
        out[habit] = rng.choices(names, weights=counts)[0] if sum(counts) > 0 else names[0]
    return out


# -- availability and the boundary (§4.2, §4.4) ---------------------------------------------------


class Availability(NamedTuple):
    yes: bool
    cap: str = ""          # "" | "quick" | "glance"


def _status(state: GameState, pid: str, at: float) -> str:
    """Their schedule status with habits applied: a night owl is still up in the first hours of their sleep band."""
    person = population.profile(state, pid)
    status = behaviour.status_at(person, at)
    if status == "asleep" and attrs.of(state, pid)["habits"]["late_night"] == "night_owl":
        shift = float((_data().get("habits") or {}).get("night_owl_shift_hours", 3))
        if behaviour.status_at(person, at - shift) != "asleep":
            return "free"
    return status


def available(state: GameState, pid: str, at: float) -> Availability:
    """Derived: will they answer a cold message now? Draws nothing, writes nothing (I14)."""
    from engine.social import life   # lazily: life imports this module

    if life.unavailable(state, pid, at):                      # a holiday (T17): away, whatever the hour
        return Availability(False)
    habits = attrs.of(state, pid)["habits"]
    status = _status(state, pid, at)
    if status == "free":
        return Availability(True)
    if status == "out":
        return Availability(True, "quick")
    if status == "work":
        return {"chatty": Availability(True), "glances": Availability(True, "glance")}.get(
            habits["at_work"], Availability(False))
    if habits["late_night"] == "sometimes" and behaviour.status_at(population.profile(state, pid), at - 1.0) != "asleep":
        return Availability(True, "quick")                    # their first sleep hour
    return Availability(False)


def next_available(state: GameState, pid: str, at: float) -> float:
    """The first whole hour (or `at` itself) at which they are available: a schedule boundary, never a draw."""
    if available(state, pid, at).yes:
        return at
    hour = math.floor(at) + 1.0
    for _ in range(24 * 8):
        if available(state, pid, hour).yes:
            return hour
        hour += 1.0
    raise ValueError(f"social: population.yaml: {pid} is never available in a week")


def _openness(av: Availability) -> int:
    """How available an answer is: 0 not at all, 1 capped (`quick` or `glance`), 2 fully."""
    return 0 if not av.yes else (1 if av.cap else 2)


def boundary_minutes(state: GameState, pid: str, at: float) -> Optional[float]:
    """Minutes until their status next changes in a way that ends talk; None when no boundary in 24 h.
    Only a change to LESS available is one (review I1): work starting for a `never` or `glances`
    worker, going out, their bed band. Coming off work, coming home (out -> free), a chatty worker's
    shift start and a night owl's late band are not: talk opens up there, or carries on (§4.4)."""
    now = _openness(available(state, pid, at))
    hour = math.floor(at) + 1.0
    for _ in range(24):
        if _openness(available(state, pid, hour)) < now:
            return (hour - at) * 60.0
        hour += 1.0
    return None


# -- the episode, read ------------------------------------------------------------------------------


def episode(state: GameState, pid: str) -> Optional[dict[str, Any]]:
    """The person's open episode (any end but a closed one), or None."""
    row = (((state.social or {}).get("people") or {}).get(pid) or {}).get("episode")
    return row if row and row.get("end") in OPEN_ENDS else None


def cap_key(state: GameState, pid: str) -> str:
    """What every per-episode cap is counted against (spec §6.4, I9): the open episode's id, else
    `after:<the last closed episode's id>` -- so the between-episodes allowance starts afresh each time
    an episode closes (pre-flight F36; a single fixed key would never reset). Read-only."""
    ep = episode(state, pid)
    if ep is not None:
        return str(ep["id"])
    person = ((state.social or {}).get("people") or {}).get(pid) or {}
    return f"after:{person.get('last_episode', '')}"


def _hour_words(hour: float) -> str:
    h = int(round(hour)) % 24
    if h == 0:
        return "midnight"
    if h == 12:
        return "noon"
    return f"{h % 12 or 12}{'am' if h < 12 else 'pm'}"


def available_words(state: GameState, pid: str, at: float) -> str:
    """What the player knows of their days (spec §4.2's "What the player sees"): at depth 1 or more,
    their working hours today in the engine's words ("Usually at work till 7pm"); below it, nothing.
    Derived from their schedule; draws nothing, writes nothing."""
    if growth.depth(state, pid) < 1:
        return ""
    work = windows.work_bands(state, pid, int(at // 24))
    if not work:
        return "Usually free today"
    if work[0][0] <= at < work[-1][1]:
        return f"At work till {_hour_words(work[-1][1])}"
    return f"Usually at work till {_hour_words(work[-1][1])}"


def _gap_hours() -> float:
    return float(_data().get("episode_gap_minutes", 45)) / 60.0


def _message_text(message: dict[str, Any]) -> str:
    return " ".join(str(b) for b in message.get("bubbles") or ()) or str(message.get("transcript") or "")


def _last_player_text(state: GameState, thread_id: str) -> Optional[str]:
    for m in reversed((messaging.thread(state, thread_id) or {}).get("messages") or []):
        if m.get("from") == "player" and messaging.shown(m):
            return _message_text(m)
    return None


def names_label(text: str, label: str) -> bool:
    """`label` named in `text`: case-folded, matched literally (`re.escape`), on whole words -- a word
    boundary on each side only where that edge of the label is itself a word character (Review Focus 4)."""
    needle = str(label or "").casefold().strip()
    if not needle:
        return False
    head = r"(?<!\w)" if re.match(r"\w", needle[0]) else ""
    tail = r"(?!\w)" if re.match(r"\w", needle[-1]) else ""
    return re.search(f"{head}{re.escape(needle)}{tail}", str(text or "").casefold()) is not None


def _named_topics(state: GameState, pid: str, text: str) -> list[str]:
    """The person's topic ids whose label the text names; a named hobby counts as their `hobbies` topics."""
    if not text:
        return []
    rows = growth.topics_of(state, pid)
    named = [str(r["id"]) for r in rows if names_label(text, str(r.get("label") or ""))]
    labels = {str(r.get("id")): str(r.get("label") or "") for r in population.table("hobbies") if isinstance(r, dict)}
    hobby = any(names_label(text, name) for h in population.profile(state, pid).hobbies
                for name in (labels.get(h, ""), h.replace("_", " ")))
    if hobby:
        named += [str(r["id"]) for r in rows if r.get("kind") == "hobbies" and str(r["id"]) not in named]
    return named


def _touched_at_depth(state: GameState, pid: str, ep: dict[str, Any]) -> bool:
    """The episode touched one of their topics whose kind is in their current rung."""
    kinds = growth.RUNGS[growth.depth(state, pid)][1]
    rows = {str(r["id"]): str(r.get("kind")) for r in social.data("topics").get("topics") or [] if r.get("id")}
    return any(rows.get(str(t)) in kinds for t in ep.get("topics") or ())


def _due_reply(state: GameState, thread_id: str) -> Optional[dict[str, Any]]:
    """The thread's unvoiced reply-family due message, if one waits."""
    t = messaging.thread(state, thread_id) or {}
    for m in reversed(t.get("messages") or []):
        if m.get("voiced") is False and ((m.get("decision") or {}).get("situation") in _REPLY_SITUATIONS):
            return m
        if m.get("from") != "player":
            return None
    return None


def _read_pending(state: GameState, pid: str, thread_id: str) -> bool:
    """A `read` for that thread is already queued: the burst rule for someone not reading yet."""
    return any(e["pid"] == pid and e["kind"] == "read" and e.get("thread_id") == thread_id
               for e in state.social.get("queue") or [])


# -- the forceable draws (lesson 1) ---------------------------------------------------------------


def _target_draw(state: GameState, pid: str, rng: random.Random) -> int:
    """The episode's target length before scaling: a whole number in the archetype's `talk.exchanges`."""
    table = _talk().get("exchanges") or {}
    low, high = table.get(population.profile(state, pid).archetype) or table.get("default") or [6, 14]
    return rng.randint(int(low), int(high))


def _ghost_factor(state: GameState, pid: str) -> float:
    """`ghost_per_episode × (1 - interest/100) × stage_factor` (§4.6); split out to be forced (lesson 1)."""
    person = state.social["people"][pid]
    arch = behaviour.archetype(population.profile(state, pid).archetype)
    factors = (_data().get("reply") or {}).get("stage_factor") or {}
    stage = str(person.get("stage") or "matched")
    return (float(arch.ghost_per_episode) * (1 - float(person.get("interest", 50)) / 100.0)
            * float(factors.get(stage, factors.get("default", 1.0))))


def _reply_factor(state: GameState, pid: str) -> float:
    """`reply_prob × interest_factor × depth_factor` (§4.6); split out to be forced (lesson 1)."""
    person = state.social["people"][pid]
    arch = behaviour.archetype(population.profile(state, pid).archetype)
    low, high = (_data().get("reply") or {}).get("interest_factor") or [0.3, 1.5]
    interest = float(person.get("interest", 50)) / 100.0
    depth_factor = ((_data().get("reply") or {}).get("depth_factor") or [1.0] * 5)[growth.depth(state, pid)]
    return float(arch.reply_prob) * (low + (high - low) * interest) * float(depth_factor)


def _promise_drawn(state: GameState, pid: str) -> bool:
    """The archetype's promise_prob, on SOCIAL_CONVO (lesson 1: forceable). A breadcrumber's is 0."""
    arch = behaviour.archetype(population.profile(state, pid).archetype)
    return behaviour.person_rng(state, SOCIAL_CONVO, pid).random() < float(arch.promise_prob)


def _ghost_protected(state: GameState, pid: str) -> bool:
    """No ghost is drawn while they hold an open promise to the player (spec §4.6, MINOR 11)."""
    return bool(promises.open_by(state, pid, by="person"))


def _episode_start(state: GameState, pid: str, at: float) -> str:
    """The draws per EPISODE START (§4.6): ghost (never while they hold a promise), else reply, else left on read."""
    rng = behaviour.person_rng(state, SOCIAL_CONVO, pid)      # inside the read event's handler: rule 3
    if not _ghost_protected(state, pid) and rng.random() < _ghost_factor(state, pid):
        apply_effect(state, {"type": "social_person", "pid": pid, "set": {"ghosted": True}})
        # Only the reply family (pre-flight F7). A player's `promise_close` (keyed by this pid), a
        # `plan_lapse`, a `life` or an `offer_number` event stays queued; open promises and plans are
        # voided through their OWN handlers (T4, T12), never by dropping their events here.
        events.cancel(state, pid, events.REPLY_FAMILY)
        return "ghosted"
    if rng.random() >= _reply_factor(state, pid):
        return "left_on_read"
    return "reply"


# -- the chain (§4.3): a send, a read, a decision ---------------------------------------------------


@contextlib.contextmanager
def marking(ids: Iterable[str]) -> Iterator[None]:
    """The due message ids a voicing pass holds, visible to the action run inside the block."""
    token = MARKED.set(frozenset(str(i) for i in ids))
    try:
        yield
    finally:
        MARKED.reset(token)


def _note_player_chars(state: GameState, pid: str, thread_id: str, at: float) -> None:
    """Inside the send's handler: the player's message's length joins the open episode's last few."""
    ep = episode(state, pid)
    text = _last_player_text(state, thread_id)
    if ep is None or text is None:
        return
    keep = max(1, int(_talk().get("player_chars_kept", 3)))
    ep["player_chars"] = [*(ep.get("player_chars") or []), len(text)][-keep:]


def read_hold_until(state: GameState, pid: str, at: float) -> float:
    """After they left the player on read at `at`: their next read waits for their next boundary or
    `left_on_read_quiet_minutes`, whichever comes first (review M1, the controller's ruling)."""
    quiet = float(_data().get("left_on_read_quiet_minutes", 60)) / 60.0
    left = boundary_minutes(state, pid, at)
    return at + min(quiet, left / 60.0) if left is not None else at + quiet


def on_player_send(state: GameState, pid: str, thread_id: str, at: float, *, note: bool = True) -> None:
    """
    A player's message (called from `social_message`'s handler). Either:
    - a reply is already due and UNMARKED: it is re-decided in place, so a burst gets one reply (§4.3);
    - one is due and MARKED: nothing now -- the pass's commit sees the player spoke since its
      snapshot and queues the next decision then (`after_commit`, I6);
    - an episode is open and they are not away: their read lands NOW (`at`), so the reply is due
      at the same minute -- the send's own `advance_time` walks it (§4.3);
    - otherwise: the read is queued at `next_available` (they read it when they can, §3.5 item 3).
    """
    if note:
        _note_player_chars(state, pid, thread_id, at)
    due = _due_reply(state, thread_id)
    if due is not None:
        if due["id"] not in MARKED.get():
            apply_effect(state, {"type": "social_episode", "op": "redecide", "pid": pid,
                                 "thread_id": thread_id, "message_id": due["id"], "at": at})
        return
    person = state.social["people"].get(pid) or {}
    if person.get("ghosted") or apps.gone(state, pid) or _read_pending(state, pid, thread_id):
        return
    ep = episode(state, pid)
    away_until = (ep or {}).get("away_until")
    if ep is not None and ep["end"] != "signed_off":
        events.push(state, at, pid, "read", thread_id=thread_id, episode=ep["id"])
    elif ep is not None and int(ep.get("after_left", 0)) > 0:
        events.push(state, at, pid, "read", thread_id=thread_id, episode=ep["id"], one_more=True)
    else:
        hold = float(person.get("read_hold_until") or at)       # left on read: no re-roll until it ends (M1)
        when = next_available(state, pid, max(at, float(away_until or at), hold))
        events.push(state, when, pid, "read", thread_id=thread_id)


@events.handles("read")
def _on_read(state: GameState, event: dict[str, Any]) -> dict[str, Any]:
    """
    They read the player's messages (inside `social_event`'s handler, rule 3): the read marks,
    then -- with no episode going -- the episode-start draws (§4.6), then the answer to a pending
    ask or the reply's decision, due at the read's own minute (§4.3).

    A conversation they signed off from is closed here once they are back (`away_until`), so the
    next one starts fresh, with its own draws. A player's pending ask is answered even when the
    reply draw says "left on read" (v0.22.0 answered an ask at every read; only a ghost skips it).
    """
    pid, thread_id, at = str(event["pid"]), str(event["thread_id"]), float(event["at"])
    person = state.social["people"].setdefault(pid, {})
    if not messaging.is_open(messaging.thread(state, thread_id)) or apps.gone(state, pid) or person.get("ghosted"):
        return {"ok": False, "why": "closed"}
    relationships.settle_left_on_read(state, pid, at)
    apply_effect(state, {"type": "social_read", "thread_id": thread_id, "reader": pid, "at": at})
    ep = episode(state, pid)
    if (ep is not None and ep["end"] == "signed_off" and not event.get("one_more")
            and at >= float(ep.get("away_until") or at)):
        apply_effect(state, {"type": "social_episode", "op": "close", "pid": pid, "at": at})
        ep = None
    asked = relationships.pending_asks(state, pid)
    if ep is None:
        start = _episode_start(state, pid, at)        # the per-episode draws (§4.6)
        if start == "left_on_read" and not asked:
            person["read_hold_until"] = read_hold_until(state, pid, at)   # inside the read handler: rule 3
        if start == "ghosted" or (start == "left_on_read" and not asked):
            return {"ok": True, start: True}
        apply_effect(state, {"type": "social_episode", "op": "open", "pid": pid, "thread_id": thread_id,
                             "at": at, "kind": "chat"})
    if asked:
        where = str(asked[0].get("thread_id") or thread_id)    # answered in the thread it was asked in
        where = where if messaging.is_open(messaging.thread(state, where)) else thread_id
        return messaging.answer_ask(state, pid, asked[0], where, at)
    decision = decide(state, pid, thread_id, at)
    messaging.queue_due(state, pid, thread_id, decision, at)
    if event.get("one_more"):
        apply_effect(state, {"type": "social_episode", "op": "one_more", "pid": pid, "at": at})
    return {"ok": True, "mode": decision.mode, "end": decision.end}


# -- the decision (§4.4, §4.5) ------------------------------------------------------------------------


def _pressure(state: GameState, pid: str, ep: dict[str, Any], at: float) -> tuple[float, str]:
    talk = _talk()
    terms = {"length": ep["exchanges"] / max(1, ep["target"]), "energy": 1.0 - ep["energy"] / 100.0}
    left = boundary_minutes(state, pid, at)
    window = float(talk.get("boundary_minutes", 20))
    if left is not None and left < window:
        terms["boundary"] = 1.0 + (window - left) / window          # steep: past sign_off_at at once
    reason = max(terms, key=terms.get)
    return terms[reason], reason


def _reason(state: GameState, pid: str, term: str, at: float) -> tuple[str, str]:
    """(the `reasons:` key, the engine's words) for what ends the talk: `term`, or for a schedule
    boundary the status it steps down to."""
    words = _data().get("reasons") or {}
    if term == "player":                                # a life event of the player's that is theirs to give (T17)
        from engine.social import life   # lazily: life imports this module

        given = life.sign_off_reason(state)
        if given:
            return term, given
    if term != "boundary":
        return term, str(words.get(term, ""))
    left = boundary_minutes(state, pid, at) or 0.0
    then = _status(state, pid, at + left / 60.0 + 0.01)
    now = _status(state, pid, at)
    if then == "work":
        if now == "free" and 11 <= at % 24 <= 15:
            return "lunch_over", str(words.get("lunch_over", ""))
        return "work", str(words.get("work", "")).format(hour=int((at + left / 60.0) % 24))
    # A boundary is only ever a step DOWN in availability (`boundary_minutes`): to `out`, or to sleep
    # (their first sleep hour, for a `sometimes`, still reads `asleep`); anything else is the morning ahead.
    key = {"asleep": "asleep", "out": "out"}.get(then, "early")
    return key, str(words.get(key, ""))


def _reason_words(state: GameState, pid: str, term: str, at: float) -> str:
    return _reason(state, pid, term, at)[1]


def _mode(state: GameState, pid: str, ep: dict[str, Any], cap: str, end: str) -> str:
    modes = _data().get("modes") or {}
    if cap in ("quick", "glance") or end == "sign_off" or ep["exchanges"] < int(modes.get("chatting_after", 3)):
        return "quick"
    chars = ep.get("player_chars") or [0]
    deep = (ep["energy"] > float(modes.get("deep_energy", 40))
            and growth.depth(state, pid) >= 2
            and sum(chars) / len(chars) > float(modes.get("deep_player_chars", 90))
            and _touched_at_depth(state, pid, ep))
    return "deep" if deep else "chatting"


def decide(state: GameState, pid: str, thread_id: str, at: float, *, situation: str = "reply",
           exchange: bool = True) -> Decision:
    """
    The reply's shape, from the episode, their schedule and depth (inside a social handler).
    Each decision is one exchange (its energy, its openness gain), but for a burst re-decided in
    place (`exchange=False`): one reply answers the whole burst, so it is counted once.
    """
    ep = episode(state, pid)
    if ep is None:                                      # no conversation going (an arc's, a game's): plain
        return Decision(situation=situation, kind="text", max_bubbles=2, followup_id=_followup_id(state, pid, at))
    if exchange:
        apply_effect(state, {"type": "social_episode", "op": "exchange", "pid": pid, "at": at})
        ep = episode(state, pid) or ep
    cap = available(state, pid, at).cap
    pressure, term = _pressure(state, pid, ep, at)
    talk = _talk()
    already_gone = ep["end"] == "signed_off"
    if already_gone:                                    # one more thing after their sign-off: still going
        end, term = "sign_off", ""
    elif ep.get("end_by") == "player":                  # the player said "talk later": they say goodbye
        end, term = "sign_off", "player"
    elif cap == "glance" and ep["exchanges"] >= 2:
        end, term = "sign_off", "glance"
    elif pressure >= float(talk.get("sign_off_at", 1.0)):
        end = "sign_off"
    elif pressure >= float(talk.get("winding_at", 0.8)):
        end = "winding"
    else:
        end = "none"
    mode = _mode(state, pid, ep, cap, end)
    caps = ((_data().get("modes") or {}).get("caps") or {}).get(mode) or {"bubbles": [1, 2]}
    burst = messaging.player_burst(state, thread_id)
    asked = promises.accept_asked(state, pid, at)       # a promise the player stated, with no model (§5.2)
    promise_id = str(ep.get("promise_id") or "") or str((asked or {}).get("id") or "")
    reason_key = ""
    if already_gone:
        reason = str(ep.get("end_reason") or "")
    elif end != "none":
        reason_key, reason = _reason(state, pid, term, at)
    else:
        reason = ""
    if end == "none" and situation == "reply":
        broken = promises.broken_reason(state, pid)     # carried to the voice once (§5.3)
        if broken:
            reason = broken
            apply_effect(state, {"type": "social_person", "pid": pid, "set": {"broken_promise": None}})
        else:
            from engine.social import life   # lazily: life imports this module

            news = life.take_news(state, pid)           # what happened in their life, told once (§11.3, T17)
            if news:
                situation, reason = "news", f"this happened to you: {news}"
    if end == "sign_off" and not already_gone:
        if not promise_id:
            promise_id = _maybe_promise(state, pid, thread_id, at, cap)   # recorded BEFORE voicing (§5.2)
        apply_effect(state, {"type": "social_episode", "op": "end", "pid": pid, "at": at,
                             "end": "signed_off", "reason": reason, "reason_key": reason_key,
                             "promise_id": promise_id, "away": term})
    elif end == "winding":
        apply_effect(state, {"type": "social_episode", "op": "end", "pid": pid, "at": at,
                             "end": "winding", "reason": reason, "reason_key": reason_key})
    if exchange:
        growth.gain(state, pid, "exchange", mode=mode)
    high = int(caps["bubbles"][1])
    return Decision(situation=situation, kind="text", mode=mode, max_bubbles=high,
                    min_bubbles=min(high, max(int(caps["bubbles"][0]), 2 if burst >= 3 else 1)),
                    end=end, reason=reason, promise_id=promise_id, followup_id=_followup_id(state, pid, at))


def _followup_id(state: GameState, pid: str, at: float) -> str:
    """The person's oldest follow-up due now (spec §7.3), carried by their next reply; closed when that
    reply is committed (`social_voiced`)."""
    from engine.social import memory   # lazily: memory reads agreement, which reads population

    due = memory.followup_due(state, pid, at)
    return str(due["id"]) if due else ""


def sign_off_window(state: GameState, pid: str, at: float) -> str:
    """The window their own sign-off promises: the first of `promises.SIGN_OFF_WINDOWS` their schedule
    has within `max_ahead_hours`, else `later`. Draws nothing."""
    reach = float(social.data("promises").get("max_ahead_hours", 48))
    for window in promises.SIGN_OFF_WINDOWS:
        span = windows.resolve(state, pid, window, at)
        if span is not None and span[0] - at <= reach:
            return window
    return "later"


def _maybe_promise(state: GameState, pid: str, thread_id: str, at: float, cap: str) -> str:
    """Their sign-off carries a promise when the archetype's draw says so (§5.2 route 2): a glance at
    work promises lunch, any other sign-off their `sign_off_window`. The promise's id, or ""."""
    if not _promise_drawn(state, pid):
        return ""
    window = "lunch" if cap == "glance" else sign_off_window(state, pid, at)
    row = promises.make(state, pid, by="person", window=window, at=at)
    return row["id"] if row else ""


def after_commit(state: GameState, pid: str, thread_id: str, through_id: str, at: float) -> bool:
    """
    The voicing pass committed a reply whose snapshot read the thread up to message `through_id`
    (CALLER HOLDS the turn lock, inside the commit's transaction). If the player spoke after it,
    the NEXT decision is made now, at the commit's minute, as a due message -- never discarded (I6).
    Returns True when one was queued (the pass then sets `rerun`). With the conversation over (lapsed,
    or signed off with no "one more thing" left) their read is queued instead, as for any cold message.
    """
    if not through_id:
        return False
    t = messaging.thread(state, thread_id) or {}
    after = False
    for m in t.get("messages") or []:
        if after and m.get("from") == "player" and messaging.shown(m):
            if _due_reply(state, thread_id) is not None:
                return False
            ep = episode(state, pid)
            if ep is None or (ep["end"] == "signed_off" and int(ep.get("after_left", 0)) <= 0):
                # The conversation is over (it lapsed, or they signed off with nothing more to say):
                # they read what was said since when they can, as any cold message (never dropped).
                on_player_send(state, pid, thread_id, at, note=False)   # its length was noted at its send (M4)
                return False
            decision = decide(state, pid, thread_id, at)
            messaging.new_message(state, thread_id, pid, "text", at=at, voiced=False,
                                  decision=dataclasses.asdict(decision))
            if ep["end"] == "signed_off":
                apply_effect(state, {"type": "social_episode", "op": "one_more", "pid": pid, "at": at})
            return True
        if m.get("id") == through_id:
            after = True
    return False


def on_their_message(state: GameState, pid: str, thread_id: str, at: float) -> None:
    """An opener or an initiation of theirs landed (inside its event's handler): it starts a conversation."""
    if episode(state, pid) is None:
        apply_effect(state, {"type": "social_episode", "op": "open", "pid": pid, "thread_id": thread_id,
                             "at": at, "kind": "chat"})


def initiation_skip(state: GameState, pid: str, situation: str, at: float) -> str:
    """Why a window initiation due now does not land ("" when it does): a conversation already going,
    the player wrote to them a moment ago, or a situation retired as bare (spec §4.7, §13.1)."""
    if episode(state, pid) is not None:
        return "in a conversation"
    last = ((state.social.get("people") or {}).get(pid) or {}).get("last_player_at")
    skip = float((_data().get("initiation") or {}).get("skip_if_talked_minutes", 120)) / 60.0
    if last is not None and at - float(last) < skip:
        return "talked a moment ago"
    if situation in RETIRED_SITUATIONS:
        return "a retired situation"
    return ""


# -- the one writer (rule 3) -------------------------------------------------------------------------


def _late(at: float) -> bool:
    hour = at % 24
    return hour >= 21 or hour < 4


def _open(state: GameState, pid: str, person: dict[str, Any], effect: dict[str, Any], at: float) -> dict[str, Any]:
    if episode(state, pid) is not None:
        return {"type": "social_episode", "ok": False, "text": f"{pid} already has an episode open"}
    kind = str(effect.get("kind") or "chat")
    if kind not in ("chat", "scene"):
        return {"type": "social_episode", "ok": False, "text": f"{kind!r} is no episode kind"}
    talk = _talk()
    rng = behaviour.person_rng(state, SOCIAL_CONVO, pid)
    mult = float((talk.get("per_depth") or [1.0] * 5)[growth.depth(state, pid)])
    if _late(at):
        late = talk.get("late_mult") or {}
        night_owl = attrs.of(state, pid)["habits"]["late_night"] == "night_owl"
        mult *= float(late.get("night_owl" if night_owl else "default", 1.0))
    if _status(state, pid, at) == "work":
        mult *= float(talk.get("work_mult", 1.0))
    target = max(1, int(round(_target_draw(state, pid, rng) * mult)))
    counters = state.social.setdefault("counters", {})
    counters["episode"] = int(counters.get("episode", 0)) + 1
    row = {"id": f"e{counters['episode']}", "kind": kind, "thread_id": str(effect.get("thread_id") or ""),
           "location": str(effect.get("location") or ""), "started_at": at, "last_at": at, "exchanges": 0,
           "target": target, "energy": 100.0, "mode": "quick", "end": "none", "end_reason": "",
           "promise_id": "", "topics": [], "warmth_at_open": float(person.get("warmth", 0)),
           "after_left": 0, "away_until": None, "player_chars": []}
    asked = person.get("asks_this_episode")
    if isinstance(asked, dict) and asked.get("key") == cap_key(state, pid):
        asked["key"] = row["id"]        # the ask that brought this conversation counts in it (T5 review I2)
    person["episode"] = row
    relationships.touch(person)
    if kind == "chat":
        events.push(state, at + _gap_hours(), pid, "episode_lapse", episode=row["id"])
    return {"type": "social_episode", "ok": True, "text": f"{pid}: episode {row['id']} opened", "episode": row["id"]}


def _exchange(state: GameState, pid: str, person: dict[str, Any], ep: dict[str, Any], at: float) -> dict[str, Any]:
    talk = _talk()
    ep["exchanges"] = int(ep["exchanges"]) + 1
    ep["last_at"] = at
    cost = float(talk.get("energy_per_exchange", 6))
    text = _last_player_text(state, str(ep.get("thread_id") or "")) or ""
    if len(text) < float(talk.get("short_player_chars", 25)):
        cost += float(talk.get("short_extra_energy", 4))
    named = _named_topics(state, pid, text)
    back = float(talk.get("topic_energy_back", 3)) if named else 0.0
    ep["topics"] = [*ep.get("topics", []), *[t for t in named if t not in ep.get("topics", [])]]
    ep["energy"] = max(0.0, min(100.0, float(ep["energy"]) - cost + back))
    relationships.touch(person)
    if ep.get("kind") == "chat":
        events.cancel(state, pid, {"episode_lapse"})
        events.push(state, at + _gap_hours(), pid, "episode_lapse", episode=ep["id"])
    return {"type": "social_episode", "ok": True, "text": f"{pid}: exchange {ep['exchanges']}"}


def _end(state: GameState, pid: str, person: dict[str, Any], ep: dict[str, Any], effect: dict[str, Any],
         at: float) -> dict[str, Any]:
    end = str(effect.get("end") or "")
    if end not in ("winding", "signed_off"):
        return {"type": "social_episode", "ok": False, "text": f"{end!r} is no episode end"}
    ep["end"] = end
    ep["end_reason"] = str(effect.get("reason") or "")
    ep["end_key"] = str(effect.get("reason_key") or "")       # the `reasons:` key: the recap's words (T6)
    if effect.get("promise_id"):
        ep["promise_id"] = str(effect["promise_id"])
    if effect.get("by") == "player":
        ep["end_by"] = "player"                         # the player's "talk later": their reply signs off
    if end == "signed_off":
        low, high = _talk().get("after_sign_off") or [0, 0]
        away = _away_hours(state, pid, str(effect.get("away") or ""), at)
        ep["away_until"] = next_available(state, pid, at + away)
        ep["after_left"] = behaviour.person_rng(state, SOCIAL_CONVO, pid).randint(int(low), int(high))
    relationships.touch(person)
    return {"type": "social_episode", "ok": True, "text": f"{pid}: {end}"}


def _away_hours(state: GameState, pid: str, key: str, at: float) -> float:
    """How long they are gone after a sign-off, by what ended it (`talk.away_after_sign_off`, T3 review
    M6), so the reason they gave matches how long they are away. A schedule boundary's sign-off is gone
    at least until the boundary itself; an unknown key (a hand-applied end) reads as `boundary`."""
    table = _talk().get("away_after_sign_off") or {}
    key = key if key in SIGN_OFF_KEYS else "boundary"
    hours = float(table.get(key, 15)) / 60.0
    if key == "boundary":
        left = boundary_minutes(state, pid, at)
        if left is not None:
            hours = max(hours, left / 60.0)
    return hours


def _close(state: GameState, pid: str, person: dict[str, Any], ep: dict[str, Any], effect: dict[str, Any],
           at: float) -> dict[str, Any]:
    end = str(effect.get("end") or ("signed_off" if ep.get("end") == "signed_off" else "lapsed"))
    signed_off = ep.get("end") == "signed_off" or end == "signed_off"
    from engine.social import memory   # lazily: memory reads agreement, which reads population

    rows = person.setdefault("recap_due", [])
    # Only what a recap reads (memory.DUE_KEYS); the recap job consumes the row (T6).
    rows.append({k: v for k, v in {**ep, "end": end, "closed_at": at}.items() if k in memory.DUE_KEYS})
    limit = max(1, int(social.setting("recap_due_max", 20)))
    if len(rows) > limit:
        del rows[:len(rows) - limit]
    person["episodes_done"] = int(person.get("episodes_done", 0)) + 1
    person["episode"] = None
    from engine.social import plans   # lazily: plans imports this module

    plans.on_episode_close(state, pid)             # a `soon` plan that has waited long enough lapses (§9.3, F30)
    if ep.get("kind") == "chat":
        person.pop("recorded", None)                # what a scene's closer recorded holds through the next chat (T13)
    person["last_episode"] = str(ep["id"])          # keys the between-episodes cap (`cap_key`, F36)
    relationships.touch(person)
    events.cancel(state, pid, {"episode_lapse"})
    if signed_off and float(person.get("warmth", 0)) > float(ep.get("warmth_at_open", 0)):
        growth.gain(state, pid, "good_end")           # a sign-off on good terms (§6.3)
    apply_effect(state, {"type": "social_growth", "op": "tick", "pid": pid})
    from engine.social import media   # lazily: media imports messaging, which this module imports

    media.after_episode(state, pid, at)               # budgets refilled per episode, one unasked maybe (§6.4)
    return {"type": "social_episode", "ok": True, "text": f"{pid}: episode {ep['id']} closed ({end})"}


def _redecide(state: GameState, pid: str, effect: dict[str, Any], at: float) -> dict[str, Any]:
    thread_id, message_id = str(effect.get("thread_id") or ""), str(effect.get("message_id") or "")
    t = messaging.thread(state, thread_id) or {}
    message = next((m for m in t.get("messages") or [] if m.get("id") == message_id), None)
    if message is None or message.get("voiced") is not False:
        return {"type": "social_episode", "ok": False, "text": f"{message_id} is no due message"}
    old = decision_from_row(message.get("decision"), where=f"redecide:{message_id}")
    shape = decide(state, pid, thread_id, at, situation=old.situation, exchange=False)
    message["decision"] = dataclasses.asdict(dataclasses.replace(
        old, mode=shape.mode, max_bubbles=shape.max_bubbles, min_bubbles=shape.min_bubbles, end=shape.end,
        reason=shape.reason or (old.reason if old.situation == "news" else ""),
        promise_id=shape.promise_id or old.promise_id,
        followup_id=shape.followup_id or old.followup_id))
    return {"type": "social_episode", "ok": True, "text": f"{message_id} re-decided"}


@effect_kind("social_episode")
@recorded
def _e_episode(state: GameState, effect: dict[str, Any], ctx: EffectContext) -> dict[str, Any]:
    """
    Engine-only: one person's conversation episode (spec §4.1). Ops: ``open`` (the §4.1 row, its
    target drawn), ``exchange`` (one more: energy spent, topics named), ``end`` (``winding`` or
    ``signed_off``, with the engine's reason), ``one_more`` (a thing answered after the sign-off),
    ``close`` (the row to ``recap_due``, the growth tick), ``redecide`` (a burst's due reply, in place).
    """
    if not state.social:
        return {"type": "social_episode", "ok": False, "text": "no social slice"}
    pid = str(effect.get("pid") or "")
    op = effect.get("op")
    if op not in EPISODE_OPS:
        return {"type": "social_episode", "ok": False, "text": f"unknown op {op!r}"}
    person = (state.social.get("people") or {}).get(pid)
    if not isinstance(person, dict):
        return {"type": "social_episode", "ok": False, "text": f"{pid!r} is not someone the player knows"}
    at = float(effect["at"]) if effect.get("at") is not None else state.world_clock_hours
    if op == "open":
        return _open(state, pid, person, effect, at)
    if op == "redecide":
        return _redecide(state, pid, effect, at)
    ep = episode(state, pid)
    if ep is None:
        return {"type": "social_episode", "ok": False, "text": f"{pid} has no episode open"}
    if op == "exchange":
        return _exchange(state, pid, person, ep, at)
    if op == "end":
        return _end(state, pid, person, ep, effect, at)
    if op == "one_more":
        ep["after_left"] = max(0, int(ep.get("after_left", 0)) - 1)
        relationships.touch(person)
        return {"type": "social_episode", "ok": True, "text": f"{pid}: one more"}
    return _close(state, pid, person, ep, effect, at)


@events.handles("episode_lapse")
def _on_lapse(state: GameState, event: dict[str, Any]) -> dict[str, Any]:
    """No message either way for the gap: the chat episode closes (a scene episode never lapses, m9)."""
    pid, at = str(event["pid"]), float(event["at"])
    ep = episode(state, pid)
    if ep is None or ep.get("kind") != "chat" or str(event.get("episode") or ep["id"]) != ep["id"]:
        return {"ok": False, "why": "no such episode"}
    if float(ep["last_at"]) + _gap_hours() > at + 1e-9:
        return {"ok": False, "why": "still going"}
    apply_effect(state, {"type": "social_episode", "op": "close", "pid": pid, "at": at})
    return {"ok": True, "closed": ep["id"]}


# -- their number offer (spec §15.2) -----------------------------------------------------------------


def _offer_drawn(state: GameState, pid: str) -> bool:
    """The archetype's `offer_number_prob`, one draw on SOCIAL_CONVO (split out to be forced: lesson 1)."""
    arch = behaviour.archetype(population.profile(state, pid).archetype)
    return behaviour.person_rng(state, SOCIAL_CONVO, pid).random() < float(arch.offer_number_prob)


def offer_skip(state: GameState, pid: str) -> str:
    """Why their number offer is moot now ("" when it stands): gone, past the number already, or one
    of theirs already waiting for the player's answer."""
    person = ((state.social or {}).get("people") or {}).get(pid) or {}
    stage = person.get("stage")
    if apps.gone(state, pid) or person.get("ghosted") or stage_rank(stage) < 0:
        return "gone"
    if stage_rank(stage) >= stage_rank("numbers"):
        return "has the number"
    if relationships.pending_offers(state, pid, "number"):
        return "already offered"
    ok, why = growth.willing(state, pid, "number")
    return "" if ok else why


@events.handles("offer_number")
def _on_offer_number(state: GameState, event: dict[str, Any]) -> dict[str, Any]:
    """
    Reaching `everyday` (inside `social_event`'s handler, rule 3): their `offer_number_prob` drawn
    (`_offer_drawn`); on yes a request of theirs (`what: number`, answered by the player through v0.22's
    number path, `relationships.answer`) and a due `offer_number` message in their thread at this minute.
    """
    pid, at = str(event["pid"]), float(event["at"])
    skip = offer_skip(state, pid)
    if skip:
        return {"ok": False, "why": skip}
    if not _offer_drawn(state, pid):
        return {"ok": True, "offered": False}
    tid = messaging.thread_for(state, pid) or ""
    if not messaging.is_open(messaging.thread(state, tid)):
        return {"ok": False, "why": "closed"}
    made = apply_effect(state, {"type": "social_request", "op": "create", "pid": pid, "from": "them",
                                "what": "number", "thread_id": tid, "at": at})
    messaging.queue_due(state, pid, tid, Decision(situation="offer_number"), at)
    return {"ok": True, "offered": True, "request_id": made["request"]["id"]}


# -- initiations by window (§4.7) -------------------------------------------------------------------


def _daily_initiations(state: GameState) -> None:
    """
    The `daily` step: each live person's initiation rows, one a day at most. A row's window is
    resolved against their schedule; its chance is `prob[depth]`, its minute drawn inside the
    window (both on SOCIAL_CONVO). Nobody is nudged while a conversation with them is going.
    """
    day_at = events.daily_at(state)
    queued = {e["pid"] for e in state.social.get("queue", []) if e["kind"] == "initiate"}
    for pid in messaging.live_people(state):
        if pid in queued or episode(state, pid) is not None:
            continue
        person = population.profile(state, pid)
        state.social["people"].setdefault(pid, {})
        depth = growth.depth(state, pid)
        for row in behaviour.archetype(person.archetype).initiations:
            span = windows.resolve(state, pid, str(row["window"]), day_at)
            if span is None or span[0] >= day_at + 24.0:
                continue                                  # no such window in this day of theirs
            if not messaging.when_holds(state, pid, row.get("when") or {}, span[0]):
                continue
            rng = behaviour.person_rng(state, SOCIAL_CONVO, pid)
            if rng.random() >= float(list(row["prob"])[depth]):
                continue
            at = span[0] + rng.random() * (span[1] - span[0])
            tid = messaging.initiation_thread(state, pid)
            if tid is None:
                break
            decision = Decision(situation=str(row.get("instruction") or "window_message"), kind=str(row["kind"]))
            messaging.queue_due(state, pid, tid, decision, at, initiation=row["id"])
            break


if _daily_initiations not in events.daily_hooks:
    events.daily_hooks.append(_daily_initiations)
