"""
The Law, part five: patrols, arrest and custody.

THE SHAPE. Once a turn -- after the chosen intent has run, before a word is
narrated -- ``engine/scenes/default_state.py::run_turn`` asks ``law.patrol``
whether a watchman standing here knows the face the player is wearing.
``law.recognition`` rolls, per law-role person present and awake, the
file's ``recognise[band]`` times the best precision the watch holds on that
face in this jurisdiction; the first hit opens the story's ``arrest.encounter``
through ``encounter.begin``. An outcome of that scene carrying ``{type:
arrest}`` moves the player to the gaol, takes every HOT unit they carry and
sets ``custody``. From there ``pay_fine`` (only with the coin) or ``serve``
(days x 24 through ``advance_time``) ends it. Rest is offered in the cells;
travel is not.

WHAT THESE TESTS HOLD. ``unknown`` and ``noticed`` are never recognised and
never roll; ``hunted`` at full precision is recognised at about the file's
rate (measured over 200 seeds); a hit opens the encounter and names the
watchman, never an id; a missing encounter warns once and rolls nothing; the
arrest outcome confiscates exactly the hot units of a mixed stack and prices
the sentence from the counted-once severity; the fine needs the gold; the
sentence takes exactly its hours through the clock's one writer; nothing
rolls while a scene is open or while held; and a story with no Law never
reaches the patrol at all.

Version: v0.1.0 [2026-09-24]
"""

from __future__ import annotations

import copy
import json
import logging
import re
from pathlib import Path
from typing import Any, Iterator

import pytest
import yaml

from engine.config import set_overlay
from engine.game import encounter, intents
from engine.game.effects import apply_effect
from engine.game.procgen import generate_world
from engine.game.rng import LAW
from engine.game.state import GameState
from engine.world import law, thievery

from test_law import SPEC as _BASE_SPEC

#: The shared synthetic file plus the arrest scene this file authors below:
#: `arrest.encounter` is checked against the encounters at load.
LAW_SPEC = copy.deepcopy(_BASE_SPEC)
LAW_SPEC["arrest"]["encounter"] = "watch_stop"

SQUARE = "edgewood_square"
GAOL = LAW_SPEC["arrest"]["gaol"]
ALL_DAY = [{"hours": list(range(24)), "location": SQUARE, "activity": "idling"}]
ASLEEP = [{"hours": list(range(24)), "location": SQUARE, "activity": "dozing", "available": False}]

THIEVERY_SPEC = {
    "alertness": {"default": "standard"},
    "purses": {"default": [{"gold": [2, 4], "weight": 1}]},
    "hot_days": 5,
}
ENCOUNTERS = {
    "encounters": [{
        "id": "watch_stop",
        "intro": "A lantern swings up into your face.",
        "threat": {"name": "the watch", "resolve": 2},
        "approaches": {
            "run": {
                "auto": True,
                "degree": "success",
                "text": "Bolt for the alleys",
                "outcomes": {"success": {"text": "You lose them.", "ends": True}},
            },
            "surrender": {
                "auto": True,
                "degree": "success",
                "text": "Hold out your wrists",
                "outcomes": {"success": {
                    "text": "They walk you to the cells.",
                    "effects": [{"type": "arrest"}],
                }},
            },
        },
    }],
}


def _dump(path: Path, doc: Any) -> str:
    path.write_text(yaml.safe_dump(doc), encoding="utf-8")
    return str(path)


def _paths(tmp_path: Path, law_doc: dict[str, Any] | None = None) -> dict[str, str]:
    enc_dir = tmp_path / "encounters"
    enc_dir.mkdir(exist_ok=True)
    _dump(enc_dir / "watch.yaml", ENCOUNTERS)
    return {
        "law": _dump(tmp_path / "law.yaml", law_doc or LAW_SPEC),
        "thievery": _dump(tmp_path / "thievery.yaml", THIEVERY_SPEC),
        "encounters": str(enc_dir),
        "npc_schedules": _dump(tmp_path / "npc_schedules.yaml", {"npcs": {}}),
    }


@pytest.fixture()
def lawful(tmp_path: Path) -> Iterator[Path]:
    set_overlay({"paths": _paths(tmp_path)})
    try:
        yield tmp_path
    finally:
        set_overlay(None)


