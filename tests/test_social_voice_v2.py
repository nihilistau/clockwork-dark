"""
The voice, reworked (v0.23.0 T7; spec §4.5's caps, §7.4, §13.1-§13.4, §19.4).

The mode sets the bubbles, their length and the call's `max_tokens`; the
prompt's window reserves the mode's cap and degrades on a 4096 binding; the
voice reads who they are now, their story, what is open, the bridge, the
mode, the end and its reason; a reply's follow-ups, promise and opening up
reach the state only through the engine's own re-checked writes; and two
new agreement checks hold promises and commitments to the facts. No model
is called: every voice here is a stub.
"""

from __future__ import annotations

import dataclasses
import json
from typing import Any

import pytest

from tests.social_fixtures import (  # noqa: F401
    _act, _open_episode, _replies_forced, _set_person, matched, receipts_active, receipts_state,
)
from tests.social_stub import StubVoice


def _snap(state, thread):
    """The thread's snapshot; a fresh match's opener is not due yet, so with nothing due a `reply` of
    theirs is made due now (`_due`) -- the snapshot needs one message to voice."""
    from engine.social import voicing

    if voicing.snapshot_of(state, thread) is None:
        _due(state, thread)
    snap = voicing.snapshot_of(state, thread)
    assert snap is not None
    return snap


def _due(state, thread: str, **decision: Any) -> str:
    """A due message of theirs in ``thread`` now, carrying ``Decision(**decision)`` (situation `reply` by
    default): its id. Any earlier due message of theirs is voiced first by the caller or left alone."""
    from engine.social import messaging
    from engine.social.kinds import Decision

    pid = thread.split(":")[1]
    decision.setdefault("situation", "reply")
    row = messaging.new_message(state, thread, pid, "text", at=state.world_clock_hours, voiced=False,
                                decision=dataclasses.asdict(Decision(**decision)))
    return str(row["id"])


def _only_due(state, thread: str, **decision: Any):
    """The thread's earlier due messages withdrawn (through `social_voiced`), then one due now: its snapshot."""
    from engine.game.effects import apply_effect

    t = state.social["threads"][thread]
    earlier = [m["id"] for m in t["messages"] if m.get("voiced") is False]
    if earlier:
        assert apply_effect(state, {"type": "social_voiced", "op": "withdraw", "thread_id": thread,
                                    "message_ids": earlier})["ok"]
    _due(state, thread, **decision)
    return _snap(state, thread)


def _reply(text: str = "sure", **extra: Any) -> str:
    return json.dumps({"bubbles": [{"text": text}], "regard": {"warmth": 0, "trust": 0, "mood": "neutral"},
                       "learned": [], "shared": [], **extra})


def _user(msgs) -> str:
    return msgs[1]["content"]


def _block(user: str, title: str) -> str:
    from engine.social import voicing

    after = user.split(f"{title}\n", 1)[1]
    titles = list(voicing.BLOCK_TITLES)
    following = titles[titles.index(title) + 1] if title != titles[-1] else None
    return after.split(f"\n\n{following}\n", 1)[0] if following else after


# The block-order test is NOT here: it is v0.22's `tests/test_social_voicing.py::
# test_the_voice_prompt_is_exactly_its_blocks`, rewritten in place against the new BLOCK_TITLES
# (one test per fact; pre-flight F25). Its v0.22 title parse (`part.split("\n", 1)[0]` over the
# blank-line-separated blocks) is kept.


# -- the brief's tests ----------------------------------------------------------------------------


@pytest.mark.parametrize("mode,bubbles,chars,tokens", [("quick", 2, 280, 300), ("chatting", 4, 500, 560),
                                                       # T9's latency lever: deep on chatting's caps (§20.2)
                                                       ("deep", 3, 500, 560)])
def test_the_mode_sets_bubbles_length_and_max_tokens(receipts_state, matched, mode, bubbles, chars, tokens) -> None:
    from engine.social import voicing
    from engine.social.kinds import Decision

    schema = voicing.reply_schema(Decision(situation="reply", mode=mode, max_bubbles=bubbles), (), ("neutral",))
    items = schema["properties"]["bubbles"]
    assert items["maxItems"] == bubbles and items["items"]["properties"]["text"]["maxLength"] == chars
    assert voicing.mode_caps(mode)["max_tokens"] == tokens


def test_a_4096_binding_degrades_and_still_fits(receipts_state, matched) -> None:
    """§7.4, I7: a 4096-context stub binding gets a fitting prompt and a reply; nothing never-trimmed is cut."""
    from engine.social import memory, voicing
    from tests.social_stub import StubVoice

    thread = matched("matchstick")
    pid = thread.split(":")[1]
    window, degraded = voicing.window_for(4096, "deep")
    assert degraded and window <= 4096 - voicing.mode_caps("chatting")["max_tokens"]
    snap = _snap(receipts_state, thread)
    msgs = voicing.messages(snap, usable_context=4096)
    assert memory._estimate({"all": msgs[0]["content"] + msgs[1]["content"]}) <= 4096
    body = msgs[1]["content"]
    for kept in ("WHO YOU ARE NOW\n", "STILL OPEN\n", "THIS CONVERSATION\n", "RIGHT NOW\n"):
        assert kept in body                                       # v0.22's block form: f"{title}\n{body}"
    reply = voicing.voice(snap, StubVoice("zero"))
    assert reply.bubbles and not reply.fallback
    assert pid == snap.pid


_LONG = ("honestly I could talk about the harbour all day, the boats coming in at six and the gulls "
         "fighting over the chip papers, and the way the light goes gold on the water before the rain")


