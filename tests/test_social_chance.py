"""Chance meetings with the cast (v0.23.0 addendum 4, W9; C3, I7)."""

from __future__ import annotations

import copy
import time

import pytest

from tests.social_fixtures import (  # noqa: F401
    _force_stage, _live_session, _matched_in, _phone, matched, receipts_active, receipts_state,
)


@pytest.fixture
def always_out(monkeypatch):
    """Every person is out now (their schedule forced) and fits one venue, The Anchor: the draw then decides only
    whether they are out at all, and `_cfg` forces that too."""
    from engine.social import behaviour, places

    monkeypatch.setattr(behaviour, "status_at", lambda person, at: "out")
    monkeypatch.setattr(places, "fitting_venues", lambda state, pid, kind="": ["the_anchor"])


def _cfg(monkeypatch, **over):
    """scenes.yaml `chance:` with `over` laid over it (a forced probability makes every draw certain)."""
    from engine import social

    real = social.data

    def data(name):
        d = real(name)
        if name == "scenes":
            d = {**d, "chance": {**(d.get("chance") or {}), **over}}
        return d

    monkeypatch.setattr(social, "data", data)


def _pid(matched) -> str:
    return matched("matchstick").split(":")[1]


def _at_the_anchor(state) -> None:
    state.location_id = "the_anchor"
    state.social["phone_up"] = False


# -- who can be where -----------------------------------------------------------------------------------------


def test_chance_presence_replays_and_writes_nothing(receipts_state, matched, always_out, monkeypatch) -> None:
    from engine.social import presence

    _cfg(monkeypatch, prob={"out": 1.0, "free": 1.0})
    pid = _pid(matched)
    _at_the_anchor(receipts_state)
    before = copy.deepcopy(receipts_state.to_save_dict())
    counters = dict(receipts_state.rng_counters)
    first = presence.chance_here(receipts_state, "the_anchor")
    assert pid in first and presence.chance_here(receipts_state, "the_anchor") == first
    presence.here_view(receipts_state)
    presence.with_player(receipts_state, pid)
    assert receipts_state.to_save_dict() == before
    assert dict(receipts_state.rng_counters) == counters           # rule 4: no stream moved


def test_the_draw_replays_from_the_seed(receipts_state, matched, monkeypatch) -> None:
    """The real draw (no forced probability): the same seed, day and block give the same answer, whoever asks."""
    from engine.social import behaviour, presence

    monkeypatch.setattr(behaviour, "status_at", lambda person, at: "out")
    pid = _pid(matched)
    answers = {presence._chance_venue(receipts_state, pid) for _ in range(5)}
    assert len(answers) == 1


def test_one_venue_per_block(receipts_state, matched, monkeypatch) -> None:
    from engine.social import behaviour, places, presence

    monkeypatch.setattr(behaviour, "status_at", lambda person, at: "out")
    monkeypatch.setattr(places, "fitting_venues", lambda state, pid, kind="": ["lantern_wine_bar", "the_anchor"])
    _cfg(monkeypatch, prob={"out": 1.0})
    pid = _pid(matched)
    seen = []
    for venue in ("the_anchor", "lantern_wine_bar"):
        receipts_state.location_id = venue
        if pid in presence.chance_here(receipts_state, venue):
            seen.append(venue)
    assert len(seen) == 1


def test_off_schedule_is_nowhere(receipts_state, matched, always_out, monkeypatch) -> None:
    """At work or asleep (no `prob` row) a person is at no venue, whatever the draw."""
    from engine.social import behaviour, presence

    _cfg(monkeypatch, prob={"out": 1.0, "free": 1.0})
    pid = _pid(matched)
    _at_the_anchor(receipts_state)
    for status in ("work", "asleep"):
        monkeypatch.setattr(behaviour, "status_at", lambda person, at, s=status: s)
        assert pid not in presence.chance_here(receipts_state, "the_anchor")


def test_presence_never_reads_the_population(receipts_state, matched, always_out, monkeypatch) -> None:
    from engine.social import population, presence, relationships

    _cfg(monkeypatch, prob={"out": 1.0})
    matched("matchstick")
    _at_the_anchor(receipts_state)
    calls = []
    real = population.profile
    monkeypatch.setattr(population, "profile", lambda s, p: calls.append(p) or real(s, p))
    presence.chance_here(receipts_state, "the_anchor")
    live = [p for p, row in receipts_state.social["people"].items() if row.get("stage") in relationships.LIVE_STAGES]
    assert live and len(calls) <= len(live)
    assert set(calls) <= set(live)


