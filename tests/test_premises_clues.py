"""
The Magpie's trail (v0.16 Task 6, HUE & CRY spec §3).

THE SHAPE. ``paths.premises`` may hold ``clues.yaml`` (engine/world/clues.py).
At world generation the seed lays a trail through the GENERATED houses, on the
new ``CLUES`` stream after every PREMISES draw: ``trail`` clues pointing at the
seed's real Magpie (``agendas.role``, read, never drawn) and ``herrings`` for
each of the other two. Casing reveals a clue house, last, as "something here
doesn't belong"; the score sees the clue cased or not; a job carried out keeps
it -- ``clue_found:<id>``, a ``clue`` ledger fact, and the veiled ``evidence``
meter one higher. ``clues_favour`` is a condition over the found clues, never
rendered.

WHAT THESE TESTS HOLD. The trail follows the seed and moves no house; every
candidate's trail is laid and findable in 40 seeds; a clue is rendered to the
narrator only once found, and names nobody; the GM region never names the
Magpie before the reveal; the predicate is never rendered; a replay is
identical; a save from before the trail loads and plays; and the loader
refuses a clue that names or points at the wrong people.
"""

from __future__ import annotations

import copy
import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from engine.games import registry

CANDIDATES = ("npc_wren", "npc_silas", "npc_imelda")
#: Every name, alias and trade word that would point at a candidate
#: (tests/test_hue_and_cry.py's `_CANDIDATE_WORDS`): a clue describes a thing,
#: never the person or their calling.
CANDIDATE_WORDS = ("wren", "silas", "crook", "imelda", "lamplighter", "dapper", "vessaline")
SEEDS = range(40)


@pytest.fixture()
def hue():
    registry.activate("hue-and-cry")
    yield


def _city(seed: int):
    from engine.game.procgen import new_game_state

    return new_game_state(seed=seed)


def _magpie(state) -> str:
    from engine.world import agendas

    return agendas.role(state, "magpie")


def _clue_houses(state) -> dict[str, dict[str, Any]]:
    """premise id -> premise, for every house holding a clue."""
    return {p["id"]: p for p in state.procgen.premises if p.get("clue")}


class _Roll:
    def __init__(self, degree: str) -> None:
        self.degree = degree
        self.margin = {"success": 1, "failure": -8}[degree]

    @property
    def success(self) -> bool:
        return self.degree == "success"


def _burgle(state, premise_id: str, monkeypatch, *, ledger=None, until: str = "") -> list:
    """Open a job on ``premise_id`` from its district and walk it with every
    roll a success, returning every stage receipt. ``until`` stops before
    that stage is played."""
    from engine.game.clock import set_clock
    from engine.world import jobs, premises

    prem = premises.get(state, premise_id)
    state.location_id = prem["district"]
    set_clock(state, day=state.world_day, hour=13)
    monkeypatch.setattr(jobs, "_check", lambda s, skill, band: _Roll("success"))
    opened = jobs.begin(state, premise_id)
    assert opened["ok"] is True, opened
    out = []
    for _ in range(20):
        if jobs.active(state) is None:
            break
        if until and jobs.current_stage(state) == until:
            break
        receipt = jobs.resolve_stage(state, jobs.approaches(state)[0][0], ledger=ledger)
        assert receipt["ok"] is True, receipt
        out.append(receipt)
    return out


# ---------------------------------------------------------------------------
# Laying the trail
# ---------------------------------------------------------------------------


def test_hue_and_cry_lays_a_trail(hue) -> None:
    from engine.world import clues

    assert clues.declared()
    sp = clues.spec()
    assert sp["role"] == "magpie" and sp["candidates"] == list(CANDIDATES)
    assert sp["evidence"] == "evidence"
    assert (sp["trail"], sp["herrings"]) == (4, 2)
    for npc in CANDIDATES:
        assert sum(r["points_to"] == npc for r in sp["clues"].values()) >= 4, npc


