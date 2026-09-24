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


# ---------------------------------------------------------------------------
# The Lantern Watch (v0.10, the Law): the stop, the bribe, the smock, and the
# numbers scripts/simulate_law.py measured
# ---------------------------------------------------------------------------


class _Forced:
    """A check result of one chosen degree -- the stop's approaches, one at a time."""

    def __init__(self, degree: str) -> None:
        self.degree = degree
        self.summary = f"forced {degree}"
        self.margin = 0

    def to_dict(self) -> dict:
        return {"degree": self.degree}


@pytest.fixture()
def lantern_lunch():
    """Wickmarket at 14:00: Brask, Tully and Hobb all in the square."""
    from engine.game.clock import set_clock

    registry.activate("hue-and-cry")
    session = SessionStore().create(seed=11, llm_fn=lambda m, **k: "{}")
    state = session.engine.state
    set_clock(state, day=1, hour=14)
    state.location_id = "wickmarket"
    return session


def _stopped(session, monkeypatch, degree: str = "success"):
    from engine.game import encounter

    monkeypatch.setattr("engine.game.checks.resolve", lambda *a, **k: _Forced(degree))
    state = session.engine.state
    encounter.begin(state, "watch_stop")
    assert encounter.active(state)
    return state


def test_the_law_loads_against_the_story(hue) -> None:
    from engine.world import law

    spec = law.load_spec()
    assert spec["arrest"]["encounter"] == "watch_stop"
    assert spec["arrest"]["gaol"] == "lantern_house"
    assert {g["item"] for g in spec["guises"].values() if "item" in g} == {
        "magpie_mask", "porters_smock"}
    # Every public district answers to a watch-house; the three secret places
    # answer to none, on purpose (data/rules/law.yaml).
    for district in PREMISE_DISTRICTS:
        assert law.jurisdiction_of(district), district
    for district in SECRET_DISTRICTS:
        assert law.jurisdiction_of(district) == "", district
    for name in spec["jurisdictions"]:
        assert law.jurisdiction_label(name) != name.replace("_", " ").title(), name


def test_the_stop_offers_all_five_ways_out(lantern_lunch, monkeypatch) -> None:
    from engine.game import encounter
    from engine.game.effects import apply_effect

    state = _stopped(lantern_lunch, monkeypatch)
    apply_effect(state, {"type": "gold", "delta": 10})
    offered = {a["id"] for a in encounter.available_approaches(state)}
    assert offered == {"run", "talk", "bribe", "surrender", "fight"}


def test_a_clean_run_is_a_getaway(lantern_lunch, monkeypatch) -> None:
    from engine.game import encounter
    from engine.world import law

    state = _stopped(lantern_lunch, monkeypatch, "success")
    receipt = encounter.resolve_approach(state, "run")
    assert receipt["ok"] and receipt["outcome"] == "escaped"
    assert not encounter.active(state) and not law.in_custody(state)
    assert state.location_id == "wickmarket"


def test_a_failed_run_is_the_cells(lantern_lunch, monkeypatch) -> None:
    from engine.game import encounter
    from engine.world import law

    state = _stopped(lantern_lunch, monkeypatch, "failure")
    receipt = encounter.resolve_approach(state, "run")
    assert receipt["outcome"] == "arrested"
    assert law.in_custody(state) and state.location_id == "lantern_house"


def test_talk_can_win_waver_or_land_you_in_the_cells(lantern_lunch, monkeypatch) -> None:
    from engine.game import encounter
    from engine.world import law

    state = _stopped(lantern_lunch, monkeypatch, "partial")
    encounter.resolve_approach(state, "talk")
    assert encounter.active(state), "a partial buys one more sentence"
    monkeypatch.setattr("engine.game.checks.resolve", lambda *a, **k: _Forced("success"))
    assert encounter.resolve_approach(state, "talk")["outcome"] == "talked_down"
    assert not law.in_custody(state)

    state = _stopped(lantern_lunch, monkeypatch, "failure")
    encounter.resolve_approach(state, "talk")
    assert law.in_custody(state)


def test_a_bribe_costs_more_the_more_he_has_on_you(lantern_lunch, monkeypatch) -> None:
    """`cost_per_severity`: three crowns a severity of the charge he would lay."""
    from engine.game import encounter
    from engine.world import law

    state = _stopped(lantern_lunch, monkeypatch)
    _file(state, "self", 2)
    assert law.charged_severity(state, "self", "wick") == 2
    state.stats.gold = 5
    assert "bribe" not in {a["id"] for a in encounter.available_approaches(state)}
    state.stats.gold = 7
    offered = {a["id"]: a for a in encounter.available_approaches(state)}
    assert offered["bribe"]["cost_gold"] == 6
    receipt = encounter.resolve_approach(state, "bribe")
    assert receipt["outcome"] == "bribed"
    assert state.stats.gold == 1 and not law.in_custody(state)
    # Five more lifts on file and the same Lantern wants twenty-one.
    state = _stopped(lantern_lunch, monkeypatch)
    _file(state, "self", 5)
    state.stats.gold = 100
    assert {a["id"]: a for a in encounter.available_approaches(state)}["bribe"]["cost_gold"] == 21


def test_surrender_is_the_cells_without_a_roll(lantern_lunch, monkeypatch) -> None:
    from engine.game import encounter
    from engine.world import law

    state = _stopped(lantern_lunch, monkeypatch)
    monkeypatch.setattr("engine.game.checks.resolve", lambda *a, **k: pytest.fail("rolled"))
    encounter.resolve_approach(state, "surrender")
    assert law.in_custody(state) and state.location_id == "lantern_house"


