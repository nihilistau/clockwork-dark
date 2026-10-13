"""The save-size bound, measured then pinned (spec §17.2, v0.22.0 T26).

After the last task that adds state (T26, after meet-ups), the simulator writes
a day-180 attentive save -- media rows, games and meets in it, made at every
action as play's saves make it (`saves.compact`: threads past
`social.state_messages` and dead ones whole to `phone_archive.jsonl`,
swiped-only people cut to the swipe, old answered requests forgotten) -- and
its `save.json` is pinned at the measured size plus 25%, no higher than the
spec's budget ("well under 1 MB"). A run of 180 in-game days takes many
minutes, so the test is `slow`.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))                    # scripts.* importable (tests/test_generate_art_cli.py:33)

from tests.social_fixtures import receipts_active  # noqa: E402,F401

pytestmark = pytest.mark.slow

#: Spec §17.2: "the design expectation is well under 1 MB".
SAVE_BUDGET = 1_000_000
#: Measured 2026-10-13 (v0.22.0 T26 fix round 1, the shipped constants) by
#: `scripts.simulate_social.write_day_save(seed=7, days=180, policy="attentive", out=<scratch>)`:
#: save.json 817,664 bytes (phone_archive.jsonl 3,559,368). Before the save's compaction it was
#: 2,873,179 (T26's first pass). The bound is that plus 25% (1,022,080), held to the budget.
SAVE_SIZE_MEASURED = 817_664
SAVE_SIZE_BOUND = min(int(SAVE_SIZE_MEASURED * 1.25), SAVE_BUDGET)


@pytest.mark.timeout(3600)
def test_a_day_180_attentive_save_stays_under_its_bound(receipts_active, tmp_path) -> None:
    import scripts.simulate_social as sim

    path = sim.write_day_save(seed=7, days=180, policy="attentive", out=tmp_path)
    size = (path / "save.json").stat().st_size
    assert SAVE_SIZE_BOUND > 0, "measure first (Step 4)"
    assert size <= SAVE_SIZE_BOUND, size
    # What the bound is for: the state keeps a bounded slice, the archive the rest.
    assert (path / "phone_archive.jsonl").stat().st_size > size, "the archive holds less than state: no spill"
