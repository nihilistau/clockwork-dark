"""
READ RECEIPTS' Balance Harness
==============================

Play READ RECEIPTS headlessly with a scripted player and report the numbers
that decide whether its phone is tuned (AGENTS.md rule 10; v0.22.0 spec §20):
match rates, how often a match turns into a conversation, ghosting, reply
latency, how fast each archetype warms, and how many relationships an
attentive player keeps going.

WHAT IS REAL AND WHAT IS NOT. Every action -- a swipe, a like, a message, an
ask, an answer, a wait -- goes through ``engine.social.turn.run_mechanics``,
the phone's own mechanics action, so legality, refusals, costs, the event
queue and every draw are the engine's. After each action the due messages are
voiced by ``engine.social.voicer.run_until_quiet`` on this thread, exactly the
pass a player's phone runs (no scheduler, no admission, no threads). The
"model" is a deterministic stub, never a model server: ``neutral_model``
(the default, T26: a working model's pleasant, unremarkable replies)
proposes warmth +1 trust +1 on every reply, ``romantic_model`` +3/+1,
``cold_model`` -2/-1, ``zero`` 0/0, and ``no_model`` calls nothing, so
every reply is the engine's fallback line, which proposes relationships.yaml
``regard.fallback`` (no more than the neutral model's). No stub proposes
anything (§10.5), so every photo, voice note and video a run measures is the
engine's own: unasked, or answering the player. The thread
summary is the deterministic fallback. Time passes only through the ``wait``
action (``clock.advance_time``).

THE SESSION is built by ``SessionStore.create`` over a save store that keeps
nothing (``_KeepsNothing``, ``keeps_nothing = True``; Plan decision 28), so a
run writes no save, starts no DirtySaver thread, and the voicing pass's
generation check asks THIS store -- not the app's -- whether the run is live.

THE PLAYER POLICIES (what the player does; the people are the engine's):

  attentive   Checks the phone whenever it buzzes, 08:00-23:00. Each morning
              likes about half the Matchstick cards it is shown (15 likes),
              four Front Porch profiles, and everyone in Likes you. Writes
              first to every match, answers every message, asks for a
              number once the closeness band shows warming, at most every
              two days per person, and says yes to every request.
  swiper      Likes every card (the daily limit on both apps), answers at
              09, 13, 18 and 22 o'clock.
  picky       Likes one card in seven (5 Matchstick, 2 Front Porch), else
              the attentive player.
  slow        The attentive player who looks at the phone at 09, 15 and 21.
  neglectful  Likes like the attentive player, writes first half the time,
              looks twice a day and answers only on even days; never asks.
  pushy       The attentive player who sends two messages each time and asks
              for a number at every look once a person is talking.

              Every policy that asks (all but neglectful) also asks to meet
              anyone at numbers or past it with nothing planned or asked,
              at most every three days per person, and goes to every
              meet-up that comes due (T26).

REPORT ROWS (``REPORT_ROWS``, the plan's Shared interfaces; banded by
``tests/test_simulate_social.py``). A row with nothing to measure reports
``None``. Each window is censored at the run's end: a match counts
toward a 3-day row only if it was made at least 3 days before the end, and
likewise for 14 and 21 days.

  like_to_match.<app>   matches / likes on that app, likes made at least 3
                        days before the end; Front Porch counts its like-backs
                        too (apps.yaml's header)
  match_to_talking_3d   matched people at stage talking within 3 days
  match_to_message_3d   matched people who wrote ANY message (an opener, a
                        reply) within 3 days -- the player's own writing is
                        the policy's, so it is not what this measures
  talking_to_ghosted_14d   talking people who ghosted within 14 days
  talking_to_numbers_21d.attentive   talking people at numbers within 21
                        days (measured under the run's policy; banded for
                        attentive)
  interest_half_life_days   per person, a spell of 3+ mornings with no
                        contact, up to the morning interest reaches 0:
                        (interest at its start / 2) / interest lost per day;
                        the median
  live_relationships_day30.attentive   people at talking or beyond, still
                        live, not ghosted and not gone, on the morning of day
                        30 (None for a run shorter than 30 days)
  messages_per_day.attentive   messages the people sent, per in-game day
  numbers_to_meet_21d   people at numbers who met the player (a meet-up
                        gone to and resolved) within 21 days
  meet_band.<band>      of the meet-ups resolved, the share in that band
  photos_per_close_week   photos they sent per week of relationship from
                        reaching "close" to the run's end or their leaving
  voice_per_relationship_week_after_numbers   likewise voice notes, from
                        reaching numbers
  videos_per_close_month   likewise videos, from "close", per 30 days
  turners_turned_60d    turners whose turn fired within 60 days of reaching
                        talking, of those who reached it at least 60 days
                        before the run's end: None for any run of 60 days or
                        fewer (the row needs --days of about 75 or more)
  events_per_72h_away_day60   a run of 60 days or more ends with the
                        player 72 hours away (one away advance, after every
                        other row is measured); the most queued events any
                        run's advance applied (None for a shorter run)
  days_to_<band>.<archetype>   median days from match to that closeness
                        band, over the people of that archetype who got there

Also reported (``also.*``, unbanded): reply latency in minutes (median and
p90), the share of threads whose last word is the player's, ghosts per talking
person, matches, people talking and at numbers, actions and refusals per run,
the ten commonest refusals (action and reason) per run, meet-ups by status,
and after the 72-hour away: the due messages its first voicing pass finds
(p95, spec §20's last row) and the planned meet-ups it made no-shows.

ON DISK (``--disk DIR``, ``run(disk=...)``): the run saves under a real save
store and spills every thread past ``social.state_messages`` into its
``phone_archive.jsonl`` after each action, as play's saves do; the
measurements read the archive too, so a run measures the same on disk or off
(a test holds it). ``write_day_save`` writes the day-N save the size bound
pins (spec §17.2).
The same seeds give the same report (the wall time is printed, never
reported).

Usage:
    python scripts/simulate_social.py --game read-receipts --days 60 --seeds 40 --policy attentive
    python scripts/simulate_social.py --game read-receipts --policy all --voice all --seeds 10
    python scripts/simulate_social.py --game read-receipts --policy attentive --voice no_model --json out.json
    # 40 seeds side by side, in four shells, then one report:
    python scripts/simulate_social.py --game read-receipts --first-seed 0 --seeds 10 --raw r0.json
    ...
    python scripts/simulate_social.py --game read-receipts --fold r0.json r10.json r20.json r30.json
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import statistics
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, Optional

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

#: The story this harness plays (it refuses any other ``--game``).
SLUG = "read-receipts"

#: The report's rows, defined ONCE in the plan's Shared interfaces (pre-flight F26).
REPORT_ROWS: tuple[str, ...] = (
    "like_to_match.matchstick", "like_to_match.front_porch",
    "match_to_talking_3d", "match_to_message_3d",
    "talking_to_ghosted_14d", "talking_to_numbers_21d.attentive",
    "numbers_to_meet_21d",
    "meet_band.great", "meet_band.good", "meet_band.fine", "meet_band.awkward", "meet_band.bad",
    "interest_half_life_days", "live_relationships_day30.attentive", "messages_per_day.attentive",
    "photos_per_close_week", "voice_per_relationship_week_after_numbers", "videos_per_close_month",
    "turners_turned_60d", "events_per_72h_away_day60",
)

#: ``events_per_72h_away_day60``: a run of at least this many days ends with one
#: 72-hour away advance (spec §15.2, §20), whose applied events it counts. Shorter
#: runs are censored (None).
AWAY_ROW_DAYS = 60
AWAY_ROW_HOURS = 72.0

#: The harness's wall clock (seconds since the epoch): the away advance is
#: measured from it, never from the real clock, so a run replays.
WALL_EPOCH = 1_800_000_000.0

#: The closeness bands a ``days_to_*`` row is reported for (relationships.yaml ``bands``).
BAND_ROWS: tuple[tuple[str, str], ...] = (("warming", "warming"), ("close", "close"),
                                         ("very_close", "very close"))

#: The stub "model"'s replies, by policy: the same as tests/social_stub.py (a test holds them equal).
#: `neutral` (T26) is a WORKING model writing pleasant, unremarkable replies: what the shipped
#: constants are tuned against, and what a dead model server's fallback must not out-progress.
STUB_POLICIES: dict[str, tuple[str, dict[str, Any]]] = {
    "warm": ("that sounds lovely, tell me more", {"warmth": 3, "trust": 1, "mood": "fond"}),
    "cold": ("ok", {"warmth": -2, "trust": -1, "mood": "annoyed"}),
    "neutral": ("sure, sounds good", {"warmth": 1, "trust": 1, "mood": "neutral"}),
    "zero": ("sure", {"warmth": 0, "trust": 0, "mood": "neutral"}),
    "wordy": ("honestly that's such a good point, I keep thinking about it",
              {"warmth": 0, "trust": 0, "mood": "neutral"}),
}

#: The voice policies (spec §20): a name -> the stub policy, or None for no model (the fallback).
VOICES: dict[str, Optional[str]] = {
    "neutral_model": "neutral",
    "romantic_model": "warm",
    "cold_model": "cold",
    "zero": "zero",
    "no_model": None,
}

#: The voice a run gets unless it names one: the working neutral model (T26), which the bands
#: (tests/test_simulate_social.py) are pinned under.
DEFAULT_VOICE = "neutral_model"

#: The player's actions that like someone: a swipe, a Front Porch like, a like back from "Likes you".
LIKE_ACTIONS: frozenset[str] = frozenset({"swipe", "like", "like_back"})

HOUR_WAKE = 8.0
HOUR_BED = 23.0


# ---------------------------------------------------------------------------
# The stub voice and the session
# ---------------------------------------------------------------------------


class StubVoice:
    """A scripted ``llm_fn``: one bubble, the policy's regard, nothing learned or shared, no proposal."""

    def __init__(self, policy: str) -> None:
        if policy not in STUB_POLICIES:
            raise ValueError(f"StubVoice: no policy {policy!r} ({', '.join(STUB_POLICIES)})")
        self.policy = policy
        self.calls = 0

    def __call__(self, messages: list[dict[str, Any]], fmt: dict[str, Any]) -> str:
        self.calls += 1
        text, regard = STUB_POLICIES[self.policy]
        props = (((fmt or {}).get("json_schema") or {}).get("schema") or {}).get("properties") or {}
        out: dict[str, Any] = {"bubbles": [{"text": text}], "regard": dict(regard), "learned": [], "shared": []}
        if "proposals" in props:
            out["proposals"] = []
        if "media" in props:
            out["media"] = {"caption": "this one's for you"}
        return json.dumps(out)