def test_hitting_a_lantern_is_assault_whether_you_win_or_lose(lantern_lunch, monkeypatch) -> None:
    from engine.game import encounter
    from engine.world import law

    state = _stopped(lantern_lunch, monkeypatch, "success")
    encounter.resolve_approach(state, "fight")
    assert not law.in_custody(state)
    assert any(r["deed"] == "assault_watch" and r["jurisdiction"] == "wick"
               and r["precision"] == 1.0 for r in state.law["reports"])
    assert law.wanted_band(state, "self", "wick") == "sought"  # 5 x 1.0 on a clean face

    state = _stopped(lantern_lunch, monkeypatch, "failure")
    encounter.resolve_approach(state, "fight")
    held = law.custody(state)
    # Both assaults (same session) are on the charge sheet: severity 10 is
    # 30 crowns and 10 days uncapped, and the caps hold it to 30 and 3.
    assert held and held["days"] == 3 and held["fine"] == 30, held


def test_the_smock_is_sold_on_the_quay_and_can_be_worn(session) -> None:
    from engine.agents.tool_dispatcher import execute_intent
    from engine.game import intents

    state = session.engine.state
    assert state.location_id == "tallow_docks" and state.world_hour == 8
    receipt = execute_intent({"action": "buy", "target": "npc_dock_mag/porters_smock"},
                             session.engine)
    assert receipt and receipt[0]["result"]["success"], receipt
    verb = intents.find_verb(intents.legal_intents(state), "guise")
    assert verb and "porter" in {t for t, _ in verb.options}


def test_the_mask_is_for_sale_at_marrows(hue) -> None:
    from engine.game import trade

    assert "magpie_mask" in trade.vendor("npc_marrow")["sells"]


def _file(state, guise: str, times: int = 1) -> None:
    from engine.game.effects import apply_effect

    for _ in range(times):
        assert apply_effect(state, {"type": "report", "deed": "pickpocket", "guise": guise,
                                    "jurisdiction": "wick", "precision": 1.0})["ok"]


def _file_in(state, guise: str, jurisdiction: str) -> None:
    from engine.game.effects import apply_effect

    assert apply_effect(state, {"type": "report", "deed": "pickpocket", "guise": guise,
                                "jurisdiction": jurisdiction, "precision": 1.0})["ok"]


def test_brasks_bribe_loses_your_file_and_the_magpies(hue) -> None:
    """The discharge quashes LINKED reports, in the Wick only -- and the thread bounder keeps it."""
    from engine.game import threads
    from engine.world import law

    state = _city(11)
    state.location_id = "lantern_house"
    _file(state, "self", 3)
    _file(state, "magpie", 2)   # the Watch believes the Magpie is you
    _file(state, "porter", 1)   # a face nobody has tied to you
    _file_in(state, "self", "quay")   # the Quay's drawer is not Brask's
    assert law.wanted_band(state, "self", "wick") == "sought"  # 3 + 2 linked
    sealed = threads.seal(state, threads.offer(state, "brask_bribe"))
    assert sealed["ok"], sealed
    state.stats.gold = 20
    out = threads.discharge(state, sealed["thread"]["id"])
    assert out["ok"], out
    assert state.stats.gold == 8
    assert law.wanted_band(state, "self", "wick") == "unknown"
    assert sorted((r["jurisdiction"], r["guise"]) for r in state.law["reports"]) == [
        ("quay", "self"), ("wick", "porter")]


def test_brask_will_not_lose_a_file_for_an_empty_purse(hue) -> None:
    from engine.game import intents, threads
    from engine.world import law

    state = _city(11)
    state.location_id = "lantern_house"
    _file(state, "self", 4)
    sealed = threads.seal(state, threads.offer(state, "brask_bribe"))
    state.stats.gold = 5
    assert intents.find_verb(intents.legal_intents(state), "discharge") is None
    out = threads.discharge(state, sealed["thread"]["id"])
    assert out["ok"] is False
    assert state.stats.gold == 5 and len(state.law["reports"]) == 4
    assert threads.get(state, sealed["thread"]["id"])["status"] == "active"
    state.stats.gold = 12
    verb = intents.find_verb(intents.legal_intents(state), "discharge")
    assert verb and sealed["thread"]["id"] in {t for t, _ in verb.options}
    assert law.wanted_band(state, "self", "wick") == "sought"


def test_brasks_price_is_named_at_his_desk_and_only_once(session) -> None:
    """Template `requires:` gates the `bargain` verb and the skill; a struck one is not re-offered."""
    import json

    from engine.game import intents, threads
    from engine.game.engine import active_engine
    from engine.skills.builtin.scenes import strike_bargain

    state = session.engine.state
    assert state.location_id == "tallow_docks"

    def offered() -> set:
        verb = intents.find_verb(intents.legal_intents(state), "bargain")
        return {t for t, _ in verb.options} if verb else set()

    assert "brask_bribe" not in offered()
    with active_engine(session.engine):
        refused = json.loads(strike_bargain("brask_bribe"))
        assert refused["ok"] is False and not state.threads
        state.location_id = "lantern_house"
        assert "brask_bribe" in offered()
        struck = json.loads(strike_bargain("brask_bribe"))
        assert struck["ok"] is True
    assert "brask_bribe" not in offered()
    assert threads.offerable(state) == []


def test_the_missing_death_rules_are_warned_about_once(hue, caplog) -> None:
    import logging

    from engine.game import encounter

    with caplog.at_level(logging.WARNING, logger="engine.game.encounter"):
        for _ in range(4):
            assert encounter.load_death_rules() == {}
    assert sum("Death rules missing" in r.getMessage() for r in caplog.records) == 1


#: MEASURED, v0.10.0, scripts/simulate_law.py over 40 seeds x 10 in-game
#: days (the table is in CHANGELOG.md [Unreleased]): careful below `sought` on
#: 100% of seed-days; reckless `wanted` by day 4 on 78% of seeds; reckless
#: arrested at least once on 80%, and a reckless thief who bribes whenever
#: it can on 80% too (bribes cost it 19% of what it lifted); no sentence
#: longer than `arrest.max_days`. The floors and ceilings are asserted here
#: over the FIRST 12 SEEDS -- 83% wanted by day 4, 75% arrested for both --
#: because 40 seeds x 3 policies is a minute of suite time and 12 still
#: separates a tuned Watch from the plan's starting numbers (which gave 0%
#: wanted by day 4 and 100% arrested).
LAW_SEEDS = 12
LAW_DAYS = 10


