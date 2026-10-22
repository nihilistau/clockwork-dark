"""
READ RECEIPTS' Balance Harness, v2
==================================

Play READ RECEIPTS headlessly with a scripted player and report the numbers
that decide whether its conversations are tuned (AGENTS.md rule 10; v0.23.0
spec §3.4, §17): how long a conversation runs and why it ends, how often a
cold message goes unanswered or ghosted, how much REAL play it takes from a
match to a phone number, and whether promises are kept.

WHAT IS REAL AND WHAT IS NOT. Every action -- a swipe, a like, a message, a
"talk later", an ask, an answer, a wait -- goes through
``engine.social.turn.run_mechanics``, the phone's own mechanics action, so
legality, refusals, costs, the event queue and every draw are the engine's.
After each action the due messages are voiced by
``engine.social.voicer.run_until_quiet`` on this thread, the pass a player's
phone runs (no scheduler, no admission, no threads). The "model" is a
deterministic stub, never a model server: ``neutral_model`` (the default, a
working model's pleasant replies) proposes warmth +1 trust +1 on every reply,
``romantic_model`` +3/+1, ``cold_model`` -2/-1, ``zero`` 0/0, and
``no_model`` calls nothing, so every reply is the engine's fallback line. Since
v0.23.0 T9 the stub also proposes what the reply schema offers it (§17.1): a
follow-up on one reply in ten (`followups`), a promise on half the sign-offs
that offer one (`promise`), and, whenever the schema asks, that it raised the
follow-up it was given (`followup_asked`) and told the layer it was offered
(`opened_up`) -- so follow-ups close and reveals land in a run. Time passes
only through the ``wait`` action and each action's own cost
(``clock.advance_time``).

THE REAL-TIME COST MODEL (spec §3.4; ``REAL_SECONDS``, ``RealClock``). Nothing
reads a wall clock (R-03): each action the policy takes is PRICED in real
seconds -- a send (and a "talk later") 30, a swipe, like or pass 4 (an ask
or an answer is priced as a tap, a swipe's 4), each bubble of theirs the player
reads 3, and the model's seconds (``--model-seconds``: 6, 15 or 30, the
latency of §20.2) for each reply a send got; a ``wait`` costs nothing. The
world's two (``world`` 35, ``moment`` 40) are T29's: no phone-only session
spends them.

  Calibration (T9, against v0.22.0 T30's measured cadence: an agent driving
  the pane did p95 32 and at most 36 actions a minute, its dedicated swipe
  minute 36 in 54 s): the harness's busiest real minute is a run of swipes
  at 4 s, 15 a minute, and a chat runs at most 2 actions a minute (a send of
  30 s and its reply), both under T30's p95 of 32 -- a person reads and
  types slower than an agent clicks, so the phone actions' first estimates
  stand (reported per run: ``also.actions_per_real_minute_max``). T29
  calibrates ``world`` and ``moment``; T31 re-checks all of them live.

A SESSION (T9, PHONE ONLY; ``Session``) is ``SESSION_REAL_SECONDS`` (40 real
minutes) of the policy's actions from its waking hour: it looks at the phone
and waits for more (a wait is free) until the session's real seconds are
spent or its bedtime comes, then winds down -- says "talk later" in any
conversation it was still in, and keeps any promise of its own that opens
before the morning -- and "goes to bed" with ``wait {until: morning}``. T29
swaps in the world's sleep, work and scenes.

THE GAME SESSION is built by ``SessionStore.create`` over a save store that keeps
nothing (``_KeepsNothing``, ``keeps_nothing = True``; Plan decision 28), so a
run writes no save, starts no DirtySaver thread, and the voicing pass's
generation check asks THIS store -- not the app's -- whether the run is live.

THE PLAYER POLICIES (what the player does; the people are the engine's). Each
looks at the phone, answers what is waiting, and CHATS: once a conversation is
going it answers every reply (one message a reply, a reply landing at once in
an open conversation, §4.3) until the person signs off, or the player's own
patience for that conversation runs out, when it says "talk later" with a
promise of its own (``sign_off {who: me}``) and keeps it in the window. A
person's sign-off is not answered. Once a day it writes first to each person it
is talking with that it has not talked to that day, and to every new match.

  attentive   Looks whenever the phone buzzes, 07:00-23:00. Likes about half
              the Matchstick cards it is shown (15 likes a day), four Front
              Porch profiles, and everyone in Likes you. Asks for a number
              once the closeness band shows warming (at most every two days a
              person), says yes to every request, keeps every promise.
  swiper      Likes every card (the daily limit on both apps); looks at 09,
              13, 18 and 22 o'clock.
  picky       Likes one card in seven (5 Matchstick, 2 Front Porch).
  slow        The attentive player who looks at 09, 15 and 21.
  neglectful  Looks at 10 and 20, writes first half the time, answers only on
              even days, never asks and never promises.
  pushy       Sends two messages each time; asks for a number at every look
              once a person is talking.
  devoted     Once someone it talks to reaches the `everyday` rung, talks to
              them alone (spec §17.1; plans, scenes and the long-term asks are
              T29's).
  bachelor    Keeps 3-6 relationships going: writes first to no new match
              while six people are talking with it.
  flaky       The attentive player who breaks a third of its own promises
              (it does not write in their window); standing up a plan is T29's.
  chatty      The attentive player whose messages are long (90-160
              characters): the player text lengths that drive `deep`.

REPORT ROWS (``REPORT_ROWS``, v2, the plan's Shared interfaces). A row whose
system is not built yet, or that a phone-only run cannot reach, reports
``None``. ``DERIVED_ROWS`` follow from ``REAL_SECONDS`` and are never banded.
The rows T9 measures:

  ratio.chat            in-game minutes per real minute, over the actions in
                        a thread whose person was in an open conversation
                        (derived); ratio.overall: over a session's waking
                        span, the free waits included (derived)
  exchanges_per_episode.d0 / .d2plus   median exchanges (decided replies) of a
                        closed chat episode with one or more that the player
                        wrote in while it was open (a conversation: a reply
                        that landed while the player was away, and lapsed
                        unread, is not one), by its depth when it opened
                        (d2plus: depth 2 or more)
  end_reason.schedule / .energy / .player   of those episodes, the share ended
                        by their day (work, lunch over, sleep, going out, an
                        early start, or a glance at work), by their energy,
                        and by the player's "talk later"; the rest ended at
                        their length, or lapsed (``also.end_reason.*``)
  cold_unanswered_1h.d0 of the player's cold messages (no conversation going)
                        at depth 0, the share with no reply of theirs within
                        one in-game hour (censored at the run's end)
  ghosted_per_episode.d0 / .d2plus   of the episode-start draws (a cold
                        message read), the share that ghosted, by depth
  chat_minutes_to_numbers.fast / .mid / .slow   per person who reached
                        numbers, the REAL minutes the player spent on them
                        (sends, reads, the model's seconds) from the match to
                        numbers; the median per pace tercile (terciles of
                        `attrs.of(...)["pace"]` over every matched person)
  numbers_within_session   of the people the player talked with (an episode
                        with an exchange), the share at numbers by the end of
                        the first session in which they talked (censored: not
                        the run's last session)
  person_promises_kept  of the people's promises whose window closed in the
                        run (void ones left out), the share kept: 1.0,
                        asserted (spec §17.2)
  player_promises_kept.attentive / .flaky   of the player's own promises
                        judged in the run, the share kept, under that policy
                        (``report`` runs the flaky player beside an attentive
                        report for its row)
  full_replies_in_long_episodes   of the replies decided in episodes of six or
                        more exchanges, the share `chatting` or `deep`

Also reported (``also.*``, never banded): ``chat_minutes_to_depth1.<tercile>``
(real minutes from match to the `everyday` rung), every end reason's share,
the episodes the player never wrote in,
the left-on-read share of episode starts and how long the hold ran, window
initiations per live person per day, people talking, at depth 1 and at
numbers per run, photos per relationship-week from talking, real hours and
in-game days to the warming band by archetype, the prompt tokens per voice
mode (``memory._estimate``, the latency probe's input), how often a `short`
texter below depth 2 was asked for a chatting or deep reply (T7 review M1),
actions and refusals.

ON DISK (``--disk DIR``, ``run(disk=...)``): the run saves under a real save
store and spills every thread past ``social.state_messages`` into its
``phone_archive.jsonl`` after each action, as play's saves do; the
measurements read the archive too, so a run measures the same on disk or off
(a test holds it). ``write_day_save`` writes the day-N save the size bound
pins (spec §17.2). The same seeds give the same report (the wall time is
printed, never reported).

Usage:
    python scripts/simulate_social.py --game read-receipts --sessions 6 --seeds 10 --policy attentive --model-seconds 30
    python scripts/simulate_social.py --game read-receipts --policy all --voice all --seeds 10
    # 10 seeds side by side, in shells, then one report:
    python scripts/simulate_social.py --game read-receipts --first-seed 0 --seeds 5 --raw r0.json
    python scripts/simulate_social.py --game read-receipts --first-seed 5 --seeds 5 --raw r5.json
    python scripts/simulate_social.py --game read-receipts --fold r0.json r5.json
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

#: The report's rows, defined ONCE in the plan's Shared interfaces (T9; banded by T29).
REPORT_ROWS: tuple[str, ...] = (
    "ratio.chat", "ratio.world", "ratio.overall",
    "exchanges_per_episode.d0", "exchanges_per_episode.d2plus",
    "end_reason.schedule", "end_reason.energy", "end_reason.player",
    "cold_unanswered_1h.d0",
    "ghosted_per_episode.d0", "ghosted_per_episode.d2plus",
    "chat_minutes_to_numbers.fast", "chat_minutes_to_numbers.mid", "chat_minutes_to_numbers.slow",
    "numbers_within_session",
    "sessions_to_first_scene",
    "real_hours_to_depth.fast.2", "real_hours_to_depth.fast.3", "real_hours_to_depth.fast.4",
    "real_hours_to_depth.slow.2", "real_hours_to_depth.slow.3", "real_hours_to_depth.slow.4",
    "scene_band.great", "scene_band.good", "scene_band.fine", "scene_band.awkward", "scene_band.bad",
    "person_promises_kept",
    "player_promises_kept.attentive", "player_promises_kept.flaky",
    "full_replies_in_long_episodes",
    "life_events.player_per_week", "life_events.person_per_month_d2plus",
    "devoted.together_10h", "devoted.living_together_20h", "devoted.married_40h",
    "active_relationships_20h.bachelor", "active_relationships_20h.attentive",
    "save_bytes_day180.attentive", "save_bytes_day180.bachelor", "save_bytes_day180.devoted",
    "events_per_jump_morning_day60",
)
#: Rows that follow arithmetically from ``REAL_SECONDS``: reported, never banded (spec §3.4).
DERIVED_ROWS: frozenset[str] = frozenset({"ratio.chat", "ratio.world", "ratio.overall"})

#: Each policy action's real seconds (spec §3.4), the first estimates from v0.22.0 T30's cadence
#: (the module docstring's calibration). `world` and `moment` are T29's.
REAL_SECONDS: dict[str, float] = {"send": 30.0, "read_bubble": 3.0, "swipe": 4.0, "world": 35.0, "moment": 40.0}
#: A session's real seconds: 40 real minutes (spec §3.2's 30-45).
SESSION_REAL_SECONDS = 40 * 60
#: The model latencies a banded run is made at (spec §3.4, I8): the bands hold at 30, the worst case.
MODEL_SECONDS: tuple[float, ...] = (6.0, 15.0, 30.0)
DEFAULT_MODEL_SECONDS = 15.0
#: The phone actions and the ``REAL_SECONDS`` row each is priced at (an ask or an answer is a tap,
#: priced as a swipe; opening a thread costs only the bubbles read).
ACTION_PRICE: dict[str, str] = {"send": "send", "sign_off": "send", "swipe": "swipe", "like": "swipe",
                                "pass": "swipe", "like_back": "swipe", "ask": "swipe", "answer": "swipe"}
#: The rows a report measures under ANOTHER policy than its own: a run of that policy beside it.
COMPANION_ROWS: dict[str, str] = {"player_promises_kept.flaky": "flaky"}


class RealClock:
    """Real seconds spent by the policy's actions in one session (no wall clock is read: rule R-03)."""

    def __init__(self, model_seconds: float, budget: float = SESSION_REAL_SECONDS) -> None:
        self.model_seconds = float(model_seconds)
        self.budget = float(budget)
        self.spent = 0.0

    def charge(self, action: str, *, bubbles: int = 0, replies: int = 0) -> None:
        self.spent += REAL_SECONDS.get(action, 0.0) + REAL_SECONDS["read_bubble"] * bubbles
        self.spent += self.model_seconds * replies

    @property
    def over(self) -> bool:
        return self.spent >= self.budget


