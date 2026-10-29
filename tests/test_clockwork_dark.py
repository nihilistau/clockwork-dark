"""
The Clockwork Dark, overhauled (v0.25.0; spec docs/superpowers/specs/
2026-10-27-v0.25.0-clockwork-dark-overhaul-design.md).

One file for the story's own claims, grown task by task: the cast (T4), the
map (T5), the doors (T6-T7), the critical path and the levy (T8), and the
card-only walks and the presence sweep (T9).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterator

import pytest
import yaml

from engine.games import registry

STORY = Path(__file__).resolve().parents[1] / "games" / "clockwork-dark"
NEW_PEOPLE = ("npc_hallam", "npc_nessa", "npc_wenna", "npc_edrin")

#: Plan decision 2: each person's hours, each covering the day exactly once.
WHERE = {
    "npc_hallam": {"the_forge": range(6, 19), "edgewood_square": (19, 20),
                   "well_row": (21, 22, 23, 0, 1, 2, 3, 4, 5)},
    "npc_nessa": {"fallow_farm": (6, 7, 8, 17, 18, 19, 20, 21, 22, 23, 0, 1, 2, 3, 4, 5),
                  "edgewood_square": range(9, 17)},
    "npc_wenna": {"edgewood_shrine": (6, 7, 18, 19, 20, 21), "well_row": (*range(8, 18), 22, 23, 0, 1, 2, 3, 4, 5)},
    "npc_edrin": {"fallow_farm": range(24)},
}
ASLEEP = {
    "npc_hallam": {21, 22, 23, 0, 1, 2, 3, 4, 5}, "npc_nessa": {21, 22, 23, 0, 1, 2, 3, 4, 5},
    "npc_wenna": {22, 23, 0, 1, 2, 3, 4, 5}, "npc_edrin": {20, 21, 22, 23, 0, 1, 2, 3, 4},
}


@pytest.fixture
def flagship() -> Iterator[None]:
    registry.activate("clockwork-dark")
    try:
        yield
    finally:
        registry.deactivate()


def new_state(seed: int = 7) -> Any:
    from engine.game.procgen import new_game_state

    return new_game_state(seed=seed)


def at_hour(state: Any, hour: int) -> None:
    """Stand on an hour of the current day (tests only; `set_clock` writes no world)."""
    from engine.game.clock import set_clock

    set_clock(state, day=state.world_day, hour=hour)


def _schedules() -> dict:
    return yaml.safe_load((STORY / "data" / "world" / "npc_schedules.yaml").read_text(encoding="utf-8"))


# -- the cast (T4, §3.3) ------------------------------------------------------------------------------


def test_the_four_new_people_cover_every_hour_once() -> None:
    npcs = _schedules()["npcs"]
    for npc_id in NEW_PEOPLE:
        row = npcs[npc_id]
        assert row["name"] and row["role"] and row["home"], npc_id
        hours = sorted(h for slot in row["routine"] for h in slot["hours"])
        assert hours == list(range(24)), npc_id


@pytest.mark.parametrize("npc_id", NEW_PEOPLE)
def test_each_stands_where_the_cast_table_puts_them(flagship, npc_id: str) -> None:
    from engine.world import npc_sim

    state = new_state()
    for place, hours in WHERE[npc_id].items():
        for hour in hours:
            at_hour(state, hour)
            presence = npc_sim.resolve_npc(state, npc_id)
            assert presence.location_id == place, (npc_id, hour)
            assert presence.available is (hour not in ASLEEP[npc_id]), (npc_id, hour)


def test_they_are_not_in_the_procgen_village() -> None:
    """§3.3: the PROCGEN stream draws the template's named list; adding to it would regenerate every seed."""
    template = (STORY / "data" / "procgen_templates" / "edgewood.yaml").read_text(encoding="utf-8")
    assert not any(npc_id in template for npc_id in NEW_PEOPLE)


def test_nessa_has_one_surname() -> None:
    for path in STORY.rglob("*"):
        if path.is_file() and path.suffix in (".yaml", ".md", ".json"):
            text = path.read_text(encoding="utf-8")
            assert "Nessa Weller" not in text and "Weller girl" not in text, path
    assert "Weller" in (STORY / "data" / "quests" / "quiet_life" / "lost_goat.yaml").read_text(encoding="utf-8")


#: An age as the story's text gives it: "a six-year-old", "She is six", "Nessa Fallow, nine".
_AGE = re.compile(
    r"\b(\w+)[- ]years?[- ]old\b|\bshe is (\w+)\b|\bNessa(?: Fallow)?, (\w+)\b", re.IGNORECASE
)
_NUMBER_WORDS = {"one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
                 "eleven", "twelve", "thirteen", "fourteen"}