def test_a_4096_binding_with_a_long_history_trims_to_fit(receipts_state, matched) -> None:
    """§7.4, I7, with a history long enough to need trimming: twelve recaps and a story, 40 canon facts,
    60 history rows and 50 long messages. On a 4096 binding the prompt fits its window, the recaps are cut
    to three, the conversation keeps at least its floor of 16, and WHO YOU ARE NOW, STILL OPEN, the bridge
    and RIGHT NOW are whole; a reply is still made."""
    from engine.memory.budget import estimate_messages
    from engine.social import memory, messaging, relationships, voicing

    thread = matched("matchstick")
    pid = thread.split(":")[1]
    for n in range(16):
        memory.add_recap(receipts_state, pid, {"id": f"e9{n:02d}", "from_at": float(n), "to_at": float(n) + 0.5,
                                               "recap": f"You talked about {_LONG} ({n}).", "topics": []})
    memory.add_canon(receipts_state, pid, [f"{_LONG} ({i})" for i in range(40)])
    for row in range(60):
        relationships.add_history(receipts_state, pid, "moment", f"a small thing happened ({row})", at=float(row))
    memory.add_open(receipts_state, pid, {"kind": "followup", "about": "their sister's wedding",
                                          "due_at": receipts_state.world_clock_hours + 30.0, "by": "person"})
    at = receipts_state.world_clock_hours
    for n in range(50):
        messaging.new_message(receipts_state, thread, "player" if n % 2 else pid, "text", bubbles=[_LONG],
                              at=at - 2.0 + n * 0.01)
    receipts_state.social["people"][pid]["memory"]["bridge"] = [
        {"id": "m9999", "thread_id": thread, "from": pid, "at": 0.9, "bubbles": ["night! talk tomorrow x"]}]
    snap = _only_due(receipts_state, thread, mode="deep", max_bubbles=3)
    assert memory.person(receipts_state, pid)["story"] and len(snap.memory["episodes"]) == 12
    window, degraded = voicing.window_for(4096, "deep")
    msgs = voicing.messages(snap, usable_context=4096)
    user = _user(msgs)
    assert degraded and estimate_messages(msgs) <= 4096
    assert estimate_messages(msgs) <= window                           # the margin covers the joins (review M6)
    assert _block(user, "WHO YOU ARE NOW") == snap.who_now
    assert "their sister's wedding" in _block(user, "STILL OPEN")
    assert "night! talk tomorrow x" in _block(user, "THIS CONVERSATION")
    assert _block(user, "RIGHT NOW").endswith(f"SITUATION: {voicing.texter_prompt().instructions['reply']}")
    together = _block(user, "YOUR STORY TOGETHER").split("\n")
    assert sum(1 for line in together if "You talked about" in line) <= memory.EPISODES_MIN
    now_lines = _block(user, "THIS CONVERSATION").split("Now:\n", 1)[1].split("\n")
    assert len(now_lines) >= 16
    assert not voicing.voice(snap, StubVoice("zero")).fallback
    roomy = voicing.messages(snap, usable_context=16384)
    assert len(_user(roomy)) > len(user)                                 # the big binding keeps more of it


def test_the_bio_is_absent_at_everyday(receipts_state, matched) -> None:
    from engine.game.effects import apply_effect
    from engine.social import population, voicing

    thread = matched("matchstick")
    pid = thread.split(":")[1]
    bio = next(iter(population.profile(receipts_state, pid).bio.values()))
    assert bio in voicing.messages(_snap(receipts_state, thread))[1]["content"]       # at small talk: there
    _set_person(receipts_state, pid, warmth=99, trust=99, episodes_done=2)
    apply_effect(receipts_state, {"type": "social_growth", "op": "gain", "pid": pid, "amount": 100})
    assert bio not in voicing.messages(_snap(receipts_state, thread))[1]["content"]


def test_commitment_claimed_fails_a_step_the_table_does_not_hold(receipts_state, matched) -> None:
    from engine.social import agreement
    from engine.social.kinds import Decision

    pid = matched("matchstick").split(":")[1]
    view = agreement.view_from_state(receipts_state, pid)
    reply = {"bubbles": [{"text": "honestly, let's move in together"}]}
    names = [f.check for f in agreement.check(reply, Decision(situation="reply"), view)]
    assert "commitment_claimed" in names


def test_promise_claimed_fails_a_different_window(receipts_state, matched) -> None:
    from engine.social import agreement, promises
    from engine.social.kinds import Decision

    pid = matched("matchstick").split(":")[1]
    row = promises.make(receipts_state, pid, by="person", window="after_work")
    view = agreement.view_from_state(receipts_state, pid)
    reply = {"bubbles": [{"text": "I'll message you in the morning"}]}
    names = [f.check for f in agreement.check(reply, Decision(situation="sign_off", end="sign_off",
                                                                promise_id=row["id"]), view)]
    assert "promise_claimed" in names


# -- the brief's further tests ----------------------------------------------------------------------


@pytest.mark.parametrize("mode", ["quick", "chatting", "deep"])
def test_the_prompt_reserves_the_modes_cap(receipts_state, matched, mode) -> None:
    """§7.4 (MINOR 8): the user block fits the window left once the MODE's own reply cap is reserved."""
    from engine.memory.budget import estimate_messages
    from engine.social import voicing

    thread = matched("matchstick")
    snap = _only_due(receipts_state, thread, mode=mode, max_bubbles=3)
    ceiling = voicing._configured_window()                     # social.voice.window_tokens (6144 since T9)
    window, degraded = voicing.window_for(8192, mode)
    assert not degraded and window == ceiling - voicing.mode_caps(mode)["max_tokens"] - voicing.WINDOW_MARGIN
    msgs = voicing.messages(snap, usable_context=8192)
    assert estimate_messages([msgs[1]]) <= window


