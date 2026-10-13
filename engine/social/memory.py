"""
Memory and context (v0.22.0 spec §12): what each person remembers.

ONE MEMORY PER RELATIONSHIP. Everything here is kept per person (or per
thread) in `state.social`, and nothing crosses from one person to another:

- **Canon** (`people[pid].canon`, §12.1): what they have told the player
  about themselves -- a voiced reply's `shared` facts (after the agreement
  checks) and an arc's reveal -- bounded at `social.canon_max`; the oldest
  leave state FOLDED into the summary of each of their threads, so the voice
  still reads them there.
- **Knows** (`people[pid].knows`, §12.2): what they have learned about the
  player -- a reply's `learned` facts -- bounded at `social.knows_max`, the
  oldest dropped. A person knows only what the player told THEM.
- **Told** (`people[pid].told`): the names of the player's other contacts the
  player wrote in THIS person's threads (`agreement.AgreementView.told`).
  Recorded when the player's messages leave state for the archive
  (`messaging._archive` -> `note_told`), so the spill never makes a person
  "forget" a name the player gave them; `agreement.view_from_state` reads it
  beside the messages still in state. Bounded by the player's contacts.
- **The thread summary** (`threads[tid].summary`, `summary_through`, §12.3):
  the conversation older than the voice's verbatim window, folded by
  `summarize_thread` over `engine/memory/summarizer.py::summarize_with` with
  this module's renderer ("Tue 21:14 you: ..."), its deterministic fallback
  and `prompts/thread_summary.md`, at most `social.memory.summary_words`.

Every write is a `social_memory` effect (rule 3): `op: canon | knows | told |
summary`. The summary call is a UTILITY call on the `small` profile with
reasoning off (`production_summary_fn`, pre-flight F10: its model function
takes ONE argument, the messages), degradable: in hosted mode a busy utility
lane is an exception the summarizer swallows, and the deterministic fallback
is the expected hosted path. A summary the model writes from a snapshot is
committed with its `base` (the summary it was written over): if the summary
moved meanwhile (a canon fold, another pass) the commit is refused as stale,
and the next pass folds again.

THE SPILL (T10's carry). `archive.spill` moves a thread's oldest messages
out of state at save time, under the turn lock, where no model may be
called. So the summary does not summarise before the spill; it reads
`phone_archive.jsonl` instead, whenever the thread has archived a message
newer than its summary (`archived_through` past `summary_through`): under
the lock `thread_view` copies state's rows and marks the view
`needs_archive`; off the lock `with_archive` reads the file from its end
(`archive.archived_after`, as far back as the summary reaches) and fills
the overflow. An archive that should hold such messages and does not (the
file gone or unreadable) leaves the overflow empty and the watermark where
it is: a summary never moves past messages it did not read.

The thread's summary keeps folded canon ("Earlier they shared: ..." lines)
ahead of the conversation when it is cut to its words (`cap_summary`).
A write for a person with no row is refused, never a row made up.

The budget (§12.4, `budgeted`): blocks 1, 6 and 7 fixed; 2-5 trimmed in
order -- the verbatim tail (to `memory.verbatim_min`), history (to
`memory.history_min`), canon (oldest first), the summary (oldest words
first) -- until the estimate fits the window.
"""

from __future__ import annotations

import copy
import logging
from pathlib import Path
from typing import Any, Callable, Optional

from engine import social
from engine.game.effects import EffectContext, apply_effect, effect_kind
from engine.game.state import GameState
from engine.social.kinds import recorded

logger = logging.getLogger(__name__)

#: The summarizer's model function (pre-flight F10): the messages in, raw text out.
SummaryFn = Callable[[list[dict[str, Any]]], str]

#: `social_memory`'s operations.
OPS: tuple[str, ...] = ("canon", "knows", "told", "summary")

#: The prompt file, in the story's `prompts/` directory (spec §11.6).
SUMMARY_PROMPT = "thread_summary.md"

#: The user block's label for a thread's new messages (the ledger's is "NEW EVENTS").
NEW_MESSAGES = "NEW MESSAGES"

#: How the player is named in a rendered thread.
YOU = "you"

#: The most words one message keeps in the deterministic fallback (its first sentence, cut here).
ENTRY_WORDS = 25

#: How a media message reads in a rendered thread, before its words.
MEDIA_MARKS: tuple[tuple[str, str], ...] = (("photo", "[photo]"), ("video", "[video]"), ("voice", "[voice note]"))