def llm_for(voice_policy: str) -> Optional[StubVoice]:
    """The ``llm_fn`` for a voice policy: a ``VOICES`` name or a stub policy name; None is no model."""
    if voice_policy in VOICES:
        stub = VOICES[voice_policy]
        return None if stub is None else StubVoice(stub)
    if voice_policy in STUB_POLICIES:
        return StubVoice(voice_policy)
    raise ValueError(f"simulate_social: no voice policy {voice_policy!r} "
                     f"({', '.join([*VOICES, *STUB_POLICIES])})")


class _KeepsNothing:
    """A save store that writes nothing and keeps nothing (Plan decision 28): no file, no timer, no thread."""

    keeps_nothing = True

    def save(self, state: Any, **_: Any) -> str:
        return ""


_KEEPS_NOTHING = _KeepsNothing()


def _disk_store(root: Path) -> Any:
    """
    A REAL save store under ``root`` that starts no timer (``keeps_nothing``,
    so ``mark_dirty`` schedules nothing and the run stays on one thread): the
    harness spills each thread past ``social.state_messages`` into the run's
    ``phone_archive.jsonl`` itself, after every action (``Phone.spill``), as
    play's saves do, and ``write_day_save`` writes ``save.json`` at the end.
    """
    from engine.persistence import SaveStore

    class _Disk(SaveStore):
        keeps_nothing = True

    return _Disk(root=Path(root), slug=SLUG)


def _ensure_active() -> None:
    """READ RECEIPTS active and its social package booted (a no-op when a caller already did)."""
    from engine import social
    from engine.games import registry

    manifest = registry.peek()
    if manifest is None or manifest.slug != SLUG:
        registry.activate(SLUG)
    social.boot()


#: A voicing pass's wall-clock deadline for the run: past any run's length, so no reply in a run
#: becomes a "deadline" fallback because the machine was slow (a replay never reads the wall clock).
PASS_DEADLINE_SECONDS = 1e9


@contextmanager
def _quiet_summaries() -> Iterator[None]:
    """
    For the run: the thread summary's deterministic fallback (never a model),
    and the pass deadline pinned past reach (``PASS_DEADLINE_SECONDS``); both
    restored after.
    """
    from engine.social import voicer

    before = voicer._summary_fn
    deadline = voicer._deadline_seconds
    voicer.set_summary_fn(lambda messages: "")
    voicer._deadline_seconds = lambda: PASS_DEADLINE_SECONDS   # type: ignore[assignment]
    try:
        yield
    finally:
        voicer._deadline_seconds = deadline                    # type: ignore[assignment]
        voicer.set_summary_fn(before)


