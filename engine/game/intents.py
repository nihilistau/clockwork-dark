"""
Turn Intents
============

What the engine will accept from a choice THIS TURN, and how each one maps to
the skill that resolves it.

THE DEFECT THIS CLOSES
----------------------
A narration turn could not change the world. A player picked "Follow the smoke
toward Edgewood", the model wrote them walking into the village, and the save
afterwards read ``turn 1 | forest_clearing | 10.0h | stamina 100``. Nothing had
moved, because the only channel that could move anything was unreachable:

  1. ``engine/lmstudio/schemas.py::storyteller_turn_schema`` sets
     ``additionalProperties: False`` and declares no ``tool_calls`` property,
     so with the grammar on a tool call is literally unsamplable.
  2. Nothing sent a tool manifest -- ``engine/lmstudio/tools.py::build_manifest``
     lost its last production caller when ``turn_loop.py`` was retired.
  3. No prompt mentioned tool calls, and the flagship persona forbids the
     concept outright.

So ``move_to``, ``resolve_skill_check``, ``rest``, ``eat`` and ``trade`` were
dead in real play. ``scripts/simulate.py`` never noticed because it calls engine
methods directly, and every mock LLM in the suite emitted a ``tool_calls`` key
the live grammar forbids -- which is precisely how the bug survived for months.

THE FIX: PUT THE MECHANIC IN THE CHOICE
---------------------------------------
The turn schema already proves that a per-turn enum works: ``npc_id`` is an
enum of the NPCs actually present, so voicing somebody who is not in the room
is unsamplable rather than merely wrong. This module applies the same trick to
ACTIONS. Each choice may carry a structured ``intent``; the legal verbs and the
legal targets for each are built fresh every turn from what the engine will
actually accept, so an unreachable destination cannot be sampled at all. There
is no post-hoc validation step to forget.

The model still never resolves anything. It declares "this option is a walk to
``edgewood_square``"; the ENGINE walks, spends the stamina, moves the clock and
hands the receipt back as narration input on the following turn.

WHY VERBS COME AND GO
---------------------
A verb appears only where the engine can honour it. A story with no travel
graph gets no ``travel``. A story that ships no skill rules (The Wicked Garden
declares no dice at all) gets no ``check``. A player carrying no food gets no
``eat``. An open encounter suppresses everything except ``encounter``, because
``engine/game/encounter.py`` already owns the option list while a scene is
running. A story that can honour none of them gets no ``intent`` property in
its schema at all and its payload is byte-for-byte what it was.

WHY THE CATALOGUE IS REBUILT AT EXECUTION TIME
----------------------------------------------
An intent is declared on turn N and executed when the player picks it on turn
N+1, and the world moves in between -- the background tick spends hunger, an
edge can close, stamina can fall below what the leg costs. So legality is
re-checked against the live state at execution, and a intent that has gone
illegal becomes an engine-authored REFUSAL that is fed to the narrator. It is
never a silent no-op: the one thing the player must never read is that they
walked somewhere they did not.

Version: v0.1.0 [2026-08-14]
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from engine.game.state import GameState

logger = logging.getLogger(__name__)

#: Verbs whose target list is capped before it reaches the grammar. A vendor
#: with forty lines of stock would otherwise put forty tokens of enum into every
#: prompt for the rest of the run. Travel is deliberately absent: a location
#: graph's out-degree is small by construction, and silently hiding a road is
#: the same defect as never having had one.
_MAX_OPTIONS = 8

#: Difficulty bands a ``check`` intent may name. The model picks the band; the
#: engine derives the DC and itemises every modifier (engine/game/checks.py).
DIFFICULTY_BANDS = ("trivial", "easy", "standard", "hard", "severe", "legendary")


@dataclass(frozen=True)
class IntentVerb:
    """
    One action the engine will accept this turn, with its legal targets.

    Attributes:
        action: The verb, as it appears in the grammar's ``action`` enum.
        options: ``(target_id, human label)`` pairs. Empty for a verb that
            takes no target at all.
        extra: Further constrained fields this verb alone carries, as
            ``field name -> legal values``. Only ``check`` uses one today (its
            difficulty band), and it is the reason the schema branches per verb
            rather than crossing one action enum with one target enum: a flat
            pair of enums would make ``{"action": "travel", "target":
            "persuasion"}`` samplable.
    """

    action: str
    options: tuple[tuple[str, str], ...] = ()
    extra: dict[str, tuple[str, ...]] = field(default_factory=dict)

    @property
    def targets(self) -> tuple[str, ...]:
        """Just the ids, in declaration order. This is what the grammar sees."""
        return tuple(target for target, _ in self.options)

    def label_for(self, target: str) -> str:
        for candidate, label in self.options:
            if candidate == target:
                return label
        return target


# ---------------------------------------------------------------------------
# building the catalogue
# ---------------------------------------------------------------------------


def _travel(state: GameState) -> Optional[IntentVerb]:
    """
    Every place directly reachable from where the player is standing.

    Sourced from the SAME graph ``GameEngine.move_to`` validates against, plus
    any hidden path foraging has discovered -- so the enum and the executor
    cannot disagree about what a road is. A story that declares no graph has no
    neighbours and gets no verb.
    """
    from engine.game.locations import LOCATIONS, get_edge, neighbours

    reachable = list(neighbours(state.location_id))

    # A discovered hidden path is a way through the wood the map does not draw.
    # It can open a leg the graph lacks, so it belongs in the enum -- otherwise
    # the player could find a shortcut and never be offered it.
    try:
        from engine.game import foraging

        for row in foraging.discovered_paths(state):
            for candidate in (row.get("from_id"), row.get("to_id")):
                target = str(candidate or "")
                if (
                    target
                    and target != state.location_id
                    and target in LOCATIONS
                    and target not in reachable
                    and foraging.shortcut_hours(state, state.location_id, target)
                    is not None
                ):
                    reachable.append(target)
    except Exception as exc:  # noqa: BLE001 -- a missing shortcut is not an error
        logger.debug("[intents] No hidden paths: %s", exc)

    options: list[tuple[str, str]] = []
    for target in sorted(reachable):
        name = str((LOCATIONS.get(target) or {}).get("name") or target)
        edge = get_edge(state.location_id, target) or {}
        hours = edge.get("hours")
        options.append(
            (target, f"{name}, {hours}h" if hours is not None else name)
        )
    return IntentVerb("travel", tuple(options)) if options else None


def _rest(state: GameState) -> Optional[IntentVerb]:
    """
    Every configured way of stopping.

    Never conditioned on where the player is standing (CLAUDE.md rule 6):
    ``survival.rest`` downgrades a bed it cannot reach to sleeping rough rather
    than refusing, and a location gate here would rebuild the stamina soft-lock
    one layer higher up.
    """
    from engine.game import survival

    kinds = [str(k) for k in survival.rest_kinds() if str(k)]
    return (
        IntentVerb("rest", tuple((k, k.replace("_", " ")) for k in kinds))
        if kinds
        else None
    )


def _eat(state: GameState) -> Optional[IntentVerb]:
    """Whatever in the pack the survival rules actually count as food."""
    from engine.game import survival

    rules = survival.load_rules()
    options: list[tuple[str, str]] = []
    for entry in state.inventory:
        if entry.qty <= 0:
            continue
        if survival.food_value(entry.id, list(entry.tags), rules):
            options.append((entry.id, str(getattr(entry, "name", "") or entry.id)))
    return IntentVerb("eat", tuple(options[:_MAX_OPTIONS])) if options else None


def _check(state: GameState) -> Optional[IntentVerb]:
    """
    The story's declared skills.

    Absent for a story that ships no skill rules -- The Wicked Garden declares
    no HP, no stamina and no checks, and offering its narrator a dice verb would
    be the engine inventing a mechanic the story does not have.
    """
    from engine.game.checks import load_skill_rules

    rules = load_skill_rules() or {}
    skills = [str(s) for s in sorted((rules.get("skills") or {})) if str(s)]
    if not skills:
        return None
    return IntentVerb(
        "check",
        tuple((s, s) for s in skills[:_MAX_OPTIONS]),
        extra={"difficulty": DIFFICULTY_BANDS},
    )


def _buy(state: GameState) -> Optional[IntentVerb]:
    """
    What a vendor standing here will sell, that the player can afford.

    The target is composite -- ``npc_id/item_id`` -- because a purchase needs
    both and a flat pair of enums would let the grammar cross a baker with a
    tinker's stock. The engine splits it back apart; the model only ever picks
    a token the engine wrote.
    """
    try:
        from engine.game import trade
    except Exception as exc:  # noqa: BLE001 -- a story with no economy
        logger.debug("[intents] No trade module: %s", exc)
        return None

    options: list[tuple[str, str]] = []
    for npc_id in trade.vendors_at(state.location_id):
        listing = trade.browse(state, npc_id)
        if not listing.get("ok"):
            continue
        vendor_name = str(listing.get("vendor") or npc_id)
        for row in listing.get("sells") or []:
            if not row.get("affordable"):
                continue
            options.append(
                (
                    f"{npc_id}/{row['item_id']}",
                    f"{row.get('name') or row['item_id']} from {vendor_name}, "
                    f"{row.get('price')}g",
                )
            )
    return IntentVerb("buy", tuple(options[:_MAX_OPTIONS])) if options else None


def _flag(state: GameState) -> Optional[IntentVerb]:
    """
    Quest beats the fiction is currently allowed to reach.

    Scoped by ``QuestEngine.allowed_narrative_flags`` to the current stage, so
    a later stage's flag stays unsamplable and the intervening fiction cannot
    be skipped. Flags already raised are dropped: re-raising one is a no-op and
    an option that does nothing is worse than no option.
    """
    try:
        from engine.game.quests import QuestEngine

        allowed = sorted(QuestEngine.allowed_narrative_flags(state))
    except Exception as exc:  # noqa: BLE001 -- a story with no quests
        logger.debug("[intents] No narrative flags: %s", exc)
        return None

    pending = [f for f in allowed if not state.flags.get(f)]
    return (
        IntentVerb("flag", tuple((f, f) for f in pending[:_MAX_OPTIONS]))
        if pending
        else None
    )


def _scene_open(state: GameState) -> bool:
    """Whether an unresolved encounter owns this turn."""
    try:
        from engine.game import encounter

        return bool(encounter.active(state))
    except Exception as exc:  # noqa: BLE001 -- a story with no encounters
        logger.debug("[intents] No encounter system: %s", exc)
        return False


def _absent(label: str, exc: Exception) -> None:
    """
    Log a verb builder's failure at the right volume.

    Every builder here swallows exceptions, and it must: a story that ships no
    forage table, no vendors or no threads has to yield no verb rather than
    lose the turn. But that same catch will happily swallow a BUG, and it did
    -- ``foraging.nodes_at`` takes ``(state, location_id)`` and was called with
    one argument, so the resulting TypeError was logged at DEBUG and the
    ``forage`` verb simply never appeared. Silent, and indistinguishable from
    "this story does not forage".

    A TypeError or AttributeError from an engine module is a programming error
    every time. Those are WARNINGs with a traceback; a genuinely absent system
    stays at DEBUG.
    """
    if isinstance(exc, (TypeError, AttributeError)):
        logger.warning(
            "[intents] Verb builder failed (operation=%s) -- this is a bug, "
            "not a story without the system: %s",
            label,
            exc,
            exc_info=True,
        )
    else:
        logger.debug("[intents] No %s: %s", label, exc)


def _challenge_open(state: GameState) -> bool:
    """Whether a running set-piece owns this turn."""
    return bool(getattr(state, "challenge", None))


def _challenge(state: GameState) -> Optional[IntentVerb]:
    """
    The next step of the running challenge.

    A PUZZLE IS THE ONE VERB WHOSE TARGET CANNOT BE AN ENUM: its input is the
    player's own words. ``intent_schema`` already omits the target enum when a
    verb declares no options, so the schema handles this without a special
    case -- the verb simply carries an empty options tuple and the model writes
    free text.
    """
    try:
        from engine.challenges import runner

        step = runner.present(state)
    except Exception as exc:  # noqa: BLE001 -- a story with no challenges
        _absent("challenge", exc)
        return None
    if step is None:
        return None
    targets = tuple(
        (str(o.get("id")), str(o.get("text") or o.get("id")))
        for o in (step.options or [])
        if o.get("id")
    )
    return IntentVerb("challenge", targets[:_MAX_OPTIONS])


def _set_piece(state: GameState) -> Optional[IntentVerb]:
    """
    Set-pieces whose gates are open here and now.

    ``set_pieces.available`` already filters on location and flags, so every id
    it returns will start.
    """
    try:
        from engine.challenges import set_pieces

        rows = set_pieces.available(state)
    except Exception as exc:  # noqa: BLE001 -- a story with no challenges
        _absent("set-pieces", exc)
        return None
    targets = tuple(
        (str(p.get("id")), str(p.get("title") or p.get("id")))
        for p in rows
        if p.get("id")
    )
    return IntentVerb("set_piece", targets[:_MAX_OPTIONS]) if targets else None


def _work(state: GameState) -> Optional[IntentVerb]:
    """
    Shifts that can be worked here, now.

    ``economy.available`` already filters on requirements, the hour and today's
    cap, so an offered job is a job that will run.
    """
    try:
        from engine.game import economy

        rows = economy.available(state, state.location_id)
    except Exception as exc:  # noqa: BLE001 -- a story with no labour table
        _absent("labour", exc)
        return None
    targets = tuple(
        (str(j.get("id")), str(j.get("name") or j.get("id")))
        for j in rows
        if j.get("id")
    )
    return IntentVerb("work", targets[:_MAX_OPTIONS]) if targets else None


def _forage(state: GameState) -> Optional[IntentVerb]:
    """Forageable ground at this location, if the story ships any."""
    try:
        from engine.game import foraging

        if not foraging.forageable(state.location_id):
            return None
        nodes = foraging.nodes_at(state, state.location_id)
    except Exception as exc:  # noqa: BLE001 -- a story with no forage table
        _absent("foraging", exc)
        return None
    targets = tuple(
        (str(n.get("id")), str(n.get("name") or n.get("id")))
        for n in (nodes or [])
        if n.get("id")
    )
    # NO NODES MEANS NO VERB, even though the location's TAGS admit foraging.
    # `forageable()` answers from tags alone, and the node pool is dealt out
    # per save -- so a tag-only check offers a verb whose skill can only ever
    # answer "you find no ground here worth working". A verb that is guaranteed
    # to refuse is worse than an absent one: it spends an option slot, an enum
    # token in every prompt, and a turn.
    return IntentVerb("forage", targets[:_MAX_OPTIONS]) if targets else None


def _sell(state: GameState) -> Optional[IntentVerb]:
    """
    What the player is carrying that someone here will actually buy.

    THE ECONOMY'S MISSING HALF. ``buy`` has been reachable since intents
    shipped and ``sell`` has not, so gold had a sink and no faucet -- while
    ``scripts/simulate.py``, which set every balance constant, drove selling
    directly.
    """
    try:
        from engine.game import trade

        vendors = trade.vendors_at(state.location_id)
    except Exception as exc:  # noqa: BLE001 -- a story with no vendors
        _absent("vendors", exc)
        return None

    targets: list[tuple[str, str]] = []
    for npc_id in vendors:
        for item in state.inventory:
            try:
                if not trade.deals_in(npc_id, item.id):
                    continue
                quote = trade.quote(state, npc_id, item.id, side="sell")
            except Exception:  # noqa: BLE001 -- one bad row must not kill the verb
                continue
            price = quote.get("unit_price") if isinstance(quote, dict) else None
            label = f"{item.name or item.id}" + (f" for {price}" if price else "")
            targets.append((f"{npc_id}/{item.id}", label))
            if len(targets) >= _MAX_OPTIONS:
                break
        if len(targets) >= _MAX_OPTIONS:
            break
    return IntentVerb("sell", tuple(targets)) if targets else None


def _bargain(state: GameState) -> Optional[IntentVerb]:
    """Thread templates this story declares that can be struck now."""
    try:
        from engine.game import threads

        rows = threads.offerable(state)
    except Exception as exc:  # noqa: BLE001 -- a story with no threads
        _absent("threads", exc)
        return None
    targets = tuple(
        (str(t.get("id")), str(t.get("title") or t.get("id")))
        for t in (rows or [])
        if t.get("id")
    )
    return IntentVerb("bargain", targets[:_MAX_OPTIONS]) if targets else None


def _discharge(state: GameState) -> Optional[IntentVerb]:
    """
    Live threads the player can settle.

    The one the player actually needs: a debt you cannot pay is not a bargain,
    it is a trap.
    """
    try:
        from engine.game import threads

        rows = threads.active(state)
    except Exception as exc:  # noqa: BLE001 -- a story with no threads
        _absent("active threads", exc)
        return None
    targets = tuple(
        (str(t.get("id")), str(t.get("title") or t.get("id")))
        for t in (rows or [])
        if isinstance(t, dict) and t.get("id")
    )
    return IntentVerb("discharge", targets[:_MAX_OPTIONS]) if targets else None


def _card_open(state: GameState) -> bool:
    """Whether a dealt authored scene owns this turn."""
    try:
        from engine.content import director

        return bool(director.active(state))
    except Exception as exc:  # noqa: BLE001 -- a story with no decks
        _absent("scene director", exc)
        return False


def _card(state: GameState) -> Optional[IntentVerb]:
    """
    The answers the dealt card allows.

    ``director.options`` calls ``deck.chosen_beats`` for the menu/sequence
    distinction rather than reimplementing the tag check, so a beat offered here
    is a beat ``resolve`` will accept.
    """
    try:
        from engine.content import director

        rows = director.options(state)
    except Exception as exc:  # noqa: BLE001 -- a story with no decks
        _absent("scene options", exc)
        return None
    if not rows:
        return None
    targets = tuple(
        (str(r["id"]), str(r.get("text") or r["id"]))
        for r in rows[:_MAX_OPTIONS]
    )
    return IntentVerb("card", targets) if targets else None


def _encounter(state: GameState) -> Optional[IntentVerb]:
    """
    The approaches the open scene allows, engine-authored.

    ``available_approaches`` already excludes anything the player cannot pay
    for, reach at this hour, or lacks the item for, so every id it returns
    resolves.
    """
    try:
        from engine.game import encounter

        rows = encounter.available_approaches(state)
    except Exception as exc:  # noqa: BLE001 -- a story with no encounters
        logger.debug("[intents] No encounter approaches: %s", exc)
        return None

    options = [
        (str(row.get("id")), str(row.get("text") or row.get("id")))
        for row in rows
        if row.get("id")
    ]
    return IntentVerb("encounter", tuple(options)) if options else None


def legal_intents(state: GameState) -> tuple[IntentVerb, ...]:
    """
    Everything the engine will accept from a choice, given this exact state.

    Args:
        state: Live game state. Read only -- building the catalogue must never
            move the world, because it runs while a prompt is being assembled.

    Returns:
        The legal verbs, each with its legal targets. Empty for a story the
        engine can honour nothing for, which is what keeps the ``intent``
        property out of that story's grammar entirely.
    """
    if _challenge_open(state):
        # A running set-piece owns the turn for the same reason an encounter
        # does: its steps are the only legal moves, and offering travel would
        # let the narrator walk the player out of a gauntlet the runner still
        # believes is open.
        step = _challenge(state)
        return (step,) if step is not None else ()

    if _card_open(state):
        # A dealt card is the turn, and answering it is the only thing on
        # offer. Same rule as the encounter branch below and for the same
        # reason: the engine owns the option list while a scene is open, so the
        # narrator cannot walk the player out of a scene the director believes
        # is still running. Checked FIRST because a card can open an encounter
        # but never the reverse.
        card = _card(state)
        return (card,) if card is not None else ()

    if _scene_open(state):
        # A scene is running and the engine owns the option list. Offering
        # travel here would let the narrator walk the player out of a
        # confrontation the encounter system believes is still open.
        #
        # The suppression is keyed on the scene being OPEN, not on approaches
        # being found. An encounter whose definition has gone missing yields no
        # approaches, and falling through to the ordinary verbs would then hand
        # the narrator a road out of a fight it cannot see -- the failure mode
        # would be a content bug quietly becoming an escape hatch.
        scene = _encounter(state)
        return (scene,) if scene is not None else ()

    verbs = [
        builder(state)
        for builder in (
            _travel,
            _rest,
            _eat,
            _check,
            _buy,
            # The economy's other half. `sell`, `work` and `forage` were
            # implemented, data-complete and unreachable: 17 jobs, a forage
            # table and a whole trade module that no choice could ever invoke,
            # while scripts/simulate.py drove all three directly and set every
            # balance constant against them.
            _sell,
            _work,
            _forage,
            _set_piece,
            _bargain,
            _discharge,
            _flag,
        )
    ]
    return tuple(verb for verb in verbs if verb is not None)


def describe_intent(state: GameState, intent: Any) -> str:
    """
    A short player-facing label for what a choice will make the engine do.

    WHY THIS EXISTS. A choice's ``intent`` is executed before the next beat is
    written, and the narrator decides which choices carry one. It is told not to
    put an intent on a choice that is only talk (``engine/agents/prompts.py``),
    but nothing can enforce that -- no schema can read a sentence and tell
    movement from conversation. Measured once in a since-removed test story:
    "Ask what is
    required of you today" carried ``travel -> afterdeck``, the narration
    described sitting still at the table, and the save moved the player.

    Since it cannot be made unsamplable, it is made VISIBLE: the client renders
    this beside the choice, so a player who is about to be moved can see it
    before they commit rather than infer it from a location header afterwards.

    The label is taken from ``legal_intents`` rather than recomputed, so it is
    the SAME string the grammar's enum was built from -- one notion of what a
    target is called, including the travel verb's "somewhere, 2h" hours.

    Args:
        state: Live game state. Read only.
        intent: A choice's declared intent, in any shape ``normalise``
            accepts. Anything unrecognised yields "".

    Returns:
        A label like ``"The Afterdeck, 0h"``, or the bare action for a verb
        that takes no target (``"rest"``), or "" when there is nothing honest
        to say -- an absent intent, or one this state would refuse anyway.
    """
    row = normalise(intent)
    action = str(row.get("action") or "")
    if not action:
        return ""

    try:
        verb = find_verb(legal_intents(state), action)
    except Exception as exc:  # noqa: BLE001 -- a label must never cost a turn
        logger.debug("[intents] No catalogue to describe %r: %s", action, exc)
        return ""
    if verb is None:
        # Legal when the narrator wrote it, illegal now. Saying nothing is
        # right: `execute_intent` will refuse it and the refusal reaches the
        # prose, which is a better place for the news than a chip.
        return ""

    target = str(row.get("target") or "")
    if not target:
        # A verb that takes no target at all -- its own name is the label.
        # A verb that DOES take one, with none declared, is malformed and gets
        # nothing rather than a half-sentence.
        return action if not verb.options else ""
    # Membership first: `label_for` falls back to the raw id, and an id is
    # exactly what this is meant to keep off the screen. A target that is not
    # in the catalogue will be refused at execution anyway.
    if target not in verb.targets:
        return ""
    label = verb.label_for(target)

    # `check` labels its options with the bare skill name, because that is what
    # the catalogue is for -- the prompt block renders these too, so the labels
    # themselves are left alone and the READING is shaped here. "lore" on a chip
    # is cryptic; "lore check (standard)" is the sentence the engine is about to
    # act on.
    if action == "check":
        band = str(row.get("difficulty") or "")
        return f"{label} check ({band})" if band else f"{label} check"
    return label


def find_verb(
    verbs: tuple[IntentVerb, ...], action: str
) -> Optional[IntentVerb]:
    """The verb with this name, or None."""
    for verb in verbs:
        if verb.action == action:
            return verb
    return None


# ---------------------------------------------------------------------------
# mapping an intent onto the skill that resolves it
# ---------------------------------------------------------------------------

#: Verb -> the registered skill that does the work. Every one of these is an
#: existing production entry point: nothing here reimplements a mechanic, so
#: the single writers (``effects.apply_effect``, ``clock.advance_time``) stay
#: the only things that touch state.
SKILL_FOR_ACTION: dict[str, str] = {
    "travel": "move_to",
    "rest": "rest",
    "eat": "eat",
    "check": "resolve_skill_check",
    "buy": "trade",
    "flag": "set_narrative_flag",
    "encounter": "encounter_approach",
    "card": "resolve_scene_card",
    "sell": "trade_sell",
    "work": "work",
    "forage": "forage",
    "set_piece": "start_set_piece",
    "challenge": "resolve_challenge",
    "bargain": "strike_bargain",
    "discharge": "discharge_thread",
}

#: Which key in a skill's result means IT DID NOT HAPPEN, per verb. ``None``
#: means the verb has no refusal at all.
#:
#: This has to be declared rather than sniffed, and the reason is
#: ``resolve_skill_check``: its result carries ``success: false`` for a roll
#: that FAILED, which is an outcome the story is built out of, not a refusal.
#: A blanket scan for a false ``success`` marks every failed check as "this did
#: not happen", and the narrator is then told to write the attempt coming to
#: nothing when the engine has just applied a complication.
#:
#: ``move_to`` is the opposite case and the one that matters most: MoveResult
#: reports ``success: false`` with a ``message`` and no ``error`` key, so
#: ``execute_tool`` scored a refused walk as a SUCCESSFUL receipt --
#: ``receipts_block`` then handed the narrator "travelled to millhaven_gate
#: (4h, 20 stamina)" for a leg that was never walked. That is the exact
#: sentence a player must never read.
#:
#: ``rest`` is deliberately ``None``: it never refuses (CLAUDE.md rule 6), and
#: a refusal path here would be a stamina soft-lock rebuilt one layer up.
REFUSAL_KEY_FOR_ACTION: dict[str, Optional[str]] = {
    "travel": "success",
    "rest": None,
    "eat": "success",
    "check": None,
    "buy": "ok",
    "flag": "success",
    "encounter": "ok",
    # A beat the card does not carry, or a resolve against a scene that has
    # already closed, is a genuine refusal and the narrator must be told --
    # otherwise the card silently applies nothing and the prose describes a
    # consequence the engine never produced.
    "card": "ok",
    # `trade_sell` reports a refused sale the way `trade` does.
    "sell": "ok",
    # `work` and `forage` both report a shift or a search that did not happen
    # under `success`. Note this is NOT the same as a shift that went badly:
    # a failed check still worked the hours, and those come back success=True
    # with a poor outcome, exactly like `resolve_skill_check`.
    "work": "success",
    "forage": "success",
    "set_piece": "ok",
    "challenge": "ok",
    "bargain": "ok",
    "discharge": "ok",
}


def declined_reason(action: str, result: Any) -> str:
    """
    The skill's own refusal, or "" if it did what it was asked.

    Args:
        action: The intent verb, which decides which key is even consulted.
        result: The decoded skill result.

    Returns:
        A player-independent reason string for the narrator, or "".
    """
    key = REFUSAL_KEY_FOR_ACTION.get(action)
    if key is None or not isinstance(result, dict):
        return ""
    if result.get(key) is not False:
        return ""
    return str(
        result.get("message")
        or result.get("reason")
        or result.get("error")
        or "the engine declined"
    )


def normalise(intent: Any) -> dict[str, str]:
    """
    Coerce whatever came off the wire into a plain ``{action, target, ...}``.

    Returns an empty dict for anything that is not a usable intent, which is
    what makes a model that emits none -- or an old save that carries none --
    degrade to the behaviour the game had before this module existed.
    """
    if not isinstance(intent, dict):
        return {}
    action = str(intent.get("action") or "").strip()
    if not action:
        return {}
    out = {"action": action}
    target = str(intent.get("target") or "").strip()
    if target:
        out["target"] = target
    difficulty = str(intent.get("difficulty") or "").strip()
    if difficulty:
        out["difficulty"] = difficulty
    return out


def refusal(intent: dict[str, str], reason: str) -> dict[str, Any]:
    """
    The engine declining an intent, in the shape a receipt takes.

    ``success`` is False and ``refused`` marks it as the engine's own decision
    rather than a skill that errored, which is what
    ``prompts.receipts_block`` renders as an explicit "this did not happen".
    """
    return {
        "type": "intent",
        "skill": str(intent.get("action") or "intent"),
        "args": dict(intent),
        "result": {"error": reason},
        "success": False,
        "refused": True,
        "intent": dict(intent),
    }


def to_tool_call(
    state: GameState, intent: dict[str, str]
) -> tuple[str, dict[str, Any]]:
    """
    Translate a legal intent into the skill call that resolves it.

    Args:
        state: Live state, for the verbs whose arguments are derived rather
            than named (``buy`` splits its composite target).
        intent: An intent already checked against :func:`legal_intents`.

    Returns:
        ``(skill name, kwargs)``.

    Raises:
        KeyError: If the action has no registered skill. Callers check
            legality first, so this is a programming error rather than a
            model error.
    """
    action = intent["action"]
    name = SKILL_FOR_ACTION[action]
    target = intent.get("target", "")

    if action == "travel":
        return name, {"location_id": target}
    if action == "rest":
        return name, {"kind": target}
    if action == "eat":
        return name, {"item_id": target}
    if action == "check":
        return name, {
            "skill": target,
            "difficulty": intent.get("difficulty") or "standard",
            "reason": f"the player's chosen {target} attempt",
        }
    if action == "buy":
        npc_id, _, item_id = target.partition("/")
        return name, {
            "action": "buy",
            "npc_id": npc_id,
            "item_id": item_id,
            "qty": 1,
        }
    if action == "flag":
        return name, {"flag_id": target}
    if action == "encounter":
        return name, {"approach": target}
    if action == "card":
        return name, {"chosen": target}
    if action == "sell":
        # Same composite shape as `buy`: one enum entry has to name both the
        # vendor and the goods, because a flat pair of enums would make
        # "sell the baker's oven to the baker" samplable.
        npc_id, _, item_id = target.partition("/")
        return name, {"npc_id": npc_id, "item_id": item_id, "qty": 1}
    if action == "work":
        return name, {"job_id": target}
    if action == "forage":
        return name, {"node_id": target}
    if action == "set_piece":
        return name, {"piece_id": target}
    if action == "challenge":
        # A puzzle's answer is free text and a gauntlet's choice is an enum
        # entry; the skill takes both and uses whichever it was given.
        return name, {"choice": target, "answer": target}
    if action == "bargain":
        return name, {"template_id": target}
    if action == "discharge":
        return name, {"thread_id": target}
    raise KeyError(action)


__all__ = [
    "DIFFICULTY_BANDS",
    "IntentVerb",
    "REFUSAL_KEY_FOR_ACTION",
    "SKILL_FOR_ACTION",
    "declined_reason",
    "find_verb",
    "legal_intents",
    "normalise",
    "refusal",
    "to_tool_call",
]
