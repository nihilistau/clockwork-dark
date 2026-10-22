"""
READ RECEIPTS: person memory (v0.23.0 T6, spec §7.1-§7.3, §15.5, §19.4's continuity).

Memory is per PERSON, not per thread: the same `current` whichever app the
conversation moves to; a closed episode is recapped (the deterministic
fallback here: no model is ever called) into `episodes`, the oldest folding
into `story`; a stale recap is refused; follow-ups are carried while due
and closed when voiced; the thread summary is no longer written; the
archive takes `scene` rows.
"""

from __future__ import annotations

import json

import pytest

from tests.social_fixtures import (  # noqa: F401
    _act, _force_stage, _open_episode, _replies_forced, _voice_all, matched, matched_numbers,
    receipts_active, receipts_state,
)


def test_the_memory_is_identical_from_matchstick_and_natter(receipts_state, matched_numbers) -> None:
    """§19.4: per PERSON, across apps. Acceptance 3's engine half."""
    from engine.social import memory
    from tests.social_stub import StubVoice

    app_thread = matched_numbers("matchstick")
    pid = app_thread.split(":")[1]
    with _replies_forced():
        _open_episode(receipts_state, pid, app_thread)
        _act(receipts_state, "send", target=app_thread, args={"kind": "text"}, text="the climbing gym was packed")
        _voice_all(receipts_state, StubVoice("zero"))
        _act(receipts_state, "send", target=f"natter:{pid}", args={"kind": "text"}, text="moved us to natter!")
        _voice_all(receipts_state, StubVoice("zero"))
    mem = memory.person(receipts_state, pid)
    words = [b for m in mem["current"] for b in m["bubbles"]]
    assert "the climbing gym was packed" in words and "moved us to natter!" in words
    assert {m["thread_id"] for m in mem["current"]} == {app_thread, f"natter:{pid}"}
    assert any(m["from"] == pid for m in mem["current"])          # their replies too, from both apps


def test_the_voice_snapshot_reads_the_other_apps_conversation(receipts_state, matched_numbers) -> None:
    """The cross-app memory reaches the voice: a Natter reply's snapshot holds the Matchstick lines."""
    from engine.social import voicing
    from tests.social_stub import StubVoice

    app_thread = matched_numbers("matchstick")
    pid = app_thread.split(":")[1]
    with _replies_forced():
        _open_episode(receipts_state, pid, app_thread)
        _act(receipts_state, "send", target=app_thread, args={"kind": "text"}, text="the climbing gym was packed")
        _voice_all(receipts_state, StubVoice("zero"))
        _act(receipts_state, "send", target=f"natter:{pid}", args={"kind": "text"}, text="moved us to natter!")
    snap = voicing.snapshot_of(receipts_state, f"natter:{pid}")
    assert snap is not None
    lines = voicing._conversation_lines(snap)
    assert "the climbing gym was packed" in lines and "moved us to natter!" in lines
    assert snap.memory["current"] and snap.through_id.startswith("m")
    natter = [m["id"] for m in receipts_state.social["threads"][f"natter:{pid}"]["messages"]]
    assert snap.through_id in natter                              # the commit's watermark stays this thread's


def test_a_closed_episode_recaps_with_the_fallback_naming_topics_and_promise(receipts_state, matched, monkeypatch) -> None:
    from engine.game import clock
    from engine.social import convo, memory, promises, voicer  # noqa: F401
    from tests.social_stub import StubVoice

    thread = matched("matchstick")
    pid = thread.split(":")[1]
    with _replies_forced():
        _open_episode(receipts_state, pid, thread)
        topic = memory.topic_rows(receipts_state, pid)[0]
        _act(receipts_state, "send", target=thread, args={"kind": "text"}, text=f"tell me about {topic['label']}")
        promises.make(receipts_state, pid, by="person", window="morning")
    voicer.set_summary_fn(lambda messages: "")            # "" -> the deterministic fallback
    clock.advance_time(receipts_state, 1.0)               # the episode lapses
    _voice_all(receipts_state, StubVoice("zero"))
    recap = memory.person(receipts_state, pid)["episodes"][-1]["recap"]
    assert topic["label"] in recap and "morning" in recap
    assert memory.person(receipts_state, pid)["current"] == []
    assert memory.person(receipts_state, pid)["bridge"]
    assert not receipts_state.social["people"][pid].get("recap_due")   # consumed: the backlog stays bounded