def test_nessa_is_nine_everywhere_the_story_gives_her_age() -> None:
    """v0.25.0 T4 fix round 1 (the controller's ruling): the cast line, the portrait and the
    quest gave a narrator two ages. Every age in a file that speaks of Nessa (or of her
    drawing, `childs_drawing`) is nine."""
    ages: list[tuple[str, str]] = []
    for path in STORY.rglob("*"):
        if not (path.is_file() and path.suffix in (".yaml", ".md", ".json")) or path.name == "CHANGELOG.md":
            continue
        text = path.read_text(encoding="utf-8")
        if "Nessa" not in text and path.name != "childs_drawing.yaml":
            continue
        for match in _AGE.finditer(text):
            word = next(g for g in match.groups() if g).lower()
            if word in _NUMBER_WORDS or word.isdigit():
                ages.append((path.name, word))
    assert ages, "no age found: the pattern no longer reads the story"
    assert all(word == "nine" for _, word in ages), ages


def test_the_vines_bring_ilya_to_the_square(flagship) -> None:
    from engine.world import npc_sim, world_effects

    state = new_state()
    at_hour(state, 10)
    assert npc_sim.resolve_npc(state, "npc_ilya").location_id == "tinker_caravan"
    world_effects.apply_beat(state, "vines_breach_forest")
    assert npc_sim.resolve_npc(state, "npc_ilya").location_id == "edgewood_square"


def test_the_tower_empties_the_fallow_holding_and_brings_sera_in(flagship) -> None:
    from engine.world import npc_sim, world_effects

    state = new_state()
    at_hour(state, 10)
    world_effects.apply_beat(state, "tower_assembles")
    for npc_id, place in (("npc_edrin", "refugee_camp"), ("npc_nessa", "refugee_camp"),
                          ("npc_sera", "edgewood_square")):
        assert npc_sim.resolve_npc(state, npc_id).location_id == place, npc_id


def test_a_pin_still_outranks_a_doom_move(flagship) -> None:
    from engine.game.effects import apply_effect
    from engine.world import npc_sim, world_effects

    state = new_state()
    at_hour(state, 10)
    world_effects.apply_beat(state, "vines_breach_forest")
    apply_effect(state, {"type": "flag", "flag": "npc_pin_npc_ilya", "value": True})
    assert npc_sim.resolve_npc(state, "npc_ilya").location_id == "tinker_caravan"


def test_the_codex_lists_the_declared_people_named_once_met(flagship) -> None:
    from types import SimpleNamespace

    from engine.scenes import default_api

    state = new_state()
    unmet = default_api.codex_souls(state, SimpleNamespace(relations={}))["souls"]
    met = default_api.codex_souls(state, SimpleNamespace(relations={"npc_hallam": SimpleNamespace(met=True)}))["souls"]
    assert len(unmet) == len(state.procgen.npcs) + len(NEW_PEOPLE)
    assert "Hallam" in [s["name"] for s in met] and "Hallam" not in [s["name"] for s in unmet]
    assert sum(1 for s in met if s["name"] == "Hallam") == 1


def test_the_prompt_names_the_four_and_nothing_else_moved() -> None:
    prompt = (STORY / "prompts" / "storyteller.md").read_text(encoding="utf-8")
    for name in ("Hallam", "Nessa Fallow", "Wenna", "Edrin Fallow"):
        assert name in prompt
    for word in ("intensity", "explicit", "safety", "content limit"):
        assert word not in prompt.lower()          # rule 12


# -- the map (T5, §3.4, §5.3) ----------------------------------------------------------------------

LOCATIONS = STORY / "data" / "world" / "locations.yaml"


def test_no_edge_keeps_a_needs_band_note_with_danger() -> None:
    for number, line in enumerate(LOCATIONS.read_text(encoding="utf-8").splitlines(), 1):
        if "needs band" in line and "danger_dc:" in line:
            assert "danger_dc: 0" in line, f"locations.yaml:{number} has danger and still needs a band"
    assert "needs band" not in "".join(
        line for line in LOCATIONS.read_text(encoding="utf-8").splitlines() if "danger_dc:" in line)


BANDED = {
    6: ("forest_clearing>deeper_forest", "deeper_forest>forest_clearing", "forest_clearing>herb_glen",
        "herb_glen>forest_clearing", "deeper_forest>herb_glen", "herb_glen>deeper_forest",
        "deeper_forest>charcoal_burn", "charcoal_burn>deeper_forest", "edgewood_square>charcoal_burn",
        "edgewood_square>fallow_farm"),
    10: ("deeper_forest>old_barrows", "old_barrows>deeper_forest", "old_barrows>tunnel_entrance",
         "tunnel_entrance>old_barrows", "millhaven_gate>toll_bridge", "toll_bridge>burned_farmstead",
         "burned_farmstead>toll_bridge", "refugee_camp>burned_farmstead", "burned_farmstead>refugee_camp",
         "millhaven_gate>refugee_camp"),
    12: ("forest_clearing>the_works", "the_works>forest_clearing"),
    14: ("toll_bridge>heartland_road", "heartland_road>toll_bridge", "heartland_road>the_join",
         "the_join>heartland_road"),
}
DOORS = ("millhaven_gate>millhaven_market", "millhaven_gate>millhaven_barracks",
         "millhaven_market>millhaven_barracks", "millhaven_barracks>millhaven_market")


