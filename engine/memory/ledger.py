"""
Story Ledger
============

The engine's memory of the fiction.

The Storyteller had none. Its message array was always exactly
``[system, user]``, so everything it narrated was generated and immediately
discarded: it could not know what it said last turn, which choice the player
made, what any NPC promised, or that the player had met them at all. The world
had amnesia every ten seconds.

The engine models mechanics well and fiction not at all. This closes that gap
without handing narrative authority to the model:

  - The model PROPOSES ledger deltas as part of its structured output.
  - The engine VALIDATES and applies them.
  - Engine events (tool receipts, quests, reputation) write directly and are
    never overridden by a proposal.

``names`` matters more than it looks. It is what stops the model renaming the
innkeeper every third turn.

Version: v0.2.0 [2026-08-07]
"""

from __future__ import annotations

import hashlib
import logging
import re
from collections import deque
from dataclasses import asdict, dataclass, field, fields
from typing import Any, Iterable, Optional

logger = logging.getLogger(__name__)

# How much a fact's weight decays per in-game day. Facts fade rather than
# vanish so an old detail can still surface if nothing newer crowds it out.
DECAY_PER_DAY = 0.97
ARCHIVE_BELOW = 0.25

MAX_FACTS_PER_TURN = 3
MAX_FACT_CHARS = 140
MAX_DISPOSITION_STEP = 5
TURN_BUFFER_SIZE = 6

SOURCE_ENGINE = "engine"
SOURCE_LLM = "llm"
SOURCE_PLAYER = "player"


def _coerce(cls: type, raw: Any) -> Optional[Any]:
    """Build a dataclass from a dict, ignoring unknown keys. None if unusable."""
    if not isinstance(raw, dict):
        return None
    known = {f.name for f in fields(cls)}
    try:
        return cls(**{k: v for k, v in raw.items() if k in known})
    except TypeError:
        return None


def _coerce_list(cls: type, raw: Any) -> list[Any]:
    """
    Coerce a list of dicts, dropping anything unusable.

    Guards the type as well as the contents: a stray string here would
    otherwise iterate into one entry per character.
    """
    if not isinstance(raw, list):
        return []
    return [item for item in (_coerce(cls, r) for r in raw) if item is not None]


def _norm(text: str) -> str:
    """Normalized form used for dedupe."""
    return re.sub(r"[^a-z0-9 ]+", "", text.lower()).strip()


def fact_key(text: str) -> str:
    return hashlib.blake2b(_norm(text).encode("utf-8"), digest_size=8).hexdigest()


@dataclass
class LedgerFact:
    """One remembered detail about the world."""

    id: str
    text: str
    kind: str = "fact"  # fact | name | secret | event
    subject_id: str = ""
    turn: int = 0
    day: int = 0
    weight: float = 1.0
    source: str = SOURCE_LLM

    @property
    def archived(self) -> bool:
        return self.weight < ARCHIVE_BELOW


@dataclass
class Promise:
    """An obligation in either direction. The spine of consequence."""

    id: str
    text: str
    from_id: str = "player"
    to_id: str = ""
    due_day: Optional[int] = None
    status: str = "open"  # open | kept | broken | expired
    turn_made: int = 0


@dataclass
class NPCRelation:
    """
    What one NPC feels and knows about the player.

    ``disposition`` is the single home for this number. It was previously split
    between a never-written ``state.reputations`` and a never-written
    ``assistant_mind.trust_level``.
    """

    npc_id: str
    disposition: int = 0  # -100..100
    trust: int = 0
    met: bool = False
    first_met_day: int = 0
    last_seen_day: int = 0
    last_seen_location: str = ""
    known_facts: list[str] = field(default_factory=list)
    debts: list[str] = field(default_factory=list)
    owed: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)


@dataclass
class TurnRecord:
    """One exchange kept verbatim in the rolling buffer."""

    turn: int
    day: int
    location_id: str
    player_action: str
    narration: str
    outcomes: list[str] = field(default_factory=list)