def test_the_recap_fallback_says_why_it_ended(receipts_active) -> None:
    from engine.social import memory

    view = {"topic_rows": [{"id": "t1", "label": "their shifts"}, {"id": "t2", "label": "the climbing gym"}],
            "topics": ["t1", "t2"], "end_reason": "asleep",
            "promise_words": "they said they'd message you in the morning"}
    assert memory.recap_fallback(view) == ("You talked about their shifts and the climbing gym; they had to go "
                                           "to sleep; they said they'd message you in the morning.")
    assert memory.recap_fallback({"end_reason": "your shift starts at 9"}) == "they had to get to work."
    assert memory.recap_fallback({}) == "You talked for a while."


def test_a_model_recap_is_used_and_held_to_its_words(receipts_state, matched) -> None:
    """One utility call over episode_recap.md, its text kept, held to `memory.recap_words`."""
    from engine.game import clock
    from engine.social import memory, voicer
    from tests.social_stub import StubVoice

    thread = matched("matchstick")
    pid = thread.split(":")[1]
    calls: list = []
    with _replies_forced():
        _open_episode(receipts_state, pid, thread)
        _act(receipts_state, "send", target=thread, args={"kind": "text"}, text="how was the interview?")
    voicer.set_summary_fn(lambda messages: calls.append(messages) or ("word " * 200) + "You talked about work.")
    clock.advance_time(receipts_state, 1.0)
    _voice_all(receipts_state, StubVoice("zero"))
    assert len(calls) == 1
    system, user = calls[0]
    assert system["content"] == memory.recap_prompt() and "## The story so far" not in system["content"]
    assert user["content"].startswith("CURRENT SUMMARY:\n(nothing yet)\n\nTHIS CONVERSATION:\n")
    assert "you: how was the interview?" in user["content"]
    recap = memory.person(receipts_state, pid)["episodes"][-1]["recap"]
    assert len(recap.split()) == 70


def test_the_oldest_episode_folds_into_the_story(receipts_state, matched) -> None:
    from engine.game.effects import apply_effect
    from engine.social import memory

    pid = matched("matchstick").split(":")[1]
    for i in range(14):
        apply_effect(receipts_state, {"type": "social_memory", "op": "recap", "pid": pid,
                                      "row": {"id": f"e{i}", "kind": "chat", "recap": f"Episode {i} recap.",
                                              "topics": [], "end_reason": "lapsed"}})
    mem = memory.person(receipts_state, pid)
    assert len(mem["episodes"]) == 12 and "Episode 0 recap." in mem["story"]


def test_a_full_memory_folds_before_it_recaps(receipts_state, matched) -> None:
    """A recap due for a person whose episodes are full: the fold job first (its own job), then the recap."""
    from engine.game import clock
    from engine.social import memory, voicer
    from tests.social_stub import StubVoice

    thread = matched("matchstick")
    pid = thread.split(":")[1]
    for i in range(12):
        memory.add_recap(receipts_state, pid, {"id": f"x{i}", "recap": f"Old talk {i}.", "topics": []})
    calls: list = []
    voicer.set_summary_fn(lambda messages: calls.append(messages[0]["content"]) or "")
    with _replies_forced():
        _open_episode(receipts_state, pid, thread)
        _act(receipts_state, "send", target=thread, args={"kind": "text"}, text="hello again")
    clock.advance_time(receipts_state, 1.0)
    _voice_all(receipts_state, StubVoice("zero"))
    mem = memory.person(receipts_state, pid)
    assert calls == [memory.story_prompt(), memory.recap_prompt()]     # two jobs, one call each, fold first
    assert len(mem["episodes"]) == 12 and mem["episodes"][0]["id"] == "x1"
    assert "Old talk 0." in mem["story"] and mem["episodes"][-1]["id"].startswith("e")


