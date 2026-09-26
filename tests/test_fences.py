"""
Fences and honest vendors: what a stolen thing is worth to sell.

THE SHAPE. ``thievery.heat_split`` names, per unit, how many of a carried
stack are ``clean`` (never stolen), ``cool`` (stolen, aged past ``hot_days``)
and ``hot`` (stolen and still fresh, or the item is ``named``, which never
ages out). ``trade.quote``/``trade.sell`` read it -- only on the sell side --
through one shared helper, ``trade._plan_sale``, so the two can never
disagree about a mixed stack. A vendor without ``fence: true`` sells clean
and cool units at the ordinary price and refuses to move past them into hot
ones, in the vendor's own voice. A fence (``fence: true``, optional
``fence_cut: {hot, cool}``, default 0.5/0.8) sells hot units first, then
cool, then clean, pricing each at its own cut -- clean units always at full
price, even at a fence. Selling is what launders: one ``provenance`` record
consumed per STOLEN unit actually sold (never for a clean one, since it has
no record to begin with), through the ``provenance`` effect kind -- the one
writer. A complication or any other non-sale removal (``remove_item``) never
touches a record -- goods lost that way keep exactly the history they had.

F1 (v0.9.0 review, round 1): the first cut of this task read ``thievery.heat``
-- the item's single, worst-case answer -- and applied it to an ENTIRE
requested quantity. Selling one clean ring and one stolen ring together had
an honest vendor refuse both, and a fence discount both. The mixed-stack
tests below are what that review round added; the rest were already green
when it landed and are checked again here for the same reason the whole
suite is: this file is the regression guard for both.

Version: v0.2.0 [2026-09-23]
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator, Optional

import pytest
import yaml

from engine.config import set_overlay
from engine.game import trade
from engine.game.clock import advance_time, set_clock
from engine.game.effects import apply_effect
from engine.game.state import GameState, InventoryItem
from engine.world import thievery

SQUARE = "edgewood_square"
#: Flagship registry item: value 120, tags charm/trade/quest, no `named` tag
#: of its own -- so its heat comes ENTIRELY from provenance, the case these
#: tests are about.
RING = "golden_ring"
#: Never touched by a `stolen_from` record in any test below.
LOAF = "loaf"
#: Where `npc_grudge` keeps her counter (v0.15's `refuses_to_buy`).
BACK_ROOM = "edgewood_bakery"

THIEVERY_SPEC = {
    "alertness": {"default": "standard"},
    "purses": {"default": [{"gold": [1, 2], "weight": 1}]},
    "hot_days": 5,
}

TRADE_DOC = {
    "version": 1,
    "trade": {
        # Flat 1.0 both ways: the arithmetic under test is the FENCE cut, not
        # the ordinary spread `test_livelihood.py` already covers.
        "spread": {"buy": 1.0, "sell": 1.0},
        "min_sale_price": 1,
        "never_traded_tags": [],
        "scarcity": {},
    },
    "vendors": {
        "npc_honest": {"name": "Honest Hal", "location": SQUARE},
        "npc_fence": {
            "name": "Sly Rue",
            "location": SQUARE,
            "fence": True,
            "fence_cut": {"hot": 0.4, "cool": 0.75},
        },
        # v0.15: a fence who will not buy from a player who welshed on her
        # (`refuses_to_buy`). In another room, so the square's verbs above
        # are exactly what they were.
        "npc_grudge": {
            "name": "Old Grudge",
            "location": BACK_ROOM,
            "fence": True,
            "refuses_to_buy": {
                "when": {"flag": "welshed_on_grudge"},
                "text": "Old Grudge buys nothing from someone who owes her ten crowns.",
            },
        },
    },
}

# Neither vendor declares a faction, so each needs a stock row -- even an
# empty one -- to read as `known`: `vendor()` sets `known = bool(faction or
# stock)`.
ECONOMY_DOC = {
    "npc_honest": {"sells": {}, "buys": {}},
    "npc_fence": {"sells": {}, "buys": {}},
    "npc_grudge": {"sells": {LOAF: {"price": 2}}, "buys": {}},
}


@pytest.fixture()
def market(tmp_path: Path) -> Iterator[None]:
    (tmp_path / "thievery.yaml").write_text(yaml.safe_dump(THIEVERY_SPEC), encoding="utf-8")
    (tmp_path / "trade.yaml").write_text(yaml.safe_dump(TRADE_DOC), encoding="utf-8")
    (tmp_path / "economy.yaml").write_text(yaml.safe_dump(ECONOMY_DOC), encoding="utf-8")
    set_overlay(
        {
            "paths": {
                "thievery": str(tmp_path / "thievery.yaml"),
                "tables": str(tmp_path),
                "economy": str(tmp_path / "economy.yaml"),
            }
        }
    )
    try:
        yield
    finally:
        set_overlay(None)


def _mixed_state(clean: int, stolen_days: Optional[list[int]]) -> GameState:
    """
    A square holding ``clean`` honest rings plus one stolen record per entry
    in ``stolen_days`` -- the day each was lifted, where day 1 is "today".
    """
    stolen_days = stolen_days or []
    state = GameState(location_id=SQUARE)
    set_clock(state, day=1, hour=12)
    held = clean + len(stolen_days)
    state.inventory.append(
        InventoryItem(id=RING, name="Gold ring", qty=held, tags=["charm", "trade", "quest"])
    )
    if stolen_days:
        state.provenance[RING] = [
            {"whom": "gen_t_mark", "where": SQUARE, "day": day} for day in stolen_days
        ]
    return state


def _state(qty: int = 1) -> GameState:
    """A square with `qty` stolen rings in the pack, each lifted today (hot)."""
    return _mixed_state(clean=0, stolen_days=[1] * qty)


def _verbs(state: GameState) -> dict[str, tuple[tuple[str, str], ...]]:
    from engine.game.intents import legal_intents

    return {v.action: v.options for v in legal_intents(state)}


# -- the refusal (a uniformly hot stack) -------------------------------------


def test_hot_goods_are_refused_by_a_vendor_without_fence(market: None) -> None:
    state = _state()
    assert thievery.heat_split(state, RING) == {"clean": 0, "cool": 0, "hot": 1}

    quote = trade.quote(state, "npc_honest", RING, side="sell")
    assert quote["ok"] is False
    assert quote["reason"] == "Honest Hal won't touch it -- not this week"
    assert quote["unit_kind"] == "hot"

    sale = trade.sell(state, "npc_honest", RING, 1)
    assert sale["success"] is False
    assert sale["message"] == "Honest Hal won't touch it -- not this week"
    # A refusal moves nothing: the ring and its record are exactly as before.
    assert state.inventory[0].qty == 1
    assert state.provenance[RING] == [{"whom": "gen_t_mark", "where": SQUARE, "day": 1}]


# -- the fence's cut (a uniform stack) ---------------------------------------


def test_a_fence_buys_hot_goods_at_the_hot_cut(market: None) -> None:
    state = _state()
    quote = trade.quote(state, "npc_fence", RING, side="sell")
    assert quote["ok"] is True
    assert quote["unit_kind"] == "hot"
    assert quote["fence"] is True
    assert quote["unit_price"] == 48  # 120 base value * 0.4 fence_cut.hot

    gold_before = state.stats.gold
    sale = trade.sell(state, "npc_fence", RING, 1)
    assert sale["success"] is True
    assert state.stats.gold == gold_before + 48
    # The one theft record is what the sale paid to forget.
    assert RING not in state.provenance
    assert state.inventory == []


def test_cool_goods_sell_to_honest_vendors_at_the_normal_price(market: None) -> None:
    state = _state()
    advance_time(state, 24 * 6)  # past hot_days=5
    assert thievery.heat_split(state, RING) == {"clean": 0, "cool": 1, "hot": 0}

    honest = trade.quote(state, "npc_honest", RING, side="sell")
    assert honest["ok"] is True
    assert honest["fence"] is False
    assert honest["unit_price"] == 120  # no cut at all for an honest vendor

    fence = trade.quote(state, "npc_fence", RING, side="sell")
    assert fence["ok"] is True
    # A fence still discounts a cool item -- fencing is the whole business.
    assert fence["unit_price"] == 90  # 120 * 0.75 fence_cut.cool


def test_a_never_stolen_item_carries_no_cut_at_either_vendor(market: None) -> None:
    state = _state()
    state.inventory.append(InventoryItem(id=LOAF, name="Loaf of bread", qty=1, tags=["food"]))
    assert thievery.heat_split(state, LOAF) == {"clean": 1, "cool": 0, "hot": 0}

    honest = trade.quote(state, "npc_honest", LOAF, side="sell")
    fence = trade.quote(state, "npc_fence", LOAF, side="sell")
    assert honest["unit_price"] == fence["unit_price"] == 2  # loaf's registry value


# -- F1: a mixed stack, priced and refused per unit --------------------------


def test_a_mixed_stack_sells_its_clean_unit_to_an_honest_vendor(market: None) -> None:
    """One clean ring and one still-hot ring: the honest vendor's `qty=1`
    sale is the clean one, at the ordinary price, touching no record."""
    state = _mixed_state(clean=1, stolen_days=[1])
    assert thievery.heat_split(state, RING) == {"clean": 1, "cool": 0, "hot": 1}

    quote = trade.quote(state, "npc_honest", RING, side="sell", qty=1)
    assert quote["ok"] is True
    assert quote["unit_kind"] == "clean"
    assert quote["unit_price"] == 120

    gold_before = state.stats.gold
    sale = trade.sell(state, "npc_honest", RING, 1)
    assert sale["success"] is True
    assert state.stats.gold == gold_before + 120
    assert state.inventory[0].qty == 1  # the hot one is what's left
    assert state.provenance[RING] == [{"whom": "gen_t_mark", "where": SQUARE, "day": 1}]


def test_a_mixed_stack_refuses_to_sell_past_its_clean_units(market: None) -> None:
    """Same stack, asked for both at once: the honest vendor cannot take the
    hot one, and the WHOLE sale is refused rather than half-executed."""
    state = _mixed_state(clean=1, stolen_days=[1])

    quote = trade.quote(state, "npc_honest", RING, side="sell", qty=2)
    assert quote["ok"] is False
    assert quote["reason"] == "Honest Hal will take the clean ones, not the rest"

    sale = trade.sell(state, "npc_honest", RING, 2)
    assert sale["success"] is False
    # A refusal moves nothing -- not even the clean unit it would sell alone.
    assert state.inventory[0].qty == 2
    assert state.provenance[RING] == [{"whom": "gen_t_mark", "where": SQUARE, "day": 1}]


def test_a_cool_stolen_unit_sells_to_an_honest_vendor_and_consumes_its_record(
    market: None,
) -> None:
    """No clean units at all: both rings were stolen, but long enough ago to
    have cooled. The brief's own rule -- cool goods sell to honest vendors
    normally -- made literal: a real record is what a sale here consumes."""
    state = _mixed_state(clean=0, stolen_days=[1, 1])
    advance_time(state, 24 * 6)  # past hot_days=5: both records have cooled
    assert thievery.heat_split(state, RING) == {"clean": 0, "cool": 2, "hot": 0}

    gold_before = state.stats.gold
    sale = trade.sell(state, "npc_honest", RING, 1)
    assert sale["success"] is True
    assert state.stats.gold == gold_before + 120  # the ordinary price, no cut
    assert len(state.provenance[RING]) == 1  # one record consumed
    assert state.inventory[0].qty == 1


def test_a_fence_prices_a_mixed_stack_per_unit_and_consumes_only_the_stolen_records(
    market: None,
) -> None:
    """One clean ring, one still-hot ring, sold together: the fence discounts
    only the stolen unit and its own record is the only one consumed."""
    state = _mixed_state(clean=1, stolen_days=[1])

    quote = trade.quote(state, "npc_fence", RING, side="sell", qty=2)
    assert quote["ok"] is True
    assert quote["breakdown"]["prices_by_kind"] == {"hot": 48, "clean": 120}
    assert quote["total"] == 48 + 120
    assert quote["stolen_sold"] == 1

    gold_before = state.stats.gold
    sale = trade.sell(state, "npc_fence", RING, 2)
    assert sale["success"] is True
    assert state.stats.gold == gold_before + 168
    assert state.inventory == []  # both units sold
    assert RING not in state.provenance  # the one stolen record, gone


# -- provenance and the sale (uniform stacks) --------------------------------


def test_selling_consumes_one_provenance_record_per_unit(market: None) -> None:
    state = _state(qty=2)
    trade.sell(state, "npc_fence", RING, 1)
    assert len(state.provenance[RING]) == 1
    trade.sell(state, "npc_fence", RING, 1)
    assert RING not in state.provenance
    assert state.inventory == []


def test_a_non_sale_removal_does_not_launder_provenance(market: None) -> None:
    """A complication that costs the player the ring is not a sale."""
    state = _state()
    apply_effect(state, {"type": "remove_item", "item_id": RING, "qty": 1})
    assert state.inventory == []
    # The record survives on goods the player no longer has: a later theft of
    # the same id must not read as somehow cleaner for this one having left.
    assert state.provenance[RING] == [{"whom": "gen_t_mark", "where": SQUARE, "day": 1}]


def test_selling_a_never_stolen_item_touches_no_provenance(market: None) -> None:
    state = _state()  # one hot ring, untouched by this sale
    state.inventory.append(InventoryItem(id=LOAF, name="Loaf of bread", qty=1, tags=["food"]))
    sale = trade.sell(state, "npc_honest", LOAF, 1)
    assert sale["success"] is True
    assert state.provenance == {RING: [{"whom": "gen_t_mark", "where": SQUARE, "day": 1}]}


def test_the_provenance_receipt_names_the_item_never_its_raw_id(market: None) -> None:
    """`item_id.replace('_', ' ')` is not the item's name; the registry is."""
    state = _state()
    out = apply_effect(state, {"type": "provenance", "item_id": RING, "qty": 1})
    assert out["removed"] == 1
    assert "Gold ring" in out["text"]
    assert "golden_ring" not in out["text"] and "golden ring" not in out["text"]


