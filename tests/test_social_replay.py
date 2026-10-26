"""Replay (spec §19.1): the same seed and actions give the same state.social.

Also the balance harness's own guarantees (scripts/simulate_social.py, spec
§20; v0.23.0 §3.4, §17): a harness run starts no thread and still voices, a refused commit
leaves the slice as it was, the same seeds give the same report, a session prices its actions
in real seconds, a turnstile deferral cannot stall it, its stub proposes what the schema offers,
and on a schema offering none of that it is the suite's stub voice.
"""

from __future__ import annotations

import dataclasses
import json
import threading

import pytest

from tests.social_fixtures import receipts_active  # noqa: F401

WALL = {"last_active_wall"}


def _strip(slice_: dict) -> str:
    return json.dumps({k: v for k, v in slice_.items() if k not in WALL}, sort_keys=True)


def test_a_200_action_run_replays_byte_identical(receipts_active) -> None:
    import scripts.simulate_social as sim

    a = sim.scripted_run(seed=31, actions=200, voice_policy="warm")
    b = sim.scripted_run(seed=31, actions=200, voice_policy="warm")
    assert _strip(a.social) == _strip(b.social)


def test_with_regard_pinned_to_zero_two_voice_policies_give_the_same_mechanics(receipts_active) -> None:
    import scripts.simulate_social as sim

    a = sim.scripted_run(seed=31, actions=200, voice_policy="zero")
    b = sim.scripted_run(seed=31, actions=200, voice_policy="wordy")
    assert sim.mechanics_of(a) == sim.mechanics_of(b)
    # Not vacuous: the two runs voiced different words over the same mechanics.
    words = {json.dumps([m.get("bubbles") for t in s.social["threads"].values() for m in t["messages"]
                         if m["from"] not in ("player", "system")]) for s in (a, b)}
    assert len(words) == 2


def test_one_persons_draws_are_unchanged_by_a_third_persons_history(receipts_active) -> None:
    import scripts.simulate_social as sim

    a = sim.scripted_run(seed=31, actions=120, voice_policy="zero")
    b = sim.scripted_run(seed=31, actions=120, voice_policy="zero", extra_contact="p0899")
    assert sim.person_trace(a, "p0005") == sim.person_trace(b, "p0005")
    # Not vacuous: the extra contact is outside every other step of the script, it was matched
    # and written to, and someone the script itself talked to keeps the same trace.
    assert "p0899" not in a.social["people"]
    assert any(t["pid"] == "p0899" and t["messages"] for t in b.social["threads"].values())
    talked = sorted({t["pid"] for t in a.social["threads"].values() if sim.person_trace(a, t["pid"])})
    assert talked, "the script talked to nobody"
    for pid in talked:
        assert sim.person_trace(a, pid) == sim.person_trace(b, pid), pid


def test_a_harness_session_starts_no_thread_and_voices(receipts_active) -> None:
    import scripts.simulate_social as sim

    before = threading.active_count()
    state = sim.scripted_run(seed=31, actions=200, voice_policy="warm")
    assert threading.active_count() == before
    assert not any(t.name == "social-dirty-saver" for t in threading.enumerate())
    voiced = [m for t in state.social["threads"].values() for m in t["messages"]
              if m["from"] not in ("player", "system") and m.get("voiced") is True]
    assert voiced, "the harness voiced nothing: its passes read as cancelled (Plan decision 28)"


def _due_phone(sim, monkeypatch: pytest.MonkeyPatch):
    """A harness phone (romantic_model, seed 5) holding a due message, its voicing held back."""
    from engine.social import matching, messaging, voicer

    monkeypatch.setattr(matching, "likes_back", lambda *a, **k: True)
    real = voicer.run_until_quiet
    monkeypatch.setattr(voicer, "run_until_quiet", lambda *a, **k: 0)
    phone = sim.Phone(5, "romantic_model")
    for _ in range(4):
        card = phone.phone["deck"]["matchstick"]["card"]
        phone.act("swipe", card["pid"], {"dir": "like"})
    for _ in range(40):
        if messaging.unvoiced(phone.state):
            break
        phone.act("wait", args={"until": "1h"})
    assert messaging.unvoiced(phone.state), "nothing fell due"
    monkeypatch.setattr(voicer, "run_until_quiet", real)
    return phone


