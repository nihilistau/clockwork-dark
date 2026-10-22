"""
Promises and sign-offs (v0.23.0 spec §5).

"Message me at work", "I'll text you in the morning", "talk later": each is a
tracked ENGINE commitment, a row in ``state.social["promises"]`` (§5.1)
written only by the ``social_promise`` effect (rule 3):

    {id: "pr<n>", pid, by: person|player, window, opens_at, closes_at, about,
     made_at, status: open|kept|broken|void, fallback}

**How one is made (§5.2; rule 1: never trusted from model text).**
- The player's chip, the phone verb ``sign_off {who: me|you, window}``
  ("Talk later"): their line is sent, the promise recorded, and the person's
  reply signs the conversation off.
- The person's own sign-off decision (``convo._maybe_promise``): their
  archetype's ``promise_prob``, drawn on SOCIAL_CONVO; recorded BEFORE voicing.
- A model's ``promise`` proposal (``relationships.yaml`` ``proposals:``),
  legal only while the episode is winding or signed off, accepted when the
  window resolves within ``max_ahead_hours``.
- With no model, ``promises.yaml`` ``phrases:`` matched in the player's own
  message (``phrase_match``): a pending request (``people[pid]["promise_asked"]``)
  the person's next decision accepts (``accept_asked``).

**Who the window belongs to (m4).** ``windows.owner_of``: the sender's
schedule, but ``at_work`` the receiver's. A window that does not exist for
them resolves to their next free band, worded truthfully ("after work, so
tomorrow morning").

**Kept (§5.3).** The person's: a ``promise_due`` event inside the window
lands their ``promised_message`` (an initiation with a reason); withdrawn
(``void``) only if they leave or the relationship ends; no ghost is drawn
while one is open (``convo._ghost_protected``). The player's: any message of
theirs to that person inside the window keeps it (trust ``kept_trust``,
openness ``promise_kept``); silence until ``closes_at + grace_minutes``
breaks it (``promise_close``: trust and warmth ``broken``, openness
``broken_promise``, and the person's next reply carries it once).

A window already open when a promise is made is its NEXT occurrence (a promise names a later time;
T9 fix round 1). Closed rows past `closed_kept` a person are forgotten at compaction
(`forget_closed`), tallied on the person.

``wait {until: promise:<id>}`` jumps to it (engine/social/turn.py). Every
number is ``promises.yaml``'s (rule 10; unmeasured until T9).
"""

from __future__ import annotations

import dataclasses
import logging
from typing import Any, Optional

from engine import social
from engine.game.effects import EffectContext, apply_effect, effect_kind
from engine.game.intents import IntentVerb
from engine.game.rng import SOCIAL_CONVO
from engine.game.state import GameState
from engine.social import apps, behaviour, events, growth, messaging, relationships, windows
from engine.social.intents import ArgSpec, phone_verb
from engine.social.kinds import recorded
from engine.social.payload import section

logger = logging.getLogger(__name__)

#: Who keeps a promise: the person writes in the window, or the player does.
BY: tuple[str, ...] = ("person", "player")
#: A promise's states (§5.1).
STATUSES: tuple[str, ...] = ("open", "kept", "broken", "void")
#: The `social_promise` ops and the status each closing op sets.
OPS: tuple[tuple[str, str], ...] = (("make", "open"), ("land", "open"), ("keep", "kept"), ("break", "broken"),
                                     ("void", "void"), ("forget", ""))
#: The windows a chip, a proposal or a phrase may name (spec §5.2; `weekend`, `later` and `at:<hour>`
#: resolve, but no chip offers them).
CHIP_WINDOWS: tuple[str, ...] = ("lunch", "after_work", "tonight", "morning", "at_work")
#: The chip's two sides: "I'll message you ..." (the player promises) and "Message me ..." (the person does).
WHO: tuple[str, ...] = ("me", "you")
#: The person's own sign-off promise, by preference: the first that resolves for them in reach.
SIGN_OFF_WINDOWS: tuple[str, ...] = ("after_work", "tonight", "morning")
#: The refusal of a window too far ahead (the chip's, a proposal's).
TOO_FAR = "That's too far off to promise."
#: How many closed promises the payload still lists (newest first), beside the open ones.
SHOWN_CLOSED = 5

