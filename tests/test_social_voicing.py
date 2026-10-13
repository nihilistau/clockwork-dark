"""
The voicing call (v0.22.0 spec §11.1-11.4, T13): the snapshot, the prompt's
seven blocks, the per-call schema, conform on a no-grammar provider, the
agreement checks with one retry, and the engine-written fallback -- seeded,
final, and proposing relationships.yaml `regard.fallback` (the §10.2
ruling). No model is called: every `llm_fn` here is a stub.
"""

from __future__ import annotations

import copy
import dataclasses
import json
import threading
from pathlib import Path
from typing import Any

import pytest

from tests.social_fixtures import (  # noqa: F401
    _force_stage, matched, receipts_active, receipts_state,
)
from tests.social_stub import StubVoice

#: Words a correction line never carries (rule 12: it names facts, never a register).
RATING_WORDS = ("explicit", "content", "safe", "appropriate", "rating", "nsfw", "tone", "boundar")


def _good(text: str = "how was your day?", **regard: Any) -> str:
    row = {"warmth": 1, "trust": 0, "mood": "fond", **regard}
    return json.dumps({"bubbles": [{"text": text}], "regard": row, "learned": [], "shared": [], "proposals": []})


def _snapshot(*, decision: dict[str, Any] | None = None, **over: Any):
    """A PersonSnapshot for the matchstick pool's first person at stage `talking`: three tail
    messages, one due message, seed 4242 -- from `population.person` and literal dicts, no state."""
    from engine.social import population, voicing
    from engine.social.kinds import Decision

    index = population.pool("matchstick")[0]
    pid = population.pid_for(index)
    person = population.person(4242, index, {})
    tid = f"matchstick:{pid}"

    def msg(mid: str, sender: str, at: float, text: str, read_at: float | None) -> dict[str, Any]:
        return {"id": mid, "thread_id": tid, "from": sender, "kind": "text", "at": at, "bubbles": [text],
                "voiced": True, "decision": None, "media_id": None, "read_at": read_at, "transcript": None}

    tail = [msg("m1", pid, 30.0, "hey you", 30.5), msg("m2", "player", 30.6, "hi! how's your week going", 31.0),
            msg("m3", pid, 31.2, "good thanks, busy one", 31.4)]
    due = [{"id": "m5", "thread_id": tid, "from": pid, "kind": "text", "at": 31.9, "bubbles": [], "voiced": False,
            "decision": decision or dataclasses.asdict(Decision("reply")), "media_id": None, "read_at": None,
            "transcript": None}]
    tail.append(msg("m4", "player", 31.5, "what are you up to this weekend?", 31.8))
    fields: dict[str, Any] = dict(
        pid=pid, thread_id=tid, profile=dataclasses.asdict(person),
        dynamic={"stage": "talking", "warmth": 24, "trust": 12, "interest": 55, "mood": "fond", "mood_until": 40.0,
                 "familiarity": {"exchanges": 5, "contact_days": 2}, "rev": 3,
                 "history": [{"at": 20.0, "day": 1, "kind": "matched", "text": "Matched on Matchstick"}],
                 "canon": ["I grew up by the sea"], "knows": ["They run on Sundays"]},
        tail=tail, summary="", due=due, proposals=(),
        player={"name": "Sam", "age": 29, "sex": "female", "neighbourhood": "harbourside",
                "looking_for": "long_term", "hobbies": ["climbing", "running"], "attributes": {"job": "nurse"}},
        now={"day": 2, "hour": 8, "minute": 0, "weekday": "tue", "status": "free", "at": 32.0},
        contacts=("Jordan",), seed=4242,
    )
    fields.update(over)
    return voicing.PersonSnapshot(**fields)


# -- the prompt (§11.3) ---------------------------------------------------------------------------


def test_the_voice_prompt_is_exactly_its_blocks(receipts_active) -> None:
    from engine.social import voicing

    snap = _snapshot()
    msgs = voicing.messages(snap)
    assert [m["role"] for m in msgs] == ["system", "user"]
    assert msgs[0]["content"] == voicing.texter_prompt().persona
    titles = [part.split("\n", 1)[0] for part in msgs[1]["content"].split("\n\n") if part.split("\n", 1)[0].isupper()]
    assert titles == list(voicing.BLOCK_TITLES)
    assert "SITUATION:" in msgs[1]["content"].split("RIGHT NOW\n", 1)[1].split("\n\nFORMAT\n", 1)[0]


