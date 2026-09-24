"""
Jobs, part four: authored jobs and guild contracts.

THE SHAPE. An anchored premise's own stages (Task 2) resolve with their
authored skill and band already; this file's engine change is narrower --
``features`` and ``tools`` rows may now name an anchor's own stage id, not
only the five derived ones, and the loader still rejects a stage id that
names nothing real, naming the file. A GUILD CONTRACT needs no new engine
surface at all: it is a plain ``threads.yaml`` template whose ``requires``
says where it can be struck, whose ``discharge_requires`` is the shared
condition grammar reading ``premise_robbed`` (Task 1's predicate, wired
through ``jobs.robbed`` once a job closes clean or noisy), whose
``on_discharge`` pays the fee net of the Guild's cut as a plain ``gold``
effect, and whose ``on_break`` sours the Guild as a plain ``reputation``
effect -- ``threads.expire_due`` already breaks a contract whose day has
passed, exactly as it does for the Wicked Garden's bargains.

WHAT THESE TESTS HOLD. A feature or tool authored against an anchor stage id
applies its shift and its reason there, same as at any of the five; a feature
or tool naming a stage id that is not one of the five AND not any anchor's own
is still a load fault naming the file, and so is a row that would load and
do nothing -- a feature on an anchor stage its own anchor does not carry,
``obstacle: true`` off ``inside``, ``entries`` where no entry stage is named;
a guild contract can be struck only
where its own ``requires`` holds; it cannot be discharged until a job has
robbed a premise matching its ``discharge_requires`` filters (type AND
district, not either alone); discharging then pays the net fee and nothing
else; and a contract left unpaid past its ``due_in_days`` breaks and pays its
``on_break`` cost, through the same ``expire_due`` sweep every other thread in
this engine already uses.

Built on test_premises.py's synthetic directory and test_jobs.py's synthetic
jobs file, same as the rest of this family. HUE & CRY's own jobs and its
guild contract (`gannet_silk_row`) are tested in test_hue_and_cry.py.

Version: v0.1.2 [2026-09-24]
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import pytest

from engine.config import set_overlay
from engine.game import checks, threads
from engine.game.clock import set_clock
from engine.game.effects import apply_effect
from engine.game.inventory import name_of
from engine.world import jobs, premises

from test_jobs import MARKET, MILL, SQUARE, _dump, _mutated, _paths
from test_jobs_stages import _approach, _rolls, _walk_to, _world

# ---------------------------------------------------------------------------
# Features and tools may name an anchor's own stage
# ---------------------------------------------------------------------------


@contextmanager
def _story(tmp_path: Path, doc: Any = None) -> Iterator[Path]:
    set_overlay({"paths": _paths(tmp_path, doc)})
    try:
        yield tmp_path
    finally:
        set_overlay(None)


ANCHOR_FEATURE_DOC = _mutated(
    features__iron_bar={"stage": "bell_floor", "shift": 1, "known_shift": 0},
    tools__bent_nail={"stage": ["entry", "score", "bell_floor"],
                      "entries": ["door", "cellar"], "shift": -1},
)


def test_the_contract_loads_a_feature_and_tool_named_for_an_anchor_stage(tmp_path: Path) -> None:
    with _story(tmp_path, ANCHOR_FEATURE_DOC):
        spec = jobs.spec()
        assert spec["features"]["iron_bar"]["stage"] == "bell_floor"
        assert "bell_floor" in spec["tools"]["bent_nail"]["stage"]


def test_a_feature_and_a_tool_apply_to_an_anchor_stage(tmp_path: Path, monkeypatch) -> None:
    with _story(tmp_path, ANCHOR_FEATURE_DOC):
        state = _world(location=MARKET)
        assert jobs.begin(state, MILL)["ok"] is True
        _rolls(monkeypatch, "success")
        _walk_to(state, "bell_floor")

        # The anchor's own band (severe), walked by the unknown feature's shift.
        band, reasons = jobs.band_for(state, "bell_floor")
        assert band == checks.shift_band("severe", 1)
        assert reasons == ["an iron bar across the door, not yet cased"]

        # Casing it drops the shift -- `iron_bar`'s known_shift is 0 (the
        # default is 0, NOT its `shift`), so the band returns to severe -- but
        # the bar is still named as the reason, cased now: `_plan` names every
        # feature the premise carries at its stage, moved band or not.
        apply_effect(state, {"type": "intel", "premise": MILL, "intel": "security:iron_bar"})
        band, reasons = jobs.band_for(state, "bell_floor")
        assert band == "severe"
        assert reasons == ["an iron bar across the door, cased already"]

        # A carried tool eases the same roll, named alongside the feature.
        # `iron_bar`'s known_shift is 0, so once cased it no longer moves the
        # band -- only the tool's -1 does, one full band down from severe.
        apply_effect(state, {"type": "item", "item_id": "bent_nail"})
        band, reasons = jobs.band_for(state, "bell_floor")
        assert band == checks.shift_band("severe", -1)
        assert reasons == ["an iron bar across the door, cased already", name_of("bent_nail")]

        # And it rolls the anchor's own skill, eased by the held tool.
        calls = _rolls(monkeypatch, "success")
        jobs.resolve_stage(state, "bell_floor")
        assert calls == [("nerve", checks.shift_band("severe", -1))]


ANCHOR_MALFORMED = {
    "a feature naming a stage that is neither of the five nor any anchor's": _mutated(
        features__good_lock={"stage": "ghost_floor", "shift": 1}
    ),
    "a tool naming a stage that is neither of the five nor any anchor's": _mutated(
        tools__bent_nail={"stage": ["ghost_floor"], "shift": -1}
    ),
}


@pytest.mark.parametrize("fault", sorted(ANCHOR_MALFORMED))
def test_a_feature_or_tool_on_an_unknown_stage_fails_naming_the_file(
    tmp_path: Path, fault: str
) -> None:
    paths = _paths(tmp_path, ANCHOR_MALFORMED[fault])
    set_overlay({"paths": paths})
    try:
        with pytest.raises(ValueError) as caught:
            jobs.spec()
        assert paths["jobs"] in str(caught.value)
        assert "ghost_floor" in str(caught.value)
    finally:
        set_overlay(None)


#: Rows that USED to load and then silently did nothing (or worse) at runtime.
#: Each value is (doc, a token the error must name besides the file).
SILENT_MALFORMED = {
    # `_plan` walks only the robbed premise's own `security`, and only the
    # anchor's own premise reaches its stage: good_lock is a townhouse's
    # feature, the mill house never carries it, so it could never apply.
    "a feature on an anchor stage whose anchor does not carry it": (
        _mutated(features__good_lock={"stage": "bell_floor", "shift": 1}),
        "good_lock",
    ),
    # `_ensure_obstacles` queues every obstacle feature at `inside` while
    # `_plan` applies its shift only at its own stage: a dog that blocks
    # `inside` with no shift anywhere.
    "an obstacle feature on the entry": (
        _mutated(features__good_lock={"stage": "entry", "obstacle": True, "shift": 1}),
        "good_lock",
    ),
    "an obstacle feature on an anchor stage": (
        _mutated(features__iron_bar={"stage": "bell_floor", "obstacle": True, "shift": 1}),
        "iron_bar",
    ),
    # The entries filter binds only at `entry`; anywhere else it is ignored.
    "a feature with entries on a stage that is not the entry": (
        _mutated(features__yard_dog={"stage": "inside", "obstacle": True,
                                     "known_shift": -1, "entries": ["door"]}),
        "yard_dog",
    ),
    "a tool with entries but no entry stage": (
        _mutated(tools__hand_lantern={"stage": ["getaway"], "shift": -1, "entries": ["door"]}),
        "hand_lantern",
    ),
}


@pytest.mark.parametrize("fault", sorted(SILENT_MALFORMED))
def test_a_row_that_would_load_and_do_nothing_fails_naming_the_file(
    tmp_path: Path, fault: str
) -> None:
    doc, token = SILENT_MALFORMED[fault]
    paths = _paths(tmp_path, doc)
    set_overlay({"paths": paths})
    try:
        with pytest.raises(ValueError) as caught:
            jobs.spec()
        assert paths["jobs"] in str(caught.value)
        assert token in str(caught.value)
    finally:
        set_overlay(None)


def test_the_anchors_extra_stage_is_still_offered_in_order(tmp_path: Path) -> None:
    """Task 2's own ruling, kept honest here: unaffected by the wider stage set."""
    with _story(tmp_path, ANCHOR_FEATURE_DOC):
        state = _world(location=MARKET)
        assert jobs.stages_for(state, MILL) == [
            "approach", "entry", "inside", "bell_floor", "score", "getaway",
        ]


