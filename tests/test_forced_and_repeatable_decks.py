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
- A forced deck with its own ``when:`` waits for it (v0.17): the fair forced
  while the thief is in the Snuffs is neither dealt nor retired, deals once
  they reach Gallows Green, and an arrest on fair day deals the interrogation
  meanwhile. If the event lapses first, the fair is never dealt.
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
    # Forced by a declared event (the fair), but only where the fair IS and
    # only to a free thief: its own `when:` must hold before it deals (v0.17).
    # `event_active` too, because a deck with a `when:` is also SCHEDULED by
    # it: without it the green would deal the fair on any day.
    "fair_day": _deck(
        "fair_day",
        when={"all": [{"event_active": "hanging_fair"}, {"at_location": "gallows_green"},
                      {"in_custody": False}]},
    ),
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
        "hanging_fair": {
            "on_day": 3,
            "duration_days": 1,
            "location_id": "gallows_green",
            "text": "The gallows are dressed in bunting.",
            "forces_scene": "fair_day",
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


# -- a forced deck honours its own `when:` (v0.17) --------------------------------


def _scene_played(state: GameState, scene_id: str) -> bool:
    from engine.game import clocks

    return bool(state.flags.get(f"{clocks.SCENE_PLAYED_FLAG_PREFIX}{scene_id}"))


def test_a_forced_deck_waits_for_its_when_and_deals_once_it_holds(story: Any) -> None:
    """The fair is forced, but the thief is in the Snuffs: nothing is dealt,
    nothing is spent, and the promise stands. Walked to Gallows Green, it deals."""
    story("fair_day")
    state = _world([])
    state.location_id = "the_snuffs"
    _to_day(state, 3)
    from engine.game import clocks

    assert "fair_day" in clocks.forced_scenes(state)
    assert director.due(state) == ("", "", "")
    receipts = director.ensure_scene(state)
    assert receipts == [], receipts  # not "no cards were eligible"
    assert not state.flags.get(director._played_flag("fair_day"))
    assert not _scene_played(state, "fair_day"), "retired without being dealt"
    assert "fair_day" in clocks.forced_scenes(state)

    state.location_id = "gallows_green"
    assert director.due(state) == ("fair_day", "", "forced")
    assert _turn(state) == ["fair_day"]
    assert _scene_played(state, "fair_day")
    assert _turn(state) == []


def test_other_due_decks_deal_while_a_forced_deck_waits(story: Any) -> None:
    """An arrest on fair day deals the interrogation, not the fair: the fair
    wants a free thief on the green, and a forced promise it cannot yet keep
    must not hold the turn from a deck that can deal."""
    story("fair_day", "the_cells")
    state = _world([])
    state.location_id = "gallows_green"
    _to_day(state, 3)
    _arrest(state)
    state.location_id = "gallows_green"  # arrested on the green itself
    assert _turn(state) == ["the_cells"]
    assert not _scene_played(state, "fair_day")
    _release(state)
    state.location_id = "gallows_green"
    assert _turn(state) == ["fair_day"]


def test_a_forced_deck_whose_when_never_held_is_simply_not_dealt(story: Any) -> None:
    """The event lapses with the thief elsewhere the whole day: the fair is
    never dealt, and nothing about it is left pending once the row expires."""
    story("fair_day")
    state = _world([])
    state.location_id = "the_snuffs"
    dealt: list[str] = []
    for day in range(1, 6):
        _to_day(state, day)
        dealt += _turn(state)
    from engine.game import clocks

    assert dealt == []
    assert "fair_day" not in clocks.forced_scenes(state)
    state.location_id = "gallows_green"
    assert _turn(state) == []


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


#: Where a story's walk stands, when its one deck is not dealt at the entry.
#: HUE & CRY's initiation is dealt in the Snuffs (v0.16), not on the quay.
_WALK_FROM = {"hue-and-cry": "the_snuffs"}

#: Walks kept fed. Left standing forty eight-hour turns, HUE & CRY's walk
#: starved to 0 hp by its third day -- recorded in its digest, and nothing to
#: do with dealing. Fed at each step (hunger set to 0), it records the deal
#: alone. The other walks were recorded unfed and stay as recorded. (The
#: "Death rules missing" line it logged until v0.17 was not starvation: every
#: advance_time asks for death.yaml, which HUE & CRY ships since v0.17.)
_WALK_FED = {"hue-and-cry"}

#: Arrests and releases at fixed steps (``arrest`` / ``release`` effects, before
#: the step's deal). HUE & CRY's interrogation (v0.16 T5) is the first shipped
#: REPEATABLE deck -- dealt by `in_custody: true` on every stay -- so its walk
#: is taken to the cells twice, and the record holds both deals and the
#: re-arm between them (the `deck_played_interrogation` False write).
_WALK_CUSTODY = {"hue-and-cry": {4: "arrest", 6: "release", 9: "arrest", 11: "release"}}


def _walk(slug: str, winds: dict[int, list[tuple[str, float]]]) -> dict[str, Any]:
    """A fixed director walk: a turn every eight hours, first answer every time."""
    from engine.game import clocks
    from engine.game.procgen import new_game_state
    from engine.games import registry

    registry.activate(slug)
    try:
        state = new_game_state(
            seed=7, location_id=_WALK_FROM.get(slug) or registry.get(slug).entry_location
        )
        log: list[Any] = []
        for step in range(40):
            if slug in _WALK_FED:
                state.hunger = 0.0
            for name, by in winds.get(step, []):
                clocks.advance(state, name, by)
            clocks.resolve(state)
            custody = (_WALK_CUSTODY.get(slug) or {}).get(step)
            if custody:
                assert apply_effect(state, {"type": custody})["ok"], (slug, step, custody)
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


#: The first three recorded at b59a3ea, before repeatable decks and
#: event-forced scenes existed; later rows say when they were recorded.
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
    # Recorded at v0.16 T4 (fix round 1), when HUE & CRY gained its first
    # deck: the initiation, dealt once in the Snuffs on the first turn Gannet
    # holds court (18:00-04:00). Walked from the Snuffs, fed (`_WALK_FED`).
    # RE-RECORDED at v0.16 T5, and why: the interrogation joined it -- the
    # first shipped repeatable deck -- and a walk that is never arrested
    # would pin nothing of it (its digest came out unchanged). The walk is
    # now taken to the cells twice (`_WALK_CUSTODY`): the initiation, then
    # the interrogation on each arrest, re-armed by the release between.
    # RE-RECORDED at v0.16 T7, and why: the Lantern House front desk joined
    # (lantern_house_desk.yaml, repeatable). The first stay (steps 4-6) holds
    # the thief through the Magpie's small hours, so the release at step 6
    # leaves a free thief in the Lantern House with an alibi earned: the
    # desk deals D1_the_alibi, the walk's first answer presents it, and the
    # second stay's hand has no Q4 (the alibi was closed at the desk). The
    # desk's played flag is re-armed once its `when:` falls. The same run
    # twice gave the same digest.
    ("hue-and-cry", {}, ["initiation", "interrogation", "lantern_house_desk", "interrogation"],
     "83e47fb3974971b797898c1b9b26b7df91ddfb08afc51ba6730327b074b718ae"),
]


