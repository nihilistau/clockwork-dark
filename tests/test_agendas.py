"""
Agendas, part one: the data, the state, and the seed-chosen roles.

THE SHAPE. ``paths.agendas`` names ONE YAML file (the contract is in
.superpowers/sdd/2026-09-24-v0.12.0-agendas/context.md): ``roles`` -- hidden
identities the seed chooses from a list of scheduled NPCs, DERIVED on read and
never stored -- and ``agendas``, each an owner, a goal, a hidden clock, moves
on a cadence and reactions to engine events. ``state.agendas`` holds only the
bookkeeping, and the ``agenda_mark`` effect is the only writer of its
``last_hour``/``moves``/``fired``/``truth``.

WHAT THESE TESTS HOLD. The loader accepts the contract and rejects each
malformed file loudly, naming the file -- an agenda whose gate names a
predicate nobody registered, or whose clock the narrator's clock block never
reads, would load, validate and do nothing. A role is the same NPC for the
same seed across a save/load round trip and every candidate is reachable over
thirty seeds. A story that declares no agendas keeps an empty ``agendas`` and
every call is inert. The four predicates the loader validates against have
working semantics from this task on: ``wanted``, ``reported_to``,
``agenda_hit`` and ``premise_robbed``'s ``owner`` filter.

Synthetic stories only (HUE & CRY's agendas land in Task 5). The byte-
identical controls are the flagship and a synthetic story that declares the
Law and jobs but no agendas.

Version: v0.1.1 [2026-09-25]
"""

from __future__ import annotations

import copy
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import pytest
import yaml

from engine.config import set_overlay
from engine.game import quests
from engine.game.effects import apply_effect
from engine.game.procgen import generate_world
from engine.game.state import GameState
from engine.state import active as active_state
from engine.state.schema import parse_schema
from engine.world import agendas, law, premises

from test_jobs import JOBS_SPEC, LAW_SPEC, _rob
from test_law_arrest import ENCOUNTERS
from test_premises import MILL_HOUSE, _build

SQUARE = "edgewood_square"
MARKET = "millhaven_market"
CANDIDATES = ["npc_wren", "npc_silas", "npc_imelda"]

#: The synthetic cast: the three the seed may choose, and a captain.
SCHEDULES: dict[str, Any] = {
    "npcs": {
        "npc_wren": {"name": "Wren", "role": "lamplighter", "home": SQUARE, "routine": []},
        "npc_silas": {"name": "Silas Crook", "role": "upstart", "home": SQUARE, "routine": []},
        "npc_imelda": {"name": "Lady Imelda", "role": "noble", "home": MARKET, "routine": []},
        "npc_ardane": {"name": "Captain Ardane", "role": "watch", "home": SQUARE,
                       "routine": []},
    }
}

CLOCKS_TABLE: dict[str, Any] = {
    "clocks": {
        "magpie_spree": {"label": "How close the Magpie is to the heart of the city"},
        "open_clock": {"label": "A clock the player can see"},
    }
}

STATE_YAML: dict[str, Any] = {
    "clocks": {
        "magpie_spree": {"min": 0, "max": 6, "visibility": "hidden"},
        "open_clock": {"min": 0, "max": 6, "visibility": "public"},
        # Declared as a value, missing from the clock table: the narrator's
        # clock block (prompts._clocks_block) reads only the table.
        "tableless": {"min": 0, "max": 6, "visibility": "hidden"},
    }
}

