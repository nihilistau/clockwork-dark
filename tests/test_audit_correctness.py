"""
The v0.8 correctness batch: small seams where the engine said one thing and
did another.

Each test here failed against the code before its fix. Grouped by the audit's
numbering (A6a..A6h) so a regression names the finding it reopens.

Version: v0.1.0 [2026-09-23]
"""

from __future__ import annotations

import logging

import pytest

from engine.game import trade
from engine.game.clock import set_clock
from engine.games import registry
from engine.scenes.default_state import SessionStore
from engine.world import npc_sim


def _session(slug: str):
    registry.activate(slug)
    return SessionStore().create(seed=3, llm_fn=lambda messages, **kw: "{}")


# ---------------------------------------------------------------------------
# A6a -- a vendor trades where their schedule puts them
# ---------------------------------------------------------------------------
#
# `vendors_at` read the static counter in trade.yaml, so at edgewood_square at
# 11:00 "sell to npc_brindle" was offered while Brindle's own schedule had her
# at forest_clearing. Measuring every vendor against its schedule also found a
# shop that could NEVER have opened honestly: Odran's counter was
# tinker_caravan and his schedule never takes him there -- he hawks off the cart
# tail in edgewood_square all day.

SCHEDULED_TRADERS = ["clockwork-dark", "neon-city", "the-long-con"]


def test_a_vendor_away_from_their_counter_does_not_trade() -> None:
    session = _session("clockwork-dark")
    state = session.engine.state
    counter = trade.vendor_location("npc_brindle")
    for hour in range(24):
        set_clock(state, day=1, hour=hour)
        presence = npc_sim.resolve_npc(state, "npc_brindle")
        if presence.location_id != counter:
            assert "npc_brindle" not in trade.vendors_at(counter, state=state), hour
            return
    pytest.fail("Brindle never leaves her counter; the fixture assumption is broken")


def test_a_vendor_at_their_counter_trades() -> None:
    session = _session("clockwork-dark")
    state = session.engine.state
    counter = trade.vendor_location("npc_maris")
    for hour in range(24):
        set_clock(state, day=1, hour=hour)
        presence = npc_sim.resolve_npc(state, "npc_maris")
        if presence.location_id == counter and presence.available:
            assert "npc_maris" in trade.vendors_at(counter, state=state)
            return
    pytest.fail("Maris is never at her counter")


def test_a_sleeping_vendor_does_not_trade() -> None:
    session = _session("clockwork-dark")
    state = session.engine.state
    for hour in range(24):
        set_clock(state, day=1, hour=hour)
        presence = npc_sim.resolve_npc(state, "npc_odran")
        if not presence.available:
            assert "npc_odran" not in trade.vendors_at(presence.location_id, state=state)
            return
    pytest.fail("Odran never sleeps")


@pytest.mark.parametrize("slug", SCHEDULED_TRADERS)
def test_every_scheduled_vendor_is_at_their_counter_some_hour(slug: str) -> None:
    """A counter the schedule never visits is a shop that can never open."""
    session = _session(slug)
    state = session.engine.state
    scheduled = (npc_sim.load_npc_schedules().get("npcs") or {}).keys()
    never_open = []
    for npc_id, profile in trade.vendors().items():
        if npc_id not in scheduled:
            continue
        counter = str(profile.get("location") or "")
        open_hours = 0
        for hour in range(24):
            set_clock(state, day=1, hour=hour)
            presence = npc_sim.resolve_npc(state, npc_id)
            if presence and presence.location_id == counter and presence.available:
                open_hours += 1
        if not open_hours:
            never_open.append((npc_id, counter))
    assert not never_open, f"{slug}: counters no schedule ever reaches: {never_open}"


def test_the_map_still_shows_where_a_stall_is() -> None:
    """Without state, it answers 'where is the counter' -- the map's question."""
    _session("clockwork-dark")
    assert "npc_brindle" in trade.vendors_at(trade.vendor_location("npc_brindle"))


