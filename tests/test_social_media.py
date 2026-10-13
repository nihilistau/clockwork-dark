"""
READ RECEIPTS' phone media (v0.22.0 spec §13.1-13.4, §16.1 step 3; T19):
photos, voice notes and videos as special events the ENGINE decides (rule
1) -- budgets, the stage, trust, warmth, mood and a draw on SOCIAL_MEDIA
(rule 4) -- the image request built from the person's appearance with only a
length cap (rule 12), the portraits by policy, the jobs' hand-off into the
run (liveness, the turn lock or the inbox, `social_media`, `media_ready`),
the owner-scoped media route, resubmission on resume and the worker stopped
on a hosted drain.

No live ComfyUI: `phone_media.provider` is `procedural` by default (no
service), and the `stub` tests drive `tests/comfy_stub.py::StubComfy` in
process (no bind). No model: the voice is `tests/social_stub.py::StubVoice`.
"""

from __future__ import annotations

import ast
import dataclasses
import json
import logging
from pathlib import Path
from typing import Any

import pytest

from tests.social_fixtures import (  # noqa: F401  (fixtures)
    _force_stage,
    _live_session,
    _matched_in,
    _phone,
    _set_person,
    _top,
    _wait_until,
    hosted_receipts,
    matched,
    matched_numbers,
    media_root,
    receipts_active,
    receipts_state,
)

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _restore_the_overlay() -> Any:
    from engine.config import overlay, set_overlay

    saved = overlay()
    try:
        yield
    finally:
        set_overlay(saved)


def _with_config(values: dict[str, Any]) -> None:
    """Dotted config keys for this test only (the overlay, restored at its end)."""
    from engine.config import deep_merge, overlay, set_overlay

    nested: dict[str, Any] = {}
    for dotted, value in values.items():
        node = nested
        parts = dotted.split(".")
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value
    set_overlay(deep_merge(overlay(), nested))


class _Recorder:
    """A stand-in for the process's media worker: records each submission, takes them all."""

    def __init__(self) -> None:
        self.specs: list[Any] = []

    def submit(self, spec: Any) -> bool:
        self.specs.append(spec)
        return True


def _locked(session):
    """The session's turn lock held for a block (a context manager), released through release_turn."""
    import contextlib

    from engine.session.store import release_turn

    @contextlib.contextmanager
    def held():
        assert session.lock.acquire(blocking=False)
        try:
            yield session.engine.state
        finally:
            release_turn(session)

    return held()


def _numbers_session():
    """`(scene, session, pid, natter_thread)`: a live run with one person at `numbers`, Natter open, never ghosting."""
    from engine.social import messaging

    scene, session = _live_session()
    pid = _matched_in(session, "matchstick").split(":")[1]
    with _locked(session) as state:
        _force_stage(state, pid, "numbers")
        messaging.open_numbers(state, pid)
        _set_person(state, pid, interest=100)
    return scene, session, pid, f"natter:{pid}"


def _free_hour(person: Any, start: float) -> float:
    """The first whole in-game hour at or after `start` at which `person` is `free`."""
    from engine.social import behaviour

    at = float(int(start))
    for _ in range(24 * 8):
        if behaviour.status_at(person, at) == "free":
            return at
        at += 1.0
    raise AssertionError("no free hour in a week")


def _photo_row(state, kind: str = "photo") -> dict[str, Any]:
    rows = [r for r in state.social["media"].values() if r["kind"] == kind]
    assert rows, f"no {kind} media row"
    return rows[-1]


def _ask_and_get_photo(scene, session, natter: str, monkeypatch, what: str = "photo") -> dict[str, Any]:
    """The player asks for a photo (or `what`); the person accepts (accept odds forced to 1) and their message lands."""
    from engine.social import media

    monkeypatch.setattr(media, "accept_p", lambda *a, **k: 1.0)
    pid = natter.split(":")[1]
    with _locked(session) as state:
        _set_person(state, pid, media_budget={"photo": 0, "voice": 0, "video": 0, what: 2})
    asked = _phone(scene, session, "ask", target=natter, args={"what": what})
    assert not asked["receipts"][0].get("refused"), asked["receipts"][0]
    state = session.engine.state

    def landed() -> bool:
        return any(r["kind"] == what for r in (state.social.get("media") or {}).values())

    for _ in range(48):
        if landed():
            break
        _phone(scene, session, "wait", args={"until": "1h"})
    assert landed(), f"their {what} never landed"
    return _photo_row(state, what)


# -- the decisions (rule 1) ---------------------------------------------------------------------


def test_a_request_without_budget_is_declined_by_the_relationship(receipts_state, matched) -> None:
    from engine.social import media

    pid = matched("matchstick").split(":")[1]
    _force_stage(receipts_state, pid, "talking")
    _set_person(receipts_state, pid, media_budget={"photo": 0, "voice": 0, "video": 0}, trust=90, warmth=90)
    for _ in range(20):
        decided = media.decide_request(receipts_state, pid, "photo")
        assert decided["answer"] in ("decline", "later") and decided["why"] == "budget"
    assert receipts_state.social["people"][pid]["media_budget"]["photo"] == 0      # nothing spent


def test_a_request_with_budget_and_trust_is_accepted_and_spends(receipts_state, matched, monkeypatch) -> None:
    from engine.social import behaviour, media, population

    pid = matched("matchstick").split(":")[1]
    _force_stage(receipts_state, pid, "talking")
    _set_person(receipts_state, pid, media_budget={"photo": 1, "voice": 0, "video": 0}, trust=100, warmth=100)
    monkeypatch.setattr(media, "accept_p", lambda *a, **k: 1.0)
    at = _free_hour(population.profile(receipts_state, pid), receipts_state.world_clock_hours)
    decided = media.decide_request(receipts_state, pid, "photo", at=at)
    assert decided["answer"] == "accept" and decided["subject"] in media.subjects_for(receipts_state, pid, at)
    assert receipts_state.social["people"][pid]["media_budget"]["photo"] == 0
    assert receipts_state.social["people"][pid]["rng_n"][media.SOCIAL_MEDIA] >= 1   # its own stream (rule 4)
    assert behaviour.status_at(population.profile(receipts_state, pid), at) == "free"


def test_a_stage_too_early_declines_whatever_the_draw(receipts_state, matched, monkeypatch) -> None:
    from engine.social import media

    pid = matched("matchstick").split(":")[1]                   # stage `matched`: photos unlock at `talking`
    _set_person(receipts_state, pid, media_budget={"photo": 2, "voice": 2, "video": 1})
    monkeypatch.setattr(media, "accept_p", lambda *a, **k: 1.0)
    assert media.decide_request(receipts_state, pid, "photo")["why"] == "stage"


def test_the_mood_multiplier_is_held_inside_its_bounds(receipts_state, matched) -> None:
    from engine import social
    from engine.social import media

    pid = matched("matchstick").split(":")[1]
    _force_stage(receipts_state, pid, "talking")
    low, high = social.data("relationships")["mood"]["media_mult"]
    for mood in social.data("relationships")["mood"]["values"]:
        _set_person(receipts_state, pid, mood=mood, mood_until=None)
        assert low <= media._mood_mult(receipts_state, pid) <= high


def test_offer_photo_cannot_beat_the_budget(receipts_state, matched_numbers) -> None:
    from engine.social import relationships

    pid = matched_numbers("natter").split(":")[1]
    _set_person(receipts_state, pid, media_budget={"photo": 1, "voice": 0, "video": 0})
    assert "offer_photo" in relationships.legal_proposals(receipts_state, pid)      # the control: open with budget
    _set_person(receipts_state, pid, media_budget={"photo": 0, "voice": 0, "video": 0})
    assert "offer_photo" not in relationships.legal_proposals(receipts_state, pid)
    assert not relationships.apply_proposal(receipts_state, pid, "offer_photo")["ok"]


def test_offer_photo_needs_a_thread_that_can_carry_it(receipts_state, matched) -> None:
    from engine.social import relationships

    pid = matched("matchstick").split(":")[1]                    # Matchstick carries text only
    _force_stage(receipts_state, pid, "talking")
    _set_person(receipts_state, pid, media_budget={"photo": 2, "voice": 2, "video": 1})
    assert "offer_photo" not in relationships.legal_proposals(receipts_state, pid)