def test_production_passes_the_modes_max_tokens(receipts_state, matched, monkeypatch) -> None:
    """`production_llm_fn` passes the mode's cap through `backend.chat`'s own `max_tokens` (spec §4.5);
    the profile's 800 is only the ceiling. No network: the backend and the binding are stubbed."""
    from types import SimpleNamespace

    from engine.llm import backend as backend_mod
    from engine.social import voicing

    seen: list[dict[str, Any]] = []

    class Backend:
        def structured_output(self, envelope):
            return {"type": "json_schema", "json_schema": envelope}

        def chat(self, msgs, **kw):
            seen.append(kw)
            return SimpleNamespace(content=_reply("that sounds lovely"), truncated=False)

    monkeypatch.setattr(backend_mod, "get_backend", lambda: Backend())
    monkeypatch.setattr(voicing.TexterCall, "usable_context", lambda self: 16384)
    thread = matched("matchstick")
    reply = voicing.voice(_only_due(receipts_state, thread, mode="deep", max_bubbles=3), voicing.production_llm_fn())
    assert not reply.fallback
    # Deep's own cap (T9's `modes.deep_as_chatting` lever puts it on chatting's: 560, not 760).
    assert seen[0]["max_tokens"] == voicing.mode_caps("deep")["max_tokens"] and seen[0]["profile"] == "texter"
    # On a 4096 binding deep is voiced with chatting's caps (§7.4).
    monkeypatch.setattr(voicing.TexterCall, "usable_context", lambda self: 4096)
    voicing.voice(_snap(receipts_state, thread), voicing.production_llm_fn())
    assert seen[-1]["max_tokens"] == 560


def test_the_fallbacks_cover_every_situation_and_mode(receipts_active) -> None:
    """§13.1: every `situation.mode` the instruction table names has `any:` lines (three or more), and
    every template names only engine facts."""
    from engine.social import voicing
    from engine.social.kinds import MODES

    prompt = voicing.texter_prompt()
    every = prompt.fallbacks[voicing.ANY_KEY]
    thin = [f"{row}.{mode}" for row in prompt.instructions for mode in MODES if len(every.get(f"{row}.{mode}") or ()) < 3]
    assert thin == []
    for block in prompt.fallbacks.values():
        for lines in block.values():
            for line in lines:
                assert voicing._fields(line) <= set(voicing.FACT_FIELDS), line
    for row in prompt.instructions.values():
        assert voicing._fields(row) <= set(voicing.FACT_FIELDS), row
    assert set(prompt.reasons) == set(__import__("engine.social.convo", fromlist=["REASON_KEYS"]).REASON_KEYS)
    for retired in ("good_morning", "check_in", "late_night", "reveal_turn"):
        assert retired not in prompt.instructions
    for row in ("winding", "sign_off", "promised_message", "followup", "news", "opens_up", "stood_up", "flake",
                "window_message"):
        assert row in prompt.instructions
    assert "Most texts are short" not in prompt.persona
    assert ("When you are properly talking, write like a person in a real conversation: full thoughts, a "
            "question back, and picking up things said earlier — today or weeks ago.") in prompt.persona


def test_texter_has_no_rating_line(receipts_active) -> None:
    """Rule 12 (§19.6): v0.22's `RATING_WORDS`, applied to the new correction lines, the persona, the
    instruction table, the mode words and the schema's notes (unchanged scope)."""
    from engine.social import voicing
    from tests.test_social_voicing import RATING_WORDS

    prompt = voicing.texter_prompt()
    texts = [prompt.persona, *prompt.instructions.values(), *voicing.CORRECTIONS.values(),
             *voicing.MODE_WORDS.values(), voicing.DEFAULT_CORRECTION]
    for text in texts:
        for word in RATING_WORDS:
            assert word not in text.lower(), (word, text)


# -- the window and the budget (§7.4) ----------------------------------------------------------------


def test_the_budget_never_trims_now_who_open_or_bridge(receipts_active) -> None:
    """`memory.budgeted`: a window far too small trims recaps to 3, the story, canon, history to its
    floor and the conversation to 16 -- and never touches `now`, `who_now`, `open` or `bridge`."""
    from engine.social import memory

    long = " ".join(f"word{i}." for i in range(400))
    parts = {"persona": "P " * 50, "who_now": "W " * 300, "story": long,
             "episodes": "\n".join(f"recap {i} " + "x " * 40 for i in range(12)), "knows": "K",
             "open": "O " * 200, "you_and_them": "Y", "canon": "\n".join(f"canon {i}" for i in range(40)),
             "history": "\n".join(f"Day {i}: h" for i in range(20)), "bridge": "B " * 200,
             "current": "\n".join(f"line {i} " + "y " * 20 for i in range(40)), "now": "N " * 100, "format": "F"}
    out = memory.budgeted(parts, 200)
    for key in memory.NEVER_TRIMMED:
        assert out[key] == parts[key], key
    assert len(out["episodes"].split("\n")) == memory.EPISODES_MIN
    assert out["episodes"].split("\n") == parts["episodes"].split("\n")[-memory.EPISODES_MIN:]   # oldest first
    assert out["story"] == "" and out["canon"] == ""
    assert len(out["history"].split("\n")) == 4 and len(out["current"].split("\n")) == 16
    assert out["current"].split("\n") == parts["current"].split("\n")[-16:]


def test_a_degraded_binding_cuts_the_story_and_recaps_first(receipts_active) -> None:
    """§7.4 step 2: on a degraded binding the story is cut to its newest 120 words and three recaps are
    kept before anything else, even when the window would hold them all."""
    from engine.social import memory

    story = " ".join(f"w{i}" for i in range(300)) + "."
    parts = {"story": story, "episodes": "\n".join(f"recap {i}" for i in range(12)), "current": "a\nb"}
    out = memory.budgeted(parts, 100_000, degraded=True)
    assert out["story"].split() == story.split()[-memory.DEGRADED_STORY_WORDS:]
    assert out["episodes"] == "recap 9\nrecap 10\nrecap 11" and out["current"] == "a\nb"
    assert memory.budgeted(parts, 100_000) == parts                                     # not degraded: untouched