def _person(npc_id: str, role: str, routine: list[dict[str, Any]]) -> dict[str, Any]:
    return {"id": npc_id, "name": npc_id.replace("_", " ").title(), "role": role, "routine": routine}


def _world(people: list[dict[str, Any]], *, seed: int = 42) -> GameState:
    state = GameState(rng_seed=seed, location_id=SQUARE)
    state.procgen = generate_world(seed)
    state.procgen.npcs = people
    return state


def _file(state: GameState, deed: str, times: int = 1, *, guise: str = "self",
          where: str = "village", precision: float = 1.0) -> None:
    """File ``times`` separate deeds of one kind with the watch, through the effect."""
    for _ in range(times):
        out = apply_effect(state, {"type": "report", "deed": deed, "guise": guise,
                                   "jurisdiction": where, "precision": precision})
        assert out["ok"], out


def _hunted(state: GameState) -> None:
    _file(state, "assault_watch", 3)  # 3 x 5 x 1.0 = 15 -> hunted
    assert law.wanted_band(state, "self", "village") == "hunted"


WATCH = [_person("gen_a_watch", "watch", ALL_DAY)]


# -- recognition ---------------------------------------------------------------


def test_unknown_and_noticed_are_never_recognised_and_never_roll(lawful: Path) -> None:
    state = _world(copy.deepcopy(WATCH))
    assert law.wanted_band(state, "self", "village") == "unknown"
    for _ in range(50):
        assert law.recognition(state)["recognised"] is False
    _file(state, "fencing", 1)  # 2 -> noticed
    assert law.wanted_band(state, "self", "village") == "noticed"
    for _ in range(50):
        assert law.recognition(state)["recognised"] is False
    # Not merely unlucky: a band the file does not list in `recognise` never
    # touches the stream, so a clean face cannot shift any later roll.
    assert LAW not in state.rng_counters


def test_hunted_at_full_precision_is_recognised_at_about_the_files_rate(lawful: Path) -> None:
    # MEASURED, over 200 seeded turns: one watchman, hunted, precision 1.0.
    # The file says 0.8; the rate must sit near it, not merely be "often".
    hits = 0
    for seed in range(200):
        state = _world(copy.deepcopy(WATCH), seed=seed)
        _hunted(state)
        hits += bool(law.recognition(state)["recognised"])
    rate = hits / 200
    assert 0.7 <= rate <= 0.9, rate


def test_precision_scales_the_chance(lawful: Path) -> None:
    # The same file seen only half-clearly: every report at hop-2 precision.
    # 3 x 5 x 0.6 = 9 -> wanted (0.5), times 0.6 = 0.3 per watchman.
    hits = 0
    for seed in range(200):
        state = _world(copy.deepcopy(WATCH), seed=seed)
        _file(state, "assault_watch", 3, precision=0.6)
        assert law.wanted_band(state, "self", "village") == "wanted"
        hits += bool(law.recognition(state)["recognised"])
    assert 0.2 <= hits / 200 <= 0.4, hits / 200


def test_only_the_law_looks_and_only_awake(lawful: Path) -> None:
    state = _world([_person("gen_a_lab", "labourer", ALL_DAY), _person("gen_a_w", "watch", ASLEEP)])
    _hunted(state)
    for _ in range(20):
        assert law.recognition(state)["recognised"] is False
    assert LAW not in state.rng_counters


