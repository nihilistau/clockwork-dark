"""
Messaging (v0.22.0 spec §9; v0.23.0 spec §4): the threads across the apps
(the dating apps' chats, Texts, Natter), the player's messages, and the
person's side of them. No model runs here: a message that needs words lands
as a DUE message (`voiced: False`, no bubbles) carrying the engine's
`Decision`, which the voicing pass words later.

**A send** (`send`) appends the player's message through `social_message`,
whose handler hands it to `engine/social/convo.py` (`on_player_send`): in a
conversation already going the person reads it at once, so their reply is
due at the send's own minute (v0.23.0 §4.3); otherwise they read it when
they are next available (a schedule boundary, never a lognormal delay). The
read, the per-episode-start draws (a ghost, a reply or left on read), a
pending ask's answer and the reply's shape are convo's. Then the send's
minutes (conversation.yaml `costs:`) pass through `clock.advance_time`
(rule 2).

**Openers** (spec §8.3): every match queues an `initiate` with situation
`opener` at a delay from their pace; when it falls due, `opener_prob` is
drawn. The player writing first cancels it. **Initiations** are convo's
daily step (by window, v0.23.0 §4.7); this module lands them when due.
An opener or an initiation that lands starts a conversation
(`convo.on_their_message`). **Double texts**: when a message of theirs
lands, `double_text.prob` is drawn; a `double_text` falls due `after_hours`
later, unless the player has written since or a conversation is going,
capped at `max_in_row` since the player's last message.

**Receipts** (§9.4): opening a thread (`open_thread`) writes the player's
read time on the person's (voiced) messages; on a receipts app with the
player's receipts on, the person sees it (`seen_by_them_at`), and a last
message of theirs read and not answered starts `left_on_read_since`, which
costs interest (relationships.settle_left_on_read) at their next event, or
when the player writes. Receipts off hides both directions in the payload.

**Asks** (§9.5, §10.6): `ask {what: number}` at stage `talking` (or `what:
exclusive` at `dating`) is relationships.ask: a request and a request
message; the person decides at their next read (`answer_ask`: the stage's
gate, then a draw, `_number_accepted` for a number): yes moves the stage
through `social_stage` and, for a number, opens the Texts and Natter
threads; either way the answer is due at the read's own minute
(`answer_request`, a `decline` when no). Every message between the two
counts toward their familiarity (`relationships.note_message`).

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
from engine.social import apps, behaviour, events, matching, places, population, relationships
from engine.social.intents import ArgSpec, phone_verb
from engine.social.kinds import MEDIA_KINDS, PLAN_KINDS, PLAN_WHENS, Decision, stage_rank
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
#: What `ask` may ask for: their number and to be exclusive (T9), to move in and to marry (v0.23.0 T18), a photo,
#: a voice note or a video (T19, decided by engine/social/media.py), and a
#: meet-up (T24, `MEET_ASK`). A game is started with `game_invite` (engine/social/games/, T22).
#: A meet-up asked for: a plan with no set time (engine/social/plans.py `REQUEST`, v0.23.0 T12).
MEET_ASK = "meet"
ASKS: tuple[str, ...] = tuple(what for what, _stage in relationships.ASK_STAGE) + MEDIA_KINDS + (MEET_ASK,)
#: How an ask names one of a kind ("Ask Kai for a voice note").
ONE_OF: tuple[tuple[str, str], ...] = (("photo", "a photo"), ("voice", "a voice note"), ("video", "a video"))
#: A dating app's `first_message` (spec §6): either side, or only the player.
FIRST_MESSAGE: tuple[str, ...] = ("either", "player")
#: The schedule statuses a person is out of work and awake in.
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


# -- threads ----------------------------------------------------------------------------


def _threads(state: GameState) -> dict[str, Any]:
    return state.social.get("threads") or {}


def thread(state: GameState, thread_id: str) -> Optional[dict[str, Any]]:
    return _threads(state).get(thread_id)


def _person(state: GameState, pid: str) -> dict[str, Any]:
    """READ ONLY: a person's dynamic slice, {} when there is none."""
    return (state.social.get("people") or {}).get(pid) or {}


def is_open(t: Optional[dict[str, Any]]) -> bool:
    """A thread that can be written in: it exists and nothing closed it (not even an expiry)."""
    return t is not None and not t.get("closed")


