"""
READ RECEIPTS: memory and context (v0.22.0 T12, spec §12).

Canon and knows per person (no fact crosses threads), the thread summary
over `summarizer.summarize_with` (its prompt exactly its blocks; the ledger's
`summarize` byte-identical to v0.21.1), the deterministic fallback, the
summary's reach into the archive after a spill, the names the player told a
person kept past the spill, the production summary function's one-argument
shape on the utility profile, the hosted busy-lane fallback, and the voice
prompt's budget on a 40-person save at day 90.

The day-90 save is built once per module by ``build_day90`` in this file,
through the effects (never by the simulator), and handed to the budget test
(the controller's ruling on T12's review: no committed fixture file).
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from tests.social_fixtures import (  # noqa: F401
    _force_stage, _live_session, _matched_in, _with, matched, receipts_active, receipts_state,
)


#: The texter profile's reply cap (spec §11.4), reserved out of the 4096 window.
TEXTER_MAX_TOKENS = 360

#: v0.21.1's summarizer request for `_ledger()` and `_turns()`, written out by hand
#: (pre-flight F18): never rebuilt from SUMMARIZER_PROMPT or _render_turns.
EXPECTED_V0221_MESSAGES = [
    {
        "role": "system",
        "content": (
            "You maintain the running memory of a dark-fantasy RPG session.\n"
            "\n"
            "Rewrite the summary below so it also covers the new events. Rules:\n"
            "- At most 250 words. Prose, past tense, third person (\"the traveller\").\n"
            "- Keep EVERY proper noun: people, places, objects with names.\n"
            "- Keep every unresolved promise, debt, threat, and open question.\n"
            "- Keep what changed about the world, not what the weather was like.\n"
            "- Drop moment-to-moment detail. Compress old material harder than new.\n"
            "- Output only the summary. No preamble, no headings, no commentary.\n"
        ),
    },
    {
        "role": "user",
        "content": (
            "CURRENT SUMMARY:\n"
            "The traveller woke in the clearing.\n"
            "\n"
            "NEW EVENTS:\n"
            "[day 1, forest_clearing]\n"
            "The traveller: I follow the path east.\n"
            "The path east narrows between birches. A clock ticks ahead.\n"
            "[day 2, edgewood_square]\n"
            "The traveller: I ask the baker about the clock.\n"
            "(persuasion: success)"
        ),
    },
]


def _ledger():
    from engine.memory.ledger import StoryLedger

    ledger = StoryLedger()
    ledger.summary = "The traveller woke in the clearing."
    return ledger


def _turns():
    from engine.memory.ledger import TurnRecord

    return [
        TurnRecord(turn=1, day=1, location_id="forest_clearing", player_action="I follow the path east.",
                   narration="The path east narrows between birches. A clock ticks ahead."),
        TurnRecord(turn=2, day=2, location_id="edgewood_square", player_action="I ask the baker about the clock.",
                   narration="", outcomes=["persuasion: success"]),
    ]


def _msg(sender: str, text: str, at: float, n: int = 1, *, thread: str = "natter:p0001") -> dict[str, Any]:
    return {"id": f"m{n}", "thread_id": thread, "from": sender, "kind": "text", "at": at, "bubbles": [text],
            "voiced": True, "decision": None, "media_id": None, "read_at": None, "transcript": None}


# -- the prompt and the summarizer ------------------------------------------------------------------


def test_the_summary_prompt_is_exactly_its_blocks(receipts_active) -> None:
    from engine import social
    from engine.social import memory

    text = (social.social_dir().parent.parent / "prompts" / "thread_summary.md").read_text(encoding="utf-8")
    messages = memory.summary_messages("they like climbing", [_msg("player", "hi", 21.25)], {"p0001": "Kai"})
    assert [m["role"] for m in messages] == ["system", "user"]
    assert messages[0]["content"] == text
    user = messages[1]["content"]
    assert user.startswith("CURRENT SUMMARY:\nthey like climbing\n\nNEW MESSAGES:\n")
    assert user.count("\n\n") == 1                                  # exactly the two user blocks
    assert user.endswith("Mon 21:15 you: hi")


def test_summarize_thread_sends_exactly_the_summary_messages(receipts_active) -> None:
    """The call `summarize_thread` makes IS `summary_messages`'s (one construction, two readers)."""
    from engine.social import memory

    overflow = [_msg("player", "hi there", 21.25, 1), _msg("p0001", "hey! long day?", 21.5, 2)]
    seen: list = []
    text, used = memory.summarize_thread({"summary": "", "overflow": overflow, "names": {"p0001": "Kai"}},
                                         lambda m: seen.append(m) or "They said hello.")
    assert (text, used) == ("They said hello.", True)
    assert seen == [memory.summary_messages("", overflow, {"p0001": "Kai"})]
    assert "Mon 21:30 Kai: hey! long day?" in seen[0][1]["content"]