#: The budgeted blocks (§11.3's seven, split where §12.4 trims inside one): block 1 `persona`,
#: 2 `who` + `canon`, 3 `where` + `history`, 4 `knows`, 5 `summary` + `verbatim`, 6 `now`,
#: 7 `format`. Each trimmable part is one row per line, oldest first.
BLOCK_PARTS: tuple[str, ...] = ("persona", "who", "canon", "where", "history", "knows", "summary",
                                "verbatim", "now", "format")


#: Prompt paths already reported missing by `summary_prompt` (one WARNING per path, per process).
_PROMPT_MISSING_LOGGED: set[str] = set()


def _number(message_id: Any) -> int:
    text = str(message_id or "")
    return int(text[1:]) if text[:1] == "m" and text[1:].isdigit() else -1


def _summary_words() -> int:
    return max(20, int(social.setting("memory.summary_words", 180)))


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


#: How a canon fold's line starts in a summary (one line each, `_fold_into_summaries`).
FOLD_PREFIX = "Earlier they shared:"


def _split_folds(text: str) -> tuple[list[str], str]:
    """(the canon fold lines, the rest as one line) of a summary."""
    folds: list[str] = []
    rest: list[str] = []
    for line in str(text or "").split("\n"):
        line = " ".join(line.split())
        if line.startswith(FOLD_PREFIX):
            folds.append(line)
        elif line:
            rest.append(line)
    return folds, " ".join(rest)


def cap_summary(text: str, limit: int) -> str:
    """
    A summary held to ``limit`` words: the conversation loses its oldest words
    first, and the folded canon lines (kept first, one a line) only once the
    conversation is gone -- the oldest fold first.
    """
    folds, rest = _split_folds(text)
    while folds and sum(len(f.split()) for f in folds) > limit:
        folds.pop(0)
    room = limit - sum(len(f.split()) for f in folds)
    kept = last_words(rest, room) if room > 0 else ""
    return "\n".join(folds + ([kept] if kept else []))


