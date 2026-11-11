"""
The other six stories are byte-identical to v0.24.0 (spec §11.3, §12.5).

Against the recording plan T0 made from the v0.24.0 tree
(``tests/flagship_overhaul_recorder.py``). The flagship is held at its
OPENINGS only (plan decision 8): its four new people change who is present,
and so the turn schema's ``npc_id`` enum, from T4 on.
"""

from __future__ import annotations

import json
import os

import pytest

from tests import flagship_overhaul_recorder as rec

RECORD = os.environ.get("CLOCKWORK_FLAGSHIP_RECORD") == "1"


def test_the_v0240_recording_exists_or_is_made_now() -> None:
    """Under CLOCKWORK_FLAGSHIP_RECORD=1 (plan T0, in the v0.24.0 worktree) this WRITES the recording."""
    if RECORD:
        rec.refuse_a_dirty_tree()
        rec.FIXTURE.parent.mkdir(parents=True, exist_ok=True)
        rec.FIXTURE.write_text(json.dumps(rec.record_all(), indent=1, sort_keys=True) + "\n",
                               encoding="utf-8")
    assert rec.FIXTURE.is_file(), "plan T0 records this from 3c6882f"


def test_the_recorder_refuses_a_dirty_tree() -> None:
    """T14 review (d6): an uncommitted change under engine/ or games/ stops a re-recording, by name."""
    with pytest.raises(pytest.fail.Exception, match="engine/game/clock.py"):
        rec.refuse_a_dirty_tree(lambda: " M engine/game/clock.py\n?? games/x/new.yaml\n")
    rec.refuse_a_dirty_tree(lambda: " M docs/GOVERNANCE.md\n?? tests/new_test.py\n")   # outside: passes
    rec.refuse_a_dirty_tree(lambda: "")


@pytest.fixture(scope="module")
def recorded() -> dict:
    return json.loads(rec.FIXTURE.read_text(encoding="utf-8"))


@pytest.mark.parametrize("slug", rec.SEVEN)
def test_every_storys_opening_catalogue_is_v0240s(recorded: dict, slug: str) -> None:
    assert rec.openings(slug, (rec.OPENING_SEED,)) == recorded["openings"][slug]


def test_the_flagship_catalogue_at_the_golden_seeds_is_v0240s(recorded: dict) -> None:
    assert rec.openings(rec.FLAGSHIP, rec.FLAGSHIP_GOLDEN_SEEDS) == recorded["flagship_golden"]


@pytest.mark.parametrize("slug", rec.OTHER_SIX)
def test_every_shipped_decks_bound_beats_are_v0240s(recorded: dict, slug: str) -> None:
    assert rec.bound_beats(slug) == recorded["beats"][slug]


@pytest.mark.parametrize("slug", [s for s in rec.RUN_STORIES if s != rec.FLAGSHIP])
def test_a_20_turn_stub_run_is_v0240s(recorded: dict, slug: str) -> None:
    assert rec.stub_run(slug) == recorded["runs"][slug]


@pytest.mark.parametrize("slug", rec.LEGACY_SLOT_STORIES)
def test_the_legacy_slots_roll_as_in_v0240(recorded: dict, slug: str) -> None:
    """Forced and unforced, and the three `schedule.*` counters after the run (`on_tick` untouched, §6.1)."""
    assert rec.legacy_rolls(slug) == recorded["legacy"][slug]


def test_hue_and_crys_endings_block_is_v0240s(recorded: dict) -> None:
    assert rec.hue_endings() == recorded["hue_endings"]