def test_a_long_model_summary_keeps_its_end(receipts_active) -> None:
    """Review M3: the cap is applied to the raw reply, losing its oldest words -- not a middle slice."""
    from engine.social import memory

    reply = " ".join(f"w{i}" for i in range(400))
    text, used = memory.summarize_thread({"summary": "", "overflow": [_msg("player", "hi", 21.0)], "names": {}},
                                         lambda m: reply)
    assert used and text.split() == [f"w{i}" for i in range(220, 400)]


def test_summarize_is_byte_identical_for_the_ledger(monkeypatch) -> None:
    from engine.memory import summarizer

    seen: list = []
    summarizer.summarize(_ledger(), _turns(), llm_fn=lambda m: seen.append(m) or "ok")
    assert seen[0] == EXPECTED_V0221_MESSAGES   # a LITERAL (F18): never rebuilt from SUMMARIZER_PROMPT or _render_turns


def test_summarize_keeps_its_cap_and_fallbacks() -> None:
    """`summarize`'s behaviour after `used_llm` is v0.21.1's: a model's text cut at 1.3x the cap, the
    fallback on "" or a raise, the ledger's watermark moved either way."""
    from engine.memory import summarizer

    ledger = _ledger()
    out = summarizer.summarize(ledger, _turns(), llm_fn=lambda m: "word " * 400, max_words=100)
    assert len(out.split()) == 130 and ledger.summary_through_turn == 2
    ledger = _ledger()
    out = summarizer.summarize(ledger, _turns(), llm_fn=lambda m: "")
    assert "The path east narrows between birches" in out and ledger.summary_through_turn == 2

    def boom(_m):
        raise RuntimeError("down")

    assert summarizer.summarize(_ledger(), _turns(), llm_fn=boom) == out


def test_the_summary_prompt_states_the_configured_word_cap(receipts_active) -> None:
    from engine import social
    from engine.social import memory

    words = int(social.setting("memory.summary_words", 0))
    assert words == 180
    assert f"at most {words} words" in memory.summary_prompt()


# -- canon, knows, told ---------------------------------------------------------------------------


def test_no_fact_crosses_threads(receipts_state, matched) -> None:
    from engine.social import memory

    a = matched("matchstick").split(":")[1]
    b = matched("front_porch").split(":")[1]
    memory.add_knows(receipts_state, a, ["works nights at the hospital"])
    assert receipts_state.social["people"][b].get("knows", []) == []
    memory.add_canon(receipts_state, a, ["grew up by the harbour"])
    assert receipts_state.social["people"][b].get("canon", []) == []
    assert receipts_state.social["people"][a]["knows"] == ["works nights at the hospital"]