@pytest.fixture(scope="module")
def measured_law():
    import sys
    from pathlib import Path

    root = str(Path(__file__).resolve().parents[1])
    if root not in sys.path:
        sys.path.insert(0, root)
    from scripts import simulate_law

    # Module-scoped, so it is set up BEFORE conftest's per-test story guard
    # records what was active -- which would then never see this activation
    # and leave Tallowmere's map loaded for the next file. Undone here.
    before = registry.peek()
    registry.activate("hue-and-cry")
    try:
        # Agendas OFF: these bounds are what the thief's own conduct earns
        # from the Watch. With the Magpie on, its robberies land on the
        # thief's name too and a careful thief is `sought` like anyone else
        # -- restated, measured, in `measured_agendas` below (v0.12).
        with simulate_law.agendas_off():
            return {p: simulate_law.measure(p, LAW_SEEDS, LAW_DAYS)
                    for p in simulate_law.POLICIES}
    finally:
        if registry.peek() is not before:
            registry.deactivate()


def test_a_careful_thief_stays_below_sought_most_days(measured_law) -> None:
    assert measured_law["careful"]["below_sought_seed_days"] >= 0.60, measured_law["careful"]


def test_a_reckless_thief_is_wanted_by_day_four(measured_law) -> None:
    assert measured_law["reckless"]["wanted_by_day_4"] >= 0.60, measured_law["reckless"]


def test_a_reckless_thief_is_likely_but_not_certain_to_be_arrested(measured_law) -> None:
    rate = measured_law["reckless"]["runs_with_an_arrest"]
    assert 0.50 <= rate < 0.95, measured_law["reckless"]


def test_bribing_is_not_a_free_pass(measured_law) -> None:
    """The band holds for a thief who pays every Lantern it can afford."""
    report = measured_law["briber"]
    assert report["bribes_per_run"] > 0, report  # the policy really bribed
    assert 0.50 <= report["runs_with_an_arrest"] < 0.95, report


def test_no_sentence_outlasts_the_cap(measured_law, hue) -> None:
    from engine.world import law

    cap = law.load_spec()["arrest"]["max_days"]
    assert cap == 3
    for policy, report in measured_law.items():
        if report["max_days_served"] is not None:
            assert report["max_days_served"] <= cap, (policy, report)


def test_a_sentence_never_kills_and_a_day_is_cheap(measured_law) -> None:
    for policy, report in measured_law.items():
        if report["min_hp_after_sentence"] is not None:
            assert report["min_hp_after_sentence"] > 0, (policy, report)
        # About a hundred people, presence resolved per hour for the rumour
        # pass: measured at under 0.4s for the slowest day. A second is the flag.
        assert report["max_seconds_per_day"] < 1.0, (policy, report)


def test_no_house_is_cased_from_a_cell(hue) -> None:
    """v0.10.0 final fix: `case` was offered to a prisoner at the gaol -- the
    Lantern House's district holds houses, and the verb never asked."""
    from engine.game import intents
    from engine.game.clock import set_clock
    from engine.game.effects import apply_effect
    from engine.world import law

    state = _city(3)
    set_clock(state, day=1, hour=10)
    state.location_id = "tallow_docks"
    _file_in(state, "self", "quay")
    assert apply_effect(state, {"type": "arrest"})["ok"]
    assert law.in_custody(state)
    assert intents.find_verb(intents.legal_intents(state), "case") is None
    apply_effect(state, {"type": "release"})
    assert intents.find_verb(intents.legal_intents(state), "case") is not None


def test_a_deed_inside_a_house_is_filed_with_its_streets_watch(hue) -> None:
    """v0.10.0 final fix: `commit_deed` read `jurisdiction_of`, which knows no
    interior id, so a Lantern who caught you inside a Wick house filed
    nothing. A house answers to its street (`law.jurisdiction_at`)."""
    from engine.game.clock import set_clock
    from engine.world import law

    state = _city(3)
    set_clock(state, day=1, hour=14)
    seen = law.commit_deed(state, "pickpocket", location="wickmarket/some_house",
                           informants=("npc_lantern_1",))
    assert seen == {"witnesses": ["npc_lantern_1"], "reported": True}
    assert [r["jurisdiction"] for r in state.law["reports"]] == ["wick"]


# ---------------------------------------------------------------------------
# v0.11.0: jobs (data/rules/jobs.yaml, scripts/simulate_jobs.py)
# ---------------------------------------------------------------------------


class _JobRoll:
    """What ``jobs._check`` hands back: the three fields a stage reads."""

    def __init__(self, degree: str) -> None:
        self.degree = degree
        self.margin = {"crit_success": 7, "success": 1, "partial": -2, "failure": -8}[degree]

    @property
    def success(self) -> bool:
        return self.degree in ("success", "crit_success")


def _script_rolls(monkeypatch, degree: str) -> None:
    from engine.world import jobs

    monkeypatch.setattr(jobs, "_check", lambda state, skill, band: _JobRoll(degree))


def _walk_job(state, *, turns: int = 20) -> dict:
    """Play the open job's first offered approach at every stage until it closes."""
    from engine.world import jobs

    out: dict = {}
    for _ in range(turns):
        if jobs.active(state) is None:
            return out
        options = jobs.approaches(state)
        out = jobs.resolve_stage(state, options[0][0])
        assert out["ok"] is True, out
    return out


def _scripts_on_path() -> None:
    import sys
    from pathlib import Path

    root = str(Path(__file__).resolve().parents[1])
    if root not in sys.path:
        sys.path.insert(0, root)