# ---------------------------------------------------------------------------
# Guild contracts: a thread template, nothing more
# ---------------------------------------------------------------------------

GUILD_FEE_NET = 18
GUILD_BREAK_PENALTY = -8

CONTRACT_SPEC: dict[str, Any] = {
    "templates": {
        "guild_job_treasury": {
            "source": "guild",
            "terms": "empty a townhouse strongroom in the Square, robbery only -- no bloodshed",
            "requires": {"at_location": SQUARE},
            "due_in_days": 5,
            "discharge_requires": {
                "premise_robbed": {"type": "townhouse", "district": SQUARE},
            },
            "on_discharge": [{"type": "gold", "delta": GUILD_FEE_NET}],
            "on_break": [{"type": "reputation", "faction": "guild", "delta": GUILD_BREAK_PENALTY}],
        }
    }
}


def _contract_paths(tmp_path: Path) -> dict[str, str]:
    paths = _paths(tmp_path)
    paths["threads"] = _dump(tmp_path / "threads.yaml", CONTRACT_SPEC)
    return paths


@contextmanager
def _contract_story(tmp_path: Path) -> Iterator[Path]:
    set_overlay({"paths": _contract_paths(tmp_path)})
    try:
        yield tmp_path
    finally:
        set_overlay(None)


def _townhouse_at(state, location: str) -> str:
    prem = next(p for p in premises.at(state, location) if p["type"] == "townhouse")
    return str(prem["id"])


