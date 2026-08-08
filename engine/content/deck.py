"""
Deck-Drawn Scenes — authored cards, engine-chosen hand
======================================================

Select N authored cards from a pool by state predicate, always including the
required ones. The shape ``DAY-05-LABYRINTH.md`` asks for exactly:

    Not a full CRPG map. 5 chambers drawn from a deck; always include
    Entrance, Heart Trial, Exit. GM Agent picks 2-3 middle chambers by flags.

WHY THIS IS AN ENGINE FUNCTION AND NOT A PROMPT. "Pick two or three chambers by
flags" handed to a model is a model that picks the Winter Mouth without the
passport, forgets the Heart Trial on the run where it matters, and lays out a
different labyrinth on a replay of the same seed. The chambers are authored;
what the engine owns is *which* -- the eligibility, the required spine, the
count, and the draw being reproducible. The agent's job starts after the hand
is dealt.

THE SPINE IS NOT NEGOTIABLE. ``required`` cards are included whether or not
their conditions hold, in authored order, and they do not consume draw slots.
A middle chamber is variety; the Heart Trial is the scene. A selector that could
drop it under some flag combination would occasionally produce a labyrinth with
no labyrinth in it.

NO SECOND GRAMMAR. Card conditions are ``when:`` trees in the shared predicate
grammar (``engine/game/quests.py``), the same one quest stages, clock beats,
thread cutters and ending gates are written in -- extended with ``value``,
``clock``, ``track``, ``thread`` and ``ending`` by the modules that own those.
A card that says "requires the passport OR deep Ashen route OR Lost >= 2" is
written once and reads the same as any other gate in the game.

PER-BEAT RESOLUTION lives here too, because a beat is what a card is made of.
An authored beat declares exactly one of:

  ``gate:``  a HARD threshold or a SEEDED HIDDEN CHECK. Deterministic and
             replayable either way -- a threshold reads state, a hidden check
             draws from ``world_rng(state, stream)``. Never bare ``random``:
             the labyrinth is the one scene most likely to be in a bug report,
             and an unreproducible one is a bug report you cannot act on.

  ``band:``  a RANGE, e.g. ``favor: +5..12``, within which an agent picks by
             judged quality. The engine owns the range and the clamp; the model
             owns only where inside it the moment landed. That is the narrowest
             possible thing to trust a model with that is still worth trusting
             it with, and with no quality supplied it resolves to the midpoint,
             so the simulator and the tests never need a model at all.

Version: v0.1.0 [2026-08-08]
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

import yaml

from engine.challenges import spec as spec_module
from engine.game import effects as effects_module
from engine.game.rng import BEAT as RNG_BEAT
from engine.game.rng import DECK as RNG_DECK
from engine.game.rng import world_rng
from engine.game.state import GameState

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parents[2]

# -- structural bounds ------------------------------------------------------
#: A deck lands in a turn payload and, if a caller stores the hand, in a save.
#: Bounded for the same reason a challenge spec is: an oversized one is paid for
#: on every save write and every turn payload forever.
MAX_CARDS = 32
MAX_DRAW = 8
MAX_BEATS = 12
MAX_TEXT = 600

#: Flag prefix recording that a ``once: true`` card has been dealt on this save.
DRAWN_FLAG_PREFIX = "deck_drawn_"

#: Band resolution when no agent judged the moment. The midpoint, deliberately:
#: a default at either end would make "the model did not answer" mechanically
#: identical to "the model judged this perfect", and the simulator runs on this
#: path for every band in the game.
DEFAULT_QUALITY = 0.5


@dataclass
class Card:
    """One authored card, bounded at load."""

    id: str
    text: str = ""
    title: str = ""
    required: bool = False
    once: bool = False
    weight: float = 1.0
    tags: list[str] = field(default_factory=list)
    when: Any = None
    beats: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "text": self.text,
            "required": self.required,
            "tags": list(self.tags),
            "beats": [dict(b) for b in self.beats],
        }


@dataclass
class Deck:
    """A pool of cards and the rules for dealing a hand from it."""

    id: str = ""
    draw: int = 0
    cards: list[Card] = field(default_factory=list)
    #: Optional condition every card is additionally gated on.
    when: Any = None

    @property
    def required(self) -> list[Card]:
        return [c for c in self.cards if c.required]

    @property
    def pool(self) -> list[Card]:
        return [c for c in self.cards if not c.required]


@dataclass
class Hand:
    """The dealt result. What the narrator is handed."""

    deck_id: str = ""
    cards: list[Card] = field(default_factory=list)
    #: id -> why it was not dealt. The designer-facing half of the receipt.
    rejected: dict[str, str] = field(default_factory=dict)
    eligible: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "deck_id": self.deck_id,
            "cards": [c.to_dict() for c in self.cards],
            "card_ids": [c.id for c in self.cards],
            "rejected": dict(self.rejected),
            "eligible": list(self.eligible),
        }


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def _decks_dir() -> Optional[Path]:
    """The deck directory, or None when the story declares none."""
    from engine.config import get_config

    rel = str(get_config().get("paths.decks", "") or "").strip()
    return (_ROOT / rel) if rel else None


@lru_cache(maxsize=32)
def _read_deck(path_str: str, _mtime: float) -> dict[str, Any]:
    """Parse one deck file, memoized on (path, mtime). See engine/game/survival.py."""
    try:
        with Path(path_str).open(encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
    except (OSError, yaml.YAMLError) as exc:
        logger.error("[deck] Unreadable deck file (path=%s): %s", path_str, exc)
        return {}
    return data if isinstance(data, dict) else {}


def _text(value: Any, limit: int = MAX_TEXT) -> str:
    return str(value or "").strip()[:limit]


def bound_beats(raw: Any, deck_id: str, card_id: str) -> list[dict[str, Any]]:
    """
    Bound a list of beats.

    Effects inside a beat go through the challenge spec's clamps, so an
    authored beat cannot be worth more than the running story says one scene
    may be worth. That the author is human does not change the answer for
    SIZE: the ceiling exists because of what a scene IS, not because of who
    wrote it. (It does change the answer for CAPABILITY -- see the
    ``authored=True`` note in ``_bound_gate``.)

    Public because a deck card is not the only thing made of beats: an ending's
    Speak/Act/Seal module is authored in this same grammar in
    ``data/rules/endings.yaml`` and read by ``engine/game/endings.py``. It
    reaching in for a private helper, or worse resolving unbounded beats
    because bounding was inconvenient to import, is how a second grammar gets
    invented for the same shape.

    Args:
        deck_id: Only for log lines -- the caller's name for where these came
            from. An ending module passes its ending id.
    """
    rows = raw if isinstance(raw, list) else []
    if len(rows) > MAX_BEATS:
        logger.warning(
            "[deck] Card has %d beats, keeping %d (deck=%s, card=%s)",
            len(rows),
            MAX_BEATS,
            deck_id,
            card_id,
        )
        rows = rows[:MAX_BEATS]

    out: list[dict[str, Any]] = []
    for index, raw_beat in enumerate(rows):
        if not isinstance(raw_beat, dict):
            continue
        adjustments: list[str] = []
        beat: dict[str, Any] = {
            "id": str(raw_beat.get("id") or f"{card_id}_{index}"),
            "text": _text(raw_beat.get("text")),
        }
        if "gate" in raw_beat and isinstance(raw_beat["gate"], dict):
            beat["gate"] = _bound_gate(raw_beat["gate"], adjustments)
        if "band" in raw_beat and isinstance(raw_beat["band"], dict):
            beat["band"] = _bound_band(raw_beat["band"], adjustments)
        if "gate" in beat and "band" in beat:
            # A beat is one question. Both would mean the gate's outcome and the
            # band's award are two independent resolutions of the same moment,
            # and the receipt could not say which one the player experienced.
            logger.warning(
                "[deck] Beat declares both gate and band, keeping gate "
                "(deck=%s, beat=%s)",
                deck_id,
                beat["id"],
            )
            beat.pop("band")
        if adjustments:
            beat["adjustments"] = adjustments
        out.append(beat)
    return out


def _bound_gate(raw: dict[str, Any], adjustments: list[str]) -> dict[str, Any]:
    """Bound a gate: its condition, its check, and both outcome branches."""
    gate: dict[str, Any] = {}
    if "when" in raw:
        gate["when"] = raw["when"]
    check = raw.get("check")
    if isinstance(check, dict):
        bounded: dict[str, Any] = {"stream": str(check.get("stream") or RNG_BEAT)}
        if "chance" in check:
            try:
                chance = float(check["chance"])
            except (TypeError, ValueError):
                chance = 0.0
            if not 0.0 <= chance <= 1.0:
                adjustments.append(f"chance {chance} clamped into 0..1")
                chance = max(0.0, min(1.0, chance))
            bounded["chance"] = chance
        if "skill" in check:
            bounded["skill"] = str(check.get("skill") or "").strip().lower()
            difficulty = str(check.get("difficulty") or "").strip().lower()
            if difficulty not in spec_module.DIFFICULTIES:
                if difficulty:
                    adjustments.append(f"difficulty {difficulty!r} unknown, using standard")
                difficulty = spec_module.DEFAULT_DIFFICULTY
            bounded["difficulty"] = difficulty
        gate["check"] = bounded
    for branch in ("on_pass", "on_fail"):
        if branch in raw:
            # `authored=True`: this came out of a YAML file in the story's own
            # tree, not out of a model mid-turn. It widens the type allowlist by
            # the structural kinds -- `ending_lock` and `ending_intent` -- and
            # nothing else. Every magnitude clamp still applies, because a beat
            # being written greedily is a mistake a human makes too.
            gate[branch] = spec_module.clamp_outcome(raw[branch], adjustments, authored=True)
    return gate


def _bound_band(raw: dict[str, Any], adjustments: list[str]) -> dict[str, Any]:
    """
    Bound a band: the value it moves and the two ends of its range.

    The range itself is clamped by the story's per-scene ceiling, so ``favor:
    +5..400`` becomes ``+5..<ceiling>`` rather than being dropped -- the beat is
    still a good beat, it was just written greedily, which is the same argument
    ``engine/challenges/spec.py`` makes for clamping over rejection.
    """
    name = str(raw.get("value") or raw.get("name") or "").strip()
    band: dict[str, Any] = {"value": name, "text": _text(raw.get("text"), 200)}
    try:
        low = float(raw.get("min", 0))
    except (TypeError, ValueError):
        low = 0.0
    try:
        high = float(raw.get("max", low))
    except (TypeError, ValueError):
        high = low
    if high < low:
        low, high = high, low

    ceiling = spec_module.effect_ceilings().get(name)
    if ceiling is not None:
        for edge, value in (("min", low), ("max", high)):
            if abs(value) > ceiling:
                adjustments.append(
                    f"band {name} {edge} {value:+g} clamped to the story's ceiling {ceiling}"
                )
        low = max(-float(ceiling), min(float(ceiling), low))
        high = max(-float(ceiling), min(float(ceiling), high))

    band["min"] = low
    band["max"] = high
    return band


def _parse_deck(deck_id: str, data: dict[str, Any]) -> Deck:
    """Build a bounded Deck from a parsed file."""
    raw_cards = data.get("cards")
    rows = raw_cards if isinstance(raw_cards, list) else []
    if len(rows) > MAX_CARDS:
        logger.warning(
            "[deck] Deck has %d cards, keeping %d (deck=%s)", len(rows), MAX_CARDS, deck_id
        )
        rows = rows[:MAX_CARDS]

    try:
        draw = max(0, min(MAX_DRAW, int(data.get("draw", 0))))
    except (TypeError, ValueError):
        draw = 0

    cards: list[Card] = []
    seen: set[str] = set()
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        card_id = str(raw.get("id") or "").strip()
        if not card_id or card_id in seen:
            # A duplicate id would make `once` flags and rejection reasons
            # ambiguous, and the deck is small enough that this is a typo.
            logger.warning(
                "[deck] Card with a missing or duplicate id, skipped "
                "(deck=%s, id=%r)",
                deck_id,
                card_id,
            )
            continue
        seen.add(card_id)
        try:
            weight = max(0.0, float(raw.get("weight", 1.0)))
        except (TypeError, ValueError):
            weight = 1.0
        cards.append(
            Card(
                id=card_id,
                title=_text(raw.get("title"), 120),
                text=_text(raw.get("text")),
                required=bool(raw.get("required")),
                once=bool(raw.get("once")),
                weight=weight,
                tags=[str(t) for t in (raw.get("tags") or [])],
                when=raw.get("when"),
                beats=bound_beats(raw.get("beats"), deck_id, card_id),
            )
        )

    return Deck(id=deck_id, draw=draw, cards=cards, when=data.get("when"))


def load_deck(deck_id: str) -> Optional[Deck]:
    """
    Read one deck by id from the story's deck directory.

    Returns None when the story ships no such deck -- which is both shipped
    games today, and is not an error.
    """
    directory = _decks_dir()
    if directory is None:
        logger.debug("[deck] Story declares no decks (operation=load_deck)")
        return None
    path = directory / f"{deck_id}.yaml"
    try:
        mtime = path.stat().st_mtime
    except OSError:
        logger.debug("[deck] No deck file (operation=load_deck, path=%s)", path)
        return None
    data = _read_deck(str(path), mtime)
    if not data:
        return None
    return _parse_deck(deck_id, data)


def deck_ids() -> list[str]:
    """Every deck the running story ships."""
    directory = _decks_dir()
    if directory is None or not directory.is_dir():
        return []
    return sorted(p.stem for p in directory.glob("*.yaml"))


# ---------------------------------------------------------------------------
# Dealing
# ---------------------------------------------------------------------------


def _drawn_flag(deck_id: str, card_id: str) -> str:
    return f"{DRAWN_FLAG_PREFIX}{deck_id}_{card_id}"


def eligible_cards(
    state: GameState,
    deck: Deck,
    *,
    ledger: Optional[Any] = None,
) -> tuple[list[Card], dict[str, str]]:
    """
    Which pool cards could be dealt right now, and why the others could not.

    Returns:
        ``(eligible, rejected)``. The rejection reasons exist because a
        labyrinth that quietly never shows the Winter Mouth is indistinguishable
        from one where the Winter Mouth is broken.
    """
    from engine.game.quests import evaluate_condition

    eligible: list[Card] = []
    rejected: dict[str, str] = {}
    for card in deck.pool:
        if card.once and state.flags.get(_drawn_flag(deck.id, card.id)):
            rejected[card.id] = "already drawn"
            continue
        if card.weight <= 0:
            rejected[card.id] = "weight 0"
            continue
        if not evaluate_condition(state, card.when, ledger=ledger):
            rejected[card.id] = "conditions not met"
            continue
        eligible.append(card)
    return eligible, rejected


def draw(
    state: GameState,
    deck_id: str,
    *,
    count: Optional[int] = None,
    rng: Optional[random.Random] = None,
    ledger: Optional[Any] = None,
    mark_drawn: bool = True,
) -> Hand:
    """
    Deal a hand: every required card, plus ``count`` eligible pool cards.

    Args:
        state: Game state. Read for conditions; written only to record
            ``once`` cards, and only when ``mark_drawn``.
        deck_id: Deck to deal from.
        count: How many pool cards. Defaults to the deck's declared ``draw``.
        rng: Injected RNG, for tests. Otherwise the deterministic ``deck``
            stream, so the same seed lays out the same labyrinth.
        ledger: Optional StoryLedger, for conditions that read disposition.
        mark_drawn: Set the ``once`` flags. False lets a caller preview a hand
            without spending the cards -- which the mirror pool needs and the
            labyrinth must not use.

    Returns:
        A Hand. ``cards`` is required-first in authored order, then the drawn
        pool cards; a deck whose author put the Exit last gets the Exit last by
        writing it last, which is the ordering an author expects.
    """
    deck = load_deck(deck_id)
    if deck is None:
        return Hand(deck_id=deck_id, rejected={"deck": "not found"})

    from engine.game.quests import evaluate_condition

    if not evaluate_condition(state, deck.when, ledger=ledger):
        return Hand(deck_id=deck_id, rejected={"deck": "deck conditions not met"})

    wanted = deck.draw if count is None else int(count)
    wanted = max(0, min(MAX_DRAW, wanted))

    eligible, rejected = eligible_cards(state, deck, ledger=ledger)
    picked = _weighted_sample(eligible, wanted, rng or world_rng(state, RNG_DECK))
    for card in eligible:
        if card not in picked:
            rejected.setdefault(card.id, "not drawn")

    if mark_drawn:
        for card in picked:
            if card.once:
                effects_module.apply_effect(
                    state,
                    {"type": "flag", "flag": _drawn_flag(deck.id, card.id), "value": True},
                )

    # Required first, in authored order. See the module docstring: the spine is
    # not part of the draw and does not consume a slot.
    hand = Hand(
        deck_id=deck_id,
        cards=[*deck.required, *picked],
        rejected=rejected,
        eligible=[c.id for c in eligible],
    )
    logger.info(
        "[deck] Hand dealt (operation=draw, deck=%s, required=%d, drawn=%d, "
        "eligible=%d)",
        deck_id,
        len(deck.required),
        len(picked),
        len(eligible),
    )
    return hand


def _weighted_sample(pool: list[Card], count: int, rng: random.Random) -> list[Card]:
    """
    Draw without replacement, honouring weights.

    Sorted by id first so the draw does not depend on the order the YAML
    happened to be written in -- otherwise reordering a file silently changes
    every seed's labyrinth, and "the same seed replays identically" stops being
    true for a reason nobody would ever look for.
    """
    if count <= 0 or not pool:
        return []
    remaining = sorted(pool, key=lambda c: c.id)
    if count >= len(remaining):
        return remaining

    chosen: list[Card] = []
    for _ in range(count):
        total = sum(c.weight for c in remaining)
        if total <= 0:
            break
        roll = rng.random() * total
        upto = 0.0
        for card in remaining:
            upto += card.weight
            if roll <= upto:
                chosen.append(card)
                remaining.remove(card)
                break
    return chosen


# ---------------------------------------------------------------------------
# Per-beat resolution
# ---------------------------------------------------------------------------


@dataclass
class BeatResult:
    """How one beat resolved, as a receipt."""

    beat_id: str = ""
    mode: str = ""
    passed: bool = True
    value: Optional[float] = None
    band: Optional[tuple[float, float]] = None
    quality: Optional[float] = None
    roll: Optional[float] = None
    check: Optional[dict[str, Any]] = None
    effects: list[dict[str, Any]] = field(default_factory=list)
    text: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "beat_id": self.beat_id,
            "mode": self.mode,
            "passed": self.passed,
            "value": self.value,
            "band": list(self.band) if self.band else None,
            "quality": self.quality,
            "roll": self.roll,
            "check": self.check,
            "effects": list(self.effects),
            "text": self.text,
        }


def resolve_beat(
    state: GameState,
    beat: dict[str, Any],
    *,
    quality: Optional[float] = None,
    ledger: Optional[Any] = None,
    rng: Optional[random.Random] = None,
    by: str = "engine",
) -> BeatResult:
    """
    Resolve one authored beat -- a gate or a band.

    Args:
        state: Mutable game state.
        beat: A bounded beat from a loaded card.
        quality: For a ``band`` beat only: 0.0-1.0, how well the moment landed
            in the agent's judgement. Clamped. ``None`` resolves to the
            midpoint, so nothing here needs a model to run.
        ledger: Optional StoryLedger.
        rng: Injected RNG for a seeded hidden check. Otherwise the beat's
            declared stream.
        by: Writer id for the effects.

    Returns:
        A BeatResult. A beat with neither a gate nor a band is a text-only beat
        and resolves as a pass with no effects, because narration is a legal
        thing for a beat to be.
    """
    beat_id = str(beat.get("id") or "")
    if isinstance(beat.get("gate"), dict):
        return _resolve_gate(state, beat_id, beat["gate"], ledger=ledger, rng=rng, by=by)
    if isinstance(beat.get("band"), dict):
        return _resolve_band(state, beat_id, beat["band"], quality=quality, ledger=ledger, by=by)
    return BeatResult(beat_id=beat_id, mode="text", text=str(beat.get("text") or ""))


def _resolve_gate(
    state: GameState,
    beat_id: str,
    gate: dict[str, Any],
    *,
    ledger: Optional[Any],
    rng: Optional[random.Random],
    by: str,
) -> BeatResult:
    """
    A hard threshold, a seeded hidden check, or a skill check. Never a guess.

    A gate with both a ``when`` and a ``check`` requires both: the threshold is
    the price of admission and the check is whether it went well. "Knowledge >=
    35 AND you did not fumble the recitation" is one beat, not two.
    """
    from engine.game.quests import evaluate_condition

    result = BeatResult(beat_id=beat_id, mode="gate")
    passed = True

    if "when" in gate:
        passed = evaluate_condition(state, gate.get("when"), ledger=ledger)

    check = gate.get("check")
    if passed and isinstance(check, dict):
        if check.get("skill"):
            from engine.game import checks as checks_module

            # Routed through checks.resolve for the reason
            # engine/challenges/runner.py gives: a private formula would be the
            # one place in the game where being wounded or hungry did not
            # matter, and the itemised modifier receipt would not exist.
            outcome = checks_module.resolve(
                state,
                str(check["skill"]),
                str(check.get("difficulty") or spec_module.DEFAULT_DIFFICULTY),
                rng=rng,
                ledger=ledger,
            )
            result.check = {
                "skill": outcome.skill,
                "difficulty": outcome.difficulty,
                "dc": outcome.dc,
                "total": outcome.total,
                "margin": outcome.margin,
                "degree": outcome.degree,
                "summary": outcome.summary,
            }
            passed = outcome.success
        elif "chance" in check:
            stream = str(check.get("stream") or RNG_BEAT)
            draw_rng = rng if rng is not None else world_rng(state, stream)
            roll = draw_rng.random()
            result.roll = round(roll, 4)
            passed = roll < float(check["chance"])

    result.passed = passed
    branch = gate.get("on_pass" if passed else "on_fail") or {}
    result.text = str(branch.get("text") or "")
    result.effects = effects_module.apply_effects(
        state, branch.get("effects") or [], ledger=ledger, by=by, turn=state.turn_number
    )
    return result


def _resolve_band(
    state: GameState,
    beat_id: str,
    band: dict[str, Any],
    *,
    quality: Optional[float],
    ledger: Optional[Any],
    by: str,
) -> BeatResult:
    """
    ``favor: +5..12`` -- the engine owns the range, the agent picks inside it.

    The award is rounded to an integer for a bounded value, because a meter the
    player reads as a rose opening should not move by 8.3333. Unbounded values
    keep their precision (a story's time debt may legitimately carry fractional
    shards).
    """
    name = str(band.get("value") or "")
    low = float(band.get("min", 0.0))
    high = float(band.get("max", low))

    judged = DEFAULT_QUALITY if quality is None else max(0.0, min(1.0, float(quality)))
    raw = low + (high - low) * judged
    award = round(raw) if abs(high - low) >= 1 else round(raw, 3)

    result = BeatResult(
        beat_id=beat_id,
        mode="band",
        band=(low, high),
        quality=judged,
        value=award,
        text=str(band.get("text") or ""),
    )
    if not name:
        logger.warning("[deck] Band beat names no value (operation=resolve_beat, beat=%s)", beat_id)
        return result

    result.effects = [
        effects_module.apply_effect(
            state,
            {"type": "value", "name": name, "delta": award, "why": f"band:{beat_id}"},
            ledger=ledger,
            by=by,
            turn=state.turn_number,
        )
    ]
    return result


#: Cards tagged this way are a DECISION: their beats are alternatives and
#: exactly one resolves. The counterpart tag is ``sequence``, where the beats are
#: steps and all of them resolve in order. Content already declares one or the
#: other on every card (tests/test_wicked_garden_scenes.py asserts it); this is
#: the engine end of that contract.
MENU_TAG = "menu"


def chosen_beats(card: Card, chosen: Optional[str] = None) -> list[dict[str, Any]]:
    """
    The beats a resolution should actually apply.

    A ``sequence`` card returns all of them. A ``menu`` card returns exactly one
    -- the beat named by ``chosen``, because its beats are branches of a single
    question. Resolving a menu card whole applies every branch at once, which on
    The Wicked Garden's first morning means the player both looks at their
    mortal home and refuses to, taking the autonomy for one and the corruption
    for the other.

    With no ``chosen`` on a menu card there is no honest engine answer -- the
    choice belongs to the player. The first beat is taken and the fallback is
    logged at WARNING, on the grounds that resolving *something* keeps a scene
    from happening with no mechanical trace at all, and a silent zero-effect
    card is the harder failure to ever notice.
    """
    if MENU_TAG not in card.tags or not card.beats:
        return list(card.beats)

    if chosen:
        for beat in card.beats:
            if str(beat.get("id")) == chosen:
                return [beat]
        logger.warning(
            "[deck] Chosen beat not on card (operation=resolve_card, card=%s, beat=%s)",
            card.id,
            chosen,
        )
    else:
        logger.warning(
            "[deck] Menu card resolved with no choice (operation=resolve_card, card=%s)",
            card.id,
        )
    return [card.beats[0]]


def resolve_card(
    state: GameState,
    card: Card,
    *,
    chosen: Optional[str] = None,
    qualities: Optional[dict[str, float]] = None,
    ledger: Optional[Any] = None,
    by: str = "engine",
) -> list[BeatResult]:
    """
    Resolve a card's beats, in authored order.

    Args:
        chosen: on a ``menu`` card, the id of the beat the player picked.
            Ignored on a ``sequence`` card, whose beats are steps rather than
            alternatives. See :func:`chosen_beats`.
        qualities: beat id -> 0.0-1.0 judgement, for band beats. Missing ids
            resolve to the midpoint.
    """
    judged = qualities or {}
    return [
        resolve_beat(state, beat, quality=judged.get(str(beat.get("id"))), ledger=ledger, by=by)
        for beat in chosen_beats(card, chosen)
    ]


__all__ = [
    "DEFAULT_QUALITY",
    "DRAWN_FLAG_PREFIX",
    "MAX_BEATS",
    "MAX_CARDS",
    "MAX_DRAW",
    "MENU_TAG",
    "BeatResult",
    "Card",
    "Deck",
    "Hand",
    "chosen_beats",
    "deck_ids",
    "draw",
    "eligible_cards",
    "load_deck",
    "resolve_beat",
    "resolve_card",
]