def test_the_system_message_is_the_persona_section_verbatim(receipts_active) -> None:
    """Plan decision 22: everything above `## Instructions`, byte for byte, and nothing of the table
    or the fallbacks; RIGHT NOW ends with the situation's own row."""
    from engine import social
    from engine.social import voicing

    text = (social.social_dir().parent.parent / "prompts" / "texter.md").read_text(encoding="utf-8")
    persona = voicing.texter_prompt().persona
    assert persona == text.split("## Instructions")[0].rstrip()
    msgs = voicing.messages(_snapshot())
    assert "## Instructions" not in msgs[0]["content"] and "## Fallbacks" not in msgs[0]["content"]
    now = msgs[1]["content"].split("RIGHT NOW\n", 1)[1].split("\n\nFORMAT\n", 1)[0]
    assert now.endswith(f"SITUATION: {voicing.texter_prompt().instructions['reply']}")


def test_the_prompt_reads_mood_as_it_is_now(receipts_active) -> None:
    """`relationships.mood_now`: a mood past its `mood_until` reads `neutral`."""
    from engine.social import voicing

    fond = voicing.messages(_snapshot())[1]["content"]
    assert "Your mood: fond." in fond
    later = _snapshot(now={"day": 2, "hour": 18, "minute": 0, "weekday": "tue", "status": "free", "at": 42.0})
    assert "Your mood: neutral." in voicing.messages(later)[1]["content"]


def test_the_prompt_carries_what_they_know_and_said(receipts_active) -> None:
    from engine.social import voicing

    user = voicing.messages(_snapshot())[1]["content"]
    assert "I grew up by the sea" in user.split("WHERE YOU ARE WITH THEM")[0]       # canon in WHO YOU ARE
    assert "They run on Sundays" in user.split("WHAT YOU KNOW ABOUT THEM\n")[1].split("\n\nTHE CONVERSATION")[0]
    conversation = user.split("THE CONVERSATION\n")[1].split("\n\nRIGHT NOW")[0]
    assert "Sam: what are you up to this weekend?" in conversation and "you: hey you" in conversation
    assert "Day 1: Matched on Matchstick" in user


# -- the schema (§11.2) ---------------------------------------------------------------------------


def test_no_media_key_without_media(receipts_active) -> None:
    from engine.social import voicing
    from engine.social.kinds import Decision

    assert "media" not in voicing.reply_schema(Decision("reply"), (), ("neutral",))["properties"]
    assert "media" in voicing.reply_schema(Decision("send_selfie", kind="photo", media_kind="photo"), (),
                                           ("neutral",))["required"]


def test_proposals_are_offered_only_when_legal(receipts_active) -> None:
    """No proposal legal: the key is left out, so a closed object forbids it (conform cannot hold an
    items-less `maxItems: 0`); legal ones are the enum."""
    from engine.social import voicing
    from engine.social.kinds import Decision

    assert "proposals" not in voicing.reply_schema(Decision("reply"), (), ("neutral",))["properties"]
    schema = voicing.reply_schema(Decision("reply", max_bubbles=2), ("offer_number",), ("neutral",))
    assert schema["properties"]["proposals"]["items"]["enum"] == ["offer_number"]
    assert schema["properties"]["bubbles"]["maxItems"] == 2


def test_a_no_grammar_provider_is_conformed(receipts_active) -> None:
    from engine.social import voicing

    stub = lambda msgs, fmt: ('{"bubbles":[{"text":"hey"}],"regard":{"warmth":9,"trust":0,"mood":"giddy"},'  # noqa: E731
                              '"learned":[],"shared":[],"proposals":["marry_me"],"extra":1}')
    reply = voicing.voice(_snapshot(), stub)
    assert reply.bubbles == ["hey"] and "marry_me" not in reply.proposals
    assert reply.regard == {"warmth": 4, "trust": 0, "mood": "neutral"}      # the schema's bound; an unknown mood
    assert not reply.fallback