def test_the_window_degrades_below_the_configured_window(receipts_active, monkeypatch) -> None:
    """Plan decision 33: degraded reads `social.voice.window_tokens`, not a literal 8192."""
    from engine import social
    from engine.social import voicing
    from tests.social_fixtures import _with

    # 6144 since T9's latency lever (config/default.yaml `social.voice.window_tokens`); deep on chatting's caps.
    assert voicing.window_for(8192, "chatting") == (6144 - 560 - 128, False)
    assert voicing.window_for(32768, "deep") == (6144 - 560 - 128, False)                 # the window is a ceiling
    assert voicing.window_for(6000, "chatting") == (6000 - 560 - 128, True)
    monkeypatch.setattr(social, "setting", _with(social.setting, **{"voice.window_tokens": 4096}))
    assert voicing.window_for(4096, "chatting") == (4096 - 560 - 128, False)
    assert voicing.window_for(3000, "deep") == (3000 - 560 - 128, True)


@pytest.mark.parametrize("flag,tokens,chars", [(False, 760, 700), (True, 560, 500)])
def test_deep_as_chatting_puts_deep_on_chattings_caps(receipts_active, monkeypatch, flag, tokens, chars) -> None:
    """Spec §20.2's third latency lever (T9): `modes.deep_as_chatting` voices deep with chatting's caps on any
    binding; off, deep keeps its own unless the binding is degraded."""
    from engine import social
    from engine.social import voicing

    modes = social.data("conversation")["modes"]
    monkeypatch.setitem(modes, "deep_as_chatting", flag)
    assert voicing.mode_caps("deep")["max_tokens"] == tokens
    assert voicing.mode_caps("deep")["bubble_chars"] == chars
    assert voicing.mode_caps("deep", degraded=True)["max_tokens"] == 560
    assert voicing.mode_caps("chatting")["max_tokens"] == 560


def test_deep_as_chatting_must_be_a_boolean(receipts_active) -> None:
    import copy

    from engine import social
    from engine.social import convo

    data = copy.deepcopy(social.data("conversation"))
    data["modes"]["deep_as_chatting"] = "yes"
    with pytest.raises(ValueError, match="deep_as_chatting"):
        convo.check_data(data)


# -- what the voice reads (§13.2) -----------------------------------------------------------------


def test_right_now_reads_the_mode_the_end_and_its_reason(receipts_state, matched) -> None:
    """A sign-off's ENDING row carries the engine's reason; a winding one the same; the mode's words."""
    from engine.social import voicing

    thread = matched("matchstick")
    snap = _only_due(receipts_state, thread, mode="chatting", max_bubbles=4, min_bubbles=2,
                     end="sign_off", reason="your shift starts at 7")
    now = _block(_user(voicing.messages(snap)), "RIGHT NOW")
    assert f"How the conversation is going: {voicing.MODE_WORDS['chatting']}" in now
    assert "ENDING: You need to go now: your shift starts at 7." in now
    assert "Send 2-4 messages." in now
    wind = _only_due(receipts_state, thread, end="winding", reason="it's a natural place to leave it")
    assert "ENDING: The conversation is coming to a natural end: it's a natural place to leave it." in \
        _block(_user(voicing.messages(wind)), "RIGHT NOW")


def test_a_promise_reads_its_window_and_a_promised_message_its_row(receipts_state, matched) -> None:
    """T4's `promise_id`, read at last: the sign-off is told the window it promised; a promised message's
    own row names it; STILL OPEN lists it."""
    from engine.social import promises, voicing

    thread = matched("matchstick")
    pid = thread.split(":")[1]
    row = promises.make(receipts_state, pid, by="person", window="tonight")
    assert row is not None
    words = promises.window_words(row, speaker="person", now=receipts_state.world_clock_hours)
    snap = _only_due(receipts_state, thread, end="sign_off", reason="you're about to head out", promise_id=row["id"])
    user = _user(voicing.messages(snap))
    assert f"Your promise: you will message them {words}." in _block(user, "RIGHT NOW")
    assert f"You said you'd message them {words}." in _block(user, "STILL OPEN")
    kept = _only_due(receipts_state, thread, situation="promised_message", promise_id=row["id"])
    assert f"SITUATION: You said you would message them {words}, and this is that message." in \
        _block(_user(voicing.messages(kept)), "RIGHT NOW")


def test_the_story_recaps_bridge_and_open_rows_reach_the_prompt(receipts_state, matched) -> None:
    """§7.1's parts in their blocks: the story and recaps in YOUR STORY TOGETHER (labelled from the
    player's side), a follow-up in STILL OPEN, the bridge in THIS CONVERSATION, before the current talk."""
    from engine.game.effects import apply_effect
    from engine.social import memory, voicing

    thread = matched("matchstick")
    pid = thread.split(":")[1]
    memory.add_recap(receipts_state, pid, {"id": "e900", "from_at": 1.0, "to_at": 2.0,
                                           "recap": "You talked about the harbour; they told you about their sister.",
                                           "topics": []})
    memory.add_open(receipts_state, pid, {"kind": "followup", "about": "their sister's wedding",
                                          "due_at": receipts_state.world_clock_hours + 48.0, "by": "person"})
    person = receipts_state.social["people"][pid]
    bridge = [{"id": "m900", "thread_id": thread, "from": pid, "at": 1.5, "bubbles": ["night! sleep well"]}]
    person.setdefault("memory", memory.fresh())["bridge"] = bridge   # a hand-set part (a test fixture)
    apply_effect(receipts_state, {"type": "social_person", "pid": pid, "set": {}})
    user = _user(voicing.messages(_only_due(receipts_state, thread)))
    together = _block(user, "YOUR STORY TOGETHER")
    assert "they told you about their sister" in together and "\"you\" in it means" in together
    assert "To ask them about (later): their sister's wedding" in _block(user, "STILL OPEN")
    conversation = _block(user, "THIS CONVERSATION")
    assert conversation.startswith("How you left it last time:\n") and "night! sleep well" in conversation