def test_a_stale_recap_is_refused(receipts_state, matched) -> None:
    from engine.game import clock
    from engine.social import memory

    thread = matched("matchstick")
    pid = thread.split(":")[1]
    with _replies_forced():
        _open_episode(receipts_state, pid, thread)
        _act(receipts_state, "send", target=thread, args={"kind": "text"}, text="see you soon")
    clock.advance_time(receipts_state, 1.0)
    view = memory.recap_view(receipts_state, pid)
    assert view is not None
    assert memory.commit_recap(receipts_state, view, "First.")["ok"]
    before = memory.person(receipts_state, pid)
    refused = memory.commit_recap(receipts_state, view, "A second recap of the same episode.")
    assert refused["ok"] is False and "stale" in refused["text"]
    assert memory.person(receipts_state, pid) == before


def test_a_stale_fold_is_refused(receipts_state, matched) -> None:
    from engine.social import memory

    pid = matched("matchstick").split(":")[1]
    for i in range(12):
        memory.add_recap(receipts_state, pid, {"id": f"x{i}", "recap": f"Talk {i}.", "topics": []})
    view = memory.fold_view(receipts_state, pid)
    assert view is not None and view["episode"]["id"] == "x0"
    memory.add_canon(receipts_state, pid, [f"fact {i}" for i in range(41)])   # one canon fact folds: the story moved
    refused = memory.commit_fold(receipts_state, view, "A story.")
    assert refused["ok"] is False and "stale" in refused["text"]
    assert memory.person(receipts_state, pid)["episodes"][0]["id"] == "x0"


def test_a_recap_reads_the_messages_the_spill_took(receipts_active, monkeypatch) -> None:
    """The recap's view off the lock reads phone_archive.jsonl for the episode's older messages."""
    from engine import social
    from engine.game.effects import apply_effect
    from engine.social import archive, memory, messaging
    from tests.social_fixtures import _live_session, _matched_in, _with

    monkeypatch.setattr(social, "setting", _with(social.setting, state_messages=3, closed_thread_tail=3, **{"memory.verbatim": 2}))
    monkeypatch.setattr(messaging.convo, "on_player_send", lambda *a, **k: None)
    _scene, session = _live_session()
    state = session.engine.state
    tid = _matched_in(session, "matchstick")
    pid = tid.split(":")[1]
    with session.lock:
        start = state.world_clock_hours - 1.0           # the episode began before these messages
        for i in range(8):
            messaging.new_message(state, tid, "player", "text", bubbles=[f"spill-word-{i}"])
        assert archive.spill(session) == 5
        person = state.social["people"][pid]
        person["recap_due"] = [{"id": "e99", "kind": "chat", "thread_id": tid, "started_at": start,
                                "last_at": state.world_clock_hours, "closed_at": state.world_clock_hours,
                                "topics": [], "end_reason": ""}]
        blind = memory.recap_view(state, pid)                   # under the lock: state and memory only
        directory = archive.save_dir(session)
    assert blind["needs_archive"]
    words = [b for m in blind["items"] for b in m["bubbles"]]
    assert "spill-word-0" not in words                          # gone from state, and from current's 2 bubbles
    view = memory.with_archive(blind, directory)                # off the lock
    words = [b for m in view["items"] for b in m["bubbles"]]
    assert all(f"spill-word-{i}" in words for i in range(8))
    seen: list = []
    text, used = memory.write_recap(view, lambda m: seen.append(m) or "You wrote eight times.")
    assert used and "spill-word-0" in seen[0][1]["content"]
    with session.lock:
        assert memory.commit_recap(state, view, text)["ok"]
        assert apply_effect(state, {"type": "social_memory", "op": "spoken", "pid": pid, "message": {}})["ok"] is False


