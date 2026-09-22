"""
What the engine resolved reaches the narrator as events, never as bookkeeping.

THREE LEAKS, ONE CLASS: the prompt carried numbers the story had chosen to keep
from the prose.

  * ``pipeline.narration_block`` printed ``name after`` for every committed
    receipt -- so a VEILED meter reached the narrator as an integer, despite the
    receipt carrying a ``visibility`` field that exists for exactly this.
  * ``prompts.receipts_block`` fell through to ``f"- {skill} -> {result}"`` for
    every skill it did not special-case. A forage receipt measured ~1,600
    characters, including the DC, every roll and "stamina 94".
  * The ``scene_begin`` receipt listed the whole hand's card ids -- a spoiler for
    every card the player had not reached yet.

And one bug found on the way, in the same place: ``work`` reported how a shift
WENT under the key the intent layer reads to decide whether it HAPPENED, so
every shift worked badly was narrated as refused -- "did NOT happen" -- with its
hours and stamina really spent.

Version: v0.1.0 [2026-09-23]
"""

from __future__ import annotations

import re
from types import SimpleNamespace

import pytest

from engine.agents import prompts
from engine.agents.pipeline import narration_block

#: A number the narrator must not be handed: two or more digits, or a DC.
_NUMBERISH = re.compile(r"\b\d{2,}\b|\bdc\b", re.IGNORECASE)


def _pipeline_result(receipts):
    turn = SimpleNamespace(
        accepted=True, lead="world", beats=[], resolutions=[], blocked=[], choices=[]
    )
    return SimpleNamespace(
        ran=True, turn=turn, receipts=receipts, speaker=lambda: None
    )


def test_a_veiled_value_reaches_the_narrator_as_a_band() -> None:
    from engine.state import active as active_state
    from engine.state.schema import load_schema

    active_state._schema = load_schema("games/wicked-garden/state.yaml", slug="wicked-garden")
    try:
        spec = next(
            s
            for s in active_state.active_schema().values.values()
            if s.visibility == "veiled" and s.minimum is not None and s.maximum is not None
        )
        text = narration_block(
            _pipeline_result(
                [{"name": spec.name, "after": 55, "visibility": "veiled", "ok": True}]
            )
        )
    finally:
        active_state.reset_schema()
    assert "55" not in text
    assert spec.band(55) in text


def test_a_hidden_value_is_not_mentioned_at_all() -> None:
    text = narration_block(
        _pipeline_result([{"name": "suspicion", "after": 70, "visibility": "hidden", "ok": True}])
    )
    assert "suspicion" not in text and "70" not in text


FORAGE = {
    "skill": "forage",
    "success": True,
    "result": {
        "success": True,
        "location_id": "forest_clearing",
        "node_id": "forage_4",
        "resource": "herb",
        "check": {"dc": 10, "total": 6, "degree": "partial", "success": False,
                  "summary": "survival (easy): d20 4 +2 = 6 vs DC 10"},
        "found": [{"item_id": "wild_sage", "name": "Wild sage", "qty": 1}],
        "stamina": 94,
    },
}

WORK = {
    "skill": "work",
    "success": True,
    "result": {"success": True, "worked": True, "job_id": "courier_run",
               "name": "Run a package for the Grid", "degree": "success", "wage": 40,
               "check": {"dc": 13, "total": 15}, "gold": 1735, "hours": 4.0,
               "text": "The package arrives dry, which is the whole job."},
}

BUY = {
    "skill": "trade",
    "success": True,
    "result": {"success": True, "vendor": "Mira Vex", "name": "Cooldown Spoof",
               "qty": 1, "gold_spent": 330, "gold": 1670,
               "quote": {"breakdown": {"standing_multiplier": 1.1}}},
}


@pytest.mark.parametrize("receipt", [FORAGE, WORK, BUY], ids=["forage", "work", "buy"])
def test_no_receipt_is_dumped_as_a_dict(receipt) -> None:
    block = prompts.receipts_block([receipt])
    body = block.split("\n", 2)[-1]
    assert "{" not in body and "'" not in body, body
    assert len(body) < 320, body


def test_forage_says_what_was_found_and_not_the_arithmetic() -> None:
    body = prompts.receipts_block([FORAGE]).split("\n", 2)[-1]
    assert "Wild sage" in body
    assert "94" not in body and not re.search(r"\bdc\b", body, re.IGNORECASE), body


def test_a_purchase_names_the_goods_and_the_price() -> None:
    """The price is a number the player just paid -- that one the prose may say."""
    body = prompts.receipts_block([BUY]).split("\n", 2)[-1]
    assert "Cooldown Spoof" in body and "Mira Vex" in body and "330" in body
    assert "1670" not in body, "the purse after is bookkeeping, not an event"


def test_scene_begin_does_not_spoil_the_hand() -> None:
    receipt = {"skill": "scene_begin", "success": True,
               "result": {"ok": True, "deck_id": "day_01", "card_ids": ["c1", "c2", "c3"]}}
    body = prompts.receipts_block([receipt])
    assert "c2" not in body and "c3" not in body


def test_an_unknown_skill_still_renders_as_words() -> None:
    receipt = {"skill": "some_future_skill", "success": True,
               "result": {"success": True, "secret_number": 77}}
    body = prompts.receipts_block([receipt]).split("\n", 2)[-1]
    assert "77" not in body and "{" not in body


def test_a_shift_worked_badly_is_not_a_refusal() -> None:
    """Driven through the real dispatcher: hours spent, so it happened."""
    from engine.agents.tool_dispatcher import execute_intent
    from engine.game import intents
    from engine.games import registry
    from engine.scenes.default_state import SessionStore

    registry.activate("neon-city")
    for seed in range(1, 40):
        session = SessionStore().create(seed=seed, llm_fn=lambda messages, **kw: "{}")
        work = intents.find_verb(intents.legal_intents(session.engine.state), "work")
        if work is None or not work.targets:
            continue
        receipt = execute_intent(
            {"action": "work", "target": list(work.targets)[0]}, session.engine
        )[0]
        if receipt["result"].get("degree") != "failure":
            continue
        assert not receipt.get("refused"), receipt
        assert "did NOT happen" not in prompts.receipts_block([receipt])
        return
    pytest.skip("no seed in range rolled a failed shift")


def test_money_is_written_in_the_storys_own_currency() -> None:
    """The buy label hardcoded "g"; NEON CITY is a credits economy."""
    from engine.game.trade import currency_label
    from engine.games import registry

    registry.activate("neon-city")
    assert currency_label(330) == "₵330"
    registry.activate("the-long-con")
    assert currency_label(12) == "$12"
    registry.activate("clockwork-dark")
    assert currency_label(12) == "12g"
