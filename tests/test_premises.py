"""
Premises: the houses, shops and counting-rooms inside a district.

THE SHAPE. ``paths.premises`` names a directory: ``districts.yaml`` says how
many premises each district holds and of which types, ``names.yaml`` carries
the pools, ``types/`` the generated kinds and ``anchors/`` the hand-written
ones. ``procgen.generate_world`` lays them out once from the seed on their own
``PREMISES`` stream, and every household member becomes a procgen NPC whose
routine is already resolved to real ids -- so ``npc_sim`` finds them at their
desk at ten and at home at midnight with no new code of its own.

WHAT THESE TESTS HOLD. The layout replays from the seed; the anchor appears
exactly once; security scales with tier; ``@work`` lands on one of the type's
own workplaces; a content fault is a ValueError naming its file rather than a
premise quietly missing; and a story that declares no premises -- the flagship
-- generates the byte-identical village it generated at v0.8.1.

The synthetic fixture uses the flagship's location and item ids because those
are what the default config loads; the engine validates against whatever the
active story ships.

Version: v0.1.0 [2026-09-23]
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterator

import pytest
import yaml

from engine.config import set_overlay
from engine.game.clock import set_clock
from engine.game.locations import LOCATIONS
from engine.game.procgen import generate_world
from engine.game.state import GameState
from engine.world import npc_sim, premises

TOWNHOUSE: dict[str, Any] = {
    "id": "townhouse",
    "label": "townhouse",
    "name_patterns": ["the {surname} townhouse", "Number {n}, {street}"],
    "tiers": {1: 5, 2: 3, 3: 1},
    "household": [
        {
            "role": "master",
            "routine": [
                {
                    "hours": [9, 10, 11, 12, 13, 14, 15, 16, 17],
                    "location": "@work",
                    "activity": "at their counting desk",
                },
                {"hours": [18, 19], "location": "@home", "activity": "at supper"},
            ],
        },
        {"role": "cook", "routine": []},
    ],
    "work_at": ["edgewood_bakery", "the_forge"],
    "security": [
        {"id": "good_lock", "text": "a good lock on the street door", "tier_min": 1},
        {"id": "barred_shutters", "text": "barred shutters", "tier_min": 1},
        {"id": "yard_dog", "text": "a dog in the yard after dark", "tier_min": 2},
        {"id": "night_man", "text": "a man who sits up", "tier_min": 3},
    ],
    "loot": {
        1: [{"item_id": "loaf", "weight": 3}],
        2: [{"item_id": "loaf", "weight": 2}, {"item_id": "golden_ring", "weight": 1}],
        3: [{"item_id": "golden_ring", "weight": 2}],
    },
    "secrets": [
        {"id": "second_ledger", "text": "a second set of books"},
        {"id": "debt_letter", "text": "a letter about a debt"},
    ],
}

MILL_HOUSE: dict[str, Any] = {
    "id": "mill_house",
    "label": "the mill house",
    "district": "millhaven_market",
    "name": "the old mill house",
    "tier": 3,
    "household": [
        {
            "role": "miller",
            "routine": [{"hours": [8, 9, 10], "location": "@work", "activity": "grinding"}],
        },
    ],
    "work_at": ["millhaven_gate"],
    "security": [
        {"id": "iron_bar", "text": "an iron bar across the door"},
        {"id": "mill_dog", "text": "the miller's dog"},
    ],
    "loot": ["golden_ring"],
    "secrets": [{"id": "flour_debt", "text": "the mill owes the Guild"}],
}

DISTRICTS: dict[str, Any] = {
    "edgewood_square": {"count": 3, "types": {"townhouse": 1}},
    "millhaven_market": {"count": 2, "types": {"townhouse": 1}, "anchors": ["mill_house"]},
}

NAMES: dict[str, Any] = {
    "pools": {
        "surname": ["Harrowgate", "Fenwick", "Olde", "Marrow", "Pike", "Tallis", "Venn"],
        "street": ["Wick Lane", "Tallow Row", "Bell Street"],
        "trade": ["chandler", "cooper"],
        "given": ["Ada", "Bram", "Cass", "Dell", "Edda", "Fitch", "Gil", "Hob"],
    }
}


def _write(root: Path, rel: str, data: Any) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def _build(root: Path, **overrides: Any) -> Path:
    """Write the fixture tree; an override replaces one file's document."""
    files = {
        "districts.yaml": DISTRICTS,
        "names.yaml": NAMES,
        "types/townhouse.yaml": TOWNHOUSE,
        "anchors/mill_house.yaml": MILL_HOUSE,
    }
    files.update(overrides)
    for rel, doc in files.items():
        _write(root, rel, doc)
    return root


