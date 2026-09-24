"""
The Law, part three: reports travel.

THE SHAPE. ``law.propagate(state, hours)`` runs inside ``clock.advance_time``
for a story that declares a Law. For each in-game hour boundary the clock
crossed, the hour that just elapsed is an hour of talk (the first 48 per call)
and then an hour of cooling (every one). In an hour of talk, everyone awake
shares a room with whoever else ``npc_sim`` placed there THROUGH THAT HOUR;
each deed a person holds may be told to one of them with ``spread_per_hour``
on the LAW stream, as a new ``witness`` row one hop further out at that hop's
precision. Never beyond hop 3, and never to anyone who already holds the deed
at any hop. A row reaching a ``roles`` person files a report with the watch
where that person stands.

WHAT THESE TESTS HOLD. A baker's sighting reaches the watch through a shared
room; precision decays by hop and hop 4 never happens; a told copy keeps the
deed, its id, severity, guise and place, at exactly its hop's precision; a
seed replays; the whole of ``state.law`` is a function of hours passed and not
of calls made -- twelve 1h advances, forty-eight quarter hours, twelve
background ticks and one 12h advance leave it bit-identical -- and a tick with
no time in it does nothing; a report filed late in a long call is not cooled
away by the hours before it; a long sleep talks for 48 hours at most; an hour
with no teller awake resolves only the tellers; and the flagship's
``advance_time`` never enters the pass.

Version: v0.1.0 [2026-09-24]
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Iterator

import pytest
import yaml

from engine.config import set_overlay
from engine.game import encounter
from engine.game.clock import advance_time, set_clock
from engine.game.effects import apply_effect
from engine.game.procgen import generate_world
from engine.game.rng import LAW
from engine.game.state import GameState
from engine.world import law, npc_sim
from engine.world.world_sim import ScheduleRoll, WorldSim

from test_law import SPEC as LAW_SPEC

BAKERY, SQUARE, GATE = "edgewood_bakery", "edgewood_square", "millhaven_gate"


def _slot(hours: range, where: str, *, awake: bool = True) -> dict[str, Any]:
    return {"hours": list(hours), "location": where, "activity": "about", "available": awake}


def _person(npc_id: str, role: str, routine: list[dict[str, Any]]) -> dict[str, Any]:
    return {"id": npc_id, "name": npc_id.replace("_", " ").title(), "role": role, "routine": routine}


#: A three-district town. The baker works the ovens in the morning and sells
#: in the square in the afternoon; the porter crosses the square at midday and
#: drinks by the gate at night; the watch stands the gate all day, with a
#: corporal beside it who never walks anywhere.
TOWN = [
    _person("gen_baker", "baker", [_slot(range(0, 12), BAKERY), _slot(range(12, 24), SQUARE)]),
    _person("gen_porter", "porter", [
        _slot(range(0, 12), "millhaven_market"),
        _slot(range(12, 18), SQUARE),
        _slot(range(18, 24), GATE),
    ]),
    _person("gen_watch", "watch", [_slot(range(24), GATE)]),
    _person("gen_corporal", "labourer", [_slot(range(24), GATE)]),
]


def _dump(path: Path, doc: Any) -> str:
    path.write_text(yaml.safe_dump(doc), encoding="utf-8")
    return str(path)


def _overlay(tmp_path: Path, **law_overrides: Any) -> None:
    doc = copy.deepcopy(LAW_SPEC)
    doc.update(law_overrides)
    set_overlay({"paths": {
        "law": _dump(tmp_path / "law.yaml", doc),
        # No scheduled cast: the synthetic town is the whole population.
        "npc_schedules": _dump(tmp_path / "npc_schedules.yaml", {"npcs": {}}),
    }})


@pytest.fixture()
def certain(tmp_path: Path) -> Iterator[Path]:
    """A Law whose rumours always travel -- the path, not the odds."""
    _overlay(tmp_path, spread_per_hour=1.0)
    try:
        yield tmp_path
    finally:
        set_overlay(None)


@pytest.fixture()
def lawful(tmp_path: Path) -> Iterator[Path]:
    """A Law at its default spread."""
    _overlay(tmp_path)
    try:
        yield tmp_path
    finally:
        set_overlay(None)


def _town(seed: int = 42, hour: int = 8, people: list[dict[str, Any]] | None = None) -> GameState:
    state = GameState(rng_seed=seed, location_id=BAKERY)
    state.procgen = generate_world(seed)
    state.procgen.npcs = copy.deepcopy(people if people is not None else TOWN)
    set_clock(state, day=1, hour=hour)
    return state


def _baker_sees(state: GameState) -> str:
    """A lift in the bakery, seen by the baker alone. Returns its deed id."""
    law.commit_deed(state, "pickpocket", location=BAKERY, certain=["gen_baker"])
    rows = state.law["witnessed"]
    assert [r["npc"] for r in rows] == ["gen_baker"]
    return rows[0]["deed_id"]


def _held(state: GameState, npc: str) -> list[dict[str, Any]]:
    return [r for r in state.law.get("witnessed") or [] if r["npc"] == npc]


# -- the path ------------------------------------------------------------------


def test_a_bakers_sighting_reaches_the_watch_through_a_shared_room(certain: Path) -> None:
    state = _town()
    deed_id = _baker_sees(state)
    assert not state.law.get("reports")  # the baker is nobody's watch

    # 12:00 -- the hour just gone, eleven to noon, the baker spent at the ovens.
    advance_time(state, 4)
    assert not _held(state, "gen_porter")

    advance_time(state, 1)  # 13:00 -- the noon hour in the square, with the porter
    assert [r["hop"] for r in _held(state, "gen_porter")] == [2]
    assert not state.law.get("reports")

    # 20:00 -- the porter spent 18:00 and 19:00 at the gate and has told both
    # men there, one an hour, in whichever order the dice chose.
    advance_time(state, 7)
    watch = _held(state, "gen_watch")
    assert [r["hop"] for r in watch] == [3]
    reports = state.law["reports"]
    assert len(reports) == 1
    # Filed where the watchman heard it, not where the deed was done: the
    # town's watch has heard about the village's thief.
    assert reports[0]["jurisdiction"] == "town"
    assert reports[0]["deed_id"] == deed_id
    assert reports[0]["precision"] == pytest.approx(0.3)


def test_precision_decays_by_hop(certain: Path) -> None:
    state = _town()
    _baker_sees(state)
    advance_time(state, 12)
    by_npc = {r["npc"]: r for r in state.law["witnessed"]}
    assert by_npc["gen_baker"]["precision"] == pytest.approx(1.0)
    assert by_npc["gen_porter"]["precision"] == pytest.approx(0.6)
    assert by_npc["gen_watch"]["precision"] == pytest.approx(0.3)


def test_hop_four_never_happens(certain: Path) -> None:
    # The corporal shares the gate with the watchman (hop 3) all day, and with
    # the porter (hop 2) from 18:00 -- so he hears it at 3, from the porter,
    # and never at 4 from the watchman however long they stand together.
    state = _town()
    _baker_sees(state)
    advance_time(state, 48)
    advance_time(state, 48)
    hops = [r["hop"] for r in state.law["witnessed"]]
    assert max(hops) == 3
    assert [r["hop"] for r in _held(state, "gen_corporal")] == [3]


def test_whoever_holds_a_deed_is_never_told_it_again(certain: Path) -> None:
    # A carter walks the porter's round. The baker tells both at hop 2 in the
    # square; the porter then stands beside the carter all afternoon and all
    # evening -- and under the gossip rule would hand him the same deed again
    # at hop 3, a copy that changes nothing and costs a roll.
    people = copy.deepcopy(TOWN)
    carter = copy.deepcopy(people[1])
    carter["id"], carter["name"] = "gen_carter", "Gen Carter"
    people.append(carter)
    state = _town(people=people)
    _baker_sees(state)
    advance_time(state, 48)
    advance_time(state, 48)
    assert [r["hop"] for r in _held(state, "gen_baker")] == [1]
    for npc in ("gen_porter", "gen_carter", "gen_watch", "gen_corporal"):
        assert len(_held(state, npc)) == 1, (npc, _held(state, npc))


def test_a_told_copy_keeps_what_was_seen(certain: Path) -> None:
    state = _town()
    _baker_sees(state)
    advance_time(state, 12)
    source = _held(state, "gen_baker")[0]
    for npc in ("gen_porter", "gen_watch"):
        copy_row = _held(state, npc)[0]
        for key in ("deed_id", "deed", "severity", "guise", "where"):
            assert copy_row[key] == source[key], (npc, key)
        assert copy_row["id"] != source["id"]


def test_a_propagated_row_needs_a_real_teller(certain: Path) -> None:
    state = _town()
    deed_id = _baker_sees(state)
    base = {"type": "witness", "deed": "pickpocket", "guise": "self", "npc": "gen_porter",
            "where": BAKERY, "deed_id": deed_id, "hop": 2, "precision": 0.6}
    # Each variant would let a copy say something the sighting did not.
    for bad in ({"deed_id": ""}, {"deed_id": "d99"}, {"guise": "magpie"},
                {"deed": "fencing"}, {"where": SQUARE}, {"hop": 3}, {"hop": 4},
                {"precision": 0.5}, {"precision": 1.0}):
        before = copy.deepcopy(state.law)
        receipt = apply_effect(state, {**base, **bad})
        assert receipt["ok"] is False, bad
        assert state.law == before, bad
    assert apply_effect(state, base)["ok"] is True


def test_no_report_where_no_watch_reaches(certain: Path) -> None:
    # The same watchman, standing in the forest: he hears, and there is no
    # watch-house for the word to reach.
    people = copy.deepcopy(TOWN)
    people[2]["routine"] = [_slot(range(24), "forest_clearing")]
    people[1]["routine"][2] = _slot(range(18, 24), "forest_clearing")
    state = _town(people=people)
    _baker_sees(state)
    advance_time(state, 12)
    assert _held(state, "gen_watch")
    assert not state.law.get("reports")


def test_sleepers_are_neither_told_nor_tell(certain: Path) -> None:
    people = copy.deepcopy(TOWN)
    people[1]["routine"][1] = _slot(range(12, 18), SQUARE, awake=False)
    state = _town(people=people)
    _baker_sees(state)
    advance_time(state, 6)  # 14:00, the porter dozing on a bench in the square
    assert not _held(state, "gen_porter")


# -- hours, not calls ------------------------------------------------------------


def _travelled(state: GameState) -> tuple[dict[str, Any], int]:
    """The whole of ``state.law`` -- rows, reports AND cooling -- and the draws it took."""
    return copy.deepcopy(state.law), state.rng_counters.get(LAW, 0)


def _law_after(steps: list[float], seed: int) -> tuple[dict[str, Any], int]:
    state = _town(seed=seed)
    _baker_sees(state)
    for hours in steps:
        advance_time(state, hours)
    return _travelled(state)


@pytest.mark.parametrize("seed", [1, 7, 42, 99])
def test_twelve_hours_is_twelve_hours_however_it_is_cut(lawful: Path, seed: int) -> None:
    once = _law_after([12.0], seed)
    assert _law_after([1.0] * 12, seed) == once
    assert _law_after([0.25] * 48, seed) == once
    assert _law_after([5.5, 0.5, 6.0], seed) == once


def test_a_seed_replays(lawful: Path) -> None:
    assert _law_after([30.0], 5) == _law_after([30.0], 5)


def test_seeds_differ(lawful: Path) -> None:
    # Not a tautology check on the replay above: at spread 0.3 the telling is
    # a roll, and a pass that never rolled would replay just as well.
    outcomes = {repr(_law_after([30.0], seed)[0]) for seed in range(12)}
    assert len(outcomes) > 1


def test_the_background_tick_adds_nothing_beyond_the_hours_it_passes(
    lawful: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The world tick's own schedule rolls could move people (a caravan); held
    # still, so the only difference between the two runs is how time was cut.
    for name in ("check_caravan", "check_tinker", "check_militia"):
        monkeypatch.setattr(ScheduleRoll, name, staticmethod(lambda *a, **k: []))
    ticked = _town(seed=3)
    _baker_sees(ticked)
    for _ in range(12):
        WorldSim.on_tick(ticked, hours=1.0)
    for _ in range(5):
        WorldSim.on_tick(ticked, hours=0.0)  # the menu sat open; no time passed
    assert _travelled(ticked) == _law_after([12.0], 3)


def test_a_long_sleep_steps_two_days_at_most(
    lawful: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stepped: list[int] = []
    real = law._propagate_hour

    def _count(state: GameState, scratch: GameState, hour: int, spec: dict[str, Any]) -> Any:
        stepped.append(hour)
        return real(state, scratch, hour, spec)

    monkeypatch.setattr(law, "_propagate_hour", _count)
    # Four days unfed would faint the player, and fainting costs hours through
    # a nested advance_time -- hours that really pass, and step on their own.
    # Held off here so the count is of the one call.
    monkeypatch.setattr(encounter, "check_death", lambda *_a, **_k: None)
    state = _town()
    _baker_sees(state)
    advance_time(state, 100)
    assert len(stepped) == law.MAX_PROPAGATION_HOURS == 48
    # The first two days after the clock started moving, in order, each the
    # hour that had just elapsed.
    assert stepped == list(range(8, 56))
    # Cooling is not capped: all hundred hours wore the file down.
    assert law.wanted_score(state, "self", "town") == pytest.approx(0.0)


def test_no_crime_no_walk(lawful: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(*_a: Any, **_k: Any) -> None:
        raise AssertionError("nothing to tell, so nothing to step through")

    monkeypatch.setattr(law, "_propagate_hour", _boom)
    state = _town()
    advance_time(state, 12)
    assert state.law == {}
    assert LAW not in state.rng_counters


def test_nothing_left_to_tell_stops_the_talk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A file with no hop past the witness: nobody can ever tell anybody, so
    # the first hour says so and the rest of the call does not look again.
    _overlay(tmp_path, precision={1: 1.0})
    try:
        calls: list[int] = []
        real = law._propagate_hour

        def _count(state: GameState, scratch: GameState, hour: int, spec: dict[str, Any]) -> Any:
            calls.append(hour)
            return real(state, scratch, hour, spec)

        monkeypatch.setattr(law, "_propagate_hour", _count)
        state = _town()
        _baker_sees(state)
        advance_time(state, 24)
        assert calls == [8]
        assert len(state.law["witnessed"]) == 1
    finally:
        set_overlay(None)


def test_an_hour_with_every_teller_abed_resolves_only_the_tellers(
    certain: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    people = copy.deepcopy(TOWN)
    people[0]["routine"][0] = _slot(range(0, 12), BAKERY, awake=False)
    state = _town(people=people)
    _baker_sees(state)
    resolved: list[str] = []
    real = npc_sim.resolve_npc

    def _count(scratch: GameState, npc_id: str) -> Any:
        resolved.append(npc_id)
        return real(scratch, npc_id)

    monkeypatch.setattr(npc_sim, "resolve_npc", _count)
    advance_time(state, 3)  # 08:00-11:00, the baker asleep over the ovens
    assert resolved.count("gen_baker") == 3
    assert set(resolved) - {"gen_baker"} == set()


# -- the flagship ----------------------------------------------------------------


def test_the_flagship_never_enters_the_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    assert not law.declared()

    def _boom(*_a: Any, **_k: Any) -> None:
        raise AssertionError("a story without a Law must not reach the Law")

    monkeypatch.setattr(law, "propagate", _boom)
    monkeypatch.setattr(law, "cool", _boom)
    state = _town(people=TOWN)
    advance_time(state, 30)
    assert state.law == {}
    assert LAW not in state.rng_counters


# -- cooling is on the clock now -------------------------------------------------


def test_the_clock_cools_the_watchs_memory(certain: Path) -> None:
    state = _town()
    _baker_sees(state)
    advance_time(state, 12)
    filed = law.filed_score(state, "self", "town")
    assert filed == pytest.approx(0.3)
    advance_time(state, 24)
    # 1.5 a day against a 0.3 file: worn to nothing, and capped there.
    assert law.cooling_of(state, "self", "town") == pytest.approx(filed)
    assert law.wanted_score(state, "self", "town") == pytest.approx(0.0)


def test_a_report_filed_late_in_a_long_call_is_not_cooled_by_the_hours_before_it(
    certain: Path,
) -> None:
    # No corporal, so the watchman is told in the first hour at the gate.
    state = _town(people=[p for p in TOWN if p["id"] != "gen_corporal"])
    _baker_sees(state)
    advance_time(state, 12)  # 08:00 -> 20:00; told through 18:00, filed at 19:00
    assert law.filed_score(state, "self", "town") == pytest.approx(0.3)
    # Two hours of cooling (the boundary it was filed at, and 20:00) -- not
    # the twelve of the whole call, which would have worn 0.3 to nothing.
    assert law.wanted_score(state, "self", "town") == pytest.approx(0.3 - 2 * 1.5 / 24)


# -- a quash lasts (v0.10.0 final fix: I1) ---------------------------------------


def test_a_quashed_deed_is_not_refiled_when_its_witnesses_talk(certain: Path) -> None:
    """A bribe that loses a file must not be undone by the next watchman to
    hear the gossip. Before the fix, the corporal's sighting reached the
    watchman beside him within the hour and ``propagate`` filed the deed
    again in the very watch-house that had just lost it."""
    state = _town()
    law.commit_deed(state, "pickpocket", location=GATE,
                    certain=["gen_corporal"], exclude=["gen_watch"])
    deed_id = state.law["witnessed"][0]["deed_id"]
    apply_effect(state, {"type": "report", "deed": "pickpocket", "guise": "self",
                         "jurisdiction": "town", "precision": 1.0, "deed_id": deed_id})
    assert law.filed_score(state, "self", "town") == pytest.approx(1.0)

    apply_effect(state, {"type": "quash_reports", "jurisdiction": "town"})
    assert state.law["quashed"] == {"town": [deed_id]}
    advance_time(state, 24)  # through the real clock

    assert _held(state, "gen_watch"), "the watchman did hear it -- he just cannot file it"
    assert not [r for r in state.law.get("reports") or [] if r["jurisdiction"] == "town"]
    assert law.wanted_score(state, "self", "town") == pytest.approx(0.0)


def test_a_quash_holds_only_where_it_was_bought(certain: Path) -> None:
    """The lost file is the town's. The same deed can still be filed with the
    village's watch -- nobody paid them."""
    state = _town()
    law.commit_deed(state, "pickpocket", location=GATE,
                    certain=["gen_corporal"], exclude=["gen_watch"])
    deed_id = state.law["witnessed"][0]["deed_id"]
    base = {"type": "report", "deed": "pickpocket", "guise": "self",
            "precision": 1.0, "deed_id": deed_id}
    apply_effect(state, {**base, "jurisdiction": "town"})
    apply_effect(state, {"type": "quash_reports", "jurisdiction": "town"})
    assert not apply_effect(state, {**base, "jurisdiction": "town"})["ok"]
    assert apply_effect(state, {**base, "jurisdiction": "village"})["ok"]


def test_the_quashed_record_survives_a_save(certain: Path) -> None:
    state = _town()
    law.commit_deed(state, "pickpocket", location=GATE,
                    certain=["gen_corporal"], exclude=["gen_watch"])
    deed_id = state.law["witnessed"][0]["deed_id"]
    apply_effect(state, {"type": "report", "deed": "pickpocket", "guise": "self",
                         "jurisdiction": "town", "precision": 1.0, "deed_id": deed_id})
    apply_effect(state, {"type": "quash_reports", "jurisdiction": "town"})
    loaded = GameState.from_dict(json.loads(json.dumps(state.to_save_dict())))
    assert law.quashed(loaded, "town") == {deed_id}
    # And a save from before the key existed loads with nothing quashed.
    old = json.loads(json.dumps(state.to_save_dict()))
    old["law"].pop("quashed")
    assert law.quashed(GameState.from_dict(old), "town") == set()