class Phone:
    """One run: a session in a keeps-nothing store, its stub voice, and one action at a time."""

    def __init__(self, seed: int, voice_policy: str, *, disk: Optional[Path] = None) -> None:
        from engine.scenes.default_state import SessionStore

        _ensure_active()
        saves = _disk_store(Path(disk)) if disk is not None else _KEEPS_NOTHING
        self.store = SessionStore(save_store=lambda: saves)
        self.session = self.store.create(seed=seed, player_name="Sam", llm_fn=lambda m, **k: "{}")
        self.state = self.session.engine.state
        #: A run on disk spills its threads into the archive after every action, as play's saves do.
        self.disk = disk is not None
        if self.disk and not self.session.save_id:   # the store's create saved the opening already
            self.session.saves = saves
            self.session.save_id = saves.save(self.state, memory=self.session.ledger.to_dict())
        self.llm = llm_for(voice_policy)
        self.actions = 0
        self.refused = 0
        #: Refusals by "<action>: <reason>", the person's name read as <name>.
        self.refusals: dict[str, int] = {}
        self.payload: dict[str, Any] = {}
        #: (app, pid) -> when the player liked them (``_note_like``).
        self.likes: dict[tuple[str, str], float] = {}
        self.observers: list[Callable[["Phone"], None]] = []
        self.act("wait", args={"until": "15m"})   # a first payload to read (and the queue's first events)

    @property
    def now(self) -> float:
        return float(self.state.world_clock_hours)

    @property
    def phone(self) -> dict[str, Any]:
        return (self.payload.get("state") or {}).get("phone") or {}

    def act(self, action: str, target: str = "", args: Optional[dict[str, Any]] = None,
            text: str = "") -> dict[str, Any]:
        """One phone action through the mechanics action, then voicing until quiet: the receipt."""
        from engine.session.store import release_turn
        from engine.social import turn, voicer

        intent = {"action": action, "target": target, "args": dict(args or {}), "text": text}
        if not self.session.lock.acquire(blocking=False):      # this thread is the run's only one
            raise RuntimeError("simulate_social: the run's turn lock is held")
        try:
            self.payload = turn.run_mechanics(self.session, action, intent)
        finally:
            release_turn(self.session)                     # as run_guarded lets it go (Plan decision 31)
        voicer.run_until_quiet(self.session, self.llm)
        if action in LIKE_ACTIONS:
            self._note_like(target)
        self.spill()
        receipt = (self.payload.get("receipts") or [{}])[0]
        self._rebuild(receipt)
        self.actions += 1
        if receipt.get("refused"):
            self.refused += 1
            reason = str((receipt.get("result") or {}).get("error") or "")
            key = f"{action}: {self._unnamed(reason, target)}"
            self.refusals[key] = self.refusals.get(key, 0) + 1
        for observe in self.observers:
            observe(self)
        return receipt

    def _note_like(self, pid: str) -> None:
        """
        A like the player made (``LIKE_ACTIONS``), with its time, as the
        person's app row has it the moment it is made: a save compacts a
        swiped-only row to its swipe alone (``saves.compact``), so the report
        reads the likes from here, on disk or off.
        """
        rows = ((self.state.social.get("people") or {}).get(pid) or {}).get("apps") or {}
        for app, row in rows.items():
            if isinstance(row, dict) and row.get("swiped") in ("like", "super") and row.get("at") is not None:
                self.likes.setdefault((app, pid), float(row["at"]))

    def spill(self) -> int:
        """
        A run on disk: what the phone's save makes of state (``saves.compact``):
        threads past ``social.state_messages``, and dead ones whole, to the
        archive; swiped-only people cut to their swipe.
        """
        from engine.session.store import release_turn
        from engine.social import saves

        if not self.disk:
            return 0
        if not self.session.lock.acquire(blocking=False):
            raise RuntimeError("simulate_social: the run's turn lock is held")
        try:
            return saves.compact(self.session)
        finally:
            release_turn(self.session)

    def messages(self, thread: dict[str, Any]) -> list[dict[str, Any]]:
        """A thread's every message, oldest first: the archive's (a run on disk), then state's, each once."""
        from engine.social import archive

        rows = list(thread.get("messages") or [])
        if not self.disk:
            return rows
        older = archive.archived(archive.save_dir(self.session), str(thread["thread_id"]))
        seen: set[str] = set()
        out = []
        for m in older + rows:
            if str(m["id"]) not in seen:
                seen.add(str(m["id"]))
                out.append(m)
        return out

    def _rebuild(self, receipt: dict[str, Any]) -> None:
        """
        The payload again, AFTER the action's voicing: in play each voiced
        reply reaches the phone as it lands (a `phone_message` push), so the
        player never sees one still "pending" that has been written.
        """
        from engine.session.store import release_turn
        from engine.social import payload

        if not self.session.lock.acquire(blocking=False):
            raise RuntimeError("simulate_social: the run's turn lock is held")
        try:
            with payload.building(self.session, receipt):
                self.payload = {**self.payload, "state": self.state.to_client_dict()}
        finally:
            release_turn(self.session)

    def _unnamed(self, reason: str, target: str) -> str:
        """A refusal's words with the person's name as <name>, so reasons count together."""
        from engine.social import population

        threads = self.state.social.get("threads") or {}
        requests = self.state.social.get("requests") or {}
        pid = ((threads.get(target) or {}).get("pid") or (requests.get(target) or {}).get("pid") or target)
        try:
            name = population.profile(self.state, str(pid)).name
        except (ValueError, KeyError, IndexError):
            return reason
        return reason.replace(name, "<name>") if name else reason

    def away(self, hours: float) -> int:
        """
        The player away for ``hours`` real hours, then back (spec §15.2): the
        resume's one away advance, through ``away.apply_on_resume`` with the
        harness's own wall clock (``WALL_EPOCH``, never the real one), then
        voicing until quiet, as a resume requests a pass. How many queued
        events the advance applied.
        """
        from engine.game.effects import apply_effect
        from engine.session.store import release_turn
        from engine.social import away, kinds, voicer

        if not self.session.lock.acquire(blocking=False):
            raise RuntimeError("simulate_social: the run's turn lock is held")
        try:
            apply_effect(self.state, {"type": "social_settings", "field": "last_active_wall", "value": WALL_EPOCH})
        finally:
            release_turn(self.session)
        from engine.social import messaging

        planned = {m["id"] for m in (self.state.social.get("meets") or {}).values() if m.get("status") == "agreed"}
        live_before = _live_count(self.state)
        with kinds.collecting() as applied:
            away.apply_on_resume(self.session, wall=lambda: WALL_EPOCH + float(hours) * 3600.0)
        # What the advance left: the due messages its first voicing pass finds (spec §20's last row),
        # and the meets planned before it that it made no-shows.
        self.away_due = len(messaging.unvoiced(self.state))
        self.away_live = (live_before, _live_count(self.state))
        self.away_planned = len(planned)
        meets = self.state.social.get("meets") or {}
        self.away_no_shows = sum(1 for mid in planned if (meets.get(mid) or {}).get("status") == "no_show")
        voicer.run_until_quiet(self.session, self.llm)
        self.spill()
        self._rebuild({})
        return sum(1 for row in applied if row.get("type") == "social_event")

    def close(self) -> None:
        self.store.delete(self.state.session_id)


# ---------------------------------------------------------------------------
# The scripted run (spec §19.1's replay): a fixed script over N actions
# ---------------------------------------------------------------------------


def _extra_match(phone: Phone, pid: str) -> str:
    """
    The replay's extra contact (spec §19.1): matched and written to through
    the effects alone, costing no in-game time, so every other step of the
    script runs at the same hour with or without it. Its thread id.
    """
    from engine.game.effects import apply_effect
    from engine.session.store import release_turn
    from engine.social import messaging, population

    app = population.apps_of(pid)[0]
    if not phone.session.lock.acquire(blocking=False):
        raise RuntimeError("simulate_social: the run's turn lock is held")
    try:
        apply_effect(phone.state, {"type": "social_match", "app": app, "pid": pid, "at": phone.now})
        tid = f"{app}:{pid}"
        messaging.new_message(phone.state, tid, "player", "text", bubbles=["hey, how's your week going?"])
    finally:
        release_turn(phone.session)
    return tid