def test_a_passing_offer_queues_a_new_due_message_and_spends(receipts_active, monkeypatch) -> None:
    from engine.social import media, messaging, voicer
    from tests.social_stub import StubVoice

    scene, session, pid, natter = _numbers_session()
    with _locked(session) as state:
        _set_person(state, pid, media_budget={"photo": 1, "voice": 0, "video": 0})
        messaging.new_message(state, natter, pid, "text", voiced=False, decision={"situation": "reply"})
        before = {m["id"] for t in state.social["threads"].values() for m in t["messages"]}
    monkeypatch.setattr(media, "unsolicited_draw", lambda *a, **k: True)
    # A subject that fits whatever they are doing now (the deck's top person is the data's: T26's pools).
    monkeypatch.setattr(media, "subjects_for", lambda *a, **k: ["selfie_now"])
    offer = json.dumps({"bubbles": [{"text": "want to see where I am?"}], "regard": {"warmth": 0, "trust": 0,
                        "mood": "neutral"}, "learned": [], "shared": [], "proposals": ["offer_photo"]})
    voice = StubVoice("zero", script=[offer])
    voicer.run_until_quiet(session, voice)
    state = session.engine.state
    new = [m for t in state.social["threads"].values() for m in t["messages"] if m["id"] not in before]
    photos = [m for m in new if (m.get("decision") or {}).get("media_kind") == "photo"]
    assert len(photos) == 1 and photos[0]["from"] == pid and photos[0]["media_id"]
    assert state.social["media"][photos[0]["media_id"]]["kind"] == "photo"
    assert state.social["people"][pid]["media_budget"]["photo"] == 0                # spent: 1 -> 0
    assert photos[0]["voiced"] is True                                             # its own voicing, a caption
    assert state.social["media"][photos[0]["media_id"]]["caption"] == "this one's for you"


def test_a_failed_offer_draw_sends_nothing_and_spends_nothing(receipts_state, matched_numbers, monkeypatch) -> None:
    from engine.social import media

    pid = matched_numbers("natter").split(":")[1]
    _set_person(receipts_state, pid, media_budget={"photo": 1, "voice": 0, "video": 0})
    monkeypatch.setattr(media, "unsolicited_draw", lambda *a, **k: False)
    result = media.offer(receipts_state, pid, "photo")
    assert result["ok"] and result["sent"] is False
    assert receipts_state.social["people"][pid]["media_budget"]["photo"] == 1
    assert not receipts_state.social["media"]


def test_subjects_gate_on_fixed_flags_not_canon(receipts_state, matched, monkeypatch) -> None:
    from engine.social import media, memory, population

    pid = matched("matchstick").split(":")[1]
    person = population.profile(receipts_state, pid)
    if person.has_flag("has_pet"):                              # this test needs a person WITHOUT the flag
        real = population.profile
        monkeypatch.setattr(population, "profile", lambda s, p: dataclasses.replace(
            real(s, p), flags=tuple(f for f in real(s, p).flags if f != "has_pet")) if p == pid else real(s, p))
    _force_stage(receipts_state, pid, "talking")
    memory.add_canon(receipts_state, pid, ["I have a dog called Biscuit and he goes everywhere with me"])
    monkeypatch.setattr(media, "accept_p", lambda *a, **k: 1.0)
    at = _free_hour(population.profile(receipts_state, pid), receipts_state.world_clock_hours)
    subjects = set()
    for _ in range(200):
        _set_person(receipts_state, pid, media_budget={"photo": 2, "voice": 0, "video": 0})
        decided = media.decide_request(receipts_state, pid, "photo", at=at)
        assert decided["answer"] == "accept"
        subjects.add(decided["subject"])
    assert "pet" not in subjects and subjects                   # canon says "my dog"; the flag says no pet
    # The control: the same person WITH the fixed flag can send their pet.
    real = population.profile
    monkeypatch.setattr(population, "profile", lambda s, p: dataclasses.replace(
        real(s, p), flags=tuple(real(s, p).flags) + ("has_pet",)) if p == pid else real(s, p))
    assert "pet" in media.subjects_for(receipts_state, pid, at)


def test_a_morning_refills_every_live_persons_budget_to_its_cap(receipts_state, matched) -> None:
    from engine import social
    from engine.game import clock

    pid = matched("matchstick").split(":")[1]
    _force_stage(receipts_state, pid, "talking")
    _set_person(receipts_state, pid, media_budget={"photo": 0, "voice": 1.9, "video": 0})
    clock.advance_time(receipts_state, 24.0)                    # exactly one morning passes
    budget = social.data("media")["budget"]
    held = receipts_state.social["people"][pid]["media_budget"]
    assert held["photo"] == pytest.approx(budget["photo"]["per_day"])
    assert held["voice"] == pytest.approx(budget["voice"]["cap"])                   # 1.9 + 0.25, capped at 2
    assert held["video"] == pytest.approx(budget["video"]["per_day"])


@pytest.mark.parametrize("odds, kept", [(1.0, True), (0.0, False)])
def test_a_later_request_is_kept_or_broken_the_next_morning(receipts_state, matched_numbers, monkeypatch,
                                                           odds: float, kept: bool) -> None:
    from engine.game import clock
    from engine.game.effects import apply_effect
    from engine.social import media, relationships

    thread = matched_numbers("natter")
    pid = thread.split(":")[1]
    _set_person(receipts_state, pid, media_budget={"photo": 2, "voice": 0, "video": 0})
    asked = relationships.ask(receipts_state, thread, "photo")
    assert asked["ok"], asked
    rid = asked["request_id"]
    apply_effect(receipts_state, {"type": "social_request", "op": "answer", "request_id": rid, "status": "later"})
    monkeypatch.setattr(media, "accept_p", lambda *a, **k: odds)
    monkeypatch.setattr(media, "unsolicited_draw", lambda *a, **k: False)   # the morning's unasked one: not this
    clock.advance_time(receipts_state, 24.0)
    request = receipts_state.social["requests"][rid]
    assert request["status"] == ("yes" if kept else "no")      # kept or broken, never left hanging
    queued = [e["decision"] for e in receipts_state.social["queue"] if (e.get("decision") or {}).get("request_id") == rid]
    landed = [m["decision"] for t in receipts_state.social["threads"].values() for m in t["messages"]
              if (m.get("decision") or {}).get("request_id") == rid and m.get("from") == pid]
    held = receipts_state.social["people"][pid]["media_budget"]["photo"]
    if kept:                                                    # the medium is sent today, one spent
        assert [d["media_kind"] for d in queued + landed] == ["photo"]
        assert held == pytest.approx(min(2.0, 2.0 + 0.15) - 1.0)
    else:
        assert not queued and not landed and held == pytest.approx(2.0)


def test_a_media_ask_is_refused_in_words_where_it_cannot_happen(receipts_state, matched, matched_numbers) -> None:
    from engine.agents.tool_dispatcher import execute_phone_intent
    from tests.social_fixtures import _engine

    def ask(thread: str, what: str) -> dict[str, Any]:
        return execute_phone_intent({"action": "ask", "target": thread, "args": {"what": what}},
                                    _engine(receipts_state))

    natter = matched_numbers("natter")
    pid = natter.split(":")[1]
    refused = ask(f"matchstick:{pid}", "photo")
    assert refused["refused"] and refused["result"]["error"] == "Matchstick can't send photos"
    for _ in range(2):
        assert not ask(natter, "photo").get("refused")
    third = ask(natter, "photo")
    assert third["refused"] and third["result"]["error"] == "Give it a day"


# -- the image request (rule 12) ----------------------------------------------------------------


