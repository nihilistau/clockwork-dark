"""The shipped constants land each measured §17.2 row in its band, at every model latency (10 seeds).

v0.23.0 T9 (spec §3.4, §17, §19.8). `sim.report` plays the attentive player
(and, beside it, the flaky one for its own row) for six PHONE-ONLY sessions on
seeds 0-9 under the harness's default voice, the working neutral model
(`simulate_social.DEFAULT_VOICE`), at each of the three model latencies
(`--model-seconds` 6, 15 and 30): a band holds at all three or it is not a
band. The rows T9 cannot land, and those a phone-only session cannot reach,
are DEFERRED by data (each its CLAUDE.md row, never widened); T29's full pass
(world, scenes, deep growth) bands them. The tables are in the story's
CHANGELOG and `conversation.yaml`'s header.
"""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))                    # scripts.* importable (tests/test_generate_art_cli.py:33)

import scripts.simulate_social as sim  # noqa: E402
from tests.social_fixtures import receipts_active  # noqa: E402,F401

#: `slow`: a balance measurement (rule 10). The runs are in-process (`sim.report`), one after another.
pytestmark = pytest.mark.slow

#: The seeds and sessions the bands are pinned on (spec §17.1: 10 seeds; T29's full pass is 40).
SEEDS = range(10)
SESSIONS = 6
#: A report takes minutes; each test may take this many seconds.
TIMEOUT = 3600

#: The rows T9 measures (the brief's PHONE_BANDS) that hold at 6, 15 AND 30 model seconds (after T9's fix
#: round: the engine's `wait next` and promise windows fixed, closed promises bounded). A row that
#: misses at any latency moves to DEFERRED_ROWS with its measured values -- never widened, never
#: skipped (lesson 11). `person_promises_kept` is asserted (1.0), not banded (spec §17.2).
PHONE_BANDS = {
    "ghosted_per_episode.d0": (0.05, 0.15),
    "player_promises_kept.attentive": (0.95, 1.0),
}
#: T9's bands are the phone rows; T29 adds the rest.
BANDS = dict(PHONE_BANDS)

_MEASURED = ("(T9's phone-only harness: 10 seeds x 6 sessions, attentive, neutral model)")
_DEFERRED_T9 = ("so the row is deferred by data (`tests/test_simulate_social.py` `DEFERRED_ROWS`), not retuned "
                "or widened: measured again at T29b (world, scenes, deep growth), deferred to the end of v0.24.0.")
_T29 = "measured at T29b (world, scenes, deep growth), deferred to the end of v0.24.0: spec §24 stub table."


def _t9(row: str, band: str, measured: str) -> str:
    return f"READ RECEIPTS' `{row}` (spec §17.2, band {band}) measures {measured} {_MEASURED}, {_DEFERRED_T9}"


def _later(row: str, why: str) -> str:
    return f"READ RECEIPTS' `{row}` is not measured by T9's phone-only sessions ({why}): {_T29}"


_SCENE = "it needs depth 2, which needs a scene (growth.yaml `counts.scenes`; T13)"


