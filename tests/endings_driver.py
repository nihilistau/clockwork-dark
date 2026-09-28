"""
Per-ending driver: one ending, through its real door, to its epilogue card.

WHY IT EXISTS. ``tests/test_finales.py`` asked each story one question --
"does SOME ending reach an epilogue?" -- through the bare effect pair
(``ending_lock`` + ``ending_module``). That is the question the old stories
failed, and it cannot see an ending whose door is broken while another's
works, or a door that locks the WRONG ending (an id-less lock resolving to a
fail-forward). HUE & CRY's eight endings (v0.17) each need the stronger claim:
THIS ending, through THIS door, shows THIS card.

WHAT A DRIVE IS.

1. Activate the story (``slug``), or use the config already in force
   (``slug=None``: a synthetic story a test installed with ``set_overlay``).
2. Build a state -- ``new_game_state(seed=..., location_id=...)`` -- or take
   the caller's.
3. Run ``setup(state)``. The setup puts the run where the door opens, and it
   writes state the way play would: through ``effects.apply_effect`` (flags,
   values, items, reports, arrests), moving time with ``clock.advance_time``
   (``set_clock`` only where a test must land on an exact hour), and setting
   ``state.location_id`` only to stand the player somewhere. A setup that
   pokes ``state.flags`` directly is testing a door no player can open.
4. Fire the REAL door -- the code a running game calls:

   ``Door.quest(quest_id)``
       ``QuestEngine.evaluate`` until the quest completes (at most a few
       passes: start, then stages). Its ``on_complete`` is the door.
   ``Door.card(deck_id, card_id, beat_id="", answers=None)``
       ``director.begin`` deals the deck with no shortcut: as ``director.due``
       deals it when it is due (scheduled, or forced by a clock or event);
       otherwise naturally, with the deck's ``when:`` asserted. A POOL card
       -- the seeded, weighted draw cannot be aimed -- is placed only after
       its own eligibility (``deck.eligible_cards``: ``when:``, ``once``,
       weight) is asserted, so a setup that never met the card's gate
       fails. The card must be in the dealt hand. Then the hand is played through
       ``director.resolve``: ``beat_id`` on the door card (a ``menu`` card's
       branch; empty for a ``sequence`` card), ``answers[card_id]`` or the
       first option on every other card. Play stops when the hand ends or
       the epilogue shows -- a finale deck usually locks on one card and
       plays the module on a later one.
   ``Door.set_piece(piece_id, *steps)``
       ``set_pieces.start``, then ``set_pieces.resolve(state, **step)`` for
       each step (``{"answer": ...}``, ``{"choice": ...}``, ``{"rng": ...}``)
       until the challenge closes. It must close in success.
   ``Door.death()``
       ``apply_effect`` an ``hp`` delta to 0, then ``encounter.check_death``
       -- a terminal ``death.yaml`` block is the door.

5. Assert ``endings.locked(state) == ending_id`` -- for a card door, unlocked
   just before the door card and locked straight after it -- and that ``epilogue.for_state(state)``
   is that ending's card: its ``ending_id`` and its declared title.

Returns ``(state, epilogue)`` for a caller with more to assert.

REGISTERING A STORY'S DOORS. ``tests/test_finales.py`` holds
``ENDING_DOORS``, one row per ending::

    EndingDoor(
        slug="hue-and-cry",
        ending_id="honest_after_all",
        door=Door.quest("the_evening_barge"),
        setup=_board_the_evening_barge,     # Callable[[GameState], None]
        seed=11,                            # optional
        location_id="",                     # optional; "" = the entry
    )

and a story listed in ``COMPLETE_DOORS`` there must register a door for
EVERY ending it declares -- a new ending without one fails the suite.

Version: v0.1.0 [2026-09-27]
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from engine.game.state import GameState

#: How many ``QuestEngine.evaluate`` passes a quest door may take: one to
#: start it, one per stage, and slack. Bounded, so a door that never opens
#: fails instead of spinning.
MAX_QUEST_PASSES = 8

#: A hand is never longer than this (``director.MAX_SCENE_CARDS``); the
#: play-on loop is bounded by it twice over.
MAX_PLAY_ON = 64


@dataclass(frozen=True)
class Door:
    """Which authored thing ends the run. Build one with the class methods."""

    kind: str
    target: str = ""
    card: str = ""
    beat: str = ""
    answers: dict[str, str] = field(default_factory=dict)
    steps: tuple[dict[str, Any], ...] = ()

    @classmethod
    def quest(cls, quest_id: str) -> "Door":
        return cls(kind="quest", target=quest_id)

    @classmethod
    def card(
        cls, deck_id: str, card_id: str, beat_id: str = "",
        answers: Optional[dict[str, str]] = None,
    ) -> "Door":
        return cls(kind="card", target=deck_id, card=card_id, beat=beat_id,
                   answers=dict(answers or {}))

    @classmethod
    def set_piece(cls, piece_id: str, *steps: dict[str, Any]) -> "Door":
        return cls(kind="set_piece", target=piece_id, steps=tuple(steps))

    @classmethod
    def death(cls) -> "Door":
        return cls(kind="death")

    def label(self) -> str:
        """A short id for a parametrized test."""
        if self.kind == "card":
            return f"card:{self.target}/{self.card}{'/' + self.beat if self.beat else ''}"
        return f"{self.kind}:{self.target}" if self.target else self.kind


@dataclass(frozen=True)
class EndingDoor:
    """One registered ending: a story, the ending, its door and its setup."""

    slug: str
    ending_id: str
    door: Door
    setup: Optional[Callable[[GameState], None]] = None
    seed: int = 7
    location_id: str = ""

    def label(self) -> str:
        return f"{self.slug}:{self.ending_id}"


# ---------------------------------------------------------------------------
# The doors
# ---------------------------------------------------------------------------


def _fire_quest(state: GameState, door: Door) -> None:
    from engine.game.quests import STATUS_COMPLETED, QuestEngine, progress_records

    for _ in range(MAX_QUEST_PASSES):
        QuestEngine.evaluate(state)
        record = progress_records(state).get(door.target)
        if record is not None and record.status == STATUS_COMPLETED:
            return
    record = progress_records(state).get(door.target)
    raise AssertionError(
        f"quest door {door.target!r} never completed: "
        f"{record.to_dict() if record else 'never started'}"
    )


def _fire_card(state: GameState, door: Door, ending_id: str) -> None:
    from engine.content import deck as deck_module
    from engine.content import director
    from engine.game import endings, epilogue

    deck = deck_module.load_deck(door.target)
    assert deck is not None, f"card door: no deck {door.target!r}"
    by_id = {c.id: c for c in deck.cards}
    assert door.card in by_id, f"card door: {door.card!r} is not in {door.target!r}"
    card = by_id[door.card]
    if door.beat:
        assert door.beat in {str(b.get("id")) for b in card.beats}, (
            f"card door: {door.beat!r} is not a beat of {door.card!r}"
        )
    # NO SHORTCUT DEAL. `begin(forced_card=...)` puts a card first in the hand
    # whatever its own `when:` says, so forcing a card the run has not earned
    # would pass a door no player can open. Three honest ways in, in order:
    #   1. the director says this deck is due (scheduled, or forced by a
    #      clock beat or event) -- dealt exactly as `ensure_scene` would;
    #   2. a required card -- dealt naturally; the deck's `when:` must hold
    #      (`draw` refuses otherwise);
    #   3. a pool card -- the draw is weighted and seeded, so it cannot be
    #      aimed at; instead the deck's `when:` AND the card's own
    #      eligibility (`deck.eligible_cards`: its `when:`, `once`, weight)
    #      are asserted first, and only then is it placed.
    from engine.game.quests import evaluate_condition

    due_deck, due_card, source = director.due(state)
    if due_deck == door.target:
        forced, how = due_card, source
    else:
        assert evaluate_condition(state, deck.when), (
            f"card door: {door.target!r}'s own `when:` does not hold, so no deal "
            "could reach it"
        )
        forced, how = "", "scheduled"
        if door.card not in {c.id for c in deck.required}:
            eligible, rejected = deck_module.eligible_cards(state, deck)
            assert door.card in {c.id for c in eligible}, (
                f"card door: {door.card!r} is not eligible "
                f"({rejected.get(door.card, 'not in the pool')}); the setup has "
                "not met its gate"
            )
            forced = door.card
    receipt = director.begin(state, door.target, forced_card=forced, source=how)
    assert receipt.get("ok"), f"card door: {door.target!r} dealt nothing: {receipt}"
    assert door.card in receipt["card_ids"], (
        f"card door: {door.card!r} is not in the hand {receipt['card_ids']}"
    )

    played_door = False
    for _ in range(MAX_PLAY_ON):
        if not director.active(state) or epilogue.for_state(state) is not None:
            break
        current = director.current_card(state)
        assert current is not None
        if current.id == door.card:
            assert endings.locked(state) == endings.NONE_ID, (
                f"card door: {endings.locked(state)!r} was locked before "
                f"{door.card!r} was played, so it is not the door"
            )
            is_menu = deck_module.MENU_TAG in current.tags
            chosen = door.beat if is_menu else ""
            out = director.resolve(state, chosen=chosen)
            assert out.get("ok"), f"card door: {door.card!r} refused: {out}"
            played_door = True
            assert endings.locked(state) == ending_id, (
                f"card door {door.card!r} resolved and locked "
                f"{endings.locked(state)!r}, not {ending_id!r}"
            )
            continue
        chosen = door.answers.get(current.id) or director.options(state)[0]["id"]
        out = director.resolve(state, chosen=chosen)
        assert out.get("ok"), f"card door: {current.id!r} refused {chosen!r}: {out}"
    assert played_door, f"card door: the hand ended before {door.card!r} was played"


def _fire_set_piece(state: GameState, door: Door) -> None:
    from engine.challenges import runner, set_pieces

    started = set_pieces.start(state, door.target)
    assert started.status != runner.STATUS_ERROR, (
        f"set-piece door {door.target!r} would not start: {started.text}"
    )
    result = started
    for step in door.steps:
        if not state.challenge:
            break
        result = set_pieces.resolve(state, **step)
    assert not state.challenge, f"set-piece door {door.target!r} is still open"
    assert result.ended and result.success, (
        f"set-piece door {door.target!r} did not end in success: {result.status}"
    )


def _fire_death(state: GameState) -> None:
    from engine.game import encounter
    from engine.game.effects import apply_effect

    hp = int(state.stats.hp)
    if hp > 0:
        apply_effect(state, {"type": "hp", "delta": -hp})
    death = encounter.check_death(state)
    assert death is not None and death.get("terminal"), (
        f"death door: the death was not terminal: {death}"
    )


# ---------------------------------------------------------------------------
# The drive
# ---------------------------------------------------------------------------


def drive_ending(
    slug: Optional[str],
    ending_id: str,
    door: Door,
    setup: Optional[Callable[[GameState], None]] = None,
    *,
    state: Optional[GameState] = None,
    seed: int = 7,
    location_id: str = "",
) -> tuple[GameState, Any]:
    """
    Drive ``ending_id`` through ``door`` and assert its epilogue card.

    Args:
        slug: The story to activate, or None to use the config in force
            (a synthetic story installed with ``set_overlay``).
        ending_id: The ending the door must lock.
        door: See the module docstring.
        setup: ``setup(state)``, run before the door; writes through
            ``apply_effect`` (module docstring, step 3).
        state: A ready state. Default: ``new_game_state(seed, location_id)``.
        seed: For the default state.
        location_id: For the default state; "" means the story's entry.

    Returns:
        ``(state, epilogue)``.
    """
    from engine.games import registry

    if slug is not None:
        registry.activate(slug)
    try:
        return _drive(ending_id, door, setup, state=state, seed=seed,
                      location_id=location_id, slug=slug)
    finally:
        if slug is not None:
            registry.deactivate()


def drive(case: EndingDoor) -> tuple[GameState, Any]:
    """``drive_ending`` for one registered row."""
    return drive_ending(case.slug, case.ending_id, case.door, case.setup,
                        seed=case.seed, location_id=case.location_id)


def _drive(
    ending_id: str,
    door: Door,
    setup: Optional[Callable[[GameState], None]],
    *,
    state: Optional[GameState],
    seed: int,
    location_id: str,
    slug: Optional[str],
) -> tuple[GameState, Any]:
    from engine.game import endings, epilogue

    declared_endings = endings.declared()
    assert ending_id in declared_endings, (
        f"{ending_id!r} is not an ending this story declares: {sorted(declared_endings)}"
    )
    card_row = epilogue.declared().get(ending_id)
    assert card_row, f"{ending_id!r} has no epilogue card"

    if state is None:
        from engine.game.procgen import new_game_state

        where = location_id
        if not where and slug is not None:
            from engine.games import registry

            where = registry.get(slug).entry_location or ""
        state = new_game_state(seed=seed, location_id=where or None)
    assert endings.locked(state) == endings.NONE_ID, "the run is already locked"
    if setup is not None:
        setup(state)
    assert endings.locked(state) == endings.NONE_ID, (
        f"the setup locked {endings.locked(state)!r} itself; the door must"
    )

    if door.kind == "quest":
        _fire_quest(state, door)
    elif door.kind == "card":
        _fire_card(state, door, ending_id)
    elif door.kind == "set_piece":
        _fire_set_piece(state, door)
    elif door.kind == "death":
        _fire_death(state)
    else:
        raise AssertionError(f"unknown door kind {door.kind!r}")

    assert endings.locked(state) == ending_id, (
        f"{door.label()} locked {endings.locked(state)!r}, not {ending_id!r}"
    )
    shown = epilogue.for_state(state)
    assert shown is not None, (
        f"{door.label()} locked {ending_id!r} and no epilogue came back "
        f"(module ran: {endings.module_ran(state)!r})"
    )
    assert shown.ending_id == ending_id, shown.ending_id
    assert shown.title == str(card_row.get("title") or ending_id), shown.title
    return state, shown


__all__ = ["Door", "EndingDoor", "drive", "drive_ending"]