def test_a_legal_proposal_survives_and_the_reply_is_held_to_its_bounds(receipts_active) -> None:
    from engine.social import voicing

    raw = json.dumps({"bubbles": [{"text": "x" * 400}, {"text": "  "}], "regard": {"warmth": -9, "trust": 5,
                      "mood": "playful"}, "learned": ["they climb", "they run", "a third"], "shared": ["y" * 300],
                      "proposals": ["offer_number", "offer_number", "cool_off"]})
    reply = voicing.voice(_snapshot(proposals=("offer_number",)), lambda m, f: raw)
    assert reply.bubbles == ["x" * 280] and reply.regard == {"warmth": -4, "trust": 2, "mood": "playful"}
    assert reply.learned == ["they climb", "they run"] and reply.shared == ["y" * 140]
    assert reply.proposals == ["offer_number"]


# -- the call, the checks, the retry -----------------------------------------------------------------


def test_a_good_reply_is_voiced_in_one_call(receipts_active) -> None:
    from engine.social import voicing

    stub = StubVoice("warm")
    reply = voicing.voice(_snapshot(), stub)
    assert stub.calls == 1 and not reply.fallback and reply.failures == []
    assert reply.bubbles == ["that sounds lovely, tell me more"]
    assert reply.regard == {"warmth": 3, "trust": 1, "mood": "fond"}
    assert reply.message_ids == ("m5",) and reply.pid == _snapshot().pid
    _msgs, fmt = stub.requests[0]
    assert fmt["type"] == "json_schema" and fmt["json_schema"]["name"] == "texter_reply"


def test_one_failure_retries_with_a_one_line_correction(receipts_active) -> None:
    from engine.social import voicing

    stub = StubVoice("warm", script=[_good("sent you a pic"), _good("how was your day?")])
    reply = voicing.voice(_snapshot(), stub)
    assert not reply.fallback and reply.bubbles == ["how was your day?"] and reply.failures == ["media_claimed"]
    assert stub.calls == 2
    second, _fmt = stub.requests[1]
    assert [m["role"] for m in second] == ["system", "user", "assistant", "user"]
    correction = second[-1]["content"]
    assert "\n" not in correction and "sent you a pic" in correction and "nothing is attached" in correction
    assert not any(word in correction.lower() for word in RATING_WORDS)


def test_two_agreement_failures_fall_back(receipts_active) -> None:
    from engine.social import voicing

    claims = StubVoice("warm", script=['{"bubbles":[{"text":"sent you a pic"}],"regard":{"warmth":1,"trust":0,'
                                       '"mood":"fond"},"learned":[],"shared":[],"proposals":[]}'] * 2)
    reply = voicing.voice(_snapshot(), claims)
    assert reply.fallback and reply.failures.count("media_claimed") == 2 and claims.calls == 2


def test_a_second_failure_drops_only_what_disagrees(receipts_active) -> None:
    from engine.social import voicing

    two = json.dumps({"bubbles": [{"text": "sent you a pic"}, {"text": "how was your day?"}],
                      "regard": {"warmth": 2, "trust": 1, "mood": "fond"}, "learned": [], "shared": [],
                      "proposals": []})
    reply = voicing.voice(_snapshot(), StubVoice(script=[two, two]))
    assert not reply.fallback and reply.bubbles == ["how was your day?"]
    assert reply.failures == ["media_claimed", "media_claimed"]


def test_an_unparsed_reply_is_retried_then_falls_back(receipts_active) -> None:
    from engine.social import voicing

    once = StubVoice("zero", fail=1)
    reply = voicing.voice(_snapshot(), once)
    assert not reply.fallback and reply.failures == ["unparsed"] and once.calls == 2
    twice = StubVoice("zero", fail=2)
    reply = voicing.voice(_snapshot(), twice)
    assert reply.fallback and reply.failures == ["unparsed", "unparsed"] and twice.calls == 2


def test_a_blocked_stub_waits_for_its_event(receipts_active) -> None:
    from engine.social import voicing

    gate = threading.Event()
    stub = StubVoice("cold", block=gate)
    out: list[Any] = []
    worker = threading.Thread(target=lambda: out.append(voicing.voice(_snapshot(), stub)))
    worker.start()
    worker.join(0.2)
    assert worker.is_alive() and not out
    gate.set()
    worker.join(5)
    assert out and out[0].regard == {"warmth": -2, "trust": -1, "mood": "annoyed"}


def test_the_media_caption_is_kept_when_media_is_attached(receipts_active) -> None:
    from engine.social import voicing
    from engine.social.kinds import Decision

    snap = _snapshot(decision=dataclasses.asdict(Decision("reply", kind="photo", media_kind="photo")))
    reply = voicing.voice(snap, StubVoice("wordy"))
    assert reply.caption == "this one's for you" and not reply.fallback


