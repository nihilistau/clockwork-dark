"""
The newly-reachable verbs, proven end to end.

``SKILL_FOR_ACTION`` carried seven verbs -- travel, rest, eat, check, buy, flag,
encounter -- while the engine shipped complete, tested implementations of
foraging, seventeen jobs, selling, haggling, crafting, set-pieces and threads
that no player choice could ever invoke. Note the asymmetry that made it
obvious in hindsight: ``buy`` was reachable and ``sell`` was not, so the economy
was a pure sink with no faucet. Meanwhile ``scripts/simulate.py`` -- the harness
that set every balance constant in ``config/default.yaml`` -- drove sell, forage,
work and set_piece directly. The numbers were tuned against a game nobody could
play.

WHY THESE TESTS EXIST IN THIS SHAPE. Each verb builder catches broadly, because
a story shipping no forage table must yield no verb rather than lose the turn.
That same catch hid two real signature bugs while this was being written --
``foraging.nodes_at`` and ``trade.vendors_at`` were both called with the wrong
arity, the TypeErrors were swallowed, and the verbs silently never appeared,
indistinguishable from "this story does not do that". So every assertion below
is that the verb IS OFFERED somewhere real, and that executing it MOVES
something. A test that only checked the tables would have passed throughout.
"""

from __future__ import annotations

import pytest

from engine.games import registry


@pytest.fixture
def flagship():
    registry.activate("clockwork-dark")
    try:
        yield
    finally:
        registry.deactivate()


def _state(location_id: str):
    from engine.game.state import GameState

    return GameState(location_id=location_id)


def _verbs(state) -> dict[str, tuple]:
    from engine.game.intents import legal_intents

    return {v.action: v.targets for v in legal_intents(state)}


# -- the verbs appear where the content says they should -----------------


def test_work_is_offered_where_there_is_a_shift(flagship) -> None:
    """Seventeen jobs shipped and no choice could reach any of them."""
    verbs = _verbs(_state("edgewood_bakery"))
    assert "work" in verbs, "the labour economy is unreachable again"
    assert "oven_shift" in verbs["work"]


def test_work_is_not_offered_where_there_is_no_work(flagship) -> None:
    """The negative control: a verb that is always offered is not a verb."""
    assert "work" not in _verbs(_state("forest_clearing"))


def _seeded_state(location_id: str):
    """
    A state built the way a real run builds one.

    The forage node pool is DEALT per save by ``engine/game/procgen.py``, so a
    bare ``GameState()`` has forageable tags and no nodes -- which is exactly
    the situation the verb must not offer itself in.
    """
    from engine.scenes.default_state import SessionStore

    session = SessionStore().create(seed=42)
    session.engine.state.location_id = location_id
    return session.engine.state


def test_forage_is_offered_where_there_is_ground_to_work(flagship) -> None:
    from engine.game import foraging

    state = _seeded_state("herb_glen")
    assert foraging.nodes_at(state, "herb_glen"), "this test needs dealt nodes"

    verbs = _verbs(state)
    assert "forage" in verbs
    assert verbs["forage"], "forage offered with no node to work"


def test_forage_is_not_offered_where_the_pool_dealt_nothing(flagship) -> None:
    """
    A tag alone is not enough. ``forageable()`` answers from location tags and
    the node pool is dealt per save, so a tag-only check offered a verb whose
    skill could only ever answer "you find no ground here worth working" -- a
    guaranteed refusal costing an option slot, an enum token in every prompt,
    and the player's turn.
    """
    from engine.game import foraging
    from engine.game.state import GameState

    bare = GameState(location_id="herb_glen")
    assert foraging.forageable("herb_glen"), "tags still admit foraging"
    assert not foraging.nodes_at(bare, "herb_glen"), "no nodes on a bare state"
    assert "forage" not in _verbs(bare)


def test_forage_is_not_offered_on_ground_that_grows_nothing(flagship) -> None:
    from engine.game import foraging

    assert not foraging.forageable("charcoal_burn")
    assert "forage" not in _verbs(_state("charcoal_burn"))


def test_sell_appears_only_with_something_a_vendor_will_take(flagship) -> None:
    """
    ``buy`` was reachable and ``sell`` was not: the economy was a sink with no
    faucet.
    """
    from engine.game.state import InventoryItem

    empty_handed = _state("edgewood_bakery")
    assert "sell" not in _verbs(empty_handed), "sell offered with nothing to sell"

    carrying = _state("edgewood_bakery")
    carrying.inventory.append(
        InventoryItem(id="hedge_berries", name="Hedge berries", qty=3)
    )
    verbs = _verbs(carrying)
    assert "sell" in verbs
    assert any(t.endswith("/hedge_berries") for t in verbs["sell"])