def scripted_run(seed: int, actions: int, voice_policy: str, extra_contact: Optional[str] = None) -> Any:
    """
    The replay script (spec §19.1), ``actions`` phone actions long: a cycle of
    four Matchstick swipes (one in three a pass), a Front Porch like, a
    message to every match the script made whose last word is theirs (or
    who has none), a 15-minute and a one-hour wait; once, half way, a wait
    until morning; once, three quarters of the way, 72 hours away (an away
    advance, ``Phone.away``: no action). ``extra_contact``: one more person, matched and written
    to by effects at the script's tenth action (``_extra_match``) and never
    touched by any other step. The final ``GameState``.
    """
    with _quiet_summaries():
        phone = Phone(seed, voice_policy)
        mine: set[str] = set()
        extra_tid = ""
        step = 0
        morning_done = False
        away_done = False
        try:
            while phone.actions < actions:
                if extra_contact and not extra_tid and phone.actions >= 10:
                    extra_tid = _extra_match(phone, extra_contact)   # no action and no time: the script goes on
                if not morning_done and phone.actions >= actions // 2:
                    morning_done = True
                    phone.act("wait", args={"until": "morning"})
                    continue
                if not away_done and phone.actions >= (actions * 3) // 4:
                    away_done = True
                    phone.away(AWAY_ROW_HOURS)                         # the resume's advance (T16)
                    continue
                slot = step % 9
                step += 1
                if slot < 4:
                    card = ((phone.phone.get("deck") or {}).get("matchstick") or {}).get("card")
                    if card and (phone.phone["deck"]["matchstick"].get("likes_left") or 0) > 0:
                        phone.act("swipe", card["pid"], {"dir": "pass" if step % 3 == 0 else "like"})
                        mine.add(card["pid"])
                    continue
                if slot == 4:
                    deck = (phone.phone.get("deck") or {}).get("front_porch") or {}
                    card = deck.get("card")
                    if card and (deck.get("likes_left") or 0) > 0:
                        phone.act("like", card["pid"], {"on": card["photos"][0]["id"]})
                        mine.add(card["pid"])
                    continue
                if slot == 5:
                    for row in list(phone.phone.get("threads") or []):
                        if phone.actions >= actions:
                            break
                        if row["pid"] not in mine or not row["open"] or row["thread_id"] == extra_tid:
                            continue
                        last = row.get("last")
                        if last is None or (last["from"] == row["pid"] and not last.get("pending")):
                            phone.act("send", row["thread_id"], {"kind": "text"}, "how's your week going?")
                    continue
                if slot in (6, 7):
                    phone.act("wait", args={"until": "15m"})
                    continue
                phone.act("wait", args={"until": "1h"})
        finally:
            phone.close()
    return phone.state


def mechanics_of(state: Any) -> dict[str, Any]:
    """
    Per person, what the ENGINE decided, never the words (spec §19.1): when
    they matched, their stage history, every message's sender, time, kind
    and decision with its read marks, whether they ghosted, and their media
    decisions. Message ids are left out (a pass's order may number them).
    """
    out: dict[str, Any] = {}
    people = state.social.get("people") or {}
    threads = state.social.get("threads") or {}
    for pid in sorted(people):
        person = people[pid]
        rows = []
        for tid in sorted(t for t, row in threads.items() if row.get("pid") == pid):
            for m in threads[tid].get("messages") or []:
                rows.append((tid, m["from"], m["kind"], m["at"], json.dumps(m.get("decision"), sort_keys=True),
                             m.get("read_at"), m.get("seen_by_them_at"), m.get("voiced") == "withdrawn"))
        out[pid] = {
            "matched_at": person.get("matched_at"),
            "stages": [(h["kind"], h["at"]) for h in person.get("history") or []],
            "messages": rows,
            "ghosted": bool(person.get("ghosted")),
            "media": [r[4] for r in rows if r[2] in ("photo", "voice", "video")],
        }
    return out


def person_trace(state: Any, pid: str) -> list[tuple[str, str, float]]:
    """
    ``pid``'s outcomes as times RELATIVE to the player's sends to them: each
    message of theirs (its situation) and each read mark, hours after the
    player's latest message before it in that thread.
    """
    out: list[tuple[str, str, float]] = []
    threads = state.social.get("threads") or {}
    for tid in sorted(t for t, row in threads.items() if row.get("pid") == pid):
        last_sent: Optional[float] = None
        for m in threads[tid].get("messages") or []:
            if m["from"] == "player":
                last_sent = float(m["at"])
                if m.get("read_at") is not None:
                    out.append((tid, "read", round(float(m["read_at"]) - last_sent, 9)))
            elif m["from"] == pid and last_sent is not None:
                situation = str((m.get("decision") or {}).get("situation") or m["kind"])
                out.append((tid, situation, round(float(m["at"]) - last_sent, 9)))
    return out


# ---------------------------------------------------------------------------
# The player policies
# ---------------------------------------------------------------------------