#: Every other non-derived row, with the EXACT text of its CLAUDE.md "Deliberately deferred" row.
DEFERRED_ROWS: dict[str, str] = {
    # T9 measured these and they miss at one latency or more (6 / 15 / 30 model seconds).
    "exchanges_per_episode.d0": _t9("exchanges_per_episode.d0", "6-14", "6.0 / 6.0 / 5.0 at 6 / 15 / 30 s"),
    "end_reason.schedule": _t9("end_reason.schedule", "30-55%", "20.9% / 18.6% / 19.2% at 6 / 15 / 30 s"),
    "end_reason.energy": _t9("end_reason.energy", "25-50%", "11.0% / 9.0% / 8.9% at 6 / 15 / 30 s"),
    "end_reason.player": _t9("end_reason.player", "10-30%", "26.5% / 32.3% / 35.4% at 6 / 15 / 30 s"),
    "cold_unanswered_1h.d0": _t9("cold_unanswered_1h.d0", "15-35%", "65.1% / 63.7% / 61.3% at 6 / 15 / 30 s"),
    # Measured 16.8 at 30 s in v0.23.0's release run (the 6 and 15 s values were not recorded); the owner
    # deferred the balance pass (T29b) to v0.24.0, so the row is deferred by data, its band (6-15) unwidened.
    "chat_minutes_to_numbers.fast": _t9("chat_minutes_to_numbers.fast", "6-15 real minutes",
                                        "16.8 at 30 s (6 and 15 s not recorded)"),
    "chat_minutes_to_numbers.mid": _t9("chat_minutes_to_numbers.mid", "12-30 real minutes",
                                       "11.43 / 14.45 / 17.68 at 6 / 15 / 30 s"),
    "chat_minutes_to_numbers.slow": _t9("chat_minutes_to_numbers.slow", "25-60 real minutes",
                                        "14.25 / 17.95 / 25.3 at 6 / 15 / 30 s"),
    "numbers_within_session": _t9("numbers_within_session", "40-70%", "13.8% / 8.7% / 6.8% at 6 / 15 / 30 s"),
    "player_promises_kept.flaky": _t9("player_promises_kept.flaky", "55-75%",
                                      "74.5% / 75.9% / 74.4% at 6 / 15 / 30 s"),
    # The latency lever spec §20.2 pre-committed, `modes.chatting_after` 5, pushed it below its band.
    "full_replies_in_long_episodes": _t9("full_replies_in_long_episodes", "60% or more",
                                         "53.9% / 52.9% / 53.1% at 6 / 15 / 30 s, below its band since the "
                                         "latency lever `conversation.yaml` `modes.chatting_after` 5 (70.3% at "
                                         "30 s under 3, before T9's fix round)"),
    # Not measured phone-only: each with what it waits for.
    **{row: _later(row, _SCENE) for row in (
        "exchanges_per_episode.d2plus", "ghosted_per_episode.d2plus", "sessions_to_first_scene",
        "real_hours_to_depth.fast.2", "real_hours_to_depth.fast.3", "real_hours_to_depth.fast.4",
        "real_hours_to_depth.slow.2", "real_hours_to_depth.slow.3", "real_hours_to_depth.slow.4",
        "scene_band.great", "scene_band.good", "scene_band.fine", "scene_band.awkward", "scene_band.bad",
    )},
    **{row: _later(row, "life events are T17's") for row in (
        "life_events.player_per_week", "life_events.person_per_month_d2plus")},
    **{row: _later(row, "the long-term stages are T18's") for row in (
        "devoted.together_10h", "devoted.living_together_20h", "devoted.married_40h")},
    **{row: _later(row, "20 real hours of full sessions") for row in (
        "active_relationships_20h.bachelor", "active_relationships_20h.attentive")},
    **{row: _later(row, "`SAVE_SIZE_MEASURED` is re-pinned on full sessions") for row in (
        "save_bytes_day180.attentive", "save_bytes_day180.bachelor", "save_bytes_day180.devoted")},
    "events_per_jump_morning_day60": _later("events_per_jump_morning_day60", "a day-60 run of full sessions"),
}

#: Asserted, not banded (spec §17.2: "100%, asserted"): neither in BANDS nor deferred.
ASSERTED = ("person_promises_kept",)


def test_every_report_row_is_banded_or_deferred_exactly_once() -> None:      # v0.22's test, extended in place (F25)
    assert (set(BANDS) | set(DEFERRED_ROWS) | set(sim.DERIVED_ROWS) | set(ASSERTED) | set(sim.UNBANDED_ROWS)
            == set(sim.REPORT_ROWS))
    assert not set(sim.UNBANDED_ROWS) & (set(BANDS) | set(DEFERRED_ROWS) | set(sim.DERIVED_ROWS) | set(ASSERTED))
    assert not set(BANDS) & set(DEFERRED_ROWS)
    assert not (set(BANDS) | set(DEFERRED_ROWS)) & set(sim.DERIVED_ROWS)     # a derived row is never banded (§3.4)
    assert not set(ASSERTED) & (set(BANDS) | set(DEFERRED_ROWS) | set(sim.DERIVED_ROWS))


def test_every_deferred_row_is_recorded_in_claude_md() -> None:
    claude = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    for row, line in DEFERRED_ROWS.items():
        assert line and line in claude, f"{row}: its deferred row is not in CLAUDE.md"


@pytest.mark.timeout(TIMEOUT)
@pytest.mark.parametrize("model_seconds", sim.MODEL_SECONDS)
def test_phone_rows_hold_at_every_latency(receipts_active, model_seconds: float) -> None:
    rep = sim.report(SEEDS, sessions=SESSIONS, policy="attentive", voice_policy="neutral_model",
                     model_seconds=model_seconds)
    for row, (low, high) in BANDS.items():
        value = rep[row]
        assert value is not None and low <= value <= high, (row, value, model_seconds)
    assert rep["person_promises_kept"] == 1.0
    for row in sim.REPORT_ROWS:
        if row in DEFERRED_ROWS and DEFERRED_ROWS[row].endswith(_T29):
            assert rep[row] is None, f"{row} measures {rep[row]} phone-only: band it, or say why it is T29's"