def test_every_marked_line_is_banded_or_a_door(flagship) -> None:
    from engine.game.locations import LOCATIONS as GRAPH

    for dc, legs in BANDED.items():
        for leg in legs:
            src, dst = leg.split(">")
            assert int(GRAPH[src]["connections"][dst]["danger_dc"]) == dc, leg
    for leg in DOORS:
        src, dst = leg.split(">")
        edge = GRAPH[src]["connections"][dst]
        assert int(edge["danger_dc"]) == 0 and int(edge["hours"]) == 0, leg


def test_the_holding_has_rows_of_its_own_and_the_squares_rows_are_unchanged() -> None:
    """Ruling I5 (amends Plan decision 17): the square's arrivals keep `to: [edgewood_square]`
    and the holding's outbound leg is carried by rows written for it."""
    doc = yaml.safe_load((STORY / "data" / "encounters" / "village.yaml").read_text(encoding="utf-8"))
    destinations = [tuple(row["triggers"]["to"]) for row in doc["encounters"]]
    assert {d for d in destinations if d != ("fallow_farm",)} == {("edgewood_square",)}
    assert 1 <= destinations.count(("fallow_farm",)) <= 2


@pytest.mark.parametrize("place, condition", [
    ("the_works", "seam"),
    ("the_join", "road"),
])
def test_a_secret_place_is_unknown_until_its_condition(flagship, place: str, condition: str) -> None:
    from engine.game import locations
    from engine.game.effects import apply_effect
    from engine.game.quests import QuestProgress

    state = new_state()
    assert not locations.is_known(state, place)
    if condition == "seam":
        apply_effect(state, {"type": "flag", "flag": "seam_opened", "value": True})
    else:
        state.quests["the_heartland_road"] = QuestProgress(quest_id="the_heartland_road", stage_index=1).to_dict()
    assert locations.is_known(state, place)


@pytest.mark.parametrize("place, neighbour", [
    ("the_works", "forest_clearing"),
    ("the_join", "heartland_road"),
])
def test_a_secret_place_is_never_offered_as_a_road_before(flagship, place: str, neighbour: str) -> None:
    from engine.game import intents

    state = new_state()
    state.location_id = neighbour
    travel = intents.find_verb(intents.legal_intents(state), "travel")
    assert travel is not None and travel.targets, neighbour   # the neighbour has other roads
    assert place not in travel.targets


@pytest.mark.parametrize("degree", ["crit_success", "success", "partial", "failure"])
def test_sharing_bread_with_the_burners_dog_spends_the_loaf(
    flagship, monkeypatch: pytest.MonkeyPatch, degree: str
) -> None:
    import dataclasses

    from engine.game import checks, encounter
    from engine.game.effects import apply_effect

    state = new_state()
    apply_effect(state, {"type": "item", "item_id": "loaf", "name": "Loaf of bread", "qty": 1, "tags": ["food"]})
    before = sum(i.qty for i in state.inventory if i.id == "loaf")
    encounter.begin(state, "the_burners_dog")
    forced = dataclasses.replace(checks.resolve(state, "craft", "easy"), degree=degree)
    monkeypatch.setattr(checks, "resolve", lambda *a, **k: forced)
    receipt = encounter.resolve_approach(state, "share")
    assert receipt["ok"] and receipt["degree"] == degree, receipt
    assert sum(i.qty for i in state.inventory if i.id == "loaf") == before - 1


def test_the_works_below_is_found_on_arrival(flagship) -> None:
    from engine.game.effects import apply_effect
    from engine.game.quests import QuestEngine, STATUS_COMPLETED, progress_records

    state = new_state()
    state.arcs_unlocked.append("whisper")          # long open by 0.70 (arcs.yaml); the arc writer is a list append
    apply_effect(state, {"type": "flag", "flag": "seam_opened", "value": True})
    state.location_id = "the_works"
    for _ in range(3):
        QuestEngine.evaluate(state)
    assert progress_records(state)["the_works_below"].status == STATUS_COMPLETED
    assert any(i.id == "brass_shard" for i in state.inventory)


def test_the_join_is_where_the_road_is_walked() -> None:
    quest = yaml.safe_load((STORY / "data" / "quests" / "convergence" / "the_heartland_road.yaml").read_text("utf-8"))
    walk = next(s for s in quest["stages"] if s["id"] == "walk_the_join")
    assert {"at_location": "the_join"} in walk["complete_when"]["all"]