def test_a_linked_face_is_known_and_an_unlinked_one_is_not(lawful: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from test_law_guises import _carry

    state = _world(copy.deepcopy(WATCH))
    _hunted(state)
    # The porter was never linked to you: a hunted face under a porter's smock
    # is a stranger to the watch.
    _carry(state, "candle")
    state.law["guise"] = "porter"
    assert law.recognition(state)["recognised"] is False
    assert LAW not in state.rng_counters
    # The Magpie IS linked (the file's starting belief): your file is its file.
    _carry(state, "golden_ring")
    state.law["guise"] = "magpie"
    hits = sum(bool(law.recognition(state)["recognised"]) for _ in range(40))
    assert hits > 0


# -- a hit opens the scene -------------------------------------------------------


def _always(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Sure:
        def random(self) -> float:
            return 0.0

    monkeypatch.setattr("engine.game.rng.world_rng", lambda state, stream: _Sure())


def test_a_hit_opens_the_arrest_encounter_and_names_the_watchman(
    lawful: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = _world(copy.deepcopy(WATCH))
    _hunted(state)
    _always(monkeypatch)
    receipt = law.patrol(state)
    assert receipt is not None
    assert encounter.active(state) and state.encounter["id"] == "watch_stop"
    from engine.agents.prompts import summarise_receipt

    line = summarise_receipt(receipt)
    assert "Gen A Watch" in line and "your own face" in line
    assert "gen_a_watch" not in line and "watch_stop" not in line
    assert not re.search(r"\d", line), line


def test_no_roll_while_a_scene_is_open(lawful: Path) -> None:
    state = _world(copy.deepcopy(WATCH))
    _hunted(state)
    encounter.begin(state, "watch_stop")
    for _ in range(20):
        assert law.patrol(state) is None
    assert LAW not in state.rng_counters


def test_no_roll_while_held(lawful: Path) -> None:
    state = _world(copy.deepcopy(WATCH))
    _hunted(state)
    apply_effect(state, {"type": "arrest"})
    state.location_id = SQUARE  # the watchman's street, to be sure it is custody that stops it
    for _ in range(20):
        assert law.patrol(state) is None
    assert LAW not in state.rng_counters


def test_a_missing_encounter_warns_once_and_rolls_nothing(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    # A misnamed scene fails at LOAD now (see
    # test_a_misnamed_arrest_encounter_fails_at_load); this is the runtime
    # guard behind it -- the scene vanishing after the law file loaded (a
    # content edit under a running game).
    set_overlay({"paths": _paths(tmp_path)})
    try:
        law.load_spec()
        (tmp_path / "encounters" / "watch.yaml").unlink()
        state = _world(copy.deepcopy(WATCH))
        _hunted(state)
        with caplog.at_level(logging.WARNING, logger="engine.world.law"):
            for _ in range(5):
                assert law.patrol(state) is None
        warnings = [r for r in caplog.records if "watch_stop" in r.getMessage()]
        assert len(warnings) == 1
        assert not encounter.active(state)
        assert LAW not in state.rng_counters
    finally:
        set_overlay(None)


# -- arrest ----------------------------------------------------------------------


def _stolen(state: GameState, item_id: str, *, days_ago: int = 0) -> None:
    apply_effect(state, {"type": "item", "item_id": item_id, "qty": 1,
                         "stolen_from": {"whom": "gen_mark", "where": SQUARE}})
    if days_ago:
        state.provenance[item_id][-1]["day"] = state.world_day - days_ago


def test_the_encounters_arrest_outcome_moves_confiscates_and_holds(lawful: Path) -> None:
    state = _world(copy.deepcopy(WATCH))
    _hunted(state)
    # The same deed again, half-seen, and a crime under an unlinked face: the
    # first counts once, the second is not the watch's charge against YOU.
    first = state.law["reports"][0]
    apply_effect(state, {"type": "report", "deed": "assault_watch", "guise": "self",
                         "jurisdiction": "village", "precision": 0.6, "deed_id": first["deed_id"]})
    _file(state, "fencing", 1, guise="porter")
    _file(state, "fencing", 1, where="town")  # another district's file

    # A mixed stack: one ring stolen long ago (cool), one this morning (hot).
    _stolen(state, "golden_ring", days_ago=10)
    _stolen(state, "golden_ring")
    apply_effect(state, {"type": "item", "item_id": "candle", "qty": 2})  # honest
    assert thievery.heat_split(state, "golden_ring") == {"clean": 0, "cool": 1, "hot": 1}

    encounter.begin(state, "watch_stop")
    out = encounter.resolve_approach(state, "surrender")
    assert out["ok"] and out["resolved"]
    assert not encounter.active(state)

    assert state.location_id == GAOL
    ring = next(i for i in state.inventory if i.id == "golden_ring")
    assert ring.qty == 1
    # The ring left behind is the COOL one: its record, not the fresh one's.
    assert thievery.heat_split(state, "golden_ring") == {"clean": 0, "cool": 1, "hot": 0}
    assert next(i for i in state.inventory if i.id == "candle").qty == 2

    held = state.law["custody"]
    # Three assaults counted once each: 15 severity. x6 coin, x1 day.
    assert held["fine"] == 15 * 6 and held["days"] == 15
    assert held["since_day"] == state.world_day


def test_days_are_at_least_one_when_anything_is_charged(tmp_path: Path) -> None:
    doc = copy.deepcopy(LAW_SPEC)
    doc["arrest"]["days_per_severity"] = 0
    set_overlay({"paths": _paths(tmp_path, doc)})
    try:
        state = _world([])
        _file(state, "pickpocket", 1)
        apply_effect(state, {"type": "arrest"})
        assert state.law["custody"]["days"] == 1
    finally:
        set_overlay(None)


def test_an_arrest_while_held_is_refused(lawful: Path) -> None:
    state = _world([])
    assert apply_effect(state, {"type": "arrest"})["ok"] is True
    again = apply_effect(state, {"type": "arrest"})
    assert again["ok"] is False and again["message"]


def test_arrest_and_release_are_inert_without_a_law() -> None:
    state = GameState(location_id=SQUARE)
    assert apply_effect(state, {"type": "arrest"})["ok"] is False
    assert apply_effect(state, {"type": "release"})["ok"] is False
    assert state.location_id == SQUARE and state.law == {}


# -- custody: the verbs ----------------------------------------------------------


def _held(state: GameState, deed: str = "fencing") -> dict[str, Any]:
    _file(state, deed, 1)
    assert apply_effect(state, {"type": "arrest"})["ok"]
    return dict(state.law["custody"])


def _verbs(state: GameState) -> dict[str, intents.IntentVerb]:
    return {v.action: v for v in intents.legal_intents(state)}


def test_in_custody_rest_is_offered_and_travel_is_not(lawful: Path) -> None:
    state = _world([])
    state.location_id = GAOL
    assert "travel" in _verbs(state)  # the barracks has roads out
    _held(state)
    verbs = _verbs(state)
    assert "travel" not in verbs
    assert "rest" in verbs and "serve" in verbs


def test_rest_works_in_the_gaol(lawful: Path) -> None:
    from engine.agents.tool_dispatcher import execute_intent
    from engine.game.engine import GameEngine

    state = _world([])
    _held(state)
    state.stats.stamina = 10
    engine = GameEngine(state)
    kind = _verbs(state)["rest"].targets[0]
    (receipt,) = execute_intent({"action": "rest", "target": kind}, engine)
    assert receipt["success"] and not receipt.get("refused")
    assert state.stats.stamina > 10
    assert state.location_id == GAOL and law.in_custody(state)


def test_travel_is_refused_by_the_engine_while_held(lawful: Path) -> None:
    from engine.game.engine import GameEngine

    state = _world([])
    _held(state)
    result = GameEngine(state).move_to("millhaven_gate")
    assert result.success is False and result.message
    assert state.location_id == GAOL


def test_pay_fine_needs_the_gold_and_releases(lawful: Path) -> None:
    from engine.agents.tool_dispatcher import execute_intent
    from engine.game.engine import GameEngine

    state = _world([])
    held = _held(state)  # fencing: 2 severity -> 12 coin
    assert held["fine"] == 12
    state.stats.gold = 11
    assert "pay_fine" not in _verbs(state)
    engine = GameEngine(state)
    (refused,) = execute_intent({"action": "pay_fine"}, engine)
    assert refused["refused"] and law.in_custody(state) and state.stats.gold == 11

    # The skill itself refuses too, whatever called it.
    out = law.pay_fine(state)
    assert out["ok"] is False and out["message"]

    state.stats.gold = 20
    assert "pay_fine" in _verbs(state)
    (paid,) = execute_intent({"action": "pay_fine"}, engine)
    assert paid["success"] and not paid.get("refused")
    assert state.stats.gold == 8
    assert not law.in_custody(state)
    # The debt is discharged: the file that put you here is closed, so the
    # watchman at the door does not arrest you again on the way out.
    assert law.wanted_band(state, "self", "village") == "unknown"
    assert "pay_fine" not in _verbs(state) and "serve" not in _verbs(state)
    assert "travel" in _verbs(state)


def test_serve_takes_exactly_its_days_through_the_clock(
    lawful: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from engine.game import clock

    state = _world([])
    held = _held(state)  # 2 days
    calls: list[float] = []
    real = clock.advance_time

    def spy(s: GameState, hours: float) -> Any:
        calls.append(hours)
        return real(s, hours)

    monkeypatch.setattr(clock, "advance_time", spy)
    before = state.world_clock_hours
    out = law.serve_sentence(state)
    assert out["ok"] is True
    # Day by day, with rations between (fix round 1): the hours add up to
    # exactly the sentence, every one of them through the clock's one writer.
    assert calls == [24.0] * held["days"]
    assert state.world_clock_hours == before + held["days"] * 24
    assert not law.in_custody(state)


def test_serve_and_pay_refuse_when_not_held(lawful: Path) -> None:
    state = _world([])
    assert law.serve_sentence(state)["ok"] is False
    assert law.pay_fine(state)["ok"] is False
    assert "serve" not in _verbs(state)


def test_release_clears_custody_and_nothing_else(lawful: Path) -> None:
    state = _world([])
    _held(state)
    reports = copy.deepcopy(state.law["reports"])
    out = apply_effect(state, {"type": "release"})
    assert out["ok"] is True
    assert not law.in_custody(state)
    # A break-out is a release too, and must not launder the file.
    assert state.law["reports"] == reports


def test_verb_mapping() -> None:
    assert intents.SKILL_FOR_ACTION["pay_fine"] == "pay_fine"
    assert intents.SKILL_FOR_ACTION["serve"] == "serve_sentence"
    assert intents.REFUSAL_KEY_FOR_ACTION["pay_fine"] == "ok"
    assert intents.REFUSAL_KEY_FOR_ACTION["serve"] == "ok"
    assert intents.to_tool_call(GameState(), {"action": "pay_fine"}) == ("pay_fine", {})
    assert intents.to_tool_call(GameState(), {"action": "serve"}) == ("serve_sentence", {})


def test_summaries_carry_no_ids_and_no_numbers_but_money(lawful: Path) -> None:
    from engine.agents.prompts import summarise_receipt

    state = _world([])
    _held(state)
    state.stats.gold = 50
    paid = summarise_receipt({"skill": "pay_fine", "result": law.pay_fine(state)})
    assert "12" in paid  # the coin, as the story's currency
    assert not re.search(r"\d", paid.replace("12", "")), paid
    state.location_id = SQUARE  # back on the watch's street to be charged again
    _held(state, "assault_watch")
    served = summarise_receipt({"skill": "serve_sentence", "result": law.serve_sentence(state)})
    assert "days" in served and not re.search(r"\d", served), served
    for line in (paid, served):
        assert GAOL not in line and "village" not in line


# -- the turn --------------------------------------------------------------------


@pytest.fixture()
def _isolated_saves(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    from engine.persistence import reset_save_store
    from engine.persistence.saves import SaveStore

    reset_save_store()
    store = SaveStore(root=tmp_path / "saves")
    monkeypatch.setattr("engine.scenes.default_state.get_save_store", lambda: store)
    yield
    reset_save_store()


def _session_turn(session: Any, seen: list[str]) -> dict[str, Any]:
    from content.scenes.clockwork.clockwork_state import run_turn
    from test_turn_intent import canned_reply

    reply = canned_reply(session.engine.state)

    def fake(messages: list[dict[str, Any]]) -> str:
        seen.append("\n".join(str(m.get("content", "")) for m in messages))
        return reply

    session.storyteller.llm_fn = fake
    session.assistant.llm_fn = fake
    return run_turn(session, "The player chooses: Stand a while and look")


def test_a_turn_under_a_watchmans_eye_opens_the_stop_before_narration(
    tmp_path: Path, _isolated_saves: None
) -> None:
    from content.scenes.clockwork.clockwork_state import SessionStore

    doc = copy.deepcopy(LAW_SPEC)
    doc["recognise"]["hunted"] = 1.0  # certain, so the turn is not a coin toss
    set_overlay({"paths": _paths(tmp_path, doc)})
    try:
        session = SessionStore().create(seed=42, llm_fn=None)
        state = session.engine.state
        state.location_id = SQUARE
        state.procgen.npcs = copy.deepcopy(WATCH)
        _hunted(state)
        seen: list[str] = []
        _session_turn(session, seen)
        assert encounter.active(state) and state.encounter["id"] == "watch_stop"
        prompt = seen[0]
        assert "MECHANICAL RESULTS" in prompt and "Gen A Watch" in prompt
        assert "watch_stop" not in prompt.split("MECHANICAL RESULTS", 1)[1].split("\n\n", 1)[0]
    finally:
        set_overlay(None)


def test_the_flagship_turn_never_reaches_the_patrol(
    monkeypatch: pytest.MonkeyPatch, _isolated_saves: None
) -> None:
    from content.scenes.clockwork.clockwork_state import SessionStore

    def boom(state: GameState) -> Any:
        raise AssertionError("the patrol ran in a story with no Law")

    monkeypatch.setattr(law, "patrol", boom)
    monkeypatch.setattr(law, "recognition", boom)
    session = SessionStore().create(seed=42, llm_fn=None)
    assert not law.declared()
    seen: list[str] = []
    payload = _session_turn(session, seen)
    assert payload
    assert session.engine.state.law == {}
    assert "pay_fine" not in json.dumps(payload) and "custody" not in json.dumps(payload)


# ---------------------------------------------------------------------------
# Fix round 1: rations, scene gates, no re-fire, lasting discharge
# ---------------------------------------------------------------------------


def test_a_long_sentence_ends_alive_and_unstarved(lawful: Path) -> None:
    # 3 assaults: 15 days. One advance of 360 hours starved the prisoner to
    # death in the cells (measured: hp 20 -> -28, then a respawn). Rations
    # each day keep the hunger clock from ever reaching starving.
    state = _world([])
    state.location_id = SQUARE
    _file(state, "assault_watch", 3)
    apply_effect(state, {"type": "arrest"})
    assert state.law["custody"]["days"] == 15
    hp = state.stats.hp
    out = law.serve_sentence(state)
    assert out["ok"] is True
    assert state.stats.hp == hp
    from engine.game import survival

    assert survival.hunger_stage(state) != "starving"
    assert state.location_id == GAOL  # served, not carried out dead


def test_death_while_held_clears_custody(lawful: Path) -> None:
    from engine.game.clock import advance_time

    state = _world([])
    _held(state)
    assert "travel" not in _verbs(state)
    state.stats.hp = 0
    advance_time(state, 1.0)  # the clock's death check carries the body out
    assert state.location_id != GAOL or not law.in_custody(state)
    assert not law.in_custody(state)
    assert "travel" in _verbs(state)


def test_an_open_card_or_set_piece_blocks_recognition(lawful: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state = _world(copy.deepcopy(WATCH))
    _hunted(state)
    _always(monkeypatch)
    monkeypatch.setattr(intents, "_card_open", lambda s: True)
    assert law.recognition(state)["recognised"] is False
    assert law.patrol(state) is None
    monkeypatch.setattr(intents, "_card_open", lambda s: False)
    monkeypatch.setattr(intents, "_challenge_open", lambda s: True)
    assert law.patrol(state) is None
    assert not encounter.active(state)
    monkeypatch.setattr(intents, "_challenge_open", lambda s: False)
    assert law.patrol(state) is not None


def test_escaping_a_stop_does_not_re_fire_it_the_same_turn(
    tmp_path: Path, _isolated_saves: None
) -> None:
    from content.scenes.clockwork.clockwork_state import SessionStore, run_turn
    from test_turn_intent import canned_reply

    doc = copy.deepcopy(LAW_SPEC)
    doc["recognise"]["hunted"] = 1.0
    set_overlay({"paths": _paths(tmp_path, doc)})
    try:
        session = SessionStore().create(seed=42, llm_fn=None)
        state = session.engine.state
        state.location_id = SQUARE
        state.procgen.npcs = copy.deepcopy(WATCH)
        _hunted(state)
        encounter.begin(state, "watch_stop")
        reply = canned_reply(state)
        session.storyteller.llm_fn = lambda messages: reply
        session.assistant.llm_fn = session.storyteller.llm_fn
        run_turn(session, "The player chooses: Bolt", intent={"action": "encounter", "target": "run"})
        assert not encounter.active(state), "the same watchman stopped the player again at once"
        assert state.location_id == SQUARE
        # A later turn under the same eye can.
        _session_turn(session, [])
        assert encounter.active(state)
    finally:
        set_overlay(None)


def test_serving_discharges_only_what_was_charged(lawful: Path) -> None:
    state = _world([])
    _held(state)
    # Committed from the cell: never charged, so serving must not wipe it.
    _file(state, "pickpocket", 1)
    fresh = state.law["reports"][-1]["deed_id"]
    law.serve_sentence(state)
    assert [r["deed_id"] for r in state.law["reports"]] == [fresh]


def test_a_served_deed_never_becomes_a_report_again(tmp_path: Path) -> None:
    doc = copy.deepcopy(LAW_SPEC)
    doc["spread_per_hour"] = 1.0
    set_overlay({"paths": _paths(tmp_path, doc)})
    try:
        from engine.game.clock import advance_time

        state = _world([_person("gen_a_watch", "watch", ALL_DAY), _person("gen_a_lab", "labourer", ALL_DAY)])
        law.commit_deed(state, "fencing", certain=("gen_a_watch", "gen_a_lab"))
        deed = state.law["reports"][0]["deed_id"]
        apply_effect(state, {"type": "arrest"})
        assert law.pay_fine(state)["ok"] is False  # no coin; serve instead
        law.serve_sentence(state)
        # A new watchman joins the labourer who saw it; rumour spreads surely.
        state.procgen.npcs = [_person("gen_a_lab", "labourer", ALL_DAY),
                              _person("gen_b_watch", "watch", ALL_DAY)]
        advance_time(state, 12.0)
        assert all(r.get("deed_id") != deed for r in state.law.get("reports") or [])
        # And the effect itself refuses to file it.
        again = apply_effect(state, {"type": "report", "deed": "fencing", "guise": "self",
                                     "jurisdiction": "village", "precision": 1.0, "deed_id": deed})
        assert again["ok"] is False
    finally:
        set_overlay(None)


def test_the_arrest_receipt_carries_no_raw_counts(lawful: Path) -> None:
    state = _world([])
    _stolen(state, "golden_ring")
    _stolen(state, "golden_ring")
    out = apply_effect(state, {"type": "arrest"})
    assert not re.search(r"\d", out["text"]), out["text"]


def test_the_recognition_line_does_not_assume_a_watch(lawful: Path) -> None:
    from engine.agents.prompts import summarise_receipt

    line = summarise_receipt({"skill": "law_recognition",
                              "result": {"name": "Sergeant Pell", "label": "the Magpie's mask"}})
    assert "watch" not in line.lower()
    assert "Sergeant Pell" in line and "the Magpie's mask" in line


def test_custody_survives_a_save(lawful: Path) -> None:
    state = _world([])
    held = _held(state)
    loaded = GameState.from_dict(json.loads(json.dumps(state.to_save_dict())))
    assert loaded.law["custody"] == held
    assert law.in_custody(loaded)
    assert "travel" not in _verbs(loaded) and "serve" in _verbs(loaded)


# -- Task 7: the arrest scene is checked at load; a fight is a deed ---------------


def test_a_misnamed_arrest_encounter_fails_at_load(tmp_path: Path) -> None:
    """Deferred from Task 1: a story that ships encounters but not the named one."""
    doc = copy.deepcopy(LAW_SPEC)
    doc["arrest"]["encounter"] = "watch_stpo"
    set_overlay({"paths": _paths(tmp_path, doc)})
    try:
        with pytest.raises(ValueError) as caught:
            law.load_spec()
    finally:
        set_overlay(None)
    assert str(tmp_path / "law.yaml") in str(caught.value)
    assert "watch_stpo" in str(caught.value)


def test_the_named_arrest_encounter_loads(lawful: Path) -> None:
    assert law.load_spec()["arrest"]["encounter"] == "watch_stop"


def test_a_deed_effect_commits_through_the_law_and_the_watch_sees_it_for_certain(
    lawful: Path,
) -> None:
    """How a scene's fight becomes `assault_watch`: every Lantern present is sure."""
    for seed in range(20):
        state = _world(copy.deepcopy(WATCH), seed=seed)
        out = apply_effect(state, {"type": "deed", "deed": "assault_watch", "seen_by_watch": True})
        assert out["ok"] is True and out["reported"] is True, seed
        assert law.wanted_band(state, "self", "village") == "sought"  # 5 x 1.0
        assert "gen_a_watch" not in out["text"]


def test_a_deed_effect_without_the_watch_flag_rolls_like_any_deed(lawful: Path) -> None:
    seen = 0
    for seed in range(40):
        state = _world(copy.deepcopy(WATCH), seed=seed)
        seen += bool(apply_effect(state, {"type": "deed", "deed": "assault_watch"})["reported"])
    assert 0 < seen < 40, seen  # notice 0.6 by day: sometimes, not always


def test_a_struck_watchman_nobody_scheduled_still_reports_it(lawful: Path) -> None:
    """
    v0.14: the drunk Lantern in a street scene is not a scheduled person, so
    `seen_by_watch` finds no law-role witness and the blow could go unfiled.
    `report_precision` is the victim telling the watch-house himself: one report
    of the deed, for the guise worn, where it happened, at that clarity.
    """
    for seed in range(10):
        state = _world([], seed=seed)  # nobody present to see it
        out = apply_effect(state, {"type": "deed", "deed": "assault_watch",
                                   "seen_by_watch": True, "report_precision": 0.6})
        assert out["ok"] is True and out["reported"] is True, seed
        reports = state.law.get("reports") or []
        assert len(reports) == 1, reports
        assert reports[0]["deed"] == "assault_watch"
        assert reports[0]["guise"] == "self"
        assert reports[0]["jurisdiction"] == "village"
        assert reports[0]["precision"] == 0.6
        assert law.wanted_band(state, "self", "village") == "noticed"  # 5 x 0.6 = 3


def test_a_struck_watchman_who_was_seen_is_not_reported_twice(lawful: Path) -> None:
    """A Lantern on duty already filed it: the victim's own report adds no second deed."""
    state = _world(copy.deepcopy(WATCH))
    apply_effect(state, {"type": "deed", "deed": "assault_watch",
                         "seen_by_watch": True, "report_precision": 0.6})
    ids = {r.get("deed_id") for r in state.law.get("reports") or []}
    assert len(ids) == 1, state.law.get("reports")
    assert law.wanted_band(state, "self", "village") == "sought"  # the clear report stands


@pytest.mark.parametrize("bad", [-0.1, 1.5, "clear"])
def test_a_bad_report_precision_is_refused(lawful: Path, bad: Any) -> None:
    state = _world([])
    out = apply_effect(state, {"type": "deed", "deed": "assault_watch", "report_precision": bad})
    assert out["ok"] is False and "report_precision" in out["message"]
    assert not state.law.get("reports")


def test_a_deed_effect_naming_an_unknown_deed_is_refused(lawful: Path) -> None:
    state = _world(copy.deepcopy(WATCH))
    out = apply_effect(state, {"type": "deed", "deed": "treason"})
    assert out["ok"] is False and "treason" in out["message"]
    assert not state.law


def test_a_deed_effect_is_inert_without_a_law() -> None:
    state = GameState(rng_seed=1, location_id=SQUARE)
    assert apply_effect(state, {"type": "deed", "deed": "assault_watch"})["ok"] is False
    assert state.law == {}


# -- Task 7 fix: sentence caps -----------------------------------------------------


def test_the_caps_bound_the_fine_and_the_days(tmp_path: Path) -> None:
    doc = copy.deepcopy(LAW_SPEC)
    doc["arrest"].update({"max_days": 3, "max_fine": 20})
    set_overlay({"paths": _paths(tmp_path, doc)})
    try:
        state = _world([])
        _file(state, "pickpocket", 10)  # S = 10: 60 crowns, 10 days uncapped
        assert law.sentence_for(state, "self", "village") == {"fine": 20, "days": 3}
        state = _world([])
        _file(state, "pickpocket", 2)  # under both caps: untouched
        assert law.sentence_for(state, "self", "village") == {"fine": 12, "days": 2}
    finally:
        set_overlay(None)


def test_no_caps_means_the_old_formula(lawful: Path) -> None:
    state = _world([])
    _file(state, "pickpocket", 10)
    assert law.sentence_for(state, "self", "village") == {"fine": 60, "days": 10}


@pytest.mark.parametrize("cap, value", [("max_days", 0), ("max_fine", -1), ("max_days", "soon")])
def test_a_bad_cap_fails_naming_the_file(tmp_path: Path, cap: str, value: Any) -> None:
    doc = copy.deepcopy(LAW_SPEC)
    doc["arrest"][cap] = value
    set_overlay({"paths": _paths(tmp_path, doc)})
    try:
        with pytest.raises(ValueError) as caught:
            law.load_spec()
    finally:
        set_overlay(None)
    assert str(tmp_path / "law.yaml") in str(caught.value) and cap in str(caught.value)