# -- the thread, rendered ----------------------------------------------------------------------


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
    reads word for word (§11.3 block 5); older ones are what the summary covers."""
    count = 0
    cut = len(messages)
    while cut > 0 and count < verbatim:
        cut -= 1
        count += max(1, len(messages[cut].get("bubbles") or ()))
    return messages[:cut], messages[cut:]


# -- the summary prompt and its fallback ----------------------------------------------------


def summary_prompt() -> str:
    """`prompts/thread_summary.md`, verbatim (spec §11.6); "" when the story has none (a WARNING, once
    per path: the summary would go out with an empty system message)."""
    directory = social.social_dir()
    if directory is None:
        return ""
    path = directory.parent.parent / "prompts" / SUMMARY_PROMPT
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        key = str(path)
        if key not in _PROMPT_MISSING_LOGGED:
            _PROMPT_MISSING_LOGGED.add(key)
            logger.warning("[social] The story has no thread summary prompt; summaries go out with an empty "
                           "system message (operation=summary_prompt, path=%s): %s", path, exc)
        return ""


def summary_messages(existing: str, messages: list[dict[str, Any]], names: dict[str, str]) -> list[dict[str, Any]]:
    """
    The thread summary's request, exactly (spec §11.6): the system message is
    `thread_summary.md` verbatim; the user message is CURRENT SUMMARY and NEW
    MESSAGES. Built by `summarize_with` itself (the message it would send), so
    this and `summarize_thread` agree by construction.
    """
    from engine.memory.summarizer import summarize_with

    seen: list[list[dict[str, Any]]] = []

    def record(request: list[dict[str, Any]]) -> str:
        seen.append(request)
        return ""

    summarize_with(existing, list(messages) or [{}], renderer=lambda items: render_thread(items, names),
                   fallback=lambda e, _items: e, system=summary_prompt(), new_label=NEW_MESSAGES,
                   llm_fn=record, max_words=_summary_words())
    return seen[0]


def fallback_thread_summary(existing: str, messages: list[dict[str, Any]]) -> str:
    """
    Deterministic compression when no model answers (§12.3): the current
    summary, then one line per message ("Tue 21:14 you: <the first sentence
    of its first bubble>",
    the person as "them"), held to `memory.summary_words` by losing the oldest
    material first -- but the conversation's lines before any folded canon
    ("Earlier they shared: ..." lines, `cap_summary`), which is kept longest.
    The same input always gives the same text.
    """
    from engine.memory.summarizer import _first_sentence

    folds, rest = _split_folds(existing)
    parts = [rest] if rest else []
    for message in messages:
        if message.get("voiced") is False:
            continue
        said = message_words(message)
        sentence = _clip_words(_first_sentence(said[0]), ENTRY_WORDS) if said else ""
        if not sentence:
            continue
        who = YOU if message.get("from") == "player" else "them"
        parts.append(f"{stamp(message.get('at'))} {who}: {sentence}.")
    return cap_summary("\n".join(folds + [" ".join(parts)]), _summary_words())


def summarize_thread(view: dict[str, Any], llm_fn: Optional[SummaryFn]) -> tuple[str, bool]:
    """
    A thread's new summary over a snapshot (`thread_view`'s dict: `summary`,
    `overflow`, `names`): (the text, whether the model wrote it). Pure: no
    state, no lock. Nothing to fold returns the summary unchanged.
    """
    from engine.memory.summarizer import summarize_with

    names = dict(view.get("names") or {})
    words = _summary_words()
    capped: Optional[SummaryFn] = None
    if llm_fn is not None:
        model = llm_fn

        def capped(messages: list[dict[str, Any]]) -> str:
            # The cap applied to the RAW reply, keeping its end (summarize_with's own 1.3x cut,
            # which keeps the start, is then a no-op).
            return last_words(model(messages) or "", words)

    return summarize_with(
        str(view.get("summary") or ""), list(view.get("overflow") or []),
        renderer=lambda items: render_thread(items, names), fallback=fallback_thread_summary,
        system=summary_prompt(), new_label=NEW_MESSAGES, llm_fn=capped, max_words=words,
        operation="summarize_thread")


def production_summary_fn() -> Optional[SummaryFn]:
    """
    The production binding (pre-flight F10, T14 calls it): one argument, the
    messages; the `small` profile (the UTILITY lane) with reasoning off. None
    when no model server answers; a reply starved by reasoning is "" so the
    deterministic fallback fires (`default_state._summarizer_fn`'s pattern).
    A busy utility lane (hosted) raises `InferenceBusy` out of the call, which
    `summarize_with` swallows into the fallback.
    """
    try:
        from engine.llm.backend import get_backend

        backend = get_backend()
        if not backend.server_available():
            return None
    except Exception as exc:  # noqa: BLE001 -- memory is best-effort
        logger.debug("[social] No thread summarizer available: %s", exc)
        return None

    def _call(messages: list[dict[str, Any]]) -> str:
        response = backend.chat(messages, profile="small", temperature=0.2, reasoning="off",
                                label="social_summary")
        if getattr(response, "starved_by_reasoning", False):
            logger.error("[social] Thread summary starved by reasoning (operation=production_summary_fn, "
                         "model=%s); the summary will be deterministic", getattr(response, "model", ""))
            return ""
        return str(getattr(response, "content", "") or "")

    return _call


# -- the view, and the commit -------------------------------------------------------------------


def _names(state: GameState, pid: str) -> dict[str, str]:
    from engine.social import population

    return {pid: population.profile(state, pid).name}


def thread_view(state: GameState, thread_id: str) -> Optional[dict[str, Any]]:
    """
    What `summarize_thread` reads, copied out of state (CALLER HOLDS the
    turn lock; no file is read here): {"thread_id", "summary", "through",
    "overflow", "names"}, plus what `with_archive` needs. `overflow` is the
    voiced messages older than the verbatim tail and newer than
    `summary_through`, oldest first, at most `memory.summary_batch`, stopping
    at the first not yet voiced (the watermark is a clean point); `through`
    is the newest of them (the watermark a commit moves to).

    When the archive holds messages newer than the summary
    (`archived_through` past `summary_through`), the view `needs_archive`:
    its overflow stays EMPTY (nothing is committed past messages not read)
    until `with_archive` reads them, off the lock. None for an unknown thread.
    """
    t = ((state.social or {}).get("threads") or {}).get(thread_id)
    if t is None:
        return None
    through = str(t.get("summary_through") or "")
    view = {"thread_id": thread_id, "summary": str(t.get("summary") or ""), "through": through,
            "summary_through": through, "archived_through": str(t.get("archived_through") or ""),
            "rows": copy.deepcopy(list(t.get("messages") or [])), "overflow": [],
            "names": _names(state, str(t["pid"]))}
    view["needs_archive"] = _number(view["archived_through"]) > _number(through)
    return view if view["needs_archive"] else _with_overflow(view, [])


def with_archive(view: dict[str, Any], directory: Optional[Path]) -> dict[str, Any]:
    """
    ``view`` with the archive's part of its overflow (NO lock needed: the
    file is append-only and read from its end, `archive.archived_after`).
    A view that needs nothing is returned as it is. When the archive should
    hold messages past the summary but gives up none -- no save directory,
    the file missing or unreadable, or the newest archived message not in it
    -- the overflow stays empty and the watermark where it is (a WARNING):
    a summary is never committed past messages it did not read.
    """
    from engine.social import archive

    if not view.get("needs_archive"):
        return view
    after = _number(view.get("summary_through"))
    rows = archive.archived_after(directory, str(view["thread_id"]), after) if directory is not None else None
    if not rows or not any(str(r.get("id")) == view.get("archived_through") for r in rows):
        logger.warning("[social] The archive does not hold the messages past this thread's summary; the "
                       "summary waits (operation=with_archive, thread=%s, through=%s, archived_through=%s)",
                       view["thread_id"], view.get("summary_through"), view.get("archived_through"))
        return dict(view, overflow=[], through=str(view.get("summary_through") or ""))
    return _with_overflow(dict(view), rows)


def _with_overflow(view: dict[str, Any], archived: list[dict[str, Any]]) -> dict[str, Any]:
    """Fill ``view``'s `overflow` and `through` from the archive's rows and its state rows."""
    through = _number(view.get("summary_through"))
    rows: dict[str, dict[str, Any]] = {}
    for row in archived:
        rows.setdefault(str(row["id"]), row)
    for row in view.get("rows") or []:
        rows[str(row["id"])] = row          # state's copy wins over a crash duplicate
    ordered = sorted(rows.values(), key=lambda m: _number(m.get("id")))
    older, _tail = split_tail(ordered, max(1, int(social.setting("memory.verbatim", 24))))
    batch = max(1, int(social.setting("memory.summary_batch", 40)))
    overflow: list[dict[str, Any]] = []
    for message in older:
        if _number(message.get("id")) <= through:
            continue
        if message.get("voiced") is False or len(overflow) >= batch:
            break
        overflow.append(copy.deepcopy(message))
    view["overflow"] = overflow
    view["through"] = str(overflow[-1]["id"]) if overflow else str(view.get("summary_through") or "")
    return view


def commit_summary(state: GameState, view: dict[str, Any], text: str) -> dict[str, Any]:
    """A summary written over ``view`` committed through `social_memory` (refused if it went stale)."""
    return apply_effect(state, {"type": "social_memory", "op": "summary", "thread_id": view["thread_id"],
                                "text": text, "through": view["through"], "base": view["summary"]})


def add_canon(state: GameState, pid: str, facts: list[str]) -> None:
    """What they shared about themselves (§12.1), through `social_memory`; bounded, the oldest folded."""
    apply_effect(state, {"type": "social_memory", "op": "canon", "pid": pid, "facts": list(facts)})


def add_knows(state: GameState, pid: str, facts: list[str]) -> None:
    """What they learned about the player (§12.2), through `social_memory`; bounded, the oldest dropped."""
    apply_effect(state, {"type": "social_memory", "op": "knows", "pid": pid, "facts": list(facts)})


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


def _fold_into_summaries(state: GameState, pid: str, facts: list[str]) -> None:
    """Canon leaving state, folded as one line into each of the person's threads' summaries."""
    line = f"{FOLD_PREFIX} " + "; ".join(" ".join(f.split()).rstrip(".") for f in facts) + "."
    for t in (state.social.get("threads") or {}).values():
        if t.get("pid") == pid:
            t["summary"] = cap_summary(f"{t.get('summary') or ''}\n{line}", _summary_words())


@effect_kind("social_memory")
@recorded
def _e_memory(state: GameState, effect: dict[str, Any], ctx: EffectContext) -> dict[str, Any]:
    """
    Engine-only memory writes (spec §12). `op: canon` (`pid`, `facts`):
    appended, bounded at `social.canon_max`, the oldest folded into the
    person's thread summaries. `op: knows` (`pid`, `facts`): appended,
    bounded at `social.knows_max`, the oldest dropped. `op: told` (`pid`,
    `names`): the contact names remembered as told to them. `op: summary`
    (`thread_id`, `text`, `through`, optional `base`): the thread's summary
    and its watermark, refused when `through` is not past the current one or
    the summary is no longer `base`. Every write bumps the person's `rev`.
    """
    from engine.social import relationships

    if not state.social:
        return {"type": "social_memory", "ok": False, "text": "no social slice"}
    op = str(effect.get("op") or "")
    if op not in OPS:
        return {"type": "social_memory", "ok": False, "text": f"{op!r} is no memory op"}
    if op == "summary":
        return _summary(state, effect)
    pid = str(effect.get("pid") or "")
    if not pid:
        return {"type": "social_memory", "ok": False, "text": "no person named"}
    person = (state.social.get("people") or {}).get(pid)
    if person is None:                     # a refusal, never a row made up for nobody
        return {"type": "social_memory", "ok": False, "text": f"no person {pid}"}
    if op == "told":
        names = [str(n) for n in effect.get("names") or () if str(n).strip()]
        added = _append(person.setdefault("told", []), names)
        if added:
            relationships.touch(person)
        return {"type": "social_memory", "ok": True, "text": f"{pid} told of {len(added)}", "added": added}
    facts = _facts(effect)
    rows = person.setdefault(op, [])
    added = _append(rows, facts)
    limit = max(1, int(social.setting(f"{op}_max", 40 if op == "canon" else 30)))
    gone: list[str] = []
    if len(rows) > limit:
        gone = rows[: len(rows) - limit]
        del rows[: len(rows) - limit]
        if op == "canon":
            _fold_into_summaries(state, pid, gone)
    if added or gone:
        relationships.touch(person)
    return {"type": "social_memory", "ok": True, "text": f"{pid} {op} +{len(added)} -{len(gone)}",
            "added": added, "dropped": gone}


def _summary(state: GameState, effect: dict[str, Any]) -> dict[str, Any]:
    from engine.social import relationships

    tid = str(effect.get("thread_id") or "")
    t = (state.social.get("threads") or {}).get(tid)
    if t is None:
        return {"type": "social_memory", "ok": False, "text": f"no thread {tid}"}
    if "base" in effect and str(effect.get("base") or "") != str(t.get("summary") or ""):
        return {"type": "social_memory", "ok": False, "text": f"{tid}'s summary moved (stale)"}
    through = str(effect.get("through") or "")
    if _number(through) <= _number(t.get("summary_through")):
        return {"type": "social_memory", "ok": False, "text": f"{tid} is summarised through {through} already"}
    t["summary"] = cap_summary(str(effect.get("text") or ""), _summary_words())
    t["summary_through"] = through
    relationships.touch(state.social.setdefault("people", {}).setdefault(str(t["pid"]), {}))
    return {"type": "social_memory", "ok": True, "text": f"{tid} summarised through {through}"}


# -- the budget (§12.4) ---------------------------------------------------------------------------


def _estimate(blocks: dict[str, str]) -> int:
    from engine.memory.budget import estimate_messages

    return estimate_messages({"content": text} for text in blocks.values() if text)


def budgeted(snapshot_blocks: dict[str, str], window: int) -> dict[str, str]:
    """
    The voice prompt's blocks (`BLOCK_PARTS`) trimmed to fit ``window``
    tokens (§12.4): `persona`, `who`, `where`, `knows`, `now` and `format` are
    fixed; then, in order, the `verbatim` tail loses its oldest lines down to
    `memory.verbatim_min`, `history` its oldest rows down to
    `memory.history_min`, `canon` its oldest facts, and the `summary` its
    oldest words, until the estimate fits. A copy; what still does not fit is
    returned as trimmed as the floors allow.
    """
    unknown = sorted(set(snapshot_blocks) - set(BLOCK_PARTS))
    if unknown:
        raise ValueError(f"memory.budgeted: {', '.join(unknown)} is no block part ({', '.join(BLOCK_PARTS)})")
    blocks = {key: str(value or "") for key, value in snapshot_blocks.items()}
    floors = (("verbatim", max(0, int(social.setting("memory.verbatim_min", 12)))),
              ("history", max(0, int(social.setting("memory.history_min", 4)))),
              ("canon", 0))
    for key, floor in floors:
        lines = blocks.get(key, "").split("\n") if blocks.get(key) else []
        while len(lines) > floor and _estimate(blocks) > window:
            lines.pop(0)
            blocks[key] = "\n".join(lines)
    words = blocks.get("summary", "").split()
    while words and _estimate(blocks) > window:
        words = words[max(1, len(words) // 10):]
        blocks["summary"] = " ".join(words)
    return blocks


__all__ = [
    "BLOCK_PARTS", "NEW_MESSAGES", "SummaryFn", "add_canon", "add_knows", "budgeted", "commit_summary",
    "fallback_thread_summary", "last_words", "note_told", "production_summary_fn", "render_thread",
    "split_tail", "summarize_thread", "summary_messages", "summary_prompt", "thread_view", "with_archive",
    "cap_summary", "FOLD_PREFIX",
]