#: ``Phone.away``'s absence in the replay script (spec §19.1): 72 hours.
AWAY_ROW_HOURS = 72.0

#: The harness's wall clock (seconds since the epoch): the away advance is
#: measured from it, never from the real clock, so a run replays.
WALL_EPOCH = 1_800_000_000.0

#: The closeness bands an ``also.days_to_*`` row is reported for (relationships.yaml ``bands``).
BAND_ROWS: tuple[tuple[str, str], ...] = (("warming", "warming"), ("close", "close"))

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

#: The voice policies (spec §17.1): a name -> the stub policy, or None for no model (the fallback).
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

#: The stub's proposals (spec §17.1): a follow-up on one reply in FOLLOWUP_EVERY, a promise on one
#: sign-off in PROMISE_EVERY of those whose schema offers one.
FOLLOWUP_EVERY = 10
PROMISE_EVERY = 2

#: The player's actions that like someone: a swipe, a Front Porch like, a like back from "Likes you".
LIKE_ACTIONS: frozenset[str] = frozenset({"swipe", "like", "like_back"})

#: The player's day. HOUR_WAKE is where `wait {until: morning}` lands -- conversation.yaml `clock.morning`
#: (7) -- so a policy that sleeps "until morning" wakes inside its own day.
HOUR_WAKE = 7.0
HOUR_BED = 23.0


# ---------------------------------------------------------------------------
# The stub voice and the session
# ---------------------------------------------------------------------------


def _mode_of(fmt: dict[str, Any]) -> str:
    """The voice mode a call was made in, read off its schema's bubble length (conversation.yaml caps)."""
    from engine import social

    schema = (((fmt or {}).get("json_schema") or {}).get("schema") or {})
    bubble = ((((schema.get("properties") or {}).get("bubbles") or {}).get("items") or {})
              .get("properties") or {}).get("text") or {}
    chars = bubble.get("maxLength")
    caps = (social.data("conversation").get("modes") or {}).get("caps") or {}
    for mode in ("quick", "chatting", "deep"):
        if chars is not None and int((caps.get(mode) or {}).get("bubble_chars", -1)) == int(chars):
            return mode
    return ""


class StubVoice:
    """
    A scripted ``llm_fn``: one bubble, the policy's regard, nothing learned or shared; of what the
    schema offers, a follow-up on one reply in ``FOLLOWUP_EVERY``, a promise on one sign-off in
    ``PROMISE_EVERY``, and ``followup_asked`` / ``opened_up`` true whenever asked (spec §17.1). Per
    mode it keeps the prompt's estimated tokens (``memory._estimate``), the latency probe's input.
    """

    def __init__(self, policy: str) -> None:
        if policy not in STUB_POLICIES:
            raise ValueError(f"StubVoice: no policy {policy!r} ({', '.join(STUB_POLICIES)})")
        self.policy = policy
        self.calls = 0
        self.promise_offers = 0
        #: mode -> each call's estimated prompt tokens.
        self.prompt_tokens: dict[str, list[int]] = {}

    def __call__(self, messages: list[dict[str, Any]], fmt: dict[str, Any]) -> str:
        self.calls += 1
        text, regard = STUB_POLICIES[self.policy]
        props = (((fmt or {}).get("json_schema") or {}).get("schema") or {}).get("properties") or {}
        out: dict[str, Any] = {"bubbles": [{"text": text}], "regard": dict(regard), "learned": [], "shared": []}
        if "proposals" in props:
            out["proposals"] = []
        if "media" in props:
            out["media"] = {"caption": "this one's for you"}
        if "followups" in props:
            whens = ((((props["followups"].get("items") or {}).get("properties") or {}).get("when") or {})
                     .get("enum") or ["tomorrow"])
            out["followups"] = ([{"about": "how the week goes", "when": "tomorrow" if "tomorrow" in whens else whens[0]}]
                                if self.calls % FOLLOWUP_EVERY == 0 else [])
        if "promise" in props:
            self.promise_offers += 1
            windows = ((((props["promise"].get("items") or {}).get("properties") or {}).get("window") or {})
                       .get("enum") or [])
            out["promise"] = ([{"window": windows[0], "about": "catching up"}]
                              if windows and self.promise_offers % PROMISE_EVERY == 1 else [])
        if "followup_asked" in props:
            out["followup_asked"] = True
        if "opened_up" in props:
            out["opened_up"] = True
        if messages:
            from engine.social import memory

            mode = _mode_of(fmt)
            if mode:
                tokens = memory._estimate({str(i): str(m.get("content") or "") for i, m in enumerate(messages)})
                self.prompt_tokens.setdefault(mode, []).append(int(tokens))
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


@contextmanager
def _away_mode_real() -> Iterator[None]:
    """
    ``Phone.away`` measures `social.away.mode: real` (the 72-hour absence, v0.22.0 §15.2). Since
    v0.23.0 the default is `none` (spec §3.6: a resume moves the clock by 0), so the harness's one away
    advance names the mode it measures, for its own call only; play and every other read keep the
    configured mode.
    """
    from engine import social

    real = social.setting

    def setting(key: str, default: Any) -> Any:
        if key == "away":
            return {**dict(real(key, default) or {}), "mode": "real"}
        return real(key, default)

    social.setting = setting  # type: ignore[assignment]
    try:
        yield
    finally:
        social.setting = real  # type: ignore[assignment]


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


def _private_storage() -> None:
    """
    Refuse, before any write, a run whose storage root is not private (T5 review C1): a run's opening
    draws its scene art, and the procedural provider writes it under the storage root, so every way in
    (`run`, `write_day_save`, a test, a wrapper) builds its `Phone` through this. `CLOCKWORK_DATA_DIR`
    must be set (`main` sets a throwaway one; the suite's conftest sets its own) and must not resolve to
    the owner's configured root (`storage.root`).
    """
    from engine.config import get_config
    from engine.persistence import storage

    if not os.environ.get(storage.DATA_DIR_ENV, "").strip():
        raise RuntimeError("simulate_social: CLOCKWORK_DATA_DIR is unset; a run must not write the owner's "
                           "storage (run it through main(), or set a temporary root)")
    real = storage._anchored(str(get_config().get("storage.root", storage.DEFAULT_ROOT) or storage.DEFAULT_ROOT))
    if storage.data_root().resolve() == real.resolve():
        raise RuntimeError(f"simulate_social: CLOCKWORK_DATA_DIR names the real storage root ({real}); "
                           "a run must not write the owner's storage")


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
#: ``Phone.voice``: voicing passes re-run after a turnstile deferral before the run is called stuck.
DEFERRAL_RETRIES = 3


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