# -- the verb and the intent -------------------------------------------------


def test_the_sell_verb_flags_hot_goods_in_its_label(market: None) -> None:
    state = _state()
    state.inventory.append(InventoryItem(id=LOAF, name="Loaf of bread", qty=1, tags=["food"]))
    targets = dict(_verbs(state)["sell"])
    assert targets[f"npc_honest/{RING}"].endswith("(hot)")
    assert targets[f"npc_fence/{RING}"].endswith("(hot)")
    assert not targets[f"npc_honest/{LOAF}"].endswith("(hot)")


def test_a_mixed_stacks_label_reflects_the_unit_that_would_actually_move(market: None) -> None:
    """One clean, one hot: the composite `sell` target always moves exactly
    one unit (`to_tool_call` hard-codes `qty=1`), and for an honest vendor
    that unit is the clean one -- so no `(hot)` warning belongs on it."""
    state = _mixed_state(clean=1, stolen_days=[1])
    targets = dict(_verbs(state)["sell"])
    assert not targets[f"npc_honest/{RING}"].endswith("(hot)")
    # A fence sells the hot one first, so its target still warns.
    assert targets[f"npc_fence/{RING}"].endswith("(hot)")


def test_a_refused_hot_sale_reaches_the_narrator_as_a_refusal(market: None) -> None:
    from engine.agents.tool_dispatcher import execute_intent
    from engine.game.engine import GameEngine

    state = _state()
    target = f"npc_honest/{RING}"
    assert target in dict(_verbs(state)["sell"]), "the refused target must still be legal to attempt"

    engine = GameEngine(state)
    receipts = execute_intent({"action": "sell", "target": target}, engine)
    assert receipts and receipts[0]["success"] is False
    assert receipts[0]["refused"] is True
    assert "won't touch it" in receipts[0]["result"]["message"]
    # The engine declined; nothing sold.
    assert state.inventory[0].qty == 1