def test_chance_tier_skipped_away_from_venues(receipts_state, matched, monkeypatch) -> None:
    from engine.social import population, presence

    matched("matchstick")
    monkeypatch.setattr(population, "profile", lambda s, p: (_ for _ in ()).throw(AssertionError("read")))
    for room in ("apt_lounge", "bldg_reception"):
        receipts_state.location_id = room
        assert presence.here_view(receipts_state)["chance"] == ()
        assert presence.chance_here(receipts_state, room) == ()


def test_no_chance_presence_at_work(receipts_state, matched, always_out, monkeypatch) -> None:
    from engine.social import presence

    _cfg(monkeypatch, prob={"out": 1.0})
    _pid(matched)
    _at_the_anchor(receipts_state)
    receipts_state.social["at_work"] = True
    assert presence.chance_here(receipts_state, "the_anchor") == ()


def test_here_view_computed_once_per_pass(receipts_state, matched, always_out, monkeypatch) -> None:
    from engine.social import presence

    _cfg(monkeypatch, prob={"out": 1.0})
    pid = _pid(matched)
    _at_the_anchor(receipts_state)
    view = presence.here_view(receipts_state)
    assert pid in view["chance"] and presence.where(receipts_state, pid, view) == "the_anchor"
    monkeypatch.setattr(presence, "chance_here", lambda *a, **k: (_ for _ in ()).throw(AssertionError("again")))
    assert presence.with_player(receipts_state, pid, view)


def test_one_question_agrees_with_the_view(receipts_state, matched, always_out, monkeypatch) -> None:
    """`with_player` with no view (the delivery seam's one question) answers as the pass's view does, the
    `max_here` cut included."""
    from engine.social import presence

    pids = [_pid(matched) for _ in range(3)]
    _at_the_anchor(receipts_state)
    for prob, here in ((1.0, 1), (1.0, 2), (0.0, 2)):
        _cfg(monkeypatch, prob={"out": prob}, max_here=here)
        view = presence.here_view(receipts_state)
        assert len(view["chance"]) == (here if prob else 0)
        for pid in pids:
            assert presence.with_player(receipts_state, pid) == presence.with_player(receipts_state, pid, view)


def test_at_most_max_here(receipts_state, matched, always_out, monkeypatch) -> None:
    from engine.social import presence

    _cfg(monkeypatch, prob={"out": 1.0}, max_here=2)
    pids = sorted(_pid(matched) for _ in range(3))
    _at_the_anchor(receipts_state)
    assert presence.chance_here(receipts_state, "the_anchor") == tuple(pids[:2])


def test_the_excluded_are_never_by_chance(receipts_state, matched, always_out, monkeypatch) -> None:
    """The blocked, the ghosting, the household partner and anyone in the scene are no candidates."""
    from engine.social import presence

    _cfg(monkeypatch, prob={"out": 1.0}, max_here=8)
    pids = [_pid(matched) for _ in range(4)]
    _at_the_anchor(receipts_state)
    people = receipts_state.social["people"]
    people[pids[0]]["blocked"] = True
    people[pids[1]]["ghosted"] = True
    receipts_state.social["household"] = pids[2]
    assert presence.chance_here(receipts_state, "the_anchor") == (pids[3],)
    assert presence.chance_here(receipts_state, "the_anchor", scene_pid=pids[3]) == ()


def test_away_is_never_by_chance(receipts_state, matched, always_out, monkeypatch) -> None:
    from engine.social import life, presence

    _cfg(monkeypatch, prob={"out": 1.0})
    pid = _pid(matched)
    _at_the_anchor(receipts_state)
    receipts_state.social["people"][pid]["life"] = [{"id": "x"}]
    monkeypatch.setattr(life, "unavailable", lambda s, p, at: p == pid)
    assert pid not in presence.chance_here(receipts_state, "the_anchor")


def test_candidates_capped_most_recent_first(receipts_state, matched, always_out, monkeypatch) -> None:
    from engine.social import presence

    _cfg(monkeypatch, prob={"out": 1.0}, max_candidates=1)
    old, new = _pid(matched), _pid(matched)
    people = receipts_state.social["people"]
    people[old]["last_player_at"], people[new]["last_player_at"] = 1.0, 5.0
    assert presence.candidates(receipts_state, presence._chance_cfg()) == [new]