def test_canon_and_knows_are_bounded(receipts_state, matched, monkeypatch) -> None:
    from engine import social
    from engine.social import memory

    assert int(social.setting("canon_max", 0)) == 40 and int(social.setting("knows_max", 0)) == 30
    tid = matched("matchstick")
    pid = tid.split(":")[1]
    person = receipts_state.social["people"][pid]
    rev = int(person.get("rev", 0))
    facts = [f"canon fact number {i:02d}" for i in range(50)]
    for i in range(0, 50, 2):                                         # two a reply, as voiced replies bring them
        memory.add_canon(receipts_state, pid, facts[i:i + 2])
    assert person["canon"] == facts[10:]
    summary = receipts_state.social["threads"][tid]["summary"]
    for fact in facts[:10]:
        assert fact in summary, fact                                  # the oldest 10 folded, not lost
    assert int(person["rev"]) > rev

    learned = [f"the player said thing {i:02d}" for i in range(35)]
    memory.add_knows(receipts_state, pid, learned)
    assert person["knows"] == learned[5:]                             # the newest 30
    memory.add_knows(receipts_state, pid, [learned[-1].upper()])       # said again: not a second row
    assert person["knows"] == learned[5:]


def test_a_memory_write_goes_through_social_memory(receipts_state, matched) -> None:
    from engine.game.effects import apply_effect
    from engine.social import kinds, memory

    pid = matched("matchstick").split(":")[1]
    with kinds.collecting() as applied:
        memory.add_canon(receipts_state, pid, ["has a dog called Biscuit"])
    assert [r["type"] for r in applied] == ["social_memory"]
    assert apply_effect(receipts_state, {"type": "social_memory", "op": "forget", "pid": pid})["ok"] is False


def test_a_name_the_player_told_survives_the_spill(receipts_state, matched) -> None:
    """T11's carry: `told` once read only messages in state; the archive no longer makes them forget."""
    from engine.game.effects import apply_effect
    from engine.social import agreement, messaging, population

    a_tid = matched("matchstick")
    b_tid = matched("front_porch")
    a = a_tid.split(":")[1]
    b_name = population.profile(receipts_state, b_tid.split(":")[1]).name
    messaging.new_message(receipts_state, a_tid, "player", "text", bubbles=[f"my mate {b_name} says hi"])
    messaging.new_message(receipts_state, a_tid, "player", "text", bubbles=["anyway how was work"])
    assert b_name in agreement.view_from_state(receipts_state, a).told
    t = receipts_state.social["threads"][a_tid]
    count = next(i for i, m in enumerate(t["messages"]) if m["from"] == "player") + 1
    assert apply_effect(receipts_state, {"type": "social_message", "op": "archive", "thread_id": a_tid,
                                         "count": count})["ok"]
    assert not any(b_name in " ".join(m["bubbles"]) for m in t["messages"])   # the words have left state
    assert receipts_state.social["people"][a]["told"] == [b_name]
    assert b_name in agreement.view_from_state(receipts_state, a).told


def test_an_arc_reveal_names_a_canon_row_or_fails_at_load(tmp_path, monkeypatch) -> None:
    import shutil

    import yaml

    from engine import social

    src = Path(__file__).resolve().parents[1] / "games" / "read-receipts" / "data" / "social"
    shutil.copytree(src, tmp_path / "social")
    path = tmp_path / "social" / "behaviours.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    del data["canon"]["wants_something_else"]
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    monkeypatch.setattr(social, "social_dir", lambda: tmp_path / "social")
    monkeypatch.setattr(social, "_DATA_CACHE", None)
    with pytest.raises(ValueError, match=r"behaviours.yaml: arcs.turner_wants_different.beat.reveal"):
        social.load_all()
    assert social._DATA_CACHE is None


def test_every_shipped_reveal_is_a_canon_row_of_prose(receipts_active) -> None:
    from engine import social
    from engine.social import behaviour

    rows = behaviour.check_canon(social.data("behaviours"))
    reveals = [((spec.get("beat") or {}).get("reveal")) for spec in social.data("behaviours")["arcs"].values()]
    assert [r for r in reveals if r] and all(r in rows for r in reveals if r)
    assert all(0 < len(text) <= behaviour.CANON_TEXT_MAX for text in rows.values())


