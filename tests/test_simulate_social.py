"""The shipped constants land each measured §17.2 row in its band (spec §3.4, §17, §19.8).

Two measurements, two shapes.

**Full sessions (v0.24.0 T11, v0.23.0 T29b).** The harness's full sessions (the phone, capped at
`simulate_social.PHONE_SHARE` of the session, then the world day: work, dinner, plans, scenes, the morning
after, life events, the long-term stages) were measured at the OWNER's scale (2026-10-24): 10 seeds x 60
sessions, `--no-companion`, the neutral model; every policy at 15 model seconds, and `attentive` at 6, 15 and
30 s (and under the romantic, cold, zero and no-model voices: reported, not banded). An `attentive` row is a
band only if it holds at all three latencies; a `devoted`, `bachelor` or `flaky` row is banded at 15 s ONLY,
which `FULL_MEASURED` and its CLAUDE.md row say. A 60-session run takes 15-25 minutes, so the suite does not
replay the 160: `FULL_MEASURED` holds what was measured, and a fast test holds it to the bands. Re-measure
with `scripts/simulate_social.py --sessions 60 --seeds 10 --no-companion ...` (the story CHANGELOG has the
tables) after changing any balance constant (rule 10), and update both.

**Phone-only sessions (v0.23.0 T9's shape, `world=False`).** `sim.report` plays the attentive player (and,
beside it, the flaky one) for six phone-only sessions on seeds 0-9 at each latency, in the suite (`slow`):
`PHONE_BANDS` hold there at all three.

The rows that miss are DEFERRED by data (each its CLAUDE.md row, never widened). The day-180 save rows are
pinned by `tests/test_social_save_size.py`.
"""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))                    # scripts.* importable (tests/test_generate_art_cli.py:33)

import scripts.simulate_social as sim  # noqa: E402
from tests.social_fixtures import receipts_active  # noqa: E402,F401

#: The seeds and sessions the phone-only bands are pinned on (spec §17.1: 10 seeds).
SEEDS = range(10)
SESSIONS = 6
#: A report takes minutes; each test may take this many seconds.
TIMEOUT = 3600

#: The rows that hold PHONE-ONLY (T9's shape) at 6, 15 AND 30 model seconds, replayed in the suite (`slow`).
#: Re-measured v0.24.0 T11: ghosted 5.1 / 5.4 / 6.8%, the attentive player's own promises 1.0 / 1.0 / 1.0.
PHONE_BANDS = {
    "ghosted_per_episode.d0": (0.05, 0.15),
    "player_promises_kept.attentive": (0.95, 1.0),
}

#: The full-session rows that land in their band (spec §17.2), with what v0.24.0 T11 measured (10 seeds x 60
#: sessions, neutral model, `--no-companion`): `attentive` at 6 / 15 / 30 s, every other policy at 15 s only
#: (the owner's scale). Measured by hand, not replayed here: update both after any balance change (rule 10).
FULL_BANDS: dict[str, tuple[float, float]] = {
    "end_reason.player": (0.10, 0.30),
    "ghosted_per_episode.d0": (0.05, 0.15),
    "ghosted_per_episode.d2plus": (0.0, 0.03),
    "chat_minutes_to_numbers.mid": (12.0, 30.0),
    "real_hours_to_depth.fast.2": (1.0, 2.0),
    "real_hours_to_depth.fast.3": (3.0, 5.0),
    "scene_band.great": (0.10, 0.20),
    "scene_band.good": (0.25, 0.40),
    "scene_band.fine": (0.20, 0.30),
    "scene_band.bad": (0.05, 0.15),
    "player_promises_kept.attentive": (0.95, 1.0),
    "player_promises_kept.flaky": (0.55, 0.75),
    "life_events.person_per_month_d2plus": (0.5, 1.5),
    "devoted.living_together_20h": (0.20, 0.50),
    "devoted.married_40h": (0.10, 0.30),
    "events_per_jump_morning_day60": (0, 1500),
}
_A6, _A15, _A30, _D15 = "attentive 6 s", "attentive 15 s", "attentive 30 s", "devoted 15 s"
FULL_MEASURED: dict[str, dict[str, float]] = {
    "end_reason.player": {_A6: 0.141, _A15: 0.159, _A30: 0.146},
    "ghosted_per_episode.d0": {_A6: 0.062, _A15: 0.068, _A30: 0.066},
    "ghosted_per_episode.d2plus": {_A6: 0.015, _A15: 0.005, _A30: 0.008},
    "chat_minutes_to_numbers.mid": {_A6: 12.62, _A15: 14.75, _A30: 19.77},
    "real_hours_to_depth.fast.2": {_D15: 1.94},
    "real_hours_to_depth.fast.3": {_D15: 3.06},
    "scene_band.great": {_A6: 0.162, _A15: 0.162, _A30: 0.136},
    "scene_band.good": {_A6: 0.31, _A15: 0.34, _A30: 0.354},
    "scene_band.fine": {_A6: 0.215, _A15: 0.234, _A30: 0.226},
    "scene_band.bad": {_A6: 0.101, _A15: 0.111, _A30: 0.134},
    "player_promises_kept.attentive": {_A6: 0.995, _A15: 1.0, _A30: 0.997},
    "player_promises_kept.flaky": {"flaky 15 s": 0.699},
    "life_events.person_per_month_d2plus": {_A6: 1.105, _A15: 1.269, _A30: 1.233},
    "devoted.living_together_20h": {_D15: 0.2},
    "devoted.married_40h": {_D15: 0.3},
    "events_per_jump_morning_day60": {_A6: 26, _A15: 25, _A30: 14},
}
#: The balance files `FULL_MEASURED` was measured on (v0.24.0 T11; each carries a "Measured T11" header), and a
#: sha256 of their PARSED content (comments and layout do not move it; any value does). A change fails
#: `tests/test_social_balance_pin.py` until the 160 runs are re-measured (rule 10) and `FULL_MEASURED`, the
#: CLAUDE.md rows and this digest are updated together (v0.24.0 T14).
FULL_MEASURED_DATA = ("behaviours", "conversation", "growth", "life_events", "plans", "promises", "relationships",
                      "scenes")