def _new_thread(thread_id: str, app: str, pid: str) -> dict[str, Any]:
    return {"thread_id": thread_id, "app": app, "pid": pid, "messages": [], "focus": 0, "unread": 0,
            "archived": 0, "opened_at": None}


def _stamp(t: dict[str, Any]) -> dict[str, Any]:
    """
    What a thread whose every message went to the archive keeps of them
    (`stamp`, written by `_archive` when it empties the thread, v0.22.0 T26):
    `last_at` (its last message's time), `last` and `last_spoken` (copies of
    its last shown message and its last shown non-system one), `player_at`
    (the player's last message's time), `burst` (`player_burst`'s count over
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


def last_at(t: dict[str, Any]) -> float:
    """When the thread last moved: its newest message in state, else its stamp's `last_at` (-1 for none)."""
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
    if last and is_open(thread(state, last)):
        return str(last)
    candidates = [t for t in _threads(state).values() if t.get("pid") == pid and is_open(t)]
    if not candidates:
        return None
    return max(candidates, key=lambda t: (last_at(t), t["thread_id"]))["thread_id"]


def messengers() -> list[str]:
    """The messenger apps a number exchange opens (apps.yaml `kind: messenger`, `unlock: numbers`)."""
    rows = social.data("apps").get("apps") or {}
    return [name for name, row in rows.items()
            if isinstance(row, dict) and row.get("kind") == "messenger" and row.get("unlock") == "numbers"]


def player_burst(state: GameState, thread_id: str) -> int:
    """The player's messages since the person last wrote in the thread."""
    return _burst_of(thread(state, thread_id) or {})


def _burst_of(t: dict[str, Any]) -> int:
    """`player_burst` over one thread row: its messages, then its stamp's count once they run out.
    A due message of theirs not yet voiced is not "they wrote" (v0.23.0: in a conversation it is
    decided at the player's first send, before the rest of the burst arrives)."""
    count = 0
    for message in reversed(t.get("messages") or []):
        if not shown(message) or message.get("voiced") is False:
            continue                                  # withdrawn: never sent; due: not written yet
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
           *, at: Optional[float] = None, promise_id: str = "") -> None:
    """One notification, newest last, bounded at `social.notifications_max` (inside a handler only).
    A person's promised message names its promise (`promise_id`, v0.23.0 T11, pre-flight F35), so a
    sleeper with "wake me for messages" on is woken by it (`world._wakes`); no other row carries it."""
    counters = state.social.setdefault("counters", {})
    counters["notification"] = int(counters.get("notification", 0)) + 1
    rows = state.social.setdefault("notifications", [])
    row = {"id": f"n{counters['notification']}", "app": app, "thread_id": thread_id, "pid": pid,
           "kind": kind, "preview": preview[:PREVIEW_CHARS],
           "at": float(state.world_clock_hours if at is None else at)}
    if promise_id:
        row["promise_id"] = str(promise_id)
    rows.append(row)
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
    unlocks). A player's message goes to their conversation (`convo.on_player_send`:
    the person's read, now or when they are next available); theirs counts
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
        from engine.social import convo, memory, promises   # lazily: each imports this module

        memory.note_spoken(state, pid, message)   # the person's memory, whatever the app (v0.23.0 §7.1)

        # A promise of theirs kept by this message, or one stated in it (no model, §5.2): before the
        # read, so the person's next decision accepts it.
        promises.on_player_message(state, pid, at)
        promises.note_player_text(state, pid, " ".join(message["bubbles"]) or str(message.get("transcript") or ""), at)
        convo.on_player_send(state, pid, tid, at)
    elif sender == pid:
        person["last_them_at"] = at
        relationships.note_message(state, pid, sender, at, message["bubbles"])
        if message["voiced"] is not False:
            from engine.social import memory   # lazily: memory reads agreement, which reads population

            memory.note_spoken(state, pid, message)   # written now; a due one is noted when voiced
        _recount(t)
        notify(state, t["app"], tid, pid, kind, _preview(message), at=at, promise_id=_promise_of(message))
    return {"type": "social_message", "ok": True, "text": f"{sender} wrote in {tid}", "message": message}