def test_a_sell_target_names_both_the_vendor_and_the_goods(flagship) -> None:
    """
    Same composite shape as ``buy``, for the same reason: a flat pair of enums
    would make "sell the baker's oven to the baker" samplable.
    """
    from engine.game.state import InventoryItem

    state = _state("edgewood_bakery")
    state.inventory.append(InventoryItem(id="hedge_berries", name="Berries", qty=1))
    for target in _verbs(state)["sell"]:
        npc_id, sep, item_id = target.partition("/")
        assert sep and npc_id and item_id, f"malformed sell target {target!r}"


# -- executing them actually moves the world -----------------------------


def test_working_a_shift_pays(flagship) -> None:
    from engine.agents.tool_dispatcher import execute_intent
    from engine.game.engine import GameEngine

    state = _state("edgewood_bakery")
    engine = GameEngine(state)
    before_gold = state.stats.gold
    before_hour = state.world_hour

    receipts = execute_intent({"action": "work", "target": "oven_shift"}, engine)

    assert receipts, "the work intent resolved to nothing"
    assert state.world_hour != before_hour or state.world_day != 1, (
        "a shift took no time"
    )
    # Pay depends on the roll, but the shift must have been RECORDED either way.
    from engine.game.economy import shifts_worked

    assert shifts_worked(state) == 1
    assert state.stats.gold >= before_gold


def test_selling_puts_gold_in_the_purse(flagship) -> None:
    from engine.agents.tool_dispatcher import execute_intent
    from engine.game.engine import GameEngine
    from engine.game.state import InventoryItem

    state = _state("edgewood_bakery")
    state.inventory.append(
        InventoryItem(id="hedge_berries", name="Hedge berries", qty=2)
    )
    engine = GameEngine(state)
    before = state.stats.gold

    target = next(t for t in _verbs(state)["sell"] if t.endswith("/hedge_berries"))
    receipts = execute_intent({"action": "sell", "target": target}, engine)

    assert receipts and receipts[0]["success"] is True, receipts
    assert state.stats.gold > before, "the sale paid nothing"


def test_foraging_spends_the_hours_whether_or_not_it_finds_anything(flagship) -> None:
    from engine.agents.tool_dispatcher import execute_intent
    from engine.game.engine import GameEngine

    state = _seeded_state("herb_glen")
    engine = GameEngine(state)
    before_stamina = state.stats.stamina
    node = _verbs(state)["forage"][0]

    receipts = execute_intent({"action": "forage", "target": node}, engine)

    assert receipts, "the forage intent resolved to nothing"
    assert state.stats.stamina < before_stamina, (
        "foraging cost nothing -- it is supposed to cost the hours and the "
        "stamina whether or not anything is found"
    )


# -- set-pieces ----------------------------------------------------------


def test_a_running_challenge_suppresses_every_other_verb(flagship) -> None:
    """
    Same rule as an encounter and a dealt card: while a set-piece is running
    the engine owns the option list, so the narrator cannot offer a road out of
    a gauntlet the runner still believes is open.
    """
    state = _state("edgewood_square")
    state.challenge = {
        "id": "probe",
        "kind": "decision_tree",
        "title": "A probe",
        "current": "start",
        "nodes": {
            "start": {
                "text": "Two doors.",
                "options": [
                    {"id": "left", "text": "Left"},
                    {"id": "right", "text": "Right"},
                ],
            }
        },
    }

    verbs = _verbs(state)
    assert list(verbs) == ["challenge"]
    assert set(verbs["challenge"]) == {"left", "right"}


def test_a_puzzle_offers_no_enum_because_its_answer_is_the_players_words(
    flagship,
) -> None:
    """
    The one verb whose target cannot be an enum. ``intent_schema`` already omits
    the target enum for a verb with no options, so this needs no special case.
    """
    state = _state("edgewood_square")
    state.challenge = {
        "id": "probe",
        "kind": "puzzle",
        "title": "A riddle",
        "prompt": "What has keys but opens nothing?",
        "answers": ["piano"],
        "attempts_left": 2,
    }

    verbs = _verbs(state)
    assert list(verbs) == ["challenge"]
    assert verbs["challenge"] == ()
