"""HUE & CRY: the skeleton holds its shape before any feature is built on it."""
from __future__ import annotations

import pytest

from engine.games import registry
from engine.game.locations import LOCATIONS
from engine.scenes.default_state import SessionStore
from engine.world import npc_sim

DISTRICTS = ["tallow_docks", "wickmarket", "the_snuffs", "silk_row", "chandlers_rise",
             "lantern_house", "margraves_hill", "gallows_green", "the_undercroft",
             "rooftop_road", "old_bell_tower"]


@pytest.fixture()
def session():
    registry.activate("hue-and-cry")
    return SessionStore().create(seed=11, llm_fn=lambda m, **k: "{}")


def test_the_city_has_its_districts(session) -> None:
    assert set(DISTRICTS) <= set(LOCATIONS)


def test_the_run_starts_on_the_docks(session) -> None:
    assert session.engine.state.location_id == "tallow_docks"


def test_every_hour_somebody_is_somewhere(session) -> None:
    from engine.game.clock import set_clock
    state = session.engine.state
    for hour in range(24):
        set_clock(state, day=1, hour=hour)
        assert any(npc_sim.npcs_at(state, d) for d in DISTRICTS), hour


def test_the_watch_has_watch_roles(session) -> None:
    rows = npc_sim.load_npc_schedules()["npcs"]
    roles = {rows[i]["role"] for i in ("npc_ardane", "npc_brask", "npc_lantern_1")}
    assert roles == {"captain", "sergeant", "watch"}


def _board_the_barge(session, *, hour: int) -> None:
    from engine.game.clock import set_clock
    from engine.game.quests import QuestEngine

    state = session.engine.state
    QuestEngine.evaluate(state, session.ledger)  # the quest offers itself
    set_clock(state, day=1, hour=hour)
    state.flags["nf_boarded_the_evening_barge"] = True
    QuestEngine.evaluate(state, session.ledger)


def test_the_evening_barge_ends_the_story(session) -> None:
    """The one reachable ending, driven through the quest that locks it."""
    from engine.game import endings, epilogue

    _board_the_barge(session, hour=18)

    assert endings.locked(session.engine.state) == "honest_after_all"
    card = epilogue.for_state(session.engine.state)
    assert card is not None and card.to_dict().get("title") == "Honest After All"


def test_the_morning_barge_is_not_the_evening_barge(session) -> None:
    """The hour is part of the stage: saying you boarded at nine ends nothing."""
    from engine.game import endings

    _board_the_barge(session, hour=9)

    assert endings.locked(session.engine.state) != "honest_after_all"


# ---------------------------------------------------------------------------
# Premises: the houses a thief cases (v0.9, spec §3 and §6)
# ---------------------------------------------------------------------------

#: The districts that hold houses. The three secret places hold none: the
#: Undercroft, the Rooftop Road and the Old Bell Tower are ways IN, not
#: addresses, and a premise there would be a door on a map that hides the room.
PREMISE_DISTRICTS = ["tallow_docks", "wickmarket", "the_snuffs", "silk_row",
                     "chandlers_rise", "lantern_house", "margraves_hill",
                     "gallows_green"]
SECRET_DISTRICTS = ["the_undercroft", "rooftop_road", "old_bell_tower"]
PREMISE_TYPES = {"townhouse", "chandlery", "counting_house", "tavern",
                 "warehouse", "temple_house", "manor", "palace_wing"}
ANCHORS = {"vessaline_manor": "silk_row", "margraves_treasury": "margraves_hill",
           "gannets_house": "the_snuffs", "captains_office": "lantern_house"}
#: Types and anchors whose households never all leave at once: a great house
#: is never empty, which is exactly what makes it a job rather than a walk-in.
NEVER_EMPTY = {"manor", "palace_wing", "vessaline_manor", "margraves_treasury"}

#: MEASURED, v0.9.0, across seeds 0-39 (see CHANGELOG [Unreleased]): 637 of
#: 1240 premises (51.4%) have an empty window of at least three hours; the
#: worst single seed is 32.3%. The brief's line is 30%. The floor is the
#: measured aggregate rounded down, so a routine edit that quietly fills the
#: city's empty hours fails here first -- and the per-seed floor stays above
#: the brief's line, so no one unlucky seed ships a city with nowhere to go in.
EMPTY_WINDOW_FLOOR = 0.50
PER_SEED_FLOOR = 0.30
MEASURE_SEEDS = range(40)