def _promise_of(message: dict[str, Any]) -> str:
    """The promise a person's promised message keeps (its decision's `promise_id`), or ""."""
    decision = message.get("decision") or {}
    if not isinstance(decision, dict) or decision.get("situation") != "promised_message":
        return ""
    return str(decision.get("promise_id") or "")


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
    # The newest message the archive holds: an episode's recap reads the archive
    # for messages older than state's (memory.recap_view, with_archive).
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


def queue_due(state: GameState, pid: str, thread_id: str, decision: Decision, at: float, **extra: Any) -> None:
    """Queue a due message: a `reply`, `initiate` or `double_text` event carrying `decision`. A promised
    message's event names its promise (`promise_id`, pre-flight F35), as its notification will."""
    if decision.situation == "promised_message" and decision.promise_id:
        extra.setdefault("promise_id", decision.promise_id)
    events.push(state, at, pid, _event_kind(decision.situation), thread_id=thread_id,
                decision=dataclasses.asdict(decision), **extra)


_queue_due = queue_due


def _awake(person: population.Person, at: float) -> float:
    return behaviour.next_awake(person, at) if behaviour.status_at(person, at) == "asleep" else at


def _number_accepted(state: GameState, pid: str) -> bool:
    """The number draw (spec §9.5): relationships.accept_draw for a number (F16: a test pins it here)."""
    return relationships.accept_draw(state, pid, "number")


def answer_ask(state: GameState, pid: str, request: dict[str, Any], thread_id: str, at: float) -> dict[str, Any]:
    """
    At their read (inside the read handler): the player's ask decided (relationships.ask_decision),
    the stage moved on yes, and the answer due at the read's own minute (v0.23.0 §4.3), shaped by
    the conversation (`convo.decide`, situation `answer_request`). A media ask (T19) is decided by
    `media.answer_request`: the medium itself, or the decline, is due.
    """
    from engine.social import convo   # lazily: convo imports this module

    shape = convo.decide(state, pid, thread_id, at, situation="answer_request")
    if str(request["what"]) in MEDIA_KINDS:
        from engine.social import media

        return media.answer_request(state, pid, request, thread_id, at, shape)
    if str(request["what"]) == MEET_ASK:
        from engine.social import plans   # lazily: plans imports this module

        accepted = plans.answer_ask(state, pid, request, at)   # a plan with no set time (v0.23.0 §9.2)
    else:
        decided = relationships.ask_decision(state, pid, str(request["what"]))
        accepted = bool(decided["accept"])
        relationships.settle_ask(state, request, accepted, at, why=str(decided.get("why") or ""))
    decision = dataclasses.replace(shape, kind="text" if accepted else "decline", request_id=str(request["id"]))
    queue_due(state, pid, thread_id, decision, at)
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


def live_people(state: GameState) -> list[str]:
    """Everyone the player has an open thread with and has not lost (sorted: the draws' order is fixed)."""
    pids = {t["pid"] for t in _threads(state).values() if is_open(t)}
    return sorted(pid for pid in pids if not apps.gone(state, pid))


def initiation_thread(state: GameState, pid: str) -> Optional[str]:
    """Where they start a conversation: their preferred messenger once numbers are swapped, else thread_for."""
    open_ = sorted(tid for tid in (matching.thread_id(app, pid) for app in messengers())
                   if is_open(thread(state, tid)))
    if open_:
        return stable_rng(state.rng_seed, f"{SOCIAL_BEHAVIOUR}:{pid}:messenger").choice(open_)
    return thread_for(state, pid)


def hold_retry_hours() -> float:
    """How long a held message waits before it is tried again (conversation.yaml `together.hold_retry_minutes`)."""
    return max(1.0, float(social.data("conversation").get("together", {}).get("hold_retry_minutes", 15))) / 60.0


def held(state: GameState, pid: str, here_view: Optional[dict[str, Any]] = None) -> bool:
    """Their texts are held, never dropped, while they are with the player (a scene open, arrived at the
    player's place, or at the player's venue by chance, approached or not: A4 W5, W9); the engine's own
    "<name>'s here" notice is not their text and is never held. With no `here_view` (the delivery seam, once per
    due event) presence answers for this one person (I7)."""
    from engine.social import presence   # lazily: presence imports plans, which imports this module

    return presence.with_player(state, pid, here_view)


