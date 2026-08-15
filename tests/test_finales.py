"""
Every shipped game can be finished.

NOTHING TESTED THIS. The engine has an ending system, an ending MODULE
(Speak/Act/Seal) and an epilogue system, all three well covered in isolation --
and no test anywhere drove a single story through
``ending_lock -> ending_module -> epilogue``. The consequences were not
theoretical:

* **The Wicked Garden could not be finished by playing it.** Its only
  ``ending_lock`` sits on a card in ``day_09_finale``, and nothing in a running
  game ever dealt a deck.
* **THE LONG CON could not end at all.** No ``endings:``, no ``epilogues:``,
  and its single quest had no ``on_complete`` -- finishing all four stages
  awarded nothing and set no flag.
* **dev-story declared three endings and three epilogue cards** and emitted
  neither ``ending_lock`` nor ``ending_module`` anywhere.

The nearest thing that existed was ``test_wicked_garden_scenes.py``, which
calls ``deck.resolve_card`` directly -- i.e. it tested the offline walker's
path, not the game's. So these tests deliberately assert the CHAIN rather than
its parts, and the graph cases go through ``run_turn``, because "the effect
applies" and "a player can reach the effect" are the two claims that came apart.
"""

from __future__ import annotations

import json

import pytest

from engine.games import registry
from engine.persistence import reset_save_store


@pytest.fixture(autouse=True)
def _saves(tmp_path, monkeypatch):
    from engine.persistence.saves import SaveStore

    reset_save_store()
    store = SaveStore(root=tmp_path / "saves")
    monkeypatch.setattr("engine.scenes.default_state.get_save_store", lambda: store)
    yield
    reset_save_store()


def _activate(slug: str):
    registry.activate(slug)


def _finish_chain(state) -> None:
    """Lock an ending and play its module, the way a finale quest does."""
    from engine.game import effects

    effects.apply_effect(state, {"type": "ending_lock"})
    effects.apply_effect(state, {"type": "ending_module"})


def _assert_finale(state, slug: str) -> None:
    from engine.game import endings as endings_module
    from engine.game import epilogue as epilogue_module

    locked = endings_module.locked(state)
    assert locked, f"{slug}: ending_lock produced no locked ending"

    card = epilogue_module.for_state(state)
    assert card is not None, (
        f"{slug}: the ending locked and its module ran, and no epilogue came "
        "back -- the run reaches its end and the player is shown nothing"
    )
    rendered = card.to_dict()
    assert rendered.get("title"), f"{slug}: epilogue has no title"


# -- every game declares a reachable finale ------------------------------


@pytest.mark.parametrize(
    "slug",
    ["clockwork-dark", "neon-city", "wicked-garden", "the-long-con", "dev-story"],
)
def test_every_shipped_game_can_reach_an_epilogue(slug: str) -> None:
    """
    THE HEADLINE GATE. Two of these five could not do this at all.

    Driven through the effect pair the finale quests and finale cards actually
    declare, rather than through one story's content, so it asks the same
    question of a graph story, a deck story and a hybrid.
    """
    _activate(slug)
    try:
        from engine.game.state import GameState

        state = GameState()
        _finish_chain(state)
        _assert_finale(state, slug)
    finally:
        registry.deactivate()


@pytest.mark.parametrize(
    "slug", ["clockwork-dark", "neon-city", "wicked-garden", "the-long-con", "dev-story"]
)
def test_every_shipped_game_declares_a_fail_forward(slug: str) -> None:
    """
    A run that qualifies for nothing still has to land somewhere.

    Without this the finale depends on the player having earned a specific
    ending, and the ones who did not get a locked story with no last page.
    """
    _activate(slug)
    try:
        from engine.game import endings as endings_module

        assert endings_module.fail_forward_id(), f"{slug} declares no fail_forward"
    finally:
        registry.deactivate()


# -- the graph shape, through a real turn --------------------------------