@pytest.fixture()
def declared(tmp_path: Path) -> Iterator[Path]:
    root = _build(tmp_path / "premises")
    set_overlay({"paths": {"premises": str(root)}})
    try:
        yield root
    finally:
        set_overlay(None)


def _generated(prems: list[dict[str, Any]], district: str) -> list[dict[str, Any]]:
    return [p for p in prems if p["district"] == district and not p["anchor"]]


# -- (a) counts and the anchor ------------------------------------------------


def test_each_district_holds_its_count_and_the_anchor_once(declared: Path) -> None:
    prems, _ = premises.generate(42)
    assert len(_generated(prems, "edgewood_square")) == 3
    assert len(_generated(prems, "millhaven_market")) == 2
    anchors = [p for p in prems if p["anchor"]]
    assert [(p["type"], p["district"]) for p in anchors] == [("mill_house", "millhaven_market")]
    anchor = anchors[0]
    # An anchor's contents are authored, not drawn.
    assert anchor["name"] == "the old mill house"
    assert anchor["tier"] == 3
    assert anchor["security"] == ["iron_bar", "mill_dog"]
    assert anchor["loot"] == ["golden_ring"]
    assert anchor["secret"] == "flour_debt"
    ids = [p["id"] for p in prems]
    assert len(ids) == len(set(ids))


def test_a_premise_has_the_documented_shape(declared: Path) -> None:
    prems, _ = premises.generate(42)
    first = _generated(prems, "edgewood_square")[0]
    assert first["id"] == "prem_edgewood_square_1"
    assert set(first) == {
        "id", "district", "type", "anchor", "name", "tier",
        "household", "security", "loot", "secret",
    }
    assert first["household"] == [
        "gen_edgewood_square_1_master",
        "gen_edgewood_square_1_cook",
    ]
    assert first["secret"] in {"second_ledger", "debt_letter"}


# -- (b) determinism ----------------------------------------------------------


def test_the_same_seed_lays_out_the_same_city(declared: Path) -> None:
    assert premises.generate(42) == premises.generate(42)


def test_different_seeds_lay_out_different_cities(declared: Path) -> None:
    layouts = set()
    for seed in range(10):
        prems, npcs = premises.generate(seed)
        layouts.add(
            json.dumps(
                [(p["name"], p["tier"]) for p in prems] + [n["name"] for n in npcs]
            )
        )
    assert len(layouts) > 1


# -- (c)/(d) households are real procgen people --------------------------------


def test_every_household_member_is_a_procgen_npc_with_a_real_routine(
    declared: Path,
) -> None:
    world = generate_world(42)
    by_id = {n["id"]: n for n in world.npcs}
    assert world.premises, "generate_world must carry the premises"
    for prem in world.premises:
        home = npc_sim.interior_id(prem["district"], prem["id"])
        for member_id in prem["household"]:
            npc = by_id[member_id]
            assert npc["home"] == home
            assert npc["premise"] == prem["id"]
            assert " " in npc["name"]
            for slot in npc["routine"]:
                loc = slot["location"]
                assert loc == home or loc in LOCATIONS, loc


def test_at_work_resolves_to_one_of_work_at(declared: Path) -> None:
    for seed in range(10):
        _, npcs = premises.generate(seed)
        for npc in npcs:
            spec = premises.spec(
                "mill_house" if npc["premise"] == "prem_mill_house" else "townhouse"
            )
            work = [s for s in npc["routine"] if s["activity"] in {"at their counting desk", "grinding"}]
            for slot in work:
                assert slot["location"] in spec["work_at"]


def test_a_household_member_is_found_at_work_and_at_home(declared: Path) -> None:
    state = GameState()
    state.procgen = generate_world(42)
    prem = _generated(state.procgen.premises, "edgewood_square")[0]
    master = state.procgen.npc_by_id(prem["household"][0])
    assert master is not None
    work = next(s["location"] for s in master["routine"] if 10 in s["hours"])
    set_clock(state, day=1, hour=10)
    assert npc_sim.resolve_npc(state, master["id"]).location_id == work
    set_clock(state, day=1, hour=23)
    assert npc_sim.resolve_npc(state, master["id"]).location_id == npc_sim.interior_id(
        prem["district"], prem["id"]
    )