_DAY_NAMES: dict[str, str] = {"mon": "Monday", "tue": "Tuesday", "wed": "Wednesday", "thu": "Thursday",
                              "fri": "Friday", "sat": "Saturday", "sun": "Sunday"}


def _data() -> dict[str, Any]:
    return social.data("promises")


# -- load-time check (promises.yaml) ------------------------------------------------------------------


def _fault(key: str, message: str) -> ValueError:
    return ValueError(f"social: promises.yaml: {key}: {message}")


def _is_num(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def check_data(data: dict[str, Any]) -> None:
    """promises.yaml whole (spec §5): every key the engine reads, each the shape it reads. A ValueError
    naming the file and the key."""
    for key in ("later_min_hours", "max_ahead_hours", "grace_minutes"):
        if not _is_num(data.get(key)) or data[key] < 0:
            raise _fault(key, f"must be a number 0 or more, not {data.get(key)!r}")
    closed = data.get("closed_kept")
    if not isinstance(closed, int) or isinstance(closed, bool) or closed < 0:
        raise _fault("closed_kept", f"must be a whole number 0 or more, not {closed!r}")
    if not isinstance(data.get("kept_trust"), int) or isinstance(data.get("kept_trust"), bool) or data["kept_trust"] < 0:
        raise _fault("kept_trust", "must be a whole number 0 or more")
    broken = data.get("broken")
    if not isinstance(broken, dict) or set(broken) != {"trust", "warmth"} or not all(
            isinstance(v, int) and not isinstance(v, bool) and v <= 0 for v in broken.values()):
        raise _fault("broken", "must be {trust, warmth}, each a whole number 0 or less")
    reason = data.get("broken_reason")
    if not isinstance(reason, str) or "{window}" not in reason:
        raise _fault("broken_reason", "must be the engine's words, naming {window}")
    phrases = data.get("phrases")
    if not isinstance(phrases, dict) or set(phrases) != set(WHO):
        raise _fault("phrases", f"must be a mapping of {', '.join(WHO)} to windows")
    for who, table in phrases.items():
        if not isinstance(table, dict):
            raise _fault(f"phrases.{who}", "must be a mapping of window to phrases")
        for window, rows in table.items():
            if window not in CHIP_WINDOWS:
                raise _fault(f"phrases.{who}.{window}", f"is not one of {', '.join(CHIP_WINDOWS)}")
            if not isinstance(rows, list) or not rows or not all(isinstance(r, str) and r.strip() for r in rows):
                raise _fault(f"phrases.{who}.{window}", "must be a list of phrases")
    words = data.get("words")
    if not isinstance(words, dict):
        raise _fault("words", "must be a mapping of window to words")
    for window in (*windows.PROMISE_WINDOWS, "fallback"):
        if not isinstance(words.get(window), str) or not words[window].strip():
            raise _fault(f"words.{window}", "must be the window's words, a non-empty line")
    if "{window}" not in words["fallback"] or "{when}" not in words["fallback"]:
        raise _fault("words.fallback", "must name {window} and {when}")


# -- reading ------------------------------------------------------------------------------------------


def _rows(state: GameState) -> dict[str, dict[str, Any]]:
    return state.social.setdefault("promises", {})


def _read_rows(state: GameState) -> dict[str, dict[str, Any]]:
    """The rows, for a read path: never creates the key (I14)."""
    return (state.social or {}).get("promises") or {}


def open_by(state: GameState, pid: str, by: Optional[str] = None) -> list[dict[str, Any]]:
    """`pid`'s open promises (of one side when `by` is given), soonest first. Reads only."""
    return sorted((r for r in _read_rows(state).values()
                   if r["pid"] == pid and r["status"] == "open" and (by is None or r["by"] == by)),
                  key=lambda r: (r["opens_at"], r["id"]))


def span_for(state: GameState, pid: str, *, by: str, window: str,
             at: float) -> Optional[tuple[float, float, bool]]:
    """`(opens_at, closes_at, fallback)` the window resolves to for this speaker, or None when it opens
    further ahead than `max_ahead_hours`. Draws nothing, writes nothing."""
    who = windows.owner_of(window, by=by, pid=pid)
    fallback = False
    try:                                                 # `later` and the fallback read `first_free` (review M4)
        span = windows.resolve(state, who, window, at)
        if span is None:                                 # no such window for them: their next free band (§5.1)
            span, fallback = windows.first_free(state, who, at), True
        if span[0] <= at and window != "later":
            # A promise names a LATER time (§3.5 item 2): a window already open now is its next
            # occurrence -- "lunch" said at lunch is tomorrow's (T9 fix round 1: a glance at work at
            # lunch promised the lunch it was in, fell due at once and looped through the hour).
            span = (windows.first_free(state, who, span[1]) if fallback
                    else windows.resolve(state, who, window, span[1]))
            if span is None:
                return None
    except ValueError:                                   # no free band in a week: nothing to promise into
        logger.warning("[social] No window to promise into (operation=span_for, pid=%s, window=%s)", pid, window)
        return None
    if span[0] - at > float(_data().get("max_ahead_hours", 48)):
        return None
    return span[0], span[1], fallback


def _when_words(at: float, now: float) -> str:
    """When `at` is, relative to `now`, in words ("tomorrow morning", "yesterday"): no number reaches
    the player."""
    if at <= now:
        back = int(now // 24) - int(at // 24)
        if back == 0:
            return "earlier today"
        if back == 1:
            return "yesterday"
        return f"on {_DAY_NAMES[behaviour.WEEKDAYS[int(at // 24) % 7]]}"
    hour = at % 24
    part = "morning" if hour < 12 else "afternoon" if hour < 17 else "evening" if hour < 21 else "night"
    days = int(at // 24) - int(now // 24)
    if days == 0:
        return "tonight" if part == "night" else f"this {part}"
    if days == 1:
        return f"tomorrow {part}"
    return f"on {_DAY_NAMES[behaviour.WEEKDAYS[int(at // 24) % 7]]} {part}"


def window_words(row: dict[str, Any], *, speaker: str = "", now: Optional[float] = None) -> str:
    """How a promise's window reads (spec §5.1). A fallback window says when it really is ("after work,
    so tomorrow morning"). `speaker` ("person" or "player", whoever says it) is kept for the voice
    (T7); the shipped words read the same from either side."""
    words = _data().get("words") or {}
    window = str(row.get("window") or "")
    if window.startswith("at:"):
        hour = int(float(window.split(":", 1)[1])) % 24
        base = f"at {hour % 12 or 12}{'am' if hour < 12 else 'pm'}"
    else:
        base = str(words.get(window, window.replace("_", " ")))
    if not row.get("fallback"):
        return base
    since = float(row.get("made_at", 0.0) if now is None else now)
    when = "now" if float(row["opens_at"]) <= since else _when_words(float(row["opens_at"]), since)
    return str(words.get("fallback", "{window}, so {when}")).format(window=base, when=when)


def phrase_match(text: str) -> Optional[tuple[str, str]]:
    """`(who, window)` for a promise stated in the player's own words (`promises.yaml` `phrases:`), or
    None: a whole phrase, case-folded, not asked (agreement.py's matcher). `who` is `me` (the player
    promises) or `you` (the person is asked to)."""
    from engine.social import agreement   # lazily: agreement reads the story's phrase lists

    for who in ("you", "me"):
        for window, rows in ((_data().get("phrases") or {}).get(who) or {}).items():
            if agreement.stated(str(text or ""), rows, negatable=True):
                return who, str(window)
    return None


# -- making one ---------------------------------------------------------------------------------------


def make(state: GameState, pid: str, *, by: str, window: str, about: str = "",
         at: Optional[float] = None) -> Optional[dict[str, Any]]:
    """Record a promise (a chip, a sign-off decision, an accepted proposal or a phrase); the row. None if
    its window opens too far ahead. An open promise of the same side and window whose span overlaps is
    the SAME promise, returned as it is (review I1): a chip's line caught again as a phrase, a decision
    made later than the chip (the window clipped to a later start), a model proposing it twice."""
    now = state.world_clock_hours if at is None else float(at)
    span = span_for(state, pid, by=by, window=window, at=now)
    if span is None:
        return None
    for row in open_by(state, pid, by=by):
        if row["window"] == window and row["opens_at"] < span[1] and span[0] < row["closes_at"]:
            return dict(row)
    result = apply_effect(state, {"type": "social_promise", "op": "make", "pid": pid, "by": by, "window": window,
                                  "opens_at": span[0], "closes_at": span[1], "about": str(about or "")[:100],
                                  "made_at": now, "fallback": span[2]})
    return result.get("promise")


@effect_kind("social_promise")
@recorded
def _e_promise(state: GameState, effect: dict[str, Any], ctx: EffectContext) -> dict[str, Any]:
    """
    Engine-only: one promise (spec §5.1). ``make`` writes the row and queues how it is judged: a
    person's ``promise_due`` inside the window (their message, kept), a player's ``promise_close``
    at the window's close plus the grace. ``keep``, ``break`` and ``void`` close an open one.
    """
    if not state.social:
        return {"type": "social_promise", "ok": False, "text": "no social slice"}
    rows = _rows(state)
    op = str(effect.get("op") or "")
    if op not in dict(OPS):
        return {"type": "social_promise", "ok": False, "text": f"unknown op {op!r}"}
    if op == "make":
        by = str(effect.get("by") or "")
        if by not in BY:
            return {"type": "social_promise", "ok": False, "text": f"{by!r} is not one of {', '.join(BY)}"}
        counters = state.social.setdefault("counters", {})
        counters["promise"] = int(counters.get("promise", 0)) + 1
        row = {"id": f"pr{counters['promise']}", "pid": str(effect["pid"]), "by": by,
               "window": str(effect["window"]), "opens_at": float(effect["opens_at"]),
               "closes_at": float(effect["closes_at"]), "about": str(effect.get("about") or "")[:100],
               "made_at": float(effect["made_at"]), "status": "open", "fallback": bool(effect.get("fallback"))}
        rows[row["id"]] = row
        if row["by"] == "person":                        # kept: their message lands inside the window (§5.3)
            rng = behaviour.person_rng(state, SOCIAL_CONVO, row["pid"])
            due_at = row["opens_at"] + rng.random() * max(0.0, min(1.0, row["closes_at"] - row["opens_at"]))
            events.push(state, due_at, row["pid"], "promise_due", promise_id=row["id"])
        else:                                            # the player's: judged at the window's close + grace
            grace = float(_data().get("grace_minutes", 60)) / 60.0
            events.push(state, row["closes_at"] + grace, row["pid"], "promise_close", promise_id=row["id"])
        return {"type": "social_promise", "ok": True, "text": f"promise {row['id']} made", "promise": dict(row),
                "save_reason": "promise"}
    if op == "forget":                                   # bounded state (`forget_closed`): a closed row
        row = rows.get(str(effect.get("promise_id") or ""))
        if row is None or row["status"] == "open":
            return {"type": "social_promise", "ok": False, "text": "no closed promise"}
        person = state.social.setdefault("people", {}).setdefault(row["pid"], {})
        tally = person.setdefault("promises_closed", {}).setdefault(row["by"], {})
        tally[row["status"]] = int(tally.get(row["status"], 0)) + 1
        del rows[row["id"]]
        return {"type": "social_promise", "ok": True, "text": f"promise {row['id']} forgotten"}
    row = rows.get(str(effect.get("promise_id") or ""))
    if row is None or row["status"] != "open":
        return {"type": "social_promise", "ok": False, "text": "no open promise"}
    if op == "land":                                     # their promised message landed, not yet written
        row["message_id"] = str(effect.get("message_id") or "")
        return {"type": "social_promise", "ok": True, "text": f"promise {row['id']} landed", "promise": dict(row)}
    row["status"] = dict(OPS)[op]
    return {"type": "social_promise", "ok": True, "text": f"promise {row['id']} {row['status']}",
            "promise": dict(row)}


# -- bounded state (spec §17.2) ---------------------------------------------------------------------------


def _still_read(state: GameState) -> set[str]:
    """The closed rows a reader still needs: the broken promise a person's next reply carries
    (`broken_promise`), any a queued event or a due message names, any an open episode or one due a recap
    names (`promise_id`) or that was made inside one (`memory._promise_words`), and the newest
    `SHOWN_CLOSED` (the payload's list)."""
    slice_ = state.social or {}
    rows = _read_rows(state)
    named: set[str] = set()
    spans: list[tuple[str, float, float]] = []
    for pid, person in (slice_.get("people") or {}).items():
        if not isinstance(person, dict):
            continue
        named.add(str(person.get("broken_promise") or ""))
        episodes = [person.get("episode") or {}, *(person.get("recap_due") or [])]
        for ep in episodes:
            if not ep:
                continue
            named.add(str(ep.get("promise_id") or ""))
            end = ep.get("closed_at") if ep.get("closed_at") is not None else ep.get("last_at")
            if ep.get("started_at") is not None:
                spans.append((str(pid), float(ep["started_at"]), float(end if end is not None else 1e18)))
    named |= {str(e.get("promise_id") or "") for e in slice_.get("queue") or []}
    named |= {str((m.get("decision") or {}).get("promise_id") or "")
              for t in (slice_.get("threads") or {}).values() for m in t.get("messages") or []
              if m.get("voiced") is False}
    for row in rows.values():
        if any(row["pid"] == pid and start - 1e-9 <= float(row["made_at"]) <= end + 1e-9 for pid, start, end in spans):
            named.add(row["id"])
    closed = sorted((r for r in rows.values() if r["status"] != "open"), key=lambda r: (r["made_at"], r["id"]),
                    reverse=True)
    named |= {r["id"] for r in closed[:SHOWN_CLOSED]}
    return named


def forget_closed(state: GameState) -> int:
    """
    Bounded state (spec §17.2, v0.23.0 T9 fix round 1), made at every save (`saves.compact`): per person,
    closed rows (kept, broken, void) past the newest `promises.yaml` `closed_kept` leave state through
    `social_promise` `op: forget` (rule 3), oldest first, each tallied on the person
    (`promises_closed[by][status]`). Open rows stay, and so does every closed row a reader still needs
    (`_still_read`). How many left.
    """
    rows = _read_rows(state)
    if not rows:
        return 0
    keep = max(0, int(_data().get("closed_kept", 3)))
    needed = _still_read(state)
    by_person: dict[str, list[dict[str, Any]]] = {}
    for row in rows.values():
        if row["status"] != "open":
            by_person.setdefault(row["pid"], []).append(row)
    gone = 0
    for pid in sorted(by_person):
        closed = sorted(by_person[pid], key=lambda r: (r["made_at"], r["id"]))
        for row in closed[:max(0, len(closed) - keep)]:
            if row["id"] in needed:
                continue
            gone += bool(apply_effect(state, {"type": "social_promise", "op": "forget",
                                              "promise_id": row["id"]}).get("ok"))
    return gone


# -- keeping them (§5.3) ----------------------------------------------------------------------------------


def on_player_message(state: GameState, pid: str, at: float) -> None:
    """A player's message in any of that person's threads inside a window keeps their promise (§5.3)
    (inside `social_message`'s handler). The message that made it -- the sign-off chip's own line, at
    the promise's minute -- does not."""
    for row in open_by(state, pid, by="player"):
        if row["opens_at"] <= at <= row["closes_at"] and at > row["made_at"]:
            apply_effect(state, {"type": "social_promise", "op": "keep", "promise_id": row["id"]})
            relationships.apply_regard_exact(state, pid, trust=int(_data().get("kept_trust", 1)))
            growth.gain(state, pid, "promise_kept")


def note_player_text(state: GameState, pid: str, text: str, at: float) -> None:
    """With no model (§5.2): a promise stated in the player's message is a pending request
    (`people[pid]["promise_asked"]`, inside `social_message`'s handler), accepted at the person's next
    decision (`accept_asked`)."""
    found = phrase_match(text)
    if found is None:
        return
    person = state.social["people"].setdefault(pid, {})
    person["promise_asked"] = {"who": found[0], "window": found[1], "at": float(at)}


def accept_asked(state: GameState, pid: str, at: float) -> Optional[dict[str, Any]]:
    """The person's decision accepts the player's pending promise request (inside a social handler): the
    promise made, the request cleared. None when there is none, or it no longer resolves in reach."""
    person = (state.social.get("people") or {}).get(pid) or {}
    asked = person.get("promise_asked")
    if not isinstance(asked, dict):
        return None
    apply_effect(state, {"type": "social_person", "pid": pid, "set": {"promise_asked": None}})
    if at - float(asked.get("at", at)) > float(_data().get("max_ahead_hours", 48)):
        return None
    by = "player" if asked.get("who") == "me" else "person"
    return make(state, pid, by=by, window=str(asked.get("window") or ""), at=at)


def _gone(state: GameState, pid: str) -> bool:
    return apps.gone(state, pid) or relationships.ended(state, pid)


@events.handles("promise_due")
def _on_promise_due(state: GameState, event: dict[str, Any]) -> dict[str, Any]:
    """The person keeps their promise: inside the window their `promised_message` is decided and due at
    once, a conversation opened for it (an initiation with a reason, §4.7). Void if they have gone. It is
    KEPT when that message is voiced (`on_voiced`, review M2), void if it never lands or is withdrawn."""
    from engine.social import convo   # lazily: convo imports this module

    row = _rows(state).get(str(event.get("promise_id") or ""))
    pid = str(event["pid"])
    if row is None or row["status"] != "open":
        return {"ok": False, "why": "no open promise"}
    thread_id = messaging.thread_for(state, pid)
    if _gone(state, pid) or thread_id is None:
        apply_effect(state, {"type": "social_promise", "op": "void", "promise_id": row["id"]})
        return {"ok": True, "void": row["id"]}
    at = float(event["at"])
    ep = convo.episode(state, pid)
    if ep is not None and ep["end"] == "signed_off":     # the conversation they signed off from is over
        apply_effect(state, {"type": "social_episode", "op": "close", "pid": pid, "at": at})
        ep = None
    if ep is None:
        apply_effect(state, {"type": "social_episode", "op": "open", "pid": pid, "thread_id": thread_id,
                             "at": at, "kind": "chat"})
    decision = convo.decide(state, pid, thread_id, at, situation="promised_message")
    if not decision.promise_id:                          # a promise its own decision made is named (review M3)
        decision = dataclasses.replace(decision, promise_id=row["id"])
    messaging.queue_due(state, pid, thread_id, decision, at, promise_id=row["id"])
    return {"ok": True, "due": row["id"]}


def on_landed(state: GameState, promise_id: str, message_id: str) -> None:
    """Their promised message landed (inside its due event's handler): the promise remembers it; or, with
    no message (`message_id` ""), it could not land and the promise is void."""
    op = {"op": "land", "message_id": message_id} if message_id else {"op": "void"}
    apply_effect(state, {"type": "social_promise", "promise_id": promise_id, **op})


def on_voiced(state: GameState, message_ids: Any, *, withdrawn: bool = False) -> None:
    """Messages committed (inside `social_voiced`'s handler): an open promise whose landed message is
    among them is kept (openness `promise_kept`), or void when the message was withdrawn unvoiced."""
    ids = {str(m) for m in message_ids}
    for row in [r for r in _read_rows(state).values()
                if r["status"] == "open" and r["by"] == "person" and r.get("message_id") in ids]:
        apply_effect(state, {"type": "social_promise", "op": "void" if withdrawn else "keep", "promise_id": row["id"]})
        if not withdrawn:
            growth.gain(state, row["pid"], "promise_kept")


@events.handles("promise_close")
def _on_promise_close(state: GameState, event: dict[str, Any]) -> dict[str, Any]:
    """The player's window closed (plus the grace) with no message to them: broken -- trust, warmth and
    openness lost, and the person's next reply carries it once. Void if the person has gone."""
    row = _rows(state).get(str(event.get("promise_id") or ""))
    if row is None or row["status"] != "open":
        return {"ok": False, "why": "no open promise"}
    pid = row["pid"]
    if _gone(state, pid):
        apply_effect(state, {"type": "social_promise", "op": "void", "promise_id": row["id"]})
        return {"ok": True, "void": row["id"]}
    apply_effect(state, {"type": "social_promise", "op": "break", "promise_id": row["id"]})
    cost = _data().get("broken") or {}
    relationships.apply_regard_exact(state, pid, trust=int(cost.get("trust", 0)), warmth=int(cost.get("warmth", 0)))
    growth.loss(state, pid, "broken_promise")
    apply_effect(state, {"type": "social_person", "pid": pid,
                         "set": {"broken_promise": row["id"]}})        # the next decision carries it once
    from engine.social import memory   # lazily: memory reads agreement, which reads population

    # They remember it (spec §7.3): a follow-up their next reply can raise, due now.
    due = float(event.get("at", state.world_clock_hours))
    memory.add_open(state, pid, {"kind": "followup", "by": "person", "due_at": due,
                                 # From their side, a thing to ask after ("How did your plans tonight go?",
                                 # T7 review M2): the broken promise itself is the next reply's reason.
                                 "about": f"your plans {window_words(row, speaker='player')}"})
    return {"ok": True, "broken": row["id"]}


def broken_reason(state: GameState, pid: str) -> str:
    """The engine's words for the broken promise the person's next reply carries ("" when none)."""
    pr = ((state.social.get("people") or {}).get(pid) or {}).get("broken_promise")
    row = _read_rows(state).get(str(pr or ""))
    if row is None:
        return ""
    return str(_data().get("broken_reason", "")).format(window=window_words(row, speaker="player"))


# -- the chip: `sign_off` (§5.2 route 1) ----------------------------------------------------------------


def _default_line(who: str, words: str) -> str:
    return f"Talk later — I'll message you {words}" if who == "me" else f"Message me {words}?"


def sign_off(state: GameState, thread_id: str, who: str, window: str, text: str = "") -> dict[str, Any]:
    """
    The player's "Talk later": the promise recorded (refused, with nothing sent, if its window is out of
    reach), the conversation marked as theirs to end -- so the person's reply signs it off -- and their
    line (or the default) sent, its time spent through `messaging.send` (rule 2).
    """
    from engine.social import convo   # lazily: convo imports this module

    t = messaging.thread(state, thread_id)
    if t is None or not messaging.is_open(t):
        return {"ok": False, "error": "There's no such conversation."}
    pid = str(t["pid"])
    if convo.episode(state, pid) is None:
        return {"ok": False, "error": f"You're not talking with {messaging._name(state, pid)} right now."}
    if who not in WHO or window not in CHIP_WINDOWS:
        return {"ok": False, "error": "That isn't a promise you can make."}
    by = "player" if who == "me" else "person"
    row = make(state, pid, by=by, window=window)
    if row is None:
        return {"ok": False, "error": TOO_FAR}
    ep = convo.episode(state, pid) or {}
    if ep.get("end") != "signed_off":
        reason = str((social.data("conversation").get("reasons") or {}).get("player", ""))
        apply_effect(state, {"type": "social_episode", "op": "end", "pid": pid, "at": state.world_clock_hours,
                             "end": "winding", "reason": reason, "by": "player", "promise_id": row["id"]})
    line = str(text or "").strip() or _default_line(who, window_words(row, speaker="player"))
    sent = messaging.send(state, thread_id, "text", line)
    if not sent.get("ok"):
        apply_effect(state, {"type": "social_promise", "op": "void", "promise_id": row["id"]})
        return sent
    if (state.social["people"].get(pid) or {}).get("promise_asked"):   # the chip's own line: already recorded (I1)
        apply_effect(state, {"type": "social_person", "pid": pid, "set": {"promise_asked": None}})
    return {**sent, "promise_id": row["id"], "by": row["by"], "window": row["window"]}


@phone_verb("sign_off", payload={"who": ArgSpec("enum", WHO, required=True),
                                 "window": ArgSpec("enum", CHIP_WINDOWS, required=True)},
            skill="social_sign_off", takes_text=True, text_cap="social.max_text_chars",
            label=lambda s, i: "Talk later")
def _sign_off_verb(state: GameState) -> Optional[IntentVerb]:
    """Legal for a thread whose person the player is talking with now (an open episode)."""
    from engine.social import convo   # lazily: convo imports this module

    rows = [t for t in (state.social.get("threads") or {}).values()
            if messaging.is_open(t) and convo.episode(state, str(t["pid"])) is not None]
    if not rows:
        return None
    return IntentVerb("sign_off", options=tuple((t["thread_id"], messaging._thread_label(state, t)) for t in rows))


# -- the payload (§5.3: what the player sees) -----------------------------------------------------------


@section("promises", time_varying=True)
def _promises_section(state: GameState, session: Any) -> list[dict[str, Any]]:
    """Open promises, soonest first, then the last few closed: words only, never a number (lesson 7)."""
    now = state.world_clock_hours
    rows = list(_read_rows(state).values())
    shown = sorted((r for r in rows if r["status"] == "open"), key=lambda r: (r["opens_at"], r["id"]))
    closed = sorted((r for r in rows if r["status"] != "open"), key=lambda r: (r["made_at"], r["id"]), reverse=True)
    out = []
    for row in [*shown, *closed[:SHOWN_CLOSED]]:
        out.append({"id": row["id"], "pid": row["pid"], "name": messaging._name(state, row["pid"]),
                    "by": row["by"], "window_words": window_words(row, speaker=row["by"]),
                    "opens_at_words": ("now" if row["status"] == "open" and float(row["opens_at"]) <= now
                                       else _when_words(float(row["opens_at"]), now)),
                    "status": row["status"]})
    return out