# -- the fallback (§11.4, §10.2's ruling) -----------------------------------------------------------


@pytest.mark.parametrize("why, llm", [("no server", None),
                                      ("starved", lambda m, f: (_ for _ in ()).throw(RuntimeError("starved")))])
def test_fallbacks_are_final_and_seeded(receipts_active, why, llm) -> None:
    from engine import social
    from engine.social import voicing

    a = voicing.voice(_snapshot(), llm)
    b = voicing.voice(_snapshot(), llm)
    fallback = social.data("relationships")["regard"]["fallback"]
    assert a.fallback and a.bubbles == b.bubbles
    # the §10.2 ruling (commit c30ab02): a fallback proposes regard.fallback, never zero
    assert a.regard == {"warmth": fallback["warmth"], "trust": fallback["trust"], "mood": "neutral"}
    assert a.regard["warmth"] > 0 and a.learned == a.shared == a.proposals == []


def test_the_fallback_is_a_pure_function_of_the_snapshot(receipts_active) -> None:
    """Seeded by `seed` and the first due message's id only: a different message id may pick another
    line, the same snapshot always the same; the line is the archetype's own for the situation."""
    from engine.social import voicing
    from engine.social.kinds import Decision

    snap = _snapshot()
    archetype = snap.profile["archetype"]
    rows = voicing.texter_prompt().fallbacks[archetype]
    picks = set()
    for n in range(12):
        due = [dict(snap.due[0], id=f"m{100 + n}")]
        line = voicing.fallback_reply(_snapshot(due=due), "test").bubbles[0]
        assert line == voicing.fallback_reply(_snapshot(due=due), "test").bubbles[0]
        assert line in rows["reply"]
        picks.add(line)
    assert len(picks) > 1, "twelve message ids all drew one line: the pick is not seeded by the message"
    declined = _snapshot(decision=dataclasses.asdict(Decision("answer_request", kind="decline", request_id="r1")))
    assert voicing.fallback_reply(declined, "test").bubbles[0] in rows["decline"]
    kept = voicing.fallback_reply(snap, "two failures", failures=["media_claimed", "stage_claimed"])
    assert kept.failures == ["media_claimed", "stage_claimed"] and kept.fallback


def test_no_model_play_moves_warmth_up_across_days(receipts_state, matched, monkeypatch) -> None:
    """The §10.2 ruling: fallback replies, applied through `social_regard` (`apply_regard`, as T14's
    commit does), grow warmth day by day -- and the per-day cap still holds within a day."""
    from engine import social
    from engine.social import relationships, voicing
    from tests.social_fixtures import _force_archetype

    pid = matched("matchstick").split(":", 1)[1]
    _force_archetype(monkeypatch, receipts_state, pid, "steady")        # no band cap, warmth_mult 1.0
    person = receipts_state.social["people"][pid]
    start = int(person.get("warmth", social.data("relationships")["regard"]["start"]["warmth"]))
    snap = _snapshot()
    cap = int(social.data("relationships")["regard"]["per_day_gain"]["warmth"])
    by_day = []
    for day in (1, 2, 3):
        for _ in range(20):                               # far more replies than the cap allows
            reply = voicing.fallback_reply(snap, "no model")
            assert relationships.apply_regard(receipts_state, pid, reply.regard, day=day)["ok"]
        by_day.append(int(receipts_state.social["people"][pid]["warmth"]))
    assert start < by_day[0] < by_day[1] < by_day[2], (start, by_day)
    assert by_day[0] - start <= cap


# -- the view, and no writes ----------------------------------------------------------------------


def _due(state, tid: str) -> None:
    from engine.social import messaging
    from engine.social.kinds import Decision

    pid = tid.split(":", 1)[1]
    messaging.new_message(state, tid, pid, "text", bubbles=(), voiced=False,
                          decision=dataclasses.asdict(Decision("reply")))