def test_hue_and_cry_declares_jobs_against_its_law(hue) -> None:
    from engine.world import jobs, law

    assert jobs.declared()
    spec = jobs.spec()
    assert spec["alarm"]["deed"] == "burglary"
    assert "burglary" in law.load_spec()["deeds"]
    assert set(spec["tools"]) == {"lockpicks", "smoke_pellet"}
    # The Treasury's own stage, and nothing spliced into Vessaline House.
    assert [s["id"] for s in spec["anchors"]["margraves_treasury"]["stages"]] == ["vault_floor"]
    assert "vessaline_manor" not in spec["anchors"]
    assert spec["features"]["bell_floor"]["stage"] == "vault_floor"


def test_every_security_row_in_the_city_does_something_to_a_job(hue) -> None:
    """A security row with no `features` line is text a watch learns and a job
    never feels -- so a new premise type cannot ship inert."""
    from engine.world import jobs, premises

    features = jobs.spec()["features"]
    catalogue = premises.definitions()
    declared: dict[str, str] = {}
    for kind in ("types", "anchors"):
        for owner, spec in catalogue[kind].items():
            for row in spec.get("security") or []:
                declared[str(row["id"])] = owner
    missing = sorted(f"{owner}:{fid}" for fid, owner in declared.items() if fid not in features)
    assert not missing, missing
    inert = sorted(fid for fid, row in features.items()
                   if not (row["shift"] or row["known_shift"] or row["obstacle"]))
    assert not inert, inert
    assert len(declared) == len(features)  # and no line for a row nobody has


def test_the_burglars_kit_is_sold_in_the_snuffs(hue) -> None:
    from engine.game import inventory, trade

    for item in ("lockpicks", "smoke_pellet"):
        assert inventory.value_of(item) > 0, item
        quote = trade.quote(_city(11), "npc_marrow", item, side=trade.BUY)
        assert quote["ok"], (item, quote)
    assert trade.vendor_location("npc_marrow") == "the_snuffs"


def test_a_raised_alarm_brings_the_watch_and_the_stop(hue, monkeypatch) -> None:
    """Every roll failing raises the house; the watch arrives
    `watch_delay_hours` later, the job closes `caught` and the Lantern's stop
    (the Law's arrest scene) opens."""
    from engine.game import encounter
    from engine.game.clock import set_clock
    from engine.world import jobs, premises

    state = _city(3)
    set_clock(state, day=1, hour=23)
    state.location_id = "wickmarket"
    prem = next(p for p in premises.at(state, "wickmarket") if p["tier"] == 1)
    assert jobs.begin(state, prem["id"])["ok"]
    _script_rolls(monkeypatch, "failure")
    raised = False
    out: dict = {}
    for _ in range(10):
        out = jobs.resolve_stage(state, jobs.approaches(state)[0][0])
        job = jobs.active(state)
        raised = raised or bool(job and job.get("raised_at") is not None)
        if out.get("closed"):
            break
    assert raised
    assert out["closed"] is True and out["outcome"] == "caught", out
    assert state.jobs["last"]["outcome"] == "caught"
    assert encounter.active(state) and state.encounter.get("id") == "watch_stop"
    assert jobs.spec()["alarm"]["watch_delay_hours"] == 2
    assert any(r["deed"] == "burglary" for r in state.law.get("reports") or [])


#: MEASURED, v0.11.0, scripts/simulate_jobs.py (CHANGELOG.md [Unreleased]):
#: over 40 seeds careful carried the take out of 93% of tier-1 and 75% of
#: tier-2 jobs and was never caught; blind was caught on 22% / 58%; the
#: prepped Treasury was carried out 20% of the time and the bare one never.
#: Asserted over the FIRST 12 SEEDS (fifteen seconds for every policy), loosely.
JOB_SEEDS = 12


@pytest.fixture(scope="module")
def measured_jobs():
    _scripts_on_path()
    from scripts import simulate_jobs

    # Module-scoped: undone here, for the reason `measured_law` gives.
    before = registry.peek()
    registry.activate("hue-and-cry")
    try:
        # Agendas OFF, for `measured_law`'s reason: `deeds_filed` would count
        # the Magpie's burglaries as the job's. Outcomes barely differ
        # either way (measured, 40 seeds: a point or two of drift, and less
        # haul where the Magpie emptied the house first -- CHANGELOG 0.12.0).
        from scripts.simulate_law import agendas_off

        with agendas_off():
            return {p: simulate_jobs.measure(p, JOB_SEEDS) for p in simulate_jobs.POLICIES}
    finally:
        if registry.peek() is not before:
            registry.deactivate()


def test_a_careful_thief_gets_the_take_out_and_is_not_caught(measured_jobs) -> None:
    """The brief asked for careful CLEAN >= 60% on tier 1-2; the engine's
    degree table caps clean near 30% (a partial is always noise, and a job is
    four rolls) -- measured in data/rules/jobs.yaml's header. What careful
    reliably does is carry the take out and never meet the watch."""
    report = measured_jobs["careful"]["tier_1_2"]
    assert report["carried_out"] >= 0.60, report
    assert report["caught"] <= 0.10, report
    assert report["clean"] > measured_jobs["blind"]["tier_1_2"]["clean"], measured_jobs


def test_a_blind_thief_is_caught_often_enough_to_feel_it(measured_jobs) -> None:
    report = measured_jobs["blind"]["tier_1_2"]
    assert report["caught"] >= 0.20, report


def test_the_treasury_wants_prep_and_tools(measured_jobs) -> None:
    bare = measured_jobs["greedy_bare"]["treasury"]
    prepped = measured_jobs["greedy"]["treasury"]
    assert bare["jobs"] and prepped["jobs"]
    assert bare["carried_out"] == 0.0, bare
    assert 0.0 < prepped["carried_out"] < 0.5, prepped


def test_no_job_takes_the_thief_to_zero_hp(measured_jobs) -> None:
    """HUE & CRY has no death rules until v1.0: a fall costs one hp and that is
    all, so the measurement watches for a run that would have died."""
    for policy, report in measured_jobs.items():
        assert report["min_hp"] is None or report["min_hp"] > 0, (policy, report)