def test_a_sale_is_counted_out_in_the_storys_money() -> None:
    """The sell receipt hardcoded "c" beside a hardcoded "g" on the buy label."""
    from engine.agents.tool_dispatcher import execute_intent
    from engine.game import intents

    session = _session("neon-city")
    sell = intents.find_verb(intents.legal_intents(session.engine.state), "sell")
    assert sell is not None and sell.targets
    receipt = execute_intent(
        {"action": "sell", "target": list(sell.targets)[0]}, session.engine
    )[0]
    assert "₵" in receipt["result"]["text"], receipt["result"]["text"]


# ---------------------------------------------------------------------------
# A6b -- an agent's choice survives the merge
# ---------------------------------------------------------------------------
#
# The narrator's choices went first with a limit of four, and the turn schema
# lets the narrator write four. Whenever it did, every choice an agent put on
# the table -- the thing that lets a companion say "not that door" -- was lost.


def test_an_agent_choice_survives_four_narrated_ones() -> None:
    from engine.agents.negotiate import NegotiatedTurn
    from engine.agents.pipeline import PipelineResult, merge_choices
    from engine.agents.plan import ProposedChoice

    turn = NegotiatedTurn()
    turn.choices = [ProposedChoice(text="Not that door.", source="pip")]
    result = PipelineResult(ran=True, turn=turn)
    narrated = [{"id": c, "text": f"option {c}"} for c in "abcd"]

    merged = merge_choices(result, narrated, limit=4)
    assert len(merged) == 4
    assert "Not that door." in [row["text"] for row in merged]
    assert [row["id"] for row in merged] == ["a", "b", "c", "d"]


def test_with_no_agent_choices_the_narrator_keeps_all_four() -> None:
    from engine.agents.pipeline import PipelineResult, merge_choices

    narrated = [{"id": c, "text": f"option {c}"} for c in "abcd"]
    merged = merge_choices(PipelineResult(ran=False), narrated, limit=4)
    assert [row["text"] for row in merged] == [f"option {c}" for c in "abcd"]


# ---------------------------------------------------------------------------
# A6c -- reputation has one writer and one clamp
# ---------------------------------------------------------------------------
#
# `economy.work` called `reputation.adjust` directly, around `apply_effect`
# (CLAUDE.md rule 3), and the two writers clamped differently: `adjust` by the
# faction's own bounds, the effect kind by a global -100..100.


def test_a_shift_moves_standing_through_the_one_writer(monkeypatch) -> None:
    from engine.game import economy, effects
    from engine.game.procgen import new_game_state

    seen: list[dict] = []
    real = effects.apply_effect

    def spy(state, effect, **kw):
        seen.append(dict(effect))
        return real(state, effect, **kw)

    monkeypatch.setattr(effects, "apply_effect", spy)
    for seed in range(1, 30):
        state = new_game_state(seed=seed, location_id="edgewood_bakery")
        outcome = economy.work(state, "oven_shift")
        if outcome.get("reputation"):
            assert any(e.get("type") == "reputation" for e in seen), seen
            return
    pytest.fail("no seed produced a standing change")


def test_the_effect_kind_uses_the_factions_own_bounds() -> None:
    from engine.game import reputation
    from engine.game.effects import apply_effect
    from engine.game.procgen import new_game_state

    state = new_game_state(seed=1, location_id="edgewood_bakery")
    faction = next(iter((reputation.load_factions().get("factions") or {})))
    low, high = reputation._bounds(faction)
    apply_effect(state, {"type": "reputation", "faction": faction, "delta": 10_000})
    assert state.reputations[faction] == high


# ---------------------------------------------------------------------------
# A6d -- the director does not loop on a promise it cannot keep
# ---------------------------------------------------------------------------


