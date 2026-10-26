"""The save-size bound, measured then pinned (spec §17.2, v0.22.0 T26; re-pinned on full sessions, v0.24.0 T11).

The simulator writes a day-180 save per policy (attentive, bachelor, devoted) -- full sessions since
v0.24.0 T11 (v0.23.0 T29b): the phone, the world, scenes, plans, life events and the long-term stages,
made at every action as play's saves make it (`saves.compact`: threads past `social.state_messages` and
dead ones whole to `phone_archive.jsonl`, swiped-only people cut to the swipe, old answered requests and
closed promises forgotten) -- and each `save.json` is pinned at its measured size plus 25%, no higher than
the spec's budget ("well under 1 MB"). A run of 180 in-game days takes many minutes, so the test is `slow`.
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
#: Measured 2026-10-26 (v0.24.0 T11, the shipped constants, full sessions) by
#: `scripts/simulate_social.py --day-save 180 --first-seed 7 --policy <p> --disk <scratch>`, the same call as
#: `write_day_save(seed=7, days=180, policy=<p>, out=<scratch>)` (romantic voice). Before: one attentive pin,
#: 817,664 bytes (v0.22.0 T26), and v0.23.0 T9's phone-only 861,222. The bounds: attentive and bachelor
#: 1,000,000 (the budget, under x1.25), devoted 381,036.
SAVE_SIZE_MEASURED = {"attentive": 843_415, "bachelor": 809_272, "devoted": 304_829}
SAVE_SIZE_BOUND = {policy: min(int(size * 1.25), SAVE_BUDGET) for policy, size in SAVE_SIZE_MEASURED.items()}


@pytest.mark.timeout(3600)
@pytest.mark.parametrize("policy", sorted(SAVE_SIZE_MEASURED))
def test_a_day_180_save_stays_under_its_bound(receipts_active, tmp_path, capsys, policy: str) -> None:
    import scripts.simulate_social as sim

    path = sim.write_day_save(seed=7, days=180, policy=policy, out=tmp_path)
    size = (path / "save.json").stat().st_size
    with capsys.disabled():
        print(f"\n[save size] {policy}: save.json {size} bytes (bound {SAVE_SIZE_BOUND[policy]})")
    assert SAVE_SIZE_BOUND[policy] > 0, "measure first (Step 5)"
    assert size <= SAVE_SIZE_BOUND[policy], size
    # What the bound is for: the state keeps a bounded slice, the archive the rest.
    assert (path / "phone_archive.jsonl").stat().st_size > size, "the archive holds less than state: no spill"
