"""
Secret places stay secret until found.

`secret: true` used to be a promise only the map kept. `codex_places` withheld
the place and every road to it, while `intents._travel` built its enum straight
from the graph -- so on turn one of HUE & CRY the model was handed "The
Undercroft, 1h" as a legal, labelled travel option, and THE LONG CON offered
the drying room from the first time the player stood on Harbour Road, three
stages before the case sends them there.

One predicate now decides whether a place is known
(`engine.game.locations.is_known`): not secret, OR stood in, OR visited, OR
revealed by the `location_known:<id>` flag, OR the end of a discovered hidden
path. `_travel`, the map payload and the resume choices all ask it, so none of
them can drift from the others again.
"""

from __future__ import annotations

import pytest

from engine.game.state import GameState
from engine.games import registry

HUE_SECRETS = ("the_undercroft", "rooftop_road", "old_bell_tower")


def _travel_targets(state: GameState) -> set[str]:
    from engine.game.intents import _travel

    verb = _travel(state)
    return set(verb.targets) if verb else set()


def _map(state: GameState) -> dict[str, dict]:
    from engine.scenes.default_api import codex_places

    return {p["id"]: p for p in codex_places(state)}


def _map_roads_from_here(state: GameState) -> set[str]:
    here = _map(state).get(state.location_id)
    assert here is not None, "the place the player stands in is missing from the map"
    return {road["to"] for road in here["roads"]}


def _reveal(state: GameState, loc_id: str) -> None:
    from engine.game.effects import apply_effect
    from engine.game.locations import KNOWN_FLAG_PREFIX

    receipt = apply_effect(state, {"type": "flag", "flag": f"{KNOWN_FLAG_PREFIX}{loc_id}"})
    assert receipt.get("ok"), receipt


def _assert_map_agrees_with_travel(state: GameState) -> None:
    """The map and the enum ask the same question, so they give one answer."""
    assert _travel_targets(state) == _map_roads_from_here(state), state.location_id


@pytest.fixture()
def hue():
    registry.activate("hue-and-cry")
    state = GameState(session_id="secrets")
    state.location_id = "tallow_docks"
    yield state


# -- HUE & CRY -----------------------------------------------------------------


def test_the_green_control_turn_one_offers_real_roads(hue: GameState) -> None:
    """Without this, every absence below would pass against an empty enum."""
    assert {"wickmarket", "the_snuffs", "lantern_house"} <= _travel_targets(hue)


def test_turn_one_offers_no_secret_place_from_anywhere(hue: GameState) -> None:
    from engine.game.locations import LOCATIONS

    public = [loc for loc, row in LOCATIONS.items() if not row.get("secret")]
    assert len(public) >= 8
    for loc in public:
        hue.location_id = loc
        offered = _travel_targets(hue)
        assert not offered & set(HUE_SECRETS), (loc, offered & set(HUE_SECRETS))
        assert not set(_map(hue)) & set(HUE_SECRETS), loc
        _assert_map_agrees_with_travel(hue)


def test_a_revealed_place_is_offered_and_drawn(hue: GameState) -> None:
    _reveal(hue, "the_undercroft")

    assert "the_undercroft" in _travel_targets(hue)
    places = _map(hue)
    assert "the_undercroft" in places
    # Known to exist is not the same as having been there: drawn, greyed.
    assert places["the_undercroft"]["discovered"] is False
    assert places["the_undercroft"]["image"] == ""
    # Revealing one secret reveals exactly one.
    assert "rooftop_road" not in places and "old_bell_tower" not in places
    _assert_map_agrees_with_travel(hue)


def test_a_visited_place_stays_known_without_the_flag(hue: GameState) -> None:
    from engine.game.quests import QuestEngine

    hue.location_id = "the_undercroft"
    QuestEngine.observe(hue)  # the visited ledger, as every turn writes it
    hue.location_id = "tallow_docks"

    assert not any(k.startswith("location_known:") for k in hue.flags)
    assert "the_undercroft" in _travel_targets(hue)
    assert _map(hue)["the_undercroft"]["discovered"] is True
    _assert_map_agrees_with_travel(hue)


def test_the_place_you_stand_in_is_known(hue: GameState) -> None:
    """
    Arriving by some other door (a card, a relocation) is finding it. From the
    Rooftop Road the Old Bell Tower is still a secret; the road you are on is not.
    """
    hue.location_id = "rooftop_road"

    offered = _travel_targets(hue)
    assert {"wickmarket", "the_snuffs", "silk_row"} <= offered
    assert "old_bell_tower" not in offered
    places = _map(hue)
    assert places["rooftop_road"]["here"] is True
    assert "old_bell_tower" not in places
    _assert_map_agrees_with_travel(hue)