@pytest.mark.slow
def test_every_candidates_trail_is_laid_in_every_seed(hue) -> None:
    """40 seeds: the real Magpie's four clues and two for each other candidate,
    each in its own generated house in a district a thief can walk to."""
    from engine.game.locations import LOCATIONS
    from engine.world import clues

    rows = clues.spec()["clues"]
    magpies = set()
    for seed in SEEDS:
        state = _city(seed)
        magpie = _magpie(state)
        magpies.add(magpie)
        assert all("clue" in p for p in state.procgen.premises), seed
        houses = _clue_houses(state)
        placed = [p["clue"] for p in houses.values()]
        assert len(placed) == len(set(placed)) == 8, seed
        counts = {npc: sum(rows[c]["points_to"] == npc for c in placed) for npc in CANDIDATES}
        assert counts[magpie] == 4, (seed, counts)
        assert all(counts[n] == 2 for n in CANDIDATES if n != magpie), (seed, counts)
        for prem in houses.values():
            assert not prem["anchor"], (seed, prem["id"])
            assert not LOCATIONS[prem["district"]].get("secret"), (seed, prem["id"])
    assert magpies == set(CANDIDATES)


def test_the_trail_follows_the_seed(hue) -> None:
    from engine.game.procgen import generate_world

    def trail(seed: int) -> dict[str, str]:
        return {p["id"]: p["clue"] for p in generate_world(seed).premises if p["clue"]}

    assert trail(7) == trail(7)
    assert len({tuple(sorted(trail(s).items())) for s in range(10)}) == 10


def test_the_trail_moves_no_house(hue, monkeypatch) -> None:
    """Drawn after every PREMISES draw on its own stream: with the trail struck
    out, the city is the city generated without one."""
    from engine.game.procgen import generate_world
    from engine.world import clues

    laid = {s: generate_world(s).to_dict() for s in (1, 7, 42)}
    monkeypatch.setattr(clues, "place", lambda seed, prems: None)
    for seed, world in laid.items():
        bare = generate_world(seed).to_dict()
        for prem in world["premises"]:
            assert prem.pop("clue") is not None
        assert world == bare, seed


def test_the_trail_draws_nothing_from_premises_or_the_run(hue) -> None:
    """The CLUES stream is its own, and a run's counters start untouched.
    Recomputed here from the documented order -- the chosen candidate's rows,
    each other candidate's in declared order, then the sorted generated
    houses -- on `stable_rng(seed, CLUES)`, so a placement on any other
    stream (PREMISES included) fails."""
    from engine.game import rng
    from engine.world import agendas, clues

    assert rng.CLUES == "clues" and rng.CLUES != rng.PREMISES
    sp = clues.spec()
    for seed in (3, 8, 21):
        state = _city(seed)
        assert "clues" not in state.rng_counters
        draw = rng.stable_rng(seed, rng.CLUES)
        chosen = agendas.role_for_seed(seed, "magpie")
        assert chosen == _magpie(state)

        def rows(npc: str) -> list[str]:
            return sorted(c for c, r in sp["clues"].items() if r["points_to"] == npc)

        picked = draw.sample(rows(chosen), sp["trail"])
        for npc in CANDIDATES:
            if npc != chosen:
                picked += draw.sample(rows(npc), sp["herrings"])
        houses = sorted(p["id"] for p in state.procgen.premises if not p["anchor"])
        expected = dict(zip(draw.sample(houses, len(picked)), picked))
        assert {p["id"]: p["clue"] for p in state.procgen.premises if p["clue"]} == expected


# ---------------------------------------------------------------------------
# Finding it
# ---------------------------------------------------------------------------


def test_casing_to_the_end_says_something_here_doesnt_belong(hue) -> None:
    """The hint is the LAST intel, and the rest keep the order they had."""
    from engine.world import clues, premises

    state = _city(5)
    prem = next(iter(_clue_houses(state).values()))
    order = [row["id"] for row in premises.intel_for(state, prem["id"])]
    assert order[-1] == premises.CLUE_HINT
    assert premises.intel_for(state, prem["id"])[-1]["text"] == "something here doesn't belong"
    bare = dict(prem, clue="")
    assert premises._ordered_ids(state, bare) == order[:-1]
    assert clues.row_for(bare) == {}

    state.location_id = prem["district"]
    for _ in range(len(order)):
        assert premises.case(state, prem["id"])["ok"] is True
    assert premises.known(state, prem["id"]) == order
    assert premises.case(state, prem["id"])["ok"] is False