def test_the_seams_riddle_counts_its_own_answer() -> None:
    doc = yaml.safe_load((STORY / "data" / "challenges" / "edgewood.yaml").read_text(encoding="utf-8"))
    seam = next(p for p in doc["set_pieces"] if p["id"] == "sealed_seam")
    answer = str(seam["challenge"]["answer"])
    words = {4: "four", 5: "five", 6: "six"}
    assert f"{words[len(answer)]} letters" in str(seam["challenge"]["prompt"])


# -- doors I (T6, §4.2-§4.3) ---------------------------------------------------------------------

from endings_driver import Door, drive_ending  # noqa: E402

from tests import clockwork_doors as doors  # noqa: E402

SCENES = STORY / "data" / "scenes"


def _drive(ending_id: str, door: Door, setup) -> Any:
    state, shown = drive_ending("clockwork-dark", ending_id, door, setup, seed=7)
    return state


@pytest.mark.parametrize("ending_id, door, setup", [
    ("the_hearth_holds", Door.card("the_morning_firing", "H1_the_question", "stay"), doors.hearth_door),
    ("the_dark_keeps_its_hours", Door.card("the_morning_firing", "H1_the_question", "stay_anyway"),
     doors.stay_anyway_door),
    ("the_long_witness", Door.card("the_count_kept", "W1_the_list", "give_it"), doors.witness_door),
    ("the_counted_march", Door.card("the_muster_roll", "M1_strike_the_name", "strike_it"), doors.march_door),
    ("the_named_wound", Door.card("the_morning_firing", "Q1_tell_her_or_dont", "tell_her"), doors.named_wound_door),
    ("the_named_wound", Door.card("the_morning_firing", "Q1_tell_her_or_dont", "say_nothing"),
     doors.named_wound_door),
])
def test_each_door_of_the_first_three_decks_locks_its_ending(ending_id, door, setup) -> None:
    _drive(ending_id, door, setup)


def _deal(state: Any, deck_id: str) -> list[str]:
    from engine.content import director

    receipt = director.begin(state, deck_id)
    assert receipt["ok"], receipt
    return receipt["card_ids"]


def test_h1_offers_stay_only_while_the_hearth_is_open(flagship) -> None:
    from engine.content import director

    open_state, shut_state = new_state(), new_state()
    doors.hearth_door(open_state)
    doors.stay_anyway_door(shut_state)
    for state, offered in ((open_state, ["stay", "not_yet"]), (shut_state, ["stay_anyway", "not_yet"])):
        assert _deal(state, "the_morning_firing") == ["H1_the_question"]
        assert [o["id"] for o in director.options(state)] == offered


def test_h1_is_not_dealt_while_the_named_wound_is_open(flagship) -> None:
    from engine.content import deck as deck_module

    state = new_state()
    doors.named_wound_door(state)
    doors.at_stage(state, "banking_the_fire", 1)
    doors.flag(state, "nf_hearth_taking_stock")
    eligible, _ = deck_module.eligible_cards(state, deck_module.load_deck("the_morning_firing"))
    assert [c.id for c in eligible] == ["Q1_tell_her_or_dont"]


def test_a_dealt_door_stays_answerable_after_its_person_leaves(flagship) -> None:
    """Review Focus 1: Maris goes to the square at noon; the card in hand still locks what it says."""
    from engine.content import director
    from engine.game import endings
    from engine.game.clock import advance_time

    state = new_state()
    doors.hearth_door(state)
    _deal(state, "the_morning_firing")
    advance_time(state, 8.0)                       # 05:00 -> 13:00
    assert director.resolve(state, chosen="stay")["ok"]
    assert endings.locked(state) == "the_hearth_holds"


def test_not_yet_locks_nothing_and_the_deck_comes_round_again(flagship) -> None:
    from engine.content import director
    from engine.game import endings

    state = new_state()
    doors.hearth_door(state)
    _deal(state, "the_morning_firing")
    assert director.resolve(state, chosen="not_yet")["ok"]
    assert endings.locked(state) == endings.NONE_ID
    doors.stand(state, "edgewood_square", 12)
    director.rearm(state)
    doors.stand(state, "edgewood_bakery", 5)
    deck_id, _card, _src = director.due(state)
    assert deck_id == "the_morning_firing"


def test_no_id_less_ending_lock_remains_in_the_story() -> None:
    from engine.games.validation import walk

    for path in (STORY / "data").rglob("*.yaml"):
        for node in walk(yaml.safe_load(path.read_text(encoding="utf-8"))):
            if node.get("type") == "ending_lock":
                assert node.get("ending"), f"{path.relative_to(STORY)}: an id-less ending_lock"


