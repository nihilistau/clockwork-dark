"""The shipped constants land every §20 row in its band (10 seeds; the full pass is the script's).

v0.22.0 T26 (spec §20, Plan decision 30). `sim_report` runs the attentive
player for 60 days on seeds 0-9 under the harness's default voice, the working
neutral model (`simulate_social.DEFAULT_VOICE`); `turners_turned_60d` needs a
run of 75 days or more (its window is censored at 60), so it is measured on
its own 75-day report. The full pass and its tables are in the story's
CHANGELOG and every `data/social/*.yaml` header.
"""

import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))                    # scripts.* importable (tests/test_generate_art_cli.py:33)

import scripts.simulate_social as sim  # noqa: E402
from tests.social_fixtures import receipts_active  # noqa: E402,F401

#: `slow` (a balance measurement, rule 10) and `process`: the runs are the script's own, one
#: interpreter per seed side by side (`--raw`, then `fold`), as the full pass is made.
pytestmark = [pytest.mark.slow, pytest.mark.process]

#: The seeds the bands are pinned on (the full pass's 20-40 are the script's).
SEEDS = range(10)
#: The rows a 60-day run cannot measure, and the longer run that does.
LONG_ROWS = ("turners_turned_60d",)
LONG_DAYS = 75
#: A module's runs take long; each test may take this many seconds (fixture setup included).
TIMEOUT = 3600

#: Keyed by sim.REPORT_ROWS (the plan's Shared interfaces). A row moves from here to
#: DEFERRED_ROWS only as Plan decision 30 says -- never widened, never skipped.
BANDS = {
    "like_to_match.matchstick": (0.12, 0.25),
    "like_to_match.front_porch": (0.25, 0.40),
    "match_to_talking_3d": (0.40, 0.60),
    "match_to_message_3d": (0.55, 0.75),
    "talking_to_ghosted_14d": (0.20, 0.35),
    "meet_band.great": (0.10, 0.20), "meet_band.good": (0.25, 0.40), "meet_band.fine": (0.20, 0.30),
    "meet_band.bad": (0.05, 0.15),
    "interest_half_life_days": (4.0, 10.0),
    "messages_per_day.attentive": (15.0, 60.0),
    "photos_per_close_week": (0.5, 1.0),
    "voice_per_relationship_week_after_numbers": (0.5, 1.5),
    "videos_per_close_month": (0.5, 1.5),
    "turners_turned_60d": (0.60, 0.90),
    "events_per_72h_away_day60": (0.0, 1500.0),
}

#: Spec §20's closeness row (median days from match), for the archetypes it names.
CLOSENESS = {"warming": (2.0, 5.0), "close": (10.0, 25.0), "very_close": (30.0, 60.0)}
CLOSENESS_ARCHETYPES = ("romantic", "steady")
#: A closeness cell (band, archetype) deferred the same way as `DEFERRED_ROWS`, with the EXACT
#: text of its CLAUDE.md "Deliberately deferred" row (v0.22.0 T32 ruling): still measured and
#: reached, but not held to its band.
DEFERRED_CLOSENESS: dict[tuple[str, str], str] = {
    # Seed-sensitive since the final review's wave 2 numbers gate; v0.23.0 replaces the pacing model.
    ("warming", "romantic"): (
        "READ RECEIPTS' days from a match to warming for a romantic (spec §20, band 2-5 days) measure 5.22 on `tests/test_simulate_social.py`'s seeds 0-9 (attentive, neutral model, 60 days; 4.08 before the final review's wave 2 numbers gate, 9c09d38) and 3.76 over 40 seeds, in band: seed-sensitive, so the cell is deferred by data (`tests/test_simulate_social.py` `DEFERRED_CLOSENESS`), not retuned or widened; v0.23.0 replaces the pacing model (the owner's growth brief and its addenda)."),
}

