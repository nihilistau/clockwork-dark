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

v0.17: a forced deck waits for its own ``when:`` (``due``) -- and a deck's
``when:`` schedules it on its own as well, forced or not -- and a card that
takes hp to the death threshold runs the death check on that card
(``resolve``).

Version: v0.2.0 [2026-09-27]
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

#: The hours of the day at which ``GameState.time_of_day`` changes its answer
#: (dawn 5, day 8, dusk 17, night 20). ``due_boundary_hours`` cuts a long wait
#: here when a deck reads the band; tests/test_law_arrest.py reads the edges
#: off the property itself, so the two cannot drift apart.
TIME_OF_DAY_EDGES: tuple[int, ...] = (5, 8, 17, 20)

#: Forced scenes already warned about. A clock names a scene once and it stays
#: pending for the rest of the run, so an unanswerable one logged a WARNING on
#: every single turn. Nulled per activation (engine/games/caches.py).
_WARNED_FORCED: Optional[set[str]] = None


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
    promise outranks a schedule -- once it can be kept: a forced DECK whose own
    ``when:`` does not hold waits, and does not hold the turn from the decks
    that can deal (v0.17).

    A deck's ``when:`` ALSO SCHEDULES IT ON ITS OWN. Any unplayed deck whose
    ``when:`` holds comes due below as ``scheduled``, forced or not -- so a
    deck meant to deal only while an event forces it must name the event in
    its ``when:`` (``event_active: <id>``), or it deals whenever the rest of
    that ``when:`` holds.
    """
    known = deck_module.deck_ids()
    if not known:
        # The story declares no decks. Nothing below can apply, and this is the
        # line that keeps graph-shaped stories byte-identical.
        return "", "", ""

    from engine.game.quests import evaluate_condition

    for scene_id in clocks_module.forced_scenes(state):
        if scene_id in known:
            # A FORCED DECK HONOURS ITS OWN `when:` (v0.17). A fair forced by
            # its event but gated `at_location: gallows_green` used to come
            # due wherever the player stood, and `begin` answered "no cards
            # were eligible" every turn -- while outranking the interrogation
            # an arrest on fair day owed. It now WAITS: neither dealt nor
            # retired (`scene_played_` is written only by a deal), and the
            # decks below may deal meanwhile. When the `when:` holds while the
            # promise still stands, it deals; if the event lapses first, it is
            # simply not dealt. A deck with no `when:` -- every forced deck
            # shipped before this -- is unaffected. A forced CARD is not read
            # here: it is placed in the hand whatever the draw says (`begin`),
            # as it always was.
            deck = deck_module.load_deck(scene_id)
            if (
                deck is not None
                and deck.when is not None
                and not evaluate_condition(state, deck.when, ledger=ledger)
            ):
                continue
            return scene_id, "", "forced"
        deck_id, card_id = _deck_holding_card(scene_id)
        if deck_id:
            return deck_id, card_id, "forced"
        global _WARNED_FORCED
        warned = _WARNED_FORCED  # read once: a reset nulls it without a lock
        if warned is None:
            warned = _WARNED_FORCED = set()
        if scene_id in warned:
            continue
        warned.add(scene_id)
        logger.warning(
            "[director] Forced scene names neither a deck nor a card "
            "(operation=due, scene=%s). The clock's promise cannot be kept.",
            scene_id,
        )

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


def _requires_custody(when: Any) -> Optional[bool]:
    """``True``/``False`` when a deck's ``when:`` pins ``in_custody`` at its
    top level (bare, or one clause of a top-level ``all:``); ``None`` if not."""
    if not isinstance(when, dict):
        return None
    if "in_custody" in when:
        return bool(when["in_custody"])
    for clause in when.get("all") or []:
        if isinstance(clause, dict) and "in_custody" in clause and len(clause) == 1:
            return bool(clause["in_custody"])
    return None


def due_boundary_hours(*, in_custody: Optional[bool] = None) -> tuple[int, ...]:
    """
    The hours of the day at which ``due`` can change its answer without a turn.

    Midnight -- a declared event starts and ends on the day roll, and
    ``min_day``/``max_day`` turn over -- plus every bound of an
    ``hour_between`` in any deck's ``when:``, plus the four band edges
    (``TIME_OF_DAY_EDGES``) when any deck's ``when:`` reads ``time_of_day``
    (v0.17 T4: a dusk-gated deck used to fall due and away again between two
    cuts). Sorted, 0-23. For a caller that moves the clock a long way in one
    action and must stop where a scene falls due (``law.serve_sentence``):
    stepping to each of these hours and asking ``due`` there sees every hour
    a CLOCK-READING gate can move at, for a handful of ``advance_time`` calls
    a day rather than one an hour. ``(0,)`` for a story with no decks.

    NOT every hour anything can change at: a gate on a flag, a value, a
    clock or anything else ``advance_time`` moves in passing (hunger, an
    agenda's beat, a rumour) is caught at the next cut, not on the hour it
    turned true -- at worst the next midnight or band edge.

    ``in_custody``: the caller knows the player's custody will not change
    over the stretch (a sentence served), so a deck whose ``when:`` pins the
    OTHER value can never come due in it and its hours are left out. HUE &
    CRY held: midnight and nine (the gallows), not the free decks' five more.
    """
    hours: set[int] = {0}
    for deck_id in deck_module.deck_ids():
        deck = deck_module.load_deck(deck_id)
        if deck is None or deck.when is None:
            continue
        pinned = _requires_custody(deck.when)
        if in_custody is not None and pinned is not None and pinned is not in_custody:
            continue
        stack: list[Any] = [deck.when]
        while stack:
            node = stack.pop()
            if isinstance(node, dict):
                for key, value in node.items():
                    if key == "hour_between" and isinstance(value, (list, tuple)):
                        for bound in value:
                            try:
                                hours.add(int(bound) % 24)
                            except (TypeError, ValueError):
                                continue
                    elif key == "time_of_day":
                        hours.update(TIME_OF_DAY_EDGES)
                    else:
                        stack.append(value)
            elif isinstance(node, list):
                stack.extend(node)
    return tuple(sorted(hours))


# ---------------------------------------------------------------------------
# Re-arming a repeatable deck
# ---------------------------------------------------------------------------


def _trigger_holds(state: GameState, deck: deck_module.Deck, *, ledger: Any = None) -> bool:
    """
    Whether anything is asking for this deck right now, played or not.

    Two triggers, the two ways ``due`` deals: an active world-ledger row that
    forces the deck or one of its cards (read WITHOUT the played flags -- the
    question is whether the promise is still standing, not whether it is still
    owed), or the deck's own ``when:``.

    ONE EXCEPTION (v0.17): a DECLARED EVENT's row that forces the DECK itself,
    when the deck declares a ``when:``. Such a deck is dealt only while its
    ``when:`` holds (``due``), so that row is not a trigger of its own and the
    ``when:`` alone is: the event is still active after the player walks off
    the fair's green, and counting it would never let HUE & CRY's fair re-arm
    for a return. Everything else keeps the row as a trigger, deliberately:
    a row forcing a single CARD deals that card whatever the deck's ``when:``
    says (``begin``), so its event must hold the deck spent or it re-deals
    every turn; and a CLOCK beat's row is permanent, so a clock-forced deck is
    one promise kept once, ``when:`` or no ``when:``.
    """
    card_ids = {c.id for c in deck.cards}
    for event in state.world_events:
        scene_id = clocks_module.event_forced_scene(event)
        if scene_id in card_ids:
            return True
        if scene_id == deck.id:
            payload = event.get("payload")
            declared_event = isinstance(payload, dict) and bool(payload.get("declared"))
            if not (declared_event and deck.when is not None):
                return True
    if deck.when is None:
        return False
    from engine.game.quests import evaluate_condition

    return bool(evaluate_condition(state, deck.when, ledger=ledger))


def rearm(state: GameState, *, ledger: Any = None) -> list[str]:
    """
    Re-arm every spent ``repeatable`` deck whose trigger has fallen.

    ONE DEAL PER RISING EDGE. A repeatable deck is spent by its deal exactly
    as a one-shot deck is -- ``deck_played_<id>``, and for a forced deal
    ``scene_played_<id>`` -- so it does not re-deal on every turn its trigger
    stays true. It comes back only once that trigger has been seen FALSE: a
    deck gated ``{in_custody: true}`` deals on the first arrest, not again
    while the player is still held, and again on the second arrest. A forced
    repeatable deck re-arms when no active world event forces it any more --
    except a deck forced AS A DECK by a declared event and gated on its own
    ``when:``, which re-arms when that ``when:`` falls (``_trigger_holds``,
    v0.17: HUE & CRY's fair, dealt again on each return to the green). A
    clock beat's row is permanent, so a clock-forced deck never re-arms,
    ``when:`` or no ``when:``.

    THE FALL IS STATE. Clearing the played flags IS the "has fallen" bit, and
    it is written through ``apply_effect`` like every other flag -- so it
    rides the save, and a reload between the fall and the rise re-deals. It is
    read here, at the turn, which is the only place a deal can happen, so how
    ``advance_time`` was cut between two turns cannot change it. A fall and a
    rise inside one turn are one fact to the director and deal nothing new.

    Returns:
        The deck ids re-armed. ``[]`` for a story with no decks, and for any
        deck that does not declare ``repeatable: true`` -- the one-shot decks
        every story shipped with are never read past that line.
    """
    rearmed: list[str] = []
    for deck_id in deck_module.deck_ids():
        deck = deck_module.load_deck(deck_id)
        if deck is None or not deck.repeatable:
            continue
        spent = [_played_flag(deck_id)] + [
            f"{clocks_module.SCENE_PLAYED_FLAG_PREFIX}{scene_id}"
            for scene_id in [deck_id] + [c.id for c in deck.cards]
        ]
        spent = [flag for flag in spent if state.flags.get(flag)]
        if not spent or _trigger_holds(state, deck, ledger=ledger):
            continue
        from engine.game import effects as effects_module

        for flag in spent:
            effects_module.apply_effect(state, {"type": "flag", "flag": flag, "value": False})
        rearmed.append(deck_id)
        logger.info(
            "[director] Repeatable deck re-armed (operation=rearm, deck=%s)", deck_id
        )
    return rearmed


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
        # SPENT, not pending. A deck whose gate is open and whose cards are all
        # ineligible used to come due again every turn, and the narrator read
        # "scene_begin failed: no cards were eligible" on every one of them.
        from engine.game import effects as effects_module

        effects_module.apply_effect(
            state, {"type": "flag", "flag": _played_flag(deck_id), "value": True}
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
    # First, and before either early return: a repeatable deck's trigger that
    # fell while a hand or a job held the turn still fell.
    rearm(state, ledger=ledger)
    if active(state):
        return []
    # A burglary under way owns the turn the way a scene does. A card dealt
    # over it would take the turn from the job's own verbs, and the player
    # would answer a hand while the house they are standing in waited. The
    # scene is not lost: whatever made it due is still true when the job
    # ends. `jobs.active` reads `state.jobs`, which is `{}` for a story
    # without jobs, so a deck story that burgles nothing is unchanged.
    from engine.world import jobs

    if jobs.active(state) is not None:
        return []
    # An open encounter owns the turn too, and here it must win: a card can
    # open an encounter but never the reverse (intents.legal_intents checks
    # a dealt card FIRST, so a hand dealt over an encounter leaves `card` the
    # only verb and the encounter hanging). In run_turn the Law's patrol runs
    # before this call, so a Lantern's stop on arrival would otherwise be
    # buried under the scene the arrival made due. The deal WAITS, unspent --
    # nothing is marked played -- and lands on the first turn after the
    # encounter resolves, if its `when:` still holds. `state.encounter` is
    # `{}` whenever no encounter is open, so a turn with none is unchanged.
    from engine.game import encounter

    if encounter.active(state):
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

    hp_before = int(state.stats.hp)
    from engine.game import endings as endings_module

    # Neither locked nor played before this card: see "ENDS THE HAND" below.
    story_open = (endings_module.locked(state) == endings_module.NONE_ID
                  and endings_module.module_ran(state) == endings_module.NONE_ID)
    results = deck_module.resolve_card(
        state,
        card,
        chosen=chosen if chosen != "resolve" else None,
        qualities=qualities,
        ledger=ledger,
    )

    state.scene["cursor"] = int(state.scene.get("cursor", 0)) + 1
    deck_id = str(state.scene.get("deck_id", ""))

    # A CARD THAT TAKES HP CAN KILL, ON THAT CARD (v0.17). An encounter's
    # outcome and a job's stage check death the moment they land; a card turn
    # moves no clock, so hp lost to a beat used to wait for whatever next
    # called `advance_time` -- the player answered the rest of the hand at 0
    # hp and died after the narrator had them walk on. Asked only when this
    # card LOWERED hp: a card that takes none (every card shipped before
    # this) never calls it, and a player already down from elsewhere is
    # that elsewhere's death. A death -- terminal or a respawn -- ends the
    # hand, as it ends an open encounter: the scene cannot outlive the
    # player being carried out of it.
    death: Optional[dict[str, Any]] = None
    if int(state.stats.hp) < hp_before:
        from engine.game import encounter

        death = encounter.check_death(state, ledger=ledger)
        if death is not None:
            end(state)

    # A CARD THAT PLAYS AN ENDING ENDS THE HAND (v0.17, controller's ruling).
    # When this card both LOCKED the run's ending and played its module
    # (Speak/Act/Seal) -- neither had happened before it -- the story is
    # over: no later card in the hand may be
    # presented or resolved -- HUE & CRY's desk once dealt two doors in one
    # hand, and the second resolved its "this ends the story" prose and
    # ledger fact over an ending already locked. Scoped to the card that
    # plays the ending, not merely the one that locks it: the Wicked Garden's
    # finale locks on F3 and plays the module on F4, with its epilogue cards
    # after, and that hand must run on. A hand in which no card plays an
    # ending (every other shipped hand) is untouched.
    if (
        story_open
        and active(state)
        and endings_module.locked(state) != endings_module.NONE_ID
        and endings_module.module_ran(state) != endings_module.NONE_ID
    ):
        end(state)

    finished = not active(state)
    if finished:
        end(state)

    receipt: dict[str, Any] = {
        "ok": True,
        "deck_id": deck_id,
        "card_id": card.id,
        "chosen": chosen,
        "beats": [r.to_dict() for r in results],
        "scene_complete": finished,
    }
    if death is not None:
        receipt["death"] = death
    return receipt


__all__ = [
    "MAX_SCENE_CARDS",
    "TIME_OF_DAY_EDGES",
    "active",
    "begin",
    "current_card",
    "due",
    "end",
    "ensure_scene",
    "options",
    "resolve",
]