class Policy:
    """What a player does at a look at the phone; the subclass rows are the module docstring's."""

    name = ""
    #: Matchstick and Front Porch likes a day, and the share of shown cards liked.
    matchstick_likes = 15
    porch_likes = 4
    like_share = 0.5
    like_back = True
    #: "live": look whenever the phone buzzes (wait until next), else the clock hours of each look.
    looks: Any = "live"
    sends_per_reply = 1
    #: Messages a day to any one person, at most: a person, not a chat bot, answers a few times a day.
    sends_per_person_day = 4
    opener_share = 1.0
    answers_on_odd_days = True
    #: Ask for a number: never | warming (the band shows warming, every ask_every_days) | always.
    asks = "warming"
    ask_every_days = 2.0
    #: Ask to meet anyone at numbers or past it with no meet-up planned or asked, at most every
    #: meet_every_days, and go to every meet-up that comes due (T26). Never for `asks: never`.
    meet_every_days = 3.0

    def __init__(self, phone: Phone, seed: int) -> None:
        from engine.game.rng import stable_rng

        self.phone = phone
        self.seed = seed
        self._rng = stable_rng
        self.liked_today: dict[str, int] = {}
        self.sent_today: dict[str, int] = {}
        self.day = -1
        self.asked_at: dict[str, float] = {}
        self.meet_asked_at: dict[str, float] = {}
        self.opened: set[str] = set()

    # -- small reads ---------------------------------------------------------

    def _wants(self, pid: str, share: float) -> bool:
        """A stable per-card choice (the harness's own stable key, never a bare random)."""
        return self._rng(self.seed, f"simulate_social:{self.name}:{pid}").random() < share

    def awake(self) -> bool:
        hour = self.phone.now % 24
        return HOUR_WAKE <= hour < HOUR_BED

    # -- one look ------------------------------------------------------------

    def look(self) -> None:
        phone = self.phone
        if phone.state.world_day != self.day:
            self.day = phone.state.world_day
            self.liked_today = {}
            self.sent_today = {}
        self.deck()
        self.answer_requests()
        self.go_to_meets()
        self.messages()

    def deck(self) -> None:
        phone = self.phone
        if self.like_back:
            for row in list(phone.phone.get("likes_you") or []):
                phone.act("like_back", row["pid"])
        for app, budget in (("matchstick", self.matchstick_likes), ("front_porch", self.porch_likes)):
            shown = 0
            while self.liked_today.get(app, 0) < budget and shown < 400:
                deck = (phone.phone.get("deck") or {}).get(app) or {}
                card = deck.get("card")
                if not card or int(deck.get("likes_left") or 0) <= 0:
                    break
                shown += 1
                pid = card["pid"]
                like = self._wants(pid, self.like_share)
                if app == "matchstick":
                    phone.act("swipe", pid, {"dir": "like" if like else "pass"})
                elif like:
                    phone.act("like", pid, {"on": card["photos"][0]["id"]})
                else:
                    phone.act("pass", pid)
                if like:
                    self.liked_today[app] = self.liked_today.get(app, 0) + 1

    def answer_requests(self) -> None:
        phone = self.phone
        for row in list(phone.phone.get("requests") or []):
            if row["from"] == "them" and row["status"] in ("pending", "later"):
                phone.act("answer", row["id"], {"reply": "yes"})

    def go_to_meets(self) -> None:
        """Every meet-up that has come due: go (``meet {do: go}``)."""
        phone = self.phone
        for row in list(phone.phone.get("calendar") or []):
            if row.get("status") == "due":
                phone.act("meet", row["id"], {"do": "go"})

    def messages(self) -> None:
        phone = self.phone
        if not self.answers_on_odd_days and phone.state.world_day % 2:
            return
        for row in list(phone.phone.get("threads") or []):
            if not row["open"]:
                continue
            tid, pid = row["thread_id"], row["pid"]
            last = row.get("last")
            theirs = last is not None and last["from"] == pid and not last.get("pending")
            first = last is None and tid not in self.opened
            if theirs and row.get("unread"):
                phone.act("open_thread", tid)
            if first:
                self.opened.add(tid)
                if not self._wants(f"{pid}:opener", self.opener_share):
                    continue
            if (theirs or first) and self.sent_today.get(pid, 0) < self.sends_per_person_day:
                for i in range(self.sends_per_reply):
                    phone.act("send", tid, {"kind": "text"}, "how's your week been?" if i == 0 else "?")
                    self.sent_today[pid] = self.sent_today.get(pid, 0) + 1
            self.maybe_ask(row)
            self.maybe_meet(row)

    def maybe_meet(self, row: dict[str, Any]) -> None:
        """At numbers or past it, nothing planned or asked with them: ``ask {what: meet}`` (the engine picks)."""
        from engine.social import kinds

        if self.asks == "never":
            return
        pid = row["pid"]
        person = (self.phone.state.social.get("people") or {}).get(pid) or {}
        if kinds.stage_rank(person.get("stage")) < kinds.stage_rank("numbers") or person.get("ghosted"):
            return
        if any(m.get("pid") == pid and m.get("status") in ("agreed", "due")
               for m in self.phone.phone.get("calendar") or []):
            return
        if any(r.get("pid") == pid and r.get("what") == "meet" and r.get("status") in ("pending", "later")
               for r in self.phone.phone.get("requests") or []):
            return
        if self.phone.now - self.meet_asked_at.get(pid, -1e9) < self.meet_every_days * 24:
            return
        self.meet_asked_at[pid] = self.phone.now
        self.phone.act("ask", row["thread_id"], {"what": "meet"})

    def maybe_ask(self, row: dict[str, Any]) -> None:
        if self.asks == "never" or row.get("stage_words") != "Talking":
            return
        if self.asks == "warming" and row.get("band") in ("", "new"):
            return
        pid = row["pid"]
        if self.asks == "warming" and self.phone.now - self.asked_at.get(pid, -1e9) < self.ask_every_days * 24:
            return
        self.asked_at[pid] = self.phone.now
        self.phone.act("ask", row["thread_id"], {"what": "number"})

    # -- the day -------------------------------------------------------------

    def step(self) -> None:
        """One look if it is time for one, then the wait to the next."""
        phone = self.phone
        if not self.awake():
            phone.act("wait", args={"until": "morning"})
            return
        if self.looks == "live":
            self.look()
            phone.act("wait", args={"until": "next"})
            return
        hour = int(phone.now % 24)
        if hour in self.looks and getattr(self, "_looked", None) != (phone.state.world_day, hour):
            self._looked = (phone.state.world_day, hour)
            self.look()
        phone.act("wait", args={"until": "1h"})


class Attentive(Policy):
    name = "attentive"


class Swiper(Policy):
    name = "swiper"
    matchstick_likes = 60
    porch_likes = 8
    like_share = 1.0
    looks = (9, 13, 18, 22)


class Picky(Policy):
    name = "picky"
    matchstick_likes = 5
    porch_likes = 2
    like_share = 1.0 / 7.0


class Slow(Policy):
    name = "slow"
    looks = (9, 15, 21)


class Neglectful(Policy):
    name = "neglectful"
    looks = (10, 20)
    opener_share = 0.5
    answers_on_odd_days = False
    asks = "never"


class Pushy(Policy):
    name = "pushy"
    sends_per_reply = 2
    sends_per_person_day = 8
    asks = "always"


POLICIES: dict[str, type[Policy]] = {p.name: p for p in (Attentive, Swiper, Picky, Slow, Neglectful, Pushy)}


# ---------------------------------------------------------------------------
# One run, observed
# ---------------------------------------------------------------------------


class Observer:
    """
    What the state does not keep with a time: when a person first ghosted,
    reached each closeness band and had their turn fire (seen after each
    action, so to within one action), and every morning's interest.
    """

    def __init__(self) -> None:
        self.ghosted_at: dict[str, float] = {}
        self.band_at: dict[str, dict[str, float]] = {}
        self.turned_at: dict[str, float] = {}
        #: When each person first stopped being a live relationship (not live, ghosted or gone).
        self.left_at: dict[str, float] = {}
        #: Every meet-up seen, by id, as last seen (`social.meets_kept` trims finished ones from state).
        self.meets: dict[str, dict[str, Any]] = {}
        self.mornings: dict[str, list[tuple[int, float, Optional[float], bool]]] = {}
        self.day30: Optional[int] = None
        self._day = 0

    def __call__(self, phone: Phone) -> None:
        from engine.social import apps, relationships

        state = phone.state
        now = phone.now
        people = state.social.get("people") or {}
        for mid, row in (state.social.get("meets") or {}).items():
            if self.meets.get(mid) != row:
                self.meets[mid] = dict(row)
        pids = {t["pid"] for t in (state.social.get("threads") or {}).values()}
        new_day = state.world_day != self._day
        if new_day:
            self._day = state.world_day
        for pid in pids:
            person = people.get(pid) or {}
            if person.get("ghosted") and pid not in self.ghosted_at:
                self.ghosted_at[pid] = now
            if person.get("arc_fired") and pid not in self.turned_at:
                self.turned_at[pid] = now
            if pid not in self.left_at and person.get("stage") and (
                    not relationships.live(person) or person.get("ghosted") or apps.gone(state, pid)):
                self.left_at[pid] = now
            if person.get("stage"):
                band = relationships.band(person)
                seen = self.band_at.setdefault(pid, {})
                names = [str(r["name"]) for r in relationships._bands()]
                for name in names[:names.index(band) + 1]:
                    seen.setdefault(name, now)
            if new_day:
                self.mornings.setdefault(pid, []).append((
                    state.world_day, float(person.get("interest", 50)),
                    relationships._last_contact(person), relationships.live(person)))
        if new_day and state.world_day == 30:
            self.day30 = _live_count(state)