def test_the_thread_summary_is_no_longer_written(receipts_state, matched) -> None:
    from tests.social_stub import StubVoice

    thread = matched("matchstick")
    for i in range(60):
        _act(receipts_state, "send", target=thread, args={"kind": "text"}, text=f"line {i}")
    _voice_all(receipts_state, StubVoice("zero"))
    assert not receipts_state.social["threads"][thread].get("summary")
    assert "summary_through" not in receipts_state.social["threads"][thread]


def test_current_is_bounded_in_bubbles(receipts_state, matched) -> None:
    from engine import social
    from engine.social import memory, messaging

    thread = matched("matchstick")
    pid = thread.split(":")[1]
    for i in range(30):
        messaging.new_message(receipts_state, thread, "player", "text", bubbles=[f"a{i}", f"b{i}"])
    current = memory.person(receipts_state, pid)["current"]
    limit = int(social.setting("memory.verbatim", 0))
    assert limit == 40 and sum(len(m["bubbles"]) for m in current) == limit
    assert current[-1]["bubbles"] == ["a29", "b29"]


# -- follow-ups (§7.3) ---------------------------------------------------------------------------------


def test_a_followup_is_carried_when_due_and_closed_when_voiced(receipts_state, matched) -> None:
    from engine.social import convo, memory  # noqa: F401
    from tests.social_stub import StubVoice

    thread = matched("matchstick")
    pid = thread.split(":")[1]
    memory.add_open(receipts_state, pid, {"kind": "followup", "about": "their interview",
                                          "due_at": receipts_state.world_clock_hours, "by": "person"})
    with _replies_forced():
        _open_episode(receipts_state, pid, thread)
        _act(receipts_state, "send", target=thread, args={"kind": "text"}, text="hi")
    due = next(m for m in receipts_state.social["threads"][thread]["messages"] if m["voiced"] is False)
    assert due["decision"]["followup_id"]
    # Closed only when the reply raised it (v0.23.0 T7, T6 review M3): "how did the interview go" does.
    raised = json.dumps({"bubbles": [{"text": "wait, how did the interview go?"}],
                         "regard": {"warmth": 0, "trust": 0, "mood": "neutral"}, "learned": [], "shared": []})
    _voice_all(receipts_state, StubVoice("zero", script=[raised]))
    assert memory.person(receipts_state, pid)["open"] == []


def test_a_followup_not_yet_due_is_not_carried(receipts_state, matched) -> None:
    from engine.social import memory

    thread = matched("matchstick")
    pid = thread.split(":")[1]
    memory.add_open(receipts_state, pid, {"kind": "followup", "about": "their interview",
                                          "due_at": receipts_state.world_clock_hours + 24, "by": "person"})
    with _replies_forced():
        _open_episode(receipts_state, pid, thread)
        _act(receipts_state, "send", target=thread, args={"kind": "text"}, text="hi")
    due = next(m for m in receipts_state.social["threads"][thread]["messages"] if m["voiced"] is False)
    assert due["decision"]["followup_id"] == ""


def test_open_rows_are_bounded_the_oldest_closed_first(receipts_state, matched) -> None:
    from engine.social import memory

    pid = matched("matchstick").split(":")[1]
    made = [memory.add_open(receipts_state, pid, {"kind": "followup", "about": f"thing {i}", "due_at": 0.0})
            for i in range(10)]
    assert all(r["ok"] for r in made)
    rows = memory.person(receipts_state, pid)["open"]
    assert [r["about"] for r in rows] == [f"thing {i}" for i in range(2, 10)]
    assert memory.add_open(receipts_state, pid, {"kind": "plan", "about": "x"})["ok"] is False
    assert memory.close_open(receipts_state, pid, rows[0]["id"])["ok"]
    assert memory.close_open(receipts_state, pid, rows[0]["id"])["ok"] is False


