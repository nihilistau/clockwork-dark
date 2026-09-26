"""
World events that force a scene, and decks that can deal again (v0.13.0, T3).

THE GAP. Two, both in the scene director's reach and neither expressible:

- A deck is dealt when a clock beat FORCES it (``forces_scene:`` on a beat,
  read back by ``clocks.forced_scenes``) or when its own ``when:`` holds. A
  story-declared world event -- the ``events:`` block of ``world_schedules``,
  on the calendar -- could not force anything: ``schedules._declared_event``
  dropped every key but text, rumour and cast. A raid on day 3 had no way to
  put its scene in front of the player.
- Every deck was one-shot. ``deck_played_<id>`` (and, for a forced deck,
  ``scene_played_<id>``) retire it for the rest of the run, so a scene that
  should happen on every arrest happened on the first one only.

WHAT THESE TESTS HOLD.

- A declared event may carry ``forces_scene: <deck or card id>``. It flows
  through the SAME ``clocks.forced_scenes`` path a clock beat uses: the deck
  is dealt, source ``forced``, on a day the event is active.
- A deck may declare ``repeatable: true``. It still deals once per RISING
  EDGE: after it is played it re-arms only once its trigger has been seen
  false (its ``when:`` fell, or no active world event forces it any more).
  The "has fallen" bit is the played flag itself, cleared through
  ``apply_effect`` -- so it is state, survives save/load, and does not depend
  on how the clock was cut between turns.
- A deck with no ``repeatable`` is exactly as one-shot as it was.
- The shipped deck stories deal byte-identically: a fixed director walk of
  the-long-con, wicked-garden and dev-story, recorded at b59a3ea (before this
  change), replays to the same hands and the same played flags.
- Validation: an event's ``forces_scene`` must name a deck or card, and a
  story with no decks declaring one is an error naming the schedules file;
  ``repeatable`` must be a bool.

Version: v0.1.0 [2026-09-25]
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterator

import pytest
import yaml

from engine.config import set_overlay
from engine.content import director
from engine.game import clock as clock_module
from engine.game.effects import apply_effect
from engine.game.state import GameState
from engine.world import law, schedules

from test_law_arrest import _file, _paths, _world


def _card(card_id: str) -> dict[str, Any]:
    return {
        "id": card_id,
        "required": True,
        "tags": ["sequence"],
        "title": card_id.replace("_", " ").title(),
        "text": "INTENT: a scene.",
        "beats": [{"id": f"{card_id}_go", "text": "It happens."}],
    }


def _deck(deck_id: str, *, when: Any = None, repeatable: Any = None) -> dict[str, Any]:
    doc: dict[str, Any] = {"id": deck_id, "draw": 1, "cards": [_card(f"{deck_id}_card")]}
    if when is not None:
        doc["when"] = when
    if repeatable is not None:
        doc["repeatable"] = repeatable
    return doc


DECKS = {
    # Forced by a declared event, one-shot.
    "raid": _deck("raid"),
    # Forced by a declared event on a cadence, repeatable.
    "market_brawl": _deck("market_brawl", repeatable=True),
    # Scheduled on custody, repeatable and one-shot.
    "the_cells": _deck("the_cells", when={"in_custody": True}, repeatable=True),
    "first_night_inside": _deck("first_night_inside", when={"in_custody": True}),
}

EVENTS = {
    "events": {
        "the_raid": {
            "on_day": 3,
            "duration_days": 1,
            "text": "The watch kicks in doors along the quay.",
            "forces_scene": "raid",
        },
        "market_day": {
            "every_days": 2,
            "first_day": 2,
            "duration_days": 1,
            "text": "The market is loud and short-tempered.",
            "forces_scene": "market_brawl",
        },
        "the_raid_again": {
            "on_day": 5,
            "duration_days": 1,
            "text": "They come back for the ones they missed.",
            "forces_scene": "raid",
        },
    }
}


def _write_story(tmp_path: Path, decks: dict[str, Any], events: dict[str, Any]) -> dict[str, str]:
    paths = _paths(tmp_path)
    deck_dir = tmp_path / "scenes"
    deck_dir.mkdir(exist_ok=True)
    for deck_id, doc in decks.items():
        (deck_dir / f"{deck_id}.yaml").write_text(yaml.safe_dump(doc), encoding="utf-8")
    sched = tmp_path / "schedules.yaml"
    sched.write_text(yaml.safe_dump(events), encoding="utf-8")
    paths["decks"] = str(deck_dir)
    paths["world_schedules"] = str(sched)
    return paths


@pytest.fixture()
def story(tmp_path: Path) -> Iterator[Any]:
    """A factory: ``story("raid")`` installs a story shipping only those decks.

    One deck per test, rather than retiring the others by flag: retiring a
    repeatable deck by flag is exactly what ``rearm`` undoes once its trigger
    is false, so the only honest way to watch one deck is to ship one.
    """

    def install(*deck_ids: str) -> Path:
        decks = {d: DECKS[d] for d in deck_ids}
        set_overlay({"paths": _write_story(tmp_path, decks, EVENTS)})
        schedules._SCHEDULE_CACHE = None
        return tmp_path

    director._WARNED_FORCED = None
    try:
        yield install
    finally:
        schedules._SCHEDULE_CACHE = None
        director._WARNED_FORCED = None
        set_overlay(None)


def _turn(state: GameState) -> list[str]:
    """One turn's worth of director: open what is due, answer it through."""
    dealt = [r["result"]["deck_id"] for r in director.ensure_scene(state) if r["result"].get("ok")]
    guard = 0
    while director.active(state) and guard < 64:
        director.resolve(state, chosen=director.options(state)[0]["id"])
        guard += 1
    return dealt