def test_a_clue_carried_out_is_found(hue, monkeypatch) -> None:
    """Uncased: the score sees it and says so; the getaway keeps it -- the flag,
    the ledger fact and the evidence meter, all written as effects."""
    from engine.agents import prompts
    from engine.memory.ledger import StoryLedger
    from engine.state.active import store_for
    from engine.world import clues

    state = _city(5)
    prem = next(iter(_clue_houses(state).values()))
    row = clues.row_for(prem)
    ledger = StoryLedger()
    receipts = _burgle(state, prem["id"], monkeypatch, ledger=ledger)
    score = next(r for r in receipts if r["stage"] == "score")
    getaway = receipts[-1]
    assert score["clue"] == row["text"] and "clue_taken" not in score
    assert getaway["outcome"] in ("clean", "noisy") and getaway["closed"]
    assert getaway["clue_taken"] == row["text"] and getaway["evidence"] == "faint"
    assert state.flags.get(clues.found_flag(row["id"])) is True
    assert clues.found(state) == [row["id"]]
    assert store_for(state).get("evidence") == 1
    facts = [f for f in ledger.facts if f.kind == "clue"]
    # The WHOLE clue, first: the ledger clips a fact at MAX_FACT_CHARS, so the
    # house's name (which may be long) goes after it (fix round 1).
    assert len(facts) == 1 and facts[0].source == "engine"
    assert facts[0].text.lower().startswith(row["text"].lower())

    seen = prompts._sum_job_stage(score)
    kept = prompts._sum_job_stage(getaway)
    assert row["text"] in seen and "yours only if you get clear" in seen
    assert row["text"] in kept and "faint" in kept
    # The meter rises for a red herring too, so the line must never say the
    # evidence is against the REAL Magpie -- after one herring that is a lie.
    assert "real magpie" not in kept.lower()
    for line in (seen, kept, facts[0].text):
        assert not any(w in line.lower() for w in CANDIDATE_WORDS), line
        assert row["points_to"] not in line and row["id"] not in line


def test_a_second_clue_raises_the_band(hue, monkeypatch) -> None:
    from engine.state.active import store_for

    state = _city(5)
    first, second = list(_clue_houses(state))[:2]
    _burgle(state, first, monkeypatch)
    out = _burgle(state, second, monkeypatch)
    assert out[-1]["evidence"] == "some"
    assert store_for(state).get("evidence") == 2


def test_a_job_that_is_not_carried_out_keeps_no_clue(hue, monkeypatch) -> None:
    from engine.world import clues, jobs

    state = _city(5)
    prem = next(iter(_clue_houses(state).values()))
    receipts = _burgle(state, prem["id"], monkeypatch, until="getaway")
    assert any(r.get("clue") for r in receipts)
    assert jobs.abort(state)["ok"] is True
    assert clues.found(state) == []
    # Not robbed, so the thief may come back for it -- and it is still there.
    out = _burgle(state, prem["id"], monkeypatch)
    assert out[-1]["clue_taken"]


def test_an_emptied_house_still_gives_its_clue(hue, monkeypatch) -> None:
    """An agenda that robbed the house first took shine, not the clue."""
    from engine.game.effects import apply_effect
    from engine.world import clues

    state = _city(5)
    prem = next(iter(_clue_houses(state).values()))
    assert apply_effect(state, {"type": "agenda_hit", "agenda": "the_magpie",
                                "premise": prem["id"], "hour": 1})["ok"] is True
    out = _burgle(state, prem["id"], monkeypatch)
    assert out[-1].get("emptied") and out[-1]["clue_taken"]
    assert len(clues.found(state)) == 1