def test_a_memory_write_for_a_person_with_no_row_is_refused(receipts_state) -> None:
    from engine.game.effects import apply_effect

    for op, extra in (("canon", {"facts": ["x"]}), ("knows", {"facts": ["x"]}), ("told", {"names": ["Kai"]})):
        result = apply_effect(receipts_state, {"type": "social_memory", "op": op, "pid": "p9999", **extra})
        assert result["ok"] is False and "no person p9999" in result["text"]
    assert "p9999" not in receipts_state.social["people"]


def test_a_missing_summary_prompt_is_warned_once(receipts_active, monkeypatch, tmp_path, caplog) -> None:
    import logging

    from engine import social
    from engine.social import memory

    (tmp_path / "story" / "data" / "social").mkdir(parents=True)
    monkeypatch.setattr(social, "social_dir", lambda: tmp_path / "story" / "data" / "social")
    monkeypatch.setattr(memory, "_PROMPT_MISSING_LOGGED", set())
    with caplog.at_level(logging.WARNING, logger="engine.social.memory"):
        assert memory.summary_prompt() == "" and memory.summary_prompt() == ""
    assert sum("no thread summary prompt" in r.getMessage() for r in caplog.records) == 1


# -- the thread summary -----------------------------------------------------------------------------


def test_the_thread_fallback_is_deterministic_and_within_180_words(receipts_active) -> None:
    from engine.social import memory

    long = ("so I finally went to that climbing gym by the docks and honestly my arms are jelly now but it was "
            "worth it, the instructor was great")
    messages = [_msg("player" if i % 2 else "p0001", f"{i}: {long}", 20.0 + i / 4, i + 1) for i in range(200)]
    first = memory.fallback_thread_summary("They met on Matchstick.", messages)
    assert first == memory.fallback_thread_summary("They met on Matchstick.", messages)
    assert 0 < len(first.split()) <= 180
    assert "199: so I finally" in first                              # the newest kept, the oldest lost
    assert "They met on Matchstick." not in first
    folded = memory.fallback_thread_summary("They met.\nEarlier they shared: has a dog called Biscuit.", messages)
    assert folded.startswith("Earlier they shared: has a dog called Biscuit.\n")   # canon outlives the chatter
    assert len(folded.split()) <= 180 and "199: so I finally" in folded
    short = memory.fallback_thread_summary("They met on Matchstick.", messages[:2])
    assert short.startswith("They met on Matchstick. Mon 20:00 them: 0: so I finally")


def test_a_spilled_message_reaches_the_summary_input(receipts_active, monkeypatch) -> None:
    """T10's carry: the summary pass reads phone_archive.jsonl for messages the spill took past it."""
    from engine import social
    from engine.social import archive, memory, messaging

    monkeypatch.setattr(social, "setting", _with(social.setting, state_messages=3, **{"memory.verbatim": 2}))
    monkeypatch.setattr(messaging, "schedule_reply", lambda *a, **k: None)
    _scene, session = _live_session()
    state = session.engine.state
    tid = _matched_in(session, "matchstick")
    with session.lock:
        for i in range(8):
            messaging.new_message(state, tid, "player", "text", bubbles=[f"spill-word-{i}"])
        assert archive.spill(session) == 5
        directory = archive.save_dir(session)
        blind = memory.thread_view(state, tid)          # under the lock: state only, no file read
    assert blind["needs_archive"] and blind["overflow"] == []   # nothing to commit past unread messages
    view = memory.with_archive(blind, directory)        # off the lock: the archive's part
    said = [" ".join(m["bubbles"]) for m in view["overflow"]]
    assert "spill-word-0" in said and "spill-word-5" in said and "spill-word-7" not in said
    seen: list = []
    text, used = memory.summarize_thread(view, lambda m: seen.append(m) or "You wrote eight times.")
    assert used and "spill-word-0" in seen[0][1]["content"]
    with session.lock:
        assert memory.commit_summary(state, view, text)["ok"]
        again = memory.thread_view(state, tid)
    assert not again["needs_archive"] and again["overflow"] == []
    assert state.social["threads"][tid]["summary_through"] == view["through"]