def test_a_careful_job_on_a_fixed_seed_resolves_clean(hue) -> None:
    """Seed 1, the careful policy's second job: cased, lockpicks, the empty
    hour, a flashback -- and every roll a full success. It replays."""
    _scripts_on_path()
    from scripts import simulate_jobs

    first = simulate_jobs.play(1, "careful").jobs[1]
    assert first.outcome == "clean", first
    assert first.alarm == 0 and first.loot_value > 0 and first.prep_at_start > 0, first
    assert simulate_jobs.play(1, "careful").jobs[1] == first


def _silk_row_house(state) -> str:
    """A generated Silk Row house, not a townhouse where the seed has one."""
    from engine.world import premises

    houses = [p for p in premises.at(state, "silk_row") if not p.get("anchor")]
    others = [p for p in houses if p["type"] != "townhouse"]
    return str((others or houses)[0]["id"])


def test_mother_gannets_job_is_struck_in_the_snuffs_and_pays_after_the_house(
    hue, monkeypatch
) -> None:
    """Any house on Silk Row pays -- a counting house as well as a townhouse."""
    from engine.game import threads
    from engine.game.clock import set_clock
    from engine.world import jobs, premises

    state = _city(11)
    set_clock(state, day=1, hour=20)
    state.location_id = "wickmarket"
    assert threads.can_strike(state, "gannet_silk_row") is False
    state.location_id = "the_snuffs"
    assert "gannet_silk_row" in [r["id"] for r in threads.offerable(state)]
    sealed = threads.seal(state, threads.offer(state, "gannet_silk_row"))
    assert sealed["ok"], sealed
    thread_id = sealed["thread"]["id"]
    gold = state.stats.gold

    # Not until a Silk Row house has been carried out of -- and not by a house
    # anywhere else.
    assert threads.discharge(state, thread_id)["ok"] is False
    state.location_id = "wickmarket"
    elsewhere = str(premises.at(state, "wickmarket")[0]["id"])
    assert jobs.begin(state, elsewhere)["ok"]
    _script_rolls(monkeypatch, "success")
    assert _walk_job(state)["outcome"] == "clean"
    assert threads.discharge(state, thread_id)["ok"] is False
    assert state.stats.gold == gold

    state.location_id = "silk_row"
    target = _silk_row_house(state)
    assert jobs.begin(state, target)["ok"]
    closed = _walk_job(state)
    assert closed["outcome"] == "clean", closed
    assert target in jobs.robbed(state)

    paid = threads.discharge(state, thread_id)
    assert paid["ok"], paid
    assert state.stats.gold == gold + 15  # twenty, less the Company's quarter
    assert threads.get(state, thread_id)["status"] == threads.STATUS_DISCHARGED


def test_mother_gannets_job_can_be_done_on_every_seed(hue) -> None:
    """Controller fix: a townhouse-only contract could only break on 7 of the
    first 300 seeds (Silk Row drew none). What the contract reads must exist on
    every one: generated houses on Silk Row, not counting the anchor."""
    from engine.game import threads
    from engine.world import premises

    wants = threads.templates()["gannet_silk_row"]["discharge_requires"]["premise_robbed"]
    for seed in range(300):
        generated, _ = premises.generate(seed)
        matching = [p for p in generated
                    if all(str(p.get(k)) == str(v) for k, v in
                           {"district": wants.get("district"), "type": wants.get("type")}.items()
                           if v is not None)]
        assert matching, seed


def test_mother_gannets_job_left_undone_sours_the_company_quietly(hue, caplog) -> None:
    """Controller fix: the break used to log "Unknown faction" -- the Company
    is now a faction HUE & CRY declares, and breaking logs no warning at all."""
    import logging

    from engine.game import reputation, threads
    from engine.game.clock import set_clock

    assert "honest_company" in reputation.faction_ids()
    state = _city(11)
    set_clock(state, day=1, hour=20)
    state.location_id = "the_snuffs"
    thread_id = threads.seal(state, threads.offer(state, "gannet_silk_row"))["thread"]["id"]
    due = threads.get(state, thread_id)["due_day"]
    set_clock(state, day=due + 1, hour=9)
    with caplog.at_level(logging.WARNING):
        threads.expire_due(state)
    warned = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert not warned, warned
    assert threads.get(state, thread_id)["status"] == threads.STATUS_BROKEN
    assert int(state.reputations.get("honest_company", 0)) == -10
    assert reputation.standing(state, "honest_company") == "neutral"


def test_a_bribed_servant_needs_the_house_watched_not_just_the_street(
    hue, monkeypatch
) -> None:
    """
    Final review M3. ``bribed_servant`` asked only ``visited: {district}``:
    walking down the street once bought a servant inside any house on it. It
    asks ``premise_cased`` now -- you watched this house and know its people.
    """
    from engine.game import quests
    from engine.game.clock import set_clock
    from engine.game.effects import apply_effect
    from engine.world import jobs, premises

    def at_the_inside(cased: bool):
        state = _city(11)
        state.location_id = "wickmarket"
        set_clock(state, day=1, hour=12)
        quests.QuestEngine.observe(state)  # the district is visited either way
        pid = next(str(p["id"]) for p in premises.at(state, "wickmarket")
                   if not p.get("anchor"))
        if cased:
            assert premises.case(state, pid)["ok"] is True
        set_clock(state, day=1, hour=23)
        apply_effect(state, {"type": "job_prep", "delta": 3})
        state.stats.gold = 50
        assert jobs.begin(state, pid)["ok"] is True
        _script_rolls(monkeypatch, "success")
        for _ in range(6):
            if jobs.current_stage(state) == "inside":
                break
            jobs.resolve_stage(state, jobs.approaches(state)[0][0])
        assert jobs.current_stage(state) == "inside"
        return jobs.legal_flashbacks(state)

    assert "bribed_servant" not in at_the_inside(cased=False)
    assert "bribed_servant" in at_the_inside(cased=True)