@pytest.mark.slow
def test_every_candidates_trail_is_findable_in_40_seeds(hue, monkeypatch) -> None:
    """For every seed, one of each candidate's clue houses is burgled and its
    clue kept: every trail can be walked, the herrings' included."""
    from engine.world import clues

    rows = clues.spec()["clues"]
    for seed in SEEDS:
        state = _city(seed)
        state.hp = 99
        houses = _clue_houses(state)
        for npc in CANDIDATES:
            premise_id = next(pid for pid, p in sorted(houses.items())
                              if rows[p["clue"]]["points_to"] == npc)
            out = _burgle(state, premise_id, monkeypatch)
            assert out[-1].get("clue_taken"), (seed, npc, out[-1])
        assert clues.tally(state) == {n: 1 for n in CANDIDATES}, seed


# ---------------------------------------------------------------------------
# The predicate
# ---------------------------------------------------------------------------


def _holds(state, condition) -> bool:
    from engine.game.quests import evaluate_condition

    return bool(evaluate_condition(state, condition))


def _find(state, *clue_ids: str) -> None:
    from engine.game.effects import apply_effect
    from engine.world import clues

    for cid in clue_ids:
        apply_effect(state, {"type": "flag", "flag": clues.found_flag(cid)})


def test_clues_favour_reads_the_lead(hue) -> None:
    state = _city(5)
    ask = lambda npc, least=1: _holds(state, {"clues_favour": {"npc": npc, "min": least}})  # noqa: E731
    assert not any(ask(n) for n in CANDIDATES)
    _find(state, "wick_ends")
    assert ask("npc_wren") and not ask("npc_silas") and not ask("npc_wren", 2)
    _find(state, "pie_papers")
    assert not ask("npc_wren") and not ask("npc_silas")      # a tie favours nobody
    _find(state, "lamp_soot")
    assert ask("npc_wren", 2) and not ask("npc_wren", 3)
    for bad in ({"npc": "npc_ardane"}, {"npc": "npc_wren", "min": 0},
                {"npc": "npc_wren", "min": True}, {"npc": "npc_wren", "min": "1"}, "npc_wren"):
        assert not _holds(state, {"clues_favour": bad}), bad


def test_clues_favour_can_set_candidates_aside(hue) -> None:
    """v0.16 T7: ``excluding`` counts the lead among the OTHER candidates, so
    a candidate already named wrongly stops blocking the next accusation."""
    state = _city(5)
    ask = lambda npc, *out: _holds(  # noqa: E731
        state, {"clues_favour": {"npc": npc, "excluding": list(out)}})
    _find(state, "pie_papers", "company_chit", "wick_ends")  # silas 2, wren 1
    assert ask("npc_silas") and not ask("npc_wren")
    assert ask("npc_wren", "npc_silas")                # silas set aside: wren leads
    assert not ask("npc_imelda", "npc_silas")          # imelda has nothing
    assert not ask("npc_silas", "npc_silas")           # an excluded npc never leads
    assert ask("npc_wren", "npc_silas", "npc_imelda")
    for bad in ("npc_silas", [7], [""], {"npc": "x"}):
        assert not _holds(state, {"clues_favour": {"npc": "npc_wren", "excluding": bad}}), bad


def test_a_clue_carried_out_raises_the_fresh_flag(hue, monkeypatch) -> None:
    """v0.16 T7: ``fresh_flag`` (clues.yaml) is set by every clue carried out,
    so content may clear it and later ask "a clue since then?"."""
    from engine.game.effects import apply_effect
    from engine.world import clues

    assert clues.spec()["fresh_flag"] == "clue_fresh"
    state = _city(5)
    state.hp = 99
    assert not state.flags.get("clue_fresh")
    houses = sorted(_clue_houses(state))
    _burgle(state, houses[0], monkeypatch)
    assert state.flags.get("clue_fresh") is True
    apply_effect(state, {"type": "flag", "flag": "clue_fresh", "value": False})
    _burgle(state, houses[1], monkeypatch)
    assert state.flags.get("clue_fresh") is True


