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
    """A wage earned on the quay first (since v0.17 the barge takes only a
    thief who has earned Honest After All), then aboard at ``hour`` the
    next day."""
    from engine.game.clock import set_clock
    from engine.game.quests import QuestEngine

    state = session.engine.state
    QuestEngine.evaluate(state, session.ledger)  # the quest offers itself
    _earn_an_honest_wage(state)
    set_clock(state, day=state.world_day + 1, hour=hour)
    state.location_id = "tallow_docks"
    state.flags["nf_boarded_the_evening_barge"] = True
    QuestEngine.evaluate(state, session.ledger)


def test_the_evening_barge_ends_the_story(session) -> None:
    """The one reachable ending, driven through the quest that locks it."""
    from engine.game import endings, epilogue

    _board_the_barge(session, hour=18)

    assert endings.locked(session.engine.state) == "honest_after_all"
    card = epilogue.for_state(session.engine.state)
    assert card is not None and card.to_dict().get("title") == "Honest After All"


def test_the_evening_barge_locks_its_ending_by_name(session, monkeypatch) -> None:
    """v0.17: the barge locks `honest_after_all` BY NAME. An id-less lock asks
    `endings.resolve()`, which -- once honest_after_all is a gated, earned
    ending and The Rope the fail-forward -- would hang the thief who stepped
    aboard. `resolve` is made to answer anything else, to prove it is not asked."""
    from engine.game import endings

    monkeypatch.setattr(endings, "resolve", lambda *a, **k: "the_rope")
    _board_the_barge(session, hour=18)
    assert endings.locked(session.engine.state) == "honest_after_all"


def test_every_authored_ending_lock_in_hue_and_cry_names_a_declared_ending() -> None:
    """Lock by name at every authored door (v0.17 constraint): a quest, card,
    set-piece or death that locks an ending says which, and it is one
    endings.yaml declares."""
    from pathlib import Path

    import yaml

    from engine.games.validation import walk

    root = Path(__file__).resolve().parents[1] / "games" / "hue-and-cry"
    endings_doc = yaml.safe_load((root / "data" / "rules" / "endings.yaml").read_text(encoding="utf-8"))
    declared: set[str] = set()
    for class_id, body in (endings_doc.get("classes") or {}).items():
        declared.update(str(e) for e in ((body or {}).get("variants") or {str(class_id): body}))
    locks = []
    for path in sorted((root / "data").rglob("*.yaml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        for node in walk(doc):
            if node.get("type") == "ending_lock":
                locks.append((path.name, node.get("ending")))
    assert locks, "HUE & CRY ships no ending lock at all"
    unnamed = [(name, ending) for name, ending in locks if ending not in declared]
    assert unnamed == [], unnamed


def test_the_morning_barge_is_not_the_evening_barge(session) -> None:
    """The hour is part of the stage: saying you boarded at nine ends nothing."""
    from engine.game import endings

    _board_the_barge(session, hour=9)

    assert endings.locked(session.engine.state) != "honest_after_all"


# ---------------------------------------------------------------------------
# v0.17 Task 2: The Rope -- data/rules/death.yaml and the fail-forward
# ---------------------------------------------------------------------------


def _hanging_fair_is_on(state) -> None:
    """The fair as the calendar raises it (`advance_time` -> `apply_events`),
    on whatever day the test stands on. The event is declared for day 10
    (data/world/schedules.yaml, v0.17 T3); these death tests raise it where
    they are rather than walk ten days, and the fair's own tests (the
    Hanging Fair section, below) walk the clock into the real one."""
    from engine.world.schedules import SimEvent
    from engine.world.world_sim import WorldSim

    day = int(state.world_day)
    WorldSim.apply_events(state, [SimEvent(
        event_id="hanging_fair", day=day, location_id="gallows_green",
        expires_day=day + 1, payload={"text": "Gallows Green is hung with bunting."})])


def _down_to(state, hp: int) -> None:
    from engine.game.effects import apply_effect

    apply_effect(state, {"type": "hp", "delta": hp - int(state.stats.hp)})


def _held_on_the_quay(state) -> None:
    """The opening's third choice: the Lantern's blurred report, then the arrest."""
    from engine.game.effects import apply_effect

    apply_effect(state, {"type": "report", "deed": "pickpocket", "guise": "magpie",
                         "jurisdiction": "quay", "precision": 0.3})
    assert apply_effect(state, {"type": "arrest"})["ok"]


def test_hue_and_cry_ships_death_rules_with_a_respawn_and_the_rope(hue) -> None:
    from engine.game import encounter

    rules = encounter.load_death_rules()
    assert rules["respawn"]["location_id"] == "the_snuffs"
    assert rules["terminal"]["ending"] == "the_rope"
    assert rules["terminal"]["when"] == {
        "all": [{"in_custody": True}, {"event_active": "hanging_fair"}]}


def test_a_thief_who_starves_wakes_in_the_snuffs(session) -> None:
    """Ordinary hp 0 is a setback: the step of Old Nance's, the next morning,
    half a purse lighter, a wound, a charity crust -- and the story goes on."""
    from engine.game.clock import advance_time
    from engine.game.effects import apply_effect

    state = session.engine.state
    apply_effect(state, {"type": "gold", "delta": 10 - int(state.stats.gold)})
    apply_effect(state, {"type": "hunger", "delta": 100})
    _down_to(state, 1)
    day_before = state.world_day
    advance_time(state, 4)

    assert not state.ended
    assert state.location_id == "the_snuffs"
    assert 0 < state.stats.hp <= 8, state.stats.hp
    assert state.stats.gold == 5
    assert state.hunger < 85, state.hunger
    assert any("ankle" in w.text for w in state.wounds), state.wounds
    assert state.world_day >= day_before
    from engine.game import endings

    assert endings.locked(state) == endings.NONE_ID


def test_a_death_in_the_cells_outside_the_fair_wakes_still_held(session) -> None:
    """Owner's ruling (v0.17): a thief who dies in the cells on an ordinary
    day respawns STILL IN CUSTODY -- on the plank bench at the Lantern House,
    the stay going on, the sentence and the fine as they were. Nothing is
    hanged on an ordinary day, and dying is not a way out of the cells
    (death.yaml's `respawn.in_custody`)."""
    from engine.game import encounter, endings
    from engine.world import law

    state = session.engine.state
    _held_on_the_quay(state)
    held = law.custody(state)
    _down_to(state, 0)
    death = encounter.check_death(state)

    assert death and death["died"] and not death["terminal"], death
    assert death["kept_in_custody"] is True
    assert "Lantern House" in death["text"], death["text"]
    assert not state.ended and endings.locked(state) == endings.NONE_ID
    assert law.custody(state) == held
    assert state.location_id == "lantern_house"
    assert state.stats.hp > 0


def test_after_a_death_in_the_cells_the_stay_ends_the_usual_way(session) -> None:
    """The interrogation was dealt once for this stay and is not dealt again
    after the death (the stay never ended); the rest verb is still there in
    the cell (rule 6); and serving the sentence releases as it always does."""
    from engine.content import director
    from engine.game import encounter, intents
    from engine.world import law

    state = session.engine.state
    _held_on_the_quay(state)
    encounter.end(state)
    _play_interrogation(state)
    _down_to(state, 0)
    assert encounter.check_death(state)["kept_in_custody"] is True

    dealt = director.ensure_scene(state)
    assert not dealt and not director.active(state), dealt
    verbs = {v.action: v.targets for v in intents.legal_intents(state)}
    assert "rest" in verbs and "serve" in verbs, verbs
    served = law.serve_sentence(state)
    assert served["ok"] and served["served_out"] is True, served
    assert not law.in_custody(state)


def test_after_a_death_in_the_cells_the_fine_still_buys_the_way_out(session) -> None:
    """The fine stands through a kept respawn: paid (from what the respawn left
    in the purse), the charge is discharged and the thief walks out."""
    from engine.content import director
    from engine.game import encounter, intents
    from engine.game.effects import apply_effect
    from engine.world import law

    state = session.engine.state
    _held_on_the_quay(state)
    fine = int(law.custody(state)["fine"])
    assert fine > 0
    encounter.end(state)
    _play_interrogation(state)
    apply_effect(state, {"type": "gold", "delta": 2 * fine + 2 - int(state.stats.gold)})
    _down_to(state, 0)
    assert encounter.check_death(state)["kept_in_custody"] is True
    assert int(law.custody(state)["fine"]) == fine
    assert not director.ensure_scene(state) and not director.active(state)
    assert "pay_fine" in {v.action for v in intents.legal_intents(state)}

    gold = int(state.stats.gold)
    paid = law.pay_fine(state)
    assert paid["ok"] and paid["paid"] == fine, paid
    assert int(state.stats.gold) == gold - fine
    assert not law.in_custody(state)


def test_the_fair_alone_does_not_hang_a_free_thief(session) -> None:
    from engine.game import encounter

    state = session.engine.state
    _hanging_fair_is_on(state)
    _down_to(state, 0)
    death = encounter.check_death(state)
    assert death and not death["terminal"], death
    assert not state.ended and state.location_id == "the_snuffs"


def test_held_at_the_hanging_fair_a_death_is_the_rope(session) -> None:
    from engine.game import encounter, endings, epilogue
    from engine.world import law

    state = session.engine.state
    _held_on_the_quay(state)
    _hanging_fair_is_on(state)
    _down_to(state, 0)
    death = encounter.check_death(state)

    assert death and death["terminal"] and death["ending"] == "the_rope", death
    assert state.ended and endings.locked(state) == "the_rope"
    assert law.in_custody(state)  # nobody wakes from this one
    card = epilogue.for_state(state)
    assert card is not None and card.title == "The Rope"


def test_the_rope_is_the_fail_forward(hue) -> None:
    """The spec's fail-forward is The Rope, played for the laugh. Honest After
    All is earned since v0.17 Task 5 (its gates: the section below)."""
    from engine.game import endings

    assert endings.fail_forward_id() == "the_rope"
    declared = endings.declared()
    assert {"the_rope", "honest_after_all"} <= set(declared)
    assert not declared["the_rope"].get("requires")
    assert declared["honest_after_all"].get("requires")


def test_the_rope_plays_speak_act_seal_and_shows_its_card(hue) -> None:
    from engine.game import endings, epilogue

    beats = [b["id"] for b in endings.declared()["the_rope"]["beats"]]
    assert beats == ["the_rope_speak", "the_rope_act", "the_rope_seal"]
    for beat in endings.declared()["the_rope"]["beats"]:
        word = beat["id"].rsplit("_", 1)[1].upper()
        assert beat["text"].startswith(f"{word}."), beat["id"]
    row = epilogue.declared()["the_rope"]
    assert row["title"] == "The Rope"
    assert row["card_m"].strip() and row["card_g"].strip()


def test_the_time_line_fits_every_ending(session) -> None:
    """One `time_line_template` serves every ending ({garden_days} is the
    engine's name for the day count): it may not say how the run ended."""
    from engine.game import epilogue

    state = session.engine.state
    for ending_id in epilogue.declared():
        line = epilogue.render(state, ending_id).time_line
        assert "1 day in Tallowmere" in line, (ending_id, line)
        # "back on the evening one" was the barge's ending, told to every ending.
        assert "evening" not in line.lower(), (ending_id, line)


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

#: MEASURED, v0.9.0, across seeds 0-39 (see CHANGELOG [0.9.0]): 637 of
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
        "magpie_mask", "porters_smock", "lamplighters_coat"}
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


def test_brask_takes_no_price_once_his_file_is_gone(hue) -> None:
    """Struck while the Wick held a file; the file went before he was paid
    (the city-wide quash is `ardane_magpie_file`'s first discharge effect).
    Paying him now would cost twelve crowns and quash nothing, so the
    discharge is refused and the thread simply comes due (it has no
    `on_break`)."""
    from engine.game import intents, threads
    from engine.game.effects import apply_effect
    from engine.world import law

    state = _city(11)
    state.location_id = "lantern_house"
    _file(state, "self", 2)
    sealed = threads.seal(state, threads.offer(state, "brask_bribe"))
    assert sealed["ok"], sealed
    tid = sealed["thread"]["id"]
    state.stats.gold = 20
    assert apply_effect(state, {"type": "quash_reports", "guise": "self", "linked": True})["ok"]
    assert law.wanted_band(state, "self", "wick") == "unknown"

    verb = intents.find_verb(intents.legal_intents(state), "discharge")
    assert verb is None or tid not in {t for t, _ in verb.options}
    out = threads.discharge(state, tid)
    assert out["ok"] is False, out
    assert state.stats.gold == 20
    assert threads.get(state, tid)["status"] == "active"


def test_brasks_discharge_asks_for_the_file_as_well_as_the_coin(hue) -> None:
    from engine.game import threads

    gate = threads.templates()["brask_bribe"]["discharge_requires"]
    assert {"min_gold": 12} in gate["all"]
    assert {"filed": {"jurisdiction": "wick", "guise": "self", "linked": True}} in gate["all"]
    # And he still has no on_break: a file lost before payday breaks nothing.
    assert not threads.templates()["brask_bribe"].get("on_break")


def test_brasks_price_is_named_at_his_desk_and_only_once(session) -> None:
    """Template `requires:` gates the `bargain` verb and the skill; a struck one is not re-offered."""
    import json

    from engine.game import intents, threads
    from engine.game.engine import active_engine
    from engine.skills.builtin.scenes import strike_bargain

    state = session.engine.state
    assert state.location_id == "tallow_docks"
    _file(state, "self")   # something in his drawer to lose (`filed`)

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


def _brask_offered(state) -> bool:
    from engine.game import threads

    return "brask_bribe" in {row["id"] for row in threads.offerable(state)}


def test_brask_names_no_price_to_a_clean_record(hue) -> None:
    """Nothing filed in the Wick, nothing to lose: the bribe is not offered, nor struck."""
    from engine.game import threads

    state = _city(11)
    state.location_id = "lantern_house"
    assert not state.law.get("reports")
    assert not threads.can_strike(state, "brask_bribe")
    assert not _brask_offered(state)


def test_a_lift_filed_in_the_wick_opens_brasks_price(hue) -> None:
    from engine.game import threads

    state = _city(11)
    state.location_id = "lantern_house"
    _file(state, "self")
    assert threads.can_strike(state, "brask_bribe")
    assert _brask_offered(state)


def test_the_magpies_file_opens_brasks_price_through_the_link(hue) -> None:
    """The Magpie agenda files against `magpie`; the watch takes her for you."""
    from engine.game import threads
    from engine.world import law

    state = _city(11)
    state.location_id = "lantern_house"
    assert "magpie" in law.same_person(state, "self")
    _file(state, "magpie")
    assert threads.can_strike(state, "brask_bribe")
    assert _brask_offered(state)


def test_another_districts_file_does_not_open_brasks_price(hue) -> None:
    from engine.game import threads

    state = _city(11)
    state.location_id = "lantern_house"
    _file_in(state, "self", "quay")
    _file(state, "porter")   # the Wick, but a face nobody has tied to you
    assert not threads.can_strike(state, "brask_bribe")
    assert not _brask_offered(state)


def test_filed_reads_live_rows_the_way_a_quash_matches_them(hue) -> None:
    """`filed` and `quash_reports` share one row matcher: what one finds, the other loses."""
    from engine.game.effects import apply_effect
    from engine.game.quests import evaluate_condition

    state = _city(11)
    linked = {"filed": {"jurisdiction": "wick", "guise": "self", "linked": True}}
    exact = {"filed": {"jurisdiction": "wick", "guise": "self"}}
    _file(state, "magpie")
    assert evaluate_condition(state, linked)
    assert not evaluate_condition(state, exact)   # exact guise unless `linked`
    assert evaluate_condition(state, {"filed": {"jurisdiction": "wick"}})
    assert not evaluate_condition(state, {"filed": {"jurisdiction": "quay"}})
    # A gate that cannot be answered stays shut.
    assert not evaluate_condition(state, {"filed": {"jurisdiction": "atlantis"}})
    assert not evaluate_condition(state, {"filed": {"jurisdiction": "wick", "guise": "nobody"}})
    assert not evaluate_condition(state, {"filed": {"guise": "self", "linked": True}})
    assert not evaluate_condition(state, {"filed": True})
    assert apply_effect(state, {"type": "quash_reports", "jurisdiction": "wick",
                                "guise": "self", "linked": True})["ok"]
    assert not evaluate_condition(state, linked)   # a lost file is nothing to lose


@pytest.mark.parametrize("blank", [" ", "   ", "\t"])
def test_filed_with_a_blank_jurisdiction_stays_shut(hue, blank: str) -> None:
    """A whitespace jurisdiction is a missing one, not "any jurisdiction":
    it passed the truthiness check and then stripped to no filter at all."""
    from engine.game.quests import evaluate_condition

    state = _city(11)
    _file(state, "self")
    assert not evaluate_condition(state, {"filed": {"jurisdiction": blank}})
    assert not evaluate_condition(state, {"filed": {"jurisdiction": blank, "guise": "self"}})


def test_brasks_gate_is_the_filed_predicates_production_caller(hue) -> None:
    from engine.game import threads

    requires = threads.templates()["brask_bribe"]["requires"]
    assert {"at_location": "lantern_house"} in requires["all"]
    assert {"filed": {"jurisdiction": "wick", "guise": "self", "linked": True}} in requires["all"]


def test_death_rules_load_quietly(hue, caplog) -> None:
    """v0.17: HUE & CRY ships death.yaml, so the "Death rules missing" warning
    it logged once per activation until then is gone (the warn-once guard
    itself is tested on a synthetic story, tests/test_encounter.py)."""
    import logging

    from engine.game import encounter

    with caplog.at_level(logging.WARNING, logger="engine.game.encounter"):
        for _ in range(4):
            assert encounter.load_death_rules()
    assert not any("Death rules missing" in r.getMessage() for r in caplog.records)


#: MEASURED, v0.10.0, scripts/simulate_law.py over 40 seeds x 10 in-game
#: days (the table is in CHANGELOG.md [0.10.0]): careful below `sought` on
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
    served = 0
    for policy, report in measured_law.items():
        if report["min_hp_after_sentence"] is not None:
            assert report["min_hp_after_sentence"] > 0, (policy, report)
        # COUNTED, NOT TIMED (v0.17 T4). A served day costs what its clock
        # advances cost -- every one runs the city's hour -- and HUE & CRY
        # held is cut at midnight and nine (the gallows) plus a meal: three
        # a day, measured. Four is the flag. The 1.0s-a-day guard this
        # replaces sat inside the owner's machine noise (0.7-1.25s between
        # identical runs, v0.17 T3), so it is kept only as a loose backstop.
        if report["max_advances_per_day_served"] is not None:
            served += 1
            assert report["max_advances_per_day_served"] <= 4, (policy, report)
        assert report["max_seconds_per_day"] < 3.0, (policy, report)
    assert served, "no measured policy served a sentence: the count guard guarded nothing"


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


def test_a_harness_run_leaves_the_save_store_untouched(hue, monkeypatch) -> None:
    """T8: every harness run wrote one save per seed into the owner's real
    `data/saves/hue-and-cry` (SessionStore().create's first save) -- tens of
    thousands of runs nobody played, in the load menu's index. A harness is
    a measurement: it keeps nothing. Every harness's player is built on
    simulate_law.Thief, and each one is asserted here, one short day each."""
    _scripts_on_path()
    from engine.persistence import saves
    from scripts import (simulate_acts, simulate_agendas, simulate_endings, simulate_hoard,
                         simulate_jobs, simulate_labour, simulate_law, simulate_scrounge,
                         simulate_streets)

    written: list[str] = []
    real_save = saves.SaveStore.save

    def spy(self, state, **kwargs):
        written.append(str(self.root))
        return real_save(self, state, **kwargs)

    monkeypatch.setattr(saves.SaveStore, "save", spy)
    root = saves.saves_root("hue-and-cry")
    before = sorted(p.name for p in root.iterdir()) if root.is_dir() else []
    with simulate_law.agendas_off():
        simulate_law.play(0, "careful", 1)
        simulate_jobs.Burglar(0, "careful")
        simulate_agendas.measure("idle", 1, 1)
        simulate_labour.play(0, "careful_pell", 1)
        simulate_scrounge.play(0, "mornings", 1)
        simulate_streets.Wanderer(0)
        simulate_hoard.Hoarder(0)
    simulate_acts.play(0, "c", 1)  # agendas on: the spine needs the Magpie
    simulate_endings.Porter(0, "porter", "b")   # v0.17 T8
    after = sorted(p.name for p in root.iterdir()) if root.is_dir() else []
    assert written == [], written
    assert after == before


def test_hue_and_cry_declares_jobs_against_its_law(hue) -> None:
    from engine.world import jobs, law

    assert jobs.declared()
    spec = jobs.spec()
    assert spec["alarm"]["deed"] == "burglary"
    assert "burglary" in law.load_spec()["deeds"]
    assert set(spec["tools"]) == {"lockpicks", "smoke_pellet", "forged_pass"}
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


#: MEASURED, v0.11.0, scripts/simulate_jobs.py (CHANGELOG.md [0.11.0]):
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


def test_a_fall_off_the_roof_at_one_hp_respawns_and_closes_the_job(hue, monkeypatch) -> None:
    """v0.17: a job CAN take the thief to 0 hp -- the roof is the one entry
    that hurts -- and since death.yaml it respawns: the job closes `hurt`, the
    thief wakes on Old Nance's step in the Snuffs, and the story goes on.
    (Until v0.17 this was `test_no_job_takes_the_thief_to_zero_hp`, which
    passed trivially: no measured policy takes the roof.)"""
    from engine.game.clock import set_clock
    from engine.world import jobs, premises

    state = _city(3)
    set_clock(state, day=1, hour=23)
    state.location_id = "wickmarket"
    prem = next(p for p in premises.at(state, "wickmarket") if p["tier"] == 1)
    assert jobs.begin(state, prem["id"])["ok"]
    _script_rolls(monkeypatch, "success")
    assert jobs.resolve_stage(state, "approach")["ok"]
    assert jobs.current_stage(state) == "entry"
    assert "roof" in [a for a, _ in jobs.approaches(state)]
    _down_to(state, 1)
    _script_rolls(monkeypatch, "failure")
    out = jobs.resolve_stage(state, "roof")

    assert out["outcome"] == "hurt", out
    assert jobs.active(state) is None and state.jobs["last"]["outcome"] == "hurt"
    assert not state.ended
    assert state.location_id == "the_snuffs"
    assert state.stats.hp > 0


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
    state.flags["guild_initiated"] = True  # sworn to the Company (v0.16)
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
    state.flags["guild_initiated"] = True  # sworn to the Company (v0.16)
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
    state.flags["guild_initiated"] = True  # sworn to the Company (v0.16)
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
#: days (CHANGELOG.md [0.12.0]): a player who never steals is `sought` by
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
    state.flags["guild_initiated"] = True  # sworn to the Company (v0.16)
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


# ---------------------------------------------------------------------------
# Somewhere to sleep (v0.14, spec §6: flophouse, guild bunks, taverns)
# ---------------------------------------------------------------------------

#: The districts anybody can walk into on turn one (not `secret: true`).
PUBLIC_DISTRICTS = [d for d in DISTRICTS
                    if d not in ("the_undercroft", "rooftop_road", "old_bell_tower")]

REST_KINDS = {"rest_short", "sleep_flophouse", "sleep_guild_bunk", "sleep_tavern",
              "sleep_cell", "sleep_rough"}


def _rest_targets(state) -> list:
    from engine.game import intents

    verb = intents.find_verb(intents.legal_intents(state), "rest")
    return [t for t, _label in (verb.options if verb else ())]


def _held(state) -> None:
    from engine.game.effects import apply_effect
    from engine.world import law

    _file_in(state, "self", "quay")
    assert apply_effect(state, {"type": "arrest"})["ok"]
    assert law.in_custody(state)


def test_tallowmere_has_every_kind_of_bed(hue) -> None:
    from engine.game import survival

    assert REST_KINDS <= set(survival.rest_kinds())


def test_a_rest_verb_is_offered_in_every_district_and_in_the_cells(hue) -> None:
    from engine.game.clock import set_clock

    state = _city(3)
    set_clock(state, day=1, hour=22)
    for district in PUBLIC_DISTRICTS:
        state.location_id = district
        assert "sleep_rough" in _rest_targets(state), district
    state.location_id = "tallow_docks"
    _held(state)
    assert state.location_id == "lantern_house"
    assert {"sleep_cell", "sleep_rough"} <= set(_rest_targets(state))


def test_resting_restores_stamina_in_every_district(hue) -> None:
    from engine.game import survival
    from engine.game.clock import set_clock

    for district in PUBLIC_DISTRICTS:
        state = _city(5)
        set_clock(state, day=1, hour=22)
        state.location_id = district
        state.stats.stamina = 10
        out = survival.rest(state, "sleep_rough")
        assert out["success"] and state.stats.stamina > 10, (district, out)


def test_nothing_gates_sleeping_rough(hue) -> None:
    """Rule 6: not the wanted band, not the cells, not an empty purse, not the
    Company's bad books -- a rough night is always there and always gives
    stamina back."""
    from engine.game import survival
    from engine.game.clock import set_clock

    def rough(state) -> None:
        state.stats.stamina = 5
        assert "sleep_rough" in _rest_targets(state)
        out = survival.rest(state, "sleep_rough")
        assert out["success"] and out["kind"] == "sleep_rough", out
        assert state.stats.stamina > 5

    for reports in (0, 3, 15):  # unknown ... wanted, in the Wickmarket ward
        state = _city(7)
        set_clock(state, day=1, hour=22)
        state.location_id = "wickmarket"
        for _ in range(reports):
            _file_in(state, "self", "wick")
        rough(state)

    for gold, standing in ((0, 0), (0, -100), (40, -100)):
        for district in PUBLIC_DISTRICTS:
            state = _city(7)
            set_clock(state, day=1, hour=22)
            state.location_id = district
            state.stats.gold = gold
            state.reputations["honest_company"] = standing
            rough(state)

    state = _city(7)
    set_clock(state, day=1, hour=10)
    state.location_id = "tallow_docks"
    state.stats.gold = 0
    state.reputations["honest_company"] = -100
    _held(state)
    rough(state)


def test_the_flophouse_costs_coin(hue) -> None:
    from engine.game import survival
    from engine.game.clock import set_clock

    state = _city(9)
    set_clock(state, day=1, hour=22)
    state.location_id = "the_snuffs"
    state.stats.gold = 5
    state.stats.stamina = 10
    out = survival.rest(state, "sleep_flophouse")
    assert out["kind"] == "sleep_flophouse"
    assert out["paid"] >= 1 and state.stats.gold == 5 - out["paid"]
    assert state.stats.stamina == survival.stamina_cap(state)

    # No coin: a doorway instead, never a refusal, and nothing taken.
    state.stats.gold = 0
    out = survival.rest(state, "sleep_flophouse")
    assert out["success"] and out["kind"] == "sleep_rough"
    assert state.stats.gold == 0


def test_the_tavern_rooms_are_on_the_docks_and_in_wickmarket(hue) -> None:
    from engine.game import survival
    from engine.game.clock import set_clock

    for district in ("tallow_docks", "wickmarket"):
        state = _city(9)
        set_clock(state, day=1, hour=22)
        state.location_id = district
        state.stats.gold = 10
        out = survival.rest(state, "sleep_tavern")
        assert out["kind"] == "sleep_tavern" and out["paid"] > 0, district
    state = _city(9)
    state.location_id = "silk_row"
    state.stats.gold = 10
    assert survival.rest(state, "sleep_tavern")["kind"] == "sleep_rough"
    assert state.stats.gold == 10


def test_the_guild_bunk_needs_the_companys_good_opinion(hue) -> None:
    from engine.game import survival
    from engine.game.clock import set_clock

    state = _city(9)
    state.flags["guild_initiated"] = True  # sworn to the Company (v0.16)
    set_clock(state, day=1, hour=22)
    state.location_id = "the_snuffs"
    state.stats.gold = 5
    out = survival.rest(state, "sleep_guild_bunk")
    assert out["kind"] == "sleep_guild_bunk" and state.stats.gold == 5
    assert "paid" not in out

    state.reputations["honest_company"] = -10  # a contract left undone
    out = survival.rest(state, "sleep_guild_bunk")
    assert out["success"] and out["kind"] == "sleep_rough"
    assert state.stats.gold == 5  # soured, it does not quietly buy a flophouse bed


def test_a_prisoner_sleeps_in_the_cells(hue) -> None:
    from engine.game import survival
    from engine.game.clock import set_clock
    from engine.game.effects import apply_effect

    state = _city(4)
    set_clock(state, day=1, hour=10)
    state.location_id = "tallow_docks"
    _held(state)
    state.stats.stamina = 5
    out = survival.rest(state, "sleep_cell")
    assert out["kind"] == "sleep_cell" and state.stats.stamina > 5

    apply_effect(state, {"type": "release"})
    state.location_id = "lantern_house"
    assert survival.rest(state, "sleep_cell")["kind"] == "sleep_rough"


def test_there_is_a_meal_to_buy_morning_and_evening(hue) -> None:
    """Hunger is the engine's (2 an hour); a meal is bought across a counter
    and eaten through `eat`. Dock Mag feeds the quay by day, Pell Hollis's
    shelf of biscuit carries it into the evening."""
    from engine.game import survival, trade

    from engine.game.clock import set_clock

    meals = set((survival.load_rules().get("eat") or {}).get("items") or {})
    for vendor, counter, hour in (("npc_dock_mag", "tallow_docks", 8),
                                  ("npc_pell_hollis", "wickmarket", 20)):
        sold = meals & set(trade.vendor(vendor)["sells"])
        assert sold, f"{vendor} sells nothing the survival rules count as a meal"
        for item in sold:
            state = _city(2)
            set_clock(state, day=1, hour=hour)
            state.location_id = counter
            state.stats.gold = 5
            bought = trade.buy(state, vendor, item)
            assert bought.get("success") or bought.get("ok"), (vendor, item, bought)
            assert state.stats.gold < 5
            state.hunger = 60.0
            assert survival.eat(state, item)["success"], item
            assert state.hunger < 60.0, item


def test_a_rest_note_names_the_place_not_its_id(hue) -> None:
    """A tavern asked for on Silk Row downgrades with a note in prose."""
    from engine.agents.prompts import summarise_receipt
    from engine.game import survival

    state = _city(9)
    state.location_id = "silk_row"
    out = survival.rest(state, "sleep_tavern")
    line = summarise_receipt({"skill": "rest", "result": out})
    for text in (out["text"], line):
        for place in LOCATIONS:
            assert place not in text, (place, text)
    assert str(LOCATIONS["silk_row"]["name"]) in out["text"]


# ---------------------------------------------------------------------------
# Scrounging and the secret ways (v0.14, spec §6)
# ---------------------------------------------------------------------------

#: The streets a thief can scrounge. Not Silk Row, the Hill or the Watch's own
#: house (nobody drops anything there that is not watched), and never a secret
#: place: the forage snapshot names every scroungeable place, and naming one
#: of the three would give it away.
SCROUNGE_DISTRICTS = {"tallow_docks", "wickmarket", "the_snuffs", "gallows_green",
                      "chandlers_rise"}

#: sha256 (first 16 hex) of `generate_world(seed).to_dict()` WITHOUT its
#: `forest` -- the npcs, the households, the buildings and the premises --
#: measured at 4003587, before this story declared procgen templates. The
#: templates add a margin (forage ground and hidden paths) and must not move a
#: single house: premises draw on their own stream, after every PROCGEN draw.
PRE_TEMPLATE_WORLD_DIGESTS = {1: "39b2ee800b66da00", 7: "80177bc06b63a440",
                              42: "c4ec9301b3453a38"}
PRE_TEMPLATE_PREMISES_DIGESTS = {1: "65070778e0010d28", 7: "d0a8e14393f2a60d",
                                 42: "3751ff8b2131f850"}


#: The Hoard pieces an anchor's loot list names (v0.15, see HOARD below).
HOARD_IN_ANCHORS = {"lantern_house_knocker", "swan_salt", "nightingale_comb",
                    "chandlers_loving_cup"}


def _digest(value) -> str:
    import hashlib
    import json

    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()[:16]


def test_the_secret_ways_never_move_a_house(hue, monkeypatch) -> None:
    from engine.game import procgen

    assert procgen.load_templates().get("hidden_path_placements"), "no templates declared"
    for seed in PRE_TEMPLATE_WORLD_DIGESTS:
        world = procgen.generate_world(seed).to_dict()
        assert world["forest"]["hidden_paths"], seed
        # v0.15 added a Magpie's Hoard piece to four anchors' AUTHORED loot
        # lists: content, not a draw. Struck out, the city hashes exactly as
        # it did at 4003587 -- no house moved, which is this test's claim.
        for prem in world["premises"]:
            prem["loot"] = [i for i in prem.get("loot") or [] if i not in HOARD_IN_ANCHORS]
            # v0.16 laid the Magpie's trail (data/premises/clues.yaml): a
            # `clue` field on every premise, drawn on its own CLUES stream
            # after every PREMISES draw. Struck out for the same reason as the
            # Hoard pieces -- it is the one added field, and no house moved.
            assert "clue" in prem, prem["id"]
            prem.pop("clue")
        assert _digest(world["premises"]) == PRE_TEMPLATE_PREMISES_DIGESTS[seed], seed
        world.pop("forest")
        assert _digest(world) == PRE_TEMPLATE_WORLD_DIGESTS[seed], seed

    # And the same claim without a pinned number: the city generated with no
    # templates at all is the city generated with them, bar its margin.
    with_templates = [procgen.generate_world(s).to_dict() for s in (3, 99)]
    monkeypatch.setattr(procgen, "load_templates", lambda: {})
    for seed, world in zip((3, 99), with_templates):
        bare = procgen.generate_world(seed).to_dict()
        assert bare["forest"] == {"forage_nodes": [], "hidden_paths": [], "barrow_dungeon": {}}
        world.pop("forest")
        bare.pop("forest")
        assert world == bare, seed


def test_tallowmere_scrounges_its_streets_and_not_its_secrets(hue) -> None:
    import json

    from engine.game import foraging
    from engine.game.locations import LOCATIONS

    assert foraging.configured()
    assert set(foraging._all_forageable_places()) == SCROUNGE_DISTRICTS
    for seed in (1, 11, 42):
        state = _city(seed)
        for district in SCROUNGE_DISTRICTS:
            assert foraging.nodes_at(state, district), (seed, district)
        # The snapshot is a skill's answer and reaches the model: it lists
        # every scroungeable place, so no secret may be one.
        blob = json.dumps(foraging.snapshot(state))
        for secret in SECRET_DISTRICTS:
            assert secret not in blob, (seed, secret)
            assert str(LOCATIONS[secret]["name"]) not in blob, (seed, secret)


def test_every_scrounged_thing_is_in_the_registry_and_sells(hue) -> None:
    from engine.game import foraging, inventory

    known = inventory.load_items()
    for table in foraging.load_rules()["tables"]:
        for pool in ("common", "uncommon"):
            for row in table.get(pool) or []:
                item = known.get(str(row["item_id"]))
                assert item is not None, (table["id"], row)
                assert int(item.get("value") or 0) > 0, row["item_id"]


def test_every_arrest_shows_the_drain(hue) -> None:
    """Every outcome that ends in the cells reveals the Undercroft -- the
    Lantern's stop and, since v0.14, the night streets' drunk Lantern too."""
    from engine.game import encounter

    arrests: dict[str, int] = {}
    for row in encounter.all_encounters():
        for approach in (row.get("approaches") or {}).values():
            for degree, outcome in (approach.get("outcomes") or {}).items():
                effects = outcome.get("effects") or []
                if any(e.get("type") == "arrest" for e in effects):
                    arrests[row["id"]] = arrests.get(row["id"], 0) + 1
                    assert {"type": "flag", "flag": "location_known:the_undercroft",
                            "value": True} in effects, (row["id"], degree)
    assert arrests.get("watch_stop", 0) >= 4, arrests
    assert arrests.get("drunk_lantern", 0) >= 2, arrests


def test_every_secret_has_a_way_in(hue) -> None:
    """At least one reveal each, and none that waits on content still to come."""
    from engine.game import procgen
    from engine.game.locations import LOCATIONS

    pinned = {str(p.get("leads_to")) for p in procgen.load_templates()["hidden_path_placements"]}
    assert pinned == {"rooftop_road", "the_undercroft", "old_bell_tower"}
    assert LOCATIONS["old_bell_tower"].get("known_when")


#: Small on purpose: the whole table is scripts/simulate_scrounge.py at 40
#: seeds x 10 days (forage.yaml's header). These seeds bound the same claims.
SCROUNGE_SEEDS = 6
SCROUNGE_DAYS = 6
#: What a careful pickpocket earns a day, coin plus goods at a fence
#: (survival.yaml's header, simulate_law). Scrounging must earn less.
CAREFUL_PICKPOCKET_CR_PER_DAY = 1.33
#: A day's hunger at 2 an hour.
HUNGER_PER_DAY = 48.0


@pytest.fixture(scope="module")
def measured_scrounge():
    _scripts_on_path()
    from scripts import simulate_law, simulate_scrounge

    before = registry.peek()
    registry.activate("hue-and-cry")
    try:
        with simulate_law.agendas_off():
            return simulate_scrounge.measure("scrounger", SCROUNGE_SEEDS, SCROUNGE_DAYS)
    finally:
        if registry.peek() is not before:
            registry.deactivate()


def test_scrounging_all_day_earns_less_than_picking_pockets(measured_scrounge) -> None:
    """A living, barely: coin enough for nothing, and less than a careful lift."""
    report = measured_scrounge
    assert 0.3 <= report["cr_per_day"] < CAREFUL_PICKPOCKET_CR_PER_DAY, report
    assert report["value_per_hour"] < 0.6, report


def test_scrounging_all_day_does_not_quite_feed_you(measured_scrounge) -> None:
    """Most of a day's food from twelve hours in the gutters -- never all of it."""
    report = measured_scrounge
    assert 20.0 <= report["food_per_day"] < HUNGER_PER_DAY, report
    assert report["min_hp"] > 0, report
    assert report["runs_with_a_death"] == 0, report  # a respawn hides the 0 (v0.17)


def test_a_scrounger_finds_the_ways_in(measured_scrounge) -> None:
    for secret, row in measured_scrounge["ways_found"].items():
        assert row["share"] >= 0.5, (secret, row)


# ---------------------------------------------------------------------------
# v0.14: honest work, luck and trade (data/tables/labour.yaml, boons.yaml,
# complications.yaml; scripts/simulate_labour.py)
# ---------------------------------------------------------------------------

#: Who hires for each posting, and where they must be standing when a shift
#: starts (data/world/npc_schedules.yaml). Errands have no one employer.
EMPLOYERS = {
    "dock_portering": "npc_dock_mag",
    "candle_dipping": "npc_tobiah",
    "lamplighting": "npc_wren",
}


def _slot(npc_id: str, hour: int) -> dict:
    routine = npc_sim.load_npc_schedules()["npcs"][npc_id]["routine"]
    return next(row for row in routine if hour % 24 in row["hours"])


def _offered_at(job_id: str, hour: int) -> bool:
    from engine.game import economy
    from engine.game.clock import set_clock

    job = economy.get_job(job_id)
    state = _city(3)
    set_clock(state, day=1, hour=hour)
    state.location_id = job["location_id"]
    return any(row["id"] == job_id for row in economy.available(state))


def test_tallowmere_posts_honest_work_on_the_board(hue) -> None:
    from engine.game.clock import set_clock
    from engine.scenes.default_api import notice_board

    state = _city(3)
    set_clock(state, day=1, hour=8)
    state.location_id = "tallow_docks"
    board = notice_board(state)
    assert board["configured"] is True
    assert [n["id"] for n in board["notices"]] == ["dock_portering"]
    assert {e["id"] for e in board["elsewhere"]} == {
        "candle_dipping", "market_errands", "lamplighting"}


def test_every_posting_is_open_only_while_its_employer_is_there(hue) -> None:
    from engine.game import economy

    for job_id, npc_id in EMPLOYERS.items():
        job = economy.get_job(job_id)
        open_hours = [h for h in range(24) if _offered_at(job_id, h)]
        assert open_hours, job_id
        for hour in open_hours:
            slot = _slot(npc_id, hour)
            assert slot["location"] == job["location_id"], (job_id, hour, slot)
            assert slot.get("available", True), (job_id, hour, slot)
    # The two stationary trades end before their masters go home.
    for job_id in ("dock_portering", "candle_dipping"):
        job = economy.get_job(job_id)
        last_start = max(h for h in range(24) if _offered_at(job_id, h))
        end = last_start + int(job["hours"])
        slot = _slot(EMPLOYERS[job_id], end - 1)
        assert slot["location"] == job["location_id"], (job_id, end, slot)


def test_a_posting_out_of_hours_is_refused_in_the_citys_words(hue) -> None:
    from engine.game import economy
    from engine.game.clock import set_clock

    state = _city(3)
    set_clock(state, day=1, hour=3)
    state.location_id = "tallow_docks"
    before = (state.world_clock_hours, state.stats.stamina, state.stats.gold)
    out = economy.work(state, "dock_portering")
    assert out["worked"] is False and "Dock Mag" in out["message"], out
    assert (state.world_clock_hours, state.stats.stamina, state.stats.gold) == before


def test_a_shift_is_worked_through_the_production_channel(session) -> None:
    from engine.agents.tool_dispatcher import execute_intent
    from engine.game import intents

    state = session.engine.state
    assert state.location_id == "tallow_docks" and state.world_hour == 8
    verb = intents.find_verb(intents.legal_intents(state), "work")
    assert verb and [t for t, _ in verb.options] == ["dock_portering"]
    gold = state.stats.gold
    receipt = execute_intent({"action": "work", "target": "dock_portering"},
                             session.engine)[0]["result"]
    assert receipt["worked"] is True and receipt["hours"] == 6, receipt
    assert state.stats.gold == gold + receipt["wage"]


def test_luck_is_tallowmeres_and_pip_is_never_a_boon(hue) -> None:
    from engine.game import checks

    boons = checks._load_table("boons.yaml", "boons")
    complications = checks._load_table("complications.yaml", "complications")
    assert boons and complications
    for row in boons:
        assert "jackdaw" not in row["text"].lower() and "pip" not in row["text"].lower(), row
    for row in complications:
        if "jackdaw" in row["text"].lower():
            assert row["effects"] == [], row  # flavour only: Pip speaks for himself


def test_no_complication_piles_on_the_law_and_luck_only_cools_it(hue) -> None:
    from engine.game import checks

    law_kinds = {"deed", "report", "witness", "arrest", "law_link", "law_guise",
                 "law_last_deed", "track", "job_alarm"}
    for row in checks._load_table("complications.yaml", "complications"):
        assert not {e["type"] for e in row["effects"]} & (law_kinds | {"law_cool"}), row
    for row in checks._load_table("boons.yaml", "boons"):
        assert not {e["type"] for e in row["effects"]} & law_kinds, row


def test_every_boon_and_complication_applies_cleanly(hue) -> None:
    from engine.game import checks
    from engine.game.effects import apply_effects

    for table, key in (("boons.yaml", "boons"), ("complications.yaml", "complications")):
        for row in checks._load_table(table, key):
            state = _city(3)
            state.stats.gold = 3
            receipts = apply_effects(state, row["effects"])
            for receipt in receipts:
                assert receipt.get("ok", True) is not False, (row["id"], receipt)


#: MEASURED, v0.14, scripts/simulate_labour.py over 40 seeds x 10 days
#: (labour.yaml's header, CHANGELOG.md [0.14.0]): an honest porter keeps
#: 97% of days fed and under a roof and saves about 0.2 cr a day, a candle-
#: dipper 89% and the same 0.2; the careful pickpocket keeps 8%. Asserted
#: over 8 seeds x 8 days, loosely.
LABOUR_SEEDS = 8
LABOUR_DAYS = 8
#: What a reckless pickpocket lifts a day, coin plus goods at a fence
#: (survival.yaml's header, simulate_law). Thieving must pay more.
RECKLESS_PICKPOCKET_CR_PER_DAY = 3.50


@pytest.fixture(scope="module")
def measured_living():
    _scripts_on_path()
    from scripts import simulate_labour, simulate_law

    before = registry.peek()
    registry.activate("hue-and-cry")
    try:
        with simulate_law.agendas_off():
            return {p: simulate_labour.measure(p, LABOUR_SEEDS, LABOUR_DAYS)
                    for p in ("porter", "dipper", "careful", "careful_pell")}
    finally:
        if registry.peek() is not before:
            registry.deactivate()


def test_an_honest_day_pays_for_bread_and_a_bed_most_days(measured_living) -> None:
    """Honest After All has to be a life you can actually live -- either way."""
    report = measured_living["porter"]
    assert report["shifts_per_day"] >= 1.8, report  # it really worked
    assert report["kept_days"] >= 0.75, report
    assert report["min_hp"] > 0, report
    assert report["deaths_per_run"] == 0, report  # a respawn hides the 0 (v0.17)
    dipper = measured_living["dipper"]
    assert dipper["shifts_per_day"] >= 1.6, dipper  # day one misses the stalls
    assert dipper["kept_days"] >= 0.6, dipper


def test_an_honest_day_leaves_little_over(measured_living) -> None:
    """Thin: a crown a day saved would make honesty the easy road."""
    for policy in ("porter", "dipper"):
        report = measured_living[policy]
        assert -0.5 < report["saved_per_day"] < 1.0, (policy, report)


def test_thieving_pays_more_than_honest_work(measured_living) -> None:
    for policy in ("porter", "dipper"):
        report = measured_living[policy]
        assert report["earned_per_day"] < RECKLESS_PICKPOCKET_CR_PER_DAY, (policy, report)


def test_honest_work_keeps_you_better_than_careful_purses(measured_living) -> None:
    porter, careful = measured_living["porter"], measured_living["careful"]
    assert porter["kept_days"] > careful["kept_days"] + 0.3, (porter, careful)


#: MEASURED, v0.15 (T7 fix round 2), scripts/simulate_labour.py, 40 seeds,
#: with `--no-credit` controls (CHANGELOG [0.15.0]). Counted in DAYS kept
#: (fed and roofed) per run:
#:   - The careful pickpocket keeps 0.7 over 10 days and 1.0 over 20.
#:   - On Pell's advance it keeps 5.4 and 5.8: +4.7 and +4.8 over the
#:     control. 95% of the advances break.
#:   - The collectors (night, and by day in the fences' districts) meet it
#:     0.5 and 1.2 times a run.
#:   - No fence buys from it: earnings 1.20 v 1.36 cr a day over 10 days.
#: HONESTLY: welshing still beats never borrowing, the gain does not erode
#: between 10 and 20 days, and it is never a living beside an honest
#: porter's 18.4 kept days in 20. Asserted over the fixture's 8 x 8, loosely:
#: the lifeline, the trap, the lower earnings and the gap to the porter.
def test_pells_advance_is_a_lifeline_and_a_trap(measured_living) -> None:
    careful, credit = measured_living["careful"], measured_living["careful_pell"]
    assert credit["credit_struck"] >= 1.0, credit
    assert credit["kept_days"] >= careful["kept_days"] + 0.2, (careful, credit)
    # Purses alone cannot find thirteen crowns by the third day.
    assert credit["credit_broken"] >= 0.6, credit
    # And the break costs it: no fence will buy what it lifts.
    assert credit["earned_per_day"] < careful["earned_per_day"], (careful, credit)
    # Never a better living than honest work.
    assert credit["kept_days"] < measured_living["porter"]["kept_days"] - 0.2, credit


def test_a_welshers_night_streets_are_mostly_the_collectors(session) -> None:
    """The collectors' odds for a night walker, from the engine's own
    formula: at 22:00 on the quay-to-Snuffs street, a welsher on Pell meets
    SOME scene about a quarter of the time, and it is her collectors more
    than half of those (weight 30 against the street's others)."""
    from engine.game import encounter
    from engine.game.clock import set_clock

    state = session.engine.state
    state.flags["welshed_on_pell"] = True
    set_clock(state, day=2, hour=22)
    rows = encounter.eligible(state, "tallow_docks", "the_snuffs")
    weights = {r["id"]: int(r.get("weight", 10)) for r in rows}
    share = weights["pells_collectors"] / sum(weights.values())
    assert share >= 0.5, weights
    assert encounter.trigger_chance(state, "tallow_docks", "the_snuffs") * share >= 0.1


# ---------------------------------------------------------------------------
# v0.14 task 4: the streets at night (data/encounters/streets.yaml)
# ---------------------------------------------------------------------------

#: The scenes a road may hand the player. `watch_stop` is not one: the Law's
#: patrol opens it, and it carries `on_roads: false` so no road ever draws it.
STREET_SCENES = {"cutpurses", "press_gang", "drunk_lantern", "lamplighters_warning",
                 "silas_toughs", "pells_collectors", "marrows_lads",
                 "pells_collectors_by_day", "marrows_lads_by_day"}
#: MEASURED, v0.14 (rules.yaml's header): the per-leg chance for a fresh
#: thief (stealth +2) over every public street is 17.5% on average at 23:00
#: (6% on the Hill, 26% on any street touching the Docks or the Snuffs) and
#: at most 0.5% at noon. Bounds sit just outside the measured numbers.
NIGHT_MEAN_FLOOR = 0.15
NIGHT_MAX_CEILING = 0.30
DAY_MAX_CEILING = 0.02
#: scripts/simulate_streets.py, a street an hour around the clock. 40 seeds x
#: 3 days: a scene on 19.7% of night legs and 0.3% of day legs, min hp 20.
#: Asserted over 6 seeds x 2 days, loosely.
STREET_SEEDS = 6
STREET_DAYS = 2


def _public_legs():
    from engine.game.locations import LOCATIONS

    for src, spec in LOCATIONS.items():
        if spec.get("secret"):
            continue
        for dst in spec.get("connections") or {}:
            if not (LOCATIONS.get(dst) or {}).get("secret"):
                yield src, dst


def _chance_at(session, hour: int, src: str, dst: str) -> float:
    from engine.game import encounter
    from engine.game.clock import set_clock

    state = session.engine.state
    set_clock(state, day=2, hour=hour)
    return encounter.trigger_chance(state, src, dst)


def test_the_streets_ship_their_night_scenes(session) -> None:
    from engine.game import encounter

    rows = {r["id"]: r for r in encounter.all_encounters()}
    assert STREET_SCENES <= set(rows), sorted(rows)
    assert rows["watch_stop"].get("on_roads") is False
    for scene in STREET_SCENES:
        assert rows[scene].get("on_roads", True) is not False, scene


def test_the_lanterns_stop_is_never_drawn_on_a_road(session) -> None:
    from engine.game import encounter
    from engine.game.clock import set_clock

    state = session.engine.state
    for hour in range(24):
        set_clock(state, day=2, hour=hour)
        for src, dst in _public_legs():
            ids = {r["id"] for r in encounter.eligible(state, src, dst)}
            assert "watch_stop" not in ids, (src, dst, hour)
            assert ids <= STREET_SCENES, (src, dst, hour, ids)


def test_every_leg_that_can_draw_has_something_to_draw(session) -> None:
    """A nonzero chance with nothing eligible is a roll that cannot pay off."""
    from engine.game import encounter

    for hour in range(24):
        for src, dst in _public_legs():
            if _chance_at(session, hour, src, dst) > 0.0:
                assert encounter.eligible(session.engine.state, src, dst), (src, dst, hour)


def test_the_secret_ways_are_quiet(session) -> None:
    """The Undercroft, the roofs and the tower are how a thief AVOIDS the streets."""
    from engine.game.locations import LOCATIONS

    for src, spec in LOCATIONS.items():
        for dst, edge in (spec.get("connections") or {}).items():
            if spec.get("secret") or (LOCATIONS.get(dst) or {}).get("secret"):
                assert int(edge.get("danger_dc") or 0) == 0, (src, dst)


def test_night_streets_are_a_real_risk_and_days_mostly_safe(session) -> None:
    """The per-leg chance for a fresh thief (stealth +2), straight from the
    engine's own formula -- the table is in rules.yaml's header."""
    legs = list(_public_legs())
    night = [_chance_at(session, 23, s, d) for s, d in legs]
    noon = [_chance_at(session, 12, s, d) for s, d in legs]
    assert sum(night) / len(night) >= NIGHT_MEAN_FLOOR, night
    assert max(night) <= NIGHT_MAX_CEILING, night
    assert max(noon) <= DAY_MAX_CEILING, noon
    # The waterfront and the Snuffs are worse than the Hill after dark.
    assert (_chance_at(session, 23, "tallow_docks", "the_snuffs")
            > _chance_at(session, 23, "silk_row", "margraves_hill"))


def test_no_street_scene_can_soft_lock(session) -> None:
    """Every road scene has a way out that needs no roll, no coin, no item,
    no hour and no flag -- and taking it ends the scene."""
    from engine.game import encounter
    from engine.game.clock import set_clock

    state = session.engine.state
    rows = {r["id"]: r for r in encounter.all_encounters()}
    gated = ("cost_gold", "cost_per_severity", "requires_item", "requires_flag",
             "requires_time", "requires_phase")
    for scene in sorted(STREET_SCENES):
        free = [key for key, spec in rows[scene]["approaches"].items()
                if spec.get("auto") and not any(spec.get(g) for g in gated)]
        assert free, scene
        set_clock(state, day=2, hour=23)
        state.stats.gold = 0
        encounter.begin(state, scene)
        receipt = encounter.resolve_approach(state, free[0])
        assert receipt["ok"] and receipt["resolved"], (scene, receipt)
        assert not encounter.active(state), scene


def test_no_street_scene_hurts_more_than_three_hp(session) -> None:
    """The streets rob, chase and arrest, and a fight costs a little blood --
    never enough to kill a thief who meets one. (Written before death.yaml;
    since v0.17 a death would respawn, and the line still holds.)"""
    from engine.game import encounter

    for row in encounter.all_encounters():
        if row["id"] not in STREET_SCENES:
            continue
        for key, spec in row["approaches"].items():
            for degree, block in (spec.get("outcomes") or {}).items():
                hp = sum(int(e.get("delta") or 0) for e in block.get("effects") or []
                         if e.get("type") == "hp")
                assert hp >= -3, (row["id"], key, degree)


def test_hitting_a_drunk_lantern_is_still_assault(session, monkeypatch) -> None:
    """Silk Row at ten at night: Lantern Hobb is walking it and sees who did it."""
    from engine.game import encounter
    from engine.game.clock import set_clock
    from engine.world import law

    state = session.engine.state
    set_clock(state, day=2, hour=22)
    state.location_id = "silk_row"
    monkeypatch.setattr("engine.game.checks.resolve", lambda *a, **k: _Forced("success"))
    encounter.begin(state, "drunk_lantern")
    encounter.resolve_approach(state, "fight")
    assert not law.in_custody(state)
    assert any(r["deed"] == "assault_watch" for r in state.law.get("reports") or [])

    monkeypatch.setattr("engine.game.checks.resolve", lambda *a, **k: _Forced("failure"))
    encounter.begin(state, "drunk_lantern")
    encounter.resolve_approach(state, "fight")
    assert law.in_custody(state) and state.location_id == "lantern_house"
    assert state.flags.get("location_known:the_undercroft")


def test_a_drunk_lantern_struck_with_no_watch_on_duty_still_files_it(session, monkeypatch) -> None:
    """
    v0.14 final: the drunk Lantern is no scheduled person, so on a street no
    duty Lantern walks the blow went unfiled. `report_precision` has him tell
    the watch-house himself -- one blurred report, never none.
    """
    from engine.game import encounter
    from engine.game.clock import set_clock
    from engine.world import law, npc_sim

    state = session.engine.state
    set_clock(state, day=2, hour=1)
    state.location_id = "wickmarket"
    real = npc_sim.npcs_at
    roles = set(law.load_spec()["roles"])
    # Nobody of the watch on this street tonight: the struck man is the scene's.
    monkeypatch.setattr(npc_sim, "npcs_at",
                        lambda st, loc: [p for p in real(st, loc) if p.role not in roles])
    monkeypatch.setattr("engine.game.checks.resolve", lambda *a, **k: _Forced("success"))
    encounter.begin(state, "drunk_lantern")
    encounter.resolve_approach(state, "fight")
    reports = [r for r in state.law.get("reports") or [] if r["deed"] == "assault_watch"]
    assert len(reports) == 1, reports
    assert reports[0]["precision"] == 0.6


def test_every_struck_lantern_outcome_reports_itself() -> None:
    """Every `assault_watch` in the street scenes carries the victim's own report."""
    import yaml
    from pathlib import Path

    doc = yaml.safe_load(Path("games/hue-and-cry/data/encounters/streets.yaml").read_text(encoding="utf-8"))
    found = 0
    for scene in doc["encounters"]:
        for approach in (scene.get("approaches") or {}).values():
            for outcome in ((approach or {}).get("outcomes") or {}).values():
                for eff in (outcome or {}).get("effects") or []:
                    if eff.get("type") == "deed" and eff.get("deed") == "assault_watch":
                        found += 1
                        assert eff.get("report_precision") == 0.6, (scene["id"], eff)
    assert found >= 4, found


def test_a_night_street_hands_the_walker_a_scene_through_travel(session) -> None:
    """The production channel: `travel` at night draws a street scene; the
    same number of walks at noon draws next to nothing."""
    from engine.agents.tool_dispatcher import execute_intent
    from engine.game import encounter
    from engine.game.clock import set_clock

    state = session.engine.state

    def walks(hour: int) -> list[str]:
        drawn: list[str] = []
        for n in range(40):
            state.encounter = {}
            state.stats.stamina = state.stats.max_stamina
            set_clock(state, day=2 + n, hour=hour)
            there = "the_snuffs" if state.location_id == "tallow_docks" else "tallow_docks"
            execute_intent({"action": "travel", "target": there}, session.engine)
            assert state.location_id == there
            if encounter.active(state):
                drawn.append(str(state.encounter["id"]))
        return drawn

    state.location_id = "tallow_docks"
    night = walks(23)
    assert len(night) >= 4, night
    assert set(night) <= STREET_SCENES, night
    assert len(walks(12)) <= 2


def test_the_wanderer_meets_the_night_and_not_the_day(hue) -> None:
    """The harness, production channel: a street an hour, day and night."""
    _scripts_on_path()
    from scripts import simulate_streets

    report = simulate_streets.measure(STREET_SEEDS, STREET_DAYS)
    parts = report["by_daypart"]
    assert parts["night"]["rate"] >= 0.12, report
    assert parts["day"]["rate"] <= 0.03, report
    assert parts["night"]["rate"] > parts["dusk"]["rate"], report
    assert report["min_hp"] > 0, report
    assert report["runs_with_a_death"] == 0, report  # a respawn hides the 0 (v0.17)


# -- v0.14 Task 5: factions and the city's memory ----------------------------------

SEVEN_FACTIONS = {"honest_company", "lantern_watch", "chandlers_guild", "market_stalls",
                  "temple_everflame", "margraves_household", "silk_row"}
#: Empty since v0.17: the Temple of the Everflame, the last faction the acts
#: were waiting on, is moved by the Everflame's heart taken (fair_day.yaml,
#: the_last_job.yaml). The Row and the Hill have been moved since v0.15 by a
#: squeeze left uncollected (threads.yaml).
AWAITING_ACTS: set[str] = set()


def _story_yaml(rel: str):
    import yaml
    from pathlib import Path

    return yaml.safe_load(Path("games/hue-and-cry", rel).read_text(encoding="utf-8"))


def _faction_movers() -> set[str]:
    """Every faction some shipped hue-and-cry content moves (labour, boons, effects)."""
    import re
    from pathlib import Path

    moved: set[str] = set()
    for path in Path("games/hue-and-cry/data").rglob("*.yaml"):
        moved.update(re.findall(r"faction:\s*([a-z_]+)", path.read_text(encoding="utf-8")))
    return moved


def test_tallowmere_declares_seven_factions(session) -> None:
    from engine.game import reputation

    assert set(_story_yaml("data/world/factions.yaml")["factions"]) == SEVEN_FACTIONS
    assert set(reputation.faction_ids()) == SEVEN_FACTIONS
    for fid in SEVEN_FACTIONS:
        assert reputation.standing(session.engine.state, fid) == "neutral", fid
        assert reputation.faction_name(fid) != fid, fid  # a name, never the id


def test_striking_a_lantern_costs_the_watchs_good_opinion(session, monkeypatch) -> None:
    from engine.game import encounter, reputation
    from engine.game.clock import set_clock

    state = session.engine.state
    set_clock(state, day=2, hour=22)
    state.location_id = "silk_row"
    before = reputation.get(state, "lantern_watch")
    monkeypatch.setattr("engine.game.checks.resolve", lambda *a, **k: _Forced("success"))
    encounter.begin(state, "drunk_lantern")
    encounter.resolve_approach(state, "fight")
    assert reputation.get(state, "lantern_watch") == before - 10


def test_every_faction_but_the_acts_ones_is_moved_by_something() -> None:
    """A faction nothing moves is the inert shape; since v0.17 every one of the seven is moved."""
    moved = _faction_movers()
    assert SEVEN_FACTIONS - AWAITING_ACTS <= moved, SEVEN_FACTIONS - AWAITING_ACTS - moved
    assert not (moved - SEVEN_FACTIONS), moved - SEVEN_FACTIONS  # no undeclared faction


def test_honest_work_earns_the_employers_good_opinion(session, monkeypatch) -> None:
    from engine.agents.tool_dispatcher import execute_intent
    from engine.game import reputation
    from engine.game.clock import set_clock

    state = session.engine.state
    monkeypatch.setattr("engine.game.checks.resolve", lambda *a, **k: _Forced("success"))
    for day, place, hour, job, faction in (
        (2, "chandlers_rise", 7, "candle_dipping", "chandlers_guild"),
        (3, "wickmarket", 9, "market_errands", "market_stalls"),
        (4, "wickmarket", 18, "lamplighting", "lantern_watch"),
    ):
        before = reputation.get(state, faction)
        state.location_id = place
        set_clock(state, day=day, hour=hour)
        state.stats.stamina = state.stats.max_stamina
        receipt = execute_intent({"action": "work", "target": job}, session.engine)[0]["result"]
        assert receipt.get("worked") is True, (job, receipt)
        assert reputation.get(state, faction) == before + 1, (job, before, reputation.get(state, faction))


def test_the_lore_corpus_is_retrievable(tmp_path) -> None:
    from pathlib import Path

    from engine.lore.manager import reset_lore_manager

    manager = reset_lore_manager(db_path=tmp_path / "hue_lore.db")
    count = manager.ingest_directory(Path("games/hue-and-cry/data/lore"))
    assert count >= 20, count
    hits = manager.search("Everflame crystal lantern palace", limit=3)
    assert hits and any("Everflame" in h.text for h in hits)
    hits = manager.search("Mother Gannet knitting porters", limit=3)
    assert hits and any("Gannet" in h.text for h in hits)


def test_the_hidden_city_is_the_narrators_not_pips(tmp_path) -> None:
    """The secret places live only in gm_secrets chunks: a public-only reader never gets them."""
    from pathlib import Path

    from engine.agents.knowledge import SCOPE_GM, SCOPE_PUBLIC
    from engine.lore.manager import reset_lore_manager

    manager = reset_lore_manager(db_path=tmp_path / "hue_lore.db")
    manager.ingest_directory(Path("games/hue-and-cry/data/lore"))
    for query in ("Undercroft drains grating", "Rooftop Road gutters", "bell tower Green"):
        public = manager.search(query, limit=5, scopes=(SCOPE_PUBLIC,))
        assert not any(name in h.text for h in public
                       for name in ("Undercroft", "Rooftop Road", "Old Bell Tower")), query
        gm = manager.search(query, limit=5, scopes=(SCOPE_PUBLIC, SCOPE_GM))
        assert gm, query


def test_the_lore_never_links_a_candidate_to_the_magpie() -> None:
    """No sentence in the corpus puts a Magpie candidate and the Magpie together."""
    import re
    from pathlib import Path

    names = {"Wren", "Silas", "Imelda", "Vessaline", "Crook", "lamplighter", "Dapper"}
    for path in Path("games/hue-and-cry/data/lore").glob("*.md"):
        for sentence in re.split(r"(?<=[.!?])\s+", path.read_text(encoding="utf-8")):
            if "Magpie" in sentence:
                hit = {n for n in names if n in sentence}
                assert not hit, (path.name, hit, sentence)


def test_work_elsewhere_says_whether_it_is_open_now(session) -> None:
    """v0.14 final: the narrator saw lamplighting as hiring at 08:00, when Wren sleeps."""
    from engine.game import economy
    from engine.game.clock import set_clock

    state = session.engine.state
    state.location_id = "tallow_docks"
    set_clock(state, day=2, hour=8)
    rows = {r["id"]: r for r in economy.snapshot(state)["elsewhere"]}
    assert rows["lamplighting"]["open_now"] is False
    assert rows["candle_dipping"]["open_now"] is True
    set_clock(state, day=2, hour=18)
    rows = {r["id"]: r for r in economy.snapshot(state)["elsewhere"]}
    assert rows["lamplighting"]["open_now"] is True


# ---------------------------------------------------------------------------
# v0.15: the Porters' Hall workshop (data/recipes/workshop.yaml)
# ---------------------------------------------------------------------------

#: recipe id -> (what it makes, how many). One bench, in the Snuffs.
WORKSHOP = {
    "file_lockpicks": ("lockpicks", 1),
    "roll_smoke_pellets": ("smoke_pellet", 2),
    "cut_lamplighters_coat": ("lamplighters_coat", 1),
    "forge_hill_pass": ("forged_pass", 1),
}
#: The counters a thief can buy at without an honest vendor.
FENCES = ("npc_pell_hollis", "npc_marrow")
#: Marrow's price for a set of picks (data/economy.yaml).
MARROWS_PICKS = 15


def _workshop():
    from engine.skills.builtin.mechanics import _load_recipes

    return _load_recipes()


def _fence_price(item_id: str) -> int:
    """The cheapest a fence sells it for, or 0 when no fence does."""
    from engine.game import trade

    state = _city(11)
    prices = [trade.quote(state, npc, item_id, side=trade.BUY) for npc in FENCES
              if item_id in trade.vendor(npc).get("sells", {})]
    return min((int(q["unit_price"]) for q in prices if q["ok"]), default=0)


def _scrounged() -> set[str]:
    from engine.game import foraging

    return {str(row["item_id"]) for table in foraging.load_rules()["tables"]
            for pool in ("common", "uncommon") for row in table.get(pool) or []}


def _per_attempt(recipe: dict, modifier: int = 0) -> dict:
    """What one attempt yields on average: every d20 face through the story's
    own DC and degree table, at the recipe's band (a fed, rested thief at
    `modifier`) -- exact, not sampled."""
    from engine.game import checks
    from engine.skills.builtin.mechanics import _craft_yield

    rules = checks.load_skill_rules()
    _, dc = checks.difficulty_dc(str(recipe["band"]), rules)
    made = salvage = passed = 0.0
    for face in range(1, 21):
        degree = checks.degree_for(face + modifier - dc, rules)
        got = _craft_yield(degree, recipe)
        if degree == "failure":
            salvage += (_fence_price(got["id"]) * got["qty"] if got else 0) / 20
        else:
            passed += 1 / 20
            made += (got["qty"] if got else 0) / 20
    coin = sum(_fence_price(str(i["id"])) * int(i.get("qty", 1)) for i in recipe["inputs"])
    return {"made": made, "passed": passed, "coin": coin,
            "coin_per_unit": (coin - salvage) / made if made else float("inf")}


def test_the_porters_hall_is_the_workshop(hue) -> None:
    recipes = _workshop()
    assert {rid: (r["output"]["id"], int(r["output"].get("qty", 1)))
            for rid, r in recipes.items()} == WORKSHOP
    for rid, recipe in recipes.items():
        assert recipe["station"] == "the_snuffs", rid
        assert recipe["skill"] == "craft", rid


def test_every_recipe_can_be_sourced_by_a_thief(hue) -> None:
    """Every input and tool is scrounged off a street or sold by a fence --
    and each fence, and the gutters, supply at least one of them."""
    from engine.game import trade

    scrounged = _scrounged()
    stocked = {npc: set(trade.vendor(npc).get("sells", {})) for npc in FENCES}
    needed: set[str] = set()
    for recipe in _workshop().values():
        needed |= {str(i["id"]) for i in recipe["inputs"]}
        needed |= {str(t) for t in recipe.get("tools") or []}
    assert needed
    for item in needed:
        assert item in scrounged or any(item in s for s in stocked.values()), item
    assert needed & scrounged
    for npc, stock in stocked.items():
        assert needed & stock, npc


def test_every_recipe_is_craftable_from_what_the_fences_sell(session, monkeypatch) -> None:
    """Buy every input across a fence's counter, walk to the Porters' Hall, and
    the `craft` verb offers all four -- and each one, executed, makes its thing."""
    from engine.agents.tool_dispatcher import execute_intent
    from engine.game import intents, inventory, trade
    from engine.game.clock import set_clock

    state = session.engine.state
    state.stats.gold = 200
    set_clock(state, day=1, hour=18)   # both fences at their counters
    for npc in FENCES:
        state.location_id = trade.vendor_location(npc)
        for recipe in _workshop().values():
            for row in recipe["inputs"]:
                item, qty = str(row["id"]), int(row.get("qty", 1))
                if item not in trade.vendor(npc).get("sells", {}):
                    continue
                while inventory.quantity(state, item) < qty * 2:
                    receipt = execute_intent({"action": "buy", "target": f"{npc}/{item}"},
                                             session.engine)
                    assert receipt and receipt[0]["result"]["success"], (npc, item, receipt)
    state.location_id = "the_snuffs"
    verb = intents.find_verb(intents.legal_intents(state), "craft")
    assert verb is not None and {t for t, _ in verb.options} == set(WORKSHOP)
    monkeypatch.setattr("engine.game.checks.resolve", lambda *a, **k: _Forced("success"))
    for rid, (item, qty) in WORKSHOP.items():
        before = inventory.quantity(state, item)
        receipt = execute_intent({"action": "craft", "target": rid}, session.engine)
        assert receipt and receipt[0]["result"]["ok"], (rid, receipt)
        assert inventory.quantity(state, item) == before + qty, rid


def test_the_workshop_is_not_offered_off_its_bench(session) -> None:
    from engine.game import intents, inventory

    state = session.engine.state
    for recipe in _workshop().values():
        for row in recipe["inputs"]:
            inventory.grant(state, str(row["id"]), int(row.get("qty", 1)))
    state.location_id = "the_snuffs"
    assert intents.find_verb(intents.legal_intents(state), "craft") is not None
    state.location_id = "wickmarket"
    assert intents.find_verb(intents.legal_intents(state), "craft") is None


#: MEASURED, v0.15 (CHANGELOG [0.15.0]): an exact expectation over the
#: d20 at the recipe's band, inputs at the cheapest fence price, a failed
#: attempt's salvage credited at the same price: a set of picks from the
#: bench costs 7.25 crowns against Marrow's 15, and four hours his counter
#: does not. Bounded at 60% of his price, so one input may move a crown.
def test_crafted_lockpicks_cost_less_coin_and_more_hours_than_marrows(hue) -> None:
    from engine.game import trade

    recipe = _workshop()["file_lockpicks"]
    assert _fence_price("lockpicks") == MARROWS_PICKS
    measured = _per_attempt(recipe)
    assert measured["coin_per_unit"] < MARROWS_PICKS * 0.6, measured
    assert float(recipe["hours"]) >= 4
    # And no money loop: a set made from bought wire costs more than any
    # counter in the city pays for one.
    state = _city(11)
    paid = [trade.quote(state, npc, "lockpicks", side=trade.SELL)
            for npc in (*FENCES, "npc_dock_mag")]
    best = max(int(q["unit_price"]) for q in paid if q["ok"])
    assert measured["coin_per_unit"] > best, (measured, best)


def test_no_workshop_recipe_turns_bought_inputs_into_profit(hue) -> None:
    """Anything a thief can make from a fence's stock sells for less than the
    stock cost: the bench saves coin on a tool, it never mints it."""
    from engine.game import trade

    state = _city(11)
    for rid, recipe in _workshop().items():
        measured = _per_attempt(recipe)
        item = str(recipe["output"]["id"])
        paid = [trade.quote(state, npc, item, side=trade.SELL)
                for npc in (*FENCES, "npc_dock_mag")]
        best = max((int(q["unit_price"]) for q in paid if q["ok"]), default=0)
        assert measured["coin_per_unit"] > best, (rid, measured, best)


def test_the_lamplighters_coat_is_a_face_the_watch_files(session) -> None:
    """Wear the coat and a witness files `a lamplighter`, not you."""
    from engine.agents.tool_dispatcher import execute_intent
    from engine.game import intents, inventory
    from engine.game.clock import set_clock
    from engine.world import law

    state = session.engine.state
    assert law.load_spec()["guises"]["lamplighter"]["item"] == "lamplighters_coat"
    inventory.grant(state, "lamplighters_coat", 1)
    verb = intents.find_verb(intents.legal_intents(state), "guise")
    assert verb and "lamplighter" in {t for t, _ in verb.options}
    receipt = execute_intent({"action": "guise", "target": "lamplighter"}, session.engine)
    assert receipt and receipt[0]["result"]["ok"], receipt
    set_clock(state, day=1, hour=14)
    law.commit_deed(state, "pickpocket", location="wickmarket", informants=("npc_lantern_1",))
    filed = state.law["reports"][-1]
    assert filed["guise"] == "lamplighter"
    assert law.guise_label(filed["guise"]) == "a lamplighter"


def _hill_and_row_bands(state) -> dict:
    from engine.game.effects import apply_effect
    from engine.world import jobs, premises

    out = {}
    for district in ("margraves_hill", "silk_row"):
        state.location_id = district
        prem = next(p for p in premises.at(state, district) if not p.get("anchor"))
        assert jobs.begin(state, prem["id"])["ok"], district
        out[district] = {"approach": jobs.band_for(state, "approach"),
                         "door": jobs.band_for(state, "entry", "door"),
                         "window": jobs.band_for(state, "entry", "window"),
                         "score": jobs.band_for(state, "score")}
        assert apply_effect(state, {"type": "job_close", "outcome": "aborted"})["ok"]
    return out


def test_the_forged_pass_opens_the_hill_and_nowhere_else(hue) -> None:
    """A Margrave's Hill pass eases the approach and the door of a Hill house,
    and does nothing at all on Silk Row next door."""
    from engine.game import inventory
    from engine.game.checks import shift_band
    from engine.game.clock import set_clock
    from engine.world import jobs

    assert jobs.spec()["tools"]["forged_pass"]["districts"] == ["margraves_hill"]
    state = _city(11)
    set_clock(state, day=1, hour=23)
    bare = _hill_and_row_bands(state)
    inventory.grant(state, "forged_pass", 1)
    carried = _hill_and_row_bands(state)
    pass_name = inventory.name_of("forged_pass")

    hill, bare_hill = carried["margraves_hill"], bare["margraves_hill"]
    for stage in ("approach", "door"):
        assert hill[stage][0] == shift_band(bare_hill[stage][0], -1), (stage, bare_hill, hill)
        assert pass_name in hill[stage][1], stage
    assert hill["window"] == bare_hill["window"]
    assert hill["score"] == bare_hill["score"]
    assert carried["silk_row"] == bare["silk_row"]


def test_every_counter_offers_all_of_its_stock(session) -> None:
    """The `buy` verb offers at most eight choices at a place and cuts the rest
    (intents._MAX_OPTIONS): a ninth stock row is stock nobody can choose. v0.15
    put both fences at eight; this fails the moment a row falls off."""
    from engine.game import intents, trade
    from engine.game.clock import set_clock

    state = session.engine.state
    state.stats.gold = 500
    for npc in (*FENCES, "npc_dock_mag"):
        hour = 18 if npc != "npc_dock_mag" else 10
        set_clock(state, day=1, hour=hour)
        state.location_id = trade.vendor_location(npc)
        verb = intents.find_verb(intents.legal_intents(state), "buy")
        offered = {t for t, _ in verb.options} if verb else set()
        stock = {f"{npc}/{item}" for item in trade.vendor(npc).get("sells", {})}
        assert stock <= offered, (npc, sorted(stock - offered))


# ---------------------------------------------------------------------------
# The Magpie's Hoard (v0.15): six shines the ballad says were never fenced
# ---------------------------------------------------------------------------

#: Where each piece rests when the city is generated: four in anchors (the
#: same house in every seed), two in secret places, found once by standing
#: there (data/quests/the_magpies_hoard/).
HOARD = {
    "lantern_house_knocker": "captains_office",
    "swan_salt": "margraves_treasury",
    "nightingale_comb": "vessaline_manor",
    "chandlers_loving_cup": "gannets_house",
    "mitre_of_saint_wick": "old_bell_tower",
    "harbourmasters_chain": "the_undercroft",
}
HOARD_FINDS = {"old_bell_tower": "mitre_of_saint_wick",
               "the_undercroft": "harbourmasters_chain"}


def _hoard_row():
    from engine.game import inventory

    return next(r for r in inventory.load_collections() if r.get("id") == "magpies_hoard")


def test_the_hoard_is_six_named_shinies(hue) -> None:
    from engine.game import inventory

    row = _hoard_row()
    assert set(row["items"]) == set(HOARD) and len(row["items"]) == 6
    for piece in HOARD:
        assert {"shiny", "named"} <= set(inventory.tags_of(piece)), piece
        assert inventory.collection_of(piece) == "magpies_hoard", piece
        assert "collect" in inventory.verbs_for(piece), piece


def test_the_hoard_keeps_the_citys_secrets(hue) -> None:
    """Every word of it is readable before any secret place is found, and in
    every seed -- so it names no secret place, and none of the three people
    the seed may make the Magpie."""
    from engine.game import inventory

    row = _hoard_row()
    texts = [str(row.get(k) or "") for k in ("name", "blurb", "reward_text")]
    for piece in HOARD:
        spec = inventory.get_item(piece) or {}
        texts += [str(spec.get("name") or ""), str(spec.get("description") or "")]
    body = " ".join(texts).lower()
    for word in ("undercroft", "rooftop", "bell tower", "wren", "silas", "crook", "imelda"):
        assert word not in body, word


def test_every_hoard_piece_is_placed_in_every_seed(hue) -> None:
    """Across 40 cities: the four anchor pieces sit in their anchor's loot, and
    standing in each secret place finds its piece. (The Magpie's agenda may
    still rob an anchor before the thief does -- a piece reachable at the
    start, not guaranteed at the end.)"""
    from engine.game import inventory
    from engine.game.quests import QuestEngine

    for seed in range(40):
        state = _city(seed)
        loot = {str(p["id"]): set(p.get("loot") or []) for p in state.procgen.premises}
        for piece, where in HOARD.items():
            if where in ANCHORS:
                assert piece in loot[f"prem_{where}"], (seed, piece)
        for place, piece in HOARD_FINDS.items():
            state.location_id = place
            QuestEngine.evaluate(state)
            assert inventory.quantity(state, piece) == 1, (seed, place)


def test_a_hoard_find_yields_once_and_only_where_it_is(hue) -> None:
    from engine.game import inventory, quests
    from engine.game.quests import QuestEngine
    from engine.world import thievery

    state = _city(11)
    QuestEngine.evaluate(state)  # on the docks: nothing found, no arc opened
    assert "the_magpies_hoard" not in state.arcs_unlocked
    assert not any(q.startswith("hoard_") for q in quests.progress_records(state))
    assert not any(inventory.quantity(state, p) for p in HOARD)

    state.location_id = "old_bell_tower"
    QuestEngine.evaluate(state)
    QuestEngine.evaluate(state)
    state.location_id = "gallows_green"
    QuestEngine.evaluate(state)
    state.location_id = "old_bell_tower"
    QuestEngine.evaluate(state)
    assert inventory.quantity(state, "mitre_of_saint_wick") == 1
    assert inventory.quantity(state, "harbourmasters_chain") == 0
    # A famous piece off somebody's list: hot, and hot for good.
    assert thievery.heat(state, "mitre_of_saint_wick") == "hot"


def test_collecting_all_six_sets_the_flag_once(hue) -> None:
    from engine.game import inventory

    state = _city(11)
    before = int(state.reputations.get("honest_company", 0))
    pieces = list(HOARD)
    for piece in pieces[:-1]:
        assert "collections" not in inventory.grant(state, piece)
    assert not state.flags.get("magpies_hoard_complete")

    receipt = inventory.grant(state, pieces[-1])

    assert [c["id"] for c in receipt["collections"]] == ["magpies_hoard"]
    assert receipt["collections"][0]["text"] == _hoard_row()["reward_text"]
    assert state.flags["magpies_hoard_complete"] is True
    assert state.flags["collection_magpies_hoard_complete"] is True
    paid = int(state.reputations.get("honest_company", 0))
    assert paid > before

    # Put one down and pick it up again: the Hoard pays once.
    inventory.take(state, pieces[0])
    again = inventory.grant(state, pieces[0])
    assert "collections" not in again
    assert int(state.reputations.get("honest_company", 0)) == paid


def test_selling_a_piece_breaks_the_set(hue) -> None:
    from engine.game import inventory, trade
    from engine.game.clock import set_clock

    state = _city(11)
    for piece in HOARD:
        inventory.grant(state, piece)
    assert _hoard_row_status(state)["complete"] is True

    set_clock(state, day=1, hour=19)
    state.location_id = "the_snuffs"
    sold = trade.sell(state, "npc_marrow", "swan_salt")
    assert sold.get("success") is True, sold

    status = _hoard_row_status(state)
    assert status["complete"] is False and status["missing"] == ["swan_salt"]
    assert status["claimed"] is True  # it paid; selling does not claw it back


def _hoard_row_status(state):
    from engine.game import inventory

    return next(r for r in inventory.collection_status(state) if r["id"] == "magpies_hoard")


def test_a_burglary_that_takes_the_last_piece_closes_the_hoard(hue, monkeypatch) -> None:
    """The anchors' pieces arrive by the getaway, which grants through the
    effect dispatcher rather than ``inventory.grant`` -- the Hoard must still
    close on the spot, and the narrator must be told."""
    from engine.agents import prompts
    from engine.game import inventory
    from engine.game.clock import set_clock
    from engine.game.effects import apply_effect
    from engine.world import jobs

    state = _city(11)
    for piece in HOARD:
        if piece != "lantern_house_knocker":
            inventory.grant(state, piece)
    assert not state.flags.get("magpies_hoard_complete")

    state.location_id = "lantern_house"
    set_clock(state, day=1, hour=13)
    apply_effect(state, {"type": "job_prep", "delta": 3})
    state.stats.gold = 50
    assert jobs.begin(state, "prem_captains_office")["ok"] is True
    _script_rolls(monkeypatch, "success")
    out = _walk_job(state)

    assert out.get("closed") is True, out
    assert inventory.quantity(state, "lantern_house_knocker") == 1
    assert state.flags.get("magpies_hoard_complete") is True
    assert [c["id"] for c in out.get("collections") or []] == ["magpies_hoard"]
    line = prompts.summarise_receipt({"skill": "job_stage", "success": True, "result": out})
    assert _hoard_row()["reward_text"].strip() in line


# -- fix round 1 ------------------------------------------------------------


def _hoard_but(state, missing: str) -> None:
    from engine.game import inventory

    for piece in HOARD:
        if piece != missing:
            inventory.grant(state, piece)


def _burgle_the_office(state, monkeypatch) -> dict:
    from engine.game.clock import set_clock
    from engine.game.effects import apply_effect
    from engine.world import jobs

    state.location_id = "lantern_house"
    set_clock(state, day=1, hour=13)
    apply_effect(state, {"type": "job_prep", "delta": 3})
    state.stats.gold = 50
    assert jobs.begin(state, "prem_captains_office")["ok"] is True
    _script_rolls(monkeypatch, "success")
    return _walk_job(state)


def test_the_magpie_robbing_an_anchor_leaves_its_hoard_piece(hue, monkeypatch) -> None:
    """`lift_a_shiny` may rob the Office, Gannet's or Vessaline House first. An
    agenda's robbery never takes a collection member: the thief who comes
    after finds the house stripped of everything else, and the piece."""
    from engine.agents import prompts
    from engine.game import inventory
    from engine.game.effects import apply_effect

    state = _city(11)
    hit = apply_effect(state, {"type": "agenda_hit", "agenda": "the_magpie",
                               "premise": "prem_captains_office", "hour": 1})
    assert hit["ok"] is True, hit
    _hoard_but(state, "lantern_house_knocker")

    out = _burgle_the_office(state, monkeypatch)

    assert out.get("closed") is True and out.get("emptied") is True, out
    assert inventory.quantity(state, "lantern_house_knocker") == 1
    assert inventory.quantity(state, "captains_spyglass") == 0
    assert state.flags.get("magpies_hoard_complete") is True
    line = prompts.summarise_receipt({"skill": "job_stage", "success": True, "result": out})
    assert inventory.name_of("lantern_house_knocker") in line
    assert "with nothing" not in line


def test_a_find_that_closes_the_hoard_tells_the_narrator(hue) -> None:
    """The quest event's text is what reaches the ledger and the client from
    a find; the set's reward line rides it."""
    from engine.game.quests import QuestEngine
    from engine.memory.ledger import StoryLedger

    state = _city(11)
    _hoard_but(state, "mitre_of_saint_wick")
    ledger = StoryLedger()
    state.location_id = "old_bell_tower"
    events = QuestEngine.evaluate(state, ledger)

    assert state.flags.get("magpies_hoard_complete") is True
    reward = _hoard_row()["reward_text"].strip()
    assert any(reward in e.text for e in events), [e.text for e in events]


def test_a_getaway_that_closes_the_hoard_writes_its_ledger_fact(hue, monkeypatch) -> None:
    """Through the production door: a session's engine, the `job_stage` skill."""
    from engine.game.engine import active_engine
    from engine.skills.builtin.jobs import job_stage
    from engine.world import jobs
    from engine.game.clock import set_clock
    from engine.game.effects import apply_effect
    import json

    session = SessionStore().create(seed=11, llm_fn=lambda m, **k: "{}")
    state = session.engine.state
    _hoard_but(state, "lantern_house_knocker")
    state.location_id = "lantern_house"
    set_clock(state, day=1, hour=13)
    apply_effect(state, {"type": "job_prep", "delta": 3})
    state.stats.gold = 50
    assert jobs.begin(state, "prem_captains_office")["ok"] is True
    _script_rolls(monkeypatch, "success")
    with active_engine(session.engine):
        for _ in range(20):
            if jobs.active(state) is None:
                break
            out = json.loads(job_stage(jobs.approaches(state)[0][0]))
            assert out["ok"] is True, out

    assert state.flags.get("magpies_hoard_complete") is True
    assert any("Magpie's Hoard" in f.text for f in session.ledger.facts)


# -- a secret is a lever (v0.15, Task 6) --------------------------------------

#: Each anchor's secret, the blackmail thread it opens, who it squeezes, and
#: where and at what hour that person is found awake to be squeezed.
LEVERS = {
    "vessaline_manor": ("butlers_memoir", "vessaline_memoir", "npc_imelda", "silk_row", 10),
    "gannets_house": ("fund_of_ious", "gannet_ious", "npc_gannet", "the_snuffs", 20),
    "captains_office": ("magpie_file", "ardane_magpie_file", "npc_ardane", "lantern_house", 19),
    "margraves_treasury": ("light_crowns", "quill_light_crowns", "npc_steward_quill",
                           "margraves_hill", 15),
}


def _at(state, where: str, hour: int) -> None:
    from engine.game.clock import set_clock

    state.location_id = where
    set_clock(state, day=state.world_day, hour=hour)


def _hold(state, anchor: str) -> None:
    """Hold an anchor's secret the way a score does: the flag it writes."""
    secret = LEVERS[anchor][0]
    state.flags[f"secret_held:prem_{anchor}:{secret}"] = True


def _offered_ids(state) -> set:
    from engine.game import threads

    return {row["id"] for row in threads.offerable(state)}


def test_taking_the_vessaline_memoir_holds_it(hue, monkeypatch) -> None:
    """Through the production door (a session's engine, the `job_stage` skill):
    the score names the memoir, the getaway that carries it out writes the
    flag and an engine `secret` fact, and only THAT receipt line says the
    thief holds a lever, and over whom."""
    import json

    from engine.agents import prompts
    from engine.game.clock import set_clock
    from engine.game.effects import apply_effect
    from engine.game.engine import active_engine
    from engine.skills.builtin.jobs import job_stage
    from engine.world import jobs

    session = SessionStore().create(seed=11, llm_fn=lambda m, **k: "{}")
    state = session.engine.state
    state.location_id = "silk_row"
    set_clock(state, day=1, hour=1)
    apply_effect(state, {"type": "intel", "premise": "prem_vessaline_manor", "intel": "secret"})
    assert jobs.begin(state, "prem_vessaline_manor")["ok"] is True
    _script_rolls(monkeypatch, "success")
    score = getaway = None
    with active_engine(session.engine):
        for _ in range(20):
            if jobs.active(state) is None:
                break
            out = json.loads(job_stage(jobs.approaches(state)[0][0]))
            assert out["ok"] is True, out
            if out["stage"] == "score":
                score = out
                assert not state.flags.get("secret_held:prem_vessaline_manor:butlers_memoir")
            getaway = out

    assert state.flags.get("secret_held:prem_vessaline_manor:butlers_memoir") is True
    facts = [f for f in session.ledger.facts if f.kind == "secret"]
    assert facts and "memoir" in facts[0].text and facts[0].source == "engine"
    assert score is not None and "memoir" in score["secret"]
    found = prompts.summarise_receipt({"skill": "job_stage", "success": True, "result": score})
    assert "memoir" in found and "lever" not in found and "Imelda" not in found
    assert getaway is not None and getaway["closed"] and "memoir" in getaway["held"]
    line = prompts.summarise_receipt({"skill": "job_stage", "success": True, "result": getaway})
    assert "memoir" in line and "lever" in line and "Lady Imelda Vessaline" in line
    assert "pay" not in line   # a lever, not a promised price (the thread has its own gates)


def test_a_thief_caught_leaving_the_captains_office_cannot_squeeze_her(hue, monkeypatch) -> None:
    """Caught at the getaway: the Watch took its file back, so there is no lever."""
    from engine.game.effects import apply_effect
    from engine.world import jobs

    state = _city(11)
    apply_effect(state, {"type": "intel", "premise": "prem_captains_office", "intel": "secret"})
    _script_rolls(monkeypatch, "success")
    state.location_id = "lantern_house"
    from engine.game.clock import set_clock
    set_clock(state, day=1, hour=13)
    apply_effect(state, {"type": "job_prep", "delta": 3})
    assert jobs.begin(state, "prem_captains_office")["ok"] is True
    for _ in range(20):
        if jobs.current_stage(state) == "getaway":
            break
        jobs.resolve_stage(state, jobs.approaches(state)[0][0])
    assert jobs.current_stage(state) == "getaway"
    _script_rolls(monkeypatch, "failure")
    out: dict = {}
    for _ in range(10):
        out = jobs.resolve_stage(state, "getaway")
        if out.get("closed"):
            break
    assert out["closed"] and out["outcome"] == "caught", out
    assert not any(k.startswith("secret_held:") for k in state.flags)
    _at(state, "lantern_house", 19)
    _file(state, "self")
    assert "ardane_magpie_file" not in _offered_ids(state)


def test_imeldas_squeeze_is_offered_only_once_the_memoir_is_held(hue) -> None:
    state = _city(11)
    _at(state, "silk_row", 10)
    assert "vessaline_memoir" not in _offered_ids(state)
    _hold(state, "vessaline_manor")
    assert "vessaline_memoir" in _offered_ids(state)
    _at(state, "silk_row", 14)         # at the Temple, not at home
    assert "vessaline_memoir" not in _offered_ids(state)
    _at(state, "wickmarket", 10)       # squeezed on her own street, nowhere else
    assert "vessaline_memoir" not in _offered_ids(state)


def test_every_anchor_secret_names_its_blackmail_thread(hue) -> None:
    """A secret's `thread:` names its template; the template is a Blackmail
    squeezing the owner, gated on holding exactly that secret, where they are."""
    from engine.game import threads
    from engine.world import premises

    for anchor, (secret, template, npc, where, hour) in LEVERS.items():
        row = premises.spec(anchor)["secrets"][0]
        assert (row["id"], row.get("thread")) == (secret, template), anchor
        raw = threads.templates()[template]
        assert raw["source"] == npc and raw["tags"] == ["Blackmail"], template
        assert raw.get("on_break"), template
        state = _city(11)
        _at(state, where, hour)
        _file(state, "self")   # the captain's price wants something on file
        assert template not in _offered_ids(state), template
        _hold(state, anchor)
        assert template in _offered_ids(state), template


def test_imeldas_squeeze_never_leans_on_who_the_magpie_is(hue) -> None:
    """Imelda is a Magpie candidate: her thread turns on her butler's memoir."""
    from engine.game import threads

    raw = threads.templates()["vessaline_memoir"]
    words = f"{raw['title']} {raw['terms']}".lower()
    assert "memoir" in words
    for word in ("magpie", "debt", "owes", "ruin", "motive", "thief"):
        assert word not in words, word


def _seal(state, template: str) -> dict:
    from engine.game import threads

    sealed = threads.seal(state, threads.offer(state, template))
    assert sealed["ok"], sealed
    return sealed["thread"]


def test_imelda_pays_at_the_silversmiths_window(hue) -> None:
    from engine.game import threads
    from engine.game.clock import set_clock

    state = _city(11)
    _at(state, "silk_row", 10)
    _hold(state, "vessaline_manor")
    thread = _seal(state, "vessaline_memoir")
    assert not threads.can_discharge(state, thread)   # in her parlour, not at the window
    set_clock(state, day=state.world_day, hour=17)
    gold = state.stats.gold
    assert threads.discharge(state, thread["id"])["ok"]
    assert state.stats.gold == gold + 20


def test_a_squeeze_left_uncollected_goes_to_the_watch(hue) -> None:
    """The blackmail deed: filed by the one witness to it, the victim, on break."""
    from engine.game import threads
    from engine.world import law

    state = _city(11)
    _at(state, "silk_row", 10)
    _hold(state, "vessaline_manor")
    thread = _seal(state, "vessaline_memoir")
    assert not state.law.get("reports")
    out = threads.break_thread(state, thread["id"])
    assert out["ok"], out
    rows = state.law["reports"]
    assert [(r["deed"], r["jurisdiction"], r["guise"]) for r in rows] == [
        ("blackmail", "rise", "self")]
    assert law.load_spec()["deeds"]["blackmail"] == rows[0]["severity"]


def test_the_blackmail_deed_weighs_what_law_yaml_says(hue) -> None:
    """T8: law.yaml's severity claim is replayed by a committed harness
    (`scripts/simulate_hoard.py --severity`), not a scratch script. At the
    shipped 3: `noticed` two mornings alone; beside a lift seen up the Rise,
    `sought` the day it lands and `noticed` four days more. At 4 a squeeze
    alone would be `sought` -- the stop the file's reason turns down."""
    _scripts_on_path()
    from engine.world import law
    from scripts import simulate_hoard
    from scripts.simulate_law import agendas_off

    assert law.load_spec()["deeds"]["blackmail"] == 3
    with agendas_off():
        shipped = simulate_hoard.severity_sweep((law.load_spec()["deeds"]["blackmail"], 4), days=6)
    assert shipped["3"]["alone"] == ["noticed", "noticed"] + ["unknown"] * 5
    assert shipped["3"]["beside_a_lift"] == ["sought"] + ["noticed"] * 4 + ["unknown"] * 2
    assert shipped["4"]["alone"][0] == "sought"
    assert law.load_spec()["deeds"]["blackmail"] == 3   # the sweep put it back


def test_squeezing_mother_gannet_costs_the_company_on_the_spot(hue) -> None:
    from engine.game import reputation

    state = _city(11)
    _at(state, "the_snuffs", 20)
    _hold(state, "gannets_house")
    before = reputation.get(state, "honest_company")
    _seal(state, "gannet_ious")
    assert reputation.get(state, "honest_company") < before


def test_ardane_looks_away_from_every_watch_house(hue) -> None:
    """The captain's price: her file on you, and the Magpie's, lost city-wide."""
    from engine.game import threads
    from engine.game.clock import set_clock
    from engine.world import law

    state = _city(11)
    _at(state, "lantern_house", 19)
    _hold(state, "captains_office")
    assert "ardane_magpie_file" not in _offered_ids(state)   # nothing for her to lose
    _file(state, "magpie")
    _file_in(state, "self", "quay")
    _file(state, "porter")   # a face nobody has tied to you stays filed
    assert "ardane_magpie_file" in _offered_ids(state)
    thread = _seal(state, "ardane_magpie_file")
    assert threads.discharge(state, thread["id"])["ok"]
    assert [(r["jurisdiction"], r["guise"]) for r in state.law["reports"]] == [("wick", "porter")]
    assert law.wanted_band(state, "self", "quay") == "unknown"


def test_no_squeeze_is_cut_at_the_table(hue) -> None:
    """The thread bounder drops a disallowed kind and clamps a large one with
    only a logged adjustment: every squeeze must survive it whole -- the
    victim's `report` included (authored-only, `STRUCTURAL_EFFECT_TYPES`)."""
    from engine.game import threads

    state = _city(11)
    for _anchor, (_s, template, _n, _w, _h) in LEVERS.items():
        offer = threads.offer(state, template)
        assert offer is not None and offer.adjustments == [], (template, offer.adjustments)
        raw = threads.templates()[template]
        for hook in ("on_seal", "on_discharge", "on_break"):
            assert getattr(offer, hook) == list(raw.get(hook) or []), (template, hook)


def test_a_model_composed_challenge_still_cannot_file_a_report() -> None:
    """`report` is authored-only: a dice table must not frame the player."""
    from engine.challenges import spec as spec_module

    notes: list[str] = []
    out = spec_module.clamp_outcome(
        {"effects": [{"type": "report", "deed": "blackmail", "guise": "self",
                      "jurisdiction": "rise", "precision": 1.0}]}, notes)
    assert out["effects"] == [] and any("report" in n for n in notes)


def test_every_squeeze_left_uncollected_has_teeth(hue) -> None:
    """Row, Hill and captain file blackmail in their own jurisdiction; the Snuffs
    never go to the Watch, so Gannet's teeth are the Company's opinion."""
    from engine.game import reputation, threads

    expected = {"vessaline_memoir": ("rise", "silk_row"),
                "gannet_ious": (None, "honest_company"),
                "ardane_magpie_file": ("wick", "lantern_watch"),
                "quill_light_crowns": ("rise", "margraves_household")}
    for anchor, (_s, template, _n, where, hour) in LEVERS.items():
        state = _city(11)
        _at(state, where, hour)
        _file_in(state, "self", "quay")   # the captain's price wants something on file
        _hold(state, anchor)
        thread = _seal(state, template)
        jurisdiction, faction = expected[template]
        before = reputation.get(state, faction)
        filed = len(state.law.get("reports") or [])
        assert threads.break_thread(state, thread["id"])["ok"]
        assert reputation.get(state, faction) == before - 10, template
        rows = (state.law.get("reports") or [])[filed:]
        if jurisdiction is None:
            assert rows == [], template
        else:
            assert [(r["deed"], r["jurisdiction"], r["precision"]) for r in rows] == [
                ("blackmail", jurisdiction, 1.0)], template


def test_the_steward_pays_at_his_table(hue) -> None:
    from engine.game import threads

    state = _city(11)
    _at(state, "margraves_hill", 15)
    _hold(state, "margraves_treasury")
    thread = _seal(state, "quill_light_crowns")
    gold = state.stats.gold
    assert threads.discharge(state, thread["id"])["ok"]
    assert state.stats.gold == gold + 25


# ---------------------------------------------------------------------------
# v0.15: the fences' credit (data/rules/threads.yaml `pell_advance`,
# `marrow_slate`; data/tables/trade.yaml `refuses_to_buy`)
# ---------------------------------------------------------------------------

#: Each credit thread: its fence, her counter, an hour she trades there and
#: one she does not, what she stands you, what you owe back, and the flag a
#: break sets.
CREDIT = {
    "pell_advance": ("npc_pell_hollis", "wickmarket", 10, 3, 10, 13, "welshed_on_pell"),
    "marrow_slate": ("npc_marrow", "the_snuffs", 21, 12, 5, 8, "welshed_on_marrow"),
}


def _credit_state(template: str, *, open_hours: bool = True):
    _fence, where, hour, closed, *_ = CREDIT[template]
    state = _city(11)
    _at(state, where, hour if open_hours else closed)
    state.stats.gold = 0
    return state


def test_credit_is_offered_only_at_the_fences_own_counter(hue) -> None:
    from engine.game import threads

    for template, (_fence, where, _h, _c, *_rest) in CREDIT.items():
        state = _credit_state(template)
        assert template in _offered_ids(state), template
        assert threads.can_strike(state, template), template
        closed = _credit_state(template, open_hours=False)
        assert template not in _offered_ids(closed), template   # she is not trading
        for district in PUBLIC_DISTRICTS:
            if district == where:
                continue
            state.location_id = district
            assert template not in _offered_ids(state), (template, district)
            assert not threads.can_strike(state, template), (template, district)


def test_sealing_credit_pays_out(hue) -> None:
    for template, (*_x, lent, _owed, _flag) in CREDIT.items():
        state = _credit_state(template)
        _seal(state, template)
        assert state.stats.gold == lent, template


def test_an_open_line_of_credit_is_not_offered_twice(hue) -> None:
    """One copy at a time: a second advance on top of the first is one debt counted twice."""
    from engine.game import threads

    for template in CREDIT:
        state = _credit_state(template)
        _seal(state, template)
        assert template not in _offered_ids(state), template
        assert not threads.can_strike(state, template), template


def test_credit_is_repaid_in_coin_at_her_counter_and_offered_again(hue) -> None:
    from engine.game import intents, threads

    for template, (_fence, where, _h, _c, lent, owed, _flag) in CREDIT.items():
        state = _credit_state(template)
        thread = _seal(state, template)
        assert state.stats.gold == lent
        assert not threads.can_discharge(state, thread), template   # short of it
        state.stats.gold = owed + 2
        state.location_id = "tallow_docks"
        assert not threads.can_discharge(state, thread), template   # not at her counter
        state.location_id = where
        verb = intents.find_verb(intents.legal_intents(state), "discharge")
        assert verb and thread["id"] in {t for t, _ in verb.options}, template
        out = threads.discharge(state, thread["id"])
        assert out["ok"], (template, out)
        assert state.stats.gold == 2, template
        assert threads.get(state, thread["id"])["status"] == "discharged"
        assert template in _offered_ids(state), template   # a slate paid is a slate open
        assert state.moved == [], (template, state.moved)   # settling breaks nothing


def test_welshing_on_a_fence_shuts_both_to_you_and_the_word_goes_round(hue) -> None:
    """Fix round 1: fences stand together -- welsh on one and NEITHER buys
    from you or lends to you again (before, the other fence still bought,
    which cost a thief who sold to her nothing at all)."""
    from engine.game import intents, threads, trade
    from engine.game.effects import apply_effect

    for template, (_fence, where, hour, _c, _lent, _owed, flag) in CREDIT.items():
        state = _credit_state(template)
        thread = _seal(state, template)
        state.stats.gold = 0
        state.world_clock_hours += 24 * 4
        _at(state, where, hour)
        threads.expire_due(state)
        assert threads.get(state, thread["id"])["status"] == "broken", template
        assert state.flags.get(flag) is True, template
        apply_effect(state, {"type": "item", "item_id": "silver_thimble", "qty": 1})
        for other, (other_fence, other_where, other_hour, *_r) in CREDIT.items():
            _at(state, other_where, other_hour)
            # Neither buys -- refused in her words, never offered.
            assert trade.refusal_to_buy(state, other_fence), (template, other_fence)
            sale = trade.sell(state, other_fence, "silver_thimble", 1)
            assert sale["success"] is False, (template, other_fence)
            assert sale["message"] == trade.refusal_to_buy(state, other_fence)
            verb = intents.find_verb(intents.legal_intents(state), "sell")
            assert not verb or not any(t.startswith(f"{other_fence}/") for t, _ in verb.options)
            # ...and neither stands you credit again.
            assert other not in _offered_ids(state), (template, other)
            assert not threads.can_strike(state, other), (template, other)
        # Dock Mag is no fence and was never party to it.
        assert trade.refusal_to_buy(state, "npc_dock_mag") == ""


def test_welshing_on_pell_costs_you_the_stalls(hue) -> None:
    """Her neighbours talk (factions.yaml `market_stalls`)."""
    from engine.game import reputation, threads

    state = _credit_state("pell_advance")
    thread = _seal(state, "pell_advance")
    before = reputation.get(state, "market_stalls")
    threads.break_thread(state, thread["id"])
    assert reputation.get(state, "market_stalls") == before - 5


def test_the_narrator_hears_the_break_and_sees_the_shut_counter(hue) -> None:
    """Audit question 2: the break is journalled once, in the story's words,
    and standing at her counter the PEOPLE HERE line says she will not buy."""
    from engine.agents import prompts
    from engine.game import threads, trade

    for template, (fence, where, hour, *_r) in CREDIT.items():
        state = _credit_state(template)
        assert "buys nothing from you" not in prompts._npcs_present_block(state)
        thread = _seal(state, template)
        state.world_clock_hours += 24 * 4
        threads.expire_due(state)
        block = prompts.moved_block(state)
        assert "the word has gone round" in block, template
        assert "after dark" in block, template   # the collectors, and why
        assert threads.get(state, thread["id"])["terms"] not in block   # its own line
        _at(state, where, hour)
        people = prompts._npcs_present_block(state)
        line = next(l for l in people.splitlines() if l.startswith(f"- {fence}:"))
        assert trade.refusal_to_buy(state, fence) in line, (template, line)
        assert "buys nothing from you" in line, (template, line)


def test_no_credit_state_gates_rest(hue) -> None:
    """Rule 6: welsh on both fences, sit on an empty purse -- a rough night is
    still there wherever you stand, and the flophouse still takes your crown."""
    from engine.game import survival, threads

    state = _city(3)
    for template, (_f, where, hour, *_r) in CREDIT.items():
        _at(state, where, hour)
        thread = _seal(state, template)
        threads.break_thread(state, thread["id"])
    state.stats.gold = 0
    _at(state, "the_snuffs", 22)
    for district in PUBLIC_DISTRICTS:
        state.location_id = district
        assert "sleep_rough" in _rest_targets(state), district
    state.location_id = "the_snuffs"
    state.stats.stamina = 5
    assert survival.rest(state, "sleep_rough")["success"] and state.stats.stamina > 5
    state.stats.gold = 1
    assert "sleep_flophouse" in _rest_targets(state)
    paid = survival.rest(state, "sleep_flophouse")   # a roof, not a downgrade
    assert paid["success"] and paid.get("kind") == "sleep_flophouse", paid
    assert state.stats.gold == 0


def test_no_credit_term_is_cut_at_the_table(hue) -> None:
    """Every credit thread survives the bounder whole (gold clamps at 25 here)."""
    from engine.game import threads

    state = _city(11)
    for template in CREDIT:
        offer = threads.offer(state, template)
        assert offer is not None and offer.adjustments == [], (template, offer.adjustments)
        assert offer.tags == ["Credit"]
        raw = threads.templates()[template]
        for hook in ("on_seal", "on_discharge", "on_break"):
            assert getattr(offer, hook) == list(raw.get(hook) or []), (template, hook)
        assert raw.get("repeatable") is True


def test_every_hue_thread_that_can_break_says_so(hue) -> None:
    """Owner direction (T7 fix round 1): no thread with an `on_break` breaks
    in silence. Each carries the narrator's line, worded true both for a
    break that came due and for one made early."""
    from engine.game import threads

    for template_id, raw in threads.templates().items():
        if not raw.get("on_break"):
            continue
        text = str(raw.get("broken_text") or "").strip()
        assert text, template_id
        assert "came due" not in text.lower(), template_id


def test_every_squeeze_break_tells_the_narrator_about_the_heat(hue) -> None:
    """A thread whose `on_break` files a report says who went to the Watch."""
    from engine.game import threads

    for template_id, raw in threads.templates().items():
        if any(e.get("type") == "report" for e in raw.get("on_break") or []):
            assert "watch" in raw["broken_text"].lower(), template_id


def test_imeldas_broken_line_turns_on_the_memoir_alone(hue) -> None:
    from engine.game import threads

    words = threads.templates()["vessaline_memoir"]["broken_text"].lower()
    assert "memoir" in words
    for word in ("magpie", "debt", "owes", "ruin", "motive", "thief", "mask"):
        assert word not in words, word
    for template_id, raw in threads.templates().items():
        assert "magpie" not in str(raw.get("broken_text") or "").lower(), template_id


def test_a_refused_strike_says_why(session) -> None:
    """Rule 1: the refusal that reaches the prose is the true one -- already
    open, already struck once, or not here and now."""
    import json

    from engine.game import threads
    from engine.game.engine import active_engine
    from engine.skills.builtin.scenes import strike_bargain

    state = session.engine.state
    with active_engine(session.engine):
        _at(state, "tallow_docks", 10)
        assert json.loads(strike_bargain("pell_advance"))["error"] == threads.REFUSED_HERE
        _at(state, "wickmarket", 10)
        assert json.loads(strike_bargain("pell_advance"))["ok"] is True
        assert json.loads(strike_bargain("pell_advance"))["error"] == threads.REFUSED_OPEN
        _file(state, "self")
        _at(state, "lantern_house", 10)
        assert json.loads(strike_bargain("brask_bribe"))["ok"] is True
        assert json.loads(strike_bargain("brask_bribe"))["error"] == threads.REFUSED_ONCE
    assert threads.strike_refusal(state, "no_such_bargain") == threads.REFUSED_HERE



# -- the fences' collectors (v0.15, T7 fix round 1: the owner's teeth) --------

#: Each collector scene, the flag that sends it, and what settles it.
COLLECTORS = {"pells_collectors": ("welshed_on_pell", 13, "pell_advance"),
              "marrows_lads": ("welshed_on_marrow", 8, "marrow_slate"),
              "pells_collectors_by_day": ("welshed_on_pell", 13, "pell_advance"),
              "marrows_lads_by_day": ("welshed_on_marrow", 8, "marrow_slate")}


def test_no_collector_walks_for_anyone_who_never_welshed(session) -> None:
    """Seed replay is unchanged: without the flag neither scene is ever
    eligible, so the ENCOUNTER stream draws from exactly the old table."""
    from engine.game import encounter
    from engine.game.clock import set_clock

    state = session.engine.state
    for hour in range(24):
        set_clock(state, day=2, hour=hour)
        for src, dst in _public_legs():
            ids = {r["id"] for r in encounter.eligible(state, src, dst)}
            assert not ids & set(COLLECTORS), (src, dst, hour, ids)
            # ...and no leg is made one hair more dangerous by the day rows'
            # `min_chance`: the chance a leg rolls is the v0.14 formula's.
            assert encounter.row_floor(state, src, dst) == 0.0, (src, dst, hour)
            assert encounter.leg_chance(state, src, dst) == encounter.trigger_chance(
                state, src, dst), (src, dst, hour)


def test_a_non_welshers_streets_draw_exactly_as_before(session) -> None:
    """Byte-identical ENCOUNTER stream: the same seeded walks, drawn through
    `roll_for_encounter` (now `leg_chance`) and through the v0.14 formula
    alone, pick the same scenes on the same legs at every hour."""
    import random

    from engine.game import encounter
    from engine.game.clock import set_clock

    state = session.engine.state

    def v014(gen, src, dst):
        chance = encounter.trigger_chance(state, src, dst)
        if chance <= 0.0 or gen.random() >= chance:
            return None
        rows = encounter.eligible(state, src, dst)
        return encounter._weighted_choice(rows, gen)["id"] if rows else None

    for hour in range(24):
        set_clock(state, day=2, hour=hour)
        a, b = random.Random(hour), random.Random(hour)
        for _ in range(3):
            for src, dst in _public_legs():
                now = encounter.roll_for_encounter(state, src, dst, rng=a)
                assert ((now or {}).get("id")) == v014(b, src, dst), (hour, src, dst)


def test_a_welsher_meets_the_collectors_after_dark(session) -> None:
    from engine.game import encounter
    from engine.game.clock import set_clock

    state = session.engine.state
    for scene, (flag, _owed, _t) in COLLECTORS.items():
        if scene.endswith("_by_day"):
            continue   # the next test's
        state.flags[flag] = True
        set_clock(state, day=2, hour=22)
        assert scene in {r["id"] for r in encounter.eligible(state, "tallow_docks", "the_snuffs")}
        set_clock(state, day=2, hour=12)
        assert scene not in {r["id"] for r in encounter.eligible(state, "tallow_docks", "the_snuffs")}
        set_clock(state, day=2, hour=22)
        assert scene not in {r["id"] for r in encounter.eligible(state, "silk_row", "margraves_hill")}
        state.flags[flag] = False
        set_clock(state, day=2, hour=12)
        state.flags[flag] = True
        assert scene not in {r["id"] for r in encounter.eligible(state, "tallow_docks", "the_snuffs")}
        state.flags[flag] = False


def test_a_welsher_meets_the_collectors_by_day_in_the_fences_districts(session) -> None:
    """Owner, T7 fix round 2: by day too, in Wickmarket and the Snuffs only,
    at a smaller share than the night's worst leg."""
    from engine.game import encounter
    from engine.game.clock import set_clock

    state = session.engine.state

    def collectors_share(src: str, dst: str) -> float:
        rows = encounter.eligible(state, src, dst)
        weights = {r["id"]: int(r.get("weight", 10)) for r in rows}
        mine = sum(w for k, w in weights.items() if k in COLLECTORS)
        return encounter.leg_chance(state, src, dst) * mine / max(1, sum(weights.values()))

    for scene, (flag, _owed, _t) in COLLECTORS.items():
        if not scene.endswith("_by_day"):
            continue
        state.flags[flag] = True
        set_clock(state, day=2, hour=12)
        for dst in ("wickmarket", "the_snuffs"):
            assert scene in {r["id"] for r in encounter.eligible(state, "tallow_docks", dst)}
            assert encounter.leg_chance(state, "tallow_docks", dst) >= 0.10
        assert scene not in {r["id"] for r in encounter.eligible(state, "wickmarket", "tallow_docks")}
        by_day = collectors_share("tallow_docks", "the_snuffs")
        set_clock(state, day=2, hour=22)
        assert scene not in {r["id"] for r in encounter.eligible(state, "tallow_docks", "the_snuffs")}
        at_night = collectors_share("tallow_docks", "the_snuffs")
        assert 0.05 <= by_day < at_night, (scene, by_day, at_night)
        state.flags[flag] = False


def _strings(node) -> list[str]:
    if isinstance(node, str):
        return [node]
    if isinstance(node, dict):
        return [s for v in node.values() for s in _strings(v)]
    if isinstance(node, list):
        return [s for v in node for s in _strings(v)]
    return []


def test_no_daytime_street_scene_speaks_of_the_night(session) -> None:
    """Audit questions 2 and 3 (T8): a row that can only fire by day must not
    tell a noon scene "see you another night" or "they let you go --
    tonight". The collectors' day rows are YAML merges of the night ones, and
    inherited exactly that until they overrode the words."""
    import re

    from engine.game import encounter

    day_hours = set(range(6, 18))
    day_rows = [r for r in encounter.all_encounters()
                if (r.get("triggers") or {}).get("hours")
                and set((r.get("triggers") or {})["hours"]) <= day_hours]
    ids = {r["id"] for r in day_rows}
    assert {"pells_collectors_by_day", "marrows_lads_by_day"} <= ids, ids
    for row in day_rows:
        for text in _strings({k: v for k, v in row.items() if k != "triggers"}):
            assert not re.search(r"night", text, re.IGNORECASE), (row["id"], text)


def test_the_collectors_say_whose_debt_it_is(session) -> None:
    """Audit question 2: the scene's own words name the fence and the sum."""
    from engine.game import encounter

    rows = {r["id"]: r for r in encounter.all_encounters()}
    assert "Hollis" in rows["pells_collectors"]["intro"]
    assert "Thirteen crowns" in rows["pells_collectors"]["intro"]
    assert "Eight crowns" in rows["marrows_lads"]["intro"]
    assert "gatepost" in rows["marrows_lads"]["intro"]


def test_paying_the_collectors_closes_the_debt(session) -> None:
    from engine.game import encounter, trade
    from engine.game.clock import set_clock

    state = session.engine.state
    for scene, (flag, owed, _t) in COLLECTORS.items():
        state.flags[flag] = True
        set_clock(state, day=2, hour=22)
        state.stats.gold = owed - 1
        encounter.begin(state, scene)
        offered = {a["id"] for a in encounter.available_approaches(state)}
        assert "settle" not in offered and "turn_out_pockets" in offered   # short of it
        encounter.resolve_approach(state, "turn_out_pockets")
        assert state.flags.get(flag) is True, scene   # on account: the debt stands
        state.stats.gold = owed + 1
        encounter.begin(state, scene)
        receipt = encounter.resolve_approach(state, "settle")
        assert receipt["ok"] and receipt["resolved"], receipt
        assert state.stats.gold == 1, scene
        assert not state.flags.get(flag), scene
        assert trade.refusal_to_buy(state, "npc_marrow") == "", scene
        assert trade.refusal_to_buy(state, "npc_pell_hollis") == "", scene


def test_on_account_takes_coin_and_leaves_the_debt(session) -> None:
    from engine.game import encounter
    from engine.game.clock import set_clock

    state = session.engine.state
    state.flags["welshed_on_pell"] = True
    set_clock(state, day=2, hour=22)
    state.stats.gold = 9
    encounter.begin(state, "pells_collectors")
    encounter.resolve_approach(state, "turn_out_pockets")
    assert state.stats.gold == 4
    assert state.flags.get("welshed_on_pell") is True


def test_a_known_welsher_is_told_why_no_credit(session) -> None:
    """T7 fix round 2: a credit line shut by the word going round says so,
    not "here and now"."""
    import json

    from engine.game import threads
    from engine.game.engine import active_engine
    from engine.skills.builtin.scenes import strike_bargain

    state = session.engine.state
    with active_engine(session.engine):
        for flag in ("welshed_on_pell", "welshed_on_marrow"):
            state.flags[flag] = True
            for template, (_f, where, hour, *_r) in CREDIT.items():
                _at(state, where, hour)
                out = json.loads(strike_bargain(template))
                assert out["ok"] is False
                assert "known welsher" in out["error"], (flag, template, out)
            state.flags[flag] = False
        # Not a welsher, wrong street: still the honest "here and now".
        _at(state, "tallow_docks", 10)
        assert json.loads(strike_bargain("pell_advance"))["error"] == threads.REFUSED_HERE


# ---------------------------------------------------------------------------
# v0.16 T1: the acts, and the act the narrator is told
# ---------------------------------------------------------------------------


def test_a_fresh_run_opens_in_act_one_with_no_phantom_arc(hue) -> None:
    """The run starts in Act I, the way out open beside it, and no
    `quiet_life` -- the flagship's arc every story used to inherit."""
    from engine.scenes.default_api import quest_journal

    state = _city(11)
    assert state.active_arc == "hue_and_cry"
    assert state.arcs_unlocked == ["the_way_out", "hue_and_cry"]
    journal = quest_journal(state)
    assert journal["active_arc_title"] == "Hue and Cry"
    assert [a["id"] for a in journal["arcs_unlocked"]] == ["the_way_out", "hue_and_cry"]


def test_the_acts_climb_on_initiation_and_the_side_arcs_stay_open(hue) -> None:
    """Act II opens on `guild_initiated` (set here directly: the initiation
    deck that sets it is T4). The way out's quest still offers itself, and
    finding the Hoard opens its arc without taking the act away."""
    from engine.game.quests import EVENT_ARC_UNLOCKED, QuestEngine, progress_records

    state = _city(11)
    QuestEngine.evaluate(state)
    assert state.active_arc == "hue_and_cry"
    assert "honest_work" not in state.arcs_unlocked
    assert "the_evening_barge" in progress_records(state)

    state.location_id = "old_bell_tower"
    QuestEngine.evaluate(state)
    assert "the_magpies_hoard" in state.arcs_unlocked
    assert state.active_arc == "hue_and_cry"

    state.flags["guild_initiated"] = True
    events = QuestEngine.evaluate(state)
    assert [e.quest_id for e in events if e.kind == EVENT_ARC_UNLOCKED] == ["honest_work"]
    assert state.active_arc == "honest_work"

    # Monotonic: the flag going away does not walk the act back.
    state.flags["guild_initiated"] = False
    QuestEngine.evaluate(state)
    assert state.active_arc == "honest_work"


def test_a_save_from_before_the_acts_climbs_into_act_one(hue) -> None:
    """An old-shaped save: `quiet_life` active and unlocked, the way out
    open. It loads, reads the unknown arc as order -1, climbs into Act I on
    the next evaluate, and its journal no longer lists the phantom."""
    import json

    from engine.game.quests import QuestEngine, arc_order
    from engine.game.state import GameState
    from engine.scenes.default_api import quest_journal

    old = json.loads(json.dumps(_city(11).to_save_dict()))
    old["active_arc"] = "quiet_life"
    old["arcs_unlocked"] = ["quiet_life", "the_way_out"]
    state = GameState.from_dict(old)
    assert arc_order("quiet_life") == -1
    QuestEngine.evaluate(state)
    assert state.active_arc == "hue_and_cry"
    assert "hue_and_cry" in state.arcs_unlocked
    titles = [a["id"] for a in quest_journal(state)["arcs_unlocked"]]
    assert "quiet_life" not in titles


def test_the_narrator_is_told_the_act(hue) -> None:
    from engine.agents import prompts
    from engine.game.quests import QuestEngine

    state = _city(11)
    QuestEngine.evaluate(state)
    act = prompts.act_block(state)
    assert act.startswith("ACT: Hue and Cry. ")
    assert len(act.splitlines()) == 1
    assert act in prompts.world_state_block(state, {})

    state.flags["guild_initiated"] = True
    QuestEngine.evaluate(state)
    act = prompts.act_block(state)
    assert act.startswith("ACT: Honest Work. ")
    assert act in prompts.world_state_block(state, {})


def test_the_act_line_is_the_only_change_to_the_prompt(hue) -> None:
    """Against the pre-acts state (the old default arcs), the world-state
    block differs by the ACT line and nothing else -- and the act never
    names the real Magpie."""
    from engine.agents import prompts
    from engine.game.quests import QuestEngine, load_arcs

    fresh = _city(11)
    legacy = _city(11)
    legacy.active_arc, legacy.arcs_unlocked = "quiet_life", ["quiet_life"]
    QuestEngine.evaluate(fresh)
    QuestEngine.evaluate(legacy)
    # Where the pre-acts content settled: the way out was the highest arc.
    legacy.active_arc = "the_way_out"
    act = prompts.act_block(fresh)
    lines = prompts.world_state_block(fresh, {}).splitlines()
    assert act in lines
    lines.remove(act)
    old = prompts.world_state_block(legacy, {})
    assert "ACT:" not in old
    assert "\n".join(lines) == old
    # Both acts: no candidate's name or alias (agendas.yaml's role mask).
    acts = [act, "ACT: " + " ".join(str(load_arcs()["honest_work"]["blurb"]).split())]
    for word in ("wren", "silas", "crook", "imelda", "lamplighter", "dapper", "vessaline"):
        assert not any(word in line.lower() for line in acts), word


def test_act_one_arrives_on_the_barge_the_opening_arrives_on(hue) -> None:
    """The Act I blurb is in every Act I prompt and in the journal: the barge
    it says you came off must be the one the opening lands you from."""
    import re

    from engine.game.quests import load_arcs
    from engine.scenes.default_state import opening_narration

    opening = opening_narration().lower()
    blurb = " ".join(str(load_arcs()["hue_and_cry"]["blurb"]).split()).lower()
    arrived = set(re.findall(r"(\w+) barge", opening))
    said = set(re.findall(r"(\w+) barge", blurb))
    assert arrived == {"morning"}, arrived
    assert said <= arrived, (said, blurb)


def test_act_two_stays_true_after_a_right_naming(hue) -> None:
    """Audit question 3: a right naming (`law_unlink self/magpie`) lands
    while Act II is still the act, so the ACT line must not go on telling the
    narrator that the Magpie's robberies land on your name."""
    from engine.agents import prompts
    from engine.game.effects import apply_effect
    from engine.game.quests import QuestEngine

    state = _city(11)
    state.flags["guild_initiated"] = True
    QuestEngine.evaluate(state)
    assert state.active_arc == "honest_work"
    assert apply_effect(state, {"type": "law_unlink", "a": "self", "b": "magpie"})["ok"]
    act = prompts.act_block(state).lower()
    assert act.startswith("act: honest work. ")
    assert "on your name" not in act, act
    assert "lands on you" not in act, act


# ---------------------------------------------------------------------------
# Off the barge (v0.16 Task 3): the opening's three choices are real
# ---------------------------------------------------------------------------

#: Every name and alias the Magpie's role mask hides (agendas.yaml), plus the
#: trades that would point at one of them. Nothing the opening says or does
#: may carry any of them.
_CANDIDATE_WORDS = ("wren", "silas", "crook", "imelda", "lamplighter", "dapper", "vessaline")


def _opening_llm(_messages, **_kwargs) -> str:
    import json

    return json.dumps({"narration": "The quay holds its breath, and then lets it go.",
                       "choices": [{"id": "a", "text": "Wait"},
                                   {"id": "b", "text": "Look about"}]})


def _opening_session(seed: int):
    session = SessionStore().create(seed=seed, llm_fn=_opening_llm)
    session.storyteller.llm_fn = _opening_llm
    session.assistant.llm_fn = _opening_llm
    return session


@pytest.fixture()
def quay_saves(tmp_path, monkeypatch):
    """HUE & CRY active, every save this test makes kept in a temp directory."""
    from engine.persistence import reset_save_store
    from engine.persistence.saves import SaveStore

    registry.activate("hue-and-cry")
    reset_save_store()
    store = SaveStore(root=tmp_path / "saves")
    monkeypatch.setattr("engine.scenes.default_state.get_save_store", lambda: store)
    monkeypatch.setattr("engine.session.store.get_save_store", lambda: store)
    yield
    reset_save_store()


@pytest.fixture()
def barge(quay_saves):
    """A fresh run on the quay at 08:00, on the opening frame."""
    return _opening_session(11)


def _opening_row(choice_id: str) -> dict:
    rows = registry.get("hue-and-cry").entry["opening"]["choices"]
    return next(r for r in rows if r["id"] == choice_id)


def _take_opening(session, choice_id: str) -> dict:
    """The real door: the sentence, the intent and the authored half, then run_turn."""
    from engine.scenes.default_state import (resolve_authored_choice, resolve_player_action,
                                             resolve_player_intent, run_turn)

    action = resolve_player_action(session, choice_id)
    intent = resolve_player_intent(session, choice_id)
    authored = resolve_authored_choice(session, choice_id)
    return run_turn(session, action, intent=intent, authored=authored)


def _force(monkeypatch, degree: str) -> None:
    """Every check lands at ``degree`` (the opening's roll and the stop's)."""
    from engine.game import checks

    real = checks.resolve

    def forced(state, skill, difficulty, **kwargs):
        result = real(state, skill, difficulty, **kwargs)
        result.degree = degree
        return result

    monkeypatch.setattr(checks, "resolve", forced)


def _authored_receipt(payload: dict) -> dict:
    rows = [r for r in payload.get("tool_receipts") or [] if r.get("skill") == "authored_choice"]
    assert len(rows) == 1, payload.get("tool_receipts")
    return rows[0]["result"]


def test_the_openings_authored_consequences_are_sound(hue) -> None:
    """Every deed a law deed, every scene a declared one, every effect one an
    authored choice may use -- the validator's check, asked of the shipped
    file -- and the three choices do what the brief says they do."""
    from engine.game import authored_choice, encounter
    from engine.games.validation import validate_story
    from engine.world import law

    deeds = law.load_spec()["deeds"]
    scenes = {row["id"] for row in encounter.all_encounters()}
    for choice_id in ("a", "b", "c"):
        assert authored_choice.problems(_opening_row(choice_id), deeds=deeds,
                                        encounters=scenes) == [], choice_id
    assert not [i for i in validate_story("hue-and-cry") if "entry.opening" in i.ref_id]

    run = authored_choice.bound(_opening_row("a"))
    assert run["deed"] == "resisting_watch"
    assert run["on_fail"]["encounter"] == "watch_stop"
    talk = authored_choice.bound(_opening_row("b"))
    assert "deed" not in talk and not talk["on_pass"]["effects"]
    assert [e["type"] for e in talk["on_fail"]["effects"]] == ["report"]
    quiet = authored_choice.bound(_opening_row("c"))
    assert "intent" not in _opening_row("c")
    assert [e["type"] for e in quiet["on_pass"]["effects"]] == ["report", "arrest", "flag"]
    assert "adjustments" not in run and "adjustments" not in talk and "adjustments" not in quiet


def test_going_quietly_says_it_arrests_before_it_is_taken(hue) -> None:
    """Rule 1: choice (c) declares no intent -- an arrest is not a verb the
    grammar offers -- yet it takes the player to the Lantern House. Its chip
    is read from its authored `on_pass`, so the button says so first."""
    from engine.scenes.default_state import opening

    choices = {c["id"]: c for c in opening(_city(11))["choices"]}
    assert "intent" not in choices["c"]
    # The gaol's own name, the one the arrest receipt says ("taken to ...").
    assert choices["c"].get("intent_label") == "arrest · The Lantern House", choices["c"]
    # (b) arrests nobody; its chip stays the check's own.
    assert "arrest" not in str(choices["b"].get("intent_label") or "")


@pytest.mark.parametrize("slug", ["clockwork-dark", "wicked-garden", "neon-city",
                                  "the-long-con", "dev-story"])
def test_other_openings_are_labelled_exactly_as_before(slug) -> None:
    """Display only: a story with no authored opening consequences gets the
    same opening choices, byte for byte, as `_label_intents` alone gives."""
    import json

    from engine.scenes import default_state

    registry.activate(slug)
    state = _city(11)
    before = default_state._label_intents(state, default_state.opening_choices())
    after = default_state.opening(state)["choices"]
    assert json.dumps(after, sort_keys=True) == json.dumps(before, sort_keys=True)


def test_a_filed_run_is_noticed_on_the_quay_and_never_sought(hue) -> None:
    """Measured (law.yaml header, CHANGELOG [0.16.0]): a run a Lantern
    files leaves the Quay `noticed` into the next morning -- the narrator can
    feel it -- and never `sought` on its own; two mornings on, it has gone."""
    from engine.game.clock import advance_time
    from engine.world import law

    state = next(s for s in (_city(seed) for seed in range(20))
                 if law.commit_deed(s, "resisting_watch")["reported"])
    assert law.wanted_band(state, "self", "quay") == "noticed"
    advance_time(state, 24.0)  # the next morning
    assert law.wanted_band(state, "self", "quay") == "noticed"
    # The morning after, it crosses `noticed`'s floor within the hour (the
    # harness reads it at 08:00, a hair under); a day and a half on, clear.
    advance_time(state, 30.0)
    assert law.wanted_band(state, "self", "quay") == "unknown"
    deeds = law.load_spec()["deeds"]
    assert deeds["fencing"] < deeds["resisting_watch"] < deeds["assault_watch"]


def test_a_clean_run_slips_away_with_the_deed_on_the_quays_book(barge, monkeypatch) -> None:
    from engine.game import encounter
    from engine.world import law

    _force(monkeypatch, "success")
    payload = _take_opening(barge, "a")
    state = barge.engine.state
    receipt = _authored_receipt(payload)
    assert receipt["passed"] is True and receipt["scene"] is False
    assert not encounter.active(state) and not law.in_custody(state)
    assert state.location_id == "tallow_docks"
    # Committed through commit_deed: witness rows rolled on LAW, and a Lantern
    # who saw it files it on the Quay, in the player's own face.
    assert {w["deed"] for w in state.law.get("witnessed") or []} == {"resisting_watch"}
    for row in state.law.get("reports") or []:
        assert (row["deed"], row["guise"], row["jurisdiction"]) == ("resisting_watch", "self", "quay")


def test_a_failed_run_is_the_lanterns_stop(barge, monkeypatch) -> None:
    from engine.game import encounter
    from engine.world import law

    _force(monkeypatch, "failure")
    payload = _take_opening(barge, "a")
    state = barge.engine.state
    assert _authored_receipt(payload)["scene"] is True
    assert encounter.active(state) and state.encounter["id"] == "watch_stop"
    assert not law.in_custody(state)
    assert {w["deed"] for w in state.law.get("witnessed") or []} == {"resisting_watch"}
    offered = {a["id"] for a in encounter.available_approaches(state)}
    assert {"run", "talk", "surrender"} <= offered


def test_talking_him_down_files_nothing(barge, monkeypatch) -> None:
    from engine.world import law

    _force(monkeypatch, "success")
    payload = _take_opening(barge, "b")
    state = barge.engine.state
    assert _authored_receipt(payload)["passed"] is True
    assert not state.law.get("reports") and not state.law.get("witnessed")
    assert not law.in_custody(state)


def test_a_failed_talk_files_the_magpie_blurred(barge, monkeypatch) -> None:
    from engine.game import encounter
    from engine.world import law

    _force(monkeypatch, "failure")
    payload = _take_opening(barge, "b")
    state = barge.engine.state
    assert _authored_receipt(payload)["passed"] is False
    rows = state.law.get("reports") or []
    assert [(r["guise"], r["jurisdiction"], r["precision"]) for r in rows] == [("magpie", "quay", 0.3)]
    assert not law.in_custody(state) and not encounter.active(state)
    assert state.location_id == "tallow_docks"


def test_coming_quietly_is_an_arrest_on_the_quay(barge) -> None:
    from engine.game.locations import is_known
    from engine.world import law

    payload = _take_opening(barge, "c")
    state = barge.engine.state
    assert _authored_receipt(payload)["passed"] is True
    assert law.in_custody(state) and state.location_id == "lantern_house"
    held = law.custody(state)
    # A small fine or a short sentence: the Lantern's one blurred charge.
    assert held["jurisdiction"] == "quay"
    assert (held["fine"], held["days"]) == (3, 1)
    assert held["fine"] <= state.stats.gold
    assert is_known(state, "the_undercroft")  # every arrest learns the drain


def _answer_and_walk(session, target: str = "the_snuffs", budget: int = 8) -> int:
    """Answer whatever holds the player, then walk; the actions it took.

    A card the director dealt (since v0.16 T5, the interrogation on every
    arrest) is answered roll-free and NOT counted: the budget is the walk and
    the way out of the cells, and the small room is its own scene
    (`test_coming_quietly_walks_straight_into_the_small_room`)."""
    from engine.agents.tool_dispatcher import execute_intent
    from engine.content import director
    from engine.game import encounter
    from engine.game.intents import find_verb, legal_intents
    from engine.world import law

    state = session.engine.state
    cards = 0
    while director.active(state) and cards < 8:
        cards += 1
        card = director.current_card(state)
        beat = next((str(b["id"]) for b in card.beats if _roll_free(b)), "resolve")
        if "menu" not in card.tags:
            beat = "resolve"
        execute_intent({"action": "card", "target": beat}, session.engine)
    for spent in range(budget):
        if encounter.active(state):
            offered = [a["id"] for a in encounter.available_approaches(state)]
            execute_intent({"action": "encounter",
                            "target": "surrender" if "surrender" in offered else offered[0]},
                           session.engine)
        elif law.in_custody(state):
            fine = int(law.custody(state).get("fine") or 0)
            execute_intent({"action": "pay_fine" if state.stats.gold >= fine else "serve"},
                           session.engine)
        elif state.location_id == target:
            return spent
        else:
            step = _next_street(state.location_id, target)
            verb = find_verb(legal_intents(state), "travel")
            assert verb is not None and step in verb.targets, (state.location_id, verb)
            execute_intent({"action": "travel", "target": step}, session.engine)
    return budget


def _next_street(start: str, goal: str) -> str:
    """The first leg of the shortest walk over public streets."""
    from collections import deque

    back: dict[str, str] = {start: ""}
    queue = deque([start])
    while queue:
        here = queue.popleft()
        for there in (LOCATIONS.get(here) or {}).get("connections") or {}:
            if there in back or there in SECRET_DISTRICTS:
                continue
            back[there] = here
            queue.append(there)
    step = goal
    while back.get(step) and back[step] != start:
        step = back[step]
    return step


@pytest.mark.parametrize("choice_id,degree", [
    ("a", "success"), ("a", "failure"), ("b", "success"), ("b", "failure"), ("c", "success"),
])
def test_every_opening_reaches_the_snuffs(barge, monkeypatch, choice_id, degree) -> None:
    """Act I's next beat is the guild finding you in the Snuffs (Task 4 deals
    it). Every way off the barge leaves the player free to walk there within
    a few turns: a getaway walks, a stop is answered, a cell is paid out of."""
    from engine.world import law

    _force(monkeypatch, degree)
    _take_opening(barge, choice_id)
    spent = _answer_and_walk(barge)
    state = barge.engine.state
    assert state.location_id == "the_snuffs" and not law.in_custody(state), spent
    assert spent <= 4, spent


def test_the_opening_names_no_magpie_candidate(barge) -> None:
    """Spec §6: nothing names or implies the real Magpie before the reveal --
    not the opening's prose, its buttons or its authored lines."""
    import json

    opening = registry.get("hue-and-cry").entry["opening"]
    texts = [opening["narration"], json.dumps(barge.last_turn.get("choices"))]
    for row in opening["choices"]:
        texts.append(row["text"])
        for branch in ("on_pass", "on_fail"):
            texts.append(str((row.get(branch) or {}).get("text") or ""))
    for text in texts:
        assert not any(word in text.lower() for word in _CANDIDATE_WORDS), text


@pytest.mark.parametrize("choice_id,degree", [
    ("a", "success"), ("a", "failure"), ("b", "failure"), ("c", "success"),
])
def test_what_the_narrator_is_handed_names_no_candidate(barge, monkeypatch, choice_id,
                                                        degree) -> None:
    """The receipts block for each outcome: the authored line reaches it,
    and nothing in it names a candidate or an engine id."""
    from engine.agents import prompts

    _force(monkeypatch, degree)
    payload = _take_opening(barge, choice_id)
    block = prompts.receipts_block(payload.get("tool_receipts") or [])
    line = str(_authored_receipt(payload)["text"])
    assert line and line in block
    lowered = block.lower()
    assert "authored_choice" not in lowered and "resisting_watch" not in lowered
    assert not any(word in lowered for word in _CANDIDATE_WORDS), block


def test_an_opening_replays_from_its_seed(quay_saves) -> None:
    """Same seed, same choice: the same witnesses, reports and scene -- the
    deed's rolls are the LAW stream's, not the wall clock's -- and a save
    carries them whole."""
    from engine.game.state import GameState

    def one(seed: int):
        session = _opening_session(seed)
        _take_opening(session, "a")
        return session.engine.state

    for seed in (3, 7):
        first, second = one(seed), one(seed)
        assert first.law.get("witnessed"), seed
        assert (first.law, first.encounter, first.location_id) == (
            second.law, second.encounter, second.location_id), seed
        loaded = GameState.from_dict(first.to_save_dict())
        assert (loaded.law, loaded.encounter) == (first.law, first.encounter)


# ---------------------------------------------------------------------------
# The Honest Company takes you in (v0.16 Task 4): Mother Gannet's initiation
# ---------------------------------------------------------------------------

#: The deck's id (data/scenes/initiation.yaml). The Company's two gifts that
#: wait for its oath are the guild bunk and Gannet's contract; the bench, the
#: flophouse and a rough night do not wait for anything.
INITIATION = "initiation"


def _in_the_hall(seed: int = 9, hour: int = 20):
    """A fresh city with the thief standing in the Snuffs while Gannet holds court."""
    from engine.game.clock import set_clock

    state = _city(seed)
    state.location_id = "the_snuffs"
    set_clock(state, day=1, hour=hour)
    return state


def _initiation_deck():
    from engine.content import deck

    found = deck.load_deck(INITIATION)
    assert found is not None, "no initiation deck"
    return found


def _play_initiation(state, picks: dict | None = None) -> list[dict]:
    """Deal the initiation where it stands and answer every card: ``picks``
    names a card's beat, otherwise its first option. The receipts, in order."""
    from engine.content import director

    dealt = director.ensure_scene(state)
    assert dealt and dealt[0]["result"]["deck_id"] == INITIATION, dealt
    receipts = []
    guard = 0
    while director.active(state) and guard < 16:
        guard += 1
        card = director.current_card(state)
        chosen = (picks or {}).get(card.id) or director.options(state)[0]["id"]
        receipts.append(director.resolve(state, chosen=chosen))
    assert not director.active(state)
    return receipts


def _roll_free(beat: dict) -> bool:
    """A beat that asks no dice and no threshold: text, or a gate with neither."""
    gate = beat.get("gate")
    if "band" in beat:
        return True  # a band is judged, never failed
    return gate is None or (not gate.get("check") and "when" not in gate)


def test_the_initiation_is_a_one_shot_deck(hue) -> None:
    from engine.content import deck
    from engine.games.validation import validate_story

    # Since v0.16 T5 the interrogation ships beside it (its own section below).
    assert INITIATION in deck.deck_ids()
    found = _initiation_deck()
    assert found.repeatable is False  # dealt once, never re-armed
    for card in found.cards:
        # The menu/sequence contract, and nothing clamped at load.
        assert (deck.MENU_TAG in card.tags) != ("sequence" in card.tags), card.id
        for beat in card.beats:
            assert "adjustments" not in beat, (card.id, beat)
    issues = [i for i in validate_story("hue-and-cry")
              if "scenes" in str(i.ref_id) or INITIATION in str(i.ref_id)]
    assert issues == [], issues


def test_the_initiation_is_dealt_in_the_snuffs_while_gannet_holds_court(hue) -> None:
    """At the Snuffs, free, not yet sworn, and while Gannet holds court at the
    long table (npc_schedules.yaml: 18:00-04:00) -- not while she sleeps or
    does the accounts, and nowhere else."""
    from engine.content import director
    from engine.game.clock import set_clock

    state = _city(9)
    set_clock(state, day=1, hour=8)
    assert director.ensure_scene(state) == []  # on the quay, off the barge
    state.location_id = "wickmarket"
    set_clock(state, day=1, hour=20)
    assert director.ensure_scene(state) == []
    state.location_id = "the_snuffs"
    set_clock(state, day=1, hour=10)
    assert director.ensure_scene(state) == []  # she is asleep behind four locks
    set_clock(state, day=1, hour=12)
    assert director.ensure_scene(state) == []  # the accounts, in two ledgers
    set_clock(state, day=1, hour=17)
    assert director.ensure_scene(state) == []
    set_clock(state, day=1, hour=18)
    dealt = director.ensure_scene(state)
    assert dealt and dealt[0]["result"]["ok"], dealt
    assert dealt[0]["result"]["deck_id"] == INITIATION


def test_the_initiation_is_not_dealt_in_the_cells_or_to_the_sworn(hue) -> None:
    from engine.content import director
    from engine.game.effects import apply_effect
    from engine.world import law

    state = _in_the_hall()
    state.flags["guild_initiated"] = True
    assert director.ensure_scene(state) == []

    state = _in_the_hall()
    apply_effect(state, {"type": "report", "deed": "pickpocket", "guise": "self",
                         "jurisdiction": "wick", "precision": 1.0})
    apply_effect(state, {"type": "arrest"})
    assert law.in_custody(state)
    state.location_id = "the_snuffs"  # held, wherever the test says it stands
    dealt = director.ensure_scene(state)
    # The cells deal the interrogation (v0.16 T5), never the Company's welcome.
    assert [r["result"]["deck_id"] for r in dealt] == ["interrogation"], dealt


def test_the_initiation_is_dealt_once_and_never_over_a_job(hue, monkeypatch) -> None:
    from engine.content import director
    from engine.world import jobs

    state = _in_the_hall()
    monkeypatch.setattr(jobs, "active", lambda _state: {"house": "somewhere"})
    assert director.ensure_scene(state) == []  # the job owns the turn
    monkeypatch.undo()
    _play_initiation(state)
    state.flags["guild_initiated"] = False  # even unsworn again, it is spent
    assert director.ensure_scene(state) == []


def test_every_initiation_card_has_a_way_through_without_a_roll(hue) -> None:
    for card in _initiation_deck().cards:
        if "menu" in card.tags:
            assert any(_roll_free(b) for b in card.beats), card.id
        else:
            assert all(_roll_free(b) for b in card.beats), card.id


def _every_path():
    """Every menu answer the required cards offer, one card at a time."""
    rows = []
    for card in _initiation_deck().cards:
        if "menu" in card.tags and card.required:
            rows += [(card.id, str(b["id"])) for b in card.beats]
    return rows


@pytest.mark.parametrize("degree", ["success", "failure"])
def test_initiation_always_takes_you_in(hue, monkeypatch, degree) -> None:
    """Whichever way the cards fall -- every answer, every roll passed or
    failed, on seeds that deal either pool card -- the thief is sworn, and
    Act II opens."""
    from engine.game.quests import QuestEngine

    _force(monkeypatch, degree)
    paths = _every_path()
    assert paths
    for seed, (card_id, beat_id) in enumerate(paths * 2):
        state = _in_the_hall(seed)
        _play_initiation(state, {card_id: beat_id})
        assert state.flags.get("guild_initiated") is True, (card_id, beat_id)
        assert state.reputations.get("honest_company", 0) >= 1, (card_id, beat_id)
        QuestEngine.evaluate(state, None)
        assert state.active_arc == "honest_work", (card_id, beat_id)


def _standing_after(monkeypatch, degree: str, picks: dict) -> int:
    _force(monkeypatch, degree)
    state = _in_the_hall()
    _play_initiation(state, picks)
    monkeypatch.undo()
    return int(state.reputations.get("honest_company", 0))


def test_the_rolls_decide_how_warmly_the_company_takes_you_in(hue, monkeypatch) -> None:
    """The dice buy standing, never the oath: a thief who wins every roll
    starts warmer than one who takes the roll-free way, who starts warmer than
    one who fails every roll -- and all three are in."""
    deck = _initiation_deck()
    rolled = {c.id: next(str(b["id"]) for b in c.beats if not _roll_free(b))
              for c in deck.cards
              if "menu" in c.tags and any(not _roll_free(b) for b in c.beats)}
    free = {c.id: next(str(b["id"]) for b in c.beats if _roll_free(b))
            for c in deck.cards if "menu" in c.tags}
    best = _standing_after(monkeypatch, "success", rolled)
    plain = _standing_after(monkeypatch, "success", free)
    worst = _standing_after(monkeypatch, "failure", rolled)
    assert best > plain > worst >= 1, (best, plain, worst)
    assert best <= 10, best  # a welcome, not a promotion


def test_the_guild_bunk_and_gannets_job_wait_for_the_oath(hue) -> None:
    from engine.game import survival, threads

    state = _in_the_hall(hour=22)
    assert state.reputations.get("honest_company", 0) == 0
    assert survival.rest(state, "sleep_guild_bunk")["kind"] == "sleep_rough"
    assert threads.can_strike(state, "gannet_silk_row") is False
    refusal = threads.strike_refusal(state, "gannet_silk_row")
    assert refusal != threads.REFUSED_HERE and "oath" in refusal.lower(), refusal
    # Both say when the Company receives: the narrator and the player can
    # tell a door that opens after dark from one that never will.
    assert "after dark" in refusal.lower(), refusal
    bunk = survival.rest(_in_the_hall(hour=10), "sleep_guild_bunk")
    assert bunk["kind"] == "sleep_rough" and "after dark" in bunk["text"].lower(), bunk

    state = _in_the_hall(hour=22)
    state.flags["guild_initiated"] = True
    assert survival.rest(state, "sleep_guild_bunk")["kind"] == "sleep_guild_bunk"
    assert threads.can_strike(state, "gannet_silk_row") is True


def test_rest_and_the_bench_stay_open_to_the_unsworn(hue) -> None:
    """Rule 6: the bunk may wait for the oath only because the flophouse and a
    rough night never do -- and the Porters' Hall bench is paid bench time,
    open to anyone (the v0.15 hoarder and the craft verb rely on it)."""
    from pathlib import Path

    from engine.game import intents, survival

    state = _in_the_hall(hour=22)
    state.stats.gold = 5
    assert survival.rest(state, "sleep_flophouse")["kind"] == "sleep_flophouse"
    assert survival.rest(state, "sleep_rough")["kind"] == "sleep_rough"
    for district in DISTRICTS:
        if district in SECRET_DISTRICTS:
            continue
        state.location_id = district
        verb = intents.find_verb(intents.legal_intents(state), "rest")
        assert verb is not None and "sleep_rough" in verb.targets, district
    root = Path(__file__).resolve().parents[1]
    paths = registry.get("hue-and-cry").paths
    text = (root / paths["rules"] / "survival.yaml").read_text(encoding="utf-8")
    for bed in ("  sleep_flophouse:", "  sleep_rough:", "  rest_short:", "  sleep_cell:"):
        block = text.split(bed, 1)[1].split("\n  sleep_", 1)[0]
        assert "guild_initiated" not in block, bed
    for recipe in (root / paths["recipes"]).glob("*.yaml"):
        assert "guild_initiated" not in recipe.read_text(encoding="utf-8"), recipe


def test_the_initiation_names_no_magpie_candidate(hue) -> None:
    """Spec §6: Gannet believes the stranger is the Magpie; she may tell the
    legend, and nothing on any card points at who the real one is."""
    import json

    found = _initiation_deck()
    for card in found.cards:
        text = json.dumps([card.title, card.text, card.beats]).lower()
        assert not any(word in text for word in _CANDIDATE_WORDS), card.id
    assert "magpie" in json.dumps([c.text for c in found.cards]).lower()


def _plain_turn(session, action: str = "The player looks about the Hall.") -> dict:
    from engine.scenes.default_state import run_turn

    return run_turn(session, action)


@pytest.mark.parametrize("choice_id,degree", [("a", "success"), ("b", "failure"),
                                              ("c", "success")])
def test_every_way_off_the_barge_meets_the_company_in_the_snuffs(barge, monkeypatch,
                                                                 choice_id, degree) -> None:
    """End to end through run_turn: the opening, then the walk to the Snuffs,
    then the first turn there while Gannet holds court deals the initiation. Coming
    quietly meets it after release, never in the cell."""
    from engine.game.clock import advance_time
    from engine.world import law

    _force(monkeypatch, degree)
    _take_opening(barge, choice_id)
    state = barge.engine.state
    if law.in_custody(state):
        # The cell deals the interrogation (v0.16 T5), and never the Company.
        assert state.scene.get("deck_id") == "interrogation", state.scene
        payload = _plain_turn(barge, "The player waits in the cell.")
        assert payload["state"]["scene"].get("deck_id") != INITIATION, "dealt in the cell"
    _answer_and_walk(barge)
    assert state.location_id == "the_snuffs"
    advance_time(state, (18 - state.world_hour) % 24)  # until Gannet holds court
    payload = _plain_turn(barge)
    dealt = [r for r in payload["tool_receipts"] if r.get("type") == "scene"]
    assert dealt and dealt[0]["result"]["deck_id"] == INITIATION, payload["tool_receipts"]


def test_the_bunk_harness_takes_the_oath_as_a_player_would(hue) -> None:
    """simulate_labour's `bunk` policy relied on the guild bunk from its first
    night; since the bunk waits for the oath, the harness deals the initiation
    the way run_turn does and answers it roll-free, then sleeps upstairs. The
    other beds never deal it, and every policy reports the day it was due."""
    _scripts_on_path()
    from scripts import simulate_labour, simulate_law

    with simulate_law.agendas_off():
        bunk = simulate_labour.play(0, "porter", 1, "bunk")
        flop = simulate_labour.play(0, "porter", 1, "flophouse")
    assert bunk.initiated_day == 1 and bunk.bed_nights == bunk.days, bunk
    assert flop.initiated_day is None and flop.initiation_due_day == 1, flop


def test_the_initiation_waits_for_a_lanterns_stop_to_end(hue) -> None:
    """Review, fix round 1: a patrol runs before the deal in run_turn, so a
    Lantern could stop a wanted thief entering the Snuffs and the deck was
    then dealt over the open stop -- `card` the only verb, the stop hanging.
    The deal waits for the stop; it is not spent by waiting."""
    from engine.content import director
    from engine.game import encounter, intents

    state = _in_the_hall(9, hour=20)
    encounter.begin(state, "watch_stop")
    assert encounter.active(state)
    assert director.ensure_scene(state) == []
    assert director.active(state) is False
    assert intents.find_verb(intents.legal_intents(state), "encounter") is not None
    assert not state.flags.get("deck_played_initiation")

    encounter.end(state)
    dealt = director.ensure_scene(state)
    assert dealt and dealt[0]["result"]["deck_id"] == INITIATION, dealt


# ---------------------------------------------------------------------------
# The small room (v0.16 Task 5): the interrogation, dealt on every arrest
# ---------------------------------------------------------------------------

#: The deck's id (data/scenes/interrogation.yaml): scheduled by
#: `in_custody: true`, repeatable, so every stay in the cells deals it once.
INTERROGATION = "interrogation"
#: The three interrogators, exactly one eligible at any hour.
CAPTAIN, SERGEANT, DUTY_DESK = "Q2_the_captain", "Q2_the_sergeant", "Q2_the_duty_desk"
#: One hour inside each interrogator's window.
_ASKED_AT = {CAPTAIN: 8, SERGEANT: 16, DUTY_DESK: 14}


def _interrogation_deck():
    from engine.content import deck

    found = deck.load_deck(INTERROGATION)
    assert found is not None, "no interrogation deck"
    return found


def _arrested(seed: int = 9, hour: int = 8, *, gold: int = 50):
    """A thief with one petty lift on file in the Wick wards, arrested there
    at ``hour`` -- a fine of three crowns or a day, and crowns to pay it."""
    from engine.game.clock import set_clock
    from engine.game.effects import apply_effect
    from engine.world import law

    state = _city(seed)
    state.location_id = "wickmarket"
    set_clock(state, day=2, hour=hour)
    state.stats.gold = gold
    apply_effect(state, {"type": "report", "deed": "pickpocket", "guise": "self",
                         "jurisdiction": "wick", "precision": 1.0})
    assert apply_effect(state, {"type": "arrest"})["ok"]
    assert law.in_custody(state) and state.location_id == "lantern_house"
    return state


def _play_interrogation(state, picks: dict | None = None) -> list[str]:
    """Deal the interrogation where it stands and answer every card; the ids
    of the cards answered. While a card is open the card is the only verb."""
    from engine.content import director

    dealt = director.ensure_scene(state)
    assert dealt and dealt[0]["result"]["deck_id"] == INTERROGATION, dealt
    answered = []
    guard = 0
    while director.active(state) and guard < 16:
        guard += 1
        assert _verbs(state) == {"card"}  # pay_fine and serve are hidden
        card = director.current_card(state)
        answered.append(card.id)
        chosen = (picks or {}).get(card.id) or director.options(state)[0]["id"]
        director.resolve(state, chosen=chosen)
    assert not director.active(state)
    return answered


def _verbs(state) -> set:
    from engine.game import intents

    return {v.action for v in intents.legal_intents(state)}


def test_hue_and_cry_ships_the_interrogation_and_it_deals_again(hue) -> None:
    from engine.content import deck
    from engine.games.validation import validate_story

    # v0.17 T3 added the fair and the gallows (their own section, below);
    # T6 the Porters' Hall and the confrontation; T8's fix round 1 the last job.
    assert deck.deck_ids() == ["fair_day", INITIATION, INTERROGATION, DESK, "porters_hall",
                               "the_confrontation", "the_gallows", "the_last_job"]
    found = _interrogation_deck()
    assert found.repeatable is True  # every arrest, not the first
    assert found.when == {"in_custody": True}
    assert [c.id for c in found.required] == ["Q1_the_book"]
    # Task 7 filled Q4_the_alibi and released Q3_the_evidence (the header);
    # Task 8 split the alibi by what the Watch believes (the _struck card).
    assert {c.id for c in found.pool} == {CAPTAIN, SERGEANT, DUTY_DESK, "Q4_the_alibi",
                                          "Q4_the_alibi_struck"}
    # Room for the interrogator and the alibi, so the alibi never makes the
    # hand a random draw.
    assert found.draw >= 2
    for card in found.cards:
        assert (deck.MENU_TAG in card.tags) != ("sequence" in card.tags), card.id
        for beat in card.beats:
            assert "adjustments" not in beat, (card.id, beat)
    issues = [i for i in validate_story("hue-and-cry") if INTERROGATION in str(i.source)
              or INTERROGATION in str(i.ref_id)]
    assert issues == [], issues


def test_nothing_on_an_interrogation_card_was_cut_to_fit(hue) -> None:
    """The loader truncates text past deck.MAX_TEXT without a word; a card
    whose constraints were cut off is a narrator told half the rules."""
    from pathlib import Path

    import yaml

    from engine.content import deck

    root = Path(__file__).resolve().parents[1]
    raw = yaml.safe_load((root / registry.get("hue-and-cry").paths["decks"]
                          / f"{INTERROGATION}.yaml").read_text(encoding="utf-8"))
    for card in raw["cards"]:
        assert len(card["text"].strip()) <= deck.MAX_TEXT, card["id"]
        for beat in card["beats"]:
            assert len(str(beat.get("text") or "").strip()) <= deck.MAX_TEXT, beat["id"]
            for branch in ("on_pass", "on_fail"):
                line = str(((beat.get("gate") or {}).get(branch) or {}).get("text") or "")
                assert len(line.strip()) <= deck.MAX_TEXT, (beat["id"], branch)


def test_exactly_one_interrogator_asks_at_every_hour_and_the_schedule_agrees(hue) -> None:
    """Captain Ardane when she is in the Lantern House and awake; Sergeant
    Brask when he is at its desk and she is not; the Lantern who brought you
    in when neither is -- read off npc_schedules.yaml, so a card never puts
    somebody in the room the schedule puts elsewhere."""
    from engine.content import deck
    from engine.game.clock import set_clock

    state = _arrested()
    found = _interrogation_deck()
    for hour in range(24):
        set_clock(state, day=2, hour=hour)
        eligible, _rejected = deck.eligible_cards(state, found)
        present = {p.npc_id for p in npc_sim.npcs_at(state, "lantern_house") if p.available}
        expected = (CAPTAIN if "npc_ardane" in present
                    else SERGEANT if "npc_brask" in present else DUTY_DESK)
        assert [c.id for c in eligible] == [expected], (hour, present)


def test_the_interrogation_is_dealt_on_arrest_and_only_in_custody(hue) -> None:
    from engine.content import director

    free = _in_the_hall(9, hour=10)  # the Snuffs, before Gannet holds court
    assert director.ensure_scene(free) == []
    for card_id, hour in _ASKED_AT.items():
        state = _arrested(hour=hour)
        dealt = director.ensure_scene(state)
        assert dealt and dealt[0]["result"]["card_ids"] == ["Q1_the_book", card_id], dealt


def _every_answer():
    rows = []
    for card_id, hour in _ASKED_AT.items():
        card = next(c for c in _interrogation_deck().cards if c.id == card_id)
        rows += [(card_id, hour, str(b["id"])) for b in card.beats]
    return rows


@pytest.mark.parametrize("degree", ["success", "failure"])
def test_no_held_thief_is_ever_stuck_in_the_small_room(hue, monkeypatch, degree) -> None:
    """While a card is open `pay_fine` and `serve` are hidden. Every answer on
    every interrogator's card, every roll passed and failed: the hand ends,
    both ways out come back, the sentence is what the door said, and serving
    it ends custody."""
    from engine.world import law

    _force(monkeypatch, degree)
    rows = _every_answer()
    assert len(rows) == 8, rows
    for card_id, hour, beat_id in rows:
        state = _arrested(hour=hour)
        sentence = (law.custody(state)["fine"], law.custody(state)["days"])
        answered = _play_interrogation(state, {card_id: beat_id})
        assert answered == ["Q1_the_book", card_id]
        assert {"pay_fine", "serve"} <= _verbs(state), (card_id, beat_id)
        held = law.custody(state)
        assert (held["fine"], held["days"]) == sentence, (card_id, beat_id)  # it stands
        assert law.serve_sentence(state)["ok"]
        assert not law.in_custody(state), (card_id, beat_id)


def test_every_interrogation_card_has_a_way_through_without_a_roll(hue) -> None:
    """A menu card offers one answer with no dice and no threshold; the
    sequence card asks no dice at all (its one gate reads the Watch's belief,
    and both branches only say it)."""
    for card in _interrogation_deck().cards:
        if "menu" in card.tags:
            assert any(_roll_free(b) for b in card.beats), card.id
        else:
            for beat in card.beats:
                gate = beat.get("gate") or {}
                assert not gate.get("check"), (card.id, beat["id"])
                for branch in ("on_pass", "on_fail"):
                    assert not (gate.get(branch) or {}).get("effects"), (card.id, beat["id"])


def _rows(state) -> list:
    return sorted((r["deed"], r["guise"], r["jurisdiction"], r["precision"])
                  for r in state.law.get("reports") or [])


def _thick_file(hour: int = 8):
    """Held in the Wick, with petty sheets filed in three jurisdictions and a
    burglary up the Rise that no answer can lose."""
    from engine.game.effects import apply_effect

    state = _arrested(hour=hour)
    for deed, jurisdiction in (("pickpocket", "rise"), ("pickpocket", "quay"),
                               ("burglary", "rise")):
        apply_effect(state, {"type": "report", "deed": deed, "guise": "self",
                             "jurisdiction": jurisdiction, "precision": 1.0})
    return state


def test_what_the_room_can_do_to_the_file(hue, monkeypatch) -> None:
    """Quashed, kept or added -- and never the sentence. A good answer to the
    captain loses every petty sheet against your face; a steady eye loses the
    Wick's; a lie caught writes one more lift into the Magpie's file; a plain
    answer changes nothing. A house broken stays filed whatever is said."""
    from engine.world import law

    def after(degree: str, beat: str, card: str = CAPTAIN):
        _force(monkeypatch, degree)
        state = _thick_file(_ASKED_AT[card])
        sentence = dict(law.custody(state))
        _play_interrogation(state, {card: beat})
        monkeypatch.undo()
        assert law.custody(state) == sentence
        return _rows(state)

    before = _rows(_thick_file())
    burglary = [("burglary", "self", "rise", 1.0)]
    assert after("success", "talk_her_round") == burglary
    assert after("success", "hold_her_eye") == [r for r in before if r[2] != "wick"]
    assert after("failure", "talk_her_round") == sorted(
        before + [("pickpocket", "magpie", "rise", 1.0)])
    assert after("failure", "hold_her_eye") == sorted(
        before + [("pickpocket", "magpie", "rise", 0.6)])
    assert after("success", "answer_straight") == before
    assert after("failure", "answer_straight") == before
    assert after("success", "the_biscuit_tin", SERGEANT) == burglary
    assert after("failure", "stare_him_out", SERGEANT) == sorted(
        before + [("pickpocket", "magpie", "wick", 0.3)])
    assert after("failure", "sleep_on_it", DUTY_DESK) == before


def test_a_lie_in_the_magpies_file_is_yours_while_the_watch_links_you(hue, monkeypatch) -> None:
    """The added row is filed against the MAGPIE: it weighs on your face
    exactly as long as the Watch takes the two for one person."""
    from engine.game.effects import apply_effect
    from engine.world import law

    _force(monkeypatch, "failure")
    state = _arrested()
    _play_interrogation(state, {CAPTAIN: "talk_her_round"})
    assert law.wanted_score(state, "self", "rise") > 0
    assert apply_effect(state, {"type": "law_unlink", "a": "self", "b": "magpie"})["ok"]
    assert law.wanted_score(state, "self", "rise") == 0


def _beat_text(receipt) -> str:
    import json

    return json.dumps(receipt)


def test_the_file_says_what_the_watch_believes(hue) -> None:
    """The spine restates the link: while it holds the file says MAGPIE; once
    something breaks it (Task 7), the same beat says so instead."""
    from engine.content import director
    from engine.game.effects import apply_effect

    state = _arrested()
    director.ensure_scene(state)
    text = _beat_text(director.resolve(state))
    assert "THE MAGPIE" in text, text

    state = _arrested()
    assert apply_effect(state, {"type": "law_unlink", "a": "self", "b": "magpie"})["ok"]
    director.ensure_scene(state)
    text = _beat_text(director.resolve(state))
    assert "THE MAGPIE" not in text and "line drawn through" in text, text


def test_the_interrogation_deals_again_on_the_next_arrest_and_not_twice_a_stay(hue) -> None:
    from engine.content import director
    from engine.game.clock import advance_time
    from engine.game.effects import apply_effect
    from engine.world import law

    state = _arrested()
    _play_interrogation(state)
    assert director.ensure_scene(state) == []  # still held: spent
    advance_time(state, 12)
    assert director.ensure_scene(state) == []  # still held, half a day on
    assert law.pay_fine(state)["ok"] and not law.in_custody(state)
    assert director.ensure_scene(state) == []  # free: re-armed, nothing to deal
    assert not state.flags.get("deck_played_interrogation")
    apply_effect(state, {"type": "report", "deed": "pickpocket", "guise": "self",
                         "jurisdiction": "wick", "precision": 1.0})
    assert apply_effect(state, {"type": "arrest"})["ok"]
    _play_interrogation(state)  # the second arrest deals it again


def test_the_small_room_survives_a_save(hue) -> None:
    """Dealt, half-answered, saved and loaded: the same card is waiting, the
    deck is still spent for this stay, and it re-arms after release."""
    from engine.content import director
    from engine.game.state import GameState
    from engine.world import law

    state = _arrested()
    director.ensure_scene(state)
    director.resolve(state)  # the book
    loaded = GameState.from_dict(state.to_save_dict())
    assert director.active(loaded) and director.current_card(loaded).id == CAPTAIN
    assert _verbs(loaded) == {"card"}
    director.resolve(loaded, chosen="answer_straight")
    assert director.ensure_scene(loaded) == []
    reloaded = GameState.from_dict(loaded.to_save_dict())
    assert reloaded.flags.get("deck_played_interrogation") is True
    assert law.pay_fine(reloaded)["ok"]
    director.ensure_scene(reloaded)
    assert not reloaded.flags.get("deck_played_interrogation")


def test_an_arrest_replays_to_the_same_room(hue, monkeypatch) -> None:
    """Same seed, same hour, same answer: the same hand and the same file."""
    def one():
        state = _arrested(seed=5, hour=19)
        _play_interrogation(state, {CAPTAIN: "talk_her_round"})
        return state

    first, second = one(), one()
    assert first.law.get("reports") and first.rng_counters
    assert (first.law, first.rng_counters) == (second.law, second.rng_counters)


def test_the_small_room_names_no_magpie_candidate(hue) -> None:
    import json

    found = _interrogation_deck()
    for card in found.cards:
        text = json.dumps([card.title, card.text, card.beats]).lower()
        assert not any(word in text for word in _CANDIDATE_WORDS), card.id
    assert "magpie" in json.dumps([c.text for c in found.cards]).lower()


def _card_turn(session, beat: str = "") -> dict:
    """Answer the open card through run_turn, the way a player's choice does."""
    from engine.content import director
    from engine.scenes.default_state import run_turn

    chosen = beat or director.options(session.engine.state)[0]["id"]
    return run_turn(session, "The player answers.", intent={"action": "card", "target": chosen})


def _dealt(payload: dict) -> list:
    return [r["result"]["deck_id"] for r in payload.get("tool_receipts") or []
            if r.get("type") == "scene"]


@pytest.fixture()
def street(quay_saves):
    """A run in Wickmarket at 08:00 on day two, with a lift on file there."""
    from engine.game.clock import set_clock
    from engine.game.effects import apply_effect

    session = _opening_session(11)
    state = session.engine.state
    state.location_id = "wickmarket"
    set_clock(state, day=2, hour=8)
    state.stats.gold = 50
    apply_effect(state, {"type": "report", "deed": "pickpocket", "guise": "self",
                         "jurisdiction": "wick", "precision": 1.0})
    return session


def _stop_ends_in_arrest(session, approach: str) -> dict:
    from engine.game import encounter
    from engine.scenes.default_state import run_turn
    from engine.world import law

    state = session.engine.state
    encounter.begin(state, "watch_stop")
    payload = run_turn(session, "The player answers the Lantern.",
                       intent={"action": "encounter", "target": approach})
    assert law.in_custody(state), payload.get("tool_receipts")
    assert not encounter.active(state)
    return payload


@pytest.mark.parametrize("approach,degree", [("surrender", "success"), ("run", "failure")])
def test_a_lanterns_stop_that_ends_in_the_cells_ends_in_the_small_room(street, monkeypatch,
                                                                        approach, degree) -> None:
    """The real path, through run_turn: the stop is answered with a surrender
    or a fumbled run, the arrest closes the stop, and the interrogation is
    dealt on that same turn -- then again on the next arrest, after release."""
    from engine.content import director
    from engine.scenes.default_state import run_turn
    from engine.world import law

    _force(monkeypatch, degree)
    state = street.engine.state
    payload = _stop_ends_in_arrest(street, approach)
    assert _dealt(payload) == [INTERROGATION]
    guard = 0
    while director.active(state) and guard < 8:
        guard += 1
        assert _verbs(state) == {"card"}
        _card_turn(street)
    assert not director.active(state)
    assert {"pay_fine", "serve"} <= _verbs(state)
    run_turn(street, "The player pays.", intent={"action": "pay_fine"})
    assert not law.in_custody(state)
    assert not state.flags.get("deck_played_interrogation")  # re-armed on that turn

    payload = _stop_ends_in_arrest(street, approach)
    assert _dealt(payload) == [INTERROGATION], "the second arrest did not re-deal"


def test_coming_quietly_walks_straight_into_the_small_room(barge) -> None:
    """The opening's (c), end to end: the authored arrest, custody, and the
    interrogation dealt on the opening turn itself; answered, the fine is
    offered again and paid, and the thief walks out free."""
    from engine.content import director
    from engine.scenes.default_state import run_turn
    from engine.world import law

    payload = _take_opening(barge, "c")
    state = barge.engine.state
    assert law.in_custody(state)
    assert _dealt(payload) == [INTERROGATION]
    assert director.current_card(state).id == "Q1_the_book"
    assert _verbs(state) == {"card"}
    _card_turn(barge)
    assert director.current_card(state).id == CAPTAIN  # 08:00, at her desk
    _card_turn(barge, "answer_straight")
    assert not director.active(state) and {"pay_fine", "serve"} <= _verbs(state)
    run_turn(barge, "The player pays.", intent={"action": "pay_fine"})
    assert not law.in_custody(state)


def test_a_release_seen_only_under_a_lanterns_stop_still_rearms(hue) -> None:
    """Task 4's review: while an open encounter holds a deal back, is the
    repeatable deck's fall still seen? Released, then stopped by a Lantern
    before any turn saw the thief free: the director deals nothing over the
    stop, but re-arms under it -- so the arrest that ends the stop deals the
    small room again."""
    from engine.content import director
    from engine.game import encounter
    from engine.game.effects import apply_effect
    from engine.world import law

    state = _arrested()
    _play_interrogation(state)
    assert law.pay_fine(state)["ok"]  # no turn in between
    encounter.begin(state, "watch_stop")
    assert director.ensure_scene(state) == []  # the stop owns the turn
    assert not state.flags.get("deck_played_interrogation")  # ...but the fall was seen
    assert apply_effect(state, {"type": "arrest"})["ok"]
    encounter.end(state)
    _play_interrogation(state)


#: Reviewed and legitimate: each phrase has "the Magpie" and a sexed pronoun
#: in one window, and the pronoun belongs to somebody else. Matched against
#: the text around the hit, lower-cased. Add a row only after reading it.
_UNGENDERED_ALLOWED = (
    # The Lantern writes the Magpie into HIS book (the opening's talk branch).
    "the magpie into his book",
    # The Margrave's own desk (palace_wing.yaml's security line).
    "the margrave's snuffbox off his own",
    # Ardane's clock, after the people who saw the Magpie's face (agendas.yaml).
    "the magpie's face, and when her",
    # Silas, who lets the Snuffs wonder whether the new Magpie did it (agendas.yaml).
    "the new magpie did it, and he",
    # Ardane, whose reach the Magpie's file is heavy within (agendas.yaml).
    "the magpie's file is heavy anywhere she",
    # Ardane, to whom your file and the Magpie's are one (threads.yaml).
    "the magpie's are one file to her",
    # Ardane again, who feeds the petty sheets to the stove (interrogation.yaml).
    "in all those years, and she",
    # Brask's feet, not the Magpie's (interrogation.yaml, the biscuit tin).
    "the magpie -- his feet",
    # Gannet's thimble, in the README's initiation row.
    "(steal her thimble",
)


def test_the_magpie_is_never_given_a_sex(hue) -> None:
    """Spec §6 and the lore (data/lore/the_magpie.md): the Magpie is "a
    gentleman", "a lady", by turns -- the city does not know, and the real one
    is any of the three candidates. A pronoun that sexes the Magpie rules a
    candidate out, and genders the player the Watch takes for the Magpie (the
    player is "they", prompts/storyteller.md).

    Over everything in the story's tree the narrator or an author reads --
    YAML (comments included), lore, prompts, README and CHANGELOG -- no
    she/he/her/his/hers/him follows "Magpie" (or "Magpie's") within ten words
    of one sentence, whatever punctuation, dashes or backticks sit between;
    and nobody "has caught her" about the Magpie. A POSSESSIVE is read too: a
    pronoun after "the Magpie's file" is often somebody else's, but not
    always ("the Magpie's file ... links your face to hers" was a slip), so
    every such hit is either fixed or reviewed into `_UNGENDERED_ALLOWED`
    with its reason. Only the Magpie as the object of a preposition ("a
    warrant for the Magpie in her own hand") is skipped unread."""
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "games" / "hue-and-cry"
    pronoun = r"(?:she|he|her|his|hers|him|herself|himself)"
    # Anything but a letter or a sentence's end between words: commas,
    # dashes, parentheses and backticks do not end the window.
    gap = r"[^a-z.!?;:\"]+"
    in_clause = re.compile(r"\bmagpie\b(?:'s)?(?:" + gap + r"[a-z]+){0,10}?" + gap
                           + pronoun + r"\b")
    caught = re.compile(r"\bmagpie\b[^.!?]{0,80}?\b(?:caught|catch|catching|hunted|hunting|hunt"
                        r"|believes? (?:it|you|they) (?:has |have )?(?:caught|are|is)) "
                        r"(?:her|him)\b")
    preposition = re.compile(r"\b(?:of|for|at|about|to|with|by|from|on|into|as|than)"
                             r"\s+(?:the|a)\s+$")
    found = []
    paths = [p for p in root.rglob("*") if p.suffix in (".yaml", ".md") and "art" not in p.parts]
    assert any(p.name == "interrogation.yaml" for p in paths)
    assert any(p.name == "clues.yaml" for p in paths)
    # v0.17 T7: Act III's decks, quests, endings and epilogues are read too.
    assert {"fair_day.yaml", "the_gallows.yaml", "the_confrontation.yaml",
            "porters_hall.yaml", "the_heart_goes_home.yaml", "the_evening_barge.yaml",
            "endings.yaml", "death.yaml", "epilogue_cards.yaml",
            "epilogue_index.yaml"} <= {p.name for p in paths}
    for path in paths:
        lines = path.read_text(encoding="utf-8").splitlines()
        text = " ".join(re.sub(r"^\s*#\s?", "", line).strip() for line in lines).lower()
        for match in in_clause.finditer(text):
            if preposition.search(text[max(0, match.start() - 12):match.start()]):
                continue
            around = text[max(0, match.start() - 40):match.end() + 12]
            if any(ok in around for ok in _UNGENDERED_ALLOWED):
                continue
            found.append((path.name, match.group(0)))
        found += [(path.name, m.group(0)) for m in caught.finditer(text)]
    assert found == [], found


# ---------------------------------------------------------------------------
# The reveal and the alibi (v0.16 Task 7): the Lantern House front desk
# ---------------------------------------------------------------------------

#: data/scenes/lantern_house_desk.yaml -- walked into FREE, repeatable.
DESK = "lantern_house_desk"
ALIBI_CARD = "D1_the_alibi"
#: The same duty book once a right naming struck the word Magpie off the
#: file (v0.16 T8): the card says what the Watch believes.
STRUCK_CARD = "D1_the_alibi_struck"
#: The accusation, one card a suspect; the short name each card's id carries.
SUSPECTS = {"npc_wren": "wren", "npc_silas": "silas", "npc_imelda": "imelda"}
#: Each suspect's clue rows (data/premises/clues.yaml `points_to`).
CLUES_OF = {
    "npc_wren": ("wick_ends", "lamp_soot", "brass_ferrule", "ladder_feet", "snuffer_ring"),
    "npc_silas": ("pie_papers", "company_chit", "back_stair_mud", "taproom_token",
                  "porters_rota"),
    "npc_imelda": ("violet_wax", "gilded_taper", "appraisal_slip", "blue_tissue",
                   "place_card"),
}
#: The evidence bar (the deck's `value: {name: evidence, min: 2}`), MEASURED in
#: v0.16 T8 (scripts/simulate_acts.py; the desk's header has the reasoning).
EVIDENCE_BAR = 2


def _desk_deck():
    from engine.content import deck

    found = deck.load_deck(DESK)
    assert found is not None, "no front desk"
    return found


def _seed_for(magpie: str) -> int:
    from engine.world import agendas

    return next(s for s in range(200) if agendas.role(_city(s), "magpie") == magpie)


def _carry(state, *clue_ids: str) -> None:
    """Carry clues out of a house the way a getaway does: the engine's own
    ``clues.take`` (flag, meter, fresh flag)."""
    from engine.world import clues

    for cid in clue_ids:
        assert clues.take(state, {"id": f"prem_{cid}", "name": "a house", "clue": cid})


def _at_the_desk(seed: int, *, hour: int = 9, carried: tuple = ()):
    """A free thief standing in the Lantern House on day two at ``hour``."""
    from engine.game.clock import set_clock

    state = _city(seed)
    state.location_id = "lantern_house"
    set_clock(state, day=2, hour=hour)
    _carry(state, *carried)
    return state


def _desk_hand(state) -> list:
    """Deal what is due here; the card ids of the desk's hand, or []."""
    from engine.content import director

    dealt = director.ensure_scene(state)
    if not dealt or dealt[0]["result"].get("deck_id") != DESK:
        return []
    return list(dealt[0]["result"]["card_ids"])


def _answer_hand(state, picks: dict | None = None, ledger=None) -> list:
    from engine.content import director

    answered = []
    guard = 0
    while director.active(state) and guard < 8:
        guard += 1
        assert _verbs(state) == {"card"}
        card = director.current_card(state)
        answered.append(card.id)
        chosen = (picks or {}).get(card.id) or director.options(state)[0]["id"]
        receipt = director.resolve(state, chosen=chosen, ledger=ledger)
        assert receipt["ok"], receipt
    assert not director.active(state)
    return answered


def _walk_out_and_back(state) -> list:
    """Leave the Lantern House for a turn (the desk's `when:` falls, so it
    re-arms), come back, and return what is dealt."""
    from engine.content import director

    state.location_id = "wickmarket"
    director.ensure_scene(state)
    state.location_id = "lantern_house"
    return _desk_hand(state)


def _linked(state) -> bool:
    from engine.game.quests import evaluate_condition

    return evaluate_condition(state, {"linked": {"a": "self", "b": "magpie"}})


def _gm(state) -> str:
    import re

    from engine.agents import prompts

    found = re.search(r"GM ONLY.*", prompts.world_state_block(state, {}), re.S)
    return found.group(0) if found else ""


def test_the_front_desk_ships_bounded_and_repeatable(hue) -> None:
    from engine.content import deck
    from engine.games.validation import validate_story

    found = _desk_deck()
    assert found.repeatable is True
    assert found.required == []
    assert {c.id for c in found.pool} == {ALIBI_CARD, STRUCK_CARD, "D3_the_badge",
                                          "D4_cleared_at_the_desk"} | {
        f"D2_name_{short}" for short in SUSPECTS.values()}
    assert found.draw >= 2  # the alibi and the one favoured suspect
    for card in found.cards:
        assert deck.MENU_TAG in card.tags, card.id
        assert any(_roll_free(b) for b in card.beats), card.id
        for beat in card.beats:
            assert "adjustments" not in beat, (card.id, beat)  # nothing clamped
    issues = [i for i in validate_story("hue-and-cry") if DESK in str(i.source)
              or DESK in str(i.ref_id)]
    assert issues == [], issues


def test_nothing_on_a_desk_card_was_cut_to_fit(hue) -> None:
    from pathlib import Path

    import yaml

    from engine.content import deck

    root = Path(__file__).resolve().parents[1]
    raw = yaml.safe_load((root / registry.get("hue-and-cry").paths["decks"]
                          / f"{DESK}.yaml").read_text(encoding="utf-8"))
    for card in raw["cards"]:
        assert len(card["text"].strip()) <= deck.MAX_TEXT, card["id"]
        for beat in card["beats"]:
            assert len(str(beat.get("text") or "").strip()) <= deck.MAX_TEXT, beat["id"]
            for branch in ("on_pass", "on_fail"):
                line = str(((beat.get("gate") or {}).get(branch) or {}).get("text") or "")
                assert len(line.strip()) <= deck.MAX_TEXT, (beat["id"], branch)


def test_the_alibi_is_one_set_of_effects_at_both_doors(hue) -> None:
    """The ruling: the front desk's alibi and the cell's share their effects,
    so one door cannot drift from the other."""
    def present(deck, card_id):
        card = next(c for c in deck.cards if c.id == card_id)
        beat = next(b for b in card.beats if b["id"] == "present_it")
        return beat["gate"]["on_pass"]["effects"]

    for desk_card, cell_card in ((ALIBI_CARD, "Q4_the_alibi"),
                                 (STRUCK_CARD, "Q4_the_alibi_struck")):
        desk = present(_desk_deck(), desk_card)
        cell = present(_interrogation_deck(), cell_card)
        assert desk == cell, desk_card
        assert [e["type"] for e in desk] == ["law_discharge", "flag", "ledger_fact"]
        assert desk[0] == {"type": "law_discharge", "alibi": True, "agenda": "the_magpie"}
        assert desk[1] == {"type": "flag", "flag": "alibi_proven"}
        # The alibi alone never breaks the Watch's belief (controller's ruling).
        assert all(e["type"] != "law_unlink" for e in desk)


@pytest.mark.parametrize("magpie", list(SUSPECTS))
def test_naming_the_magpie_rightly_breaks_the_watchs_belief(hue, magpie) -> None:
    """For each of the three: the clues lean to the real Magpie, the captain
    hears the name, and the spine happens -- `magpie_unmasked`, the link
    broken, the Magpie's robberies off your face -- and only THEN does the GM
    line say who it is."""
    from engine.game.clock import advance_time
    from engine.game.effects import apply_effect
    from engine.world import law, npc_sim

    state = _at_the_desk(_seed_for(magpie), carried=CLUES_OF[magpie][:EVIDENCE_BAR])
    # The Magpie's night's work, on your name while the watch links you.
    apply_effect(state, {"type": "report", "deed": "burglary", "guise": "magpie",
                         "jurisdiction": "rise", "precision": 0.6})
    assert law.wanted_score(state, "self", "rise") > 0
    before = _gm(state).lower()
    assert not any(w in before for w in _CANDIDATE_WORDS), before
    card = f"D2_name_{SUSPECTS[magpie]}"
    assert _desk_hand(state) == [card]
    assert _answer_hand(state, {card: "name_them"}) == [card]
    assert state.flags.get("magpie_unmasked") is True
    assert not state.flags.get("magpie_named_wrongly")
    assert not _linked(state)
    assert law.wanted_score(state, "self", "rise") == 0
    assert law.wanted_score(state, "magpie", "rise") > 0  # still the Magpie's
    assert npc_sim.display_name(magpie) in _gm(state)
    # Unmasked, the accusation is never dealt again.
    advance_time(state, 1)
    assert _walk_out_and_back(state) == []


def test_a_wrong_naming_costs_and_a_second_try_waits_for_a_new_clue(hue) -> None:
    """The owner's decision: a wrong naming files a false witness on your own
    face and leaves the Watch's belief whole; the same suspect is never
    offered again, and nobody else is until a clue has been carried out since
    -- with the wrongly named set aside, a new clue can let the real Magpie
    lead, and the second try, named rightly, unmasks and unlinks."""
    from engine.world import law

    # Wren three, Silas one: the clues favour Wren, and Silas leads the rest.
    state = _at_the_desk(_seed_for("npc_silas"),
                         carried=CLUES_OF["npc_wren"][:3] + CLUES_OF["npc_silas"][:1])
    assert _desk_hand(state) == ["D2_name_wren"]
    _answer_hand(state, {"D2_name_wren": "name_them"})
    assert state.flags.get("magpie_named_wrongly") is True
    assert state.flags.get("wrongly_accused_wren") is True
    assert not state.flags.get("magpie_unmasked") and _linked(state)
    assert not state.flags.get("clue_fresh")
    [row] = [r for r in state.law["reports"] if r["deed"] == "false_witness"]
    assert (row["guise"], row["jurisdiction"], row["precision"]) == ("self", "wick", 1.0)
    assert law.wanted_band(state, "self", "wick") == "noticed"  # felt, never a stop
    assert not any(w in _gm(state).lower() for w in _CANDIDATE_WORDS)
    # No instant retry: Silas already leads the rest, but nothing is new.
    assert _walk_out_and_back(state) == []
    # A clue carried out since -- another of Wren's, as it happens: Wren still
    # leads the whole tally and is never offered again; Silas, leading the
    # rest, is.
    _carry(state, CLUES_OF["npc_wren"][3])
    assert _walk_out_and_back(state) == ["D2_name_silas"]
    _answer_hand(state, {"D2_name_silas": "name_them"})
    assert state.flags.get("magpie_unmasked") is True and not _linked(state)
    assert state.flags.get("magpie_named_wrongly") is True  # v0.17 reads both


def test_two_clues_that_agree_are_what_the_captain_asks(hue) -> None:
    """T8's measured bar: evidence 2 with the lead -- which, since a tie
    favours nobody, is exactly two clues pointing at the same suspect. One
    clue is not enough, and two that disagree lead nowhere; a third that
    points elsewhere leaves the two still leading (the weakest lead at 3 is
    no stronger than at 2 -- why the bar is 2)."""
    wren, silas = CLUES_OF["npc_wren"], CLUES_OF["npc_silas"]
    seed = _seed_for("npc_silas")
    assert _desk_hand(_at_the_desk(seed, carried=wren[:1])) == []
    assert _desk_hand(_at_the_desk(seed, carried=(wren[0], silas[0]))) == []
    assert _desk_hand(_at_the_desk(seed, carried=wren[:2])) == ["D2_name_wren"]
    assert _desk_hand(_at_the_desk(seed, carried=(*wren[:2], silas[0]))) == ["D2_name_wren"]


def test_a_wrong_naming_stacks_on_the_magpies_file_while_you_are_linked(hue) -> None:
    """T7 review, measured in T8: "never `sought` alone" is true only of a
    clean face. Every accuser is still linked to the Magpie (a right naming is
    what breaks the link), so the false witness lands on top of whatever the
    Magpie has done in the Wick in your name. Two of the Magpie's robberies
    there (agendas.yaml's burglary at 0.6: 3.6, `noticed`) and a wrong naming
    (3 at 1.0) is 6.6: `sought`, the band a Lantern knows you in on the way
    out (law.yaml `recognise`). scripts/simulate_acts.py measures the band
    a real wrong-namer lands in; this pins the arithmetic it reads."""
    from engine.game.effects import apply_effect
    from engine.world import law

    state = _at_the_desk(_seed_for("npc_silas"), carried=CLUES_OF["npc_wren"][:3])
    for _ in range(2):
        assert apply_effect(state, {"type": "report", "deed": "burglary", "guise": "magpie",
                                    "jurisdiction": "wick", "precision": 0.6})["ok"]
    assert _linked(state)
    assert law.wanted_band(state, "self", "wick") == "noticed"
    assert _desk_hand(state) == ["D2_name_wren"]
    _answer_hand(state, {"D2_name_wren": "name_them"})
    assert state.flags.get("magpie_named_wrongly") is True
    assert law.wanted_band(state, "self", "wick") == "sought"
    assert "sought" in law.load_spec()["recognise"]  # a patrol can know you now
    # The false witness is on your own file and the Magpie's file is
    # unchanged: it is the link that adds the two together, both ways.
    assert law.filed_score(state, "self", "wick") == pytest.approx(3.0)
    assert law.filed_score(state, "magpie", "wick") == pytest.approx(3.6)
    assert law.wanted_band(state, "magpie", "wick") == "sought"


@pytest.mark.parametrize("case", ["low_evidence", "no_lead", "captain_out",
                                  "captain_asleep", "in_custody", "elsewhere", "unmasked"])
def test_the_accusation_is_refused_without_its_gate(hue, case) -> None:
    from engine.content import deck
    from engine.game.effects import apply_effect

    wren = CLUES_OF["npc_wren"]
    carried = {"low_evidence": wren[:EVIDENCE_BAR - 1],
               "no_lead": (wren[0], CLUES_OF["npc_silas"][0], CLUES_OF["npc_imelda"][0])
               }.get(case, wren[:3])
    hour = {"captain_out": 14, "captain_asleep": 23}.get(case, 9)
    state = _at_the_desk(_seed_for("npc_wren"), hour=hour, carried=carried)
    if case == "in_custody":
        assert apply_effect(state, {"type": "arrest"})["ok"]
    if case == "elsewhere":
        state.location_id = "wickmarket"
    if case == "unmasked":
        apply_effect(state, {"type": "flag", "flag": "magpie_unmasked"})
    if case not in ("in_custody", "elsewhere"):  # those two are the deck's own gate
        eligible, _ = deck.eligible_cards(state, _desk_deck())
        assert not [c.id for c in eligible if c.id.startswith("D2_")], case
    assert _desk_hand(state) == [], case


def _alibi_earned(seed: int = 9):
    """Arrested in the Wick at 20:00, held through the Magpie's small hours
    (the robbery at 01:00 is joined to its report), and released by paying:
    free, standing in the Lantern House, one alibi earned."""
    from engine.game.clock import advance_time
    from engine.world import agendas, law

    state = _arrested(seed=seed, hour=20)
    advance_time(state, 8)
    assert law.pay_fine(state)["ok"] and not law.in_custody(state)
    assert state.location_id == "lantern_house"
    [deed] = agendas.alibi_deeds(state, "the_magpie")
    return state, deed


def test_the_alibi_is_presented_at_the_front_desk_once(hue) -> None:
    """Released, standing at the desk: the duty book clears exactly the
    Magpie's robberies walked while you were held. It does not break the
    Watch's belief. Presented, it is not offered again; a robbery in a LATER
    stay earns (and offers) another."""
    from engine.game.clock import advance_time
    from engine.game.effects import apply_effect
    from engine.game.quests import evaluate_condition
    from engine.world import agendas, law

    state, deed = _alibi_earned()
    assert any(r["deed_id"] == deed for r in state.law["reports"])
    assert _desk_hand(state) == [ALIBI_CARD]
    _answer_hand(state, {ALIBI_CARD: "present_it"})
    assert deed in law.discharged(state)
    assert not any(r["deed_id"] == deed for r in state.law["reports"])
    assert state.flags.get("alibi_proven") is True
    assert _linked(state) and not state.flags.get("magpie_unmasked")  # ruling: NO
    assert evaluate_condition(state, {"alibi": {}})  # earned stays earned
    assert _walk_out_and_back(state) == []           # ...but presented once
    # A second stay, a second robbery, a second alibi.
    apply_effect(state, {"type": "report", "deed": "pickpocket", "guise": "self",
                         "jurisdiction": "wick", "precision": 1.0})
    assert apply_effect(state, {"type": "arrest"})["ok"]
    advance_time(state, 24)
    assert law.pay_fine(state)["ok"]
    assert len(agendas.alibi_deeds(state, "the_magpie")) == 2
    assert _desk_hand(state) == [ALIBI_CARD]


def test_an_alibi_kept_back_is_offered_again(hue) -> None:
    state, deed = _alibi_earned()
    assert _desk_hand(state) == [ALIBI_CARD]
    _answer_hand(state, {ALIBI_CARD: "let_it_lie"})
    assert not state.flags.get("alibi_proven")
    from engine.world import law

    assert deed not in law.discharged(state)
    assert _walk_out_and_back(state) == [ALIBI_CARD]


def _unmask(state) -> None:
    """What a right naming writes about the Watch's belief (the desk's
    `name_them` on_pass): the flag, and the link broken."""
    from engine.game.effects import apply_effect

    assert apply_effect(state, {"type": "flag", "flag": "magpie_unmasked"})["ok"]
    assert apply_effect(state, {"type": "law_unlink", "a": "self", "b": "magpie"})["ok"]


def _card_text(found_deck, card_id: str) -> str:
    return next(c for c in found_deck.cards if c.id == card_id).text


def test_the_duty_book_says_what_the_watch_believes(hue) -> None:
    """T7 review: the alibi's CONSTRAINT told the narrator "the file still
    says Magpie" -- false once a right naming struck the word off, and an
    alibi can still be open then (earned before the naming and kept back,
    or earned in a later stay). The book comes in two now, one per belief,
    at both doors, with the same discharge."""
    from engine.content import director
    from engine.game.effects import apply_effect
    from engine.world import law

    desk, cells = _desk_deck(), _interrogation_deck()
    for card_id, found in ((ALIBI_CARD, desk), ("Q4_the_alibi", cells)):
        assert "still says Magpie" in _card_text(found, card_id), card_id
    for card_id, found in ((STRUCK_CARD, desk), ("Q4_the_alibi_struck", cells)):
        text = _card_text(found, card_id)
        assert "still says" not in text and "no longer takes you for" in text, card_id

    # Linked: the plain card.
    state, deed = _alibi_earned()
    assert _desk_hand(state) == [ALIBI_CARD]
    _answer_hand(state, {ALIBI_CARD: "let_it_lie"})
    # Named rightly while the alibi is still open: the struck card, never the plain one.
    _unmask(state)
    assert not _linked(state)
    assert _walk_out_and_back(state) == [STRUCK_CARD]
    _answer_hand(state, {STRUCK_CARD: "present_it"})
    assert deed in law.discharged(state) and state.flags.get("alibi_proven") is True
    assert _walk_out_and_back(state) == []  # presented once, as before
    # The cells say the same: a later stay's alibi, after the naming.
    state2, _ = _alibi_earned()
    _unmask(state2)
    state2.location_id = "wickmarket"
    apply_effect(state2, {"type": "report", "deed": "pickpocket", "guise": "self",
                          "jurisdiction": "wick", "precision": 1.0})
    assert apply_effect(state2, {"type": "arrest"})["ok"]
    dealt = director.ensure_scene(state2)
    assert dealt[0]["result"]["deck_id"] == INTERROGATION
    ids = dealt[0]["result"]["card_ids"]
    assert "Q4_the_alibi_struck" in ids and "Q4_the_alibi" not in ids


def test_the_struck_duty_book_says_the_nights_leave_every_file(hue) -> None:
    """Final review: `law_discharge` drops a discharged deed's reports from
    EVERY file, the Magpie's included (effects.py), so the struck alibi's
    prose may not say those nights stay marked against the Magpie's name."""
    import json

    from engine.world import law

    state, deed = _alibi_earned()
    _unmask(state)
    assert _walk_out_and_back(state) == [STRUCK_CARD]
    _answer_hand(state, {STRUCK_CARD: "present_it"})
    assert deed in law.discharged(state)
    assert not any(r["deed_id"] == deed for r in state.law["reports"])  # magpie's too

    for card_id, found in ((STRUCK_CARD, _desk_deck()),
                           ("Q4_the_alibi_struck", _interrogation_deck())):
        card = next(c for c in found.cards if c.id == card_id)
        said = (card.text + json.dumps(card.beats)).lower()
        for claim in ("where they belong", "against the magpie's name", "file straight",
                      "file was put straight"):
            assert claim not in said, (card_id, claim)


def test_the_alibi_in_the_cells_on_a_later_arrest(hue) -> None:
    """Q4: an alibi not presented at the desk, then a second arrest -- the
    one asking has the duty book, and it clears the same robberies. The
    charge you came in on stands; the next stay's file remembers in red."""
    from engine.content import director
    from engine.game.effects import apply_effect
    from engine.world import law

    state, deed = _alibi_earned()
    state.location_id = "wickmarket"  # walked out without a word at the desk
    apply_effect(state, {"type": "report", "deed": "pickpocket", "guise": "self",
                         "jurisdiction": "wick", "precision": 1.0})
    assert apply_effect(state, {"type": "arrest"})["ok"]
    sentence = (law.custody(state)["fine"], law.custody(state)["days"])
    dealt = director.ensure_scene(state)
    assert dealt[0]["result"]["deck_id"] == INTERROGATION
    assert "Q4_the_alibi" in dealt[0]["result"]["card_ids"]
    answered = _answer_hand(state, {"Q4_the_alibi": "present_it"})
    assert answered[0] == "Q1_the_book" and "Q4_the_alibi" in answered
    assert deed in law.discharged(state) and state.flags.get("alibi_proven")
    assert (law.custody(state)["fine"], law.custody(state)["days"]) == sentence
    assert {"pay_fine", "serve"} <= _verbs(state)
    assert law.pay_fine(state)["ok"]
    assert _desk_hand(state) == []  # presented in the cell: the desk has nothing
    # The next stay's book remembers it in red.
    state.location_id = "wickmarket"
    director.ensure_scene(state)
    apply_effect(state, {"type": "report", "deed": "pickpocket", "guise": "self",
                         "jurisdiction": "wick", "precision": 1.0})
    assert apply_effect(state, {"type": "arrest"})["ok"]
    dealt = director.ensure_scene(state)
    assert "Q4_the_alibi" not in dealt[0]["result"]["card_ids"]  # presented once
    receipt = director.resolve(state)
    assert "In red" in _beat_text(receipt), receipt


def _desk_rows():
    rows = []
    for card in _desk_deck().cards:
        rows += [(card.id, str(b["id"])) for b in card.beats]
    return rows


#: Every answer on every desk card (held equal to the deck's own beats below:
#: parametrising needs the list before any story is active).
_DESK_ROWS = [(ALIBI_CARD, "present_it"), (ALIBI_CARD, "let_it_lie"),
              (STRUCK_CARD, "present_it"), (STRUCK_CARD, "let_it_lie")] + [
    (f"D2_name_{s}", b) for s in SUSPECTS.values() for b in ("name_them", "not_yet")] + [
    # A Lantern's door (v0.17 T5): taking the badge ENDS the story, so the
    # guard asserts the lock there, not the city's verbs.
    ("D3_the_badge", "take_the_badge"), ("D3_the_badge", "clear_my_name"),
    ("D3_the_badge", "not_yet"),
    # Cleared after the fair (fix round 1): hearing it said ends the story.
    ("D4_cleared_at_the_desk", "hear_it_said"), ("D4_cleared_at_the_desk", "not_yet")]


@pytest.mark.parametrize("card_id,beat_id", _DESK_ROWS)
def test_no_thief_is_ever_stuck_at_the_front_desk(hue, card_id, beat_id) -> None:
    """Every answer on every desk card, right and wrong: the hand ends and the
    city's verbs come back; nothing here arrests or moves the thief."""
    from engine.world import law

    if card_id in ("D3_the_badge", "D4_cleared_at_the_desk"):
        from engine.game import endings

        state = _badge_ready() if card_id == "D3_the_badge" else _after_the_fair_at_the_desk()
        assert _desk_hand(state) == [card_id]
        _answer_hand(state, {card_id: beat_id})
        if beat_id in ("take_the_badge", "hear_it_said", "clear_my_name"):
            assert endings.locked(state) == ("a_lantern" if beat_id == "take_the_badge"
                                             else "cleared")
        else:
            assert endings.locked(state) == endings.NONE_ID
            assert _verbs(state) - {"card"} and not law.in_custody(state)
        return
    if card_id == ALIBI_CARD:
        state, _deed = _alibi_earned()
    elif card_id == STRUCK_CARD:
        state, _deed = _alibi_earned()
        _unmask(state)
    else:
        suspect = next(n for n, s in SUSPECTS.items() if card_id.endswith(s))
        for magpie in SUSPECTS:  # named rightly, and named wrongly
            state = _at_the_desk(_seed_for(magpie), carried=CLUES_OF[suspect][:3])
            assert _desk_hand(state) == [card_id]
            _answer_hand(state, {card_id: beat_id})
            assert _verbs(state) - {"card"} and not law.in_custody(state)
            assert state.location_id == "lantern_house"
        return
    assert _desk_hand(state) == [card_id]
    _answer_hand(state, {card_id: beat_id})
    assert _verbs(state) - {"card"} and not law.in_custody(state)


def test_every_desk_answer_is_offered_by_the_parametrised_guard(hue) -> None:
    """The stuck-guard's rows are the deck's own beats, so a new beat is not
    left out of it."""
    assert sorted(_desk_rows()) == sorted(_DESK_ROWS)


def test_the_front_desk_replays(hue) -> None:
    """Same seed, same clues, same wrong name then right one: the same file."""
    def one():
        state = _at_the_desk(_seed_for("npc_silas"), carried=CLUES_OF["npc_wren"][:3])
        _desk_hand(state)
        _answer_hand(state, {"D2_name_wren": "name_them"})
        _carry(state, CLUES_OF["npc_silas"][0])
        _walk_out_and_back(state)
        _answer_hand(state, {"D2_name_silas": "name_them"})
        return state

    first, second = one(), one()
    assert first.flags.get("magpie_unmasked")
    assert (first.law, first.flags, first.rng_counters) == \
        (second.law, second.flags, second.rng_counters)


def test_an_old_save_meets_the_front_desk(hue) -> None:
    """A save from before Task 7 (clues found, no `clue_fresh`, no false
    witness) still reaches the first accusation; a save with the desk's hand
    open reloads to the same card; and a save from before v0.16 (no custody
    log, no joined hits) is offered no alibi."""
    from engine.content import director
    from engine.game.state import GameState

    state = _at_the_desk(_seed_for("npc_imelda"), carried=CLUES_OF["npc_imelda"][:3])
    old = state.to_save_dict()
    old["flags"].pop("clue_fresh", None)
    loaded = GameState.from_dict(old)
    assert _desk_hand(loaded) == ["D2_name_imelda"]
    reloaded = GameState.from_dict(loaded.to_save_dict())
    assert director.current_card(reloaded).id == "D2_name_imelda"
    _answer_hand(reloaded, {"D2_name_imelda": "name_them"})
    assert reloaded.flags.get("magpie_unmasked")

    earned, _deed = _alibi_earned()
    pre = earned.to_save_dict()
    pre["law"].pop("custody_log", None)
    for hit in pre["agendas"].get("hits") or []:
        hit.pop("deed_id", None)
    assert _desk_hand(GameState.from_dict(pre)) == []


def test_the_right_naming_is_remembered_through_the_card_verb(street) -> None:
    """Through run_turn and the `card` intent: the reveal's ledger facts land
    in the session's ledger (the skill passes it now), and the next prompt's
    GM line names the Magpie."""
    from engine.content import director
    from engine.game.clock import set_clock
    from engine.world import agendas, npc_sim

    state = street.engine.state
    magpie = agendas.role(state, "magpie")
    state.location_id = "lantern_house"
    set_clock(state, day=2, hour=9)
    _carry(state, *CLUES_OF[magpie][:3])
    assert _desk_hand(state) == [f"D2_name_{SUSPECTS[magpie]}"]
    assert "WHO THE MAGPIE IS" not in _gm(state)
    _card_turn(street, "name_them")
    assert not director.active(state) and state.flags.get("magpie_unmasked")
    facts = [f.text for f in street.ledger.recall(magpie, limit=8)]
    assert any("is the Magpie" in f for f in facts), facts
    assert npc_sim.display_name(magpie) in _gm(state)


# ---------------------------------------------------------------------------
# Acts I-II, measured (v0.16 Task 8): scripts/simulate_acts.py
# ---------------------------------------------------------------------------

#: MEASURED, v0.16 T8, scripts/simulate_acts.py over 40 seeds x 12 days, every
#: opening (the table is in CHANGELOG.md [0.16.0]): an investigator who
#: cases the city for clue houses, burgles them and takes what it finds to
#: Captain Ardane's desk carries out 2.5 clues by day 12 and unmasks the
#: Magpie by day 12 on 60% of runs (mean day 9), naming wrongly first on 12%.
#: Asserted here over the FIRST 10 SEEDS of "come quietly" -- every thief
#: arrested, interrogated and released through the Lantern House -- where the
#: harness reads 2.7 clues by day 12, 7 of 10 unmasked by day 12, 1 wrong
#: first naming, and every run sworn to the Company on day 1.
ACTS_SEEDS = 10
ACTS_OPENING = "c"


@pytest.fixture(scope="module")
def measured_acts():
    _scripts_on_path()
    from scripts import simulate_acts

    # Module-scoped, as measured_law: activated here and undone here. The
    # agendas stay ON -- the spine needs the Magpie (and `agenda_role` reads
    # nothing without them).
    before = registry.peek()
    registry.activate("hue-and-cry")
    try:
        return [simulate_acts.play(seed, ACTS_OPENING) for seed in range(ACTS_SEEDS)]
    finally:
        if registry.peek() is not before:
            registry.deactivate()


def test_every_investigator_is_sworn_to_the_company_on_day_one(measured_acts) -> None:
    """Off the barge by the Lantern House, fine paid, to the Snuffs by
    evening: the initiation is dealt, and answered, on the first night."""
    assert [r.initiated_day for r in measured_acts] == [1] * ACTS_SEEDS


def test_the_trail_reads_slowly_but_it_reads(measured_acts) -> None:
    """A clue costs about three houses cased to the end; by day 12 every run
    has carried out at least two, and the mean is well above that."""
    by_twelve = [sum(d <= 12 for d in r.clue_days) for r in measured_acts]
    assert min(by_twelve) >= 2, by_twelve
    assert sum(by_twelve) / ACTS_SEEDS >= 2.3, by_twelve
    # And not so fast that the reveal is free: nobody has two by day 3.
    assert all(sum(d <= 3 for d in r.clue_days) < 2 for r in measured_acts)


def test_the_reveal_is_an_achievement_within_the_spine(measured_acts) -> None:
    """Reachable for a deliberate investigator within the spine's ~10-12
    days, and not for everyone: most unmask the Magpie by day 12, some do
    not, and a first naming is right far more often than wrong."""
    unmasked = [r.unmasked_day for r in measured_acts]
    by_twelve = sum(d is not None and d <= 12 for d in unmasked)
    assert 0.5 <= by_twelve / ACTS_SEEDS < 1.0, unmasked
    first = [r.namings[0]["right"] for r in measured_acts if r.namings]
    assert sum(first) > 2 * (len(first) - sum(first)), first
    assert min(d for d in unmasked if d is not None) >= 4, unmasked


def test_a_wrong_naming_always_costs_the_accuser_something(measured_acts, hue) -> None:
    """Every real wrong naming strictly raises the accuser's own wanted score
    in the Wick -- an accuser already `hunted` pays too, not only one a band
    below it -- and leaves that face at least `noticed`."""
    from engine.world import law

    bands = list(law.load_spec()["wanted"]["bands"])
    wrong = [n for r in measured_acts for n in r.namings if not n["right"]]
    assert wrong, "no wrong naming in the measured seeds"
    for n in wrong:
        assert n["score_after"] > n["score_before"], n
        assert bands.index(n["band_after"]) >= max(1, bands.index(n["band_before"])), n


def test_no_investigator_starves_or_is_stuck(measured_acts) -> None:
    # Since v0.17 hp 0 respawns inside the hour that reached it, so the
    # sampled min_hp alone would miss a death: count them (counting_deaths).
    assert min(r.min_hp for r in measured_acts) > 0
    assert sum(r.deaths for r in measured_acts) == 0


def test_the_acts_harness_replays_from_its_seed(hue) -> None:
    """Rule 4 and the harness's own promise: a seed replays byte for byte."""
    _scripts_on_path()
    from scripts import simulate_acts

    assert simulate_acts.play(3, "a", 5) == simulate_acts.play(3, "a", 5)


# ---------------------------------------------------------------------------
# v0.17 Task 3: the Hanging Fair -- the event, the fair deck, the gallows,
# the Everflame's heart and Act III
# ---------------------------------------------------------------------------

FAIR = "fair_day"
GALLOWS = "the_gallows"
GALLOWS_CARD = "G1_the_last_morning"
#: data/world/schedules.yaml: the fair's first day and its length. The
#: gallows deck's `min_day` is the last of them (asserted).
FAIR_FIRST_DAY, FAIR_DAYS = 10, 3
FAIR_LAST_DAY = FAIR_FIRST_DAY + FAIR_DAYS - 1
#: The hour the Watch walks its saved-up thieves down to the Green.
GALLOWS_HOUR = 9
#: Ids the fair deck's header reserved for v0.17 Tasks 5-6. F3 (Cleared, T5),
#: F4 (The Dapper's City) and F6 (Partners) are built; F5 was released unbuilt
#: (T6: Guildmaster's door is the Porters' Hall) and may be taken by no card.
FAIR_RESERVED = ("F5_gannets_stake",)
#: The one fair card that may name a candidate: Silas Crook's move for the
#: Company (F4), which is about the Company and says nothing of the Magpie.
FAIR_NAMES_SILAS = "F4_silas_makes_his_move"


def _fed_until(state, day: int, hour: int = 0) -> None:
    """Walk the clock to ``day``/``hour`` through `advance_time` -- the path
    the calendar takes, so the fair is raised by its own schedule -- fed
    before every step, so no test here dies of anything but the gallows."""
    from engine.game.clock import advance_time
    from engine.game.effects import apply_effect

    target = float((day - 1) * 24 + hour)
    while state.world_clock_hours < target:
        if state.hunger > 0:
            apply_effect(state, {"type": "hunger", "delta": -state.hunger})
        advance_time(state, min(6.0, target - state.world_clock_hours))
    assert (state.world_day, state.world_hour) == (day, hour)


def _fair_on(state, *, hour: int = 10) -> None:
    _fed_until(state, FAIR_FIRST_DAY, hour)


def _arrest_on(state, deed: str = "pickpocket", *, where: str = "wickmarket",
               precision: float = 1.0) -> None:
    """A lift (or worse) filed against your own face where you stand, then the arrest."""
    from engine.game.effects import apply_effect
    from engine.world import law

    state.location_id = where
    jurisdiction = law.jurisdiction_at(where)
    apply_effect(state, {"type": "report", "deed": deed, "guise": "self",
                         "jurisdiction": jurisdiction, "precision": precision})
    assert apply_effect(state, {"type": "arrest"})["ok"]
    assert law.in_custody(state)


def _questioned(state) -> None:
    """The stay's first turn: the interrogation, dealt and answered roll-free."""
    from engine.content import director

    dealt = director.ensure_scene(state)
    assert dealt and dealt[0]["result"]["deck_id"] == INTERROGATION, dealt
    guard = 0
    while director.active(state) and guard < 16:
        guard += 1
        card = director.current_card(state)
        beats = {str(b["id"]): b for b in card.beats}
        options = [o["id"] for o in director.options(state)]
        roll_free = [o for o in options if o in beats and _roll_free(beats[o])]
        director.resolve(state, chosen=(roll_free or options)[0])
    assert not director.active(state)


def _held_for_the_fair(seed: int = 11, *, deed: str = "pickpocket", day: int = 9,
                       hour: int = 12):
    """A thief arrested before the fair and questioned, still held."""
    state = _city(seed)
    _fed_until(state, day, hour)
    _arrest_on(state, deed)
    _questioned(state)
    return state


def _fair_deck():
    from engine.content import deck

    found = deck.load_deck(FAIR)
    assert found is not None, "no fair deck"
    return found


def _gallows_deck():
    from engine.content import deck

    found = deck.load_deck(GALLOWS)
    assert found is not None, "no gallows deck"
    return found


def _play_the_fair(state, showing: str = "watch_it_shine") -> None:
    """Every card of the dealt fair hand: ``showing`` on the Showing, the first
    option elsewhere."""
    from engine.content import director

    guard = 0
    while director.active(state) and guard < 8:
        guard += 1
        card = director.current_card(state)
        chosen = showing if card.id == "F2_the_showing" else director.options(state)[0]["id"]
        assert director.resolve(state, chosen=chosen).get("ok"), (card.id, chosen)
    assert not director.active(state)


def test_hue_and_cry_declares_the_hanging_fair(hue) -> None:
    """A declared world event (paths.world_schedules): on its day, three days
    long, on Gallows Green, forcing the fair deck -- and nothing else in the
    file, so no caravan, tinker or militia of the flagship's is staged here."""
    from engine.games.validation import validate_story
    from engine.world import schedules

    doc = schedules.load_schedules()
    assert set(doc) == {"events"}, sorted(doc)
    spec = doc["events"]["hanging_fair"]
    assert spec["on_day"] == FAIR_FIRST_DAY and spec["duration_days"] == FAIR_DAYS
    assert spec["location_id"] == "gallows_green" and spec["forces_scene"] == FAIR
    assert "when" not in spec  # a fixed day: the city's calendar, not the player's
    assert str(spec["text"]).strip()
    issues = [i for i in validate_story("hue-and-cry")
              if "schedules" in str(i.source) or FAIR in str(i.source)
              or GALLOWS in str(i.source)]
    assert issues == [], issues


def test_the_fair_comes_on_its_day_and_lasts_three(hue) -> None:
    """Raised by `advance_time`'s day roll, never by the wall clock: not on
    the day before, active for exactly its three days, gone on the fourth,
    and remembered (`event_seen`) after it is gone."""
    from engine.game.quests import QuestEngine, evaluate_condition

    state = _city(11)
    _fed_until(state, FAIR_FIRST_DAY - 1, 23)
    assert not evaluate_condition(state, {"event_active": "hanging_fair"})
    for day in range(FAIR_FIRST_DAY, FAIR_LAST_DAY + 1):
        _fed_until(state, day, 1)
        assert evaluate_condition(state, {"event_active": "hanging_fair"}), day
        QuestEngine.evaluate(state)
    _fed_until(state, FAIR_LAST_DAY + 1, 1)
    assert not evaluate_condition(state, {"event_active": "hanging_fair"})
    assert evaluate_condition(state, {"event_seen": "hanging_fair"})


def test_the_fair_deck_deals_only_on_the_green_during_the_fair(hue) -> None:
    """Forced by the event, and waiting on its own `when:` (T1's seam): not on
    the Green the day before, not elsewhere during the fair, on the Green
    during it -- the spine and the Showing -- and not after it."""
    from engine.content import director

    found = _fair_deck()
    assert found.when == {"all": [{"event_active": "hanging_fair"},
                                  {"at_location": "gallows_green"},
                                  {"in_custody": False}]}
    assert found.repeatable is True  # review round 1: a return re-deals

    early = _city(11)
    _fed_until(early, FAIR_FIRST_DAY - 1, 10)
    early.location_id = "gallows_green"
    assert director.due(early)[0] != FAIR

    state = _city(11)
    _fair_on(state)
    state.location_id = "wickmarket"
    assert director.due(state)[0] != FAIR
    assert director.ensure_scene(state) == []
    state.location_id = "gallows_green"
    assert director.due(state) == (FAIR, "", "forced")
    dealt = director.ensure_scene(state)
    assert dealt and dealt[0]["result"]["deck_id"] == FAIR, dealt
    assert dealt[0]["result"]["card_ids"] == ["F1_the_green", "F2_the_showing"]

    late = _city(11)
    _fed_until(late, FAIR_LAST_DAY + 1, 10)
    late.location_id = "gallows_green"
    assert director.due(late)[0] != FAIR


def test_the_fair_deck_is_dealt_once_a_visit(hue) -> None:
    """Repeatable, but one deal per rising edge: a thief who stays on the
    Green is not dealt the fair again (a return is, below)."""
    from engine.content import director

    state = _city(11)
    _fair_on(state)
    state.location_id = "gallows_green"
    director.ensure_scene(state)
    _play_the_fair(state)
    _fed_until(state, FAIR_FIRST_DAY + 1, 10)
    assert director.due(state)[0] != FAIR
    assert director.ensure_scene(state) == []


def test_an_arrest_on_fair_day_is_questioned_and_not_hanged(hue) -> None:
    """T1's seam, on the real fair: an arrest while the fair is on deals the
    interrogation (the forced fair waits -- the thief is not on the Green).
    Taken DURING the fair, the thief is not one the Watch saved up for it:
    no gallows on the last morning, and the fine still buys the way out."""
    from engine.content import director
    from engine.game import intents
    from engine.world import law

    state = _city(11)
    _fed_until(state, FAIR_LAST_DAY, GALLOWS_HOUR + 1)
    state.stats.gold = 50
    _arrest_on(state)
    assert director.due(state) == (INTERROGATION, "", "scheduled")
    _questioned(state)
    assert director.ensure_scene(state) == []
    assert not director.active(state)
    assert "pay_fine" in {v.action for v in intents.legal_intents(state)}
    assert law.pay_fine(state)["ok"] and not law.in_custody(state)


def test_held_before_event_reads_the_stay_against_the_events_start(hue) -> None:
    """`held_before_event: <id>` -- held now, in a stay that began no later
    than the live event did. False when free, when the event is not on, and
    for a stay begun after it started."""
    from engine.game.quests import evaluate_condition

    probe = {"held_before_event": "hanging_fair"}
    before = _city(11)
    _fed_until(before, FAIR_FIRST_DAY - 1, 22)
    assert not evaluate_condition(before, probe)  # free
    _arrest_on(before)
    assert not evaluate_condition(before, probe)  # no fair yet
    _fed_until(before, FAIR_FIRST_DAY, 2)
    assert evaluate_condition(before, probe)

    during = _city(11)
    _fed_until(during, FAIR_FIRST_DAY, 0)
    _arrest_on(during)
    assert not evaluate_condition(during, probe)


def test_a_thief_held_when_the_fair_comes_is_hanged_on_its_last_morning(hue) -> None:
    """The Rope's second door: no death, no hp -- the Watch walks the thieves
    it saved up down to the Green at nine on the last morning. Dealt in the
    cell, not before the hour (T4's jailbreak has the fair until then), and
    the answer locks The Rope by name and plays its module."""
    from engine.content import director
    from engine.game import endings, epilogue

    state = _held_for_the_fair()
    _fed_until(state, FAIR_LAST_DAY, GALLOWS_HOUR - 1)
    assert director.ensure_scene(state) == []
    _fed_until(state, FAIR_LAST_DAY, GALLOWS_HOUR)
    assert director.due(state) == (GALLOWS, "", "scheduled")
    dealt = director.ensure_scene(state)
    assert dealt[0]["result"]["card_ids"] == [GALLOWS_CARD], dealt
    assert endings.locked(state) == endings.NONE_ID
    out = director.resolve(state, chosen=director.options(state)[0]["id"])
    assert out.get("ok"), out
    assert endings.locked(state) == "the_rope"
    card = epilogue.for_state(state)
    assert card is not None and card.title == "The Rope"


@pytest.mark.parametrize("beat", ["head_up", "argue_the_case", "look_for_the_jackdaw"])
def test_every_way_down_the_hill_is_the_rope(hue, beat) -> None:
    from engine.content import director
    from engine.game import endings, epilogue

    state = _held_for_the_fair()
    _fed_until(state, FAIR_LAST_DAY, GALLOWS_HOUR)
    director.ensure_scene(state)
    assert beat in {o["id"] for o in director.options(state)}
    assert director.resolve(state, chosen=beat).get("ok")
    assert endings.locked(state) == "the_rope" and endings.module_ran(state)
    assert epilogue.for_state(state).ending_id == "the_rope"


def test_a_sentence_served_into_the_last_morning_stops_for_the_gallows(hue) -> None:
    """Serving is waiting, and the Watch does not let a saved-up thief wait
    out the fair: a sentence that would run past nine on the last morning
    stops when the gallows falls due (`serve_sentence`'s interruption), and
    the hand is dealt on that turn. A sentence that ends before the hour is
    served out as always."""
    from engine.content import director
    from engine.world import law

    state = _held_for_the_fair(deed="resisting_watch", day=9, hour=12)
    assert law.custody(state)["days"] == 3
    served = law.serve_sentence(state)
    assert served["ok"] and served["served_out"] is False, served
    assert served["interrupted_by"] == GALLOWS
    assert law.in_custody(state) and state.world_day == FAIR_LAST_DAY
    assert state.world_hour >= GALLOWS_HOUR
    assert director.ensure_scene(state)[0]["result"]["deck_id"] == GALLOWS

    early = _held_for_the_fair(deed="resisting_watch", day=9, hour=6)
    done = law.serve_sentence(early)
    assert done["served_out"] is True and "interrupted_by" not in done, done
    assert not law.in_custody(early)


def test_a_sentence_begun_at_the_fair_is_served_through_it(hue) -> None:
    from engine.world import law

    state = _city(11)
    _fed_until(state, FAIR_FIRST_DAY + 1, 12)
    _arrest_on(state, "resisting_watch")
    _questioned(state)
    done = law.serve_sentence(state)
    assert done["served_out"] is True, done
    assert not law.in_custody(state)


def test_an_interrupted_sentence_is_narrated_as_one(hue) -> None:
    from engine.agents import prompts

    line = prompts._sum_serve({"ok": True, "days": 3, "gaol": "the Lantern House",
                               "served_out": False, "interrupted_by": GALLOWS})
    assert "carried out" not in line
    assert "the Lantern House" in line


def test_the_gallows_waits_for_its_hour_and_names_the_rope(hue) -> None:
    """The gallows deck: one required card, dealt only to a thief held since
    before the fair, from nine on its last day; every answer roll-free, each
    locking `the_rope` BY NAME then playing its module."""
    import json

    from engine.world import schedules

    found = _gallows_deck()
    spec = schedules.load_schedules()["events"]["hanging_fair"]
    assert found.when == {"all": [{"held_before_event": "hanging_fair"},
                                  {"event_active": "hanging_fair"},
                                  {"min_day": spec["on_day"] + spec["duration_days"] - 1},
                                  {"hour_between": [GALLOWS_HOUR, 24]}]}
    assert [c.id for c in found.required] == [GALLOWS_CARD] and not found.pool
    [card] = found.cards
    assert "menu" in card.tags
    for beat in card.beats:
        gate = beat.get("gate") or {}
        # No dice anywhere; a `when:` (argue_the_case reads the Law's links)
        # only chooses the words, and every branch it can take locks.
        assert not gate.get("check") and "band" not in beat, beat["id"]
        branches = ["on_pass"] + (["on_fail"] if "when" in gate else [])
        for branch in branches:
            effects = (gate.get(branch) or {}).get("effects") or []
            assert effects[:2] == [{"type": "ending_lock", "ending": "the_rope"},
                                   {"type": "ending_module"}], (beat["id"], branch)
    text = json.dumps([card.title, card.text, card.beats]).lower()
    assert not any(word in text for word in _CANDIDATE_WORDS)


def test_the_fair_deck_is_always_answerable(hue, monkeypatch) -> None:
    """Every card has a way through with no dice; every answer, every roll
    passed and failed, ends the hand (no card opens another scene)."""
    from engine.content import director

    for card in _fair_deck().cards:
        if "menu" in card.tags:
            assert any(_roll_free(b) for b in card.beats), card.id
        else:
            for beat in card.beats:
                assert not (beat.get("gate") or {}).get("check"), (card.id, beat["id"])
    showing = next(c for c in _fair_deck().cards if c.id == "F2_the_showing")
    for degree in ("success", "failure"):
        _force(monkeypatch, degree)
        for beat in showing.beats:
            state = _city(11)
            _fair_on(state)
            state.location_id = "gallows_green"
            director.ensure_scene(state)
            _play_the_fair(state, str(beat["id"]))


def test_the_fair_deck_reserves_the_ending_doors_and_keeps_the_mask(hue) -> None:
    """The released door id is named in the header and no card takes it (T5's
    F3 and T6's F4 and F6 are built, and the header says so); no `when:` in
    the deck reads the Magpie's role; no card names a candidate -- save that
    F4, Silas Crook's move for the Company, names Silas and no other."""
    import json
    from pathlib import Path

    import yaml

    from engine.games.validation import walk

    path = (Path(__file__).resolve().parents[1] / "games" / "hue-and-cry" / "data"
            / "scenes" / f"{FAIR}.yaml")
    raw_text = path.read_text(encoding="utf-8")
    header = "\n".join(line for line in raw_text.splitlines() if line.startswith("#"))
    for reserved in FAIR_RESERVED:
        assert reserved in header, reserved
    found = _fair_deck()
    assert not {c.id for c in found.cards} & set(FAIR_RESERVED)
    doc = yaml.safe_load(raw_text)
    assert "agenda_role" not in json.dumps(doc.get("when") or {})
    for node in walk(doc):
        assert "agenda_role" not in json.dumps(node.get("when") or {}), node
    silas = ("silas", "crook", "dapper")
    for card in found.cards:
        text = json.dumps([card.title, card.text, card.beats]).lower()
        words = [w for w in _CANDIDATE_WORDS
                 if not (card.id == FAIR_NAMES_SILAS and w in silas)]
        assert not any(word in text for word in words), card.id


def test_the_everflames_heart_is_a_relic_nobody_will_buy(hue) -> None:
    """Named, shiny, and a `relic`: no counter in Tallowmere deals in it, fence
    or honest. Not one of the Magpie's Hoard, and in no house -- it is on the
    palace steps at the fair and nowhere a burglar can reach between fairs."""
    from pathlib import Path

    from engine.game import inventory, trade
    from engine.game.effects import apply_effect

    tags = set(inventory.tags_of("everflame_heart"))
    assert {"named", "shiny", "relic"} <= tags
    assert inventory.value_of("everflame_heart") > 0
    assert not inventory.collection_of("everflame_heart")
    assert "relic" in trade._cfg().get("never_traded_tags", [])
    premises = Path(__file__).resolve().parents[1] / "games" / "hue-and-cry" / "data" / "premises"
    for path in premises.rglob("*.yaml"):
        assert "everflame_heart:" not in path.read_text(encoding="utf-8"), path.name
        assert "- everflame_heart" not in path.read_text(encoding="utf-8"), path.name

    state = _city(11)
    apply_effect(state, {"type": "item", "item_id": "everflame_heart",
                         "name": "The Everflame's Heart"})
    for npc in ("npc_pell_hollis", "npc_marrow", "npc_dock_mag"):
        assert not trade.deals_in(npc, "everflame_heart"), npc
        assert not trade.sell(state, npc, "everflame_heart")["success"], npc
    assert inventory.quantity(state, "everflame_heart") == 1


@pytest.mark.parametrize("degree", ["success", "failure"])
def test_the_heart_is_lifted_off_the_palace_steps_on_a_roll(hue, monkeypatch, degree) -> None:
    """The Showing's heist: a severe stealth roll. Won, the heart is yours --
    stolen from the household, so hot for good and taken back at any arrest --
    and the Watch files it as the Magpie's. Lost, a Lantern saw the hand."""
    from engine.content import director
    from engine.game import inventory
    from engine.world import thievery

    _force(monkeypatch, degree)
    state = _city(11)
    _fair_on(state)
    state.location_id = "gallows_green"
    director.ensure_scene(state)
    before = len(state.law.get("reports") or [])
    _play_the_fair(state, "lift_the_heart")
    new = (state.law.get("reports") or [])[before:]
    if degree == "success":
        assert inventory.quantity(state, "everflame_heart") == 1
        assert thievery.heat_split(state, "everflame_heart")["hot"] == 1
        assert [(r["deed"], r["guise"]) for r in new] == [("sacrilege", "magpie")]
    else:
        assert inventory.quantity(state, "everflame_heart") == 0
        assert [(r["deed"], r["guise"]) for r in new] == [("sacrilege", "self")]


def test_the_fair_replays_from_its_seed(hue) -> None:
    """Rule 4: the same seed walked to the same fair with the same answers is
    the same world -- the heist's roll included."""
    from engine.content import director

    def one():
        state = _city(5)
        _fair_on(state)
        state.location_id = "gallows_green"
        director.ensure_scene(state)
        _play_the_fair(state, "lift_the_heart")
        return state

    first, second = one(), one()
    assert first.rng_counters
    assert (first.law, first.flags, [(i.id, i.qty) for i in first.inventory],
            first.rng_counters, first.world_events) == \
           (second.law, second.flags, [(i.id, i.qty) for i in second.inventory],
            second.rng_counters, second.world_events)


def test_act_three_opens_with_the_fair(hue) -> None:
    """`the_hanging_fair`, order 3 and narrated, opens on `event_seen:
    hanging_fair` -- so it stays the act after the fair is gone -- and its
    ACT line names the fair."""
    from engine.agents import prompts
    from engine.game.quests import QuestEngine, load_arcs

    arc = load_arcs()["the_hanging_fair"]
    assert arc["narrate"] is True and arc["order"] == 3
    assert arc["requires_any"] == [{"event_seen": "hanging_fair"}]

    state = _city(11)
    state.flags["guild_initiated"] = True
    _fed_until(state, FAIR_FIRST_DAY - 1, 12)
    QuestEngine.evaluate(state)
    assert state.active_arc == "honest_work"
    _fair_on(state)
    QuestEngine.evaluate(state)
    assert state.active_arc == "the_hanging_fair"
    act = prompts.act_block(state)
    assert act.startswith("ACT: The Hanging Fair. ") and len(act.splitlines()) == 1
    assert act in prompts.world_state_block(state, {})
    _fed_until(state, FAIR_LAST_DAY + 2, 10)
    QuestEngine.evaluate(state)
    assert state.active_arc == "the_hanging_fair"


def test_act_three_stays_true_after_the_unmasking(hue) -> None:
    """Audit question 3, as v0.16 fixed Act II: the Act III line must not
    tell the narrator the Watch takes you for the Magpie once a right naming
    broke that, and it never names or sexes the Magpie."""
    import re

    from engine.agents import prompts
    from engine.game.effects import apply_effect
    from engine.game.quests import QuestEngine

    state = _city(11)
    _fair_on(state)
    QuestEngine.evaluate(state)
    apply_effect(state, {"type": "flag", "flag": "magpie_unmasked"})
    assert apply_effect(state, {"type": "law_unlink", "a": "self", "b": "magpie"})["ok"]
    act = prompts.act_block(state).lower()
    assert act.startswith("act: the hanging fair. ")
    for phrase in ("on your name", "lands on you", "takes you for the magpie",
                   "you are the magpie", "as the magpie"):
        assert phrase not in act, phrase
    assert not any(word in act for word in _CANDIDATE_WORDS)
    assert not re.search(r"\b(she|he|her|his|him|hers)\b", act), act


# -- T3 fix round 1 ------------------------------------------------------------


@pytest.mark.parametrize("day, hour", [(FAIR_FIRST_DAY, 6), (FAIR_FIRST_DAY, 0),
                                       (FAIR_FIRST_DAY + 1, 8), (FAIR_FIRST_DAY + 1, 20)])
def test_a_sentence_started_at_any_hour_stops_at_nine_on_the_last_morning(hue, day, hour) -> None:
    """Review round 1: the serve used to ask the director only at each meal
    step (24h here), so a sentence begun before nine checked the last day
    before nine, then the day after the fair, and walked free. Now the
    director is asked every hour: whatever hour the serve began, it stops at
    nine on the fair's last day, and the gallows is dealt."""
    from engine.content import director
    from engine.world import law

    state = _held_for_the_fair(deed="resisting_watch", day=9, hour=12)
    _fed_until(state, day, hour)
    assert law.in_custody(state)
    served = law.serve_sentence(state)
    assert served["served_out"] is False and served["interrupted_by"] == GALLOWS, served
    assert (state.world_day, state.world_hour) == (FAIR_LAST_DAY, GALLOWS_HOUR)
    assert law.in_custody(state)
    assert director.ensure_scene(state)[0]["result"]["deck_id"] == GALLOWS


def _fair_with_a_door(tmp_path):
    """The shipped decks, plus a synthetic door card on the fair gated on
    `magpie_unmasked` -- the shape Tasks 5/6 fill F3-F6 with -- installed over
    the active story's `paths.decks`."""
    import shutil

    import yaml

    from engine.config import overlay, set_overlay

    src = _fair_deck_path().parent
    dst = tmp_path / "scenes"
    shutil.copytree(src, dst)
    doc = yaml.safe_load((dst / f"{FAIR}.yaml").read_text(encoding="utf-8"))
    doc["cards"].append({
        "id": "F9_test_door", "once": True, "tags": ["menu", "gm", "fair"],
        "title": "A Door", "text": "INTENT: a test door. MENU.",
        "when": {"flag": "magpie_unmasked"},
        "beats": [{"id": "walk_through", "text": "Walk through.",
                   "gate": {"on_pass": {"text": "Through."}}}],
    })
    (dst / f"{FAIR}.yaml").write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    layer = overlay()
    layer.setdefault("paths", {})["decks"] = str(dst)
    set_overlay(layer)


def _fair_deck_path():
    from pathlib import Path

    return (Path(__file__).resolve().parents[1] / "games" / "hue-and-cry" / "data"
            / "scenes" / f"{FAIR}.yaml")


def test_the_fair_deals_again_on_a_return_with_what_has_come_due(hue, tmp_path) -> None:
    """Controller's ruling (round 1): the fair is repeatable. Visit on day 10,
    leave, unmask the Magpie on day 11, come back: the door card that has
    come due since is offered, the Showing (`once`) is not dealt again, and
    the spine does not retell the whole fair."""
    from engine.content import director

    _fair_with_a_door(tmp_path)
    state = _city(11)
    _fair_on(state)
    state.location_id = "gallows_green"
    first = director.ensure_scene(state)[0]["result"]["card_ids"]
    assert first == ["F1_the_green", "F2_the_showing"], first
    _play_the_fair(state)
    assert state.flags.get("saw_the_hanging_fair")

    state.location_id = "wickmarket"
    assert director.ensure_scene(state) == []  # a turn off the Green re-arms it
    state.flags["magpie_unmasked"] = True
    _fed_until(state, FAIR_FIRST_DAY + 1, 10)
    state.location_id = "gallows_green"
    again = director.ensure_scene(state)[0]["result"]["card_ids"]
    # Since v0.17 T5 the real door comes due with the test one: F3, Cleared's.
    assert again == ["F1_the_green", "F3_the_real_magpie", "F9_test_door"], again


def test_a_return_to_the_fair_is_a_short_card(hue) -> None:
    """With nothing new due, a return deals the spine alone, and its beats
    that tell the fair the first time say nothing the second (the one beat
    that repeats is the ballad, which is sung all day)."""
    from engine.content import director

    state = _city(11)
    _fair_on(state)
    state.location_id = "gallows_green"
    director.ensure_scene(state)
    _play_the_fair(state)
    state.location_id = "wickmarket"
    director.ensure_scene(state)
    state.location_id = "gallows_green"
    again = director.ensure_scene(state)[0]["result"]["card_ids"]
    assert again == ["F1_the_green"], again
    spine = next(c for c in _fair_deck().cards if c.id == "F1_the_green")
    for beat in spine.beats:
        if beat["id"] == "the_ballad":
            continue
        assert beat["gate"]["when"] == {"not_flag": "saw_the_hanging_fair"}, beat["id"]


def test_the_way_down_the_hill_is_true_after_a_right_naming(hue) -> None:
    """Review round 1: a thief held on a lesser charge is hanged too after a
    right naming, so arguing that you are not the Magpie reads the Watch's
    belief (`linked`), and both branches still lock The Rope."""
    from engine.content import director
    from engine.game import endings
    from engine.game.effects import apply_effect

    card = _gallows_deck().cards[0]
    assert "nobody here knows" not in card.text.lower()
    argue = next(b for b in card.beats if b["id"] == "argue_the_case")
    assert argue["gate"]["when"] == {"linked": {"a": "self", "b": "magpie"}}
    for branch in ("on_pass", "on_fail"):
        assert argue["gate"][branch]["effects"][:2] == [
            {"type": "ending_lock", "ending": "the_rope"}, {"type": "ending_module"}], branch

    state = _held_for_the_fair()
    assert apply_effect(state, {"type": "law_unlink", "a": "self", "b": "magpie"})["ok"]
    _fed_until(state, FAIR_LAST_DAY, GALLOWS_HOUR)
    director.ensure_scene(state)
    assert director.resolve(state, chosen="argue_the_case").get("ok")
    assert endings.locked(state) == "the_rope"


def test_the_small_room_warns_of_the_fair(hue) -> None:
    """Review round 1: the at-risk player is the one in the cells before the
    fair, so the interrogation's spine tells them, from day 7 until the fair
    has come, that the Watch keeps its thieves for the last morning."""
    from engine.game.quests import evaluate_condition

    book = next(c for c in _interrogation_deck().cards if c.id == "Q1_the_book")
    warn = next(b for b in book.beats if b["id"] == "the_fair_coming")
    when = warn["gate"]["when"]
    assert "hanging fair" in warn["gate"]["on_pass"]["text"].lower()
    assert not warn["gate"].get("on_fail")

    state = _city(11)
    _fed_until(state, 6, 12)
    assert not evaluate_condition(state, when)
    _fed_until(state, 7, 12)
    assert evaluate_condition(state, when)
    _fed_until(state, FAIR_FIRST_DAY, 12)
    from engine.game.quests import QuestEngine

    QuestEngine.evaluate(state)
    assert not evaluate_condition(state, when)


# ---------------------------------------------------------------------------
# v0.17 Task 4: the jailbreak -- out of the Lantern House cells without
# paying or waiting, and on the fair's last morning the one way past the
# gallows for a thief who cannot pay
# ---------------------------------------------------------------------------

#: data/challenges/lantern_house.yaml: the first break-out, and the one
#: offered on every stay after it has once succeeded.
BREAK, BREAK_AGAIN = "lantern_house_break", "lantern_house_break_again"
BROKE_OUT = "broke_out_of_the_lantern_house"
#: What a failed attempt costs (the file's header argues it).
BEATING = 3


class _Sure(__import__("random").Random):
    """Rolls 19: passes every band a jailbreak uses, short of a natural crit
    (which would draw the boon table into a test not about boons)."""

    def randint(self, a: int, b: int) -> int:  # noqa: D102
        return max(a, b - 1)


class _Hopeless(__import__("random").Random):
    """Rolls 2: fails every band, short of a fumble."""

    def randint(self, a: int, b: int) -> int:  # noqa: D102
        return min(b, a + 1)


def _break_out(state, piece: str = BREAK, *, win: bool = True):
    """Start the piece and roll every step of it, won or lost. The receipt
    of the last step."""
    from engine.challenges import runner, set_pieces

    assert set_pieces.start(state, piece).status != runner.STATUS_ERROR
    rng = _Sure() if win else _Hopeless()
    result = None
    while state.challenge:
        result = set_pieces.resolve(state, rng=rng)
    return result


def _set_pieces_offered(state) -> tuple:
    from engine.game import intents

    verb = intents.find_verb(intents.legal_intents(state), "set_piece")
    return verb.targets if verb is not None else ()


def test_hue_and_cry_declares_the_jailbreak(hue) -> None:
    """Two gauntlets in the cells, gated on custody: never a dice table
    (every row of one is a success, AUTHORING §3.11), `release` only on a
    win, a hiding on a loss, and every text inside the spec's limits (the
    bounder truncates silently)."""
    from engine.challenges import set_pieces
    from engine.challenges import spec as spec_module
    from engine.world import law

    catalogue = set_pieces.load_set_pieces()
    assert set(catalogue) == {BREAK, BREAK_AGAIN}
    gaol = law.load_spec()["arrest"]["gaol"]
    for piece_id, piece in catalogue.items():
        assert piece["location_id"] == gaol
        assert piece["requires"] == {"in_custody": True}
        challenge = piece["challenge"]
        assert challenge["kind"] == "skill_gauntlet", piece_id
        assert set_pieces.set_piece_problems(piece) == [], piece_id
        checked = spec_module.validate(challenge, authored=True)
        assert checked.ok and checked.adjustments == [], (piece_id, checked.adjustments)
        assert checked.spec["reward"]["effects"] == [
            {"type": "release"},
            {"type": "report", "deed": "escape", "guise": "self",
             "jurisdiction": "wick", "precision": 1.0}]
        assert checked.spec["fail"]["effects"] == [{"type": "hp", "delta": -BEATING}]
        for step in challenge["steps"]:
            assert len(step["text"].strip()) <= spec_module.MAX_TEXT, piece_id
            assert len(step["on_fail_text"].strip()) <= 200, piece_id
        for key in ("reward", "fail"):
            assert len(challenge[key]["text"].strip()) <= spec_module.MAX_TEXT, piece_id
    assert catalogue[BREAK]["grants_flag"] == BROKE_OUT
    # The second reads the first's flag and grants none: offered every stay after.
    assert catalogue[BREAK_AGAIN]["requires_flags"] == [BROKE_OUT]
    assert "grants_flag" not in catalogue[BREAK_AGAIN]
    assert law.load_spec()["deeds"]["escape"] == 4


def test_the_jailbreak_is_offered_in_the_cell_once_the_questions_are_done(hue) -> None:
    """Held: the interrogation is the first turn of a stay and owns it --
    only `card` is offered -- and from the next turn the break-out is. Free,
    even standing in the Lantern House, it is not."""
    from engine.content import director
    from engine.game import intents

    state = _city(11)
    _fed_until(state, 3, 12)
    state.location_id = "lantern_house"
    assert _set_pieces_offered(state) == ()
    _arrest_on(state)
    dealt = director.ensure_scene(state)
    assert dealt and dealt[0]["result"]["deck_id"] == INTERROGATION
    guard = 0
    while director.active(state) and guard < 16:
        guard += 1
        assert {v.action for v in intents.legal_intents(state)} == {"card"}
        assert _set_pieces_offered(state) == ()
        director.resolve(state, chosen=director.options(state)[0]["id"])
    assert not director.active(state)
    assert _set_pieces_offered(state) == (BREAK,)
    verbs = {v.action for v in intents.legal_intents(state)}
    assert {"rest", "serve", "set_piece"} <= verbs and "travel" not in verbs


def test_a_break_out_frees_the_thief_and_files_an_escape(hue) -> None:
    """Released where the Watch held you, still wanted for everything the
    arrest charged (a break-out discharges nothing) and now for the escape
    too: a report filed by the Lantern House against your own face in the
    Wick at full precision, so the Wick's heat on you rises."""
    from engine.world import law

    state = _held_for_the_fair(day=3)
    charged = list(law.custody(state)["charged"])
    before = law.wanted_score(state, "self", "wick")
    reports = len(state.law["reports"])
    result = _break_out(state)
    assert result.ended and result.success
    assert not law.in_custody(state)
    assert state.location_id == "lantern_house"
    assert state.flags.get(BROKE_OUT) is True
    rows = state.law["reports"][reports:]
    assert [(r["deed"], r["guise"], r["jurisdiction"], r["precision"]) for r in rows] == [
        ("escape", "self", "wick", 1.0)]
    assert all(d not in law.discharged(state) for d in charged)
    assert {r["deed_id"] for r in state.law["reports"]} >= set(charged)
    assert law.wanted_score(state, "self", "wick") > before
    assert _set_pieces_offered(state) == ()


def test_a_failed_break_out_is_a_hiding_and_the_cell_still_rests(hue) -> None:
    """Failure costs hp and the rest of the day: still held, nothing filed,
    the bench still a bed (rule 6), `serve` still ends the stay, and the
    break not offered again until tomorrow (fix round 1)."""
    from engine.agents.tool_dispatcher import execute_intent
    from engine.game import intents
    from engine.game.engine import GameEngine
    from engine.world import law

    state = _held_for_the_fair(day=3)
    held = law.custody(state)
    hp = state.stats.hp
    reports = list(state.law["reports"])
    result = _break_out(state, win=False)
    assert result.ended and not result.success
    assert law.in_custody(state) and law.custody(state) == held
    assert state.stats.hp == hp - BEATING
    assert state.law["reports"] == reports
    assert not state.flags.get(BROKE_OUT)
    assert _set_pieces_offered(state) == ()
    verbs = {v.action: v for v in intents.legal_intents(state)}
    assert "sleep_cell" in {t for t, _ in verbs["rest"].options}
    engine = GameEngine(state)
    (rested,) = execute_intent({"action": "rest", "target": "sleep_cell"}, engine)
    assert rested["success"] and not rested.get("refused")
    served = law.serve_sentence(state)
    assert served["served_out"] is True and not law.in_custody(state), served


def test_after_one_break_out_the_window_bar_is_offered_on_every_stay(hue) -> None:
    """The ring on the nail is one-shot (its flag retires it); the window
    bar reads that flag and grants none, so every later stay has a way out
    that is neither the fine nor the wait."""
    from engine.content import director
    from engine.world import law

    state = _held_for_the_fair(day=2)
    _break_out(state)
    for day in (4, 6):
        # A turn walked free, so the interrogation re-arms for the next stay.
        assert director.ensure_scene(state) == []
        _fed_until(state, day, 12)
        _arrest_on(state)
        _questioned(state)
        assert _set_pieces_offered(state) == (BREAK_AGAIN,), day
        assert _break_out(state, BREAK_AGAIN).success
        assert not law.in_custody(state)


def test_a_thief_held_for_the_fair_breaks_out_on_day_eleven_and_is_not_hanged(hue) -> None:
    """The ruling's case: held since before the fair, no coin, day 11 --
    the break-out is offered, it frees the thief, and at nine on the last
    morning the gallows has nobody to deal to."""
    from engine.content import director
    from engine.game import endings
    from engine.world import law

    state = _held_for_the_fair()
    state.stats.gold = 0
    _fed_until(state, FAIR_LAST_DAY - 1, 14)
    assert law.in_custody(state)
    assert _set_pieces_offered(state) == (BREAK,)
    assert _break_out(state).success
    assert not law.in_custody(state)
    _fed_until(state, FAIR_LAST_DAY, GALLOWS_HOUR)
    assert director.due(state)[0] != GALLOWS
    assert all(r["result"].get("deck_id") != GALLOWS for r in director.ensure_scene(state))
    _fed_until(state, FAIR_LAST_DAY, GALLOWS_HOUR + 3)
    assert director.due(state)[0] != GALLOWS
    assert endings.locked(state) == endings.NONE_ID and not state.ended


def test_the_break_out_is_there_until_nine_on_the_last_morning(hue) -> None:
    """No path strands a saved-up thief without it: at 08:00 on the last
    morning the gallows is not yet due and the break-out is offered; the
    last minute before nine is still a way out."""
    from engine.content import director
    from engine.world import law

    state = _held_for_the_fair()
    _fed_until(state, FAIR_LAST_DAY, GALLOWS_HOUR - 1)
    assert director.due(state)[0] != GALLOWS
    assert _set_pieces_offered(state) == (BREAK,)
    assert _break_out(state).success and not law.in_custody(state)


def test_a_hiding_that_kills_is_a_death_on_that_step(hue) -> None:
    """The hp a failed attempt takes is checked on the step that took it,
    as a card's is: before the fair the thief wakes on the same bench, still
    held; held during the fair it is The Rope."""
    from engine.game import endings
    from engine.world import law

    early = _held_for_the_fair(day=5)
    early.stats.hp = BEATING - 1
    result = _break_out(early, win=False)
    assert result.death is not None and result.death.get("kept_in_custody"), result
    assert law.in_custody(early) and early.location_id == "lantern_house"
    assert not early.ended
    assert result.to_dict()["death"] == result.death

    fair = _held_for_the_fair()
    _fed_until(fair, FAIR_LAST_DAY - 1, 14)
    fair.stats.hp = BEATING - 1
    result = _break_out(fair, win=False)
    assert result.death is not None
    assert fair.ended and endings.locked(fair) == "the_rope"


def test_a_challenge_that_kills_says_so_in_its_receipt(hue) -> None:
    """The narrator hears the death as the step's last sentence, as it does
    a card's; a challenge that took no hp carries no `death` key at all."""
    from engine.agents import prompts
    from engine.challenges import runner

    line = prompts.summarise_receipt({"skill": "resolve_challenge", "result": {
        "text": "The ring jingles.", "death": {"text": "You come to on the bench."}}})
    assert line.endswith("You come to on the bench.")
    assert "death" not in runner.ChallengeResult(text="x").to_dict()


def test_the_jailbreak_replays_from_its_seed(hue) -> None:
    """Rolled on the challenge stream: the same seed and the same choices
    break out, or fail, identically."""
    from engine.challenges import set_pieces

    outcomes = []
    for _ in range(2):
        state = _held_for_the_fair(day=3)
        set_pieces.start(state, BREAK)
        steps = []
        while state.challenge:
            steps.append(set_pieces.resolve(state).to_dict())
        outcomes.append((steps, state.stats.hp, dict(state.law.get("custody") or {})))
    assert outcomes[0] == outcomes[1]


# -- v0.17 Task 4, fix round 1: one try a day, a hiding that reads true either way


def test_a_failed_break_out_waits_for_the_next_day(hue) -> None:
    """The ruling: one try a day. A hiding at noon closes the break-out for
    the rest of that day -- resting to evening does not reopen it -- and
    midnight does. Both pieces declare it (`retry: next_day`)."""
    from engine.challenges import set_pieces
    from engine.world import law

    for piece in set_pieces.load_set_pieces().values():
        assert piece.get("retry") == "next_day", piece["id"]
    state = _held_for_the_fair(day=3)
    assert not _break_out(state, win=False).success
    assert _set_pieces_offered(state) == ()
    _fed_until(state, 3, 23)
    assert law.in_custody(state) and _set_pieces_offered(state) == ()
    _fed_until(state, 4, 0)
    assert _set_pieces_offered(state) == (BREAK,)
    assert _break_out(state).success and not law.in_custody(state)


def test_a_thief_saved_for_the_fair_has_a_try_on_each_day_before_the_gallows(hue) -> None:
    """The fair-day door is kept: held since day 9, a thief who fails on days
    10 and 11 still has a try on day 12 before nine, and one that works then
    is not hanged."""
    from engine.content import director
    from engine.world import law

    state = _held_for_the_fair()
    for day, hour in ((FAIR_FIRST_DAY, 10), (FAIR_LAST_DAY - 1, 10)):
        _fed_until(state, day, hour)
        assert _set_pieces_offered(state) == (BREAK,), day
        assert not _break_out(state, win=False).success
        assert _set_pieces_offered(state) == (), day
    _fed_until(state, FAIR_LAST_DAY, GALLOWS_HOUR - 1)
    assert _set_pieces_offered(state) == (BREAK,)
    assert _break_out(state).success and not law.in_custody(state)
    _fed_until(state, FAIR_LAST_DAY, GALLOWS_HOUR)
    assert director.due(state)[0] != GALLOWS


def test_the_hiding_text_is_true_whether_or_not_it_kills(hue) -> None:
    """A hiding that kills is followed by the death's text (the bench, or
    The Rope), so no failure text promises the thief is fine."""
    from engine.challenges import set_pieces

    for piece in set_pieces.load_set_pieces().values():
        challenge = piece["challenge"]
        texts = [s["on_fail_text"] for s in challenge["steps"]] + [challenge["fail"]["text"]]
        for text in texts:
            lowered = " ".join(text.lower().split())
            for promise in ("nothing broken", "for days", "sore ribs", "you'll live",
                            "no worse"):
                assert promise not in lowered, (piece["id"], promise)


def _hue_issues_with(tmp_path, *, pieces=None, deck=None) -> list[str]:
    """HUE & CRY validated with a set-piece file and/or one extra deck swapped
    in from tmp. Errors only, as `source|ref|message`."""
    import yaml

    from engine.games import validation

    manifest = registry.get("hue-and-cry")
    paths = dict(manifest.paths)
    if pieces is not None:
        directory = tmp_path / "challenges"
        directory.mkdir()
        (directory / "cells.yaml").write_text(yaml.safe_dump({"set_pieces": pieces}),
                                              encoding="utf-8")
        paths["challenges"] = str(directory)
    if deck is not None:
        directory = tmp_path / "scenes"
        directory.mkdir()
        (directory / f"{deck['id']}.yaml").write_text(yaml.safe_dump(deck), encoding="utf-8")
        paths["decks"] = str(directory)
    patched = type(manifest)(**{**manifest.__dict__, "paths": paths})
    return [f"{i.source}|{i.ref_id}|{i.message}"
            for i in validation.errors_only(validation.validate_story(patched))]


def _piece_filing(report: dict) -> dict:
    return {
        "id": "typo_break", "location_id": "lantern_house",
        "requires": {"in_custody": True},
        "challenge": {
            "id": "typo_break", "kind": "skill_gauntlet", "title": "Typo",
            "steps": [{"skill": "stealth", "difficulty": "easy", "text": "Go."}],
            "reward": {"text": "Out.", "effects": [{"type": "release"}, report]},
            "fail": {"text": "In.", "effects": []},
        },
    }


@pytest.mark.parametrize("field, bad", [("deed", "escpae"), ("guise", "selfe"),
                                        ("jurisdiction", "wicks")])
def test_a_report_naming_what_the_law_file_lacks_is_an_error(hue, tmp_path, field, bad) -> None:
    """Fix round 1: a `report` effect whose deed, guise or jurisdiction the
    law file does not declare is refused at runtime and files nothing. The
    validator names it, in a set-piece and in a deck card alike."""
    report = {"type": "report", "deed": "escape", "guise": "self",
              "jurisdiction": "wick", "precision": 1.0, field: bad}
    issues = _hue_issues_with(tmp_path, pieces=[_piece_filing(report)])
    hits = [i for i in issues if bad in i and "report" in i]
    assert hits and "cells.yaml" in hits[0], issues

    deck = {"id": "typo_deck", "draw": 1, "when": {"in_custody": True}, "cards": [{
        "id": "typo_card", "required": True, "tags": ["sequence"], "title": "Typo",
        "text": "INTENT: a report.", "beats": [{"id": "go", "text": "Filed.",
                                               "effects": [report]}]}]}
    (tmp_path / "d").mkdir()
    issues = _hue_issues_with(tmp_path / "d", deck=deck)
    hits = [i for i in issues if bad in i and "report" in i]
    assert hits and "typo_deck.yaml" in hits[0], issues


def test_the_shipped_reports_name_what_the_law_file_declares(hue, tmp_path) -> None:
    report = {"type": "report", "deed": "escape", "guise": "self",
              "jurisdiction": "wick", "precision": 1.0}
    issues = _hue_issues_with(tmp_path, pieces=[_piece_filing(report)])
    assert not [i for i in issues if "report" in i.split("|")[-1]], issues


def test_custody_served_is_the_engines_alone(hue, tmp_path) -> None:
    """Fix round 1: `custody_served` is bookkeeping `serve` writes. Authored
    content naming it is refused: an agenda move at load, anything else by
    the validator. A card, a thread and a set-piece's bounder drop it too."""
    from engine.challenges import spec as spec_module
    from engine.game import effects
    from engine.world import agendas

    assert "custody_served" in effects.ENGINE_ONLY_EFFECTS
    assert effects.ENGINE_ONLY_EFFECTS <= agendas.BOOKKEEPING_EFFECTS
    adjustments: list[str] = []
    out = spec_module.clamp_outcome({"effects": [{"type": "custody_served", "hours": 24}]},
                                    adjustments, authored=True,
                                    extra_types=spec_module.AUTHORED_CHALLENGE_EFFECT_TYPES)
    assert out["effects"] == []
    issues = _hue_issues_with(tmp_path, pieces=[_piece_filing(
        {"type": "custody_served", "hours": 72})])
    assert [i for i in issues if "custody_served" in i and "engine" in i], issues


# ---------------------------------------------------------------------------
# v0.17 Task 5: endings I -- Cleared, A Lantern, Honest After All
# ---------------------------------------------------------------------------

#: The three earned endings this task declares (data/rules/endings.yaml).
ENDINGS_I = ("cleared", "a_lantern", "honest_after_all")
#: A Lantern's standing with the Watch (endings.yaml `a_lantern`
#: `lamps_kept`), MEASURED: the header there has the table.
LANTERN_STANDING = 5
#: The labour record: written by every paid shift (labour.yaml `effects`).
HONEST_WAGE = "honest_wage_earned"
#: F3 at the fair: Cleared's door. D3 at the front desk: A Lantern's.
F3 = "F3_the_real_magpie"
BADGE_CARD = "D3_the_badge"
#: Guildmaster's standing with the Honest Company (endings.yaml `guildmaster`
#: `the_hall_trusts_you`), MEASURED in v0.17 T6 (scripts/simulate_labour.py
#: --endings; pinned by test_guildmasters_standing_is_the_measured_one).
GUILD_STANDING = 5
#: The four postings, where and when each is open.
POSTINGS = (("dock_portering", "tallow_docks", 7), ("candle_dipping", "chandlers_rise", 7),
            ("market_errands", "wickmarket", 9), ("lamplighting", "wickmarket", 18))


def _eligible(state, ending_id: str) -> bool:
    from engine.game import endings

    return ending_id in endings.eligible(state).eligible


def _earn_an_honest_wage(state) -> None:
    """A shift for Dock Mag the way a player works one -- `economy.work`, the
    real roll -- repeated on the next morning until one is paid."""
    from engine.game import economy
    from engine.game.clock import advance_time
    from engine.game.effects import apply_effect

    state.location_id = "tallow_docks"
    for _ in range(8):
        hour = int(state.world_hour)
        if not 5 <= hour < 13:
            advance_time(state, (7 - hour) % 24 or 24)
        apply_effect(state, {"type": "hunger", "delta": -state.hunger})
        apply_effect(state, {"type": "stamina", "delta": state.stats.max_stamina})
        receipt = economy.work(state, "dock_portering")
        assert receipt["worked"], receipt
        if state.flags.get(HONEST_WAGE):
            return
    raise AssertionError("eight mornings on the quay and never paid")


def _lamps_kept(state, standing: int = LANTERN_STANDING) -> None:
    from engine.game.effects import apply_effect

    apply_effect(state, {"type": "reputation", "faction": "lantern_watch", "delta": standing})


@pytest.mark.parametrize("job,place,hour", POSTINGS)
@pytest.mark.parametrize("degree", ["crit_success", "success", "partial", "failure"])
def test_an_honest_wage_goes_on_the_record_only_when_it_is_paid(
        hue, monkeypatch, job, place, hour, degree) -> None:
    """The labour record Honest After All reads: a posting's `effects`, fired
    on the degrees that pay. A botched shift took the hours and paid nothing,
    and it is no wage."""
    from engine.game import economy
    from engine.game.clock import set_clock

    monkeypatch.setattr("engine.game.checks.resolve", lambda *a, **k: _Forced(degree))
    state = _city(11)
    state.location_id = place
    set_clock(state, day=2, hour=hour)
    receipt = economy.work(state, job)
    assert receipt["worked"] is True, receipt
    assert bool(state.flags.get(HONEST_WAGE)) is (degree != "failure"), (job, degree)
    assert (receipt["wage"] > 0) is (degree != "failure"), receipt


def test_every_posting_keeps_the_record(hue) -> None:
    """All four postings write it, on exactly the degrees their pay table pays."""
    from engine.game import economy

    for job in economy.load_rules()["jobs"]:
        rows = [e for e in job.get("effects") or [] if e.get("flag") == HONEST_WAGE]
        assert len(rows) == 1, job["id"]
        paid = {d for d, share in job["pay"].items() if share > 0}
        assert set(rows[0]["degrees"]) == paid, job["id"]


def test_the_validator_counts_a_postings_effects_as_the_writer(hue, tmp_path) -> None:
    """The two-direction flag sweep sees the labour table's `effects`: with
    them the ending's gate has its writer; without them it is a gate that
    can never open, and the validator says so."""
    import shutil
    from pathlib import Path

    import yaml

    from engine.games import validation

    manifest = registry.get("hue-and-cry")
    root = Path(__file__).resolve().parents[1]
    tables = tmp_path / "tables"
    shutil.copytree(root / manifest.paths["tables"], tables)
    doc = yaml.safe_load((tables / "labour.yaml").read_text(encoding="utf-8"))
    for job in doc["jobs"]:
        job.pop("effects", None)
    (tables / "labour.yaml").write_text(yaml.safe_dump(doc), encoding="utf-8")
    patched = type(manifest)(**{**manifest.__dict__,
                                "paths": {**manifest.paths, "tables": str(tables)}})
    issues = [f"{i.source}|{i.ref_id}|{i.message}"
              for i in validation.errors_only(validation.validate_story(patched))]
    assert [i for i in issues if HONEST_WAGE in i and "never written" in i], issues
    shipped = [f"{i.source}|{i.ref_id}|{i.message}"
               for i in validation.errors_only(validation.validate_story("hue-and-cry"))]
    assert not [i for i in shipped if HONEST_WAGE in i], shipped


def test_the_first_three_earned_endings_are_declared_whole(hue) -> None:
    """Each: earned (a `requires`), Speak/Act/Seal, a card, the same title."""
    from engine.game import endings, epilogue

    declared = endings.declared()
    cards = epilogue.declared()
    assert set(declared) == set(cards), (sorted(declared), sorted(cards))
    for ending_id in ENDINGS_I:
        body = declared[ending_id]
        assert body.get("requires"), ending_id
        assert [b["id"] for b in body["beats"]] == [
            f"{ending_id}_{w}" for w in ("speak", "act", "seal")], ending_id
        for beat in body["beats"]:
            word = beat["id"].rsplit("_", 1)[1].upper()
            assert beat["text"].startswith(f"{word}."), beat["id"]
        assert cards[ending_id]["card_m"].strip() and cards[ending_id]["card_g"].strip()
        assert cards[ending_id]["title"] == body["label"], ending_id
        assert body.get("tease"), ending_id


def test_every_lock_reason_names_a_clause(hue) -> None:
    """A `lock_reasons` line whose clause id is not in the gate is prose the
    gallery can never show."""
    from engine.game import endings
    from engine.games.validation import walk

    for ending_id in ENDINGS_I:
        body = endings.declared()[ending_id]
        ids = {str(n["id"]) for n in walk([body.get("requires"), body.get("completable")])
               if n.get("id")}
        assert set(body.get("lock_reasons") or {}) == ids, (ending_id, ids)


def test_cleared_is_earned_only_by_the_unmasking(hue) -> None:
    """The Watch's belief broken -- a right naming -- and nothing less: an
    alibi clears nights, not the name. A wrong naming left standing shuts it
    (`completable`) until a right one corrects it."""
    from engine.game import endings
    from engine.game.effects import apply_effect

    state = _city(11)
    assert not _eligible(state, "cleared")
    apply_effect(state, {"type": "flag", "flag": "alibi_proven"})
    assert not _eligible(state, "cleared")
    apply_effect(state, {"type": "flag", "flag": "magpie_named_wrongly"})
    report = endings.eligible(state)
    assert "cleared" in report.unreachable and "cleared" not in report.eligible
    _unmask(state)
    assert _eligible(state, "cleared")


def test_a_lantern_asks_the_unmasking_the_lamps_and_no_squeeze(hue) -> None:
    """Each clause alone shuts it: no right naming; the Watch's opinion one
    short; the captain's own file ever used against her (struck, whether or
    not it was paid)."""
    from engine.game import threads

    ready = _city(11)
    _unmask(ready)
    _lamps_kept(ready)
    assert _eligible(ready, "a_lantern")

    never_named = _city(11)
    _lamps_kept(never_named)
    assert not _eligible(never_named, "a_lantern")

    short = _city(11)
    _unmask(short)
    _lamps_kept(short, LANTERN_STANDING - 1)
    assert not _eligible(short, "a_lantern")

    squeezed = _city(11)
    _at(squeezed, "lantern_house", 19)
    _hold(squeezed, "captains_office")
    _file(squeezed, "magpie")
    thread = _seal(squeezed, "ardane_magpie_file")
    _unmask(squeezed)
    _lamps_kept(squeezed)
    assert not _eligible(squeezed, "a_lantern")
    assert threads.discharge(squeezed, thread["id"])["ok"]
    assert not _eligible(squeezed, "a_lantern")   # paid or not, it was struck

    # Broken (left to come due, or reneged): struck all the same. The break
    # costs the Watch's standing (-10); it is made up here so the squeeze is
    # the one clause that shuts the door.
    broken = _city(11)
    _at(broken, "lantern_house", 19)
    _hold(broken, "captains_office")
    _file(broken, "magpie")
    thread = _seal(broken, "ardane_magpie_file")
    assert threads.break_thread(broken, thread["id"])["ok"]
    assert threads.get(broken, thread["id"])["status"] == threads.STATUS_BROKEN
    _unmask(broken)
    _lamps_kept(broken, LANTERN_STANDING + 10)
    assert not _eligible(broken, "a_lantern")


def test_a_lanterns_standing_is_the_measured_one(hue) -> None:
    """The number this module (and tests/test_finales.py's A Lantern door)
    walks with is the one endings.yaml gates on."""
    from engine.game import endings
    from engine.games.validation import walk

    body = endings.declared()["a_lantern"]
    rows = [n["reputation"] for n in walk(body["requires"]) if "reputation" in n]
    assert rows == [{"faction": "lantern_watch", "min": LANTERN_STANDING}], rows


def _sought_on_the_quay(state) -> None:
    from engine.world import law

    for _ in range(6):
        if law.wanted_band(state, "self", "quay") in ("sought", "wanted", "hunted"):
            _file_in(state, "self", "quay")   # one more: the hours to dusk cool it
            return
        _file_in(state, "self", "quay")
    raise AssertionError(law.wanted_band(state, "self", "quay"))


def _on_credit(state) -> None:
    _at(state, "wickmarket", 10)
    _seal(state, "pell_advance")
    state.location_id = "tallow_docks"


def _welshed(state) -> None:
    from engine.game.effects import apply_effect

    apply_effect(state, {"type": "flag", "flag": "welshed_on_marrow"})


def _unmasked_with_the_heart(state) -> None:
    """T6 review round 1: the Magpie named rightly (the link broken), then the
    heart lifted at the Showing -- F2's own on_pass effects, whose
    `sacrilege` is filed on the MAGPIE's mask, so after the unlink your own
    record stays clean. The heart is in the pack all the same."""
    from engine.content import deck
    from engine.game.effects import apply_effect

    _unmask(state)
    card = next(c for c in deck.load_deck("fair_day").cards if c.id == "F2_the_showing")
    beat = next(b for b in card.beats if b["id"] == "lift_the_heart")
    for effect in beat["gate"]["on_pass"]["effects"]:
        if effect["type"] != "ledger_fact":   # (no session ledger here)
            assert apply_effect(state, effect)["ok"], effect


#: One failing clause of Honest After All each, and the refusal words that
#: must reach the narrator for it.
HONEST_BREAKS = {
    "no_wage": (None, "honest wage"),
    "sought": (_sought_on_the_quay, "looking for your face"),
    "credit": (_on_credit, "owe"),
    "welshed": (_welshed, "owe"),
    # v0.17 T6 review round 1: a clean record and the Everflame's heart.
    "heart": (_unmasked_with_the_heart, "Everflame's heart"),
}


def _a_purse_nobody_saw(state) -> None:
    """One lift, committed where nobody is (the bell tower's beam): no witness,
    no report -- the Watch's file stays empty -- and the deed is counted."""
    from engine.world import law

    seen = law.commit_deed(state, "pickpocket", location=UNSEEN_PLACE)
    assert seen == {"witnesses": [], "reported": False}, seen


#: A place nobody is (a secret loft): a deed there is seen by no one.
UNSEEN_PLACE = "old_bell_tower"
# T8 fix round 1 (the owner's ruling): no thieving at all, seen or unseen.
HONEST_BREAKS["stole"] = (_a_purse_nobody_saw, "taken what was not yours")


# T8 fix round 2 (I2): a squeeze struck and paid is thieving too.
def _squeezed_and_paid(state) -> None:
    """A squeeze struck and paid (Gannet's strike-fund IOUs, the Company's
    head at the long table): nothing committed, nothing filed -- and it was
    a squeeze all the same."""
    from engine.game import threads
    from engine.game.effects import apply_effect
    from engine.world import jobs

    apply_effect(state, {"type": "flag",
                         "flag": f"{jobs.SECRET_HELD_PREFIX}prem_gannets_house:fund_of_ious"})
    _at(state, "the_snuffs", 20)
    sealed = threads.seal(state, threads.offer(state, "gannet_ious"))
    assert sealed["ok"], sealed
    assert threads.discharge(state, sealed["thread"]["id"])["ok"]
    state.location_id = "tallow_docks"


HONEST_BREAKS["squeezed"] = (_squeezed_and_paid, "squeeze")


def _honest_ready(seed: int = 11):
    """Clean, square, and a wage earned on the quay: the barge will take you."""
    state = _city(seed)
    _earn_an_honest_wage(state)
    return state


def test_honest_after_all_asks_a_clean_name_square_fences_and_an_honest_wage(hue) -> None:
    ready = _honest_ready()
    assert _eligible(ready, "honest_after_all")
    for case, (breaker, _words) in HONEST_BREAKS.items():
        state = _city(11) if breaker is None else _honest_ready()
        if breaker is not None:
            breaker(state)
        assert not _eligible(state, "honest_after_all"), case


def test_noticed_is_clean_enough_for_the_barge(hue) -> None:
    """The line is `sought`: one blurred sighting on the Quay (`noticed`) does
    not keep an honest thief off the barge."""
    from engine.game.effects import apply_effect
    from engine.world import law

    state = _honest_ready()
    apply_effect(state, {"type": "report", "deed": "pickpocket", "guise": "self",
                         "jurisdiction": "quay", "precision": 0.3})
    assert law.wanted_band(state, "self", "quay") in ("unknown", "noticed")
    assert _eligible(state, "honest_after_all")


def _barge_at_dusk(state) -> None:
    """On the docks at six in the evening, the barge's quest open."""
    from engine.game.clock import advance_time
    from engine.game.quests import QuestEngine

    QuestEngine.evaluate(state)
    state.location_id = "tallow_docks"
    advance_time(state, (18 - int(state.world_hour)) % 24 or 24)
    QuestEngine.evaluate(state)


@pytest.mark.parametrize("case", sorted(HONEST_BREAKS))
def test_the_barge_refuses_the_unearned_and_the_narrator_hears_why(hue, case) -> None:
    """Audit question 2. The barge's stage waits on the ending's own gate, so
    an unearned thief cannot leave: the quest simply does not complete, and
    no ending is locked. The narrator is told why in the objective line --
    the stage's `refusals` -- and is not handed the flag that would say
    "aboard", so it cannot narrate a departure the engine refused."""
    from engine.agents import prompts
    from engine.game import endings
    from engine.game.effects import apply_effect
    from engine.game.quests import QuestEngine, progress_records

    breaker, words = HONEST_BREAKS[case]
    state = _city(11) if breaker is None else _honest_ready()
    if breaker is not None:
        breaker(state)
    _barge_at_dusk(state)
    block = prompts._objectives_block(state)
    assert "The Evening Barge" in block and words in block, (case, block)
    assert "nf_boarded_the_evening_barge" not in QuestEngine.allowed_narrative_flags(state)
    # Even a flag raised by other means is no ticket.
    apply_effect(state, {"type": "flag", "flag": "nf_boarded_the_evening_barge"})
    QuestEngine.evaluate(state)
    assert progress_records(state)["the_evening_barge"].status == "active"
    assert endings.locked(state) == endings.NONE_ID


def test_an_earned_barge_says_nothing_of_refusal_and_offers_the_flag(hue) -> None:
    from engine.agents import prompts
    from engine.game.quests import QuestEngine

    state = _honest_ready()
    _barge_at_dusk(state)
    block = prompts._objectives_block(state)
    assert "The Evening Barge" in block and "Not yet" not in block, block
    assert "nf_boarded_the_evening_barge" in QuestEngine.allowed_narrative_flags(state)


def test_the_barges_refusals_mirror_the_endings_gate(hue) -> None:
    """The stage's refusals restate endings.yaml's clauses in the
    bargemaster's words: over every case, a refusal holds exactly when the
    ending is not earned."""
    from engine.game.quests import QuestEngine, load_quests

    stage = load_quests()["the_evening_barge"]["stages"][0]
    states = [_honest_ready()]
    for breaker, _words in HONEST_BREAKS.values():
        state = _city(11) if breaker is None else _honest_ready()
        if breaker is not None:
            breaker(state)
        states.append(state)
    for state in states:
        refused = QuestEngine.stage_refusal(state, stage)
        assert bool(refused) is (not _eligible(state, "honest_after_all")), refused


@pytest.mark.parametrize("bad, words", [
    ({"when": {"wantd": {"min": "sought"}}, "text": "no"}, "unknown predicate `wantd`"),
    ({"when": {"flag": "x"}}, "needs a `when` and a `text`"),
    ({"when": {"disposition": {"npc": "npc_dock_mag", "min": 1}}, "text": "no"}, "ledger"),
])
def test_a_stage_refusal_the_engine_cannot_read_is_an_error(hue, tmp_path, bad, words) -> None:
    """The validator reads a stage's `refusals` as the thread and bed
    refusals are read: a list of {when, text}, the `when` in the grammar and
    answerable with no ledger (the objective line is built with none)."""
    import shutil
    from pathlib import Path

    import yaml

    from engine.games import validation

    manifest = registry.get("hue-and-cry")
    root = Path(__file__).resolve().parents[1]
    quests = tmp_path / "quests"
    shutil.copytree(root / manifest.paths["quests"], quests)
    barge = quests / "the_way_out" / "the_evening_barge.yaml"
    doc = yaml.safe_load(barge.read_text(encoding="utf-8"))
    doc["stages"][0]["refusals"] = [bad]
    barge.write_text(yaml.safe_dump(doc), encoding="utf-8")
    patched = type(manifest)(**{**manifest.__dict__,
                                "paths": {**manifest.paths, "quests": str(quests)}})
    issues = [f"{i.source}|{i.ref_id}|{i.message}"
              for i in validation.errors_only(validation.validate_story(patched))]
    hits = [i for i in issues if "refusals" in i and words in i]
    assert hits and "the_evening_barge" in hits[0], issues


def test_the_barge_gates_on_the_ending_itself(hue) -> None:
    """One source of truth: the stage asks `ending: {eligible:
    honest_after_all}`, not a copy of its clauses."""
    from engine.game.quests import load_quests

    stage = load_quests()["the_evening_barge"]["stages"][0]
    assert {"ending": {"eligible": "honest_after_all"}} in stage["complete_when"]["all"]


# -- Cleared's door: F3 at the fair -------------------------------------------


def _unmasked_on_the_green(seed: int = 11):
    state = _city(seed)
    _fair_on(state)
    _unmask(state)
    state.location_id = "gallows_green"
    return state


def test_the_real_magpie_is_dealt_at_the_fair_only_once_unmasked(hue) -> None:
    from engine.content import director

    masked = _city(11)
    _fair_on(masked)
    masked.location_id = "gallows_green"
    dealt = director.ensure_scene(masked)
    assert F3 not in dealt[0]["result"]["card_ids"]

    state = _unmasked_on_the_green()
    dealt = director.ensure_scene(state)
    assert dealt[0]["result"]["deck_id"] == FAIR
    assert F3 in dealt[0]["result"]["card_ids"]


def test_walking_away_from_the_real_magpie_is_not_final(hue) -> None:
    """Owner's decision (T5 review): F3 is gated on its own ending's
    eligibility and NOT `once` -- a thief who walks away locks nothing, and
    is offered it again on the next return to the Green while the fair is
    on. It cannot be walked through twice: a locked run never locks again."""
    from engine.content import director
    from engine.game import endings

    state = _unmasked_on_the_green()
    dealt = director.ensure_scene(state)
    assert F3 in dealt[0]["result"]["card_ids"]
    walked = False
    guard = 0
    while director.active(state) and guard < 8:
        guard += 1
        card = director.current_card(state)
        chosen = "walk_away" if card.id == F3 else director.options(state)[0]["id"]
        walked = walked or card.id == F3
        assert director.resolve(state, chosen=chosen)["ok"]
    assert walked
    assert endings.locked(state) == endings.NONE_ID
    state.location_id = "wickmarket"
    director.ensure_scene(state)
    state.location_id = "gallows_green"
    dealt = director.ensure_scene(state)
    assert F3 in dealt[0]["result"]["card_ids"]
    while director.active(state):
        card = director.current_card(state)
        chosen = "see_it_done" if card.id == F3 else director.options(state)[0]["id"]
        assert director.resolve(state, chosen=chosen)["ok"]
    assert endings.locked(state) == "cleared"
    assert endings.lock(state, "cleared")["ok"] is False   # never twice


def test_the_real_magpie_is_roll_free_and_keeps_the_mask(hue) -> None:
    """Every answer roll-free; its `when` reads the ending, never the role
    (which is what exempts it from `once`); no candidate named, no Magpie
    sexed (the narrator names the Magpie from the unmasked GM line, never
    from this card)."""
    import json

    card = next(c for c in _fair_deck().cards if c.id == F3)
    assert card.once is False
    assert card.when == {"ending": {"eligible": "cleared"}}
    assert "menu" in card.tags and all(_roll_free(b) for b in card.beats)
    text = json.dumps([card.title, card.text, card.beats]).lower()
    assert not any(word in text for word in _CANDIDATE_WORDS)
    locks = [e for b in card.beats for e in ((b.get("gate") or {}).get("on_pass") or {})
             .get("effects", []) if e.get("type") == "ending_lock"]
    assert locks == [{"type": "ending_lock", "ending": "cleared"}]


# -- A Lantern's door: D3 at the front desk -----------------------------------


def _badge_ready(seed: int = 11, hour: int = 9):
    state = _at_the_desk(seed, hour=hour)
    _unmask(state)
    _lamps_kept(state)
    return state


def test_the_badge_is_offered_at_the_desk_only_when_it_is_earned(hue) -> None:
    """Dealt at the front desk while Captain Ardane is in, free, and only to a
    thief the ending would take; the same visit without the standing, or at
    an hour she is out, deals nothing."""
    assert _desk_hand(_badge_ready()) == [BADGE_CARD]
    assert _desk_hand(_badge_ready(hour=15)) == []   # the captain is out

    short = _at_the_desk(11)
    _unmask(short)
    _lamps_kept(short, LANTERN_STANDING - 1)
    assert _desk_hand(short) == []


def test_the_badge_kept_back_is_offered_again(hue) -> None:
    from engine.game import endings

    state = _badge_ready()
    assert _desk_hand(state) == [BADGE_CARD]
    _answer_hand(state, {BADGE_CARD: "not_yet"})
    assert endings.locked(state) == endings.NONE_ID
    assert _walk_out_and_back(state) == [BADGE_CARD]


def test_the_badge_keeps_the_mask(hue) -> None:
    import json

    card = next(c for c in _desk_deck().cards if c.id == BADGE_CARD)
    text = json.dumps([card.title, card.text, card.beats]).lower()
    assert not any(word in text for word in _CANDIDATE_WORDS)
    assert "agenda_role" not in json.dumps(card.when)
    locks = [e for b in card.beats for e in ((b.get("gate") or {}).get("on_pass") or {})
             .get("effects", []) if e.get("type") == "ending_lock"]
    # The badge, or (round 2) just your name cleared.
    assert locks == [{"type": "ending_lock", "ending": "a_lantern"},
                     {"type": "ending_lock", "ending": "cleared"}]


# -- T5 fix round 1 --------------------------------------------------------------


def _magpie_robs(state, jurisdiction: str = "quay", times: int = 3) -> None:
    """What the Magpie's agenda files when it robs a house: a report against
    the Magpie's mask, stamped with the agenda and the hour (agendas._try_move)."""
    from engine.game.effects import apply_effect

    for n in range(times):
        assert apply_effect(state, {"type": "report", "deed": "burglary", "guise": "magpie",
                                    "jurisdiction": jurisdiction, "precision": 1.0,
                                    "agenda": "the_magpie",
                                    "hour": int(state.world_clock_hours) + n})["ok"]


def test_wanted_own_leaves_out_what_the_world_pinned_on_you(hue) -> None:
    """`wanted {own: true}`: the Magpie's robberies, filed by its agenda on a
    mask the Watch links to your face, do not count; with `own` absent they
    do, exactly as before."""
    from engine.game.quests import evaluate_condition
    from engine.world import law

    state = _city(11)
    assert _linked(state)
    _magpie_robs(state)
    everything = {"wanted": {"guise": "self", "jurisdiction": "quay", "min": "sought"}}
    own = {"wanted": {"guise": "self", "jurisdiction": "quay", "min": "sought", "own": True}}
    assert evaluate_condition(state, everything)
    assert not evaluate_condition(state, own)
    assert law.wanted_band(state, "self", "quay", own=True) == "unknown"
    assert law.wanted_band(state, "self", "quay") == law.wanted_band(state, "self", "quay",
                                                                      own=False)


def test_wanted_own_still_counts_your_deeds_under_any_linked_face(hue) -> None:
    """Your own deeds count wherever they were filed: your face, or the
    Magpie's mask (the heart lifted at the fair is filed as the Magpie's while
    the Watch links you) -- nothing but the agenda's stamp is left out."""
    from engine.game.effects import apply_effect
    from engine.game.quests import evaluate_condition

    state = _city(11)
    apply_effect(state, {"type": "report", "deed": "sacrilege", "guise": "magpie",
                         "jurisdiction": "rise", "precision": 1.0})
    assert evaluate_condition(state, {"wanted": {"guise": "self", "jurisdiction": "rise",
                                                 "min": "sought", "own": True}})
    mine = _city(11)
    _sought_on_the_quay(mine)
    assert evaluate_condition(mine, {"wanted": {"guise": "self", "jurisdiction": "quay",
                                                "min": "sought", "own": True}})


def test_the_magpies_robberies_do_not_keep_an_honest_thief_off_the_barge(hue) -> None:
    """Owner's decision: Honest After All counts only your own deeds."""
    from engine.world import law

    state = _honest_ready()
    for jurisdiction in ("quay", "wick", "rise"):
        _magpie_robs(state, jurisdiction)
        assert law.wanted_band(state, "self", jurisdiction) in ("sought", "wanted", "hunted")
    assert _eligible(state, "honest_after_all")
    _barge_at_dusk(state)
    from engine.game.quests import QuestEngine, load_quests

    assert not QuestEngine.stage_refusal(state, load_quests()["the_evening_barge"]["stages"][0])


@pytest.mark.parametrize("clause, words", [
    ({"guise": "self", "jurisdiction": "quay", "min": "sought", "own": "yes"},
     "`wanted.own` must be true or false"),
    ({"guise": "self", "jurisdiction": "quay", "min": "sougth"}, "is not a wanted band"),
    ({"guise": "selfe", "jurisdiction": "quay", "min": "sought"}, "`wanted.guise`"),
])
def test_a_wanted_condition_the_law_cannot_read_is_an_error(hue, tmp_path, clause, words) -> None:
    """Any `wanted` condition in a story file, not only an agenda's gate."""
    import shutil
    from pathlib import Path

    import yaml

    from engine.games import validation

    manifest = registry.get("hue-and-cry")
    root = Path(__file__).resolve().parents[1]
    quests = tmp_path / "quests"
    shutil.copytree(root / manifest.paths["quests"], quests)
    barge = quests / "the_way_out" / "the_evening_barge.yaml"
    doc = yaml.safe_load(barge.read_text(encoding="utf-8"))
    doc["stages"][0]["refusals"][0]["when"] = {"wanted": clause}
    barge.write_text(yaml.safe_dump(doc), encoding="utf-8")
    patched = type(manifest)(**{**manifest.__dict__,
                                "paths": {**manifest.paths, "quests": str(quests)}})
    issues = [f"{i.source}|{i.ref_id}|{i.message}"
              for i in validation.errors_only(validation.validate_story(patched))]
    assert [i for i in issues if words in i and "the_evening_barge" in i], issues


@pytest.mark.parametrize("row, words", [
    ({"type": "flag", "flag": HONEST_WAGE, "degrees": ["sucess"]}, "'sucess'"),
    ({"type": "flagg", "flag": HONEST_WAGE}, "unknown effect type 'flagg'"),
    ({"type": "flag", "name_of": HONEST_WAGE}, "names no `flag`"),
])
def test_a_postings_effects_are_checked(hue, tmp_path, row, words) -> None:
    """Minor (T5 review): a labour row's kind, its fields, and its `degrees`
    against the job's own `pay` table."""
    import shutil
    from pathlib import Path

    import yaml

    from engine.games import validation

    manifest = registry.get("hue-and-cry")
    root = Path(__file__).resolve().parents[1]
    tables = tmp_path / "tables"
    shutil.copytree(root / manifest.paths["tables"], tables)
    doc = yaml.safe_load((tables / "labour.yaml").read_text(encoding="utf-8"))
    doc["jobs"][0]["effects"] = doc["jobs"][0]["effects"] + [row]
    (tables / "labour.yaml").write_text(yaml.safe_dump(doc), encoding="utf-8")
    patched = type(manifest)(**{**manifest.__dict__,
                                "paths": {**manifest.paths, "tables": str(tables)}})
    issues = [f"{i.source}|{i.ref_id}|{i.message}"
              for i in validation.errors_only(validation.validate_story(patched))]
    assert [i for i in issues if "labour.yaml" in i and words in i], issues


def _after_the_fair_at_the_desk(seed: int = 11, *, unmask: bool = True):
    """The morning after the fair's last day, in the Lantern House, free.
    The quests pass runs once while the fair is on, as every turn runs it:
    that is what records the fair as seen (`event_seen`)."""
    from engine.game.quests import QuestEngine

    state = _city(seed)
    _fair_on(state)
    QuestEngine.evaluate(state)
    _fed_until(state, FAIR_LAST_DAY + 1, 9)
    if unmask:
        _unmask(state)
    state.location_id = "lantern_house"
    return state


def test_cleared_after_the_fair_is_offered_at_the_desk(hue) -> None:
    """Controller's ruling: F3 exists only during the fair, so a thief who
    names the Magpie rightly after it is cleared by the captain at the desk
    (D4). Not before the fair's been, not while it is on, not unearned, and
    not while the captain is out; "not yet" offers it again."""
    from engine.game import endings
    from engine.game.clock import set_clock

    state = _after_the_fair_at_the_desk()
    assert _desk_hand(state) == ["D4_cleared_at_the_desk"]
    _answer_hand(state, {"D4_cleared_at_the_desk": "not_yet"})
    assert endings.locked(state) == endings.NONE_ID
    assert _walk_out_and_back(state) == ["D4_cleared_at_the_desk"]

    assert _desk_hand(_after_the_fair_at_the_desk(unmask=False)) == []
    out = _after_the_fair_at_the_desk()
    set_clock(out, day=out.world_day, hour=15)
    assert _desk_hand(out) == []

    during = _city(11)
    _fair_on(during)
    _unmask(during)
    during.location_id = "lantern_house"
    assert "D4_cleared_at_the_desk" not in _desk_hand(during)   # the Green's, then

    before = _at_the_desk(11)
    _unmask(before)
    assert "D4_cleared_at_the_desk" not in _desk_hand(before)


def test_cleared_after_the_fair_keeps_the_mask_and_locks_only_cleared(hue) -> None:
    import json

    card = next(c for c in _desk_deck().cards if c.id == "D4_cleared_at_the_desk")
    assert card.once is False
    text = json.dumps([card.title, card.text, card.beats]).lower()
    assert not any(word in text for word in _CANDIDATE_WORDS)
    assert "agenda_role" not in json.dumps(card.when)
    assert {"ending": {"eligible": "cleared"}} in card.when["all"]
    locks = [e for b in card.beats for e in ((b.get("gate") or {}).get("on_pass") or {})
             .get("effects", []) if e.get("type") == "ending_lock"]
    assert locks == [{"type": "ending_lock", "ending": "cleared"}]


def test_the_endings_measurement_replays(hue) -> None:
    """Rule 10: the numbers in endings.yaml and the CHANGELOGs come from a
    committed harness (`simulate_labour.py --endings`), and it replays."""
    from scripts import simulate_labour
    from scripts.simulate_law import agendas_off

    with agendas_off():
        first = simulate_labour.measure_endings("porter", 1, 3)
        second = simulate_labour.measure_endings("porter", 1, 3)
    assert first == second
    assert set(first["3"]) == {"lamps_kept", "own_record_clean", "whole_file_clean",
                               "square_with_fences", "wage_earned", "honest_after_all",
                               # endings II (v0.17 T6)
                               "hall_trusts", "silas_won"}
    assert first["3"]["wage_earned"] == 1.0
    assert simulate_labour.LAMPS_KEPT == LANTERN_STANDING


# -- T5 fix round 2 --------------------------------------------------------------


def _desk_with_both_doors(tmp_path) -> None:
    """The shipped decks with D4 gated as it was in round 1 (Cleared after
    the fair, with no word about A Lantern), so a thief who has earned both
    is dealt [D3, D4] in one hand -- the shape the review's probe found."""
    import shutil

    import yaml

    from engine.config import overlay, set_overlay

    src = _fair_deck_path().parent
    dst = tmp_path / "scenes"
    shutil.copytree(src, dst)
    path = dst / f"{DESK}.yaml"
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    d4 = next(c for c in doc["cards"] if c["id"] == "D4_cleared_at_the_desk")
    d4["when"] = {"all": [{"any": [{"hour_between": [6, 13]}, {"hour_between": [18, 23]}]},
                          {"event_seen": "hanging_fair"},
                          {"none": [{"event_active": "hanging_fair"}]},
                          {"ending": {"eligible": "cleared"}}]}
    path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    layer = overlay()
    layer.setdefault("paths", {})["decks"] = str(dst)
    set_overlay(layer)


def test_a_card_that_plays_an_ending_ends_the_hand(hue, tmp_path) -> None:
    """Controller's ruling (T5 review round 2): once a card has locked an
    ending and played its module, the story is over -- no later card in that
    hand is presented or resolved. The probe: [D3, D4] dealt together, the
    badge taken; D4 used to be presented anyway, its "cleared your name"
    prose resolved, and its ledger fact written."""
    from engine.content import director
    from engine.game import endings, epilogue

    _desk_with_both_doors(tmp_path)
    session = SessionStore().create(seed=11, llm_fn=lambda m, **k: "{}")
    state = session.engine.state
    _fed_until(state, FAIR_FIRST_DAY, 10)
    from engine.game.quests import QuestEngine

    QuestEngine.evaluate(state)
    _fed_until(state, FAIR_LAST_DAY + 1, 9)
    _unmask(state)
    _lamps_kept(state)
    state.location_id = "lantern_house"
    assert _desk_hand(state) == [BADGE_CARD, "D4_cleared_at_the_desk"]
    receipt = director.resolve(state, chosen="take_the_badge", ledger=session.ledger)
    assert receipt["ok"] and receipt["scene_complete"] is True, receipt
    assert not director.active(state)
    assert director.current_card(state) is None
    assert endings.locked(state) == "a_lantern"
    assert not any("cleared your name" in f.text for f in session.ledger.facts)
    assert epilogue.for_state(state).ending_id == "a_lantern"


@pytest.mark.parametrize("beat, ending", [("take_the_badge", "a_lantern"),
                                          ("clear_my_name", "cleared")])
def test_with_both_earned_one_card_offers_both(hue, beat, ending) -> None:
    """Controller's ruling (legibility): with A Lantern and Cleared both
    earned, the badge card is the one card dealt, and it offers both -- take
    the badge, or just have your name cleared and go. D4 stays for the
    Cleared-only case."""
    from engine.content import director
    from engine.game import endings, epilogue

    state = _after_the_fair_at_the_desk()
    _lamps_kept(state)
    assert _desk_hand(state) == [BADGE_CARD]
    assert {o["id"] for o in director.options(state)} >= {"take_the_badge", "clear_my_name"}
    assert director.resolve(state, chosen=beat)["ok"]
    assert endings.locked(state) == ending
    assert epilogue.for_state(state).ending_id == ending
    assert not director.active(state)


def test_the_badge_card_clears_a_name_before_the_fair_too(hue) -> None:
    """Both earned before the fair: the badge card's second answer is
    Cleared's door there as well, so a thief who wants no badge is not sent
    to wait for the fair."""
    from engine.content import director
    from engine.game import endings

    state = _badge_ready()
    assert _desk_hand(state) == [BADGE_CARD]
    assert director.resolve(state, chosen="clear_my_name")["ok"]
    assert endings.locked(state) == "cleared"


def test_a_door_card_is_once_unless_it_is_its_own_endings_gate(hue) -> None:
    """The fair header's rule, with the owner's exemption: every card that
    locks an ending is `once`, or every lock on it is gated on exactly the
    ending it locks -- by the card's `when:` or the beat's own gate (so
    declining never closes it, and a locked run cannot lock twice)."""
    for found in (_fair_deck(), _desk_deck(), _hall_deck()):
        for card in found.cards:
            when = card.when or {}
            for beat in card.beats:
                gate = beat.get("gate") or {}
                for branch in ("on_pass", "on_fail"):
                    for e in (gate.get(branch) or {}).get("effects") or []:
                        if e.get("type") != "ending_lock":
                            continue
                        gated = {"ending": {"eligible": e.get("ending")}}
                        own_gate = (when == gated or gated in (when.get("all") or [])
                                    or (branch == "on_pass" and gate.get("when") == gated))
                        assert card.once or own_gate, (card.id, beat["id"])


# ===========================================================================
# v0.17 Task 6 -- endings II: Partners, The Legend, Guildmaster, The Dapper's
# City; and a locked run deals no door.
# ===========================================================================


def test_a_locked_run_deals_no_door_card(hue) -> None:
    """Carried from T5's re-review: `endings.eligible` ignores an existing
    lock, so a door card gated on its own ending's eligibility could be dealt
    again after the run had ended -- the story over, and a "this ends the
    story" card on the table. A pool card whose beats carry an `ending_lock`
    is not dealt while the run is locked (`deck.eligible_cards`)."""
    from engine.content import deck
    from engine.game import endings
    from engine.game.effects import apply_effect

    state = _badge_ready()
    assert _eligible(state, "a_lantern")
    assert apply_effect(state, {"type": "ending_lock", "ending": "a_lantern"})["ok"]
    assert apply_effect(state, {"type": "ending_module"})["ok"]
    assert endings.locked(state) == "a_lantern"
    # Still "eligible" by its gate -- the lock is what ends it.
    assert _eligible(state, "a_lantern")
    eligible, rejected = deck.eligible_cards(state, _desk_deck())
    assert BADGE_CARD not in {c.id for c in eligible}
    assert rejected[BADGE_CARD] == "the run's ending is locked"
    # The desk's own `when:` still reads the gate, so the deck comes due and
    # deals nothing (spent, as any deck whose cards are all ineligible).
    from engine.content import director

    dealt = director.ensure_scene(state)
    assert all(not r["result"].get("ok") for r in dealt), dealt
    assert not director.active(state)


def test_the_validator_counts_a_collections_reward_as_the_writer(hue, tmp_path) -> None:
    """The Legend reads `magpies_hoard_complete` (the Hoard's first reader,
    v0.17 T6), which only the Magpie's Hoard's completion `effects` write
    (data/tables/collections.yaml). The two-direction flag sweep counts those
    as writers; without them the gate can never open, and it says so."""
    import shutil
    from pathlib import Path

    import yaml

    from engine.games import validation

    manifest = registry.get("hue-and-cry")
    root = Path(__file__).resolve().parents[1]
    tables = tmp_path / "tables"
    shutil.copytree(root / manifest.paths["tables"], tables)
    doc = yaml.safe_load((tables / "collections.yaml").read_text(encoding="utf-8"))
    for row in doc["collections"]:
        row["effects"] = [e for e in row["effects"] if e.get("type") != "flag"]
    (tables / "collections.yaml").write_text(yaml.safe_dump(doc), encoding="utf-8")
    patched = type(manifest)(**{**manifest.__dict__,
                                "paths": {**manifest.paths, "tables": str(tables)}})
    hoard = "magpies_hoard_complete"
    issues = [f"{i.source}|{i.ref_id}|{i.message}"
              for i in validation.errors_only(validation.validate_story(patched))]
    assert [i for i in issues if hoard in i and "never written" in i], issues
    shipped = [f"{i.source}|{i.ref_id}|{i.message}"
               for i in validation.errors_only(validation.validate_story("hue-and-cry"))]
    assert not [i for i in shipped if hoard in i], shipped


#: The four endings T6 adds (endings.yaml), each earned.
ENDINGS_II = ("partners", "the_legend", "guildmaster", "the_dappers_city")
CONFRONTATION = "the_confrontation"
HALL = "porters_hall"
#: The confrontation card for each suspect, and where and when they are found
#: (data/scenes/the_confrontation.yaml). 04:00 in the Snuffs: after Mother
#: Gannet has gone up to bed, so the long table deals nothing over it.
CONFRONT_CARD = {"npc_wren": "C1_wrens_stair", "npc_silas": "C1_silas_taproom",
                 "npc_imelda": "C1_imeldas_parlour"}
HAUNT = {"npc_wren": ("the_snuffs", 4), "npc_silas": ("the_snuffs", 4),
         "npc_imelda": ("silk_row", 10)}
#: The factions a wrong confrontation costs, per suspect.
CONFRONT_COST = {"npc_wren": "lantern_watch", "npc_silas": "honest_company",
                 "npc_imelda": "silk_row"}


def _confrontation_deck():
    from engine.content import deck

    found = deck.load_deck(CONFRONTATION)
    assert found is not None, "no confrontation deck"
    return found


def _hall_deck():
    from engine.content import deck

    found = deck.load_deck(HALL)
    assert found is not None, "no Porters' Hall deck"
    return found


def _at_the_haunt(seed: int, suspect: str, *, carried: tuple = (), day: int = 2):
    """A free thief at ``suspect``'s haunt at an hour they are there."""
    from engine.game.clock import set_clock

    state = _city(seed)
    where, hour = HAUNT[suspect]
    state.location_id = where
    set_clock(state, day=day, hour=hour)
    _carry(state, *carried)
    return state


def _hand_of(state, deck_id: str) -> list:
    """Deal what is due here; the card ids if it is ``deck_id``'s hand, or []."""
    from engine.content import director

    dealt = director.ensure_scene(state)
    if not dealt or dealt[0]["result"].get("deck_id") != deck_id:
        return []
    return list(dealt[0]["result"].get("card_ids") or [])


def _leave_and_return(state, deck_id: str, away: str = "wickmarket") -> list:
    from engine.content import director

    here = state.location_id
    state.location_id = away
    director.ensure_scene(state)
    state.location_id = here
    return _hand_of(state, deck_id)


def _partnered(seed: int = 11):
    """The real Magpie found out at their haunt and thrown in with, through
    the confrontation deck."""
    from engine.content import director
    from engine.world import agendas

    magpie = agendas.role(_city(seed), "magpie")
    state = _at_the_haunt(seed, magpie, carried=CLUES_OF[magpie][:EVIDENCE_BAR])
    card = CONFRONT_CARD[magpie]
    assert _hand_of(state, CONFRONTATION) == [card]
    assert director.resolve(state, chosen="say_it")["ok"]
    assert state.flags.get("partners_with_the_magpie") is True
    return state


def test_the_four_new_endings_are_declared_whole(hue) -> None:
    """Each: earned (a `requires`), Speak/Act/Seal, a card, the same title, a
    tease; every lock reason names a clause of its gate and every clause has
    one; and eight endings in all, the design's eight."""
    from engine.game import endings, epilogue
    from engine.games.validation import walk

    declared = endings.declared()
    cards = epilogue.declared()
    assert set(declared) == set(cards)
    assert set(declared) == {"cleared", "a_lantern", "honest_after_all", "the_rope",
                             *ENDINGS_II}
    for ending_id in ENDINGS_II:
        body = declared[ending_id]
        assert body.get("requires"), ending_id
        assert [b["id"] for b in body["beats"]] == [
            f"{ending_id}_{w}" for w in ("speak", "act", "seal")], ending_id
        for beat in body["beats"]:
            word = beat["id"].rsplit("_", 1)[1].upper()
            assert beat["text"].startswith(f"{word}."), beat["id"]
        assert cards[ending_id]["card_m"].strip() and cards[ending_id]["card_g"].strip()
        assert cards[ending_id]["title"] == body["label"], ending_id
        assert body.get("tease"), ending_id
        ids = {str(n["id"]) for n in walk([body.get("requires"), body.get("completable")])
               if n.get("id")}
        assert set(body.get("lock_reasons") or {}) == ids, (ending_id, ids)


def test_guildmasters_standing_is_the_measured_one(hue) -> None:
    """The Hall's good opinion Guildmaster asks (endings.yaml) is the number
    the harness measured against (simulate_labour.GUILD_STANDING), and the one
    these tests use."""
    from engine.game import endings
    from scripts import simulate_labour

    gate = endings.declared()["guildmaster"]["requires"]["all"]
    row = next(c for c in gate if c.get("id") == "the_hall_trusts_you")
    assert row["reputation"] == {"faction": "honest_company", "min": GUILD_STANDING}
    assert simulate_labour.GUILD_STANDING == GUILD_STANDING


# -- Partners: the confrontation, then the heart between two -----------------


def test_the_confrontation_ships_bounded_and_repeatable(hue) -> None:
    from pathlib import Path

    import yaml

    from engine.content import deck
    from engine.games.validation import validate_story

    found = _confrontation_deck()
    assert found.repeatable is True and found.required == []
    assert {c.id for c in found.pool} == set(CONFRONT_CARD.values())
    for card in found.cards:
        assert deck.MENU_TAG in card.tags, card.id
        assert any(_roll_free(b) for b in card.beats), card.id
        assert not card.once, card.id
        assert not deck.locks_an_ending(card), card.id  # a door opens elsewhere
    raw = yaml.safe_load((Path(__file__).resolve().parents[1] / registry.get(
        "hue-and-cry").paths["decks"] / f"{CONFRONTATION}.yaml").read_text(encoding="utf-8"))
    for card in raw["cards"]:
        assert len(card["text"].strip()) <= deck.MAX_TEXT, card["id"]
        for beat in card["beats"]:
            for branch in ("on_pass", "on_fail"):
                line = str(((beat.get("gate") or {}).get(branch) or {}).get("text") or "")
                assert len(line.strip()) <= deck.MAX_TEXT, (beat["id"], branch)
                assert len((((beat.get("gate") or {}).get(branch) or {}).get("effects")
                            or [])) <= 4, (beat["id"], branch)
    issues = [i for i in validate_story("hue-and-cry") if CONFRONTATION in str(i.source)]
    assert issues == [], issues


def test_card_presence_never_reads_the_role(hue) -> None:
    """Secrecy (spec §6): in the two new decks no `when:` that decides whether
    a card is dealt reads `agenda_role` -- only a beat's own gate does, when
    the player has already said the name -- and each confrontation card names
    only its own suspect."""
    import json
    from pathlib import Path

    import yaml

    root = Path(__file__).resolve().parents[1] / registry.get("hue-and-cry").paths["decks"]
    words = {"npc_wren": ("wren", "lamplighter"), "npc_silas": ("silas", "crook", "dapper"),
             "npc_imelda": ("imelda", "vessaline")}
    for deck_id in (CONFRONTATION, HALL):
        doc = yaml.safe_load((root / f"{deck_id}.yaml").read_text(encoding="utf-8"))
        assert "agenda_role" not in json.dumps(doc.get("when") or {}), deck_id
        for card in doc["cards"]:
            assert "agenda_role" not in json.dumps(card.get("when") or {}), card["id"]
    for card in _confrontation_deck().cards:
        mine = next(n for n, c in CONFRONT_CARD.items() if c == card.id)
        text = json.dumps([card.title, card.text, card.beats]).lower()
        for other, said in words.items():
            if other != mine:
                assert not any(w in text for w in said), (card.id, other)
    hall = json.dumps([[c.title, c.text, c.beats] for c in _hall_deck().cards]).lower()
    assert not any(w in hall for w in _CANDIDATE_WORDS)


@pytest.mark.parametrize("magpie", list(SUSPECTS))
def test_the_real_magpie_found_out_takes_a_partner(hue, magpie) -> None:
    """For each of the three: the clues lean to the real Magpie, the thief
    stands at the Magpie's haunt at an hour they are there, and says it. The
    Magpie takes the thief on -- and only THEN does the GM line say who it
    is. The Watch is told nothing: it still takes the thief for the Magpie."""
    from engine.content import director
    from engine.world import npc_sim

    state = _at_the_haunt(_seed_for(magpie), magpie, carried=CLUES_OF[magpie][:EVIDENCE_BAR])
    before = _gm(state).lower()
    assert not any(w in before for w in _CANDIDATE_WORDS), before
    card = CONFRONT_CARD[magpie]
    assert _hand_of(state, CONFRONTATION) == [card]
    assert director.resolve(state, chosen="say_it")["ok"]
    assert state.flags.get("partners_with_the_magpie") is True
    assert not state.flags.get("magpie_unmasked")
    assert _linked(state)  # the Watch still believes it
    assert npc_sim.display_name(magpie) in _gm(state)
    assert _eligible(state, "partners")
    # Partnered, the confrontation is never dealt again.
    assert _leave_and_return(state, CONFRONTATION) == []


def test_a_wrong_confrontation_costs_and_never_soft_locks(hue) -> None:
    """Like a wrong naming: flags that set the suspect aside, the lead spent
    (a second confrontation waits for a clue carried out since), and the
    suspect's own people hear of it. Nothing is arrested and no ending is
    closed: with a fresh clue the trail can still lead to the real Magpie."""
    from engine.content import director
    from engine.game import endings

    seed = _seed_for("npc_wren")
    state = _at_the_haunt(seed, "npc_silas", carried=CLUES_OF["npc_silas"][:EVIDENCE_BAR])
    standing = int(state.reputations.get("honest_company", 0))
    assert _hand_of(state, CONFRONTATION) == [CONFRONT_CARD["npc_silas"]]
    assert director.resolve(state, chosen="say_it")["ok"]
    assert state.flags.get("magpie_confronted_wrongly") is True
    assert state.flags.get("wrongly_confronted_silas") is True
    assert not state.flags.get("clue_fresh")
    assert not state.flags.get("partners_with_the_magpie")
    assert int(state.reputations.get("honest_company", 0)) == standing - 5
    assert "partners" not in endings.eligible(state).unreachable
    from engine.world import law

    assert not law.in_custody(state)
    # No new clue: nothing, anywhere.
    assert _leave_and_return(state, CONFRONTATION) == []
    # Three of Wren's (the lead, with Silas set aside), one carried since:
    # Wren's card at Wren's haunt; Silas's never again.
    _carry(state, *CLUES_OF["npc_wren"][:3])
    assert _leave_and_return(state, CONFRONTATION) == [CONFRONT_CARD["npc_wren"]]
    assert director.resolve(state, chosen="say_it")["ok"]
    assert state.flags.get("partners_with_the_magpie") is True


@pytest.mark.parametrize("suspect", list(SUSPECTS))
def test_each_wrong_confrontation_costs_that_suspects_people(hue, suspect) -> None:
    from engine.content import director

    right = next(n for n in SUSPECTS if n != suspect)
    state = _at_the_haunt(_seed_for(right), suspect, carried=CLUES_OF[suspect][:EVIDENCE_BAR])
    faction = CONFRONT_COST[suspect]
    before = int(state.reputations.get(faction, 0))
    assert _hand_of(state, CONFRONTATION) == [CONFRONT_CARD[suspect]]
    assert director.resolve(state, chosen="say_it")["ok"]
    assert int(state.reputations.get(faction, 0)) == before - 5
    assert state.flags.get(f"wrongly_confronted_{SUSPECTS[suspect]}") is True


def test_the_confrontation_waits_for_the_haunt_the_hour_and_the_lead(hue) -> None:
    """Dealt only where and when the favoured suspect is, on the desk's own
    evidence bar, and never after the Magpie has been named to the captain."""
    from engine.game.clock import set_clock

    seed = _seed_for("npc_imelda")
    clues = CLUES_OF["npc_imelda"][:EVIDENCE_BAR]
    assert _hand_of(_at_the_haunt(seed, "npc_imelda", carried=clues), CONFRONTATION) == [
        CONFRONT_CARD["npc_imelda"]]
    wrong_place = _at_the_haunt(seed, "npc_imelda", carried=clues)
    wrong_place.location_id = "the_snuffs"
    assert _hand_of(wrong_place, CONFRONTATION) == []
    wrong_hour = _at_the_haunt(seed, "npc_imelda", carried=clues)
    set_clock(wrong_hour, day=2, hour=14)   # at the Temple
    assert _hand_of(wrong_hour, CONFRONTATION) == []
    one_clue = _at_the_haunt(seed, "npc_imelda", carried=clues[:1])
    assert _hand_of(one_clue, CONFRONTATION) == []
    named = _at_the_haunt(seed, "npc_imelda", carried=clues)
    _unmask(named)
    assert _hand_of(named, CONFRONTATION) == []
    # A suspect named wrongly at the desk is set aside here too.
    accused = _at_the_haunt(_seed_for("npc_wren"), "npc_imelda", carried=clues)
    from engine.game.effects import apply_effect

    apply_effect(accused, {"type": "flag", "flag": "wrongly_accused_imelda"})
    assert _hand_of(accused, CONFRONTATION) == []


def test_the_heist_together_replaces_the_showing_for_a_partner(hue) -> None:
    """At the fair a partner is dealt F6 -- the heart with the Magpie -- and
    not F2, the heart alone: one Showing card, one choice. A thief with no
    partner is dealt F2 and never F6."""
    state = _partnered()
    _fair_on(state)
    state.location_id = "gallows_green"
    hand = _hand_of(state, FAIR)
    assert "F6_the_heist_together" in hand and "F2_the_showing" not in hand
    alone = _city(11)
    _fair_on(alone)
    alone.location_id = "gallows_green"
    hand = _hand_of(alone, FAIR)
    assert "F2_the_showing" in hand and "F6_the_heist_together" not in hand


def test_selling_a_partner_out_closes_partners(hue) -> None:
    """Blocked by `magpie_unmasked`: a partner who then names the Magpie to
    the captain has already given them up. Partners goes out of reach -- the
    gallery says why -- F6 is never dealt, and the heart alone is offered
    again."""
    from engine.game import endings

    state = _partnered()
    _unmask(state)
    report = endings.eligible(state)
    assert "partners" not in report.eligible and "partners" in report.unreachable
    _fair_on(state)
    state.location_id = "gallows_green"
    hand = _hand_of(state, FAIR)
    assert "F6_the_heist_together" not in hand and "F2_the_showing" in hand


def test_partners_ends_at_the_fair_and_moves_the_temple(hue) -> None:
    from engine.content import director
    from engine.game import endings, epilogue

    state = _partnered()
    _fair_on(state)
    state.location_id = "gallows_green"
    assert "F6_the_heist_together" in _hand_of(state, FAIR)
    temple = int(state.reputations.get("temple_everflame", 0))
    guard = 0
    while director.active(state) and guard < 8:
        guard += 1
        card = director.current_card(state)
        chosen = ("take_it_together" if card.id == "F6_the_heist_together"
                  else director.options(state)[0]["id"])
        assert director.resolve(state, chosen=chosen)["ok"]
    assert endings.locked(state) == "partners"
    assert epilogue.for_state(state).ending_id == "partners"
    assert int(state.reputations.get("temple_everflame", 0)) == temple - 10


# -- The Legend: the heart, and the getaway home ----------------------------


def _lifted_the_heart(monkeypatch, seed: int = 11):
    from engine.content import director
    from engine.game import inventory
    from engine.game.quests import QuestEngine

    _force(monkeypatch, "success")
    state = _city(seed)
    _fair_on(state)
    state.location_id = "gallows_green"
    director.ensure_scene(state)
    _play_the_fair(state, "lift_the_heart")
    assert inventory.quantity(state, "everflame_heart") == 1
    QuestEngine.evaluate(state)   # the turn's end: the getaway begins
    return state


def test_the_heist_starts_the_getaway_and_the_snuffs_end_it(hue, monkeypatch) -> None:
    """The lock is on the GETAWAY, not the roll (T3's ruling): the heist puts
    the heart under the thief's coat and starts the quest; the Snuffs, one
    street from the Green, end it -- The Legend, by name. The heist is the
    Temple's first mover."""
    from engine.game import endings, epilogue
    from engine.game.quests import STATUS_ACTIVE, QuestEngine, progress_records

    state = _lifted_the_heart(monkeypatch)
    assert int(state.reputations.get("temple_everflame", 0)) == -10
    assert progress_records(state)["the_heart_goes_home"].status == STATUS_ACTIVE
    assert endings.locked(state) == endings.NONE_ID
    QuestEngine.evaluate(state)   # still on the Green: not yet
    assert endings.locked(state) == endings.NONE_ID
    state.location_id = "the_snuffs"
    QuestEngine.evaluate(state)
    assert endings.locked(state) == "the_legend"
    assert epilogue.for_state(state).ending_id == "the_legend"


def test_a_thief_taken_with_the_heart_is_no_legend(hue, monkeypatch) -> None:
    """Taken before the Snuffs, the Watch has the heart back (hot for good),
    the getaway fails, and nothing is locked."""
    from engine.game import endings, inventory
    from engine.game.quests import STATUS_FAILED, QuestEngine, progress_records

    state = _lifted_the_heart(monkeypatch)
    _arrest_on(state, "pickpocket", where="gallows_green")
    assert inventory.quantity(state, "everflame_heart") == 0
    QuestEngine.evaluate(state)
    assert progress_records(state)["the_heart_goes_home"].status == STATUS_FAILED
    assert endings.locked(state) == endings.NONE_ID
    assert not _eligible(state, "the_legend")


@pytest.mark.parametrize("hoard", [True, False])
def test_the_legend_reads_the_magpies_hoard(hue, hoard) -> None:
    """The Hoard's first reader (v0.15's promise): carried whole, it raises
    The Legend's closeness and its Seal says so; without it, the Seal keeps
    the secret."""
    from engine.game import endings
    from engine.game.effects import apply_effect

    state = _city(11)
    apply_effect(state, {"type": "item", "item_id": "everflame_heart",
                         "name": "The Everflame's Heart"})
    base = endings.eligible(state).scores["the_legend"]
    if hoard:
        apply_effect(state, {"type": "flag", "flag": "magpies_hoard_complete"})
        assert endings.eligible(state).scores["the_legend"] > base
    assert apply_effect(state, {"type": "ending_lock", "ending": "the_legend"})["ok"]
    played = apply_effect(state, {"type": "ending_module"})
    seal = next(r for r in played["results"] if r["beat_id"] == "the_legend_seal")
    assert ("It fits." in seal["text"]) is hoard


# -- Guildmaster -------------------------------------------------------------


def _guild_ready(state=None, *, standing: int = GUILD_STANDING, lever: str = "secret"):
    """Sworn, the Hall's good opinion at ``standing``, and Gannet's measure
    taken by ``lever``; at the long table at eight in the evening."""
    from engine.game import threads
    from engine.game.clock import set_clock
    from engine.game.effects import apply_effect
    from engine.world import jobs, premises

    from engine.game.quests import QuestEngine

    # T8 fix round 1: the needles wait for the Hanging Fair. Midnight of its
    # first day -- the fair raised by the calendar, the quests pass run -- is
    # inside the long table's hours. Seed 2: Silas's rise never fills on its
    # own by then (on seed 11 it does, on day 7).
    state = state or _city(2)
    if (state.world_day, state.world_hour) < (FAIR_FIRST_DAY, 0):
        _fed_until(state, FAIR_FIRST_DAY, 0)
    QuestEngine.evaluate(state)
    apply_effect(state, {"type": "flag", "flag": "guild_initiated"})
    now = int(state.reputations.get("honest_company", 0))
    apply_effect(state, {"type": "reputation", "faction": "honest_company",
                         "delta": standing - now})
    state.location_id = "the_snuffs"
    if lever == "secret":
        apply_effect(state, {"type": "flag",
                             "flag": f"{jobs.SECRET_HELD_PREFIX}prem_gannets_house:fund_of_ious"})
    elif lever == "blessing":
        thread_id = threads.seal(state, threads.offer(state, "gannet_silk_row"))["thread"]["id"]
        # The Row robbed by a finished job (jobs.robbed): the contract's own
        # discharge gate, which the jobs tests walk end to end.
        state.jobs.setdefault("robbed", []).append(premises.at(state, "silk_row")[0]["id"])
        assert threads.discharge(state, thread_id)["ok"]
        now = int(state.reputations.get("honest_company", 0))
        apply_effect(state, {"type": "reputation", "faction": "honest_company",
                             "delta": standing - now})
    return state


@pytest.mark.parametrize("lever", ["secret", "blessing"])
def test_guildmaster_asks_the_oath_the_hall_and_gannets_measure(hue, lever) -> None:
    from engine.game.effects import apply_effect

    assert _eligible(_guild_ready(lever=lever), "guildmaster")
    assert not _eligible(_guild_ready(standing=GUILD_STANDING - 1, lever=lever), "guildmaster")
    assert not _eligible(_guild_ready(lever="none"), "guildmaster")
    unsworn = _guild_ready(lever=lever)
    apply_effect(unsworn, {"type": "flag", "flag": "guild_initiated", "value": False})
    assert not _eligible(unsworn, "guildmaster")
    holding = _guild_ready(lever=lever)
    apply_effect(holding, {"type": "item", "item_id": "everflame_heart",
                           "name": "The Everflame's Heart"})
    assert not _eligible(holding, "guildmaster")


def test_the_long_table_deals_guildmaster_only_while_earned(hue) -> None:
    """Dealt at the long table in Gannet's hours to a thief the ending would
    take; kept back, it is offered again on the next visit; unearned, or at
    an hour she is not holding court, nothing is dealt."""
    from engine.content import director
    from engine.game import endings
    from engine.game.clock import set_clock

    assert _hand_of(_guild_ready(), HALL) == ["P1_the_needles"]
    short = _guild_ready(standing=GUILD_STANDING - 1)
    assert _hand_of(short, HALL) == []
    noon = _guild_ready()
    set_clock(noon, day=FAIR_FIRST_DAY, hour=12)
    assert _hand_of(noon, HALL) == []
    state = _guild_ready()
    assert _hand_of(state, HALL) == ["P1_the_needles"]
    assert director.resolve(state, chosen="not_yet")["ok"]
    assert endings.locked(state) == endings.NONE_ID
    assert _leave_and_return(state, HALL) == ["P1_the_needles"]
    assert director.resolve(state, chosen="take_the_chair")["ok"]
    assert endings.locked(state) == "guildmaster"
    assert not director.active(state)


def test_silas_winning_shuts_guildmaster_until_he_is_stood_against(hue, monkeypatch) -> None:
    """Silas's rise complete, Guildmaster is out of reach (the gallery says
    why). Stood against at the fair and beaten, Silas is stopped: the Company
    warms to the thief, Guildmaster opens again, and The Dapper's City shuts."""
    from engine.game import endings

    _force(monkeypatch, "success")
    state = _guild_ready()
    _silas_splits(state)
    assert "guildmaster" in endings.eligible(state).unreachable
    assert _eligible(state, "the_dappers_city")
    _fair_on(state)
    state.location_id = "gallows_green"
    assert "F4_silas_makes_his_move" in _hand_of(state, FAIR)
    standing = int(state.reputations.get("honest_company", 0))
    _answer_the_fair(state, {"F4_silas_makes_his_move": "stand_against_him"})
    assert state.flags.get("silas_stopped") is True
    assert endings.locked(state) == endings.NONE_ID
    assert int(state.reputations.get("honest_company", 0)) == standing + 5
    report = endings.eligible(state)
    assert "guildmaster" not in report.unreachable
    assert "the_dappers_city" in report.unreachable
    # Walked off the Green and back: F4 is not offered again.
    assert "F4_silas_makes_his_move" not in _leave_and_return(state, FAIR)


def test_a_stopped_silas_stops_working_the_company(hue) -> None:
    """Silas's two moves (agendas.yaml) wait on `silas_stopped`: the same seed
    walked the same days robs the Company's ward only while he is not."""
    from engine.game.effects import apply_effect

    def silas_hits(stopped: bool) -> int:
        state = _city(11)
        if stopped:
            apply_effect(state, {"type": "flag", "flag": "silas_stopped"})
        _fed_until(state, 9, 12)
        return sum(1 for h in state.agendas.get("hits") or []
                   if h.get("agenda") == "silas_ambition")

    assert silas_hits(False) > 0
    assert silas_hits(True) == 0


# -- The Dapper's City -------------------------------------------------------


def _silas_splits(state) -> None:
    from engine.game import clocks

    clocks.advance(state, "silas_rise", 5, why="test: the Company split")
    clocks.resolve(state)
    assert state.flags.get("silas_splits_the_company") is True


def _answer_the_fair(state, picks: dict) -> None:
    from engine.content import director

    guard = 0
    while director.active(state) and guard < 8:
        guard += 1
        card = director.current_card(state)
        chosen = picks.get(card.id) or director.options(state)[0]["id"]
        assert director.resolve(state, chosen=chosen)["ok"], card.id


@pytest.mark.parametrize("beat, degree", [("stand_with_him", "success"),
                                          ("stand_against_him", "failure")])
def test_standing_with_silas_or_losing_to_him_is_the_dappers_city(
        hue, monkeypatch, beat, degree) -> None:
    """Bittersweet by design: stood with him, or failed to stop him."""
    from engine.game import endings, epilogue

    _force(monkeypatch, degree)
    state = _city(11)
    from engine.game.effects import apply_effect

    apply_effect(state, {"type": "flag", "flag": "guild_initiated"})
    _silas_splits(state)
    _fair_on(state)
    state.location_id = "gallows_green"
    assert "F4_silas_makes_his_move" in _hand_of(state, FAIR)
    _answer_the_fair(state, {"F4_silas_makes_his_move": beat})
    assert endings.locked(state) == "the_dappers_city"
    assert epilogue.for_state(state).ending_id == "the_dappers_city"


@pytest.mark.parametrize("closer", ["magpie_unmasked", "partners_with_the_magpie"])
def test_the_dappers_city_is_no_place_for_an_informer_or_a_partner(hue, closer) -> None:
    from engine.game import endings
    from engine.game.effects import apply_effect

    state = _city(11)
    apply_effect(state, {"type": "flag", "flag": "guild_initiated"})
    _silas_splits(state)
    assert _eligible(state, "the_dappers_city")
    apply_effect(state, {"type": "flag", "flag": closer})
    assert "the_dappers_city" in endings.eligible(state).unreachable


# -- No hand holds two doors -------------------------------------------------


def test_no_hand_can_hold_two_doors(hue) -> None:
    """The ruling: no hand may deal two doors that could both lock. Over every
    combination of the facts the doors read, at most one door card of each
    deck has its own `when:` holding at once (the badge card is one card that
    offers two). And the Legend's getaway, the one door that is not a card,
    ends in the Snuffs, where the only door -- the long table -- is never
    open to a thief holding the heart."""
    import copy
    import itertools

    from engine.content import deck
    from engine.game.effects import apply_effect
    from engine.game.quests import evaluate_condition

    facts = ("magpie_unmasked", "partners_with_the_magpie", "guild_initiated",
             "silas_splits_the_company", "silas_stopped", "heart", "lamps", "hall")
    decks = [_fair_deck(), _desk_deck(), _hall_deck(), _confrontation_deck()]
    doors = {d.id: [c for c in d.cards if deck.locks_an_ending(c)] for d in decks}
    assert {c.id for c in doors[FAIR]} == {"F3_the_real_magpie", "F4_silas_makes_his_move",
                                           "F6_the_heist_together"}
    assert doors[CONFRONTATION] == []
    base = _city(11)
    apply_effect(base, {"type": "flag",
                        "flag": "secret_held:prem_gannets_house:fund_of_ious"})
    checked = 0
    for bits in itertools.product((False, True), repeat=len(facts)):
        state = copy.deepcopy(base)
        on = dict(zip(facts, bits))
        for flag in facts[:5]:
            if on[flag]:
                apply_effect(state, {"type": "flag", "flag": flag})
        if on["heart"]:
            apply_effect(state, {"type": "item", "item_id": "everflame_heart",
                                 "name": "The Everflame's Heart"})
        if on["lamps"]:
            _lamps_kept(state)
        if on["hall"]:
            apply_effect(state, {"type": "reputation", "faction": "honest_company",
                                 "delta": GUILD_STANDING})
        for deck_id, cards in doors.items():
            open_doors = [c.id for c in cards if evaluate_condition(state, c.when)]
            assert len(open_doors) <= 1, (on, deck_id, open_doors)
        if on["heart"]:
            assert not _eligible(state, "guildmaster"), on
        checked += 1
    assert checked == 2 ** len(facts)


# -- The fair's door ids, built and released ---------------------------------


def test_the_fair_builds_f4_and_f6_and_releases_f5(hue) -> None:
    """T3 reserved F4-F6 for T6. F4 (the Dapper's City) and F6 (Partners) are
    built, F5 was released unbuilt -- Guildmaster's door is the Porters' Hall,
    reachable before the fair -- and the header says so."""
    from pathlib import Path

    header = "\n".join(
        line for line in (Path(__file__).resolve().parents[1] / "games" / "hue-and-cry"
                          / "data" / "scenes" / f"{FAIR}.yaml")
        .read_text(encoding="utf-8").splitlines() if line.startswith("#"))
    ids = {c.id for c in _fair_deck().cards}
    assert {"F4_silas_makes_his_move", "F6_the_heist_together"} <= ids
    assert "F5_gannets_stake" not in ids
    assert "RELEASED  F5_gannets_stake" in header
    assert "RESERVED" not in header


def test_an_unmasked_thief_with_the_heart_is_not_honest_after_all(hue) -> None:
    """T6 review round 1. After a right naming the heist's `sacrilege` lands
    on the Magpie's file alone, so the thief's own record reads clean --
    and the barge would have taken a relic aboard as Honest After All. The
    heart in the pack shuts it (`empty_handed`), whatever the file says --
    and, since T8 fix round 1, so does the hand that took it (`never_stole`)."""
    from engine.game import endings
    from engine.world import law

    state = _honest_ready()
    _unmasked_with_the_heart(state)
    assert all(law.wanted_band(state, "self", j, own=True) in ("unknown", "noticed")
               for j in ("quay", "wick", "rise"))
    assert not _eligible(state, "honest_after_all")
    reasons = endings.declared()["honest_after_all"]["lock_reasons"]
    assert endings.eligible(state).locked["honest_after_all"] == [
        reasons["never_stole"], reasons["empty_handed"]]


def test_the_desk_honours_a_wrong_confrontation(hue) -> None:
    """T6 review round 1. A suspect confronted wrongly is not the Magpie, and
    the thief knows it: the front desk sets them aside as the confrontation
    does, and its second-try bar reads a wrong confrontation as it reads a
    wrong naming -- the lead is spent until a clue is carried out since. So
    the right suspect surfaces at the desk without a false naming first."""
    from engine.content import director

    state = _at_the_haunt(_seed_for("npc_wren"), "npc_silas",
                          carried=CLUES_OF["npc_silas"][:EVIDENCE_BAR])
    assert _hand_of(state, CONFRONTATION) == [CONFRONT_CARD["npc_silas"]]
    assert director.resolve(state, chosen="say_it")["ok"]
    assert state.flags.get("wrongly_confronted_silas") is True
    # At the desk in the captain's hours: the lead is spent -- nothing.
    state.location_id = "lantern_house"
    from engine.game.clock import set_clock

    set_clock(state, day=3, hour=9)
    assert _desk_hand(state) == []
    # One of Wren's carried out since: with Silas set aside, Wren leads.
    _carry(state, CLUES_OF["npc_wren"][0])
    assert _walk_out_and_back(state) == ["D2_name_wren"]


def test_a_wrong_confrontation_spends_the_lead_at_the_desk(hue) -> None:
    """The desk's second-try bar reads a wrong confrontation as it reads a
    wrong naming: with the next suspect already leading once the wrong one is
    set aside, the captain still hears nothing until a clue is carried out
    since."""
    from engine.content import director
    from engine.game.clock import set_clock

    state = _at_the_haunt(_seed_for("npc_wren"), "npc_silas",
                          carried=(*CLUES_OF["npc_silas"][:EVIDENCE_BAR],
                                   CLUES_OF["npc_wren"][0]))
    assert _hand_of(state, CONFRONTATION) == [CONFRONT_CARD["npc_silas"]]
    assert director.resolve(state, chosen="say_it")["ok"]
    state.location_id = "lantern_house"
    set_clock(state, day=3, hour=9)
    assert _desk_hand(state) == []          # Wren leads, but the lead is spent
    _carry(state, CLUES_OF["npc_wren"][1])
    assert _walk_out_and_back(state) == ["D2_name_wren"]


# ---------------------------------------------------------------------------
# v0.17 Task 7: all eight, held
# ---------------------------------------------------------------------------


def test_a_wrong_naming_spends_the_lead_at_the_confrontation(hue) -> None:
    """T6 re-review, carried: the confrontation's second-try bar mirrors the
    desk's. A wrong NAMING at the desk spends the lead at the suspect's door
    too -- with the next suspect already leading once the wrong one is set
    aside, nobody's door deals until a clue is carried out since."""
    from engine.game.clock import set_clock

    state = _at_the_desk(_seed_for("npc_wren"),
                         carried=(*CLUES_OF["npc_silas"][:EVIDENCE_BAR],
                                  CLUES_OF["npc_wren"][0]))
    assert _desk_hand(state) == ["D2_name_silas"]
    _answer_hand(state, {"D2_name_silas": "name_them"})
    assert state.flags.get("magpie_named_wrongly") is True
    assert not state.flags.get("clue_fresh")
    where, hour = HAUNT["npc_wren"]
    state.location_id = where
    set_clock(state, day=3, hour=hour)
    assert _hand_of(state, CONFRONTATION) == []   # Wren leads; the lead is spent
    _carry(state, CLUES_OF["npc_wren"][1])
    state.location_id = "wickmarket"
    _hand_of(state, CONFRONTATION)
    state.location_id = where
    assert _hand_of(state, CONFRONTATION) == [CONFRONT_CARD["npc_wren"]]


# -- the eight, whole: one set of ids, three beats each, every beat resolves --

#: The design's eight (spec §8), by class id.
EIGHT = ("cleared", "a_lantern", "honest_after_all", "partners", "the_legend",
         "guildmaster", "the_dappers_city", "the_rope")


def test_endings_epilogue_index_and_cards_are_one_set_of_ids(hue) -> None:
    """The Garden's same-set check (test_wicked_garden_scenes.py), read from
    the three files raw: endings.yaml's classes, the epilogue index's ids and
    classes, and the prose file's card keys are the same eight, and each
    index row's title is its ending's label."""
    from engine.game import endings, epilogue

    classes = set((endings.load_rules().get("classes") or {}))
    index = epilogue.load_index()["endings"]
    cards = set(epilogue.load_cards())
    assert classes == set(EIGHT)
    assert {row["id"] for row in index} == classes
    assert {row["class"] for row in index} == classes
    assert all(row["id"] == row["class"] for row in index)
    assert len(index) == len(classes)
    assert cards == classes
    assert set(endings.declared()) == classes
    labels = {e: body["label"] for e, body in endings.declared().items()}
    assert {row["id"]: row["title"] for row in index} == labels


def test_every_one_of_the_eight_has_speak_act_and_seal(hue) -> None:
    """Read from the raw table: three beats, `<id>_speak`, `_act`, `_seal`,
    in that order, each opening with its own word."""
    from engine.game import endings

    classes = endings.load_rules()["classes"]
    for ending_id in EIGHT:
        beats = classes[ending_id]["beats"]
        assert [b["id"] for b in beats] == [
            f"{ending_id}_{w}" for w in ("speak", "act", "seal")], ending_id
        for beat in beats:
            word = beat["id"].rsplit("_", 1)[1].upper()
            assert beat["text"].startswith(f"{word}."), beat["id"]


@pytest.mark.parametrize("hoard", [False, True])
def test_every_ending_beat_resolves_through_the_deck_engine(hue, hoard) -> None:
    """Each of the 24 beats is an ordinary beat in the shared grammar: bounded
    as the module bounds it (`endings.module_beats`), it resolves without
    raising, says something, and carries no effect the dispatcher does not
    know. Both branches of a gated beat (the Legend's Seal reads the Hoard)."""
    from engine.content import deck
    from engine.game import endings
    from engine.game.effects import apply_effect

    for ending_id in EIGHT:
        state = _city(11)
        if hoard:
            apply_effect(state, {"type": "flag", "flag": "magpies_hoard_complete"})
        beats = endings.module_beats(ending_id)
        assert len(beats) == 3, ending_id
        for beat in beats:
            result = deck.resolve_beat(state, beat, by="test")
            assert result.beat_id == beat["id"], ending_id
            assert str(result.text).strip(), beat["id"]
            for receipt in result.effects:
                assert not str(receipt.get("type", "")).startswith("unknown"), (
                    beat["id"], receipt)
                assert receipt.get("ok", True), (beat["id"], receipt)


# -- resolve() never picks an unearned ending ---------------------------------


def _held(state) -> None:
    from engine.game.effects import apply_effect

    apply_effect(state, {"type": "report", "deed": "pickpocket", "guise": "self",
                         "jurisdiction": "wick", "precision": 1.0})
    assert apply_effect(state, {"type": "arrest"})["ok"]


def _the_heart(state) -> None:
    """F2 `lift_the_heart`'s own on_pass effects (not the ledger fact)."""
    from engine.content import deck
    from engine.game.effects import apply_effect

    card = next(c for c in deck.load_deck("fair_day").cards if c.id == "F2_the_showing")
    beat = next(b for b in card.beats if b["id"] == "lift_the_heart")
    for effect in beat["gate"]["on_pass"]["effects"]:
        if effect["type"] != "ledger_fact":
            assert apply_effect(state, effect)["ok"], effect


def _fact(flag: str):
    def write(state) -> None:
        from engine.game.effects import apply_effect

        assert apply_effect(state, {"type": "flag", "flag": flag})["ok"]
    return write


def _standing(faction: str, value: int):
    """The faction's good opinion brought up to ``value`` (T8 fix round 1: a
    walked calendar can have moved it -- Silas robs the Company's ward)."""
    def write(state) -> None:
        from engine.game.effects import apply_effect

        now = int(state.reputations.get(faction, 0))
        apply_effect(state, {"type": "reputation", "faction": faction,
                             "delta": max(0, value - now)})
    return write


#: Every fact the eight gates read, each written the way play writes it.
_GATE_FACTS = {
    "unmasked": _unmask,
    "partnered": _fact("partners_with_the_magpie"),
    "named_wrongly": _fact("magpie_named_wrongly"),
    "sworn": _fact("guild_initiated"),
    "silas_won": _fact("silas_splits_the_company"),
    "silas_stopped": _fact("silas_stopped"),
    "wage": _fact(HONEST_WAGE),
    "welshed": _fact("welshed_on_pell"),
    "lamps": _standing("lantern_watch", LANTERN_STANDING),
    "hall": _standing("honest_company", GUILD_STANDING),
    "lever": _fact("secret_held:prem_gannets_house:fund_of_ious"),
    "heart": _the_heart,
    "held": _held,
    "sought": lambda s: _file(s, "self", 6),
    # T8 fix round 1: a purse lifted where nobody saw.
    "stole": lambda s: _a_purse_nobody_saw(s),
    # T8 fix round 1: the Hanging Fair come and gone -- the calendar walked
    # through it, the quests pass run during it. First in any list that
    # writes a standing (the walk's days can move one). The property test
    # below reads it by starting from a walked base instead (``_base``).
    "fair": lambda s: _the_fair_come_and_gone(s),
}


def _the_fair_come_and_gone(state) -> None:
    from engine.game.quests import QuestEngine

    _fed_until(state, FAIR_FIRST_DAY, 10)
    QuestEngine.evaluate(state)
    _fed_until(state, FAIR_LAST_DAY + 1, 10)


#: What each earned ending cannot be had without, and what it cannot be had
#: with, in terms of the facts above -- written from the design (the endings
#: table in the spec, endings.yaml's header), NOT read off the gates, so a
#: gate that drifts from its ending's promise disagrees with it (T8: this
#: replaces T7's `_independently_earned`, which asked the gate itself and so
#: agreed with `endings.eligible` by construction). Only facts whose effect
#: does not depend on their order: the heart and a stay in the cells meet
#: in one order and not the other, so neither forbids the other here.
_NEEDS = {
    "cleared": {"unmasked"},
    "a_lantern": {"unmasked", "lamps"},
    "honest_after_all": {"wage"},
    "partners": {"partnered"},
    "the_legend": {"heart"},
    "guildmaster": {"sworn", "hall", "lever", "fair"},
    "the_dappers_city": {"silas_won", "sworn"},
}
_FORBIDS = {
    # The partner who sold the Magpie to the captain.
    "partners": {"unmasked"},
    # Nobody walks home with the heart from a cell.
    "the_legend": {"held"},
    # A face the Watch is looking for, a welsh on a fence, or any theft,
    # seen or unseen (a hand on the heart included: T8 fix round 1).
    "honest_after_all": {"sought", "welshed", "stole", "heart"},
    # Silas stopped, a name taken to the captain, the Magpie's partner.
    "the_dappers_city": {"silas_stopped", "unmasked", "partnered"},
}


def _facts_allow(ending_id: str, facts: set[str]) -> bool:
    """Whether the facts applied could have earned ``ending_id`` at all."""
    if ending_id == "the_rope":
        return True
    if not _NEEDS[ending_id] <= facts or _FORBIDS.get(ending_id, set()) & facts:
        return False
    # Guildmaster shuts while Silas has WON: risen and not stopped.
    return not (ending_id == "guildmaster" and "silas_won" in facts
                and "silas_stopped" not in facts)


def test_resolve_never_picks_an_unearned_ending(hue) -> None:
    """Property-style, over seeds and combinations of every fact the gates
    read (a seeded sample: the same 3 x 40 states every run), with an ending
    sworn while it was eligible and then, often, a fact that breaks it:
    `endings.resolve` answers an ending the facts could have earned
    (``_facts_allow``, written from the design, not the gates), or The Rope;
    never one the thief did not earn. Every ending the report calls eligible
    passes the same check; `lock` refuses every ending the report does not
    call eligible, and accepts what resolve chose."""
    import copy
    import random

    from engine.game import endings
    from engine.game.effects import apply_effect

    names = sorted(n for n in _GATE_FACTS if n != "fair")
    picker = random.Random(20260928)   # the test's own sample, not the game's rng
    seen: set[str] = set()
    broken_oaths = 0
    bases: dict = {}

    def _base(seed: int, fair: bool):
        # One walk per seed, copied for every sample (T8 fix round 1). The
        # seeds are ones where Silas's rise never fills on its own by then,
        # so `silas_won` is only ever the fact applied.
        if (seed, fair) not in bases:
            state = _city(seed)
            if fair:
                _the_fair_come_and_gone(state)
            bases[(seed, fair)] = state
        return copy.deepcopy(bases[(seed, fair)])

    for seed in (2, 3, 5):
        for _ in range(40):
            chosen = [n for n in names if picker.random() < 0.35]
            picker.shuffle(chosen)
            fair = picker.random() < 0.5
            state = _base(seed, fair)
            if fair:
                chosen.insert(0, "fair")   # already applied: the base walked it
            cut = picker.randrange(len(chosen) + 1)
            for name in chosen[:cut]:
                if name != "fair":
                    _GATE_FACTS[name](state)
            earned = [e for e in endings.eligible(state).eligible if e != "the_rope"]
            sworn = ""
            if earned:
                sworn = picker.choice(earned)
                assert apply_effect(state, {"type": "ending_intent", "ending": sworn})["ok"]
            for name in chosen[cut:]:
                if name != "fair":
                    _GATE_FACTS[name](state)

            report = endings.eligible(state)
            picked = endings.resolve(state)
            broken_oaths += bool(sworn) and sworn not in report.eligible
            assert picked in report.eligible, (seed, chosen, picked)
            assert _facts_allow(picked, set(chosen)), (seed, chosen, picked)
            for ending_id in EIGHT:
                if ending_id in report.eligible:
                    assert _facts_allow(ending_id, set(chosen)), (seed, chosen, ending_id)
                else:
                    assert not endings.lock(state, ending_id)["ok"], (seed, chosen, ending_id)
            assert endings.locked(state) == endings.NONE_ID
            assert endings.lock(state, picked)["ok"], (seed, chosen, picked)
            seen.add(picked)
    # Not vacuous: the sample picks more than the fail-forward, and swears
    # endings it then breaks.
    assert len(seen) >= 4 and "the_rope" in seen, sorted(seen)
    assert broken_oaths >= 5, broken_oaths


#: T8 (T7's review): the four combinations the sample above never reaches,
#: each driven on purpose -- the facts that make the SWORN ending eligible,
#: the oath, then the fact that breaks it -- with the ending resolve must
#: fall to. (sworn facts, sworn ending, breaking fact, the pick.)
_BROKEN_OATHS = [
    # A partner who then gives the Magpie up at the desk: the name cleared.
    (("partnered",), "partners", "unmasked", "cleared"),
    # Bound for the barge, then the heart in the pack: the heart's getaway.
    (("wage",), "honest_after_all", "heart", "the_legend"),
    # Gannet's needles earned, then Silas's rise wins: the Dapper's city.
    # (Since T8 fix round 1 the needles wait for the fair: it is walked first.)
    (("fair", "sworn", "hall", "lever"), "guildmaster", "silas_won", "the_dappers_city"),
]


@pytest.mark.parametrize("sworn_facts,sworn,breaks,expected", _BROKEN_OATHS,
                         ids=[row[1] for row in _BROKEN_OATHS])
def test_a_broken_oath_falls_to_what_was_earned_instead(hue, sworn_facts, sworn, breaks,
                                                         expected) -> None:
    from engine.game import endings
    from engine.game.effects import apply_effect

    state = _city(2)   # Silas's rise never fills on its own here (seed 11: day 7)
    for fact in sworn_facts:
        _GATE_FACTS[fact](state)
    assert sworn in endings.eligible(state).eligible
    assert apply_effect(state, {"type": "ending_intent", "ending": sworn})["ok"]
    assert endings.resolve(state) == sworn
    _GATE_FACTS[breaks](state)
    report = endings.eligible(state)
    assert sworn not in report.eligible, report.eligible
    assert endings.intent(state) == sworn   # the oath stands; the gate does not
    assert endings.resolve(state) == expected
    assert _facts_allow(expected, {*sworn_facts, breaks})
    assert not endings.lock(state, sworn)["ok"]
    assert endings.lock(state, expected)["ok"]


def test_a_wrong_naming_after_a_right_one_leaves_cleared_sworn(hue) -> None:
    """The fourth combination: Cleared sworn on a right naming, then a wrong
    one on the captain's desk. It does not break -- the right naming stands
    over it (`no_wrong_name_standing` holds whenever `unmasked` does, T7's
    finding) -- so resolve keeps the oath; and before any right naming, a
    wrong one leaves Cleared unsworn and resolve falls to The Rope."""
    from engine.game import endings
    from engine.game.effects import apply_effect

    state = _city(11)
    _GATE_FACTS["unmasked"](state)
    assert apply_effect(state, {"type": "ending_intent", "ending": "cleared"})["ok"]
    _GATE_FACTS["named_wrongly"](state)
    assert "cleared" in endings.eligible(state).eligible
    assert endings.resolve(state) == "cleared"
    assert endings.lock(state, "cleared")["ok"]

    state = _city(11)
    _GATE_FACTS["named_wrongly"](state)
    assert "cleared" not in endings.eligible(state).eligible
    assert not apply_effect(state, {"type": "ending_intent", "ending": "cleared"})["ok"]
    assert endings.resolve(state) == "the_rope"


# -- secrecy -------------------------------------------------------------------


def test_the_gm_line_names_the_magpie_only_after_the_reveal_or_the_partnership(hue) -> None:
    """For each candidate the seed may choose: every other fact the endings
    read, even a locked ending played out, and the GM line says nothing of
    who the Magpie is; the partnership alone, or the right naming alone,
    and it does -- by name."""
    from engine.game import endings
    from engine.world import agendas

    others = ("sworn", "silas_won", "wage", "lamps", "hall", "lever", "heart",
              "named_wrongly")
    for candidate in CANDIDATES:
        seed = _seed_for(candidate)
        name = npc_sim.display_name(candidate)
        state = _city(seed)
        assert agendas.role(state, "magpie") == candidate
        for fact in others:
            _GATE_FACTS[fact](state)
        assert "WHO THE MAGPIE IS" not in _gm(state), candidate
        assert endings.lock(state, "the_legend")["ok"]
        assert endings.run_module(state)["ok"]
        assert "WHO THE MAGPIE IS" not in _gm(state), candidate

        for lifts in ("partnered", "unmasked"):
            state = _city(seed)
            assert "WHO THE MAGPIE IS" not in _gm(state)
            _GATE_FACTS[lifts](state)
            gm = _gm(state)
            assert "WHO THE MAGPIE IS" in gm and name in gm, (candidate, lifts)


def _ending_texts() -> list[tuple[str, str, str]]:
    """``(ending, where, text)`` for every line the endings put in front of
    anyone: label, tease, lock reasons (the gallery, BEFORE a lock), beats
    and both branches of a gated beat, and the epilogue card's prose."""
    from engine.game import endings, epilogue

    out = []
    for ending_id, body in endings.declared().items():
        out.append((ending_id, "label", str(body.get("label") or "")))
        out.append((ending_id, "tease", str(body.get("tease") or "")))
        for clause, reason in (body.get("lock_reasons") or {}).items():
            out.append((ending_id, f"lock_reasons.{clause}", str(reason)))
        for beat in body.get("beats") or []:
            out.append((ending_id, beat["id"], str(beat.get("text") or "")))
            for branch in ("on_pass", "on_fail"):
                text = ((beat.get("gate") or {}).get(branch) or {}).get("text")
                if text:
                    out.append((ending_id, f"{beat['id']}.{branch}", str(text)))
    for ending_id, row in epilogue.declared().items():
        for key in ("title", "card_m", "card_g"):
            out.append((ending_id, key, str(row.get(key) or "")))
    return out


def test_no_ending_text_names_who_the_magpie_is(hue) -> None:
    """The endings' prose is the same whoever the seed made the Magpie, so it
    may never say which candidate it was: no sentence of any ending text --
    the gallery's (shown before a lock) or the module's and the card's
    (after) -- puts "Magpie" and a candidate's name or alias together. A
    candidate may be named in a sentence of their own (Silas Crook, the
    Company's upstart, in Guildmaster and The Dapper's City)."""
    import re

    words = re.compile(r"\b(?:" + "|".join(_CANDIDATE_WORDS) + r")\b", re.I)
    found = []
    texts = _ending_texts()
    assert len({e for e, _w, _t in texts}) == len(EIGHT)
    for ending_id, where, text in texts:
        assert "agenda_role" not in text and "clues_favour" not in text
        for sentence in re.split(r"(?<=[.!?])\s+", text):
            if re.search(r"\bmagpie", sentence, re.I) and words.search(sentence):
                found.append((ending_id, where, sentence))
    assert found == [], found


def test_the_epilogue_and_the_module_stay_hidden_until_the_lock(hue) -> None:
    """Before a lock nothing shows an ending's module or card: no epilogue,
    and the gallery rows carry only the client contract's keys (a tease and
    lock reasons at most, no beat or card prose, no title for a
    silhouette). Locked but not yet played, still no card; played, the
    card."""
    import json

    from engine.game import endings, epilogue

    prose = [text.strip()[:60] for _e, where, text in _ending_texts()
             if where.endswith(("_speak", "_act", "_seal")) or where in ("card_m", "card_g")]
    assert len(prose) == 5 * len(EIGHT)
    builds = (lambda s: None, _unmask, _GATE_FACTS["partnered"],
              lambda s: (_GATE_FACTS["heart"](s), _GATE_FACTS["named_wrongly"](s)))
    silhouettes = 0
    for build in builds:
        state = _city(11)
        build(state)
        assert epilogue.for_state(state) is None
        client = endings.to_client(state)
        for row in client["gallery"]:
            assert set(row) <= set(endings.CLIENT_ROW_KEYS), row
            if row["tier"] == endings.TIER_SILHOUETTE:
                silhouettes += 1
                assert "title" not in row, row
        shown = json.dumps(client)
        assert not [p for p in prose if p in shown]
    assert silhouettes, "no build drew a silhouette"
    state = _city(11)
    _unmask(state)
    assert endings.lock(state, "cleared")["ok"]
    assert epilogue.for_state(state) is None     # locked, not yet played
    assert endings.run_module(state)["ok"]
    card = epilogue.for_state(state)
    assert card is not None and card.ending_id == "cleared"


def test_no_deck_decides_a_card_by_the_magpies_role(hue) -> None:
    """Card presence never reads `agenda_role` -- in EVERY deck HUE & CRY
    ships, not only the ones a task remembered to check: nothing on a deck
    or a card outside its beats (its `when:`, a weight row, anything that
    decides whether it is dealt), and nothing on a beat outside its gate,
    names the role. Only a beat's own gate reads it, once the player has
    already said the name."""
    import json
    from pathlib import Path

    import yaml

    root = Path(__file__).resolve().parents[1] / registry.get("hue-and-cry").paths["decks"]
    files = sorted(root.glob("*.yaml"))
    assert {"the_confrontation.yaml", "porters_hall.yaml", "fair_day.yaml",
            "the_gallows.yaml", "lantern_house_desk.yaml"} <= {p.name for p in files}
    in_gates = 0
    for path in files:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        deck_level = {k: v for k, v in doc.items() if k != "cards"}
        assert "agenda_role" not in json.dumps(deck_level), path.name
        for card in doc.get("cards") or []:
            outside = {k: v for k, v in card.items() if k != "beats"}
            assert "agenda_role" not in json.dumps(outside), (path.name, card.get("id"))
            for beat in card.get("beats") or []:
                assert "agenda_role" not in json.dumps(
                    {k: v for k, v in beat.items() if k != "gate"}), (path.name, beat.get("id"))
                in_gates += "agenda_role" in json.dumps(beat.get("gate") or {})
    assert in_gates == 6, in_gates   # the desk's three names, the three confrontations


# ---------------------------------------------------------------------------
# v0.17 Task 8: the endings, measured -- scripts/simulate_endings.py
# ---------------------------------------------------------------------------

#: One seed per ending on which the policy that plays for it reaches it,
#: through the door the harness reports (scripts/simulate_endings.py, 40
#: seeds: the hue CHANGELOG's endings table). Pinned so the harness keeps
#: every ending in reach of a policy that acts only on what a player sees.
#: (ending, policy, seed, door)
SEED_CLEARED = SEED_LANTERN = SEED_HONEST = SEED_PARTNERS = SEED_GUILD = 0
SEED_LEGEND = SEED_DAPPER = SEED_ROPE = 1
SEED_PARTNERS_BY_NIGHT = 23
ENDINGS_REACHED = [
    ("cleared", "investigator_c", SEED_CLEARED, "card:F3_the_real_magpie"),
    ("a_lantern", "lantern", SEED_LANTERN, "card:D3_the_badge"),
    ("honest_after_all", "porter", SEED_HONEST, "quest:the_evening_barge"),
    ("partners", "partner", SEED_PARTNERS, "card:F6_the_heist_together"),
    # T8 fix round 1: partnered on the last night, after the fair -- up the Hill.
    ("partners", "partner", SEED_PARTNERS_BY_NIGHT, "card:L1_the_heart_by_night"),
    ("the_legend", "heister", SEED_LEGEND, "quest:the_heart_goes_home"),
    ("guildmaster", "loyalist", SEED_GUILD, "card:P1_the_needles"),
    ("the_dappers_city", "dapper", SEED_DAPPER, "card:F4_silas_makes_his_move"),
    ("the_rope", "reckless", SEED_ROPE, "card:G1_the_last_morning"),
]


@pytest.fixture()
def hue_scripts(hue):
    _scripts_on_path()
    yield


def test_the_endings_harness_reads_the_fair_the_story_declares(hue_scripts) -> None:
    from scripts import simulate_endings

    assert simulate_endings.fair_days() == (FAIR_FIRST_DAY, FAIR_LAST_DAY)
    assert set(simulate_endings.POLICIES) == set(simulate_endings.CLASSES)
    assert set(simulate_endings.POLICIES) == set(simulate_endings.OPENINGS)


@pytest.mark.parametrize("ending_id,policy,seed,door", ENDINGS_REACHED,
                         ids=[f"{row[0]}-{row[3]}" for row in ENDINGS_REACHED])
def test_every_ending_is_reached_by_a_policy_that_plays_for_it(hue_scripts, ending_id, policy,
                                                                seed, door) -> None:
    from engine.game import endings
    from scripts import simulate_endings

    assert set(endings.declared()) == {row[0] for row in ENDINGS_REACHED}
    run = simulate_endings.play(seed, policy)
    assert (run.ending, run.door) == (ending_id, door), run
    if ending_id == "guildmaster":   # T8 fix round 1: never before the fair
        assert run.ending_day >= FAIR_FIRST_DAY, run


def test_the_endings_harness_replays_from_its_seed(hue_scripts) -> None:
    """Rule 4 and the harness's own promise: a seed replays byte for byte --
    here a run that plays the whole fair to its horizon."""
    from scripts import simulate_endings

    first = simulate_endings.play(SEED_HONEST, "porter")
    assert first.ending == "honest_after_all" and first.fair_day == FAIR_FIRST_DAY
    assert simulate_endings.play(SEED_HONEST, "porter") == first


def test_no_endings_policy_reads_what_a_player_cannot_see() -> None:
    """The harness's policies act on what the table offers: nowhere in
    scripts/simulate_endings.py's code (docstrings and comments aside) is
    the Magpie's role, a clue's `points_to` or `clues_favour` read, and an
    ending's eligibility is read only by the table (`end_of_day`), never by
    a choice."""
    import ast
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "scripts" / "simulate_endings.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    forbidden = {"agenda_role", "points_to", "clues_favour", "role", "tally"}
    for fn in (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)):
        for node in ast.walk(fn):
            name = (node.attr if isinstance(node, ast.Attribute)
                    else node.id if isinstance(node, ast.Name)
                    else node.value if isinstance(node, ast.Constant)
                    and isinstance(node.value, str) and len(node.value) < 40 else None)
            if name is None:
                continue
            assert name not in forbidden, (fn.name, name)
            if name == "eligible" and fn.name not in ("end_of_day",):
                raise AssertionError(f"{fn.name} reads an ending's eligibility")


# ---------------------------------------------------------------------------
# v0.17 Task 8, fix round 1 (the owner's rulings): Honest After All is never a
# thief's; Gannet waits for the fair; Partners has a door after it
# ---------------------------------------------------------------------------


def test_every_deed_is_counted_seen_or_unseen(hue) -> None:
    """`law.commit_deed` counts each deed it commits before any witness is
    looked for (the engine-only `law_deed_committed`), so a lift nobody saw
    is counted as one the whole market saw -- and `committed_deed` reads it.
    A deed only REPORTED (a card's or an agenda's `report`) was never
    committed, and is not counted."""
    from engine.game.effects import apply_effect
    from engine.game.quests import evaluate_condition
    from engine.world import law

    state = _city(11)
    assert law.committed(state) == 0
    assert not evaluate_condition(state, {"committed_deed": "pickpocket"})
    _a_purse_nobody_saw(state)
    assert not state.law.get("witnessed")
    assert law.committed(state, "pickpocket") == 1
    assert evaluate_condition(state, {"committed_deed": "pickpocket"})
    assert evaluate_condition(state, {"committed_deed": ["burglary", "pickpocket"]})
    assert not evaluate_condition(state, {"committed_deed": "burglary"})
    law.commit_deed(state, "pickpocket", location=UNSEEN_PLACE)
    law.commit_deed(state, "loitering", location=UNSEEN_PLACE)
    assert state.law["committed"] == {"pickpocket": 2, "loitering": 1}
    # Reported, never committed: not counted.
    apply_effect(state, {"type": "report", "deed": "burglary", "guise": "self",
                         "jurisdiction": "wick", "precision": 1.0})
    assert not evaluate_condition(state, {"committed_deed": "burglary"})
    # A deed the law file does not list is not a crime there: nothing counted.
    law.commit_deed(state, "treason", location=UNSEEN_PLACE)
    assert "treason" not in state.law["committed"]


def test_a_lift_is_counted_through_its_own_code(hue) -> None:
    """The real caller, not the function alone: a lift (`thievery.lift`) is
    counted whether its hand came away full or not."""
    from engine.world import law, npc_sim, thievery

    state = _city(11)
    _at(state, "wickmarket", 13)
    roles = set(law.load_spec()["roles"])
    marks = [p.npc_id for p in npc_sim.npcs_at(state, "wickmarket")
             if p.available and p.role not in roles]
    assert marks
    thievery.lift(state, marks[0])
    assert law.committed(state, "pickpocket") == 1


def test_law_deed_committed_is_the_engines_alone(hue, tmp_path) -> None:
    """Bookkeeping `commit_deed` writes. Authored content naming it forges
    a theft: refused in an agenda move at load, reported anywhere else by
    the validator, dropped by a set-piece's bounder."""
    from engine.challenges import spec as spec_module
    from engine.game import effects
    from engine.world import agendas

    assert "law_deed_committed" in effects.ENGINE_ONLY_EFFECTS
    assert effects.ENGINE_ONLY_EFFECTS <= agendas.BOOKKEEPING_EFFECTS
    out = spec_module.clamp_outcome({"effects": [{"type": "law_deed_committed",
                                                  "deed": "pickpocket"}]},
                                    [], authored=True,
                                    extra_types=spec_module.AUTHORED_CHALLENGE_EFFECT_TYPES)
    assert out["effects"] == []
    issues = _hue_issues_with(tmp_path, pieces=[_piece_filing(
        {"type": "law_deed_committed", "deed": "pickpocket"})])
    assert [i for i in issues if "law_deed_committed" in i and "engine" in i], issues


@pytest.mark.parametrize("deed, flagged", [("pickpoket", True), ("pickpocket", False)])
def test_a_committed_deed_condition_naming_no_deed_is_an_error(hue, tmp_path, deed,
                                                                flagged) -> None:
    piece = _piece_filing({"type": "report", "deed": "escape", "guise": "self",
                           "jurisdiction": "wick", "precision": 1.0})
    piece["requires"] = {"all": [{"in_custody": True}, {"committed_deed": [deed]}]}
    issues = _hue_issues_with(tmp_path, pieces=[piece])
    hits = [i for i in issues if "committed_deed" in i]
    assert bool(hits) is flagged, issues


def test_honest_after_all_is_shut_by_any_theft_seen_or_unseen(hue) -> None:
    """The owner's ruling: no thieving at all. An honest porter who lifts ONE
    purse nobody sees -- no witness, no report, the Watch's file clean -- is
    no longer honest; nor one who burgled, fenced, or laid a hand on the
    heart. The reason is `never_stole`, alone."""
    from engine.game import endings
    from engine.game.effects import apply_effect
    from engine.world import law

    reason = endings.declared()["honest_after_all"]["lock_reasons"]["never_stole"]
    for deed in ("pickpocket", "burglary", "fencing"):
        state = _honest_ready()
        seen = law.commit_deed(state, deed, location=UNSEEN_PLACE)
        assert seen == {"witnesses": [], "reported": False}, deed
        report = endings.eligible(state)
        assert report.locked["honest_after_all"] == [reason], (deed, report.locked)
    state = _honest_ready()
    apply_effect(state, {"type": "flag", "flag": "laid_a_hand_on_the_heart"})
    assert endings.eligible(state).locked["honest_after_all"] == [reason]
    # Casing a house is not thieving (nor a jailbreak, nor a Lantern knocked
    # down: the Watch's own file answers for those, `a_clean_name`).
    state = _honest_ready()
    law.commit_deed(state, "loitering", location=UNSEEN_PLACE)
    assert _eligible(state, "honest_after_all")


@pytest.mark.parametrize("branch", ["on_pass", "on_fail"])
def test_a_hand_on_the_heart_is_recorded_won_or_lost(hue, branch) -> None:
    from engine.content import deck

    card = next(c for c in deck.load_deck("fair_day").cards if c.id == "F2_the_showing")
    beat = next(b for b in card.beats if b["id"] == "lift_the_heart")
    assert ({"type": "flag", "flag": "laid_a_hand_on_the_heart"}
            in beat["gate"][branch]["effects"])


def test_gannet_names_nobody_before_the_fair(hue) -> None:
    """The owner's ruling: Guildmaster only once the Hanging Fair has come.
    Every other clause met on the first night, and the one reason is
    `the_fair_has_come`; the fair seen, the chair is offered."""
    from engine.game import endings
    from engine.game.effects import apply_effect
    from engine.game.quests import QuestEngine
    from engine.world import jobs

    state = _city(2)
    for fact in ("sworn", "hall"):
        _GATE_FACTS[fact](state)
    apply_effect(state, {"type": "flag",
                         "flag": f"{jobs.SECRET_HELD_PREFIX}prem_gannets_house:fund_of_ious"})
    reason = endings.declared()["guildmaster"]["lock_reasons"]["the_fair_has_come"]
    assert endings.eligible(state).locked["guildmaster"] == [reason]
    _fed_until(state, FAIR_FIRST_DAY, 10)
    QuestEngine.evaluate(state)
    now = int(state.reputations.get("honest_company", 0))
    apply_effect(state, {"type": "reputation", "faction": "honest_company",
                         "delta": GUILD_STANDING - now})
    assert _eligible(state, "guildmaster")


LAST_JOB = "the_last_job"


def _partnered_by_the_confrontation(state) -> None:
    """The partnership as the confrontation's right answer writes it."""
    from engine.game.effects import apply_effect

    apply_effect(state, {"type": "flag", "flag": "partners_with_the_magpie"})


def test_the_last_job_is_dealt_on_the_hill_by_night_after_the_fair(hue) -> None:
    """Partners' door after the fair: on Margrave's Hill after dark, once the
    fair has come and gone, to a partner. Not during the fair (F6 is the door
    then), not by day, not to a thief who never threw in with the Magpie."""
    from engine.content import deck, director
    from engine.game.quests import QuestEngine

    found = deck.load_deck(LAST_JOB)
    assert found is not None and found.repeatable
    [card] = found.cards
    assert card.when == {"ending": {"eligible": "partners"}}
    assert {str(b["id"]) for b in card.beats} == {"take_it_together", "not_yet"}

    state = _city(11)
    _partnered_by_the_confrontation(state)
    state.location_id = "margraves_hill"
    _fed_until(state, FAIR_FIRST_DAY - 1, 23)
    assert director.due(state)[0] != LAST_JOB           # before the fair
    _fed_until(state, FAIR_FIRST_DAY, 23)
    QuestEngine.evaluate(state)
    assert director.due(state)[0] != LAST_JOB           # during it
    _fed_until(state, FAIR_LAST_DAY + 1, 12)
    assert director.due(state)[0] != LAST_JOB           # by day
    _fed_until(state, FAIR_LAST_DAY + 1, 19)
    assert director.due(state)[0] != LAST_JOB           # dusk is not yet dark
    _fed_until(state, FAIR_LAST_DAY + 1, 20)
    assert director.due(state)[0] == LAST_JOB           # after dark (the clock's
    assert state.time_of_day == "night"                 # night), after the fair

    stranger = _city(11)
    stranger.location_id = "margraves_hill"
    _fed_until(stranger, FAIR_FIRST_DAY, 12)
    QuestEngine.evaluate(stranger)
    _fed_until(stranger, FAIR_LAST_DAY + 1, 23)
    assert director.due(stranger)[0] != LAST_JOB


def test_partners_by_night_is_told_as_a_night_on_the_hill(hue) -> None:
    """The module's Act has two tellings: the Showing's, while the fair is
    on, and the night's after it."""
    from engine.content import deck
    from engine.game import endings
    from engine.game.quests import QuestEngine

    act = next(b for b in endings.module_beats("partners") if b["id"] == "partners_act")
    state = _city(11)
    _fed_until(state, FAIR_FIRST_DAY, 10)
    QuestEngine.evaluate(state)
    assert "sun" in deck.resolve_beat(state, act, by="test").text
    _fed_until(state, FAIR_LAST_DAY + 1, 23)
    night = deck.resolve_beat(state, act, by="test").text
    assert "gravel" in night and "sun" not in night


def test_the_partnership_says_where_the_last_job_is(hue) -> None:
    """Legible: the confrontation's right answer names both doors."""
    from engine.content import deck

    for card in deck.load_deck("the_confrontation").cards:
        say = next(b for b in card.beats if b["id"] == "say_it")
        text = " ".join(say["gate"]["on_pass"]["text"].split())
        assert "Hanging Fair" in text and "up the Hill after dark" in text, card.id


# ---------------------------------------------------------------------------
# v0.17 Task 8, fix round 2: nothing authored is cut short in silence; a
# squeeze is thieving
# ---------------------------------------------------------------------------


def _long(words: int = 200) -> str:
    return " ".join(["lamplight"] * words)   # ~2000: past even the authored cap


def test_a_cut_line_is_recorded_as_an_adjustment() -> None:
    """The bounders RECORD what they cut (the validator reads it back): an
    outcome's text past its cap, a beat's past the deck's, and an outcome's
    effects past `MAX_EFFECTS`. Fix round 3: the cap depends on the path --
    AUTHORED text (a story's own file) gets `MAX_AUTHORED_TEXT`, and only
    MODEL-composed text is held to `MAX_TEXT`."""
    from engine.challenges import spec as spec_module
    from engine.content import deck

    assert spec_module.MAX_AUTHORED_TEXT > spec_module.MAX_TEXT
    assert deck.MAX_TEXT == spec_module.MAX_AUTHORED_TEXT   # a deck is authored
    adjustments: list[str] = []
    out = spec_module.clamp_outcome({"text": _long(), "effects": []}, adjustments,
                                    authored=True)
    assert len(out["text"]) == spec_module.MAX_AUTHORED_TEXT
    assert any(spec_module.TEXT_CUT in a for a in adjustments), adjustments
    # An authored line between the two caps is kept whole, and nothing is cut.
    middle = _long(60)   # ~600 characters
    assert spec_module.MAX_TEXT < len(middle) < spec_module.MAX_AUTHORED_TEXT
    kept: list[str] = []
    assert spec_module.clamp_outcome({"text": middle, "effects": []}, kept,
                                     authored=True)["text"] == middle
    assert kept == []
    [beat] = deck.bound_beats([{"id": "b", "text": middle}], "d", "c")
    assert beat["text"] == middle and "adjustments" not in beat
    # The same line composed by a model is still bounded, and the cut recorded.
    model: list[str] = []
    assert len(spec_module.clamp_outcome({"text": middle, "effects": []}, model)["text"]) \
        == spec_module.MAX_TEXT
    assert any(spec_module.TEXT_CUT in a for a in model), model
    [beat] = deck.bound_beats([{"id": "b", "text": _long()}], "d", "c")
    assert any(spec_module.TEXT_CUT in a for a in beat["adjustments"]), beat
    short: list[str] = []
    spec_module.clamp_outcome({"text": "fine", "effects": []}, short, authored=True)
    assert short == []


def _deck_with(beat: dict) -> dict:
    return {"id": "long_deck", "draw": 1, "when": {"in_custody": True}, "cards": [{
        "id": "long_card", "required": True, "tags": ["menu"], "title": "Long",
        "text": "INTENT: a long line.", "beats": [beat]}]}


@pytest.mark.parametrize("case", ["outcome_text", "beat_text", "effects", "card_text"])
def test_a_truncated_line_in_story_content_is_an_error(hue, tmp_path, case) -> None:
    """v0.17 T8 fix round 2: text or effects the loader would cut off are a
    validator ERROR, naming the card and beat -- they vanished silently at
    play time (fix round 1 lost a fifth effect and a line's end that way).
    Since fix round 3 authored text is cut only past `MAX_AUTHORED_TEXT`, so
    the long line here is past that."""
    flag = {"type": "flag", "flag": "a"}
    beat = {"id": "go", "text": "Go.", "gate": {"on_pass": {"text": "Done.", "effects": []}}}
    deck = _deck_with(beat)
    if case == "outcome_text":
        beat["gate"]["on_pass"]["text"] = _long()
    elif case == "beat_text":
        beat["text"] = _long()
    elif case == "effects":
        beat["gate"]["on_pass"]["effects"] = [dict(flag, flag=f"f{i}") for i in range(5)]
    else:
        deck["cards"][0]["text"] = _long()
    issues = _hue_issues_with(tmp_path, deck=deck)
    hits = [i for i in issues if "long_deck.yaml" in i and "long_card" in i
            and ("cut" in i or "kept first" in i)]
    assert hits, issues


def test_a_truncated_set_piece_line_is_an_error(hue, tmp_path) -> None:
    piece = _piece_filing({"type": "report", "deed": "escape", "guise": "self",
                           "jurisdiction": "wick", "precision": 1.0})
    piece["challenge"]["reward"]["text"] = _long()
    issues = _hue_issues_with(tmp_path, pieces=[piece])
    assert [i for i in issues if "typo_break" in i and "cut" in i], issues


def test_no_shipped_story_is_cut_short() -> None:
    """Every shipped story validates with no truncation finding: fix round 3
    set the authored cap above the longest shipped authored line and
    restored the text fix round 2 had trimmed. And the longest card and beat
    this release ships -- The Wicked Garden's -- reach the narrator whole."""
    from engine.games import validation

    for slug in registry.discover():
        issues = validation.validate_story(registry.get(slug))
        cut = [f"{i.source}|{i.ref_id}|{i.message}" for i in issues
               if "cut to" in i.message or "kept first" in i.message]
        assert not cut, (slug, cut)
    registry.activate("wicked-garden")
    try:
        from engine.content import deck

        mirrors = deck.load_deck("day_08_mirrors")
        cards = {c.id: c for c in mirrors.cards}
        collects = cards["D8_06c_ashen_collects"].text
        assert collects.rstrip().endswith("MENU -- resolve exactly the beat the player chose."), \
            collects[-80:]
        night = next(b for b in cards["D8_07_night_before"].beats
                     if b["id"] == "the_asking_night")
        # Whole, and ending on its prose: the final review moved the beat's
        # design notes ("WHY IT IS NOT ON D8_05", the two doors) to a comment.
        assert night["text"].rstrip().endswith("she was not the one who raised it."), \
            night["text"][-80:]
        assert "WHY IT IS NOT" not in night["text"]
    finally:
        registry.deactivate()




def test_a_paid_squeeze_is_thieving(hue) -> None:
    """v0.17 T8 fix round 2 (I2): blackmail is filed only when a squeeze goes
    UNcollected; one paid commits and files nothing. `never_stole` reads the
    thread itself -- any Blackmail-tagged thread, in any status."""
    from engine.game import endings
    from engine.world import law

    state = _honest_ready()
    _squeezed_and_paid(state)
    assert law.committed(state) == 0 or "blackmail" not in state.law.get("committed", {})
    reason = endings.declared()["honest_after_all"]["lock_reasons"]["never_stole"]
    assert endings.eligible(state).locked["honest_after_all"] == [reason]