def test_a_deck_that_deals_nothing_is_not_due_again(monkeypatch) -> None:
    """It came due every turn and the narrator read 'no cards were eligible' every turn."""
    from engine.content import deck as deck_module
    from engine.content import director

    session = _session("wicked-garden")
    state = session.engine.state
    deck_id = deck_module.deck_ids()[0]
    empty = type("Hand", (), {"cards": [], "rejected": {"all": "test"}})()
    monkeypatch.setattr(deck_module, "draw", lambda *a, **k: empty)

    receipt = director.begin(state, deck_id)
    assert receipt["ok"] is False
    assert state.flags.get(director._played_flag(deck_id)), "an empty deck stays due forever"


def test_an_unanswerable_forced_scene_warns_once(monkeypatch, caplog) -> None:
    from engine.content import director
    from engine.game import clocks

    session = _session("wicked-garden")
    state = session.engine.state
    monkeypatch.setattr(clocks, "forced_scenes", lambda s: ["no_such_scene_anywhere"])
    with caplog.at_level(logging.WARNING, logger="engine.content.director"):
        for _ in range(3):
            director.due(state)
    warnings = [r for r in caplog.records if "neither a deck nor a card" in r.getMessage()]
    assert len(warnings) == 1, [r.getMessage() for r in warnings]


# ---------------------------------------------------------------------------
# A6e -- a pipeline failure costs the negotiation, not the turn
# ---------------------------------------------------------------------------


def test_a_pipeline_that_raises_degrades_the_turn(monkeypatch, caplog) -> None:
    from engine.scenes import default_state

    session = _session("dev-story")

    def boom(*a, **k):
        raise RuntimeError("negotiation exploded")

    monkeypatch.setattr(default_state, "run_pipeline", boom)
    with caplog.at_level(logging.WARNING):
        payload = default_state.run_turn(session, "look around")
    assert payload.get("narration") is not None
    assert any("negotiation exploded" in r.getMessage() or "pipeline" in r.getMessage().lower()
               for r in caplog.records if r.levelno >= logging.WARNING)


# ---------------------------------------------------------------------------
# A6f -- the objectives block names the real lever
# ---------------------------------------------------------------------------


def test_the_objectives_block_names_the_flag_intent_and_skips_raised_flags(monkeypatch) -> None:
    """
    It told the model to "Call set_narrative_flag" -- a tool the turn grammar
    gives it no way to call -- and listed flags already raised as beats still
    to reach.
    """
    from engine.agents import prompts
    from engine.game.quests import QuestEngine
    from engine.game.state import GameState

    monkeypatch.setattr(QuestEngine, "active_objectives", staticmethod(lambda s: ["Find the tinker."]))
    monkeypatch.setattr(
        QuestEngine, "allowed_narrative_flags", staticmethod(lambda s: ["met_tinker", "heard_bells"])
    )
    state = GameState()
    state.flags["heard_bells"] = True

    block = prompts._objectives_block(state)
    assert "Find the tinker." in block
    assert "set_narrative_flag" not in block
    assert "`flag` intent" in block
    assert "met_tinker" in block and "heard_bells" not in block


# ---------------------------------------------------------------------------
# A6h -- no flagship furniture in the shared engine
# ---------------------------------------------------------------------------


def test_the_tone_scorer_has_no_favourite_story() -> None:
    from engine.agents.evaluator import StorytellerEvaluator

    flagship = StorytellerEvaluator._score_tone("Mist over the oven and the forest road.")
    neon = StorytellerEvaluator._score_tone("Rain on the neon and the grid below.")
    assert flagship == neon


def test_a_speaking_agent_is_not_assumed_to_be_her() -> None:
    from types import SimpleNamespace

    from engine.agents.pipeline import narration_block

    turn = SimpleNamespace(accepted=True, lead="pip", beats=[], resolutions=[],
                           blocked=[], choices=[])
    result = SimpleNamespace(
        ran=True, turn=turn, receipts=[],
        speaker=lambda: SimpleNamespace(agent="pip", line="Shiny."),
    )
    text = narration_block(result)
    assert "Shiny." in text
    assert " her " not in text