def test_a_missing_archive_never_moves_the_summary_past_unread_messages(receipts_active, monkeypatch) -> None:
    """Review I1: the archive gone after a spill -- the overflow stays empty and the watermark stays put."""
    from engine import social
    from engine.social import archive, memory, messaging

    monkeypatch.setattr(social, "setting", _with(social.setting, state_messages=3, **{"memory.verbatim": 2}))
    monkeypatch.setattr(messaging, "schedule_reply", lambda *a, **k: None)
    _scene, session = _live_session()
    state = session.engine.state
    tid = _matched_in(session, "matchstick")
    with session.lock:
        for i in range(8):
            messaging.new_message(state, tid, "player", "text", bubbles=[f"lost-word-{i}"])
        assert archive.spill(session) == 5
        directory = archive.save_dir(session)
        before = state.social["threads"][tid]["summary_through"]
        view = memory.thread_view(state, tid)
    (directory / archive.ARCHIVE_FILE).unlink()
    view = memory.with_archive(view, directory)
    assert view["overflow"] == [] and view["through"] == before
    text, used = memory.summarize_thread(view, lambda m: "never asked")
    assert (text, used) == (view["summary"], False)
    with session.lock:
        refused = memory.commit_summary(state, view, text)
    assert refused["ok"] is False
    assert state.social["threads"][tid]["summary_through"] == before
    assert memory.with_archive(memory.thread_view(state, tid), None)["overflow"] == []   # no directory: the same


def test_the_archive_is_read_from_its_end_across_blocks_and_crash_duplicates(receipts_active, monkeypatch,
                                                                             tmp_path) -> None:
    from engine.social import archive

    monkeypatch.setattr(archive, "TAIL_BLOCK", 64)                     # every row straddles a block
    rows = [{"id": f"m{n}", "thread_id": "natter:p0001" if n % 2 else "natter:p0002", "bubbles": [f"r{n}"]}
            for n in range(1, 41)]
    rows += rows[-6:]                                                   # a crash re-appends the newest batch
    lines = [json.dumps(r) for r in rows]
    lines.insert(10, "{torn")
    (tmp_path / archive.ARCHIVE_FILE).write_text("\n".join(lines) + "\n", encoding="utf-8")
    got = archive.archived_after(tmp_path, "natter:p0001", 31)
    assert sorted({r["id"] for r in got}, key=lambda i: int(i[1:])) == ["m33", "m35", "m37", "m39"]
    assert [r["id"] for r in archive.archived_after(tmp_path, "natter:p0001", 0)][:3] == ["m1", "m3", "m5"]
    assert archive.archived_after(tmp_path / "nowhere", "natter:p0001", 0) is None


def test_a_stale_summary_is_refused_at_commit(receipts_state, matched, monkeypatch) -> None:
    """A summary written over a snapshot does not overwrite a summary that moved meanwhile (a canon fold)."""
    from engine import social
    from engine.social import memory, messaging

    monkeypatch.setattr(social, "setting", _with(social.setting, canon_max=1, **{"memory.verbatim": 1}))
    tid = matched("matchstick")
    pid = tid.split(":")[1]
    for i in range(3):
        messaging.new_message(receipts_state, tid, "player", "text", bubbles=[f"line {i}"])
    view = memory.thread_view(receipts_state, tid)
    assert view["overflow"]
    memory.add_canon(receipts_state, pid, ["loves sea swimming", "has two sisters"])   # one folded
    refused = memory.commit_summary(receipts_state, view, "a summary over the old one")
    assert refused["ok"] is False and "stale" in refused["text"]
    assert "loves sea swimming" in receipts_state.social["threads"][tid]["summary"]