def test_view_from_snapshot_mirrors_view_from_state(receipts_state, matched, monkeypatch) -> None:
    """The carried T11/T12 item: `told` from their memory AND from every word the player wrote them
    still in state (not only the tail), `stage_before` as `view_from_state` reads it."""
    from engine import social
    from engine.game.effects import apply_effect
    from engine.social import agreement, messaging, population, voicing
    from tests.social_fixtures import _with

    first_tid = matched("matchstick")
    first = first_tid.split(":", 1)[1]
    second = matched("front_porch").split(":", 1)[1]
    third_tid = matched("matchstick")
    third = third_tid.split(":", 1)[1]
    second_name = population.profile(receipts_state, second).name
    third_name = population.profile(receipts_state, third).name
    assert messaging.send(receipts_state, first_tid, "text", f"{second_name} says hi")["ok"]
    assert messaging.send(receipts_state, first_tid, "text", "anyway, how is your week")["ok"]
    monkeypatch.setattr(social, "setting", _with(social.setting, **{"memory.verbatim": 1}))   # the naming is out of the tail
    # a name told in a message since spilled to the archive: only their memory holds it
    assert apply_effect(receipts_state, {"type": "social_memory", "op": "told", "pid": first,
                                         "names": [third_name]})["ok"]
    _force_stage(receipts_state, first, "talking")
    _force_stage(receipts_state, first, "winding_down")
    _due(receipts_state, first_tid)
    snap = voicing.snapshot_of(receipts_state, first_tid)
    assert snap is not None and snap.seed == receipts_state.rng_seed
    assert all(second_name not in " ".join(m["bubbles"]) for m in snap.tail)
    live = agreement.view_from_state(receipts_state, first)
    assert set(live.told) == {second_name, third_name} and live.stage_before == "talking"
    assert agreement.view_from_snapshot(snap) == live
    # and for a person with nothing told, at a live stage
    _due(receipts_state, third_tid)
    assert agreement.view_from_snapshot(voicing.snapshot_of(receipts_state, third_tid)) == \
        agreement.view_from_state(receipts_state, third)


def test_voice_writes_no_state(receipts_state, matched) -> None:
    """Rule 1: the reply is a proposal; `voice` changes neither the state nor its snapshot."""
    from engine.social import voicing

    tid = matched("matchstick")
    _due(receipts_state, tid)
    snap = voicing.snapshot_of(receipts_state, tid)
    before_state = copy.deepcopy(receipts_state.social)
    before_snap = copy.deepcopy(snap)
    for llm in (StubVoice("warm"), None, StubVoice("zero", fail=2)):
        voicing.voice(snap, llm)
    assert receipts_state.social == before_state and snap == before_snap


def test_a_thread_with_nothing_due_has_no_snapshot(receipts_state, matched) -> None:
    from engine.social import voicing

    tid = matched("matchstick")
    assert voicing.snapshot_of(receipts_state, tid) is None
    assert voicing.snapshot_of(receipts_state, "matchstick:p9999") is None


# -- texter.md, its situations, the profile -------------------------------------------------------


def test_every_situation_has_a_row(receipts_active) -> None:
    from engine import social
    from engine.social import voicing

    prompt = voicing.texter_prompt()
    assert set(voicing.SITUATIONS) <= set(prompt.instructions)
    assert voicing.situation_faults(prompt, social.data("behaviours")) == []


def test_an_unknown_situation_is_a_load_time_fault(receipts_active) -> None:
    from engine.social import voicing

    prompt = voicing.texter_prompt()
    behaviours = {"archetypes": {"steady": {"initiations": [{"id": "serenade", "kind": "text"}]}},
                  "arcs": {"turn": {"beat": {"instruction": "vanish"}}}}
    keys = [key for key, _ in voicing.situation_faults(prompt, behaviours)]
    assert "behaviours.yaml archetypes.steady.initiations[0].instruction" in keys
    assert "behaviours.yaml arcs.turn.beat.instruction" in keys
    thin = voicing.TexterPrompt(prompt.persona, {k: v for k, v in prompt.instructions.items() if k != "reply"}, {})
    assert ("SITUATIONS.reply", "the engine emits it; ## Instructions has no row for it") in \
        voicing.situation_faults(thin, {})
    with pytest.raises(ValueError, match=r"texter.md: fallbacks.dry_texter.serenade"):
        voicing.parse_texter("Persona.\n\n## Instructions\n\n- `reply`: Answer.\n\n## Fallbacks\n\n"
                             "```yaml\ndry_texter:\n  serenade: [\"la\"]\n```\n")