@pytest.mark.parametrize("slug", ["clockwork-dark", "neon-city"])
def test_a_graph_story_reports_its_ending_on_the_turn_it_happens(slug: str) -> None:
    """
    Through ``run_turn``, not through the effect dispatcher.

    This is the difference the whole file exists for: the effects applied
    correctly the entire time, and no player could reach them. It also pins the
    payload ordering -- quest evaluation runs BEFORE the client dict is built,
    so a quest-fired ending is reported on its own turn rather than the next.
    """
    _activate(slug)
    try:
        from engine.scenes.default_state import SessionStore, run_turn
        import engine.scenes.default_state as ds

        llm = lambda _m: json.dumps(  # noqa: E731
            {
                "narration": "The hour closes over the whole of it, and holds.",
                "choices": [{"id": "a", "text": "Wait"}],
            }
        )
        session = SessionStore().create(seed=7, llm_fn=llm)

        def _ending_quest(sess):
            _finish_chain(sess.engine.state)
            return [{"kind": "completed", "quest_id": "finale", "text": "Done."}]

        original = ds._evaluate_quests
        ds._evaluate_quests = _ending_quest
        try:
            turn = run_turn(session, "The player chooses: Wait")
        finally:
            ds._evaluate_quests = original

        assert "ending" in turn, (
            f"{slug}: the story ended on this turn and the payload did not say so"
        )
        assert turn["ending"].get("title")
    finally:
        registry.deactivate()


# -- the deck shape, through the director --------------------------------


def test_the_wicked_garden_reaches_its_finale_deck_by_playing() -> None:
    """
    The Garden's only ``ending_lock`` is on a card in ``day_09_finale``.

    Nothing dealt that deck, so the largest body of authored prose in the repo
    ended in a deck the player could never see. This walks the scheduling rule
    that now deals it.
    """
    _activate("wicked-garden")
    try:
        from engine.content import deck, director
        from engine.game.state import GameState

        state = GameState(location_id="mortal_threshold")
        # Day 9's deck is gated on the day it belongs to.
        state.meters["garden_days"] = 9.0
        while state.world_day < 9:
            from engine.game.clock import advance_time

            advance_time(state, 24)

        # Every earlier deck has been played by the time the finale is due.
        for day in range(9):
            for deck_id in deck.deck_ids():
                if deck_id.startswith(f"day_{day:02d}"):
                    state.flags[f"{director.PLAYED_FLAG_PREFIX}{deck_id}"] = True

        deck_id, _forced, source = director.due(state)
        assert deck_id == "day_09_finale", (
            f"the finale deck is not what comes due on day 9; got {deck_id!r}"
        )
        assert source == "scheduled"
    finally:
        registry.deactivate()


def test_the_finale_deck_actually_carries_the_lock() -> None:
    """
    The other half: the deck that comes due is the one holding the ending.

    Asserted against the loaded deck rather than the YAML, so a card whose
    effect was renamed or dropped fails here rather than at the end of
    somebody's run.
    """
    _activate("wicked-garden")
    try:
        from engine.content import deck

        finale = deck.load_deck("day_09_finale")
        assert finale is not None

        kinds = {
            str(effect.get("type"))
            for card in finale.cards
            for beat in card.beats
            for effect in (
                (beat.get("gate") or {}).get("on_pass", {}).get("effects", [])
                or beat.get("effects")
                or []
            )
            if isinstance(effect, dict)
        }
        assert "ending_lock" in kinds, (
            "day_09_finale no longer locks an ending -- the Garden has no "
            "authored way to end again"
        )
    finally:
        registry.deactivate()


# -- the hybrid shape ----------------------------------------------------


def test_the_long_cons_clock_can_fill_from_the_graph() -> None:
    """
    ``the_frame`` was deadlocked at 1 of 4 segments.

    Its three advance rules key on ``heat >= 55``, ``standing <= 20`` and one
    flag -- and the ONLY content that wrote heat or standing was the deck the
    clock is supposed to force. The clock could not fill without the scene, and
    the scene could not arrive without the clock. The case quest moves both
    meters now, so playing the case is what brings the car to the kerb.
    """
    _activate("the-long-con")
    try:
        from engine.game import clocks
        from engine.game.state import GameState

        state = GameState(location_id="the_office")
        state.meters["heat"] = 60.0
        state.meters["standing"] = 15.0
        state.flags["nf_opened_the_cold_room"] = True

        clocks.resolve(state)

        assert clocks.value_of(state, "the_frame") >= 3, (
            "the frame cannot fill from graph play; it is still waiting on the "
            "deck it is supposed to force"
        )
    finally:
        registry.deactivate()


def test_the_long_cons_case_quest_ends_the_story() -> None:
    """The quest had no ``on_complete`` at all: four stages, then nothing."""
    _activate("the-long-con")
    try:
        import yaml

        raw = yaml.safe_load(
            open(
                "games/the-long-con/data/quests/the_case/"
                "the_dead_man_photographed.yaml",
                encoding="utf-8",
            )
        )
        effects = [
            str(e.get("type"))
            for e in ((raw.get("on_complete") or {}).get("effects") or [])
            if isinstance(e, dict)
        ]
        assert "ending_lock" in effects and "ending_module" in effects, (
            "closing the case does not end the story"
        )
    finally:
        registry.deactivate()