def test_a_hosted_summary_under_a_busy_utility_lane_takes_the_fallback(receipts_active, monkeypatch, tmp_path) -> None:
    from engine.config import hosting_enabled, reset_config
    from engine.llm import backend as backend_mod
    from engine.llm import gate
    from engine.social import memory
    from tests.hosted_app import hosting_layer

    hosting_layer(monkeypatch, tmp_path)
    try:
        reset_config()
        assert hosting_enabled()
        lanes: list[str] = []

        def busy(lane, timeout, label, account="", cancel=None):
            lanes.append(lane)
            raise gate.InferenceBusy(f"Inference busy: {label}")

        monkeypatch.setattr(gate, "_acquire", busy)
        real = backend_mod.LMStudioBackend()
        monkeypatch.setattr(real, "server_available", lambda: True)
        monkeypatch.setattr(real, "use_native", lambda **_k: False)
        monkeypatch.setattr(backend_mod, "get_backend", lambda: real)
        view = {"summary": "They matched.", "overflow": [_msg("player", "free on friday?", 30.0)],
                "names": {"p0001": "Kai"}}
        text, used = memory.summarize_thread(view, memory.production_summary_fn())
        assert used is False
        assert text == memory.fallback_thread_summary("They matched.", view["overflow"])
        assert lanes == ["utility"]                                    # the small profile's lane, asked and busy
    finally:
        monkeypatch.undo()
        reset_config()


def test_the_production_summary_fn_takes_one_argument_on_the_utility_profile(receipts_active, monkeypatch) -> None:
    from engine.llm import backend as backend_mod
    from engine.llm.profiles import resolve_profile
    from engine.social import memory

    calls: list[dict[str, Any]] = []

    class Recorder:
        available = True

        def server_available(self) -> bool:
            return self.available

        def chat(self, messages, **kwargs):
            calls.append({"messages": messages, **kwargs})
            return SimpleNamespace(content="They planned Friday.", starved_by_reasoning=False, model="m")

    recorder = Recorder()
    monkeypatch.setattr(backend_mod, "get_backend", lambda: recorder)
    fn = memory.production_summary_fn()
    assert fn is not None and len(inspect.signature(fn).parameters) == 1
    request = [{"role": "user", "content": "x"}]
    assert fn(request) == "They planned Friday."
    assert calls[0]["messages"] == request
    assert calls[0]["profile"] == "small" and calls[0]["reasoning"] == "off"
    assert calls[0]["label"] == "social_summary"
    assert resolve_profile("small").lane == "utility"
    recorder.chat = lambda messages, **kw: SimpleNamespace(content="half a thought", starved_by_reasoning=True, model="m")
    assert fn(request) == ""                                           # starved: the fallback fires
    recorder.available = False
    assert memory.production_summary_fn() is None


# -- the budget (§12.4) ---------------------------------------------------------------------------


_CANON = [
    "grew up above a chip shop on the harbour and still can't stand the smell of vinegar on a cold morning",
    "has two older sisters who both moved to the city and call every Sunday to ask when she is visiting",
    "learnt to sail at fourteen on a borrowed dinghy and capsized it twice in the first summer out",
    "works the early shift and is usually awake by half five, coffee first and then the sea wall walk",
    "keeps a list of every gig they have been to since school, it is up to two hundred and eleven now",
]
_KNOWS = [
    "the player said they moved to Port Merrow last spring for a job at the library on Quay Street",
    "the player admitted they cannot cook anything but pasta and a very good cheese toastie at midnight",
    "the player's flatmate keeps a lizard called Gerald who lives on top of the fridge for the warmth",
    "the player runs on the beach at weekends when the tide is out and the sand is firm underfoot",
]
_LINES = [
    "haha no way, that is exactly what happened to me last week, I was mortified and the whole bus saw it",
    "honestly I could eat chips every day if nobody stopped me, the ones from the van on the front are the best",
    "are you around on saturday? there's a thing at the harbour with live music and I think you'd like it",
    "work was long, the new manager keeps changing the rota on us and nobody knows when they're on any more",
    "I'll send you the playlist later, it's mostly old soul stuff and a couple of things my dad used to play",
    "that sounds lovely, I haven't been out to the point in ages, we should walk it when the weather turns",
]