@dataclass
class StoryLedger:
    """Engine-owned narrative memory."""

    facts: list[LedgerFact] = field(default_factory=list)
    promises: list[Promise] = field(default_factory=list)
    relations: dict[str, NPCRelation] = field(default_factory=dict)
    names: dict[str, str] = field(default_factory=dict)
    open_threads: list[str] = field(default_factory=list)
    summary: str = ""
    summary_through_turn: int = 0
    turn_buffer: deque[TurnRecord] = field(
        default_factory=lambda: deque(maxlen=TURN_BUFFER_SIZE)
    )

    # -- facts -----------------------------------------------------------

    def add_fact(
        self,
        text: str,
        *,
        kind: str = "fact",
        subject_id: str = "",
        turn: int = 0,
        day: int = 0,
        source: str = SOURCE_LLM,
    ) -> Optional[LedgerFact]:
        """Record a fact, ignoring near-duplicates. Returns None if dropped."""
        text = text.strip()[:MAX_FACT_CHARS]
        if not text:
            return None

        key = fact_key(text)
        for existing in self.facts:
            if existing.id == key:
                # Re-stating a fact refreshes it rather than duplicating it.
                existing.weight = max(existing.weight, 1.0)
                existing.turn = turn or existing.turn
                return existing

        fact = LedgerFact(
            id=key,
            text=text,
            kind=kind,
            subject_id=subject_id,
            turn=turn,
            day=day,
            source=source,
            weight=1.0,
        )
        self.facts.append(fact)
        if subject_id and subject_id in self.relations:
            self.relations[subject_id].known_facts.append(key)
        return fact

    def decay(self, days: float) -> None:
        """Age facts. Engine-sourced facts hold a floor; they are not opinions."""
        if days <= 0:
            return
        factor = DECAY_PER_DAY ** days
        for fact in self.facts:
            if fact.source == SOURCE_ENGINE:
                fact.weight = max(0.5, fact.weight * factor)
            else:
                fact.weight *= factor

    def salient_facts(self, *, limit: int = 8, subject_ids: Iterable[str] = ()) -> list[LedgerFact]:
        """Highest-weight live facts, biased toward the named subjects."""
        subjects = set(subject_ids)

        def rank(fact: LedgerFact) -> tuple[int, float, int]:
            return (
                1 if fact.subject_id in subjects else 0,
                fact.weight,
                fact.turn,
            )

        live = [f for f in self.facts if not f.archived]
        return sorted(live, key=rank, reverse=True)[:limit]

    # -- names -----------------------------------------------------------

    def remember_name(self, name: str, gloss: str) -> None:
        """Pin a proper noun the model invented so it stays that name."""
        name = name.strip()
        if name and name not in self.names:
            self.names[name] = gloss.strip()[:MAX_FACT_CHARS]

    # -- relations -------------------------------------------------------

    def relation(self, npc_id: str) -> NPCRelation:
        """Get or create the relation record for an NPC."""
        rel = self.relations.get(npc_id)
        if rel is None:
            rel = NPCRelation(npc_id=npc_id)
            self.relations[npc_id] = rel
        return rel

    def meet(self, npc_id: str, *, day: int, location_id: str) -> NPCRelation:
        rel = self.relation(npc_id)
        if not rel.met:
            rel.met = True
            rel.first_met_day = day
        rel.last_seen_day = day
        rel.last_seen_location = location_id
        return rel

    def adjust_disposition(self, npc_id: str, delta: int, *, clamp_step: bool = True) -> int:
        """
        Move an NPC's disposition.

        Model-proposed deltas are clamped per turn: affection should be earned
        over a scene, not granted in one flattering sentence.
        """
        if clamp_step:
            delta = max(-MAX_DISPOSITION_STEP, min(MAX_DISPOSITION_STEP, delta))
        rel = self.relation(npc_id)
        rel.disposition = max(-100, min(100, rel.disposition + delta))
        return rel.disposition

    # -- promises --------------------------------------------------------

    def add_promise(
        self,
        text: str,
        *,
        from_id: str = "player",
        to_id: str = "",
        due_day: Optional[int] = None,
        turn: int = 0,
    ) -> Promise:
        promise = Promise(
            id=fact_key(f"{from_id}->{to_id}:{text}"),
            text=text.strip()[:MAX_FACT_CHARS],
            from_id=from_id,
            to_id=to_id,
            due_day=due_day,
            turn_made=turn,
        )
        for existing in self.promises:
            if existing.id == promise.id:
                return existing
        self.promises.append(promise)
        if to_id:
            self.relation(to_id).owed.append(promise.id)
        return promise

    def resolve_promise(self, promise_id: str, status: str) -> Optional[Promise]:
        for promise in self.promises:
            if promise.id == promise_id:
                promise.status = status
                return promise
        return None

    def open_promises(self) -> list[Promise]:
        return [p for p in self.promises if p.status == "open"]

    def expire_promises(self, current_day: int) -> list[Promise]:
        """Mark overdue promises broken. Silence is an answer too."""
        broken = []
        for promise in self.promises:
            if (
                promise.status == "open"
                and promise.due_day is not None
                and current_day > promise.due_day
            ):
                promise.status = "broken"
                broken.append(promise)
        return broken

    # -- turn buffer -----------------------------------------------------

    def record_turn(self, record: TurnRecord) -> Optional[TurnRecord]:
        """
        Append a turn. Returns the record evicted from the buffer, if any.

        The evicted record is what the summarizer folds into the running
        summary, so nothing leaves the buffer without being remembered.
        """
        evicted = None
        if len(self.turn_buffer) == self.turn_buffer.maxlen:
            evicted = self.turn_buffer[0]
        self.turn_buffer.append(record)
        return evicted

    # -- serialization ---------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "facts": [asdict(f) for f in self.facts],
            "promises": [asdict(p) for p in self.promises],
            "relations": {k: asdict(v) for k, v in self.relations.items()},
            "names": dict(self.names),
            "open_threads": list(self.open_threads),
            "summary": self.summary,
            "summary_through_turn": self.summary_through_turn,
            "turn_buffer": [asdict(t) for t in self.turn_buffer],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StoryLedger:
        if not isinstance(data, dict):
            return cls()
        raw_relations = data.get("relations")
        relations = {}
        if isinstance(raw_relations, dict):
            for key, value in raw_relations.items():
                coerced = _coerce(NPCRelation, value)
                if coerced is not None:
                    relations[str(key)] = coerced

        raw_names = data.get("names")
        ledger = cls(
            facts=_coerce_list(LedgerFact, data.get("facts")),
            promises=_coerce_list(Promise, data.get("promises")),
            relations=relations,
            names=dict(raw_names) if isinstance(raw_names, dict) else {},
            open_threads=[str(t) for t in (data.get("open_threads") or [])]
            if isinstance(data.get("open_threads"), list)
            else [],
            summary=str(data.get("summary", "") or ""),
            summary_through_turn=int(data.get("summary_through_turn", 0) or 0),
        )
        ledger.turn_buffer = deque(
            _coerce_list(TurnRecord, data.get("turn_buffer")),
            maxlen=TURN_BUFFER_SIZE,
        )
        return ledger