@pytest.mark.parametrize("slug,winds,decks,digest", SHIPPED_WALKS, ids=[w[0] for w in SHIPPED_WALKS])
def test_shipped_deck_stories_deal_as_recorded(
    slug: str, winds: dict[int, list[tuple[str, float]]], decks: Any, digest: Any
) -> None:
    walk = _walk(slug, winds)
    if decks is not None:
        assert [row[2] for row in walk["log"]] == decks
    encoded = json.dumps(walk, sort_keys=True).encode("utf-8")
    assert hashlib.sha256(encoded).hexdigest() == digest


#: The shipped decks that opt in to `repeatable`, and nothing else. Until
#: v0.16 this set was empty and the test asserted that nothing shipped opted
#: in. HUE & CRY's interrogation (v0.16 T5) is the first: dealt on every
#: arrest, which is exactly the case the key was built for (v0.13). Its walk
#: in SHIPPED_WALKS covers two deals and the re-arm between them; every other
#: story still declares neither key, so their walks stay byte-identical.
#: v0.16 T7 adds the second: HUE & CRY's Lantern House front desk (the
#: alibi and the accusation), dealt on each visit that finds something to
#: offer. The same walk now deals it once, after the first release.
#: v0.17 T3 (review round 1): the Hanging Fair re-deals on each return to the
#: Green while it is on, so a door card come due since the last visit is met.
SHIPPED_REPEATABLE = {("hue-and-cry", "interrogation"), ("hue-and-cry", "lantern_house_desk"),
                      ("hue-and-cry", "fair_day"),
                      # v0.17 T6: Guildmaster's door and Partners' first half.
                      ("hue-and-cry", "porters_hall"), ("hue-and-cry", "the_confrontation"),
                      # v0.17 T8 fix round 1: Partners' door after the fair.
                      ("hue-and-cry", "the_last_job")}


def test_only_hue_and_crys_six_decks_opt_in() -> None:
    """Byte-identical by construction for every other story: nothing else
    shipped declares either key."""
    root = Path(__file__).resolve().parents[1] / "games"
    opted: set[tuple[str, str]] = set()
    for path in root.glob("*/data/**/*.yaml"):
        # A DECK's `repeatable` is a top-level key of its file. Read as YAML
        # rather than grepped: since v0.15 a thread TEMPLATE may declare its
        # own `repeatable` (HUE & CRY's fence credit, threads.yaml), nested
        # under `templates:`, which is not a deck opting in.
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        if isinstance(doc, dict) and "repeatable" in doc:
            assert doc["repeatable"] is True, path
            assert path.parent.name == "scenes", path
            opted.add((path.relative_to(root).parts[0], path.stem))
    assert opted == SHIPPED_REPEATABLE
    # An event that forces a scene: HUE & CRY's Hanging Fair (v0.17 T3), and
    # nothing in any other story.
    forcing: set[tuple[str, str, str]] = set()
    for path in root.glob("*/data/world/schedules.yaml"):
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for event_id, spec in (doc.get("events") or {}).items():
            if "forces_scene" in (spec or {}):
                forcing.add((path.relative_to(root).parts[0], str(event_id),
                             str(spec["forces_scene"])))
    assert forcing == {("hue-and-cry", "hanging_fair", "fair_day")}


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


