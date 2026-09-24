"""
The Law, part two: deeds and the people who saw them.

THE SHAPE. A deed is committed through ``law.commit_deed``: everyone
``npc_sim`` places there this hour and awake rolls on the LAW stream to see
it, shaded by the dark and the stealth margin; ``certain`` people see it
without a roll; each witness is one ``witness`` row; a witness who IS the
watch reports at once, a ``reporters`` role with its chance, an informant
always. Three production callers commit deeds: a lift (``pickpocket``), a
watch on a house (``loitering``) and hot goods offered to an honest vendor
(``fencing``). Each receipt carries ``seen_by`` and ``reported``.

WHAT THESE TESTS HOLD. Nobody present, nobody sees; sleepers never see; a
caught hand is always seen by its mark and a clean one never is; the dark
lowers the witness rate (measured over 200 seeded deeds, not asserted per
roll); a watchman witness reports at once; loitering is recorded and never
lifts wanted above the first band; a seed replays; no roll happens while the
legal intents or a prompt are built; the narrator's receipt line never
carries an id; and a story without a Law -- the flagship, and a story with
thievery but no Law -- gets byte-identical receipts and an empty ``law``.

Version: v0.1.0 [2026-09-24]
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Iterator

import pytest
import yaml

from engine.config import set_overlay
from engine.game import checks
from engine.game.clock import set_clock
from engine.game.effects import apply_effect
from engine.game.procgen import generate_world
from engine.game.rng import LAW
from engine.game.state import GameState, InventoryItem
from engine.world import law, npc_sim, premises, thievery

from test_law import SPEC as LAW_SPEC
from test_premises import _build

SQUARE = "edgewood_square"
ALL_DAY = [{"hours": list(range(24)), "location": SQUARE, "activity": "idling"}]
ASLEEP = [{"hours": list(range(24)), "location": SQUARE, "activity": "dozing", "available": False}]

THIEVERY_SPEC = {
    "alertness": {"default": "standard"},
    "purses": {"default": [{"gold": [2, 4], "weight": 1}]},
    "hot_days": 5,
}
TRADE_DOC = {
    "version": 1,
    "trade": {
        "spread": {"buy": 1.0, "sell": 1.0},
        "min_sale_price": 1,
        "never_traded_tags": [],
        "scarcity": {},
    },
    "vendors": {"npc_honest": {"name": "Honest Hal", "location": SQUARE}},
}
ECONOMY_DOC = {"npc_honest": {"sells": {}, "buys": {}}}


def _dump(path: Path, doc: Any) -> str:
    path.write_text(yaml.safe_dump(doc), encoding="utf-8")
    return str(path)


def _paths(tmp_path: Path, *, with_law: bool = True, law_doc: Any = None) -> dict[str, str]:
    paths = {
        "thievery": _dump(tmp_path / "thievery.yaml", THIEVERY_SPEC),
        "tables": str(tmp_path),
        "economy": _dump(tmp_path / "economy.yaml", ECONOMY_DOC),
        "premises": str(_build(tmp_path / "premises")),
        # No scheduled cast: the flagship's own people stand in the square, and
        # every head count below is of the synthetic crowd alone.
        "npc_schedules": _dump(tmp_path / "npc_schedules.yaml", {"npcs": {}}),
    }
    _dump(tmp_path / "trade.yaml", TRADE_DOC)
    if with_law:
        paths["law"] = _dump(tmp_path / "law.yaml", law_doc or LAW_SPEC)
    return paths


@pytest.fixture()
def lawful(tmp_path: Path) -> Iterator[Path]:
    set_overlay({"paths": _paths(tmp_path)})
    try:
        yield tmp_path
    finally:
        set_overlay(None)


@pytest.fixture()
def lawless(tmp_path: Path) -> Iterator[Path]:
    """Thievery, premises and fences -- and no Law."""
    set_overlay({"paths": _paths(tmp_path, with_law=False)})
    try:
        yield tmp_path
    finally:
        set_overlay(None)


def _person(npc_id: str, role: str, routine: list[dict[str, Any]]) -> dict[str, Any]:
    return {"id": npc_id, "name": npc_id.replace("_", " ").title(), "role": role, "routine": routine}


def _world(people: list[dict[str, Any]], *, seed: int = 42, hour: int = 12) -> GameState:
    state = GameState(rng_seed=seed, location_id=SQUARE)
    state.procgen = generate_world(seed)
    state.procgen.npcs = people
    set_clock(state, day=1, hour=hour)
    return state


def _crowd() -> list[dict[str, Any]]:
    return [
        _person("gen_w_mark", "labourer", ALL_DAY),
        _person("gen_w_a", "labourer", ALL_DAY),
        _person("gen_w_b", "labourer", ALL_DAY),
        _person("gen_w_c", "labourer", ALL_DAY),
    ]


class _Rigged:
    def __init__(self, degree: str, margin: int) -> None:
        self.degree = degree
        self.margin = margin

    def to_dict(self) -> dict[str, Any]:
        return {"degree": self.degree, "margin": self.margin}


def _rig(monkeypatch: pytest.MonkeyPatch, degree: str, margin: int = 0) -> None:
    monkeypatch.setattr(checks, "resolve", lambda *a, **k: _Rigged(degree, margin))


# -- who can see ---------------------------------------------------------------


def test_nobody_present_nobody_sees(lawful: Path) -> None:
    state = _world([])
    out = law.commit_deed(state, "pickpocket")
    assert out == {"witnesses": [], "reported": False}
    assert state.law == {}
    # Nobody to roll for draws nothing: the stream does not move.
    assert LAW not in state.rng_counters


def test_the_asleep_never_see(lawful: Path) -> None:
    sleepers = [_person(f"gen_w_s{i}", "watch", ASLEEP) for i in range(4)]
    for seed in range(40):
        state = _world(sleepers, seed=seed)
        assert law.commit_deed(state, "pickpocket")["witnesses"] == []
    assert "witnessed" not in state.law


def test_a_house_indoors_does_not_see_the_street(lawful: Path) -> None:
    home = npc_sim.interior_id(SQUARE, "prem_x")
    indoors = [{"id": "gen_w_in", "name": "In", "role": "watch", "home": home,
                "routine": [{"hours": list(range(24)), "location": home, "activity": "in"}]}]
    state = _world(indoors)
    assert law.commit_deed(state, "pickpocket", certain=())["witnesses"] == []
    # ...and the same household does see a deed inside its own house.
    assert law.commit_deed(state, "pickpocket", location=home, certain=("gen_w_in",))[
        "witnesses"
    ] == ["gen_w_in"]


def test_a_witness_row_has_the_state_shape(lawful: Path) -> None:
    state = _world([_person("gen_w_mark", "labourer", ALL_DAY)])
    law.commit_deed(state, "pickpocket", certain=("gen_w_mark",))
    law.commit_deed(state, "pickpocket", certain=("gen_w_mark",))
    rows = state.law["witnessed"]
    assert rows[0] == {
        "id": "w1", "deed_id": "d1", "deed": "pickpocket", "severity": 1, "guise": "self",
        "npc": "gen_w_mark", "where": SQUARE, "day": 1, "hop": 1, "precision": 1.0,
    }
    assert rows[1]["id"] == "w2" and rows[1]["deed_id"] == "d2"
    # The current guise is what gets filed -- effective, not merely stored:
    # `current_guise` (Task 4 fix F2) only honours a stored guise whose item
    # is still carried, so wearing the Magpie's mask means carrying it too.
    state.inventory.append(
        InventoryItem(id="golden_ring", name="Gold ring", qty=1, tags=["charm", "trade", "quest"])
    )
    state.law["guise"] = "magpie"
    law.commit_deed(state, "pickpocket", certain=("gen_w_mark",))
    assert state.law["witnessed"][-1]["guise"] == "magpie"


def test_the_witness_effect_refuses_what_the_law_does_not_know(lawful: Path) -> None:
    state = _world([])
    bad = apply_effect(state, {"type": "witness", "deed": "arson", "guise": "self",
                               "npc": "x", "where": SQUARE})
    assert bad["ok"] is False and "arson" in bad["message"] and bad["text"] == ""
    assert state.law == {}


def test_the_witness_effect_refuses_without_a_law() -> None:
    state = GameState()
    out = apply_effect(state, {"type": "witness", "deed": "pickpocket", "guise": "self",
                               "npc": "x", "where": SQUARE})
    assert out["ok"] is False and state.law == {}


def test_an_undeclared_kind_is_no_crime(lawful: Path) -> None:
    state = _world(_crowd())
    assert law.commit_deed(state, "arson", certain=("gen_w_mark",)) == {
        "witnesses": [], "reported": False,
    }
    assert state.law == {}


# -- the rate --------------------------------------------------------------------


def _rate(hour: int, deeds: int = 200) -> float:
    seen = 0
    crowd = _crowd()
    for seed in range(deeds):
        state = _world(crowd, seed=seed, hour=hour)
        seen += len(law.commit_deed(state, "pickpocket")["witnesses"])
    return seen / (deeds * len(crowd))


def test_the_dark_lowers_the_witness_rate(lawful: Path) -> None:
    day, dusk, night = _rate(12), _rate(18), _rate(23)
    # base 0.6, night -0.25: measured, not asserted per roll. Wide bands; the
    # point is the ordering and roughly the size of the gap.
    assert 0.5 < day < 0.7, day
    assert 0.25 < night < 0.45, night
    assert 0.25 < dusk < 0.45, dusk
    assert day - night > 0.15


def test_a_better_margin_lowers_the_chance(lawful: Path) -> None:
    state = _world([])
    assert law.notice_chance(state, 6) < law.notice_chance(state, 0) < law.notice_chance(state, -6)
    # Clamped: never certain, never impossible.
    assert law.notice_chance(state, -100) == law.NOTICE_CEILING
    assert law.notice_chance(state, 100) == law.NOTICE_FLOOR


# -- who tells the watch -----------------------------------------------------


def test_a_watchman_witness_reports_at_once(lawful: Path) -> None:
    state = _world([_person("gen_w_watch", "watch", ALL_DAY)])
    out = law.commit_deed(state, "pickpocket", certain=("gen_w_watch",))
    assert out == {"witnesses": ["gen_w_watch"], "reported": True}
    (row,) = state.law["reports"]
    assert row["deed"] == "pickpocket" and row["jurisdiction"] == "village"
    assert row["guise"] == "self" and row["precision"] == 1.0


def test_an_ordinary_witness_does_not_report_by_itself(lawful: Path) -> None:
    state = _world([_person("gen_w_a", "labourer", ALL_DAY)])
    out = law.commit_deed(state, "pickpocket", certain=("gen_w_a",))
    assert out == {"witnesses": ["gen_w_a"], "reported": False}
    assert "reports" not in state.law


def test_a_reporter_role_reports_at_its_chance(lawful: Path) -> None:
    told = 0
    for seed in range(200):
        state = _world([_person("gen_w_v", "vendor", ALL_DAY)], seed=seed)
        told += law.commit_deed(state, "pickpocket", certain=("gen_w_v",))["reported"]
    assert 0.2 < told / 200 < 0.4, told  # reporters.vendor = 0.3


def test_a_deed_seen_by_three_watchmen_is_filed_once(lawful: Path) -> None:
    watch = [_person(f"gen_w_watch{i}", "watch", ALL_DAY) for i in range(3)]
    state = _world(watch)
    out = law.commit_deed(state, "pickpocket", certain=tuple(p["id"] for p in watch))
    assert len(out["witnesses"]) == 3 and out["reported"] is True
    # Three rows, three reports -- one deed id across all six, one severity.
    assert len(state.law["reports"]) == 3
    ids = {r["deed_id"] for r in state.law["witnessed"] + state.law["reports"]}
    assert ids == {"d1"}
    assert law.filed_score(state, "self", "village") == 1.0


def test_a_later_hop_of_the_same_deed_adds_nothing(lawful: Path) -> None:
    state = _world([_person("gen_w_watch", "watch", ALL_DAY)])
    law.commit_deed(state, "fencing", certain=("gen_w_watch",))
    assert law.filed_score(state, "self", "village") == 2.0
    # The same deed arriving again, second-hand and blurrier (Task 3's
    # propagation will file exactly this): the best precision stands.
    apply_effect(state, {"type": "report", "deed": "fencing", "guise": "self",
                         "jurisdiction": "village", "precision": 0.6, "deed_id": "d1"})
    assert law.filed_score(state, "self", "village") == 2.0
    # ...and a blurry first report is lifted, not added to, by a clear one.
    apply_effect(state, {"type": "report", "deed": "pickpocket", "guise": "self",
                         "jurisdiction": "village", "precision": 0.3, "deed_id": "d9"})
    apply_effect(state, {"type": "report", "deed": "pickpocket", "guise": "self",
                         "jurisdiction": "village", "precision": 1.0, "deed_id": "d9"})
    assert law.filed_score(state, "self", "village") == 3.0


def test_two_deeds_still_add(lawful: Path) -> None:
    state = _world([_person("gen_w_watch", "watch", ALL_DAY)])
    law.commit_deed(state, "pickpocket", certain=("gen_w_watch",))
    law.commit_deed(state, "pickpocket", certain=("gen_w_watch",))
    assert {r["deed_id"] for r in state.law["reports"]} == {"d1", "d2"}
    assert law.filed_score(state, "self", "village") == 2.0
    # A report row with no deed id (a hand-edited save) is its own deed.
    state.law["reports"].append({"deed": "pickpocket", "severity": 1, "guise": "self",
                                 "jurisdiction": "village", "precision": 1.0, "day": 1})
    assert law.filed_score(state, "self", "village") == 3.0


def test_cooling_caps_at_the_counted_once_score(lawful: Path) -> None:
    watch = [_person(f"gen_w_watch{i}", "watch", ALL_DAY) for i in range(3)]
    state = _world(watch)
    law.commit_deed(state, "fencing", certain=tuple(p["id"] for p in watch))
    law.cool(state, 30)
    # Capped at the one deed's 2.0, not the three reports' 6.0: a quiet month
    # must not bank forgiveness against the next crime.
    assert law.cooling_of(state, "self", "village") == 2.0
    law.commit_deed(state, "fencing", certain=("gen_w_watch0",))
    assert law.wanted_score(state, "self", "village") == 2.0


def test_tuning_reporters_does_not_move_who_saw(tmp_path: Path) -> None:
    # Interleaved rolls survived a changed CHANCE (the same draws are consumed
    # either way) but not a role added to or dropped from `reporters`, which
    # changes how many draws each witness takes. Both are tuning; neither may
    # change who saw.
    crowd = [_person(f"gen_w_v{i}", "vendor", ALL_DAY) for i in range(6)]

    def witnesses(tag: str, reporters: dict[str, float]) -> list[list[str]]:
        doc = copy.deepcopy(LAW_SPEC)
        doc["reporters"] = reporters
        sub = tmp_path / tag
        sub.mkdir()
        set_overlay({"paths": _paths(sub, law_doc=doc)})
        try:
            return [
                law.commit_deed(_world(crowd, seed=seed), "pickpocket")["witnesses"]
                for seed in range(60)
            ]
        finally:
            set_overlay(None)

    none = witnesses("none", {})
    assert any(none)
    assert witnesses("low", {"vendor": 0.1}) == none
    assert witnesses("high", {"vendor": 0.9}) == none


def test_no_watch_reaches_the_forest(lawful: Path) -> None:
    state = _world([_person("gen_w_watch", "watch", ALL_DAY)])
    out = law.commit_deed(state, "pickpocket", location="forest_clearing",
                          certain=("gen_w_watch",))
    assert out == {"witnesses": ["gen_w_watch"], "reported": False}


# -- the callers -----------------------------------------------------------------


def test_a_caught_hand_is_always_seen_by_its_mark(
    lawful: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _rig(monkeypatch, "failure", margin=-4)
    for seed in range(30):
        state = _world(_crowd(), seed=seed)
        out = thievery.lift(state, "gen_w_mark")
        assert out["noticed"] and "gen_w_mark" in out["seen_by"], out
        assert set(out["seen_by"]) == {r["npc"] for r in state.law["witnessed"]}


def test_a_clean_lift_is_never_seen_by_its_mark(
    lawful: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _rig(monkeypatch, "success", margin=2)
    for seed in range(30):
        state = _world(_crowd(), seed=seed)
        out = thievery.lift(state, "gen_w_mark")
        assert out["success"] and "gen_w_mark" not in out["seen_by"]
        assert out["reported"] is False


def test_casing_is_loitering_and_never_raises_wanted(lawful: Path) -> None:
    state = _world(_crowd(), hour=8)
    prem = next(p for p in state.procgen.premises if p["district"] == SQUARE)
    seen_any = False
    for _ in range(len(premises.intel_for(state, prem["id"]))):
        out = premises.case(state, prem["id"])
        assert out["ok"] and "seen_by" in out and out["reported"] is False
        seen_any = seen_any or bool(out["seen_by"])
    assert seen_any
    assert all(r["deed"] == "loitering" for r in state.law["witnessed"])
    assert "reports" not in state.law
    assert law.wanted_band(state, "self", "village") == "unknown"


def test_casing_by_a_watchman_is_remembered_not_reported(lawful: Path) -> None:
    people = [_person(f"gen_w_watch{i}", "watch", ALL_DAY) for i in range(6)]
    state = _world(people, hour=8)
    prem = next(p for p in state.procgen.premises if p["district"] == SQUARE)
    out = premises.case(state, prem["id"])
    assert out["seen_by"] and out["reported"] is False
    assert law.wanted_band(state, "self", "village") == "unknown"


def _hot_ring(state: GameState) -> None:
    state.inventory.append(
        InventoryItem(id="golden_ring", name="Gold ring", qty=1, tags=["charm", "trade", "quest"])
    )
    state.provenance["golden_ring"] = [{"whom": "gen_w_mark", "where": SQUARE, "day": 1}]


def test_hot_goods_at_an_honest_vendor_are_fencing_and_reported(lawful: Path) -> None:
    from engine.game import trade

    state = _world([])
    _hot_ring(state)
    out = trade.sell(state, "npc_honest", "golden_ring", 1)
    assert out["success"] is False
    assert out["seen_by"] == ["npc_honest"] and out["reported"] is True
    (row,) = state.law["witnessed"]
    assert row["deed"] == "fencing" and row["npc"] == "npc_honest"
    (report,) = state.law["reports"]
    assert report["deed"] == "fencing" and report["severity"] == 2


def test_a_browse_or_quote_of_hot_goods_commits_nothing(lawful: Path) -> None:
    from engine.game import trade

    state = _world(_crowd())
    _hot_ring(state)
    trade.quote(state, "npc_honest", "golden_ring", trade.SELL, 1)
    trade.browse(state, "npc_honest")
    assert state.law == {} and LAW not in state.rng_counters


def test_a_seed_replays(lawful: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def run() -> dict[str, Any]:
        state = _world(_crowd(), seed=7, hour=21)
        for npc in ("gen_w_mark", "gen_w_a", "gen_w_b"):
            thievery.lift(state, npc)
        return copy.deepcopy(state.law)

    first = run()
    assert first.get("witnessed")
    assert run() == first


def test_no_roll_while_building_intents_or_a_prompt(lawful: Path) -> None:
    from engine.agents import prompts
    from engine.game.intents import legal_intents

    state = _world(_crowd())
    _hot_ring(state)
    legal_intents(state)
    prompts.world_state_block(state, {})
    assert LAW not in state.rng_counters and state.law == {}


def test_the_receipt_line_never_carries_a_witness_id(
    lawful: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from engine.agents.prompts import summarise_receipt
    from engine.game import trade

    for degree in ("failure", "success"):
        _rig(monkeypatch, degree, margin=-3)
        state = _world(_crowd(), seed=3)
        out = thievery.lift(state, "gen_w_mark")
        assert out["seen_by"]
        line = summarise_receipt({"skill": "lift_purse", "result": out})
        assert not any(npc in line for npc in out["seen_by"]) and "seen_by" not in line

    state = _world(_crowd(), hour=8)
    prem = next(p for p in state.procgen.premises if p["district"] == SQUARE)
    out = premises.case(state, prem["id"])
    line = summarise_receipt({"skill": "case_premise", "result": out})
    assert "gen_w" not in line and "seen_by" not in line

    # A refused sale renders through the block's REFUSED branch in play, not
    # through a summariser -- so that is the path held here.
    from engine.agents.prompts import receipts_block
    from engine.agents.tool_dispatcher import execute_intent
    from engine.game.engine import GameEngine

    state = _world([])
    _hot_ring(state)
    receipts = execute_intent(
        {"action": "sell", "target": "npc_honest/golden_ring"}, GameEngine(state)
    )
    assert receipts and receipts[0]["result"].get("seen_by") == ["npc_honest"], receipts
    block = receipts_block(receipts)
    assert "REFUSED" in block or "failed" in block, block
    assert "npc_honest" not in block and "seen_by" not in block


# -- a story without a Law pays nothing ----------------------------------------------


def test_without_a_law_the_callers_are_unchanged(
    lawless: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from engine.game import trade

    _rig(monkeypatch, "failure")
    state = _world(_crowd(), hour=8)
    out = thievery.lift(state, "gen_w_mark")
    assert out["ok"] and "seen_by" not in out and "reported" not in out
    prem = next(p for p in state.procgen.premises if p["district"] == SQUARE)
    out = premises.case(state, prem["id"])
    assert out["ok"] and "seen_by" not in out
    _hot_ring(state)
    out = trade.sell(state, "npc_honest", "golden_ring", 1)
    assert out["success"] is False and "seen_by" not in out
    assert state.law == {} and LAW not in state.rng_counters


def test_the_flagship_sell_is_unchanged() -> None:
    # Only the SELL half is coverage: the flagship declares neither thievery
    # nor premises, so its lift and case refuse before reaching the Law, and
    # the two asserts on them below only pin that they still refuse cleanly.
    # The real "no Law, same receipt" coverage for lift and case is
    # `test_without_a_law_the_callers_are_unchanged`, above.
    from engine.game import trade
    from engine.games import registry

    registry.activate("clockwork-dark")
    try:
        assert not law.declared()
        state = GameState(rng_seed=42, location_id=SQUARE)
        state.procgen = generate_world(42)
        assert "seen_by" not in thievery.lift(state, "anyone")
        assert "seen_by" not in premises.case(state, "anything")
        state.inventory.append(InventoryItem(id="loaf", name="Loaf", qty=1, tags=[]))
        vendors = [v for v in trade.vendors() if trade.vendor(v).get("known")]
        assert vendors
        for npc_id in vendors[:3]:
            assert "seen_by" not in trade.sell(state, npc_id, "loaf", 1)
        assert state.law == {} and LAW not in state.rng_counters
    finally:
        registry.deactivate()