def _to_day(state: GameState, day: int) -> None:
    while state.world_day < day:
        clock_module.advance_time(state, 24)


# -- declared events force a scene -----------------------------------------------


def test_a_declared_event_carries_its_forced_scene_into_the_world(story: Any) -> None:
    story("raid")
    state = _world([])
    _to_day(state, 3)
    event = next(e for e in state.world_events if e["event_id"] == "the_raid")
    assert event["payload"]["forces_scene"] == "raid"
    from engine.game import clocks

    assert "raid" in clocks.forced_scenes(state)


def test_a_declared_event_deals_its_deck_on_the_day_it_is_active(story: Any) -> None:
    story("raid")
    state = _world([])
    _to_day(state, 2)
    assert director.due(state) == ("", "", "")
    _to_day(state, 3)
    assert director.due(state) == ("raid", "", "forced")
    assert _turn(state) == ["raid"]
    assert _turn(state) == []


def test_a_one_shot_forced_deck_is_dealt_once_ever(story: Any) -> None:
    """``the_raid_again`` forces the same deck on day 5; a one-shot deck stays spent."""
    story("raid")
    state = _world([])
    dealt: list[str] = []
    for day in range(1, 8):
        _to_day(state, day)
        dealt += _turn(state)
    assert dealt == ["raid"]


def test_an_event_may_force_a_single_card(tmp_path: Path) -> None:
    events = {"events": {"the_raid": {"on_day": 2, "forces_scene": "raid_card"}}}
    set_overlay({"paths": _write_story(tmp_path, {"raid": _deck("raid")}, events)})
    schedules._SCHEDULE_CACHE = None
    try:
        state = _world([])
        _to_day(state, 2)
        assert director.due(state) == ("raid", "raid_card", "forced")
    finally:
        schedules._SCHEDULE_CACHE = None
        set_overlay(None)


