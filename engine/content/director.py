"""
Scene Director
==============

Deals an authored scene into a running turn, and lets the player answer it.

WHAT THIS CLOSES. ``engine/content/deck.py`` is 830 lines of dealing, gating,
weighting and beat resolution, and until this module existed ``draw`` and
``resolve_card`` were called by exactly two things: ``scripts/simulate_decks.py``
and the tests. Nothing in a running game ever dealt a hand.

The cost of that was not theoretical. The Wicked Garden ships 11 decks, 136
cards and 386 beats -- the largest body of authored prose in the repo -- and its
only ``ending_lock`` sits on a card in ``day_09_finale``. A deck nothing deals
is an ending nothing reaches: **the game could not be finished by playing it**.
THE LONG CON's whole pitch is a clock whose ``forces_scene`` deals an authored
interrogation mid-run, and ``clocks.forced_scenes()`` -- whose own docstring
says "this is the query a scene director answers" -- had no caller either.

THE SHAPE IS NOT NEW. This deliberately mirrors ``engine/game/encounter.py``
function for function: an engine-owned scene that occupies a turn, suppresses
the other verbs while it is open, and is resolved by ONE intent verb backed by
ONE skill. Encounters have worked that way since they shipped, so a second
scene system inventing a second shape would be the actual risk here.

INERT BY CONSTRUCTION, NOT BY CARE. ``deck_ids()`` reads ``paths.decks``, and
The Clockwork Dark and NEON CITY declare no such path -- so it returns ``[]``,
``due()`` returns None on its first line, and their turns are byte-for-byte what
they were. That is a property of the data, not a flag anyone has to remember to
set, and ``tests/test_scene_director.py`` asserts it rather than trusting it.

WHY IDS AND NOT CARDS. ``state.scene`` stores card ids. ``load_deck`` is cached
on (path, mtime), so re-resolving an id costs nothing, the save stays small, and
editing a deck mid-run degrades to "that card is gone, skip it" instead of
replaying a stale copy the author has since rewritten.

Version: v0.1.0 [2026-08-15]
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from engine.content import deck as deck_module
from engine.game import clocks as clocks_module
from engine.game.state import GameState

logger = logging.getLogger(__name__)

#: A hand can never own more turns than this, whatever the content says. A
#: ``required``-heavy deck plus a clock that refills on its own setpiece is a
#: loop, and a loop here is a run that cannot be played out of.
MAX_SCENE_CARDS = 32

#: Flag marking a deck as already dealt this run, so scheduled decks do not
#: re-deal every turn their ``when`` is true.
PLAYED_FLAG_PREFIX = "deck_played_"


def _played_flag(deck_id: str) -> str:
    return f"{PLAYED_FLAG_PREFIX}{deck_id}"


# ---------------------------------------------------------------------------
# Lifecycle -- mirrors engine/game/encounter.py
# ---------------------------------------------------------------------------


def active(state: GameState) -> bool:
    """True while a dealt hand still has cards the player has not answered."""
    scene = state.scene
    if not scene:
        return False
    return int(scene.get("cursor", 0)) < len(scene.get("card_ids") or [])


def end(state: GameState) -> None:
    """Clear the current scene. Idempotent."""
    if state.scene:
        logger.info(
            "[director] Scene ended (operation=end, deck=%s)",
            state.scene.get("deck_id"),
        )
    state.scene = {}


def current_card(state: GameState) -> Optional[deck_module.Card]:
    """
    The card the player is being asked to answer, or None.

    A card id that no longer resolves -- the deck was edited mid-run -- is
    skipped rather than raised on, which is the whole reason ids are stored
    instead of copies.
    """
    scene = state.scene
    if not scene:
        return None
    deck = deck_module.load_deck(str(scene.get("deck_id", "")))
    if deck is None:
        return None

    card_ids = list(scene.get("card_ids") or [])
    by_id = {c.id: c for c in deck.cards}
    while int(scene.get("cursor", 0)) < len(card_ids):
        card = by_id.get(str(card_ids[int(scene["cursor"])]))
        if card is not None:
            return card
        logger.warning(
            "[director] Card gone from deck, skipping (operation=current_card, "
            "deck=%s, card=%s)",
            scene.get("deck_id"),
            card_ids[int(scene["cursor"])],
        )
        scene["cursor"] = int(scene.get("cursor", 0)) + 1
    return None


def options(state: GameState) -> list[dict[str, str]]:
    """
    What the player may answer the current card with.

    A ``menu`` card offers one option per beat, because its beats are branches
    of a single question. A ``sequence`` card offers a single "go on": its beats
    are steps, and resolving them is not a choice. ``deck.chosen_beats`` owns
    the menu/sequence distinction and is called rather than reimplemented.
    """
    card = current_card(state)
    if card is None:
        return []

    if deck_module.MENU_TAG in card.tags and card.beats:
        rows: list[dict[str, str]] = []
        for beat in card.beats:
            beat_id = str(beat.get("id") or "")
            if not beat_id:
                continue
            rows.append(
                {"id": beat_id, "text": str(beat.get("text") or beat_id)}
            )
        if rows:
            return rows

    return [{"id": "resolve", "text": card.title or "Go on"}]


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------


def _deck_holding_card(card_id: str) -> tuple[str, str]:
    """
    Find the deck that contains ``card_id``.

    A ``forces_scene:`` may name a whole deck OR a single card. The Wicked
    Garden's four all name cards -- ``D8_06_briar_threshold`` and friends -- and
    a director that only understood deck ids would leave all four promises
    unanswered forever, which is exactly the state they were found in.

    Returns:
        ``(deck_id, card_id)``, or ``("", "")`` when nothing holds it.
    """
    for deck_id in deck_module.deck_ids():
        deck = deck_module.load_deck(deck_id)
        if deck is None:
            continue
        if any(c.id == card_id for c in deck.cards):
            return deck_id, card_id
    return "", ""


def due(state: GameState, *, ledger: Any = None) -> tuple[str, str, str]:
    """
    Which scene wants this turn.

    Returns:
        ``(deck_id, forced_card_id, source)``. All empty when nothing is due.
        ``forced_card_id`` is set only when a clock named a single card.

    Order is deliberate. A clock that has FILLED is a promise the engine made
    and owes the player now; a scheduled deck is merely the next thing due. A
    promise outranks a schedule.
    """
    known = deck_module.deck_ids()
    if not known:
        # The story declares no decks. Nothing below can apply, and this is the
        # line that keeps graph-shaped stories byte-identical.
        return "", "", ""

    for scene_id in clocks_module.forced_scenes(state):
        if scene_id in known:
            return scene_id, "", "forced"
        deck_id, card_id = _deck_holding_card(scene_id)
        if deck_id:
            return deck_id, card_id, "forced"
        logger.warning(
            "[director] Forced scene names neither a deck nor a card "
            "(operation=due, scene=%s). The clock's promise cannot be kept.",
            scene_id,
        )

    from engine.game.quests import evaluate_condition

    for deck_id in known:
        if state.flags.get(_played_flag(deck_id)):
            continue
        deck = deck_module.load_deck(deck_id)
        if deck is None:
            continue
        # `Deck.when` already exists and is already evaluated inside `draw`, so
        # scheduling a deck costs no new grammar: `when: {min_day: 3}` uses the
        # same predicate a quest gate would.
        if deck.when is None:
            continue
        if evaluate_condition(state, deck.when, ledger=ledger):
            return deck_id, "", "scheduled"

    return "", "", ""


# ---------------------------------------------------------------------------
# Dealing
# ---------------------------------------------------------------------------


def begin(
    state: GameState,
    deck_id: str,
    *,
    forced_card: str = "",
    source: str = "scheduled",
    ledger: Any = None,
) -> dict[str, Any]:
    """
    Deal a hand and make it the current scene.

    Args:
        state: Mutable game state. ``state.scene`` is overwritten.
        deck_id: Deck to deal from.
        forced_card: A card a clock named specifically. It is placed FIRST and
            is guaranteed present even if the draw would not have picked it --
            a forced scene that dealt a hand not containing the scene it forced
            would be a promise kept in name only.
        source: ``"forced"`` or ``"scheduled"``, recorded for the receipt.
        ledger: Optional StoryLedger, for conditions that read disposition.

    Returns:
        A receipt describing what was dealt. An unknown or empty deck returns a
        receipt with ``ok: False`` and leaves the state idle rather than
        raising -- the caller is a turn, not a test.
    """
    hand = deck_module.draw(state, deck_id, ledger=ledger)
    card_ids = [c.id for c in hand.cards]

    if forced_card:
        card_ids = [forced_card] + [c for c in card_ids if c != forced_card]

    card_ids = card_ids[:MAX_SCENE_CARDS]

    if not card_ids:
        logger.warning(
            "[director] Nothing dealt (operation=begin, deck=%s, rejected=%s)",
            deck_id,
            hand.rejected,
        )
        return {
            "ok": False,
            "deck_id": deck_id,
            "error": "no cards were eligible",
            "rejected": dict(hand.rejected),
        }

    state.scene = {
        "deck_id": deck_id,
        "card_ids": card_ids,
        "cursor": 0,
        "source": source,
        "started_day": int(state.world_day),
        "started_hour": int(state.world_hour),
    }

    # Marked on the DEAL, not at the end of the hand. Marking at the end means a
    # save reloaded mid-scene re-deals the same deck, and the hand already
    # sitting on `state.scene` is the record that it started.
    from engine.game import effects as effects_module

    effects_module.apply_effect(
        state, {"type": "flag", "flag": _played_flag(deck_id), "value": True}
    )
    if source == "forced":
        # Retires the clock's promise. Without this, `forced_scenes()`
        # accumulates the same id forever -- measured at 100% pending across a
        # 40-run walk of The Wicked Garden.
        clocks_module.mark_scene_played(state, forced_card or deck_id)

    logger.info(
        "[director] Scene dealt (operation=begin, deck=%s, cards=%d, source=%s)",
        deck_id,
        len(card_ids),
        source,
    )
    return {
        "ok": True,
        "deck_id": deck_id,
        "source": source,
        "card_ids": list(card_ids),
        "forced_card": forced_card,
    }


def ensure_scene(state: GameState, *, ledger: Any = None) -> list[dict[str, Any]]:
    """
    Open a scene if one is due and none is running. The turn's entry point.

    Returns:
        Receipts, for the turn's ``tool_receipts``. Empty in the overwhelmingly
        common case, and ALWAYS empty for a story that declares no decks --
        ``due`` returns on its first line for those, before anything is read.

    At most one scene is opened per turn: a hand is a scene, and dealing two in
    one turn would mean the player answered neither.
    """
    if active(state):
        return []

    deck_id, forced_card, source = due(state, ledger=ledger)
    if not deck_id:
        return []

    receipt = begin(
        state, deck_id, forced_card=forced_card, source=source, ledger=ledger
    )
    return [{"skill": "scene_begin", "args": {"deck_id": deck_id}, "result": receipt,
             "success": bool(receipt.get("ok")), "type": "scene"}]


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------


def resolve(
    state: GameState,
    *,
    chosen: str = "",
    qualities: Optional[dict[str, float]] = None,
    ledger: Any = None,
) -> dict[str, Any]:
    """
    Apply the current card's chosen beat and advance to the next card.

    Args:
        chosen: On a ``menu`` card, the beat the player picked. Ignored on a
            ``sequence`` card, whose beats are steps rather than alternatives.
        qualities: beat id -> 0.0-1.0, for band beats.
        ledger: Optional StoryLedger.

    Returns:
        A receipt. ``ok: False`` when there is no scene open or the named beat
        is not on the card -- a REFUSAL, which reaches the narrator through the
        intent machinery rather than becoming a silent no-op.
    """
    card = current_card(state)
    if card is None:
        return {"ok": False, "error": "no scene is open"}

    legal = {row["id"] for row in options(state)}
    if chosen and chosen not in legal:
        logger.info(
            "[director] Refused beat (operation=resolve, card=%s, chosen=%s)",
            card.id,
            chosen,
        )
        return {
            "ok": False,
            "card_id": card.id,
            "error": f"'{chosen}' is not on this card",
            "options": sorted(legal),
        }

    results = deck_module.resolve_card(
        state,
        card,
        chosen=chosen if chosen != "resolve" else None,
        qualities=qualities,
        ledger=ledger,
    )

    state.scene["cursor"] = int(state.scene.get("cursor", 0)) + 1
    finished = not active(state)
    deck_id = str(state.scene.get("deck_id", ""))
    if finished:
        end(state)

    return {
        "ok": True,
        "deck_id": deck_id,
        "card_id": card.id,
        "chosen": chosen,
        "beats": [r.to_dict() for r in results],
        "scene_complete": finished,
    }


__all__ = [
    "MAX_SCENE_CARDS",
    "active",
    "begin",
    "current_card",
    "due",
    "end",
    "ensure_scene",
    "options",
    "resolve",
]