def test_a_reply_followup_resolves_its_when(receipts_state, matched) -> None:
    from engine.social import memory, relationships

    pid = matched("matchstick").split(":")[1]
    now = receipts_state.world_clock_hours
    made = relationships.apply_followups(receipts_state, pid, [
        {"about": "their interview", "when": "tomorrow"},
        {"about": "the gig", "when": "days:3"},
        {"about": "never read", "when": "after:lunch"},          # past the row's max of 2
    ])
    assert [r["about"] for r in made] == ["their interview", "the gig"]
    assert made[0]["due_at"] == (now // 24 + 1) * 24 + 7 and made[1]["due_at"] == (now // 24 + 3) * 24 + 7
    assert relationships.apply_followups(receipts_state, pid, [{"about": "x", "when": "someday"}]) == []
    assert relationships.followup_due_at(receipts_state, pid, "days:99", now) is None
    assert relationships.followup_due_at(receipts_state, pid, "after:lunch", now) is not None
    assert "followups" not in relationships.legal_proposals(receipts_state, pid)
    assert len(memory.person(receipts_state, pid)["open"]) == 2


def test_a_broken_player_promise_writes_a_followup(receipts_state, matched) -> None:
    from engine.game import clock
    from engine.social import memory, promises

    thread = matched("matchstick")
    pid = thread.split(":")[1]
    row = promises.make(receipts_state, pid, by="player", window="tonight")
    assert row is not None
    clock.advance_time(receipts_state, row["closes_at"] + 2.0 - receipts_state.world_clock_hours)
    assert receipts_state.social["promises"][row["id"]]["status"] == "broken"
    (followup,) = memory.person(receipts_state, pid)["open"]
    assert followup["kind"] == "followup" and followup["about"] == "your plans tonight"   # from their side (T7 review M2)
    assert memory.followup_due(receipts_state, pid, receipts_state.world_clock_hours)["id"] == followup["id"]


# -- the moved parts and the archive -------------------------------------------------------------------


def test_a_v022_person_row_is_read_and_moved_by_its_first_write(receipts_state, matched) -> None:
    from engine.social import memory

    pid = matched("matchstick").split(":")[1]
    person = receipts_state.social["people"][pid]
    person.pop("memory", None)
    person["canon"] = ["grew up by the harbour"]
    person["knows"] = ["works nights"]
    assert memory.person(receipts_state, pid)["canon"] == ["grew up by the harbour"]
    memory.add_knows(receipts_state, pid, ["likes jazz"])
    assert "canon" not in person and "knows" not in person
    assert person["memory"]["canon"] == ["grew up by the harbour"]
    assert person["memory"]["knows"] == ["works nights", "likes jazz"]


def test_scene_rows_are_an_archive_kind(tmp_path, receipts_state, matched) -> None:
    from engine.social import archive

    thread = matched("matchstick")
    row = {"id": "m900", "thread_id": thread, "at": 30.0, "bubbles": ["You walk along the harbour together."],
           "voiced": True}
    assert archive.append(tmp_path, [row], kind="scene")
    page = archive.page(tmp_path, receipts_state, thread, "", 10)
    assert [(m["id"], m["kind"], m["from"], m["bubbles"]) for m in page["messages"]] == [
        ("m900", "scene", "system", ["You walk along the harbour together."])]
    assert archive.archived(tmp_path, thread)[0]["row"] == "scene"
    with pytest.raises(ValueError):
        archive.append(tmp_path, [row], kind="narration")
    with pytest.raises(ValueError):
        archive.append(tmp_path, [{"thread_id": thread, "id": "s1"}], kind="scene")


def test_the_recap_prompt_is_cached_and_warned_once(receipts_active, monkeypatch, tmp_path, caplog) -> None:
    import logging

    from engine import social
    from engine.games import caches
    from engine.social import memory

    text = (social.social_dir().parent.parent / "prompts" / "episode_recap.md").read_text(encoding="utf-8")
    assert memory.recap_prompt() == text.split(memory.STORY_HEADING)[0].strip() + "\n"
    assert "at most 70 words" in memory.recap_prompt() and "at most 300 words" in memory.story_prompt()
    assert int(social.setting("memory.recap_words", 0)) == 70 and int(social.setting("memory.story_words", 0)) == 300
    assert ("engine.social.memory", "_RECAP_PROMPT_CACHE") in caches.NULLED_ATTRIBUTES
    (tmp_path / "story" / "data" / "social").mkdir(parents=True)
    monkeypatch.setattr(social, "social_dir", lambda: tmp_path / "story" / "data" / "social")
    monkeypatch.setattr(memory, "_PROMPT_MISSING_LOGGED", set())
    monkeypatch.setattr(memory, "_RECAP_PROMPT_CACHE", None)
    with caplog.at_level(logging.WARNING, logger="engine.social.memory"):
        assert memory.recap_prompt() == "" and memory.story_prompt() == ""
        monkeypatch.setattr(memory, "_RECAP_PROMPT_CACHE", None)
        assert memory.recap_prompt() == ""
    assert sum("no episode recap prompt" in r.getMessage() for r in caplog.records) == 1


# -- the dormant lever, lossless (T6 review I1) ---------------------------------------------------------


def _long_recap(i: int) -> str:
    """A realistic recap: 70 words, its own first and last word findable."""
    words = [f"r{i}start"] + [f"word{i}x{k}" for k in range(68)] + [f"r{i}end."]
    return " ".join(words)


STORY = ("They first matched on a wet Tuesday and talked about the harbour lights. "
         + " ".join(f"Then thing {k} happened between them." for k in range(40)))


def _dormant(state, pid: str, recaps: int = 12) -> None:
    """A person with `recaps` 70-word recaps, a long story and a current, last heard from long ago."""
    from engine import social
    from engine.game.effects import apply_effect
    from engine.social import memory

    long_ago = state.world_clock_hours - int(social.setting("memory.dormant_days", 30)) * 24.0 - 1.0
    for i in range(recaps):
        memory.add_recap(state, pid, {"id": f"x{i}", "recap": _long_recap(i), "topics": [], "to_at": long_ago})
    row = state.social["people"][pid]
    row["memory"]["story"] = memory.cap_story(STORY)
    apply_effect(state, {"type": "social_memory", "op": "spoken", "pid": pid,
                         "message": {"id": "m9001", "thread_id": f"natter:{pid}", "from": "player", "at": long_ago,
                                     "bubbles": ["see you around"]}})
    row.pop("episode", None)
    row.pop("recap_due", None)
    for key in ("last_player_at", "last_them_at"):
        row[key] = long_ago
    assert memory.person(state, pid)["story"].startswith("They first matched")


def test_a_dormant_memory_is_shelved_whole_in_the_archive(receipts_state, matched, tmp_path) -> None:
    """Nothing is folded or cut: the older recaps, the story, current and bridge reach the archive first."""
    from engine.social import memory

    pid = matched("matchstick").split(":")[1]
    _dormant(receipts_state, pid)
    before = memory.person(receipts_state, pid)
    assert memory.compact_dormant(receipts_state, None) == 0          # no archive to move into: left whole
    assert memory.person(receipts_state, pid) == before
    assert memory.compact_dormant(receipts_state, tmp_path) == 1
    after = memory.person(receipts_state, pid)
    assert [e["id"] for e in after["episodes"]] == ["x9", "x10", "x11"]
    assert after["story"] == before["story"]                          # the story is not cut
    assert after["current"] == [] and after["bridge"] == []
    (shelf,) = memory.archived_memory(tmp_path, pid)
    assert shelf["story"] == before["story"] and shelf["current"] == before["current"]
    assert [e["recap"] for e in shelf["episodes"]] == [_long_recap(i) for i in range(9)]
    assert receipts_state.social["people"][pid]["memory"]["shelved"] == [shelf["id"]]
    assert memory.compact_dormant(receipts_state, tmp_path) == 0      # nothing left to move


@pytest.mark.parametrize("model", [True, False])
def test_a_reconnect_restores_the_shelved_memory(receipts_state, matched, tmp_path, model) -> None:
    """After compaction and a reconnect, the story's first sentence and every recap are recoverable, and the
    restore folds the shelf back into the story: condensed by the model, or (no model) the newest kept for
    the prompt while the archive keeps every word."""
    from engine.social import memory

    thread = matched("matchstick")
    pid = thread.split(":")[1]
    _dormant(receipts_state, pid)
    assert memory.compact_dormant(receipts_state, tmp_path) == 1
    assert memory.restore_view(receipts_state, pid) is None            # dormant: nothing to restore yet
    with _replies_forced():
        _open_episode(receipts_state, pid, thread)                      # they talk again
    view = memory.job_view(receipts_state)
    assert view is not None and view["kind"] == "restore"
    view = memory.job_with_archive(view, tmp_path)
    assert [e["id"] for e in view["episodes"]] == [f"x{i}" for i in range(9)] and view["missing"] == []
    seen: list = []
    fn = (lambda m: seen.append(m) or "You met on a wet Tuesday; nine long talks since.") if model else None
    text, used = memory.write_restore(view, fn)
    assert used is model
    if model:
        assert "They first matched" in seen[0][1]["content"] and "r0start" in seen[0][1]["content"]
    assert memory.commit_restore(receipts_state, view, text)["ok"]
    assert memory.person(receipts_state, pid)["story"] == memory.cap_story(text)
    assert not receipts_state.social["people"][pid]["memory"].get("shelved")
    assert memory.commit_restore(receipts_state, view, text)["ok"] is False    # stale: the shelf is back already
    shelves = memory.archived_memory(tmp_path, pid)
    words = " ".join([r["story"] for r in shelves] + [e["recap"] for r in shelves for e in r["episodes"]]
                     + [e["recap"] for e in memory.person(receipts_state, pid)["episodes"]])
    assert "They first matched on a wet Tuesday" in words
    assert all(_long_recap(i) in words for i in range(12))


def test_the_restore_runs_in_a_pass_and_a_fold_leaves_its_record(receipts_active) -> None:
    """In play (a saved run): a dormant person who writes again gets their shelf back through the pass's
    memory job, and a fold job writes the recap and story it folds to the archive before it commits."""
    from engine.session.store import release_turn
    from engine.social import archive, memory, voicer
    from tests.social_fixtures import _live_session, _matched_in

    _scene, session = _live_session()
    state = session.engine.state
    thread = _matched_in(session, "matchstick")
    pid = thread.split(":")[1]
    directory = archive.save_dir(session)
    assert session.lock.acquire(blocking=False)
    try:
        _dormant(state, pid)
        assert memory.compact_dormant(state, directory) == 1
        with _replies_forced():
            _open_episode(state, pid, thread)
    finally:
        release_turn(session)
    voicer.set_summary_fn(lambda messages: "The story so far, condensed.")
    p = voicer.VoicePass(session, session.epoch)
    assert voicer._recap_one(session, p)
    assert memory.person(state, pid)["story"] == "The story so far, condensed."
    assert session.lock.acquire(blocking=False)
    try:
        for i in range(12, 21):
            memory.add_recap(state, pid, {"id": f"y{i}", "recap": f"Talk {i}.", "topics": []})
        assert len(memory.person(state, pid)["episodes"]) == 12
        state.social["people"][pid]["recap_due"] = [{"id": "e900", "kind": "chat", "thread_id": thread,
                                                     "started_at": state.world_clock_hours,
                                                     "last_at": state.world_clock_hours,
                                                     "closed_at": state.world_clock_hours, "topics": []}]
    finally:
        release_turn(session)
    assert voicer._recap_one(session, p)                                 # the fold job
    folds = [r for r in memory.archived_memory(directory, pid) if r["id"].startswith("fold-")]
    assert folds and folds[0]["story"] == "The story so far, condensed." and folds[0]["episodes"][0]["id"] == "x9"


def test_a_missing_shelf_restores_the_rest_and_warns(receipts_state, matched, tmp_path, caplog) -> None:
    import logging

    from engine.social import archive, memory

    thread = matched("matchstick")
    pid = thread.split(":")[1]
    _dormant(receipts_state, pid)
    assert memory.compact_dormant(receipts_state, tmp_path) == 1
    (tmp_path / archive.ARCHIVE_FILE).unlink()
    with _replies_forced():
        _open_episode(receipts_state, pid, thread)
    with caplog.at_level(logging.WARNING, logger="engine.social.memory"):
        view = memory.job_with_archive(memory.job_view(receipts_state), tmp_path)
    assert view["missing"] and any("does not hold these shelves" in r.getMessage() for r in caplog.records)
    text, _used = memory.write_restore(view, None)
    assert memory.commit_restore(receipts_state, view, text)["ok"]       # never stuck: the job is spent


# -- the review's minors ------------------------------------------------------------------------------


def test_add_recap_clears_current_only_up_to_its_end(receipts_state, matched) -> None:
    """M1: a recap row landing mid-chat (T12's stub) keeps the lines said after it."""
    from engine.social import memory, messaging

    thread = matched("matchstick")
    pid = thread.split(":")[1]
    now = receipts_state.world_clock_hours
    messaging.new_message(receipts_state, thread, "player", "text", bubbles=["before"], at=now - 1.0)
    messaging.new_message(receipts_state, thread, "player", "text", bubbles=["after"], at=now)
    memory.add_recap(receipts_state, pid, {"id": "z1", "recap": "You met.", "to_at": now - 0.5})
    mem = memory.person(receipts_state, pid)
    assert [m["bubbles"] for m in mem["current"]] == [["after"]]
    assert [m["bubbles"] for m in mem["bridge"]] == [["before"]]
    memory.add_recap(receipts_state, pid, {"id": "z2", "recap": "No end given."})
    assert [m["bubbles"] for m in memory.person(receipts_state, pid)["current"]] == [["after"]]


def test_the_archive_window_reads_an_old_episode_past_newer_rows(receipts_active, tmp_path) -> None:
    """M2: an episode whose messages lie behind more than a page of newer archived rows is still read."""
    import json

    from engine.social import archive, memory

    tid = "natter:p0001"
    rows = [{"id": f"m{n}", "thread_id": tid, "from": "player", "kind": "text", "at": float(n), "bubbles": [f"w{n}"],
             "voiced": True} for n in range(1, 301)]
    (tmp_path / archive.ARCHIVE_FILE).write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    view = {"kind": "recap", "pid": "p0001", "from_at": 10.0, "to_at": 20.0, "earliest": 10.0, "items": [],
            "needs_archive": [(tid, 301)]}
    got = memory.with_archive(view, tmp_path)
    assert [m["bubbles"][0] for m in got["items"]] == [f"w{n}" for n in range(10, 21)]


def test_a_followup_with_no_due_time_is_never_due(receipts_state, matched) -> None:
    """M3: an open row with no `due_at` is not raised (T7 decides when a follow-up counts as addressed)."""
    from engine.social import memory

    pid = matched("matchstick").split(":")[1]
    assert memory.add_open(receipts_state, pid, {"kind": "followup", "about": "someday"})["ok"]
    assert memory.followup_due(receipts_state, pid, receipts_state.world_clock_hours + 1000.0) is None


def test_state_keeps_memory_rows_compact_and_person_gives_them_whole(receipts_state, matched) -> None:
    """M8: empty parts left out, history without `day`, messages without their thread id or the person's
    own name; `memory.person` and `full_history` put every one back."""
    from engine.social import memory, messaging

    thread = matched("matchstick")
    pid = thread.split(":")[1]
    messaging.new_message(receipts_state, thread, "player", "text", bubbles=["hello there"])
    stored = receipts_state.social["people"][pid]["memory"]
    assert set(stored) == {"current", "history"}
    assert "day" not in stored["history"][0] and "thread_id" not in stored["current"][0]
    full = memory.person(receipts_state, pid)
    assert full["history"][0]["day"] == int(full["history"][0]["at"] // 24) + 1
    assert full["current"][0]["thread_id"] == thread and full["current"][0]["from"] == "player"
    assert set(full) == set(memory.PARTS)