def test_mother_gannets_job_is_not_paid_by_a_robbery_that_came_first(
    hue, monkeypatch
) -> None:
    """
    Final review M4. ``discharge_requires`` reads "a Silk Row house has been
    robbed", ever -- so a thief who robbed Silk Row first and struck the
    contract after was paid on the spot. The contract is only struck while
    Silk Row is unrobbed.
    """
    from engine.game import threads
    from engine.game.clock import set_clock
    from engine.world import jobs

    state = _city(11)
    set_clock(state, day=1, hour=20)
    state.location_id = "silk_row"
    assert jobs.begin(state, _silk_row_house(state))["ok"]
    _script_rolls(monkeypatch, "success")
    assert _walk_job(state)["outcome"] == "clean"

    state.location_id = "the_snuffs"
    assert threads.can_strike(state, "gannet_silk_row") is False
    assert "gannet_silk_row" not in [r["id"] for r in threads.offerable(state)]


# ---------------------------------------------------------------------------
# v0.12.0: agendas (data/rules/agendas.yaml, scripts/simulate_agendas.py) --
# the Magpie, Captain Ardane's net, Silas Crook's rise
# ---------------------------------------------------------------------------

CANDIDATES = ("npc_wren", "npc_silas", "npc_imelda")


def _seed_for(candidate: str) -> int:
    """The first seed that makes ``candidate`` the Magpie."""
    from engine.game.state import GameState
    from engine.world import agendas

    return next(s for s in range(200)
                if agendas.role(GameState(rng_seed=s), "magpie") == candidate)


def _candidate_names() -> set[str]:
    """Every name and declared alias of all three candidates."""
    from engine.world import agendas

    mask = agendas.spec()["roles"]["magpie"]["mask"]
    names = {npc_sim.display_name(n) for n in CANDIDATES}
    for aliases in mask["aliases"].values():
        names.update(aliases)
    return names


def test_hue_and_cry_declares_three_agendas_on_hidden_clocks(hue) -> None:
    from engine.game import clocks
    from engine.state.active import active_schema
    from engine.world import agendas, premises

    table = agendas.spec()
    assert sorted(table["agendas"]) == ["ardane_hunt", "silas_ambition", "the_magpie"]
    assert table["roles"]["magpie"]["from"] == list(CANDIDATES)
    assert table["agendas"]["the_magpie"]["owner"] == {"role": "magpie"}
    for name in ("magpie_spree", "ardane_net", "silas_rise"):
        assert active_schema().get(name).visibility == "hidden"
        assert clocks.load_clocks()[name]["label"]
    state = _city(11)
    owners = {premises.owner(state, f"prem_{a}") for a in
              ("gannets_house", "vessaline_manor", "captains_office", "margraves_treasury")}
    assert owners == {"npc_gannet", "npc_imelda", "npc_ardane", "npc_steward_quill"}


def test_every_candidate_can_be_the_magpie_and_roughly_as_often(hue) -> None:
    _scripts_on_path()
    from scripts import simulate_agendas

    roles = simulate_agendas.role_evenness(90)
    assert set(roles) == set(CANDIDATES), roles
    # Measured over 90 seeds: 31 / 35 / 24. Each at least 20 of 90.
    assert min(roles.values()) >= 20, roles


def test_the_magpies_name_is_masked_until_the_flag(hue) -> None:
    from engine.game.effects import apply_effect
    from engine.world import agendas

    for candidate in CANDIDATES:
        state = _city(_seed_for(candidate))
        assert agendas.role(state, "magpie") == candidate
        name = npc_sim.display_name(candidate, state)
        assert agendas.mask_text(state, f"{name} was seen on a roof.") == \
            "The Magpie was seen on a roof."
        for other in CANDIDATES:
            if other != candidate:
                shown = npc_sim.display_name(other, state)
                assert agendas.mask_text(state, f"{shown} was seen.") == f"{shown} was seen."
        assert agendas.revealed(state) == []
        apply_effect(state, {"type": "flag", "flag": "magpie_unmasked"})
        assert agendas.mask_text(state, f"{name} was seen.") == f"{name} was seen."
        assert [row[1] for row in agendas.revealed(state)] == [name]


def test_no_house_name_changes_under_any_candidates_mask(hue) -> None:
    """Four taverns are "The ... Lamplighter": a title-case alias would mask
    "The Lamplighter's Arms" in exactly the seeds Wren is the thief."""
    from engine.game.procgen import generate_world
    from engine.world import agendas

    masks = {}
    for candidate in CANDIDATES:
        masks[candidate] = agendas.masked_terms(_city(_seed_for(candidate)))
    state = _city(0)
    for seed in range(40):
        for prem in generate_world(seed).premises:
            name = str(prem.get("name") or "")
            for candidate, terms in masks.items():
                assert agendas.mask_text(state, name, terms) == name, (seed, candidate, name)


def test_no_agenda_ever_writes_a_candidates_name(hue) -> None:
    """The secret is the link: the signs are impersonal in every seed, so the
    mask is a guard, not the thing keeping the secret."""
    from engine.game.clock import advance_time

    names = _candidate_names()
    for candidate in CANDIDATES:
        state = _city(_seed_for(candidate))
        for _ in range(10):
            advance_time(state, 24.0)
        texts = [str(t["text"]) for t in state.agendas.get("traces") or []]
        assert texts, candidate
        for text in texts:
            assert not any(n in text for n in names), (candidate, text)


def test_the_law_and_jobs_harnesses_really_switch_agendas_off(hue) -> None:
    """The v0.10/v0.11 bounds are measured with agendas off; if the switch
    stopped working they would silently start measuring the Magpie."""
    _scripts_on_path()
    from engine.game.clock import advance_time
    from scripts import simulate_law

    with simulate_law.agendas_off():
        quiet = _city(3)
        for _ in range(3):
            advance_time(quiet, 24.0)
    assert quiet.agendas == {} and not quiet.law.get("reports")
    loud = _city(3)
    for _ in range(3):
        advance_time(loud, 24.0)
    assert loud.agendas.get("hits") and loud.law.get("reports")