def test_you_and_them_lists_the_commitments_that_hold(receipts_state, matched) -> None:
    """§13.2 block 6: only the commitments a phone ask can act on, and never `stay_over` (m5)."""
    from engine.social import voicing
    from tests.social_fixtures import _force_stage

    thread = matched("matchstick")
    pid = thread.split(":")[1]
    first = _block(_user(voicing.messages(_only_due(receipts_state, thread))), "YOU AND THEM")
    assert "What you would be up for with them now: nothing more yet." in first
    _force_stage(receipts_state, pid, "dating")
    _set_person(receipts_state, pid, warmth=90, trust=90, scenes_done=4)
    later = _block(_user(voicing.messages(_only_due(receipts_state, thread))), "YOU AND THEM")
    assert "swapping numbers" in later and "meeting up" in later and "having them over" in later
    assert "stay" not in later.split("up for with them now:")[1].split("\n")[0]


# -- the schema's additions (§13.3) ------------------------------------------------------------------


def test_followups_are_offered_and_bounded_and_recorded_at_commit(receipts_state, matched) -> None:
    """A reply's `followups` (at most 2, `when` an enum the engine resolves) reach `apply_followups` at
    commit: `relationships.apply_followups` has its production caller (T6's concern 3)."""
    from engine.social import memory, voicing
    from tests.social_fixtures import _voice_all

    thread = matched("matchstick")
    pid = thread.split(":")[1]
    snap = _only_due(receipts_state, thread)
    schema = voicing.reply_schema(voicing._decision(snap), snap.proposals, ("neutral",),
                                  followups=snap.followups_max)
    rows = schema["properties"]["followups"]
    assert rows["maxItems"] == 2 and "tomorrow" in rows["items"]["properties"]["when"]["enum"]
    assert "after:lunch" in rows["items"]["properties"]["when"]["enum"]
    stub = StubVoice("zero", script=[_reply("good luck tomorrow!", followups=[
        {"about": "your interview", "when": "tomorrow"}, {"about": "the gig", "when": "days:3"},
        {"about": "a third", "when": "days:2"}, {"about": "bad", "when": "never"}])])
    _voice_all(receipts_state, stub)
    opened = [r["about"] for r in memory.person(receipts_state, pid)["open"]]
    assert opened == ["your interview", "the gig"]


def test_a_promise_is_offered_only_while_ending_and_made_at_commit(receipts_state, matched) -> None:
    """§5.2 route 3: `promise` is in the schema only while winding or signing off with no promise of their
    own, its window an enum of those that resolve for them; the commit makes it."""
    from engine.social import promises, voicing
    from tests.social_fixtures import _voice_all

    thread = matched("matchstick")
    pid = thread.split(":")[1]
    _open_episode(receipts_state, pid, thread)
    plain = _only_due(receipts_state, thread)
    assert "promise" not in voicing.reply_schema(voicing._decision(plain), plain.proposals, ("neutral",),
                                                 promise_windows=plain.promise_windows)["properties"]
    from engine.game.effects import apply_effect

    apply_effect(receipts_state, {"type": "social_episode", "op": "end", "pid": pid, "end": "winding",
                                  "reason": "it's a natural place to leave it", "reason_key": "length",
                                  "at": receipts_state.world_clock_hours})
    snap = _only_due(receipts_state, thread, end="winding", reason="it's a natural place to leave it")
    assert snap.promise_windows
    schema = voicing.reply_schema(voicing._decision(snap), snap.proposals, ("neutral",),
                                  promise_windows=snap.promise_windows)
    window = snap.promise_windows[0]
    assert schema["properties"]["promise"]["items"]["properties"]["window"]["enum"] == list(snap.promise_windows)
    assert "promise" not in (schema["properties"].get("proposals") or {}).get("items", {}).get("enum", [])
    stub = StubVoice("zero", script=[_reply("talk soon!", promise=[{"window": window, "about": ""}])])
    _voice_all(receipts_state, stub)
    made = promises.open_by(receipts_state, pid, by="person")
    assert [r["window"] for r in made] == [window]


def test_a_promise_stated_mid_chat_becomes_a_tracked_promise(receipts_state, matched, monkeypatch) -> None:
    """Review I1: "I'll text you <window>" in an ordinary chatting reply -- no `promise` key offered, none
    made by the decision -- is adopted at commit through the validated promise path when the window
    resolves for them, so the person keeps it (addendum 2's continuity)."""
    from engine import social
    from engine.social import agreement, promises, voicing
    from tests.social_fixtures import _voice_all

    monkeypatch.setattr(agreement, "makes_promises", lambda state, pid_: True)   # forced: no archetype draw
    thread = matched("matchstick")
    pid = thread.split(":")[1]
    _open_episode(receipts_state, pid, thread)
    snap = _only_due(receipts_state, thread, mode="chatting", max_bubbles=4)
    assert snap.promise_windows, "no window resolves now: the fixture proves nothing"
    schema = voicing.reply_schema(voicing._decision(snap), snap.proposals, ("neutral",),
                                  promise_windows=snap.promise_windows)
    assert "promise" not in schema["properties"]                       # mid-chat: no key to fill
    window = snap.promise_windows[0]
    phrase = (social.data("relationships")["claims"]["promise"][window])[0]
    words = f"oh that sounds fun, {phrase} and you can tell me how it went"
    assert agreement.check({"bubbles": [words]}, voicing._decision(snap), agreement.view_from_snapshot(snap)) == []
    assert promises.open_by(receipts_state, pid, by="person") == []
    _voice_all(receipts_state, StubVoice("zero", script=[_reply(words)]))
    assert [r["window"] for r in promises.open_by(receipts_state, pid, by="person")] == [window]


def test_a_stated_promise_is_adopted_only_from_someone_who_makes_promises(receipts_state, matched, monkeypatch) -> None:
    """A breadcrumber makes no promises (§5.2): no window resolves for them, the words fail the check, and the
    commit never records one."""
    from engine.social import agreement, promises, voicing
    from tests.social_fixtures import _voice_all

    thread = matched("matchstick")
    pid = thread.split(":")[1]
    monkeypatch.setattr(agreement, "makes_promises", lambda state, pid_: False)
    snap = _only_due(receipts_state, thread)
    assert snap.promise_windows == () and not snap.makes_promises
    words = {"bubbles": ["I'll text you tonight"]}
    assert "promise_claimed" in [f.check for f in agreement.check(words, voicing._decision(snap),
                                                                 agreement.view_from_snapshot(snap))]
    _voice_all(receipts_state, StubVoice("zero", script=[_reply("I'll text you tonight")] * 2))
    assert promises.open_by(receipts_state, pid, by="person") == []