AGENDAS_SPEC: dict[str, Any] = {
    "roles": {
        "magpie": {
            "from": list(CANDIDATES),
            "mask": {"instead": "the Magpie", "unmask_when": {"flag": "magpie_unmasked"}},
        }
    },
    "agendas": {
        "the_magpie": {
            "owner": {"role": "magpie"},
            "goal": "steal every shining thing",
            "clock": "magpie_spree",
            "moves": [
                {
                    "id": "lift_a_shiny",
                    "every_hours": 24,
                    "at_hours": [1, 2, 3],
                    "when": {"none": [{"flag": "magpie_caught"}]},
                    "select": {"premise": {"tier_min": 2, "not_robbed": True,
                                           "loot_tag": "trade"}},
                    "effects": [{"type": "report", "deed": "burglary", "guise": "magpie",
                                 "jurisdiction": "{target_jurisdiction}", "precision": 0.6}],
                    "advance": 1,
                    "robs": True,
                    "trace": {"text": "a black feather on the sill of {target_name}",
                              "where": "target", "public": False},
                },
                {
                    "id": "watch_the_witnesses",
                    "every_hours": 12,
                    "select": {"witness": {"knows": "magpie"}},
                    "effects": [],
                    "trace": {"text": "someone asked after you", "where": SQUARE},
                },
            ],
            "reactions": [
                {
                    "id": "the_captain_hears",
                    "on": {"reported_to": {"npc": "npc_ardane", "guise": "magpie"}},
                    "once": True,
                    "effects": [],
                    "advance": 1,
                },
                {
                    "id": "hunted",
                    "on": {"wanted": {"min": "hunted"}},
                    "effects": [{"type": "flag", "flag": "magpie_lies_low"}],
                },
            ],
        },
        "the_captain": {
            "owner": "npc_ardane",
            "goal": "hang the Magpie",
            "clock": "magpie_spree",
            "moves": [
                {"id": "sweep", "every_hours": 6, "start_hour": 30,
                 "when": {"agenda_hit": {"agenda": "the_magpie"}}},
            ],
        },
    },
}


def _dump(path: Path, doc: Any) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = doc if isinstance(doc, str) else yaml.safe_dump(doc, sort_keys=False)
    path.write_text(text, encoding="utf-8")
    return str(path)


def _paths(tmp_path: Path, agendas_doc: Any = None, *, lawful: bool = True,
           with_premises: bool = True, with_agendas: bool = True,
           with_jobs: bool = False, **premise_files: Any) -> dict[str, str]:
    paths = {
        "npc_schedules": _dump(tmp_path / "npc_schedules.yaml", SCHEDULES),
        "clocks": _dump(tmp_path / "clocks.yaml", CLOCKS_TABLE),
    }
    if with_agendas:
        doc = AGENDAS_SPEC if agendas_doc is None else agendas_doc
        paths["agendas"] = _dump(tmp_path / "agendas.yaml", doc)
    if with_premises:
        paths["premises"] = str(_build(tmp_path / "premises", **premise_files))
    if lawful:
        paths["law"] = _dump(tmp_path / "law.yaml", LAW_SPEC)
        _dump(tmp_path / "encounters" / "watch.yaml", ENCOUNTERS)
        paths["encounters"] = str(tmp_path / "encounters")
    if with_jobs:
        paths["jobs"] = _dump(tmp_path / "jobs.yaml", JOBS_SPEC)
    return paths


@contextmanager
def story(paths: dict[str, str]) -> Iterator[None]:
    """Activate a synthetic story: the overlay, then its state schema."""
    set_overlay({"paths": paths})
    active_state._schema = parse_schema(STATE_YAML, slug="synthetic")
    try:
        yield
    finally:
        active_state.reset_schema()
        set_overlay(None)


@pytest.fixture()
def declared(tmp_path: Path) -> Iterator[Path]:
    with story(_paths(tmp_path)):
        yield tmp_path


def _world(seed: int = 42, location: str = SQUARE) -> GameState:
    state = GameState(rng_seed=seed, location_id=location)
    state.procgen = generate_world(seed)
    return state


def _mutated(**changes: Any) -> dict[str, Any]:
    """A copy of the contract with ``a__b__0__c`` paths replaced."""
    doc = copy.deepcopy(AGENDAS_SPEC)
    for dotted, value in changes.items():
        node: Any = doc
        *parents, leaf = dotted.split("__")
        for key in parents:
            node = node[int(key)] if isinstance(node, list) else node[key]
        if isinstance(node, list):
            node[int(leaf)] = value
        else:
            node[leaf] = value
    return doc


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def test_the_contract_loads(declared: Path) -> None:
    assert agendas.declared()
    spec = agendas.spec()
    assert spec["roles"]["magpie"]["from"] == CANDIDATES
    assert spec["roles"]["magpie"]["mask"]["instead"] == "the Magpie"
    magpie = spec["agendas"]["the_magpie"]
    assert magpie["owner"] == {"role": "magpie"}
    assert magpie["clock"] == "magpie_spree"
    lift = magpie["moves"][0]
    assert lift["id"] == "lift_a_shiny" and lift["every_hours"] == 24
    assert lift["at_hours"] == [1, 2, 3] and lift["start_hour"] == 0
    assert lift["robs"] is True and lift["advance"] == 1
    assert lift["select"] == {"premise": {"tier_min": 2, "not_robbed": True,
                                          "loot_tag": "trade"}}
    assert lift["trace"] == {"text": "a black feather on the sill of {target_name}",
                             "where": "target", "public": False}
    # Defaults: no hours filter, no robbing, no clock movement, not public.
    watch = magpie["moves"][1]
    assert watch["at_hours"] == [] and watch["robs"] is False and watch["advance"] == 0
    assert watch["trace"]["public"] is False
    hears = magpie["reactions"][0]
    assert hears["once"] is True and hears["advance"] == 1
    assert magpie["reactions"][1]["once"] is False
    captain = spec["agendas"]["the_captain"]
    assert captain["owner"] == "npc_ardane"
    assert captain["moves"][0]["start_hour"] == 30
    assert captain["reactions"] == []