def test_every_tease_is_one_sentence_and_names_no_ending() -> None:
    doc = yaml.safe_load((STORY / "data" / "rules" / "endings.yaml").read_text(encoding="utf-8"))
    titles = [str(body["label"]).lower() for body in doc["classes"].values()]
    for ending_id, body in doc["classes"].items():
        tease = str(body.get("tease") or "")
        assert tease.endswith(".") and tease.count(". ") == 0, ending_id
        assert not any(title in tease.lower() for title in titles), ending_id
        assert "clockwork" not in tease.lower(), ending_id    # the reveal word (spoilers.yaml)


def test_no_tease_carries_a_term_the_spoilers_mask() -> None:
    """The payload ships every tease at every tier (§8.4), so none may say what spoilers.yaml hides."""
    endings_doc = yaml.safe_load((STORY / "data" / "rules" / "endings.yaml").read_text(encoding="utf-8"))
    rows = yaml.safe_load((STORY / "data" / "rules" / "spoilers.yaml").read_text(encoding="utf-8"))["spoilers"]
    assert rows
    for ending_id, body in endings_doc["classes"].items():
        tease = str(body.get("tease") or "")
        assert tease, ending_id
        for row in rows:
            flags = 0 if row.get("case_sensitive") else re.IGNORECASE
            pattern = r"\b" + re.escape(str(row["term"])) + r"\b"
            assert not re.search(pattern, tease, flags), (ending_id, row["term"])


# -- doors II (T7, §4.2-§4.3, §6.3) ------------------------------------------------------------------

@pytest.mark.parametrize("item_id", ["the_written_name", "ninth_pin", "brass_shard"])
def test_s2_takes_exactly_the_thing_offered_and_the_price_is_asked(item_id: str) -> None:
    """Bug 2: the sacrifice took the written name whatever was chosen."""
    others = [i for i in doors.PAID if i != item_id]

    def setup(state):
        doors.price_door_for(item_id)(state)
        for other in others:
            doors.effect(state, type="item", item_id=other, qty=1)

    state = _drive("the_price_asked", Door.card("the_price", "S2_pay_it", doors.PAID[item_id]), setup)
    held = {i.id for i in state.inventory if i.qty > 0}
    assert item_id not in held and set(others) <= held


def test_paying_the_shard_completes_the_sacrifice_and_the_name_stays(flagship) -> None:
    """Bug 2, the quest half: once S2 pays the shard, the_sacrifice completes through
    QuestEngine.evaluate, the written name is still held and the card's lock stands
    (pay_it removed the name and the quest locked the ending itself)."""
    from engine.content import director
    from engine.game import endings
    from engine.game.quests import STATUS_COMPLETED, QuestEngine, progress_records

    state = new_state()
    state.arcs_unlocked.append("convergence")
    doors.price_door_for("brass_shard")(state)
    doors.effect(state, type="item", item_id="the_written_name", qty=1)
    assert _deal(state, "the_price") == ["S2_pay_it"]
    assert director.resolve(state, chosen="pay_the_shard")["ok"]
    assert endings.locked(state) == "the_price_asked"
    for _ in range(3):
        QuestEngine.evaluate(state)
    assert progress_records(state)["the_sacrifice"].status == STATUS_COMPLETED
    held = {i.id for i in state.inventory if i.qty > 0}
    assert "the_written_name" in held and "brass_shard" not in held
    assert endings.locked(state) == "the_price_asked"


def test_the_sacrifice_quest_locks_no_ending_the_card_does() -> None:
    """Bug 2: the quest's on_complete locked The Price Asked itself. A lock is never walked
    back, so a quest-level lock behind the card's is invisible in a drive; held by the file."""
    from engine.games.validation import walk

    quest = yaml.safe_load((STORY / "data" / "quests" / "convergence" / "the_sacrifice.yaml").read_text("utf-8"))
    kinds = {node.get("type") for node in walk(quest)}
    assert not kinds & {"ending_lock", "ending_module"}, kinds & {"ending_lock", "ending_module"}


def test_s1_offers_one_beat_per_thing_carried(flagship) -> None:
    from engine.content import director

    state = new_state()
    doors.at_pay_it_by_the_narrator(state)        # a v0.24.0-shaped run: re-offered the choice (I1)
    assert _deal(state, "the_price") == ["S1_choose_what"]
    assert [o["id"] for o in director.options(state)] == ["offer_the_name", "offer_the_shard", "not_yet"]


def test_a_thing_offered_and_then_sold_is_offered_again(flagship) -> None:
    from engine.content import deck as deck_module

    state = new_state()
    doors.price_door_for("brass_shard")(state)
    doors.effect(state, type="remove_item", item_id="brass_shard", qty=1)
    doors.effect(state, type="item", item_id="the_written_name", qty=1)
    eligible, _ = deck_module.eligible_cards(state, deck_module.load_deck("the_price"))
    assert [c.id for c in eligible] == ["S1_choose_what"]


