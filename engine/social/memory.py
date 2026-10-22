"""
Memory and context (v0.23.0 spec §7; v0.22.0 §12): what each PERSON remembers.

ONE MEMORY PER PERSON, not per thread (§7.1): moving from the dating app to
Texts or Natter keeps the whole history (§15.5). Everything lives at
``people[pid]["memory"]`` (``fresh()``'s shape), and nothing crosses from one
person to another:

- **current**: the open conversation's messages, either side, from EVERY app,
  verbatim (``note_spoken``, called from ``social_message``'s handler for the
  player and from ``social_voiced``'s for them), bounded at
  ``memory.verbatim`` bubbles, the oldest dropped.
- **bridge**: the last ``memory.bridge_bubbles`` of the previous episode,
  verbatim: "how you left it".
- **episodes**: closed episodes' recaps ``{id, kind, where, from_at, to_at,
  recap, topics, end_reason}``, at most ``memory.episodes_kept``; past it the
  oldest is folded into ``story``.
- **story**: the relationship so far, at most ``memory.story_words``, losing
  its OLDEST sentences first (``cap_story``).
- **open**: follow-ups (§7.3), each ``{id, kind, about, due_at, by}``, at most
  ``memory.open_max``, the oldest closed first.
- **canon**, **knows**, **told**, **history**: v0.22's rows, moved under the
  person's memory with the same bounds (``social.canon_max``, ``knows_max``,
  ``history_max``); canon that leaves state is folded into ``story``. A
  v0.22.0 person row that still carries them at its top level is read there
  (``part``) and moved under ``memory`` by the first write; a v0.22.0 save is migrated at load
  (``engine/social/migrate.py``), so only a hand-built row still carries them.

Thread ``summary`` and ``summary_through`` are retired: nothing writes them
(a v0.22.0 save's are joined into the person's story at load, ``engine/social/migrate.py``).

Every write is a ``social_memory`` effect (rule 3): ``op: canon | knows | told
| spoken | recap | fold | open_add | open_close``, each bounded in its handler.

RECAPS (§7.2). An episode that closes joins the person's ``recap_due``
(``convo._close``). The voicing pass runs ONE recap job at a time
(``voicer._recap_one``), in v0.22's order: the view read under the turn lock
(``recap_view``: the episode's messages from ``current`` and the person's
threads in state, never a file), the archive read off the lock
(``with_archive``) for messages the spill already took, the recap written
holding no lock (``write_recap``: ``summarize_with`` over
``prompts/episode_recap.md``, one utility call), then committed under the lock
(``commit_recap``), refused as stale when its ``recap_due`` row is gone. A
person whose ``episodes`` are full first gets a FOLD job (``fold_view``,
``write_fold``, ``commit_fold``): the oldest recap folded into ``story`` by the
same call, refused as stale when the story or the oldest episode moved. With
no model the deterministic fallbacks write both (``recap_fallback``,
``cap_story``). Committed recaps leave ``recap_due``, so the backlog stays
bounded by what play has not yet recapped (``social.recap_due_max``).

The summary function is a UTILITY call on the ``small`` profile with
reasoning off (``production_summary_fn``, pre-flight F10: ONE argument, the
messages), degradable: a busy utility lane is an exception the summarizer
swallows into the fallback.

The budget (v0.23.0 spec §7.4, ``budgeted``, T7): the voice prompt's parts
(``BLOCK_PARTS``) trimmed to the call's window -- older recaps, the story,
canon, history, then the conversation, oldest first, each to its floor --
never ``now``, ``who_now``, ``open`` or ``bridge`` (``NEVER_TRIMMED``).
"""

from __future__ import annotations

import copy
import logging
import re
from pathlib import Path
from typing import Any, Callable, Optional

from engine import social
from engine.game.effects import EffectContext, apply_effect, effect_kind
from engine.game.state import GameState
from engine.social.kinds import recorded

logger = logging.getLogger(__name__)

#: The summarizer's model function (pre-flight F10): the messages in, raw text out. The recap's too.
SummaryFn = Callable[[list[dict[str, Any]]], str]

#: `social_memory`'s operations.
OPS: tuple[str, ...] = ("canon", "knows", "told", "spoken", "recap", "fold", "open_add", "open_close", "shelve",
                        "restore")

#: The parts of a person's memory (§7.1), in `fresh()`'s order.
PARTS: tuple[str, ...] = ("current", "bridge", "episodes", "story", "open", "canon", "knows", "told", "history")

#: v0.22.0's per-person rows that moved under `memory` (a v0.22.0 save's are moved at load, engine/social/migrate.py;
#: still read at the top level for a hand-built row).
MOVED: tuple[str, ...] = ("canon", "knows", "told", "history")

#: The recap's prompt file, in the story's `prompts/` directory (spec §7.2).
RECAP_PROMPT = "episode_recap.md"

#: The heading in `episode_recap.md` above the story-so-far fold's instructions (the recap's are above it).
STORY_HEADING = "## The story so far"

#: The user block's label for an episode's messages, and for a folded episode's recap.
THIS_CONVERSATION = "THIS CONVERSATION"
EARLIER_CONVERSATION = "AN EARLIER CONVERSATION"

#: How the player is named in a rendered conversation.
YOU = "you"

#: The most messages one recap reads (the newest of the episode): one utility call's input stays bounded.
RECAP_MESSAGES_MAX = 80

#: How close two message times count as the same moment: `current` keeps `at` to four places
#: (`_stored_message`).
AT_EPS = 1e-4

#: How a media message reads in a rendered conversation, before its words.
MEDIA_MARKS: tuple[tuple[str, str], ...] = (("photo", "[photo]"), ("video", "[video]"), ("voice", "[voice note]"))

#: What a `current` row keeps of a message.
SPOKEN_KEYS: tuple[str, ...] = ("id", "thread_id", "from", "kind", "at", "bubbles", "transcript")

#: What a `recap_due` row keeps of a closed episode (convo._close): what a recap reads, nothing more.
DUE_KEYS: tuple[str, ...] = ("id", "kind", "thread_id", "location", "started_at", "last_at", "closed_at", "end",
                             "end_reason", "end_key", "promise_id", "topics", "band")

#: The voice prompt's budgeted parts (v0.23.0 spec §7.4, §13.2), one row per line where a part is trimmed,
#: oldest first: the persona; WHO YOU ARE NOW (`who_now`); YOUR STORY TOGETHER (`story`, then the
#: `episodes` recaps); WHAT YOU KNOW ABOUT THEM (`knows`); STILL OPEN (`open`); YOU AND THEM
#: (`you_and_them`, `canon`, `history`); THIS CONVERSATION (`bridge`, `current`); RIGHT NOW (`now`);
#: FORMAT (`format`).
BLOCK_PARTS: tuple[str, ...] = ("persona", "who_now", "story", "episodes", "knows", "open", "you_and_them",
                                "canon", "history", "bridge", "current", "now", "format")

#: The parts the budget never trims (§7.4): `now`, `who_now`, `open` and `bridge`, with the persona,
#: what they know, where the two of you stand and the format, which are fixed.
NEVER_TRIMMED: tuple[str, ...] = ("persona", "who_now", "knows", "open", "you_and_them", "bridge", "now",
                                  "format")

#: The recaps a trim keeps at least, and a degraded binding keeps at most (§7.4).
EPISODES_MIN = 3

#: The words a degraded binding's story is cut to before any other trim (§7.4, I7).
DEGRADED_STORY_WORDS = 120

#: The active story's `prompts/episode_recap.md`, split: (the recap's system prompt, the story fold's).
#: NULLED_ATTRIBUTES row; warmed by `caches._warm_recap_prompt`; read once into a local.
_RECAP_PROMPT_CACHE: Optional[tuple[str, str]] = None