MALFORMED: dict[str, Any] = {
    "an owner who is not a scheduled NPC": _mutated(
        agendas__the_captain__owner="npc_nobody"),
    "an owner naming an undeclared role": _mutated(
        agendas__the_captain__owner={"role": "phantom"}),
    "a role member who is not a scheduled NPC": _mutated(
        roles__magpie__from=["npc_wren", "npc_ghost"]),
    "a role with no candidates": _mutated(roles__magpie__from=[]),
    "a mask with no replacement text": _mutated(
        roles__magpie__mask={"instead": "", "unmask_when": {"flag": "x"}}),
    "an undeclared clock": _mutated(agendas__the_captain__clock="no_such_clock"),
    "a clock that is not hidden": _mutated(agendas__the_captain__clock="open_clock"),
    "a clock missing from the clock table": _mutated(
        agendas__the_captain__clock="tableless"),
    "an unknown predicate in a move's when": _mutated(
        agendas__the_captain__moves__0__when={"moon_phase": "full"}),
    "an unknown predicate nested in a group": _mutated(
        agendas__the_captain__moves__0__when={"any": [{"flag": "x"}, {"moon_phase": 1}]}),
    "an unknown predicate in a reaction's on": _mutated(
        agendas__the_magpie__reactions__1__on={"moon_phase": "full"}),
    "an unknown predicate in unmask_when": _mutated(
        roles__magpie__mask={"instead": "the Magpie", "unmask_when": {"moon_phase": 1}}),
    "a group beside a sibling predicate": _mutated(
        agendas__the_captain__moves__0__when={"all": [{"flag": "x"}], "not_flag": "y"}),
    "a reaction with no on": _mutated(
        agendas__the_magpie__reactions__1={"id": "hunted", "effects": []}),
    "an unknown selector key": _mutated(
        agendas__the_magpie__moves__0__select={"premise": {"wealth_min": 3}}),
    "an unknown selector kind": _mutated(
        agendas__the_magpie__moves__0__select={"tavern": {}}),
    "two selector kinds at once": _mutated(
        agendas__the_magpie__moves__1__select={"witness": {"knows": "magpie"},
                                               "fence": {}}),
    "a premise selector naming an unknown district": _mutated(
        agendas__the_magpie__moves__0__select={"premise": {"district": "atlantis"}}),
    "a premise selector naming an unknown type": _mutated(
        agendas__the_magpie__moves__0__select={"premise": {"type": "castle"}}),
    "a premise selector whose loot tag no item carries": _mutated(
        agendas__the_magpie__moves__0__select={"premise": {"loot_tag": "shiny_nonsense"}}),
    "a premise selector whose not_robbed is not a bool": _mutated(
        agendas__the_magpie__moves__0__select={"premise": {"not_robbed": "yes"}}),
    "a witness selector without knows": _mutated(
        agendas__the_magpie__moves__1__select={"witness": {}}),
    "a witness selector knowing an unknown guise": _mutated(
        agendas__the_magpie__moves__1__select={"witness": {"knows": "phantom"}}),
    "a fence selector in a story with no fence": _mutated(
        agendas__the_magpie__moves__1__select={"fence": {}}),
    "a cadence of zero": _mutated(agendas__the_captain__moves__0__every_hours=0),
    "a move with no cadence": _mutated(
        agendas__the_captain__moves__0={"id": "sweep"}),
    "an hour of the day that does not exist": _mutated(
        agendas__the_magpie__moves__0__at_hours=[1, 24]),
    "a bad trace where": _mutated(
        agendas__the_magpie__moves__1__trace={"text": "x", "where": "atlantis"}),
    "a trace with no text": _mutated(
        agendas__the_magpie__moves__1__trace={"text": "", "where": "owner"}),
    "a trace whose public is not a bool": _mutated(
        agendas__the_magpie__moves__1__trace={"text": "x", "where": "owner",
                                              "public": "maybe"}),
    "a trace at the target with no target": _mutated(
        agendas__the_captain__moves__0__trace={"text": "x", "where": "target"}),
    "an effect with no type": _mutated(
        agendas__the_magpie__moves__1__effects=[{"flag": "x"}]),
    "an effect of an unknown type": _mutated(
        agendas__the_magpie__moves__1__effects=[{"type": "teleport"}]),
    "robs that is not a bool": _mutated(agendas__the_magpie__moves__0__robs="yes"),
    "robs without a premise selector": _mutated(
        agendas__the_magpie__moves__1__robs=True),
    "two moves with one id": _mutated(
        agendas__the_magpie__moves__1__id="lift_a_shiny"),
    "a wanted gate on a band the Law does not have": _mutated(
        agendas__the_magpie__reactions__1__on={"wanted": {"min": "beloved"}}),
    "a reported_to gate on someone unscheduled": _mutated(
        agendas__the_magpie__reactions__0__on={"reported_to": {"npc": "npc_nobody"}}),
    "not valid YAML": "agendas: [unclosed",
}