def _landed(message: dict[str, Any]) -> bool:
    """Their message was written: by the model (`voiced` True) or as the engine's fallback line."""
    return message.get("voiced") is True or message.get("voiced") == "fallback"


def _bubbles(message: dict[str, Any]) -> int:
    """How many bubbles a message shows (a media message, or one with no bubbles, reads as one)."""
    return max(1, len(message.get("bubbles") or ()))


class Phone:
    """One run: a session in a keeps-nothing store, its stub voice, and one action at a time."""

    def __init__(self, seed: int, voice_policy: str, *, disk: Optional[Path] = None) -> None:
        from engine.scenes.default_state import SessionStore

        _private_storage()                         # first: never the owner's storage (T5 review C1)
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
        #: The session's real clock (``Session`` sets it; None: nothing is priced).
        self.clock: Optional[RealClock] = None
        #: Every priced action: (pid or "", in-game hour after it, real seconds, in-game minutes, in an episode).
        self.charges: list[tuple[str, float, float, float, bool]] = []
        #: Their messages the player has read (priced once each, ``read_bubble`` a bubble).
        self._read: set[str] = set()
        #: Actions after whose voicing something was still due (``voice``).
        self.unquiet = 0
        self.act("wait", args={"until": "1h"})   # a first payload to read (and the queue's first events)

    @property
    def now(self) -> float:
        return float(self.state.world_clock_hours)

    @property
    def phone(self) -> dict[str, Any]:
        return (self.payload.get("state") or {}).get("phone") or {}

    def _thread_of(self, action: str, target: str) -> Optional[dict[str, Any]]:
        """The thread an action acts in: its target, or the thread of the request it answers."""
        threads = self.state.social.get("threads") or {}
        if target in threads:
            return threads[target]
        request = (self.state.social.get("requests") or {}).get(target) or {}
        return threads.get(str(request.get("thread_id") or "")) if request else None

    def _theirs(self, thread: dict[str, Any]) -> list[dict[str, Any]]:
        from engine.social import messaging

        return [m for m in thread.get("messages") or []
                if m.get("from") == thread["pid"] and _landed(m) and messaging.shown(m)]

    def act(self, action: str, target: str = "", args: Optional[dict[str, Any]] = None,
            text: str = "") -> dict[str, Any]:
        """One phone action through the mechanics action, then voicing until quiet: the receipt."""
        from engine.session.store import release_turn
        from engine.social import convo, turn

        intent = {"action": action, "target": target, "args": dict(args or {}), "text": text}
        thread = self._thread_of(action, target) if target else None
        pid = str(thread["pid"]) if thread else ""
        talking = bool(pid) and convo.episode(self.state, pid) is not None
        known = {str(m["id"]) for m in self._theirs(thread)} if thread else set()
        began = self.now
        if not self.session.lock.acquire(blocking=False):      # this thread is the run's only one
            raise RuntimeError("simulate_social: the run's turn lock is held")
        try:
            self.payload = turn.run_mechanics(self.session, action, intent)
        finally:
            release_turn(self.session)                     # as run_guarded lets it go (Plan decision 31)
        self.voice()
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
        self._price(action, thread, pid, known, began, talking)
        for observe in self.observers:
            observe(self)
        return receipt

    def voice(self) -> None:
        """
        Voice until quiet (``voicer.run_until_quiet``). A pass that meets a held narration turnstile
        stops at once (``deferred``, T8); nothing else on this thread holds it, so the harness re-runs
        the pass, and a deferral that outlives ``DEFERRAL_RETRIES`` is a stuck run, raised -- never a
        silent stall. Anything still due after the retries is counted (``unquiet``), never dropped:
        the next action's voicing takes it.
        """
        from engine.social import turnstile, voicer

        for _ in range(DEFERRAL_RETRIES + 1):
            voicer.run_until_quiet(self.session, self.llm)
            if not voicer.pending(self.session):
                return
            if turnstile.of(self.session).holder is not None:
                raise RuntimeError("simulate_social: the narration turnstile is held on the run's only thread")
        self.unquiet += 1                  # still due after the retries (a pass's own cap): counted, reported

    def _price(self, action: str, thread: Optional[dict[str, Any]], pid: str, known: set[str],
               began: float, talking: bool) -> None:
        """The action's real seconds on the session's clock (``ACTION_PRICE``): in a thread, each of
        their bubbles not read before, and the model's seconds for each reply this action got."""
        if self.clock is None:
            return
        bubbles = replies = 0
        if thread is not None and action != "wait":
            for m in self._theirs(thread):
                mid = str(m["id"])
                if mid in self._read:
                    continue
                self._read.add(mid)
                bubbles += _bubbles(m)
                if mid not in known and self.llm is not None and action in ("send", "sign_off"):
                    replies += 1
        price = ACTION_PRICE.get(action, "")
        if not price and not bubbles:
            return
        before = self.clock.spent
        self.clock.charge(price, bubbles=bubbles, replies=replies)
        from engine.social import convo

        in_episode = talking or (bool(pid) and convo.episode(self.state, pid) is not None)
        self.charges.append((pid, self.now, self.clock.spent - before, (self.now - began) * 60.0, in_episode))

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
        from engine.social import away, kinds

        if not self.session.lock.acquire(blocking=False):
            raise RuntimeError("simulate_social: the run's turn lock is held")
        try:
            apply_effect(self.state, {"type": "social_settings", "field": "last_active_wall", "value": WALL_EPOCH})
        finally:
            release_turn(self.session)
        with kinds.collecting() as applied, _away_mode_real():
            away.apply_on_resume(self.session, wall=lambda: WALL_EPOCH + float(hours) * 3600.0)
        self.voice()
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
                    phone.act("wait", args={"until": "1h"})
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
    from engine.social import memory

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
            "stages": [(h["kind"], h["at"]) for h in memory.part(person, "history") or []],
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