def test_a_broken_promise_follow_up_reads_as_a_question(receipts_state, matched) -> None:
    """Review M2: a follow-up's `about` is from the person's side ("your plans tonight"), so §13.1's
    "How did {followup} go?" reads well over it; the `player` reason reads well in a sign-off."""
    from engine.social import voicing

    prompt = voicing.texter_prompt()
    assert "How did {followup} go?" in prompt.fallbacks[voicing.ANY_KEY]["followup.chatting"]
    for line in (*prompt.fallbacks[voicing.ANY_KEY]["sign_off.quick"], *prompt.fallbacks[voicing.ANY_KEY]["sign_off.chatting"]):
        said = voicing._fill(line, {"reason": prompt.reasons["player"], "promise_words": ""})
        assert "you've got to go" not in said, said
    thread = matched("matchstick")
    oid = _with_followup(receipts_state, thread, about="your plans tonight")
    snap = _only_due(receipts_state, thread, followup_id=oid, mode="chatting", max_bubbles=4)
    lines = {voicing.fallback_reply(dataclasses.replace(snap, seed=s), "no model").bubbles[0] for s in range(60)}
    assert "How did your plans tonight go?" in lines
    quick = _only_due(receipts_state, thread, followup_id=oid)
    said = {voicing.fallback_reply(dataclasses.replace(quick, seed=s), "no model").bubbles[0] for s in range(60)}
    assert "so... your plans tonight?" in said                          # an ellipsis is kept whole


def test_right_now_tells_an_arc_reveal_now(receipts_state, matched) -> None:
    """Review M3: the engine has already applied an arc's reveal, so the voice is told to say it now."""
    from engine.social import voicing

    thread = matched("matchstick")
    snap = _only_due(receipts_state, thread, situation="opens_up", reveal="wants_something_else")
    now = _block(_user(voicing.messages(snap)), "RIGHT NOW")
    assert "What has changed:" in now and "Tell them now." in now


# -- follow-ups closed only when raised (T6 review M3) ------------------------------------------------


def _with_followup(state, thread: str, *, about: str = "your interview") -> str:
    from engine.social import memory

    pid = thread.split(":")[1]
    done = memory.add_open(state, pid, {"kind": "followup", "about": about,
                                        "due_at": state.world_clock_hours, "by": "person"})
    return done["open"]["id"]


@pytest.mark.parametrize("words,closed", [("how did the interview go??", True), ("haha same", False)])
def test_a_followup_closes_only_when_the_reply_raised_it(receipts_state, matched, words, closed) -> None:
    from engine.social import memory
    from tests.social_fixtures import _voice_all

    thread = matched("matchstick")
    pid = thread.split(":")[1]
    oid = _with_followup(receipts_state, thread)
    snap = _only_due(receipts_state, thread, followup_id=oid)
    assert snap.followup["about"] == "your interview"
    assert "FOLLOW-UP: Something they told you before is on your mind: your interview." in \
        _block(_user(__import__("engine.social.voicing", fromlist=["messages"]).messages(snap)), "RIGHT NOW")
    _voice_all(receipts_state, StubVoice("zero", script=[_reply(words)]))
    still = [r["id"] for r in memory.person(receipts_state, pid)["open"]]
    assert (oid not in still) is closed


@pytest.mark.parametrize("asked,words,closed", [(True, "haha same", True), (False, "how did the interview go??", False)])
def test_followup_asked_is_the_reply_s_own_statement(receipts_state, matched, asked, words, closed) -> None:
    """Review I2: with `snap.followup` set the schema offers `followup_asked`, and the commit closes the
    follow-up on its word alone -- true closes it whatever the words, false keeps it whatever they say."""
    from engine.social import memory, voicing
    from tests.social_fixtures import _voice_all

    thread = matched("matchstick")
    pid = thread.split(":")[1]
    oid = _with_followup(receipts_state, thread)
    snap = _only_due(receipts_state, thread, followup_id=oid)
    schema = voicing.reply_schema(voicing._decision(snap), snap.proposals, ("neutral",), followup_asked=True)
    assert schema["properties"]["followup_asked"]["type"] == "boolean" and "followup_asked" in schema["required"]
    plain = voicing.reply_schema(voicing._decision(snap), snap.proposals, ("neutral",))
    assert "followup_asked" not in plain["properties"] and "opened_up" not in plain["properties"]
    _voice_all(receipts_state, StubVoice("zero", script=[_reply(words, followup_asked=asked)]))
    assert (oid not in [r["id"] for r in memory.person(receipts_state, pid)["open"]]) is closed


@pytest.mark.parametrize("asked,closed", [(False, False), (True, True)])
def test_a_sign_off_says_outright_whether_it_raised_the_follow_up(receipts_state, matched, asked, closed) -> None:
    """Re-review I2: a winding or signing-off reply that carries a follow-up is offered `followup_asked` too,
    so its own word decides: "talk tonight" does not close an unasked broken-promise follow-up ("your plans
    tonight"), and `followup_asked: true` on the sign-off does."""
    from engine.social import memory, voicing
    from tests.social_fixtures import _voice_all

    thread = matched("matchstick")
    pid = thread.split(":")[1]
    oid = _with_followup(receipts_state, thread, about="your plans tonight")
    snap = _only_due(receipts_state, thread, followup_id=oid, end="sign_off", reason="you're about to head out")
    schema = voicing._schema_for(snap, voicing._decision(snap), ("neutral",), degraded=False)
    assert "followup_asked" in schema["required"]
    assert "FOLLOW-UP:" in _block(_user(voicing.messages(snap)), "RIGHT NOW")
    _voice_all(receipts_state, StubVoice("zero", script=[_reply("gotta go, talk tonight x", followup_asked=asked)]))
    assert (oid not in [r["id"] for r in memory.person(receipts_state, pid)["open"]]) is closed