@pytest.mark.parametrize("fault", sorted(MALFORMED))
def test_a_malformed_file_fails_naming_itself(tmp_path: Path, fault: str) -> None:
    paths = _paths(tmp_path, MALFORMED[fault])
    with story(paths):
        with pytest.raises(ValueError) as caught:
            agendas.spec()
        assert paths["agendas"] in str(caught.value), caught.value


# Final fix C (review M4): the secret is a schema invariant. A trace -- private
# or public -- may not carry any role candidate's display name or declared
# alias, in any seed: the mask guards only the seed's chosen NPC, so a trace
# naming another candidate would reach the narrator unmasked, and one naming
# the chosen candidate is the link itself.
NAMED_IN_A_TRACE: dict[str, Any] = {
    "a candidate's display name in a private trace": {
        "text": "Silas Crook's man was asking after you", "where": SQUARE},
    "a candidate's display name in a public trace": {
        "text": "Word is Lady Imelda sent for the watch", "where": SQUARE, "public": True},
    "a declared alias in a trace": {
        "text": "Silas was seen near the square", "where": SQUARE},
}


def _silas_agenda(trace: dict[str, Any]) -> dict[str, Any]:
    """The contract plus a Silas-owned agenda whose one move leaves ``trace``,
    and an alias for Silas on the Magpie's mask."""
    doc = _mutated()
    doc["roles"]["magpie"]["mask"]["aliases"] = {"npc_silas": ["Silas"]}
    doc["agendas"]["silas_rise"] = {
        "owner": "npc_silas", "goal": "rise", "clock": "magpie_spree",
        "moves": [{"id": "whisper", "every_hours": 24, "trace": dict(trace)}],
    }
    return doc


@pytest.mark.parametrize("fault", sorted(NAMED_IN_A_TRACE))
def test_a_trace_naming_a_role_candidate_is_refused(tmp_path: Path, fault: str) -> None:
    paths = _paths(tmp_path, _silas_agenda(NAMED_IN_A_TRACE[fault]))
    with story(paths):
        with pytest.raises(ValueError) as caught:
            agendas.spec()
    message = str(caught.value)
    assert paths["agendas"] in message, message
    assert "names a role candidate" in message, message


def test_a_trace_naming_nobody_in_particular_loads(tmp_path: Path) -> None:
    """The control: the same Silas-owned agenda with an impersonal trace, and
    words that are only part of a name ("crooked" is not "Silas Crook")."""
    trace = {"text": "a crooked chalk mark on the wall, and a lady's glove underfoot",
             "where": SQUARE}
    with story(_paths(tmp_path, _silas_agenda(trace))):
        assert "silas_rise" in agendas.spec()["agendas"]