def test_the_pin_is_set_at_the_join_and_leaves_the_pack() -> None:
    state = _drive("the_pin_and_the_join", Door.card("the_join", "J1_the_pin", "set_it"), doors.pin_door)
    assert not any(i.id == "ninth_pin" and i.qty > 0 for i in state.inventory)


def test_the_last_hour_deals_the_last_morning() -> None:
    _drive("the_stopped_wheel", Door.card("the_stopped_wheel", "Z1_the_last_morning"), doors.last_hour_door)


def test_the_last_morning_waits_for_an_open_hand_then_is_dealt(flagship) -> None:
    """Review Focus 4: an encounter open at the crossing keeps the turn; the wheel's scene comes after."""
    from engine.content import director
    from engine.game import encounter

    state = new_state()
    encounter.begin(state, "lost_child_at_the_treeline")
    doors.last_hour_door(state)
    assert director.ensure_scene(state) == []
    encounter.end(state)
    (receipt,) = director.ensure_scene(state)
    assert receipt["result"]["deck_id"] == "the_stopped_wheel"


def test_the_second_death_in_consuming_ends_in_the_fail_forward() -> None:
    _drive("the_dark_keeps_its_hours", Door.death(), doors.second_death_door)


def test_leaving_the_pin_grants_no_pin(flagship) -> None:
    """Bug 1: `take_it_or_dont`'s on_complete granted the pin either way."""
    from engine.game.quests import STATUS_COMPLETED, QuestEngine, progress_records

    state = new_state()
    state.arcs_unlocked.append("convergence")
    doors.completed(state, "naming_the_wound")
    doors.at_stage(state, "the_ninth_pin", 2)
    doors.flag(state, "nf_ninth_left")
    QuestEngine.evaluate(state)
    assert progress_records(state)["the_ninth_pin"].status == STATUS_COMPLETED
    assert not any(i.id == "ninth_pin" for i in state.inventory)


@pytest.mark.parametrize("quest_id, index, flag_id", [
    ("the_ninth_pin", 2, "nf_ninth_taken"),
    ("the_ninth_pin", 2, "nf_ninth_left"),
    ("the_sacrifice", 1, "nf_sacrifice_chosen"),
    ("the_sacrifice", 2, "nf_sacrifice_paid"),
])
def test_the_narrator_cannot_raise_a_card_carried_flag(flagship, quest_id, index, flag_id) -> None:
    from engine.game.quests import QuestEngine

    state = new_state()
    doors.at_stage(state, quest_id, index)
    assert flag_id not in QuestEngine.allowed_narrative_flags(state)


# -- the critical path, the levy, the bargain (T8, §4.3-§5.1) -------------------------------------

def test_every_deck_is_due_only_when_a_card_can_be_dealt() -> None:
    """Plan decision 3: a deck with a `when:` ends it with `any:` of its cards' own gates, in card order."""
    for path in sorted(SCENES.glob("*.yaml")):
        deck = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert deck.get("draw") == 1, path.name
        if "when" not in deck or path.stem == "the_press":
            continue
        tail = deck["when"]["all"][-1]
        assert list(tail) == ["any"], path.name
        assert tail["any"] == [card["when"] for card in deck["cards"]], path.name


def test_fourteen_decks_and_thirty_four_cards() -> None:
    decks = [yaml.safe_load(p.read_text(encoding="utf-8")) for p in SCENES.glob("*.yaml")]
    assert len(decks) == 14 and sum(len(d["cards"]) for d in decks) == 34


def _rep(faction: str, n: int):
    return lambda s: doors.effect(s, type="reputation", faction=faction, delta=n)


def _item(item_id: str):
    return lambda s: doors.effect(s, type="item", item_id=item_id, qty=1)


def _phase(progress: float):
    """The reading set the engine's way (ruling B1: `doors.at_reading`, never a bare write)."""
    return lambda s: doors.at_reading(s, progress)


def _pin_ilya(s):
    doors.flag(s, "npc_pin_npc_ilya")


def _pin_sera(s):
    doors.flag(s, "npc_pin_npc_sera")