#: A §20 row that cannot land without breaking another (Step 3), with the EXACT text of its
#: CLAUDE.md "Deliberately deferred" row (written in the same commit): the declared, tested
#: reason of spec §19.6 (Plan decision 30, pre-flight F15). Empty unless Step 3 defers one.
DEFERRED_ROWS: dict[str, str] = {
    # The band 4-10 (spec §20); the measured value, the levers tried and why they broke the rest
    # are CLAUDE.md's row (T26 fix round 1: a 1.75-day fade landed it, and was rejected).
    "live_relationships_day30.attentive": (
        "READ RECEIPTS' live relationships at day 30 (spec §20, band 4-10) measure 35.0 for the attentive player (20 seeds x 60 days, neutral model, v0.22.0 T26 fix round 1), so the row is deferred by data (`tests/test_simulate_social.py` `DEFERRED_ROWS`), not banded."),
    # The numbers gate lost its days (owner bug, v0.22.0 final review wave 2); v0.23.0 redesigns pacing.
    "talking_to_numbers_21d.attentive": (
        "READ RECEIPTS' talking-to-numbers within 21 days (spec §20, band 15-30%) measures 35.0% for the attentive player (10 seeds x 60 days, neutral model) since the numbers gate lost its 6 in-game days (owner bug, v0.22.0 final review wave 2: warmth 30, trust 23, 20 exchanges, no days), so the row is deferred by data (`tests/test_simulate_social.py` `DEFERRED_ROWS`), not banded; v0.23.0 redesigns pacing around real session time (the owner's growth brief, docs/superpowers/briefs/2026-10-13-read-receipts-growth-brief.md)."),
    "numbers_to_meet_21d": (
        "READ RECEIPTS' numbers-to-meet within 21 days (spec §20, band 25-45%) measures 16.0% for the attentive player (10 seeds x 60 days, neutral model) since numbers come days sooner, at lower warmth and trust, while the meeting gate (warmth 70, trust 70) is unchanged (v0.22.0 final review wave 2), so the row is deferred by data (`tests/test_simulate_social.py` `DEFERRED_ROWS`), not banded; v0.23.0 redesigns pacing around real session time (the owner's growth brief)."),
    "meet_band.awkward": (
        "READ RECEIPTS' awkward meet-ups (spec §20, band 10-20%) measure 20.8% for the attentive player (10 seeds x 60 days, neutral model) since the numbers gate lost its days (v0.22.0 final review wave 2), so the row is deferred by data (`tests/test_simulate_social.py` `DEFERRED_ROWS`), not banded; v0.23.0 redesigns pacing around real session time (the owner's growth brief)."),
}


def _reports(groups: list[tuple[str, str, int, range]], tmp: Path) -> list[dict]:
    """
    Each (policy, voice, days, seeds) folded into its report: every run its own
    `scripts/simulate_social.py --raw` interpreter, side by side, the same
    report one process makes (`fold` of the same seeds, byte for byte).
    """
    tasks = [(p, v, d, s) for p, v, d, seeds in groups for s in seeds]

    def one(task: tuple[str, str, int, int]) -> Path:
        p, v, d, s = task
        raw = tmp / f"r-{p}-{v}-{d}-{s}.json"
        subprocess.run([sys.executable, str(ROOT / "scripts" / "simulate_social.py"), "--days", str(d),
                        "--first-seed", str(s), "--seeds", "1", "--policy", p, "--voice", v, "--raw", str(raw)],
                       cwd=ROOT, check=True, timeout=TIMEOUT, stdout=subprocess.DEVNULL)
        return raw

    with ThreadPoolExecutor(max(1, min(len(tasks), os.cpu_count() or 1))) as pool:
        raws = dict(zip(tasks, pool.map(one, tasks)))
    out = []
    for p, v, d, seeds in groups:
        runs = [run for s in seeds for run in json.loads(raws[(p, v, d, s)].read_text(encoding="utf-8"))[f"{p}/{v}"]]
        out.append(sim.fold(sorted(runs, key=lambda r: r["seed"])))
    return out


@pytest.fixture(scope="module")
def sim_report(tmp_path_factory) -> dict:
    """The bands' report: seeds 0-9, every run its own interpreter (no story is activated here)."""
    voice = sim.DEFAULT_VOICE
    out, long = _reports([("attentive", voice, 60, SEEDS), ("attentive", voice, LONG_DAYS, SEEDS)],
                         tmp_path_factory.mktemp("sim_report"))
    for row in LONG_ROWS:
        out[row] = long[row]
    return out


def test_every_report_row_is_banded_or_deferred_exactly_once() -> None:
    assert set(BANDS) | set(DEFERRED_ROWS) == set(sim.REPORT_ROWS)
    assert not set(BANDS) & set(DEFERRED_ROWS)


def test_every_deferred_row_is_recorded_in_claude_md() -> None:
    claude = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    for row, line in DEFERRED_ROWS.items():
        assert line and line in claude, f"{row}: its deferred row is not in CLAUDE.md"
    for cell, line in DEFERRED_CLOSENESS.items():
        assert line and line in claude, f"{cell}: its deferred closeness row is not in CLAUDE.md"


def test_every_deferred_closeness_cell_is_a_cell() -> None:
    for band, archetype in DEFERRED_CLOSENESS:
        assert band in CLOSENESS and archetype in CLOSENESS_ARCHETYPES, (band, archetype)


@pytest.mark.timeout(TIMEOUT)
@pytest.mark.parametrize("row", sorted(BANDS))
def test_every_row_lands_in_its_band(row, sim_report) -> None:
    low, high = BANDS[row]
    assert sim_report[row] is not None, f"{row}: not measured"
    assert low <= sim_report[row] <= high, f"{row} = {sim_report[row]:.3f}, band {low}-{high}"