def test_a_bare_on_key_is_refused_with_a_hint_to_quote_it(tmp_path: Path) -> None:
    """Final fix D. YAML 1.1 reads a bare ``on:`` as the boolean true, so the
    reaction arrives keyed ``True`` with no ``on``; the loader says so, and
    how to fix it, instead of "a reaction needs an `on` trigger"."""
    text = yaml.safe_dump(AGENDAS_SPEC, sort_keys=False).replace("'on':", "on:")
    assert "'on'" not in text and "\n      on:" in text
    paths = _paths(tmp_path, text)
    with story(paths):
        with pytest.raises(ValueError) as caught:
            agendas.spec()
    message = str(caught.value)
    assert paths["agendas"] in message, message
    assert '"on":' in message and "quote" in message, message


@pytest.mark.parametrize("where", ["when", "on", "unmask_when"])
def test_a_ledger_predicate_is_refused_because_the_pass_has_no_ledger(
    tmp_path: Path, where: str
) -> None:
    """``disposition`` needs a StoryLedger; ``advance_time`` holds none, so it
    would be False forever -- a gate that loads and never opens."""
    gate = {"disposition": {"npc": "npc_ardane", "min": 1}}
    doc = {
        "when": _mutated(agendas__the_captain__moves__0__when=gate),
        "on": _mutated(agendas__the_magpie__reactions__1__on=gate),
        "unmask_when": _mutated(roles__magpie__mask={"instead": "the Magpie",
                                                     "unmask_when": gate}),
    }[where]
    paths = _paths(tmp_path, doc)
    with story(paths):
        with pytest.raises(ValueError) as caught:
            agendas.spec()
    message = str(caught.value)
    assert paths["agendas"] in message
    assert "no ledger" in message.replace(paths["agendas"], "")


def test_a_premise_selector_needs_premises(tmp_path: Path) -> None:
    doc = _mutated(agendas__the_magpie__moves__1__robs=False)
    doc["agendas"]["the_magpie"]["moves"][1]["select"] = {"witness": {"knows": "magpie"}}
    paths = _paths(tmp_path, doc, with_premises=False)
    with story(paths):
        with pytest.raises(ValueError) as caught:
            agendas.spec()
    message = str(caught.value)
    assert paths["agendas"] in message
    assert "`paths.premises`" in message.replace(paths["agendas"], "")


def _lawless_doc() -> dict[str, Any]:
    """The contract with every Law reference taken out."""
    doc = copy.deepcopy(AGENDAS_SPEC)
    magpie = doc["agendas"]["the_magpie"]
    magpie["moves"][0]["effects"] = []
    magpie["moves"] = magpie["moves"][:1]
    magpie["reactions"] = []
    return doc


def test_the_lawless_contract_loads(tmp_path: Path) -> None:
    with story(_paths(tmp_path, _lawless_doc(), lawful=False)):
        assert not law.declared()
        assert list(agendas.spec()["agendas"]) == ["the_magpie", "the_captain"]


@pytest.mark.parametrize("fault", ["witness selector", "wanted", "reported_to"])
def test_the_law_references_need_a_law(tmp_path: Path, fault: str) -> None:
    doc = _lawless_doc()
    magpie = doc["agendas"]["the_magpie"]
    if fault == "witness selector":
        magpie["moves"].append({"id": "w", "every_hours": 6,
                                "select": {"witness": {"knows": "self"}}})
    elif fault == "wanted":
        magpie["reactions"] = [{"id": "r", "on": {"wanted": {"min": "hunted"}}}]
    else:
        magpie["reactions"] = [{"id": "r", "on": {"reported_to": {"npc": "npc_ardane"}}}]
    paths = _paths(tmp_path, doc, lawful=False)
    with story(paths):
        with pytest.raises(ValueError) as caught:
            agendas.spec()
    message = str(caught.value)
    assert paths["agendas"] in message
    assert "`paths.law`" in message.replace(paths["agendas"], "")