def test_the_refusal_key_matches_what_sell_returns() -> None:
    """
    ``trade.sell`` and ``trade.buy`` both report a refusal under ``success``;
    neither has ever had an ``ok`` key. The entry that named ``"ok"`` here
    never matched what the skill returned, so ``declined_reason`` never fired
    for a refused sale -- fixed alongside the fence refusal this key now
    catches.
    """
    from engine.game.intents import REFUSAL_KEY_FOR_ACTION, SKILL_FOR_ACTION

    assert SKILL_FOR_ACTION["sell"] == "trade_sell"
    assert REFUSAL_KEY_FOR_ACTION["sell"] == "success"


# -- F2: `buy` had the identical latent bug ----------------------------------


def test_the_old_buy_refusal_key_would_have_missed_a_real_refusal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Canary. ``declined_reason`` reads whatever key ``REFUSAL_KEY_FOR_ACTION``
    names for the action; swapped back to the pre-fix ``"ok"`` for ``buy``,
    the exact refusal ``trade.buy`` actually returns (under ``success``)
    vanishes -- which is precisely how a refused purchase reached the
    narrator as a successful one before this fix.
    """
    from engine.game.intents import REFUSAL_KEY_FOR_ACTION, declined_reason

    refusal = {"success": False, "message": "That is 12c and you have 0c."}
    monkeypatch.setitem(REFUSAL_KEY_FOR_ACTION, "buy", "ok")
    assert declined_reason("buy", refusal) == ""  # the bug: a real refusal, unseen
    monkeypatch.setitem(REFUSAL_KEY_FOR_ACTION, "buy", "success")
    assert declined_reason("buy", refusal) == "That is 12c and you have 0c."


def test_a_refused_buy_reaches_the_narrator_as_a_refusal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The same fix, end to end through `execute_intent` rather than against
    `declined_reason` in isolation -- a legal `buy` target whose underlying
    sale the engine still declines must come back refused, not successful."""
    from engine.agents.tool_dispatcher import execute_intent
    from engine.game import trade as trade_module
    from engine.game.engine import GameEngine

    state = GameState(location_id="edgewood_bakery")
    state.stats.gold = 500  # affordable, so a real target is offered
    engine = GameEngine(state)
    target = next(t for t, _ in _verbs(state)["buy"] if t.startswith("npc_maris/"))

    def refused_buy(state: GameState, npc_id: str, item_id: str, qty: int = 1) -> dict:
        return {
            "success": False,
            "npc_id": npc_id,
            "item_id": item_id,
            "message": "Maris shakes her head: that batch is already sold.",
        }

    monkeypatch.setattr(trade_module, "buy", refused_buy)
    receipts = execute_intent({"action": "buy", "target": target}, engine)
    assert receipts and receipts[0]["success"] is False
    assert receipts[0]["refused"] is True
    assert "already sold" in receipts[0]["result"]["message"]