@pytest.mark.parametrize("second", ["key", "again"])
def test_a_promise_stated_twice_is_recorded_once(receipts_state, matched, monkeypatch, second) -> None:
    """Re-review minor: a window said in the words and by the `promise` key, or said in two replies in a row,
    is ONE promise (`promises.make` returns the open row it overlaps)."""
    from engine import social
    from engine.game.effects import apply_effect
    from engine.social import agreement, promises
    from tests.social_fixtures import _voice_all

    monkeypatch.setattr(agreement, "makes_promises", lambda state, pid_: True)
    thread = matched("matchstick")
    pid = thread.split(":")[1]
    _open_episode(receipts_state, pid, thread)
    snap = _only_due(receipts_state, thread, mode="chatting", max_bubbles=4)
    window = snap.promise_windows[0]
    phrase = social.data("relationships")["claims"]["promise"][window][0]
    _voice_all(receipts_state, StubVoice("zero", script=[_reply(f"okay, {phrase}")]))
    if second == "key":
        apply_effect(receipts_state, {"type": "social_episode", "op": "end", "pid": pid, "end": "winding",
                                      "reason": "it's a natural place to leave it", "reason_key": "length",
                                      "at": receipts_state.world_clock_hours})
        _only_due(receipts_state, thread, end="winding", reason="it's a natural place to leave it")
        extra = {"promise": [{"window": window, "about": ""}]}
    else:
        _only_due(receipts_state, thread, mode="chatting", max_bubbles=4)
        extra = {}
    _voice_all(receipts_state, StubVoice("zero", script=[_reply(f"night! {phrase}", **extra)]))
    assert [r["window"] for r in promises.open_by(receipts_state, pid, by="person")] == [window]


@pytest.mark.parametrize("about,words,raised", [
    ("how their week went", "this week has been so long", False),         # one short key word: not enough
    ("their sister's wedding", "how was the wedding?", True),              # one key word of six letters
    ("your trip home", "how was the trip home?", True),                    # two key words
    ("your trip home", "good trip?", False),                               # one of them, short
    ("your plans tonight", "my plans fell through", False),               # one short key word
])
def test_an_ungrammared_reply_raises_a_followup_only_with_enough_words(about, words, raised) -> None:
    from engine.social import voicing

    assert voicing.raised_followup([words], {"about": about}) is raised


def test_a_fallback_raises_the_followup_with_its_own_line(receipts_state, matched) -> None:
    """With no model the fallback asks about it (an `any:` `followup.<mode>` line), and so closes it."""
    from engine.social import memory, voicing

    thread = matched("matchstick")
    pid = thread.split(":")[1]
    oid = _with_followup(receipts_state, thread)
    snap = _only_due(receipts_state, thread, followup_id=oid)
    reply = voicing.fallback_reply(snap, "no model")
    assert "your interview" in reply.bubbles[0] and reply.followup_raised == oid
    plain = voicing.fallback_reply(_only_due(receipts_state, thread), "no model")
    assert plain.followup_raised == ""
    assert oid in [r["id"] for r in memory.person(receipts_state, pid)["open"]]


# -- the fallback's facts (§13.1) -------------------------------------------------------------------


def test_a_sign_off_fallback_says_its_reason_in_their_words(receipts_state, matched) -> None:
    from engine.game.effects import apply_effect
    from engine.social import voicing

    thread = matched("matchstick")
    pid = thread.split(":")[1]
    _open_episode(receipts_state, pid, thread)
    apply_effect(receipts_state, {"type": "social_episode", "op": "end", "pid": pid, "end": "signed_off",
                                  "reason": "you're up early tomorrow", "reason_key": "early",
                                  "at": receipts_state.world_clock_hours})
    snap = _only_due(receipts_state, thread, end="sign_off", reason="you're up early tomorrow", mode="chatting",
                     max_bubbles=4)
    said = voicing.texter_prompt().reasons["early"]
    lines = [voicing.fallback_reply(dataclasses.replace(snap, seed=seed), "no model").bubbles[0]
             for seed in range(40)]
    assert any(said in line for line in lines)
    assert not any("{" in line or "you're up early" in line for line in lines)


def test_a_retired_situation_still_voices(receipts_state, matched) -> None:
    """A v0.22 save's message due as `good_morning` or `reveal_turn` is voiced by its successor row, never a
    content fault."""
    from engine.social import voicing

    thread = matched("matchstick")
    for old, new in voicing.RETIRED_ROWS:
        snap = _only_due(receipts_state, thread, situation=old)
        now = _block(_user(voicing.messages(snap)), "RIGHT NOW")
        assert now.endswith(f"SITUATION: {voicing.texter_prompt().instructions[new]}")
        assert not voicing.voice(snap, StubVoice("zero")).fallback


def test_situation_faults_ask_for_the_end_rows(receipts_active) -> None:
    from engine.social import voicing

    prompt = voicing.texter_prompt()
    thin = voicing.TexterPrompt(prompt.persona, {k: v for k, v in prompt.instructions.items()
                                                 if k not in ("sign_off", "opens_up")}, {})
    keys = [key for key, _ in voicing.situation_faults(thin, {})]
    assert "SITUATIONS.sign_off" in keys and "SITUATIONS.opens_up" in keys
    with pytest.raises(ValueError, match=r"names \{mood\}"):
        voicing.parse_texter("Persona.\n\n## Instructions\n\n- `reply`: Answer {mood}.\n\n## Fallbacks\n\n"
                             "```yaml\nany:\n  reply.quick: [\"x\"]\n```\n")
    with pytest.raises(ValueError, match=r"fallbacks.any.reply.slow"):
        voicing.parse_texter("Persona.\n\n## Instructions\n\n- `reply`: Answer.\n\n## Fallbacks\n\n"
                             "```yaml\nany:\n  reply.slow: [\"x\"]\n```\n")