def build_day90(state) -> dict[str, Any]:
    """
    A 40-person save at day 90, made through the effects (never the
    simulator): each person a Natter thread at stage `dating`, 70 history
    rows (bounded and folded), 50 canon facts (40 kept, 10 folded), 35
    learned facts (30 kept), 60 messages from day 1 to day 90 folded into a
    summary by the deterministic fallback, the older ones archived. Returns
    the slice the budget test reads.
    """
    from engine.game.effects import apply_effect
    from engine.social import matching, memory, messaging, population, relationships

    out: dict[str, Any] = {"seed": state.rng_seed, "day": 90, "people": {}, "threads": {}}
    real = messaging.schedule_reply
    messaging.schedule_reply = lambda *a, **k: None
    try:
        for index in range(1, 41):
            pid = population.pid_for(index)
            tid = matching.thread_id("natter", pid)
            assert apply_effect(state, {"type": "social_message", "op": "open", "thread_id": tid})["ok"]
            _force_stage(state, pid, "dating")
            for row in range(70):
                relationships.add_history(state, pid, "moment", f"a small thing happened ({row})",
                                          at=float(row * 24 + 12))
            for i in range(0, 50, 2):
                memory.add_canon(state, pid, [f"{_CANON[(i + j + index) % 5]} ({i + j})" for j in (0, 1)])
            memory.add_knows(state, pid, [f"{_KNOWS[(i + index) % 4]} ({i})" for i in range(35)])
            for n in range(60):
                sender = "player" if n % 2 else pid
                bubbles = [_LINES[(n + k + index) % 6] for k in range(1 + (n % 3))]
                messaging.new_message(state, tid, sender, "text", bubbles=bubbles,
                                      at=float(n * 36 + 20 + (index % 3)))
            while (view := memory.thread_view(state, tid))["overflow"]:
                text, _used = memory.summarize_thread(view, None)
                assert memory.commit_summary(state, view, text)["ok"]
            t = state.social["threads"][tid]
            older, _tail = memory.split_tail(t["messages"], 24)
            assert apply_effect(state, {"type": "social_message", "op": "archive", "thread_id": tid,
                                        "count": len(older)})["ok"]
            person = state.social["people"][pid]
            assert len(person["history"]) == 60                     # bounded, the oldest folded
            out["people"][pid] = {"canon": person["canon"], "knows": person["knows"],
                                  "history": [{"day": r["day"], "text": r["text"]} for r in person["history"][-8:]]}
            out["threads"][tid] = {"pid": pid, "summary": t["summary"],
                                   "messages": [{k: m[k] for k in ("id", "from", "kind", "at", "bubbles")}
                                                for m in t["messages"]]}
    finally:
        messaging.schedule_reply = real
    return json.loads(json.dumps(out, default=str))


def _schema_text() -> str:
    """A stand-in for block 7 the size of §11.2's schema (T13 composes the real one and re-pins this budget)."""
    schema = {
        "type": "object", "additionalProperties": False,
        "required": ["bubbles", "regard", "learned", "shared", "proposals"],
        "properties": {
            "bubbles": {"type": "array", "minItems": 1, "maxItems": 3,
                        "items": {"type": "object", "additionalProperties": False, "required": ["text"],
                                  "properties": {"text": {"type": "string", "maxLength": 280}}}},
            "regard": {"type": "object", "additionalProperties": False, "required": ["warmth", "trust", "mood"],
                       "properties": {"warmth": {"type": "integer", "minimum": -4, "maximum": 4},
                                      "trust": {"type": "integer", "minimum": -2, "maximum": 2},
                                      "mood": {"enum": ["neutral", "fond", "playful", "tired", "annoyed", "hurt"]}}},
            "learned": {"type": "array", "maxItems": 2, "items": {"type": "string", "maxLength": 140}},
            "shared": {"type": "array", "maxItems": 2, "items": {"type": "string", "maxLength": 140}},
            "proposals": {"type": "array", "items": {"enum": ["offer_number", "ask_meet", "offer_photo",
                                                               "invite_game", "cool_off"]}},
        },
    }
    return "Reply with JSON only, in this shape:\n" + json.dumps(schema)