def test_planned_person_is_never_by_chance(receipts_state, matched, always_out, monkeypatch) -> None:
    from engine.social import plans, presence
    from tests.test_social_plans import _willing_meet

    _cfg(monkeypatch, prob={"out": 1.0})
    _willing_meet(monkeypatch)
    pid = _pid(matched)
    assert plans.make(receipts_state, pid, kind="drinks", when="now", venue="lantern_wine_bar") is not None
    _at_the_anchor(receipts_state)
    assert pid not in presence.chance_here(receipts_state, "the_anchor")


# -- cost (I7) -------------------------------------------------------------------------------------------------


def test_chance_tier_cost_is_bounded(receipts_state, matched, monkeypatch) -> None:
    """A 1,200-person people slice with 300 live contacts: one pass reads at most `max_candidates` draws and only
    the profiles of those whose draw falls under the highest probability (the real `prob`, not forced), and takes
    well under the bound at a venue."""
    from engine.game import rng
    from engine.social import population, presence

    pid = _pid(matched)
    template = copy.deepcopy(receipts_state.social["people"][pid])
    people = receipts_state.social["people"]
    ids = [i for i in population.pool("matchstick") if f"p{i}" not in people][:1200]
    assert len(ids) == 1200
    for n, i in enumerate(ids):
        row = copy.deepcopy(template) if n < 300 else {"rng_n": {"x": 1}}
        if n < 300:
            row["last_player_at"] = float(n)
        people[f"p{i}"] = row
    _at_the_anchor(receipts_state)
    draws, reads = [], []
    real_rng, real_profile = rng.stable_rng, population.profile
    monkeypatch.setattr(presence, "stable_rng", lambda seed, stream: draws.append(stream) or real_rng(seed, stream))
    monkeypatch.setattr(population, "profile", lambda s, p: reads.append(p) or real_profile(s, p))
    cfg = presence._chance_cfg()
    presence.here_view(receipts_state)
    assert len(draws) <= int(cfg["max_candidates"])
    top = max(float(v) for v in cfg["prob"].values())
    assert len(set(reads)) <= int(cfg["max_candidates"] * top * 2) + 5      # ~top x candidates, generous for chance
    monkeypatch.undo()
    runs = []
    for _ in range(7):
        t0 = time.perf_counter()
        presence.here_view(receipts_state)
        runs.append(time.perf_counter() - t0)
    assert sorted(runs)[len(runs) // 2] < 0.015         # the median: measured ~1-2 ms here; headroom for slow CI


# -- going over (W9, C3) ---------------------------------------------------------------------------------------


def test_approach_is_offered_and_opens_a_chance_scene(receipts_state, matched, always_out, monkeypatch) -> None:
    from engine import social
    from engine.social import scene, world

    _cfg(monkeypatch, prob={"out": 1.0})
    pid = _pid(matched)
    _at_the_anchor(receipts_state)
    verb = next(v for v in world.world_verbs(receipts_state) if v.action == "scene")
    assert f"approach:{pid}" in dict(verb.options)
    out = scene.move(receipts_state, f"approach:{pid}")
    assert out["ok"] and out["opened"] == "chance"
    assert social.scene_open(receipts_state) and scene.current(receipts_state)["kind"] == "chance"
    assert scene.approach_options(receipts_state) == []          # nobody else is approached while it is open


def test_approach_refused_for_someone_not_here(receipts_state, matched, always_out, monkeypatch) -> None:
    from engine import social
    from engine.social import scene

    _cfg(monkeypatch, prob={"out": 0.0, "free": 0.0})
    pid = _pid(matched)
    _at_the_anchor(receipts_state)
    assert not scene.move(receipts_state, f"approach:{pid}")["ok"]
    assert not social.scene_open(receipts_state)


def test_approach_records_a_soon_plan_met(receipts_state, matched, always_out, monkeypatch) -> None:
    from engine.social import plans, scene
    from tests.test_social_plans import _willing_meet

    _cfg(monkeypatch, prob={"out": 1.0})
    _willing_meet(monkeypatch)
    pid = _pid(matched)
    row = plans.make(receipts_state, pid, kind="drinks", when="soon", venue="lantern_wine_bar")
    assert row is not None
    _at_the_anchor(receipts_state)
    out = scene.move(receipts_state, f"approach:{pid}")
    assert out["ok"] and out["met"] == row["id"]
    assert plans.get(receipts_state, row["id"])["status"] == "met"


def test_chance_prior_takes_its_bias(receipts_state, matched, monkeypatch) -> None:
    from engine.social import scene

    monkeypatch.setattr(scene, "_prior_draw", lambda s, p: 0.0)
    _cfg(monkeypatch, prior_bias=-0.25)
    pid = _pid(matched)
    _at_the_anchor(receipts_state)
    scene.open_scene(receipts_state, pid, "the_anchor", kind="chance")
    chance = scene.current(receipts_state)["prior"]
    scene.end_scene(receipts_state, "player", then="stay")
    scene.open_scene(receipts_state, pid, "the_anchor", kind="drinks")
    assert scene.current(receipts_state)["prior"] - chance == pytest.approx(0.25, abs=1e-5)


def test_chance_scene_never_skips_a_willingness_gate(receipts_state, matched, monkeypatch) -> None:
    """C3: a matched, never-texted contact and a fine-or-better chance scene leave the stage and numbers alone;
    one whose `number` gate holds swaps numbers, and still does not reach `meeting` without `meet`."""
    from engine.social import growth, messaging, scene

    monkeypatch.setattr(scene, "_scene_band", lambda avg: "great")
    pid = _pid(matched)
    _at_the_anchor(receipts_state)
    monkeypatch.setattr(growth, "willing", lambda s, p, c: (False, "not_yet"))
    threads = set(receipts_state.social["threads"])
    scene.open_scene(receipts_state, pid, "the_anchor", kind="chance")
    scene.end_scene(receipts_state, "player", then="stay")
    person = receipts_state.social["people"][pid]
    assert person["stage"] == "matched" and set(receipts_state.social["threads"]) == threads
    assert int(person.get("meets_good", 0)) == 0                 # a pre-meeting run-in pre-pays no branch
    assert int(person["scenes_done"]) == 1
    monkeypatch.setattr(growth, "willing", lambda s, p, c: (c == "number", ""))
    scene.open_scene(receipts_state, pid, "the_anchor", kind="chance")
    scene.end_scene(receipts_state, "player", then="stay")
    assert person["stage"] == "numbers" and int(person.get("meets_good", 0)) == 0
    assert any(t.startswith(tuple(f"{a}:" for a in messaging.messengers())) for t in receipts_state.social["threads"])
    monkeypatch.setattr(growth, "willing", lambda s, p, c: (True, ""))
    scene.open_scene(receipts_state, pid, "the_anchor", kind="chance")
    scene.end_scene(receipts_state, "player", then="stay")
    assert person["stage"] == "meeting" and int(person.get("meets_good", 0)) == 1


def test_a_planned_scene_keeps_its_branch(receipts_state, matched, monkeypatch) -> None:
    """Every other kind keeps today's end: its plan already passed `meet`, so no `willing` is asked."""
    from engine.social import growth, scene

    monkeypatch.setattr(scene, "_scene_band", lambda avg: "great")
    monkeypatch.setattr(growth, "willing", lambda s, p, c: (_ for _ in ()).throw(AssertionError(c)))
    pid = _pid(matched)
    _at_the_anchor(receipts_state)
    apply = scene.apply_effect
    apply(receipts_state, {"type": "social_scene", "op": "open", "pid": pid, "location": "the_anchor", "kind": "drinks"})
    scene.end_scene(receipts_state, "player", then="stay")
    person = receipts_state.social["people"][pid]
    assert person["stage"] == "meeting" and int(person["meets_good"]) == 1


def test_the_run_in_goes_on_their_card(receipts_state, matched, monkeypatch) -> None:
    from engine.social import growth, scene

    monkeypatch.setattr(growth, "willing", lambda s, p, c: (False, "not_yet"))
    pid = _pid(matched)
    _at_the_anchor(receipts_state)
    scene.open_scene(receipts_state, pid, "the_anchor", kind="chance")
    scene.end_scene(receipts_state, "player", then="stay")
    from engine.social import memory

    lines = [str(h.get("text") or "") for h in memory.part(receipts_state.social["people"][pid], "history")]
    assert any(line.startswith("Ran into each other at The Anchor") for line in lines)


def test_chance_closers_need_meet(receipts_state, matched, monkeypatch) -> None:
    from engine.social import growth, scene

    pid = _pid(matched)
    _force_stage(receipts_state, pid, "meeting")
    _at_the_anchor(receipts_state)
    monkeypatch.setattr(growth, "willing", lambda s, p, c: (c != "meet", ""))
    scene.open_scene(receipts_state, pid, "the_anchor", kind="chance")
    targets = [t for t, _ in scene._close_options(receipts_state, scene.current(receipts_state))]
    ids = {t.split(":")[0] for t in targets}
    assert not {"back_to_yours", "back_to_theirs", "go_somewhere_else"} & ids
    assert "call_it_a_night:plan:soon" not in targets
    assert {"call_it_a_night", "walk_them_home"} <= ids              # the way home is never gated
    monkeypatch.setattr(growth, "willing", lambda s, p, c: (True, ""))
    targets = [t for t, _ in scene._close_options(receipts_state, scene.current(receipts_state))]
    assert "call_it_a_night:plan:soon" in targets and "back_to_yours" in {t.split(":")[0] for t in targets}


# -- the phone while they are here (W5) --------------------------------------------------------------------------


def test_no_text_from_someone_present_by_chance(receipts_state, matched, always_out, monkeypatch) -> None:
    """Across the room counts as together (A4 W5: "a W9 chance person at the player's venue"), approached or not:
    their text is held, re-pushed, never dropped; it lands once the player has left."""
    from engine.game import clock
    from engine.social import messaging, world
    from engine.social.kinds import Decision

    _cfg(monkeypatch, prob={"out": 1.0})
    tid = matched("matchstick")
    pid = tid.split(":")[1]
    _at_the_anchor(receipts_state)

    def theirs():
        return [m for m in receipts_state.social["threads"][tid].get("messages") or () if m.get("from") == pid]

    landed = len(theirs())
    messaging.queue_due(receipts_state, pid, tid, Decision(situation="reply"), receipts_state.world_clock_hours + 0.1)
    clock.advance_time(receipts_state, 0.5)
    assert len(theirs()) == landed
    assert [e for e in receipts_state.social["queue"] if e["pid"] == pid and e["kind"] == "reply" and e.get("held")]
    world.go(receipts_state, world.HOME)
    assert len(theirs()) == landed + 1


def test_no_text_lands_in_a_chance_scene(receipts_state, matched, always_out, monkeypatch) -> None:
    from engine.game import clock
    from engine.social import messaging, scene
    from engine.social.kinds import Decision

    _cfg(monkeypatch, prob={"out": 1.0})
    tid = matched("matchstick")
    pid = tid.split(":")[1]
    _at_the_anchor(receipts_state)
    assert scene.move(receipts_state, f"approach:{pid}")["ok"]
    before = len(receipts_state.social["threads"][tid].get("messages") or ())
    messaging.queue_due(receipts_state, pid, tid, Decision(situation="reply"), receipts_state.world_clock_hours + 0.1)
    clock.advance_time(receipts_state, 0.5)
    assert len(receipts_state.social["threads"][tid].get("messages") or ()) == before


# -- what the player and the narrator see -------------------------------------------------------------------------


def test_also_here_reaches_the_narrator_and_the_payload(receipts_state, matched, always_out, monkeypatch) -> None:
    import json

    from engine.social import payload, scene, world

    _cfg(monkeypatch, prob={"out": 1.0})
    pid = _pid(matched)
    _at_the_anchor(receipts_state)
    name = scene._name(receipts_state, pid)
    assert f"Also here: {name} (just matched)." in world.narration_block(receipts_state)
    here = payload.phone_block(receipts_state)["world"]["here"]
    assert {"name": name, "kind": "contact"} in here
    assert all(set(r) == {"name", "kind"} and r["kind"] in ("contact", "around") for r in here)
    assert pid not in json.dumps(here)


def test_nobody_also_here_off_venues(receipts_state, matched, always_out, monkeypatch) -> None:
    from engine.social import payload, world

    _cfg(monkeypatch, prob={"out": 1.0})
    _pid(matched)
    receipts_state.location_id = "apt_lounge"
    assert "Also here" not in world.narration_block(receipts_state)
    assert [r for r in payload.phone_block(receipts_state)["world"]["here"] if r["kind"] == "contact"] == []


def test_staff_on_shift_are_around(receipts_state, monkeypatch) -> None:
    """W8's background people at this place now are listed `around`, by name."""
    from engine.world import npc_sim
    from engine.social import world

    receipts_state.location_id = "the_anchor"
    present = [p.name for p in npc_sim.npcs_at(receipts_state, "the_anchor")]
    assert [r["name"] for r in world.here_rows(receipts_state) if r["kind"] == "around"] == present


# -- the data ---------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("bad", [
    {"prob": {"out": 1.5}}, {"prob": {"dancing": 0.1}}, {"block_hours": 0}, {"max_here": 0},
    {"max_candidates": 1.5}, {"prior_bias": "low"}, {"extra": 1},
])
def test_scenes_chance_block_is_checked(receipts_active, bad) -> None:
    from engine import social
    from engine.social import scene

    data = copy.deepcopy(social.data("scenes"))
    data["chance"] = {**data["chance"], **bad}
    with pytest.raises(ValueError, match="scenes.yaml: chance"):
        scene.check_data(data)