#: (deck, card, beat or "", quest, stage index, place, hour, extra setup, flag the beat writes)
CARDS = [
    ("the_bakehouse", "B1_ask_for_work", "", "bakery_apprentice", 0, "edgewood_bakery", 9, None, "nf_bakery_asked_for_work"),
    ("nessas_drawings", "N1_see_it", "", "childs_drawing", 0, "edgewood_square", 10, None, "nf_drawing_seen"),
    ("nessas_drawings", "N2_ask_her", "", "childs_drawing", 1, "edgewood_square", 10, None, "nf_drawing_asked"),
    ("nessas_drawings", "N3_keep_one", "", "childs_drawing", 2, "edgewood_bakery", 10, None, "nf_drawing_kept"),
    ("the_naming", "G1_lay_it_out", "", "naming_the_wound", 0, "edgewood_square", 20, None, "nf_naming_laid_it_out"),
    ("the_naming", "G2_say_it_aloud", "", "naming_the_wound", 1, "tinker_caravan", 20, _phase(0.55), "nf_naming_spoke_it"),
    ("the_naming", "G3_write_it_down", "", "naming_the_wound", 2, "edgewood_bakery", 20, None, "nf_naming_wrote_it_down"),
    ("the_village_meeting", "V1_call_the_meeting", "", "what_edgewood_keeps", 0, "edgewood_square", 12, None, "nf_edgewood_called_it"),
    ("the_village_meeting", "V2_the_vote", "split", "what_edgewood_keeps", 1, "edgewood_square", 12, None, "nf_edgewood_split"),
    ("the_village_meeting", "V3_warn_them", "", "conscription_list", 2, "edgewood_square", 12, _item("copied_list"), "nf_list_warned_edgewood"),
    ("the_levy_table", "L1_watch_them_choose", "", "militia_press", 0, "millhaven_gate", 9, None, "nf_press_watched"),
    ("the_levy_table", "L2_the_weller_boy", "speak_up", "militia_press", 1, "millhaven_gate", 9, None, "nf_press_spoke_up"),
    ("the_levy_table", "L3_get_near_it", "", "conscription_list", 0, "millhaven_gate", 9, None, "nf_list_glimpsed"),
    ("the_levy_table", "L5_ask_her_straight", "", "seras_compromise", 0, "millhaven_gate", 9, _pin_sera, "nf_sera_asked"),
    ("the_levy_table", "L6_hear_the_number", "", "seras_compromise", 1, "millhaven_gate", 9, _pin_sera, "nf_sera_heard_out"),
    ("the_levy_table", "L7_answer_her", "refuse", "seras_compromise", 2, "millhaven_gate", 9, _pin_sera, "nf_sera_refused"),
    ("the_ninth_pin", "T1_ask_for_it", "", "the_ninth_pin", 0, "tinker_caravan", 10, _pin_ilya, "nf_ninth_asked"),
    ("the_ninth_pin", "T2_pay_for_it", "", "the_ninth_pin", 1, "tinker_caravan", 10,
     lambda s: (_pin_ilya(s), _rep("tinkers", 10)(s)), "nf_ninth_earned"),
    ("the_ninth_pin", "T3_take_it_or_dont", "leave_it", "the_ninth_pin", 2, "tinker_caravan", 10, _pin_ilya, "nf_ninth_left"),
    ("the_inward_road", "R1_measure_it", "", "the_heartland_road", 0, "millhaven_gate", 12, _item("road_map"), "nf_road_measured"),
]


@pytest.mark.parametrize("row", CARDS, ids=[r[1] for r in CARDS])
def test_each_critical_path_card_is_dealt_at_its_stage_and_writes_its_flag(flagship, row) -> None:
    from engine.content import deck as deck_module
    from engine.content import director
    from engine.game.quests import evaluate_condition

    deck_id, card_id, beat, quest, index, place, hour, extra, flag_id = row
    state = new_state()
    doors.at_stage(state, quest, index)
    if extra is not None:
        extra(state)
    doors.stand(state, place, hour)
    deck = deck_module.load_deck(deck_id)
    assert evaluate_condition(state, deck.when), f"{deck_id} is not due at {place} at {hour}"
    eligible, rejected = deck_module.eligible_cards(state, deck)
    assert card_id in [c.id for c in eligible], rejected
    assert director.begin(state, deck_id, forced_card=card_id)["ok"]
    out = director.resolve(state, chosen=beat)
    assert out["ok"], out
    assert state.flags.get(flag_id), flag_id


def test_l4_copies_the_list_on_a_pass_and_costs_standing_on_a_fail(flagship, monkeypatch) -> None:
    """A stealth roll (`checks.resolve`, which a beat's skill gate calls), forced both ways."""
    from types import SimpleNamespace

    from engine.content import director
    from engine.game import checks, reputation

    for passed in (True, False):
        state = new_state()
        doors.at_stage(state, "conscription_list", 1)
        doors.stand(state, "millhaven_gate", 9)
        outcome = SimpleNamespace(skill="stealth", difficulty="standard", dc=12, total=12 if passed else 4,
                                  margin=0, degree="success" if passed else "failure", summary="",
                                  success=passed)
        monkeypatch.setattr(checks, "resolve", lambda *a, outcome=outcome, **k: outcome)
        before = reputation.get(state, "militia")
        assert director.begin(state, "the_levy_table", forced_card="L4_copy_it")["ok"]
        assert director.resolve(state, chosen="")["ok"]
        assert bool(state.flags.get("nf_list_copied")) is passed
        assert reputation.get(state, "militia") == (before if passed else before - 4)