def test_the_validator_reports_a_situation_without_a_row(tmp_path: Path) -> None:
    import shutil

    from engine.games import registry
    from engine.games.validation import StoryValidator

    story = Path(__file__).resolve().parents[1] / "games" / "read-receipts"
    (tmp_path / "data").mkdir()
    shutil.copytree(story / "data" / "social", tmp_path / "data" / "social")
    (tmp_path / "prompts").mkdir()
    text = (story / "prompts" / "texter.md").read_text(encoding="utf-8")
    start = text.index("- `late_night`:")
    (tmp_path / "prompts" / "texter.md").write_text(text[:start] + text[text.index("\n", start) + 1:],
                                                   encoding="utf-8")
    validator = StoryValidator(registry.get("read-receipts"))
    validator._check_texter(tmp_path / "data" / "social")
    named = {(i.source, i.ref_id) for i in validator.issues if i.severity == "error"}
    assert named == {("prompts/texter.md", "behaviours.yaml archetypes.night_owl.initiations[0].instruction")}, \
        validator.issues
    clean = StoryValidator(registry.get("read-receipts"))
    clean._check_texter(story / "data" / "social")
    assert clean.issues == []


def test_the_texter_profile_overrides_big(receipts_active) -> None:
    from engine.llm import profiles

    cfg = profiles._config_for("texter")
    assert (cfg["require_tools"], cfg["min_context"], cfg["reasoning_budget"], cfg["lane"]) == (False, 4096, 0, "narration")
    assert (cfg["max_tokens"], cfg["reasoning"], cfg["temperature"]) == (360, "off", 0.9)


def test_production_llm_fn_calls_the_texter_profile(receipts_active, monkeypatch) -> None:
    """The production binding: profile texter, reasoning off, the grammar through the backend's ladder;
    a reply starved with no content raises, which `voice` turns into the fallback."""
    from types import SimpleNamespace

    from engine.llm import backend as backend_mod
    from engine.social import voicing

    seen: list[dict[str, Any]] = []

    class Backend:
        reply = SimpleNamespace(content=_good(), truncated=False)

        def structured_output(self, envelope):
            return {"type": "json_schema", "json_schema": envelope}

        def chat(self, msgs, **kw):
            seen.append(kw)
            return self.reply

    fake = Backend()
    monkeypatch.setattr(backend_mod, "get_backend", lambda: fake)
    reply = voicing.voice(_snapshot(), voicing.production_llm_fn())
    assert not reply.fallback and reply.bubbles == ["how was your day?"]
    assert seen[0]["profile"] == "texter" and seen[0]["reasoning"] == "off" and seen[0]["label"] == "social_voice"
    assert seen[0]["response_format"]["json_schema"]["name"] == "texter_reply"
    fake.reply = SimpleNamespace(content="", truncated=True)
    assert voicing.voice(_snapshot(), voicing.production_llm_fn()).fallback


# -- T13 fix round 1 (review minors 1, 2, 5, 6, 7) ------------------------------------------------


def test_the_offered_regard_is_narrowed_by_per_reply(receipts_active, monkeypatch) -> None:
    """Minor 1: the schema offers the intersection of its caps and relationships.yaml `regard.per_reply`,
    and a reply is held to the same bounds."""
    import copy as copy_

    from engine import social
    from engine.social import voicing
    from engine.social.kinds import Decision

    real = social.data

    def narrow(name: str):
        data = real(name)
        if name != "relationships":
            return data
        data = copy_.deepcopy(data)
        data["regard"]["per_reply"] = {"warmth": [-1, 2], "trust": [0, 9]}
        return data

    monkeypatch.setattr(social, "data", narrow)
    regard = voicing.reply_schema(Decision("reply"), (), ("neutral",))["properties"]["regard"]["properties"]
    assert (regard["warmth"]["minimum"], regard["warmth"]["maximum"]) == (-1, 2)
    assert (regard["trust"]["minimum"], regard["trust"]["maximum"]) == (0, 2)     # the schema's cap still holds
    reply = voicing.voice(_snapshot(), lambda m, f: _good(warmth=4, trust=-2))
    assert (reply.regard["warmth"], reply.regard["trust"]) == (2, 0)


def test_right_now_reads_the_clock_from_total_minutes(receipts_state, matched) -> None:
    """Minor 2: 31.9999 hours is 08:00 on the clock, never 07:00."""
    import math

    from engine.game import clock
    from engine.social import voicing

    tid = matched("matchstick")
    now = receipts_state.world_clock_hours
    target = math.floor(now) + 1.9999
    clock.advance_time(receipts_state, target - now)
    _due(receipts_state, tid)
    snap = voicing.snapshot_of(receipts_state, tid)
    assert (snap.now["hour"], snap.now["minute"]) == ((math.floor(now) + 2) % 24, 0)
    assert f"{(math.floor(now) + 2) % 24:02d}:00, day" in voicing.messages(snap)[1]["content"]