def _window_hours(text: str) -> int:
    """Hours in an occupancy intel line, as `premises._occupancy_text` words it."""
    import re

    if text == "empty all day and night":
        return 24
    found = re.fullmatch(r"empty from (\d\d):00 to (\d\d):00", text)
    if not found:
        return 0
    start, end = int(found.group(1)), int(found.group(2))
    return (end - start) % 24


def _city(seed: int):
    from engine.game.procgen import new_game_state

    return new_game_state(seed=seed)


@pytest.fixture()
def hue():
    registry.activate("hue-and-cry")
    yield


def test_every_district_that_holds_houses_holds_three(hue) -> None:
    from engine.world import premises

    state = _city(11)
    for district in PREMISE_DISTRICTS:
        assert len(premises.at(state, district)) >= 3, district
    for district in SECRET_DISTRICTS:
        assert premises.at(state, district) == [], district


def test_every_anchor_stands_in_its_district(hue) -> None:
    from engine.world import premises

    state = _city(11)
    anchors = {p["type"]: p["district"] for p in state.procgen.premises if p["anchor"]}
    assert anchors == ANCHORS
    for anchor_id in ANCHORS:
        assert premises.spec(anchor_id)["label"]


def test_all_eight_types_are_authored(hue) -> None:
    from engine.world import premises

    loaded = premises._load()
    assert set(loaded["types"]) == PREMISE_TYPES
    for type_id, spec in loaded["types"].items():
        assert spec["label"], type_id
        assert len(spec.get("secrets") or []) >= 4, type_id


def test_great_houses_are_never_empty(hue) -> None:
    from engine.world import premises

    state = _city(11)
    for prem in state.procgen.premises:
        if prem["type"] in NEVER_EMPTY:
            assert premises._occupancy_text(state, prem) == "never empty", prem["name"]


def test_most_houses_have_an_hour_to_go_in(hue) -> None:
    """At least the measured share of houses stand empty for three hours running."""
    from engine.world import premises

    total = windowed = 0
    for seed in MEASURE_SEEDS:
        state = _city(seed)
        here = [
            _window_hours(premises._occupancy_text(state, prem)) >= 3
            for prem in state.procgen.premises
        ]
        assert sum(here) / len(here) >= PER_SEED_FLOOR, (seed, sum(here), len(here))
        total += len(here)
        windowed += sum(here)
    assert windowed / total >= EMPTY_WINDOW_FLOOR, f"{windowed}/{total}"


def test_every_loot_and_purse_item_exists_and_is_worth_something(hue) -> None:
    from engine.game import inventory
    from engine.world import premises, thievery

    items = inventory.load_items()
    loaded = premises._load()
    named: set[str] = set()
    for type_id, spec in loaded["types"].items():
        for rows in spec["loot"].values():
            for row in rows:
                named.add(str(row["item_id"]))
    for spec in loaded["anchors"].values():
        named.update(spec["loot"])
    for rows in thievery.load_spec()["purses"].values():
        named.update(str(r["item_id"]) for r in rows if "item_id" in r)
    missing = sorted(i for i in named if i not in items)
    assert not missing, missing
    worthless = sorted(i for i in named if inventory.value_of(i) <= 0)
    assert not worthless, worthless


def test_a_signet_is_a_named_piece(hue) -> None:
    from engine.game import inventory

    assert "named" in inventory.tags_of("merchants_signet")


def test_both_fences_buy_hot_goods(hue) -> None:
    from engine.game import trade
    from engine.game.effects import apply_effect
    from engine.world import thievery

    from engine.game.clock import set_clock

    state = _city(11)
    apply_effect(state, {"type": "item", "item_id": "merchants_signet", "qty": 1,
                         "stolen_from": {"whom": "gen_x", "where": "silk_row"}})
    assert thievery.heat(state, "merchants_signet") == "hot"
    paid: dict[str, int] = {}
    # At an hour each one's SCHEDULE has her at the counter and awake -- the
    # static counter alone would pass for a fence who is asleep upstairs.
    for fence, counter, hour in (("npc_pell_hollis", "wickmarket", 10),
                                 ("npc_marrow", "the_snuffs", 19)):
        assert trade.vendor(fence)["fence"] is True
        assert trade.vendor_location(fence) == counter
        set_clock(state, day=1, hour=hour)
        state.location_id = counter
        assert fence in trade.vendors_at(counter, state=state), (fence, hour)
        quote = trade.quote(state, fence, "merchants_signet", side=trade.SELL)
        assert quote["ok"], quote
        assert quote["fence"] is True and quote["unit_kind"] == "hot"
        assert quote["unit_price"] > 0, quote
        paid[fence] = quote["unit_price"]
    # The melter pays more for a crest than the shopkeeper: by morning it has
    # no crest on it. That difference is why the city has two fences.
    assert paid["npc_marrow"] > paid["npc_pell_hollis"], paid