# -- a story without thievery pays nothing -----------------------------------


def test_the_flagship_sell_path_is_unaffected_without_thievery() -> None:
    """
    No ``paths.thievery`` means ``heat_split`` answers all-clean for
    everything: no refusal, no fence cut, no ``(hot)`` label -- the
    flagship's sell path is byte-identical to before this task.
    """
    from engine.game.state import InventoryItem as Item

    assert not thievery.declared()
    state = GameState(location_id="edgewood_bakery")
    state.inventory.append(Item(id="hedge_berries", name="Hedge berries", qty=1, tags=["food"]))
    assert thievery.heat_split(state, "hedge_berries") == {"clean": 1, "cool": 0, "hot": 0}

    targets = dict(_verbs(state)["sell"])
    assert any(t.endswith("/hedge_berries") for t in targets)
    assert not any(label.endswith("(hot)") for label in targets.values())

    gold_before = state.stats.gold
    sale = trade.sell(state, "npc_maris", "hedge_berries", 1)
    assert sale["success"] is True
    assert state.stats.gold > gold_before
    assert state.provenance == {}


# -- a vendor who will not buy from you (v0.15, `refuses_to_buy`) ------------


def _at_grudge(welshed: bool) -> GameState:
    state = _mixed_state(clean=1, stolen_days=[1])
    state.location_id = BACK_ROOM
    if welshed:
        apply_effect(state, {"type": "flag", "flag": "welshed_on_grudge", "value": True})
    return state