def test_clues_favour_holds_nowhere_without_a_trail() -> None:
    from engine.game.state import GameState
    from engine.world import clues

    assert not clues.declared()
    assert not _holds(GameState(), {"clues_favour": {"npc": "npc_wren"}})


def test_clues_favour_and_points_to_never_reach_a_prompt(hue) -> None:
    """A condition only, like `agenda_role`: asking it changes no prompt block,
    and nothing in the prompt layer reads the tally or where a clue points."""
    from engine.agents import prompts

    state = _city(11)
    _find(state, "wick_ends", "violet_wax", "lamp_soot")
    before = prompts.world_state_block(state, {})
    for npc in CANDIDATES:
        _holds(state, {"clues_favour": {"npc": npc}})
    assert prompts.world_state_block(state, {}) == before
    assert "clues_favour" not in before
    root = Path(__file__).resolve().parents[1] / "engine" / "agents"
    for source in root.rglob("*.py"):
        text = source.read_text(encoding="utf-8")
        for word in ("clues_favour", "points_to", "tally("):
            assert word not in text, (source, word)


# ---------------------------------------------------------------------------
# Secrecy
# ---------------------------------------------------------------------------


def test_no_clue_names_or_sexes_anybody(hue) -> None:
    from engine.world import clues

    pronoun = re.compile(r"\b(?:she|he|her|his|hers|him|herself|himself|lady|gentleman)\b")
    for row in clues.spec()["clues"].values():
        lowered = row["text"].lower()
        assert not any(w in lowered for w in CANDIDATE_WORDS), row
        assert not pronoun.search(lowered), row
        assert row["id"] not in row["text"]


#: Dress and grooming a reader codes as a man's or a woman's. The Watch takes
#: the PLAYER for the Magpie, so a clue that sexes the Magpie sexes the player
#: too (prompts/storyteller.md: "they"), and rules a suspect in or out besides.
#: A clue points at its suspect through trade, place or habit instead.
#: Whole words only, so ordinary text does not trip it: "stays" (a corset, but
#: far more often the verb) is left out, and "powder" is listed only as the
#: toilette's ("face powder", "hair powder", "powder puff"), not the gunner's.
#: v0.16 T7 added "scented" (the matcher's `s?` never reached it) and the
#: jewellery a reader sexes: pearl, locket, necklace, paste.
GENDERED_DRESS = (
    "waistcoat", "cravat", "cufflink", "pomade", "barber", "shaving", "razor", "beard",
    "moustache", "whisker", "cane", "walking-stick", "top hat", "breeches", "trouser",
    "glove", "kid glove", "skirt", "petticoat", "bonnet", "corset", "bodice",
    "garter", "stocking", "hairpin", "hair-pin", "ribbon", "lace cap", "fan", "rouge",
    "face powder", "hair powder", "powder puff", "perfume", "scent", "scented", "lipstick",
    "earring", "brooch", "reticule", "muff", "shawl", "gown", "dress", "fichu", "chemise",
    "pearl", "locket", "necklace", "paste",
)


def test_no_clue_is_a_mans_or_a_womans_thing(hue) -> None:
    """T6 fix round 1: five rows (a waistcoat's thread, a paste cufflink, a
    cane's dent, bay rum and pomade, a kid glove's button) read as a
    gentleman's or a lady's. T7: "the costly scented kind" of sealing-wax was a
    sixth, missed because "scented" was not matched. The words are matched
    whole, so "fancy" is not "fan"."""
    from engine.world import clues

    found = []
    for row in clues.spec()["clues"].values():
        lowered = row["text"].lower()
        found += [(row["id"], w) for w in GENDERED_DRESS
                  if re.search(rf"\b{re.escape(w)}s?\b", lowered)]
    assert found == [], found


