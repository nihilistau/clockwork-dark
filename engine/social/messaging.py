"""
Messaging and pacing (v0.22.0 spec §9): the threads across the apps (the
dating apps' chats, Texts, Natter), the player's messages, and when the
people answer -- each on their own clock, decided by the ENGINE from the seed
and the player's actions (rule 1). No model runs here: a message that needs
words lands as a DUE message (`voiced: False`, no bubbles) carrying the
engine's `Decision`, which the voicing pass (T13/T14) words later.

**A send** (`send`) appends the player's message through `social_message`,
whose handler schedules a `read` for the person (`schedule_reply`):
`read_minutes` from now, or their waking time if they are asleep then. A
burst of messages in a thread gets ONE read (`pending_read`, keyed by
thread: a send in another thread gets its own), so one decision. Then the
send's `cost_minutes` pass through `clock.advance_time` (rule 2).

**The read** (`_on_read`) writes `read_at` on the player's messages on an
app with `receipts: true`, then decides, in this order: a ghost
(`ghost_per_exchange` x (1 - interest/100) x the stage's factor; a ghost
sets the hidden `ghosted` and cancels their queue), the player's pending
number ask if there is one (`_answer_number`), else a reply (`reply_prob` x
the interest and burst factors) or left on read. A reply is a due message
`reply_minutes` x their status's multiplier / (interest/50) after the read.

**Openers** (spec §8.3): every match queues an `initiate` with situation
`opener` at a delay from their pace; when it falls due, `opener_prob` is
drawn. The player writing first cancels it. **Initiations** (§9.3): each
`daily`, every live person's archetype `initiations` are tried (one a day at
most), at one of their `at_hours` (or any hour) that falls in their free
time, while the row's `when` holds -- checked when queued and again when due.
**Double texts**: when a message of theirs lands, `double_text.prob` is
drawn; a `double_text` falls due `after_hours` later, unless the player has
written since, capped at `max_in_row` since the player's last message.

**Receipts** (§9.4): opening a thread (`open_thread`) writes the player's
read time on the person's (voiced) messages; on a receipts app with the
player's receipts on, the person sees it (`seen_by_them_at`), and a last
message of theirs read and not answered starts `left_on_read_since`, which
costs interest (relationships.settle_left_on_read) at their next event, or
when the player writes. Receipts off hides both directions in the payload.

**Asks** (§9.5, §10.6): `ask {what: number}` at stage `talking` (or `what:
exclusive` at `dating`) is relationships.ask: a request and a request
message; the person decides at their next read (`relationships.ask_decision`:
the stage's gate, then a draw, `_number_accepted` for a number): yes moves
the stage through `social_stage` and, for a number, opens the Texts and
Natter threads; either way the answer is a due message (`answer_request`, a
`decline` when no). Every message between the two counts toward their
familiarity (`relationships.note_message`: exchanges, contact days).

Every number is behaviours.yaml's (the archetypes and `pacing:`; rule 10).
Every write is a `social_message` / `social_read` effect or happens inside a
`social_*` handler (events.py: an event handler IS the effect; rule 3).
"""

from __future__ import annotations

import dataclasses
from typing import Any, Optional

from engine import social
from engine.game import clock
from engine.game.effects import EffectContext, apply_effect, effect_kind
from engine.social.kinds import recorded
from engine.game.intents import IntentVerb
from engine.game.rng import SOCIAL_BEHAVIOUR, SOCIAL_PACE, stable_rng
from engine.game.state import GameState
from engine.social import apps, behaviour, events, matching, population, relationships
from engine.social.intents import ArgSpec, phone_verb
from engine.social.kinds import MEDIA_KINDS, Decision, stage_rank
from engine.social.payload import section
from engine.social.turn import cost_hours

#: What a player's message may be (spec §7.1); each app allows its `capabilities`.
SEND_KINDS: tuple[str, ...] = ("text", "photo", "voice", "video")
#: What the player can send: text, photos and videos (T19) and voice notes
#: (T21: a transcript, its audio never kept, spec §13.7).
SENDABLE: tuple[str, ...] = ("text", "photo", "voice", "video")
#: The longest `audio_transcript` the catalogue takes (characters); what is kept is cut to
#: `media.yaml` `voice.max_seconds` of words (`media.voice_transcript`).
AUDIO_TRANSCRIPT_MAX = 600
#: How a refusal names a kind ("Texts can't send voice notes").
NOUNS: tuple[tuple[str, str], ...] = (("text", "texts"), ("photo", "photos"), ("voice", "voice notes"),
                                      ("video", "videos"))
#: What `ask` may ask for: their number and to be exclusive (T9), a photo,
#: a voice note or a video (T19, decided by engine/social/media.py), and a
#: meet-up (T24, `MEET_ASK`). A game is started with `game_invite` (engine/social/games/, T22).
#: A meet-up asked for: the engine picks the venue and the slot (engine/social/meets.py `REQUEST`, T24).
MEET_ASK = "meet"
ASKS: tuple[str, ...] = tuple(what for what, _stage in relationships.ASK_STAGE) + MEDIA_KINDS + (MEET_ASK,)
#: How an ask names one of a kind ("Ask Kai for a voice note").
ONE_OF: tuple[tuple[str, str], ...] = (("photo", "a photo"), ("voice", "a voice note"), ("video", "a video"))
#: A dating app's `first_message` (spec §6): either side, or only the player.
FIRST_MESSAGE: tuple[str, ...] = ("either", "player")
#: The schedule statuses an initiation may be written in ("inside their free hours", §9.3).
FREE: tuple[str, ...] = ("free", "out")
#: The queue kinds whose handler lands a due message.
DUE_KINDS: tuple[str, ...] = ("reply", "initiate", "double_text")
#: A message row's kinds (the plan's shared interfaces).
MESSAGE_KINDS: tuple[str, ...] = ("text", "voice", "photo", "video", "system", "request", "recap")
#: How a notification reads before a due message is voiced (spec §11.1).
NEW_MESSAGE = "New message"
#: A match's notification (the row carries the name; T30 follow-up).
NEW_MATCH = "New match"

#: A due message RETIRED unvoiced (`voiced: "withdrawn"`, no words): its person left -- unmatched,
#: blocked or ended -- before it was voiced (v0.22.0 T14, `voicer`). Never voiced, never shown.
WITHDRAWN = "withdrawn"


def shown(message: dict[str, Any]) -> bool:
    """Whether a message is one the player can see (every one but a withdrawn one)."""
    return message.get("voiced") != WITHDRAWN
#: A notification or a thread row's preview of a voiced message, at most.
PREVIEW_CHARS = 80


def _no(reason: str) -> dict[str, Any]:
    return {"ok": False, "error": reason}


def _name(state: GameState, pid: str) -> str:
    return matching._name(state, pid)


def _noun(kind: str) -> str:
    return dict(NOUNS).get(kind, kind)


# -- pacing (behaviours.yaml `pacing:`, rule 10) -----------------------------------


def _pacing() -> dict[str, Any]:
    """behaviours.yaml's `pacing:` block, checked whole when the story's data loads (social._check_loaded)."""
    block = social.data("behaviours").get("pacing")
    if not isinstance(block, dict):
        raise ValueError("social: behaviours.yaml: pacing: required (spec §9.2)")
    return block