def test_the_pin_is_earned_by_the_tinkers_standing_not_a_disposition(flagship) -> None:
    from engine.game.quests import QuestEngine, progress_records

    state = new_state()
    state.arcs_unlocked.append("convergence")
    doors.completed(state, "naming_the_wound")
    doors.at_stage(state, "the_ninth_pin", 1)
    doors.flag(state, "nf_ninth_earned")
    doors.stand(state, "tinker_caravan", 10)
    QuestEngine.evaluate(state)
    assert progress_records(state)["the_ninth_pin"].stage_index == 1     # tinkers 0
    doors.effect(state, type="reputation", faction="tinkers", delta=10)
    QuestEngine.evaluate(state)
    assert progress_records(state)["the_ninth_pin"].stage_index == 2


def test_taking_the_pin_on_its_card_completes_the_quest_and_opens_the_join(flagship) -> None:
    """The Pin and the Join, reached in play: T3's `take_it` grants the pin and writes its flag, the
    quest completes through `QuestEngine.evaluate`, and with the road walked the join's door is dealt."""
    from engine.content import deck as deck_module
    from engine.content import director
    from engine.game.quests import STATUS_COMPLETED, QuestEngine, evaluate_condition, progress_records

    state = new_state()
    state.arcs_unlocked.append("convergence")
    doors.completed(state, "naming_the_wound")
    doors.at_stage(state, "the_ninth_pin", 2)
    _pin_ilya(state)
    doors.stand(state, "tinker_caravan", 10)
    assert director.due(state)[0] == "the_ninth_pin"
    assert director.begin(state, "the_ninth_pin", forced_card="T3_take_it_or_dont")["ok"]
    assert director.resolve(state, chosen="take_it")["ok"]
    QuestEngine.evaluate(state)
    assert progress_records(state)["the_ninth_pin"].status == STATUS_COMPLETED
    assert state.flags.get("nf_ninth_taken")
    assert sum(i.qty for i in state.inventory if i.id == "ninth_pin") == 1
    doors.at_stage(state, "the_heartland_road", 2)
    doors.stand(state, "the_join", 12)
    assert evaluate_condition(state, {"ending": {"eligible": "the_pin_and_the_join"}})
    eligible, rejected = deck_module.eligible_cards(state, deck_module.load_deck("the_join"))
    assert "J1_the_pin" in [c.id for c in eligible], rejected


def test_the_levy_fills_on_its_days_and_forces_the_press_in_the_square(flagship) -> None:
    from engine.content import director
    from engine.game import clocks
    from engine.game.quests import QuestEngine
    from engine.world.world_sim import WorldSim

    state = new_state()
    doors.effect(state, type="awareness", delta=25)
    doors.fed_until(state, 3, 9)
    WorldSim.on_tick(state, hours=0.0, force=["militia_press"])
    QuestEngine.evaluate(state)                                   # records the press as seen
    doors.fed_until(state, 3 + 9, 9)
    assert clocks.value_of(state, "the_levy") == 4                # +1 seen, then days 3, 6, 9
    doors.fed_until(state, 3 + 15, 7)
    assert clocks.value_of(state, "the_levy") == 6
    doors.stand(state, "edgewood_square", 9)
    deck_id, _card, source = director.due(state)
    assert (deck_id, source) == ("the_press", "forced")


def test_the_press_never_schedules_itself(flagship) -> None:
    """Plan decision 4: in the square in its hours, with no levy owed, it is not due."""
    from engine.content import director

    state = new_state()
    doors.stand(state, "edgewood_square", 9)
    assert director.due(state)[0] != "the_press"


def _strike(state):
    """`strike_bargain`'s own two steps: offer, then seal (engine/skills/builtin/scenes.py)."""
    from engine.game import threads

    assert not threads.strike_refusal(state, "seras_bargain")
    threads.seal(state, threads.offer(state, "seras_bargain"))
    return threads.active(state)[-1]["id"]


def test_seras_bargain_strikes_discharges_on_the_wall_and_breaks_on_its_day(flagship) -> None:
    import json

    from engine.game import threads

    state = new_state()
    doors.at_stage(state, "conscription_list", 0)
    doors.stand(state, "millhaven_gate", 9)
    tid = _strike(state)
    doors.stand(state, "millhaven_gate", 23)
    assert threads.discharge(state, tid)["ok"]
    assert state.flags.get("stood_the_wall")
    broken = new_state()
    doors.at_stage(broken, "conscription_list", 0)
    doors.stand(broken, "millhaven_gate", 9)
    tid = _strike(broken)
    doors.fed_until(broken, broken.world_day + 4, 9)
    assert threads.get(broken, tid)["status"] == threads.STATUS_BROKEN
    assert "night on the wall" in json.dumps(threads.get(broken, tid)) + json.dumps(broken.moved)