# -- (e) security scales with tier ---------------------------------------------


def test_security_count_is_the_tier_and_respects_tier_min(declared: Path) -> None:
    pool = {s["id"]: s for s in TOWNHOUSE["security"]}
    for seed in range(20):
        prems, _ = premises.generate(seed)
        for prem in prems:
            if prem["anchor"]:
                continue
            assert len(prem["security"]) == prem["tier"]
            assert len(set(prem["security"])) == prem["tier"]
            for sec in prem["security"]:
                assert pool[sec]["tier_min"] <= prem["tier"]
            assert len(prem["loot"]) == prem["tier"]


# -- lookups ------------------------------------------------------------------


def test_at_and_get_read_the_state(declared: Path) -> None:
    state = GameState()
    state.procgen = generate_world(42)
    here = premises.at(state, "millhaven_market")
    assert len(here) == 3
    assert all(p["district"] == "millhaven_market" for p in here)
    assert premises.at(state, "forest_clearing") == []
    assert premises.get(state, "prem_mill_house")["name"] == "the old mill house"
    assert premises.get(state, "prem_nowhere") is None
    assert premises.spec("townhouse")["label"] == "townhouse"
    assert premises.spec("mill_house")["name"] == "the old mill house"


# -- content faults name their file ---------------------------------------------


def _fault(tmp_path: Path, **overrides: Any) -> str:
    root = _build(tmp_path / "premises", **overrides)
    set_overlay({"paths": {"premises": str(root)}})
    try:
        with pytest.raises(ValueError) as info:
            premises.generate(1)
    finally:
        set_overlay(None)
    return str(info.value)


def test_unknown_loot_item_is_a_fault_naming_the_file(tmp_path: Path) -> None:
    bad = {**TOWNHOUSE, "loot": {**TOWNHOUSE["loot"], 2: [{"item_id": "no_such_spoon", "weight": 1}]}}
    msg = _fault(tmp_path, **{"types/townhouse.yaml": bad})
    assert "townhouse.yaml" in msg and "no_such_spoon" in msg


def test_unknown_district_is_a_fault_naming_the_file(tmp_path: Path) -> None:
    bad = {**DISTRICTS, "nowhere_row": {"count": 1, "types": {"townhouse": 1}}}
    msg = _fault(tmp_path, **{"districts.yaml": bad})
    assert "districts.yaml" in msg and "nowhere_row" in msg


def test_unknown_routine_location_is_a_fault_naming_the_file(tmp_path: Path) -> None:
    household = [{"role": "cook", "routine": [{"hours": [3], "location": "the_moon", "activity": "x"}]}]
    msg = _fault(tmp_path, **{"types/townhouse.yaml": {**TOWNHOUSE, "household": household}})
    assert "townhouse.yaml" in msg and "the_moon" in msg


def test_a_tier_with_too_little_security_is_a_fault(tmp_path: Path) -> None:
    # Tier 3 must draw three features; two eligible would silently hand the
    # richest houses in the city fewer defences than their tier promises.
    thin = {**TOWNHOUSE, "security": TOWNHOUSE["security"][:2]}
    msg = _fault(tmp_path, **{"types/townhouse.yaml": thin})
    assert "townhouse.yaml" in msg and "security" in msg


def test_a_type_with_no_label_is_a_fault_naming_the_file(tmp_path: Path) -> None:
    # `label` is what the casing board shows the player
    # (engine/game/state.py::GameState._premises_block); an id like
    # "townhouse" standing in for it is exactly the id-as-content bug this
    # repo keeps finding, so it is required at load time rather than
    # defaulted at read time.
    unlabeled = {k: v for k, v in TOWNHOUSE.items() if k != "label"}
    msg = _fault(tmp_path, **{"types/townhouse.yaml": unlabeled})
    assert "townhouse.yaml" in msg and "label" in msg


def test_an_anchor_with_no_label_is_a_fault_naming_the_file(tmp_path: Path) -> None:
    unlabeled = {k: v for k, v in MILL_HOUSE.items() if k != "label"}
    msg = _fault(tmp_path, **{"anchors/mill_house.yaml": unlabeled})
    assert "mill_house.yaml" in msg and "label" in msg


def test_a_declared_directory_that_is_missing_is_a_fault(tmp_path: Path) -> None:
    set_overlay({"paths": {"premises": str(tmp_path / "absent")}})
    try:
        with pytest.raises(ValueError, match="absent"):
            premises.generate(1)
    finally:
        set_overlay(None)