def _interest_factor(interest: float) -> float:
    low, high = (float(v) for v in _pacing()["interest_factor"])
    return low + (high - low) * max(0.0, min(100.0, float(interest))) / 100.0


def _burst_factor(burst: int) -> float:
    table = list(_pacing()["burst_factor"])
    return float(table[min(max(int(burst), 1), len(table)) - 1])


def _status_mult(person: population.Person, at: float) -> float:
    return float((_pacing().get("status_mult") or {}).get(behaviour.status_at(person, at), 1.0))


def _stage_factor(stage: Optional[str]) -> float:
    """The ghost chance's stage term (split out so a test can pin it, F16)."""
    return float((_pacing().get("stage_factor") or {}).get(str(stage or "matched"), 1.0))


# -- threads ----------------------------------------------------------------------------


def _threads(state: GameState) -> dict[str, Any]:
    return state.social.get("threads") or {}


def thread(state: GameState, thread_id: str) -> Optional[dict[str, Any]]:
    return _threads(state).get(thread_id)


def _person(state: GameState, pid: str) -> dict[str, Any]:
    """READ ONLY: a person's dynamic slice, {} when there is none."""
    return (state.social.get("people") or {}).get(pid) or {}


def _open(t: Optional[dict[str, Any]]) -> bool:
    """A thread that can be written in: it exists and nothing closed it (not even an expiry)."""
    return t is not None and not t.get("closed")


def _new_thread(thread_id: str, app: str, pid: str) -> dict[str, Any]:
    return {"thread_id": thread_id, "app": app, "pid": pid, "messages": [], "summary": "",
            "summary_through": "", "focus": 0, "unread": 0, "archived": 0, "opened_at": None}


def _stamp(t: dict[str, Any]) -> dict[str, Any]:
    """
    What a thread whose every message went to the archive keeps of them
    (`stamp`, written by `_archive` when it empties the thread, v0.22.0 T26):
    `last_at` (its last message's time), `last` and `last_spoken` (copies of
    its last shown message and its last shown non-system one), `player_at`
    (the player's last message's time), `burst` (`_player_burst`'s count over
    them), `in_a_row` (`_in_a_row`'s) and `spoken` (anyone but the system
    wrote). Every reader of a thread's messages falls back to it once the
    messages in state run out, so a thread emptied to the archive reads as it
    did whole. {} for a thread never emptied.
    """
    return t.get("stamp") or {}


#: A stamp's `last_spoken` when it is its `last` row too (`stamp_of`).
SAME_AS_LAST = "last"

#: What a stamp keeps of a message (`_stamp_row`): what a thread row, its preview and its read
#: state show, and what the readers above compare.
STAMP_KEYS: tuple[str, ...] = ("id", "thread_id", "from", "kind", "at", "voiced", "read_at", "seen_by_them_at")