def test_a_refused_commit_leaves_the_slice_as_it_was(receipts_active, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    The branch the commit's snapshot exists for (v0.22.0 T26, which deleted
    the harness's ``light_commits``): ``social_voiced`` refuses an all-blank
    reply, and the scoped rollback leaves the slice byte-identical.
    """
    import scripts.simulate_social as sim
    from engine.session.store import release_turn
    from engine.social import voicer, voicing

    with sim._quiet_summaries():
        phone = _due_phone(sim, monkeypatch)
        try:
            p = voicer.VoicePass(phone.session, phone.session.epoch)
            assert phone.session.lock.acquire(blocking=False)
            try:
                snaps = voicer.snapshot(phone.session, p)
            finally:
                release_turn(phone.session)
            reply = dataclasses.replace(voicing.fallback_reply(snaps[0], "test"), bubbles=["   "])
            before = _strip(phone.state.social)
            assert voicer.commit(phone.session, p, reply) == "discarded"
            assert _strip(phone.state.social) == before
        finally:
            phone.close()


def test_a_reply_voiced_by_an_action_is_not_pending_in_its_payload(receipts_active) -> None:
    """
    The policies read ``Phone.phone`` after the action's voicing (review I1):
    a reply written in that pass shows its words, as a push shows it in play.
    """
    import scripts.simulate_social as sim
    from engine.social import messaging

    seen: list[str] = []

    def check(phone) -> None:
        for row in phone.phone.get("threads") or []:
            last = row.get("last")
            if not last or not last.get("pending"):
                continue
            t = messaging.thread(phone.state, row["thread_id"])
            shown = [m for m in t["messages"] if messaging.shown(m)]
            if shown[-1].get("voiced") is not False:
                seen.append(row["thread_id"])

    with sim._quiet_summaries():
        phone = sim.Phone(0, "romantic_model")
        try:
            phone.observers.append(check)
            policy = sim.POLICIES["slow"](phone, 0)
            voiced = 0
            while phone.now < 24 * 2:
                policy.step()
                voiced = sum(1 for t in phone.state.social["threads"].values() for m in t["messages"]
                             if m["from"] == t["pid"] and m.get("voiced") is True)
        finally:
            phone.close()
    assert voiced, "nothing was voiced: the check is vacuous"
    assert not seen, f"voiced replies shown as pending: {sorted(set(seen))[:5]}"


def test_the_report_has_every_row_and_replays(receipts_active) -> None:
    import scripts.simulate_social as sim

    first = sim.report([0, 1], sessions=2, policy="attentive", voice_policy="no_model")
    again = sim.report([0, 1], sessions=2, policy="attentive", voice_policy="no_model")
    assert first == again                                     # the same seeds, the same report
    assert set(sim.REPORT_ROWS) <= set(first)
    assert first["ratio.chat"] is not None and first["also.actions_per_run"] > 0
    assert first["ratio.world"] is not None                    # full sessions (T29): the world was played
    assert first["also.runs"] == 2                            # the attentive runs; the flaky companion's apart
    assert isinstance(first["also.refusals_per_run"], dict)
    assert "also.days_to_warming.romantic" in first            # one row per behaviours.yaml archetype
    extra = set(first) - set(sim.REPORT_ROWS)
    assert all(k.startswith("also.") for k in extra), sorted(extra)


def test_a_session_spends_its_real_seconds_then_sleeps(receipts_active) -> None:
    """T9 (spec §3.4): a phone-only session prices each action (`REAL_SECONDS`, the model's seconds per
    reply a send got, `read_bubble` per bubble read; a wait is free), stops once its budget is spent or
    its day is over, and goes to bed: it ends at the waking hour."""
    import scripts.simulate_social as sim

    with sim._quiet_summaries():
        phone = sim.Phone(4, "neutral_model")
        try:
            player = sim.POLICIES["attentive"](phone, 4)
            spans = [sim.Session(phone, player, model_seconds=30, real_seconds_budget=600, world=False).play()
                     for _ in range(2)]
            assert phone.now % 24 == pytest.approx(sim.HOUR_WAKE)
            assert all(s["real_seconds"] < 600 + 40 * 63 for s in spans)      # the wind-down's few sends past it
            sends = [c for c in phone.charges if c[2] >= sim.REAL_SECONDS["send"]]
            assert sends, "the sessions sent nothing: the check is vacuous"
            # A send that got a reply is priced its 30 s, the model's 30 s and the bubbles read.
            assert any(c[2] >= sim.REAL_SECONDS["send"] + 30 + sim.REAL_SECONDS["read_bubble"] for c in sends)
            assert all(c[2] > 0 for c in phone.charges)
        finally:
            phone.close()


def test_the_real_clock_prices_by_the_table() -> None:
    import scripts.simulate_social as sim

    clock = sim.RealClock(15.0)
    clock.charge("send", bubbles=2, replies=1)
    assert clock.spent == pytest.approx(30 + 2 * 3 + 15)
    clock.charge("wait")
    clock.charge("swipe")
    assert clock.spent == pytest.approx(30 + 6 + 15 + 4)
    assert not clock.over
    clock.charge("send", replies=200)
    assert clock.over


def test_the_stub_proposes_what_the_schema_offers(receipts_active) -> None:
    """Spec §17.1: a follow-up on one reply in ten, a promise on half the sign-offs offered one, and the
    reply's own statements (`followup_asked`, `opened_up`) true whenever the schema asks for them."""
    import scripts.simulate_social as sim

    def fmt(props):
        return {"json_schema": {"schema": {"properties": props}}}

    offer = {"followups": {"items": {"properties": {"when": {"enum": ["tomorrow", "days:2"]}}}},
             "promise": {"items": {"properties": {"window": {"enum": ["tonight", "morning"]}}}},
             "followup_asked": {"type": "boolean"}, "opened_up": {"type": "boolean"}}
    stub = sim.StubVoice("neutral")
    replies = [json.loads(stub([], fmt(offer))) for _ in range(20)]
    assert sum(1 for r in replies if r["followups"]) == 2
    assert next(r["followups"] for r in replies if r["followups"]) == [{"about": "how the week goes",
                                                                        "when": "tomorrow"}]
    assert sum(1 for r in replies if r["promise"]) == 10
    assert all(r["promise"][0]["window"] == "tonight" for r in replies if r["promise"])
    assert all(r["followup_asked"] is True and r["opened_up"] is True for r in replies)
    plain = json.loads(sim.StubVoice("neutral")([], fmt({})))
    assert not {"followups", "promise", "followup_asked", "opened_up"} & set(plain)


def test_a_turnstile_deferral_cannot_stall_a_run(receipts_active, monkeypatch: pytest.MonkeyPatch) -> None:
    """T8: a voicing pass that meets a held narration turnstile stops (`deferred`). A turnstile held on the
    harness's only thread is raised, never waited on; a deferral with nothing holding it (a world turn that
    has let go) is followed by another pass, and the due message is voiced."""
    import scripts.simulate_social as sim
    from engine.social import messaging, turnstile

    with sim._quiet_summaries():
        phone = _due_phone(sim, monkeypatch)
        try:
            gate = turnstile.of(phone.session)
            assert gate is not turnstile.NULL, "a READ RECEIPTS session has its own turnstile"
            assert gate.acquire_world(0.1)
            try:
                with pytest.raises(RuntimeError, match="turnstile"):
                    phone.voice()
            finally:
                gate.release(turnstile.WORLD)
            assert messaging.unvoiced(phone.state), "the held turnstile voiced something"
            real = gate.try_acquire_voice
            calls = {"n": 0}

            def busy_once() -> bool:
                calls["n"] += 1
                return False if calls["n"] == 1 else real()

            monkeypatch.setattr(gate, "try_acquire_voice", busy_once)
            phone.voice()
            assert calls["n"] >= 2 and not messaging.unvoiced(phone.state)
        finally:
            phone.close()


def test_the_latency_table_is_each_modes_cap_over_the_rate(receipts_active) -> None:
    """Spec §20.2 (T9): p50 at half the mode's cap, p95 at the cap, and with the starvation retry twice it."""
    import scripts.simulate_social as sim
    from engine.social import voicing

    table = sim.latency_table(20.0)
    for mode in ("quick", "chatting", "deep"):
        cap = voicing.mode_caps(mode)["max_tokens"]
        assert table[mode]["p50_s"] == pytest.approx(cap / 40.0, abs=0.05)
        assert table[mode]["p95_s"] == pytest.approx(cap / 20.0, abs=0.05)
        assert table[mode]["p95_with_retry_s"] == pytest.approx(cap / 10.0, abs=0.05)
    assert sim.latency_table(40.0)["quick"]["p95_s"] == pytest.approx(table["quick"]["p95_s"] / 2, abs=0.05)
    # T9 fix round 3 (review M6): the rate is prompt-eval weighted, so the table records no prompt tokens
    # it does not use.
    assert all(set(row) == {"max_tokens", "p50_s", "p95_s", "p95_with_retry_s"} for row in table.values())


def test_the_harness_stub_is_the_suites(receipts_active) -> None:
    import scripts.simulate_social as sim
    from tests.social_stub import POLICIES

    assert sim.STUB_POLICIES == POLICIES
    assert {v for v in sim.VOICES.values() if v} <= set(POLICIES)
    fmt = {"json_schema": {"schema": {"properties": {"proposals": {}}}}}
    from tests.social_stub import StubVoice

    for policy in POLICIES:
        assert sim.StubVoice(policy)([], fmt) == StubVoice(policy)([], fmt)


def test_the_cli_plays_read_receipts_only() -> None:
    import scripts.simulate_social as sim

    with pytest.raises(SystemExit):
        sim.main(["--game", "hue-and-cry", "--sessions", "1", "--seeds", "1"])


def test_the_scripted_run_is_away_72_hours_once(receipts_active, monkeypatch: pytest.MonkeyPatch) -> None:
    """T16: the replay script holds one away advance, on the harness's wall clock (never the real one)."""
    import scripts.simulate_social as sim

    calls: list[float] = []
    real = sim.Phone.away

    def away(self, hours: float) -> int:
        calls.append(hours)
        before = self.state.world_clock_hours
        applied = real(self, hours)
        assert self.state.world_clock_hours - before == pytest.approx(hours, abs=1e-9)
        return applied

    monkeypatch.setattr(sim.Phone, "away", away)
    state = sim.scripted_run(seed=31, actions=40, voice_policy="zero")
    assert calls == [sim.AWAY_ROW_HOURS]
    assert state.world_clock_hours > 19.0 + sim.AWAY_ROW_HOURS


def _owner_tree() -> dict[str, tuple[int, int]]:
    """Every file under the repository's own `data/` (the owner's storage root by default): size and mtime."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "data"
    return {str(p): (p.stat().st_size, p.stat().st_mtime_ns) for p in root.rglob("*") if p.is_file()} \
        if root.is_dir() else {}


def test_the_harness_runs_under_a_throwaway_storage_root(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    T26: a harness run's opening drew its scene art into the owner's
    `data/media/images/`. With no CLOCKWORK_DATA_DIR, `main` runs under a
    temporary root (the run itself stubbed here, so nothing is written if it
    did not), and gives the variable back.
    """
    import os
    from pathlib import Path

    import scripts.simulate_social as sim
    from engine.persistence import storage

    monkeypatch.delenv("CLOCKWORK_DATA_DIR", raising=False)
    roots: list[Path] = []
    monkeypatch.setattr(sim, "_main", lambda args: roots.append(storage.data_root()) or 0)
    assert sim.main(["--sessions", "1", "--seeds", "1"]) == 0
    repo = Path(__file__).resolve().parents[1]
    assert roots and repo not in roots[0].resolve().parents and roots[0].resolve() != repo / "data"
    assert not roots[0].exists()                                   # thrown away after the run
    assert "CLOCKWORK_DATA_DIR" not in os.environ


def test_a_harness_run_leaves_the_owners_data_untouched(receipts_active) -> None:
    """A real one-session run through `main`: every file under the repository's `data/` as it was."""
    import scripts.simulate_social as sim

    before = _owner_tree()
    assert sim.main(["--sessions", "1", "--seeds", "1", "--no-companion"]) == 0
    assert _owner_tree() == before


def test_a_harness_run_puts_logging_back_as_it_found_it(receipts_active) -> None:
    """`main` quiets logging for its run (`logging.disable(WARNING)`) and must restore the caller's level:
    left disabled, every later test in the process that asserts a WARNING through `caplog` failed
    (`tests/test_save_id_containment.py`, found in v0.23.0 T20)."""
    import logging

    import scripts.simulate_social as sim

    before = logging.root.manager.disable
    assert sim.main(["--sessions", "1", "--seeds", "1", "--no-companion"]) == 0
    assert logging.root.manager.disable == before
