"""
Agent Plans
===========

What an agent PROPOSES for a turn, before anything is committed.

THE SHAPE THIS REPLACES. Today the two agents are strictly sequential and
one-directional: the Storyteller runs to completion and commits, then the
Assistant is invoked with the final narration string as its only input. Neither
produces a plan, neither can object to the other, and there is no shared
per-turn artifact besides already-committed ``GameState``. The Storyteller never
sees the companion's output at all -- not this turn, not next turn, because the
companion's line is never written to the ledger.

That is fine for a narrator plus a hint system. It cannot express a second
character who wants something, who may write shared state under conditions, who
may lie in dialogue while the record tracks the truth, and whose intent has to
be reconciled with the world's before either of them speaks.

So: each agent emits an ``AgentPlan``, a negotiation phase reconciles them, and
ONE atomic commit follows. A plan is inert -- constructing one changes nothing.
That is the property that makes negotiation possible at all, because a proposal
that has already taken effect cannot be argued with.

WHY EFFECTS ARE PROPOSED, NOT APPLIED. ``effects.apply_effect`` remains the only
writer of game state (CLAUDE.md rule 3). A plan carries effect REQUESTS; the
commit phase runs them through the real writer, with the proposing agent
recorded, so the state store's per-agent ACL and write journal see who asked.
An agent cannot reach around this by constructing a plan.

Version: v0.1.0 [2026-08-08]
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)

#: What an agent is trying to accomplish this turn. Deliberately coarse: the
#: negotiator reasons about intents, not about prose.
INTENT_NARRATE = "narrate"
INTENT_SPEAK = "speak"
INTENT_INTERRUPT = "interrupt"
INTENT_OFFER = "offer"
INTENT_WITHHOLD = "withhold"
INTENT_SILENT = "silent"


@dataclass
class ProposedEffect:
    """
    One state change an agent wants, not yet applied.

    Mirrors the effect dicts ``engine/game/effects.py`` already accepts, so the
    commit phase can hand them straight to the existing single writer rather
    than translating between two vocabularies.
    """

    kind: str
    payload: dict[str, Any] = field(default_factory=dict)
    #: Why the agent wants it. Carried into the state store's write journal --
    #: an unexplained write is one nobody can audit later.
    reason: str = ""

    def to_effect(self) -> dict[str, Any]:
        """The dict shape ``apply_effect`` expects."""
        return {"type": self.kind, **self.payload}

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "payload": dict(self.payload), "reason": self.reason}


@dataclass
class ProposedChoice:
    """
    A choice an agent wants offered to the player.

    ``whisper`` is the one-line consequence hint -- "She will like this." /
    "This spends the Briar Key." Choices are jointly authored: today they are
    written solely by the narrator and the companion never sees them, so a
    companion who just warned you about a door cannot put "not that door" on the
    table.
    """

    text: str
    id: str = ""
    hint: str = ""
    whisper: str = ""
    #: Which agent wants this choice offered. Set by the planner, used by the
    #: negotiator when two agents propose overlapping options.
    source: str = ""

    def to_dict(self) -> dict[str, Any]:
        row = {"id": self.id, "text": self.text}
        if self.hint:
            row["hint"] = self.hint
        if self.whisper:
            row["whisper"] = self.whisper
        return row


@dataclass
class AgentPlan:
    """
    One agent's proposal for one turn.

    Attributes:
        agent: Who is proposing. Matches the ids the skill registry and the
            state schema's ``owners`` use, so a plan can be checked against
            both.
        intent: Coarse goal; what the negotiator reasons about.
        effects: State changes requested, applied only at commit.
        choices: Options this agent wants offered.
        tools: Skill calls requested, checked against this agent's ACL before
            dispatch rather than after.
        beat: What the agent wants to happen, in one line, for the negotiator
            and the eventual narration prompt. NOT player-facing prose.
        private: Reasoning the agent keeps. Never rendered, never given to the
            other agent -- this is where a character's real motive lives, and
            handing it over would collapse the knowledge partition that makes
            two agents worth having.
        confidence: How strongly the agent wants this, 0..1. Used to break ties
            the resolution rules do not cover.
        speaks_as: Voice id, so a plan that tries to speak as someone it does
            not own can be refused rather than merely discouraged by prompt.
    """

    agent: str
    intent: str = INTENT_SILENT
    effects: list[ProposedEffect] = field(default_factory=list)
    choices: list[ProposedChoice] = field(default_factory=list)
    tools: list[dict[str, Any]] = field(default_factory=list)
    beat: str = ""
    private: str = ""
    confidence: float = 0.5
    speaks_as: str = ""
    #: Free-form extras a story's pipeline may attach. Kept so a story can carry
    #: something the base plan has not learned about without subclassing.
    extras: dict[str, Any] = field(default_factory=dict)

    @property
    def silent(self) -> bool:
        return self.intent == INTENT_SILENT and not self.effects and not self.choices

    def to_dict(self, *, include_private: bool = False) -> dict[str, Any]:
        """
        Serialisable form.

        ``private`` is withheld unless explicitly asked for. The default is the
        safe one because this dict is what gets logged, put in a turn journal
        and shipped to telemetry -- a private motive that leaks into any of
        those is a private motive the other agent can eventually read.
        """
        out: dict[str, Any] = {
            "agent": self.agent,
            "intent": self.intent,
            "effects": [e.to_dict() for e in self.effects],
            "choices": [c.to_dict() for c in self.choices],
            "tools": list(self.tools),
            "beat": self.beat,
            "confidence": round(float(self.confidence), 3),
            "speaks_as": self.speaks_as,
        }
        if include_private:
            out["private"] = self.private
        return out


def plan_schema(agent: str, *, voices: tuple[str, ...] = ()) -> dict[str, Any]:
    """
    JSON schema an agent fills in to emit a plan.

    Built per agent rather than shared: ``speaks_as`` is constrained to the
    voices that agent actually owns, so a character agent cannot propose
    speaking as someone else's NPC. That is the same trick the existing turn
    schema uses for ``npc_voices`` -- enumerating the NPCs actually present
    makes an off-scene character unsampleable rather than merely discouraged.

    Args:
        agent: Agent id, for the description text.
        voices: Voice ids this agent owns. Omitted entirely when empty, because
            an empty enum matches nothing and would make the field unfillable.

    Returns:
        A JSON schema dict for ``response_format``.
    """
    speaks_as: dict[str, Any] = {"type": "string"}
    if voices:
        speaks_as = {"type": "string", "enum": list(voices)}

    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["intent", "beat"],
        "properties": {
            "intent": {
                "type": "string",
                "enum": [
                    INTENT_NARRATE,
                    INTENT_SPEAK,
                    INTENT_INTERRUPT,
                    INTENT_OFFER,
                    INTENT_WITHHOLD,
                    INTENT_SILENT,
                ],
                "description": f"What {agent} wants to do this turn.",
            },
            "beat": {
                "type": "string",
                "maxLength": 240,
                "description": "What should happen, in one line. Not prose for the player.",
            },
            "private": {
                "type": "string",
                "maxLength": 240,
                "description": "Your reasoning. The player and the other agent never see this.",
            },
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "speaks_as": speaks_as,
            "choices": {
                "type": "array",
                "maxItems": 4,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["text"],
                    "properties": {
                        "text": {"type": "string", "maxLength": 120},
                        "whisper": {
                            "type": "string",
                            "maxLength": 80,
                            "description": "One line on what it costs. Never name an ending.",
                        },
                        "hint": {
                            "type": "string",
                            "enum": ["safe", "risky", "costly", "unknown"],
                        },
                    },
                },
            },
        },
    }


def parse_plan(agent: str, raw: dict[str, Any]) -> AgentPlan:
    """
    Build a plan from a model's structured output.

    Tolerant of shape, strict about ownership: unknown intents fall back to
    silence rather than raising, because a malformed plan must cost the agent
    its turn and not the player's. Effects are NOT read from the model here --
    an agent requests state changes through its declared tools, which are
    already ACL-checked, so a plan cannot smuggle in an effect the agent has no
    permission to ask for.
    """
    if not isinstance(raw, dict):
        return AgentPlan(agent=agent)

    intent = str(raw.get("intent") or INTENT_SILENT)
    if intent not in {
        INTENT_NARRATE, INTENT_SPEAK, INTENT_INTERRUPT,
        INTENT_OFFER, INTENT_WITHHOLD, INTENT_SILENT,
    }:
        logger.debug(
            "[plan] Unknown intent, treating as silent (agent=%s, intent=%s)",
            agent,
            intent,
        )
        intent = INTENT_SILENT

    choices: list[ProposedChoice] = []
    for row in raw.get("choices") or []:
        if not isinstance(row, dict):
            continue
        text = str(row.get("text") or "").strip()
        if not text:
            continue
        choices.append(
            ProposedChoice(
                text=text,
                hint=str(row.get("hint") or ""),
                whisper=str(row.get("whisper") or ""),
                source=agent,
            )
        )

    try:
        confidence = min(1.0, max(0.0, float(raw.get("confidence", 0.5))))
    except (TypeError, ValueError):
        confidence = 0.5

    return AgentPlan(
        agent=agent,
        intent=intent,
        choices=choices,
        beat=str(raw.get("beat") or "").strip(),
        private=str(raw.get("private") or "").strip(),
        confidence=confidence,
        speaks_as=str(raw.get("speaks_as") or ""),
    )


__all__ = [
    "INTENT_INTERRUPT",
    "INTENT_NARRATE",
    "INTENT_OFFER",
    "INTENT_SILENT",
    "INTENT_SPEAK",
    "INTENT_WITHHOLD",
    "AgentPlan",
    "ProposedChoice",
    "ProposedEffect",
    "parse_plan",
    "plan_schema",
]
