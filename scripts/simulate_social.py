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
world's two (T29): a world turn (``World.turn``: a walk to a room, an activity,
going out, waiting for someone) ``world`` 35, and a scene's move or closer
``moment`` 40 -- still spec §3.4's first estimates (T29 Step 1's pane
measurement has not replaced them; T31 re-checks all of them live).

  Calibration (T9, against v0.22.0 T30's measured cadence: an agent driving
  the pane did p95 32 and at most 36 actions a minute, its dedicated swipe
  minute 36 in 54 s): the harness's busiest real minute is a run of swipes
  at 4 s, 15 a minute, and a chat runs at most 2 actions a minute (a send of
  30 s and its reply), both under T30's p95 of 32 -- a person reads and
  types slower than an agent clicks, so the phone actions' first estimates
  stand (reported per run: ``also.actions_per_real_minute_max``). T29
  calibrates ``world`` and ``moment``; T31 re-checks all of them live.

A SESSION (``Session``) is ``SESSION_REAL_SECONDS`` (40 real minutes) of the
policy's actions from its waking hour: it looks at the phone and waits for more
(a wait is free) until the session's real seconds are spent or its bedtime
comes, then winds down -- says "talk later" in any conversation it was still
in, and keeps any promise of its own that opens before the morning. PHONE ONLY
(``world=False``, ``--phone-only``; T9's) it then "goes to bed" with ``wait
{until: morning}``. FULL (the default since T29 Step 2, v0.24.0 §13) the world
runs between its looks (``World.step``), each step a world turn through the
engine's own narrated turn (``default_scene.run_guarded``, narrated by
``StubNarration``, the phone put down first): a shift on a work day (from the
hall; each buzz that stops it, the policy looks, then carries on), the plans it
made or said yes to (to the place, "Wait for {name}", the evening's scene:
``ask_about`` at their depth, ``playful``, then its closer -- "Call it a night"
with a promise half the time, or, for the attentive and devoted players, back to
theirs or the flat and staying the night when offered), dinner, the four life
decks of v0.24.0 §12.2 (on a day one runs the policy walks once to its room and
takes the deck's first beat; any dealt card is answered with its first beat
wherever it is met), an evening with a partner who lives with it, and the way
home. The phone's waits go no further than an hour toward the world's next
step (``World.next_at``). A plan still due that evening is kept after the
session's time is spent; then the policy's bed: the bedroom and ``sleep`` from
20:00 (an earlier end passes the day on the phone's ``wait {until: morning}``).
A stay-over ends the session there: the next one opens on the morning scene,
where the policy takes one ``quiet`` and sees them out (the flat) or heads home
(theirs). The morning counts as no scene (v0.24.0 §12.1).

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
              them alone (spec §17.1); asks each long-term step (exclusive,
              moving in, marrying) as soon as their thread offers it, proposes
              in a scene when offered, and goes to the wedding.
  bachelor    Keeps 3-6 relationships going: writes first to no new match
              while six people are talking with it.
  flaky       The attentive player who breaks a third of its own promises
              (it does not write in their window) and stands up one plan in
              five (it never sets out for it).
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

The rows the world adds (T29; full sessions only, else ``None``):

  ratio.world           in-game minutes per real minute over the world turns
                        (derived)
  sessions_to_first_scene   per person who had one, the sessions from their
                        match's to their first scene's (median)
  real_hours_to_depth.<fast|slow>.<2|3|4>   per person, the run's real hours
                        (phone and world) from their match to that depth, by
                        pace tercile (median)
  scene_band.<band>     of the scenes that ended, the share by end band; the
                        morning after is no scene (v0.24.0 §12.1)
  life_events.player_per_week / .person_per_month_d2plus   the player's events
                        a week; a person's, started at depth 2 or more, per
                        month they were at depth 2 or more
  devoted.together_10h / .living_together_20h / .married_40h   of the devoted
                        runs, the share that reached the stage within those
                        real hours
  active_relationships_20h.<bachelor|attentive>   the people with an episode in
                        the 7 in-game days before 20 real hours (median)
  events_per_jump_morning_day60   the social events the night's sleep into
                        day 60 applied (the most of any run)
  life_decks_met_per_week   the four life decks met (their first beat taken)
                        a week: reported, unbanded (``UNBANDED_ROWS``)
  save_bytes_day180.*   ``write_day_save``'s, measured by the save-size test
                        (``None`` here)

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
    "life_decks_met_per_week",                                        # v0.24.0 §13 (T11): reported, unbanded
)
#: Rows that follow arithmetically from ``REAL_SECONDS``: reported, never banded (spec §3.4).
DERIVED_ROWS: frozenset[str] = frozenset({"ratio.chat", "ratio.world", "ratio.overall"})
#: Rows reported with no band to hold (v0.24.0 §13): how often the four life decks of v0.24.0 §12.2 are met
#: (their room walked to on a day they run and the first beat taken), per in-game week.
UNBANDED_ROWS: frozenset[str] = frozenset({"life_decks_met_per_week"})

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

# -- the world half of a full session (T29 Step 2; v0.24.0 §13) ---------------------------------------------

#: The four life decks met by walking to their room (v0.24.0 §12.2, §13): the policies `go` straight to
#: venues, so on a day one runs the policy walks once to its room, where the director deals it, and takes
#: the deck's first beat.
DECK_ROOMS: dict[str, str] = {"neighbour_party": "apt_hall", "lift_out": "bldg_lift", "family_visit": "apt_lounge",
                              "wedding_invite": "apt_hall"}
#: The policy cooks and eats once an evening from this hour, unless a plan is due soon.
DINNER_HOUR = 18.0
#: It sets out for a `now` / `tonight` plan this long before the plan is due (and waits there: "Wait for").
PLAN_LEAD_HOURS = 1.0
#: It skips its own dinner when a plan of the evening is due within this many hours (it eats out).
DINNER_PLAN_HOURS = 3.0
#: It goes to work this long before its work band starts ("Go to work" is offered earlier, from the hall).
WORK_LEAD_HOURS = 0.5
#: It asks someone to meet `tonight` before this hour, and `now` before WORK_NOW_BEFORE; later, not at all.
MEET_TONIGHT_BEFORE = 17.0
MEET_NOW_BEFORE = 21.0
#: A session that ends before this hour does not walk to bed: the rest of the day passes on the phone's
#: `wait {until: morning}`, as T9's sessions did (a nap at noon would wake the player at four).
BED_FROM_HOUR = 20.0
#: A sleep that ends before this hour, after the waking hour, woke the player into the next morning.
MORNING_ENDS = 12.0
#: Bounds on the world's loops (each step is a priced world turn, so none spins: these only cap a stuck run).
SCENE_STEPS_MAX = 24
WORK_STOPS_MAX = 60
SLEEP_STOPS_MAX = 6
#: The two moves a policy takes in an evening before its closer (T29 Step 2: `ask_about` at their depth,
#: then `playful`); the morning after takes one `quiet` (v0.24.0 §13).
DATE_MOVES: tuple[str, ...] = ("ask_about", "playful")
#: The closers that move an evening on to another place: a policy takes one at most once an evening, so the
#: evening never goes back and forth between the two homes.
MOVING_ON: frozenset[str] = frozenset({"back_to_yours", "back_to_theirs", "go_somewhere_else"})
MORNING_MOVE = "quiet"
#: The stages that count as "together" for `devoted.together_10h` (spec §17.2).
TOGETHER_STAGES: frozenset[str] = frozenset({"exclusive", "living_together", "engaged", "married"})
#: The real-hour marks of the long-term and active-relationship rows (spec §17.2).
TOGETHER_REAL_HOURS = 10.0
LIVING_REAL_HOURS = 20.0
MARRIED_REAL_HOURS = 40.0
ACTIVE_REAL_HOURS = 20.0
#: "Active": an episode with them in the last this-many in-game days before the mark (spec §17.2).
ACTIVE_DAYS = 7.0
#: The in-game day the jump-to-morning event count is taken at (spec §17.2).
JUMP_DAY = 60
#: The depths `real_hours_to_depth.*` reports (spec §17.2).
DEPTH_ROWS: tuple[int, ...] = (2, 3, 4)
#: A scene's end bands, best first (scenes.yaml `end_bands` and below).
SCENE_BANDS: tuple[str, ...] = ("great", "good", "fine", "awkward", "bad")