def test_a_repeatable_forced_deck_deals_on_every_firing_of_its_event(story: Any) -> None:
    """Market day every other day: dealt on 2, 4 and 6 -- once each, never twice in a window."""
    story("market_brawl")
    state = _world([])
    dealt: list[tuple[int, str]] = []
    for day in range(1, 8):
        _to_day(state, day)
        for _ in range(3):  # three turns a day
            dealt += [(state.world_day, d) for d in _turn(state)]
            clock_module.advance_time(state, 2)
    assert dealt == [(2, "market_brawl"), (4, "market_brawl"), (6, "market_brawl")]


# -- repeatable decks deal once per rising edge ---------------------------------


def _arrest(state: GameState) -> None:
    _file(state, "fencing", 1)
    assert apply_effect(state, {"type": "arrest"})["ok"]


def _release(state: GameState) -> None:
    out = apply_effect(state, {"type": "release"})
    assert out["ok"], out


def test_a_repeatable_deck_deals_on_each_arrest_and_not_while_held(story: Any) -> None:
    story("the_cells")
    state = _world([])
    assert _turn(state) == []
    _arrest(state)
    assert _turn(state) == ["the_cells"]
    assert _turn(state) == [], "dealt again while still held"
    clock_module.advance_time(state, 24)
    assert _turn(state) == [], "dealt again while still held, a day on"
    _release(state)
    assert _turn(state) == []
    _arrest(state)
    assert _turn(state) == ["the_cells"], "the second arrest did not re-deal"
    assert _turn(state) == []


def test_a_repeatable_deal_held_behind_an_open_job_deals_when_the_job_closes(
    story: Any,
) -> None:
    """A burglary owns the turn (`ensure_scene`), so a deal due during it
    waits -- and is not lost: the second arrest's rising edge is still owed
    when the job ends."""
    story("the_cells")
    state = _world([])
    _arrest(state)
    assert _turn(state) == ["the_cells"]
    _release(state)
    assert _turn(state) == []
    state.jobs = {"active": {"id": "job_1", "stage": "inside"}}
    _arrest(state)
    assert _turn(state) == [], "dealt over an open job"
    state.jobs = {}
    assert _turn(state) == ["the_cells"], "the held deal was lost with the job"
    assert _turn(state) == []


def test_a_repeatable_deck_forced_by_a_card_id_rearms_and_redeals(tmp_path: Path) -> None:
    """An event forcing one CARD of a repeatable deck (`scene_played_<card>`
    as well as the deck's flag) re-arms when the event lapses."""
    events = {"events": {"market_day": {
        "every_days": 2, "first_day": 2, "duration_days": 1,
        "text": "The market is loud.", "forces_scene": "market_brawl_card",
    }}}
    set_overlay({"paths": _write_story(
        tmp_path, {"market_brawl": DECKS["market_brawl"]}, events)})
    schedules._SCHEDULE_CACHE = None
    try:
        state = _world([])
        dealt: list[tuple[int, str]] = []
        for day in range(1, 8):
            _to_day(state, day)
            for _ in range(3):
                dealt += [(state.world_day, d) for d in _turn(state)]
                clock_module.advance_time(state, 2)
        assert dealt == [(2, "market_brawl"), (4, "market_brawl"), (6, "market_brawl")]
    finally:
        schedules._SCHEDULE_CACHE = None
        set_overlay(None)


def test_a_one_shot_deck_on_the_same_gate_deals_once(story: Any) -> None:
    story("first_night_inside")
    state = _world([])
    dealt: list[str] = []
    for _ in range(2):
        _arrest(state)
        dealt += _turn(state) + _turn(state)
        _release(state)
        dealt += _turn(state)
    assert dealt == ["first_night_inside"]