def test_the_storyteller_knows_the_city_moves_and_names_no_magpie(hue) -> None:
    from pathlib import Path

    text = (Path(__file__).resolve().parents[1] / "games/hue-and-cry/prompts/storyteller.md"
            ).read_text(encoding="utf-8")
    assert "## THE CITY MOVES WITHOUT YOU" in text
    section = text.split("## THE CITY MOVES WITHOUT YOU", 1)[1].split("\n## ", 1)[0]
    assert "Magpie" in section
    for name in ("Wren", "Silas", "Imelda", "lamplighter", "Dapper"):
        assert name not in section, name


#: MEASURED, v0.12.0, scripts/simulate_agendas.py over 40 seeds x 10 in-game
#: days (CHANGELOG.md [Unreleased]): a player who never steals is `sought` by
#: day 6 on 80% of seeds (median day 5); the Magpie robs 9.8 houses a run;
#: player jobs land on a house the Magpie already robbed 9% (careful) and 7%
#: (reckless) of the time; the captain's net reaches its top band for 60% of
#: reckless runs (median day 9) and for no careful one; Silas moves about 3
#: times; 13-18 traces a run. Asserted over the FIRST 12 SEEDS, loosely.
AGENDA_SEEDS = 12


@pytest.fixture(scope="module")
def measured_agendas():
    _scripts_on_path()
    from scripts import simulate_agendas

    # Module-scoped: undone here, for the reason `measured_law` gives.
    before = registry.peek()
    registry.activate("hue-and-cry")
    try:
        return {p: simulate_agendas.measure(p, AGENDA_SEEDS, 10)
                for p in simulate_agendas.POLICIES}
    finally:
        if registry.peek() is not before:
            registry.deactivate()


def test_a_player_who_never_steals_is_sought_for_the_magpies_work(measured_agendas) -> None:
    report = measured_agendas["idle"]
    assert report["sought_by_day_6"] >= 0.60, report
    assert report["first_noticed_median_day"] <= 3, report


def test_the_magpie_robs_most_nights_and_rarely_where_you_do(measured_agendas) -> None:
    for policy, report in measured_agendas.items():
        assert 7 <= report["magpie_hits_per_run"] <= 11, (policy, report)
    for policy in ("careful", "reckless"):
        report = measured_agendas[policy]
        assert report["player_jobs"] > 0, report
        assert report["magpie_collision_rate"] < 0.15, (policy, report)


def test_the_captains_net_closes_on_the_reckless_first(measured_agendas) -> None:
    reckless, careful = measured_agendas["reckless"], measured_agendas["careful"]
    assert reckless["ardane"]["utmost"]["reached"] >= 0.30, reckless["ardane"]
    assert reckless["ardane"]["strong"]["median_day"] <= 8, reckless["ardane"]
    assert careful["ardane"]["utmost"]["reached"] <= 0.10, careful["ardane"]
    assert careful["per_day"][-1]["ardane_mean"] < reckless["per_day"][-1]["ardane_mean"]


def test_silas_works_the_company_and_the_signs_stay_few(measured_agendas) -> None:
    for policy, report in measured_agendas.items():
        assert 1 <= report["silas_moves_per_run"] <= 5, (policy, report)
        assert report["company_standing_mean"] < 0, (policy, report)
        # Traces are never pruned; ten days leave well under two dozen.
        assert report["traces_max"] <= 25, (policy, report)


def test_with_the_magpie_on_a_careful_thief_is_sought_like_anyone(measured_agendas) -> None:
    """RESTATED from v0.10's `test_a_careful_thief_stays_below_sought_most_days`
    (100% of seed-days below `sought`, measured with agendas off and still
    asserted that way above). With the Magpie on, its robberies land on the
    thief's name, and careful measures 39% of seed-days below `sought` over
    this module's 12 seeds (AGENDA_SEEDS) -- the same as a player who never
    steals at all (40%, 12 seeds). The CHANGELOG's 40% vs 42% is the 40-seed
    harness run. Either way the careful thief's own lifts add nothing the
    Watch notices. A reckless one stands out from both."""
    idle, careful = measured_agendas["idle"], measured_agendas["careful"]
    reckless = measured_agendas["reckless"]
    assert abs(careful["below_sought_seed_days"] - idle["below_sought_seed_days"]) <= 0.10
    assert reckless["below_sought_seed_days"] < careful["below_sought_seed_days"]


# ---------------------------------------------------------------------------
# v0.12.0 final fix: where a player's job meets an agenda's robbery
# ---------------------------------------------------------------------------


def _job_draws(state) -> int:
    from engine.game.rng import JOB

    return int(state.rng_counters.get(JOB, 0))


def _walk_to_the_score(state) -> dict:
    """Play the open job up to and including its score; the score's receipt."""
    from engine.world import jobs

    for _ in range(20):
        stage = jobs.current_stage(state)
        out = jobs.resolve_stage(state, jobs.approaches(state)[0][0])
        assert out["ok"] is True, out
        if stage == "score" and out["advanced"]:
            return out
    raise AssertionError("never reached the score")


def test_a_house_the_magpie_emptied_yields_nothing_at_the_score(hue, monkeypatch) -> None:
    """
    Final fix A. The Magpie robbed the house first (``agenda_hit``); the player
    may still burgle it (the thief need not know), but the strongroom is bare:
    the score's receipt says ``emptied``, draws nothing and spends no JOB draw
    on loot -- and the job still counts as done (``jobs.robbed``), so a clean
    close is a robbery like any other. The narrator is told, in words.
    """
    from engine.agents import prompts
    from engine.game.clock import set_clock
    from engine.game.effects import apply_effect
    from engine.world import jobs

    _script_rolls(monkeypatch, "success")
    state = _city(11)
    set_clock(state, day=1, hour=20)
    state.location_id = "silk_row"
    target = _silk_row_house(state)
    hit = apply_effect(state, {"type": "agenda_hit", "agenda": "the_magpie",
                               "premise": target, "hour": 2})
    assert hit["ok"], hit

    assert jobs.begin(state, target)["ok"], "burgle stays allowed on an emptied house"
    before = _job_draws(state)
    score = _walk_to_the_score(state)
    assert score["emptied"] is True, score
    assert score["loot"] == [], score
    assert _job_draws(state) == before, "no JOB draw for loot that is not there"
    worded = prompts.summarise_receipt({"skill": "job_stage", "result": score})
    assert "already" in worded and "bare" in worded, worded
    assert "already bare" in prompts.job_block(state), prompts.job_block(state)

    pack = len(state.inventory)
    closed = _walk_job(state)
    assert closed["outcome"] == "clean", closed
    assert closed["emptied"] is True and closed["loot"] == [], closed
    assert len(state.inventory) == pack
    assert target in jobs.robbed(state)
    assert "already bare" in prompts.job_block(state)