def test_a_house_whose_clue_was_taken_hints_no_more(hue, monkeypatch) -> None:
    """Fix round 1: once the clue is carried out, casing, the district block
    and the board stop saying something here doesn't belong."""
    from engine.agents import prompts
    from engine.world import premises

    state = _city(5)
    prem = next(iter(_clue_houses(state).values()))
    state.location_id = prem["district"]
    for _ in range(len(premises.intel_for(state, prem["id"]))):
        premises.case(state, prem["id"])
    assert "doesn't belong" in prompts.district_block(state)
    _burgle(state, prem["id"], monkeypatch)
    state.location_id = prem["district"]
    assert premises.CLUE_HINT not in [r["id"] for r in premises.intel_for(state, prem["id"])]
    assert "doesn't belong" not in prompts.district_block(state)
    assert "doesn't belong" not in str(state.to_client_dict())


def test_nothing_of_a_clue_reaches_the_narrator_before_it_is_found(hue) -> None:
    """The district block and the casing board carry only what casing learned:
    the hint once cased to the end, never the clue's words or id."""
    from engine.agents import prompts
    from engine.world import clues, premises

    state = _city(5)
    prem = next(iter(_clue_houses(state).values()))
    row = clues.row_for(prem)
    state.location_id = prem["district"]

    def rendered() -> str:
        return prompts.world_state_block(state, {}) + prompts.district_block(state) + str(
            state.to_client_dict())

    for _ in range(len(premises.intel_for(state, prem["id"])) - 1):
        premises.case(state, prem["id"])
        text = rendered()
        assert row["text"] not in text and "doesn't belong" not in text
    premises.case(state, prem["id"])
    text = rendered()
    assert "something here doesn't belong" in prompts.district_block(state)
    assert row["text"] not in text and f"'{row['id']}'" not in text
    assert f'"{row["id"]}"' not in text


def test_the_gm_region_never_names_the_magpie_before_the_reveal(hue, monkeypatch) -> None:
    """Every clue found, in seeds that make each candidate the Magpie: the GM
    line names nobody until `magpie_unmasked`, and then names the right one."""
    from engine.agents import prompts
    from engine.game.effects import apply_effect
    from engine.world import clues, npc_sim

    gm = re.compile(r"GM ONLY.*", re.S)
    for magpie in CANDIDATES:
        seed = next(s for s in range(200) if _magpie(_city(s)) == magpie)
        state = _city(seed)
        _find(state, *(p["clue"] for p in _clue_houses(state).values()))
        assert sum(clues.tally(state).values()) == 8
        region = gm.search(prompts.world_state_block(state, {})).group(0).lower()
        assert not any(w in region for w in CANDIDATE_WORDS), (magpie, region)
        apply_effect(state, {"type": "flag", "flag": "magpie_unmasked"})
        region = gm.search(prompts.world_state_block(state, {})).group(0)
        assert npc_sim.display_name(magpie) in region


# ---------------------------------------------------------------------------
# Replay and saves
# ---------------------------------------------------------------------------


def test_a_burglary_replays_to_the_same_trail(hue, monkeypatch) -> None:
    from engine.world import clues

    def one():
        state = _city(9)
        first = sorted(_clue_houses(state))[0]
        _burgle(state, first, monkeypatch)
        return state

    a, b = one(), one()
    assert clues.found(a) == clues.found(b) and len(clues.found(a)) == 1
    one_save, other = a.to_save_dict(), b.to_save_dict()
    # A session id is minted per process-level session, not by the seed.
    one_save.pop("session_id"), other.pop("session_id")
    assert one_save == other


def test_a_save_carries_the_trail_and_what_was_found(hue, monkeypatch) -> None:
    from engine.game.state import GameState
    from engine.world import clues

    state = _city(9)
    _burgle(state, sorted(_clue_houses(state))[0], monkeypatch)
    loaded = GameState.from_dict(state.to_save_dict())
    assert _clue_houses(loaded).keys() == _clue_houses(state).keys()
    assert clues.found(loaded) == clues.found(state)
    assert clues.tally(loaded) == clues.tally(state)