def test_the_fall_is_state_written_through_an_effect_and_survives_a_save(
    story: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    story("the_cells")
    state = _world([])
    _arrest(state)
    assert _turn(state) == ["the_cells"]
    _release(state)

    import engine.game.effects as effects_module

    seen: list[dict[str, Any]] = []
    real = effects_module.apply_effect

    def spy(s: GameState, effect: dict[str, Any], *a: Any, **k: Any) -> dict[str, Any]:
        seen.append(dict(effect))
        return real(s, effect, *a, **k)

    monkeypatch.setattr(effects_module, "apply_effect", spy)
    assert _turn(state) == []
    monkeypatch.undo()
    assert {"type": "flag", "flag": director._played_flag("the_cells"), "value": False} in seen

    restored = GameState.from_dict(json.loads(json.dumps(state.to_save_dict())))
    _arrest(restored)
    assert _turn(restored) == ["the_cells"]


def test_repeatable_dealing_does_not_depend_on_how_the_clock_was_cut(story: Any) -> None:
    """Edges are read at the turn, where a deal can happen; the hours between are one fact."""
    story("the_cells")

    def run(chunks: int) -> list[tuple[int, str]]:
        state = _world([])
        log: list[tuple[int, str]] = []
        for step in range(12):
            # Hunger is not what is under test, and a death in the cells is a
            # release of its own (on its own clock): keep the thief fed.
            state.stats.hp = state.stats.max_hp
            if step in (1, 6):
                _arrest(state)
            # Twelve-hour turns can serve a short sentence on their own, so
            # the release is only written where the cell still holds.
            if step in (4, 9) and law.in_custody(state):
                _release(state)
            log += [(state.world_day, d) for d in _turn(state)]
            for _ in range(chunks):
                clock_module.advance_time(state, 12 / chunks)
        return log

    one = run(1)
    assert one == run(4) == run(12)
    assert [d for _, d in one].count("the_cells") == 2


# -- the shipped deck stories are unchanged --------------------------------------


def _walk(slug: str, winds: dict[int, list[tuple[str, float]]]) -> dict[str, Any]:
    """A fixed director walk: a turn every eight hours, first answer every time."""
    from engine.game import clocks
    from engine.game.procgen import new_game_state
    from engine.games import registry

    registry.activate(slug)
    try:
        state = new_game_state(seed=7, location_id=registry.get(slug).entry_location)
        log: list[Any] = []
        for step in range(40):
            for name, by in winds.get(step, []):
                clocks.advance(state, name, by)
            clocks.resolve(state)
            for receipt in director.ensure_scene(state):
                result = receipt["result"]
                log.append([step, state.world_day, result.get("deck_id"), result.get("source"),
                            result.get("card_ids"), result.get("ok")])
            guard = 0
            while director.active(state) and guard < 64:
                director.resolve(state, chosen=director.options(state)[0]["id"])
                guard += 1
            clock_module.advance_time(state, 8)
        # Every played-flag WRITE, falsy values included: a re-arm that
        # cleared a shipped deck's flag would show here as a `False`.
        flags = sorted(
            [k, v] for k, v in state.flags.items()
            if k.startswith((director.PLAYED_FLAG_PREFIX, "scene_played_"))
        )
        return {"log": log, "flags": flags}
    finally:
        registry.deactivate()


#: Recorded at b59a3ea, before repeatable decks and event-forced scenes existed.
#: (slug, clock winds, dealt deck sequence, sha256 of the full walk).
SHIPPED_WALKS = [
    (
        "wicked-garden",
        {},
        # day_09_finale twice: its forced card comes due after the scheduled
        # deal. Pre-existing, one-shot per id, and recorded as it was.
        ["day_00_prologue", "day_01_guest", "day_02_laws", "day_03_heat",
         "day_04_ashen", "day_05_labyrinth", "day_06_roots", "day_07_reckoning",
         "day_08_mirrors", "day_09_finale", "day_09_finale"],
        "980349ba972d5c8fb4cf3f85fe75f13b731c45f61082cb6cb4dc9ba965d25b46",
    ),
    (
        "the-long-con",
        {3: [("the_frame", 10.0)]},
        ["the_interview"],
        "9e7a75a2c4dcd655c4cd184c19e5f36c088a35342a44a4bb4886a4548ccd5642",
    ),
    ("dev-story", {}, [], "82dfe7a6e57ac5fb42c513213580018f7ebf23a5e7d5dcfe9b312774785d8a96"),
]


@pytest.mark.parametrize("slug,winds,decks,digest", SHIPPED_WALKS, ids=[w[0] for w in SHIPPED_WALKS])
def test_shipped_deck_stories_deal_exactly_as_before(
    slug: str, winds: dict[int, list[tuple[str, float]]], decks: Any, digest: Any
) -> None:
    walk = _walk(slug, winds)
    if decks is not None:
        assert [row[2] for row in walk["log"]] == decks
    encoded = json.dumps(walk, sort_keys=True).encode("utf-8")
    assert hashlib.sha256(encoded).hexdigest() == digest


def test_no_shipped_story_opts_in() -> None:
    """Byte-identical by construction too: nothing shipped declares either key."""
    root = Path(__file__).resolve().parents[1] / "games"
    for path in root.glob("*/data/**/*.yaml"):
        # A DECK's `repeatable` is a top-level key of its file. Read as YAML
        # rather than grepped: since v0.15 a thread TEMPLATE may declare its
        # own `repeatable` (HUE & CRY's fence credit, threads.yaml), nested
        # under `templates:`, which is not a deck opting in.
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert not (isinstance(doc, dict) and "repeatable" in doc), path
    for path in root.glob("*/data/world/schedules.yaml"):
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for spec in (doc.get("events") or {}).values():
            assert "forces_scene" not in (spec or {}), path


# -- validation ------------------------------------------------------------------


def _issues(tmp_path: Path, decks: dict[str, Any], events: dict[str, Any]) -> list[str]:
    from engine.games import registry, validation

    manifest = registry.get("dev-story")
    paths = dict(manifest.paths)
    # dev-story's own clock forces one of its own cards; with its decks swapped
    # out that promise would be reported too and drown the one under test.
    paths.pop("clocks", None)
    story_paths = _write_story(tmp_path, decks, events)
    if decks:
        paths["decks"] = story_paths["decks"]
    else:
        paths.pop("decks", None)
    paths["world_schedules"] = story_paths["world_schedules"]
    patched = type(manifest)(**{**manifest.__dict__, "paths": paths})
    return [
        f"{i.source}|{i.ref_id}|{i.message}"
        for i in validation.errors_only(validation.validate_story(patched))
    ]


def test_an_event_forcing_a_scene_that_does_not_exist_is_an_error(tmp_path: Path) -> None:
    events = {"events": {"the_raid": {"on_day": 3, "forces_scene": "no_such_deck"}}}
    issues = _issues(tmp_path, {"raid": _deck("raid")}, events)
    hits = [i for i in issues if "no_such_deck" in i]
    assert hits and "schedules.yaml" in hits[0], issues


def test_an_event_forcing_a_scene_in_a_story_with_no_decks_is_an_error(tmp_path: Path) -> None:
    events = {"events": {"the_raid": {"on_day": 3, "forces_scene": "raid"}}}
    issues = _issues(tmp_path, {}, events)
    hits = [i for i in issues if "ships no decks" in i]
    assert hits and "schedules.yaml" in hits[0], issues


def test_an_event_forcing_a_real_deck_or_card_is_clean(tmp_path: Path) -> None:
    events = {"events": {
        "a": {"on_day": 3, "forces_scene": "raid"},
        "b": {"on_day": 4, "forces_scene": "raid_card"},
    }}
    issues = _issues(tmp_path, {"raid": _deck("raid", repeatable=True)}, events)
    assert not [i for i in issues if "forces_scene" in i or "repeatable" in i], issues


def test_repeatable_must_be_a_bool(tmp_path: Path) -> None:
    issues = _issues(tmp_path, {"raid": _deck("raid", repeatable="yes")}, {"events": {}})
    assert [i for i in issues if "repeatable" in i], issues
