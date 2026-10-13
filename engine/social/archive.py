"""
The phone's message archive (v0.22.0 spec §17.2, Plan decision 18).

State keeps `social.state_messages` (60) messages per thread; older ones move
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

The thread summary reads the file too (`archived_after`, from
`memory.with_archive`, off the turn lock, from the file's end), for
messages the spill took past the summary: the spill runs under the turn
lock, where no model may be called, so it never summarises first.

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


def _keep() -> int:
    return max(1, int(social.setting("state_messages", 60)))


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
    return any(other is not t and other.get("pid") == pid and messaging._last_at(other) > last
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
    Move each thread's messages past `social.state_messages` out of state into
    the save directory's archive (CALLER HOLDS the turn lock). Returns how
    many moved. Nothing moves when the run has no save directory yet -- it is
    never created here, so a purged folder stays gone -- or when the append
    fails (the rows stay in state; the next save tries again). Never raises.
    """
    state = session.engine.state
    threads = (state.social or {}).get("threads") or {}
    keep = _keep()
    plan = [(tid, len(t["messages"]) if dead(state, t) else _spillable(t.get("messages") or [], keep))
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
    lines = [json.dumps(m, ensure_ascii=False, default=str) for tid, n in plan for m in threads[tid]["messages"][:n]]
    path = directory / ARCHIVE_FILE
    try:
        # A torn last line (a crash mid-append) is closed off first, so this
        # batch's first row never glues onto it and is lost with it.
        lead = "\n" if _torn(path) else ""
        with path.open("a", encoding="utf-8") as handle:
            handle.write(lead + "\n".join(lines) + "\n")
    except OSError as exc:
        logger.warning("[social] Archive append failed; the messages stay in state "
                       "(operation=spill, id=%s): %s", session.session_id, exc)
        return 0
    moved = 0
    for tid, n in plan:
        result = apply_effect(state, {"type": "social_message", "op": "archive", "thread_id": tid, "count": n})
        moved += len(result.get("messages") or []) if result.get("ok") else 0
    return moved


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


__all__ = ["ARCHIVE_FILE", "PAGE_MAX", "archived", "archived_after", "archived_before", "archived_message", "dead",
           "page", "save_dir", "spill"]