#: The narration the harness's storyteller writes for a world turn (no model is ever called).
_NARRATION = ("The day goes on around you in its ordinary way: the light shifting on the walls, the street "
              "carrying on below, the small sounds of the building settling. Nothing asks anything of you for "
              "a moment, and you take it as it comes.")


class StubNarration:
    """
    The world turn's storyteller, with no model (T29 Step 2; the tests' ``StubNarrator`` shape): for a
    Storyteller call, a turn valid under the live grammar -- the narration above and the first three legal
    verbs as choices, each with an intent on its first target; any other agent's call gets a short line.
    The policy does not pick from these choices: it hands the turn its own intent, which the engine
    re-checks against what is legal now (``tool_dispatcher.execute_intent``), as every choice is.
    """

    def __init__(self) -> None:
        self.calls = 0
        #: The run's state (``Phone`` sets it): the turn's verbs are read off it.
        self.state: Any = None

    def __call__(self, messages: list[dict[str, Any]], **_: Any) -> str:
        from engine.agents.prompts import storyteller_persona

        persona = storyteller_persona().strip().splitlines()[0]
        if not any(persona in str(m.get("content", "")) for m in messages):
            return "Nothing is said, at length."
        self.calls += 1
        return json.dumps(self.turn())

    def turn(self) -> dict[str, Any]:
        from engine.game.intents import legal_intents

        state = self.state
        if state is None:
            from engine.game.engine import get_active_engine

            state = get_active_engine().state
        verbs = legal_intents(state)
        choices: list[dict[str, Any]] = []
        for verb in verbs:
            if len(choices) == 3:
                break
            if verb.extra:
                continue
            row: dict[str, Any] = {"id": "abcd"[len(choices)], "text": f"{verb.action} {len(choices)}"[:100]}
            if verb.targets:
                row["text"] = verb.label_for(verb.targets[0])[:100]
                row["intent"] = {"action": verb.action, "target": verb.targets[0]}
            else:
                row["intent"] = {"action": verb.action}
            choices.append(row)
        while len(choices) < 2:
            choices.append({"id": "abcd"[len(choices)], "text": "Stay where you are"})
        return {"narration": _NARRATION, "choices": choices}


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

    def append_transcript(self, save_id: str, record: dict[str, Any]) -> None:
        """A world turn's narration line (``default_state._autosave``): kept nowhere."""


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
    the pass deadline pinned past reach (``PASS_DEADLINE_SECONDS``), and no
    model server (profiles resolve offline; no backend is built); all
    restored after.
    """
    from engine.llm import backend, profiles
    from engine.social import voicer

    before = voicer._summary_fn
    deadline = voicer._deadline_seconds
    bind, get_backend = profiles._bind, backend.get_backend
    voicer.set_summary_fn(lambda messages: "")
    voicer._deadline_seconds = lambda: PASS_DEADLINE_SECONDS   # type: ignore[assignment]
    # No model server, ever (T29: a world turn reads the narration budget off the bound model, which asks the
    # server what is loaded): every profile resolves as the engine does offline, from config, and anything
    # that would build a backend to talk to one is refused here, before it connects.
    profiles._bind = lambda profile, settings: None             # type: ignore[assignment]
    backend.get_backend = _no_backend                          # type: ignore[assignment]
    profiles._cache.clear()
    try:
        yield
    finally:
        profiles._cache.clear()
        profiles._bind, backend.get_backend = bind, get_backend  # type: ignore[assignment]
        voicer._deadline_seconds = deadline                    # type: ignore[assignment]
        voicer.set_summary_fn(before)


def _no_backend(*_: Any, **__: Any) -> Any:
    raise RuntimeError("simulate_social: a harness run reaches no model server (its voices and narrator are stubs)")


@contextmanager
def _scheduler_paused() -> Iterator[None]:
    """
    The voicing scheduler paused for the run (a world turn requests a pass, `voicer.request(now=True)`, as the
    route does): the harness voices on its own thread after every action (``Phone.voice``), so no background
    pass ever races it. Resumed after only if it was running before.
    """
    from engine.social import voicer

    scheduler = voicer.get_scheduler()
    was = bool(getattr(scheduler, "_paused", False))
    scheduler.pause()
    try:
        yield
    finally:
        if not was:
            scheduler.resume()


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
        #: The world turn's storyteller (``StubNarration``): the phone's actions never call it.
        self.narrator = StubNarration()
        self.session = self.store.create(seed=seed, player_name="Sam", llm_fn=self.narrator)
        self.state = self.session.engine.state
        self.narrator.state = self.state
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
        #: Every priced world turn (``World.turn``): (in-game hour after it, real seconds, in-game minutes,
        #: kind -- ``world`` or ``moment``). Kept apart from ``charges``, whose rows are the phone's chat.
        self.world_charges: list[tuple[float, float, float, str]] = []
        self.world_actions = 0
        self.world_refused = 0
        #: The social events applied by the sleep that jumps to the morning of day ``JUMP_DAY`` (``World.bed``).
        self.jump_events: Optional[int] = None
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
    # -- the world (full sessions only: ``in_world``, set by ``Session(world=True)``) --
    #: It asks people to meet (`ask {what: meet}`) and keeps its plans.
    meets = True
    #: It asks them back to its flat or goes back to theirs, and to stay the night, when offered (v0.24.0 §13:
    #: the devoted and attentive players reach the morning after).
    stays = False
    #: The share of its plans it stands up (never goes to), spec §17.1's flaky player.
    stand_up_share = 0.0

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
        #: A full session's world (``Session(world=True)`` sets it): the asks to meet and the long-term asks
        #: are made only then, so a phone-only run is T9's.
        self.in_world = False
        self.meet_asked: dict[str, float] = {}
        self.long_asked: dict[str, float] = {}
        #: Its world driver, kept across the run's sessions (``Session`` makes it).
        self.world: Optional["World"] = None

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
        if self.in_world:
            self.asks_to_meet()
            self.asks_long_term()

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

    # -- the world's asks (full sessions) ---------------------------------------

    def _evening_plan_open(self) -> bool:
        from engine.social import plans

        return any(r.get("when") != "soon" and r.get("kind") != plans.WEDDING for r in plans.open_for(self.phone.state))

    def asks_to_meet(self) -> None:
        """
        One ask to meet a look (`ask {what: meet}`, the engine picking the place by shared hobbies), to someone
        the band shows warming or closer whose thread offers it now (`messaging.ready_asks`), at most every
        ``ask_every_days`` a person, and only while it has no evening plan open: `tonight` before
        ``MEET_TONIGHT_BEFORE``, `now` before ``MEET_NOW_BEFORE``. They decide at their read.
        """
        from engine.social import messaging, relationships

        if not self.meets or self._evening_plan_open():
            return
        hour = self.phone.now % 24
        when = "tonight" if hour < MEET_TONIGHT_BEFORE else ("now" if hour < MEET_NOW_BEFORE else "")
        if not when:
            return
        for t in sorted((self.social.get("threads") or {}).values(), key=lambda t: str(t["thread_id"])):
            if self.over():
                return
            pid = str(t["pid"])
            person = self._person(pid)
            if not self._allowed(pid) or person.get("ghosted") or self._avoids(pid):
                continue
            if relationships.band(person) in ("", "new"):
                continue
            if self.phone.now - self.meet_asked.get(pid, -1e9) < self.ask_every_days * 24:
                continue
            if messaging.MEET_ASK not in messaging.ready_asks(self.phone.state, t):
                continue
            self.meet_asked[pid] = self.phone.now
            self.phone.act("ask", str(t["thread_id"]), {"what": messaging.MEET_ASK, "when": when})
            return

    def asks_long_term(self) -> None:
        """The devoted player asks each long-term step (`exclusive`, `move_in`, `propose`) of the one it is devoted
        to as soon as its thread offers it (spec §17.1: once the stage's gate holds), at most every
        ``ask_every_days`` a step."""
        from engine.social import messaging

        if not self.devoted or not self.focus:
            return
        tid = messaging.thread_for(self.phone.state, self.focus)
        t = messaging.thread(self.phone.state, tid) if tid else None
        if t is None:
            return
        ready = messaging.ready_asks(self.phone.state, t)
        for what in ("exclusive", "move_in", "propose"):
            if self.over():
                return
            if what not in ready or self.phone.now - self.long_asked.get(what, -1e9) < self.ask_every_days * 24:
                continue
            if any(r.get("pid") == self.focus and r.get("what") == what and r.get("status") in ("pending", "later")
                   for r in (self.social.get("requests") or {}).values()):
                continue
            self.long_asked[what] = self.phone.now
            self.phone.act("ask", str(tid), {"what": what})
            return

    def stands_up(self, plan_id: str) -> bool:
        """It means to stand this plan up (spec §17.1: the flaky player, one in five)."""
        return self.stand_up_share > 0 and self._wants(f"stand_up:{plan_id}", self.stand_up_share)

    def scene_choice(self, scn: dict[str, Any], moves_taken: int, moves: list[str],
                     closers: list[str]) -> tuple[str, str]:
        """
        Its next step in a scene, as (action, target): the morning after takes one `quiet` and then sees them
        out (at the flat) or heads home (at theirs) (v0.24.0 §13); the wedding, which has no closer, takes its
        moments; any other scene takes ``DATE_MOVES`` -- `ask_about` at their depth (the first offered: their
        rung first), then `playful` -- then its closer (``closer``). ("", "") when nothing is offered.
        """
        kind = str(scn.get("kind") or "")
        if kind == "morning":
            if moves_taken == 0 and MORNING_MOVE in moves:
                return "scene", MORNING_MOVE
            for name in ("see_them_out", "call_it_a_night"):
                if name in closers:
                    return "close", name
        elif closers and moves_taken < len(DATE_MOVES):
            want = DATE_MOVES[moves_taken]
            pick = next((m for m in moves if m == want or m.startswith(f"{want}:")), "")
            if pick:
                return "scene", pick
        if closers:
            return "close", self.closer(scn, closers)
        order = ("quiet", "playful", "talk")                     # the wedding: its moments, in this order
        pick = next((m for m in order if m in moves), moves[0] if moves else "")
        return ("scene", pick) if pick else ("", "")

    def closer(self, scn: dict[str, Any], closers: list[str]) -> str:
        """How it ends an evening: the devoted player proposes when offered (the evening goes on); a player who
        ``stays`` asks them to stay the night, else back to its flat or theirs; else "Call it a night", with a
        promise to text in the morning half the time (T29 Step 2) when it makes promises."""
        if self.devoted and "propose" in closers:
            return "propose"
        if self.stays:
            for name in ("stay_the_night", "back_to_yours", "back_to_theirs"):
                if name in closers:
                    return name
        from engine.social import scene as social_scene

        promise = f"call_it_a_night:promise:{social_scene.PROMISE_WINDOW}"
        if (self.promises and promise in closers
                and self._wants(f"promise:{scn.get('pid')}:{scn.get('started_at')}", 0.5)):
            return promise
        return "call_it_a_night" if "call_it_a_night" in closers else closers[0]

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

    def wait_for_more(self, stop_at: Optional[float] = None) -> bool:
        """Live: until the phone buzzes, or one of its own promises opens if that is sooner; else an hour.
        False, waiting nothing, when nothing comes before its bedtime: the session's day is over. ``stop_at``
        (a full session's next world step, ``World.next_at``): the wait goes no further than an hour toward it,
        and waits nothing once it is due; None is T9's wait, unchanged."""
        from engine.social import turn

        phone = self.phone
        if stop_at is not None and stop_at <= phone.now + 1e-9:
            return True                                    # the world is due now: the session's loop does it
        if self.looks != "live":
            if phone.now + 1.0 >= self._bedtime() and (stop_at is None or stop_at >= self._bedtime()):
                return False
            phone.act("wait", args={"until": "1h"})
            return True
        due = turn._next_notifying_at(phone.state)
        soonest = min((t for t in (due, stop_at) if t is not None), default=None)
        mine = self._next_own_promise(soonest if soonest is not None else self._bedtime())
        if mine is not None:
            phone.act("wait", args={"until": f"{turn.PROMISE_TARGET}{mine['id']}"})
            return True
        if stop_at is not None and (due is None or stop_at < due) and stop_at < self._bedtime():
            phone.act("wait", args={"until": "1h"})          # toward the world's next step, an hour at a time
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
    stays = True


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
    meets = False


class Pushy(Policy):
    name = "pushy"
    sends_per_reply = 2
    asks = "always"


class Devoted(Policy):
    name = "devoted"
    devoted = True
    stays = True


class Bachelor(Policy):
    name = "bachelor"
    max_live = 6


class Flaky(Policy):
    name = "flaky"
    break_share = 1.0 / 3.0
    stand_up_share = 0.2


class Chatty(Policy):
    name = "chatty"
    texts = CHATTY_TEXTS


POLICIES: dict[str, type[Policy]] = {p.name: p for p in (Attentive, Swiper, Picky, Slow, Neglectful, Pushy,
                                                        Devoted, Bachelor, Flaky, Chatty)}


# ---------------------------------------------------------------------------
# The world (T29 Step 2; v0.24.0 §13): what a full session does with the phone down
# ---------------------------------------------------------------------------


def _day_of(hours: float) -> int:
    """The in-game day an hour falls on, as ``GameState.world_day`` counts it (1-based)."""
    return 1 + int(float(hours) // 24)


class World:
    """
    The world half of a full session, one run's (``Session(world=True)``). Every step is a WORLD TURN
    (``turn``): the phone put down (``put_down``, a phone action), then the engine's own narrated turn
    (``default_scene.run_guarded``, the route's call, narrated by ``StubNarration``) with the policy's intent,
    re-checked by the engine against what is legal now -- so legality, the travel, the plans' arrivals, the
    director's decks and every draw are the engine's. Each is priced ``REAL_SECONDS["world"]``, or
    ``["moment"]`` for a scene's move or closer, on the session's clock (``Phone.world_charges``).

    ``step`` does at most one thing due now, in this order: an open scene (``scene``), a shift in progress
    (``work_on``), the wedding, a plan to keep, going to work, one of the four life decks (``deck``), dinner,
    an evening with the household partner, and the way home from a place the policy has no reason to be.
    A dealt card owns the turn wherever it is met (``_cards``): the policy takes its first beat.
    """

    def __init__(self, phone: Phone, policy: Policy) -> None:
        self.phone = phone
        self.policy = policy
        self.worked = -1
        self.dined = -1
        self.home_evening = -1
        #: (deck, in-game day) the policy has walked to; plans it has set out for, or stood up.
        self.decks_tried: set[tuple[str, int]] = set()
        self.plans_done: set[str] = set()
        #: A stay-over this session: the night is over and the morning scene waits for the next session.
        self.stayed = False
        self.counts: dict[str, Any] = {"work_days": 0, "dinners": 0, "at_home": 0, "stay_overs": 0,
                                       "stood_up_by_player": 0, "decks": {}}

    @property
    def state(self) -> Any:
        return self.phone.state

    @property
    def day(self) -> int:
        return int(self.state.world_day)

    def legal(self) -> dict[str, list[str]]:
        """Every world verb legal now -> its targets (``intents.legal_intents``, the engine's catalogue)."""
        from engine.game.intents import legal_intents

        return {v.action: [str(t) for t in v.targets] for v in legal_intents(self.state)}

    # -- one world turn ---------------------------------------------------------------------------------

    def turn(self, action: str = "", target: str = "", *, price: str = "world") -> dict[str, Any]:
        """One world turn with this intent (none: a look), then any dealt card's first beat. Its receipt."""
        receipt = self._run(action, target, price)
        self._cards()
        return receipt

    def _run(self, action: str, target: str, price: str) -> dict[str, Any]:
        from engine import social
        from engine.game import intents as game_intents
        from engine.scenes.default_scene import run_guarded

        phone = self.phone
        state = self.state
        if state.social.get("phone_up"):
            phone.act("put_down")
            if social.scene_open(state) and action not in ("scene", "close"):
                return {}                                   # someone arrived as the phone went down: the scene first
        intent = {"action": action, "target": target} if action else None
        words = (game_intents.player_label(state, action, target) or target) if action else "Look around"
        began = phone.now
        payload, error, _busy = run_guarded(phone.session, f"The player chooses: {words}", intent)
        if payload is None:
            raise RuntimeError(f"simulate_social: a world turn failed ({action or 'look'} {target}): {error}")
        phone.voice()
        phone.spill()
        phone._rebuild({})
        receipts = payload.get("tool_receipts") or []
        receipt = next((r for r in receipts if (r.get("intent") or {}).get("action") == action), {}) if action else {}
        phone.world_actions += 1
        if receipt.get("refused"):
            phone.world_refused += 1
            reason = str((receipt.get("result") or {}).get("error") or "")
            key = f"world {action}: {phone._unnamed(reason, '')}"
            phone.refusals[key] = phone.refusals.get(key, 0) + 1
        if phone.clock is not None:
            seconds = REAL_SECONDS[price]
            phone.clock.spent += seconds
            phone.world_charges.append((phone.now, seconds, (phone.now - began) * 60.0, price))
        for observe in phone.observers:
            observe(phone)
        return receipt

    def _cards(self) -> None:
        """A dealt card owns the turn (a life deck where the policy stands): its first beat, until none is dealt."""
        for _ in range(4):
            targets = self.legal().get("card") or []
            if not targets:
                return
            deck = str((self.state.scene or {}).get("deck_id") or "")
            self._run("card", targets[0], "world")
            decks = self.counts["decks"]
            decks[deck] = decks.get(deck, 0) + 1

    # -- getting about ------------------------------------------------------------------------------------

    @staticmethod
    def _path(here: str, to: str) -> list[str]:
        """The rooms from ``here`` to ``to`` through the flat and building's edges (breadth first), ``to`` last."""
        from engine.game.locations import LOCATIONS

        seen = {here: ""}
        frontier = [here]
        while frontier:
            nxt: list[str] = []
            for room in frontier:
                for edge in sorted(((LOCATIONS.get(room) or {}).get("connections") or {})):
                    if edge in seen:
                        continue
                    seen[edge] = room
                    if edge == to:
                        path = [edge]
                        while seen[path[-1]] != here:
                            path.append(seen[path[-1]])
                        return list(reversed(path))
                    nxt.append(edge)
            frontier = nxt
        return []

    def walk_to(self, room: str) -> bool:
        """To ``room`` in the flat or building: "Head home" first from outside, then one `travel` a room."""
        from engine import social
        from engine.social import places, world

        for _ in range(12):
            here = str(self.state.location_id or "")
            if here == room:
                return True
            if social.scene_open(self.state) or self.state.social.get("at_work"):
                return False
            legal = self.legal()
            if not places.is_flat(here):
                if world.HOME not in legal.get("go", []):
                    return False
                self.turn("go", world.HOME)
                continue
            path = self._path(here, room)
            if not path or path[0] not in legal.get("travel", []):
                return False
            self.turn("travel", path[0])
        return str(self.state.location_id or "") == room

    # -- the steps --------------------------------------------------------------------------------------------

    def step(self) -> bool:
        """At most one world thing due now, done (see the class docstring). True when one was."""
        from engine import social

        if social.scene_open(self.state):
            self.scene()
            return True
        if self.state.social.get("at_work"):
            self.work_on()
            return True
        for one in (self.wedding, self.plan, self.work, self.deck, self.dinner, self.at_home, self.head_home):
            if one():
                return True
        return False

    def next_at(self) -> Optional[float]:
        """When the next world step falls due (an in-game hour), for the phone's wait (``wait_for_more``)."""
        now = self.phone.now
        times = [self._leave_at(r) for r in self._evening_plans()]
        band = self._work_band()
        if band is not None and self.worked != self.day and _day_of(band[0]) == self.day:
            times.append(band[0] - WORK_LEAD_HOURS)
        if self.dined != self.day and now % 24 < DINNER_HOUR:
            times.append(now - now % 24 + DINNER_HOUR)
        return min(times) if times else None

    def _work_band(self) -> Optional[tuple[float, float]]:
        from engine.social import world

        band = world._player_work_band(self.state, self.phone.now)
        return (float(band[0]), float(band[1])) if band else None

    def _evening_plans(self) -> list[dict[str, Any]]:
        """The open `now` / `tonight` plans it has not yet set out for, soonest due first."""
        from engine.social import plans

        rows = [r for r in plans.open_for(self.state) if r.get("when") != "soon" and r.get("kind") != plans.WEDDING
                and str(r["id"]) not in self.plans_done and r.get("due_at") is not None]
        return sorted(rows, key=lambda r: (float(r["due_at"]), str(r["id"])))

    @staticmethod
    def _leave_at(row: dict[str, Any]) -> float:
        return float(row["due_at"]) - PLAN_LEAD_HOURS

    def plan(self) -> bool:
        """A plan due: it goes to the plan's place (a `your_place` plan waits in the lounge), waits for them if
        they are on their way ("Wait for {name}"), and spends the evening (``scene``); a flaky player stands one
        in five up. Then home, if nothing is going on where it is."""
        from engine import social
        from engine.social import plans, places

        now = self.phone.now
        due = [r for r in self._evening_plans() if now >= self._leave_at(r) - 1e-9]
        if not due:
            return False
        row = due[0]
        plan_id = str(row["id"])
        self.plans_done.add(plan_id)
        if self.policy.stands_up(plan_id):
            self.counts["stood_up_by_player"] += 1
            return True
        if plans.arrives_at(row) + float(row.get("patience_hours") or 0.0) < now:
            return True                                       # long gone: nothing to go to
        place = plans.place_of(self.state, row)
        if row.get("kind") == "your_place":
            self.walk_to("apt_lounge")
        elif str(self.state.location_id or "") != place:
            if place not in self.legal().get("go", []):
                self.walk_to("apt_lounge")                    # from a place that offers only the way home
            if place in self.legal().get("go", []):
                self.turn("go", place)
        for _ in range(3):
            if social.scene_open(self.state):
                self.scene()
                break
            wait = f"plan:{plan_id}"
            if wait not in self.legal().get("scene", []):
                break
            self.turn("scene", wait)
        if not social.scene_open(self.state) and not self.stayed and not places.is_flat(str(self.state.location_id)):
            self.head_home()
        return True

    def wedding(self) -> bool:
        """An open wedding (life_events.yaml's `wedding`, for an engaged couple): to the registry office."""
        from engine import social
        from engine.social import plans

        rows = [r for r in plans.open_for(self.state) if r.get("kind") == plans.WEDDING
                and f"{r['id']}@{self.day}" not in self.plans_done]
        if not rows:
            return False
        row = rows[0]
        self.plans_done.add(f"{row['id']}@{self.day}")
        place = plans.place_of(self.state, row)
        if place not in self.legal().get("go", []):
            self.walk_to("apt_lounge")
        if place in self.legal().get("go", []):
            self.turn("go", place)
        if social.scene_open(self.state):
            self.scene()
        self.head_home()
        return True

    def work(self) -> bool:
        """A work day: from the hall, "Go to work" (interruptible), once a day, from ``WORK_LEAD_HOURS`` before
        its band; then ``work_on``."""
        band = self._work_band()
        if self.worked == self.day or band is None or _day_of(band[0]) != self.day:
            return False
        if self.phone.now < band[0] - WORK_LEAD_HOURS - 1e-9:
            return False
        self.worked = self.day
        if self.phone.now >= band[1] or not self.walk_to("apt_hall"):
            return True
        if "go_to_work" not in self.legal().get("do", []):
            return True
        self.counts["work_days"] += 1
        self.turn("do", "go_to_work")
        self.work_on()
        return True

    def work_on(self) -> None:
        """At work: each buzz that stops the shift, the policy picks the phone up and looks (unless its session's
        time is spent), then carries on (`carry_on_working`), until the shift is over."""
        for _ in range(WORK_STOPS_MAX):
            if not self.state.social.get("at_work"):
                return
            if not self.policy.over():
                self.policy.look()
            if not self.state.social.get("at_work") or "carry_on_working" not in self.legal().get("do", []):
                return
            self.turn("do", "carry_on_working")

    def deck(self) -> bool:
        """One of the four life decks running today (its flag): the policy walks once to its room; the director
        deals it there and the policy takes its first beat (``_cards``); a look deals it if the walk did not."""
        for deck, room in DECK_ROOMS.items():
            key = (deck, self.day)
            if not self.state.flags.get(f"life_{deck}") or key in self.decks_tried:
                continue
            self.decks_tried.add(key)
            if self.walk_to(room) and self.state.flags.get(f"life_{deck}"):
                self.turn()
            return True
        return False

    def dinner(self) -> bool:
        """Once an evening from ``DINNER_HOUR``: to the kitchen, "Make dinner", "Eat" -- unless a plan is due
        within ``DINNER_PLAN_HOURS`` (it eats out)."""
        hour = self.phone.now % 24
        if self.dined == self.day or not DINNER_HOUR <= hour < HOUR_BED - 1:
            return False
        self.dined = self.day
        if any(float(r["due_at"]) - self.phone.now < DINNER_PLAN_HOURS for r in self._evening_plans()):
            return False
        if not self.walk_to("apt_kitchen"):
            return True
        for activity in ("make_dinner", "eat"):
            if activity in self.legal().get("do", []):
                self.turn("do", activity)
        self.counts["dinners"] += 1
        return True

    def at_home(self) -> bool:
        """An evening with the household partner, home and free (a player who ``stays``), once an evening."""
        from engine.social import scene as social_scene

        if not self.policy.stays or self.home_evening == self.day or self.phone.now % 24 < DINNER_HOUR:
            return False
        target = next((t for t in self.legal().get("scene", []) if t.startswith(f"{social_scene.AT_HOME_TARGET}:")), "")
        if not target:
            return False
        self.home_evening = self.day
        self.counts["at_home"] += 1
        self.turn("scene", target)
        self.scene()
        return True

    def head_home(self) -> bool:
        """Outside the flat with nothing to wait for there: "Head home"."""
        from engine import social
        from engine.social import places, plans, world

        here = str(self.state.location_id or "")
        if places.is_flat(here) or social.scene_open(self.state) or plans.waiting_here(self.state):
            return False
        if world.HOME not in self.legal().get("go", []):
            return False
        self.turn("go", world.HOME)
        return True

    def scene(self) -> None:
        """While a scene is open: the policy's moves and closer (``Policy.scene_choice``), each a priced moment.
        A stay-over ends the session (``stayed``): the morning scene opens at the player's morning and is the
        next session's first step."""
        from engine.social import scene as social_scene

        taken: dict[str, int] = {}
        moved_on = False                          # the evening has gone on somewhere once (back to yours or theirs)
        for _ in range(SCENE_STEPS_MAX):
            scn = social_scene.current(self.state)
            if not scn.get("pid"):
                return
            key = f"{scn['pid']}@{scn.get('started_at')}"
            legal = self.legal()
            closers = [c for c in legal.get("close") or []
                       if not (moved_on and c.split(":")[0] in MOVING_ON)]
            action, target = self.policy.scene_choice(scn, taken.get(key, 0), legal.get("scene") or [], closers)
            moved_on = moved_on or (action == "close" and target.split(":")[0] in MOVING_ON)
            if not action:
                return
            self.turn(action, target, price="moment")
            if action == "scene":
                taken[key] = taken.get(key, 0) + 1
            after = social_scene.current(self.state)
            if target == "stay_the_night" and after.get("kind") == social_scene.MORNING:
                self.stayed = True
                self.counts["stay_overs"] += 1
                return

    # -- the session's end ---------------------------------------------------------------------------------

    def keep_tonight(self) -> None:
        """The session's time is spent, but a plan of this evening is still to come: the phone waits toward it
        (free) and the policy keeps it, as a player with a date would."""
        bedtime = self.phone.now - self.phone.now % 24 + HOUR_BED
        for _ in range(24):
            rows = [r for r in self._evening_plans() if self._leave_at(r) < bedtime]
            if not rows or self.stayed:
                return
            if self.phone.now >= self._leave_at(rows[0]) - 1e-9:
                self.plan()
                continue
            self.phone.act("wait", args={"until": "1h"})

    def bed(self) -> None:
        """The policy's bed: a shift still going is finished; from ``BED_FROM_HOUR`` it walks to the bedroom and
        sleeps (`sleep`, again if a wake stopped it); then, if the morning has not come (an early end, or no bed
        to reach), the phone's `wait {until: morning}`. The sleep into day ``JUMP_DAY`` counts its events."""
        from engine import social
        from engine.social import events

        self.work_on()
        if social.scene_open(self.state):
            self.scene()
        if self.stayed:
            return
        went_to_bed = self.phone.now
        hour = self.phone.now % 24
        if (hour >= BED_FROM_HOUR or hour < HOUR_WAKE) and self.walk_to("apt_bedroom"):
            counting = self.day + (1 if hour >= HOUR_WAKE else 0) >= JUMP_DAY and self.phone.jump_events is None
            real = events.advance
            applied = [0]

            def advance(state: Any, from_hours: float, to_hours: float) -> list[dict[str, Any]]:
                out = real(state, from_hours, to_hours)
                applied[0] += len(out)
                return out

            events.advance = advance              # type: ignore[assignment]
            try:
                for _ in range(SLEEP_STOPS_MAX):
                    if "sleep" not in self.legal().get("do", []):
                        break
                    done = self.turn("do", "sleep")
                    if not (done.get("result") or {}).get("stopped") or social.scene_open(self.state):
                        break
            finally:
                events.advance = real             # type: ignore[assignment]
            if counting and self.day >= JUMP_DAY:
                self.phone.jump_events = applied[0]
            if social.scene_open(self.state):
                self.scene()
        woke = self.phone.now > went_to_bed + 1.0 and HOUR_WAKE - 1e-6 <= self.phone.now % 24 < MORNING_ENDS
        if not woke and not self.stayed:
            self.phone.act("wait", args={"until": "morning"})


# ---------------------------------------------------------------------------
# A session (T9: phone only; T29: full)
# ---------------------------------------------------------------------------


class Session:
    """
    One session (spec §3.4). PHONE ONLY (``world=False``, T9's): the policy looks and waits for more until
    ``real_seconds_budget`` real seconds are spent (``RealClock``) or its bedtime comes, winds down, and goes to
    bed (``wait {until: morning}``). FULL (``world=True``, the default since T29): the same phone, with the
    world between its looks (``World.step``: work, the plans and their scenes, the life decks, dinner), the
    phone's waits going no further than the world's next step, and the policy's bed (``World.bed``); a session
    that wakes to a morning scene (a stay-over) takes it first, and one that ends in a stay-over ends there.
    ``play`` returns the session's span.
    """

    def __init__(self, phone: Phone, policy: Policy, *, model_seconds: float = DEFAULT_MODEL_SECONDS,
                 real_seconds_budget: float = SESSION_REAL_SECONDS, world: bool = True) -> None:
        self.phone = phone
        self.policy = policy
        self.model_seconds = float(model_seconds)
        self.real_seconds_budget = float(real_seconds_budget)
        self.world = bool(world)

    def play(self) -> dict[str, Any]:
        if not self.world:
            return self._play_phone()
        return self._play_full()

    def _look(self) -> None:
        phone, policy = self.phone, self.policy
        hour = int(phone.now % 24)
        if policy.looks == "live" or (hour in policy.looks
                                      and getattr(policy, "_looked", None) != (phone.state.world_day, hour)):
            policy._looked = (phone.state.world_day, hour)
            policy.look()

    def _play_phone(self) -> dict[str, Any]:
        phone, policy = self.phone, self.policy
        if not policy.awake():
            phone.act("wait", args={"until": "morning"})
        clock = RealClock(self.model_seconds, budget=self.real_seconds_budget)
        phone.clock = policy.clock = clock
        start = phone.now
        try:
            while policy.awake() and not clock.over:
                before = (phone.now, clock.spent)
                self._look()
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

    def _play_full(self) -> dict[str, Any]:
        from engine import social

        with _scheduler_paused():
            return self._play_world()

    def _play_world(self) -> dict[str, Any]:
        from engine import social

        phone, policy = self.phone, self.policy
        policy.in_world = True
        world = policy.world
        if world is None:
            world = policy.world = World(phone, policy)
        world.stayed = False
        if not policy.awake() and not social.scene_open(phone.state):
            phone.act("wait", args={"until": "morning"})
        clock = RealClock(self.model_seconds, budget=self.real_seconds_budget)
        phone.clock = policy.clock = clock
        start = phone.now
        try:
            while not world.stayed and (policy.awake() or social.scene_open(phone.state)) and not clock.over:
                before = (phone.now, clock.spent)
                if world.step() and (phone.now, clock.spent) != before:
                    continue
                if world.stayed:
                    break
                self._look()
                if clock.over or not policy.awake():
                    break
                if not policy.wait_for_more(world.next_at()):
                    break
                if (phone.now, clock.spent) == before:
                    phone.act("wait", args={"until": "1h"})
            if not world.stayed and not social.scene_open(phone.state):
                policy.wind_down()
                world.keep_tonight()
            end = phone.now
            if not world.stayed:
                world.bed()
        finally:
            phone.clock = policy.clock = None
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
        #: The world (T29): each scene as it ends (who, its kind, its band, when it opened and ended, why),
        #: each life event as it starts (whose, which, when, their depth then), each plan as it is made and
        #: closed.
        self.scene_opened: dict[str, float] = {}
        self.scenes: list[dict[str, Any]] = []
        self.life: list[dict[str, Any]] = []
        self.plans_made: list[dict[str, Any]] = []
        self.plans_closed: list[str] = []


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
        with _recording_world(rec):
            yield
    finally:
        for name, fn in real.items():
            setattr(convo, name, fn)


@contextmanager
def _recording_world(rec: Recorder) -> Iterator[None]:
    """`scene._open` / `_end`, `life._start` and `plans._make` / `_close_row` wrapped for ``rec`` (each is called
    by its effect handler by name, so the wrapper sees every one), restored after."""
    from engine.social import growth, life, plans, scene

    real = {"scene._open": scene._open, "scene._end": scene._end, "life._start": life._start,
            "plans._make": plans._make, "plans._close_row": plans._close_row}

    def scene_open(state, effect, at):
        out = real["scene._open"](state, effect, at)
        if out.get("ok"):
            scn = state.social.get("scene") or {}
            rec.scene_opened[f"{scn.get('pid')}@{scn.get('started_at')}"] = float(at)
        return out

    def scene_end(state, scn, effect, at):
        key = f"{scn.get('pid')}@{scn.get('started_at')}"
        out = real["scene._end"](state, scn, effect, at)
        if out.get("ok"):
            rec.scenes.append({"pid": str(scn.get("pid") or ""), "kind": str(scn.get("kind") or ""),
                               "band": str(out.get("band") or ""), "opened_at": rec.scene_opened.get(key, float(at)),
                               "at": float(at), "reason": str(out.get("reason") or ""),
                               "moments": int(scn.get("count", 0))})
        return out

    def life_start(state, who, event_id, at):
        out = real["life._start"](state, who, event_id, at)
        if out.get("ok", True):
            rec.life.append({"who": "player" if who == "player" else "person", "pid": "" if who == "player" else who,
                             "id": event_id, "at": float(at),
                             "depth": 0 if who == "player" else growth.depth(state, who)})
        return out

    def plan_make(state, effect, at):
        out = real["plans._make"](state, effect, at)
        if out.get("ok"):
            row = out.get("plan") or {}
            rec.plans_made.append({"when": str(row.get("when") or ""), "kind": str(row.get("kind") or ""),
                                   "by": str(effect.get("by") or ""), "at": float(at)})
        return out

    def plan_close(row, status, at):
        rec.plans_closed.append(str(status))
        return real["plans._close_row"](row, status, at)

    scene._open, scene._end, life._start = scene_open, scene_end, life_start
    plans._make, plans._close_row = plan_make, plan_close
    try:
        yield
    finally:
        scene._open, scene._end, life._start = real["scene._open"], real["scene._end"], real["life._start"]
        plans._make, plans._close_row = real["plans._make"], real["plans._close_row"]


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
        #: Per person, when each depth of ``DEPTH_ROWS`` was first seen; the first time any person was seen
        #: together (``TOGETHER_STAGES``), living with the player (`living_together`, or the household) and
        #: married (T29's long-term rows).
        self.depth_at: dict[str, dict[int, float]] = {}
        self.stage_at: dict[str, float] = {}

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
            depth = growth.depth(state, pid) if person.get("stage") else 0
            if pid not in self.depth1_at and depth >= 1:
                self.depth1_at[pid] = now
            if depth >= DEPTH_ROWS[0]:
                seen_depth = self.depth_at.setdefault(pid, {})
                for n in DEPTH_ROWS:
                    if depth >= n:
                        seen_depth.setdefault(n, now)
            stage = str(person.get("stage") or "")
            if stage in TOGETHER_STAGES:
                self.stage_at.setdefault("together", now)
            if stage == "living_together" or (stage and relationships.household(state) == pid):
                self.stage_at.setdefault("living_together", now)
            if stage == "married":
                self.stage_at.setdefault("married", now)
            if person.get("stage"):
                seen = self.band_at.setdefault(pid, {})
                for name in names[:names.index(relationships.band(person)) + 1]:
                    seen.setdefault(name, now)


def run(seed: int, sessions: int, policy: str, voice_policy: str = DEFAULT_VOICE, *,
        model_seconds: float = DEFAULT_MODEL_SECONDS, disk: Optional[Path] = None, world: bool = True) -> dict[str, Any]:
    """
    One run of ``sessions`` sessions (``Session``: full, or phone-only with ``world=False``) at
    ``model_seconds`` a reply: its raw measurements (``report`` folds many). ``disk``: a directory the run
    saves under, spilling its threads into the archive after every action as play does (``Phone.spill``);
    the measurements read the archive too, so they are the same either way.
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
            spans = [Session(phone, player, model_seconds=model_seconds, world=world).play()
                     for _ in range(int(sessions))]
            return _measure(phone, player, observer, rec, spans, seed, policy, voice_policy, float(model_seconds),
                            time.perf_counter() - started)
        finally:
            phone.close()


def write_day_save(seed: int, days: int, policy: str, out: Path, voice_policy: str = "romantic_model", *,
                   model_seconds: float = DEFAULT_MODEL_SECONDS, world: bool = True) -> Path:
    """
    A day-``days`` run of ``policy`` saved under ``out`` (spec §17.2's size
    bound): played on disk as ``days`` sessions (``Session``, full since T29,
    phone-only with ``world=False``; one an in-game day, each from waking to
    the next morning), its threads
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
                Session(phone, player, model_seconds=model_seconds, world=world).play()
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


def _real_timeline(phone: Phone) -> tuple[list[float], list[float]]:
    """The run's real clock: every priced action, phone and world, by in-game hour, and the real seconds spent
    up to and including it (each in-game hour is after its action, so the list is in time order)."""
    priced = sorted([(float(at), float(sec)) for _p, at, sec, _m, _e in phone.charges]
                    + [(float(at), float(sec)) for at, sec, _m, _k in phone.world_charges], key=lambda r: r[0])
    ats: list[float] = []
    cum: list[float] = []
    total = 0.0
    for at, sec in priced:
        total += sec
        ats.append(at)
        cum.append(total)
    return ats, cum


def _real_hours_at(ats: list[float], cum: list[float], at: float) -> float:
    """The real hours the run had spent by in-game hour ``at``."""
    import bisect

    i = bisect.bisect_right(ats, float(at) + 1e-9)
    return (cum[i - 1] if i else 0.0) / 3600.0


def _ingame_at_real(ats: list[float], cum: list[float], hours: float) -> Optional[float]:
    """The in-game hour at which the run had spent ``hours`` real hours; None when it never did."""
    import bisect

    i = bisect.bisect_left(cum, float(hours) * 3600.0)
    return ats[i] if i < len(ats) else None


def _measure_world(phone: Phone, world: Optional["World"], observer: "Observer", rec: "Recorder",
                   ats: list[float], cum: list[float], mark: Optional[float]) -> dict[str, Any]:
    """A run's world measurements (T29): its scenes, life events, plans, world turns and counts, the real hours
    at which the long-term stages were first reached, the people active at ``ACTIVE_REAL_HOURS`` real hours
    (an episode with them in the ``ACTIVE_DAYS`` in-game days before), and the events of the jump to morning
    on day ``JUMP_DAY``."""
    active = None
    if mark is not None:
        since = mark - ACTIVE_DAYS * 24.0
        who = {e["pid"] for e in rec.episodes if float(e["started_at"]) <= mark and float(e["closed_at"]) >= since
               and (e.get("kind") != "chat" or (int(e["exchanges"]) >= 1 and e.get("joined")))}
        who |= {s["pid"] for s in rec.scenes if float(s["opened_at"]) <= mark and float(s["at"]) >= since}
        active = len(who)
    plans_closed: dict[str, int] = {}
    for status in rec.plans_closed:
        plans_closed[status] = plans_closed.get(status, 0) + 1
    return {
        "scenes": list(rec.scenes),
        "life": list(rec.life),
        "plans_made": list(rec.plans_made),
        "plans_closed": plans_closed,
        "world_charges": [[round(sec, 3), round(minutes, 4), kind] for _at, sec, minutes, kind in phone.world_charges],
        "world_actions": phone.world_actions,
        "world_refused": phone.world_refused,
        "world_counts": dict(world.counts) if world is not None else {},
        "jump_events": phone.jump_events,
        "active_20h": active,
        "stage_real": {k: round(_real_hours_at(ats, cum, at), 4) for k, at in sorted(observer.stage_at.items())},
        "real_total": round((cum[-1] if cum else 0.0) / 3600.0, 4),
    }


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
    ats, cum = _real_timeline(phone)
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
            # T29: when each depth was first seen, and the run's real hours then and at the match.
            "depth_at": {str(n): at for n, at in sorted(observer.depth_at.get(pid, {}).items())},
            "depth_real": {str(n): round(_real_hours_at(ats, cum, at), 4)
                           for n, at in sorted(observer.depth_at.get(pid, {}).items())},
            "matched_real": None if matched_at is None else round(_real_hours_at(ats, cum, float(matched_at)), 4),
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
    world = player.world
    mark = _ingame_at_real(ats, cum, ACTIVE_REAL_HOURS)
    return {
        **_measure_world(phone, world, observer, rec, ats, cum, mark),
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
    _fold_world(out, mine, by_policy, rows, cuts)
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


def _weeks(runs: list[dict[str, Any]]) -> float:
    """The in-game weeks the runs played, from each one's first session to its end."""
    return sum(max(0.0, float(r["end"]) - float(r["spans"][0]["start"])) for r in runs if r.get("spans")) / (7 * 24.0)


def _session_index(spans: list[dict[str, Any]], at: float) -> Optional[int]:
    """The session an in-game hour belongs to: the first whose end is at or after it (a night's hour is the next
    morning's session's)."""
    return next((i for i, span in enumerate(spans) if float(span["end"]) >= float(at) - 1e-9), None)


def _fold_world(out: dict[str, Any], mine: list[dict[str, Any]], by_policy: dict[str, list[dict[str, Any]]],
                rows: list[dict[str, Any]], cuts: tuple[float, float]) -> None:
    """The world's rows (T29; v0.24.0 §13) into ``out``: the scenes (the morning after counts as no scene, spec
    §12.1), the deep growth, life events, the four life decks, the long-term stages, the people active at 20
    real hours, the jump to morning, and the world's ratio (derived). A run with no world (phone only, or one
    folded from before T29) reports None for each."""
    world_runs = [r for r in mine if "scenes" in r]
    if not world_runs:
        return
    scenes = [s for r in world_runs for s in r["scenes"] if s["kind"] != "morning"]
    for band in SCENE_BANDS:
        out[f"scene_band.{band}"] = _share(sum(1 for s in scenes if s["band"] == band), len(scenes))
    gaps: list[float] = []
    for r in world_runs:
        first: dict[str, float] = {}
        for s in r["scenes"]:
            if s["kind"] != "morning" and s["pid"] not in first:
                first[s["pid"]] = float(s["opened_at"])
        matched = {p["pid"]: p.get("matched_at") for p in r["people"]}
        for pid, opened in first.items():
            if matched.get(pid) is None:
                continue
            k_scene, k_match = _session_index(r["spans"], opened), _session_index(r["spans"], float(matched[pid]))
            if k_scene is not None and k_match is not None:
                gaps.append(float(k_scene - k_match))
    out["sessions_to_first_scene"] = _median(gaps)
    world_rows = [p for r in world_runs for p in r["people"]]
    for band in ("fast", "slow"):
        for n in DEPTH_ROWS:
            values = [float(p["depth_real"][str(n)]) - float(p["matched_real"]) for p in world_rows
                      if str(n) in (p.get("depth_real") or {}) and p.get("matched_real") is not None
                      and _tercile(p["pace"], cuts) == band]
            out[f"real_hours_to_depth.{band}.{n}"] = _median(values)
    weeks = _weeks(world_runs)
    player_events = sum(1 for r in world_runs for e in r["life"] if e["who"] == "player")
    out["life_events.player_per_week"] = None if weeks <= 0 else round(player_events / weeks, 3)
    months = 0.0
    for r in world_runs:
        for p in r["people"]:
            reached = (p.get("depth_at") or {}).get(str(DEPTH_ROWS[0]))
            if reached is not None:
                stop = float(p["left_at"]) if p.get("left_at") is not None else float(r["end"])
                months += max(0.0, stop - float(reached)) / (30 * 24.0)
    deep_events = sum(1 for r in world_runs for e in r["life"] if e["who"] == "person" and int(e["depth"]) >= 2)
    out["life_events.person_per_month_d2plus"] = None if months <= 0 else round(deep_events / months, 3)
    met = sum(int(((r.get("world_counts") or {}).get("decks") or {}).get(deck, 0)) for r in world_runs for deck in DECK_ROOMS)
    out["life_decks_met_per_week"] = None if weeks <= 0 else round(met / weeks, 3)
    for row, stage, hours in (("devoted.together_10h", "together", TOGETHER_REAL_HOURS),
                              ("devoted.living_together_20h", "living_together", LIVING_REAL_HOURS),
                              ("devoted.married_40h", "married", MARRIED_REAL_HOURS)):
        devoted = [r for r in by_policy.get("devoted", []) if "stage_real" in r]
        out[row] = (_share(sum(1 for r in devoted if float((r["stage_real"]).get(stage, 1e9)) <= hours), len(devoted))
                    if devoted else None)
    for name in ("bachelor", "attentive"):
        counts = [float(r["active_20h"]) for r in by_policy.get(name, []) if r.get("active_20h") is not None]
        out[f"active_relationships_20h.{name}"] = _median(counts)
    jumps = [int(r["jump_events"]) for r in world_runs if r.get("jump_events") is not None]
    out["events_per_jump_morning_day60"] = max(jumps) if jumps else None
    charges = [c for r in world_runs for c in r["world_charges"]]
    seconds = sum(float(c[0]) for c in charges)
    out["ratio.world"] = None if seconds <= 0 else round(sum(float(c[1]) for c in charges) / (seconds / 60.0), 3)
    # -- also.* (never banded): what the world did, per run ---------------------------------------------------
    runs = len(world_runs)
    out["also.scenes_per_run"] = round(len(scenes) / runs, 2)
    out["also.mornings_per_run"] = round(sum(1 for r in world_runs for s in r["scenes"] if s["kind"] == "morning") / runs, 2)
    kinds: dict[str, int] = {}
    for s in scenes:
        kinds[s["kind"]] = kinds.get(s["kind"], 0) + 1
    out["also.scene_kinds_per_run"] = {k: round(v / runs, 2) for k, v in sorted(kinds.items())}
    out["also.scene_moments_median"] = _median([float(s["moments"]) for s in scenes])
    out["also.plans_made_per_run"] = round(sum(len(r["plans_made"]) for r in world_runs) / runs, 2)
    closed: dict[str, int] = {}
    for r in world_runs:
        for status, n in (r.get("plans_closed") or {}).items():
            closed[status] = closed.get(status, 0) + int(n)
    out["also.plans_closed_per_run"] = {k: round(v / runs, 2) for k, v in sorted(closed.items())}
    for key in ("work_days", "dinners", "at_home", "stay_overs", "stood_up_by_player"):
        out[f"also.{key}_per_run"] = round(sum(int((r.get("world_counts") or {}).get(key, 0)) for r in world_runs) / runs, 2)
    decks: dict[str, int] = {}
    for r in world_runs:
        for deck, n in (((r.get("world_counts") or {}).get("decks")) or {}).items():
            decks[deck] = decks.get(deck, 0) + int(n)
    out["also.decks_met_per_run"] = {k: round(v / runs, 2) for k, v in sorted(decks.items())}
    out["also.player_life_events_per_run"] = round(player_events / runs, 2)
    out["also.world_actions_per_run"] = round(sum(int(r["world_actions"]) for r in world_runs) / runs, 1)
    out["also.world_refused_per_run"] = round(sum(int(r["world_refused"]) for r in world_runs) / runs, 1)
    out["also.real_hours_per_run"] = round(sum(float(r["real_total"]) for r in world_runs) / runs, 2)
    out["also.events_per_jump_morning_day60.median"] = _median([float(j) for j in jumps])
    for stage in ("together", "living_together", "married"):
        reached = [float(r["stage_real"][stage]) for r in world_runs if stage in (r.get("stage_real") or {})]
        out[f"also.real_hours_to_{stage}.median"] = _median(reached)
        out[f"also.{stage}_runs"] = _share(len(reached), runs)


def companions(policy: str) -> list[str]:
    """The other policies a report of ``policy`` runs beside it, for its ``COMPANION_ROWS``."""
    return sorted({p for p in COMPANION_ROWS.values() if p != policy})


def report(seeds: Iterable[int], sessions: int = 6, policy: str = "attentive", voice_policy: str = DEFAULT_VOICE, *,
           model_seconds: float = DEFAULT_MODEL_SECONDS, companion: bool = True, world: bool = True) -> dict[str, Any]:
    """One value per ``REPORT_ROWS`` key (None: not reachable by these runs -- phone-only, say, or another
    policy's row), plus ``also.*``. With ``companion``, the ``COMPANION_ROWS`` policies are run on the same seeds
    for their rows. ``world=False``: T9's phone-only sessions."""
    seeds = [int(s) for s in seeds]
    policies = [policy, *(companions(policy) if companion else [])]
    return fold([run(seed, sessions, p, voice_policy, model_seconds=model_seconds, world=world)
                 for p in policies for seed in seeds])


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
    parser.add_argument("--sessions", type=int, default=6, help="sessions a run plays (40 real minutes each)")
    parser.add_argument("--phone-only", action="store_true",
                        help="T9's phone-only sessions: no world, no work, no plans or scenes (full sessions by default)")
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
                            disk=Path(args.disk) / f"{p}-{voice}-{seed}" if args.disk else None,
                            world=not args.phone_only)
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