def test_a_request_carries_only_the_sampler_keys_its_workflow_binds(receipts_state, matched) -> None:
    """T20 fix round 1 (M1): the photo's request (and so its digest) is unchanged; the video's carries no SDXL keys."""
    from engine.media.comfy.jobs import JobSpec
    from engine.media.comfy.workflows import load_workflow
    from engine.social import media, population

    pid = matched("matchstick").split(":")[1]
    person = population.profile(receipts_state, pid)
    now = media.now_for(receipts_state, person)
    subject = media.subject_row("selfie_now")
    sampler = media._sampler_values()
    photo_wf, video_wf = load_workflow("photo"), load_workflow("video")
    photo = media.photo_request(person, subject, "hi", now, mid="x1", seed=7, workflow=photo_wf)
    # The pre-fix formula: every sampler key, whatever the workflow binds.
    style = ", ".join(p for p in [person.appearance, subject["scene"], "hi", f"{now['daypart']}, {now['status']}",
                                  str(media._data().get("style") or "")] if p)
    before = {"positive": style, "seed": 7, "width": photo_wf.size["width"], "height": photo_wf.size["height"],
              "filename_prefix": "phone/x1", **sampler}
    assert photo == before

    def digest(values: dict[str, Any]) -> str:
        return JobSpec(mid="x1", kind="image", owner="", save_id="s1", session_id="s", epoch=1, workflow="photo",
                       values=values, priority=0, account="").digest()

    assert digest(photo) == digest(before)
    video = media.photo_request(person, subject, "hi", now, mid="x2", seed=7, workflow=video_wf)
    assert set(video) == set(video_wf.bindings) and not set(sampler) & set(video)