@pytest.mark.timeout(TIMEOUT)
def test_dry_texters_never_reach_close(sim_report) -> None:
    assert sim_report["days_to_close.dry_texter"] is None
    assert sim_report["days_to_close.romantic"] is not None, "nobody reached close: the check is vacuous"


@pytest.mark.timeout(TIMEOUT)
@pytest.mark.parametrize("archetype", CLOSENESS_ARCHETYPES)
@pytest.mark.parametrize("band", sorted(CLOSENESS))
def test_closeness_takes_its_days(band, archetype, sim_report) -> None:
    low, high = CLOSENESS[band]
    days = sim_report[f"days_to_{band}.{archetype}"]
    assert days is not None, f"no {archetype} reached {band}"
    if (band, archetype) in DEFERRED_CLOSENESS:
        return                                   # measured and reached; its band is deferred (CLAUDE.md)
    assert low <= days <= high, f"{archetype} reaches {band} in {days} days, band {low}-{high}"


@pytest.mark.timeout(TIMEOUT)
def test_a_dead_model_server_progresses_slowly(receipts_active, tmp_path) -> None:
    """
    Spec §10.2's ruling, measured (T26 fix round 2): with no model every reply
    is the engine's fallback, whose regard (`regard.fallback`, +1/+1) is capped
    a day by `regard.fallback.per_day` (3/2). Such a run DOES progress -- it
    swaps numbers and, in time, meets -- but more slowly than a working
    neutral model (+1/+1 under `per_day_gain` 6/4), which is slower than a
    warm one (+3/+1), on the same seeds.
    """
    seeds, days = range(6), 60
    none, neutral, warm = _reports([("attentive", v, days, seeds)
                                    for v in ("no_model", "neutral_model", "romantic_model")], tmp_path)
    rate = "talking_to_numbers_21d.attentive"
    assert 0 < none[rate] < neutral[rate]
    assert 0 < none["also.numbers_per_run"] < neutral["also.numbers_per_run"] < warm["also.numbers_per_run"]
    assert 0 < none["also.meets_per_run"] < neutral["also.meets_per_run"] < warm["also.meets_per_run"]


@pytest.mark.timeout(TIMEOUT)
def test_a_run_on_disk_measures_the_same_as_one_in_memory(receipts_active, tmp_path, monkeypatch) -> None:
    """
    The mechanics are spill- and compaction-invariant (T26): a run that makes
    a save's bounded state after every action (`saves.compact`) -- every
    thread past a SMALL keep spilled, every dead thread (here a 3-day fade, a
    1-day quiet) emptied to its stamp, every swiped-only person cut to the
    swipe, answered requests past 2 forgotten -- measures exactly what the same run keeping everything in state
    does, the measurements reading the archive back.
    """
    from engine import social
    from engine.social import archive, relationships, saves

    real_setting, real_block = social.setting, relationships._block
    monkeypatch.setattr(social, "setting", lambda key, default: {"state_messages": 12, "archive_dead_after_days": 1,
                                                                 "requests_kept": 2}.get(key, real_setting(key, default)))
    monkeypatch.setattr(relationships, "_block", lambda name: 3 if name == "fade_days" else real_block(name))
    held = sim.run(2, 20, "attentive", "romantic_model")
    seen = {"stamped": 0, "compacted": 0, "forgotten": 0}
    real_compact, real_forget = saves.compact, relationships.forget_answered

    def forgetting(state):
        gone = real_forget(state)
        seen["forgotten"] += gone
        return gone

    monkeypatch.setattr(relationships, "forget_answered", forgetting)

    def counting(session):
        out = real_compact(session)
        state = session.engine.state
        seen["stamped"] = max(seen["stamped"], sum(1 for t in state.social["threads"].values() if t.get("stamp")))
        seen["compacted"] = max(seen["compacted"],
                                sum(1 for p in state.social["people"].values() if set(p) == {"apps"}))
        return out

    monkeypatch.setattr(saves, "compact", counting)
    spilled = sim.run(2, 20, "attentive", "romantic_model", disk=tmp_path)
    for row in (held, spilled):
        row.pop("wall_seconds")
    files = list(tmp_path.rglob(archive.ARCHIVE_FILE))
    assert files and files[0].stat().st_size > 10_000, "nothing spilled: the check is vacuous"
    assert seen["stamped"] >= 10 and seen["compacted"] >= 100 and seen["forgotten"] >= 5, seen
    assert held["received"] > 100
    assert json.dumps(held, sort_keys=True) == json.dumps(spilled, sort_keys=True)