def test_the_harness_never_resolves_the_real_storage_root(monkeypatch) -> None:
    """Review C1 (T5): a run built by any entry point (`run`, `write_day_save`, a wrapper) refuses before
    any write unless `CLOCKWORK_DATA_DIR` names a private root -- unset, or naming the owner's configured
    root, is a RuntimeError -- and nothing lands in either image directory."""
    from engine.config import get_config
    from engine.persistence import storage

    real = storage._anchored(str(get_config().get("storage.root", storage.DEFAULT_ROOT) or storage.DEFAULT_ROOT))
    real_images = real / "media" / "images"
    before = sorted(real_images.iterdir()) if real_images.is_dir() else []

    def files(path: Path) -> list[Path]:
        return sorted(path.iterdir()) if path.is_dir() else []

    temp_images = storage.image_dir()
    temp_before = files(temp_images)

    def past_the_guard() -> None:                 # the first step after the guard: never reached, never writes
        raise AssertionError("Phone got past the storage guard")

    monkeypatch.setattr(sim, "_ensure_active", past_the_guard)
    monkeypatch.delenv("CLOCKWORK_DATA_DIR", raising=False)
    with pytest.raises(RuntimeError, match="CLOCKWORK_DATA_DIR"):
        sim.Phone(0, "neutral_model")
    monkeypatch.setenv("CLOCKWORK_DATA_DIR", str(real))
    with pytest.raises(RuntimeError, match="real storage root"):
        sim.Phone(0, "neutral_model")
    assert files(real_images) == before
    assert files(temp_images) == temp_before


@pytest.mark.timeout(TIMEOUT)
def test_a_dead_model_server_progresses_slowly(receipts_active) -> None:
    """
    Spec §10.2's ruling, measured (v0.22.0 T26 fix round 2; v0.23.0 T9's sessions): with no model every
    reply is the engine's fallback, whose regard (`regard.fallback`, +1/+1) is capped an episode by
    `regard.fallback.per_episode` (3/2). Such a run DOES progress -- people reach the `everyday` rung and
    swap numbers -- but more slowly than a working neutral model, on the same seeds and sessions. The
    three are priced alike (`model_seconds` 0): a fallback costs no model time, so at a real latency the
    fallback player gets more exchanges into a session, which is pacing, not the voice's regard (T9's
    report: 3.17 numbers a run against the neutral model's 2.33 at 15 s).
    """
    seeds = range(6)
    none, neutral, warm = (sim.report(seeds, sessions=SESSIONS, policy="attentive", voice_policy=v,
                                      model_seconds=0, companion=False)
                           for v in ("no_model", "neutral_model", "romantic_model"))
    assert 0 < none["also.depth1_per_run"] < neutral["also.depth1_per_run"] <= warm["also.depth1_per_run"]
    assert 0 < none["also.numbers_per_run"] < neutral["also.numbers_per_run"] <= warm["also.numbers_per_run"]


@pytest.mark.timeout(TIMEOUT)
def test_a_run_on_disk_measures_the_same_as_one_in_memory(receipts_active, tmp_path, monkeypatch) -> None:
    """
    The mechanics are spill- and compaction-invariant (v0.22.0 T26): a run that makes a save's bounded
    state after every action (`saves.compact`) -- every thread past a SMALL keep spilled, every dead
    thread (here a 3-day fade, a 1-day quiet) emptied to its stamp, every swiped-only person cut to the
    swipe -- measures exactly what the same run keeping everything in state does, the measurements
    reading the archive back.
    """
    from engine import social
    from engine.social import archive, relationships, saves

    real_setting, real_block = social.setting, relationships._block
    monkeypatch.setattr(social, "setting", lambda key, default: {"state_messages": 12, "archive_dead_after_days": 1,
                                                                 "requests_kept": 2}.get(key, real_setting(key, default)))
    monkeypatch.setattr(relationships, "_block", lambda name: 3 if name == "fade_days" else real_block(name))
    held = sim.run(2, 8, "attentive", "romantic_model")
    seen = {"stamped": 0, "compacted": 0, "forgotten": 0}
    real_compact = saves.compact

    def counting(session):
        out = real_compact(session)
        state = session.engine.state
        seen["stamped"] = max(seen["stamped"], sum(1 for t in state.social["threads"].values() if t.get("stamp")))
        seen["forgotten"] = max(seen["forgotten"], sum(
            int(n) for p in state.social["people"].values()
            for counts in (p.get("promises_closed") or {}).values() for n in (counts or {}).values()))
        seen["compacted"] = max(seen["compacted"],
                                sum(1 for p in state.social["people"].values() if set(p) == {"apps"}))
        return out

    monkeypatch.setattr(saves, "compact", counting)
    spilled = sim.run(2, 8, "attentive", "romantic_model", disk=tmp_path)
    for row in (held, spilled):
        row.pop("wall_seconds")
    # The voice's input is the same on disk: its tail is read through the archive when a save moved the
    # thread's older messages out of state (T9 fix round 3, review M4), so the stub's prompt sizes match.
    assert held["prompt_tokens"] == spilled["prompt_tokens"] and held["prompt_tokens"]
    files = list(tmp_path.rglob(archive.ARCHIVE_FILE))
    assert files and files[0].stat().st_size > 10_000, "nothing spilled: the check is vacuous"
    assert seen["compacted"] >= 50, seen
    # The compaction paths the equality rests on really ran (review M1): threads emptied to their stamp,
    # and closed promises forgotten (`promises.forget_closed`).
    assert seen["stamped"] >= 1 and seen["forgotten"] >= 1, seen
    assert sum(len(p["theirs"]) for p in held["people"]) > 100
    assert json.dumps(held, sort_keys=True) == json.dumps(spilled, sort_keys=True)