def test_money_is_counted_in_crowns(hue) -> None:
    from engine.game import trade

    assert trade.currency_label(12) == "12 cr"


def test_every_premise_type_has_an_art_subject(hue) -> None:
    import yaml
    from pathlib import Path

    doc = yaml.safe_load(
        (Path(__file__).resolve().parents[1] / "games" / "hue-and-cry" / "data"
         / "art" / "subjects.yaml").read_text(encoding="utf-8")
    )
    for type_id in PREMISE_TYPES:
        entry = doc["locations"].get(f"premise_{type_id}")
        assert entry and entry["subject"], type_id
        assert {"day", "night"} <= set(entry["times"]), type_id


# ---------------------------------------------------------------------------
# Review round 1 (v0.9.0 T8): names that misread, pieces that exist twice,
# secrets that rewrite the spine
# ---------------------------------------------------------------------------

#: Callings in the broad tavern pool that are not candle-workshop crafts. A
#: chandlery signed "Bargeman" or a palace window named for porters is the
#: misread the `craft` pool exists to prevent.
_NOT_CRAFTS = ("Bargeman", "Porter", "Snuffer", "Lamplighter", "Fat-Boiler",
               "Tallow-Renderer")


def test_signs_read_as_the_house_they_hang_on(hue) -> None:
    import re

    from engine.world import premises

    crafts = set(premises._load()["pools"]["craft"])
    assert not crafts & set(_NOT_CRAFTS)
    for seed in MEASURE_SEEDS:
        prems = _city(seed).procgen.premises
        margravines = [p for p in prems if "Margravine" in p["name"]]
        assert len(margravines) <= 1, (seed, [p["name"] for p in margravines])
        for prem in margravines:
            assert prem["name"] == "the late Margravine's Apartments", prem["name"]
        for prem in prems:
            if prem["type"] in {"chandlery", "palace_wing"}:
                for word in _NOT_CRAFTS:
                    assert word not in prem["name"], (seed, prem["name"])
            if prem["name"].startswith("the Wing of the "):
                # "{craft}s' Window": every craft noun takes a plain -s.
                found = re.fullmatch(r"the Wing of the (.+)s' Window", prem["name"])
                assert found and found.group(1) in crafts, prem["name"]


def test_a_one_of_a_kind_piece_is_in_one_place(hue) -> None:
    """The Everflame Prism exists once: in the Treasury, and nowhere else."""
    from engine.world import premises

    loaded = premises._load()
    for type_id, spec in loaded["types"].items():
        for rows in spec["loot"].values():
            assert all(r["item_id"] != "everflame_prism" for r in rows), type_id
    holders = [a for a, s in loaded["anchors"].items() if "everflame_prism" in s["loot"]]
    assert holders == ["margraves_treasury"]
    for seed in range(10):
        prems = _city(seed).procgen.premises
        assert sum(p["loot"].count("everflame_prism") for p in prems) == 1, seed


def test_no_house_secret_rewrites_the_everflame(hue) -> None:
    """The Everflame has never once gone out (prompts/storyteller.md)."""
    import re

    from engine.world import premises

    loaded = premises._load()
    specs = list(loaded["types"].values()) + list(loaded["anchors"].values())
    for spec in specs:
        for secret in spec.get("secrets") or []:
            text = str(secret["text"]).lower()
            if "everflame" in text:
                assert not re.search(r"went out|gone out|relit|extinguish", text), secret["id"]


def test_vessalines_secret_gives_imelda_no_motive(hue) -> None:
    """The seed picks the real Magpie; static content must not lean on one suspect."""
    from engine.world import premises

    text = premises.spec("vessaline_manor")["secrets"][0]["text"].lower()
    for word in ("imelda", "debt", "mortgage", "owes", "ruin"):
        assert word not in text, word


def test_everybody_in_a_household_sleeps(hue) -> None:
    from engine.world import premises

    loaded = premises._load()
    for owner, spec in [*loaded["types"].items(), *loaded["anchors"].items()]:
        for member in spec.get("household") or []:
            asleep = [s for s in member.get("routine") or [] if s.get("available") is False]
            assert asleep, (owner, member["role"])
            for slot in asleep:
                assert "asleep" in slot["activity"], (owner, member["role"], slot["activity"])


def test_no_purse_rolls_an_empty_hand(hue) -> None:
    from engine.world import thievery

    for role, rows in thievery.load_spec()["purses"].items():
        for row in rows:
            if "gold" in row:
                assert row["gold"][0] >= 1, role
