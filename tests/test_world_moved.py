"""
What the engine changed between turns reaches the prose on the turn it changed.

THE GAP. The clock layer writes authored prose into state -- a beat's ``text:``,
a world event's ``text``, a rumour -- and the prompt then printed only IDS:
``_events_block`` rendered "- forecast_traffic_spike at None (since day 14)".
Roughly fifteen authored lines across the shipped clock tables reached no
narrator. ``ledger.expire_promises`` returned the promises it broke to nobody,
and a veiled meter crossing a band ("unease: some -> high") was a ready story
beat that nothing surfaced.

THE SHAPE OF THE FIX. ``engine/game/moved.py`` is a per-turn journal written by
the system that caused each change, read by one prompt block, marked when a
prompt renders it and cleared once the narrator has written -- so each line is
mentioned on the turn it happened and never again, retries included. It is saved with the state, deliberately: an entry pending at
save time is a change the player has not yet been told about, and losing it on
reload would be the same bug one layer down.

Version: v0.1.0 [2026-09-23]
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

import pytest

from engine.agents import prompts
from engine.config import set_overlay
from engine.game import clock as clock_module
from engine.game import clocks, moved
from engine.game.state import GameState
from engine.state import active as active_state
from engine.state.schema import load_schema

GARDEN_SCHEMA = Path("games/wicked-garden") / "state.yaml"


def _story_paths(slug: str) -> dict[str, str]:
    from engine.games.registry import discover

    manifest = discover()[slug]
    return {k: str(v) for k, v in (manifest.paths or {}).items()}


@pytest.fixture()
def garden() -> Iterator[GameState]:
    """The Wicked Garden's shipped clocks, through the real loaders."""
    set_overlay({"paths": _story_paths("wicked-garden")})
    active_state._schema = load_schema(GARDEN_SCHEMA, slug="wicked-garden")
    state = GameState(rng_seed=42)
    try:
        yield state
    finally:
        active_state.reset_schema()
        set_overlay(None)


# ---------------------------------------------------------------------------
# The journal itself
# ---------------------------------------------------------------------------


def test_a_note_reaches_the_block_exactly_once() -> None:
    state = GameState(rng_seed=1)
    moved.note(state, "beat", "The roots are counting.")
    assert "The roots are counting." in prompts.moved_block(state)
    moved.mark_shown(state)
    # A retry rebuilds the prompt: what was shown is still there to show again.
    assert "The roots are counting." in prompts.moved_block(state)
    moved.clear_shown(state)
    assert prompts.moved_block(state) == ""


def test_what_arrives_after_the_prompt_waits_for_the_next_turn() -> None:
    state = GameState(rng_seed=1)
    moved.note(state, "beat", "Before the prompt.")
    moved.mark_shown(state)
    moved.note(state, "standing", "After the prose was written.")
    moved.clear_shown(state)
    assert [e["text"] for e in state.moved] == ["After the prose was written."]


def test_an_empty_journal_costs_nothing() -> None:
    """The line that keeps a quiet turn's prompt byte-identical."""
    assert prompts.moved_block(GameState(rng_seed=1)) == ""


def test_the_journal_survives_a_save() -> None:
    """Pending at save time means not yet told -- a reload must not lose it."""
    state = GameState(rng_seed=1)
    moved.note(state, "event", "The bells are ringing in the square.")
    loaded = GameState.from_dict(state.to_save_dict())
    assert [e["text"] for e in loaded.moved] == ["The bells are ringing in the square."]


def test_an_unknown_kind_is_a_programming_error() -> None:
    with pytest.raises(ValueError):
        moved.note(GameState(rng_seed=1), "vibes", "x")


def test_the_same_line_is_not_journalled_twice() -> None:
    state = GameState(rng_seed=1)
    moved.note(state, "beat", "Once.")
    moved.note(state, "beat", "Once.")
    assert len(state.moved) == 1


def test_an_entry_elsewhere_is_not_narrated_here() -> None:
    state = GameState(rng_seed=1)
    state.location_id = "edgewood_square"
    moved.note(state, "event", "A caravan unloads at the gate.", location_id="millhaven_gate")
    assert prompts.moved_block(state) == ""


# ---------------------------------------------------------------------------
# Driven through the real writers
# ---------------------------------------------------------------------------


def test_a_clock_world_event_is_journalled_with_its_words(garden: GameState) -> None:
    """briar_hunger_4 carries 'Something under the Garden keeps a slower time'."""
    clocks.advance(garden, "briar_hunger", 4, why="test")
    clock_module.advance_time(garden, 1)
    texts = [e["text"] for e in garden.moved]
    assert any("keeps a slower time" in t for t in texts), texts