def _live_count(state: Any) -> int:
    from engine.social import apps, relationships

    people = state.social.get("people") or {}
    pids = {t["pid"] for t in (state.social.get("threads") or {}).values()}
    return sum(1 for pid in pids
               if relationships.live(people.get(pid) or {}) and (people.get(pid) or {}).get("stage") != "matched"
               and not (people.get(pid) or {}).get("ghosted") and not apps.gone(state, pid))


def run(seed: int, days: int, policy: str, voice_policy: str = DEFAULT_VOICE, *,
        disk: Optional[Path] = None) -> dict[str, Any]:
    """
    One run of ``days`` in-game days: its raw measurements (``report`` folds
    many). ``disk``: a directory the run saves under, spilling its threads
    into the archive after every action as play does (``Phone.spill``); the
    measurements read the archive too, so they are the same either way
    (``tests/test_simulate_social.py``'s spill test).
    """
    if policy not in POLICIES:
        raise ValueError(f"simulate_social: no policy {policy!r} ({', '.join(POLICIES)})")
    started = time.perf_counter()
    with _quiet_summaries():
        phone = Phone(seed, voice_policy, disk=disk)
        observer = Observer()
        phone.observers.append(observer)
        player = POLICIES[policy](phone, seed)
        end = phone.now + days * 24.0
        try:
            while phone.now < end:
                player.step()
            measured = _measure(phone, observer, end, days, seed, policy, voice_policy,
                                time.perf_counter() - started)
            # Measured first: the away advance runs after the run's end, so it moves no other row.
            measured["away_events"] = phone.away(AWAY_ROW_HOURS) if days >= AWAY_ROW_DAYS else None
            measured["away_due"] = getattr(phone, "away_due", None)
            measured["away_planned"] = getattr(phone, "away_planned", None)
            measured["away_no_shows"] = getattr(phone, "away_no_shows", None)
            measured["away_live"] = getattr(phone, "away_live", None)
            return measured
        finally:
            phone.close()


def write_day_save(seed: int, days: int, policy: str, out: Path, voice_policy: str = "romantic_model") -> Path:
    """
    A day-``days`` run of ``policy`` saved under ``out`` (spec §17.2's size
    bound, T26): played on disk, its threads spilled into the archive after
    every action as play's saves do, then the archive spilled once more and
    ``save.json`` written through the store, as ``saves.save_now`` writes it.
    The save's directory (``save.json``, ``phone_archive.jsonl``).
    """
    from engine.session.store import release_turn
    from engine.social import archive

    with _quiet_summaries():
        phone = Phone(seed, voice_policy, disk=Path(out))
        try:
            player = POLICIES[policy](phone, seed)
            end = phone.now + days * 24.0
            while phone.now < end:
                player.step()
            session = phone.session
            if not session.lock.acquire(blocking=False):
                raise RuntimeError("simulate_social: the run's turn lock is held")
            try:
                archive.spill(session)
                session.saves.save(phone.state, save_id=session.save_id, memory=session.ledger.to_dict())
            finally:
                release_turn(session)
            return Path(session.saves.path_for(session.save_id))
        finally:
            phone.close()


def _first(history: list[dict[str, Any]], kind: str) -> Optional[float]:
    return next((float(h["at"]) for h in history if h.get("kind") == kind), None)


def _measure(phone: Phone, observer: Observer, end: float, days: int, seed: int, policy: str,
             voice_policy: str, wall: float) -> dict[str, Any]:
    from engine import social
    from engine.social import apps, population

    state = phone.state
    people = state.social.get("people") or {}
    threads = state.social.get("threads") or {}
    likes = {app: 0 for app in apps.dating_apps()}
    matches = {app: 0 for app in apps.dating_apps()}
    for (app, pid), at in sorted(phone.likes.items()):
        if app not in likes or at > end - 72:
            continue
        likes[app] += 1
        if (((people.get(pid) or {}).get("apps") or {}).get(app) or {}).get("matched_at") is not None:
            matches[app] += 1
    people_rows: list[dict[str, Any]] = []
    latency: list[float] = []
    received = 0
    unanswered = 0
    sent = 0
    for pid in sorted({t["pid"] for t in threads.values()}):
        person = people.get(pid) or {}
        history = person.get("history") or []
        mine = [t for t in threads.values() if t["pid"] == pid]
        theirs_at: list[float] = []
        media: dict[str, list[float]] = {"photo": [], "voice": [], "video": []}
        for t in mine:
            last_player: Optional[float] = None
            answered = True
            for m in phone.messages(t):
                if m.get("voiced") == "withdrawn":
                    continue
                if m["from"] == "player":
                    sent += 1
                    if last_player is None:
                        last_player = float(m["at"])
                    answered = False
                elif m["from"] == pid:
                    received += 1
                    theirs_at.append(float(m["at"]))
                    if m.get("kind") in media:
                        media[m["kind"]].append(float(m["at"]))
                    situation = (m.get("decision") or {}).get("situation")
                    if situation == "reply" and last_player is not None:
                        latency.append((float(m["at"]) - last_player) * 60.0)
                    last_player = None
                    answered = True
            if not answered:
                unanswered += 1
        matched_at = person.get("matched_at")
        people_rows.append({
            "pid": pid,
            "archetype": population.profile(state, pid).archetype,
            "matched_at": None if matched_at is None else float(matched_at),
            "first_theirs": min(theirs_at) if theirs_at else None,
            "talking_at": _first(history, "talking"),
            "numbers_at": _first(history, "numbers"),
            "ghosted_at": observer.ghosted_at.get(pid),
            "turned_at": observer.turned_at.get(pid),
            "left_at": observer.left_at.get(pid),
            "met_at": min((float(m["start"]) for m in observer.meets.values()
                           if m.get("pid") == pid and m.get("status") == "done"), default=None),
            "media": media,
            "band_at": observer.band_at.get(pid, {}),
            "mornings": observer.mornings.get(pid, []),
        })
    return {
        "seed": seed, "days": days, "policy": policy, "voice": voice_policy, "end": end,
        "likes": likes, "matches": matches, "people": people_rows,
        "received": received, "sent": sent, "unanswered_threads": unanswered, "threads": len(threads),
        "reply_minutes": latency, "live_day30": observer.day30,
        "meets": sorted(({"pid": m.get("pid"), "status": m.get("status"), "band": m.get("band"),
                          "start": m.get("start")} for m in observer.meets.values()),
                        key=lambda m: (float(m["start"] or 0), str(m["pid"]))),
        "actions": phone.actions, "refused": phone.refused, "refusals": dict(phone.refusals), "wall_seconds": round(wall, 2),
        "archetypes": sorted((social.data("behaviours").get("archetypes") or {}).keys()),
    }