#: Prompt paths already reported missing by `recap_prompt` (one WARNING per path, per process).
_PROMPT_MISSING_LOGGED: set[str] = set()


# -- settings -------------------------------------------------------------------------------------


def _setting(key: str, default: int) -> int:
    return int(social.setting(f"memory.{key}", default))


def _story_words() -> int:
    return max(20, _setting("story_words", 300))


def _recap_words() -> int:
    return max(10, _setting("recap_words", 70))


# -- words ----------------------------------------------------------------------------------------


def _clip_words(text: str, limit: int) -> str:
    words = str(text or "").split()
    return " ".join(words[:limit]) if len(words) > limit else " ".join(words)


def last_words(text: str, limit: int) -> str:
    """
    ``text`` held to ``limit`` words, losing its OLDEST material: the last
    ``limit`` words, then whatever runs before the first sentence end among
    them (no headless fragment), unless that would leave nothing.
    """
    words = str(text or "").split()
    if len(words) <= limit:
        return " ".join(words)
    tail = words[-limit:]
    for i, word in enumerate(tail[:-1]):
        if word.endswith((".", "!", "?")):
            return " ".join(tail[i + 1:])
    return " ".join(tail)


def fresh() -> dict[str, Any]:
    """An empty person memory (§7.1)."""
    return {"current": [], "bridge": [], "episodes": [], "story": "", "open": [],
            "canon": [], "knows": [], "told": [], "history": []}


def cap_story(text: str) -> str:
    """The story so far bounded to `memory.story_words`, keeping the NEWEST sentences (§7.2's fold fallback)."""
    return last_words(text, int(social.setting("memory.story_words", 300)))


def _join(items: list[str]) -> str:
    items = [str(i) for i in items if str(i).strip()]
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


# -- reading --------------------------------------------------------------------------------------


def part(person_row: dict[str, Any], key: str) -> Any:
    """
    One part of a person row's memory (READ ONLY): ``memory[key]``, else a
    v0.22.0 row's top-level copy of a part that moved (``MOVED``), else the
    part's empty value.
    """
    mem = person_row.get("memory") if isinstance(person_row, dict) else None
    if isinstance(mem, dict) and key in mem:
        return mem[key]
    if key in MOVED and isinstance(person_row, dict) and key in person_row:
        return person_row[key]
    return fresh()[key]


def person(state: GameState, pid: str) -> dict[str, Any]:
    """A person's whole memory (§7.1), a COPY (read-only): every part, empty for nobody known; every
    message and episode row in its full shape (state keeps them compact: `_stored_message`,
    `_stored_episode`)."""
    row = ((state.social or {}).get("people") or {}).get(pid) or {}
    out = {key: copy.deepcopy(part(row, key)) for key in PARTS}
    for key in ("current", "bridge"):
        out[key] = [full_message(m, pid) for m in out[key]]
    out["episodes"] = [{**_episode_defaults(), **e} for e in out["episodes"]]
    out["history"] = [full_history(h) for h in out["history"]]
    return out


def full_message(row: dict[str, Any], pid: str) -> dict[str, Any]:
    """A `current`/`bridge` row in its full shape (state keeps it compact, `_stored_message`): `thread_id`
    from its `app` and the person, `from` the person when it names nobody, `kind` `text` when it names none."""
    out = {"kind": "text", **row}
    if "thread_id" not in out and out.get("app"):
        out["thread_id"] = f"{out['app']}:{pid}"
    out.pop("app", None)
    out.setdefault("from", pid)
    return out