def test_a_clock_beat_is_journalled_with_its_words(garden: GameState) -> None:
    """briar_hunger_full carries 'Tomorrow you grow or you feed.'"""
    clocks.advance(garden, "briar_hunger", 99, why="test")
    clock_module.advance_time(garden, 1)
    texts = [e["text"] for e in garden.moved]
    assert "Tomorrow you grow or you feed." in texts, texts


def test_a_clock_rumour_is_journalled(garden: GameState) -> None:
    clocks.advance(garden, "briar_hunger", 2, why="test")
    clock_module.advance_time(garden, 1)
    texts = [e["text"] for e in garden.moved]
    assert any("stopped walking the low paths" in t for t in texts), texts


def test_happening_now_prints_words_not_ids(garden: GameState) -> None:
    """It rendered '- briar_pulse at None (since day 1)'."""
    clocks.advance(garden, "briar_hunger", 4, why="test")
    clock_module.advance_time(garden, 1)
    block = prompts._events_block(garden)
    assert "briar_pulse" not in block
    assert "slower time" in block


def test_a_forced_scene_never_leaks_its_card_id(garden: GameState) -> None:
    """The fallback text was 'The story owes you: D8_06_briar_threshold'."""
    clocks.advance(garden, "briar_hunger", 99, why="test")
    clock_module.advance_time(garden, 1)
    rendered = prompts._events_block(garden) + prompts.moved_block(garden)
    assert "D8_06" not in rendered
    assert "owes you" not in rendered


def test_a_broken_promise_is_journalled_with_a_name() -> None:
    from types import SimpleNamespace

    from engine.games import registry
    from engine.scenes.default_state import SessionStore, _record_memory
    from engine.world import npc_sim

    registry.activate("neon-city")
    session = SessionStore().create(seed=7, llm_fn=lambda messages, **kw: "{}")
    state, ledger = session.engine.state, session.ledger
    who = npc_sim.known_npc_ids(state)[0]
    ledger.add_promise("the fuel money", from_id="player", to_id=who, due_day=0)
    from engine.game.clock import set_clock

    set_clock(state, day=state.world_day + 2, hour=8)  # tests-only, per its docstring
    _record_memory(session, "wait", SimpleNamespace(narration="You wait.", parsed={}))

    texts = [e["text"] for e in state.moved if e["kind"] == "promise"]
    assert texts and npc_sim.display_name(who, state) in texts[0], texts
    assert who not in texts[0] or who == npc_sim.display_name(who, state)


def test_a_veiled_meter_crossing_a_band_is_journalled_without_digits(garden: GameState) -> None:
    from engine.game.effects import apply_effect
    from engine.state.active import active_schema

    veiled = next(
        s
        for s in active_schema().values.values()
        if s.visibility == "veiled" and s.minimum is not None and s.maximum is not None
    )
    before = veiled.band(float(veiled.default))
    apply_effect(garden, {"type": "value", "name": veiled.name, "delta": 60, "why": "test"})
    rows = [e for e in garden.moved if e["kind"] == "band"]
    assert rows, f"{veiled.name} moved 60 and crossed no band from {before}?"
    assert not any(ch.isdigit() for ch in rows[0]["text"]), rows[0]["text"]


def test_gossip_in_the_players_room_is_overheard() -> None:
    """You walk in on somebody telling somebody else about you."""
    import random

    from engine.games import registry
    from engine.scenes.default_state import SessionStore
    from engine.world.gossip import spread

    registry.activate("clockwork-dark")
    session = SessionStore().create(seed=42, llm_fn=lambda messages, **kw: "{}")
    state, ledger = session.engine.state, session.ledger
    for who in ("npc_odran", "npc_villager_1", "npc_villager_2", "npc_villager_3"):
        ledger.add_fact(f"you spoke to them about the wood", subject_id=who, turn=1, day=1)
    rng = random.Random(7)
    for _ in range(40):
        spread(state, ledger, rng=rng)
    rows = [e for e in state.moved if e["kind"] == "gossip"]
    assert rows, "forty ticks in a crowded village and nothing was said"
    room = rows[0]["location_id"]
    state.location_id = room
    assert "about you" in prompts.moved_block(state)
    state.location_id = "nowhere_at_all"
    assert "about you" not in prompts.moved_block(state)