def apply_ledger_delta(
    ledger: StoryLedger,
    delta: dict[str, Any],
    *,
    turn: int,
    day: int,
    known_npc_ids: Iterable[str] = (),
) -> dict[str, Any]:
    """
    Validate and apply a model-proposed ledger delta.

    The model may observe the fiction; it may not rewrite the record. Every
    proposal is bounded here:

      - at most MAX_FACTS_PER_TURN facts, each truncated and deduped
      - subjects must resolve to an NPC the engine knows about
      - disposition moves are clamped per turn

    Returns a report of what was accepted, for logging and tests.
    """
    known = set(known_npc_ids)
    accepted: dict[str, Any] = {"facts": [], "names": [], "promises": [], "dispositions": {}}
    if not isinstance(delta, dict):
        return accepted

    for raw in (delta.get("facts") or [])[:MAX_FACTS_PER_TURN]:
        text, subject = (raw, "") if isinstance(raw, str) else (
            str(raw.get("text", "")),
            str(raw.get("subject_id", "")),
        )
        if subject and subject not in known:
            logger.debug(
                "[memory] Dropping fact for unknown subject "
                "(operation=apply_ledger_delta, subject=%s)",
                subject,
            )
            subject = ""
        fact = ledger.add_fact(
            text, subject_id=subject, turn=turn, day=day, source=SOURCE_LLM
        )
        if fact is not None:
            accepted["facts"].append(fact.text)

    for name, gloss in (delta.get("names") or {}).items():
        ledger.remember_name(str(name), str(gloss))
        accepted["names"].append(str(name))

    for raw in (delta.get("promises") or [])[:1]:
        if not isinstance(raw, dict):
            continue
        to_id = str(raw.get("to_id", ""))
        if to_id and to_id not in known:
            continue
        promise = ledger.add_promise(
            str(raw.get("text", "")),
            from_id=str(raw.get("from_id", "player")),
            to_id=to_id,
            due_day=raw.get("due_day"),
            turn=turn,
        )
        accepted["promises"].append(promise.text)

    for npc_id, raw_delta in (delta.get("npc_disposition") or {}).items():
        if npc_id not in known:
            continue
        try:
            value = int(raw_delta)
        except (TypeError, ValueError):
            continue
        accepted["dispositions"][npc_id] = ledger.adjust_disposition(npc_id, value)

    return accepted