# ---------------------------------------------------------------------------
# Folding runs into the report
# ---------------------------------------------------------------------------


def _share(hits: int, total: int) -> Optional[float]:
    return None if total == 0 else round(hits / total, 3)


def _median(values: list[float]) -> Optional[float]:
    return None if not values else round(statistics.median(values), 2)


def _pct(values: list[float], q: float) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[min(len(ordered) - 1, int(q * len(ordered)))], 2)


def _within(rows: list[dict[str, Any]], end_of: Callable[[dict[str, Any]], float], start: str, then: str,
            hours: float) -> Optional[float]:
    """Of the rows whose ``start`` was at least ``hours`` before their run's end, those reaching ``then`` in time."""
    total = hits = 0
    for row in rows:
        began = row.get(start)
        if began is None or began > end_of(row) - hours:
            continue
        total += 1
        reached = row.get(then)
        if reached is not None and began <= reached <= began + hours:
            hits += 1
    return _share(hits, total)


def _half_life(mornings: list[tuple[int, float, Optional[float], bool]]) -> list[float]:
    """
    Each no-contact spell of 3+ live mornings: (interest at its start / 2) /
    interest lost per day, the spell measured up to the first morning
    interest reaches 0 (T26 fix round 1: interest floors at 0, and a spell
    runs on to the fade, `fade_days`, so days spent on the floor would read
    as a slower decay).
    """
    out: list[float] = []
    spell: list[tuple[int, float]] = []
    last_mark: Any = object()
    for day, interest, last, is_live in mornings + [(0, 0.0, None, False)]:
        if is_live and last == last_mark and spell:
            spell.append((day, interest))
            continue
        floor = next((i for i, (_d, level) in enumerate(spell) if level <= 0), None)
        if floor is not None:
            spell = spell[:floor + 1]
        if len(spell) >= 3:
            (d0, i0), (d1, i1) = spell[0], spell[-1]
            lost = (i0 - i1) / max(1, d1 - d0)
            if lost > 0 and i0 > 0:
                out.append((i0 / 2.0) / lost)
        spell = [(day, interest)] if is_live else []
        last_mark = last
    return out


def _rate(rows: list[dict[str, Any]], since: str, kind: str, per_hours: float) -> Optional[float]:
    """
    ``kind`` media they sent per ``per_hours`` of relationship, from ``since``
    (a row key, or a closeness band's name in ``band_at``) to the run's end or
    their leaving: the media sent in those spans over the spans' length.
    """
    hours = sent = 0.0
    for row in rows:
        start = row.get(since) if since in row else (row.get("band_at") or {}).get(since)
        if start is None:
            continue
        stop = float(row["_end"])
        if row.get("left_at") is not None:
            stop = min(stop, float(row["left_at"]))
        if stop <= float(start):
            continue
        hours += stop - float(start)
        sent += sum(1 for at in (row.get("media") or {}).get(kind) or () if float(start) <= at <= stop)
    return None if hours <= 0 else round(sent / (hours / per_hours), 3)