def test_a_save_from_before_the_trail_loads_and_plays(hue, monkeypatch) -> None:
    """No `clue` key on any premise: no hint, no clue, no error -- and the
    houses it did hold burgle as they always did."""
    from engine.game.state import GameState
    from engine.world import clues, premises

    state = _city(9)
    target = sorted(_clue_houses(state))[0]
    data = copy.deepcopy(state.to_save_dict())
    for prem in data["procgen"]["premises"]:
        prem.pop("clue")
    old = GameState.from_dict(data)
    assert premises.CLUE_HINT not in [r["id"] for r in premises.intel_for(old, target)]
    out = _burgle(old, target, monkeypatch)
    assert out[-1]["closed"] and "clue_taken" not in out[-1]
    assert not any(r.get("clue") for r in out)
    assert clues.found(old) == []


# ---------------------------------------------------------------------------
# The loader
# ---------------------------------------------------------------------------


def _fault(tmp_path: Path, mutate) -> str:
    from engine.world import clues

    src = Path(__file__).resolve().parents[1] / "games" / "hue-and-cry" / "data" / "premises"
    doc = yaml.safe_load((src / "clues.yaml").read_text(encoding="utf-8"))
    mutate(doc)
    path = tmp_path / "clues.yaml"
    path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    with pytest.raises(ValueError) as info:
        clues._parse(path)
    assert "clues.yaml" in str(info.value)
    return str(info.value)


def test_the_loader_refuses_what_would_give_the_game_away(hue, tmp_path) -> None:
    def rename(name: str):
        def go(doc):
            doc["clues"][0]["text"] = f"a scrap of paper signed {name}"
        return go

    assert "Silas" in _fault(tmp_path, rename("Silas"))
    assert "the lamplighter" in _fault(tmp_path, rename("the lamplighter"))

    def point_at_ardane(doc):
        doc["clues"][0]["points_to"] = "npc_ardane"
    assert "points_to" in _fault(tmp_path, point_at_ardane)

    def thin(doc):
        imelda = [r for r in doc["clues"] if r["points_to"] == "npc_imelda"]
        doc["clues"] = [r for r in doc["clues"] if r["points_to"] != "npc_imelda"] + imelda[:3]
    assert "npc_imelda" in _fault(tmp_path, thin)

    def twice(doc):
        doc["clues"].append(dict(doc["clues"][0]))
    assert "twice" in _fault(tmp_path, twice)

    def no_role(doc):
        doc["role"] = "the_butler"
    assert "role" in _fault(tmp_path, no_role)

    def hidden_meter(doc):
        doc["evidence"] = "magpie_spree"
    assert "evidence" in _fault(tmp_path, hidden_meter)

    def too_many(doc):
        doc["trail"] = 30
        for npc in CANDIDATES:
            doc["clues"] += [{"id": f"{npc}_{i}", "points_to": npc, "text": "a button"}
                             for i in range(30)]
    assert "houses" in _fault(tmp_path, too_many)

    def too_long(doc):
        doc["clues"][0]["text"] = "a scrap of paper " * 10
    assert "140" in _fault(tmp_path, too_long)

    def bool_count(doc):
        doc["herrings"] = True
    assert "herrings" in _fault(tmp_path, bool_count)

    def found_prefix(doc):
        doc["fresh_flag"] = "clue_found:wick_ends"
    assert "fresh_flag" in _fault(tmp_path, found_prefix)

    def not_a_name(doc):
        doc["fresh_flag"] = ["clue_fresh"]
    assert "fresh_flag" in _fault(tmp_path, not_a_name)


def test_a_story_without_clues_yaml_lays_no_trail(tmp_path) -> None:
    """The synthetic premises tree of tests/test_premises.py: no file, no key."""
    from engine.config import set_overlay
    from engine.world import premises
    from tests.test_premises import _build

    root = _build(tmp_path / "premises")
    set_overlay({"paths": {"premises": str(root)}})
    try:
        prems, _ = premises.generate(42)
        assert prems and all("clue" not in p for p in prems)
    finally:
        set_overlay(None)


def test_the_shipped_trail_is_the_one_the_tree_holds(hue) -> None:
    """The file is found by fixed filename inside `paths.premises`."""
    from engine.world import clues, premises

    assert clues._path() == premises._premises_dir() / "clues.yaml"
    assert clues._path().is_file()