def _blocks(state, persona: str, pid: str, person: dict[str, Any], thread: dict[str, Any]) -> dict[str, str]:
    from engine.social import memory, population

    p = population.profile(state, pid)
    bio = " ".join(p.bio.values())
    prompts = " ".join(f"{q} {a}" for q, a in p.prompts)
    attributes = ", ".join(f"{k}: {v}" for k, v in p.attributes)
    tail_lines = memory.render_thread(thread["messages"], {pid: p.name}).split("\n")[-24:]
    return {
        "persona": persona,
        "who": (f"WHO YOU ARE\nYou are {p.name}, {p.age}, a {p.job} in {p.neighbourhood}. You like "
                f"{', '.join(p.hobbies)}. You are {', '.join(p.traits)}. You text {p.texting_style}. {attributes}. "
                f"{bio} {prompts}"),
        "canon": "\n".join(person.get("canon") or []),
        "where": f"WHERE YOU ARE WITH THEM\nDating; close; mood fond; you want {p.intent}.",
        "history": "\n".join(f"Day {r['day']}: {r['text']}" for r in (person.get("history") or [])[-8:]),
        "knows": "WHAT YOU KNOW ABOUT THEM\n" + "\n".join(person.get("knows") or []),
        "summary": thread.get("summary") or "",
        "verbatim": "\n".join(tail_lines),
        "now": ("RIGHT NOW\nIt is Sunday 21:40, day 90. You are free. They wrote 12 minutes ago and you have "
                "read it. SITUATION: Answer what they last said, the way you text."),
        "format": _schema_text(),
    }


@pytest.fixture(scope="module")
def day90() -> dict[str, Any]:
    """The 40-person save at day 90, built once for the module through the effects (`build_day90`)."""
    from engine import social
    from engine.game import procgen
    from engine.games import registry

    registry.activate("read-receipts")
    try:
        social.boot()
        from engine.social import population

        population.reset_profiles()
        return build_day90(procgen.new_game_state(player_name="Sam", seed=4242))
    finally:
        registry.deactivate()


def test_the_budget_fits_4096_with_a_40_person_save_at_day_90(receipts_active, day90) -> None:
    from engine import social
    from engine.game import procgen
    from engine.memory.budget import estimate_messages
    from engine.social import memory

    state = procgen.new_game_state(player_name="Sam", seed=int(day90["seed"]))
    assert day90["day"] == 90 and len(day90["people"]) == 40
    texter = (social.social_dir().parent.parent / "prompts" / "texter.md").read_text(encoding="utf-8")
    persona = texter.split("## Instructions")[0]
    window = 4096 - TEXTER_MAX_TOKENS
    over = 0
    for tid, thread in sorted(day90["threads"].items()):
        pid = thread["pid"]
        person = day90["people"][pid]
        assert len(person["canon"]) == 40 and len(person["knows"]) == 30
        full = _blocks(state, persona, pid, person, thread)
        assert len(full["verbatim"].split("\n")) == 24
        over += estimate_messages({"content": v} for v in full.values() if v) > window
        fitted = memory.budgeted(full, window)
        assert estimate_messages({"content": v} for v in fitted.values() if v) + TEXTER_MAX_TOKENS <= 4096, pid
        assert len(fitted["verbatim"].split("\n")) >= 12 and len(fitted["history"].split("\n")) >= 4, pid
        for key in ("persona", "who", "where", "knows", "now", "format"):
            assert fitted[key] == full[key]                            # blocks 1, 6, 7 (and 2-4's fixed parts) whole
        assert fitted["verbatim"] == "\n".join(full["verbatim"].split("\n")[-len(fitted["verbatim"].split("\n")):])
    assert over, "no person's prompt needed trimming: the fixture proves nothing"