def test_an_unrobbed_house_still_draws_its_take(hue, monkeypatch) -> None:
    """The control: the same walk on a house nobody emptied draws on JOB."""
    from engine.game.clock import set_clock
    from engine.world import jobs

    _script_rolls(monkeypatch, "success")
    state = _city(11)
    set_clock(state, day=1, hour=20)
    state.location_id = "silk_row"
    assert jobs.begin(state, _silk_row_house(state))["ok"]
    before = _job_draws(state)
    score = _walk_to_the_score(state)
    assert not score.get("emptied"), score
    assert score["loot"] and _job_draws(state) == before + 1, score


def test_gannets_contract_completes_on_a_house_the_magpie_emptied(hue, monkeypatch) -> None:
    """The job was done -- the house was entered and the take went out, empty-
    handed or not -- so Mother Gannet's Silk Row contract pays."""
    from engine.game import threads
    from engine.game.clock import set_clock
    from engine.game.effects import apply_effect
    from engine.world import jobs

    _script_rolls(monkeypatch, "success")
    state = _city(11)
    set_clock(state, day=1, hour=20)
    state.location_id = "the_snuffs"
    thread_id = threads.seal(state, threads.offer(state, "gannet_silk_row"))["thread"]["id"]
    state.location_id = "silk_row"
    target = _silk_row_house(state)
    apply_effect(state, {"type": "agenda_hit", "agenda": "the_magpie",
                         "premise": target, "hour": 2})
    gold = state.stats.gold
    assert jobs.begin(state, target)["ok"]
    assert _walk_job(state)["outcome"] == "clean"
    paid = threads.discharge(state, thread_id)
    assert paid["ok"], paid
    assert state.stats.gold == gold + 15


def _nights_hits(state, premise_id: str) -> list:
    return [h for h in state.agendas.get("hits") or [] if h["premise"] == premise_id]


def _only_candidate_left(seed: int):
    """A city at 23:30 on day 1 where every Magpie candidate but one is robbed."""
    from engine.game.clock import set_clock
    from engine.game.effects import apply_effect
    from engine.world import agendas

    selector = agendas.spec()["agendas"]["the_magpie"]["moves"][0]["select"]
    state = _city(seed)
    set_clock(state, day=1, hour=23)
    pool = agendas.candidates(state, selector)
    target, others = pool[0], pool[1:]
    for premise_id in others:
        apply_effect(state, {"type": "agenda_hit", "agenda": "the_magpie",
                             "premise": premise_id, "hour": 1})
    assert agendas.candidates(state, selector) == [target]
    return state, target, selector


def test_the_magpie_never_robs_the_house_of_the_players_open_job(hue) -> None:
    """
    Final fix B (review I1). With the job's house the only candidate left and
    the job open across 01:00-03:00, the Magpie takes nothing -- and the same
    in one call as in hourly ones (the job opens at a call boundary, so the
    pass reads the same `taken` whichever way the night is cut). Once the job
    closes without the score, the house is fair game again.
    """
    from engine.game.clock import advance_time
    from engine.game.effects import apply_effect
    from engine.world import agendas, jobs

    runs = []
    for cut in (1, 6):
        state, target, selector = _only_candidate_left(3)
        opened = apply_effect(state, {"type": "job_open", "premise": target,
                                      "stages": jobs.stages_for(state, target)})
        assert opened["ok"], opened
        assert agendas.candidates(state, selector) == []
        for _ in range(6 // cut):
            advance_time(state, cut)
        assert jobs.active(state) is not None
        assert _nights_hits(state, target) == [], cut
        runs.append((state.agendas.get("hits"), dict(state.rng_counters)))
    assert runs[0] == runs[1]

    apply_effect(state, {"type": "job_close", "outcome": "aborted", "by": "player"})
    assert agendas.candidates(state, selector) == [target]
    advance_time(state, 24)
    assert len(_nights_hits(state, target)) == 1


def test_the_magpies_beats_name_no_candidates_district(hue) -> None:
    """Final fix E. A beat line on the Magpie's clock is the same in every
    seed; naming Silk Row (Lady Imelda's home) or the Snuffs (Wren's and
    Silas's) points at a candidate the way a name would."""
    from engine.game import clocks
    from engine.game.locations import LOCATIONS
    from engine.world.npc_sim import load_npc_schedules

    table = load_npc_schedules()["npcs"]
    places = set()
    for npc in CANDIDATES:
        name = str(LOCATIONS[table[npc]["home"]]["name"])
        places.add(name[4:] if name.lower().startswith("the ") else name)
    for beat in clocks.load_clocks()["magpie_spree"]["beats"]:
        for place in places:
            assert place.lower() not in beat["text"].lower(), (beat["id"], place)


def test_a_statement_trace_reads_as_where_it_is_left(hue) -> None:
    """Final fix E. ``takes_a_statement`` leaves its sign where the witness saw
    the deed (``where: target``), so it may not describe a watch-house board
    the player is nowhere near."""
    from engine.world import agendas

    move = next(m for m in agendas.spec()["agendas"]["ardane_hunt"]["moves"]
                if m["id"] == "takes_a_statement")
    assert move["trace"]["where"] == "target"
    assert "watch-house" not in move["trace"]["text"], move["trace"]["text"]