# -- opening up (growth.reveal, spec §6.4) -----------------------------------------------------------


def _reveal_due(state, pid: str) -> str:
    from engine.game.effects import apply_effect
    from engine.social import growth

    _set_person(state, pid, warmth=99, trust=99, episodes_done=2)
    apply_effect(state, {"type": "social_growth", "op": "gain", "pid": pid, "amount": 100})
    due = growth.record(state, pid)["reveal_due"]
    assert due.startswith("l_"), "the step queued no layer: the fixture proves nothing"
    return due


def test_a_reply_opens_up_on_its_layer_and_the_commit_reveals_it(receipts_state, matched) -> None:
    from engine.social import growth, voicing
    from tests.social_fixtures import _voice_all

    thread = matched("matchstick")
    pid = thread.split(":")[1]
    due = _reveal_due(receipts_state, pid)
    snap = _only_due(receipts_state, thread)
    assert snap.reveal["id"] == due
    now = _block(_user(voicing.messages(snap)), "RIGHT NOW")
    assert "OPENING UP:" in now and snap.reveal["text"] in now
    ending = _only_due(receipts_state, thread, end="sign_off", reason="you're about to head out")
    assert ending.reveal == {}                                          # never while they are going
    plain = _only_due(receipts_state, thread)
    schema = voicing.reply_schema(voicing._decision(plain), plain.proposals, ("neutral",),
                                  opened_up=bool(plain.reveal))
    assert schema["properties"]["opened_up"]["type"] == "boolean" and "opened_up" in schema["required"]
    # Said it, but the reply's `opened_up` says no: not recorded (review M7: a stated fact, never assumed).
    _voice_all(receipts_state, StubVoice("warm", script=[_reply("can I tell you something", opened_up=False)]))
    assert growth.record(receipts_state, pid)["reveal_due"] == due
    _only_due(receipts_state, thread)
    _voice_all(receipts_state, StubVoice("warm", script=[_reply("can I tell you something", opened_up=True)]))
    rec = growth.record(receipts_state, pid)
    assert rec["revealed"] == [due] and rec["reveal_due"] == ""


def test_an_ungrammared_reply_reveals_only_when_its_words_carry_the_layer(receipts_state, matched) -> None:
    """With no `opened_up` key (a rung-3 reply) the words decide: the layer's own words, two key words or one
    of six letters or more -- never a reply that only says "tell me more"."""
    from engine.social import growth
    from tests.social_fixtures import _voice_all

    thread = matched("matchstick")
    pid = thread.split(":")[1]
    due = _reveal_due(receipts_state, pid)
    snap = _only_due(receipts_state, thread)
    _voice_all(receipts_state, StubVoice("warm"))                          # "that sounds lovely, tell me more"
    assert growth.record(receipts_state, pid)["reveal_due"] == due
    _only_due(receipts_state, thread)
    _voice_all(receipts_state, StubVoice("zero", script=[_reply(f"honestly? {snap.reveal['text']}")]))
    assert growth.record(receipts_state, pid)["revealed"] == [due]



def test_a_fallback_reveals_nothing(receipts_state, matched) -> None:
    from engine.social import growth
    from tests.social_fixtures import _voice_all

    thread = matched("matchstick")
    pid = thread.split(":")[1]
    due = _reveal_due(receipts_state, pid)
    _only_due(receipts_state, thread)
    _voice_all(receipts_state, StubVoice("zero", fail=2))             # both attempts unparsed: the fallback
    assert growth.record(receipts_state, pid)["reveal_due"] == due


# -- agreement (§13.4) -------------------------------------------------------------------------------


def test_commitment_claimed_passes_a_step_that_holds_and_one_negated(receipts_state, matched) -> None:
    from engine.social import agreement
    from engine.social.kinds import Decision
    from tests.social_fixtures import _force_stage

    pid = matched("matchstick").split(":")[1]
    asked = {"bubbles": [{"text": "will you marry me?"}]}
    view = agreement.view_from_state(receipts_state, pid)
    assert "commitment_claimed" in [f.check for f in agreement.check(asked, Decision("reply"), view)]
    negated = {"bubbles": [{"text": "I'm not saying let's move in together, relax"}]}
    assert "commitment_claimed" not in [f.check for f in agreement.check(negated, Decision("reply"), view)]
    _force_stage(receipts_state, pid, "engaged")
    held = agreement.view_from_state(receipts_state, pid)
    assert "propose" in held.willing and "move_in" not in held.willing     # m6 (T18): moving in is the household
    assert "commitment_claimed" not in [f.check for f in agreement.check(asked, Decision("reply"), held)]
    from engine.game.effects import apply_effect

    assert apply_effect(receipts_state, {"type": "social_household", "op": "move_in", "pid": pid})["ok"]
    assert "move_in" in agreement.view_from_state(receipts_state, pid).willing


def test_promise_claimed_holds_the_proposal_and_the_archetype(receipts_state, matched) -> None:
    from engine.social import agreement
    from engine.social.kinds import Decision

    pid = matched("matchstick").split(":")[1]
    view = dataclasses.replace(agreement.view_from_state(receipts_state, pid), makes_promises=True)
    words = {"bubbles": [{"text": "I'll text you tonight"}]}
    assert "promise_claimed" not in [f.check for f in agreement.check(words, Decision("reply"), view)]
    mismatch = {**words, "promise": [{"window": "morning", "about": ""}]}
    assert "promise_claimed" in [f.check for f in agreement.check(mismatch, Decision("reply", end="sign_off"), view)]
    none_made = dataclasses.replace(view, makes_promises=False)
    assert "promise_claimed" in [f.check for f in agreement.check(words, Decision("reply"), none_made)]