def _stamp_row(message: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """A message cut to `STAMP_KEYS` and its first bubble's preview (a stamp is bounded state too)."""
    if message is None:
        return None
    row = {k: message[k] for k in STAMP_KEYS if k in message}
    bubbles = message.get("bubbles") or []
    row["bubbles"] = [str(bubbles[0])[:PREVIEW_CHARS]] if bubbles else []
    return row


def stamp_of(messages: list[dict[str, Any]], before: dict[str, Any]) -> dict[str, Any]:
    """`messages` (a thread's, oldest first, all of them) folded onto the stamp `before` they followed."""
    shown_rows = [m for m in messages if shown(m)]
    spoken = [m for m in shown_rows if m["from"] != "system"]
    players = [m for m in messages if m["from"] == "player" and shown(m)]
    holder = {"messages": messages, "stamp": before}
    return {
        "last_at": float(messages[-1]["at"]) if messages else before.get("last_at", -1.0),
        "last": _stamp_row(shown_rows[-1]) if shown_rows else before.get("last"),
        # The same row as `last` most often: then only a mark (`last_shown` reads `last`).
        "last_spoken": (SAME_AS_LAST if spoken and shown_rows and spoken[-1] is shown_rows[-1]
                        else _stamp_row(spoken[-1]) if spoken
                        else before.get("last") if before.get("last_spoken") == SAME_AS_LAST
                        else before.get("last_spoken")),
        "player_at": float(players[-1]["at"]) if players else before.get("player_at"),
        "burst": _burst_of(holder),
        "in_a_row": _in_a_row(holder),
        "spoken": bool(spoken) or bool(before.get("spoken")),
    }


def _last_at(t: dict[str, Any]) -> float:
    messages = t.get("messages") or []
    return float(messages[-1]["at"]) if messages else float(_stamp(t).get("last_at", -1.0))


def last_shown(t: dict[str, Any], *, spoken: bool = False) -> Optional[dict[str, Any]]:
    """The thread's last shown message (`spoken`: not the system's), in state or else its stamp's."""
    rows = [m for m in t.get("messages") or [] if shown(m) and (not spoken or m["from"] != "system")]
    if rows:
        return rows[-1]
    stamp = _stamp(t)
    row = stamp.get("last_spoken" if spoken else "last")
    return stamp.get("last") if row == SAME_AS_LAST else row


def thread_for(state: GameState, pid: str) -> Optional[str]:
    """The thread `pid` replies in: the one the player last wrote in, else their latest open one."""
    last = _person(state, pid).get("last_thread")
    if last and _open(thread(state, last)):
        return str(last)
    candidates = [t for t in _threads(state).values() if t.get("pid") == pid and _open(t)]
    if not candidates:
        return None
    return max(candidates, key=lambda t: (_last_at(t), t["thread_id"]))["thread_id"]


def messengers() -> list[str]:
    """The messenger apps a number exchange opens (apps.yaml `kind: messenger`, `unlock: numbers`)."""
    rows = social.data("apps").get("apps") or {}
    return [name for name, row in rows.items()
            if isinstance(row, dict) and row.get("kind") == "messenger" and row.get("unlock") == "numbers"]


def _player_burst(state: GameState, thread_id: str) -> int:
    """The player's messages since the person last wrote in the thread."""
    return _burst_of(thread(state, thread_id) or {})


def _burst_of(t: dict[str, Any]) -> int:
    """`_player_burst` over one thread row: its messages, then its stamp's count once they run out."""
    count = 0
    for message in reversed(t.get("messages") or []):
        if not shown(message):
            continue                                  # withdrawn: never sent
        if message["from"] == "player":
            count += 1
        elif message["from"] != "system":
            return count
    return count + int(_stamp(t).get("burst") or 0)     # all of them the player's: the archived ones too


def unvoiced(state: GameState) -> list[dict[str, Any]]:
    """Every due message (`voiced is False`) across the threads, oldest first."""
    rows = [m for t in _threads(state).values() for m in t.get("messages") or [] if m.get("voiced") is False]
    return sorted(rows, key=lambda m: (float(m["at"]), int(str(m["id"])[1:] or 0)))


def badges(state: GameState) -> dict[str, int]:
    """Unread messages per app, over the threads the player can see."""
    out: dict[str, int] = {}
    for t in _threads(state).values():
        if matching.listed(t) and int(t.get("unread") or 0) > 0:
            out[t["app"]] = out.get(t["app"], 0) + int(t["unread"])
    return out


# -- writing (inside a social_* handler only: rule 3) --------------------------------------


def _recount(t: dict[str, Any]) -> None:
    t["unread"] = sum(1 for m in t.get("messages") or []
                      if m["from"] == t["pid"] and m.get("read_at") is None and shown(m))


def recount(t: dict[str, Any]) -> None:
    """A thread's unread count, again (inside a social_* handler only: the voicer's withdrawal)."""
    _recount(t)


def notify(state: GameState, app: str, thread_id: str, pid: str, kind: str, preview: str,
           *, at: Optional[float] = None) -> None:
    """One notification, newest last, bounded at `social.notifications_max` (inside a handler only)."""
    counters = state.social.setdefault("counters", {})
    counters["notification"] = int(counters.get("notification", 0)) + 1
    rows = state.social.setdefault("notifications", [])
    rows.append({"id": f"n{counters['notification']}", "app": app, "thread_id": thread_id, "pid": pid,
                 "kind": kind, "preview": preview[:PREVIEW_CHARS],
                 "at": float(state.world_clock_hours if at is None else at)})
    limit = int(social.setting("notifications_max", 30))
    if len(rows) > limit:
        del rows[:len(rows) - limit]


def _preview(message: dict[str, Any]) -> str:
    if message.get("voiced") is False:
        return NEW_MESSAGE
    bubbles = message.get("bubbles") or []
    return str(bubbles[0])[:PREVIEW_CHARS] if bubbles else ""


def _cancel_waiting(state: GameState, pid: str, thread_id: str) -> None:
    """The player wrote: an opener not yet sent in this thread, and any double text of theirs, are moot."""
    def moot(event: dict[str, Any]) -> bool:
        if event["kind"] == "double_text":
            return True
        return event.get("thread_id") == thread_id and _is_opener(event)

    events.cancel(state, pid, {"double_text", "initiate"}, where=moot)


@effect_kind("social_message")
@recorded
def _e_message(state: GameState, effect: dict[str, Any], ctx: EffectContext) -> dict[str, Any]:
    """
    Engine-only: append one message to a thread (`op: append`, the default), or
    open a thread with none (`op: open`: the messengers a number exchange
    unlocks). A player's message schedules the person's read; theirs counts
    unread and notifies.
    """
    if not state.social:
        return {"type": "social_message", "ok": False, "text": "no social slice"}
    tid = str(effect.get("thread_id") or "")
    threads = state.social.setdefault("threads", {})
    if effect.get("op") == "open":
        if tid in threads:
            return {"type": "social_message", "ok": False, "text": f"{tid} is already open"}
        app, _, pid = tid.partition(":")
        if not pid:
            return {"type": "social_message", "ok": False, "text": f"{tid!r} is no thread id"}
        threads[tid] = _new_thread(tid, app, pid)
        return {"type": "social_message", "ok": True, "text": f"opened {tid}", "thread_id": tid}
    t = threads.get(tid)
    if t is None:
        return {"type": "social_message", "ok": False, "text": f"no thread {tid}"}
    if effect.get("op") == "archive":
        return _archive(state, t, int(effect.get("count") or 0))
    kind = str(effect.get("kind") or "text")
    if kind not in MESSAGE_KINDS:
        return {"type": "social_message", "ok": False, "text": f"{kind!r} is no message kind"}
    sender = str(effect.get("from") or "")
    pid = str(t["pid"])
    if sender not in ("player", "system", pid):
        return {"type": "social_message", "ok": False, "text": f"{sender!r} does not write in {tid}"}
    at = float(effect["at"]) if effect.get("at") is not None else state.world_clock_hours
    counters = state.social.setdefault("counters", {})
    counters["message"] = int(counters.get("message", 0)) + 1
    message: dict[str, Any] = {
        "id": f"m{counters['message']}", "thread_id": tid, "from": sender, "kind": kind, "at": at,
        "bubbles": [str(b) for b in effect.get("bubbles") or ()], "voiced": effect.get("voiced", True),
        "decision": effect.get("decision"), "media_id": effect.get("media_id"), "read_at": None,
        "transcript": effect.get("transcript"),
    }
    for key in ("ask", "answer", "request_id"):
        if effect.get(key):
            message[key] = str(effect[key])
    t.setdefault("messages", []).append(message)
    person = state.social.setdefault("people", {}).setdefault(pid, {})
    relationships.touch(person)
    if sender == "player":
        relationships.settle_left_on_read(state, pid, at, clear=True)
        person["last_player_at"] = at
        person["last_thread"] = tid
        relationships.note_message(state, pid, sender, at, message["bubbles"])
        _cancel_waiting(state, pid, tid)
        schedule_reply(state, pid, tid)
    elif sender == pid:
        person["last_them_at"] = at
        relationships.note_message(state, pid, sender, at, message["bubbles"])
        _recount(t)
        notify(state, t["app"], tid, pid, kind, _preview(message), at=at)
    return {"type": "social_message", "ok": True, "text": f"{sender} wrote in {tid}", "message": message}


def _archive(state: GameState, t: dict[str, Any], count: int) -> dict[str, Any]:
    """
    `op: archive` (spec §17.2, Plan decision 18): the thread's oldest `count`
    messages leave state -- `archive.spill` has already appended them to the
    save's `phone_archive.jsonl` -- and `archived` counts them
    (`archived_through` names the newest). Never a due message (one not yet
    voiced stays until it is). An opener of theirs that leaves is remembered
    (`opener_landed`), so they never write first twice; contacts the player
    named in them are remembered as told (`memory.note_told`, T12).
    """
    messages = t.setdefault("messages", [])
    tid = t["thread_id"]
    if count <= 0 or count >= len(messages) + 1:
        return {"type": "social_message", "ok": False, "text": f"cannot archive {count} of {tid}"}
    moved = messages[:count]
    if any(m.get("voiced") is False for m in moved):
        return {"type": "social_message", "ok": False, "text": f"{tid} holds a due message in those {count}"}
    if count == len(messages):
        # Every message leaves (a dead thread, archive.spill): what their readers need of them stays
        # behind as the thread's stamp (`_stamp`, v0.22.0 T26).
        t["stamp"] = stamp_of(moved, _stamp(t))
    del messages[:count]
    t["archived"] = int(t.get("archived") or 0) + count
    # The newest message the archive holds: the thread summary reads the
    # archive while this is past its `summary_through` (memory.thread_view).
    t["archived_through"] = str(moved[-1]["id"])
    if any(_is_opener(m) and m["from"] == t["pid"] and shown(m) for m in moved):
        state.social.setdefault("people", {}).setdefault(t["pid"], {})["opener_landed"] = True
    # Names the player gave them in these messages stay known once only the
    # archive holds the words (agreement.view_from_state reads `told`).
    from engine.social import memory   # lazily: memory reads agreement, which reads population

    memory.note_told(state, str(t["pid"]), moved)
    return {"type": "social_message", "ok": True, "text": f"archived {count} of {tid}", "thread_id": tid,
            "messages": moved}


@effect_kind("social_read")
@recorded
def _e_read(state: GameState, effect: dict[str, Any], ctx: EffectContext) -> dict[str, Any]:
    """
    Engine-only read marks (spec §9.4). `reader: player` (open_thread): the
    player's read time on the person's voiced messages, the thread's focus
    stamp and `open_thread`; seen by them where receipts allow, and a last
    message of theirs left unanswered starts `left_on_read_since`. `reader:
    <pid>`: their read time on the player's messages, kept on a receipts app.
    """
    if not state.social:
        return {"type": "social_read", "ok": False, "text": "no social slice"}
    tid = str(effect.get("thread_id") or "")
    t = _threads(state).get(tid)
    if t is None:
        return {"type": "social_read", "ok": False, "text": f"no thread {tid}"}
    reader = str(effect.get("reader") or "player")
    at = float(effect["at"]) if effect.get("at") is not None else state.world_clock_hours
    on_app = bool(apps.app(t["app"]).get("receipts"))
    marked = 0
    if reader == "player":
        seen = on_app and bool((state.social.get("settings") or {}).get("receipts", True))
        for message in t.get("messages") or []:
            if message["from"] != t["pid"] or message.get("voiced") is False or message.get("read_at") is not None:
                continue
            message["read_at"] = at
            marked += 1
            if seen:
                message["seen_by_them_at"] = at
        t["opened_at"] = at
        t["focus"] = max([int(x.get("focus") or 0) for x in _threads(state).values()] + [0]) + 1
        state.social["open_thread"] = tid
        _recount(t)
        last = last_shown(t, spoken=True)
        if seen and last is not None and last["from"] == t["pid"] and last.get("voiced") is not False:
            person = state.social.setdefault("people", {}).setdefault(t["pid"], {})
            if person.get("left_on_read_since") is None:
                person["left_on_read_since"] = at
                relationships.touch(person)
    elif reader == t["pid"]:
        if on_app:
            for message in t.get("messages") or []:
                if message["from"] == "player" and message.get("read_at") is None:
                    message["read_at"] = at
                    marked += 1
    else:
        return {"type": "social_read", "ok": False, "text": f"{reader!r} does not read {tid}"}
    return {"type": "social_read", "ok": True, "text": f"{reader} read {tid}", "marked": marked}


def new_message(state: GameState, thread_id: str, sender: str, kind: str, *, at: Optional[float] = None,
                bubbles: Any = (), voiced: Any = True, decision: Optional[dict[str, Any]] = None,
                media_id: Optional[str] = None, transcript: Optional[str] = None) -> dict[str, Any]:
    """Append one message through `social_message`; the row. A ValueError when the effect refuses it."""
    result = apply_effect(state, {
        "type": "social_message", "thread_id": thread_id, "from": sender, "kind": kind, "at": at,
        "bubbles": list(bubbles), "voiced": voiced, "decision": decision, "media_id": media_id,
        "transcript": transcript,
    })
    if not result.get("ok"):
        raise ValueError(f"social: new_message: {result.get('text')}")
    return result["message"]


def open_numbers(state: GameState, pid: str) -> list[str]:
    """Open the messenger threads a number exchange unlocks (Texts, Natter); the ids opened."""
    opened: list[str] = []
    for app in messengers():
        tid = matching.thread_id(app, pid)
        if tid not in _threads(state) and apply_effect(
                state, {"type": "social_message", "op": "open", "thread_id": tid}).get("ok"):
            opened.append(tid)
    return opened


# -- the person's side: reads, replies, openers, initiations, double texts --------------------


def _event_kind(situation: str) -> str:
    return situation if situation in ("reply", "double_text") else (
        "reply" if situation == "answer_request" else "initiate")


def queue_due(state: GameState, pid: str, thread_id: str, decision: Decision, at: float) -> None:
    """Queue a due message: a `reply`, `initiate` or `double_text` event carrying `decision`."""
    _queue_due(state, pid, thread_id, decision, at)


def _queue_due(state: GameState, pid: str, thread_id: str, decision: Decision, at: float, **extra: Any) -> None:
    events.push(state, at, pid, _event_kind(decision.situation), thread_id=thread_id,
                decision=dataclasses.asdict(decision), **extra)


def _awake(person: population.Person, at: float) -> float:
    return behaviour.next_awake(person, at) if behaviour.status_at(person, at) == "asleep" else at


def schedule_reply(state: GameState, pid: str, thread_id: str) -> None:
    """On a player send: a read, then (decided at the read) a reply or left-on-read; one decision per burst."""
    person_state = state.social["people"][pid]
    pending = person_state.get("pending_read")
    if not isinstance(pending, dict):              # one read pending per THREAD: a send elsewhere gets its own
        pending = person_state["pending_read"] = {}
    if pending.get(thread_id) or person_state.get("ghosted") or apps.gone(state, pid):
        return                                    # a burst: the read already queued decides for all of it
    person = population.profile(state, pid)
    arch = behaviour.archetype(person.archetype)
    now = float(((thread(state, thread_id) or {}).get("messages") or [{}])[-1].get("at", state.world_clock_hours))
    rng = behaviour.person_rng(state, SOCIAL_PACE, pid)
    read_at = now + behaviour.lognormal_minutes(rng, *arch.read_minutes) / 60.0
    if behaviour.status_at(person, read_at) == "asleep":
        read_at = behaviour.next_awake(person, read_at)
    pending[thread_id] = True                     # inside the social_message handler that called this
    events.push(state, read_at, pid, "read", thread_id=thread_id)


def _reply_minutes(state: GameState, pid: str, person: population.Person, at: float, interest: float) -> float:
    arch = behaviour.archetype(person.archetype)
    pace = behaviour.person_rng(state, SOCIAL_PACE, pid)
    return (behaviour.lognormal_minutes(pace, *arch.reply_minutes) * _status_mult(person, at)
            / max(0.2, interest / 50.0))


@events.handles("read")
def _on_read(state: GameState, event: dict[str, Any]) -> dict[str, Any]:
    pid, thread_id = str(event["pid"]), str(event["thread_id"])
    person_state = state.social["people"].setdefault(pid, {})
    pending = person_state.get("pending_read")
    if isinstance(pending, dict):
        pending.pop(thread_id, None)
    if not _open(thread(state, thread_id)) or apps.gone(state, pid) or person_state.get("ghosted"):
        return {"ok": False, "why": "closed"}
    at = float(event["at"])
    relationships.settle_left_on_read(state, pid, at)
    apply_effect(state, {"type": "social_read", "thread_id": thread_id, "reader": pid, "at": at})
    person = population.profile(state, pid)
    arch = behaviour.archetype(person.archetype)
    rng = behaviour.person_rng(state, SOCIAL_BEHAVIOUR, pid)
    interest = float(person_state.get("interest", 50))
    burst = _player_burst(state, thread_id)
    ghost_p = arch.ghost_per_exchange * (1 - interest / 100.0) * _stage_factor(person_state.get("stage"))
    if rng.random() < ghost_p:
        apply_effect(state, {"type": "social_person", "pid": pid, "set": {"ghosted": True}})
        events.cancel(state, pid)
        return {"ok": True, "ghosted": True}
    asked = relationships.pending_asks(state, pid)
    if asked:
        where = str(asked[0].get("thread_id") or thread_id)   # answered in the thread it was asked in
        return _answer_ask(state, pid, asked[0], where if _open(thread(state, where)) else thread_id, at, burst,
                           interest)
    if rng.random() >= arch.reply_prob * _interest_factor(interest) * _burst_factor(burst):
        return {"ok": True, "left_on_read": True}
    minutes = _reply_minutes(state, pid, person, at, interest)
    decision = Decision(situation="reply", kind="text", max_bubbles=min(3, 1 + burst))
    queue_due(state, pid, thread_id, decision, at + minutes / 60.0)
    return {"ok": True, "reply_in_minutes": minutes}


def _number_accepted(state: GameState, pid: str) -> bool:
    """The number draw (spec §9.5): relationships.accept_draw for a number (F16: a test pins it here)."""
    return relationships.accept_draw(state, pid, "number")


def _answer_ask(state: GameState, pid: str, request: dict[str, Any], thread_id: str, at: float, burst: int,
                interest: float) -> dict[str, Any]:
    """At their read: the player's ask decided (relationships.ask_decision), the stage moved on yes. The answer is due.
    A media ask (T19) is decided by `media.answer_request`: the medium itself, or the decline, is due."""
    if str(request["what"]) in MEDIA_KINDS:
        from engine.social import media

        person = population.profile(state, pid)
        minutes = _reply_minutes(state, pid, person, at, interest)
        return media.answer_request(state, pid, request, thread_id, at, at + minutes / 60.0, burst)
    if str(request["what"]) == MEET_ASK:
        from engine.social import meets   # lazily: meets imports this module

        accepted = meets.answer_ask(state, pid, request, at)   # the engine picks the venue and the slot
    else:
        decided = relationships.ask_decision(state, pid, str(request["what"]))
        accepted = bool(decided["accept"])
        relationships.settle_ask(state, request, accepted, at, why=str(decided.get("why") or ""))
    person = population.profile(state, pid)
    minutes = _reply_minutes(state, pid, person, at, interest)
    decision = Decision(situation="answer_request", kind="text" if accepted else "decline",
                        max_bubbles=min(3, 1 + burst), request_id=str(request["id"]))
    queue_due(state, pid, thread_id, decision, at + minutes / 60.0)
    return {"ok": True, str(request["what"]): accepted}


def on_match(state: GameState, app: str, pid: str, at: float) -> None:
    """
    A new match (called inside `social_match`'s handler): the person's
    possible opener, queued at a delay from their pace; whether they write
    first (`opener_prob`) is drawn when it falls due.
    """
    if str(apps.app(app).get("first_message") or "either") == "player":
        return
    if _opener_taken(state, pid):
        return                                    # ONE opener per person, whichever app matched first
    person = population.profile(state, pid)
    arch = behaviour.archetype(person.archetype)
    pace = behaviour.person_rng(state, SOCIAL_PACE, pid)
    due = _awake(person, at + behaviour.lognormal_minutes(pace, *arch.reply_minutes) / 60.0)
    queue_due(state, pid, matching.thread_id(app, pid), Decision(situation="opener"), due)


def _is_opener(row: dict[str, Any]) -> bool:
    return (row.get("decision") or {}).get("situation") == "opener"


def _opener_taken(state: GameState, pid: str) -> bool:
    """An opener of `pid`'s is pending, or one already landed in any thread of theirs."""
    if any(e["pid"] == pid and e["kind"] == "initiate" and _is_opener(e) for e in state.social.get("queue") or []):
        return True
    if _person(state, pid).get("opener_landed"):
        return True   # it landed, and has since moved to the archive
    return any(_is_opener(m) for t in _threads(state).values() if t.get("pid") == pid
               for m in t.get("messages") or [] if m["from"] == pid and shown(m))


def _player_wrote_since(t: dict[str, Any], since: float) -> bool:
    if any(m["from"] == "player" and float(m["at"]) > since for m in t.get("messages") or []):
        return True
    player_at = _stamp(t).get("player_at")
    return player_at is not None and float(player_at) > since


def _in_a_row(t: dict[str, Any]) -> int:
    """Their double texts since the player's last message in the thread."""
    count = 0
    for message in reversed(t.get("messages") or []):
        if not shown(message):
            continue                                  # withdrawn: never sent, not a double text
        if message["from"] == "player":
            return count
        if (message.get("decision") or {}).get("situation") == "double_text":
            count += 1
    return count + int(_stamp(t).get("in_a_row") or 0)  # no player message in state: the archived run too


def _maybe_double_text(state: GameState, pid: str, thread_id: str, at: float) -> None:
    """A message of theirs just landed: draw whether they text again after `after_hours` of silence."""
    person = population.profile(state, pid)
    spec = behaviour.archetype(person.archetype).double_text
    if float(spec.get("prob", 0)) <= 0 or int(spec.get("max_in_row", 0)) <= 0:
        return
    if _in_a_row(thread(state, thread_id) or {}) >= int(spec["max_in_row"]):
        return
    if any(e["pid"] == pid and e["kind"] == "double_text" and e.get("thread_id") == thread_id
           for e in state.social.get("queue") or []):
        return                                    # one chain at a time: the pending one is the next in the row
    if behaviour.person_rng(state, SOCIAL_BEHAVIOUR, pid).random() >= float(spec["prob"]):
        return
    due = _awake(person, at + float(spec["after_hours"]))
    _queue_due(state, pid, thread_id, Decision(situation="double_text"), due, since=at)


def _initiation_row(person: population.Person, initiation: str) -> Optional[dict[str, Any]]:
    rows = behaviour.archetype(person.archetype).initiations
    return next((row for row in rows if row["id"] == initiation), None)


def when_holds(state: GameState, pid: str, when: dict[str, Any], at: float) -> bool:
    """An initiation's `when` (behaviours.yaml's header), read at in-game hour `at`."""
    person_state = _person(state, pid)
    if bool(person_state.get("ghosted")) != bool(when.get("ghosted", False)):
        return False
    since_player = person_state.get("last_player_at", person_state.get("matched_at"))
    marks = [person_state.get(k) for k in ("last_player_at", "last_them_at", "matched_at")]
    last = max((float(v) for v in marks if v is not None), default=None)
    for key, value in when.items():
        if key == "ghosted":
            continue
        if key == "stage_min":
            if stage_rank(person_state.get("stage")) < stage_rank(value) or stage_rank(value) < 0:
                return False
        elif key == "hours_since_player":
            if since_player is None or at - float(since_player) < float(value):
                return False
        elif key == "days_since_last":
            if last is None or (at - last) / 24.0 < float(value):
                return False
        elif key == "weekend":
            if (behaviour.weekday_of(at) in ("sat", "sun")) != bool(value):
                return False
        else:
            return False
    return True


def _live(state: GameState) -> list[str]:
    """Everyone the player has an open thread with and has not lost (sorted: the draws' order is fixed)."""
    pids = {t["pid"] for t in _threads(state).values() if _open(t)}
    return sorted(pid for pid in pids if not apps.gone(state, pid))


def _initiation_thread(state: GameState, pid: str) -> Optional[str]:
    """Where they start a conversation: their preferred messenger once numbers are swapped, else thread_for."""
    open_ = sorted(tid for tid in (matching.thread_id(app, pid) for app in messengers())
                   if _open(thread(state, tid)))
    if open_:
        return stable_rng(state.rng_seed, f"{SOCIAL_BEHAVIOUR}:{pid}:messenger").choice(open_)
    return thread_for(state, pid)


def _initiation_at(person: population.Person, row: dict[str, Any], day_at: float, rng: Any) -> Optional[float]:
    """One of the row's `at_hours` (or any hour) inside the daily's day that falls in their free time."""
    midnight = day_at - events.DAILY_HOUR

    def clock_at(hour: int) -> float:
        at = midnight + hour
        return at + 24.0 if at < day_at else at

    hours = [h for h in (row.get("at_hours") or range(24)) if behaviour.status_at(person, clock_at(h)) in FREE]
    if not hours:
        return None
    return clock_at(rng.choice(hours)) + rng.random()


def _queue_initiations(state: GameState) -> None:
    """The `daily` step (spec §9.3): each live person's initiations, one a day at most."""
    day_at = events.daily_at(state)
    queued = {e["pid"] for e in state.social.get("queue", []) if e["kind"] == "initiate"}
    for pid in _live(state):
        if pid in queued:
            continue
        person = population.profile(state, pid)
        person_state = state.social["people"].setdefault(pid, {})
        for row in behaviour.archetype(person.archetype).initiations:
            once = "prob" in row
            marker = person_state.get("last_player_at")
            done = person_state.setdefault("initiated", {})
            if once and row["id"] in done and done[row["id"]] == marker:
                continue                      # `prob`: one draw per spell of the player's silence
            at = _initiation_at(person, row, day_at, behaviour.person_rng(state, SOCIAL_PACE, pid))
            if at is None or not when_holds(state, pid, row.get("when") or {}, at):
                continue
            chance = float(row["prob"] if once else row["prob_per_day"])
            if once:
                done[row["id"]] = marker
            if behaviour.person_rng(state, SOCIAL_BEHAVIOUR, pid).random() >= chance:
                continue
            tid = _initiation_thread(state, pid)
            if tid is None:
                break
            decision = Decision(situation=str(row.get("instruction") or row["id"]), kind=str(row["kind"]))
            _queue_due(state, pid, tid, decision, at, initiation=row["id"])
            break


if _queue_initiations not in events.daily_hooks:
    events.daily_hooks.append(_queue_initiations)


def _on_due(state: GameState, event: dict[str, Any]) -> dict[str, Any]:
    """A due message falls due: re-checked, then landed unvoiced with its decision (no model runs)."""
    pid, tid = str(event["pid"]), str(event["thread_id"])
    decision = dict(event.get("decision") or {})
    situation = str(decision.get("situation") or "")
    t = thread(state, tid)
    person_state = state.social["people"].setdefault(pid, {})
    if not _open(t) or apps.gone(state, pid):
        return {"ok": False, "why": "closed"}
    at = float(event["at"])
    person = population.profile(state, pid)
    if event.get("initiation"):
        row = _initiation_row(person, str(event["initiation"]))
        if row is None or not when_holds(state, pid, row.get("when") or {}, at):
            return {"ok": False, "why": "no longer holds"}
        if person_state.get("ghosted"):
            person_state["ghosted"] = False          # a `ghosted: true` row: they came back
            relationships.touch(person_state)
            relationships.add_history(state, pid, "reconnected", "Got back in touch", at=at)
            from engine.social import games       # lazily: games imports this module

            games.rearm(state, pid, at)              # a game left on their turn while they were gone
    elif person_state.get("ghosted"):
        return {"ok": False, "why": "gone quiet"}
    elif situation == "opener":
        if last_shown(t, spoken=True) is not None:
            return {"ok": False, "why": "already written in"}
        arch = behaviour.archetype(person.archetype)
        if behaviour.person_rng(state, SOCIAL_BEHAVIOUR, pid).random() >= arch.opener_prob:
            return {"ok": True, "opener": False}
    elif situation == "double_text":
        if _player_wrote_since(t, float(event.get("since", at))):
            return {"ok": False, "why": "the player wrote"}
        cap = int(behaviour.archetype(person.archetype).double_text.get("max_in_row", 0))
        if _in_a_row(t) >= cap:
            return {"ok": False, "why": "max_in_row"}         # the cap holds when it lands, too
    relationships.settle_left_on_read(state, pid, at)
    kind = str(decision.get("kind") or "text")
    media_kind = str(decision.get("media_kind") or "")
    if media_kind:
        from engine.social import media

        if not media.can_carry(state, tid, media_kind):
            return {"ok": False, "why": f"{tid} cannot carry a {media_kind}"}
    message = new_message(state, tid, pid, kind if kind in MESSAGE_KINDS else "text", at=at,
                          bubbles=(), voiced=False, decision=decision)
    if media_kind:
        media.attach(state, pid, tid, message["id"], media_kind, str(decision.get("subject") or ""))
    _maybe_double_text(state, pid, tid, at)
    return {"ok": True, "message_id": message["id"], "situation": situation}


for _kind in DUE_KINDS:
    events.handles(_kind)(_on_due)


# -- the player's actions ---------------------------------------------------------------------


def _closed_reason(state: GameState, t: dict[str, Any]) -> str:
    name = _name(state, t["pid"])
    closed = t.get("closed")
    if closed == "blocked":
        return f"You blocked {name}."
    if closed == "unmatched":
        by = _person(state, t["pid"]).get("unmatched_by")
        return f"{name} unmatched you." if by == "them" else f"You unmatched {name}."
    if closed == "expired":
        return f"Your match with {name} expired."
    return f"You can't write to {name} there any more."


def send(state: GameState, thread_id: str, kind: str, text: str, *, photo_id: str = "", subject: str = "",
         transcript: str = "") -> dict[str, Any]:
    """
    The player's message (spec §9.2): appended (the person's read is
    scheduled), then its minutes spent. A voice note (spec §13.7) is its
    ``transcript`` (the client's push-to-talk, `POST /api/voice/transcribe`),
    cut by length to `media.yaml` `voice.max_seconds`; no audio is kept.
    """
    t = thread(state, thread_id)
    if t is None:
        return _no("There's no such conversation.")
    if t.get("closed"):
        return _no(_closed_reason(state, t))
    app = str(t["app"])
    if kind not in apps.capabilities(app):
        return _no(f"{apps.label(app)} can't send {_noun(kind)}")
    if kind not in SENDABLE:
        return _no(f"Sending {_noun(kind)} isn't possible yet.")
    words = str(text or "").strip()
    if kind == "text" and not words:
        return _no("Write something first.")
    cap = int(social.setting("max_text_chars", 600))
    if len(words) > cap:
        return _no(f"That message is longer than {cap} characters.")
    if kind in ("photo", "video"):
        return _send_media(state, t, kind, words, photo_id=str(photo_id or ""), subject=str(subject or ""))
    if kind == "voice":
        from engine.social import media

        said = media.voice_transcript(str(transcript or "").strip())
        if not said:
            return _no("Say something first.")
        message = new_message(state, thread_id, "player", "voice", transcript=said)
        clock.advance_time(state, cost_hours(state, app, kind))
        return {"ok": True, "thread_id": thread_id, "app": app, "pid": t["pid"], "message_id": message["id"],
                "seconds": media.voice_note_seconds(said)}
    message = new_message(state, thread_id, "player", kind, bubbles=[words])
    clock.advance_time(state, cost_hours(state, app, kind))
    return {"ok": True, "thread_id": thread_id, "app": app, "pid": t["pid"], "message_id": message["id"]}


def _send_media(state: GameState, t: dict[str, Any], kind: str, words: str, *, photo_id: str,
                subject: str) -> dict[str, Any]:
    """
    The player's own photo or video (spec §13.7): a camera-roll photo
    (`photo_id`, one of their profile photos) or a `player_subjects` row
    (`subject`), with an optional caption; a media row `own` rides on it.
    """
    from engine.social import media

    if kind == "photo" and photo_id:
        if photo_id not in media.player_photos(state):
            return _no("That photo isn't in your camera roll.")
        subject = ""
    elif subject:
        if subject not in {r["id"] for r in media.player_subjects(kind)}:
            return _no(f"You can't send that as a {kind}.")
        photo_id = ""
    else:
        return _no("Pick a photo first." if kind == "photo" else "Pick something to film first.")
    app = str(t["app"])
    message = new_message(state, t["thread_id"], "player", kind, bubbles=[words] if words else [])
    mid = media.attach_own(state, t["thread_id"], message["id"], kind, subject, photo_id)
    clock.advance_time(state, cost_hours(state, app, kind))
    return {"ok": True, "thread_id": t["thread_id"], "app": app, "pid": t["pid"], "message_id": message["id"],
            "media_id": mid}


def open_thread(state: GameState, thread_id: str) -> dict[str, Any]:
    """Open a thread: the player's read marks, its focus (raises its voicing priority, §11.1)."""
    t = thread(state, thread_id)
    if t is None or not matching.listed(t):
        return _no("There's no such conversation.")
    result = apply_effect(state, {"type": "social_read", "thread_id": thread_id, "reader": "player"})
    return {"ok": bool(result.get("ok")), "thread_id": thread_id, "marked": result.get("marked", 0)}


def ask(state: GameState, thread_id: str, what: str) -> dict[str, Any]:
    """The player's ask in a thread (relationships.ask: their number, to be exclusive)."""
    return relationships.ask(state, thread_id, what)


# -- the catalogue (spec §7.1) -------------------------------------------------------------------


def _thread_label(state: GameState, t: dict[str, Any]) -> str:
    return f"{_name(state, t['pid'])} ({apps.label(t['app'])})"


def _target_name(state: GameState, intent: dict[str, Any]) -> str:
    t = thread(state, str(intent.get("target") or ""))
    return _name(state, t["pid"]) if t else str(intent.get("target") or "")


@phone_verb("send", payload={"kind": ArgSpec("enum", SEND_KINDS, required=True), "photo_id": ArgSpec("id"),
                             "subject": ArgSpec("enum"),
                             "audio_transcript": ArgSpec("text", max_len=AUDIO_TRANSCRIPT_MAX)}, skill="social_send",
            takes_text=True, text_cap="social.max_text_chars",
            label=lambda s, i: f"Message {_target_name(s, i)}")
def _send_verb(state: GameState) -> Optional[IntentVerb]:
    # Every thread the player has: a closed one is refused by `send` in words ("Kai unmatched you.").
    rows = [t for t in _threads(state).values()]
    if not rows:
        return None
    from engine.social import media

    return IntentVerb("send", options=tuple((t["thread_id"], _thread_label(state, t)) for t in rows),
                      extra={"photo_id": tuple(media.player_photos(state)),
                             "subject": tuple(r["id"] for r in media.player_subjects())})


@phone_verb("open_thread", payload={}, skill="social_open_thread",
            label=lambda s, i: f"Open your chat with {_target_name(s, i)}")
def _open_thread_verb(state: GameState) -> Optional[IntentVerb]:
    rows = [t for t in _threads(state).values() if matching.listed(t)]
    if not rows:
        return None
    return IntentVerb("open_thread", options=tuple((t["thread_id"], _thread_label(state, t)) for t in rows))


def _ask_label(state: GameState, intent: dict[str, Any]) -> str:
    name = _target_name(state, intent)
    what = str((intent.get("args") or {}).get("what") or "")
    if what in MEDIA_KINDS:
        return f"Ask {name} for {dict(ONE_OF).get(what, what)}"
    if what == MEET_ASK:
        return f"Ask {name} to meet up"
    return f"Ask {name} to be exclusive" if what == "exclusive" else f"Ask {name} for their number"


def _ask_refusal(state: GameState, intent: dict[str, Any]) -> str:
    """
    Why an ask the catalogue does not offer is refused: their stage's reason
    first ("You already have Kai's number."), else past today's asks, "Give
    it a day" (spec §10.6).
    """
    t = thread(state, str(intent.get("target") or ""))
    what = str((intent.get("args") or {}).get("what") or "")
    if t is None or what not in ASKS or t.get("closed") or apps.gone(state, t["pid"]):
        return ""
    pid = str(t["pid"])
    if what in MEDIA_KINDS:
        from engine.social import media

        return media.ask_refusal(state, pid, t["thread_id"], what)
    if what == MEET_ASK:
        from engine.social import meets

        return meets.ask_refusal(state, pid)
    return relationships.ask_stage_refusal(state, pid, what) or relationships.ask_refusal(state, pid, what)


def _offered_asks(state: GameState, t: dict[str, Any]) -> list[str]:
    """The asks the catalogue offers in thread ``t`` now (the `ask` verb's rule; the person still decides)."""
    if not _open(t) or apps.gone(state, t["pid"]):
        return []
    offered = []
    what = relationships.ask_kind_for(_person(state, t["pid"]).get("stage"))
    if what is not None and not relationships.ask_refusal(state, t["pid"], what):
        offered.append(what)
    from engine.social import media

    refusals = {k: media.ask_refusal(state, t["pid"], t["thread_id"], k) for k in MEDIA_KINDS}
    offered += [k for k, why in refusals.items() if not why]
    from engine.social import meets

    if meets.venues() and not meets.ask_refusal(state, t["pid"]):
        offered.append(MEET_ASK)
    return offered


def ready_asks(state: GameState, t: dict[str, Any]) -> list[str]:
    """
    The thread row's `asks` (owner bug, v0.22.0): the asks offered now, a
    stage ask (their number, to be exclusive) only once its stage's gate
    holds (`relationships.can_reach`), so the Ask menu greys "Their number"
    by the engine's word until a yes is possible. Still decided at their read.
    """
    pid = str(t["pid"])
    stage_asks = dict(relationships.ASK_STAGE)
    return [k for k in _offered_asks(state, t)
            if k not in stage_asks or relationships.can_reach(state, pid, stage_asks[k])]


@phone_verb("ask", payload={"what": ArgSpec("enum", ASKS, required=True)}, skill="social_ask",
            label=_ask_label, refuse=_ask_refusal)
def _ask_verb(state: GameState) -> Optional[IntentVerb]:
    rows: list[dict[str, Any]] = []
    kinds: list[str] = []
    for t in _threads(state).values():
        offered = _offered_asks(state, t)
        if not offered:
            continue
        rows.append(t)
        kinds += [k for k in offered if k not in kinds]
    if not rows:
        return None
    return IntentVerb("ask", options=tuple((t["thread_id"], _thread_label(state, t)) for t in rows),
                      extra={"what": tuple(k for k in ASKS if k in kinds)})


# -- the payload (spec §17.3) ----------------------------------------------------------------------


def _receipts_shown(state: GameState, t: dict[str, Any]) -> bool:
    """Read receipts show in this thread: its app keeps them and the player has theirs on (§9.4)."""
    return bool(apps.app(t["app"]).get("receipts")) and bool(
        (state.social.get("settings") or {}).get("receipts", True))


def _typing_shown(t: dict[str, Any], typing: set[str]) -> bool:
    """Typing dots in this thread: a voicing call is in flight on it AND its app shows them
    (apps.yaml `typing`, true when unset; Texts says false, as SMS shows none)."""
    return t["thread_id"] in typing and bool(apps.app(t["app"]).get("typing", True))


def _message_view(state: GameState, t: dict[str, Any], m: dict[str, Any]) -> dict[str, Any]:
    """A message as the player sees it: no decision, no words before it is voiced."""
    pending = m.get("voiced") is False
    view: dict[str, Any] = {
        "id": m["id"], "from": m["from"], "kind": m["kind"], "at": m["at"],
        "bubbles": [] if pending else list(m.get("bubbles") or []), "pending": pending,
        "media_id": m.get("media_id"), "transcript": None if pending else m.get("transcript"),
    }
    if m.get("media_id") and not pending:
        from engine.social import media

        view["media"] = media.media_view(state, str(m["media_id"]))
    if m["from"] == "player":
        view["read_at"] = m.get("read_at") if _receipts_shown(state, t) else None
    for key in ("ask", "answer", "request_id"):
        if m.get(key):
            view[key] = m[key]
    decision = m.get("decision") or {}
    if not pending and m["from"] != "player" and decision.get("kind") == "decline" and decision.get("request_id"):
        # Their no, and whether it was "not yet" (the gate) rather than a plain no (owner bug, v0.22.0).
        request = (state.social.get("requests") or {}).get(str(decision["request_id"])) or {}
        view["declined"] = "not_yet" if request.get("why") == "not yet" else "no"
    if isinstance(m.get("counter"), dict):
        from engine.social import meets   # lazily: meets imports this module

        view["counter"] = meets.counter_view(state, str(t["pid"]), m["counter"])
    return view


def _read_state(state: GameState, t: dict[str, Any]) -> str:
    last = last_shown(t, spoken=True)
    if last is None or last["from"] != "player":
        return ""
    return "read" if _receipts_shown(state, t) and last.get("read_at") is not None else "delivered"


def _thread_row(state: GameState, t: dict[str, Any], typing: set[str]) -> dict[str, Any]:
    last = last_shown(t)
    person_state = _person(state, t["pid"])
    stage = person_state.get("stage")
    return {
        "thread_id": t["thread_id"], "app": t["app"], "pid": t["pid"], "name": _name(state, t["pid"]),
        "avatar_url": _avatar(state, t["pid"]),
        "last": None if last is None else {"from": last["from"], "kind": last["kind"], "at": last["at"],
                                           "preview": _preview(last), "pending": last.get("voiced") is False},
        "unread": int(t.get("unread") or 0), "typing": _typing_shown(t, typing),
        "read_state": _read_state(state, t), "open": not t.get("closed"),
        "stage_words": relationships.stage_words(str(stage)) if stage else "",
        "band": relationships.band(person_state) if stage else "",
        "asks": ready_asks(state, t),
    }


def _avatar(state: GameState, pid: str) -> str:
    """Their ready portrait's URL (T19), else "": the client draws the procedural tile."""
    from engine.social import media

    return media.portrait_url(state, pid)


def thread_row(state: GameState, thread_id: str, session: Any = None) -> Optional[dict[str, Any]]:
    """One row of the payload's `threads` (spec §17.3), by id; None for no such thread."""
    t = thread(state, thread_id)
    return None if t is None else _thread_row(state, t, _typing(session))


def message_view(state: GameState, t: dict[str, Any], m: dict[str, Any]) -> dict[str, Any]:
    """A message row as the client may see it (the thread page reuses it)."""
    return _message_view(state, t, m)


def _typing(session: Any) -> set[str]:
    return set(tuple(getattr(session, "typing", None) or ()))


@section("threads", time_varying=True)
def _threads_section(state: GameState, session: Any) -> list[dict[str, Any]]:
    """Every thread the player can see (unmatched and blocked ones hidden), latest first."""
    typing = _typing(session)
    rows = [t for t in _threads(state).values() if matching.listed(t)]
    rows.sort(key=lambda t: (-_last_at(t), t["thread_id"]))
    return [_thread_row(state, t, typing) for t in rows]


@section("notifications", time_varying=True)
def _notifications_section(state: GameState, session: Any) -> list[dict[str, Any]]:
    """The newest notifications (social.notifications_max), for threads still listed."""
    return notification_rows(state)


def notification_rows(state: GameState) -> list[dict[str, Any]]:
    """The `notifications` section's rows, oldest first (the away lock screen reads them too)."""
    out = []
    for row in state.social.get("notifications") or []:
        t = thread(state, str(row.get("thread_id") or ""))
        if t is not None and not matching.listed(t):
            continue
        out.append({**row, "name": _name(state, str(row.get("pid") or ""))})
    return out


def latest_notification(state: GameState, thread_id: str) -> Optional[dict[str, Any]]:
    """The newest notification of ``thread_id`` as the `notifications` section shows it, or None (§17.3's
    `phone_message` push carries it)."""
    t = thread(state, thread_id)
    if t is not None and not matching.listed(t):
        return None
    for row in reversed(state.social.get("notifications") or []):
        if str(row.get("thread_id") or "") == thread_id:
            return {**row, "name": _name(state, str(row.get("pid") or ""))}
    return None


@section("open_thread", time_varying=True)
def _open_thread_section(state: GameState, session: Any) -> Optional[dict[str, Any]]:
    """The thread the player last opened: its last `social.state_messages` messages, or null."""
    t = thread(state, str(state.social.get("open_thread") or ""))
    if t is None or not matching.listed(t):
        return None
    limit = int(social.setting("state_messages", 60))
    messages = [m for m in t.get("messages") or [] if shown(m)]
    return {"thread_id": t["thread_id"], "app": t["app"], "pid": t["pid"], "name": _name(state, t["pid"]),
            "open": not t.get("closed"), "typing": _typing_shown(t, _typing(session)),
            "messages": [_message_view(state, t, m) for m in messages[-limit:]],
            # Older ones to page through (GET /api/phone/thread): past the limit, or archived.
            "more": len(messages) > limit or int(t.get("archived") or 0) > 0}