def _finish_job(state, monkeypatch, pid: str) -> None:
    assert jobs.begin(state, pid)["ok"] is True
    _rolls(monkeypatch, "success")
    for _ in range(20):
        if jobs.current_stage(state) is None:
            return
        out = jobs.resolve_stage(state, _approach(state, "door"))
        assert out["ok"] is True, out
    raise AssertionError(f"job on {pid} never closed")


def test_a_guild_contract_can_be_struck_only_where_it_is_authored(tmp_path: Path) -> None:
    with _contract_story(tmp_path):
        state = _world(location=SQUARE)
        assert threads.can_strike(state, "guild_job_treasury") is True
        rows = threads.offerable(state)
        assert [r["id"] for r in rows] == ["guild_job_treasury"]

        state.location_id = MARKET
        assert threads.can_strike(state, "guild_job_treasury") is False
        assert threads.offerable(state) == []


def test_a_guild_contract_discharges_only_after_the_matching_premise_is_robbed(
    tmp_path: Path, monkeypatch
) -> None:
    with _contract_story(tmp_path):
        state = _world(location=SQUARE)
        before_gold = state.stats.gold

        proposal = threads.offer(state, "guild_job_treasury")
        assert proposal is not None
        sealed = threads.seal(state, proposal)
        assert sealed["ok"] is True
        thread_id = sealed["thread"]["id"]

        # Not yet: no job has robbed anything.
        assert threads.can_discharge(state, threads.get(state, thread_id)) is False
        refused = threads.discharge(state, thread_id)
        assert refused["ok"] is False
        assert threads.get(state, thread_id)["status"] == threads.STATUS_ACTIVE
        assert state.stats.gold == before_gold

        pid = _townhouse_at(state, SQUARE)
        _finish_job(state, monkeypatch, pid)
        assert pid in jobs.robbed(state)

        assert threads.can_discharge(state, threads.get(state, thread_id)) is True
        paid = threads.discharge(state, thread_id)
        assert paid["ok"] is True
        # The fee net of the Guild's cut, nothing else -- one gold effect.
        assert state.stats.gold == before_gold + GUILD_FEE_NET
        assert threads.get(state, thread_id)["status"] == threads.STATUS_DISCHARGED


def test_discharge_requires_filters_by_type_and_district_together(
    tmp_path: Path, monkeypatch
) -> None:
    with _contract_story(tmp_path):
        state = _world(location=SQUARE)
        thread_id = threads.seal(state, threads.offer(state, "guild_job_treasury"))["thread"]["id"]

        # Wrong type AND wrong district: the anchor, in millhaven_market.
        state.location_id = MARKET
        _finish_job(state, monkeypatch, MILL)
        assert MILL in jobs.robbed(state)
        assert threads.can_discharge(state, threads.get(state, thread_id)) is False

        # Right type, wrong district: a townhouse, still in millhaven_market.
        other_pid = _townhouse_at(state, MARKET)
        _finish_job(state, monkeypatch, other_pid)
        assert other_pid in jobs.robbed(state)
        assert threads.can_discharge(state, threads.get(state, thread_id)) is False

        # Right type, right district: a townhouse in edgewood_square.
        state.location_id = SQUARE
        pid = _townhouse_at(state, SQUARE)
        _finish_job(state, monkeypatch, pid)
        assert threads.can_discharge(state, threads.get(state, thread_id)) is True


def test_a_guild_contract_breaks_past_its_due_date_and_sours_the_guild(tmp_path: Path) -> None:
    with _contract_story(tmp_path):
        state = _world(location=SQUARE)
        sealed = threads.seal(state, threads.offer(state, "guild_job_treasury"))
        thread_id = sealed["thread"]["id"]
        due_day = threads.get(state, thread_id)["due_day"]
        before = int(state.reputations.get("guild", 0))

        set_clock(state, day=due_day + 1, hour=state.world_hour)
        broken = threads.expire_due(state)

        assert [b["thread"]["id"] for b in broken if b.get("thread")] == [thread_id]
        assert threads.get(state, thread_id)["status"] == threads.STATUS_BROKEN
        assert int(state.reputations.get("guild", 0)) == before + GUILD_BREAK_PENALTY