def test_the_prompt_has_no_negative_and_no_filter(receipts_state, matched) -> None:
    from engine.media.comfy.workflows import bind, load_workflow
    from engine.social import media, population

    pid = matched("matchstick").split(":")[1]
    person = population.profile(receipts_state, pid)
    caption = ("0123456789" * 30)                                # 300 characters, as the model wrote them
    workflow = load_workflow("photo")
    values = media.photo_request(person, media.subject_row("selfie_now"), caption,
                                 media.now_for(receipts_state, person), mid="x1", seed=7, workflow=workflow)
    assert caption[:200] in values["positive"] and caption[:201] not in values["positive"]
    assert values["positive"].startswith(person.appearance)
    assert values["filename_prefix"] == "phone/x1" and values["seed"] == 7
    assert "negative" not in values
    graph = bind(workflow, values)
    assert graph["3"]["inputs"]["text"] == ""                       # the negative node is the template's, empty
    assert graph["2"]["inputs"]["text"] == values["positive"]
    # No function named like a sanitiser, filter, classifier or moderator is CALLED in media.py.
    tree = ast.parse((ROOT / "engine" / "social" / "media.py").read_text(encoding="utf-8"))
    called = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            called.add(fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", ""))
    import re

    banned = sorted(n for n in called if re.search(r"sanitiz|sanitis|filter|classif|moderat", n, re.I))
    assert not banned, f"media.py calls {banned}"


def test_seeds_are_stable_and_per_stream(receipts_state) -> None:
    from engine.game.rng import SOCIAL_MEDIA, _mix
    from engine.social import media

    assert media.face_seed(receipts_state, "p0001") == _mix(receipts_state.rng_seed, f"{SOCIAL_MEDIA}:face:p0001", 0) % 2**31
    assert media.media_seed(receipts_state, "p0001", "x3") == \
        _mix(receipts_state.rng_seed, f"{SOCIAL_MEDIA}:p0001:x3", 0) % 2**31
    assert media.face_seed(receipts_state, "p0001") != media.face_seed(receipts_state, "p0002")


@pytest.mark.parametrize("hour, part", [(5, "morning"), (11.9, "morning"), (12, "afternoon"), (17, "evening"),
                                        (21.5, "evening"), (22, "night"), (3, "night"), (29, "morning")])
def test_daypart_is_the_engines_words(hour: float, part: str) -> None:
    from engine.social import media

    assert media.daypart(hour) == part


# -- portraits by policy, and the day's cap ---------------------------------------------------------


def _swipe_passes(scene, session, n: int) -> None:
    for _ in range(n):
        turn = _phone(scene, session, "swipe", target=_top(session.engine.state, "matchstick"), args={"dir": "pass"})
        assert not turn["receipts"][0].get("refused"), turn["receipts"][0]


def test_on_match_portraits_cost_nothing_before_a_match(receipts_active, monkeypatch) -> None:
    from engine.media.comfy import jobs

    _with_config({"phone_media.provider": "stub", "phone_media.portraits": "on_match"})
    recorder = _Recorder()
    monkeypatch.setattr(jobs, "get_media_worker", lambda: recorder)
    scene, session = _live_session()
    _swipe_passes(scene, session, 60)
    assert recorder.specs == []                                   # 60 cards seen: not one job
    thread = _matched_in(session, "matchstick")
    _phone(scene, session, "wait", args={"until": "15m"})
    pid = thread.split(":")[1]
    assert [s.mid for s in recorder.specs] == [session.engine.state.social["people"][pid]["portrait"]]
    assert recorder.specs[0].workflow == "portrait" and recorder.specs[0].priority == 2


def test_on_view_submissions_stop_at_the_cap(receipts_active, monkeypatch) -> None:
    from engine.media.comfy import jobs
    from engine.media.comfy.client import ComfyClient

    _with_config({"phone_media.provider": "stub", "phone_media.portraits": "on_view", "phone_media.daily_job_cap": 5})
    worker = jobs.MediaJobWorker(client_factory=lambda: ComfyClient("http://comfy.test"), on_done=lambda s, r: None,
                                 start=False)                    # never started: the queue is only counted
    monkeypatch.setattr(jobs, "get_media_worker", lambda: worker)
    scene, session = _live_session()
    _swipe_passes(scene, session, 20)
    rows = [r for r in session.engine.state.social["media"].values() if r["kind"] == "portrait"]
    shown = len(rows)
    assert shown >= 20                                             # every card the deck showed owed a portrait
    assert worker.pending() == 5                                   # exactly the cap was submitted
    assert sum(r["status"] == "submitted" for r in rows) == 5
    assert sum(r["status"] == "fallback" for r in rows) == shown - 5   # the rest procedural at once


def test_portraits_off_make_no_rows(receipts_active, monkeypatch) -> None:
    from engine.media.comfy import jobs

    _with_config({"phone_media.provider": "stub", "phone_media.portraits": "off"})
    recorder = _Recorder()
    monkeypatch.setattr(jobs, "get_media_worker", lambda: recorder)
    scene, session = _live_session()
    _matched_in(session, "matchstick")
    _swipe_passes(scene, session, 3)
    assert recorder.specs == [] and not session.engine.state.social["media"]


# -- the provider off: no service at all ------------------------------------------------------------


def test_procedural_contacts_no_server(receipts_active, monkeypatch) -> None:
    import httpx

    from engine.social import messaging, voicer
    from tests.social_stub import StubVoice

    def refuse(*a: Any, **k: Any) -> Any:
        raise AssertionError("procedural media contacted a server")

    monkeypatch.setattr(httpx.Client, "send", refuse)
    scene, session, pid, natter = _numbers_session()
    row = _ask_and_get_photo(scene, session, natter, monkeypatch)
    voicer.run_until_quiet(session, StubVoice("warm"))
    _phone(scene, session, "wait", args={"until": "15m"})
    state = session.engine.state
    row = state.social["media"][row["mid"]]
    assert row["status"] == "fallback" and row["url"] == "" and row["caption"] == "this one's for you"
    message = next(m for m in state.social["threads"][natter]["messages"] if m.get("media_id") == row["mid"])
    view = messaging.message_view(state, state.social["threads"][natter], message)
    assert view["media"] == {"mid": row["mid"], "kind": "photo", "status": "fallback", "url": "", "poster_url": "",
                             "caption": "this one's for you"}


# -- the whole pipeline, through the in-process ComfyUI ---------------------------------------------


def test_a_requested_photo_is_made_stored_handed_off_and_served(receipts_active, media_root, monkeypatch) -> None:
    from engine.media.comfy import jobs
    from engine.media.comfy.client import ComfyClient
    from engine.social import agreement, voicer
    from engine.social.voicer import _decision_of
    from tests.comfy_stub import StubComfy
    from tests.social_stub import StubVoice

    _with_config({"phone_media.provider": "stub", "phone_media.portraits": "off", "comfyui.poll_seconds": 0.01})
    stub = StubComfy("ready")
    jobs.set_client_factory(lambda: ComfyClient("http://comfy.test", transport=stub.transport))
    pushed: list[tuple[str, dict[str, Any]]] = []
    scene, session, pid, natter = _numbers_session()
    voicer.set_emitter(lambda _sid, event, body: pushed.append((event, body)))
    row = _ask_and_get_photo(scene, session, natter, monkeypatch)
    voicer.run_until_quiet(session, StubVoice("warm"))            # the caption committed: the job goes at once
    state = session.engine.state
    _wait_until(lambda: state.social["media"][row["mid"]]["status"] == "ready", timeout=10)
    row = state.social["media"][row["mid"]]
    assert row["url"] == f"/api/phone/media/{session.save_id}/{row['mid']}-{row['digest']}.png"
    assert row["file"] == f"{row['mid']}-{row['digest']}.png"
    ready = [body for event, body in pushed if event == "media_ready"]
    assert ready and set(ready[-1]) == {"message_id", "mid", "url", "poster_url", "kind", "thread"}
    assert ready[-1]["mid"] == row["mid"] and ready[-1]["url"] == row["url"] and ready[-1]["thread"]["thread_id"] == natter
    # The prompt reached ComfyUI as built: appearance, scene, caption.
    posted = [json.loads(r.content) for r in stub.requests if r.url.path == "/prompt"]
    assert posted and "this one's for you" in posted[0]["prompt"]["2"]["inputs"]["text"]
    assert posted[0]["prompt"]["3"]["inputs"]["text"] == ""
    # Served, owner-scoped, from the local route.
    served = scene.app.test_client().get(row["url"])
    assert served.status_code == 200 and served.data.startswith(b"\x89PNG")
    # T11's agreement holds against the attached photo once it has landed.
    message = next(m for m in state.social["threads"][natter]["messages"] if m.get("media_id") == row["mid"])
    view = agreement.view_from_state(state, pid)
    decision = _decision_of(message)
    assert not [f for f in agreement.check({"bubbles": ["here's a pic for you"], "shared": [], "learned": []},
                                           decision, view) if f.check == "media_claimed"]
    denied = agreement.check({"bubbles": ["I'm not sending you a photo"], "shared": [], "learned": []},
                             decision, view)
    assert [f for f in denied if f.check == "media_denied"]


def test_a_video_request_with_comfyui_off_is_a_poster_tile_and_caption(receipts_active, monkeypatch) -> None:
    """T20 (spec §13.8): with ComfyUI off a video is the procedural poster tile and its caption."""
    import httpx

    from engine.social import messaging, voicer
    from tests.social_stub import StubVoice

    def refuse(*a: Any, **k: Any) -> Any:
        raise AssertionError("procedural media contacted a server")

    monkeypatch.setattr(httpx.Client, "send", refuse)
    _with_config({"phone_media.provider": "procedural"})
    scene, session, pid, natter = _numbers_session()
    row = _ask_and_get_photo(scene, session, natter, monkeypatch, "video")
    assert row["priority"] == 0 and row["subject"]                 # thread media, a subject the engine drew
    voicer.run_until_quiet(session, StubVoice("warm"))
    _phone(scene, session, "wait", args={"until": "15m"})
    state = session.engine.state
    row = state.social["media"][row["mid"]]
    assert row["status"] == "fallback" and row["url"] == "" and row["poster_url"] == ""
    assert row["caption"] == "this one's for you"
    message = next(m for m in state.social["threads"][natter]["messages"] if m.get("media_id") == row["mid"])
    view = messaging.message_view(state, state.social["threads"][natter], message)
    assert view["media"] == {"mid": row["mid"], "kind": "video", "status": "fallback", "url": "", "poster_url": "",
                             "caption": "this one's for you"}


def test_a_requested_video_is_made_with_its_poster_and_served(receipts_active, media_root, monkeypatch) -> None:
    """T20: the shipped video workflow, through the in-process ComfyUI: a WEBM and its poster, both served."""
    from engine.media.comfy import jobs
    from engine.media.comfy.client import ComfyClient
    from engine.social import voicer
    from tests.comfy_stub import StubComfy
    from tests.social_stub import StubVoice

    _with_config({"phone_media.provider": "stub", "phone_media.portraits": "off", "comfyui.poll_seconds": 0.01})
    stub = StubComfy("video")
    jobs.set_client_factory(lambda: ComfyClient("http://comfy.test", transport=stub.transport))
    pushed: list[tuple[str, dict[str, Any]]] = []
    scene, session, pid, natter = _numbers_session()
    voicer.set_emitter(lambda _sid, event, body: pushed.append((event, body)))
    row = _ask_and_get_photo(scene, session, natter, monkeypatch, "video")
    voicer.run_until_quiet(session, StubVoice("warm"))
    state = session.engine.state
    _wait_until(lambda: state.social["media"][row["mid"]]["status"] == "ready", timeout=10)
    row = state.social["media"][row["mid"]]
    stem = f"{row['mid']}-{row['digest']}"
    assert row["url"] == f"/api/phone/media/{session.save_id}/{stem}.webm"
    assert row["poster_url"] == f"/api/phone/media/{session.save_id}/{stem}_poster.png"
    ready = [body for event, body in pushed if event == "media_ready" and body["mid"] == row["mid"]]
    assert ready and ready[-1]["kind"] == "video" and ready[-1]["poster_url"] == row["poster_url"]
    posted = [json.loads(r.content)["prompt"] for r in stub.requests if r.url.path == "/prompt"]
    assert posted and posted[0]["10"]["class_type"] == "SaveWEBM"     # the shipped template, not the photo's
    assert "this one's for you" in posted[0]["5"]["inputs"]["text"] and posted[0]["6"]["inputs"]["text"] == ""
    client = scene.app.test_client()
    clip, poster = client.get(row["url"]), client.get(row["poster_url"])
    assert clip.status_code == 200 and clip.data.startswith(b"\x1a\x45\xdf\xa3")
    assert poster.status_code == 200 and poster.data.startswith(b"\x89PNG")


def test_a_failed_job_is_a_fallback_for_good(receipts_active, media_root, monkeypatch) -> None:
    from engine.media.comfy import jobs
    from engine.media.comfy.client import ComfyClient
    from engine.social import voicer
    from tests.comfy_stub import StubComfy
    from tests.social_stub import StubVoice

    _with_config({"phone_media.provider": "stub", "phone_media.portraits": "off", "comfyui.poll_seconds": 0.01,
                  "comfyui.retries": 0})
    stub = StubComfy("node_errors")
    jobs.set_client_factory(lambda: ComfyClient("http://comfy.test", transport=stub.transport))
    scene, session, pid, natter = _numbers_session()
    row = _ask_and_get_photo(scene, session, natter, monkeypatch)
    voicer.run_until_quiet(session, StubVoice("warm"))
    state = session.engine.state
    _wait_until(lambda: state.social["media"][row["mid"]]["status"] == "fallback", timeout=10)
    assert state.social["media"][row["mid"]]["error"]


# -- the hand-off (spec §13.4 step 8, §16.4) ------------------------------------------------------------


def _submitted_photo(session, natter: str) -> tuple[str, Any]:
    """A photo of theirs, voiced and its job submitted, in a live run: `(mid, spec)`."""
    from engine.media.comfy.jobs import JobSpec
    from engine.social import media, messaging

    pid = natter.split(":")[1]
    with _locked(session) as state:
        message = messaging.new_message(state, natter, pid, "photo", bubbles=["look"], voiced=True,
                                        decision=dataclasses.asdict(media.send_decision("photo", "selfie_now")))
        mid = media.attach(state, pid, natter, message["id"], "photo", "selfie_now")
        spec = JobSpec(mid=mid, kind="image", owner=session.owner, save_id=session.save_id,
                       session_id=session.session_id, epoch=session.epoch, workflow="photo",
                       values={"positive": "x"}, priority=0, account=session.owner)
        media.mark_submitted(state, mid, {"positive": "x"}, account=session.owner, provider="stub",
                             digest=spec.digest())
    return mid, spec


def _ready(mid: str, save_id: str) -> Any:
    from engine.media.comfy import storage
    from engine.media.comfy.jobs import JobResult

    return JobResult(mid, "ready", url=storage.url_for(save_id, f"{mid}.png"), path=f"/x/{mid}.png", kind="image",
                     attempts=1)


def test_a_media_result_mid_action_parks_in_the_inbox(receipts_active) -> None:
    from engine.social import media, voicer

    scene, session, pid, natter = _numbers_session()
    mid, spec = _submitted_photo(session, natter)
    pushed: list[tuple[str, dict[str, Any]]] = []
    voicer.set_emitter(lambda _sid, event, body: pushed.append((event, body)))
    assert session.lock.acquire(blocking=False)                    # an action holds the turn lock
    try:
        media.hand_off(spec, _ready(mid, session.save_id))
        assert len(session.inbox) == 1                             # parked, nothing written meanwhile
        assert session.engine.state.social["media"][mid]["status"] == "submitted"
        assert not pushed
    finally:
        session.lock.release()
    _phone(scene, session, "wait", args={"until": "15m"})       # the next action drains it under the lock
    row = session.engine.state.social["media"][mid]
    assert row["status"] == "ready" and row["file"] == f"{mid}.png" and len(session.inbox) == 0
    ready = [body for event, body in pushed if event == "media_ready"]
    assert len(ready) == 1 and ready[0]["mid"] == mid and ready[0]["message_id"]


def test_a_parked_media_result_lands_with_no_player_action(receipts_active) -> None:
    """Final review I1: parked while the lock was busy, it lands once the lock is free -- no tap needed."""
    from engine.social import media, voicer

    scene, session, pid, natter = _numbers_session()
    mid, spec = _submitted_photo(session, natter)
    pushed: list[tuple[str, dict[str, Any]]] = []
    voicer.set_emitter(lambda _sid, event, body: pushed.append((event, body)))
    voicer.get_scheduler().resume()
    assert session.lock.acquire(blocking=False)                    # a timed save, say, holds the turn lock
    try:
        media.hand_off(spec, _ready(mid, session.save_id))
        assert len(session.inbox) == 1
    finally:
        session.lock.release()                                      # released; the player does nothing
    _wait_until(lambda: any(event == "media_ready" for event, _ in pushed), timeout=5.0)
    row = session.engine.state.social["media"][mid]
    assert row["status"] == "ready" and len(session.inbox) == 0
    assert [body["mid"] for event, body in pushed if event == "media_ready"] == [mid]


def test_a_free_lock_applies_the_result_at_once(receipts_active) -> None:
    from engine.social import media, voicer

    scene, session, pid, natter = _numbers_session()
    mid, spec = _submitted_photo(session, natter)
    pushed: list[str] = []
    voicer.set_emitter(lambda _sid, event, body: pushed.append(event))
    media.hand_off(spec, _ready(mid, session.save_id))
    assert session.engine.state.social["media"][mid]["status"] == "ready" and pushed == ["media_ready"]
    assert session.dirty                                             # saved by the dirty timer
    assert not session.lock.locked()


def test_a_result_for_another_account_or_epoch_is_dropped(receipts_active, caplog) -> None:
    from engine.social import media, voicer

    scene, session, pid, natter = _numbers_session()
    mid, spec = _submitted_photo(session, natter)
    result = _ready(mid, session.save_id)
    caplog.set_level(logging.INFO)
    # At the hand-off: another build of the run, or another owner -- nothing written, nothing parked.
    media.hand_off(dataclasses.replace(spec, epoch=spec.epoch + 1), result)
    media.hand_off(dataclasses.replace(spec, owner="u_0123456789abcdef"), result)
    assert session.engine.state.social["media"][mid]["status"] == "submitted" and len(session.inbox) == 0
    # At the drain: an item of another epoch, or another account's, is dropped with a log line.
    session.inbox.put({"kind": "media", "payload": result, "epoch": session.epoch + 1, "account": session.owner})
    session.inbox.put({"kind": "media", "payload": result, "epoch": session.epoch, "account": "u_0123456789abcdef"})
    with _locked(session):
        assert voicer.drain_inbox(session) == 0
    assert session.engine.state.social["media"][mid]["status"] == "submitted"
    assert "another build's" in caplog.text and "another account's media" in caplog.text
    assert "its run is not live" in caplog.text


def test_a_result_for_a_released_run_writes_nothing(receipts_active) -> None:
    from engine.social import media

    scene, session, pid, natter = _numbers_session()
    mid, spec = _submitted_photo(session, natter)
    scene.store.delete(session.session_id)
    media.hand_off(spec, _ready(mid, session.save_id))
    assert session.engine.state.social["media"][mid]["status"] == "submitted" and len(session.inbox) == 0


def test_a_hand_off_reports_a_media_job_metric(receipts_active, monkeypatch) -> None:
    from engine.scenes import default_scene
    from engine.social import media

    seen: list[tuple[str, str]] = []
    monkeypatch.setattr(default_scene, "phone_metric", lambda account, event, status, ms: seen.append((event, status)))
    scene, session, pid, natter = _numbers_session()
    mid, spec = _submitted_photo(session, natter)
    media.hand_off(spec, _ready(mid, session.save_id))
    media.hand_off(dataclasses.replace(spec, epoch=spec.epoch + 1), _ready(mid, session.save_id))
    assert ("media_job", "ok") in seen and ("media_job", "dropped") in seen


# -- resume and drain ---------------------------------------------------------------------------------


def test_a_resume_resubmits_unfinished_jobs_with_their_request(receipts_active, monkeypatch) -> None:
    from engine.media.comfy import jobs

    _with_config({"phone_media.provider": "stub", "phone_media.portraits": "off"})
    scene, session, pid, natter = _numbers_session()
    mid, _spec = _submitted_photo(session, natter)
    with _locked(session):
        from engine.social import saves

        assert saves.save_now(session)
    recorder = _Recorder()
    monkeypatch.setattr(jobs, "get_media_worker", lambda: recorder)
    resumed = scene.store.resume(session.save_id)
    assert [s.mid for s in recorder.specs] == [mid]
    assert recorder.specs[0].values == {"positive": "x"}               # the stored request: idempotent
    assert recorder.specs[0].epoch == resumed.epoch and recorder.specs[0].session_id == resumed.session_id


def test_a_resume_under_procedural_turns_unfinished_jobs_into_tiles(receipts_active) -> None:
    scene, session, pid, natter = _numbers_session()
    mid, _spec = _submitted_photo(session, natter)
    with _locked(session):
        from engine.social import saves

        assert saves.save_now(session)
    resumed = scene.store.resume(session.save_id)
    assert resumed.engine.state.social["media"][mid]["status"] == "fallback"


def test_a_hosted_drain_stops_the_media_worker(receipts_active, media_root) -> None:
    from engine import hosting
    from engine.media.comfy import jobs

    worker = jobs.get_media_worker()
    assert hosting.drain(None, 0.2)
    assert jobs._worker is None and worker.join(5)


# -- the player's own (spec §13.7) --------------------------------------------------------------------


def test_the_player_sends_a_camera_roll_photo_and_a_subject(receipts_active) -> None:
    scene, session, pid, natter = _numbers_session()
    state = session.engine.state
    photos = list((state.social.get("player") or {}).get("photos") or [])
    assert photos, "the run's player has a camera roll"
    sent = _phone(scene, session, "send", target=natter, args={"kind": "photo", "photo_id": photos[0]}, text="me!")
    assert not sent["receipts"][0].get("refused"), sent["receipts"][0]
    row = _photo_row(state, "own")
    assert row["photo_id"] == photos[0] and row["sends"] == "photo" and row["priority"] == 1
    assert row["caption"] == "me!" and row["status"] == "fallback"     # procedural by default: a tile at once
    video = _phone(scene, session, "send", target=natter, args={"kind": "video", "subject": "my_walk"})
    assert not video["receipts"][0].get("refused"), video["receipts"][0]
    assert _photo_row(state, "own")["sends"] == "video"


def test_the_players_own_media_are_refused_in_words_where_they_cannot_go(receipts_active) -> None:
    scene, session, pid, natter = _numbers_session()

    def error(args: dict[str, Any], target: str = natter) -> str:
        receipt = _phone(scene, session, "send", target=target, args=args)["receipts"][0]
        assert receipt.get("refused"), receipt
        return str(receipt["result"]["error"])

    assert error({"kind": "photo"}) == "Pick a photo first."
    assert error({"kind": "video", "subject": "my_dinner"}) == "You can't send that as a video."
    assert error({"kind": "photo"}, target=f"matchstick:{pid}") == "Matchstick can't send photos"
    assert error({"kind": "voice"}) == "Say something first."         # T21: a voice note is its transcript


# -- the owner-scoped route ---------------------------------------------------------------------------


def test_the_media_route_is_owner_scoped(hosted_receipts) -> None:
    from engine.media.comfy import storage

    alice = hosted_receipts.login_and_start("alice")
    bob = hosted_receipts.login_and_start("bob")
    session = hosted_receipts.scene.store.live_sessions()
    a_run = next(s for s in session if s.session_id == alice.sid)
    folder = storage.phone_media_dir(alice.account_id, a_run.save_id)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "x1.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)
    url = storage.url_for(a_run.save_id, "x1.png")
    assert alice.client.get(url).status_code == 200
    assert bob.client.get(url).status_code == 404                    # another account's save answers as missing
    assert alice.client.get(f"/api/phone/media/{a_run.save_id}/..%2Fsave.json").status_code == 404
    assert alice.client.get(f"/api/phone/media/{a_run.save_id}/x2.png").status_code == 404
    assert alice.client.get("/api/phone/media/nosuchsave01/x1.png").status_code == 404
    assert hosted_receipts.hosted.client().get(url).status_code in (302, 303, 401)   # logged out: the gate first


def test_the_local_media_route_refuses_traversal(receipts_active) -> None:
    from engine.media.comfy import storage

    scene, session = _live_session()
    folder = storage.phone_media_dir("", session.save_id)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "x1.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    client = scene.app.test_client()
    assert client.get(storage.url_for(session.save_id, "x1.png")).status_code == 200
    for name in ("..%2F..%2Fsave.json", "x1.svg", "save.json"):
        assert client.get(f"/api/phone/media/{session.save_id}/{name}").status_code == 404


# -- the data -------------------------------------------------------------------------------------------


def test_media_yaml_is_checked_whole(receipts_active) -> None:
    from engine import social
    from engine.social import media

    data = social.data("media")
    assert media.media_faults(data, social.data("population"), social.data("relationships")) == []
    bad = json.loads(json.dumps(data))
    bad["subjects"][0]["when"] = "dancing"
    bad["subjects"][3]["requires_flag"] = "has_a_dragon"
    bad["budget"]["video"]["unlock_stage"] = "married"
    faults = dict(media.media_faults(bad, social.data("population"), social.data("relationships")))
    assert "subjects[0].when" in faults and "subjects[3].requires_flag" in faults
    assert "budget.video.unlock_stage" in faults
    with pytest.raises(ValueError, match="media.yaml"):
        media.check_data(bad, social.data("population"))


def test_a_bad_media_yaml_fails_at_load_and_in_the_validator(tmp_path, monkeypatch) -> None:
    import shutil

    from engine import social
    from engine.games import validation

    src = ROOT / "games" / "read-receipts" / "data" / "social"
    shutil.copytree(src, tmp_path / "social")
    path = tmp_path / "social" / "media.yaml"
    path.write_text(path.read_text(encoding="utf-8").replace("requires_flag: has_pet", "requires_flag: has_a_dragon"),
                    encoding="utf-8")
    monkeypatch.setattr(social, "social_dir", lambda: tmp_path / "social")
    monkeypatch.setattr(social, "_DATA_CACHE", None)
    with pytest.raises(ValueError, match=r"media.yaml: subjects\[3\].requires_flag"):
        social.load_all()
    assert social._DATA_CACHE is None
    real = validation._declared_dir
    monkeypatch.setattr(validation, "_declared_dir",
                        lambda manifest, key: tmp_path / "social" if key == "social" else real(manifest, key))
    issues = [i for i in validation.errors_only(validation.validate_story("read-receipts"))
              if i.source == "social/media.yaml"]
    assert [(i.ref_id, "has_a_dragon" in i.message) for i in issues] == [("subjects[3].requires_flag", True)]


def test_the_shipped_story_validates_clean_for_media() -> None:
    from engine.games.validation import errors_only, validate_story

    assert [i for i in errors_only(validate_story("read-receipts")) if "media" in i.source] == []


# -- review fix round 1 (T19 review I1, M1, M4) ----------------------------------------------------------


def test_a_result_of_another_request_under_the_rows_mid_is_refused(receipts_active) -> None:
    """I1: a result carries its job's request digest; a row made by a different request refuses it."""
    from engine.social import media

    scene, session, pid, natter = _numbers_session()
    mid, spec = _submitted_photo(session, natter)
    other = dataclasses.replace(spec, values={"positive": "someone else's photo"})
    assert other.digest() != spec.digest()
    media.hand_off(other, _ready(mid, session.save_id))
    assert session.engine.state.social["media"][mid]["status"] == "submitted"     # not applied
    media.hand_off(spec, _ready(mid, session.save_id))
    assert session.engine.state.social["media"][mid]["status"] == "ready"         # its own request's is


def test_a_fault_in_step_3_costs_the_jobs_never_the_action(receipts_active, monkeypatch, caplog) -> None:
    """M1: `submit_due` raising inside the mechanics action is logged; the action completes and the rows stay
    `requested` for the next one."""
    from engine.social import media

    _with_config({"phone_media.provider": "stub", "phone_media.portraits": "off"})
    scene, session, pid, natter = _numbers_session()
    with _locked(session) as state:
        message = media.messaging.new_message(state, natter, pid, "photo", bubbles=["look"], voiced=True,
                                              decision=dataclasses.asdict(media.send_decision("photo", "selfie_now")))
        mid = media.attach(state, pid, natter, message["id"], "photo", "selfie_now")

    def broken(session_: Any) -> list[Any]:
        raise RuntimeError("a fault building the job")

    monkeypatch.setattr(media, "jobs_for", broken)
    caplog.set_level(logging.WARNING)
    turn = _phone(scene, session, "wait", args={"until": "15m"})
    assert turn["receipts"][0]["success"]
    assert session.engine.state.social["media"][mid]["status"] == "requested"
    assert "Media jobs not submitted" in caplog.text


def test_no_portrait_is_made_for_someone_gone(receipts_active, monkeypatch) -> None:
    """M4: under on_match, a person who unmatched (gone) is never owed a portrait job."""
    from engine.media.comfy import jobs

    _with_config({"phone_media.provider": "stub", "phone_media.portraits": "on_match"})
    recorder = _Recorder()
    monkeypatch.setattr(jobs, "get_media_worker", lambda: recorder)
    scene, session = _live_session()
    pid = _matched_in(session, "matchstick").split(":")[1]
    turn = _phone(scene, session, "unmatch", target=pid)
    assert not turn["receipts"][0].get("refused"), turn["receipts"][0]
    _phone(scene, session, "wait", args={"until": "15m"})
    assert recorder.specs == [] and not session.engine.state.social["people"][pid].get("portrait")


def test_only_a_declared_value_not_offered_now_takes_the_rows_own_words(receipts_state, matched_numbers) -> None:
    """M2: the row's `refuse` words answer a declared value not offered now ("Give it a day"); a value the row
    never takes keeps the payload's own problem."""
    from engine.agents.tool_dispatcher import execute_phone_intent
    from tests.social_fixtures import _engine

    natter = matched_numbers("natter")
    pid = natter.split(":")[1]

    def ask(target: str, what: str) -> str:
        receipt = execute_phone_intent({"action": "ask", "target": target, "args": {"what": what}},
                                       _engine(receipts_state))
        assert receipt["refused"], receipt
        return str(receipt["result"]["error"])

    assert ask(natter, "smoke").startswith("what must be one of")          # malformed: never the row's words
    assert ask(f"matchstick:{pid}", "photo") == "Matchstick can't send photos"   # declared, not offered here


# -- voice notes (T21, spec §13.6) --------------------------------------------------------------------


def _speech_worker(stub: Any) -> Any:
    """The process's speech worker, speaking to the in-process TTS stub (no bind); dropped by `_reset_media`."""
    from engine.media import tts

    tts.reset_speech_worker()
    worker = tts.SpeechWorker(tts.TTSClient(base_url="http://tts.test", transport=stub.transport))
    with tts._worker_lock:
        tts._worker = worker
    worker.start()
    return worker


def _voice_message(state, thread: str, pid: str) -> str:
    from engine.social import messaging

    return messaging.new_message(state, thread, pid, "voice", bubbles=["hey you"])["id"]


def test_a_voice_note_with_tts_off_is_a_transcript_tile(receipts_state, matched_numbers) -> None:
    from engine.social import media

    thread = matched_numbers("natter")
    pid = thread.split(":")[1]
    mid = media.attach(receipts_state, pid, thread, _voice_message(receipts_state, thread, pid), "voice", "")
    row = receipts_state.social["media"][mid]
    media.voice_fallback(receipts_state, mid, transcript="ok so about saturday " * 3)
    assert row["status"] == "fallback" and row["url"] == ""
    assert row["seconds"] == pytest.approx(media.voice_note_seconds("ok so about saturday " * 3))
    assert row["transcript"] == ("ok so about saturday " * 3).strip()
    message = next(m for m in receipts_state.social["threads"][thread]["messages"] if m.get("media_id") == mid)
    assert message["transcript"] == row["transcript"]               # the memory and the payload read it there
    view = media.media_view(receipts_state, mid)
    assert view["kind"] == "voice" and view["status"] == "fallback"
    assert view["transcript"] == row["transcript"] and view["seconds"] == row["seconds"]


def test_a_voice_note_is_capped_at_max_seconds(receipts_state, matched_numbers) -> None:
    """400 words are 15 s of note (`voice.max_seconds`), and the kept transcript is 15 s of words at 150 a minute."""
    from engine import social
    from engine.social import media

    cap = float(social.data("media")["voice"]["max_seconds"])
    words = [f"word{i}" for i in range(400)]
    assert media.voice_note_seconds(" ".join(words)) == cap
    assert media.voice_max_words() == int(cap * 150 / 60)
    thread = matched_numbers("natter")
    pid = thread.split(":")[1]
    mid = media.attach(receipts_state, pid, thread, _voice_message(receipts_state, thread, pid), "voice", "")
    media.voice_fallback(receipts_state, mid, " ".join(words))
    row = receipts_state.social["media"][mid]
    assert row["transcript"].split() == words[:int(cap * 150 / 60)]     # cut by LENGTH, the words as written
    assert row["seconds"] == pytest.approx(int(cap * 150 / 60) * 60 / 150) and row["seconds"] <= cap   # the words kept
    assert media.voice_note_seconds("") == 0.0 and media.voice_note_seconds("hi") == 1.0


def test_the_settings_voice_list_is_tts_voices(receipts_active) -> None:
    from engine.api import settings
    from engine.config import get_config

    ids = [v["id"] for v in get_config().get("tts.voices")]
    row = next(r for r in settings.settings_view()["settings"] if r["key"] == "tts.voice")
    assert row["options"] == ids == ["neutral_male", "neutral_female", "warm_female", "old_male"]   # v0.21.1's literal
    assert "options_from" not in row
    assert settings.validate_setting("tts.voice", "warm_female")[0]
    assert not settings.validate_setting("tts.voice", "robot")[0]
    assert {v["sex"] for v in get_config().get("tts.voices")} == {"male", "female"}


def test_a_requested_voice_note_with_tts_off_lands_as_its_transcript(receipts_active, monkeypatch) -> None:
    """TTS off (the default): the person's voice note is its tile, its transcript the words they wrote for it."""
    import httpx

    from engine.social import messaging, voicer
    from tests.social_stub import StubVoice

    def refuse(*a: Any, **k: Any) -> Any:
        raise AssertionError("a voice note with TTS off contacted a server")

    monkeypatch.setattr(httpx.Client, "send", refuse)
    pushed: list[tuple[str, dict[str, Any]]] = []
    scene, session, pid, natter = _numbers_session()
    voicer.set_emitter(lambda _sid, event, body: pushed.append((event, body)))
    row = _ask_and_get_photo(scene, session, natter, monkeypatch, "voice")
    assert row["priority"] == 0 and row["subject"] == ""
    voicer.run_until_quiet(session, StubVoice("warm"))
    state = session.engine.state
    row = state.social["media"][row["mid"]]
    assert row["status"] == "fallback" and row["url"] == ""
    assert row["transcript"] == "this one's for you" and row["seconds"] == pytest.approx(1.6)
    message = next(m for m in state.social["threads"][natter]["messages"] if m.get("media_id") == row["mid"])
    assert message["kind"] == "voice" and message["transcript"] == "this one's for you"
    view = messaging.message_view(state, state.social["threads"][natter], message)
    assert view["transcript"] == "this one's for you" and view["media"]["seconds"] == pytest.approx(1.6)
    assert [b for e, b in pushed if e == "media_ready" and b["mid"] == row["mid"]]


def test_a_voice_note_is_spoken_in_their_voice_stored_and_served(receipts_active, media_root, monkeypatch) -> None:
    """TTS on, through the in-process stub: the transcript spoken in the person's own voice, uncached, a WAV
    beside the save's other media, handed off, pushed and served owner-scoped."""
    from engine.persistence import storage as roots
    from engine.social import population, voicer
    from tests.social_stub import StubVoice
    from tests.tts_stub import StubTTS

    _with_config({"tts.enabled": True})
    stub = StubTTS()
    _speech_worker(stub)
    pushed: list[tuple[str, dict[str, Any]]] = []
    scene, session, pid, natter = _numbers_session()
    voicer.set_emitter(lambda _sid, event, body: pushed.append((event, body)))
    row = _ask_and_get_photo(scene, session, natter, monkeypatch, "voice")
    voicer.run_until_quiet(session, StubVoice("warm"))
    state = session.engine.state
    _wait_until(lambda: state.social["media"][row["mid"]]["status"] == "ready", timeout=10)
    row = state.social["media"][row["mid"]]
    voice_id = population.profile(state, pid).voice_id
    assert voice_id and stub.requests == [{"text": "this one's for you", "voice": voice_id, "euler_steps": 3}]
    assert row["provider"] == "tts" and row["request"] == {"transcript": "this one's for you", "voice": voice_id}
    assert row["url"] == f"/api/phone/media/{session.save_id}/{row['mid']}-{row['digest']}.wav"
    assert row["seconds"] == pytest.approx(1.6) and row["transcript"] == "this one's for you"
    ready = [b for e, b in pushed if e == "media_ready" and b["mid"] == row["mid"]]
    assert ready and ready[-1]["kind"] == "voice" and ready[-1]["url"] == row["url"]
    served = scene.app.test_client().get(row["url"])
    assert served.status_code == 200 and served.data[:4] == b"RIFF" and served.data[8:12] == b"WAVE"
    audio = roots.audio_dir()
    assert not audio.exists() or not any(audio.iterdir())          # never the shared narration cache


@pytest.mark.parametrize("behaviour", ["down", "not_wav", "long", "expired"])
def test_a_voice_note_that_cannot_be_spoken_is_its_transcript_tile(receipts_active, media_root, monkeypatch,
                                                                    behaviour) -> None:
    """The server down, a body that is no WAV, audio far past the cap or a wait past `tts.job_timeout_seconds`:
    the transcript tile for good, nothing stored."""
    from engine.media.comfy import storage
    from engine.social import voicer
    from tests.social_stub import StubVoice
    from tests.tts_stub import StubTTS

    _with_config({"tts.enabled": True, **({"tts.job_timeout_seconds": -1} if behaviour == "expired" else {})})
    stub = StubTTS("ok" if behaviour == "expired" else behaviour)
    _speech_worker(stub)
    scene, session, pid, natter = _numbers_session()
    row = _ask_and_get_photo(scene, session, natter, monkeypatch, "voice")
    voicer.run_until_quiet(session, StubVoice("warm"))
    state = session.engine.state
    _wait_until(lambda: state.social["media"][row["mid"]]["status"] == "fallback", timeout=10)
    row = state.social["media"][row["mid"]]
    assert row["url"] == "" and row["error"] and row["transcript"] == "this one's for you"
    folder = storage.phone_media_dir(session.owner, session.save_id)
    assert not folder.exists() or not list(folder.glob("*.wav"))
    if behaviour == "expired":
        assert stub.requests == []                                    # never started


def test_a_resume_resubmits_a_voice_note_or_makes_it_its_tile(receipts_active, monkeypatch) -> None:
    from engine.media import tts
    from engine.social import media

    scene, session, pid, natter = _numbers_session()
    with _locked(session) as state:
        mid = media.attach(state, pid, natter, _voice_message(state, natter, pid), "voice", "")
        media.mark_submitted(state, mid, {"transcript": "back in five", "voice": "warm_female"},
                             account=session.owner, provider="tts", digest="d")
    calls: list[tuple[str, str]] = []

    class _Worker:
        def holds(self, key: tuple) -> bool:
            return False

        def submit(self, text: str, **kw: Any) -> int:
            calls.append((text, kw["voice"]))
            return 1

    monkeypatch.setattr(tts, "get_speech_worker", lambda: _Worker())
    _with_config({"tts.enabled": True})
    with _locked(session):
        assert media.resubmit_unfinished(session) == 1
    assert calls == [("back in five", "warm_female")]                 # the stored request, unchanged
    _with_config({"tts.enabled": False})
    with _locked(session) as state:
        assert media.resubmit_unfinished(session) == 0
        row = state.social["media"][mid]
    assert row["status"] == "fallback" and row["transcript"] == "back in five"


def test_a_voice_notes_transcript_is_checked_like_any_reply(receipts_state, matched_numbers) -> None:
    """Rule 1: the model writes only the transcript, and it is checked as their bubbles are (and dropped
    when it disagrees: the note keeps the message's own words)."""
    from types import SimpleNamespace

    from engine.social import agreement, media, voicing

    thread = matched_numbers("natter")
    pid = thread.split(":")[1]
    view = agreement.view_from_state(receipts_state, pid)
    decision = media.send_decision("voice", "")
    reply = {"bubbles": ["here you go"], "learned": [], "shared": [],
             "media": {"caption": "I'm not sending you a voice note"}}
    found = voicing.transcript_failures(reply, decision, view)
    assert found and {f.where for f in found} == {voicing.TRANSCRIPT} and found[0].check == "media_denied"
    assert voicing._drop(reply, found)["media"]["caption"] == ""
    assert voicing._drop(reply, found)["bubbles"] == ["here you go"]
    assert voicing.transcript_failures(reply, media.send_decision("photo", "selfie_now"), view) == []
    note = voicing._format_note(SimpleNamespace(proposals=()), decision)
    assert "transcript of the voice note" in note and f"at most {media.voice_max_words()} words" in note


def test_a_resumed_voice_note_is_retargeted_never_queued_twice(receipts_active, media_root) -> None:
    """Review I1: a real speech worker, paused (not started): two resubmissions of one in-flight note leave
    ONE request queued, and its result reaches the newest run (its epoch), not the one that first asked."""
    from engine.media import tts
    from engine.social import media
    from tests.tts_stub import StubTTS

    _with_config({"tts.enabled": True})
    stub = StubTTS()
    tts.reset_speech_worker()
    worker = tts.SpeechWorker(tts.TTSClient(base_url="http://tts.test", transport=stub.transport))
    with tts._worker_lock:
        tts._worker = worker                                           # paused: built, not started
    scene, session, pid, natter = _numbers_session()
    with _locked(session) as state:
        mid = media.attach(state, pid, natter, _voice_message(state, natter, pid), "voice", "")
        media.mark_submitted(state, mid, {"transcript": "back in five", "voice": "warm_female"},
                             account=session.owner, provider="tts", digest="d")
    first = session.epoch
    with _locked(session):
        assert media.resubmit_unfinished(session) == 1
    session.epoch = first + 1                                           # a newer build of the run resumes
    with _locked(session):
        assert media.resubmit_unfinished(session) == 1
    assert worker.pending() == 1                                       # one request, retargeted
    worker.start()
    state = session.engine.state
    _wait_until(lambda: state.social["media"][mid]["status"] == "ready", timeout=10)
    assert len(stub.requests) == 1 and state.social["media"][mid]["url"].endswith(".wav")


def test_a_voice_note_counts_against_the_daily_job_cap(receipts_active, monkeypatch, caplog) -> None:
    """Review I2: a voice note is one of the account's `phone_media.daily_job_cap` jobs, counted with its
    images and videos: past the cap it is its transcript tile, nothing queued, and it is logged."""
    from engine.media import tts
    from engine.media.comfy import jobs
    from engine.social import media
    from tests.tts_stub import StubTTS

    _with_config({"tts.enabled": True, "phone_media.daily_job_cap": 1})
    tts.reset_speech_worker()
    worker = tts.SpeechWorker(tts.TTSClient(base_url="http://tts.test", transport=StubTTS().transport))
    with tts._worker_lock:
        tts._worker = worker                                           # paused: nothing is spoken
    scene, session, pid, natter = _numbers_session()
    caplog.set_level(logging.INFO)
    with _locked(session) as state:
        first = media.attach(state, pid, natter, _voice_message(state, natter, pid), "voice", "")
        second = media.attach(state, pid, natter, _voice_message(state, natter, pid), "voice", "")
        media.submit_due(session)
        rows = state.social["media"]
    assert rows[first]["status"] == "submitted" and worker.pending() == 1      # the day's one job
    assert rows[second]["status"] == "fallback" and rows[second]["transcript"] == "hey you"
    assert worker.pending() == 1                                               # nothing more queued
    assert "Daily job cap reached" in caplog.text and "over the daily job cap" in caplog.text
    assert not jobs.get_media_worker().charge(                                 # one counter for every kind
        jobs.JobSpec(mid="x9", kind="image", owner=session.owner, save_id=str(session.save_id), session_id="s",
                     epoch=0, workflow="photo", values={}, priority=0, account=session.owner))


def test_a_transcript_is_cut_by_whole_words_to_the_servers_limit(receipts_active) -> None:
    """Review M4: never mid-word -- the note's words, then whole words off its end to `tts.max_chars`;
    the voice reply's grammar allows that many characters, not the caption's 200."""
    from engine.config import get_config
    from engine.social import media, voicing

    limit = int(get_config().get("tts.max_chars"))
    words = [f"{i:02d}" + "x" * 12 for i in range(60)]                     # 37 of them are > 400 characters
    cut = media.voice_transcript(" ".join(words))
    assert len(cut) <= limit and cut.split() == words[:len(cut.split())]
    assert len(cut.split()) < media.voice_max_words()
    schema = voicing.reply_schema(media.send_decision("voice", ""), (), voicing._moods())
    assert schema["properties"]["media"]["properties"]["caption"]["maxLength"] == limit
    photo = voicing.reply_schema(media.send_decision("photo", "selfie_now"), (), voicing._moods())
    assert photo["properties"]["media"]["properties"]["caption"]["maxLength"] == voicing.CAPTION_CHARS


# -- the Photos app's received media (T29, spec §18.2) --------------------------------------------------


def test_the_gallery_shows_their_photos_and_videos_once_voiced(receipts_state, matched_numbers) -> None:
    """The `gallery` section: each photo or video a person sent, newest first, as `media_view` shows it with
    who and where; a voice note stays in its thread, an unvoiced message's media waits for its words, and a
    person blocked takes theirs with them (their threads are no longer listed)."""
    from engine.social import matching, media, messaging, payload

    state = receipts_state
    natter = matched_numbers("natter")
    pid = natter.split(":")[1]
    photo = messaging.new_message(state, natter, pid, "photo", bubbles=["look"], voiced=True)
    photo_mid = media.attach(state, pid, natter, photo["id"], "photo", "selfie_now")
    media.mark_procedural(state, photo_mid)
    voice = messaging.new_message(state, natter, pid, "voice", bubbles=["hey you"])
    media.attach(state, pid, natter, voice["id"], "voice", "")
    waiting = messaging.new_message(state, natter, pid, "video", voiced=False, decision={"situation": "reply"})
    waiting_mid = media.attach(state, pid, natter, waiting["id"], "video", "selfie_now")
    rows = payload.phone_block(state)["gallery"]
    assert [r["mid"] for r in rows] == [photo_mid]
    (row,) = rows
    assert row == {**media.media_view(state, photo_mid), "pid": pid, "name": row["name"], "thread_id": natter,
                   "message_id": photo["id"], "at": state.social["media"][photo_mid]["created_at"]}
    assert row["name"] and "gallery" in payload.TIME_VARYING_SECTIONS
    # Voiced: its video shows too, newest first.
    waiting["voiced"] = True
    assert [r["mid"] for r in payload.phone_block(state)["gallery"]] == [waiting_mid, photo_mid]
    assert matching.block(state, pid)["ok"]
    assert payload.phone_block(state)["gallery"] == []