@pytest.mark.parametrize("with_model", [False, True])
def test_a_content_fault_falls_back_on_both_paths(receipts_active, caplog, with_model) -> None:
    """Minor 5 (ruling): a situation texter.md has no row for never raises; with or without a model it
    falls back, logged at ERROR, and no model is called."""
    import logging

    from engine.social import voicing
    from engine.social.kinds import Decision

    snap = _snapshot(decision=dataclasses.asdict(Decision("serenade")))
    stub = StubVoice("warm")
    with caplog.at_level(logging.ERROR, logger="engine.social.voicing"):
        reply = voicing.voice(snap, stub if with_model else None)
    assert reply.fallback and reply.bubbles
    assert stub.calls == 0
    assert any(r.levelno == logging.ERROR and "serenade" in r.getMessage() for r in caplog.records)


def test_every_fallback_row_agrees_with_its_situation(receipts_active) -> None:
    """Minor 6: fallbacks are final and never checked at run time, so every line of every row passes
    `agreement.check` for its own situation (a `decline` row against a decline decision)."""
    from engine.social import agreement, voicing
    from engine.social.kinds import Decision

    snap = _snapshot()
    view = agreement.AgreementView(stage="talking", person=voicing.person_of(snap), player=dict(snap.player),
                                   contacts=("Jordan", "Maya", "Kai"))
    prompt = voicing.texter_prompt()
    bad = []
    for archetype, rows in prompt.fallbacks.items():
        for key, lines in rows.items():
            decline = key == voicing.DECLINE_KEY
            decision = Decision("answer_request" if decline else key, kind="decline" if decline else "text",
                                max_bubbles=1)
            for line in lines:
                found = agreement.check({"bubbles": [line]}, decision, view)
                if found:
                    bad.append((archetype, key, line, [f.check for f in found]))
    assert bad == []


def test_an_unparsed_reply_is_retried_with_one_line(receipts_active) -> None:
    """Minor 7: the retry after a reply that did not parse asks for the JSON object only."""
    from engine.social import voicing

    stub = StubVoice("zero", fail=1)
    reply = voicing.voice(_snapshot(), stub)
    second, _fmt = stub.requests[1]
    assert not reply.fallback and [m["role"] for m in second] == ["system", "user", "assistant", "user"]
    assert second[-1]["content"] == voicing.JSON_ONLY


def test_the_validator_requires_a_post_meet_row(tmp_path: Path) -> None:
    """T31 fix: meet-ups emit `post_meet` (meets.py), so a texter.md without its row is a validator
    error like any other situation the engine emits, not a reply that fails in play."""
    import shutil

    from engine.games import registry
    from engine.games.validation import StoryValidator
    from engine.social import voicing

    assert "post_meet" in voicing.SITUATIONS
    story = Path(__file__).resolve().parents[1] / "games" / "read-receipts"
    (tmp_path / "data").mkdir()
    shutil.copytree(story / "data" / "social", tmp_path / "data" / "social")
    (tmp_path / "prompts").mkdir()
    text = (story / "prompts" / "texter.md").read_text(encoding="utf-8")
    start = text.index("- `post_meet`:")
    (tmp_path / "prompts" / "texter.md").write_text(text[:start] + text[text.index("\n", start) + 1:],
                                                   encoding="utf-8")
    validator = StoryValidator(registry.get("read-receipts"))
    validator._check_texter(tmp_path / "data" / "social")
    named = {(i.source, i.ref_id) for i in validator.issues if i.severity == "error"}
    assert named == {("prompts/texter.md", "SITUATIONS.post_meet")}, validator.issues


def test_right_now_names_a_missing_row_as_a_content_fault(receipts_active) -> None:
    """T31 fix: `_right_now`'s table lookup raises the content fault `voice` falls back on (a
    ValueError naming the situation), never a bare KeyError, whoever calls it."""
    from engine.social import voicing
    from engine.social.kinds import Decision

    snap = _snapshot(decision=dataclasses.asdict(Decision("serenade")))
    with pytest.raises(ValueError, match="serenade"):
        voicing._right_now(snap, voicing.texter_prompt())