# -- (f) a story without premises pays nothing ---------------------------------

# blake2b(16) of json.dumps(generate_world(seed).to_dict(), sort_keys=True),
# measured on v0.8.1's flagship before premises existed.
V081_FLAGSHIP_DIGESTS = {
    42: "7fac26b33c11caa1795b13d4f86e0ef0",
    7: "019ce1ec178f4c0f47507f29e73c4ecd",
}


@pytest.mark.parametrize("seed", sorted(V081_FLAGSHIP_DIGESTS))
def test_the_flagship_village_is_byte_identical(seed: int) -> None:
    assert not premises.declared()
    result = generate_world(seed)
    assert result.premises == []
    data = result.to_dict()
    assert data.pop("premises") == []
    digest = hashlib.blake2b(
        json.dumps(data, sort_keys=True).encode("utf-8"), digest_size=16
    ).hexdigest()
    assert digest == V081_FLAGSHIP_DIGESTS[seed]


def test_undeclared_generates_nothing() -> None:
    assert premises.generate(42) == ([], [])


# -- a secret's `thread:` (v0.15) ---------------------------------------------


def _mill_with_thread(thread: str) -> dict[str, Any]:
    return {**MILL_HOUSE, "secrets": [{**MILL_HOUSE["secrets"][0], "thread": thread}]}


def _threads_doc(requires: Any) -> dict[str, Any]:
    return {"version": 1, "tags": ["Blackmail"], "templates": {
        "squeeze_the_miller": {"title": "the miller's debt", "source": "npc_marta",
                               "tags": ["Blackmail"], "terms": "coin for quiet",
                               "requires": requires}}}


def _load_with(tmp_path: Path, mill: dict[str, Any], threads_doc: Any = None) -> Any:
    root = _build(tmp_path / "premises", **{"anchors/mill_house.yaml": mill})
    paths = {"premises": str(root)}
    if threads_doc is not None:
        path = tmp_path / "threads.yaml"
        path.write_text(yaml.safe_dump(threads_doc, sort_keys=False), encoding="utf-8")
        paths["threads"] = str(path)
    set_overlay({"paths": paths})
    try:
        return premises.generate(1)
    finally:
        set_overlay(None)


def test_a_secrets_thread_must_name_a_declared_template(tmp_path: Path) -> None:
    with pytest.raises(ValueError) as info:
        _load_with(tmp_path, _mill_with_thread("squeeze_the_miller"))
    assert "mill_house.yaml" in str(info.value) and "squeeze_the_miller" in str(info.value)


def test_a_secrets_thread_must_gate_on_holding_that_secret(tmp_path: Path) -> None:
    """A lever offered before the thief holds it is the inert-shape bug: it must
    read `secret_held` for this secret in its `requires`."""
    with pytest.raises(ValueError) as info:
        _load_with(tmp_path, _mill_with_thread("squeeze_the_miller"),
                   _threads_doc({"at_location": "millhaven_market"}))
    assert "mill_house.yaml" in str(info.value) and "secret_held" in str(info.value)
    with pytest.raises(ValueError):
        _load_with(tmp_path, _mill_with_thread("squeeze_the_miller"),
                   _threads_doc({"secret_held": {"secret": "some_other_secret"}}))
    # Held as one alternative, or held NOT at all, gates nothing.
    for loose in ({"any": [{"secret_held": {"secret": "flour_debt"}},
                           {"at_location": "millhaven_market"}]},
                  {"none": [{"secret_held": {"secret": "flour_debt"}}]}):
        with pytest.raises(ValueError):
            _load_with(tmp_path, _mill_with_thread("squeeze_the_miller"), _threads_doc(loose))


def test_a_secrets_thread_that_gates_on_it_loads(tmp_path: Path) -> None:
    prems, _ = _load_with(
        tmp_path, _mill_with_thread("squeeze_the_miller"),
        _threads_doc({"all": [{"at_location": "millhaven_market"},
                              {"secret_held": {"secret": "flour_debt"}}]}))
    assert any(p["type"] == "mill_house" for p in prems)


def test_a_secrets_thread_must_be_a_name(tmp_path: Path) -> None:
    with pytest.raises(ValueError) as info:
        _load_with(tmp_path, {**MILL_HOUSE, "secrets": [{**MILL_HOUSE["secrets"][0],
                                                         "thread": ["a", "b"]}]})
    assert "mill_house.yaml" in str(info.value) and "thread" in str(info.value)