def test_no_chance_block_means_nobody_by_chance(receipts_state, matched, always_out, monkeypatch) -> None:
    from engine import social
    from engine.social import presence

    real = social.data
    monkeypatch.setattr(social, "data", lambda name: {k: v for k, v in real(name).items() if k != "chance"}
                        if name == "scenes" else real(name))
    _pid(matched)
    _at_the_anchor(receipts_state)
    assert presence.chance_here(receipts_state, "the_anchor") == ()


# -- the review's three (T23G fix round 0) ---------------------------------------------------------------------


def _to_block_start(state, minutes_before: float = 0.0) -> None:
    """The clock moved (rule 2) to `minutes_before` minutes before the next chance block begins."""
    from engine.game import clock
    from engine.social import presence

    size = float(presence._chance_cfg()["block_hours"])
    now = float(state.world_clock_hours)
    nxt = (now // size + 1) * size
    clock.advance_time(state, max(0.0, nxt - now - minutes_before / 60.0))


def test_no_reapproach_for_the_rest_of_their_block(receipts_state, matched, always_out, monkeypatch) -> None:
    from engine.social import scene

    _cfg(monkeypatch, prob={"out": 1.0})
    pid = _pid(matched)
    _at_the_anchor(receipts_state)
    _to_block_start(receipts_state)                         # a fresh block, its whole length ahead
    assert scene.move(receipts_state, f"approach:{pid}")["ok"]
    scene.end_scene(receipts_state, "player", then="stay")
    assert f"approach:{pid}" not in dict(scene.approach_options(receipts_state))
    assert not scene.move(receipts_state, f"approach:{pid}")["ok"]
    _to_block_start(receipts_state)                         # the next block: they may be here again
    assert f"approach:{pid}" in dict(scene.approach_options(receipts_state))


def test_the_run_in_mark_is_one_bounded_key_that_round_trips(receipts_state, matched, always_out, monkeypatch) -> None:
    import json

    from engine.game.state import GameState
    from engine.social import scene

    _cfg(monkeypatch, prob={"out": 1.0})
    pid = _pid(matched)
    _at_the_anchor(receipts_state)
    for _ in range(3):                                      # three blocks, three run-ins: still one key
        _to_block_start(receipts_state)
        assert scene.move(receipts_state, f"approach:{pid}")["ok"]
        scene.end_scene(receipts_state, "player", then="stay")
    mark = receipts_state.social["people"][pid]["chance_met"]
    assert isinstance(mark, str) and len(mark) < 16
    text = json.dumps(receipts_state.to_save_dict(), ensure_ascii=False)
    again = GameState.from_dict(json.loads(text))
    assert again.social["people"][pid]["chance_met"] == mark
    assert json.dumps(again.to_save_dict(), ensure_ascii=False) == text


def test_a_chance_scene_sends_no_after_date_text(receipts_state, matched, always_out, monkeypatch) -> None:
    """texter.md has no chance follow-up row, so a run-in sends none (a planned evening still does)."""
    from engine.social import scene

    monkeypatch.setattr(scene, "_scene_band", lambda avg: "great")
    pid = _pid(matched)
    _at_the_anchor(receipts_state)

    def post_meets():
        return [e for e in receipts_state.social["queue"] if e["pid"] == pid
                and ((e.get("decision") or {}).get("situation") == "post_meet")]

    scene.open_scene(receipts_state, pid, "the_anchor", kind="chance")
    scene.end_scene(receipts_state, "player", then="stay")
    assert post_meets() == []
    scene.open_scene(receipts_state, pid, "the_anchor", kind="drinks")
    scene.end_scene(receipts_state, "player", then="stay")
    assert len(post_meets()) == 1


def _present_until_the_block_turns(monkeypatch, state) -> None:
    """Chance presence forced to THIS block only: everyone is at The Anchor until the block turns."""
    from engine.social import presence

    first = presence._block(state, presence._chance_cfg())

    def venue(state_, pid, cfg=None, block=None):
        now = presence._block(state_, cfg or presence._chance_cfg()) if block is None else block
        return "the_anchor" if now == first else ""

    monkeypatch.setattr(presence, "_chance_venue", venue)


def test_held_texts_land_when_their_block_moves_them_on_phone_action(receipts_active, monkeypatch) -> None:
    """Crossing a block boundary: the held text lands at the next phone action, not at its re-push 15 minutes on,
    and a voicing pass is asked for."""
    from engine.game import clock
    from engine.session.store import release_turn
    from engine.social import messaging, voicer
    from engine.social.kinds import Decision

    scene, session = _live_session()
    tid = _matched_in(session, "matchstick")
    pid = tid.split(":")[1]
    state = session.engine.state
    assert session.lock.acquire(blocking=False)
    try:
        state.location_id = "the_anchor"
        _to_block_start(state, minutes_before=10)
        _present_until_the_block_turns(monkeypatch, state)
        before = len(state.social["threads"][tid].get("messages") or ())
        messaging.queue_due(state, pid, tid, Decision(situation="reply"), state.world_clock_hours + 0.02)
        clock.advance_time(state, 0.05)                     # due while present: held, re-pushed 15 minutes on
        held = [e for e in state.social["queue"] if e["pid"] == pid and e.get("held")]
        assert held and held[0]["at"] > state.world_clock_hours + 0.1
        clock.advance_time(state, 0.12)                     # over the boundary, before the re-push
        assert len(state.social["threads"][tid].get("messages") or ()) == before
    finally:
        release_turn(session)
    asked = []
    monkeypatch.setattr(voicer, "request_if_due", lambda s, **k: asked.append(s))
    _phone(scene, session, "put_down")
    assert len(state.social["threads"][tid].get("messages") or ()) == before + 1
    assert not [e for e in state.social["queue"] if e["pid"] == pid and e.get("held")]
    assert asked


def test_held_texts_land_when_their_block_moves_them_on_world_turn(receipts_active, monkeypatch) -> None:
    """The world turn's post-turn step (`_meet_if_here`, under the lock) lands them too."""
    from engine.game import clock
    from engine.scenes import default_scene
    from engine.session.store import release_turn
    from engine.social import messaging
    from engine.social.kinds import Decision

    _scene, session = _live_session()
    tid = _matched_in(session, "matchstick")
    pid = tid.split(":")[1]
    state = session.engine.state
    assert session.lock.acquire(blocking=False)
    try:
        state.location_id = "the_anchor"
        state.social["phone_up"] = False
        _to_block_start(state, minutes_before=10)
        _present_until_the_block_turns(monkeypatch, state)
        before = len(state.social["threads"][tid].get("messages") or ())
        messaging.queue_due(state, pid, tid, Decision(situation="reply"), state.world_clock_hours + 0.02)
        clock.advance_time(state, 0.05)
        clock.advance_time(state, 0.12)
        assert len(state.social["threads"][tid].get("messages") or ()) == before
        default_scene._meet_if_here(session, ({}, None))
        assert len(state.social["threads"][tid].get("messages") or ()) == before + 1
    finally:
        release_turn(session)


# -- the review (T23G fix round 1) ------------------------------------------------------------------------------


def test_after_a_run_in_they_are_still_here_only_not_approachable(receipts_state, matched, always_out,
                                                                    monkeypatch) -> None:
    """Review minor 1: the person has not left. After a chance scene ends `then: stay` they stay "Also here" and
    with the player (their texts still wait) for the rest of the block; only "Go over to" is not offered."""
    from engine.social import presence, scene, world

    _cfg(monkeypatch, prob={"out": 1.0})
    pid = _pid(matched)
    _at_the_anchor(receipts_state)
    _to_block_start(receipts_state)
    assert scene.move(receipts_state, f"approach:{pid}")["ok"]
    scene.end_scene(receipts_state, "player", then="stay")
    assert pid in presence.chance_here(receipts_state, "the_anchor")
    assert presence.with_player(receipts_state, pid)
    assert presence.with_player(receipts_state, pid, presence.here_view(receipts_state))
    assert f"Also here: {scene._name(receipts_state, pid)}" in world.narration_block(receipts_state)
    assert scene.approach_options(receipts_state) == []


def test_typing_a_present_persons_name_opens_nothing(receipts_state, matched, always_out, monkeypatch) -> None:
    """Review minor 2 (A4 section 3, A2): a typed line never approaches. Their name, or going over to them, is no
    approach."""
    from engine import social
    from engine.social import scene, typed

    _cfg(monkeypatch, prob={"out": 1.0})
    pid = _pid(matched)
    _at_the_anchor(receipts_state)
    name = scene._name(receipts_state, pid)
    assert f"approach:{pid}" in dict(scene.approach_options(receipts_state))
    for line in (name, f"go over to {name}", f"*walks over to {name}*", f"I go and say hi to {name}"):
        intent = typed.intent_for(receipts_state, line) or {}
        assert not str(intent.get("target") or "").startswith("approach"), (line, intent)
        assert intent.get("action") != "scene", (line, intent)
    assert not social.scene_open(receipts_state)


def test_a_typed_name_through_the_route_opens_no_scene(receipts_active, monkeypatch) -> None:
    from engine import social
    from engine.social import behaviour, places, scene
    from tests.social_world_stub import StubNarrator

    _cfg(monkeypatch, prob={"out": 1.0})
    monkeypatch.setattr(behaviour, "status_at", lambda person, at: "out")
    monkeypatch.setattr(places, "fitting_venues", lambda state, pid, kind="": ["the_anchor"])
    app_scene, session = _live_session(llm_fn=StubNarrator())
    pid = _matched_in(session, "matchstick").split(":")[1]
    _phone(app_scene, session, "put_down")
    state = session.engine.state
    state.location_id = "the_anchor"
    resp = app_scene.app.test_client().post("/api/game/choice", json={
        "session_id": session.session_id, "choice_id": "custom",
        "custom_text": f"go over to {scene._name(state, pid)}"})
    assert resp.status_code == 200, resp.get_data(as_text=True)
    assert not social.scene_open(state)


def test_the_run_in_reads_in_lower_case_mid_sentence(receipts_state, matched) -> None:
    """Review minor 3: "You are with Sam, in person: you ran into each other at The Anchor." No capital mid-line."""
    from engine.social import scene

    pid = _pid(matched)
    _at_the_anchor(receipts_state)
    scene.open_scene(receipts_state, pid, "the_anchor", kind="chance")
    line = scene.narration_line(receipts_state)
    assert "in person: you ran into each other at The Anchor." in line and "Ran into" not in line
    block = scene.companion_block(receipts_state, tokens=1200)
    assert "Where you are: you ran into each other at The Anchor." in block


def test_chance_tier_computed_once_per_world_turn(receipts_active, monkeypatch) -> None:
    """Review Important 1 (A4 W9, I7): at a venue, one whole world turn that moves no time (a typed line that
    names nothing) computes the chance tier ONCE, though the narration block, every `legal_intents` and the
    payload's `world.here` all read it."""
    from engine.social import behaviour, places, presence
    from tests.social_world_stub import StubNarrator

    _cfg(monkeypatch, prob={"out": 1.0})
    monkeypatch.setattr(behaviour, "status_at", lambda person, at: "out")
    monkeypatch.setattr(places, "fitting_venues", lambda state, pid, kind="": ["the_anchor"])
    app_scene, session = _live_session(llm_fn=StubNarrator())
    _matched_in(session, "matchstick")
    _phone(app_scene, session, "put_down")
    session.engine.state.location_id = "the_anchor"
    calls = []
    real = presence.candidates
    monkeypatch.setattr(presence, "candidates", lambda *a, **k: calls.append(1) or real(*a, **k))
    before = session.engine.state.world_clock_hours
    resp = app_scene.app.test_client().post("/api/game/choice", json={
        "session_id": session.session_id, "choice_id": "custom", "custom_text": "the light is nice today"})
    assert resp.status_code == 200, resp.get_data(as_text=True)
    assert session.engine.state.world_clock_hours == before
    here = (((resp.get_json().get("state") or {}).get("phone") or {}).get("world") or {}).get("here")
    assert here is None or any(r["kind"] == "contact" for r in here)
    assert len(calls) == 1, len(calls)


def test_a_pass_never_outlives_its_scope(receipts_state, matched, always_out, monkeypatch) -> None:
    """The memo is per pass (a ContextVar scope): outside one, every read computes afresh, and an effect inside one
    drops what it held."""
    from engine.game.effects import apply_effect
    from engine.social import presence

    _cfg(monkeypatch, prob={"out": 1.0})
    _pid(matched)
    _at_the_anchor(receipts_state)
    calls = []
    real = presence.candidates
    monkeypatch.setattr(presence, "candidates", lambda *a, **k: calls.append(1) or real(*a, **k))
    presence.chance_here(receipts_state, "the_anchor")
    presence.chance_here(receipts_state, "the_anchor")
    assert len(calls) == 2
    with presence.one_pass():
        presence.chance_here(receipts_state, "the_anchor")
        presence.here_view(receipts_state)
        assert len(calls) == 3
        apply_effect(receipts_state, {"type": "social_settings", "field": "phone_up", "value": False})
        presence.chance_here(receipts_state, "the_anchor")
        assert len(calls) == 4
    presence.chance_here(receipts_state, "the_anchor")
    assert len(calls) == 5