def full_history(row: dict[str, Any]) -> dict[str, Any]:
    """A history row with its in-game `day` (state keeps only `at`; v0.22.0 rows carry both)."""
    return {**row, "day": int(row["day"]) if row.get("day") is not None else int(float(row.get("at") or 0.0) // 24) + 1}


#: An episode row's parts a save leaves out at their default (`_stored_episode`; `person` puts them back).
EPISODE_DEFAULTS: tuple[tuple[str, Any], ...] = (("kind", "chat"), ("where", ""), ("topics", ()), ("end_reason", ""))


def _episode_defaults() -> dict[str, Any]:
    return {k: list(v) if isinstance(v, tuple) else v for k, v in EPISODE_DEFAULTS}


def _stored_message(message: dict[str, Any], pid: str) -> dict[str, Any]:
    """A message as `current` and `bridge` keep it (`full_message` puts the rest back): `SPOKEN_KEYS`
    only, an empty one left out, the thread as its `app` (the person is the row's owner), `from` only
    for the player, `kind` left out when `text`, `at` to four places (a third of a second)."""
    row = {k: copy.deepcopy(message.get(k)) for k in SPOKEN_KEYS if message.get(k) not in (None, "", [])}
    thread = str(row.pop("thread_id", "") or "")
    app, _, owner = thread.partition(":")
    if owner == pid:
        row["app"] = app
    elif thread:
        row["thread_id"] = thread                      # never expected: kept whole rather than misattributed
    if row.get("from") == pid:
        del row["from"]
    if row.get("kind") == "text":
        del row["kind"]
    if isinstance(row.get("at"), float):
        row["at"] = round(row["at"], 4)
    return row


def _stored_episode(row: dict[str, Any]) -> dict[str, Any]:
    """An `episodes` row as state keeps it (§7.1's shape): a part at its default left out."""
    episode = {"id": str(row["id"]), "kind": str(row.get("kind") or "chat"), "where": str(row.get("where") or ""),
               "from_at": row.get("from_at"), "to_at": row.get("to_at"),
               "recap": _clip_words(str(row.get("recap") or ""), _recap_words()),
               "topics": [str(t) for t in row.get("topics") or ()], "end_reason": str(row.get("end_reason") or "")}
    defaults = _episode_defaults()
    return {k: v for k, v in episode.items() if k not in defaults or v != defaults[k]}


def topic_rows(state: GameState, pid: str) -> list[dict[str, Any]]:
    """The person's drawn topic rows (`{id, kind, label}`), read-only."""
    from engine.social import growth

    return [{"id": str(r["id"]), "kind": str(r.get("kind") or ""), "label": str(r.get("label") or "")}
            for r in growth.topics_of(state, pid)]


def _writable(person_row: dict[str, Any]) -> dict[str, Any]:
    """The person's memory to write (INSIDE `social_memory` / `social_history` only): made on first
    write, every part present while the handler runs (`_prune` drops the empty ones after), a v0.22.0
    row's top-level parts moved under it."""
    mem = person_row.get("memory")
    if not isinstance(mem, dict):
        mem = person_row["memory"] = {}
    for key, empty in fresh().items():
        mem.setdefault(key, empty)
    for key in MOVED:
        if key in person_row:
            legacy = person_row.pop(key)
            if isinstance(legacy, list) and not mem[key]:
                mem[key] = legacy
    return mem


def _prune(person_row: dict[str, Any]) -> None:
    """Every empty part of the person's memory left out of state (`part` reads a missing one as empty)."""
    mem = person_row.get("memory")
    if isinstance(mem, dict):
        for key in [k for k, v in mem.items() if v in ([], "", None)]:
            del mem[key]


def writable_part(person_row: dict[str, Any], key: str) -> Any:
    """One part of the person's memory to write in place (INSIDE an effect handler only, e.g.
    `relationships._e_history`); the handler calls `prune` after its write."""
    if key not in PARTS:
        raise ValueError(f"memory.writable_part: {key!r} is no part ({', '.join(PARTS)})")
    return _writable(person_row)[key]


def prune(person_row: dict[str, Any]) -> None:
    """After a write through `writable_part`: the empty parts left out of state (`_prune`)."""
    _prune(person_row)


# -- the conversation, rendered -------------------------------------------------------------------


def stamp(at: Any) -> str:
    from engine.social import behaviour

    hours = float(at or 0.0)
    minutes = int(round((hours % 24.0) * 60)) % (24 * 60)
    return f"{behaviour.weekday_of(hours).title()} {minutes // 60:02d}:{minutes % 60:02d}"


def message_words(message: dict[str, Any]) -> list[str]:
    """What a message says: its bubbles, or a voice note's transcript; a media message marked."""
    bubbles = [str(b).strip() for b in message.get("bubbles") or () if str(b).strip()]
    if not bubbles and message.get("transcript"):
        bubbles = [str(message["transcript"]).strip()]
    mark = dict(MEDIA_MARKS).get(str(message.get("kind") or ""))
    if mark:
        bubbles = [f"{mark} {b}" for b in bubbles] or [mark]
    return bubbles


def _speaker(message: dict[str, Any], names: dict[str, str]) -> str:
    sender = str(message.get("from") or "")
    if sender == "player":
        return YOU
    return names.get(sender) or sender or "them"


def render_thread(messages: list[dict[str, Any]], names: dict[str, str]) -> str:
    """One line per bubble, oldest first: "Tue 21:14 you: ...", "Tue 21:16 Kai: ...". A message
    not yet voiced has no words and no line."""
    lines: list[str] = []
    for message in messages:
        if message.get("voiced") is False or message.get("voiced") == "withdrawn":
            continue
        who = _speaker(message, names)
        when = stamp(message.get("at"))
        lines.extend(f"{when} {who}: {words}" for words in message_words(message))
    return "\n".join(lines)


def split_tail(messages: list[dict[str, Any]], verbatim: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(older, tail): the tail is the newest messages holding the last ``verbatim`` bubbles the voice
    reads word for word (§11.3 block 5)."""
    count = 0
    cut = len(messages)
    while cut > 0 and count < verbatim:
        cut -= 1
        count += max(1, len(messages[cut].get("bubbles") or ()))
    return messages[:cut], messages[cut:]


def story_lines(mem: dict[str, Any]) -> str:
    """The person's story so far, then each kept episode's recap, oldest first (one line each): the
    voice's YOUR STORY TOGETHER block is built from the same parts (`voicing.messages`)."""
    lines = [str(mem.get("story") or "").strip()]
    lines += [f"{stamp(e.get('to_at'))}: {str(e.get('recap') or '').strip()}" for e in mem.get("episodes") or ()
              if str(e.get("recap") or "").strip()]
    return "\n".join(line for line in lines if line)


# -- the recap prompt ------------------------------------------------------------------------------


def _prompt_pair() -> tuple[str, str]:
    """`prompts/episode_recap.md` split at `STORY_HEADING` (cached, warmed): ("", "") with no story
    declaring `paths.social`, or (one WARNING per path) when the story has no such file."""
    global _RECAP_PROMPT_CACHE
    cached = _RECAP_PROMPT_CACHE  # read once: a reset nulls it without a lock
    if cached is not None:
        return cached
    directory = social.social_dir()
    if directory is None:
        loaded = ("", "")
    else:
        path = directory.parent.parent / "prompts" / RECAP_PROMPT
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            key = str(path)
            if key not in _PROMPT_MISSING_LOGGED:
                _PROMPT_MISSING_LOGGED.add(key)
                logger.warning("[social] The story has no episode recap prompt; recaps go out with an empty "
                               "system message (operation=recap_prompt, path=%s): %s", path, exc)
            text = ""
        head, sep, tail = text.partition(STORY_HEADING)
        loaded = (head.strip() + "\n" if head.strip() else "", tail.strip() + "\n" if sep and tail.strip() else "")
    _RECAP_PROMPT_CACHE = loaded
    return loaded


def recap_prompt() -> str:
    """The recap's system prompt: `prompts/episode_recap.md` above `## The story so far` (§7.2)."""
    return _prompt_pair()[0]


def story_prompt() -> str:
    """The story fold's system prompt: `prompts/episode_recap.md` under `## The story so far`."""
    return _prompt_pair()[1]


# -- the recap's view, fallback and job (§7.2) -----------------------------------------------------


def _they(reason: str) -> str:
    """An end reason (a `conversation.yaml` `reasons:` key, or its words) as a third-person line from
    `reasons_recap:` ("they had to go to sleep"); "" when it names none."""
    data = social.data("conversation")
    table = data.get("reasons_recap") or {}
    if reason in table:
        return str(table[reason])
    for key, words in (data.get("reasons") or {}).items():
        pattern = re.escape(str(words)).replace(re.escape("{hour}"), r"\d+")
        if re.fullmatch(pattern, reason) and key in table:
            return str(table[key])
    return ""


def recap_fallback(view: dict[str, Any]) -> str:
    """The deterministic recap, built from engine facts (§7.2): the topics, the end reason, the promise,
    and a scene's band words."""
    names = {t["id"]: t["label"] for t in view.get("topic_rows") or []}
    topics = [names[t] for t in view.get("topics") or [] if t in names]
    parts: list[str] = []
    if topics:
        parts.append("You talked about " + _join(topics))
    reason = str(view.get("end_reason") or "")
    if reason:
        line = _they(reason)            # "you're winding down for the night" -> "they had to go to sleep"
        if line:
            parts.append(line)
    promise = view.get("promise_words")
    if promise:
        parts.append(str(promise))                       # "they said they'd message you in the morning"
    if view.get("band"):                                 # a scene (T13): the band's words
        parts.append(str(view["band_words"]))
    return "; ".join(parts) + "." if parts else "You talked for a while."


def _promise_words(state: GameState, pid: str, due: dict[str, Any]) -> str:
    """The newest promise either side made in the episode, in the engine's words ("" when none)."""
    from engine.social import promises

    rows = (state.social or {}).get("promises") or {}
    start = float(due.get("started_at") or 0.0) - 1e-9
    end = float(due.get("closed_at") if due.get("closed_at") is not None else due.get("last_at") or 0.0) + 1e-9
    made = [r for r in rows.values() if r.get("pid") == pid and start <= float(r.get("made_at", -1)) <= end]
    if due.get("promise_id") and due["promise_id"] in rows:
        made.append(rows[due["promise_id"]])
    if not made:
        return ""
    row = max(made, key=lambda r: (float(r.get("made_at", 0)), str(r.get("id"))))
    words = promises.window_words(row, speaker=str(row.get("by") or ""))
    if row.get("by") == "player":
        return f"you said you'd message them {words}"
    return f"they said they'd message you {words}"


def _spoken(message: dict[str, Any]) -> bool:
    return message.get("voiced") is not False and message.get("voiced") != "withdrawn"


def _number(message_id: Any) -> int:
    text = str(message_id or "")
    return int(text[1:]) if text[:1] == "m" and text[1:].isdigit() else -1


def _names(state: GameState, pid: str) -> dict[str, str]:
    from engine.social import population

    return {pid: population.profile(state, pid).name}


def _band_view(due: dict[str, Any]) -> dict[str, str]:
    """A scene episode's band and the engine's words for it (v0.23.0 T13; `recap_fallback` reads them); {} for a
    chat."""
    band = str(due.get("band") or "")
    if not band:
        return {}
    from engine.social import scene   # lazily: scene imports this module's peers

    return {"band": band, "band_words": scene.recap_line(band)}


def recap_due_pids(state: GameState) -> list[str]:
    """The people with an episode waiting for its recap, the oldest closed first. Reads only."""
    people = (state.social or {}).get("people") or {}
    waiting = [(float((p.get("recap_due") or [{}])[0].get("closed_at") or 0.0), pid)
               for pid, p in people.items() if isinstance(p, dict) and p.get("recap_due")]
    return [pid for _at, pid in sorted(waiting)]


def restore_pids(state: GameState) -> list[str]:
    """The people whose shelved memory waits to come back: shelves archived and a conversation open."""
    return [pid for pid, p in sorted(((state.social or {}).get("people") or {}).items())
            if isinstance(p, dict) and p.get("episode") and isinstance(p.get("memory"), dict)
            and p["memory"].get("shelved")]


def recap_pending(state: GameState) -> bool:
    """Whether any memory job waits -- a recap, or a restore (a pass then runs one, `voicer._recap_one`)."""
    return any(isinstance(p, dict) and (p.get("recap_due") or (p.get("episode") and isinstance(p.get("memory"), dict)
                                                               and p["memory"].get("shelved")))
               for p in ((state.social or {}).get("people") or {}).values())


def recap_view(state: GameState, pid: str) -> Optional[dict[str, Any]]:
    """
    What the recap of ``pid``'s oldest closed episode reads (CALLER HOLDS the
    turn lock; no file is read here): the episode's facts and its messages --
    ``current``'s unrecapped rows up to the episode's last exchange, and the
    rows of the person's threads still in state inside it -- copied. When a
    thread's oldest row in state is newer than the episode's start and the
    thread has archived messages, the view names it in ``needs_archive``
    (``with_archive`` reads them off the lock). None when nothing is due.
    """
    row = ((state.social or {}).get("people") or {}).get(pid) or {}
    rows = row.get("recap_due") or []
    if not rows:
        return None
    due = rows[0]
    from_at = float(due.get("started_at") or 0.0)
    to_at = float(due.get("last_at") if due.get("last_at") is not None else from_at)
    items: dict[str, dict[str, Any]] = {}
    current = [full_message(m, pid) for m in part(row, "current")]
    for m in current:
        if float(m.get("at", 0.0)) <= to_at + AT_EPS:
            items[str(m["id"])] = copy.deepcopy(m)
    earliest = min([from_at] + [float(m["at"]) for m in items.values()])
    needs: list[tuple[str, int]] = []
    for tid, t in sorted(((state.social or {}).get("threads") or {}).items()):
        if t.get("pid") != pid:
            continue
        messages = t.get("messages") or []
        for m in messages:
            if earliest - AT_EPS <= float(m.get("at", 0.0)) <= to_at + AT_EPS and _spoken(m) and m.get("from") != "system":
                items.setdefault(str(m["id"]), {k: copy.deepcopy(m.get(k)) for k in SPOKEN_KEYS})
        oldest = float(messages[0]["at"]) if messages else None
        if t.get("archived_through") and (oldest is None or oldest > from_at):
            needs.append((tid, _number(messages[0]["id"]) if messages else -1))
    view = {
        "kind": "recap", "pid": pid, "due_id": str(due["id"]), "episode_kind": str(due.get("kind") or "chat"),
        "where": str(due.get("location") or str(due.get("thread_id") or "").partition(":")[0]),
        "from_at": from_at, "to_at": to_at,
        "end_reason": str(due.get("end_key") or due.get("end_reason") or ""),
        "topics": [str(t) for t in due.get("topics") or ()], "topic_rows": topic_rows(state, pid),
        "promise_words": _promise_words(state, pid, due), "names": _names(state, pid),
        **_band_view(due),
        "items": sorted(items.values(), key=lambda m: (float(m.get("at", 0.0)), _number(m.get("id")))),
        "needs_archive": needs, "earliest": earliest,
    }
    return view


def with_archive(view: dict[str, Any], directory: Optional[Path]) -> dict[str, Any]:
    """
    ``view`` with the episode's messages the spill already took (NO lock
    needed: the file is append-only and read from its end), read by the
    episode's TIME WINDOW (`archive.archived_between`, review M2), so an
    older episode in a backlog is read however much was archived after it.
    When the read never got back to the window's start (the file missing,
    unreadable or ending first) the view keeps what it has, with a WARNING:
    a recap moves no watermark, so nothing is skipped for good by it.
    """
    from engine.social import archive

    if not view.get("needs_archive"):
        return view
    items = {str(m["id"]): m for m in view.get("items") or ()}
    low, high = float(view.get("earliest", view["from_at"])), float(view["to_at"])
    for tid, below in view["needs_archive"]:
        rows, reached = archive.archived_between(directory, tid, below, low - AT_EPS, high + AT_EPS)
        if not reached:
            logger.warning("[social] The archive did not reach back to this episode's start; the recap reads "
                           "what it found (operation=with_archive, thread=%s, rows=%d)", tid, len(rows))
        for m in rows:
            if low - AT_EPS <= float(m.get("at", 0.0)) <= high + AT_EPS and _spoken(m) and m.get("from") != "system":
                items.setdefault(str(m["id"]), {k: copy.deepcopy(m.get(k)) for k in SPOKEN_KEYS})
    ordered = sorted(items.values(), key=lambda m: (float(m.get("at", 0.0)), _number(m.get("id"))))
    return dict(view, items=ordered, needs_archive=[])


def _render_episode(items: list[dict[str, Any]], names: dict[str, str]) -> str:
    return render_thread(items, names)


def write_recap(view: dict[str, Any], llm_fn: Optional[SummaryFn]) -> tuple[str, bool]:
    """
    The recap over ``view`` (pure: no state, no lock): (the text, whether the
    model wrote it). One `summarize_with` call over `episode_recap.md`; with no
    messages, no model, a raise or an empty answer, `recap_fallback`. At most
    `memory.recap_words` words.
    """
    from engine.memory.summarizer import summarize_with

    items = list(view.get("items") or [])[-RECAP_MESSAGES_MAX:]
    words = _recap_words()
    if not any(_spoken(m) and message_words(m) for m in items):
        return _clip_words(recap_fallback(view), words), False
    names = dict(view.get("names") or {})
    text, used = summarize_with("", items, renderer=lambda rows: _render_episode(rows, names),
                                fallback=lambda existing, rows: recap_fallback(view), system=recap_prompt(),
                                new_label=THIS_CONVERSATION, llm_fn=llm_fn, max_words=words,
                                operation="write_recap")
    return _clip_words(text, words), used


def recap_row(view: dict[str, Any], text: str) -> dict[str, Any]:
    """The `episodes` row a recap commits (§7.1)."""
    return {"id": str(view["due_id"]), "kind": str(view.get("episode_kind") or "chat"),
            "where": str(view.get("where") or ""), "from_at": round(float(view["from_at"]), 4),
            "to_at": round(float(view["to_at"]), 4),
            "recap": _clip_words(text, _recap_words()), "topics": list(view.get("topics") or ()),
            "end_reason": str(view.get("end_reason") or "")}


def commit_recap(state: GameState, view: dict[str, Any], text: str) -> dict[str, Any]:
    """A recap written over ``view`` committed through `social_memory` `op: recap` (refused as stale when
    its `recap_due` row is gone)."""
    return apply_effect(state, {"type": "social_memory", "op": "recap", "pid": view["pid"],
                                "due_id": view["due_id"], "through_at": view["to_at"],
                                "row": recap_row(view, text)})


def add_recap(state: GameState, pid: str, row: dict[str, Any]) -> dict[str, Any]:
    """A closed episode's recap row appended directly (`op: recap`, no `recap_due` row): T12's stub.
    `current` is cleared only up to the row's `to_at` (review M1): a chat still going keeps its lines;
    a row with no `to_at` clears nothing of it."""
    effect: dict[str, Any] = {"type": "social_memory", "op": "recap", "pid": pid, "row": dict(row)}
    effect["through_at"] = float(row["to_at"]) if row.get("to_at") is not None else -1.0
    return apply_effect(state, effect)


def fold_view(state: GameState, pid: str) -> Optional[dict[str, Any]]:
    """The story fold's view (CALLER HOLDS the lock): the oldest kept episode and the story it folds
    into, when the person's `episodes` are full; else None."""
    row = ((state.social or {}).get("people") or {}).get(pid) or {}
    episodes = part(row, "episodes")
    if len(episodes) < max(1, _setting("episodes_kept", 12)):
        return None
    return {"kind": "fold", "pid": pid, "episode": copy.deepcopy(episodes[0]), "story": str(part(row, "story") or "")}


def write_fold(view: dict[str, Any], llm_fn: Optional[SummaryFn]) -> tuple[str, bool]:
    """The story with the oldest episode folded in (pure): one `summarize_with` call over the story
    prompt; its fallback appends the recap and keeps the newest sentences (`cap_story`)."""
    from engine.memory.summarizer import summarize_with

    episode = dict(view["episode"])
    text, used = summarize_with(
        str(view.get("story") or ""), [episode],
        renderer=lambda rows: "\n".join(f"{stamp(e.get('to_at'))}: {e.get('recap')}" for e in rows),
        fallback=lambda existing, rows: cap_story(f"{existing} {' '.join(str(e.get('recap') or '') for e in rows)}"),
        system=story_prompt(), new_label=EARLIER_CONVERSATION, llm_fn=llm_fn, max_words=_story_words(),
        operation="write_fold")
    return cap_story(text), used


def commit_fold(state: GameState, view: dict[str, Any], text: str) -> dict[str, Any]:
    """A fold written over ``view`` committed (`op: fold`), refused as stale when the story or the oldest
    episode moved since."""
    return apply_effect(state, {"type": "social_memory", "op": "fold", "pid": view["pid"],
                                "episode_id": view["episode"]["id"], "base": view["story"], "story": text})


def commit_job(state: GameState, view: dict[str, Any], text: str) -> dict[str, Any]:
    """A recap, a fold or a restore committed, by the view's kind."""
    kind = view.get("kind")
    if kind == "fold":
        return commit_fold(state, view, text)
    if kind == "restore":
        return commit_restore(state, view, text)
    return commit_recap(state, view, text)


def job_record(view: dict[str, Any]) -> Optional[dict[str, Any]]:
    """What a FOLD job hands the archive before it commits (the caller appends it under the turn lock,
    `archive.append(..., kind="recap")`): the recap it folds and the story as it stood, so the fallback's
    cut never loses a word for good. None for any other job."""
    if view.get("kind") != "fold":
        return None
    episode = {**_episode_defaults(), **dict(view["episode"])}
    return {"id": f"fold-{episode['id']}", "pid": str(view["pid"]), "at": episode.get("to_at"),
            "story": str(view.get("story") or ""), "episodes": [episode]}


def job_with_archive(view: dict[str, Any], directory: Optional[Path]) -> dict[str, Any]:
    """The job's view with what it reads from the archive (NO lock): a recap's older messages
    (`with_archive`), a restore's shelves (`restore_with_archive`); a fold reads nothing."""
    if view.get("kind") == "recap":
        return with_archive(view, directory)
    if view.get("kind") == "restore":
        return restore_with_archive(view, directory)
    return view


def job_view(state: GameState, prefer: tuple[str, ...] = ()) -> Optional[dict[str, Any]]:
    """
    The next memory job's view (CALLER HOLDS the lock): the person with a
    recap due (those in ``prefer`` first, then the oldest closed): a fold
    when their `episodes` are full, else the recap. None when none is due.
    """
    for pid in restore_pids(state):                   # a dormant memory back first: its story is the context
        view = restore_view(state, pid)
        if view is not None:
            return view
    due = recap_due_pids(state)
    order = [p for p in prefer if p in due] + [p for p in due if p not in prefer]
    for pid in order:
        view = fold_view(state, pid) or recap_view(state, pid)
        if view is not None:
            return view
    return None


def write_job(view: dict[str, Any], llm_fn: Optional[SummaryFn]) -> tuple[str, bool]:
    kind = view.get("kind")
    if kind == "fold":
        return write_fold(view, llm_fn)
    if kind == "restore":
        return write_restore(view, llm_fn)
    return write_recap(view, llm_fn)


def production_summary_fn() -> Optional[SummaryFn]:
    """
    The production binding (pre-flight F10): one argument, the messages; the
    `small` profile (the UTILITY lane) with reasoning off. None when no model
    server answers; a reply starved by reasoning is "" so the deterministic
    fallback fires. A busy utility lane (hosted) raises `InferenceBusy` out
    of the call, which `summarize_with` swallows into the fallback.
    """
    try:
        from engine.llm.backend import get_backend

        backend = get_backend()
        if not backend.server_available():
            return None
    except Exception as exc:  # noqa: BLE001 -- memory is best-effort
        logger.debug("[social] No recap summarizer available: %s", exc)
        return None

    def _call(messages: list[dict[str, Any]]) -> str:
        response = backend.chat(messages, profile="small", temperature=0.2, reasoning="off",
                                label="social_summary")
        if getattr(response, "starved_by_reasoning", False):
            logger.error("[social] Recap starved by reasoning (operation=production_summary_fn, "
                         "model=%s); the recap will be deterministic", getattr(response, "model", ""))
            return ""
        return str(getattr(response, "content", "") or "")

    return _call


# -- follow-ups (§7.3) -----------------------------------------------------------------------------


def add_open(state: GameState, pid: str, row: dict[str, Any]) -> dict[str, Any]:
    """An open row (a follow-up: `{kind, about, due_at, by}`), bounded at `memory.open_max`, the oldest
    closed first (`op: open_add`)."""
    return apply_effect(state, {"type": "social_memory", "op": "open_add", "pid": pid, "row": dict(row)})


def close_open(state: GameState, pid: str, open_id: str) -> dict[str, Any]:
    """An open row closed (`op: open_close`)."""
    return apply_effect(state, {"type": "social_memory", "op": "open_close", "pid": pid, "open_id": str(open_id)})


def followup_due(state: GameState, pid: str, at: float) -> Optional[dict[str, Any]]:
    """The person's oldest follow-up due at ``at`` (a copy), or None: a row with no `due_at` is never
    due (review M3). Reads only."""
    row = ((state.social or {}).get("people") or {}).get(pid) or {}
    due = [r for r in part(row, "open") if r.get("kind") == "followup" and r.get("due_at") is not None
           and float(r["due_at"]) <= at + 1e-9]
    if not due:
        return None
    return copy.deepcopy(min(due, key=lambda r: (float(r["due_at"]), _number_of(r.get("id")))))


def _number_of(open_id: Any) -> int:
    text = str(open_id or "")
    return int(text[1:]) if text[:1] == "o" and text[1:].isdigit() else -1


# -- canon, knows, told, spoken --------------------------------------------------------------------


def add_canon(state: GameState, pid: str, facts: list[str]) -> None:
    """What they shared about themselves (§12.1), through `social_memory`; bounded, the oldest folded."""
    apply_effect(state, {"type": "social_memory", "op": "canon", "pid": pid, "facts": list(facts)})


def add_knows(state: GameState, pid: str, facts: list[str]) -> None:
    """What they learned about the player (§12.2), through `social_memory`; bounded, the oldest dropped."""
    apply_effect(state, {"type": "social_memory", "op": "knows", "pid": pid, "facts": list(facts)})


def note_spoken(state: GameState, pid: str, message: dict[str, Any]) -> None:
    """
    A message either side wrote, in ANY of the person's threads, into their
    `current` (`op: spoken`): the player's from `social_message`'s handler,
    theirs from `social_voiced`'s (cross-app continuity, §15.5). A message
    with no words is not noted.
    """
    if not message_words(message):
        return
    apply_effect(state, {"type": "social_memory", "op": "spoken", "pid": pid,
                         "message": {k: copy.deepcopy(message.get(k)) for k in SPOKEN_KEYS}})


def note_told(state: GameState, pid: str, messages: list[dict[str, Any]]) -> None:
    """
    The contacts the player named in ``messages`` (theirs, in ``pid``'s
    threads) remembered as told to ``pid`` (`op: told`). Called as the
    messages leave state for the archive, so `agreement.view_from_state`
    still counts them once only the archive holds the words.
    """
    from engine.social import agreement

    said: set[str] = set()
    for message in messages:
        if message.get("from") == "player":
            for bubble in message.get("bubbles") or ():
                said |= agreement.words_of(bubble)
    if not said:
        return
    names = [name for name in agreement.contact_names(state, pid) if agreement.name_words(name) & said]
    if names:
        apply_effect(state, {"type": "social_memory", "op": "told", "pid": pid, "names": names})


# -- the effect -----------------------------------------------------------------------------------


#: How a canon fold's sentence starts in the story (`_fold_canon`).
FOLD_PREFIX = "Earlier they shared:"


def _facts(effect: dict[str, Any]) -> list[str]:
    return [" ".join(str(f).split()) for f in effect.get("facts") or () if str(f).strip()]


def _append(rows: list[str], facts: list[str]) -> list[str]:
    """Each new fact appended once (case and spacing ignored); the facts actually added."""
    seen = {r.casefold() for r in rows}
    added = []
    for fact in facts:
        if fact.casefold() not in seen:
            seen.add(fact.casefold())
            rows.append(fact)
            added.append(fact)
    return added


def _bubbles(rows: list[dict[str, Any]]) -> int:
    return sum(max(1, len(r.get("bubbles") or ())) for r in rows)


def _last_bubbles(rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    """The newest rows holding the last ``limit`` bubbles (the oldest row cut to fit)."""
    out: list[dict[str, Any]] = []
    left = limit
    for r in reversed(rows):
        if left <= 0:
            break
        bubbles = list(r.get("bubbles") or ())
        if len(bubbles) > left:
            r = dict(r, bubbles=bubbles[-left:])
        out.append(r)
        left -= max(1, len(r.get("bubbles") or ()))
    return list(reversed(out))


def bridge_of(messages: list[dict[str, Any]], pid: str) -> list[dict[str, Any]]:
    """A `bridge` built from thread message rows (v0.23.0 T20, a v0.22.0 save's thread tail): the last
    `memory.bridge_bubbles` voiced, spoken bubbles of the player and `pid`, each row as state keeps it."""
    spoken = [_stored_message(m, pid) for m in messages
              if m.get("from") in ("player", pid) and m.get("voiced") is True and m.get("bubbles")]
    return _last_bubbles(spoken, max(0, _setting("bridge_bubbles", 6)))


def _fold_episodes(mem: dict[str, Any], keep: int) -> list[str]:
    """The oldest episodes past ``keep`` folded into the story, deterministically; their ids."""
    gone: list[str] = []
    while len(mem["episodes"]) > keep:
        oldest = mem["episodes"].pop(0)
        mem["story"] = cap_story(f"{mem['story']} {str(oldest.get('recap') or '').strip()}".strip())
        gone.append(str(oldest.get("id")))
    return gone


def _fail(text: str) -> dict[str, Any]:
    return {"type": "social_memory", "ok": False, "text": text}


@effect_kind("social_memory")
@recorded
def _e_memory(state: GameState, effect: dict[str, Any], ctx: EffectContext) -> dict[str, Any]:
    """
    Engine-only writes to a person's memory (spec §7.1), each bounded here:
    `canon` (`facts`; `social.canon_max`, the oldest folded into the story),
    `knows` (`facts`; `social.knows_max`, the oldest dropped), `told`
    (`names`), `spoken` (`message`: into `current`, `memory.verbatim`
    bubbles), `recap` (`row`, optional `due_id` and `through_at`: the episode
    appended, its `recap_due` row consumed -- refused as stale when gone --
    `current` up to `through_at` cleared into the `bridge`, the oldest
    episodes past `memory.episodes_kept` folded into the story), `fold`
    (`episode_id`, `base`, `story`: the oldest episode folded by a written
    story; refused as stale when either moved), `open_add` (`row`;
    `memory.open_max`, the oldest closed first) and `open_close`
    (`open_id`). A write for a person with no row is refused, never a row
    made up. Every write bumps the person's `rev`.
    """
    from engine.social import relationships

    if not state.social:
        return _fail("no social slice")
    op = str(effect.get("op") or "")
    if op not in OPS:
        return _fail(f"{op!r} is no memory op")
    pid = str(effect.get("pid") or "")
    if not pid:
        return _fail("no person named")
    person_row = (state.social.get("people") or {}).get(pid)
    if person_row is None:                     # a refusal, never a row made up for nobody
        return _fail(f"no person {pid}")
    handler = dict(_OP_HANDLERS)[op]
    result = handler(state, pid, person_row, effect)
    _prune(person_row)
    if result.get("ok") and result.pop("touched", True):
        relationships.touch(person_row)
    return {"type": "social_memory", **result}


def _op_told(state: GameState, pid: str, person_row: dict[str, Any], effect: dict[str, Any]) -> dict[str, Any]:
    names = [str(n) for n in effect.get("names") or () if str(n).strip()]
    added = _append(_writable(person_row)["told"], names)
    return {"ok": True, "text": f"{pid} told of {len(added)}", "added": added, "touched": bool(added)}


def _op_facts(state: GameState, pid: str, person_row: dict[str, Any], effect: dict[str, Any]) -> dict[str, Any]:
    op = str(effect["op"])
    mem = _writable(person_row)
    rows = mem[op]
    added = _append(rows, _facts(effect))
    limit = max(1, int(social.setting(f"{op}_max", 40 if op == "canon" else 30)))
    gone: list[str] = []
    if len(rows) > limit:
        gone = rows[: len(rows) - limit]
        del rows[: len(rows) - limit]
        if op == "canon":
            line = f"{FOLD_PREFIX} " + "; ".join(" ".join(f.split()).rstrip(".") for f in gone) + "."
            mem["story"] = cap_story(f"{mem['story']} {line}".strip())
    return {"ok": True, "text": f"{pid} {op} +{len(added)} -{len(gone)}", "added": added, "dropped": gone,
            "touched": bool(added or gone)}


def _op_spoken(state: GameState, pid: str, person_row: dict[str, Any], effect: dict[str, Any]) -> dict[str, Any]:
    message = effect.get("message")
    if not isinstance(message, dict) or not message.get("id"):
        return {"ok": False, "text": "no message"}
    row = _stored_message(message, pid)
    current = _writable(person_row)["current"]
    for i, old in enumerate(current):
        if old.get("id") == row["id"]:
            current[i] = row                     # the same message noted again: its words now
            break
    else:
        current.append(row)
    limit = max(1, _setting("verbatim", 40))
    while len(current) > 1 and _bubbles(current) > limit:
        current.pop(0)
    return {"ok": True, "text": f"{pid} spoken {row['id']}"}


def _op_recap(state: GameState, pid: str, person_row: dict[str, Any], effect: dict[str, Any]) -> dict[str, Any]:
    row = effect.get("row")
    if not isinstance(row, dict) or not row.get("id"):
        return {"ok": False, "text": "no recap row"}
    due_id = str(effect.get("due_id") or "")
    if due_id:
        waiting = person_row.get("recap_due") or []
        index = next((i for i, r in enumerate(waiting) if str(r.get("id")) == due_id), None)
        if index is None:
            return {"ok": False, "text": f"{pid}'s episode {due_id} is recapped already (stale)"}
        del waiting[index]
        if not waiting:
            person_row.pop("recap_due", None)
    mem = _writable(person_row)
    through = effect.get("through_at")
    if through is None:
        consumed, kept = list(mem["current"]), []
    else:
        consumed = [m for m in mem["current"] if float(m.get("at", 0.0)) <= float(through) + AT_EPS]
        kept = [m for m in mem["current"] if float(m.get("at", 0.0)) > float(through) + AT_EPS]
    if consumed:
        mem["bridge"] = _last_bubbles(consumed, max(0, _setting("bridge_bubbles", 6)))
    mem["current"] = kept
    episode = _stored_episode(row)
    mem["episodes"].append(episode)
    folded = _fold_episodes(mem, max(1, _setting("episodes_kept", 12)))
    return {"ok": True, "text": f"{pid} recapped {episode['id']}", "folded": folded}


def _op_fold(state: GameState, pid: str, person_row: dict[str, Any], effect: dict[str, Any]) -> dict[str, Any]:
    mem = _writable(person_row)
    if not mem["episodes"] or str(mem["episodes"][0].get("id")) != str(effect.get("episode_id") or ""):
        return {"ok": False, "text": f"{pid}'s oldest episode moved (stale)"}
    if "base" in effect and str(effect.get("base") or "") != str(mem["story"] or ""):
        return {"ok": False, "text": f"{pid}'s story moved (stale)"}
    oldest = mem["episodes"].pop(0)
    mem["story"] = cap_story(str(effect.get("story") or ""))
    return {"ok": True, "text": f"{pid} folded {oldest.get('id')}"}


def _op_shelve(state: GameState, pid: str, person_row: dict[str, Any], effect: dict[str, Any]) -> dict[str, Any]:
    """A dormant person's older recaps, `current` and `bridge` taken out of state once `archive.append`
    has written them to the archive under `shelf_id` (`compact_dormant`): nothing is folded or cut, and
    the shelf's id is remembered for the restore. Refused if its id is not the next one."""
    counters = state.social.setdefault("counters", {})
    shelf_id = str(effect.get("shelf_id") or "")
    if shelf_id != _next_shelf_id(state):
        return {"ok": False, "text": f"{shelf_id!r} is not the next shelf"}
    mem = _writable(person_row)
    count = max(0, int(effect.get("count") or 0))
    if count > len(mem["episodes"]):
        return {"ok": False, "text": f"{pid} has fewer than {count} recaps (stale)"}
    counters["shelf"] = int(counters.get("shelf", 0)) + 1
    del mem["episodes"][:count]
    mem["current"], mem["bridge"] = [], []
    mem.setdefault("shelved", []).append(shelf_id)
    return {"ok": True, "text": f"{pid} shelved {count} recap(s) as {shelf_id}", "shelf_id": shelf_id}


def _op_restore(state: GameState, pid: str, person_row: dict[str, Any], effect: dict[str, Any]) -> dict[str, Any]:
    """The shelves `shelf` brought back into the story (`write_restore`'s text): refused as stale when the
    story moved or a shelf is no longer waiting."""
    mem = _writable(person_row)
    shelf = [str(x) for x in effect.get("shelf") or ()]
    waiting = list(mem.get("shelved") or ())
    if not shelf or any(x not in waiting for x in shelf):
        return {"ok": False, "text": f"{pid}'s shelves moved (stale)"}
    if str(effect.get("base") or "") != str(mem["story"] or ""):
        return {"ok": False, "text": f"{pid}'s story moved (stale)"}
    mem["story"] = cap_story(str(effect.get("story") or ""))
    mem["shelved"] = [x for x in waiting if x not in shelf]
    return {"ok": True, "text": f"{pid} restored {', '.join(shelf)}"}


def _op_open_add(state: GameState, pid: str, person_row: dict[str, Any], effect: dict[str, Any]) -> dict[str, Any]:
    row = effect.get("row")
    if not isinstance(row, dict) or str(row.get("kind") or "") not in OPEN_KINDS:
        return {"ok": False, "text": f"an open row's kind must be one of {', '.join(OPEN_KINDS)}"}
    about = " ".join(str(row.get("about") or "").split())[:ABOUT_CHARS]
    if not about:
        return {"ok": False, "text": "an open row needs what it is about"}
    by = str(row.get("by") or "person")
    if by not in ("person", "player"):
        return {"ok": False, "text": f"{by!r} is not person or player"}
    mem = _writable(person_row)
    counters = state.social.setdefault("counters", {})
    counters["open"] = int(counters.get("open", 0)) + 1
    added = {"id": f"o{counters['open']}", "kind": str(row["kind"]), "about": about, "by": by}
    if row.get("due_at") is not None:
        added["due_at"] = float(row["due_at"])
    limit = max(1, _setting("open_max", 8))
    closed: list[str] = []
    while len(mem["open"]) >= limit:
        closed.append(str(mem["open"].pop(0).get("id")))
    mem["open"].append(added)
    return {"ok": True, "text": f"{pid} open {added['id']}", "open": dict(added), "closed": closed}


def _op_open_close(state: GameState, pid: str, person_row: dict[str, Any], effect: dict[str, Any]) -> dict[str, Any]:
    open_id = str(effect.get("open_id") or "")
    rows = part(person_row, "open")
    if not any(str(r.get("id")) == open_id for r in rows):
        return {"ok": False, "text": f"{pid} has no open {open_id!r}"}
    mem = _writable(person_row)
    mem["open"] = [r for r in mem["open"] if str(r.get("id")) != open_id]
    return {"ok": True, "text": f"{pid} closed {open_id}"}


#: The recaps a dormant person keeps in state (spec §17.2's lever); the older ones go to the archive.
DORMANT_EPISODES = 3


def _last_heard(row: dict[str, Any]) -> Optional[float]:
    """When the two of them last talked: their last message, the player's, or a recap's end."""
    times = [float(row[k]) for k in ("last_player_at", "last_them_at") if row.get(k) is not None]
    times += [float(e["to_at"]) for e in part(row, "episodes")[-1:] if e.get("to_at") is not None]
    return max(times) if times else None


def _next_shelf_id(state: GameState) -> str:
    return f"s{int(((state.social or {}).get('counters') or {}).get('shelf', 0)) + 1}"


def compact_dormant(state: GameState, directory: Optional[Path]) -> int:
    """
    Every DORMANT person's memory compacted, LOSSLESSLY (CALLER HOLDS the
    turn lock; at each save, `saves.compact`; spec §17.2's lever, the T6
    review's I1): no conversation open and none waiting for its recap, and
    none for `memory.dormant_days`. Their recaps past `DORMANT_EPISODES`,
    their story as it stands, `current` and `bridge` are first appended to
    the save's archive as one `recap` row (`archive.append`, the shelf
    ``s<n>``), then taken out of state (`op: shelve`); nothing is folded or
    cut. Their next conversation brings them back (`restore_view`). With no
    save directory, or when the append fails, nothing is compacted. How
    many people were compacted.
    """
    from engine.social import archive

    if not state.social or directory is None:
        return 0
    now = float(state.world_clock_hours)
    quiet = max(0.0, float(_setting("dormant_days", 30))) * 24.0
    done = 0
    for pid, row in sorted((state.social.get("people") or {}).items()):
        if not isinstance(row, dict) or not isinstance(row.get("memory"), dict):
            continue
        mem = row["memory"]
        episodes = list(mem.get("episodes") or ())
        if len(episodes) <= DORMANT_EPISODES and not mem.get("current") and not mem.get("bridge"):
            continue
        if row.get("episode") or row.get("recap_due"):
            continue
        heard = _last_heard(row)
        if heard is None or now - heard < quiet:
            continue
        count = max(0, len(episodes) - DORMANT_EPISODES)
        shelf_id = _next_shelf_id(state)
        full = person(state, pid)
        record = {"id": shelf_id, "pid": pid, "at": round(now, 4), "story": full["story"],
                  "episodes": full["episodes"][:count], "current": full["current"], "bridge": full["bridge"]}
        if not archive.append(directory, [record], kind="recap"):
            logger.warning("[social] A dormant memory stays whole: the archive did not take it "
                           "(operation=compact_dormant, pid=%s)", pid)
            continue
        result = apply_effect(state, {"type": "social_memory", "op": "shelve", "pid": pid, "shelf_id": shelf_id,
                                      "count": count})
        done += bool(result.get("ok"))
    return done


def restore_view(state: GameState, pid: str) -> Optional[dict[str, Any]]:
    """The restore job's view (CALLER HOLDS the lock): a person with shelves waiting and a conversation
    open again -- the shelves' ids and the story they are folded into. None otherwise."""
    row = ((state.social or {}).get("people") or {}).get(pid) or {}
    mem = row.get("memory") if isinstance(row.get("memory"), dict) else {}
    if not mem.get("shelved") or not row.get("episode"):
        return None
    return {"kind": "restore", "pid": pid, "shelf": list(mem["shelved"]), "story": str(mem.get("story") or ""),
            "episodes": [], "missing": []}


def restore_with_archive(view: dict[str, Any], directory: Optional[Path]) -> dict[str, Any]:
    """The restore view with its shelves' recaps read from the archive (NO lock: `archive.archived_memory`
    reads the append-only file). A shelf the archive does not hold is named in `missing` (a WARNING): its
    words stay wherever the file is, and the restore commits the rest."""
    rows = {str(r.get("id")): r for r in archived_memory(directory, str(view["pid"]))}
    episodes: list[dict[str, Any]] = []
    missing: list[str] = []
    for shelf in view["shelf"]:
        if shelf in rows:
            episodes += list(rows[shelf].get("episodes") or ())
        else:
            missing.append(shelf)
    if missing:
        logger.warning("[social] The archive does not hold these shelves; the restore folds the rest "
                       "(operation=restore_with_archive, pid=%s, missing=%s)", view["pid"], missing)
    return dict(view, episodes=episodes, missing=missing)


def write_restore(view: dict[str, Any], llm_fn: Optional[SummaryFn]) -> tuple[str, bool]:
    """The story with a dormant spell's shelved recaps folded back in (pure): one `summarize_with` call
    over the story prompt, which CONDENSES them; with no model the fallback keeps the newest sentences
    for the prompt's budget (`cap_story`) -- the archive keeps every word either way."""
    from engine.memory.summarizer import summarize_with

    episodes = list(view.get("episodes") or ())
    if not episodes:
        return str(view.get("story") or ""), False
    text, used = summarize_with(
        str(view.get("story") or ""), episodes,
        renderer=lambda rows: "\n".join(f"{stamp(e.get('to_at'))}: {e.get('recap')}" for e in rows),
        fallback=lambda existing, rows: cap_story(f"{existing} {' '.join(str(e.get('recap') or '') for e in rows)}"),
        system=story_prompt(), new_label=EARLIER_CONVERSATION, llm_fn=llm_fn, max_words=_story_words(),
        operation="write_restore")
    return cap_story(text), used


def commit_restore(state: GameState, view: dict[str, Any], text: str) -> dict[str, Any]:
    """A restore committed (`op: restore`), refused as stale when the story or the shelves moved."""
    return apply_effect(state, {"type": "social_memory", "op": "restore", "pid": view["pid"],
                                "shelf": list(view["shelf"]), "base": view["story"], "story": text})


def archived_memory(directory: Optional[Path], pid: str) -> list[dict[str, Any]]:
    """Everything of ``pid``'s memory the archive holds (dormant shelves and fold records), oldest first:
    the whole history stays recoverable however the prompt's story is cut (NO lock)."""
    from engine.social import archive

    return list(archive.archived_memory(directory, pid) or ())


#: The kinds of open row (§7.1): follow-ups now; plans join with T12.
OPEN_KINDS: tuple[str, ...] = ("followup",)

#: The most characters an open row's `about` keeps (§7.3: "about ≤ 100").
ABOUT_CHARS = 100

#: Each op's handler (`_e_memory` dispatches on it).
_OP_HANDLERS: tuple[tuple[str, Callable[..., dict[str, Any]]], ...] = (
    ("canon", _op_facts), ("knows", _op_facts), ("told", _op_told), ("spoken", _op_spoken), ("recap", _op_recap),
    ("fold", _op_fold), ("open_add", _op_open_add), ("open_close", _op_open_close), ("shelve", _op_shelve),
    ("restore", _op_restore),
)


# -- the budget (§7.4) ----------------------------------------------------------------------------


def _estimate(blocks: dict[str, str]) -> int:
    from engine.memory.budget import estimate_messages

    return estimate_messages({"content": text} for text in blocks.values() if text)


def budgeted(parts: dict[str, str], window: int, *, degraded: bool = False) -> dict[str, str]:
    """
    The voice prompt's parts (`BLOCK_PARTS`) trimmed to fit ``window``
    tokens (v0.23.0 spec §7.4). On a ``degraded`` binding (one under
    `social.voice.window_tokens`) the `episodes` keep their last
    `EPISODES_MIN` and the `story` its last `DEGRADED_STORY_WORDS` words
    first. Then, until the estimate fits, oldest first within each part:
    1. older `episodes`, down to `EPISODES_MIN`;
    2. `story` words;
    3. `canon`;
    4. `history`, down to `memory.history_min`;
    5. `current`, down to `memory.verbatim_min`.
    `NEVER_TRIMMED` is never touched: when the window cannot hold it plus
    the floors, every part is returned as trimmed as the floors allow (the
    binding's own context check is the backstop). A copy.
    """
    unknown = sorted(set(parts) - set(BLOCK_PARTS))
    if unknown:
        raise ValueError(f"memory.budgeted: {', '.join(unknown)} is no block part ({', '.join(BLOCK_PARTS)})")
    blocks = {key: str(value or "") for key, value in parts.items()}

    def lines(key: str) -> list[str]:
        return blocks.get(key, "").split("\n") if blocks.get(key) else []

    if degraded:
        blocks["episodes"] = "\n".join(lines("episodes")[-EPISODES_MIN:])
        if blocks.get("story"):
            blocks["story"] = last_words(blocks["story"], DEGRADED_STORY_WORDS)

    def trim_lines(key: str, floor: int) -> None:
        rows = lines(key)
        while len(rows) > floor and _estimate(blocks) > window:
            rows.pop(0)
            blocks[key] = "\n".join(rows)

    trim_lines("episodes", EPISODES_MIN)
    words = blocks.get("story", "").split()
    while words and _estimate(blocks) > window:
        words = words[max(1, len(words) // 10):]
        blocks["story"] = " ".join(words)
    trim_lines("canon", 0)
    trim_lines("history", max(0, _setting("history_min", 4)))
    trim_lines("current", max(0, _setting("verbatim_min", 16)))
    return blocks


__all__ = [
    "BLOCK_PARTS", "DEGRADED_STORY_WORDS", "EPISODES_MIN", "NEVER_TRIMMED", "PARTS", "SummaryFn", "THIS_CONVERSATION", "add_canon", "add_knows", "add_open", "add_recap",
    "budgeted", "cap_story", "close_open", "commit_fold", "compact_dormant", "commit_job", "commit_recap", "fold_view", "followup_due",
    "fresh", "job_view", "last_words", "message_words", "note_spoken", "note_told", "part", "person",
    "production_summary_fn", "recap_due_pids", "recap_fallback", "recap_pending", "recap_prompt", "recap_view",
    "render_thread", "split_tail", "stamp", "story_lines", "story_prompt", "topic_rows", "with_archive",
    "write_fold", "write_job", "write_recap",
]
