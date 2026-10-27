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
        rec.FIXTURE.parent.mkdir(parents=True, exist_ok=True)
        rec.FIXTURE.write_text(json.dumps(rec.record_all(), indent=1, sort_keys=True) + "\n",
                               encoding="utf-8")
    assert rec.FIXTURE.is_file(), "plan T0 records this from 3c6882f"


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


class _NoLore:
    """A lore index with nothing in it: the recording's (T0 ran in a fresh worktree, which has no
    gitignored ``lore.db``). With the flagship's ``lore.db`` present every prompt gains a LORE
    CONTEXT block, so the prompt digests would follow the checkout, not the code."""

    def count(self) -> int:
        return 0


def test_the_flagships_stub_run_is_v0240s_until_its_cast_arrives(
    recorded: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T2 ONLY (plan decision 8): the builder split moved no flagship catalogue. Deleted by T4,
    whose four new people change who stands in the square, and so the turn schema's npc enum.

    The catalogues and prompts only, never the save (controller ruling M22): T1 converted the
    flagship's caravan, tinker and press to probabilistic declared events, so its save digest can
    move for T1's reason. The catalogue and prompt digests are what the builder split could move.
    The lore index is held empty, as the recording's worktree had it (``_NoLore``)."""
    from engine.agents import storyteller

    monkeypatch.setattr(storyteller, "get_lore_manager", lambda **_: _NoLore())
    run = rec.stub_run(rec.FLAGSHIP)
    was = recorded["runs"][rec.FLAGSHIP]
    assert run["catalogues"] == was["catalogues"]
    assert run["prompts"] == was["prompts"]