def fold(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """The report (``REPORT_ROWS`` plus ``days_to_*`` and ``also.*``) over finished runs."""
    rows: list[dict[str, Any]] = []
    for r in runs:
        for p in r["people"]:
            rows.append({**p, "_end": r["end"]})
    end_of: Callable[[dict[str, Any]], float] = lambda row: float(row["_end"])
    out: dict[str, Any] = {key: None for key in REPORT_ROWS}
    for app in ("matchstick", "front_porch"):
        out[f"like_to_match.{app}"] = _share(sum(r["matches"].get(app, 0) for r in runs),
                                             sum(r["likes"].get(app, 0) for r in runs))
    out["match_to_talking_3d"] = _within(rows, end_of, "matched_at", "talking_at", 72.0)
    out["match_to_message_3d"] = _within(rows, end_of, "matched_at", "first_theirs", 72.0)
    out["talking_to_ghosted_14d"] = _within(rows, end_of, "talking_at", "ghosted_at", 14 * 24.0)
    out["talking_to_numbers_21d.attentive"] = _within(rows, end_of, "talking_at", "numbers_at", 21 * 24.0)
    out["interest_half_life_days"] = _median([h for row in rows for h in _half_life(
        [tuple(m) for m in row["mornings"]])])
    day30 = [r["live_day30"] for r in runs if r["live_day30"] is not None]
    out["live_relationships_day30.attentive"] = None if not day30 else round(statistics.mean(day30), 2)
    out["messages_per_day.attentive"] = (None if not runs else
                                         round(sum(r["received"] for r in runs) / sum(r["days"] for r in runs), 2))
    out["numbers_to_meet_21d"] = _within(rows, end_of, "numbers_at", "met_at", 21 * 24.0)
    done = [m for r in runs for m in r.get("meets") or [] if m.get("status") == "done"]
    for band in ("great", "good", "fine", "awkward", "bad"):
        out[f"meet_band.{band}"] = _share(sum(1 for m in done if m.get("band") == band), len(done))
    out["photos_per_close_week"] = _rate(rows, "close", "photo", 7 * 24.0)
    out["voice_per_relationship_week_after_numbers"] = _rate(rows, "numbers_at", "voice", 7 * 24.0)
    out["videos_per_close_month"] = _rate(rows, "close", "video", 30 * 24.0)
    turners = [row for row in rows if row["archetype"] == "turner"]
    out["turners_turned_60d"] = _within(turners, end_of, "talking_at", "turned_at", 60 * 24.0)
    archetypes = sorted({a for r in runs for a in r["archetypes"]})
    for arch in archetypes:
        mine = [row for row in rows if row["archetype"] == arch and row["matched_at"] is not None]
        for key, band in BAND_ROWS:
            days = [(row["band_at"][band] - row["matched_at"]) / 24.0 for row in mine if band in row["band_at"]]
            out[f"days_to_{key}.{arch}"] = _median([max(0.0, d) for d in days])
    latency = [m for r in runs for m in r["reply_minutes"]]
    talking = [row for row in rows if row["talking_at"] is not None]
    out["also.reply_minutes_median"] = _median(latency)
    out["also.reply_minutes_p90"] = _pct(latency, 0.9)
    out["also.unanswered_threads_share"] = _share(sum(r["unanswered_threads"] for r in runs),
                                                  sum(r["threads"] for r in runs))
    out["also.ghosted_share_of_talking"] = _share(sum(1 for row in talking if row["ghosted_at"] is not None),
                                                  len(talking))
    out["also.matches_per_run"] = round(sum(len(r["people"]) for r in runs) / max(1, len(runs)), 2)
    out["also.talking_per_run"] = round(len(talking) / max(1, len(runs)), 2)
    out["also.numbers_per_run"] = round(sum(1 for row in rows if row["numbers_at"] is not None)
                                        / max(1, len(runs)), 2)
    out["also.actions_per_run"] = round(sum(r["actions"] for r in runs) / max(1, len(runs)), 1)
    out["also.refused_per_run"] = round(sum(r["refused"] for r in runs) / max(1, len(runs)), 1)
    reasons: dict[str, int] = {}
    for r in runs:
        for key, count in (r.get("refusals") or {}).items():
            reasons[key] = reasons.get(key, 0) + int(count)
    # The ten commonest refusals, per run: whether a policy's actions reach a mechanic at all.
    out["also.refusals_per_run"] = {key: round(count / max(1, len(runs)), 1) for key, count in
                                    sorted(reasons.items(), key=lambda kv: (-kv[1], kv[0]))[:10]}
    meets = [m for r in runs for m in r.get("meets") or []]
    out["also.meets_per_run"] = round(len(meets) / max(1, len(runs)), 2)
    out["also.meet_status_per_run"] = {k: round(sum(1 for m in meets if m.get("status") == k) / max(1, len(runs)), 2)
                                       for k in sorted({str(m.get("status")) for m in meets})}
    due = [int(r["away_due"]) for r in runs if r.get("away_due") is not None]
    # Spec §20's last row: the due messages the first voicing pass after a 72 h away finds (p95 over runs).
    out["also.due_after_72h_away_p95"] = _pct([float(d) for d in due], 0.95)
    out["also.away_no_shows_per_run"] = (None if not due else round(
        sum(int(r.get("away_no_shows") or 0) for r in runs) / len(due), 2))
    out["also.away_planned_per_run"] = (None if not due else round(
        sum(int(r.get("away_planned") or 0) for r in runs) / len(due), 2))
    lives = [r["away_live"] for r in runs if r.get("away_live")]
    # Live relationships before the 72-hour away and after it (summed over runs): what an absence costs.
    out["also.away_live_before_after"] = (None if not lives else
                                         [sum(a for a, _ in lives), sum(b for _, b in lives)])
    away_events = [int(r["away_events"]) for r in runs if r.get("away_events") is not None]
    # The worst run: the spec's band (§20, <= 1500) is a ceiling on one advance's work.
    out["events_per_72h_away_day60"] = max(away_events) if away_events else None
    out["also.runs"] = len(runs)
    return out


def report(seeds: Iterable[int], days: int, policy: str, voice_policy: str = DEFAULT_VOICE) -> dict[str, Any]:
    """One value per ``REPORT_ROWS`` key (None: not built yet), plus ``days_to_*`` and ``also.*``."""
    return fold([run(int(seed), days, policy, voice_policy) for seed in seeds])


# ---------------------------------------------------------------------------
# The command line
# ---------------------------------------------------------------------------


def render(policy: str, voice: str, rep: dict[str, Any], seeds: int, days: int) -> str:
    lines = [f"== {policy} x {voice} ({seeds} seeds x {days} days) =="]
    for key, value in rep.items():
        shown = "-" if value is None else value
        lines.append(f"  {key:<46} {shown}")
    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0].strip().splitlines()[0])
    parser.add_argument("--game", default=SLUG, help=f"the story to play; only {SLUG!r} has this harness")
    parser.add_argument("--days", type=int, default=60)
    parser.add_argument("--seeds", type=int, default=40)
    parser.add_argument("--first-seed", type=int, default=0)
    parser.add_argument("--policy", choices=(*POLICIES, "all"), default="attentive")
    parser.add_argument("--voice", choices=(*VOICES, "all"), default=DEFAULT_VOICE,
                        help=f"the stub model's regard, or no_model (the fallback); default {DEFAULT_VOICE}")
    parser.add_argument("--raw", metavar="OUT", default="",
                        help="write each run's raw measurements to this JSON file (for --fold)")
    parser.add_argument("--fold", metavar="RAW", nargs="+", default=[],
                        help="fold --raw files (seed ranges run side by side) into one report; plays nothing")
    parser.add_argument("--disk", metavar="DIR", default="",
                        help="play on disk under DIR, spilling into the archive as play does (one folder per run)")
    parser.add_argument("--json", metavar="OUT", default="", help="also write the reports to this JSON file")
    args = parser.parse_args(argv)
    if args.game != SLUG:
        parser.error(f"argument --game: this harness plays {SLUG!r} only (scripts/simulate.py plays the others)")
    if args.days < 1 or args.seeds < 1:
        parser.error("--days and --seeds must be at least 1")
    if os.environ.get("CLOCKWORK_DATA_DIR", "").strip():
        return _main(args)
    # Never the owner's storage (T26): a run's opening draws its scene art, and the procedural
    # provider writes it under the storage root. A throwaway root unless the caller names one.
    with tempfile.TemporaryDirectory(prefix="simulate_social-") as root:
        os.environ["CLOCKWORK_DATA_DIR"] = root
        try:
            return _main(args)
        finally:
            os.environ.pop("CLOCKWORK_DATA_DIR", None)


def _main(args: argparse.Namespace) -> int:

    reports: dict[str, dict[str, Any]] = {}
    if args.fold:
        # Runs made side by side (each its own --first-seed range and --raw file), folded as one.
        raw: dict[str, list[dict[str, Any]]] = {}
        for name in args.fold:
            for key, runs in json.loads(Path(name).read_text(encoding="utf-8")).items():
                raw.setdefault(key, []).extend(runs)
        for key, runs in raw.items():
            runs.sort(key=lambda r: r["seed"])
            reports[key] = fold(runs)
            policy, voice = key.split("/", 1)
            print(render(policy, voice, reports[key], len(runs), max(r["days"] for r in runs)), flush=True)
    else:
        logging.disable(logging.WARNING)
        _ensure_active()
        seeds = range(args.first_seed, args.first_seed + args.seeds)
        policies = list(POLICIES) if args.policy == "all" else [args.policy]
        voices = list(VOICES) if args.voice == "all" else [args.voice]
        raw_runs: dict[str, list[dict[str, Any]]] = {}
        for policy in policies:
            for voice in voices:
                began = time.perf_counter()
                runs = [run(seed, args.days, policy, voice,
                            disk=Path(args.disk) / f"{policy}-{voice}-{seed}" if args.disk else None)
                        for seed in seeds]
                raw_runs[f"{policy}/{voice}"] = runs
                reports[f"{policy}/{voice}"] = fold(runs)
                print(render(policy, voice, reports[f"{policy}/{voice}"], args.seeds, args.days), flush=True)
                print(f"  (wall time {time.perf_counter() - began:.0f} s)", flush=True)
        if args.raw:
            Path(args.raw).write_text(json.dumps(raw_runs, sort_keys=True), encoding="utf-8")
    if args.json:
        Path(args.json).write_text(json.dumps(reports, indent=2, sort_keys=True), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