FULL_MEASURED_DATA_SHA256 = "9107cac84f1505d45c22d7f7200e9bd268cc93a6ad1d0e9bab3722c5705d652a"
BANDS = {**PHONE_BANDS, **FULL_BANDS}
#: Pinned by `tests/test_social_save_size.py` (`SAVE_SIZE_MEASURED`, under 1 MB per policy), not by a report.
SAVE_ROWS = ("save_bytes_day180.attentive", "save_bytes_day180.bachelor", "save_bytes_day180.devoted")

_FULL = "(v0.24.0 T11's full sessions: 10 seeds x 60 sessions, neutral model, the owner's scale)"
_DEFERRED = ("so the row is deferred by data (`tests/test_simulate_social.py` `DEFERRED_ROWS`), not retuned or "
             "widened.")


def _t11(row: str, band: str, measured: str) -> str:
    return f"READ RECEIPTS' `{row}` (spec §17.2, band {band}) measures {measured} {_FULL}, {_DEFERRED}"


_A = "attentive at 6 / 15 / 30 s"
_D = "devoted at 15 s only"

#: Every other non-derived row, with the EXACT text of its CLAUDE.md "Deliberately deferred" row.
DEFERRED_ROWS: dict[str, str] = {
    "exchanges_per_episode.d0": _t11("exchanges_per_episode.d0", "6-14", f"7 / 6 / 5, {_A}"),
    "exchanges_per_episode.d2plus": _t11("exchanges_per_episode.d2plus", "12-30", f"10 / 9 / 5, {_A}"),
    "end_reason.schedule": _t11("end_reason.schedule", "30-55%", f"14.4% / 13.6% / 15.1%, {_A}"),
    "end_reason.energy": _t11("end_reason.energy", "25-50%", f"16.9% / 14.4% / 11.2%, {_A}"),
    "cold_unanswered_1h.d0": _t11("cold_unanswered_1h.d0", "15-35%", f"68.7% / 67.2% / 73.6%, {_A}"),
    "chat_minutes_to_numbers.fast": _t11("chat_minutes_to_numbers.fast", "6-15 real minutes",
                                         f"11.0 / 11.93 / 16.42, {_A}"),
    "chat_minutes_to_numbers.slow": _t11("chat_minutes_to_numbers.slow", "25-60 real minutes",
                                         f"18.08 / 19.8 / 25.35, {_A}"),
    "numbers_within_session": _t11("numbers_within_session", "40-70%",
                                   f"0.7% / 1.1% / 0.8%, {_A} (phone-only 11.0% / 10.5% / 8.3%)"),
    "sessions_to_first_scene": _t11("sessions_to_first_scene", "1-3", f"15 / 14.5 / 16.5, {_A}"),
    "real_hours_to_depth.fast.4": _t11("real_hours_to_depth.fast.4", "6-10", f"5.23, {_D}"),
    "real_hours_to_depth.slow.2": _t11("real_hours_to_depth.slow.2", "3-6", f"2.39, {_D}"),
    "real_hours_to_depth.slow.3": _t11("real_hours_to_depth.slow.3", "7-12", f"3.78, {_D}"),
    "real_hours_to_depth.slow.4": _t11("real_hours_to_depth.slow.4", "14-24", f"5.47, {_D}"),
    "scene_band.awkward": _t11("scene_band.awkward", "10-20%",
                               f"21.2% / 15.4% / 15.1%, {_A}, after the one end-bands round"),
    "full_replies_in_long_episodes": _t11("full_replies_in_long_episodes", "60% or more",
                                          f"59.9% / 57.9% / 57.9%, {_A}"),
    "life_events.player_per_week": _t11("life_events.player_per_week", "1-3", f"0.90 / 0.92 / 0.93, {_A}"),
    "devoted.together_10h": _t11("devoted.together_10h", "40-70%", f"10%, {_D}"),
    "active_relationships_20h.bachelor": _t11("active_relationships_20h.bachelor", "3-8",
                                              "10, bachelor at 15 s only"),
    "active_relationships_20h.attentive": _t11("active_relationships_20h.attentive", "3-8",
                                               f"12 / 10.5 / 9, {_A}"),
}