#: The player's messages (30-80 characters: long enough to cost no `short_extra_energy`, never a
#: promise phrase, never a question that asks for a number). The chatty player's are 90-160.
TEXTS: tuple[str, ...] = (
    "how's your week been going so far?",
    "ha, that's fair. what did you end up doing today?",
    "honestly same, I've been running around all day",
    "that sounds good, I could do with a quiet evening",
    "oh nice, I haven't been there in ages",
    "I keep meaning to try that, is it any good?",
    "work was alright, a bit slow this afternoon",
    "ha okay, you'll have to tell me more about that",
)
CHATTY_TEXTS: tuple[str, ...] = (
    "honestly my week has been a lot, work has been chaotic and I've barely had a minute to myself, "
    "so this is a nice change",
    "that's such a good question, I think I'd say the thing I miss most is having a slow Sunday "
    "morning with nowhere to be at all",
    "I went for a long walk by the river after work and it was the first time in days I actually "
    "felt like I could breathe properly",
    "ha, I love that, I used to do something similar when I was younger and I still think about "
    "it more than I probably should",
)
#: The windows the player's own "talk later" may promise, tried soonest-opening first (spec §5.2).
PLAYER_WINDOWS: tuple[str, ...] = ("lunch", "after_work", "tonight", "morning")
#: A "talk later" promises a window opening at least this many hours ahead (one open now would be
#: kept by the next message at once).
PROMISE_LEAD_HOURS = 1.0


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
    #: Messages a day to any one person, at most (a ceiling a conversation rarely meets).
    sends_per_person_day = 60
    opener_share = 1.0
    answers_on_odd_days = True
    #: Ask for a number: never | warming (the band shows warming, every ask_every_days) | always.
    asks = "warming"
    ask_every_days = 2.0
    #: Exchanges the player stays in one conversation, drawn per episode, before its "talk later".
    patience: tuple[int, int] = (8, 30)
    #: Its "talk later" carries a promise of its own (`sign_off {who: me}`); else it just stops.
    promises = True
    #: The share of its own promises it breaks (never writes to them in the window).
    break_share = 0.0
    #: Writes first to no new match while this many people are talking with it (None: no limit).
    max_live: Optional[int] = None
    #: Talks only to the first person it talks with who reaches the `everyday` rung.
    devoted = False
    #: It writes first only while the session has time left for this many exchanges (a send, the
    #: model's reply and its reading): no conversation started that the session's end would cut short.
    start_reserve_exchanges = 8
    texts: tuple[str, ...] = TEXTS

    def __init__(self, phone: Phone, seed: int) -> None:
        from engine.game.rng import stable_rng

        self.phone = phone
        self.seed = seed
        self._rng = stable_rng
        self.liked_today: dict[str, int] = {}
        self.sent_today: dict[str, int] = {}
        self.day = -1
        self.asked_at: dict[str, float] = {}
        self.opened: set[str] = set()
        self.clock: Optional[RealClock] = None
        self.focus = ""
        self._said = 0
        #: The cold messages it sent: (pid, thread id, in-game hour, depth).
        self.cold: list[tuple[str, str, float, int]] = []

    # -- small reads ---------------------------------------------------------

    def _wants(self, key: str, share: float) -> bool:
        """A stable per-key choice (the harness's own stable key, never a bare random)."""
        return self._rng(self.seed, f"simulate_social:{self.name}:{key}").random() < share

    def awake(self) -> bool:
        hour = self.phone.now % 24
        return HOUR_WAKE <= hour < HOUR_BED

    def over(self) -> bool:
        return self.clock is not None and self.clock.over

    def has_time_to_start(self) -> bool:
        """Time left in the session for a conversation of ``start_reserve_exchanges`` (no clock: always)."""
        clock = self.clock
        if clock is None:
            return True
        exchange = REAL_SECONDS["send"] + REAL_SECONDS["read_bubble"] + clock.model_seconds
        return clock.budget - clock.spent >= self.start_reserve_exchanges * exchange

    @property
    def social(self) -> dict[str, Any]:
        return self.phone.state.social

    def _person(self, pid: str) -> dict[str, Any]:
        return (self.social.get("people") or {}).get(pid) or {}

    def _text(self) -> str:
        self._said += 1
        return self.texts[self._said % len(self.texts)]

    def _last_shown(self, thread: dict[str, Any]) -> Optional[dict[str, Any]]:
        from engine.social import messaging

        # The engine's own reading: state's messages, else a spilled thread's stamp (so a run on disk reads
        # what a run in memory does).
        return messaging.last_shown(thread) if thread else None

    def _avoids(self, pid: str) -> bool:
        """A promise it means to break is open now for them: it writes them nothing in its window."""
        now = self.phone.now
        return any(r["pid"] == pid and r["by"] == "player" and r["status"] == "open"
                   and float(r["opens_at"]) <= now <= float(r["closes_at"]) and self._breaks(r["id"])
                   for r in (self.social.get("promises") or {}).values())

    def _breaks(self, promise_id: str) -> bool:
        return self.break_share > 0 and self._wants(f"break:{promise_id}", self.break_share)

    def _allowed(self, pid: str) -> bool:
        """Devoted to someone: only them."""
        return not self.focus or pid == self.focus

    def _theirs_turn(self, thread: dict[str, Any]) -> bool:
        """Their message is the last word, voiced, and not their sign-off: the player's turn."""
        from engine.social import convo, messaging

        pid = str(thread["pid"])
        if not messaging.is_open(thread) or not self._allowed(pid) or self._avoids(pid):
            return False
        if not self.answers_on_odd_days and self.phone.state.world_day % 2:
            return False
        last = self._last_shown(thread)
        if last is None or last.get("from") != pid or not _landed(last):
            return False
        if str((last.get("decision") or {}).get("end") or "") == "sign_off":
            return False
        ep = convo.episode(self.phone.state, pid)
        return not (ep is not None and ep.get("end") == "signed_off")

    # -- one look ------------------------------------------------------------

    def look(self) -> None:
        phone = self.phone
        if phone.state.world_day != self.day:
            self.day = phone.state.world_day
            self.liked_today = {}
            self.sent_today = {}
        self.choose_focus()
        if not self.focus:
            self.deck()
        self.answer_requests()
        self.conversations()
        self.keep_promises()
        self.cold_starts()
        self.conversations()
        self.asks_for_numbers()

    def choose_focus(self) -> None:
        from engine.social import apps, growth

        if not self.devoted or self.focus:
            if self.focus and (self._person(self.focus).get("ghosted") or apps.gone(self.phone.state, self.focus)):
                self.focus = ""
            return
        for t in sorted((self.social.get("threads") or {}).values(), key=lambda t: str(t["thread_id"])):
            pid = str(t["pid"])
            if growth.depth(self.phone.state, pid) >= 1 and not self._person(pid).get("ghosted"):
                self.focus = pid
                return

    def deck(self) -> None:
        phone = self.phone
        if self.like_back:
            for row in list(phone.phone.get("likes_you") or []):
                if self.over():
                    return
                phone.act("like_back", row["pid"])
        for app, budget in (("matchstick", self.matchstick_likes), ("front_porch", self.porch_likes)):
            shown = 0
            while self.liked_today.get(app, 0) < budget and shown < 400 and not self.over():
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
            if self.over():
                return
            pid = str(row.get("pid"))
            if (row["from"] == "them" and row["status"] in ("pending", "later") and self._allowed(pid)
                    and not self._avoids(pid)):
                phone.act("answer", row["id"], {"reply": "yes"})

    def _send(self, tid: str, pid: str, *, cold: bool = False) -> None:
        from engine.social import growth

        for i in range(self.sends_per_reply):
            if self.sent_today.get(pid, 0) >= self.sends_per_person_day:
                return
            if cold and i == 0:
                self.cold.append((pid, tid, self.phone.now, growth.depth(self.phone.state, pid)))
            if i == 0 and int(((self.social.get("threads") or {}).get(tid) or {}).get("unread") or 0):
                # It writes from inside the thread, as the client does: what it answers is read (§9.4's
                # receipts are written by `open_thread`, T9 fix round 2).
                self.phone.act("open_thread", tid)
            self.phone.act("send", tid, {"kind": "text"}, self._text() if i == 0 else "?")
            self.sent_today[pid] = self.sent_today.get(pid, 0) + 1

    def _patience(self, pid: str, ep: dict[str, Any]) -> int:
        low, high = self.patience
        return self._rng(self.seed, f"simulate_social:{self.name}:patience:{pid}:{ep['id']}").randint(low, high)

    def sign_off(self, tid: str, pid: str, *, not_before: Optional[float] = None) -> bool:
        """"Talk later" with a promise of its own: the soonest of ``PLAYER_WINDOWS`` opening at least
        ``PROMISE_LEAD_HOURS`` ahead (and not before ``not_before``), in its own waking hours. False when
        none is in reach (nothing sent)."""
        from engine.social import promises

        now = self.phone.now
        earliest = max(now + PROMISE_LEAD_HOURS, float(not_before if not_before is not None else now))
        best: Optional[tuple[float, str]] = None
        for window in PLAYER_WINDOWS:
            span = promises.span_for(self.phone.state, pid, by="player", window=window, at=now)
            if span is None or span[0] < earliest or not HOUR_WAKE <= span[0] % 24 < HOUR_BED - 1:
                continue                                  # too soon, or while it sleeps: it could not keep it
            if best is None or span[0] < best[0]:
                best = (span[0], window)
        if best is None:
            return False
        receipt = self.phone.act("sign_off", tid, {"who": "me", "window": best[1]})
        self.sent_today[pid] = self.sent_today.get(pid, 0) + 1
        return not receipt.get("refused")

    def chat(self, tid: str) -> None:
        """Answer every reply in this conversation until it is not the player's turn: they signed off,
        their reply has not come, its patience ran out ("talk later"), or the session's time did."""
        from engine.social import convo

        thread = (self.social.get("threads") or {}).get(tid) or {}
        pid = str(thread.get("pid") or "")
        for _ in range(80):
            if self.over() or not self._theirs_turn((self.social.get("threads") or {}).get(tid) or {}):
                return
            if self.sent_today.get(pid, 0) >= self.sends_per_person_day:
                return
            ep = convo.episode(self.phone.state, pid)
            if ep is not None and ep.get("end") == "none" and int(ep["exchanges"]) >= self._patience(pid, ep):
                if self.promises:
                    self.sign_off(tid, pid)
                return
            self._send(tid, pid)

    def conversations(self) -> None:
        for tid in sorted((self.social.get("threads") or {})):
            if self.over():
                return
            thread = (self.social.get("threads") or {}).get(tid) or {}
            if self._theirs_turn(thread):
                if int(thread.get("unread") or 0):
                    self.phone.act("open_thread", tid)
                self.chat(tid)

    def keep_promises(self) -> None:
        """Each promise of its own whose window is open now: a message to them (unless it breaks it)."""
        from engine.social import messaging

        now = self.phone.now
        for row in sorted((self.social.get("promises") or {}).values(), key=lambda r: (r["opens_at"], r["id"])):
            if self.over():
                return
            if row["by"] != "player" or row["status"] != "open" or self._breaks(row["id"]):
                continue
            if not (float(row["opens_at"]) <= now <= float(row["closes_at"])):
                continue
            tid = messaging.thread_for(self.phone.state, str(row["pid"]))
            if tid is None or not messaging.is_open(messaging.thread(self.phone.state, tid)):
                continue
            self._send(tid, str(row["pid"]), cold=self._is_cold(str(row["pid"])))
            self.chat(tid)

    def _is_cold(self, pid: str) -> bool:
        from engine.social import convo

        ep = convo.episode(self.phone.state, pid)
        return ep is None or (ep.get("end") == "signed_off" and int(ep.get("after_left", 0)) <= 0)

    def _live_talking(self) -> list[str]:
        from engine.social import apps, kinds

        out = []
        for t in (self.social.get("threads") or {}).values():
            pid = str(t["pid"])
            person = self._person(pid)
            if (kinds.stage_rank(person.get("stage")) >= kinds.stage_rank("talking") and not person.get("ghosted")
                    and not apps.gone(self.phone.state, pid)):
                out.append(pid)
        return out

    def cold_starts(self) -> None:
        """Once a day, a first message to each person it is talking with and has not talked to today;
        then an opener to each new match (none past ``max_live``)."""
        from engine.social import apps, kinds, messaging

        state = self.phone.state
        threads = sorted((self.social.get("threads") or {}).values(), key=lambda t: str(t["thread_id"]))
        talking = self._live_talking()
        for t in threads:
            if self.over() or not self.has_time_to_start():
                return
            pid, tid = str(t["pid"]), str(t["thread_id"])
            if (pid not in talking or not messaging.is_open(t) or not self._allowed(pid) or self._avoids(pid)
                    or not self._is_cold(pid)):
                continue
            if self.max_live is not None and pid not in sorted(talking)[: self.max_live]:
                continue
            last = self._last_shown(t)
            if last is not None and last.get("from") == "player":
                continue                                   # no double text: their read is still to come
            contact = self._person(pid).get("last_player_at")     # kept on the person: a spilled thread too
            if contact is not None and int(float(contact) // 24) == int(self.phone.now // 24):
                continue                                   # talked to them today already
            self._send(tid, pid, cold=True)
            self.chat(tid)
        if self.focus:
            return
        for t in threads:
            if self.over() or not self.has_time_to_start():
                return
            pid, tid = str(t["pid"]), str(t["thread_id"])
            if (self._last_shown(t) is not None or tid in self.opened or not messaging.is_open(t)
                    or apps.gone(state, pid)):                # a word in it (a spilled thread's stamp too): not new
                continue
            if self.max_live is not None and len(self._live_talking()) >= self.max_live:
                return
            if kinds.stage_rank(self._person(pid).get("stage")) < 0:
                continue
            self.opened.add(tid)
            if not self._wants(f"{pid}:opener", self.opener_share):
                continue
            self._send(tid, pid, cold=True)
            self.chat(tid)

    def asks_for_numbers(self) -> None:
        from engine.social import relationships

        if self.asks == "never":
            return
        for t in sorted((self.social.get("threads") or {}).values(), key=lambda t: str(t["thread_id"])):
            if self.over():
                return
            pid = str(t["pid"])
            person = self._person(pid)
            if person.get("stage") != "talking" or not self._allowed(pid) or person.get("ghosted") or self._avoids(pid):
                continue
            if self.asks == "warming" and relationships.band(person) in ("", "new"):
                continue
            if self.asks == "warming" and self.phone.now - self.asked_at.get(pid, -1e9) < self.ask_every_days * 24:
                continue
            if any(r.get("pid") == pid and r.get("what") == "number" and r.get("status") in ("pending", "later")
                   for r in (self.social.get("requests") or {}).values()):
                continue
            self.asked_at[pid] = self.phone.now
            self.phone.act("ask", str(t["thread_id"]), {"what": "number"})

    # -- between looks, and the end of a session ------------------------------

    def _next_own_promise(self, before: float) -> Optional[dict[str, Any]]:
        """Its soonest open promise still to open, before ``before``, that it means to keep."""
        now = self.phone.now
        rows = [r for r in (self.social.get("promises") or {}).values()
                if r["by"] == "player" and r["status"] == "open" and now < float(r["opens_at"]) < before
                and not self._breaks(r["id"])]
        return min(rows, key=lambda r: (float(r["opens_at"]), r["id"])) if rows else None

    def _bedtime(self) -> float:
        now = self.phone.now
        return now - (now % 24) + HOUR_BED

    def wait_for_more(self) -> bool:
        """Live: until the phone buzzes, or one of its own promises opens if that is sooner; else an hour.
        False, waiting nothing, when nothing comes before its bedtime: the session's day is over."""
        from engine.social import turn

        phone = self.phone
        if self.looks != "live":
            if phone.now + 1.0 >= self._bedtime():
                return False
            phone.act("wait", args={"until": "1h"})
            return True
        due = turn._next_notifying_at(phone.state)
        mine = self._next_own_promise(due if due is not None else self._bedtime())
        if mine is not None:
            phone.act("wait", args={"until": f"{turn.PROMISE_TARGET}{mine['id']}"})
            return True
        if due is None or due >= self._bedtime():
            return False
        before = phone.now
        phone.act("wait", args={"until": "next"})
        if phone.now - before < 1.0 / 60.0:
            phone.act("wait", args={"until": "1h"})        # nothing it can answer is due: never a busy loop
        return True

    def _next_wake(self) -> float:
        now = self.phone.now
        return now - (now % 24) + 24.0 + HOUR_WAKE

    def _sign_off_all(self) -> None:
        """"Talk later" wherever it is the player's turn in a conversation still going: a promise for
        the next session (its next waking morning or later), when it will be back."""
        from engine.social import convo

        for tid in sorted((self.social.get("threads") or {})):
            thread = (self.social.get("threads") or {}).get(tid) or {}
            pid = str(thread.get("pid") or "")
            ep = convo.episode(self.phone.state, pid) if pid else None
            if ep is not None and ep.get("end") in ("none", "winding") and self._theirs_turn(thread):
                self.sign_off(tid, pid, not_before=self._next_wake())

    def wind_down(self) -> None:
        """The session's end: "talk later" wherever it is still the player's turn in a conversation
        (promising the next session); then each promise of its own open now, or opening before its
        bedtime, kept -- one message in its window, waiting for it if need be -- and "talk later" (for
        the next session) if they answer at once."""
        from engine.social import messaging, turn

        if not self.promises:
            return
        phone = self.phone
        for _ in range(40):
            self._sign_off_all()
            now = phone.now
            due = [r for r in (self.social.get("promises") or {}).values()
                   if r["by"] == "player" and r["status"] == "open" and not self._breaks(r["id"])
                   and float(r["opens_at"]) <= now <= float(r["closes_at"])]
            for row in sorted(due, key=lambda r: (r["opens_at"], r["id"])):
                tid = messaging.thread_for(phone.state, str(row["pid"]))
                if tid is not None and messaging.is_open(messaging.thread(phone.state, tid)):
                    self._send(tid, str(row["pid"]), cold=self._is_cold(str(row["pid"])))
            self._sign_off_all()
            mine = self._next_own_promise(self._bedtime())
            if mine is None:
                return
            phone.act("wait", args={"until": f"{turn.PROMISE_TARGET}{mine['id']}"})

    # -- the day (v0.22's driver: a look, then the wait to the next) ----------

    def step(self) -> None:
        """One look if it is time for one, then the wait to the next (no real clock: ``write_day_save``'s
        and the tests' day-driven runs)."""
        phone = self.phone
        if not self.awake():
            phone.act("wait", args={"until": "morning"})
            return
        if self.looks == "live":
            self.look()
            if not self.wait_for_more():
                phone.act("wait", args={"until": "morning"})
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
    promises = False
    patience = (3, 8)


class Pushy(Policy):
    name = "pushy"
    sends_per_reply = 2
    asks = "always"


class Devoted(Policy):
    name = "devoted"
    devoted = True


class Bachelor(Policy):
    name = "bachelor"
    max_live = 6


class Flaky(Policy):
    name = "flaky"
    break_share = 1.0 / 3.0


class Chatty(Policy):
    name = "chatty"
    texts = CHATTY_TEXTS


POLICIES: dict[str, type[Policy]] = {p.name: p for p in (Attentive, Swiper, Picky, Slow, Neglectful, Pushy,
                                                        Devoted, Bachelor, Flaky, Chatty)}


# ---------------------------------------------------------------------------
# A session (T9: phone only)
# ---------------------------------------------------------------------------


class Session:
    """
    One phone-only session (spec §3.4): the policy looks and waits for more until ``real_seconds_budget``
    real seconds are spent (``RealClock``) or its bedtime comes, winds down, and goes to bed (``wait
    {until: morning}``). ``play`` returns the session's span.
    """

    def __init__(self, phone: Phone, policy: Policy, *, model_seconds: float = DEFAULT_MODEL_SECONDS,
                 real_seconds_budget: float = SESSION_REAL_SECONDS) -> None:
        self.phone = phone
        self.policy = policy
        self.model_seconds = float(model_seconds)
        self.real_seconds_budget = float(real_seconds_budget)

    def play(self) -> dict[str, Any]:
        phone, policy = self.phone, self.policy
        if not policy.awake():
            phone.act("wait", args={"until": "morning"})
        clock = RealClock(self.model_seconds, budget=self.real_seconds_budget)
        phone.clock = policy.clock = clock
        start = phone.now
        try:
            while policy.awake() and not clock.over:
                before = (phone.now, clock.spent)
                hour = int(phone.now % 24)
                if policy.looks == "live" or (hour in policy.looks
                                              and getattr(policy, "_looked", None) != (phone.state.world_day, hour)):
                    policy._looked = (phone.state.world_day, hour)
                    policy.look()
                if clock.over or not policy.awake():
                    break
                if not policy.wait_for_more():
                    break
                if (phone.now, clock.spent) == before:
                    phone.act("wait", args={"until": "1h"})
            policy.wind_down()
            end = phone.now
        finally:
            phone.clock = policy.clock = None
        phone.act("wait", args={"until": "morning"})
        return {"start": start, "end": end, "real_seconds": round(clock.spent, 1)}


# ---------------------------------------------------------------------------
# One run, observed
# ---------------------------------------------------------------------------


class Recorder:
    """
    What the engine decides inside an action that the state does not keep: each episode as it opens
    (its depth then) and closes (its exchanges, how it ended), each episode-start draw, and each
    decided reply's mode. Fed by ``_recording``'s wrappers round `engine.social.convo`'s own
    functions, for one run only.
    """

    def __init__(self) -> None:
        self.open_depth: dict[str, int] = {}
        self.modes: dict[str, list[str]] = {}
        self.episodes: list[dict[str, Any]] = []
        #: Episodes the player wrote in while they were open (a conversation, not an answer left unread).
        self.joined: set[str] = set()
        self.starts: list[dict[str, Any]] = []
        #: Chatting or deep decisions for a `short` texter below depth 2 (T7 review M1), and all such.
        self.short_full = 0
        self.full = 0


@contextmanager
def _recording(rec: Recorder) -> Iterator[None]:
    """`convo._open`, `_close`, `_episode_start` and `decide` wrapped for ``rec``, restored after."""
    from engine.social import convo, growth, population

    real = {name: getattr(convo, name) for name in ("_open", "_close", "_episode_start", "decide", "on_player_send")}

    def on_player_send(state, pid, thread_id, at, *, note=True):
        ep = convo.episode(state, pid)
        if note and ep is not None and ep.get("end") != "signed_off":
            rec.joined.add(str(ep["id"]))
        return real["on_player_send"](state, pid, thread_id, at, note=note)

    def _open(state, pid, person, effect, at):
        out = real["_open"](state, pid, person, effect, at)
        if out.get("ok"):
            rec.open_depth[str(out["episode"])] = growth.depth(state, pid)
        return out

    def _close(state, pid, person, ep, effect, at):
        end = str(effect.get("end") or ("signed_off" if ep.get("end") == "signed_off" else "lapsed"))
        rec.episodes.append({"pid": pid, "id": ep["id"], "kind": ep.get("kind"), "exchanges": int(ep["exchanges"]),
                             "end": end, "end_key": str(ep.get("end_key") or ""), "started_at": ep["started_at"],
                             "closed_at": at, "depth": rec.open_depth.get(str(ep["id"]), growth.depth(state, pid)),
                             "modes": list(rec.modes.get(str(ep["id"]), [])), "joined": str(ep["id"]) in rec.joined})
        return real["_close"](state, pid, person, ep, effect, at)

    def _episode_start(state, pid, at):
        out = real["_episode_start"](state, pid, at)
        rec.starts.append({"pid": pid, "at": at, "depth": growth.depth(state, pid), "result": out})
        return out

    def decide(state, pid, thread_id, at, *, situation="reply", exchange=True):
        decision = real["decide"](state, pid, thread_id, at, situation=situation, exchange=exchange)
        ep = convo.episode(state, pid)
        if exchange and ep is not None:
            rec.modes.setdefault(str(ep["id"]), []).append(decision.mode)
            if decision.mode in ("chatting", "deep"):
                rec.full += 1
                row = next((r for r in population.table("texting_styles")
                            if isinstance(r, dict) and r.get("id") == population.profile(state, pid).texting_style), {})
                if row.get("length") == "short" and growth.depth(state, pid) < 2:
                    rec.short_full += 1
        return decision

    for name, fn in (("_open", _open), ("_close", _close), ("_episode_start", _episode_start), ("decide", decide),
                     ("on_player_send", on_player_send)):
        setattr(convo, name, fn)
    try:
        yield
    finally:
        for name, fn in real.items():
            setattr(convo, name, fn)


class Observer:
    """
    What the state does not keep with a time: when a person first ghosted,
    reached each closeness band and the `everyday` rung (seen after each
    action, so to within one action), and when they stopped being live.
    """

    def __init__(self) -> None:
        self.ghosted_at: dict[str, float] = {}
        self.band_at: dict[str, dict[str, float]] = {}
        self.depth1_at: dict[str, float] = {}
        self.left_at: dict[str, float] = {}

    def __call__(self, phone: Phone) -> None:
        from engine.social import apps, growth, relationships

        state = phone.state
        now = phone.now
        people = state.social.get("people") or {}
        names = [str(r["name"]) for r in relationships._bands()]
        for pid in {t["pid"] for t in (state.social.get("threads") or {}).values()}:
            person = people.get(pid) or {}
            if person.get("ghosted") and pid not in self.ghosted_at:
                self.ghosted_at[pid] = now
            if pid not in self.left_at and person.get("stage") and (
                    not relationships.live(person) or person.get("ghosted") or apps.gone(state, pid)):
                self.left_at[pid] = now
            if pid not in self.depth1_at and person.get("stage") and growth.depth(state, pid) >= 1:
                self.depth1_at[pid] = now
            if person.get("stage"):
                seen = self.band_at.setdefault(pid, {})
                for name in names[:names.index(relationships.band(person)) + 1]:
                    seen.setdefault(name, now)


def run(seed: int, sessions: int, policy: str, voice_policy: str = DEFAULT_VOICE, *,
        model_seconds: float = DEFAULT_MODEL_SECONDS, disk: Optional[Path] = None) -> dict[str, Any]:
    """
    One run of ``sessions`` phone-only sessions (``Session``) at ``model_seconds`` a reply: its raw
    measurements (``report`` folds many). ``disk``: a directory the run saves under, spilling its
    threads into the archive after every action as play does (``Phone.spill``); the measurements read
    the archive too, so they are the same either way.
    """
    if policy not in POLICIES:
        raise ValueError(f"simulate_social: no policy {policy!r} ({', '.join(POLICIES)})")
    started = time.perf_counter()
    rec = Recorder()
    with _quiet_summaries(), _recording(rec):
        phone = Phone(seed, voice_policy, disk=disk)
        observer = Observer()
        phone.observers.append(observer)
        player = POLICIES[policy](phone, seed)
        try:
            spans = [Session(phone, player, model_seconds=model_seconds).play() for _ in range(int(sessions))]
            return _measure(phone, player, observer, rec, spans, seed, policy, voice_policy, float(model_seconds),
                            time.perf_counter() - started)
        finally:
            phone.close()


def write_day_save(seed: int, days: int, policy: str, out: Path, voice_policy: str = "romantic_model", *,
                   model_seconds: float = DEFAULT_MODEL_SECONDS) -> Path:
    """
    A day-``days`` run of ``policy`` saved under ``out`` (spec §17.2's size
    bound): played on disk as ``days`` phone-only sessions (``Session``, one
    an in-game day, each from waking to the next morning), its threads
    spilled into the archive after every action as play's saves do, then the
    archive spilled once more and ``save.json`` written through the store, as
    ``saves.save_now`` writes it. The save's directory (``save.json``,
    ``phone_archive.jsonl``).
    """
    from engine.session.store import release_turn
    from engine.social import archive

    with _quiet_summaries():
        phone = Phone(seed, voice_policy, disk=Path(out))
        try:
            player = POLICIES[policy](phone, seed)
            for _ in range(int(days)):
                Session(phone, player, model_seconds=model_seconds).play()
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


#: The end reasons that are their day (spec §17.2's "schedule or sleep"): a schedule boundary's
#: words (`convo._reason`), and a glance at work.
SCHEDULE_KEYS: frozenset[str] = frozenset({"work", "lunch_over", "asleep", "out", "early", "glance"})


def _end_class(ep: dict[str, Any]) -> str:
    key = str(ep.get("end_key") or "")
    if key in SCHEDULE_KEYS:
        return "schedule"
    if key in ("energy", "player", "length"):
        return key
    return "lapsed"


def _initiation_situations() -> set[str]:
    from engine import social

    out = {"window_message"}
    for arch in (social.data("behaviours").get("archetypes") or {}).values():
        for row in (arch or {}).get("initiations") or ():
            out.add(str(row.get("instruction") or "window_message"))
    return out


def _measure(phone: Phone, player: Policy, observer: Observer, rec: Recorder, spans: list[dict[str, Any]],
             seed: int, policy: str, voice_policy: str, model_seconds: float, wall: float) -> dict[str, Any]:
    from engine import social
    from engine.social import attrs, memory, population

    state = phone.state
    people = state.social.get("people") or {}
    threads = state.social.get("threads") or {}
    end = phone.now
    initiations = _initiation_situations()
    seconds_by: dict[str, list[tuple[float, float]]] = {}
    for pid, at, seconds, _minutes, _ep in phone.charges:
        if pid:
            seconds_by.setdefault(pid, []).append((at, seconds))
    rows: list[dict[str, Any]] = []
    for pid in sorted({t["pid"] for t in threads.values()}):
        person = people.get(pid) or {}
        history = memory.part(person, "history") or []
        theirs: list[tuple[float, str, str]] = []           # (at, kind, situation) of their voiced messages
        for t in (t for t in threads.values() if t["pid"] == pid):
            for m in phone.messages(t):
                if m.get("from") == pid and _landed(m):
                    theirs.append((float(m["at"]), str(m.get("kind")),
                                   str((m.get("decision") or {}).get("situation") or "")))
        matched_at = person.get("matched_at")
        rows.append({
            "pid": pid,
            "archetype": population.profile(state, pid).archetype,
            "pace": float(attrs.of(state, pid).get("pace") or 1.0),
            "matched_at": None if matched_at is None else float(matched_at),
            "talking_at": _first(history, "talking"),
            "numbers_at": _first(history, "numbers"),
            "depth1_at": observer.depth1_at.get(pid),
            "ghosted_at": observer.ghosted_at.get(pid),
            "left_at": observer.left_at.get(pid),
            "band_at": observer.band_at.get(pid, {}),
            "theirs": theirs,
            "charges": seconds_by.get(pid, []),
            "initiations": sum(1 for _at, _k, s in theirs if s in initiations),
        })
    cold = []
    for pid, tid, at, depth in player.cold:
        t = threads.get(tid) or {}
        answered = None
        if at + 1.0 <= end:
            answered = any(m.get("from") == pid and _landed(m) and at <= float(m["at"]) <= at + 1.0
                           for m in phone.messages(t))
        cold.append({"pid": pid, "at": at, "depth": depth, "answered_1h": answered})
    # Only an open one's window matters (judged or not by the run's end); a closed one is its side and status.
    promises = [{"by": r["by"], "status": r["status"],
                 "closes_at": float(r["closes_at"]) if r["status"] == "open" else -1.0}
                for r in (state.social.get("promises") or {}).values()]
    # Closed rows a save's compaction forgot (`promises.forget_closed`), as their tallies on the person.
    for person in people.values():
        for by, counts in ((person or {}).get("promises_closed") or {}).items():
            for status, n in (counts or {}).items():
                promises += [{"by": by, "status": status, "closes_at": -1.0}] * int(n)
    promises.sort(key=lambda r: (r["by"], r["status"], r["closes_at"]))
    stub = phone.llm
    return {
        "seed": seed, "sessions": len(spans), "policy": policy, "voice": voice_policy,
        "model_seconds": model_seconds, "end": end, "spans": spans,
        "people": rows, "episodes": [e for e in rec.episodes if e.get("kind") == "chat"],
        "starts": rec.starts, "cold": cold, "promises": promises,
        "charges": [[round(s, 3), round(m, 4), bool(e)] for _p, _a, s, m, e in phone.charges],
        "prompt_tokens": dict(stub.prompt_tokens) if stub is not None else {},
        "short_full": rec.short_full, "full": rec.full,
        "actions": phone.actions, "refused": phone.refused, "refusals": dict(phone.refusals),
        "unquiet": phone.unquiet, "wall_seconds": round(wall, 2),
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


def _terciles(values: list[float]) -> tuple[float, float]:
    """The two cut points that split ``values`` into thirds (slow below the first, fast above the second)."""
    ordered = sorted(values)
    if not ordered:
        return (0.0, 0.0)
    return ordered[len(ordered) // 3], ordered[(2 * len(ordered)) // 3]


def _tercile(pace: float, cuts: tuple[float, float]) -> str:
    return "slow" if pace < cuts[0] else ("mid" if pace < cuts[1] else "fast")


def _real_minutes(row: dict[str, Any], until: float) -> float:
    """The real minutes the player spent on this person from their match up to ``until`` (inclusive)."""
    began = row.get("matched_at")
    return sum(seconds for at, seconds in row["charges"]
               if (began is None or at >= float(began) - 1e-9) and at <= until + 1e-9) / 60.0


def _session_of(spans: list[dict[str, Any]], at: float) -> Optional[int]:
    for i, span in enumerate(spans):
        if float(span["start"]) - 1e-9 <= at <= float(span["end"]) + 1e-9:
            return i
    return None


def _fold_promises(runs: list[dict[str, Any]], by: str) -> Optional[float]:
    kept = judged = 0
    for r in runs:
        for p in r["promises"]:
            if p["by"] != by or p["status"] == "void":
                continue
            if p["status"] == "open" and (by == "player" or p["closes_at"] > float(r["end"])):
                continue                                     # not judged yet in the run
            judged += 1
            kept += p["status"] == "kept"
    return _share(kept, judged)


def fold(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """The report (``REPORT_ROWS`` plus ``also.*``) over finished runs: every row from the runs of the
    first run's policy, but a ``COMPANION_ROWS`` row from its own policy's runs."""
    out: dict[str, Any] = {key: None for key in REPORT_ROWS}
    if not runs:
        return out
    main = str(runs[0]["policy"])
    by_policy: dict[str, list[dict[str, Any]]] = {}
    for r in runs:
        by_policy.setdefault(str(r["policy"]), []).append(r)
    mine = by_policy[main]
    # A conversation: an episode with a reply in it that the player wrote in while it was open (an answer
    # that landed while the player was away, and lapsed unread, is not one).
    every = [e for r in mine for e in r["episodes"] if int(e["exchanges"]) >= 1]
    episodes = [e for e in every if e.get("joined")]
    shallow = [e for e in episodes if int(e["depth"]) == 0]
    deep = [e for e in episodes if int(e["depth"]) >= 2]
    out["exchanges_per_episode.d0"] = _median([float(e["exchanges"]) for e in shallow])
    out["exchanges_per_episode.d2plus"] = _median([float(e["exchanges"]) for e in deep])
    classes = [_end_class(e) for e in episodes]
    for key in ("schedule", "energy", "player"):
        out[f"end_reason.{key}"] = _share(classes.count(key), len(classes))
    cold = [c for r in mine for c in r["cold"] if c["depth"] == 0 and c["answered_1h"] is not None]
    out["cold_unanswered_1h.d0"] = _share(sum(1 for c in cold if not c["answered_1h"]), len(cold))
    starts = [s for r in mine for s in r["starts"]]
    for name, chosen in (("d0", [s for s in starts if s["depth"] == 0]),
                         ("d2plus", [s for s in starts if s["depth"] >= 2])):
        out[f"ghosted_per_episode.{name}"] = _share(sum(1 for s in chosen if s["result"] == "ghosted"), len(chosen))
    rows = [p for r in mine for p in r["people"]]
    cuts = _terciles([p["pace"] for p in rows if p["matched_at"] is not None])
    for key, then in (("chat_minutes_to_numbers", "numbers_at"), ("also.chat_minutes_to_depth1", "depth1_at")):
        for band in ("fast", "mid", "slow"):
            values = [_real_minutes(p, float(p[then])) for p in rows
                      if p.get(then) is not None and p["matched_at"] is not None and _tercile(p["pace"], cuts) == band]
            out[f"{key}.{band}"] = _median(values)
    # Numbers within the first session they talked in (not the run's last session: censored).
    hits = total = hits_next = 0
    for r in mine:
        spans = r["spans"]
        talked: dict[str, int] = {}
        for e in r["episodes"]:
            if int(e["exchanges"]) >= 1:
                k = _session_of(spans, float(e["started_at"]))
                if k is not None and k < len(spans) - 1:
                    talked[e["pid"]] = min(talked.get(e["pid"], k), k)
        people = {p["pid"]: p for p in r["people"]}
        for pid, k in talked.items():
            total += 1
            numbers = (people.get(pid) or {}).get("numbers_at")
            if numbers is not None and float(numbers) <= float(spans[k]["end"]) + 1e-9:
                hits += 1
            if numbers is not None and float(numbers) <= float(spans[min(k + 1, len(spans) - 1)]["end"]) + 1e-9:
                hits_next += 1
    out["numbers_within_session"] = _share(hits, total)
    out["also.numbers_by_next_session"] = _share(hits_next, total)
    out["person_promises_kept"] = _fold_promises(mine, "person")
    for row in ("player_promises_kept.attentive", "player_promises_kept.flaky"):
        name = row.split(".", 1)[1]
        out[row] = _fold_promises(by_policy[name], "player") if name in by_policy else None
    long_modes = [m for e in episodes if int(e["exchanges"]) >= 6 for m in e["modes"]]
    out["full_replies_in_long_episodes"] = _share(sum(1 for m in long_modes if m in ("chatting", "deep")),
                                                  len(long_modes))
    chat = [c for r in mine for c in r["charges"] if c[2]]
    chat_seconds = sum(c[0] for c in chat)
    out["ratio.chat"] = None if chat_seconds <= 0 else round(sum(c[1] for c in chat) / (chat_seconds / 60.0), 3)
    real = sum(float(s["real_seconds"]) for r in mine for s in r["spans"])
    ingame = sum((float(s["end"]) - float(s["start"])) * 60.0 for r in mine for s in r["spans"])
    out["ratio.overall"] = None if real <= 0 else round(ingame / (real / 60.0), 3)
    # -- also.* -----------------------------------------------------------------------------------
    for key in ("schedule", "energy", "player", "length", "lapsed"):
        out[f"also.end_reason.{key}"] = _share(classes.count(key), len(classes))
    out["also.episodes_per_run"] = round(len(episodes) / len(mine), 2)
    out["also.unjoined_episodes_per_run"] = round((len(every) - len(episodes)) / len(mine), 2)
    out["also.exchanges_per_episode.d0_unjoined_included"] = _median(
        [float(e["exchanges"]) for e in every if int(e["depth"]) == 0])
    out["also.exchanges_per_episode.d1"] = _median([float(e["exchanges"]) for e in episodes if int(e["depth"]) == 1])
    out["also.left_on_read_per_episode_start"] = _share(sum(1 for s in starts if s["result"] == "left_on_read"),
                                                       len(starts))
    out["also.ghosted_per_episode_start"] = _share(sum(1 for s in starts if s["result"] == "ghosted"), len(starts))
    out["also.cold_unanswered_1h.all"] = _share(
        sum(1 for r in mine for c in r["cold"] if c["answered_1h"] is False),
        sum(1 for r in mine for c in r["cold"] if c["answered_1h"] is not None))
    live_days = 0.0
    for r in mine:
        for p in r["people"]:
            if p["talking_at"] is not None:
                stop = float(p["left_at"]) if p.get("left_at") is not None else float(r["end"])
                live_days += max(0.0, stop - float(p["talking_at"])) / 24.0
    out["also.initiations_per_live_person_day"] = (None if live_days <= 0 else
                                                   round(sum(p["initiations"] for p in rows) / live_days, 3))
    photos = 0
    weeks = 0.0
    for r in mine:
        for p in r["people"]:
            if p["talking_at"] is None:
                continue
            stop = float(p["left_at"]) if p.get("left_at") is not None else float(r["end"])
            weeks += max(0.0, stop - float(p["talking_at"])) / (7 * 24.0)
            photos += sum(1 for at, kind, _s in p["theirs"] if kind == "photo" and float(p["talking_at"]) <= at <= stop)
    out["also.photos_per_relationship_week"] = None if weeks <= 0 else round(photos / weeks, 3)
    out["also.talking_per_run"] = round(sum(1 for p in rows if p["talking_at"] is not None) / len(mine), 2)
    out["also.depth1_per_run"] = round(sum(1 for p in rows if p["depth1_at"] is not None) / len(mine), 2)
    out["also.numbers_per_run"] = round(sum(1 for p in rows if p["numbers_at"] is not None) / len(mine), 2)
    out["also.matches_per_run"] = round(sum(1 for p in rows if p["matched_at"] is not None) / len(mine), 2)
    for key, band in BAND_ROWS:
        for arch in sorted({a for r in mine for a in r["archetypes"]}):
            chosen = [p for p in rows if p["archetype"] == arch and p["matched_at"] is not None and band in p["band_at"]]
            out[f"also.days_to_{key}.{arch}"] = _median(
                [max(0.0, (p["band_at"][band] - p["matched_at"]) / 24.0) for p in chosen])
            out[f"also.real_hours_to_{key}.{arch}"] = _median(
                [_real_minutes(p, p["band_at"][band]) / 60.0 for p in chosen])
    for mode in ("quick", "chatting", "deep"):
        tokens = [float(n) for r in mine for n in (r.get("prompt_tokens") or {}).get(mode, [])]
        out[f"also.prompt_tokens.{mode}.p50"] = _pct(tokens, 0.5)
        out[f"also.prompt_tokens.{mode}.p95"] = _pct(tokens, 0.95)
        out[f"also.replies.{mode}"] = len(tokens)
    out["also.short_texter_full_replies_below_depth2"] = _share(sum(r["short_full"] for r in mine),
                                                               sum(r["full"] for r in mine))
    per_minute = []
    for r in mine:
        bucket = 0.0
        count = 0
        for seconds, _m, _e in r["charges"]:
            bucket += seconds
            count += 1
            if bucket >= 60.0:
                per_minute.append(count * 60.0 / bucket)
                bucket, count = 0.0, 0
    out["also.actions_per_real_minute_max"] = round(max(per_minute), 2) if per_minute else None
    out["also.real_minutes_per_session"] = round(real / 60.0 / max(1, sum(len(r["spans"]) for r in mine)), 1)
    out["also.ingame_hours_per_session"] = round(ingame / 60.0 / max(1, sum(len(r["spans"]) for r in mine)), 2)
    out["also.actions_per_run"] = round(sum(r["actions"] for r in mine) / len(mine), 1)
    out["also.refused_per_run"] = round(sum(r["refused"] for r in mine) / len(mine), 1)
    out["also.unquiet_per_run"] = round(sum(r.get("unquiet", 0) for r in mine) / len(mine), 2)
    reasons: dict[str, int] = {}
    for r in mine:
        for key, count in (r.get("refusals") or {}).items():
            reasons[key] = reasons.get(key, 0) + int(count)
    out["also.refusals_per_run"] = {key: round(count / len(mine), 1) for key, count in
                                    sorted(reasons.items(), key=lambda kv: (-kv[1], kv[0]))[:10]}
    out["also.runs"] = len(mine)
    out["also.model_seconds"] = mine[0].get("model_seconds")
    return out


def companions(policy: str) -> list[str]:
    """The other policies a report of ``policy`` runs beside it, for its ``COMPANION_ROWS``."""
    return sorted({p for p in COMPANION_ROWS.values() if p != policy})


def report(seeds: Iterable[int], sessions: int = 6, policy: str = "attentive", voice_policy: str = DEFAULT_VOICE, *,
           model_seconds: float = DEFAULT_MODEL_SECONDS, companion: bool = True) -> dict[str, Any]:
    """One value per ``REPORT_ROWS`` key (None: not built yet, or not reachable phone-only), plus ``also.*``.
    With ``companion``, the ``COMPANION_ROWS`` policies are run on the same seeds for their rows."""
    seeds = [int(s) for s in seeds]
    policies = [policy, *(companions(policy) if companion else [])]
    return fold([run(seed, sessions, p, voice_policy, model_seconds=model_seconds) for p in policies for seed in seeds])


# ---------------------------------------------------------------------------
# The latency probe's arithmetic (spec §20.2)
# ---------------------------------------------------------------------------

#: The ASSUMED texter throughput when no live probe has run (spec §20.2): 20 tokens a second,
#: prompt-eval weighted, for a 4B model on the owner's RTX 2060 -- a figure that folds the prompt's
#: evaluation into the reply's tokens, so a call's seconds are its reply tokens over it.
ASSUMED_TOKENS_PER_SECOND = 20.0


def latency_table(tokens_per_second: float = ASSUMED_TOKENS_PER_SECOND) -> dict[str, dict[str, Any]]:
    """
    Per voice mode, a reply's seconds at ``tokens_per_second`` (spec §20.2): p50 at half the mode's
    `max_tokens`, p95 at all of it, and p95 counting the starvation retry -- a second call within the
    same cap (`backend.chat`'s retry, T7 review M5), so twice the cap. The prompt's tokens do not enter:
    the rate is prompt-eval weighted, so the prompt's evaluation is already in it (the stub's prompt sizes
    are recorded apart, ``also.prompt_tokens.*``; T9 fix round 3, review M6).
    """
    from engine.social import voicing

    out: dict[str, dict[str, Any]] = {}
    for mode in ("quick", "chatting", "deep"):
        cap = int(voicing.mode_caps(mode)["max_tokens"])
        out[mode] = {"max_tokens": cap, "p50_s": round(cap / 2.0 / tokens_per_second, 1),
                     "p95_s": round(cap / tokens_per_second, 1),
                     "p95_with_retry_s": round(2 * cap / tokens_per_second, 1)}
    return out


# ---------------------------------------------------------------------------
# The command line
# ---------------------------------------------------------------------------


def render(key: str, rep: dict[str, Any], seeds: int, sessions: int) -> str:
    lines = [f"== {key} ({seeds} seeds x {sessions} sessions) =="]
    for row, value in rep.items():
        shown = "-" if value is None else value
        lines.append(f"  {row:<52} {shown}")
    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0].strip().splitlines()[0])
    parser.add_argument("--game", default=SLUG, help=f"the story to play; only {SLUG!r} has this harness")
    parser.add_argument("--sessions", type=int, default=6, help="phone-only sessions a run plays (40 real minutes each)")
    parser.add_argument("--seeds", type=int, default=10)
    parser.add_argument("--first-seed", type=int, default=0)
    parser.add_argument("--policy", choices=(*POLICIES, "all"), default="attentive")
    parser.add_argument("--voice", choices=(*VOICES, "all"), default=DEFAULT_VOICE,
                        help=f"the stub model's regard, or no_model (the fallback); default {DEFAULT_VOICE}")
    parser.add_argument("--model-seconds", type=float, default=DEFAULT_MODEL_SECONDS,
                        help="real seconds the model takes per reply (spec §3.4: 6, 15 or 30)")
    parser.add_argument("--no-companion", action="store_true",
                        help="do not run the companion policies (the flaky player) beside the report's own")
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
    if args.sessions < 1 or args.seeds < 1:
        parser.error("--sessions and --seeds must be at least 1")
    # `_main` quiets logging for the run; the caller's level comes back after it, as scripts/simulate.py
    # does: left disabled, every later caplog WARNING assertion in the process failed (v0.23.0 T20).
    quiet = logging.root.manager.disable
    try:
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
    finally:
        logging.disable(quiet)


def _main(args: argparse.Namespace) -> int:
    reports: dict[str, dict[str, Any]] = {}
    if args.fold:
        # Runs made side by side (each its own --first-seed range and --raw file), folded as one.
        raw: dict[str, list[dict[str, Any]]] = {}
        for name in args.fold:
            for key, runs in json.loads(Path(name).read_text(encoding="utf-8")).items():
                raw.setdefault(key, []).extend(runs)
        for key, runs in raw.items():
            runs.sort(key=lambda r: (r["policy"] != key.split("/", 1)[0], r["policy"], r["seed"]))
            reports[key] = fold(runs)
            seeds = len({r["seed"] for r in runs})
            print(render(key, reports[key], seeds, max(r["sessions"] for r in runs)), flush=True)
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
                key = f"{policy}/{voice}/{args.model_seconds:g}"
                ran = [policy, *([] if args.no_companion or args.policy == "all" else companions(policy))]
                runs = [run(seed, args.sessions, p, voice, model_seconds=args.model_seconds,
                            disk=Path(args.disk) / f"{p}-{voice}-{seed}" if args.disk else None)
                        for p in ran for seed in seeds]
                raw_runs[key] = runs
                reports[key] = fold(runs)
                print(render(key, reports[key], args.seeds, args.sessions), flush=True)
                print(f"  (wall time {time.perf_counter() - began:.0f} s)", flush=True)
        if args.raw:
            Path(args.raw).write_text(json.dumps(raw_runs, sort_keys=True), encoding="utf-8")
    if args.json:
        Path(args.json).write_text(json.dumps(reports, indent=2, sort_keys=True), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
