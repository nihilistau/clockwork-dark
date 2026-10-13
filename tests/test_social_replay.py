"""Replay (spec §19.1): the same seed and actions give the same state.social.

Also the balance harness's own guarantees (scripts/simulate_social.py, spec
§20): a harness run starts no thread and still voices, a refused commit
leaves the slice as it was, the same seeds give the same report, and its stub voice is the
suite's.
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

    first = sim.report([0, 1], 4, "attentive", "no_model")    # 4 days: likes 3 days before the end count
    again = sim.report([0, 1], 4, "attentive", "no_model")
    assert first == again                                     # the same seeds, the same report
    assert set(sim.REPORT_ROWS) <= set(first)
    assert first["like_to_match.matchstick"] is not None
    assert first["turners_turned_60d"] is None                # censored: no 4-day run has 60 days after talking
    assert isinstance(first["also.refusals_per_run"], dict)
    assert "days_to_warming.romantic" in first                 # one row per behaviours.yaml archetype
    extra = set(first) - set(sim.REPORT_ROWS)
    assert all(k.startswith(("days_to_", "also.")) for k in extra), sorted(extra)


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
        sim.main(["--game", "hue-and-cry", "--days", "1", "--seeds", "1"])


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


def test_the_away_row_counts_one_advances_events(receipts_active, monkeypatch: pytest.MonkeyPatch) -> None:
    import scripts.simulate_social as sim

    monkeypatch.setattr(sim, "AWAY_ROW_DAYS", 1)
    rows = [sim.run(seed, 1, "attentive", "zero") for seed in (0, 1)]
    counts = [r["away_events"] for r in rows]
    assert all(isinstance(c, int) and c > 0 for c in counts), counts   # 72 hours hold at least three dailies
    assert sim.fold(rows)["events_per_72h_away_day60"] == max(counts)
    assert sim.run(0, 1, "attentive", "zero")["away_events"] == counts[0]   # replays


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
    assert sim.main(["--days", "1", "--seeds", "1"]) == 0
    repo = Path(__file__).resolve().parents[1]
    assert roots and repo not in roots[0].resolve().parents and roots[0].resolve() != repo / "data"
    assert not roots[0].exists()                                   # thrown away after the run
    assert "CLOCKWORK_DATA_DIR" not in os.environ


def test_a_harness_run_leaves_the_owners_data_untouched(receipts_active) -> None:
    """A real one-day run through `main`: every file under the repository's `data/` as it was."""
    import scripts.simulate_social as sim

    before = _owner_tree()
    assert sim.main(["--days", "1", "--seeds", "1"]) == 0
    assert _owner_tree() == before