#: Asserted, not banded (spec §17.2: "100%, asserted"): neither in BANDS nor deferred. 1.0 in every T11 config.
ASSERTED = ("person_promises_kept",)

#: The rows a phone-only session cannot measure (no world, no scenes, six sessions): None there.
FULL_ONLY = (
    "ratio.world", "exchanges_per_episode.d2plus", "ghosted_per_episode.d2plus", "sessions_to_first_scene",
    "real_hours_to_depth.fast.2", "real_hours_to_depth.fast.3", "real_hours_to_depth.fast.4",
    "real_hours_to_depth.slow.2", "real_hours_to_depth.slow.3", "real_hours_to_depth.slow.4",
    "scene_band.great", "scene_band.good", "scene_band.fine", "scene_band.awkward", "scene_band.bad",
    "life_events.person_per_month_d2plus", "devoted.together_10h", "devoted.living_together_20h",
    "devoted.married_40h", "active_relationships_20h.bachelor", "active_relationships_20h.attentive",
    *SAVE_ROWS, "events_per_jump_morning_day60",
)


def test_every_report_row_is_banded_or_deferred_exactly_once() -> None:      # v0.22's test, extended in place (F25)
    placed = set(BANDS) | set(DEFERRED_ROWS) | set(sim.DERIVED_ROWS) | set(ASSERTED) | set(sim.UNBANDED_ROWS)
    assert placed | set(SAVE_ROWS) == set(sim.REPORT_ROWS)
    assert not set(SAVE_ROWS) & placed
    assert not set(sim.UNBANDED_ROWS) & (set(BANDS) | set(DEFERRED_ROWS) | set(sim.DERIVED_ROWS) | set(ASSERTED))
    assert not set(BANDS) & set(DEFERRED_ROWS)
    assert not (set(BANDS) | set(DEFERRED_ROWS)) & set(sim.DERIVED_ROWS)     # a derived row is never banded (§3.4)
    assert not set(ASSERTED) & (set(BANDS) | set(DEFERRED_ROWS) | set(sim.DERIVED_ROWS))


def test_every_deferred_row_is_recorded_in_claude_md() -> None:
    claude = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    for row, line in DEFERRED_ROWS.items():
        assert line and line in claude, f"{row}: its deferred row is not in CLAUDE.md"


def test_the_full_session_measurements_sit_in_their_bands() -> None:
    """What T11 measured on full sessions, held to §17.2's bands: an attentive row at all three latencies."""
    assert set(FULL_MEASURED) == set(FULL_BANDS)
    for row, (low, high) in FULL_BANDS.items():
        seen = FULL_MEASURED[row]
        if row.startswith(("devoted.", "real_hours_to_depth.")):
            assert set(seen) == {_D15}, row
        elif row == "player_promises_kept.flaky":
            assert set(seen) == {"flaky 15 s"}, row
        else:
            assert set(seen) == {_A6, _A15, _A30}, row
        for where, value in seen.items():
            assert low <= value <= high, (row, where, value)


@pytest.mark.slow
@pytest.mark.timeout(TIMEOUT)
@pytest.mark.parametrize("model_seconds", sim.MODEL_SECONDS)
def test_phone_rows_hold_at_every_latency(receipts_active, model_seconds: float) -> None:
    rep = sim.report(SEEDS, sessions=SESSIONS, policy="attentive", voice_policy="neutral_model",
                     model_seconds=model_seconds, world=False)
    for row, (low, high) in PHONE_BANDS.items():
        value = rep[row]
        assert value is not None and low <= value <= high, (row, value, model_seconds)
    assert rep["person_promises_kept"] == 1.0
    for row in FULL_ONLY:
        assert rep[row] is None, f"{row} measures {rep[row]} phone-only: is it still a full-session row?"


@pytest.mark.slow
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


@pytest.mark.slow
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
                                      model_seconds=0, companion=False, world=False)
                           for v in ("no_model", "neutral_model", "romantic_model"))
    assert 0 < none["also.depth1_per_run"] < neutral["also.depth1_per_run"] <= warm["also.depth1_per_run"]
    assert 0 < none["also.numbers_per_run"] < neutral["also.numbers_per_run"] <= warm["also.numbers_per_run"]


@pytest.mark.slow
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