def test_a_vendor_refuses_to_buy_while_her_condition_holds(market: None) -> None:
    state = _at_grudge(welshed=True)
    assert trade.refusal_to_buy(state, "npc_grudge") == (
        "Old Grudge buys nothing from someone who owes her ten crowns.")
    quote = trade.quote(state, "npc_grudge", RING, side="sell")
    assert quote["ok"] is False
    assert quote["reason"] == "Old Grudge buys nothing from someone who owes her ten crowns."
    gold, held = state.stats.gold, state.inventory[0].qty
    sale = trade.sell(state, "npc_grudge", RING, 1)
    assert sale["success"] is False and "owes her ten crowns" in sale["message"]
    assert state.stats.gold == gold and state.inventory[0].qty == held
    assert len(state.provenance[RING]) == 1     # nothing laundered
    assert "reported" not in sale                # a grudge is not a fencing deed


def test_a_refusing_vendor_is_not_offered_to_sell_to(market: None) -> None:
    """Rule 1: a sale the engine would refuse is unsamplable."""
    welshed = _at_grudge(welshed=True)
    assert "sell" not in _verbs(welshed)
    clean = _at_grudge(welshed=False)
    assert {t for t, _ in _verbs(clean)["sell"]} == {f"npc_grudge/{RING}"}


def test_a_refusing_vendor_still_sells_to_you(market: None) -> None:
    """`refuses_to_buy` is the buying side only: her shelves stay open."""
    state = _at_grudge(welshed=True)
    state.stats.gold = 10
    assert trade.quote(state, "npc_grudge", LOAF, side="buy")["ok"] is True
    assert trade.buy(state, "npc_grudge", LOAF, 1)["success"] is True


def test_a_vendor_whose_condition_does_not_hold_buys_as_before(market: None) -> None:
    state = _at_grudge(welshed=False)
    assert trade.refusal_to_buy(state, "npc_grudge") == ""
    assert trade.refusal_to_buy(state, "npc_fence") == ""   # no key at all
    assert trade.sell(state, "npc_grudge", RING, 1)["success"] is True