def release_held(state: GameState) -> list[dict[str, Any]]:
    """Land, now, every held text whose person is no longer with the player (the clock stopped: the end of a
    scene, the end of a walk). Each queued event is taken off and applied at the present hour; the receipts."""
    now = float(state.world_clock_hours)
    view = None
    out: list[dict[str, Any]] = []
    for event in [e for e in (state.social.get("queue") or []) if e.get("held") and e.get("kind") in DUE_KINDS]:
        from engine.social import presence

        view = view if view is not None else presence.here_view(state)
        if held(state, str(event["pid"]), view):
            continue
        out.append(apply_effect(state, {"type": "social_event", "event": {**event, "at": now}}))
    return out


def _on_due(state: GameState, event: dict[str, Any]) -> dict[str, Any]:
    """A due message falls due (`_land_due`). A person's promised message tells its promise whether it
    landed (`promises.on_landed`: remembered, or void when it could not, review M2)."""
    result = _land_due(state, event)
    if event.get("promise_id") and not result.get("held"):     # a held message is still to land: its promise waits
        from engine.social import promises   # lazily: promises imports this module

        landed = str(result.get("message_id") or "") if result.get("ok") else ""
        promises.on_landed(state, str(event["promise_id"]), landed)
    return result


def _land_due(state: GameState, event: dict[str, Any]) -> dict[str, Any]:
    """A due message falls due: re-checked, then landed unvoiced with its decision (no model runs). While the
    person is with the player it is HELD instead (A4 W5): the same event is pushed again `hold_retry_minutes`
    on, so it lands once they are apart. No draw is made on a hold (rule 4)."""
    pid, tid = str(event["pid"]), str(event["thread_id"])
    if held(state, pid):
        retry = hold_retry_hours()
        data = {k: v for k, v in event.items() if k not in ("at", "seq", "pid", "kind")}
        data["held"] = True
        events.push(state, max(float(event["at"]), float(state.world_clock_hours)) + retry, pid, str(event["kind"]), **data)
        return {"ok": True, "quiet": True, "held": True}
    decision = dict(event.get("decision") or {})
    situation = str(decision.get("situation") or "")
    if event.get("held"):
        decision["after_together"] = True         # it waited while they were with the player (W5)
    t = thread(state, tid)
    person_state = state.social["people"].setdefault(pid, {})
    if not is_open(t) or apps.gone(state, pid):
        return {"ok": False, "why": "closed"}
    at = float(event["at"])
    person = population.profile(state, pid)
    from engine.social import convo   # lazily: convo imports this module

    if event.get("initiation"):
        row = _initiation_row(person, str(event["initiation"]))
        if row is None or not when_holds(state, pid, row.get("when") or {}, at):
            return {"ok": False, "why": "no longer holds"}
        skip = convo.initiation_skip(state, pid, situation, at)
        if skip:
            return {"ok": False, "why": skip}
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
        if convo.episode(state, pid) is not None:
            return {"ok": False, "why": "in a conversation"}     # a double text is for a silence (v0.23.0)
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
    if event.get("initiation") or situation == "opener":
        convo.on_their_message(state, pid, tid, at)          # they started it: a conversation is going
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
    from engine.social import plans   # lazily: plans imports this module

    plans.on_player_text(state, str(t["pid"]), words)         # "running late" within patience extends a plan (§9.3)
    from engine.social import life   # lazily: life imports this module

    life.support(state, str(t["pid"]))                        # a reply while a hard event of theirs runs (§6.3)
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