def test_resume_choices_do_not_name_a_secret_road(
    hue: GameState, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    The resume screen offers the first two roads out, in authored order. The
    shipped files happen to list every secret road last; an author who lists
    the Undercroft first must not have a reload spoil the city.
    """
    from engine.game import locations as locations_module
    from engine.memory.ledger import StoryLedger
    from engine.scenes.default_state import resume_opening

    graph = dict(locations_module.LOCATIONS)
    docks = dict(graph["tallow_docks"])
    roads = dict(docks["connections"])
    docks["connections"] = {"the_undercroft": roads.pop("the_undercroft"), **roads}
    graph["tallow_docks"] = docks
    monkeypatch.setattr(locations_module, "LOCATIONS", graph)

    payload = resume_opening(hue, StoryLedger())
    targets = {
        (c.get("intent") or {}).get("target")
        for c in payload["choices"]
        if (c.get("intent") or {}).get("action") == "travel"
    }
    assert targets, "no roads offered at all; the test proves nothing"
    assert not targets & set(HUE_SECRETS), targets


# -- the predicate ---------------------------------------------------------------


def test_is_known_is_the_one_rule(hue: GameState) -> None:
    from engine.game.locations import is_known

    assert is_known(hue, "wickmarket")
    assert not is_known(hue, "old_bell_tower")
    _reveal(hue, "old_bell_tower")
    assert is_known(hue, "old_bell_tower")
    # An id the graph does not hold is nobody's secret.
    assert is_known(hue, "no_such_place")


def test_a_discovered_hidden_path_makes_its_end_known(hue: GameState) -> None:
    from engine.game import foraging
    from engine.game.locations import is_known

    hue.procgen.forest = {
        "hidden_paths": [{"id": "hidden_path_1", "label": "a drain", "leads_to": "the_undercroft"}]
    }
    assert not is_known(hue, "the_undercroft")
    hue.flags[f"{foraging.PATH_FLAG_PREFIX}hidden_path_1"] = True
    assert is_known(hue, "the_undercroft")


def test_the_validator_reads_a_reveal_as_a_location_reference() -> None:
    """A reveal naming a place that does not exist is a typo, caught at load."""
    from engine.games.validation import location_refs

    doc = {"effects": [{"type": "flag", "flag": "location_known:the_undercroft"}]}
    assert location_refs(doc) == {"the_undercroft"}


# -- THE LONG CON ----------------------------------------------------------------


def test_the_long_con_withholds_the_drying_room_until_the_case_names_it() -> None:
    """
    The drying room's own comment: the player must not know it exists "until
    the case puts them at its door". Before this it was a road off Harbour Road
    from the first visit. Now the case's fourth stage opening reveals it.
    """
    registry.activate("the-long-con")
    from engine.game.quests import QuestEngine, QuestProgress, _write

    state = GameState(session_id="long-con")
    state.location_id = "harbour_road"
    assert "the_drying_room" not in _travel_targets(state)
    assert "the_drying_room" not in _map(state)
    _assert_map_agrees_with_travel(state)

    # Mid-case, on the harbour stage: the manifest seen, standing on the road.
    _write(state, QuestProgress(quest_id="the_dead_man_photographed", stage_index=2))
    state.flags["nf_saw_the_manifest"] = True
    events = QuestEngine.evaluate(state)
    assert any(e.stage_id == "the_harbour" for e in events), events

    assert "the_drying_room" in _travel_targets(state)
    assert "the_drying_room" in _map(state)
    _assert_map_agrees_with_travel(state)


def test_a_v012_save_already_on_the_cold_room_can_travel_there_and_finish() -> None:
    """
    I1. v0.12 had no reveal, so a save already on `the_cold_room` never ran
    the v0.13 `on_enter` flag -- and the stage's door was a secret road
    nothing would ever offer. The reveal is DERIVED now (`known_when:` on the
    drying room, asked by `is_known`), so the old save needs nothing stored.
    """
    registry.activate("the-long-con")
    from engine.game.engine import GameEngine
    from engine.game.quests import QuestEngine, QuestProgress, _write, progress_records

    state = GameState(session_id="v012")
    state.location_id = "harbour_road"
    _write(state, QuestProgress(quest_id="the_dead_man_photographed", stage_index=3))
    old = GameState.from_save_dict(state.to_save_dict()) if hasattr(
        GameState, "from_save_dict") else state
    assert not any(k.startswith("location_known:") for k in old.flags)
    QuestEngine.evaluate(old)

    assert "the_drying_room" in _travel_targets(old)
    assert "the_drying_room" in _map(old)
    _assert_map_agrees_with_travel(old)

    engine = GameEngine.__new__(GameEngine)
    engine.state = old
    moved = engine.move_to("the_drying_room")
    assert moved.success, moved
    old.flags["nf_opened_the_cold_room"] = True
    QuestEngine.evaluate(old)
    record = progress_records(old)["the_dead_man_photographed"]
    assert record.status == "completed", record


def test_the_drying_room_stays_secret_before_the_cold_room() -> None:
    registry.activate("the-long-con")
    from engine.game.locations import is_known
    from engine.game.quests import QuestProgress, _write

    state = GameState(session_id="early")
    state.location_id = "harbour_road"
    assert not is_known(state, "the_drying_room")
    _write(state, QuestProgress(quest_id="the_dead_man_photographed", stage_index=2))
    assert not is_known(state, "the_drying_room")
    _write(state, QuestProgress(quest_id="the_dead_man_photographed", stage_index=3))
    assert is_known(state, "the_drying_room")


def _graph_with(tmp_path, **drying: object):
    import yaml

    doc = {"locations": {
        "yard": {"name": "Yard", "ring": 1, "connections": {"vault": {"hours": 1}}},
        "vault": {"name": "Vault", "ring": 1, "secret": True,
                  "connections": {"yard": {"hours": 1}}, **drying},
    }}
    path = tmp_path / "locations.yaml"
    path.write_text(yaml.safe_dump(doc), encoding="utf-8")
    return path


def test_known_when_reveals_while_it_holds(tmp_path) -> None:
    from engine.game import locations

    graph = locations.load_locations(_graph_with(tmp_path, known_when={"flag": "map_bought"}))
    assert graph["vault"]["known_when"] == {"flag": "map_bought"}
    state = GameState(session_id="kw")
    state.location_id = "yard"
    saved = dict(locations.LOCATIONS)
    try:
        locations.LOCATIONS.clear()
        locations.LOCATIONS.update(graph)
        assert not locations.is_known(state, "vault")
        state.flags["map_bought"] = True
        assert locations.is_known(state, "vault")
    finally:
        locations.LOCATIONS.clear()
        locations.LOCATIONS.update(saved)


@pytest.mark.parametrize("bad", [
    {"moon_phase": "full"},                          # unknown: unmet forever
    {"all": [{"flag": "x"}], "not_flag": "y"},        # sibling beside a group
    {"days_in_stage": 2},                             # no quest record here
    {"disposition": {"npc": "x", "min": 1}},          # no ledger here
    "the map",                                        # not a condition
])
def test_a_bad_known_when_is_refused_at_load(tmp_path, caplog, bad) -> None:
    from engine.game import locations

    graph = locations.load_locations(_graph_with(tmp_path, known_when=bad))
    assert "known_when" not in graph["vault"]
    assert "known_when" in caplog.text


def test_known_when_on_a_place_that_is_not_secret_is_refused(tmp_path, caplog) -> None:
    import yaml

    from engine.game import locations

    path = _graph_with(tmp_path)
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    doc["locations"]["yard"]["known_when"] = {"flag": "x"}
    path.write_text(yaml.safe_dump(doc), encoding="utf-8")
    graph = locations.load_locations(path)
    assert "known_when" not in graph["yard"]
    assert "known_when" in caplog.text


def test_the_validator_reports_a_bad_known_when() -> None:
    import copy

    from engine.games import registry as reg, validation

    manifest = reg.get("the-long-con")
    checker = validation.StoryValidator(manifest)
    checker._build_registries()
    checker.locations = copy.deepcopy(checker.locations)
    checker.locations["the_drying_room"]["known_when"] = {"moon_phase": "full"}
    checker.issues = []
    checker.check_locations()
    hits = [i for i in checker.issues if i.ref_id == "the_drying_room"]
    assert hits and "moon_phase" in hits[0].message, checker.issues


def test_the_validator_reads_a_narrative_flag_reveal_as_a_location_reference() -> None:
    """AUTHORING §3.7: a reveal listed in a stage's `narrative_flags` names a
    place too, so a typo there is caught like one in a flag effect."""
    from engine.games.validation import location_refs

    doc = {"stages": [{"id": "s", "narrative_flags": ["nf_x", "location_known:the_vault"]}]}
    assert location_refs(doc) == {"the_vault"}


# -- the flagship ------------------------------------------------------------------


def test_the_flagship_travel_is_the_raw_graph_unchanged() -> None:
    """
    A story that declares no secret pays nothing: every place is known, and the
    enum is exactly the graph's roads with their labels, as it always was.
    """
    registry.activate("clockwork-dark")
    from engine.game.intents import _travel
    from engine.game.locations import LOCATIONS, get_edge, is_known, neighbours

    assert not any(row.get("secret") for row in LOCATIONS.values())
    for loc in sorted(LOCATIONS):
        state = GameState(session_id="flagship")
        state.location_id = loc
        assert all(is_known(state, other) for other in LOCATIONS)
        expected = tuple(
            (
                other,
                f"{LOCATIONS[other]['name']}, {get_edge(loc, other)['hours']}h",
            )
            for other in neighbours(loc)
        )
        verb = _travel(state)
        assert (verb.options if verb else ()) == expected, loc


#: sha256 of the flagship's `codex_places` payload -- at game start in its
#: entry location, and standing in each of its 20 places -- measured at ab54fa7
#: (before v0.13.0's secret places) in a scratch worktree. A story with no
#: secret must draw exactly the map it always drew.
FLAGSHIP_MAP_DIGEST = "af9028ded693c58c40411d9b6153ce9cfb893fe2928badae296ae1d19a0de055"
FLAGSHIP_START_MAP_DIGEST = "6982486eb4e81e61e29799b7d10cf1291e7732367821dbb03bd46ee3e79b816d"


def test_the_flagship_map_payload_is_what_it_was_before_secret_places() -> None:
    import hashlib
    import json

    from engine.game.locations import LOCATIONS
    from engine.scenes.default_api import codex_places

    registry.activate("clockwork-dark")
    out = {}
    start = GameState(session_id="s", rng_seed=7)
    start.location_id = registry.get("clockwork-dark").entry_location
    out["__start__"] = codex_places(start)
    for loc in sorted(LOCATIONS):
        state = GameState(session_id="s", rng_seed=7)
        state.location_id = loc
        out[loc] = codex_places(state)

    def digest(value: object) -> str:
        blob = json.dumps(value, sort_keys=True, default=str)
        return hashlib.sha256(blob.encode()).hexdigest()

    assert len(LOCATIONS) == 20
    assert digest(out["__start__"]) == FLAGSHIP_START_MAP_DIGEST
    assert digest(out) == FLAGSHIP_MAP_DIGEST


# -- follow-up: found shortcuts are offered, unknown secrets are refused ------------


def _force_forage_success(monkeypatch: pytest.MonkeyPatch) -> None:
    from engine.game import checks
    from engine.game.dice import DiceResult

    dice = DiceResult(
        sides=20, rolls=[10], modifier=0, total=20,
        critical=False, fumble=False, reason="forage",
    )
    result = checks.CheckResult(
        skill="survival", stat="wits", dc=10, difficulty="standard",
        dice=dice, modifiers=[], total=20, margin=10, degree="success",
    )
    monkeypatch.setattr(checks, "resolve", lambda *a, **k: result)


def test_a_found_shortcut_is_offered_walkable_and_drawn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    `_travel` read `to_id` from rows that carry `leads_to`, so a hidden path
    found by foraging never offered the leg it opens: `move_to` would walk it,
    the enum never named it. Found by foraging here, the way the game finds it.
    """
    registry.activate("clockwork-dark")
    from engine.game import foraging
    from engine.game.engine import GameEngine
    from engine.game.locations import LOCATIONS, get_edge
    from engine.game.procgen import new_game_state

    state = new_game_state(seed=42)
    home = sorted(foraging._all_forageable_places())[0]
    far = next(
        loc for loc in sorted(LOCATIONS)
        if loc != home and get_edge(home, loc) is None
    )
    state.procgen.forest["hidden_paths"] = [
        {"id": "hidden_path_1", "label": "deer track", "leads_to": far, "dc": 2}
    ]
    assert foraging.path_home(state, "hidden_path_1") == home
    state.location_id = home
    assert far not in _travel_targets(state)

    _force_forage_success(monkeypatch)
    assert foraging.forage(state)["discovery"] is not None

    from engine.game.intents import _travel

    verb = _travel(state)
    assert far in verb.targets, "a found shortcut is not offered"
    assert verb.label_for(far) == (
        f"{LOCATIONS[far]['name']}, {foraging.SHORTCUT_HOURS}h"
    )
    # The map draws the same leg the enum offers.
    _assert_map_agrees_with_travel(state)
    assert far in {r["to"] for r in _map(state)[home]["roads"]}

    state.stats.stamina = 100
    move = GameEngine(state).move_to(far)
    assert move.success is True
    assert move.hours == foraging.SHORTCUT_HOURS


def test_move_to_refuses_a_secret_place_the_player_does_not_know(hue: GameState) -> None:
    """
    AGENTS.md rule 1: an intent illegal at execution produces an engine refusal
    that reaches the prose -- never a silent walk into a place nobody found.
    """
    from engine.game.engine import GameEngine
    from engine.game.intents import declined_reason

    engine = GameEngine(hue)
    move = engine.move_to("the_undercroft")
    assert move.success is False
    assert hue.location_id == "tallow_docks"
    assert declined_reason("travel", move.to_dict()), "the refusal has no words"
    assert "Undercroft" not in move.message, "the refusal names the secret"

    _reveal(hue, "the_undercroft")
    assert engine.move_to("the_undercroft").success is True
    assert hue.location_id == "the_undercroft"