def test_a_declared_file_that_is_missing_is_a_broken_install(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    missing = str(tmp_path / "nowhere.yaml")
    with story({**paths, "agendas": missing}):
        with pytest.raises(ValueError) as caught:
            agendas.spec()
    assert missing in str(caught.value)


def test_the_spec_memo_is_dropped_on_a_story_swap() -> None:
    from engine.games.caches import NULLED_ATTRIBUTES

    assert ("engine.world.agendas", "_SPEC_CACHE") in NULLED_ATTRIBUTES


def test_the_agenda_predicates_are_part_of_the_grammar() -> None:
    assert "engine.world.agendas" in quests._GRAMMAR_MODULES
    names = set(quests.predicate_names())
    assert {"wanted", "reported_to", "agenda_hit", "premise_robbed"} <= names


# ---------------------------------------------------------------------------
# Roles: chosen by the seed, derived on read
# ---------------------------------------------------------------------------


def test_a_role_survives_a_save_and_load(declared: Path) -> None:
    state = _world(7)
    chosen = agendas.role(state, "magpie")
    assert chosen in CANDIDATES
    loaded = GameState.from_dict(state.to_save_dict())
    assert agendas.role(loaded, "magpie") == chosen
    # Derived, never stored: the save holds no trace of who it is.
    assert chosen not in repr(state.to_save_dict()["agendas"])
    assert state.agendas == {}


def test_every_candidate_is_chosen_by_some_seed(declared: Path) -> None:
    chosen = {agendas.role(GameState(rng_seed=seed), "magpie") for seed in range(30)}
    assert chosen == set(CANDIDATES)


def test_the_same_seed_chooses_the_same_npc(declared: Path) -> None:
    for seed in range(10):
        assert agendas.role(GameState(rng_seed=seed), "magpie") == agendas.role(
            GameState(rng_seed=seed), "magpie")


def test_an_unknown_role_is_nobody(declared: Path) -> None:
    assert agendas.role(GameState(rng_seed=1), "phantom") == ""


def test_owner_of_resolves_a_role_or_a_named_npc(declared: Path) -> None:
    state = GameState(rng_seed=11)
    assert agendas.owner_of(state, "the_magpie") == agendas.role(state, "magpie")
    assert agendas.owner_of(state, "the_captain") == "npc_ardane"
    assert agendas.owner_of(state, "no_such_agenda") == ""


# ---------------------------------------------------------------------------
# Undeclared: inert end to end
# ---------------------------------------------------------------------------


def test_an_undeclared_story_has_no_agendas() -> None:
    assert not agendas.declared()
    assert agendas.spec() == {}
    state = GameState(location_id=SQUARE)
    assert state.agendas == {}
    assert agendas.role(state, "magpie") == ""
    assert agendas.owner_of(state, "the_magpie") == ""
    refused = apply_effect(state, {"type": "agenda_mark", "last_hour": 5})
    assert refused["ok"] is False and refused["message"]
    assert state.agendas == {}


def test_the_flagship_save_round_trips_with_empty_agendas() -> None:
    from engine.games import registry

    registry.activate("clockwork-dark")
    try:
        assert not agendas.declared()
        state = GameState()
        data = state.to_save_dict()
        assert data["agendas"] == {}
        assert GameState.from_dict(data).agendas == {}
        # A save written before agendas existed loads as "nothing has moved".
        data.pop("agendas")
        assert GameState.from_dict(data).agendas == {}
        assert "agendas" not in state.to_client_dict()
    finally:
        registry.deactivate()


def test_a_story_with_the_law_and_jobs_but_no_agendas_is_untouched(tmp_path: Path) -> None:
    with story(_paths(tmp_path, with_agendas=False, with_jobs=True)):
        assert law.declared() and not agendas.declared()
        state = _world(42)
        assert state.agendas == {}
        assert state.to_save_dict()["agendas"] == {}
        assert "agendas" not in state.to_client_dict()
        assert agendas.role(state, "magpie") == ""


# ---------------------------------------------------------------------------
# agenda_mark: the only writer of the bookkeeping
# ---------------------------------------------------------------------------


def test_agenda_mark_writes_the_bookkeeping(declared: Path) -> None:
    state = GameState(rng_seed=3)
    out = apply_effect(state, {"type": "agenda_mark", "last_hour": 49,
                               "move": "the_magpie:lift_a_shiny", "hour": 49})
    assert out["ok"], out
    assert state.agendas["last_hour"] == 49
    assert state.agendas["moves"] == {"the_magpie:lift_a_shiny": 49}
    out = apply_effect(state, {"type": "agenda_mark", "fired": "the_magpie:the_captain_hears",
                               "truth": {"the_magpie:the_captain_hears": True}})
    assert out["ok"], out
    assert state.agendas["fired"] == ["the_magpie:the_captain_hears"]
    assert state.agendas["truth"] == {"the_magpie:the_captain_hears": True}
    # Firing twice records once.
    apply_effect(state, {"type": "agenda_mark", "fired": "the_magpie:the_captain_hears"})
    assert state.agendas["fired"] == ["the_magpie:the_captain_hears"]
    # A receipt of bookkeeping never reaches the prose.
    assert out["hidden"] is True and out["text"] == ""


@pytest.mark.parametrize("effect", [
    {"type": "agenda_mark", "move": "the_magpie:no_such_move", "hour": 3},
    {"type": "agenda_mark", "move": "the_magpie:lift_a_shiny"},
    {"type": "agenda_mark", "fired": "the_magpie:no_such_reaction"},
    {"type": "agenda_mark", "fired": "the_magpie:hunted"},
    {"type": "agenda_mark", "truth": {"nobody:nothing": True}},
    {"type": "agenda_mark", "truth": {"the_magpie:hunted": "yes"}},
    {"type": "agenda_mark", "last_hour": "soon"},
    {"type": "agenda_mark"},
])
def test_agenda_mark_refuses_what_it_cannot_record(declared: Path, effect: dict) -> None:
    state = GameState(rng_seed=3)
    out = apply_effect(state, effect)
    assert out["ok"] is False and out["message"], out
    assert state.agendas == {}


def test_agenda_mark_never_walks_the_pass_backwards(declared: Path) -> None:
    state = GameState(rng_seed=3)
    assert apply_effect(state, {"type": "agenda_mark", "last_hour": 40})["ok"]
    out = apply_effect(state, {"type": "agenda_mark", "last_hour": 30})
    assert out["ok"] is False and out["message"]
    assert state.agendas["last_hour"] == 40


# ---------------------------------------------------------------------------
# Premise owners
# ---------------------------------------------------------------------------


def test_an_anchor_declares_its_owner(tmp_path: Path) -> None:
    mill = {**MILL_HOUSE, "owner": "npc_imelda"}
    with story(_paths(tmp_path, **{"anchors/mill_house.yaml": mill})):
        state = _world(42, MARKET)
        assert premises.owner(state, "prem_mill_house") == "npc_imelda"


def test_an_anchor_owner_must_be_a_scheduled_npc(tmp_path: Path) -> None:
    mill = {**MILL_HOUSE, "owner": "npc_nobody"}
    with story(_paths(tmp_path, **{"anchors/mill_house.yaml": mill})):
        with pytest.raises(ValueError) as caught:
            premises.definitions()
    assert "mill_house.yaml" in str(caught.value)


def test_a_premise_without_a_declared_owner_is_owned_by_its_first_member(
    declared: Path,
) -> None:
    state = _world(42)
    generated = premises.get(state, "prem_edgewood_square_1")
    assert premises.owner(state, "prem_edgewood_square_1") == generated["household"][0]
    anchor = premises.get(state, "prem_mill_house")
    assert premises.owner(state, "prem_mill_house") == anchor["household"][0]
    assert premises.owner(state, "prem_nowhere") == ""


# ---------------------------------------------------------------------------
# The predicates
# ---------------------------------------------------------------------------


def _holds(state: GameState, condition: Any) -> bool:
    return quests.evaluate_condition(state, condition)


def test_wanted_reads_the_band_here(declared: Path) -> None:
    state = _world(5)
    assert not _holds(state, {"wanted": {"min": "noticed"}})
    # fencing is severity 2 at precision 1.0: exactly `noticed` in the village.
    assert apply_effect(state, {"type": "report", "deed": "fencing", "guise": "self",
                                "jurisdiction": "village", "precision": 1.0})["ok"]
    assert _holds(state, {"wanted": {"min": "noticed"}})
    assert _holds(state, {"wanted": {"min": "unknown"}})
    assert not _holds(state, {"wanted": {"min": "sought"}})
    # Another jurisdiction has heard nothing.
    assert not _holds(state, {"wanted": {"min": "noticed", "jurisdiction": "town"}})
    # The watch takes the Magpie for you: the heat is shared.
    assert _holds(state, {"wanted": {"min": "noticed", "guise": "magpie"}})
    assert not _holds(state, {"wanted": {"min": "noticed", "guise": "porter"}})
    # An unknown band is unmet, never open.
    assert not _holds(state, {"wanted": {"min": "beloved"}})


def test_wanted_is_false_without_a_law(tmp_path: Path) -> None:
    with story(_paths(tmp_path, _lawless_doc(), lawful=False)):
        assert not _holds(GameState(), {"wanted": {"min": "unknown"}})


def _witness(state: GameState, npc: str, guise: str = "self",
             where: str = SQUARE) -> str:
    row = apply_effect(state, {"type": "witness", "deed": "fencing", "guise": guise,
                               "npc": npc, "where": where})
    assert row["ok"], row
    return str(row["deed_id"])


def test_reported_to_needs_a_live_row_held_by_that_npc(declared: Path) -> None:
    state = _world(5)
    gate = {"reported_to": {"npc": "npc_ardane", "guise": "magpie"}}
    assert not _holds(state, gate)
    _witness(state, "npc_wren", guise="magpie")
    assert not _holds(state, gate), "someone else holding it is not the captain"
    deed = _witness(state, "npc_ardane", guise="magpie")
    assert _holds(state, gate)
    # The watch links the Magpie to your own face, so the default guise holds too.
    assert _holds(state, {"reported_to": {"npc": "npc_ardane"}})
    assert not _holds(state, {"reported_to": {"npc": "npc_ardane", "guise": "porter"}})
    # Discharged: the row is gone and the gate with it.
    assert apply_effect(state, {"type": "law_discharge", "deed_ids": [deed]})["ok"]
    assert not _holds(state, gate)


def test_reported_to_ignores_a_quashed_deed(declared: Path) -> None:
    state = _world(5)
    deed = _witness(state, "npc_ardane")
    assert apply_effect(state, {"type": "report", "deed": "fencing", "guise": "self",
                                "jurisdiction": "village", "deed_id": deed})["ok"]
    assert _holds(state, {"reported_to": {"npc": "npc_ardane"}})
    assert apply_effect(state, {"type": "quash_reports", "jurisdiction": "village"})["ok"]
    assert not _holds(state, {"reported_to": {"npc": "npc_ardane"}})


def test_reported_to_is_false_without_a_law(tmp_path: Path) -> None:
    with story(_paths(tmp_path, _lawless_doc(), lawful=False)):
        assert not _holds(GameState(), {"reported_to": {"npc": "npc_ardane"}})


def test_agenda_hit_reads_the_hits(declared: Path) -> None:
    state = _world(5)
    assert not _holds(state, {"agenda_hit": {}})
    # Seeded directly: the writer (`agenda_hit`, the effect) lands in Task 2.
    state.agendas["hits"] = [{"agenda": "the_magpie", "premise": "prem_mill_house",
                              "hour": 49}]
    assert _holds(state, {"agenda_hit": {}})
    assert _holds(state, {"agenda_hit": {"agenda": "the_magpie"}})
    assert _holds(state, {"agenda_hit": {"premise": "prem_mill_house"}})
    assert _holds(state, {"agenda_hit": {"district": MARKET}})
    assert not _holds(state, {"agenda_hit": {"district": SQUARE}})
    assert not _holds(state, {"agenda_hit": {"agenda": "the_captain"}})


def test_premise_robbed_filters_on_the_owner(tmp_path: Path) -> None:
    mill = {**MILL_HOUSE, "owner": "npc_imelda"}
    paths = _paths(tmp_path, with_jobs=True, **{"anchors/mill_house.yaml": mill})
    with story(paths):
        state = _world(42, MARKET)
        assert not _holds(state, {"premise_robbed": {"owner": "npc_imelda"}})
        _rob(state, "prem_mill_house")
        assert _holds(state, {"premise_robbed": {"owner": "npc_imelda"}})
        assert not _holds(state, {"premise_robbed": {"owner": "npc_silas"}})
        # The other filters still bind beside it.
        assert not _holds(state, {"premise_robbed": {"owner": "npc_imelda",
                                                     "district": SQUARE}})