# -- event ids in conditions name declared events (v0.17 T3, review round 1) --


def test_an_event_predicate_naming_no_declared_event_is_an_error(tmp_path: Path) -> None:
    """A typo in `event_active` / `held_before_event` / `event_seen` is false
    forever and silently: the validator names it."""
    events = {"events": {"hanging_fair": {"on_day": 3, "forces_scene": "fair"}}}
    decks = {"fair": _deck("fair", when={"all": [{"event_active": "hanging_fiar"},
                                                 {"held_before_event": "hanging_fair"}]})}
    issues = _issues(tmp_path, decks, events)
    hits = [i for i in issues if "hanging_fiar" in i]
    assert hits and "fair.yaml" in hits[0], issues
    assert not [i for i in issues if "'hanging_fair'" in i], issues


def test_an_event_predicate_naming_a_declared_event_is_clean(tmp_path: Path) -> None:
    events = {"events": {"hanging_fair": {"on_day": 3, "forces_scene": "fair"}}}
    decks = {"fair": _deck("fair", when={"all": [{"event_active": "hanging_fair"},
                                                 {"event_seen": ["hanging_fair"]},
                                                 {"held_before_event": "hanging_fair"}]})}
    issues = _issues(tmp_path, decks, events)
    assert not [i for i in issues if "event" in i.split("|")[-1] and "declare" in i], issues


# -- the re-arm trigger, by the kind of row that forces (T3 review round 2) -----


def _one_story(tmp_path: Path, decks: dict[str, Any], events: dict[str, Any]) -> None:
    set_overlay({"paths": _write_story(tmp_path, decks, events)})
    schedules._SCHEDULE_CACHE = None
    director._WARNED_FORCED = None


def _clear_story() -> None:
    schedules._SCHEDULE_CACHE = None
    director._WARNED_FORCED = None
    set_overlay(None)


def test_a_card_forced_repeatable_deck_is_dealt_once_per_event(tmp_path: Path) -> None:
    """The reviewer's probe: a repeatable deck whose `when:` never holds, with
    one of its CARDS forced by an event. The forced-card path ignores the
    deck's `when:`, so the card deals; the event is its trigger, and while
    the event stands the deck stays spent -- one deal, not one a turn."""
    deck = _deck("brawl", when={"flag": "never_set"}, repeatable=True)
    events = {"events": {"market_day": {"on_day": 2, "duration_days": 1,
                                        "forces_scene": "brawl_card"}}}
    _one_story(tmp_path, {"brawl": deck}, events)
    try:
        state = _world([])
        _to_day(state, 2)
        dealt = []
        for _ in range(5):
            dealt += _turn(state)
            clock_module.advance_time(state, 1)
        assert dealt == ["brawl"], dealt
    finally:
        _clear_story()


def test_a_deck_forced_repeatable_deck_with_a_when_re_arms_on_its_when(tmp_path: Path) -> None:
    """The fair's shape: forced as a DECK by a declared event and gated on its
    own `when:`. Walking off the green (the `when:` falls) re-arms it while
    the event still stands; coming back deals it again, once."""
    deck = _deck("fair", when={"all": [{"event_active": "the_fair"}, {"flag": "on_green"}]},
                 repeatable=True)
    events = {"events": {"the_fair": {"on_day": 2, "duration_days": 2, "forces_scene": "fair"}}}
    _one_story(tmp_path, {"fair": deck}, events)
    try:
        state = _world([])
        _to_day(state, 2)
        dealt = []
        for on_green in (True, True, False, True, True):
            apply_effect(state, {"type": "flag", "flag": "on_green", "value": on_green})
            dealt += _turn(state)
        assert dealt == ["fair", "fair"], dealt
    finally:
        _clear_story()


def test_a_clock_forced_repeatable_deck_never_re_arms(tmp_path: Path) -> None:
    """A clock beat's row is permanent, so a deck it forces is its promise
    kept once -- `when:` or no `when:` (rearm's docstring)."""
    deck = _deck("omen", when={"flag": "on_green"}, repeatable=True)
    _one_story(tmp_path, {"omen": deck}, {"events": {}})
    try:
        state = _world([])
        state.world_events.append({"event_id": "clock_beat_omen", "forces_scene": "omen"})
        dealt = []
        for on_green in (True, True, False, True, False, True):
            apply_effect(state, {"type": "flag", "flag": "on_green", "value": on_green})
            dealt += _turn(state)
        assert dealt == ["omen"], dealt
    finally:
        _clear_story()