def ask(state: GameState, thread_id: str, what: str, meet: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """The player's ask in a thread (relationships.ask: their number, to be exclusive, a plan to meet: `meet`
    is its `kind`, `venue` and `when`)."""
    return relationships.ask(state, thread_id, what, meet)


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
    if what == "move_in":
        return f"Ask {name} to move in with you"
    if what == "propose":
        return f"Ask {name} to marry you"
    return f"Ask {name} to be exclusive" if what == "exclusive" else f"Ask {name} for their number"


def _ask_refusal(state: GameState, intent: dict[str, Any]) -> str:
    """
    Why an ask the catalogue does not offer is refused: their stage's reason
    first ("You already have Kai's number."), else past this episode's asks,
    "Give it a while" (spec §6.4, §10.6).
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
        from engine.social import plans

        return plans.ask_refusal(state, pid)
    return relationships.ask_stage_refusal(state, pid, what) or relationships.ask_refusal(state, pid, what)


def _offered_asks(state: GameState, t: dict[str, Any]) -> list[str]:
    """The asks the catalogue offers in thread ``t`` now (the `ask` verb's rule; the person still decides)."""
    if not is_open(t) or apps.gone(state, t["pid"]):
        return []
    offered = [what for what in relationships.ask_kinds(state, t["pid"])      # a stage ask; T18: two at once
               if not relationships.ask_refusal(state, t["pid"], what)]
    from engine.social import media

    refusals = {k: media.ask_refusal(state, t["pid"], t["thread_id"], k) for k in MEDIA_KINDS}
    offered += [k for k, why in refusals.items() if not why]
    from engine.social import plans

    if places.venue_ids() and not plans.ask_refusal(state, t["pid"]):
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
            if k not in stage_asks or relationships.ask_ready(state, pid, k)]


@phone_verb("ask", payload={"what": ArgSpec("enum", ASKS, required=True),
                            "kind": ArgSpec("enum", PLAN_KINDS), "venue": ArgSpec("enum"),
                            "when": ArgSpec("enum", PLAN_WHENS)}, skill="social_ask",
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
                      extra={"what": tuple(k for k in ASKS if k in kinds),
                             "venue": tuple(places.venue_ids()) if MEET_ASK in kinds else ()})


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
        view["declined"] = "not_yet" if request.get("why") in relationships.NOT_YET_WHYS else "no"
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
    rows.sort(key=lambda t: (-last_at(t), t["thread_id"]))
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
        out.append(_client_row(state, row))
    return out


def _client_row(state: GameState, row: dict[str, Any]) -> dict[str, Any]:
    """A notification as the client reads it: its name added, and the engine's own `promise_id` (a sleep's
    wake rule, T11) left out, so the section's rows keep their shape."""
    out = {k: v for k, v in row.items() if k != "promise_id"}
    out["name"] = _name(state, str(row.get("pid") or ""))
    return out


def latest_notification(state: GameState, thread_id: str) -> Optional[dict[str, Any]]:
    """The newest notification of ``thread_id`` as the `notifications` section shows it, or None (§17.3's
    `phone_message` push carries it)."""
    t = thread(state, thread_id)
    if t is not None and not matching.listed(t):
        return None
    for row in reversed(state.social.get("notifications") or []):
        if str(row.get("thread_id") or "") == thread_id:
            return _client_row(state, row)
    return None


@section("open_thread", time_varying=True)
def _open_thread_section(state: GameState, session: Any) -> Optional[dict[str, Any]]:
    """The thread the player last opened: its last `social.state_messages` messages (one screen), or null.
    When state holds fewer than a screen and the archive holds more (a closed conversation's messages
    leave state at the save, `archive.keep_for`), the screen is filled from the archive's end
    (`archive.page`, v0.23.0 T9 fix round 2)."""
    t = thread(state, str(state.social.get("open_thread") or ""))
    if t is None or not matching.listed(t):
        return None
    limit = int(social.setting("state_messages", 8))
    messages = [m for m in t.get("messages") or [] if shown(m)]
    views = [_message_view(state, t, m) for m in messages[-limit:]]
    archived = int(t.get("archived") or 0)
    if len(messages) < limit and archived > 0 and session is not None:
        from engine.social import archive   # lazily: archive imports this module

        try:
            directory = archive.save_dir(session)
        except ValueError:
            directory = None
        if directory is not None:
            page = archive.page(directory, state, t["thread_id"], "", limit)
            views = list(reversed(page["messages"]))
    return {"thread_id": t["thread_id"], "app": t["app"], "pid": t["pid"], "name": _name(state, t["pid"]),
            "open": not t.get("closed"), "typing": _typing_shown(t, _typing(session)),
            "messages": views,
            # Older ones to page through (GET /api/phone/thread): past the limit, or archived.
            "more": len(messages) > limit or archived > 0}


# The person's side of a conversation (the `read` and `episode_lapse` handlers, the `social_episode`
# kind, the daily initiations) lives in engine/social/convo.py, which imports this module: loaded
# here too, so a queued read always finds its handler.
from engine.social import convo  # noqa: E402,F401  (v0.23.0 T3)
