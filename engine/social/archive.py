"""
The phone's message archive (v0.22.0 spec §17.2, Plan decision 18).

State keeps a thread's conversation going on, its unread messages and, for
the thread the player has open, one screen (`social.state_messages`, 8); any
other thread keeps `social.closed_thread_tail` (0) behind its stamp
(`keep_for`, v0.23.0 T9 fix round 2). Older ones move
to an append-only `phone_archive.jsonl` in the run's save directory, one
message row per line. The move is made by the phone's one save path
(`saves.save_now`, under the turn lock, immediately before `_autosave`
replaces the envelope): the rows are appended to the file FIRST, then taken
out of state through `social_message` `op: archive` (rule 3). A crash
between the two -- or between the spill and the envelope's replace -- leaves
a row both in the file and in the save it reloads with: a duplicate line,
dropped by message id on read (`page`). `SaveStore.save` is unchanged, and
`SaveStore.delete` already removes every file of the save's directory, this
one included.

An episode's recap reads the file too (`archived_before`, from
`memory.with_archive`, off the turn lock, from the file's end), for the
episode's messages the spill already took: the spill runs under the turn
lock, where no model may be called, so it never recaps first.

Three kinds of row (`ROW_KINDS`, v0.23.0 T6): a `message` (the spill's), a
`scene` (a scene's narration, one row per turn, written by `append` from
T13 on: §7.1 keeps scene narration out of memory) and a `recap` (a person's
memory moved out of state whole: a dormant person's shelf or a fold's
record, `memory.compact_dormant`, `memory.job_record`). A scene row carries
`"row": "scene"`, its thread's id and a message number, and pages like a
message. A recap row carries `"row": "recap"`, the person's `pid` and its
own `id`, and no thread: no page or thread read ever sees it
(`archived_memory` reads them).

Reading (`page`) is read-only: state's rows first, then the file's, newest
first, `before` a message id, at most `PAGE_MAX` at a time, each row as the
client may see it (`messaging.message_view`: no decision, no words before
it is voiced). It reads the file from its END and stops once it holds the
page (`archived_before`), so a page costs what it shows, not the run's
length: the route reads under the turn lock (v0.22.0 T26 measured the whole
file's read at about 18-24 ms a page for a day-60 save's 335 KB archive, growing
with every day played).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

from engine import social
from engine.game.effects import apply_effect
from engine.game.state import GameState

logger = logging.getLogger(__name__)

#: The file, in the run's save directory.
ARCHIVE_FILE = "phone_archive.jsonl"

#: The most rows one page returns (`GET /api/phone/thread/<thread_id>`).
PAGE_MAX = 50

#: The kinds of archive row (`append`): the spill's messages, and a scene's narration (T13 writes them).
ROW_KINDS: tuple[str, ...] = ("message", "scene", "recap")


def _keep() -> int:
    return max(1, int(social.setting("state_messages", 8)))


def keep_for(state: GameState, t: dict[str, Any]) -> int:
    """
    How many of a thread's newest messages state keeps (v0.23.0 T9 fix round 2; spec §7.1, R8): the
    conversation going on in it (the person's open episode, from its start), every message of theirs the
    player has not read, the last turn the conversation's own reads count (`_last_turn`), and, for the
    thread the player has open, one screen (`social.state_messages`); any
    other thread keeps `social.closed_thread_tail` (0): its last word is its stamp, the person's memory
    holds what the voice reads, and the client pages the rest from the archive (`page`).
    """
    from engine.social import convo, messaging   # lazily: convo imports messaging, which imports this module

    tid = str(t.get("thread_id") or "")
    tail = _keep() if tid == str(state.social.get("open_thread") or "") else max(
        0, int(social.setting("closed_thread_tail", 0)))
    messages = t.get("messages") or []
    going = 0
    ep = convo.episode(state, str(t.get("pid") or ""))
    if ep is not None and str(ep.get("thread_id") or "") == tid:
        start = float(ep.get("started_at") or 0.0) - 1e-9
        going = sum(1 for m in messages if float(m.get("at") or 0.0) >= start)
    pid = str(t.get("pid") or "")
    # From the player's oldest unread message of theirs on (the badge and the lock screen count them).
    unread = next((len(messages) - i for i, m in enumerate(messages)
                   if m.get("from") == pid and m.get("read_at") is None and messaging.shown(m)), 0)
    return max(tail, unread, going, _last_turn(messages, pid))


#: The player's run the conversation reads (`convo.decide`: a burst of this many raises the reply's floor).
BURST_READ = 3


def _last_turn(messages: list[dict[str, Any]], pid: str) -> int:
    """
    The last turn's messages, which the conversation's own reads count: their run since the player last
    wrote with the player's message before it (`messaging._in_a_row`, the double-text cap), or the
    player's run since they last wrote (`convo._last_player_text`, `messaging.player_burst`) -- up to
    `BURST_READ` of it, with their message before it when the run is shorter.
    """
    from engine.social import messaging

    spoken = [i for i, m in enumerate(messages) if m.get("from") in (pid, "player") and messaging.shown(m)]
    if not spoken:
        return 0
    last = messages[spoken[-1]].get("from")
    run = [i for i in spoken if messages[i].get("from") == last]
    other = [i for i in spoken if messages[i].get("from") != last]
    start = (other[-1] + 1) if other else 0
    run_start = min(i for i in run if i >= start)
    if last == "player":
        count = sum(1 for i in run if i >= run_start)
        if count >= BURST_READ:
            return len(messages) - [i for i in run if i >= run_start][-BURST_READ]
    anchor = other[-1] if other else run_start
    return len(messages) - anchor


def _dead_after_hours() -> float:
    return max(0.0, float(social.setting("archive_dead_after_days", 7))) * 24.0


#: A person at one of these has left the relationship (or the player left them): their thread is dead.
DEAD_STAGES: tuple[str, ...] = ("faded", "ended")


def dead(state: GameState, t: dict[str, Any]) -> bool:
    """
    A thread to empty whole (spec §17.2's bound, v0.22.0 T26): not the open
    thread, nothing due or unread in it, quiet -- its last message `social.archive_dead_after_days`
    old -- and either its person faded, ended, unmatched or blocked, or it is
    left behind: another thread of theirs has a later message (they moved to a
    messenger once numbers were swapped). A person who writes in it again
    writes into it as before (`messaging._stamp` answers for what left).
    """
    from engine.social import apps, messaging

    messages = t.get("messages") or []
    if not messages or int(t.get("unread") or 0) or any(m.get("voiced") is False for m in messages):
        return False
    last = float(messages[-1]["at"])
    if state.world_clock_hours - last < _dead_after_hours():
        return False
    if t.get("thread_id") == state.social.get("open_thread"):
        return False                                   # the open thread's section shows its messages (§17.3)
    pid = str(t.get("pid") or "")
    person = (state.social.get("people") or {}).get(pid) or {}
    if person.get("stage") in DEAD_STAGES or apps.gone(state, pid):
        return True
    return any(other is not t and other.get("pid") == pid and messaging.last_at(other) > last
               for other in (state.social.get("threads") or {}).values())


def _spillable(messages: list[dict[str, Any]], keep: int) -> int:
    """How many of the oldest rows may leave: those past `keep`, up to the first due (unvoiced) one."""
    count = 0
    for message in messages[: max(0, len(messages) - keep)]:
        if message.get("voiced") is False:
            break
        count += 1
    return count


def save_dir(session: Any) -> Optional[Path]:
    """The run's save directory, or None for a run not yet saved."""
    if not getattr(session, "save_id", ""):
        return None
    store = getattr(session, "saves", None)
    if store is None:
        from engine.persistence import get_save_store

        store = get_save_store()
    return Path(store.path_for(session.save_id))


def spill(session: Any) -> int:
    """
    Move each thread's messages past what it keeps (`keep_for`) out of state into
    the save directory's archive (CALLER HOLDS the turn lock). Returns how
    many moved. Nothing moves when the run has no save directory yet -- it is
    never created here, so a purged folder stays gone -- or when the append
    fails (the rows stay in state; the next save tries again). Never raises.
    """
    state = session.engine.state
    threads = (state.social or {}).get("threads") or {}
    plan = [(tid, len(t["messages"]) if dead(state, t) else _spillable(t.get("messages") or [], keep_for(state, t)))
            for tid, t in sorted(threads.items())]
    plan = [(tid, n) for tid, n in plan if n]
    if not plan:
        return 0
    try:
        directory = save_dir(session)
    except ValueError as exc:   # an id the store refuses
        logger.warning("[social] Archive skipped (operation=spill, id=%s): %s", session.session_id, exc)
        return 0
    if directory is None or not directory.is_dir():
        return 0
    if not append(directory, [m for tid, n in plan for m in threads[tid]["messages"][:n]]):
        logger.warning("[social] Archive append failed; the messages stay in state (operation=spill, id=%s)",
                       session.session_id)
        return 0
    moved = 0
    for tid, n in plan:
        result = apply_effect(state, {"type": "social_message", "op": "archive", "thread_id": tid, "count": n})
        moved += len(result.get("messages") or []) if result.get("ok") else 0
    return moved


def append(directory: Optional[Path], rows: list[dict[str, Any]], *, kind: str = "message") -> bool:
    """
    ``rows`` appended to the save directory's archive, one JSON line each
    (CALLER HOLDS the turn lock): `message` rows as they are, `scene` rows
    stamped ``"row": "scene"`` (``kind``, one of `ROW_KINDS`; a scene row
    with no `from` or `kind` reads as the system's ``scene``), `recap` rows
    stamped ``"row": "recap"``. A message or scene row must name its thread
    and carry a message number (``m<n>``), so it pages like a message; a
    recap row must name its person (`pid`) and its `id`, and names no
    thread. A torn last line is closed off first. True when written; False
    with no directory or when the write fails (nothing is written).
    """
    if kind not in ROW_KINDS:
        raise ValueError(f"archive.append: {kind!r} is not one of {', '.join(ROW_KINDS)}")
    out: list[dict[str, Any]] = []
    for row in rows:
        if kind == "recap":
            if not row.get("pid") or not row.get("id") or row.get("thread_id"):
                raise ValueError("archive.append: a recap row needs its pid and id, and no thread")
            out.append({**row, "row": kind})
            continue
        if not row.get("thread_id") or _number(row.get("id")) < 0:
            raise ValueError(f"archive.append: a row needs its thread and a message number, not {row.get('id')!r}")
        out.append(row if kind == "message" else {"from": "system", "kind": "scene", **row, "row": kind})
    if directory is None:
        return False
    if not out:
        return True
    path = directory / ARCHIVE_FILE
    try:
        # A torn last line (a crash mid-append) is closed off first, so this
        # batch's first row never glues onto it and is lost with it.
        lead = "\n" if _torn(path) else ""
        with path.open("a", encoding="utf-8") as handle:
            handle.write(lead + "\n".join(json.dumps(r, ensure_ascii=False, default=str) for r in out) + "\n")
    except OSError as exc:
        logger.warning("[social] Archive append failed (operation=append, path=%s): %s", path, exc)
        return False
    return True


def _torn(path: Path) -> bool:
    """Whether the file exists, is not empty, and does not end in a newline."""
    try:
        with path.open("rb") as handle:
            handle.seek(0, 2)
            if handle.tell() == 0:
                return False
            handle.seek(-1, 2)
            return handle.read(1) != b"\n"
    except FileNotFoundError:
        return False


def _number(message_id: Any) -> int:
    text = str(message_id or "")
    return int(text[1:]) if text[:1] == "m" and text[1:].isdigit() else -1


def archived(directory: Optional[Path], thread_id: str) -> list[dict[str, Any]]:
    """The file's rows for one thread, in the order written; a bad line is skipped."""
    if directory is None:
        return []
    path = directory / ARCHIVE_FILE
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning("[social] Archive unreadable (operation=page, path=%s): %s", path, exc)
        return []
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and row.get("thread_id") == thread_id and _number(row.get("id")) >= 0:
            rows.append(row)
    return rows


#: How many bytes `archived_after` reads at a time, from the file's end.
TAIL_BLOCK = 65536


def archived_after(directory: Path, thread_id: str, after: int) -> Optional[list[dict[str, Any]]]:
    """
    One thread's archived rows with a message number above ``after``, in
    the order written, read from the file's END and stopping at that
    thread's first row at or below ``after`` (the thread summary's read,
    `memory.with_archive`): its cost is what the summary has not read, not
    the run's length. Rows of one thread are written in id order, a crash
    duplicate repeating only the newest batch, so nothing above ``after``
    lies before that row. A bad or torn line is skipped. None when the file
    is missing or cannot be read.
    """
    path = directory / ARCHIVE_FILE
    found: list[dict[str, Any]] = []
    try:
        with path.open("rb") as handle:
            handle.seek(0, 2)
            pos = handle.tell()
            carry = b""
            while pos > 0:
                size = min(TAIL_BLOCK, pos)
                pos -= size
                handle.seek(pos)
                lines = (handle.read(size) + carry).split(b"\n")
                carry = lines.pop(0) if pos > 0 else b""   # may be the tail of an earlier line
                for raw in reversed(lines):
                    try:
                        row = json.loads(raw.decode("utf-8")) if raw.strip() else None
                    except ValueError:
                        continue
                    if not isinstance(row, dict) or row.get("thread_id") != thread_id:
                        continue
                    number = _number(row.get("id"))
                    if number < 0:
                        continue
                    if number <= after:
                        return list(reversed(found))
                    found.append(row)
    except OSError as exc:
        logger.warning("[social] Archive unreadable (operation=archived_after, path=%s): %s", path, exc)
        return None
    return list(reversed(found))


def archived_between(directory: Optional[Path], thread_id: str, below: int, low: float,
                     high: float) -> tuple[list[dict[str, Any]], bool]:
    """
    One thread's archived rows numbered below ``below`` (any, when it is
    negative) whose `at` lies in ``[low, high]``, oldest first, read from
    the file's END and stopping at the first row of the thread older than
    ``low`` (a thread's rows are written in id and time order; a crash
    duplicate is dropped by id): an episode's window, however far back it
    lies (`memory.with_archive`, review M2). With it, whether the read got
    back past ``low`` -- False means the file ended (or could not be read)
    before the window's start, so rows may be missing.
    """
    if directory is None:
        return [], False
    path = directory / ARCHIVE_FILE
    found: dict[str, dict[str, Any]] = {}
    needle = json.dumps(thread_id, ensure_ascii=False).encode("utf-8")
    try:
        with path.open("rb") as handle:
            handle.seek(0, 2)
            pos = handle.tell()
            carry = b""
            while pos > 0:
                size = min(TAIL_BLOCK, pos)
                pos -= size
                handle.seek(pos)
                lines = (handle.read(size) + carry).split(b"\n")
                carry = lines.pop(0) if pos > 0 else b""   # may be the tail of an earlier line
                for raw in reversed(lines):
                    if needle not in raw:
                        continue
                    try:
                        row = json.loads(raw.decode("utf-8"))
                    except ValueError:
                        continue
                    if not isinstance(row, dict) or row.get("thread_id") != thread_id:
                        continue
                    number = _number(row.get("id"))
                    if number < 0 or (below >= 0 and number >= below):
                        continue
                    at = float(row.get("at") or 0.0)
                    if at < low:
                        return sorted(found.values(), key=lambda r: _number(r.get("id"))), True
                    if at <= high:
                        found.setdefault(str(row["id"]), row)
    except FileNotFoundError:
        return [], False
    except OSError as exc:
        logger.warning("[social] Archive unreadable (operation=archived_between, path=%s): %s", path, exc)
        return [], False
    return sorted(found.values(), key=lambda r: _number(r.get("id"))), False


def archived_memory(directory: Optional[Path], pid: str) -> Optional[list[dict[str, Any]]]:
    """
    Every `recap` row of ``pid`` (a dormant shelf, a fold's record), in the
    order written (NO lock: the file is append-only); a crash duplicate is
    dropped by id. None when the file is missing or cannot be read.
    """
    if directory is None:
        return None
    path = directory / ARCHIVE_FILE
    needle = json.dumps(str(pid), ensure_ascii=False)
    rows: dict[str, dict[str, Any]] = {}
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if '"recap"' not in line or needle not in line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if isinstance(row, dict) and row.get("row") == "recap" and row.get("pid") == pid:
                    rows.setdefault(str(row.get("id")), row)
    except FileNotFoundError:
        return None
    except OSError as exc:
        logger.warning("[social] Archive unreadable (operation=archived_memory, path=%s): %s", path, exc)
        return None
    return list(rows.values())


def archived_before(directory: Optional[Path], thread_id: str, below: int, want: int,
                    skip: frozenset[str] = frozenset()) -> list[dict[str, Any]]:
    """
    One thread's archived rows with a message number below ``below`` (any,
    when it is negative), newest first, read from the file's END and stopping
    once ``want`` of them are shown (`messaging.shown`): a page's read. Each
    message once (a crash duplicate dropped by id); ids in ``skip`` (state's
    own copies) left out. A bad or torn line is skipped; a missing or
    unreadable file reads as empty.
    """
    from engine.social import messaging

    if directory is None or want <= 0:
        return []
    path = directory / ARCHIVE_FILE
    found: list[dict[str, Any]] = []
    seen: set[str] = set()
    shown = 0
    # A line that does not hold the thread's id, quoted, is another thread's: never decoded.
    needle = json.dumps(thread_id, ensure_ascii=False).encode("utf-8")
    try:
        with path.open("rb") as handle:
            handle.seek(0, 2)
            pos = handle.tell()
            carry = b""
            while pos > 0:
                size = min(TAIL_BLOCK, pos)
                pos -= size
                handle.seek(pos)
                lines = (handle.read(size) + carry).split(b"\n")
                carry = lines.pop(0) if pos > 0 else b""   # may be the tail of an earlier line
                for raw in reversed(lines):
                    if needle not in raw:
                        continue
                    try:
                        row = json.loads(raw.decode("utf-8"))
                    except ValueError:
                        continue
                    if not isinstance(row, dict) or row.get("thread_id") != thread_id:
                        continue
                    number, mid = _number(row.get("id")), str(row.get("id"))
                    if number < 0 or (below >= 0 and number >= below) or mid in skip or mid in seen:
                        continue
                    seen.add(mid)
                    found.append(row)
                    shown += bool(messaging.shown(row))
                    if shown >= want:
                        return found
    except FileNotFoundError:
        return []
    except OSError as exc:
        logger.warning("[social] Archive unreadable (operation=page, path=%s): %s", path, exc)
        return []
    return found


def archived_message(directory: Optional[Path], thread_id: str, message_id: str) -> Optional[dict[str, Any]]:
    """One archived message by id (a tail read, `archived_before`), or None when the archive lacks it."""
    number = _number(message_id)
    if number < 0:
        return None
    rows = archived_before(directory, thread_id, number + 1, 1)
    return next((r for r in rows if str(r.get("id")) == str(message_id)), None)


def page(save_dir: Optional[Path], state: GameState, thread_id: str, before: str, limit: int) -> dict[str, Any]:
    """
    One page of a thread, newest first: state's rows, then the archive's,
    each message once (a crash duplicate dropped by id), only those older
    than `before` when it names a message, at most `limit` (1..PAGE_MAX).
    `more` says whether older rows remain.
    """
    from engine.social import messaging

    t = messaging.thread(state, thread_id)
    if t is None:
        return {"thread_id": thread_id, "messages": [], "more": False}
    size = max(1, min(PAGE_MAX, int(limit or PAGE_MAX)))
    cut = _number(before)
    rows: dict[str, dict[str, Any]] = {}
    for row in t.get("messages") or []:
        rows.setdefault(str(row["id"]), row)
    held = sum(1 for m in rows.values() if messaging.shown(m) and (cut < 0 or _number(m.get("id")) < cut))
    # The archive's rows are older than state's: only as many as the page still needs (one more says `more`).
    for row in archived_before(save_dir, thread_id, cut, size + 1 - held, frozenset(rows)):
        rows.setdefault(str(row["id"]), row)   # state's own copy wins
    ordered = sorted((m for m in rows.values() if messaging.shown(m)), key=lambda m: _number(m.get("id")),
                     reverse=True)
    if cut >= 0:
        ordered = [m for m in ordered if _number(m.get("id")) < cut]
    return {"thread_id": thread_id, "messages": [messaging.message_view(state, t, m) for m in ordered[:size]],
            "more": len(ordered) > size}


__all__ = ["ARCHIVE_FILE", "PAGE_MAX", "ROW_KINDS", "append", "archived", "archived_after", "archived_before",
           "archived_between", "archived_memory", "archived_message", "dead", "page", "save_dir", "spill"]
